"""在已分类的 BOQ xlsx 中安装透视表 — 纯 Python，不启动 Excel。

从 pivot_template.xlsx 搬运 4 个透视表 sheet 及其 pivotTable/pivotCache 部件，
合并样式表并重映射索引，把缓存源指向「分类定义区」，置 refreshOnLoad=1
让 Excel 打开文件时自动刷新出新数据。

用法:
    python setup_pivots.py <classified.xlsx> [--template tpl.xlsx] [--sheet 合并报表] [--output out.xlsx]

模板视为只读资产：用 Excel 打开再保存会重写 sheet XML，产出的文件 Excel 打不开。
确需调整透视表布局时，改完必须拿本脚本的产物验证一遍再投用。
"""
import argparse
import posixpath
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKGREL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"

PIVOT_SHEETS = ["UniqueBQ", "Materials", "MainQty", "RFQPlan"]
CLASS_HEADERS = [
    "BQ Code", "Dept1", "Dept2", "Dept3", "Discipline", "SortKey",
    "Category", "Subcategory", "Element", "Material", "Spec",
    "Description", "Unit", "Quantity", "Rate", "Amount",
]
RANGE_NAME = "分类定义区"
STYLE_ORDER = ["numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs",
               "cellStyles", "dxfs", "tableStyles", "extLst"]

ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_REL)


def rels_drop(xml, rid):
    return re.sub(rf'<Relationship[^>]* Id="{rid}"[^>]*/>', "", xml)


def rels_add(xml, rid, kind, target):
    item = f'<Relationship Type="{NS_REL}/{kind}" Target="{target}" Id="{rid}"/>'
    return xml.replace("</Relationships>", item + "</Relationships>")


def ct_add(xml, part, ctype):
    item = f'<Override PartName="/{part}" ContentType="{ctype}"/>'
    return xml.replace("</Types>", item + "</Types>")


def q(tag, ns=NS_MAIN):
    return f"{{{ns}}}{tag}"


def resolve_target(base_part, target):
    """rels 的 Target 可能是绝对路径（/xl/...）也可能是相对路径（../pivotTables/...）。
    Excel 重新保存过的文件用相对路径，只认绝对路径会读不到部件。"""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


# ── 目标表：定位分类列区域 ────────────────────────────────────────────

def find_class_range(zf, sheet_path):
    """扫描表头行，返回分类列的连续区域 (first_col, last_col, last_row)。

    只认表头右侧那一段连续命中：原表常有同名的 Unit / Rate / Quantity 列，
    从右往左找连续块可以避免把它们卷进来。
    """
    xml = zf.read(sheet_path).decode("utf8")
    root = ET.fromstring(xml)
    sst = load_shared_strings(zf)

    header, last_row = {}, 0
    for row in root.iter(q("row")):
        r = int(row.get("r", 0))
        last_row = max(last_row, r)
        if r != 1:
            continue
        for c in row.iter(q("c")):
            ref = c.get("r", "")
            col = col_index(re.match(r"[A-Z]+", ref).group(0))
            header[col] = cell_text(c, sst)

    hits = sorted(col for col, v in header.items() if v in CLASS_HEADERS)
    if not hits:
        raise RuntimeError("未找到分类列表头，请先跑 add_classification_columns.py")

    # 从最右一个命中往左收，遇到断裂即停 → 分类列块
    last = hits[-1]
    first = last
    while first - 1 in hits:
        first -= 1
    return first, last, last_row


def cell_text(c, sst):
    t = c.get("t")
    if t == "inlineStr":
        el = c.find(f"{q('is')}/{q('t')}")
        return el.text if el is not None else ""
    v = c.find(q("v"))
    if v is None:
        return ""
    if t == "s":
        i = int(v.text)
        return sst[i] if i < len(sst) else ""
    return v.text or ""


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


def load_shared_strings(zf):
    """目标表可能把表头存进 sharedStrings，t="s" 的单元格要靠它还原文本。"""
    try:
        sst_xml = zf.read("xl/sharedStrings.xml").decode("utf8")
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(q("t")))
            for si in ET.fromstring(sst_xml)]


