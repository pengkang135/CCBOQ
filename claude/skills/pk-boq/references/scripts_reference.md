# Scripts CLI Reference

每个脚本的完整参数列表和使用方式。技能主体（SKILL.md）只保留典型调用示例和关键规则，详细参数查阅本文件。

## merge_boq.py — 单源归一化

```bash
python merge_boq.py <source.xlsx> [-o output.xlsx] [--sheet-regex PATTERN] [--skip PATTERN ...] [--delete-hidden-rows]
```

| 参数 | 说明 |
|------|------|
| `source` | 原始 Excel 文件路径（必填） |
| `-o, --output` | 输出路径（默认：`(YYYY-MM-DD Merge){原文件名}.xlsx`，放源文件同目录） |
| `--sheet-regex` | 识别清单表的 sheet 名正则（默认 `^SCHED(?:ULE)?[\.\s]`） |
| `--skip` | sheet 名跳过关键字，可多个（默认 `SUMMARY LIST COLLECTION "GRAND TOTAL" 汇总 总计`） |
| `--delete-hidden-rows` | 删除隐藏行后继续（不传则检测到隐藏行时停下来报告并退出） |

**功能**：fastexcel 读值 + openpyxl 读样式 + xlsxwriter 输出。识别两类清单表——分部分项（描述+单位+工程量）和开办费/暂列金（描述+金额），按表头名称对齐各表列位（金额列同义词归一），注入 L1【sheet名】标记，去垃圾行，描述列前向填充，工程量+金额分段交叉校验。

**汇总表**：结构与开办费表相同，只能靠 sheet 名排除。遇到 `BILL NO.1`、`RECAP` 这类新命名必须用 `--skip` 补上，否则金额重复计算且校验查不出来。

**格式保留**：底色、字体色、加粗、斜体逐格保留（人工标注靠这些）。字体名/字号统一 9pt Microsoft YaHei UI，边框和行高不保留，由 `pk-boq-hierarchy` 按层级设置。

**性能**：7500 行 5.5 秒，30000 行 20 秒。样式读取用 openpyxl read_only，不是瓶颈。

**列对齐**：按表头文本匹配，无需手动传列映射。表头文本异常（大量空表头）时才需要先跑 `document-ingest` 确认结构。

## compare_boq.py — 清单对比分析

以第一份清单为基准，逐项匹配其余清单，输出 Markdown 对比报告。清单份数不限。

```bash
# 列位相同，走默认列映射
python compare_boq.py --list "A.xlsx|甲方" --list "B.xlsx|乙方" -o 对比报告.md

# 各清单列位不同，逐份指定
python compare_boq.py --list "A.xlsx|甲方" \
                      --list "B.xlsx|乙方|MergeSheet|code=1,desc=2,unit=3,qty=6" \
                      --list "C.xlsx|丙方" --project "某项目"

# JSON 配置模式（sheet 名或路径含中文时推荐，避开命令行编码问题）
python compare_boq.py --config lists.json
```

| 参数 | 说明 |
|------|------|
| `--list` | 清单规格串，可重复；**第一个为对比基准** |
| `--config` | JSON 配置文件路径 |
| `-o, --output` | 输出 .md 路径（默认：`{date}_BOQ_Comparison_Report.md`） |
| `--project` | 项目名称（显示在报告标题） |
| `--date` | 报告日期（默认今日） |
| `-t, --threshold` | 差异高亮阈值百分比（默认 20） |
| `--sim-threshold` | 描述相似度匹配下限（默认 0.75） |
| `--group-re` | 自定义分组提取正则，需含一个捕获组；默认取编码首段 |
| `--top-n` | 关键发现中列出的最大差异项数（默认 10） |

**`--list` 规格串格式**：`path[|label[|sheet[|code=1,desc=2,unit=3,qty=4]]]`

列号 **1-based**，省略的部分用默认值：`sheet=MergeSheet`、`code=1,desc=2,unit=3,qty=4`。
label 省略时取文件名；label 重名自动加 `(2)` 后缀。

**JSON 配置格式**：
```json
{
  "project": "某项目",
  "threshold": 20,
  "output": "对比报告.md",
  "lists": [
    {"file": "A.xlsx", "label": "甲方", "sheet": "MergeSheet",
     "cols": {"code": 1, "desc": 2, "unit": 3, "qty": 5}},
    {"file": "B.xlsx", "label": "乙方", "sheet": "MergeSheet"}
  ]
}
```
`cols` 只需写与默认值不同的键。CLI 上的 `--list` 会追加在 config 的 lists 之后。

