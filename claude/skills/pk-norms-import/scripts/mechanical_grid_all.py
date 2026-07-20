"""
Generalized mechanical grid fill — handles any norm table page.
Input: bbox JSON files → Output: 2D grid JSON
v2: Robust column detection — quota codes for value cols, left-edge clustering for fixed cols
    Header label expansion in value region
"""
import json, re
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent.parent
Y_TOL = 3.0
X_TOL = 12.0


def load_page(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["lines"]


def cluster_1d(values, tol):
    """Cluster 1D values, return list of group dicts with min/max/center"""
    vals = sorted(set(round(v) for v in values))
    if not vals:
        return []
    groups = []
    cur = [vals[0]]
    for v in vals[1:]:
        if v - cur[-1] < tol:
            cur.append(v)
        else:
            groups.append(cur)
            cur = [v]
    groups.append(cur)
    return [{"min": min(g) - tol, "max": max(g) + tol, "center": sum(g) / len(g)} for g in groups]


def _is_seq(l):
    t = l["text"].strip()
    if not t:
        return False
    if re.match(r'^\d{1,2}$', t) and l["x"] < 60:
        return True
    if re.match(r'^\d{1,2}\s+\S', t) and l["x"] < 60:
        return True
    return False


def _row_group_has_seq(rg, lines):
    row_lines = [l for l in lines if rg["min"] <= (l["y"] + l["y2"]) / 2 <= rg["max"]]
    return any(_is_seq(l) for l in row_lines)


def detect_table_bounds(lines):
    seqs = [l for l in lines if _is_seq(l)]
    if not seqs:
        return None, None
    data_ymax = max(l["y2"] for l in seqs)
    de = [l for l in lines if "定额编号" in l["text"]]
    header_ymin = min(l["y"] for l in de) if de else min(l["y"] for l in seqs) - 50
    # Truncate at note text: "注：" lines below header mark end of main table
    note_lines = [l for l in lines if "注：" in l["text"] or (l["text"].strip().startswith("注") and len(l["text"].strip()) > 2)]
    if note_lines:
        note_y = min(l["y"] for l in note_lines)
        if note_y > header_ymin:
            data_ymax = min(data_ymax, note_y - 5)
    return header_ymin - 10, data_ymax + 10


def is_table_line(l, ymin, ymax):
    t = l["text"].strip()
    if not t or t == ".":
        return False
    if re.match(r'^-\s*\d+\s*-$', t):
        return False
    if "注：" in t or (t.startswith("注") and len(t) > 2):
        return False
    if re.match(r'^\d+.*[m㎡³]', t) and l["x"] > 450 and l["y"] < 80:
        return False
    yc = (l["y"] + l["y2"]) / 2
    return ymin <= yc <= ymax


def find_col_boundaries(lines, row_groups):
    """
    Two-phase column detection:
    Phase 1: Value columns from 5-digit quota codes in header
    Phase 2: Fixed columns (left side) by left-edge (x) clustering of data row texts
    """
    # Identify data vs header rows
    data_rgs = [rg for rg in row_groups if _row_group_has_seq(rg, lines)]
    if not data_rgs:
        return [], [], row_groups

    first_data_y = min(rg["min"] for rg in data_rgs)

    # Phase 1: Value columns from 5-digit quota codes
    quota_codes = [l for l in lines if re.match(r'^\d{5}$', l["text"].strip()) and l["y"] < first_data_y]
    if not quota_codes:
        # Fallback: look in data rows too
        quota_codes = [l for l in lines if re.match(r'^\d{5}$', l["text"].strip())]

    quota_codes.sort(key=lambda l: l["x"])
    value_centers = []
    if quota_codes:
        # Cluster nearby codes (in case of duplicates across rows)
        code_x = sorted(set(round((l["x"] + l["x2"]) / 2) for l in quota_codes))
        code_groups = cluster_1d(code_x, X_TOL)
        value_centers = [g["center"] for g in code_groups]

    # Phase 2: Fixed columns from data row texts (left of first value column)
    first_value_x = min(l["x"] for l in quota_codes) if quota_codes else 300

    data_lines = []
    for l in lines:
        t = l["text"].strip()
        if not t or t == ".":
            continue
        yc = (l["y"] + l["y2"]) / 2
        in_data = any(rg["min"] <= yc <= rg["max"] for rg in data_rgs)
        if in_data and l["x"] < first_value_x - 10:
            data_lines.append(l)

    fixed_centers = []
    if data_lines:
        left_edges = sorted(set(round(l["x"]) for l in data_lines))
        edge_groups = cluster_1d(left_edges, X_TOL)
        fixed_centers = [g["center"] for g in edge_groups]

        # Merge phantom columns from wide texts: two adjacent groups
        # are the same column iff their text x-ranges overlap in any data row.
        group_x_ranges = []
        for g in edge_groups:
            g_lines = [l for l in data_lines if g["min"] <= round(l["x"]) <= g["max"]]
            if g_lines:
                group_x_ranges.append((min(l["x"] for l in g_lines), max(l["x2"] for l in g_lines)))
            else:
                group_x_ranges.append((g["center"], g["center"]))

        merged = []
        merge_centers = [fixed_centers[0]]
        merge_xmin, merge_xmax = group_x_ranges[0]
        for i in range(1, len(fixed_centers)):
            gx_min, gx_max = group_x_ranges[i]
            if gx_min <= merge_xmax and gx_max >= merge_xmin:
                merge_centers.append(fixed_centers[i])
                merge_xmin = min(merge_xmin, gx_min)
                merge_xmax = max(merge_xmax, gx_max)
            else:
                merged.append(sum(merge_centers) / len(merge_centers))
                merge_centers = [fixed_centers[i]]
                merge_xmin, merge_xmax = gx_min, gx_max
        merged.append(sum(merge_centers) / len(merge_centers))
        fixed_centers = merged

    # Combine
    col_centers = fixed_centers + value_centers
    n_cols = len(col_centers)
    if n_cols < 2:
        return [], [], row_groups

    # Assign texts to columns using x-center
    # Collect all data+header texts
    all_texts = []
    for l in lines:
        t = l["text"].strip()
        if not t or t == ".":
            continue
        yc = (l["y"] + l["y2"]) / 2
        in_table = any(rg["min"] <= yc <= rg["max"] for rg in row_groups)
        if in_table:
            all_texts.append(l)

    col_texts = defaultdict(list)
    for l in all_texts:
        xc = (l["x"] + l["x2"]) / 2
        ci = min(range(n_cols), key=lambda i: abs(xc - col_centers[i]))
        col_texts[ci].append(l)

    # Boundaries = midpoint of gap between adjacent columns
    col_bounds = []
    for i in range(n_cols - 1):
        left_max_x2 = max((t["x2"] for t in col_texts[i]), default=0)
        right_min_x = min((t["x"] for t in col_texts[i + 1]), default=float("inf"))
        if right_min_x > left_max_x2:
            boundary = (left_max_x2 + right_min_x) / 2
        else:
            boundary = (col_centers[i] + col_centers[i + 1]) / 2
        col_bounds.append(boundary)

    return col_bounds, col_centers, row_groups


def get_span(x, x2, col_bounds, col_centers=None, fixed_boundary=None):
    n = len(col_bounds) + 1
    xc = (x + x2) / 2
    text_w = x2 - x

    # In the fixed-column region, texts should never span multiple columns.
    # Use center-based single-column assignment to avoid boundary-crossing
    # artifacts (e.g. wide cost items bleeding into unit column).
    if col_centers and (text_w < 60 or (fixed_boundary and x < fixed_boundary)):
        best = min(range(n), key=lambda i: abs(xc - col_centers[i]))
        return best, best

    start, end = n - 1, 0
    for ci in range(n):
        left = col_bounds[ci - 1] if ci > 0 else float("-inf")
        right = col_bounds[ci] if ci < n - 1 else float("inf")
        if x2 > left and x < right:
            start = min(start, ci)
            end = max(end, ci)
    if start > end:
        best = min(range(n), key=lambda i: abs(xc - col_centers[i] if col_centers else (left + right) / 2))
        start = end = best
    return start, end


def get_row_span(y, y2, row_groups):
    """Return row span based on significant vertical overlap (>=25% of text height)."""
    text_h = y2 - y
    if text_h <= 0:
        cy = (y + y2) / 2
        best = min(range(len(row_groups)), key=lambda i: abs(row_groups[i]["center"] - cy))
        return best, best
    start, end = len(row_groups) - 1, 0
    for ri, rg in enumerate(row_groups):
        overlap = min(y2, rg["max"]) - max(y, rg["min"])
        if overlap > text_h * 0.25:
            start = min(start, ri)
            end = max(end, ri)
    if start > end:
        cy = (y + y2) / 2
        best = min(range(len(row_groups)), key=lambda i: abs(row_groups[i]["center"] - cy))
        start = end = best
    return start, end


def _is_numeric_part(p):
    """Check if a token looks like a standalone number (with optional parens, dash, comma)."""
    return bool(re.match(r'^[\d.,()（）－-]+$', p))


def expand_header_spans(grid, row_groups, first_data_row, lines):
    """
    Post-fill: expand header labels in the value-column region.
    Count distinct texts in the value region per header row, divide equally.
    """
    n_rows = len(grid)
    n_cols = len(grid[0]) if grid else 0
    if first_data_row < 2 or n_cols < 2:
        return

    # Find value region: first column that contains a 5-digit code in any row
    value_start_col = n_cols
    for ci in range(n_cols):
        for ri in range(n_rows):
            v = grid[ri][ci]
            if v and re.match(r'^\d{5}$', v):
                value_start_col = min(value_start_col, ci)
                break
    if value_start_col >= n_cols:
        # Fallback: value region starts after mid-table
        value_start_col = n_cols // 2

    value_n = n_cols - value_start_col
    if value_n < 2:
        return

    # For each header row, count distinct non-empty texts in value region
    for ri in range(1, first_data_row):
        row_texts = {}
        for ci in range(value_start_col, n_cols):
            v = grid[ri][ci]
            if v and v not in ('定额编号', '顺', '序', '号', '项目', '单位', '代码'):
                if v not in row_texts:
                    row_texts[v] = []
                row_texts[v].append(ci)

        n_texts = len(row_texts)
        if n_texts == 0:
            continue

        if n_texts == value_n:
            continue

        # If any text appears in non-adjacent columns, this row has
        # per-column labels (e.g. soil categories) — skip expansion
        if n_texts > 1:
            has_fragmented = False
            for cols in row_texts.values():
                for i in range(1, len(cols)):
                    if cols[i] - cols[i - 1] > 1:
                        has_fragmented = True
                        break
                if has_fragmented:
                    break
            if has_fragmented:
                continue

        chunk = value_n / n_texts

        # Clear existing fill in value region for this row
        for ci in range(value_start_col, n_cols):
            grid[ri][ci] = ""

        # Fill proportionally
        for idx, (text, _) in enumerate(row_texts.items()):
            c_start = value_start_col + int(idx * chunk)
            c_end = value_start_col + int((idx + 1) * chunk) - 1
            if c_end >= n_cols:
                c_end = n_cols - 1
            for ci in range(c_start, c_end + 1):
                if not grid[ri][ci]:
                    grid[ri][ci] = text


def merge_multiline_rows(grid, row_groups, first_data):
    """
    Merge continuation rows (multi-line cost items) into data rows.
    A continuation row has no seq# in col0 and no 11-digit code in its code column.
    """
    n_rows = len(grid)
    n_cols = len(grid[0]) if grid else 0
    if n_rows < 3 or n_cols < 4 or first_data >= n_rows:
        return grid, row_groups, first_data

    # Find code column in data rows
    code_col = None
    for ci in range(min(5, n_cols)):
        for ri in range(first_data, n_rows):
            v = grid[ri][ci]
            if v and re.match(r'^\d{11,12}$', v):
                code_col = ci
                break
        if code_col is not None:
            break

    # Mark data rows: have seq# in col0 OR have code in code_col
    is_data = [False] * n_rows
    for ri in range(n_rows):
        if ri < first_data:
            is_data[ri] = True
            continue
        v0 = grid[ri][0].strip() if n_cols > 0 else ""
        vc = grid[ri][code_col].strip() if code_col is not None and code_col < n_cols else ""
        has_seq = bool(re.match(r'^\d{1,2}$', v0) or re.match(r'^\d{1,2}\s+\S', v0))
        has_code = bool(re.match(r'^\d{11}', vc))
        is_data[ri] = has_seq or has_code

    # Assign each continuation row to its closest data row by y-center.
    # This avoids greedy absorption where the preceding data row steals
    # continuations that belong to the following data row.
    data_indices = [ri for ri in range(first_data, n_rows) if is_data[ri]]

    if not data_indices:
        return grid, row_groups, first_data

    continuation_map = defaultdict(list)
    for ri in range(first_data, n_rows):
        if is_data[ri]:
            continue
        best_dr = min(data_indices, key=lambda dr: abs(row_groups[ri]["center"] - row_groups[dr]["center"]))
        continuation_map[best_dr].append(ri)

    # Find first value column (boundary for concat vs overwrite)
    first_val = n_cols
    for ci in range(n_cols):
        for ri2 in range(first_data):
            if grid[ri2][ci] and re.match(r'^\d{5}$', grid[ri2][ci]):
                first_val = min(first_val, ci)
                break

    # Build merged grid
    new_grid = []
    new_row_groups = []
    processed = set()

    for ri in range(n_rows):
        if ri < first_data:
            new_grid.append(list(grid[ri]))
            new_row_groups.append(dict(row_groups[ri]))
            continue

        if not is_data[ri]:
            continue

        merged = list(grid[ri])
        merged_rg = dict(row_groups[ri])

        # Apply continuations in top-down order
        for ci_ri in sorted(continuation_map.get(ri, [])):
            crow = grid[ci_ri]
            for ci in range(n_cols):
                if not crow[ci]:
                    continue
                if not merged[ci]:
                    merged[ci] = crow[ci]
                elif ci < first_val:  # fixed-region text column: concat
                    merged[ci] = merged[ci] + crow[ci]
            merged_rg["min"] = min(merged_rg["min"], row_groups[ci_ri]["min"])
            merged_rg["max"] = max(merged_rg["max"], row_groups[ci_ri]["max"])
            processed.add(ci_ri)

        merged_rg["center"] = (merged_rg["min"] + merged_rg["max"]) / 2
        new_grid.append(merged)
        new_row_groups.append(merged_rg)

    # Recalculate first_data_row
    new_first = 0
    for ri in range(len(new_grid)):
        v0 = new_grid[ri][0].strip()
        if (re.match(r'^\d{1,2}$', v0) or re.match(r'^\d{1,2}\s', v0)) and ri > 2:
            new_first = ri
            break

    return new_grid, new_row_groups, new_first


def build_grid(lines):
    ymin, ymax = detect_table_bounds(lines)
    if ymin is None:
        return None

    tl = [l for l in lines if is_table_line(l, ymin, ymax)]

    # Row detection
    y_centers = [(l["y"] + l["y2"]) / 2 for l in tl]
    row_groups = cluster_1d(y_centers, Y_TOL)
    n_rows = len(row_groups)

    # Column detection (two-phase)
    col_bounds, col_centers, _ = find_col_boundaries(tl, row_groups)
    n_cols = len(col_centers)
    if n_cols == 0:
        return None

    # Build empty grid
    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]

    # Fill — first-writer-wins
    # Determine fixed-region boundary: x of first quota code column
    quota_codes_in_table = [l for l in tl if re.match(r'^\d{5}$', l["text"].strip())]
    fixed_boundary = min(l["x"] for l in quota_codes_in_table) - 10 if quota_codes_in_table else None

    for l in tl:
        t = l["text"].strip()
        r_start, r_end = get_row_span(l["y"], l["y2"], row_groups)
        c_start, c_end = get_span(l["x"], l["x2"], col_bounds, col_centers, fixed_boundary)

        # Handle merged multi-value text: space-separated numbers spanning multiple cols
        col_span = c_end - c_start + 1
        if col_span > 1:
            parts = t.split()
            if len(parts) >= col_span and all(_is_numeric_part(p) for p in parts):
                for idx, part in enumerate(parts):
                    ci = c_start + idx
                    if ci < n_cols:
                        for ri in range(r_start, r_end + 1):
                            if ri < n_rows and not grid[ri][ci]:
                                grid[ri][ci] = part
                continue

        for ri in range(r_start, r_end + 1):
            for ci in range(c_start, c_end + 1):
                if ri < n_rows and ci < n_cols and not grid[ri][ci]:
                    grid[ri][ci] = t

    # Find first data row (before expansion)
    # Only check col 0 — sequence numbers are always at the left edge
    first_data = 0
    for ri in range(n_rows):
        v = grid[ri][0]
        if v and (re.match(r'^\d{1,2}$', v) or re.match(r'^\d{1,2}\s', v)) and ri > 2:
            first_data = ri
            break

    # Expand header labels in value region
    expand_header_spans(grid, row_groups, first_data, tl)

    # Merge multi-line continuation rows into data rows
    grid, row_groups, first_data = merge_multiline_rows(grid, row_groups, first_data)
    n_rows = len(grid)

    rows_out = []
    for ri, rg in enumerate(row_groups):
        rows_out.append({
            "yc": round(rg["center"], 1),
            "cells": [grid[ri][ci] for ci in range(n_cols)],
        })

    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "col_centers": [round(c, 1) for c in col_centers],
        "col_bounds": [round(b, 1) for b in col_bounds],
        "first_data_row": first_data,
        "rows": rows_out,
    }


