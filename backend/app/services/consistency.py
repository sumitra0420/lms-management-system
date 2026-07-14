import logging
import os
import asyncio
from difflib import SequenceMatcher

from app.services.extractor import extract

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
CONSISTENCY_THRESHOLD = float(os.getenv("CONSISTENCY_THRESHOLD", "0.85"))


def _build_retry_hint(consistency: dict) -> str:
    details   = consistency.get("details", {})
    per_q     = details.get("per_question", [])
    count_a   = details.get("count_a", 0)
    count_b   = details.get("count_b", 0)

    issues = []

    # Count mismatch (weighted 20% of final score)
    if count_a != count_b:
        issues.append(
            f"- QUESTION COUNT MISMATCH: one model found {count_a} questions, "
            f"the other found {count_b}. Count every numbered question separately — "
            "do not merge multi-part questions and do not skip any."
        )

    if per_q:
        avg_text   = sum(q["text_similarity"]   for q in per_q) / len(per_q)
        avg_answer = sum(q["answer_similarity"]  for q in per_q) / len(per_q)
        avg_choices= sum(q["choices_similarity"] for q in per_q) / len(per_q)
        type_mismatches   = sum(1 for q in per_q if q["type_match"]   == 0)
        points_mismatches = sum(1 for q in per_q if q["points_match"] == 0)

        if avg_answer < 0.80:
            issues.append(
                f"- LOW ANSWER SIMILARITY ({avg_answer:.2f}): Copy the ASSESSOR KEY / model "
                "answer text VERBATIM. Do not paraphrase, summarise, or shorten it."
            )
        if avg_text < 0.80:
            issues.append(
                f"- LOW QUESTION TEXT SIMILARITY ({avg_text:.2f}): Extract the COMPLETE "
                "question text exactly as written — do not truncate, rephrase, or omit "
                "any part of the question."
            )
        if avg_choices < 0.75:
            issues.append(
                f"- LOW CHOICES SIMILARITY ({avg_choices:.2f}): For multiple-choice questions "
                "include ALL answer options exactly as listed (A, B, C, D). Mark the correct "
                "option with \"correct\": true."
            )
        if type_mismatches > 0:
            issues.append(
                f"- QUESTION TYPE MISMATCH ({type_mismatches} question(s)): Use "
                "\"multiple_choice\" only when labelled options (A/B/C/D) are present, "
                "otherwise use \"short_answer\"."
            )
        if points_mismatches > 0:
            issues.append(
                f"- POINTS MISMATCH ({points_mismatches} question(s)): Read the marks/points "
                "stated next to each question carefully and use the exact number."
            )

    if not issues:
        issues.append("- Re-read every question carefully and ensure nothing is skipped or merged.")

    hint_body = "\n".join(issues)
    return (
        f"\n\nIMPORTANT — previous extraction had consistency issues. Fix these specific problems:\n"
        f"{hint_body}\n"
        "Re-extract ALL questions from scratch with these corrections applied."
    )


# ---------------------------------------------------------------------------
# Field-level similarity helpers
# ---------------------------------------------------------------------------

