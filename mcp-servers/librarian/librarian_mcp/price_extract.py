"""
价格提取管线：从 MD source_note 中识别价格表格并结构化入库 price_index。

三层过滤：
  第一道：文件名/路径关键词（脚本，0 token）
  第二道：表格密度 + 价格列模式（脚本，0 token）
  第三道：LLM 确认（Flash，极低 token）

用法:
  python price_extract.py --classify          # 扫描全部 source_note，输出候选清单 JSON
  python price_extract.py --tables <vault_path>  # 提取指定文件的候选价格表格片段
  python price_extract.py --insert <vault_path> --records <json>  # 写入 price_index
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

LIBRARY_DIR = Path("F:/FeynmanLibrary/.library")
VAULT_ROOT = Path("F:/FeynmanLibrary")

# ── 第一道：文件名/路径信号 ──────────────────────────────────────────
PRICE_KEYWORDS_IN_FILENAME = [
    "价格", "报价", "市场价", "信息价", "造价", "单价", "报价单",
    "price", "rate", "quotation", "price list", "cost data",
    "材料价", "设备价", "厂商报价", "供应商",
]

PRICE_PATH_PREFIXES = [
    "DocWork/工作/信息价",
    "DocWork/工作/报价",
    "Knowledge/Construction_Cost/Price",
    "Knowledge/Construction_Cost/Reports",
]


def _filename_signals(vault_path: str) -> bool:
    """第一道：文件名或路径含价格关键词。"""
    lower = vault_path.lower()
    for kw in PRICE_KEYWORDS_IN_FILENAME:
        if kw in lower:
            return True
    for prefix in PRICE_PATH_PREFIXES:
        if lower.startswith(prefix.lower()):
            return True
    return False


# ── 第二道：内容级信号 ──────────────────────────────────────────────
PRICE_COLUMN_PATTERNS = [
    re.compile(r"(?:单价|价格|市场价|信息价|报价|含税价|除税价|综合单价|材料单价)"),
    re.compile(r"(?:unit\s*price|rate|cost|price)"),
]

PRICE_TABLE_HEADING = re.compile(
    r"(?:价格表|报价单|市场价|信息价|单价表|价格信息|Price\s*information|厂商报价)",
)
PRICE_UNIT_LINE = re.compile(r"(?:单位[：:]\s*(?:元|美元|USD|RMB))")
NUMERIC_LINE = re.compile(r"^\s*\d{2,6}(?:[.]\d{1,2})?\s*$")


def _table_density_signals(md_content: str) -> tuple[bool, int]:
    """第二道：表格密度 + 价格列模式。同时检测 Markdown 表格和原始文本表格。"""
    lines = md_content.split("\n")

    # 检测 Markdown 表格（|---| 分隔）
    md_table_seps = sum(1 for line in lines if re.match(r"^\|[\s\-:|]+\|$", line.strip()))

    # 检测原始文本表格：连续数字行密度
    numeric_line_indices = []
    price_heading_line = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if PRICE_TABLE_HEADING.search(stripped) or PRICE_UNIT_LINE.search(stripped):
            price_heading_line = i
        if NUMERIC_LINE.match(stripped):
            numeric_line_indices.append(i)

    # 在价格标题后 200 行内的数字行数
    nearby_numeric = 0
    if price_heading_line >= 0:
        window_end = min(price_heading_line + 200, len(lines))
        nearby_numeric = sum(1 for idx in numeric_line_indices if price_heading_line < idx <= window_end)

    # 通过条件：MD 表格足够多，或原始数字密度足够高
    if md_table_seps >= 3:
        # 检查 Markdown 表头含价格关键词
        header_found = False
        for line in lines:
            stripped = line.strip()
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                continue
            if "|" not in stripped:
                continue
            for pattern in PRICE_COLUMN_PATTERNS:
                if pattern.search(stripped):
                    header_found = True
                    break
            if header_found:
                break
        numeric_ratio = _md_table_numeric_ratio(lines)
        if header_found and numeric_ratio > 0.25:
            return True, md_table_seps

    if nearby_numeric >= 5:
        return True, nearby_numeric

    return False, 0


def _md_table_numeric_ratio(lines: list[str]) -> float:
    """计算 Markdown 表格中数字单元格占比。"""
    table_lines = [l for l in lines if "|" in l and not re.match(r"^\|[\s\-:|]+\|$", l.strip())]
    numeric = 0
    total = 0
    for line in table_lines:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        for cell in cells:
            total += 1
            if re.match(r"^[\d,]+\.?\d*$", cell):
                numeric += 1
    return numeric / max(total, 1)


# ── 表格/数值段落提取 ─────────────────────────────────────────────────
def extract_table_blocks(md_content: str, max_blocks: int = 10) -> list[str]:
    """从 MD 中提取候选价格表格段落（兼容 Markdown 表格和原始文本表格）。"""
    lines = md_content.split("\n")
    blocks = []

    # 先找价格相关的标题行作为锚点
    anchor_indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if PRICE_TABLE_HEADING.search(stripped) or PRICE_UNIT_LINE.search(stripped):
            anchor_indices.append(i)

    # 也从 Markdown 表格分隔行找锚点
    for i, line in enumerate(lines):
        if re.match(r"^\|[\s\-:|]+\|$", line.strip()):
            anchor_indices.append(i)

    anchor_indices = sorted(set(anchor_indices))

    for anchor_idx in anchor_indices[:max_blocks]:
        # 扩展范围：标题前 5 行到后 80 行
        start = max(0, anchor_idx - 5)
        end = min(len(lines), anchor_idx + 80)
        block_text = "\n".join(lines[start:end])
        if len(block_text) > 150:
            blocks.append(block_text)

    # 如果锚点不够，按窗口扫描数字密集区
    if len(blocks) < 2:
        blocks.extend(_scan_numeric_windows(lines, max_blocks - len(blocks)))

    return blocks[:max_blocks]


def _scan_numeric_windows(lines: list[str], max_blocks: int) -> list[str]:
    """扫描数字密集窗口（用于没有明确价格标题的文件）。"""
    blocks = []
    window_size = 60
    step = 30

    for start in range(0, len(lines) - window_size, step):
        if len(blocks) >= max_blocks:
            break
        window = lines[start:start + window_size]
        numeric_count = sum(1 for l in window if NUMERIC_LINE.match(l.strip()))
        unit_price_count = sum(1 for l in window if PRICE_UNIT_LINE.search(l))
        heading_count = sum(1 for l in window if PRICE_TABLE_HEADING.search(l))
        if numeric_count >= 8 or (numeric_count >= 4 and (unit_price_count or heading_count)):
            block_text = "\n".join(window)
            if len(block_text) > 150:
                blocks.append(block_text)

    return blocks


def build_extraction_prompt(table_blocks: list[str], source_name: str) -> str:
    """构建给 Flash 的价格提取提示词。"""
    blocks_text = "\n\n---\n\n".join(table_blocks[:5])
    return f"""提取以下表格中的材料价格信息。来源文件：{source_name}

