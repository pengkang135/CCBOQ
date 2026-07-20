"""
query.py — Query a master.jsonl BOQ state file. Keeps Claude context clean.

Modes:
  --rows 1,2,3         Print specific Excel row numbers (comma-separated).
  --where <expr>       Python-eval WHERE. `r` is the record dict.
                       Examples:
                         --where "r.get('current_disc')=='【MEP】'"
                         --where "'Morning Glory' in (r.get('desc') or '')"
  --preset <name>      Use a built-in detector preset (see below).
  --group-by fld,fld   Group and count.

Output:
  --format table|json|jsonl|count|row-list
  --sample N           Only show first N matching rows (default 20).
                       Use 0 for all (careful with size).
  --output <file>      Write to file instead of stdout (great for feeding shard.py).

Built-in presets:
  plant_in_non_landscape
  pipe_insul_in_arch_insulation
  gypsum_ceiling_not_ceiling_cat
  spiral_rebar_not_steel
  general_general_fallback
  missing_material
  discipline_mismatch_with_chapter
  duplicate_desc

Examples:
  # Explore
  python query.py --master master.jsonl --group-by current_disc,current_cat

  # Find suspects, write to targets.json for shard.py
  python query.py --master master.jsonl \
      --preset plant_in_non_landscape,pipe_insul_in_arch_insulation \
      --format row-list --output targets.json

  # Verify specific rows after a fix
  python query.py --master master.jsonl --rows 12103,14369 --format table
"""
import argparse, json, sys, re
sys.stdout.reconfigure(encoding='utf-8')

# ============ PRESETS ============
_PLANT_KW = r'\b(Ipomoea|Ixora|Sedge|Lepironia|Cyperus|Umbrella Plant|Firecracker|Russelia|Morning Glory|Water Spinach|Water Hyacinth|Water Lettuce|Water Primrose|Water Olive|Water Screw|Water Jasmine|Water Mitragyna|Water Plantain|Water Willow|Water Bloom|Duck Water|Ottelia|Blowgun|Elephant Ear|Alocasia|Calathea|Snake Plant|Sansevieria|Crinum|Ficus|Pandanus|Papyrus|Cassia|Dracaena|Gardenia|Wild [A-Z]\w+|Alpinia|Zingiber|Colocasia|Piper|Ludwigia|Elaeocarpus|Wrightia|Murraya|Spathiphyllum|Frangipani|Acacia|Leucaena|Eaglewood|Aquilaria|Peace Lily|Song of|Boiling Ganges|Spiderwort|Fishbone|Fragrant Willow|Fragrant Pandanus|Weeping Fig|Diospyros|Grevillea|West Indies Mahogany|Rose Apple|Malay Apple|Java Plum|Syzygium|Frog Leg|Rice-field|Silver Button|Green Shank|Lee Kuan Yew|Golden Chain|Cardamom|Sedum|Purple[- ])\b'

def preset_plant_in_non_landscape(r):
    d = r.get('desc') or ''
    if not r.get('current_material'):
        return False
    if r.get('current_disc') == '【Landscape】':
        return False
    if not re.search(_PLANT_KW, d, re.I):
        return False
    if re.search(r'stucco|sculpture|waterproofing tray|Door', d, re.I):
        return False
    return True

def preset_pipe_insul_in_arch_insulation(r):
    d = r.get('desc') or ''
    return r.get('current_cat') == '《Insulation》' and \
           bool(re.search(r'insulation.*(pipe|Ø|inch|Waste.*drain|drain.*pipe|refrigerant|Copper|Rock wool)', d, re.I))

def preset_gypsum_ceiling_not_ceiling_cat(r):
    d = r.get('desc') or ''
    return bool(re.search(r'^\s*C\d\w*\s+Gypsum board ceiling|Ceiling Gypsum Board|Gypsum board ceiling\b', d, re.I)) and \
           r.get('current_cat') != '《Ceiling》' and r.get('current_material')

def preset_spiral_rebar_not_steel(r):
    d = r.get('desc') or ''
    return bool(re.search(r'SPIRAL RB|Spiral RB', d)) and r.get('current_cat') != '《Steel》' and r.get('current_material')

def preset_general_general_fallback(r):
    return r.get('current_disc') and 'General' in r.get('current_disc','') and \
           r.get('current_cat') and 'General' in r.get('current_cat','')

def preset_missing_material(r):
    # leaf item (has unit+qty, not a heading) but no material assigned
    if r.get('heading_type'):
        return False
    return r.get('unit') and r.get('qty') and not r.get('current_material') and r.get('unit') != 'Works'

_CHAP2DISC = {'ST':'【Civil / Structural】','AR':'【Architectural】','SN':'【MEP】','EE':'【MEP】',
              'AC':'【MEP】','FA':'【MEP】','EL':'【MEP】','ELV':'【MEP】','LA':'【Landscape】','ID':'【Architectural】'}
def preset_discipline_mismatch_with_chapter(r):
    if not r.get('current_material'): return False
    chap = r.get('chapter_code') or ''
    for code, expected in _CHAP2DISC.items():
        if re.search(rf'\b{code}\b', chap):
            return r.get('current_disc') != expected
    return False

def preset_duplicate_desc(r):
    # only useful with a --group-by
    return bool(r.get('desc'))

