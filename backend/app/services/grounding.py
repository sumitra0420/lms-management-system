"""
Hallucination detection — verifies that each extracted question's text
fields actually appear in the source document, rather than being invented
by the AI.

This is independent of and complementary to the Model A vs Model B
consistency score: two models could agree with each other while both
still fabricating content that isn't present in the source text at all.
"""

import re

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
})

# Short/common words are excluded from the fallback word-coverage check —
# they're present almost everywhere and wouldn't meaningfully signal
# whether a field's actual content is grounded in the source.
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "are",
    "that", "this", "with", "as", "by", "be", "it", "at", "from", "was", "were",
})

GROUNDING_THRESHOLD = 0.80


def _normalize(text: str) -> str:
    text = text.translate(_QUOTE_MAP).lower()
    return re.sub(r"\s+", " ", text).strip()


def _word_coverage(field_value: str, normalized_source: str) -> float:
    """
    Fraction of the field's significant words that appear somewhere in the
    source text. Fallback used when the field isn't found verbatim (e.g.
    the model lightly reworded or reordered otherwise-faithful content).
    """
    words = [
        w for w in re.findall(r"[a-z0-9']+", _normalize(field_value))
        if w not in _STOPWORDS and len(w) > 2
    ]
    if not words:
        return 1.0
    found = sum(1 for w in words if w in normalized_source)
    return found / len(words)


def _field_grounding(field_value: str, normalized_source: str) -> float:
    value = (field_value or "").strip()
    if not value:
        return 1.0
    normalized_value = _normalize(value)
    if normalized_value in normalized_source:
        return 1.0
    return _word_coverage(value, normalized_source)


def check_question_grounding(question: dict, raw_text: str) -> dict:
    """
    Check whether a question's text fields (question text, each answer-key
    bullet, choice text, feedback) are grounded in the source document.

    Returns:
        {
          "grounding_score": 0.0-1.0,     # average across all checked fields
          "hallucination_detected": bool, # grounding_score below threshold
          "ungrounded_fields": [...],     # which fields/bullets failed
        }
    """
    normalized_source = _normalize(raw_text)
    field_scores: dict[str, float] = {}

    field_scores["text"] = _field_grounding(question.get("text", ""), normalized_source)

    answer_bullets = [b for b in (question.get("correct_answer") or "").split(" | ") if b.strip()]
    for i, bullet in enumerate(answer_bullets):
        field_scores[f"correct_answer[{i}]"] = _field_grounding(bullet, normalized_source)

    for i, choice in enumerate(question.get("choices") or []):
        field_scores[f"choices[{i}].text"] = _field_grounding(choice.get("text", ""), normalized_source)

    feedback = question.get("feedback", "")
    if feedback and feedback.strip():
        field_scores["feedback"] = _field_grounding(feedback, normalized_source)

    if not field_scores:
        return {"grounding_score": 1.0, "hallucination_detected": False, "ungrounded_fields": []}

    grounding_score = sum(field_scores.values()) / len(field_scores)
    ungrounded_fields = [f for f, s in field_scores.items() if s < GROUNDING_THRESHOLD]

    return {
        "grounding_score":        round(grounding_score, 4),
        "hallucination_detected": grounding_score < GROUNDING_THRESHOLD,
        "ungrounded_fields":      ungrounded_fields,
    }