{blocks_text}

请对每个可识别的材料/产品条目，提取：
- material_name: 材料名称+规格（如 "YJV 0.6/1KV 铜芯电力电缆 3×4mm²"）
- price_value: 价格数值（纯数字，如 "19580"）
- unit: 价格单位（如 "元/KM"、"元/米"、"元/吨"）
- note: 补充信息（如供应商名、品牌、阻燃等级）

返回 JSON 数组格式。如果某行无法识别材料名或价格，跳过该行。"""


# ── 扫描分类 ─────────────────────────────────────────────────────────
def classify_all() -> list[dict]:
    """扫描所有 source_note，返回通过前两道过滤的候选文件清单。"""
    import sqlite3
    from librarian_mcp.config import DB_PATH

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT d.vault_path, d.title, d.type, d.file_mtime
        FROM documents d
        WHERE d.type = 'source_note'
        ORDER BY d.vault_path
        """
    ).fetchall()
    conn.close()

    candidates = []
    for row in rows:
        vault_path = row["vault_path"]

        # 第一道
        if not _filename_signals(vault_path):
            continue

        # 第二道
        md_path = VAULT_ROOT / vault_path
        if not md_path.exists():
            continue
        try:
            content = md_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        passed, table_count = _table_density_signals(content)
        if not passed:
            continue

        # 提取表格片段用于第三道
        blocks = extract_table_blocks(content)
        candidates.append(
            {
                "vault_path": vault_path,
                "title": row["title"],
                "table_count": table_count,
                "candidate_block_count": len(blocks),
                "char_count": len(content),
            }
        )

    return candidates


