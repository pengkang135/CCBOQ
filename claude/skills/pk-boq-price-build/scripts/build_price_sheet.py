#!/usr/bin/env python3
"""人材机价格表构建 — 将原始人材机数据按BOQ四级层级分类输出格式化Excel。

用法:
  python build_price_sheet.py <input.xlsx> [-o output.xlsx] [-s SUPPLIER] [-d DATE]
"""

import pandas as pd
import xlsxwriter
import yaml
import os
import re
import argparse
from pathlib import Path


def load_configs(config_dir):
    """加载YAML配置文件"""
    with open(os.path.join(config_dir, 'hierarchy_template.yaml'), 'r', encoding='utf-8') as f:
        hierarchy_cfg = yaml.safe_load(f)
    with open(os.path.join(config_dir, 'classification_rules.yaml'), 'r', encoding='utf-8') as f:
        rules_cfg = yaml.safe_load(f)
    return hierarchy_cfg, rules_cfg


def build_equipment_sets(rules_cfg):
    """从YAML构建设备分类集合"""
    es = rules_cfg.get('equipment_sets', {})
    return {k: set(v) for k, v in es.items()}


def build_l3_classifiers(rules_cfg):
    """从YAML构建L3分类器: {classifier_name: {l3_label: [keywords]}}"""
    classifiers = {}
    for name, mapping in rules_cfg.get('l3_classifiers', {}).items():
        classifiers[name] = {}
        for l3_label, keywords in mapping.items():
            classifiers[name][l3_label] = [k.lower() for k in keywords]
    return classifiers


def classify_by_l3_classifier(name, classifier_rules, default='{其他}'):
    """通用L3分类器：按关键词列表匹配"""
    nl = name.lower()
    for l3_label, keywords in classifier_rules.items():
        if keywords and any(k in nl for k in keywords):
            return l3_label
    return default


def classify_by_l3_set(name, classifier_rules, default='{其他}'):
    """按集合匹配的L3分类器（用于人工工种分类）"""
    for l3_label, names in classifier_rules.items():
        if name in names:
            return l3_label
    return default


def _eval_subexpr(subexpr, name, cat, remark, equip_sets):
    """求值单个子表达式（不含 and/or）。"""
    s = subexpr.strip()

    if s == 'always':
        return True

    if s.startswith('IS_'):
        eq_set = equip_sets.get(s, set())
        return name in eq_set

    # name contains [a, b, c]
    m = re.match(r"^name\s+contains\s+\[(.+)\]$", s)
    if m:
        keywords = [k.strip().strip("'\"") for k in m.group(1).split(',')]
        nl = name.lower()
        return any(k.lower() in nl for k in keywords)

    # name not contains 'xxx'
    m = re.match(r"^name\s+not\s+contains\s+'([^']+)'$", s)
    if m:
        return m.group(1).lower() not in name.lower()

    # name contains 'xxx'
    m = re.match(r"^name\s+contains\s+'([^']+)'$", s)
    if m:
        return m.group(1).lower() in name.lower()

    # name == 'xxx'
    m = re.match(r"^name\s+==\s+'([^']+)'$", s)
    if m:
        return name == m.group(1)

    # cat contains 'xxx'
    m = re.match(r"^cat\s+contains\s+'([^']+)'$", s)
    if m:
        return m.group(1) in cat

    # cat not contains 'xxx'
    m = re.match(r"^cat\s+not\s+contains\s+'([^']+)'$", s)
    if m:
        return m.group(1) not in cat

    # name in SET_NAME
    m = re.match(r"^name\s+in\s+(\w+)$", s)
    if m:
        eq_set = equip_sets.get(m.group(1), set())
        return name in eq_set

    return False


