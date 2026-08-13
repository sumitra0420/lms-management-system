"""
Tallies the auto_verdict column from auto_verdict.py's CSVs (TP/FP/TN/FN
per question, with any human_override taking precedence) and plots two or
more runs side by side — e.g. old prompt vs new prompt vs a repeat run —
so you can see whether flagging accuracy actually differs or if it's just
run-to-run API noise.

    TP = pipeline flagged it AND the question genuinely has a problem
    FP = pipeline flagged it BUT the question is actually fine
    TN = pipeline did NOT flag it AND the question is fine
    FN = pipeline did NOT flag it BUT the question actually has a problem

Run from inside backend/ (after auto_verdict.py has produced auto_review.csv
for each run — spot-check/fill human_override first if you want overrides
reflected):
    python tests/plot_flag_results.py integration/result_oldprompt integration/result_newprompt integration/result_newprompt_check

Takes 2 or more run subfolders — not just a pair.

Add --out <filename> anywhere in the arguments to write to a different
filename instead of the default comparison.png, so a new comparison
doesn't overwrite one you already have:
    python tests/plot_flag_results.py integration/result_oldprompt integration/result_newprompt --out comparison_verify_flow.png

Reads:  tests/output/test_results/flag_review/<run>/auto_review.csv
Writes: tests/output/test_results/flag_review/<--out filename, default comparison.png>
"""

import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
FLAG_REVIEW_DIR = os.path.join(BASE_DIR, "flag_review")

VERDICTS = ["TP", "FP", "TN", "FN"]
VERDICT_LABELS = {
    "TP": "Correct Flag (TP)",
    "FP": "False Alarm (FP)",
    "TN": "All Correct (TN)",
    "FN": "System Miss (FN)",
}

# dataviz skill categorical palette, fixed order — one slot per run/series.
# Outcome identity (TP/FP/TN/FN) is carried by x position + labels, not by
# a second color channel. Supports up to 4 runs before this needs folding
# into "Other"/faceting per the skill's series-cap guidance.
RUN_COLORS = ["#2a78d6", "#008300", "#e87ba4", "#eda100"]


def _tally(run: str) -> dict:
    csv_path = os.path.join(FLAG_REVIEW_DIR, run, "auto_review.csv")
    if not os.path.isfile(csv_path):
        print(f"CSV not found: {csv_path}")
        print("Run tests/auto_verdict.py for this run first.")
        sys.exit(1)

    counts = {v: 0 for v in VERDICTS}
    blank = 0
    unrecognised = set()

    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # human_override wins when present — that's your manual
            # correction of a heuristic mistake (e.g. a formatting-only
            # mismatch the auto-verdict misread as a content error).
            verdict = (row.get("human_override") or row.get("auto_verdict") or "").strip().upper()
            if not verdict:
                blank += 1
                continue
            if verdict not in counts:
                unrecognised.add(verdict)
                continue
            counts[verdict] += 1

    if blank:
        print(f"WARNING [{run}]: {blank} row(s) have no verdict — excluded from the tally.")
    if unrecognised:
        print(f"WARNING [{run}]: unrecognised verdict value(s) {sorted(unrecognised)} — excluded. Expected one of {VERDICTS}.")

    return counts


def _metrics(counts: dict) -> dict:
    tp, fp, tn, fn = counts["TP"], counts["FP"], counts["TN"], counts["FN"]
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall    = tp / (tp + fn) if (tp + fn) else float("nan")
    accuracy  = (tp + tn) / total if total else float("nan")
    return {"precision": precision, "recall": recall, "accuracy": accuracy, "total": total}


def _print_summary(label: str, counts: dict):
    m = _metrics(counts)
    print(f"\n{label}")
    print(f"  TP={counts['TP']}  FP={counts['FP']}  TN={counts['TN']}  FN={counts['FN']}  (n={m['total']})")
    print(f"  precision={m['precision']:.3f}  recall={m['recall']:.3f}  accuracy={m['accuracy']:.3f}")


def _plot(runs: list[str], all_counts: list[dict], out_filename: str = "comparison.png"):
    if len(runs) > len(RUN_COLORS):
        print(f"WARNING: {len(runs)} runs but only {len(RUN_COLORS)} palette slots defined — "
              f"add more to RUN_COLORS or this will error.")

    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")

    x = range(len(VERDICTS))
    n = len(runs)
    group_width = 0.8
    bar_width = group_width / n

    for i, (run, counts) in enumerate(zip(runs, all_counts)):
        vals = [counts[v] for v in VERDICTS]
        offset = (i - (n - 1) / 2) * bar_width
        bars = ax.bar(
            [xi + offset for xi in x], vals, bar_width * 0.92,
            label=run, color=RUN_COLORS[i % len(RUN_COLORS)],
        )
        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                str(int(height)),
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=8, color="#0b0b0b",
            )

    ax.set_xticks(list(x))
    ax.set_xticklabels([VERDICT_LABELS[v] for v in VERDICTS], color="#0b0b0b")
    ax.set_ylabel("Question count", color="#52514e")
    ax.set_title("Flagging accuracy — run comparison", color="#0b0b0b", fontsize=12, pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#898781")
    ax.yaxis.grid(True, color="#e1e0d9", linewidth=1)
    ax.set_axisbelow(True)

    # Below the chart, not inside the axes — TN typically dominates and sits
    # near the top of the y-range, so an inside legend collides with it.
    ax.legend(
        frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12),
        ncol=min(len(runs), 3), labelcolor="#0b0b0b", fontsize=8,
    )

    out_path = os.path.join(FLAG_REVIEW_DIR, out_filename)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    print(f"\nChart written to {out_path}")


def main(runs: list[str], out_filename: str = "comparison.png"):
    all_counts = [_tally(run) for run in runs]

    for run, counts in zip(runs, all_counts):
        _print_summary(run, counts)

    _plot(runs, all_counts, out_filename)


if __name__ == "__main__":
    args = sys.argv[1:]
    out_filename = "comparison.png"
    if "--out" in args:
        i = args.index("--out")
        out_filename = args[i + 1]
        args = args[:i] + args[i + 2:]

    if len(args) < 2:
        print("Usage: python tests/plot_flag_results.py <run-1> <run-2> [run-3 ...] [--out filename.png]")
        print("e.g.:  python tests/plot_flag_results.py integration/result_oldprompt integration/result_newprompt integration/result_newprompt_check --out comparison_verify_flow.png")
        sys.exit(1)
    main(args, out_filename)
