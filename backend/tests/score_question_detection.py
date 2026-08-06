"""
Detection-level metrics: did the pipeline find the real questions?

Compares:
    tests/output/test_results/groundtruth/  (hand-reviewed answer key)
    tests/output/test_results/integration/  (full production pipeline output)

Unlike score_count_validation.py (which only checks whether the TOTAL
count matches), this scores question detection quality directly:

    Precision = TP / (TP + FP)   — of what was predicted, how much was real
    Recall    = TP / (TP + FN)   — of what's real, how much was found
    F1        = harmonic mean of the two

    TP = a predicted question matched to a real ground-truth question
    FP = a predicted question that matched nothing real (hallucinated/duplicate)
    FN = a ground-truth question that matched no prediction (missed)

Why this matters even when raw counts match: a model can miss one real
question AND hallucinate one extra question in the same document — the
total count comes out identical (looks "100% correct" by count alone)
while two individual questions are actually wrong. Precision/Recall/F1
via matching catches this; a raw count comparison cannot.

Matching is by greedy best-match TEXT SIMILARITY (difflib SequenceMatcher),
not array index — this stays correct even when a question is dropped,
merged, or inserted, which would otherwise misalign every question after it.

Run from inside backend/ (after generate_ground_truth.py AND
run_integration_test.py have both been run):
    python tests/score_question_detection.py

Or score a specific run — e.g. after testing a different model pair with
run_integration_test.py's output-subfolder argument — by passing the same
subfolder path (relative to tests/output/test_results/):
    python tests/score_question_detection.py integration/result_llama_mistral_270726_1430

Results are written to tests/output/test_results/question_detection/<run>/,
mirroring the run name, so scores from different model pairs never overwrite
each other.
"""

import json
import os
import sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services.consistency import normalize_quotes

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
GT_DIR   = os.path.join(BASE_DIR, "groundtruth")
DEFAULT_RUN = "integration/result_claude_nova_260726_0811"

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


def _prf1(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall    = tp / (tp + fn) if (tp + fn) else 1.0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall":    round(recall, 4),
        "f1":        round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
    }


def _score_file(gt_record: dict, pred_record: dict) -> dict:
    gt_questions   = gt_record.get("questions", [])
    pred_questions = pred_record.get("questions", [])

    gt_texts   = [q.get("question") or "" for q in gt_questions]
    pred_texts = [q.get("text")     or "" for q in pred_questions]

    matched_pairs, unmatched_gt, unmatched_pred = _greedy_match(gt_texts, pred_texts, MATCH_THRESHOLD)

    metrics = _prf1(tp=len(matched_pairs), fp=len(unmatched_pred), fn=len(unmatched_gt))

    return {
        "count_gt":          len(gt_questions),
        "count_pred":        len(pred_questions),
        "count_matches":     len(gt_questions) == len(pred_questions),
        "metrics":           metrics,
        "missed_questions":  [gt_questions[i].get("id")   for i in unmatched_gt],
        "extra_questions":   [pred_questions[j].get("id") for j in unmatched_pred],
    }


def main(run: str = DEFAULT_RUN):
    pred_dir   = os.path.join(BASE_DIR, run)
    output_dir = os.path.join(BASE_DIR, "question_detection", run)

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

    summary = []
    agg_tp = agg_fp = agg_fn = 0
    count_exact_matches = 0
    skipped = 0

    header = f"{'File':<55} {'GT#':>4} {'Pred#':>5} {'CountOK':>8} {'Prec':>6} {'Recall':>7} {'F1':>6}"
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

        result = _score_file(gt_record, pred_record)

        out_path = os.path.join(output_dir, fname)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        m = result["metrics"]
        agg_tp += m["tp"]; agg_fp += m["fp"]; agg_fn += m["fn"]
        if result["count_matches"]:
            count_exact_matches += 1

        count_ok = "yes" if result["count_matches"] else "NO"
        print(
            f"{fname[:55]:<55} {result['count_gt']:>4} {result['count_pred']:>5} {count_ok:>8} "
            f"{m['precision']:>6.2f} {m['recall']:>7.2f} {m['f1']:>6.2f}"
        )

        summary.append({"filename": fname, **result})

    print("-" * len(header))
    overall = _prf1(agg_tp, agg_fp, agg_fn)
    total_files = len(summary)
    count_acc = count_exact_matches / total_files if total_files else 0.0

    print(f"Question count accuracy (exact count match): {count_exact_matches}/{total_files} ({count_acc:.1%})")
    print(
        f"Question detection (micro-average over all files): "
        f"Precision={overall['precision']:.4f}  Recall={overall['recall']:.4f}  F1={overall['f1']:.4f}  "
        f"(TP={overall['tp']} FP={overall['fp']} FN={overall['fn']})"
    )

    if skipped:
        print(f"\n{skipped} file(s) pending — run run_integration_test.py to fill these in.")

    summary_path = os.path.join(output_dir, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "per_file": summary,
            "question_count_accuracy": {
                "exact_matches": count_exact_matches,
                "total_files": total_files,
                "accuracy": round(count_acc, 4),
            },
            "overall_detection_metrics": overall,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nOutput: {output_dir}")


if __name__ == "__main__":
    run = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RUN
    main(run)
