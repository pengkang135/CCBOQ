# Scripts CLI Reference

每个脚本的完整参数列表和使用方式。技能主体（SKILL.md）只保留典型调用示例和关键规则，详细参数查阅本文件。

## merge_boq.py — 单源归一化

```bash
python merge_boq.py <source.xlsx> [-o output.xlsx] [--keep-source-sheets] [--no-outline] [--no-write-blank] [--columns '{"item":1,...}']
```

| 参数 | 说明 |
|------|------|
| `source` | 原始 Excel 文件路径（必填） |
| `-o, --output` | 输出路径（默认：`{source}_merge.xlsx`） |
| `--keep-source-sheets` | 保留原始各 sheet 数据（默认不保留） |
| `--no-outline` | 禁用行分组/折叠 |
| `--no-write-blank` | 跳过空单元格写入，减少 XML 体积 |
| `--columns` | 列映射 JSON：`{"item":1,"desc":2,"unit":3,"qty":4,"data_start":5}`（1-based） |

**功能**：自动检测列布局（描述列/单位列/数量列/单价列/合价列），4 级层级识别（`【】` → `《》` → `{}` → 普通条目），层级配色，数字会计格式 `#,##0.00;-#,##0.00;-`。

**新项目适配**：遇到未知 BOQ 格式时，先运行 `document-ingest` semantic_analysis 确定列映射，再通过 `--columns` 传入。

## compare_boq.py — 清单对比分析

以一份清单为基准，逐项匹配其他类似清单，输出 Markdown 对比报告。

```bash
python compare_boq.py --base <基准> --other <清单2> [--other <清单3> ...] [-o <output.md>] [--project <name>] [--date <YYYY-MM-DD>]
```

| 参数 | 说明 |
|------|------|
| `--base` | 对比基准 BQMerge xlsx |
| `--other` | 其他清单 BQMerge xlsx（可重复指定） |
| `-o, --output` | 输出 .md 路径（默认：`{date}_BOQ_Comparison_Report.md`） |
| `--project` | 项目名称 |
| `--date` | 日期前缀（默认今日） |

**匹配引擎**（三级逐级降级）：精确匹配 → 前缀匹配 → 语义匹配（SequenceMatcher > 0.75）。

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

**qty_col 说明**：WTCC 格式通常工程量在 F 列（0-based = 5），FHDI 格式多在 D 列（0-based = 3）。

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

**完整流程**（PDF→翻译→分类→重评估→交叉引用→影响总结）详见 [qa_processing_pipeline.md](qa_processing_pipeline.md)。

## build_quotation_xlsx.py — 报价资料处理

```bash
# CLI 模式
python build_quotation_xlsx.py --data <data_file.py> [-o output.xlsx] [--title ...] [--subtitle ...]

# Python API 模式
from build_quotation_xlsx import build_xlsx
build_xlsx(ALL_DATA, "output.xlsx", "标题", "副标题")
```

ALL_DATA 格式：8 元组 `(分组, 编码, 专业, 名称, 项目特征, 单价, 日期, 来源)` 或 12 元组 `(分组, 编码, 专业, 名称, 项目特征, 单位, 单价, 日期, 币种, 来源, 供应商, 备注)`。

完整流程详见 [quotation_workflow.md](quotation_workflow.md)。

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

## clean_external_links.py — ZIP/XML 级别清理外部链接

直接操作 xlsx 底层 ZIP/XML，无需 Excel COM 或 openpyxl。彻底清除外部链接和无效定义名称，解决 Excel 打开含大量外部链接文件时卡死/长时间等待的问题。

```bash
python clean_external_links.py <file.xlsx> [-o output.xlsx] [--no-backup]
```

| 参数 | 说明 |
|------|------|
| `input` | 输入 .xlsx 文件路径（必填） |
| `-o, --output` | 输出路径（默认：`{input}_clean.xlsx`） |
| `--no-backup` | 跳过备份（默认自动备份到 `原始备份/` 子目录） |

**清理内容**：
- 删除 `xl/externalLinks/` 目录下所有外部链接文件
- 去除所有含 `#REF!`、`[`、`]`+`!`、绝对路径的外部引用定义名称
- 清理 `xl/_rels/workbook.xml.rels` 等 `.rels` 文件中的 externalLink 关系
- 去除 `xl/workbook.xml` 中的 `<externalReferences>` 元素

**坏名称检测规则**：含 `#REF!/#VALUE!/#N/A/#NAME?/#NUM!/#NULL!/#DIV/0!` 的无效引用；含 `[` 的外部工作簿索引；含 `file://` / `https?://` 的协议引用；含 `\\` 的 UNC 网络路径；含 `X:\` 的 Windows 绝对路径。

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

**典型工作流**：`clean_external_links.py` → `document-ingest` 的 `excel_to_ast.py`，先清理后结构化。

## 拆分询价包 — 图纸分发

无独立脚本，手工流程：文件名关键词搜索 → 编号文件查图纸索引 → 复制保持源层级。详见 [inquiry_package_splitting.md](inquiry_package_splitting.md)。
