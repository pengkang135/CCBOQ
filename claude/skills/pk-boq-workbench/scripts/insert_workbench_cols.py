#!/usr/bin/env python3
"""在 CombineBQ 左侧插 Main Key，右侧整块复刻模板的报价脚手架。

原清单一个单元格不改：Main Key 靠右移腾位，脚手架全部追加在原清单最右侧。
zip/XML 层做，不用 openpyxl —— 它往返读写会丢 drawing 和 media 部件（图片、
图表全没），而原清单里的图往往是别人已完成的成果。

脚手架 = 模板 r1 第一个分组标签那列起、到表头行最后一列止（EXPORT / COST /
AI / SUBCONTRACTOR 四组，含 AI 组里的 BQ KEY、CleanDescription、分类五列、
Norm/Ref 四列，以及组间的空隔列）。**整块按模板列序复刻，不按列名挑**：
Labor / Material / Equipment / Rate / Amount 在三组里各出现一次，按列名建
字典会键冲突，只有按模板列字母定位才唯一。

原来分「原清单自带脚手架」和「原清单只到 Quantity」两种情况，现在统一成一种
—— 一律整块插入，源清单只需提供 No. / Description / Unit / Qty。

公式和样式都从模板 pivot_template.xlsx 实时取，不写死：模板改过好几版，
写死的公式和列字母每次都要跟着改，漏改一处就是整批错位。

用法:
    python insert_workbench_cols.py 清单.xlsx -o 工作台.xlsx
    python insert_workbench_cols.py in.xlsx -o out.xlsx --sheet CombineBQ --header-row 4
"""
import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, unescape

UNESC = {"&quot;": '"', "&apos;": "'"}

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout
import xlsx_parts as xp

TPL_DEFAULT = Path(__file__).resolve().parent.parent / "references/pivot_template.xlsx"
# 左插的键列。layout.KEY_COLS 是工作台的全部键列（另两个在脚手架块里）
LEFT_COLS = ["Main Key"]
CLASS_COLS = layout.AI_COLS
GROUPS = layout.GROUPS
ANCHOR = "Description"

ALIASES = layout.ALIASES


# ── 插列：把已有内容整体右移 ──────────────────────────────────────────

COL_ONLY = re.compile(r"^(\$?)([A-Z]{1,3}):(\$?)([A-Z]{1,3})$")


def shift_ref(ref, at, delta):
    m = COL_ONLY.match(ref.strip())
    if m:                                   # 整列引用 A:C / $H:$Z，没有行号
        d1, c1, d2, c2 = m.groups()
        n1, n2 = xp.col_index(c1), xp.col_index(c2)
        return (f"{d1}{xp.col_letter(n1 + delta) if n1 >= at else c1}:"
                f"{d2}{xp.col_letter(n2 + delta) if n2 >= at else c2}")

    def one(mm):
        dollar_c, letters, dollar_r, row = mm.groups()
        n = xp.col_index(letters)
        if n < at:
            return mm.group(0)
        return f"{dollar_c}{xp.col_letter(n + delta)}{dollar_r}{row}"
    return xp.REF.sub(one, ref)


TOKEN = re.compile(
    r"(?:(\[\d+\])?('[^']+'|[A-Za-z一-鿿][\w一-鿿]*)!)?"
    r"(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?"
    r"|\$?[A-Z]{1,3}:\$?[A-Z]{1,3})")


def shift_formula(f, at, delta, sheet_name):
    """公式列引用平移。

    跨表引用不动 —— 别的 sheet 没插列。本表名加感叹号的（CombineBQ!A1）要动，
    它指的就是这张表。插列跟 shared formula 展开不同：绝对引用 $A$1 也要平移，
    Excel 自己插列时就是这个语义。

    表名前缀和引用必须一次匹配完：分开扫的话 `Sheet2!A1:C10` 的 C10 落单，
    会被当成本表引用平移，区域右边界就错了。
    """
    def one(m):
        ext, name, ref = m.group(1), m.group(2), m.group(3)
        if name is not None:
            if ext or name.strip("'") != sheet_name:
                return m.group(0)
        return (m.group(0)[:m.start(3) - m.start(0)]
                + shift_ref(ref, at, delta))

    out, pos = [], 0
    for q in xp.QUOTED.finditer(f):
        out.append(TOKEN.sub(one, f[pos:q.start()]))
        out.append(q.group(0))
        pos = q.end()
    out.append(TOKEN.sub(one, f[pos:]))
    return "".join(out)


