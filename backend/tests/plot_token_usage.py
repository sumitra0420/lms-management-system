"""
Plots token_usage_probe.py's per-branch token totals — grand total tokens
per method (summed across every file probed for that branch label), split
input vs output so the composition is visible too (output tokens are
typically priced several times higher than input tokens on Bedrock, so two
methods with similar totals can still have very different real cost).

Run from inside backend/ (after token_usage_probe.py has been run for each
method you want to compare — they all append to the same comparison.csv,
grouped by whatever <branch_label> you passed it):
    python tests/plot_token_usage.py claudenova_main claudenova_verifyflow claudeclaude_verifyflow

Add --out <filename> anywhere in the arguments to write to a different
filename instead of the default comparison.png:
    python tests/plot_token_usage.py claudenova_main claudenova_verifyflow claudeclaude_verifyflow --out comparison_token_usage.png

Reads:  tests/output/test_results/token_usage/comparison.csv
Writes: tests/output/test_results/token_usage/<--out filename, default comparison.png>
"""

import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results", "token_usage")
CSV_PATH = os.path.join(BASE_DIR, "comparison.csv")

# Same fixed palette/order as the other plot_*.py scripts, reused here for
# the "input" bar of each method; output uses a lighter tint of the same hue.
RUN_COLORS       = ["#2a78d6", "#008300", "#e87ba4", "#eda100"]
RUN_COLORS_LIGHT = ["#a9c8ef", "#a3d1a3", "#f3cddf", "#f6d9a3"]


def _load(branch_labels: list) -> dict:
    if not os.path.isfile(CSV_PATH):
        print(f"Not found: {CSV_PATH}")
        print("Run tests/token_usage_probe.py for at least one method first.")
        sys.exit(1)

    totals = {b: {"input": 0, "output": 0, "files": 0} for b in branch_labels}
    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            b = row.get("branch")
            if b not in totals:
                continue
            totals[b]["input"]  += int(row["grand_total_input"])
            totals[b]["output"] += int(row["grand_total_output"])
            totals[b]["files"]  += 1

    missing = [b for b, t in totals.items() if t["files"] == 0]
    if missing:
        print(f"WARNING: no rows found for branch label(s): {missing} — check the label matches what you passed to token_usage_probe.py.")

    return totals


def _plot(branch_labels: list, totals: dict, out_filename: str):
    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")

    x = range(len(branch_labels))
    bar_width = 0.55

    inputs  = [totals[b]["input"]  for b in branch_labels]
    outputs = [totals[b]["output"] for b in branch_labels]

    input_bars  = ax.bar(x, inputs, bar_width, label="Input tokens",
                          color=[RUN_COLORS[i % len(RUN_COLORS)] for i in range(len(branch_labels))])
    output_bars = ax.bar(x, outputs, bar_width, bottom=inputs, label="Output tokens",
                          color=[RUN_COLORS_LIGHT[i % len(RUN_COLORS_LIGHT)] for i in range(len(branch_labels))])

    for i, b in enumerate(branch_labels):
        total = inputs[i] + outputs[i]
        ax.annotate(
            f"{total:,}",
            xy=(i, total),
            xytext=(0, 4), textcoords="offset points",
            ha="center", va="bottom", fontsize=9, color="#0b0b0b", fontweight="bold",
        )

    ax.set_xticks(list(x))
    ax.set_xticklabels(branch_labels, color="#0b0b0b")
    ax.set_ylabel("Tokens", color="#52514e")
    ax.set_title("Token Usage — total per method (all files probed)", color="#0b0b0b", fontsize=12, pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#898781")
    ax.yaxis.grid(True, color="#e1e0d9", linewidth=1)
    ax.set_axisbelow(True)

    ax.legend(
        frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12),
        ncol=2, labelcolor="#0b0b0b", fontsize=8,
    )

    out_path = os.path.join(BASE_DIR, out_filename)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    print(f"\nChart written to {out_path}")


def main(branch_labels: list, out_filename: str):
    totals = _load(branch_labels)

    for b in branch_labels:
        t = totals[b]
        total = t["input"] + t["output"]
        print(f"{b:<24} files={t['files']:<4} input={t['input']:>9,} output={t['output']:>9,} total={total:>9,}")

    _plot(branch_labels, totals, out_filename)


if __name__ == "__main__":
    args = sys.argv[1:]

    out_filename = "comparison.png"
    if "--out" in args:
        i = args.index("--out")
        out_filename = args[i + 1]
        args = args[:i] + args[i + 2:]

    if len(args) < 1:
        print("Usage: python tests/plot_token_usage.py <branch-1> [branch-2 ...] [--out filename.png]")
        print("e.g.:  python tests/plot_token_usage.py claudenova_main claudenova_verifyflow claudeclaude_verifyflow")
        sys.exit(1)

    main(args, out_filename)
