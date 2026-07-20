# Excel Write-Back Workflow

将 AI 修改后的 AST 精准写回 xlsx 文件的完整流程。仅在需要修改现有 Excel 时使用；单纯读取无需此文档。

## 三步流程

### Step 1: Extract AST

```bash
# 快速概览
python scripts/excel_to_ast.py "input.xlsx" --mode workbook_summary

# 读取特定 sheet（大文件加筛选）
python scripts/excel_to_ast.py "input.xlsx" --mode sheet_ast \
    --sheet "Sheet1" --max-rows 200 -o ast.json

# 语义分析（自动识别表头树、数据区、汇总行）
python scripts/excel_to_ast.py "input.xlsx" --mode semantic_analysis \
    --sheet "Sheet1" -o semantic.json
```

`-o` 指定的路径应放在源文件所在目录。

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
- `new_value` 是 `"="` 开头则视为公式
- 只写要改的单元格，5 万行文件改 5 个格子只需 20 行 JSON
- 修改计划 JSON 保存在源文件所在目录

### Step 3: Apply

```bash
# 预览（推荐先做）
python scripts/ast_to_excel.py "input.xlsx" --plan plan.json --dry-run

# 执行
python scripts/ast_to_excel.py "input.xlsx" --plan plan.json \
    -o output.xlsx --backup
```

## ast_to_excel.py Options

| 选项 | 说明 |
|------|------|
| `--plan PLAN` | 修改计划 JSON 路径（必须） |
| `-o OUTPUT` | 输出路径（必须，不覆盖原文件） |
| `--dry-run` | 预览变更内容，不写入 |
| `--backup` | 写入前备份原文件为 `*_backup.xlsx` |
| `--force` | 忽略 non-fatal 警告继续执行 |

## Safety Rules

`ast_to_excel.py` 自动检查以下不变量：

1. **不破坏公式** — 覆盖公式 → 非公式值会产生警告，需 `--force`
2. **不移除合并单元格** — 写回后合并区域数不得减少
3. **不大批量重写** — 修改超过 5% 单元格会有警告
4. **不重排行/列** — 不暴露 insert/delete 操作
5. **不覆盖原文件** — `-o` 必须指定输出路径
6. **保留 VBA** — `keep_vba=True` 加载和保存

## Error Handling

| 错误级别 | 行为 |
|----------|------|
| `ERROR` | 阻塞：sheet 不存在、cell 无效、plan 格式错误。不会写入。 |
| `WARN` | 非阻塞但需 `--force`：公式覆盖、old_value 不匹配、合并单元格内写入、重复 cell |
| `SAFETY` | 写后检查失败：公式数量下降、合并区域减少、修改比 >5%。需 `--force`。 |

## Modification Plan Schema

### Change Entry Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `sheet` | Yes | string | Target sheet name |
| `cell` | Yes | string | Cell coordinate, e.g. "E12" |
| `new_value` | Yes | any | New value or formula string ("=...") |
| `old_value` | No | any | Expected current value for validation |
| `reason` | No | string | Human-readable change description |

### Validation Rules

1. All `sheet` values must exist in the workbook
2. All `cell` coordinates must be valid
3. Overwriting a formula with a non-formula value generates a warning
4. `old_value` mismatch generates a warning (not error)
5. Duplicate cell references: last write wins (warning)
6. Writing to non-top-left cell of merged region: redirected to top-left (warning)

## Reference

完整 AST Schema（sheet_ast、semantic_analysis 各字段规范）见 [ast_schema.md](ast_schema.md)。
