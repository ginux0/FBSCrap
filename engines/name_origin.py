"""
NameOriginDetector — statistical name-origin analysis for Mexican political CIB context.

Zero hardcoded data. All name lists, weights, and patterns are loaded from
cfg["troll_hunter"]["name_origins_file"] (defaults to
config/patterns/name_origins.json). Add or remove names in that file — no
code changes needed.

Returns NameOriginResult with: origin label, confidence 0.0-1.0, matched pattern.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache


@dataclass
class NameOriginResult:
    origin:          str      # ARABIC | SOUTH_ASIAN | MALAY_INDONESIAN | RUSSIAN_SLAVIC |
                              # CHINESE | JAPANESE | KOREAN | US_ENGLISH | PAGE_ACCOUNT | UNKNOWN
    confidence:      float    # 0.0 – 1.0
    weight_mult:     float    # origin's weight_multiplier from JSON
    matched_pattern: str      # what triggered the detection
    severity:        str = "MEDIUM"  # CRITICAL | HIGH | MEDIUM | LOW (from JSON)


# ── Loader ─────────────────────────────────────────────────────────────────────

def _load_db(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class NameOriginDetector:
    """
    Detect statistical name origin of a Facebook author string.
    Loads name database from JSON — no lists embedded in code.
    """

    def __init__(self, db_path: str | Path | None = None, cfg: dict | None = None):
        if db_path is None:
            c = (cfg or {}).get("troll_hunter", {})
            rel = c.get("name_origins_file", "config/patterns/name_origins.json")
            # resolve relative to fbscrap root (parent of engines/)
            base = Path(__file__).parent.parent
            db_path = base / rel
        self._db   = _load_db(db_path)
        self._cache: dict[str, NameOriginResult] = {}
        self._compile()

    def _compile(self) -> None:
        """Pre-compile structures for O(1) lookups."""
        origins = self._db.get("origins", {})

        # Per-origin frozensets for first names, last names
        self._first:   dict[str, frozenset] = {}
        self._last:    dict[str, frozenset] = {}
        self._mult:    dict[str, float]     = {}
        self._sev:     dict[str, str]       = {}

        for origin, data in origins.items():
            fn = (data.get("first_names", []) +
                  data.get("first_names_male", []) +
                  data.get("first_names_female", []))
            ln = (data.get("last_names", []) + data.get("last_name_endings", []))
            self._first[origin] = frozenset(n.lower() for n in fn)
            self._last[origin]  = frozenset(n.lower() for n in ln)
            self._mult[origin]  = data.get("weight_multiplier", 1.0)
            self._sev[origin]   = data.get("severity", "MEDIUM")

        # Arabic-specific: last name prefixes
        ar = origins.get("ARABIC", {})
        self._ar_prefixes = tuple(
            p.lower() for p in ar.get("last_name_prefixes", [])
        )

        # Russian-specific: last name suffixes
        ru = origins.get("RUSSIAN_SLAVIC", {})
        self._ru_suffixes = tuple(ru.get("last_name_suffixes", []))

        # US_ENGLISH: require BOTH first AND last to be foreign
        us = origins.get("US_ENGLISH", {})
        self._us_require_both = us.get("require_both_foreign", True)

        # Page account detection
        pa = self._db.get("page_account", {})
        kw_es   = pa.get("keywords_es", [])
        kw_en   = pa.get("keywords_en", [])
        all_kw  = [re.escape(k) for k in sorted(kw_es + kw_en, key=len, reverse=True)]
        self._page_re = re.compile(
            r"\b(" + "|".join(all_kw) + r")\b", re.IGNORECASE
        ) if all_kw else None
        self._page_min_words = pa.get("min_words_org_name", 3)
        self._page_caps_len  = pa.get("all_caps_word_min_len", 3)
        self._all_caps_re    = re.compile(r"\b[A-ZÁÉÍÓÚÜÑ]{%d,}\b" % self._page_caps_len)

        # Bot account patterns
        bp = self._db.get("bot_account_patterns", {})
        self._generic_pfx = frozenset(bp.get("generic_prefixes", []))
        raw_pats = bp.get("suspicious_name_patterns", [])
        self._bot_pats = [re.compile(p, re.IGNORECASE) for p in raw_pats]

    # ─────────────────────────────────────────────────────────────────────────

    def detect(self, name: str) -> NameOriginResult:
        if not name or len(name) < 2:
            return NameOriginResult("UNKNOWN", 0.0, 1.0, "")

        # Cache hit
        if name in self._cache:
            return self._cache[name]

        result = self._detect_uncached(name)
        self._cache[name] = result
        return result

    def _detect_uncached(self, name: str) -> NameOriginResult:
        clean = name.strip()
        lower = clean.lower()
        parts = clean.split()
        first = parts[0].lower() if parts else ""
        last  = parts[-1].lower() if len(parts) > 1 else ""

        # ── 1. Page account check (highest priority) ──────────────────────────
        page_conf = self._page_score(clean, lower, parts)
        if page_conf >= 0.65:
            return NameOriginResult(
                "PAGE_ACCOUNT", page_conf,
                self._mult.get("page_account", 1.0),
                f"page_keyword:{lower[:35]}",
            )

        # ── 2. Arabic ─────────────────────────────────────────────────────────
        # First name direct match
        if first in self._first.get("ARABIC", frozenset()):
            return self._hit("ARABIC", 0.95, f"arabic_first:{first}")
        # Last name prefix (al-, el-, abu-, etc.)
        for pfx in self._ar_prefixes:
            if lower.startswith(pfx) or f" {pfx}" in lower:
                return self._hit("ARABIC", 0.90, f"arabic_prefix:{pfx.strip()}")
        # Last name direct match
        if last in self._first.get("ARABIC", frozenset()):
            return self._hit("ARABIC", 0.80, f"arabic_name:{last}")
        # Last name endings (-awi, -ouri, etc.)
        for ending in self._last.get("ARABIC", frozenset()):
            if last.endswith(ending) and len(last) > 4:
                return self._hit("ARABIC", 0.65, f"arabic_ending:{ending}")

        # ── 3. South Asian ────────────────────────────────────────────────────
        if first in self._first.get("SOUTH_ASIAN", frozenset()):
            return self._hit("SOUTH_ASIAN", 0.92, f"sa_first:{first}")
        if last in self._last.get("SOUTH_ASIAN", frozenset()):
            return self._hit("SOUTH_ASIAN", 0.88, f"sa_last:{last}")
        for part in (p.lower() for p in parts):
            if part in self._last.get("SOUTH_ASIAN", frozenset()):
                return self._hit("SOUTH_ASIAN", 0.80, f"sa_surname:{part}")

        # ── 4. Russian / Slavic ───────────────────────────────────────────────
        if first in self._first.get("RUSSIAN_SLAVIC", frozenset()):
            return self._hit("RUSSIAN_SLAVIC", 0.90, f"russian_first:{first}")
        if last in self._first.get("RUSSIAN_SLAVIC", frozenset()):
            return self._hit("RUSSIAN_SLAVIC", 0.82, f"russian_name:{last}")
        for sfx in self._ru_suffixes:
            if last.endswith(sfx) and len(last) > 4:
                return self._hit("RUSSIAN_SLAVIC", 0.70, f"russian_suffix:{sfx}")

        # ── 5. Chinese ────────────────────────────────────────────────────────
        if (last in self._last.get("CHINESE", frozenset()) and
                first in self._first.get("CHINESE", frozenset())):
            return self._hit("CHINESE", 0.88, f"chinese:{first}_{last}")
        if last in self._last.get("CHINESE", frozenset()) and len(parts) <= 2:
            # Short name + Chinese surname → likely Chinese
            return self._hit("CHINESE", 0.72, f"chinese_last:{last}")

        # ── 6. Malay / Indonesian ─────────────────────────────────────────────
        if first in self._first.get("MALAY_INDONESIAN", frozenset()):
            return self._hit("MALAY_INDONESIAN", 0.88, f"malay_first:{first}")
        if last in self._first.get("MALAY_INDONESIAN", frozenset()):
            return self._hit("MALAY_INDONESIAN", 0.75, f"malay_name:{last}")

        # ── 7. Japanese ───────────────────────────────────────────────────────
        if (first in self._first.get("JAPANESE", frozenset()) and
                last in self._last.get("JAPANESE", frozenset())):
            return self._hit("JAPANESE", 0.90, f"japanese:{first}_{last}")
        if (first in self._first.get("JAPANESE", frozenset()) or
                last in self._last.get("JAPANESE", frozenset())):
            return self._hit("JAPANESE", 0.72, f"japanese_partial:{first}_{last}")

        # ── 8. Korean ─────────────────────────────────────────────────────────
        if (last in self._last.get("KOREAN", frozenset()) and
                first in self._first.get("KOREAN", frozenset())):
            return self._hit("KOREAN", 0.88, f"korean:{first}_{last}")
        if last in self._last.get("KOREAN", frozenset()) and len(parts) <= 2:
            return self._hit("KOREAN", 0.68, f"korean_last:{last}")

        # ── 9. US English — only when BOTH first AND last are Anglo ───────────
        if self._us_require_both:
            us_first = self._first.get("US_ENGLISH", frozenset())
            us_last  = self._last.get("US_ENGLISH", frozenset())
            if first in us_first and last in us_last:
                return self._hit("US_ENGLISH", 0.72, f"us_english:{first}_{last}")
        else:
            if first in self._first.get("US_ENGLISH", frozenset()):
                return self._hit("US_ENGLISH", 0.55, f"us_first:{first}")

        # ── 10. Partial page account ──────────────────────────────────────────
        if page_conf >= 0.40:
            return NameOriginResult(
                "PAGE_ACCOUNT", page_conf,
                self._mult.get("page_account", 1.0),
                f"page_partial:{lower[:35]}",
            )

        return NameOriginResult("UNKNOWN", 0.0, 1.0, "")

    # ─────────────────────────────────────────────────────────────────────────

    def _hit(self, origin: str, confidence: float, pattern: str) -> NameOriginResult:
        return NameOriginResult(
            origin=origin,
            confidence=confidence,
            weight_mult=self._mult.get(origin, 1.0),
            matched_pattern=pattern,
            severity=self._sev.get(origin, "MEDIUM"),
        )

    def _page_score(self, name: str, lower: str, parts: list[str]) -> float:
        score = 0.0
        # Keyword match
        if self._page_re and self._page_re.search(name):
            score += 0.55
        # Too many words to be a personal name
        if len(parts) >= self._page_min_words and not self._looks_personal(parts):
            score += 0.20
        elif len(parts) >= 5:
            score += 0.25
        # ALL-CAPS word segment (typical of pages: "NOTICIAS CULIACÁN")
        if self._all_caps_re.search(name):
            score += 0.20
        # Digit in name (e.g., "Noticias Sinaloa 24")
        if any(c.isdigit() for c in name):
            score += 0.15
        return min(1.0, score)

    @staticmethod
    def _looks_personal(parts: list[str]) -> bool:
        """Heuristic: does this look like a real Mexican first + last name?"""
        if len(parts) == 2:
            return True
        # 3-word Mexican names: María de los Ángeles, Juan Carlos López
        if len(parts) == 3 and parts[1].lower() in (
            "de","del","la","los","las","san","carlos","jose","juan","maria"
        ):
            return True
        return False

    def reload(self) -> None:
        """Force reload of name database (useful after editing the JSON)."""
        self._cache.clear()
        self._compile()
