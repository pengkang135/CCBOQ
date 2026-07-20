"""Step 5: Verify imported data quality in SQLite."""

import sqlite3, sys, os


def verify(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    issues = []

    # 1. Document count
    cur.execute("SELECT COUNT(*) FROM document")
    doc_count = cur.fetchone()[0]
    print(f'1. Documents: {doc_count}')
    if doc_count == 0:
        issues.append('No documents found')

    # 2. Chapter structure
    cur.execute("SELECT COUNT(*), MAX(level) FROM chapter")
    ch_count, max_level = cur.fetchone()
    print(f'2. Chapters: {ch_count}, max level: {max_level}')

    # 3. Item count and code coverage
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT norms_code) FROM norms_item")
    item_count, code_count = cur.fetchone()
    print(f'3. Items: {item_count}, Unique codes: {code_count}')

    # 4. Table count
    cur.execute("SELECT COUNT(*) FROM norms_table")
    table_count = cur.fetchone()[0]
    print(f'4. Tables: {table_count}')

    # 5. Null ratio
    cur.execute("SELECT COUNT(*) FROM norms_item WHERE amount IS NULL")
    null_count = cur.fetchone()[0]
    null_ratio = 100.0 * null_count / item_count if item_count else 0
    print(f'5. Null amount: {null_count}/{item_count} ({null_ratio:.1f}%)')
    if null_ratio > 30:
        issues.append(f'Null ratio {null_ratio:.1f}% exceeds 30%')

    # 6. 基价 coverage
    cur.execute("SELECT COUNT(DISTINCT norms_code) FROM norms_item WHERE cost_item LIKE '%基价%' OR cost_item LIKE '%基價%'")
    base_price_codes = cur.fetchone()[0]
    bp_ratio = 100.0 * base_price_codes / code_count if code_count else 0
    print(f'6. Codes with 基价: {base_price_codes}/{code_count} ({bp_ratio:.1f}%)')
    if bp_ratio < 80:
        issues.append(f'基价 coverage {bp_ratio:.1f}% below 80%')

    # 7. Attribute coverage
    cur.execute("SELECT COUNT(DISTINCT attr1_label) FROM norms_item WHERE attr1_label != ''")
    attr_count = cur.fetchone()[0]
    avg_attr = attr_count / table_count if table_count else 0
    print(f'7. Attribute labels: {attr_count} unique, {avg_attr:.1f} avg per table')

    # 8. Orphan check
    cur.execute("SELECT COUNT(*) FROM norms_item WHERE table_id NOT IN (SELECT id FROM norms_table)")
    orphans = cur.fetchone()[0]
    print(f'8. Orphan items: {orphans}')

    # 9. Code format
    cur.execute("SELECT COUNT(*) FROM norms_item WHERE norms_code GLOB '[0-9][0-9][0-9][0-9][0-9]'")
    valid_codes = cur.fetchone()[0]
    print(f'9. Valid 5-digit codes: {valid_codes}/{item_count}')

    conn.close()

    # Summary
    print(f'\n{"PASS" if not issues else "ISSUES FOUND"}: {len(issues)} issues')
    for i in issues:
        print(f'  - {i}')
    return len(issues) == 0


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Verify imported data')
    ap.add_argument('--db', default=r'F:\BaiduSyncdisk\2.清单定额\Norms-AI\output\quota_data.sqlite',
                    help='Path to SQLite database')
    args = ap.parse_args()
    if not os.path.exists(args.db):
        print(f'Database not found: {args.db}')
        sys.exit(1)
    verify(args.db)
