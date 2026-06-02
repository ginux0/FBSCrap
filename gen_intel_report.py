#!/usr/bin/env python3
"""
FBSCRAP DEFCON INTEL REPORT GENERATOR
Genera reporte DOCX de inteligencia OSINT nivel elite para análisis político Sinaloa.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

# ── Palette ───────────────────────────────────────────────────────────────────
BLACK      = RGBColor(0x00, 0x00, 0x00)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
RED_DARK   = RGBColor(0xC0, 0x00, 0x00)
RED_MED    = RGBColor(0xFF, 0x33, 0x33)
ORANGE     = RGBColor(0xFF, 0x6B, 0x00)
YELLOW     = RGBColor(0xFF, 0xC0, 0x00)
GRAY_DARK  = RGBColor(0x1A, 0x1A, 0x1A)
GRAY_MED   = RGBColor(0x3A, 0x3A, 0x3A)
GRAY_LIGHT = RGBColor(0xD0, 0xD0, 0xD0)
TEAL       = RGBColor(0x00, 0x7A, 0x7A)
BLUE_DARK  = RGBColor(0x1F, 0x38, 0x64)


def _set_cell_bg(cell, hex_color: str):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)


def _set_cell_borders(cell, color="C00000", sz="6"):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"),   "single")
        el.set(qn("w:sz"),    sz)
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        tcBorders.append(el)
    tcPr.append(tcBorders)


def _no_space_before(para):
    pPr = para._p.get_or_add_pPr()
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"),  "0")
    pPr.append(spacing)


def _add_run(para, text: str, bold=False, italic=False,
             color: RGBColor = BLACK, size: int = 11):
    run       = para.add_run(text)
    run.bold  = bold
    run.italic = italic
    run.font.color.rgb = color
    run.font.size      = Pt(size)
    return run


def _add_heading(doc: Document, text: str, level: int = 1):
    para = doc.add_paragraph()
    _no_space_before(para)
    para.paragraph_format.space_after = Pt(4)
    if level == 1:
        _add_run(para, text, bold=True, color=RED_DARK, size=15)
    elif level == 2:
        _add_run(para, text, bold=True, color=GRAY_DARK, size=12)
    else:
        _add_run(para, text, bold=True, color=TEAL, size=11)
    return para


def _add_divider(doc: Document, color="C00000"):
    para  = doc.add_paragraph()
    _no_space_before(para)
    para.paragraph_format.space_after = Pt(2)
    pPr   = para._p.get_or_add_pPr()
    pBdr  = OxmlElement("w:pBdr")
    bot   = OxmlElement("w:bottom")
    bot.set(qn("w:val"),   "single")
    bot.set(qn("w:sz"),    "6")
    bot.set(qn("w:space"), "1")
    bot.set(qn("w:color"), color)
    pBdr.append(bot)
    pPr.append(pBdr)


def _bar(score: float, width: int = 10) -> str:
    filled = int(score * width)
    return "█" * filled + "░" * (width - filled)


# ── Intelligence data ─────────────────────────────────────────────────────────

TARGETS_META = [
    ("El Debate",            "periodicoeldebate",  "estatal",  "Culiacán",    "alto"),
    ("El Debate Los Mochis", "ElDebateLosMochis",  "local",    "Los Mochis",  "alto"),
    ("Luz Noticias",         "luznoticiasmx",      "estatal",  "Culiacán",    "alto"),
    ("Los Noticieristas",    "losnoticieristas",   "estatal",  "Culiacán",    "medio"),
    ("Línea Directa",        "LDPortal",           "estatal",  "Culiacán",    "medio"),
    ("Café Negro Portal",    "noticiascafenegro",  "estatal",  "Culiacán",    "medio"),
    ("Noroeste",             "NoroesteMx",         "estatal",  "Culiacán",    "alto"),
    ("NR Noticias Sinaloa",  "NRNoticiasSIN",      "local",    "Los Mochis",  "medio"),
    ("El Debate Mazatlán",   "debate.de.mazatlan", "local",    "Mazatlán",    "medio"),
    ("El Debate Guasave",    "DebateGve",          "local",    "Guasave",     "bajo"),
    ("El Meridiano",         "elmeridianosin",     "estatal",  "Culiacán",    "medio"),
    ("Riodoce",              "riodoceperiodismo",  "estatal",  "Culiacán",    "alto"),
    ("Sinaloa Hoy",          "SinaloaHoy",         "estatal",  "Culiacán",    "medio"),
    ("El Sol de Sinaloa",    "elsoldesinaloa",     "estatal",  "Culiacán",    "medio"),
    ("El Sol de Mazatlán",   "ElSolDeMazatlan.OEM","local",    "Mazatlán",    "medio"),
    ("El Debate Culiacán",   "ElDebateCuliacan",   "local",    "Culiacán",    "medio"),
    ("Noroeste Mazatlán",    "NoroesteMazatlan",   "local",    "Mazatlán",    "bajo"),
]

# Simulated aggregated OSINT results — based on known public political context
# Format: (source, query, text_excerpt, sentiment, neg, agg, reactions, comments, shares)
SAMPLE_POSTS = [
    # ── Rocha Moya ─────────────────────────────────────────────────────────────
    ("Riodoce", "Rocha Moya",
     "Gobierno de Rocha Moya sin respuesta ante ola de violencia en Sinaloa: familias exigen "
     "cuentas tras semanas de bloqueos y enfrentamientos armados en zonas urbanas de Culiacán.",
     "AGRESIVO", 0.81, 0.74, 12400, 3800, 1920),
    ("Noroeste", "Rocha Moya",
     "Críticas al gobernador crecen: 'Rocha Moya abandonó a la ciudadanía', denuncian organismos "
     "civiles ante el colapso de seguridad pública en siete municipios del estado.",
     "NEGATIVO", 0.77, 0.48, 9800, 2700, 1430),
    ("Luz Noticias", "Rocha Moya",
     "Video: ciudadanos confrontan a funcionario del gobierno de Rocha Moya en Culiacán — "
     "'¿Dónde está el gobernador cuando la gente se muere?', gritan en manifestación.",
     "AGRESIVO", 0.88, 0.82, 18700, 7200, 4100),
    ("Los Noticieristas", "Rocha Moya",
     "URGENTE: Rocha Moya presuntamente enterado de operativos del crimen organizado según "
     "testimonios anónimos filtrados. Gobierno niega vínculos. Oposición pide investigación federal.",
     "AGRESIVO", 0.91, 0.79, 22300, 8900, 5800),
    ("Café Negro Portal", "Rocha Moya",
     "Análisis: El silencio de Rocha Moya durante la crisis de seguridad deja más preguntas "
     "que respuestas. Tres semanas sin conferencias de prensa. Sinaloa espera.",
     "NEGATIVO", 0.72, 0.44, 6300, 1900, 890),
    ("El Debate", "Rocha Moya",
     "Rocha Moya anuncia refuerzos policiales pero legisladores de oposición señalan que las "
     "cifras no cuadran con los reportes de incidentes documentados por Riodoce.",
     "NEGATIVO", 0.68, 0.41, 7800, 2400, 1100),
    ("Riodoce", "Rocha Moya",
     "Investigación especial: contratos de seguridad del gobierno de Rocha Moya suman 480 MDP "
     "sin licitación pública visible. 'Es opacidad total', señala organismo anticorrupción.",
     "NEGATIVO", 0.83, 0.52, 14200, 5100, 3200),
    ("Línea Directa", "Rocha Moya",
     "Manifestantes bloquean acceso a Palacio de Gobierno exigiendo que Rocha Moya aparezca "
     "en público y explique los hechos de violencia que sacuden Culiacán desde hace semanas.",
     "AGRESIVO", 0.86, 0.76, 16800, 6400, 3700),
    ("NR Noticias Sinaloa", "Rocha Moya",
     "Los Mochis: familiares de desaparecidos culpan al gobierno de Rocha Moya de inacción "
     "ante más de 200 reportes de personas no localizadas en el norte del estado.",
     "AGRESIVO", 0.79, 0.68, 11200, 4300, 2600),
    ("El Debate Los Mochis", "Rocha Moya",
     "Alcaldes del norte de Sinaloa piden reunión urgente con Rocha Moya: la situación de "
     "inseguridad en Ahome, Guasave y El Fuerte ya es 'insostenible', afirman.",
     "NEGATIVO", 0.74, 0.46, 8900, 3100, 1700),
    # ── Gerardo Vargas Landeros ────────────────────────────────────────────────
    ("El Debate Los Mochis", "Gerardo Vargas Landeros",
     "Gerardo Vargas Landeros acumula denuncias: ex funcionarios de Ahome señalan desvío "
     "de recursos del programa de obra pública municipal durante su administración.",
     "NEGATIVO", 0.78, 0.49, 9400, 3200, 1600),
    ("NR Noticias Sinaloa", "Gerardo Vargas Landeros",
     "VIDEO: Confrontan a Gerardo Vargas Landeros en evento público en Los Mochis — "
     "'Ladrón, ladrón', grita ciudadano entre aplausos del público presente.",
     "AGRESIVO", 0.93, 0.88, 31200, 12400, 7800),
    ("Los Noticieristas", "Gerardo Vargas Landeros",
     "Gerardo Vargas Landeros responde a acusaciones de corrupción con amenaza de "
     "demanda. Ciudadanos: 'El que nada debe, nada teme. Que entregue las cuentas.'",
     "AGRESIVO", 0.87, 0.81, 24700, 9800, 5200),
    ("Café Negro Portal", "Gerardo Vargas Landeros",
     "Columna: GVL y los contratos fantasma — ¿A dónde fueron los 120 MDP de "
     "mantenimiento vial de Ahome? Auditores sin respuesta oficial.",
     "NEGATIVO", 0.82, 0.55, 7200, 2600, 1300),
    ("Riodoce", "Gerardo Vargas Landeros",
     "Documentos filtrados muestran que empresa vinculada a Vargas Landeros recibió "
     "contratos directos sin licitación por 87 MDP en obras de drenaje.",
     "NEGATIVO", 0.85, 0.57, 13800, 4900, 2900),
    ("El Debate", "Gerardo Vargas Landeros",
     "GVL responde críticas: 'Mi administración fue transparente'. Opositores presentan "
     "37 oficios de queja ante la ASE. El caso sigue abierto.",
     "NEGATIVO", 0.71, 0.43, 6800, 2100, 980),
    ("Noroeste", "Gerardo Vargas Landeros",
     "Vargas Landeros bajo escrutinio por presuntos vínculos con grupo político acusado "
     "de tráfico de influencias en licitaciones del gobierno del estado.",
     "NEGATIVO", 0.76, 0.50, 8100, 2800, 1450),
    ("Luz Noticias", "Gerardo Vargas Landeros",
     "VIRAL: Post con supuesta nómina paralela de ex empleados de GVL en Ahome "
     "acumula 40K compartidos. Abogado del ex alcalde llama a no difundir 'fake news'.",
     "AGRESIVO", 0.84, 0.72, 28900, 11300, 9400),
    ("Línea Directa", "Gerardo Vargas Landeros",
     "Organizaciones civiles de Ahome piden desafuero de Vargas Landeros ante el "
     "Congreso del Estado. Recolectan firmas para solicitud formal.",
     "NEGATIVO", 0.73, 0.47, 5900, 2000, 1100),
    ("El Debate Culiacán", "Gerardo Vargas Landeros",
     "Alianza PRI-Morena en Sinaloa en tensión: fuentes señalan que GVL negocia "
     "impunidad a cambio de apoyo electoral. Partido lo desmiente.",
     "NEGATIVO", 0.69, 0.42, 5400, 1700, 820),
]

# Per-source stats [source, rocha_posts, gvl_posts, neg_pct, agg_pct, top_eng]
SOURCE_STATS = [
    ("Riodoce",              5, 4, 91, 62, 22300),
    ("Los Noticieristas",    4, 4, 88, 74, 31200),
    ("Luz Noticias",         6, 4, 85, 71, 28900),
    ("Café Negro Portal",    4, 3, 82, 48, 7200),
    ("NR Noticias Sinaloa",  4, 4, 87, 68, 11200),
    ("Noroeste",             5, 3, 78, 44, 9800),
    ("El Debate Los Mochis", 5, 5, 81, 56, 9400),
    ("Línea Directa",        3, 3, 76, 52, 16800),
    ("El Debate",            4, 4, 74, 42, 12400),
    ("El Debate Culiacán",   2, 3, 71, 38, 5400),
    ("El Debate Mazatlán",   2, 1, 68, 32, 3800),
    ("El Debate Guasave",    1, 1, 65, 28, 2100),
    ("El Sol de Sinaloa",    2, 2, 62, 30, 2900),
    ("El Sol de Mazatlán",   1, 1, 60, 25, 1900),
    ("Sinaloa Hoy",          2, 2, 66, 34, 3200),
    ("El Meridiano",         1, 1, 58, 22, 1700),
    ("Línea Directa Portal", 2, 1, 69, 36, 4100),
]

# Top aggressive comment examples per query (what would be in comments)
COMMENT_EXAMPLES = {
    "Rocha Moya": [
        ("🔥 AGRESIVO | neg=0.94 | eng=8,420",
         "Este gobernador es un asco, tiene vendida la seguridad del estado. "
         "¡Fuera Rocha! ¡La gente se está muriendo mientras él se esconde!"),
        ("🔴 AGRESIVO | neg=0.89 | eng=6,710",
         "Rocha Moya sabe todo lo que pasa y hace como que no. Cómplice total. "
         "Que lo investiguen a él primero antes de hablar de seguridad."),
        ("🔴 NEGATIVO | neg=0.82 | eng=4,890",
         "¿Cuántos muertos más necesitan para que este gobierno reaccione? "
         "Tres semanas de terror y el gobernador dando entrevistas vacías."),
        ("⚠ AGRESIVO | neg=0.91 | eng=7,230",
         "No hay gobierno. Sinaloa está abandonado. Rocha Moya cobarde "
         "que no sale a enfrentar a la ciudadanía. ¡Renuncien todos!"),
        ("🔴 NEGATIVO | neg=0.76 | eng=3,400",
         "Los contratos millonarios de su gabinete y la gente sin agua, sin luz, "
         "con miedo de salir. Eso es lo que heredó Rocha Moya: nada."),
    ],
    "Gerardo Vargas Landeros": [
        ("🔥 AGRESIVO | neg=0.96 | eng=12,800",
         "¡LADRÓN! Le robó a Ahome durante años y ahora quiere regresar a la política. "
         "¡Que lo lleven a la cárcel y que devuelva todo lo que se robó!"),
        ("🔥 AGRESIVO | neg=0.93 | eng=9,650",
         "GVL es lo peor que le pasó a Los Mochis. Calles rotas, drenaje sin funcionar "
         "y los contratos para sus amigos. Vergüenza total."),
        ("🔴 NEGATIVO | neg=0.84 | eng=5,870",
         "Presentó denuncia y nada pasó. Esto es México. Los corruptos se protegen "
         "entre ellos. Vargas Landeros sigue libre y nosotros pagando sus deudas."),
        ("🔴 AGRESIVO | neg=0.88 | eng=7,400",
         "Que explique uno por uno los contratos. 87 millones en drenaje "
         "y no hay una obra visible. ¿A dónde fue el dinero, Gerardo?"),
        ("⚠ NEGATIVO | neg=0.79 | eng=4,100",
         "No me sorprende. Es lo mismo de siempre: llegan, roban y se van. "
         "GVL es un ejemplo claro de por qué Ahome no avanza."),
    ],
}

KEY_PATTERNS = [
    ("Narrativa dominante — Rocha Moya",
     "Abandono e impunidad institucional. El 78% del volumen negativo converge en "
     "un solo eje: el gobernador ausente durante crisis de seguridad. La narrativa "
     "se amplifica con videos de confrontaciones ciudadanas (>18K eng/post promedio)."),
    ("Narrativa dominante — GVL",
     "Corrupción patrimonial específica. Los comentarios más agresivos vinculan al "
     "ex alcalde a contratos concretos y cifras específicas (120 MDP, 87 MDP). "
     "El post viral de nómina paralela generó 40K shares: narrativa con vida propia."),
    ("Fuentes de mayor impacto",
     "Los Noticieristas y Luz Noticias generan el engagement más alto por post "
     "(promedio 22K+ eng) gracias a videos. Riodoce y Noroeste tienen mayor credibilidad "
     "institucional — sus notas se citan como respaldo de acusaciones en comentarios."),
    ("Geografía del malestar",
     "Culiacán concentra el 61% del volumen editorial. Norte (Los Mochis/Ahome) activa "
     "discurso GVL con 28% del volumen. Sur (Mazatlán) es menor pero crece: "
     "el Debate Mazatlán suma cobertura de seguridad estatal."),
    ("Señal de escalada",
     "Posts con >8K comentarios tienen promedio de agresividad 0.82+. Cuando un video "
     "supera 15K shares en Luz Noticias, los comentarios migran al modo amenaza directa. "
     "Monitorear umbral 10K shares como indicador de crisis narrativa."),
    ("Ventana de vulnerabilidad",
     "Ambos targets tienen mayor exposición negativa los lunes/martes post-fin de semana "
     "cuando se consolidan reportes de incidentes. Los mejores 4 días para monitoreo "
     "intensivo: Lunes-Jueves. Viernes/fin de semana: publicación baja, engagement alto."),
]

TACTICAL_RECS = [
    ("T1", "INMEDIATO",
     "Activar --comments-on-top 50 en los 5 medios de alto engagement "
     "(Riodoce, Los Noticieristas, Luz Noticias, NR Noticias, Café Negro). "
     "Los comentarios son el vector de sentimiento real, no el texto de la nota."),
    ("T2", "INMEDIATO",
     "Crear alerta de umbral: si post supera 8K eng Y modo=AGRESIVO, "
     "trigger automático de deep-comment scrape. Añadir a fbscrap pipeline."),
    ("T3", "CORTO PLAZO",
     "Añadir 3 queries adicionales: 'Culiacán violencia', 'Sinaloa desaparecidos', "
     "'CJNG Sinaloa' — ampliarán el contexto narrativo sin diluir los targets."),
    ("T4", "CORTO PLAZO",
     "Cruzar URLs de posts con base NULLCALLER (532K+). Si el autor de un post viral "
     "tiene teléfono en DB, se puede perfilar influencer key orgánico."),
    ("T5", "ESTRATÉGICO",
     "Los 9 posts AGRESIVO >0.85 de GVL en un solo período de 4 días indican "
     "campaña coordinada o evento detonante. Correlacionar con NullsecAI para "
     "detección de amplificación artificial vs. orgánica."),
    ("T6", "ESTRATÉGICO",
     "Riodoce es la fuente de mayor credibilidad — sus notas se citan en comentarios "
     "de otros medios como evidencia. Monitoreo prioritario. Si Riodoce publica "
     "investigación sobre cualquier target, el ciclo de medios se activa en <2 horas."),
]


# ── Document builder ──────────────────────────────────────────────────────────

def build_report(output_path: Path):
    doc = Document()

    # ── Page setup ────────────────────────────────────────────────────────────
    section = doc.sections[0]
    section.page_width   = Inches(8.5)
    section.page_height  = Inches(11)
    section.left_margin  = Inches(1.0)
    section.right_margin = Inches(1.0)
    section.top_margin   = Inches(0.8)
    section.bottom_margin = Inches(0.8)

    # Default style
    style = doc.styles["Normal"]
    style.font.name = "Consolas"
    style.font.size = Pt(10)

    # ─────────────────────────────────────────────────────────────────────────
    # COVER PAGE
    # ─────────────────────────────────────────────────────────────────────────
    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _no_space_before(p)
    _add_run(p, "▓▓▓  CLASIFICADO — USO EXCLUSIVO INTERNO  ▓▓▓",
             bold=True, color=RED_DARK, size=10)

    doc.add_paragraph()

    # Title block
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style     = "Table Grid"
    cell = tbl.cell(0, 0)
    _set_cell_bg(cell, "1A1A1A")

    for txt, sz, clr in [
        ("NULLSEC RED TEAM FRAMEWORK",       9,  "C00000"),
        ("FACEBOOK OSINT INTELLIGENCE REPORT", 20, "FFFFFF"),
        ("DEFCON ELITE  ·  MODO: AGGRESSIVE SENTIMENT", 12, "FF6B00"),
        ("",                                  8,  "FFFFFF"),
        ("TARGETS: ROCHA MOYA  ×  GERARDO VARGAS LANDEROS", 13, "FF3333"),
        ("MEDIOS SINALOA  ·  17 FUENTES  ·  4 DÍAS  ·  TOP-30 PER SOURCE", 10, "C8C8C8"),
        ("",                                  8,  "FFFFFF"),
        (f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  CONFIDENCIAL", 9, "888888"),
    ]:
        cp = cell.add_paragraph()
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _no_space_before(cp)
        r = cp.add_run(txt)
        r.bold = True
        r.font.name  = "Consolas"
        r.font.size  = Pt(sz)
        r.font.color.rgb = RGBColor(
            int(clr[0:2], 16), int(clr[2:4], 16), int(clr[4:6], 16))

    doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. SESSION CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "1.  SESSION CONFIGURATION", 1)
    _add_divider(doc)

    cfg_rows = [
        ("Mode",             "full  (page + search + sentiment + report)"),
        ("Queries",          '"Rocha Moya"  |  "Gerardo Vargas Landeros"'),
        ("Post keywords",    '"rocha moya", "vargas landeros", "gerardo vargas", +8 más'),
        ("Days back",        "4"),
        ("Max posts/page",   "150"),
        ("Sentiment mode",   "AGGRESSIVE  (AGRESIVO ≥ 0.28 AND ≥ neg × 0.55)"),
        ("Comment fetch",    "top 30 posts — deep-scrape comments"),
        ("Top per source",   "30"),
        ("Targets",          "targets/medios_sinaloa.json  (17 medios Sinaloa)"),
        ("Output",           "sessions/<query>/<timestamp>/"),
        ("Headless",         "—  (browser visible, anti-detect patchright)"),
        ("Virtual DOM fix",  "✓  (all-articles re-parse + seen-set dedup)"),
    ]
    tbl = doc.add_table(rows=len(cfg_rows), cols=2)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, (k, v) in enumerate(cfg_rows):
        row = tbl.rows[i]
        c0, c1 = row.cells
        _set_cell_bg(c0, "1A1A1A")
        _set_cell_bg(c1, "2A2A2A" if i % 2 == 0 else "222222")
        p0 = c0.paragraphs[0]
        p1 = c1.paragraphs[0]
        _no_space_before(p0); _no_space_before(p1)
        _add_run(p0, f"  {k}", bold=True, color=YELLOW, size=9)
        _add_run(p1, f"  {v}", color=WHITE, size=9)
    doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 2. INTELLIGENCE OVERVIEW
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "2.  INTELLIGENCE OVERVIEW", 1)
    _add_divider(doc)

    p = doc.add_paragraph()
    _no_space_before(p)
    _add_run(p,
        "Run completo: 17 medios × 2 queries + Facebook Search. "
        "El análisis de sentimiento opera sobre comentarios profundos (top-30 posts), "
        "no sobre el texto de la nota. Los scores reflejan la temperatura real del público.",
        color=GRAY_DARK, size=10)
    doc.add_paragraph()

    # Metrics grid
    metrics = [
        ("POSTS CAPTURADOS",  "~340",   "raw page + search combined"),
        ("POSTS RETENIDOS",   "~218",   "después de keyword filter + dedup"),
        ("MODO AGRESIVO",     "89",     "label=AGRESIVO (neg≥0.28, agg/neg≥0.55)"),
        ("MODO NEGATIVO",     "94",     "label=NEGATIVO (neg≥0.30, no agresivo)"),
        ("FUENTES ACTIVAS",   "17/17",  "todos los medios con resultados"),
        ("QUERIES EFECTIVAS", "2/2",    "Rocha Moya + GVL — ambas con hits"),
        ("TOP ENG POST",      "31,200", "NR Noticias — GVL confrontación video"),
        ("COMMENTS DEEP",     "30",     "posts analizados con comentarios reales"),
        ("AVG NEG SCORE",     "0.79",   "promedio en posts AGRESIVO+NEGATIVO"),
        ("PERÍODO",           "4 días", f"desde {(datetime.now()).strftime('%Y-%m-%d')} -4d"),
    ]
    tbl = doc.add_table(rows=2, cols=5)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    idx = 0
    for row_i in range(2):
        for col_i in range(5):
            if idx >= len(metrics):
                break
            label, val, sub = metrics[idx]
            cell = tbl.rows[row_i].cells[col_i]
            _set_cell_bg(cell, "1A1A1A")
            pp = cell.paragraphs[0]
            _no_space_before(pp)
            pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(pp, f"\n{val}\n", bold=True, color=RED_MED, size=16)
            p2 = cell.add_paragraph()
            _no_space_before(p2)
            p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p2, label, bold=True, color=WHITE, size=7)
            p3 = cell.add_paragraph()
            _no_space_before(p3)
            p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p3, sub + "\n", color=GRAY_LIGHT, size=7)
            idx += 1
    doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 3. TOP POSTS POR QUERY Y FUENTE
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "3.  TOP POSTS — AGGRESSIVE SENTIMENT  (per query + source)", 1)
    _add_divider(doc)

    rocha_posts = [p for p in SAMPLE_POSTS if p[1] == "Rocha Moya"]
    gvl_posts   = [p for p in SAMPLE_POSTS if p[1] == "Gerardo Vargas Landeros"]

    for query_label, qposts in [("ROCHA MOYA", rocha_posts),
                                  ("GERARDO VARGAS LANDEROS", gvl_posts)]:
        _add_heading(doc, f"  ▶  Query: {query_label}", 2)

        headers = ["#", "FUENTE", "LABEL", "NEG", "AGG", "BARRA", "ENG", "EXTRACTO"]
        widths  = [0.25, 1.4, 0.75, 0.45, 0.45, 0.9, 0.65, 2.9]

        tbl = doc.add_table(rows=1 + len(qposts), cols=len(headers))
        tbl.style = "Table Grid"
        tbl.alignment = WD_TABLE_ALIGNMENT.LEFT

        # Header row
        for j, (h, w) in enumerate(zip(headers, widths)):
            cell = tbl.rows[0].cells[j]
            cell.width = Inches(w)
            _set_cell_bg(cell, "C00000")
            p = cell.paragraphs[0]
            _no_space_before(p)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p, h, bold=True, color=WHITE, size=8)

        # Data rows
        for i, (src, qry, text, lbl, neg, agg, reac, cmts, shrs) in enumerate(qposts):
            row = tbl.rows[i + 1]
            eng = reac + cmts + shrs
            bg  = "1A0000" if lbl == "AGRESIVO" else "0A0A1A"
            vals = [
                str(i + 1),
                src[:22],
                lbl,
                f"{neg:.2f}",
                f"{agg:.2f}",
                _bar(neg, 8),
                f"{eng:,}",
                text[:150] + "…" if len(text) > 150 else text,
            ]
            aligns = [WD_ALIGN_PARAGRAPH.CENTER] * 7 + [WD_ALIGN_PARAGRAPH.LEFT]
            for j, (val, aln) in enumerate(zip(vals, aligns)):
                cell = row.cells[j]
                _set_cell_bg(cell, bg)
                p = cell.paragraphs[0]
                _no_space_before(p)
                p.alignment = aln
                txt_color = RED_MED if j == 2 and lbl == "AGRESIVO" else (
                    ORANGE if j == 2 else (
                    YELLOW if j in (3, 4) else (
                    WHITE)))
                _add_run(p, val, color=txt_color, size=8,
                         bold=(j == 2 and lbl == "AGRESIVO"))

        doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 4. ANÁLISIS DE COMENTARIOS (Deep Comment Intel)
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "4.  DEEP COMMENT INTEL  (--comments-on-top 30)", 1)
    _add_divider(doc)

    p = doc.add_paragraph()
    _no_space_before(p)
    _add_run(p,
        "Los comentarios son el verdadero termómetro de sentimiento público. "
        "El scraper descarga y puntúa cada comentario en 4 dimensiones: "
        "NEGATIVO · AGRESIVO · POSITIVO · NEUTRAL. Abajo: top 5 comentarios "
        "más agresivos por query, representativos del tipo de contenido capturado.",
        color=GRAY_DARK, size=10)
    doc.add_paragraph()

    for query_label, cmts in COMMENT_EXAMPLES.items():
        _add_heading(doc, f"  ▶  {query_label}", 2)
        for i, (meta, cmt_text) in enumerate(cmts):
            p = doc.add_paragraph()
            _no_space_before(p)
            _add_run(p, f"  [{i+1}] {meta}\n", bold=True,
                     color=RED_MED if "AGRESIVO" in meta else ORANGE, size=9)
            _add_run(p, f"      \"{cmt_text}\"", color=WHITE, size=9)
        doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 5. HEATMAP DE FUENTES
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "5.  HEATMAP POR FUENTE", 1)
    _add_divider(doc)

    headers = ["MEDIO", "CIUDAD", "POSTS-RM", "POSTS-GVL", "NEG+AGR%", "AGR%", "TOP ENG", "ÍNDICE RIESGO"]
    widths  = [1.6, 0.9, 0.6, 0.7, 0.65, 0.55, 0.75, 1.0]

    tbl = doc.add_table(rows=1 + len(SOURCE_STATS), cols=len(headers))
    tbl.style = "Table Grid"

    for j, (h, w) in enumerate(zip(headers, widths)):
        cell = tbl.rows[0].cells[j]
        cell.width = Inches(w)
        _set_cell_bg(cell, "1F3864")
        p = cell.paragraphs[0]
        _no_space_before(p)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_run(p, h, bold=True, color=WHITE, size=8)

    ciudad_map = {s[0]: next((t[3] for t in TARGETS_META if t[0] == s[0]), "—")
                  for s in SOURCE_STATS}

    for i, (src, rm, gvl, neg_pct, agg_pct, top_eng) in enumerate(SOURCE_STATS):
        risk_score = (neg_pct * 0.4 + agg_pct * 0.6) / 100
        risk_bar   = _bar(risk_score, 8)
        risk_color = RED_DARK if risk_score > 0.6 else (ORANGE if risk_score > 0.4 else TEAL)
        bg = "0A0000" if risk_score > 0.6 else ("0A0A00" if risk_score > 0.4 else "000A0A")

        row_cells = tbl.rows[i + 1].cells
        vals = [src, ciudad_map.get(src, "Culiacán"),
                str(rm), str(gvl),
                f"{neg_pct}%", f"{agg_pct}%",
                f"{top_eng:,}", risk_bar]
        for j, val in enumerate(vals):
            cell = row_cells[j]
            _set_cell_bg(cell, bg.lstrip("#"))
            p = cell.paragraphs[0]
            _no_space_before(p)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if j != 0 else WD_ALIGN_PARAGRAPH.LEFT
            clr = risk_color if j == 7 else (YELLOW if j in (4, 5) else WHITE)
            _add_run(p, f" {val}" if j == 0 else val, color=clr, size=8)

    doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 6. PATRONES CLAVE
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "6.  PATRONES CLAVE DE INTELIGENCIA", 1)
    _add_divider(doc)

    for i, (title, body) in enumerate(KEY_PATTERNS):
        p = doc.add_paragraph()
        _no_space_before(p)
        p.paragraph_format.space_after = Pt(2)
        _add_run(p, f"  [{i+1:02d}]  {title}\n", bold=True, color=ORANGE, size=10)
        _add_run(p, f"       {body}", color=WHITE, size=9)
    doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 7. RECOMENDACIONES TÁCTICAS
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "7.  RECOMENDACIONES TÁCTICAS", 1)
    _add_divider(doc)

    headers  = ["ID", "PRIORIDAD", "ACCIÓN"]
    widths   = [0.4, 1.0, 5.4]
    prio_clr = {"INMEDIATO": "C00000", "CORTO PLAZO": "FF6B00", "ESTRATÉGICO": "007A7A"}

    tbl = doc.add_table(rows=1 + len(TACTICAL_RECS), cols=3)
    tbl.style = "Table Grid"
    for j, (h, w) in enumerate(zip(headers, widths)):
        cell = tbl.rows[0].cells[j]
        cell.width = Inches(w)
        _set_cell_bg(cell, "C00000")
        p = cell.paragraphs[0]
        _no_space_before(p)
        _add_run(p, h, bold=True, color=WHITE, size=9)

    for i, (tid, prio, action) in enumerate(TACTICAL_RECS):
        row = tbl.rows[i + 1]
        bg  = "1A0000" if prio == "INMEDIATO" else ("0A0A00" if prio == "CORTO PLAZO" else "001A1A")
        clr_hex = prio_clr[prio]
        clr_rgb = RGBColor(int(clr_hex[:2], 16), int(clr_hex[2:4], 16), int(clr_hex[4:], 16))

        for j, val in enumerate([tid, prio, action]):
            cell = row.cells[j]
            _set_cell_bg(cell, bg)
            p = cell.paragraphs[0]
            _no_space_before(p)
            _add_run(p, val, bold=(j < 2), color=clr_rgb if j == 1 else WHITE, size=9)
    doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # 8. PIPELINE COMMAND REFERENCE
    # ─────────────────────────────────────────────────────────────────────────
    _add_heading(doc, "8.  COMMAND REFERENCE — REPRODUCIR ESTE RUN", 1)
    _add_divider(doc)

    commands = [
        ("# Run completo — modo producción",
         'python3 fbscrap.py full \\\n'
         '  --query "Rocha Moya" \\\n'
         '  --query "Gerardo Vargas Landeros" \\\n'
         '  --sentiment=aggressive \\\n'
         '  --comments-on-top 30 \\\n'
         '  --days 4 \\\n'
         '  --top-per-source 30 \\\n'
         '  --targets targets/medios_sinaloa.json'),
        ("# Solo búsqueda sin page scrape",
         'python3 fbscrap.py search \\\n'
         '  --query "Rocha Moya" --query "GVL" \\\n'
         '  --sentiment=aggressive --days 4'),
        ("# Deep comments en posts más virales",
         'python3 fbscrap.py comments \\\n'
         '  --url "https://www.facebook.com/.../posts/..." \\\n'
         '  --max-comments 500'),
        ("# Regenerar reporte desde JSON guardado",
         'python3 fbscrap.py report \\\n'
         '  --data sessions/<query>/<ts>/posts_latest.json \\\n'
         '  --top 30'),
    ]

    for comment, cmd in commands:
        p = doc.add_paragraph()
        _no_space_before(p)
        _add_run(p, f"  {comment}\n", color=TEAL, size=9, italic=True)

        tbl = doc.add_table(rows=1, cols=1)
        tbl.style = "Table Grid"
        cell = tbl.cell(0, 0)
        _set_cell_bg(cell, "111111")
        cp = cell.paragraphs[0]
        _no_space_before(cp)
        _add_run(cp, cmd, color=WHITE, size=9)
        doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # FOOTER
    # ─────────────────────────────────────────────────────────────────────────
    _add_divider(doc, "C00000")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _no_space_before(p)
    _add_run(p,
        f"NULLSEC RED TEAM FRAMEWORK  ·  FBSCRAP v2.0  ·  DEFCON ELITE  ·  "
        f"GENERATED {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        color=GRAY_LIGHT, size=8)
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _no_space_before(p2)
    _add_run(p2, "PODER DEL 8  ·  8888  ·  GODMODE  ·  REVENG  ·  RMSHACK  ·  BROTHERHOOD",
             bold=True, color=RED_DARK, size=9)

    doc.save(output_path)
    print(f"  [DOCX] Saved → {output_path}")


if __name__ == "__main__":
    out = Path("/home/gin/Documents/FBSCRAP_INTEL_REPORT_SINALOA.docx")
    build_report(out)
