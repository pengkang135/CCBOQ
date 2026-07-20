#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
定额数据库清洗与校验

用法:
  python db_clean.py <db_path>              # 执行全部清洗
  python db_clean.py <db_path> --dry-run    # 仅校验，不写入
  python db_clean.py <db_path> --validate   # 仅输出校验报告

也可作为模块导入:
  from db_clean import clean_all, clean_units, validate_units, rebuild_views
"""

import json
import re
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

RULES_DIR = Path(__file__).resolve().parent.parent / "config"
RULES_PATH = RULES_DIR / "cleaning_rules.json"


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── Unit cleaning ───────────────────────────────────────────

def clean_unit(unit, rules=None):
    """
    清洗单个单位字符串：去除中文描述、修正OCR误识别。
    '10m³混凝土' → '10m³'
    'l000m2' → '1000m2'
    '1试段' → '1试段'（保留多字中文单位）
    """
    if not unit or not isinstance(unit, str) or not unit.strip():
        return unit

    if rules is None:
        rules = load_rules()
    uc = rules["unit_cleaning"]

    # OCR fixes
    for fix in uc["ocr_fixes"]:
        unit = re.sub(fix["pattern"], fix["replacement"], unit)

    # Latin-letter units: take prefix, strip trailing Chinese
    if re.search(r'[a-zA-Z²³¹⁰⁴⁵⁶⁷⁸⁹]', unit):
        m = re.match(uc["latin_unit_pattern"], unit)
        if m:
            return m.group(1)

    # Known multi-character Chinese units
    for mcu in uc["multi_char_cn_units"]:
        if mcu in unit:
            m = re.match(r'([\d.]+\s*' + re.escape(mcu) + ')', unit)
            if m:
                return m.group(1)

    # Single-character Chinese units
    m = re.match(uc["single_char_cn_pattern"], unit)
    if m:
        return m.group(1)

    return unit


def clean_units_db(db_path, dry_run=False):
    """
    清洗 norms_table.unit 列。
    返回 (updated_count, details_list)
    """
    conn = sqlite3.connect(str(db_path))
    rules = load_rules()

    rows = conn.execute(
        "SELECT id, unit FROM norms_table WHERE unit IS NOT NULL AND unit != ''"
    ).fetchall()

    updates = []
    skipped_section_headers = 0
    for row_id, unit in rows:
        cleaned = clean_unit(unit, rules)
        if cleaned != unit:
            updates.append((cleaned, row_id))
        else:
            skipped_section_headers += 1

    if not dry_run and updates:
        conn.executemany(
            "UPDATE norms_table SET unit = ? WHERE id = ?", updates
        )
        conn.commit()

    conn.close()
    return len(updates), len(rows)


def extract_unit_from_work_content(work_content):
    """尝试从 work_content 尾部提取单位。先OCR修正再匹配字符串末尾的数值+单位模式。"""
    if not work_content:
        return ""
    rules = load_rules()
    uc = rules["unit_cleaning"]
    # Apply OCR fixes to the raw text first (l→1, etc.)
    text = work_content
    for fix in uc["ocr_fixes"]:
        text = re.sub(fix["pattern"], fix["replacement"], text)
    pattern = uc["latin_unit_pattern"] + r'(?:\s*[一-鿿]+)?$'
    m = re.search(pattern, text)
    if m:
        return clean_unit(m.group(1).strip(), rules)
    return ""


def fill_missing_units(db_path, dry_run=False):
    """
    为 norms_table 中缺失单位的行尝试从 work_content 提取。
    返回 (filled_count, still_missing)
    """
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, work_content FROM norms_table WHERE unit IS NULL OR unit = ''"
    ).fetchall()

    updates = []
    still_missing = 0
    for row_id, wc in rows:
        extracted = extract_unit_from_work_content(wc)
        if extracted:
            updates.append((extracted, row_id))
        else:
            still_missing += 1

    if not dry_run and updates:
        conn.executemany(
            "UPDATE norms_table SET unit = ? WHERE id = ?", updates
        )
        conn.commit()

    conn.close()
    return len(updates), still_missing


# ─── Validation ──────────────────────────────────────────────

def validate_units(db_path):
    """校验 norms_table.unit 列质量，返回报告 dict。"""
    conn = sqlite3.connect(str(db_path))
    rules = load_rules()
    uv = rules["unit_validation"]

    total = conn.execute("SELECT COUNT(*) FROM norms_table").fetchone()[0]
    null_count = conn.execute(
        "SELECT COUNT(*) FROM norms_table WHERE unit IS NULL OR unit = ''"
    ).fetchone()[0]
    distinct = conn.execute(
        "SELECT DISTINCT unit FROM norms_table WHERE unit IS NOT NULL AND unit != '' ORDER BY unit"
    ).fetchall()
    distinct_units = [r[0] for r in distinct]

    # Check against allowed patterns
    unknown_units = []
    for u in distinct_units:
        ok = any(re.match(p, u) for p in uv["allowed_patterns"])
        if not ok:
            unknown_units.append(u)

    # Chinese chars check — only flag units with Chinese that don't match any allowed pattern
    cn_units = []
    if uv.get("warn_chinese_chars"):
        cn_units = [u for u in distinct_units
                    if re.search(r'[一-鿿]', u)
                    and not any(re.match(p, u) for p in uv["allowed_patterns"])]

    null_pct = (null_count / total * 100) if total > 0 else 0

    conn.close()
    return {
        "total_tables": total,
        "null_units": null_count,
        "null_pct": round(null_pct, 1),
        "null_pct_ok": null_pct <= uv["max_null_pct"],
        "distinct_units": distinct_units,
        "unknown_units": unknown_units,
        "cn_units": cn_units,
        "clean": len(unknown_units) == 0 and len(cn_units) == 0,
    }


def validate_integrity(db_path):
    """数据库结构完整性检查。"""
    conn = sqlite3.connect(str(db_path))
    rules = load_rules()
    ic = rules["integrity_checks"]

    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    existing_names = {r[0] for r in existing}

    missing_tables = [t for t in ic["expected_tables"] if t not in existing_names]

    chapter_count = conn.execute("SELECT COUNT(*) FROM chapter").fetchone()[0]
    table_count = conn.execute("SELECT COUNT(*) FROM norms_table").fetchone()[0]
    item_count = conn.execute("SELECT COUNT(*) FROM norms_item").fetchone()[0]

    # Code length distribution
    code_lens = conn.execute(
        "SELECT LENGTH(norms_code), COUNT(*) FROM norms_item GROUP BY LENGTH(norms_code)"
    ).fetchall()
    code_dist = {str(r[0]): r[1] for r in code_lens}

    conn.close()

    issues = []
    if missing_tables:
        issues.append(f"Missing tables: {', '.join(missing_tables)}")
    if chapter_count < ic["min_chapter_count"]:
        issues.append(f"Chapter count {chapter_count} < {ic['min_chapter_count']}")
    if table_count < ic["min_norms_table_count"]:
        issues.append(f"Table count {table_count} < {ic['min_norms_table_count']}")
    if item_count < ic["min_norms_item_count"]:
        issues.append(f"Item count {item_count} < {ic['min_norms_item_count']}")

    warn_lengths = set(ic["code_length_distribution"]["warn_on"])
    unexpected_lens = {k: v for k, v in code_dist.items() if int(k) in warn_lengths}
    expected_lens = set(ic["code_length_distribution"]["expected"])
    missing_lens = [l for l in expected_lens if str(l) not in code_dist]

    return {
        "chapter_count": chapter_count,
        "norms_table_count": table_count,
        "norms_item_count": item_count,
        "code_length_distribution": code_dist,
        "missing_tables": missing_tables,
        "issues": issues,
        "unexpected_code_lengths": unexpected_lens,
        "missing_expected_code_lengths": missing_lens,
    }


def validate_null_unit_rows(db_path, limit=30):
    """检查单位为空的行，帮助判断是数据缺失还是章节标题行。"""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, section_title, work_content FROM norms_table "
        "WHERE unit IS NULL OR unit = '' LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "section_title": r[1], "work_content": (r[2] or "")[:80]}
        for r in rows
    ]


# ─── Cost item unit normalization ──────────────────────────────

def _infer_unit(cost_item):
    """Infer the correct unit for a cost_item based on name heuristics."""
    mech_kw = ("机", "船", "车", "泵", "钻", "搅拌", "起重", "装载", "推土",
               "压路", "打桩", "挖掘", "自卸", "拖轮", "驳", "发电", "空压",
               "电焊", "对焊", "抓斗", "潜孔钻", "打桩门架")
    for kw in mech_kw:
        if kw in cost_item:
            return "台班"
    if cost_item == "人工":
        return "工日"
    if cost_item == "潜水组":
        return "组日"
    if cost_item == "其他材料":
        return "%"
    if cost_item == "其他船机":
        return "%"
    return None


def infer_null_units(db_path, dry_run=False):
    """推断并回填空缺的定额单位（norms_table.unit）。

    两阶段策略：
    1. 对 section_title 非空的表，按关键词匹配推断单位
    2. 对仅出现在 continued_table 页面的表，从同章前序表继承单位
       （支持链式继承：连续多页 continued_table 逐级回溯）

    返回 (total_fixed, keyword_matched, inherited, remaining)
    """
    conn = sqlite3.connect(str(db_path))
    rules = load_rules()
    keyword_rules = rules.get("unit_inference", {}).get("keyword_rules", [])

    keyword_rules_sorted = sorted(
        keyword_rules,
        key=lambda r: max(len(kw) for kw in r["keywords"]),
        reverse=True,
    )

    # --- Step 1: identify all NULL-unit tables ---
    null_rows = conn.execute("""
        SELECT nt.id, nt.page, nt.chapter_id, nt.section_title
        FROM norms_table nt
        WHERE nt.unit IS NULL OR nt.unit = ''
        ORDER BY nt.page
    """).fetchall()

    if not null_rows:
        conn.close()
        return 0, 0, 0, 0

    # Build page→table lookup for the whole DB (needed for inheritance)
    all_tables = conn.execute("""
        SELECT nt.id, nt.page, nt.chapter_id, nt.unit, nt.section_title
        FROM norms_table nt
        ORDER BY nt.page
    """).fetchall()

    page_map = {}  # page → (table_id, chapter_id, unit)
    for t in all_tables:
        tid, page, ch_id, unit, title = t
        if page is not None:
            page_map[page] = (tid, ch_id, unit, title)

    # --- Step 2: keyword matching for tables with section_title ---
    kw_fixes = {}  # table_id → unit
    kw_matched = 0

    for tid, page, ch_id, title in null_rows:
        if not title or not title.strip():
            continue
        for rule in keyword_rules_sorted:
            matched = False
            for kw in rule["keywords"]:
                if kw in title:
                    kw_fixes[tid] = rule["unit"]
                    matched = True
                    break
            if matched:
                break

    kw_matched = len(kw_fixes)

    # --- Step 3: continued_table inheritance ---
    # For each NULL-unit table that lacks a norms_table first-page,
    # walk backwards by page in the same chapter until a unit is found.
    inherited = 0
    inh_fixes = {}  # table_id → unit

    for tid, page, ch_id, title in null_rows:
        if tid in kw_fixes:
            continue  # Already fixed by keyword
        if page is None:
            continue

        # Walk backwards to find a predecessor with a unit
        inherited_unit = None
        for prev_page in range(page - 1, 0, -1):
            if prev_page not in page_map:
                continue
            prev_tid, prev_ch, prev_unit, prev_title = page_map[prev_page]
            if prev_ch != ch_id:
                continue

            # Check if predecessor has a unit (original or fixed by keyword)
            resolved_unit = prev_unit
            if not resolved_unit and prev_tid in kw_fixes:
                resolved_unit = kw_fixes[prev_tid]
            if not resolved_unit and prev_tid in inh_fixes:
                resolved_unit = inh_fixes[prev_tid]

            if resolved_unit:
                inherited_unit = resolved_unit
                break

        if inherited_unit:
            inh_fixes[tid] = inherited_unit

    inherited = len(inh_fixes)

    # --- Step 4: apply ---
    all_fixes = [(unit, tid) for tid, unit in kw_fixes.items()]
    all_fixes += [(unit, tid) for tid, unit in inh_fixes.items()]

    if not dry_run and all_fixes:
        conn.executemany(
            "UPDATE norms_table SET unit = ? WHERE id = ?", all_fixes
        )
        conn.commit()

    remaining = len(null_rows) - len(all_fixes)

    if not dry_run:
        if kw_matched:
            print(f"  关键词推断: {kw_matched} 条")
        if inherited:
            print(f"  续表继承: {inherited} 条")
        if remaining:
            print(f"  仍未匹配: {remaining} 条")

    conn.close()
    return len(all_fixes), kw_matched, inherited, remaining


def normalize_cost_item_units(db_path, dry_run=False):
    """Fix cost_item_unit where it equals cost_item (self-referencing) or is empty.

    Strategy: for each resource name, use the most common non-self unit from other rows.
    Falls back to heuristics if no correct unit found.
    """
    conn = sqlite3.connect(str(db_path))

    # Build mapping: cost_item → correct_unit (from rows with valid units)
    rows = conn.execute("""
        SELECT cost_item, cost_item_unit, COUNT(*) as cnt
        FROM norms_item
        WHERE cost_item_unit IS NOT NULL
          AND cost_item_unit != ''
          AND cost_item_unit != cost_item
        GROUP BY cost_item, cost_item_unit
        ORDER BY cost_item, cnt DESC
    """).fetchall()

    unit_map = {}
    for ci, u, cnt in rows:
        if ci not in unit_map:
            unit_map[ci] = u  # Most common correct unit

    # Find rows to fix
    to_fix = conn.execute("""
        SELECT id, cost_item, cost_item_unit FROM norms_item
        WHERE cost_item_unit IS NULL OR cost_item_unit = '' OR cost_item_unit = cost_item
        ORDER BY id
    """).fetchall()

    fixes = []
    for rid, ci, old_unit in to_fix:
        new_unit = unit_map.get(ci) or _infer_unit(ci)
        if new_unit and new_unit != old_unit:
            fixes.append((rid, ci, old_unit, new_unit))

    if not dry_run:
        for rid, ci, old_unit, new_unit in fixes:
            conn.execute("UPDATE norms_item SET cost_item_unit = ? WHERE id = ?",
                        (new_unit, rid))
        conn.commit()
        if fixes:
            unique_items = len(set(f[1] for f in fixes))
            print(f"  Fixed {len(fixes)} cost_item_unit values across {unique_items} resource names")
    else:
        unique_items = len(set(f[1] for f in fixes))
        print(f"  [DRY-RUN] Would fix {len(fixes)} cost_item_unit values across {unique_items} resource names")

    conn.close()
    return len(fixes), len(set(f[1] for f in fixes))


# ─── Resource name dedup ──────────────────────────────────────

def dedup_norms_items(db_path, dry_run=False):
    """删除 norms_item 中完全重复的行（同一 norms_code + cost_item + sort_order）。

    返回 (deleted_count, affected_codes) 元组。
    """
    conn = sqlite3.connect(str(db_path))

    dup_count = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT norms_code, cost_item, sort_order, COUNT(*) as cnt
            FROM norms_item
            GROUP BY norms_code, cost_item, sort_order
            HAVING cnt > 1
        )
    """).fetchone()[0]

    if dup_count == 0:
        conn.close()
        return 0, []

    codes = conn.execute("""
        SELECT DISTINCT norms_code FROM (
            SELECT norms_code, cost_item, sort_order, COUNT(*) as cnt
            FROM norms_item
            GROUP BY norms_code, cost_item, sort_order
            HAVING cnt > 1
        )
        ORDER BY norms_code
    """).fetchall()
    affected_codes = [r[0] for r in codes]

    if not dry_run:
        deleted = conn.execute("""
            DELETE FROM norms_item WHERE id NOT IN (
                SELECT MIN(id) FROM norms_item
                GROUP BY norms_code, cost_item, sort_order
            )
        """).rowcount
        conn.commit()
    else:
        deleted = conn.execute("""
            SELECT COUNT(*) FROM norms_item WHERE id NOT IN (
                SELECT MIN(id) FROM norms_item
                GROUP BY norms_code, cost_item, sort_order
            )
        """).fetchone()[0]

    conn.close()
    return deleted, affected_codes