**匹配引擎**（三级逐级降级）：精确编码匹配（置信 1.0）→ 父级编码前缀匹配（0.85）→ 描述相似度匹配（SequenceMatcher，低于 `--sim-threshold` 则判为未匹配）。候选集按「分组 + 小节前两级」分桶，桶内无候选时逐级回退到整个分组。

**分组识别**：优先按 pk-boq 层级符号 `【】` 认 L1 分组、`《》`/`{}` 认小节；清单没打层级符号时，才退回形态推断（无单位无数量 + 编码是单段短记号如 `B`、`F3`、`12`）。条目一律沿用上方分组，不自行推断——否则编码列里填的 `ADD`、`RunWay` 这类说明词会各自伪造出一个分组。整份清单一个分组标题都没有时，自动按条目编码首段分组。

**ADD 项**：编码含 `ADD` 记号（`B.2.9ADD`、`ADD` 均可，`ADDITIONAL` 不算）的条目视为基准清单外新增项，匹配时剥离该记号，报告中单独统计。

## check_boq_consistency.py — 清单一致性校验

```bash
# JSON 配置模式（推荐，避免中文 sheet 名编码问题）
python check_boq_consistency.py target.xlsx --config mappings.json

# 显式映射模式
python check_boq_consistency.py target.xlsx \
    -m "TargetSheet|source.xlsx|SourceSheet|5" \
    -m "TargetSheet2|source2.xlsx|SourceSheet2|3"

# 自动匹配模式（sheet 名相同时）
python check_boq_consistency.py target.xlsx source.xlsx --qty-col 5
```

| 参数 | 说明 |
|------|------|
| `target` | 待校验的目标 BOQ 文件（必填） |
| `source` | 单个源文件（自动匹配模式） |
| `-m, --map` | 映射规则：`TargetSheet\|source.xlsx\|SourceSheet\|qty_col` |
| `--config` | JSON 配置文件路径（推荐） |
| `--qty-col` | 工程量所在列索引（0-based） |
| `-t, --threshold` | 差异阈值（默认 1.0） |
| `--json` | JSON 格式输出 |

**JSON 配置格式**：
```json
{
  "threshold": 1.0,
  "mappings": [
    {"target_sheet": "E_Quay(OP1) WTCC", "source_file": "wtcc_boq.xlsx", "source_sheet": "E_Quay(OPT. 1)", "qty_col": 5}
  ]
}
```

**qty_col 说明**：0-based。各家清单列位不同且会随版本变动（同一来源的新旧两版工程量列都可能挪位），**动手前必须先 dump 前 100 行确认表头**，不要沿用上次的列号。带单价的清单常有「设计工程量」「报价工程量」两列，注意取的是哪一列。

## mark_boq_three_color.py — 三色差异标记

把新版清单相对旧版合并清单的变更，用红/黄/绿三色标到旧版副本（绿新增/黄修改/红删除）。

```bash
python mark_boq_three_color.py --base <旧版合并BOQ> --new <新版清单> \
    --base-cols desc=5,unit=6,qty=7 --new-cols desc=3,unit=4,qty=5 \
    [--base-sheet 合并报表] [--new-sheet MergeSheet] [-o out.xlsx] [--dry-run] [--json diff.json]
```

| 参数 | 说明 |
|------|------|
| `--base` | 基准清单（旧版合并 BOQ，干净旧版，必填） |
| `--new` | 对比清单（新版设计院清单，必填） |
| `--base-sheet` | 基准 sheet 名（默认 `合并报表`） |
| `--new-sheet` | 新版 sheet 名（默认 `MergeSheet`） |
| `--base-cols` | 基准列映射 `desc=5,unit=6,qty=7`（1-based，qty 可省） |
| `--new-cols` | 新版列映射 `desc=3,unit=4,qty=5`（1-based） |
| `-o, --output` | 输出副本（默认 `{base}_三色变更.xlsx`） |
| `--dry-run` | 只 diff 不写文件，打印三色清单 |
| `--json` | diff 结果 JSON（modify/new/delete 三数组） |
| `--l2-extra` | 基准里需归并的额外 L2 名（逗号分隔，归一化后） |
| `--l2-merge-to` | `--l2-extra` 归并到的新版 L2 名（归一化后） |

