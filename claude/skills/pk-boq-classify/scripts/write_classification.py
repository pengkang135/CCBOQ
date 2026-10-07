#!/usr/bin/env python3
"""把分类五列插进清单 Excel，写回分类值 —— 分类的收尾落地步骤。

zip/XML 层手术，只重写目标 sheet，其余部件字节级复制：
- 清单最右侧隔一空列插入 Discipline / SortKey / Category / Subcategory / Element 五列
- 分类值来自 classification.json（src_row 直接等于 Excel 行号）
- 表头样式 / 数据样式从源清单现有表头、数据格动态取，不写死 s 值
- OOB / NA 条目在 Discipline 列写标记（避免被误认为漏分类）
- 输出新文件，源清单不修改

不能用 openpyxl 往返写 —— 会丢 drawing 和 media 部件（图片、图表全没）；
也不用 ElementTree 序列化已有部件 —— 会改写 mc/x15/x14ac 命名空间、丢 mc:Ignorable，
Excel 拒开。只做字符串拼接，在闭合标签前插内容。

用法:
    python write_classification.py <清单.xlsx> -c classification.json \
        [--sheet 合并报表] [--header-row 3] [-o 清单_分类.xlsx]

    --oob / --na 接 out_of_book.json / not_applicable.json（可选）；
    classification.json 里若带 out_of_book / not_applicable 键也会一并读。
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string

AI_HEADERS = ("Discipline", "SortKey", "Category", "Subcategory", "Element")
SEP_WIDTH = 3.0
AI_WIDTHS = (20.0, 11.0, 22.0, 22.0, 22.0)


def _norm(v) -> str:
    return " ".join(str(v).replace("\n", " ").split()) if v is not None else ""


def find_sheet_xml(src: Path, sheet_name: str) -> str:
    """sheet 名 -> xl/worksheets/sheetN.xml（经 workbook.xml + rels 两级解析）。"""
    with zipfile.ZipFile(src) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    m = re.search(r'<sheet[^>]*name="%s"[^>]*r:id="(rId\d+)"' % re.escape(sheet_name), wb)
    if not m:
        # 没有 name 就按 sheetId=1 兜底，找第一个 sheet
        m2 = re.search(r'<sheet[^>]*r:id="(rId\d+)"', wb)
        if not m2:
            raise SystemExit(f"[abort] workbook.xml 找不到 sheet {sheet_name!r}")
        rid = m2.group(1)
    else:
        rid = m.group(1)
    m = re.search(r'<Relationship[^>]*Id="%s"[^>]*Target="([^"]+)"' % rid, rels)
    if not m:
        raise SystemExit(f"[abort] workbook.xml.rels 找不到 {rid}")
    target = m.group(1).lstrip("/")
    return target if target.startswith("xl/") else "xl/" + target


def resolve_sheet_name(src: Path, cls: dict, sheet_arg: str | None) -> str:
    if sheet_arg:
        return sheet_arg
    if cls.get("sheet"):
        return cls["sheet"]
    with zipfile.ZipFile(src) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
    m = re.search(r'<sheet[^>]*name="([^"]+)"', wb)
    return m.group(1) if m else "Sheet1"


def resolve_header_row(cls: dict, header_arg: int | None) -> int:
    if header_arg:
        return header_arg
    return int(cls.get("header_row") or 3)


def load_marks(cls: dict, base_dir: Path, oob_arg, na_arg):
    """合并 OOB/NA 标记：优先 --oob/--na 文件，其次 classification.json 内嵌键。"""
    def read_list(p):
        p = Path(p)
        if not p.exists():
            return []
        return json.loads(p.read_text(encoding="utf-8"))

    oob = read_list(oob_arg) if oob_arg else cls.get("out_of_book", [])
    na = read_list(na_arg) if na_arg else cls.get("not_applicable", [])
    return oob, na


def inline_cell(letter, row, style, text):
    return (f'<c r="{letter}{row}" s="{style}" t="inlineStr">'
            f'<is><t xml:space="preserve">{escape(str(text))}</t></is></c>')


def find_desc_col(src: Path, sheet: str, header_row: int):
    """表头行里找描述列（表头名含 description），拿它的样式作分类列样式。

    分类列是文本，样式要跟描述列一致（左对齐文本），不能跟编号列走（数字右对齐）。
    """
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    ws = wb[sheet] if sheet in wb.sheetnames else wb[wb.sheetnames[0]]
    for row in ws.iter_rows(min_row=header_row, max_row=header_row):
        for cell in row:
            name = _norm(cell.value)
            if "description" in name.lower():
                wb.close()
                return cell.column
        break
    wb.close()
    return None


def main():
    ap = argparse.ArgumentParser(description="把分类五列插进清单 Excel 并写值")
    ap.add_argument("source", help="清单 xlsx（原清单或工作台）")
    ap.add_argument("-c", "--classification", required=True, help="classification.json")
    ap.add_argument("--sheet")
    ap.add_argument("--header-row", type=int)
    ap.add_argument("--oob", help="out_of_book.json（可选）")
    ap.add_argument("--na", help="not_applicable.json（可选）")
    ap.add_argument("-o", "--out", help="输出 xlsx（默认 <源名>_分类.xlsx）")
    a = ap.parse_args()

    src = Path(a.source)
    cls = json.loads(Path(a.classification).read_text(encoding="utf-8"))
    items = cls.get("items", [])
    if not items:
        raise SystemExit("[abort] classification.json 的 items 为空，分类没跑完")
    if cls.get("pending"):
        raise SystemExit(
            f"[abort] pending 还有 {len(cls['pending'])} 条，LLM 阶段没跑完，先清空再写回")

    sheet = resolve_sheet_name(src, cls, a.sheet)
    header_row = resolve_header_row(cls, a.header_row)

    # 分类值 + 标记
    seen = {}
    values = {}
    for it in items:
        if it["src_row"] in seen:
            raise SystemExit(f"[abort] 重复 src_row {it['src_row']}")
        seen[it["src_row"]] = it["desc_head"]
        values[it["src_row"]] = [it.get(c, "") for c in AI_HEADERS]
    oob, na = load_marks(cls, src.parent, a.oob, a.na)
    oob_rows = {r["src_row"] for r in oob}
    for r in oob + na:
        if r["src_row"] in values:
            raise SystemExit(f"[abort] oob/na 与 items 重叠 src_row {r['src_row']}")
        tag = "OUT-OF-BOOK" if r["src_row"] in oob_rows else "NOT-APPLICABLE"
        values[r["src_row"]] = [tag, "", "", "", ""]
    expect = set(values)
    print(f"[write] items {len(items)} | OOB {len(oob)} | NA {len(na)} "
          f"| 期望写入行 {len(expect)}", file=sys.stderr)

    sheet_xml = find_sheet_xml(src, sheet)
    with zipfile.ZipFile(src) as z:
        xml = z.read(sheet_xml).decode("utf-8")

    # dimension 右列 -> 新右列
    m = re.search(r'<dimension[^>]*ref="([A-Z]+)\d+:([A-Z]+)(\d+)"', xml)
    if not m:
        raise SystemExit("[abort] 读不到 dimension ref")
    left_letter, right_letter, bottom_row = m.group(1), m.group(2), m.group(3)
    last_col = column_index_from_string(right_letter)
    new_last_col = last_col + 6
    new_right = get_column_letter(new_last_col)
    xml, n_dim = re.subn(
        r'<dimension[^>]*ref="[^"]*"',
        f'<dimension ref="{left_letter}1:{new_right}{bottom_row}"', xml)
    if n_dim != 1:
        raise SystemExit(f"[abort] dimension 替换失败 (n={n_dim})")

    # 表头行：取 desc 列表头格的 s 作分类列表头样式
    hm = re.search(r'<row r="%d"[^>]*>(.*?)</row>' % header_row, xml, re.S)
    if not hm:
        raise SystemExit(f"[abort] 表头行 {header_row} 不存在")
    header_body = hm.group(1)

    # 描述列样式：优先按表头名含 description 定位，退化到第一个文本表头格
    desc_col = find_desc_col(src, sheet, header_row)
    if desc_col is None:
        for cm in re.finditer(r'<c r="([A-Z]+)%d"[^>]*t="s"' % header_row, header_body):
            desc_col = column_index_from_string(cm.group(1))
            break
    if desc_col is None:
        raise SystemExit(f"[abort] 表头行 {header_row} 无文本表头格，无法取样式")

    s_header = "0"
    m = re.search(r'<c r="%s%d"[^>]*s="(\d+)"' % (get_column_letter(desc_col), header_row),
                  header_body)
    if m:
        s_header = m.group(1)
    # 空分隔样式：表头里第一个无 t、无 v、带 s 的空格；找不到用 "0"
    s_sep = "0"
    for cm in re.finditer(r'<c r="([A-Z]+)%d"\s+s="(\d+)"\s*/>' % header_row, header_body):
        s_sep = cm.group(2)
        break
    # 数据样式：desc 列第一个数据格的 s
    s_data = "0"
    first_row = min(expect)
    m = re.search(r'<row r="%d"[^>]*>.*?<c r="%s%d"[^>]*s="(\d+)"'
                  % (first_row, get_column_letter(desc_col), first_row), xml, re.S)
    if m:
        s_data = m.group(1)

    # 追加 cols
    col_entries = [f'<col min="{last_col+1}" max="{last_col+1}" width="{SEP_WIDTH}" '
                   f'customWidth="1"/>']
    for i, w in enumerate(AI_WIDTHS, start=1):
        c = last_col + 1 + i
        col_entries.append(f'<col min="{c}" max="{c}" width="{w}" customWidth="1"/>')
    xml, n_cols = re.subn(r'(</cols>)', "".join(col_entries) + r"\1", xml)
    if n_cols != 1:
        raise SystemExit(f"[abort] cols 追加失败 (n={n_cols})")

    def fix_spans(opentag):
        return re.sub(r'spans="(\d+):(\d+)"',
                      lambda m: f'spans="{m.group(1)}:{max(int(m.group(2)), new_last_col)}"',
                      opentag)

    # 表头 cells
    sep_cell = f'<c r="{get_column_letter(last_col+1)}{header_row}" s="{s_sep}"/>'
    header_cells = sep_cell + "".join(
        inline_cell(get_column_letter(last_col + 1 + i), header_row, s_header, h)
        for i, h in enumerate(AI_HEADERS, start=1))

    written = set()

    def row_repl(m):
        r = int(m.group(2))
        is_hdr = (r == header_row)
        has_data = (r in values)
        if not is_hdr and not has_data:
            return m.group(0)
        cells = header_cells if is_hdr else (
            f'<c r="{get_column_letter(last_col+1)}{r}" s="{s_sep}"/>'
            + "".join(inline_cell(get_column_letter(last_col + 1 + i), r, s_data, v)
                      for i, v in enumerate(values[r], start=1)))
        if has_data:
            written.add(r)
        return fix_spans(m.group(1)) + m.group(3) + cells + m.group(4)

    xml, _ = re.subn(r'(<row r="(\d+)"[^>]*>)(.*?)(</row>)', row_repl, xml, flags=re.S)

    missed = expect - written
    if missed:
        raise SystemExit(f"[abort] 未命中 {len(missed)} 行: {sorted(missed)[:20]}")

    # 写新文件，其余部件字节级复制
    out = Path(a.out) if a.out else src.with_name(src.stem + "_分类.xlsx")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = xml if item.filename == sheet_xml else zin.read(item.filename)
            zout.writestr(item, data)

    print(f"[write] 命中写入 {len(written)} 行（含表头）", file=sys.stderr)
    print(f"[write] 新列布局: {left_letter}~{right_letter}(原{last_col}列) "
          f"| {get_column_letter(last_col+1)}(空) | {' | '.join(AI_HEADERS)}", file=sys.stderr)
    print(f"[write] 输出 {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
