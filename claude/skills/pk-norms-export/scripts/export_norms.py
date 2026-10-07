"""
Export norms to 综合单价 + 人材机 sheets with cross-sheet price links.

综合单价: A序号 B分类指标 C定额编号 D项目名称 E单位 F合价 G工程量 H单价 I人工 J材料 K机械 L-BN消耗量x55
人材机:   A编号 B名称 C单位 D数量 E除税单价 F合价 G价格来源  (no merged cells)

The 参考单价 row of each subsection links to 人材机!E{row}, so a rate entered once in
人材机 propagates through SUMPRODUCT into every 单价 that consumes it. This sheet is
about 组价, not sourcing rates: the base rate comes straight from the norm library,
already fixed per 定额子目. Switching base rates = another --db.

Sheet layout and styling live in sheet_writers.py.
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict, OrderedDict
from pathlib import Path

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).parent))
from resource_taxonomy import CAT1_REMAP, CLASS_DICT, classify_resource, save_classification_dict
from sheet_writers import (N_CONSUMPTION, SHEET_LMM, SHEET_RATE,
                           write_lmm, write_rate_sheet)

# Which base rate to quote, and the currency that goes with it — the 币种 label can
# never contradict the rate because both come from the same entry. The two columns
# hold the same rate at a fixed 1 CNY = 5 THB (verified across A/C/D 册).
RATE_FIELDS = {'cny': ('cons_Market', '人民币'), 'thb': ('cons_Price', '泰铢')}


def natural_key(name):
    """A.01.02 before A.01.10; BJ12.1-7 before BJ12.1-14. Digit runs compare numeric."""
    head = (name or '').split()[0] if name else ''
    return [(0, int(s)) if s.isdigit() else (1, s)
            for s in re.split(r'[.\-]', head)]


def classify_cost_kind(kind_id, cons_name):
    """labour / materials / mech — drives 人工/材料/机械 column banding."""
    ks = str(kind_id or 0)
    if ks.startswith('1') or '工日' in cons_name:
        return 'labour'
    if ks.startswith('3'):
        return 'mech'
    for kw in ['机', '车', '船', '泵', '钻', '搅拌', '起重', '装载', '推土', '压路',
               '打桩', '挖掘', '自卸', '拖轮', '驳', '发电', '空压', '电焊']:
        if kw in cons_name:
            return 'mech'
    return 'materials'


def load_codes(path):
    """Accept pk-norms-match merge_summary.json, a bare code list, or {code: qty}."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict) and 'results' in data:
        rows = [r for r in data['results']
                if r.get('match_type', '').startswith('matched') and r.get('quota_code')]
        return [{'code': r['quota_code'], 'row': r.get('row')} for r in rows]
    if isinstance(data, dict):
        return [{'code': k, 'row': None} for k in data]
    out = []
    for r in data:
        if isinstance(r, str):
            out.append({'code': r, 'row': None})
        elif r.get('quota_code') or r.get('code'):
            out.append({'code': r.get('quota_code') or r.get('code'), 'row': r.get('row')})
    return out


def load_qty_map(boq_path, sheet, code_col, qty_col):
    """Norm code → summed quantity, columns located by header name."""
    import fastexcel
    wb = fastexcel.read_excel(str(boq_path))
    names = wb.sheet_names
    if sheet not in names:
        raise SystemExit(f"sheet '{sheet}' not in {boq_path}: {names}")
    df = wb.load_sheet_by_name(sheet).to_pandas()

    header_row, cmap = None, {}
    for ri in range(min(len(df), 10)):
        vals = {str(v).strip(): ci for ci, v in enumerate(df.iloc[ri]) if v is not None}
        if code_col in vals and qty_col in vals:
            header_row, cmap = ri, vals
            break
    if header_row is None:
        vals = {str(c).strip(): ci for ci, c in enumerate(df.columns)}
        if code_col in vals and qty_col in vals:
            header_row, cmap = -1, vals
    if header_row is None:
        raise SystemExit(f"columns '{code_col}' / '{qty_col}' not found in {sheet}; "
                         f"header candidates: {list(df.columns)[:20]}")

    ci_code, ci_qty = cmap[code_col], cmap[qty_col]
    qty = defaultdict(float)
    for ri in range(header_row + 1, len(df)):
        code = df.iloc[ri, ci_code]
        if code is None:
            continue
        code = str(code).strip()
        if not code or code in ('0', 'nan', '(空白)', code_col):
            continue
        try:
            qty[code] += float(df.iloc[ri, ci_qty])
        except (TypeError, ValueError):
            continue
    return dict(qty)


