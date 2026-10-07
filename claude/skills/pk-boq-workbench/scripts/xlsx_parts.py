"""zip/XML 层的 xlsx 部件操作 — 插列和搬透视表共用一份。

原本这些函数长在 transplant_pivot_pages.py 里，跟那份脚本的项目专用常量绑死，
insert_workbench_cols.py 要用只能复制一份。抽出来之后两边 import 同一份实现，
踩过的坑（命名空间、dxf numFmt 自映射、元素边界）只修一处。

全程字符串拼接，不用 ElementTree。ET 只认注册过的命名空间，mc / x15 / x14ac /
xcalcf 会被改写成 ns1..ns8，根元素上的 mc:Ignorable 属性直接丢失 —— 文档里还留着
x14ac 扩展元素却没了"可忽略"声明，Excel 拒绝打开。危险在于 ET 写的 ET 读得回来，
XML 良构检查、openpyxl、LibreOffice 全放行，只有 Excel 严格。
"""
import re
from pathlib import Path

CT = "application/vnd.openxmlformats-officedocument.spreadsheetml"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

STYLE_ORDER = ["numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs",
               "cellStyles", "dxfs", "tableStyles", "colors", "extLst"]

QUOTED = re.compile(r'"[^"]*"')
REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")
ROW_RE = re.compile(r'<row r="(\d+)"([^>]*)>(.*?)</row>', re.S)
CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)


# ── 列号 ──────────────────────────────────────────────────────────────

