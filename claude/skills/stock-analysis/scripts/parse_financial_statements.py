#!/usr/bin/env python3
"""
从中间格式 Markdown 表格提取财务数据，输出结构化 JSON。
用法: python parse_financial_statements.py <中间格式目录> [--company 公司名] [-o output.json]
"""

import re
import os
import json
import sys
import glob
from collections import defaultdict


def parse_md_table(md_path):
    """解析Markdown文件中的表格，返回 {sheet_name: [rows]}"""
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    tables = {}
    current_sheet = None
    current_rows = []
    in_table = False
    header_sep = False

    for line in content.split("\n"):
        stripped = line.strip()

        if stripped.startswith("## "):
            if current_sheet and current_rows:
                tables[current_sheet] = current_rows
            current_sheet = stripped[3:].strip()
            current_rows = []
            in_table = False
            header_sep = False
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if header_sep and all(re.match(r"^[-:]+$", c) for c in cells if c):
                header_sep = False
                continue
            if not in_table:
                in_table = True
            current_rows.append(cells)
        elif in_table and not stripped:
            in_table = False

    if current_sheet and current_rows:
        tables[current_sheet] = current_rows

    return tables


def extract_company_name(dir_path, given_name=None):
    """从目录路径或给定名称提取公司名"""
    if given_name:
        return given_name
    dir_name = os.path.basename(dir_path.rstrip("/\\"))
    return dir_name


def find_md_files(data_dir):
    """查找所有中间格式MD文件"""
    files = {}
    file_types = {
        "main": "_主要财务指标.md",
        "benefit": "_利润表.md",
        "cash": "_现金流量表.md",
        "debt": "_资产负债表.md",
        "diy": "_自定义指标.md",
    }

    for key, suffix in file_types.items():
        matches = glob.glob(os.path.join(data_dir, f"*{suffix}"))
        if matches:
            files[key] = matches[0]

    # 年报/季报
    for pattern in ["*年度报告.md", "*半年度报告.md", "*Q1报告.md", "*季度报告.md"]:
        matches = glob.glob(os.path.join(data_dir, pattern))
        for m in matches:
            bn = os.path.basename(m)
            if "年度报告" in bn and "半年度" not in bn:
                files["annual_report"] = m
            elif "半年度" in bn:
                files["semi_report"] = m
            elif "Q1" in bn or "一季度" in bn or "第一季度" in bn:
                files["q1_report"] = m
            elif "Q3" in bn or "三季度" in bn or "第三季度" in bn:
                files["q3_report"] = m

    return files


def parse_value(val_str):
    """解析带单位的数值字符串"""
    if not val_str:
        return None
    val_str = val_str.strip()
    if val_str in ("-", "", "--", "N/A", "不适用"):
        return None
    try:
        if val_str.endswith("%"):
            return float(val_str[:-1])
        if "亿" in val_str:
            return float(val_str.replace("亿", "")) * 1e8
        if "万" in val_str:
            return float(val_str.replace("万", "")) * 1e4
        return float(val_str.replace(",", ""))
    except ValueError:
        return val_str


def build_indicator_time_series(tables):
    """从表格构建指标→时间序列映射"""
    series = defaultdict(dict)

    for sheet_name, rows in tables.items():
        if len(rows) < 2:
            continue
        header = rows[0]
        date_cols = header[1:]  # 第一列是"科目\时间"

        for row in rows[1:]:
            if not row:
                continue
            indicator = row[0].strip()
            if not indicator:
                continue
            for i, date in enumerate(date_cols):
                if i + 1 >= len(row):
                    break
                val = parse_value(row[i + 1])
                if val is not None:
                    series[indicator][date] = val

    return dict(series)


def compute_derived_metrics(series):
    """从原始数据计算衍生指标"""
    derived = {}

    # 近3年和5年CAGR
    for metric in ["净利润(元)", "营业总收入(元)", "扣非净利润(元)"]:
        if metric in series:
            dates = sorted(series[metric].keys(), reverse=True)
            vals = [series[metric][d] for d in dates if series[metric][d] is not None]
            if len(vals) >= 4:
                derived[f"{metric}_3Y_CAGR"] = (vals[0] / vals[3]) ** (1 / 3) - 1
            if len(vals) >= 6:
                derived[f"{metric}_5Y_CAGR"] = (vals[0] / vals[5]) ** (1 / 5) - 1

        # 修正: 使用标准名称
        if metric == "营业总收入(元)":
            metric2 = "营业总收入"
            if metric2 in series:
                dates = sorted(series[metric2].keys(), reverse=True)
                vals = [series[metric2][d] for d in dates if series[metric2][d] is not None]
                if len(vals) >= 4:
                    derived[f"{metric}_3Y_CAGR"] = (vals[0] / vals[3]) ** (1 / 3) - 1
                if len(vals) >= 6:
                    derived[f"{metric}_5Y_CAGR"] = (vals[0] / vals[5]) ** (1 / 5) - 1

    return derived


