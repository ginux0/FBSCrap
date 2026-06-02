"""
Dynamic DOCX intelligence report generator for FBSCRAP.

Secciones (idénticas al formato FBSCRAP_GVL_TOP30_LINKS.docx):
  1. Portada
  2. ¿Qué pasó realmente? — timeline auto-extraído de los posts
  3. TOP N tabla — hipervínculos clickeables
  4. Mapa de ataques — detección automática por análisis de texto
  5. Templates de respuesta — contra-narrativa generada
  6. CIB Bot Analysis — Comportamiento Inauténtico Coordinado (motor real)
  7. Footer
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import docx.opc.constants


# ── Palette ───────────────────────────────────────────────────────────────────
def _hex_to_rgb(hex_str: str) -> RGBColor:
    """Convert hex color string (e.g., 'ff4444') to RGBColor object."""
    h = hex_str.lstrip("#").lower()
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return RGBColor(r, g, b)

WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
RED_DARK = RGBColor(0xC0, 0x00, 0x00)
RED_MED  = RGBColor(0xFF, 0x33, 0x33)
ORANGE   = RGBColor(0xFF, 0x6B, 0x00)
YELLOW   = RGBColor(0xFF, 0xC0, 0x00)
GREEN    = RGBColor(0x00, 0xBB, 0x55)
TEAL     = RGBColor(0x00, 0xAA, 0xAA)
CYAN     = RGBColor(0x44, 0xCC, 0xFF)
GRAY     = RGBColor(0xC0, 0xC0, 0xC0)
PURPLE   = RGBColor(0xBB, 0x44, 0xFF)

_LABEL_META: dict[str, tuple[str, RGBColor, str]] = {
    "AGRESIVO": ("C00000", RED_MED,  "140000"),
    "NEGATIVO": ("8B3A00", ORANGE,   "0A0800"),
    "NEUTRAL":  ("1A2A4A", TEAL,     "0A0A16"),
    "POSITIVO": ("003A10", GREEN,    "001A06"),
}


# ── DOCX helpers ──────────────────────────────────────────────────────────────

def _bg(cell, h: str) -> None:
    tc = cell._tc
    pr = tc.get_or_add_tcPr()
    s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear")
    s.set(qn("w:color"), "auto")
    s.set(qn("w:fill"), h)
    pr.append(s)


def _sp(para, before: str = "0", after: str = "40") -> None:
    pPr = para._p.get_or_add_pPr()
    sp = OxmlElement("w:spacing")
    sp.set(qn("w:before"), before)
    sp.set(qn("w:after"), after)
    pPr.append(sp)


def _r(para, txt: str, bold: bool = False, italic: bool = False,
       color: RGBColor = WHITE, size: int = 9):
    run = para.add_run(txt)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = color
    run.font.size = Pt(size)
    run.font.name = "Consolas"
    return run


def _div(doc: Document, color: str = "C00000") -> None:
    p = doc.add_paragraph()
    _sp(p, "0", "10")
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), "8")
    b.set(qn("w:space"), "1")
    b.set(qn("w:color"), color)
    pBdr.append(b)
    pPr.append(pBdr)


def _h1(doc: Document, txt: str) -> None:
    p = doc.add_paragraph()
    _sp(p, "100", "10")
    _r(p, txt, bold=True, color=RED_DARK, size=13)
    _div(doc)


def _bar(v: float, w: int = 6) -> str:
    n = int(max(0.0, min(1.0, v)) * w)
    return "█" * n + "░" * (w - n)


def _priority_score(post: dict) -> tuple[int, str, RGBColor]:
    """
    0-100 composite priority score for intervention targeting.
    Combines: post text NEG/AGG (primary) + engagement (secondary) + comment attack layer.
    Returns (score, label, color).
    """
    neg = _neg(post)
    agg = _agg(post)
    eng = _eng(post)

    # Log-normalize engagement: 100eng≈0.5, 1K≈0.75, 10K≈1.0
    eng_norm = min(math.log10(max(eng, 1)) / 4.0, 1.0)

    # Base score from post text
    score = neg * 0.45 + agg * 0.25 + eng_norm * 0.30

    # Augment with comment attack data when available
    cs = post.get("comment_sentiment") or {}
    if cs:
        c_neg = float(cs.get("negative_score", 0))
        c_agg = float(cs.get("aggressive_score", 0))
        comment_attack = c_neg * 0.55 + c_agg * 0.45
        # Comment layer adds up to 20% boost when it CONFIRMS the attack
        score = score * 0.82 + comment_attack * 0.18

    score_int = min(int(score * 100), 99)
    if score_int >= 65:
        return score_int, "CRÍTICO", RED_MED
    elif score_int >= 40:
        return score_int, "ALTO",    ORANGE
    elif score_int >= 18:
        return score_int, "MEDIO",   YELLOW
    else:
        return score_int, "BAJO",    GRAY


def _comment_confirms_attack(post: dict) -> bool:
    """True when comment_sentiment is available AND labels as NEGATIVO or AGRESIVO."""
    cs = post.get("comment_sentiment") or {}
    return cs.get("label") in ("NEGATIVO", "AGRESIVO")


def _hyperlink(para, url: str, text: str,
               color: RGBColor = CYAN, size: int = 8, bold: bool = False) -> None:
    part = para.part
    r_id = part.relate_to(
        url,
        docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK,
        is_external=True,
    )
    hl = OxmlElement("w:hyperlink")
    hl.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")

    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)

    clr_el = OxmlElement("w:color")
    clr_el.set(qn("w:val"), str(color))
    rPr.append(clr_el)

    for tag in ("w:sz", "w:szCs"):
        sz_el = OxmlElement(tag)
        sz_el.set(qn("w:val"), str(size * 2))
        rPr.append(sz_el)

    if bold:
        rPr.append(OxmlElement("w:b"))

    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Consolas")
    rFonts.set(qn("w:hAnsi"), "Consolas")
    rPr.append(rFonts)

    run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(t)
    hl.append(run)
    para._p.append(hl)


# ── Post field extractors ─────────────────────────────────────────────────────

def _label(post: dict) -> str:
    sent = post.get("sentiment") or {}
    lbl = (sent.get("label") or "NEUTRAL").upper()
    return lbl if lbl in _LABEL_META else "NEUTRAL"


def _neg(post: dict) -> float:
    return float((post.get("sentiment") or {}).get("negative_score") or 0.0)


def _agg(post: dict) -> float:
    return float((post.get("sentiment") or {}).get("aggressive_score") or 0.0)


def _eng(post: dict) -> int:
    eng = post.get("engagement_total")
    if eng is None:
        eng = (int(post.get("reactions") or 0)
               + int(post.get("comments_count") or 0)
               + int(post.get("shares") or 0))
    return int(eng)


def _fecha(post: dict) -> str:
    ts = post.get("timestamp")
    if ts:
        try:
            return datetime.fromisoformat(ts).strftime("%d/%m")
        except Exception:
            pass
    raw = post.get("timestamp_raw", "")
    if raw and str(raw).isdigit():
        try:
            return datetime.fromtimestamp(int(raw)).strftime("%d/%m")
        except Exception:
            pass
    return "s/f"


def _title(post: dict) -> str:
    text = (post.get("text") or "").strip()
    if not text:
        return "(sin texto)"
    for sep in ("\n", ". ", " — ", " | "):
        idx = text.find(sep)
        if 0 < idx < 120:
            return text[:idx].strip()
    return text[:110].strip()


def _source_label(post: dict) -> str:
    src = (post.get("source") or post.get("source_handle") or "Desconocido").strip()
    url = post.get("url", "")
    star = "★" if any(x in url for x in ("pfbid", "/posts/", "/videos/", "/reel/")) else "☆"
    return f"{src[:22]} {star}"


# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE EXTRACTION ENGINES
# ══════════════════════════════════════════════════════════════════════════════

# ── Timeline extractor ────────────────────────────────────────────────────────

def _build_timeline(posts: list[dict], max_events: int = 8) -> list[tuple[str, str, str]]:
    """
    Returns list of (date_str, source, event_snippet) sorted oldest→newest.
    Deduplicates by title similarity.
    """
    dated = []
    for p in posts:
        ts = p.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                dated.append((dt, p))
            except Exception:
                pass

    dated.sort(key=lambda x: x[0])

    events: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for dt, post in dated:
        snip = _title(post)
        key = snip[:40].lower()
        if key in seen:
            continue
        seen.add(key)
        src = (post.get("source") or "Desconocido")[:30]
        events.append((dt.strftime("%d/%m/%Y"), src, snip[:100]))
        if len(events) >= max_events:
            break

    return events


# ── Attack pattern detector ───────────────────────────────────────────────────

# Each type: list of keyword groups (any match in the text = hit)
_ATK_TYPES: dict[str, dict] = {
    "TIPO A — ACUSACIÓN SIN CONTEXTO": {
        "keywords": ["corrupto", "corrupción", "corrupcion", "robo", "ladrón", "ladron",
                     "desvío", "desvio", "ilegal", "irregular", "malversación", "saqueo",
                     "abuso", "deshonesto", "fraude", "peculado"],
        "risk":     "ALTO",
        "attack":   "Acusación de corrupción sin marco temporal ni prueba directa",
        "counter":  (
            "Contextualizar: ¿CUÁNDO ocurrieron los hechos? ¿Por qué el caso "
            "se abrió AHORA y no antes? La cronología es el arma más poderosa. "
            "Exigir: fecha del acto, fecha de la denuncia, quién denunció y por qué en ese momento."
        ),
    },
    "TIPO B — ASOCIACIÓN CRIMINAL": {
        "keywords": ["narco", "cartel", "cártel", "crimen organizado", "criminal",
                     "cómplice", "nexo", "vínculo", "capo", "sicario", "plaza",
                     "protegido por", "cuida la"],
        "risk":     "ALTO",
        "attack":   "Asociación con el crimen organizado sin evidencia directa",
        "counter":  (
            "Invertir la narrativa: ¿El acusador tiene su expediente limpio? "
            "Documentar si quien lanza la acusación tiene señalamientos equivalentes o peores. "
            "Exigir fuentes: ¿DOJ, FGR, o solo 'dicen que dicen'?"
        ),
    },
    "TIPO C — VICTIMISMO/DISTRACCIÓN": {
        "keywords": ["víctima", "victima", "victimiza", "excusa", "pretexto", "cortina",
                     "distracción", "distraccion", "manipula", "engaña", "engana",
                     "show", "teatrito", "circo"],
        "risk":     "MEDIO",
        "attack":   "Descalificar la denuncia como victimismo o distracción mediática",
        "counter":  (
            "La denuncia fue hecha ante una INSTITUCIÓN FORMAL, no en redes sociales. "
            "Citar la declaración exacta documentada. Preguntar: "
            "¿denunciar con nombre completo ante el Congreso es 'victimizarse'?"
        ),
    },
    "TIPO D — ARGUMENTO JUDICIAL/LEGAL": {
        "keywords": ["desafuero", "scjn", "tribunal", "sentencia", "audiencia",
                     "proceso", "fgr", "fge", "vinculado a proceso", "auto de vinculación",
                     "juez", "fiscalía", "fiscalia", "ministerio público"],
        "risk":     "MEDIO",
        "attack":   "Uso de resoluciones judiciales sin distinguir forma vs. fondo",
        "counter":  (
            "Separar FORMA de FONDO: una resolución por extemporaneidad procesal "
            "NO es una declaración de culpabilidad. Señalar si existían órdenes "
            "de jueces federales que fueron ignoradas — eso es la historia real."
        ),
    },
    "TIPO E — INSULTO DIRECTO (patrón bot)": {
        "keywords": ["ratero", "mentiroso", "traidor", "hipócrita", "hipocrìta",
                     "sinvergüenza", "sinverguenza", "mafioso", "delincuente",
                     "corrupto", "imbécil", "imbecil", "idiota"],
        "risk":     "ALTO (bot)",
        "attack":   "Insultos directos sin argumento — perfil bot probable",
        "counter":  (
            "[NO RESPONDER] Documentar: screenshot + hora exacta. "
            "Si el mismo texto aparece en múltiples cuentas en <15 min: "
            "reportar en Facebook → '...' → Reportar → 'Comportamiento inauténtico'. "
            "En lugar de responder: publicar los hechos documentados sin mencionar el ataque."
        ),
    },
}


def _detect_attacks(posts: list[dict]) -> list[dict]:
    """
    Returns attack records sorted by frequency descending.
    Each record: type, risk, count, pct, example, attack_desc, counter_text
    """
    hits: dict[str, list[str]] = {k: [] for k in _ATK_TYPES}

    for post in posts:
        text = (post.get("text") or "").lower()
        if not text:
            continue
        for atk_type, meta in _ATK_TYPES.items():
            for kw in meta["keywords"]:
                if kw in text:
                    snip = _title(post)[:80]
                    if snip not in hits[atk_type]:
                        hits[atk_type].append(snip)
                    break

    total = max(len(posts), 1)
    result = []
    for atk_type, examples in sorted(hits.items(), key=lambda x: -len(x[1])):
        cnt = len(examples)
        meta = _ATK_TYPES[atk_type]
        result.append({
            "type":    atk_type,
            "risk":    meta["risk"],
            "count":   cnt,
            "pct":     round(cnt / total * 100),
            "example": examples[0] if examples else "—",
            "attack":  meta["attack"],
            "counter": meta["counter"],
        })
    return result


# ── Response template generator ───────────────────────────────────────────────

_TEMPLATE_LIBRARY: dict[str, tuple[str, str]] = {
    "TIPO A — ACUSACIÓN SIN CONTEXTO": (
        "Cuando dicen: 'Es un corrupto / robó / actuó ilegalmente'",
        "Pregunta clave: ¿CUÁNDO ocurrió? ¿Cuándo se abrió el caso y por qué en ese momento?\n"
        "Si hay 3-4 años de silencio antes de la denuncia, la cronología lo explica todo.\n"
        "Exige contexto: fecha del acto, fecha de la denuncia, identidad de quien denuncia.",
    ),
    "TIPO B — ASOCIACIÓN CRIMINAL": (
        "Cuando dicen: 'Tiene nexos con el crimen / protegido por el narco'",
        "Pregunta: ¿Cuál es la fuente? ¿DOJ, FGR, o solo declaraciones del gobierno rival?\n"
        "Si quien acusa está él mismo señalado por organismos internacionales — eso es la historia real.\n"
        "La DEA y el SDNY son fuentes verificables. Medios alineados a un gobierno, no.",
    ),
    "TIPO C — VICTIMISMO/DISTRACCIÓN": (
        "Cuando dicen: 'Se victimiza / es una distracción / todo es teatro'",
        "La denuncia fue ante una INSTITUCIÓN FORMAL con nombre, apellido y cita textual documentada.\n"
        "Eso no es redes sociales. Eso es un acto jurídico ante el Congreso del Estado.\n"
        "¿Denunciar formalmente es 'victimizarse'? ¿O temen que la cita exacta sea verificada?",
    ),
    "TIPO D — ARGUMENTO JUDICIAL/LEGAL": (
        "Cuando dicen: 'El tribunal / SCJN / juez ya resolvió en su contra'",
        "Separar FORMA de FONDO: resolver por extemporaneidad procesal NO es declaración de culpabilidad.\n"
        "¿Hubo órdenes de jueces federales que fueron ignoradas? Eso es la verdadera historia.\n"
        "El proceso judicial sigue abierto — afirmar que 'ya está resuelto' es desinformación.",
    ),
    "TIPO E — INSULTO DIRECTO (patrón bot)": (
        "Cuando insultan sin argumento (patrón bot probable)",
        "[NO RESPONDER AL INSULTO]\n"
        "1. Screenshot + hora exacta (evidencia de coordinación).\n"
        "2. Si el mismo texto aparece en varias cuentas en <15 min: reportar como 'comportamiento inauténtico'.\n"
        "3. En tu lugar: publicar UNA pieza de los hechos documentados. Sin mencionar el ataque.\n"
        "4. Los insultos sin argumento confirman que no tienen contrarrelato factual.",
    ),
    "OFENSIVO — TOMAR LA INICIATIVA": (
        "Argumento ofensivo: no esperar el ataque, publicar primero",
        "Publicar la cronología completa antes de que la narrativa adversaria la defina:\n"
        "→ ¿Cuándo ocurrieron los hechos? → ¿Cuándo se denunciaron y por qué entonces?\n"
        "→ ¿Quién tiene señalamientos de organismos internacionales reales?\n"
        "La ofensiva narrativa es más efectiva que la defensa. Los hechos documentados ganan.",
    ),
}


def _build_templates(attack_records: list[dict]) -> list[tuple[str, str]]:
    """
    Returns (trigger, response) pairs, prioritizing detected attack types,
    always appending the offensive template at the end.
    """
    detected_types = {r["type"] for r in attack_records if r["count"] > 0}
    templates: list[tuple[str, str]] = []
    seen: set[str] = set()

    for atk_type in _ATK_TYPES:
        if atk_type in detected_types and atk_type in _TEMPLATE_LIBRARY:
            trigger, resp = _TEMPLATE_LIBRARY[atk_type]
            templates.append((trigger, resp))
            seen.add(atk_type)

    for atk_type, (trigger, resp) in _TEMPLATE_LIBRARY.items():
        if atk_type not in seen:
            templates.append((trigger, resp))

    return templates[:6]


# ══════════════════════════════════════════════════════════════════════════════
# GLOSSARY DEFAULTS — overridable via cfg["glossary"]
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULT_GLOSSARY_ABBR = {
    "CIB":           "Comportamiento Inorgánico Coordinado — actividad falsa coordinada en redes sociales",
    "BOT":           "Robot automatizado — cuenta que opera sin intervención humana real",
    "TROLL":         "Cuenta humana usada deliberadamente para atacar o manipular la opinión pública",
    "HCS":           "Human Confidence Score — índice de confianza de humanidad (0-99, mayor = más humano)",
    "CPH":           "Comentarios Por Hora — velocidad de publicación del actor",
    "TF-IDF":        "Term Frequency-Inverse Document Frequency — técnica estadística de análisis de texto",
    "IDOR":          "Insecure Direct Object Reference — vulnerabilidad de acceso no autorizado a datos",
    "JWT":           "JSON Web Token — token de autenticación digital",
    "CIB Score":     "Puntuación unificada de Comportamiento Inorgánico Coordinado (0-100)",
    "E1–E8":         "Motores de análisis forense (Identity, ReplyChain, Contagion, Engagement, DarkAmp, CrossCampaign, BotFarmShift, NarrativeMutation)",
    "S1–S8":         "Señales TrollHunter: S1=Nombre, S2=Página, S3=MultiPágina, S4=Agresión, S5=Cruzado, S6=Velocidad, S7=Coordinación, S8=Perfil",
    "SHA-256":       "Algoritmo criptográfico para verificar la integridad de los datos (huella digital del documento)",
    "DOM":           "Document Object Model — estructura interna de una página web",
    "GraphQL":       "Lenguaje de consulta para APIs web, usado por Facebook",
    "Jaccard":       "Medida matemática de similitud entre conjuntos (0=ninguna similitud, 1=idénticos)",
    "TrollHunter":   "Motor de detección de perfiles bot/troll (NULLSEC FBSCRAP)",
    "DEFCON":        "Conferencia internacional de seguridad informática de élite (Las Vegas)",
    "NLP":           "Natural Language Processing — procesamiento computacional de texto humano",
    "Baseline":      "Valor de referencia promedio para comparar comportamiento anómalo",
}

_DEFAULT_GLOSSARY_TERMS = {
    "Comportamiento Inorgánico Coordinado (CIB)": (
        "Se refiere a la actividad en redes sociales donde múltiples cuentas actúan "
        "de forma coordinada y artificial para manipular la percepción pública. "
        "Las cuentas pueden ser bots (automatizadas) o trolls (humanos contratados). "
        "La coordinación se detecta cuando la sincronización, los mensajes o los patrones "
        "son imposibles de explicar como comportamiento espontáneo de personas reales."
    ),
    "Bot (robot automatizado)": (
        "Una cuenta de redes sociales controlada por software, no por una persona real. "
        "Los bots pueden publicar comentarios, dar 'me gusta' y compartir contenido "
        "de forma automática, a velocidades imposibles para humanos. "
        "Se usan para amplificar narrativas falsas, atacar figuras públicas "
        "o crear la ilusión de apoyo popular inexistente."
    ),
    "Granja de bots (Bot Farm)": (
        "Una red de cuentas falsas controladas por un operador o empresa, "
        "usadas para ejecutar campañas de desinformación coordinadas. "
        "Las granjas de bots pueden tener desde decenas hasta millones de cuentas "
        "y son alquiladas o vendidas como servicios en mercados clandestinos."
    ),
    "Ola de ataque coordinado": (
        "Un evento donde múltiples cuentas publican comentarios negativos "
        "de forma simultánea (con diferencia de segundos) sobre el mismo contenido. "
        "Esta precisión temporal es físicamente imposible para humanos actuando "
        "de forma independiente — requiere automatización o coordinación directa."
    ),
    "Amplificación oscura (Dark Amplification)": (
        "Técnica donde una publicación recibe miles de reacciones artificiales "
        "en poco tiempo para hacer que el algoritmo de la plataforma la muestre "
        "a más usuarios, creando percepción falsa de relevancia o tendencia."
    ),
    "Mutación de narrativa": (
        "Cambio coordinado en el vocabulario de ataque durante una campaña. "
        "El operador modifica el mensaje central ('corrupto' → 'narco') "
        "para evadir filtros de contenido o adaptar el ataque a nuevos eventos. "
        "Las mutaciones coordinadas confirman control centralizado de la operación."
    ),
    "Análisis estilométrico": (
        "Técnica forense que identifica el 'estilo de escritura' único de cada persona: "
        "uso de emojis, mayúsculas, puntuación, longitud de oraciones, vocabulario preferido. "
        "Cuando dos cuentas diferentes tienen el mismo estilo de escritura, "
        "es evidencia de que son operadas por el mismo individuo."
    ),
    "Cadena de custodia (Chain of Custody)": (
        "Registro cronológico e íntegro de la evidencia digital, desde su recolección "
        "hasta su presentación en un proceso legal. Cada pieza de evidencia tiene "
        "un hash SHA-256 que garantiza que no fue modificada. "
        "Permite que la evidencia sea admisible en procedimientos judiciales."
    ),
    "Contagio emocional": (
        "Fenómeno donde la irrupción masiva de comentarios negativos de bots "
        "cambia el tono general de la discusión, 'contagiando' de negatividad "
        "incluso a usuarios reales que veían el contenido antes de la llegada "
        "de los bots. El sistema mide este cambio comparando el sentimiento "
        "antes y después de la llegada de los actores sospechosos."
    ),
    "Secuestro de hilo (Reply Hijacking)": (
        "Táctica donde múltiples bots responden masivamente a comentarios "
        "positivos de ciudadanos reales, enterrándolos bajo una avalancha "
        "de respuestas negativas. El objetivo es que los comentarios de apoyo "
        "queden invisibles para otros usuarios."
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def generate_docx_report(
    posts: list[dict],
    output_path: Path,
    query: str = "",
    top_n: int = 30,
    days: int = 7,
    cfg: dict | None = None,
) -> None:
    """
    Build a full DOCX intelligence report from live fbscrap data.
    Identical visual format to FBSCRAP_GVL_TOP30_LINKS.docx + bot analysis.
    """
    top       = posts[:top_n]
    now       = datetime.now()
    date_lbl  = now.strftime("%Y-%m-%d %H:%M")
    total     = len(posts)

    # Pre-compute analytics
    neg_count  = sum(1 for p in posts if _label(p) in ("NEGATIVO", "AGRESIVO"))
    agg_count  = sum(1 for p in posts if _label(p) == "AGRESIVO")
    neg_pct    = round(neg_count / max(total, 1) * 100)
    agg_pct    = round(agg_count / max(total, 1) * 100)
    sources    = sorted({(p.get("source") or "?") for p in top})
    src_label  = ", ".join(sources[:6]) + (" +más" if len(sources) > 6 else "")
    title_up   = (query or "BÚSQUEDA FACEBOOK").upper()

    # Priority distribution across top posts
    prio_scores  = [_priority_score(p) for p in top]
    critico_cnt  = sum(1 for s, l, _ in prio_scores if l == "CRÍTICO")
    alto_cnt     = sum(1 for s, l, _ in prio_scores if l == "ALTO")
    comment_layer_cnt = sum(1 for p in top if p.get("comment_sentiment"))

    timeline       = _build_timeline(posts)
    attack_records = _detect_attacks(posts)
    templates      = _build_templates(attack_records)

    from engines.bot_detector import analyze as _bot_analyze
    from engines.comment_bot_detector import analyze_comments as _comment_analyze
    from engines.cib_graph import CIBGraphEngine
    from engines.hcs_engine import HCSEngine
    from engines.ownership_engine import OwnershipEngine
    from engines.temporal_engine import TemporalEngine
    from engines.stylometry_engine import StylometryEngine
    from engines.sentiment_delta_engine import SentimentDeltaEngine
    from engines.first_mover_engine import FirstMoverEngine
    from engines.semantic_engine import SemanticEngine
    from engines.legal_export_engine import LegalExportEngine
    from engines.lifecycle_engine import LifecycleEngine
    from engines.narrative_injection_engine import NarrativeInjectionEngine
    from engines.influence_topology_engine import InfluenceTopologyEngine
    from engines.hashtag_engine import HashtagWeaponizationEngine
    from engines.velocity_engine import AccountVelocityEngine
    from engines.narrative_seeding_engine import NarrativeSeedingEngine
    from engines.time_correlation_engine import TimeCorrelationEngine
    from engines.bot_attribution_engine import BotAttributionEngine
    from engines.troll_hunter_engine import TrollHunterEngine
    from engines.engagement_anomaly_engine import EngagementAnomalyEngine
    from engines.emotional_contagion_engine import EmotionalContagionEngine
    from engines.reply_chain_engine import ReplyChainHijackEngine
    from engines.cross_campaign_engine import CrossCampaignPersistenceEngine
    from engines.dark_amplification_engine import DarkAmplificationEngine
    from engines.bot_farm_shift_engine import BotFarmShiftEngine
    from engines.identity_persistence_engine import IdentityPersistenceEngine
    from engines.narrative_mutation_engine import NarrativeMutationEngine
    from engines.html_reporter import generate_html_dashboard

    # Collect all per-post comment lists for engines that need them
    all_comment_results: list[dict] = [
        {"url": p.get("url", ""), "comments": p.get("comments", [])}
        for p in posts
        if p.get("comments")
    ]

    bot_report       = _bot_analyze(posts, cfg=cfg)
    comment_report   = _comment_analyze(posts, cfg=cfg)
    cib_result       = CIBGraphEngine(
        posts, comment_report.top_bot_suspects, output_path.parent, cfg=cfg
    ).build()
    hcs_report       = HCSEngine(
        posts, comment_report.top_bot_suspects, cib_result, cfg=cfg
    ).score_all()
    ownership_report  = OwnershipEngine(
        posts, comment_report.top_bot_suspects, cib_result, cfg=cfg
    ).analyze()
    temporal_report  = TemporalEngine(cfg=cfg).analyze(all_comment_results)
    stylo_report     = StylometryEngine(cfg=cfg).analyze(all_comment_results)

    bot_actor_set    = {s.author for s in (comment_report.top_bot_suspects or [])}
    sentiment_report = SentimentDeltaEngine(cfg=cfg).analyze(all_comment_results)
    first_mover_report = FirstMoverEngine(cfg=cfg).analyze(all_comment_results)
    semantic_report  = SemanticEngine(cfg=cfg).analyze(all_comment_results, bot_actor_set)
    lifecycle_report  = LifecycleEngine(cfg=cfg).analyze(all_comment_results, posts=posts)
    injection_report  = NarrativeInjectionEngine(cfg=cfg).analyze(all_comment_results, posts=posts)
    topology_report   = InfluenceTopologyEngine(cfg=cfg).analyze(cib_result)
    hashtag_report    = HashtagWeaponizationEngine(cfg=cfg).analyze(all_comment_results)
    velocity_report   = AccountVelocityEngine(cfg=cfg).analyze(all_comment_results)
    seeding_report    = NarrativeSeedingEngine(cfg=cfg).analyze(all_comment_results)
    correlation_report = TimeCorrelationEngine(cfg=cfg).analyze(all_comment_results)
    bot_actors_set    = {s.author for s in (comment_report.top_bot_suspects or [])
                         if getattr(s, "bot_score", 0) >= 60}
    attribution_report = BotAttributionEngine(cfg=cfg).analyze(
        all_comment_results, bot_actors=bot_actors_set or None
    )
    # TrollHunter: pass wave actors + copy-paste actors for coordination signal
    wave_actors_set   = {a for w in (temporal_report.waves or [])
                         for a in getattr(w, "actors", [])}
    cpaste_actors_set = {a for g in (stylo_report.copy_paste_groups or [])
                         for a in getattr(g, "actors", [])}
    troll_report      = TrollHunterEngine(cfg=cfg).analyze(
        all_comment_results,
        wave_actors=wave_actors_set,
        copy_paste_actors=cpaste_actors_set,
    )
    engagement_report = EngagementAnomalyEngine(cfg=cfg).analyze(posts)
    contagion_report  = EmotionalContagionEngine(cfg=cfg).analyze(
        all_comment_results,
        temporal_report=temporal_report,
        posts=posts,
    )
    # E2: bot actors from TrollHunter + HCS to improve reply detection
    known_bots = {p.actor for p in troll_report.profiles
                  if p.bot_risk_score >= 60} if troll_report else set()
    reply_report = ReplyChainHijackEngine(cfg=cfg).analyze(
        all_comment_results,
        bot_actors=known_bots,
        posts=posts,
    )
    # E6: register session actors → query cross-campaign patterns
    _cc_engine = CrossCampaignPersistenceEngine(cfg=cfg)
    _cc_engine.register_session(query or "unknown", troll_report)
    cross_campaign_report = _cc_engine.analyze(current_campaign=query)
    # E1: register fingerprints → cross-match identities
    _id_engine = IdentityPersistenceEngine(cfg=cfg)
    _id_engine.register_fingerprints(
        query or "unknown", all_comment_results,
        troll_report=troll_report,
    )
    identity_report = _id_engine.analyze(current_campaign=query or "unknown")

    # E8: narrative mutation tracking
    mutation_report = NarrativeMutationEngine(cfg=cfg).analyze(
        all_comment_results,
        injection_report=injection_report,
    )

    dark_amp_report = DarkAmplificationEngine(cfg=cfg).analyze(
        posts, scraped_results=all_comment_results,
    )
    known_bots_e7 = {p.actor for p in troll_report.profiles
                     if p.bot_risk_score >= 60} if troll_report else set()
    shift_report = BotFarmShiftEngine(cfg=cfg).analyze(
        all_comment_results,
        bot_actors=known_bots_e7,
        troll_report=troll_report,
    )

    # ── N8: Legal Evidence Export — runs LAST so ALL engine reports are available ──
    legal_report = LegalExportEngine(cfg=cfg).export(
        query               = query,
        scraped_posts       = posts,
        bot_report          = comment_report,
        temporal_report     = temporal_report,
        first_mover_report  = first_mover_report,
        sentiment_report    = sentiment_report,
        troll_report        = troll_report,
        engagement_report   = engagement_report,
        contagion_report    = contagion_report,
        reply_report        = reply_report,
        cross_campaign_report = cross_campaign_report,
        identity_report     = identity_report,
        mutation_report     = mutation_report,
        shift_report        = shift_report,
        dark_amp_report     = dark_amp_report,
        cib_result          = cib_result,
        hcs_report          = hcs_report,
        comment_report      = comment_report,
        output_dir          = output_path.parent,
    )

    # ── Multi-Source cross-page CIB detection ────────────────────────────────
    from engines.multi_source_engine import MultiSourceEngine
    multi_source_report = MultiSourceEngine(cfg=cfg).analyze(posts, troll_report=troll_report)
    if len(multi_source_report.sources) >= 2:
        print(f"  [MULTI-SRC] {len(multi_source_report.sources)} sources · "
              f"cross_actors={len(multi_source_report.cross_page_actors)} · "
              f"confirmed={len(multi_source_report.confirmed_cross_bots)} · "
              f"score={multi_source_report.cross_page_score}/100")

    # ── Unified CIB Confidence Score — computed from ALL engines ─────────────
    from engines.cib_score_engine import CIBScoreEngine
    cib_score_report = CIBScoreEngine(cfg=cfg).compute(
        troll_report          = troll_report,
        cib_result            = cib_result,
        temporal_report       = temporal_report,
        mutation_report       = mutation_report,
        dark_amp_report       = dark_amp_report,
        engagement_report     = engagement_report,
        contagion_report      = contagion_report,
        reply_report          = reply_report,
        shift_report          = shift_report,
        cross_campaign_report = cross_campaign_report,
        identity_report       = identity_report,
    )
    print(f"  [CIB SCORE] {cib_score_report.overall_score}/100 — "
          f"{cib_score_report.confidence_label} — "
          f"{cib_score_report.engines_present} engines active")

    # ── Confidence Chain Engine ───────────────────────────────────────────────
    from engines.confidence_chain_engine import ConfidenceChainEngine
    chain_report = ConfidenceChainEngine(cfg=cfg).analyze(
        troll_report          = troll_report,
        temporal_report       = temporal_report,
        stylo_report          = stylo_report,
        hcs_report            = hcs_report,
        velocity_report       = velocity_report,
        cross_campaign_report = cross_campaign_report,
        identity_report       = identity_report,
        reply_report          = reply_report,
        shift_report          = shift_report,
    )
    print(f"  [CHAINS] {chain_report.total_actors} actor chains · "
          f"confirmed={chain_report.confirmed_chains} · "
          f"high_risk={chain_report.high_risk_chains}")

    print(f"  [CIB GRAPH] {cib_result.total_actors} actors · "
          f"{cib_result.total_edges} edges · "
          f"{len(cib_result.clusters)} clusters · "
          f"coord={cib_result.coordination_score}/100")
    print(f"  [HCS] {hcs_report.total_actors} actors · "
          f"bots={len(hcs_report.confirmed_bots)} · "
          f"high_risk={len(hcs_report.high_risk)} · "
          f"mean={hcs_report.mean_hcs}")
    print(f"  [OWNERSHIP] {ownership_report.total_attack_pages} attack pages · "
          f"{ownership_report.total_operators} operators")
    print(f"  [TEMPORAL] {temporal_report.timestamped_events} events · "
          f"{len(temporal_report.waves)} waves · "
          f"score={temporal_report.overall_score}/100")
    print(f"  [STYLOMETRY] {len(stylo_report.actor_styles)} actors · "
          f"bot_style={len(stylo_report.bot_style_actors)} · "
          f"clusters={len(stylo_report.clusters)} · "
          f"copy_paste={len(stylo_report.copy_paste_groups)}")
    seeded_count = sum(1 for d in sentiment_report.post_deltas if d.manipulation_label == "SEEDED")
    print(f"  [SENTIMENT] {len(sentiment_report.post_deltas)} posts analyzed · "
          f"seeded={seeded_count} · "
          f"score={sentiment_report.manipulation_score}/100")
    print(f"  [FIRST MOVER] {len(first_mover_report.seed_accounts)} seed accounts · "
          f"teams={len(first_mover_report.seeding_teams)} · "
          f"score={first_mover_report.overall_score}/100")
    print(f"  [SEMANTIC] {semantic_report.total_comments} comments · "
          f"clusters={len(semantic_report.clusters)} · "
          f"bot_dominated={semantic_report.bot_dominated_count} · "
          f"score={semantic_report.narrative_score}/100")
    print(f"  [LEGAL] {legal_report.manifest.total_items} evidence items · "
          f"case={legal_report.manifest.case_id}")
    print(f"  [LIFECYCLE] {lifecycle_report.total_actors} actors · "
          f"sleepers={len(lifecycle_report.sleepers)} · "
          f"bursters={len(lifecycle_report.bursters)} · "
          f"cells={len(lifecycle_report.sleeper_cells)} · "
          f"score={lifecycle_report.anomaly_score}/100")
    print(f"  [NARR INJECT] {injection_report.total_attack_comments} attack comments · "
          f"narratives={injection_report.total_narratives} · "
          f"score={injection_report.injection_score}/100")
    print(f"  [TOPOLOGY] {topology_report.total_actors} actors · "
          f"gini={topology_report.pagerank_gini:.3f} · "
          f"commands={len(topology_report.command_chain)} · "
          f"score={topology_report.influence_score}/100")
    print(f"  [HASHTAG] {hashtag_report.total_hashtags} hashtags · "
          f"weaponized={len(hashtag_report.weaponized_hashtags)} · "
          f"score={hashtag_report.weaponization_score}/100")
    print(f"  [VELOCITY] {velocity_report.total_actors} actors profiled · "
          f"bot_velocity={len(velocity_report.bot_velocity_actors)} · "
          f"max_cph={velocity_report.max_cph} · "
          f"score={velocity_report.velocity_score}/100")
    print(f"  [SEEDING] {seeding_report.total_seeded} seeded narrative(s) · "
          f"cross_post_actors={len(seeding_report.cross_post_actors)} · "
          f"score={seeding_report.propagation_score}/100")
    print(f"  [CORRELATION] {correlation_report.total_pairs} pairs · "
          f"high={sum(1 for p in correlation_report.top_pairs if p.label == 'HIGH')} · "
          f"max_jaccard={correlation_report.max_jaccard:.3f} · "
          f"score={correlation_report.correlation_score}/100")
    print(f"  [BOT ATTR] {attribution_report.total_operators} operator(s) · "
          f"bots={attribution_report.total_bots} · "
          f"edges={attribution_report.bipartite_edges} · "
          f"score={attribution_report.attribution_score}/100")
    print(f"  [TROLL HUNTER] {troll_report.total_analyzed} actors · "
          f"confirmed={len(troll_report.confirmed_bots)} · "
          f"high_risk={len(troll_report.high_risk)} · "
          f"foreign_names={len(troll_report.foreign_names)} · "
          f"page_ops={len(troll_report.page_operators)} · "
          f"score={troll_report.bot_risk_score}/100")
    print(f"  [ENGAGEMENT] {engagement_report.total_analyzed} posts · "
          f"bot_boosted={len(engagement_report.bot_boosted)} · "
          f"suspicious={len(engagement_report.suspicious)} · "
          f"ghost={len(engagement_report.ghost_posts)} · "
          f"baseline={engagement_report.baseline_ratio:.1f}x · "
          f"score={engagement_report.anomaly_score}/100")
    print(f"  [CONTAGION] {len(contagion_report.posts)} posts · "
          f"affected={contagion_report.affected_posts} · "
          f"direction={contagion_report.shift_direction} · "
          f"score={contagion_report.contagion_score}/100")
    print(f"  [IDENTITY] {identity_report.total_fingerprinted} actors fingerprinted · "
          f"confirmed_morphs={len(identity_report.confirmed_morphs)} · "
          f"probable_morphs={len(identity_report.probable_morphs)} · "
          f"unique_ops={identity_report.unique_operators} · "
          f"score={identity_report.persistence_score}/100")
    print(f"  [MUTATION] {len(mutation_report.mutations)} mutations · "
          f"pivot={mutation_report.pivot_events} · "
          f"expansion={mutation_report.expansion_events} · "
          f"injection={mutation_report.injection_events} · "
          f"score={mutation_report.mutation_score}/100")
    print(f"  [DARK AMP] {dark_amp_report.total_analyzed} posts · "
          f"dark_amp={len(dark_amp_report.dark_amplified)} · "
          f"suspicious={len(dark_amp_report.suspicious)} · "
          f"baseline={dark_amp_report.baseline_velocity:.0f}eng/h · "
          f"score={dark_amp_report.amp_score}/100")
    print(f"  [SHIFT DET] {len(shift_report.cohorts)} windows · "
          f"shifts={shift_report.confirmed_shifts} · "
          f"rotated={shift_report.total_rotated} · "
          f"score={shift_report.shift_score}/100")
    print(f"  [REPLY CHAIN] {len(reply_report.hijacked_posts)} hijacked · "
          f"targeted={reply_report.total_targeted} organic comments · "
          f"career_hijackers={len(reply_report.career_hijackers)} · "
          f"score={reply_report.hijack_score}/100")
    print(f"  [CROSS-CAMPAIGN] {cross_campaign_report.total_tracked} actors tracked · "
          f"campaigns={cross_campaign_report.campaigns_count} · "
          f"professional={len(cross_campaign_report.professional)} · "
          f"persistent={len(cross_campaign_report.persistent)} · "
          f"score={cross_campaign_report.persistence_score}/100")

    # Generate HTML dashboard alongside DOCX
    html_path = output_path.with_suffix(".html")
    generate_html_dashboard(
        posts=posts, output_path=html_path, query=query,
        comment_report=comment_report, bot_report=bot_report,
        cib_result=cib_result, hcs_report=hcs_report,
        ownership_report=ownership_report,
        temporal_report=temporal_report,
        stylo_report=stylo_report,
        sentiment_report=sentiment_report,
        first_mover_report=first_mover_report,
        semantic_report=semantic_report,
        legal_report=legal_report,
        lifecycle_report=lifecycle_report,
        injection_report=injection_report,
        topology_report=topology_report,
        hashtag_report=hashtag_report,
        velocity_report=velocity_report,
        seeding_report=seeding_report,
        correlation_report=correlation_report,
        attribution_report=attribution_report,
        troll_report=troll_report,
        engagement_report=engagement_report,
        contagion_report=contagion_report,
        reply_report=reply_report,
        cross_campaign_report=cross_campaign_report,
        dark_amp_report=dark_amp_report,
        shift_report=shift_report,
        identity_report=identity_report,
        mutation_report=mutation_report,
        cib_score_report=cib_score_report,
        chain_report=chain_report,
        multi_source_report=multi_source_report,
        cfg=cfg,
    )

    # ── Document setup ────────────────────────────────────────────────────────
    doc = Document()
    sec = doc.sections[0]
    sec.page_width    = Inches(11)
    sec.page_height   = Inches(8.5)
    sec.left_margin   = Inches(0.6)
    sec.right_margin  = Inches(0.6)
    sec.top_margin    = Inches(0.5)
    sec.bottom_margin = Inches(0.5)
    doc.styles["Normal"].font.name = "Consolas"
    doc.styles["Normal"].font.size = Pt(9)

    # ── SECCIÓN 1: PORTADA ────────────────────────────────────────────────────
    cv_tbl = doc.add_table(rows=1, cols=1)
    cv_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cv = cv_tbl.cell(0, 0)
    _bg(cv, "080808")

    for txt, sz, clr in [
        ("◈ NULLSEC RED TEAM  ·  Social Media Threat Intelligence  ·  OSINT", 8,  "C00000"),
        ("",                                                                    4,  "FFFFFF"),
        (f"ANÁLISIS DE INTELIGENCIA — {title_up}",                             20, "FFFFFF"),
        (f"TOP {top_n} NOTAS  ·  {neg_pct}% NEGATIVO / {agg_pct}% AGRESIVO"
         f"  ·  {total} POSTS TOTALES",                                        11, "FF3333"),
        ("",                                                                    4,  "FFFFFF"),
        (f"FUENTES: {src_label}",                                               9,  "FF6B00"),
        (
            f"PRIO CRÍTICO: {critico_cnt}  ·  ALTO: {alto_cnt}"
            f"  ·  BOTS COMENTS: {comment_report.bot_confirmed_pct}% BOT"
            f"  ·  CIB: {bot_report.cib_cluster_count} clusters"
            f"  ·  ★ = comentarios confirman ataque ({comment_layer_cnt} posts)"
            if comment_report.has_data else
            f"PRIO CRÍTICO: {critico_cnt}  ·  ALTO: {alto_cnt}"
            f"  ·  CIB: {bot_report.cib_cluster_count} clusters | {bot_report.bot_confirmed_pct}% CONFIRMADO"
            f"  ·  Agrega --comments-on-top {top_n} para capa de comentarios",
            9, "FF6B00"
        ),
        ("",                                                                    4,  "FFFFFF"),
        (f"Generado: {date_lbl}  ·  USO INTERNO  ·  CONFIDENCIAL",            7,  "555555"),
    ]:
        p = cv.add_paragraph()
        _sp(p)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(txt)
        r.bold = True
        r.font.name = "Consolas"
        r.font.size = Pt(sz)
        r.font.color.rgb = RGBColor(
            int(clr[0:2], 16), int(clr[2:4], 16), int(clr[4:6], 16)
        )
    doc.add_paragraph()

    # ── SECCIÓN 2: ¿QUÉ PASÓ REALMENTE? ─────────────────────────────────────
    _h1(doc, "¿QUÉ PASÓ REALMENTE?  —  CRONOLOGÍA AUTO-EXTRAÍDA DE LOS POSTS")

    ctx_tbl = doc.add_table(rows=1, cols=1)
    ctx = ctx_tbl.cell(0, 0)
    _bg(ctx, "0D0800")
    p = ctx.add_paragraph()
    _sp(p)
    _r(p, "CRONOLOGÍA DETECTADA EN MEDIOS — POSTS MÁS RELEVANTES:\n\n",
       bold=True, color=YELLOW, size=10)

    if timeline:
        for date_str, src, snip in timeline:
            _r(p, f"  {date_str}  [{src}]\n", bold=True, color=ORANGE, size=9)
            _r(p, f"  → {snip}\n\n", color=GRAY, size=9)
    else:
        _r(p, "  No se detectaron posts con timestamp válido en la ventana analizada.\n",
           color=GRAY, size=9)

    # Stats block
    _r(p, "\n", color=WHITE, size=6)
    _r(p, f"ESTADÍSTICAS DE SENTIMIENTO:\n", bold=True, color=YELLOW, size=9)
    lbl_colors = {"AGRESIVO": RED_MED, "NEGATIVO": ORANGE,
                  "NEUTRAL": GRAY, "POSITIVO": GREEN}
    for lbl, clr in lbl_colors.items():
        cnt = sum(1 for p2 in posts if _label(p2) == lbl)
        pct = round(cnt / max(total, 1) * 100)
        bar = _bar(cnt / max(total, 1), 18)
        _r(p, f"  {lbl:<10}  {bar}  {cnt:4d}  ({pct:3d}%)\n", color=clr, size=9)

    doc.add_paragraph()

    # ── SECCIÓN 3: TOP N TABLA ────────────────────────────────────────────────
    _h1(doc, f"TOP {top_n} — LINKS DE FACEBOOK  (CLICK EN EL TITULAR → VA DIRECTO AL POST)")

    leg = doc.add_paragraph()
    _sp(leg)
    _r(leg, "  ★ en FUENTE = Link DIRECTO al post (pfbid scrapeado)  ",
       bold=True, color=CYAN, size=9)
    _r(leg, "  ☆ en FUENTE = Página del medio (busca el post reciente)\n",
       bold=True, color=YELLOW, size=9)
    _r(leg, "  ★ en LBL = comentarios de FB también confirman narrativa de ataque  ",
       bold=True, color=RED_MED, size=9)
    _r(leg, "  PRIO = score 0-99 (NEG×45% + AGG×25% + ENG×30% + capa comentarios)\n",
       bold=True, color=ORANGE, size=9)
    _r(leg, "  PRIO >= 65 = CRÍTICO (rojo)  ·  >= 40 = ALTO (naranja)  ·  >= 18 = MEDIO (amarillo)",
       italic=True, color=GRAY, size=8)
    doc.add_paragraph()

    hdrs = ["#", "FECHA", "FUENTE", "LBL", "NEG", "AGG", "PRIO", "ENG",
            "TITULAR — CLICK PARA ABRIR ↗"]
    wds  = [0.22, 0.52, 1.40, 0.72, 0.38, 0.38, 0.62, 0.62, 6.14]

    main_tbl = doc.add_table(rows=1 + len(top), cols=len(hdrs))
    main_tbl.style     = "Table Grid"
    main_tbl.alignment = WD_TABLE_ALIGNMENT.LEFT

    for j, (h, w) in enumerate(zip(hdrs, wds)):
        c = main_tbl.rows[0].cells[j]
        c.width = Inches(w)
        _bg(c, "1F3864")
        pp = c.paragraphs[0]
        _sp(pp)
        pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _r(pp, h, bold=True, color=WHITE, size=8)

    for i, post in enumerate(top):
        row = main_tbl.rows[i + 1]
        lbl = _label(post)
        neg = _neg(post)
        agg = _agg(post)
        eng = _eng(post)
        lbl_bg, lbl_clr, row_bg = _LABEL_META.get(lbl, ("222222", WHITE, "111111"))
        lbl_rgb  = RGBColor(int(lbl_bg[0:2], 16), int(lbl_bg[2:4], 16), int(lbl_bg[4:6], 16))
        eng_str  = f"{eng // 1000}K" if eng >= 1000 else str(eng)
        agg_clr  = RED_MED if agg >= 0.70 else ORANGE

        # PRIO column — composite priority score
        prio_int, prio_label, prio_clr = _priority_score(post)
        prio_bar  = _bar(prio_int / 100, 4)
        prio_abbr = {"CRÍTICO": "CRIT", "ALTO": "ALTO", "MEDIO": "MED", "BAJO": "BAJO"}.get(prio_label, prio_label)
        prio_str  = f"{prio_bar}\n{prio_int:02d} {prio_abbr}"

        # LBL with comment confirmation marker
        lbl_display = lbl + "★" if _comment_confirms_attack(post) else lbl

        simple = [
            (str(i + 1),          WD_ALIGN_PARAGRAPH.CENTER, YELLOW,   8, True),
            (_fecha(post),         WD_ALIGN_PARAGRAPH.CENTER, GRAY,     8, False),
            (_source_label(post),  WD_ALIGN_PARAGRAPH.LEFT,   WHITE,    8, False),
            (lbl_display,          WD_ALIGN_PARAGRAPH.CENTER, lbl_rgb,  8, lbl == "AGRESIVO"),
            (f"{neg:.2f}",         WD_ALIGN_PARAGRAPH.CENTER, YELLOW,   8, False),
            (f"{agg:.2f}",         WD_ALIGN_PARAGRAPH.CENTER, agg_clr,  8, False),
            (prio_str,             WD_ALIGN_PARAGRAPH.CENTER, prio_clr, 8, prio_int >= 65),
            (eng_str,              WD_ALIGN_PARAGRAPH.CENTER, TEAL,     8, False),
        ]
        for j, (val, aln, clr, sz, bld) in enumerate(simple):
            c = row.cells[j]
            _bg(c, lbl_bg if j == 3 else row_bg)
            pp = c.paragraphs[0]
            _sp(pp)
            pp.alignment = aln
            _r(pp, val, bold=bld, color=clr, size=sz)

        c = row.cells[8]
        _bg(c, row_bg)
        pp = c.paragraphs[0]
        _sp(pp)
        pp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        title_str = _title(post)
        title_str = title_str[:110] + "…" if len(title_str) > 110 else title_str
        url = post.get("url") or ""
        if url:
            _hyperlink(pp, url, title_str, color=CYAN, size=8)
        else:
            _r(pp, title_str, color=GRAY, size=8)

    doc.add_paragraph()

    # ── SECCIÓN 4: MAPA DE ATAQUES ────────────────────────────────────────────
    _h1(doc, f"MAPA DE ATAQUES EN FACEBOOK  —  {len([r for r in attack_records if r['count']>0])} TIPOS DETECTADOS")

    atk_hdrs = ["TIPO / FREC.", "RIESGO", "POSTS DETECTADOS", "NARRATIVA ATACANTE", "RESPUESTA DOCUMENTADA"]
    atk_wds  = [1.40, 0.75, 0.65, 2.75, 5.05]

    visible = [r for r in attack_records if r["count"] > 0] or attack_records[:3]

    atk_tbl = doc.add_table(rows=1 + len(visible), cols=5)
    atk_tbl.style = "Table Grid"

    for j, (h, w) in enumerate(zip(atk_hdrs, atk_wds)):
        c = atk_tbl.rows[0].cells[j]
        c.width = Inches(w)
        _bg(c, "C00000")
        pp = c.paragraphs[0]
        _sp(pp)
        _r(pp, h, bold=True, color=WHITE, size=8)

    atk_bgs = {"ALTO": "1A0000", "MEDIO": "0A0A00", "ALTO (bot)": "001010"}
    for i, rec in enumerate(visible):
        row = atk_tbl.rows[i + 1]
        bg  = atk_bgs.get(rec["risk"], "111111")
        risk_clr = RED_MED if "ALTO" in rec["risk"] else (ORANGE if rec["risk"] == "MEDIO" else PURPLE)

        for j, (val, clr, bld) in enumerate([
            (f"{rec['type']} — {rec['pct']}%", YELLOW,   True),
            (rec["risk"],                        risk_clr, True),
            (f"{rec['count']} post(s)",          CYAN,     False),
            (rec["attack"][:90],                 RED_MED,  False),
            (rec["counter"][:200],               GREEN,    False),
        ]):
            c = row.cells[j]
            _bg(c, bg)
            pp = c.paragraphs[0]
            _sp(pp)
            _r(pp, val, bold=bld, color=clr, size=8)

    doc.add_paragraph()

    # ── SECCIÓN 5: TEMPLATES DE RESPUESTA ────────────────────────────────────
    _h1(doc, "TEMPLATES DE RESPUESTA  —  COPIAR, ADAPTAR Y PEGAR EN FACEBOOK")

    for trigger, resp in templates:
        t_tbl = doc.add_table(rows=2, cols=1)
        t_tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
        c0 = t_tbl.rows[0].cells[0]
        _bg(c0, "1A0800")
        pp0 = c0.paragraphs[0]
        _sp(pp0)
        _r(pp0, f"  ← {trigger}", bold=True, color=ORANGE, size=9)
        c1 = t_tbl.rows[1].cells[0]
        _bg(c1, "001A06")
        pp1 = c1.paragraphs[0]
        _sp(pp1)
        _r(pp1, f"  ✅ {resp}", color=GREEN, size=9)
        doc.add_paragraph()

    # ── SECCIÓN 6: BOTS EN COMENTARIOS (PRIMARY CIB) ─────────────────────────
    _h1(doc, "CIB ANALYSIS — BOT DETECTION IN COMMENT SECTION  ·  COORDINATED INAUTHENTIC BEHAVIOR")

    if not comment_report.has_data:
        # No comments loaded — show clear instructions
        warn_tbl = doc.add_table(rows=1, cols=1)
        wc = warn_tbl.cell(0, 0)
        _bg(wc, "0A0A00")
        wp = wc.add_paragraph()
        _sp(wp)
        _r(wp, "  [!]  SIN DATOS DE COMENTARIOS — EJECUTAR CON --comments-on-top\n\n",
           bold=True, color=YELLOW, size=11)
        _r(wp,
           "  Los comentarios no fueron scrapeados en esta ejecución.\n"
           "  Para activar detección de bots en sección de comentarios:\n\n",
           color=GRAY, size=9)
        q_label = (query or "QUERY").upper()
        _r(wp,
           f"  python3 fbscrap.py search --query \"{q_label}\""
           f" --days {days} --sentiment --comments-on-top 30\n\n",
           bold=True, color=CYAN, size=9)
        _r(wp,
           "  8 VECTORES DE DETECCIÓN ACTIVOS:\n"
           "  1. TEXT FINGERPRINTING    — comentarios idénticos entre distintos posts (Jaccard 3-gram)\n"
           "  2. REPEAT ATTACKER        — mismo autor atacando en 2+ posts distintos\n"
           "  3. NAME ENTROPY           — nombres bot: números, CAPS, genérico, keyword institucional\n"
           "  4. ATTACK TEMPLATE        — frases de ataque sin contexto (\"CORRUPTO!\", \"A LA CÁRCEL\")\n"
           "  5. CAPS RATIO             — % de texto en mayúsculas en comentarios de ataque\n"
           "  6. ZERO-LIKE ATTACK       — ataque sin resonancia orgánica (0 likes)\n"
           "  7. ATTACK DENSITY         — % de comentarios ataque por post\n"
           "  8. COPYCAT BURST          — misma frase coordinada en múltiples posts del mismo tema\n",
           italic=True, color=GRAY, size=8)
        doc.add_paragraph()

    else:
        # --- 6A: RESUMEN GLOBAL COMENTARIOS ---
        bot_sum = doc.add_table(rows=1, cols=1)
        bsc = bot_sum.cell(0, 0)
        _bg(bsc, "080010")
        bsp = bsc.add_paragraph()
        _sp(bsp)
        _r(bsp,
           f"RESUMEN — {comment_report.total_comments_analyzed} COMENTARIOS ANALIZADOS"
           f"  ·  {comment_report.total_posts_with_comments} POSTS CON COMENTARIOS\n\n",
           bold=True, color=YELLOW, size=10)
        _r(bsp,
           f"  BOT CONFIRMADO   {_bar(comment_report.bot_confirmed_pct/100, 20)}"
           f"  {comment_report.bot_confirmed_count:4d}  ({comment_report.bot_confirmed_pct}%)\n",
           color=RED_MED, size=9)
        _r(bsp,
           f"  SOSPECHOSO       {_bar(comment_report.suspicious_pct/100, 20)}"
           f"  {comment_report.suspicious_count:4d}  ({comment_report.suspicious_pct}%)\n",
           color=ORANGE, size=9)
        _r(bsp,
           f"  ORGÁNICO         {_bar(comment_report.organic_pct/100, 20)}"
           f"  {comment_report.organic_count:4d}  ({comment_report.organic_pct}%)\n\n",
           color=GREEN, size=9)
        _r(bsp,
           f"  COPY-PASTE CIB: {len(comment_report.copycat_clusters)} clusters"
           f"  |  REPEAT ATTACKERS: {len(comment_report.repeat_attackers)}"
           f"  |  NOMBRES SOSPECHOSOS: {comment_report.suspicious_name_count}"
           f" ({comment_report.suspicious_name_pct}%)\n",
           bold=True, color=PURPLE, size=9)
        _r(bsp,
           f"  DENSIDAD MEDIA DE ATAQUE: {comment_report.avg_attack_density:.1f}%"
           "  |  Jaccard 3-gram + name entropy + repeat attacker + template detection\n",
           italic=True, color=GRAY, size=8)
        doc.add_paragraph()

        # --- 6B: COPY-PASTE CIB CLUSTERS ---
        if comment_report.copycat_clusters:
            _h1(doc,
                f"COPY-PASTE CIB — {len(comment_report.copycat_clusters)} FRASES COORDINADAS"
                "  (MISMO TEXTO · DISTINTOS USUARIOS · DISTINTOS POSTS)")

            for idx, cluster in enumerate(comment_report.copycat_clusters):
                cl_tbl = doc.add_table(rows=1, cols=1)
                clc = cl_tbl.cell(0, 0)
                _bg(clc, "1A0005")
                clp = clc.add_paragraph()
                _sp(clp)
                _r(clp,
                   f"CLUSTER #{idx+1}  —  {cluster.occurrences} comentaristas"
                   f"  en {len(cluster.posts)} posts distintos"
                   f"  |  sim={cluster.similarity:.2f}  |  CIB CONFIRMADO\n",
                   bold=True, color=RED_MED, size=9)
                _r(clp, f"  Texto: \"{cluster.sample_text[:120]}\"\n\n",
                   italic=True, color=ORANGE, size=8)
                _r(clp, "  Autores: ", bold=True, color=GRAY, size=8)
                _r(clp, " | ".join(cluster.authors[:8]), color=YELLOW, size=8)
                _r(clp, "\n  Posts:   ", bold=True, color=GRAY, size=8)
                _r(clp, " | ".join(cluster.posts[:5]), color=CYAN, size=8)
                _r(clp, "\n", color=WHITE, size=8)
                doc.add_paragraph()

        # --- 6C: REPEAT ATTACKERS ---
        if comment_report.repeat_attackers:
            _h1(doc,
                f"REPEAT ATTACKERS — {len(comment_report.repeat_attackers)} CUENTAS"
                "  QUE ATACAN EN MÚLTIPLES POSTS (RED COORDINADA)")

            ra_tbl = doc.add_table(
                rows=1 + len(comment_report.repeat_attackers), cols=5)
            ra_tbl.style = "Table Grid"
            for j, (h, w) in enumerate(zip(
                ["AUTOR", "POSTS ATACADOS", "TOTAL ATAQUES", "NOMBRE BOT?",
                 "MUESTRA DE ATAQUES"],
                [1.70, 1.10, 1.10, 1.40, 5.30],
            )):
                c = ra_tbl.rows[0].cells[j]
                c.width = Inches(w)
                _bg(c, "3A0015")
                pp = c.paragraphs[0]
                _sp(pp)
                _r(pp, h, bold=True, color=WHITE, size=8)

            for i, att in enumerate(comment_report.repeat_attackers):
                row    = ra_tbl.rows[i + 1]
                row_bg = "1A0010" if att.name_score.is_bot else "0A0008"

                # Show first signal text + score — not just the score
                if att.name_score.signals:
                    sig_abbr  = att.name_score.signals[0][:40]
                    name_flag = f"{sig_abbr}\n({att.name_score.score}/100)"
                else:
                    name_flag = "—"
                name_clr = (RED_MED if att.name_score.score >= 60 else
                            ORANGE  if att.name_score.score >= 35 else GREEN)

                # Show sample texts AND media sources (previously lost)
                sample_txt = "  /  ".join(att.sample_texts[:2])
                sources_txt = " · ".join(att.sources[:4])
                muestra = f"{sample_txt[:65]}\n  ↳ medios: {sources_txt}" if sources_txt else sample_txt[:90]

                for j, (val, clr, bld) in enumerate([
                    (att.author[:28],        WHITE,    False),
                    (str(att.post_count),    RED_MED,  True),
                    (str(att.total_attacks), ORANGE,   True),
                    (name_flag,              name_clr, att.name_score.is_bot),
                    (muestra,                GRAY,     False),
                ]):
                    c = row.cells[j]
                    _bg(c, row_bg)
                    pp = c.paragraphs[0]
                    _sp(pp)
                    _r(pp, val, bold=bld, color=clr, size=8)

            doc.add_paragraph()

        # --- 6D: TOP BOT COMMENTS ---
        if comment_report.top_bot_comments:
            _h1(doc,
                f"TOP COMENTARIOS BOT — {len(comment_report.top_bot_comments)}"
                "  MÁS SOSPECHOSOS (SCORE MÁS ALTO)")

            bc_tbl = doc.add_table(
                rows=1 + len(comment_report.top_bot_comments), cols=5)
            bc_tbl.style = "Table Grid"
            for j, (h, w) in enumerate(zip(
                ["AUTOR", "CLASE", "POST (FUENTE)", "SEÑAL PRINCIPAL", "COMENTARIO"],
                [1.50, 1.20, 1.40, 2.10, 4.40],
            )):
                c = bc_tbl.rows[0].cells[j]
                c.width = Inches(w)
                _bg(c, "200010")
                pp = c.paragraphs[0]
                _sp(pp)
                _r(pp, h, bold=True, color=WHITE, size=8)

            for i, rec in enumerate(comment_report.top_bot_comments):
                row    = bc_tbl.rows[i + 1]
                row_bg = "1A0008" if rec.bot_class == "BOT CONFIRMADO" else "0A0010"
                cls_clr = RED_MED if rec.bot_class == "BOT CONFIRMADO" else ORANGE
                top_sig = rec.signals[0].description[:55] if rec.signals else "—"

                for j, (val, clr, bld) in enumerate([
                    (rec.author[:24],      WHITE,   False),
                    (rec.bot_class,        cls_clr, True),
                    (rec.post_source[:22], CYAN,    False),
                    (top_sig,              ORANGE,  False),
                    (rec.text[:85],        GRAY,    False),
                ]):
                    c = row.cells[j]
                    _bg(c, row_bg)
                    pp = c.paragraphs[0]
                    _sp(pp)
                    _r(pp, val, bold=bld, color=clr, size=8)

            doc.add_paragraph()

        # --- 6E: ATTACK DENSITY PER POST ---
        if comment_report.attack_density_per_post:
            _h1(doc, "DENSIDAD DE ATAQUE POR POST  —  % DE COMENTARIOS QUE SON ATAQUE PURO")

            ad_tbl = doc.add_table(
                rows=1 + len(comment_report.attack_density_per_post), cols=5)
            ad_tbl.style = "Table Grid"
            for j, (h, w) in enumerate(zip(
                ["FUENTE", "TOTAL COMENTS", "ATAQUES", "% ATAQUE", "BARRA"],
                [1.80, 1.00, 0.85, 0.80, 6.15],
            )):
                c = ad_tbl.rows[0].cells[j]
                c.width = Inches(w)
                _bg(c, "001020")
                pp = c.paragraphs[0]
                _sp(pp)
                _r(pp, h, bold=True, color=WHITE, size=8)

            for i, d in enumerate(comment_report.attack_density_per_post):
                row    = ad_tbl.rows[i + 1]
                pct    = d["pct"]
                bg     = ("1A0000" if pct >= 70 else
                          "0A0400" if pct >= 40 else "001005")
                bar_clr = (RED_MED if pct >= 70 else
                           ORANGE  if pct >= 40 else GREEN)

                for j, (val, clr, bld) in enumerate([
                    (d["source"][:28],     WHITE,   False),
                    (str(d["total"]),       GRAY,    False),
                    (str(d["attacks"]),     ORANGE,  False),
                    (f"{pct}%",            bar_clr, True),
                    (_bar(pct / 100, 22),  bar_clr, False),
                ]):
                    c = row.cells[j]
                    _bg(c, bg)
                    pp = c.paragraphs[0]
                    _sp(pp)
                    _r(pp, val, bold=bld, color=clr, size=8)

            doc.add_paragraph()

        # --- 6F: TOP ATTACK PHRASES ---
        if comment_report.top_attack_phrases:
            ap = doc.add_paragraph()
            _sp(ap, "60", "10")
            _r(ap, "TOP FRASES DE ATAQUE EN COMENTARIOS:\n",
               bold=True, color=RED_MED, size=9)
            max_cnt = comment_report.top_attack_phrases[0][1]
            for phrase, cnt in comment_report.top_attack_phrases:
                bar = _bar(cnt / max(max_cnt, 1), 12)
                _r(ap, f"  [{cnt:3d}x]  {bar}  \"{phrase[:70]}\"\n",
                   color=ORANGE, size=8)
            doc.add_paragraph()

        # --- 6H: TOP 20 BOT SUSPECTS — CROSS-POST INTELLIGENCE ---
        if comment_report.top_bot_suspects:
            _h1(doc,
                f"TOP {len(comment_report.top_bot_suspects)} BOT SUSPECTS"
                "  —  RASTREO CROSS-MEDIA  (QUIÉN · CUÁNTO · DÓNDE)")

            sp_tbl = doc.add_table(
                rows=1 + len(comment_report.top_bot_suspects), cols=6)
            sp_tbl.style = "Table Grid"
            sp_hdrs = ["#", "AUTOR", "SCORE", "ATAQUES", "MEDIOS", "SEÑALES / MUESTRA"]
            sp_wids = [0.22, 1.50, 0.55, 0.55, 0.75, 6.43]
            for j, (h, w) in enumerate(zip(sp_hdrs, sp_wids)):
                cell = sp_tbl.cell(0, j)
                _bg(cell, "220015")
                cell.width = Inches(w)
                pp = cell.paragraphs[0]
                _sp(pp, "20", "20")
                _r(pp, h, bold=True, color=WHITE, size=8)

            for i, sus in enumerate(comment_report.top_bot_suspects):
                row    = sp_tbl.rows[i + 1]
                row_bg = "1A000E" if sus.cross_media else "0C0008"
                if sus.composite_score >= 60:
                    row_bg = "2A0010"

                if sus.composite_score >= 60:
                    sc_clr = RED_MED
                elif sus.composite_score >= 35:
                    sc_clr = ORANGE
                else:
                    sc_clr = YELLOW

                cross_tag = " ★" if sus.cross_media else ""
                sig_text  = " · ".join(sus.signals[:3])
                sample    = (sus.sample_attacks[0][:60] if sus.sample_attacks else "")
                detail    = f"{sig_text}\n  └─ \"{sample}\"" if sample else sig_text

                cells_data = [
                    (f"{i+1}",                                        WHITE),
                    (f"{sus.author[:30]}",                            YELLOW if sus.cross_media else WHITE),
                    (f"{sus.composite_score:02d}/99{cross_tag}",      sc_clr),
                    (f"{sus.total_attacks}x · {sus.posts_attacked}p", ORANGE),
                    ("\n".join(sus.sources[:4]),                       GREEN),
                    (detail,                                           GRAY),
                ]
                for j, (txt, clr) in enumerate(cells_data):
                    c  = row.cells[j]
                    _bg(c, row_bg)
                    pp = c.paragraphs[0]
                    _sp(pp, "15", "15")
                    _r(pp, txt, color=clr, size=7)

            doc.add_paragraph()

            cross_cnt = sum(1 for s in comment_report.top_bot_suspects if s.cross_media)
            if cross_cnt:
                note = doc.add_paragraph()
                _sp(note, "30", "10")
                _r(note,
                   f"  ★ {cross_cnt} sospechosos atacan en 2+ MEDIOS DISTINTOS"
                   "  — red coordinada cross-media confirmada (prioridad máxima)\n",
                   color=RED_MED, size=8, bold=True)
                doc.add_paragraph()

    # ── 6G: POST-LEVEL CIB (secondary) ───────────────────────────────────────
    _h1(doc, "AMPLIFICACIÓN COORDINADA DE PUBLICACIÓN  ·  NIVEL POST  (CIB SECUNDARIO)")

    # 6G-a summary
    pst_sum = doc.add_table(rows=1, cols=1)
    psc = pst_sum.cell(0, 0)
    _bg(psc, "0A000A")
    psp = psc.add_paragraph()
    _sp(psp)
    _r(psp,
       f"RESUMEN — {bot_report.total_posts} POSTS ANALIZADOS  ·  COORDINACIÓN ENTRE FUENTES PUBLICADORAS\n\n",
       bold=True, color=YELLOW, size=9)
    _r(psp,
       f"  BOT CONFIRMADO  {_bar(bot_report.bot_confirmed_pct/100, 18)}"
       f"  {bot_report.bot_confirmed_count:3d} ({bot_report.bot_confirmed_pct}%)\n",
       color=RED_MED, size=8)
    _r(psp,
       f"  SOSPECHOSO      {_bar(bot_report.suspicious_pct/100, 18)}"
       f"  {bot_report.suspicious_count:3d} ({bot_report.suspicious_pct}%)\n",
       color=ORANGE, size=8)
    _r(psp,
       f"  ORGÁNICO        {_bar(bot_report.organic_pct/100, 18)}"
       f"  {bot_report.organic_count:3d} ({bot_report.organic_pct}%)\n\n",
       color=GREEN, size=8)
    _r(psp,
       f"  CLUSTERS CIB: {bot_report.cib_cluster_count}"
       f"  |  GHOST AMPLIFIERS: {bot_report.ghost_count}"
       f"  |  BURST CAMPAIGNS: {len(bot_report.burst_events)}"
       f"  |  ENG ARTIFICIAL EST.: {bot_report.estimated_fake_eng:,}\n",
       bold=True, color=PURPLE, size=8)
    _r(psp,
       "  Jaccard 3-gram shingles + burst temporal + ghost amplifier + attack source profiling.\n",
       italic=True, color=GRAY, size=7)
    doc.add_paragraph()

    # 6G-b CIB post clusters
    if bot_report.cib_clusters:
        _h1(doc,
            f"CLUSTERS CIB NIVEL POST — {len(bot_report.cib_clusters)}"
            "  CAMPAÑAS (TEXTO IDÉNTICO, FUENTES DISTINTAS)")
        for cluster in bot_report.cib_clusters:
            cib_tbl = doc.add_table(rows=1, cols=1)
            cc = cib_tbl.cell(0, 0)
            _bg(cc, "1A0000")
            cp = cc.add_paragraph()
            _sp(cp)
            _r(cp,
               f"CLUSTER #{cluster.cluster_id + 1}  —  {len(cluster.posts)} cuentas"
               f"  |  ventana {cluster.time_span_min:.0f} min  |  COORDINACIÓN CONFIRMADA\n",
               bold=True, color=RED_MED, size=9)
            _r(cp, f"  Texto: \"{cluster.sample_text[:120]}\"\n\n",
               italic=True, color=ORANGE, size=8)
            for src, sim in zip(cluster.sources, cluster.similarities):
                icon = "[BOT]" if sim >= 0.90 else "[!] "
                _r(cp,
                   f"  {icon}  {src:<30}  Jaccard={sim:.2f}  "
                   f"{'COPIA EXACTA' if sim >= 0.95 else 'CASI EXACTA' if sim >= 0.70 else 'SIMILAR'}\n",
                   color=RED_MED if sim >= 0.90 else ORANGE, size=9)
            doc.add_paragraph()

    # 6G-c Ghost amplifiers
    if bot_report.ghost_amplifiers:
        _h1(doc,
            f"GHOST AMPLIFIERS — {len(bot_report.ghost_amplifiers)} CUENTAS SIN AUDIENCIA REAL")
        gh_rows = bot_report.ghost_amplifiers
        gh_tbl  = doc.add_table(rows=1 + len(gh_rows), cols=5)
        gh_tbl.style = "Table Grid"
        for j, (h, w) in enumerate(zip(
            ["CUENTA / FUENTE", "CLASE", "R / C / S", "SEÑAL PRINCIPAL", "EVIDENCIA"],
            [1.60, 1.10, 0.70, 2.40, 4.80],
        )):
            c = gh_tbl.rows[0].cells[j]
            c.width = Inches(w)
            _bg(c, "3A0000")
            pp = c.paragraphs[0]
            _sp(pp)
            _r(pp, h, bold=True, color=WHITE, size=8)

        for i, gr in enumerate(gh_rows):
            row     = gh_tbl.rows[i + 1]
            row_bg  = "1A0010" if gr.bot_class == "BOT CONFIRMADO" else "0A0A10"
            cls_clr = RED_MED if gr.bot_class == "BOT CONFIRMADO" else ORANGE
            top_sig = gr.signals[0] if gr.signals else None
            for j, (val, clr, bld) in enumerate([
                (gr.source[:28],                                     WHITE,   False),
                (gr.bot_class,                                       cls_clr, True),
                (f"r={gr.reactions} c={gr.comments} s={gr.shares}", GRAY,    False),
                (top_sig.description[:50] if top_sig else "—",      ORANGE,  False),
                (top_sig.evidence[:80]    if top_sig else "—",      PURPLE,  False),
            ]):
                c = row.cells[j]
                _bg(c, row_bg)
                pp = c.paragraphs[0]
                _sp(pp)
                _r(pp, val, bold=bld, color=clr, size=8)
        doc.add_paragraph()

    # 6G-d Burst campaigns
    if bot_report.burst_events:
        _h1(doc,
            f"BURST CAMPAIGNS — {len(bot_report.burst_events)} VENTANAS DE PUBLICACIÓN COORDINADA")
        bu_tbl = doc.add_table(rows=1 + len(bot_report.burst_events), cols=4)
        bu_tbl.style = "Table Grid"
        for j, (h, w) in enumerate(zip(
            ["VENTANA TEMPORAL", "POSTS / SPAN", "FUENTES COORDINADAS", "TEMA / SAMPLE"],
            [1.30, 0.80, 2.90, 5.60],
        )):
            c = bu_tbl.rows[0].cells[j]
            c.width = Inches(w)
            _bg(c, "001A3A")
            pp = c.paragraphs[0]
            _sp(pp)
            _r(pp, h, bold=True, color=WHITE, size=8)

        for i, b in enumerate(bot_report.burst_events):
            row    = bu_tbl.rows[i + 1]
            row_bg = "000A1A"
            srcs   = " | ".join(b["sources"][:4])
            if len(b["sources"]) > 4:
                srcs += f" +{len(b['sources'])-4}"
            for j, (val, clr, bld) in enumerate([
                (f"{b['window_start']} → {b['window_end']}", CYAN,   False),
                (f"{b['post_count']} posts / {b['span_min']}min", YELLOW, True),
                (srcs[:55],                                        ORANGE, False),
                (b["sample_text"][:65],                            WHITE,  False),
            ]):
                c = row.cells[j]
                _bg(c, row_bg)
                pp = c.paragraphs[0]
                _sp(pp)
                _r(pp, val, bold=bld, color=clr, size=8)
        doc.add_paragraph()

    # 6G-e Attack-focused sources
    if bot_report.attack_sources:
        _h1(doc,
            f"FUENTES 100% ATAQUE — {len(bot_report.attack_sources)}"
            "  MEDIOS/CUENTAS CON AGENDA NEGATIVA EXCLUSIVA")
        as_tbl = doc.add_table(rows=1 + len(bot_report.attack_sources), cols=4)
        as_tbl.style = "Table Grid"
        for j, (h, w) in enumerate(zip(
            ["FUENTE", "% NEGATIVO", "POSTS", "MUESTRA DE TITULARES"],
            [1.80, 0.85, 0.55, 7.40],
        )):
            c = as_tbl.rows[0].cells[j]
            c.width = Inches(w)
            _bg(c, "1A0010")
            pp = c.paragraphs[0]
            _sp(pp)
            _r(pp, h, bold=True, color=WHITE, size=8)

        for i, a in enumerate(bot_report.attack_sources):
            row    = as_tbl.rows[i + 1]
            row_bg = "120008"
            sample = "  |  ".join(a["sample_titles"])[:80]
            for j, (val, clr, bld) in enumerate([
                (a["source"][:28],                          WHITE,   False),
                (f"{a['neg_pct']}%  {_bar(a['neg_pct']/100, 8)}", RED_MED, True),
                (str(a["post_count"]),                      YELLOW,  True),
                (sample,                                    ORANGE,  False),
            ]):
                c = row.cells[j]
                _bg(c, row_bg)
                pp = c.paragraphs[0]
                _sp(pp)
                _r(pp, val, bold=bld, color=clr, size=8)
        doc.add_paragraph()

    # ── SECCIÓN 7: CIB NETWORK INTELLIGENCE ──────────────────────────────────
    _h1(doc, "CIB NETWORK INTELLIGENCE  ·  MAPA DE COMPORTAMIENTO INAUTÉNTICO COORDINADO")

    # 7A — Summary box
    net_box = doc.add_table(rows=1, cols=1)
    nc = net_box.cell(0, 0)
    _bg(nc, "001A2A")
    np_ = nc.add_paragraph()
    _sp(np_)

    coord = cib_result.coordination_score
    coord_bar = "█" * (coord // 5) + "░" * (20 - coord // 5)
    coord_clr = RED_MED if coord >= 70 else ORANGE if coord >= 40 else YELLOW

    _r(np_, "NETWORK OVERVIEW\n\n", bold=True, color=CYAN, size=9)
    _r(np_,
       f"  ACTORES TOTALES    {cib_result.total_actors:>6}\n"
       f"  ARISTAS (EDGES)    {cib_result.total_edges:>6}\n"
       f"  CLUSTERS DETECTADOS{len(cib_result.clusters):>6}\n"
       f"  NODOS COMANDO      {len(cib_result.command_nodes):>6}\n"
       f"  NODOS AMPLIFICADOR {len(cib_result.amplifier_nodes):>6}\n\n",
       color=WHITE, size=8)
    _r(np_, f"  COORDINATION SCORE  [{coord_bar}]  {coord}/100\n",
       bold=True, color=coord_clr, size=9)

    role_counts: dict[str, int] = {}
    for n in cib_result.nodes.values():
        role_counts[n.role] = role_counts.get(n.role, 0) + 1
    role_line = "  " + "  |  ".join(
        f"{r}: {role_counts[r]}"
        for r in ("COMMAND", "AMPLIFIER", "BOT_CLUSTER", "HUB", "PERIPHERAL")
        if r in role_counts
    )
    _r(np_, f"\n{role_line}\n", color=GRAY, size=7)

    if cib_result.graphml_path:
        _r(np_,
           f"\n  EXPORT → {cib_result.graphml_path}  (abrir con Gephi)\n"
           f"           {cib_result.d3_path}  (visualización D3 interactiva)\n",
           italic=True, color=TEAL, size=7)
    doc.add_paragraph()

    # 7B — Cluster table (top 10)
    if cib_result.clusters:
        _h1(doc,
            f"TOP {min(10, len(cib_result.clusters))} CLUSTERS CIB"
            "  ·  REDES DE COORDINACIÓN DETECTADAS")
        cl_tbl = doc.add_table(rows=1 + min(10, len(cib_result.clusters)), cols=6)
        cl_tbl.style = "Table Grid"
        _cl_hdrs = ["#", "TAMAÑO", "RISK", "TOP ACTOR", "COORD SCORE", "ATAQUES"]
        _cl_wids = [0.22, 0.60, 0.80, 2.50, 1.20, 0.75]
        for j, (h, w) in enumerate(zip(_cl_hdrs, _cl_wids)):
            c = cl_tbl.cell(0, j)
            _bg(c, "002030")
            c.width = Inches(w)
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, h, bold=True, color=CYAN, size=8)

        _risk_color = {"CRITICAL": RED_MED, "HIGH": ORANGE, "MEDIUM": YELLOW, "LOW": TEAL}
        _risk_bg    = {"CRITICAL": "200010", "HIGH": "1A0800", "MEDIUM": "1A1000", "LOW": "001A10"}

        for i, cl in enumerate(cib_result.clusters[:10]):
            row = cl_tbl.rows[i + 1]
            rbg = _risk_bg.get(cl.risk_label, "0A0A0A")
            rc  = _risk_color.get(cl.risk_label, GRAY)
            actors_preview = ", ".join(cl.actors[:3])
            if len(cl.actors) > 3:
                actors_preview += f" +{len(cl.actors) - 3}"
            cells_d = [
                (f"{i+1}",           WHITE),
                (f"{cl.size}",       YELLOW),
                (cl.risk_label,      rc),
                (f"{cl.top_actor[:28]}\n{actors_preview[:35]}", WHITE),
                (f"{cl.coord_score:.1f}/99\n"
                 f"density {cl.edge_density:.2f}", rc),
                (f"{cl.attack_count}", ORANGE if cl.attack_count else GRAY),
            ]
            for j, (txt, clr) in enumerate(cells_d):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, color=clr, size=7)
        doc.add_paragraph()

    # 7C — Command + Amplifier nodes table
    key_nodes = (
        [(a, "COMMAND")   for a in cib_result.command_nodes[:5]] +
        [(a, "AMPLIFIER") for a in cib_result.amplifier_nodes[:5]]
    )
    if key_nodes:
        _h1(doc, "NODOS CLAVE  ·  COMMAND NODES + AMPLIFICADORES DETECTADOS")
        kn_tbl = doc.add_table(rows=1 + len(key_nodes), cols=5)
        kn_tbl.style = "Table Grid"
        for j, (h, w) in enumerate(zip(
            ["ACTOR", "ROL", "DEGREE", "BETWEENNESS", "PAGERANK"],
            [2.80, 1.10, 0.60, 1.10, 0.90],
        )):
            c = kn_tbl.cell(0, j)
            _bg(c, "001030")
            c.width = Inches(w)
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, h, bold=True, color=CYAN, size=8)

        for i, (actor, role) in enumerate(key_nodes):
            node  = cib_result.nodes.get(actor)
            row   = kn_tbl.rows[i + 1]
            rbg   = "1A0010" if role == "COMMAND" else "0A0A1A"
            rc    = RED_MED  if role == "COMMAND" else ORANGE
            for j, (txt, clr) in enumerate([
                (actor[:35],                                      WHITE),
                (role,                                            rc),
                (str(node.degree)       if node else "?",        YELLOW),
                (f"{node.betweenness:.4f}" if node else "?",     CYAN),
                (f"{node.pagerank:.6f}" if node else "?",        TEAL),
            ]):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, bold=(j == 1), color=clr, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 8: HUMAN CONFIDENCE SCORE (HCS) ──────────────────────────────
    _h1(doc, "HUMAN CONFIDENCE SCORE (HCS)  ·  PROBABILIDAD PERSONA REAL  vs  BOT")

    # 8A — Distribution summary
    dist_box = doc.add_table(rows=1, cols=1)
    dc = dist_box.cell(0, 0)
    _bg(dc, "0A0010")
    dp = dc.add_paragraph()
    _sp(dp)
    _r(dp, f"HCS DISTRIBUTION  ·  {hcs_report.total_actors} ACTORES ANALIZADOS\n\n",
       bold=True, color=PURPLE, size=9)

    _dist_rows = [
        (hcs_report.confirmed_bots,  "CONFIRMED BOT ",  RED_MED,  "FF3333"),
        (hcs_report.high_risk,       "HIGH RISK     ",  ORANGE,   "FF6B00"),
        (hcs_report.suspicious,      "SUSPICIOUS    ",  YELLOW,   "FFC000"),
        (hcs_report.likely_human,    "LIKELY HUMAN  ",  CYAN,     "44CCFF"),
        (hcs_report.human,           "HUMAN         ",  GREEN,    "00BB55"),
    ]
    total_a = max(hcs_report.total_actors, 1)
    for bucket_list, label, clr, _ in _dist_rows:
        n   = len(bucket_list)
        pct = n / total_a
        bar = "█" * int(pct * 25) + "░" * (25 - int(pct * 25))
        _r(dp, f"  {label}  [{bar}]  {n:4d}  ({pct:.0%})\n", color=clr, size=8)

    _r(dp,
       f"\n  MEAN HCS: {hcs_report.mean_hcs:.1f}  |  "
       f"BOT/HIGH-RISK: {hcs_report.bot_percentage:.1f}%\n",
       bold=True,
       color=RED_MED if hcs_report.bot_percentage >= 50 else ORANGE,
       size=8)
    doc.add_paragraph()

    # 8B — Top 30 most suspicious actors (lowest HCS)
    top_suspicious = hcs_report.actor_scores[:30]
    if top_suspicious:
        _h1(doc,
            f"TOP {len(top_suspicious)} ACTORES MÁS SOSPECHOSOS  "
            "·  HCS SCORE + EVIDENCIA FORENSE")
        hcs_tbl = doc.add_table(rows=1 + len(top_suspicious), cols=6)
        hcs_tbl.style = "Table Grid"
        _hcs_hdrs = ["#", "ACTOR", "HCS", "LABEL", "ATK RATE", "SEÑALES"]
        _hcs_wids = [0.22, 2.20, 0.50, 1.20, 0.75, 5.73]
        for j, (h, w) in enumerate(zip(_hcs_hdrs, _hcs_wids)):
            c = hcs_tbl.cell(0, j)
            _bg(c, "1A001A")
            c.width = Inches(w)
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, h, bold=True, color=PURPLE, size=8)

        for i, actor_s in enumerate(top_suspicious):
            row = hcs_tbl.rows[i + 1]
            # Row background by label
            _hcs_bg = {
                "CONFIRMED BOT": "1A0008",
                "HIGH RISK":     "1A0800",
                "SUSPICIOUS":    "101000",
                "LIKELY HUMAN":  "001010",
                "HUMAN":         "001A08",
            }
            rbg = _hcs_bg.get(actor_s.label, "0A0A0A")
            lc  = RGBColor(*bytes.fromhex(actor_s.label_color.lstrip("#")))
            sigs_txt = " · ".join(actor_s.signals[:3]) if actor_s.signals else "—"
            cells_d = [
                (f"{i+1}",                                    WHITE),
                (actor_s.actor[:28],                         YELLOW if actor_s.hcs < 20 else WHITE),
                (f"{actor_s.hcs:02d}/99",                    lc),
                (actor_s.label,                              lc),
                (f"{actor_s.attack_ratio:.0%}"
                 f"  ({actor_s.attack_count}x)",             ORANGE if actor_s.attack_ratio > 0.5 else GRAY),
                (sigs_txt[:75],                              GRAY),
            ]
            for j, (txt, clr) in enumerate(cells_d):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, bold=(j == 2), color=clr, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 9: TEMPORAL ATTACK WAVE DETECTOR (P2) ────────────────────────
    doc.add_paragraph()
    _div(doc, "C00000")
    p9h = doc.add_paragraph()
    _sp(p9h, "60", "20")
    p9h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p9h, "⏱  SECCIÓN 9 — TEMPORAL ATTACK WAVE DETECTOR",
       bold=True, color=RED_MED, size=13)
    doc.add_paragraph()

    # Summary box
    p9s = doc.add_paragraph()
    _sp(p9s)
    _r(p9s, f"[TEMPORAL SCORE: {temporal_report.overall_score}/100]  ", bold=True, color=ORANGE, size=10)
    _r(p9s, temporal_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    if temporal_report.waves:
        # Attack waves table
        ph = doc.add_paragraph()
        _sp(ph)
        _r(ph, f"▶  {len(temporal_report.waves)} COORDINATED ATTACK WAVE(S) DETECTED", bold=True, color=RED_MED, size=10)

        wt = doc.add_table(rows=1, cols=6)
        wt.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, hdr in enumerate(["WAVE #", "START UTC", "END UTC", "PARTICIPANTS", "EVENTS", "INTENSITY"]):
            c = wt.rows[0].cells[j]
            _bg(c, "3A0000")
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, hdr, bold=True, color=RED_MED, size=8)

        for wi, wave in enumerate(temporal_report.waves[:20]):
            rbg = "1A0000" if wi % 2 == 0 else "0E0000"
            row = wt.add_row()
            for j, (txt, clr) in enumerate([
                (f"W-{wave.wave_id:02d}",                               CYAN),
                (wave.start.strftime("%Y-%m-%d %H:%M:%S"),              WHITE),
                (wave.end.strftime("%H:%M:%S"),                         WHITE),
                (f"{len(wave.participants)} actors",                    ORANGE),
                (f"{len(wave.events)} comments",                        YELLOW),
                (f"{wave.intensity:.2f}",                               RED_MED if wave.intensity > 1.0 else GRAY),
            ]):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, bold=(j == 0), color=clr, size=7)
        doc.add_paragraph()

        # Top wave participants
        if temporal_report.suspicious_actors:
            psa = doc.add_paragraph()
            _sp(psa)
            _r(psa, "► MULTI-WAVE ACTORS (appear in ≥2 waves — highest coordination risk): ",
               bold=True, color=RED_MED, size=9)
            _r(psa, "  ·  ".join(temporal_report.suspicious_actors[:15]), color=YELLOW, size=8)
            doc.add_paragraph()

    if temporal_report.sync_pairs:
        psp = doc.add_paragraph()
        _sp(psp)
        _r(psp, f"⚡ ULTRA-SYNC PAIRS (≤3s between different accounts — impossible organically): ",
           bold=True, color=ORANGE, size=9)
        top_pairs = temporal_report.sync_pairs[:8]
        pair_txts = [f"{p.author_a[:20]} ↔ {p.author_b[:20]} (Δ{p.delta_s}s)" for p in top_pairs]
        _r(psp, "  |  ".join(pair_txts), color=YELLOW, size=8)
        doc.add_paragraph()

    if not temporal_report.waves and not temporal_report.sync_pairs:
        pnt = doc.add_paragraph()
        _sp(pnt)
        _r(pnt, "No timestamped comments available — run with --comments-on-top to enable temporal analysis.",
           color=GRAY, size=8)
        doc.add_paragraph()

    # ── SECCIÓN 10: STYLOMETRIC FINGERPRINTING ───────────────────────────
    doc.add_paragraph()
    _div(doc, "4A0080")
    p10h = doc.add_paragraph()
    _sp(p10h, "60", "20")
    p10h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p10h, "🖋  SECCIÓN 10 — STYLOMETRIC FINGERPRINTING",
       bold=True, color=PURPLE, size=13)
    doc.add_paragraph()

    p10s = doc.add_paragraph()
    _sp(p10s)
    _r(p10s, "[STYLOMETRY]  ", bold=True, color=PURPLE, size=10)
    _r(p10s, stylo_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    if stylo_report.clusters:
        pc = doc.add_paragraph()
        _sp(pc)
        _r(pc, f"▶  {len(stylo_report.clusters)} STYLOMETRIC CLUSTER(S) — actors sharing writing fingerprint:",
           bold=True, color=PURPLE, size=10)

        ct = doc.add_table(rows=1, cols=4)
        ct.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, hdr in enumerate(["CLUSTER", "TYPE", "ACTORS", "COSINE SIM"]):
            c = ct.rows[0].cells[j]
            _bg(c, "200030")
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, hdr, bold=True, color=PURPLE, size=8)

        for ci, cl in enumerate(stylo_report.clusters[:15]):
            rbg = "120020" if ci % 2 == 0 else "0C0018"
            row = ct.add_row()
            actor_list = "  ·  ".join(cl.actors[:6]) + (" +más" if len(cl.actors) > 6 else "")
            for j, (txt, clr) in enumerate([
                (f"C-{cl.cluster_id:02d}",    CYAN),
                (cl.label,                    PURPLE if "TEMPLATE" in cl.label else ORANGE),
                (actor_list[:100],            YELLOW),
                (f"{cl.similarity:.4f}",      RED_MED if cl.similarity > 0.95 else GRAY),
            ]):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, bold=(j == 0), color=clr, size=7)
        doc.add_paragraph()

    if stylo_report.clone_pairs:
        pclone = doc.add_paragraph()
        _sp(pclone)
        _r(pclone, f"🔗 CLONE PAIRS (cosine ≥0.95 — same operator writing style): ",
           bold=True, color=ORANGE, size=9)
        clone_txts = [f"{a[:20]} ↔ {b[:20]} ({sim:.4f})" for a, b, sim in stylo_report.clone_pairs[:8]]
        _r(pclone, "  |  ".join(clone_txts), color=YELLOW, size=8)
        doc.add_paragraph()

    if stylo_report.copy_paste_groups:
        pcp = doc.add_paragraph()
        _sp(pcp)
        _r(pcp, f"📋 COPY-PASTE TEMPLATES ({len(stylo_report.copy_paste_groups)} template(s) used by ≥3 actors):",
           bold=True, color=RED_MED, size=9)
        for cpg in stylo_report.copy_paste_groups[:5]:
            pline = doc.add_paragraph()
            _sp(pline)
            _r(pline, f"  • [{cpg.count}x across {len(cpg.actors)} actors] ", bold=True, color=ORANGE, size=8)
            _r(pline, f'"{cpg.signature}…"', color=YELLOW, size=8)
        doc.add_paragraph()

    if stylo_report.bot_style_actors:
        pb = doc.add_paragraph()
        _sp(pb)
        _r(pb, f"🤖 BOT-TEMPLATE WRITERS ({len(stylo_report.bot_style_actors)} actors, low vocab diversity): ",
           bold=True, color=RED_MED, size=9)
        _r(pb, "  ·  ".join(stylo_report.bot_style_actors[:20]), color=YELLOW, size=8)
        doc.add_paragraph()

    # ── SECCIÓN 11: SENTIMENT MANIPULATION DELTA ────────────────────────
    doc.add_paragraph()
    _div(doc, "AA2200")
    p11h = doc.add_paragraph()
    _sp(p11h, "60", "20")
    p11h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p11h, "📊  SECTION 11 — SENTIMENT MANIPULATION DELTA",
       bold=True, color=ORANGE, size=13)
    doc.add_paragraph()

    p11s = doc.add_paragraph()
    _sp(p11s)
    _r(p11s, f"[SENTIMENT SCORE: {sentiment_report.manipulation_score}/100]  ",
       bold=True, color=ORANGE, size=10)
    _r(p11s, sentiment_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    seeded_deltas = [d for d in sentiment_report.post_deltas
                     if d.manipulation_label in ("SEEDED", "REVERSED")]
    if seeded_deltas:
        ph11 = doc.add_paragraph()
        _sp(ph11)
        _r(ph11, f"▶  {len(seeded_deltas)} SEEDED/REVERSED POST(S) DETECTED — SENTIMENT INJECTION",
           bold=True, color=RED_MED, size=10)

        sd_tbl = doc.add_table(rows=1, cols=5)
        sd_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, hdr in enumerate(["LABEL", "DELTA", "W0 NEG%", "W2 NEG%", "URL / DOMINANT ACTORS"]):
            c = sd_tbl.rows[0].cells[j]
            _bg(c, "3A1000")
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, hdr, bold=True, color=ORANGE, size=8)

        for di, delta in enumerate(seeded_deltas[:20]):
            rbg = "1A0800" if di % 2 == 0 else "100600"
            row = sd_tbl.add_row()
            w0 = delta.windows[0] if delta.windows else None
            w2 = delta.windows[2] if len(delta.windows) > 2 else None
            w0_neg = f"{w0.neg_ratio:.0%}" if w0 else "—"
            w2_neg = f"{w2.neg_ratio:.0%}" if w2 else "—"
            actors_txt = "  ·  ".join(delta.dominant_neg_actors[:4])
            url_short  = delta.post_url[:50] if delta.post_url else "?"
            detail     = f"{url_short}\n  actors: {actors_txt}" if actors_txt else url_short
            for j, (txt, clr) in enumerate([
                (delta.manipulation_label,        RED_MED if delta.manipulation_label == "SEEDED" else ORANGE),
                (f"{delta.manipulation_delta:+.3f}", RED_MED),
                (w0_neg,                          ORANGE),
                (w2_neg,                          GREEN),
                (detail[:100],                    GRAY),
            ]):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, color=clr, size=7)
        doc.add_paragraph()

    if sentiment_report.top_seed_accounts:
        p11sa = doc.add_paragraph()
        _sp(p11sa)
        _r(p11sa, f"TOP SEED ACCOUNTS (dominant early negative actors): ",
           bold=True, color=RED_MED, size=9)
        _r(p11sa, "  ·  ".join(sentiment_report.top_seed_accounts[:15]),
           color=YELLOW, size=8)
        doc.add_paragraph()

    # ── SECCIÓN 12: FIRST-MOVER SEEDING ANALYSIS ────────────────────────
    doc.add_paragraph()
    _div(doc, "005080")
    p12h = doc.add_paragraph()
    _sp(p12h, "60", "20")
    p12h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p12h, "🚀  SECTION 12 — FIRST-MOVER SEEDING ANALYSIS",
       bold=True, color=CYAN, size=13)
    doc.add_paragraph()

    p12s = doc.add_paragraph()
    _sp(p12s)
    _r(p12s, f"[SEEDING SCORE: {first_mover_report.overall_score}/100]  ",
       bold=True, color=CYAN, size=10)
    _r(p12s, first_mover_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    if first_mover_report.seed_accounts:
        ph12 = doc.add_paragraph()
        _sp(ph12)
        _r(ph12,
           f"▶  {len(first_mover_report.seed_accounts)} CONFIRMED SEED ACCOUNT(S) "
           f"— CONSISTENTLY COMMENT FIRST",
           bold=True, color=CYAN, size=10)

        fm_tbl = doc.add_table(rows=1, cols=5)
        fm_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, hdr in enumerate(["ACTOR", "SEED COUNT", "AVG POS", "POSTS SEEDED", "SAMPLE TEXT"]):
            c = fm_tbl.rows[0].cells[j]
            _bg(c, "002A40")
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, hdr, bold=True, color=CYAN, size=8)

        for fi, profile in enumerate(first_mover_report.seed_accounts[:20]):
            rbg = "001A28" if fi % 2 == 0 else "001020"
            row = fm_tbl.add_row()
            sample = profile.sample_texts[0][:60] if profile.sample_texts else "—"
            for j, (txt, clr) in enumerate([
                (profile.actor[:28],              YELLOW),
                (str(profile.seed_count),         RED_MED),
                (f"{profile.avg_position:.1f}",   ORANGE),
                (str(len(profile.posts)),         TEAL),
                (sample,                          GRAY),
            ]):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, color=clr, size=7)
        doc.add_paragraph()

    if first_mover_report.seeding_teams:
        p12t = doc.add_paragraph()
        _sp(p12t)
        _r(p12t,
           f"SEEDING TEAMS ({len(first_mover_report.seeding_teams)} detected — "
           "actors who co-seed the same posts): ",
           bold=True, color=ORANGE, size=9)
        for team in first_mover_report.seeding_teams[:5]:
            pline = doc.add_paragraph()
            _sp(pline)
            _r(pline, f"  • TEAM {team.team_id}: ", bold=True, color=ORANGE, size=8)
            _r(pline, "  ·  ".join(team.actors[:8]), color=YELLOW, size=8)
            _r(pline, f"  ({len(team.posts)} shared posts)", color=GRAY, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 13: SEMANTIC NARRATIVE CLUSTERS ─────────────────────────
    doc.add_paragraph()
    _div(doc, "4A008A")
    p13h = doc.add_paragraph()
    _sp(p13h, "60", "20")
    p13h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p13h, "🧠  SECTION 13 — SEMANTIC NARRATIVE CLUSTER ANALYSIS",
       bold=True, color=PURPLE, size=13)
    doc.add_paragraph()

    p13s = doc.add_paragraph()
    _sp(p13s)
    _r(p13s, f"[NARRATIVE SCORE: {semantic_report.narrative_score}/100]  ",
       bold=True, color=PURPLE, size=10)
    _r(p13s, semantic_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    if semantic_report.clusters:
        ph13 = doc.add_paragraph()
        _sp(ph13)
        _r(ph13,
           f"▶  {len(semantic_report.clusters)} NARRATIVE CLUSTER(S) — "
           f"{semantic_report.bot_dominated_count} BOT-DOMINATED",
           bold=True, color=PURPLE, size=10)

        nc_tbl = doc.add_table(rows=1, cols=5)
        nc_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, hdr in enumerate(["CLUSTER", "LABEL", "SIZE", "BOT%", "TOP TERMS / ACTORS"]):
            c = nc_tbl.rows[0].cells[j]
            _bg(c, "200040")
            pp = c.paragraphs[0]
            _sp(pp, "20", "20")
            _r(pp, hdr, bold=True, color=PURPLE, size=8)

        for ni, cl in enumerate(semantic_report.clusters[:15]):
            rbg = "180030" if cl.label == "BOT_DOMINATED" else ("100020" if cl.label == "MIXED" else "0A001A")
            lbl_clr = RED_MED if cl.label == "BOT_DOMINATED" else (ORANGE if cl.label == "MIXED" else GREEN)
            row = nc_tbl.add_row()
            terms  = ", ".join(cl.top_terms[:5])
            actors = "  ·  ".join(cl.actors[:4])
            detail = f"terms: [{terms}]\nactors: {actors}"
            for j, (txt, clr) in enumerate([
                (f"NC-{cl.cluster_id:02d}",      CYAN),
                (cl.label,                        lbl_clr),
                (str(cl.size),                    YELLOW),
                (f"{cl.bot_ratio:.0%}",           RED_MED if cl.bot_ratio >= 0.5 else ORANGE),
                (detail[:100],                    GRAY),
            ]):
                c = row.cells[j]
                _bg(c, rbg)
                pp = c.paragraphs[0]
                _sp(pp, "15", "15")
                _r(pp, txt, color=clr, size=7)
        doc.add_paragraph()

    if semantic_report.amplifiers or semantic_report.soldiers:
        p13r = doc.add_paragraph()
        _sp(p13r)
        if semantic_report.amplifiers:
            _r(p13r,
               f"AMPLIFIERS ({len(semantic_report.amplifiers)} — spreading narrative across ≥3 clusters): ",
               bold=True, color=ORANGE, size=9)
            _r(p13r, "  ·  ".join(semantic_report.amplifiers[:15]), color=YELLOW, size=8)
            _r(p13r, "\n", color=WHITE, size=8)
        if semantic_report.soldiers:
            _r(p13r,
               f"SOLDIERS ({len(semantic_report.soldiers)} bots focused on single narrative): ",
               bold=True, color=RED_MED, size=9)
            _r(p13r, "  ·  ".join(semantic_report.soldiers[:15]), color=YELLOW, size=8)
        doc.add_paragraph()

    # ── SECCIÓN 14: LEGAL EVIDENCE PACKAGE ──────────────────────────────
    doc.add_paragraph()
    _div(doc, "007040")
    p14h = doc.add_paragraph()
    _sp(p14h, "60", "20")
    p14h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p14h, "⚖️  SECTION 14 — LEGAL EVIDENCE PACKAGE (CHAIN-OF-CUSTODY)",
       bold=True, color=GREEN, size=13)
    doc.add_paragraph()

    mf = legal_report.manifest
    p14s = doc.add_paragraph()
    _sp(p14s)
    _r(p14s, f"CASE ID: {mf.case_id}  ·  {mf.total_items} EVIDENCE ITEMS\n",
       bold=True, color=GREEN, size=10)
    _r(p14s, f"Generated: {mf.generated_at}  ·  Analyst: {mf.analyst}  ·  Tool: {mf.tool_version}\n",
       color=GRAY, size=8)
    cats_str = "  |  ".join(f"{c}:{n}" for c, n in mf.categories.items())
    _r(p14s, f"Categories: {cats_str}\n", color=TEAL, size=8)
    _r(p14s,
       f"Manifest integrity hash (SHA-256): {mf.manifest_hash}\n",
       color=GREEN, size=7)
    doc.add_paragraph()

    _r(p14s, legal_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    if legal_report.html_path:
        p14f = doc.add_paragraph()
        _sp(p14f)
        _r(p14f, "EXPORTED FILES:\n", bold=True, color=GREEN, size=9)
        _r(p14f, f"  HTML evidence package: {legal_report.html_path}\n", color=CYAN, size=8)
        if legal_report.json_path:
            _r(p14f, f"  JSON manifest:         {legal_report.json_path}\n", color=CYAN, size=8)
        _r(p14f,
           "  All evidence hashed with SHA-256. Tampering with any item invalidates "
           "its hash and breaks chain-of-custody integrity.\n",
           italic=True, color=GRAY, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 15: ACCOUNT LIFECYCLE ANOMALY DETECTOR ──────────────────
    doc.add_paragraph()
    _div(doc, "3A0060")
    p15h = doc.add_paragraph()
    _sp(p15h, "60", "20")
    p15h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p15h, "SECTION 15 — ACCOUNT LIFECYCLE ANOMALY DETECTOR",
       bold=True, color=PURPLE, size=13)
    doc.add_paragraph()

    _rp = (cfg or {}).get("reporting", {}).get("docx", {})
    _max_lc_actors  = _rp.get("max_lifecycle_actors", 25)
    _max_lc_cells   = _rp.get("max_sleeper_cells",     5)

    p15s = doc.add_paragraph()
    _sp(p15s)
    lc_start_str = (lifecycle_report.campaign_start.strftime("%Y-%m-%d %H:%M")
                    if lifecycle_report.campaign_start else "unknown")
    _r(p15s,
       f"Campaign start: {lc_start_str}  ·  "
       f"{lifecycle_report.total_actors} actors analyzed  ·  "
       f"Sleepers: {len(lifecycle_report.sleepers)}  ·  "
       f"Bursters: {len(lifecycle_report.bursters)}  ·  "
       f"Coordinators: {len(lifecycle_report.coordinators)}  ·  "
       f"Score: {lifecycle_report.anomaly_score}/100\n",
       bold=True, color=PURPLE, size=9)
    _r(p15s, lifecycle_report.summary, color=WHITE, size=8)
    doc.add_paragraph()

    # Sleeper cells table
    if lifecycle_report.sleeper_cells:
        p15c = doc.add_paragraph()
        _sp(p15c)
        _r(p15c, f"COORDINATED SLEEPER CELLS ({len(lifecycle_report.sleeper_cells)})",
           bold=True, color=PURPLE, size=10)
        tbl15c = doc.add_table(rows=1, cols=5)
        tbl15c.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(["CELL-ID", "ACTORS", "ACTIVATION WINDOW", "POSTS HIT", "COORD%"]):
            c = tbl15c.cell(0, j)
            _bg(c, "280040")
            _r(c.paragraphs[0], h, bold=True, color=PURPLE, size=7)
        for cell in lifecycle_report.sleeper_cells[:_max_lc_cells]:
            win_str = (f"{cell.activation_start.strftime('%H:%M')} – "
                       f"{cell.activation_end.strftime('%H:%M')}"
                       if cell.activation_start else "—")
            row = tbl15c.add_row()
            for j, txt in enumerate([
                f"CELL-{cell.cell_id:02d}",
                ", ".join(cell.actors[:5]) + ("…" if len(cell.actors) > 5 else ""),
                win_str,
                str(len(cell.posts_targeted)),
                f"{cell.coordination_score:.0f}%",
            ]):
                c = row.cells[j]
                _bg(c, "1A0028")
                _sp(c.paragraphs[0], "15", "15")
                _r(c.paragraphs[0], txt, color=PURPLE, size=7)
        doc.add_paragraph()

    # Main lifecycle actors table
    _lc_label_bg = {
        "SLEEPER":     "3A0060",
        "BURST":       "3A2000",
        "COORDINATOR": "2A2A00",
        "ORGANIC":     "0A0A0A",
    }
    _lc_label_clr = {
        "SLEEPER":     PURPLE,
        "BURST":       ORANGE,
        "COORDINATOR": YELLOW,
        "ORGANIC":     GRAY,
    }
    if lifecycle_report.actors:
        p15t = doc.add_paragraph()
        _sp(p15t)
        _r(p15t, f"ACTOR LIFECYCLE BREAKDOWN (top {_max_lc_actors})",
           bold=True, color=PURPLE, size=10)
        tbl15 = doc.add_table(rows=1, cols=8)
        tbl15.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(["ACTOR", "FIRST SEEN", "WIN(h)", "CPH", "LAG(h)", "BURST", "SCORE", "LABEL"]):
            c = tbl15.cell(0, j)
            _bg(c, "280040")
            _r(c.paragraphs[0], h, bold=True, color=PURPLE, size=7)
        for actor in lifecycle_report.actors[:_max_lc_actors]:
            lbl   = actor.lifecycle_label
            bg    = _lc_label_bg.get(lbl, "0A0A0A")
            clr   = _lc_label_clr.get(lbl, GRAY)
            first_str = actor.first_seen.strftime("%m/%d %H:%M") if actor.first_seen else "—"
            row   = tbl15.add_row()
            for j, (txt, color) in enumerate([
                (actor.actor[:28],                      YELLOW if lbl == "SLEEPER" else WHITE),
                (first_str,                             GRAY),
                (f"{actor.active_window_hours:.1f}",    GRAY),
                (f"{actor.comments_per_hour:.1f}",      ORANGE if actor.comments_per_hour >= 10 else GRAY),
                (f"{actor.activation_lag_hours:.1f}",   RED_MED if actor.activation_lag_hours < 2 else GRAY),
                (str(actor.burst_count),                RED_MED if actor.burst_count >= 3 else GRAY),
                (f"{actor.anomaly_score}/100",          clr),
                (lbl,                                   clr),
            ]):
                cell = row.cells[j]
                _bg(cell, bg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 7), color=color, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 16: NARRATIVE INJECTION POINT DETECTOR ──────────────────
    doc.add_paragraph()
    _div(doc, "004060")
    p16h = doc.add_paragraph()
    _sp(p16h, "60", "20")
    p16h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p16h, "SECTION 16 — NARRATIVE INJECTION POINT DETECTOR",
       bold=True, color=CYAN, size=13)
    doc.add_paragraph()

    _max_inj     = _rp.get("max_injections",   15)
    _max_chain   = _rp.get("max_chain_entries",  8)

    p16s = doc.add_paragraph()
    _sp(p16s)
    _r(p16s,
       f"{injection_report.total_attack_comments} attack comments analyzed  ·  "
       f"{injection_report.total_narratives} narrative(s) detected  ·  "
       f"Score: {injection_report.injection_score}/100\n",
       bold=True, color=CYAN, size=9)
    _r(p16s, injection_report.summary, color=WHITE, size=8)
    doc.add_paragraph()

    # Top injectors summary line
    if injection_report.top_injectors:
        p16ti = doc.add_paragraph()
        _sp(p16ti)
        _r(p16ti, "TOP INJECTORS:  ", bold=True, color=CYAN, size=9)
        for actor, cnt in injection_report.top_injectors[:8]:
            _r(p16ti, f"{actor}({cnt})  ", color=YELLOW, size=8)
        doc.add_paragraph()

    # Main injections table
    if injection_report.injections:
        p16ht = doc.add_paragraph()
        _sp(p16ht)
        _r(p16ht, f"NARRATIVE INJECTION POINTS (top {_max_inj})",
           bold=True, color=CYAN, size=10)
        tbl16 = doc.add_table(rows=1, cols=7)
        tbl16.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(["NARR-ID", "SEED ACCOUNT", "SEED TIME", "TOP TERMS", "PROP", "POSTS", "SCORE"]):
            c = tbl16.cell(0, j)
            _bg(c, "002040")
            _r(c.paragraphs[0], h, bold=True, color=CYAN, size=7)
        for inj in injection_report.injections[:_max_inj]:
            ts_str = (inj.seed_timestamp.strftime("%m/%d %H:%M")
                      if inj.seed_timestamp else "—")
            score_bg = "3A1000" if inj.injection_score >= 70 else "001A2A"
            row = tbl16.add_row()
            for j, (txt, clr) in enumerate([
                (inj.narrative_id,                        CYAN),
                (inj.seed_account[:28],                   YELLOW),
                (ts_str,                                  GRAY),
                (", ".join(inj.top_terms[:4]),            WHITE),
                (str(inj.propagation_count),              ORANGE if inj.propagation_count >= 5 else GRAY),
                (str(inj.propagation_posts),              RED_MED if inj.propagation_posts >= 3 else GRAY),
                (f"{inj.injection_score}/100",            ORANGE if inj.injection_score >= 70 else CYAN),
            ]):
                cell = row.cells[j]
                _bg(cell, score_bg if j == 6 else "001428")
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 0), color=clr, size=7)
        doc.add_paragraph()

    # Propagation chains for top 3 narratives
    if injection_report.propagation_chains:
        p16ch = doc.add_paragraph()
        _sp(p16ch)
        _r(p16ch, "PROPAGATION CHAINS (top narratives):\n",
           bold=True, color=CYAN, size=9)
        for chain in injection_report.propagation_chains[:3]:
            _r(p16ch, f"\n  {chain.narrative_id}  ", bold=True, color=CYAN, size=8)
            for step in chain.steps[:_max_chain]:
                ts_disp = step.ts[:16] if step.ts else "??:??"
                _r(p16ch,
                   f"\n    [{ts_disp}]  {step.actor}  →  {step.text_excerpt[:60]}",
                   color=GRAY, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 17: INFLUENCE TOPOLOGY SCORE ────────────────────────────
    doc.add_paragraph()
    _div(doc, "002860")
    p17h = doc.add_paragraph()
    _sp(p17h, "60", "20")
    p17h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p17h, "🕸  SECTION 17 — INFLUENCE TOPOLOGY SCORE",
       bold=True, color=CYAN, size=13)
    doc.add_paragraph()

    _rp17 = (cfg or {}).get("reporting", {}).get("docx", {})
    _max_top_actors = _rp17.get("max_topology_actors", 20)
    _max_top_comms  = _rp17.get("max_topology_comms",   8)

    p17s = doc.add_paragraph()
    _sp(p17s)
    _r(p17s,
       f"[TOPOLOGY SCORE: {topology_report.influence_score}/100]  "
       f"Gini={topology_report.pagerank_gini:.3f}  ·  "
       f"{topology_report.total_actors} actors  ·  "
       f"CIB coord={topology_report.coordination_score}/100\n",
       bold=True, color=CYAN, size=10)
    _r(p17s, topology_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    # Command chain + amplifiers inline
    if topology_report.command_chain:
        p17c = doc.add_paragraph()
        _sp(p17c)
        _r(p17c, "COMMAND NODES (highest PageRank + betweenness — narrative controllers): ",
           bold=True, color=RED_MED, size=9)
        _r(p17c, "  ·  ".join(topology_report.command_chain[:8]), color=YELLOW, size=8)
        doc.add_paragraph()
    if topology_report.amplifiers:
        p17a = doc.add_paragraph()
        _sp(p17a)
        _r(p17a, "AMPLIFIERS (high degree, suspect — spreading influence): ",
           bold=True, color=ORANGE, size=9)
        _r(p17a, "  ·  ".join(topology_report.amplifiers[:8]), color=YELLOW, size=8)
        doc.add_paragraph()

    # Top actors table
    if topology_report.actors:
        p17th = doc.add_paragraph()
        _sp(p17th)
        _r(p17th, f"INFLUENCE TOPOLOGY RANKING (top {_max_top_actors})",
           bold=True, color=CYAN, size=10)
        tbl17 = doc.add_table(rows=1, cols=8)
        tbl17.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(["RANK", "ACTOR", "SCORE", "ROLE", "PAGERANK", "BETWEENNESS", "DEGREE", "SUSPECT?"]):
            c = tbl17.cell(0, j)
            _bg(c, "001A3A")
            _r(c.paragraphs[0], h, bold=True, color=CYAN, size=7)
        _role_clr17 = {
            "COMMAND":    RED_MED,
            "AMPLIFIER":  ORANGE,
            "HUB":        YELLOW,
            "BOT_CLUSTER":PURPLE,
            "PERIPHERAL": GRAY,
        }
        for actor in topology_report.actors[:_max_top_actors]:
            rbg   = "1A0808" if actor.role == "COMMAND" else ("0A0A1A" if actor.is_suspect else "050510")
            rc    = _role_clr17.get(actor.role, GRAY)
            row   = tbl17.add_row()
            for j, (txt, clr) in enumerate([
                (f"#{actor.rank}",                       YELLOW),
                (actor.actor[:28],                       WHITE if not actor.is_suspect else RED_MED),
                (f"{actor.influence_score:.1f}/100",     rc),
                (actor.role,                             rc),
                (f"{actor.pagerank:.6f}",                CYAN),
                (f"{actor.betweenness:.4f}",             TEAL),
                (str(actor.degree),                      GRAY),
                ("★ BOT" if actor.is_suspect else "—",  RED_MED if actor.is_suspect else GRAY),
            ]):
                cell = tbl17.rows[-1].cells[j]
                _bg(cell, rbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 2), color=clr, size=7)
        doc.add_paragraph()

    # Community topology
    if topology_report.top_communities:
        p17cm = doc.add_paragraph()
        _sp(p17cm)
        _r(p17cm, f"INFLUENCE COMMUNITIES (top {_max_top_comms} by avg influence × size)",
           bold=True, color=TEAL, size=9)
        cm_tbl = doc.add_table(rows=1, cols=5)
        cm_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(["COMM-ID", "SIZE", "TOP ACTOR", "AVG INFLUENCE", "SUSPECT RATIO"]):
            c = cm_tbl.cell(0, j)
            _bg(c, "001828")
            _r(c.paragraphs[0], h, bold=True, color=TEAL, size=7)
        for comm in topology_report.top_communities[:_max_top_comms]:
            sbg = "1A0A00" if comm.suspect_ratio >= 0.5 else "050518"
            row = cm_tbl.add_row()
            for j, (txt, clr) in enumerate([
                (f"C-{comm.community_id:02d}",      CYAN),
                (str(comm.size),                     YELLOW),
                (comm.top_actor[:28],                WHITE),
                (f"{comm.avg_influence:.1f}/100",    ORANGE if comm.avg_influence >= 60 else TEAL),
                (f"{comm.suspect_ratio:.0%}",        RED_MED if comm.suspect_ratio >= 0.5 else GRAY),
            ]):
                cell = row.cells[j]
                _bg(cell, sbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, color=clr, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 18: HASHTAG WEAPONIZATION DETECTOR ──────────────────────
    doc.add_paragraph()
    _div(doc, "302800")
    p18h = doc.add_paragraph()
    _sp(p18h, "60", "20")
    p18h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(p18h, "#  SECTION 18 — HASHTAG WEAPONIZATION DETECTOR",
       bold=True, color=YELLOW, size=13)
    doc.add_paragraph()

    _max_htags = _rp17.get("max_hashtags", 20)

    p18s = doc.add_paragraph()
    _sp(p18s)
    _r(p18s,
       f"[WEAPONIZATION SCORE: {hashtag_report.weaponization_score}/100]  "
       f"{hashtag_report.total_hashtags} hashtag(s) tracked  ·  "
       f"{len(hashtag_report.weaponized_hashtags)} weaponized  ·  "
       f"{len(hashtag_report.organic_hashtags)} organic\n",
       bold=True, color=YELLOW, size=10)
    _r(p18s, hashtag_report.summary, color=WHITE, size=9)
    doc.add_paragraph()

    # Top seeders
    if hashtag_report.top_seeders:
        p18ts = doc.add_paragraph()
        _sp(p18ts)
        _r(p18ts, "TOP HASHTAG SEEDERS (accounts introducing weaponized tags first): ",
           bold=True, color=ORANGE, size=9)
        _r(p18ts, "  ·  ".join(hashtag_report.top_seeders[:15]), color=YELLOW, size=8)
        doc.add_paragraph()

    # Main hashtag table
    visible_htags = [p for p in hashtag_report.hashtag_profiles if p.weaponized]
    if not visible_htags:
        visible_htags = hashtag_report.hashtag_profiles
    if visible_htags:
        p18th = doc.add_paragraph()
        _sp(p18th)
        _r(p18th, f"HASHTAG PROFILES (top {_max_htags} — sorted by adoption rate)",
           bold=True, color=YELLOW, size=10)
        ht_tbl = doc.add_table(rows=1, cols=8)
        ht_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(["HASHTAG", "LABEL", "USES", "ACTORS", "POSTS", "PEAK/H", "RATE", "FIRST SEEDER"]):
            c = ht_tbl.cell(0, j)
            _bg(c, "1E1800")
            _r(c.paragraphs[0], h, bold=True, color=YELLOW, size=7)
        _ht_label_clr = {
            "RAPID_SEEDING": RED_MED,
            "AMPLIFIED":     ORANGE,
            "ORGANIC":       GRAY,
        }
        for htag in visible_htags[:_max_htags]:
            lc  = _ht_label_clr.get(htag.weaponization_label, GRAY)
            rbg = "1A0A00" if htag.weaponized else "0A0A0A"
            row = ht_tbl.add_row()
            for j, (txt, clr) in enumerate([
                (htag.hashtag[:25],              YELLOW if htag.weaponized else WHITE),
                (htag.weaponization_label,       lc),
                (str(htag.total_uses),           ORANGE),
                (str(htag.unique_actors),        CYAN),
                (str(htag.posts_hit),            TEAL),
                (str(htag.peak_hour_count),      RED_MED if htag.peak_hour_count >= 5 else GRAY),
                (f"{htag.adoption_rate:.1f}x",   RED_MED if htag.adoption_rate >= 3 else ORANGE if htag.adoption_rate >= 1.8 else GRAY),
                (htag.first_actor[:22],          RED_MED if htag.weaponized else GRAY),
            ]):
                cell = row.cells[j]
                _bg(cell, rbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 0 and htag.weaponized), color=clr, size=7)
        doc.add_paragraph()

    # Adoption curve text for top 3 weaponized hashtags
    top_weap = [p for p in hashtag_report.hashtag_profiles if p.weaponized][:3]
    if top_weap:
        p18curve = doc.add_paragraph()
        _sp(p18curve)
        _r(p18curve, "ADOPTION CURVES — TOP WEAPONIZED HASHTAGS:\n",
           bold=True, color=ORANGE, size=9)
        for htag in top_weap:
            _r(p18curve, f"\n  {htag.hashtag}  ", bold=True, color=YELLOW, size=8)
            _r(p18curve, f"(rate={htag.adoption_rate:.1f}x · {htag.unique_actors} actors · seed: {htag.first_actor})\n",
               color=GRAY, size=7)
            curve_pts = htag.adoption_curve[:12]
            for pt in curve_pts:
                bar = "█" * min(pt["count"], 20)
                _r(p18curve, f"    {pt['hour'][11:16]}  {bar}  {pt['count']}\n",
                   color=ORANGE if pt["count"] == htag.peak_hour_count else GRAY, size=7)
        doc.add_paragraph()

    # ── SECTION 19 — ACCOUNT VELOCITY PROFILE ───────────────────────────
    dcfg_v = (cfg or {}).get("reporting", {}).get("docx", {})
    max_vel = dcfg_v.get("max_velocity_actors", 25)
    _div(doc, "0A0012")
    p19h = doc.add_paragraph()
    _sp(p19h)
    _r(p19h, "⚡  SECTION 19 — ACCOUNT VELOCITY PROFILE",
       bold=True, color=YELLOW, size=12)
    _r(p19h, f"   score {velocity_report.velocity_score}/100  ·  "
             f"{velocity_report.total_actors} actors  ·  "
             f"max CPH {velocity_report.max_cph}  ·  "
             f"bot_velocity={len(velocity_report.bot_velocity_actors)}",
       color=GRAY, size=8)
    p19s = doc.add_paragraph()
    _sp(p19s)
    _r(p19s, velocity_report.summary, color=CYAN, size=9)
    doc.add_paragraph()

    vel_actors = velocity_report.profiles[:max_vel]
    if vel_actors:
        vel_hdrs = ["ACTOR", "CPH", "COMMENTS", "POSTS", "SPAN(H)", "LABEL", "SCORE"]
        vel_tbl  = doc.add_table(rows=1, cols=len(vel_hdrs))
        vel_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(vel_hdrs):
            cell = vel_tbl.rows[0].cells[j]
            _bg(cell, "1A001A")
            _sp(cell.paragraphs[0], "15", "15")
            _r(cell.paragraphs[0], h, bold=True, color=YELLOW, size=7)
        for i, vp in enumerate(vel_actors):
            rbg = "100010" if i % 2 == 0 else "0A000A"
            lc  = (RED_MED if vp.velocity_label == "BOT_VELOCITY"
                   else ORANGE if vp.velocity_label == "SUSPICIOUS" else CYAN)
            row = vel_tbl.add_row()
            for j, (txt, clr) in enumerate([
                (vp.actor[:28],               WHITE),
                (f"{vp.cph:.1f}",             RED_MED if vp.cph >= 15 else ORANGE if vp.cph >= 7 else CYAN),
                (str(vp.total_comments),      ORANGE),
                (str(vp.unique_posts),        TEAL),
                (f"{vp.span_hours:.1f}",      GRAY),
                (vp.velocity_label,           lc),
                (str(vp.velocity_score),      RED_MED if vp.velocity_score >= 60 else ORANGE if vp.velocity_score >= 30 else CYAN),
            ]):
                cell = row.cells[j]
                _bg(cell, rbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 0), color=clr, size=7)
        doc.add_paragraph()

    # ── SECTION 20 — CROSS-POST NARRATIVE SEEDING ───────────────────────
    max_seeds  = dcfg_v.get("max_seeds", 15)
    _div(doc, "0A1200")
    p20h = doc.add_paragraph()
    _sp(p20h)
    _r(p20h, "🌱  SECTION 20 — CROSS-POST NARRATIVE SEEDING",
       bold=True, color=GREEN, size=12)
    _r(p20h, f"   score {seeding_report.propagation_score}/100  ·  "
             f"seeded narratives={seeding_report.total_seeded}  ·  "
             f"cross-post actors={len(seeding_report.cross_post_actors)}",
       color=GRAY, size=8)
    p20s = doc.add_paragraph()
    _sp(p20s)
    _r(p20s, seeding_report.summary, color=GREEN, size=9)

    if seeding_report.cross_post_actors:
        doc.add_paragraph()
        p20cp = doc.add_paragraph()
        _sp(p20cp)
        _r(p20cp, "CROSS-POST ACTORS (3+ posts):  ", bold=True, color=ORANGE, size=9)
        _r(p20cp, "  ·  ".join(seeding_report.cross_post_actors[:12]), color=WHITE, size=8)

    top_seeds = seeding_report.seeds[:max_seeds]
    if top_seeds:
        doc.add_paragraph()
        seed_hdrs = ["NARRATIVE (first 55 chars)", "SEED ACCOUNT", "POSTS", "ACTORS", "SPREAD"]
        seed_tbl  = doc.add_table(rows=1, cols=len(seed_hdrs))
        seed_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(seed_hdrs):
            cell = seed_tbl.rows[0].cells[j]
            _bg(cell, "001500")
            _sp(cell.paragraphs[0], "15", "15")
            _r(cell.paragraphs[0], h, bold=True, color=GREEN, size=7)
        for i, seed in enumerate(top_seeds):
            rbg = "001200" if i % 2 == 0 else "000D00"
            row = seed_tbl.add_row()
            for j, (txt, clr) in enumerate([
                (seed.key[:55],              YELLOW),
                (seed.first_actor[:22],      RED_MED if seed.propagation_count >= 3 else ORANGE),
                (str(seed.unique_posts),     RED_MED if seed.unique_posts >= 5 else ORANGE),
                (str(seed.unique_actors),    CYAN),
                (str(seed.propagation_count), RED_MED if seed.propagation_count >= 3 else TEAL),
            ]):
                cell = row.cells[j]
                _bg(cell, rbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 0), color=clr, size=7)
        doc.add_paragraph()

    # ── SECTION 21 — CROSS-POST TIME CORRELATION ────────────────────────
    max_cpairs = dcfg_v.get("max_cross_pairs", 15)
    _div(doc, "120A00")
    p21h = doc.add_paragraph()
    _sp(p21h)
    _r(p21h, "🔗  SECTION 21 — CROSS-POST TIME CORRELATION",
       bold=True, color=ORANGE, size=12)
    _r(p21h, f"   score {correlation_report.correlation_score}/100  ·  "
             f"{correlation_report.total_pairs} pairs analyzed  ·  "
             f"max Jaccard={correlation_report.max_jaccard:.3f}  ·  "
             f"mean={correlation_report.mean_jaccard:.3f}",
       color=GRAY, size=8)
    p21s = doc.add_paragraph()
    _sp(p21s)
    _r(p21s, correlation_report.summary, color=ORANGE, size=9)
    doc.add_paragraph()

    top_cpairs = [p for p in correlation_report.top_pairs if p.label != "LOW"][:max_cpairs]
    if top_cpairs:
        cp_hdrs = ["POST A (truncated)", "POST B (truncated)", "SHARED", "A", "B", "JACCARD", "LABEL"]
        cp_tbl  = doc.add_table(rows=1, cols=len(cp_hdrs))
        cp_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(cp_hdrs):
            cell = cp_tbl.rows[0].cells[j]
            _bg(cell, "1A0A00")
            _sp(cell.paragraphs[0], "15", "15")
            _r(cell.paragraphs[0], h, bold=True, color=ORANGE, size=7)
        for i, cp in enumerate(top_cpairs):
            rbg = "120800" if i % 2 == 0 else "0D0500"
            lc  = RED_MED if cp.label == "HIGH" else YELLOW if cp.label == "MEDIUM" else GRAY
            row = cp_tbl.add_row()
            a_short = (cp.post_a.split("/")[-1] or cp.post_a)[:30]
            b_short = (cp.post_b.split("/")[-1] or cp.post_b)[:30]
            for j, (txt, clr) in enumerate([
                (a_short,                WHITE),
                (b_short,                WHITE),
                (str(cp.shared_actors),  RED_MED if cp.shared_actors >= 10 else ORANGE),
                (str(cp.actors_a),       GRAY),
                (str(cp.actors_b),       GRAY),
                (f"{cp.jaccard:.3f}",    RED_MED if cp.jaccard >= 0.35 else ORANGE),
                (cp.label,               lc),
            ]):
                cell = row.cells[j]
                _bg(cell, rbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 6 and cp.label == "HIGH"), color=clr, size=7)
        doc.add_paragraph()

    # ── SECTION 22 — BOT OPERATOR ATTRIBUTION ───────────────────────────
    max_ops = dcfg_v.get("max_operators", 12)
    _div(doc, "1A0010")
    p22h = doc.add_paragraph()
    _sp(p22h)
    _r(p22h, "🕵  SECTION 22 — BOT OPERATOR ATTRIBUTION",
       bold=True, color=PURPLE, size=12)
    _r(p22h, f"   score {attribution_report.attribution_score}/100  ·  "
             f"{attribution_report.total_operators} operator(s)  ·  "
             f"bots tracked={attribution_report.total_bots}  ·  "
             f"edges={attribution_report.bipartite_edges}",
       color=GRAY, size=8)
    p22s = doc.add_paragraph()
    _sp(p22s)
    _r(p22s, attribution_report.summary, color=PURPLE, size=9)
    doc.add_paragraph()

    op_list = attribution_report.operators[:max_ops]
    if op_list:
        op_hdrs = ["OPERATOR", "LABEL", "BOTS", "CO-POSTS", "EXCLUSIVITY", "CONFIDENCE", "TOP BOTS"]
        op_tbl  = doc.add_table(rows=1, cols=len(op_hdrs))
        op_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(op_hdrs):
            cell = op_tbl.rows[0].cells[j]
            _bg(cell, "1A001A")
            _sp(cell.paragraphs[0], "15", "15")
            _r(cell.paragraphs[0], h, bold=True, color=PURPLE, size=7)
        for i, op in enumerate(op_list):
            rbg = "100010" if i % 2 == 0 else "0A000A"
            lc  = (RED_MED if op.operation_label == "CONFIRMED"
                   else ORANGE if op.operation_label == "LIKELY" else YELLOW)
            top_bots_str = ", ".join(op.attributed_bots[:3])
            row = op_tbl.add_row()
            for j, (txt, clr) in enumerate([
                (op.operator[:25],            WHITE),
                (op.operation_label,          lc),
                (str(len(op.attributed_bots)), RED_MED),
                (str(op.unique_co_posts),     ORANGE),
                (f"{op.bot_exclusivity:.2f}", TEAL),
                (str(op.confidence),          RED_MED if op.confidence >= 70 else ORANGE),
                (top_bots_str[:35],           GRAY),
            ]):
                cell = row.cells[j]
                _bg(cell, rbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 0), color=clr, size=7)
        doc.add_paragraph()

    # ── SECTION 23 — TROLLHUNTER: MEXICAN POLITICAL CIB DETECTOR ─────────────
    dcfg_th   = (cfg or {}).get("reporting", {}).get("docx", {})
    max_th    = dcfg_th.get("max_troll_profiles", 30)
    _div(doc, "1A0600")
    p23h = doc.add_paragraph()
    _sp(p23h)
    _r(p23h, "🎯  SECTION 23 — TROLLHUNTER: MEXICAN POLITICAL CIB DETECTOR",
       bold=True, color=RED_MED, size=12)
    _r(p23h, f"   score {troll_report.bot_risk_score}/100  ·  "
             f"{troll_report.total_analyzed} actors  ·  "
             f"confirmed={len(troll_report.confirmed_bots)}  ·  "
             f"high_risk={len(troll_report.high_risk)}  ·  "
             f"foreign_names={len(troll_report.foreign_names)}  ·  "
             f"page_operators={len(troll_report.page_operators)}",
       color=GRAY, size=8)
    p23s = doc.add_paragraph()
    _sp(p23s)
    _r(p23s, troll_report.summary, color=RED_MED, size=9)

    # Summary panels: foreign names + page operators + multi-page ops
    if troll_report.foreign_names:
        doc.add_paragraph()
        p23fn = doc.add_paragraph()
        _sp(p23fn)
        _r(p23fn, "⚠ FOREIGN-NAME ACCOUNTS (bot farm indicator):  ",
           bold=True, color=ORANGE, size=9)
        _r(p23fn, "  ·  ".join(troll_report.foreign_names[:15]), color=YELLOW, size=8)

    if troll_report.page_operators:
        doc.add_paragraph()
        p23po = doc.add_paragraph()
        _sp(p23po)
        _r(p23po, "📄 PAGE ACCOUNTS (not personal profiles):  ",
           bold=True, color=CYAN, size=9)
        _r(p23po, "  ·  ".join(troll_report.page_operators[:12]), color=WHITE, size=8)

    if troll_report.multi_page_ops:
        doc.add_paragraph()
        p23mp = doc.add_paragraph()
        _sp(p23mp)
        _r(p23mp, "🔗 MULTI-PAGE OPERATORS (one identity, multiple accounts):  ",
           bold=True, color=PURPLE, size=9)
        _r(p23mp, "  ·  ".join(troll_report.multi_page_ops[:8]), color=WHITE, size=8)

    doc.add_paragraph()

    # Main forensic table
    th_profiles = troll_report.profiles[:max_th]
    if th_profiles:
        th_hdrs = ["ACTOR", "RISK", "CLASS", "SIGNALS", "CPH", "POSTS", "ATTACK%", "TOP EVIDENCE"]
        th_tbl  = doc.add_table(rows=1, cols=len(th_hdrs))
        th_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(th_hdrs):
            cell = th_tbl.rows[0].cells[j]
            _bg(cell, "200500")
            _sp(cell.paragraphs[0], "15", "15")
            _r(cell.paragraphs[0], h, bold=True, color=RED_MED, size=7)

        clr_map = {
            "CONFIRMED_BOT": ("3D0000", RED_MED),
            "HIGH_RISK":     ("2A1000", ORANGE),
            "SUSPICIOUS":    ("2A2000", YELLOW),
            "LIKELY_HUMAN":  ("001030", CYAN),
            "HUMAN":         ("002010", GREEN),
        }
        for i, tp in enumerate(th_profiles):
            bg_base, lc = clr_map.get(tp.classification, ("0A0000", GRAY))
            rbg = bg_base if i % 2 == 0 else "0A0000"
            top_sig = sorted(tp.signals, key=lambda s: {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3}.get(s.severity,4))
            top_ev  = top_sig[0].label if top_sig else "—"
            sig_codes = ", ".join(s.code.replace("_","") for s in top_sig[:3])
            row = th_tbl.add_row()
            for j, (txt, clr) in enumerate([
                (tp.actor[:26],                   WHITE),
                (str(tp.bot_risk_score),          RED_MED if tp.bot_risk_score >= 60 else ORANGE if tp.bot_risk_score >= 40 else CYAN),
                (tp.classification[:15],          lc),
                (sig_codes[:20],                  ORANGE),
                (f"{tp.cph:.1f}" if tp.cph else "—",  RED_MED if tp.cph >= 15 else ORANGE if tp.cph >= 7 else GRAY),
                (str(tp.posts_attacked),          RED_MED if tp.posts_attacked >= 5 else ORANGE),
                (f"{tp.attack_ratio:.0%}",        RED_MED if tp.attack_ratio >= 0.8 else ORANGE if tp.attack_ratio >= 0.5 else GRAY),
                (top_ev[:30],                     lc),
            ]):
                cell = row.cells[j]
                _bg(cell, rbg)
                _sp(cell.paragraphs[0], "15", "15")
                _r(cell.paragraphs[0], txt, bold=(j == 0), color=clr, size=7)
        doc.add_paragraph()

    # Forensic evidence cards for top confirmed bots
    top_confirmed = [p for p in th_profiles if p.classification in ("CONFIRMED_BOT", "HIGH_RISK")][:6]
    if top_confirmed:
        p23ev = doc.add_paragraph()
        _sp(p23ev)
        _r(p23ev, "FORENSIC EVIDENCE — TOP FLAGGED ACTORS:\n",
           bold=True, color=RED_MED, size=9)
        for tp in top_confirmed:
            _r(p23ev, f"\n  ► {tp.actor}  [{tp.classification}  {tp.bot_risk_score}/100]\n",
               bold=True, color=RED_MED if tp.classification == "CONFIRMED_BOT" else ORANGE, size=8)
            for s in sorted(tp.signals, key=lambda x: {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3}.get(x.severity,4))[:4]:
                sev_icon = {"CRITICAL":"⛔","HIGH":"🔴","MEDIUM":"🟡","LOW":"⚪"}.get(s.severity,"•")
                detail_short = s.detail[:110] + ("…" if len(s.detail) > 110 else "")
                _r(p23ev, f"    {sev_icon} [{s.code}] {s.label}: {detail_short}\n",
                   color=ORANGE if s.severity == "CRITICAL" else YELLOW if s.severity == "HIGH" else GRAY,
                   size=7)
            if tp.comment_sample:
                _r(p23ev, f"    SAMPLE: \"{tp.comment_sample[0][:80]}\"\n",
                   color=GRAY, size=7, italic=True)
        doc.add_paragraph()

    # ── SECCIÓN 24: ENGAGEMENT ANOMALY INDEX ─────────────────────────────────
    _div(doc, "1e3a5f")
    p24h = doc.add_paragraph()
    _sp(p24h)
    _h1(doc, "SECTION 24 — ENGAGEMENT ANOMALY INDEX")
    p24s = doc.add_paragraph()
    _sp(p24s)
    _r(p24s, f"   anomaly_score {engagement_report.anomaly_score}/100  ·  "
             f"{engagement_report.total_analyzed} posts analyzed  ·  "
             f"baseline ratio {engagement_report.baseline_ratio:.1f}x  ·  "
             f"bot_boosted={len(engagement_report.bot_boosted)}  ·  "
             f"suspicious={len(engagement_report.suspicious)}  ·  "
             f"ghost={len(engagement_report.ghost_posts)}",
       color=CYAN, size=9)
    p24sum = doc.add_paragraph()
    _sp(p24sum)
    _r(p24sum, engagement_report.summary, color=WHITE, size=9)

    max_eng = cfg.get("reporting", {}).get("docx", {}).get("max_engagement_posts", 15)
    eng_posts = engagement_report.posts[:max_eng]
    if eng_posts:
        # Classification color map
        eng_colors = {
            "BOT_BOOSTED": "ff4444", "GHOST": "ff6600",
            "SUSPICIOUS": "ffaa00", "AMPLIFIED": "44aaff", "ORGANIC": "888888",
        }
        tbl24 = doc.add_table(rows=1, cols=5)
        tbl24.style = "Table Grid"
        for i, hd in enumerate(["SOURCE", "CLASSIFICATION", "RATIO", "R/C/S", "POST PREVIEW"]):
            _bg(tbl24.rows[0].cells[i], "1e3a5f")
            _r(tbl24.rows[0].cells[i].paragraphs[0], hd, bold=True, color=WHITE, size=8)
        for ep in eng_posts:
            row = tbl24.add_row()
            cls_color = _hex_to_rgb(eng_colors.get(ep.classification, "888888"))
            _r(row.cells[0].paragraphs[0], ep.source[:22], color=WHITE, size=7)
            _r(row.cells[1].paragraphs[0], ep.classification, bold=True,
               color=cls_color, size=7)
            _r(row.cells[2].paragraphs[0], f"{ep.ratio:.1f}x (+{ep.deviation_pct:.0f}%)",
               color=ORANGE if ep.anomaly_score > 40 else YELLOW, size=7)
            _r(row.cells[3].paragraphs[0],
               f"R:{ep.reactions} C:{ep.comments} S:{ep.shares}", color=GRAY, size=7)
            _r(row.cells[4].paragraphs[0], ep.text_preview[:60], color=WHITE, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 25: EMOTIONAL CONTAGION SCORE ────────────────────────────────
    _div(doc, "3d1a2a")
    p25h = doc.add_paragraph()
    _sp(p25h)
    _h1(doc, "SECTION 25 — EMOTIONAL CONTAGION SCORE")
    p25s = doc.add_paragraph()
    _sp(p25s)
    dir_color = _hex_to_rgb({"NEGATIVE": "ff4444", "POSITIVE": "44ff88",
                             "MIXED": "ffaa00", "NONE": "888888"}.get(contagion_report.shift_direction, "888888"))
    _r(p25s, f"   contagion_score {contagion_report.contagion_score}/100  ·  "
             f"bot_arrival={contagion_report.bot_arrival_ts or 'N/A'}  ·  "
             f"affected={contagion_report.affected_posts}/{len(contagion_report.posts)}  ·  "
             f"direction=",
       color=CYAN, size=9)
    _r(p25s, contagion_report.shift_direction, bold=True, color=dir_color, size=9)

    p25sum = doc.add_paragraph()
    _sp(p25sum)
    _r(p25sum, contagion_report.summary, color=WHITE, size=9)

    # PRE / DURING / POST aggregate sentiment table
    def _fmt_window(w: dict) -> str:
        if not w:
            return "N/A"
        return (f"neg={w.get('neg',0):.2f} agg={w.get('agg',0):.2f} "
                f"pos={w.get('pos',0):.2f} ({w.get('comments',0)} comments)")

    p25agg = doc.add_paragraph()
    _sp(p25agg)
    _r(p25agg, "AGGREGATE SENTIMENT SHIFT:\n", bold=True, color=YELLOW, size=9)
    _r(p25agg, f"  PRE-BOT   : {_fmt_window(contagion_report.pre_bot_sentiment)}\n",
       color=GRAY, size=8)
    _r(p25agg, f"  DURING    : {_fmt_window(contagion_report.during_bot_sentiment)}\n",
       color=ORANGE, size=8)
    _r(p25agg, f"  POST-BOT  : {_fmt_window(contagion_report.post_bot_sentiment)}\n",
       color=RED_MED if contagion_report.shift_direction == "NEGATIVE" else WHITE, size=8)

    # Top contaminated posts
    max_cont = cfg.get("reporting", {}).get("docx", {}).get("max_contagion_posts", 8)
    cont_posts = [p for p in contagion_report.posts if p.contagion_confirmed][:max_cont]
    if cont_posts:
        p25ev = doc.add_paragraph()
        _sp(p25ev)
        _r(p25ev, "MOST CONTAMINATED THREADS:\n", bold=True, color=RED_MED, size=9)
        for cp in cont_posts:
            shift_icon = "⬆️" if cp.shift_magnitude > 0 else "⬇️"
            _r(p25ev,
               f"\n  {shift_icon} {cp.source[:28]:<28}  "
               f"shift={cp.shift_magnitude:+.2f}  ",
               bold=True,
               color=RED_MED if cp.shift_magnitude > 0.2 else ORANGE, size=8)
            windows = []
            if cp.pre_bot:
                windows.append(f"PRE:{cp.pre_bot.dominant}({cp.pre_bot.comment_count})")
            if cp.during_bot:
                windows.append(f"DURING:{cp.during_bot.dominant}({cp.during_bot.comment_count})")
            if cp.post_bot:
                windows.append(f"POST:{cp.post_bot.dominant}({cp.post_bot.comment_count})")
            _r(p25ev, " → ".join(windows) + "\n", color=GRAY, size=7)
            if cp.peak_agg_comment:
                _r(p25ev,
                   f"    PEAK AGGRESSIVE: \"{cp.peak_agg_comment[:100]}\"\n",
                   color=GRAY, size=7, italic=True)
        doc.add_paragraph()

    # ── SECCIÓN 26: REPLY-CHAIN HIJACK DETECTOR ──────────────────────────────
    _div(doc, "1a3a1a")
    _h1(doc, "SECTION 26 — REPLY-CHAIN HIJACK DETECTOR")
    p26s = doc.add_paragraph()
    _sp(p26s)
    _r(p26s, f"   hijack_score {reply_report.hijack_score}/100  ·  "
             f"{len(reply_report.hijacked_posts)} thread(s) hijacked  ·  "
             f"{reply_report.total_targeted} organic comment(s) targeted  ·  "
             f"career_hijackers={len(reply_report.career_hijackers)}",
       color=CYAN, size=9)
    p26sum = doc.add_paragraph()
    _sp(p26sum)
    _r(p26sum, reply_report.summary, color=WHITE, size=9)

    if reply_report.career_hijackers:
        p26ch = doc.add_paragraph()
        _sp(p26ch)
        _r(p26ch, "CAREER HIJACKERS (3+ posts):  ", bold=True, color=RED_MED, size=9)
        _r(p26ch, "  ·  ".join(reply_report.career_hijackers[:10]), color=ORANGE, size=8)

    max_rp = cfg.get("reporting", {}).get("docx", {}).get("max_reply_posts", 10)
    hijack_posts = reply_report.posts[:max_rp]
    if hijack_posts:
        atk_colors = {"TEMPORAL":"fab387","MENTION":"cba6f7","SATURATION":"f38ba8"}
        tbl26 = doc.add_table(rows=1, cols=4)
        tbl26.style = "Table Grid"
        for i, hd in enumerate(["SOURCE", "HIJACK TYPE", "TARGETED", "BOT ATTACKERS"]):
            _bg(tbl26.rows[0].cells[i], "1a3a1a")
            _r(tbl26.rows[0].cells[i].paragraphs[0], hd, bold=True, color=WHITE, size=8)
        for hp in hijack_posts:
            for tc in hp.targeted_comments[:2]:
                row = tbl26.add_row()
                _r(row.cells[0].paragraphs[0], hp.source[:22], color=WHITE, size=7)
                _r(row.cells[1].paragraphs[0], tc.attack_type, bold=True,
                   color=_hex_to_rgb(atk_colors.get(tc.attack_type, "888888")), size=7)
                _r(row.cells[2].paragraphs[0],
                   f"{tc.organic_author[:20]}  (Δ{tc.attack_delta_s:.0f}s)",
                   color=YELLOW, size=7)
                _r(row.cells[3].paragraphs[0],
                   ", ".join(tc.bot_attackers[:4]) + (
                       f"… +{tc.reply_count-4}" if tc.reply_count > 4 else ""),
                   color=ORANGE, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 27: CROSS-CAMPAIGN ACTOR PERSISTENCE ─────────────────────────
    _div(doc, "3a1a3a")
    _h1(doc, "SECTION 27 — CROSS-CAMPAIGN ACTOR PERSISTENCE")
    p27s = doc.add_paragraph()
    _sp(p27s)
    _r(p27s, f"   persistence_score {cross_campaign_report.persistence_score}/100  ·  "
             f"{cross_campaign_report.total_tracked} actors in registry  ·  "
             f"{cross_campaign_report.campaigns_count} campaign(s)  ·  "
             f"professional={len(cross_campaign_report.professional)}  ·  "
             f"persistent={len(cross_campaign_report.persistent)}  ·  "
             f"new_this_session={cross_campaign_report.new_discoveries}",
       color=CYAN, size=9)
    p27sum = doc.add_paragraph()
    _sp(p27sum)
    _r(p27sum, cross_campaign_report.summary, color=WHITE, size=9)

    cls_colors = {
        "PROFESSIONAL": "f38ba8", "PERSISTENT": "fab387",
        "RECURRING": "f9e2af", "NEW": "6c7086",
    }
    max_cc = cfg.get("reporting", {}).get("docx", {}).get("max_cross_actors", 20)
    cc_actors = cross_campaign_report.actors[:max_cc]
    if cc_actors:
        tbl27 = doc.add_table(rows=1, cols=5)
        tbl27.style = "Table Grid"
        for i, hd in enumerate(["ACTOR", "CLASS", "CAMPAIGNS", "AVG BOT SCORE", "TARGETS"]):
            _bg(tbl27.rows[0].cells[i], "3a1a3a")
            _r(tbl27.rows[0].cells[i].paragraphs[0], hd, bold=True, color=WHITE, size=8)
        for ca in cc_actors:
            row = tbl27.add_row()
            _r(row.cells[0].paragraphs[0], ca.name[:28], color=WHITE, size=7)
            _r(row.cells[1].paragraphs[0], ca.classification, bold=True,
               color=_hex_to_rgb(cls_colors.get(ca.classification, "888888")), size=7)
            _r(row.cells[2].paragraphs[0], str(ca.campaign_count),
               color=RED_MED if ca.campaign_count >= 5 else ORANGE, size=7)
            _r(row.cells[3].paragraphs[0], f"{ca.avg_bot_score:.0f}/100",
               color=RED_MED if ca.avg_bot_score >= 80 else YELLOW, size=7)
            _r(row.cells[4].paragraphs[0],
               " · ".join(ca.campaigns[:4]) + (
                   f"…+{ca.campaign_count-4}" if ca.campaign_count > 4 else ""),
               color=GRAY, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 28: DARK AMPLIFICATION TRACKER ───────────────────────────────
    _div(doc, "0d1a2e")
    _h1(doc, "SECTION 28 — DARK AMPLIFICATION TRACKER")
    p28s = doc.add_paragraph()
    _sp(p28s)
    _r(p28s, f"   amp_score {dark_amp_report.amp_score}/100  ·  "
             f"{dark_amp_report.total_analyzed} posts analyzed  ·  "
             f"baseline {dark_amp_report.baseline_velocity:.0f} eng/h  ·  "
             f"dark_amp={len(dark_amp_report.dark_amplified)}  ·  "
             f"suspicious={len(dark_amp_report.suspicious)}",
       color=CYAN, size=9)
    p28sum = doc.add_paragraph()
    _sp(p28sum)
    _r(p28sum, dark_amp_report.summary, color=WHITE, size=9)

    max_da = cfg.get("reporting", {}).get("docx", {}).get("max_dark_amp_posts", 15)
    da_posts = dark_amp_report.events[:max_da]
    if da_posts:
        cls_colors_da = {
            "DARK_AMP":"f38ba8", "SUSPICIOUS":"f9e2af",
            "VIRAL_GENUINE":"89b4fa", "ORGANIC":"6c7086",
        }
        tbl28 = doc.add_table(rows=1, cols=6)
        tbl28.style = "Table Grid"
        for i, hd in enumerate(["SOURCE", "CLASS", "AMP FACTOR", "VELOCITY", "PURITY", "AGE"]):
            _bg(tbl28.rows[0].cells[i], "0d1a2e")
            _r(tbl28.rows[0].cells[i].paragraphs[0], hd, bold=True, color=WHITE, size=8)
        for ev in da_posts:
            row = tbl28.add_row()
            cc = _hex_to_rgb(cls_colors_da.get(ev.classification, "888888"))
            _r(row.cells[0].paragraphs[0], ev.source[:20], color=WHITE, size=7)
            _r(row.cells[1].paragraphs[0], ev.classification, bold=True, color=cc, size=7)
            _r(row.cells[2].paragraphs[0], f"{ev.amplification_factor:.1f}x",
               color=RED_MED if ev.amplification_factor >= 5 else ORANGE, size=7)
            _r(row.cells[3].paragraphs[0], f"{ev.velocity:.0f}/h", color=YELLOW, size=7)
            _r(row.cells[4].paragraphs[0], f"{ev.reaction_purity:.0%}",
               color=RED_MED if ev.reaction_purity >= 0.85 else GRAY, size=7)
            _r(row.cells[5].paragraphs[0], f"{ev.age_hours:.1f}h", color=GRAY, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 29: BOT FARM SHIFT DETECTOR ──────────────────────────────────
    _div(doc, "1a1a0d")
    _h1(doc, "SECTION 29 — BOT FARM SHIFT DETECTOR")
    p29s = doc.add_paragraph()
    _sp(p29s)
    _r(p29s, f"   shift_score {shift_report.shift_score}/100  ·  "
             f"{len(shift_report.cohorts)} time windows  ·  "
             f"confirmed_shifts={shift_report.confirmed_shifts}  ·  "
             f"actors_rotated={shift_report.total_rotated}  ·  "
             f"timeline: {(shift_report.timeline_start or '')[:16]} → {(shift_report.timeline_end or '')[:16]}",
       color=CYAN, size=9)
    p29sum = doc.add_paragraph()
    _sp(p29sum)
    _r(p29sum, shift_report.summary, color=WHITE, size=9)

    conf_colors = {"HIGH":"f38ba8","MEDIUM":"fab387","LOW":"f9e2af"}
    max_sh = cfg.get("reporting", {}).get("docx", {}).get("max_shift_events", 8)
    shift_events = shift_report.shift_events[:max_sh]
    if shift_events:
        p29ev = doc.add_paragraph()
        _sp(p29ev)
        _r(p29ev, "DETECTED SHIFT EVENTS:\n", bold=True, color=YELLOW, size=9)
        for se in shift_events:
            cc = _hex_to_rgb(conf_colors.get(se.confidence, "888888"))
            _r(p29ev,
               f"\n  ⚡ [{se.confidence}] shift score {se.shift_score}/100  "
               f"jaccard={se.jaccard_overlap:.2f}  turnover={se.turnover_pct:.0%}  "
               f"naming_sim={se.naming_sim:.0%}\n",
               bold=True, color=cc, size=8)
            _r(p29ev,
               f"     FROM: {se.from_cohort.window_end[:16]}  "
               f"{len(se.from_cohort.bot_actors)} bots  "
               f"density={se.from_cohort.bot_pct:.0%}  "
               f"patterns={', '.join(se.from_cohort.naming_patterns[:2]) or 'none'}\n",
               color=GRAY, size=7)
            _r(p29ev,
               f"      TO:  {se.to_cohort.window_start[:16]}  "
               f"{len(se.to_cohort.bot_actors)} bots  "
               f"density={se.to_cohort.bot_pct:.0%}  "
               f"patterns={', '.join(se.to_cohort.naming_patterns[:2]) or 'none'}\n",
               color=GRAY, size=7)
        doc.add_paragraph()

    # ── SECCIÓN 30: IDENTITY PERSISTENCE TRACKER ─────────────────────────────
    _div(doc, "0d0d2e")
    _h1(doc, "SECTION 30 — IDENTITY PERSISTENCE TRACKER")
    p30s = doc.add_paragraph()
    _sp(p30s)
    _r(p30s, f"   persistence_score {identity_report.persistence_score}/100  ·  "
             f"{identity_report.total_fingerprinted} actors fingerprinted  ·  "
             f"unique_operators={identity_report.unique_operators}  ·  "
             f"confirmed_morphs={len(identity_report.confirmed_morphs)}  ·  "
             f"probable_morphs={len(identity_report.probable_morphs)}",
       color=CYAN, size=9)
    p30sum = doc.add_paragraph()
    _sp(p30sum)
    _r(p30sum, identity_report.summary, color=WHITE, size=9)

    conf_colors_id = {"CONFIRMED_MORPH":"f38ba8","PROBABLE_MORPH":"fab387","POSSIBLE_MORPH":"f9e2af"}
    max_id = cfg.get("reporting", {}).get("docx", {}).get("max_identity_morphs", 12)
    id_morphs = identity_report.morphs[:max_id]
    if id_morphs:
        p30ev = doc.add_paragraph()
        _sp(p30ev)
        _r(p30ev, "IDENTITY MORPH DETECTIONS:\n", bold=True, color=YELLOW, size=9)
        for m in id_morphs:
            cc = _hex_to_rgb(conf_colors_id.get(m.confidence, "888888"))
            _r(p30ev,
               f"\n  🧬 [{m.confidence}]  sim={m.similarity:.3f}\n",
               bold=True, color=cc, size=8)
            _r(p30ev,
               f"     CURRENT: '{m.actor_a}' ({m.campaign_a})\n"
               f"    PREVIOUS: '{m.actor_b}' ({m.campaign_b})\n",
               color=GRAY, size=7)
            _r(p30ev, f"     {m.evidence[:200]}\n", color=GRAY, size=7, italic=True)
        doc.add_paragraph()

    # ── SECCIÓN 31: NARRATIVE MUTATION TRACKER ────────────────────────────────
    _div(doc, "2e0d0d")
    _h1(doc, "SECTION 31 — NARRATIVE MUTATION TRACKER")
    p31s = doc.add_paragraph()
    _sp(p31s)
    _r(p31s, f"   mutation_score {mutation_report.mutation_score}/100  ·  "
             f"{len(mutation_report.mutations)} mutation(s)  ·  "
             f"pivot={mutation_report.pivot_events}  ·  "
             f"expansion={mutation_report.expansion_events}  ·  "
             f"injection={mutation_report.injection_events}  ·  "
             f"mutator='{mutation_report.most_active_mutator or 'none'}'",
       color=CYAN, size=9)
    p31sum = doc.add_paragraph()
    _sp(p31sum)
    _r(p31sum, mutation_report.summary, color=WHITE, size=9)

    if mutation_report.seed_narrative:
        p31nar = doc.add_paragraph()
        _sp(p31nar)
        _r(p31nar, "NARRATIVE EVOLUTION:\n", bold=True, color=YELLOW, size=9)
        _r(p31nar, f"  SEED:  [{', '.join(mutation_report.seed_narrative[:6])}]\n",
           color=GRAY, size=8)
        _r(p31nar, f"  FINAL: [{', '.join(mutation_report.final_narrative[:6])}]\n",
           color=WHITE if mutation_report.seed_narrative != mutation_report.final_narrative else GRAY,
           size=8)

    mut_type_colors = {
        "PIVOT":"f38ba8","INJECTION":"cba6f7","EXPANSION":"fab387",
        "AMPLIFICATION":"f9e2af","CONVERGENCE":"89b4fa",
    }
    max_mt = cfg.get("reporting", {}).get("docx", {}).get("max_mutations", 8)
    for me in mutation_report.mutations[:max_mt]:
        p31m = doc.add_paragraph()
        _sp(p31m)
        cc = _hex_to_rgb(mut_type_colors.get(me.mutation_type, "888888"))
        _r(p31m,
           f"  ⚡ [{me.mutation_type}] score={me.mutation_score}/100  "
           f"similarity_drop={me.similarity_drop:.2f}  "
           f"introducer='{me.mutation_introducer}'  "
           f"adoption={me.adoption_count} actors\n",
           bold=True, color=cc, size=8)
        if me.new_terms:
            _r(p31m, f"     + NEW: {', '.join(me.new_terms[:6])}\n", color=YELLOW, size=7)
        if me.dropped_terms:
            _r(p31m, f"     - DROPPED: {', '.join(me.dropped_terms[:4])}\n", color=GRAY, size=7)
    if mutation_report.mutations:
        doc.add_paragraph()

    # ── SECCIÓN 32: UNIFIED CIB CONFIDENCE SCORE ─────────────────────────────
    _div(doc, "0d2b0d")
    _h1(doc, "SECTION 32 — UNIFIED CIB CONFIDENCE SCORE")
    p32s = doc.add_paragraph()
    _sp(p32s)
    label_colors = {
        "CONFIRMED_CIB":    "f38ba8",
        "HIGH_CONFIDENCE":  "fab387",
        "PROBABLE":         "f9e2af",
        "POSSIBLE":         "89b4fa",
        "ORGANIC":          "6c7086",
    }
    lc = _hex_to_rgb(label_colors.get(cib_score_report.confidence_label, "888888"))
    _r(p32s, f"   SCORE: ", color=CYAN, size=11, bold=True)
    _r(p32s, f"{cib_score_report.overall_score:.0f} / 100", color=WHITE, size=14, bold=True)
    _r(p32s, f"   →  ", color=GRAY, size=11)
    _r(p32s, cib_score_report.confidence_label, color=lc, size=12, bold=True)
    _r(p32s, f"   ({cib_score_report.engines_present} engines)", color=GRAY, size=9)

    p32nar = doc.add_paragraph()
    _sp(p32nar)
    _r(p32nar, cib_score_report.narrative, color=WHITE, size=9)

    if cib_score_report.top_signals:
        p32sig = doc.add_paragraph()
        _sp(p32sig)
        _r(p32sig, "TOP EVIDENCE SIGNALS:\n", bold=True, color=YELLOW, size=9)
        for sig in cib_score_report.top_signals:
            _r(p32sig, f"  ▸ {sig}\n", color=WHITE, size=8)

    if cib_score_report.dimensions:
        p32dim = doc.add_paragraph()
        _sp(p32dim)
        _r(p32dim, "DIMENSION BREAKDOWN:\n", bold=True, color=CYAN, size=9)
        for dim in cib_score_report.dimensions:
            bar_len = int(dim.score / 10)
            bar     = "█" * bar_len + "░" * (10 - bar_len)
            dc = _hex_to_rgb(label_colors.get(
                "CONFIRMED_CIB" if dim.score >= 80 else
                "HIGH_CONFIDENCE" if dim.score >= 60 else
                "PROBABLE" if dim.score >= 40 else
                "POSSIBLE" if dim.score >= 20 else "ORGANIC",
                "6c7086"
            ))
            _r(p32dim,
               f"  [{bar}] {dim.score:5.1f}/100  {dim.label:<22} "
               f"w={dim.weight:.3f}  contrib={dim.contribution:.1f}\n",
               color=dc, size=7)
    doc.add_paragraph()

    # ── SECCIÓN 33: CADENAS DE EVIDENCIA FORENSE (Confidence Chain) ───────────
    from engines.confidence_chain_engine import ConfidenceChainEngine
    chain_report = ConfidenceChainEngine(cfg=cfg).analyze(
        troll_report          = troll_report,
        temporal_report       = temporal_report,
        stylo_report          = stylo_report,
        hcs_report            = hcs_report,
        velocity_report       = velocity_report,
        cross_campaign_report = cross_campaign_report,
        identity_report       = identity_report,
        reply_report          = reply_report,
        shift_report          = shift_report,
    )
    if chain_report.chains:
        _div(doc, "0a2a0a")
        _h1(doc, "SECTION 33 — CADENAS DE EVIDENCIA FORENSE POR ACTOR")
        p33intro = doc.add_paragraph()
        _sp(p33intro)
        _r(p33intro,
           "Esta sección explica, en términos no técnicos, por qué cada cuenta fue "
           "clasificada como bot o troll. Cada señal incluye una descripción del "
           "comportamiento detectado y su relevancia como evidencia forense digital.",
           color=WHITE, size=9)
        doc.add_paragraph()

        max_chains = cfg.get("reporting", {}).get("docx", {}).get("max_chain_actors", 15)
        sev_colors_chain = {
            "CRÍTICO": "f38ba8", "ALTO": "fab387",
            "MEDIO": "f9e2af", "BAJO": "89b4fa",
        }
        cls_colors_chain = {
            "CONFIRMED_BOT": "f38ba8", "HIGH_RISK": "fab387",
            "SUSPICIOUS": "f9e2af", "LIKELY_HUMAN": "89b4fa", "HUMAN": "6c7086",
        }
        for ch in chain_report.chains[:max_chains]:
            _div(doc, "1a1a2e")
            pa = doc.add_paragraph()
            _sp(pa)
            cc = _hex_to_rgb(cls_colors_chain.get(ch.classification, "888888"))
            _r(pa, f"  👤 {ch.actor}  ", bold=True, color=WHITE, size=10)
            _r(pa, f"[{ch.classification_es}]  ", bold=True, color=cc, size=9)
            _r(pa, f"  Score: {ch.bot_risk_score}/100  ·  {ch.total_signals} señal(es)",
               color=GRAY, size=8)

            psumm = doc.add_paragraph()
            _sp(psumm)
            _r(psumm, f"  {ch.summary_sentence}", color=WHITE, size=8, italic=True)

            for i, sig in enumerate(ch.signals, 1):
                ps = doc.add_paragraph()
                _sp(ps)
                sc = _hex_to_rgb(sev_colors_chain.get(sig.severity, "888888"))
                _r(ps, f"  {i:2d}. ", color=GRAY, size=8)
                _r(ps, f"[{sig.severity}] ", bold=True, color=sc, size=8)
                _r(ps, f"{sig.title}", bold=True, color=WHITE, size=8)
                _r(ps, f"  ·  {sig.source_engine}  ·  {sig.points}pts\n", color=GRAY, size=7)
                _r(ps, f"      {sig.explanation}\n", color=WHITE, size=7, italic=True)
                _r(ps, f"      📊 {sig.evidence}", color=YELLOW, size=7)
            doc.add_paragraph()
        print(f"  [CHAINS] {len(chain_report.chains)} actor chains generated")

    # ── SECCIÓN 34: GLOSARIO DE TÉRMINOS ──────────────────────────────────────
    if cfg.get("reporting", {}).get("docx", {}).get("include_glossary", True):
        doc.add_page_break()
        _div(doc, "1e1e2e")
        _h1(doc, "APÉNDICE — GLOSARIO DE TÉRMINOS Y ABREVIATURAS")
        p_glo_intro = doc.add_paragraph()
        _sp(p_glo_intro)
        _r(p_glo_intro,
           "Este glosario explica los términos técnicos y abreviaturas utilizados "
           "en el presente reporte, para facilitar su comprensión por parte de "
           "autoridades, abogados, periodistas y público en general.",
           color=WHITE, size=9, italic=True)
        doc.add_paragraph()

        glossary_abbr = cfg.get("glossary", {}).get("abbreviations", _DEFAULT_GLOSSARY_ABBR)
        glossary_terms = cfg.get("glossary", {}).get("terms", _DEFAULT_GLOSSARY_TERMS)

        _r(doc.add_paragraph(), "ABREVIATURAS Y ACRÓNIMOS", bold=True, color=CYAN, size=10)
        for abbr, definition in glossary_abbr.items():
            pg = doc.add_paragraph()
            _sp(pg)
            _r(pg, f"  {abbr:<20}", bold=True, color=YELLOW, size=8)
            _r(pg, f"{definition}", color=WHITE, size=8)

        doc.add_paragraph()
        _r(doc.add_paragraph(), "CONCEPTOS TÉCNICOS EXPLICADOS", bold=True, color=CYAN, size=10)
        for term, definition in glossary_terms.items():
            pg = doc.add_paragraph()
            _sp(pg)
            _r(pg, f"  {term}\n", bold=True, color=WHITE, size=9)
            _r(pg, f"  {definition}", color=WHITE, size=8, italic=True)
            doc.add_paragraph()

    # ── FOOTER ────────────────────────────────────────────────────────────────
    _div(doc, "C00000")
    pf = doc.add_paragraph()
    _sp(pf)
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(pf, f"◈ NULLSEC RED TEAM  ·  FBSCRAP v2.0  ·  Social Media Intelligence  ·  {date_lbl}",
       color=GRAY, size=7)
    pf2 = doc.add_paragraph()
    _sp(pf2)
    pf2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(pf2, "◈ NULLSEC RED TEAM  ·  Open-Source Threat Intelligence  ·  nullsec-rt.io",
       bold=True, color=RED_DARK, size=8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    size_kb = output_path.stat().st_size // 1024
    print(f"  [DOCX] → {output_path}  ({size_kb} KB)")
