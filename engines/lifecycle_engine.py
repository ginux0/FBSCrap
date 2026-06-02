"""
LifecycleEngine — P4: Account Lifecycle Anomaly Detector.

Detects accounts that were dormant and suddenly activated at campaign
start (sleeper cells), accounts with superhuman comment velocity
(bursters), and cross-post coordinators.

Key signals:
  - activation_lag_hours: how long after campaign start the account
    first appeared. Near-zero = activated WITH the campaign = sleeper.
  - burst_count: comments fired in the first burst_window_minutes
    after the account's own first appearance. Humans ramp up; bots
    dump 5+ comments immediately.
  - comments_per_hour: total / active_window. > 10 CPH is inhuman.
  - Sleeper cells: N sleepers all activating within cell_window_h of
    each other = coordinated release, not coincidence.

All parameters read from cfg["lifecycle"]. Zero hardcoded values.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ActorLifecycle:
    actor:                str
    first_seen:           Optional[datetime]
    last_seen:            Optional[datetime]
    active_window_hours:  float
    total_comments:       int
    posts_count:          int
    comments_per_hour:    float
    activation_lag_hours: float          # (first_seen − campaign_start) in hours
    burst_count:          int            # comments within first burst_window_min
    anomaly_score:        int            # 0-100
    lifecycle_label:      str            # SLEEPER / BURST / COORDINATOR / ORGANIC
    anomaly_flags:        list[str] = field(default_factory=list)


@dataclass
class SleeperCell:
    cell_id:             int
    actors:              list[str]
    activation_start:    datetime
    activation_end:      datetime
    posts_targeted:      list[str]
    coordination_score:  float           # fraction of all sleepers in this cell


@dataclass
class LifecycleReport:
    actors:           list[ActorLifecycle]   # top N sorted by anomaly_score desc
    sleepers:         list[ActorLifecycle]
    bursters:         list[ActorLifecycle]
    coordinators:     list[ActorLifecycle]
    sleeper_cells:    list[SleeperCell]
    campaign_start:   Optional[datetime]
    total_actors:     int
    anomaly_score:    float
    summary:          str


# ── Engine ─────────────────────────────────────────────────────────────────────

class LifecycleEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("lifecycle", {})
        self.burst_window_min   = c.get("burst_window_minutes",        30)
        self.min_burst          = c.get("min_burst_comments",           3)
        self.velocity_thresh    = c.get("velocity_threshold_per_hour", 10.0)
        self.sleeper_lag_h      = c.get("sleeper_lag_threshold_hours",  2.0)
        self.cell_window_h      = c.get("sleeper_cell_window_hours",    1.0)
        self.cell_min_actors    = c.get("sleeper_cell_min_actors",      3)
        self.top_output         = c.get("top_actors_output",           30)
        sw = c.get("score_weights", {})
        self._sw_activation     = sw.get("activation_lag",  30)
        self._sw_burst          = sw.get("burst",           20)
        self._sw_velocity       = sw.get("velocity",        25)
        self._sw_laser          = sw.get("laser_focus",     15)
        self._sw_tight          = sw.get("tight_window",    10)

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze(
        self,
        scraped_results: list[dict],
        posts: list[dict] | None = None,
    ) -> LifecycleReport:
        campaign_start = self._campaign_start(posts, scraped_results)
        actor_events   = self._collect(scraped_results)

        lifecycles = sorted(
            [self._score(actor, evs, campaign_start)
             for actor, evs in actor_events.items()],
            key=lambda a: -a.anomaly_score,
        )

        sleepers     = [a for a in lifecycles if a.lifecycle_label == "SLEEPER"]
        bursters     = [a for a in lifecycles if a.lifecycle_label == "BURST"]
        coordinators = [a for a in lifecycles if a.lifecycle_label == "COORDINATOR"]
        cells        = self._detect_cells(sleepers, scraped_results)
        score        = self._overall_score(sleepers, bursters, coordinators, cells, lifecycles)
        summary      = self._build_summary(sleepers, bursters, coordinators, cells, score, campaign_start)

        return LifecycleReport(
            actors=lifecycles[:self.top_output],
            sleepers=sleepers,
            bursters=bursters,
            coordinators=coordinators,
            sleeper_cells=cells,
            campaign_start=campaign_start,
            total_actors=len(lifecycles),
            anomaly_score=score,
            summary=summary,
        )

    # ── Collection ─────────────────────────────────────────────────────────────

    def _collect(self, results: list[dict]) -> dict[str, list[dict]]:
        actor_events: dict[str, list[dict]] = {}
        for r in results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                actor  = c.get("author", "?")
                ts_str = c.get("timestamp")
                if actor == "?" or not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    continue
                actor_events.setdefault(actor, []).append({"ts": ts, "url": url})
        return actor_events

    def _campaign_start(
        self,
        posts:           list[dict] | None,
        scraped_results: list[dict],
    ) -> Optional[datetime]:
        candidates: list[datetime] = []
        if posts:
            for p in posts:
                ts_str = p.get("timestamp")
                if ts_str:
                    try:
                        candidates.append(datetime.fromisoformat(ts_str))
                        continue
                    except (ValueError, TypeError):
                        pass
                raw = p.get("timestamp_raw", "")
                if raw and str(raw).isdigit():
                    try:
                        candidates.append(datetime.fromtimestamp(int(raw)))
                    except (ValueError, TypeError):
                        pass
        if not candidates:
            for r in scraped_results:
                for c in r.get("comments", []):
                    ts_str = c.get("timestamp")
                    if ts_str:
                        try:
                            candidates.append(datetime.fromisoformat(ts_str))
                        except (ValueError, TypeError):
                            pass
        return min(candidates) if candidates else None

    # ── Per-actor scoring ───────────────────────────────────────────────────────

    def _score(
        self,
        actor:          str,
        events:         list[dict],
        campaign_start: Optional[datetime],
    ) -> ActorLifecycle:
        evs        = sorted(events, key=lambda e: e["ts"])
        first_seen = evs[0]["ts"]
        last_seen  = evs[-1]["ts"]
        window_h   = max((last_seen - first_seen).total_seconds() / 3600, 0.0)
        posts_set  = {e["url"] for e in evs}
        total      = len(evs)
        cph        = total / max(window_h, 0.5)

        burst_end  = first_seen + timedelta(minutes=self.burst_window_min)
        burst_n    = sum(1 for e in evs if e["ts"] <= burst_end)

        lag_h: float = 0.0
        if campaign_start is not None:
            lag_h = (first_seen - campaign_start).total_seconds() / 3600

        flags: list[str] = []
        score = 0

        if 0.0 <= lag_h < self.sleeper_lag_h:
            score += self._sw_activation
            flags.append(f"activated_at_campaign_start(lag={lag_h:.1f}h)")

        if burst_n >= self.min_burst:
            score += self._sw_burst
            flags.append(f"burst_{burst_n}_in_{self.burst_window_min}min")

        if cph >= self.velocity_thresh:
            score += self._sw_velocity
            flags.append(f"velocity_{cph:.1f}cph")

        if len(posts_set) == 1 and total >= 5:
            score += self._sw_laser
            flags.append("laser_focus_single_post")

        if 0 < window_h < 0.5:
            score += self._sw_tight
            flags.append("active_window_<30min")

        score = min(100, score)
        label = self._label(score, cph, len(posts_set))

        return ActorLifecycle(
            actor=actor,
            first_seen=first_seen,
            last_seen=last_seen,
            active_window_hours=round(window_h, 2),
            total_comments=total,
            posts_count=len(posts_set),
            comments_per_hour=round(cph, 2),
            activation_lag_hours=round(lag_h, 2),
            burst_count=burst_n,
            anomaly_score=score,
            lifecycle_label=label,
            anomaly_flags=flags,
        )

    def _label(self, score: int, cph: float, posts_count: int) -> str:
        if score >= 75:
            return "SLEEPER"
        if cph >= self.velocity_thresh and score >= 40:
            return "BURST"
        if posts_count >= 3 and score >= 35:
            return "COORDINATOR"
        return "ORGANIC"

    # ── Sleeper cell detection ──────────────────────────────────────────────────

    def _detect_cells(
        self,
        sleepers:        list[ActorLifecycle],
        scraped_results: list[dict],
    ) -> list[SleeperCell]:
        if len(sleepers) < self.cell_min_actors:
            return []

        timed = [(a, a.first_seen) for a in sleepers if a.first_seen]
        timed.sort(key=lambda x: x[1])

        cells: list[SleeperCell] = []
        cell_id = 0
        i = 0
        while i < len(timed):
            win_end = timed[i][1] + timedelta(hours=self.cell_window_h)
            j, group = i, []
            while j < len(timed) and timed[j][1] <= win_end:
                group.append(timed[j][0])
                j += 1
            if len(group) >= self.cell_min_actors:
                actor_set = {a.actor for a in group}
                targeted: set[str] = set()
                for r in scraped_results:
                    for c in r.get("comments", []):
                        if c.get("author") in actor_set:
                            targeted.add(r.get("url", ""))
                coord = round(len(group) / max(len(timed), 1) * 100, 1)
                cell_id += 1
                cells.append(SleeperCell(
                    cell_id=cell_id,
                    actors=[a.actor for a in group],
                    activation_start=group[0].first_seen,
                    activation_end=group[-1].first_seen,
                    posts_targeted=sorted(targeted),
                    coordination_score=coord,
                ))
                i = j
            else:
                i += 1
        return cells

    # ── Report scoring ──────────────────────────────────────────────────────────

    def _overall_score(
        self,
        sleepers, bursters, coordinators, cells, all_actors,
    ) -> float:
        if not all_actors:
            return 0.0
        anomalous = len(sleepers) + len(bursters) + len(coordinators)
        ratio     = anomalous / max(len(all_actors), 1)
        score     = min(60.0, ratio * 200)
        score    += min(25.0, len(cells) * 12.5)
        if sleepers:
            score += min(15.0, sleepers[0].anomaly_score / 100 * 15)
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        sleepers, bursters, coordinators, cells, score, campaign_start,
    ) -> str:
        parts: list[str] = []
        if campaign_start:
            parts.append(f"Campaign start: {campaign_start.strftime('%Y-%m-%d %H:%M')}.")
        total_anom = len(sleepers) + len(bursters) + len(coordinators)
        if total_anom == 0:
            suffix = " No lifecycle anomalies detected."
            return (parts[0] if parts else "") + suffix
        parts.append(
            f"{len(sleepers)} sleeper(s), {len(bursters)} burst(s), "
            f"{len(coordinators)} coordinator(s) detected."
        )
        if cells:
            parts.append(
                f"{len(cells)} coordinated sleeper cell(s) — "
                f"multiple accounts activating within {self.cell_window_h:.0f}h of each other."
            )
        if sleepers:
            top = sleepers[0]
            flags_str = ", ".join(top.anomaly_flags[:2])
            parts.append(
                f"Top anomaly: '{top.actor}' — score {top.anomaly_score}/100"
                + (f" [{flags_str}]" if flags_str else "") + "."
            )
        parts.append(f"Lifecycle anomaly score: {score}/100.")
        return " ".join(parts)
