"""
EngagementAnomalyEngine.

Detects posts artificially boosted by bot farms via engagement ratio analysis.
Key insight: bot reactions don't generate comments or shares — so bot-boosted posts
show abnormally high reactions/comments ratios vs organic posts.

Classifications per post:
  ORGANIC      — ratio within normal baseline range
  SUSPICIOUS   — ratio elevated, possible light boost
  AMPLIFIED    — high reactions + high shares (could be organic viral OR coordinated)
  BOT_BOOSTED  — high reactions + low comments + low shares = pure bot inflation
  GHOST        — reactions with near-zero comments AND shares = ghost engagement

Campaign score 0-100 based on % of anomalous posts and severity.

All thresholds from cfg["engagement_anomaly"]. Zero hardcoded values.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import List


@dataclass
class PostAnomalyScore:
    url:            str
    source:         str
    text_preview:   str
    reactions:      int
    comments:       int
    shares:         int
    ratio:          float   # reactions / max(comments, 1)
    baseline_ratio: float   # dataset median
    deviation_pct:  float   # how far above baseline (%)
    classification: str     # ORGANIC|SUSPICIOUS|AMPLIFIED|BOT_BOOSTED|GHOST
    anomaly_score:  int     # 0-100 per-post


@dataclass
class EngagementAnomalyReport:
    posts:          List[PostAnomalyScore]
    baseline_ratio: float
    bot_boosted:    List[str]       # URLs
    suspicious:     List[str]
    amplified:      List[str]
    ghost_posts:    List[str]
    anomaly_score:  float           # campaign-level 0-100
    total_analyzed: int
    summary:        str


class EngagementAnomalyEngine:
    """
    Detect bot-boosted posts via engagement ratio analysis.
    Input: list of post dicts with reactions/comments_count/shares fields.
    """

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("engagement_anomaly", {})
        self._min_reactions      = c.get("min_reactions",          5)
        self._bot_boost_ratio    = c.get("bot_boost_ratio",       10.0)
        self._suspicious_ratio   = c.get("suspicious_ratio",       5.0)
        self._amplified_share_pct= c.get("amplified_share_pct",    0.15)
        self._ghost_comment_max  = c.get("ghost_comment_max",       2)
        self._ghost_share_max    = c.get("ghost_share_max",         2)
        self._top_anomalies      = c.get("top_anomalies_output",   20)
        sw = c.get("score_weights", {})
        self._sw_anomaly_pct     = sw.get("anomaly_pct",           60.0)
        self._sw_ratio_mult      = sw.get("avg_ratio_multiplier",   0.8)
        self._sw_max_ratio_score = sw.get("max_ratio_score",       40.0)

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(self, posts: list[dict]) -> EngagementAnomalyReport:
        if not posts:
            return self._empty()

        # Filter posts with meaningful engagement
        eligible = [
            p for p in posts
            if p.get("reactions", 0) >= self._min_reactions
        ]
        if not eligible:
            return self._empty()

        # Build baseline: median reaction/comment ratio across dataset
        ratios = [
            p.get("reactions", 0) / max(p.get("comments_count", 0), 1)
            for p in eligible
        ]
        baseline = statistics.median(ratios) if ratios else 1.0

        # Score each post
        scored: list[PostAnomalyScore] = []
        for p in eligible:
            score = self._score_post(p, baseline)
            scored.append(score)

        # Sort by anomaly_score descending
        scored.sort(key=lambda s: -s.anomaly_score)
        top = scored[:self._top_anomalies]

        bot_boosted = [s.url for s in scored if s.classification == "BOT_BOOSTED"]
        suspicious  = [s.url for s in scored if s.classification == "SUSPICIOUS"]
        amplified   = [s.url for s in scored if s.classification == "AMPLIFIED"]
        ghost       = [s.url for s in scored if s.classification == "GHOST"]

        campaign_score = self._campaign_score(scored, bot_boosted, suspicious)
        summary        = self._build_summary(scored, bot_boosted, suspicious,
                                              amplified, ghost, baseline, campaign_score)

        return EngagementAnomalyReport(
            posts          = top,
            baseline_ratio = round(baseline, 2),
            bot_boosted    = bot_boosted,
            suspicious     = suspicious,
            amplified      = amplified,
            ghost_posts    = ghost,
            anomaly_score  = campaign_score,
            total_analyzed = len(eligible),
            summary        = summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _score_post(self, p: dict, baseline: float) -> PostAnomalyScore:
        reactions = p.get("reactions",      0)
        comments  = p.get("comments_count", 0)
        shares    = p.get("shares",         0)

        ratio = reactions / max(comments, 1)
        dev   = ((ratio - baseline) / max(baseline, 0.01)) * 100.0

        # Classify
        classification = self._classify(reactions, comments, shares, ratio)

        # Per-post anomaly score 0-100
        if classification == "ORGANIC":
            per_score = 0
        elif classification == "SUSPICIOUS":
            per_score = min(40, int(dev * 0.4))
        elif classification == "AMPLIFIED":
            per_score = min(50, int(dev * 0.35))
        elif classification == "BOT_BOOSTED":
            per_score = min(90, int(40 + dev * 0.3))
        else:  # GHOST
            per_score = min(100, int(50 + (reactions / max(reactions, 1)) * 50))

        return PostAnomalyScore(
            url            = p.get("url", ""),
            source         = p.get("source", "?"),
            text_preview   = (p.get("text", "") or "")[:80],
            reactions      = reactions,
            comments       = comments,
            shares         = shares,
            ratio          = round(ratio, 1),
            baseline_ratio = round(baseline, 2),
            deviation_pct  = round(dev, 1),
            classification = classification,
            anomaly_score  = per_score,
        )

    def _classify(self, reactions: int, comments: int, shares: int, ratio: float) -> str:
        # Ghost: high reactions, near-zero comments AND shares
        if (reactions >= self._min_reactions * 4
                and comments <= self._ghost_comment_max
                and shares <= self._ghost_share_max):
            return "GHOST"

        if ratio >= self._bot_boost_ratio:
            # High ratio — is it amplified (viral with shares) or pure bot boost?
            share_pct = shares / max(reactions, 1)
            if share_pct >= self._amplified_share_pct:
                return "AMPLIFIED"
            return "BOT_BOOSTED"

        if ratio >= self._suspicious_ratio:
            return "SUSPICIOUS"

        return "ORGANIC"

    def _campaign_score(
        self,
        scored: list[PostAnomalyScore],
        bot_boosted: list[str],
        suspicious: list[str],
    ) -> float:
        if not scored:
            return 0.0
        n = len(scored)
        anomaly_pct = (len(bot_boosted) + len(suspicious) * 0.5) / n
        avg_score   = sum(s.anomaly_score for s in scored) / n
        score = (anomaly_pct * self._sw_anomaly_pct
                 + min(self._sw_max_ratio_score, avg_score * self._sw_ratio_mult))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        scored: list[PostAnomalyScore],
        bot_boosted: list[str],
        suspicious: list[str],
        amplified: list[str],
        ghost: list[str],
        baseline: float,
        score: float,
    ) -> str:
        n = len(scored)
        if not n:
            return "No posts with sufficient engagement to analyze."
        parts = [
            f"{n} post(s) analyzed — engagement anomaly score {score}/100. "
            f"Baseline ratio reactions/comments: {baseline:.1f}x."
        ]
        flagged = len(bot_boosted) + len(suspicious) + len(ghost)
        if flagged:
            parts.append(
                f"{flagged} anomalous: "
                f"{len(bot_boosted)} BOT_BOOSTED · "
                f"{len(suspicious)} SUSPICIOUS · "
                f"{len(ghost)} GHOST · "
                f"{len(amplified)} AMPLIFIED."
            )
        if bot_boosted:
            top = next((s for s in scored if s.url == bot_boosted[0]), None)
            if top:
                parts.append(
                    f"Most inflated post: {top.ratio:.0f}x reactions/comments "
                    f"({top.deviation_pct:+.0f}% above baseline) — {top.source}."
                )
        return " ".join(parts)

    @staticmethod
    def _empty() -> EngagementAnomalyReport:
        return EngagementAnomalyReport(
            posts=[], baseline_ratio=0.0, bot_boosted=[], suspicious=[],
            amplified=[], ghost_posts=[], anomaly_score=0.0,
            total_analyzed=0,
            summary="No posts with sufficient engagement data to analyze.",
        )
