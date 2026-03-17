# app.py
# -*- coding: utf-8 -*-

import io
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import streamlit as st
import pandas as pd
from pypdf import PdfReader

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak
)

st.set_page_config(page_title="Comparador de Formularios PDF", layout="wide")


# =========================================================
# UTILIDADES
# =========================================================
def strip_accents(text: str) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def normalize_spaces(text: str) -> str:
    if text is None:
        return ""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_for_compare(text: str) -> str:
    if not text:
        return ""
    text = strip_accents(text.lower())
    text = normalize_spaces(text)
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, clean_for_compare(a), clean_for_compare(b)).ratio()


def is_noise_line(line: str) -> bool:
    """
    Ignora notas, instrucciones, encabezados, numeración de páginas, títulos globales.
    """
    raw = line.strip()
    if not raw:
        return True

    low = clean_for_compare(raw)

    noise_prefixes = [
        "nota:",
        "nota.",
        "nota previa",
        "nota condicional",
        "logica condicional",
        "lógica condicional",
        "consentimiento informado",
        "estrategia sembremos seguridad",
        "fin de la encuesta",
        "datos generales de caracter estadistico",
        "datos generales de carácter estadístico",
        "informacion adicional y contacto voluntario",
        "información adicional y contacto voluntario",
        "propuestas ciudadanas para la mejora de la seguridad",
        "confianza policial",
        "delitos",
        "victimizacion",
        "victimización",
        "riesgos sociales y situacionales",
        "contexto territorial y problematicas",
        "contexto territorial y problemáticas",
        "informacion de condiciones institucionales",
        "información de condiciones institucionales",
    ]

    if any(low.startswith(x) for x in noise_prefixes):
        return True

    # Encabezados de página o solo número de página
    if re.fullmatch(r"\d+", low):
        return True

    # Títulos grandes en mayúsculas sin ser pregunta
    if len(raw) < 80 and raw.isupper() and "?" not in raw:
        return True

    return False


def normalize_option_text(text: str) -> str:
    text = text.strip(" -•\t")
    text = re.sub(r"^[\(\[]?\s*[xX ]?\s*[\)\]]\s*", "", text)
    text = re.sub(r"^[oO]\s+", "", text)
    text = re.sub(r"^[•●▪◦]\s*", "", text)
    text = re.sub(r"^☐\s*", "", text)
    text = re.sub(r"^\(\s*\)\s*", "", text)
    text = re.sub(r"^\-\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .;:")
    return text.strip()


# =========================================================
# EXTRACCIÓN PDF
# =========================================================
def extract_pdf_text(file_obj) -> str:
    try:
        reader = PdfReader(file_obj)
        pages = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            pages.append(txt)
        return normalize_spaces("\n".join(pages))
    except Exception:
        return ""


def detect_tipo(text: str, filename: str = "") -> str:
    base = clean_for_compare((filename or "") + " " + (text[:1500] if text else ""))

    if "encuesta policial" in base or "policial" in base:
        return "Policial"
    if "encuesta comercio" in base or "comercio" in base:
        return "Comercio"
    if "encuesta comunidad" in base or "comunidad" in base:
        return "Comunidad"
    return "Desconocido"


def detect_delegacion(text: str, filename: str = "") -> str:
    source = (filename or "") + "\n" + (text[:1500] if text else "")

    # Busca D71 PUNTARENAS, D71 - PUNTARENAS, etc.
    m = re.search(r"\bD\s*([0-9]{1,3})\b.*?\b([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{2,})\b", source, re.DOTALL)
    if m:
        d = f"D{m.group(1)}"
        place = m.group(2).strip()
        place = re.sub(r"\s+", " ", place)
        place = re.sub(r"(FORMATO|ENCUESTA|COMUNIDAD|COMERCIO|POLICIAL)$", "", place).strip()
        if place:
            return f"{d} - {place.title()}"

    m2 = re.search(r"\bD\s*([0-9]{1,3})\b", source)
    if m2:
        return f"D{m2.group(1)}"

    return "No identificada"


# =========================================================
# PARSER DE PREGUNTAS / OPCIONES
# =========================================================
QUESTION_RE = re.compile(
    r"^\s*(\d{1,2}(?:\.\d+)?)[\.\-–]?\s*(.+)$"
)

OPTION_HINT_WORDS = [
    "si",
    "no",
    "muy inseguro",
    "inseguro",
    "seguro",
    "muy seguro",
    "nunca",
    "casi nunca",
    "todos los dias",
    "todos los días",
    "varias veces",
    "una vez",
    "otro",
    "otra",
    "no aplica",
    "desconocido",
]


