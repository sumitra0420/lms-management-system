"""
Breaks down auto_verdict.py's TP/FP/TN/FN counts by QUESTION TYPE
(multiple_choice / true_false / short_answer) — answers "which type of
question is responsible for false alarms (FP) / missed problems (FN)?"
rather than plot_flag_results.py's whole-run totals.

Type comes straight from each row's own "type" column in auto_review.csv
(the model's predicted type for that question) — no re-matching or
re-scoring, just a group-by over data auto_verdict.py already produced.
Rows with no predicted type (a ground-truth question that was never
extracted at all — always verdict FN) are grouped under "missing".

Run from inside backend/ (after auto_verdict.py has produced
auto_review.csv for the run):
    python tests/score_flag_by_type.py integration/result_newprompt_convertfix

Reads:  tests/output/test_results/flag_review/<run>/auto_review.csv
Writes: tests/output/test_results/flag_by_type/<run>/_summary.csv
"""

import csv
import os
import sys

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
VERDICTS = ["TP", "FP", "TN", "FN"]


def main(run: str):
    in_path = os.path.join(BASE_DIR, "flag_review", run, "auto_review.csv")
    if not os.path.isfile(in_path):
        print(f"auto_review.csv not found: {in_path}")
        print("Run tests/auto_verdict.py for this run first.")
        sys.exit(1)

    counts: dict[str, dict[str, int]] = {}
    with open(in_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            qtype = row.get("type") or "missing"
            verdict = row.get("auto_verdict") or ""
            if verdict not in VERDICTS:
                continue
            counts.setdefault(qtype, {v: 0 for v in VERDICTS})
            counts[qtype][verdict] += 1

    header = f"{'Type':<18} {'TP':>6} {'FP':>6} {'TN':>6} {'FN':>6} {'Total':>7} {'FP rate':>9}"
    print(header)
    print("-" * len(header))

    out_dir = os.path.join(BASE_DIR, "flag_by_type", run)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "_summary.csv")

    rows_out = []
    for qtype in sorted(counts, key=lambda t: (t == "missing", t)):
        c = counts[qtype]
        total = sum(c.values())
        fp_rate = c["FP"] / total if total else float("nan")
        print(f"{qtype:<18} {c['TP']:>6} {c['FP']:>6} {c['TN']:>6} {c['FN']:>6} {total:>7} {fp_rate:>8.1%}")
        rows_out.append({
            "question_type": qtype,
            "TP": c["TP"], "FP": c["FP"], "TN": c["TN"], "FN": c["FN"],
            "total": total,
            "fp_rate_pct": round(fp_rate * 100, 1) if total else "",
        })

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["question_type", "TP", "FP", "TN", "FN", "total", "fp_rate_pct"])
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\nOutput: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests/score_flag_by_type.py <run-subfolder>")
        print("e.g.:  python tests/score_flag_by_type.py integration/result_newprompt_convertfix")
        sys.exit(1)
    main(sys.argv[1])
