import os
import asyncio
from difflib import SequenceMatcher

from app.services.extractor import extract

MAX_RETRIES = 3
CONSISTENCY_THRESHOLD = float(os.getenv("CONSISTENCY_THRESHOLD", "0.85"))

RETRY_HINT = (
    "\n\nIMPORTANT: Be thorough and precise. "
    "Extract EVERY question exactly as written. "
    "Do not skip any question or merge questions together."
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
    last_result = None

    for attempt in range(1, MAX_RETRIES + 1):
        extract_text = text if attempt == 1 else text + RETRY_HINT
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

        if consistency["consistent"]:
            return result

        if attempt < MAX_RETRIES:
            print(f"  Attempt {attempt}/{MAX_RETRIES} — score {consistency['score']} "
                  f"below threshold {CONSISTENCY_THRESHOLD}, retrying...")

    if last_result and "consistency" not in last_result:
        last_result["consistency"] = {"score": 0.0, "consistent": False,
                                      "max_retries_reached": True}
    else:
        last_result["consistency"]["max_retries_reached"] = True

    return last_result
