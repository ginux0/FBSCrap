"""
name_utils — Global actor name extraction and cleaning utility.

Single source of truth for all name processing across FBScrap engines.
Facebook DOM frequently merges author name + comment body on the same line
without a space, e.g. "Ana Garcia LopezEmpezó el CHAY..." — this module
detects and splits those merges.

Usage:
    from engines.name_utils import clean_actor_name, truncate_actor

    author = clean_actor_name(raw_line)          # extract clean name
    label  = truncate_actor(author, max_len=28)  # for display
"""
from __future__ import annotations
import re

# ── Regex patterns ────────────────────────────────────────────────────────────

# Detects a CamelCase merge point: lowercase letter immediately followed by
# an uppercase letter, digit, '#', '¿', '¡', '@', or emoji range.
# Example: "RosaExcelente" → split at 'a'→'E'
_CAMEL_MERGE = re.compile(
    r'([a-záéíóúüñ])([A-ZÁÉÍÓÚÜÑ\d#¿¡@])',
    re.UNICODE,
)

# A proper name segment: Title-Case words interleaved with optional lowercase particles
# Handles: "Ana María", "Juan Carlos López", "José de la Rosa", "María del Carmen"
# Name segment: TitleCase word with optional hyphenated/apostrophe TitleCase continuation
# Matches: "García", "Al-Rashid", "Jean-Pierre", "O'Brien", "D'Angelo"
_NAME_SEG = (
    r"[A-ZÁÉÍÓÚÜÑ]"
    r"(?:'[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+|[a-záéíóúüñ]+)"  # O'Brien or regular
    r"(?:-[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)*"               # optional -Compound
)
_PARTICLE  = r"(?:de[l]?|la|los|las|el|san|santa|von|van)"

_PROPER_NAME = re.compile(
    rf'^((?:{_NAME_SEG})'
    rf'(?:\s+(?:{_NAME_SEG}|{_PARTICLE})){{0,6}})',
    re.UNICODE,
)

# Strip domain extensions to clean page-account names like "Autorsinaloahoy.com.mx"
_DOMAIN_STRIP = re.compile(r'\.[a-z]{2,6}(?:\.[a-z]{2,3})*', re.IGNORECASE)

# Facebook page/org account indicators — strip these from name display
_ORG_NOISE = re.compile(
    r'\b(Administrador|Administrator|Página|Page|Patrocinado|Sponsored)\b',
    re.IGNORECASE,
)

# Trailing noise injected by FB: "· Editado", "· Me gusta", timestamps
_TRAILING_NOISE = re.compile(r'\s*[·•]\s*.+$')
_TIMESTAMP_SUFFIX = re.compile(
    r'\s+\d+\s*(?:h(?:rs?|oras?)?|min(?:utos?)?|s(?:eg)?|d(?:ías?|ias?|ays?)?).*$',
    re.IGNORECASE,
)


def clean_actor_name(raw: str, max_len: int = 60) -> str:
    """
    Extract a clean actor/author name from a raw Facebook DOM text line.

    Handles:
    - CamelCase merges: "Ana LopezExcelente..." → "Ana Lopez"
    - Trailing timestamps: "Juan García 14 h" → "Juan García"
    - Trailing FB noise: "Rosa Pérez · Editado" → "Rosa Pérez"
    - URL/link leakage: "El Debate https://..." → "El Debate"
    - Empty or whitespace-only input → "?"

    Returns a cleaned, title-cased name string, never empty.
    """
    if not raw:
        return "?"

    name = raw.strip()

    # Remove trailing FB dot-separator noise ("· Editado", "· Me gusta")
    name = _TRAILING_NOISE.sub("", name).strip()

    # Remove timestamp suffixes that leaked onto the author line
    name = _TIMESTAMP_SUFFIX.sub("", name).strip()

    # Remove full URLs
    name = re.sub(r'\s*https?://\S*', "", name).strip()

    # Strip domain extensions from page/org account names ("sinaloahoy.com.mx" → "sinaloahoy")
    name = _DOMAIN_STRIP.sub("", name).strip()

    # Detect and split CamelCase merge (name+comment body fused without space)
    merge = _CAMEL_MERGE.search(name)
    if merge:
        # Keep only the portion before the merge point
        name = name[:merge.start(2)].strip()

    # After split, try to extract the proper name portion only
    m = _PROPER_NAME.match(name)
    if m:
        name = m.group(1).strip()

    # Remove org noise markers
    name = _ORG_NOISE.sub("", name).strip()

    # Final cleanup: collapse multiple spaces
    name = re.sub(r'\s{2,}', " ", name).strip()

    if not name or len(name) < 2:
        return "?"

    return name[:max_len]


def truncate_actor(name: str, max_len: int = 28) -> str:
    """
    Truncate a display name to max_len with ellipsis if needed.
    Always call clean_actor_name first before truncating.
    """
    name = name.strip()
    if len(name) <= max_len:
        return name
    return name[:max_len - 1] + "…"


def clean_actor_list(names: list[str], max_len: int = 60) -> list[str]:
    """
    Clean a list of actor names, deduplicating after cleaning.
    """
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        cleaned = clean_actor_name(n, max_len)
        if cleaned != "?" and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result
