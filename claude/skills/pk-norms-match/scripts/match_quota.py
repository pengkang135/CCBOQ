"""
CLI entry: BOQ清单AST → 定额匹配结果JSON.

Usage:
    python match_quota.py <boq_ast.json> [-o results.json] [--sheet FHDI清单]
                                           [--report report.txt] [--top-n 5]

The BOQ AST is produced by document-ingest's excel_to_ast.py --mode sheet_ast.
Output is a JSON array of MatchResult objects ready for write_results.py.
"""

import json, re, sys, io, argparse, math
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


def _has_title_markers(name):
    if not name:
        return False
    markers = [('{', '}'), ('《', '》'), ('【', '】')]
    for open_m, close_m in markers:
        if open_m in name and close_m in name:
            return True
    return False


def load_ast(ast_path, sheet_name=None):
    """Load BOQ items from document-ingest sheet_ast JSON.

    Parses the AST cell grid, detecting context markers (【】《》{}),
    skipping header rows and summary rows.
    """
    with open(ast_path, 'r', encoding='utf-8') as f:
        ast = json.load(f)

    sheets = ast.get('sheets', [])
    if not sheets:
        raise SystemExit('AST has no sheets')

    sheet = sheets[0]
    if sheet_name and len(ast.get('sheets', [])) > 1:
        for s in ast['sheets']:
            if s.get('name') == sheet_name:
                sheet = s
                break

    cells = sheet.get('cells', [])
    # Build grid: {row: {col_letter: value}}
    rows = {}
    for c in cells:
        r = c.get('row', 0)
        col = c.get('column', '')
        v = c.get('value')
        if r not in rows:
            rows[r] = {}
        rows[r][col] = v

    # Detect context markers and extract data rows
    items = []
    current_div = ''
    current_subdiv = ''
    current_subitem = ''

    for r in sorted(rows.keys()):
        data = rows[r]

        # E column typically contains name/context
        col_e = data.get('E', '')
        if col_e and isinstance(col_e, str):
            s_e = col_e.strip()
            if '【' in s_e:
                current_div = s_e.replace('【', '').replace('】', '').strip()
                continue
            elif '《' in s_e:
                current_subdiv = s_e.replace('《', '').replace('》', '').strip()
                continue
            elif '{' in s_e:
                current_subitem = s_e.replace('{', '').replace('}', '').strip()
                continue

        # Column mapping: C=SN, D=No, E=Name, F=Unit, G=TrueQty, H=Factor, I=Qty, K=Description
        sn = data.get('C')
        no = data.get('D', '')
        name = data.get('E', '')
        unit = data.get('F', '')
        true_qty = data.get('G')
        factor_val = data.get('H')
        qty = data.get('I')
        desc = data.get('K', '')

        # Filter: must have numeric SN and unit
        if sn is None or not isinstance(sn, (int, float)):
            continue
        if unit is None:
            continue
        # Skip TrueQty=0, None, or NaN rows
        if true_qty is None or true_qty == 0:
            continue
        if isinstance(true_qty, float) and math.isnan(true_qty):
            continue
        # Phase 0 pre-filter: skip conceptual units (LS/lot/项)
        raw_unit = str(unit).strip().lower() if unit else ''
        if raw_unit in ('ls', 'l.s.', 'lump sum', 'item', 'lot', 'allow',
                        'allowance', '项', 'sum', 'lump'):
            continue
        # Phase 0 pre-filter: skip title/header items with hierarchy markers
        if _has_title_markers(name):
            continue

        items.append({
            'row': r,
            'sn': int(sn),
            'no': str(no).strip() if no else '',
            'name': str(name).strip() if name else '',
            'unit': str(unit).strip() if unit else '',
            'true_qty': float(true_qty) if true_qty else 0,
            'factor': float(factor_val) if factor_val else 1.0,
            'qty': float(qty) if qty else 0,
            'description': str(desc).strip() if desc else '',
            'context_div': current_div,
            'context_subdiv': current_subdiv,
            'context_subitem': current_subitem,
        })

    return items, sheet.get('name', '')


