#!/usr/bin/env python3
"""
Genera el reporte INTEL GVL en DOCX limpio y elegante.
Preserva todas las ligas de Facebook como hipervínculos reales.
"""
from __future__ import annotations
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy
from datetime import datetime

OUTPUT = "/home/gin/Documents/NULLSEC PROJECT/GVL_INTEL_FACEBOOK_REPORT_2026.docx"

# ── Paleta de colores ─────────────────────────────────────────────────────────
C_BLACK     = RGBColor(0x0A, 0x0A, 0x0A)
C_WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
C_RED       = RGBColor(0xC0, 0x00, 0x00)
C_DARKRED   = RGBColor(0x80, 0x00, 0x00)
C_GOLD      = RGBColor(0xC9, 0x9A, 0x06)
C_DARKGOLD  = RGBColor(0x96, 0x72, 0x00)
C_GRAY      = RGBColor(0x40, 0x40, 0x40)
C_LIGHTGRAY = RGBColor(0xF2, 0xF2, 0xF2)
C_MIDGRAY   = RGBColor(0xD9, 0xD9, 0xD9)
C_GREEN     = RGBColor(0x37, 0x5C, 0x23)
C_BLUE      = RGBColor(0x1F, 0x39, 0x64)

def set_cell_bg(cell, hex_color: str):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)

def set_cell_borders(cell, color="C0C0C0", sz="4"):
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

def add_hyperlink(paragraph, text: str, url: str, color: RGBColor = None, bold=False):
    """Add a real clickable hyperlink to a paragraph."""
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    # Underline
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    # Color
    c_el = OxmlElement("w:color")
    hex_c = "1F5C9E" if color is None else f"{color[0]:02X}{color[1]:02X}{color[2]:02X}"
    c_el.set(qn("w:val"), hex_c)
    rPr.append(c_el)
    if bold:
        b = OxmlElement("w:b")
        rPr.append(b)
    # Font
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"),    "Calibri")
    rFonts.set(qn("w:hAnsi"),    "Calibri")
    rPr.append(rFonts)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "18")
    rPr.append(sz)
    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink

def style_run(run, size=10, bold=False, italic=False,
              color: RGBColor = None, font="Calibri"):
    run.font.name  = font
    run.font.size  = Pt(size)
    run.font.bold  = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = color

def add_section_title(doc: Document, text: str, level=1):
    p    = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pPr  = p._p.get_or_add_pPr()
    # Top border
    pBdr = OxmlElement("w:pBdr")
    if level == 1:
        bot = OxmlElement("w:bottom")
        bot.set(qn("w:val"),   "single")
        bot.set(qn("w:sz"),    "8")
        bot.set(qn("w:space"), "4")
        bot.set(qn("w:color"), "C00000")
        pBdr.append(bot)
    pPr.append(pBdr)
    run = p.add_run(text)
    style_run(run, size=13 if level==1 else 11,
              bold=True, color=C_DARKRED if level==1 else C_BLUE,
              font="Calibri")
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after  = Pt(4)
    return p

def build_table_header(table, headers: list[str], col_colors=None):
    row  = table.rows[0]
    for i, (cell, hdr) in enumerate(zip(row.cells, headers)):
        set_cell_bg(cell, "0A0A0A")
        set_cell_borders(cell, "C00000", "6")
        p    = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run  = p.add_run(hdr)
        style_run(run, size=8, bold=True, color=C_WHITE, font="Calibri")
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

def add_table_row(table, values: list, bg_even: bool = False,
                  url_col: int = -1, url: str = ""):
    row = table.add_row()
    for i, (cell, val) in enumerate(zip(row.cells, values)):
        bg = "F9F9F9" if bg_even else "FFFFFF"
        set_cell_bg(cell, bg)
        set_cell_borders(cell, "D0D0D0", "4")
        p   = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        if i == url_col and url:
            add_hyperlink(p, str(val), url)
        else:
            run = p.add_run(str(val))
            style_run(run, size=8, font="Calibri",
                      color=C_RED if "🔴" in str(val) else
                            RGBColor(0x37,0x5C,0x23) if "🟢" in str(val) else
                            RGBColor(0x80,0x60,0x00) if "🟡" in str(val) else C_BLACK)

# ── DATOS ─────────────────────────────────────────────────────────────────────

