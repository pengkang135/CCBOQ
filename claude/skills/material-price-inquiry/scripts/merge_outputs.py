#!/usr/bin/env python3
"""Merge part_a.json + part_b.json + part_c.json → price_data.json + price_inquiry.html

Usage:
  python merge_outputs.py [--output-dir OUTPUT_DIR]

If --output-dir is not specified, uses current working directory.
The script reads part_a.json, part_b.json, part_c.json from the output directory
and writes price_data.json and price_inquiry.html there.
"""

import json
import sys
from pathlib import Path


def price_str(q):
    """Format price_usd for display."""
    p = q.get("price_usd")
    if p is None:
        return "需询价"
    if isinstance(p, (int, float)):
        return f"${p:,.2f}"
    return str(p)


def type_badge(t):
    """Return HTML color-coded type badge."""
    colors = {
        "供应商报价": "#34a853",
        "平台参考": "#4285f4",
        "市场参考": "#f9ab00",
        "无公开报价": "#ea4335",
    }
    c = colors.get(t, "#999999")
    return (
        f'<span style="background:{c};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:0.8em">{t}</span>'
    )


def lang_flag(l):
    """Return language flag emoji string."""
    flags = {
        "en": "EN",
        "bn": "BN",
        "en+bn": "EN+BN",
        "vi": "VI",
        "ar": "AR",
        "th": "TH",
    }
    label = flags.get(l, l.upper() if l else "")
    return label


def build_html(all_quotes):
    """Build complete HTML document."""
    rows = ""
    for q in all_quotes:
        url = q.get("url", "") or "#"
        source_text = q.get("source", "")
        if len(source_text) > 100:
            source_text = source_text[:97] + "..."

        note_col = ""
        if q.get("note"):
            note_col = (
                f'<td style="font-size:0.78em;color:#666">{q["note"][:120]}</td>'
            )

        rows += f"""<tr>
<td>{q['material_id']}</td>
<td>{q['material_name']}</td>
<td>{q['supplier']}</td>
<td>{q['location']}</td>
<td style="text-align:right">{price_str(q)}</td>
<td>{q.get('unit','')}</td>
<td>{type_badge(q.get('type',''))}</td>
<td><a href="{url}" target="_blank" style="color:#1A73E8">{source_text}</a></td>
<td style="font-size:0.8em">{lang_flag(q.get('language','en'))}</td>
</tr>"""

    total = len(all_quotes)
    with_price = sum(1 for q in all_quotes if q.get("price_usd") is not None)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Market Price Inquiry Report</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,Arial,sans-serif;margin:20px;background:#f5f5f5;color:#333}}
h1{{border-bottom:3px solid #4285f4;padding-bottom:10px;margin-bottom:15px}}
.summary{{margin:10px 0 20px;padding:15px;background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.1);display:flex;gap:30px;flex-wrap:wrap}}
.summary .stat{{text-align:center}}
.summary .stat .num{{font-size:2em;font-weight:700;color:#4285f4}}
.summary .stat .label{{font-size:0.85em;color:#666}}
.note{{margin:10px 0;padding:10px;background:#fffbe6;border-left:4px solid #f9ab00;border-radius:4px;font-size:0.85em}}
table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.1);border-radius:8px;overflow:hidden;margin-bottom:20px}}
th{{background:#4285f4;color:#fff;padding:12px 8px;text-align:left;font-size:0.87em;white-space:nowrap}}
td{{padding:10px 8px;border-bottom:1px solid #e0e0e0;font-size:0.83em;vertical-align:top}}
tr:hover{{background:#f0f7ff}}
a{{text-decoration:none}}a:hover{{text-decoration:underline}}
.legend{{font-size:0.82em;color:#888;margin-bottom:15px}}
@media print{{body{{background:#fff}}table{{box-shadow:none}}}}
</style>
</head>
<body>

<h1>Market Price Inquiry Report</h1>

<div class="summary">
  <div class="stat"><div class="num">{len(set(q['material_id'] for q in all_quotes))}</div><div class="label">Materials</div></div>
  <div class="stat"><div class="num">{total}</div><div class="label">Total Quotes</div></div>
  <div class="stat"><div class="num">{with_price}</div><div class="label">With Prices</div></div>
  <div class="stat"><div class="num">{total - with_price}</div><div class="label">Need RFQ</div></div>
</div>

<div class="note">
<strong>Notes:</strong> All price source links are clickable for verification.
"需询价" entries have supplier contacts for direct RFQ.
"No public price" entries mean the supplier was identified but does not publish prices online.
Local language (non-EN) sources represent native-language search results.
</div>

<div class="legend">Click any link in the <strong>Source</strong> column to verify the original price page.</div>

<table>
<thead><tr>
<th>ID</th><th>Material</th><th>Supplier</th><th>Location</th><th>Price (USD)</th><th>Unit</th><th>Type</th><th>Source</th><th>Lang</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>

</body>
</html>"""
    return html


def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    parts = ["part_a.json", "part_b.json", "part_c.json"]

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

    # Write combined JSON
    json_path = output_dir / "price_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_quotes, f, ensure_ascii=False, indent=2)
    print(f"[write] price_data.json: {len(all_quotes)} total quotes")

    # Write HTML
    html_path = output_dir / "price_inquiry.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(all_quotes))
    print(f"[write] price_inquiry.html")

    # Print summary
    groups = {}
    for q in all_quotes:
        mid = q["material_id"]
        groups.setdefault(mid, {"total": 0, "with_price": 0, "without_price": 0})
        groups[mid]["total"] += 1
        if q.get("price_usd") is not None:
            groups[mid]["with_price"] += 1
        else:
            groups[mid]["without_price"] += 1

    print("\n=== Summary ===")
    for mid in sorted(groups.keys()):
        g = groups[mid]
        print(f"  {mid}: {g['total']} quotes | priced:{g['with_price']} | RFQ:{g['without_price']}")
    total_priced = sum(1 for q in all_quotes if q.get("price_usd") is not None)
    print(f"\nTotal: {len(all_quotes)} quotes, {total_priced} with prices")


if __name__ == "__main__":
    main()