def print_grid(result):
    n_rows, n_cols = result["n_rows"], result["n_cols"]
    grid = [[result["rows"][ri]["cells"][ci] for ci in range(n_cols)] for ri in range(n_rows)]
    col_w = [max(len(str(grid[ri][ci])) for ri in range(n_rows)) + 1 for ci in range(n_cols)]
    lines = []
    for ri in range(n_rows):
        vals = []
        for ci in range(n_cols):
            v = grid[ri][ci] or "-"
            vals.append(v.ljust(col_w[ci]))
        lines.append(f"R{ri:2d} y={result['rows'][ri]['yc']:.0f}: " + " | ".join(vals))
    return "\n".join(lines)


def validate_grid(result):
    """Validate a 2D grid for common issues. Returns list of warnings."""
    warnings = []
    n_rows, n_cols = result["n_rows"], result["n_cols"]
    first_data = result["first_data_row"]
    grid = [[result["rows"][ri]["cells"][ci] for ci in range(n_cols)] for ri in range(n_rows)]

    if n_rows == 0 or n_cols == 0:
        warnings.append("Empty grid")
        return warnings

    # 1. Find value columns (contain 5-digit quota codes)
    value_cols = []
    for ci in range(n_cols):
        for ri in range(first_data):
            v = grid[ri][ci]
            if v and re.match(r'^\d{5}$', v):
                value_cols.append(ci)
                break
    fixed_cols = list(range(min(value_cols))) if value_cols else []

    # 2. Check: every data row should have content in fixed columns
    for ri in range(first_data, n_rows):
        row_empty = 0
        for ci in fixed_cols:
            if not grid[ri][ci]:
                row_empty += 1
        if row_empty == len(fixed_cols) and fixed_cols:
            warnings.append(f"R{ri}: all fixed columns empty — possible phantom row")

    # 3. Check: value columns should have few empty cells in data rows
    for ci in value_cols:
        empty_count = 0
        for ri in range(first_data, n_rows):
            if not grid[ri][ci]:
                empty_count += 1
        data_rows = n_rows - first_data
        if data_rows > 0 and empty_count > data_rows * 0.8:
            warnings.append(f"C{ci}: {empty_count}/{data_rows} empty cells — possible phantom column")

    # 4. Check: every data row should have a seq# in col 0 OR a merged cost_item
    for ri in range(first_data, n_rows):
        v0 = grid[ri][0].strip() if n_cols > 0 else ""
        if not v0:
            warnings.append(f"R{ri}: empty seq# column (col 0)")

    # 5. Check: code column should have 11-digit codes in most data rows
    if fixed_cols:
        # find code column
        code_col = None
        for ci in fixed_cols:
            code_count = sum(1 for ri in range(first_data, n_rows)
                           if grid[ri][ci] and re.match(r'^\d{11,12}$', grid[ri][ci]))
            total = sum(1 for ri in range(first_data, n_rows) if grid[ri][ci])
            if total > 0 and code_count > total * 0.6:
                code_col = ci
                break
        if code_col is None:
            warnings.append("No code column detected (no column with >60% 11-digit patterns)")

    # 6. Check: unit column should not contain 11-digit codes (swapped columns)
    if fixed_cols:
        for ci in fixed_cols:
            if ci == code_col:
                continue
            code_like = sum(1 for ri in range(first_data, n_rows)
                          if grid[ri][ci] and re.match(r'^\d{11,12}$', grid[ri][ci]))
            total = sum(1 for ri in range(first_data, n_rows) if grid[ri][ci])
            if total > 0 and code_like > total * 0.5 and ci != code_col:
                warnings.append(f"C{ci}: contains {code_like}/{total} code-like values — possible unit/code swap")

    # 7. Column count sanity: should have at least 4 fixed cols or 3 + merged seq#/cost_item
    if len(fixed_cols) < 3 and len(fixed_cols) > 0:
        warnings.append(f"Only {len(fixed_cols)} fixed columns (expected >= 3): 序号/项目/单位/代码 may be incomplete")

    return warnings


if __name__ == "__main__":
    pages = [84, 85, 86, 87, 296, 297, 515, 597, 726, 727]
    temp_dir = PROJECT_DIR / "temp"
    log_lines = []

    for pg in pages:
        input_path = temp_dir / f"page_{pg:04d}_bbox.json"
        if not input_path.exists():
            log_lines.append(f"P{pg}: SKIP (no bbox file)")
            continue

        lines = load_page(input_path)
        result = build_grid(lines)
        if result:
            out_path = temp_dir / f"page_{pg:04d}_grid.json"
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            log_lines.append(f"=== P{pg} === {result['n_rows']}R x {result['n_cols']}C, first_data={result['first_data_row']}")
            log_lines.append(print_grid(result))
            val_warnings = validate_grid(result)
            if val_warnings:
                log_lines.append(f"--- Validation ({len(val_warnings)} issues) ---")
                for w in val_warnings:
                    log_lines.append(f"  [!] {w}")
            else:
                log_lines.append("  [OK] No validation issues")
            log_lines.append(f"→ {out_path}")
        else:
            log_lines.append(f"P{pg}: FAILED (no table detected)")
        log_lines.append("")

    log_path = temp_dir / "mechanical_grid_all_log.txt"
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"Log: {log_path}")
