"""把合并清单套进报价工作台模板 — 纯 Python，不启动 Excel。

以 pivot_template.xlsx 为基底复制一份，只重写「CombineBQ」的 sheetData，
其余部件（透视表 / 缓存 / UniqueShot 表 / 样式 / 元数据）字节级保留。
源清单只需要 No. / Description / Unit / Quantity 四列，其余 33 列的公式脚手架
由本脚本按模板样板行生成。

用法:
    python build_workbook.py <merged.xlsx> -o <out.xlsx> [--sheet Sheet1]
                             [--col-desc E --col-unit F --col-qty G --col-no D]
                             [--header-row 1] [--subcontractor 二航三]
                             [--classification classification.json]

--classification 接 pk-boq-classify 的产物，装配时把五个分类列一并写入：
按 src_row 落行、用 desc_head 断言没错位。分类排在装配之前 —— 透视表按
Discipline/SortKey/Category 汇总，分类列空着刷出来只有 (空白)。

列位一律按模板表头名解析，不写死列字母：模板改过好几版（RFQPlan→CostSummary、
入价→成本），写死过一次就认错样板行、小计写错列。

模板视为只读资产：用 Excel 打开再保存会重写 sheet XML，产出的文件 Excel 打不开。
"""
import argparse
import json
import re
import shutil
import zipfile
from collections import defaultdict

import layout
from pathlib import Path
from xml.sax.saxutils import escape, unescape

TEMPLATE_SHEET = layout.SHEET
SHOT_SHEET = "UniqueShot"
HEADER_ROW = 3
DATA_START = 5
RANGE_NAME = "分类定义区"
LAST_COL = "AM"

L1, L2, L3 = "【", "《", "{"
ROW_MARK = "ROW"
TOTAL_MARK = "TOT"
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


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


def row_kind(desc):
    """行类型判定 — 与 pk-boq-hierarchy 的层级符号一致。"""
    d = (desc or "").strip()
    if d.startswith(L1):
        return "l1"
    if d.startswith(L2):
        return "l2"
    if d.startswith(L3):
        return "l3"
    return "item"


# ── 源清单读取 ────────────────────────────────────────────────────────

def load_source(path, sheet=None, cols=None, header_row=1):
    import fastexcel
    wb = fastexcel.read_excel(str(path))
    name = sheet or wb.sheet_names[0]
    if name not in wb.sheet_names:
        raise RuntimeError(f"源文件无 sheet {name!r}，现有: {wb.sheet_names}")
    grid = wb.load_sheet(name, header_row=None).to_pandas().values

    if cols:
        idx = {k: col_index(v.upper()) - 1 for k, v in cols.items()}
    else:
        idx = detect_columns(grid, header_row - 1)

    rows = []
    for r in range(header_row, grid.shape[0]):
        get = lambda k: cell_str(grid[r, idx[k]]) if idx.get(k) is not None and idx[k] < grid.shape[1] else ""
        desc = get("desc")
        if not desc and not get("unit") and not get("qty"):
            continue
        rows.append({
            # src_row 是源清单的 Excel 行号，分类结果靠它对回来（grid 从第 1 行起，故 +1）
            "src_row": r + 1,
            "no": get("no"),
            "desc": desc,
            "unit": get("unit"),
            "qty": to_number(grid[r, idx["qty"]]) if idx.get("qty") is not None and idx["qty"] < grid.shape[1] else None,
        })
    return rows


def detect_columns(grid, hrow):
    """按表头关键字定位四列。合并产物的列序不固定，硬编码列号会错位。"""
    want = {
        "no": ("no.", "no", "item no", "序号", "编号", "项目编号"),
        "desc": ("description", "item description", "描述", "名称", "项目名称"),
        "unit": ("unit", "单位"),
        "qty": ("quantity", "qty", "工程量", "数量"),
    }
    idx = {}
    if hrow < grid.shape[0]:
        for c in range(grid.shape[1]):
            v = cell_str(grid[hrow, c]).lower().strip()
            if not v:
                continue
            for key, keys in want.items():
                if key not in idx and v in keys:
                    idx[key] = c
    missing = [k for k in ("desc", "unit", "qty") if k not in idx]
    if missing:
        raise RuntimeError(
            f"表头行第 {hrow + 1} 行未找到列: {missing}。用 --col-desc/--col-unit/--col-qty 显式指定")
    return idx


def cell_str(v):
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "none", "nat"):
        return ""
    return s


