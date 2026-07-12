from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table
import tempfile
import os


# ---------------------------------------------------------------------------
# Helpers: red-run detection
# ---------------------------------------------------------------------------

def _is_red_run(run) -> bool:
    try:
        rgb = run.font.color.rgb
        if rgb is None:
            return False
        return rgb[0] >= 200 and rgb[1] <= 80 and rgb[2] <= 80
    except Exception:
        return False


def _para_text_and_red(para: Paragraph) -> tuple[str, bool]:
    text = "".join(run.text for run in para.runs).strip()
    any_red = any(_is_red_run(r) and r.text.strip() for r in para.runs)
    return text, any_red


# ---------------------------------------------------------------------------
# Helpers: textbox / DrawingML text extraction
# ---------------------------------------------------------------------------

def _textbox_texts(para: Paragraph) -> list[tuple[str, bool]]:
    """Extract text from floating text boxes embedded in this paragraph."""
    out = []
    try:
        p_elm = para._p
    except Exception:
        return out
    for el in p_elm.iter():
        if not str(getattr(el, "tag", "")).endswith("}txbxContent"):
            continue
        for p2 in el.iter():
            if not str(getattr(p2, "tag", "")).endswith("}p"):
                continue
            parts, any_red = [], False
            for r in p2.iter():
                if not str(getattr(r, "tag", "")).endswith("}r"):
                    continue
                run_text = "".join(
                    t.text for t in r.iter()
                    if str(getattr(t, "tag", "")).endswith("}t") and getattr(t, "text", None)
                )
                if run_text:
                    parts.append(run_text)
            text = "".join(parts).strip()
            if text:
                out.append((text, any_red))
    return out


# ---------------------------------------------------------------------------
# Block iteration (paragraphs + tables in document order)
# ---------------------------------------------------------------------------

def _iter_blocks(doc: Document):
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def docx_to_markdown(file_bytes: bytes, filename: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        doc = Document(tmp_path)
        items: list[dict] = []  # {"text": str, "is_red": bool}
        last_key = None

        def push(text: str, is_red: bool):
            nonlocal last_key
            text = text.strip()
            if not text:
                return
            key = (text, is_red)
            if key == last_key:
                return  # skip merged-cell duplicates
            items.append({"text": text, "is_red": is_red})
            last_key = key

        def process_para(para: Paragraph):
            text, red = _para_text_and_red(para)
            push(text, red)
            for t, r in _textbox_texts(para):
                push(t, r)

        for block in _iter_blocks(doc):
            if isinstance(block, Paragraph):
                process_para(block)
            elif isinstance(block, Table):
                for row in block.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            process_para(para)

        # Build plain text — red items (assessor keys) are labelled explicitly
        lines = []
        for item in items:
            text = item["text"]
            if item["is_red"]:
                lines.append(f"ASSESSOR KEY: {text}")
            else:
                lines.append(text)
            lines.append("")  # blank line between items for readability

        return "\n".join(lines).strip()
    finally:
        os.unlink(tmp_path)
