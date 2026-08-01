"""
Extraction Performance — axis 1 of the testing plan (Section 2: Field
Level), the finer-grained companion to score_count_validation.py's
aggregate totals (Section 1) and auto_verdict.py's flagging check
(Section 3).

Answers: "% of fields extracted correctly", broken down per field —
Question Text, Marks, Answer, Choices — checked per question against
ground truth, the way count_validation.py checks aggregate totals but at
individual-field, per-question granularity instead.

Matches predicted questions to ground truth using the same greedy
text-similarity matcher score_question_detection.py uses (MATCH_THRESHOLD,
autojunk=False), then checks each field EXACTLY (character-for-character,
after trimming surrounding whitespace) against ground truth — no fuzzy
tolerance, intentionally stricter than auto_verdict.py's similarity-threshold
comparison, per your call to use exact matching here.

One deliberate exception: correct_answer treats "|" and ";" as the same
separator when splitting into a set of items — "a; b; c" and "a | b | c"
count as the same answer, since that's a pure punctuation difference, not
a content error. Nothing else is normalized: a leading phrase like "Any
three of:" is real content (it tells the learner how many answers are
required) and is NOT stripped — if one side has it and the other doesn't,
that's still a genuine mismatch. Commas are also left alone as a
separator, since real answers use commas inside a single item (e.g.
"clean, full flavour with no sour notes") — splitting on them would
create a false mismatch in the other direction. question_text/marks/choices
stay fully exact, no normalization at all.

Denominator for each field is the number of GROUND TRUTH questions the
field applies to (not predicted questions) — a dropped question counts as
wrong on every applicable field, since ground truth is the source of truth
for what SHOULD have been extracted. Hallucinated predictions (no GT
match) don't correspond to any real field slot, so they're reported
separately as a count, not folded into field accuracy.

    question_text    — applies to every question
    marks             — applies to every question
    correct_answer    — applies to every question
    choices            — applies to multiple_choice questions only
                          (ground truth question has a non-empty choices list)

Run from inside backend/ (after generate_ground_truth.py AND
run_integration_test.py have both been run):
    python tests/score_field_accuracy.py integration/result_1

Results written to tests/output/test_results/field_accuracy/<run>/,
mirroring the run name so different runs never overwrite each other.
"""

import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.score_question_detection import _greedy_match, MATCH_THRESHOLD

BASE_DIR = os.path.join(os.path.dirname(__file__), "output", "test_results")
GT_DIR   = os.path.join(BASE_DIR, "groundtruth")

FIELDS_ALL_TYPES = ["question_text", "marks", "correct_answer"]
FIELD_CHOICES    = "choices"
ALL_FIELDS       = FIELDS_ALL_TYPES + [FIELD_CHOICES]

# "|" and ";" both separate answer-list items in different source documents
# — treated as equivalent. "," is deliberately excluded: real answers use
# commas inside a single item (e.g. "clean, full flavour with no sour
# notes"), so splitting on it would break one item into two.
_ANSWER_SEPARATOR_RE = re.compile(r"\s*[|;]\s*")


def _norm_text(s) -> str:
    return " ".join(str(s or "").split())


def _gt_answer(gt: dict) -> str:
    return gt.get("correct_answer") if gt.get("correct_answer") is not None else (gt.get("answer") or "")


def _answer_key(s) -> frozenset:
    normalized = _norm_text(s).rstrip(".").strip()
    if not normalized:
        return frozenset()
    return frozenset(_norm_text(part) for part in _ANSWER_SEPARATOR_RE.split(normalized) if _norm_text(part))


def _choices_key(choices: list) -> frozenset:
    return frozenset((_norm_text(c.get("text")), bool(c.get("correct"))) for c in (choices or []))


def _field_match(field: str, pred: dict, gt: dict) -> bool:
    if field == "question_text":
        return _norm_text(pred.get("text")) == _norm_text(gt.get("question"))
    if field == "marks":
        return pred.get("points") == gt.get("mark")
    if field == "correct_answer":
        return _answer_key(pred.get("correct_answer")) == _answer_key(_gt_answer(gt))
    if field == FIELD_CHOICES:
        return _choices_key(pred.get("choices")) == _choices_key(gt.get("choices"))
    raise ValueError(field)


