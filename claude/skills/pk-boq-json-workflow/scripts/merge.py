"""
merge.py — Apply sub-agent (or rule-based) results back to master.jsonl + xlsx.

Input: one or more results_XX.json files, each a list of objects like:
  {
    "excel_row": 12103,
    "action": "fix"    // or "keep" (skip)
    "updates": {                                 // preferred nested form
        "current_disc": "【Landscape】",
        "current_cat": "《Softscape》",
        "current_subcat": "Aquatic",
        "current_material": "Thai Morning Glory",
        "current_spec": "height 0.30-0.60 m",
        "current_mat_unit": "sq.m",
        "current_mat_qty": "410"
    },
    "reason": "plant species → Landscape"
  }

Flat form (each field at top level) is also accepted for backwards compatibility.

Does:
  1. Load master.jsonl into memory (list).
  2. Merge each result's updates into the matching master record.
  3. Append one change_log.jsonl entry per changed field (old -> new).
  4. Overwrite master.jsonl.
  5. Copy xlsx_backup.xlsx to --xlsx-out and patch the changed cells only,
     preserving all styles / formulas / merged cells / column widths.

Usage:
  python merge.py \
      --workdir temp/boq_workflow \
      --results temp/boq_workflow/batches_v7/results_*.json \
      --xlsx-out path/to/BQ_project_v7.xlsx \
      --reason "v7: fix plant/insulation misclassifications"
"""
import argparse, json, pathlib, shutil, sys, glob, datetime
sys.stdout.reconfigure(encoding='utf-8')

# Map master field name -> Excel column header the importer would have stored
# We look up the actual column index from schema.json's column_map.
FIELD_TO_COL = {
    'current_disc': 'disc',
    'current_cat': 'cat',
    'current_subcat': 'subcat',
    'current_material': 'material',
    'current_spec': 'spec',
    'current_mat_unit': 'mat_unit',
    'current_mat_qty': 'mat_qty',
    'current_conf': 'conf',
    'current_note': 'note',
}

def load_results(patterns):
    all_results = []
    for pat in patterns:
        for path in glob.glob(pat):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                all_results.extend(data)
            elif isinstance(data, dict) and 'items' in data:
                all_results.extend(data['items'])
            else:
                print(f'WARN: unrecognized result file structure: {path}', file=sys.stderr)
    return all_results

def normalize_result(r):
    """Return (excel_row, updates_dict, action, reason)."""
    row = int(r.get('excel_row') or r.get('ExcelRow'))
    action = (r.get('action') or r.get('Action') or 'fix').lower()
    reason = r.get('reason') or r.get('Reason') or ''
    if 'updates' in r and isinstance(r['updates'], dict):
        return row, r['updates'], action, reason
    # Flat form: accept both snake_case and CamelCase
    flat_map = {
        'Discipline': 'current_disc', 'discipline': 'current_disc',
        'Category': 'current_cat',    'category': 'current_cat',
        'Subcategory': 'current_subcat','subcategory': 'current_subcat',
        'Material': 'current_material','material': 'current_material',
        'Spec': 'current_spec',       'spec': 'current_spec',
        'MatUnit': 'current_mat_unit','mat_unit': 'current_mat_unit',
        'MatQty': 'current_mat_qty',  'mat_qty': 'current_mat_qty',
        'Confidence': 'current_conf', 'conf': 'current_conf',
        'Note': 'current_note',       'note': 'current_note',
    }
    updates = {}
    for k, v in r.items():
        if k in flat_map:
            updates[flat_map[k]] = v
    return row, updates, action, reason

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--workdir', required=True, help='Dir containing master.jsonl, schema.json, xlsx_backup.xlsx, change_log.jsonl')
    ap.add_argument('--results', nargs='+', required=True, help='One or more results JSON files (glob patterns OK)')
    ap.add_argument('--xlsx-out', help='Output xlsx path. If omitted, only master.jsonl is updated.')
    ap.add_argument('--reason', default='', help='Reason logged for this merge batch')
    args = ap.parse_args()

    wd = pathlib.Path(args.workdir)
    master_path = wd / 'master.jsonl'
    schema_path = wd / 'schema.json'
    xlsx_backup = wd / 'xlsx_backup.xlsx'
    change_log_path = wd / 'change_log.jsonl'

    for p in (master_path, schema_path):
        if not p.exists():
            print(f'ERROR: missing {p}', file=sys.stderr)
            sys.exit(2)

    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    col_map = schema['column_map']

    # Load master
    records = []
    with open(master_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    row2idx = {r['excel_row']: i for i, r in enumerate(records)}
    print(f'Loaded {len(records)} master records')

    # Load results
    results = load_results(args.results)
    print(f'Loaded {len(results)} result records')

    # Merge
    ts = datetime.datetime.now().isoformat()
    n_fixed = 0
    n_kept = 0
    n_missing = 0
    change_entries = []
    for r in results:
        row, updates, action, reason = normalize_result(r)
        if action == 'keep' or not updates:
            n_kept += 1
            continue
        if row not in row2idx:
            n_missing += 1
            continue
        rec = records[row2idx[row]]
        for field, new_val in updates.items():
            new_val = None if new_val == '' else new_val
            old_val = rec.get(field)
            if old_val == new_val:
                continue
            rec[field] = new_val
            change_entries.append({
                'ts': ts,
                'excel_row': row,
                'field': field,
                'old': old_val,
                'new': new_val,
                'reason': reason,
                'batch_reason': args.reason,
            })
        n_fixed += 1

    print(f'Applied: {n_fixed} fixed, {n_kept} kept, {n_missing} missing')

    # Persist master
    tmp = master_path.with_suffix('.jsonl.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    tmp.replace(master_path)
    print(f'Master rewritten: {master_path}')

    # Append change log
    with open(change_log_path, 'a', encoding='utf-8') as f:
        for e in change_entries:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
        f.write(json.dumps({'ts': ts, 'op': 'merge_summary',
                            'fixed': n_fixed, 'kept': n_kept, 'missing': n_missing,
                            'reason': args.reason}, ensure_ascii=False) + '\n')
    print(f'Change log +{len(change_entries)+1} entries')

    # Patch xlsx
    if args.xlsx_out:
        if not xlsx_backup.exists():
            print(f'ERROR: xlsx_backup not found at {xlsx_backup}', file=sys.stderr)
            sys.exit(2)
        import openpyxl
        out = pathlib.Path(args.xlsx_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(xlsx_backup, out)
        wb = openpyxl.load_workbook(out)
        ws = wb[schema['sheet']]

        # For each changed field, look up column index
        rows_touched = {e['excel_row'] for e in change_entries}
        for row in rows_touched:
            rec = records[row2idx[row]]
            for field, col_key in FIELD_TO_COL.items():
                if col_key in col_map:
                    ws.cell(row=row, column=col_map[col_key]).value = rec.get(field)
        wb.save(out)
        print(f'Patched xlsx: {out}  ({len(rows_touched)} rows touched)')

if __name__ == '__main__':
    main()