def _str_sim(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _choices_sim(ca: list, cb: list) -> float:
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0
    n = min(len(ca), len(cb))
    count_score = n / max(len(ca), len(cb))
    text_scores = [
        _str_sim(ca[i].get("text", ""), cb[i].get("text", ""))
        for i in range(n)
    ]
    return count_score * 0.3 + (sum(text_scores) / n) * 0.7


# ---------------------------------------------------------------------------
# Per-question and overall scoring
# ---------------------------------------------------------------------------

def _score_pair(qa: dict, qb: dict) -> dict:
    text_sim     = _str_sim(qa.get("text", ""),           qb.get("text", ""))
    answer_sim   = _str_sim(qa.get("correct_answer", ""), qb.get("correct_answer", ""))
    feedback_sim = _str_sim(qa.get("feedback", ""),       qb.get("feedback", ""))
    choices_sim  = _choices_sim(qa.get("choices", []),    qb.get("choices", []))
    type_match   = 1.0 if qa.get("type")   == qb.get("type")   else 0.0
    points_match = 1.0 if qa.get("points") == qb.get("points") else 0.0

    score = (
        text_sim     * 0.30 +
        answer_sim   * 0.35 +
        choices_sim  * 0.15 +
        type_match   * 0.10 +
        points_match * 0.05 +
        feedback_sim * 0.05
    )

    return {
        "text_similarity":    round(text_sim,     4),
        "answer_similarity":  round(answer_sim,   4),
        "choices_similarity": round(choices_sim,  4),
        "type_match":         type_match,
        "points_match":       points_match,
        "feedback_similarity":round(feedback_sim, 4),
        "score":              round(score,         4),
    }


def score_consistency(normalised_a: dict, normalised_b: dict) -> dict:
    qs_a = normalised_a.get("questions", [])
    qs_b = normalised_b.get("questions", [])
    count_a, count_b = len(qs_a), len(qs_b)
    n = min(count_a, count_b)

    count_score = (n / max(count_a, count_b)) if max(count_a, count_b) > 0 else 0.0

    if n == 0:
        return {
            "score": 0.0,
            "consistent": False,
            "threshold": CONSISTENCY_THRESHOLD,
            "details": {"count_a": count_a, "count_b": count_b, "per_question": []},
        }

    per_question = [_score_pair(qs_a[i], qs_b[i]) for i in range(n)]
    avg_q_score  = sum(q["score"] for q in per_question) / n

    # 20% question count agreement + 80% content agreement
    final_score = count_score * 0.2 + avg_q_score * 0.8

    return {
        "score":      round(final_score, 4),
        "consistent": final_score >= CONSISTENCY_THRESHOLD,
        "threshold":  CONSISTENCY_THRESHOLD,
        "details": {
            "count_a":            count_a,
            "count_b":            count_b,
            "count_score":        round(count_score, 4),
            "avg_question_score": round(avg_q_score,  4),
            "per_question":       per_question,
        },
    }


# ---------------------------------------------------------------------------
# Public API — extraction + consistency with retry
# ---------------------------------------------------------------------------

async def check_with_retry(text: str) -> dict:
    last_result  = None
    last_consistency = None

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt == 1 or last_consistency is None:
            extract_text = text
        else:
            extract_text = text + _build_retry_hint(last_consistency)

        result = await extract(extract_text)
        last_result = result

        err_a = result["normalised_a"].get("error")
        err_b = result["normalised_b"].get("error")
        if err_a or err_b:
            if attempt < MAX_RETRIES:
                continue
            break

        consistency = score_consistency(result["normalised_a"], result["normalised_b"])
        result["consistency"] = consistency
        result["attempt"]     = attempt
        last_consistency      = consistency

        details = consistency["details"]
        logger.info(
            f"[Consistency] Attempt {attempt}/{MAX_RETRIES} — "
            f"score={consistency['score']} consistent={consistency['consistent']} "
            f"(A:{details['count_a']} Qs, B:{details['count_b']} Qs, "
            f"count_score={details.get('count_score', 'n/a')}, "
            f"avg_q_score={details.get('avg_question_score', 'n/a')})"
        )
        for i, q in enumerate(details.get("per_question", [])):
            logger.debug(
                f"  Q{i+1}: score={q['score']:.4f} | "
                f"text={q['text_similarity']:.4f} answer={q['answer_similarity']:.4f} "
                f"type={q['type_match']} points={q['points_match']}"
            )

        if consistency["consistent"]:
            logger.info(f"[Consistency] PASSED on attempt {attempt}")
            return result

        if attempt < MAX_RETRIES:
            logger.info(
                f"[Consistency] Score {consistency['score']} below threshold "
                f"{CONSISTENCY_THRESHOLD}, retrying..."
            )

    if last_result and "consistency" not in last_result:
        last_result["consistency"] = {"score": 0.0, "consistent": False,
                                      "max_retries_reached": True}
    else:
        last_result["consistency"]["max_retries_reached"] = True

    return last_result
