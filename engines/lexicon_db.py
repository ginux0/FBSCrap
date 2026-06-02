"""
NULLSEC LexiconDB — SQLite-backed keyword/lexicon manager.

All sentiment lexicons, attack words, bot signals, and templates live here.
Auto-creates and seeds the DB on first run. Cached in memory after first load.
Zero hardcoding in analysis engines — everything is queryable and updatable.

Usage:
  db = LexiconDB()
  neg_corrupt = db.load_sentiment_category("neg_corruption")  -> dict[str, float]
  attack_words = db.load_attack_words()                       -> set[str]
  templates    = db.load_attack_templates()                   -> list[str]
  bot_keywords = db.load_bot_name_keywords()                  -> list[str]

  # Live update (no restart needed — cache invalidated automatically)
  db.add_keyword("neg_corruption", "enriquecimiento ilícito", 3.0, context="sinaloa")
  db.add_attack_word("asqueroso")
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).parent.parent / "data" / "lexicons.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentiment_words (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT    NOT NULL,
    phrase   TEXT    NOT NULL,
    score    REAL    NOT NULL,
    context  TEXT    DEFAULT 'generic',
    active   INTEGER DEFAULT 1,
    UNIQUE(category, phrase)
);

CREATE TABLE IF NOT EXISTS attack_words (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    word     TEXT    NOT NULL UNIQUE,
    category TEXT    DEFAULT 'generic',
    active   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS attack_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT    NOT NULL UNIQUE,
    description TEXT,
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bot_name_keywords (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT    NOT NULL UNIQUE,
    active  INTEGER DEFAULT 1
);
"""

# ── Seed data (all previously hardcoded, now in DB) ──────────────────────────