def insert_columns(sheet_xml, at, n, sheet_name):
    """把 at 列及其右侧的一切整体右移 n 列。"""

    def cell(m):
        col, row, attrs, inner = m.group(1), m.group(2), m.group(3), m.group(4)
        idx = xp.col_index(col)
        if idx >= at:
            attrs_ref = f'<c r="{xp.col_letter(idx + n)}{row}"{attrs}'
        else:
            attrs_ref = f'<c r="{col}{row}"{attrs}'
        if inner is None:
            return attrs_ref + "/>"
        body = re.sub(r"<f([^>]*)>(.*?)</f>",
                      lambda f: f"<f{f.group(1)}>"
                                f"{escape(shift_formula(unescape(f.group(2), UNESC), at, n, sheet_name))}"
                                f"</f>",
                      inner, flags=re.S)
        return attrs_ref + ">" + body + "</c>"

    out = xp.CELL_RE.sub(cell, sheet_xml)

    out = re.sub(r'<row([^>]*?)spans="(\d+):(\d+)"',
                 lambda m: f'<row{m.group(1)}spans="{m.group(2)}:{int(m.group(3)) + n}"',
                 out)

    def colspec(m):
        lo, hi = int(m.group(2)), int(m.group(3))
        if hi < at:
            return m.group(0)
        return (f'<col{m.group(1)}min="{lo + n if lo >= at else lo}"'
                f' max="{hi + n}"{m.group(4)}')
    out = re.sub(r'<col([^>]*?)min="(\d+)" max="(\d+)"([^>]*?)(?=/>)', colspec, out)

    for tag, attr in (("autoFilter", "ref"), ("mergeCell", "ref"),
                      ("hyperlink", "ref"), ("conditionalFormatting", "sqref"),
                      ("dataValidation", "sqref"), ("tablePart", "ref")):
        out = re.sub(rf'(<{tag}\b[^>]*?\b{attr}=")([^"]+)(")',
                     lambda m: m.group(1) + shift_ref(m.group(2), at, n) + m.group(3),
                     out)

    # dimension 只扩右边界：左边界是新键列的起点，跟着平移就把 A..C 漏在区外了
    def dim(m):
        lo, hi = m.group(2), m.group(3)
        hm = xp.REF.match(hi)
        if hm:
            hi = (f"{hm.group(1)}{xp.col_letter(xp.col_index(hm.group(2)) + n)}"
                  f"{hm.group(3)}{hm.group(4)}")
        return f'{m.group(1)}{lo}:{hi}"'
    return re.sub(r'(<dimension ref=")([^":]+):([^"]+)"', dim, out)


# ── 写新列 ────────────────────────────────────────────────────────────

