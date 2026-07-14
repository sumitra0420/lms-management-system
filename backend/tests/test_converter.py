"""
Run:  python tests/test_converter.py [path/to/file.docx]

If no path is given, uses the first .docx file found in tests/input/
Output is written to tests/output/01_converted/
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.converter import docx_to_markdown

DEFAULT_DOCX = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "../../data/LearningManagementSystem/services/tests/data/docx/"
    "SITXWHS005_Knowledge_Test_MultipleChoice.docx",
))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "01_converted")


def main():
    docx_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOCX

    if not os.path.exists(docx_path):
        print(f"ERROR: File not found: {docx_path}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(docx_path))[0]
    out_path = os.path.join(OUTPUT_DIR, f"{base_name}.md")

    print(f"Converting : {os.path.basename(docx_path)}")

    with open(docx_path, "rb") as f:
        file_bytes = f.read()

    markdown = docx_to_markdown(file_bytes, os.path.basename(docx_path))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"Output     : {out_path}")
    print(f"Lines      : {len(markdown.splitlines())}")
    print(f"Chars      : {len(markdown)}")
    print("PASS: converter produced output without errors.")


if __name__ == "__main__":
    main()