_SEED_SENTIMENT: list[tuple[str, str, float, str]] = [
    # (category, phrase, score, context)

    # NEG_CORRUPTION — generic
    ("neg_corruption", "corrupto", 3.0, "generic"),
    ("neg_corruption", "corrupcion", 3.0, "generic"),
    ("neg_corruption", "corrupción", 3.0, "generic"),
    ("neg_corruption", "ladron", 3.0, "generic"),
    ("neg_corruption", "ladrón", 3.0, "generic"),
    ("neg_corruption", "roba", 2.8, "generic"),
    ("neg_corruption", "robar", 2.8, "generic"),
    ("neg_corruption", "robaron", 2.8, "generic"),
    ("neg_corruption", "se robo", 3.0, "generic"),
    ("neg_corruption", "se robó", 3.0, "generic"),
    ("neg_corruption", "robo", 2.8, "generic"),
    ("neg_corruption", "fraude", 3.0, "generic"),
    ("neg_corruption", "fraudulento", 2.8, "generic"),
    ("neg_corruption", "malversacion", 2.8, "generic"),
    ("neg_corruption", "malversación", 2.8, "generic"),
    ("neg_corruption", "peculado", 2.8, "generic"),
    ("neg_corruption", "desvio", 2.5, "generic"),
    ("neg_corruption", "desvío", 2.5, "generic"),
    ("neg_corruption", "desfalco", 2.8, "generic"),
    ("neg_corruption", "saqueo", 2.5, "generic"),
    ("neg_corruption", "ilegal", 2.0, "generic"),
    ("neg_corruption", "ilegalmente", 2.2, "generic"),
    ("neg_corruption", "irregular", 1.8, "generic"),
    ("neg_corruption", "soborno", 2.5, "generic"),
    ("neg_corruption", "mordida", 2.0, "generic"),
    ("neg_corruption", "coima", 2.0, "generic"),
    ("neg_corruption", "dinero publico", 2.5, "generic"),
    ("neg_corruption", "erario", 2.3, "generic"),
    ("neg_corruption", "licitacion", 1.3, "generic"),
    ("neg_corruption", "licitación", 1.3, "generic"),
    ("neg_corruption", "sin licitar", 2.8, "generic"),
    ("neg_corruption", "patrullas", 1.0, "generic"),
    ("neg_corruption", "171 millones", 3.0, "generic"),
    ("neg_corruption", "171 mdp", 3.0, "generic"),
    ("neg_corruption", "recursos publicos", 2.5, "generic"),
    # NEG_CORRUPTION — political corruption terms
    ("neg_corruption", "inconsistencias", 2.0, "sinaloa"),
    ("neg_corruption", "inconsistencia", 2.0, "sinaloa"),
    ("neg_corruption", "cuentas publicas", 2.0, "sinaloa"),
    ("neg_corruption", "cuentas públicas", 2.0, "sinaloa"),
    ("neg_corruption", "señalamiento", 1.5, "sinaloa"),
    ("neg_corruption", "señalamientos", 1.5, "sinaloa"),
    ("neg_corruption", "señalado", 1.8, "sinaloa"),
    ("neg_corruption", "investigado", 1.5, "sinaloa"),
    ("neg_corruption", "licitaciones", 1.5, "sinaloa"),
    ("neg_corruption", "adjudicacion", 2.0, "sinaloa"),
    ("neg_corruption", "adjudicación", 2.0, "sinaloa"),
    ("neg_corruption", "enriquecimiento ilicito", 3.0, "sinaloa"),
    ("neg_corruption", "enriquecimiento ilícito", 3.0, "sinaloa"),
    ("neg_corruption", "opacidad", 2.0, "sinaloa"),
    ("neg_corruption", "sin transparencia", 2.3, "sinaloa"),

    # NEG_PERSONAL — generic
    ("neg_personal", "imbecil", 2.5, "generic"),
    ("neg_personal", "imbécil", 2.5, "generic"),
    ("neg_personal", "idiota", 2.5, "generic"),
    ("neg_personal", "estupido", 2.3, "generic"),
    ("neg_personal", "estúpido", 2.3, "generic"),
    ("neg_personal", "pendejo", 2.0, "generic"),
    ("neg_personal", "pendejos", 2.0, "generic"),
    ("neg_personal", "inutil", 2.0, "generic"),
    ("neg_personal", "inútil", 2.0, "generic"),
    ("neg_personal", "mentiroso", 2.8, "generic"),
    ("neg_personal", "mentirosa", 2.8, "generic"),
    ("neg_personal", "mentira", 2.0, "generic"),
    ("neg_personal", "miente", 2.3, "generic"),
    ("neg_personal", "embustero", 2.5, "generic"),
    ("neg_personal", "hipocrita", 2.3, "generic"),
    ("neg_personal", "hipócrita", 2.3, "generic"),
    ("neg_personal", "traidor", 2.8, "generic"),
    ("neg_personal", "traidora", 2.8, "generic"),
    ("neg_personal", "traicion", 2.5, "generic"),
    ("neg_personal", "traición", 2.5, "generic"),
    ("neg_personal", "rata", 2.5, "generic"),
    ("neg_personal", "ratas", 2.5, "generic"),
    ("neg_personal", "ratero", 2.8, "generic"),
    ("neg_personal", "ratera", 2.8, "generic"),
    ("neg_personal", "vibora", 2.3, "generic"),
    ("neg_personal", "víbora", 2.3, "generic"),
    ("neg_personal", "sinverguenza", 2.5, "generic"),
    ("neg_personal", "sinvergüenza", 2.5, "generic"),
    ("neg_personal", "descarado", 2.0, "generic"),
    ("neg_personal", "cinico", 2.0, "generic"),
    ("neg_personal", "cínico", 2.0, "generic"),
    ("neg_personal", "delincuente", 2.8, "generic"),
    ("neg_personal", "criminal", 3.0, "generic"),
    ("neg_personal", "malandro", 2.5, "generic"),
    ("neg_personal", "farsante", 2.5, "generic"),
    ("neg_personal", "impostor", 2.5, "generic"),
    ("neg_personal", "bueno para nada", 2.5, "generic"),
    ("neg_personal", "mediocre", 1.8, "generic"),
    ("neg_personal", "inepto", 1.8, "generic"),
    ("neg_personal", "miserable", 2.5, "generic"),
    ("neg_personal", "deshonesto", 2.8, "generic"),
    ("neg_personal", "deshonesta", 2.8, "generic"),
    ("neg_personal", "vergüenza", 2.0, "generic"),
    ("neg_personal", "verguenza", 2.0, "generic"),
    ("neg_personal", "que pena", 1.5, "generic"),
    # NEG_PERSONAL — personal attack terms
    ("neg_personal", "despreciable", 2.8, "sinaloa"),
    ("neg_personal", "llorando", 1.8, "sinaloa"),
    ("neg_personal", "llorón", 2.0, "sinaloa"),
    ("neg_personal", "limpiaba los zapatos", 3.0, "sinaloa"),
    ("neg_personal", "lamebotas", 2.8, "sinaloa"),
    ("neg_personal", "hueso", 1.5, "sinaloa"),
    ("neg_personal", "hueso que perdió", 3.0, "sinaloa"),
    ("neg_personal", "desaforado", 2.5, "sinaloa"),
    ("neg_personal", "prófugo", 2.5, "sinaloa"),
    ("neg_personal", "profugo", 2.5, "sinaloa"),
    ("neg_personal", "cobarde", 2.3, "sinaloa"),
    ("neg_personal", "huyó", 2.0, "sinaloa"),
    ("neg_personal", "huyo", 2.0, "sinaloa"),
    ("neg_personal", "simulacro", 1.8, "sinaloa"),
    ("neg_personal", "show político", 2.0, "sinaloa"),
    ("neg_personal", "show politico", 2.0, "sinaloa"),
    ("neg_personal", "lacayo", 2.5, "sinaloa"),
    ("neg_personal", "pelele", 2.3, "sinaloa"),

    # NEG_POLITICAL — generic
    ("neg_political", "narco", 3.0, "generic"),
    ("neg_political", "narcos", 3.0, "generic"),
    ("neg_political", "narcoestado", 3.0, "generic"),
    ("neg_political", "narcogobierno", 3.0, "generic"),
    ("neg_political", "narcopolitico", 3.0, "generic"),
    ("neg_political", "narco político", 3.0, "generic"),
    ("neg_political", "cartel", 3.0, "generic"),
    ("neg_political", "crimen organizado", 3.0, "generic"),
    ("neg_political", "mayiza", 3.0, "generic"),
    ("neg_political", "mayo zambada", 3.0, "generic"),
    ("neg_political", "zambada", 2.5, "generic"),
    ("neg_political", "chapitos", 3.0, "generic"),
    ("neg_political", "cjng", 3.0, "generic"),
    ("neg_political", "sicario", 3.0, "generic"),
    ("neg_political", "desafuero", 2.0, "generic"),
    ("neg_political", "acusado", 1.5, "generic"),
    ("neg_political", "detenido", 1.5, "generic"),
    ("neg_political", "arrestado", 1.5, "generic"),
    ("neg_political", "preso", 2.0, "generic"),
    ("neg_political", "encarcelado", 2.0, "generic"),
    ("neg_political", "culpable", 2.5, "generic"),
    ("neg_political", "abuso de autoridad", 2.5, "generic"),
    ("neg_political", "abuso de poder", 2.5, "generic"),
    ("neg_political", "nepotismo", 2.3, "generic"),
    ("neg_political", "impunidad", 2.5, "generic"),
    ("neg_political", "impune", 2.3, "generic"),
    ("neg_political", "encubrimiento", 2.5, "generic"),
    ("neg_political", "tapadera", 2.5, "generic"),
    ("neg_political", "complice", 2.3, "generic"),
    ("neg_political", "cómplice", 2.3, "generic"),
    # NEG_POLITICAL — Sinaloa
    ("neg_political", "rocha moya", 2.0, "sinaloa"),
    ("neg_political", "rubén rocha", 1.8, "sinaloa"),
    ("neg_political", "ruben rocha", 1.8, "sinaloa"),
    ("neg_political", "rochismo", 2.0, "sinaloa"),
    ("neg_political", "perseguido políticamente", 2.8, "sinaloa"),
    ("neg_political", "persecución política", 2.8, "sinaloa"),
    ("neg_political", "persecucion politica", 2.8, "sinaloa"),
    ("neg_political", "guerra política", 2.5, "sinaloa"),
    ("neg_political", "guerra politica", 2.5, "sinaloa"),
    ("neg_political", "amenazas de rocha", 3.0, "sinaloa"),
    ("neg_political", "expediente", 1.3, "sinaloa"),
    ("neg_political", "expedientes", 1.3, "sinaloa"),
    ("neg_political", "extradición", 2.0, "sinaloa"),
    ("neg_political", "extradicion", 2.0, "sinaloa"),
    ("neg_political", "vinculado a proceso", 2.5, "sinaloa"),
    ("neg_political", "auto de vinculación", 2.5, "sinaloa"),

    # AGGRESSIVE
    ("aggressive", "matar", 3.5, "generic"),
    ("aggressive", "matarlo", 3.5, "generic"),
    ("aggressive", "matenlo", 3.5, "generic"),
    ("aggressive", "lo maten", 3.5, "generic"),
    ("aggressive", "asesino", 3.5, "generic"),
    ("aggressive", "asesinar", 3.5, "generic"),
    ("aggressive", "asesinarlo", 3.5, "generic"),
    ("aggressive", "golpear", 2.5, "generic"),
    ("aggressive", "golpea", 2.5, "generic"),
    ("aggressive", "golpeen", 2.5, "generic"),
    ("aggressive", "linchar", 3.5, "generic"),
    ("aggressive", "lincharlo", 3.5, "generic"),
    ("aggressive", "linchamiento", 3.5, "generic"),
    ("aggressive", "colgar", 3.0, "generic"),
    ("aggressive", "colgarlo", 3.0, "generic"),
    ("aggressive", "ahorcar", 3.0, "generic"),
    ("aggressive", "ejecutar", 3.0, "generic"),
    ("aggressive", "ejecucion", 3.0, "generic"),
    ("aggressive", "eliminarlo", 2.5, "generic"),
    ("aggressive", "crucificar", 2.8, "generic"),
    ("aggressive", "lapidarlo", 3.0, "generic"),
    ("aggressive", "que se muera", 3.5, "generic"),
    ("aggressive", "ojala muera", 3.5, "generic"),
    ("aggressive", "que muera", 3.5, "generic"),
    ("aggressive", "muerto", 2.5, "generic"),
    ("aggressive", "muerte", 2.5, "generic"),
    ("aggressive", "amenaza", 2.5, "generic"),
    ("aggressive", "amenazar", 2.5, "generic"),
    ("aggressive", "amenazas", 2.5, "generic"),
    ("aggressive", "violencia", 2.5, "generic"),
    ("aggressive", "violento", 2.3, "generic"),
    ("aggressive", "agresion", 2.5, "generic"),
    ("aggressive", "agresión", 2.5, "generic"),
    ("aggressive", "atacar", 2.0, "generic"),
    ("aggressive", "ataque", 2.0, "generic"),
    ("aggressive", "al bote", 2.0, "generic"),
    ("aggressive", "encárcelenlo", 2.0, "generic"),
    ("aggressive", "encerrarlo", 2.0, "generic"),
    ("aggressive", "a la carcel", 2.0, "generic"),
    ("aggressive", "a la cárcel", 2.0, "generic"),
    ("aggressive", "hijo de puta", 3.5, "generic"),
    ("aggressive", "hdp", 3.0, "generic"),
    ("aggressive", "puta madre", 3.0, "generic"),
    ("aggressive", "cabron", 2.0, "generic"),
    ("aggressive", "cabrón", 2.0, "generic"),
    ("aggressive", "chingado", 2.0, "generic"),
    ("aggressive", "chinga", 2.5, "generic"),
    ("aggressive", "mierda", 2.0, "generic"),
    ("aggressive", "bastardo", 2.5, "generic"),
    ("aggressive", "bastardos", 2.5, "generic"),
    ("aggressive", "maldito", 2.0, "generic"),
    ("aggressive", "maldita", 2.0, "generic"),
    ("aggressive", "asco", 1.8, "generic"),
    ("aggressive", "fuera", 1.5, "generic"),
    ("aggressive", "abajo", 1.5, "generic"),
    ("aggressive", "que se vaya", 1.5, "generic"),
    ("aggressive", "ya estuvo", 1.3, "generic"),
    ("aggressive", "se lo merece", 1.5, "generic"),
    ("aggressive", "lo merecía", 1.5, "generic"),

    # POSITIVE
    ("positive", "inocente", 3.0, "generic"),
    ("positive", "inocencia", 3.0, "generic"),
    ("positive", "victima", 2.5, "generic"),
    ("positive", "víctima", 2.5, "generic"),
    ("positive", "perseguido", 2.5, "generic"),
    ("positive", "persecucion politica", 2.8, "generic"),
    ("positive", "lo apoyo", 2.8, "generic"),
    ("positive", "te apoyo", 2.8, "generic"),
    ("positive", "apoyamos", 2.8, "generic"),
    ("positive", "apoyo", 2.0, "generic"),
    ("positive", "respaldo", 2.0, "generic"),
    ("positive", "te apoyamos", 2.8, "generic"),
    ("positive", "con el", 1.5, "generic"),
    ("positive", "con él", 2.0, "generic"),
    ("positive", "fuerza", 1.8, "generic"),
    ("positive", "animo", 1.8, "generic"),
    ("positive", "ánimo", 1.8, "generic"),
    ("positive", "transparente", 3.0, "generic"),
    ("positive", "honesto", 2.8, "generic"),
    ("positive", "honestidad", 2.8, "generic"),
    ("positive", "buen trabajo", 2.5, "generic"),
    ("positive", "buena gestion", 2.5, "generic"),
    ("positive", "buena gestión", 2.5, "generic"),
    ("positive", "logro", 2.0, "generic"),
    ("positive", "logros", 2.0, "generic"),
    ("positive", "obras", 1.5, "generic"),
    ("positive", "injusticia", 2.3, "generic"),
    ("positive", "no es justo", 2.0, "generic"),
    ("positive", "no tiene pruebas", 2.0, "generic"),
    ("positive", "sin pruebas", 2.0, "generic"),
    ("positive", "son mentiras", 2.5, "generic"),
    ("positive", "es mentira", 2.3, "generic"),
    ("positive", "lo persiguen", 2.5, "generic"),
    ("positive", "lo estan persiguiendo", 2.8, "generic"),
    ("positive", "dios te bendiga", 2.0, "generic"),
    ("positive", "bendiciones", 1.8, "generic"),
    ("positive", "orando", 1.5, "generic"),
    ("positive", "candidato", 1.5, "generic"),
    ("positive", "senado", 1.3, "generic"),
    ("positive", "votamos", 1.5, "generic"),
    # POSITIVE — support and defense terms
    ("positive", "perseguido políticamente", 2.8, "sinaloa"),
    ("positive", "perseguido por", 2.5, "sinaloa"),
    ("positive", "primer perseguido", 2.5, "sinaloa"),
    ("positive", "amenazado por", 2.5, "sinaloa"),
    ("positive", "lo amenazan", 2.5, "sinaloa"),
]

