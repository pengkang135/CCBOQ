"""混凝土标号换算映射生成器 —— 套定额链路的「定额换算」前置。

从清单（通常是 pk-boq-workbench 的 UniqueShot 页，或任何带
「定额编号 + 描述 + 工程量」三列的表）里，按描述解析混凝土标号，汇总出
每个定额子目在各标号下的工程量，产出 pk-norms-export 的 `--concrete-map`：

    {"A.04.03.006.BJ21.5-10": [{"grade": "35", "qty": 7742.919},
                               {"grade": "50", "qty": 5676.0045}, ...]}

标号口径（默认）：欧标写法 C50/60、C35/45、C28/35 取**第一个数**（圆柱体强度，
与中国定额 C 标号一致）→ C50 / C35 / C28。用 --grade-index 2 可改为取第二个数。

用法:
    python build_concrete_map.py 清单.xlsx --sheet UniqueShot \
        --code-col CODE --desc-col CleanDescription --qty-col "求和项:Qty" \
        [-o concrete_map.json] [--code-map code_map.json] [--grade-index 1]

    # 定额编号在清单里没带分册前缀（01.02.001.BJ12.1-7）时默认补 "A."，
    # 跨册（C/D/B/E）的零散编号用 --code-map 显式指定：
    #   {"21.05.03.BJ21.13.5-25": "C.13.05.003.BJ21.13.5-25", "JTS.SGB81": "D.05.02.001.SGB81"}
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import fastexcel

GRADE_RE = re.compile(r"C(\d{2})(?:/\d{2})?")
BOOK_HEADS = ("A", "B", "C", "D", "E")


def find_header(df, needed: list[str]) -> tuple[int, dict[str, int]]:
    """在前 10 行里找同时含所需列名的表头行；退化为 pandas 列名。"""
    for ri in range(min(len(df), 10)):
        vals = {str(v).strip(): ci for ci, v in enumerate(df.iloc[ri]) if v is not None}
        if all(n in vals for n in needed):
            return ri, vals
    vals = {str(c).strip(): ci for ci, c in enumerate(df.columns)}
    if all(n in vals for n in needed):
        return -1, vals
    raise SystemExit(f"找不到列 {needed}；候选表头: {list(df.columns)[:20]}")


def normalize_code(code: str, code_map: dict) -> str:
    if code in code_map:
        return code_map[code]
    head = code.split(".")[0]
    if head in BOOK_HEADS or code.startswith("JTS") or code.startswith("第一节"):
        return code
    return "A." + code


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boq", help="清单 xlsx")
    ap.add_argument("--sheet", default="UniqueShot", help="sheet 名（默认 UniqueShot）")
    ap.add_argument("--code-col", default="CODE", help="定额编号列表头名")
    ap.add_argument("--desc-col", default="CleanDescription", help="描述列表头名")
    ap.add_argument("--qty-col", default="求和项:Qty", help="工程量列表头名")
    ap.add_argument("--code-map", help='JSON {清单编号: 完整编号}，用于跨册零散编号')
    ap.add_argument("--grade-index", type=int, default=1, choices=(1, 2),
                    help="欧标 C50/60 取第几个数（默认 1 = 圆柱体，对齐中国 C 标号）")
    ap.add_argument("-o", "--out", default="concrete_map.json")
    a = ap.parse_args()

    code_map = json.loads(Path(a.code_map).read_text(encoding="utf-8")) if a.code_map else {}

    wb = fastexcel.read_excel(str(a.boq))
    if a.sheet not in wb.sheet_names:
        raise SystemExit(f"sheet '{a.sheet}' 不在 {a.boq}: {wb.sheet_names}")
    df = wb.load_sheet_by_name(a.sheet).to_pandas()
    hrow, cmap = find_header(df, [a.code_col, a.desc_col, a.qty_col])
    ic, idc, iq = cmap[a.code_col], cmap[a.desc_col], cmap[a.qty_col]

    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    rows = 0
    for ri in range(hrow + 1, len(df)):
        code = df.iloc[ri, ic]
        desc = df.iloc[ri, idc]
        if code is None or desc is None:
            continue
        code = str(code).strip()
        m = GRADE_RE.search(str(desc))
        if not code or "." not in code or not m:
            continue
        grade = m.group(1) if a.grade_index == 1 else (m.group(0).split("/")[1] if "/" in m.group(0) else m.group(1))
        try:
            q = float(df.iloc[ri, iq])
        except (TypeError, ValueError):
            q = 0.0
        agg[normalize_code(code, code_map)][grade] += q
        rows += 1

    out = {k: [{"grade": g, "qty": round(v, 4)} for g, v in sorted(d.items())]
           for k, d in agg.items()}
    pre = [k for k in out if re.search(r"c\d{2}$", k)]
    if pre:
        print(f"WARNING: {len(pre)} 个编号已带换算后缀（{pre[:3]} …）——本脚本要吃**换算前**的表，"
              f"否则会叠加换算。请改用换算前的清单/分类表重跑。", file=sys.stderr)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    multi = sum(1 for v in out.values() if len(v) > 1)
    print(f"命中 {rows} 行 → {len(out)} 个定额子目（其中 {multi} 个跨多标号）", file=sys.stderr)
    print(f"已写 {a.out}；下一步：pk-norms-export --concrete-map {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
