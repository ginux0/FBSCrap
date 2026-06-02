"""
SemanticEngine — N5: Narrative Cluster Analysis.

Pure-Python TF-IDF + cosine greedy clustering. No external ML deps.
Adaptive threshold auto-calibrated from pairwise similarity distribution.

All parameters read from cfg["semantic"]. Zero hardcoded values.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_BASE_DIR = Path(__file__).parent.parent


def _load_stopwords(path_str: str) -> set[str]:
    try:
        raw = json.loads((_BASE_DIR / path_str).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return set(raw)
    except Exception:
        pass
    return set()


@dataclass
class NarrativeCluster:
    cluster_id:    int
    size:          int
    top_terms:     list[str]
    actors:        list[str]
    sample_texts:  list[str]
    centroid_sim:  float
    bot_ratio:     float
    label:         str       # BOT_DOMINATED | MIXED | ORGANIC


@dataclass
class ActorNarrativeRole:
    actor:      str
    label:      str           # SOLDIER | AMPLIFIER | ORGANIC
    clusters:   list[int]     # cluster IDs this actor appears in
    top_terms:  list[str]


@dataclass
class SemanticReport:
    clusters:             list[NarrativeCluster]
    actor_roles:          list[ActorNarrativeRole]
    bot_dominated_count:  int
    soldiers:             list[str]
    amplifiers:           list[str]
    total_comments:       int
    clustered_comments:   int
    narrative_score:      float
    threshold_used:       float
    summary:              str


class SemanticEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("semantic", {})

        sw_file = c.get("stopwords_file", "config/patterns/stopwords_es_en.json")
        self._stopwords = _load_stopwords(sw_file)

        self._adaptive            = c.get("adaptive_threshold", True)
        self._fixed_threshold     = c.get("cluster_sim_threshold", None)
        self._adaptive_sample     = c.get("adaptive_sample_vectors", 50)
        self._adaptive_k_std      = c.get("adaptive_k_std", 1.0)
        self._adaptive_min        = c.get("adaptive_min", 0.15)
        self._adaptive_max        = c.get("adaptive_max", 0.55)
        self._adaptive_fallback   = c.get("adaptive_fallback", 0.25)

        self._min_cluster_size    = c.get("min_cluster_size", 3)
        self._top_terms           = c.get("top_terms", 8)
        self._bot_cluster_thresh  = c.get("bot_cluster_threshold", 0.50)
        self._soldier_max_clust   = c.get("soldier_max_clusters", 1)
        self._amplifier_min_clust = c.get("amplifier_min_clusters", 3)
        self._max_comments        = c.get("max_comments", 5000)
        self._min_comment_len     = c.get("min_comment_len", 10)
        self._min_term_len        = c.get("min_term_len", 3)

        sw = c.get("score_weights", {})
        self._sw_bot_dom_per     = sw.get("bot_dominated_per_cluster", 20.0)
        self._sw_bot_dom_max     = sw.get("max_bot_dom_score", 60.0)
        self._sw_amp_mult        = sw.get("amplifier_multiplier", 4.0)
        self._sw_amp_max         = sw.get("max_amplifier_score", 20.0)
        self._sw_sol_mult        = sw.get("soldier_multiplier", 2.0)
        self._sw_sol_max         = sw.get("max_soldier_score", 20.0)

    def analyze(
        self,
        scraped_results:   list[dict],
        bot_actor_set:     set[str] | None = None,
    ) -> SemanticReport:
        bot_actors = bot_actor_set or set()

        # Collect comments
        comments: list[dict] = []
        for r in scraped_results:
            for c in r.get("comments", []):
                text = (c.get("text") or "").strip()
                if len(text) >= self._min_comment_len:
                    comments.append({
                        "author": c.get("author", "?"),
                        "text":   text,
                        "is_bot": c.get("author", "?") in bot_actors,
                    })
            if len(comments) >= self._max_comments:
                break

        if not comments:
            return self._empty_report()

        # Build TF-IDF vectors
        vectors   = [self._tfidf_vector(c["text"]) for c in comments]
        idf_boost = self._compute_idf(vectors)
        vectors   = [self._apply_idf(v, idf_boost) for v in vectors]

        # Calibrate threshold
        threshold = self._calibrate_threshold(vectors)

        # Greedy clustering
        raw_clusters = self._greedy_cluster(comments, vectors, threshold)

        # Build rich cluster objects
        clusters: list[NarrativeCluster] = []
        for cid, indices in enumerate(raw_clusters, 1):
            if len(indices) < self._min_cluster_size:
                continue
            cluster_comments = [comments[i] for i in indices]
            cluster_vectors  = [vectors[i] for i in indices]

            actors    = list({c["author"] for c in cluster_comments})
            bots_in   = sum(1 for c in cluster_comments if c["is_bot"])
            bot_ratio = bots_in / len(cluster_comments)

            top_terms   = self._top_terms_from_vectors(cluster_vectors)
            sample_text = [c["text"][:80] for c in cluster_comments[:3]]
            centroid    = self._centroid(cluster_vectors)
            avg_sim     = sum(
                self._cosine(vectors[i], centroid) for i in indices
            ) / len(indices)

            label = (
                "BOT_DOMINATED" if bot_ratio >= self._bot_cluster_thresh
                else "MIXED" if bot_ratio > 0
                else "ORGANIC"
            )

            clusters.append(NarrativeCluster(
                cluster_id=cid, size=len(indices),
                top_terms=top_terms, actors=actors,
                sample_texts=sample_text,
                centroid_sim=round(avg_sim, 4),
                bot_ratio=round(bot_ratio, 3),
                label=label,
            ))

        clusters.sort(key=lambda c: (-c.bot_ratio, -c.size))

        # Actor roles
        actor_cluster_map: dict[str, list[int]] = defaultdict(list)
        for cl in clusters:
            for actor in cl.actors:
                actor_cluster_map[actor].append(cl.cluster_id)

        actor_roles: list[ActorNarrativeRole] = []
        soldiers:    list[str] = []
        amplifiers:  list[str] = []

        for actor, clust_ids in actor_cluster_map.items():
            if len(clust_ids) >= self._amplifier_min_clust:
                role = "AMPLIFIER"
                amplifiers.append(actor)
            elif len(clust_ids) <= self._soldier_max_clust and actor in bot_actors:
                role = "SOLDIER"
                soldiers.append(actor)
            else:
                role = "ORGANIC"

            actor_roles.append(ActorNarrativeRole(
                actor=actor, label=role,
                clusters=clust_ids,
                top_terms=[],
            ))

        actor_roles.sort(key=lambda a: (-len(a.clusters), a.label))

        bot_dominated = [cl for cl in clusters if cl.label == "BOT_DOMINATED"]
        score         = self._narrative_score(clusters, soldiers, amplifiers)
        total_clustered = sum(len(raw_clusters[i]) for i in range(len(raw_clusters))
                              if len(raw_clusters[i]) >= self._min_cluster_size)

        return SemanticReport(
            clusters=clusters,
            actor_roles=actor_roles,
            bot_dominated_count=len(bot_dominated),
            soldiers=soldiers,
            amplifiers=amplifiers,
            total_comments=len(comments),
            clustered_comments=total_clustered,
            narrative_score=score,
            threshold_used=threshold,
            summary=self._build_summary(clusters, soldiers, amplifiers, score, len(comments)),
        )

    # ── TF-IDF ─────────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        words = re.findall(r'\b\w+\b', text.lower())
        return [
            w for w in words
            if len(w) >= self._min_term_len and w not in self._stopwords
        ]

    def _tfidf_vector(self, text: str) -> dict[str, float]:
        tokens = self._tokenize(text)
        if not tokens:
            return {}
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        n = len(tokens)
        return {t: c / n for t, c in freq.items()}

    @staticmethod
    def _compute_idf(vectors: list[dict]) -> dict[str, float]:
        n = len(vectors)
        if not n:
            return {}
        doc_freq: dict[str, int] = {}
        for v in vectors:
            for term in v:
                doc_freq[term] = doc_freq.get(term, 0) + 1
        return {
            t: math.log(n / df) + 1.0
            for t, df in doc_freq.items()
        }

    @staticmethod
    def _apply_idf(vector: dict[str, float], idf: dict[str, float]) -> dict[str, float]:
        return {t: w * idf.get(t, 1.0) for t, w in vector.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        keys  = set(a) & set(b)
        if not keys:
            return 0.0
        dot   = sum(a[k] * b[k] for k in keys)
        mag_a = math.sqrt(sum(v ** 2 for v in a.values()))
        mag_b = math.sqrt(sum(v ** 2 for v in b.values()))
        denom = mag_a * mag_b
        return dot / denom if denom else 0.0

    @staticmethod
    def _centroid(vectors: list[dict[str, float]]) -> dict[str, float]:
        if not vectors:
            return {}
        merged: dict[str, float] = {}
        n = len(vectors)
        for v in vectors:
            for t, w in v.items():
                merged[t] = merged.get(t, 0.0) + w / n
        return merged

    def _top_terms_from_vectors(self, vectors: list[dict[str, float]]) -> list[str]:
        centroid = self._centroid(vectors)
        sorted_terms = sorted(centroid.items(), key=lambda x: -x[1])
        return [t for t, _ in sorted_terms[:self._top_terms]]

    # ── Adaptive threshold ─────────────────────────────────────────────────────

    def _calibrate_threshold(self, vectors: list[dict]) -> float:
        if not self._adaptive or self._fixed_threshold is not None:
            return self._fixed_threshold or self._adaptive_fallback

        sample = vectors[:self._adaptive_sample]
        sims: list[float] = []
        n = len(sample)
        for i in range(n):
            for j in range(i + 1, n):
                s = self._cosine(sample[i], sample[j])
                if s > 0:
                    sims.append(s)

        if len(sims) < 5:
            return self._adaptive_fallback

        mean  = sum(sims) / len(sims)
        var   = sum((s - mean) ** 2 for s in sims) / len(sims)
        std   = math.sqrt(var)
        t     = mean + self._adaptive_k_std * std
        return round(max(self._adaptive_min, min(self._adaptive_max, t)), 4)

    # ── Greedy clustering ──────────────────────────────────────────────────────

    def _greedy_cluster(
        self,
        comments: list[dict],
        vectors:  list[dict[str, float]],
        threshold: float,
    ) -> list[list[int]]:
        assigned: list[int] = [-1] * len(comments)
        cluster_centroids: list[dict[str, float]] = []
        clusters: list[list[int]] = []

        for i, vec in enumerate(vectors):
            if not vec:
                continue
            best_cid = -1
            best_sim = threshold - 1e-9

            for cid, centroid in enumerate(cluster_centroids):
                sim = self._cosine(vec, centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_cid = cid

            if best_cid >= 0:
                clusters[best_cid].append(i)
                assigned[i] = best_cid
                cluster_centroids[best_cid] = self._centroid(
                    [vectors[j] for j in clusters[best_cid]]
                )
            else:
                new_cid = len(clusters)
                clusters.append([i])
                assigned[i] = new_cid
                cluster_centroids.append(dict(vec))

        return clusters

    # ── Score ──────────────────────────────────────────────────────────────────

    def _narrative_score(
        self,
        clusters:   list[NarrativeCluster],
        soldiers:   list[str],
        amplifiers: list[str],
    ) -> float:
        score  = 0.0
        bot_dom = sum(1 for c in clusters if c.label == "BOT_DOMINATED")
        score += min(self._sw_bot_dom_max, bot_dom * self._sw_bot_dom_per)
        score += min(self._sw_amp_max,     len(amplifiers) * self._sw_amp_mult)
        score += min(self._sw_sol_max,     len(soldiers)   * self._sw_sol_mult)
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        clusters:   list[NarrativeCluster],
        soldiers:   list[str],
        amplifiers: list[str],
        score:      float,
        total:      int,
    ) -> str:
        if not clusters:
            return f"{total} comments analyzed. No significant narrative clusters detected."

        parts = [f"{total} comments analyzed — {len(clusters)} narrative cluster(s) found."]
        bot_dom = [c for c in clusters if c.label == "BOT_DOMINATED"]
        if bot_dom:
            top = bot_dom[0]
            parts.append(
                f"{len(bot_dom)} bot-dominated cluster(s) detected. "
                f"Largest: {top.size} comments, top terms: [{', '.join(top.top_terms[:4])}], "
                f"bot ratio: {top.bot_ratio:.0%}."
            )
        if amplifiers:
            parts.append(
                f"{len(amplifiers)} amplifier account(s) spreading narrative "
                f"across ≥{self._amplifier_min_clust} clusters."
            )
        if soldiers:
            parts.append(f"{len(soldiers)} soldier bot(s) focused on single narrative cluster.")
        parts.append(f"Narrative manipulation score: {score}/100.")
        return " ".join(parts)

    @staticmethod
    def _empty_report() -> SemanticReport:
        return SemanticReport(
            clusters=[], actor_roles=[], bot_dominated_count=0,
            soldiers=[], amplifiers=[], total_comments=0, clustered_comments=0,
            narrative_score=0.0, threshold_used=0.0,
            summary="No comments available for semantic analysis.",
        )
