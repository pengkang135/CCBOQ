"""
BOQ merge — fastexcel values + openpyxl styles → xlsxwriter output.
Finds BOQ item tables (sheets with description + unit + quantity columns) and merges them.
Preserves original column structure, headers, and per-cell fill/font annotation.
Columns align by header name, so narrow sheets missing a column still line up.
Creates temp copy to protect original file. Detects hidden rows.
Usage: python merge_boq.py <source.xlsx> [-o out.xlsx] [--sheet-regex PATTERN] [--skip PATTERN] [--delete-hidden-rows]

Output: original columns and cell colours preserved, L1 【sheet name】 markers
injected between sheets.
"""
import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fastexcel
import numpy as np
import openpyxl
import xlsxwriter

# External link cleaner — import from sibling skill
_sys_path = Path(__file__).resolve().parents[2] / "xlsx-purge" / "scripts"
if str(_sys_path) not in sys.path:
    sys.path.insert(0, str(_sys_path))
from xlsx_purge import purge

FONT_NAME = "Microsoft YaHei UI"
FONT_COLOR = "#1A1A1A"
HEADER_FILL = "#1F4E79"
NUM_FORMAT = '#,##0.00'
L1_FILL = "#C6D9F1"

DEFAULT_SHEET_RE = r"^SCHED(?:ULE)?[\.\s]"
# Lump-sum sheets (preliminaries, provisional sums) are description+amount, and so
# are collection/summary sheets — the difference is only in the sheet name, so these
# patterns are the sole guard against double-counting a total.
DEFAULT_SKIP_PATTERNS = [
    "SUMMARY", "LIST", "COLLECTION", "GRAND TOTAL",
    "汇总", "总计",
]

# Headers that mean "the money column". A lump-sum sheet calls it Amount, a
# measured sheet calls it Total Price; both must land in the same output column.
AMOUNT_ALIASES = frozenset({
    "amount", "total", "sum", "total price", "total amount", "total cost",
    "amt", "price", "金额", "合价", "总价", "总额",
})
REMOVE_RE = re.compile(
    r"^\s*(SUBTOTAL|TOTAL|% COST|CARRIED|BROUGHT|DITTO|PAGE\s*TOTAL)\b",
    re.IGNORECASE,
)
EXCEL_ERRORS = frozenset({"#REF!", "#VALUE!", "#N/A", "#DIV/0!", "#NAME?", "#NULL!"})
PAGE_NUMBERS = frozenset({"1/1", "2/2", "1/2", "1/3", "1/4"})


