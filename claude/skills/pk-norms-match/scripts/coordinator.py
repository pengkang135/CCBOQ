"""
Coordinator: BOQ classification -> agent dispatch -> merge results.

Multi-agent orchestration for large BOQs (>200 items). Handles:
  1. BOQ item classification by work type (using agent_config.json)
  2. Per-agent split file generation
  3. Result merging with conflict detection
  4. Review flag generation

Usage:
  # Split mode: classify BOQ and output per-agent JSONs
  python coordinator.py "boq.xlsx" --mode split --sheet "Sheet名" -o split/

  # Merge mode: combine agent results into final JSON
  python coordinator.py --mode merge split/*_results.json -o merged.json

  # Run mode: sequential execution (for small BOQs or testing)
  python coordinator.py "boq.xlsx" --mode run --sheet "Sheet名" -o output/
"""

import json, sys, io, argparse, os, math
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
BASE = HERE.parent


def _setup_stdout():
    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        except (ValueError, AttributeError):
            pass


def load_agent_config():
    with open(BASE / 'config' / 'agent_config.json', 'r', encoding='utf-8') as f:
        return json.load(f)


def _has_title_markers(name):
    """Check if name contains BOQ hierarchy markers (title/header row)."""
    if not name:
        return False
    markers = [('{', '}'), ('《', '》'), ('【', '】')]
    for open_m, close_m in markers:
        if open_m in name and close_m in name:
            return True
    return False


def load_boq_from_excel(excel_path, sheet_name=None):
    """Load BOQ items from Excel using fastexcel.

    Column layout (by index, not Excel letter — fastexcel uses 0-based):
      2=SN(C), 3=No(D), 4=Name(E), 5=Unit(F), 6=TrueQty(G), 9=Qty(J), 11=Description(L)
    """
    import fastexcel
    reader = fastexcel.read_excel(excel_path)
    if sheet_name:
        sheet = reader.load_sheet(sheet_name)
    else:
        sheet = reader.load_sheet(0)

    df = sheet.to_pandas()
    rows_data = []

    current_div = ''
    current_subdiv = ''
    current_subitem = ''

    for idx, row in df.iterrows():
        excel_row = idx + 1  # pandas idx is 0-based, excel is 1-based

        # Access by integer column index
        col_sn = row.iloc[2] if len(row) > 2 else None       # C — SN
        col_no = row.iloc[3] if len(row) > 3 else ''          # D — No
        col_name = row.iloc[4] if len(row) > 4 else ''        # E — Name
        col_unit = row.iloc[5] if len(row) > 5 else ''        # F — Unit
        col_true_qty = row.iloc[6] if len(row) > 6 else None  # G — TrueQty
        col_qty = row.iloc[9] if len(row) > 9 else 0          # J — Qty
        col_desc = row.iloc[11] if len(row) > 11 else ''      # L — Description

        # Parse context markers from column E (name column)
        name_str = str(col_name).strip() if col_name is not None else ''
        if '【' in name_str:
            current_div = name_str.replace('【', '').replace('】', '').strip()
            continue
        elif '《' in name_str:
            current_subdiv = name_str.replace('《', '').replace('》', '').strip()
            continue
        elif '{' in name_str:
            current_subitem = name_str.replace('{', '').replace('}', '').strip()
            continue

        # Filter: must have numeric SN
        try:
            sn = float(col_sn) if col_sn is not None else None
        except (ValueError, TypeError):
            continue

        if sn is None or (isinstance(sn, float) and sn != sn):  # NaN check
            continue
        if col_unit is None or (isinstance(col_unit, float) and col_unit != col_unit):
            continue

        try:
            true_qty = float(col_true_qty) if col_true_qty is not None else 0
        except (ValueError, TypeError):
            continue

        if true_qty == 0 or math.isnan(true_qty):
            continue

        # Phase 0 pre-filter: skip conceptual units (LS/lot/项)
        raw_unit = str(col_unit).strip().lower() if col_unit is not None else ''
        conceptual_units = {'ls', 'l.s.', 'lump sum', 'item', 'lot', 'allow',
                            'allowance', '项', 'sum', 'lump'}
        if raw_unit in conceptual_units:
            continue

        # Phase 0 pre-filter: skip title/header items with hierarchy markers
        if _has_title_markers(name_str):
            continue

        try:
            qty_val = float(col_qty) if col_qty is not None else true_qty
        except (ValueError, TypeError):
            qty_val = true_qty

        rows_data.append({
            'row': excel_row,
            'sn': int(sn),
            'no': str(col_no).strip() if col_no is not None and not (
                isinstance(col_no, float) and col_no != col_no
            ) else '',
            'name': str(col_name).strip() if col_name is not None else '',
            'unit': str(col_unit).strip() if col_unit is not None else '',
            'true_qty': true_qty,
            'qty': qty_val,
            'description': str(col_desc).strip() if col_desc is not None and not (
                isinstance(col_desc, float) and col_desc != col_desc
            ) else '',
            'context_div': current_div,
            'context_subdiv': current_subdiv,
            'context_subitem': current_subitem,
        })

    return rows_data, sheet_name or 'Sheet1'


