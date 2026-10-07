#!/usr/bin/env python3
"""
Sync UniqueBQ → 定额BQ with delta detection and color coding.

Usage:
    python sync_de_norms.py <workbook.xlsx> [--config <config.json>] [--dry-run]
"""

import json
import sys
import re
from pathlib import Path
from copy import copy
from fastexcel import read_excel
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import column_index_from_string, get_column_letter


# Color definitions
FILL_NEW = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")       # light green
FILL_DELETED = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")    # light gray
FILL_HAS_NORM = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")   # light blue
FILL_HEADER = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")     # dark blue header
FONT_HEADER = Font(color="FFFFFF", bold=True, size=10)
FONT_DELETED = Font(strikethrough=True, color="808080")
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)


def load_config(wb_path):
    """Load config from JSON file next to workbook, or auto-discover."""
    config_path = wb_path.parent / f"{wb_path.stem}_norms_config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))

    # Auto-discover
    from discover_config import classify_sheets, build_config
    print("No config found. Auto-discovering...")
    analysis = classify_sheets(wb_path)
    config = build_config(analysis)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Config auto-generated and saved to: {config_path}")
    return config


def clean_description(raw):
    """Multi-pass description cleaning for matching."""
    if not raw:
        return ""
    s = str(raw).strip()
    # Normalize whitespace
    s = re.sub(r'\s+', ' ', s)
    # Lowercase
    s = s.lower()
    # Strip leading "- "
    s = re.sub(r'^-\s+', '', s)
    # Strip surrounding {}
    s = s.strip('{}')
    # Strip section number prefix like "1.9 " or "01-1 "
    s = re.sub(r'^[\d]+(\.[\d]+)*\s+', '', s)
    s = re.sub(r'^[\d]+-[\d]+\s+', '', s)
    return s.strip()


def find_data_column(headers, patterns):
    """Find column letter matching given patterns."""
    for idx, h in enumerate(headers):
        if h:
            h_norm = str(h).strip().lower().replace(" ", "").replace("_", "")
            for p in patterns:
                if p.replace(" ", "").replace("_", "") in h_norm:
                    return get_column_letter(idx + 1)
    return None


def read_定额BQ_data(fx_sheet, config):
    """Read existing 定额BQ data via fastexcel -> pandas."""
    df = fx_sheet.to_pandas()
    desc_col = column_index_from_string(config["de_norms_desc_col"]) - 1
    norm_code_col = column_index_from_string(config.get("de_norms_norm_code_col", "K")) - 1
    norm_name_col = column_index_from_string(config.get("de_norms_norm_name_col", "L")) - 1
    norm_unit_col = column_index_from_string(config.get("de_norms_norm_unit_col", "M")) - 1
    data_start = config.get("de_norms_data_start", 2)

    rows = []
    for i in range(data_start - 1, len(df)):
        desc_val = df.iloc[i, desc_col]
        if pd.isna(desc_val) or str(desc_val).strip() == "":
            continue
        rows.append({
            "row": i + 1,  # 1-indexed row
            "desc_raw": str(desc_val).strip(),
            "desc_clean": clean_description(desc_val),
            "norm_code": _safe_str(df.iloc[i, norm_code_col]),
            "norm_name": _safe_str(df.iloc[i, norm_name_col]),
            "norm_unit": _safe_str(df.iloc[i, norm_unit_col]) if norm_unit_col < df.shape[1] else "",
        })
    return rows


def read_unique_bq_data(fx_sheet, config):
    """Read UniqueBQ descriptions via fastexcel -> pandas."""
    df = fx_sheet.to_pandas()
    desc_col = column_index_from_string(config["unique_bq_desc_col"]) - 1
    unit_col_letter = config.get("unique_bq_unit_col", "")
    unit_col = column_index_from_string(unit_col_letter) - 1 if unit_col_letter else -1
    data_start = config.get("unique_bq_data_start", 5)

    rows = []
    for i in range(data_start - 1, len(df)):
        desc_val = df.iloc[i, desc_col]
        if pd.isna(desc_val):
            continue
        desc_str = str(desc_val).strip()
        if desc_str in ("(blank)", "", "(空白)") or desc_str.lower().startswith("sum of"):
            continue
        unit_val = _safe_str(df.iloc[i, unit_col]) if unit_col >= 0 else ""
        rows.append({
            "row": i + 1,
            "desc_raw": desc_str,
            "desc_clean": clean_description(desc_str),
            "unit": unit_val.strip() if unit_val else "",
        })
    return rows


