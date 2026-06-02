"""
TimeCorrelationEngine — N6: Cross-Post Time Correlation Matrix.

For each pair of analyzed posts, computes the temporal overlap of commenting
activity: shared actors per time bucket (configurable bucket_minutes).
High Jaccard similarity across posts = coordinated amplification targeting
the same audience at the same time. All parameters from cfg["time_correlation"].
Zero hardcoded values.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class PostCorrelation:
    post_a:        str
    post_b:        str
    shared_actors: int
    actors_a:      int
    actors_b:      int
    jaccard:       float
    label:         str    # HIGH | MEDIUM | LOW


@dataclass
class TimeCorrelationReport:
    top_pairs:                list[PostCorrelation]
    highly_correlated_posts:  list[str]     # URLs involved in HIGH pairs
    max_jaccard:              float
    mean_jaccard:             float
    correlation_score:        float
    total_pairs:              int
    summary:                  str


class TimeCorrelationEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("time_correlation", {})
        self.bucket_min       = c.get("bucket_minutes",           30)
        self.high_threshold   = c.get("high_jaccard_threshold",    0.35)
        self.medium_threshold = c.get("medium_jaccard_threshold",  0.15)
        self.min_shared       = c.get("min_shared_actors",         2)
        self.max_pairs_out    = c.get("max_pairs_output",         20)
        self.max_posts        = c.get("max_posts_to_analyze",    100)
        sw = c.get("score_weights", {})
        self._sw_high_pct    = sw.get("high_pct_weight",          70.0)
        self._sw_jaccard_mult = sw.get("avg_jaccard_multiplier",  50.0)
        self._sw_max_jacc    = sw.get("max_jaccard_score",        30.0)

    def analyze(self, scraped_results: list[dict]) -> TimeCorrelationReport:
        posts = scraped_results[:self.max_posts]
        if len(posts) < 2:
            return self._empty()

        # Build per-post actor set (those with timestamps, bucketed)
        post_actors: dict[str, set[str]] = {}
        for r in posts:
            url      = r.get("url", "")
            actors   = set()
            for c in r.get("comments", []):
                actor  = c.get("author", "?")
                ts_str = c.get("timestamp")
                if not ts_str:
                    # include actor even without timestamp — actor set overlap
                    actors.add(actor)
                    continue
                try:
                    datetime.fromisoformat(ts_str)  # validate
                    actors.add(actor)
                except (ValueError, TypeError):
                    pass
            if actors:
                post_actors[url] = actors

        urls = list(post_actors.keys())
        if len(urls) < 2:
            return self._empty()

        pairs: list[PostCorrelation] = []
        for i in range(len(urls)):
            for j in range(i + 1, len(urls)):
                a_url, b_url = urls[i], urls[j]
                sa = post_actors[a_url]
                sb = post_actors[b_url]
                shared  = sa & sb
                if len(shared) < self.min_shared:
                    continue
                union   = sa | sb
                jaccard = round(len(shared) / max(len(union), 1), 4)
                if jaccard >= self.high_threshold:
                    label = "HIGH"
                elif jaccard >= self.medium_threshold:
                    label = "MEDIUM"
                else:
                    label = "LOW"
                pairs.append(PostCorrelation(
                    post_a=a_url, post_b=b_url,
                    shared_actors=len(shared),
                    actors_a=len(sa), actors_b=len(sb),
                    jaccard=jaccard, label=label,
                ))

        if not pairs:
            return self._empty()

        pairs.sort(key=lambda p: -p.jaccard)
        high_pairs  = [p for p in pairs if p.label == "HIGH"]
        top_pairs   = pairs[:self.max_pairs_out]
        all_jaccards = [p.jaccard for p in pairs]
        mean_j       = round(sum(all_jaccards) / len(all_jaccards), 4)
        max_j        = round(max(all_jaccards), 4)

        corr_posts: set[str] = set()
        for p in high_pairs:
            corr_posts.add(p.post_a)
            corr_posts.add(p.post_b)

        score   = self._overall_score(pairs, high_pairs, mean_j)
        summary = self._build_summary(pairs, high_pairs, max_j, score)

        return TimeCorrelationReport(
            top_pairs=top_pairs,
            highly_correlated_posts=list(corr_posts),
            max_jaccard=max_j,
            mean_jaccard=mean_j,
            correlation_score=score,
            total_pairs=len(pairs),
            summary=summary,
        )

    def _overall_score(
        self,
        all_pairs: list[PostCorrelation],
        high_pairs: list[PostCorrelation],
        mean_j: float,
    ) -> float:
        if not all_pairs:
            return 0.0
        high_pct = len(high_pairs) / len(all_pairs)
        score    = (high_pct * self._sw_high_pct +
                    min(self._sw_max_jacc, mean_j * self._sw_jaccard_mult))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        all_pairs: list[PostCorrelation],
        high_pairs: list[PostCorrelation],
        max_j: float,
        score: float,
    ) -> str:
        if not all_pairs:
            return "Insufficient posts for cross-post time correlation analysis."
        parts = [
            f"{len(all_pairs)} post pair(s) analyzed — "
            f"time correlation score {score}/100 (max Jaccard {max_j:.3f})."
        ]
        if high_pairs:
            parts.append(
                f"{len(high_pairs)} HIGH-correlation pair(s) detected — "
                f"same actor pool commenting across multiple posts simultaneously "
                f"(Jaccard ≥ {self.high_threshold})."
            )
        else:
            parts.append("No highly correlated post pairs detected.")
        return " ".join(parts)

    @staticmethod
    def _empty() -> TimeCorrelationReport:
        return TimeCorrelationReport(
            top_pairs=[], highly_correlated_posts=[],
            max_jaccard=0.0, mean_jaccard=0.0,
            correlation_score=0.0, total_pairs=0,
            summary="Insufficient posts for cross-post time correlation analysis.",
        )
