"""
Count validation — the fast, aggregate-level sanity check before the more
expensive similarity-matching Information Retrieval scorer.

Compares FILE-LEVEL TOTALS only (no per-question matching):
    tests/output/test_results/groundtruth/  (hand-reviewed answer key)
    tests/output/test_results/integration/  (full production pipeline output)

For each file, checks whether these totals agree:
    total_questions        — all question types
    total_marks            — sum of mark/points across all questions
    total_choices           MCQ only
    total_correct_answers   MCQ only
    total_answers           short_answer only

This mirrors the same idea as consistency.py's Model-A-vs-B count_score
(n / max(count_a, count_b)), just applied between ground truth and the
integration pipeline's output instead of between the two models.

It does NOT tell you which question was missed or hallucinated — a
count match can still hide a wrong question being swapped for another.
Use score_information_retrieval.py for that deeper, matched analysis.

Run from inside backend/ (after generate_ground_truth.py AND
run_integration_test.py have both been run):
    python tests/score_count_validation.py

Or score a specific run — e.g. after testing a different model pair with
run_integration_test.py's output-subfolder argument — by passing the same
subfolder path (relative to tests/output/test_results/):
    python tests/score_count_validation.py integration/result_llama_mistral_270726_1430

Results are written to tests/output/test_results/count_validation/<run>/,
mirroring the run name, so scores from different model pairs never overwrite
each other.
"""

import csv
import json
import os
import sys

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
GT_DIR   = os.path.join(BASE_DIR, "groundtruth")
DEFAULT_RUN = "integration/result_claude_nova_260726_0811"


def _pred_totals(pred_record: dict) -> dict:
    """
    Recomputes the same total_* metrics on the prediction side, filtered by
    each question's own predicted type — this stays correct even when a
    file has a mix of multiple_choice and short_answer questions (the
    misclassification bug this whole eval effort started from).
    """
    questions = pred_record.get("questions", [])
    mcq_qs = [q for q in questions if q.get("type") == "multiple_choice"]
    sa_qs  = [q for q in questions if q.get("type") == "short_answer"]

    return {
        "total_questions": len(questions),
        "total_marks": sum(q.get("points") or 0 for q in questions),
        "total_choices": sum(len(q.get("choices") or []) for q in mcq_qs),
        "total_correct_answers": sum(
            sum(1 for c in (q.get("choices") or []) if c.get("correct"))
            for q in mcq_qs
        ),
        "total_answers": sum(
            1 for q in sa_qs if (q.get("correct_answer") or "").strip()
        ),
    }


def _compare_file(gt_record: dict, pred_record: dict) -> dict:
    pred_totals = _pred_totals(pred_record)

    fields = ["total_questions", "total_marks", "total_choices", "total_correct_answers", "total_answers"]
    comparisons = {}
    for field in fields:
        if field not in gt_record:
            continue  # metric doesn't apply to this file's question type mix
        gt_val = gt_record[field]
        pred_val = pred_totals[field]
        comparisons[field] = {
            "ground_truth": gt_val,
            "predicted": pred_val,
            "match": gt_val == pred_val,
            "diff": pred_val - gt_val,
        }
    return comparisons


def main(run: str = DEFAULT_RUN):
    pred_dir   = os.path.join(BASE_DIR, run)
    output_dir = os.path.join(BASE_DIR, "count_validation", run)

    if not os.path.isdir(GT_DIR):
        print(f"Ground truth folder not found: {GT_DIR}")
        print("Run tests/generate_ground_truth.py first.")
        sys.exit(1)
    if not os.path.isdir(pred_dir):
        print(f"Integration test folder not found: {pred_dir}")
        print("Run tests/run_integration_test.py first.")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    gt_files = sorted(
        f for f in os.listdir(GT_DIR)
        if f.endswith(".json") and not f.startswith("_")
    )

    if not gt_files:
        print(f"No ground truth files found in {GT_DIR}")
        return

    fields = ["total_questions", "total_marks", "total_choices", "total_correct_answers", "total_answers"]
    field_match_counts = {f: 0 for f in fields}
    field_total_counts = {f: 0 for f in fields}
    summary = []
    skipped = 0

    header = f"{'File':<55} {'Field':<24} {'GT':>6} {'Pred':>6} {'Match':>6}"
    print(header)
    print("-" * len(header))

    for fname in gt_files:
        gt_path   = os.path.join(GT_DIR, fname)
        pred_path = os.path.join(pred_dir, fname)

        if not os.path.exists(pred_path):
            print(f"  PENDING {fname} — no integration result yet")
            skipped += 1
            continue

        with open(gt_path, encoding="utf-8") as f:
            gt_record = json.load(f)
        with open(pred_path, encoding="utf-8") as f:
            pred_record = json.load(f)

        comparisons = _compare_file(gt_record, pred_record)

        out_path = os.path.join(output_dir, fname)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"filename": fname, "comparisons": comparisons}, f, indent=2, ensure_ascii=False)

        all_match = all(c["match"] for c in comparisons.values())
        first = True
        for field, c in comparisons.items():
            field_total_counts[field] += 1
            if c["match"]:
                field_match_counts[field] += 1
            mark = "OK" if c["match"] else "MISMATCH"
            fname_col = fname[:55] if first else ""
            print(f"{fname_col:<55} {field:<24} {c['ground_truth']:>6} {c['predicted']:>6} {mark:>6}")
            first = False

        summary.append({
            "filename": fname,
            "all_match": all_match,
            "comparisons": comparisons,
        })

    print("-" * len(header))
    print("Field-level agreement across all files:")
    for field in fields:
        total = field_total_counts[field]
        if total == 0:
            continue
        matched = field_match_counts[field]
        print(f"  {field:<24} {matched}/{total} files match ({matched / total:.1%})")

    if skipped:
        print(f"\n{skipped} file(s) pending — run run_integration_test.py to fill these in.")

    summary_path = os.path.join(output_dir, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "per_file": summary,
            "field_agreement": {
                field: {"matched": field_match_counts[field], "total": field_total_counts[field]}
                for field in fields if field_total_counts[field] > 0
            },
        }, f, indent=2, ensure_ascii=False)

    # Flat CSV — one row per (file, field) comparison, for pasting straight
    # into a report/spreadsheet instead of parsing the nested JSON above.
    csv_path = os.path.join(output_dir, "_summary.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "field", "ground_truth", "predicted", "match", "diff"])
        for row in summary:
            for field, c in row["comparisons"].items():
                writer.writerow([row["filename"], field, c["ground_truth"], c["predicted"], c["match"], c["diff"]])
        writer.writerow([])
        writer.writerow(["field", "matched", "total", "agreement_pct"])
        for field in fields:
            total = field_total_counts[field]
            if total == 0:
                continue
            matched = field_match_counts[field]
            writer.writerow([field, matched, total, round(matched / total * 100, 1)])

    print(f"\nOutput: {output_dir}")
    print(f"CSV:    {csv_path}")


if __name__ == "__main__":
    run = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RUN
    main(run)
