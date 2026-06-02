"""
NULLSEC — Generador de Playbook de Contraofensiva Narrativa
Mismo engine DOCX que fbscrap. Corre standalone:
  python3 gen_playbook.py
Genera: sessions/playbook/PLAYBOOK_GVL_CONTRAOFENSIVA.docx
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


# ── Paleta idéntica a docx_reporter ──────────────────────────────────────────
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


# ── Helpers (mismos que docx_reporter) ───────────────────────────────────────

def _bg(cell, h: str) -> None:
    tc = cell._tc
    pr = tc.get_or_add_tcPr()
    s  = OxmlElement("w:shd")
    s.set(qn("w:val"),   "clear")
    s.set(qn("w:color"), "auto")
    s.set(qn("w:fill"),  h)
    pr.append(s)


def _sp(para, before: str = "0", after: str = "40") -> None:
    pPr = para._p.get_or_add_pPr()
    sp  = OxmlElement("w:spacing")
    sp.set(qn("w:before"), before)
    sp.set(qn("w:after"),  after)
    pPr.append(sp)


def _r(para, txt: str, bold: bool = False, italic: bool = False,
       color: RGBColor = WHITE, size: int = 9):
    run = para.add_run(txt)
    run.bold         = bold
    run.italic       = italic
    run.font.color.rgb = color
    run.font.size    = Pt(size)
    run.font.name    = "Consolas"
    return run


def _div(doc: Document, color: str = "C00000") -> None:
    p   = doc.add_paragraph()
    _sp(p, "0", "10")
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    b    = OxmlElement("w:bottom")
    b.set(qn("w:val"),   "single")
    b.set(qn("w:sz"),    "8")
    b.set(qn("w:space"), "1")
    b.set(qn("w:color"), color)
    pBdr.append(b)
    pPr.append(pBdr)


def _h1(doc: Document, txt: str) -> None:
    p = doc.add_paragraph()
    _sp(p, "100", "10")
    _r(p, txt, bold=True, color=RED_DARK, size=13)
    _div(doc)


def _h2(doc: Document, txt: str, color: RGBColor = YELLOW) -> None:
    p = doc.add_paragraph()
    _sp(p, "60", "10")
    _r(p, f"  {txt}", bold=True, color=color, size=10)
    _div(doc, "555555")


def _box(doc: Document, bg: str, lines: list[tuple[str, RGBColor, int, bool, bool]]) -> None:
    """Single-cell dark box with multiple styled lines."""
    tbl = doc.add_table(rows=1, cols=1)
    c   = tbl.cell(0, 0)
    _bg(c, bg)
    p   = c.add_paragraph()
    _sp(p)
    for txt, clr, sz, bld, itl in lines:
        _r(p, txt, bold=bld, italic=itl, color=clr, size=sz)
    doc.add_paragraph()


def _table(doc: Document, headers: list[str], widths: list[float],
           rows: list[list[tuple[str, RGBColor, bool]]],
           hdr_bg: str = "1F3864", row_bg: str = "0A0A10",
           alt_bg: str = "080810") -> None:
    """Generic table builder matching fbscrap style."""
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.style     = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT

    for j, (h, w) in enumerate(zip(headers, widths)):
        c  = tbl.rows[0].cells[j]
        c.width = Inches(w)
        _bg(c, hdr_bg)
        pp = c.paragraphs[0]
        _sp(pp)
        _r(pp, h, bold=True, color=WHITE, size=8)

    for i, row_data in enumerate(rows):
        bg = row_bg if i % 2 == 0 else alt_bg
        for j, (val, clr, bld) in enumerate(row_data):
            c  = tbl.rows[i + 1].cells[j]
            _bg(c, bg)
            pp = c.paragraphs[0]
            _sp(pp)
            _r(pp, val, bold=bld, color=clr, size=8)

    doc.add_paragraph()


# ══════════════════════════════════════════════════════════════════════════════
# CONTENIDO DEL PLAYBOOK
# ══════════════════════════════════════════════════════════════════════════════

_REGLAS_ORO = [
    (
        "REGLA 1  —  HECHOS, NO EMOCIONES",
        "SIEMPRE",
        "Cualquier comentario",
        (
            "Un comentario basado en hechos documentados vale 10 veces más que uno enojado.\n"
            "Si el post dice 'robó 50 millones' — pregunta: ¿cuándo? ¿qué expediente? ¿qué juzgado?\n"
            "El hecho de que no tengan respuesta ya es tu victoria. NO necesitas insultar."
        ),
    ),
    (
        "REGLA 2  —  NUNCA REPETIR LA ACUSACIÓN",
        "CRÍTICA",
        "Siempre que vayas a negar algo",
        (
            "Si dices 'GVL NO es corrupto' — refuerzas la palabra CORRUPTO en la mente del lector.\n"
            "En su lugar: '¿Cuándo exactamente? ¿Ante qué institución? La cronología importa.'\n"
            "Técnica: REDIRIGIR, no NEGAR. Nunca repitas la narrativa del atacante."
        ),
    ),
    (
        "REGLA 3  —  UN SOLO MENSAJE CLAVE POR DÍA",
        "ESTRATÉGICA",
        "Coordinación de equipo",
        (
            "Todos el mismo día refuerzan el mismo punto. Ejemplo: lunes = obra pública documentada.\n"
            "El algoritmo de Facebook premia consistencia temática. La repetición ORGÁNICA persuade.\n"
            "No improvisar. El coordinador define el mensaje del día ANTES de que el equipo actúe."
        ),
    ),
    (
        "REGLA 4  —  NEVER FEED THE TROLL",
        "ABSOLUTA",
        "Con bots y provocadores",
        (
            "Un bot o un troll quiere que respondas con enojo — cada respuesta enojada es su victoria.\n"
            "Protocolo: SCREENSHOT + REPORTE FB + IGNORAR. No debatir con cuentas bot.\n"
            "Si parece humano y argumenta mal: UNA respuesta factual, luego silencio total."
        ),
    ),
    (
        "REGLA 5  —  PROPOSITIVO SIEMPRE",
        "IMAGEN",
        "Todo comentario público",
        (
            "Cada comentario debe terminar con algo que GVL SÍ ha hecho o propone hacer.\n"
            "Ejemplo: '...y mientras tanto, en [colonia] se inauguró [obra] el [fecha].'\n"
            "La ciudadanía recuerda lo que construyes, no lo que niegas."
        ),
    ),
    (
        "REGLA 6  —  EL COMENTARIO INVISIBLE",
        "AVANZADA",
        "Notas con > 200 comentarios negativos",
        (
            "No combatas en terreno del enemigo. Haz un POST PROPIO con los hechos documentados\n"
            "y COMPÁRTELO en los comentarios de la nota atacante. Un enlace a tu contenido\n"
            "saca al lector del ecosistema del ataque y lo lleva a tu narrativa."
        ),
    ),
    (
        "REGLA 7  —  IDENTIDAD REAL = CREDIBILIDAD",
        "FUNDAMENTAL",
        "Todo el equipo",
        (
            "Fotos de perfil reales, nombre completo visible, historial de publicaciones normales.\n"
            "Una cuenta que parece humana y tiene historial pesa MÁS que 10 cuentas nuevas.\n"
            "El equipo NO crea cuentas falsas. Usa tu perfil real — eso es la diferencia vs los bots."
        ),
    ),
    (
        "REGLA 8  —  DOCUMENTA TODO",
        "OPERACIONAL",
        "Antes de responder",
        (
            "Antes de comentar algo, asegúrate de tener la fuente a 2 clics de distancia.\n"
            "Si alguien te pide la fuente y no la tienes: pierdes credibilidad inmediatamente.\n"
            "Carpeta compartida del equipo con: fechas, obras, declaraciones, PDFs, screenshots."
        ),
    ),
]

_REACCION_NOTAS = [
    (
        "TIPO A\nACUSACIÓN\nSIN PRUEBA",
        "Alto impacto",
        "Pregunta la cronología",
        "\"Fecha exacta del acto, fecha de la denuncia, quién denunció y por qué exactamente ahora. Sin esos 3 datos, no hay caso — solo narrativa.\"",
        "Si hay 3+ años de silencio antes de la denuncia — ese silencio lo explica todo. Señálalo con fecha.",
    ),
    (
        "TIPO B\nASO. CRIMINAL\n(narco / cartel)",
        "Máximo impacto",
        "Invierte la pregunta",
        "\"¿La fuente es el DOJ, la DEA o el SDNY? ¿O es una declaración del gobierno rival? No es lo mismo. Exige verificación.\"",
        "Documentar si el acusador tiene señalamientos propios. La simetría de evidencia es tu arma.",
    ),
    (
        "TIPO C\nINSULTO DIRECTO\n(ratero, corrupto)",
        "Bot probable",
        "NO RESPONDER al insulto",
        "Screenshot + reporte FB. En tu propio muro: publica UNA pieza de hechos documentados. Sin mencionar el insulto.",
        "Los insultos sin argumento confirman que el atacante no tiene contrarrelato factual. Tu silencio + tus hechos los destruye.",
    ),
    (
        "TIPO D\nARGUMENTO\nJUDICIAL",
        "Medio impacto",
        "Separa FORMA de FONDO",
        "\"Una resolución por extemporaneidad procesal NO es una declaración de culpabilidad. ¿Cuál es exactamente la resolución de fondo?\"",
        "Proceso abierto ≠ culpabilidad. Afirmar que 'ya está resuelto' cuando el proceso sigue es desinformación verificable.",
    ),
    (
        "TIPO E\nCOMPARAC. CON\nOTROS POLÍTICOS",
        "Bajo impacto",
        "Acepta y supera",
        "\"Tienes razón en señalar a X — y también merece escrutinio. Ahora bien, ¿qué hace diferente a GVL? [hecho concreto + fecha]\"",
        "Nunca defiendes comparando con otros. Solo con hechos propios. La comparación es trampa retórica.",
    ),
    (
        "TIPO F\nDESSINFO\nDE OBRA PÚBLICA",
        "Medio impacto",
        "Foto + fecha + lugar",
        "\"[Foto/video de la obra] + dirección exacta + fecha de inauguración. ¿Quieres las coordenadas GPS?\"",
        "Una imagen con geolocalización vale más que 1000 palabras. El equipo debe tener banco de imágenes listo.",
    ),
]

_EMOJI_STRATEGY = [
    ("👍 Me gusta",      "SÍ — prioritario",  "Boost al alcance orgánico del comentario. Primero en reaccionar es el que más ayuda."),
    ("❤️ Me encanta",    "SÍ — selectivo",    "Usar en comentarios que conecten emocionalmente. No en todos — pierde valor."),
    ("💪 Fuerza",        "SÍ — movilización", "Ideal para comentarios de acción ciudadana y convocatorias."),
    ("🙏 Gracias",       "SÍ — contexto",     "Para comentarios que aportan datos o correcciones respetuosas."),
    ("😮 Sorpresa",      "CONTEXTUAL",        "Solo si el comentario revela algo que genuinamente sorprende. No como spam."),
    ("😡 Enojo",         "NUNCA en aliados",  "Reaccionar con enojo a un comentario ALIADO envía señal confusa al algoritmo."),
    ("🤣 Jaja",          "JAMÁS a bots",      "Reírse de un bot lo visibiliza. Ignorar + reportar es siempre mejor."),
    ("RESPONDER a otro", "SÍ — 30-60 min",    "Escalonar las respuestas entre miembros. No todos al mismo tiempo = parece orgánico."),
]

_COMENTARIOS_ESTRATEGIA = [
    (
        "¿Cuántos comentarios por nota?",
        "1 COMENTARIO FUERTE",
        "Un comentario bien redactado con hecho + pregunta + cierre propositivo pesa más que 5 débiles.",
        "Regla: calidad >> cantidad. El algoritmo premia comentarios con replies. Uno bueno genera debate real.",
    ),
    (
        "¿Cuándo publicar el comentario?",
        "PRIMEROS 30 MIN",
        "Los primeros comentarios reciben más visibilidad algorítmica. Configurar alerta del post.",
        "Si el post tiene más de 4h, el comentario tendrá menos alcance pero sigue siendo valioso.",
    ),
    (
        "¿Responder a otros comentarios?",
        "SÍ — selectivo",
        "Responder a comentarios ORGÁNICOS que tienen dudas genuinas. Nunca a insultos ni a cuentas bot.",
        "Un ciudadano con duda real = oportunidad real. Respóndele con hechos + pregunta abierta.",
    ),
    (
        "¿Hacer segundo comentario en misma nota?",
        "SOLO SI HAY REPLY",
        "Si alguien te respondió con un argumento nuevo y válido: UNA réplica factual. Luego silencio.",
        "Más de 2 comentarios tuyos en una nota = parece spam. El algoritmo puede penalizarte.",
    ),
    (
        "¿Compartir la nota negativa?",
        "JAMÁS SIN CONTEXTO",
        "Compartir una nota negativa sin texto propio amplifica el ataque. Si compartes: texto tuyo PRIMERO.",
        "Formato correcto: 'Esto dice el post — aquí están los hechos: [link / screenshot]'",
    ),
    (
        "¿Editar un comentario después de publicado?",
        "EVITAR",
        "FB marca los comentarios editados. Parece que te corrigieron. Piensa antes de publicar.",
        "Si cometiste un error: nuevo comentario con la corrección. No edites el original.",
    ),
]

_DEFCON_IDEAS = [
    (
        "OVERTON WINDOW\n(desplazamiento de marco)",
        "ELITE",
        "No pelees en el terreno del enemigo. Desplaza la conversación a territorio favorable.\n"
        "Si atacan en corrupción → lleva a obra pública documentada.\n"
        "Si atacan en seguridad → lleva a estadísticas de inversión en policía.\n"
        "El que define el tema del debate, gana el debate.",
    ),
    (
        "QUESTION BOMBING\n(bombardeo de preguntas)",
        "AVANZADA",
        "Responde a una acusación con 3-4 preguntas específicas que no pueden responder:\n"
        "¿Cuándo exactamente? ¿Qué expediente? ¿Qué juez? ¿Quién fue el denunciante?\n"
        "Cada pregunta sin respuesta es evidencia pública de que el ataque no tiene base.",
    ),
    (
        "TIMESTAMP TRAP\n(trampa de cronología)",
        "AVANZADA",
        "Colecta las declaraciones pasadas del atacante. Muestra contradicciones con fecha exacta.\n"
        "'El [fecha], [atacante] dijo X. El [fecha], el mismo dijo Y. ¿Cuál es la verdad?'\n"
        "Las contradicciones son letales para la credibilidad del atacante.",
    ),
    (
        "PERSONA CALIBRATION\n(diversidad de voces)",
        "COORDINACIÓN",
        "El equipo no habla igual — diversifica los perfiles que responden:\n"
        "• Adulto mayor → experiencia de obra anterior\n"
        "• Joven → oportunidades de empleo / educación\n"
        "• Empresario → certeza jurídica / inversión\n"
        "Un coro diverso es orgánico. Un coro idéntico es bot.",
    ),
    (
        "ANCHOR TECHNIQUE\n(ancla de mensaje)",
        "FUNDAMENTAL",
        "Siempre aterrizas en el mismo punto de llegada, sin importar el ataque:\n"
        "'Lo importante es que [obra/logro/propuesta] ya existe y está documentado.'\n"
        "La repetición de una verdad concreta la instala en la mente del lector.",
    ),
    (
        "RAPID RESPONSE NETWORK\n(red de alerta)",
        "OPERACIONAL",
        "Grupo de WhatsApp del equipo: cuando cae una nota nueva, el primer miembro que la ve avisa.\n"
        "Los primeros 30 minutos de un post son críticos para el alcance algorítmico.\n"
        "Alerta incluye: link + tipo de ataque (A/B/C/D/E/F) + mensaje clave del día.",
    ),
    (
        "CONTENT FLOODING\n(inundación positiva)",
        "PROACTIVA",
        "No esperar los ataques. Producir contenido positivo que sature el espacio antes del ataque:\n"
        "• Video corto de obra inaugurada\n"
        "• Testimonio de ciudadano beneficiado\n"
        "• Dato económico con infografía\n"
        "Una persona que ya vio 3 piezas positivas es resistente al ataque.",
    ),
    (
        "EVIDENCE ARCHIVE\n(archivo de evidencias)",
        "INFRAESTRUCTURA",
        "Carpeta compartida (Google Drive / OneDrive) con:\n"
        "• Fotos de obras + fecha + ubicación GPS\n"
        "• PDFs de presupuesto aprobado\n"
        "• Capturas de declaraciones de opositores con fecha\n"
        "• Links a noticias verificadas de logros\n"
        "Sin evidencia a 2 clics de distancia, el equipo improvisa y pierde.",
    ),
]

_TRAINING_TIPS = [
    (
        "IDENTIFICAR UN BOT",
        "DETECCIÓN",
        [
            "• Cuenta creada hace < 6 meses con < 20 publicaciones propias",
            "• Nombre genérico + número (Juan1234, María456)",
            "• Foto de perfil: modelo de stock, AI-generated, o figura pública robada",
            "• Comentarios con CAPS LOCK o emojis agresivos sin argumento",
            "• Mismo comentario copiado en múltiples posts en < 15 minutos",
            "• Cero contexto personal (sin fotos familiares, sin eventos, sin historia)",
        ],
    ),
    (
        "CUANDO TE ATACAN PERSONALMENTE",
        "RESISTENCIA",
        [
            "• Respira. El enojo es exactamente lo que buscan.",
            "• Regla 10 minutos: si quieres responder enojado, espera 10 min.",
            "• Evalúa: ¿tiene argumento o solo insulto? Si solo insulta: NO RESPONDAS.",
            "• Si tiene argumento real: UNA respuesta factual y calma. Solo una.",
            "• Screenshot + reporte + ignorar es SIEMPRE la respuesta correcta para insultos.",
            "• Tu estabilidad emocional visible es más persuasiva que cualquier argumento.",
        ],
    ),
    (
        "EJERCICIO: ROLE-PLAY DE ATAQUES",
        "ENTRENAMIENTO",
        [
            "• 2 veces por semana: un miembro del equipo juega al atacante.",
            "• Lanza los 6 tipos de ataque (A-F) en el grupo de WhatsApp.",
            "• Los demás tienen 5 minutos para redactar la respuesta ideal.",
            "• El coordinador evalúa: ¿es factual? ¿propositivo? ¿sin repetir la acusación?",
            "• Los mejores comentarios van al banco de respuestas reutilizables.",
            "• Objetivo: que la respuesta correcta sea instinto, no reflexión.",
        ],
    ),
    (
        "SEÑALES DE QUE VAS MAL",
        "AUTOCORRECCIÓN",
        [
            "• Estás respondiendo con más de 3 párrafos → demasiado. Corta.",
            "• Usaste la palabra 'corrupto' para negarlo → repetiste la acusación.",
            "• Llevas más de 2 intercambios con la misma cuenta → te enganchaste.",
            "• Tu comentario tiene emojis agresivos → modo bot activado.",
            "• Publicaste sin tener la fuente a mano → vulnerable al contra-ataque.",
            "• Estás respondiendo a las 2am → pausa. La guardia baja de noche.",
        ],
    ),
    (
        "REGLA DE ORO: EL ESPECTADOR",
        "MENTALIDAD",
        [
            "• No escribes para convencer al atacante. Él nunca cambiará de opinión.",
            "• Escribes para el ciudadano que está LEYENDO en silencio.",
            "• Ese espectador ve: ¿quién tiene hechos? ¿quién tiene insultos?",
            "• Un comentario tranquilo con datos concretos convierte a los indecisos.",
            "• El enojo del atacante frente a tu calma lo delata ante los espectadores.",
            "• SIEMPRE escribe pensando en el lector silencioso, no en el atacante.",
        ],
    ),
    (
        "AUTOCUIDADO DEL EQUIPO",
        "BIENESTAR",
        [
            "• Máximo 1 hora diaria en modo respuesta. Más tiempo = agotamiento mental.",
            "• Rotación de tareas: no siempre el mismo miembro responde lo más duro.",
            "• Grupo interno de desahogo: lo que no se publica, se dice en el grupo privado.",
            "• Celebrar victorias: cuando un ciudadano agradece o cambia de opinión → compartirlo.",
            "• Los insultos recibidos NO se guardan. Se reportan y se borran de la mente.",
            "• El coordinador revisa bienestar del equipo. Un miembro quemado comete errores.",
        ],
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
# BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build(output_path: Path) -> None:
    now      = datetime.now()
    date_lbl = now.strftime("%Y-%m-%d %H:%M")

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

    # ── PORTADA ───────────────────────────────────────────────────────────────
    cv_tbl = doc.add_table(rows=1, cols=1)
    cv_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cv = cv_tbl.cell(0, 0)
    _bg(cv, "080808")

    for txt, sz, clr in [
        ("NULLSEC RED TEAM  ·  DEFCON ELITE  ·  INTELIGENCIA POLÍTICA OSINT",  8,  "C00000"),
        ("",                                                                     4,  "FFFFFF"),
        ("PROTOCOLO DE CONTRAOFENSIVA NARRATIVA",                               20, "FFFFFF"),
        ("GERARDO VARGAS LANDERS  ·  CAMPAÑA DE CONTENCIÓN ORGÁNICA",          13, "FF3333"),
        ("",                                                                     4,  "FFFFFF"),
        ("MANUAL OPERATIVO PARA EL EQUIPO DE RESPUESTA CIUDADANA",              11, "FF6B00"),
        ("8 REGLAS DE ORO  ·  6 TIPOS DE ATAQUE  ·  8 IDEAS DEFCON  ·  6 MÓDULOS TRAINING", 9, "FF6B00"),
        ("",                                                                     4,  "FFFFFF"),
        (f"USO INTERNO — CONFIDENCIAL  ·  Generado: {date_lbl}",               7,  "555555"),
    ]:
        p = cv.add_paragraph()
        _sp(p)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(txt)
        r.bold            = True
        r.font.name       = "Consolas"
        r.font.size       = Pt(sz)
        r.font.color.rgb  = RGBColor(int(clr[0:2],16), int(clr[2:4],16), int(clr[4:6],16))
    doc.add_paragraph()

    # ── SECCIÓN 1: REGLAS DE ORO ──────────────────────────────────────────────
    _h1(doc, "REGLAS DE ORO — CONTENCIÓN ORGÁNICA PROPOSITIVA  ·  DEFCON ELITE LEVEL")

    _box(doc, "0D0005", [
        ("  PRINCIPIO CENTRAL: No eres un defensor. Eres un ciudadano que exige hechos.\n",
         YELLOW, 10, True, False),
        ("  La campaña negra busca que reacciones con enojo — porque el enojo valida el ataque.\n"
         "  Tu arma más poderosa es la CALMA + el DATO DOCUMENTADO + la PREGUNTA SIN RESPUESTA.\n"
         "  Un equipo que opera con estas 8 reglas es más efectivo que 100 cuentas bot del adversario.\n",
         GRAY, 9, False, True),
    ])

    for i, (titulo, prioridad, contexto, contenido) in enumerate(_REGLAS_ORO):
        tbl = doc.add_table(rows=2, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
        pri_bg = {"SIEMPRE": "1A0005", "CRÍTICA": "1A0000", "ABSOLUTA": "200000",
                  "ESTRATÉGICA": "001A00", "IMAGEN": "001010", "AVANZADA": "0A0010",
                  "FUNDAMENTAL": "0A0800", "OPERACIONAL": "001020"}.get(prioridad, "111111")
        pri_clr = (RED_MED   if prioridad in ("CRÍTICA", "ABSOLUTA") else
                   GREEN     if prioridad in ("SIEMPRE", "FUNDAMENTAL") else
                   ORANGE    if prioridad in ("IMAGEN", "OPERACIONAL") else
                   CYAN      if prioridad in ("AVANZADA", "ESTRATÉGICA") else YELLOW)

        c0 = tbl.rows[0].cells[0]
        _bg(c0, "1F1010")
        pp0 = c0.paragraphs[0]
        _sp(pp0)
        _r(pp0, f"  [{i+1}/8]  {titulo}", bold=True,  color=YELLOW,  size=9)
        _r(pp0, f"   [{prioridad}]",       bold=True,  color=pri_clr, size=8)
        _r(pp0, f"   CUÁNDO: {contexto}",  bold=False, color=GRAY,    size=8)

        c1 = tbl.rows[1].cells[0]
        _bg(c1, pri_bg)
        pp1 = c1.paragraphs[0]
        _sp(pp1)
        for line in contenido.split("\n"):
            _r(pp1, f"  {line}\n", color=WHITE, size=9)
        doc.add_paragraph()

    # ── SECCIÓN 2: CÓMO REACCIONAR EN NOTAS NEGATIVAS ────────────────────────
    _h1(doc, "CÓMO REACCIONAR EN NOTAS NEGATIVAS — 6 TIPOS DE ATAQUE + RESPUESTA EXACTA")

    _box(doc, "0A0000", [
        ("  PROTOCOLO: Identificar el tipo → aplicar la respuesta correspondiente → publicar.\n",
         ORANGE, 9, True, False),
        ("  Si no sabes qué tipo es: pregunta en el grupo antes de publicar. Un comentario incorrecto\n"
         "  hace más daño que ningún comentario. Cuando dudes: silencio + documentación.\n",
         GRAY, 8, False, True),
    ])

    _table(
        doc,
        headers=["TIPO DE ATAQUE", "IMPACTO", "ESTRATEGIA",
                 "COMENTARIO MODELO (COPIAR Y ADAPTAR)", "NOTAS INTERNAS"],
        widths=[1.15, 0.80, 1.10, 4.00, 3.55],
        hdr_bg="C00000",
        row_bg="120008",
        alt_bg="0A0005",
        rows=[
            [
                (tipo,       YELLOW,  True),
                (impacto,    RED_MED if "Alto" in impacto or "Máximo" in impacto else
                             ORANGE  if "Medio" in impacto else CYAN, True),
                (estrategia, GREEN,   False),
                (modelo,     WHITE,   False),
                (notas,      GRAY,    False),
            ]
            for tipo, impacto, estrategia, modelo, notas in _REACCION_NOTAS
        ],
    )

    # ── SECCIÓN 3: EMOJIS Y REACCIONES ───────────────────────────────────────
    _h1(doc, "COORDINACIÓN DE REACCIONES Y EMOJIS — GUÍA OPERACIONAL COMPLETA")

    _box(doc, "001020", [
        ("  REGLA CLAVE: Las reacciones a los comentarios de tu equipo amplían el alcance algorítmico.\n",
         CYAN, 9, True, False),
        ("  Facebook mide: reacciones + replies + tiempo de lectura. Un comentario con 5 reacciones\n"
         "  aparece más arriba y más veces en el feed que uno con 0. Reacciona con propósito.\n"
         "  TIEMPO: No reaccionen todos al mismo tiempo. Escalonar 15-60 min entre miembros.\n",
         GRAY, 8, False, True),
    ])

    _table(
        doc,
        headers=["EMOJI / ACCIÓN", "¿USAR?", "CUÁNDO Y POR QUÉ"],
        widths=[1.60, 1.30, 7.70],
        hdr_bg="001A3A",
        row_bg="000A1A",
        alt_bg="00060F",
        rows=[
            [
                (emoji,     YELLOW, True),
                (uso,       GREEN if "SÍ" in uso else (RED_MED if "JAMÁS" in uso or "NUNCA" in uso else ORANGE), True),
                (cuando,    WHITE, False),
            ]
            for emoji, uso, cuando in _EMOJI_STRATEGY
        ],
    )

    # ── SECCIÓN 4: ESTRATEGIA DE COMENTARIOS ─────────────────────────────────
    _h1(doc, "ESTRATEGIA DE COMENTARIOS — ¿CUÁNTOS, CUÁNDO, CÓMO?")

    _box(doc, "000A00", [
        ("  REGLA MAESTRA: Calidad >> Cantidad. Un comentario bien hecho vale más que cinco mediocres.\n",
         GREEN, 9, True, False),
        ("  El algoritmo penaliza el spam. Más de 2 comentarios tuyos en la misma nota en < 1h\n"
         "  puede hacer que FB limite tu alcance. Opera con precisión, no con volumen.\n",
         GRAY, 8, False, True),
    ])

    for pregunta, respuesta, detalle, nota in _COMENTARIOS_ESTRATEGIA:
        tbl = doc.add_table(rows=1, cols=3)
        c0, c1, c2 = tbl.rows[0].cells
        _bg(c0, "001A00"); c0.width = Inches(2.00)
        _bg(c1, "003A00"); c1.width = Inches(1.60)
        _bg(c2, "001000"); c2.width = Inches(7.00)
        p0 = c0.paragraphs[0]; _sp(p0); _r(p0, pregunta,  bold=True,  color=YELLOW, size=9)
        p1 = c1.paragraphs[0]; _sp(p1); _r(p1, respuesta, bold=True,  color=GREEN,  size=9)
        p2 = c2.paragraphs[0]; _sp(p2)
        _r(p2, detalle + "\n", color=WHITE, size=9)
        _r(p2, f"  ↳ {nota}", italic=True, color=GRAY, size=8)
        doc.add_paragraph()

    # ── SECCIÓN 5: IDEAS DEFCON ELITE ─────────────────────────────────────────
    _h1(doc, "IDEAS DEFCON ELITE — 8 VECTORES QUE PROBABLEMENTE NO ESTÁS USANDO")

    _box(doc, "0A000A", [
        ("  Estas tácticas no son reemplazos de las reglas base — son amplificadores.\n"
         "  Aplica primero las 8 reglas. Luego implementa estos vectores según disponibilidad del equipo.\n",
         PURPLE, 9, True, False),
    ])

    for i, (nombre, nivel, descripcion) in enumerate(_DEFCON_IDEAS):
        tbl  = doc.add_table(rows=2, cols=1)
        lvl_bg  = "1A001A" if nivel == "ELITE" else ("0A0A1A" if nivel == "AVANZADA" else "001A1A")
        lvl_clr = PURPLE if nivel == "ELITE" else (CYAN if nivel == "AVANZADA" else TEAL)

        c0 = tbl.rows[0].cells[0]
        _bg(c0, "1A1A00")
        pp0 = c0.paragraphs[0]; _sp(pp0)
        _r(pp0, f"  [{i+1}/8]  {nombre}", bold=True, color=YELLOW, size=9)
        _r(pp0, f"   NIVEL: {nivel}",      bold=True, color=lvl_clr, size=8)

        c1 = tbl.rows[1].cells[0]
        _bg(c1, lvl_bg)
        pp1 = c1.paragraphs[0]; _sp(pp1)
        for line in descripcion.strip().split("\n"):
            _r(pp1, f"  {line}\n", color=WHITE, size=9)
        doc.add_paragraph()

    # ── SECCIÓN 6: TRAINING ANTI-PROVOCACIÓN ─────────────────────────────────
    _h1(doc, "TRAINING — RESISTENCIA PSICOLÓGICA  ·  CÓMO NO CAER EN PROVOCACIONES")

    _box(doc, "000A00", [
        ("  El campo de batalla real no es Facebook. Es la mente de tu equipo.\n",
         GREEN, 10, True, False),
        ("  Un miembro que reacciona con enojo regala al adversario exactamente lo que busca.\n"
         "  Este training convierte las respuestas correctas en reflejos, no en decisiones.\n"
         "  Practicar 2x por semana. Los primeros 30 días son los más importantes.\n",
         GRAY, 8, False, True),
    ])

    for titulo, categoria, bullets in _TRAINING_TIPS:
        cat_bg  = {"DETECCIÓN": "001020", "RESISTENCIA": "1A0000", "ENTRENAMIENTO": "001A10",
                   "AUTOCORRECCIÓN": "100A00", "MENTALIDAD": "0A000A",
                   "BIENESTAR": "001A1A"}.get(categoria, "111111")
        cat_clr = {"DETECCIÓN": CYAN, "RESISTENCIA": RED_MED, "ENTRENAMIENTO": GREEN,
                   "AUTOCORRECCIÓN": YELLOW, "MENTALIDAD": PURPLE,
                   "BIENESTAR": TEAL}.get(categoria, WHITE)

        tbl = doc.add_table(rows=2, cols=1)
        c0  = tbl.rows[0].cells[0]
        _bg(c0, "1A1A00")
        pp0 = c0.paragraphs[0]; _sp(pp0)
        _r(pp0, f"  {titulo}", bold=True,  color=YELLOW,  size=9)
        _r(pp0, f"  [{categoria}]", bold=True, color=cat_clr, size=8)

        c1  = tbl.rows[1].cells[0]
        _bg(c1, cat_bg)
        pp1 = c1.paragraphs[0]; _sp(pp1)
        for bullet in bullets:
            _r(pp1, f"  {bullet}\n", color=WHITE, size=9)
        doc.add_paragraph()

    # ── QUICK REFERENCE CARD ─────────────────────────────────────────────────
    _h1(doc, "QUICK REFERENCE CARD — IMPRIMIR Y TENER A LA MANO")

    _box(doc, "080808", [
        ("  ANTES DE PUBLICAR — CHECKLIST DE 5 SEGUNDOS:\n\n",        YELLOW,  10, True, False),
        ("  [1] ¿Tengo la fuente a 2 clics de distancia?           SI / NO\n", GREEN, 9, False, False),
        ("  [2] ¿Estoy repitiendo la acusación que quiero negar?   SI / NO\n", GREEN, 9, False, False),
        ("  [3] ¿Mi comentario termina en algo propositivo?        SI / NO\n", GREEN, 9, False, False),
        ("  [4] ¿Estoy respondiendo a un bot o a un humano real?   BOT / HUMANO\n", GREEN, 9, False, False),
        ("  [5] ¿Mi tono está calmado o enojado?                   CALMA / ENOJO\n\n", GREEN, 9, False, False),
        ("  → Si respondiste NO a [1-3] o ENOJO a [5]: NO PUBLIQUES todavía.\n",  RED_MED, 9, True, False),
        ("  → Si es BOT en [4]: SCREENSHOT + REPORTE FB + IGNORAR. Sin excepción.\n", ORANGE, 9, True, False),
        ("\n  FRASE ANCLA PARA TODO EL EQUIPO:\n",  YELLOW, 9, True, False),
        ("  \"Hablo para el ciudadano que lee en silencio, no para el atacante.\"\n",
         CYAN, 10, True, True),
    ])

    # ── FOOTER ────────────────────────────────────────────────────────────────
    _div(doc, "C00000")
    pf = doc.add_paragraph()
    _sp(pf)
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(pf, f"NULLSEC RED TEAM  ·  PROTOCOLO CONTRAOFENSIVA GVL  ·  {date_lbl}",
       color=GRAY, size=7)
    pf2 = doc.add_paragraph()
    _sp(pf2)
    pf2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r(pf2, "PODER DEL 8  ·  8888  ·  GODMODE  ·  REVENG  ·  RMSHACK  ·  BROTHERHOOD",
       bold=True, color=RED_DARK, size=8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    size_kb = output_path.stat().st_size // 1024
    print(f"  [DOCX] → {output_path}  ({size_kb} KB)")


if __name__ == "__main__":
    out = Path(__file__).parent / "sessions" / "playbook" / "PLAYBOOK_GVL_CONTRAOFENSIVA.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    print("\n  NULLSEC — Generando Playbook Contraofensiva GVL...")
    build(out)
    print("  [DONE]  Abre el archivo y distribúyelo al equipo.\n")
