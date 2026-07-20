"""Complete rebuild: no table merging + 912 page index."""
import json, re, sqlite3, os, sys
from pathlib import Path
from collections import OrderedDict

sys.path.insert(0, str(Path(__file__).parent))
from extract_ref_final import parse_sheet

gp = Path(r'F:\BaiduSyncdisk\2.清单定额\1 预算定额\3 水工定额\JTS∕T 276-1-2019 沿海港口水工建筑工程定额（非正式出版稿）_grid.json')
with open(gp, 'r', encoding='utf-8') as f:
    data = json.load(f)
sd = data['sheets']
ch_starts = {28: '第一章', 197: '第二章', 534: '第三章', 712: '第四章', 796: '第五章', 832: '第六章'}

# Parse TOC
toc = OrderedDict()
cur_ch = None
cur_section = None
for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet', ''))):
    snum = int(sn.replace('Sheet', ''))
    if snum < 10 or snum > 23: continue
    for row in sd[sn]['rows']:
        cells = row['cells']
        vals = [str(v).strip() for v in cells.values()]
        is_full = len(vals) > 1 and all(v == vals[0] for v in vals)
        if is_full:
            t = vals[0].strip()
            clean = re.sub(r'[.]{3,}.*$', '', t).strip()
            clean = re.sub(r'\s*[-]\s*\d+\s*[-]?\s*$', '', clean).strip()
            if not clean: continue
            ch_m = re.match(r'^(第[一二三四五六七八九十]+章)\s*(.+)', clean)
            if ch_m:
                cn = ch_m.group(1)
                if cn not in toc: toc[cn] = {'title': clean, 'sections': [], 'direct_items': []}
                cur_ch = toc[cn]; cur_section = None; continue
            sec_m = re.match(r'^(第[一二三四五六七八九十]+节)\s*(.+)', clean)
            if sec_m and cur_ch:
                cur_section = {'title': clean, 'items': []}; cur_ch['sections'].append(cur_section); continue
            im = re.match(r'^([一二三四五六七八九十]+)[、,]\s*(.+)', clean)
            if im and cur_ch and '说明' not in clean:
                it = {'num': im.group(1), 'title': clean}
                if cur_section: cur_section['items'].append(it)
                else: cur_ch['direct_items'].append(it)
        else:
            for col in ['A', 'B']:
                if col in cells:
                    v = str(cells[col]).strip(); vc = re.sub(r'[.]{3,}.*$', '', v).strip()
                    sec_m = re.match(r'^(第[一二三四五六七八九十]+节)\s*(.+)', vc)
                    if sec_m and cur_ch:
                        cur_section = {'title': vc, 'items': []}; cur_ch['sections'].append(cur_section); break
                    im = re.match(r'^([一二三四五六七八九十]+)[、,]\s*(.+)', vc)
                    if im and cur_ch and '说明' not in vc:
                        it = {'num': im.group(1), 'title': vc}
                        if cur_section: cur_section['items'].append(it)
                        else: cur_ch['direct_items'].append(it); break

# Fix Ch5/6
ch5_titles = [
    '一、金属栈（引）桥制作', '二、金属栈（引）桥安装', '三、钢管桩制作', '四、钢梁制作安装',
    '五、陆上钢结构制作安装', '六、钢廊道制作安装', '七、钢撑杆制作安装', '八、靠船钢立柱安装',
    '九、钢联撑安装', '十、钢吊具制作', '十一、钢板桩导梁制作安装', '十二、锚碇钢拉杆制作安装',
    '十三、钢结构除锈', '十四、刷油工程', '十五、钢结构件包覆玻璃钢防腐', '十六、钢拉杆防腐',
    '十七、钢管桩焊接', '十八、钢格板安装']
ch5_items = [{'num': str(i+1), 'title': t} for i, t in enumerate(ch5_titles)]
ch6_items = []
for k in ['第五章', '第六章']:
    if k in toc: ch6_items.extend(toc[k].get('direct_items', []))
toc['第五章'] = {'title': '第五章 钢结构制作及安装工程', 'sections': [], 'direct_items': ch5_items}
toc['第六章'] = {'title': '第六章 其他工程', 'sections': [], 'direct_items': ch6_items}

