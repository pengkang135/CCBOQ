# master.jsonl Schema

Each line of `master.jsonl` is a JSON object describing one row of the source Excel sheet, plus rolled-forward context (project / chapter / subheading) so no field requires looking at other rows.

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `excel_row` | int | 1-based Excel row number (matches the xlsx). |
| `heading_type` | str \| null | `"project"` for 【...】, `"chapter"` for 《...》, `"subheading"` for `{...}`, `null` for leaf items. |
| `no` | str \| null | The "No." column (item number). |
| `desc` | str \| null | Description column, verbatim. |
| `unit` | str \| null | Unit of measure column. |
| `qty` | str \| null | Quantity column (kept as string to preserve formatting). |
| `project` | str \| null | Most recent 【...】 in force above this row. |
| `chapter` | str \| null | Most recent 《...》 in force. |
| `chapter_code` | str \| null | Chapter content stripped of 《》 (e.g. `"01-1 ST"`, `"3.1 Landscape Works (Main)"`). |
| `subheading` | str \| null | Most recent `{...}` in force. |
| `rate`, `amount`, `labor_rate`, `remark` | str \| null | Optional, only present if source workbook had these columns. |
| `current_disc`, `current_cat`, `current_subcat` | str \| null | Existing classification (if the source xlsx already had classification columns). |
| `current_material`, `current_spec`, `current_mat_unit`, `current_mat_qty` | str \| null | Existing extracted material fields. |
| `current_conf`, `current_note` | str \| null | Optional confidence + note fields carried over from prior version. |

## Design principles

- **Every leaf-item record is self-contained**: `project`/`chapter`/`subheading` are frozen at import time. A sub-agent handed a single record doesn't need to see any other rows to know what section it's in.
- **String-preserving**: Numeric fields (qty, rate, amount) are stored as strings. This avoids losing leading zeros, formulas, or Excel-specific formatting. Cast to numeric when you compute; store as string.
- **`current_*` fields are the only mutable state**. Everything else (excel_row, desc, unit, project, chapter, ...) is treated as immutable from the source workbook. Merging results only writes to `current_*` fields.
- **JSONL, not JSON**. One record per line for streaming reads, tail/head/grep-friendly, and no risk of file-level corruption on partial writes.

## Chapter code conventions

Chapters typically encode the discipline in a short suffix code:

| Code | Meaning | Expected discipline |
|------|---------|---------------------|
| `ST` | Structural | 【Civil / Structural】 |
| `AR` | Architectural | 【Architectural】 |
| `SN` | Sanitary/Plumbing | 【MEP】 |
| `EE` | Electrical | 【MEP】 |
| `AC` | Aircon/HVAC | 【MEP】 |
| `FA` | Fire Alarm | 【MEP】 |
| `EL` / `ELV` | ELV | 【MEP】 |
| `LA` | Landscape | 【Landscape】 |
| `ID` | Interior Decoration | 【Architectural】 |

Sub-building prefixes (e.g. `HS-`, `HO-`, `MP-`, `ME-`, `SA-`) inherit the trailing discipline code: `HS-ST` → Civil/Structural, `HO-EE` → MEP, etc.

## schema.json

Metadata about the import:

```json
{
  "source_xlsx": "F:/.../BQ_project.xlsx",
  "sheet": "ZOO BQ",
  "header_row": 1,
  "data_start_row": 3,
  "max_row": 23101,
  "max_col": 18,
  "column_map": {
    "no": 1, "desc": 2, "unit": 3, "qty": 4,
    "disc": 13, "cat": 14, "subcat": 15,
    "material": 16, "spec": 17, "mat_unit": 18, "mat_qty": 19
  },
  "imported_at": "2026-07-11T14:23:00",
  "row_count": 23099
}
```

`column_map` is what `merge.py` uses to write back to the correct Excel cells.
