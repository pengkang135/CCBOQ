import argparse
import json
import re
from pathlib import Path


TABLE_HEADER = "| row"
TABLE_SEPARATOR = "| ---"


def split_markdown_row(line):
    content = line.strip()
    if not content.startswith("|") or not content.endswith("|"):
        return []
    content = content[1:-1]
    cells = []
    current = []
    escape = False
    for ch in content:
        if escape:
            current.append(ch)
            escape = False
        elif ch == "\\":
            escape = True
        elif ch == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append("".join(current).strip())
    return cells


def escape_md(value):
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "<br>")
    text = text.replace("|", r"\|")
    return text.strip()


def normalize_cell(value):
    text = value.strip()
    if text in {"", "<br />", "<br/>", "<br>"}:
        return ""
    return text


def is_code_like(value):
    return bool(re.fullmatch(r"[A-Z]+(?:\.\d+)+", value))


def heading_rank(item, source):
    item = normalize_cell(item)
    source = normalize_cell(source)
    if not item:
        return 99
    if item.startswith("CLASS "):
        return 0
    if is_code_like(item):
        return item.count(".") + 1
    if source.startswith("【") and source.endswith("】"):
        return 1
    return 99


def parse_review_markdown(md_path):
    lines = Path(md_path).read_text(encoding="utf-8").splitlines()
    preamble = []
    header_lines = []
    rows = []
    in_table = False

    for line in lines:
        if line.startswith(TABLE_HEADER):
            in_table = True
            header_lines.append(line)
            continue
        if in_table and line.startswith(TABLE_SEPARATOR):
            header_lines.append(line)
            continue

        if not in_table:
            preamble.append(line)
            continue

        cells = split_markdown_row(line)
        if len(cells) != 6:
            continue
        if cells[0] in {"row", "---"}:
            continue
        try:
            excel_row = int(cells[0])
        except ValueError:
            continue
        rows.append(
            {
                "excel_row": excel_row,
                "item": cells[1],
                "source": cells[2],
                "target": cells[3],
                "unit": cells[4],
                "quantity": cells[5],
                "line": line,
            }
        )

    if not header_lines or not rows:
        raise ValueError(f"failed to parse review markdown table: {md_path}")
    return preamble, header_lines, rows


def build_sections(rows):
    sections = []
    current = None

    for row in rows:
        rank = heading_rank(row["item"], row["source"])
        starts_new = current is None or rank <= 2
        if starts_new:
            if current:
                sections.append(current)
            current = {
                "title": derive_section_title(row),
                "rank": rank,
                "rows": [row],
            }
        else:
            current["rows"].append(row)

    if current:
        sections.append(current)

    return sections


def derive_section_title(row):
    item = normalize_cell(row["item"])
    source = normalize_cell(row["source"])
    if item and source:
        return f"{item} - {source}"
    if item:
        return item
    if source:
        return source
    return f"row-{row['excel_row']}"


def split_large_section(section, max_rows):
    rows = section["rows"]
    if len(rows) <= max_rows:
        return [section]

    sub_sections = []
    current = None
    for row in rows:
        item = normalize_cell(row["item"])
        source = normalize_cell(row["source"])
        starts_new = bool(item) and not source.startswith("-")
        if current is None or starts_new:
            if current:
                sub_sections.append(current)
            current = {
                "title": derive_section_title(row),
                "rank": section["rank"] + 1,
                "rows": [row],
            }
        else:
            current["rows"].append(row)

    if current:
        sub_sections.append(current)

    if len(sub_sections) == 1:
        return [section]
    return sub_sections


def merge_sections_into_chunks(sections, min_rows, max_rows):
    expanded = []
    for section in sections:
        expanded.extend(split_large_section(section, max_rows))

    chunks = []
    current_sections = []
    current_count = 0

    for section in expanded:
        section_count = len(section["rows"])
        if not current_sections:
            current_sections.append(section)
            current_count = section_count
            continue

        would_exceed = current_count + section_count > max_rows
        if would_exceed and current_count >= min_rows:
            chunks.append(make_chunk(current_sections))
            current_sections = [section]
            current_count = section_count
            continue

        current_sections.append(section)
        current_count += section_count

    if current_sections:
        chunks.append(make_chunk(current_sections))

    return chunks


def make_chunk(sections):
    rows = []
    titles = []
    for section in sections:
        rows.extend(section["rows"])
        titles.append(section["title"])
    return {
        "title": titles[0] if len(titles) == 1 else f"{titles[0]} ... {titles[-1]}",
        "section_titles": titles,
        "rows": rows,
        "start_row": rows[0]["excel_row"],
        "end_row": rows[-1]["excel_row"],
    }


