"""Step 3: Parse quota tables from grid rows → 1D records.

Works directly on grid rows, detecting table boundaries, extracting
quota codes from header, parsing attribute dimensions, and flattening
multi-dimensional data to 1D norms_item records.
"""

import json, re, sys, os
from pathlib import Path
from collections import defaultdict, OrderedDict

QUOTA_CODE_RE = re.compile(r'\b(\d{5})\b')
COST_CODE_RE = re.compile(r'\b(\d{10,12})\b')
WORK_CONTENT_RE = re.compile(r'工程内容[：:]')
UNITS = {'工日', '元', 'kg', 't', 'm', 'm2', 'm3', 'm²', 'm³',
         '台班', '艘班', '组日', '套', '个', '根', '块', '%',
         'km', '10m', '100m', '100m2', '100m3', '10m3', '100m³',
         '片', '只', '条', '张', '吨', '千块', '千根', 'm²', 'm³'}


def find_tables(rows):
    """Find table regions in the grid rows.

    A table starts with:
    - A section title (full-row merge, like "一、人力土方")
    - Optional work content row (full-row merge, like "工程内容：...")
    - A table_header row (A="顺序号", has "定额编号")
    - Optional attr_dimension rows
    - One or more data rows (A=number, B=cost item name)

    Returns list of table dicts.
    """
    tables = []
    current = None
    in_table = False

    for i, row in enumerate(rows):
        cells = row['cells']
        merged = _full_merge_val(cells)

        # Section title: full-row merge starting with Chinese number + "、"
        if merged and re.match(r'^[一二三四五六七八九十]+[、，,]', merged.strip()):
            if in_table and current:
                tables.append(current)
                in_table = False
            current = {
                'row_start': row['row'],
                'section_title': merged.strip(),
                'work_content': '',
                'unit': '',
                'header_row': None,
                'attr_rows': [],
                'data_rows': [],
                'note_rows': [],
                'raw_rows': [row]
            }
            continue

        # Work content row
        if merged and WORK_CONTENT_RE.search(merged) and current:
            current['work_content'] = merged.strip()
            current['raw_rows'].append(row)
            # Extract unit from the end
            parts = merged.strip().split()
            if parts and parts[-1] in UNITS:
                current['unit'] = parts[-1]
            continue

        # Table header
        a_val = str(cells.get('A', '')).strip()
        b_val = str(cells.get('B', '')).strip()
        if a_val == '顺序号' and ('定额编号' in b_val or
                                   '定额编号' in str(cells.get('C', ''))):
            if current is None:
                current = {'row_start': row['row'], 'section_title': '',
                           'work_content': '', 'unit': '',
                           'header_row': None, 'attr_rows': [],
                           'data_rows': [], 'note_rows': [], 'raw_rows': []}
            current['header_row'] = row
            current['raw_rows'].append(row)
            in_table = True
            continue

        # Attribute dimension rows (between header and first data row)
        if in_table and current and current['header_row'] and not current['data_rows']:
            # Check if this is attr row or data row
            if a_val.isdigit() and b_val:
                # This is a data row
                current['data_rows'].append(row)
                current['raw_rows'].append(row)
            else:
                # Check for "序号" or "顺序号" in header-like rows
                if a_val == '顺序号':
                    current['attr_rows'].append(row)
                else:
                    # Could be attr dimension or section continuation
                    current['attr_rows'].append(row)
                current['raw_rows'].append(row)
            continue

        # Data rows
        if in_table and current:
            if a_val.isdigit() and 1 <= int(a_val) <= 500 and b_val:
                current['data_rows'].append(row)
                current['raw_rows'].append(row)
            elif merged and ('注：' in merged or '注:' in merged):
                current['note_rows'].append(row)
                current['raw_rows'].append(row)
            elif merged and '续表' in merged:
                # End current table, "continued" marker
                if current.get('data_rows'):
                    tables.append(current)
                current = None
                in_table = False
            elif merged and re.match(r'^[一二三四五六七八九十]+[、，,]', merged.strip()):
                # New section starts
                if in_table and current:
                    tables.append(current)
                in_table = False
                current = {
                    'row_start': row['row'],
                    'section_title': merged.strip(),
                    'work_content': '', 'unit': '',
                    'header_row': None, 'attr_rows': [],
                    'data_rows': [], 'note_rows': [], 'raw_rows': [row]
                }
            else:
                # Could be attr dim or separation within table
                current['raw_rows'].append(row)
            continue

    if in_table and current:
        tables.append(current)

    return tables