# Content section scan
sheet_section = {}
current_sec = ''
for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet', ''))):
    snum = int(sn.replace('Sheet', ''))
    if snum < 28: continue
    for row in sd[sn]['rows']:
        vals = [str(v).strip() for v in row['cells'].values()]
        is_full = len(vals) > 1 and all(v == vals[0] for v in vals)
        if is_full:
            t = vals[0].strip(); clean = re.sub(r'[.]{3,}.*$', '', t).strip()
            if re.match(r'^第[一二三四五六七八九十]+节', clean): current_sec = clean; break
        for c in ['A', 'B']:
            if c in row['cells']:
                v = str(row['cells'][c]).strip()
                if re.match(r'^第[一二三四五六七八九十]+节', v): current_sec = v; break
    sheet_section[snum] = current_sec
prev = ''
for snum in sorted(sheet_section.keys()):
    if sheet_section[snum]: prev = sheet_section[snum]
    elif prev: sheet_section[snum] = prev
for snum in sorted(sheet_section.keys()):
    if not sheet_section[snum]:
        ch = '第一章'
        for s in sorted(ch_starts.keys()):
            if snum >= s: ch = ch_starts[s]
        if ch in toc and toc[ch]['sections']: sheet_section[snum] = toc[ch]['sections'][0]['title']

# Table extraction - NO MERGING
tables = []
for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet', ''))):
    snum = int(sn.replace('Sheet', ''))
    if snum <= 27: continue
    if not sd[sn]['rows']: continue
    if not any(str(r['cells'].get('A', '')).strip() == '顺序号' for r in sd[sn]['rows']): continue
    parsed = parse_sheet(sd, sn)
    if parsed is None or not parsed['items']: continue
    ch = '第一章'
    for s in sorted(ch_starts.keys()):
        if snum >= s: ch = ch_starts[s]
    parsed['chapter'] = ch
    parsed['section'] = sheet_section.get(snum, '')
    tables.append(parsed)

# Flatten with attribute extraction
pt = []
ti = 0
for t in tables:
    cn = t['quota_codes']
    if not cn: continue
    cols = sorted(set().union(*[it['vals'].keys() for it in t['items']]), key=lambda x: (len(x), x))
    c2n = {cols[i]: cn[i] for i in range(min(len(cols), len(cn)))}

    # Build per-code attribute values from attr_labels/attr_values
    # Labels sequence: [constant_labels..., value_labels...]
    # Values sequence: [value_dicts...]
    # Pairing: values[j] is labeled by labels[len(al)-len(av)+j]
    al = t.get('attr_labels', [])
    av = t.get('attr_values', [])
    label_offset = max(0, len(al) - len(av))  # extra labels at start are constants
    code_attrs = {}
    for cv in set(c2n.values()):
        labels = []; vals = []
        # Add constant labels (no per-column value variation)
        for j in range(label_offset):
            if j < len(al):
                labels.append(al[j])
                vals.append(al[j])  # the label itself is the constant value
        # Add per-column values paired with their labels
        for j, av_map in enumerate(av):
            for i, col in enumerate(cols):
                if c2n.get(col) == cv and col in av_map:
                    v = av_map[col]
                    if v and v not in vals:
                        vals.append(v)
                        lbl = al[label_offset + j] if (label_offset + j) < len(al) else ''
                        if lbl and lbl not in labels:
                            labels.append(lbl)
        # If values exist but no labels, use values as labels
        if vals and not any(labels):
            labels = vals[:]
        code_attrs[cv] = (labels, vals)

    recs = []
    for item in t['items']:
        for col, val in item['vals'].items():
            if val and val not in ('-', chr(8212), '--', '---'):
                try: amt = float(val.strip('()' + chr(65289) + chr(65288)))
                except: amt = None
                cn_code = c2n.get(col, '?')
                if cn_code != '?':
                    attrs = code_attrs.get(cn_code, ([], []))
                    recs.append({'quota_code': cn_code, 'cost_item': item['name'],
                                 'cost_item_unit': item['unit'], 'cost_item_code': item['code'],
                                 'amount': amt,
                                 'attr_values': attrs[1] + [''] * (4 - len(attrs[1])),
                                 'attr_labels': attrs[0] + [''] * (4 - len(attrs[0])),
                                 'sequence': item['seq']})
    if recs:
        page = int(t.get('sheet', '0').replace('Sheet', '0'))
        pt.append({'row_range': [page, page], 'chapter': t.get('chapter', ''),
                   'section': t.get('section', ''), 'section_title': t.get('section_title', ''),
                   'work_content': t.get('work_content', ''), 'unit': t.get('unit', ''),
                   'notes': t.get('notes', []),
                   'quota_codes': list(dict.fromkeys(r['quota_code'] for r in recs)),
                   'item_count': len(recs), 'items': recs})
        ti += len(recs)

