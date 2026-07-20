#!/usr/bin/env python3
"""Phase A2: Coordinate clustering + column alignment.
Converts PyMuPDF text+coordinate JSON to column-aligned clustered JSON.

Usage:
  python cluster_columns.py --text-dir output/text/ --output output/clustered/
  python cluster_columns.py --text-dir output/text/ --output output/clustered/ --pages 44-100
"""

import json, sys, re, os, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def group_by_y(lines, tolerance=5):
    groups = []
    for line in sorted(lines, key=lambda l: (l['y'], l['x'])):
        placed = False
        for grp in groups:
            if abs(grp[0]['y'] - line['y']) <= tolerance:
                grp.append(line)
                placed = True
                break
        if not placed:
            groups.append([line])
    for grp in groups:
        grp.sort(key=lambda l: l['x'])
    groups.sort(key=lambda g: g[0]['y'])
    return groups


def extract_page_meta(groups):
    subsection, work_content, unit = '', '', ''
    for grp in groups[:5]:
        text = ''.join(l['text'].strip() for l in grp)
        if re.match(r'^[一二三四五六七八九十]+、', text) and not subsection:
            subsection = text
        elif '工程内容' in text or '工作内容' in text:
            work_content = text.replace('工程内容：', '').replace('工作内容：', '').strip()
        elif re.match(r'^\d+\.?\d*\s*(m|㎡|m²|m³|km|t|kg)', text):
            unit = text
    return subsection, work_content, unit


def find_code_columns(groups):
    for i, grp in enumerate(groups):
        if any('定额编号' in l['text'] for l in grp):
            codes = []
            for l in grp:
                t = l['text'].strip()
                if re.match(r'^\d{5}$', t):
                    codes.append({'code': t, 'x': l['x']})
            return sorted(codes, key=lambda c: c['x']), i
    return [], -1


def collect_header_texts(groups, code_columns, header_start_idx):
    header_texts = {c['code']: [] for c in code_columns}
    col_ranges = []
    for i, c in enumerate(code_columns):
        left = (code_columns[i-1]['x'] + c['x']) / 2 if i > 0 else 0
        right = (c['x'] + code_columns[i+1]['x']) / 2 if i < len(code_columns)-1 else 9999
        col_ranges.append((left, right))
    for grp in groups[:header_start_idx]:
        for l in grp:
            t = l['text'].strip()
            if not t or re.match(r'^\d{5}$', t) or t in ('定额编号', '项目', '单位', '代码', '顺', '序', '号'):
                continue
            for j, (left, right) in enumerate(col_ranges):
                if left <= l['x'] <= right:
                    code = code_columns[j]['code']
                    header_texts[code].append({'text': t, 'y': round(l['y'], 1)})
                    break
    for code in header_texts:
        header_texts[code].sort(key=lambda h: h['y'])
    return header_texts


UNIT_WORDS = {'工日', 'm³', '元', '%', 'kg', 't', 'm²', '㎡', 'km', 'm',
              '个', '套', '艘', '台', '台班', '班', '艘班', '组日', '10m³', '100m³'}


def parse_data_rows(groups, code_columns, data_start_idx):
    data_rows = []
    for i in range(data_start_idx, len(groups)):
        grp = groups[i]
        texts = [l['text'].strip() for l in grp]
        if not texts or not re.match(r'^\d+$', texts[0]):
            continue
        name = texts[1] if len(texts) > 1 else ''
        unit, code = '', ''
        for l in grp:
            t = l['text'].strip()
            if t in UNIT_WORDS or re.match(r'^\d+m[³]', t):
                if not unit:
                    unit = t
            elif re.match(r'^\d{10,}$', t):
                code = t
        values = {}
        for l in grp:
            t = l['text'].strip()
            if t in ('－', '—', '...'):
                val = None
            elif re.match(r'^-?\d+\.?\d*$', t):
                val = float(t)
            else:
                continue
            best_code, best_dist = None, 999
            for c in code_columns:
                dist = abs(l['x'] - c['x'])
                if dist < best_dist and dist < 100:
                    best_dist = dist
                    best_code = c['code']
            if best_code:
                values[best_code] = val
        data_rows.append({
            'seq': int(texts[0]), 'name': name,
            'unit': unit, 'code': code, 'values': values
        })
    return data_rows


def is_continued(groups):
    if not groups:
        return False
    first_text = ''.join(l['text'] for l in groups[0])
    return '续表' in first_text or '续前表' in first_text


def cluster_page(lines):
    filtered = [l for l in lines
                if l['text'].strip() not in ('.', '- 22 -', '- 23 -')
                and not l['text'].strip().startswith('- ')
                and len(l['text'].strip()) > 0]
    groups = group_by_y(filtered)
    if not groups:
        return None
    subsection, work_content, unit = extract_page_meta(groups)
    code_columns, header_start_idx = find_code_columns(groups)
    if not code_columns:
        return {
            'page': None, 'subsection': subsection,
            'work_content': work_content, 'unit': unit,
            'is_continued': is_continued(groups),
            'code_columns': [], 'data_rows': [],
            'note': 'no quota codes detected'
        }
    header_texts = collect_header_texts(groups, code_columns, header_start_idx)
    data_start_idx = header_start_idx + 1
    for i in range(header_start_idx + 1, len(groups)):
        grp = groups[i]
        texts = [l['text'].strip() for l in grp]
        if texts and re.match(r'^\d+$', texts[0]):
            if i > header_start_idx + 2:
                data_start_idx = i
                break
    data_rows = parse_data_rows(groups, code_columns, data_start_idx)
    code_cols_out = [{
        'code': c['code'], 'x': c['x'],
        'header_texts': header_texts.get(c['code'], [])
    } for c in code_columns]
    return {
        'page': None, 'subsection': subsection,
        'work_content': work_content, 'unit': unit,
        'is_continued': is_continued(groups),
        'code_columns': code_cols_out, 'data_rows': data_rows
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Cluster text blocks into column-aligned data')
    ap.add_argument('--text-dir', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--pages')
    args = ap.parse_args()
    text_dir = Path(args.text_dir)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.pages:
        if '-' in args.pages:
            start, end = args.pages.split('-')
            pages = list(range(int(start), int(end) + 1))
        else:
            pages = [int(args.pages)]
    else:
        pages = []
        for fpath in sorted(text_dir.glob('page_*.json')):
            m = re.match(r'page_(\d+)\.json', fpath.name)
            if m:
                pages.append(int(m.group(1)))
    processed = 0
    for pg in sorted(pages):
        fpath = text_dir / f'page_{pg:04d}.json'
        if not fpath.exists():
            continue
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        result = cluster_page(data['lines'])
        if result is None:
            continue
        result['page'] = pg
        out_path = out_dir / f'page_{pg:04d}.json'
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        processed += 1
        if processed % 100 == 0:
            print(f'  ... {processed} pages')
    print(f'Clustered: {processed} pages -> {out_dir}')


if __name__ == '__main__':
    main()