def _full_merge_val(cells):
    vals = [str(v).strip() for v in cells.values()]
    if len(vals) < 2:
        return None
    return vals[0] if all(v == vals[0] for v in vals) else None


def extract_quota_codes(header_cells):
    """Extract quota codes from header row, mapping code → column list."""
    code_cols = OrderedDict()
    for col in sorted(header_cells.keys(), key=lambda c: (len(c), c)):
        sv = str(header_cells[col]).strip()
        m = QUOTA_CODE_RE.search(sv)
        if m:
            code = m.group()
            if code not in code_cols:
                code_cols[code] = []
            code_cols[code].append(col)
    return list(code_cols.items())


def parse_attr_dimensions(attr_rows, code_columns):
    """Parse attribute dimension rows.

    attr_rows: list of row dicts between header and first data row
    code_columns: [(code, [cols]), ...]

    Heuristic:
    - If all values across code columns are the same → this is a label row
    - If values differ per code → this is a value row
    - Label row followed by value row → pair them
    """
    dims = []
    pending_label = None

    for row in attr_rows:
        cells = row['cells']

        # Build per-code values
        code_vals = {}
        for code, cols in code_columns:
            vals = []
            for c in cols:
                v = str(cells.get(c, '')).strip()
                if v and v != '顺序号':
                    vals.append(v)
            if vals:
                code_vals[code] = vals[0]

        if not code_vals:
            continue

        unique = set(code_vals.values())

        if len(unique) == 1 and len(code_vals) >= 2:
            # All columns same → label row
            label = list(unique)[0]
            # Clean: remove leading whitespace, deduplicate
            label = re.sub(r'\s+', '', label)
            if len(label) > 20:
                label = label[:20]
            pending_label = label if label else pending_label
        elif len(unique) > 1:
            # Different values per code → value row
            if pending_label:
                dims.append({
                    'label': pending_label,
                    'values': dict(code_vals)
                })
                pending_label = None
            else:
                # Try to infer label
                inferred = _infer_label(unique)
                dims.append({
                    'label': inferred,
                    'values': dict(code_vals)
                })
        else:
            # Single value, single code — can't determine
            pass

    # If only a pending label remains, it might be the only dimension
    if pending_label and not dims:
        dims.append({'label': pending_label, 'values': {}})

    return dims


def _infer_label(values):
    sample = ' '.join(list(values)[:5])
    if any('类' in v for v in values):
        return '土壤类别'
    if any('级' in v for v in values):
        return '级别'
    if any('冻' in v for v in values):
        return '冻土'
    if any(v.replace('.', '').replace('-', '').isdigit() for v in values if v):
        return '厚度(m)'
    if any(v in ('Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ') for v in values):
        return '类别'
    if any('m' in v for v in values):
        return '尺寸'
    return '属性'


