"""
SentimentEngine — Multi-level Spanish political comment sentiment.
Analyzes COMMENTS (text fallback when no comments available).

Dimensions per post:
  negative   — corruption, theft, crime, personal attacks
  aggressive — violence, threats, extreme profanity, mob calls
  positive   — support, victim narrative, defense
  neutral    — balanced / informational

Lexicons are stored in SQLite (engines/lexicon_db.py) — zero hardcoded keywords here.
Add new keywords at runtime: LexiconDB().add_keyword("neg_corruption", "term", score)
"""
from __future__ import annotations
import re
from collections import Counter
from typing import Optional

# ── Linguistic constants (structural, not keyword lists) ─────────────────────
_NEGATION    = {"no", "ni", "nunca", "jamás", "jamas", "tampoco", "sin", "nada", "nadie", "ningún", "ningun"}
_INTENSIFIER = {"muy", "súper", "super", "demasiado", "totalmente", "completamente",
                "absolutamente", "bien", "bastante", "extremadamente", "re"}

# ── Lazy-loaded lexicon pools (from LexiconDB SQLite) ────────────────────────
_POOLS: Optional[list[tuple[str, dict[str, float]]]] = None


def _get_pools() -> list[tuple[str, dict[str, float]]]:
    """Return scoring pools, loading from DB on first call."""
    global _POOLS
    if _POOLS is None:
        try:
            from engines.lexicon_db import get_db
            db = get_db()
            _POOLS = [
                ("neg", {
                    **db.load_sentiment_category("neg_corruption"),
                    **db.load_sentiment_category("neg_personal"),
                    **db.load_sentiment_category("neg_political"),
                }),
                ("agg", db.load_sentiment_category("aggressive")),
                ("pos", db.load_sentiment_category("positive")),
            ]
        except Exception as exc:
            print(f"  [SENTIMENT] WARNING: LexiconDB unavailable ({exc}), using empty pools")
            _POOLS = [("neg", {}), ("agg", {}), ("pos", {})]
    return _POOLS


def reload_lexicons() -> None:
    """Force lexicon reload from DB on next scoring call (call after DB updates)."""
    global _POOLS
    _POOLS = None
    try:
        from engines.lexicon_db import LexiconDB
        LexiconDB.invalidate_cache()
    except Exception:
        pass


# ── Core text scorer ──────────────────────────────────────────────────────────

def _score_one(text: str) -> dict:
    """Score a single text string across neg/pos/agg dimensions."""
    nt = text.strip().lower()
    # Normalize slang
    nt = re.sub(r"\bhdp\b", "hijo de puta", nt)
    nt = re.sub(r"\bq\b", "que", nt)
    nt = re.sub(r"\bjtp\b", "a la cárcel", nt)

    words     = re.split(r"\W+", nt)
    orig_wrds = text.split()
    raw_neg = raw_pos = raw_agg = 0.0
    triggers: list[str] = []

    all_pools = _get_pools()

    # Multi-word phrases first
    for dim, pool in all_pools:
        for phrase, score in pool.items():
            if " " in phrase and phrase in nt:
                if dim == "neg":
                    raw_neg += score
                elif dim == "agg":
                    raw_agg += score
                    raw_neg += score * 0.4
                else:
                    raw_pos += score
                if phrase not in triggers:
                    triggers.append(phrase)

    # Word scan with negation / intensifier windows
    for i, word in enumerate(words):
        negated     = any(w in _NEGATION    for w in words[max(0, i - 4):i])
        intensified = any(w in _INTENSIFIER for w in words[max(0, i - 2):i])
        mult = 0.55 if negated else (1.45 if intensified else 1.0)
        if i < len(orig_wrds) and orig_wrds[i].isupper() and len(orig_wrds[i]) > 2:
            mult *= 1.3

        for dim, pool in all_pools:
            if word in pool and " " not in word:
                val = pool[word] * mult
                if dim == "neg":
                    raw_neg += val
                elif dim == "agg":
                    raw_agg += val
                    raw_neg += val * 0.4
                else:
                    raw_pos += val
                if word not in triggers:
                    triggers.append(word)

    def _norm(r: float) -> float:
        return round(min(r / 12.0, 1.0), 3)

    neg = _norm(raw_neg)
    pos = _norm(raw_pos)
    agg = _norm(raw_agg)

    # Priority: AGRESIVO > NEGATIVO > POSITIVO > NEUTRAL
    # Thresholds lowered to 0.15 — one meaningful word crosses the line
    # (previously 0.22 was causing true NEGATIVO/POSITIVO to fall to NEUTRAL)
    if agg >= 0.15:
        label = "AGRESIVO"
    elif neg >= 0.15:
        label = "NEGATIVO"
    elif pos >= 0.15:
        label = "POSITIVO"
    else:
        label = "NEUTRAL"

    return {"label": label, "neg": neg, "pos": pos, "agg": agg, "triggers": triggers[:8]}


# ── Engine ────────────────────────────────────────────────────────────────────

