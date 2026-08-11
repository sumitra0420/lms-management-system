"""
Generic text/field similarity helpers.

Not used by the production extraction pipeline anymore (see verification.py
— Model A's output is now checked against source text by Model B directly,
not diffed against an independent second extraction). Kept here because the
eval scripts under tests/ (score_field_accuracy.py, auto_verdict.py,
matching.py) still use these to diff extracted JSON against ground truth.
"""

from difflib import SequenceMatcher

# Curly/smart quotes normalized to their straight equivalents before any
# text comparison — one source outputting ' ' " " and the other ' ' " "
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


# Per-field similarity thresholds below which two field values are considered
# "in conflict" — used by the eval scripts to decide when a predicted field
# differs enough from ground truth to report as a mismatch.
FIELD_CONFLICT_THRESHOLDS = {
    "text":           0.90,
    "correct_answer": 0.90,
    "choices":        0.85,
    "feedback":       0.80,
}
