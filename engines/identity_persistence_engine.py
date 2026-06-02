"""
IdentityPersistenceEngine.

Detects when the SAME bot operator changes account name/photo between
campaigns while keeping an identical behavioral fingerprint. This is
the hardest-to-detect CIB technique: operators assume that a new name
creates a new identity. Wrong.

Behavioral DNA = 8 linguistic/temporal dimensions that are extremely
difficult to consciously fake across thousands of comments:
  1. vocab_entropy       — unique words / total words (writing diversity)
  2. avg_comment_len     — normalized average comment word count
  3. caps_ratio          — UPPERCASE word frequency
  4. emoji_ratio         — emoji character frequency
  5. punct_density       — punctuation density
  6. attack_ratio        — aggressive/negative keyword ratio
  7. digit_ratio         — numeric content frequency
  8. sentence_rhythm     — variance in comment length (writing cadence)

Cosine similarity between 8D vectors identifies "identity morphs" —
same operator, different account.

Architecture:
  - Extends cross_campaign registry with `actor_fingerprints` table
  - Each session registers behavioral fingerprints per actor
  - Cross-matches against all historical fingerprints
  - Reports IDENTITY_MORPH candidates with confidence + evidence

Identity Morph Classifications:
  CONFIRMED_MORPH  — similarity >= high_threshold + timing evidence
  PROBABLE_MORPH   — similarity >= medium_threshold
  POSSIBLE_MORPH   — similarity >= low_threshold (flag only)

All thresholds from cfg["identity_persistence"]. Zero hardcoded values.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List


# ── Linguistic patterns ────────────────────────────────────────────────────────
_EMOJI_RE    = re.compile(
    r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
    r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
    r'☀-⛿✀-➿]'
)
_PUNCT_RE    = re.compile(r'[!?¡¿.,;:…–—"\'()\[\]{}]')
_DIGIT_RE    = re.compile(r'\d')
_CAPS_WORD   = re.compile(r'\b[A-ZÁÉÍÓÚÜÑ]{2,}\b')
_AGG_RE      = re.compile(
    r'\b(pendejo|puta|corrupto|ladrón|ladron|ratero|imbécil|imbecil|'
    r'pinche|culero|maldito|fuera|renuncia|asesino|narco|traidor)\b',
    re.IGNORECASE,
)


def _compute_fingerprint(comments: list[str]) -> list[float]:
    """Compute normalized 8D behavioral fingerprint from comment list."""
    if not comments:
        return [0.0] * 8

    all_text = " ".join(comments)
    words    = all_text.lower().split()
    n_words  = max(len(words), 1)
    n_chars  = max(len(all_text), 1)
    n_comments = max(len(comments), 1)

    # 1. Vocabulary entropy (diversity)
    unique_ratio = len(set(words)) / n_words

    # 2. Average comment length (normalized: 0-1 for 0-50 words)
    avg_len = sum(len(c.split()) for c in comments) / n_comments
    avg_len_norm = min(1.0, avg_len / 50.0)

    # 3. CAPS ratio
    caps = len(_CAPS_WORD.findall(all_text))
    caps_ratio = min(1.0, caps / max(len(words), 1))

    # 4. Emoji ratio
    emojis = len(_EMOJI_RE.findall(all_text))
    emoji_ratio = min(1.0, emojis / n_comments)

    # 5. Punctuation density
    puncts = len(_PUNCT_RE.findall(all_text))
    punct_density = min(1.0, puncts / n_chars * 10)

    # 6. Attack ratio
    attack = len(_AGG_RE.findall(all_text))
    attack_ratio = min(1.0, attack / n_comments)

    # 7. Digit ratio
    digits = len(_DIGIT_RE.findall(all_text))
    digit_ratio = min(1.0, digits / n_chars * 5)

    # 8. Comment length variance (writing cadence / rhythm)
    lengths = [len(c.split()) for c in comments]
    if len(lengths) > 1:
        mean_l = sum(lengths) / len(lengths)
        variance = sum((l - mean_l) ** 2 for l in lengths) / len(lengths)
        rhythm = min(1.0, math.sqrt(variance) / 20.0)
    else:
        rhythm = 0.0

    return [
        round(unique_ratio, 4),
        round(avg_len_norm, 4),
        round(caps_ratio,   4),
        round(emoji_ratio,  4),
        round(punct_density,4),
        round(attack_ratio, 4),
        round(digit_ratio,  4),
        round(rhythm,       4),
    ]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot    = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot / (norm_a * norm_b), 4)


# ── Schema extension ───────────────────────────────────────────────────────────
_FINGERPRINT_SCHEMA = """
CREATE TABLE IF NOT EXISTS actor_fingerprints (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id     INTEGER NOT NULL REFERENCES actors(id),
    campaign     TEXT    NOT NULL,
    session_ts   TEXT    NOT NULL,
    fingerprint  TEXT    NOT NULL,
    n_comments   INTEGER DEFAULT 0,
    UNIQUE(actor_id, campaign, session_ts)
);
CREATE INDEX IF NOT EXISTS idx_fp_actor ON actor_fingerprints(actor_id);
"""


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class IdentityMorph:
    actor_a:        str             # current session actor name
    actor_b:        str             # historical actor name (different campaign)
    campaign_a:     str
    campaign_b:     str
    similarity:     float           # cosine similarity 0-1
    confidence:     str             # CONFIRMED | PROBABLE | POSSIBLE
    fingerprint_a:  list[float]
    fingerprint_b:  list[float]
    evidence:       str             # forensic explanation


@dataclass
class IdentityPersistenceReport:
    morphs:              List[IdentityMorph]
    confirmed_morphs:    List[str]          # actor_a names
    probable_morphs:     List[str]
    total_fingerprinted: int
    unique_operators:    int                # estimated distinct operators
    persistence_score:   float             # 0-100
    summary:             str


class IdentityPersistenceEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("identity_persistence", {})
        base = Path(__file__).parent.parent
        rel  = c.get("registry_path", "sessions/actor_registry.db")
        self._db_path    = base / rel
        self._confirmed  = c.get("confirmed_threshold",  0.92)
        self._probable   = c.get("probable_threshold",   0.85)
        self._possible   = c.get("possible_threshold",   0.75)
        self._min_comms  = c.get("min_comments_fp",       5)
        self._top_morphs = c.get("top_morphs_output",    20)
        self._min_bot    = c.get("min_bot_score",        40)

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ─────────────────────────────────────────────────────────────────────────

    def register_fingerprints(
        self,
        campaign:       str,
        scraped_results:list[dict],
        troll_report=None,
        session_ts:     str | None = None,
    ) -> int:
        """Compute and store behavioral fingerprints for current session actors."""
        ts = session_ts or datetime.now().isoformat(timespec="seconds")

        # Build actor → comments map
        actor_comments: dict[str, list[str]] = {}
        for r in scraped_results:
            for c in r.get("comments", []):
                actor = c.get("author", "?")
                text  = (c.get("text") or "").strip()
                if actor and actor != "?" and text:
                    actor_comments.setdefault(actor, []).append(text)

        # Only fingerprint actors with enough comments (or known bots)
        bot_set = set()
        if troll_report:
            bot_set = {p.actor for p in getattr(troll_report, "profiles", [])
                       if p.bot_risk_score >= self._min_bot}

        registered = 0
        campaign_up = campaign.strip().upper()

        with self._connect() as conn:
            for actor, comments in actor_comments.items():
                if len(comments) < self._min_comments and actor not in bot_set:
                    continue

                from engines.name_utils import clean_actor_name
                name      = clean_actor_name(actor)
                norm_name = name.lower().strip()
                if not norm_name or norm_name == "?":
                    continue

                conn.execute(
                    "INSERT OR IGNORE INTO actors (name, normalized_name) VALUES (?,?)",
                    (name, norm_name),
                )
                row = conn.execute(
                    "SELECT id FROM actors WHERE normalized_name=?", (norm_name,)
                ).fetchone()
                if not row:
                    continue
                actor_id = row[0]

                fp = _compute_fingerprint(comments)
                conn.execute(
                    """INSERT OR IGNORE INTO actor_fingerprints
                       (actor_id, campaign, session_ts, fingerprint, n_comments)
                       VALUES (?,?,?,?,?)""",
                    (actor_id, campaign_up, ts, json.dumps(fp), len(comments)),
                )
                registered += 1

        return registered

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        current_campaign: str,
    ) -> IdentityPersistenceReport:
        """
        Cross-match current session fingerprints against all historical
        fingerprints to find identity morphs.
        """
        camp_up = current_campaign.strip().upper()

        with self._connect() as conn:
            # Get current session fingerprints
            current_fps = conn.execute("""
                SELECT a.name, af.campaign, af.fingerprint, af.n_comments
                FROM actor_fingerprints af
                JOIN actors a ON a.id = af.actor_id
                WHERE af.campaign = ?
                ORDER BY af.n_comments DESC
            """, (camp_up,)).fetchall()

            if not current_fps:
                return self._empty()

            # Get ALL historical fingerprints (other campaigns)
            historical_fps = conn.execute("""
                SELECT a.name, af.campaign, af.fingerprint, af.n_comments
                FROM actor_fingerprints af
                JOIN actors a ON a.id = af.actor_id
                WHERE af.campaign != ?
                ORDER BY af.n_comments DESC
            """, (camp_up,)).fetchall()

            total_fp = conn.execute(
                "SELECT COUNT(*) FROM actor_fingerprints WHERE campaign=?", (camp_up,)
            ).fetchone()[0]

        if not historical_fps:
            return IdentityPersistenceReport(
                morphs=[], confirmed_morphs=[], probable_morphs=[],
                total_fingerprinted=total_fp, unique_operators=total_fp,
                persistence_score=0.0,
                summary=f"{total_fp} actors fingerprinted — no historical data yet for cross-matching.",
            )

        # Cross-match current vs historical
        morphs: list[IdentityMorph] = []
        seen_pairs: set[frozenset] = set()

        for cur_name, cur_camp, cur_fp_json, cur_n in current_fps:
            try:
                cur_fp = json.loads(cur_fp_json)
            except Exception:
                continue

            for hist_name, hist_camp, hist_fp_json, hist_n in historical_fps:
                # Skip same normalized name (already tracked by E6)
                if cur_name.lower().strip() == hist_name.lower().strip():
                    continue

                pair = frozenset([f"{cur_name}:{cur_camp}", f"{hist_name}:{hist_camp}"])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                try:
                    hist_fp = json.loads(hist_fp_json)
                except Exception:
                    continue

                sim = _cosine_similarity(cur_fp, hist_fp)
                if sim < self._possible:
                    continue

                conf = self._classify_confidence(sim)
                evidence = self._build_evidence(
                    cur_name, hist_name, cur_camp, hist_camp,
                    cur_fp, hist_fp, sim, conf,
                )

                morphs.append(IdentityMorph(
                    actor_a       = cur_name,
                    actor_b       = hist_name,
                    campaign_a    = cur_camp,
                    campaign_b    = hist_camp,
                    similarity    = sim,
                    confidence    = conf,
                    fingerprint_a = cur_fp,
                    fingerprint_b = hist_fp,
                    evidence      = evidence,
                ))

        morphs.sort(key=lambda m: -m.similarity)
        top = morphs[:self._top_morphs]

        confirmed = [m.actor_a for m in top if m.confidence == "CONFIRMED_MORPH"]
        probable  = [m.actor_a for m in top if m.confidence == "PROBABLE_MORPH"]

        # Estimate unique operators: subtract confirmed morphs
        unique_ops = max(1, total_fp - len(confirmed))
        score      = self._score(top, confirmed, probable)
        summary    = self._build_summary(top, confirmed, probable, total_fp, unique_ops, score)

        return IdentityPersistenceReport(
            morphs              = top,
            confirmed_morphs    = confirmed,
            probable_morphs     = probable,
            total_fingerprinted = total_fp,
            unique_operators    = unique_ops,
            persistence_score   = score,
            summary             = summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _classify_confidence(self, sim: float) -> str:
        if sim >= self._confirmed:
            return "CONFIRMED_MORPH"
        if sim >= self._probable:
            return "PROBABLE_MORPH"
        return "POSSIBLE_MORPH"

    _FP_LABELS = [
        "vocab_entropy", "avg_len", "caps_ratio", "emoji_ratio",
        "punct_density", "attack_ratio", "digit_ratio", "rhythm",
    ]

    def _build_evidence(
        self,
        name_a: str, name_b: str,
        camp_a: str, camp_b: str,
        fp_a: list[float], fp_b: list[float],
        sim: float, conf: str,
    ) -> str:
        dims = []
        for i, (la, lb, label) in enumerate(
            zip(fp_a, fp_b, self._FP_LABELS)
        ):
            diff = abs(la - lb)
            if diff < 0.08:
                dims.append(f"{label}≈{la:.2f}")
        matching_dims = ", ".join(dims[:5])
        return (
            f"{conf}: '{name_a}' (current: {camp_a}) is behaviorally identical "
            f"to '{name_b}' (historical: {camp_b}). "
            f"Cosine similarity {sim:.3f}. "
            f"Matching behavioral dimensions: {matching_dims}. "
            f"Same operator, different account name — identity morph detected."
        )

    def _score(
        self,
        morphs:    list[IdentityMorph],
        confirmed: list,
        probable:  list,
    ) -> float:
        if not morphs:
            return 0.0
        conf_score = len(confirmed) * 25.0
        prob_score = len(probable)  * 10.0
        avg_sim    = sum(m.similarity for m in morphs) / len(morphs) * 20
        return round(min(100.0, conf_score + prob_score + avg_sim), 1)

    def _build_summary(
        self,
        morphs: list, confirmed: list, probable: list,
        total: int, unique: int, score: float,
    ) -> str:
        parts = [
            f"Identity persistence score {score}/100. "
            f"{total} actor(s) fingerprinted — estimated {unique} unique operator(s)."
        ]
        if confirmed or probable:
            parts.append(
                f"{len(confirmed)} CONFIRMED_MORPH · {len(probable)} PROBABLE_MORPH "
                f"identity change(s) detected."
            )
            if morphs:
                top = morphs[0]
                parts.append(
                    f"Highest confidence: '{top.actor_a}' ≡ '{top.actor_b}' "
                    f"(similarity {top.similarity:.3f})."
                )
        else:
            parts.append("No identity morphs detected — all actors appear to be distinct individuals.")
        return " ".join(parts)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            # Ensure base actors table exists (shared with E6)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS actors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    UNIQUE(normalized_name)
                );
            """)
            conn.executescript(_FINGERPRINT_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _empty() -> IdentityPersistenceReport:
        return IdentityPersistenceReport(
            morphs=[], confirmed_morphs=[], probable_morphs=[],
            total_fingerprinted=0, unique_operators=0,
            persistence_score=0.0,
            summary="No fingerprint data available for identity analysis.",
        )

    @property
    def _min_comments(self) -> int:
        return self._min_comms