# ── styles.xml 合并 ──────────────────────────────────────────────────

def get_or_create(root, tag):
    el = root.find(q(tag))
    if el is not None:
        return el
    el = ET.Element(q(tag))
    idx = STYLE_ORDER.index(tag)
    pos = len(list(root))
    for i, child in enumerate(list(root)):
        name = child.tag.split("}")[-1]
        if name in STYLE_ORDER and STYLE_ORDER.index(name) > idx:
            pos = i
            break
    root.insert(pos, el)
    return el


def merge_styles(tgt_xml, tpl_xml):
    """把模板样式追加到目标，返回 (新styles_xml, xf映射, dxf偏移, numFmt映射)。"""
    tgt = ET.fromstring(tgt_xml)
    tpl = ET.fromstring(tpl_xml)

    offsets = {}
    for tag in ("fonts", "fills", "borders", "dxfs"):
        t = get_or_create(tgt, tag)
        p = tpl.find(q(tag))
        offsets[tag] = len(list(t))
        for el in list(p if p is not None else []):
            t.append(el)
        t.set("count", str(len(list(t))))

    # numFmts：自定义格式（id>=164）重新编号，内建 id 原样保留
    t_nf = get_or_create(tgt, "numFmts")
    p_nf = tpl.find(q("numFmts"))
    by_code = {e.get("formatCode"): int(e.get("numFmtId")) for e in t_nf}
    used = {int(e.get("numFmtId")) for e in t_nf} | {163}
    numfmt_map = {}
    for e in list(p_nf if p_nf is not None else []):
        old, code = int(e.get("numFmtId")), e.get("formatCode")
        if code in by_code:
            numfmt_map[old] = by_code[code]
            continue
        new = max(used) + 1
        used.add(new)
        e.set("numFmtId", str(new))
        t_nf.append(e)
        numfmt_map[old] = new
    t_nf.set("count", str(len(list(t_nf))))

    # cellXfs：重映射 fontId/fillId/borderId/numFmtId 后追加
    t_xf = get_or_create(tgt, "cellXfs")
    p_xf = tpl.find(q("cellXfs"))
    base = len(list(t_xf))
    xf_map = {}
    for i, el in enumerate(list(p_xf if p_xf is not None else [])):
        for attr, tag in (("fontId", "fonts"), ("fillId", "fills"), ("borderId", "borders")):
            if el.get(attr) is not None:
                el.set(attr, str(int(el.get(attr)) + offsets[tag]))
        nf = el.get("numFmtId")
        if nf is not None and int(nf) >= 164:
            el.set("numFmtId", str(numfmt_map.get(int(nf), int(nf))))
        el.set("xfId", "0")
        t_xf.append(el)
        xf_map[i] = base + i
    t_xf.set("count", str(len(list(t_xf))))

    return ET.tostring(tgt, encoding="UTF-8", xml_declaration=True), xf_map, offsets["dxfs"], numfmt_map


def pivot_area(pt_xml):
    """从 pivotTable 的 location 取出它在 sheet 上占的矩形区域。"""
    m = re.search(r'<location[^>]*\bref="([A-Z]+)(\d+):([A-Z]+)(\d+)"', pt_xml)
    if not m:
        return None
    return (col_index(m.group(1)), int(m.group(2)),
            col_index(m.group(3)), int(m.group(4)))


def clear_pivot_area(xml, area):
    """清掉透视表区域内的静态单元格。

    搬过来的 sheet 带着模板上次保存时的渲染结果，也就是上一个项目的分类数据。
    refreshOnLoad 打开时会重建它们，但万一自动刷新没发生（用户关了自动刷新、
    或用别的表格软件打开），留着就成了误导。清空后未刷新时是空白透视表，
    一眼就知道该刷新。区域外的内容保留 —— MainQty 的 Q 列参考表就在区域外。
    """
    if not area:
        return xml
    c1, r1, c2, r2 = area

    def row_repl(m):
        head, body = m.group(1), m.group(2)
        rm = re.search(r'\br="(\d+)"', head)
        if not rm or not (r1 <= int(rm.group(1)) <= r2):
            return m.group(0)

        def cell_repl(cm):
            col = col_index(re.match(r"[A-Z]+", cm.group(1)).group(0))
            return "" if c1 <= col <= c2 else cm.group(0)

        body = re.sub(r'<c r="([A-Z]+\d+)"[^>]*(?:/>|>.*?</c>)', cell_repl, body,
                      flags=re.S)
        return f"{head}{body}</row>"

    return re.sub(r"(<row\b[^>]*>)(.*?)</row>", row_repl, xml, flags=re.S)


