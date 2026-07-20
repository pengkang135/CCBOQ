"""Final Claude-verified extraction of JTS/T 276-3 reference quota.
Based on complete analysis of all 60 data sheets. Handles all known patterns.
"""
import json, re, sys
from pathlib import Path
from collections import OrderedDict, Counter

def cl(v):
    """Clean cell value: strip newlines, whitespace, leading dots"""
    s = str(v).replace('\n', ' ').replace('\r', ' ').strip()
    s = s.lstrip('. ')
    return s

def fm(cells):
    vals = [cl(v) for v in cells.values()]
    return vals[0] if len(vals) >= 2 and all(v == vals[0] for v in vals) else None

def dc(cells):
    return sorted([k for k in cells.keys() if k >= 'E'], key=lambda x: (len(x), x))

def find_unit(text):
    """Extract unit from end of work content text. Handles '1t', '10根', '10 根', '100m3' etc."""
    tokens = text.strip().split()
    for n in range(min(3, len(tokens)), 0, -1):
        candidate = ''.join(tokens[-n:])
        # At least 1 digit + at least 1 letter/Chinese char; not just a lone digit
        if re.match(r'^\d+[a-zA-Z²³̂̃一-鿿]{1,8}$', candidate):
            return candidate
    if tokens:
        last = tokens[-1].rstrip('.')
        if re.match(r'^\d+[a-zA-Z²³̂̃一-鿿]{1,8}$', last):
            return last
    return None

def looks_like_label(vals):
    """Check if a set of values looks like attribute labels (not values)."""
    sample = ' '.join(vals)
    # Contains Chinese measurement/classification characters
    label_chars = '长宽高深厚径截面级类别土岩型号围'
    return any(c in sample for c in label_chars) and not any(v.replace('.','',1).lstrip('-').isdigit() for v in vals)

def parse_sheet(sd, sn):
    """Parse a single sheet into structured data. Handles all known patterns."""
    rows = sd[sn]['rows']
    if not rows: return None

    result = {
        'sheet': sn, 'section_title': '', 'subsection': '',
        'work_content': '', 'unit': '', 'quota_codes': [],
        'attr_labels': [], 'attr_values': [], 'notes': [], 'items': [],
        'is_continued': False
    }

    header_seen = False; data_cols = []

    for i, row in enumerate(rows):
        cells = row['cells']; m = fm(cells); a = str(cells.get('A','')).strip()

        # Skip page numbers
        if m and re.search(r'^[-]\s*\d+\s*[-]?$', m.strip()): continue

        # Row 0: section title or "续表"
        if i == 0:
            if m and '续表' in m:
                result['is_continued'] = True
                u = find_unit(m.strip())
                if u: result['unit'] = u
                continue
            if m:
                result['section_title'] = m.strip()
                continue

        # Work content row
        if m and '工程内容' in m:
            result['work_content'] = m.strip()
            u = find_unit(m.strip())
            if u:
                result['unit'] = u
                idx = result['work_content'].rfind(u)
                if idx > 0:
                    result['work_content'] = result['work_content'][:idx].rstrip()
            continue

        # Notes
        if m and '注' in m[:3]:
            result['notes'].append(m.strip())
            continue

        # Header row
        if a == '顺序号':
            b = cl(cells.get('B',''))
            c_val = cl(cells.get('C',''))

            if '定额编号' in b:
                data_cols = dc(cells)
                # Only keep columns with numeric codes (filter out text descriptor columns like E="细平")
                code_cols = []
                nums = []
                for c in data_cols:
                    v = cl(cells.get(c, ''))
                    v_clean = re.sub(r'[.\s]+', '', v)
                    v_clean = v_clean.replace('l', '1').replace('O', '0')
                    if v_clean.isdigit():
                        nums.append(v_clean)
                        code_cols.append(c)
                if nums:
                    result['quota_codes'] = nums
                    data_cols = code_cols  # only use columns that have codes
                header_seen = True
                continue

            if header_seen and b == '项目':
                vals = OrderedDict()
                for c in data_cols:
                    v = cl(cells.get(c, ''))
                    if v:
                        vals[c] = v
                if not vals: continue
                unique = list(dict.fromkeys(vals.values()))
                # Label row: same value across all columns that looks like a label
                if len(unique) == 1 and looks_like_label(unique):
                    result['attr_labels'].append(unique[0])
                else:
                    # Value row: per-column values (may include digits or same-value across columns)
                    result['attr_values'].append(vals)
                continue

        # Data row
        if a.isdigit() and int(a) >= 1:
            b = cl(cells.get('B',''))
            if not b: continue
            item = {
                'seq': int(a),
                'name': b,
                'unit': cl(cells.get('C','')),
                'code': cl(cells.get('D','')),
                'vals': {}
            }
            for c in data_cols:
                if c in cells:
                    item['vals'][c] = cl(cells.get(c, ''))
            result['items'].append(item)

    return result


