"""
NarrativeInjectionEngine — N3: Narrative Injection Point Detector.

Finds the exact post + comment where each attack narrative was
FIRST introduced, and tracks how far it propagated across posts.

Algorithm:
  1. Filter comments that contain attack vocabulary (same lexicon as
     comment_bot_detector — cfg["narrative_injection"]["patterns_file"]).
  2. TF-IDF vectorize attack comments (pure Python, no ML deps).
  3. Greedy cosine-similarity clustering — each cluster is one
     narrative theme.
  4. Sort each cluster by timestamp: first entry = injection point.
  5. Score by cluster size + post spread (large + wide = high-impact
     narrative seeding operation).
  6. Export top N injections + propagation chains for the top 5.

All parameters read from cfg["narrative_injection"]. Zero hardcoded values.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).parent.parent


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class NarrativeInjection:
    narrative_id:      str              # NARR-001
    top_terms:         list[str]        # defining keywords of this narrative
    seed_account:      str              # account that introduced it first
    seed_post_url:     str
    seed_comment_text: str              # first 120 chars
    seed_timestamp:    Optional[datetime]
    propagation_count: int              # total comments in this narrative cluster
    propagation_posts: int              # unique posts it reached
    co_injectors:      list[str]        # other accounts in first 3 comments
    injection_score:   int              # 0-100


@dataclass
class PropagationStep:
    ts:           Optional[str]    # ISO string or None
    actor:        str
    post_url:     str
    text_excerpt: str


@dataclass
class PropagationChain:
    narrative_id: str
    steps:        list[PropagationStep]


@dataclass
class NarrativeInjectionReport:
    injections:           list[NarrativeInjection]
    top_injectors:        list[tuple[str, int]]    # (actor, count) sorted desc
    most_propagated:      list[NarrativeInjection]
    propagation_chains:   list[PropagationChain]
    total_narratives:     int
    total_attack_comments: int
    injection_score:      float
    summary:              str


# ── Engine ─────────────────────────────────────────────────────────────────────

class NarrativeInjectionEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("narrative_injection", {})
        self.min_propagation  = c.get("min_propagation_count",    2)
        self.min_score        = c.get("min_injection_score",      40)
        self.top_terms_n      = c.get("top_terms_per_narrative",   6)
        self.max_narratives   = c.get("max_narratives",           20)
        self.sim_threshold    = c.get("similarity_threshold",     0.35)
        self.min_cluster_size = c.get("min_cluster_size",          2)
        self.min_comment_len  = c.get("min_comment_len",          10)
        self.max_comments     = c.get("max_comments",           5000)
        self.min_term_len     = c.get("min_term_len",              3)
        self.chain_max        = c.get("chain_max_entries",        10)
        self.top_inj_out      = c.get("top_injectors_output",     15)
        sw = c.get("score_weights", {})
        self._sw_size_mult    = sw.get("cluster_size_multiplier",  5.0)
        self._sw_spread_mult  = sw.get("spread_multiplier",        8.0)
        self._sw_max_size     = sw.get("max_size_score",          50.0)
        self._sw_max_spread   = sw.get("max_spread_score",        50.0)
        self._attack_words    = self._load_flat(
            c.get("patterns_file", "config/patterns/attack_words.json"))
        self._stopwords       = self._load_flat(
            c.get("stopwords_file", "config/patterns/stopwords_es_en.json"))

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze(
        self,
        scraped_results: list[dict],
        posts: list[dict] | None = None,
    ) -> NarrativeInjectionReport:
        attack_comments = self._collect_attack(scraped_results)
        if not attack_comments:
            return self._empty_report()

        vectors  = self._vectorize(attack_comments)
        raw_clusters = self._cluster(attack_comments, vectors)

        id_to_cluster: dict[str, list[dict]] = {}
        all_injections: list[NarrativeInjection] = []
        for cid, cluster in enumerate(raw_clusters, 1):
            if len(cluster) < self.min_cluster_size:
                continue
            inj = self._build_injection(cid, cluster)
            id_to_cluster[inj.narrative_id] = cluster
            all_injections.append(inj)

        injections = sorted(
            [i for i in all_injections if i.injection_score >= self.min_score],
            key=lambda i: -i.injection_score,
        )[:self.max_narratives]

        chains     = [self._build_chain(inj, id_to_cluster[inj.narrative_id])
                      for inj in injections[:5]]
        top_inj    = self._top_injectors(injections)
        most_prop  = sorted(injections, key=lambda i: -i.propagation_count)[:5]
        score      = self._overall_score(injections, attack_comments)
        summary    = self._build_summary(injections, top_inj, score, attack_comments)

        return NarrativeInjectionReport(
            injections=injections,
            top_injectors=top_inj,
            most_propagated=most_prop,
            propagation_chains=chains,
            total_narratives=len(injections),
            total_attack_comments=len(attack_comments),
            injection_score=score,
            summary=summary,
        )

    # ── Collection ─────────────────────────────────────────────────────────────

    def _collect_attack(self, results: list[dict]) -> list[dict]:
        comments: list[dict] = []
        for r in results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                text = (c.get("text") or "").strip()
                if len(text) < self.min_comment_len:
                    continue
                if not self._is_attack(text):
                    continue
                ts: Optional[datetime] = None
                ts_str = c.get("timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        pass
                comments.append({
                    "actor":    c.get("author", "?"),
                    "text":     text,
                    "ts":       ts,
                    "post_url": url,
                })
                if len(comments) >= self.max_comments:
                    return comments
        return comments

    def _is_attack(self, text: str) -> bool:
        lo = text.lower()
        return any(w in lo for w in self._attack_words)

    # ── TF-IDF ─────────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        return [
            t for t in re.findall(r"[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]+", text.lower())
            if len(t) >= self.min_term_len and t not in self._stopwords
        ]

    def _vectorize(self, comments: list[dict]) -> list[dict[str, float]]:
        corpus  = [self._tokenize(c["text"]) for c in comments]
        n       = len(corpus)
        tf_vecs = [Counter(doc) for doc in corpus]
        df: Counter = Counter()
        for doc in corpus:
            for term in set(doc):
                df[term] += 1
        idf = {t: math.log((n + 1) / (f + 1)) + 1.0 for t, f in df.items()}
        vecs: list[dict[str, float]] = []
        for tf in tf_vecs:
            total = sum(tf.values()) or 1
            vec   = {t: (cnt / total) * idf.get(t, 1.0) for t, cnt in tf.items()}
            norm  = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            vecs.append({t: v / norm for t, v in vec.items()})
        return vecs

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        return sum(a.get(t, 0.0) * v for t, v in b.items())

    # ── Greedy clustering ───────────────────────────────────────────────────────

    def _cluster(
        self,
        comments: list[dict],
        vectors:  list[dict[str, float]],
    ) -> list[list[dict]]:
        assigned: list[int] = [-1] * len(comments)
        clusters: list[list[int]] = []

        for i in range(len(comments)):
            best_c, best_sim = -1, 0.0
            for c_id, cluster in enumerate(clusters):
                sim = self._cosine(vectors[i], vectors[cluster[0]])
                if sim > best_sim:
                    best_sim, best_c = sim, c_id
            if best_sim >= self.sim_threshold:
                clusters[best_c].append(i)
                assigned[i] = best_c
            else:
                assigned[i] = len(clusters)
                clusters.append([i])

        result: list[list[dict]] = []
        _max_ts = datetime.max
        for idxs in clusters:
            cluster_comments = [comments[i] for i in idxs]
            cluster_comments.sort(
                key=lambda c: (c["ts"] is None, c["ts"] or _max_ts)
            )
            result.append(cluster_comments)
        return result

    # ── Injection building ──────────────────────────────────────────────────────

    def _build_injection(self, cid: int, cluster: list[dict]) -> NarrativeInjection:
        seed      = cluster[0]
        posts_set = {c["post_url"] for c in cluster}
        all_text  = " ".join(c["text"] for c in cluster)
        top_terms = [t for t, _ in Counter(self._tokenize(all_text)).most_common(self.top_terms_n)]
        co_inj    = [c["actor"] for c in cluster[1:3] if c["actor"] != seed["actor"]]

        size_sc   = min(self._sw_max_size,
                        math.log(max(len(cluster), 1) + 1) * self._sw_size_mult * 10)
        spread_sc = min(self._sw_max_spread, len(posts_set) * self._sw_spread_mult)
        inj_score = int(min(100, size_sc + spread_sc))

        return NarrativeInjection(
            narrative_id=f"NARR-{cid:03d}",
            top_terms=top_terms,
            seed_account=seed["actor"],
            seed_post_url=seed["post_url"],
            seed_comment_text=(seed["text"] or "")[:120],
            seed_timestamp=seed["ts"],
            propagation_count=len(cluster),
            propagation_posts=len(posts_set),
            co_injectors=co_inj,
            injection_score=inj_score,
        )

    def _build_chain(
        self,
        inj:     NarrativeInjection,
        cluster: list[dict],
    ) -> PropagationChain:
        steps = [
            PropagationStep(
                ts=c["ts"].isoformat() if c["ts"] else None,
                actor=c["actor"],
                post_url=c["post_url"],
                text_excerpt=c["text"][:80],
            )
            for c in cluster[:self.chain_max]
        ]
        return PropagationChain(narrative_id=inj.narrative_id, steps=steps)

    # ── Aggregates ──────────────────────────────────────────────────────────────

    def _top_injectors(
        self,
        injections: list[NarrativeInjection],
    ) -> list[tuple[str, int]]:
        ctr: Counter = Counter()
        for inj in injections:
            ctr[inj.seed_account] += 1
        return ctr.most_common(self.top_inj_out)

    def _overall_score(
        self,
        injections:      list[NarrativeInjection],
        attack_comments: list[dict],
    ) -> float:
        if not attack_comments or not injections:
            return 0.0
        top   = injections[0]
        score = min(50.0, len(injections) * 5.0)
        score += min(30.0, top.propagation_count * 3.0)
        score += min(20.0, top.propagation_posts * 5.0)
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        injections:      list[NarrativeInjection],
        top_injectors:   list[tuple[str, int]],
        score:           float,
        attack_comments: list[dict],
    ) -> str:
        if not attack_comments:
            return "No attack comments available for narrative injection analysis."
        if not injections:
            return (
                f"{len(attack_comments)} attack comments analyzed. "
                "No distinct narrative clusters found."
            )
        unique_posts = len({c["post_url"] for c in attack_comments})
        parts = [
            f"{len(attack_comments)} attack comments across {unique_posts} post(s) analyzed."
        ]
        top = injections[0]
        parts.append(
            f"{len(injections)} distinct narrative(s) detected. "
            f"Top: {top.narrative_id} seeded by '{top.seed_account}' "
            f"({', '.join(top.top_terms[:3])}) — "
            f"{top.propagation_count} comments · {top.propagation_posts} post(s)."
        )
        if top_injectors:
            actor, cnt = top_injectors[0]
            parts.append(f"Most active injector: '{actor}' — {cnt} narrative(s) seeded.")
        parts.append(f"Narrative injection score: {score}/100.")
        return " ".join(parts)

    # ── Utilities ───────────────────────────────────────────────────────────────

    def _empty_report(self) -> NarrativeInjectionReport:
        return NarrativeInjectionReport(
            injections=[], top_injectors=[], most_propagated=[],
            propagation_chains=[], total_narratives=0,
            total_attack_comments=0, injection_score=0.0,
            summary="No attack comments found for narrative injection analysis.",
        )

    @staticmethod
    def _load_flat(rel_path: str) -> set[str]:
        path = _BASE_DIR / rel_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(x).lower() for x in data}
            if isinstance(data, dict):
                items: list = []
                for v in data.values():
                    if isinstance(v, list):
                        items.extend(v)
                return {str(x).lower() for x in items}
        except Exception:
            pass
        return set()