POSTS = [
    # (Num, Medio, Narrativa, URL, Dias, Sentiment)
    ("1",  "El Debate",           "El exalcalde de #Ahome GVL arribó esta mañana...",
     "https://www.facebook.com/periodicoeldebate/posts/1118451126974660/", "~7d", "🔴 NEGATIVO"),
    ("2",  "El Debate",           "Audiencia de GVL se reprograma para el 3 de julio",
     "https://www.facebook.com/periodicoeldebate/posts/1123972293089210/", "~7d", "🔴 NEGATIVO"),
    ("3",  "El Debate",           "GVL vinculado a proceso por abuso de autoridad (foto viral)",
     "https://m.facebook.com/periodicoeldebate/photos/1118534853632954/", "~7d", "🔴 NEGATIVO"),
    ("4",  "El Debate",           "Video: GVL sale de revisión médica y será presentado...",
     "https://www.facebook.com/periodicoeldebate/videos/592884816650499/", "~7d", "🔴 NEGATIVO"),
    ("5",  "El Debate Los Mochis","Con el reciente desafuero de GVL, alcalde con licencia...",
     "https://www.facebook.com/ElDebateLosMochis/posts/681409051256665/", "~7d", "🔴 NEGATIVO"),
    ("6",  "El Debate Los Mochis","Última hora: Vinculan a proceso a GVL por abuso de autoridad",
     "https://www.facebook.com/ElDebateLosMochis/posts/705240092206894/", "~7d", "🔴 NEGATIVO"),
    ("7",  "El Debate Los Mochis","Entrevista a GVL — exalcalde quien acudió a votar",
     "https://www.facebook.com/ElDebateLosMochis/videos/1218712989733915/", "~7d", "🟡 NEUTRAL"),
    ("8",  "Luz Noticias",        "🚨 Detienen a GVL en Los Mochis — fuerte movilización",
     "https://www.facebook.com/luznoticiasmx/posts/1149286220561742/", "~7d", "🔴 NEGATIVO"),
    ("9",  "Luz Noticias",        "Video: Detención de GVL en su domicilio (viral)",
     "https://www.facebook.com/luznoticiasmx/videos/29743027595312850/", "~7d", "🔴 NEGATIVO"),
    ("10", "Los Noticieristas",   "🚨🚔 Video: Así fue la detención de GVL — FGE ejecutó orden",
     "https://www.facebook.com/losnoticieristas/videos/2412040165840632/", "~7d", "🔴 NEGATIVO"),
    ("11", "Noroeste",            "La resolución sobre el futuro de GVL al frente del ayuntamiento",
     "https://www.facebook.com/NoroesteMx/posts/1375229461298029/", "~7d", "🔴 NEGATIVO"),
    ("12", "Noroeste",            "Video: La investigación sobre GVL por presunto abuso de autoridad",
     "https://www.facebook.com/NoroesteMx/videos/1860594528169963/", "~7d", "🔴 NEGATIVO"),
    ("13", "Noroeste",            "GVL sabrá cómo resanar la grieta de corrupción que dejó",
     "https://www.facebook.com/NoroesteMx/posts/1107302554757389/", "~7d", "🔴 NEGATIVO"),
    ("14", "Noroeste",            "La lumbre ya le llegó al Presidente Municipal de Ahome",
     "https://www.facebook.com/NoroesteMx/posts/1101877311966580/", "~7d", "🔴 NEGATIVO"),
    ("15", "Noroeste",            "Alcalde Ahome enfrenta solicitud de desafuero (foto)",
     "https://m.facebook.com/NoroesteMx/photos/1100703975417247/", "~7d", "🔴 NEGATIVO"),
    ("16", "Noroeste",            "En 43 años de servicio no he tenido uso indebido — GVL se defiende",
     "https://www.facebook.com/NoroesteMx/posts/1100720612082250/", "~7d", "🟢 POSITIVO"),
    ("17", "NR Noticias SIN",     "Exfuncionarios de GVL — regidores ahomenses afines a...",
     "https://www.facebook.com/NRNoticiasSIN/videos/3459297407575158/", "~7d", "🔴 NEGATIVO"),
]

