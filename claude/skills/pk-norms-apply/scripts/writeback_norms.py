#!/usr/bin/env python3
"""
Write norms from 定额BQ back to master BOQ via description matching.

Usage:
    python writeback_norms.py <workbook.xlsx> [--config <config.json>] [--dry-run]
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict
from fastexcel import read_excel
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import column_index_from_string


def clean_description(raw):
    """Multi-pass cleaning, same as sync_de_norms.py."""
    if not raw:
        return ""
    s = str(raw).strip()
    s = re.sub(r'\s+', ' ', s)
    s = s.lower()
    s = re.sub(r'^-\s+', '', s)
    s = s.strip('{}')
    s = re.sub(r'^[\d]+(\.[\d]+)*\s+', '', s)
    s = re.sub(r'^[\d]+-[\d]+\s+', '', s)
    return s.strip()


def generate_variants(raw_desc):
    """Generate all matching variants for a description.

    BOQ items may be nested under section headers. The raw description in
    ZOO BQ includes the full path context, while UniqueBQ/定额BQ only has
    the leaf description. So we need to try multiple variants.
    """
    s = str(raw_desc).strip()
    variants = [s.lower()]

    # Strip surrounding {}
    if s.startswith('{') and s.endswith('}'):
        inner = s[1:-1].strip()
        variants.append(inner.lower())
        s = inner  # continue processing with stripped version

    # Strip "- " prefix
    if s.startswith('- '):
        inner = s[2:].strip()
        variants.append(inner.lower())
        # Also strip {} from inner
        if inner.startswith('{') and inner.endswith('}'):
            variants.append(inner[1:-1].strip().lower())

    # Strip section number prefix
    for v in list(variants):
        cleaned = re.sub(r'^[\d]+(\.[\d]+)*\s+', '', v).strip()
        if cleaned != v:
            variants.append(cleaned)
        cleaned2 = re.sub(r'^[\d]+-[\d]+\s+', '', v).strip()
        if cleaned2 != v and cleaned2 not in variants:
            variants.append(cleaned2)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    return result


def load_config(wb_path):
    """Load config from JSON file."""
    config_path = wb_path.parent / f"{wb_path.stem}_norms_config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"Config not found: {config_path}\n"
        f"Run discover_config.py first to auto-detect the workbook structure."
    )


def build_norms_lookup(fx_de_sheet, config):
    """Build description→(norm_code, norm_name, norm_unit) map from 定额BQ via fastexcel."""
    df = fx_de_sheet.to_pandas()
    desc_col = column_index_from_string(config["de_norms_desc_col"]) - 1
    norm_code_col = column_index_from_string(config.get("de_norms_norm_code_col", "K")) - 1
    norm_name_col = column_index_from_string(config.get("de_norms_norm_name_col", "L")) - 1
    norm_unit_col = column_index_from_string(config.get("de_norms_norm_unit_col", "M")) - 1
    data_start = config.get("de_norms_data_start", 2)

    lookup = {}
    for i in range(data_start - 1, len(df)):
        norm_code = df.iloc[i, norm_code_col]
        if pd.isna(norm_code) or str(norm_code).strip() == "":
            continue
        desc = df.iloc[i, desc_col]
        if pd.isna(desc):
            continue
        norm_name = df.iloc[i, norm_name_col]
        norm_unit = df.iloc[i, norm_unit_col] if norm_unit_col < df.shape[1] else ""

        key = clean_description(desc)
        if key and key not in lookup:
            lookup[key] = (str(norm_code).strip(),
                           str(norm_name).strip() if not pd.isna(norm_name) else "",
                           str(norm_unit).strip() if not pd.isna(norm_unit) else "")
    return lookup


def _safe_str(val):
    if pd.isna(val):
        return ""
    return str(val).strip()


def writeback(wb_path, dry_run=False):
    """Main writeback logic."""
    config = load_config(wb_path)

    master_sheet = config["master_sheet"]
    de_sheet = config["de_norms_sheet"]
    master_desc_col = column_index_from_string(config["master_desc_col"])
    master_norm_code_col = column_index_from_string(config.get("master_norm_code_col", "O"))
    master_norm_name_col = column_index_from_string(config.get("master_norm_name_col", "P"))

    print(f"Workbook: {wb_path.name}")
    print(f"Master sheet: {master_sheet} (desc=col {master_desc_col})")
    print(f"定额BQ sheet: {de_sheet}")
    print(f"Writing Norm Code → col {config.get('master_norm_code_col', 'O')}")
    print(f"Writing Norm Name → col {config.get('master_norm_name_col', 'P')}")

    if dry_run:
        print("Mode: DRY RUN")

    # Read with fastexcel (fast)
    fx_wb = read_excel(str(wb_path))

    if de_sheet not in fx_wb.sheet_names:
        print(f"ERROR: 定额BQ sheet '{de_sheet}' not found!")
        fx_wb = None
        return

    if master_sheet not in fx_wb.sheet_names:
        print(f"ERROR: Master sheet '{master_sheet}' not found!")
        fx_wb = None
        return

    # Build norms lookup from 定额BQ via fastexcel
    fx_de = fx_wb.load_sheet_by_name(de_sheet)
    norms_lookup = build_norms_lookup(fx_de, config)
    print(f"\nNorms in 定额BQ: {len(norms_lookup)} unique entries with norm codes")

    # Scan master BOQ via fastexcel
    fx_master = fx_wb.load_sheet_by_name(master_sheet)
    df_master = fx_master.to_pandas()
    master_data_start = config.get("master_data_start", 5)
    total_rows = 0
    matched_rows = 0
    unmatched = []
    used_norms = set()

    # Build list of (row_index, desc) for rows to write back
    write_ops = []  # (excel_row, norm_code, norm_name)

    for i in range(master_data_start - 1, len(df_master)):
        desc = df_master.iloc[i, master_desc_col - 1]
        if pd.isna(desc):
            continue
        total_rows += 1

        variants = generate_variants(desc)
        found = None
        for v in variants:
            if v in norms_lookup:
                found = norms_lookup[v]
                break

        if found:
            norm_code, norm_name, norm_unit = found
            write_ops.append((i + 1, norm_code, norm_name))
            used_norms.add(clean_description(desc))
            matched_rows += 1
        else:
            cleaned = clean_description(desc)
            if cleaned not in norms_lookup:
                unmatched.append((i + 1, str(desc)[:80]))
            else:
                found = norms_lookup[cleaned]
                norm_code, norm_name, norm_unit = found
                write_ops.append((i + 1, norm_code, norm_name))
                used_norms.add(cleaned)
                matched_rows += 1

    # Check for norms in 定额BQ not found in master
    unused_norms = set(norms_lookup.keys()) - used_norms

    print(f"\n--- Results ---")
    print(f"Master BOQ data rows scanned: {total_rows}")
    print(f"Matched and written: {matched_rows}")
    print(f"Not matched (no norm): {len(unmatched)}")
    print(f"Norms in 定额BQ not found in master: {len(unused_norms)}")

    if unmatched and len(unmatched) <= 20:
        print(f"\nFirst {min(len(unmatched), 10)} unmatched items:")
        for row, desc in unmatched[:10]:
            print(f"  Row {row}: {desc}")

    if unused_norms:
        print(f"\nNorms in 定额BQ not used (may indicate description changes in master):")
        for key in sorted(unused_norms)[:10]:
            code, name, unit = norms_lookup[key]
            print(f"  {key[:60]} → {code} | {name}")

    if not dry_run and write_ops:
        wb = load_workbook(wb_path)
        ws_master = wb[master_sheet]
        for row, code, name in write_ops:
            ws_master.cell(row=row, column=master_norm_code_col, value=code)
            ws_master.cell(row=row, column=master_norm_name_col, value=name)
        output_path = wb_path.parent / f"{wb_path.stem}_writeback.xlsx"
        wb.save(str(output_path))
        print(f"\nSaved to: {output_path}")
        wb.close()
    elif not dry_run and not write_ops:
        print("\nNo norms to write back.")
    else:
        print("\n[DRY RUN] No changes written.")

    return matched_rows, len(unmatched)


def main():
    wb_path = None
    dry_run = False

    for arg in sys.argv[1:]:
        if arg.endswith(".xlsx") or arg.endswith(".xlsm"):
            wb_path = Path(arg)
        elif arg == "--dry-run":
            dry_run = True

    if not wb_path:
        print("Usage: python writeback_norms.py <workbook.xlsx> [--config <config.json>] [--dry-run]")
        sys.exit(1)

    writeback(wb_path, dry_run)


if __name__ == "__main__":
    main()
