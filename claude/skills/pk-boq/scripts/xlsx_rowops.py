"""xlsx 行级编辑 — 纯 zip/XML，不启动 Excel。

插行、改单元格值、整行填充。为的是替掉 Excel COM：COM 的 Rows().Insert() 能自动
调整公式行引用，openpyxl 的 insert_rows 不能，所以以前只能起 Excel。这里自己做
行号映射和公式引用平移，把这条依赖去掉。

用法:
    ed = SheetEditor("in.xlsx", "合并报表")
    ed.set_cell(12, 6, "m3")
    ed.fill_row(12, "FFFF00")
    ed.insert_row(after=20, values={5: "新增条目", 6: "m2", 7: 12.5}, fill="00FF00")
    ed.save("out.xlsx")

一次 save 里可以混用多次 insert_row —— 行号一律按**原表**的行号给，
内部统一算映射后再落盘，不需要调用方从后往前排。
"""
import re
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

ROW_RE = re.compile(r'<row\b([^>]*)>(.*?)</row>|<row\b([^>]*?)/>', re.S)
CELL_RE = re.compile(r'<c\b([^>]*?)(?:/>|>(.*?)</c>)', re.S)
QUOTED = re.compile(r'"[^"]*"')
# 单元格引用：$?列$?行。平移只动行号那一段。
REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")


