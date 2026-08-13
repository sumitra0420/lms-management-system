"""
Breaks down score_field_accuracy.py's field accuracy by QUESTION TYPE
(multiple_choice / true_false / short_answer) instead of by file — answers
"which type of question is causing the most extraction errors?" rather than
"which field is causing the most errors?" or "which file is worst?".

Type is inferred from ground truth (predictions don't get a vote here,
same principle as field_accuracy — ground truth defines what SHOULD have
been extracted):
    no choices                          -> short_answer
    choices, texts are exactly {true, false} (case-insensitive) -> true_false
    choices, anything else              -> multiple_choice

Reuses the same matching + field-comparison logic as score_field_accuracy.py
(matching.py's greedy text matcher, exact-match field comparison) so a
question's per-field correctness here is identical to what that script
would say about it — this just re-groups the same underlying comparisons.

Run from inside backend/ (after generate_ground_truth.py AND
run_integration_test.py have both been run):
    python tests/score_accuracy_by_type.py integration/result_newprompt_convertfix

Results written to tests/output/test_results/accuracy_by_type/<run>/,
mirroring the run name so different runs never overwrite each other.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.matching import _greedy_match, MATCH_THRESHOLD
from tests.score_field_accuracy import (
    ALL_FIELDS, FIELDS_ALL_TYPES, FIELD_CHOICES, _field_match,
)

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
GT_DIR   = os.path.join(BASE_DIR, "groundtruth")

QUESTION_TYPES = ["multiple_choice", "true_false", "short_answer"]


def _infer_type(gt: dict) -> str:
    choices = gt.get("choices") or []
    if not choices:
        return "short_answer"
    texts = {str(c.get("text", "")).strip().lower() for c in choices}
    if texts == {"true", "false"}:
        return "true_false"
    return "multiple_choice"


def _score_file(gt_record: dict, pred_record: dict, tallies: dict, per_file_counts: dict):
    gt_questions   = gt_record.get("questions", [])
    pred_questions = pred_record.get("questions", [])

    gt_texts   = [q.get("question") or "" for q in gt_questions]
    pred_texts = [q.get("text")     or "" for q in pred_questions]

    matched_pairs, _, _ = _greedy_match(gt_texts, pred_texts, MATCH_THRESHOLD)
    matched_by_gt = {gt_i: pred_j for gt_i, pred_j, _ in matched_pairs}

    for gt_i, gt in enumerate(gt_questions):
        qtype = _infer_type(gt)
        is_mcq = qtype in ("multiple_choice", "true_false")
        fields = FIELDS_ALL_TYPES + ([FIELD_CHOICES] if is_mcq else [])

        pred_j = matched_by_gt.get(gt_i)
        pred = pred_questions[pred_j] if pred_j is not None else {}

        per_file_counts[qtype] = per_file_counts.get(qtype, 0) + 1

        for field in ALL_FIELDS:
            if field not in fields:
                continue
            correct = (pred_j is not None) and _field_match(field, pred, gt)
            tallies[qtype][field]["correct"] += int(correct)
            tallies[qtype][field]["total"]   += 1

        # "matched" itself is a useful signal per type — a question that was
        # never matched to any prediction fails every field trivially, but
        # it's worth also seeing type-level "extraction miss rate" alone.
        tallies[qtype]["_matched"]["correct"] += int(pred_j is not None)
        tallies[qtype]["_matched"]["total"]   += 1


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

    out_dir = os.path.join(BASE_DIR, "accuracy_by_type", run)
    os.makedirs(out_dir, exist_ok=True)

    gt_files = sorted(f for f in os.listdir(GT_DIR) if f.endswith(".json") and not f.startswith("_"))

    tallies = {
        qtype: {f: {"correct": 0, "total": 0} for f in ALL_FIELDS + ["_matched"]}
        for qtype in QUESTION_TYPES
    }
    question_counts = {}
    skipped = 0

    for fname in gt_files:
        pred_path = os.path.join(pred_dir, fname)
        if not os.path.exists(pred_path):
            skipped += 1
            continue
        with open(os.path.join(GT_DIR, fname), encoding="utf-8") as f:
            gt_record = json.load(f)
        with open(pred_path, encoding="utf-8") as f:
            pred_record = json.load(f)
        _score_file(gt_record, pred_record, tallies, question_counts)

    header = f"{'Type':<18} {'Questions':>9} {'Matched':>10} {'Q Text':>9} {'Answer':>9} {'Marks':>9} {'Choices':>9} {'Overall':>9}"
    print(header)
    print("-" * len(header))

    summary_rows = []
    for qtype in QUESTION_TYPES:
        t = tallies[qtype]
        n = question_counts.get(qtype, 0)
        if n == 0:
            continue

        def _acc(field):
            c, tot = t[field]["correct"], t[field]["total"]
            return (c / tot) if tot else float("nan")

        applicable_fields = ALL_FIELDS if qtype in ("multiple_choice", "true_false") else FIELDS_ALL_TYPES
        overall_c = sum(t[f]["correct"] for f in applicable_fields)
        overall_t = sum(t[f]["total"]   for f in applicable_fields)
        overall_acc = overall_c / overall_t if overall_t else float("nan")

        def _fmt(field):
            return f"{_acc(field):.1%}" if t[field]["total"] else "n/a"

        print(
            f"{qtype:<18} {n:>9} {_fmt('_matched'):>10} {_fmt('question_text'):>9} "
            f"{_fmt('correct_answer'):>9} {_fmt('marks'):>9} {_fmt(FIELD_CHOICES):>9} "
            f"{overall_acc:>8.1%}"
        )

        summary_rows.append({
            "question_type":  qtype,
            "question_count": n,
            "matched_pct":    round(_acc("_matched") * 100, 1) if t["_matched"]["total"] else "",
            "question_text_pct": round(_acc("question_text") * 100, 1) if t["question_text"]["total"] else "",
            "correct_answer_pct": round(_acc("correct_answer") * 100, 1) if t["correct_answer"]["total"] else "",
            "marks_pct":      round(_acc("marks") * 100, 1) if t["marks"]["total"] else "",
            "choices_pct":    round(_acc(FIELD_CHOICES) * 100, 1) if t[FIELD_CHOICES]["total"] else "",
            "overall_pct":    round(overall_acc * 100, 1) if overall_t else "",
        })

    if skipped:
        print(f"\n{skipped} file(s) pending — run run_integration_test.py to fill these in.")

    summary_csv_path = os.path.join(out_dir, "_summary.csv")
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "question_type", "question_count", "matched_pct", "question_text_pct",
            "correct_answer_pct", "marks_pct", "choices_pct", "overall_pct",
        ])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"\nOutput: {summary_csv_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests/score_accuracy_by_type.py <run-subfolder>")
        print("e.g.:  python tests/score_accuracy_by_type.py integration/result_newprompt_convertfix")
        sys.exit(1)
    main(sys.argv[1])
