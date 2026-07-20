#!/usr/bin/env python3
"""Phase 3: Load extracted JSON files into SQLite database.
Reads structure.json and extracted JSON, writes all 6 tables in dependency order.

Usage:
  python load_all_to_sqlite.py --extracted-dir output/extracted/ --structure output/structure.json --db output/quota_data.sqlite
  python load_all_to_sqlite.py --extracted-dir output/extracted/ --structure output/structure.json --db output/quota_data.sqlite --reset
"""

import json, sys, re, os, io
from pathlib import Path
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doc_number TEXT,
    publisher TEXT,
    publish_year INTEGER,
    total_pages INTEGER,
    pdf_path TEXT,
    pdf_type TEXT,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    level INTEGER NOT NULL,
    parent_id INTEGER,
    sort_order INTEGER,
    start_page INTEGER,
    end_page INTEGER,
    pdf_start INTEGER,
    pdf_end INTEGER,
    code_range TEXT,
    FOREIGN KEY (parent_id) REFERENCES chapter(id)
);

CREATE TABLE IF NOT EXISTS page_index (
    page INTEGER PRIMARY KEY,
    internal_page INTEGER,
    page_type TEXT NOT NULL,
    chapter_id INTEGER,
    table_id INTEGER,
    text_preview TEXT,
    ocr_status TEXT DEFAULT 'extracted',
    FOREIGN KEY (chapter_id) REFERENCES chapter(id),
    FOREIGN KEY (table_id) REFERENCES quota_table(id)
);

CREATE TABLE IF NOT EXISTS section_text (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER,
    page INTEGER NOT NULL,
    type TEXT NOT NULL,
    title TEXT,
    content TEXT,
    FOREIGN KEY (chapter_id) REFERENCES chapter(id)
);

CREATE TABLE IF NOT EXISTS quota_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER,
    section_title TEXT,
    subsection_title TEXT,
    work_content TEXT,
    unit TEXT,
    page INTEGER NOT NULL,
    header_json TEXT,
    row_count INTEGER,
    col_count INTEGER,
    continued_from INTEGER,
    source TEXT DEFAULT 'pymupdf_text',
    FOREIGN KEY (chapter_id) REFERENCES chapter(id)
);

CREATE TABLE IF NOT EXISTS quota_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER NOT NULL,
    page INTEGER NOT NULL,
    quota_code TEXT NOT NULL,
    sort_order INTEGER,
    attr_level1 TEXT,
    attr_level2 TEXT,
    attr_level3 TEXT,
    attr_level4 TEXT,
    attr1_label TEXT,
    attr2_label TEXT,
    attr3_label TEXT,
    attr4_label TEXT,
    cost_item TEXT NOT NULL,
    cost_item_unit TEXT,
    code TEXT,
    amount REAL,
    ocr_source TEXT DEFAULT 'pymupdf_text',
    data_quality TEXT DEFAULT 'ai_extracted',
    FOREIGN KEY (table_id) REFERENCES quota_table(id)
);

CREATE INDEX IF NOT EXISTS idx_quota_item_code ON quota_item(quota_code);
CREATE INDEX IF NOT EXISTS idx_quota_item_cost ON quota_item(cost_item);
CREATE INDEX IF NOT EXISTS idx_quota_item_table ON quota_item(table_id);
CREATE INDEX IF NOT EXISTS idx_quota_item_page ON quota_item(page);
"""


def init_db(db_path, reset=False):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA foreign_keys=ON")

    if reset:
        for table in ['quota_item', 'quota_table', 'section_text', 'page_index', 'chapter', 'document']:
            conn.execute(f"DROP TABLE IF EXISTS {table}")

    for stmt in DB_SCHEMA.split(';'):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)

    return conn


def load_document(conn, doc_info):
    conn.execute("""
        INSERT INTO document (title, doc_number, total_pages)
        VALUES (?, ?, ?)
    """, (
        doc_info.get('title', 'Unknown'),
        doc_info.get('doc_number', ''),
        doc_info.get('total_pages', 0),
    ))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def load_chapters(conn, chapters, parent_id=None):
    """Recursively insert chapters from structure.json tree."""
    ids = {}
    for i, ch in enumerate(chapters):
        cur = conn.execute("""
            INSERT INTO chapter (title, level, parent_id, sort_order, start_page, end_page, pdf_start, pdf_end, code_range)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ch['title'],
            ch.get('level', 1),
            parent_id,
            ch.get('sort_order', i + 1),
            ch.get('internal_start'),
            ch.get('internal_end'),
            ch.get('pdf_start'),
            ch.get('pdf_end'),
            ch.get('codes', [''])[0] if ch.get('codes') else None,
        ))
        ch_id = cur.lastrowid
        ids[ch['title']] = ch_id

        if 'children' in ch:
            child_ids = load_chapters(conn, ch['children'], parent_id=ch_id)
            ids.update(child_ids)

    return ids