def col_at(tpl_sheet, tpl_hdr, col, header=None):
    """按模板列字母取该列的表头样式和数据行样板。

    只有列字母唯一：Labor / Material / Equipment / Rate / Amount 在 EXPORT /
    COST / SUBCONTRACTOR 三组里各出现一次，按列名取会串组。

    共享公式取宿主行 —— 跟随行是 `<f t="shared" si="0"/>` 自闭合、没有公式
    文本，正则匹配不上会自动跳过，而宿主行在 sheetData 里排在前面。
    """
    hs = re.search(rf'<c r="{col}{tpl_hdr}"([^>]*)', tpl_sheet)
    hstyle = re.search(r's="(\d+)"', hs.group(1)) if hs else None
    base = {"name": header, "tpl_col": col,
            "header_s": hstyle.group(1) if hstyle else None,
            "data_s": None, "formula": None, "src_row": None,
            "group": None, "group_s": None}
    fallback = None

    for m in xp.ROW_RE.finditer(tpl_sheet):
        r = int(m.group(1))
        if r <= tpl_hdr:
            continue
        c = re.search(rf'<c r="{col}{r}"([^>]*?)(?:/>|>(.*?)</c>)', m.group(3), re.S)
        if not c:
            continue
        s = re.search(r's="(\d+)"', c.group(1))
        entry = dict(base, data_s=s.group(1) if s else None, src_row=r)
        f = re.search(r"<f[^>]*>(.*?)</f>", c.group(2) or "", re.S)
        if f:
            entry["formula"] = unescape(f.group(1), UNESC)
            return entry
        if fallback is None and s:
            fallback = entry
    return fallback if fallback is not None else base


def col_template(tpl_sheet, tpl_hdr, tpl_sst, name, need_formula=True):
    """按列名取样板 —— 只用于左插的键列，那几个名字在模板里唯一。

    need_formula=False 用于数据行本来就空的列（值交给 pk-boq-classify 填），
    但样式不能省：表头深红底白字、数据行有自己的 s 值，统一成一种就跟模板
    对不上了。
    """
    hdrmap = xp.header_map(tpl_sheet, tpl_hdr, tpl_sst)
    if name not in hdrmap:
        raise SystemExit(f"模板表头第 {tpl_hdr} 行找不到 {name!r}，"
                         f"现有: {sorted(hdrmap)}")
    sp = col_at(tpl_sheet, tpl_hdr, hdrmap[name], header=name)
    if need_formula and not sp["formula"]:
        raise SystemExit(f"模板 {name!r} 列在数据行里没有公式，无法取样板")
    if not need_formula and sp["data_s"] is None:
        raise SystemExit(f"模板 {name!r} 列在数据行里没有样式，无法取样板")
    return sp


def group_row(tpl_sheet, tpl_hdr, tpl_sst):
    """找分组标签行 —— 表头行上方、含 EXPORT / COST 之类标签的那行。"""
    for r in range(1, tpl_hdr):
        cells = xp.row_cells(tpl_sheet, r, tpl_sst)
        labels = {c: v for c, v in cells.items() if v in GROUPS}
        if labels:
            return r, labels
    return None, {}


def block_specs(tpl_sheet, tpl_hdr, tpl_sst):
    """脚手架块：分组标签行第一个标签那列起，到表头行最后一列止。

    组之间没有表头名的空隔列一起复刻 —— 少了它们分组标签的跨度、透视缓存的
    字段序号（模板里那几个 `字段12` / `字段29` 占位）都会错位。
    """
    grow, labels = group_row(tpl_sheet, tpl_hdr, tpl_sst)
    if not labels:
        raise SystemExit(f"模板表头第 {tpl_hdr} 行上方找不到分组标签行（{GROUPS}）")

    # 表头名按列直接读，不走 header_map —— 那是列名→列字母，Labor / Material /
    # Equipment / Rate / Amount 在三组里重名，字典里只活得下来一个，反查出来的
    # 列名会有一整组是空的（表头丢名、只剩公式和样式）。
    hdrcells = xp.row_cells(tpl_sheet, tpl_hdr, tpl_sst)
    by_idx = {xp.col_index(c): v for c, v in hdrcells.items() if v}
    lbl_idx = {xp.col_index(c): v for c, v in labels.items()}
    start, end = min(lbl_idx), max(by_idx)
    if end < start:
        raise SystemExit(f"模板分组标签在第 {start} 列，表头最右只到第 {end} 列")

    specs = []
    for idx in range(start, end + 1):
        col = xp.col_letter(idx)
        sp = col_at(tpl_sheet, tpl_hdr, col, header=by_idx.get(idx))
        if idx in lbl_idx:
            gs = re.search(rf'<c r="{col}{grow}"([^>]*)', tpl_sheet)
            sp["group"] = lbl_idx[idx]
            sp["group_s"] = (re.search(r's="(\d+)"', gs.group(1)).group(1)
                             if gs and re.search(r's="(\d+)"', gs.group(1)) else None)
        specs.append(sp)
    return specs, grow


