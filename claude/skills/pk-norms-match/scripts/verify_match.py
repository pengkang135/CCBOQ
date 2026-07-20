"""
Validation and reporting for quota matching results.

Generates:
  - Summary statistics (by chapter/division)
  - Unmatched item analysis (why items failed)
  - Random sampling for human review
  - Score distribution analysis

Usage:
    python verify_match.py matching.json [--sample 20] [--report report.txt]
"""

import json, sys, io, argparse, random
from collections import defaultdict, Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_results(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze(results, sample_count=20):
    """Statistical analysis of matching results."""
    total = len(results)
    if total == 0:
        return {'error': 'No results to analyze'}

    stats = Counter()
    for r in results:
        stats[r['match_type']] += 1

    matched_items = [r for r in results if r['match_type'] == '已匹配']
    unmatched_items = [r for r in results if r['match_type'] != '已匹配']

    # By division
    div_stats = defaultdict(lambda: {'total': 0, 'matched': 0, 'no_match': 0, 'low_score': 0, 'no_quota': 0, 'no_unit': 0})
    for r in results:
        div = r.get('context_div', '') or '(无分部)'
        div_stats[div]['total'] += 1
        if r['match_type'] == '已匹配':
            div_stats[div]['matched'] += 1
        else:
            div_stats[div][{
                '得分不足': 'low_score',
                '无对应定额': 'no_quota',
                '定额无单位': 'no_unit',
            }.get(r['match_type'], 'no_match')] += 1

    # Score distribution
    scores = []
    for r in matched_items:
        if r['matches']:
            scores.append(r['matches'][0].get('score', 0))

    score_buckets = {'90+': 0, '60-89': 0, '30-59': 0, '<30': 0}
    for s in scores:
        if s >= 90: score_buckets['90+'] += 1
        elif s >= 60: score_buckets['60-89'] += 1
        elif s >= 30: score_buckets['30-59'] += 1
        else: score_buckets['<30'] += 1

    # Why unmatched - categorize by note
    no_quota_notes = Counter()
    for r in unmatched_items:
        if r['match_type'] == '无对应定额':
            no_quota_notes[r.get('category_note', '未知')] += 1

    # Unit mismatch analysis
    unit_issues = []
    for r in unmatched_items:
        if r['match_type'] == '得分不足' and r['matches']:
            best = r['matches'][0]
            bd = best.get('score_breakdown', {})
            unit_result = bd.get('unit', '')
            if unit_result in ('hard_mismatch', 'conceptual_mismatch', 'no_quota_unit'):
                unit_issues.append({
                    'boq_name': r['boq_name'],
                    'boq_unit': bd.get('boq_unit', ''),
                    'cand_unit': bd.get('cand_unit', ''),
                    'unit_result': unit_result,
                    'best_code': best['quota_code'],
                })

    return {
        'total': total,
        'stats': dict(stats),
        'match_rate': 100 * stats['已匹配'] / total if total else 0,
        'div_stats': dict(div_stats),
        'score_distribution': score_buckets,
        'avg_score': sum(scores) / len(scores) if scores else 0,
        'min_score': min(scores) if scores else 0,
        'max_score': max(scores) if scores else 0,
        'no_quota_categories': dict(no_quota_notes.most_common(20)),
        'unit_issues': unit_issues[:10],
        'matched_items': matched_items,
        'unmatched_items': unmatched_items,
    }


def print_report(analysis, sample_count=20):
    """Print formatted analysis report."""
    print('=' * 60)
    print('定额匹配验证报告')
    print('=' * 60)

    print(f'\n总条目: {analysis["total"]}')
    print(f'已匹配: {analysis["stats"].get("已匹配", 0)} ({analysis["match_rate"]:.1f}%)')
    for key, label in [('得分不足', '得分不足'), ('无对应定额', '无对应定额'),
                        ('定额无单位', '定额无单位')]:
        if key in analysis['stats']:
            print(f'{label}: {analysis["stats"][key]}')

    # Score distribution
    if analysis.get('score_distribution'):
        print(f'\n--- 得分分布 (已匹配项) ---')
        sd = analysis['score_distribution']
        print(f'  90+:  {sd["90+"]}')
        print(f'  60-89: {sd["60-89"]}')
        print(f'  30-59: {sd["30-59"]}')
        print(f'  平均分: {analysis["avg_score"]:.1f}')
        print(f'  最低/最高: {analysis["min_score"]}/{analysis["max_score"]}')

    # By division
    print(f'\n{"分部":<35} {"总数":>5} {"已匹配":>7} {"匹配率":>8}')
    print('-' * 58)
    for div in sorted(analysis['div_stats'].keys()):
        s = analysis['div_stats'][div]
        rate = 100 * s['matched'] / s['total'] if s['total'] else 0
        print(f'{div:<35} {s["total"]:>5} {s["matched"]:>7} {rate:>7.1f}%')

    # No quota categories
    if analysis.get('no_quota_categories'):
        print(f'\n--- 无对应定额类别 ---')
        for note, count in analysis['no_quota_categories'].items():
            print(f'  {note}: {count}')

    # Unit issues
    if analysis.get('unit_issues'):
        print(f'\n--- 单位相关未匹配 (前10) ---')
        for u in analysis['unit_issues']:
            print(f'  {u["boq_name"][:50]} | BOQ:{u["boq_unit"]} | 候选:{u["cand_unit"]} | {u["unit_result"]}')

    # Sampling for review
    print(f'\n--- 抽样验证 ({sample_count}项) ---')
    random.seed(42)
    good = analysis['matched_items']
    unmatched = analysis['unmatched_items']

    n_good = min(sample_count, len(good))
    n_unmatch = min(sample_count // 3, len(unmatched))

    if n_good:
        print('\n已匹配样本:')
        for r in random.sample(good, n_good):
            best = r['matches'][0] if r['matches'] else {}
            bd = best.get('score_breakdown', {})
            print(f'\n  [{r.get("context_div", "")[:20]}] {r["boq_name"][:70]} | {r["boq_unit"]}')
            print(f'  -> [{best.get("quota_code", "")}] {best.get("quota_name", "")[:80]}')
            print(f'     得分:{best.get("score", 0):.0f} | 单位:{bd.get("unit", "")} | 关键词命中:{bd.get("keyword_hits", 0)}')
            # Show 2nd and 3rd candidates if available
            for idx in range(1, min(3, len(r['matches']))):
                m = r['matches'][idx]
                print(f'     #{idx+1}: [{m["quota_code"]}] {m["quota_name"][:70]} (得分:{m["score"]:.0f})')

    if n_unmatch:
        print('\n未匹配样本:')
        for r in random.sample(unmatched, n_unmatch):
            print(f'\n  [{r.get("context_div", "")[:20]}] {r["boq_name"][:70]} | {r["boq_unit"]}')
            print(f'  类型: {r["match_type"]} | 说明: {r.get("category_note", "")}')
            if r['matches']:
                best = r['matches'][0]
                print(f'  最佳候选: [{best["quota_code"]}] {best["quota_name"][:80]} (得分:{best["score"]:.0f})')


def main():
    parser = argparse.ArgumentParser(description='定额匹配结果验证与报告')
    parser.add_argument('matching_json', help='match_quota.py 输出的匹配JSON')
    parser.add_argument('--sample', type=int, default=20, help='抽样验证数量 (默认20)')
    parser.add_argument('--report', help='报告输出路径 (默认: 源文件同目录_report.txt)')
    args = parser.parse_args()

    results = load_results(args.matching_json)
    analysis = analyze(results, args.sample)

    if args.report:
        # Redirect stdout to file
        original_stdout = sys.stdout
        with open(args.report, 'w', encoding='utf-8') as f:
            sys.stdout = f
            print_report(analysis, args.sample)
        sys.stdout = original_stdout
        print(f'报告已保存: {args.report}')
        # Also print to console
        print_report(analysis, args.sample)
    else:
        print_report(analysis, args.sample)


if __name__ == '__main__':
    main()