# ── 写入 price_index ────────────────────────────────────────────────
def insert_price_records(vault_path: str, records: list[dict]) -> int:
    """将结构化价格记录写入 price_index。"""
    import sqlite3
    from librarian_mcp.config import DB_PATH

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 查找 document_id
    doc = conn.execute("SELECT id, vault_path, source_path FROM documents WHERE vault_path = ?", (vault_path,)).fetchone()
    if not doc:
        conn.close()
        return 0

    source_name = Path(vault_path).name
    now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    inserted = 0
    for rec in records:
        material_name = _normalize(str(rec.get("material_name", "")))
        price_value = _normalize(str(rec.get("price_value", "")))
        if not material_name or not price_value:
            continue

        unit = _normalize(str(rec.get("unit", "")))
        price_text = _normalize(str(rec.get("price_text", ""))) or price_value
        note = _normalize(str(rec.get("note", "")))
        lookup_key = " ".join(p for p in [material_name, price_value, unit] if p)
        material_name_key = _material_key(material_name)
        price_numeric = _parse_float(price_value)

        cursor = conn.execute(
            """
            INSERT INTO price_index(
                document_id, source_note_path, source_path, source_name,
                material_name, material_name_key, unit, price_text,
                price_value, price_value_numeric, note,
                lookup_key, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc["id"], vault_path, doc["source_path"], source_name,
                material_name, material_name_key, unit, price_text,
                price_value, price_numeric, note,
                lookup_key, now_iso,
            ),
        )
        record_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO price_fts(material_name, unit, price_text, note, lookup_key, source_name, record_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (material_name, unit, price_text, note, lookup_key, source_name, record_id),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def _normalize(text: str) -> str:
    import unicodedata
    text = str(text or "").strip()
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _material_key(name: str) -> str:
    """生成材料名的标准化 key，用于精确匹配。"""
    return re.sub(r"[^\w一-鿿]+", "", name.lower())


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value.replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return None


# ── CLI ───────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("用法: price_extract.py --classify | --tables <vault_path> | --insert <vault_path> --records '<json>'",
              file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    try:
        if cmd == "--classify":
            candidates = classify_all()
            print(json.dumps({"ok": True, "candidates": candidates, "count": len(candidates)},
                             ensure_ascii=False, indent=2))

        elif cmd == "--tables":
            if len(sys.argv) < 3:
                print("缺少 vault_path 参数", file=sys.stderr)
                sys.exit(1)
            vault_path = sys.argv[2]
            md_path = VAULT_ROOT / vault_path
            if not md_path.exists():
                print(json.dumps({"ok": False, "error": f"文件不存在: {vault_path}"}, ensure_ascii=False))
                sys.exit(1)
            content = md_path.read_text(encoding="utf-8", errors="ignore")
            blocks = extract_table_blocks(content)
            passed, _ = _table_density_signals(content)
            print(json.dumps({
                "ok": True,
                "vault_path": vault_path,
                "passed_filters": passed,
                "block_count": len(blocks),
                "blocks": blocks[:10],
            }, ensure_ascii=False, indent=2))

        elif cmd == "--insert":
            if len(sys.argv) < 4:
                print("缺少参数", file=sys.stderr)
                sys.exit(1)
            vault_path = sys.argv[2]
            records = json.loads(sys.argv[3])
            count = insert_price_records(vault_path, records)
            print(json.dumps({"ok": True, "inserted": count}, ensure_ascii=False))

        else:
            print(f"未知命令: {cmd}", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