**三色语义**：绿 `0x00FF00`=新增（整行插入）、黄 `0x00FFFF`=修改（改单位/工程量）、红 `0x0000FF`=删除（标红不删）。判定：qty/单位实质变化→黄；名称同义仅翻译差异→不改；新版独有→绿；基准独有→红。

**插入**：`xlsx_rowops.SheetEditor.insert_row(after=原行号)`，zip/XML 层不启动 Excel，公式行引用自动平移。行号按原表给，多处插入的偏移内部统一算。禁止 openpyxl `insert_rows`（破坏公式）。

方法论详见 [three_color_diff.md](three_color_diff.md)。

## match_boq_prices.py — 清单价格匹配（产出结构化 JSON）

源报价清单 vs 目标清单，编号精确 → desc 归一化（region 分桶）三级降级，产出 `fill/conflict/multi/none/target_only` 结构化 JSON。匹配结果只算一次，供 `fill_boq_prices.py` 回填和对比分析复用。

```bash
python match_boq_prices.py --source 源报价.xlsx --target 目标表.xlsx --out match.json \
    --src-cols item=2,desc=3,unit=4,qty=5 \
    --src-extra rate=7,total=15 \
    --tgt-cols item=2,desc=3,unit=4,qty=5
```

| 参数 | 说明 |
|------|------|
| `--source` | 源报价清单 xlsx（必填） |
| `--target` | 目标清单 xlsx（必填） |
| `--out` | 输出匹配 JSON 路径（必填） |
| `--src-cols` | 源列映射（**1-based**），必填，需含 item/desc/unit/qty |
| `--tgt-cols` | 目标列映射（**1-based**），必填，同上 |
| `--src-extra` | 源额外列（供 multi/none 人审看价格），`label=列号` 逗号分隔 |
| `--src-sheet` / `--tgt-sheet` | sheet 名（默认各自第一个） |

**输出字段**：`fill`（自动配对，直接回填）、`conflict`（同编号 desc 不符）、`multi`（一源对多目标）、`none`（源无对应）、`target_only`（目标独有）。后四类是人工审查区，裁决写进 **`decisions.json`** 交给 `fill_boq_prices.py`，不要改脚本。

**列号基准**：本技能族全部脚本统一 **1-based**（A 列 = 1）。传 <1 的值会直接报错；列号越界或读不到条目也会报错而非静默读错列。

## fill_boq_prices.py — 清单价格回填

按 `match_boq_prices.py` 的 JSON + `decisions.json` 人工裁决，把源报价写到目标表预留列，总额对齐校验通过才写盘。

```bash
python fill_boq_prices.py --source 源报价.xlsx --target 目标表.xlsx --match match.json \
    --decisions decisions.json \
    --src-cols item=2,desc=3,unit=4,qty=5,rate=7,labour=8,plant=9,mat=10,sub=11,others=12,offsite=13,headoffice=14,total=15 \
    --tgt-cols qty=17,rate=18,labour=19,plant=20,mat=21,sub=22,others=23,offsite=24,headoffice=25,total=26 \
    --expect-total 17323515.97539893 --dry-run
```

| 参数 | 说明 |
|------|------|
| `--source` | 源报价清单 xlsx（必填） |
| `--target` | 目标成本测算表 xlsx（必填，就地回填并自动备份） |
| `--match` | `match_boq_prices.py` 产出的 JSON（必填） |
| `--decisions` | 人工裁决 JSON，跟项目走。**不传即无裁决**（新项目首跑的正确初值） |
| `--src-cols` | 源列映射（**1-based**），必填，需含 item/desc/unit/qty 及各成本科目 |
| `--tgt-cols` | 目标预留列区（**1-based**），必填，需含 qty/total |
| `--tgt-key-cols` | 目标表键列（1-based），默认 `item=2,desc=3,unit=4,trueqty=5` |
| `--sheet` | 源表 sheet 名（默认第一个） |
| `--expect-total` | 期望总额。**写盘必须传**且差额在容差内；`--dry-run` 时可省 |
| `--dry-run` | 只统计不写文件 |

**decisions.json 结构**（全部键可选，缺省即空）：

```json
{
  "_target": "目标表文件名.xlsx",
  "manual_fill":       [["源编号", "目标编号"]],
  "green_fill":        ["源编号"],
  "green_fill_offset": [["源编号", "目标编号"]],
  "green_insert":      ["源编号"],
  "insert_desc":       {"源编号": "目标desc前缀"},
  "item0_desc":        {"源编号": "源desc前缀"},
  "skip_src":          ["源编号"],
  "special":           [["src来源", "src键", "tgt类型", "tgt键"]]
}
```