def chain_and_flatten(sd):
    """Chain continued sheets and flatten to 1D records."""
    data_sheets = []
    for sn in sorted(sd.keys(), key=lambda x: int(x.replace('Sheet','')) if x.startswith('Sheet') else 999):
        snum = int(sn.replace('Sheet',''))
        if snum <= 11: continue
        parsed = parse_sheet(sd, sn)
        if parsed is None: continue
        if not parsed['items'] and not parsed['is_continued']: continue
        data_sheets.append(parsed)

    # Chain continued tables
    chains = []; cur = None
    for p in data_sheets:
        if p['is_continued'] and cur:
            cur['items'].extend(p['items'])
            if p['unit'] and not cur['unit']: cur['unit'] = p['unit']
            if p['notes']: cur['notes'].extend(p['notes'])
        else:
            if cur: chains.append(cur)
            cur = p
    if cur: chains.append(cur)

    # Chapter assignment from sheet numbers
    ch_ord = ['第一章','第二章','第三章','第四章','第五章','第六章']
    ch_starts = {10:0, 24:1, 60:2, 64:3, 70:4, 82:5}
    def get_ch(sn):
        s = int(sn.replace('Sheet',''))
        cur_ch = 0
        for start, idx in sorted(ch_starts.items()):
            if s >= start: cur_ch = idx
        return ch_ord[cur_ch]

    # Flatten to 1D records
    tables = []; total_items = 0; page = 1
    for chain in chains:
        cn = chain['quota_codes']
        if not cn: continue

        cols = sorted(set().union(*[it['vals'].keys() for it in chain['items']]),
                      key=lambda x: (len(x), x))
        c2n = {cols[i]: cn[i] for i in range(min(len(cols), len(cn)))}

        # Build per-code attribute values
        code_attrs = {}
        for code_val in set(c2n.values()):
            labels = []; vals = []
            for i, col in enumerate(cols):
                if c2n.get(col) == code_val:
                    for j, av in enumerate(chain['attr_values']):
                        if col in av:
                            vals.append(av[col])
                            if j < len(chain['attr_labels']):
                                if chain['attr_labels'][j] not in labels:
                                    labels.append(chain['attr_labels'][j])
            code_attrs[code_val] = (labels, vals)

        recs = []
        for item in chain['items']:
            for col, val in item['vals'].items():
                if val and val not in ('-','—','--','---','…','...'):
                    try: amt = float(val.strip('()（）'))
                    except: amt = None
                    cn_code = c2n.get(col, '?')
                    if cn_code != '?':
                        attrs = code_attrs.get(cn_code, ([], []))
                        pad_vals = attrs[1] + ['']*(4-len(attrs[1]))
                        pad_lbls = attrs[0] + ['']*(4-len(attrs[0]))
                        recs.append({
                            'quota_code': cn_code,
                            'cost_item': item['name'],
                            'cost_item_unit': item['unit'],
                            'cost_item_code': item['code'],
                            'amount': amt,
                            'attr_values': pad_vals[:4],
                            'attr_labels': pad_lbls[:4],
                            'sequence': item['seq']
                        })

        if recs:
            codes = list(dict.fromkeys(r['quota_code'] for r in recs))
            tables.append({
                'row_range': [page, page],
                'chapter': get_ch(chain['sheet']),
                'section_title': chain['section_title'],
                'subsection': chain['subsection'],
                'work_content': chain['work_content'],
                'unit': chain['unit'],
                'notes': chain['notes'],
                'quota_codes': codes,
                'attr_labels': chain['attr_labels'],
                'attr_values': [dict(av) for av in chain['attr_values']],
                'item_count': len(recs),
                'items': recs
            })
            page += 1; total_items += len(recs)

    return tables, total_items


