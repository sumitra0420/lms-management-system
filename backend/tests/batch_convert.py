"""
Batch-converts all DOCX files in a directory through converter.py
and saves each result as a .txt file in tests/output/

Run from inside backend/:
    python tests/batch_convert.py

Or point at a custom DOCX folder:
    python tests/batch_convert.py /path/to/docx/folder
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.converter import docx_to_markdown

DEFAULT_DOCX_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "../../data/LearningManagementSystem/services/tests/data/docx",
))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def batch_convert(docx_dir: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    docx_files = sorted([
        f for f in os.listdir(docx_dir)
        if f.endswith(".docx") and not f.startswith("~$")  # skip Word lock files
    ])

    if not docx_files:
        print(f"No DOCX files found in: {docx_dir}")
        return

    print(f"Found {len(docx_files)} files in: {docx_dir}")
    print(f"Output folder : {OUTPUT_DIR}")
    print("-" * 60)

    passed, failed = [], []

    for filename in docx_files:
        docx_path = os.path.join(docx_dir, filename)
        out_name = os.path.splitext(filename)[0] + ".txt"
        out_path = os.path.join(OUTPUT_DIR, out_name)

        try:
            with open(docx_path, "rb") as f:
                file_bytes = f.read()

            text = docx_to_markdown(file_bytes, filename)

            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)

            line_count = len(text.splitlines())
            print(f"  OK   {filename}  ({line_count} lines)")
            passed.append(filename)

        except Exception as e:
            print(f"  FAIL {filename}  → {e}")
            failed.append((filename, str(e)))

    print("-" * 60)
    print(f"Done: {len(passed)} passed, {len(failed)} failed")

    if failed:
        print("\nFailed files:")
        for name, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    docx_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOCX_DIR
    batch_convert(os.path.abspath(docx_dir))
