"""
Run:  python tests/test_extractor.py [path/to/file.txt]

If no path is given, uses the first .txt file in tests/output/01_converted/
Saves 4 JSON files to tests/output/02_extracted/
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.extractor import extract

CONVERTED_DIR = os.path.join(os.path.dirname(__file__), "output", "01_converted")
OUTPUT_BASE   = os.path.join(os.path.dirname(__file__), "output", "02_extracted")

SUBDIRS = {
    "raw_a":        os.path.join(OUTPUT_BASE, "model_a_raw"),
    "raw_b":        os.path.join(OUTPUT_BASE, "model_b_raw"),
    "normalised_a": os.path.join(OUTPUT_BASE, "model_a_normalised"),
    "normalised_b": os.path.join(OUTPUT_BASE, "model_b_normalised"),
}


async def main():
    # Resolve input file
    if len(sys.argv) > 1:
        txt_path = os.path.abspath(sys.argv[1])
    else:
        files = sorted(f for f in os.listdir(CONVERTED_DIR) if f.endswith(".txt"))
        if not files:
            print(f"No .txt files found in {CONVERTED_DIR}")
            print("Run batch_convert.py first.")
            sys.exit(1)
        txt_path = os.path.join(CONVERTED_DIR, files[0])

    if not os.path.exists(txt_path):
        print(f"ERROR: File not found: {txt_path}")
        sys.exit(1)

    base_name = os.path.splitext(os.path.basename(txt_path))[0]

    print(f"File       : {os.path.basename(txt_path)}")
    print(f"Model A    : {os.getenv('MODEL_A_ID', 'not set')}")
    print(f"Model B    : {os.getenv('MODEL_B_ID', 'not set')}")
    print("Calling both models in parallel...")
    print("-" * 60)

    with open(txt_path, encoding="utf-8") as f:
        text = f.read()

    result = await extract(text)

    # Create output subdirectories
    for path in SUBDIRS.values():
        os.makedirs(path, exist_ok=True)

    # Save raw outputs
    for key in ("raw_a", "raw_b"):
        out_path = os.path.join(SUBDIRS[key], f"{base_name}.json")
        try:
            parsed = json.loads(result[key])
            content = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            content = result[key]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

    # Save normalised outputs
    for key in ("normalised_a", "normalised_b"):
        out_path = os.path.join(SUBDIRS[key], f"{base_name}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result[key], f, indent=2, ensure_ascii=False)

    # Summary
    q_a = len(result["normalised_a"].get("questions", []))
    q_b = len(result["normalised_b"].get("questions", []))
    err_a = result["normalised_a"].get("error")
    err_b = result["normalised_b"].get("error")

    print(f"Model A extracted : {q_a} questions" + (f" ⚠ {err_a}" if err_a else ""))
    print(f"Model B extracted : {q_b} questions" + (f" ⚠ {err_b}" if err_b else ""))
    print(f"Output saved to   : {OUTPUT_BASE}")
    print("-" * 60)
    print("Files written:")
    for key, path in SUBDIRS.items():
        print(f"  {key:20s} → {os.path.join(path, base_name + '.json')}")


if __name__ == "__main__":
    asyncio.run(main())