def to_number(v):
    s = cell_str(v).replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── 模板样板行提取 ────────────────────────────────────────────────────

ROW_RE = re.compile(r'<row r="(\d+)"([^>]*)>(.*?)</row>', re.S)
CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
F_RE = re.compile(r"<f([^>]*?)(?:/>|>(.*?)</f>)", re.S)


def find_qty_col(hdr):
    """工程量列 —— 模板这一版叫 Qty，早先叫 Quantity，两种都认。"""
    for name in layout.ALIASES["Qty"]:
        col = find_header_col(hdr, name)
        if col:
            return col
    return None


def cell_text_at(body, col, sst):
    """读某列的显示文本 —— parse_cells 只留公式，值不留，这里单独取。"""
    m = re.search(rf'<c r="{col}\d+"([^>]*?)(?:/>|>(.*?)</c>)', body, re.S)
    if not m:
        return ""
    attrs, inner = m.group(1), m.group(2) or ""
    t = re.search(r"<t[^>]*>(.*?)</t>", inner, re.S)
    if t:
        return t.group(1)
    v = re.search(r"<v>(.*?)</v>", inner, re.S)
    if not v:
        return ""
    if 't="s"' in attrs:
        i = int(v.group(1))
        return sst[i] if i < len(sst) else ""
    return v.group(1)


def extract_templates(sheet_xml, sst=()):
    """从模板 sheetData 里挑 4 类样板行，公式行号替换成占位符。

    模板改版后重跑即可跟随，不需要同步任何常量 —— 唯一的约定是模板里
    必须各留一行 L1 / L2 / L3 / 有量明细行，以及末尾的 TOTAL 行。
    """
    rows = {int(m.group(1)): m for m in ROW_RE.finditer(sheet_xml)}
    shared = collect_shared(sheet_xml)
    hdr = read_template_headers(sheet_xml, sst)
    groups = split_groups(hdr)

    desc_col = next((c for c, n in hdr.items() if n == layout.ANCHOR), None)
    if not desc_col:
        raise SystemExit(f"模板表头里找不到 {layout.ANCHOR!r} 列")

    tpl, total_row = {}, None
    for r in sorted(rows):
        if r <= HEADER_ROW + 1:
            continue
        m = rows[r]
        cells = parse_cells(m.group(3), r, shared)
        kind = classify_template_row(cells, hdr,
                                     cell_text_at(m.group(3), desc_col, sst))
        if kind == "total":
            total_row = r
            tpl.setdefault("total", (m.group(2), cells, r))
        elif kind == "item":
            if "item" not in tpl or (item_score(cells, hdr, groups)
                                     > item_score(tpl["item"][1], hdr, groups)):
                tpl["item"] = (m.group(2), cells, r)
        elif kind and kind not in tpl:
            tpl[kind] = (m.group(2), cells, r)
    return tpl, total_row, hdr


def item_score(cells, hdr, groups):
    """挑公式列最全的明细样板：某一组的人材机四件套齐全的优先。

    模板里按项计价的条目只填了 Labor，拿它当样板会让整表少掉
    Material / Equipment 两列的拆分公式。
    """
    fcols = {c for c, d in cells.items() if d["f"]}
    by_group = defaultdict(set)
    for c in fcols:
        if hdr.get(c) in CRAFT_HEADERS:
            by_group[groups.get(c)].add(hdr[c])
    full = any(len(v) == len(CRAFT_HEADERS) for v in by_group.values())
    return (100 if full else 0) + len(fcols)


def collect_shared(sheet_xml):
    """shared formula 只有宿主格存公式文本，引用格是空的 <f t="shared" si="N"/>。
    先按 si 收好宿主的文本和行号，解析时展开成独立公式。"""
    out = {}
    for m in ROW_RE.finditer(sheet_xml):
        r = int(m.group(1))
        for c in CELL_RE.finditer(m.group(3)):
            f = F_RE.search(c.group(4) or "")
            if not f or not f.group(2):
                continue
            si = re.search(r'si="(\d+)"', f.group(1) or "")
            if si and si.group(1) not in out:
                out[si.group(1)] = (f.group(2), r, c.group(1))
    return out


QUOTED = re.compile(r'"[^"]*"')
REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")


