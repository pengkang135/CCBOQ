"""Step 1b: Grid JSON → structured Markdown with 2D filled tables.

Splits grid by structural boundaries (chapters, sections, table groups)
since the Excel file has no standalone page numbers. Generates readable
markdown files for inspection of merge-cell filling correctness.
"""

import json, re, sys, os
from pathlib import Path
from collections import defaultdict

CHAPTER_RE = re.compile(r'第[一二三四五六七八九十]+章')
SECTION_RE = re.compile(r'第[一二三四五六七八九十]+节')
SUBSECTION_RE = re.compile(r'^[一二三四五六七八九十]+[、，,]')
TOC_RE = re.compile(r'……|…')


def is_full_row_merge(cells):
    """Check if all cells in the row have the same value."""
    values = [str(v).strip() for v in cells.values()]
    if not values or len(values) < 2:
        return None
    if all(v == values[0] for v in values):
        return values[0]
    return None


def classify_row(row):
    """Classify a single row."""
    merged_val = is_full_row_merge(row['cells'])
    cells = row['cells']
    a_val = str(cells.get('A', '')).strip()
    b_val = str(cells.get('B', '')).strip()
    all_text = ' '.join(str(v) for v in cells.values())

    if merged_val:
        if CHAPTER_RE.search(merged_val) and TOC_RE.search(merged_val):
            return 'toc_entry'
        if CHAPTER_RE.search(merged_val):
            return 'chapter_title'
        if '续表' in merged_val:
            return 'continued_table'
        if '注：' in merged_val or '注:' in merged_val:
            return 'notes'
        if SECTION_RE.search(merged_val) or '说明' in merged_val:
            return 'section_intro'
        return 'full_text'

    if a_val == '顺序号' and ('定额编号' in b_val or '定额编号' in str(cells.get('C', ''))):
        return 'table_header'
    if a_val.isdigit() and 1 <= int(a_val) <= 500 and b_val:
        return 'data_row'

    if all_text.strip():
        return 'text'

    return 'empty'


def split_into_sections(rows):
    """Split rows into logical sections based on structural boundaries.

    Hierarchy:
    - chapter_title → new chapter section
    - toc_entry → TOC section
    - table_header → new table group within chapter
    """
    sections = []
    current = {'type': 'front_matter', 'title': 'Front Matter', 'rows': [], 'subsections': []}
    current_table = None  # sub-group for table + data rows

    for row in rows:
        rtype = classify_row(row)
        merged_val = is_full_row_merge(row['cells'])

        if rtype == 'chapter_title':
            if current['rows'] or current.get('subsections'):
                sections.append(current)
            current = {'type': 'chapter', 'title': merged_val, 'rows': [], 'subsections': []}
            current_table = None

        elif rtype == 'toc_entry':
            if current['type'] == 'front_matter' and not current['title']:
                current['title'] = '目录'
            current['rows'].append(row)

        elif rtype == 'table_header':
            if current_table:
                current['subsections'].append(current_table)
            current_table = {'type': 'table', 'rows': [row], 'title': f'Table at row {row["row"]}'}
            current['rows'].append(row)

        elif rtype == 'data_row':
            if current_table:
                current_table['rows'].append(row)
            current['rows'].append(row)

        elif rtype == 'continued_table':
            if current_table:
                current_table['rows'].append(row)
            current['rows'].append(row)

        else:
            # text, notes, section_intro, full_text, empty
            if current_table and rtype in ('empty',):
                # empty row within a table group: could be separation
                current_table['rows'].append(row)
            elif current_table and rtype == 'notes':
                # notes after a table belong to the table
                current_table['rows'].append(row)
            else:
                # End current table group
                if current_table:
                    current['subsections'].append(current_table)
                    current_table = None
                current['rows'].append(row)

    if current_table:
        current['subsections'].append(current_table)
    if current['rows'] or current.get('subsections'):
        sections.append(current)

    return sections


def build_md_table(rows, max_cols=36):
    """Convert rows to a markdown table string."""
    if not rows:
        return '*Empty*'

    all_cols = set()
    for r in rows:
        all_cols.update(r['cells'].keys())
    if not all_cols:
        return '*No data cells*'

    sorted_cols = sorted(all_cols, key=lambda c: (len(c), c))
    if len(sorted_cols) > max_cols:
        sorted_cols = sorted_cols[:max_cols]

    header = '| Row |' + '|'.join(f' {c} ' for c in sorted_cols) + '|'
    sep = '|-----|' + '|-----' * len(sorted_cols) + '|'
    lines = [header, sep]

    for row in rows:
        cells = row['cells']
        rtype = classify_row(row)
        prefix = {'table_header': 'H', 'data_row': 'D', 'continued_table': 'C',
                  'notes': 'N', 'empty': '~'}.get(rtype, '')
        rn = f'{row["row"]}{prefix}'
        cell_strs = []
        for c in sorted_cols:
            val = cells.get(c, '')
            if val:
                clean = str(val).replace('\n', ' ').replace('|', '/')
                if len(clean) > 35:
                    clean = clean[:32] + '...'
                cell_strs.append(clean)
            else:
                cell_strs.append('')
        lines.append(f'| {rn} |' + '|'.join(f' {cs} ' for cs in cell_strs) + '|')

    return '\n'.join(lines)


