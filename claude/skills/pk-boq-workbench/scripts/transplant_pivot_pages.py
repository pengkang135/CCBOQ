#!/usr/bin/env python3
"""把模板的三张透视表页 + UniqueShot 整包搬进一份已有内容的清单。

**只复制，不理解**：字段索引、值字段、formats 全部原样，布局到 Excel 里手工调。
需要的话透视表 refreshOnLoad="1"，用户打开时 Excel 自己刷新出数。

不用 setup_pivots.install()。它拿 ElementTree 解析再序列化 workbook.xml 和
styles.xml，而 ET 只认注册过的命名空间，mc / x15 / x14ac / xcalcf 全被改写成
ns1..ns8，根元素上的 mc:Ignorable 属性直接丢失。文档里还留着 x14ac 等扩展
元素，却没了"这些可忽略"的声明，Excel 就拒绝打开 —— 2026-08-27 连续三次
交付失败都是这一个原因。ET 写的 ET 自己读得回来，所以 XML 良构性检查、
LibreOffice、openpyxl 全都放行，只有 Excel 严格。

底层的字符串拼接和样式合并在 xlsx_parts.py，跟 insert_workbench_cols.py 共用。

`UniqueShot` 必须一起搬。UniqueBQ 页的 VLOOKUP 全指着它，漏掉就是整页
引用不存在工作表的公式，Excel 打开虽不至于拒绝，但一定弹"发现不可读取的内容"。
它自带 tableParts，table 部件要跟着走。

pivotCacheDefinition 的 worksheetSource 不能搬成 `name` 引用 definedName。模板里
写的是 `<worksheetSource name="分类定义区"/>`，靠 definedName 间接定位数据区。
Excel 对 name 引用解析不稳定 —— definedName 一旦缺失、范围错、或指向不存在的
sheet，Excel 打开时**静默删掉三张透视表 + workbook.xml 的 pivotCaches 属性**，
不报错不弹窗；LibreOffice 反而能开（它容错 name 引用）。修法是改成 ref+sheet
显式引用：`<worksheetSource ref="A4:AU1497" sheet="MergeBQ"/>`，这是 Excel 生成
worksheetSource 的标准写法、一定能解析。本脚本搬 cdef 时要把 name 引用换掉，
ref 用数据区 A1 范围、sheet 用数据 sheet 名（`rng` / `sheet_name` 已算好，但
`rng` 是 `Sheet!$A$3:$AU$N` 的 definedName 格式，要拆掉 sheet 前缀和 `$`）。

用法:
    python transplant_pivot_pages.py 工作台.xlsx -o 工作台_带透视表.xlsx
    python transplant_pivot_pages.py in.xlsx -o out.xlsx --sheet CombineBQ
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xlsx_parts as xp

TPL_DEFAULT = Path(__file__).resolve().parent.parent / "references/pivot_template.xlsx"
PAGES = ["CostSummary", "MainQty", "UniqueBQ"]
PLAIN = ["UniqueShot"]                  # 无透视表，但 UniqueBQ 的 VLOOKUP 靠它


def apply(parts, tpl, xf_map, dxf_off, sheet=None, header_row=None,
          defined_name="分类定义区", pages=None, log=print):
    """在 parts 上原地搬页。样式由调用方先 merge 好并传 xf_map / dxf_off 进来。

    样式合并不放这里：串在 insert 后面时两边各合一次，模板样式在 styles.xml 里
    存两份、cellXfs 白涨一倍。build_bench.py 合一次，两步共用同一份映射。
    """
    pages = list(pages or PAGES)
    sheet_name, sheet_path = xp.resolve_sheet(parts, sheet)
    sx = parts[sheet_path].decode("utf8")
    sst = xp.read_sst(parts)
    hrow = header_row or xp.find_header_row(sx, sst)
    if not hrow:
        raise SystemExit(f"{sheet_name} 前 20 行找不到表头，用 --header-row 指定")
    rng = xp.data_range(sx, sheet_name, hrow, sst)
    log(f"数据源: {rng}")

    exist = set(xp.sheet_paths(parts))
    dup = [p for p in pages + PLAIN if p in exist]
    if dup:
        raise SystemExit(f"目标簿已有同名页 {dup}，先删掉或改名再搬")

    tsheet = xp.sheet_paths(tpl)
    for p in pages + PLAIN:
        if p not in tsheet:
            raise SystemExit(f"模板没有页 {p!r}，现有: {sorted(tsheet)}")

    # sharedStrings：透视表页的 t="s" 引用模板索引，目标 sharedStrings 是原清单
    # 重建版，索引错位。把模板 <si> 追加到目标末尾，透视表页索引整体偏移过去。
    pivot_ts = 0
    for page in pages + PLAIN:
        pivot_ts += len(re.findall(r'<c\b[^>]*\bt="s"[^>]*>\s*<v>\d+</v>',
                                   tpl[tsheet[page]].decode("utf-8")))
    tpl_sst_raw = tpl["xl/sharedStrings.xml"].decode("utf8")
    tpl_n = len(re.findall(r"<si\b", re.search(r"<sst\b[^>]*>(.*)</sst>",
                                               tpl_sst_raw, re.S).group(1)))
    sst_xml, sst_off = xp.merge_shared_strings(
        parts["xl/sharedStrings.xml"].decode("utf8"), tpl_sst_raw, pivot_ts)
    parts["xl/sharedStrings.xml"] = sst_xml.encode("utf8")
    log(f"sharedStrings: 追加模板 {tpl_n} 条，透视表页 t=\"s\" 偏移 +{sst_off}")

    rid = max(int(x) for x in re.findall(
        r'Id="rId(\d+)"', parts["xl/_rels/workbook.xml.rels"].decode("utf8")))
    sid = max(int(x) for x in re.findall(r'<sheet [^>]*sheetId="(\d+)"',
                                         parts["xl/workbook.xml"].decode("utf8")))
    new_rels, new_sheets, new_ct = [], [], []

    rid += 1
    cache_rid = f"rId{rid}"
    cdef = tpl["xl/pivotCache/pivotCacheDefinition1.xml"].decode("utf8")
    cdef = re.sub(r'\srefreshOnLoad="[01]"', "", cdef)
    cdef = cdef.replace("<pivotCacheDefinition ",
                        '<pivotCacheDefinition refreshOnLoad="1" ', 1)
    parts["xl/pivotCache/pivotCacheDefinitionP1.xml"] = cdef.encode("utf8")
    parts["xl/pivotCache/pivotCacheRecordsP1.xml"] = \
        tpl["xl/pivotCache/pivotCacheRecords1.xml"]
    parts["xl/pivotCache/_rels/pivotCacheDefinitionP1.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{xp.NS_REL}/pivotCacheRecords"'
        f' Target="pivotCacheRecordsP1.xml"/></Relationships>').encode("utf8")
    new_rels.append(f'<Relationship Id="{cache_rid}" Type="{xp.NS_REL}/pivotCacheDefinition"'
                    f' Target="pivotCache/pivotCacheDefinitionP1.xml"/>')
    new_ct += [f'<Override PartName="/xl/pivotCache/pivotCacheDefinitionP1.xml"'
               f' ContentType="{xp.CT}.pivotCacheDefinition+xml"/>',
               f'<Override PartName="/xl/pivotCache/pivotCacheRecordsP1.xml"'
               f' ContentType="{xp.CT}.pivotCacheRecords+xml"/>']

    moved = []
    for i, page in enumerate(pages, 1):
        s = tsheet[page]
        sxp = xp.strip_tab_selected(
            xp.shift_sst_index(xp.remap_s(tpl[s].decode("utf8"), xf_map), sst_off))
        parts[f"xl/worksheets/sheetP{i}.xml"] = sxp.encode("utf8")
        moved.append((f"xl/worksheets/sheetP{i}.xml", page))

        pt_rel = tpl[f"xl/worksheets/_rels/{Path(s).name}.rels"].decode("utf8")
        pt_src = "xl/" + re.search(r'Target="[./]*([^"]*pivotTable[^"]*)"',
                                   pt_rel).group(1)
        px = tpl[pt_src].decode("utf8")
        px = re.sub(r'dxfId="(\d+)"',
                    lambda m: f'dxfId="{int(m.group(1)) + dxf_off}"', px)
        px = re.sub(r'cacheId="\d+"', 'cacheId="1"', px)
        parts[f"xl/pivotTables/pivotTableP{i}.xml"] = px.encode("utf8")
        parts[f"xl/pivotTables/_rels/pivotTableP{i}.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{xp.NS_REL}/pivotCacheDefinition"'
            f' Target="../pivotCache/pivotCacheDefinitionP1.xml"/></Relationships>'
        ).encode("utf8")
        parts[f"xl/worksheets/_rels/sheetP{i}.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{xp.NS_REL}/pivotTable"'
            f' Target="../pivotTables/pivotTableP{i}.xml"/></Relationships>'
        ).encode("utf8")

        rid += 1
        sid += 1
        new_rels.append(f'<Relationship Id="rId{rid}" Type="{xp.NS_REL}/worksheet"'
                        f' Target="worksheets/sheetP{i}.xml"/>')
        new_sheets.append(f'<sheet name="{page}" sheetId="{sid}" r:id="rId{rid}"/>')
        new_ct += [f'<Override PartName="/xl/worksheets/sheetP{i}.xml"'
                   f' ContentType="{xp.CT}.worksheet+xml"/>',
                   f'<Override PartName="/xl/pivotTables/pivotTableP{i}.xml"'
                   f' ContentType="{xp.CT}.pivotTable+xml"/>']
        log(f"  {page} → sheetP{i}.xml + pivotTableP{i}.xml  (rId{rid}, sheetId={sid})")

    for j, page in enumerate(PLAIN, len(pages) + 1):
        s = tsheet[page]
        sxp = xp.strip_tab_selected(
            xp.shift_sst_index(xp.remap_s(tpl[s].decode("utf8"), xf_map), sst_off))
        parts[f"xl/worksheets/sheetP{j}.xml"] = sxp.encode("utf8")
        moved.append((f"xl/worksheets/sheetP{j}.xml", page))

        # 页里的 tableParts 挂着 table 部件，rels 和 Content_Types 都得跟着搬
        rp = f"xl/worksheets/_rels/{Path(s).name}.rels"
        sub, tn = [], 0
        for m in re.finditer(r'<Relationship[^>]*?Id="([^"]+)"[^>]*?'
                             r'Target="([^"]*tables/table\d+\.xml)"',
                             tpl[rp].decode("utf8") if rp in tpl else ""):
            tn += 1
            tp = f"xl/tables/tableP{tn}.xml"
            parts[tp] = tpl["xl/" + m.group(2).lstrip("./")]
            sub.append(f'<Relationship Id="{m.group(1)}" Type="{xp.NS_REL}/table"'
                       f' Target="../tables/tableP{tn}.xml"/>')
            new_ct.append(f'<Override PartName="/{tp}"'
                          f' ContentType="{xp.CT}.table+xml"/>')
        parts[f"xl/worksheets/_rels/sheetP{j}.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">' + "".join(sub) + "</Relationships>").encode("utf8")

        rid += 1
        sid += 1
        new_rels.append(f'<Relationship Id="rId{rid}" Type="{xp.NS_REL}/worksheet"'
                        f' Target="worksheets/sheetP{j}.xml"/>')
        new_sheets.append(f'<sheet name="{page}" sheetId="{sid}" r:id="rId{rid}"/>')
        new_ct.append(f'<Override PartName="/xl/worksheets/sheetP{j}.xml"'
                      f' ContentType="{xp.CT}.worksheet+xml"/>')
        log(f"  {page} → sheetP{j}.xml + {tn} 个 table  (rId{rid}, sheetId={sid})")

    r = parts["xl/_rels/workbook.xml.rels"].decode("utf8")
    parts["xl/_rels/workbook.xml.rels"] = r.replace(
        "</Relationships>", "".join(new_rels) + "</Relationships>").encode("utf8")
    c = parts["[Content_Types].xml"].decode("utf8")
    parts["[Content_Types].xml"] = c.replace(
        "</Types>", "".join(new_ct) + "</Types>").encode("utf8")

    # workbook.xml：只在闭合标签前插字符串，根元素与 mc:Ignorable 一字不动
    w = parts["xl/workbook.xml"].decode("utf8")
    w = w.replace("</sheets>", "".join(new_sheets) + "</sheets>", 1)
    pc = f'<pivotCaches><pivotCache cacheId="1" r:id="{cache_rid}"/></pivotCaches>'
    m = re.search(r"<calcPr\b[^>]*/>", w)          # CT_Workbook: calcPr 在 pivotCaches 之前
    w = w[:m.end()] + pc + w[m.end():] if m else \
        w.replace("</definedNames>", "</definedNames>" + pc, 1)
    w = xp.set_defined_name(w, defined_name, rng)
    parts["xl/workbook.xml"] = w.encode("utf8")
    log(f"  workbook: +{len(new_sheets)} sheets, pivotCaches({cache_rid}), "
          f"{defined_name} → {rng}")

    known = xp.known_names(parts)
    log(f"  可解析表名 {len(known)} 个，逐页检查公式引用:")
    tot = 0
    for part, page in moved:
        fixed, n = xp.strip_dead_formulas(parts[part].decode("utf8"), known, page)
        parts[part] = fixed.encode("utf8")
        tot += n
        log(f"    {page:14s} 公式 {len(re.findall(r'<f[ >]', fixed)):5d} 条，"
              f"断链 {n} 条已转静态值")
    log(f"  合计清理 {tot} 条死公式（Excel 修复提示的来源）")

    return {"sheet": sheet_name, "header_row": hrow, "range": rng}


def main():
    ap = argparse.ArgumentParser(description="把模板透视表页整包搬进目标簿")
    ap.add_argument("source")
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--template", default=str(TPL_DEFAULT))
    ap.add_argument("--sheet", help="数据源 sheet 名，默认自动认含 Description 的那张")
    ap.add_argument("--header-row", type=int, help="表头行号，默认自动探测")
    ap.add_argument("--defined-name", default="分类定义区")
    ap.add_argument("--pages", default=",".join(PAGES))
    a = ap.parse_args()

    tplp = Path(a.template)
    if not tplp.exists():
        raise SystemExit(f"模板不存在: {tplp}")
    with zipfile.ZipFile(tplp) as z:
        tpl = {n: z.read(n) for n in z.namelist()}
    with zipfile.ZipFile(a.source) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    print(f"模板: {tplp.name}")

    from insert_workbench_cols import merge_template_styles, write_parts
    xf_map, dxf_off = merge_template_styles(parts, tpl)
    apply(parts, tpl, xf_map, dxf_off, a.sheet, a.header_row, a.defined_name,
          [p.strip() for p in a.pages.split(",") if p.strip()])
    xp.drop_calc_chain(parts)
    write_parts(parts, a.output)
    print(f"完成 → {a.output}")


if __name__ == "__main__":
    main()