def _field_display(field: str, pred: dict, gt: dict) -> tuple:
    """Short pred-vs-gt strings for the mismatch printout — truncated so a
    long answer/choices list doesn't blow out the terminal line."""
    def _trunc(s, n=70):
        s = _norm_text(s)
        return s if len(s) <= n else s[:n - 1] + "…"

    if field == "question_text":
        return _trunc(pred.get("text")), _trunc(gt.get("question"))
    if field == "marks":
        return str(pred.get("points")), str(gt.get("mark"))
    if field == "correct_answer":
        return _trunc(pred.get("correct_answer")), _trunc(_gt_answer(gt))
    if field == FIELD_CHOICES:
        pred_n = len(pred.get("choices") or [])
        gt_n   = len(gt.get("choices") or [])
        return f"{pred_n} option(s)", f"{gt_n} option(s)"
    raise ValueError(field)


def _score_file(gt_record: dict, pred_record: dict, tallies: dict, rows: list, hallucinated: list, mismatches: list) -> dict:
    gt_questions   = gt_record.get("questions", [])
    pred_questions = pred_record.get("questions", [])
    filename = pred_record.get("filename", "")

    gt_texts   = [q.get("question") or "" for q in gt_questions]
    pred_texts = [q.get("text")     or "" for q in pred_questions]

    matched_pairs, unmatched_gt, unmatched_pred = _greedy_match(gt_texts, pred_texts, MATCH_THRESHOLD)
    matched_by_gt = {gt_i: pred_j for gt_i, pred_j, _ in matched_pairs}

    file_tally = {f: {"correct": 0, "total": 0} for f in ALL_FIELDS}

    for gt_i, gt in enumerate(gt_questions):
        is_mcq = bool(gt.get("choices"))
        fields = FIELDS_ALL_TYPES + ([FIELD_CHOICES] if is_mcq else [])

        pred_j = matched_by_gt.get(gt_i)
        pred = pred_questions[pred_j] if pred_j is not None else {}

        row = {
            "filename":       filename,
            "gt_question_id": gt.get("id"),
            "matched":        pred_j is not None,
        }
        for field in ALL_FIELDS:
            if field not in fields:
                row[field] = ""  # not applicable to this question's type
                continue
            correct = (pred_j is not None) and _field_match(field, pred, gt)
            tallies[field]["correct"]    += int(correct)
            tallies[field]["total"]      += 1
            file_tally[field]["correct"] += int(correct)
            file_tally[field]["total"]   += 1
            row[field] = correct

            if not correct:
                if pred_j is None:
                    pred_val, gt_val = "(question not extracted)", _field_display(field, {}, gt)[1]
                else:
                    pred_val, gt_val = _field_display(field, pred, gt)
                mismatches.append({
                    "filename": filename, "gt_question_id": gt.get("id"), "field": field,
                    "pred": pred_val, "gt": gt_val,
                })
        rows.append(row)

    for pred_j in unmatched_pred:
        hallucinated.append({
            "filename": filename,
            "question_id": pred_questions[pred_j].get("id"),
            "text": pred_questions[pred_j].get("text"),
        })

    return file_tally


