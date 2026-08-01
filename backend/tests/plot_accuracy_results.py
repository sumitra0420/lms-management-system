"""
Plots Extraction Performance accuracy across two or more runs — Section 1
(count validation, file-level totals) and Section 2 (field-level accuracy,
per-question fields) of the testing plan. Both share one chart shape
deliberately: Accuracy% on the y-axis, one group of bars per field, one
bar per run within each group — the same visual language as
plot_flag_results.py (Section 3, Review/Flag Performance), so the whole
report reads as one system instead of three unrelated charts.

Run from inside backend/ (after score_count_validation.py or
score_field_accuracy.py have produced results for each run):
    python tests/plot_accuracy_results.py count_validation integration/result_1 integration/result_2 integration/result_3
    python tests/plot_accuracy_results.py field_accuracy integration/result_1 integration/result_2 integration/result_3

Reads:
    count_validation: tests/output/test_results/count_validation/<run>/_summary.json  (field_agreement: {field: {matched, total}})
    field_accuracy:    tests/output/test_results/field_accuracy/<run>/_summary.json     (fields: {field: {correct, total}})

Writes: tests/output/test_results/<metric>/comparison.png
"""

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")

# dataviz skill categorical palette, fixed order — one slot per run/result.
RUN_COLORS = ["#2a78d6", "#008300", "#e87ba4", "#eda100"]

METRIC_CONFIG = {
    "count_validation": {
        "summary_subdir": "count_validation",
        "dict_key":       "field_agreement",
        "numerator_key":  "matched",
        "field_order":    ["total_questions", "total_marks", "total_choices", "total_correct_answers", "total_answers"],
        "field_labels": {
            "total_questions":       "Questions",
            "total_marks":           "Marks",
            "total_choices":         "Choices",
            "total_correct_answers": "Correct Answers",
            "total_answers":         "Answers",
        },
        "title": "Extraction Performance — Count Validation",
    },
    "field_accuracy": {
        "summary_subdir": "field_accuracy",
        "dict_key":       "fields",
        "numerator_key":  "correct",
        "field_order":    ["question_text", "correct_answer", "marks", "choices"],
        "field_labels": {
            "question_text":  "Question",
            "correct_answer": "Answer",
            "marks":          "Mark",
            "choices":        "Choices",
        },
        "title": "Extraction Performance — Field-Level Accuracy",
    },
}


def _load(metric: str, run: str) -> dict:
    cfg = METRIC_CONFIG[metric]
    path = os.path.join(BASE_DIR, cfg["summary_subdir"], run, "_summary.json")
    if not os.path.isfile(path):
        print(f"Summary not found: {path}")
        print(f"Run tests/score_{metric}.py for this run first.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(cfg["dict_key"], {})


def _accuracy(field_data: dict, numerator_key: str) -> float:
    total = field_data.get("total", 0)
    if not total:
        return float("nan")
    return field_data.get(numerator_key, 0) / total


def _plot(metric: str, runs: list, all_data: list):
    cfg = METRIC_CONFIG[metric]
    fields = [f for f in cfg["field_order"] if any(f in d for d in all_data)]
    labels = [cfg["field_labels"].get(f, f) for f in fields]

    if len(runs) > len(RUN_COLORS):
        print(f"WARNING: {len(runs)} runs but only {len(RUN_COLORS)} palette slots defined.")

    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")

    x = range(len(fields))
    n = len(runs)
    group_width = 0.8
    bar_width = group_width / n

    all_vals = [[_accuracy(data.get(f, {}), cfg["numerator_key"]) * 100 for f in fields] for data in all_data]

    for i, (run, vals) in enumerate(zip(runs, all_vals)):
        offset = (i - (n - 1) / 2) * bar_width
        ax.bar(
            [xi + offset for xi in x], vals, bar_width * 0.92,
            label=run, color=RUN_COLORS[i % len(RUN_COLORS)],
        )

    # Selective direct labels: when every run has the same value for a
    # field, repeating "100.0%" once per bar just collides — label that
    # group once, centered, instead. Only label per-bar where runs
    # actually differ, so the label draws attention to real variation.
    for f_idx in range(len(fields)):
        col = [vals[f_idx] for vals in all_vals if vals[f_idx] == vals[f_idx]]  # drop nan
        if not col:
            continue
        uniform = (max(col) - min(col)) < 0.05
        if uniform:
            ax.annotate(
                f"{col[0]:.1f}%",
                xy=(x[f_idx], max(col)),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=8, color="#0b0b0b",
            )
        else:
            for i in range(n):
                val = all_vals[i][f_idx]
                if val != val:
                    continue
                offset = (i - (n - 1) / 2) * bar_width
                ax.annotate(
                    f"{val:.1f}%",
                    xy=(x[f_idx] + offset, val),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=8, color="#0b0b0b",
                )

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, color="#0b0b0b")
    ax.set_ylabel("Accuracy (%)", color="#52514e")
    ax.set_ylim(0, 109)
    ax.set_title(cfg["title"], color="#0b0b0b", fontsize=12, pad=12)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#898781")
    ax.yaxis.grid(True, color="#e1e0d9", linewidth=1)
    ax.set_axisbelow(True)

    # Below the chart, not inside the axes — values cluster near 100% here,
    # so an inside legend collides with bars/labels on whichever group is
    # tallest (see git history for the in-axes version that did this).
    ax.legend(
        frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12),
        ncol=min(len(runs), 3), labelcolor="#0b0b0b", fontsize=8,
    )

    out_dir = os.path.join(BASE_DIR, cfg["summary_subdir"])
    out_path = os.path.join(out_dir, "comparison.png")
    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight")
    print(f"\nChart written to {out_path}")


def main(metric: str, runs: list):
    if metric not in METRIC_CONFIG:
        print(f"Unknown metric {metric!r} — expected one of {list(METRIC_CONFIG)}")
        sys.exit(1)

    cfg = METRIC_CONFIG[metric]
    all_data = [_load(metric, run) for run in runs]

    for run, data in zip(runs, all_data):
        print(f"\n{run}")
        for field in cfg["field_order"]:
            if field not in data:
                continue
            acc = _accuracy(data[field], cfg["numerator_key"])
            num = data[field].get(cfg["numerator_key"], 0)
            total = data[field].get("total", 0)
            print(f"  {cfg['field_labels'].get(field, field):<16} {acc:.1%}  ({num}/{total})")

    _plot(metric, runs, all_data)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python tests/plot_accuracy_results.py <count_validation|field_accuracy> <run-1> <run-2> [run-3 ...]")
        print("e.g.:  python tests/plot_accuracy_results.py field_accuracy integration/result_1 integration/result_2 integration/result_3")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2:])
