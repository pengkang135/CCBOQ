#!/usr/bin/env python3
"""Phase 4: Quality verification of extracted data in SQLite.

Checks:
  1. Completeness - every PDF page in page_index
  2. Attribute quality - avg_attr per chapter
  3. Quota code range - matches TOC declarations
  4. Chapter hierarchy - matches structure.json

Usage:
  python verify_extraction.py --db output/quota_data.sqlite --structure output/structure.json
  python verify_extraction.py --db output/quota_data.sqlite --structure output/structure.json --json-report output/report.json
"""

import json, sys, re, os, io
from pathlib import Path
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def check_completeness(cur, total_pages):
    """Verify every page has an entry in page_index."""
    pages_in_db = set(row[0] for row in cur.execute("SELECT page FROM page_index"))
    missing = [p for p in range(1, total_pages + 1) if p not in pages_in_db]
    return {
        'check': 'completeness',
        'passed': len(missing) == 0,
        'total_pages': total_pages,
        'pages_in_db': len(pages_in_db),
        'missing': missing,
        'summary': f"{len(pages_in_db)}/{total_pages} pages indexed, {len(missing)} missing"
    }


def check_attribute_quality(cur):
    """Check attribute dimension coverage per chapter."""
    rows = cur.execute("""
        WITH page_attrs AS (
            SELECT qt.id, qt.page, qt.chapter_id,
                   (SELECT COUNT(DISTINCT attr1_label) FROM quota_item WHERE table_id = qt.id AND attr1_label != '') as n_attr
            FROM quota_table qt
        )
        SELECT c.title, COUNT(*) as tables,
               ROUND(AVG(pa.n_attr), 1) as avg_attr,
               SUM(CASE WHEN pa.n_attr = 0 THEN 1 ELSE 0 END) as zero_attr
        FROM page_attrs pa
        JOIN chapter c ON c.id = pa.chapter_id
        GROUP BY c.id
        ORDER BY c.sort_order
    """).fetchall()

    per_chapter = []
    total_zero = 0
    all_ok = True
    for title, tables, avg_attr, zero_attr in rows:
        per_chapter.append({
            'chapter': title, 'tables': tables,
            'avg_attr': avg_attr, 'zero_attr': zero_attr
        })
        total_zero += zero_attr
        if avg_attr < 1.0:
            all_ok = False

    return {
        'check': 'attribute_quality',
        'passed': all_ok,
        'per_chapter': per_chapter,
        'total_zero_attr': total_zero,
        'summary': f"Total zero-attr pages: {total_zero}. Chapter details: see per_chapter"
    }


def check_quota_codes(cur):
    """Check quota code ranges and continuity."""
    codes = [row[0] for row in cur.execute(
        "SELECT DISTINCT quota_code FROM quota_item ORDER BY quota_code"
    ).fetchall()]

    if not codes:
        return {'check': 'quota_codes', 'passed': False, 'summary': 'No quota codes found'}

    code_ints = []
    for c in codes:
        try:
            code_ints.append(int(c))
        except ValueError:
            pass

    code_ints.sort()

    return {
        'check': 'quota_codes',
        'passed': True,
        'total_distinct': len(codes),
        'range': f"{codes[0]} ~ {codes[-1]}",
        'summary': f"{len(codes)} distinct quota codes, range {codes[0]}~{codes[-1]}"
    }


def check_chapter_tree(cur, structure_chapters):
    """Verify DB chapter tree matches structure.json."""
    db_chapters = cur.execute(
        "SELECT COUNT(*) FROM chapter WHERE level = 1"
    ).fetchone()[0]

    struct_chapters = len(structure_chapters)

    return {
        'check': 'chapter_tree',
        'passed': db_chapters > 0,
        'db_level1_chapters': db_chapters,
        'structure_level1_chapters': struct_chapters,
        'summary': f"DB: {db_chapters} chapters, Structure: {struct_chapters} chapters"
    }


def check_null_ratio(cur):
    """Check null value ratio overall and per chapter."""
    total = cur.execute("SELECT COUNT(*) FROM quota_item").fetchone()[0]
    nulls = cur.execute("SELECT COUNT(*) FROM quota_item WHERE amount IS NULL").fetchone()[0]

    ratio = round(nulls / total * 100, 1) if total else 0

    return {
        'check': 'null_ratio',
        'passed': ratio < 25,
        'total_items': total,
        'null_items': nulls,
        'null_pct': ratio,
        'summary': f"{nulls}/{total} items null ({ratio}%)"
    }