def split_lines_safely(text: str) -> list[str]:
    lines = []
    for raw in text.split("\n"):
        part = raw.strip()
        if not part:
            continue

        # Si hay una pregunta pegada a otra, intenta separarlas
        part = re.sub(r"(?<!^)\s+(\d{1,2}(?:\.\d+)?[\.\-–])\s*", r"\n\1 ", part)
        for p in part.split("\n"):
            p = p.strip()
            if p:
                lines.append(p)
    return lines


def is_question_line(line: str) -> bool:
    if is_noise_line(line):
        return False

    m = QUESTION_RE.match(line)
    if not m:
        return False

    q_text = m.group(2).strip()
    low = clean_for_compare(q_text)

    # filtra títulos sin forma de pregunta
    if len(q_text) < 3:
        return False

    # si empieza con número y luego texto razonable, lo tomamos
    return True


def looks_like_option(line: str) -> bool:
    if is_noise_line(line):
        return False

    raw = line.strip()
    low = clean_for_compare(raw)

    if raw.startswith(("☐", "•", "●", "▪", "◦")):
        return True
    if re.match(r"^\(\s*\)\s*", raw):
        return True
    if re.match(r"^[oO]\s+", raw):
        return True

    # líneas cortas debajo de una pregunta que parecen opción
    if len(raw) <= 120 and any(word in low for word in OPTION_HINT_WORDS):
        return True

    return False


def parse_questions(text: str) -> list[dict]:
    lines = split_lines_safely(text)

    questions = []
    current = None

    for line in lines:
        if is_question_line(line):
            m = QUESTION_RE.match(line)
            q_num = m.group(1).strip()
            q_text = m.group(2).strip()

            current = {
                "num": q_num,
                "question": q_text,
                "options": []
            }
            questions.append(current)
            continue

        if current is None:
            continue

        # Ignorar notas y ruido
        if is_noise_line(line):
            continue

        # Si parece opción, agregarla
        if looks_like_option(line):
            opt = normalize_option_text(line)
            if opt:
                current["options"].append(opt)
            continue

        # Si no es opción, pero la pregunta quedó partida en varias líneas,
        # la concatenamos SOLO si no parece instrucción.
        if current and len(line) < 220:
            low = clean_for_compare(line)
            if not low.startswith(("nota", "logica", "lógica", "si la respuesta", "en caso de", "al continuar")):
                current["question"] = (current["question"] + " " + line).strip()

    # limpieza final
    cleaned = []
    for q in questions:
        q_text = re.sub(r"\s+", " ", q["question"]).strip()
        opts = []
        seen = set()

        for op in q["options"]:
            op2 = re.sub(r"\s+", " ", op).strip()
            op_key = clean_for_compare(op2)
            if op2 and op_key not in seen:
                seen.add(op_key)
                opts.append(op2)

        if q_text:
            cleaned.append({
                "num": q["num"],
                "question": q_text,
                "options": opts
            })

    return cleaned


# =========================================================
# EMPAREJAMIENTO Y COMPARACIÓN
# =========================================================
def build_question_map(questions: list[dict]) -> dict:
    return {q["num"]: q for q in questions}


def compare_options(orig_opts: list[str], new_opts: list[str]) -> list[dict]:
    changes = []

    orig_norm = {clean_for_compare(x): x for x in orig_opts}
    new_norm = {clean_for_compare(x): x for x in new_opts}

    orig_keys = set(orig_norm.keys())
    new_keys = set(new_norm.keys())

    added = [new_norm[k] for k in sorted(new_keys - orig_keys)]
    removed = [orig_norm[k] for k in sorted(orig_keys - new_keys)]

    # Intentar detectar modificaciones cercanas entre eliminadas/agregadas
    used_added = set()
    used_removed = set()

    for i, rem in enumerate(removed):
        best_j = None
        best_score = 0.0
        for j, add in enumerate(added):
            if j in used_added:
                continue
            sc = similarity(rem, add)
            if sc > best_score:
                best_score = sc
                best_j = j

        if best_j is not None and best_score >= 0.60:
            changes.append({
                "type": "opcion_modificada",
                "antes": rem,
                "despues": added[best_j]
            })
            used_removed.add(i)
            used_added.add(best_j)

    for i, rem in enumerate(removed):
        if i not in used_removed:
            changes.append({
                "type": "opcion_eliminada",
                "texto": rem
            })

    for j, add in enumerate(added):
        if j not in used_added:
            changes.append({
                "type": "opcion_agregada",
                "texto": add
            })

    return changes