def parse_match_expr(expr, name, cat, remark, equip_sets):
    """解析匹配表达式，支持 'and' 连接的复合条件。"""
    expr = expr.strip()

    # 复合表达式: subexpr ' and ' subexpr [' and ' subexpr ...]
    if ' and ' in expr:
        parts = expr.split(' and ')
        return all(_eval_subexpr(p, name, cat, remark, equip_sets) for p in parts)

    return _eval_subexpr(expr, name, cat, remark, equip_sets)


def classify_row(name, cat, remark, rules, equip_sets, l3_classifiers):
    """对单行数据分类。Python 处理复杂逻辑，简单匹配委托 YAML 规则。"""
    managers = equip_sets.get('MANAGER_NAMES', set())

    # --- Python-level complex logic ---
    if '人工费' in cat:
        # 混凝土生产 (cat: 【人工费-混凝土】)
        if '混凝土' in cat:
            return ('【人工费】', '《混凝土生产》', None, '劳务分包')
        # 连锁块生产 (cat: 【人工费-连锁块】)
        if '连锁块' in cat:
            return ('【人工费】', '《连锁块生产》', None, '劳务分包')
        # 管理人员
        if name in managers:
            return ('【人工费】', '《管理人员》', None, '劳务分包')
        # 潜水员
        if name == '潜水员':
            return ('【人工费】', '《潜水员》', None, '劳务分包')
        # 中方人员 (月薪 >= 2000 USD)
        if '月薪' in remark and 'USD' in remark:
            try:
                monthly = float(remark.split('月薪')[1].split('USD')[0])
                if monthly >= 2000:
                    l3 = classify_by_l3_classifier(name, l3_classifiers.get('labor_l3', {}), '{普通劳务}')
                    return ('【人工费】', '《中方人员》', l3, '劳务分包')
            except (ValueError, IndexError):
                pass
        # 日工
        l3 = classify_by_l3_classifier(name, l3_classifiers.get('labor_l3', {}), '{普通劳务}')
        return ('【人工费】', '《日工》', l3, '劳务分包')

    if '材料费' in cat:
        # 周转材料（专业列判断优先）
        if '周转' in cat:
            return ('【材料费】', '《周转材料》', None, '建筑装饰')
        # 混凝土配合比
        if '混凝土配合比' in cat:
            return ('【材料费】', '《混凝土》', '{配合比/单价}', '建筑装饰')
        # 混凝土（专业列）
        if '混凝土' in cat and '配合比' not in cat:
            l3 = classify_by_l3_classifier(name, l3_classifiers.get('concrete_l3', {}), '{其他混凝土}')
            return ('【材料费】', '《混凝土》', l3, '建筑装饰')

        # 按名称关键词匹配（YAML规则顺序）
        for rule in rules:
            match_expr = rule.get('match', '')
            if not match_expr or 'cat contains' in match_expr or match_expr.strip() == 'always':
                continue  # 跳过专业列规则和全局兜底
            if parse_match_expr(match_expr, name, cat, remark, equip_sets):
                l1 = rule.get('l1', '【材料费】')
                l2 = rule.get('l2', '《其他材料》')
                spec = rule.get('spec', '建筑装饰')
                l3 = rule.get('l3')
                if l3 is None:
                    cname = rule.get('l3_classifier')
                    if cname and cname in l3_classifiers:
                        l3 = classify_by_l3_classifier(name, l3_classifiers[cname])
                return (l1, l2, l3, spec)

        return ('【材料费】', '《其他材料》', None, '建筑装饰')

    if '机械费' in cat:
        # 建站费用 (cat: 【机械费-建站】)
        if '建站' in cat:
            return ('【机械费】', '《建站费用》', None, '工程机械')
        # 建站设备（名称匹配）
        station_eq = equip_sets.get('STATION_EQUIP', set())
        if name in station_eq:
            return ('【机械费】', '《建站设备》', None, '工程机械')
        # 设备租赁
        if '设备租赁' in cat:
            return _classify_equipment(name, '《设备租赁》', equip_sets, l3_classifiers)
        # 自有机械（船机/陆机等）
        return _classify_equipment(name, '《自有机械》', equip_sets, l3_classifiers)

    return ('【其他】', '《其他》', None, '建筑装饰')


