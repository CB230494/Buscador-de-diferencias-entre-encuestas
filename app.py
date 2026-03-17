
# app.py
# -*- coding: utf-8 -*-

import io
import re
import html
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import fitz  # PyMuPDF
import streamlit as st
from pypdf import PdfReader
from rapidfuzz import fuzz

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

st.set_page_config(page_title="Comparador de Formularios PDF", layout="wide")


# =========================================================
# Utilidades
# =========================================================

def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def norm(text: str) -> str:
    if text is None:
        return ""
    text = str(text).replace("\ufeff", " ").replace("\xa0", " ")
    text = text.replace("•", "\n• ").replace("☐", "\n☐ ").replace("□", "\n□ ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def normalize_for_compare(text: str) -> str:
    text = norm(text).lower()
    text = strip_accents(text)
    text = text.replace("¿", "").replace("?", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_option(text: str) -> str:
    text = normalize_for_compare(text)
    text = re.sub(r"^(si|no|otro|no aplica|ninguno de los anteriores)\b", lambda m: m.group(0), text)
    text = re.sub(r"^(o|•|\(|\)|☐|\-)\s*", "", text)
    text = re.sub(r"^nota[:.\- ]*", "", text)
    return text.strip(" .;:-")


def clean_visual_line(line: str) -> str:
    line = norm(line)
    line = re.sub(r"^\s*(?:☐|□|•|o|O|\(\s*\)|\(\s*[xX]\s*\)|-\s*)\s*", "", line)
    return line.strip()


def safe_filename(name: str) -> str:
    name = strip_accents(name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name.strip("_") or "archivo"


# =========================================================
# Extracción de texto PDF
# =========================================================

def extract_text_pymupdf(file_bytes: bytes) -> str:
    parts = []
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        for page in doc:
            txt = page.get_text("text")
            if txt:
                parts.append(txt)
    return norm("\n".join(parts))


def extract_text_pypdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        if txt:
            parts.append(txt)
    return norm("\n".join(parts))


def extract_pdf_text(file_bytes: bytes) -> str:
    text = ""
    try:
        text = extract_text_pymupdf(file_bytes)
    except Exception:
        text = ""
    if len(text.strip()) < 100:
        try:
            text2 = extract_text_pypdf(file_bytes)
            if len(text2.strip()) > len(text.strip()):
                text = text2
        except Exception:
            pass
    return norm(text)


# =========================================================
# Modelo
# =========================================================

@dataclass
class QuestionBlock:
    qid: str
    raw_header: str
    question_text: str
    options: List[str] = field(default_factory=list)
    raw_block: str = ""


@dataclass
class SurveyDoc:
    filename: str
    survey_type: str
    delegacion_codigo: str
    delegacion_lugar: str
    text: str
    questions: Dict[str, QuestionBlock]


# =========================================================
# Identificación de tipo y delegación
# =========================================================

def identify_survey_type(text: str, filename: str = "") -> str:
    base = normalize_for_compare(text[:2000] + " " + filename)
    if "encuesta policial" in base or "percepcion institucional" in base:
        return "Policial"
    if "encuesta comercio" in base or "zona comercial" in base or "comerciod" in base:
        return "Comercio"
    if "encuesta comunidad" in base or "percepcion de comunidad" in base:
        return "Comunidad"
    # fallback
    if "policial" in base:
        return "Policial"
    if "comercio" in base:
        return "Comercio"
    return "Comunidad"


def identify_delegacion(text: str, filename: str = "") -> Tuple[str, str]:
    head = norm((text[:1500] + "\n" + filename).upper())

    m = re.search(r"\bD\s*([0-9]{1,3})\b", head)
    codigo = f"D{m.group(1)}" if m else "SIN_CODIGO"

    lugar = "SIN_LUGAR"
    lines = [x.strip() for x in head.splitlines() if x.strip()]
    # buscar línea siguiente al encabezado
    for i, ln in enumerate(lines[:8]):
        if "FORMATO" in ln and i + 1 < len(lines):
            cand = lines[i + 1]
            if len(cand) <= 40 and "ESTRATEGIA" not in cand:
                lugar = cand.strip()
        if re.fullmatch(r"[A-ZÁÉÍÓÚÜÑ ]{4,}", ln) and "ENCUESTA" not in ln and "ESTRATEGIA" not in ln:
            if not re.search(r"\b(COMUNIDAD|COMERCIO|POLICIAL|CONSENTIMIENTO)\b", ln):
                lugar = ln.strip()
                break

    # fallback por patrón Dxx LUGAR
    m2 = re.search(r"\bD\s*[0-9]{1,3}\s+([A-ZÁÉÍÓÚÜÑ ]{3,})", head)
    if m2:
        lugar = m2.group(1).strip()

    lugar = re.sub(r"\s{2,}", " ", lugar)
    return codigo, lugar.title()


# =========================================================
# Extracción de preguntas
# =========================================================

Q_START_RE = re.compile(
    r"(?m)^(?P<qid>\d{1,2}(?:\.\d+)?)(?:\s*[\.\-–]|[\.\-–])\s*(?P<rest>.+)$"
)


def preprocess_question_text(text: str) -> str:
    text = norm(text)
    text = text.replace("31- ¿", "31. ¿").replace("1- ", "1. ").replace("2- ", "2. ")
    text = text.replace("3- ", "3. ").replace("4- ", "4. ").replace("5- ", "5. ")
    text = text.replace("6- ", "6. ").replace("7- ", "7. ").replace("8- ", "8. ")
    text = text.replace("9- ", "9. ").replace("10- ", "10. ").replace("11- ", "11. ")
    text = text.replace("12- ", "12. ").replace("13- ", "13. ").replace("14- ", "14. ")
    text = text.replace("15- ", "15. ").replace("16- ", "16. ").replace("17- ", "17. ")
    text = text.replace("18- ", "18. ").replace("19- ", "19. ").replace("20- ", "20. ")
    text = text.replace("21- ", "21. ").replace("22- ", "22. ").replace("23- ", "23. ")
    text = text.replace("24- ", "24. ").replace("25- ", "25. ").replace("26- ", "26. ")
    text = text.replace("27- ", "27. ").replace("28- ", "28. ").replace("29- ", "29. ")
    text = text.replace("30- ", "30. ")
    return text


def split_question_blocks(text: str) -> List[Tuple[str, str]]:
    text = preprocess_question_text(text)
    matches = list(Q_START_RE.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        qid = m.group("qid")
        block = text[start:end].strip()
        blocks.append((qid, block))
    return blocks


def is_option_line(line: str) -> bool:
    raw = line.strip()
    if not raw:
        return False
    lowered = normalize_for_compare(raw)
    if lowered.startswith("nota"):
        return False
    if re.match(r"^\s*(?:☐|□|•|o|\(\s*\)|\(\s*[xX]\s*\))\s*", raw):
        return True
    if lowered in {"si", "no", "no aplica", "no indica", "desconocido", "otro"}:
        return True
    # líneas cortas dentro de listas
    if len(raw) <= 120 and (
        raw.startswith("o ")
        or raw.startswith("• ")
        or raw.startswith("☐ ")
        or raw.startswith("( )")
    ):
        return True
    return False


def parse_question_block(qid: str, block: str) -> QuestionBlock:
    lines = [ln.strip() for ln in norm(block).splitlines() if ln.strip()]
    if not lines:
        return QuestionBlock(qid=qid, raw_header=qid, question_text="", options=[], raw_block=block)

    header = lines[0]
    header = re.sub(rf"^{re.escape(qid)}\s*[\.\-–]?\s*", "", header).strip()

    body_lines = lines[1:]
    question_lines = [header]
    options = []

    for line in body_lines:
        if normalize_for_compare(line).startswith("nota"):
            continue
        if is_option_line(line):
            options.append(clean_visual_line(line))
        else:
            # si ya empezaron opciones y viene una línea corta, se pega a la última opción
            if options and len(line) < 120 and not re.match(r"^\d+(?:\.\d+)?", line):
                options[-1] = (options[-1] + " " + clean_visual_line(line)).strip()
            else:
                question_lines.append(line)

    question_text = " ".join(question_lines).strip()

    # limpieza adicional
    options = [x for x in [norm(o) for o in options] if x]
    options = dedupe_preserve(options)

    return QuestionBlock(
        qid=qid,
        raw_header=header,
        question_text=question_text,
        options=options,
        raw_block=block,
    )


def dedupe_preserve(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        k = normalize_option(item)
        if k and k not in seen:
            seen.add(k)
            out.append(item.strip())
    return out


def extract_questions(text: str) -> Dict[str, QuestionBlock]:
    blocks = split_question_blocks(text)
    data: Dict[str, QuestionBlock] = {}
    for qid, block in blocks:
        qb = parse_question_block(qid, block)
        if qb.question_text.strip():
            data[qid] = qb
    return data


# =========================================================
# Construcción de documento
# =========================================================

def build_survey_doc(filename: str, file_bytes: bytes) -> SurveyDoc:
    text = extract_pdf_text(file_bytes)
    survey_type = identify_survey_type(text, filename)
    codigo, lugar = identify_delegacion(text, filename)
    questions = extract_questions(text)
    return SurveyDoc(
        filename=filename,
        survey_type=survey_type,
        delegacion_codigo=codigo,
        delegacion_lugar=lugar,
        text=text,
        questions=questions,
    )


# =========================================================
# Comparación
# =========================================================

def smart_equal(a: str, b: str, threshold: int = 97) -> bool:
    na = normalize_for_compare(a)
    nb = normalize_for_compare(b)
    if na == nb:
        return True
    return fuzz.ratio(na, nb) >= threshold


def compare_options(old_opts: List[str], new_opts: List[str]) -> Tuple[List[str], List[str], List[Tuple[str, str]]]:
    old_norm_map = {normalize_option(x): x for x in old_opts if normalize_option(x)}
    new_norm_map = {normalize_option(x): x for x in new_opts if normalize_option(x)}

    removed = []
    added = []
    changed = []

    unmatched_old = dict(old_norm_map)
    unmatched_new = dict(new_norm_map)

    # exactos
    for k in list(unmatched_old.keys()):
        if k in unmatched_new:
            unmatched_old.pop(k, None)
            unmatched_new.pop(k, None)

    # parecidos = cambiados
    used_new = set()
    for ok, oval in list(unmatched_old.items()):
        best_key = None
        best_score = -1
        for nk, nval in unmatched_new.items():
            if nk in used_new:
                continue
            score = fuzz.ratio(ok, nk)
            if score > best_score:
                best_score = score
                best_key = nk
        if best_key is not None and best_score >= 78:
            changed.append((oval, unmatched_new[best_key]))
            used_new.add(best_key)
            unmatched_old.pop(ok, None)

    for nk in used_new:
        unmatched_new.pop(nk, None)

    removed = list(unmatched_old.values())
    added = list(unmatched_new.values())
    return removed, added, changed


def compare_docs(original: SurveyDoc, modified: SurveyDoc) -> Dict:
    result = {
        "original": original,
        "modified": modified,
        "question_changes": [],
        "new_questions": [],
        "missing_questions": [],
        "total_changes": 0,
    }

    oq = original.questions
    mq = modified.questions

    all_ids = sorted(
        set(oq.keys()) | set(mq.keys()),
        key=lambda x: [int(p) if p.isdigit() else p for p in re.findall(r"\d+|\D+", x)]
    )

    for qid in all_ids:
        old = oq.get(qid)
        new = mq.get(qid)

        if old and not new:
            result["missing_questions"].append({"qid": qid, "question": old.question_text})
            continue

        if new and not old:
            result["new_questions"].append({"qid": qid, "question": new.question_text})
            continue

        if not old or not new:
            continue

        question_text_changed = not smart_equal(old.question_text, new.question_text, threshold=96)
        removed_opts, added_opts, changed_opts = compare_options(old.options, new.options)

        if question_text_changed or removed_opts or added_opts or changed_opts:
            result["question_changes"].append({
                "qid": qid,
                "old_question": old.question_text,
                "new_question": new.question_text,
                "question_text_changed": question_text_changed,
                "removed_options": removed_opts,
                "added_options": added_opts,
                "changed_options": changed_opts,
            })

    result["total_changes"] = (
        len(result["question_changes"])
        + len(result["new_questions"])
        + len(result["missing_questions"])
    )
    return result


# =========================================================
# PDF de salida
# =========================================================

def build_report_pdf(comparisons: List[Dict]) -> bytes:
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontSize=12, leading=14, spaceAfter=8))
    styles.add(ParagraphStyle(name="Item", parent=styles["BodyText"], fontSize=9.2, leading=12, spaceAfter=4))

    elems = []
    elems.append(Paragraph("Reporte Comparativo de Cambios en Formularios PDF", styles["Title"]))
    elems.append(Spacer(1, 0.2 * inch))

    summary_data = [["Archivo", "Tipo", "Delegación", "Cambios detectados"]]
    for comp in comparisons:
        mod = comp["modified"]
        summary_data.append([
            mod.filename,
            mod.survey_type,
            f"{mod.delegacion_codigo} - {mod.delegacion_lugar}",
            str(comp["total_changes"]),
        ])

    table = Table(summary_data, colWidths=[2.8 * inch, 1.0 * inch, 1.7 * inch, 1.1 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
    ]))
    elems.append(table)
    elems.append(PageBreak())

    for idx, comp in enumerate(comparisons, 1):
        mod = comp["modified"]
        orig = comp["original"]

        elems.append(Paragraph(f"{idx}. {html.escape(mod.filename)}", styles["Heading1"]))
        elems.append(Paragraph(
            f"<b>Tipo:</b> {mod.survey_type} &nbsp;&nbsp;&nbsp; "
            f"<b>Delegación:</b> {mod.delegacion_codigo} - {html.escape(mod.delegacion_lugar)}",
            styles["BodyText"],
        ))
        elems.append(Paragraph(
            f"<b>Original asociado:</b> {html.escape(orig.filename)}",
            styles["BodyText"],
        ))
        elems.append(Spacer(1, 0.12 * inch))

        if comp["total_changes"] == 0:
            elems.append(Paragraph("No se detectaron cambios en preguntas ni respuestas.", styles["BodyText"]))
            elems.append(PageBreak())
            continue

        if comp["new_questions"]:
            elems.append(Paragraph("Preguntas nuevas", styles["Section"]))
            for item in comp["new_questions"]:
                txt = f"<b>{item['qid']}</b>. {html.escape(item['question'])}"
                elems.append(Paragraph(txt, styles["Item"]))
            elems.append(Spacer(1, 0.08 * inch))

        if comp["missing_questions"]:
            elems.append(Paragraph("Preguntas eliminadas o ausentes", styles["Section"]))
            for item in comp["missing_questions"]:
                txt = f"<b>{item['qid']}</b>. {html.escape(item['question'])}"
                elems.append(Paragraph(txt, styles["Item"]))
            elems.append(Spacer(1, 0.08 * inch))

        if comp["question_changes"]:
            elems.append(Paragraph("Cambios detectados por pregunta", styles["Section"]))

            for ch in comp["question_changes"]:
                elems.append(Paragraph(f"<b>Pregunta {ch['qid']}</b>", styles["BodyText"]))

                if ch["question_text_changed"]:
                    elems.append(Paragraph(
                        f"<b>Texto original:</b> {html.escape(ch['old_question'])}",
                        styles["Small"],
                    ))
                    elems.append(Paragraph(
                        f"<b>Texto nuevo:</b> {html.escape(ch['new_question'])}",
                        styles["Small"],
                    ))

                for a, b in ch["changed_options"]:
                    elems.append(Paragraph(
                        f"• <b>Opción modificada:</b> “{html.escape(a)}” → “{html.escape(b)}”",
                        styles["Small"],
                    ))

                for a in ch["added_options"]:
                    elems.append(Paragraph(
                        f"• <b>Opción agregada:</b> {html.escape(a)}",
                        styles["Small"],
                    ))

                for r in ch["removed_options"]:
                    elems.append(Paragraph(
                        f"• <b>Opción eliminada:</b> {html.escape(r)}",
                        styles["Small"],
                    ))

                elems.append(Spacer(1, 0.08 * inch))

        elems.append(PageBreak())

    doc.build(elems)
    return buffer.getvalue()


# =========================================================
# UI
# =========================================================

st.title("Comparador de Formularios PDF")
st.caption("Compara preguntas y respuestas entre formularios originales y versiones modificadas, y genera un PDF ordenado con los cambios detectados.")

with st.expander("Cómo funciona", expanded=False):
    st.markdown(
        """
        1. Cargue los **3 formularios originales**.  
        2. Cargue uno o varios **formularios modificados**.  
        3. La app identifica automáticamente el tipo de encuesta y la delegación.  
        4. Compara **solo preguntas y opciones de respuesta**.  
        5. Genera un **PDF de reporte** con los cambios detectados.
        """
    )

col1, col2 = st.columns(2)

with col1:
    original_files = st.file_uploader(
        "Cargue los PDFs originales",
        type=["pdf"],
        accept_multiple_files=True,
        key="orig"
    )

with col2:
    modified_files = st.file_uploader(
        "Cargue los PDFs modificados",
        type=["pdf"],
        accept_multiple_files=True,
        key="mod"
    )

compare_btn = st.button("Comparar formularios", type="primary", use_container_width=True)

if compare_btn:
    if not original_files or not modified_files:
        st.error("Debe cargar al menos un PDF original y un PDF modificado.")
        st.stop()

    with st.spinner("Leyendo PDFs y detectando cambios..."):
        originals: List[SurveyDoc] = []
        modifieds: List[SurveyDoc] = []

        for f in original_files:
            originals.append(build_survey_doc(f.name, f.getvalue()))

        for f in modified_files:
            modifieds.append(build_survey_doc(f.name, f.getvalue()))

        if not originals:
            st.error("No se pudieron procesar los originales.")
            st.stop()

        orig_by_type: Dict[str, SurveyDoc] = {o.survey_type: o for o in originals}

        comparisons = []
        rows = []

        for mod in modifieds:
            original = orig_by_type.get(mod.survey_type)
            if not original:
                rows.append({
                    "Archivo": mod.filename,
                    "Tipo": mod.survey_type,
                    "Delegación": f"{mod.delegacion_codigo} - {mod.delegacion_lugar}",
                    "Estado": "Sin original asociado",
                    "Cambios": "",
                })
                continue

            comp = compare_docs(original, mod)
            comparisons.append(comp)

            estado = "Sin cambios" if comp["total_changes"] == 0 else f"{comp['total_changes']} cambio(s)"
            rows.append({
                "Archivo": mod.filename,
                "Tipo": mod.survey_type,
                "Delegación": f"{mod.delegacion_codigo} - {mod.delegacion_lugar}",
                "Estado": estado,
                "Cambios": comp["total_changes"],
            })

    st.subheader("Resumen")
    st.dataframe(rows, use_container_width=True)

    for comp in comparisons:
        mod = comp["modified"]
        titulo = f"{mod.survey_type} | {mod.delegacion_codigo} - {mod.delegacion_lugar} | {mod.filename}"
        with st.expander(titulo, expanded=True):
            st.write(f"**Original asociado:** {comp['original'].filename}")
            if comp["total_changes"] == 0:
                st.success("No se detectaron cambios en preguntas ni respuestas.")
                continue

            if comp["new_questions"]:
                st.markdown("**Preguntas nuevas**")
                for item in comp["new_questions"]:
                    st.markdown(f"- **{item['qid']}**. {item['question']}")

            if comp["missing_questions"]:
                st.markdown("**Preguntas eliminadas o ausentes**")
                for item in comp["missing_questions"]:
                    st.markdown(f"- **{item['qid']}**. {item['question']}")

            if comp["question_changes"]:
                st.markdown("**Cambios por pregunta**")
                for ch in comp["question_changes"]:
                    st.markdown(f"### Pregunta {ch['qid']}")
                    if ch["question_text_changed"]:
                        st.markdown("**Texto original:**")
                        st.info(ch["old_question"])
                        st.markdown("**Texto nuevo:**")
                        st.warning(ch["new_question"])

                    if ch["changed_options"]:
                        st.markdown("**Opciones modificadas**")
                        for old_op, new_op in ch["changed_options"]:
                            st.markdown(f"- `{old_op}` → `{new_op}`")

                    if ch["added_options"]:
                        st.markdown("**Opciones agregadas**")
                        for op in ch["added_options"]:
                            st.markdown(f"- {op}")

                    if ch["removed_options"]:
                        st.markdown("**Opciones eliminadas**")
                        for op in ch["removed_options"]:
                            st.markdown(f"- {op}")

    if comparisons:
        pdf_bytes = build_report_pdf(comparisons)
        st.download_button(
            "Descargar reporte PDF",
            data=pdf_bytes,
            file_name="reporte_comparativo_formularios.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

        txt = []
        for comp in comparisons:
            mod = comp["modified"]
            txt.append(f"ARCHIVO: {mod.filename}")
            txt.append(f"TIPO: {mod.survey_type}")
            txt.append(f"DELEGACION: {mod.delegacion_codigo} - {mod.delegacion_lugar}")
            txt.append(f"CAMBIOS: {comp['total_changes']}")
            txt.append("-" * 80)
            for ch in comp["question_changes"]:
                txt.append(f"Pregunta {ch['qid']}")
                if ch["question_text_changed"]:
                    txt.append(f"  Texto original: {ch['old_question']}")
                    txt.append(f"  Texto nuevo   : {ch['new_question']}")
                for a, b in ch["changed_options"]:
                    txt.append(f"  Opción modificada: {a} -> {b}")
                for a in ch["added_options"]:
                    txt.append(f"  Opción agregada: {a}")
                for r in ch["removed_options"]:
                    txt.append(f"  Opción eliminada: {r}")
            for item in comp["new_questions"]:
                txt.append(f"Pregunta nueva: {item['qid']} - {item['question']}")
            for item in comp["missing_questions"]:
                txt.append(f"Pregunta ausente: {item['qid']} - {item['question']}")
            txt.append("")

        st.download_button(
            "Descargar reporte TXT",
            data="\n".join(txt).encode("utf-8"),
            file_name="reporte_comparativo_formularios.txt",
            mime="text/plain",
            use_container_width=True,
        )





