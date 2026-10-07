#!/usr/bin/env python
"""
扫描件价格表读数 + 交叉验证 —— 纯图片报价单唯一允许的价格来源路径。

为什么要这个：技能原本的铁律是「价格不走 OCR」，前提是总有一份 Excel 兜底。
纯扫描件批次把这个前提抽掉了，而那份签了字盖了章的扫描件往往才是定稿。
所以铁律改成「单一 OCR 读数不得直接入库」——价格可以来自扫描件，但必须交叉验证，
并把验证方式留在数据里。

三层验证，每个数字走它能走到的最高档：

  arith  行内 a×b=c、列求和、比例关系闭合 —— 确定性证明，能定位到具体哪个字段读错
  dual   双引擎读数一致（rapidocr 读中文强、paddleocr 读数字强，失效模式不同）
  none   上面都不成立 → 填报员标 uncertain，进审核优先清单

算术层为什么用组合搜索而不是先认列：倾斜、合并单元格、跨页续表都会让列识别失准，
而「这一行里哪三个数满足 a×b=c」是自证的，顺带就认出了谁是数量、谁是单价、谁是总价。

    python scan_price_table.py <扫描件.pdf> --page 1 --rel 0.08,0.15,0.86,0.42
    python scan_price_table.py <扫描件.pdf> --engines rapid        # 快速迭代，跳过慢的 paddle
    python scan_price_table.py <图片.jpg> --json out.json

输出人读报告 + JSON。JSON 供填报员据以写 manifest：verify=arith/dual 的正常填，
verify=none 的填最可能值并标 uncertain。
"""
import sys, io, os, re, json, time, argparse, itertools
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# 命中即不是可入库单价，交填报员判。与「整项/包干价不入库」同一类
MARKER_WORDS = {
    'lumpsum':     ('实报实销', '据实结算', 'at cost', 'reimburs', 'actual cost'),
    'provisional': ('暂定', '暂列', '备用金', 'provisional', 'contingency', 'p.c.', 'prime cost'),
    'conditional': ('如有', '若有', '若发生', 'if any', 'if required', 'when applicable'),
    'total':       ('合计', '总价', '总计', '小计', 'total', 'subtotal', 'sum of'),
}

# 各类校验的容差不能共用一个阈值：乘法应当精确，比例关系有四舍五入
TOL_PRODUCT = 0.02          # a×b=c，绝对容差（分）
TOL_SUM_PER_ITEM = 0.02     # 列求和，按参与项数累积
TOL_RATIO_REL = 2e-4        # 比例关系，相对容差


def load_page_image(src, page_no, dpi):
    from PIL import Image
    if Path(src).suffix.lower() == '.pdf':
        import fitz
        doc = fitz.open(src)
        if page_no < 1 or page_no > len(doc):
            raise SystemExit(f'页码越界：PDF 共 {len(doc)} 页，请求第 {page_no} 页')
        pix = doc[page_no - 1].get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
        doc.close()
        return img
    return Image.open(src).convert('RGB')


def _box_of(poly):
    """任意四点多边形或 (x0,y0,x1,y1) → (x0,y0,x1,y1)"""
    a = [list(map(float, pt)) if hasattr(pt, '__iter__') else [float(pt)] for pt in poly]
    if len(a) == 4 and all(len(p) == 2 for p in a):
        xs = [p[0] for p in a]
        ys = [p[1] for p in a]
        return (min(xs), min(ys), max(xs), max(ys))
    flat = [v for p in a for v in p]
    if len(flat) == 4:
        return (flat[0], flat[1], flat[2], flat[3])
    raise ValueError(f'无法解析坐标: {poly}')


def ocr_rapid(arr):
    from rapidocr_onnxruntime import RapidOCR
    res, _ = RapidOCR()(arr)
    out = []
    for r in (res or []):
        out.append({'text': r[1], 'score': float(r[2]), 'box': _box_of(r[0]), 'engine': 'rapid'})
    return out


