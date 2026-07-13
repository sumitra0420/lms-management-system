"""
Run:  python tests/test_consistency.py [basename]

Reads normalised_a and normalised_b from tests/output/02_extracted/
Writes consistency report to tests/output/03_consistency/

If no basename given, uses the first file found in model_a_normalised/
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.consistency import score_consistency

EXTRACTED_DIR = os.path.join(os.path.dirname(__file__), "output", "02_extracted")
OUTPUT_DIR    = os.path.join(os.path.dirname(__file__), "output", "03_consistency")


def _resolve_basename(arg: str | None) -> str:
    norm_a_dir = os.path.join(EXTRACTED_DIR, "model_a_normalised")
    if arg:
        return arg if arg.endswith(".json") else arg + ".json"
    files = sorted(f for f in os.listdir(norm_a_dir) if f.endswith(".json"))
    if not files:
        print(f"No files found in {norm_a_dir}")
        sys.exit(1)
    return files[0]


def main():
    basename = _resolve_basename(sys.argv[1] if len(sys.argv) > 1 else None)

    path_a = os.path.join(EXTRACTED_DIR, "model_a_normalised", basename)
    path_b = os.path.join(EXTRACTED_DIR, "model_b_normalised", basename)

    if not os.path.exists(path_a):
        print(f"ERROR: {path_a} not found — run test_extractor.py first")
        sys.exit(1)
    if not os.path.exists(path_b):
        print(f"ERROR: {path_b} not found — run test_extractor.py first")
        sys.exit(1)

    with open(path_a, encoding="utf-8") as f:
        normalised_a = json.load(f)
    with open(path_b, encoding="utf-8") as f:
        normalised_b = json.load(f)

    print(f"File       : {basename}")
    print(f"Questions A: {len(normalised_a.get('questions', []))}")
    print(f"Questions B: {len(normalised_b.get('questions', []))}")
    print("-" * 60)

    result = score_consistency(normalised_a, normalised_b)

    print(f"Score      : {result['score']} / 1.0")
    print(f"Threshold  : {result['threshold']}")
    print(f"Consistent : {'PASS' if result['consistent'] else 'FAIL'}")
    print()

    details = result["details"]
    print(f"Count match: {details['count_score']} "
          f"(A={details['count_a']}, B={details['count_b']})")
    print(f"Avg Q score: {details['avg_question_score']}")
    print()
    print(f"{'Q':<4} {'Text':>6} {'Answer':>8} {'Choices':>8} {'Type':>6} {'Pts':>5} {'Total':>7}")
    print("-" * 50)
    for i, q in enumerate(details["per_question"], 1):
        print(f"Q{i:<3} {q['text_similarity']:>6.2f} {q['answer_similarity']:>8.2f} "
              f"{q['choices_similarity']:>8.2f} {q['type_match']:>6.1f} "
              f"{q['points_match']:>5.1f} {q['score']:>7.4f}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, basename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print()
    print(f"Output     : {out_path}")


if __name__ == "__main__":
    main()
