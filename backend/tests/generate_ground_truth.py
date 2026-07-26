"""
Generates a basic answer-key ground truth for each .docx file in
tests/input/Quiz — a single Model A (Claude) extraction pass, with
NO retry loop, NO consistency scoring, and NO grounding/schema checks.
Only the core answer-key fields are kept.

Meant to be hand-reviewed/corrected, then used as the reference set
that run_integration_test.py's output is compared against.

MCQ files  -> per question: id, question, choices, correct_answer, mark, feedback
            + total_questions, total_marks, total_choices, total_correct_answers
SA files   -> per question: id, question, answer, feedback
            + total_questions, total_answers

Run from inside backend/:
    python tests/generate_ground_truth.py

Or point at a custom folder:
    python tests/generate_ground_truth.py /path/to/docx/folder
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.classifier import classify_document_type
from app.services.converter import extract_document, parse_points_per_question
from app.services.extractor import _extract_model, _normalise

DEFAULT_DOCX_DIR = os.path.join(os.path.dirname(__file__), "input", "Quiz")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results", "groundtruth")


def _simplify_mcq(q: dict) -> dict:
    return {
        "id":             q.get("id"),
        "question":       q.get("text"),
        "choices":        q.get("choices") or [],
        "correct_answer": q.get("correct_answer"),
        "mark":           q.get("points"),
        "feedback":       q.get("feedback") or "",
    }


def _simplify_sa(q: dict) -> dict:
    return {
        "id":       q.get("id"),
        "question": q.get("text"),
        "answer":   q.get("correct_answer"),
        "mark":     q.get("points"),
        "feedback": q.get("feedback") or "",
    }


async def _run_one(filename: str, file_bytes: bytes) -> dict:
    text, instructions = extract_document(file_bytes, filename)
    file_type = classify_document_type(filename)

    raw_a = await _extract_model(text, "MODEL_A_API_KEY", "MODEL_A_BASE_URL", "MODEL_A_ID")
    norm_a = _normalise(raw_a, "model_a", filename)
    questions = norm_a.get("questions", [])

    rubric_points = parse_points_per_question(instructions)
    if rubric_points is not None:
        questions = [{**q, "points": rubric_points} for q in questions]

    is_mcq = file_type == "quiz_multiple_choice"

    if is_mcq:
        simplified = [_simplify_mcq(q) for q in questions]
        record = {
            "filename":              filename,
            "file_type":             file_type,
            "questions":             simplified,
            "total_questions":       len(simplified),
            "total_marks":           sum(q.get("mark") or 0 for q in simplified),
            "total_choices":         sum(len(q["choices"]) for q in simplified),
            "total_correct_answers": sum(
                sum(1 for c in q["choices"] if c.get("correct"))
                for q in simplified
            ),
        }
    else:
        simplified = [_simplify_sa(q) for q in questions]
        record = {
            "filename":        filename,
            "file_type":       file_type,
            "questions":       simplified,
            "total_questions": len(simplified),
            "total_marks":     sum(q.get("mark") or 0 for q in simplified),
            "total_answers":   sum(1 for q in simplified if (q.get("answer") or "").strip()),
        }

    if norm_a.get("error"):
        record["extraction_error"] = norm_a["error"]

    return record


async def main(docx_dir: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    docx_files = sorted(
        f for f in os.listdir(docx_dir)
        if f.endswith(".docx") and not f.startswith("~$")
    )

    if not docx_files:
        print(f"No DOCX files found in: {docx_dir}")
        return

    print(f"Found {len(docx_files)} files in: {docx_dir}")
    print(f"Output folder : {OUTPUT_DIR}")
    print("-" * 70)

    summary = []

    for filename in docx_files:
        docx_path = os.path.join(docx_dir, filename)
        base_name = os.path.splitext(filename)[0]
        out_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")

        t0 = time.time()
        try:
            with open(docx_path, "rb") as f:
                file_bytes = f.read()

            record = await _run_one(filename, file_bytes)
            elapsed = time.time() - t0

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)

            if "total_choices" in record:
                extra_str = (
                    f", marks={record['total_marks']}, "
                    f"choices={record['total_choices']}, "
                    f"correct={record['total_correct_answers']}"
                )
            else:
                extra_str = f", marks={record['total_marks']}, answers={record['total_answers']}"
            err_str = f" ⚠ {record['extraction_error']}" if record.get("extraction_error") else ""
            print(
                f"  OK   {filename} — {record['file_type']}, "
                f"{record['total_questions']}Q{extra_str}, {elapsed:.1f}s{err_str}"
            )
            summary.append({
                "filename":              filename,
                "file_type":             record["file_type"],
                "total_questions":       record["total_questions"],
                "total_marks":           record.get("total_marks"),
                "total_choices":         record.get("total_choices"),
                "total_correct_answers": record.get("total_correct_answers"),
                "total_answers":         record.get("total_answers"),
                "extraction_error":      record.get("extraction_error"),
                "elapsed_sec":           round(elapsed, 1),
            })

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR {filename} → {e}")
            summary.append({
                "filename":    filename,
                "status":      "ERROR",
                "error":       str(e),
                "elapsed_sec": round(elapsed, 1),
            })

    summary_path = os.path.join(OUTPUT_DIR, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("-" * 70)
    errored = sum(1 for s in summary if s.get("status") == "ERROR")
    print(f"Done: {len(summary) - errored} generated, {errored} errored")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    docx_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOCX_DIR
    asyncio.run(main(os.path.abspath(docx_dir)))