def retarget(formula, lookup, tpl_row, row, tpl_start=None, start=None):
    """样板公式重定向：模板的列字母换成目标簿的，行号换成目标簿的对应行。

    `lookup` 是模板列字母 → 目标列字母，由调用方拼：源清单那几列按列名对，
    脚手架块按位置对（块里列名重复，只能按位置）。

    两种行号都要换。样板行（tpl_row）换成当前行是显然的；容易漏的是数据起始行
    —— Main Key 的 DataRng 是 `$E$4:E18` 这种从数据首行累积到当前行的区域，
    起点 4 是**模板的**数据首行。目标簿表头在第 5 行时数据从第 6 行起，起点还
    留着 4 就把表头行和上面的空行圈进了 LOOKUP 区，上级标题会追溯错。
    """
    def one(m):
        dc, letters, dr, rownum = m.groups()
        col = lookup.get(letters, letters)
        n = int(rownum)
        if n == tpl_row:
            rn = str(row)
        elif tpl_start is not None and n == tpl_start:
            rn = str(start)
        else:
            rn = rownum
        return f"{dc}{col}{dr}{rn}"

    out, pos = [], 0
    for q in xp.QUOTED.finditer(formula):
        out.append(xp.REF.sub(one, formula[pos:q.start()]))
        out.append(q.group(0))
        pos = q.end()
    out.append(xp.REF.sub(one, formula[pos:]))
    return "".join(out)


def put_cell(row_xml, col, rownum, payload):
    """把 <c> 插到 row 里的正确列序位置 —— Excel 要求 c 按列号升序。"""
    idx = xp.col_index(col)
    for m in xp.CELL_RE.finditer(row_xml):
        if xp.col_index(m.group(1)) > idx:
            return row_xml[:m.start()] + payload + row_xml[m.start():]
    return row_xml + payload


def load_classification(path, sheet_xml, hrow, data_rows, sst, desc_col):
    """读 classification.json，用 desc_head 断言没错位，返回 {行号: {列名: 值}}。

    这里不用换算行号：脚本是原地插列、行号不动，分类结果的 src_row 就是目标簿的
    行号。断言照做 —— 对不上就是分类跑的不是这份清单，宁可停下也别写错一整批。
    """
    from build_workbook import load_classification as _load
    values, heads = _load(path)

    desc = {}
    for r in data_rows:
        cells = xp.row_cells(sheet_xml, r, sst)
        if desc_col in cells:
            desc[r] = cells[desc_col]

    bad = []
    for r, h in heads.items():
        if not h or r not in desc:
            continue
        if not desc[r].startswith(h[:24]):
            bad.append(f"  行 {r}: 分类结果记的是 {h[:28]!r}，清单里是 {desc[r][:28]!r}")
    if bad:
        raise SystemExit("分类结果与清单错位，未写入任何分类值:\n" + "\n".join(bad[:15])
                         + (f"\n  …共 {len(bad)} 处" if len(bad) > 15 else ""))
    return {r: v for r, v in values.items() if r in data_rows and v}


