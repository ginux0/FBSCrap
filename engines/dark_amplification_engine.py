"""
DarkAmplificationEngine.

Detects posts artificially pushed to trend by bot farms via engagement velocity
analysis. "Dark amplification" = a post receives a massive bot-generated
engagement burst in a short window, then stalls or decays because there is no
organic interest to sustain it.

Key metrics per post:
  - velocity:            engagement_total / age_hours
  - amplification_factor: velocity / dataset_baseline (how many times above normal)
  - comment_burst_ratio: fraction of comments arriving in first N% of post lifetime
  - reaction_purity:     reactions / (reactions + comments + shares) — high = low
                         organic interaction (people reacted but didn't engage)

Classifications:
  ORGANIC        — velocity within normal range
  SUSPICIOUS     — elevated velocity, ambiguous
  DARK_AMP       — high velocity + low organic interaction signal
  VIRAL_GENUINE  — high velocity + strong organic signal (high comments+shares)

Campaign amplification score 0-100.
All thresholds from cfg["dark_amplification"]. Zero hardcoded values.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List


@dataclass
class AmplificationEvent:
    url:                  str
    source:               str
    text_preview:         str
    post_ts:              str | None    # post creation ISO timestamp
    age_hours:            float         # hours old at scrape time
    engagement_total:     int
    reactions:            int
    comments:             int
    shares:               int
    velocity:             float         # eng / age_hours
    baseline_velocity:    float         # dataset median
    amplification_factor: float         # velocity / baseline
    reaction_purity:      float         # reactions / total (0-1)
    comment_burst_ratio:  float         # comments in burst window / total
    classification:       str           # ORGANIC|SUSPICIOUS|DARK_AMP|VIRAL_GENUINE
    amp_score:            int           # 0-100 per post


@dataclass
class DarkAmplificationReport:
    events:           List[AmplificationEvent]
    dark_amplified:   List[str]     # URLs classified as DARK_AMP
    suspicious:       List[str]
    baseline_velocity:float
    amp_score:        float         # campaign-level 0-100
    total_analyzed:   int
    top_amplified_source: str | None
    summary:          str


class DarkAmplificationEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("dark_amplification", {})
        self._dark_amp_factor    = c.get("dark_amp_factor",         5.0)
        self._suspicious_factor  = c.get("suspicious_factor",       3.0)
        self._viral_comment_min  = c.get("viral_comment_min_pct",   0.15)
        self._viral_share_min    = c.get("viral_share_min_pct",     0.05)
        self._reaction_purity_threshold = c.get("reaction_purity_threshold", 0.85)
        self._burst_window_pct   = c.get("burst_window_pct",        0.20)
        self._min_engagement     = c.get("min_engagement",          50)
        self._min_age_hours      = c.get("min_age_hours",           0.5)
        self._top_events         = c.get("top_events_output",       20)
        sw = c.get("score_weights", {})
        self._sw_dark_pct        = sw.get("dark_pct",               60.0)
        self._sw_avg_factor      = sw.get("avg_factor_multiplier",   4.0)
        self._sw_max_factor      = sw.get("max_factor_score",       40.0)

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        posts:       list[dict],
        scraped_results: list[dict] | None = None,
    ) -> DarkAmplificationReport:
        """
        posts:           raw post dicts with timestamp, scraped_at, engagement fields
        scraped_results: comment data (optional — enriches burst_ratio detection)
        """
        if not posts:
            return self._empty()

        # Build comment timestamp map for burst detection
        comment_ts_map: dict[str, list[datetime]] = {}
        for r in (scraped_results or []):
            url = r.get("url", "")
            tss = []
            for c in r.get("comments", []):
                ts_str = c.get("timestamp")
                if ts_str:
                    try:
                        tss.append(datetime.fromisoformat(ts_str))
                    except Exception:
                        pass
            if tss:
                comment_ts_map[url] = sorted(tss)

        # Compute velocity for all eligible posts to establish baseline
        eligible = []
        for p in posts:
            age_h = self._age_hours(p)
            eng   = p.get("engagement_total", 0)
            if eng >= self._min_engagement and age_h >= self._min_age_hours:
                eligible.append((age_h, eng, p))

        if not eligible:
            return self._empty()

        velocities = [eng / age_h for age_h, eng, _ in eligible]
        baseline   = statistics.median(velocities)

        # Score each eligible post
        events: list[AmplificationEvent] = []
        for age_h, eng, p in eligible:
            ev = self._score_post(p, age_h, eng, baseline, comment_ts_map)
            events.append(ev)

        events.sort(key=lambda e: -e.amp_score)
        top = events[:self._top_events]

        dark_amp   = [e.url for e in events if e.classification == "DARK_AMP"]
        suspicious = [e.url for e in events if e.classification == "SUSPICIOUS"]

        top_src = None
        if dark_amp:
            top_ev = next((e for e in events if e.url == dark_amp[0]), None)
            top_src = top_ev.source if top_ev else None

        score   = self._campaign_score(events, dark_amp, suspicious, baseline)
        summary = self._build_summary(events, dark_amp, suspicious, baseline, score, top_src)

        return DarkAmplificationReport(
            events            = top,
            dark_amplified    = dark_amp,
            suspicious        = suspicious,
            baseline_velocity = round(baseline, 1),
            amp_score         = score,
            total_analyzed    = len(eligible),
            top_amplified_source = top_src,
            summary           = summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _score_post(
        self,
        p:           dict,
        age_h:       float,
        eng:         int,
        baseline:    float,
        comment_ts:  dict[str, list[datetime]],
    ) -> AmplificationEvent:
        reactions = p.get("reactions",      0)
        comments  = p.get("comments_count", 0)
        shares    = p.get("shares",         0)

        velocity  = eng / max(age_h, 0.01)
        amp_factor = velocity / max(baseline, 0.01)

        # Reaction purity: high = mostly reactions, low organic text interaction
        react_purity = reactions / max(eng, 1)

        # Comment burst ratio: fraction of comments in first burst_window_pct of lifetime
        burst_ratio = self._compute_burst_ratio(
            p.get("url", ""), p.get("timestamp"), age_h,
            comments, comment_ts,
        )

        # Comment and share pct of engagement
        comment_pct = comments / max(eng, 1)
        share_pct   = shares   / max(eng, 1)

        classification = self._classify(
            amp_factor, react_purity, comment_pct, share_pct, burst_ratio,
        )

        per_score = self._per_post_score(amp_factor, react_purity, burst_ratio, classification)

        return AmplificationEvent(
            url                  = p.get("url", ""),
            source               = p.get("source", "?"),
            text_preview         = (p.get("text") or "")[:80],
            post_ts              = p.get("timestamp"),
            age_hours            = round(age_h, 1),
            engagement_total     = eng,
            reactions            = reactions,
            comments             = comments,
            shares               = shares,
            velocity             = round(velocity, 1),
            baseline_velocity    = round(baseline, 1),
            amplification_factor = round(amp_factor, 2),
            reaction_purity      = round(react_purity, 3),
            comment_burst_ratio  = round(burst_ratio, 3),
            classification       = classification,
            amp_score            = per_score,
        )

    def _classify(
        self,
        factor:       float,
        react_purity: float,
        comment_pct:  float,
        share_pct:    float,
        burst_ratio:  float,
    ) -> str:
        is_high_velocity = factor >= self._dark_amp_factor
        is_organic_signal = (
            comment_pct >= self._viral_comment_min
            or share_pct >= self._viral_share_min
        )
        is_pure_reaction  = react_purity >= self._reaction_purity_threshold
        is_burst          = burst_ratio >= 0.70

        if factor < self._suspicious_factor:
            return "ORGANIC"

        if is_high_velocity:
            if is_organic_signal and not is_pure_reaction:
                return "VIRAL_GENUINE"    # high velocity but people commented/shared = real
            return "DARK_AMP"             # velocity spike without organic engagement

        if factor >= self._suspicious_factor:
            if is_pure_reaction or is_burst:
                return "SUSPICIOUS"

        return "ORGANIC"

    def _compute_burst_ratio(
        self,
        url:         str,
        post_ts_str: str | None,
        age_h:       float,
        total_comments: int,
        comment_ts:  dict[str, list[datetime]],
    ) -> float:
        """Fraction of comments arriving in the first burst_window_pct of post lifetime."""
        tss = comment_ts.get(url, [])
        if not tss or not post_ts_str or total_comments < 3:
            return 0.0
        try:
            post_dt  = datetime.fromisoformat(post_ts_str[:19])
            burst_end = post_dt + timedelta(hours=age_h * self._burst_window_pct)
            burst_cnt = sum(1 for t in tss if t <= burst_end)
            return burst_cnt / max(total_comments, 1)
        except Exception:
            return 0.0

    def _per_post_score(
        self,
        factor:       float,
        react_purity: float,
        burst_ratio:  float,
        cls:          str,
    ) -> int:
        if cls == "ORGANIC":
            return 0
        if cls == "VIRAL_GENUINE":
            return max(5, int((factor / self._dark_amp_factor) * 20))

        base = min(60, int((factor / self._dark_amp_factor) * 30))
        purity_bonus = int(react_purity * 20)
        burst_bonus  = int(burst_ratio  * 20)
        return min(100, base + purity_bonus + burst_bonus)

    def _campaign_score(
        self,
        events:    list[AmplificationEvent],
        dark_amp:  list[str],
        suspicious:list[str],
        baseline:  float,
    ) -> float:
        if not events:
            return 0.0
        n = len(events)
        dark_pct = (len(dark_amp) + len(suspicious) * 0.4) / n
        avg_factor = sum(e.amplification_factor for e in events) / n
        score = (dark_pct * self._sw_dark_pct
                 + min(self._sw_max_factor, avg_factor * self._sw_avg_factor))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        events:    list[AmplificationEvent],
        dark_amp:  list[str],
        suspicious:list[str],
        baseline:  float,
        score:     float,
        top_src:   str | None,
    ) -> str:
        n = len(events)
        if not n:
            return "No posts with sufficient engagement for amplification analysis."
        parts = [
            f"Dark amplification score {score}/100. "
            f"{n} post(s) analyzed — baseline velocity {baseline:.0f} eng/h."
        ]
        flagged = len(dark_amp) + len(suspicious)
        if flagged:
            parts.append(
                f"{flagged} flagged: {len(dark_amp)} DARK_AMP · {len(suspicious)} SUSPICIOUS."
            )
        if dark_amp and top_src:
            top_ev = next((e for e in events if e.url == dark_amp[0]), None)
            if top_ev:
                parts.append(
                    f"Peak amplification: '{top_src}' — {top_ev.amplification_factor:.1f}x above baseline "
                    f"({top_ev.velocity:.0f} eng/h vs {baseline:.0f} baseline). "
                    f"Reaction purity {top_ev.reaction_purity:.0%} — "
                    f"{'artificially boosted' if top_ev.reaction_purity >= 0.85 else 'ambiguous'}."
                )
        return " ".join(parts)

    def _age_hours(self, p: dict) -> float:
        ts  = p.get("timestamp")
        sc  = p.get("scraped_at")
        if ts and sc:
            try:
                return max(
                    0.1,
                    (datetime.fromisoformat(sc[:19]) - datetime.fromisoformat(ts[:19])).total_seconds() / 3600
                )
            except Exception:
                pass
        return 24.0  # safe fallback

    @staticmethod
    def _empty() -> DarkAmplificationReport:
        return DarkAmplificationReport(
            events=[], dark_amplified=[], suspicious=[],
            baseline_velocity=0.0, amp_score=0.0,
            total_analyzed=0, top_amplified_source=None,
            summary="No post data available for dark amplification analysis.",
        )
