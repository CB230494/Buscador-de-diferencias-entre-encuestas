# -*- coding: utf-8 -*-

import io
import re
import html
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import fitz  # PyMuPDF
import streamlit as st
from pypdf import PdfReader
from rapidfuzz import fuzz

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

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
    text = text.replace("\r", "\n")
    text = text.replace("•", "\n• ").replace("☐", "\n☐ ").replace("□", "\n□ ")
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
    text = re.sub(r"^\s*(?:☐|□|•|o|\(\s*\)|\(\s*[xX]\s*\)|-)\s*", "", text)
    text = re.sub(r"\s*[_\.]{3,}\s*$", "", text)
    return text.strip(" .;:-")


def safe_filename(name: str) -> str:
    name = strip_accents(name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name.strip("_") or "archivo"


def dedupe_preserve(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        key = normalize_option(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


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
            fallback = extract_text_pypdf(file_bytes)
            if len(fallback.strip()) > len(text.strip()):
                text = fallback
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

    m2 = re.search(r"\bD\s*[0-9]{1,3}\s+([A-ZÁÉÍÓÚÜÑ ]{3,})", head)
    if m2:
        lugar = m2.group(1).strip()
    else:
        for ln in lines[:10]:
            if re.fullmatch(r"[A-ZÁÉÍÓÚÜÑ ]{4,}", ln) and "ENCUESTA" not in ln and "ESTRATEGIA" not in ln:
                if not re.search(r"\b(COMUNIDAD|COMERCIO|POLICIAL|CONSENTIMIENTO)\b", ln):
                    lugar = ln.strip()
                    break

    lugar = re.sub(r"\s{2,}", " ", lugar)
    return codigo, lugar.title()


# =========================================================
# Extracción de preguntas
# =========================================================

Q_START_RE = re.compile(r"(?m)^(?P<qid>\d{1,2}(?:\.\d+)?)\s*[\.\-–]\s*(?P<rest>.+)$")

NOISE_PREFIXES = (
    "nota", "nota previa", "nota condicional", "logica condicional", "lógica condicional",
    "apartado ", "riesgos sociales", "victimizacion", "victimización", "delitos",
    "propuestas ciudadanas", "confianza policial", "informacion adicional", "información adicional",
    "programa seguridad comercial", "datos generales", "contexto territorial",
    "informacion de condiciones", "información de condiciones"
)


def preprocess_question_text(text: str) -> str:
    text = norm(text)
    for i in range(1, 51):
        text = text.replace(f"{i}- ", f"{i}. ")
        text = text.replace(f"{i}-¿", f"{i}. ¿")
        text = text.replace(f"{i}- ¿", f"{i}. ¿")
    return text


def split_question_blocks(text: str) -> List[Tuple[str, str]]:
    text = preprocess_question_text(text)
    matches = list(Q_START_RE.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((m.group("qid"), text[start:end].strip()))
    return blocks


def is_noise_line(line: str) -> bool:
    raw = normalize_for_compare(line)
    if not raw:
        return True
    if raw.startswith(NOISE_PREFIXES):
        return True
    if raw in {"fin", "no hay respuestas correctas o incorrectas", "(recuerde, su informacion es confidencial.)"}:
        return True
    return False


def is_scale_or_matrix_line(line: str) -> bool:
    raw = normalize_for_compare(line)
    if re.fullmatch(r"[0-9 ]{3,}", raw):
        return True
    if raw in {
        "1 2 3 4 5", "1 2 3 4 5 6 7 8 9 10", "zona muy inseguro inseguro ni seguro ni inseguro seguro muy seguro no aplica"
    }:
        return True
    if any(token in raw for token in ["muy inseguro", "ni seguro ni inseguro", "muy seguro", "no aplica"]):
        return True
    return False


def is_option_line(line: str) -> bool:
    raw = line.strip()
    if not raw or is_noise_line(raw):
        return False
    if is_scale_or_matrix_line(raw):
        return False
    lowered = normalize_for_compare(raw)
    if re.match(r"^\s*(?:☐|□|•|o|\(\s*\)|\(\s*[xX]\s*\)|-)\s*", raw):
        return True
    if raw.startswith("Otro:") or raw.startswith("Otro "):
        return True
    if lowered in {"si", "no", "no aplica", "no indica", "desconocido", "ninguno de los anteriores"}:
        return True
    return False


def clean_option_line(line: str) -> str:
    line = norm(line)
    line = re.sub(r"^\s*(?:☐|□|•|o|\(\s*\)|\(\s*[xX]\s*\)|-)\s*", "", line)
    line = re.sub(r"\s*[_\.]{3,}\s*$", "", line)
    return line.strip(" ;")


def parse_question_block(qid: str, block: str) -> QuestionBlock:
    lines = [ln.strip() for ln in norm(block).splitlines() if ln.strip()]
    if not lines:
        return QuestionBlock(qid=qid, raw_header=qid, question_text="", options=[], raw_block=block)

    header = re.sub(rf"^{re.escape(qid)}\s*[\.\-–]?\s*", "", lines[0]).strip()
    question_lines = [header]
    options = []

    for line in lines[1:]:
        if is_noise_line(line):
            continue
        if is_option_line(line):
            options.append(clean_option_line(line))
        elif not is_scale_or_matrix_line(line):
            if options and len(line) < 90 and not re.match(r"^\d+(?:\.\d+)?", line):
                options[-1] = f"{options[-1]} {clean_option_line(line)}".strip()
            else:
                question_lines.append(line)

    question_text = " ".join(question_lines).strip()
    question_text = re.sub(r"\s+", " ", question_text)
    question_text = re.sub(r"\s*[_\.]{3,}\s*$", "", question_text)

    # eliminar falsos positivos de matrices donde cada fila fue tomada como opción sin sentido
    filtered_options = []
    for opt in dedupe_preserve(options):
        nopt = normalize_option(opt)
        if not nopt or is_noise_line(opt) or is_scale_or_matrix_line(opt):
            continue
        if len(nopt) <= 1:
            continue
        filtered_options.append(opt)

    return QuestionBlock(
        qid=qid,
        raw_header=header,
        question_text=question_text,
        options=filtered_options,
        raw_block=block,
    )


def extract_questions(text: str) -> Dict[str, QuestionBlock]:
    data: Dict[str, QuestionBlock] = {}
    for qid, block in split_question_blocks(text):
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

    unmatched_old = dict(old_norm_map)
    unmatched_new = dict(new_norm_map)
    changed = []

    for k in list(unmatched_old.keys()):
        if k in unmatched_new:
            unmatched_old.pop(k, None)
            unmatched_new.pop(k, None)

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
        if best_key is not None and best_score >= 84:
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
    all_ids = sorted(set(oq.keys()) | set(mq.keys()), key=lambda x: [int(n) for n in re.findall(r"\d+", x)])

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

        question_text_changed = not smart_equal(old.question_text, new.question_text, threshold=98)
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
        len(result["question_changes"]) + len(result["new_questions"]) + len(result["missing_questions"])
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
        rightMargin=30,
        leftMargin=30,
        topMargin=34,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small2", parent=styles["BodyText"], fontSize=8.5, leading=10.5, spaceAfter=2))
    styles.add(ParagraphStyle(name="BoxTitle", parent=styles["Heading3"], fontSize=10.2, leading=12, spaceAfter=5, textColor=colors.HexColor("#12395b")))
    styles.add(ParagraphStyle(name="Meta", parent=styles["BodyText"], fontSize=9, leading=11))

    elems = []
    elems.append(Paragraph("Reporte comparativo de preguntas y opciones", styles["Title"]))
    elems.append(Paragraph("Solo se muestran cambios sustantivos en preguntas y respuestas. Las notas, leyendas e instrucciones no se incluyen.", styles["Meta"]))
    elems.append(Spacer(1, 0.16 * inch))

    summary_data = [["Archivo", "Tipo", "Delegación", "Detalle"]]
    for comp in comparisons:
        mod = comp["modified"]
        detalle = "Sin cambios" if comp["total_changes"] == 0 else f"{comp['total_changes']} cambio(s) con detalle"
        summary_data.append([mod.filename, mod.survey_type, f"{mod.delegacion_codigo} - {mod.delegacion_lugar}", detalle])

    table = Table(summary_data, colWidths=[2.65 * inch, 0.9 * inch, 1.55 * inch, 1.35 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#f3f6f9")]),
    ]))
    elems.append(table)
    elems.append(PageBreak())

    for idx, comp in enumerate(comparisons, 1):
        mod = comp["modified"]
        orig = comp["original"]
        elems.append(Paragraph(f"{idx}. {html.escape(mod.filename)}", styles["Heading1"]))
        elems.append(Paragraph(
            f"<b>Tipo:</b> {mod.survey_type} &nbsp;&nbsp; <b>Delegación:</b> {mod.delegacion_codigo} - {html.escape(mod.delegacion_lugar)}<br/>"
            f"<b>Original asociado:</b> {html.escape(orig.filename)}",
            styles["Meta"],
        ))
        elems.append(Spacer(1, 0.08 * inch))

        if comp["total_changes"] == 0:
            elems.append(Paragraph("No se detectaron cambios en preguntas ni opciones de respuesta.", styles["BodyText"]))
            if idx < len(comparisons):
                elems.append(PageBreak())
            continue

        for item in comp["new_questions"]:
            elems.append(Paragraph(f"Pregunta nueva {item['qid']}", styles["BoxTitle"]))
            elems.append(Paragraph(html.escape(item["question"]), styles["Small2"]))
            elems.append(Spacer(1, 0.04 * inch))

        for item in comp["missing_questions"]:
            elems.append(Paragraph(f"Pregunta ausente {item['qid']}", styles["BoxTitle"]))
            elems.append(Paragraph(html.escape(item["question"]), styles["Small2"]))
            elems.append(Spacer(1, 0.04 * inch))

        for ch in comp["question_changes"]:
            elems.append(Paragraph(f"Pregunta {ch['qid']}", styles["BoxTitle"]))
            if ch["question_text_changed"]:
                elems.append(Paragraph(f"<b>Texto original:</b> {html.escape(ch['old_question'])}", styles["Small2"]))
                elems.append(Paragraph(f"<b>Texto modificado:</b> {html.escape(ch['new_question'])}", styles["Small2"]))
            for old_op, new_op in ch["changed_options"]:
                elems.append(Paragraph(f"• <b>Opción modificada:</b> {html.escape(old_op)} <b>→</b> {html.escape(new_op)}", styles["Small2"]))
            for op in ch["added_options"]:
                elems.append(Paragraph(f"• <b>Opción agregada:</b> {html.escape(op)}", styles["Small2"]))
            for op in ch["removed_options"]:
                elems.append(Paragraph(f"• <b>Opción eliminada:</b> {html.escape(op)}", styles["Small2"]))
            elems.append(Spacer(1, 0.06 * inch))

        if idx < len(comparisons):
            elems.append(PageBreak())

    doc.build(elems)
    return buffer.getvalue()


# =========================================================
# UI
# =========================================================

st.title("Comparador de Formularios PDF")
st.caption("Compara solo preguntas y opciones de respuesta. No toma en cuenta notas, leyendas ni instrucciones.")

with st.expander("Qué detecta esta versión", expanded=False):
    st.markdown(
        """
        - Cambios en el texto de la pregunta.
        - Opciones agregadas.
        - Opciones eliminadas.
        - Opciones modificadas.
        - Preguntas nuevas o ausentes.

        No incluye notas, aclaraciones, leyendas ni texto de poca importancia.
        """
    )

col1, col2 = st.columns(2)
with col1:
    original_files = st.file_uploader("PDFs originales", type=["pdf"], accept_multiple_files=True, key="orig")
with col2:
    modified_files = st.file_uploader("PDFs modificados", type=["pdf"], accept_multiple_files=True, key="mod")

compare_btn = st.button("Comparar formularios", type="primary", use_container_width=True)

if compare_btn:
    if not original_files or not modified_files:
        st.error("Debe cargar al menos un PDF original y un PDF modificado.")
        st.stop()

    with st.spinner("Leyendo PDFs y comparando preguntas/opciones..."):
        originals = [build_survey_doc(f.name, f.getvalue()) for f in original_files]
        modifieds = [build_survey_doc(f.name, f.getvalue()) for f in modified_files]
        orig_by_type = {o.survey_type: o for o in originals}

        comparisons = []
        resumen_rows = []

        for mod in modifieds:
            original = orig_by_type.get(mod.survey_type)
            if not original:
                resumen_rows.append({
                    "Archivo": mod.filename,
                    "Tipo": mod.survey_type,
                    "Delegación": f"{mod.delegacion_codigo} - {mod.delegacion_lugar}",
                    "Resultado": "Sin original asociado",
                })
                continue

            comp = compare_docs(original, mod)
            comparisons.append(comp)
            resumen_rows.append({
                "Archivo": mod.filename,
                "Tipo": mod.survey_type,
                "Delegación": f"{mod.delegacion_codigo} - {mod.delegacion_lugar}",
                "Resultado": "Sin cambios" if comp["total_changes"] == 0 else f"{comp['total_changes']} cambio(s) con detalle",
            })

    st.subheader("Resumen")
    st.dataframe(resumen_rows, use_container_width=True, hide_index=True)

    for comp in comparisons:
        mod = comp["modified"]
        with st.expander(f"{mod.survey_type} | {mod.delegacion_codigo} - {mod.delegacion_lugar} | {mod.filename}", expanded=True):
            st.markdown(f"**Original asociado:** {comp['original'].filename}")

            if comp["total_changes"] == 0:
                st.success("No se detectaron cambios en preguntas ni opciones de respuesta.")
                continue

            if comp["new_questions"]:
                st.markdown("### Preguntas nuevas")
                for item in comp["new_questions"]:
                    st.markdown(f"**{item['qid']}** — {item['question']}")

            if comp["missing_questions"]:
                st.markdown("### Preguntas ausentes")
                for item in comp["missing_questions"]:
                    st.markdown(f"**{item['qid']}** — {item['question']}")

            if comp["question_changes"]:
                st.markdown("### Cambios detectados por pregunta")
                for ch in comp["question_changes"]:
                    st.markdown(f"#### Pregunta {ch['qid']}")
                    if ch["question_text_changed"]:
                        st.markdown("**Texto original**")
                        st.code(ch["old_question"])
                        st.markdown("**Texto modificado**")
                        st.code(ch["new_question"])
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
            "Descargar reporte PDF detallado",
            data=pdf_bytes,
            file_name="reporte_comparativo_formularios_detallado.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

        lines = []
        for comp in comparisons:
            mod = comp["modified"]
            lines.append(f"ARCHIVO: {mod.filename}")
            lines.append(f"TIPO: {mod.survey_type}")
            lines.append(f"DELEGACION: {mod.delegacion_codigo} - {mod.delegacion_lugar}")
            lines.append(f"TOTAL CAMBIOS: {comp['total_changes']}")
            lines.append("-" * 90)
            for item in comp["new_questions"]:
                lines.append(f"PREGUNTA NUEVA {item['qid']}: {item['question']}")
            for item in comp["missing_questions"]:
                lines.append(f"PREGUNTA AUSENTE {item['qid']}: {item['question']}")
            for ch in comp["question_changes"]:
                lines.append(f"PREGUNTA {ch['qid']}")
                if ch["question_text_changed"]:
                    lines.append(f"  TEXTO ORIGINAL : {ch['old_question']}")
                    lines.append(f"  TEXTO NUEVO    : {ch['new_question']}")
                for old_op, new_op in ch["changed_options"]:
                    lines.append(f"  OPCION MODIFICADA: {old_op} -> {new_op}")
                for op in ch["added_options"]:
                    lines.append(f"  OPCION AGREGADA : {op}")
                for op in ch["removed_options"]:
                    lines.append(f"  OPCION ELIMINADA: {op}")
            lines.append("")

        st.download_button(
            "Descargar reporte TXT detallado",
            data="\n".join(lines).encode("utf-8"),
            file_name="reporte_comparativo_formularios_detallado.txt",
            mime="text/plain",
            use_container_width=True,
        )
