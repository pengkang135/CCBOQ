---
name: excel-ast
description: "Convert Excel files to/from a structured JSON AST representation that preserves formulas, merged cells, number formats, and semantic structure. Use when: reading or analyzing a large existing Excel file, understanding spreadsheet layout and structure, making targeted modifications to existing workbooks, extracting data from specific regions, or when MCP-based Excel reading is too slow. Supports selective sheet/range extraction, semantic region detection (headers, data tables, summary rows), and surgical write-back of modifications."
---

# Excel-AST: Semantic Excel Processing via JSON AST

将 Excel 文件转为带坐标和语义的 JSON AST，在中间件上分析和修改，再精准写回。

**核心区别**: xlsx skill 面向「创建新文件」和「直接编辑」，excel-ast 面向「理解大型现有文件结构」和「精准修改」。两者互补。

## Trigger Quick Reference

| 用户意图 | 脚本 / 模式 | 说明 |
|----------|------------|------|
| 了解 Excel 结构、列出 sheet | `excel_to_ast.py --mode workbook_summary` | 仅元数据，极低 token |
| 读取 sheet 数据、查看单元格 | `excel_to_ast.py --mode sheet_ast --sheet "Sheet1"` | 完整 cell 级 AST |
| 分析表头层级、表格区域、汇总行 | `excel_to_ast.py --mode semantic_analysis` | 自动识别语义区域 |
| 修改现有 Excel 单元格 | 三步流程: 提取 → 编写修改计划 → 写回 | 参见下方 Workflow |
| 限定范围读取 | 加 `--range "A1:Z500"` 或 `--max-rows 200` | 大文件必须 |
| 预览修改效果 | `ast_to_excel.py --dry-run` | 不实际写入 |

## Decision Tree

```
用户说"我有一个Excel文件..."
  │
  ├── "想快速看看里面有什么"
  │   └── excel_to_ast.py --mode workbook_summary
  │
  ├── "读某个 sheet 的数据/单元格内容"
  │   └── excel_to_ast.py --mode sheet_ast --sheet "XXX"
  │       ├── 文件很大? 加 --max-rows 500
  │       └── 只要某区域? 加 --range "A1:Z1000"
  │
  ├── "帮我分析表头/表格/汇总/公式结构"
  │   └── excel_to_ast.py --mode semantic_analysis
  │       └── 基于 semantic.regions 和 header_tree 推理
  │
  └── "帮我修改某些单元格"
      ├── Step 1: excel_to_ast.py 提取 AST 了解结构
      ├── Step 2: 编写 modification_plan.json
      └── Step 3: ast_to_excel.py --plan plan.json -o output.xlsx
```

## Core Workflow (Three Steps)

### Step 1: Extract AST

```bash
# 快速概览
python scripts/excel_to_ast.py "input.xlsx" --mode workbook_summary

# 读取特定 sheet（大文件务必加筛选）
python scripts/excel_to_ast.py "input.xlsx" --mode sheet_ast \
    --sheet "Sheet1" --max-rows 200 -o ast.json

# 语义分析（自动识别表头树、数据区域、汇总行）
python scripts/excel_to_ast.py "input.xlsx" --mode semantic_analysis \
    --sheet "Sheet1" -o semantic.json
```

输出是 JSON —— 直接在上下文中阅读和分析。

### Step 2: Build Modification Plan

基于 AST 分析结果，编写修改计划 JSON：

```json
{
  "source_file": "input.xlsx",
  "changes": [
    {
      "sheet": "Sheet1",
      "cell": "E12",
      "old_value": 42.5,
      "new_value": 45.0,
      "reason": "更新单价"
    },
    {
      "sheet": "Sheet1",
      "cell": "F12",
      "new_value": "=E12*1.15",
      "reason": "更新公式引用新的单价"
    }
  ]
}
```

- `old_value` 可选，提供后会做校验
- `new_value` 是 `"=..."` 开头则视为公式
- 只写要改的单元格，5 万行文件改 5 个格子只需 20 行 JSON

### Step 3: Apply

```bash
# 预览（推荐先做）
python scripts/ast_to_excel.py "input.xlsx" --plan plan.json --dry-run

# 执行
python scripts/ast_to_excel.py "input.xlsx" --plan plan.json \
    -o output.xlsx --backup
```

## Output Modes

| 模式 | 命令 | 输出大小 | 适用场景 |
|------|------|---------|---------|
| `workbook_summary` | `--mode workbook_summary` | ~0.5-2 KB | 第一步了解文件结构 |
| `sheet_ast` | `--mode sheet_ast` | ~1-5 KB/100 cells | 需要看到具体单元格数据 |
| `semantic_analysis` | `--mode semantic_analysis` | ~3-10 KB | 需要理解表格布局和语义 |

## Safety Rules

修改时必须遵守（`ast_to_excel.py` 会自动检查）：

1. **不破坏公式** — 覆盖公式 → 非公式值会产生警告，需 `--force`
2. **不移除合并单元格** — 写回后合并区域数不得减少
3. **不大批量重写** — 修改超过 5% 单元格会有警告
4. **不重排行/列** — 不暴露 insert/delete 操作
5. **不覆盖原文件** — `-o` 必须指定输出路径
6. **保留 VBA** — `keep_vba=True` 加载和保存

## Large File Strategies

处理大 Excel 文件时的最佳实践：

```bash
# 第一步：只看结构
python scripts/excel_to_ast.py "big.xlsx" --mode workbook_summary

# 第二步：只看目标 sheet 的前 200 行
python scripts/excel_to_ast.py "big.xlsx" --mode sheet_ast \
    --sheet "TargetSheet" --max-rows 200

# 第三步：只看特定区域
python scripts/excel_to_ast.py "big.xlsx" --mode sheet_ast \
    --sheet "TargetSheet" --range "A1:K500"

# 第四步：语义分析同一区域
python scripts/excel_to_ast.py "big.xlsx" --mode semantic_analysis \
    --sheet "TargetSheet" --range "A1:K500"
```

原则：**先探测、再限定、逐步放大**。不要一次读出所有单元格。

## ast_to_excel.py Options

| 选项 | 说明 |
|------|------|
| `--plan PLAN` | 修改计划 JSON 路径（必须） |
| `-o OUTPUT` | 输出路径（必须，不覆盖原文件） |
| `--dry-run` | 预览变更内容，不写入 |
| `--backup` | 写入前备份原文件为 `*_backup.xlsx` |
| `--force` | 忽略 non-fatal 警告继续执行 |

## Error Handling

| 错误级别 | 行为 |
|----------|------|
| `ERROR` | 阻塞：sheet 不存在、cell 无效、plan 格式错误。不会写入。 |
| `WARN` | 非阻塞但需 `--force`：公式覆盖、old_value 不匹配、合并单元格内写入、重复 cell |
| `SAFETY` | 写后检查失败：公式数量下降、合并区域减少、修改比 >5%。需 `--force`。 |

## Cross-Skill References

| Skill | 关系 |
|-------|------|
| `xlsx` | 创建新 Excel、添加格式、pandas 分析。本 skill 面向「理解+修改现有文件」。 |
| `pk-boq` | BOQ 专用处理流程。可配合 excel-ast 做前置的 Excel 结构理解。 |
| `thinking-in-files` | 复杂多步修改建议先用 thinking-in-files 规划，再生成修改计划。 |

## Reference

完整 AST Schema 定义见 [references/ast_schema.md](references/ast_schema.md)，包含所有模式输出的字段规范、修改计划格式、验证规则和安全不变量。
