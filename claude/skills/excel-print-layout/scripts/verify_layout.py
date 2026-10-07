# -*- coding: utf-8 -*-
# 验证打印排版结果：
#   1) 行高抽查（COM RowHeight vs 期望，来自 --measures JSON）
#   2) 打印宽度（每 sheet FitToPagesWide 是否 = --expect-wide）
#   3) 分页符：XML rowBreaks（brk id + 1 = 新页首行）vs COM HPageBreaks 实际分页。
#
# 注意 COM 集合陷阱：不要用 HPageBreaks(i) 按索引取（会误报/崩溃），用
# `for br in ws.HPageBreaks` 迭代。
import sys, io, argparse, json, zipfile, re, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from lxml import etree
import win32com.client, openpyxl

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def parse_args():
    ap = argparse.ArgumentParser(description="验证 Excel 打印排版（行高/页宽/分页符）。")
    ap.add_argument("input", help="输入 xlsx 路径")
    ap.add_argument("--measures", help="实测 JSON 路径（验证行高用，可选）")
    ap.add_argument("--expect-wide", type=int, default=1, help="期望的 FitToPagesWide 值，默认 1")
    ap.add_argument("--sample", type=int, default=8, help="每 sheet 抽查行数上限，默认 8")
    return ap.parse_args()


def main():
    args = parse_args()
    src = os.path.abspath(args.input)  # COM 需要绝对路径
    meas = json.load(open(os.path.abspath(args.measures), encoding="utf-8")) if args.measures else {}

    wbt = openpyxl.load_workbook(src, read_only=True, data_only=False)
    order = {i + 1: ws.title for i, ws in enumerate(wbt.worksheets)}
    wbt.close()

    # XML 层：手动分页符（转成新页首行）+ fitToWidth
    xml_info = {}
    zin = zipfile.ZipFile(src)
    for i, title in order.items():
        n = "xl/worksheets/sheet%d.xml" % i
        root = etree.fromstring(zin.read(n))
        rbk = root.find("{%s}rowBreaks" % NS)
        brs = []
        if rbk is not None:
            for b in rbk.findall("{%s}brk" % NS):
                brs.append(int(b.get("id")) + 1)  # 新页首行
        ps = root.find("{%s}pageSetup" % NS)
        ftw = ps.get("fitToWidth") if ps is not None else None
        xml_info[title] = (sorted(brs), ftw)
    zin.close()

    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(src, ReadOnly=True, UpdateLinks=0)
        h_ok = h_bad = h_chk = 0
        wide_ok = wide_bad = 0
        brk_missing = brk_auto = brk_ok = 0
        for ws in wb.Worksheets:
            title = ws.Name
            adj = meas.get(title, {})
            hb = []
            for ri, (r, expect) in enumerate(adj.items()):
                if ri >= args.sample:
                    break
                got = round(ws.Rows(int(r)).RowHeight, 1)
                h_chk += 1
                if abs(got - expect) <= 0.3:
                    h_ok += 1
                else:
                    h_bad += 1
                    hb.append((r, expect, got))
            if hb:
                print("!! 行高不符 %-30s %s" % (title, hb))
            fw = ws.PageSetup.FitToPagesWide
            if fw == args.expect_wide:
                wide_ok += 1
            else:
                wide_bad += 1
                print("!! 页宽不符 %-30s FitToPagesWide=%s" % (title, fw))
            # 实际分页（迭代，勿用索引）
            breaks = []
            try:
                for br in ws.HPageBreaks:
                    breaks.append(br.Location.Row)
            except Exception:
                breaks = []
            breaks = sorted(breaks)
            xb, _ = xml_info.get(title, ([], None))
            # 手动分页符（新页首行）是否全部生效；额外的是自动分页（行高调大常导致）
            bset = set(breaks)
            missing = [r for r in xb if r not in bset]
            auto_only = [r for r in breaks if r not in set(xb)]
            if missing:
                brk_missing += 1
                print("!! 手动分页符丢失 %-30s 期望%s 缺%s" % (title, xb[:8], missing))
            elif auto_only:
                brk_auto += 1
                print("  手动分页全生效+自动分页 %-30s 手动%d个 额外自动%d个 %s" % (
                    title, len(xb), len(auto_only), auto_only[:6]))
            else:
                brk_ok += 1
        print()
        print("行高抽查: %d 匹配 / %d 不符 / %d 共" % (h_ok, h_bad, h_chk))
        print("打印宽度: FitToPagesWide=%d 的 sheet %d 个, 其余 %d 个" % (args.expect_wide, wide_ok, wide_bad))
        print("分页符: 精确一致 %d 个 / 手动全生效(含自动分页) %d 个 / 手动丢失 %d 个" % (brk_ok, brk_auto, brk_missing))
        wb.Close(False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