def main(run: str):
    pred_dir = os.path.join(BASE_DIR, run)
    if not os.path.isdir(GT_DIR):
        print(f"Ground truth folder not found: {GT_DIR}")
        print("Run tests/generate_ground_truth.py first.")
        sys.exit(1)
    if not os.path.isdir(pred_dir):
        print(f"Integration test folder not found: {pred_dir}")
        print("Run tests/run_integration_test.py first.")
        sys.exit(1)

    out_dir = os.path.join(BASE_DIR, "field_accuracy", run)
    os.makedirs(out_dir, exist_ok=True)

    gt_files = sorted(f for f in os.listdir(GT_DIR) if f.endswith(".json") and not f.startswith("_"))

    tallies = {f: {"correct": 0, "total": 0} for f in ALL_FIELDS}
    rows = []
    hallucinated = []
    mismatches = []
    skipped = 0

    header = f"{'File':<55} {'Q':>5} {'Ans':>5} {'Mark':>5} {'Choice':>7}"
    print(header)
    print("-" * len(header))

    for fname in gt_files:
        pred_path = os.path.join(pred_dir, fname)
        if not os.path.exists(pred_path):
            print(f"  PENDING {fname} — no prediction for this run yet")
            skipped += 1
            continue
        with open(os.path.join(GT_DIR, fname), encoding="utf-8") as f:
            gt_record = json.load(f)
        with open(pred_path, encoding="utf-8") as f:
            pred_record = json.load(f)
        file_tally = _score_file(gt_record, pred_record, tallies, rows, hallucinated, mismatches)

        def _cell(field):
            t = file_tally[field]
            if not t["total"]:
                return "n/a"
            return f"{t['correct']}/{t['total']}" + ("" if t["correct"] == t["total"] else " !")

        print(f"{fname[:55]:<55} {_cell('question_text'):>5} {_cell('correct_answer'):>5} {_cell('marks'):>5} {_cell('choices'):>7}")

    print("-" * len(header))
    print(f"{'Field':<18} {'Correct':>8} {'Total':>8} {'Accuracy':>10}")
    print("-" * 48)
    for field in ALL_FIELDS:
        t = tallies[field]
        acc = t["correct"] / t["total"] if t["total"] else float("nan")
        print(f"{field:<18} {t['correct']:>8} {t['total']:>8} {acc:>9.1%}")

    pooled_correct = sum(tallies[f]["correct"] for f in ALL_FIELDS)
    pooled_total   = sum(tallies[f]["total"]   for f in ALL_FIELDS)
    pooled_acc = pooled_correct / pooled_total if pooled_total else float("nan")
    print("-" * 48)
    print(f"{'OVERALL':<18} {pooled_correct:>8} {pooled_total:>8} {pooled_acc:>9.1%}")

    if mismatches:
        print(f"\nMismatches ({len(mismatches)}):")
        mhead = f"  {'File':<40} {'Q':<8} {'Field':<15} {'Predicted':<35} {'Ground Truth'}"
        print(mhead)
        for m in mismatches:
            print(f"  {m['filename'][:40]:<40} {m['gt_question_id']:<8} {m['field']:<15} {m['pred'][:35]:<35} {m['gt']}")

    print(f"\nHallucinated (extra, unmatched) predicted questions: {len(hallucinated)}")
    if skipped:
        print(f"{skipped} file(s) pending — run run_integration_test.py to fill these in.")

    # Detail CSV — one row per ground-truth question, pass/fail per field
    detail_path = os.path.join(out_dir, "detail.csv")
    with open(detail_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "gt_question_id", "matched"] + ALL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    # Summary CSV — one row per field, for pasting into a report
    summary_csv_path = os.path.join(out_dir, "_summary.csv")
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["field", "correct", "total", "accuracy_pct"])
        for field in ALL_FIELDS:
            t = tallies[field]
            acc = round(t["correct"] / t["total"] * 100, 1) if t["total"] else ""
            writer.writerow([field, t["correct"], t["total"], acc])
        writer.writerow(["OVERALL", pooled_correct, pooled_total, round(pooled_acc * 100, 1) if pooled_total else ""])
        writer.writerow([])
        writer.writerow(["hallucinated_questions", len(hallucinated)])

    summary_json_path = os.path.join(out_dir, "_summary.json")
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "fields": {f: {"correct": tallies[f]["correct"], "total": tallies[f]["total"]} for f in ALL_FIELDS},
            "overall": {"correct": pooled_correct, "total": pooled_total},
            "hallucinated": hallucinated,
        }, f, indent=2, ensure_ascii=False)

    print(f"\nOutput: {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tests/score_field_accuracy.py <run-subfolder>")
        print("e.g.:  python tests/score_field_accuracy.py integration/result_oldprompt")
        sys.exit(1)
    main(sys.argv[1])
