#!/usr/bin/env python3
"""Phase 1: 结构解析 — 目录解析 + 页面分类 + 章节映射 → structure.json

用法:
  python build_structure.py <pdf_path> --output output/structure.json
  python build_structure.py <pdf_path> --text-dir output/text/ --output output/structure.json
"""

import json, sys, re, os, io
from pathlib import Path
from collections import OrderedDict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CN_NUM = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}

def chinese_to_int(s):
    if s in CN_NUM:
        return CN_NUM[s]
    if s.startswith('十'):
        return 10 + (CN_NUM.get(s[1], 0) if len(s) > 1 else 0)
    if '十' in s:
        a, b = s.split('十', 1)
        return CN_NUM[a] * 10 + (CN_NUM.get(b, 0) if b else 0)
    return 0

# ─── 页面类型分类 ───

FOOTER_RE = re.compile(r'^\s*-\s*(\d{1,3})\s*-\s*$')
CHAPTER_RE = re.compile(r'^第([一二三四五六七八九十]+)章\s+(.+?)\s*\.{3,}\s*\((\d+)\)')
SECTION_RE = re.compile(r'^第([一二三四五六七八九十]+)节\s+(.+?)\s*\.{3,}\s*\((\d+)\)')
SUBSECTION_RE = re.compile(r'^([一二三四五六七八九十]+)、\s*(.+?)\s*\.{3,}\s*\((\d+)\)')
ITEM_RE = re.compile(r'^(\d+)\.\s+(.+?)\s*\.{3,}\s*\((\d+)\)')

def has_quota_codes(lines):
    codes = [l["text"].strip() for l in lines if re.match(r'^\d{5}$', l["text"].strip())]
    return len(codes) >= 3

def classify_page(lines, page_num):
    """判定页面类型"""
    full_text = "".join(l["text"] for l in lines)
    text_count = len([l for l in lines if l["text"].strip()])

    if text_count < 5:
        return "blank"

    if page_num <= 5 and ("行业标准" in full_text or "主编单位" in full_text):
        return "cover"

    if "公告" in full_text and "第" in full_text and "号" in full_text:
        return "notice"

    toc_score = len(re.findall(r'第[一二三四五六七八九十]+章', full_text))
    dots_count = full_text.count("...") + full_text.count("…")
    if toc_score >= 3 and dots_count >= 5:
        return "toc"

    if "总说明" in full_text and not has_quota_codes(lines):
        return "general_instruction"

    if re.search(r'^第[一二三四五六七八九十]+章\s', full_text) and text_count < 15:
        return "chapter_title"

    if "续表" in full_text or "续前表" in full_text:
        return "continued_table"

    if "附加说明" in full_text or "附录" in full_text:
        return "appendix"

    if has_quota_codes(lines):
        return "quota_table"

    if re.search(r'第[一二三四五六七八九十]+节', full_text) or "说明" in full_text:
        return "section_intro"

    return "general_instruction"

# ─── 目录解析 ───

def parse_toc(toc_pages, lines_by_page):
    """从目录页提取章节树"""
    chapters = []
    stack = []  # 用于追踪层级

    for pg in sorted(toc_pages):
        lines = lines_by_page[pg]
        full_text = " ".join(l["text"] for l in lines)

        for line in full_text.split("\n"):  # 简化: 按原始文本块处理
            pass  # 实际需要更精细的逐行解析

    return chapters

def extract_internal_page(lines):
    """从页脚提取内部页码"""
    for l in reversed(lines):
        m = FOOTER_RE.match(l["text"].strip())
        if m:
            return int(m.group(1))
    return None

# ─── 主流程 ───

def build_structure(pdf_path, text_dir=None, output_path=None):
    """主入口：解析 PDF 结构"""
    import fitz

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    if text_dir is None:
        text_dir = Path(pdf_path).parent / "text"
    text_dir = Path(text_dir)
    output_path = Path(output_path) if output_path else Path("output/structure.json")

    page_map = {}
    page_types = {}
    internal_to_pdf = {}

    print(f"Analyzing {total_pages} pages...")

    # 第一遍：提取每页文本 + 分类
    all_lines = {}
    for pg in range(total_pages):
        page = doc[pg]
        blocks = page.get_text("dict")["blocks"]
        lines = []
        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if text:
                        lines.append({
                            "text": text,
                            "x": round(span["bbox"][0], 1),
                            "y": round(span["bbox"][1], 1),
                        })

        all_lines[pg + 1] = lines
        page_type = classify_page(lines, pg + 1)
        page_types[pg + 1] = page_type

        # 提取内部页码
        internal = extract_internal_page(lines)
        if internal is not None:
            internal_to_pdf[internal] = pg + 1

    # 第二遍：解析目录
    toc_pages = [pg for pg, t in page_types.items() if t == "toc"]
    chapters = parse_toc(toc_pages, all_lines) if toc_pages else []

    # 第三遍：构建 page_map
    for pg in range(1, total_pages + 1):
        page_map[str(pg)] = {
            "type": page_types.get(pg, "unknown"),
            "pdf_page": pg,
        }

        lines = all_lines.get(pg, [])
        internal = extract_internal_page(lines)
        if internal is not None:
            page_map[str(pg)]["internal_page"] = internal

    doc.close()

    result = {
        "document": {
            "title": doc.metadata.get("title", Path(pdf_path).stem),
            "total_pages": total_pages,
        },
        "page_map": page_map,
        "chapters": chapters,
        "internal_to_pdf": {str(k): v for k, v in internal_to_pdf.items()},
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 统计
    type_counts = {}
    for info in page_map.values():
        t = info["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"\nStructure saved to {output_path}")
    print(f"Page types:")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")
    print(f"TOC pages: {toc_pages}")
    print(f"Internal pages mapped: {len(internal_to_pdf)}")

    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build document structure from quota PDF")
    ap.add_argument("pdf_path", help="Path to PDF file")
    ap.add_argument("--text-dir", help="Directory with pre-extracted text JSON")
    ap.add_argument("--output", default="output/structure.json", help="Output path")
    args = ap.parse_args()

    build_structure(args.pdf_path, args.text_dir, args.output)
