---
name: pk-boq-workbench
description: "在已有 BOQ 清单上装配报价工作台：左侧插 Main Key 键列，右侧整块追加报价脚手架（EXPORT/COST/AI/SUBCONTRACTOR 四组，含 Discipline/SortKey/Category/Subcategory/Element 五个分类列、BQ KEY/CleanDescription 两个键列、Norm Rate/Norm Amount/Ref Rate/Ref Amount 四个套价列），并带入三张透视表（CostSummary/MainQty/UniqueBQ）和 UniqueShot 快照页。原清单只增不改。为 AI 套价、AI 套定额准备脚手架。触发词：建工作台、套模板、报价工作台、插入工作台、装配工作台、加分类列、BOQ 模板。上游顺序：无分级符号先调 pk-boq-hierarchy，分类值由 pk-boq-classify 产出 classification.json 后用 --classification 一并写入。"
license: Proprietary. LICENSE.txt has complete terms
---

# pk-boq-workbench — 报价工作台装配

> **禁止用 Excel COM 处理表格**（全局硬规则，见 `~/.claude/CLAUDE.md`）。本技能全程 zip/XML 层字符串拼接，不起 Excel，也**不用 ElementTree 序列化任何已有部件**（会毁命名空间导致 Excel 拒开）。

技能族里的位置：`pk-boq-hierarchy` 打层级符号 → `pk-boq-classify` 产出 `classification.json` → **本技能装配工作台** → `pk-boq-db-match` / `pk-norms-match` 套价。本技能只管结构，不判断任何条目属于哪个分部。

## 装配

```bash
python scripts/build_bench.py <清单.xlsx> -o <工作台.xlsx> \
    [--classification classification.json] \
    [--sheet CombineBQ] [--header-row 3] [--no-pivots]
```

一条命令做完两件事：插列 + 搬透视表。目标 sheet 和表头行默认自动探测（找含 `Description` 的那行），认不出再显式指定。

```
[Main Key][ 源清单原有列 ][ ←———————— 整块追加的报价脚手架 ————————→ ]
   左插1列     只增不改       EXPORT │ COST │      AI       │ SUBCONTRACTOR
                             Factor   Labor   Discipline..     Labor
                             Labor    ..      Element          ..
                             ..       Amount  BQ KEY           Amount
                             Amount           CleanDescription
                                              Norm/Ref Rate+Amount
```

**只有一种情形。** 源清单只需提供 `No.` / `Description` / `Unit` / `Qty`（`Quantity` 也认），脚手架一律整块追加在最右侧。原来分「自带报价列」和「只到 Quantity」两种做法，已经合并。

**分区边界靠 r1 的分组标签认，不是列字母。** 脚手架内部按模板列序整块复刻 —— `Labor`/`Material`/`Equipment`/`Rate`/`Amount` 在三组里各出现一次，按列名挑列会有一整组丢表头。

**原清单只增不改。** 已有内容整体右移，公式引用跟着平移，drawing / media / 图表字节级保留 —— 已完成的报价、breakdown 明细和图片洗掉没法补。

**分类在装配之前。** 三张透视表按 Discipline / SortKey / Category 分组汇总，分类列空着刷出来只有 `(空白)`。先跑 `pk-boq-classify` 拿到 `classification.json`，用 `--classification` 一次成型。分类值按 `src_row` 落行、用 `desc_head` 断言不错位，对不上就整批拒绝写入并逐行报差异。不传就把分类列留空（半成品，后面还得补）。

源清单缺 `Description` / `Unit` / `Qty` 里任何一个会直接报错停下 —— 模板样板公式引用这几列，对不上就会留着模板列字母指到别的列去，产物看着正常但数是错的。

## 交付检查

```bash
python scripts/verify_workbook.py <工作台.xlsx> --stage build
```

`--stage build` 只验结构（分类五列此时可以是空的）；整条链路走完之后用默认的 `--stage full` 再验一次。全过退出码 0，有 FAIL 退出码 1。期望结构从模板实时读，不写死。