def _safe_str(val):
    if pd.isna(val):
        return ""
    return str(val).strip()


def sync(config_path_override=None):
    """Main sync logic."""
    # Find workbook
    wb_path = None
    for arg in sys.argv[1:]:
        if arg.endswith(".xlsx") or arg.endswith(".xlsm"):
            wb_path = Path(arg)
            break

    if not wb_path:
        print("ERROR: No workbook specified.")
        print("Usage: python sync_de_norms.py <workbook.xlsx> [--config <config.json>] [--dry-run]")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv

    config = load_config(wb_path)
    if config_path_override:
        config.update(json.loads(Path(config_path_override).read_text(encoding="utf-8")))

    print(f"Workbook: {wb_path.name}")
    print(f"UniqueBQ sheet: {config['unique_bq_sheet']} (desc={config['unique_bq_desc_col']})")
    print(f"定额BQ sheet: {config['de_norms_sheet']} (desc={config['de_norms_desc_col']})")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")

    # Read with fastexcel (fast)
    fx_wb = read_excel(str(wb_path))

    # Read UniqueBQ
    if config["unique_bq_sheet"] not in fx_wb.sheet_names:
        print(f"ERROR: UniqueBQ sheet '{config['unique_bq_sheet']}' not found!")
        sys.exit(1)

    fx_unique = fx_wb.load_sheet_by_name(config["unique_bq_sheet"])
    unique_rows = read_unique_bq_data(fx_unique, config)
    print(f"\nUniqueBQ: {len(unique_rows)} unique items")

    # Build UniqueBQ lookup by cleaned description
    unique_map = {}
    for r in unique_rows:
        key = r["desc_clean"]
        if key not in unique_map:
            unique_map[key] = r

    # Check if 定额BQ exists
    de_norms_exists = config["de_norms_sheet"] in fx_wb.sheet_names

    if de_norms_exists:
        fx_de = fx_wb.load_sheet_by_name(config["de_norms_sheet"])
        de_rows = read_定额BQ_data(fx_de, config)

        # Build 定额BQ lookup
        de_map = {}
        for r in de_rows:
            de_map[r["desc_clean"]] = r

        # Three-way comparison
        matched = []    # in both
        new_only = []   # in UniqueBQ only
        deleted = []    # in 定额BQ only

        for uq in unique_rows:
            if uq["desc_clean"] in de_map:
                matched.append((uq, de_map[uq["desc_clean"]]))
            else:
                new_only.append(uq)

        for de in de_rows:
            if de["desc_clean"] not in unique_map:
                deleted.append(de)

        print(f"Matched (keep norms): {len(matched)}")
        print(f"New (to add): {len(new_only)}")
        print(f"Deleted (mark gray): {len(deleted)}")
        print(f"Of matched, with norms: {sum(1 for _, d in matched if d['norm_code'])}")
        print(f"Of matched, without norms: {sum(1 for _, d in matched if not d['norm_code'])}")

        if not dry_run:
            wb = load_workbook(wb_path)
            ws_de = wb[config["de_norms_sheet"]]
            _apply_sync(wb, ws_de, config, matched, new_only, deleted, unique_rows, de_rows)
    else:
        # First time: create 定额BQ sheet from UniqueBQ
        print(f"\n定额BQ sheet '{config['de_norms_sheet']}' not found. Creating from UniqueBQ...")
        print(f"All {len(unique_rows)} items will be added as new.")
        if not dry_run:
            wb = load_workbook(wb_path)
            _create_de_norms_sheet(wb, config, unique_rows)

    if not dry_run:
        output_path = wb_path.parent / f"{wb_path.stem}_synced.xlsx"
        wb.save(str(output_path))
        print(f"\nSaved to: {output_path}")
        wb.close()
    else:
        print("\n[DRY RUN] No changes written.")


def _get_de_norms_headers(config):
    """Get the column headers for 定额BQ, detecting from config or using defaults."""
    headers = {}
    desc_letter = config.get("de_norms_desc_col", "E")
    unit_letter = config.get("de_norms_unit_col", "F")
    norm_code_letter = config.get("de_norms_norm_code_col", "K")
    norm_name_letter = config.get("de_norms_norm_name_col", "L")
    norm_unit_letter = config.get("de_norms_norm_unit_col", "M")
    status_letter = config.get("de_norms_status_col", "N")

    col_map = {
        column_index_from_string(desc_letter): "Description",
        column_index_from_string(unit_letter): "Unit",
        column_index_from_string(norm_code_letter): "Norm Code",
        column_index_from_string(norm_name_letter): "Norm Name",
        column_index_from_string(norm_unit_letter): "Norm Unit",
        column_index_from_string(status_letter): "Status",
    }
    return col_map