def extract(grid_path, output_path=None):
    gp = Path(grid_path)
    with open(gp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if output_path is None:
        output_path = gp.parent / f'{gp.stem.replace("_grid","")}_parsed.json'

    sd = data.get('sheets', {})

    # Extract TOC from sheets 6-7
    toc = OrderedDict()
    cur_ch = None
    for sn in ['Sheet6', 'Sheet7']:
        if sn not in sd: continue
        for row in sd[sn]['rows']:
            m = fm(row['cells'])
            if not m: continue
            t = m.strip()
            # Also check non-full-merge rows (Sheet7 has column B text)
            if not t:
                vals = [str(v).strip() for v in row['cells'].values() if str(v).strip()]
                t = ' '.join(vals) if vals else ''
            if not t or '目' in t[:3] or (len(t)<=6 and t.startswith('-')): continue
            clean = re.sub(r'[.]{3,}.*$', '', t).strip()
            clean = re.sub(r'\s*[-]\s*\d+\s*[-]?\s*$', '', clean).strip()
            if not clean: continue
            ch_m = re.match(r'^(第[一二三四五六七八九十]+章)\s*(.+)', clean)
            if ch_m:
                cur_ch = {'title': clean, 'sections': []}
                toc[ch_m.group(1)] = cur_ch
                continue
            sec_m = re.match(r'^([一二三四五六七八九十]+)[、]\s*(.+)', clean)
            if sec_m and cur_ch:
                cur_ch['sections'].append({'num': sec_m.group(1), 'title': clean})
                continue
            if '总说明' in clean and '总说明' not in toc:
                toc['总说明'] = {'title': '总说明', 'sections': []}

    # Extract text content
    texts = []
    if 'Sheet8' in sd:
        content = []
        for row in sd['Sheet8']['rows']:
            m = fm(row['cells'])
            if m and not m.strip().startswith('-') and m.strip() != '总说明':
                content.append(m.strip())
        if content:
            texts.append({'type': 'general_instruction', 'title': '总说明', 'content': '\n'.join(content)})

    for sn in ['Sheet5','Sheet82','Sheet83','Sheet84','Sheet85','Sheet86','Sheet87']:
        if sn not in sd: continue
        content = []; title = ''
        for row in sd[sn]['rows']:
            m = fm(row['cells'])
            if m and not m.strip().startswith('-'):
                if not title: title = m.strip()[:40]
                content.append(m.strip())
            else:
                vals = [str(v).strip() for v in row['cells'].values() if str(v).strip()]
                if vals: content.append(' '.join(vals))
        if content:
            tp = 'appendix' if any(kw in ''.join(content) for kw in ['附注','附加']) else 'chapter_text'
            texts.append({'type': tp, 'title': title, 'content': '\n'.join(content)})

    # Parse and flatten tables
    tables, ti = chain_and_flatten(sd)

    result = {
        'file': str(gp),
        'toc': {k: {'title': v['title'], 'sections': v['sections']} for k, v in toc.items()},
        'text_content': texts,
        'documents': [{'sheet': 'ref', 'table_count': len(tables), 'total_items': ti, 'tables': tables}]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'TOC: {len(toc)} ch | Texts: {len(texts)} | Tables: {len(tables)} | Items: {ti}')
    print(f'Codes: {len(set(r["quota_code"] for t in tables for r in t["items"]))}')
    ch_dist = Counter(t['chapter'] for t in tables)
    for ch, cnt in ch_dist.most_common():
        items = sum(t['item_count'] for t in tables if t['chapter']==ch)
        print(f'  {ch}: {cnt} tables, {items} items')

    bad = [t for t in tables if any(r['quota_code']=='?' for r in t['items'])]
    print(f'Bad codes: {len(bad)} tables')

    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('grid_json'); ap.add_argument('-o','--output')
    args = ap.parse_args()
    if not __import__('os').path.exists(args.grid_json):
        print('Not found'); sys.exit(1)
    extract(args.grid_json, args.output)
