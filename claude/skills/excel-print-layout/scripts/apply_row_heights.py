# -*- coding: utf-8 -*-
# 应用实测行高到 sheet XML：对每个 sheet 的 sheetData/row[@r=row] 写 ht +
# customHeight="1"。纯 ZIP+lxml，其余条目（分页符/打印设置/样式/公式/媒体）原样搬运。
#
# 为什么不用 openpyxl 保存：会丢失媒体/样式/计算链，Excel 打不开。这里 openpyxl
# 只用于读 sheet 顺序，写操作全走原生 XML。
import sys, io, argparse, json, zipfile, shutil, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from lxml import etree
import openpyxl

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def parse_args():
    ap = argparse.ArgumentParser(description="把实测行高写回 xlsx（纯 XML，先备份）。")
    ap.add_argument("input", help="输入 xlsx 路径")
    ap.add_argument("--measures", required=True, help="measure_row_heights.py 输出的 JSON 路径")
    ap.add_argument("--output", help="输出路径；缺省则先备份 input 到同目录 temp/ 后就地覆盖")
    return ap.parse_args()


def main():
    args = parse_args()
    src = args.input
    out = args.output or src
    if args.output is None:
        d = os.path.dirname(os.path.abspath(src))
        bak = os.path.join(d, "temp", os.path.splitext(os.path.basename(src))[0] + "_行高前备份.xlsx")
        os.makedirs(os.path.dirname(bak), exist_ok=True)
        shutil.copy2(src, bak)
        print("备份:", bak)

    meas = json.load(open(args.measures, encoding="utf-8"))  # {sheet_title: {str(row): height}}
    wbt = openpyxl.load_workbook(src, read_only=True, data_only=False)
    order = {i + 1: ws.title for i, ws in enumerate(wbt.worksheets)}
    wbt.close()
    xml_by_idx = {i: "xl/worksheets/sheet%d.xml" % i for i in order}

    applied = {}
    zin = zipfile.ZipFile(src)
    items = []
    for n in zin.namelist():
        data = zin.read(n)
        if n in xml_by_idx.values():
            idx = next(i for i, p in xml_by_idx.items() if p == n)
            title = order[idx]
            adj = meas.get(title, {})
            if adj:
                root = etree.fromstring(data)
                sd = root.find("{%s}sheetData" % NS)
                hit = {}
                if sd is not None:
                    for row in sd.findall("{%s}row" % NS):
                        r = row.get("r")
                        if r and r in adj:
                            h = adj[r]
                            row.set("ht", str(h))
                            row.set("customHeight", "1")
                            hit[int(r)] = h
                applied[title] = hit
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        items.append((n, data, zin.getinfo(n).compress_type))
    zin.close()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, data, ct in items:
            zout.writestr(n, data)

    missed = sum(1 for title, adj in meas.items()
                 for r in adj if int(r) not in applied.get(title, {}))
    print("应用行数:", sum(len(v) for v in applied.values()), " 缺失(未找到 row 元素):", missed)
    for t, a in applied.items():
        if a:
            print("%-34s %4d 行  %s" % (t, len(a), dict(list(a.items())[:3])))
    print("输出:", out)


if __name__ == "__main__":
    main()
