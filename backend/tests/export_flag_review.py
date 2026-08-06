"""
Exports every question from an integration test run into a flat CSV for
manual TP/FP/TN/FN labelling of the FLAGGING decision (not question
detection — see score_question_detection.py for that).

"flagged" here is the same boolean run_integration_test.py already computes
per question (low A/B consistency score, schema validation failure, or
grounding/hallucination check). This script does not try to guess whether
a flag was "deserved" — it just lays out, per question, whether the
pipeline flagged it and why, with an empty human_verdict column for you to
fill in by hand after checking the source document:

    TP = pipeline flagged it AND the question genuinely has a problem
    FP = pipeline flagged it BUT the question is actually fine
    TN = pipeline did NOT flag it AND the question is fine
    FN = pipeline did NOT flag it BUT the question actually has a problem

Also includes conflict_fields/model_a_vs_b — the underlying per-field
Model A vs Model B disagreement (from consistency.py's conflicts dict) for
any flagged question, so you can see WHAT actually differed between the
two models' outputs, not just that they disagreed. Useful for reporting
which model tends to be the actual source of a flag (e.g. Model B
returning a raw option letter like "C" instead of resolved answer text).

Run from inside backend/ (after run_integration_test.py has produced the run):
    python tests/export_flag_review.py integration/result_claude_nova_oldprompt_270726
    python tests/export_flag_review.py integration/result_claude_nova_newprompt_270726

Output: tests/output/test_results/flag_review/<run>/review.csv
"""

import csv
import json
import os
import sys

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")


def _format_choices(q: dict) -> str:
    """
    Renders choices[] as one readable string, marking which option(s) the
    pipeline scored correct — without this, a reviewer can't tell whether a
    multiple_choice question's distractors are right (correct_answer alone
    only shows the correct option text, not the full option set).
    """
    choices = q.get("choices") or []
    return " | ".join(
        f"[correct] {c.get('text', '')}" if c.get("correct") else c.get("text", "")
        for c in choices
    )


def _flag_reasons(q: dict) -> str:
    reasons = []
    if (q.get("consistency_score") if q.get("consistency_score") is not None else 1.0) < 0.90:
        reasons.append("low_consistency")
    if not q.get("schema_valid", True):
        reasons.append("schema_invalid")
    if q.get("hallucination_detected"):
        reasons.append("hallucination")
    return "+".join(reasons) if reasons else ("unspecified" if q.get("flagged") else "")


def _fmt_conflict_value(v):
    # Full value, untruncated — this goes into a CSV cell for review, not a
    # terminal line, so there's no width to protect. Truncating here used
    # to cut the actual data (not just its display), silently hiding the
    # real difference between Model A and Model B's answers.
    return json.dumps(v) if isinstance(v, (list, dict)) else str(v)


def _format_conflicts(q: dict) -> tuple[str, str]:
    """
    Renders Model A's and Model B's conflicting values as two separate,
    aligned strings so a reviewer can see WHAT actually differed, not just
    that consistency_score was low — e.g. model_a_value="Wheat flour pasta",
    model_b_value="C" shows Model B returned a raw option letter instead of
    the resolved answer text, a Model B formatting problem, not a genuine
    disagreement about content. When a question has more than one
    conflicting field, each side's values are joined with "|" in the same
    order as conflict_fields, the same convention the choices column uses.
    """
    conflicts = q.get("conflicts") or {}
    if not conflicts:
        return "", ""
    a_vals = " | ".join(_fmt_conflict_value(vals.get("value_a")) for vals in conflicts.values())
    b_vals = " | ".join(_fmt_conflict_value(vals.get("value_b")) for vals in conflicts.values())
    return a_vals, b_vals


def main(run: str):
    run_dir = os.path.join(BASE_DIR, run)
    if not os.path.isdir(run_dir):
        print(f"Run folder not found: {run_dir}")
        print("Run tests/run_integration_test.py first.")
        sys.exit(1)

    out_dir = os.path.join(BASE_DIR, "flag_review", run)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "review.csv")

    rows = []
    for fname in sorted(os.listdir(run_dir)):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        with open(os.path.join(run_dir, fname), encoding="utf-8") as f:
            record = json.load(f)

        for q in record.get("questions", []):
            model_a_value, model_b_value = _format_conflicts(q)
            rows.append({
                "filename":          record.get("filename", fname),
                "question_id":       q.get("id"),
                "type":              q.get("type"),
                "question_text":     q.get("text"),
                "correct_answer":    q.get("correct_answer"),
                "choices":           _format_choices(q),
                "flagged":           q.get("flagged", False),
                "flag_reasons":      _flag_reasons(q),
                "consistency_score": q.get("consistency_score"),
                "grounding_score":   q.get("grounding_score"),
                "conflict_fields":   ", ".join((q.get("conflicts") or {}).keys()),
                "model_a_value":     model_a_value,
                "model_b_value":     model_b_value,
                "human_verdict":     "",  # fill in by hand: TP / FP / TN / FN
            })

    if not rows:
        print(f"No questions found in {run_dir}")
        return

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    flagged_count = sum(1 for r in rows if r["flagged"])
    print(f"Wrote {len(rows)} questions ({flagged_count} flagged) to {out_path}")
    print("Fill in the human_verdict column (TP/FP/TN/FN) for every row, then run:")
    print(f"    python tests/plot_flag_results.py {run} <other_run>")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests/export_flag_review.py <run-subfolder>")
        print("e.g.:  python tests/export_flag_review.py integration/result_claude_nova_oldprompt_270726")
        sys.exit(1)
    main(sys.argv[1])