def classify_item(item, agents):
    """Classify a BOQ item to the best-matching agent.

    Uses category_keywords from each agent. The item goes to the agent
    whose keywords have the most matches in the item text.
    """
    text = f"{item['name']} {item['description']} {item['context_div']}".lower()

    # Check boq_sections first
    for agent in agents:
        if agent['id'] == 'no-match':
            continue
        for section in agent.get('boq_sections', []):
            div_upper = item['context_div'].upper()
            if section.upper() in div_upper:
                # Section match gives priority but still check keywords
                pass

    best_agent = None
    best_score = 0

    for agent in agents:
        if agent['id'] == 'no-match':
            continue
        score = 0
        for kw in agent.get('category_keywords', []):
            if kw.lower() in text:
                score += 1
        if score > best_score:
            best_score = score
            best_agent = agent

    if best_agent and best_score > 0:
        return best_agent['id']

    # Fallback: use boq_sections only
    for agent in agents:
        if agent['id'] == 'no-match':
            continue
        for section in agent.get('boq_sections', []):
            if section.upper() in item['context_div'].upper():
                return agent['id']

    return 'no-match'


def split_items(items, agents):
    """Split BOQ items into per-agent groups."""
    groups = defaultdict(list)
    for item in items:
        agent_id = classify_item(item, agents)
        groups[agent_id].append(item)

    return dict(groups)


