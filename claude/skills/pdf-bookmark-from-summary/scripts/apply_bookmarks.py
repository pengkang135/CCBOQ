"""
Apply a bookmarks.json to a source PDF, producing a new PDF with bookmarks.
Does not modify the source file.

Usage:
    python apply_bookmarks.py <source.pdf> <bookmarks.json> [-o output.pdf] [--merge-existing]

bookmarks.json format:
    [[level, "title", page], ...]
    - level: int (1..6). Must never jump more than +1 from previous.
    - title: str (any Unicode; PDF supports UTF-8).
    - page: int (1-based, must be <= total pages).

Options:
    -o <output.pdf>      Output path. Default: <source>_bookmarked.pdf next to source.
    --merge-existing     Append to existing PDF bookmarks instead of replacing.
    --dry-run            Validate only, don't write output.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: pymupdf not installed. Run: pip install pymupdf")
    sys.exit(1)


def load_toc(json_path: Path) -> list[list]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{json_path} must contain a JSON array")
    toc = []
    for i, item in enumerate(data):
        if isinstance(item, dict):
            # Accept dict form {level, title, page}
            lvl = int(item["level"])
            title = str(item["title"])
            page = int(item["page"])
        elif isinstance(item, list) and len(item) >= 3:
            lvl, title, page = int(item[0]), str(item[1]), int(item[2])
        else:
            raise ValueError(f"item #{i} not a valid bookmark: {item!r}")
        toc.append([lvl, title, page])
    return toc


def validate_toc(toc: list[list], max_page: int) -> list[str]:
    errors = []
    prev_level = 0
    for i, (lvl, title, page) in enumerate(toc):
        if not (1 <= lvl <= 6):
            errors.append(f"#{i} '{title[:50]}': level {lvl} out of range 1..6")
        if lvl > prev_level + 1 and prev_level > 0:
            errors.append(
                f"#{i} '{title[:50]}': level {lvl} jumps from previous {prev_level}"
            )
        if not (1 <= page <= max_page):
            errors.append(f"#{i} '{title[:50]}': page {page} out of range 1..{max_page}")
        if not title.strip():
            errors.append(f"#{i}: empty title")
        prev_level = lvl
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("bookmarks", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--merge-existing", action="store_true",
                    help="Keep existing PDF bookmarks and append new ones")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"ERROR: {args.pdf} not found")
        sys.exit(1)
    if not args.bookmarks.exists():
        print(f"ERROR: {args.bookmarks} not found")
        sys.exit(1)

    new_toc = load_toc(args.bookmarks)
    print(f"loaded {len(new_toc)} bookmarks from {args.bookmarks.name}")

    doc = fitz.open(str(args.pdf))
    print(f"opened {args.pdf.name}: {doc.page_count} pages, {len(doc.get_toc())} existing bookmarks")

    if args.merge_existing:
        existing = doc.get_toc()
        # Existing bookmarks live at the top; new ones append at same-or-deeper structure
        combined = existing + new_toc
        # Re-normalise levels: after existing block, new starts at level 1
        # (Level jumps are handled below)
        toc_to_apply = combined
    else:
        toc_to_apply = new_toc

    errors = validate_toc(toc_to_apply, doc.page_count)
    if errors:
        print(f"\nValidation errors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors)-20} more")
        # Auto-fix level jumps
        print("\nauto-fixing level jumps…")
        fixed = []
        prev = 0
        for lvl, title, page in toc_to_apply:
            new_lvl = min(lvl, prev + 1) if prev > 0 else 1
            fixed.append([new_lvl, title, page])
            prev = new_lvl
        toc_to_apply = fixed
        errors2 = validate_toc(toc_to_apply, doc.page_count)
        if errors2:
            print(f"still {len(errors2)} errors after auto-fix — aborting")
            for e in errors2[:5]:
                print(f"  {e}")
            sys.exit(1)
        print("  auto-fix OK")

    if args.dry_run:
        print("\n--- Dry-run tree preview (first 30) ---")
        for lvl, title, page in toc_to_apply[:30]:
            print(f"{'  '*(lvl-1)}L{lvl} p.{page:>4}  {title[:80]}")
        doc.close()
        return

    doc.set_toc(toc_to_apply)

    if args.output:
        out = args.output
    else:
        out = args.pdf.with_name(args.pdf.stem + "_bookmarked.pdf")

    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"writing: {out}")
    doc.save(str(out), garbage=4, deflate=True)
    doc.close()

    size = out.stat().st_size / 1024 / 1024
    print(f"done. output size: {size:.1f} MB")
    print(f"open in Adobe/Foxit/browser and check the bookmarks sidebar")


if __name__ == "__main__":
    main()