def library_label(db_path):
    """企业定额_A册_建筑装饰.sqlite → A册_建筑装饰 — names the base-rate source."""
    return re.sub(r'^企业定额_', '', Path(db_path).stem)


# ── 混凝土标号换算 ────────────────────────────────────────────
# 名称以这些开头、单位为 m3、且名字里带 C 标号的才换；砌块/垫块/桩头等一律跳过
_CONC_HEAD = re.compile(r'^(预拌混凝土|预拌豆石混凝土|商砼|混凝土)\s*C?\d{2}')
_CONC_SKIP = ('砌块', '条板', '垫块', '桩头', '井', '门', '花格', '挂板', '隔水栓',
              '遮阳板', '外墙板', '内墙板', '保护剂', '钉')
_MORTAR_RE = re.compile(r'^同混凝土等级砂浆')


def consumption_price_index(db):
    """(名称, 单位) -> cons_Market，用来给换算后的新资源找基价；找不到就 None。"""
    con = sqlite3.connect(str(db)); cur = con.cursor()
    idx = {}
    try:
        for n, s, u, mk in cur.execute(
                "SELECT cons_Name, cons_Standard, cons_Units, cons_Market FROM Consumption"):
            name = f"{n} {s}".strip() if s else (n or '')
            if name and (name, u or '') not in idx:
                idx[(name, u or '')] = mk
    except sqlite3.OperationalError:
        pass
    con.close()
    return idx


def _grade_of(res):
    m = re.search(r'C(\d{2})', res.get('name') or '')
    return m.group(1) if m else None


def _conv_family(nm, unit):
    """这个资源能不能跟着标号换？返回族名（保留 水下/豆石/商砼 等限定词），不能换返回 None。"""
    if (unit or '') != 'm3':
        return None
    if not re.search(r'混凝土|砼', nm or ''):
        return None
    if any(x in nm for x in _CONC_SKIP):
        return None
    if _MORTAR_RE.match(nm):
        return None
    if not re.search(r'C\d{2}', nm):
        return None
    if '水下' in nm:
        return '预拌水下混凝土'
    if '豆石' in nm:
        return '预拌豆石混凝土'
    if '商砼' in nm:
        return '商砼'
    return '预拌混凝土'


def _swap_res(res, grade, price_idx):
    """把混凝土/同等级砂浆换成目标标号；其余资源原样返回。"""
    nm, unit = res.get('name') or '', res.get('unit') or ''
    if _MORTAR_RE.match(nm) and '砂浆' in nm:
        fam = '同混凝土等级砂浆'
    else:
        fam = _conv_family(nm, unit)
        if not fam:
            return res
    new = f"{fam} C{grade}"
    if new == nm:
        return res
    return {**res, 'name': new, 'unit': unit or 'm3',
            'label': f"{new}\n{unit or 'm3'}",
            'cons_price': price_idx.get((new, unit or 'm3')) or 0}