def compare_questions(orig_questions: list[dict], new_questions: list[dict]) -> list[dict]:
    changes = []

    orig_map = build_question_map(orig_questions)
    new_map = build_question_map(new_questions)

    all_nums = sorted(
        set(orig_map.keys()) | set(new_map.keys()),
        key=lambda x: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", x)]
    )

    for num in all_nums:
        oq = orig_map.get(num)
        nq = new_map.get(num)

        if oq and not nq:
            changes.append({
                "question_num": num,
                "question_label": f"Pregunta {num}",
                "change_kind": "pregunta_eliminada",
                "detail": f"La pregunta {num} existe en el original pero no aparece en el modificado."
            })
            continue

        if nq and not oq:
            changes.append({
                "question_num": num,
                "question_label": f"Pregunta {num}",
                "change_kind": "pregunta_agregada",
                "detail": f"Se agregó la pregunta {num}: {nq['question']}"
            })
            continue

        # Ambas existen
        q_changes = []

        q_sim = similarity(oq["question"], nq["question"])
        if q_sim < 0.97:
            q_changes.append({
                "type": "texto_pregunta_modificado",
                "antes": oq["question"],
                "despues": nq["question"]
            })

        opt_changes = compare_options(oq["options"], nq["options"])
        q_changes.extend(opt_changes)

        if q_changes:
            changes.append({
                "question_num": num,
                "question_label": f"Pregunta {num}",
                "change_kind": "detalle",
                "question_original": oq["question"],
                "question_new": nq["question"],
                "changes": q_changes
            })

    return changes


# =========================================================
# REPORTE PDF
# =========================================================
def build_detailed_pdf(report_rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    style_title = styles["Title"]
    style_h2 = styles["Heading2"]
    style_h3 = styles["Heading3"]
    style_normal = styles["BodyText"]

    style_small = ParagraphStyle(
        "small",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        spaceAfter=4
    )

    style_box = ParagraphStyle(
        "box",
        parent=styles["BodyText"],
        fontSize=9,
        leading=12,
        leftIndent=8,
        spaceBefore=2,
        spaceAfter=2
    )

    story = []

    story.append(Paragraph("Reporte comparativo de preguntas y opciones", style_title))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(
        "Solo se incluyen cambios sustantivos en preguntas y respuestas. "
        "No se incorporan notas, leyendas, instrucciones ni texto introductorio.",
        style_normal
    ))
    story.append(Spacer(1, 0.25 * inch))

    # Resumen
    summary_data = [["Archivo", "Tipo", "Delegación", "Cambios detectados"]]
    for row in report_rows:
        summary_data.append([
            row["archivo"],
            row["tipo"],
            row["delegacion"],
            str(row["total_cambios"])
        ])

    tbl = Table(summary_data, repeatRows=1, colWidths=[180, 80, 110, 90])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.3 * inch))

    # Detalle
    for idx, row in enumerate(report_rows, start=1):
        story.append(Paragraph(f"{idx}. {row['archivo']}", style_h2))
        story.append(Paragraph(
            f"<b>Tipo:</b> {row['tipo']} &nbsp;&nbsp;&nbsp; "
            f"<b>Delegación:</b> {row['delegacion']} &nbsp;&nbsp;&nbsp; "
            f"<b>Total de cambios:</b> {row['total_cambios']}",
            style_small
        ))
        story.append(Spacer(1, 0.08 * inch))

        if not row["cambios"]:
            story.append(Paragraph("No se detectaron cambios sustantivos en preguntas u opciones.", style_small))
            story.append(Spacer(1, 0.12 * inch))
            continue

        for item in row["cambios"]:
            story.append(Paragraph(item["question_label"], style_h3))

            if item["change_kind"] in ("pregunta_agregada", "pregunta_eliminada"):
                story.append(Paragraph(item["detail"], style_box))
                story.append(Spacer(1, 0.06 * inch))
                continue

            for ch in item["changes"]:
                if ch["type"] == "texto_pregunta_modificado":
                    story.append(Paragraph(
                        f"<b>Texto modificado</b><br/>"
                        f"<b>Original:</b> {ch['antes']}<br/>"
                        f"<b>Nuevo:</b> {ch['despues']}",
                        style_box
                    ))
                elif ch["type"] == "opcion_agregada":
                    story.append(Paragraph(
                        f"<b>Opción agregada:</b> {ch['texto']}",
                        style_box
                    ))
                elif ch["type"] == "opcion_eliminada":
                    story.append(Paragraph(
                        f"<b>Opción eliminada:</b> {ch['texto']}",
                        style_box
                    ))
                elif ch["type"] == "opcion_modificada":
                    story.append(Paragraph(
                        f"<b>Opción modificada</b><br/>"
                        f"<b>Antes:</b> {ch['antes']}<br/>"
                        f"<b>Después:</b> {ch['despues']}",
                        style_box
                    ))

            story.append(Spacer(1, 0.06 * inch))

        if idx < len(report_rows):
            story.append(PageBreak())

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


