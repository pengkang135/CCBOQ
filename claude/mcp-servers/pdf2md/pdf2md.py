"""CLI entry point for pdf2md - convert PDF to Markdown."""

import argparse
import sys
from pathlib import Path

from pdf2md_core import pdf_to_markdown


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to Markdown with auto text/image detection"
    )
    parser.add_argument("input", help="Input PDF file path")
    parser.add_argument("-o", "--output", help="Output markdown file path")
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="Skip text extraction, OCR every page",
    )
    parser.add_argument(
        "--page-range",
        help='Page range, e.g. "1-5,7,10-12" (1-based)',
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    md = pdf_to_markdown(
        str(input_path.resolve()),
        force_ocr=args.force_ocr,
        page_range=args.page_range,
    )

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"Saved to {args.output}")
    else:
        print(md)


if __name__ == "__main__":
    main()