def load_quota_item_batch(conn, table_id, page, items, attr_dimensions):
    """Insert all items for one page."""
    attr_names = [d['name'] for d in attr_dimensions] if attr_dimensions else []

    batch = []
    for idx, item in enumerate(items):
        # Extract attribute values from attr_ prefixed fields
        attr_values = []
        for dim in attr_dimensions:
            key = f"attr_{dim['name']}"
            attr_values.append(item.get(key, '') or '')
        while len(attr_values) < 4:
            attr_values.append('')
        while len(attr_names) < 4:
            attr_names.append('')

        batch.append((
            table_id, page,
            item['quota_code'], idx,
            attr_values[0], attr_values[1], attr_values[2], attr_values[3],
            attr_names[0], attr_names[1], attr_names[2], attr_names[3],
            item.get('cost_item', '') or item.get(list(attr_names[-1])[-1] if attr_names else '', ''),
            item.get('cost_item_unit', ''),
            item.get('code', ''),
            item.get('amount'),
        ))

        # The cost_item in items is embedded as key
        # Fix: use the correct cost_item field
        if len(batch) > 0:
            batch[-1] = (
                table_id, page,
                item['quota_code'], idx,
                attr_values[0], attr_values[1], attr_values[2], attr_values[3],
                attr_names[0], attr_names[1], attr_names[2], attr_names[3],
                item.get('cost_item', ''),
                item.get('cost_item_unit', ''),
                item.get('code', ''),
                item.get('amount'),
            )

    conn.executemany("""
        INSERT INTO quota_item
            (table_id, page, quota_code, sort_order,
             attr_level1, attr_level2, attr_level3, attr_level4,
             attr1_label, attr2_label, attr3_label, attr4_label,
             cost_item, cost_item_unit, code, amount,
             ocr_source, data_quality)
        VALUES (?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                'pymupdf_text', 'ai_extracted')
    """, batch)