def _classify_equipment(name, l2, equip_sets, l3_classifiers):
    """设备分类：按预定义集合匹配 L3。"""
    spec = '工程机械'

    for set_key, l3_label in [
        ('SHIP_EQUIP', '{船机}'),
        ('EARTHWORK_EQUIP', None),  # 特殊处理：用 earthwork_l3 分类器
        ('HORIZONTAL_EQUIP', '{水平运输}'),
        ('VERTICAL_EQUIP', '{垂直运输}'),
        ('PILE_EQUIP', '{桩基设备}'),
        ('CONCRETE_EQUIP', '{混凝土设备}'),
        ('SMALL_TOOLS', '{小型机具}'),
    ]:
        eq_set = equip_sets.get(set_key, set())
        if name in eq_set:
            if l3_label is None and set_key == 'EARTHWORK_EQUIP':
                l3 = classify_by_l3_classifier(name, l3_classifiers.get('earthwork_l3', {}), '{其他}')
            else:
                l3 = l3_label
            return ('【机械费】', l2, l3, spec)

    # 建站设备
    station_eq = equip_sets.get('STATION_EQUIP', set())
    if name in station_eq:
        return ('【机械费】', '《建站设备》', None, spec)

    return ('【机械费】', l2, '{其他机械}', spec)


def build_hierarchy_order(hierarchy_cfg):
    """从YAML构建层级排序索引"""
    l1_order = {}
    l2_orders = {}
    l3_orders = {}

    for section_title, l2_list in hierarchy_cfg.get('hierarchy', {}).items():
        l1_order[section_title] = len(l1_order)
        l2_orders[section_title] = {}
        l3_orders[section_title] = {}

        for l2_entry in l2_list:
            if isinstance(l2_entry, dict):
                for l2_name, l2_cfg in l2_entry.items():
                    l2_orders[section_title][l2_name] = len(l2_orders[section_title])
                    l3_list = l2_cfg.get('l3_categories', []) if l2_cfg else []
                    l3_orders[section_title][l2_name] = {
                        '{' + l3 + '}': i for i, l3 in enumerate(l3_list)
                    }
            elif isinstance(l2_entry, str):
                # Simplified format: just the L2 name
                l2_name = l2_entry
                l2_orders[section_title][l2_name] = len(l2_orders[section_title])
                l3_orders[section_title][l2_name] = {}

    return l1_order, l2_orders, l3_orders


def get_hierarchy_spec_map(hierarchy_cfg):
    """从YAML提取每个L2的默认专业(spec)和L3配置"""
    spec_map = {}
    l3_config = {}

    for section_title, l2_list in hierarchy_cfg.get('hierarchy', {}).items():
        for l2_entry in l2_list:
            if isinstance(l2_entry, dict):
                for l2_name, l2_cfg in l2_entry.items():
                    if l2_cfg:
                        spec_map[(section_title, l2_name)] = l2_cfg.get('spec', '建筑装饰')
                        if l2_cfg.get('l3_auto'):
                            l3_config[(section_title, l2_name)] = l2_cfg.get('l3_categories', [])

    return spec_map, l3_config


