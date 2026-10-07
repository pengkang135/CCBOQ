#!/usr/bin/env python3
"""装配报价工作台 —— 一条命令做完两件事。

    1. 左侧插 Main Key，右侧整块复刻模板脚手架 + 设置分类定义区
    2. 复制模板的三张透视表页 + UniqueShot（纯机械复制，不理解内容）

原清单一个单元格不改：已有内容整体右移，公式引用跟着平移，drawing / media
字节级保留。原表有多少列、表头在第几行、有没有跑过报价，都不影响 —— 分区边界
靠表头名认，不写死列字母。

两步串一条命令的实际原因是样式：分开跑的话 insert 和 transplant 各 merge 一次
模板 styles.xml，模板样式在产物里存两份、cellXfs 白涨一倍。这里合一次，两步
共用同一个 xf_map。

用法:
    python build_bench.py 清单.xlsx -o 工作台.xlsx
    python build_bench.py in.xlsx -o out.xlsx --sheet CombineBQ --header-row 4
    python build_bench.py in.xlsx -o out.xlsx --no-pivots     # 只插列
"""
import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout
import xlsx_parts as xp
import insert_workbench_cols as ins
import transplant_pivot_pages as piv

TPL_DEFAULT = Path(__file__).resolve().parent.parent / "references/pivot_template.xlsx"


def main():
    ap = argparse.ArgumentParser(description="装配报价工作台：插键列 + 搬透视表")
    ap.add_argument("source")
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--template", default=str(TPL_DEFAULT))
    ap.add_argument("--sheet", help="目标 sheet 名，默认自动认含 Description 的那张")
    ap.add_argument("--header-row", type=int, help="表头行号，默认自动探测")
    ap.add_argument("--tpl-sheet", default=layout.SHEET)
    ap.add_argument("--defined-name", default="分类定义区")
    ap.add_argument("--classification",
                    help="pk-boq-classify 产出的 classification.json，装配时把五个分类列一并写入")
    ap.add_argument("--no-pivots", action="store_true", help="只插列，不搬透视表")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src, out, tplp = Path(a.source), Path(a.output), Path(a.template)
    if not tplp.exists():
        raise SystemExit(f"模板不存在: {tplp}")
    if not src.exists():
        raise SystemExit(f"源文件不存在: {src}")

    with zipfile.ZipFile(src) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    with zipfile.ZipFile(tplp) as z:
        tpl = {n: z.read(n) for n in z.namelist()}
    print(f"源: {src.name}   模板: {tplp.name}")

    if a.dry_run:
        print("── 步骤 1: 插键列 ──")
        ins.apply(parts, tpl, {}, a.sheet, a.header_row, a.tpl_sheet,
                  a.defined_name, a.classification, dry_run=True)
        print("dry-run，未写文件")
        return

    print("── 样式 ──")
    xf_map, dxf_off = ins.merge_template_styles(parts, tpl)

    print("── 步骤 1: 插键列 + 分类定义区 ──")
    r1 = ins.apply(parts, tpl, xf_map, a.sheet, a.header_row, a.tpl_sheet,
                   a.defined_name, a.classification)

    if not a.no_pivots:
        print("── 步骤 2: 搬透视表页 ──")
        piv.apply(parts, tpl, xf_map, dxf_off, r1["sheet"], r1["header_row"],
                  a.defined_name)

    xp.drop_calc_chain(parts)
    ins.write_parts(parts, out)

    st = parts["xl/styles.xml"].decode("utf8")
    print(f"── 完成 ── cellXfs {xp.count_children(st, 'cellXfs', 'xf')[0]}，"
          f"部件 {len(parts)} 个 → {out}")


if __name__ == "__main__":
    main()
