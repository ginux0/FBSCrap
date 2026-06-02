"""
NULLSEC COMMENT CIB DETECTOR — Bots en comentarios de Facebook
NULLSEC RED TEAM  ·  Open-Source Threat Intelligence

All configurable thresholds read from cfg["comment_bot_detector"].
Pattern files: config/patterns/attack_words.json + bot_name_patterns.json
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).parent.parent


def _load_json_file(rel_path: str, fallback):
    try:
        return json.loads((_BASE_DIR / rel_path).read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _load_generic_names() -> set[str]:
    data = _load_json_file("config/patterns/bot_name_patterns.json", {})
    names = data.get("generic_first_names_es", [])
    return set(names) | {
        "ciudadano", "mexicano", "persona", "usuario", "anónimo", "anonimo",
        "patriota", "noticias", "periodista", "reportero", "informador",
    }


_GENERIC_FIRST_NAMES: set[str] = _load_generic_names()

_NAME_KEYWORDS_CACHE:    Optional[list[str]] = None
_ATTACK_TEMPLATES_CACHE: Optional[list[str]] = None
_ATTACK_WORDS_CACHE:     Optional[set[str]]  = None


def _get_name_keywords() -> list[str]:
    global _NAME_KEYWORDS_CACHE
    if _NAME_KEYWORDS_CACHE is None:
        try:
            from engines.lexicon_db import get_db
            _NAME_KEYWORDS_CACHE = get_db().load_bot_name_keywords()
        except Exception:
            data = _load_json_file("config/patterns/bot_name_patterns.json", {})
            _NAME_KEYWORDS_CACHE = data.get("bot_keywords", [
                "noticias", "noticiero", "periodico", "diario", "portal", "media",
                "news", "info", "reportero", "periodista", "ciudadano", "informador",
            ])
    return _NAME_KEYWORDS_CACHE


def _get_attack_templates() -> list[str]:
    global _ATTACK_TEMPLATES_CACHE
    if _ATTACK_TEMPLATES_CACHE is None:
        try:
            from engines.lexicon_db import get_db
            _ATTACK_TEMPLATES_CACHE = get_db().load_attack_templates()
        except Exception:
            data = _load_json_file("config/patterns/attack_words.json", {})
            _ATTACK_TEMPLATES_CACHE = data.get("attack_templates", [
                r"^(corrupto|ladr[oó]n|ratero|mentiroso|mafioso)[\s!.]*$",
                r"^(a la c[aá]rcel|que lo metan preso)[\s!.]*$",
                r"^[🤮🤡😡👎💩🚔]+$",
            ])
    return _ATTACK_TEMPLATES_CACHE


def _get_attack_words() -> set[str]:
    global _ATTACK_WORDS_CACHE
    if _ATTACK_WORDS_CACHE is None:
        try:
            from engines.lexicon_db import get_db
            _ATTACK_WORDS_CACHE = get_db().load_attack_words()
        except Exception:
            data = _load_json_file("config/patterns/attack_words.json", {})
            words = data.get("attack_words", [])
            _ATTACK_WORDS_CACHE = set(words) if words else {
                "corrupto", "ladrón", "ladron", "ratero", "mentiroso",
                "mafioso", "traidor", "inútil", "criminal", "delincuente",
                "pendejo", "idiota", "basura", "asco",
            }
    return _ATTACK_WORDS_CACHE


def reload_bot_lexicons() -> None:
    global _NAME_KEYWORDS_CACHE, _ATTACK_TEMPLATES_CACHE, _ATTACK_WORDS_CACHE
    _NAME_KEYWORDS_CACHE = _ATTACK_TEMPLATES_CACHE = _ATTACK_WORDS_CACHE = None
    try:
        from engines.lexicon_db import LexiconDB
        LexiconDB.invalidate_cache()
    except Exception:
        pass


def _get_thresholds(cfg: dict | None) -> dict:
    c = (cfg or {}).get("comment_bot_detector", {})
    return {
        "dup_threshold":          c.get("dup_threshold", 0.65),
        "copycat_min_posts":      c.get("copycat_min_posts", 2),
        "repeat_attacker_min":    c.get("repeat_attacker_min", 2),
        "copycat_max_authors":    c.get("copycat_max_authors", 15),
        "max_comparison_pairs":   c.get("max_comparison_pairs", 50000),
        "max_clusters_output":    c.get("max_clusters_output", 50),
        "max_authors_in_cluster": c.get("max_authors_in_cluster", 10),
    }


# ── Text helpers ──────────────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _shingles(text: str, k: int = 3) -> frozenset[str]:
    words = _normalize_text(text).split()
    if len(words) < k:
        return frozenset(words)
    return frozenset(" ".join(words[i:i+k]) for i in range(len(words) - k + 1))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _is_attack_template(text: str) -> bool:
    t = text.strip()
    for pat in _get_attack_templates():
        if re.match(pat, t, re.IGNORECASE):
            return True
    return False


def _has_context(comment_text: str, post_text: str) -> bool:
    if not post_text or not comment_text:
        return False
    post_words    = set(w.lower() for w in re.findall(r"\b\w{5,}\b", post_text))
    comment_words = set(w.lower() for w in re.findall(r"\b\w{4,}\b", comment_text))
    return bool(post_words & comment_words)


# ── Name analysis ─────────────────────────────────────────────────────────────

@dataclass
class NameBotScore:
    author:  str
    score:   int
    signals: list[str]
    is_bot:  bool = False


def _score_name(author: str) -> NameBotScore:
    signals: list[str] = []
    score = 0
    name  = author.strip()

    num_m = re.search(r"\d{3,}", name)
    if num_m:
        signals.append(f"numeric suffix ({num_m.group()})")
        score += 35

    if name == name.upper() and len(name) > 3:
        signals.append("ALL CAPS name")
        score += 25

    if len(name.replace(" ", "")) <= 4:
        signals.append(f"very short name ({len(name)} chars)")
        score += 20

    parts = [p.lower() for p in name.split() if p.isalpha()]
    if len(parts) == 1 and parts[0] in _GENERIC_FIRST_NAMES:
        signals.append(f"generic first name only ('{parts[0]}')")
        score += 30

    name_lower = name.lower()
    for kw in _get_name_keywords():
        if kw in name_lower:
            signals.append(f"institutional keyword in name ('{kw}')")
            score += 40
            break

    if len(parts) >= 2 and len(set(parts)) < len(parts):
        signals.append("repeated word in name")
        score += 20

    if re.match(r"^\d+$", name.replace(" ", "")):
        signals.append("name = digits only")
        score += 60

    emoji_count = len(re.findall(r"[^\w\s,.]", name))
    if emoji_count >= 2:
        signals.append(f"{emoji_count} emoji/symbols in name")
        score += 20

    score = min(score, 100)
    return NameBotScore(author=author, score=score, signals=signals, is_bot=score >= 40)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class CommentBotSignal:
    signal_type: str
    confidence:  int
    description: str
    evidence:    str


@dataclass
class CommentRecord:
    post_source: str
    post_title:  str
    post_url:    str
    author:      str
    text:        str
    likes:       int
    signals:     list[CommentBotSignal] = field(default_factory=list)
    bot_score:   int = 0
    bot_class:   str = "ORGANIC"

    def compute_class(self) -> None:
        self.bot_score = min(sum(s.confidence for s in self.signals), 100)
        if self.bot_score >= 65:
            self.bot_class = "BOT CONFIRMED"
        elif self.bot_score >= 35:
            self.bot_class = "SUSPICIOUS"
        else:
            self.bot_class = "ORGANIC"


@dataclass
class CopyCatCluster:
    sample_text: str
    occurrences: int
    authors:     list[str]
    posts:       list[str]
    similarity:  float


@dataclass
class RepeatAttacker:
    author:        str
    post_count:    int
    total_attacks: int
    name_score:    NameBotScore
    sample_texts:  list[str]
    sources:       list[str]


@dataclass
class BotSuspect:
    author:          str
    total_attacks:   int
    posts_attacked:  int
    sources:         list[str]
    composite_score: int
    name_score:      int
    signals:         list[str]
    sample_attacks:  list[str]
    cross_media:     bool


@dataclass
class CommentBotReport:
    total_posts_with_comments: int
    total_comments_analyzed:   int
    bot_confirmed_count:       int
    suspicious_count:          int
    organic_count:             int
    bot_confirmed_pct:         int
    suspicious_pct:            int
    organic_pct:               int

    copycat_clusters:        list[CopyCatCluster]
    repeat_attackers:        list[RepeatAttacker]
    top_bot_comments:        list[CommentRecord]
    attack_density_per_post: list[dict]
    top_bot_suspects:        list[BotSuspect] = field(default_factory=list)

    avg_attack_density:    float = 0.0
    top_attack_phrases:    list[tuple[str, int]] = field(default_factory=list)
    suspicious_name_count: int = 0
    suspicious_name_pct:   int = 0

    has_data: bool = True


# ── Attack phrase classifier ──────────────────────────────────────────────────

def _is_attack_comment(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in _get_attack_words()) or _is_attack_template(text)


def _attack_phrase(text: str, ctx_before: int = 10, ctx_after: int = 30) -> str:
    t = text.strip()
    if len(t) <= 80:
        return t
    t_lower = t.lower()
    for w in sorted(_get_attack_words(), key=len, reverse=True):
        idx = t_lower.find(w)
        if idx >= 0:
            start = max(0, idx - ctx_before)
            end   = min(len(t), idx + len(w) + ctx_after)
            return "..." + t[start:end] + "..."
    return t[:80]


# ── Detection engines ─────────────────────────────────────────────────────────

def _flatten_comments(posts: list[dict]) -> list[CommentRecord]:
    records: list[CommentRecord] = []
    for post in posts:
        comments = post.get("comments") or []
        if not comments:
            continue
        src   = (post.get("source") or "?")[:40]
        title = (post.get("text") or "")[:80].replace("\n", " ")
        url   = post.get("url") or ""
        for c in comments:
            text   = (c.get("text") or "").strip()
            author = (c.get("author") or "?").strip()
            likes  = int(c.get("likes") or 0)
            if not text or len(text) < 3:
                continue
            records.append(CommentRecord(
                post_source=src, post_title=title, post_url=url,
                author=author, text=text, likes=likes,
            ))
    return records


def _find_copycat_clusters(
    records:    list[CommentRecord],
    thresholds: dict,
) -> list[CopyCatCluster]:
    dup_threshold   = thresholds["dup_threshold"]
    copycat_min     = thresholds["copycat_min_posts"]
    copycat_max_aut = thresholds["copycat_max_authors"]
    max_pairs       = thresholds["max_comparison_pairs"]
    max_clusters    = thresholds["max_clusters_output"]
    max_authors_cl  = thresholds["max_authors_in_cluster"]

    clusters: list[CopyCatCluster] = []
    processed: set[int] = set()
    pairs_checked = 0

    for i, rec_i in enumerate(records):
        if id(rec_i) in processed:
            continue
        shin_i = _shingles(rec_i.text)
        if len(shin_i) < 2:
            continue

        group = [rec_i]
        for j, rec_j in enumerate(records):
            if pairs_checked >= max_pairs:
                break
            if i == j or id(rec_j) in processed:
                continue
            if rec_j.author == rec_i.author:
                continue
            if rec_j.post_url == rec_i.post_url:
                continue
            pairs_checked += 1
            shin_j = _shingles(rec_j.text)
            if _jaccard(shin_i, shin_j) >= dup_threshold:
                group.append(rec_j)

        if len(group) >= copycat_min:
            unique_authors = list(dict.fromkeys(r.author for r in group))
            unique_posts   = list(dict.fromkeys(r.post_url for r in group))

            if len(unique_posts) < 2 and len(unique_authors) < 3:
                continue
            if len(unique_authors) > copycat_max_aut:
                continue

            for r in group:
                processed.add(id(r))

            sims   = [_jaccard(shin_i, _shingles(r.text)) for r in group[1:]]
            avg_sim = sum(sims) / len(sims) if sims else 1.0

            clusters.append(CopyCatCluster(
                sample_text=rec_i.text[:120],
                occurrences=len(group),
                authors=unique_authors[:max_authors_cl],
                posts=list(dict.fromkeys(r.post_source for r in group)),
                similarity=avg_sim,
            ))

    clusters.sort(key=lambda c: -c.occurrences)
    return clusters[:max_clusters]


def _find_repeat_attackers(
    records:    list[CommentRecord],
    thresholds: dict,
) -> list[RepeatAttacker]:
    repeat_min = thresholds["repeat_attacker_min"]

    by_author: dict[str, list[CommentRecord]] = defaultdict(list)
    for rec in records:
        by_author[rec.author].append(rec)

    attackers: list[RepeatAttacker] = []
    for author, recs in by_author.items():
        attack_recs    = [r for r in recs if _is_attack_comment(r.text)]
        distinct_posts = list(dict.fromkeys(r.post_url for r in attack_recs))

        if len(distinct_posts) < repeat_min:
            continue

        name_score   = _score_name(author)
        sample_texts = list(dict.fromkeys(r.text[:70] for r in attack_recs))[:3]
        sources      = list(dict.fromkeys(r.post_source for r in attack_recs))

        attackers.append(RepeatAttacker(
            author=author, post_count=len(distinct_posts),
            total_attacks=len(attack_recs),
            name_score=name_score,
            sample_texts=sample_texts, sources=sources,
        ))

    attackers.sort(key=lambda a: -(a.post_count * 10 + a.name_score.score))
    return attackers


def _score_all_comments(
    records:          list[CommentRecord],
    copycat_clusters: list[CopyCatCluster],
    repeat_attackers: list[RepeatAttacker],
    thresholds:       dict,
) -> list[CommentRecord]:
    dup_threshold   = thresholds["dup_threshold"]
    repeat_authors: set[str] = {a.author for a in repeat_attackers}

    for rec in records:
        signals: list[CommentBotSignal] = []

        for cluster in copycat_clusters:
            if _jaccard(_shingles(rec.text), _shingles(cluster.sample_text)) >= dup_threshold:
                other_authors = [a for a in cluster.authors if a != rec.author]
                signals.append(CommentBotSignal(
                    signal_type="COPYCAT_CIB",
                    confidence=70,
                    description=f"Text replicated by {len(cluster.authors)} users across {len(cluster.posts)} posts",
                    evidence=f"Sim={cluster.similarity:.2f} | authors: {', '.join(other_authors[:3])}",
                ))
                break

        if rec.author in repeat_authors:
            attacker = next(a for a in repeat_attackers if a.author == rec.author)
            signals.append(CommentBotSignal(
                signal_type="REPEAT_ATTACKER",
                confidence=55,
                description=f"Attacks across {attacker.post_count} distinct posts ({attacker.total_attacks} attacks)",
                evidence=f"sources: {', '.join(attacker.sources[:3])}",
            ))

        name_score = _score_name(rec.author)
        if name_score.is_bot:
            signals.append(CommentBotSignal(
                signal_type="SUSPICIOUS_NAME",
                confidence=min(name_score.score // 2, 35),
                description=f"Bot name pattern: {'; '.join(name_score.signals[:2])}",
                evidence=f"score={name_score.score}/100",
            ))

        if _is_attack_template(rec.text):
            signals.append(CommentBotSignal(
                signal_type="ATTACK_TEMPLATE",
                confidence=45,
                description="Single-phrase attack with no context or argument",
                evidence=f"text: '{rec.text[:60]}'",
            ))

        caps = _caps_ratio(rec.text)
        if caps > 0.55 and _is_attack_comment(rec.text):
            signals.append(CommentBotSignal(
                signal_type="CAPS_ATTACK",
                confidence=30,
                description=f"Attack in ALL CAPS ({int(caps*100)}% of text)",
                evidence=f"'{rec.text[:60]}'",
            ))

        if rec.likes == 0 and _is_attack_comment(rec.text) and len(rec.text) > 10:
            signals.append(CommentBotSignal(
                signal_type="ZERO_LIKE_ATTACK",
                confidence=20,
                description="Attack with zero likes — no organic resonance",
                evidence=f"likes=0 | text: '{rec.text[:50]}'",
            ))

        rec.signals = signals
        rec.compute_class()

    return records


def _attack_density(posts: list[dict]) -> list[dict]:
    result = []
    for post in posts:
        comments = post.get("comments") or []
        if not comments:
            continue
        total   = len(comments)
        attacks = sum(1 for c in comments if _is_attack_comment(c.get("text") or ""))
        pct     = round(attacks / total * 100) if total else 0
        result.append({
            "source":  (post.get("source") or "?")[:35],
            "title":   (post.get("text") or "")[:60].replace("\n", " "),
            "total":   total,
            "attacks": attacks,
            "pct":     pct,
        })
    result.sort(key=lambda x: -x["pct"])
    return result


def _build_top_suspects(
    records:          list[CommentRecord],
    repeat_attackers: list[RepeatAttacker],
    copycat_clusters: list[CopyCatCluster],
) -> list[BotSuspect]:
    by_author: dict[str, list[CommentRecord]] = defaultdict(list)
    for rec in records:
        by_author[rec.author].append(rec)

    copycat_authors: set[str] = set()
    for cluster in copycat_clusters:
        copycat_authors.update(cluster.authors)

    suspect_map: dict[str, BotSuspect] = {}
    for att in repeat_attackers:
        signals: list[str] = []
        if att.name_score.is_bot:
            signals.extend(att.name_score.signals[:2])
        if att.author in copycat_authors:
            signals.append("coordinated CIB text copying")
        signals.append(f"attacks across {att.post_count} distinct posts")

        att_norm  = min(att.total_attacks / 20.0, 1.0)
        post_norm = min(att.post_count / 5.0, 1.0)
        name_norm = att.name_score.score / 100.0
        cc_bonus  = 1.0 if att.author in copycat_authors else 0.0
        composite = int((att_norm * 30 + post_norm * 40 + name_norm * 15 + cc_bonus * 15))

        suspect_map[att.author] = BotSuspect(
            author=att.author, total_attacks=att.total_attacks,
            posts_attacked=att.post_count, sources=att.sources[:8],
            composite_score=min(composite, 99),
            name_score=att.name_score.score,
            signals=signals[:5], sample_attacks=att.sample_texts[:2],
            cross_media=len(att.sources) >= 2,
        )

    for rec in records:
        if rec.author in suspect_map or rec.bot_score < 35:
            continue
        all_recs = by_author[rec.author]
        attacks  = [r for r in all_recs if _is_attack_comment(r.text)]
        if not attacks:
            continue
        sources = list(dict.fromkeys(r.post_source for r in attacks))
        ns      = _score_name(rec.author)
        sigs    = [s.description[:50] for s in rec.signals[:3]]

        att_norm  = min(len(attacks) / 20.0, 1.0)
        post_norm = min(len(sources) / 5.0, 1.0)
        name_norm = ns.score / 100.0
        cc_bonus  = 1.0 if rec.author in copycat_authors else 0.0
        composite = int((att_norm * 30 + post_norm * 40 + name_norm * 15 + cc_bonus * 15))

        if composite < 10:
            continue

        suspect_map[rec.author] = BotSuspect(
            author=rec.author, total_attacks=len(attacks),
            posts_attacked=len(sources), sources=sources[:8],
            composite_score=min(composite, 99),
            name_score=ns.score,
            signals=sigs[:5],
            sample_attacks=[r.text[:80] for r in attacks[:2]],
            cross_media=len(sources) >= 2,
        )

    suspects = sorted(suspect_map.values(), key=lambda s: -s.composite_score)
    return suspects


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_comments(posts: list[dict], cfg: dict | None = None) -> CommentBotReport:
    """
    Full comment-level CIB analysis. All thresholds from cfg["comment_bot_detector"].
    """
    thresholds = _get_thresholds(cfg)

    posts_with_comments = [p for p in posts if p.get("comments")]
    total_comments      = sum(len(p.get("comments") or []) for p in posts)

    if not posts_with_comments or total_comments == 0:
        return CommentBotReport(
            total_posts_with_comments=0, total_comments_analyzed=0,
            bot_confirmed_count=0, suspicious_count=0, organic_count=0,
            bot_confirmed_pct=0, suspicious_pct=0, organic_pct=0,
            copycat_clusters=[], repeat_attackers=[],
            top_bot_comments=[], attack_density_per_post=[], has_data=False,
        )

    records          = _flatten_comments(posts)
    copycat_clusters = _find_copycat_clusters(records, thresholds)
    repeat_attackers = _find_repeat_attackers(records, thresholds)
    scored_records   = _score_all_comments(records, copycat_clusters, repeat_attackers, thresholds)
    top_suspects     = _build_top_suspects(scored_records, repeat_attackers, copycat_clusters)

    bot_confirmed = [r for r in scored_records if r.bot_class == "BOT CONFIRMED"]
    suspicious    = [r for r in scored_records if r.bot_class == "SUSPICIOUS"]
    organic       = [r for r in scored_records if r.bot_class == "ORGANIC"]
    total         = len(scored_records)

    attack_phrases = Counter(
        _attack_phrase(r.text) for r in scored_records if _is_attack_comment(r.text)
    ).most_common(8)

    name_scores      = [_score_name(r.author) for r in scored_records]
    suspicious_names = sum(1 for n in name_scores if n.is_bot)

    density     = _attack_density(posts_with_comments)
    avg_density = sum(d["pct"] for d in density) / len(density) if density else 0.0

    seen_texts: set[str] = set()
    top_bots: list[CommentRecord] = []
    for r in sorted(bot_confirmed + suspicious, key=lambda x: -x.bot_score):
        key = r.text[:40]
        if key not in seen_texts:
            seen_texts.add(key)
            top_bots.append(r)
        if len(top_bots) >= 100:
            break

    return CommentBotReport(
        total_posts_with_comments=len(posts_with_comments),
        total_comments_analyzed=total,
        bot_confirmed_count=len(bot_confirmed),
        suspicious_count=len(suspicious),
        organic_count=len(organic),
        bot_confirmed_pct=round(len(bot_confirmed) / max(total, 1) * 100),
        suspicious_pct=round(len(suspicious)    / max(total, 1) * 100),
        organic_pct=round(len(organic)          / max(total, 1) * 100),
        copycat_clusters=copycat_clusters,
        repeat_attackers=repeat_attackers,
        top_bot_comments=top_bots,
        top_bot_suspects=top_suspects,
        attack_density_per_post=density,
        avg_attack_density=avg_density,
        top_attack_phrases=attack_phrases,
        suspicious_name_count=suspicious_names,
        suspicious_name_pct=round(suspicious_names / max(total, 1) * 100),
        has_data=True,
    )
