#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convert markdown tables to Excel (.xlsx) using xlsxwriter.
Usage: python md_to_xlsx.py input.md [output.xlsx] [--one-sheet] [--sheet-per-h2]
"""
import re, sys, os

try:
    import xlsxwriter
except ImportError:
    sys.exit("xlsxwriter not installed. Run: pip install xlsxwriter")

def sanitize_sheet_name(name, max_len=31):
    """Remove invalid Excel sheet name characters and truncate."""
    name = name.strip().lstrip('#').strip()
    for ch in '[]:*?/\\':
        name = name.replace(ch, '-')
    return name[:max_len]

def cell_value(raw):
    """Convert markdown cell content to appropriate Python type.
    Strips markdown **bold** markers. Returns int, float, or str."""
    text = str(raw).strip() if raw is not None else ''
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # strip **bold**
    text = text.replace('\\*', '*')  # unescape \*
    if not text or text == 'None':
        return ''
    # Try integer
    try:
        return int(text)
    except ValueError:
        pass
    # Try float
    try:
        return float(text)
    except ValueError:
        pass
    return text

def parse_markdown_tables(lines):
    """Parse markdown into list of (heading, rows) tuples.
    heading: (level, text) or None for tables without preceding heading.
    rows: list of lists (2D), excluding separator lines and empty trailing columns.
    """
    sections = []
    current_heading = None
    current_rows = []
    in_table = False

    for line in lines:
        stripped = line.strip()

        # Detect headings
        if stripped.startswith('### ') or stripped.startswith('## '):
            if current_rows:
                sections.append((current_heading, current_rows))
                current_rows = []
                in_table = False
            level = 3 if stripped.startswith('### ') else 2
            current_heading = (level, stripped.lstrip('#').strip())

        # Detect table separator (|---| or | --- | or |:---:| etc.)
        elif in_table and re.match(r'^\|[\s\-:|\s]+\|$', stripped):
            continue  # skip separator, keep in_table=True

        # Detect table row
        elif stripped.startswith('|') and '|' in stripped[1:]:
            parts = stripped.split('|')
            # Strip leading/trailing empty parts from split
            if parts[0].strip() == '':
                parts = parts[1:]
            if parts[-1].strip() == '':
                parts = parts[:-1]
            cells = [p.strip() for p in parts]

            # Don't start a table on a single-cell "header" that's really a separator remnant
            if not in_table and len(cells) <= 1:
                continue

            current_rows.append(cells)
            in_table = True

        else:
            # Non-table line
            if current_rows:
                sections.append((current_heading, current_rows))
                current_rows = []
            in_table = False
            # Update heading for non-H2/H3 lines that could be section markers
            if stripped and not stripped.startswith('|') and not stripped.startswith('#'):
                pass  # text content between tables - keep as context

    # Don't forget the last section
    if current_rows:
        sections.append((current_heading, current_rows))

    return sections

def is_data_row(cells, existing_rows):
    """Heuristic: skip duplicate header rows within the same section."""
    if not cells:
        return False
    # If identical to first row (header), skip
    if existing_rows and cells == existing_rows[0]:
        return False
    return True

def write_excel(sections, output_path, one_sheet=False, sheet_per_h2=False):
    wb = xlsxwriter.Workbook(output_path)

    fmt_title = wb.add_format({
        'bold': True, 'font_size': 12, 'font_color': '#003366',
        'font_name': 'Microsoft YaHei'
    })
    fmt_section = wb.add_format({
        'bold': True, 'font_size': 11, 'font_color': '#003366',
        'bg_color': '#E2EFDA', 'border': 1, 'font_name': 'Microsoft YaHei'
    })
    fmt_header = wb.add_format({
        'bold': True, 'font_size': 10, 'font_color': '#003366',
        'bg_color': '#DBEEF4', 'border': 1, 'text_wrap': True,
        'valign': 'vcenter', 'align': 'center', 'font_name': 'Microsoft YaHei'
    })
    fmt_data = wb.add_format({
        'font_size': 10, 'border': 1, 'text_wrap': True,
        'valign': 'top', 'font_name': 'Microsoft YaHei'
    })
    fmt_heading = wb.add_format({
        'bold': True, 'font_size': 14, 'font_color': '#003366',
        'font_name': 'Microsoft YaHei'
    })

    if one_sheet:
        # Single sheet mode
        ws = wb.add_worksheet('Sheet1')
        row_idx = 0
        col_widths = {}

        for heading, rows in sections:
            if heading:
                level, text = heading
                fmt = fmt_heading if level == 1 else fmt_section
                ws.merge_range(row_idx, 0, row_idx, max(len(rows[0])-1 if rows else 5, 5), text, fmt)
                row_idx += 1

            data_rows = []
            seen_header = None
            for row in rows:
                if seen_header is None:
                    seen_header = row  # first row = header
                elif row == seen_header:
                    continue  # skip duplicate headers
                data_rows.append(row)

            if data_rows:
                # First row is header
                header = data_rows[0]
                for ci, h in enumerate(header):
                    val = cell_value(h)
                    ws.write(row_idx, ci, val, fmt_header)
                    col_widths[ci] = max(col_widths.get(ci, 0), len(str(val)) * 1.2)
                row_idx += 1

                for dr in data_rows[1:]:
                    for ci, cell in enumerate(dr):
                        val = cell_value(cell)
                        ws.write(row_idx, ci, val, fmt_data)
                        col_widths[ci] = max(col_widths.get(ci, 0), min(len(str(val)) * 1.1, 60))
                    row_idx += 1

            row_idx += 1  # blank row between sections

        for ci, w in col_widths.items():
            ws.set_column(ci, ci, min(max(w, 8), 60))

        ws.freeze_panes(1, 0)

    else:
        # Multi-sheet mode: one sheet per section
        first_sheet = True
        sheet_names_used = set()

        for heading, rows in sections:
            if not rows:
                continue

            # Determine sheet name
            if heading:
                name = sanitize_sheet_name(heading[1])
            else:
                name = 'Table'

            # Deduplicate
            base = name
            counter = 1
            while name.lower() in sheet_names_used:
                name = f"{base}_{counter}"
                counter += 1
            sheet_names_used.add(name.lower())

            ws = wb.add_worksheet(name)

            row_idx = 0
            col_widths = {}

            # Section header
            if heading:
                _, text = heading
                ws.merge_range(row_idx, 0, row_idx, max(len(rows[0]) - 1, 5), text, fmt_section)
                row_idx += 1

            # Filter: first row = header, skip duplicate headers and separators
            seen_header = None
            clean_rows = []
            for row in rows:
                # Skip separator-like rows
                if all(re.match(r'^[-:\s]+$', c) for c in row):
                    continue
                if seen_header is None:
                    seen_header = row
                    clean_rows.append(row)
                elif row != seen_header:
                    clean_rows.append(row)

            if clean_rows:
                # Write header
                for ci, h in enumerate(clean_rows[0]):
                    val = cell_value(h)
                    ws.write(row_idx, ci, val, fmt_header)
                    col_widths[ci] = max(col_widths.get(ci, 0), len(str(val)) * 1.2)
                row_idx += 1

                # Write data
                for dr in clean_rows[1:]:
                    for ci, cell in enumerate(dr):
                        val = cell_value(cell)
                        ws.write(row_idx, ci, val, fmt_data)
                        col_widths[ci] = max(col_widths.get(ci, 0), min(len(str(val)) * 1.1, 60))
                    row_idx += 1

            # Set column widths
            for ci, w in col_widths.items():
                ws.set_column(ci, ci, min(max(w, 8), 60))

            ws.freeze_panes(1, 0)

    wb.close()
    return len(sections)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        sys.exit(f"File not found: {input_path}")

    base = os.path.splitext(input_path)[0]
    output_path = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else f"{base}.xlsx"
    one_sheet = '--one-sheet' in sys.argv
    sheet_per_h2 = '--sheet-per-h2' in sys.argv

    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    sections = parse_markdown_tables(lines)

    if not sections:
        sys.exit("No markdown tables found.")

    n = write_excel(sections, output_path, one_sheet=one_sheet, sheet_per_h2=sheet_per_h2)
    print(f"Converted {n} table(s) from '{input_path}' -> '{output_path}'")


if __name__ == '__main__':
    main()
