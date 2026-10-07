#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build unified Excel material price table from quotation data.json.

Takes manifest-enriched.json (the --analyze output), producing a standardized
16-column 人材机价格表 Excel file suitable for sharing and review.

Usage:
  python build_batch_excel.py <data.json> [-o output.xlsx] [--title ...] [--subtitle ...]
"""

import argparse, json, sys, os
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'pk-boq', 'scripts'))
from openpyxl_utils import clean_save


def load_data(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _num(v):
    """价格安全转数值：None / 空串 / 带千分位的字符串都能处理。

    读不到返回 None 而不是 0 —— 表格里写 0 会被读成"这东西不要钱"，
    比留空更糟。国别税率未配置时除税价反算不出来，整列会是 null，
    真按 0 写出去就是一张错表。
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(v):
    """日期只取到日。manifest-enriched 里 date 已被转成 Date 再序列化，
    原样写进表格会是 2026-06-03T00:00:00.000Z。"""
    s = str(v or "").strip()
    return s[:10] if len(s) >= 10 else s


def build_xlsx(data: dict, output_path: str, title: str, subtitle: str):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quotation"

    project = data.get("project", {})
    suppliers = data.get("suppliers", [])

    # 兼容 manifest.json 的扁平结构：items 平铺、供应商信息挂在每条上。
    # 老的 data.json 是 suppliers[].items[]，两种都要能读。
    if not suppliers and data.get("items"):
        grouped = {}
        for it in data["items"]:
            key = it.get("supplier", "") or "(未标供应商)"
            if key not in grouped:
                grouped[key] = {
                    "name": key,
                    "name_cn": it.get("supplier_cn", ""),
                    "contact": it.get("contact", ""),
                    "phone": it.get("phone", ""),
                    "address": it.get("address", ""),
                    "projectName": it.get("projectName", project.get("projectName", "")),
                    "sourceFile": (it.get("sourceRef") or {}).get("file", ""),
                    "remarks": it.get("remarks", ""),
                    "items": [],
                }
            grouped[key]["items"].append(it)
        suppliers = list(grouped.values())

    # Styles
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    header_font = Font(name="Microsoft YaHei", size=11, bold=True)
    title_font = Font(name="Microsoft YaHei", size=14, bold=True)
    data_font = Font(name="Microsoft YaHei", size=10)
    group_font = Font(name="Microsoft YaHei", size=10, bold=True)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    group_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Column widths (A-P, 16 columns)
    col_widths = {
        "A": 8, "B": 14, "C": 40, "D": 60, "E": 8, "F": 14,
        "G": 12, "H": 14, "I": 14, "J": 8, "K": 28, "L": 10,
        "M": 14, "N": 30, "O": 30, "P": 40,
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    # Row 1: Title
    ws.merge_cells("A1:P1")
    c = ws["A1"]
    c.value = title
    c.font = title_font
    c.alignment = center_align

    # Row 2: Subtitle —— 副标题紧跟标题，表头在它下面直接压着数据区
    ws.merge_cells("A2:P2")
    c = ws["A2"]
    c.value = subtitle
    c.font = Font(name="Microsoft YaHei", size=9, bold=True)
    c.alignment = left_align

    # Row 3: Headers
    headers = [
        "编号", "专业", "名称", "项目特征", "单位", "除税单价", "税金", "含税单价",
        "日期", "币种", "供应商", "联系人", "电话", "地址", "备注", "来源",
    ]
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=i, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = center_align

    # Data rows (start from row 4)
    row = 4
    seq = 1
    all_prices = []

    for supplier in suppliers:
        supplier_name = supplier.get("name_cn") or supplier.get("name", "")
        source_file = supplier.get("sourceFile", "")

        # Supplier group header
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=16)
        cell = ws.cell(row=row, column=1, value=f"《{supplier_name}》")
        cell.font = group_font
        cell.fill = group_fill
        cell.alignment = left_align
        for col_idx in range(1, 17):
            ws.cell(row=row, column=col_idx).border = thin_border
            ws.cell(row=row, column=col_idx).fill = group_fill
        row += 1

        for item in supplier.get("items", []):
            # manifest 里"读不到的价格"是显式 null，.get(k, 0) 对显式 None 不生效，
            # 且值可能是带千分位的字符串，统一走安全转换
            price_excl = _num(item.get("price_excl_tax"))
            price_incl = _num(item.get("price_incl_tax"))
            tax = round(price_incl - price_excl, 2) if (price_incl and price_excl) else ""
            # 价格统计优先用除税价；税率未配置时它整列为空，退回含税价，
            # 否则统计行会报 0.00 - 0.00
            if price_excl:
                all_prices.append(price_excl)
            elif price_incl:
                all_prices.append(price_incl)

            vals = [
                seq,
                project.get("specialty", ""),
                item.get("name_cn") or item.get("name", ""),
                item.get("features_cn") or item.get("features", ""),
                item.get("unit", ""),
                price_excl if price_excl else "",
                tax,
                price_incl if price_incl else "",
                _date(item.get("date")),
                item.get("currency", ""),
                supplier_name,
                supplier.get("contact", ""),
                supplier.get("phone", ""),
                supplier.get("address_cn") or supplier.get("address", ""),
                supplier.get("remarks", ""),
                source_file,
            ]

            for col_idx, val in enumerate(vals, 1):
                cell = ws.cell(row=row, column=col_idx, value=val)
                cell.font = data_font
                cell.border = thin_border
                if col_idx in (1, 5, 6, 7, 8, 9, 10, 12, 13, 14):
                    cell.alignment = center_align
                else:
                    cell.alignment = left_align

            seq += 1
            row += 1

    # Summary rows
    row += 1
    total = seq - 1
    sources = sorted(set(s.get("sourceFile", "") for s in suppliers))
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=16)
    cell = ws.cell(row=row, column=1)
    cell.value = f"数据来源：{', '.join(sources)}"
    cell.font = Font(name="Microsoft YaHei", size=9)
    cell.alignment = left_align
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=16)
    cell = ws.cell(row=row, column=1)
    if all_prices:
        lo, hi = min(all_prices), max(all_prices)
        avg = sum(all_prices) / len(all_prices)
        cell.value = f"价格统计：共{total}项，最低{lo:,.2f}，最高{hi:,.2f}，平均{avg:,.2f}"
    else:
        cell.value = f"价格统计：共{total}项"
    cell.font = Font(name="Microsoft YaHei", size=9)
    cell.alignment = left_align

    clean_save(wb, output_path)
    return total, (min(all_prices) if all_prices else 0), (max(all_prices) if all_prices else 0)


def main():
    parser = argparse.ArgumentParser(description="Build unified quotation Excel from data.json")
    parser.add_argument("data", help="manifest-enriched.json (the --analyze output)")
    parser.add_argument("-o", "--output", default=None, help="Output xlsx path")
    parser.add_argument("--title", default="人材机价格表", help="Main title")
    parser.add_argument("--subtitle", default="", help="Subtitle in row 3")
    args = parser.parse_args()

    data = load_data(args.data)
    output = args.output or Path(args.data).with_suffix(".xlsx").name

    total, lo, hi = build_xlsx(data, output, args.title, args.subtitle)
    print(f"Generated: {output}")
    print(f"  Entries: {total}, Price range: {lo:,.2f} - {hi:,.2f}")


if __name__ == "__main__":
    main()