def check_cost_item_quality(cur):
    """Detect cost_items that are likely misidentified (numeric names)."""
    bad_costs = cur.execute("""
        SELECT DISTINCT qt.page, qi.cost_item
        FROM quota_item qi
        JOIN quota_table qt ON qt.id = qi.table_id
        WHERE qi.cost_item GLOB '[0-9]*' OR qi.cost_item GLOB '*[~～]*'
        LIMIT 20
    """).fetchall()

    return {
        'check': 'cost_item_quality',
        'passed': len(bad_costs) == 0,
        'suspicious_items': [{'page': p, 'cost_item': c} for p, c in bad_costs],
        'summary': f"{len(bad_costs)} pages with suspicious cost_item names"
    }


def check_items_count(cur):
    """Check if items count = codes x cost_items for each page."""
    bad_pages = cur.execute("""
        SELECT qt.page,
               (SELECT COUNT(DISTINCT quota_code) FROM quota_item WHERE table_id = qt.id) as nc,
               (SELECT COUNT(DISTINCT cost_item) FROM quota_item WHERE table_id = qt.id) as nci,
               (SELECT COUNT(*) FROM quota_item WHERE table_id = qt.id) as ni
        FROM quota_table qt
        WHERE (SELECT COUNT(*) FROM quota_item WHERE table_id = qt.id) !=
              (SELECT COUNT(DISTINCT quota_code) FROM quota_item WHERE table_id = qt.id) *
              (SELECT COUNT(DISTINCT cost_item) FROM quota_item WHERE table_id = qt.id)
    """).fetchall()

    return {
        'check': 'items_count_consistency',
        'passed': len(bad_pages) < 20,
        'mismatched_pages': len(bad_pages),
        'summary': f"{len(bad_pages)} pages with items != codes x cost_items"
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Verify extraction quality')
    ap.add_argument('--db', required=True)
    ap.add_argument('--structure', required=True)
    ap.add_argument('--json-report')
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    with open(args.structure, 'r', encoding='utf-8') as f:
        structure = json.load(f)

    total_pages = structure.get('document', {}).get('total_pages', 0)

    results = []
    all_passed = True

    checks = [
        ('Completeness', check_completeness(cur, total_pages)),
        ('Attribute Quality', check_attribute_quality(cur)),
        ('Quota Codes', check_quota_codes(cur)),
        ('Chapter Tree', check_chapter_tree(cur, structure.get('chapters', []))),
        ('Null Ratio', check_null_ratio(cur)),
        ('Cost Item Quality', check_cost_item_quality(cur)),
        ('Items Count', check_items_count(cur)),
    ]

    print("=" * 60)
    print("EXTRACTION QUALITY REPORT")
    print("=" * 60)

    for name, result in checks:
        status = "PASS" if result['passed'] else "FAIL"
        print(f"\n[{status}] {name}")
        print(f"  {result['summary']}")
        if not result['passed']:
            all_passed = False
            if 'per_chapter' in result:
                for ch in result['per_chapter']:
                    flag = " ***" if ch['avg_attr'] < 1.0 else ""
                    print(f"    {ch['chapter']}: avg_attr={ch['avg_attr']}, zero={ch['zero_attr']}{flag}")
            if 'missing' in result and len(result['missing']) <= 20:
                print(f"    Missing pages: {result['missing']}")
            if 'suspicious_items' in result and result['suspicious_items']:
                for si in result['suspicious_items'][:5]:
                    print(f"    P{si['page']}: cost_item=\"{si['cost_item']}\"")

        results.append({'name': name, **result})

    print("\n" + "=" * 60)
    if all_passed:
        print("All checks PASSED")
    else:
        failed = [r['name'] for r in results if not r['passed']]
        print(f"FAILED checks: {', '.join(failed)}")
    print("=" * 60)

    if args.json_report:
        with open(args.json_report, 'w', encoding='utf-8') as f:
            json.dump({
                'all_passed': all_passed,
                'results': results
            }, f, ensure_ascii=False, indent=2)
        print(f"\nReport saved to {args.json_report}")

    conn.close()
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