def clear_tab_selected(xml):
    """搬过来的 sheet 都带 tabSelected="1"，多个 sheet 同时选中会让 Excel 进入
    组编辑模式，在该模式下透视表无法刷新。"""
    return re.sub(r'\s*tabSelected="1"', "", xml)


def remap_sheet_styles(xml, xf_map):
    def sub_s(m):
        return f'{m.group(1)}{xf_map.get(int(m.group(2)), 0)}{m.group(3)}'
    xml = re.sub(r'(<(?:c|row)\b[^>]*?\bs=")(\d+)(")', sub_s, xml)
    xml = re.sub(r'(<col\b[^>]*?\bstyle=")(\d+)(")', sub_s, xml)
    return xml


def remap_pivot_dxf(xml, dxf_offset):
    return re.sub(r'(dxfId=")(\d+)(")',
                  lambda m: f'{m.group(1)}{int(m.group(2)) + dxf_offset}{m.group(3)}', xml)


# ── 主流程 ───────────────────────────────────────────────────────────

def install(target, template, data_sheet=None, output=None):
    target, template = Path(target).resolve(), Path(template).resolve()
    output = Path(output).resolve() if output else target
    if output != target:
        shutil.copy(target, output)
        target = output

    tz = zipfile.ZipFile(target)
    pz = zipfile.ZipFile(template)

    tgt_parts = {n: tz.read(n) for n in tz.namelist()}
    wb = ET.fromstring(tgt_parts["xl/workbook.xml"])

    # 数据 sheet → 它的 xml 路径
    rels_xml = tgt_parts["xl/_rels/workbook.xml.rels"].decode("utf8")
    rel_target = {r.get("Id"): resolve_target("xl/workbook.xml", r.get("Target"))
                  for r in ET.fromstring(rels_xml)}
    sheets_el = wb.find(q("sheets"))
    sheet_paths = {}
    for s in sheets_el:
        rid = s.get(f"{{{NS_REL}}}id")
        sheet_paths[s.get("name")] = rel_target[rid]

    name = data_sheet or list(sheet_paths)[0]
    if name not in sheet_paths:
        raise RuntimeError(f"目标无 sheet {name!r}，现有: {list(sheet_paths)}")

    first, last, last_row = find_class_range(tz, sheet_paths[name])
    ref = f"'{name}'!${col_letter(first)}$1:${col_letter(last)}${last_row}"
    print(f"分类定义区: {ref}  ({last - first + 1} 列 x {last_row - 1} 行)")

    # 已存在的同名 sheet 先摘掉（重跑幂等）
    for s in list(sheets_el):
        if s.get("name") in PIVOT_SHEETS:
            rid = s.get(f"{{{NS_REL}}}id")
            tgt_parts.pop(rel_target.get(rid, ""), None)
            sheets_el.remove(s)
            rels_xml = rels_drop(rels_xml, rid)
            print(f"  移除旧 sheet: {s.get('name')}")

    # 样式合并
    new_styles, xf_map, dxf_offset, _ = merge_styles(
        tgt_parts["xl/styles.xml"], pz.read("xl/styles.xml").decode("utf8"))
    tgt_parts["xl/styles.xml"] = new_styles

    # 模板里 sheet 名 → xml 路径
    p_wb = ET.fromstring(pz.read("xl/workbook.xml"))
    p_rels = ET.fromstring(pz.read("xl/_rels/workbook.xml.rels"))
    p_rel_target = {r.get("Id"): resolve_target("xl/workbook.xml", r.get("Target"))
                    for r in p_rels}
    p_sheet_path = {
        s.get("name"): p_rel_target[s.get(f"{{{NS_REL}}}id")]
        for s in p_wb.find(q("sheets"))
    }

    next_rid = max(int(x) for x in re.findall(r'Id="rId(\d+)"', rels_xml)) + 1
    next_sid = max(int(s.get("sheetId")) for s in sheets_el) + 1
    ct_xml = tgt_parts["[Content_Types].xml"].decode("utf8")

    # pivotCache：definition 照搬（保留字段结构），records 清空，置 refreshOnLoad
    cache_def = pz.read("xl/pivotCache/pivotCacheDefinition1.xml").decode("utf8")
    cache_def = re.sub(r'\srefreshOnLoad="[01]"', "", cache_def)
    cache_def = re.sub(r' recordCount="[0-9]+"', "", cache_def)
    cache_def = cache_def.replace("<pivotCacheDefinition ",
                                  '<pivotCacheDefinition refreshOnLoad="1" recordCount="0" ', 1)
    cache_def = re.sub(r'<worksheetSource[^>]*/>',
                       f'<worksheetSource name="{RANGE_NAME}"/>', cache_def)
    # 缓存字段里的 sharedItems 还留着模板项目的取值列表，看着像该清掉，但不能：
    # pivotTable 的 <item x="N"/> 按索引引用它们，清空后索引失效，Excel 打不开。
    # 这些值在刷新时会被整体替换，且不落在任何 sheet 上，交付文件里看不见。
    cache_part = "xl/pivotCache/pivotCacheDefinitionP1.xml"
    rec_part = "xl/pivotCache/pivotCacheRecordsP1.xml"
    tgt_parts[cache_part] = cache_def.encode("utf8")
    # 不搬模板的数据快照：既避免上一个项目的数据跟着模板扩散，
    # 也让 refreshOnLoad 打开即按新数据源重建。
    tgt_parts[rec_part] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<pivotCacheRecords xmlns="{NS_MAIN}" xmlns:r="{NS_REL}" count="0"/>'
    ).encode("utf8")
    tgt_parts[f"xl/pivotCache/_rels/pivotCacheDefinitionP1.xml.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{NS_PKGREL}"><Relationship '
        f'Type="{NS_REL}/pivotCacheRecords" Target="/{rec_part}" Id="rId1"/></Relationships>'
    ).encode("utf8")
    ct_xml = ct_add(ct_xml, cache_part, "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml")
    ct_xml = ct_add(ct_xml, rec_part, "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheRecords+xml")

    cache_rid = f"rId{next_rid}"
    next_rid += 1
    rels_xml = rels_add(rels_xml, cache_rid, "pivotCacheDefinition", f"/{cache_part}")

    # cacheId 必须与 pivotTable 内部记录一致，否则 Excel 判定文件损坏
    pc_existing = re.findall(r'<pivotCache[^>]*cacheId="(\d+)"',
                             tgt_parts["xl/workbook.xml"].decode("utf8"))
    cache_id = max([int(x) for x in pc_existing] + [0]) + 1

    # 4 个透视表 sheet
    for i, sname in enumerate(PIVOT_SHEETS, 1):
        src = p_sheet_path[sname]
        sheet_xml = clear_tab_selected(
            remap_sheet_styles(pz.read(src).decode("utf8"), xf_map))

        # 该 sheet 的 pivotTable 部件
        src_rels = f"{posixpath.dirname(src)}/_rels/{posixpath.basename(src)}.rels"
        pt_src = None
        if src_rels in pz.namelist():
            for rr in ET.fromstring(pz.read(src_rels)):
                if rr.get("Type", "").endswith("/pivotTable"):
                    pt_src = resolve_target(src, rr.get("Target"))
        if not pt_src:
            raise RuntimeError(f"模板 sheet {sname} 上找不到透视表部件")

        sheet_xml = clear_pivot_area(sheet_xml, pivot_area(pz.read(pt_src).decode("utf8")))

        pt_part = f"xl/pivotTables/pivotTableP{i}.xml"
        pt_xml = remap_pivot_dxf(pz.read(pt_src).decode("utf8"), dxf_offset)
        pt_xml = re.sub(r'(cacheId=")\d+(")', rf'\g<1>{cache_id}\g<2>', pt_xml)
        tgt_parts[pt_part] = pt_xml.encode("utf8")
        tgt_parts[f"xl/pivotTables/_rels/pivotTableP{i}.xml.rels"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{NS_PKGREL}"><Relationship '
            f'Type="{NS_REL}/pivotCacheDefinition" Target="/{cache_part}" Id="rId1"/></Relationships>'
        ).encode("utf8")
        ct_xml = ct_add(ct_xml, pt_part, "application/vnd.openxmlformats-officedocument.spreadsheetml.pivotTable+xml")

        sh_part = f"xl/worksheets/sheetP{i}.xml"
        tgt_parts[sh_part] = sheet_xml.encode("utf8")
        tgt_parts[f"xl/worksheets/_rels/sheetP{i}.xml.rels"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{NS_PKGREL}"><Relationship '
            f'Type="{NS_REL}/pivotTable" Target="/{pt_part}" Id="rId1"/></Relationships>'
        ).encode("utf8")
        ct_xml = ct_add(ct_xml, sh_part, "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")

        rid = f"rId{next_rid}"
        next_rid += 1
        rels_xml = rels_add(rels_xml, rid, "worksheet", f"/{sh_part}")

        s = ET.SubElement(sheets_el, q("sheet"))
        s.set("name", sname)
        s.set("sheetId", str(next_sid))
        s.set(f"{{{NS_REL}}}id", rid)
        next_sid += 1
        print(f"  已装入: {sname}")

    # definedNames：分类定义区 + 模板里 MainQty 上的辅助区域
    dn = wb.find(q("definedNames"))
    if dn is None:
        dn = ET.Element(q("definedNames"))
        wb.insert(list(wb).index(sheets_el) + 1, dn)
    p_dn = p_wb.find(q("definedNames"))
    wanted = {RANGE_NAME: ref}
    for el in list(p_dn if p_dn is not None else []):
        if el.get("name") != RANGE_NAME and el.get("localSheetId") is None:
            wanted.setdefault(el.get("name"), el.text)
    for el in list(dn):
        if el.get("name") in wanted:
            dn.remove(el)
    for nm, txt in wanted.items():
        el = ET.SubElement(dn, q("definedName"))
        el.set("name", nm)
        el.text = txt

    # pivotCaches
    pc = wb.find(q("pivotCaches"))
    if pc is None:
        # CT_Workbook 的子元素顺序是强制的：pivotCaches 必须排在 calcPr /
        # oleSize / customWorkbookViews 之后，放错位置 Excel 会判定文件损坏。
        pc = ET.Element(q("pivotCaches"))
        before = ("fileVersion", "fileSharing", "workbookPr", "workbookProtection",
                  "bookViews", "sheets", "functionGroups", "externalReferences",
                  "definedNames", "calcPr", "oleSize", "customWorkbookViews")
        pos = 0
        for i, child in enumerate(list(wb)):
            if child.tag.split("}")[-1] in before:
                pos = i + 1
        wb.insert(pos, pc)
    c = ET.SubElement(pc, q("pivotCache"))
    c.set("cacheId", str(cache_id))
    c.set(f"{{{NS_REL}}}id", cache_rid)

    tgt_parts["xl/workbook.xml"] = ET.tostring(wb, encoding="UTF-8", xml_declaration=True)
    tgt_parts["xl/_rels/workbook.xml.rels"] = rels_xml.encode("utf8")
    tgt_parts["[Content_Types].xml"] = ct_xml.encode("utf8")

    tz.close()
    pz.close()

    tmp = target.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for n, data in tgt_parts.items():
            out.writestr(n, data)
    tmp.replace(target)
    print(f"Done: {len(PIVOT_SHEETS)} 个透视表已装入 → {target.name}（打开时自动刷新）")
    return target


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--template", default=str(
        Path(__file__).resolve().parent.parent / "references" / "pivot_template.xlsx"))
    ap.add_argument("--sheet")
    ap.add_argument("--output", "-o")
    a = ap.parse_args()
    install(a.input, a.template, a.sheet, a.output)