class SentimentEngine:

    # ── public API ────────────────────────────────────────────────────────────

    def analyze_comments(self, comments: list[dict]) -> dict:
        """Aggregate sentiment across a list of comment dicts (text/content key)."""
        scored: list[dict] = []
        texts:  list[str]  = []
        for c in comments:
            txt = (c.get("text") or c.get("content") or "").strip()
            if len(txt) < 4:
                continue
            scored.append(_score_one(txt))
            texts.append(txt)

        if not scored:
            return self._empty("comment")

        n       = len(scored)
        neg_avg = sum(s["neg"] for s in scored) / n
        pos_avg = sum(s["pos"] for s in scored) / n
        agg_avg = sum(s["agg"] for s in scored) / n
        neu_avg = max(0.0, 1.0 - neg_avg - pos_avg)

        neg_cnt = sum(1 for s in scored if s["label"] in ("NEGATIVO", "AGRESIVO"))
        pos_cnt = sum(1 for s in scored if s["label"] == "POSITIVO")
        agg_cnt = sum(1 for s in scored if s["label"] == "AGRESIVO")

        trig_ctr: Counter = Counter()
        for s in scored:
            trig_ctr.update(s["triggers"])

        heat = sorted(zip(scored, texts),
                      key=lambda x: x[0]["agg"] + x[0]["neg"], reverse=True)
        hot = [
            {"text": t[:180], "neg": s["neg"], "agg": s["agg"], "label": s["label"]}
            for s, t in heat[:3]
        ]

        if agg_avg >= 0.28 and agg_avg >= neg_avg * 0.55:
            label = "AGRESIVO"
        elif neg_avg >= 0.22:
            label = "NEGATIVO"
        elif pos_avg >= 0.22:
            label = "POSITIVO"
        else:
            label = "NEUTRAL"

        return {
            "label":            label,
            "mode":             "comment",
            "negative_score":   round(neg_avg, 3),
            "positive_score":   round(pos_avg, 3),
            "neutral_score":    round(neu_avg, 3),
            "aggressive_score": round(agg_avg, 3),
            "net_score":        round(pos_avg - neg_avg, 3),
            "comment_count":    n,
            "neg_comments":     neg_cnt,
            "pos_comments":     pos_cnt,
            "agg_comments":     agg_cnt,
            "top_triggers":     [t for t, _ in trig_ctr.most_common(10)],
            "hot_comments":     hot,
        }

    def analyze_text(self, text: str) -> dict:
        """Analyze post/article text as fallback when no comments available."""
        s   = _score_one(text or "")
        neu = max(0.0, 1.0 - s["neg"] - s["pos"])
        return {
            "label":            s["label"],
            "mode":             "text",
            "negative_score":   s["neg"],
            "positive_score":   s["pos"],
            "neutral_score":    round(neu, 3),
            "aggressive_score": s["agg"],
            "net_score":        round(s["pos"] - s["neg"], 3),
            "comment_count":    0,
            "neg_comments":     0,
            "pos_comments":     0,
            "agg_comments":     0,
            "top_triggers":     s["triggers"],
            "hot_comments":     [],
        }

    def batch(self, posts: list[dict]) -> None:
        """
        Analyze all posts in-place.

        PRIMARY:  Always analyzes post text (title/body). This is the authoritative
                  sentiment label and score used for sorting and filtering.
        SECONDARY: If comments are loaded, also stores comment-level sentiment in
                  post["comment_sentiment"] — used as an additional intelligence layer.
                  Comments NEVER override the text-based label/score.
        """
        c_augmented = 0
        for p in posts:
            # PRIMARY — always use post text (title/body) as source of truth
            p["sentiment"] = self.analyze_text(p.get("text", ""))

            # SECONDARY — augment with comment analysis when available
            comments = p.get("comments") or []
            if comments:
                p["comment_sentiment"] = self.analyze_comments(comments)
                c_augmented += 1

        total = len(posts)
        if total:
            aug_note = (
                f" + {c_augmented} posts with comment layer"
                if c_augmented else
                " (add --comments-on-top N to activate comment layer)"
            )
            print(f"  [SENTIMENT] {total} posts scored from text{aug_note}")

    # ── Filtering / sorting helpers ───────────────────────────────────────────

    @staticmethod
    def filter_by_mode(posts: list[dict], mode: str) -> list[dict]:
        """Filter posts by sentiment label matching the requested mode."""
        if mode == "all":
            return posts
        label_map = {
            "negative":   ("NEGATIVO", "AGRESIVO"),
            "aggressive": ("AGRESIVO",),
            "positive":   ("POSITIVO",),
            "neutral":    ("NEUTRAL",),
        }
        allowed = label_map.get(mode, ("NEGATIVO", "AGRESIVO"))
        return [p for p in posts if p.get("sentiment", {}).get("label") in allowed]

    @staticmethod
    def sort_key(mode: str):
        """Return a sort key function for the given sentiment mode."""
        if mode == "aggressive":
            return lambda p: (
                -(p.get("sentiment", {}).get("aggressive_score", 0)),
                -(p.get("engagement_total", 0)),
            )
        elif mode == "positive":
            return lambda p: (
                -(p.get("sentiment", {}).get("positive_score", 0)),
                -(p.get("engagement_total", 0)),
            )
        elif mode == "neutral":
            return lambda p: (
                -(p.get("sentiment", {}).get("neutral_score", 0)),
                -(p.get("engagement_total", 0)),
            )
        else:  # negative / all / default
            return lambda p: (
                -(p.get("sentiment", {}).get("negative_score", 0)),
                -(p.get("engagement_total", 0)),
            )

    @staticmethod
    def _empty(mode: str) -> dict:
        return {
            "label": "NEUTRAL", "mode": mode,
            "negative_score": 0.0, "positive_score": 0.0,
            "neutral_score": 1.0,  "aggressive_score": 0.0,
            "net_score": 0.0,      "comment_count": 0,
            "neg_comments": 0,     "pos_comments": 0, "agg_comments": 0,
            "top_triggers": [],    "hot_comments": [],
        }
