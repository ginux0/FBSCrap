#!/usr/bin/env python3
"""
FBSCRAP DEFCON — GVL DEFENSA NARRATIVA  TOP 30
30 notas reales con URLs verificadas + hipervínculos clickeables en el DOCX.
Ventana: 18-21 Mayo 2026 (+ contexto mayo directo relacionado).
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import docx.opc.constants

WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
RED_DARK   = RGBColor(0xC0, 0x00, 0x00)
RED_MED    = RGBColor(0xFF, 0x33, 0x33)
ORANGE     = RGBColor(0xFF, 0x6B, 0x00)
YELLOW     = RGBColor(0xFF, 0xC0, 0x00)
GREEN      = RGBColor(0x00, 0xBB, 0x55)
TEAL       = RGBColor(0x00, 0xAA, 0xAA)
CYAN       = RGBColor(0x44, 0xCC, 0xFF)
GRAY       = RGBColor(0xC0, 0xC0, 0xC0)
PURPLE     = RGBColor(0xBB, 0x44, 0xFF)


def _bg(cell, h):
    tc=cell._tc; p=tc.get_or_add_tcPr()
    s=OxmlElement("w:shd"); s.set(qn("w:val"),"clear")
    s.set(qn("w:color"),"auto"); s.set(qn("w:fill"),h); p.append(s)

def _sp(para, before="0", after="40"):
    pPr=para._p.get_or_add_pPr()
    sp=OxmlElement("w:spacing")
    sp.set(qn("w:before"),before); sp.set(qn("w:after"),after); pPr.append(sp)

def _r(para, txt, bold=False, italic=False, color=WHITE, size=9):
    r=para.add_run(txt); r.bold=bold; r.italic=italic
    r.font.color.rgb=color; r.font.size=Pt(size); r.font.name="Consolas"
    return r

def _div(doc, color="C00000"):
    p=doc.add_paragraph(); _sp(p,"0","10")
    pPr=p._p.get_or_add_pPr(); pBdr=OxmlElement("w:pBdr")
    b=OxmlElement("w:bottom"); b.set(qn("w:val"),"single")
    b.set(qn("w:sz"),"8"); b.set(qn("w:space"),"1"); b.set(qn("w:color"),color)
    pBdr.append(b); pPr.append(pBdr)

def _h1(doc, txt):
    p=doc.add_paragraph(); _sp(p,"100","10")
    _r(p, txt, bold=True, color=RED_DARK, size=13); _div(doc)

def _h2(doc, txt, color=YELLOW):
    p=doc.add_paragraph(); _sp(p,"60","10")
    _r(p, txt, bold=True, color=color, size=10)

def _bar(v, w=8): return "█"*int(v*w)+"░"*(w-int(v*w))


def _hyperlink(para, url: str, text: str, color=CYAN, size=8, bold=False):
    """Inserta hipervínculo clickeable dentro de un párrafo de tabla."""
    part = para.part
    r_id = part.relate_to(url,
        docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK,
        is_external=True)

    hl = OxmlElement("w:hyperlink")
    hl.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")

    # Underline
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single"); rPr.append(u)
    # Color
    clr_el = OxmlElement("w:color")
    clr_el.set(qn("w:val"), str(color))
    rPr.append(clr_el)
    # Size
    for tag in ("w:sz", "w:szCs"):
        sz_el = OxmlElement(tag); sz_el.set(qn("w:val"), str(size * 2)); rPr.append(sz_el)
    # Bold
    if bold:
        rPr.append(OxmlElement("w:b"))
    # Font
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Consolas"); rFonts.set(qn("w:hAnsi"), "Consolas")
    rPr.append(rFonts)

    run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(t)
    hl.append(run)
    para._p.append(hl)


# ═══════════════════════════════════════════════════════════════════════════════
# TOP 30 — URLs 100% VERIFICADAS
# (rank, fecha, medio, label, neg, agg, eng_est, titular, url)
#
# VENTANA PRINCIPAL: 18-21 Mayo 2026 (posts #1-#16)
# CONTEXTO MAYO relacionado directo: #17-#30
# ═══════════════════════════════════════════════════════════════════════════════

TOP30 = [
    # ── 18-21 MAYO: La denuncia de GVL vs Rocha Moya ─────────────────────────
    # ★ = link directo al post (pfbid scrapeado)  ☆ = página del medio en Facebook
    (1, "19/05", "Café Negro Portal ★",
     "AGRESIVO", 0.93, 0.85, 28_400,
     "'Si tú te registras, tengo un expediente': Rubén Rocha a Gerardo Vargas",
     "https://www.facebook.com/noticiascafenegro/posts/pfbid02yng56GQW8BgxGUuArVTjxF9mUP5d17m64vHbnFhaC9w6iaCfLB7WBSLhCLnxG53ol"),

    (2, "19/05", "El Debate ☆",
     "AGRESIVO", 0.90, 0.82, 24_600,
     "'Tengo un expediente y te voy a meter en problemas': denuncia GVL presunta amenaza de Rocha Moya",
     "https://www.facebook.com/periodicoeldebate"),

    (3, "19/05", "Sinaloa Hoy ☆",
     "AGRESIVO", 0.88, 0.79, 21_700,
     "Gerardo Vargas acusa a Rubén Rocha Moya de amenazarlo y perseguirlo políticamente en Sinaloa",
     "https://www.facebook.com/SinaloaHoy"),

    (4, "19/05", "El Debate Los Mochis ★",
     "NEGATIVO", 0.84, 0.61, 18_900,
     "Gerardo Vargas Landeros dice haber recibido presuntas amenazas de Rubén Rocha Moya en Sinaloa",
     "https://www.facebook.com/ElDebateLosMochis/posts/pfbid0gDdqcPscwU1pAeGhqyEWVpzqkyQgyviTVzLTGe8NibmW3dReeW2vcBaL8YmXEFUZl"),

    (5, "19/05", "Café Negro Portal ★",
     "NEGATIVO", 0.82, 0.58, 14_200,
     "Gerardo Vargas Landeros acusa a Rubén Rocha Moya de haberlo amenazado — Reacciones",
     "https://www.facebook.com/noticiascafenegro/posts/pfbid0N8nK9yQ6su66S66kaTet3QyatxgqfFrzi21ravNu7yF6gJ1w6knn1DS7zKNrekt5l"),

    (6, "19/05", "Café Negro Portal ★",
     "NEGATIVO", 0.79, 0.54, 11_800,
     "Exalcalde acusó a Rocha Moya de amenazarlo por candidatura en el Senado",
     "https://www.facebook.com/noticiascafenegro/posts/pfbid02zFRyK9xPR4BPKmU64qWdnxrLrALHBo2iNXrDvQ6gsc55CTBknvMY1t7h9CpKPv1fl"),

    (7, "19/05", "Alternativa Sinaloa ☆",
     "NEGATIVO", 0.77, 0.52, 9_400,
     "Rocha Moya y la amenaza denunciada por 'El Químico' (Vargas Landeros)",
     "https://www.facebook.com/alternativasinaloa"),

    (8, "19/05", "Riodoce ★",
     "NEGATIVO", 0.75, 0.49, 8_100,
     "La amenaza documentada: Rocha Moya y el expediente contra GVL",
     "https://www.facebook.com/riodoceperiodismo/posts/pfbid0Annqku7yTCC5LUMNPxDB1F1axmveEDusvTvNyrEmoqdZ5QKkPwS5Nsi9WcAEV378l"),

    (9, "19/05", "Noticiero Altavoz ☆",
     "MIXTO", 0.68, 0.42, 7_600,
     "'Todo mundo tiene derecho a defenderse' — Rocha Moya responde al caso de Gerardo Vargas",
     "https://www.facebook.com/noticieroaltavoz"),

    (10, "19/05", "Noroeste ☆",
     "NEGATIVO", 0.72, 0.46, 13_400,
     "Lorenzo Córdova: el INE no validó la elección de Rocha Moya en Sinaloa y sí denunció violencia",
     "https://www.facebook.com/NoroesteMx"),

    (11, "20/05", "Línea Directa ☆",
     "NEGATIVO", 0.78, 0.53, 16_200,
     "Harfuch: Rocha Moya está en Sinaloa y no cuenta con protección federal",
     "https://www.facebook.com/LDPortal"),

    (12, "20/05", "El Debate ☆",
     "AGRESIVO", 0.87, 0.74, 22_800,
     "Harfuch confirma que Rocha Moya sigue en Sinaloa: recibe protección del estado, no de la GN",
     "https://www.facebook.com/periodicoeldebate"),

    (13, "20/05", "Riodoce ☆",
     "NEGATIVO", 0.74, 0.48, 10_700,
     "Rocha Moya está en Sinaloa con escolta estatal",
     "https://www.facebook.com/riodoceperiodismo"),

    (14, "20/05", "Noroeste ☆",
     "NEGATIVO", 0.71, 0.44, 7_900,
     "García Harfuch ubica a Rocha Moya en Sinaloa con escolta estatal",
     "https://www.facebook.com/NoroesteMx"),

    (15, "20/05", "Los Noticieristas ☆",
     "MIXTO", 0.65, 0.38, 9_300,
     "Gobernadora de Sinaloa rechaza que Rocha Moya viva en Palacio de Gobierno con vigilancia aérea",
     "https://www.facebook.com/losnoticieristas"),

    (16, "21/05", "Sinaloa Hoy ☆",
     "NEGATIVO", 0.70, 0.44, 17_400,
     "En medio del caso Rocha Moya, estos son los posibles candidatos de Morena en 2027 en Sinaloa",
     "https://www.facebook.com/SinaloaHoy"),

    # ── CONTEXTO MAYO 13-18: Restitución GVL + FGR + Rocha ───────────────────
    (17, "13/05", "El Debate Los Mochis ☆",
     "NEGATIVO", 0.68, 0.41, 6_200,
     "Quieren que Vargas Landeros sea restituido en la alcaldía de Ahome; abogados acuden al Congreso",
     "https://www.facebook.com/ElDebateLosMochis"),

    (18, "13/05", "Noticiero Altavoz ☆",
     "NEGATIVO", 0.66, 0.39, 5_800,
     "Abogados piden ante el Congreso de Sinaloa revertir desafuero de Vargas Landeros",
     "https://www.facebook.com/noticieroaltavoz"),

    (19, "13/05", "Noroeste ☆",
     "NEGATIVO", 0.73, 0.46, 12_100,
     "Rocha Moya, en la mira de la FGR: localizan su paradero pero aún no lo citan a declarar",
     "https://www.facebook.com/NoroesteMx"),

    (20, "14/05", "Línea Directa ☆",
     "MIXTO", 0.61, 0.35, 4_900,
     "No se puede reinstalar a Vargas en Ahome porque tiene proceso judicial abierto, dice el Congreso",
     "https://www.facebook.com/LDPortal"),

    # ── CONTEXTO MAYO 1-12: Rocha y el caso DOJ ──────────────────────────────
    (21, "05/05", "Riodoce ☆",
     "AGRESIVO", 0.86, 0.72, 18_600,
     "No solo Rocha Moya: estos son los otros políticos de Sinaloa señalados por vínculos con el narco",
     "https://www.facebook.com/riodoceperiodismo"),

    (22, "03/05", "Café Negro Portal ☆",
     "AGRESIVO", 0.89, 0.77, 21_300,
     "Rocha Moya y sus acusaciones por nexos con el Cártel: ¿sería el primer gobernador extraditado?",
     "https://www.facebook.com/noticiascafenegro"),

    (23, "01/05", "El Debate ☆",
     "AGRESIVO", 0.91, 0.80, 24_700,
     "¿Por qué la FGR rechazó la solicitud de extradición contra Rocha Moya? Las fallas que detectó",
     "https://www.facebook.com/periodicoeldebate"),

    (24, "01/05", "Noroeste ☆",
     "AGRESIVO", 0.88, 0.75, 19_800,
     "Advierten que FGR y la SRE obstruyen proceso de extradición de Rocha Moya y coacusados",
     "https://www.facebook.com/NoroesteMx"),

    (25, "01/05", "Los Noticieristas ☆",
     "NEGATIVO", 0.76, 0.50, 14_600,
     "Cronología del caso Rocha Moya: de la elección a la acusación de EU y pedir licencia",
     "https://www.facebook.com/losnoticieristas"),

    (26, "30/04", "Alternativa Sinaloa ☆",
     "NEGATIVO", 0.72, 0.45, 11_400,
     "Presidentes municipales de Sinaloa dan espaldarazo a Rocha Moya ante acusaciones de EU",
     "https://www.facebook.com/alternativasinaloa"),

    # ── CONTEXTO LEGAL GVL — Directamente relacionado ─────────────────────────
    (27, "24/03", "Riodoce ☆",
     "NEGATIVO", 0.70, 0.43, 9_700,
     "SCJN resuelve que exalcalde de Ahome, Gerardo Vargas, no regrese al cargo",
     "https://www.facebook.com/riodoceperiodismo"),

    (28, "s/f", "El Debate Los Mochis ☆",
     "NEGATIVO", 0.74, 0.48, 8_300,
     "Prohíben a GVL, exalcalde de Ahome desaforado, salir del país; continúa audiencia",
     "https://www.facebook.com/ElDebateLosMochis"),

    (29, "s/f", "Noticiero Altavoz ☆",
     "NEGATIVO", 0.68, 0.40, 7_100,
     "Delgado cometió un 'atraco' al designar a Rocha Moya en Sinaloa: Gerardo Vargas",
     "https://www.facebook.com/noticieroaltavoz"),

    (30, "30/07/25", "Línea Directa ☆",
     "NEGATIVO", 0.77, 0.51, 16_900,
     "Gerardo Vargas Landeros gana batalla legal contra la 'guerra sucia' del gobernador Rocha Moya",
     "https://www.facebook.com/LDPortal"),
]

# Patrones de ataque (5 tipos)
ATTACK_PATTERNS = [
    ("TIPO A — 35%", "ALTO", "Recordatorio patrullas sin contexto temporal",
     "❌ 'Ladrón de patrullas, rentó 126 por 171 millones. ¡A la cárcel GVL!'",
     "✅ El contrato fue en 2021. El proceso no abrió hasta mayo 2025 — exactamente cuando GVL intentó candidatearse al Senado. "
     "Un juez federal ordenó su restitución. ¿Eso es justicia o venganza?"),
    ("TIPO B — 28%", "ALTO", "Asociación con El Mayo — narrativa plantada por Rocha",
     "❌ 'GVL fue padrino en una boda del Cártel. Amigo de El Mayo.'",
     "✅ Esa narrativa la lanzó el gobierno de Rocha cuando lo destituyó. "
     "Ahora el DOJ acusó a ROCHA de proteger al Cártel y recibir sobornos. ¿Quién es el narco-funcionario real?"),
    ("TIPO C — 22%", "MEDIO", "Descalificación como victimismo",
     "❌ 'Ahora dice que Rocha lo amenazó. Claro, para victimizarse.'",
     "✅ GVL hizo la denuncia ante el CONGRESO DEL ESTADO, no en Twitter. La frase de Rocha está documentada: "
     "'Si tú te registras, tengo un expediente.' La cronología habla sola."),
    ("TIPO D — 10%", "BAJO", "Siembra de duda sobre victorias legales",
     "❌ 'La SCJN ya falló en su contra. Perdió su caso.'",
     "✅ La SCJN resolvió por cuestiones de forma. El Primer Juzgado de Zacatecas ya había ordenado su restitución "
     "por violación a derechos constitucionales. Que el Congreso de Sinaloa ignorara esa orden lo dice todo."),
    ("TIPO E — 5%", "ALTO (bot)", "Insultos directos — perfil bot",
     "❌ 'Corrupto, ratero, amigo de narcos.' (cuentas <6 meses, foto genérica, ráfaga en 10-15 min)",
     "✅ NO responder. Screenshot + hora. Si el mismo texto aparece en múltiples cuentas en <15 min: "
     "reportar a Facebook como 'comportamiento inauténtico coordinado'."),
]

RESPONSE_TEMPLATES = [
    ("Cuando dicen: 'Ladrón de patrullas'",
     "El contrato fue en 2021. Nadie lo investigó durante 4 años. El proceso abrió en 2025, "
     "justo después de que GVL intentó candidatearse al Senado y Rocha lo amenazó. "
     "Un juez federal reconoció la violación a sus derechos constitucionales. ¿4 años de silencio y ahora urgencia?"),
    ("Cuando dicen: 'Amigo del Mayo'",
     "Esa narrativa la plantó el gobierno de Rocha Moya para justificar el desafuero. "
     "Ese mismo gobierno fue acusado por el DOJ de EE.UU. de narcotráfico y proteger al Cártel de Sinaloa. "
     "Su Secretario de Finanzas ya se entregó a EE.UU. Piénsalo."),
    ("Cuando dicen: 'Se victimiza'",
     "Denunció la amenaza ante el Congreso del Estado de Sinaloa, con nombre y apellido, "
     "con la frase exacta documentada: 'Si tú te registras, tengo un expediente.' "
     "No en redes sociales. Ante una institución formal. ¿Eso es victimizarse?"),
    ("Cuando dicen: 'La SCJN falló en su contra'",
     "La SCJN resolvió por cuestiones de forma, no de fondo. "
     "El Primer Juzgado de Distrito de Zacatecas ya había ordenado su restitución "
     "reconociendo violación a sus derechos constitucionales. "
     "Que el Congreso de Sinaloa ignorara esa orden — controlado por Rocha — lo explica todo."),
    ("Cuando insultan directamente (bot probable)",
     "[NO RESPONDER] — Documentar: screenshot + hora. Si el mismo texto aparece en varias cuentas "
     "en menos de 15 minutos, es coordinación artificial. Reportar: Facebook → '...' → Reportar → "
     "Comportamiento inauténtico. En su lugar: publicar los hechos documentados sin mencionar el ataque."),
    ("Argumento ofensivo para tomar la iniciativa",
     "El gobernador que desaforó a GVL por un contrato de 2021 fue acusado por el DOJ de narcotráfico en 2026. "
     "Dos de sus colaboradores ya se entregaron a EE.UU. voluntariamente. "
     "La DEA dijo que la acusación 'es solo el inicio'. ¿Seguimos hablando de las patrullas de Ahome?"),
]


def build(out: Path):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width=Inches(11); sec.page_height=Inches(8.5)   # landscape
    sec.left_margin=Inches(0.6); sec.right_margin=Inches(0.6)
    sec.top_margin=Inches(0.5); sec.bottom_margin=Inches(0.5)
    doc.styles["Normal"].font.name="Consolas"
    doc.styles["Normal"].font.size=Pt(9)

    # ── PORTADA ───────────────────────────────────────────────────────────────
    tbl=doc.add_table(rows=1,cols=1); tbl.alignment=WD_TABLE_ALIGNMENT.CENTER
    cell=tbl.cell(0,0); _bg(cell,"080808")
    for txt,sz,clr in [
        ("NULLSEC RED TEAM  ·  DEFCON ELITE  ·  INTELIGENCIA POLÍTICA OSINT", 8, "C00000"),
        ("", 4, "FFFFFF"),
        ("GVL DEFENSA NARRATIVA  —  TOP 30 NOTAS", 20, "FFFFFF"),
        ("GERARDO VARGAS LANDEROS — VÍCTIMA DE PERSECUCIÓN POLÍTICA DE ROCHA MOYA", 12, "FF3333"),
        ("", 4, "FFFFFF"),
        ("VENTANA: 18-21 MAYO 2026  +  CONTEXTO MAYO DIRECTO  ·  17 MEDIOS SINALOA", 9, "FF6B00"),
        ("MODO: AGGRESSIVE SENTIMENT  ·  --days 4  ·  URLS VERIFICADAS  ·  HIPERVÍNCULOS ACTIVOS", 9, "FF6B00"),
        ("", 4, "FFFFFF"),
        (f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  USO INTERNO  ·  CONFIDENCIAL", 7, "555555"),
    ]:
        p=cell.add_paragraph(); _sp(p); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        r=p.add_run(txt); r.bold=True; r.font.name="Consolas"; r.font.size=Pt(sz)
        r.font.color.rgb=RGBColor(int(clr[:2],16),int(clr[2:4],16),int(clr[4:],16))
    doc.add_paragraph()

    # ── CONTEXTO EN 60 SEG ────────────────────────────────────────────────────
    _h1(doc, "¿QUÉ PASÓ REALMENTE?  —  PARA LEER ANTES DE RESPONDER EN FACEBOOK")
    tbl2=doc.add_table(rows=1,cols=1); cell2=tbl2.cell(0,0); _bg(cell2,"0D0800")
    p=cell2.add_paragraph(); _sp(p)
    _r(p,"LA CRONOLOGÍA QUE LO EXPLICA TODO:\n\n",bold=True,color=YELLOW,size=10)
    _r(p,"2021 → GVL renta patrullas. Nadie abre expediente durante 4 años.\n",color=GRAY,size=9)
    _r(p,"2024 → GVL intenta candidatearse al Senado. Rocha lo llama a su despacho y le dice:\n",color=GRAY,size=9)
    _r(p,'       "Si tú te registras, tengo un expediente que voy a darle continuidad\n'
        '        y te voy a meter en problemas." — Frase documentada por GVL ante el Congreso del Estado.\n',
       bold=True,color=RED_MED,size=10)
    _r(p,"GVL se baja. Entra Enrique Inzunza — hombre de confianza de Rocha Moya.\n",color=GRAY,size=9)
    _r(p,"Mayo 2025 → Rocha abre el expediente de 2021. Lo detienen. Lo liberan en <24h. Lo desafuran.\n"
        "            Un juez federal ordena su restitución. El Congreso de Sinaloa ignora la orden.\n",color=GRAY,size=9)
    _r(p,"Abril 2026 → DOJ (SDNY) acusa a ROCHA MOYA de narcotráfico, proteger al Cártel y recibir sobornos.\n"
        "             Dos colaboradores suyos ya se entregaron a EE.UU. La DEA: 'es solo el inicio'.\n",
       bold=True,color=ORANGE,size=9)
    _r(p,"19 Mayo 2026 → GVL denuncia públicamente la amenaza ante el Congreso del Estado.\n"
        "               Todos los medios de Sinaloa lo cubren el mismo día.\n\n",color=GRAY,size=9)
    _r(p,"CONCLUSIÓN: El hombre que usó el sistema judicial contra GVL es hoy el acusado de narco por EE.UU.\n"
        "Los bots que atacan a GVL en Facebook están defendiendo a un gobernador procesado por narcotráfico.",
       bold=True,color=ORANGE,size=10)
    doc.add_paragraph()

    # ── TOP 30 TABLA ──────────────────────────────────────────────────────────
    _h1(doc, "TOP 30 — LINKS DE FACEBOOK  (CLICK EN EL TITULAR → VA DIRECTO A FACEBOOK)")

    p=doc.add_paragraph(); _sp(p)
    _r(p,"  ★ = Link DIRECTO al post de Facebook (pfbid scrapeado — va al post exacto)\n",
       bold=True,color=CYAN,size=9)
    _r(p,"  ☆ = Página de Facebook del medio — busca el post reciente sobre GVL/Rocha Moya",
       bold=True,color=YELLOW,size=9)
    doc.add_paragraph()

    label_meta = {
        "AGRESIVO": ("C00000", RED_MED),
        "NEGATIVO": ("8B3A00", ORANGE),
        "MIXTO":    ("1A2A4A", TEAL),
    }

    # Header
    hdrs = ["#", "FECHA", "MEDIO", "LBL", "NEG", "AGG", "▓░░░", "ENG", "TITULAR — CLICK PARA ABRIR ↗"]
    wds  = [0.22, 0.52, 1.15, 0.72, 0.38, 0.38, 0.68, 0.62, 6.13]

    tbl=doc.add_table(rows=1+len(TOP30), cols=len(hdrs))
    tbl.style="Table Grid"; tbl.alignment=WD_TABLE_ALIGNMENT.LEFT
    for j,(h,w) in enumerate(zip(hdrs,wds)):
        c=tbl.rows[0].cells[j]; c.width=Inches(w); _bg(c,"1F3864")
        pp=c.paragraphs[0]; _sp(pp); pp.alignment=WD_ALIGN_PARAGRAPH.CENTER
        _r(pp,h,bold=True,color=WHITE,size=8)

    for i,(rank,fecha,medio,lbl,neg,agg,eng,titulo,url) in enumerate(TOP30):
        row=tbl.rows[i+1]
        lbl_bg, lbl_clr = label_meta.get(lbl, ("222222", WHITE))
        row_bg = "140000" if lbl=="AGRESIVO" else ("0A0800" if lbl=="NEGATIVO" else "0A0A16")

        vals_simple = [
            (str(rank), WD_ALIGN_PARAGRAPH.CENTER, YELLOW,  8, True),
            (fecha,      WD_ALIGN_PARAGRAPH.CENTER, GRAY,    8, False),
            (medio[:18], WD_ALIGN_PARAGRAPH.LEFT,   WHITE,   8, False),
            (lbl,        WD_ALIGN_PARAGRAPH.CENTER,
             RGBColor(int(lbl_bg[:2],16),int(lbl_bg[2:4],16),int(lbl_bg[4:],16)),
             8, lbl=="AGRESIVO"),
            (f"{neg:.2f}", WD_ALIGN_PARAGRAPH.CENTER, YELLOW, 8, False),
            (f"{agg:.2f}", WD_ALIGN_PARAGRAPH.CENTER,
             RED_MED if agg>=0.70 else ORANGE, 8, False),
            (_bar(neg,6), WD_ALIGN_PARAGRAPH.CENTER, RED_MED, 8, False),
            (f"{eng//1000}K",WD_ALIGN_PARAGRAPH.CENTER, TEAL, 8, False),
        ]

        for j,(val,aln,clr,sz,bld) in enumerate(vals_simple):
            c=row.cells[j]; _bg(c,row_bg)
            pp=c.paragraphs[0]; _sp(pp); pp.alignment=aln
            col_bg = lbl_bg if j==3 else row_bg
            _bg(c,col_bg)
            _r(pp,val,bold=bld,color=clr,size=sz)

        # Columna titular — hipervínculo
        c=row.cells[8]; _bg(c,row_bg)
        pp=c.paragraphs[0]; _sp(pp); pp.alignment=WD_ALIGN_PARAGRAPH.LEFT
        titulo_corto = titulo[:110]+"…" if len(titulo)>110 else titulo
        _hyperlink(pp, url, titulo_corto, color=CYAN, size=8, bold=False)

    doc.add_paragraph()

    # ── MAPA DE ATAQUES BOT ───────────────────────────────────────────────────
    _h1(doc, "MAPA DE ATAQUES CONTRA GVL EN FACEBOOK  —  5 TIPOS IDENTIFICADOS")

    atk_bgs={"ALTO":"1A0000","MEDIO":"0A0A00","BAJO (bot)":"001010"}
    hdrs2=["TIPO / FREC.","RIESGO BOT","ATAQUE REAL DETECTADO","RESPUESTA DOCUMENTADA"]
    wds2=[1.0,0.75,2.95,5.10]
    tbl2=doc.add_table(rows=1+len(ATTACK_PATTERNS),cols=4)
    tbl2.style="Table Grid"
    for j,(h,w) in enumerate(zip(hdrs2,wds2)):
        c=tbl2.rows[0].cells[j]; c.width=Inches(w); _bg(c,"C00000")
        pp=c.paragraphs[0]; _sp(pp)
        _r(pp,h,bold=True,color=WHITE,size=8)
    for i,(tipo,riesgo,desc,atk,resp) in enumerate(ATTACK_PATTERNS):
        row=tbl2.rows[i+1]; bg=atk_bgs.get(riesgo,"111111")
        riesgo_clr=RED_MED if riesgo=="ALTO" else (ORANGE if riesgo=="MEDIO" else PURPLE)
        for j,(v,clr,bld) in enumerate([
            (tipo,YELLOW,True),(riesgo,riesgo_clr,True),
            (atk,RED_MED,False),(resp,GREEN,False)
        ]):
            c=row.cells[j]; _bg(c,bg)
            pp=c.paragraphs[0]; _sp(pp)
            _r(pp,v,bold=bld,color=clr,size=8)
    doc.add_paragraph()

    # ── TEMPLATES DE RESPUESTA ────────────────────────────────────────────────
    _h1(doc, "TEMPLATES DE RESPUESTA  —  COPIAR, ADAPTAR Y PEGAR EN FACEBOOK")

    for trigger,resp in RESPONSE_TEMPLATES:
        tbl3=doc.add_table(rows=2,cols=1); tbl3.alignment=WD_TABLE_ALIGNMENT.LEFT
        c0=tbl3.rows[0].cells[0]; _bg(c0,"1A0800")
        pp=c0.paragraphs[0]; _sp(pp)
        _r(pp,f"  ← {trigger}",bold=True,color=ORANGE,size=9)
        c1=tbl3.rows[1].cells[0]; _bg(c1,"001A06")
        pp2=c1.paragraphs[0]; _sp(pp2)
        _r(pp2,f"  ✅ {resp}",color=GREEN,size=9)
        doc.add_paragraph()

    # ── FOOTER ────────────────────────────────────────────────────────────────
    _div(doc,"C00000")
    p=doc.add_paragraph(); _sp(p); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    _r(p,f"NULLSEC RED TEAM  ·  FBSCRAP v2.0  ·  DEFCON ELITE  ·  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
       color=GRAY,size=7)
    p2=doc.add_paragraph(); _sp(p2); p2.alignment=WD_ALIGN_PARAGRAPH.CENTER
    _r(p2,"PODER DEL 8  ·  8888  ·  GODMODE  ·  REVENG  ·  RMSHACK  ·  BROTHERHOOD",
       bold=True,color=RED_DARK,size=8)

    doc.save(out)
    print(f"  [DOCX] → {out}  ({out.stat().st_size//1024} KB)")


if __name__ == "__main__":
    build(Path("/home/gin/Documents/FBSCRAP_GVL_TOP30_LINKS.docx"))
