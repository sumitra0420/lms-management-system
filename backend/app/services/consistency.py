import logging
import os
import asyncio
from difflib import SequenceMatcher

from app.services.extractor import extract

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
CONSISTENCY_THRESHOLD = float(os.getenv("CONSISTENCY_THRESHOLD", "0.85"))

# Per-field similarity thresholds below which A and B are considered "in
# conflict" on that specific field — surfaced to the UI so a human can pick
# which model's value to keep, instead of silently defaulting to Model A.
FIELD_CONFLICT_THRESHOLDS = {
    "text":           0.90,
    "correct_answer": 0.90,
    "choices":        0.85,
    "feedback":       0.80,
}


def _build_retry_hint(consistency: dict) -> str:
    details   = consistency.get("details", {})
    per_q     = details.get("per_question", [])
    count_a   = details.get("count_a", 0)
    count_b   = details.get("count_b", 0)

    issues = []

    # Question count is the top-priority signal — a miscount means whole
    # questions are missing or wrongly merged, which no per-field fix can
    # repair. Always call this out first and make it non-negotiable.
    count_mismatch = count_a != count_b
    if count_mismatch:
        issues.append(
            f"- QUESTION COUNT MISMATCH (highest priority): one pass found {count_a} "
            f"questions, the other found {count_b}. Before anything else, recount every "
            "numbered question in the source text one at a time. Do not merge multi-part "
            "questions into one, and do not skip any — every numbered item must produce "
            "exactly one question object."
        )

    if per_q:
        avg_text   = sum(q["text_similarity"]   for q in per_q) / len(per_q)
        avg_answer = sum(q["answer_similarity"]  for q in per_q) / len(per_q)
        avg_choices= sum(q["choices_similarity"] for q in per_q) / len(per_q)
        type_mismatches   = sum(1 for q in per_q if q["type_match"]   == 0)

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

# Curly/smart quotes normalized to their straight equivalents before any
# text comparison — one model outputting ' ' " " and the other ' ' " "
# for the exact same content is a typography choice, not a disagreement.
_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'",  # ' '
    "“": '"', "”": '"',  # " "
})


def normalize_quotes(s: str) -> str:
    return (s or "").translate(_QUOTE_MAP)


def _str_sim(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    a = normalize_quotes(a).lower().strip()
    b = normalize_quotes(b).lower().strip()
    # autojunk=False — SequenceMatcher's default autojunk heuristic can crater
    # the ratio on longer strings (>200 chars) that are otherwise near-identical
    # (e.g. the same answer reformatted with different separators/punctuation),
    # since it deprioritizes any character appearing in >1% of the string.
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


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

    # Points is excluded from scoring/conflicts entirely: it's either
    # overridden deterministically from the instructions block's rubric
    # statement, or left as a single model's un-invented value — neither
    # case is an A-vs-B disagreement worth scoring or flagging for review.
    score = (
        text_sim     * 0.35 +
        answer_sim   * 0.35 +
        choices_sim  * 0.15 +
        type_match   * 0.10 +
        feedback_sim * 0.05
    )

    # Field-level conflicts: fields where A and B disagree enough that a
    # human should pick between them, rather than silently keeping A's value.
    conflicts = {}
    field_sims = {
        "text":           text_sim,
        "correct_answer": answer_sim,
        "choices":        choices_sim,
        "feedback":       feedback_sim,
    }
    for field, sim in field_sims.items():
        if sim < FIELD_CONFLICT_THRESHOLDS[field]:
            conflicts[field] = {"value_a": qa.get(field), "value_b": qb.get(field)}
    if type_match == 0:
        conflicts["type"] = {"value_a": qa.get("type"), "value_b": qb.get("type")}

    return {
        "text_similarity":    round(text_sim,     4),
        "answer_similarity":  round(answer_sim,   4),
        "choices_similarity": round(choices_sim,  4),
        "type_match":         type_match,
        "feedback_similarity":round(feedback_sim, 4),
        "score":              round(score,         4),
        "conflicts":          conflicts,
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

    # 30% question count agreement + 70% content agreement
    final_score = count_score * 0.3 + avg_q_score * 0.7

    # Question count is a hard gate, not just a weighted-in signal: a high
    # per-question score can't compensate for whole missing/extra questions,
    # since a good average over a mismatched, index-paired subset can mask a
    # real miscount (see _build_retry_hint). Any mismatch forces a retry
    # instead of silently passing on a partial comparison.
    consistent = (final_score >= CONSISTENCY_THRESHOLD) and (count_a == count_b)

    return {
        "score":      round(final_score, 4),
        "consistent": consistent,
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

async def check_with_retry(text: str, filename: str = "") -> dict:
    last_result      = None
    last_consistency = None
    # Track the attempt that produced the best per-question score data.
    # When later retries fail (e.g. Model B returns malformed JSON), we still
    # want the per-question scores from the best successful attempt so the UI
    # can show meaningful individual scores instead of defaulting to 1.0.
    best_result_with_data: dict | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt == 1 or last_consistency is None:
            extract_text = text
        else:
            extract_text = text + _build_retry_hint(last_consistency)

        result = await extract(extract_text, filename)
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
            f"[Consistency] [{filename}] Attempt {attempt}/{MAX_RETRIES} — "
            f"score={consistency['score']} consistent={consistency['consistent']} "
            f"(A:{details['count_a']} Qs, B:{details['count_b']} Qs, "
            f"count_score={details.get('count_score', 'n/a')}, "
            f"avg_q_score={details.get('avg_question_score', 'n/a')})"
        )
        for i, q in enumerate(details.get("per_question", [])):
            logger.debug(
                f"  Q{i+1}: score={q['score']:.4f} | "
                f"text={q['text_similarity']:.4f} answer={q['answer_similarity']:.4f} "
                f"type={q['type_match']}"
            )

        # Keep track of the best attempt that has real per-question scores
        if details.get("per_question"):
            prev_best_score = (
                best_result_with_data["consistency"]["score"]
                if best_result_with_data else -1
            )
            if consistency["score"] > prev_best_score:
                best_result_with_data = result

        if consistency["consistent"]:
            logger.info(f"[Consistency] [{filename}] PASSED on attempt {attempt}")
            return result

        if attempt < MAX_RETRIES:
            logger.info(
                f"[Consistency] [{filename}] Score {consistency['score']} below threshold "
                f"{CONSISTENCY_THRESHOLD}, retrying..."
            )

    # All retries exhausted without passing.
    if last_result and "consistency" not in last_result:
        # Last attempt had an extraction error — no consistency was computed.
        # Borrow the best per-question details from a previous attempt so the
        # UI can display meaningful individual question scores.
        borrowed_details = (
            best_result_with_data["consistency"]["details"]
            if best_result_with_data else {}
        )
        borrowed_score = (
            best_result_with_data["consistency"]["score"]
            if best_result_with_data else 0.0
        )
        last_result["consistency"] = {
            "score":              borrowed_score,
            "consistent":         False,
            "max_retries_reached": True,
            "details":            borrowed_details,
        }
        if best_result_with_data:
            logger.info(
                f"[Consistency] Borrowed per-question scores from best attempt "
                f"(score={borrowed_score}) for final failure result"
            )
    else:
        last_result["consistency"]["max_retries_reached"] = True

    return last_result
