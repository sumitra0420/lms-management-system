"""
Auto-fills the human_verdict column that export_flag_review.py leaves blank,
by comparing each predicted question against the hand-reviewed ground truth
instead of requiring you to check every row by hand.

Reuses two pieces of logic that already exist elsewhere rather than
reinventing them:
  - question-level matching: the same greedy text-similarity matcher
    matching.py provides (MATCH_THRESHOLD=0.75) to pair a
    predicted question with its ground-truth counterpart.
  - field-level comparison: consistency.py's own _str_sim/_choices_sim and
    FIELD_CONFLICT_THRESHOLDS (0.90 answer text, 0.85 choices) — the same
    bar the pipeline already holds Model A vs Model B to, now applied to
    prediction vs ground truth instead.

Verdict logic (standard confusion-matrix definitions):
    content correct    + flagged=True   -> FP (false alarm)
    content correct    + flagged=False  -> TN (correctly quiet)
    content has a problem + flagged=True   -> TP (correctly caught)
    content has a problem + flagged=False  -> FN (missed)

Three ways a question can "have a problem":
  - matched to ground truth, but answer/choices/text diverge past threshold
  - a ground-truth question with NO matching prediction at all (dropped —
    there's no row to check "flagged" on, so this is always FN: a real
    problem that was never even surfaced for anyone to flag)
  - a predicted question with NO matching ground truth (hallucinated) —
    TP if flagged, FN if not

CAVEAT: ground truth here is a single Model-A pass (see
generate_ground_truth.py), meant to be hand-corrected. If you haven't
corrected it yet, this only catches disagreement with that original run,
not errors Model A itself made from the start. Spot-check the auto_verdict
column, especially rows with low match_similarity — use the human_override
column to correct any the heuristic got wrong.

Run from inside backend/ (after generate_ground_truth.py AND
run_integration_test.py have both been run):
    python tests/auto_verdict.py integration/result_oldprompt
    python tests/auto_verdict.py integration/result_newprompt_check

Output: tests/output/test_results/flag_review/<run>/auto_review.csv
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.consistency import _str_sim, _choices_sim, FIELD_CONFLICT_THRESHOLDS
from tests.matching import _greedy_match, MATCH_THRESHOLD
from tests.export_flag_review import _flag_reasons, _format_conflicts

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
GT_DIR   = os.path.join(BASE_DIR, "groundtruth")

ANSWER_THRESHOLD  = FIELD_CONFLICT_THRESHOLDS["correct_answer"]  # 0.90
CHOICES_THRESHOLD = FIELD_CONFLICT_THRESHOLDS["choices"]         # 0.85


def _format_choices(choices: list) -> str:
    return " | ".join(
        f"[correct] {c.get('text', '')}" if c.get("correct") else c.get("text", "")
        for c in (choices or [])
    )


def _gt_answer(gt: dict) -> str:
    # MCQ ground truth uses "correct_answer", short-answer uses "answer"
    return gt.get("correct_answer") if gt.get("correct_answer") is not None else (gt.get("answer") or "")


def _content_issues(pred: dict, gt: dict) -> list[str]:
    issues = []
    answer_sim = _str_sim(pred.get("correct_answer") or "", _gt_answer(gt))
    if answer_sim < ANSWER_THRESHOLD:
        issues.append(f"answer_mismatch({answer_sim:.2f})")

    pred_choices = pred.get("choices") or []
    gt_choices   = gt.get("choices") or []
    if pred_choices or gt_choices:
        choices_sim = _choices_sim(pred_choices, gt_choices)
        if choices_sim < CHOICES_THRESHOLD:
            issues.append(f"choices_mismatch({choices_sim:.2f})")

    return issues


def _score_file(gt_record: dict, pred_record: dict) -> list[dict]:
    gt_questions   = gt_record.get("questions", [])
    pred_questions = pred_record.get("questions", [])

    gt_texts   = [q.get("question") or "" for q in gt_questions]
    pred_texts = [q.get("text")     or "" for q in pred_questions]

    matched_pairs, unmatched_gt, unmatched_pred = _greedy_match(gt_texts, pred_texts, MATCH_THRESHOLD)

    rows = []

    for gt_i, pred_j, sim in matched_pairs:
        gt = gt_questions[gt_i]
        pred = pred_questions[pred_j]
        issues = _content_issues(pred, gt)
        flagged = bool(pred.get("flagged"))
        content_ok = not issues

        if content_ok and flagged:
            verdict = "FP"
        elif content_ok and not flagged:
            verdict = "TN"
        elif not content_ok and flagged:
            verdict = "TP"
        else:
            verdict = "FN"

        model_a_value, model_b_value = _format_conflicts(pred)
        rows.append({
            "filename":          pred_record.get("filename", ""),
            "question_id":       pred.get("id"),
            "gt_question_id":    gt.get("id"),
            "match_similarity":  round(sim, 3),
            "type":              pred.get("type"),
            "question_text":     pred.get("text"),
            "correct_answer":    pred.get("correct_answer"),
            "choices":           _format_choices(pred.get("choices")),
            "flagged":           flagged,
            "flag_reasons":      _flag_reasons(pred),
            "consistency_score": pred.get("consistency_score"),
            "grounding_score":   pred.get("grounding_score"),
            "conflict_fields":   ", ".join((pred.get("conflicts") or {}).keys()),
            "model_a_value":     model_a_value,
            "model_b_value":     model_b_value,
            "content_issues":    "+".join(issues),
            "auto_verdict":      verdict,
            "human_override":    "",
        })

    for gt_i in unmatched_gt:
        gt = gt_questions[gt_i]
        rows.append({
            "filename":          pred_record.get("filename", ""),
            "question_id":       "",
            "gt_question_id":    gt.get("id"),
            "match_similarity":  0,
            "type":              "",
            "question_text":     gt.get("question"),
            "correct_answer":    "",
            "choices":           "",
            "flagged":           False,
            "flag_reasons":      "",
            "consistency_score": "",
            "grounding_score":   "",
            "conflict_fields":   "",
            "model_a_value":     "",
            "model_b_value":     "",
            "content_issues":    "missing_from_extraction",
            "auto_verdict":      "FN",  # a real problem (dropped question) that nothing ever flagged
            "human_override":    "",
        })

    for pred_j in unmatched_pred:
        pred = pred_questions[pred_j]
        flagged = bool(pred.get("flagged"))
        model_a_value, model_b_value = _format_conflicts(pred)
        rows.append({
            "filename":          pred_record.get("filename", ""),
            "question_id":       pred.get("id"),
            "gt_question_id":    "",
            "match_similarity":  0,
            "type":              pred.get("type"),
            "question_text":     pred.get("text"),
            "correct_answer":    pred.get("correct_answer"),
            "choices":           _format_choices(pred.get("choices")),
            "flagged":           flagged,
            "flag_reasons":      _flag_reasons(pred),
            "consistency_score": pred.get("consistency_score"),
            "grounding_score":   pred.get("grounding_score"),
            "conflict_fields":   ", ".join((pred.get("conflicts") or {}).keys()),
            "model_a_value":     model_a_value,
            "model_b_value":     model_b_value,
            "content_issues":    "no_ground_truth_match(hallucinated)",
            "auto_verdict":      "TP" if flagged else "FN",
            "human_override":    "",
        })

    return rows


def main(run: str):
    pred_dir = os.path.join(BASE_DIR, run)
    if not os.path.isdir(GT_DIR):
        print(f"Ground truth folder not found: {GT_DIR}")
        print("Run tests/generate_ground_truth.py first.")
        sys.exit(1)
    if not os.path.isdir(pred_dir):
        print(f"Integration test folder not found: {pred_dir}")
        print("Run tests/run_integration_test.py first.")
        sys.exit(1)

    out_dir = os.path.join(BASE_DIR, "flag_review", run)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "auto_review.csv")

    gt_files = sorted(
        f for f in os.listdir(GT_DIR)
        if f.endswith(".json") and not f.startswith("_")
    )

    all_rows = []
    skipped = 0
    for fname in gt_files:
        pred_path = os.path.join(pred_dir, fname)
        if not os.path.exists(pred_path):
            print(f"  PENDING {fname} — no prediction for this run yet")
            skipped += 1
            continue
        with open(os.path.join(GT_DIR, fname), encoding="utf-8") as f:
            gt_record = json.load(f)
        with open(pred_path, encoding="utf-8") as f:
            pred_record = json.load(f)
        all_rows.extend(_score_file(gt_record, pred_record))

    if not all_rows:
        print("No rows generated.")
        return

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    counts = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    for r in all_rows:
        counts[r["auto_verdict"]] += 1

    print(f"Wrote {len(all_rows)} rows to {out_path}")
    print(f"TP={counts['TP']}  FP={counts['FP']}  TN={counts['TN']}  FN={counts['FN']}")
    print("Spot-check rows with low match_similarity or non-empty content_issues, "
          "fill human_override to correct any the heuristic got wrong.")
    if skipped:
        print(f"\n{skipped} file(s) skipped — no prediction found for this run.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests/auto_verdict.py <run-subfolder>")
        print("e.g.:  python tests/auto_verdict.py integration/result_oldprompt")
        sys.exit(1)
    main(sys.argv[1])