def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letter(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def shift_segment(seg, delta):
    def repl(m):
        if m.group(1):                       # $C 绝对列按定义不平移
            return m.group(0)
        n = col_index(m.group(2)) + delta
        if n < 1:
            return m.group(0)
        return f"{col_letter(n)}{m.group(3)}{m.group(4)}"
    return REF.sub(repl, seg)


def shift_cols(formula, delta):
    """公式里的列引用整体平移。

    只动引号外的部分 —— 公式里 "[^\\p{L}\\p{N}]+" 这种正则字面量长得很像单元格
    引用，平移它会把公式改坏。
    """
    if not delta:
        return formula
    out, pos = [], 0
    for q in QUOTED.finditer(formula):
        out.append(shift_segment(formula[pos:q.start()], delta))
        out.append(q.group(0))
        pos = q.end()
    out.append(shift_segment(formula[pos:], delta))
    return "".join(out)


# ── 部件定位 ──────────────────────────────────────────────────────────

def sheet_paths(parts):
    """sheet 名 -> xl/worksheets/sheetN.xml。

    别写死 sheet8.xml：worksheets 目录里的编号跟 workbook.xml 的 sheet 顺序无关，
    换个文件同一张表就是另一个编号。
    """
    wb = parts["xl/workbook.xml"]
    if isinstance(wb, bytes):
        wb = wb.decode("utf8")
    rels_raw = parts["xl/_rels/workbook.xml.rels"]
    if isinstance(rels_raw, bytes):
        rels_raw = rels_raw.decode("utf8")
    rels = {m.group(1): m.group(2) for m in re.finditer(
        r'<Relationship[^>]*?Id="([^"]+)"[^>]*?Target="([^"]+)"', rels_raw)}
    out = {}
    for m in re.finditer(r'<sheet name="([^"]+)"[^>]*?r:id="([^"]+)"', wb):
        out[m.group(1)] = "xl/" + rels[m.group(2)].lstrip("/")
    return out


def resolve_sheet(parts, name=None):
    paths = sheet_paths(parts)
    if name:
        if name not in paths:
            raise SystemExit(f"工作簿无 sheet {name!r}，现有: {sorted(paths)}")
        return name, paths[name]
    first = next(iter(paths))
    return first, paths[first]


# ── 读表 ──────────────────────────────────────────────────────────────

def read_sst(parts):
    raw = parts.get("xl/sharedStrings.xml")
    if not raw:
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("utf8")
    out = []
    for m in re.finditer(r"<si\b[^>]*>(.*?)</si>", raw, re.S):
        out.append("".join(re.findall(r"<t\b[^>]*>(.*?)</t>", m.group(1), re.S)))
    return out


def cell_text(inner, attrs, sst):
    t = re.search(r't="(\w+)"', attrs)
    kind = t.group(1) if t else "n"
    if kind == "s":
        v = re.search(r"<v>(\d+)</v>", inner)
        return sst[int(v.group(1))] if v and int(v.group(1)) < len(sst) else ""
    if kind == "inlineStr":
        return "".join(re.findall(r"<t\b[^>]*>(.*?)</t>", inner, re.S))
    v = re.search(r"<v>(.*?)</v>", inner, re.S)
    return v.group(1) if v else ""


def row_cells(sheet_xml, rownum, sst):
    m = re.search(rf'<row r="{rownum}"[^>]*>(.*?)</row>', sheet_xml, re.S)
    if not m:
        return {}
    out = {}
    for c in CELL_RE.finditer(m.group(1)):
        txt = " ".join(cell_text(c.group(4) or "", c.group(3), sst).split())
        if txt:
            out[c.group(1)] = txt
    return out


def find_header_row(sheet_xml, sst, anchor="Description", limit=20):
    for m in ROW_RE.finditer(sheet_xml):
        r = int(m.group(1))
        if r > limit:
            break
        if anchor in row_cells(sheet_xml, r, sst).values():
            return r
    return None


def header_map(sheet_xml, hrow, sst):
    return {txt: col for col, txt in row_cells(sheet_xml, hrow, sst).items()}


def last_row(sheet_xml):
    return max(int(x) for x in re.findall(r'<row r="(\d+)"', sheet_xml))


def data_range(sheet_xml, sheet_name, hrow, sst):
    """表头行到最后一行、最左有内容列到最右有内容列 —— 分类定义区就是这块。"""
    hdr = header_map(sheet_xml, hrow, sst)
    if not hdr:
        raise SystemExit(f"{sheet_name} 第 {hrow} 行没有表头内容")
    cols = [col_index(c) for c in hdr.values()]
    return (f"{sheet_name}!${col_letter(min(cols))}${hrow}:"
            f"${col_letter(max(cols))}${last_row(sheet_xml)}")


# ── styles.xml ────────────────────────────────────────────────────────

def count_children(xml, tag, child):
    m = re.search(rf"<{tag}\b[^>]*[^/]>(.*?)</{tag}>", xml, re.S)
    if not m:
        return 0, None
    return len(re.findall(rf"<{child}\b", m.group(1))), m


def elements(xml, tag, child):
    """取出 <tag> 下的每个 <child> 元素原文。

    child 自身不嵌套（fonts 下不会有 font 套 font），但它带自闭合子元素
    —— <font><sz val="11"/><name val="等线"/></font>。所以判断元素边界要看
    开标签末尾是不是 "/"，不能数 "/>"：数出来第一个 <sz/> 就以为 font 结束了，
    元素会被从中间截断，styles.xml 直接坏掉。
    """
    m = re.search(rf"<{tag}\b[^>]*[^/]>(.*?)</{tag}>", xml, re.S)
    if not m:
        return []
    body, out = m.group(1), []
    close = f"</{child}>"
    for mm in re.finditer(rf"<{child}\b", body):
        st = mm.start()
        open_end = re.compile(r"(/?)>").search(body, mm.end())
        if open_end.group(1):
            out.append(body[st:open_end.end()])
        else:
            out.append(body[st:body.index(close, open_end.end()) + len(close)])
    return out


def append_into(xml, tag, items, child):
    """把 items 插到 <tag>…</tag> 末尾并刷新 count。

    tag 可能是成对标签、自闭合（<dxfs count="0"/>，空表时 Excel 就这么写），
    也可能整个缺失 —— 三种都要接住，缺失时按 STYLE_ORDER 插到合法位置。
    """
    if not items:
        return xml
    body = "".join(items)
    m = re.search(rf"<{tag}\b[^>]*[^/]>(.*?)</{tag}>", xml, re.S)
    if m:
        n = len(re.findall(rf"<{child}\b", m.group(1))) + len(items)
        new = m.group(0)[:m.group(0).rindex(f"</{tag}>")] + body + f"</{tag}>"
    else:
        m = re.search(rf"<{tag}\b[^>]*/>", xml)
        n = len(items)
        new = f"<{tag} count=\"{n}\">{body}</{tag}>"
        if not m:
            for later in STYLE_ORDER[STYLE_ORDER.index(tag) + 1:]:
                nx = re.search(rf"<{later}\b", xml)
                if nx:
                    return xml[:nx.start()] + new + xml[nx.start():]
            return xml.replace("</styleSheet>", new + "</styleSheet>")
    if re.search(rf'^<{tag}\b[^>]*?\bcount="\d+"', new):
        new = re.sub(rf'^(<{tag}\b[^>]*?\b)count="\d+"', rf'\g<1>count="{n}"', new)
    else:
        new = new.replace(f"<{tag}", f'<{tag} count="{n}"', 1)
    return xml[:m.start()] + new + xml[m.end():]


def merge_styles(tgt, tpl):
    """字符串层合并样式表，返回 (新xml, xf映射, dxf偏移)。根元素原样不动。"""
    off = {}
    for tag, child in (("fonts", "font"), ("fills", "fill"),
                       ("borders", "border"), ("dxfs", "dxf")):
        off[tag], _ = count_children(tgt, tag, child)
        tgt = append_into(tgt, tag, elements(tpl, tag, child), child)

    # numFmts：自定义格式(id>=164)重新编号，formatCode 相同的复用。
    #
    # 两边都必须**只看全局 <numFmts> 表**。<dxf> 内部也有 <numFmt>，那是条件格式
    # 自带 formatCode 的局部定义，跟全局编号表没关系。而 dxfs 在这之前已经 append
    # 进 tgt 了，全文扫描就会把模板 dxf 里的 `176=千分位` `180=万元` 当成"目标簿
    # 已有此格式"，推出 nf_map[176]=176、nf_map[180]=180 这种自映射 —— 模板的 xf
    # 于是原样保留 176/180，落到目标簿全局表的 `[$-409]mmm/yy` 和 `[$-F800]dddd`
    # 上，1481 个单元格集体变成日期格式。numFmts 表是干净的，坏的是引用。
    def numfmt_scope(x):
        m2 = re.search(r"<numFmts\b.*?</numFmts>", x, re.S)
        return m2.group(0) if m2 else ""

    by_code = {m.group(2): int(m.group(1)) for m in
               re.finditer(r'<numFmt numFmtId="(\d+)" formatCode="([^"]*)"',
                           numfmt_scope(tgt))}
    used = set(by_code.values()) | {163}
    nf_map, new_nf = {}, []
    for m in re.finditer(r'<numFmt numFmtId="(\d+)" formatCode="([^"]*)"\s*/>',
                         numfmt_scope(tpl)):
        old, code = int(m.group(1)), m.group(2)
        if code in by_code:
            nf_map[old] = by_code[code]
            continue
        new = max(used) + 1
        used.add(new)
        nf_map[old] = new
        new_nf.append(f'<numFmt numFmtId="{new}" formatCode="{code}"/>')
    tgt = append_into(tgt, "numFmts", new_nf, "numFmt")

    base, _ = count_children(tgt, "cellXfs", "xf")
    xfs, xf_map = [], {}
    for i, xf in enumerate(elements(tpl, "cellXfs", "xf")):
        for attr, tag in (("fontId", "fonts"), ("fillId", "fills"),
                          ("borderId", "borders")):
            xf = re.sub(rf'{attr}="(\d+)"',
                        lambda m, t=tag: f'{m.group(0).split("=")[0]}="'
                                         f'{int(m.group(1)) + off[t]}"', xf)
        xf = re.sub(r'numFmtId="(\d+)"',
                    lambda m: f'numFmtId="{nf_map.get(int(m.group(1)), int(m.group(1)))}"'
                    if int(m.group(1)) >= 164 else m.group(0), xf)
        xf = re.sub(r'xfId="\d+"', 'xfId="0"', xf)
        xfs.append(xf)
        xf_map[i] = base + i
    tgt = append_into(tgt, "cellXfs", xfs, "xf")
    return tgt, xf_map, off["dxfs"]


def merge_table_styles(tgt, tpl, dxf_off):
    """把模板的 <tableStyles> 并进目标 —— 透视表样式不在透视表部件里。

    透视表通过 pivotTableStyleInfo name="UniqueBQ" 引用 styles.xml 的
    <tableStyle name="UniqueBQ">；漏搬样式能打开但套不上、回退默认灰白。
    tableStyleElement 的 dxfId 要按 dxf 偏移平移；模板的 tableStyle 带 xr9:uid
    扩展属性，目标簿根元素没声明 xr9 命名空间时先剥离，否则 XML 坏。
    """
    m = re.search(r"<tableStyles\b[^>]*>.*?</tableStyles>", tpl, re.S)
    if not m:
        return tgt
    items = elements(tpl, "tableStyles", "tableStyle")
    if not items:
        return tgt
    fixed = []
    for it in items:
        it = re.sub(r'dxfId="(\d+)"',
                    lambda mm: f'dxfId="{int(mm.group(1)) + dxf_off}"', it)
        it = re.sub(r'\s+xr9:uid="[^"]*"', "", it)
        fixed.append(it)
    have = {mm.group(1) for mm in re.finditer(r'<tableStyle name="([^"]+)"', tgt)}
    fixed = [it for it in fixed
             if re.search(r'name="([^"]+)"', it).group(1) not in have]
    return append_into(tgt, "tableStyles", fixed, "tableStyle")


def remap_s(xml, xf_map):
    def f(m):
        return f'{m.group(1)}{xf_map.get(int(m.group(2)), 0)}{m.group(3)}'
    xml = re.sub(r'(<(?:c|row)\b[^>]*?\bs=")(\d+)(")', f, xml)
    return re.sub(r'(<col\b[^>]*?\bstyle=")(\d+)(")', f, xml)


# ── sharedStrings ─────────────────────────────────────────────────────

def merge_shared_strings(tgt_sst, tpl_sst, pivot_ts):
    """把模板 sharedStrings 的 <si> 追加到目标末尾，返回 (新目标 sst, 偏移量)。

    透视表页从模板直接复制，sheetData 里 t="s" 单元格引用的是模板索引，跟目标簿
    的原清单字符串索引撞不到一起。追加到末尾、模板页索引整体 +offset，模板页字符串
    一个字不错，原 sheet 不用动。
    """
    offset = len(re.findall(r"<si\b", tgt_sst))
    tpl_inner = re.search(r"<sst\b[^>]*>(.*)</sst>", tpl_sst, re.S).group(1)
    tpl_n = len(re.findall(r"<si\b", tpl_inner))
    new = tgt_sst.replace("</sst>", tpl_inner + "</sst>", 1)
    new = re.sub(r'count="(\d+)"',
                 lambda m: f'count="{int(m.group(1)) + pivot_ts}"', new, count=1)
    new = re.sub(r'uniqueCount="(\d+)"',
                 lambda m: f'uniqueCount="{int(m.group(1)) + tpl_n}"', new, count=1)
    return new, offset


def shift_sst_index(xml, offset):
    return re.sub(r'(<c\b[^>]*\bt="s"[^>]*>\s*<v>)(\d+)(</v>)',
                  lambda m: m.group(1) + str(int(m.group(2)) + offset) + m.group(3),
                  xml)


# ── 公式引用 ──────────────────────────────────────────────────────────

def refs_of(formula):
    """公式里引用到的工作表名。`[1]表名!` 是跨簿，本簿名用 sheet!，带引号的另算。"""
    out = set()
    for m in re.finditer(r"(\[\d+\])?'([^']+)'!", formula):
        out.add((m.group(1) or "") + m.group(2))
    for m in re.finditer(r"(?<!['\w!])(\[\d+\])?([A-Za-z一-鿿][\w一-鿿]*)!",
                         formula):
        out.add((m.group(1) or "") + m.group(2))
    return out


def strip_dead_formulas(xml, known, tag, log=print):
    """公式指向本簿没有的表时删 <f> 保留缓存 <v>，让它变成静态值。

    这不是"优化"，是搬运的必要收尾：模板页原本引用模板自己的表，搬过来后有的
    对不上（`合并报表!#REF!` 本就是坏的；`[1]现场管理费及土建汇总` 指模板的外链簿，
    本簿 externalLink1 里没这张表）。留着它们 Excel 每次打开都报"发现不可读取的
    内容"，而缓存值本来就是 #REF! / 死数，转静态一个字节的信息都不丢。
    """
    hits = []

    def one(m):
        head, body = m.group(1), m.group(2)
        f = re.search(r"<f([^>]*)>(.*?)</f>", body, re.S)
        if not f:
            return m.group(0)
        miss = refs_of(f.group(2)) - known
        if not miss:
            return m.group(0)
        if re.search(r'\bsi="', f.group(1)):        # 共享公式的头，删了从属公式会塌
            raise SystemExit(f"{tag} {m.group(1)} 是共享公式头，需人工处理: {miss}")
        hits.append((re.search(r'r="([A-Z]+\d+)"', head).group(1), sorted(miss)))
        return f"<c{head}>{body[:f.start()] + body[f.end():]}</c>"

    out = re.sub(r"<c([^>]*)>(.*?)</c>", one, xml, flags=re.S)
    for ref, miss in hits:
        log(f"    {tag} {ref} 公式引用 {miss} —— 本簿无此表，转为静态值")
    return out, len(hits)


def known_names(parts, extra=()):
    """本簿可解析的表名：自有工作表 + 外链簿的 `[n]表名`。"""
    w = parts["xl/workbook.xml"].decode("utf8")
    names = set(re.findall(r'<sheet name="([^"]+)"', w)) | set(extra)
    rels = {m.group(1): m.group(2) for m in re.finditer(
        r'<Relationship[^>]*?Id="([^"]+)"[^>]*?Target="([^"]+)"',
        parts["xl/_rels/workbook.xml.rels"].decode("utf8"))}
    for i, m in enumerate(re.finditer(r'<externalReference r:id="([^"]+)"', w), 1):
        p = "xl/" + rels[m.group(1)].lstrip("/")
        if p in parts:
            for sn in re.findall(r'<sheetName val="([^"]+)"', parts[p].decode("utf8")):
                names.add(f"[{i}]{sn}")
    return names


# ── workbook.xml ──────────────────────────────────────────────────────

def set_defined_name(wb_xml, name, ref):
    """定义名称：有则替换，没有则新建。

    原实现直接 re.search(...).group(0) 去 replace，目标簿没有这个名称时抛
    AttributeError —— 只有恰好建过工作台的文件能跑通，新项目第一次跑必崩。
    """
    pat = rf'<definedName name="{re.escape(name)}"[^>]*>.*?</definedName>'
    new = f'<definedName name="{name}">{ref}</definedName>'
    if re.search(pat, wb_xml, re.S):
        return re.sub(pat, new, wb_xml, count=1, flags=re.S)
    if "</definedNames>" in wb_xml:
        return wb_xml.replace("</definedNames>", new + "</definedNames>", 1)
    # definedNames 在 CT_Workbook 里排在 sheets 之后、calcPr 之前
    m = re.search(r"</sheets>", wb_xml)
    block = f"<definedNames>{new}</definedNames>"
    return wb_xml[:m.end()] + block + wb_xml[m.end():]


def strip_tab_selected(xml):
    return re.sub(r'\s*tabSelected="1"', "", xml)


def drop_calc_chain(parts):
    """删 calcChain，Excel 打开时自动重建。

    三处要同步清，漏一处文件就打不开：部件本身、[Content_Types].xml 的 Override、
    workbook.xml.rels 的 Relationship。
    """
    if "xl/calcChain.xml" not in parts:
        return
    del parts["xl/calcChain.xml"]
    ct = parts["[Content_Types].xml"].decode("utf8")
    parts["[Content_Types].xml"] = re.sub(
        r'<Override PartName="/xl/calcChain\.xml"[^>]*/>', "", ct).encode("utf8")
    rl = parts["xl/_rels/workbook.xml.rels"].decode("utf8")
    parts["xl/_rels/workbook.xml.rels"] = re.sub(
        r'<Relationship[^>]*Target="calcChain\.xml"[^>]*/>', "", rl).encode("utf8")