| 键 | 用途 |
|----|------|
| `manual_fill` | 编号漂移的显式配对，覆盖自动匹配 |
| `green_fill` / `green_fill_offset` | 源叶子填到目标同编号的标题行（编号精确匹配漏掉的），标绿 |
| `green_insert` | 源有目标无，填到目标已存在的对应行 |
| `insert_desc` | 编号重复时（插入行与原行同号）用 desc 消歧定位 |
| `item0_desc` | 源 item 误填为 `'0'` 时按 desc 前缀兜底 |
| `skip_src` | 跳过自动匹配的误配项，改由 `special` 显式定位 |
| `special` | item 空 / unit 空叶子的定位。`src来源`: item/desc/unit_empty，`tgt类型`: item/desc |

`_target` 是可选的绑定声明：与 `--target` 文件名不符时会告警——裁决表绑定具体项目的编号体系，跨项目复用会把毫不相干的两项强行配对。

**三道写盘闸门**：① `--expect-total` 写盘时必填；② 差额超容差（`max(0.01, 期望×1e-9)`，避免上万条 float 累加的 1e-8 级噪音被误判）拒绝写盘；③ 同一目标行被多次填写（decisions 与自动匹配重复配对，或 decisions 张冠李戴）直接终止。另有启发式告警：裁决表条目大面积落空时提示可能不属于本项目。

陷阱详见 pk-boq-compare 技能「已知陷阱」。

## extract_boq_by_keyword.py — 按关键字提取BOQ子清单

```bash
python extract_boq_by_keyword.py <source.xlsx> <keyword> <template.xlsx> [-o output.xlsx]
```

| 参数 | 说明 |
|------|------|
| `source` | 合并后的 BOQ xlsx（必填，16 列 A-P） |
| `keyword` | 搜索关键词，大小写不敏感，匹配 B 列 |
| `template` | 样式模板 xlsx（CHEC_BOQ_BreakDown_Templete.xlsx） |
| `-o, --output` | 输出路径（默认：`{date}_BOQ_{keyword}.xlsx`） |

**层级保留**：自动识别 5 级层次结构（Section delimiter → Class header → Sub-section → Item → Sub-item）。openpyxl 实现（非 xlsxwriter），因为需要读取源文件数据且模板有合并表头。

## build_inquiry_materials.py — 主材表提炼/市场询价表生成

三阶段流水线（Phase 1 提取 → Phase 2 合并归类 → Phase 3 格式化）：

```bash
# 完整三阶段
python build_inquiry_materials.py --source <BOQ.xlsx> --config <config.json> \
    --template <模板.xlsx> -o <输出目录>

# 配合 document-ingest 自动检测列映射（新项目推荐）
python build_inquiry_materials.py --source <BOQ.xlsx> --config <config.json> \
    --ast <semantic_analysis.json> --template <模板.xlsx> -o <输出目录>

# 分阶段运行
python build_inquiry_materials.py --source <BOQ.xlsx> --config <config.json> --phase 1
python build_inquiry_materials.py --items <items.json> --config <config.json> --phase 2
python build_inquiry_materials.py --consolidated <consolidated.json> --config <config.json> \
    --template <模板.xlsx> --phase 3
```

| 参数 | 说明 |
|------|------|
| `--source` | BOQ Excel 源文件（Phase 1 必填） |
| `--config` | JSON 配置文件（必填） |
| `--ast` | document-ingest semantic_analysis JSON，自动检测列映射（Phase 1） |
| `--template` | 参考模板 xlsx（Phase 3 必填） |
| `-o, --output` | 输出目录（默认当前目录） |
| `--phase` | 1/2/3 或省略=全部 |
| `--items` | Phase 1 输出 JSON |
| `--consolidated` | Phase 2 输出 JSON |
| `--title` | Excel 标题覆盖 |
| `--no-md` | 跳过 MD 输出 |
| `--no-xlsx` | 跳过 xlsx 输出 |

**配置文件格式**和**归类规则**详见 [consolidation_rules.md](consolidation_rules.md)，**完整工作流**详见 [material_inquiry_workflow.md](material_inquiry_workflow.md)。

## question_to_designer.py — 疑问函生成器

Python API 模式（非 CLI），两阶段：MD 中文版 → Excel 英文版。