def expand_concrete(entries, meta, cons, qty_map, cmap, keep_original=True):
    """按 concrete map 给每个定额子目追加“换 Cxx”变体。

    cmap: {code: [{'grade': '50', 'qty': 123.4}, ...]}；grade 已经是清单口径
    （C50/60 取第一个数）。与原资源同标号的变体不生成。
    """
    price_idx = consumption_price_index(_DB_PATH_HOLDER[0]) if _DB_PATH_HOLDER[0] else {}
    out, made = [], 0
    for e in entries:
        code = e['code']
        variants = cmap.get(code)
        base = meta.get(code)
        if not variants or not base:
            out.append(e); continue
        if keep_original:
            out.append(e)
        base_res = cons.get(code, [])
        base_grade = None
        for _r in base_res:
            if _conv_family(_r.get('name'), _r.get('unit')) or _MORTAR_RE.match(_r.get('name') or ''):
                if _grade_of(_r):
                    base_grade = _grade_of(_r)
                    break
        if not base_grade:
            out.append(e); continue          # 没有可换算的混凝土/砂浆 → 不生变体
        for v in variants:
            g = str(v.get('grade') or '').strip()
            if not g or g == base_grade:
                continue
            swapped = [_swap_res(r, g, price_idx) for r in base_res]
            if swapped == base_res:
                continue                     # 换了等于没换 → 跳过
            vcode = f"{code}c{g.lower()}"
            if vcode in meta:
                continue
            meta[vcode] = {**base, 'name': f"{base['name']}换C{g}"}
            cons[vcode] = swapped
            qty_map[vcode] = float(v.get('qty') or 0)
            out.append({'code': vcode, 'row': None})
            made += 1
    return out, made


_DB_PATH_HOLDER = [None]


def query_norms(db, codes, rate_field):
    """Norm metadata + consumption rows.

    Accepts both the full code pk-norms-match emits (A.01.02.001.BJ12.1-7 =
    chapter prefix + norm_Code) and the bare norm_Code (BJ12.1-7). The full form
    is unambiguous; a bare code that repeats across source libraries resolves to
    the first match and is reported as ambiguous.
    """
    con = sqlite3.connect(str(db))
    cur = con.cursor()

    norms = {}
    ambiguous = set()
    cur.execute("""
        SELECT n.norm_ID, n.norm_Code, n.norm_Name, n.norm_Units,
               c3.chap_Name, c2.chap_Name, c1.chap_Name, c1.chap_Name_EN
        FROM Norm n
        JOIN chapter c3 ON n.chap_ID = c3.chap_ID
        JOIN chapter c2 ON c3.chap_PID = c2.chap_ID
        JOIN chapter c1 ON c2.chap_PID = c1.chap_ID
    """)
    for nid, ncode, name, units, sub, sec, ch, ch_en in cur.fetchall():
        rec = {'norm_ID': nid, 'name': name, 'units': units, 'subchap': sub or '',
               'section': sec or '', 'chapter': ch or '', 'chapter_en': ch_en or ''}
        full = f"{sub.split()[0]}.{ncode}" if sub else ncode
        norms[full] = rec
        if ncode in norms:
            ambiguous.add(ncode)
        else:
            norms[ncode] = rec

    meta = {code: norms[code] for code in codes if code in norms}
    hit_ambiguous = sorted(ambiguous & set(codes))
    if hit_ambiguous:
        print(f'WARNING: {len(hit_ambiguous)} bare codes exist in more than one chapter, '
              f'first match used: {hit_ambiguous[:5]} — pass full codes to disambiguate')

    by_norm_id = defaultdict(list)
    ids = {m['norm_ID'] for m in meta.values()}
    if ids:
        ph = ','.join('?' * len(ids))
        cur.execute(f"""
            SELECT ct.norm_ID, c.cons_Name, c.cons_Standard, c.cons_Units,
                   ct.cont_Amount, c.kind_ID, c.{rate_field}
            FROM Content ct
            JOIN Consumption c ON ct.cons_ID = c.cons_ID
            WHERE ct.norm_ID IN ({ph})
            ORDER BY ct.norm_ID, c.kind_ID, c.cons_Code
        """, list(ids))
        for nid, cname, cstd, cunit, amount, kind, cons_price in cur.fetchall():
            # Grade belongs in the name: 预拌混凝土 C25 and C30 carry different base
            # rates (2730 vs 2870), so they must never merge into one row.
            name = f"{cname} {cstd}".strip() if cstd else cname
            by_norm_id[nid].append({
                'name': name, 'unit': cunit or '', 'amount': amount or 0,
                'cls': classify_cost_kind(kind, name), 'cons_price': cons_price or 0,
                'label': f"{name}\n{cunit}" if cunit else name,
            })
    con.close()
    cons = {code: by_norm_id.get(m['norm_ID'], []) for code, m in meta.items()}
    return meta, cons


