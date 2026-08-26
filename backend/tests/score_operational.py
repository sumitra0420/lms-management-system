"""
Operational metrics — axis 3 of the testing plan (Table 6: Token usage,
Extraction time), the "how much did this cost / how long did it take"
companion to score_count_validation.py (Table 7) and score_field_accuracy.py
(Table 9): those two measure correctness, this one measures cost.

No ground truth needed — every number here comes straight from what
run_integration_test.py already recorded per file (tokens.model_a_*,
tokens.model_b_*, elapsed_sec), which in turn comes straight from Bedrock's
own Converse API usage response (see run_integration_test.py's boto3
converse() wrapper) — not an estimate.

Run from inside backend/ (after run_integration_test.py has produced the
run):
    python tests/score_operational.py integration/result_claude_claude_260826_1832

Results written to tests/output/test_results/operational/<run>/,
mirroring the run name so different runs never overwrite each other.
"""

import csv
import json
import os
import sys

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
DEFAULT_RUN = "integration/result_claude_claude_260826_1832"


def main(run: str = DEFAULT_RUN):
    pred_dir = os.path.join(BASE_DIR, run)
    output_dir = os.path.join(BASE_DIR, "operational", run)

    if not os.path.isdir(pred_dir):
        print(f"Integration test folder not found: {pred_dir}")
        print("Run tests/run_integration_test.py first.")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    files = sorted(
        f for f in os.listdir(pred_dir)
        if f.endswith(".json") and not f.startswith("_")
    )

    if not files:
        print(f"No per-file results found in {pred_dir}")
        return

    rows = []
    for fname in files:
        with open(os.path.join(pred_dir, fname), encoding="utf-8") as f:
            record = json.load(f)
        tokens = record.get("tokens", {})
        rows.append({
            "filename": fname,
            "input_tokens": tokens.get("grand_total_input", 0),
            "output_tokens": tokens.get("grand_total_output", 0),
            "total_tokens": tokens.get("grand_total_tokens", 0),
            "model_a_input": tokens.get("model_a_input", 0),
            "model_a_output": tokens.get("model_a_output", 0),
            "model_b_input": tokens.get("model_b_input", 0),
            "model_b_output": tokens.get("model_b_output", 0),
            "elapsed_sec": record.get("elapsed_sec", 0),
        })

    header = f"{'File':<55} {'Input':>9} {'Output':>9} {'Total':>9} {'Time (s)':>9}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['filename'][:55]:<55} {r['input_tokens']:>9} {r['output_tokens']:>9} "
            f"{r['total_tokens']:>9} {r['elapsed_sec']:>9.1f}"
        )
    print("-" * len(header))

    n = len(rows)
    total_input = sum(r["input_tokens"] for r in rows)
    total_output = sum(r["output_tokens"] for r in rows)
    total_tokens = sum(r["total_tokens"] for r in rows)
    total_time = sum(r["elapsed_sec"] for r in rows)

    print(f"\nTable: Operational metrics across {n} assessment documents")
    op_header = f"{'Metric':<28} {'Total':>12} {'Per document (avg)':>20}"
    print(op_header)
    print("-" * len(op_header))
    print(f"{'Input tokens':<28} {total_input:>12} {total_input / n:>20.1f}")
    print(f"{'Output tokens':<28} {total_output:>12} {total_output / n:>20.1f}")
    print(f"{'Total tokens':<28} {total_tokens:>12} {total_tokens / n:>20.1f}")
    print(f"{'Extraction time (s)':<28} {total_time:>12.1f} {total_time / n:>20.1f}")

    summary = {
        "run": run,
        "documents": n,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_tokens,
        "total_elapsed_sec": round(total_time, 2),
        "avg_input_tokens_per_doc": round(total_input / n, 1),
        "avg_output_tokens_per_doc": round(total_output / n, 1),
        "avg_total_tokens_per_doc": round(total_tokens / n, 1),
        "avg_elapsed_sec_per_doc": round(total_time / n, 2),
        "per_file": rows,
    }

    summary_path = os.path.join(output_dir, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    csv_path = os.path.join(output_dir, "_summary.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "filename", "input_tokens", "output_tokens", "total_tokens",
            "model_a_input", "model_a_output", "model_b_input", "model_b_output",
            "elapsed_sec",
        ])
        for r in rows:
            writer.writerow([
                r["filename"], r["input_tokens"], r["output_tokens"], r["total_tokens"],
                r["model_a_input"], r["model_a_output"], r["model_b_input"], r["model_b_output"],
                r["elapsed_sec"],
            ])
        writer.writerow([])
        writer.writerow(["metric", "total", "avg_per_document"])
        writer.writerow(["input_tokens", total_input, round(total_input / n, 1)])
        writer.writerow(["output_tokens", total_output, round(total_output / n, 1)])
        writer.writerow(["total_tokens", total_tokens, round(total_tokens / n, 1)])
        writer.writerow(["elapsed_sec", round(total_time, 2), round(total_time / n, 2)])

    print(f"\nOutput: {output_dir}")
    print(f"CSV:    {csv_path}")


if __name__ == "__main__":
    run = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_RUN
    main(run)