def generate_md(sections, output_dir, source_name):
    """Write per-section MD files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    index_lines = [
        f'# {source_name}',
        '',
        f'Sections: {len(sections)}',
        '',
        '| # | Type | Title | Rows | Subsections |',
        '|---|------|-------|------|-------------|',
    ]

    file_list = []
    for i, sec in enumerate(sections):
        sec_type = sec['type']
        title = sec.get('title', 'Untitled')[:60]
        n_rows = len(sec['rows'])
        n_subs = len(sec.get('subsections', []))
        fname = f'section_{i:03d}_{sec_type}.md'
        file_list.append((fname, sec))

        # Determine row range
        if sec['rows']:
            first_row = sec['rows'][0]['row']
            last_row = sec['rows'][-1]['row']
            row_range = f'{first_row}-{last_row}'
        else:
            row_range = '-'

        # Content type summary
        type_counts = defaultdict(int)
        for r in sec['rows']:
            type_counts[classify_row(r)] += 1
        types_str = ', '.join(f'{k}:{v}' for k, v in sorted(type_counts.items()) if v > 0)

        index_lines.append(
            f'| {i} | {sec_type} | [{title}](./{fname}) | {n_rows} ({row_range}) | {n_subs} |')
        index_lines.append(f'| | | *{types_str}* | | |')

    index_path = output_dir / 'index.md'
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(index_lines) + '\n')

    # Generate per-section files
    for fname, sec in file_list:
        lines = [
            f'# {sec["type"].upper()}: {sec.get("title", "Untitled")}',
            '',
            f'Rows: {len(sec["rows"])}',
            f'Subsections: {len(sec.get("subsections", []))}',
            '',
        ]

        # Show non-data rows first (context)
        context_rows = [r for r in sec['rows']
                        if classify_row(r) not in ('table_header', 'data_row', 'continued_table', 'empty')]
        for r in context_rows:
            rtype = classify_row(r)
            merged_val = is_full_row_merge(r['cells'])
            if merged_val:
                val = merged_val.replace('\n', ' ')
                if len(val) > 150:
                    val = val[:147] + '...'
                lines.append(f'### [{rtype}] {val}')
                lines.append('')
            else:
                non_empty = {k: v for k, v in r['cells'].items() if str(v).strip()}
                preview = ', '.join(f'{k}={str(v)[:40]}' for k, v in list(non_empty.items())[:4])
                lines.append(f'**[{rtype}] (Row {r["row"]})**: {preview}')
                lines.append('')

        # Build table for each subsection (table group)
        for si, sub in enumerate(sec.get('subsections', [])):
            table_rows = sub['rows']
            lines.append(f'## Table {si+1} (rows {table_rows[0]["row"]}-{table_rows[-1]["row"]})')
            lines.append('')
            lines.append(build_md_table(table_rows))
            lines.append('')

        # If no subsections but has table/data rows directly
        if not sec.get('subsections'):
            direct_table_rows = [r for r in sec['rows']
                               if classify_row(r) in ('table_header', 'data_row', 'continued_table')]
            if direct_table_rows:
                lines.append('## Table Data')
                lines.append('')
                lines.append(build_md_table(direct_table_rows))
                lines.append('')

        file_path = output_dir / fname
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    print(f'Index: {index_path}')
    print(f'Generated {len(file_list)} section files in {output_dir}')


def convert(grid_path, output_dir=None):
    """Main entry: convert grid JSON to structured MD."""
    grid_path = Path(grid_path)
    with open(grid_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if output_dir is None:
        output_dir = grid_path.parent / f'{grid_path.stem}_md_pages'

    for sheet_name, sheet_data in data.get('sheets', {}).items():
        rows = sheet_data.get('rows', [])
        print(f'Sheet "{sheet_name}": {len(rows)} content rows')

        sections = split_into_sections(rows)
        print(f'  Split into {len(sections)} sections')
        for i, s in enumerate(sections):
            print(f'    [{i}] {s["type"]}: {s.get("title", "")[:50]} ({len(s["rows"])} rows, '
                  f'{len(s.get("subsections", []))} tables)')

        generate_md(sections, output_dir, data.get('file', sheet_name))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Grid JSON → structured Markdown')
    ap.add_argument('grid_json', help='Path to _grid.json file')
    ap.add_argument('-o', '--output-dir', help='Output directory for MD files')
    args = ap.parse_args()

    if not os.path.exists(args.grid_json):
        print(f'File not found: {args.grid_json}')
        sys.exit(1)

    convert(args.grid_json, args.output_dir)