def build_tree(entries, meta, cons):
    """chapter → section → subsection → items, deduped by norm code."""
    tree = OrderedDict()
    missing = []
    for e in entries:
        code = e['code']
        m = meta.get(code)
        if not m:
            missing.append(code)
            continue
        ch, sec, sub = m['chapter'], m['section'], m['subchap']
        ch_d = tree.setdefault(ch, {'en': m['chapter_en'], 'sections': OrderedDict()})
        sec_d = ch_d['sections'].setdefault(sec, OrderedDict())
        sub_d = sec_d.setdefault(sub, {'items': [], 'resources': []})

        if any(i['code'] == code for i in sub_d['items']):
            continue
        sub_d['items'].append({'code': code, 'name': m['name'], 'units': m['units'],
                               'resources': cons.get(code, [])})
        seen = {r['label'] for r in sub_d['resources']}
        for res in cons.get(code, []):
            if res['label'] not in seen:
                seen.add(res['label'])
                sub_d['resources'].append(res)

    cls_order = {'labour': 0, 'materials': 1, 'mech': 2}
    ordered = OrderedDict()
    for ch in sorted(tree, key=natural_key):
        ch_d = tree[ch]
        secs = OrderedDict()
        for sec in sorted(ch_d['sections'], key=natural_key):
            subs = OrderedDict()
            for sub in sorted(ch_d['sections'][sec], key=natural_key):
                sub_d = ch_d['sections'][sec][sub]
                sub_d['resources'] = sorted(sub_d['resources'][:N_CONSUMPTION],
                                            key=lambda x: cls_order.get(x['cls'], 9))
                sub_d['items'].sort(key=lambda x: natural_key(x['code']))
                subs[sub] = sub_d
            secs[sec] = subs
        ordered[ch] = {'en': ch_d['en'], 'sections': secs}
    return ordered, missing


