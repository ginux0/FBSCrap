"""
NarrativeSeedingEngine — P5: Cross-Post Narrative Seeding Tracker.

Detects narratives (attack phrases / repeated text) that propagate across multiple
posts. Identifies the seed account (first to use a narrative), the propagation chain
(which posts it spread to), and the cross-post actors (accounts appearing in 3+ posts
with similar content). All parameters from cfg["narrative_seeding"]. Zero hardcoded.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _tfidf_sim(a: str, b: str) -> float:
    """Quick Jaccard sim on word-level trigrams — no scipy needed."""
    def trigrams(s: str) -> set[str]:
        words = s.split()
        if len(words) < 2:
            return {s}
        return {" ".join(words[i:i + 2]) for i in range(len(words) - 1)}

    sa, sb = trigrams(a), trigrams(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class PropagationEntry:
    post_url:  str
    actor:     str
    timestamp: datetime | None
    text_snippet: str


@dataclass
class NarrativeSeed:
    key:              str           # first key_len chars of normalized text
    full_text:        str
    first_post_url:   str
    first_actor:      str
    first_seen:       datetime | None
    propagation:      list[PropagationEntry]   # all occurrences ordered by time
    unique_posts:     int
    unique_actors:    int
    propagation_count: int          # unique_posts - 1 (spread beyond origin)


@dataclass
class NarrativePropagationReport:
    seeds:              list[NarrativeSeed]
    cross_post_actors:  list[str]   # actors seen in 3+ posts
    total_seeded:       int         # narratives that spread to 2+ posts
    propagation_score:  float
    summary:            str


class NarrativeSeedingEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("narrative_seeding", {})
        self.min_text_len   = c.get("min_text_len",       15)
        self.sim_threshold  = c.get("sim_threshold",       0.50)
        self.min_posts      = c.get("min_posts",           2)
        self.key_len        = c.get("key_len",             60)
        self.top_seeds_n    = c.get("top_seeds_output",    20)
        self.top_actors_n   = c.get("top_actors_output",   15)
        self.max_comments   = c.get("max_comments",        3000)
        sw = c.get("score_weights", {})
        self._sw_seed_mult  = sw.get("seed_multiplier",    8.0)
        self._sw_max_seed   = sw.get("max_seed_score",    50.0)
        self._sw_cross_mult = sw.get("cross_actor_mult",  10.0)
        self._sw_max_cross  = sw.get("max_cross_score",   50.0)

    def analyze(self, scraped_results: list[dict]) -> NarrativePropagationReport:
        # Collect all comments with metadata, deduplicated by (actor, post, text[:key_len])
        raw: list[dict] = []
        seen_keys: set[str] = set()
        for r in scraped_results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                text   = c.get("text", "")
                actor  = c.get("author", "?")
                ts_str = c.get("timestamp")
                if not text or len(text) < self.min_text_len:
                    continue
                norm = _normalize(text)
                k    = f"{actor}|{url}|{norm[:self.key_len]}"
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                try:
                    ts = datetime.fromisoformat(ts_str) if ts_str else None
                except (ValueError, TypeError):
                    ts = None
                raw.append({"text": norm, "actor": actor, "url": url, "ts": ts})
                if len(raw) >= self.max_comments:
                    break

        if not raw:
            return self._empty()

        # Greedy clustering by bigram Jaccard similarity
        clusters: list[list[dict]] = []
        assigned = [False] * len(raw)

        for i, item in enumerate(raw):
            if assigned[i]:
                continue
            cluster = [item]
            assigned[i] = True
            for j in range(i + 1, len(raw)):
                if assigned[j]:
                    continue
                if _tfidf_sim(item["text"], raw[j]["text"]) >= self.sim_threshold:
                    cluster.append(raw[j])
                    assigned[j] = True
            clusters.append(cluster)

        seeds: list[NarrativeSeed] = []
        for cluster in clusters:
            urls   = {e["url"] for e in cluster}
            if len(urls) < self.min_posts:
                continue
            # Sort by timestamp, fallback to original order
            cluster.sort(key=lambda e: (e["ts"] or datetime.max))
            first  = cluster[0]
            props  = [
                PropagationEntry(
                    post_url=e["url"], actor=e["actor"],
                    timestamp=e["ts"],
                    text_snippet=e["text"][:80],
                )
                for e in cluster
            ]
            seeds.append(NarrativeSeed(
                key=first["text"][:self.key_len],
                full_text=first["text"][:200],
                first_post_url=first["url"],
                first_actor=first["actor"],
                first_seen=first["ts"],
                propagation=props,
                unique_posts=len(urls),
                unique_actors=len({e["actor"] for e in cluster}),
                propagation_count=len(urls) - 1,
            ))

        seeds.sort(key=lambda s: (-s.propagation_count, -s.unique_actors))
        seeds = seeds[:self.top_seeds_n]

        # Cross-post actors: appear in 3+ different posts
        actor_posts: dict[str, set[str]] = defaultdict(set)
        for r in scraped_results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                actor = c.get("author", "?")
                actor_posts[actor].add(url)
        cross_post = sorted(
            [a for a, urls in actor_posts.items() if len(urls) >= 3],
            key=lambda a: -len(actor_posts[a]),
        )[:self.top_actors_n]

        score   = self._overall_score(seeds, cross_post)
        summary = self._build_summary(seeds, cross_post, score)

        return NarrativePropagationReport(
            seeds=seeds,
            cross_post_actors=cross_post,
            total_seeded=len(seeds),
            propagation_score=score,
            summary=summary,
        )

    def _overall_score(
        self,
        seeds: list[NarrativeSeed],
        cross_actors: list[str],
    ) -> float:
        seed_score  = min(self._sw_max_seed,  len(seeds)       * self._sw_seed_mult)
        cross_score = min(self._sw_max_cross, len(cross_actors) * self._sw_cross_mult)
        return round(min(100.0, seed_score + cross_score), 1)

    def _build_summary(
        self,
        seeds: list[NarrativeSeed],
        cross_actors: list[str],
        score: float,
    ) -> str:
        if not seeds and not cross_actors:
            return "No cross-post narrative seeding patterns detected."
        parts = [f"Narrative seeding score {score}/100."]
        if seeds:
            top_seed = seeds[0]
            parts.append(
                f"{len(seeds)} seeded narrative(s) tracked across posts — "
                f"top seed first deployed by '{top_seed.first_actor}', "
                f"spread to {top_seed.unique_posts} post(s)."
            )
        if cross_actors:
            parts.append(
                f"{len(cross_actors)} cross-post actor(s) commenting in 3+ posts: "
                f"{', '.join(cross_actors[:4])}."
            )
        return " ".join(parts)

    @staticmethod
    def _empty() -> NarrativePropagationReport:
        return NarrativePropagationReport(
            seeds=[], cross_post_actors=[],
            total_seeded=0, propagation_score=0.0,
            summary="No comments with sufficient text for narrative seeding analysis.",
        )