def main():
    parser = argparse.ArgumentParser(description='人材机价格表构建')
    parser.add_argument('input', help='原始人材机数据 Excel 文件')
    parser.add_argument('-o', '--output', default=None, help='输出文件路径')
    parser.add_argument('-s', '--supplier', default='', help='供应商/成本来源')
    parser.add_argument('-d', '--date', default='', help='日期标记')
    parser.add_argument('-c', '--config-dir', default=None, help='配置文件目录')
    parser.add_argument('--no-l3', action='store_true', help='禁用自动L3检测')
    parser.add_argument('--l3-threshold', type=int, default=None, help='L3自动检测阈值')
    args = parser.parse_args()

    # 确定配置文件目录
    if args.config_dir:
        config_dir = args.config_dir
    else:
        config_dir = os.path.join(os.path.dirname(__file__), '..', 'config')

    # 加载配置
    hierarchy_cfg, rules_cfg = load_configs(config_dir)
    equip_sets = build_equipment_sets(rules_cfg)
    l3_classifiers = build_l3_classifiers(rules_cfg)
    rules = rules_cfg.get('rules', [])

    # 阈值
    l3_threshold = args.l3_threshold or hierarchy_cfg.get('l3_threshold', 30)

    # 输出路径
    if args.output:
        out_path = args.output
    else:
        src_dir = os.path.dirname(os.path.abspath(args.input))
        base = os.path.splitext(os.path.basename(args.input))[0]
        out_path = os.path.join(src_dir, f'{base}_分级版.xlsx')

    # 默认供应商和日期
    supplier = args.supplier or os.path.basename(args.input)
    date_val = args.date or ''

    # 读取输入
    df = pd.read_excel(args.input)
    print(f'Read {len(df)} rows from {args.input}')

    # 分类
    results = []
    for _, row in df.iterrows():
        name = str(row.get('名称', '')).strip()
        cat = str(row.get('专业', '')).strip()
        remark = str(row.get('备注', '')).strip() if pd.notna(row.get('备注', pd.NA)) else ''
        l1, l2, l3, spec = classify_row(name, cat, remark, rules, equip_sets, l3_classifiers)
        results.append((l1, l2, l3, spec, row))

    # 过滤汇总行
    filtered = []
    for item in results:
        name = str(item[4].get('名称', '')).strip()
        if name == '汇总':
            continue
        filtered.append(item)

    # 自动L3检测
    l2_counts = {}
    for l1, l2, l3, spec, row in filtered:
        l2_counts[(l1, l2)] = l2_counts.get((l1, l2), 0) + 1

    needs_l3 = set()
    if not args.no_l3:
        needs_l3 = {k for k, v in l2_counts.items() if v > l3_threshold}

    # extra_l3_map: 对部分L2（如《周转材料》）L3从数据行重新计算
    extra_l3_map = {}
    for classifier_name, mapping in l3_classifiers.items():
        if classifier_name not in ('labor_l3', 'concrete_l3', 'aggregate_l3',
                                    'pipe_l3', 'steel_l3', 'earthwork_l3'):
            # 这些是 extra_l3 分类器，用于在数据行层面重新分类
            pass

    # 对 filtered 中 needs_l3 但 l3 为 None 的项补充分类
    new_filtered = []
    for l1, l2, l3, spec, row in filtered:
        name = str(row.get('名称', '')).strip()
        unit = str(row.get('单位', '')).strip() if pd.notna(row.get('单位', pd.NA)) else ''
        key = (l1, l2)
        if key in needs_l3 and l3 is None:
            # Try extra L3 classifiers
            assigned = False
            for cname, crules in l3_classifiers.items():
                if cname in ('labor_l3', 'concrete_l3', 'aggregate_l3',
                             'pipe_l3', 'steel_l3', 'earthwork_l3'):
                    continue
                if cname == 'turnover_l3':
                    l3 = classify_by_l3_classifier(name, crules, '{其他周转}')
                    assigned = True
                    break
            if not assigned:
                l3 = '{其他}'
        new_filtered.append((l1, l2, l3, spec, row))
    filtered = new_filtered

    # 构建层级顺序
    l1_order, l2_orders, l3_orders = build_hierarchy_order(hierarchy_cfg)

    def sort_key(item):
        l1, l2, l3, spec, row = item
        name = str(row.get('名称', '')).strip().lower()
        return (
            l1_order.get(l1, 99),
            l2_orders.get(l1, {}).get(l2, 99),
            l3_orders.get(l1, {}).get(l2, {}).get(l3 or '', 99),
            name
        )

    filtered.sort(key=sort_key)

    # ==================== 写输出 ====================
    wb = xlsxwriter.Workbook(out_path, {'strings_to_urls': False})
    ws = wb.add_worksheet('人材机直接费汇总')

    # BOQ样式常量（引用 boq_hierarchy_rules.md）
    fmt_l1 = wb.add_format({
        'bold': True, 'font_size': 11, 'font_name': 'Microsoft YaHei UI',
        'font_color': '#1A1A1A', 'bg_color': '#C6D9F1',
        'valign': 'vcenter', 'border': 0,
    })
    fmt_l2 = wb.add_format({
        'bold': True, 'font_size': 10, 'font_name': 'Microsoft YaHei UI',
        'font_color': '#1A1A1A', 'bg_color': '#EEF2FA',
        'valign': 'vcenter', 'border': 0,
    })
    fmt_l3 = wb.add_format({
        'bold': True, 'font_size': 10, 'font_name': 'Microsoft YaHei UI',
        'font_color': '#1A1A1A', 'bg_color': '#FBE5D6',
        'valign': 'vcenter', 'border': 0,
    })
    fmt_header = wb.add_format({
        'bold': True, 'font_size': 10, 'font_name': 'Microsoft YaHei UI',
        'bg_color': '#4472C4', 'font_color': '#FFFFFF',
        'border': 1, 'text_wrap': True, 'valign': 'vcenter', 'align': 'center',
    })
    fmt_data = wb.add_format({
        'font_size': 9, 'font_name': 'Microsoft YaHei UI',
        'border': 1, 'valign': 'vcenter', 'border_color': '#BFBFBF',
    })
    fmt_price = wb.add_format({
        'font_size': 9, 'font_name': 'Microsoft YaHei UI',
        'border': 1, 'valign': 'vcenter', 'border_color': '#BFBFBF',
        'num_format': '#,##0.00',
    })
    fmt_price_zero = wb.add_format({
        'font_size': 9, 'font_name': 'Microsoft YaHei UI',
        'border': 1, 'valign': 'vcenter', 'border_color': '#BFBFBF',
        'num_format': '#,##0.00', 'font_color': '#FF0000',
    })

    # 列定义（从YAML配置读取）
    col_defs = hierarchy_cfg.get('output_columns', [
        {'name': '编号', 'width': 6}, {'name': '专业', 'width': 10},
        {'name': '名称', 'width': 48}, {'name': '项目特征', 'width': 22},
        {'name': '单位', 'width': 8}, {'name': '除税单价', 'width': 14},
        {'name': '税金', 'width': 10}, {'name': '含税单价', 'width': 14},
        {'name': '日期', 'width': 12}, {'name': '币种', 'width': 8},
        {'name': '供应商', 'width': 25}, {'name': '联系人', 'width': 8},
        {'name': '电话', 'width': 12}, {'name': '地址', 'width': 10},
        {'name': '备注', 'width': 38},
    ])
    n_cols = len(col_defs)

    for c, col in enumerate(col_defs):
        ws.set_column(c, c, col['width'])
        ws.write(0, c, col['name'], fmt_header)

    ws.set_row(0, 22)
    ws.freeze_panes(1, 0)

    r = 1
    seq = 0
    current_l1 = None
    current_l2 = None
    current_l3 = None

    for l1, l2, l3, spec, row_data in filtered:
        name = str(row_data.get('名称', '')).strip()
        feat = str(row_data.get('项目特征', '')) if pd.notna(row_data.get('项目特征', pd.NA)) else ''
        unit = str(row_data.get('单位', '')).strip()
        price = row_data.get('除税单价')
        price = float(price) if pd.notna(price) and price != '' else 0
        tax = row_data.get('税金', '')
        tax = '' if pd.isna(tax) else tax
        tax_incl = row_data.get('含税单价', '')
        tax_incl = '' if pd.isna(tax_incl) else tax_incl
        remark = str(row_data.get('备注', '')).strip() if pd.notna(row_data.get('备注', pd.NA)) else ''

        # L1 header
        if l1 != current_l1:
            current_l1 = l1
            current_l2 = None
            current_l3 = None
            ws.write(r, 0, 'P', fmt_l1)
            ws.write(r, 1, '', fmt_l1)
            ws.write(r, 2, l1, fmt_l1)
            for c in range(3, n_cols):
                ws.write(r, c, '', fmt_l1)
            ws.set_row(r, 16.5, None, {'level': 0})
            r += 1

        # L2 header
        if l2 != current_l2:
            current_l2 = l2
            current_l3 = None
            ws.write(r, 0, '', fmt_l2)
            ws.write(r, 1, '', fmt_l2)
            ws.write(r, 2, l2, fmt_l2)
            for c in range(3, n_cols):
                ws.write(r, c, '', fmt_l2)
            ws.set_row(r, 14.5, None, {'level': 1})
            r += 1

        # L3 header
        key = (l1, l2)
        if key in needs_l3 and l3 != current_l3:
            current_l3 = l3
            ws.write(r, 0, '', fmt_l3)
            ws.write(r, 1, '', fmt_l3)
            ws.write(r, 2, l3, fmt_l3)
            for c in range(3, n_cols):
                ws.write(r, c, '', fmt_l3)
            ws.set_row(r, 14.5, None, {'level': 2})
            r += 1

        # Data row
        seq += 1
        ws.write(r, 0, seq, fmt_data)
        ws.write(r, 1, spec, fmt_data)
        ws.write(r, 2, name, fmt_data)
        ws.write(r, 3, feat, fmt_data)
        ws.write(r, 4, unit, fmt_data)
        if price == 0:
            ws.write_number(r, 5, 0, fmt_price_zero)
        else:
            ws.write_number(r, 5, price, fmt_price)
        ws.write(r, 6, tax, fmt_data)
        ws.write(r, 7, tax_incl, fmt_data)
        ws.write(r, 8, date_val, fmt_data)
        ws.write(r, 9, hierarchy_cfg.get('default_currency', 'USD'), fmt_data)
        ws.write(r, 10, supplier, fmt_data)
        ws.write(r, 11, '', fmt_data)
        ws.write(r, 12, '', fmt_data)
        ws.write(r, 13, '', fmt_data)
        ws.write(r, 14, remark, fmt_data)
        data_level = 3 if current_l3 is not None else 2
        ws.set_row(r, 14.5, None, {'level': data_level})
        r += 1

    wb.close()

    # 统计
    l1_counts = {}
    l2c = {}
    l3c = {}
    for l1, l2, l3, spec, row in filtered:
        l1_counts[l1] = l1_counts.get(l1, 0) + 1
        l2c[(l1, l2)] = l2c.get((l1, l2), 0) + 1
        if l3:
            l3c[(l1, l2, l3)] = l3c.get((l1, l2, l3), 0) + 1

    print(f'\nTotal data rows: {seq}')
    print(f'Total lines (incl headers): {r}')
    print(f'\n=== L1 Distribution ===')
    for k, v in l1_counts.items():
        print(f'  {k}: {v}')
    print(f'\n=== L2 Distribution ===')
    for (l1, l2), v in sorted(l2c.items(), key=lambda x: (
        l1_order.get(x[0][0], 99), l2_orders.get(x[0][0], {}).get(x[0][1], 99)
    )):
        l3_flag = ' [L3]' if (l1, l2) in needs_l3 else ''
        print(f'  {l1} → {l2}: {v}{l3_flag}')
    if l3c:
        print(f'\n=== L3 Distribution ===')
        for (l1, l2, l3), v in sorted(l3c.items(), key=lambda x: (
            l1_order.get(x[0][0], 99), l2_orders.get(x[0][0], {}).get(x[0][1], 99)
        )):
            print(f'  {l3}: {v}')

    print(f'\nOutput: {out_path}')


if __name__ == '__main__':
    main()
