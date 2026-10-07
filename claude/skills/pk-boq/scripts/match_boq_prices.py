"""清单价格匹配：源清单 vs 目标清单，编号精确→desc归一化(region分桶)→分类，产出结构化 JSON 供回填/对比复用。"""
import re
import json
import logging
import argparse

# BOQ 混合类型列会触发 fastexcel 的 dtype 回退警告，逐格读取本就按字符串处理，噪音无意义
logging.getLogger("fastexcel").setLevel(logging.ERROR)

import fastexcel


def norm(s):
    s = str(s).lower()
    s = re.sub(r'[{}（）()\[\]\.\,\;\:\'\"\-《》【】]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def is_num(v):
    if v in ('nan', '', 'None'):
        return False
    try:
        float(str(v).replace(',', ''))
        return True
    except (ValueError, AttributeError):
        return False


def region(item):
    parts = item.split('.')
    if len(parts) >= 2 and parts[0].isalpha():
        return parts[0] + '.' + parts[1]
    return parts[0]


def parse_cols(spec, required=()):
    """解析 1-based 列映射，返回 0-based 索引"""
    try:
        cols = {k.strip(): int(v) for k, v in (kv.split('=') for kv in spec.split(','))}
    except ValueError:
        raise SystemExit(f'[错误] 列映射格式应为 key=列号,key=列号：{spec}')
    bad = [k for k, v in cols.items() if v < 1]
    if bad:
        raise SystemExit(f'[错误] 列号是 1-based，{bad} 收到了 <1 的值。A 列=1')
    missing = [k for k in required if k not in cols]
    if missing:
        raise SystemExit(f'[错误] 列映射缺少必需键 {missing}：{spec}')
    return {k: v - 1 for k, v in cols.items()}


def read_items(path, sheet, cols, extra, label):
    reader = fastexcel.read_excel(path)
    if sheet is None:
        name = reader.sheet_names[0]
    elif sheet in reader.sheet_names:
        name = sheet
    else:
        raise SystemExit(f'[错误] {path} 无 sheet {sheet!r}。'
                         f'可用: {", ".join(reader.sheet_names)}')
    df = reader.load_sheet(name, header_row=None).to_pandas()

    ncol = df.shape[1]
    over = {k: v + 1 for k, v in list(cols.items()) + list(extra.items()) if v >= ncol}
    if over:
        raise SystemExit(f'[错误] {label} 表 {name} 只有 {ncol} 列，但 {over} 指向更右。'
                         f'列号是 1-based，检查是否误传了 0-based 值')

    items = {}
    for ri in range(len(df)):
        item = str(df.iloc[ri, cols['item']]).strip()
        if item in ('nan', 'Item', ''):
            continue
        d = {
            'desc': str(df.iloc[ri, cols['desc']]),
            'unit': str(df.iloc[ri, cols['unit']]),
            'qty': str(df.iloc[ri, cols['qty']]),
            'row': ri + 1,
        }
        for lb, ci in extra.items():
            d[lb] = str(df.iloc[ri, ci])
        items[item] = d

    if not items:
        raise SystemExit(f'[错误] {label} 表 {name} 未读到任何条目。'
                         f'--{label}-cols 列号（1-based）可能指错列')
    return items


def is_leaf(d):
    return d['unit'] not in ('nan', '', 'None') and is_num(d['qty'])


def main():
    ap = argparse.ArgumentParser(
        description='源清单 vs 目标清单价格匹配，产出结构化 JSON',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
所有列号均为 1-based（A 列 = 1），与 compare_boq.py / fill_boq_prices.py 一致。

输出 JSON 五类:
  fill          自动配对成功（编号精确 + desc 归一化一致），可直接回填
  conflict      编号相同但 desc 不符 —— 人审
  multi         一个源对多个目标候选 —— 人审
  none          源有、目标匹配不上 —— 人审（可能是目标缺项）
  target_only   目标有、源没有 —— 人审（可能是源缺项）
后四类的裁决写进 decisions.json 交给 fill_boq_prices.py，不要改脚本。

示例:
  python match_boq_prices.py --source 报价.xlsx --target 测算表.xlsx --out match.json \\
      --src-cols item=2,desc=3,unit=4,qty=5 --src-extra rate=7,total=15 \\
      --tgt-cols item=2,desc=3,unit=4,qty=5
        """)
    ap.add_argument('--source', required=True, help='源报价清单 xlsx')
    ap.add_argument('--target', required=True, help='目标清单 xlsx')
    ap.add_argument('--out', required=True, help='输出匹配 JSON 路径')
    ap.add_argument('--src-cols', required=True,
                    help='源列映射 1-based，需含 item,desc,unit,qty')
    ap.add_argument('--tgt-cols', required=True,
                    help='目标列映射 1-based，需含 item,desc,unit,qty')
    ap.add_argument('--src-extra', default='',
                    help='源额外列 1-based（供 multi/none 人审看价格），如 rate=7,total=15')
    ap.add_argument('--src-sheet', default=None, help='源表 sheet 名（默认第一个）')
    ap.add_argument('--tgt-sheet', default=None, help='目标表 sheet 名（默认第一个）')
    args = ap.parse_args()

    need = ('item', 'desc', 'unit', 'qty')
    src_cols = parse_cols(args.src_cols, required=need)
    tgt_cols = parse_cols(args.tgt_cols, required=need)
    src_extra = parse_cols(args.src_extra) if args.src_extra else {}

    s = read_items(args.source, args.src_sheet, src_cols, src_extra, 'src')
    t = read_items(args.target, args.tgt_sheet, tgt_cols, {}, 'tgt')

    s_leaf = {k: v for k, v in s.items() if is_leaf(v)}
    t_leaf = {k: v for k, v in t.items() if is_leaf(v)}

    by_item = []
    s_rest = []
    for k in s_leaf:
        if k in t_leaf:
            by_item.append((k, k))
        else:
            s_rest.append(k)

    ok = []
    conflict = []
    for si, ti in by_item:
        if norm(s_leaf[si]['desc']) == norm(t_leaf[ti]['desc']):
            ok.append((si, ti))
        else:
            conflict.append((si, ti))

    s_pool = s_rest + [si for si, _ in conflict]
    t_pool_keys = set(t_leaf) - set(ti for _, ti in ok)

    t_idx = {}
    for w in t_pool_keys:
        key = (region(w), norm(t_leaf[w]['desc']))
        t_idx.setdefault(key, []).append(w)

    desc_match = []
    multi = []
    none = []
    for v in s_pool:
        key = (region(v), norm(s_leaf[v]['desc']))
        cand = t_idx.get(key, [])
        if len(cand) == 1:
            desc_match.append((v, cand[0]))
        elif len(cand) > 1:
            multi.append((v, cand))
        else:
            none.append((v,))

    fill = []
    for si, ti in ok:
        fill.append({'src': si, 'tgt': ti, 'flag': 'none'})
    for v, w in desc_match:
        fill.append({'src': v, 'tgt': w, 'flag': 'none'})

    def src_ctx(d, extra_cols):
        ctx = {'desc': d['desc'], 'row': d['row']}
        for label in extra_cols:
            ctx[label] = d.get(label, '')
        return ctx

    result = {
        'fill': fill,
        'conflict': [{'src': si, 'tgt': ti,
                      'src_desc': s_leaf[si]['desc'], 'tgt_desc': t_leaf[ti]['desc'],
                      'src_row': s_leaf[si]['row'], 'tgt_row': t_leaf[ti]['row']}
                     for si, ti in conflict],
        'multi': [dict({'src': v}, **src_ctx(s_leaf[v], src_extra),
                       candidates=[{'item': c, 'desc': t_leaf[c]['desc'], 'row': t_leaf[c]['row']}
                                   for c in cand])
                  for v, cand in multi],
        'none': [dict({'src': v}, **src_ctx(s_leaf[v], src_extra))
                 for v, in none],
        'target_only': [{'item': w, 'desc': t_leaf[w]['desc'], 'row': t_leaf[w]['row']}
                        for w in sorted(t_pool_keys) if w not in
                        set(d['tgt'] for d in fill) and w not in
                        set(c for _, cand in multi for c in cand)],
    }

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print(f'fill={len(fill)} conflict={len(conflict)} multi={len(multi)} '
          f'none={len(none)} target_only={len(result["target_only"])}')
    print(f'written: {args.out}')


if __name__ == '__main__':
    main()
