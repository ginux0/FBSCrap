"""
HashtagWeaponizationEngine — N2: Hashtag Weaponization Detector.

Extracts hashtags from comment text, builds hourly adoption curves, detects
coordinated injection (seed → rapid growth → manufactured trending).
All parameters read from cfg["hashtag"]. Zero hardcoded values.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

_HASHTAG_RE = re.compile(r'#([A-Za-zÀ-ɏ0-9_]{2,})')


@dataclass
class HashtagEvent:
    hashtag:   str
    timestamp: datetime
    actor:     str
    post_url:  str
    text:      str


@dataclass
class HashtagProfile:
    hashtag:             str
    total_uses:          int
    unique_actors:       int
    posts_hit:           int
    first_actor:         str
    first_seen:          datetime | None
    peak_hour_count:     int
    adoption_rate:       float        # peak_hour / first_hour_count
    weaponized:          bool
    weaponization_label: str          # RAPID_SEEDING | AMPLIFIED | ORGANIC
    seeder_accounts:     list[str]    # first N actors to use the hashtag
    adoption_curve:      list[dict]   # [{"hour": "YYYY-MM-DD HH:00", "count": N}]


@dataclass
class HashtagWeaponizationReport:
    hashtag_profiles:    list[HashtagProfile]
    weaponized_hashtags: list[str]
    organic_hashtags:    list[str]
    top_seeders:         list[str]
    total_hashtags:      int
    weaponization_score: float
    summary:             str


class HashtagWeaponizationEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("hashtag", {})
        self.min_uses          = c.get("min_hashtag_uses",        3)
        self.min_actors        = c.get("min_unique_actors",        2)
        self.min_posts         = c.get("min_posts_hit",            1)
        self.rapid_ratio       = c.get("rapid_growth_ratio",       3.0)
        self.amplified_ratio   = c.get("amplified_ratio",          1.8)
        self.seeder_n          = c.get("seeder_window_events",     3)
        self.top_seeders_n     = c.get("top_seeders_output",      20)
        self.top_hashtags_n    = c.get("top_hashtags_output",     30)
        sw = c.get("score_weights", {})
        self._sw_weap_pct      = sw.get("weaponized_pct",         60.0)
        self._sw_rate_mult     = sw.get("avg_rate_multiplier",    15.0)
        self._sw_max_rate      = sw.get("max_rate_score",         40.0)

    def analyze(self, scraped_results: list[dict]) -> HashtagWeaponizationReport:
        events = self._collect_events(scraped_results)
        if not events:
            return self._empty()

        by_tag: dict[str, list[HashtagEvent]] = defaultdict(list)
        for ev in events:
            by_tag[ev.hashtag].append(ev)

        profiles:    list[HashtagProfile] = []
        all_seeders: dict[str, int]       = {}

        for tag, evs in by_tag.items():
            evs.sort(key=lambda e: e.timestamp)
            p = self._build_profile(tag, evs)
            if p is None:
                continue
            profiles.append(p)
            for s in p.seeder_accounts:
                all_seeders[s] = all_seeders.get(s, 0) + 1

        profiles.sort(key=lambda p: (-p.adoption_rate, -p.total_uses))
        profiles = profiles[:self.top_hashtags_n]

        weaponized  = [p.hashtag for p in profiles if p.weaponized]
        organic     = [p.hashtag for p in profiles if not p.weaponized]
        top_seeders = sorted(all_seeders, key=lambda s: -all_seeders[s])[:self.top_seeders_n]
        score       = self._overall_score(profiles)
        summary     = self._build_summary(profiles, weaponized, score)

        return HashtagWeaponizationReport(
            hashtag_profiles=profiles,
            weaponized_hashtags=weaponized,
            organic_hashtags=organic,
            top_seeders=top_seeders,
            total_hashtags=len(profiles),
            weaponization_score=score,
            summary=summary,
        )

    def _collect_events(self, scraped_results: list[dict]) -> list[HashtagEvent]:
        events: list[HashtagEvent] = []
        for r in scraped_results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                text   = c.get("text", "")
                ts_str = c.get("timestamp")
                actor  = c.get("author", "?")
                if not text or not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    continue
                for m in _HASHTAG_RE.finditer(text):
                    tag = "#" + m.group(1).lower()
                    events.append(HashtagEvent(
                        hashtag=tag, timestamp=ts,
                        actor=actor, post_url=url, text=text[:120],
                    ))
        return events

    def _build_profile(self, tag: str, evs: list[HashtagEvent]) -> HashtagProfile | None:
        unique_actors = len({e.actor   for e in evs})
        posts_hit     = len({e.post_url for e in evs})
        if len(evs) < self.min_uses or unique_actors < self.min_actors or posts_hit < self.min_posts:
            return None

        first_seen  = evs[0].timestamp
        first_actor = evs[0].actor
        seeders     = list(dict.fromkeys(e.actor for e in evs[:self.seeder_n]))

        hour_counts: dict[str, int] = defaultdict(int)
        for ev in evs:
            hour_counts[ev.timestamp.strftime("%Y-%m-%d %H:00")] += 1
        sorted_hours = sorted(hour_counts.items())
        adoption_curve = [{"hour": h, "count": n} for h, n in sorted_hours]

        first_h_count = sorted_hours[0][1] if sorted_hours else 1
        peak_h_count  = max(n for _, n in sorted_hours) if sorted_hours else 0
        adoption_rate = round(peak_h_count / max(first_h_count, 1), 2)

        if adoption_rate >= self.rapid_ratio and unique_actors >= self.min_actors:
            weaponized, label = True, "RAPID_SEEDING"
        elif adoption_rate >= self.amplified_ratio:
            weaponized, label = True, "AMPLIFIED"
        else:
            weaponized, label = False, "ORGANIC"

        return HashtagProfile(
            hashtag=tag,
            total_uses=len(evs),
            unique_actors=unique_actors,
            posts_hit=posts_hit,
            first_actor=first_actor,
            first_seen=first_seen,
            peak_hour_count=peak_h_count,
            adoption_rate=adoption_rate,
            weaponized=weaponized,
            weaponization_label=label,
            seeder_accounts=seeders,
            adoption_curve=adoption_curve[:24],
        )

    def _overall_score(self, profiles: list[HashtagProfile]) -> float:
        if not profiles:
            return 0.0
        weap = [p for p in profiles if p.weaponized]
        weap_pct  = len(weap) / len(profiles)
        avg_rate  = sum(p.adoption_rate for p in weap) / max(len(weap), 1)
        score = (weap_pct * self._sw_weap_pct +
                 min(self._sw_max_rate, avg_rate * self._sw_rate_mult))
        return round(min(100.0, score), 1)

    def _build_summary(
        self, profiles: list[HashtagProfile],
        weaponized: list[str], score: float,
    ) -> str:
        if not profiles:
            return "No hashtags found in comments."
        parts = [f"{len(profiles)} hashtag(s) tracked across analyzed comments."]
        if weaponized:
            top_tags = ", ".join(weaponized[:5])
            parts.append(
                f"{len(weaponized)} weaponized hashtag(s) detected "
                f"(coordinated injection — non-organic adoption curve). "
                f"Weaponization score: {score}/100. "
                f"Top weaponized: {top_tags}."
            )
        else:
            parts.append("No weaponized hashtag patterns detected — usage appears organic.")
        return " ".join(parts)

    @staticmethod
    def _empty() -> HashtagWeaponizationReport:
        return HashtagWeaponizationReport(
            hashtag_profiles=[], weaponized_hashtags=[],
            organic_hashtags=[], top_seeders=[],
            total_hashtags=0, weaponization_score=0.0,
            summary="No timestamped comments with hashtags available.",
        )
