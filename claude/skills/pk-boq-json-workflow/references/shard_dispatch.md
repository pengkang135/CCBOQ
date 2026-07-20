# Sharding & Agent Dispatch

## Sizing batches

**Rule of thumb:**
- 100-200 items per batch
- Aim for < 250 KB JSON per batch (each item + context ~1-2 KB)
- 4-8 parallel agents typically hit API rate limits, so plan for a fallback rule-based path

**How context-window affects size:**
- `--context-window 5 --forward-window 3` → +8 rows of context per item → about 1.5-2 KB per item
- Larger windows only help if items are cryptic ("B1", "S04", "M01") and need the surrounding block to disambiguate. For plant/material items with self-describing descriptions, window=3 is plenty.

## Agent vs rule-based decision

| Situation | Recommendation |
|-----------|----------------|
| Cryptic codes (`B1`, `S04`, `M01`, `FN8`) needing semantic understanding | Agent |
| Long free-text descriptions in local language (Thai, Latin binomials) | Agent |
| Cross-check between description and current classification | Agent |
| Well-formed patterns (`SPIRAL RB<N>mm.@<Y>mm`, `insulation ... Ø ... inch`) | Rule-based |
| Rebuild classification from scratch on a small vocab | Agent (for taxonomy calibration) |
| Retry after agent finishes to catch missed edge cases | Rule-based |
| Rate-limited on API mid-task | Fall back to rule-based |

## Hybrid pattern (recommended for big fixes)

1. First pass: dispatch **1 batch** to an agent to establish/validate patterns
2. Review agent output for the batch — inspect what fixes it applied, spot check quality
3. Codify the rules the agent used into a Python script (like `rulebased_fix_v7.py`)
4. Apply the script to all remaining batches deterministically
5. Merge everything

This gives you the agent's judgement on ambiguous cases and the script's speed/reliability on the bulk.

## Dispatching a batch — prompt template

Each agent needs three files:
1. `SUBAGENT_INSTRUCTIONS.md` (edit `subagent_template.md` for the task at hand)
2. `batch_XX.json` (its assigned batch)
3. Optionally a `taxonomy.json` or reference file

Prompt outline (see `subagent_template.md` for a full example):

```
You are a BOQ classification VALIDATOR for a construction project.

Read these files (in order):
  1. .../batches/SUBAGENT_INSTRUCTIONS.md   ← authoritative rules
  2. .../batches/batch_XX.json              ← your 100-200 items
  3. .../taxonomy.json                       ← valid (Discipline, Category) pairs

Write results to .../batches/results_XX.json in the schema specified in the
instructions, one object per input item, same ExcelRow order.

Do not touch any Excel file. Do not ask clarifying questions.
Report count of fixed vs kept in under 100 words.
```

## Handling agent failures / rate limits

If some batches fail:
- Successful batches leave `results_XX.json` behind — those are done.
- For failed batches, either wait for the rate-limit window to reset and re-dispatch, or fall back to rule-based processing for those specific items (see `rulebased_fix_v7.py` in the current project as a reference).
- `merge.py` accepts a mix of agent-produced and script-produced results — as long as they follow the same schema.

## Verifying sub-agents didn't lie

After every dispatch, before merging, run a quick sanity check:

```bash
# Count total items across all results
python -c "import json,glob; print(sum(len(json.load(open(f,encoding='utf-8'))) for f in glob.glob('batches_v7/results_*.json')))"

# Cross-check: is every ExcelRow from targets present in some results file?
python -c "
import json, glob
targets = set(json.load(open('targets.json', encoding='utf-8')))
results = set()
for f in glob.glob('batches_v7/results_*.json'):
    results |= {r['excel_row'] if 'excel_row' in r else r['ExcelRow']
                for r in json.load(open(f, encoding='utf-8'))}
print('missing:', sorted(targets - results)[:10])
print('extra:',   sorted(results - targets)[:10])
"
```

If any target rows are missing from results, either re-dispatch those, or manually classify them before running merge.
