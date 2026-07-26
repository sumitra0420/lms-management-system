"""
Runs the full production extraction pipeline (same steps as
app/routers/jobs.py::_process_job) against every .docx file in
tests/input/Quiz, WITHOUT touching the database. Saves one JSON per
file to tests/output/test_results/integration/, plus a _summary.json.

Compare this output against tests/output/test_results/groundtruth/
(see generate_ground_truth.py) to check the full pipeline's field-level
accuracy against the hand-reviewed answer key.

Run from inside backend/:
    python tests/run_integration_test.py

Or point at a custom folder:
    python tests/run_integration_test.py /path/to/docx/folder
"""

import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# app/main.py configures this same logging setup when running under uvicorn,
# which is why [Extractor]/[Consistency] INFO logs are visible there. This
# script never imports app.main, so without this call those INFO-level logs
# (model start, per-model question counts, consistency scores, retry
# attempts) would be silently dropped — only WARNING+ would show.
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

from app.services.classifier import classify_document_type
from app.services.consistency import check_with_retry
from app.services.converter import extract_document, parse_points_per_question
from app.services.grounding import check_question_grounding
from app.schemas.question import validate_questions

DEFAULT_DOCX_DIR = os.path.join(os.path.dirname(__file__), "input", "Quiz")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results", "integration")


def _flag_count(annotated: list[dict]) -> int:
    """Mirrors app/routers/jobs.py::_flag_count — the single canonical
    definition of "needs human review", kept in sync with production."""
    return sum(1 for q in annotated if (q.get("consistency_score") or 1.0) < 0.90)


async def _run_one(filename: str, file_bytes: bytes) -> dict:
    text, instructions = extract_document(file_bytes, filename)
    file_type = classify_document_type(filename)

    result = await check_with_retry(text, filename)

    consistency = result.get("consistency", {})
    questions = result["normalised_a"].get("questions", [])

    rubric_points = parse_points_per_question(instructions)
    if rubric_points is not None:
        questions = [{**q, "points": rubric_points} for q in questions]

    total_points = sum(q.get("points") or 0 for q in questions)
    per_question = consistency.get("details", {}).get("per_question", [])
    consistent = consistency.get("consistent", False)
    missing_score_default = 1.0 if consistent else 0.0

    annotated = []
    for i, q in enumerate(questions):
        pq = per_question[i] if i < len(per_question) else {}
        q_score = pq.get("score", missing_score_default)
        annotated.append({
            **q,
            "flagged": q_score < 0.75,
            "consistency_score": q_score,
            "conflicts": pq.get("conflicts", {}),
        })

    annotated = validate_questions(annotated)
    for q in annotated:
        if not q["schema_valid"]:
            q["flagged"] = True

    for q in annotated:
        grounding = check_question_grounding(q, text)
        q["grounding_score"] = grounding["grounding_score"]
        q["hallucination_detected"] = grounding["hallucination_detected"]
        q["ungrounded_fields"] = grounding["ungrounded_fields"]
        if grounding["hallucination_detected"]:
            q["flagged"] = True

    consistent = (
        consistency.get("consistent", False)
        and all(q["schema_valid"] for q in annotated)
        and not any(q["hallucination_detected"] for q in annotated)
    )

    return {
        "filename": filename,
        "file_type": file_type,
        "consistent": consistent,
        "consistency_score": consistency.get("score", 0),
        "total_questions": len(annotated),
        "total_points": total_points,
        "attempt": result.get("attempt", 1),
        "flag_count": _flag_count(annotated),
        "model_b_question_count": len(result["normalised_b"].get("questions", [])),
        "model_a_error": result["normalised_a"].get("error"),
        "model_b_error": result["normalised_b"].get("error"),
        "questions": annotated,
    }


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
    total_files = len(docx_files)

    for idx, filename in enumerate(docx_files, start=1):
        docx_path = os.path.join(docx_dir, filename)
        base_name = os.path.splitext(filename)[0]
        out_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")

        print(f"[{idx}/{total_files}] Starting {filename} ...")

        t0 = time.time()
        try:
            with open(docx_path, "rb") as f:
                file_bytes = f.read()

            record = await _run_one(filename, file_bytes)
            elapsed = time.time() - t0

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)

            status = "PASS" if record["consistent"] else "FLAG"
            print(
                f"  {status} {filename} — {record['total_questions']}Q, "
                f"consistency={record['consistency_score']:.4f}, "
                f"flagged={record['flag_count']}, attempt={record['attempt']}, "
                f"{elapsed:.1f}s"
            )
            summary.append({
                "filename": filename,
                "status": status,
                "consistent": record["consistent"],
                "consistency_score": record["consistency_score"],
                "total_questions": record["total_questions"],
                "total_points": record["total_points"],
                "flag_count": record["flag_count"],
                "attempt": record["attempt"],
                "model_a_error": record["model_a_error"],
                "model_b_error": record["model_b_error"],
                "elapsed_sec": round(elapsed, 1),
            })

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR {filename} → {e}")
            summary.append({
                "filename": filename,
                "status": "ERROR",
                "error": str(e),
                "elapsed_sec": round(elapsed, 1),
            })

    summary_path = os.path.join(OUTPUT_DIR, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("-" * 70)
    passed = sum(1 for s in summary if s.get("status") == "PASS")
    flagged = sum(1 for s in summary if s.get("status") == "FLAG")
    errored = sum(1 for s in summary if s.get("status") == "ERROR")
    print(f"Done: {passed} passed, {flagged} flagged, {errored} errored")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    docx_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOCX_DIR
    asyncio.run(main(os.path.abspath(docx_dir)))
