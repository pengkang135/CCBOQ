"""Step 4: Load parsed quota data into SQLite. Always rebuilds from scratch."""
import json, re, sqlite3, sys, os
from pathlib import Path
from collections import OrderedDict

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, doc_number TEXT,
    publisher TEXT, effective_date TEXT, total_pages INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chapter (
    id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES chapter(id),
    sort_order INTEGER NOT NULL, level INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL, subtitle TEXT, toc_page INTEGER,
    start_page INTEGER, end_page INTEGER, is_appendix INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS section_text (
    id INTEGER PRIMARY KEY, chapter_id INTEGER NOT NULL REFERENCES chapter(id),
    page INTEGER NOT NULL, seq_no INTEGER NOT NULL, type TEXT, content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appendix_table (
    id INTEGER PRIMARY KEY, chapter_id INTEGER REFERENCES chapter(id),
    table_name TEXT NOT NULL, page_from INTEGER, page_to INTEGER,
    is_continued INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS appendix_row (
    id INTEGER PRIMARY KEY, table_id INTEGER NOT NULL REFERENCES appendix_table(id),
    page INTEGER NOT NULL, sort_order INTEGER NOT NULL, data_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS norms_table (
    id INTEGER PRIMARY KEY, chapter_id INTEGER REFERENCES chapter(id),
    section_title TEXT, subsection_title TEXT, work_content TEXT, unit TEXT,
    page INTEGER NOT NULL, seq_on_page INTEGER DEFAULT 1,
    header_json TEXT NOT NULL, row_count INTEGER, col_count INTEGER
);
CREATE TABLE IF NOT EXISTS norms_item (
    id INTEGER PRIMARY KEY, table_id INTEGER NOT NULL REFERENCES norms_table(id),
    page INTEGER NOT NULL, norms_code TEXT NOT NULL, sort_order INTEGER,
    attr_level1 TEXT, attr_level2 TEXT, attr_level3 TEXT, attr_level4 TEXT,
    attr1_label TEXT, attr2_label TEXT, attr3_label TEXT, attr4_label TEXT,
    cost_item TEXT NOT NULL, cost_item_unit TEXT, amount REAL,
    ocr_source TEXT DEFAULT 'OCR', data_quality TEXT DEFAULT 'raw'
);
CREATE TABLE IF NOT EXISTS page_index (
    page INTEGER PRIMARY KEY, page_type TEXT NOT NULL,
    chapter_id INTEGER REFERENCES chapter(id),
    table_id INTEGER REFERENCES norms_table(id),
    appendix_id INTEGER REFERENCES appendix_table(id),
    text_preview TEXT, ocr_status TEXT DEFAULT 'pending',
    ocr_lines INTEGER, ocr_confidence REAL
);
CREATE INDEX IF NOT EXISTS idx_norms_code ON norms_item(norms_code);
CREATE INDEX IF NOT EXISTS idx_norms_table ON norms_item(table_id);
CREATE INDEX IF NOT EXISTS idx_page_type ON page_index(page_type);
"""

CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

def cn_to_int(s):
    n = 0
    for ch in s:
        if ch in CN_NUM: n = n * 10 + CN_NUM[ch]
    return n if n > 0 else 1

def load(parsed_path, db_path, doc_title, doc_number='', reset=False, source='excel'):
    parsed_path = Path(parsed_path)
    with open(parsed_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(SCHEMA_SQL)

    # Always clear and rebuild
    for t in ['norms_item', 'norms_table', 'section_text', 'page_index', 'chapter', 'document']:
        conn.execute(f'DELETE FROM {t}')

    # 1. Document
    cur = conn.execute("INSERT INTO document (title, doc_number, publisher, total_pages) VALUES (?, ?, ?, ?)",
                       (doc_title, doc_number, '', 0))
    doc_id = cur.lastrowid

    # 2. Chapters from TOC
    chapter_id_map = {}
    toc_data = data.get('toc', {})
    if toc_data:
        ch_sort = 0
        for ch_name, ch_info in toc_data.items():
            if ch_name == '总说明': continue
            ch_sort += 1
            cur = conn.execute(
                "INSERT INTO chapter (parent_id, sort_order, level, title, start_page, end_page) VALUES (NULL, ?, 1, ?, 0, 0)",
                (ch_sort, ch_info['title']))
            ch_id = cur.lastrowid
            chapter_id_map[ch_name] = ch_id
            sec_sort = 0
            for sec in ch_info.get('sections', []):
                sec_sort += 1
                # All sections are L2 — no L3 items in navigation
                cur = conn.execute(
                    "INSERT INTO chapter (parent_id, sort_order, level, title, start_page, end_page) VALUES (?, ?, 2, ?, 0, 0)",
                    (ch_id, sec_sort, sec['title']))
                chapter_id_map[f"{ch_name}/{sec['title']}"] = cur.lastrowid
            # Direct items: do NOT create L2 chapters — they're just reference labels
            for item in ch_info.get('direct_items', []):
                chapter_id_map[f"{ch_name}/{item['title']}"] = ch_id  # map to L1 chapter
    else:
        conn.execute("INSERT INTO chapter (parent_id, sort_order, level, title, start_page, end_page) VALUES (NULL, 1, 1, ?, 0, 0)", (doc_title,))
        chapter_id_map['default'] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    print(f'Chapters: {len(chapter_id_map)} entries')

    # 2b. Text content
    text_seq = 0
    for tc in data.get('text_content', []):
        text_seq += 1
        cid = next(iter(chapter_id_map.values())) if chapter_id_map else 1
        for ch_name, ch_id in chapter_id_map.items():
            if '/' not in ch_name and ch_name in tc.get('title', ''):
                cid = ch_id; break
        conn.execute("INSERT INTO section_text (chapter_id, page, seq_no, type, content) VALUES (?, 0, ?, ?, ?)",
                     (cid, text_seq, tc.get('type', 'text'), tc['content']))
    if text_seq > 0: print(f'Text items: {text_seq}')

    # 3. Tables
    total_tables = 0; total_items = 0; page_counter = 0

    for doc in data.get('documents', []):
        tables = doc.get('tables', [])

        # Build lookup: ch_name → [(item_title, chapter_id)] for ALL L2/L3 entries
        all_items = {}  # ch_name → [(title, cid)]
        for key, cid in chapter_id_map.items():
            if '/' in key:
                ch_name, item_title = key.split('/', 1)
                if ch_name not in all_items:
                    all_items[ch_name] = []
                all_items[ch_name].append((item_title, cid))

        # Build L2-only lookup: ch_name → [(section_title, chapter_id)]
        l2_lookup = {}
        for key, cid in chapter_id_map.items():
            if '/' in key:
                ch_name, item_title = key.split('/', 1)
                if ch_name not in l2_lookup:
                    l2_lookup[ch_name] = []
                l2_lookup[ch_name].append((item_title, cid))

        for t in tables:
            ch_key = t.get('chapter', '')
            section_name = t.get('section', '')  # 节 header
            current_chapter_id = None

            # Match by section (节) name → assign to L2 directly
            if section_name and ch_key and ch_key in l2_lookup:
                for st, cid in l2_lookup[ch_key]:
                    if st == section_name:
                        current_chapter_id = cid
                        break
                if not current_chapter_id:
                    for st, cid in l2_lookup[ch_key]:
                        if section_name.startswith(st) or st.startswith(section_name):
                            current_chapter_id = cid
                            break

            # If section is just chapter name (no real section header), match by section_title
            if not current_chapter_id and ch_key and ch_key in l2_lookup:
                stitle = t.get('section_title', '').strip()
                for st, cid in l2_lookup[ch_key]:
                    if st == stitle:
                        current_chapter_id = cid
                        break
                if not current_chapter_id and stitle:
                    for st, cid in l2_lookup[ch_key]:
                        if stitle.startswith(st) or st.startswith(stitle):
                            current_chapter_id = cid
                            break

            # If matched L2 section has same title as the table itself, skip to L1 (avoid duplicate)
            stitle = t.get('section_title', '').strip()
            if current_chapter_id and stitle:
                # Check if the L2 section title equals the table's section_title
                l2_title = conn.execute('SELECT title FROM chapter WHERE id=?', (current_chapter_id,)).fetchone()
                if l2_title and l2_title[0] == stitle:
                    current_chapter_id = chapter_id_map.get(ch_key)

            # Fallback to chapter level
            if not current_chapter_id:
                current_chapter_id = chapter_id_map.get(ch_key) or next(iter(chapter_id_map.values()), None)

            header_json = json.dumps({
                'quota_codes': t.get('quota_codes', []),
                'code_columns': t.get('code_columns', {}),
                'attr_dimensions': t.get('attr_dimensions', []),
                'cost_items': t.get('cost_items', []),
                'notes': t.get('notes', [])
            }, ensure_ascii=False)

            row_range = t.get('row_range', [0, 0])
            cur = conn.execute(
                "INSERT INTO norms_table (chapter_id, section_title, work_content, unit, page, header_json, row_count, col_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (current_chapter_id, t.get('section_title', ''), t.get('work_content', ''), t.get('unit', ''),
                 row_range[0] if row_range else 0, header_json,
                 len(t.get('items', [])), len(t.get('quota_codes', []))))
            table_id = cur.lastrowid; total_tables += 1

            for item in t.get('items', []):
                av = item.get('attr_values', []); al = item.get('attr_labels', [])
                while len(av) < 4: av.append('')
                while len(al) < 4: al.append('')
                conn.execute(
                    "INSERT INTO norms_item (table_id, page, norms_code, sort_order, attr_level1, attr_level2, attr_level3, attr_level4, attr1_label, attr2_label, attr3_label, attr4_label, cost_item, cost_item_unit, amount, ocr_source, data_quality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (table_id, item.get('row', 0), item.get('quota_code', ''), item.get('sequence', 0),
                     av[0], av[1], av[2], av[3], al[0], al[1], al[2], al[3],
                     item.get('cost_item', ''), item.get('cost_item_unit', ''), item.get('amount'), source, 'raw'))
                total_items += 1

            page_counter += 1
            conn.execute("INSERT OR REPLACE INTO page_index (page, page_type, chapter_id, table_id, ocr_status) VALUES (?, ?, ?, ?, ?)",
                         (row_range[0] if row_range else page_counter, 'norms_table', current_chapter_id, table_id, source))

    conn.commit()
    cur = conn.execute("SELECT COUNT(*) FROM norms_table"); tc = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM norms_item"); ic = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(DISTINCT norms_code) FROM norms_item"); cc = cur.fetchone()[0]
    # Check L2 table count
    l2c = conn.execute("SELECT COUNT(*) FROM norms_table nt JOIN chapter c ON nt.chapter_id=c.id WHERE c.level=2").fetchone()[0]
    print(f'Imported: {tc} tables ({l2c} at L2), {ic} items, {cc} unique codes')
    conn.close()
    return tc, ic

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Load parsed quota data into SQLite')
    ap.add_argument('parsed_json'); ap.add_argument('--db', default=''); ap.add_argument('--title', default='定额'); ap.add_argument('--doc-number', default=''); ap.add_argument('--source', default='excel')
    args = ap.parse_args()
    if not os.path.exists(args.parsed_json): print('Not found'); sys.exit(1)
    load(args.parsed_json, args.db or 'quota_data.sqlite', args.title, args.doc_number, False, args.source)
