# Scripts CLI Reference

每个脚本的完整参数列表和使用方式。技能主体（SKILL.md）只保留典型调用示例和关键规则，详细参数查阅本文件。

## merge_boq.py — 单源归一化

```bash
python merge_boq.py <source.xlsx> [-o output.xlsx] [--keep-source-sheets] [--no-outline] [--no-write-blank]
```

| 参数 | 说明 |
|------|------|
| `source` | 原始 Excel 文件路径（必填） |
| `-o, --output` | 输出路径（默认：`{source}_merge.xlsx`） |
| `--keep-source-sheets` | 保留原始各 sheet 数据（默认不保留） |
| `--no-outline` | 禁用行分组/折叠 |
| `--no-write-blank` | 跳过空单元格写入，减少 XML 体积 |

**功能**：自动检测列布局（描述列/单位列/数量列/单价列/合价列），4 级层级识别（`【】` → `《》` → `{}` → 普通条目），层级配色，数字会计格式 `#,##0.00;-#,##0.00;-`。

## compare_boq.py — 多院对比分析

```bash
python compare_boq.py --wtcc <base> --fhdi <other1> --sghcc <other2> [-o <output.md>] [--project <name>] [--date <YYYY-MM-DD>]
```

| 参数 | 说明 |
|------|------|
| `--wtcc` | 对比基准 BQMerge xlsx |
| `--fhdi` | 第二个设计院的 BQMerge xlsx |
| `--sghcc` | 第三个设计院的 BQMerge xlsx |
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

## merge_all_institutes.py — 全量合并汇总

```bash
python merge_all_institutes.py --wtcc <base> --fhdi <other1> --sghcc <other2> --tender <path> [-o <output.xlsx>] [--date <YYYY-MM-DD>]
```

| 参数 | 说明 |
|------|------|
| `--wtcc` | 模板基准 BQMerge xlsx |
| `--fhdi` | 第二个设计院的 BQMerge xlsx |
| `--sghcc` | 第三个设计院的 BQMerge xlsx |
| `--tender` | 招标标准清单 xlsx |
| `-o, --output` | 输出路径（默认：`{date}_BOQ_Merged_All_Institutes.xlsx`） |
| `--date` | 日期前缀（默认今日） |

**输出列**：`Item | Description | Unit | 招标标准清单 | 院A Design | 院A Bid | 院B方案一 | 院B方案二 | 院C | Main Specification`

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

# 分阶段运行
python build_inquiry_materials.py --source <BOQ.xlsx> --config <config.json> --phase 1
python build_inquiry_materials.py --items <items.json> --config <config.json> --phase 2
python build_inquiry_materials.py --consolidated <consolidated.json> --config <config.json> \
    --template <模板.xlsx> --phase 3
```

| 参数 | 说明 |
|------|------|
| `--source` | 设计院 BOQ Excel（Phase 1 必填） |
| `--config` | JSON 配置文件（必填） |
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

## 拆分询价包 — 图纸分发

无独立脚本，手工流程：文件名关键词搜索 → 编号文件查图纸索引 → 复制保持源层级。详见 [inquiry_package_splitting.md](inquiry_package_splitting.md)。