def col_letter(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _attr_pat(name):
    # 前置边界不能省：s="..." 会匹配到 spans="1:38" 的尾部
    return rf'(?<![\w:.-]){re.escape(name)}="([^"]*)"'


def attr(attrs, name):
    m = re.search(_attr_pat(name), attrs)
    return m.group(1) if m else None


def set_attr(attrs, name, value):
    pat = _attr_pat(name)
    if re.search(pat, attrs):
        return re.sub(pat, f'{name}="{value}"', attrs)
    return f'{attrs} {name}="{value}"'


class SheetEditor:
    def __init__(self, path, sheet):
        self.src = Path(path)
        zf = zipfile.ZipFile(self.src)
        self.parts = {n: zf.read(n) for n in zf.namelist()}
        zf.close()
        self.sheet_path = self._find_sheet(sheet)
        self.sheet_name = sheet
        self.edits = {}       # {原行号: {列号: 值}}
        self.fills = {}       # {原行号: RGB}
        self.inserts = []     # [{"after": 原行号, "values": {...}, "fill": RGB}]

    # ── 定位 ────────────────────────────────────────────────────────

    def _find_sheet(self, sheet):
        wb = self.parts["xl/workbook.xml"].decode("utf8")
        rid = None
        for m in re.finditer(r"<sheet\b([^>]*)/>", wb):
            if attr(m.group(1), "name") == sheet:
                rid = attr(m.group(1), "r:id")
                break
        if not rid:
            names = re.findall(r'<sheet[^>]*name="([^"]+)"', wb)
            raise RuntimeError(f"工作簿无 sheet {sheet!r}，现有: {names}")
        rels = self.parts["xl/_rels/workbook.xml.rels"].decode("utf8")
        m = re.search(rf'<Relationship[^>]*Id="{rid}"[^>]*/>', rels)
        target = attr(m.group(0), "Target")
        if target.startswith("/"):
            return target.lstrip("/")
        return f"xl/{target}" if not target.startswith("xl/") else target

    # ── 编辑意图（只记录，save 时统一落盘）────────────────────────

    def set_cell(self, row, col, value):
        self.edits.setdefault(row, {})[col] = value

    def fill_row(self, row, rgb):
        self.fills[row] = rgb.upper().lstrip("#")

    def insert_row(self, after, values=None, fill=None):
        self.inserts.append({"after": after, "values": values or {},
                             "fill": (fill or "").upper().lstrip("#")})

    # ── 行号映射 ────────────────────────────────────────────────────

    def _row_map(self):
        """原行号 -> 新行号。插在 after 之后，所以 > after 的行整体下移。"""
        anchors = sorted(i["after"] for i in self.inserts)

        def shift(old):
            return old + sum(1 for a in anchors if a < old)
        return shift, anchors

    def _shift_formula(self, formula, shift):
        """公式里所有行引用按映射平移。

        引号外才平移 —— 公式里 "[^\\p{L}\\p{N}]+" 这种正则字面量长得像单元格引用，
        动它会把公式改坏。绝对引用（$A$15）同样要平移：它指向的那一行也下移了，
        Excel 自己插行时也是这么处理的。
        """
        out, pos = [], 0
        for q in QUOTED.finditer(formula):
            out.append(REF.sub(lambda m: self._shift_ref(m, shift), formula[pos:q.start()]))
            out.append(q.group(0))
            pos = q.end()
        out.append(REF.sub(lambda m: self._shift_ref(m, shift), formula[pos:]))
        return "".join(out)

    @staticmethod
    def _shift_ref(m, shift):
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{shift(int(m.group(4)))}"

    # ── 样式：派生带填充的 xf ───────────────────────────────────────

    def _style_deriver(self):
        """返回 (原 xf 索引, RGB) -> 新 xf 索引 的函数。

        整行上色不能直接改原 xf —— 那个 xf 被全表共享，改了会波及无关单元格。
        所以按 (原样式, 颜色) 派生新 xf：复制原 xf、只把 fillId 换掉，
        字体和边框跟着原样式走。
        """
        xml = self.parts["xl/styles.xml"].decode("utf8")
        fills_m = re.search(r"<fills\b[^>]*>(.*?)</fills>", xml, re.S)
        xfs_m = re.search(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", xml, re.S)
        if not fills_m or not xfs_m:
            raise RuntimeError("styles.xml 缺 fills 或 cellXfs")

        # 自闭合分支必须放前面：<xf\b.*?</xf> 会从第一个 <xf 一路吞到最近的 </xf>，
        # 把中间所有自闭合的 <xf/> 卷成一条，条目直接丢掉。
        fills = re.findall(r"<fill\b[^>]*/>|<fill\b[^>]*>.*?</fill>", fills_m.group(1), re.S)
        xfs = re.findall(r"<xf\b[^>]*/>|<xf\b[^>]*>.*?</xf>", xfs_m.group(1), re.S)
        fill_cache, xf_cache = {}, {}

        def fill_id(rgb):
            if rgb in fill_cache:
                return fill_cache[rgb]
            fills.append(f'<fill><patternFill patternType="solid">'
                         f'<fgColor rgb="FF{rgb}"/><bgColor indexed="64"/>'
                         f'</patternFill></fill>')
            fill_cache[rgb] = len(fills) - 1
            return fill_cache[rgb]

        def derive(base_xf, rgb):
            key = (base_xf, rgb)
            if key in xf_cache:
                return xf_cache[key]
            base = xfs[base_xf] if base_xf is not None and base_xf < len(xfs) else "<xf/>"
            body = base
            fid = fill_id(rgb)
            body = re.sub(r'\sfillId="\d+"', "", body)
            body = re.sub(r'\sapplyFill="[01]"', "", body)
            body = body.replace("<xf", f'<xf fillId="{fid}" applyFill="1"', 1)
            xfs.append(body)
            xf_cache[key] = len(xfs) - 1
            return xf_cache[key]

        def flush():
            new = xml
            new = new[:fills_m.start(1)] + "".join(fills) + new[fills_m.end(1):]
            # fills 改了长度，cellXfs 的位置要重新定位
            m2 = re.search(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", new, re.S)
            new = new[:m2.start(1)] + "".join(xfs) + new[m2.end(1):]
            new = re.sub(r'(<fills\b[^>]*?)count="\d+"', rf'\g<1>count="{len(fills)}"', new)
            new = re.sub(r'(<cellXfs\b[^>]*?)count="\d+"', rf'\g<1>count="{len(xfs)}"', new)
            self.parts["xl/styles.xml"] = new.encode("utf8")

        return derive, flush

    # ── 落盘 ────────────────────────────────────────────────────────

    def save(self, out):
        out = Path(out)
        if out.resolve() != self.src.resolve():
            shutil.copy(self.src, out)
        shift, anchors = self._row_map()
        derive, flush_styles = self._style_deriver()

        xml = self.parts[self.sheet_path].decode("utf8")
        body_m = re.search(r"<sheetData\b[^>]*>(.*?)</sheetData>", xml, re.S)
        if not body_m:
            raise RuntimeError(f"{self.sheet_path} 没有 sheetData")

        pending = {i["after"]: [] for i in self.inserts}
        for i in self.inserts:
            pending[i["after"]].append(i)

        out_rows, last_new = [], 0
        for m in ROW_RE.finditer(body_m.group(1)):
            attrs = m.group(1) if m.group(1) is not None else m.group(3)
            inner = m.group(2) or ""
            old_r = int(attr(attrs, "r"))
            new_r = shift(old_r)
            out_rows.append(self._rewrite_row(attrs, inner, old_r, new_r, shift, derive))
            last_new = max(last_new, new_r)
            for ins in pending.get(old_r, []):
                new_r += 1
                out_rows.append(self._new_row(new_r, ins, derive))
                last_new = max(last_new, new_r)

        new_body = "".join(out_rows)
        xml = xml[:body_m.start(1)] + new_body + xml[body_m.end(1):]
        xml = self._shift_sheet_ranges(xml, shift, last_new)
        self.parts[self.sheet_path] = xml.encode("utf8")

        flush_styles()
        self._shift_defined_names(shift)
        self._drop_calc_chain()

        tmp = out.with_suffix(".tmp.xlsx")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for n, data in self.parts.items():
                z.writestr(n, data)
        tmp.replace(out)
        return {"inserted": len(self.inserts), "filled": len(self.fills),
                "edited": sum(len(v) for v in self.edits.values()), "last_row": last_new}

    def _rewrite_row(self, attrs, inner, old_r, new_r, shift, derive):
        edits = self.edits.get(old_r, {})
        rgb = self.fills.get(old_r)
        attrs = set_attr(attrs, "r", new_r)
        if rgb:
            base = attr(attrs, "s")
            attrs = set_attr(attrs, "s", derive(int(base) if base else None, rgb))
            attrs = set_attr(attrs, "customFormat", "1")

        seen = set()
        cells = []
        for c in CELL_RE.finditer(inner):
            c_attrs, c_inner = c.group(1), c.group(2) or ""
            ref = attr(c_attrs, "r") or ""
            col = col_index(re.match(r"[A-Z]+", ref).group(0)) if ref else None
            c_attrs = set_attr(c_attrs, "r", f"{col_letter(col)}{new_r}") if col else c_attrs
            if rgb:
                base = attr(c_attrs, "s")
                c_attrs = set_attr(c_attrs, "s", derive(int(base) if base else None, rgb))
            if col in edits:
                cells.append(self._value_cell(c_attrs, edits[col]))
                seen.add(col)
                continue
            # 公式行引用跟着平移；纯值单元格不动
            c_inner = re.sub(
                r"(<f\b[^>]*>)(.*?)(</f>)",
                lambda fm: fm.group(1) + self._shift_formula(fm.group(2), shift) + fm.group(3),
                c_inner, flags=re.S)
            cells.append(f"<c{c_attrs}>{c_inner}</c>" if c_inner else f"<c{c_attrs}/>")

        for col, val in sorted(edits.items()):
            if col in seen:
                continue
            s = derive(None, rgb) if rgb else None
            a = f' r="{col_letter(col)}{new_r}"' + (f' s="{s}"' if s is not None else "")
            cells.append(self._value_cell(a, val))
        cells.sort(key=lambda c: col_index(re.search(r'r="([A-Z]+)', c).group(1))
                   if re.search(r'r="([A-Z]+)', c) else 0)
        return f"<row{attrs}>{''.join(cells)}</row>"

    @staticmethod
    def _value_cell(c_attrs, value):
        """写值统一用 inlineStr / n，绕开 sharedStrings 的索引重排。"""
        c_attrs = re.sub(r'\st="\w+"', "", c_attrs)
        if isinstance(value, (int, float)):
            return f'<c{c_attrs}><v>{value}</v></c>'
        return (f'<c{c_attrs} t="inlineStr"><is>'
                f'<t xml:space="preserve">{escape(str(value))}</t></is></c>')

    def _new_row(self, new_r, ins, derive):
        rgb = ins["fill"]
        attrs = f' r="{new_r}"'
        if rgb:
            attrs += f' s="{derive(None, rgb)}" customFormat="1"'
        cells = []
        for col, val in sorted(ins["values"].items()):
            a = f' r="{col_letter(col)}{new_r}"'
            if rgb:
                a += f' s="{derive(None, rgb)}"'
            cells.append(self._value_cell(a, val))
        return f"<row{attrs}>{''.join(cells)}</row>"

    def _shift_sheet_ranges(self, xml, shift, last_row):
        """dimension / 合并单元格 / 条件格式 / 数据验证 / autoFilter 的范围也要跟着走。"""
        def fix_ref(m):
            return f'{m.group(1)}"{self._shift_a1(m.group(2), shift)}"'

        for tag in ("mergeCell", "conditionalFormatting", "dataValidation", "autoFilter"):
            xml = re.sub(rf'(<{tag}\b[^>]*?(?:ref|sqref)=)"([^"]+)"', fix_ref, xml)
        m = re.search(r'<dimension ref="([A-Z]+)\d+:([A-Z]+)\d+"/>', xml)
        if m:
            xml = xml.replace(m.group(0),
                              f'<dimension ref="{m.group(1)}1:{m.group(2)}{last_row}"/>')
        return xml

    @staticmethod
    def _shift_a1(ref, shift):
        return REF.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{shift(int(m.group(4)))}",
                       ref)

    def _shift_defined_names(self, shift):
        wb = self.parts["xl/workbook.xml"].decode("utf8")
        m = re.search(r"<definedNames>(.*?)</definedNames>", wb, re.S)
        if not m:
            return

        def fix(dm):
            txt = dm.group(2)
            # 只平移指向本 sheet 的部分，别动别的表
            if self.sheet_name not in txt and f"'{self.sheet_name}'" not in txt:
                return dm.group(0)
            return f"{dm.group(1)}{self._shift_a1(txt, shift)}{dm.group(3)}"

        new = re.sub(r"(<definedName\b[^>]*>)(.*?)(</definedName>)", fix, m.group(1), flags=re.S)
        self.parts["xl/workbook.xml"] = (wb[:m.start(1)] + new + wb[m.end(1):]).encode("utf8")

    def _drop_calc_chain(self):
        """行号一变 calcChain 就对不上，必须三处同时清，只删部件会留断链。"""
        part = "xl/calcChain.xml"
        if part not in self.parts:
            return
        del self.parts[part]
        ct = self.parts["[Content_Types].xml"].decode("utf8")
        ct = re.sub(r'<Override[^>]*PartName="/xl/calcChain\.xml"[^>]*/>', "", ct)
        self.parts["[Content_Types].xml"] = ct.encode("utf8")
        rels = self.parts["xl/_rels/workbook.xml.rels"].decode("utf8")
        rels = re.sub(r'<Relationship[^>]*Target="calcChain\.xml"[^>]*/>', "", rels)
        self.parts["xl/_rels/workbook.xml.rels"] = rels.encode("utf8")
