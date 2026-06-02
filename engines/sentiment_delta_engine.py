"""
SentimentDeltaEngine — P6: Sentiment Manipulation Delta.

All parameters and patterns read from cfg["sentiment_delta"]. Zero hardcoded values.
Pattern files: config/patterns/neg_sentiment_es.json + pos_sentiment_es.json
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).parent.parent


def _load_patterns(path_str: str, fallback: list[str]) -> list[re.Pattern]:
    try:
        p = _BASE_DIR / path_str
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [re.compile(pat, re.I) for pat in raw]
    except Exception:
        pass
    return [re.compile(pat, re.I) for pat in fallback]


_NEG_FALLBACK = [
    r'\b(odio|odia|odian)\b', r'\b(ladr[oó]n|ratero|roba)\b',
    r'\b(corrupto|corrupci[oó]n)\b', r'\b(mentiroso|miente)\b',
    r'\b(fuera|renuncia)\b', r'\b(fraude|trampa)\b', r'\b(basura|asco)\b',
]
_POS_FALLBACK = [
    r'\b(apoya|apoyo)\b', r'\b(excelente|genial|bueno)\b',
    r'\b(gracias|agradec[eo])\b', r'\b(progreso|avance|logro)\b',
]


@dataclass
class SentimentWindow:
    label:      str
    total:      int   = 0
    negative:   int   = 0
    positive:   int   = 0
    neutral:    int   = 0
    top_actors: list[str] = field(default_factory=list)

    @property
    def neg_ratio(self) -> float:
        return self.negative / self.total if self.total else 0.0

    @property
    def pos_ratio(self) -> float:
        return self.positive / self.total if self.total else 0.0


@dataclass
class PostSentimentDelta:
    post_url:            str
    post_text:           str
    windows:             list[SentimentWindow]
    manipulation_delta:  float
    manipulation_label:  str
    dominant_neg_actors: list[str]


@dataclass
class SentimentDeltaReport:
    post_deltas:        list[PostSentimentDelta]
    seeded_posts:       list[str]
    reversed_posts:     list[str]
    manipulation_score: float
    top_seed_accounts:  list[str]
    summary:            str


class SentimentDeltaEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("sentiment_delta", {})

        neg_file = c.get("neg_patterns_file", "config/patterns/neg_sentiment_es.json")
        pos_file = c.get("pos_patterns_file", "config/patterns/pos_sentiment_es.json")
        self._neg = _load_patterns(neg_file, _NEG_FALLBACK)
        self._pos = _load_patterns(pos_file, _POS_FALLBACK)

        raw_windows = c.get("window_hours", [2.0, 6.0, 24.0])
        self._window_hours  = raw_windows + [float("inf")]
        self._window_labels = self._build_labels(raw_windows)

        self.seeded_delta_threshold   = c.get("seeded_delta_threshold", 0.20)
        self.min_window_comments      = c.get("min_window_comments", 3)
        self.min_total_comments       = c.get("min_total_comments", 5)
        self.top_seed_actors_per_post = c.get("top_seed_actors_per_post", 8)
        self.top_seed_accounts_output = c.get("top_seed_accounts_output", 20)

        sw = c.get("score_weights", {})
        self._sw_seeded_pct  = sw.get("seeded_pct_weight", 60.0)
        self._sw_delta_mult  = sw.get("avg_delta_multiplier", 200.0)
        self._sw_max_delta   = sw.get("max_delta_score", 40.0)

    @staticmethod
    def _build_labels(hours: list[float]) -> list[str]:
        labels = []
        prev = 0
        for i, h in enumerate(hours):
            if h == float("inf"):
                labels.append(f"W{i}: {int(prev)}h+")
            else:
                labels.append(f"W{i}: {int(prev)}–{int(h)}h")
            prev = h
        labels.append(f"W{len(hours)}: {int(prev)}h+")
        return labels

    def _sentiment(self, text: str) -> int:
        neg = sum(1 for p in self._neg if p.search(text))
        pos = sum(1 for p in self._pos if p.search(text))
        if neg > pos:
            return -1
        if pos > neg:
            return 1
        return 0

    def analyze(self, scraped_results: list[dict]) -> SentimentDeltaReport:
        post_deltas: list[PostSentimentDelta] = []
        all_seed_actors: dict[str, int] = {}

        for r in scraped_results:
            delta = self._analyze_post(r)
            if delta:
                post_deltas.append(delta)
                if delta.manipulation_label == "SEEDED":
                    for a in delta.dominant_neg_actors:
                        all_seed_actors[a] = all_seed_actors.get(a, 0) + 1

        seeded    = [d.post_url for d in post_deltas if d.manipulation_label == "SEEDED"]
        reversed_ = [d.post_url for d in post_deltas if d.manipulation_label == "REVERSED"]
        score     = self._overall_score(post_deltas)
        top_seeds = sorted(all_seed_actors, key=lambda a: -all_seed_actors[a])[:self.top_seed_accounts_output]
        summary   = self._build_summary(post_deltas, seeded, reversed_, score)

        return SentimentDeltaReport(
            post_deltas=post_deltas,
            seeded_posts=seeded,
            reversed_posts=reversed_,
            manipulation_score=score,
            top_seed_accounts=top_seeds,
            summary=summary,
        )

    def _analyze_post(self, r: dict) -> Optional[PostSentimentDelta]:
        comments = r.get("comments", [])
        url      = r.get("url", "")
        text     = (r.get("text") or "")[:100]

        ts_comments = []
        for c in comments:
            ts_str = c.get("timestamp")
            if not ts_str:
                continue
            try:
                ts_comments.append((datetime.fromisoformat(ts_str), c))
            except (ValueError, TypeError):
                continue

        if len(ts_comments) < self.min_total_comments:
            return None

        ts_comments.sort(key=lambda x: x[0])
        t0 = ts_comments[0][0]

        n_windows = len(self._window_hours)
        windows   = [
            SentimentWindow(label=self._window_labels[i] if i < len(self._window_labels) else f"W{i}")
            for i in range(n_windows)
        ]
        actor_w0: dict[str, int] = {}

        for ts, c in ts_comments:
            age_h   = (ts - t0).total_seconds() / 3600
            win_idx = next(
                (i for i, b in enumerate(self._window_hours) if age_h < b),
                n_windows - 1,
            )
            sent = self._sentiment(c.get("text", ""))
            w    = windows[win_idx]
            w.total += 1
            if sent == -1:
                w.negative += 1
                if win_idx == 0:
                    a = c.get("author", "?")
                    actor_w0[a] = actor_w0.get(a, 0) + 1
            elif sent == 1:
                w.positive += 1
            else:
                w.neutral += 1

        top_seed = sorted(actor_w0, key=lambda a: -actor_w0[a])[:self.top_seed_actors_per_post]
        windows[0].top_actors = top_seed

        w0    = windows[0]
        w2    = windows[2] if len(windows) > 2 else windows[-1]
        delta = w0.neg_ratio - w2.neg_ratio

        if w0.total < self.min_window_comments:
            label = "INSUFFICIENT_DATA"
        elif delta >= self.seeded_delta_threshold:
            label = "SEEDED"
        elif delta <= -self.seeded_delta_threshold:
            label = "REVERSED"
        else:
            label = "ORGANIC"

        return PostSentimentDelta(
            post_url=url,
            post_text=text,
            windows=windows,
            manipulation_delta=round(delta, 4),
            manipulation_label=label,
            dominant_neg_actors=top_seed,
        )

    def _overall_score(self, deltas: list[PostSentimentDelta]) -> float:
        if not deltas:
            return 0.0
        seeded_count = sum(1 for d in deltas if d.manipulation_label == "SEEDED")
        avg_delta    = sum(abs(d.manipulation_delta) for d in deltas) / len(deltas)
        score = (seeded_count / len(deltas)) * self._sw_seeded_pct + min(
            self._sw_max_delta, avg_delta * self._sw_delta_mult
        )
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        deltas:    list[PostSentimentDelta],
        seeded:    list[str],
        reversed_: list[str],
        score:     float,
    ) -> str:
        if not deltas:
            return "No timestamped comments available for sentiment delta analysis."
        parts = [f"{len(deltas)} post(s) analyzed for temporal sentiment manipulation."]
        if seeded:
            parts.append(
                f"{len(seeded)} post(s) show bot-seeded negative injection "
                f"(first window significantly more negative than organic window). "
                f"Manipulation score: {score}/100."
            )
        if reversed_:
            parts.append(
                f"{len(reversed_)} post(s) show delayed negative amplification "
                f"(sentiment worsens after organic window — coordinated pile-on)."
            )
        if not seeded and not reversed_:
            parts.append("No significant sentiment manipulation pattern detected.")
        return " ".join(parts)
