"""
AccountVelocityEngine — N4: Account Velocity Profile.

Estimates comments-per-hour (CPH) rate per actor across all analyzed posts.
BOT_VELOCITY = CPH above cfg threshold, SUSPICIOUS = intermediate, HUMAN = organic.
All parameters read from cfg["velocity"]. Zero hardcoded values.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime


@dataclass
class VelocityProfile:
    actor:           str
    total_comments:  int
    unique_posts:    int
    first_seen:      datetime | None
    last_seen:       datetime | None
    span_hours:      float
    cph:             float
    multi_post_ratio: float   # unique_posts / total_comments
    velocity_label:  str      # BOT_VELOCITY | SUSPICIOUS | HUMAN
    velocity_score:  int      # 0-100 (higher = more bot-like)


@dataclass
class AccountVelocityReport:
    profiles:             list[VelocityProfile]
    bot_velocity_actors:  list[str]
    suspicious_actors:    list[str]
    mean_cph:             float
    max_cph:              float
    velocity_score:       float
    total_actors:         int
    summary:              str


class AccountVelocityEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("velocity", {})
        self.bot_cph        = c.get("bot_cph_threshold",        15.0)
        self.susp_cph       = c.get("suspicious_cph_threshold",  7.0)
        self.min_comments   = c.get("min_comments",              2)
        self.min_span_h     = c.get("min_span_hours",            0.25)
        self.top_n          = c.get("top_actors_output",         30)
        sw = c.get("score_weights", {})
        self._sw_bot_pct    = sw.get("bot_pct",                 60.0)
        self._sw_cph_mult   = sw.get("max_cph_multiplier",       1.5)
        self._sw_cph_cap    = sw.get("max_cph_score",           40.0)

    def analyze(self, scraped_results: list[dict]) -> AccountVelocityReport:
        # actor → list of (timestamp, post_url)
        actor_events: dict[str, list[tuple[datetime, str]]] = defaultdict(list)

        for r in scraped_results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                actor  = c.get("author", "?")
                ts_str = c.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    continue
                actor_events[actor].append((ts, url))

        if not actor_events:
            return self._empty()

        profiles: list[VelocityProfile] = []
        for actor, events in actor_events.items():
            if len(events) < self.min_comments:
                continue
            events.sort(key=lambda x: x[0])
            timestamps     = [e[0] for e in events]
            unique_posts   = len({e[1] for e in events})
            first_seen     = timestamps[0]
            last_seen      = timestamps[-1]
            span_s         = (last_seen - first_seen).total_seconds()
            span_hours     = max(span_s / 3600.0, self.min_span_h)
            cph            = round(len(events) / span_hours, 2)
            multi_ratio    = round(unique_posts / len(events), 3)

            if cph >= self.bot_cph:
                label = "BOT_VELOCITY"
                score = min(100, int(60 + (cph - self.bot_cph) * 2))
            elif cph >= self.susp_cph:
                label = "SUSPICIOUS"
                score = int(30 + (cph - self.susp_cph) / (self.bot_cph - self.susp_cph) * 30)
            else:
                label = "HUMAN"
                score = max(0, int(cph / self.susp_cph * 30))

            profiles.append(VelocityProfile(
                actor=actor,
                total_comments=len(events),
                unique_posts=unique_posts,
                first_seen=first_seen,
                last_seen=last_seen,
                span_hours=round(span_hours, 3),
                cph=cph,
                multi_post_ratio=multi_ratio,
                velocity_label=label,
                velocity_score=score,
            ))

        profiles.sort(key=lambda p: (-p.cph, -p.total_comments))

        bot_vels  = [p.actor for p in profiles if p.velocity_label == "BOT_VELOCITY"]
        suspic    = [p.actor for p in profiles if p.velocity_label == "SUSPICIOUS"]
        mean_cph  = round(sum(p.cph for p in profiles) / max(len(profiles), 1), 2)
        max_cph   = round(max((p.cph for p in profiles), default=0.0), 2)
        score     = self._overall_score(profiles, bot_vels)
        summary   = self._build_summary(profiles, bot_vels, suspic, score)

        return AccountVelocityReport(
            profiles=profiles[:self.top_n],
            bot_velocity_actors=bot_vels,
            suspicious_actors=suspic,
            mean_cph=mean_cph,
            max_cph=max_cph,
            velocity_score=score,
            total_actors=len(profiles),
            summary=summary,
        )

    def _overall_score(self, profiles: list[VelocityProfile], bot_vels: list[str]) -> float:
        if not profiles:
            return 0.0
        bot_pct  = len(bot_vels) / len(profiles)
        max_cph  = max((p.cph for p in profiles), default=0.0)
        score    = (bot_pct * self._sw_bot_pct +
                    min(self._sw_cph_cap, max_cph * self._sw_cph_mult))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        profiles: list[VelocityProfile],
        bot_vels: list[str],
        suspic: list[str],
        score: float,
    ) -> str:
        if not profiles:
            return "No actors with sufficient comment history to profile."
        parts = [f"{len(profiles)} actors profiled — velocity score {score}/100."]
        if bot_vels:
            top3 = ", ".join(bot_vels[:3])
            parts.append(
                f"{len(bot_vels)} BOT_VELOCITY actor(s) detected "
                f"(CPH ≥ {self.bot_cph}): {top3}."
            )
        if suspic:
            parts.append(f"{len(suspic)} SUSPICIOUS actor(s) with elevated comment rate.")
        return " ".join(parts)

    @staticmethod
    def _empty() -> AccountVelocityReport:
        return AccountVelocityReport(
            profiles=[], bot_velocity_actors=[], suspicious_actors=[],
            mean_cph=0.0, max_cph=0.0, velocity_score=0.0,
            total_actors=0,
            summary="No timestamped comments available for velocity analysis.",
        )
