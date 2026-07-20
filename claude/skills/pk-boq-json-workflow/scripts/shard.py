"""
shard.py — Split a target row list into batches with context, ready for sub-agents.

Given a master.jsonl + a targets JSON (list of excel_row ints or preset), produces
one batch_XX.json per batch, each containing item + PrevContext + NextContext.

Usage:
  # Targets from a query.py --format row-list output
  python shard.py --master master.jsonl --targets targets.json \
      --batches 6 --context-window 5 \
      --output-dir temp/boq_workflow/batches_v7

  # Targets inline
  python shard.py --master master.jsonl --rows 12103,14369,15668 \
      --batches 1 --output-dir temp/boq_workflow/batches_v7

Output per batch:
  {
    "batch_id": 1,
    "total_batches": 6,
    "row_range": [681, 7918],
    "items": [
      {
        "excel_row": 12103,
        "desc": "...",
        "unit": "sq.m",
        "qty": "410",
        "chapter": "《3.1 Landscape Works (Main)》",
        "chapter_code": "3.1 Landscape Works (Main)",
        "project": "【...】",
        "subheading": "{Shrub-Ground Cover Plant}",
        "current_disc": "【MEP】",       // from master state
        "current_cat": "《ELV / ICT》",
        "current_material": "Data/IT equipment",
        ...
        "prev_context": [ {excel_row, desc, unit, current_disc, current_cat}, ... ],
        "next_context": [ {excel_row, desc, unit}, ... ]
      },
      ...
    ]
  }

Also copies SUBAGENT_INSTRUCTIONS_TEMPLATE.md from the skill's references/ folder
into the output dir as SUBAGENT_INSTRUCTIONS.md so you can edit it per task.
"""
import argparse, json, math, pathlib, shutil, sys
sys.stdout.reconfigure(encoding='utf-8')

def load_master_list(path):
    recs = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs

def build_context(records, target_indices, window=5, forward=3):
    """records: list of master records, index in list.
       target_indices: iterable of INDEXES (0-based) into records.
       Return list of item dicts with prev_context/next_context."""
    out = []
    for i in target_indices:
        rec = records[i]
        prev = []
        j = i - 1
        # walk back up to 30 rows to find `window` items with a desc
        while j >= 0 and len(prev) < window:
            r = records[j]
            if r.get('desc'):
                prev.append({
                    'excel_row': r.get('excel_row'),
                    'desc': (r.get('desc') or '')[:140],
                    'unit': r.get('unit'),
                    'current_disc': r.get('current_disc'),
                    'current_cat': r.get('current_cat'),
                })
            j -= 1
            if i - j > 40: break
        prev.reverse()

        nxt = []
        j = i + 1
        while j < len(records) and len(nxt) < forward:
            r = records[j]
            if r.get('desc'):
                nxt.append({
                    'excel_row': r.get('excel_row'),
                    'desc': (r.get('desc') or '')[:140],
                    'unit': r.get('unit'),
                })
            j += 1
            if j - i > 15: break

        item = dict(rec)
        item['prev_context'] = prev
        item['next_context'] = nxt
        out.append(item)
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--master', required=True)
    ap.add_argument('--targets', help='JSON file: list of excel_row ints (from query.py --format row-list)')
    ap.add_argument('--rows', help='Alternative to --targets: inline comma-separated row numbers')
    ap.add_argument('--batches', type=int, default=6)
    ap.add_argument('--context-window', type=int, default=5, help='Prev context items')
    ap.add_argument('--forward-window', type=int, default=3, help='Next context items')
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    outdir = pathlib.Path(args.output_dir)
    if outdir.exists() and any(outdir.iterdir()) and not args.force:
        print(f'ERROR: output dir {outdir} not empty. Use --force.', file=sys.stderr)
        sys.exit(2)
    outdir.mkdir(parents=True, exist_ok=True)

    # Load targets
    if args.targets:
        with open(args.targets, encoding='utf-8') as f:
            payload = json.load(f)
        if isinstance(payload, list) and payload and isinstance(payload[0], int):
            target_rows = payload
        elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
            target_rows = [int(x['excel_row']) for x in payload]
        else:
            print(f'Unrecognized targets format', file=sys.stderr)
            sys.exit(2)
    elif args.rows:
        target_rows = [int(x) for x in args.rows.split(',')]
    else:
        print('Provide --targets or --rows', file=sys.stderr)
        sys.exit(2)

    target_set = set(target_rows)
    print(f'Targets: {len(target_set)} rows')

    records = load_master_list(args.master)
    row2idx = {r['excel_row']: i for i, r in enumerate(records)}
    target_indices = sorted([row2idx[r] for r in target_rows if r in row2idx])
    if len(target_indices) != len(target_rows):
        missing = set(target_rows) - {records[i]['excel_row'] for i in target_indices}
        print(f'WARN: {len(missing)} target rows not found in master (e.g. {sorted(missing)[:5]})',
              file=sys.stderr)

    items = build_context(records, target_indices, args.context_window, args.forward_window)
    per = math.ceil(len(items) / args.batches)

    for b in range(args.batches):
        chunk = items[b*per:(b+1)*per]
        if not chunk: break
        batch = {
            'batch_id': b + 1,
            'total_batches': args.batches,
            'row_range': [chunk[0]['excel_row'], chunk[-1]['excel_row']],
            'items': chunk,
        }
        out = outdir / f'batch_{b+1:02d}.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False, indent=1)
        size_kb = out.stat().st_size / 1024
        print(f'  batch {b+1:02d}: {len(chunk)} items, rows {batch["row_range"][0]}-{batch["row_range"][1]} ({size_kb:.1f} KB)')

    # Copy instructions template
    skill_dir = pathlib.Path(__file__).parent.parent
    tpl = skill_dir / 'references' / 'subagent_template.md'
    if tpl.exists():
        dest = outdir / 'SUBAGENT_INSTRUCTIONS.md'
        shutil.copy2(tpl, dest)
        print(f'\nCopied instructions template -> {dest}')
        print(f'Edit it for the specific task, then dispatch one agent per batch.')

if __name__ == '__main__':
    main()