_SEED_ATTACK_WORDS: list[tuple[str, str]] = [
    # (word, category)
    ("corrupto", "corruption"), ("corrupta", "corruption"),
    ("corruptos", "corruption"), ("corruptas", "corruption"),
    ("ladrón", "corruption"), ("ladron", "corruption"),
    ("ladrona", "corruption"), ("ladrones", "corruption"),
    ("ratero", "corruption"), ("ratera", "corruption"),
    ("mentiroso", "insult"), ("mentirosa", "insult"),
    ("mentirosos", "insult"), ("mafioso", "insult"), ("mafiosa", "insult"),
    ("sinvergüenza", "insult"), ("sinverguenza", "insult"),
    ("hipócrita", "insult"), ("hipocrìta", "insult"),
    ("traidor", "insult"), ("traidora", "insult"),
    ("inútil", "insult"), ("inutiles", "insult"),
    ("a la cárcel", "threat"), ("a la carcel", "threat"),
    ("que lo metan", "threat"), ("que lo paren", "threat"),
    ("delincuente", "criminal"), ("criminal", "criminal"),
    ("narco", "criminal"), ("narcopolítico", "criminal"),
    ("pendejo", "profanity"), ("pendeja", "profanity"),
    ("idiota", "profanity"), ("imbécil", "profanity"), ("imbecil", "profanity"),
    ("asqueroso", "profanity"), ("asquerosa", "profanity"),
    ("escoria", "insult"), ("basura", "insult"),
    ("despreciable", "insult"), ("miserable", "insult"),
    ("cobarde", "insult"), ("huyó", "insult"),
    ("lamebotas", "insult"), ("lacayo", "insult"),
]