def analyze_annual_report_text(md_path):
    """从年报MD提取关键文本信息"""
    if not md_path or not os.path.exists(md_path):
        return {}

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    keywords_map = {
        "管理层讨论": [
            "管理层讨论与分析", "经营情况讨论与分析", "董事会报告",
            "管理层分析与讨论", "经营层讨论与分析",
        ],
        "研发投入": ["研发投入", "研发费用", "开发支出"],
        "核心竞争力": ["核心竞争力", "核心竞争优势", "技术优势"],
        "风险因素": ["风险因素", "可能面对的风险", "风险提示", "风险分析"],
        "行业格局": ["行业格局", "行业发展趋势", "行业竞争格局"],
        "分红": ["利润分配", "现金分红", "分红方案", "股利分配"],
    }

    findings = {}
    for topic, keywords in keywords_map.items():
        for kw in keywords:
            idx = content.find(kw)
            if idx >= 0:
                start = max(0, idx - 100)
                end = min(len(content), idx + 1500)
                snippet = content[start:end]
                # 按段落切分，取包含关键词的段落
                paras = snippet.split("\n\n")
                relevant = [p.strip() for p in paras if kw in p and len(p.strip()) > 20]
                if relevant:
                    findings[topic] = relevant[:3]  # 最多取3个段落
                    break

    return findings


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    company_name = None
    out_file = None

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--company" and i + 1 < len(args):
            company_name = args[i + 1]
            i += 2
        elif args[i] == "-o" and i + 1 < len(args):
            out_file = args[i + 1]
            i += 2
        else:
            i += 1

    if not os.path.isdir(data_dir):
        print(f"ERROR: {data_dir} is not a valid directory")
        sys.exit(1)

    company = extract_company_name(data_dir, company_name)
    files = find_md_files(data_dir)

    result = {
        "company": company,
        "data_dir": data_dir,
        "files_found": {k: os.path.basename(v) for k, v in files.items()},
        "missing_files": [
            k for k in ["main", "benefit", "cash", "debt", "diy"]
            if k not in files
        ],
        "financial_data": {},
        "derived_metrics": {},
        "annual_report_findings": {},
        "semi_report_findings": {},
        "q1_report_findings": {},
    }

    # 解析财务表
    for key in ["main", "benefit", "cash", "debt", "diy"]:
        if key in files:
            tables = parse_md_table(files[key])
            series = build_indicator_time_series(tables)
            result["financial_data"][key] = {
                "indicators": list(series.keys()),
                "date_count": len(next(iter(series.values()), {})),
                "series": series,
            }
            if key == "main":
                result["derived_metrics"] = compute_derived_metrics(series)

    # 分析年报文本
    for report_key in ["annual_report", "semi_report", "q1_report"]:
        if report_key in files:
            findings = analyze_annual_report_text(files[report_key])
            result[f"{report_key}_findings"] = findings

    # 输出
    if out_file:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Output saved to {out_file}")
    else:
        # 默认输出到源目录
        out_path = os.path.join(data_dir, f"{company}_financial_data.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Output saved to {out_path}")

    # 摘要
    print(f"\nCompany: {company}")
    print(f"Files found: {len(files)} / {len(files) + len(result['missing_files'])}")
    if result["missing_files"]:
        print(f"Missing: {', '.join(result['missing_files'])}")
    if "main" in result["financial_data"]:
        indicators = result["financial_data"]["main"]["indicators"]
        key_indicators = [i for i in indicators if any(
            kw in i for kw in ["净利润", "营收", "ROE", "毛利率", "每股收益"]
        )]
        print(f"Key indicators found: {key_indicators[:10]}")
    if result["derived_metrics"]:
        print(f"Derived metrics: {list(result['derived_metrics'].keys())}")


if __name__ == "__main__":
    main()
