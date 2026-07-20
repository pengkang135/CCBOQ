"""Extract BOQ items by {} region, aggregate by classification pattern for LLM review.

Usage:
  python extract_regions.py <classified.xlsx> [--sheet "ZOO BQ"] [--region "{Wall surface material}"] [--output regions.json]

Output JSON structure:
  {
    "file": "...",
    "sheet": "...",
    "total_regions": N,
    "classification_columns": {"discipline": M, "category": N, "subcategory": O},
    "regions": [
      {
        "header": "{...}",
        "excel_start_row": N,
        "excel_end_row": N,
        "data_rows": N,
        "classification_patterns": [
          {"discipline": "...", "category": "...", "subcategory": "...", "count": N, "samples": ["desc1", ...]}
        ]
      }
    ]
  }
"""
import fastexcel, sys, json, argparse, re
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')


def find_regions(df, desc_col, region_filter=None):
    """Find all {} marker regions and their row ranges."""
    regions = []
    for i, val in enumerate(df.iloc[:, desc_col]):
        if not isinstance(val, str):
            continue
        v = val.strip()
        if not v.startswith('{'):
            continue
        if region_filter and region_filter.lower() not in v.lower():
            continue

        end = len(df)
        for j in range(i + 1, len(df)):
            nv = df.iloc[j, desc_col]
            if isinstance(nv, str) and (nv.strip().startswith('{') or nv.strip().startswith('《')):
                end = j
                break
        regions.append({'start_row': i, 'end_row': end, 'header': v})

    return regions


def extract_region_rows(df, region, desc_col, disc_col, cat_col, subcat_col):
    """Extract data rows within a region (skip markers, empties)."""
    rows = []
    for r in range(region['start_row'] + 1, region['end_row']):
        desc = df.iloc[r, desc_col]
        if not isinstance(desc, str) or desc.strip() == '':
            continue
        if desc.strip().startswith('{') or desc.strip().startswith('《'):
            continue

        def safe_str(col_idx):
            v = df.iloc[r, col_idx]
            if v is None or (isinstance(v, float) and v != v):
                return ''
            return str(v)

        rows.append({
            'excel_row': r + 1,
            'desc': str(desc)[:200],
            'discipline': safe_str(disc_col),
            'category': safe_str(cat_col),
            'subcategory': safe_str(subcat_col),
        })
    return rows


def aggregate_patterns(rows):
    """Deduplicate by (discipline, category, subcategory) pattern."""
    pattern_map = defaultdict(lambda: {'count': 0, 'samples': []})

    for row in rows:
        key = (row['discipline'], row['category'], row['subcategory'])
        entry = pattern_map[key]
        entry['count'] += 1
        if len(entry['samples']) < 3:
            entry['samples'].append(row['desc'][:120])

    patterns = []
    for (disc, cat, subcat), info in sorted(pattern_map.items(), key=lambda x: -x[1]['count']):
        patterns.append({
            'discipline': disc,
            'category': cat,
            'subcategory': subcat,
            'count': info['count'],
            'samples': info['samples'],
        })

    return patterns


def main():
    parser = argparse.ArgumentParser(description='Extract BOQ regions for LLM classification review')
    parser.add_argument('xlsx', help='Path to classified BOQ xlsx')
    parser.add_argument('--sheet', default='ZOO BQ', help='Sheet name (default: ZOO BQ)')
    parser.add_argument('--region', help='Filter by region header substring (e.g. "{Wall surface material}")')
    parser.add_argument('--desc-col', type=int, default=1, help='Description column 0-based index (default: 1 = col B)')
    parser.add_argument('--disc-col', type=int, default=12, help='Discipline column 0-based index (default: 12 = col M)')
    parser.add_argument('--cat-col', type=int, default=13, help='Category column 0-based index (default: 13 = col N)')
    parser.add_argument('--subcat-col', type=int, default=14, help='Subcategory column 0-based index (default: 14 = col O)')
    parser.add_argument('-o', '--output', help='Output JSON path (default: stdout)')
    parser.add_argument('--raw', action='store_true', help='Output raw rows instead of aggregated patterns')
    args = parser.parse_args()

    wb = fastexcel.read_excel(args.xlsx)
    sheet = wb.load_sheet(args.sheet)
    df = sheet.to_pandas()

    regions = find_regions(df, args.desc_col, args.region)
    if not regions:
        print(f"No regions found (filter='{args.region or ''}')")
        sys.exit(1)

    result = {
        'file': args.xlsx,
        'sheet': args.sheet,
        'total_regions': len(regions),
        'classification_columns': {
            'discipline': f'col_{args.disc_col}', 'category': f'col_{args.cat_col}', 'subcategory': f'col_{args.subcat_col}'
        },
        'regions': [],
    }

    for region in regions:
        rows = extract_region_rows(df, region, args.desc_col, args.disc_col, args.cat_col, args.subcat_col)
        if not rows:
            continue

        entry = {
            'header': region['header'],
            'excel_start_row': region['start_row'] + 1,
            'excel_end_row': region['end_row'],
            'data_rows': len(rows),
        }

        if args.raw:
            entry['rows'] = rows
        else:
            entry['classification_patterns'] = aggregate_patterns(rows)

        result['regions'].append(entry)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(result['regions'])} regions to {args.output}")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
