"""交付检查（阶段 ⑩）：核对工作台是不是真的装起来了、分类是不是真的填完了。

弱模型最常见的失败是跳过步骤 2 直接去分类，交付一个只有一张 sheet 的表。
这里的检查项都是跑出硬数字的，跳过哪一步都会在输出里露出来。

用法:
    python verify_workbook.py <工作台.xlsx> [--sheet CombineBQ] [--expect-rows N]

退出码 0 = 全过，1 = 有 FAIL。
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.worksheet.formula import ArrayFormula

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "references" / "pivot_template.xlsx"


def template_expectations(template):
    """期望值从模板实时读 —— 模板改过 RFQPlan→CostSummary、入价→成本，
    写死常量的检查脚本当场失效，这类改名不该让交付检查跟着返工。"""
    zf = zipfile.ZipFile(template)
    wb_xml = zf.read("xl/workbook.xml").decode("utf8")
    sheets = [s for s in re.findall(r'<sheet[^>]*name="([^"]+)"', wb_xml)
              if s != layout.SHEET]
    zf.close()

    twb = openpyxl.load_workbook(template, read_only=True)
    tws = twb[layout.SHEET]
    headers = set(layout.find_columns(tws, layout.HEADER_ROW))
    twb.close()
    # 分包组表头带分包商名（模板里是占位的 "XXX Rate"，装配时随 --subcontractor 变），
    # 那一组不进期望集合，改用「Rate/Amount 成对出现的组数」来核。
    dynamic = {h for h in headers if h.endswith((" Rate", " Amount"))
               and not h.split(" ")[0] in ("报价", "成本", "AI")}
    return sheets, headers - dynamic


def is_formula(v):
    """A/B 列是动态数组公式，openpyxl 给的是 ArrayFormula 对象而不是 = 开头的字符串。"""
    if isinstance(v, ArrayFormula):
        return True
    return isinstance(v, str) and v.startswith("=")

results = []


def check(name, ok, detail):
    results.append((name, bool(ok), detail))


def report(path, factor_note, subcontractor):
    print(f"检查对象: {path.name}")
    if factor_note is not None:
        print(f"放大系数（第 {layout.FACTOR_ROW} 行，换项目必须确认）: {factor_note or '未取到'}")
        print(f"分包商名（第 1 行）: {subcontractor or '未取到'}")
    print()
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in results if not ok]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} 项通过"
          + (f" | 未过: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    # 不默认模板名：产物的数据页保留源清单自己的 sheet 名，认表头锚点才对
    ap.add_argument("--sheet", help="数据页名，默认自动认含 Description 的那张")
    ap.add_argument("--expect-rows", type=int,
                    help="源清单的条目数，用来核对有没有漏行")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE),
                    help="期望结构的来源，默认技能自带的 pivot_template.xlsx")
    ap.add_argument("--stage", choices=("build", "full"), default="full",
                    help="build=只验工作台结构（分类列此时本就是空的）；"
                         "full=连分类填充率一起验，交付前用这个")
    a = ap.parse_args()
    path = Path(a.workbook).resolve()
    want_sheets, want_headers = template_expectations(a.template)

    # ── 工作簿结构：没套模板的话，这一条直接挂 ──
    zf = zipfile.ZipFile(path)
    wb_xml = zf.read("xl/workbook.xml").decode("utf8")
    sheets = re.findall(r'<sheet[^>]*name="([^"]+)"', wb_xml)
    missing = [s for s in want_sheets if s not in sheets]
    check("工作簿结构", not missing,
          f"sheet: {sheets}" + (f" | 缺 {missing} —— 步骤 2 没跑，这不是工作台" if missing else ""))

    n_pivot = len([n for n in zf.namelist() if "pivotTables/pivotTable" in n])
    check("透视表部件", n_pivot >= 3, f"{n_pivot} 个 pivotTable 部件（应为 3）")

    cache_defs = [n for n in zf.namelist() if "pivotCacheDefinition" in n and n.endswith(".xml")]
    refresh = all('refreshOnLoad="1"' in zf.read(n).decode("utf8") for n in cache_defs) if cache_defs else False
    check("refreshOnLoad", refresh,
          "打开即刷新已置位" if refresh else "缓存未置 refreshOnLoad，打开看到的是旧数据")

    has_range = "分类定义区" in wb_xml
    check("分类定义区", has_range,
          "定义名称在" if has_range else "定义名称丢失，透视表数据源会指空")
    zf.close()

    # 公式文本只有 openpyxl 读得到，这里必须用它
    wb = openpyxl.load_workbook(path)
    try:
        ws = layout.get_sheet(wb, a.sheet)
    except RuntimeError as e:
        check(layout.SHEET, False, str(e))
        return report(path, None, None)
    cols = layout.find_columns(ws, layout.HEADER_ROW)

    lack = sorted(n for n in want_headers if layout.resolve(cols, n) is None)
    check("表头完整", not lack,
          f"第 {layout.HEADER_ROW} 行 {len(cols)} 个表头" + (f" | 缺 {lack}" if lack else ""))

    # 组靠表头行上方的分组标签认，不靠列名后缀 —— 三组的 Rate / Amount 现在
    # 都是光名字，没有 报价 / 成本 前缀可数了。
    glabels = [ws.cell(row=r, column=c).value
               for r in range(1, layout.HEADER_ROW)
               for c in range(1, ws.max_column + 1)]
    found = [g for g in layout.GROUPS if g in glabels]
    check("分组标签", len(found) == len(layout.GROUPS),
          f"{found}（应为 {layout.GROUPS}）")

    qty_c = next((cols[n] for n in ("Qty", "Quantity") if n in cols), None)
    check("工程量列", qty_c is not None, "Qty / Quantity 之一存在"
          if qty_c else "找不到 Qty 或 Quantity 列")

    # ── 数据行 ──
    desc_c = cols.get("Description")
    rows = []
    total_row = None
    for r in range(layout.DATA_START, ws.max_row + 1):
        d = ws.cell(row=r, column=desc_c).value if desc_c else None
        if d is None or str(d).strip() == "":
            continue
        if str(d).strip().startswith("【TOTAL】"):
            total_row = r
            continue
        rows.append(r)
    check("数据行", bool(rows), f"{len(rows)} 行（从第 {layout.DATA_START} 行起）")
    check("TOTAL 行", total_row is not None,
          f"第 {total_row} 行" if total_row else "缺【TOTAL】行，汇总公式没有落点")

    if a.expect_rows:
        check("行数对账", len(rows) == a.expect_rows,
              f"工作台 {len(rows)} 行 vs 源清单 {a.expect_rows} 行")

    # ── 公式脚手架：只装了表头没生成公式，等于空壳 ──
    def formula_rate(col_name, subset):
        c = cols.get(col_name)
        if not c or not subset:
            return 0.0, 0
        n = sum(1 for r in subset if is_formula(ws.cell(row=r, column=c).value))
        return n / len(subset), n

    item_rows = [r for r in rows
                 if layout.row_kind(ws.cell(row=r, column=desc_c).value) == "item"
                 and ws.cell(row=r, column=qty_c).value not in (None, "", 0)]
    # 键列只在明细行上判：模板的标题行（【】/《》）本来就没有 Main Key / BQ KEY
    # 公式，按全部行判会把「忠实照模板生成」的产物判成不合格。
    for key in layout.KEY_COLS:
        rate, n = formula_rate(key, item_rows)
        check(f"公式列 {key}", rate > 0.9,
              f"{n}/{len(item_rows)} 个明细行有公式（{rate:.0%}）")

    for key in layout.RATE_COLS:
        rate, n = formula_rate(key, item_rows)
        check(f"套价落点 {key}", rate > 0.9,
              f"{n}/{len(item_rows)} 个明细行有公式（{rate:.0%}）")

    # ── 分类填充率：装配阶段这几列本来就空着，等 pk-boq-classify 来填 ──
    for name in (layout.AI_COLS if a.stage == "full" else []):
        c = cols.get(name)
        if not c:
            check(f"分类 {name}", False, "列不存在")
            continue
        n = sum(1 for r in item_rows
                if ws.cell(row=r, column=c).value not in (None, ""))
        rate = n / len(item_rows) if item_rows else 0
        check(f"分类 {name}", rate >= 0.9,
              f"{n}/{len(item_rows)} 个明细行有值（{rate:.0%}）")

    # ── 需要人确认的，不判定对错，只摆出来 ──
    notes = []
    fr = layout.FACTOR_ROW
    for h in ("Labor", "Material", "Equipment"):
        if h in cols:
            notes.append(f"{ws.cell(row=fr, column=cols[h]).coordinate}="
                         f"{ws.cell(row=fr, column=cols[h]).value}")
    return report(path, ", ".join(notes), " / ".join(found))


if __name__ == "__main__":
    sys.exit(main())