def write_cols(sheet_xml, specs, lookup, hrow, data_rows, xf_map,
               tpl_start=None, start=None, grow=None, last_col=None, values=None):
    """按每个 spec 自带的 tgt_col 写列，返回 (新xml, 命中行号集合)。

    左插键列和右侧整块脚手架共用这一条路径 —— 区别只在 tgt_col 是插进来的还是
    追加的。有 formula 的写公式；分类五列没公式，有 values 就写值，没有就只铺
    样式留空（等 pk-boq-classify 之后再填）；空隔列连表头都没有，只铺样式。

    命中集合必须回传：sheetData 里只有实际存在的 <row> 元素，全空行在 XML 里
    根本没有对应节点，sub 扫不到就静默漏写，产物看着正常但那几行没有公式。
    """
    hit = set()
    values = values or {}

    def row(m):
        r, attrs, body = int(m.group(1)), m.group(2), m.group(3)
        if r != hrow and r != grow and r not in data_rows:
            return m.group(0)
        for sp in specs:
            col = sp["tgt_col"]
            name = sp["name"]
            if r == grow:
                if not sp["group"]:
                    continue
                s = xf_map.get(int(sp["group_s"]), 0) if sp["group_s"] else 0
                cx = (f'<c r="{col}{r}" s="{s}" t="inlineStr">'
                      f"<is><t>{escape(sp['group'])}</t></is></c>")
                body = put_cell(body, col, r, cx)
                continue
            raw = sp["header_s"] if r == hrow else sp["data_s"]
            s = xf_map.get(int(raw), 0) if raw else 0
            if r == hrow:
                if not name:
                    cx = f'<c r="{col}{r}" s="{s}"/>'
                else:
                    cx = (f'<c r="{col}{r}" s="{s}" t="inlineStr">'
                          f"<is><t>{escape(name)}</t></is></c>")
            elif sp["formula"]:
                f = retarget(sp["formula"], lookup, sp["src_row"], r,
                             tpl_start, start)
                cx = f'<c r="{col}{r}" s="{s}"><f>{escape(f)}</f></c>'
            elif name and name in values.get(r, {}):
                cx = (f'<c r="{col}{r}" s="{s}" t="inlineStr">'
                      f"<is><t>{escape(values[r][name])}</t></is></c>")
            else:
                cx = f'<c r="{col}{r}" s="{s}"/>'
            body = put_cell(body, col, r, cx)
        hit.add(r)
        return f'<row r="{r}"{attrs}>{body}</row>'

    out = xp.ROW_RE.sub(row, sheet_xml)
    if last_col:
        out = re.sub(r'(<dimension ref="[^":]+:)\$?[A-Z]+(\d+")',
                     lambda m: f"{m.group(1)}{last_col}{m.group(2)}", out)
    return out, hit


# ── 主流程 ────────────────────────────────────────────────────────────