result = {
    'file': str(gp),
    'toc': {k: {'title': v['title'], 'sections': v['sections'],
                'direct_items': v.get('direct_items', [])} for k, v in toc.items()},
    'text_content': [],
    'documents': [{'sheet': 'main', 'table_count': len(pt), 'total_items': ti, 'tables': pt}]
}
op = gp.parent / f'{gp.stem.replace("_grid", "")}_parsed.json'
with open(op, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f'{len(pt)} tables, {ti} items')

# Import
import load_to_sqlite
import importlib
importlib.reload(load_to_sqlite)
db = r'F:\BaiduSyncdisk\2.清单定额\Norms-AI\output\db\norms_jts276-1-2019_excel.sqlite'
try: os.remove(db)
except: pass
load_to_sqlite.load(str(op), db, 'JTS/T 276-1-2019', 'T', False, 'excel')

# Page index all 912
conn = sqlite3.connect(db)
table_pages = {}
for r in conn.execute('SELECT pi.page, pi.table_id, pi.chapter_id FROM page_index pi WHERE pi.table_id IS NOT NULL'):
    table_pages[r[0]] = (r[1], r[2])
chapters = {}
for r in conn.execute('SELECT id, level, title FROM chapter'):
    chapters[r[0]] = (r[1], r[2])


def get_ch(snum):
    ch = '第一章'
    for s in sorted(ch_starts.keys()):
        if snum >= s: ch = ch_starts[s]
    return ch


conn.execute('DELETE FROM page_index')
for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet', ''))):
    snum = int(sn.replace('Sheet', ''));
    rows = sd[sn]['rows']
    if not rows: continue
    pt2 = 'blank'; preview = ''; cid = None; tid = None
    full_texts = []; has_data = False; first_text = ''
    for i, r in enumerate(rows):
        cells = r['cells']; vals = [str(v).strip() for v in cells.values()]
        if i == 0: fv = [v for v in vals if v]; first_text = fv[0][:80] if fv else ''
        if len(vals) > 1 and all(v == vals[0] for v in vals): full_texts.append(vals[0])
        if str(cells.get('A', '')).strip() == '顺序号': has_data = True
    has_ch = any(re.search(r'第[一二三四五六七八九十]+章', t) for t in full_texts)
    has_sec = any(re.search(r'第[一二三四五六七八九十]+节', t) for t in full_texts)
    has_cont = any('续表' in t for t in full_texts)
    if snum <= 5: pt2 = 'cover'; preview = first_text
    elif snum <= 9: pt2 = 'notice'; preview = first_text
    elif snum <= 23: pt2 = 'toc'; preview = first_text
    elif snum <= 27: pt2 = 'general_instruction'; preview = first_text
    elif snum >= 907: pt2 = 'appendix'; preview = first_text
    elif has_data and has_cont: pt2 = 'continued_table'; preview = '续表'
    elif has_data: pt2 = 'norms_table'; preview = first_text
    elif has_ch:
        pt2 = 'chapter_title'
        preview = ([t for t in full_texts if re.search(r'第[一二三四五六七八九十]+章', t)] + [first_text])[0][:80]
    elif has_sec:
        pt2 = 'section_intro'
        preview = ([t for t in full_texts if re.search(r'第[一二三四五六七八九十]+节', t)] + [first_text])[0][:80]
    elif full_texts: pt2 = 'section_intro'; preview = full_texts[0][:80]
    elif first_text: pt2 = 'section_intro'; preview = first_text
    if snum in table_pages: tid, _ = table_pages[snum]
    if cid is None and snum >= 28:
        ch = get_ch(snum)
        for cid2, (lev, title) in chapters.items():
            if lev == 1 and ch in title: cid = cid2; break
    if pt2 == 'continued_table' and not tid:
        for prev_p in range(snum - 1, 0, -1):
            if prev_p in table_pages:
                tid_prev, cid_prev = table_pages[prev_p]
                cid = cid_prev; break
    conn.execute('INSERT INTO page_index(page,page_type,chapter_id,table_id,text_preview,ocr_status) VALUES(?,?,?,?,?,?)',
                 (snum, pt2, cid, tid, preview[:200] if preview else '', 'excel'))

