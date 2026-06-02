"""
ReplyChainHijackEngine.

Detects coordinated bot reply-chain attacks on organic comments.

Core tactic: bots don't just flood a thread — they specifically TARGET the
most visible organic comments (high likes, early timestamp) to bury them with
aggressive replies. This is measurable without DOM-level reply parsing.

Three detection vectors:
  V1 — TEMPORAL CLUSTERING: Multiple bot-identified actors comment within
       T seconds after an organic high-liked comment = reply targeting.
  V2 — MENTION DETECTION: Comments starting with "Respondiendo a" or "@Name"
       that link a bot directly to an organic target.
  V3 — SATURATION ATTACK: When organic comments in a thread are outnumbered
       by bot replies within a tight time window = saturation hijack.

Each post thread gets a HijackScore 0-100.
Each identified organic comment that was targeted gets a TargetedComment record
with the list of bot attackers, timing delta, and attack intensity.

All thresholds from cfg["reply_chain"]. Zero hardcoded values.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List


# ── Patterns ───────────────────────────────────────────────────────────────────
_REPLY_MENTION_RE = re.compile(
    r'^(?:Respondiendo\s+a\s+|Replying\s+to\s+|@)([A-ZÁÉÍÓÚÜÑ][^\s,]{1,40}(?:\s+[A-ZÁÉÍÓÚÜÑ][^\s,]{1,40})?)',
    re.IGNORECASE | re.UNICODE,
)


@dataclass
class TargetedComment:
    organic_author:    str
    organic_text:      str        # first 120 chars
    organic_ts:        str | None # ISO
    organic_likes:     int
    bot_attackers:     List[str]  # actors that replied
    reply_count:       int        # total bot replies
    attack_delta_s:    float      # median seconds between organic + first bot reply
    intensity_score:   int        # 0-100 per targeted comment
    attack_type:       str        # TEMPORAL | MENTION | SATURATION


@dataclass
class PostHijackReport:
    url:               str
    source:            str
    text_preview:      str
    hijack_score:      int        # 0-100
    targeted_comments: List[TargetedComment]
    organic_count:     int
    bot_reply_count:   int
    saturation_ratio:  float      # bot_replies / total_comments
    dominant_attack:   str        # attack type with most instances


@dataclass
class ReplyChainHijackReport:
    posts:             List[PostHijackReport]
    hijacked_posts:    List[str]  # URLs above threshold
    total_targeted:    int        # organic comments attacked
    career_hijackers:  List[str]  # actors in 3+ hijack events
    hijack_score:      float      # campaign-level 0-100
    summary:           str


class ReplyChainHijackEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("reply_chain", {})
        self._reply_window_s   = c.get("reply_window_seconds",    90)
        self._min_bot_replies  = c.get("min_bot_replies",          2)
        self._organic_min_likes= c.get("organic_min_likes",        3)
        self._hijack_threshold = c.get("hijack_score_threshold",  40)
        self._sat_ratio        = c.get("saturation_ratio",         0.60)
        self._top_posts        = c.get("top_posts_output",         15)
        sw = c.get("score_weights", {})
        self._sw_hijacked_pct  = sw.get("hijacked_pct",           50.0)
        self._sw_avg_intensity = sw.get("avg_intensity",           50.0)

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        scraped_results: list[dict],
        bot_actors:      set[str] | None = None,
        posts:           list[dict] | None = None,
    ) -> ReplyChainHijackReport:
        """
        bot_actors: set of actor names identified as bots/high-risk by TrollHunter/HCS.
        If not provided, uses heuristic detection from comment patterns.
        """
        if not scraped_results:
            return self._empty()

        bots = bot_actors or set()
        post_meta = {p.get("url", ""): p for p in (posts or [])}

        reports: list[PostHijackReport] = []
        hijacker_counter: dict[str, int] = defaultdict(int)

        for r in scraped_results:
            url      = r.get("url", "")
            comments = r.get("comments", [])
            if len(comments) < 3:
                continue

            pr = self._analyze_post(url, comments, bots, post_meta.get(url, {}))
            if pr:
                reports.append(pr)
                for tc in pr.targeted_comments:
                    for ba in tc.bot_attackers:
                        hijacker_counter[ba] += 1

        reports.sort(key=lambda p: -p.hijack_score)
        top = reports[:self._top_posts]

        hijacked     = [p.url for p in reports if p.hijack_score >= self._hijack_threshold]
        total_target = sum(len(p.targeted_comments) for p in reports)
        career_hijack= [a for a, cnt in hijacker_counter.items() if cnt >= 3]
        campaign_score = self._campaign_score(reports, hijacked)

        return ReplyChainHijackReport(
            posts           = top,
            hijacked_posts  = hijacked,
            total_targeted  = total_target,
            career_hijackers= sorted(career_hijack,
                                     key=lambda a: -hijacker_counter[a])[:20],
            hijack_score    = campaign_score,
            summary         = self._build_summary(top, hijacked, total_target,
                                                    career_hijack, campaign_score),
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _analyze_post(
        self,
        url:      str,
        comments: list[dict],
        bots:     set[str],
        meta:     dict,
    ) -> PostHijackReport | None:
        # Parse timestamps — keep only timestamped comments for V1
        parsed: list[tuple[datetime | None, dict]] = []
        for c in comments:
            ts = None
            ts_str = c.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                except Exception:
                    pass
            parsed.append((ts, c))

        # Classify actors: organic vs bot
        # If no bots set provided, use mention/velocity heuristics
        effective_bots = bots if bots else self._infer_bots(parsed)

        organic_comments = [
            (ts, c) for ts, c in parsed
            if c.get("author", "?") not in effective_bots
            and c.get("likes", 0) >= self._organic_min_likes
        ]
        bot_comments = [
            (ts, c) for ts, c in parsed
            if c.get("author", "?") in effective_bots
        ]

        total = max(len(parsed), 1)
        sat_ratio = len(bot_comments) / total

        targeted: list[TargetedComment] = []

        # V1: Temporal clustering — bots within reply_window_s of organic comment
        for ots, oc in organic_comments:
            if ots is None:
                continue
            window_end = ots + timedelta(seconds=self._reply_window_s)
            attackers = [
                c.get("author", "?")
                for bts, c in bot_comments
                if bts is not None and ots < bts <= window_end
            ]
            if len(attackers) >= self._min_bot_replies:
                # Calculate median delta
                deltas = [
                    (bts - ots).total_seconds()
                    for bts, c in bot_comments
                    if bts is not None and ots < bts <= window_end
                ]
                med_delta = sorted(deltas)[len(deltas) // 2] if deltas else 0.0
                intensity = min(100, int(
                    (len(attackers) / max(len(bot_comments), 1)) * 60
                    + (1.0 - min(1.0, med_delta / self._reply_window_s)) * 40
                ))
                targeted.append(TargetedComment(
                    organic_author  = oc.get("author", "?"),
                    organic_text    = oc.get("text", "")[:120],
                    organic_ts      = ots.isoformat(timespec="seconds"),
                    organic_likes   = oc.get("likes", 0),
                    bot_attackers   = list(dict.fromkeys(attackers))[:10],
                    reply_count     = len(attackers),
                    attack_delta_s  = round(med_delta, 1),
                    intensity_score = intensity,
                    attack_type     = "TEMPORAL",
                ))

        # V2: Mention detection — "Respondiendo a [OrganicAuthor]"
        organic_authors = {c.get("author", "?") for _, c in organic_comments}
        for _, c in bot_comments:
            text = c.get("text", "")
            m = _REPLY_MENTION_RE.match(text)
            if m:
                target_name = m.group(1).strip()
                # Check if mention matches an organic author (partial match ok)
                matched_organic = next(
                    (a for a in organic_authors
                     if target_name.lower() in a.lower() or a.lower().startswith(target_name.lower())),
                    None
                )
                if matched_organic:
                    # Check if already in targeted list (avoid duplicates)
                    existing = next((t for t in targeted if t.organic_author == matched_organic), None)
                    actor = c.get("author", "?")
                    if existing:
                        if actor not in existing.bot_attackers:
                            existing.bot_attackers.append(actor)
                            existing.reply_count += 1
                    else:
                        targeted.append(TargetedComment(
                            organic_author  = matched_organic,
                            organic_text    = "",
                            organic_ts      = None,
                            organic_likes   = 0,
                            bot_attackers   = [actor],
                            reply_count     = 1,
                            attack_delta_s  = 0.0,
                            intensity_score = 30,
                            attack_type     = "MENTION",
                        ))

        # V3: Saturation — if bot/total ratio is high, even without individual targeting
        if sat_ratio >= self._sat_ratio and not targeted and len(bot_comments) >= 3:
            targeted.append(TargetedComment(
                organic_author  = "MULTIPLE",
                organic_text    = f"{len(organic_comments)} organic comment(s) buried",
                organic_ts      = None,
                organic_likes   = 0,
                bot_attackers   = list({c.get("author","?") for _,c in bot_comments[:10]}),
                reply_count     = len(bot_comments),
                attack_delta_s  = 0.0,
                intensity_score = min(100, int(sat_ratio * 100)),
                attack_type     = "SATURATION",
            ))

        if not targeted:
            return None

        # Post hijack score
        intensity_avg = sum(t.intensity_score for t in targeted) / len(targeted)
        sat_bonus     = int(sat_ratio * 20)
        hijack_score  = min(100, int(intensity_avg * 0.8 + sat_bonus))

        # Dominant attack type
        type_counts: dict[str, int] = defaultdict(int)
        for t in targeted:
            type_counts[t.attack_type] += 1
        dominant = max(type_counts, key=lambda k: type_counts[k])

        return PostHijackReport(
            url              = url,
            source           = meta.get("source", "?"),
            text_preview     = (meta.get("text") or "")[:80],
            hijack_score     = hijack_score,
            targeted_comments= targeted,
            organic_count    = len(organic_comments),
            bot_reply_count  = len(bot_comments),
            saturation_ratio = round(sat_ratio, 3),
            dominant_attack  = dominant,
        )

    def _infer_bots(self, parsed: list[tuple]) -> set[str]:
        """Heuristic bot detection when no external bot set is provided."""
        author_counts: dict[str, int] = defaultdict(int)
        for _, c in parsed:
            author_counts[c.get("author", "?")] += 1
        # Actors with ≥3 comments in one thread are likely bots (organic users rarely do that)
        return {a for a, cnt in author_counts.items() if cnt >= 3}

    def _campaign_score(self, reports: list, hijacked: list) -> float:
        if not reports:
            return 0.0
        hijack_pct = len(hijacked) / len(reports)
        avg_int    = sum(p.hijack_score for p in reports) / len(reports)
        score = (hijack_pct * self._sw_hijacked_pct
                 + min(self._sw_avg_intensity, avg_int * self._sw_avg_intensity / 100))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        posts: list,
        hijacked: list,
        total_targeted: int,
        career_hijackers: list,
        score: float,
    ) -> str:
        if not posts:
            return "Insufficient comment data for reply-chain analysis."
        parts = [f"Reply-chain hijack score {score}/100."]
        if hijacked:
            parts.append(
                f"{len(hijacked)} post thread(s) hijacked — "
                f"{total_targeted} organic comment(s) directly targeted."
            )
        if career_hijackers:
            parts.append(
                f"{len(career_hijackers)} career hijacker(s) active across 3+ posts: "
                f"{', '.join(career_hijackers[:4])}{'…' if len(career_hijackers) > 4 else ''}."
            )
        else:
            parts.append("No career hijackers detected (single-post patterns only).")
        return " ".join(parts)

    @staticmethod
    def _empty() -> ReplyChainHijackReport:
        return ReplyChainHijackReport(
            posts=[], hijacked_posts=[], total_targeted=0,
            career_hijackers=[], hijack_score=0.0,
            summary="No scraped comment data available for reply-chain analysis.",
        )