def write_split_files(groups, agents, output_dir):
    """Write per-agent split JSON files and a dispatch plan."""
    os.makedirs(output_dir, exist_ok=True)

    agent_map = {a['id']: a for a in agents}
    plan = {'agents': [], 'total_items': 0}

    for agent_id, items in sorted(groups.items()):
        agent_info = agent_map.get(agent_id, {'name': agent_id})
        out_path = os.path.join(output_dir, f'split_{agent_id}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

        chapters_sga = agent_info.get('sga_chapters', [])
        chapters_sgb = agent_info.get('sgb_chapters', [])

        plan['agents'].append({
            'id': agent_id,
            'name': agent_info.get('name', agent_id),
            'item_count': len(items),
            'split_file': out_path,
            'sga_chapters': chapters_sga,
            'sgb_chapters': chapters_sgb,
            'boq_sections': agent_info.get('boq_sections', []),
        })
        plan['total_items'] += len(items)

    plan_path = os.path.join(output_dir, 'dispatch_plan.json')
    with open(plan_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    return plan


def merge_results(result_paths, output_path=None):
    """Merge multiple agent result JSONs into one, sorted by row."""
    all_results = []
    for rp in result_paths:
        with open(rp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        all_results.extend(data)

    all_results.sort(key=lambda r: r.get('row', 0))

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

    return all_results


def print_split_summary(plan):
    """Print a human-readable summary of the dispatch plan."""
    print(f"\n总条目: {plan['total_items']}")
    print(f"Agent数: {len(plan['agents'])}")
    print(f"\n{'Agent':<30} {'条目数':>6} {'SGA章节':<30}")
    print('-' * 70)
    for a in plan['agents']:
        chapters = ', '.join(a.get('sga_chapters', []))[:30]
        print(f"{a['name']:<30} {a['item_count']:>6} {chapters:<30}")

    # Check if parallel recommended
    big_agents = [a for a in plan['agents'] if a['id'] != 'no-match']
    parallel_recommended = sum(a['item_count'] for a in big_agents) > 200
    if parallel_recommended:
        print(f"\n[推荐] 总匹配项>200，建议使用Agent并行模式")
        print(f"  在Claude Code中: 对每个split文件使用Agent工具并行匹配")
        print(f"  命令行: 对每个split文件运行 match_quota.py")


def main():
    _setup_stdout()
    parser = argparse.ArgumentParser(
        description='BOQ分类调度器 — 多Agent协同匹配')
    parser.add_argument('boq_path', nargs='?',
                        help='BOQ Excel文件路径 (split/run模式需要)')
    parser.add_argument('--mode', choices=['split', 'run', 'merge'],
                        default='split', help='运行模式')
    parser.add_argument('--sheet', help='目标sheet名')
    parser.add_argument('-o', '--output', help='输出路径 (split: 目录, merge: JSON文件)')
    parser.add_argument('--plan-only', action='store_true',
                        help='仅打印分类计划，不写文件')
    args = parser.parse_args()

    agents = load_agent_config()['agents']

    if args.mode == 'merge':
        if not args.output:
            raise SystemExit('merge模式需要 -o 指定输出JSON路径')
        # Merge from positional args (file patterns handled by shell)
        import glob as glob_mod
        result_files = []
        for pattern in sys.argv[2:]:
            if pattern.startswith('--') or pattern.startswith('-'):
                continue
            matched = glob_mod.glob(pattern)
            result_files.extend(matched)
        result_files = sorted(set(result_files))
        if not result_files:
            raise SystemExit('未找到匹配的结果文件')
        print(f'合并 {len(result_files)} 个结果文件...')
        merged = merge_results(result_files, args.output)
        print(f'已合并 {len(merged)} 条结果 -> {args.output}')
        return

    if not args.boq_path:
        raise SystemExit('split/run模式需要提供BOQ文件路径')

    print(f'加载BOQ: {args.boq_path}')
    items, sheet_name = load_boq_from_excel(args.boq_path, args.sheet)
    print(f'Sheet: {sheet_name}, 有效条目: {len(items)}')

    print('分类中...')
    groups = split_items(items, agents)

    output_dir = args.output or 'output/split'
    plan = write_split_files(groups, agents, output_dir)
    print_split_summary(plan)

    if not args.plan_only:
        print(f'\n拆分文件已写入: {output_dir}/')
        for a in plan['agents']:
            print(f'  split_{a["id"]}.json ({a["item_count"]}项) -> Agent: {a["name"]}')

    if args.mode == 'run':
        print('\n开始顺序匹配...')
        from match_quota import match, serialize_results

        for a in plan['agents']:
            agent_id = a['id']
            split_file = a['split_file']
            with open(split_file, 'r', encoding='utf-8') as f:
                agent_items = json.load(f)

            print(f'  Agent [{a["name"]}]: {len(agent_items)}项...')
            results = match(agent_items)
            serialized = serialize_results(results)

            out_path = os.path.join(output_dir, f'results_{agent_id}.json')
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(serialized, f, ensure_ascii=False, indent=2)

        # Auto-merge
        result_pattern = os.path.join(output_dir, 'results_*.json')
        import glob as glob_mod
        result_files = sorted(glob_mod.glob(result_pattern))
        merged_path = os.path.join(output_dir, 'merged_results.json')
        merged = merge_results(result_files, merged_path)
        print(f'\n已合并 -> {merged_path} ({len(merged)}条)')


if __name__ == '__main__':
    main()
