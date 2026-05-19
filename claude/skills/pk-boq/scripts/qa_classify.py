#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Q&A Classification & Summary Generator / 答疑分类汇总生成器

Converts bilingual Q&A markdown files into classified bilingual summaries
with cost impact labels. Outputs both .md and .xlsx.

Usage:
    # Two responding parties (default)
    python qa_classify.py file1.md file2.md -o output_dir --project "Project Name"

    # Single responding party
    python qa_classify.py file1.md -o output_dir --project "Project Name"

Input format per file:
    | Item | Query Ref | Question (EN) | Answer (EN) | Question (CN) | Answer (CN) |
"""
import re, sys, os, json
from collections import Counter

# ============================================================
# Classification Configuration — adjust per project as needed
# ============================================================

CATEGORIES = {
    '商务/合同条款类': 'Commercial & Contractual',
    '技术/设计类': 'Technical & Design',
    '范围/界面类': 'Scope & Interface',
    '施工组织/现场条件类': 'Construction Planning & Site Conditions',
    '投标文件/程序类': 'Tender Documents & Procedures',
}
CAT_ORDER = list(CATEGORIES.keys())

# Keywords: Chinese + English mixed, lowercased during matching
CONTRACT_KW = [
    '管辖法', 'governing law', '仲裁', 'arbitration', '不可抗力', 'force majeure',
    '终止', 'termination', '保险', 'insurance', '履约保证金', 'performance security',
    '保留金', 'retention', '延误损害赔偿', 'delay damage', '竣工时间', 'time for completion',
    '缺陷通知', 'DNP', '索赔', 'claim', '成本调整', 'cost adjustment', '预付款',
    'advance payment', '财务安排', 'financial arrangement', '抗腐败', 'anti-corruption',
    '出口管制', 'export control', '供应商行为', 'supplier code', '安全程序', 'safety procedure',
    '接管', 'taking over', 'sub-clause', 'particular condition', '特殊条件',
    'contract condition', '合同条件', '延期', 'extension of time', 'eot',
    '里程碑付款', 'milestone payment', '付款时间表', 'payment schedule', 'lump sum',
    '特许权协议', 'concession agreement', '接受的合同金额', 'accepted contract amount',
]

SCOPE_KW = [
    '范围', 'scope', '界面', 'interface', '边界', 'boundary', '不属于',
    'not in the scope', 'not in scope', 'out of scope', '不包括', '排除',
    'excluded', 'exclude', 'by others', '由其他', '其他承包商', 'other contractor',
    '不同包', 'different package', '设计范围', '本合同范围', '由建筑承包商',
    'building contractor', '不属于主体工程',
]
SCOPE_RE = [
    r'是否.*范围', r'是否属于', r'是否包含.*本次', r'不包括', r'不在.*范围',
    r'other.*contract.*scope', r'scope.*contract', r'not.*in.*scope',
]

TECH_KW = [
    '设计', 'design', '技术', 'technical', '规范', 'spec', '图纸', 'drawing',
    '结构', 'structural', '岩土', 'geotechnical', '地震', 'seismic', '荷载', 'load',
    '材料', 'material', '桩', 'pile', '混凝土', 'concrete', '钢筋', 'steel',
    '计算', 'calculation', '分析', 'analysis', '起重机', 'crane', '岸桥', 'STS',
    'RTG', '护舷', 'fender', '系船', 'bollard', '护岸', 'revetment', '疏浚',
    'dredging', '地基', '沉降', 'settlement', '液化', 'liquefaction', '排水',
    'drainage', '电气', 'electrical', '消防', 'fire', 'UPS', '变压器', 'transformer',
    '变电站', 'substation', '电缆', 'cable', '管线', 'pipe', '边坡', 'slope',
    '稳定', 'stability', 'FOS', 'PGA', '反应谱', '加速度', 'acceleration',
    '土壤', 'soil', 'PVD', 'SPMT', '冷藏', 'reefer', '上部结构', 'superstructure',
    '路面', 'pavement', '箱涵', 'culvert', '水闸', 'sluice', '导航', 'navigation',
    '航标', 'PHC', '强度', 'strength', '吸水率', '海堤', 'seawall', '测量',
    'survey', '垂直基准', 'datum', '系泊', 'mooring', '船舶操纵', 'UKC', '沉积',
    'sediment', '波浪', 'wave', 'HT', 'LT', 'DG', '发电机', 'CCTV', '闭路',
    '网络', 'network', 'IT', 'WiFi', '门禁', '防雷', 'lightning', '接地',
    'earthing', '开关柜', 'switchgear', '断路器', 'breaker', '馈线', 'feeder',
    '配电', 'distribution', '负载', 'SCADA', 'PLC', '光伏', 'solar', 'BESS',
    '电池', 'battery', '防火', 'HVAC', '暖通', '通风', 'ventilation', '给排水',
    'plumbing', '消防泵', '发电机', '照明', 'lighting', '插座', 'socket',
    '配电板', 'potable', '污水', 'sewage', 'WTP', 'STP',
]

CONST_KW = [
    '施工方法', '施工方案', 'methodology', 'construction method', '临时设施',
    'temporary facilit', '现场办公室', 'site office', '营地', 'camp', 'compound',
    'yard', 'storage', '堆放', '储存', '预制场', 'precast yard', '搅拌站',
    'batching plant', '加工场', '劳动力', 'labor', '工人', '宿舍', 'accommodation',
    '用水', '用电', '供水', '供电', 'water', 'power', 'connection point', '通道',
    'access', '道路', 'route', '进场', '高度限制', 'height restriction', '机场',
    'airport', '季风', 'monsoon', '雨季', '天气', 'weather', '进度', 'programme',
    '计划', 'schedule', 'WBS', 'PEP', 'execution plan', '执行计划', '搬迁',
    'relocate', '恢复', '复原', 'reinstatement', '移交', '开工日期前',
    'commencement date', '地球物理', 'geophysical', '障碍物', 'obstruction',
    '沉船', 'shipwreck', 'UXO', '未爆炸', '处置', 'disposal', '弃土', '抛泥',
    '许可', 'permit', '打桩驳船', 'pile barge', '审核', '审查', '批准', 'approval',
    '独立工程师', 'independent engineer',
]

BID_KW = [
    '投标', '招标', 'tender', 'bid', '提交', 'submission', '截止', 'deadline',
    '澄清', 'clarification', '疑问', '资格预审', 'pre-qualification', '模板',
    'template', '格式', 'format', 'Keelvar', '文件包', '标书', '建议书', 'proposal',
    '组织', 'organization', '人员', 'personnel', '关键人员', 'key personnel', 'CV',
    '资质', 'credential', '业绩', '经验', '要求', 'requirement', '指示',
    'instruction', '程序', 'procedure', '不一致', 'inconsistency', '矛盾',
    'discrepancy', '差异', '版本', '发布', '提供', 'provide', 'RFP', '招标文件',
    '附表', 'schedule', '附录', 'appendix', '附件', 'annex', '确认', 'confirm',
    '理解', 'understanding', '摘录', '组织架构', 'org chart', 'WBS ID', 'level',
    'CAD', '竣工图', 'as-built', '设计计算', '研究', 'study', '报告', 'report',
    '数据', 'data', '信息', 'information', '分享', 'share', 'available',
    'to be provided', '稍后提供', 'pending', '概念设计', 'conceptual design', 'DPR',
]

HIGH_COST_PATS = [
    'seismic', '地震', 'PGA', 'response spectra', '设计标准', 'design criteria',
    '安全系数.*降低', '不属于.*范围', 'not in.*scope', '疏浚.*处置',
    'dredging.*disposal', '赔偿', 'damage.*day', 'delay.*damage', '保留金',
    '保证金', 'bond', 'retention', '保险', 'insurance', 'indemnity', '索赔',
    'claim', 'arbitration', '仲裁', '恳请.*修改', 'respectfully.*amend',
    '恳请.*删除', '不予考虑', 'will not be considered', 'amendment.*not',
    'clause.*remain', '等待答复', 'answer pending', 'to be provided',
    'UPS.*冗余', '航标', 'navigation aid', '疏浚宽度', 'berth pocket',
    '高度限制', 'height restriction', '额外.*区域', 'additional.*area',
    '提供.*设计.*计算',
]

MED_COST_PATS = [
    '方法', 'method', '临时', 'temporary', 'compound', 'yard', '通道', 'access',
    '用水', '用电', '供水', '供电', 'water', 'power', '荷载', 'load',
    'specification', '参数', 'parameter', 'criteria', '不一致', 'inconsistency',
    '进度', 'programme', 'schedule', '许可证', 'permit', 'approval', '备件',
    'spare', '备用',
]

# Manual overrides: {item_number: category}
MANUAL_OVERRIDES = {
    '1': '投标文件/程序类', '2': '投标文件/程序类',
    '26': '投标文件/程序类', '27': '投标文件/程序类',
    '28': '投标文件/程序类', '29': '投标文件/程序类',
    '42': '商务/合同条款类', '80': '投标文件/程序类',
}

PENDING_MARKERS = ['answer pending', '等待答复']


# ============================================================
# Core logic
# ============================================================

def parse_rows(lines):
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith('|') or not re.match(r'\|\s*\d+\s*\|', line):
            continue
        parts = line.split('|')
        if len(parts) >= 7:
            rows.append({
                'item': parts[1].strip(),
                'query_ref': parts[2].strip(),
                'question_en': parts[3].strip(),
                'answer_en': parts[4].strip(),
                'question_cn': parts[5].strip(),
                'answer_cn': parts[6].strip(),
            })
    return rows


def classify_item(text_bundle, query_ref='', question_text=''):
    """Keyword scoring across 5 categories. Returns (category, cost_impact)."""
    text = text_bundle.lower()
    rl = query_ref.lower()
    qt = question_text.lower()

    # Score each category (full text)
    contract_score = sum(1 for kw in CONTRACT_KW if kw in text)
    if 'part ii - volume a - contract agreement' in rl:
        contract_score += 5

    scope_score = sum(1 for kw in SCOPE_KW if kw in text)
    for pat in SCOPE_RE:
        if re.search(pat, text): scope_score += 1

    tech_score = sum(1 for kw in TECH_KW if kw in text)
    if any(x in rl for x in ['per #', 'drawing', 'technical', 'material', 'seismic', 'design', 'electrical']):
        tech_score += 2

    const_score = sum(1 for kw in CONST_KW if kw in text)
    bid_score = sum(1 for kw in BID_KW if kw in text)

    # Priority decision tree
    if contract_score >= 3: cat = '商务/合同条款类'
    elif scope_score >= 3: cat = '范围/界面类'
    elif scope_score >= 2 and '范围' in qt: cat = '范围/界面类'
    elif const_score >= 4 and const_score > tech_score: cat = '施工组织/现场条件类'
    elif tech_score >= 3: cat = '技术/设计类'
    elif contract_score >= 1: cat = '商务/合同条款类'
    elif bid_score >= 2: cat = '投标文件/程序类'
    elif const_score >= 2: cat = '施工组织/现场条件类'
    elif scope_score >= 1: cat = '范围/界面类'
    else:
        # Fallback based on query_ref
        if 'contract' in rl or 'condition' in rl or 'agreement' in rl:
            cat = '商务/合同条款类'
        elif 'drawing' in rl or 'per' in rl:
            cat = '技术/设计类'
        elif any(x in rl for x in ['annex', 'schedule', 'instruction', 'proposal']):
            cat = '投标文件/程序类'
        else:
            cat = '技术/设计类'

    # Cost impact
    high_score = sum(1 for kw in HIGH_COST_PATS if re.search(kw, text))
    med_score = sum(1 for kw in MED_COST_PATS if re.search(kw, text))

    if cat == '商务/合同条款类':
        cost = '高' if high_score >= 1 else '中'
    elif cat == '范围/界面类':
        cost = '高' if high_score >= 3 else ('中' if high_score >= 1 or med_score >= 3 else '低')
    elif cat == '技术/设计类':
        cost = '高' if high_score >= 3 else ('中' if high_score >= 1 or med_score >= 4 else '低')
    elif cat == '施工组织/现场条件类':
        cost = '高' if high_score >= 2 else ('中' if high_score >= 1 or med_score >= 2 else '低')
    elif cat == '投标文件/程序类':
        cost = '高' if high_score >= 2 else ('中' if high_score >= 1 or med_score >= 2 else '低')
    else:
        cost = '中'

    return cat, cost


def esc(text):
    """Escape pipe characters, preserve line breaks as spaces."""
    return text.replace('\n', ' ').replace('|', '\\|')


def process_data(file1, file2=None):
    """Parse input files, merge, classify. Returns list of dicts."""
    with open(file1, 'r', encoding='utf-8') as f:
        rows1 = parse_rows(f.read().split('\n'))

    dual_mode = file2 is not None
    if dual_mode:
        with open(file2, 'r', encoding='utf-8') as f:
            rows2 = parse_rows(f.read().split('\n'))
        if len(rows1) != len(rows2):
            raise ValueError(f"Row count mismatch: {len(rows1)} vs {len(rows2)}")

    data = []
    for i in range(len(rows1)):
        d = {
            'item': rows1[i]['item'],
            'query_ref': rows1[i]['query_ref'],
            'question_cn': rows1[i]['question_cn'],
            'question_en': rows1[i]['question_en'],
            'answer1_cn': rows1[i]['answer_cn'],
            'answer1_en': rows1[i]['answer_en'],
        }
        if dual_mode:
            d['answer2_cn'] = rows2[i]['answer_cn']
            d['answer2_en'] = rows2[i]['answer_en']
        data.append(d)

    for d in data:
        text_bundle = ' '.join([
            d['question_cn'], d['question_en'], d['query_ref'],
            d['answer1_cn'], d['answer1_en'],
        ])  # answer2 excluded: mostly identical, would distort scoring

        qt = d['question_cn'] + ' ' + d['question_en']
        cat, cost = classify_item(text_bundle, d['query_ref'], qt)
        d['category'] = cat
        d['cost_impact'] = cost

    # Manual overrides
    for d in data:
        if d['item'] in MANUAL_OVERRIDES:
            d['category'] = MANUAL_OVERRIDES[d['item']]
        # Bump cost for pending answers
        if any(m in d['answer1_en'].lower() or m in d['answer1_cn'] for m in PENDING_MARKERS):
            if d['cost_impact'] == '低': d['cost_impact'] = '中'
            elif d['cost_impact'] == '中': d['cost_impact'] = '高'

    return data


def generate_markdown(data, output_path, project_name, dual_mode):
    """Generate bilingual classified markdown summary."""
    cost_order = {'高': 0, '中': 1, '低': 2}

    data_sorted = sorted(data, key=lambda d: (
        CAT_ORDER.index(d['category']) if d['category'] in CAT_ORDER else 99,
        cost_order.get(d['cost_impact'], 9),
        int(d['item'])
    ))

    if dual_mode:
        diff_items = [d['item'] for d in data if d.get('answer1_en') != d.get('answer2_en')]
    else:
        diff_items = []

    md = []
    md.append(f"# {project_name} — Query Classification Summary / 答疑分类汇总")
    md.append("")
    nc = len(data)
    md.append(f"**Total Queries**: {nc}  |  **Classification**: 5 Categories + Cost Impact (High/Medium/Low)"
              + (f"  |  **Responses**: Two parties" if dual_mode else ""))
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 1. Overview / 分类概览")
    md.append("")
    md.append("| Category / 类别 | Total / 总数 | High / 高 | Medium / 中 | Low / 低 |")
    md.append("|-----------------|-------------|-----------|-------------|----------|")

    totals = {'高': 0, '中': 0, '低': 0}
    for cat in CAT_ORDER:
        items = [d for d in data if d['category'] == cat]
        c = Counter(d['cost_impact'] for d in items)
        n = len(items)
        for k in ['高', '中', '低']:
            totals[k] += c.get(k, 0)
        md.append(f"| {CATEGORIES[cat]} / {cat} | {n} | {c.get('高', 0)} | {c.get('中', 0)} | {c.get('低', 0)} |")

    md.append(f"| **Total / 合计** | **{nc}** | **{totals['高']}** | **{totals['中']}** | **{totals['低']}** |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. Detailed Classification / 详细分类")
    md.append("")

    current_cat = None
    for d in data_sorted:
        cat = d['category']
        if cat != current_cat:
            current_cat = cat
            items = [x for x in data_sorted if x['category'] == cat]
            c = Counter(x['cost_impact'] for x in items)
            n = len(items)
            md.append(f"### {CATEGORIES[cat]} / {cat} (Total: {n} | High: {c.get('高',0)} | Medium: {c.get('中',0)} | Low: {c.get('低',0)})")
            md.append("")

            if dual_mode:
                md.append("| # | Query (CN) / 问题 | Cost / 成本 | Response 1 (CN) / 回答1 | Response 2 (CN) / 回答2 | Question (EN) / 原文 | Response 1 (EN) / 回答1原文 | Response 2 (EN) / 回答2原文 |")
                md.append("|---|-------------------|-------------|-------------------------|-------------------------|---------------------|---------------------------|---------------------------|")
            else:
                md.append("| # | Query (CN) / 问题 | Cost / 成本 | Response (CN) / 回答 | Question (EN) / 原文 | Response (EN) / 回答原文 |")
                md.append("|---|-------------------|-------------|----------------------|---------------------|-------------------------|")

        cost_label = d['cost_impact']
        if dual_mode and d['item'] in diff_items:
            cost_label += ' *'

        if dual_mode:
            md.append(f"| {d['item']} | {esc(d['question_cn'])} | {cost_label} | {esc(d['answer1_cn'])} | {esc(d.get('answer2_cn', ''))} | {esc(d['question_en'])} | {esc(d['answer1_en'])} | {esc(d.get('answer2_en', ''))} |")
        else:
            md.append(f"| {d['item']} | {esc(d['question_cn'])} | {cost_label} | {esc(d['answer1_cn'])} | {esc(d['question_en'])} | {esc(d['answer1_en'])} |")

    if diff_items:
        md.append("")
        md.append(f"*Items marked with \\* have differing responses ({len(diff_items)} item(s): Q{', Q'.join(diff_items)}). / 标\\*的条目表示回答存在差异。*")
    md.append("")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    return len(data_sorted)


def generate_excel(md_path, xlsx_path):
    """Convert generated markdown to Excel via md_to_xlsx.py."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    md_to_xlsx = os.path.join(script_dir, '..', '..', 'xlsx', 'scripts', 'md_to_xlsx.py')
    if not os.path.exists(md_to_xlsx):
        print(f"Warning: md_to_xlsx.py not found at {md_to_xlsx}, skipping Excel generation.")
        return False
    import subprocess
    result = subprocess.run(
        [sys.executable, md_to_xlsx, md_path, xlsx_path, '--one-sheet'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Excel generation failed: {result.stderr}")
        return False
    print(result.stdout.strip())
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Q&A Classification & Summary Generator / 答疑分类汇总生成器')
    parser.add_argument('file1', help='First Q&A markdown file (primary)')
    parser.add_argument('file2', nargs='?', default=None,
                        help='Second Q&A markdown file (optional, for dual-party mode)')
    parser.add_argument('-o', '--output', default='.',
                        help='Output directory (default: current dir)')
    parser.add_argument('--project', default='Project',
                        help='Project name for report title')
    parser.add_argument('--prefix', default='',
                        help='Output filename prefix (e.g. "20250423_")')
    args = parser.parse_args()

    if not os.path.exists(args.file1):
        sys.exit(f"File not found: {args.file1}")
    if args.file2 and not os.path.exists(args.file2):
        sys.exit(f"File not found: {args.file2}")

    dual_mode = args.file2 is not None
    data = process_data(args.file1, args.file2)

    os.makedirs(args.output, exist_ok=True)
    prefix = args.prefix
    md_path = os.path.join(args.output, f'{prefix}Query_Classification_Summary.md')
    xlsx_path = os.path.join(args.output, f'{prefix}Query_Classification_Summary.xlsx')

    n = generate_markdown(data, md_path, args.project, dual_mode)
    print(f"Markdown: {md_path} ({n} entries)")

    # Print stats
    for cat in CAT_ORDER:
        items = [d for d in data if d['category'] == cat]
        c = Counter(d['cost_impact'] for d in items)
        print(f"  {CATEGORIES[cat]}: {len(items)} | H:{c.get('高',0)} M:{c.get('中',0)} L:{c.get('低',0)}")

    if dual_mode:
        diff = [d['item'] for d in data if d.get('answer1_en') != d.get('answer2_en')]
        print(f"Differing responses: {diff if diff else 'None'}")

    # Generate Excel
    if generate_excel(md_path, xlsx_path):
        print(f"Excel: {xlsx_path}")


if __name__ == '__main__':
    main()
