"""
Word (.docx) to plain text converter for LMS assessment documents.

Three known template structures are handled automatically based on
document shape — no filename hints required.

  Template A  —  "Assessor Guide" (Learning Vault single-table format)
                  One large table contains both a boilerplate header section
                  (Instructions / Range and conditions / Rubric rows) AND all
                  question content packed into a single merged question cell.
                  Correct answers are indicated by RED font colour.
                  Files: SIRXCEG*, SITEEVT*, SITHACS*, SITHCCC028,
                         SITHFAB023*, SITHFAB025*, SITEEVT029

  Template B  —  Per-question Short-Answer table (SITHCCC / SITX style)
                  A block of body-level metadata paragraphs (title, student
                  name, etc.) followed by one 3-column table per question.
                  The last row of each table is a merged cell whose text
                  already starts with "ASSESSOR KEY: " in dark-green colour.
                  Files: SITHCCC027, SITHCCC029, SITHCCC036,
                         SITHKOP010, SITXFSA005

  Template C  —  Per-question Multiple-Choice table (SITHCCC / SITX style)
                  Same header block as Template B but each table has 4 rows
                  × 3 effective columns.  Options are listed two per row
                  (Col 1 / Col 2).  The correct answer sits in the last row,
                  Col 2, as "ASSESSOR KEY: X" in dark-green colour.
                  Files: SITHCCC031, SITHCCC042, SITHCCC043,
                         SITHPAT016, SITXWHS005

Templates B and C share one extraction path because their "ASSESSOR KEY:"
prefix is already embedded as literal cell text — colour detection is
unnecessary.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO ADD A NEW TEMPLATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Add a detection branch in _detect_template() that returns a new label
   (e.g. "D") based on a reliable structural signal (table shape, first-cell
   text, presence of body paragraphs, etc.).
2. Implement _extract_template_d(doc) → list[dict] following the same
   pattern as the existing extractors.  Each dict must have:
       {"text": str, "label": str | None}
   where label is "ASSESSOR KEY", "ANSWER GUIDANCE", or None.
3. Add an elif branch in docx_to_text() to call your new extractor.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table
from docx.opc.exceptions import PackageNotFoundError
import re
import tempfile
import os
import zipfile


# ===========================================================================
# Shared colour helpers
# ===========================================================================

def _is_red_run(run) -> bool:
    """
    Return True when a text run uses the red font colour used in Template A
    to mark correct answers.  Threshold: R≥200, G≤80, B≤80.
    """
    try:
        rgb = run.font.color.rgb
        if rgb is None:
            return False
        return rgb[0] >= 200 and rgb[1] <= 80 and rgb[2] <= 80
    except Exception:
        return False


def _para_red_info(para: Paragraph) -> tuple[str, bool]:
    """Return (stripped text, has_any_red_run) for a paragraph."""
    text = "".join(run.text for run in para.runs).strip()
    any_red = any(_is_red_run(r) and r.text.strip() for r in para.runs)
    return text, any_red


def _answer_label(text: str) -> str:
    """
    Choose the label prefix for a red-text item in Template A.

    Answer-guidance intro lines (e.g. 'Answer may address, but is not
    limited to, three of the following:') get a distinct ANSWER GUIDANCE
    tag so the AI extractor can separate them from the actual answer
    bullet points.

    All other red text → ASSESSOR KEY.
    """
    t = text.lower()
    if t.startswith("answer may") or t.startswith("answer must"):
        return "ANSWER GUIDANCE"
    return "ASSESSOR KEY"


# ===========================================================================
# Shared textbox helper (floating DrawingML text boxes)
# ===========================================================================

def _textbox_texts(para: Paragraph) -> list[tuple[str, bool]]:
    """
    Extract (text, is_red) pairs from any floating text boxes anchored
    to this paragraph element.  Handles DrawingML txbxContent elements.
    """
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
            parts: list[str] = []
            any_red = False
            for r in p2.iter():
                if not str(getattr(r, "tag", "")).endswith("}r"):
                    continue
                run_text = "".join(
                    t.text for t in r.iter()
                    if str(getattr(t, "tag", "")).endswith("}t")
                    and getattr(t, "text", None)
                )
                if run_text:
                    parts.append(run_text)
            text = "".join(parts).strip()
            if text:
                out.append((text, any_red))
    return out


# ===========================================================================
# Document block iterator (preserves body order)
# ===========================================================================

def _iter_blocks(doc: Document):
    """
    Yield top-level body children as Paragraph or Table objects in
    document order.  This preserves the visual sequence of content.
    """
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


# ===========================================================================
# Template detection
# ===========================================================================

def _detect_template(doc: Document) -> str:
    """
    Inspect the document structure and return a template identifier string.

    Detection strategy: look at the FIRST table's first cell text.
      "instructions"  → Template A (Learning Vault assessor-guide format)
      starts with "q" → Template B/C (per-question table format)
      anything else   → "unknown" (generic fallback)

    Body-level paragraphs before the table are intentionally ignored here
    because both Template A and B/C can have them.
    """
    for block in _iter_blocks(doc):
        if isinstance(block, Table):
            try:
                first_cell = block.rows[0].cells[0].text.strip().lower()
            except Exception:
                first_cell = ""

            if first_cell == "instructions":
                return "A"
            if first_cell.startswith("q"):
                return "B_C"
            # First table doesn't match known patterns — stop searching
            break

    return "unknown"


# ===========================================================================
# Template A — Learning Vault "Assessor Guide" single-table format
# ===========================================================================

# Column-0 labels that identify boilerplate / metadata rows in Template A.
# These rows must be skipped; only the question-content row(s) are extracted.
#
# To support a variant that adds new row labels (e.g. "Marking criteria"),
# extend this set — no other code changes are needed.
_TEMPLATE_A_SKIP_LABELS: frozenset[str] = frozenset({
    # ── Header boilerplate (top of table) ──────────────────────────────────
    "instructions",
    "range and conditions",
    "decision-making rules",
    "pre-approved reasonable adjustments",
    "rubric",
    # ── Footer boilerplate (bottom of table, SA format only) ───────────────
    "learner feedback",
    "assessment outcome",
    "assessor signature",
    "assessor name",
    "date",
    "final comments",
})


def _is_boilerplate_row_a(row) -> bool:
    """
    Return True when a Template A table row contains only boilerplate
    metadata that should not be included in the extracted text.

    Two conditions trigger a skip:
      1. The Col-0 label matches a known boilerplate name (e.g. "Rubric").
      2. All cells contain identical text that begins with "knowledge test"
         — these are section-heading rows that span the full table width.
    """
    try:
        col0 = row.cells[0].text.strip().lower()
    except Exception:
        return False

    # Condition 1: explicit boilerplate label in the first column
    if col0 in _TEMPLATE_A_SKIP_LABELS:
        return True

    # Condition 2: merged section-heading row such as "Knowledge Test 2 – MC"
    # All cells share the same text because the row is a full-width merge.
    unique_cell_texts = {c.text.strip().lower() for c in row.cells}
    if len(unique_cell_texts) == 1 and col0.startswith("knowledge test"):
        return True

    return False


def _extract_template_a(doc: Document) -> list[dict]:
    """
    Extract question content from a Template A document.

    Processing rules:
    • Boilerplate rows (header + footer) are skipped entirely — this
      eliminates false ASSESSOR KEY tags from the Rubric red bullets.
    • Within question-content rows, red-text paragraphs are labelled:
        - "ANSWER GUIDANCE" for intro lines like "Answer may address…"
        - "ASSESSOR KEY"    for actual answer text / correct MC options
    • Floating text-box text is extracted if present.
    • Consecutive duplicate items (from merged cells) are deduplicated.
    """
    items: list[dict] = []
    last_key: tuple | None = None

    def push(text: str, label: str | None) -> None:
        nonlocal last_key
        text = text.strip()
        if not text:
            return
        key = (text, label)
        if key == last_key:
            return  # deduplicate merged-cell repetitions
        items.append({"text": text, "label": label})
        last_key = key

    def process_para(para: Paragraph) -> None:
        text, is_red = _para_red_info(para)
        push(text, _answer_label(text) if is_red else None)
        for tb_text, tb_red in _textbox_texts(para):
            push(tb_text, _answer_label(tb_text) if tb_red else None)

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            # Body-level paragraphs in Template A are usually just the test
            # title (e.g. "Knowledge Test 2 - Multiple Choice") — keep them
            # as plain-text context for the AI extractor.
            text, _ = _para_red_info(block)
            push(text, None)

        elif isinstance(block, Table):
            for row in block.rows:
                if _is_boilerplate_row_a(row):
                    continue  # skip Instructions, Rubric, footer rows, etc.
                for cell in row.cells:
                    for para in cell.paragraphs:
                        process_para(para)

    return items


# ===========================================================================
# Template B / C — Per-question table format (SITHCCC / SITX style)
# ===========================================================================

# Substrings that identify body-level header paragraphs in Templates B/C.
# These appear before the question tables and contain student/admin metadata.
_TEMPLATE_BC_SKIP_SUBSTRINGS: tuple[str, ...] = (
    "knowledge test",        # e.g. "KNOWLEDGE TEST -- SHORT ANSWER"
    "student name",          # "Student Name: ___"
    "assessor:",             # "Assessor: ___"
    "result:",               # "Result: Satisfactory [ ]"
    "instructions:",         # "Instructions: Answer ALL questions"
    "write in full sentence", # "Write in full sentences where indicated."
    "sit30",                 # qualification code prefix e.g. "SIT30821"
    "total marks",           # "Total marks: 32"
)


def _is_header_para_bc(text: str) -> bool:
    """
    Return True when a body paragraph is metadata that should be skipped
    in Templates B/C (student admin header, qualification title, etc.).
    """
    t = text.lower()
    return any(pattern in t for pattern in _TEMPLATE_BC_SKIP_SUBSTRINGS)


def _extract_template_bc(doc: Document) -> list[dict]:
    """
    Extract question content from a Template B or C document.

    Processing rules:
    • Body-level metadata header paragraphs are skipped (student name,
      assessor, qualification title, etc.).
    • Each per-question table is extracted cell-by-cell in row order.
    • The "ASSESSOR KEY: " prefix is already embedded as literal text in
      the answer cell — no colour detection is required.
    • Consecutive duplicate items (from merged cells) are deduplicated.

    Template B (SA): last row of each table is a merged cell containing
      "ASSESSOR KEY: {full answer text}"

    Template C (MC): last row Col 2 contains "ASSESSOR KEY: {letter}"
      Options appear two per row across Col 1 and Col 2.
    """
    items: list[dict] = []
    last_text: str | None = None

    def push(text: str) -> None:
        nonlocal last_text
        text = text.strip()
        if not text:
            return
        if text == last_text:
            return  # deduplicate merged-cell repetitions
        items.append({"text": text, "label": None})
        last_text = text

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text and not _is_header_para_bc(text):
                push(text)

        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        push(para.text)
                        for tb_text, _ in _textbox_texts(para):
                            push(tb_text)

    return items


# ===========================================================================
# Generic fallback (unknown / future template)
# ===========================================================================

def _extract_generic(doc: Document) -> list[dict]:
    """
    Fallback extractor for unrecognised templates.

    Extracts all text in document order using red-text detection for
    answer labelling.  No boilerplate filtering is applied.

    This is a best-effort path.  If a new template type is encountered
    regularly, implement a dedicated extractor (see module docstring).
    """
    items: list[dict] = []
    last_key: tuple | None = None

    def push(text: str, label: str | None) -> None:
        nonlocal last_key
        text = text.strip()
        if not text:
            return
        key = (text, label)
        if key == last_key:
            return
        items.append({"text": text, "label": label})
        last_key = key

    def process_para(para: Paragraph) -> None:
        text, is_red = _para_red_info(para)
        push(text, _answer_label(text) if is_red else None)
        for tb_text, tb_red in _textbox_texts(para):
            push(tb_text, _answer_label(tb_text) if tb_red else None)

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            process_para(block)
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        process_para(para)

    return items


# ===========================================================================
# Private helper: instruction extraction from an already-loaded Document
# ===========================================================================

def _instructions_from_doc(doc: Document, template: str) -> str:
    """
    Extract the boilerplate instruction block from an already-loaded Document.

    Called by extract_document() on the same doc object used for raw_text,
    so the file is only read and parsed once.

    Template A only — returns "" for all other templates.
    """
    if template != "A":
        return ""

    sections: list[str] = []
    seen: set[str] = set()

    for block in _iter_blocks(doc):
        if not isinstance(block, Table):
            continue

        for row in block.rows:
            if not _is_boilerplate_row_a(row):
                continue  # skip question rows

            col0 = row.cells[0].text.strip()

            # Skip merged section-heading rows ("Knowledge Test N …")
            if col0.lower().startswith("knowledge test"):
                continue

            # Pick the content cell by content length rather than a fixed
            # column index — robust to columns being added, removed, or
            # reordered. Column 0 is always the label ("Instructions",
            # "Rubric", …); the content lives in whichever remaining cell
            # has the most text (for 3-column SA tables, columns 1 and 2
            # are merged duplicates of the same text — length-based
            # selection handles that too, since either one wins equally).
            candidates  = row.cells[1:] or row.cells[:1]
            content_cell = max(candidates, key=lambda c: len(c.text))
            content_lines = [
                p.text.strip()
                for p in content_cell.paragraphs
                if p.text.strip()
            ]
            content = "\n".join(content_lines)

            # Deduplicate identical sections that appear across merged cells
            key = f"{col0}|{content}"
            if key in seen:
                continue
            seen.add(key)

            if content:
                sections.append(f"[{col0}]\n{content}")

    return "\n\n".join(sections)


# ===========================================================================
# Points — global per-question mark value stated in the instructions block
# ===========================================================================

_POINTS_PATTERN = re.compile(r"graded out of\s+(\d+(?:\.\d+)?)\s*marks?", re.IGNORECASE)


def parse_points_per_question(instructions_text: str) -> float | None:
    """
    Extract the global per-question mark value from the Instructions block
    (Template A only), e.g. "Each question is graded out of 1 mark." →  1.0.

    This is the authoritative source for points when present — every sample
    Template A document states this uniformly, so it should override
    whatever value the AI extractor guessed per-question. Returns None when
    no such statement is found; callers should fall back to the
    per-question AI-extracted value in that case, and leave points unset
    if that's also absent rather than inventing a number.
    """
    if not instructions_text:
        return None
    match = _POINTS_PATTERN.search(instructions_text)
    if not match:
        return None
    return float(match.group(1))


# ===========================================================================
# Public API
# ===========================================================================

def extract_document(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """
    Parse a .docx file ONCE and return both extracted texts as a tuple:
        (raw_text, instructions_text)

    raw_text        — question content only, with ASSESSOR KEY / ANSWER GUIDANCE
                      labels, ready for the AI extractor.
    instructions_text — boilerplate section (Instructions, Rubric, Range, etc.)
                        stored as ground truth for future validation.
                        Empty string for Templates B/C which have no structured
                        instruction block.

    The file is opened exactly once; both values are derived from the same
    Document object so there is no redundant disk or parse overhead.
    """
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        try:
            doc = Document(tmp_path)
        except (zipfile.BadZipFile, KeyError, PackageNotFoundError) as e:
            # PackageNotFoundError/BadZipFile: the file isn't a zip archive
            # at all (e.g. a .pdf, .txt, or image renamed to .docx).
            # KeyError: it IS a zip but missing required Word package parts
            # (e.g. a .xlsx/.pptx renamed to .docx, or a corrupted file).
            raise ValueError(
                f"'{filename}' doesn't appear to be a valid .docx file "
                f"(it may be a different format, renamed, or corrupted): {e}"
            ) from e

        template = _detect_template(doc)

        # --- Question content (raw_text) ------------------------------------
        if template == "A":
            items = _extract_template_a(doc)
        elif template == "B_C":
            items = _extract_template_bc(doc)
        else:
            items = _extract_generic(doc)

        lines: list[str] = []
        for item in items:
            label = item.get("label")
            text  = item["text"]
            lines.append(f"{label}: {text}" if label else text)
            lines.append("")  # blank separator between items

        raw_text = "\n".join(lines).strip()

        # --- Instruction block (instructions_text) --------------------------
        # Reuses the same doc object — no second file read needed.
        instructions_text = _instructions_from_doc(doc, template)

        return raw_text, instructions_text

    finally:
        os.unlink(tmp_path)


def docx_to_text(file_bytes: bytes, filename: str) -> str:
    """
    Convenience wrapper — returns only raw_text.
    Prefer extract_document() when you also need instructions_text.
    """
    raw_text, _ = extract_document(file_bytes, filename)
    return raw_text