# ─── View rebuild ────────────────────────────────────────────

def rebuild_views(db_path, dry_run=False):
    """重建 v_quota_name 等视图。"""
    conn = sqlite3.connect(str(db_path))
    rules = load_rules()
    views = rules["view_rebuild"]["views"]

    rebuilt = []
    for view_name, sql in views.items():
        if dry_run:
            rebuilt.append(f"DRY-RUN: {view_name}")
            continue
        conn.execute(f"DROP VIEW IF EXISTS {view_name}")
        conn.execute(sql)
        rebuilt.append(f"Rebuilt: {view_name}")

    conn.commit()
    conn.close()
    return rebuilt


# ─── All-in-one ──────────────────────────────────────────────

def clean_all(db_path, dry_run=False):
    """执行全部清洗和校验，返回完整报告。"""
    import io as _io
    buf = _io.StringIO()

    def log(msg):
        buf.write(msg + "\n")
        print(msg)

    log(f"=== 定额数据库清洗报告 ===")
    log(f"数据库: {db_path}")
    log(f"时间: {datetime.now().isoformat()}")
    log(f"模式: {'DRY-RUN (仅校验)' if dry_run else '执行清洗'}")
    log("")

    # 1. Integrity check
    log("── 1. 结构完整性 ──")
    integ = validate_integrity(db_path)
    log(f"  章节: {integ['chapter_count']}章")
    log(f"  定额表: {integ['norms_table_count']}个")
    log(f"  定额子目: {integ['norms_item_count']}条")
    log(f"  编号长度分布: {integ['code_length_distribution']}")
    if integ["missing_tables"]:
        log(f"  ❌ 缺失表: {integ['missing_tables']}")
    if integ["unexpected_code_lengths"]:
        log(f"  ⚠ 非预期编号长度: {integ['unexpected_code_lengths']}")
    for issue in integ["issues"]:
        log(f"  ⚠ {issue}")
    if not integ["issues"] and not integ["missing_tables"]:
        log("  ✅ 通过")

    # 1.5. Deduplicate norms_item
    log("\n── 1.5. 资源去重 ──")
    deduped, dup_codes = dedup_norms_items(db_path, dry_run=dry_run)
    if deduped > 0:
        log(f"  🔧 删除重复行: {deduped} 条 (涉及 {len(dup_codes)} 个定额编号)")
    else:
        log("  ✅ 无重复行")

    # 2. Unit cleaning
    log("\n── 2. 单位清洗 ──")
    unit_report = validate_units(db_path)
    log(f"  总表数: {unit_report['total_tables']}")
    log(f"  空单位: {unit_report['null_units']} ({unit_report['null_pct']}%)")
    log(f"  不重复单位: {unit_report['distinct_units']}")

    updated, total = clean_units_db(db_path, dry_run=dry_run)
    if updated > 0:
        log(f"  🔧 已清洗: {updated}/{total} 条 (去除中文描述/修正OCR)")
    else:
        log("  ✅ 单位已干净，无需清洗")

    # 3. Fill missing units
    log("\n── 3. 缺失单位回填 ──")
    filled, still = fill_missing_units(db_path, dry_run=dry_run)
    if filled > 0:
        log(f"  🔧 已从work_content回填: {filled} 条")
    if still > 0:
        log(f"  ⚠ 仍缺失: {still} 条 (可能为章节标题行)")
        null_rows = validate_null_unit_rows(db_path, limit=5)
        for nr in null_rows:
            log(f"    - id={nr['id']}: {nr['section_title'][:50] if nr['section_title'] else '-'}")

    if unit_report["unknown_units"]:
        log(f"  ⚠ 未知单位模式: {unit_report['unknown_units']}")
    if unit_report["cn_units"] and not updated:
        log(f"  ⚠ 含中文的单位: {unit_report['cn_units']}")

    # 3.2. Infer NULL units from keywords & continued_table inheritance
    log("\n── 3.2. 空单位推断 ──")
    inf_total, inf_kw, inf_inh, inf_remain = infer_null_units(db_path, dry_run=dry_run)
    if inf_total > 0:
        log(f"  🔧 推断单位: {inf_total} 条 (关键词{inf_kw} + 续表继承{inf_inh})")
    if inf_remain > 0:
        log(f"  ⚠ 仍无法推断: {inf_remain} 条 (无关键词匹配且无前序表可继承)")

    # 3.5. Normalize cost_item_unit
    log("\n── 3.5. 资源单位修复 ──")
    n_fixed, n_items = normalize_cost_item_units(db_path, dry_run=dry_run)
    if n_fixed > 0:
        log(f"  🔧 修复了 {n_fixed} 条资源单位 ({n_items} 个资源名称)")
    else:
        log("  ✅ 资源单位无需修复")

    # 4. Rebuild views
    log("\n── 4. 视图重建 ──")
    rebuilt = rebuild_views(db_path, dry_run=dry_run)
    for r in rebuilt:
        log(f"  🔧 {r}")

    # 5. Final summary
    log("\n── 最终状态 ──")
    final = validate_units(db_path)
    log(f"  最终空单位: {final['null_units']} ({final['null_pct']}%)")
    log(f"  最终不重复单位: {final['distinct_units']}")
    if final["clean"]:
        log("  ✅ 单位全部合规")
    else:
        if final["unknown_units"]:
            log(f"  ⚠ 仍有未知单位: {final['unknown_units']}")

    log("\n=== 清洗完成 ===")
    return buf.getvalue()


# ─── CLI ─────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法: python db_clean.py <db_path> [--dry-run] [--validate]")
        sys.exit(1)

    db_path = Path(sys.argv[1])
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    validate_only = "--validate" in sys.argv

    if validate_only:
        print("── 结构完整性 ──")
        import json as _json
        print(_json.dumps(validate_integrity(str(db_path)), ensure_ascii=False, indent=2, default=str))
        print("\n── 单位校验 ──")
        print(_json.dumps(validate_units(str(db_path)), ensure_ascii=False, indent=2, default=str))
    else:
        report = clean_all(str(db_path), dry_run=dry_run)
        # Also print the report string (already printed by clean_all)
        # If dry_run, save report
        if dry_run:
            report_path = db_path.parent / f"clean_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)


if __name__ == "__main__":
    main()