def parse_data_rows(data_rows, code_columns, attr_dims):
    """Parse data rows into 1D records."""
    records = []

    for row in data_rows:
        cells = row['cells']
        seq = str(cells.get('A', '')).strip()
        cost_item = str(cells.get('B', '')).strip()
        c_val = str(cells.get('C', '')).strip()

        if not seq.isdigit() or not cost_item:
            continue

        # Extract unit and cost code from descriptor columns
        unit = ''
        cost_code = ''
        for col in sorted(cells.keys()):
            if _col_ge(col, 'K'):
                break
            sv = str(cells[col]).strip()
            if sv in UNITS and (not unit or sv in ('工日', '元', '%')):
                unit = sv
            m = COST_CODE_RE.search(sv)
            if m:
                cost_code = m.group()

        # If cost_item matches C, C might be the real cost item name
        if cost_item == c_val or not c_val:
            pass
        elif c_val and c_val not in ('定额编号', '项目') and c_val not in UNITS:
            # C has different content from B — might be a category
            pass

        # Generate one record per quota code
        for code, cols in code_columns:
            # Gather attr values for this code
            attr_vals = []
            attr_labels = []
            for dim in attr_dims:
                v = dim.get('values', {}).get(code, '')
                if v:
                    attr_labels.append(dim.get('label', ''))
                    attr_vals.append(v)

            # Get numerical amount
            amount = None
            for c in cols:
                v = str(cells.get(c, '')).strip()
                if v and v not in ('-', '—', '--', '---', '…', '...', ''):
                    try:
                        amount = float(v.strip('()（）'))
                        break
                    except ValueError:
                        pass

            records.append({
                'row': row['row'],
                'sequence': int(seq),
                'quota_code': code,
                'cost_item': cost_item,
                'cost_item_unit': unit,
                'cost_item_code': cost_code,
                'amount': amount,
                'attr_values': attr_vals,
                'attr_labels': attr_labels
            })

    return records


def _col_ge(a, b):
    """Compare column letters: True if a >= b."""
    if len(a) != len(b):
        return len(a) > len(b)
    return a >= b


def parse_grid(grid_path, output_path=None):
    """Main entry: parse all tables from grid JSON."""
    grid_path = Path(grid_path)
    with open(grid_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if output_path is None:
        output_path = grid_path.parent / f'{grid_path.stem.replace("_grid", "")}_parsed.json'

    result = {'file': data.get('file', ''), 'documents': []}

    for sheet_name, sheet_data in data.get('sheets', {}).items():
        rows = sheet_data.get('rows', [])
        print(f'Sheet "{sheet_name}": {len(rows)} rows')

        tables = find_tables(rows)
        print(f'  Found {len(tables)} tables')

        parsed = []
        for t in tables:
            if not t['header_row']:
                continue

            code_columns = extract_quota_codes(t['header_row']['cells'])
            if not code_columns:
                continue

            attr_dims = parse_attr_dimensions(t['attr_rows'], code_columns)
            records = parse_data_rows(t['data_rows'], code_columns, attr_dims)

            # Collect unique quota codes and cost items
            codes = [c for c, _ in code_columns]
            cost_items = list(set(r['cost_item'] for r in records))

            # Extract notes
            notes = []
            for r in t.get('note_rows', []):
                merged = _full_merge_val(r['cells'])
                if merged:
                    notes.append(merged)

            parsed.append({
                'row_range': [t['row_start'], t['data_rows'][-1]['row'] if t['data_rows'] else t['row_start']],
                'section_title': t.get('section_title', ''),
                'work_content': t.get('work_content', ''),
                'unit': t.get('unit', ''),
                'quota_codes': codes,
                'code_columns': {c: cols for c, cols in code_columns},
                'attr_dimensions': attr_dims,
                'cost_items': cost_items,
                'notes': notes,
                'item_count': len(records),
                'items': records
            })

        result['documents'].append({
            'sheet': sheet_name,
            'table_count': len(parsed),
            'total_items': sum(t['item_count'] for t in parsed),
            'tables': parsed
        })

        print(f'  Parsed {len(parsed)} tables, {sum(t["item_count"] for t in parsed)} items')

    output_path = Path(output_path)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    print(f'\nSaved to: {output_path}')
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Parse quota tables from grid')
    ap.add_argument('grid_json', help='Path to _grid.json')
    ap.add_argument('-o', '--output', help='Output parsed JSON path')
    args = ap.parse_args()

    if not os.path.exists(args.grid_json):
        print(f'File not found: {args.grid_json}')
        sys.exit(1)

    parse_grid(args.grid_json, args.output)
