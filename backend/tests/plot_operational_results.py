"""
Plots one run's operational metrics (Table 6: Token usage, Extraction time)
as a scatterplot — one dot per document, total tokens on x, extraction time
on y — so you can see whether larger documents take proportionally longer,
or whether time is dominated by something else (retries, network variance).

Run from inside backend/ (after score_operational.py has produced results
for the run):
    python tests/plot_operational_results.py integration/result_claude_claude_260826_1832

Add --out <filename> anywhere in the arguments to write to a different
filename instead of the default scatter_tokens_vs_elapsed.png, so a scatter
from a different run's CSV doesn't overwrite this one:
    python tests/plot_operational_results.py integration/result_claude_nova_main_260827 --out scatter_claude_nova.png

Reads:  tests/output/test_results/operational/<run>/_summary.json  (per_file: [{filename, total_tokens, elapsed_sec}, ...])
Writes: tests/output/test_results/operational/<run>/<--out filename, default scatter_tokens_vs_elapsed.png>
"""

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
OPERATIONAL_DIR = os.path.join(BASE_DIR, "operational")

# dataviz skill categorical palette — single series here, so just its first slot.
DOT_COLOR = "#2a78d6"
SURFACE = "#fcfcfb"


def _load(run: str) -> list[dict]:
    path = os.path.join(OPERATIONAL_DIR, run, "_summary.json")
    if not os.path.isfile(path):
        print(f"Summary not found: {path}")
        print("Run tests/score_operational.py for this run first.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("per_file", [])


def _plot(run: str, rows: list[dict], out_filename: str = "scatter_tokens_vs_elapsed.png"):
    x = [r["total_tokens"] for r in rows]
    y = [r["elapsed_sec"] for r in rows]

    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    # marker >=8px (r>=4pt) with a 2px surface ring so overlapping dots stay legible.
    ax.scatter(
        x, y, s=64, color=DOT_COLOR,
        edgecolors=SURFACE, linewidths=1.5, zorder=3,
    )

    ax.set_xlabel("Total tokens", color="#52514e")
    ax.set_ylabel("Extraction time (s)", color="#52514e")
    ax.set_title("Operational metrics — Tokens vs Extraction Time", color="#0b0b0b", fontsize=12, pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#898781")
    ax.xaxis.grid(True, color="#e1e0d9", linewidth=1)
    ax.yaxis.grid(True, color="#e1e0d9", linewidth=1)
    ax.set_axisbelow(True)

    out_dir = os.path.join(OPERATIONAL_DIR, run)
    out_path = os.path.join(out_dir, out_filename)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    print(f"\nChart written to {out_path}")


def main(run: str, out_filename: str = "scatter_tokens_vs_elapsed.png"):
    rows = _load(run)
    if not rows:
        print(f"No per-file rows found for run {run!r}")
        sys.exit(1)

    print(f"{run}: {len(rows)} document(s)")
    _plot(run, rows, out_filename)


if __name__ == "__main__":
    args = sys.argv[1:]
    out_filename = "scatter_tokens_vs_elapsed.png"
    if "--out" in args:
        i = args.index("--out")
        out_filename = args[i + 1]
        args = args[:i] + args[i + 2:]

    if len(args) != 1:
        print("Usage: python tests/plot_operational_results.py <run> [--out filename.png]")
        print("e.g.:  python tests/plot_operational_results.py integration/result_claude_nova_main_260827 --out scatter_claude_nova.png")
        sys.exit(1)
    main(args[0], out_filename)