PRESETS = {
    'plant_in_non_landscape': preset_plant_in_non_landscape,
    'pipe_insul_in_arch_insulation': preset_pipe_insul_in_arch_insulation,
    'gypsum_ceiling_not_ceiling_cat': preset_gypsum_ceiling_not_ceiling_cat,
    'spiral_rebar_not_steel': preset_spiral_rebar_not_steel,
    'general_general_fallback': preset_general_general_fallback,
    'missing_material': preset_missing_material,
    'discipline_mismatch_with_chapter': preset_discipline_mismatch_with_chapter,
    'duplicate_desc': preset_duplicate_desc,
}

# ============ MAIN ============
def load_master(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def compile_where(expr):
    # SECURITY NOTE: uses eval() on the --where arg. This is a local developer CLI;
    # --where only comes from the person running the script, never from user data or
    # network input. eval() runs in a hardened namespace: __builtins__ replaced with
    # {} (blocks open/exec/import/etc.) and only `r` (the record dict) and `re` are
    # exposed. A malicious --where could at worst read fields of r or run a regex.
    # If you ever want to invoke query.py from a service that takes external input,
    # replace this with a proper expression parser (e.g. simpleeval).
    code = compile(expr, '<where>', 'eval')
    def _fn(r):
        try:
            return bool(eval(code, {'__builtins__': {}}, {'r': r, 're': re}))
        except Exception:
            return False
    return _fn

def apply_preset_str(names):
    fns = []
    for n in names.split(','):
        n = n.strip()
        if n not in PRESETS:
            print(f'Unknown preset: {n}. Available: {sorted(PRESETS)}', file=sys.stderr)
            sys.exit(2)
        fns.append(PRESETS[n])
    return lambda r: any(fn(r) for fn in fns)

def print_table(records, cols=None):
    if not records:
        print('(no rows)')
        return
    cols = cols or ['excel_row', 'chapter_code', 'desc', 'unit', 'qty',
                    'current_disc', 'current_cat', 'current_subcat', 'current_material', 'current_spec']
    widths = {}
    for c in cols:
        widths[c] = max(len(c), *(len(str(r.get(c) or '')[:60]) for r in records))
        widths[c] = min(widths[c], 60)
    header = ' | '.join(c.ljust(widths[c]) for c in cols)
    print(header)
    print('-' * len(header))
    for r in records:
        vals = []
        for c in cols:
            v = str(r.get(c) or '')[:widths[c]]
            vals.append(v.ljust(widths[c]))
        print(' | '.join(vals))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--master', required=True)
    ap.add_argument('--rows', help='Comma-separated Excel row numbers')
    ap.add_argument('--where', help='Python expression using variable `r` (the record dict)')
    ap.add_argument('--preset', help='Comma-separated preset names')
    ap.add_argument('--group-by', help='Comma-separated field names to group + count')
    ap.add_argument('--sample', type=int, default=20, help='Max rows in output (0 = all)')
    ap.add_argument('--format', choices=['table','json','jsonl','count','row-list'], default='table')
    ap.add_argument('--output', help='Write to file instead of stdout')
    ap.add_argument('--cols', help='Comma-separated columns for table format')
    args = ap.parse_args()

    filters = []
    if args.rows:
        wanted = set(int(x) for x in args.rows.split(','))
        filters.append(lambda r: r.get('excel_row') in wanted)
    if args.where:
        filters.append(compile_where(args.where))
    if args.preset:
        filters.append(apply_preset_str(args.preset))

    matches = []
    for r in load_master(args.master):
        if all(f(r) for f in filters) if filters else True:
            matches.append(r)

    # group-by mode
    if args.group_by:
        keys = args.group_by.split(',')
        counts = {}
        for r in matches:
            k = tuple(r.get(k) for k in keys)
            counts[k] = counts.get(k, 0) + 1
        rows = sorted(counts.items(), key=lambda x: -x[1])
        out = '\n'.join(f'{cnt:6}  {" | ".join(str(x or "") for x in key)}' for key, cnt in rows)
        _write_out(out, args.output)
        return

    if args.format == 'count':
        _write_out(str(len(matches)), args.output)
        return
    if args.format == 'row-list':
        # emit a JSON list of excel_row ints, ready to feed shard.py
        _write_out(json.dumps([r['excel_row'] for r in matches]), args.output)
        return

    # sample slicing
    display = matches if args.sample == 0 else matches[:args.sample]

    if args.format == 'table':
        cols = args.cols.split(',') if args.cols else None
        # Capture table into string when --output is set; else print directly
        if args.output:
            import io
            buf = io.StringIO()
            orig = sys.stdout
            sys.stdout = buf
            try:
                print_table(display, cols)
            finally:
                sys.stdout = orig
            _write_out(buf.getvalue(), args.output)
        else:
            print_table(display, cols)
            print(f'\n({len(matches)} match{"" if len(matches)==1 else "es"} total, showing {len(display)})')
    elif args.format == 'json':
        _write_out(json.dumps(display, ensure_ascii=False, indent=1), args.output)
    elif args.format == 'jsonl':
        _write_out('\n'.join(json.dumps(r, ensure_ascii=False) for r in display), args.output)

def _write_out(text, path):
    if path:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'Wrote {len(text)} chars -> {path}', file=sys.stderr)
    else:
        print(text)

if __name__ == '__main__':
    main()