# Fix section_intro/chapter_title pages to point to L2 sections
l2_map={}
for r in conn.execute('SELECT c2.id,c2.title,c1.title as ch FROM chapter c2 JOIN chapter c1 ON c2.parent_id=c1.id WHERE c2.level=2'):
    l2_map[r[2]]=l2_map.get(r[2],[])+[(r[0],r[1])]
for r in conn.execute('SELECT page,chapter_id,text_preview,page_type FROM page_index WHERE page_type IN ("section_intro","chapter_title")'):
    preview=r[2] if r[2] else ''
    cid=r[1]
    ch_title=conn.execute('SELECT title FROM chapter WHERE id=?',(cid,)).fetchone()
    ch_title=ch_title[0] if ch_title else ''
    if ch_title in l2_map:
        for l2_id,l2_title in l2_map[ch_title]:
            if l2_title in preview or preview in l2_title:
                conn.execute('UPDATE page_index SET chapter_id=? WHERE page=?',(l2_id,r[0]))
                break
# For remaining section_intro at L1, use sheet_section mapping
for snum,sec_title in sheet_section.items():
    ch='第一章'
    for s in sorted(ch_starts.keys()):
        if snum>=s: ch=ch_starts[s]
    if sec_title and ch in l2_map:
        for l2_id,l2_title in l2_map[ch]:
            if l2_title==sec_title:
                conn.execute('UPDATE page_index SET chapter_id=? WHERE page=? AND page_type IN ("section_intro","chapter_title") AND chapter_id IN (SELECT id FROM chapter WHERE level=1)',
                            (l2_id,snum))
                break

conn.commit()

# Fix: match section_intro and chapter_title pages to L2 via sheet_section
ch_short_to_full = {k: v['title'] for k, v in toc.items()}
l2_map = {}
for r in conn.execute('SELECT c2.id, c2.title, c1.title FROM chapter c2 JOIN chapter c1 ON c2.parent_id = c1.id WHERE c2.level = 2'):
    l2_map[(r[2], r[1])] = r[0]
for r in conn.execute('SELECT page, page_type FROM page_index WHERE page_type IN (\"section_intro\", \"chapter_title\") AND chapter_id IN (SELECT id FROM chapter WHERE level = 1)'):
    snum = r[0]; sec = sheet_section.get(snum, '')
    if not sec: continue
    ch_short = '第一章'
    for s in sorted(ch_starts.keys()):
        if snum >= s: ch_short = ch_starts[s]
    ch_full = ch_short_to_full.get(ch_short, ch_short)
    key = (ch_full, sec)
    if key in l2_map:
        conn.execute('UPDATE page_index SET chapter_id = ? WHERE page = ?', (l2_map[key], snum))
conn.commit()

for r in conn.execute('SELECT page_type, COUNT(*) FROM page_index GROUP BY page_type ORDER BY COUNT(*) DESC'):
    print(f'{r[0]}: {r[1]}')
total_pages = conn.execute("SELECT COUNT(*) FROM page_index").fetchone()[0]
l2_tables = conn.execute(
    'SELECT COUNT(*) FROM norms_table nt JOIN chapter c ON nt.chapter_id=c.id WHERE c.level=2').fetchone()[0]
total_tables = conn.execute("SELECT COUNT(*) FROM norms_table").fetchone()[0]
print(f'Total: {total_pages} pages, {total_tables} tables ({l2_tables} at L2)')

# Verify P545-560
for r in conn.execute('SELECT page, page_type, chapter_id, table_id FROM page_index WHERE page BETWEEN 545 AND 560 ORDER BY page'):
    ch_title = conn.execute('SELECT title FROM chapter WHERE id=?', (r[2],)).fetchone() if r[2] else None
    st = conn.execute('SELECT section_title FROM norms_table WHERE id=?', (r[3],)).fetchone() if r[3] else None
    print(f'P{r[0]}: {r[1]:20s} ch={ch_title[0][:25] if ch_title else "?"} | {st[0][:40] if st else ""}')

conn.close()
print('DONE - restart.bat')
