"""
Extract-then-verify pipeline: Model A (Claude) extracts, Model B (Nova)
checks A's output against the source text and reports any problems it
finds. On failure, Model A retries from scratch up to MAX_RETRIES times
— but each retry is a plain, unmodified re-extraction of the original
source text, NEVER a "fix this" instruction built from Model B's
complaint. The best-scoring attempt across all tries is kept, not
necessarily the last one, since a blind retry has no reason to be an
improvement over an earlier attempt.

This replaces an earlier design (see git history) that folded Model B's
complaints into the retry prompt as a correction instruction. That
assumed Model B's complaints were reliable enough to guide a fix — in
practice, even in this narrower verification role, Model B still
produces a meaningful rate of hallucinated complaints (confirmed case:
Q19 of "SITHFAB023 Knowledge Test 1" was CORRECT on the first pass, but
a false complaint from Model B got fed back as a retry instruction, and
Model A obediently changed the correct answer into a wrong one to
satisfy it). Under this design, a false complaint can cost a wasted
retry — it can no longer corrupt an answer that was already right.
"""

import logging

from app.services.extractor import extract_a_only, verify_extraction

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


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


async def extract_and_verify(text: str, filename: str = "") -> dict:
    """
    Runs Model A, then Model B to check it. On failure, retries Model A
    up to MAX_RETRIES times — always re-extracting the same, unmodified
    source text, never a version adjusted with Model B's complaint.
    Returns the best-scoring attempt seen (or the first one that passes,
    returned immediately without using the remaining retry budget).

    Returns:
        {
          "normalised_a": {...},
          "attempt": <int>,
          "verification": {"score", "verified", "details": {...}},
        }
    """
    best_result: dict | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        result = await extract_a_only(text, filename)
        result["attempt"] = attempt

        if result["normalised_a"].get("error"):
            # A technical failure (malformed/truncated JSON), not a content
            # judgment call — nothing to verify this attempt.
            logger.warning(
                f"[Verification] [{filename}] Attempt {attempt}/{MAX_RETRIES} extraction "
                f"error, skipping verify: {result['normalised_a'].get('error')}"
            )
            if best_result is None:
                result["verification"] = {"score": 0.0, "verified": False, "details": {}}
                best_result = result
            continue

        verification_raw = await verify_extraction(text, result["normalised_a"], filename)
        verification = _to_result_shape(verification_raw, result["normalised_a"])
        result["verification"] = verification

        logger.info(
            f"[Verification] [{filename}] Attempt {attempt}/{MAX_RETRIES} — "
            f"score={verification['score']} verified={verification['verified']} "
            f"(source_count={verification['details'].get('source_question_count')}, "
            f"candidate_count={verification['details'].get('candidate_question_count')})"
        )

        if best_result is None or verification["score"] > best_result["verification"]["score"]:
            best_result = result

        if verification["verified"]:
            logger.info(f"[Verification] [{filename}] PASSED on attempt {attempt}")
            return result

        if attempt < MAX_RETRIES:
            logger.info(
                f"[Verification] [{filename}] Failed on attempt {attempt} "
                f"(score={verification['score']}), retrying (fresh attempt, no hint)..."
            )

    best_result["verification"]["max_retries_reached"] = True
    logger.info(
        f"[Verification] [{filename}] Exhausted {MAX_RETRIES} attempts — "
        f"keeping best attempt {best_result['attempt']} "
        f"(score={best_result['verification']['score']})"
    )
    return best_result


if __name__ == "__main__":
    # Standalone smoke test for the extract-then-verify pair. Usage:
    #   python -m app.services.verification "tests/input/Quiz/<some file>.docx"
    import asyncio
    import json
    import logging as _logging
    import os
    import sys

    from app.services.converter import extract_document

    # Without this, only WARNING+ messages print (Python's default last-resort
    # handler) — the INFO logs from extractor.py/verification.py (question
    # count, verification score) are silently dropped.
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")

    path = sys.argv[1] if len(sys.argv) > 1 else "tests/input/Quiz/SITHCCC029_Knowledge_Test_ShortAnswer.docx"
    with open(path, "rb") as f:
        file_bytes = f.read()
    doc_text, _ = extract_document(file_bytes, path)

    async def _run():
        result = await extract_and_verify(doc_text, path)
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