def ocr_paddle(arr):
    from paddleocr import PaddleOCR
    # v3 默认开文档去扭曲/方向分类，会把图像变换后返回**变换空间**的坐标，
    # 与 rapid 的坐标对不上、双引擎交叉失效。必须关掉，坐标才与输入图一致。
    try:
        ocr = PaddleOCR(lang='en', enable_mkldnn=False, use_doc_orientation_classify=False,
                        use_doc_unwarping=False, use_textline_orientation=False)
    except (TypeError, ValueError):
        try:
            ocr = PaddleOCR(lang='en', enable_mkldnn=False)
        except (TypeError, ValueError):
            ocr = PaddleOCR(lang='en')
    out = []
    for page in (ocr.predict(arr) if hasattr(ocr, 'predict') else ocr.ocr(arr)) or []:
        d = page if isinstance(page, dict) else getattr(page, 'json', {})
        d = d.get('res', d) if isinstance(d, dict) else d
        if not isinstance(d, dict):
            continue
        texts = d.get('rec_texts') or []
        scores = d.get('rec_scores') or [1.0] * len(texts)
        polys = d.get('rec_polys') or d.get('dt_polys') or d.get('rec_boxes') or []
        for i, t in enumerate(texts):
            box = None
            if i < len(polys):
                try:
                    box = _box_of(polys[i])
                except Exception:
                    box = None
            out.append({'text': t, 'score': float(scores[i]) if i < len(scores) else 1.0,
                        'box': box, 'engine': 'paddle'})
    return out


NUM_RE = re.compile(r'^[^\d\-+]{0,3}?([+-]?\d[\d,\s]*(?:\.\d+)?)[^\d]{0,4}$')


def parse_num(text):
    """'1,917,519.50' -> 1917519.5；不是纯数值返回 None。宽松吃掉币种/单位尾巴"""
    t = (text or '').strip().replace('，', ',').replace('。', '.')
    # OCR 常在小数点两侧插空格（实测天津长景那张表全是 `1053. 00`、`4110. 92`），
    # 不先粘回去整列数字都会被判成非数值，算术校验直接失效
    t = re.sub(r'(\d)\s*\.\s*(\d)', r'\1.\2', t)
    m = NUM_RE.match(t)
    if not m:
        return None
    body = m.group(1).replace(',', '').replace(' ', '')
    if body in ('', '-', '+'):
        return None
    try:
        v = float(body)
    except ValueError:
        return None
    return v


