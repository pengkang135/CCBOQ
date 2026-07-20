# merge.py & xlsx write-back

## The merge model

`merge.py` treats master.jsonl as the source of truth. Applying results is:

```
results_*.json  →  master.jsonl (in-place)  →  change_log.jsonl (+entries)
                                                     ↓
                                            xlsx_out (fresh copy of xlsx_backup + patched cells)
```

Key properties:
- **Master is versionless** by design (change_log is the version history). If you want a snapshot, `cp master.jsonl master.v6.jsonl` before running merge.
- **xlsx_backup is never modified** — every merge produces a fresh xlsx_out from the backup + patches.
- **Only changed cells are written** — styles, formulas, merged cells, column widths, row heights are all preserved because openpyxl loads the file in place.

## Result schema (canonical, nested)

```json
{
  "excel_row": 12103,
  "action": "fix",                       // or "keep" — kept rows are skipped
  "updates": {
    "current_disc": "【Landscape】",
    "current_cat": "《Softscape》",
    "current_subcat": "Aquatic",
    "current_material": "Thai Morning Glory",
    "current_spec": "height 0.30-0.60 m",
    "current_mat_unit": "sq.m",
    "current_mat_qty": "410"
  },
  "reason": "plant species under LA chapter"
}
```

## Result schema (flat, backwards-compatible)

For quick scripts and legacy agent output, the flat form also works:

```json
{
  "ExcelRow": 12103,
  "Action": "fix",
  "Discipline": "【Landscape】",
  "Category": "《Softscape》",
  "Subcategory": "Aquatic",
  "Material": "Thai Morning Glory",
  "Spec": "height 0.30-0.60 m",
  "MatUnit": "sq.m",
  "MatQty": "410",
  "Reason": "plant species under LA chapter"
}
```

`merge.py` accepts either. Use nested for new tools; the flat form is only there because earlier iterations produced it.

## change_log.jsonl

Each field change is one line:

```json
{"ts":"2026-07-11T15:00:00","excel_row":12103,"field":"current_disc","old":"【MEP】","new":"【Landscape】","reason":"plant species","batch_reason":"v7 fix plant misclass"}
{"ts":"2026-07-11T15:00:00","excel_row":12103,"field":"current_cat","old":"《ELV / ICT》","new":"《Softscape》","reason":"plant species","batch_reason":"v7 fix plant misclass"}
...
```

Every batch also gets a summary line:

```json
{"ts":"2026-07-11T15:00:00","op":"merge_summary","fixed":146,"kept":5,"missing":0,"reason":"v7 fix plant misclass"}
```

## Undoing a merge

There's no built-in `unmerge` command yet. The correct pattern is:

1. Read the last `merge_summary`'s timestamp from change_log.
2. Grep the change_log for lines with that ts, extract `excel_row`/`field`/`old`.
3. Build a synthetic results file that sets each field back to its `old` value.
4. Run merge again with that results file and reason `"revert of <original reason>"`.

The revert becomes its own entries in change_log — full audit trail preserved.

Practical tip: before a destructive merge, do `cp master.jsonl master.snap-YYYYMMDD.jsonl`. Rollback is then just `mv` back.

## xlsx style preservation

The importer stashes an unmodified copy of the source workbook at `xlsx_backup.xlsx`. `merge.py` copies that file to `--xlsx-out` and only mutates the specific cells listed in the schema's `column_map`.

This means:
- Merged cells stay merged
- Formulas stay as formulas (openpyxl won't re-evaluate)
- Number formats, fonts, borders, fills preserved
- Column widths, row heights preserved
- Conditional formatting preserved

The only thing you lose relative to the source: cells you overwrite obviously replace whatever formula/value was there before. If you need to keep both the old value and the new classification, use a different column in the source workbook (extend `column_map`).

## What if I want fresh columns beyond what the source xlsx has?

If the source workbook doesn't have `disc`/`cat`/`material` columns, the importer's `column_map` won't include them, and `merge.py` won't have anywhere to write. Fix by editing schema.json manually:

```json
"column_map": {
  ...existing...,
  "disc": 25, "cat": 26, "subcat": 27, "material": 28,
  "spec": 29, "mat_unit": 30, "mat_qty": 31
}
```

Then run merge — it'll write to columns 25-31. Set the header row separately if you want labels: use `openpyxl` in a one-off script or the xlsx skill.

## Cross-project comparisons

If you have 10 project master.jsonl files with the same schema and want to compare:

```python
import json, glob
from collections import defaultdict
prices = defaultdict(list)
for f in glob.glob('projects/*/master.jsonl'):
    project = f.split('/')[-2]
    for line in open(f, encoding='utf-8'):
        r = json.loads(line)
        if r.get('current_material') == 'HDPE pipe' and r.get('rate'):
            prices[r.get('current_spec')].append((project, r['rate']))
for spec, entries in sorted(prices.items()):
    print(spec, entries)
```

This is where SQLite starts becoming worth it — the same query with `ATTACH` across DBs is cleaner. Until then, ad hoc Python over jsonl works fine.