def match(items, top_n=5):
    """Run matching against the quota database (SGA + SGB dual-DB)."""
    from matcher import MultiDBMatcher

    db_cfg = str(BASE / 'config' / 'db_config.json')
    matcher = MultiDBMatcher(db_config_path=db_cfg, base_dir=str(BASE))
    results = matcher.match_batch(items, top_n=top_n)
    matcher.close()
    return results


def serialize_results(results):
    """Convert MatchResult list to JSON-serializable dicts."""
    out = []
    for r in results:
        matches_json = []
        for m in r.matches:
            matches_json.append({
                'quota_code': m.quota_code,
                'quota_name': m.quota_name,
                'quota_unit_raw': m.quota_unit_raw,
                'phys_unit': m.phys_unit,
                'factor': m.factor,
                'chapter_title': m.chapter_title,
                'score': m.score,
                'score_breakdown': m.score_breakdown,
                'is_manual': m.is_manual,
                'db_source': m.db_source,
                'match_evidence': m.match_evidence,
            })
        out.append({
            'row': r.row,
            'boq_name': r.boq_name,
            'boq_description': r.boq_description,
            'boq_unit': r.boq_unit,
            'boq_quantity': r.boq_quantity,
            'context_div': r.context_div,
            'context_subdiv': r.context_subdiv,
            'context_subitem': r.context_subitem,
            'match_type': r.match_type,
            'category_note': r.category_note,
            'matches': matches_json,
        })
    return out


def print_stats(results, file=None):
    """Print match statistics."""
    total = len(results)
    matched = sum(1 for r in results if r.match_type == '已匹配')
    low = sum(1 for r in results if r.match_type == '得分不足')
    no_quota = sum(1 for r in results if r.match_type == '无对应定额')
    no_unit = sum(1 for r in results if r.match_type == '定额无单位')

    lines = [
        f'总条目: {total}',
        f'已匹配: {matched} ({100*matched/total:.1f}%)' if total else '已匹配: 0',
        f'得分不足: {low}',
        f'无对应定额: {no_quota}',
        f'定额无单位: {no_unit}',
    ]

    # By division
    ch_stats = defaultdict(lambda: {'total': 0, 'matched': 0})
    for r in results:
        ch = r.context_div or '(无分部)'
        ch_stats[ch]['total'] += 1
        if r.match_type == '已匹配':
            ch_stats[ch]['matched'] += 1

    lines.append(f'\n{"分部":<35} {"总数":>5} {"已匹配":>7} {"匹配率":>8}')
    lines.append('-' * 58)
    for ch in sorted(ch_stats.keys()):
        s = ch_stats[ch]
        rate = 100 * s['matched'] / s['total'] if s['total'] else 0
        lines.append(f'{ch:<35} {s["total"]:>5} {s["matched"]:>7} {rate:>7.1f}%')

    text = '\n'.join(lines)
    if file:
        file.write(text + '\n')
    print(text)


def main():
    _setup_stdout()
    parser = argparse.ArgumentParser(description='BOQ清单 → 定额匹配')
    parser.add_argument('ast_path', help='document-ingest sheet_ast JSON文件路径')
    parser.add_argument('-o', '--output', help='输出JSON路径 (默认: 源文件同目录_matching.json)')
    parser.add_argument('--sheet', help='目标sheet名 (多sheet时指定)')
    parser.add_argument('--report', help='统计报告输出路径')
    parser.add_argument('--top-n', type=int, default=5, help='每个条目保留的候选数 (默认5)')
    args = parser.parse_args()

    ast_path = Path(args.ast_path)
    if not ast_path.exists():
        raise SystemExit(f'AST文件不存在: {ast_path}')

    print(f'加载AST: {ast_path}')
    items, sheet_name = load_ast(str(ast_path), args.sheet)
    print(f'Sheet: {sheet_name}, 有效条目: {len(items)}')

    print('开始匹配...')
    results = match(items, top_n=args.top_n)

    serialized = serialize_results(results)

    # Output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = ast_path.parent / f'{ast_path.stem}_matching.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(serialized, f, ensure_ascii=False, indent=2)
    print(f'结果已保存: {out_path}')

    # Report
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            print_stats(results, file=f)
        print(f'报告已保存: {args.report}')
    else:
        print_stats(results)


if __name__ == '__main__':
    main()
