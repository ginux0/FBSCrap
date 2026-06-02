"""Shared parsing utilities — Spanish-aware FB engagement + date parsing."""
from __future__ import annotations
import re
from datetime import datetime, timedelta

_MONTHS = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
}

_RELATIVE_PATTERNS = [
    # Verbose Spanish: "hace X ..."
    (r"hace\s+(\d+)\s+seg",  lambda m,n: n - timedelta(seconds=int(m.group(1)))),
    (r"hace\s+(\d+)\s+min",  lambda m,n: n - timedelta(minutes=int(m.group(1)))),
    (r"hace\s+(\d+)\s+hora", lambda m,n: n - timedelta(hours=int(m.group(1)))),
    (r"hace\s+(\d+)\s+d[ií]a", lambda m,n: n - timedelta(days=int(m.group(1)))),
    (r"hace\s+(\d+)\s+sem",  lambda m,n: n - timedelta(weeks=int(m.group(1)))),
    (r"hace\s+(\d+)\s+mes",  lambda m,n: n - timedelta(days=int(m.group(1))*30)),
    # Compact FB format: "2 h", "1 d", "3 sem", "2 min", "45 s"
    (r"^(\d+)\s*s$",         lambda m,n: n - timedelta(seconds=int(m.group(1)))),
    (r"^(\d+)\s*min$",       lambda m,n: n - timedelta(minutes=int(m.group(1)))),
    (r"^(\d+)\s*h$",         lambda m,n: n - timedelta(hours=int(m.group(1)))),
    (r"^(\d+)\s*d$",         lambda m,n: n - timedelta(days=int(m.group(1)))),
    (r"^(\d+)\s*sem$",       lambda m,n: n - timedelta(weeks=int(m.group(1)))),
    (r"^(\d+)\s*mes",        lambda m,n: n - timedelta(days=int(m.group(1))*30)),
    # English compact: "2h", "3d", "1w"
    (r"^(\d+)\s*w$",         lambda m,n: n - timedelta(weeks=int(m.group(1)))),
    # Verbose English
    (r"(\d+)\s+hour",        lambda m,n: n - timedelta(hours=int(m.group(1)))),
    (r"(\d+)\s+day",         lambda m,n: n - timedelta(days=int(m.group(1)))),
    (r"(\d+)\s+week",        lambda m,n: n - timedelta(weeks=int(m.group(1)))),
    (r"(\d+)\s+minute",      lambda m,n: n - timedelta(minutes=int(m.group(1)))),
    # Yesterday/today
    (r"\bayer\b",             lambda m,n: n - timedelta(days=1)),
    (r"\bhoy\b",              lambda m,n: n),
    (r"\byesterday\b",        lambda m,n: n - timedelta(days=1)),
    (r"\btoday\b",            lambda m,n: n),
]


def parse_relative_date(text: str) -> datetime | None:
    if not text:
        return None
    now  = datetime.now()
    norm = text.strip().lower()
    for pattern, handler in _RELATIVE_PATTERNS:
        m = re.search(pattern, norm)
        if m:
            try:
                return handler(m, now)
            except Exception:
                continue
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?", norm)
    if m:
        day   = int(m.group(1))
        month = _MONTHS.get(m.group(2))
        year  = int(m.group(3)) if m.group(3) else now.year
        if month:
            try:
                return datetime(year, month, day)
            except Exception:
                pass
    return None


