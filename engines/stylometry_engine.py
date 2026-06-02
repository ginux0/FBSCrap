"""
StylometryEngine — P3: Stylometric Fingerprinting.

All parameters read from cfg["stylometry_engine"]. Zero hardcoded values.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


_EMOJI_RE  = re.compile(
    "[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FA9F]",
    re.UNICODE,
)
_ACCENT_RE = re.compile(r"[áéíóúñüÁÉÍÓÚÑÜ]")
_PUNCT_RE  = re.compile(r"[^\w\s]")
_WORD_RE   = re.compile(r"\b\w+\b")


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys  = set(a) | set(b)
    dot   = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    mag_a = math.sqrt(sum(v ** 2 for v in a.values()))
    mag_b = math.sqrt(sum(v ** 2 for v in b.values()))
    return _safe_div(dot, mag_a * mag_b)


def _extract_features(texts: list[str]) -> dict[str, float]:
    if not texts:
        return {}

    all_words:     list[str] = []
    word_counts:   list[int] = []
    char_counts:   list[int] = []
    punct_counts:  list[int] = []
    accent_counts: list[int] = []
    emoji_counts:  list[int] = []
    caps_counts:   list[int] = []
    excl_counts:   list[int] = []
    ques_counts:   list[int] = []
    ellipsis:      list[int] = []

    for t in texts:
        words = _WORD_RE.findall(t)
        all_words.extend(w.lower() for w in words)
        word_counts.append(len(words))
        char_counts.append(len(t))
        punct_counts.append(len(_PUNCT_RE.findall(t)))
        accent_counts.append(len(_ACCENT_RE.findall(t)))
        emoji_counts.append(len(_EMOJI_RE.findall(t)))
        caps_counts.append(sum(1 for c in t if c.isupper()))
        excl_counts.append(t.count("!"))
        ques_counts.append(t.count("?"))
        ellipsis.append(t.count("..."))

    n           = len(texts)
    total_chars = sum(char_counts)
    vocab_div   = _safe_div(len(set(all_words)), max(len(all_words), 1))

    return {
        "word_count":      round(_safe_div(sum(word_counts), n), 2),
        "char_count":      round(_safe_div(total_chars, n), 2),
        "punct_density":   round(_safe_div(sum(punct_counts), total_chars), 4),
        "accent_ratio":    round(_safe_div(sum(accent_counts), total_chars), 4),
        "emoji_ratio":     round(_safe_div(sum(emoji_counts), n), 4),
        "caps_ratio":      round(_safe_div(sum(caps_counts), total_chars), 4),
        "vocab_diversity": round(vocab_div, 4),
        "excl_density":    round(_safe_div(sum(excl_counts), n), 4),
        "ques_density":    round(_safe_div(sum(ques_counts), n), 4),
        "ellipsis_count":  round(_safe_div(sum(ellipsis), n), 4),
    }


@dataclass
class ActorStyle:
    actor:      str
    features:   dict[str, float]
    n_comments: int
    label:      str


@dataclass
class StyleCluster:
    cluster_id: int
    actors:     list[str]
    centroid:   dict[str, float]
    similarity: float
    label:      str


@dataclass
class CopyPasteGroup:
    signature: str
    actors:    list[str]
    count:     int


@dataclass
class StylometryReport:
    actor_styles:      list[ActorStyle]
    clusters:          list[StyleCluster]
    copy_paste_groups: list[CopyPasteGroup]
    bot_style_actors:  list[str]
    organic_actors:    list[str]
    clone_pairs:       list[tuple[str, str, float]]
    summary:           str


class StylometryEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("stylometry_engine", {})
        self.cluster_sim_threshold      = c.get("cluster_sim_threshold", 0.92)
        self.clone_threshold            = c.get("clone_threshold", 0.95)
        self.bot_vocab_threshold        = c.get("bot_vocab_threshold", 0.35)
        self.bot_template_min_comments  = c.get("bot_template_min_comments", 3)
        self.bot_excl_density_threshold = c.get("bot_excl_density_threshold", 0.5)
        self.bot_word_count_threshold   = c.get("bot_word_count_threshold", 4.0)
        self.min_cluster_size           = c.get("min_cluster_size", 2)
        self.template_campaign_bot_ratio= c.get("template_campaign_bot_ratio", 0.70)
        self.clone_farm_min_actors      = c.get("clone_farm_min_actors", 3)
        self.copy_paste_min_actors      = c.get("copy_paste_min_actors", 3)
        self.copy_paste_sig_len         = c.get("copy_paste_sig_len", 30)

    def analyze(self, scraped_results: list[dict]) -> StylometryReport:
        actor_texts = self._collect_actor_texts(scraped_results)
        styles      = self._build_actor_styles(actor_texts)
        clusters    = self._cluster_styles(styles)
        copy_paste  = self._detect_copy_paste(scraped_results)
        clone_pairs = self._find_clone_pairs(styles)
        bot_actors  = [s.actor for s in styles if "BOT" in s.label]
        organic     = [s.actor for s in styles if s.label == "ORGANIC"]

        return StylometryReport(
            actor_styles=styles,
            clusters=clusters,
            copy_paste_groups=copy_paste,
            bot_style_actors=bot_actors,
            organic_actors=organic,
            clone_pairs=clone_pairs,
            summary=self._build_summary(styles, clusters, copy_paste, clone_pairs),
        )

    def _collect_actor_texts(self, results: list[dict]) -> dict[str, list[str]]:
        actor_texts: dict[str, list[str]] = {}
        for r in results:
            for c in r.get("comments", []):
                author = c.get("author", "?")
                text   = c.get("text", "").strip()
                if len(text) >= 5:
                    actor_texts.setdefault(author, []).append(text)
        return actor_texts

    def _build_actor_styles(self, actor_texts: dict[str, list[str]]) -> list[ActorStyle]:
        styles: list[ActorStyle] = []
        for actor, texts in actor_texts.items():
            feats = _extract_features(texts)
            label = self._classify(feats, len(texts))
            styles.append(ActorStyle(actor=actor, features=feats, n_comments=len(texts), label=label))
        return sorted(styles, key=lambda s: s.n_comments, reverse=True)

    def _classify(self, feats: dict[str, float], n: int) -> str:
        vd = feats.get("vocab_diversity", 1.0)
        wd = feats.get("word_count", 10.0)
        ed = feats.get("excl_density", 0.0)
        if vd < self.bot_vocab_threshold and n >= self.bot_template_min_comments:
            return "BOT_TEMPLATE"
        if wd <= self.bot_word_count_threshold and ed >= self.bot_excl_density_threshold and n >= self.bot_template_min_comments:
            return "BOT_TEMPLATE"
        return "ORGANIC"

    def _cluster_styles(self, styles: list[ActorStyle]) -> list[StyleCluster]:
        if not styles:
            return []

        assigned: set[int]           = set()
        clusters: list[list[ActorStyle]] = []

        for i, s in enumerate(styles):
            if i in assigned:
                continue
            group = [s]
            assigned.add(i)
            for j, t in enumerate(styles):
                if j in assigned:
                    continue
                if _cosine(s.features, t.features) >= self.cluster_sim_threshold:
                    group.append(t)
                    assigned.add(j)
            clusters.append(group)

        result: list[StyleCluster] = []
        for cid, group in enumerate(clusters, 1):
            if len(group) < self.min_cluster_size:
                continue
            actors   = [s.actor for s in group]
            centroid = self._centroid([s.features for s in group])
            avg_sim  = self._avg_pairwise_sim(group)
            label    = self._cluster_label(group)
            result.append(StyleCluster(
                cluster_id=cid,
                actors=actors,
                centroid=centroid,
                similarity=round(avg_sim, 4),
                label=label,
            ))

        return sorted(result, key=lambda c: len(c.actors), reverse=True)

    def _centroid(self, feature_list: list[dict[str, float]]) -> dict[str, float]:
        if not feature_list:
            return {}
        keys = feature_list[0].keys()
        n    = len(feature_list)
        return {k: round(sum(f.get(k, 0.0) for f in feature_list) / n, 4) for k in keys}

    def _avg_pairwise_sim(self, group: list[ActorStyle]) -> float:
        pairs = [(i, j) for i in range(len(group)) for j in range(i + 1, len(group))]
        if not pairs:
            return 1.0
        return sum(_cosine(group[i].features, group[j].features) for i, j in pairs) / len(pairs)

    def _cluster_label(self, group: list[ActorStyle]) -> str:
        bot_ratio = sum(1 for s in group if "BOT" in s.label) / len(group)
        if bot_ratio >= self.template_campaign_bot_ratio:
            return "TEMPLATE_CAMPAIGN"
        if len(group) >= self.clone_farm_min_actors:
            return "CLONE_FARM"
        return "ORGANIC_GROUP"

    def _find_clone_pairs(self, styles: list[ActorStyle]) -> list[tuple[str, str, float]]:
        pairs: list[tuple[str, str, float]] = []
        for i, a in enumerate(styles):
            for b in styles[i + 1:]:
                sim = _cosine(a.features, b.features)
                if sim >= self.clone_threshold:
                    pairs.append((a.actor, b.actor, round(sim, 4)))
        return sorted(pairs, key=lambda p: -p[2])

    def _detect_copy_paste(self, results: list[dict]) -> list[CopyPasteGroup]:
        sig_map: dict[str, dict[str, int]] = {}
        for r in results:
            for c in r.get("comments", []):
                text   = re.sub(r"\s+", " ", c.get("text", "").strip().lower())
                if len(text) < 15:
                    continue
                sig    = text[:self.copy_paste_sig_len]
                author = c.get("author", "?")
                entry  = sig_map.setdefault(sig, {})
                entry[author] = entry.get(author, 0) + 1

        groups: list[CopyPasteGroup] = []
        for sig, actor_counts in sig_map.items():
            if len(actor_counts) >= self.copy_paste_min_actors:
                groups.append(CopyPasteGroup(
                    signature=sig,
                    actors=list(actor_counts.keys()),
                    count=sum(actor_counts.values()),
                ))
        return sorted(groups, key=lambda g: -g.count)

    def _build_summary(
        self,
        styles:      list[ActorStyle],
        clusters:    list[StyleCluster],
        copy_paste:  list[CopyPasteGroup],
        clone_pairs: list[tuple[str, str, float]],
    ) -> str:
        parts = [f"{len(styles)} actors stylometrically profiled."]
        bot_count = sum(1 for s in styles if "BOT" in s.label)
        if bot_count:
            parts.append(
                f"{bot_count} show bot-template writing patterns "
                f"(low vocabulary diversity / formulaic structure)."
            )
        if clusters:
            parts.append(
                f"{len(clusters)} stylometric cluster(s) — "
                f"actors sharing same writing fingerprint "
                f"(cosine ≥{self.cluster_sim_threshold})."
            )
        if clone_pairs:
            parts.append(
                f"{len(clone_pairs)} clone pair(s) identified "
                f"(cosine ≥{self.clone_threshold})."
            )
        if copy_paste:
            parts.append(
                f"{len(copy_paste)} copy-paste template(s) used by "
                f"≥{self.copy_paste_min_actors} distinct accounts."
            )
        if not bot_count and not clusters and not clone_pairs:
            parts.append("No stylometric coordination detected.")
        return " ".join(parts)
