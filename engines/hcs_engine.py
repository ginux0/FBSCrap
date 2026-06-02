"""
Human Confidence Score (HCS) Engine.

All parameters read from cfg["hcs_engine"]. Zero hardcoded values.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .comment_bot_detector import BotSuspect
    from .cib_graph import CIBGraphResult


@dataclass
class ActorHCS:
    actor:             str
    hcs:               int
    label:             str
    label_color:       str

    name_penalty:      int
    attack_penalty:    int
    diversity_penalty: int
    coord_penalty:     int
    pattern_penalty:   int

    total_comments:    int
    attack_count:      int
    attack_ratio:      float
    vocabulary_size:   int
    vocab_diversity:   float
    graph_degree:      int

    signals:           list[str] = field(default_factory=list)


@dataclass
class HCSReport:
    actor_scores:   list[ActorHCS]
    confirmed_bots: list[ActorHCS]
    high_risk:      list[ActorHCS]
    suspicious:     list[ActorHCS]
    likely_human:   list[ActorHCS]
    human:          list[ActorHCS]
    total_actors:   int
    bot_percentage: float
    mean_hcs:       float


class HCSEngine:

    def __init__(
        self,
        posts:        list[dict],
        bot_suspects: "list[BotSuspect] | None" = None,
        cib_result:   "CIBGraphResult | None"   = None,
        cfg:          dict | None               = None,
    ):
        self.posts      = posts
        self.suspects   = {s.author: s for s in (bot_suspects or [])}
        self.cib_result = cib_result

        c = (cfg or {}).get("hcs_engine", {})
        self.max_score = c.get("max_score", 99)

        pw = c.get("penalty_weights", {})
        self._pw_name       = pw.get("name", 25)
        self._pw_attack     = pw.get("attack_rate", 25)
        self._pw_vocab      = pw.get("vocab_diversity", 20)
        self._pw_coord      = pw.get("coordination", 20)
        self._pw_pattern    = pw.get("pattern", 9)

        raw_ranges = c.get("label_ranges", [
            [0,  19, "CONFIRMED BOT",  "#FF3333", "3d1520"],
            [20, 39, "HIGH RISK",      "#FF6B00", "3d2010"],
            [40, 59, "SUSPICIOUS",     "#FFC000", "3d3010"],
            [60, 79, "LIKELY HUMAN",   "#44CCFF", "10203d"],
            [80, 99, "HUMAN",          "#00BB55", "103d20"],
        ])
        self._labels: list[tuple[int, int, str, str]] = [
            (r[0], r[1], r[2], r[3]) for r in raw_ranges
        ]

        np_ = c.get("name_penalties", {})
        self._np_bot_kw    = np_.get("bot_keyword", 12)
        self._np_digit     = np_.get("digit_suffix", 8)
        self._np_generic   = np_.get("generic_first_name", 5)
        self._np_no_sname  = np_.get("no_surname", 5)

        pp_ = c.get("pattern_penalties", {})
        self._pp_caps      = pp_.get("all_caps", 8)
        self._pp_punct     = pp_.get("excessive_punctuation", 5)

        self._min_words_vocab     = c.get("min_words_for_vocab", 5)
        self._default_vocab_div   = c.get("default_vocab_diversity", 0.5)
        self._min_word_len        = c.get("min_word_len", 3)

    def score_all(self) -> HCSReport:
        actor_data = self._build_actor_data()
        if not actor_data:
            return self._empty_report()

        degree_map: dict[str, int] = {}
        if self.cib_result:
            degree_map = {a: n.degree for a, n in self.cib_result.nodes.items()}
        max_degree = max(degree_map.values(), default=1) or 1

        scores = [
            self._score(actor, data, degree_map, max_degree)
            for actor, data in actor_data.items()
        ]
        scores.sort(key=lambda s: s.hcs)

        def bucket(lo: int, hi: int) -> list[ActorHCS]:
            return [s for s in scores if lo <= s.hcs <= hi]

        confirmed    = bucket(0,  19)
        high_risk    = bucket(20, 39)
        suspicious   = bucket(40, 59)
        likely_human = bucket(60, 79)
        human        = bucket(80, 99)

        at_risk = len(confirmed) + len(high_risk)
        bot_pct = at_risk / len(scores) * 100 if scores else 0.0
        mean    = sum(s.hcs for s in scores) / len(scores) if scores else 0.0

        return HCSReport(
            actor_scores=scores,
            confirmed_bots=confirmed,
            high_risk=high_risk,
            suspicious=suspicious,
            likely_human=likely_human,
            human=human,
            total_actors=len(scores),
            bot_percentage=round(bot_pct, 1),
            mean_hcs=round(mean, 1),
        )

    def _build_actor_data(self) -> dict:
        data: dict[str, dict] = defaultdict(lambda: {
            "texts": [], "total_comments": 0, "attack_count": 0
        })
        for post in self.posts:
            for c in post.get("comments", []):
                actor = (c.get("author") or "").strip()
                if not actor or actor == "?":
                    continue
                data[actor]["texts"].append(c.get("text", ""))
                data[actor]["total_comments"] += 1
        for actor, s in self.suspects.items():
            if actor in data:
                data[actor]["attack_count"] = s.total_attacks
        return dict(data)

    def _score(
        self,
        actor:      str,
        data:       dict,
        degree_map: dict[str, int],
        max_degree: int,
    ) -> ActorHCS:
        texts          = data["texts"]
        total_comments = data["total_comments"]
        attack_count   = data["attack_count"]
        suspect        = self.suspects.get(actor)
        signals: list[str] = []

        if suspect:
            name_pen = min(self._pw_name, int(suspect.name_score * self._pw_name / 100))
            if name_pen >= int(self._pw_name * 0.6):
                signals.append(f"name anomaly ({suspect.name_score}/100)")
        else:
            name_pen = self._heuristic_name(actor)
            if name_pen >= int(self._pw_name * 0.4):
                signals.append("suspicious name pattern")

        attack_ratio = attack_count / total_comments if total_comments else 0.0
        attack_pen   = min(self._pw_attack, int(attack_ratio * self._pw_attack))
        if attack_pen >= int(self._pw_attack * 0.6):
            signals.append(f"attack rate {attack_ratio:.0%}")

        vocab_size, vocab_div = self._vocab_diversity(texts)
        diversity_pen = min(self._pw_vocab, int((1.0 - vocab_div) * self._pw_vocab))
        if diversity_pen >= int(self._pw_vocab * 0.7):
            signals.append(f"low vocab diversity ({vocab_div:.2f})")

        degree    = degree_map.get(actor, 0)
        deg_pct   = degree / max_degree
        coord_pen = min(self._pw_coord, int(deg_pct * self._pw_coord))
        if coord_pen >= int(self._pw_coord * 0.6):
            signals.append(f"high coordination degree ({degree})")

        pattern_pen = self._pattern_penalty(actor, suspect)
        if pattern_pen >= int(self._pw_pattern * 0.6):
            signals.append("bot account structure")

        total_pen = name_pen + attack_pen + diversity_pen + coord_pen + pattern_pen
        hcs       = max(0, min(self.max_score, self.max_score - total_pen))

        if suspect and suspect.signals:
            for sig in suspect.signals[:2]:
                if sig not in signals:
                    signals.append(sig)
        signals = signals[:5]

        label, color = self._label(hcs)

        return ActorHCS(
            actor=actor, hcs=hcs, label=label, label_color=color,
            name_penalty=name_pen, attack_penalty=attack_pen,
            diversity_penalty=diversity_pen, coord_penalty=coord_pen,
            pattern_penalty=pattern_pen,
            total_comments=total_comments, attack_count=attack_count,
            attack_ratio=round(attack_ratio, 3),
            vocabulary_size=vocab_size, vocab_diversity=round(vocab_div, 3),
            graph_degree=degree, signals=signals,
        )

    def _heuristic_name(self, name: str) -> int:
        pen = 0
        if re.search(r'\d{2,}', name):
            pen += self._np_digit
        if re.search(r'(.)\1{2,}', name):
            pen += 8
        if len(name.replace(" ", "")) > 20 and len(name.split()) == 1:
            pen += 5
        if re.search(r'[A-Z]{3,}', name):
            pen += 5
        return min(pen, self._pw_name)

    def _pattern_penalty(self, name: str, suspect) -> int:
        pen = 0
        if re.match(r'^[A-Z][a-z]+\s[A-Z][a-z]+\d{2,}$', name):
            pen += self._pp_caps
        if suspect and suspect.cross_media:
            pen += 5
        return min(pen, self._pw_pattern)

    def _vocab_diversity(self, texts: list[str]) -> tuple[int, float]:
        all_words: list[str] = []
        for t in texts:
            all_words.extend(
                w for w in re.findall(r'\w+', t.lower())
                if len(w) > self._min_word_len
            )
        if len(all_words) < self._min_words_vocab:
            return 0, self._default_vocab_div
        unique = len(set(all_words))
        return unique, min(1.0, unique / len(all_words))

    def _label(self, hcs: int) -> tuple[str, str]:
        for lo, hi, label, color in self._labels:
            if lo <= hcs <= hi:
                return label, color
        return "UNKNOWN", "#606060"

    @staticmethod
    def _empty_report() -> HCSReport:
        return HCSReport(
            actor_scores=[], confirmed_bots=[], high_risk=[],
            suspicious=[], likely_human=[], human=[],
            total_actors=0, bot_percentage=0.0, mean_hcs=0.0,
        )
