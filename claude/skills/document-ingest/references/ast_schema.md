# Excel AST Schema Reference

## Mode 1: workbook_summary

```json
{
  "mode": "workbook_summary",
  "source": "C:/path/to/workbook.xlsx",
  "workbook": {
    "name": "workbook.xlsx",
    "path": "C:/path/to/workbook.xlsx",
    "sheet_count": 3,
    "sheets": {
      "Sheet1": {
        "dimensions": "A1:Z200",
        "state": "visible",
        "max_row": 200,
        "max_column": 26
      }
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `workbook.name` | string | File name only (no path) |
| `workbook.sheet_count` | int | Total sheets (including hidden) |
| `workbook.sheets.*.dimensions` | string | Used range, e.g. "A1:Z200" |
| `workbook.sheets.*.state` | string | `visible` / `hidden` / `veryHidden` |
| `workbook.sheets.*.max_row` | int? | Last used row, null if empty |
| `workbook.sheets.*.max_column` | int? | Last used column, null if empty |

---

## Mode 2: sheet_ast

```json
{
  "mode": "sheet_ast",
  "source": "C:/path/to/workbook.xlsx",
  "sheets": [
    {
      "sheet": "Sheet1",
      "range": "A1:E50",
      "freeze_pane": "A2",
      "merged_cells": ["A1:C1", "D1:E1"],
      "row_count": 50,
      "column_count": 5,
      "cells": [
        {
          "cell": "A1",
          "row": 1,
          "column": "A",
          "value": "Project Budget 2025",
          "formula": null,
          "number_format": null,
          "is_merged": true,
          "merged_parent": "A1",
          "style_role": "title"
        },
        {
          "cell": "E4",
          "row": 4,
          "column": "E",
          "value": 10500,
          "formula": "=C4*D4",
          "number_format": "#,##0.00",
          "is_merged": false,
          "merged_parent": null,
          "style_role": "data"
        }
      ]
    }
  ]
}
```

### Cell Fields

| Field | Type | Description |
|-------|------|-------------|
| `cell` | string | Excel coordinate, e.g. "E12" |
| `row` | int | 1-based row number |
| `column` | string | Column letter, e.g. "E" |
| `value` | any | Raw cell value (number/string/bool/None) |
| `formula` | string? | Formula string starting with "=", null if value cell |
| `number_format` | string? | Excel number format string, null if "General" |
| `is_merged` | bool | True if cell is part of a merged region |
| `merged_parent` | string? | Top-left cell of merged region, null if not merged |
| `style_role` | string | `title` / `header` / `data` / `note` |

### Sheet-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `sheet` | string | Sheet name |
| `range` | string | Used cell range |
| `freeze_pane` | string? | Freeze pane anchor |
| `merged_cells` | [string] | Merged cell range strings |
| `row_count` | int | Number of data rows extracted |
| `column_count` | int | Number of columns in range |
| `cells` | [object] | Array of cell objects |

---

## Mode 3: semantic_analysis

Same as sheet_ast, plus a `semantic` block:

```json
{
  "semantic": {
    "regions": {
      "header_rows": [1, 2],
      "data_tables": [
        {
          "range": "A3:E48",
          "header_row": 2,
          "data_start_row": 3,
          "data_end_row": 48,
          "column_count": 5,
          "row_count": 46
        }
      ],
      "summary_rows": [49, 50],
      "formula_columns": [
        {"column": "E", "formula_ratio": 0.98}
      ]
    },
    "header_tree": {
      "levels": 2,
      "rows": [1, 2],
      "nodes": [
        {"level": 0, "row": 1, "column": "A", "text": "Revenue"},
        {"level": 0, "row": 1, "column": "D", "text": "Cost"},
        {"level": 1, "row": 2, "column": "A", "text": "Q1"},
        {"level": 1, "row": 2, "column": "B", "text": "Q2"}
      ]
    }
  }
}
```

### Semantic Regions

| Field | Type | Description |
|-------|------|-------------|
| `header_rows` | [int] | Row indices detected as headers |
| `data_tables` | [object] | Detected rectangular data regions |
| `summary_rows` | [int] | Rows containing SUM/SUBTOTAL formulas |
| `formula_columns` | [object] | Columns where >40% cells are formulas |

### Data Table Object

| Field | Type | Description |
|-------|------|-------------|
| `range` | string | Full range of the data table |
| `header_row` | int? | Row above data, null if no header |
| `data_start_row` | int | First data row |
| `data_end_row` | int | Last data row |
| `column_count` | int | Number of columns |
| `row_count` | int | Number of data rows |

### Header Tree

| Field | Type | Description |
|-------|------|-------------|
| `levels` | int | Number of header levels detected |
| `rows` | [int] | Row indices for each level |
| `nodes` | [object] | Individual header cells with level/position/text |

---

## Modification Plan (Input to ast_to_excel.py)

```json
{
  "source_file": "original.xlsx",
  "changes": [
    {
      "sheet": "Sheet1",
      "cell": "E12",
      "old_value": 42.5,
      "new_value": 45.0,
      "reason": "Update unit price from supplier quote #SRV-2024-003"
    },
    {
      "sheet": "Sheet2",
      "cell": "A1",
      "old_value": null,
      "new_value": "Updated Report",
      "reason": null
    }
  ]
}
```

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

---

## Safety Invariants (Enforced by ast_to_excel.py)

| Rule | Enforcement |
|------|-------------|
| Never destroy formulas | Warning if formula → value; error if formula count drops |
| Never remove merged cells | Error if merge count drops post-write |
| Never rewrite entire sheets | Warning if >5% of cells modified |
| Never reorder rows | No insert/delete row API exposed |
| Never overwrite original | Output path is always required |
| Preserve VBA macros | `keep_vba=True` on load and save |
