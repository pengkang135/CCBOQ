"""Rebuild main quota from complete TOC analysis (sheets 10-23)."""
import json, re, sys, sqlite3, os
from pathlib import Path
from collections import OrderedDict, Counter

sys.path.insert(0, str(Path(__file__).parent))
from extract_ref_final import parse_sheet

gp = Path(r'F:\BaiduSyncdisk\2.清单定额\1 预算定额\3 水工定额\JTS∕T 276-1-2019 沿海港口水工建筑工程定额（非正式出版稿）_grid.json')
with open(gp, 'r', encoding='utf-8') as f:
    data = json.load(f)
sd = data['sheets']

ch_starts = {28: '第一章', 197: '第二章', 534: '第三章', 712: '第四章', 796: '第五章', 832: '第六章'}

# ── Parse TOC from sheets 10-23 (definitive book TOC) ──
toc = OrderedDict(); cur_ch = None; cur_section = None

for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet', ''))):
    snum = int(sn.replace('Sheet', ''))
    if snum < 10 or snum > 23: continue
    for row in sd[sn]['rows']:
        cells = row['cells']; vals = [str(v).strip() for v in cells.values()]
        is_full = len(vals) > 1 and all(v == vals[0] for v in vals)

        if is_full:
            text = vals[0].strip()
            clean = re.sub(r'[.]{3,}.*$', '', text).strip()
            clean = re.sub(r'\s*[-]\s*\d+\s*[-]?\s*$', '', clean).strip()
            if not clean: continue
            ch_m = re.match(r'^(第[一二三四五六七八九十]+章)\s*(.+)', clean)
            if ch_m:
                cn = ch_m.group(1)
                if cn not in toc: toc[cn] = {'title': clean, 'sections': [], 'direct_items': []}
                cur_ch = toc[cn]; cur_section = None; continue
            sec_m = re.match(r'^(第[一二三四五六七八九十]+节)\s*(.+)', clean)
            if sec_m and cur_ch:
                cur_section = {'title': clean, 'items': []}
                cur_ch['sections'].append(cur_section); continue
            im = re.match(r'^([一二三四五六七八九十]+)[、,]\s*(.+)', clean)
            if im and cur_ch and '说明' not in clean:
                it = {'num': im.group(1), 'title': clean}
                if cur_section: cur_section['items'].append(it)
                else: cur_ch['direct_items'].append(it)
            continue

        # Column-based
        for col in ['A', 'B']:
            if col not in cells: continue
            v = str(cells[col]).strip()
            vc = re.sub(r'[.]{3,}.*$', '', v).strip()
            sec_m = re.match(r'^(第[一二三四五六七八九十]+节)\s*(.+)', vc)
            if sec_m and cur_ch:
                cur_section = {'title': vc, 'items': []}
                cur_ch['sections'].append(cur_section); break
            im = re.match(r'^([一二三四五六七八九十]+)[、,]\s*(.+)', vc)
            if im and cur_ch and '说明' not in vc:
                it = {'num': im.group(1), 'title': vc}
                if cur_section: cur_section['items'].append(it)
                else: cur_ch['direct_items'].append(it); break


# Fix: if Chapter 6 is missing, split Ch5's direct_items (first 18 = Ch5, rest = Ch6)
# Force-add Chapter 6 and split Ch5 items
if '第六章' not in toc:
    toc['第六章'] = {'title': '第六章 其他工程', 'sections': [], 'direct_items': []}
if '第五章' in toc:
    ch5_dirs = toc['第五章'].get('direct_items', [])
    ch5_keep = ch5_dirs[:18]
    ch6_items = ch5_dirs[18:]
    toc['第五章']['direct_items'] = ch5_keep
    if ch6_items:
        toc['第六章']['direct_items'] = ch6_items
    print(f'Split Ch5->6: {len(ch5_keep)}+{len(ch6_items)} items')

for ch_name, ch in toc.items():
    secs = len(ch['sections']); its = sum(len(s['items']) for s in ch['sections'])
    dirs = len(ch['direct_items'])
    print(f"{ch_name}: {secs} sec, {its} items, {dirs} direct")

# ── Sheet→section mapping (content sheets 28+) ──
sheet_section = {}; current_sec = ''
for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet', ''))):
    snum = int(sn.replace('Sheet', ''))
    if snum < 28: continue
    for row in sd[sn]['rows']:
        vals = [str(v).strip() for v in row['cells'].values()]
        is_full = len(vals) > 1 and all(v == vals[0] for v in vals)
        if is_full:
            t = vals[0].strip(); clean = re.sub(r'[.]{3,}.*$', '', t).strip()
            if re.match(r'^第[一二三四五六七八九十]+节', clean):
                current_sec = clean; break
        # Also check columns for section headers
        for c in ['A','B']:
            if c in row['cells']:
                v = str(row['cells'][c]).strip()
                if re.match(r'^第[一二三四五六七八九十]+节', v):
                    current_sec = v; break
    sheet_section[snum] = current_sec

# Backfill
prev = ''
for snum in sorted(sheet_section.keys()):
    if sheet_section[snum]: prev = sheet_section[snum]
    elif prev: sheet_section[snum] = prev

# TOC first section for sheets before any content section
for snum in sorted(sheet_section.keys()):
    if not sheet_section[snum]:
        ch = '第一章'
        for s in sorted(ch_starts.keys()):
            if snum >= s: ch = ch_starts[s]
        if ch in toc and toc[ch]['sections']:
            sheet_section[snum] = toc[ch]['sections'][0]['title']

