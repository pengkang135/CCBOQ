"""
Standalone verifier: given a bookmarks.json and a PDF, sample each bookmark's
target page and print the first line of text so a human can eyeball whether
the anchor actually lands on the right content.

Usage:
    python verify_pages.py <bookmarks.json> <source.pdf> [--full-text]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

try:
    import fitz
except ImportError:
    print("ERROR: pymupdf not installed. Run: pip install pymupdf")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bookmarks", type=Path)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--full-text", action="store_true",
                    help="print full page text, not just first 200 chars")
    args = ap.parse_args()

    toc = json.loads(args.bookmarks.read_text(encoding="utf-8"))
    doc = fitz.open(str(args.pdf))

    print(f"{'lvl':<4} {'page':>5}  title / first content line")
    print("-" * 100)
    for item in toc:
        if isinstance(item, dict):
            lvl, title, page = item["level"], item["title"], item["page"]
        else:
            lvl, title, page = item[0], item[1], item[2]

        if not (1 <= page <= doc.page_count):
            print(f"L{lvl:<3} p.{page:>4}  {title[:50]}  [OUT OF RANGE]")
            continue

        text = doc[page - 1].get_text().strip()
        first = " ".join(text.split())
        preview_len = 500 if args.full_text else 100
        first_short = first[:preview_len]
        print(f"L{lvl:<3} p.{page:>4}  {title[:50]:<50}  |  {first_short}")

    doc.close()


if __name__ == "__main__":
    main()
