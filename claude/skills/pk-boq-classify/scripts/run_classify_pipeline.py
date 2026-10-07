#!/usr/bin/env python3
"""分类驱动：读清单 -> 规则引擎分类 -> 产出 classification.json。

只读不写 Excel —— 本脚本的产物是 classification.json，落地写回由
write_classification.py 负责（zip/XML 层把五列插进清单）。分类的输入是
Description + Unit + 分级章节，全在原清单里，不需要工作台存在。

用法:
    python run_classify_pipeline.py <清单.xlsx> [--sheet 合并报表] [--header-row 3]
                                    [-o classification.json] [--write-back <工作台.xlsx>]

--write-back 是补分类用的旁路：目标已经是建好的工作台、只想把五个分类列填上时用。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parent.as_posix())

import openpyxl

import layout
from route_boq import read_header, resolve_cols, detect_start_row, open_sheet
from classify_boq_engine import load_vocab, classify_all, write_to_excel

AI_HEADERS = ("Discipline", "SortKey", "Category", "Subcategory", "Element")


def extract_items(path, sheet=None, header_row=layout.HEADER_ROW, start_row=0):
    """按表头名定位列、自动探测数据起始行，逐行带上 L1/L2/L3 章节上下文。"""
    path = Path(path)
    hdr = read_header(path, sheet, header_row)
    cols = resolve_cols(hdr, {}, header_row)
    start = start_row or detect_start_row(path, sheet, header_row, cols["desc"])

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = open_sheet(wb, sheet)
    items = []
    l1 = l2 = l3 = ""
    for row in range(start, ws.max_row + 1):
        desc_val = ws.cell(row=row, column=cols["desc"]).value
        desc = str(desc_val).strip() if desc_val else ""
        if not desc:
            continue
        if desc.startswith("【") and "】" in desc:
            l1, l2, l3 = desc.strip("【】").strip(), "", ""
            continue
        if desc.startswith("《") and "》" in desc:
            l2, l3 = desc.strip("《》").strip(), ""
            continue
        if desc.startswith("{") and "}" in desc:
            l3 = desc.strip("{}").strip()
            continue

        unit_val = ws.cell(row=row, column=cols["unit"]).value
        unit = str(unit_val).strip() if unit_val else ""
        # 量待定的条目照样要分类（"Contractor's Supervision" 单位 Week、量空着），
        # 所以只看有没有单位，不拿 qty > 0 当门槛。
        if not unit:
            continue
        items.append({
            "excel_row": row,
            "desc": desc,
            "l1": l1, "l2": l2, "l3": l3,
            "unit": unit,
        })
    wb.close()
    print(f"[classify] 表头行 {header_row} | 数据起始行 {start} | 取到 {len(items)} 条", file=sys.stderr)
    return items


def to_record(item):
    """引擎字段 -> 表头名字段，装配脚本按表头名落列。"""
    subcat = ""
    if item.get("subcategory_name_en"):
        subcat = (f"{item['subcategory_code']} {item['subcategory_name_en']}"
                  if item.get("subcategory_code") else item["subcategory_name_en"])
    rec = {
        "src_row": item["excel_row"],
        # desc_head 是装配时的错位断言，缺了它对不上就写错一整批
        "desc_head": item["desc"][:30],
        "unit": item.get("unit", ""),
        "Discipline": item.get("discipline_en", ""),
        "SortKey": item.get("sortkey", ""),
        "Category": item.get("category_name_en", ""),
        "Subcategory": subcat,
        "Element": item.get("element_en", ""),
    }
    if item.get("source"):
        rec["source"] = item["source"]
    return rec


def main():
    ap = argparse.ArgumentParser(description="BOQ 分类：产出 classification.json")
    ap.add_argument("source", help="清单 xlsx（原清单或已建好的工作台）")
    ap.add_argument("--sheet")
    ap.add_argument("--header-row", type=int, default=layout.HEADER_ROW,
                    help=f"表头行号（默认 {layout.HEADER_ROW}，工作台布局；原清单常是 1）")
    ap.add_argument("--start-row", type=int, default=0,
                    help="数据起始行（默认自动：表头行之后第一个描述非空的行）")
    ap.add_argument("-o", "--out", default="classification.json")
    ap.add_argument("--write-back", metavar="XLSX",
                    help="旁路：目标已是工作台时，直接把五个分类列写回它")
    a = ap.parse_args()

    items = extract_items(a.source, a.sheet, a.header_row, a.start_row)
    vocab = load_vocab()
    classified, unmatched = classify_all(items, vocab)
    print(f"[classify] 规则命中 {len(classified)} 条，待 LLM 复核 {len(unmatched)} 条",
          file=sys.stderr)

    # 引擎会把没匹配上的也放进 classified，标成 Unassigned。这类不能当分类结果
    # 写进表 —— 写进去就是假值，还会让填充率看着达标、掩盖漏跑 LLM。
    records = [r for r in (to_record(it) for it in classified)
               if r["Discipline"] and r["Discipline"] != "Unassigned"]
    pending = {it["excel_row"] for it in unmatched}
    pending |= {it["excel_row"] for it in classified
                if it.get("discipline_en") in (None, "", "Unassigned")}
    payload = {
        "source": str(Path(a.source).name),
        "sheet": a.sheet or "",
        "header_row": a.header_row,
        "items": records,
        "pending": [{"src_row": it["excel_row"], "desc_head": it["desc"][:30],
                     "unit": it.get("unit", ""), "l1": it["l1"]}
                    for it in items if it["excel_row"] in pending],
    }
    Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                           encoding="utf8")
    n_pending = len(payload["pending"])
    print(f"[classify] 已写 {a.out}：规则定案 {len(records)} 条，"
          f"待 LLM {n_pending} 条（共 {len(items)} 条）", file=sys.stderr)
    if n_pending:
        print(f"[classify] 待 LLM 的条目在 JSON 的 pending 里，"
              f"走阶段③④⑦ 定完再合并进 items", file=sys.stderr)

    if a.write_back:
        n = write_to_excel(classified, a.write_back, a.write_back)
        print(f"[classify] 已写回 {n} 行 -> {a.write_back}", file=sys.stderr)


if __name__ == "__main__":
    main()