def shift_cols(formula, delta):
    """shared formula 的引用是相对的，展开到别的列要跟着平移。

    只动引号外的部分 —— 公式里 "[^\\p{L}\\p{N}]+" 这种正则字面量长得很像
    单元格引用，平移它会把公式改坏。绝对列（$C）按定义不平移。
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


def shift_segment(seg, delta):
    def repl(m):
        if m.group(1):
            return m.group(0)
        n = col_index(m.group(2)) + delta
        if n < 1:
            return m.group(0)
        return f"{col_letter(n)}{m.group(3)}{m.group(4)}"
    return REF.sub(repl, seg)


def parse_cells(body, r, shared=None):
    out = {}
    for m in CELL_RE.finditer(body):
        col, attrs, inner = m.group(1), m.group(3), m.group(4) or ""
        s = re.search(r's="(\d+)"', attrs)
        f = F_RE.search(inner)
        text, src = (f.group(2), r) if f else (None, r)
        f_attrs = f.group(1) if f else None
        if f and not text and shared:
            si = re.search(r'si="(\d+)"', f_attrs or "")
            if si and si.group(1) in shared:
                text, src, host_col = shared[si.group(1)]
                text = shift_cols(text, col_index(col) - col_index(host_col))
                f_attrs = ""
        out[col] = {
            "s": s.group(1) if s else None,
            "cm": ' cm="1"' if 'cm="1"' in attrs else "",
            "f_attrs": f_attrs,
            "f": text,
            "f_row": src,
        }
    return out


KEY_HEADERS = ("Main Key", "BQ KEY", "CleanDescription")
CRAFT_HEADERS = ("Labor", "Material", "Equipment")
AI_HEADERS = ("Discipline", "SortKey", "Category", "Subcategory", "Element")


def _clean_text(s):
    return " ".join(unescape(re.sub(r"&#\d+;", " ", s)).split())


def read_shared_strings(parts):
    """sharedStrings 表。模板改版后表头存进了共享串池，不解析就只能读到索引数字。"""
    raw = parts.get("xl/sharedStrings.xml")
    if not raw:
        return []
    xml = raw.decode("utf8")
    return [_clean_text("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)))
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def read_template_headers(sheet_xml, sst=()):
    """列字母 -> 表头名。指纹、小计列、源列全靠表头名认。

    列字母写死过一次，模板一改版（RFQPlan→CostSummary、入价→成本）就认错行、
    小计写错列，所以这里每次从模板表头行现读。
    """
    m = re.search(rf'<row r="{HEADER_ROW}"[^>]*>(.*?)</row>', sheet_xml, re.S)
    if not m:
        raise RuntimeError(f"模板读不到表头行（第 {HEADER_ROW} 行）")
    hdr = {}
    for c in CELL_RE.finditer(m.group(1)):
        col, attrs, inner = c.group(1), c.group(3), c.group(4) or ""
        if 't="s"' in attrs:
            v = re.search(r"<v>(\d+)</v>", inner)
            name = sst[int(v.group(1))] if v and int(v.group(1)) < len(sst) else ""
        else:
            t = (re.search(r"<is>.*?<t[^>]*>(.*?)</t>", inner, re.S)
                 or re.search(r"<v>(.*?)</v>", inner, re.S))
            name = _clean_text(t.group(1)) if t else ""
        if name:
            hdr[col] = name
    return hdr


def split_groups(hdr):
    """按空表头列把列切段 —— 模板用空列分隔报价 / 成本 / 分包各组。

    Labor / Material / Equipment 在三组里重名，只有配上组号才唯一。
    """
    if not hdr:
        return {}
    groups, g = {}, 0
    for i in range(1, max(col_index(c) for c in hdr) + 1):
        col = col_letter(i)
        if col in hdr:
            groups[col] = g
        else:
            g += 1
    return groups


def find_header_col(hdr, name):
    """表头名 -> 列字母，找不到返回 None。同名取最左。"""
    for col in sorted(hdr, key=col_index):
        if hdr[col] == name:
            return col
    return None


def classify_template_row(cells, hdr, desc=""):
    """按描述标记认样板行，公式指纹只用来分「有量明细」和「无量空壳」。

    原来纯靠公式列组合认，模板这一版行不通了：删掉 占比 列之后 L1【】和 L2《》
    的公式指纹一模一样，TOTAL 行跟它们也撞（三者都是「无键列 + 有 Amount」）。
    描述标记本来就是这几类行的语义来源，反而更稳。

    描述为空的行直接跳过 —— 模板首个数据行只有键列公式、没有描述，认成 l3
    会把它当空壳样板用，比 {…} 那种真 L3 行少了 CleanDescription 公式。
    """
    fcols = {c for c, d in cells.items() if d["f"]}
    if not fcols:
        return None
    d = (desc or "").strip()
    if not d:
        return None
    if d.startswith("【TOTAL】"):
        return "total"
    kind = layout.row_kind(d)
    if kind != "item":
        return kind
    names = {hdr.get(c, "") for c in fcols}
    return "item" if names & set(layout.RATE_COLS) else "l3"


def templatize(formula, src_row, total_row):
    """把公式里的行号换成占位符。

    只替换紧跟列字母的、值等于样板行号的数字：$E$4 的 4、跨度 5000、75% 都不动。
    指向 TOTAL 行的绝对引用（$U$45）单独换成 TOTAL 哨兵。

    占位符用哨兵字符串而不是 str.format —— 公式里有 FIND("{",…) 这种字面花括号，
    format 会当成字段名炸掉。
    """
    if formula is None:
        return None
    f = re.sub(rf"(\$?[A-Z]{{1,3}}\$?){src_row}(?![0-9])", r"\g<1>" + ROW_MARK, formula)
    if total_row:
        f = re.sub(rf"(\$?[A-Z]{{1,3}}\$?){total_row}(?![0-9])", r"\g<1>" + TOTAL_MARK, f)
    return f


def fill_marks(formula, r, total_row):
    return formula.replace(ROW_MARK, str(r)).replace(TOTAL_MARK, str(total_row))


# ── 行 XML 生成 ───────────────────────────────────────────────────────

def esc(v):
    return escape(CTRL.sub("", str(v)))


def cell_xml(col, r, spec, value=None, formula=None, kind=None):
    s = f' s="{spec["s"]}"' if spec and spec.get("s") else ""
    ref = f"{col}{r}"
    if formula is not None:
        fa = spec.get("f_attrs") or ""
        # shared 的宿主属性带着模板自己的 ref 范围，行数一变就对不上；
        # 展开成独立公式后这些属性没有意义，整个丢掉。array 的 ref 要留。
        if 't="shared"' in fa:
            fa = ""
        elif 'ref="' in fa:
            fa = re.sub(r'\sref="[^"]*"', f' ref="{ref}"', fa)
        cm = spec.get("cm", "")
        # 公式文本是直接从模板 XML 里取的，已经是转义态（&amp; &gt;）。再 escape
        # 一次会变成 &amp;amp;，Excel 打开即报损坏 —— 只有单元格的值需要转义。
        return f'<c r="{ref}"{s}{cm}><f{fa}>{formula}</f></c>'
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>'
    if kind == "n":
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    return (f'<c r="{ref}"{s} t="inlineStr"><is>'
            f'<t xml:space="preserve">{esc(value)}</t></is></c>')


def build_row(tpl_entry, r, tpl_total, new_total, values, outline=None):
    attrs, cells, src_row = tpl_entry
    if outline is not None:
        attrs = re.sub(r'\s*outlineLevel="\d+"', "", attrs)
        if outline:
            attrs += f' outlineLevel="{outline}"'
    parts = [f'<row r="{r}"{attrs}>']
    for col in sorted(cells, key=col_index):
        spec = cells[col]
        if col in values:
            v = values[col]
            parts.append(cell_xml(col, r, spec, v[0], kind=v[1]))
            continue
        f = templatize(spec["f"], spec.get("f_row") or src_row, tpl_total)
        if f:
            parts.append(cell_xml(col, r, spec, formula=fill_marks(f, r, new_total)))
        else:
            parts.append(cell_xml(col, r, spec))
    parts.append("</row>")
    return "".join(parts)


def build_total_row(tpl_entry, r, start, end, hdr):
    """TOTAL 行：哪些列要小计、哪些要加权，全从模板的 TOTAL 样板行推导。

    样板行里有公式的列就是要汇总的：表头以 Amount 结尾的直接 SUBTOTAL，
    其余（分包组按单价填的人材机）按工程量加权 SUMPRODUCT。
    """
    attrs, cells, _ = tpl_entry
    parts = [f'<row r="{r}"{attrs}>']
    qty_col = find_qty_col(hdr)
    desc_col = find_header_col(hdr, "Description")
    if not qty_col:
        raise RuntimeError(f"模板表头行找不到 Quantity 列，现有表头: {sorted(hdr.values())}")
    for col in sorted(cells, key=col_index):
        spec = cells[col]
        if spec["f"]:
            if hdr.get(col, "").endswith(" Amount"):
                f = f"SUBTOTAL(9,{col}{start}:{col}{end})"
            else:
                f = (f"SUMPRODUCT({col}{start}:{col}{end},"
                     f"${qty_col}${start}:${qty_col}${end})")
        else:
            f = None
        if f:
            parts.append(cell_xml(col, r, spec, formula=f))
        elif col == desc_col:
            parts.append(cell_xml(col, r, spec, "【TOTAL】"))
        else:
            parts.append(cell_xml(col, r, spec))
    parts.append("</row>")
    return "".join(parts)


def build_sheet_data(sheet_xml, rows, tpl, tpl_total_row, hdr, classified=None):
    """保留 1-4 行原样（分组标题 / 放大系数 / 表头 / 空行），第 5 行起重建。

    源列和分类列的落位都按表头名查，不写死列字母。
    """
    body = sheet_xml[sheet_xml.index("<sheetData>") + 11: sheet_xml.index("</sheetData>")]
    head = "".join(m.group(0) for m in ROW_RE.finditer(body)
                   if int(m.group(1)) <= HEADER_ROW + 1)

    src_cols = {}
    for key, name in (("no", "No."), ("desc", "Description"),
                      ("unit", "Unit"), ("qty", "Qty")):
        col = find_qty_col(hdr) if key == "qty" else find_header_col(hdr, name)
        if not col:
            raise RuntimeError(f"模板表头行找不到 {name} 列，现有表头: {sorted(hdr.values())}")
        src_cols[key] = col
    ai_cols = {name: find_header_col(hdr, name) for name in AI_HEADERS}

    total_row = DATA_START + len(rows)
    out, depth = [head], 0
    for i, src in enumerate(rows):
        r = DATA_START + i
        kind = row_kind(src["desc"])
        if kind == "l1":
            depth, outline = 0, 0
        elif kind == "l2":
            depth, outline = 1, 1
        elif kind == "l3":
            depth, outline = 2, 2
        else:
            outline = min(depth + 1, 3)

        has_qty = src["qty"] is not None and src["qty"] > 0 and bool(src["unit"])
        entry = tpl[kind] if kind in tpl else (tpl["item"] if has_qty else tpl["l3"])
        if kind == "item" and not has_qty:
            entry = tpl["l3"]

        values = {
            src_cols["no"]: (src["no"], "s"),
            src_cols["desc"]: (src["desc"], "s"),
            src_cols["unit"]: (src["unit"], "s"),
            src_cols["qty"]: (fmt_num(src["qty"]), "n"),
        }
        if classified:
            for name, val in (classified.get(src["src_row"]) or {}).items():
                col = ai_cols.get(name)
                if col and val:
                    values[col] = (val, "s")
        out.append(build_row(entry, r, tpl_total_row, total_row, values, outline))

    out.append(build_total_row(tpl["total"], total_row, DATA_START, total_row - 1, hdr))
    new_body = "".join(out)
    return (sheet_xml[:sheet_xml.index("<sheetData>") + 11] + new_body
            + sheet_xml[sheet_xml.index("</sheetData>"):]), total_row


def fmt_num(v):
    if v is None:
        return ""
    if float(v).is_integer():
        return str(int(v))
    return repr(round(float(v), 10))


# ── 其余部件调整 ──────────────────────────────────────────────────────

def set_dimension(xml, last_row):
    return re.sub(r'<dimension ref="[^"]*"/>',
                  f'<dimension ref="A1:{LAST_COL}{last_row}"/>', xml, count=1)


def clear_rows_from(xml, start, keep_blank=True):
    """清掉 start 行及之后的所有行 — UniqueShot 只留表头。

    留一个空行：table 的 ref 必须覆盖表头加至少一行数据，只剩表头的表
    Excel 判定为损坏。
    """
    body_s = xml.index("<sheetData>") + 11
    body_e = xml.index("</sheetData>")
    kept = "".join(m.group(0) for m in ROW_RE.finditer(xml[body_s:body_e])
                   if int(m.group(1)) < start)
    if keep_blank:
        kept += f'<row r="{start}"/>'
    return xml[:body_s] + kept + xml[body_e:]


def pivot_area(pt_xml):
    m = re.search(r'<location[^>]*\bref="([A-Z]+)(\d+):([A-Z]+)(\d+)"', pt_xml)
    if not m:
        return None
    return (col_index(m.group(1)), int(m.group(2)),
            col_index(m.group(3)), int(m.group(4)))


def clear_pivot_area(xml, area):
    """透视表区域内的静态单元格是模板上次保存时的渲染结果，也就是上一个项目的
    数据。refreshOnLoad 会重建，但万一自动刷新没发生，留着就是误导。"""
    if not area:
        return xml
    c1, r1, c2, r2 = area

    def row_repl(m):
        r = int(m.group(1))
        if not (r1 <= r <= r2):
            return m.group(0)

        def cell_repl(cm):
            col = col_index(cm.group(1))
            return "" if c1 <= col <= c2 else cm.group(0)

        body = re.sub(r'<c r="([A-Z]+)\d+"[^>]*(?:/>|>.*?</c>)', cell_repl,
                      m.group(3), flags=re.S)
        return f'<row r="{m.group(1)}"{m.group(2)}>{body}</row>'

    return ROW_RE.sub(row_repl, xml)


def set_defined_names(wb_xml, sheet, last_row, shot_rows):
    ref = f"'{sheet}'!$A${HEADER_ROW}:${LAST_COL}${last_row}"
    dn = re.search(r"<definedNames>.*?</definedNames>", wb_xml, re.S)
    entry = f'<definedName name="{RANGE_NAME}">{ref}</definedName>'
    if dn:
        block = re.sub(rf'<definedName name="{RANGE_NAME}"[^>]*>.*?</definedName>',
                       "", dn.group(0), flags=re.S)
        block = re.sub(r'<definedName name="_xlnm\._FilterDatabase"[^>]*>.*?</definedName>',
                       "", block, flags=re.S)
        block = block.replace("</definedNames>", entry + "</definedNames>")
        return wb_xml.replace(dn.group(0), block)
    block = f"<definedNames>{entry}</definedNames>"
    return re.sub(r"(</sheets>)", r"\1" + block, wb_xml, count=1)


def set_refresh_on_load(cache_xml):
    x = re.sub(r'\srefreshOnLoad="[01]"', "", cache_xml)
    x = re.sub(r' recordCount="[0-9]+"', "", x)
    x = x.replace("<pivotCacheDefinition ",
                  '<pivotCacheDefinition refreshOnLoad="1" recordCount="0" ', 1)
    return re.sub(r"<worksheetSource[^>]*/>",
                  f'<worksheetSource name="{RANGE_NAME}"/>', x)


def set_table_ref(table_xml, last_row):
    ref = re.search(r'ref="([A-Z]+)\d+:([A-Z]+)\d+"', table_xml)
    if not ref:
        return table_xml
    new = f'{ref.group(1)}{HEADER_ROW + 1}:{ref.group(2)}{last_row}'
    return re.sub(r'ref="[A-Z]+\d+:[A-Z]+\d+"', f'ref="{new}"', table_xml)


def clear_tab_selected(xml):
    return re.sub(r'\stabSelected="1"', "", xml, count=1)


# ── 主流程 ───────────────────────────────────────────────────────────

NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def sheet_map(zf):
    wb = zf.read("xl/workbook.xml").decode("utf8")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf8")
    target = {m.group(1): m.group(2) for m in
              re.finditer(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels)}
    target.update({m.group(2): m.group(1) for m in
                   re.finditer(r'Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
    out = {}
    for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="([^"]+)"', wb):
        t = target.get(m.group(2), "")
        out[m.group(1)] = "xl/" + t.lstrip("/").replace("xl/", "", 1)
    return out


def set_inline_cell(sheet_xml, ref, text):
    """把某个单元格改写成 inlineStr。

    表头存在共享串池里，直接改池子会波及所有引用同一个串的单元格；
    改成内联串只影响这一格。
    """
    m = re.search(rf'<c r="{ref}"([^>]*?)(?:/>|>(.*?)</c>)', sheet_xml, re.S)
    if not m:
        return sheet_xml
    attrs = re.sub(r'\st="\w+"', "", m.group(1))
    cell = (f'<c r="{ref}"{attrs} t="inlineStr">'
            f'<is><t xml:space="preserve">{escape(text)}</t></is></c>')
    return sheet_xml[:m.start()] + cell + sheet_xml[m.end():]


def rename_subcontractor_headers(sheet_xml, hdr, name):
    """分包组的表头也带分包商名（模板占位 XXX），换项目要跟着改 ——
    只改分组标题行的话，交付出去表头还写着 XXX。"""
    for col, old in hdr.items():
        if old.endswith((" Rate", " Amount")) and not old.startswith(("报价", "成本", "AI")):
            suffix = old.rsplit(" ", 1)[-1]
            sheet_xml = set_inline_cell(sheet_xml, f"{col}{HEADER_ROW}", f"{name}\n{suffix}")
    return sheet_xml


def find_subcontractor_cell(hdr):
    """分包组的分组标题格：表头形如 '{名} Rate' 且不属于报价/成本/AI 的那一列，第 1 行。"""
    for col in sorted(hdr, key=col_index):
        name = hdr[col]
        if name.endswith(" Rate") and not name.startswith(("报价", "成本", "AI")):
            return f"{col}1"
    return None


def load_classification(path):
    """分类结果 -> ({源行号: {表头名: 值}}, {源行号: 描述开头})。

    按源清单行号对回来，另存描述开头做断言 —— 错一行就整批错位。
    """
    data = json.loads(Path(path).read_text(encoding="utf8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    values, heads = {}, {}
    for it in items:
        r = it.get("src_row")
        if r is None:
            continue
        r = int(r)
        values[r] = {k: str(v).strip() for k, v in it.items()
                     if k in AI_HEADERS and v not in (None, "")}
        heads[r] = str(it.get("desc_head") or "")
    return values, heads


def check_anchor(rows, heads):
    """描述开头对不上就是错位，宁可停下也不要写错一整批。"""
    bad = []
    for src in rows:
        h = heads.get(src["src_row"])
        if h and not src["desc"].startswith(h[:24]):
            bad.append(f"  源行 {src['src_row']}: 分类结果记的是 {h[:28]!r}，"
                       f"清单里是 {src['desc'][:28]!r}")
    return bad


def build(source, output, template, src_sheet=None, cols=None, header_row=1,
          subcontractor=None, classification=None):
    template, output = Path(template).resolve(), Path(output).resolve()
    rows = load_source(source, src_sheet, cols, header_row)
    print(f"源清单: {len(rows)} 行")

    classified = None
    if classification:
        classified, heads = load_classification(classification)
        bad = check_anchor(rows, heads)
        if bad:
            raise SystemExit("分类结果与源清单对不上（错位）：\n" + "\n".join(bad[:10])
                             + f"\n共 {len(bad)} 行对不上，先查分类结果的 src_row 是不是按同一份清单生成的。")
        hit = sum(1 for s in rows if classified.get(s["src_row"]))
        print(f"分类结果: {len(classified)} 条，命中本次 {hit} 行")

    shutil.copy(template, output)
    zf = zipfile.ZipFile(output)
    parts = {n: zf.read(n) for n in zf.namelist()}
    zf.close()

    paths = sheet_map(zipfile.ZipFile(template))
    main_path = paths[TEMPLATE_SHEET]
    sheet_xml = parts[main_path].decode("utf8")

    tpl, tpl_total, hdr = extract_templates(sheet_xml, read_shared_strings(parts))
    missing = [k for k in ("l1", "l2", "l3", "item", "total") if k not in tpl]
    if missing:
        raise RuntimeError(f"模板缺样板行: {missing}（各类行至少要留一行）")
    print(f"样板行: " + ", ".join(f"{k}=R{v[2]}" for k, v in tpl.items()))

    sheet_xml, total_row = build_sheet_data(sheet_xml, rows, tpl, tpl_total, hdr, classified)
    sheet_xml = set_dimension(sheet_xml, total_row)
    if subcontractor:
        cell = find_subcontractor_cell(hdr)
        if not cell:
            raise RuntimeError("模板表头行找不到分包组的 Rate 列，无法定位分包商名格")
        sheet_xml = rename_group_label(sheet_xml, cell, subcontractor)
        sheet_xml = rename_subcontractor_headers(sheet_xml, hdr, subcontractor)
        print(f"分包商: {subcontractor}（分组标题 {cell} 和表头一并改写）")
    parts[main_path] = sheet_xml.encode("utf8")
    print(f"{TEMPLATE_SHEET}: 数据行 {DATA_START}-{total_row - 1}，TOTAL 行 {total_row}")

    shot_path = paths[SHOT_SHEET]
    shot_xml = clear_rows_from(
        clear_tab_selected(parts[shot_path].decode("utf8")), HEADER_ROW + 2)
    shot_xml = re.sub(r'<dimension ref="([A-Z]+)\d+:([A-Z]+)\d+"/>',
                      rf'<dimension ref="\g<1>1:\g<2>{HEADER_ROW + 2}"/>', shot_xml, count=1)
    parts[shot_path] = shot_xml.encode("utf8")
    for n in list(parts):
        if re.match(r"xl/tables/table\d+\.xml$", n):
            parts[n] = set_table_ref(parts[n].decode("utf8"), HEADER_ROW + 2).encode("utf8")
    print(f"{SHOT_SHEET}: 数据行已清空，只留表头")

    for name, path in paths.items():
        if name in (TEMPLATE_SHEET, SHOT_SHEET):
            continue
        xml = clear_tab_selected(parts[path].decode("utf8"))
        rel = f"{path.rsplit('/', 1)[0]}/_rels/{path.rsplit('/', 1)[1]}.rels"
        pt = None
        if rel in parts:
            m = re.search(r'Target="([^"]*pivotTable\d+\.xml)"', parts[rel].decode("utf8"))
            if m:
                pt = "xl/" + m.group(1).lstrip("./").replace("../", "")
        if pt and pt in parts:
            xml = clear_pivot_area(xml, pivot_area(parts[pt].decode("utf8")))
            print(f"{name}: 透视表区域已清空，打开时自动刷新")
        parts[path] = xml.encode("utf8")

    for n in list(parts):
        if re.match(r"xl/pivotCache/pivotCacheDefinition\d+\.xml$", n):
            parts[n] = set_refresh_on_load(parts[n].decode("utf8")).encode("utf8")
        if re.match(r"xl/pivotCache/pivotCacheRecords\d+\.xml$", n):
            parts[n] = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<pivotCacheRecords xmlns="http://schemas.openxmlformats.org/'
                f'spreadsheetml/2006/main" xmlns:r="{NS_REL}" count="0"/>'
            ).encode("utf8")

    parts["xl/workbook.xml"] = set_defined_names(
        parts["xl/workbook.xml"].decode("utf8"), TEMPLATE_SHEET, total_row,
        HEADER_ROW + 1).encode("utf8")
    # calcChain 记的是模板那套单元格的计算顺序，行数一变就对不上，直接丢掉让
    # Excel 重建。三处要同时清：部件本身、Content_Types 的 Override、
    # workbook.xml.rels 里的 Relationship —— 漏掉 rels 会留下断链，Excel 判定
    # 文件损坏且不给具体原因。
    if parts.pop("xl/calcChain.xml", None) is not None:
        parts["[Content_Types].xml"] = re.sub(
            r'<Override PartName="/xl/calcChain\.xml"[^>]*/>', "",
            parts["[Content_Types].xml"].decode("utf8")).encode("utf8")
        parts["xl/_rels/workbook.xml.rels"] = re.sub(
            r'<Relationship[^>]*Target="[^"]*calcChain\.xml"[^>]*/>', "",
            parts["xl/_rels/workbook.xml.rels"].decode("utf8")).encode("utf8")

    tmp = output.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for n, data in parts.items():
            out.writestr(n, data)
    tmp.replace(output)
    print(f"Done -> {output.name}（打开时透视表自动刷新）")
    return output


def rename_group_label(xml, ref, label):
    return re.sub(rf'<c r="{ref}"([^>]*?)(?:/>|>.*?</c>)',
                  lambda m: f'<c r="{ref}"{strip_type(m.group(1))} t="inlineStr">'
                            f'<is><t>{esc(label)}</t></is></c>', xml, count=1, flags=re.S)


def strip_type(attrs):
    return re.sub(r'\st="[^"]*"', "", attrs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--template", default=str(
        Path(__file__).resolve().parent.parent / "references" / "pivot_template.xlsx"))
    ap.add_argument("--sheet")
    ap.add_argument("--header-row", type=int, default=1)
    ap.add_argument("--col-no")
    ap.add_argument("--col-desc")
    ap.add_argument("--col-unit")
    ap.add_argument("--col-qty")
    ap.add_argument("--subcontractor")
    ap.add_argument("--classification",
                    help="pk-boq-classify 产出的 classification.json，装配时把五个分类列一并写入")
    a = ap.parse_args()

    cols = None
    if a.col_desc or a.col_unit or a.col_qty:
        cols = {"no": a.col_no or "A", "desc": a.col_desc,
                "unit": a.col_unit, "qty": a.col_qty}
        if not all(cols.values()):
            ap.error("--col-desc/--col-unit/--col-qty 要一起给")
    build(a.source, a.output, a.template, a.sheet, cols, a.header_row,
          a.subcontractor, a.classification)