def load_page(conn, pg, extracted_data, chapter_map):
    """Load one extracted page into SQLite."""
    cur = conn.cursor()

    # Determine chapter_id from structure info
    chapter_id = None
    section_title = ''
    subsection_title = extracted_data.get('subsection', '')

    # Build header_json
    header_json = json.dumps({
        'attr_dimensions': extracted_data.get('attr_dimensions', []),
        'cost_items': extracted_data.get('cost_items', []),
    }, ensure_ascii=False)

    attr_dims = extracted_data.get('attr_dimensions', [])
    cost_items = extracted_data.get('cost_items', [])

    # Upsert quota_table
    existing = cur.execute(
        "SELECT id FROM quota_table WHERE page = ?", (pg,)
    ).fetchone()

    if existing:
        table_id = existing[0]
        cur.execute("""
            UPDATE quota_table SET
                chapter_id = ?, section_title = ?, subsection_title = ?,
                work_content = ?, unit = ?, header_json = ?,
                row_count = ?, col_count = ?
            WHERE id = ?
        """, (
            chapter_id, section_title, subsection_title,
            extracted_data.get('work_content', ''),
            extracted_data.get('unit', ''),
            header_json,
            len(extracted_data.get('items', [])),
            len(attr_dims),
            table_id,
        ))
    else:
        cur.execute("""
            INSERT INTO quota_table
                (chapter_id, section_title, subsection_title, work_content,
                 unit, page, header_json, row_count, col_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chapter_id, section_title, subsection_title,
            extracted_data.get('work_content', ''),
            extracted_data.get('unit', ''),
            pg, header_json,
            len(extracted_data.get('items', [])),
            len(attr_dims),
        ))
        table_id = cur.lastrowid

    # Delete old items and re-insert
    cur.execute("DELETE FROM quota_item WHERE page = ?", (pg,))

    # Insert items with proper cost_item extraction
    items = extracted_data.get('items', [])
    ci_names = [ci['name'] for ci in cost_items]

    batch = []
    for idx, item in enumerate(items):
        attr_values = []
        attr_labels = []
        for dim in attr_dims:
            key = f"attr_{dim['name']}"
            attr_values.append(item.get(key, '') or '')
            attr_labels.append(dim['name'])
        while len(attr_values) < 4:
            attr_values.append('')
            attr_labels.append('')

        # Extract cost_item and amount from flattened items
        for ci_name in ci_names:
            amount = item.get(ci_name)
            ci_info = next((ci for ci in cost_items if ci['name'] == ci_name), {})
            batch.append((
                table_id, pg, item['quota_code'], idx,
                attr_values[0], attr_values[1], attr_values[2], attr_values[3],
                attr_labels[0] if len(attr_labels) > 0 else '',
                attr_labels[1] if len(attr_labels) > 1 else '',
                attr_labels[2] if len(attr_labels) > 2 else '',
                attr_labels[3] if len(attr_labels) > 3 else '',
                ci_name,
                ci_info.get('unit', ''),
                ci_info.get('code', ''),
                amount,
            ))

    cur.executemany("""
        INSERT INTO quota_item
            (table_id, page, quota_code, sort_order,
             attr_level1, attr_level2, attr_level3, attr_level4,
             attr1_label, attr2_label, attr3_label, attr4_label,
             cost_item, cost_item_unit, code, amount,
             ocr_source, data_quality)
        VALUES (?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                'pymupdf_text', 'ai_extracted')
    """, batch)

    # Update page_index
    text_preview = (subsection_title or '')[:100]
    cur.execute("""
        INSERT INTO page_index (page, page_type, chapter_id, table_id, text_preview, ocr_status)
        VALUES (?, 'quota_table', ?, ?, ?, 'extracted')
        ON CONFLICT(page) DO UPDATE SET
            page_type = 'quota_table',
            chapter_id = ?,
            table_id = ?,
            text_preview = ?,
            ocr_status = 'extracted'
    """, (
        pg, chapter_id, table_id, text_preview,
        chapter_id, table_id, text_preview,
    ))

    return table_id


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Load extracted JSON into SQLite')
    ap.add_argument('--extracted-dir', required=True)
    ap.add_argument('--structure', required=True)
    ap.add_argument('--db', required=True)
    ap.add_argument('--reset', action='store_true')
    args = ap.parse_args()

    extracted_dir = Path(args.extracted_dir)
    structure_path = Path(args.structure)
    db_path = Path(args.db)

    # Read structure
    with open(structure_path, 'r', encoding='utf-8') as f:
        structure = json.load(f)

    # Initialize DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path, reset=args.reset)

    # 1. Load document
    load_document(conn, structure.get('document', {}))

    # 2. Load chapters
    chapter_map = load_chapters(conn, structure.get('chapters', []))

    # 3. Load pages from extracted JSON
    total_items = 0
    total_tables = 0

    for fpath in sorted(extracted_dir.glob('page_*.json')):
        m = re.match(r'page_(\d+)\.json', fpath.name)
        if not m:
            continue
        pg = int(m.group(1))

        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data.get('items'):
            continue

        table_id = load_page(conn, pg, data, chapter_map)
        total_items += len(data['items'])
        total_tables += 1

        if total_tables % 100 == 0:
            conn.commit()
            print(f'  ... {total_tables} tables, {total_items} items')

    conn.commit()

    # Verification
    cur = conn.cursor()
    tables = cur.execute("SELECT COUNT(*) FROM quota_table").fetchone()[0]
    items = cur.execute("SELECT COUNT(*) FROM quota_item").fetchone()[0]
    codes = cur.execute("SELECT COUNT(DISTINCT quota_code) FROM quota_item").fetchone()[0]
    chapters = cur.execute("SELECT COUNT(*) FROM chapter").fetchone()[0]

    print(f'\nLoaded: {total_tables} tables, {total_items} items')
    print(f'Verification:')
    print(f'  chapters: {chapters}')
    print(f'  quota_table: {tables}')
    print(f'  quota_item: {items}')
    print(f'  distinct quota_codes: {codes}')
    print(f'  -> {db_path}')

    conn.close()

    # Post-import cleaning
    try:
        from db_clean import clean_all
        print(f'\nRunning post-import cleaning...')
        clean_all(str(db_path))
    except ImportError:
        print(f'  (db_clean module not available, skipping cleaning)')


if __name__ == '__main__':
    main()
