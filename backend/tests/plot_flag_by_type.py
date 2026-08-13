"""
Plots score_flag_by_type.py's per-question-type TP/FP/TN/FN counts across
two or more runs — same visual language as plot_flag_results.py /
plot_accuracy_results.py (grouped bars, one color per run).

Run from inside backend/ (after score_flag_by_type.py has produced
results for each run):
    python tests/plot_flag_by_type.py integration/result_oldprompt_convertfix integration/result_newprompt_convertfix

Plots FP count by default (the usual question: "which type causes false
alarms?"). Use --metric to plot a different column instead:
    python tests/plot_flag_by_type.py integration/result_oldprompt_convertfix integration/result_newprompt_convertfix --metric FN

Add --out <filename> anywhere in the arguments to write to a different
filename instead of the default comparison.png:
    python tests/plot_flag_by_type.py integration/result_oldprompt_convertfix integration/result_newprompt_convertfix --out comparison_fp_by_type.png

Reads:  tests/output/test_results/flag_by_type/<run>/_summary.csv
Writes: tests/output/test_results/flag_by_type/<--out filename, default comparison.png>
"""

import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results", "flag_by_type")
METRICS  = ["TP", "FP", "TN", "FN"]

# Same fixed palette/order as plot_accuracy_results.py and plot_flag_results.py.
RUN_COLORS = ["#2a78d6", "#008300", "#e87ba4", "#eda100"]


def _load(run: str, metric: str) -> dict:
    path = os.path.join(BASE_DIR, run, "_summary.csv")
    if not os.path.isfile(path):
        print(f"Summary not found: {path}")
        print(f"Run tests/score_flag_by_type.py {run} first.")
        sys.exit(1)
    values = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            values[row["question_type"]] = int(row[metric])
    return values


def _plot(runs: list, all_data: list, metric: str, out_filename: str):
    types = sorted({t for d in all_data for t in d}, key=lambda t: (t == "missing", t))
    if not types:
        print("No question types with data found across the given runs.")
        sys.exit(1)

    if len(runs) > len(RUN_COLORS):
        print(f"WARNING: {len(runs)} runs but only {len(RUN_COLORS)} palette slots defined.")

    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")

    x = range(len(types))
    n = len(runs)
    group_width = 0.8
    bar_width = group_width / n

    for i, (run, data) in enumerate(zip(runs, all_data)):
        vals = [data.get(t, 0) for t in types]
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
    ax.set_xticklabels([t.replace("_", " ").title() for t in types], color="#0b0b0b")
    ax.set_ylabel("Question count", color="#52514e")
    ax.set_title(f"Flagging accuracy — {metric} by Question Type", color="#0b0b0b", fontsize=12, pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#898781")
    ax.yaxis.grid(True, color="#e1e0d9", linewidth=1)
    ax.set_axisbelow(True)

    ax.legend(
        frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12),
        ncol=min(len(runs), 3), labelcolor="#0b0b0b", fontsize=8,
    )

    out_path = os.path.join(BASE_DIR, out_filename)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    print(f"\nChart written to {out_path}")


def main(runs: list, metric: str, out_filename: str):
    all_data = [_load(run, metric) for run in runs]

    for run, data in zip(runs, all_data):
        print(f"\n{run}")
        for t, v in data.items():
            print(f"  {t:<16} {v}")

    _plot(runs, all_data, metric, out_filename)


if __name__ == "__main__":
    args = sys.argv[1:]

    metric = "FP"
    if "--metric" in args:
        i = args.index("--metric")
        metric = args[i + 1]
        args = args[:i] + args[i + 2:]

    out_filename = "comparison.png"
    if "--out" in args:
        i = args.index("--out")
        out_filename = args[i + 1]
        args = args[:i] + args[i + 2:]

    if len(args) < 2:
        print("Usage: python tests/plot_flag_by_type.py <run-1> <run-2> [run-3 ...] [--metric TP|FP|TN|FN] [--out filename.png]")
        print("e.g.:  python tests/plot_flag_by_type.py integration/result_oldprompt_convertfix integration/result_newprompt_convertfix --metric FP")
        sys.exit(1)
    if metric not in METRICS:
        print(f"Unknown metric {metric!r} — expected one of {METRICS}")
        sys.exit(1)

    main(args, metric, out_filename)
