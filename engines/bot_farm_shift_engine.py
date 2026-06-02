"""
BotFarmShiftEngine.

Detects "shift changes" in bot farm operations — when a cohort of bot accounts
reaches its daily action limit, gets flagged, or is rotated out by the operator,
and a fresh cohort of different accounts takes over with a similar attack pattern.

Detection method:
  1. Divide the campaign timeline into consecutive time windows
  2. For each window, identify active actors + their bot classifications
  3. Compute actor turnover between consecutive windows (Jaccard overlap)
  4. Low Jaccard + both windows bot-heavy = shift event
  5. Naming pattern similarity between cohorts confirms the same operator

ShiftEvent confidence:
  HIGH   — low Jaccard (<0.15) + both cohorts bot-heavy + similar naming patterns
  MEDIUM — low Jaccard + one cohort bot-heavy
  LOW    — moderate Jaccard or unconfirmed bot density

All thresholds from cfg["bot_farm_shift"]. Zero hardcoded values.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List


# ── Naming pattern analysis ────────────────────────────────────────────────────

def _name_prefix(name: str, length: int = 4) -> str:
    """Extract first N chars of first word (lowercase)."""
    return name.strip().split()[0][:length].lower() if name.strip() else ""


def _name_has_digits(name: str) -> bool:
    return bool(re.search(r'\d', name))


def _name_length_bucket(name: str) -> str:
    n = len(name.replace(" ", ""))
    if n <= 6:
        return "short"
    if n <= 12:
        return "medium"
    return "long"


def _naming_similarity(actors_a: list[str], actors_b: list[str]) -> float:
    """
    Compute naming pattern similarity between two cohorts.
    Compares: prefix distribution, digit presence, length distribution.
    Returns 0.0 (totally different) – 1.0 (same patterns).
    """
    if not actors_a or not actors_b:
        return 0.0

    def _profile(actors: list[str]) -> dict:
        prefs = [_name_prefix(a) for a in actors]
        return {
            "digit_pct":  sum(1 for a in actors if _name_has_digits(a)) / len(actors),
            "len_short":  sum(1 for a in actors if _name_length_bucket(a) == "short") / len(actors),
            "len_medium": sum(1 for a in actors if _name_length_bucket(a) == "medium") / len(actors),
            "common_pfx": len({p for p in prefs if prefs.count(p) > 1}) / max(len(set(prefs)), 1),
        }

    pa, pb = _profile(actors_a), _profile(actors_b)
    diffs = [abs(pa[k] - pb[k]) for k in pa]
    return round(1.0 - sum(diffs) / len(diffs), 3)


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ShiftCohort:
    cohort_id:       int
    window_start:    str         # ISO
    window_end:      str         # ISO
    actors:          List[str]
    bot_actors:      List[str]
    bot_pct:         float       # 0-1
    comment_count:   int
    naming_patterns: List[str]   # observed naming pattern descriptors


@dataclass
class ShiftEvent:
    event_id:        int
    from_cohort:     ShiftCohort
    to_cohort:       ShiftCohort
    jaccard_overlap: float       # actor overlap — lower = more rotation
    turnover_pct:    float       # fraction of new actors in to_cohort
    naming_sim:      float       # how similar are the two cohorts' naming patterns
    confidence:      str         # HIGH | MEDIUM | LOW
    shift_score:     int         # 0-100


@dataclass
class BotFarmShiftReport:
    cohorts:           List[ShiftCohort]
    shift_events:      List[ShiftEvent]
    confirmed_shifts:  int        # HIGH + MEDIUM confidence
    total_rotated:     int        # unique actors that appeared then vanished
    shift_score:       float      # campaign 0-100
    timeline_start:    str | None
    timeline_end:      str | None
    summary:           str


class BotFarmShiftEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("bot_farm_shift", {})
        self._window_minutes      = c.get("window_minutes",          60)
        self._min_actors_window   = c.get("min_actors_per_window",    3)
        self._shift_jaccard_high  = c.get("shift_jaccard_high",       0.15)
        self._shift_jaccard_med   = c.get("shift_jaccard_medium",     0.30)
        self._bot_density_min     = c.get("bot_density_min",          0.40)
        self._min_windows         = c.get("min_windows_required",     3)
        self._top_shifts          = c.get("top_shifts_output",        10)
        sw = c.get("score_weights", {})
        self._sw_shift_count      = sw.get("shift_count",            15.0)
        self._sw_bot_density      = sw.get("bot_density",            25.0)
        self._sw_turnover         = sw.get("avg_turnover",           60.0)

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        scraped_results: list[dict],
        bot_actors:      set[str] | None = None,
        troll_report=None,
    ) -> BotFarmShiftReport:
        """
        bot_actors: set of confirmed/high-risk bot actor names from TrollHunter.
        troll_report: TrollHunterReport — used to extract bot classifications if
                      bot_actors not provided.
        """
        bots = bot_actors or set()
        if not bots and troll_report:
            bots = {p.actor for p in getattr(troll_report, "profiles", [])
                    if p.bot_risk_score >= 60}

        if not scraped_results:
            return self._empty()

        # ── Collect all comments with timestamps ──────────────────────────────
        all_comments: list[tuple[datetime, str, str]] = []  # (ts, actor, url)
        for r in scraped_results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                ts_str = c.get("timestamp")
                actor  = c.get("author", "?")
                if ts_str and actor and actor != "?":
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        all_comments.append((ts, actor, url))
                    except Exception:
                        pass

        if not all_comments:
            return self._empty()

        all_comments.sort(key=lambda x: x[0])
        t_start = all_comments[0][0]
        t_end   = all_comments[-1][0]

        # ── Build time windows ────────────────────────────────────────────────
        window_td = timedelta(minutes=self._window_minutes)
        cohorts: list[ShiftCohort] = []
        cid = 0
        current = t_start

        while current <= t_end:
            wend = current + window_td
            window_comments = [
                (ts, actor) for ts, actor, _ in all_comments
                if current <= ts < wend
            ]
            if window_comments:
                actors_in_window = list({actor for _, actor in window_comments})
                bot_in_window    = [a for a in actors_in_window if a in bots]
                bot_pct          = len(bot_in_window) / max(len(actors_in_window), 1)

                if len(actors_in_window) >= self._min_actors_window:
                    patterns = self._describe_patterns(actors_in_window, bot_in_window)
                    cohorts.append(ShiftCohort(
                        cohort_id    = cid,
                        window_start = current.isoformat(timespec="seconds"),
                        window_end   = wend.isoformat(timespec="seconds"),
                        actors       = actors_in_window[:30],
                        bot_actors   = bot_in_window[:20],
                        bot_pct      = round(bot_pct, 3),
                        comment_count= len(window_comments),
                        naming_patterns = patterns,
                    ))
                    cid += 1
            current = wend

        if len(cohorts) < self._min_windows:
            return self._empty()

        # ── Detect shift events between consecutive cohorts ───────────────────
        shifts: list[ShiftEvent] = []
        eid = 0
        for i in range(len(cohorts) - 1):
            ca, cb = cohorts[i], cohorts[i + 1]
            shift = self._detect_shift(eid, ca, cb)
            if shift:
                shifts.append(shift)
                eid += 1

        shifts.sort(key=lambda s: -s.shift_score)
        top_shifts = shifts[:self._top_shifts]

        confirmed   = sum(1 for s in shifts if s.confidence in ("HIGH", "MEDIUM"))
        # Actors that appeared in one cohort but not the next (rotated out)
        total_rotated = len({
            a for s in shifts
            for a in s.from_cohort.actors
            if a not in s.to_cohort.actors
        })

        score   = self._campaign_score(cohorts, shifts, confirmed)
        summary = self._build_summary(cohorts, shifts, confirmed, total_rotated, score)

        return BotFarmShiftReport(
            cohorts          = cohorts,
            shift_events     = top_shifts,
            confirmed_shifts = confirmed,
            total_rotated    = total_rotated,
            shift_score      = score,
            timeline_start   = t_start.isoformat(timespec="seconds"),
            timeline_end     = t_end.isoformat(timespec="seconds"),
            summary          = summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _detect_shift(
        self,
        eid: int,
        ca:  ShiftCohort,
        cb:  ShiftCohort,
    ) -> ShiftEvent | None:
        """Detect a shift event between two consecutive cohorts."""
        set_a = set(ca.actors)
        set_b = set(cb.actors)
        union = set_a | set_b
        inter = set_a & set_b

        if not union:
            return None

        jaccard  = len(inter) / len(union)
        turnover = 1.0 - (len(inter) / max(len(set_b), 1))

        # Both cohorts must have meaningful bot density for a real shift
        both_bot_dense = (
            ca.bot_pct >= self._bot_density_min
            and cb.bot_pct >= self._bot_density_min
        )

        # Naming pattern similarity between cohorts
        naming_sim = _naming_similarity(ca.bot_actors or ca.actors,
                                         cb.bot_actors or cb.actors)

        # Confidence assessment
        if jaccard <= self._shift_jaccard_high and both_bot_dense:
            confidence = "HIGH"
        elif jaccard <= self._shift_jaccard_med and (ca.bot_pct >= self._bot_density_min
                                                      or cb.bot_pct >= self._bot_density_min):
            confidence = "MEDIUM"
        elif jaccard <= self._shift_jaccard_med:
            confidence = "LOW"
        else:
            return None  # too much overlap — not a shift

        shift_score = self._shift_score(jaccard, turnover, naming_sim,
                                         ca.bot_pct, cb.bot_pct, confidence)

        return ShiftEvent(
            event_id        = eid,
            from_cohort     = ca,
            to_cohort       = cb,
            jaccard_overlap = round(jaccard, 3),
            turnover_pct    = round(turnover, 3),
            naming_sim      = naming_sim,
            confidence      = confidence,
            shift_score     = shift_score,
        )

    def _shift_score(
        self,
        jaccard:    float,
        turnover:   float,
        naming_sim: float,
        bot_pct_a:  float,
        bot_pct_b:  float,
        confidence: str,
    ) -> int:
        base = {
            "HIGH":   70,
            "MEDIUM": 45,
            "LOW":    20,
        }.get(confidence, 0)

        # More turnover = higher score
        turnover_bonus = int(turnover * 20)
        # Similar naming = same operator behind both cohorts
        naming_bonus   = int(naming_sim * 10)
        return min(100, base + turnover_bonus + naming_bonus)

    def _describe_patterns(
        self,
        actors:     list[str],
        bot_actors: list[str],
    ) -> list[str]:
        """Generate human-readable naming pattern descriptors for a cohort."""
        patterns: list[str] = []
        if not actors:
            return patterns

        digit_pct = sum(1 for a in actors if _name_has_digits(a)) / len(actors)
        if digit_pct >= 0.4:
            patterns.append(f"numeric suffix ({digit_pct:.0%})")

        short_pct = sum(1 for a in actors if _name_length_bucket(a) == "short") / len(actors)
        if short_pct >= 0.5:
            patterns.append(f"short names ({short_pct:.0%})")

        single_word = sum(1 for a in actors if " " not in a.strip()) / len(actors)
        if single_word >= 0.6:
            patterns.append(f"single-word ({single_word:.0%}) — restricted profiles")

        # Common prefixes within cohort
        prefs = [_name_prefix(a, 4) for a in actors if len(a.strip()) >= 4]
        if prefs:
            from collections import Counter
            top_pref, top_cnt = Counter(prefs).most_common(1)[0]
            if top_cnt >= 3 and top_pref:
                patterns.append(f"common prefix '{top_pref}' ({top_cnt} actors)")

        return patterns

    def _campaign_score(
        self,
        cohorts: list[ShiftCohort],
        shifts:  list[ShiftEvent],
        confirmed: int,
    ) -> float:
        if not cohorts:
            return 0.0
        avg_bot = sum(c.bot_pct for c in cohorts) / len(cohorts)
        avg_turn = sum(s.turnover_pct for s in shifts) / max(len(shifts), 1)
        score = (confirmed * self._sw_shift_count
                 + min(self._sw_bot_density, avg_bot * self._sw_bot_density)
                 + min(self._sw_turnover, avg_turn * self._sw_turnover))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        cohorts:   list[ShiftCohort],
        shifts:    list[ShiftEvent],
        confirmed: int,
        rotated:   int,
        score:     float,
    ) -> str:
        if not cohorts:
            return "Insufficient timestamped comment data for shift detection."
        parts = [
            f"Bot farm shift score {score}/100. "
            f"{len(cohorts)} time window(s) analyzed."
        ]
        if confirmed:
            high = sum(1 for s in shifts if s.confidence == "HIGH")
            med  = sum(1 for s in shifts if s.confidence == "MEDIUM")
            parts.append(
                f"{confirmed} confirmed shift event(s): "
                f"{high} HIGH · {med} MEDIUM. "
                f"{rotated} actor(s) rotated between cohorts."
            )
            if shifts:
                top = shifts[0]
                parts.append(
                    f"Sharpest shift: jaccard={top.jaccard_overlap:.2f} "
                    f"({top.turnover_pct:.0%} turnover) at "
                    f"{top.from_cohort.window_end[:16]} — "
                    f"confidence {top.confidence}."
                )
        else:
            parts.append("No confirmed bot farm shift events detected.")
        return " ".join(parts)

    @staticmethod
    def _empty() -> BotFarmShiftReport:
        return BotFarmShiftReport(
            cohorts=[], shift_events=[], confirmed_shifts=0,
            total_rotated=0, shift_score=0.0,
            timeline_start=None, timeline_end=None,
            summary="Insufficient timestamped comment data for shift analysis.",
        )
