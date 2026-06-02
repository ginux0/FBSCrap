"""
TemporalEngine — P2: Temporal Attack Wave Detector.

Detects synchronized comment bursts that indicate coordinated inauthentic
behavior. A wave of comments from different accounts within ±N seconds is
statistically impossible for organic human traffic.

All parameters read from cfg["temporal_engine"]. Zero hardcoded values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class CommentEvent:
    author:   str
    ts:       datetime
    post_url: str
    text:     str
    likes:    int = 0


@dataclass
class SyncPair:
    author_a: str
    author_b: str
    ts_a:     datetime
    ts_b:     datetime
    delta_s:  float
    post_url: str


@dataclass
class AttackWave:
    wave_id:      int
    start:        datetime
    end:          datetime
    participants: list[str]
    events:       list[CommentEvent]
    duration_s:   float
    intensity:    float
    peak_density: float


@dataclass
class TemporalReport:
    waves:              list[AttackWave]
    sync_pairs:         list[SyncPair]
    overall_score:      float
    total_events:       int
    timestamped_events: int
    attack_timeline:    list[dict]
    suspicious_actors:  list[str]
    summary:            str


class TemporalEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("temporal_engine", {})
        self.wave_window_s      = c.get("wave_window_s", 60)
        self.wave_min_events    = c.get("wave_min_events", 3)
        self.wave_min_authors   = c.get("wave_min_authors", 2)
        self.sync_threshold_s   = c.get("sync_threshold_s", 3.0)
        self.peak_window_s      = c.get("peak_density_window_s", 10)
        self.merge_gap_ratio    = c.get("merge_gap_ratio", 0.5)
        self.sus_min_waves      = c.get("suspicious_actor_min_waves", 2)
        self.max_timeline       = c.get("max_timeline_buckets", 168)
        sw = c.get("score_weights", {})
        self._sw_intensity      = sw.get("wave_intensity_multiplier", 3.0)
        self._sw_wave_count     = sw.get("wave_count_multiplier", 5.0)
        self._sw_max_wave       = sw.get("max_wave_score", 60.0)
        self._sw_sync_pair      = sw.get("sync_pair_multiplier", 8.0)
        self._sw_max_sync       = sw.get("max_sync_score", 40.0)

    def analyze(self, scraped_results: list[dict]) -> TemporalReport:
        events = self._collect(scraped_results)
        events.sort(key=lambda e: e.ts)

        waves      = self._detect_waves(events)
        sync_pairs = self._detect_sync_pairs(events)
        score      = self._score(waves, sync_pairs, events)
        timeline   = self._timeline(events)
        sus        = self._suspicious_actors(waves)
        summary    = self._summary(waves, sync_pairs, score, events)

        return TemporalReport(
            waves=waves, sync_pairs=sync_pairs, overall_score=score,
            total_events=len(events), timestamped_events=len(events),
            attack_timeline=timeline, suspicious_actors=sus, summary=summary,
        )

    # ── Collection ───────────────────────────────────────────────────────────

    def _collect(self, results: list[dict]) -> list[CommentEvent]:
        events: list[CommentEvent] = []
        for r in results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                ts_str = c.get("timestamp")
                if not ts_str:
                    continue
                try:
                    events.append(CommentEvent(
                        author=c.get("author", "?"),
                        ts=datetime.fromisoformat(ts_str),
                        post_url=url,
                        text=c.get("text", ""),
                        likes=c.get("likes", 0),
                    ))
                except (ValueError, TypeError):
                    continue
        return events

    # ── Wave detection ────────────────────────────────────────────────────────

    def _detect_waves(self, events: list[CommentEvent]) -> list[AttackWave]:
        if not events:
            return []
        waves: list[AttackWave] = []
        wave_id = 0
        i = 0
        while i < len(events):
            window_end = events[i].ts + timedelta(seconds=self.wave_window_s)
            j, bucket = i, []
            while j < len(events) and events[j].ts <= window_end:
                bucket.append(events[j])
                j += 1
            authors = list({e.author for e in bucket})
            if len(bucket) >= self.wave_min_events and len(authors) >= self.wave_min_authors:
                dur = max((bucket[-1].ts - bucket[0].ts).total_seconds(), 1.0)
                wave_id += 1
                waves.append(AttackWave(
                    wave_id=wave_id,
                    start=bucket[0].ts, end=bucket[-1].ts,
                    participants=authors, events=bucket,
                    duration_s=dur,
                    intensity=round((len(authors) * len(bucket)) / dur, 3),
                    peak_density=self._peak(bucket),
                ))
                i = j
            else:
                i += 1
        return self._merge(waves)

    def _peak(self, events: list[CommentEvent]) -> float:
        if not events:
            return 0.0
        max_count = 0
        for i, e in enumerate(events):
            sub_end = e.ts + timedelta(seconds=self.peak_window_s)
            count   = sum(1 for f in events[i:] if f.ts <= sub_end)
            max_count = max(max_count, count)
        return float(max_count)

    def _merge(self, waves: list[AttackWave]) -> list[AttackWave]:
        if len(waves) <= 1:
            return waves
        gap_limit = self.wave_window_s * self.merge_gap_ratio
        merged = [waves[0]]
        for w in waves[1:]:
            prev = merged[-1]
            if (w.start - prev.end).total_seconds() <= gap_limit:
                all_ev  = list({id(e): e for e in prev.events + w.events}.values())
                all_ev.sort(key=lambda e: e.ts)
                authors = list({e.author for e in all_ev})
                dur     = max((all_ev[-1].ts - all_ev[0].ts).total_seconds(), 1.0)
                merged[-1] = AttackWave(
                    wave_id=prev.wave_id,
                    start=all_ev[0].ts, end=all_ev[-1].ts,
                    participants=authors, events=all_ev, duration_s=dur,
                    intensity=round((len(authors) * len(all_ev)) / dur, 3),
                    peak_density=max(prev.peak_density, w.peak_density),
                )
            else:
                merged.append(w)
        return merged

    # ── Sync pairs ────────────────────────────────────────────────────────────

    def _detect_sync_pairs(self, events: list[CommentEvent]) -> list[SyncPair]:
        pairs: list[SyncPair] = []
        for i, a in enumerate(events):
            for b in events[i + 1:]:
                delta = abs((b.ts - a.ts).total_seconds())
                if delta > self.sync_threshold_s:
                    break
                if a.author != b.author:
                    pairs.append(SyncPair(
                        author_a=a.author, author_b=b.author,
                        ts_a=a.ts, ts_b=b.ts,
                        delta_s=round(delta, 2), post_url=a.post_url,
                    ))
        return pairs

    # ── Score ─────────────────────────────────────────────────────────────────

    def _score(self, waves, pairs, events) -> float:
        if not events:
            return 0.0
        score = 0.0
        if waves:
            avg_i  = sum(w.intensity for w in waves) / len(waves)
            score += min(self._sw_max_wave,
                         avg_i * self._sw_intensity + len(waves) * self._sw_wave_count)
        score += min(self._sw_max_sync, len(pairs) * self._sw_sync_pair)
        return round(min(100.0, score), 1)

    def _timeline(self, events: list[CommentEvent]) -> list[dict]:
        buckets: dict[str, int] = {}
        for e in events:
            key = e.ts.strftime("%Y-%m-%dT%H:00")
            buckets[key] = buckets.get(key, 0) + 1
        sorted_items = sorted(buckets.items())[-self.max_timeline:]
        return [{"time": k, "count": v} for k, v in sorted_items]

    def _suspicious_actors(self, waves: list[AttackWave]) -> list[str]:
        count: dict[str, int] = {}
        for w in waves:
            for a in w.participants:
                count[a] = count.get(a, 0) + 1
        return [a for a, c in sorted(count.items(), key=lambda x: -x[1])
                if c >= self.sus_min_waves]

    def _summary(self, waves, pairs, score, events) -> str:
        if not events:
            return "No timestamped comments available for temporal analysis."
        parts = [f"{len(events)} timestamped events analyzed."]
        if waves:
            top = max(waves, key=lambda w: w.intensity)
            parts.append(
                f"{len(waves)} coordinated wave(s) detected (score {score}/100). "
                f"Peak: {len(top.participants)} actors, {len(top.events)} comments "
                f"in {top.duration_s:.0f}s (intensity {top.intensity})."
            )
        if pairs:
            parts.append(
                f"{len(pairs)} ultra-sync pair(s) ≤{self.sync_threshold_s}s — "
                f"statistically impossible organically."
            )
        if not waves and not pairs:
            parts.append("No significant temporal coordination detected.")
        return " ".join(parts)