```python
from question_to_designer import QuestionConfig, build_question_xlsx
config = QuestionConfig(project_name="...", employer="...", ...)
sections = [{"title": "【Section 1 ...】", "items": [...]}, ...]
build_question_xlsx(config, sections, "output.xlsx")
```

**写作规则**：Attachment Ref. 写文件名或报告章节号；Question 简明扼要不写 OM/DI 编号；Ask By 固定 "Peng Kang"；数量比较用设计清单量 vs 设计报告量（同源），不比招标清单。

## qa_classify.py — 答疑分类汇总生成器

```bash
# 双回复方模式
python qa_classify.py file1.md file2.md -o output_dir --project "Project Name" --prefix "20250423_"

# 单回复方模式
python qa_classify.py file1.md -o output_dir --project "Project Name"
```

**输入格式**：Markdown 表格，列顺序 `Item | Query Ref | Question (EN) | Answer (EN) | Question (CN) | Answer (CN)`

**5 大分类**：商务/合同条款、技术/设计、范围/界面、施工组织/现场条件、投标文件/程序。成本影响标签：高/中/低。

## build_quotation_xlsx.py — 报价资料处理

```bash
# CLI 模式
python build_quotation_xlsx.py --data <data_file.py> [-o output.xlsx] [--title ...] [--subtitle ...]

# Python API 模式
from build_quotation_xlsx import build_xlsx
build_xlsx(ALL_DATA, "output.xlsx", "标题", "副标题")
```

ALL_DATA 格式：8 元组 `(分组, 编码, 专业, 名称, 项目特征, 单价, 日期, 来源)` 或 12 元组 `(分组, 编码, 专业, 名称, 项目特征, 单位, 单价, 日期, 币种, 来源, 供应商, 备注)`。

数据格式与 PDF→MD 整理规范详见 [quotation_xlsx_format.md](quotation_xlsx_format.md)。
**报价单入库不走这个脚本** —— 入库的唯一链路是 `pk-boq-quotation` 技能。

## split_inquiry_boq.py — 拆分询价包 BOQ 清单

```bash
python scripts/split_inquiry_boq.py \
    --template "combine.xlsx" \
    --source "WTCC.xlsx" --label WTCC \
    --source "FHDI.xlsx" --label FHDI --fix-ref "1" \
    --match "E_Quay" \
    --output "output.xlsx"
```

完整工作流详见 [inquiry_package_boq.md](inquiry_package_boq.md)。

## 清理外部链接 / 净化名称 — `xlsx-purge` 技能

不在本技能内实现，路由到 `xlsx-purge`。定义名称净化与外部链接清除是分开的两件事：

```bash
python <xlsx-purge>/scripts/xlsx_purge.py "file.xlsx" out.xlsx --mode names|links|all
```

`names` 只清名称不动公式，`links` 断外链并把引用外链的公式转值，`all` 两者都做。

## xlsx_to_ast — 语义 Excel-AST 转换（document-ingest 技能）

由 `document-ingest` 技能提供，将 xlsx 转为 JSON AST。三种模式：`workbook_summary`（sheet 元数据）、`sheet_ast`（cell 级 AST 含坐标/公式/样式角色）、`semantic_analysis`（自动识别表头树、数据区域、汇总行、公式列）。

```bash
python excel_to_ast.py "input.xlsx" --mode workbook_summary
python excel_to_ast.py "input.xlsx" --mode sheet_ast --sheet "Sheet1" --max-rows 200 -o ast.json
python excel_to_ast.py "input.xlsx" --mode semantic_analysis --sheet "Sheet1" -o semantic.json
```

| 参数 | 说明 |
|------|------|
| `input` | 输入 .xlsx 文件路径（必填） |
| `--mode` | `workbook_summary` / `sheet_ast` / `semantic_analysis` |
| `--sheet` | 目标 sheet 名 |
| `--range` | 限定区域，如 `A1:Z500` |
| `--max-rows` | 最大数据行数 |
| `-o` | 输出 JSON 路径 |

输出为 JSON 格式（非 Markdown），保留公式、合并单元格、数字格式、style_role 等完整语义信息。完整 schema 见 `document-ingest` 的 `references/ast_schema.md`。

**典型工作流**：`xlsx-purge`（`--mode links`）→ `document-ingest` 的 `excel_to_ast.py`，先清理后结构化。

## 拆分询价包 — 图纸分发

无独立脚本，手工流程：文件名关键词搜索 → 编号文件查图纸索引 → 复制保持源层级。详见 [inquiry_package_splitting.md](inquiry_package_splitting.md)。