_SEED_ATTACK_TEMPLATES: list[tuple[str, str]] = [
    # (regex pattern, description)
    (r"^(corrupto|ladr[oó]n|ratero|mentiroso|mafioso|sinverg[üu]enza|traidor)[\s!.]*$",
     "Single attack word, no argument"),
    (r"^(a la c[aá]rcel|que lo metan preso|que le caiga todo el peso)[\s!.]*$",
     "Prison demand template"),
    (r"^(rob[oó])\s+\w[\s!.]*$",
     "Simple theft accusation"),
    (r"^[🤮🤡😡👎💩🚔]+$",
     "Emoji-only attack"),
    (r"^(fuera|abajo)\s+\w+[\s!.]*$",
     "Remove from office demand"),
]

_SEED_BOT_NAME_KEYWORDS: list[str] = [
    "noticias", "noticiero", "periodico", "diario", "portal", "media",
    "news", "info", "reportero", "periodista", "ciudadano", "informador",
    "azteca", "debate", "noroeste", "reforma", "excelsior",
    "alerta", "urgente", "verdad", "pueblo", "mexico", "nacional",
    "sinaloa", "ahome", "culiacan", "mochis", "mazatlan",
]


# ── DB Manager ────────────────────────────────────────────────────────────────

class LexiconDB:
    """
    SQLite-backed lexicon manager with in-memory cache.
    Auto-creates and seeds on first access.
    Cache is invalidated automatically on any write operation.
    """

    _cache: dict[str, object] = {}

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._seed_if_empty(conn)

    def _seed_if_empty(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(*) FROM sentiment_words").fetchone()[0]
        if count > 0:
            return

        conn.executemany(
            "INSERT OR IGNORE INTO sentiment_words (category, phrase, score, context) VALUES (?,?,?,?)",
            _SEED_SENTIMENT,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO attack_words (word, category) VALUES (?,?)",
            _SEED_ATTACK_WORDS,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO attack_templates (pattern, description) VALUES (?,?)",
            _SEED_ATTACK_TEMPLATES,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO bot_name_keywords (keyword) VALUES (?)",
            [(k,) for k in _SEED_BOT_NAME_KEYWORDS],
        )
        conn.commit()
        print(f"  [LexiconDB] Seeded: {len(_SEED_SENTIMENT)} sentiment words, "
              f"{len(_SEED_ATTACK_WORDS)} attack words → {self.db_path.name}")

    # ── Read API (cached) ─────────────────────────────────────────────────────

    def load_sentiment_category(self, category: str) -> dict[str, float]:
        """Load all active phrases for a sentiment category as {phrase: score}."""
        key = f"sent_{category}"
        if key not in LexiconDB._cache:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT phrase, score FROM sentiment_words "
                    "WHERE category=? AND active=1",
                    (category,),
                ).fetchall()
            LexiconDB._cache[key] = {r["phrase"]: r["score"] for r in rows}
        return LexiconDB._cache[key]  # type: ignore

    def load_all_sentiment(self) -> dict[str, dict[str, float]]:
        """Load all active sentiment categories at once."""
        categories = ["neg_corruption", "neg_personal", "neg_political",
                      "aggressive", "positive"]
        return {cat: self.load_sentiment_category(cat) for cat in categories}

    def load_attack_words(self) -> set[str]:
        """Load all active attack words as a set."""
        key = "attack_words"
        if key not in LexiconDB._cache:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT word FROM attack_words WHERE active=1"
                ).fetchall()
            LexiconDB._cache[key] = {r["word"] for r in rows}
        return LexiconDB._cache[key]  # type: ignore

    def load_attack_templates(self) -> list[str]:
        """Load all active attack template regex patterns."""
        key = "attack_templates"
        if key not in LexiconDB._cache:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT pattern FROM attack_templates WHERE active=1"
                ).fetchall()
            LexiconDB._cache[key] = [r["pattern"] for r in rows]
        return LexiconDB._cache[key]  # type: ignore

    def load_bot_name_keywords(self) -> list[str]:
        """Load all active bot name keywords."""
        key = "bot_name_keywords"
        if key not in LexiconDB._cache:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT keyword FROM bot_name_keywords WHERE active=1"
                ).fetchall()
            LexiconDB._cache[key] = [r["keyword"] for r in rows]
        return LexiconDB._cache[key]  # type: ignore

    # ── Write API (invalidates cache) ─────────────────────────────────────────

    def add_keyword(
        self,
        category: str,
        phrase: str,
        score: float,
        context: str = "generic",
    ) -> None:
        """Add or update a sentiment keyword."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sentiment_words (category, phrase, score, context) VALUES (?,?,?,?) "
                "ON CONFLICT(category, phrase) DO UPDATE SET score=excluded.score, "
                "context=excluded.context, active=1",
                (category, phrase, score, context),
            )
            conn.commit()
        LexiconDB._cache.pop(f"sent_{category}", None)
        print(f"  [LexiconDB] Added [{category}] '{phrase}' score={score} ctx={context}")

    def add_attack_word(self, word: str, category: str = "generic") -> None:
        """Add an attack word for comment bot detection."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO attack_words (word, category) VALUES (?,?)",
                (word, category),
            )
            conn.commit()
        LexiconDB._cache.pop("attack_words", None)

    def disable_keyword(self, category: str, phrase: str) -> None:
        """Soft-delete a keyword (sets active=0)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE sentiment_words SET active=0 WHERE category=? AND phrase=?",
                (category, phrase),
            )
            conn.commit()
        LexiconDB._cache.pop(f"sent_{category}", None)

    def search_keywords(self, term: str) -> list[dict]:
        """Search for keywords containing a term across all categories."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, phrase, score, context, active "
                "FROM sentiment_words WHERE phrase LIKE ? ORDER BY category, score DESC",
                (f"%{term}%",),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        """Return count per table."""
        with self._connect() as conn:
            return {
                "sentiment_words":    conn.execute("SELECT COUNT(*) FROM sentiment_words WHERE active=1").fetchone()[0],
                "attack_words":       conn.execute("SELECT COUNT(*) FROM attack_words WHERE active=1").fetchone()[0],
                "attack_templates":   conn.execute("SELECT COUNT(*) FROM attack_templates WHERE active=1").fetchone()[0],
                "bot_name_keywords":  conn.execute("SELECT COUNT(*) FROM bot_name_keywords WHERE active=1").fetchone()[0],
            }

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._cache.clear()


# ── Module-level singleton ────────────────────────────────────────────────────
_db: Optional[LexiconDB] = None


def get_db() -> LexiconDB:
    """Return the module-level singleton, creating it if needed."""
    global _db
    if _db is None:
        _db = LexiconDB()
    return _db