# =========================================================
# UI
# =========================================================
st.title("Comparador de Formularios PDF")
st.write(
    "Cargue primero los **PDF originales** y luego los **PDF con cambios**. "
    "La comparación se realiza solo sobre **preguntas y opciones de respuesta**."
)

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. PDF originales")
    original_files = st.file_uploader(
        "Cargue los originales",
        type=["pdf"],
        accept_multiple_files=True,
        key="orig"
    )

with col2:
    st.subheader("2. PDF modificados")
    modified_files = st.file_uploader(
        "Cargue los modificados",
        type=["pdf"],
        accept_multiple_files=True,
        key="mod"
    )

compare_btn = st.button("Comparar formularios", type="primary")


def build_reference_map(files: list) -> dict:
    ref_map = {}
    for f in files:
        text = extract_pdf_text(f)
        tipo = detect_tipo(text, f.name)
        delegacion = detect_delegacion(text, f.name)
        questions = parse_questions(text)

        key = tipo.lower()
        ref_map[key] = {
            "filename": f.name,
            "tipo": tipo,
            "delegacion": delegacion,
            "text": text,
            "questions": questions
        }
    return ref_map


if compare_btn:
    if not original_files or not modified_files:
        st.warning("Debe cargar los PDFs originales y los PDFs modificados.")
        st.stop()

    with st.spinner("Procesando PDFs y comparando preguntas/opciones..."):
        originals = build_reference_map(original_files)

        report_rows = []

        for f in modified_files:
            text = extract_pdf_text(f)
            tipo = detect_tipo(text, f.name)
            delegacion = detect_delegacion(text, f.name)
            questions = parse_questions(text)

            original = originals.get(tipo.lower())
            if not original:
                report_rows.append({
                    "archivo": f.name,
                    "tipo": tipo,
                    "delegacion": delegacion,
                    "total_cambios": 0,
                    "cambios": [],
                    "error": "No se encontró original compatible."
                })
                continue

            cambios = compare_questions(original["questions"], questions)

            report_rows.append({
                "archivo": f.name,
                "tipo": tipo,
                "delegacion": delegacion,
                "total_cambios": len(cambios),
                "cambios": cambios,
                "error": None
            })

    # ================= RESUMEN =================
    st.subheader("Resumen general")

    summary_df = pd.DataFrame([
        {
            "Archivo": r["archivo"],
            "Tipo": r["tipo"],
            "Delegación": r["delegacion"],
            "Cambios detectados": r["total_cambios"]
        }
        for r in report_rows
    ])

    st.dataframe(summary_df, use_container_width=True)

    # ================= DETALLE =================
    st.subheader("Detalle de cambios")

    for row in report_rows:
        st.markdown("---")
        st.markdown(f"### {row['archivo']}")
        st.write(f"**Tipo:** {row['tipo']}")
        st.write(f"**Delegación:** {row['delegacion']}")
        st.write(f"**Total de cambios:** {row['total_cambios']}")

        if row["error"]:
            st.error(row["error"])
            continue

        if not row["cambios"]:
            st.success("No se detectaron cambios sustantivos en preguntas u opciones.")
            continue

        for item in row["cambios"]:
            st.markdown(f"#### {item['question_label']}")

            if item["change_kind"] in ("pregunta_agregada", "pregunta_eliminada"):
                st.warning(item["detail"])
                continue

            for ch in item["changes"]:
                if ch["type"] == "texto_pregunta_modificado":
                    st.info("**Texto de la pregunta modificado**")
                    st.write(f"**Original:** {ch['antes']}")
                    st.write(f"**Nuevo:** {ch['despues']}")

                elif ch["type"] == "opcion_agregada":
                    st.success(f"**Opción agregada:** {ch['texto']}")

                elif ch["type"] == "opcion_eliminada":
                    st.error(f"**Opción eliminada:** {ch['texto']}")

                elif ch["type"] == "opcion_modificada":
                    st.warning("**Opción modificada**")
                    st.write(f"**Antes:** {ch['antes']}")
                    st.write(f"**Después:** {ch['despues']}")

    # ================= DESCARGA PDF =================
    pdf_bytes = build_detailed_pdf(report_rows)

    st.download_button(
        "Descargar reporte PDF detallado",
        data=pdf_bytes,
        file_name="reporte_comparativo_preguntas_opciones.pdf",
        mime="application/pdf"
    )
