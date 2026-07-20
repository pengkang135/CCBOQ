"""Extract JTS/T 276-1-2019 main quota (912-sheet paginated format).
Adapts the extract_ref_final.py approach for the main quota's structure."""
import json, re, sys
from pathlib import Path
from collections import OrderedDict, Counter

sys.path.insert(0, str(Path(__file__).parent))
from extract_ref_final import parse_sheet

def extract_main(gp, op=None):
    gp = Path(gp)
    with open(gp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if op is None:
        op = gp.parent / f'{gp.stem.replace("_grid","")}_parsed.json'
    sd = data.get('sheets', {})

    # TOC: sheets 10-23
    toc = OrderedDict()
    cur_ch = None
    for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet',''))):
        snum = int(sn.replace('Sheet',''))
        if snum < 10 or snum > 23: continue
        cur_section = None
        for row in sd[sn]['rows']:
            cells = row['cells']; vals = [str(v).strip() for v in cells.values()]
            is_full = len(vals) > 1 and all(v == vals[0] for v in vals)
            raw_text = vals[0] if is_full else ''
            if not raw_text:
                non_empty = [str(v).strip() for v in cells.values() if str(v).strip()]
                raw_text = ' '.join(non_empty) if non_empty else ''
            if not raw_text: continue
            clean = re.sub(r'[.]{3,}.*$', '', raw_text).strip()
            clean = re.sub(r'\s*[-]\s*\d+\s*[-]?\s*$', '', clean).strip()
            if not clean: continue
            ch_m = re.match(r'^(第[一二三四五六七八九十]+章)\s*(.+)', clean)
            if ch_m:
                cur_ch = {'title': clean, 'sections': [], 'direct_items': []}
                toc[ch_m.group(1)] = cur_ch; cur_section = None; continue
            if is_full:
                sec_hdr = re.match(r'^(第[一二三四五六七八九十]+节)\s*(.+)', clean)
                if sec_hdr and cur_ch:
                    cur_section = {'title': clean, 'items': []}
                    cur_ch['sections'].append(cur_section); continue
            # Numbered item - check full-merge text first, then columns
            item_texts = [clean] if is_full else [str(cells.get(c,'')).strip() for c in ['A','B'] if str(cells.get(c,'')).strip()]
            for it_text in item_texts:
                if not it_text: continue
                it_clean = re.sub(r'[.]{3,}.*$', '', it_text).strip()
                im = re.match(r'^([一二三四五六七八九十]+)[、，,]\s*(.+)', it_clean)
                if im:
                    it = {'num': im.group(1), 'title': it_clean}
                    if cur_section: cur_section['items'].append(it)
                    elif cur_ch and '说明' not in it_clean: cur_ch['direct_items'].append(it)
                    break
    total_sec = sum(len(ch['sections']) for ch in toc.values())
    total_it = sum(sum(len(s.get('items',[])) for s in ch.get('sections',[])) + len(ch.get('direct_items',[])) for ch in toc.values())
    print(f"TOC: {len(toc)} ch, {total_sec} sections, {total_it} items")

    # Chapter boundaries (actual content start sheets)
    ch_starts = {28: '第一章', 197: '第二章', 534: '第三章', 712: '第四章', 796: '第五章', 832: '第六章'}
    ch_ord = ['第一章', '第二章', '第三章', '第四章', '第五章', '第六章']

    def get_ch(snum):
        cur = 0
        for s in sorted(ch_starts.keys()):
            if snum >= s: cur = ch_ord.index(ch_starts[s])
        return ch_ord[cur]

    # Text content
    texts = []
    for sn_range, tp in [([6, 7, 8], 'notice'), ([24, 25, 26, 27], 'general_instruction'),
                         ([907, 908, 909, 910, 911, 912], 'appendix')]:
        content = []
        for sn in [f'Sheet{i}' for i in sn_range]:
            if sn not in sd: continue
            for row in sd[sn]['rows']:
                m = None
                vals = [str(v).strip() for v in row['cells'].values()]
                if len(vals) > 1 and all(v == vals[0] for v in vals):
                    m = vals[0]
                else:
                    vals2 = [str(v).strip() for v in row['cells'].values() if str(v).strip()]
                    if vals2: m = ' '.join(vals2)
                if m and not m.strip().startswith('-'):
                    content.append(m.strip())
        if content:
            texts.append({'type': tp, 'title': content[0][:40] if content else '',
                         'content': '\n'.join(content)})
    print(f'Texts: {len(texts)}')

    # Data sheets
    skip = set(range(1, 28)) | set(ch_starts.keys())
    data_sheets = []
    for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet',''))):
        snum = int(sn.replace('Sheet',''))
        if snum in skip: continue
        rows = sd[sn]['rows']
        if not rows: continue
        has_data = any(str(r['cells'].get('A', '')).strip() == '顺序号' for r in rows)
        if has_data: data_sheets.append(sn)
    print(f'Data sheets: {len(data_sheets)}')

    # Parse and chain
    tables = []
    cur_t = None
    for sn in data_sheets:
        parsed = parse_sheet(sd, sn)
        if parsed is None: continue
        if not parsed['items'] and not parsed['is_continued']: continue
        if parsed['is_continued'] and cur_t:
            cur_t['items'].extend(parsed['items'])
            if parsed['unit'] and not cur_t['unit']: cur_t['unit'] = parsed['unit']
            if parsed['notes']: cur_t['notes'].extend(parsed['notes'])
        else:
            if cur_t: tables.append(cur_t)
            cur_t = parsed
    if cur_t: tables.append(cur_t)
    print(f'Tables (chained): {len(tables)}')

    # Flatten
    pt = []; ti = 0; pn = 1
    for chain in tables:
        cn = chain['quota_codes']
        if not cn: continue
        cols = sorted(set().union(*[it['vals'].keys() for it in chain['items']]),
                      key=lambda x: (len(x), x))
        c2n = {cols[i]: cn[i] for i in range(min(len(cols), len(cn)))}
        code_attrs = {}
        for cv in set(c2n.values()):
            labels = []; vals = []
            for i, col in enumerate(cols):
                if c2n.get(col) == cv:
                    for j, av in enumerate(chain['attr_values']):
                        if col in av:
                            vals.append(av[col])
                            if j < len(chain['attr_labels']):
                                if chain['attr_labels'][j] not in labels:
                                    labels.append(chain['attr_labels'][j])
            code_attrs[cv] = (labels, vals)
        recs = []
        for item in chain['items']:
            for col, val in item['vals'].items():
                if val and val not in ('-', chr(8212), '--', '---', chr(8230), '...'):
                    try:
                        amt = float(val.strip('()' + chr(65289) + chr(65288)))
                    except:
                        amt = None
                    cn_code = c2n.get(col, '?')
                    if cn_code != '?':
                        attrs = code_attrs.get(cn_code, ([], []))
                        recs.append({
                            'quota_code': cn_code, 'cost_item': item['name'],
                            'cost_item_unit': item['unit'], 'cost_item_code': item['code'],
                            'amount': amt,
                            'attr_values': attrs[1] + [''] * (4 - len(attrs[1])),
                            'attr_labels': attrs[0] + [''] * (4 - len(attrs[0])),
                            'sequence': item['seq']
                        })
        if recs:
            snum = int(chain['sheet'].replace('Sheet', ''))
            codes = list(dict.fromkeys(r['quota_code'] for r in recs))
            pt.append({
                'row_range': [pn, pn], 'chapter': get_ch(snum),
                'section_title': chain['section_title'],
                'subsection': chain['subsection'],
                'work_content': chain['work_content'], 'unit': chain['unit'],
                'notes': chain['notes'], 'quota_codes': codes,
                'attr_labels': chain['attr_labels'],
                'attr_values': [dict(av) for av in chain['attr_values']],
                'item_count': len(recs), 'items': recs
            })
            pn += 1; ti += len(recs)

    result = {
        'file': str(gp),
        'toc': {k: {'title': v['title'], 'sections': v['sections']}
                for k, v in toc.items()},
        'text_content': texts,
        'documents': [{'sheet': 'main', 'table_count': len(pt),
                       'total_items': ti, 'tables': pt}]
    }
    with open(op, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'\nOutput: {len(pt)} tables, {ti} items')
    ch_dist = Counter(t['chapter'] for t in pt)
    for ch, cnt in ch_dist.most_common():
        items = sum(t['item_count'] for t in pt if t['chapter'] == ch)
        print(f'  {ch}: {cnt} tables, {items} items')
    print(f'Saved: {op}')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('grid_json')
    ap.add_argument('-o', '--output')
    args = ap.parse_args()
    if not __import__('os').path.exists(args.grid_json):
        print('Not found'); sys.exit(1)
    extract_main(args.grid_json, args.output)