脚本另外会打印**需要人确认、不判对错**的值：表头行上方的放大系数（模板里 `G2`/`H2`/`I2`=1.23、`AE2`=1.05、`AG2`=0.07），以及 r1 的四个分组标签。系数从模板继承，换项目必须核对。

**收工前跑一遍，输出原样贴出来**，别自评"已完成"。

## 脚本

| 脚本 | 用途 |
|------|------|
| `build_bench.py` | **入口**：插列 + 搬透视表，样式只合并一次 |
| `insert_workbench_cols.py` | 插列本体：键列右移平移、分类列和 AI 列追加、分类定义区。可单独跑 |
| `transplant_pivot_pages.py` | 搬页本体：模板三张透视表页 + UniqueShot 整包搬入。可单独跑 |
| `xlsx_parts.py` | 共用底层：样式合并、sharedStrings 偏移、sheet 路径解析、定义名称、死公式清理 |
| `layout.py` | 行列布局的唯一事实源。**权威版在这里**，`pk-boq-classify/scripts/layout.py` 是迁移期副本，改动要同步 |
| `verify_workbook.py` | 交付检查，逐项 PASS/FAIL |
| `build_workbook.py` | 另一条路：以模板为基底重建，**只适用于裸清单，会丢弃原清单其余内容**。按 Description 的层级标记认样板行 |
| `temp/scripts/regression.py` | 回归测试：三种形态样本 + 三条独立判据 |

公式和样式全部从 `references/pivot_template.xlsx` 实时取 —— 键列的 LET 公式、Norm/Ref Rate 的 VLOOKUP、各列的 s 值都不写死在代码里，模板改版脚本自动跟随。行列几何集中在 `layout.py`（sheet 名、表头行、数据起始行、分组标签、列名别名）。

改脚本之前先读它们的 docstring：命名空间、dxf numFmt 自映射、tableStyles 漏搬、worksheetSource 悬空引用、s 值重映射、样板行锚点这些坑都记在那里，每条都对应过一次打不开的交付。

遗留不再使用：`setup_pivots.py`（`merge_styles` 用 `ET.tostring` 序列化 styles.xml 会毁命名空间，导致 Excel 拒开——不要复活它）。

## 装完之后

| 落点 | 位置 | 说明 |
|------|------|------|
| 五个分类列 | `Discipline` / `SortKey` / `Category` / `Subcategory` / `Element` | 没传 `--classification` 的话交给 `pk-boq-classify` 补 |
| BQ KEY | `BQ KEY` | `SortKey` + `|` + `CleanDescription` 哈希，形如 `A.01|64658`。**依赖分类已填**，全链路靠它对齐 |
| UniqueShot | 快照页 | 按 BQ KEY 去重后的作业面，唯一值行由套价技能生成 |
| Norm Rate | `Norm Rate` | `VLOOKUP(BQ KEY → UniqueShot)`，偏移量用 `COLUMN()` 算，增删列不断 |
| Ref Rate | `Ref Rate` | 同上，但**偏移量 5 写死**，改快照页列序必须同步改 |
| 四口径对比 | EXPORT / COST / AI / SUBCONTRACTOR 四组的 `Amount` | CostSummary 透视表横向比 |

**一律按表头名定位，不要按列字母。** 输出新文件，源清单不修改。

完整列布局、行类型公式矩阵、样板行机制见 `references/column_spec.md`（机读版 `references/column_template.json`）。

模板本体 `references/pivot_template.xlsx` 是**只读资产**：用 Excel 打开再保存会重写 sheet XML，还会带进外部链接和垃圾定义名称。确需改布局时按 `column_spec.md`「模板维护规则」走 —— 先跑 `references/temp/scripts/fix_template.py` 净化，再在 Excel 里刷新透视表重存（`cacheFields` 只有 Excel 能重建），然后跑 `temp/scripts/regression.py`。

**模板当前有一处已知公式错误**：L1 行的 `Ref Amount` 汇总的是 COST 组的 `Amount`（`$Q:$Q`）而不是自己（`AB:AB`），详见 `column_spec.md`「模板已知问题」。
