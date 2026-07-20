"""
Inspect a PDF: page count, existing bookmarks, structure hints.

Usage:
    python inspect_pdf.py <source.pdf>
"""
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: pymupdf not installed. Run: pip install pymupdf")
    sys.exit(1)


def inspect(pdf_path: Path):
    doc = fitz.open(str(pdf_path))
    print(f"File: {pdf_path.name}")
    print(f"Path: {pdf_path.resolve()}")
    print(f"Size: {pdf_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"Pages: {doc.page_count}")

    toc = doc.get_toc()
    print(f"Existing bookmarks: {len(toc)}")

    if toc:
        print("\n--- First 30 bookmarks ---")
        for lvl, title, page in toc[:30]:
            indent = "  " * (lvl - 1)
            title_safe = title.encode("utf-8", errors="replace").decode("utf-8")
            print(f"{indent}L{lvl} p.{page:>4}  {title_safe[:80]}")
        if len(toc) > 30:
            print(f"... and {len(toc) - 30} more")

        levels = {}
        for lvl, _, _ in toc:
            levels[lvl] = levels.get(lvl, 0) + 1
        print(f"\nBookmark level distribution: {dict(sorted(levels.items()))}")

        print("\nSuggestion: use --merge-existing when applying new bookmarks if you want to keep these.")
    else:
        print("\nNo existing bookmarks. Safe to apply new ones directly.")

    # detect if TOC page exists (heuristic)
    print("\n--- First 5 page text samples (for reference) ---")
    for i in range(min(5, doc.page_count)):
        text = doc[i].get_text().strip()
        preview = " ".join(text.split())[:120]
        print(f"p.{i+1}: {preview!r}")

    doc.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    pdf = Path(sys.argv[1])
    if not pdf.exists():
        print(f"ERROR: {pdf} not found")
        sys.exit(1)
    inspect(pdf)