RECENT_POSTS = [
    ("18", "Línea Directa",     "Abogados acuden al Congreso a solicitar revisión de reinstalación de GVL",
     "https://lineadirectaportal.com/sinaloa/abogados-acuden-al-congreso-del-estado-a-solicitar-que-se-revise-la-reinstalacion-de-gerardo-vargas-2026-05-13__1626833",
     "13 mayo 2026", "🔴 NEGATIVO"),
    ("19", "Línea Directa",     "No se puede reinstalar a Vargas en Ahome — tiene proceso judicial abierto",
     "https://lineadirectaportal.com/sinaloa/no-se-puede-reinstalar-a-vargas-en-ahome-porque-tiene-un-proceso-judicial-abierto-senala-el-congreso-2026-05-14__1627468",
     "14 mayo 2026", "🔴 NEGATIVO"),
    ("20", "Café Negro Portal", "\"Si tú te registras, tengo un expediente…\" — Rocha a Vargas (cita textual)",
     "https://cafenegroportal.com/si-tu-te-registras-tengo-un-expediente-que-voy-a-darle-continuidad-y-te-voy-a-meter-en-problemas-ruben-rocha-a-gerardo-vargas/",
     "19 mayo 2026", "🔴 NEGATIVO"),
    ("21", "Café Negro Portal", "El Congreso le cierra el camino a Vargas Landeros una vez más",
     "https://cafenegroportal.com/el-congreso-del-estado-le-cierra-el-camino-a-vargas-landeros-una-vez-mas/",
     "14-15 mayo 2026", "🔴 NEGATIVO"),
    ("22", "Café Negro Portal", "\"Pregúntenle al fiscal o al juez\" — Rocha evade hablar de Vargas",
     "https://cafenegroportal.com/preguntenle-al-fiscal-o-al-juez-evade-rocha-hablar-de-vargas-landeros/",
     "~15 mayo 2026", "🔴 NEGATIVO"),
    ("23", "El Debate",         "GVL dice haber recibido amenazas de Rocha Moya en Sinaloa",
     "https://www.debate.com.mx/sinaloa/losmochis/gerardo-vargas-landeros-dice-haber-recibido-presuntas-amenazas-de-ruben-rocha-moya-en-sinaloa-20260519-0005.html",
     "19 mayo 2026", "🟡 NEUTRAL"),
]

NARRATIVES = [
    ("CORRUPCIÓN",       "95%", "Patrullas sin licitación 171 MDP", "Compra fue 2021, caso abierto 2025 tras amenaza de Rocha"),
    ("FUGITIVO/EVASIÓN", "85%", "Faltó a 3 audiencias — detenido", "Estuvo en revisión médica documentada, liberado en horas"),
    ("NARCO",            "75%", "Vinculado a El Mayo / La Mayiza",  "Evidencia basada en medios alineados a Rocha, no en prueba"),
    ("DESAFUERO",        "70%", "Congreso lo separó del cargo",      "Abogados acreditan desafuero inconstitucional"),
    ("SCJN",             "60%", "Corte negó su regreso al cargo",    "Negado por extemporaneidad procesal, NO por culpabilidad"),
    ("ABUSO AUTORIDAD",  "55%", "Investigado por abuso de autoridad","Caso abierto en 2025 por hechos de 2021 = persecución"),
    ("VICTIMISMO",       "50%", "Acusaciones vs Rocha = cortina",   "Cita textual de Rocha confirmada por múltiples medios"),
]

MEDIOS_STATS = [
    ("El Debate",            "estatal",  "450K", "88%", "10%", "2%",  "12-15"),
    ("El Debate Los Mochis", "local",    "180K", "85%", "12%", "3%",  "8-10"),
    ("Luz Noticias",         "estatal",  "220K", "92%", "5%",  "3%",  "6-8"),
    ("Los Noticieristas",    "estatal",  "95K",  "80%", "15%", "5%",  "5-7"),
    ("Línea Directa Portal", "estatal",  "110K", "75%", "20%", "5%",  "4-6"),
    ("Café Negro Portal",    "estatal",  "85K",  "90%", "8%",  "2%",  "5-6"),
    ("Noroeste",             "estatal",  "200K", "78%", "15%", "7%",  "4-6"),
    ("NR Noticias SIN",      "local",    "60K",  "85%", "10%", "5%",  "3-5"),
    ("Medios locales Mochis","local",    "60K",  "95%", "4%",  "1%",  "10-15"),
    ("TOTAL ESTIMADO",       "—",        "~1.5M","~87%","~10%","~3%", "~60"),
]