def collect_resources(tree, qty_map, source_label):
    """Unique resources with summed quantity and the norm library's base rate.

    Keyed by (name, unit): 砂子 exists in the库 as both kg and m3 rows, and adding
    those two quantities together would produce a number in no unit at all.

    The rate comes from the selected RATE_FIELDS entry (default cny = cons_Market
    人民币) — base rates are already fixed per 定额子目 in the library, so switching
    base rates means pointing --db at another library or passing --rate thb.
    """
    agg = OrderedDict()
    for ch_d in tree.values():
        for sec in ch_d['sections'].values():
            for sub_d in sec.values():
                for item in sub_d['items']:
                    q = qty_map.get(item['code'], 0)
                    for res in item['resources']:
                        key = (res['name'], res['unit'])
                        r = agg.setdefault(key, {'qty': 0.0, 'rate': 0.0, 'rates_seen': set()})
                        if res['cons_price']:
                            r['rate'] = r['rate'] or res['cons_price']
                            r['rates_seen'].add(round(res['cons_price'], 4))
                        r['qty'] += (res['amount'] or 0) * q

    hierarchy = OrderedDict()
    for (name, unit), d in agg.items():
        cat1, cat2, cat3 = classify_resource(name)
        if cat1 == '材料':
            cat1 = CAT1_REMAP.get(cat2, '辅材')
        rate = d['rate'] or None
        hierarchy.setdefault(cat1, OrderedDict()).setdefault(cat2, OrderedDict()) \
                 .setdefault(cat3, []).append({
                     'name': name, 'unit': unit, 'qty': round(d['qty'], 4), 'rate': rate,
                     'source': f'{source_label} 基价' if rate else '待询价',
                     'rates_seen': d['rates_seen']})

    for c1 in hierarchy.values():
        for c2 in c1.values():
            for items in c2.values():
                items.sort(key=lambda x: (-x['qty'], x['name']))
    return hierarchy


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--codes', required=True,
                    help='norm codes: merge_summary.json from pk-norms-match, or a JSON code list')
    ap.add_argument('--db', required=True, help='norms SQLite (enterprise schema, has Norm table)')
    ap.add_argument('-o', '--output', help='output xlsx (default: alongside --codes)')
    ap.add_argument('--into', help='add both sheets into this existing xlsx instead of a new file')
    ap.add_argument('--rate', choices=sorted(RATE_FIELDS), default='cny',
                    help='which base rate to quote: cny = cons_Market 人民币 (default), '
                         'thb = cons_Price 泰铢. The 币种 label follows the rate.')
    ap.add_argument('--boq', help='BOQ xlsx supplying quantities (optional)')
    ap.add_argument('--boq-sheet', default='UniqueBQ', help='sheet in --boq (default: UniqueBQ)')
    ap.add_argument('--code-col', default='Norm Code', help='norm code column header in --boq')
    ap.add_argument('--qty-col', default='Qty', help='quantity column header in --boq')
    ap.add_argument('--concrete-map',
                    help='JSON {code: [{"grade":"50","qty":123.4}, ...]} — 为混凝土类定额子目按标号追加换算变体')
    ap.add_argument('--no-keep-original', dest='keep_original', action='store_false',
                    help='换算时不保留原定额行（默认保留）')
    ap.set_defaults(keep_original=True)
    args = ap.parse_args()

    entries = load_codes(args.codes)
    codes = sorted({e['code'] for e in entries})
    if not codes:
        raise SystemExit(f'no norm codes in {args.codes}')
    print(f'Norm codes: {len(codes)}')

    rate_field, currency = RATE_FIELDS[args.rate]
    meta, cons = query_norms(args.db, codes, rate_field)
    print(f'Found in db: {len(meta)} | rate={rate_field} ({currency})')

    qty_map = {}
    if args.boq:
        qty_map = load_qty_map(args.boq, args.boq_sheet, args.code_col, args.qty_col)
        print(f'Quantities from {args.boq_sheet}: {len(qty_map)} codes')
    has_qty = bool(qty_map)

    if args.concrete_map:
        _DB_PATH_HOLDER[0] = args.db
        cmap = json.loads(Path(args.concrete_map).read_text(encoding='utf-8'))
        entries, made = expand_concrete(entries, meta, cons, qty_map, cmap,
                                        keep_original=args.keep_original)
        print(f'混凝土换算: 追加 {made} 个变体（{"保留" if args.keep_original else "替换"}原行）')

    tree, missing = build_tree(entries, meta, cons)
    if missing:
        missing = sorted(set(missing))
        print(f'WARNING: {len(missing)} codes not in db: {missing[:8]}')

    hierarchy = collect_resources(tree, qty_map, library_label(args.db))
    all_res = [i for c1 in hierarchy.values() for c2 in c1.values()
               for items in c2.values() for i in items]
    clash = [i['name'] for i in all_res if len(i['rates_seen']) > 1]
    if clash:
        print(f'WARNING: {len(clash)} resources carry more than one base rate in the '
              f'library, first used: {clash[:5]}')
    no_rate = sum(1 for i in all_res if i['rate'] is None)
    print(f'Resources: {len(all_res)} ({no_rate} without a base rate)')

    if args.into:
        out = Path(args.into)
        wb = load_workbook(str(out))
        for name in (SHEET_RATE, SHEET_LMM):
            if name in wb.sheetnames:
                del wb[name]
        ws_lmm = wb.create_sheet(SHEET_LMM)
        ws_rate = wb.create_sheet(SHEET_RATE)
    else:
        out = Path(args.output) if args.output else Path(args.codes).with_suffix('.export.xlsx')
        wb = Workbook()
        ws_rate = wb.active
        ws_rate.title = SHEET_RATE
        ws_lmm = wb.create_sheet(SHEET_LMM)

    res_rows = write_lmm(ws_lmm, hierarchy, currency, has_qty)
    n_items = write_rate_sheet(ws_rate, tree, qty_map, res_rows, has_qty)
    if not args.into:
        wb.move_sheet(SHEET_RATE, offset=-1)

    wb.save(str(out))
    save_classification_dict(CLASS_DICT)
    print(f'Done: {n_items} norm rows, {len(res_rows)} linked resources -> {out}')


if __name__ == '__main__':
    main()