def parse_engagement_number(raw: str) -> int:
    """
    Parse Spanish/Facebook number formats:
      '3.241'  → 3241   (period = thousands separator in ES)
      '1,5 mil'→ 1500
      '2,3K'   → 2300
      '1.2K'   → 1200
      '45'     → 45
    """
    if not raw:
        return 0
    raw = raw.strip().lower()

    mul = 1
    if "millón" in raw or "millones" in raw:
        mul = 1_000_000
        raw = re.sub(r"millones?|millón", "", raw).strip()
    elif "mil" in raw:
        mul = 1_000
        raw = re.sub(r"\bmil\b", "", raw).strip()
    elif raw.endswith("m"):
        mul = 1_000_000
        raw = raw[:-1]
    elif raw.endswith("k"):
        mul = 1_000
        raw = raw[:-1]

    # Remove spaces used as thousands separator (e.g. "3 241")
    raw = raw.replace(" ", "")

    # Distinguish decimal comma (1,5) from thousands comma (1,500)
    # Rule: if comma is followed by exactly 3 digits and nothing else → thousands
    # otherwise → decimal separator
    if re.match(r"^\d+,\d{3}$", raw):
        raw = raw.replace(",", "")          # thousands: "1,500" → "1500"
    elif "," in raw:
        raw = raw.replace(",", ".")         # decimal:   "1,5"   → "1.5"

    # Same for period: period followed by exactly 3 digits → thousands separator
    if re.match(r"^\d+\.\d{3}$", raw):
        raw = raw.replace(".", "")          # "3.241" → "3241"

    try:
        return int(float(raw) * mul)
    except Exception:
        return 0


# ── Engagement extractor ──────────────────────────────────────────────────────

_ENG_PATTERNS = {
    "reactions": [
        r"([\d\s.,]+(?:\s*mil(?:lones?)?)?\s*[KMk]?)\s*(?:reacciones?|reactions?|me gusta|likes?)",
        r"([\d\s.,]+(?:\s*mil(?:lones?)?)?\s*[KMk]?)\s*(?:personas?\s+reaccionaron)",
    ],
    "comments": [
        r"([\d\s.,]+(?:\s*mil(?:lones?)?)?\s*[KMk]?)\s*(?:comentarios?|comments?)",
    ],
    "shares": [
        r"([\d\s.,]+(?:\s*mil(?:lones?)?)?\s*[KMk]?)\s*(?:veces?|compartidos?|shares?)",
        r"compartido\s+([\d\s.,]+(?:\s*mil(?:lones?)?)?\s*[KMk]?)\s*(?:veces?)?",
    ],
}


def extract_engagement(text: str) -> tuple[int, int, int]:
    """Return (reactions, comments, shares) — handles Spanish FB formats."""
    results = {}
    for key, patterns in _ENG_PATTERNS.items():
        val = 0
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = parse_engagement_number(m.group(1))
                if val > 0:
                    break
        results[key] = val
    return results["reactions"], results["comments"], results["shares"]


def extract_engagement_from_aria(aria_label: str) -> int:
    """Parse engagement from aria-label: '3,241 Me gusta' → 3241."""
    if not aria_label:
        return 0
    m = re.search(r"([\d\s.,]+(?:\s*mil)?)\s", aria_label)
    if m:
        return parse_engagement_number(m.group(1))
    return 0


def clean_url(href: str) -> str:
    if not href:
        return ""
    # story_fbid and pfbid in query string ARE the post ID — keep them
    if "story_fbid" in href:
        base = href.split("?")[0]
        m = re.search(r"story_fbid=([^&]+)", href)
        if m:
            return f"{base}?story_fbid={m.group(1)}"
        return base.rstrip("/")
    return href.split("?")[0].split("&")[0].rstrip("/")


# ── UI noise words to filter from innerText ───────────────────────────────────

_UI_NOISE = {
    "me gusta", "comentar", "compartir", "ver más", "seguir", "suscribir",
    "iniciar sesión", "registrarse", "like", "comment", "share", "subscribe",
    "sign in", "log in", "react", "reply", "see more", "traducir",
    "ocultar", "denunciar", "guardar", "etiquetas", "publicidad",
}


def clean_innertext(raw: str, min_line_len: int = 20) -> str:
    """
    Extract meaningful content from FB article innerText.
    Removes UI buttons, reaction counts, short nav lines.
    """
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if len(line) < min_line_len:
            continue
        lower = line.lower()
        if any(noise in lower for noise in _UI_NOISE):
            continue
        # Skip lines that are pure numbers or short combos (engagement counts)
        if re.match(r"^[\d\s.,KMkmil]+$", line):
            continue
        lines.append(line)
    return " ".join(lines[:20])  # cap at 20 lines to avoid noise
