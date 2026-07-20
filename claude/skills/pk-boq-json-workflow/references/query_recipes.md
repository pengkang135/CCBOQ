# query.py Recipes

Common query patterns. Master lives at `<workdir>/master.jsonl`.

## Sanity checks after import

```bash
# Total rows classified
python query.py --master master.jsonl \
    --where "r.get('current_material') is not None" --format count

# Distribution
python query.py --master master.jsonl \
    --where "r.get('current_material')" \
    --group-by current_disc,current_cat

# Chapters found
python query.py --master master.jsonl \
    --where "r.get('heading_type')=='chapter'" \
    --format table --cols excel_row,desc --sample 0
```

## Finding suspects (use built-in presets)

```bash
# Plants misclassified as MEP / Insulation / etc.
python query.py --master master.jsonl \
    --preset plant_in_non_landscape --format table

# Pipe insulation stuck in Architectural Insulation
python query.py --master master.jsonl \
    --preset pipe_insul_in_arch_insulation --format table

# Gypsum ceiling not in Ceiling category
python query.py --master master.jsonl \
    --preset gypsum_ceiling_not_ceiling_cat --format table

# Chapter/discipline mismatches (uses chapter_code)
python query.py --master master.jsonl \
    --preset discipline_mismatch_with_chapter \
    --group-by chapter_code,current_disc

# Fallback rows (【General】/《General》)
python query.py --master master.jsonl \
    --preset general_general_fallback --format count

# Multiple presets — union
python query.py --master master.jsonl \
    --preset plant_in_non_landscape,pipe_insul_in_arch_insulation,spiral_rebar_not_steel \
    --format row-list --output targets.json
```

## Custom WHERE

The `--where` expression is evaluated with `r` = the record dict, plus `re`. Use `.get()` to avoid KeyError on optional fields.

```bash
# Rows with specific material and no spec
python query.py --master master.jsonl \
    --where "r.get('current_material')=='Steel plate' and not r.get('current_spec')"

# Rows in a specific chapter with high qty
python query.py --master master.jsonl \
    --where "'LA' in (r.get('chapter_code') or '') and float(r.get('qty') or 0) > 100"

# Rows whose description matches a regex
python query.py --master master.jsonl \
    --where "re.search(r'Ø\s*\d+\s*mm', r.get('desc') or '')"

# Combine a preset with additional filter (use two runs + intersect, or add to preset def)
```

## Random access by row

```bash
# Verify specific rows after a fix
python query.py --master master.jsonl --rows 12103,14369,15668,19781 --format table

# JSON dump one row for close inspection
python query.py --master master.jsonl --rows 7654 --format json
```

## Feeding shard.py

`--format row-list` emits `[12103, 14369, 15668, ...]` which shard.py accepts as `--targets`.

```bash
python query.py --master master.jsonl \
    --preset plant_in_non_landscape,pipe_insul_in_arch_insulation \
    --format row-list --output targets.json

python shard.py --master master.jsonl \
    --targets targets.json --batches 6 --context-window 5 \
    --output-dir batches_v7
```

## Change log inspection (post-merge)

```bash
# Which rows changed in the last merge?
tail -n 200 change_log.jsonl | \
    python -c "import sys,json; [print(l['excel_row'], l.get('field'), l.get('reason')) for l in map(json.loads, sys.stdin) if l.get('op') != 'merge_summary']"

# Count changes per field
grep '"field"' change_log.jsonl | \
    python -c "import sys,json,collections; c=collections.Counter(json.loads(l)['field'] for l in sys.stdin); [print(f'{v:6} {k}') for k,v in c.most_common()]"
```

## Adding a new preset

Edit `query.py`, add a new `preset_your_name(r)` function, register it in the `PRESETS` dict. The function receives one record `r` and returns True/False.
