#!/usr/bin/env python3
"""
Bridge: mechanical 2D grid JSON → SQLite (same schema as AI extraction path).

Usage:
  python mechanical_grid_to_db.py --grid-dir output/grid/ --structure output/structure.json --db output/quota_data.sqlite
  python mechanical_grid_to_db.py --grid-dir output/grid/ --structure output/structure.json --db output/quota_data.sqlite --reset
"""

import json, re, sys, io
from pathlib import Path
from collections import defaultdict
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

UNIT_RE = re.compile(
    r'^(工日|元|%|kg|t|m|km|cm|mm|根|个|艘班|台班|件|组|套|座|只|台|辆|次|'
    r'片|块|条|卷|包|桶|张|副|10?[mM][²³]?|m[²³]|[cC][mM]|[mM][mM])$'
)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doc_number TEXT,
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
    source TEXT DEFAULT 'mechanical_grid',
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
    ocr_source TEXT DEFAULT 'mechanical_grid',
    data_quality TEXT DEFAULT 'mechanical_grid',
    FOREIGN KEY (table_id) REFERENCES quota_table(id)
);

CREATE INDEX IF NOT EXISTS idx_quota_item_code ON quota_item(quota_code);
CREATE INDEX IF NOT EXISTS idx_quota_item_cost ON quota_item(cost_item);
CREATE INDEX IF NOT EXISTS idx_quota_item_table ON quota_item(table_id);
CREATE INDEX IF NOT EXISTS idx_quota_item_page ON quota_item(page);
"""


# ── grid_to_1d (same logic as gen_viewer_html.py) ──

def grid_to_1d(grid):
    """Convert filled 2D grid to 1D records. Pure mechanical — no AI, no heuristics."""
    rows = grid["rows"]
    n_cols = grid["n_cols"]
    first_data = grid["first_data_row"]
    if first_data >= len(rows):
        return [], 0, {}

    value_cols = []
    for ci in range(n_cols):
        for ri in range(first_data):
            v = rows[ri]["cells"][ci].strip()
            if re.match(r'^\d{5}$', v):
                value_cols.append(ci)
                break

    if not value_cols:
        return [], 0, {}

    first_value = min(value_cols)
    fixed_cols = list(range(first_value))
    seq_col = 0

    code_col = None
    best_code = 0
    for ci in fixed_cols:
        if ci == seq_col:
            continue
        code_count = sum(1 for ri in range(first_data, len(rows))
                       if rows[ri]["cells"][ci].strip() and re.match(r'^\d{11,12}$', rows[ri]["cells"][ci].strip()))
        total = sum(1 for ri in range(first_data, len(rows)) if rows[ri]["cells"][ci].strip())
        if total > 0 and code_count > total * 0.5 and code_count > best_code:
            best_code = code_count
            code_col = ci

    unit_col = None
    best_unit = 0
    for ci in fixed_cols:
        if ci == seq_col or ci == code_col:
            continue
        unit_count = sum(1 for ri in range(first_data, len(rows))
                       if rows[ri]["cells"][ci].strip() and UNIT_RE.match(rows[ri]["cells"][ci].strip()))
        total = sum(1 for ri in range(first_data, len(rows)) if rows[ri]["cells"][ci].strip())
        if total > 0 and unit_count > total * 0.5 and unit_count > best_unit:
            best_unit = unit_count
            unit_col = ci

    cost_item_col = seq_col
    for ci in fixed_cols:
        if ci != seq_col and ci != code_col and ci != unit_col:
            cost_item_col = ci
            break

    if code_col is None:
        for ci in fixed_cols:
            for ri in range(first_data):
                if rows[ri]["cells"][ci] == "代码":
                    code_col = ci
                    break
            if code_col is not None:
                break

    if unit_col is None:
        for ci in fixed_cols:
            if ci == cost_item_col or ci == code_col or ci == seq_col:
                continue
            for ri in range(first_data):
                if rows[ri]["cells"][ci] == "单位":
                    unit_col = ci
                    break
            if unit_col is not None:
                break

    if cost_item_col == seq_col and len(fixed_cols) > 1:
        for ci in fixed_cols:
            if ci != seq_col and ci != code_col and ci != unit_col:
                cost_item_col = ci
                break

    col_attrs = {ci: [] for ci in value_cols}
    for ri in range(first_data):
        row_values = {}
        for ci in value_cols:
            v = rows[ri]["cells"][ci].strip()
            if v and not re.match(r'^\d{5}$', v):
                row_values[ci] = v
        if not row_values:
            continue
        unique_vals = set(row_values.values())
        if len(unique_vals) == 1:
            attr_name = list(unique_vals)[0]
            for ci in value_cols:
                col_attrs[ci].append(attr_name)
        else:
            for ci in value_cols:
                if ci in row_values:
                    col_attrs[ci].append(row_values[ci])

    for ci in value_cols:
        for ri in range(first_data):
            v = rows[ri]["cells"][ci].strip()
            if re.match(r'^\d{5}$', v):
                col_attrs[ci].insert(0, v)
                break

    max_attrs = max((len(a) - 1 for a in col_attrs.values()), default=0)

    records = []
    for ri in range(first_data, len(rows)):
        row_cells = rows[ri]["cells"]
        raw_cost = row_cells[cost_item_col].strip() if cost_item_col < len(row_cells) else ""
        if cost_item_col == seq_col:
            cost_item = re.sub(r'^\d{1,2}\s+', '', raw_cost)
        else:
            cost_item = raw_cost
        unit = row_cells[unit_col].strip() if unit_col is not None and unit_col < len(row_cells) else ""
        code = row_cells[code_col].strip() if code_col is not None and code_col < len(row_cells) else ""
        if not cost_item and not code:
            continue
        for ci in value_cols:
            amount = row_cells[ci].strip() if ci < len(row_cells) else ""
            attrs = col_attrs.get(ci, [])
            norms_code = attrs[0] if attrs else ""
            attr_values = attrs[1:] if len(attrs) > 1 else []
            records.append({
                "norms_code": norms_code,
                "attrs": attr_values,
                "cost_item": cost_item,
                "unit": unit,
                "code": code,
                "amount": amount,
            })

    return records, max_attrs, {"code_col": code_col, "unit_col": unit_col, "cost_item_col": cost_item_col}


# ── Continued-table chain detection ──

def is_continued_table(grid):
    """Detect if a grid is a continued table (no own header, inherits from previous page)."""
    rows = grid["rows"]
    first_data = grid["first_data_row"]
    n_cols = grid["n_cols"]

    # Continued tables: no 5-digit quota codes in header rows
    has_codes = False
    for ri in range(first_data):
        for ci in range(n_cols):
            v = rows[ri]["cells"][ci].strip()
            if re.match(r'^\d{5}$', v):
                has_codes = True
                break
        if has_codes:
            break

    # If header is minimal (just "顺/序/号" + one label row), likely continued
    header_text_count = 0
    for ri in range(first_data):
        for ci in range(n_cols):
            v = rows[ri]["cells"][ci].strip()
            if v and v not in ("定额编号", "顺", "序", "号", "项目", "单位", "代码", ""):
                header_text_count += 1

    return not has_codes or (has_codes and header_text_count < 5 and first_data <= 6)


def build_chain_groups(pages_data):
    """
    Group consecutive pages into (main_table, [continued_tables]) chains.
    A main table page has its own header with 5-digit quota codes.
    Continued tables share the main table's header/attribute structure.
    """
    sorted_pages = sorted(pages_data.keys())
    chains = []
    current_main = None
    current_continued = []

    for pg in sorted_pages:
        grid = pages_data[pg]
        if is_continued_table(grid):
            if current_main is not None:
                current_continued.append(pg)
            else:
                # First page is continued — treat as standalone
                chains.append((pg, []))
        else:
            if current_main is not None:
                chains.append((current_main, current_continued))
            current_main = pg
            current_continued = []

    if current_main is not None:
        chains.append((current_main, current_continued))

    return chains


# ── Database operations ──

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
    """, (doc_info.get('title', 'Unknown'), doc_info.get('doc_number', ''), doc_info.get('total_pages', 0)))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def load_chapters(conn, chapters, parent_id=None):
    ids = {}
    for i, ch in enumerate(chapters):
        cur = conn.execute("""
            INSERT INTO chapter (title, level, parent_id, sort_order, start_page, end_page, pdf_start, pdf_end, code_range)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ch['title'], ch.get('level', 1), parent_id, ch.get('sort_order', i + 1),
            ch.get('internal_start'), ch.get('internal_end'),
            ch.get('pdf_start'), ch.get('pdf_end'),
            ch.get('codes', [''])[0] if ch.get('codes') else None,
        ))
        ch_id = cur.lastrowid
        ids[ch['title']] = ch_id
        if 'children' in ch:
            child_ids = load_chapters(conn, ch['children'], parent_id=ch_id)
            ids.update(child_ids)
    return ids


def find_chapter_for_page(structure, internal_page):
    """Map internal page number to chapter."""
    chapters = structure.get('chapters', [])
    best = None

    def search(ch_list):
        nonlocal best
        for ch in ch_list:
            istart = ch.get('internal_start')
            iend = ch.get('internal_end')
            if istart is not None and iend is not None:
                if istart <= internal_page <= iend:
                    if best is None or (istart >= ch.get('internal_start', 999) and iend <= ch.get('internal_end', 0)):
                        best = ch
            if 'children' in ch:
                search(ch['children'])

    search(chapters)
    return best


def insert_table_chain(conn, chain_pages, pages_data, structure, chapter_map):
    """
    Insert one table chain (main + continued pages) into DB.
    The main page provides header structure; continued pages inherit it.
    """
    main_page, continued_pages = chain_pages
    all_pages = [main_page] + continued_pages

    main_grid = pages_data[main_page]
    main_records, max_attrs, col_info = grid_to_1d(main_grid)

    if not main_records:
        return None

    # Get header info from main page
    header_rows = []
    for ri in range(main_grid["first_data_row"]):
        header_rows.append(main_grid["rows"][ri]["cells"])

    # Build attr_labels from header rows (best-effort, no AI)
    attr_labels = []
    for ri in range(main_grid["first_data_row"]):
        for ci in range(main_grid["n_cols"]):
            v = main_grid["rows"][ri]["cells"][ci].strip()
            if v and v not in ("定额编号", "顺", "序", "号", "项目", "单位", "代码", ""):
                if not re.match(r'^\d{5}$', v) and v not in attr_labels:
                    # Look for attribute-name-like patterns (containing 类别/级别/类型/容/吨位/长)
                    if any(kw in v for kw in ['类别', '级别', '类型', '容', '吨位', '长', '距', '径']):
                        attr_labels.append(v)
                    elif len(v) <= 6:
                        attr_labels.append(v)

    # Trim to max_attrs
    attr_labels = attr_labels[:max_attrs]
    while len(attr_labels) < max_attrs:
        attr_labels.append("")

    # Find chapter for main page
    internal_page = None
    for pg in all_pages:
        ch = find_chapter_for_page(structure, pg) if structure else None
        if ch:
            internal_page = pg
            break

    chapter_id = None
    if internal_page and chapter_map:
        ch = find_chapter_for_page(structure, internal_page)
        if ch:
            chapter_id = chapter_map.get(ch.get('title'))

    # Collect all records across all pages in chain
    all_records = []
    for pg in all_pages:
        grid = pages_data[pg]
        recs, _, _ = grid_to_1d(grid)
        all_records.extend(recs)

    # Insert quota_table
    header_json = json.dumps({
        'attr_labels': attr_labels,
        'n_value_cols': len([ci for ci in range(main_grid["n_cols"])
                            for ri in range(main_grid["first_data_row"])
                            if re.match(r'^\d{5}$', main_grid["rows"][ri]["cells"][ci].strip())]),
        'continued_pages': continued_pages,
    }, ensure_ascii=False)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO quota_table
            (chapter_id, section_title, subsection_title, page, header_json,
             row_count, col_count, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'mechanical_grid')
    """, (
        chapter_id,
        '',
        '',
        main_page,
        header_json,
        len(all_records),
        max_attrs,
    ))
    table_id = cur.lastrowid

    # Collect cost_items for unit info
    cost_item_units = {}
    cost_item_codes = {}
    for r in all_records:
        ci = r["cost_item"]
        if ci and ci not in cost_item_units:
            cost_item_units[ci] = r["unit"]
            cost_item_codes[ci] = r["code"]

    # Insert quota_items
    batch = []
    for idx, r in enumerate(all_records):
        attrs = r["attrs"]
        while len(attrs) < 4:
            attrs.append("")

        amount = None
        if r["amount"] and r["amount"] not in ("－", "—", "-"):
            try:
                amount = float(r["amount"])
            except ValueError:
                amount = None

        batch.append((
            table_id, main_page,
            r["norms_code"], idx,
            attrs[0], attrs[1], attrs[2], attrs[3],
            attr_labels[0] if len(attr_labels) > 0 else "",
            attr_labels[1] if len(attr_labels) > 1 else "",
            attr_labels[2] if len(attr_labels) > 2 else "",
            attr_labels[3] if len(attr_labels) > 3 else "",
            r["cost_item"],
            r["unit"],
            r["code"],
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
                'mechanical_grid', 'mechanical_grid')
    """, batch)

    # Update page_index
    for pg in all_pages:
        cur.execute("""
            INSERT INTO page_index (page, page_type, chapter_id, table_id, ocr_status)
            VALUES (?, 'quota_table', ?, ?, 'extracted')
            ON CONFLICT(page) DO UPDATE SET
                page_type = 'quota_table',
                chapter_id = ?,
                table_id = ?,
                ocr_status = 'extracted'
        """, (pg, chapter_id, table_id, chapter_id, table_id))

    # Insert continued-table page_index entries
    for pg in continued_pages:
        cur.execute("""
            INSERT INTO page_index (page, page_type, chapter_id, table_id, ocr_status)
            VALUES (?, 'continued_table', ?, ?, 'extracted')
            ON CONFLICT(page) DO UPDATE SET
                page_type = 'continued_table',
                chapter_id = ?,
                table_id = ?,
                ocr_status = 'extracted'
        """, (pg, chapter_id, table_id, chapter_id, table_id))

    return table_id


# ── Main ──

def main():
    import argparse
    ap = argparse.ArgumentParser(description='Load mechanical grid JSON into SQLite')
    ap.add_argument('--grid-dir', required=True, help='Directory containing page_*_grid.json files')
    ap.add_argument('--structure', help='structure.json path for chapter/page mapping')
    ap.add_argument('--db', required=True, help='SQLite database path')
    ap.add_argument('--reset', action='store_true', help='Drop and recreate all tables')
    args = ap.parse_args()

    grid_dir = Path(args.grid_dir)
    db_path = Path(args.db)

    # Load grids
    pages_data = {}
    for fpath in sorted(grid_dir.glob('page_*_grid.json')):
        m = re.match(r'page_(\d+)_grid\.json', fpath.name)
        if not m:
            continue
        pg = int(m.group(1))
        pages_data[pg] = json.loads(fpath.read_text(encoding='utf-8'))

    if not pages_data:
        print("No grid files found.")
        return

    # Load structure if available
    structure = {}
    if args.structure:
        structure_path = Path(args.structure)
        if structure_path.exists():
            structure = json.loads(structure_path.read_text(encoding='utf-8'))

    # Init DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path, reset=args.reset)

    # Load document
    if structure.get('document'):
        load_document(conn, structure['document'])

    # Load chapters
    chapter_map = {}
    if structure.get('chapters'):
        chapter_map = load_chapters(conn, structure['chapters'])

    # Build chain groups
    chains = build_chain_groups(pages_data)

    print(f"Pages: {len(pages_data)}, Chains: {len(chains)}")

    # Insert each chain
    total_items = 0
    total_tables = 0
    for main_pg, cont_pgs in chains:
        chain = (main_pg, cont_pgs)
        table_id = insert_table_chain(conn, chain, pages_data, structure, chapter_map)
        if table_id:
            grid = pages_data[main_pg]
            recs, _, _ = grid_to_1d(grid)
            total_items += len(recs)
            total_tables += 1
            label = f"P{main_pg}"
            if cont_pgs:
                label += f" + [{', '.join(f'P{p}' for p in cont_pgs)}]"
            print(f"  {label}: {len(recs)} items (table {table_id})")

    conn.commit()

    # Verification
    cur = conn.cursor()
    tables = cur.execute("SELECT COUNT(*) FROM quota_table").fetchone()[0]
    items = cur.execute("SELECT COUNT(*) FROM quota_item").fetchone()[0]
    codes = cur.execute("SELECT COUNT(DISTINCT quota_code) FROM quota_item").fetchone()[0]

    print(f'\nLoaded: {total_tables} tables, {total_items} items')
    print(f'Verification:')
    print(f'  quota_table: {tables}')
    print(f'  quota_item: {items}')
    print(f'  distinct quota_codes: {codes}')
    print(f'  -> {db_path}')

    conn.close()


if __name__ == '__main__':
    main()