def cluster_rows(tokens):
    """按 y 中心聚类成行。阈值取中位字高的 0.6，对轻微倾斜够用"""
    toks = [t for t in tokens if t.get('box')]
    if not toks:
        return []
    heights = sorted(t['box'][3] - t['box'][1] for t in toks)
    h = heights[len(heights) // 2] or 10
    thr = h * 0.6
    toks.sort(key=lambda t: (t['box'][1] + t['box'][3]) / 2)
    rows, cur = [], [toks[0]]
    cy = lambda t: (t['box'][1] + t['box'][3]) / 2
    for t in toks[1:]:
        if abs(cy(t) - cy(cur[-1])) <= thr:
            cur.append(t)
        else:
            rows.append(sorted(cur, key=lambda x: x['box'][0]))
            cur = [t]
    rows.append(sorted(cur, key=lambda x: x['box'][0]))
    return rows


def find_products(numcells):
    """
    行内找 a×b=c。numcells 是 [(值, x坐标)]，**两个因子按 x 顺序返回**。

    不按大小猜谁是数量谁是单价——本例数量 12213.5 就比单价 157 大，猜必错。
    表格列序（数量在左、单价在右）才是可靠依据，而 bbox 正好给了 x。
    """
    hits = []
    for (a, xa), (b, xb), (c, _xc) in itertools.permutations(numcells, 3):
        if a <= 0 or b <= 0 or c <= 0:
            continue
        if abs(a * b - c) <= max(TOL_PRODUCT, abs(c) * 1e-9):
            f1, f2 = ((a, b) if xa <= xb else (b, a))
            hits.append((f1, f2, c))
    uniq = {(round(f1, 6), round(f2, 6), round(m, 6)) for f1, f2, m in hits}
    return sorted(uniq, key=lambda x: -x[2])


def find_row_sums(numcells):
    """
    行内跨列求和：A+B+C+D=E。物流/分项报价表极常见（"费用合计"列）。

    实测天津长景那张表就是这个形态，而只查乘法会整行漏掉——更糟的是它能反推出
    OCR 吃掉的小数位：4110.92−1861−1053−650=546.92，说明首列读成的 547 丢了小数。
    只查按 x 连续的列段（表里的加数本来就相邻），O(n²)，不会组合爆炸。
    """
    hits = []
    n = len(numcells)
    for i in range(n):
        for j in range(i + 2, n + 1):           # 至少两个加数
            seg = numcells[i:j]
            s = sum(v for v, _ in seg)
            if s <= 0:
                continue
            for k in range(j, n):                # 合计列在加数右侧
                t, _x = numcells[k]
                if abs(s - t) <= max(TOL_PRODUCT, abs(t) * 1e-9):
                    hits.append(([v for v, _ in seg], round(t, 6)))
    uniq = {(tuple(round(v, 6) for v in a), b) for a, b in hits}
    return sorted(uniq, key=lambda x: (-len(x[0]), -x[1]))


def find_near_misses(numcells):
    """
    差一点闭合的行内求和——OCR 最常见的错就是吃掉或多读一位小数，而差额能反推出错在哪。

    实测天津长景：547+1861+1053+650=4111.00，表列 4110.92，差 0.08；
    而 547−0.08=546.92 正是被 OCR 吃掉小数的真值。只报相对误差 <0.5% 的，
    再大就不是读数误差而是真的不该相加。
    """
    out = []
    n = len(numcells)
    for i in range(n):
        for j in range(i + 2, n + 1):
            seg = numcells[i:j]
            s = sum(v for v, _ in seg)
            if s <= 0:
                continue
            for k in range(j, n):
                t, _x = numcells[k]
                d = t - s
                if t > 0 and TOL_PRODUCT < abs(d) <= abs(t) * 0.005:
                    out.append({'addends': [v for v, _ in seg], 'total': round(t, 6),
                                'delta': round(d, 6),
                                'implied': [round(v + d, 6) for v, _ in seg]})
    # 差额越小越像 OCR 滑一位；差得大的多半是把柜型（"20 GP" 的 20）之类误当加数
    out.sort(key=lambda x: abs(x['delta']))
    return out[:3]


def verify_sums(row_amounts, all_nums):
    """
    列求和：页面上是否存在某个数 = 若干行总价之和。

    **不做全组合枚举**——30 行就是 2^30 次迭代，直接挂死。
    真实表里小计/合计求的本来就是连续行，所以只查：全部行 → 连续区间 → 极小组合。
    既快（O(n²)）又更贴合语义。
    """
    out = []
    n = len(row_amounts)
    if n < 2:
        return out
    pos = [v for v in all_nums if v > 0]

    def hit(idxs):
        s = sum(row_amounts[i][1] for i in idxs)
        for v in pos:
            if abs(v - s) <= TOL_SUM_PER_ITEM * len(idxs):
                return {'sum': round(s, 2), 'matched': v,
                        'rows': [row_amounts[i][0] for i in idxs],
                        'span': 'all' if len(idxs) == n else 'range'}
        return None

    if (h := hit(range(n))):
        out.append(h)
    for i in range(n):
        for j in range(i + 2, n + 1):
            if j - i == n:
                continue
            if (h := hit(range(i, j))):
                h['span'] = 'range'
                out.append(h)
                if len(out) >= 6:
                    return out
    if not out:
        for k in (2, 3):
            for combo in itertools.combinations(range(n), k):
                if (h := hit(combo)):
                    h['span'] = 'combo'
                    out.append(h)
                    return out
    return out


def verify_ratios(all_nums):
    """比例关系：c = a + b、b = a×p（p 为常见百分比）"""
    out = []
    vals = sorted({round(v, 6) for v in all_nums if v > 0}, reverse=True)[:40]
    for a, b, c in itertools.permutations(vals, 3):
        if abs(a + b - c) <= TOL_PRODUCT:
            out.append({'kind': 'a+b=c', 'a': a, 'b': b, 'c': c})
    for a, b in itertools.permutations(vals, 2):
        if a <= 0:
            continue
        p = b / a
        for pct in (0.05, 0.07, 0.10, 0.12, 0.15, 0.17, 0.18, 0.20):
            if abs(p - pct) <= TOL_RATIO_REL:
                out.append({'kind': f'b=a×{pct:.0%}', 'a': a, 'b': b})
    return out[:12]


def match_engines(rows_a, toks_b):
    """按中心点就近把 B 引擎的 token 匹配到 A 的 token 上，比对读数是否一致"""
    pool = [t for t in toks_b if t.get('box')]
    res = {}
    for row in rows_a:
        for t in row:
            x0, y0, x1, y1 = t['box']
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            best, bestd = None, 1e18
            for u in pool:
                ux0, uy0, ux1, uy1 = u['box']
                ucx, ucy = (ux0 + ux1) / 2, (uy0 + uy1) / 2
                d = (ucx - cx) ** 2 + (ucy - cy) ** 2
                if d < bestd:
                    best, bestd = u, d
            tol = ((x1 - x0) + (y1 - y0)) / 2
            if best and bestd <= tol ** 2:
                res[id(t)] = best
    return res


def mark_flags(text):
    t = (text or '').lower()
    return [k for k, ws in MARKER_WORDS.items() if any(w.lower() in t for w in ws)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--page', type=int, default=1)
    ap.add_argument('--dpi', type=int, default=300)
    ap.add_argument('--rel', help='裁切相对坐标 x,y,w,h（0~1）；不给则整页')
    ap.add_argument('--engines', default='rapid,paddle',
                    help='参与交叉的引擎，逗号分隔。只给一个则跳过 dual 档')
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        raise SystemExit(f'找不到: {src}')
    out_dir = Path(args.out_dir) if args.out_dir else src.parent / 'raw'
    out_dir.mkdir(parents=True, exist_ok=True)

    img = load_page_image(str(src), args.page, args.dpi)
    W, H = img.size
    if args.rel:
        x, y, w, h = (float(v) for v in args.rel.split(','))
        box = (round(x * W), round(y * H), round(w * W), round(h * H))
        img = img.crop((box[0], box[1], box[0] + box[2], box[1] + box[3]))
    # 存 jpg：OCR 读的是内存数组，这张只是留痕与人工复核用，没必要无损占上下文
    crop_path = out_dir / f'{src.stem}_p{args.page}_table.jpg'
    img.save(crop_path, 'JPEG', quality=80, optimize=True)
    print(f'源: {src.name}  第 {args.page} 页  {args.dpi}dpi  裁图 {img.size[0]}x{img.size[1]}')
    _kb = crop_path.stat().st_size / 1024
    print(f'裁图: {crop_path}  ({_kb:.0f} KB) —— **留痕用，不要 Read 它**'
          f'（约 {int(_kb * 1024 * 1.37 / 4):,} tokens）')
    print('本脚本下面会打印全部读数、校验结论和 JSON 路径，取数看那些就够了。\n')

    import numpy as np
    arr = np.array(img)
    engines = [e.strip() for e in args.engines.split(',') if e.strip()]
    runners = {'rapid': ocr_rapid, 'paddle': ocr_paddle}
    results = {}
    for name in engines:
        if name not in runners:
            print(f'[!] 未知引擎 {name}，跳过'); continue
        t0 = time.time()
        try:
            results[name] = runners[name](arr)
            print(f'{name}: {len(results[name])} 行  {time.time() - t0:.1f}s')
        except Exception as e:
            print(f'{name}: 失败 {type(e).__name__}: {e}')
    if not results:
        raise SystemExit('没有可用引擎')

    primary = 'rapid' if 'rapid' in results else engines[0]
    rows = cluster_rows(results[primary])
    other = next((k for k in results if k != primary), None)
    xmatch = match_engines(rows, results[other]) if other else {}

    all_nums = [v for t in results[primary] if (v := parse_num(t['text'])) is not None]
    row_recs, row_amounts = [], []

    print(f'\n版面重建：{len(rows)} 行（主引擎 {primary}'
          + (f'，交叉引擎 {other}' if other else '，无交叉引擎') + ')\n')

    for ri, row in enumerate(rows):
        texts = [t['text'] for t in row]
        line = ' | '.join(texts)
        numcells = [(v, t['box'][0]) for t in row if (v := parse_num(t['text'])) is not None]
        nums = [v for v, _ in numcells]
        # 只扫前两个单元格（标签列）。实测 SICHO 那批备注里写着
        # "Lump-sum to coverage total C&F related cost"，整行扫会把明细行误判成合计行
        flags = sorted({f for t in texts[:2] for f in mark_flags(t)})
        prods = find_products(numcells) if len(numcells) >= 3 else []
        rsums = find_row_sums(numcells) if len(numcells) >= 3 else []
        near  = find_near_misses(numcells) if (len(numcells) >= 3 and not rsums) else []

        cells = []
        for t in row:
            v = parse_num(t['text'])
            b = xmatch.get(id(t))
            agree = None
            if b is not None:
                bv = parse_num(b['text'])
                agree = (bv == v) if (v is not None and bv is not None) else \
                        (b['text'].strip() == t['text'].strip())
            cells.append({'text': t['text'], 'value': v, 'score': round(t['score'], 2),
                          'crossText': b['text'] if b else None, 'agree': agree})

        # qty/rate 按列序指派（左=数量、右=单价），填报员须对照表头确认后再写 manifest
        rec = {'row': ri, 'line': line, 'numbers': nums, 'flags': flags,
               'products': [{'qty': q, 'rate': r, 'amount': m, 'assignedBy': 'column-order'}
                            for q, r, m in prods],
               'rowSums': [{'addends': list(a), 'total': t} for a, t in rsums],
               'nearMiss': near,
               'cells': cells}
        row_recs.append(rec)
        if prods:
            row_amounts.append((ri, prods[0][2]))
        elif rsums:
            row_amounts.append((ri, rsums[0][1]))

        tag = ''
        if prods:
            q, r, m = prods[0]
            tag = f'  [arith 数量 {q:g} x 单价 {r:g} = {m:,.2f}]'
        elif rsums:
            a, t = rsums[0]
            tag = f'  [arith {" + ".join(f"{v:g}" for v in a)} = {t:,.2f}]'
        elif near:
            nm = near[0]
            tag = f'  [近似闭合 差 {nm["delta"]:+.2f}]'
        if flags:
            tag += '  [' + ','.join(flags) + ']'
        print(f'  #{ri:<3} {line[:96]}{tag}')

    sums = verify_sums(row_amounts, all_nums)
    ratios = verify_ratios(all_nums)

    print('\n--- 结构性校验 ---')
    for s in sums:
        print(f"  列求和闭合：行 {s['rows']} 总价之和 {s['sum']:,.2f} = 页面数值 {s['matched']:,.2f}")
    for r in ratios:
        if r['kind'] == 'a+b=c':
            print(f"  比例闭合：{r['a']:,.2f} + {r['b']:,.2f} = {r['c']:,.2f}")
        else:
            print(f"  比例闭合：{r['kind']}  a={r['a']:,.2f}  b={r['b']:,.2f}")
    if not sums and not ratios:
        print('  无（该表无列求和/比例冗余，价格只能靠 dual 档）')

    print('\n--- 逐值采信判定 ---')
    verified = set()
    for rec in row_recs:
        for p in rec['products']:
            verified |= {round(p['qty'], 6), round(p['rate'], 6), round(p['amount'], 6)}
        for rs in rec['rowSums']:
            verified |= {round(v, 6) for v in rs['addends']} | {round(rs['total'], 6)}
    for s in sums:
        verified.add(round(s['matched'], 6))
    for r in ratios:
        verified |= {round(v, 6) for k, v in r.items() if isinstance(v, (int, float))}

    summary = {'arith': 0, 'dual': 0, 'none': 0}
    for rec in row_recs:
        for c in rec['cells']:
            if c['value'] is None:
                continue
            if round(c['value'], 6) in verified:
                c['verify'] = 'arith'
            elif c['agree'] is True:
                c['verify'] = 'dual'
            else:
                c['verify'] = 'none'
            summary[c['verify']] += 1
            if c['verify'] != 'arith':
                cross = c['crossText'] if c['crossText'] is not None else '(交叉引擎未读到)'
                note = '双引擎一致' if c['verify'] == 'dual' else f"分歧/无交叉：本读 {c['text']!r}，对读 {cross!r}"
                print(f"  行{rec['row']:<3} {c['value']:>14,.2f}  {c['verify']:<5} {note}"
                      + (f"  置信度 {c['score']}" if c['score'] < 0.7 else ''))

    print(f"\n汇总：arith {summary['arith']} 个  dual {summary['dual']} 个  none {summary['none']} 个")
    print('填报规则：arith/dual 正常填入 manifest 并记 priceVerify；none 填最可能值 + 标 uncertain，写清分歧内容。')
    flagged = [r for r in row_recs if r['flags']]
    if flagged:
        print(f'\n下列 {len(flagged)} 行命中排除标记词，逐行判是否入库：')
        for r in flagged:
            print(f"  行{r['row']}: [{','.join(r['flags'])}] {r['line'][:80]}")

    payload = {'src': str(src), 'page': args.page, 'dpi': args.dpi,
               'crop': str(crop_path), 'engines': list(results.keys()),
               'rows': row_recs, 'sums': sums, 'ratios': ratios, 'summary': summary}
    out_json = Path(args.json) if args.json else out_dir / f'{src.stem}_p{args.page}_scan.json'
    json.dump(payload, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\nJSON: {out_json}')


if __name__ == '__main__':
    main()
