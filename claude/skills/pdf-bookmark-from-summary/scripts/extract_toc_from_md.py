"""
Parse a summary markdown into a bookmark tree by matching its headings and
page references against a source PDF.

Strategy:
  1. Parse markdown headings (## / ### / ####) to build the level structure.
  2. Find every "PDF page reference" in the md (regex on `P.212`, `PDF 212`,
     `第 212 页`, `212 起`, `212-214`, `p.212`, etc.), each anchored to the
     nearest preceding heading.
  3. For each reference, try to verify the actual PDF page via nearby context
     keywords (the heading text plus any bolded phrases on the same line).
  4. Emit bookmarks.json with [level, title, page] entries.

Usage:
    python extract_toc_from_md.py <summary.md> <source.pdf> \\
        [-o bookmarks.json] [--md-name "custom L1 title"]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: pymupdf not installed. Run: pip install pymupdf")
    sys.exit(1)


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# Page-reference patterns — capture the number(s). Order matters: try
# specific ones first.
PAGE_REF_PATTERNS = [
    # "PDF 212-214" / "PDF p.212" / "PDF 页 212"
    re.compile(r"PDF\s*(?:p\.?|页|Page)?\s*(\d{1,4})(?:\s*[-–~]\s*(\d{1,4}))?", re.I),
    # "P.212" / "p.212" (word-boundary version)
    re.compile(r"\bp\.?\s*(\d{1,4})(?:\s*[-–~]\s*(\d{1,4}))?", re.I),
    # "第 212 页" / "第212页"
    re.compile(r"第\s*(\d{1,4})\s*页(?:\s*[-–~至]\s*(?:第)?\s*(\d{1,4})\s*页?)?"),
    # "212 起" / "212 页起"
    re.compile(r"(?<![\d.])(\d{2,4})\s*(?:页)?\s*起"),
    # "212-214 页"
    re.compile(r"(?<![\d.])(\d{2,4})\s*[-–~至]\s*(\d{1,4})\s*页"),
]

# Words that indicate a line is worth extracting even if no page ref
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def parse_md_structure(md_path: Path) -> list[dict]:
    """
    Walk the markdown line by line. For each heading, record its level & text.
    For each line under a heading, extract page references + context keywords.
    """
    lines = md_path.read_text(encoding="utf-8").splitlines()

    entries = []  # each item: {level, title, page_refs: [(start, end)], context_lines: [str]}
    heading_stack = []  # list of (level, title, entry_idx)
    current_entry = None

    for lineno, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if m:
            hashes, htext = m.group(1), m.group(2)
            level = len(hashes)
            entry = {
                "type": "heading",
                "md_level": level,
                "title": htext.strip(),
                "line": lineno,
                "page_refs": [],
                "context_lines": [],
            }
            entries.append(entry)
            current_entry = entry
            continue

        # Not a heading — look for page refs in this line
        if not line.strip():
            continue

        refs = extract_page_refs(line)
        if refs and current_entry is not None:
            # Record the line as a leaf entry hanging off current heading
            leaf = {
                "type": "leaf",
                "md_level": current_entry["md_level"] + 1,  # nested one deeper
                "title": summarise_line(line),
                "line": lineno,
                "page_refs": refs,
                "context_lines": [line.strip()],
                "parent_heading": current_entry["title"],
            }
            entries.append(leaf)

    return entries


def extract_page_refs(line: str) -> list[tuple[int, int | None]]:
    """Return list of (start_page, end_page_or_None) tuples."""
    refs = []
    seen = set()
    for pat in PAGE_REF_PATTERNS:
        for m in pat.finditer(line):
            groups = m.groups()
            start = int(groups[0])
            end = int(groups[1]) if len(groups) > 1 and groups[1] else None
            # Filter obviously nonsense pages (e.g. row numbers in tables)
            if start < 1 or start > 9999:
                continue
            key = (start, end)
            if key in seen:
                continue
            seen.add(key)
            refs.append(key)
    return refs


def summarise_line(line: str) -> str:
    """Extract a short bookmark title from a table row or bullet.

    For table rows, combine the first 2-3 non-empty cells so the title has
    real semantic content (e.g. "042000 - Unit Masonry - 空心砌块…").
    """
    # Prefer first bold phrase — but only if long enough
    for boldsm in BOLD_RE.finditer(line):
        phrase = boldsm.group(1).strip()
        if len(phrase) >= 4:
            # Add trailing context from the line
            remainder = line[boldsm.end():].strip()
            # take up to next pipe/newline
            remainder = remainder.split("|", 1)[0].strip("* \t")
            if remainder and len(phrase) < 30:
                return re.sub(r"\*\*|`", "", f"{phrase} — {remainder}")[:120]
            return re.sub(r"\*\*|`", "", phrase)[:120]
    # Table row: pipe-separated — take first 2-3 non-empty cells
    if "|" in line:
        cells = [c.strip() for c in line.strip("|").split("|")]
        cells = [re.sub(r"\*\*|`", "", c).strip() for c in cells if c and c != "-"]
        if cells:
            joined = " — ".join(cells[:3])
            return joined[:120]
    # Bullet
    stripped = re.sub(r"^\s*[-*+]\s*", "", line).strip()
    return re.sub(r"\*\*|`", "", stripped)[:120]


def find_first_page(doc: fitz.Document, needles: list[str]) -> int | None:
    """Return the first PDF page (1-based) containing ALL needles as substrings."""
    if not needles:
        return None
    for pno in range(doc.page_count):
        text = doc[pno].get_text()
        if all(n in text for n in needles):
            return pno + 1
    return None


def verify_pages(entries: list[dict], pdf_path: Path) -> list[dict]:
    """For each entry with page_refs, try to verify against PDF content.

    Verification is only attempted if we have strong needles (long enough
    context keywords). Otherwise the claimed page is trusted as-is.
    """
    doc = fitz.open(str(pdf_path))
    for entry in entries:
        if not entry["page_refs"]:
            continue
        claimed = entry["page_refs"][0][0]
        entry["claimed_page"] = claimed

        # Build context needles from title + bold words in context lines
        needles = []
        title = entry["title"].strip()
        # Only trust title as needle if it's substantial (not a bare number/code)
        title_clean = title.split("（")[0].split("(")[0].strip()
        if len(title_clean) >= 8 and not re.fullmatch(r"[一二三四五六七八九十0-9. \-—]+", title_clean):
            needles.append(title_clean[:40])

        for ctx in entry.get("context_lines", []):
            for b in BOLD_RE.findall(ctx):
                if len(b) >= 6:
                    needles.append(b[:40])

        # Deduplicate while preserving order
        seen = set()
        needles = [n for n in needles if not (n in seen or seen.add(n))]

        # Only verify if we have at least one strong needle
        if not needles:
            entry["verified_page"] = None
            continue

        # Try full needle set first, then progressively drop last needle
        found = None
        for k in range(len(needles), 0, -1):
            found = find_first_page(doc, needles[:k])
            if found:
                break
        entry["verified_page"] = found

        if found and abs(found - claimed) > 2:
            entry["page_offset"] = found - claimed
    doc.close()
    return entries


def build_bookmarks(
    entries: list[dict], md_name: str, doc_page_count: int
) -> list[list]:
    """
    Assemble a bookmark tree [[level, title, page], ...] rooted at Level 1
    = md filename. Includes empty headings (without page refs) as structural
    parents when their children have page refs.

    Level mapping: baseline = smallest heading level in the doc → L2.
      Example: if only ## and ### are used, ## → L2, ### → L3, leaf → L4.
      If # exists, # → L2, ## → L3.
    """
    # Determine baseline heading level
    heading_levels = [e["md_level"] for e in entries if e["type"] == "heading"]
    if not heading_levels:
        min_lvl = 1
    else:
        min_lvl = min(heading_levels)

    def map_level(md_lvl: int) -> int:
        # md heading at min_lvl → L2 (right under file L1)
        return min(md_lvl - min_lvl + 2, 6)

    result = [[1, f"【{md_name}】索引", 1]]  # placeholder first page

    first_valid_page = None
    heading_pending = []  # queue of headings waiting to emit (need a page)

    def emit_pending_headings(fallback_page: int):
        """Emit any queued headings using fallback_page as their target."""
        nonlocal first_valid_page
        for h in heading_pending:
            result.append([map_level(h["md_level"]), h["title"], fallback_page])
            if first_valid_page is None:
                first_valid_page = fallback_page
        heading_pending.clear()

    for entry in entries:
        if entry["type"] == "heading":
            # Queue heading — will be emitted when we know its target page
            # (from the first descendant leaf) or right after with any page.
            # If heading itself has refs (rare — but possible if the heading
            # line contains a page number), use them immediately.
            heading_pending.append(entry)
            continue

        # entry is a leaf with page refs
        refs = entry.get("page_refs", [])
        page = entry.get("verified_page") or entry.get("claimed_page")
        if page is None and refs:
            page = refs[0][0]
        if page is None:
            continue
        # Clamp to doc range
        page = max(1, min(page, doc_page_count))
        if first_valid_page is None:
            first_valid_page = page

        # Emit any pending headings using this page as fallback
        emit_pending_headings(page)

        level = map_level(entry["md_level"])
        title = entry["title"]

        # Annotate mismatch between claimed and verified
        if entry.get("page_offset"):
            title = f"{title}  [PDF={page}, md 标 P.{entry['claimed_page']}]"

        # Append page marker to leaf
        title = f"{title} → P.{page}"

        result.append([level, title, page])

    # Any remaining headings without children — drop or point to end of doc
    heading_pending.clear()

    # Update L1 page to first valid page
    if first_valid_page:
        result[0][2] = first_valid_page

    result = normalise_levels(result)
    return result


def normalise_levels(toc: list[list]) -> list[list]:
    """Ensure levels never jump more than +1."""
    fixed = []
    prev = 0
    for lvl, title, page in toc:
        new_lvl = min(lvl, prev + 1)
        fixed.append([new_lvl, title, page])
        prev = new_lvl
    return fixed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("md", type=Path, help="summary markdown file")
    ap.add_argument("pdf", type=Path, help="source PDF")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output bookmarks.json (default: <md>_bookmarks.json)")
    ap.add_argument("--md-name", type=str, default=None,
                    help="custom L1 bookmark title (default: md filename)")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip PDF content verification (faster, use md pages as-is)")
    args = ap.parse_args()

    if not args.md.exists():
        print(f"ERROR: {args.md} not found")
        sys.exit(1)
    if not args.pdf.exists():
        print(f"ERROR: {args.pdf} not found")
        sys.exit(1)

    print(f"parsing markdown: {args.md.name}")
    entries = parse_md_structure(args.md)
    n_headings = sum(1 for e in entries if e["type"] == "heading")
    n_leaves = sum(1 for e in entries if e["type"] == "leaf")
    print(f"  headings: {n_headings}, leaf entries with page refs: {n_leaves}")

    if not args.no_verify:
        print(f"verifying against PDF: {args.pdf.name}")
        entries = verify_pages(entries, args.pdf)
        verified = sum(1 for e in entries if e.get("verified_page"))
        offset = sum(1 for e in entries if e.get("page_offset"))
        print(f"  verified: {verified}, with offset (mismatch): {offset}")

    doc = fitz.open(str(args.pdf))
    doc_pages = doc.page_count
    doc.close()

    md_name = args.md_name or args.md.name
    toc = build_bookmarks(entries, md_name, doc_pages)
    print(f"assembled {len(toc)} bookmarks")

    out = args.output or args.md.with_suffix(".bookmarks.json")
    out.write_text(
        json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"saved: {out}")

    # Print preview
    print("\n--- Preview (first 20) ---")
    for lvl, title, page in toc[:20]:
        indent = "  " * (lvl - 1)
        print(f"{indent}L{lvl} p.{page:>4}  {title[:80]}")

    print("\nNext: python apply_bookmarks.py", args.pdf.name, out.name)


if __name__ == "__main__":
    main()
