---
name: document-ingest
description: "统一文档处理入口：将任意办公文档转为 AI 可读的中间格式。Excel 简单 → Markdown，复杂 → JSON AST；PDF/DOCX → Markdown；图片 → OCR 文本。所有 Markdown 产物统一用 baoyu-format-markdown 美化。触发词：文档转换、中间格式、Excel AST、Excel 转 Markdown、文档结构化。"
---

# 文档处理（统一入口）

将任意办公文档转为 AI 易读的中间格式。原则是**怎么方便 AI 阅读怎么来**：能用 Markdown 就用 Markdown，非结构化不下才回到 JSON AST。

## 路由规则

| 输入 | 输出 | 工具 |
|------|------|------|
| `.pdf` | Markdown | `pdf` skill 或 `pdf2md` MCP |
| `.docx` | Markdown | `docx` skill 或 `pandoc` MCP |
| `.png` / `.jpg` / `.bmp` | 文本 | `rapid-ocr` MCP |
| `.xlsx` / `.xlsm` / `.xls` | **见下方判定** | 本 skill 脚本 |

**所有生成的 `.md` 文件转换完成后，统一调用 `baoyu-format-markdown` skill 美化一次。**

## 中间文件放置规则（强制）

所有转换产物放在**源文件所在目录**（与源文件同目录）：

- `招标文件.docx` → `招标文件.md`
- `报价清单.xlsx` → `报价清单.md`（简单）或 `报价清单_ast.json`（复杂）
- PDF/图片同理

不得创建 `output/`、`converted/`、`md_output/` 等集中目录，也不得放到 `temp/`。

## Excel 判定：MD 还是 AST

**第一步永远是先跑 `workbook_summary`** — 成本极低，据 `route_hint` 字段直接判断：

```bash
python scripts/excel_to_ast.py "input.xlsx" --mode workbook_summary
```

输出会包含：

```json
{
  "workbook": {
    "file_size_bytes": 45120,
    "visible_sheet_count": 1,
    "has_merged_cells": false,
    "has_formulas": false,
    "route_hint": { "target": "markdown", "reasons": [] },
    "sheets": { ... }
  }
}
```

`route_hint.target` 为 `"markdown"` 走 MD 路径，为 `"ast"` 走 AST 路径。判定阈值（任一命中即走 AST）：

| 检测项 | 阈值 |
|--------|------|
| 文件大小 | > 200 KB |
| 任一 sheet 行数 | > 500 |
| 任一 sheet 列数 | > 20 |
| 可见 sheet 数量 | > 1 |
| 有合并单元格 | 存在 |
| 有公式 | 存在 |

## Excel MD 路径（简单文件）

```bash
python scripts/excel_to_md.py "input.xlsx" -o "input.md"
```

选项：
- `--sheet NAME` 只转某个 sheet（默认全部可见）
- `--max-rows N` 限制每个 sheet 行数
- `--include-hidden` 包含隐藏 sheet

**转换完成后，用 `baoyu-format-markdown` skill 美化 `input.md`。**

## Excel AST 路径（复杂文件）

面向「理解大型现有文件结构」和「精准修改」。AST 是 JSON 格式，人类不易读但 AI 可快速查阅，修改后通过 `ast_to_excel.py` 精准写回。

### 三种模式

| 模式 | 输出 | 适用场景 |
|------|------|---------|
| `workbook_summary` | ~0.5-2 KB | 已在路由判定时跑过 |
| `sheet_ast` | ~1-5 KB/100 cells | 需要看到具体单元格数据 |
| `semantic_analysis` | ~3-10 KB | 需要理解表格布局和语义 |

### 常用命令

```bash
# 读取特定 sheet（大文件加筛选）
python scripts/excel_to_ast.py "input.xlsx" --mode sheet_ast \
    --sheet "Sheet1" --max-rows 200 -o input_ast.json

# 语义分析（表头树、数据区、汇总行）
python scripts/excel_to_ast.py "input.xlsx" --mode semantic_analysis \
    --sheet "Sheet1" -o input_semantic.json

# 只看某区域
python scripts/excel_to_ast.py "input.xlsx" --mode sheet_ast \
    --sheet "Sheet1" --range "A1:K500"
```

原则：**先探测（summary）、再限定（range/max-rows）、逐步放大**。不要一次读出所有单元格。

### 修改回写

需要修改 Excel 时，编写 `modification_plan.json` 后用 `ast_to_excel.py` 写回。完整流程（修改计划 schema、安全规则、错误级别）见 [references/write_back.md](references/write_back.md)。

## Excel AST Schema

各模式输出字段的完整定义见 [references/ast_schema.md](references/ast_schema.md)。

## Cross-Skill References

| Skill | 关系 |
|-------|------|
| `baoyu-format-markdown` | **本 skill 所有 MD 产物必须过一遍**该 skill 美化 |
| `xlsx` | 创建新 Excel、添加格式、pandas 分析。本 skill 面向「理解现有文件」 |
| `pk-boq` | BOQ 专用流程，接受本 skill 的 AST/MD 输出 |
| `pk-boq-inquiry` | Phase 1 用本 skill 自动检测列映射替代硬编码 |
| `material-price-inquiry` | Step 1 用本 skill 提取材料清单 |

## MCP Excel 工具的定位

`mcp__excel__*`、`mcp__shell__*` 仅用于非 .xlsx 的临时数据文件或纯 CSV。所有 .xlsx 走本 skill。