def apply(parts, tpl, xf_map, sheet=None, header_row=None, tpl_sheet=layout.SHEET,
          defined_name="分类定义区", classification=None, dry_run=False, log=print):
    """在 parts 上原地插列。样式由调用方先 merge 好并传 xf_map 进来。

    样式合并不放这里：串在 transplant 前面时两边各合一次，模板样式在 styles.xml
    里存两份、cellXfs 白涨一倍。build_bench.py 合一次，两步共用同一个 xf_map。
    """
    sheet_name, sheet_path = xp.resolve_sheet(parts, sheet)
    sx = parts[sheet_path].decode("utf8")
    sst = xp.read_sst(parts)

    hrow = header_row or xp.find_header_row(sx, sst, ANCHOR)
    if not hrow:
        raise SystemExit(f"{sheet_name} 前 20 行找不到表头（锚点 {ANCHOR!r}），"
                         f"用 --header-row 指定")
    tgt_hdr = xp.header_map(sx, hrow, sst)
    if ANCHOR not in tgt_hdr:
        raise SystemExit(f"表头第 {hrow} 行没有 {ANCHOR!r}，现有: {sorted(tgt_hdr)}")

    already = [k for k in LEFT_COLS + CLASS_COLS if k in tgt_hdr]
    if already:
        raise SystemExit(f"{sheet_name} 已有工作台列 {already}，无需重复装配")

    first_col = min(xp.col_index(c) for c in tgt_hdr.values())
    n = len(LEFT_COLS)
    lastr = xp.last_row(sx)
    data_rows = set(range(hrow + 1, lastr + 1))

    tpl_sheet_name, tpl_path = xp.resolve_sheet(tpl, tpl_sheet)
    tx = tpl[tpl_path].decode("utf8")
    tsst = xp.read_sst(tpl)
    tpl_hrow = xp.find_header_row(tx, tsst, ANCHOR)
    if not tpl_hrow:
        raise SystemExit(f"模板 {tpl_sheet_name} 找不到表头行")
    tpl_hdr = xp.header_map(tx, tpl_hrow, tsst)

    keys = {name: col_template(tx, tpl_hrow, tsst, name) for name in LEFT_COLS}
    block, tpl_grow = block_specs(tx, tpl_hrow, tsst)

    log(f"目标: {sheet_name}  表头行 {hrow}  数据 {hrow+1}..{lastr}")
    log(f"模板: {tpl_sheet_name}  表头行 {tpl_hrow}  分组行 {tpl_grow}")
    log(f"左插: 第 {first_col} 列（{xp.col_letter(first_col)}）左侧 {n} 列")
    for name in LEFT_COLS:
        sp = keys[name]
        log(f"  {name:16s} 样板行 {sp['src_row']}  "
            f"公式 {sp['formula'][:60]}{'…' if len(sp['formula']) > 60 else ''}")
    named = [sp["name"] for sp in block if sp["name"]]
    log(f"右侧整块复刻: 模板 {block[0]['tpl_col']}..{block[-1]['tpl_col']} "
        f"共 {len(block)} 列（{len(named)} 个具名列 + "
        f"{len(block) - len(named)} 个空隔列）")

    values = None
    if classification:
        values = load_classification(classification, sx, hrow, data_rows, sst,
                                     tgt_hdr[ANCHOR])
        filled = sum(len(v) for v in values.values())
        log(f"分类结果: 命中 {len(values)} 行，{filled} 个值（desc_head 断言已过）")
    if dry_run:
        return None

    sx = insert_columns(sx, first_col, n, sheet_name)

    # 插完之后表头列字母全变了，重新读一次才是新坐标
    tgt_hdr2 = xp.header_map(sx, hrow, sst)
    for i, name in enumerate(LEFT_COLS):
        keys[name]["tgt_col"] = xp.col_letter(first_col + i)
        tgt_hdr2[name] = keys[name]["tgt_col"]

    base = max(xp.col_index(c) for c in tgt_hdr2.values())
    for i, sp in enumerate(block):
        sp["tgt_col"] = xp.col_letter(base + 1 + i)

    # 模板列字母 → 目标列字母。源清单那几列按列名对（模板 B..E 对应 No. /
    # Description / Unit / Qty），脚手架块按位置对 —— 块里列名重复，按名字对
    # 会把三组的 Amount 全指到同一列。块的映射放后面写，位置优先于名字。
    lookup = {}
    for name, tcol in tpl_hdr.items():
        for alias in ALIASES.get(name, (name,)):
            if alias in tgt_hdr2:
                lookup[tcol] = tgt_hdr2[alias]
                break
    lookup.update({sp["tpl_col"]: sp["tgt_col"] for sp in block})

    # 没映射到的模板列如果被样板公式引用，重定向会原样留着模板列字母，指到
    # 目标簿的别的列去 —— 产物看着正常，数是错的。宁可停下。
    blk = {sp["tpl_col"] for sp in block}
    used = set()
    for sp in list(block) + [keys[n] for n in LEFT_COLS]:
        if sp["formula"]:
            used |= {m.group(2) for m in xp.REF.finditer(sp["formula"])}
    orphan = sorted(used - set(lookup) - blk,
                    key=lambda c: (len(c), c))
    if orphan:
        raise SystemExit(
            f"模板列 {orphan} 被样板公式引用，但在 {sheet_name} 里找不到对应列。\n"
            f"  模板表头: {sorted(tpl_hdr)}\n"
            f"  目标表头: {sorted(tgt_hdr2)}\n"
            f"  源清单缺列或列名不一致，补齐后再装配")

    last_col = xp.col_letter(base + len(block))
    want = data_rows | {hrow}
    sx, hit = write_cols(sx, [keys[n] for n in LEFT_COLS], lookup, hrow,
                         data_rows, xf_map, tpl_hrow + 1, hrow + 1)
    miss = sorted(want - hit)
    log(f"写入键列: 命中 {len(hit)}/{len(want)} 行")
    if miss:
        head = ", ".join(str(x) for x in miss[:10])
        raise SystemExit(f"以下行在 sheetData 里没有 <row> 元素，未写入: "
                         f"{head}{' …' if len(miss) > 10 else ''}（共 {len(miss)} 行）")

    grow = hrow - (tpl_hrow - tpl_grow)
    if grow < 1:
        log(f"目标表头在第 {hrow} 行，上方放不下分组标签行，跳过分组标签")
        grow = None
    sx, hit2 = write_cols(sx, block, lookup, hrow, data_rows, xf_map,
                          tpl_hrow + 1, hrow + 1, grow=grow,
                          last_col=last_col, values=values)
    log(f"追加脚手架: {len(block)} 列 "
        f"({block[0]['tgt_col']}..{last_col})，命中 {len(hit2)}/{len(want)} 行"
        + (f"，分组标签写在第 {grow} 行" if grow else ""))
    miss2 = sorted(want - hit2)
    if miss2:
        head = ", ".join(str(x) for x in miss2[:10])
        raise SystemExit(f"脚手架列以下行未写入: "
                         f"{head}{' …' if len(miss2) > 10 else ''}（共 {len(miss2)} 行）")
    parts[sheet_path] = sx.encode("utf8")

    left = xp.col_letter(first_col)
    rng = f"{sheet_name}!${left}${hrow}:${last_col}${lastr}"
    parts["xl/workbook.xml"] = xp.set_defined_name(
        parts["xl/workbook.xml"].decode("utf8"), defined_name, rng).encode("utf8")
    log(f"分类定义区 → {rng}")
    return {"sheet": sheet_name, "header_row": hrow, "range": rng}