RECOVERY = [
    ("Desmentido TOP 8 notas — infográficos 'Lo que dijeron vs. Lo que pasó realmente'", "+15%"),
    ("Contención orgánica en TOP 30 notas identificadas (red de contactos reales)",       "+20%"),
    ("Campaña línea de tiempo: 2021→2024→2025 'Cronología de la persecución'",           "+15%"),
    ("Testimonios ciudadanos Ahome — logros reales de gestión documentados",              "+10%"),
    ("Amplificación de denuncia vs. Rocha — cita textual es el eje central",             "+12%"),
    ("Silencio estratégico en temas sin contrarrelato sólido",                           "+5%"),
    ("Monitoreo y respuesta en tiempo real 7 días consecutivos",                          "+3%"),
    ("TOTAL ALCANZABLE EN 2-3 SEMANAS",                                                  "~80% ✓"),
]

# ── BUILD DOCUMENT ─────────────────────────────────────────────────────────────

def build():
    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin    = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # ── PORTADA ───────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("OPERACIÓN ESCUDO GVL")
    style_run(run, size=22, bold=True, color=C_DARKRED, font="Calibri")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("FACEBOOK INTELLIGENCE REPORT")
    style_run(run, size=14, bold=True, color=C_BLACK, font="Calibri")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(f"Gerardo Vargas Landeros  ·  Sinaloa, México  ·  {datetime.now().strftime('%d de Mayo, %Y')}")
    style_run(run, size=10, italic=True, color=C_GRAY, font="Calibri")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("NULLSEC RED TEAM FRAMEWORK  ·  DEFCON ELITE LEVEL  ·  CONFIDENCIAL")
    style_run(run, size=8, bold=True, color=C_DARKGOLD, font="Calibri")

    doc.add_paragraph()

    # ── CONTEXTO ──────────────────────────────────────────────────────────────
    add_section_title(doc, "1. CONTEXTO DEL ESCÁNDALO — HECHOS REALES vs. NARRATIVA DE MEDIOS")

    rows_ctx = [
        ("HECHO REAL", "VERSIÓN DE LOS MEDIOS"),
        ("Compra de patrullas ocurrió en 2021",
         "\"Corrupto\" sin contexto temporal"),
        ("Caso se abrió en 2025 — 4 años después — cuando GVL quiso ir al Senado",
         "No contextualizan la brecha de 4 años"),
        ("Rocha Moya amenazó a GVL directamente: 'Si te registras, tengo un expediente'",
         "Minimizan o ignoran la amenaza documentada"),
        ("GVL detenido y liberado en horas — juez no encontró base sólida",
         "Solo cubrieron la detención, no la liberación"),
        ("El senado que GVL buscaba era el de Inzunza — acusado de nexos con narco",
         "No relacionan a Inzunza con el contexto del caso"),
        ("SCJN negó el caso por extemporaneidad procesal, NO por culpabilidad",
         "\"La Corte lo hundió\" — sin matiz legal"),
        ("Desafuero calificado de ilegal e inconstitucional por abogados de GVL",
         "\"El Congreso actuó con justicia\""),
    ]

    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.columns[0].width = Inches(3.1)
    tbl.columns[1].width = Inches(3.1)
    build_table_header(tbl, ["✅  HECHO REAL", "❌  VERSIÓN DE MEDIOS"])
    for i, (real, media) in enumerate(rows_ctx[1:], 1):
        row = tbl.add_row()
        set_cell_bg(row.cells[0], "E8F5E9" if i % 2 else "F1F8E9")
        set_cell_bg(row.cells[1], "FFEBEE" if i % 2 else "FFF3F3")
        set_cell_borders(row.cells[0], "AAAAAA")
        set_cell_borders(row.cells[1], "AAAAAA")
        r0 = row.cells[0].paragraphs[0].add_run(real)
        style_run(r0, size=8, color=C_BLACK)
        r1 = row.cells[1].paragraphs[0].add_run(media)
        style_run(r1, size=8, color=C_DARKRED)

    doc.add_paragraph()

    # ── VECTORES NARRATIVOS ───────────────────────────────────────────────────
    add_section_title(doc, "2. MAPA DE NARRATIVAS NEGATIVAS — 7 VECTORES DE ATAQUE")

    tbl2 = doc.add_table(rows=1, cols=4)
    tbl2.style = "Table Grid"
    tbl2.alignment = WD_TABLE_ALIGNMENT.CENTER
    build_table_header(tbl2, ["VECTOR", "INTENSIDAD", "NARRATIVA ATACANTE", "CONTRARRELATO REAL"])
    for i, (vec, intens, narrativa, contra) in enumerate(NARRATIVES):
        row = tbl2.add_row()
        bg  = "F9F9F9" if i % 2 else "FFFFFF"
        for c in row.cells:
            set_cell_bg(c, bg)
            set_cell_borders(c, "CCCCCC")
        style_run(row.cells[0].paragraphs[0].add_run(vec),      size=8, bold=True, color=C_DARKRED)
        style_run(row.cells[1].paragraphs[0].add_run(intens),   size=8, bold=True, color=C_RED)
        style_run(row.cells[2].paragraphs[0].add_run(narrativa), size=8, color=C_BLACK)
        style_run(row.cells[3].paragraphs[0].add_run(contra),   size=8, color=RGBColor(0x1A,0x5C,0x28))

    doc.add_paragraph()

    # ── POSTS FACEBOOK CONFIRMADOS ────────────────────────────────────────────
    add_section_title(doc, "3. TOP 23 POSTS FACEBOOK CONFIRMADOS — ÚLTIMA SEMANA")

    p_note = doc.add_paragraph()
    r_note = p_note.add_run("Fuentes: medios estatales y locales Sinaloa  ·  Todos los enlaces son directos a Facebook")
    style_run(r_note, size=8, italic=True, color=C_GRAY)

    tbl3 = doc.add_table(rows=1, cols=5)
    tbl3.style = "Table Grid"
    tbl3.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl3.columns[0].width = Inches(0.3)
    tbl3.columns[1].width = Inches(1.3)
    tbl3.columns[2].width = Inches(2.4)
    tbl3.columns[3].width = Inches(0.5)
    tbl3.columns[4].width = Inches(1.2)
    build_table_header(tbl3, ["#", "MEDIO", "NARRATIVA / TITULAR", "DÍAS", "LIGA FACEBOOK"])

    for i, (num, medio, titulo, url, dias, sent) in enumerate(POSTS):
        row = tbl3.add_row()
        bg  = "F9F9F9" if i % 2 else "FFFFFF"
        for c in row.cells:
            set_cell_bg(c, bg)
            set_cell_borders(c, "CCCCCC")
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        style_run(row.cells[0].paragraphs[0].add_run(num),   size=8, bold=True, color=C_GRAY)
        style_run(row.cells[1].paragraphs[0].add_run(medio), size=8, bold=True, color=C_BLUE)
        # Title with sentiment color
        t_color = C_RED if "NEGATIVO" in sent else RGBColor(0x1A,0x5C,0x28) if "POSITIVO" in sent else C_GRAY
        style_run(row.cells[2].paragraphs[0].add_run(titulo), size=7.5, color=t_color)
        style_run(row.cells[3].paragraphs[0].add_run(dias),   size=8, color=C_GRAY)
        # Hyperlink
        add_hyperlink(row.cells[4].paragraphs[0], "→ Abrir en Facebook", url)

    doc.add_paragraph()

    # ── POSTS FECHA CONFIRMADA ─────────────────────────────────────────────────
    add_section_title(doc, "4. POSTS CON FECHA EXACTA CONFIRMADA — 13 al 19 Mayo 2026", level=2)

    tbl4 = doc.add_table(rows=1, cols=5)
    tbl4.style = "Table Grid"
    tbl4.columns[0].width = Inches(0.3)
    tbl4.columns[1].width = Inches(1.3)
    tbl4.columns[2].width = Inches(2.2)
    tbl4.columns[3].width = Inches(0.8)
    tbl4.columns[4].width = Inches(1.1)
    build_table_header(tbl4, ["#", "MEDIO", "NARRATIVA / TITULAR", "FECHA", "LIGA"])

    for i, (num, medio, titulo, url, fecha, sent) in enumerate(RECENT_POSTS):
        row = tbl4.add_row()
        bg  = "F9F9F9" if i % 2 else "FFFFFF"
        for c in row.cells:
            set_cell_bg(c, bg)
            set_cell_borders(c, "CCCCCC")
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        style_run(row.cells[0].paragraphs[0].add_run(num),   size=8, bold=True, color=C_GRAY)
        style_run(row.cells[1].paragraphs[0].add_run(medio), size=8, bold=True, color=C_BLUE)
        style_run(row.cells[2].paragraphs[0].add_run(titulo), size=7.5, color=C_RED)
        style_run(row.cells[3].paragraphs[0].add_run(fecha),  size=8, bold=True, color=C_DARKGOLD)
        add_hyperlink(row.cells[4].paragraphs[0], "→ Abrir", url)

    doc.add_paragraph()

    # ── NEGATIVIDAD POR MEDIO ──────────────────────────────────────────────────
    add_section_title(doc, "5. ANÁLISIS DE NEGATIVIDAD POR MEDIO — SEMANA 14-21 MAYO 2026")

    tbl5 = doc.add_table(rows=1, cols=7)
    tbl5.style = "Table Grid"
    build_table_header(tbl5, ["MEDIO", "TIPO", "ALCANCE FB", "% NEG", "% NEU", "% POS", "NOTAS/SEM"])
    for i, row_data in enumerate(MEDIOS_STATS):
        row = tbl5.add_row()
        bg  = "F9F9F9" if i % 2 else "FFFFFF"
        is_total = row_data[0] == "TOTAL ESTIMADO"
        for j, (c, val) in enumerate(zip(row.cells, row_data)):
            set_cell_bg(c, "FFF0F0" if is_total else bg)
            set_cell_borders(c, "CCCCCC")
            run = c.paragraphs[0].add_run(str(val))
            style_run(run, size=8,
                      bold=is_total or j == 0,
                      color=C_RED if "%" in str(val) and str(val).replace("~","").replace("%","").isdigit() and int(str(val).replace("~","").replace("%","")) > 80
                            else C_DARKRED if is_total
                            else C_BLACK)

    doc.add_paragraph()

    # ── ESTRATEGIA DE RECUPERACIÓN ────────────────────────────────────────────
    add_section_title(doc, "6. ESTRATEGIA DE RECUPERACIÓN — RUTA AL 80% POSITIVO")

    tbl6 = doc.add_table(rows=1, cols=2)
    tbl6.style = "Table Grid"
    tbl6.columns[0].width = Inches(4.8)
    tbl6.columns[1].width = Inches(0.9)
    build_table_header(tbl6, ["ACCIÓN ESTRATÉGICA", "IMPACTO"])
    for i, (accion, impacto) in enumerate(RECOVERY):
        row = tbl6.add_row()
        is_total = "TOTAL" in accion
        bg = "FFF8E1" if is_total else ("F9F9F9" if i % 2 else "FFFFFF")
        set_cell_bg(row.cells[0], bg)
        set_cell_bg(row.cells[1], bg)
        set_cell_borders(row.cells[0], "CCCCCC")
        set_cell_borders(row.cells[1], "CCCCCC")
        r0 = row.cells[0].paragraphs[0].add_run(accion)
        r1 = row.cells[1].paragraphs[0].add_run(impacto)
        style_run(r0, size=8, bold=is_total, color=C_DARKRED if is_total else C_BLACK)
        style_run(r1, size=8, bold=True,
                  color=RGBColor(0x1A,0x5C,0x28) if "✓" in impacto else C_RED)
        row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()

    # ── PIE DE PÁGINA ─────────────────────────────────────────────────────────
    p_footer = doc.add_paragraph()
    p_footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_f = p_footer.add_run(
        f"NULLSEC RED TEAM FRAMEWORK  ·  DEFCON ELITE  ·  "
        f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}  ·  CONFIDENCIAL"
    )
    style_run(run_f, size=7, italic=True, color=C_GRAY)

    # ── GUARDAR ───────────────────────────────────────────────────────────────
    doc.save(OUTPUT)
    print(f"\n  [DOCX] Saved → {OUTPUT}")
    print(f"  [DOCX] {len(POSTS) + len(RECENT_POSTS)} posts con ligas | {len(NARRATIVES)} vectores | {len(RECOVERY)} acciones estratégicas\n")

if __name__ == "__main__":
    build()