def _create_de_norms_sheet(wb, config, unique_rows):
    """Create 定额BQ sheet from scratch."""
    if config["de_norms_sheet"] in wb.sheetnames:
        ws = wb[config["de_norms_sheet"]]
    else:
        ws = wb.create_sheet(config["de_norms_sheet"])

    headers = _get_de_norms_headers(config)
    header_row = config.get("de_norms_header_row", 1)

    # Write headers
    for col_idx, name in sorted(headers.items()):
        cell = ws.cell(row=header_row, column=col_idx, value=name)
        cell.fill = FILL_HEADER
        cell.font = FONT_HEADER
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    # Write data
    desc_col = column_index_from_string(config["de_norms_desc_col"])
    unit_col = column_index_from_string(config["de_norms_unit_col"])
    data_start = config.get("de_norms_data_start", 2)

    for i, uq in enumerate(unique_rows):
        row = data_start + i
        ws.cell(row=row, column=desc_col, value=uq["desc_raw"])
        if unit_col and uq.get("unit"):
            ws.cell(row=row, column=unit_col, value=uq["unit"])

        # Color new items green
        for col_idx in range(1, 15):
            ws.cell(row=row, column=col_idx).fill = FILL_NEW

    print(f"Created {len(unique_rows)} rows in {config['de_norms_sheet']}")


def _apply_sync(wb, ws_de, config, matched, new_only, deleted, unique_rows, de_rows):
    """Apply sync changes to 定额BQ sheet with color coding."""
    desc_col = column_index_from_string(config["de_norms_desc_col"])
    unit_col = column_index_from_string(config["de_norms_unit_col"]) if config.get("de_norms_unit_col") else None
    norm_code_col = column_index_from_string(config.get("de_norms_norm_code_col", "K"))
    norm_name_col = column_index_from_string(config.get("de_norms_norm_name_col", "L"))
    norm_unit_col = column_index_from_string(config.get("de_norms_norm_unit_col", "M"))
    data_start = config.get("de_norms_data_start", 2)
    max_col = max(desc_col, unit_col or 0, norm_code_col, norm_name_col, norm_unit_col)

    # 1. Mark deleted rows with gray
    for de in deleted:
        row = de["row"]
        for col in range(1, max_col + 2):
            cell = ws_de.cell(row=row, column=col)
            cell.fill = FILL_DELETED
            cell.font = FONT_DELETED

    # 2. Update matched rows - preserve norms, ensure data is fresh
    for uq, de in matched:
        row = de["row"]
        # Update description if changed (e.g. whitespace normalization)
        current_desc = ws_de.cell(row=row, column=desc_col).value
        if str(current_desc).strip() != uq["desc_raw"]:
            ws_de.cell(row=row, column=desc_col, value=uq["desc_raw"])

        # Color: blue if has norm, otherwise no special color
        has_norm = bool(de["norm_code"] and str(de["norm_code"]).strip())
        for col in range(1, max_col + 2):
            cell = ws_de.cell(row=row, column=col)
            if has_norm:
                cell.fill = FILL_HAS_NORM
            else:
                cell.fill = PatternFill(fill_type=None)  # clear fill
            cell.font = Font(strikethrough=False)  # clear strikethrough
            cell.border = THIN_BORDER

    # 3. Append new items at the end
    next_row = max((r["row"] for r in de_rows), default=data_start - 1) + 1

    # Add a separator row
    if new_only:
        next_row += 1  # blank row
        ws_de.merge_cells(start_row=next_row, start_column=1, end_row=next_row, end_column=max_col)
        sep_cell = ws_de.cell(row=next_row, column=1,
                              value=f"--- New items from UniqueBQ refresh ({len(new_only)} items) ---")
        sep_cell.font = Font(bold=True, color="006100")
        next_row += 1

    for uq in new_only:
        ws_de.cell(row=next_row, column=desc_col, value=uq["desc_raw"])
        if unit_col and uq.get("unit"):
            ws_de.cell(row=next_row, column=unit_col, value=uq["unit"])
        for col in range(1, max_col + 2):
            cell = ws_de.cell(row=next_row, column=col)
            cell.fill = FILL_NEW
            cell.border = THIN_BORDER
        next_row += 1

    if new_only:
        print(f"Appended {len(new_only)} new items starting at row {next_row - len(new_only)}")


if __name__ == "__main__":
    sync()
