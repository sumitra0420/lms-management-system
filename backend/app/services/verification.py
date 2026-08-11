"""
Extract-then-verify pipeline: Model A (Claude) extracts, Model B (Nova)
checks A's output against the source text and reports specific problems,
and on failure we retry Model A's extraction with those problems folded
into the prompt — up to MAX_RETRIES times.

Replaces the old "extract independently with both models, diff their
outputs" approach (see git history for consistency.py): that treated any
A/B disagreement as 50/50 uncertain, even when B was simply wrong on an
easier-to-verify task than full extraction (e.g. misclassifying an MCQ as
short_answer with no choices at all). Verification is a narrower job than
extraction, so B's weaker raw accuracy matters less here.
"""

import logging

from app.services.extractor import extract_a_only, verify_extraction

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def _build_retry_hint(verification: dict) -> str:
    issues     = verification.get("issues", [])
    src_count  = verification.get("source_question_count")
    cand_count = verification.get("candidate_question_count")

    lines = []

    # Question count is the top-priority signal — a miscount means whole
    # questions are missing or wrongly merged, which no per-field fix can
    # repair. Always call this out first and make it non-negotiable.
    count_mismatch = src_count is not None and cand_count is not None and src_count != cand_count
    if count_mismatch:
        lines.append(
            f"- QUESTION COUNT MISMATCH (highest priority): the source document has "
            f"{src_count} questions, your extraction had {cand_count}. Before anything else, "
            "recount every numbered question in the source text one at a time. Do not merge "
            "multi-part questions into one, and do not skip any — every numbered item must "
            "produce exactly one question object."
        )

    for issue in issues:
        qid     = issue.get("question_id") or "unknown question"
        field   = issue.get("field") or ""
        problem = issue.get("problem") or ""
        field_part = f" ({field})" if field else ""
        lines.append(f"- {qid}{field_part}: {problem}")

    if not lines:
        lines.append("- Re-read every question carefully and ensure nothing is skipped or merged.")

    hint_body = "\n".join(lines)
    return (
        f"\n\nIMPORTANT — a verification pass found problems with your previous extraction. "
        f"Fix these specific issues:\n"
        f"{hint_body}\n"
        "Re-extract ALL questions from scratch with these corrections applied."
    )


def _to_result_shape(verification: dict, normalised_a: dict) -> dict:
    """
    Maps Model B's verification report onto normalised_a's questions (by
    "id", e.g. "Q5"), so callers can flag individual questions the same way
    they used to flag low-agreement ones under the old A/B diff.
    """
    questions  = normalised_a.get("questions", [])
    total      = len(questions)
    issues     = verification.get("issues", [])
    src_count  = verification.get("source_question_count")
    cand_count = verification.get("candidate_question_count")

    per_question = []
    for q in questions:
        qid = q.get("id", "")
        q_issues = [
            {"field": i.get("field", ""), "problem": i.get("problem", "")}
            for i in issues if i.get("question_id") == qid
        ]
        per_question.append({
            "question_id": qid,
            "score":       0.0 if q_issues else 1.0,
            "issues":      q_issues,
        })

    count_mismatch = src_count is not None and cand_count is not None and src_count != cand_count
    num_flagged    = sum(1 for pq in per_question if pq["issues"])
    score          = 0.0 if (count_mismatch or total == 0) else round(1 - num_flagged / total, 4)
    verified       = bool(verification.get("valid", False)) and not count_mismatch

    return {
        "score":    score,
        "verified": verified,
        "details": {
            "source_question_count":    src_count,
            "candidate_question_count": cand_count,
            "per_question":             per_question,
            "issues":                   issues,  # raw, unmapped — includes count-mismatch-only issues
        },
    }


async def check_with_retry(text: str, filename: str = "") -> dict:
    """
    Runs the extract → verify → retry loop and returns:
        {
          "normalised_a": {...},
          "attempt": <int>,
          "verification": {"score", "verified", "details": {...}},
        }
    """
    last_result           = None
    last_verification_raw = None
    # Track the attempt with the best verification score, so if later
    # retries fail outright (e.g. malformed JSON), we still have meaningful
    # per-question data to show instead of defaulting to all-flagged.
    best_result_with_data: dict | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt == 1 or last_verification_raw is None:
            extract_text = text
        else:
            extract_text = text + _build_retry_hint(last_verification_raw)

        result = await extract_a_only(extract_text, filename)
        last_result = result

        if result["normalised_a"].get("error"):
            if attempt < MAX_RETRIES:
                continue
            break

        verification_raw      = await verify_extraction(text, result["normalised_a"], filename)
        last_verification_raw = verification_raw

        verification         = _to_result_shape(verification_raw, result["normalised_a"])
        result["verification"] = verification
        result["attempt"]      = attempt

        logger.info(
            f"[Verification] [{filename}] Attempt {attempt}/{MAX_RETRIES} — "
            f"score={verification['score']} verified={verification['verified']} "
            f"(source_count={verification['details']['source_question_count']}, "
            f"candidate_count={verification['details']['candidate_question_count']})"
        )

        prev_best_score = (
            best_result_with_data["verification"]["score"]
            if best_result_with_data else -1
        )
        if verification["score"] > prev_best_score:
            best_result_with_data = result

        if verification["verified"]:
            logger.info(f"[Verification] [{filename}] PASSED on attempt {attempt}")
            return result

        if attempt < MAX_RETRIES:
            logger.info(
                f"[Verification] [{filename}] Failed on attempt {attempt} "
                f"(score={verification['score']}), retrying..."
            )

    # All retries exhausted without passing.
    if last_result and "verification" not in last_result:
        # Last attempt had an extraction error — no verification was computed.
        borrowed = (
            best_result_with_data["verification"]
            if best_result_with_data
            else {"score": 0.0, "verified": False, "details": {}}
        )
        last_result["verification"] = {**borrowed, "max_retries_reached": True}
    else:
        last_result["verification"]["max_retries_reached"] = True

    return last_result


if __name__ == "__main__":
    # Standalone smoke test for the full extract → verify → retry loop.
    # Usage:
    #   python -m app.services.verification "tests/input/Quiz/<some file>.docx"
    import asyncio
    import json
    import logging as _logging
    import os
    import sys

    from app.services.converter import extract_document

    # Without this, only WARNING+ messages print (Python's default last-resort
    # handler) — the per-attempt INFO logs from extractor.py/verification.py
    # (each attempt's question count and score) are silently dropped.
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")

    path = sys.argv[1] if len(sys.argv) > 1 else "tests/input/Quiz/SITHCCC029_Knowledge_Test_ShortAnswer.docx"
    with open(path, "rb") as f:
        file_bytes = f.read()
    doc_text, _ = extract_document(file_bytes, path)

    async def _run():
        result = await check_with_retry(doc_text, path)
        questions = result["normalised_a"].get("questions", [])
        print(f"\nAttempt {result.get('attempt')} — {len(questions)} questions")
        print(json.dumps(result["verification"], indent=2))

        # Full result — including raw_a (Model A's unparsed response text,
        # useful for inspecting exactly where/why a JSON parse error happened)
        # and normalised_a — written to a file instead of only the terminal.
        out_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "tests", "output", "verification_smoke"))
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nFull result (incl. raw_a, normalised_a) written to: {out_path}")

    asyncio.run(_run())
