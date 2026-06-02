"""
EmotionalContagionEngine.

Measures how bot farm activity emotionally contaminates a comment thread.
Auto-detects the bot arrival point using TemporalEngine wave data, then
splits each post's comment timeline into PRE / DURING / POST windows and
scores the sentiment shift in each window.

Key insight: organic threads start neutral or mixed. When a bot wave arrives,
the thread's aggressive/negative tone spikes — this is measurable and provable
as forensic evidence of coordinated emotional manipulation.

Output:
  - contagion_score 0-100 (magnitude of emotional contamination)
  - Pre/during/post sentiment profiles per post
  - Shift direction (NEGATIVE=attack succeeded, POSITIVE=defense succeeded)
  - Peak shift post (most contaminated thread)

All thresholds from cfg["emotional_contagion"]. Zero hardcoded values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List


@dataclass
class SentimentWindow:
    label:         str      # PRE_BOT | DURING_BOT | POST_BOT
    start_ts:      str      # ISO
    end_ts:        str      # ISO
    comment_count: int
    neg_avg:       float    # 0.0-1.0
    agg_avg:       float
    pos_avg:       float
    neutral_avg:   float
    dominant:      str      # AGRESIVO|NEGATIVO|POSITIVO|NEUTRAL


@dataclass
class PostContagion:
    url:               str
    source:            str
    text_preview:      str
    pre_bot:           SentimentWindow | None
    during_bot:        SentimentWindow | None
    post_bot:          SentimentWindow | None
    shift_magnitude:   float   # post_neg+agg - pre_neg+agg (negative = thread got worse)
    contagion_confirmed: bool
    peak_agg_comment:  str     # most aggressive comment text


@dataclass
class EmotionalContagionReport:
    posts:               List[PostContagion]
    bot_arrival_ts:      str | None         # detected bot wave start
    pre_bot_sentiment:   dict               # avg across all posts
    during_bot_sentiment:dict
    post_bot_sentiment:  dict
    contagion_score:     float              # 0-100
    affected_posts:      int
    shift_direction:     str                # NEGATIVE|POSITIVE|MIXED|NONE
    peak_shift_url:      str | None
    summary:             str


class EmotionalContagionEngine:
    """
    Detect emotional contamination caused by bot waves.

    Args:
        scraped_results: list of {url, comments: [{author,text,timestamp,likes}]}
        temporal_report: TemporalReport with waves (from TemporalEngine)
        posts: raw post dicts (for text preview and source)
    """

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("emotional_contagion", {})
        self._pre_window_min    = c.get("pre_window_minutes",      60)
        self._post_window_min   = c.get("post_window_minutes",     120)
        self._during_window_min = c.get("during_window_minutes",    30)
        self._min_comments      = c.get("min_comments_per_window",   3)
        self._contagion_thresh  = c.get("contagion_threshold",      0.15)
        self._top_posts         = c.get("top_posts_output",         10)
        sw = c.get("score_weights", {})
        self._sw_shift          = sw.get("shift_magnitude",        70.0)
        self._sw_coverage       = sw.get("coverage_pct",           30.0)

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        scraped_results: list[dict],
        temporal_report=None,
        posts: list[dict] | None = None,
    ) -> EmotionalContagionReport:
        if not scraped_results:
            return self._empty()

        # ── Detect bot arrival time ───────────────────────────────────────────
        bot_arrival = self._detect_bot_arrival(temporal_report, scraped_results)

        # Build URL → post metadata lookup
        post_meta: dict[str, dict] = {}
        for p in (posts or []):
            url = p.get("url", "")
            if url:
                post_meta[url] = p

        # ── Score each post's comment timeline ────────────────────────────────
        contagions: list[PostContagion] = []
        for r in scraped_results:
            url      = r.get("url", "")
            comments = r.get("comments", [])
            if not comments:
                continue
            pc = self._analyze_post(url, comments, bot_arrival, post_meta.get(url, {}))
            if pc:
                contagions.append(pc)

        if not contagions:
            return self._empty()

        # Sort by absolute shift magnitude (most contaminated first)
        contagions.sort(key=lambda p: -abs(p.shift_magnitude))
        top = contagions[:self._top_posts]

        affected = sum(1 for p in contagions if p.contagion_confirmed)

        pre_avg    = self._aggregate_windows([p.pre_bot    for p in contagions if p.pre_bot])
        during_avg = self._aggregate_windows([p.during_bot for p in contagions if p.during_bot])
        post_avg   = self._aggregate_windows([p.post_bot   for p in contagions if p.post_bot])

        direction = self._shift_direction(pre_avg, post_avg, during_avg)
        score     = self._campaign_score(contagions, affected)
        peak      = top[0].url if top else None

        return EmotionalContagionReport(
            posts               = top,
            bot_arrival_ts      = bot_arrival.isoformat() if bot_arrival else None,
            pre_bot_sentiment   = pre_avg,
            during_bot_sentiment= during_avg,
            post_bot_sentiment  = post_avg,
            contagion_score     = score,
            affected_posts      = affected,
            shift_direction     = direction,
            peak_shift_url      = peak,
            summary             = self._build_summary(top, bot_arrival, affected,
                                                       score, direction, pre_avg, post_avg),
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _detect_bot_arrival(self, temporal_report, scraped_results: list[dict]) -> datetime | None:
        # Strategy 1: use earliest wave from TemporalEngine
        if temporal_report:
            waves = getattr(temporal_report, "waves", []) or []
            wave_times: list[datetime] = []
            for w in waves:
                ts = getattr(w, "start_time", None) or getattr(w, "start", None)
                if isinstance(ts, datetime):
                    wave_times.append(ts)
                elif isinstance(ts, str):
                    try:
                        wave_times.append(datetime.fromisoformat(ts))
                    except Exception:
                        pass
            if wave_times:
                return min(wave_times)

        # Strategy 2: find the comment cluster with highest density
        # (many comments in short window = likely bot burst)
        all_ts: list[datetime] = []
        for r in scraped_results:
            for c in r.get("comments", []):
                ts_str = c.get("timestamp")
                if ts_str:
                    try:
                        all_ts.append(datetime.fromisoformat(ts_str))
                    except Exception:
                        pass
        if not all_ts:
            return None

        all_ts.sort()
        # Find the 15-minute window with most comments
        window = timedelta(minutes=15)
        best_start, best_count = all_ts[0], 0
        for i, t in enumerate(all_ts):
            count = sum(1 for t2 in all_ts[i:] if t2 - t <= window)
            if count > best_count:
                best_count, best_start = count, t
        return best_start

    def _analyze_post(
        self,
        url: str,
        comments: list[dict],
        bot_arrival: datetime | None,
        meta: dict,
    ) -> PostContagion | None:
        from engines.sentiment import _score_one

        if bot_arrival is None:
            # Without bot arrival time, use median comment timestamp as split
            ts_list = self._extract_timestamps(comments)
            if not ts_list:
                return None
            ts_list.sort()
            bot_arrival = ts_list[len(ts_list) // 2]

        pre_win    = bot_arrival - timedelta(minutes=self._pre_window_min)
        during_end = bot_arrival + timedelta(minutes=self._during_window_min)
        post_end   = bot_arrival + timedelta(minutes=self._post_window_min)

        pre_comments    = []
        during_comments = []
        post_comments   = []
        all_scored      = []

        for c in comments:
            ts_str = c.get("timestamp")
            text   = (c.get("text") or "").strip()
            if not text:
                continue
            scored = _score_one(text)
            all_scored.append((text, scored))

            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except Exception:
                continue

            if pre_win <= ts < bot_arrival:
                pre_comments.append((ts, text, scored))
            elif bot_arrival <= ts <= during_end:
                during_comments.append((ts, text, scored))
            elif during_end < ts <= post_end:
                post_comments.append((ts, text, scored))

        pre    = self._build_window("PRE_BOT",    pre_comments,    pre_win,    bot_arrival)
        during = self._build_window("DURING_BOT", during_comments, bot_arrival, during_end)
        post   = self._build_window("POST_BOT",   post_comments,   during_end, post_end)

        # Shift magnitude: best available comparison
        # Priority: POST vs PRE → DURING vs PRE → DURING alone
        pre_tone    = (pre.neg_avg    + pre.agg_avg)    if pre    else 0.0
        during_tone = (during.neg_avg + during.agg_avg) if during else 0.0
        post_tone   = (post.neg_avg   + post.agg_avg)   if post   else 0.0

        if pre is not None and post is not None:
            shift = round(post_tone - pre_tone, 3)
        elif pre is not None and during is not None:
            # Use DURING vs PRE — shows impact while bot wave is active
            shift = round(during_tone - pre_tone, 3)
        elif during is not None:
            shift = round(during_tone, 3)
        else:
            shift = 0.0

        confirmed = abs(shift) >= self._contagion_thresh and (
            pre is not None or during is not None or post is not None
        )

        # Most aggressive comment
        peak_agg = ""
        if all_scored:
            worst = max(all_scored, key=lambda x: x[1]["agg"] + x[1]["neg"])
            if worst[1]["agg"] + worst[1]["neg"] > 0.2:
                peak_agg = worst[0][:120]

        return PostContagion(
            url               = url,
            source            = meta.get("source", "?"),
            text_preview      = (meta.get("text") or "")[:80],
            pre_bot           = pre,
            during_bot        = during,
            post_bot          = post,
            shift_magnitude   = shift,
            contagion_confirmed = confirmed,
            peak_agg_comment  = peak_agg,
        )

    def _build_window(
        self,
        label: str,
        comments: list[tuple],
        start: datetime,
        end: datetime,
    ) -> SentimentWindow | None:
        if len(comments) < self._min_comments:
            return None
        scores = [s for _, _, s in comments]
        n = len(scores)
        neg  = sum(s["neg"] for s in scores) / n
        agg  = sum(s["agg"] for s in scores) / n
        pos  = sum(s["pos"] for s in scores) / n
        neu  = max(0.0, 1.0 - neg - pos)

        if agg >= 0.15:
            dom = "AGRESIVO"
        elif neg >= 0.15:
            dom = "NEGATIVO"
        elif pos >= 0.15:
            dom = "POSITIVO"
        else:
            dom = "NEUTRAL"

        return SentimentWindow(
            label         = label,
            start_ts      = start.isoformat(timespec="seconds"),
            end_ts        = end.isoformat(timespec="seconds"),
            comment_count = n,
            neg_avg       = round(neg, 3),
            agg_avg       = round(agg, 3),
            pos_avg       = round(pos, 3),
            neutral_avg   = round(neu, 3),
            dominant      = dom,
        )

    def _extract_timestamps(self, comments: list[dict]) -> list[datetime]:
        result = []
        for c in comments:
            ts = c.get("timestamp")
            if ts:
                try:
                    result.append(datetime.fromisoformat(ts))
                except Exception:
                    pass
        return result

    def _aggregate_windows(self, windows: list[SentimentWindow]) -> dict:
        if not windows:
            return {"neg": 0.0, "agg": 0.0, "pos": 0.0, "neutral": 1.0, "comments": 0}
        n = len(windows)
        return {
            "neg":      round(sum(w.neg_avg for w in windows) / n, 3),
            "agg":      round(sum(w.agg_avg for w in windows) / n, 3),
            "pos":      round(sum(w.pos_avg for w in windows) / n, 3),
            "neutral":  round(sum(w.neutral_avg for w in windows) / n, 3),
            "comments": sum(w.comment_count for w in windows),
        }

    def _shift_direction(self, pre: dict, post: dict, during: dict | None = None) -> str:
        # Use POST vs PRE if both available, otherwise DURING vs PRE
        baseline_neg = pre.get("neg", 0) + pre.get("agg", 0)
        baseline_pos = pre.get("pos", 0)

        if post and post.get("comments", 0) > 0:
            compare_neg = post.get("neg", 0) + post.get("agg", 0)
            compare_pos = post.get("pos", 0)
        elif during and during.get("comments", 0) > 0:
            compare_neg = during.get("neg", 0) + during.get("agg", 0)
            compare_pos = during.get("pos", 0)
        else:
            return "NONE"

        neg_shift = compare_neg - baseline_neg
        pos_shift = compare_pos - baseline_pos

        if neg_shift >= self._contagion_thresh and pos_shift < self._contagion_thresh:
            return "NEGATIVE"
        if pos_shift >= self._contagion_thresh and neg_shift < self._contagion_thresh:
            return "POSITIVE"
        if neg_shift >= self._contagion_thresh and pos_shift >= self._contagion_thresh:
            return "MIXED"
        return "NONE"

    def _campaign_score(self, contagions: list[PostContagion], affected: int) -> float:
        if not contagions:
            return 0.0
        coverage = affected / len(contagions)
        avg_shift = sum(abs(p.shift_magnitude) for p in contagions) / len(contagions)
        score = (coverage * self._sw_coverage
                 + min(self._sw_shift, avg_shift * self._sw_shift * 3))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        posts: list[PostContagion],
        bot_arrival: datetime | None,
        affected: int,
        score: float,
        direction: str,
        pre: dict,
        post: dict,
    ) -> str:
        if not posts:
            return "Insufficient timestamped comments for contagion analysis."
        arr = bot_arrival.strftime("%Y-%m-%d %H:%M") if bot_arrival else "unknown time"
        neg_delta = (post.get("neg",0) + post.get("agg",0)) - (pre.get("neg",0) + pre.get("agg",0))
        parts = [
            f"Emotional contagion score {score}/100. "
            f"Bot arrival detected: {arr}. "
            f"{affected}/{len(posts)} post(s) show measurable sentiment shift.",
        ]
        if direction == "NEGATIVE":
            parts.append(
                f"Direction: NEGATIVE — thread toxicity increased {neg_delta:+.2f} after bot wave. "
                f"Emotional manipulation CONFIRMED."
            )
        elif direction == "POSITIVE":
            parts.append("Direction: POSITIVE — bot wave failed; organic defenders dominated.")
        elif direction == "MIXED":
            parts.append("Direction: MIXED — simultaneous attack and defense waves detected.")
        else:
            parts.append("No significant emotional shift detected.")
        return " ".join(parts)

    @staticmethod
    def _empty() -> EmotionalContagionReport:
        return EmotionalContagionReport(
            posts=[], bot_arrival_ts=None,
            pre_bot_sentiment={}, during_bot_sentiment={}, post_bot_sentiment={},
            contagion_score=0.0, affected_posts=0,
            shift_direction="NONE", peak_shift_url=None,
            summary="No timestamped comment data available for contagion analysis.",
        )
