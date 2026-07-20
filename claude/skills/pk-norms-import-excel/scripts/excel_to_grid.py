"""Step 1: Excel XML → fill merged cells → normalized row-grid JSON.

Reads .xlsx directly via zipfile + ElementTree (bypasses openpyxl compatibility issues).
Outputs a clean grid with all merged-cell values propagated.
"""

import zipfile, json, re, sys, os
import defusedxml.ElementTree as ET
from pathlib import Path
from collections import defaultdict

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def parse_shared_strings(z):
    """Extract all shared strings from the xlsx zip."""
    try:
        ss_xml = z.read('xl/sharedStrings.xml')
    except KeyError:
        return []
    root = ET.fromstring(ss_xml)
    strings = []
    for si in root.findall(f'{{{NS}}}si'):
        t = si.find(f'{{{NS}}}t')
        if t is not None:
            strings.append(t.text or '')
        else:
            r_texts = []
            for r_elem in si.findall(f'{{{NS}}}r'):
                rt = r_elem.find(f'{{{NS}}}t')
                if rt is not None and rt.text:
                    r_texts.append(rt.text)
            strings.append(''.join(r_texts) if r_texts else '')
    return strings


def parse_cell_ref(ref):
    m = re.match(r'^([A-Z]+)(\d+)$', ref)
    if not m:
        raise ValueError(f'Invalid cell ref: {ref}')
    return m.group(1), int(m.group(2))


def col_to_num(col):
    n = 0
    for c in col:
        n = n * 26 + (ord(c) - ord('A') + 1)
    return n


def num_to_col(n):
    result = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord('A') + rem) + result
    return result


def parse_sheet_xml(z, sheet_path, strings):
    """Parse a sheet XML into grid dict + merge ranges."""
    sheet_xml = z.read(sheet_path)
    root = ET.fromstring(sheet_xml)

    # Parse all rows (recursive search - rows are inside sheetData)
    grid = {}
    row_count = 0
    for row_elem in root.findall(f'.//{{{NS}}}row'):
        row_count += 1
        for c in row_elem.findall(f'{{{NS}}}c'):
            ref = c.get('r')
            t = c.get('t', '')
            v = c.find(f'{{{NS}}}v')
            value = v.text if v is not None else None
            if t == 's' and value is not None:
                idx = int(value)
                if 0 <= idx < len(strings):
                    value = strings[idx]
                else:
                    value = ''
            if value is not None:
                grid[ref] = value

    # Parse merge cells (recursive search - inside worksheet root)
    merge_ranges = []
    for mc in root.findall(f'.//{{{NS}}}mergeCell'):
        merge_ranges.append(mc.get('ref'))

    return grid, merge_ranges, row_count


def fill_merged_cells(grid, merge_ranges):
    """Propagate top-left cell values across merged ranges."""
    filled = 0
    for mr in merge_ranges:
        parts = mr.split(':')
        src_value = grid.get(parts[0])
        if src_value is None:
            continue
        sc, sr = parse_cell_ref(parts[0])
        ec, er = parse_cell_ref(parts[1])
        sc_n = col_to_num(sc)
        ec_n = col_to_num(ec)
        for r in range(int(sr), int(er) + 1):
            for c in range(sc_n, ec_n + 1):
                cell_ref = f'{num_to_col(c)}{r}'
                if cell_ref not in grid:
                    grid[cell_ref] = src_value
                    filled += 1
    return filled


def build_row_list(grid, max_row):
    """Convert flat grid dict to sorted row list."""
    row_data = defaultdict(dict)
    for ref, val in grid.items():
        col, row = parse_cell_ref(ref)
        if val and val.strip():
            row_data[row][col] = val

    rows = []
    for r in range(1, max_row + 1):
        cells = row_data.get(r, {})
        if cells:
            rows.append({'row': r, 'cells': dict(sorted(cells.items(),
                              key=lambda x: (len(x[0]), x[0])))})
    return rows


REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'


def get_sheet_names(z):
    """Parse workbook.xml for sheet names."""
    wb_xml = z.read('xl/workbook.xml')
    root = ET.fromstring(wb_xml)
    sheets = []
    for s in root.findall(f'.//{{{NS}}}sheet'):
        rid = s.get(f'{{{REL_NS}}}id')
        if rid is None:
            rid = s.get(f'{{{NS_R}}}id')
        sheets.append({
            'name': s.get('name'),
            'sheetId': s.get('sheetId'),
            'state': s.get('state', 'visible'),
            'rId': rid
        })
    return sheets


def get_sheet_path(z, rId):
    """Resolve rId to actual path via rels."""
    if rId is None:
        return None
    try:
        rels_xml = z.read('xl/_rels/workbook.xml.rels')
    except KeyError:
        return f'xl/worksheets/sheet{rId[-1]}.xml'
    root = ET.fromstring(rels_xml)
    for rel in root.findall(f'.//{{{REL_NS}}}Relationship'):
        if rel.get('Id') == rId:
            return 'xl/' + rel.get('Target')
    return None


def extract(path, output=None, max_rows=None):
    """Main entry: extract Excel to grid JSON."""
    path = Path(path)
    if output is None:
        output = path.parent / f'{path.stem}_grid.json'

    with zipfile.ZipFile(path, 'r') as z:
        strings = parse_shared_strings(z)
        print(f'Shared strings: {len(strings)}')

        sheets = get_sheet_names(z)
        result = {'file': str(path.resolve()), 'sheets': {}}

        for sheet_info in sheets:
            sheet_path = get_sheet_path(z, sheet_info['rId'])
            if sheet_path is None:
                continue
            print(f'Processing sheet: {sheet_info["name"]} ({sheet_path})')

            grid, merge_ranges, row_count = parse_sheet_xml(z, sheet_path, strings)
            print(f'  Rows: {row_count}, Non-empty cells: {len(grid)}, '
                  f'Merged ranges: {len(merge_ranges)}')

            filled = fill_merged_cells(grid, merge_ranges)
            print(f'  Filled {filled} cells from merged ranges')

            rows = build_row_list(grid, row_count)
            if max_rows:
                rows = rows[:max_rows]

            # Determine column range
            all_cols = set()
            for r in rows:
                all_cols.update(r['cells'].keys())
            max_col_letter = max(all_cols, key=lambda x: (len(x), x)) if all_cols else 'A'

            result['sheets'][sheet_info['name']] = {
                'total_rows': row_count,
                'content_rows': len(rows),
                'merged_cells': len(merge_ranges),
                'filled_cells': filled,
                'columns': f'A:{max_col_letter}',
                'rows': rows
            }

    output = Path(output)
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    print(f'\nSaved to: {output}')
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Excel → grid JSON with merge cell filling')
    ap.add_argument('file', help='Path to .xlsx file')
    ap.add_argument('-o', '--output', help='Output JSON path (default: same dir, _grid.json)')
    ap.add_argument('--max-rows', type=int, help='Limit output rows')
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f'File not found: {args.file}')
        sys.exit(1)

    extract(args.file, args.output, args.max_rows)
