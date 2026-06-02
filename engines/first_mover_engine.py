"""
FirstMoverEngine — N1: First-Mover Analysis.

All parameters read from cfg["first_mover"]. Zero hardcoded values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FirstMoverEvent:
    actor:    str
    post_url: str
    position: int
    timestamp:datetime
    text:     str


@dataclass
class FirstMoverProfile:
    actor:           str
    seed_count:      int
    avg_position:    float
    posts:           list[str]
    sample_texts:    list[str]
    is_seed_account: bool


@dataclass
class SeedingTeam:
    team_id: int
    actors:  list[str]
    posts:   list[str]


@dataclass
class FirstMoverReport:
    seed_accounts:   list[FirstMoverProfile]
    per_post_firsts: dict[str, list[str]]
    seeding_teams:   list[SeedingTeam]
    overall_score:   float
    top_seed_actors: list[str]
    summary:         str


class FirstMoverEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("first_mover", {})
        self.first_n        = c.get("first_n", 5)
        self.seed_threshold = c.get("seed_threshold", 3)
        self.team_co_min    = c.get("team_co_min", 2)
        self.top_seed_limit = c.get("top_seed_limit", 20)
        sw = c.get("score_weights", {})
        self._sw_seed_mult   = sw.get("seed_account_multiplier", 8.0)
        self._sw_max_seed    = sw.get("max_seed_score", 50.0)
        self._sw_team_mult   = sw.get("team_multiplier", 15.0)
        self._sw_max_team    = sw.get("max_team_score", 30.0)
        self._sw_dom_bonus   = sw.get("dominant_seed_bonus", 20.0)
        self._sw_dom_ratio   = sw.get("dominant_seed_ratio", 0.5)

    def analyze(self, scraped_results: list[dict]) -> FirstMoverReport:
        per_post: dict[str, list[FirstMoverEvent]] = {}

        for r in scraped_results:
            url      = r.get("url", "")
            comments = r.get("comments", [])

            ts_comments = []
            for c in comments:
                ts_str = c.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts_comments.append((datetime.fromisoformat(ts_str), c))
                except (ValueError, TypeError):
                    continue

            if len(ts_comments) < self.first_n:
                continue

            ts_comments.sort(key=lambda x: x[0])
            firsts: list[FirstMoverEvent] = []
            for pos, (ts, c) in enumerate(ts_comments[:self.first_n], 1):
                firsts.append(FirstMoverEvent(
                    actor=c.get("author", "?"),
                    post_url=url,
                    position=pos,
                    timestamp=ts,
                    text=c.get("text", "")[:100],
                ))
            per_post[url] = firsts

        actor_events: dict[str, list[FirstMoverEvent]] = {}
        for events in per_post.values():
            for ev in events:
                actor_events.setdefault(ev.actor, []).append(ev)

        profiles: list[FirstMoverProfile] = []
        for actor, events in actor_events.items():
            avg_pos  = sum(e.position for e in events) / len(events)
            posts    = list({e.post_url for e in events})
            profiles.append(FirstMoverProfile(
                actor=actor,
                seed_count=len(events),
                avg_position=round(avg_pos, 2),
                posts=posts,
                sample_texts=[e.text for e in events[:3]],
                is_seed_account=(len(events) >= self.seed_threshold),
            ))

        profiles.sort(key=lambda p: (-p.seed_count, p.avg_position))
        seed_accounts = [p for p in profiles if p.is_seed_account]

        seeding_teams   = self._detect_teams(per_post, seed_accounts)
        per_post_firsts = {url: [e.actor for e in evs] for url, evs in per_post.items()}
        score           = self._overall_score(seed_accounts, seeding_teams, per_post)
        summary         = self._build_summary(seed_accounts, seeding_teams, score, per_post)

        return FirstMoverReport(
            seed_accounts=seed_accounts,
            per_post_firsts=per_post_firsts,
            seeding_teams=seeding_teams,
            overall_score=score,
            top_seed_actors=[p.actor for p in seed_accounts[:self.top_seed_limit]],
            summary=summary,
        )

    def _detect_teams(
        self,
        per_post:      dict[str, list[FirstMoverEvent]],
        seed_accounts: list[FirstMoverProfile],
    ) -> list[SeedingTeam]:
        seed_set = {p.actor for p in seed_accounts}

        post_seed_sets: dict[str, frozenset[str]] = {
            url: frozenset(e.actor for e in evs if e.actor in seed_set)
            for url, evs in per_post.items()
        }
        post_seed_sets = {u: s for u, s in post_seed_sets.items() if len(s) >= 2}

        co: dict[tuple[str, str], list[str]] = {}
        for url, actor_set in post_seed_sets.items():
            actors = sorted(actor_set)
            for i, a in enumerate(actors):
                for b in actors[i + 1:]:
                    co.setdefault((a, b), []).append(url)

        team_cores: list[set[str]] = []
        for (a, b), urls in co.items():
            if len(urls) < self.team_co_min:
                continue
            merged = False
            for team in team_cores:
                if a in team or b in team:
                    team.add(a)
                    team.add(b)
                    merged = True
                    break
            if not merged:
                team_cores.append({a, b})

        teams: list[SeedingTeam] = []
        for tid, core in enumerate(team_cores, 1):
            co_posts = [url for url, aset in post_seed_sets.items() if core & aset]
            teams.append(SeedingTeam(team_id=tid, actors=sorted(core), posts=co_posts))

        return sorted(teams, key=lambda t: -len(t.posts))

    def _overall_score(
        self,
        seed_accounts: list[FirstMoverProfile],
        teams: list[SeedingTeam],
        per_post: dict,
    ) -> float:
        if not per_post:
            return 0.0
        n_posts = len(per_post)
        score   = min(self._sw_max_seed, len(seed_accounts) * self._sw_seed_mult)
        score  += min(self._sw_max_team, len(teams) * self._sw_team_mult)
        if seed_accounts and n_posts > 0:
            top = seed_accounts[0]
            if top.seed_count / n_posts >= self._sw_dom_ratio:
                score += self._sw_dom_bonus
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        seed_accounts: list[FirstMoverProfile],
        teams: list[SeedingTeam],
        score: float,
        per_post: dict,
    ) -> str:
        if not per_post:
            return "No timestamped comments available for first-mover analysis."
        parts = [f"{len(per_post)} post(s) analyzed for first-mover seeding patterns."]
        if seed_accounts:
            top = seed_accounts[0]
            parts.append(
                f"{len(seed_accounts)} seed account(s) detected "
                f"(appeared first in ≥{self.seed_threshold} posts). "
                f"Top seed: '{top.actor}' — first in {top.seed_count} post(s), "
                f"avg position {top.avg_position:.1f}."
            )
        if teams:
            parts.append(
                f"{len(teams)} coordinated seeding team(s) detected "
                f"(accounts consistently co-appearing in first-mover positions)."
            )
        if not seed_accounts:
            parts.append("No persistent seed accounts detected.")
        parts.append(f"First-mover coordination score: {score}/100.")
        return " ".join(parts)