def main():
    ap = argparse.ArgumentParser(description="左插 Main Key + 右侧整块复刻模板脚手架 + 分类定义区")
    ap.add_argument("source")
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--template", default=str(TPL_DEFAULT))
    ap.add_argument("--sheet", help="目标 sheet 名，默认自动认含 Description 的那张")
    ap.add_argument("--header-row", type=int, help="表头行号，默认自动探测")
    ap.add_argument("--tpl-sheet", default=layout.SHEET)
    ap.add_argument("--defined-name", default="分类定义区")
    ap.add_argument("--classification",
                    help="pk-boq-classify 产出的 classification.json，装配时把五个分类列一并写入")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    tplp = Path(a.template)
    if not tplp.exists():
        raise SystemExit(f"模板不存在: {tplp}")
    with zipfile.ZipFile(a.source) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    with zipfile.ZipFile(tplp) as z:
        tpl = {n: z.read(n) for n in z.namelist()}

    if a.dry_run:
        apply(parts, tpl, {}, a.sheet, a.header_row, a.tpl_sheet,
              a.defined_name, a.classification, dry_run=True)
        print("dry-run，未写文件")
        return

    xf_map, _ = merge_template_styles(parts, tpl)
    apply(parts, tpl, xf_map, a.sheet, a.header_row, a.tpl_sheet,
          a.defined_name, a.classification)
    xp.drop_calc_chain(parts)
    write_parts(parts, a.output)
    print(f"完成 → {a.output}")


def merge_template_styles(parts, tpl, log=print):
    st, xf_map, dxf_off = xp.merge_styles(
        parts["xl/styles.xml"].decode("utf8"), tpl["xl/styles.xml"].decode("utf8"))
    st = xp.merge_table_styles(st, tpl["xl/styles.xml"].decode("utf8"), dxf_off)
    parts["xl/styles.xml"] = st.encode("utf8")
    log(f"样式合并: cellXfs +{len(xf_map)}，dxf 偏移 {dxf_off}，"
        f"根元素与 mc:Ignorable 原样保留")
    return xf_map, dxf_off


def write_parts(parts, out):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
        for name, data in parts.items():
            o.writestr(name, data)


if __name__ == "__main__":
    main()