def cell_str(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    return str(val).strip()


def row_all_empty(row_vals, max_col):
    for i in range(max_col):
        if cell_str(row_vals[i]):
            return False
    return True


def is_header_row(val_a, val_b):
    return val_a == "Ref." and "Item" in val_b


def is_boq_sheet(name, sheet_re, skip_patterns):
    if not re.search(sheet_re, name, re.IGNORECASE):
        return False
    for pat in skip_patterns:
        if pat.lower() in name.lower():
            return False
    return True


def _is_amount_header(norm_name):
    return norm_name in AMOUNT_ALIASES


def classify_sheet(df, n_rows, n_cols):
    """Decide whether a sheet is a BOQ table, and of which kind.

    "items"   — description + unit + quantity: measured work, the classic case.
    "lumpsum" — description + amount but no unit/quantity: preliminaries,
                provisional sums, day works. These carry a name and a total
                price only, and must still be merged.

    Returns (kind, header_row_index), or (None, None) if the sheet is neither.
    "items" is tested first so a measured sheet (which also has an amount
    column) is never mistaken for a lump-sum one."""
    for r in range(min(10, n_rows)):
        vals = [_norm_header(df.iloc[r, c]) for c in range(n_cols)]
        has_desc = any("item" in v or "description" in v for v in vals)
        has_qty = any(v in ("quantity", "qty") for v in vals)
        has_unit = any(v == "unit" for v in vals)
        has_amount = any(_is_amount_header(v) for v in vals)
        if has_desc and has_qty and has_unit:
            return "items", r
        if has_desc and has_amount:
            return "lumpsum", r
    return None, None


def get_boq_col_indices(df, header_row, n_cols):
    """Get column indices for description, unit, quantity and amount from header.
    Returns 0-based original column indices; any of them may be None."""
    vals_lower = [_norm_header(df.iloc[header_row, c]) for c in range(n_cols)]
    desc_col = unit_col = qty_col = amount_col = None
    for c, v in enumerate(vals_lower):
        if ("description" in v or "desc" in v) and desc_col is None:
            desc_col = c
    if desc_col is None:
        for c, v in enumerate(vals_lower):
            if "item" in v:
                desc_col = c
                break
    for c, v in enumerate(vals_lower):
        if v == "unit":
            unit_col = c
            break
    for c, v in enumerate(vals_lower):
        if v in ("quantity", "qty"):
            qty_col = c
            break
    for c, v in enumerate(vals_lower):
        if _is_amount_header(v):
            amount_col = c
            break
    return desc_col, unit_col, qty_col, amount_col


def _try_number(val):
    """Convert string to float if possible. Returns (is_numeric, value)."""
    if isinstance(val, (int, float)):
        return True, float(val)
    if isinstance(val, str):
        s = val.strip().replace(',', '')
        try:
            return True, float(s)
        except ValueError:
            return False, val
    return False, val


REF_CODE_RE = re.compile(r"^[A-Za-z]?\d+(\.\d+)*[a-z]?$")


def get_header_rows(df, main_header_row, n_rows, n_cols):
    """Return all header rows (main + sub-header if present).

    A real sub-header is a strip that labels columns — a currency row (THB /
    Baht), a column-numbering row ((1) (2) (3)). It must be told apart from two
    things that both sit in the same position and must NOT be absorbed:

      - a section title, which fills the description column alone
      - the first data row, which is what appears there when a sheet has no
        section titles at all (typical of preliminaries and provisional sums)

    So a sub-header must span two or more columns (excludes the section title),
    carry no BOQ column keywords, and show neither a long description nor an
    item reference code (excludes the data row)."""
    header_rows = []
    main_hdr = [cell_str(df.iloc[main_header_row, c]) for c in range(n_cols)]
    header_rows.append(main_hdr)

    next_row = main_header_row + 1
    if next_row < n_rows:
        vals = [cell_str(df.iloc[next_row, c]) for c in range(n_cols)]
        vals_lower = [v.lower() for v in vals]
        spans_columns = sum(1 for v in vals_lower if v) >= 2
        has_keywords = any(
            kw in v for v in vals_lower
            for kw in ("item", "unit", "quantity", "qty", "description")
        )

        desc_col, _, _, _ = get_boq_col_indices(df, main_header_row, n_cols)
        desc_text = vals[desc_col] if desc_col is not None and desc_col < n_cols else ""
        ref_text = vals[0] if n_cols else ""
        looks_like_data = len(desc_text) > 6 or bool(REF_CODE_RE.match(ref_text))

        if spans_columns and not has_keywords and not looks_like_data:
            header_rows.append(vals)

    return header_rows


def find_data_start(df, n_rows, n_cols, header_row, num_header_rows):
    """Find first content row after all header rows + blank rows + schedule title row."""
    start = header_row + num_header_rows
    while start < n_rows:
        val_b = cell_str(df.iloc[start, 1]) if n_cols > 1 else ""
        if row_all_empty(df.iloc[start].values, n_cols):
            start += 1
        elif "SCHEDULE" in val_b.upper():
            start += 1
        else:
            break
    return start


def _style_key(cell):
    """Reduce a source cell's visual style to a hashable key, or None if plain.

    Only the attributes people actually annotate a BOQ with are captured —
    fill colour, font colour, bold, italic. Keeping the key small keeps the
    xlsxwriter format pool to a few dozen objects instead of one per cell."""
    bg = None
    fill = cell.fill
    if fill is not None and fill.fill_type == "solid":
        rgb = fill.start_color.rgb
        if isinstance(rgb, str) and len(rgb) == 8 and rgb[2:].upper() not in ("FFFFFF", "000000"):
            bg = "#" + rgb[2:]

    fg = None
    bold = italic = False
    font = cell.font
    if font is not None:
        bold = bool(font.bold)
        italic = bool(font.italic)
        if font.color is not None:
            rgb = font.color.rgb
            if isinstance(rgb, str) and len(rgb) == 8 and rgb[2:].upper() not in ("000000", "FFFFFF"):
                fg = "#" + rgb[2:]

    if bg is None and fg is None and not bold and not italic:
        return None
    return (bg, fg, bold, italic)


def read_cell_styles(filepath, sheet_names):
    """Collect per-cell style keys for the qualifying sheets.

    Keyed by 0-based (row, col) so it lines up with the fastexcel frame, which
    is why sheets must be loaded with header_row=None. read_only keeps this
    cheap — styles come from the shared styles table, not a full cell parse."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    styles = {}
    for name in sheet_names:
        if name not in wb.sheetnames:
            continue
        sheet_styles = {}
        for r_idx, row in enumerate(wb[name].iter_rows()):
            for c_idx, cell in enumerate(row):
                key = _style_key(cell)
                if key is not None:
                    sheet_styles[(r_idx, c_idx)] = key
        styles[name] = sheet_styles
    wb.close()
    return styles


def make_fmt_pool(out_wb):
    """Format factory that reuses one xlsxwriter Format per distinct style."""
    cache = {}

    def fmt_for(style_key, is_num):
        ck = (style_key, is_num)
        if ck in cache:
            return cache[ck]
        props = {
            'font_name': FONT_NAME, 'font_color': FONT_COLOR,
            'font_size': 9, 'valign': 'vcenter',
        }
        if is_num:
            props['num_format'] = NUM_FORMAT
        if style_key is not None:
            bg, fg, bold, italic = style_key
            if bg:
                props['bg_color'] = bg
            if fg:
                props['font_color'] = fg
            if bold:
                props['bold'] = True
            if italic:
                props['italic'] = True
        fmt = out_wb.add_format(props)
        cache[ck] = fmt
        return fmt

    return fmt_for, cache


def identify_qualifying(reader, sheet_re, skip_patterns):
    """Find the BOQ sheets and derive the header template from the widest one.

    Both measured sheets ("items") and lump-sum sheets ("lumpsum": preliminaries,
    provisional sums) qualify. The template comes from the widest sheet, which is
    a measured one whenever the workbook has any, so its headers cover every
    column a lump-sum sheet could need to map onto.

    Sheets load with header_row=None so the frame's row index equals the real
    Excel row index, which the style map relies on. Returns None if nothing
    qualifies. Must be re-run after any row deletion — every row number moves."""
    candidates = [n for n in reader.sheet_names if is_boq_sheet(n, sheet_re, skip_patterns)]

    qualifying = []  # [(sheet_name, header_row, width, num_header_rows, kind)]
    for name in candidates:
        sheet = reader.load_sheet_by_name(name, header_row=None)
        df = sheet.to_pandas()
        n_rows = len(df)
        width = sheet.width
        kind, hdr_row = classify_sheet(df, n_rows, width)
        if kind is not None:
            hdr_rows = get_header_rows(df, hdr_row, n_rows, width)
            qualifying.append((name, hdr_row, width, len(hdr_rows), kind))

    if not qualifying:
        return None

    # Header template = widest qualifying sheet, so its headers cover every column
    hdr_sheet_name, hdr_row, n_cols, num_header_rows, _ = max(qualifying, key=lambda q: q[2])
    hdr_sheet = reader.load_sheet_by_name(hdr_sheet_name, header_row=None)
    hdr_df = hdr_sheet.to_pandas()
    header_rows = get_header_rows(hdr_df, hdr_row, len(hdr_df), n_cols)
    desc_col_idx, unit_col_idx, qty_col_idx, amount_col_idx = get_boq_col_indices(
        hdr_df, hdr_row, n_cols
    )

    return {
        "qualifying": qualifying,
        "hdr_sheet_name": hdr_sheet_name,
        "n_cols": n_cols,
        "num_header_rows": num_header_rows,
        "header_rows": header_rows,
        "template_hdr": header_rows[0],
        "desc_col": desc_col_idx,
        "unit_col": unit_col_idx,
        "qty_col": qty_col_idx,
        "amount_col": amount_col_idx,
    }


def detect_hidden_rows(filepath, sheet_names):
    """Detect hidden rows in specified sheets using openpyxl.
    Returns {sheet_name: [1-based row numbers]} for sheets that have hidden rows."""
    wb = openpyxl.load_workbook(filepath)
    hidden = {}
    for name in sheet_names:
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        hidden_rows = []
        for r in range(1, ws.max_row + 1):
            if ws.row_dimensions[r].hidden:
                hidden_rows.append(r)
        if hidden_rows:
            hidden[name] = hidden_rows
    wb.close()
    return hidden


def get_header_merges(filepath, sheet_name, num_header_rows, n_cols):
    """Extract merge patterns from original headers using openpyxl.
    Finds the main header row by locating 'Item' in column A of the first rows."""
    wb = openpyxl.load_workbook(filepath)
    ws = wb[sheet_name]

    # Find main header row (the row containing "Item" in column A)
    hdr_row_1b = None
    for row in range(1, min(ws.max_row + 1, 20)):
        val = ws.cell(row=row, column=1).value
        if val and "item" in str(val).lower():
            hdr_row_1b = row
            break

    if hdr_row_1b is None:
        wb.close()
        return []

    hdr_row = hdr_row_1b - 1  # 0-based
    hdr_end = hdr_row + num_header_rows - 1

    h_merges = []  # (out_row, c1, out_row, c2)
    v_cols = set()

    for mc in ws.merged_cells.ranges:
        r1 = mc.min_row - 1
        r2 = mc.max_row - 1
        c1 = mc.min_col - 1
        c2 = mc.max_col - 1

        if c2 >= n_cols:
            continue
        if r1 > hdr_end or r2 < hdr_row:
            continue

        if r1 == r2:
            out_r = r1 - hdr_row
            h_merges.append((out_r, c1, out_r, c2))
        elif r1 >= hdr_row:
            for c in range(c1, c2 + 1):
                v_cols.add(c)

    wb.close()

    merges = list(h_merges)
    for c in sorted(v_cols):
        if num_header_rows > 1:
            merges.append((0, c, num_header_rows - 1, c))

    return merges


def _norm_header(val):
    return re.sub(r"\s+", " ", cell_str(val)).lower()


def build_col_map(sheet_hdr, template_hdr):
    """Align a sheet's columns onto the template columns by header name.

    Sheets vary in width and in wording — a narrow sheet may lack the
    Specifications column, and a lump-sum sheet calls its money column Amount
    where the template says Total Price. Matching on header text keeps
    Unit / Quantity / Total Price aligned whichever columns are absent, which
    positional arithmetic cannot do without hardcoding a column order.

    Three passes: exact header text, then synonym group, then position. Exact
    wins so a template with both Amount and Total keeps its own columns apart.
    Returns a list of 0-based template indices, one per source column."""
    tpl = [_norm_header(v) for v in template_hdr]
    n_tpl = len(tpl)
    keys = [_norm_header(v) for v in sheet_hdr]
    col_map = [None] * len(sheet_hdr)
    used = set()

    # Pass 1: identical header text
    for c, key in enumerate(keys):
        if not key:
            continue
        for t, tname in enumerate(tpl):
            if tname == key and t not in used:
                col_map[c] = t
                used.add(t)
                break

    # Pass 2: synonym group — Amount ≡ Total ≡ Total Price
    for c, key in enumerate(keys):
        if col_map[c] is not None or not _is_amount_header(key):
            continue
        for t, tname in enumerate(tpl):
            if _is_amount_header(tname) and t not in used:
                col_map[c] = t
                used.add(t)
                break

    # Pass 3: blank or unrecognised header — hold its own position if still free
    for c in range(len(sheet_hdr)):
        if col_map[c] is not None:
            continue
        if c < n_tpl and c not in used:
            dst = c
        else:
            free = [i for i in range(n_tpl) if i not in used]
            # Template is the widest sheet, so a free slot always exists;
            # falling back to c keeps col_map aligned with the source columns.
            dst = free[0] if free else c
        col_map[c] = dst
        used.add(dst)

    return col_map


def delete_hidden_rows_from_sheets(filepath, sheet_names):
    """Delete hidden rows from specified sheets in-place on the temp copy.
    Returns total number of rows deleted."""
    wb = openpyxl.load_workbook(filepath)
    total = 0
    for name in sheet_names:
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        rows_to_delete = []
        for r in range(1, ws.max_row + 1):
            if ws.row_dimensions[r].hidden:
                rows_to_delete.append(r)
        for r in reversed(rows_to_delete):
            ws.delete_rows(r)
        total += len(rows_to_delete)
    if total > 0:
        wb.save(filepath)
    wb.close()
    return total


def merge(source_path, output_path=None, sheet_re=None, skip_patterns=None, delete_hidden_rows=False):
    sheet_re = sheet_re or DEFAULT_SHEET_RE
    skip_patterns = skip_patterns or DEFAULT_SKIP_PATTERNS
    source = Path(source_path)
    out_path = Path(output_path) if output_path else (
        source.parent / f"({datetime.now().strftime('%Y-%m-%d')} Merge){source.stem}.xlsx"
    )

    # Phase 0: Temp copy to protect original file
    temp_dir = source.parent / "temp"
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"_merge_temp_{source.stem}.xlsx"
    print(f"Creating temp copy: {temp_path.name}")
    shutil.copy2(source, temp_path)

    try:
        # Phase 0.5: Identify qualifying BOQ sheets (desc + unit + qty columns)
        reader = fastexcel.read_excel(str(temp_path))
        meta = identify_qualifying(reader, sheet_re, skip_patterns)
        if meta is None:
            print("No qualifying BOQ sheets found "
                  "(need description + unit + quantity, or description + amount).")
            sys.exit(1)

        print(f"\nQualifying BOQ sheets ({len(meta['qualifying'])}):")
        for sname, _, _, _, kind in meta["qualifying"]:
            label = "measured" if kind == "items" else "lump sum"
            print(f"  - [{label}] {sname}")

        # Phase 0.6: Hidden row detection on qualifying sheets
        qualifying_names = [q[0] for q in meta["qualifying"]]
        hidden = detect_hidden_rows(str(temp_path), qualifying_names)
        if hidden:
            total_hidden = sum(len(rows) for rows in hidden.values())
            print(f"\n!!! Hidden rows detected: {total_hidden} rows across {len(hidden)} sheet(s):")
            for sname, rows in hidden.items():
                preview = rows[:10]
                suffix = "..." if len(rows) > 10 else ""
                print(f"  - {sname}: {len(rows)} hidden rows (rows: {preview}{suffix})")
            if delete_hidden_rows:
                deleted = delete_hidden_rows_from_sheets(str(temp_path), list(hidden.keys()))
                print(f"Deleted {deleted} hidden rows from temp copy.")
                # Deleting rows shifts every row number — header rows, data starts
                # and the style map must all be recomputed against the new file
                reader = fastexcel.read_excel(str(temp_path))
                meta = identify_qualifying(reader, sheet_re, skip_patterns)
                if meta is None:
                    print("No qualifying BOQ sheets left after deleting hidden rows.")
                    sys.exit(1)
                qualifying_names = [q[0] for q in meta["qualifying"]]
            else:
                print("\n*** ACTION REQUIRED ***")
                print("Hidden rows found in source sheets.")
                print("Re-run with --delete-hidden-rows to delete them and continue.")
                print(f"Temp copy preserved at: {temp_path}")
                sys.exit(1)

        qualifying = meta["qualifying"]
        hdr_sheet_name = meta["hdr_sheet_name"]
        n_cols = meta["n_cols"]
        num_header_rows = meta["num_header_rows"]
        header_rows = meta["header_rows"]
        template_hdr = meta["template_hdr"]
        desc_col_idx = meta["desc_col"]
        unit_col_idx = meta["unit_col"]
        qty_col_idx = meta["qty_col"]
        amount_col_idx = meta["amount_col"]

        # Extract header merge patterns from the header template sheet
        hdr_merges = get_header_merges(
            str(temp_path), hdr_sheet_name, num_header_rows, n_cols
        )

        # Source cell styles — fill colour and font emphasis are human annotation
        # (flagged-for-review, anomaly, section colouring) and must reach the output
        print("Reading source cell styles...", end=" ", flush=True)
        all_styles = read_cell_styles(str(temp_path), qualifying_names)
        print(f"{sum(len(s) for s in all_styles.values())} styled cells found.")

        # Phase 1: Extract data rows from each qualifying sheet
        # Three-pass approach: read all → forward-fill merged cells → filter
        all_sheet_data = []  # [(sheet_name, [(values, styles), ...], qty_sum, amount_sum)]

        for sname, hdr_row, sheet_width, n_hdr_rows, kind in qualifying:
            print(f"  Reading: {sname}...", end=" ", flush=True)
            sheet = reader.load_sheet_by_name(sname, header_row=None)
            df = sheet.to_pandas()
            n_rows = len(df)
            sheet_styles = all_styles.get(sname, {})

            sheet_hdr = [cell_str(df.iloc[hdr_row, c]) for c in range(sheet_width)]
            col_map = build_col_map(sheet_hdr, template_hdr)

            # This sheet's own column positions. Control totals are summed from
            # these against the untouched source row, never from the mapped row —
            # otherwise a wrong col_map corrupts both sides equally and the
            # cross-validation passes while the data is misplaced.
            _, s_unit_col, s_qty_col, s_amount_col = get_boq_col_indices(
                df, hdr_row, sheet_width
            )

            data_start = find_data_start(df, n_rows, sheet_width, hdr_row, n_hdr_rows)

            # ── Pass 1: read all rows, minimal filtering ──────────────
            # Style travels with the value through the same column mapping, so a
            # narrow sheet's colours land under the right output column too.
            raw_rows = []
            for r in range(data_start, n_rows):
                row_vals = df.iloc[r].values
                if row_all_empty(row_vals, sheet_width):
                    continue
                row_data = [None] * n_cols
                row_style = [None] * n_cols
                for c in range(sheet_width):
                    dst = col_map[c]
                    val = row_vals[c]
                    if val is not None and not (isinstance(val, float) and np.isnan(val)):
                        row_data[dst] = val
                    # A blank cell can still carry a fill — keep its style either way
                    style = sheet_styles.get((r, c))
                    if style is not None:
                        row_style[dst] = style
                # The raw source row rides along for independent total-summing
                raw_rows.append([row_data, row_style, row_vals])

            # ── Pass 2: forward-fill description column only ──────
            # Vertically merged cells in source appear as empty in fastexcel.
            # Only fill the description/name column — other columns must not
            # be forward-filled, as that would incorrectly propagate values.
            last_val = None
            for row_data, _, _ in raw_rows:
                if row_data[desc_col_idx] is not None:
                    last_val = row_data[desc_col_idx]
                elif last_val is not None:
                    row_data[desc_col_idx] = last_val

            # ── Pass 3: remove unwanted rows ──────────────────────────
            sheet_rows = []
            sheet_qty_sum = 0.0
            sheet_amount_sum = 0.0
            for row_data, row_style, src_vals in raw_rows:
                val_a = cell_str(row_data[0])
                val_b = cell_str(row_data[1]) if n_cols > 1 else ""

                if val_a in EXCEL_ERRORS or val_b in EXCEL_ERRORS:
                    continue
                if is_header_row(val_a, val_b):
                    continue
                if val_b and "SCHEDULE NO." in val_b.upper():
                    continue
                if REMOVE_RE.search(val_a) or REMOVE_RE.search(val_b):
                    continue
                if val_a.strip() in PAGE_NUMBERS:
                    continue
                if "DATA ZONE" in val_a.upper() or "DATA ZONE" in val_b.upper():
                    continue

                sheet_rows.append((row_data, row_style))

                # Control totals, read straight off the source row. Quantity only
                # counts measured items (unit + qty both present); amount counts
                # every row carrying one, which is the only figure a lump-sum
                # sheet can be validated against.
                ru = cell_str(src_vals[s_unit_col]) if s_unit_col is not None and s_unit_col < sheet_width else ""
                rq = cell_str(src_vals[s_qty_col]) if s_qty_col is not None and s_qty_col < sheet_width else ""
                if ru and rq:
                    is_num, num_val = _try_number(rq)
                    if is_num:
                        sheet_qty_sum += num_val
                ra = cell_str(src_vals[s_amount_col]) if s_amount_col is not None and s_amount_col < sheet_width else ""
                if ra:
                    is_num, num_val = _try_number(ra)
                    if is_num:
                        sheet_amount_sum += num_val

            print(f"{len(sheet_rows)} rows "
                  f"(qty: {sheet_qty_sum:,.2f}  amount: {sheet_amount_sum:,.2f})")
            all_sheet_data.append((sname, sheet_rows, sheet_qty_sum, sheet_amount_sum))

        total_data = sum(len(rows) for _, rows, _, _ in all_sheet_data)
        source_qty_total = sum(q for _, _, q, _ in all_sheet_data)
        source_amount_total = sum(a for _, _, _, a in all_sheet_data)
        print(f"\nTotal: {total_data} data rows from {len(all_sheet_data)} sheets")
        print(f"Source grand totals — qty: {source_qty_total:,.2f}  "
              f"amount: {source_amount_total:,.2f}")

        # Phase 2: Write xlsxwriter
        # Output has one extra column: "No." at position 0
        out_n_cols = n_cols + 1
        out_wb = xlsxwriter.Workbook(str(out_path), {'constant_memory': False})
        out_ws = out_wb.add_worksheet("MergeSheet")

        header_fmt = out_wb.add_format({
            'font_name': FONT_NAME, 'bold': True, 'font_color': '#FFFFFF',
            'bg_color': HEADER_FILL, 'align': 'center', 'valign': 'vcenter',
            'text_wrap': True, 'font_size': 10,
            'border': 1, 'border_color': '#FFFFFF',
        })
        l1_fmt = out_wb.add_format({
            'font_name': FONT_NAME, 'font_color': FONT_COLOR, 'bold': True,
            'font_size': 10, 'bg_color': L1_FILL, 'valign': 'vcenter',
        })
        no_fmt = out_wb.add_format({
            'font_name': FONT_NAME, 'font_color': FONT_COLOR,
            'font_size': 9, 'valign': 'vcenter', 'align': 'center',
        })
        # Data formats come from a pool keyed on the source cell's style, so an
        # annotated cell keeps its colour and a plain one costs no extra object.
        fmt_for, fmt_cache = make_fmt_pool(out_wb)

        # Write headers: merge_range handles merged cells; write non-merged cells directly.
        # Build set of cells covered by merge ranges (shifted +1 for No. column)
        merged_cells = set()
        for r1, c1, r2, c2 in hdr_merges:
            for r in range(r1, r2 + 1):
                for c in range(c1 + 1, c2 + 2):  # +1 for No. column
                    merged_cells.add((r, c))

        for hi in range(num_header_rows):
            out_ws.set_row(hi, 28)

        if num_header_rows > 1:
            out_ws.merge_range(0, 0, num_header_rows - 1, 0, "No.", header_fmt)
        else:
            out_ws.write(0, 0, "No.", header_fmt)

        for hi, hdr_vals in enumerate(header_rows):
            for ci, hdr in enumerate(hdr_vals):
                if (hi, ci + 1) not in merged_cells:
                    out_ws.write(hi, ci + 1, hdr if hdr else "", header_fmt)

        for r1, c1, r2, c2 in hdr_merges:
            val = header_rows[r1][c1] if r1 < len(header_rows) and c1 < len(header_rows[r1]) else ""
            out_ws.merge_range(r1, c1 + 1, r2, c2 + 1, val if val else "", header_fmt)

        # Data rows with L1 markers
        xl_row = num_header_rows
        for sname, sheet_rows, _, _ in all_sheet_data:
            # L1 【sheet name】 row
            out_ws.set_row(xl_row, 22)
            for ci in range(out_n_cols):
                out_ws.write(xl_row, ci, "", l1_fmt)
            # Same column the validator reads the marker back from
            out_ws.write(xl_row, desc_col_idx + 1, f"【{sname}】", l1_fmt)
            xl_row += 1

            # Content rows
            for row_data, row_style in sheet_rows:
                out_ws.set_row(xl_row, 16)

                # Priceable-item check. A measured item has unit + quantity;
                # a lump-sum item (preliminaries, provisional sum) has neither but
                # does carry an amount. Both get a sequence number.
                # Secondary rows (vertically merged) may have empty desc but valid unit+qty.
                row_desc = cell_str(row_data[desc_col_idx]) if desc_col_idx is not None and desc_col_idx < len(row_data) else ""
                row_unit = cell_str(row_data[unit_col_idx]) if unit_col_idx is not None and unit_col_idx < len(row_data) else ""
                row_qty = cell_str(row_data[qty_col_idx]) if qty_col_idx is not None and qty_col_idx < len(row_data) else ""
                row_amount = cell_str(row_data[amount_col_idx]) if amount_col_idx is not None and amount_col_idx < len(row_data) else ""
                is_boq_item = (bool(row_unit) and bool(row_qty)) or bool(row_amount)

                if is_boq_item:
                    out_ws.write_formula(xl_row, 0, f'=COUNT($A$1:A{xl_row})+1', no_fmt)
                else:
                    out_ws.write_blank(xl_row, 0, None, no_fmt)

                for ci in range(min(len(row_data), n_cols)):
                    val = row_data[ci]
                    style = row_style[ci]
                    if val is None:
                        # Blank but styled — write the fill so the annotation survives
                        if style is not None:
                            out_ws.write_blank(xl_row, ci + 1, None, fmt_for(style, False))
                        continue
                    is_num, num_val = _try_number(val)
                    if is_num:
                        out_ws.write(xl_row, ci + 1, num_val, fmt_for(style, True))
                    else:
                        out_ws.write(xl_row, ci + 1, str(val), fmt_for(style, False))
                xl_row += 1

        # Column widths (out_n_cols = n_cols + 1)
        out_ws.set_column(0, 0, 5)    # No.
        out_ws.set_column(1, 1, 8)    # Ref
        out_ws.set_column(2, 2, 45)   # Description
        out_ws.set_column(3, 3, 28)   # 描述
        out_ws.set_column(4, 4, 6)    # Unit
        out_ws.set_column(5, 5, 8)    # Qty
        if out_n_cols > 6:
            out_ws.set_column(6, out_n_cols - 1, 14)
        out_ws.freeze_panes(num_header_rows, 0)
        out_ws.autofilter(0, 0, xl_row - 1, out_n_cols - 1)
        out_wb.close()

        # Phase 3: Cross-validate — compare per-sheet qty sums vs output section qty sums
        print(f"\nOutput: {out_path}")
        print(f"Size: {out_path.stat().st_size / 1024:.1f} KB")

        # Read output with fastexcel, sum qty per L1 section.
        # header_row=None keeps the frame indexed by real row number; header rows
        # are harmless here because sectioning only starts at an L1【】marker.
        out_reader = fastexcel.read_excel(str(out_path))
        out_sheet = out_reader.load_sheet(0, header_row=None)
        out_df = out_sheet.to_pandas()
        out_n_rows = len(out_df)
        # +1 for the "No." column in output. A workbook of only lump-sum sheets
        # has no quantity column at all, so these stay None.
        out_qty_col = qty_col_idx + 1 if qty_col_idx is not None else None
        out_amount_col = amount_col_idx + 1 if amount_col_idx is not None else None

        # {section_name: (qty_sum, amount_sum)} — amount is the only control total
        # a lump-sum section has, so both are tracked for every section
        out_section_sums = {}
        current_section = None
        section_qty = 0.0
        section_amount = 0.0

        for r in range(out_n_rows):
            row_vals = [cell_str(out_df.iloc[r, c]) for c in range(out_n_cols)]
            # Detect L1【section】marker in the description column
            l1_marker = row_vals[desc_col_idx + 1] if desc_col_idx + 1 < len(row_vals) else ""
            if l1_marker.startswith("【") and l1_marker.endswith("】"):
                if current_section is not None:
                    out_section_sums[current_section] = (section_qty, section_amount)
                current_section = l1_marker[1:-1]  # strip 【】
                section_qty = 0.0
                section_amount = 0.0
                continue

            if current_section is None:
                continue

            ru = row_vals[unit_col_idx + 1] if unit_col_idx is not None and unit_col_idx + 1 < len(row_vals) else ""
            rq = row_vals[out_qty_col] if out_qty_col is not None and out_qty_col < len(row_vals) else ""
            if ru and rq:
                is_num, num_val = _try_number(rq)
                if is_num:
                    section_qty += num_val

            ra = row_vals[out_amount_col] if out_amount_col is not None and out_amount_col < len(row_vals) else ""
            if ra:
                is_num, num_val = _try_number(ra)
                if is_num:
                    section_amount += num_val

        if current_section is not None:
            out_section_sums[current_section] = (section_qty, section_amount)

        out_qty_total = sum(q for q, _ in out_section_sums.values())
        out_amount_total = sum(a for _, a in out_section_sums.values())

        # ── Print comparison table ──
        # Both totals are shown per section: a measured section is proven by its
        # quantity, a lump-sum section only by its amount.
        print(f"\n{'='*94}")
        print(f"  CROSS-VALIDATION")
        print(f"{'='*94}")
        print(f"  {'Sheet/Section':<30} {'Src Qty':>12} {'Out Qty':>12} "
              f"{'Src Amount':>14} {'Out Amount':>14} {'Status':>6}")
        print(f"  {'-'*30} {'-'*12} {'-'*12} {'-'*14} {'-'*14} {'-'*6}")

        all_pass = True
        for sname, _, src_qty, src_amt in all_sheet_data:
            out_qty, out_amt = out_section_sums.get(sname, (0.0, 0.0))
            ok = abs(src_qty - out_qty) < 0.01 and abs(src_amt - out_amt) < 0.01
            if not ok:
                all_pass = False
            print(f"  {sname[:30]:<30} {src_qty:>12,.2f} {out_qty:>12,.2f} "
                  f"{src_amt:>14,.2f} {out_amt:>14,.2f} {'PASS' if ok else 'FAIL':>6}")

        print(f"  {'-'*30} {'-'*12} {'-'*12} {'-'*14} {'-'*14} {'-'*6}")
        total_ok = (abs(source_qty_total - out_qty_total) < 0.01
                    and abs(source_amount_total - out_amount_total) < 0.01)
        if not total_ok:
            all_pass = False
        print(f"  {'GRAND TOTAL':<30} {source_qty_total:>12,.2f} {out_qty_total:>12,.2f} "
              f"{source_amount_total:>14,.2f} {out_amount_total:>14,.2f} "
              f"{'PASS' if total_ok else 'FAIL':>6}")
        print(f"{'='*94}")

        if all_pass:
            print("ALL SECTIONS PASS — no BOQ items lost.")
            print("Next: route to pk-boq-hierarchy skill.")
        else:
            print("*** QTY / AMOUNT MISMATCH DETECTED — possible data loss! ***")
            print("*** Review the FAIL sections above before proceeding. ***")
            sys.exit(1)

        return out_path

    finally:
        try:
            temp_path.unlink()
            print(f"Cleaned up temp copy.")
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="BOQ merge — fastexcel → xlsxwriter")
    parser.add_argument("source", type=str, help="Source xlsx file path")
    parser.add_argument("-o", "--output", type=str, default=None, help="Output xlsx path")
    parser.add_argument("--sheet-regex", type=str, default=None,
                        help=f"Regex to identify BOQ sheets (default: {DEFAULT_SHEET_RE})")
    parser.add_argument("--skip", type=str, nargs="*", default=None,
                        help="Patterns to skip in sheet names")
    parser.add_argument("--delete-hidden-rows", action="store_true",
                        help="Delete hidden rows from temp copy before merging")
    args = parser.parse_args()

    merge(args.source, args.output, args.sheet_regex, args.skip, args.delete_hidden_rows)


if __name__ == "__main__":
    main()