# ── Table extraction ──
data_sheets = []
for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet', ''))):
    snum = int(sn.replace('Sheet', ''))
    if snum <= 27: continue
    if not sd[sn]['rows']: continue
    if any(str(r['cells'].get('A', '')).strip() == '顺序号' for r in sd[sn]['rows']):
        data_sheets.append(sn)

tables = []
for sn in data_sheets:
    parsed = parse_sheet(sd, sn)
    if parsed is None: continue
    if not parsed['items']: continue
    snum = int(sn.replace('Sheet', ''))
    ch = '第一章'
    for s in sorted(ch_starts.keys()):
        if snum >= s: ch = ch_starts[s]
    sec = sheet_section.get(snum, '')
    parsed['chapter'] = ch
    parsed['section'] = sec
    tables.append(parsed)

# ── Flatten ──
pt = []; ti = 0
for chain in tables:
    try: page_num = int(chain.get('sheet', '').replace('Sheet', ''))
    except: page_num = 0
    cn = chain['quota_codes']
    if not cn: continue
    cols = sorted(set().union(*[it['vals'].keys() for it in chain['items']]), key=lambda x: (len(x), x))
    c2n = {cols[i]: cn[i] for i in range(min(len(cols), len(cn)))}
    code_attrs = {}
    for cv in set(c2n.values()):
        labels = []; vals = []
        for i, col in enumerate(cols):
            if c2n.get(col) == cv:
                for j, av in enumerate(chain.get('attr_values', [])):
                    if col in av:
                        vals.append(av[col])
                        if j < len(chain.get('attr_labels', [])):
                            if chain['attr_labels'][j] not in labels: labels.append(chain['attr_labels'][j])
        code_attrs[cv] = (labels, vals)
    recs = []
    for item in chain['items']:
        for col, val in item['vals'].items():
            if val and val not in ('-', chr(8212), '--', '---'):
                try: amt = float(val.strip('()' + chr(65289) + chr(65288)))
                except: amt = None
                cn_code = c2n.get(col, '?')
                if cn_code != '?':
                    attrs = code_attrs.get(cn_code, ([], []))
                    recs.append({'quota_code': cn_code, 'cost_item': item['name'], 'cost_item_unit': item['unit'],
                                 'cost_item_code': item['code'], 'amount': amt,
                                 'attr_values': attrs[1] + [''] * (4 - len(attrs[1])),
                                 'attr_labels': attrs[0] + [''] * (4 - len(attrs[0])), 'sequence': item['seq']})
    if recs:
        pt.append({'row_range': [page_num, page_num], 'chapter': chain.get('chapter', ''),
                   'section': chain.get('section', ''), 'section_title': chain.get('section_title', ''),
                   'work_content': chain.get('work_content', ''), 'unit': chain.get('unit', ''),
                   'notes': chain.get('notes', []),
                   'quota_codes': list(dict.fromkeys(r['quota_code'] for r in recs)),
                   'item_count': len(recs), 'items': recs})
        ti += len(recs)

# Text
texts = []
for sn_range, tp in [([6, 7, 8], 'notice'), ([24, 25, 26, 27], 'general_instruction'), ([907, 908, 909, 910, 911, 912], 'appendix')]:
    content = []
    for sn in [f'Sheet{i}' for i in sn_range]:
        if sn not in sd: continue
        for row in sd[sn]['rows']:
            m = None; vals = [str(v).strip() for v in row['cells'].values()]
            if len(vals) > 1 and all(v == vals[0] for v in vals): m = vals[0]
            else:
                vals2 = [str(v).strip() for v in row['cells'].values() if str(v).strip()]
                if vals2: m = ' '.join(vals2)
            if m and not m.strip().startswith('-'): content.append(m.strip())
    if content: texts.append({'type': tp, 'title': content[0][:40] if content else '', 'content': '\n'.join(content)})

result = {'file': str(gp),
          'toc': {k: {'title': v['title'], 'sections': v['sections'], 'direct_items': v.get('direct_items', [])} for k, v in toc.items()},
          'text_content': texts,
          'documents': [{'sheet': 'main', 'table_count': len(pt), 'total_items': ti, 'tables': pt}]}
op = gp.parent / f'{gp.stem.replace("_grid", "")}_parsed.json'
with open(op, 'w', encoding='utf-8') as f: json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\nTables: {len(pt)}, Items: {ti}")

# Import
import load_to_sqlite, importlib; importlib.reload(load_to_sqlite)
db_path = r'F:\BaiduSyncdisk\2.清单定额\Norms-AI\output\db\norms_jts276-1-2019_excel.sqlite'
try: os.remove(db_path)
except: pass
load_to_sqlite.load(str(op), db_path, 'JTS/T 276-1-2019 主定额', 'JTS/T 276-1-2019-EXCEL', False, 'excel')

conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT level, COUNT(*) FROM chapter GROUP BY level ORDER BY level'):
    print(f"  L{r[0]}: {r[1]}")
for r in conn.execute('SELECT c.level, COUNT(nt.id) FROM norms_table nt JOIN chapter c ON nt.chapter_id=c.id GROUP BY c.level'):
    print(f"  Tables L{r[0]}: {r[1]}")

l1 = conn.execute("SELECT id,title FROM chapter WHERE level=1 AND title LIKE '%土石%'").fetchone()
if l1:
    print(f"\n{l1[1][:50]}")
    for l2 in conn.execute('SELECT id,title FROM chapter WHERE parent_id=? ORDER BY sort_order', (l1['id'],)):
        tc = conn.execute('SELECT COUNT(*) FROM norms_table WHERE chapter_id=?', (l2['id'],)).fetchone()[0]
        print(f"  {l2[1][:50]} -> {tc} tables")
conn.close()
print("DONE")
