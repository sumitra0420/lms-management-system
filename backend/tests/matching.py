"""
Shared question-matching utility — greedy best-match pairing between a
ground-truth question list and a predicted question list by text
similarity, not array index, so a dropped/hallucinated/reordered question
doesn't misalign everything after it.

Used by score_field_accuracy.py and auto_verdict.py to figure out which
predicted question corresponds to which ground-truth question before
comparing their fields/flags. Previously lived in score_question_detection.py
(a standalone TP/FP/FN detection-report script no longer used — see git
history if you need it back), extracted here once that script was removed
so the two remaining dependents didn't lose their shared matching logic.
"""

from difflib import SequenceMatcher

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services.consistency import normalize_quotes

MATCH_THRESHOLD = 0.75


def _sim(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    a = normalize_quotes(a).lower().strip()
    b = normalize_quotes(b).lower().strip()
    # autojunk=False — see consistency.py's _str_sim for why this matters on
    # longer strings (>200 chars) that are near-identical but reformatted.
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _greedy_match(gt_texts: list[str], pred_texts: list[str], threshold: float):
    """
    Greedy best-match pairing between two lists of strings by similarity.
    Returns (matched_pairs, unmatched_gt_indices, unmatched_pred_indices).
    matched_pairs: list of (gt_index, pred_index, similarity)
    """
    candidates = []
    for i, g in enumerate(gt_texts):
        for j, p in enumerate(pred_texts):
            sim = _sim(g, p)
            if sim >= threshold:
                candidates.append((sim, i, j))
    candidates.sort(reverse=True)  # highest similarity first

    matched_gt: set[int] = set()
    matched_pred: set[int] = set()
    matched_pairs: list[tuple[int, int, float]] = []
    for sim, i, j in candidates:
        if i in matched_gt or j in matched_pred:
            continue
        matched_gt.add(i)
        matched_pred.add(j)
        matched_pairs.append((i, j, sim))

    unmatched_gt   = [i for i in range(len(gt_texts))   if i not in matched_gt]
    unmatched_pred = [j for j in range(len(pred_texts)) if j not in matched_pred]
    return matched_pairs, unmatched_gt, unmatched_pred