def render_chunk_document(preamble, header_lines, chunk, index, total, source_path):
    lines = list(preamble)
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(f"- Chunk source: `{source_path.name}`")
    lines.append(f"- Chunk index: `{index}/{total}`")
    lines.append(f"- Chunk title: `{chunk['title']}`")
    lines.append(f"- Covered Excel rows: `{chunk['start_row']}-{chunk['end_row']}`")
    lines.append("")
    lines.extend(header_lines)
    for row in chunk["rows"]:
        lines.append(row["line"])
    return "\n".join(lines) + "\n"


def write_manifest(out_dir, source_path, chunks):
    manifest = {
        "source_md": str(source_path),
        "chunk_count": len(chunks),
        "chunks": [],
    }
    for index, chunk in enumerate(chunks, start=1):
        manifest["chunks"].append(
            {
                "index": index,
                "file": f"{index:02d}_{safe_slug(chunk['title'])}.md",
                "title": chunk["title"],
                "start_row": chunk["start_row"],
                "end_row": chunk["end_row"],
                "row_count": len(chunk["rows"]),
                "section_titles": chunk["section_titles"],
            }
        )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def safe_slug(text):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return slug[:80] or "chunk"


def split_command(md_path, out_dir=None, min_rows=120, max_rows=250):
    if min_rows <= 0 or max_rows <= 0:
        raise ValueError("min_rows and max_rows must be positive")
    if min_rows > max_rows:
        raise ValueError("min_rows cannot be greater than max_rows")

    source_path = Path(md_path)
    out_dir = Path(out_dir) if out_dir else source_path.with_suffix("")
    preamble, header_lines, rows = parse_review_markdown(source_path)
    sections = build_sections(rows)
    chunks = merge_sections_into_chunks(sections, min_rows=min_rows, max_rows=max_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    for index, chunk in enumerate(chunks, start=1):
        file_name = f"{index:02d}_{safe_slug(chunk['title'])}.md"
        content = render_chunk_document(
            preamble=preamble,
            header_lines=header_lines,
            chunk=chunk,
            index=index,
            total=len(chunks),
            source_path=source_path,
        )
        (out_dir / file_name).write_text(content, encoding="utf-8")

    write_manifest(out_dir, source_path, chunks)
    print(out_dir)
    print(f"chunks={len(chunks)}")


def parse_updates_from_chunk(chunk_path):
    _, _, rows = parse_review_markdown(chunk_path)
    return {row["excel_row"]: row["target"] for row in rows}


def merge_command(master_md, chunks_dir, output=None):
    master_path = Path(master_md)
    out_path = Path(output) if output else master_path
    preamble, header_lines, master_rows = parse_review_markdown(master_path)

    manifest_path = Path(chunks_dir) / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunk_files = [Path(chunks_dir) / item["file"] for item in manifest["chunks"]]
    else:
        chunk_files = sorted(Path(chunks_dir).glob("*.md"))

    updates = {}
    for chunk_file in chunk_files:
        updates.update(parse_updates_from_chunk(chunk_file))

    lines = list(preamble)
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(header_lines)
    updated_rows = 0

    for row in master_rows:
        if row["excel_row"] in updates:
            row["target"] = updates[row["excel_row"]]
            updated_rows += 1
        escaped = [
            escape_md(row["excel_row"]),
            escape_md(row["item"]),
            escape_md(row["source"]),
            escape_md(row["target"]),
            escape_md(row["unit"]),
            escape_md(row["quantity"]),
        ]
        lines.append(
            f"| {escaped[0]} | {escaped[1]} | {escaped[2]} | {escaped[3]} | {escaped[4]} | {escaped[5]} |"
        )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_path)
    print(f"updated_rows={updated_rows}")


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    split_parser = subparsers.add_parser("split")
    split_parser.add_argument("md_path")
    split_parser.add_argument("--out-dir", type=str, default=None)
    split_parser.add_argument("--min-rows", type=int, default=120)
    split_parser.add_argument("--max-rows", type=int, default=250)

    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("master_md")
    merge_parser.add_argument("chunks_dir")
    merge_parser.add_argument("--output", type=str, default=None)

    args = parser.parse_args()

    if args.command == "split":
        split_command(
            args.md_path,
            out_dir=args.out_dir,
            min_rows=args.min_rows,
            max_rows=args.max_rows,
        )
        return

    merge_command(
        args.master_md,
        args.chunks_dir,
        output=args.output,
    )


if __name__ == "__main__":
    main()
