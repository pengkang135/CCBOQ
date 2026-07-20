#!/usr/bin/env python3
"""Merge part_A.json + part_B.json + part_C.json → price_data.json → enrich → price_inquiry.html

Usage:
  python merge_outputs.py [output_dir]

If output_dir is not specified, uses current working directory.
Pipeline: merge → enrich_prices.py → generate_price_report.py
"""

import json
import subprocess
import sys
from pathlib import Path


def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)
    script_dir = Path(__file__).resolve().parent

    # ── Step 1: Merge parts ──
    parts = ["part_A.json", "part_B.json", "part_C.json"]
    all_quotes = []
    for p in parts:
        fp = output_dir / p
        if not fp.exists():
            print(f"[skip] {p} not found")
            continue
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
            all_quotes.extend(data)
            print(f"[load] {p}: {len(data)} quotes")

    if not all_quotes:
        print("[error] No part files found")
        sys.exit(1)

    json_path = output_dir / "price_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_quotes, f, ensure_ascii=False, indent=2)
    print(f"[write] price_data.json: {len(all_quotes)} total quotes")

    # ── Step 2: Enrich (EXW/FOB/CIF/DDP estimation) ──
    enriched_path = output_dir / "price_data_enriched.json"
    enrich_script = script_dir / "enrich_prices.py"
    result = subprocess.run(
        [sys.executable, str(enrich_script), str(json_path), str(enriched_path)],
        capture_output=True, text=True, encoding='utf-8'
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"[warn] enrich: {result.stderr}")

    # ── Step 3: Generate HTML ──
    html_path = output_dir / "price_inquiry.html"
    report_script = script_dir / "generate_price_report.py"
    result = subprocess.run(
        [sys.executable, str(report_script), str(enriched_path), str(html_path)],
        capture_output=True, text=True, encoding='utf-8'
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"[error] HTML generation: {result.stderr}")
        sys.exit(1)

    # ── Summary ──
    groups = {}
    for q in all_quotes:
        mid = q.get("material_id") or q.get("material_type") or "??"
        groups.setdefault(mid, {"total": 0, "with_price": 0, "without_price": 0})
        groups[mid]["total"] += 1
        if q.get("price_usd") is not None:
            groups[mid]["with_price"] += 1
        else:
            groups[mid]["without_price"] += 1

    total_priced = sum(1 for q in all_quotes if q.get("price_usd") is not None)
    print(f"\nTotal: {len(all_quotes)} quotes, {total_priced} with prices")
    print(f"Output: {html_path}")

    # Write detailed summary to file (avoids UnicodeEncodeError on Windows stdout)
    summary_path = output_dir / "_summary.txt"
    with open(summary_path, "w", encoding="utf-8") as sf:
        sf.write("=== Summary ===\n")
        for mid in sorted(groups.keys()):
            g = groups[mid]
            sf.write(f"  {mid}: {g['total']} quotes | priced:{g['with_price']} | RFQ:{g['without_price']}\n")
        sf.write(f"\nTotal: {len(all_quotes)} quotes, {total_priced} with prices\n")
    print(f"[write] {summary_path}")


if __name__ == "__main__":
    main()
