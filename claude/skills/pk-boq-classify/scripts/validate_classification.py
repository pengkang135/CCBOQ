#!/usr/bin/env python
"""Validate BOQ classification values against coding database closed vocabulary.

Usage as module:
    from validate_classification import load_closed_vocab, validate_item

Usage as CLI (audit existing classified Excel):
    python validate_classification.py <classified.xlsx> [--db-dir DB_DIR] [--lang en|zh] [--sheet SheetName]
"""

import argparse
import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path
import sys
sys.path.insert(0, Path(__file__).parent.as_posix())
import layout

# ── Discipline → book mapping ──────────────────────────────
# Values that validate_discipline accepts
DISCIPLINE_EN = {
    "Civil": "A",
    "Decoration": "A",
    "Civil & Decoration": "A",
    "MEP Installation": "B",
    "External & Municipal": "C",
    "Marine & Waterway": "D",
    "Water Transport Engineering": "D",
    "General Installation": "B",
    "Building Repair": "E",
    "Building Repair & Renovation": "E",
    "Preliminaries": "PRELIM",
    "Preliminaries & General": "PRELIM",
}

# Categories that are valid across all books (e.g. instruction/template rows)
UNIVERSAL_CATEGORIES = {"Instruction/Template"}
DISCIPLINE_ZH = {
    "建筑装饰": "A",
    "通用安装": "B",
    "市政园林": "C",
    "水运工程": "D",
    "房屋修缮": "E",
    "开办费": "PRELIM",
}

# 分类列 — 按表头名定位，Material / Spec 已随模板改版删除
CLASS_COLS = ["Main Key", "BQ KEY", "CleanDescription",
              "Discipline", "SortKey", "Category", "Subcategory", "Element",
              "Description", "Unit", "Quantity"]


def _db_files(db_dir):
    return {
        "A": Path(db_dir) / "企业定额_A册_建筑装饰.sqlite",
        "B": Path(db_dir) / "企业定额_B册_通用安装.sqlite",
        "C": Path(db_dir) / "企业定额_C册_市政园林.sqlite",
        "D": Path(db_dir) / "企业定额_D册_水运工程.sqlite",
        "E": Path(db_dir) / "企业定额_E册_房屋修缮.sqlite",
    }


def load_closed_vocab(db_dir, lang="en"):
    """Load division + sub_division closed vocabulary from the A-E SQLite DBs.

    Returns:
        dict: {book_letter: {division_name: [sub_division_names]}}
        Both keys and values use name or name_EN depending on `lang`.

    某一册在该语言下没有译名时（E 册 name_EN 目前整列为 NULL），那一册的
    闭词表是空的，不是塌成一个 None 键 —— None 混进闭词表会让任何值都校验
    不过，且报错指向不明。
    """
    name_col = "name_EN" if lang == "en" else "name"
    sub_name_col = "name_EN" if lang == "en" else "name"
    vocab = {}
    for book, path in _db_files(db_dir).items():
        if not path.exists():
            print(f"[WARN] DB not found: {path}")
            vocab[book] = {}
            continue
        conn = sqlite3.connect(str(path))
        if not _has_sub_divisions(conn):
            div_map = _chapter_tree_vocab(conn, lang, depth=2)
            conn.close()
            if not div_map:
                print(f"[WARN] Book {book}: 无 sub_division 且 chapter 在 lang={lang} "
                      f"下无译名，该册闭词表为空，不参与分类")
            vocab[book] = div_map
            continue
        rows = conn.execute(
            f"SELECT d.{name_col}, s.{sub_name_col} "
            "FROM division d "
            "LEFT JOIN sub_division s ON s.division_code = d.code "
            "ORDER BY d.code, s.sub_code"
        ).fetchall()
        conn.close()
        div_map = {}
        untranslated = 0
        for div_name, sub_name in rows:
            if not div_name:
                untranslated += 1
                continue
            if div_name not in div_map:
                div_map[div_name] = []
            if sub_name:
                div_map[div_name].append(sub_name)
        if untranslated and not div_map:
            print(f"[WARN] Book {book}: division 在 lang={lang} 下无译名"
                  f"（{untranslated} 行），该册闭词表为空，不参与分类")
        vocab[book] = div_map
    return vocab


_CHAP_PREFIX = re.compile(r"^第[一二三四五六七八九十百]+章\s*")


def _chapter_tree_vocab(conn, lang, depth=2):
    """没有 sub_division 的册（E 册房屋修缮）从 chapter 树补闭词表。

    L1 章节当 Category、L2 当 Subcategory、L3 当 Element。章名带「第X章 」
    前缀，剥掉再入表 —— 带前缀的名字进闭词表，LLM 抄回来的值和库里对不上。

    depth=2 返回 {category: [subcategories]}，depth=3 返回
    {category: {subcategory: [elements]}}。
    """
    col = "chap_Name_EN" if lang == "en" else "chap_Name"
    rows = conn.execute(
        f"SELECT chap_ID, chap_PID, {col} FROM chapter").fetchall()
    children = {}
    for cid, pid, name in rows:
        children.setdefault(pid, []).append((cid, name))

    def clean(n):
        return _CHAP_PREFIX.sub("", (n or "")).strip()

    out = {}
    for l1_id, l1_name in children.get(0, []):
        cat = clean(l1_name)
        if not cat:
            continue
        if depth == 2:
            out[cat] = [clean(n) for _i, n in children.get(l1_id, []) if clean(n)]
            continue
        subs = {}
        for l2_id, l2_name in children.get(l1_id, []):
            sub = clean(l2_name)
            if not sub:
                continue
            elems = [_strip_element_prefix(n) for _i, n in children.get(l2_id, [])]
            elems = [e for e in elems if e]
            if elems:
                subs[sub] = elems
        if subs:
            out[cat] = subs
    return out


def _has_sub_divisions(conn):
    return conn.execute("SELECT COUNT(*) FROM sub_division").fetchone()[0] > 0


def _strip_element_prefix(name):
    """Strip 'X.XX.XX.XXX ' or 'XX.XX.XXX ' prefix from element/chapter name."""
    if not name:
        return ""
    m = re.match(r'^(?:[A-E]\.)?\d{2}\.\d{2}\.\d{3}\s+(.+)', name)
    if m:
        return m.group(1).strip()
    return name.strip()


def load_element_vocab(db_dir, lang="en"):
    """Load element (L3 分项工程) closed vocabulary from chapter tables.

    Builds a mapping: {book: {subcategory_name_EN: [element_names_EN]}}
    by reconstructing the chapter table tree (L1→L2→L3) and linking
    L2 nodes to sub_division names via code matching.

    Chapter codes are book-agnostic (e.g. "01.01"), while sub_division uses
    (division_code, sub_code). We match: chapter_L2.chap_code == div_suffix.sub_code.
    """
    name_col = "name_EN" if lang == "en" else "name"
    sub_name_col = "name_EN" if lang == "en" else "name"

    name_col_div = "name_EN" if lang == "en" else "name"

    # ── Load division mapping: {book: {chap_l1_code: division_name}} ──
    div_map = {}
    # ── Load sub_division mapping: {book: {chap_l2_code: sub_name}} ──
    sub_map = {}
    for book, path in _db_files(db_dir).items():
        if not path.exists():
            div_map[book] = {}
            sub_map[book] = {}
            continue
        conn = sqlite3.connect(str(path))
        div_rows = conn.execute(
            f"SELECT code, {name_col_div} FROM division"
        ).fetchall()
        sub_rows = conn.execute(
            f"SELECT division_code, sub_code, {sub_name_col} FROM sub_division"
        ).fetchall()
        conn.close()

        div_map[book] = {}
        for div_code, name in div_rows:
            _book, div_suffix = div_code.split(".", 1)
            div_map[book][div_suffix] = name

        sub_map[book] = {}
        for div_code, sub_code, name in sub_rows:
            _book, div_suffix = div_code.split(".", 1)
            chap_l2_code = f"{div_suffix}.{sub_code}"
            sub_map[book][chap_l2_code] = name

    # ── Build element vocab from chapter tree: {book: {category: {subcategory: [elements]}}} ──
    element_vocab = {}
    for book, path in _db_files(db_dir).items():
        if not path.exists():
            element_vocab[book] = {}
            continue
        conn = sqlite3.connect(str(path))
        if not _has_sub_divisions(conn):
            # 没有 sub_division 的册，L1→L2→L3 直接落在 chapter 树上
            element_vocab[book] = _chapter_tree_vocab(conn, lang, depth=3)
            conn.close()
            continue
        col_name = "chap_Name_EN" if lang == "en" else "chap_Name"
        rows = conn.execute(
            f"SELECT chap_ID, chap_PID, chap_code, {col_name} FROM chapter"
        ).fetchall()
        conn.close()

        # Detect if chapter codes use book prefix (e.g. B book: "B.01.01" vs A book: "01.01")
        has_book_prefix = any(
            code.startswith(book + ".") for _, _, code, _ in rows[:5] if code
        )
        prefix = book + "."

        children = {}
        for chap_id, pid, code, name in rows:
            children.setdefault(pid, []).append((chap_id, code, name))

        element_vocab[book] = {}
        for _l1_id, l1_code, _l1_name in children.get(0, []):
            # Normalize L1 code: strip book prefix if present
            l1_code_norm = l1_code[len(prefix):] if has_book_prefix and l1_code.startswith(prefix) else l1_code
            div_name = div_map.get(book, {}).get(l1_code_norm)
            if not div_name:
                continue

            for _l2_id, l2_code, _l2_name in children.get(_l1_id, []):
                # Normalize L2 code: strip book prefix if present
                l2_code_norm = l2_code[len(prefix):] if has_book_prefix and l2_code.startswith(prefix) else l2_code
                sub_name = sub_map.get(book, {}).get(l2_code_norm)
                if not sub_name:
                    continue
                elements = []
                for _l3_id, _l3_code, l3_name in children.get(_l2_id, []):
                    clean = _strip_element_prefix(l3_name)
                    if clean:
                        elements.append(clean)
                if elements:
                    element_vocab[book].setdefault(div_name, {})[sub_name] = elements

    return element_vocab


def validate_element(val, category, subcategory, book, element_vocab):
    """Check if element `val` exists under category→subcategory in element_vocab[book].

    Returns:
        (is_valid: bool, corrected: str|None)
    """
    if not val:
        return True, ""
    if val in UNIVERSAL_SUBCATEGORIES:
        return True, val
    if book not in element_vocab:
        return False, None
    cat_vocab = element_vocab[book].get(category, {})
    if not cat_vocab:
        return False, None
    elements = cat_vocab.get(subcategory, [])
    if not elements:
        return False, None
    if val in elements:
        return True, val
    match = _fuzzy_match(val, elements, threshold=0.50)
    return False, match


def _discipline_to_book(discipline, lang="en"):
    """Map a discipline name to book letter (A/B/C/D/PRELIM). Returns None if invalid."""
    disc_map = DISCIPLINE_EN if lang == "en" else DISCIPLINE_ZH
    return disc_map.get(discipline)


def _fuzzy_match(val, candidates, threshold=0.5):
    """Return the best fuzzy match from candidates, or None."""
    if not candidates or not val:
        return None
    best_score = 0
    best_cand = None
    for c in candidates:
        score = SequenceMatcher(None, val.lower(), c.lower()).ratio()
        if score > best_score:
            best_score = score
            best_cand = c
    if best_score >= threshold:
        return best_cand
    return None


def _strip_subcat_code(name):
    """Strip 'XX ' code prefix from subcategory name.
    e.g. '01 Demolition Works' → 'Demolition Works'
    """
    if not name:
        return ""
    m = re.match(r'^\d{2}\s+(.+)', name)
    if m:
        return m.group(1).strip()
    return name.strip()


def validate_category(val, book, vocab):
    """Check if category `val` exists in vocab[book] divisions.

    Returns:
        (is_valid: bool, corrected: str|None)
    """
    if not val:
        return False, None
    if val in UNIVERSAL_CATEGORIES:
        return True, val
    if book not in vocab:
        return False, None
    divisions = list(vocab[book].keys())
    if val in divisions:
        return True, val
    # Try fuzzy match
    match = _fuzzy_match(val, divisions, threshold=0.50)
    return False, match


# Subcategory values that are always valid across all books (e.g. trade-specific provisional sums)
UNIVERSAL_SUBCATEGORIES = {"暂列金", "Provisional Sums"}


def validate_subcategory(val, division_name, book, vocab):
    """Check if subcategory `val` exists under division_name in vocab[book].

    Subcategory values may have a 'XX ' code prefix (e.g. '01 Demolition Works')
    which is stripped before comparison against the norms DB.
    """
    if not val:
        return True, ""  # empty subcategory is valid
    if val in UNIVERSAL_SUBCATEGORIES:
        return True, val
    if book not in vocab:
        return False, None
    subcats = vocab[book].get(division_name, [])
    if not subcats:
        return False, None
    # Try exact match first
    if val in subcats:
        return True, val
    # Strip code prefix and try again (e.g. '01 Demolition Works' → 'Demolition Works')
    stripped = _strip_subcat_code(val)
    if stripped and stripped in subcats:
        return True, val
    # Try fuzzy match against stripped value
    match = _fuzzy_match(stripped if stripped else val, subcats, threshold=0.50)
    return False, match


def validate_item(discipline, category, subcategory, vocab, lang="en",
                  element="", element_vocab=None):
    """Validate all classification fields against closed vocabulary.

    Returns:
        dict: {
            "valid": bool,
            "discipline": str (original or corrected),
            "category": str (original or corrected),
            "subcategory": str (original or corrected),
            "element": str (original or corrected),
            "errors": [str],
        }
    """
    errors = []
    warnings = []
    book = _discipline_to_book(discipline, lang)

    if book is None:
        errors.append(f"Unknown Discipline: '{discipline}'")
        return {
            "valid": False,
            "discipline": discipline,
            "category": category,
            "subcategory": subcategory,
            "element": element,
            "errors": errors,
        }

    if book == "PRELIM":
        return {
            "valid": True,
            "discipline": discipline,
            "category": category,
            "subcategory": subcategory,
            "element": element,
            "errors": [],
        }

    # Universal categories (e.g. Instruction/Template) are always valid
    if category in UNIVERSAL_CATEGORIES:
        return {
            "valid": True,
            "discipline": discipline,
            "category": category,
            "subcategory": subcategory,
            "element": element,
            "errors": [],
        }

    # Validate category
    cat_ok, cat_fix = validate_category(category, book, vocab)
    if not cat_ok:
        if cat_fix:
            errors.append(
                f"Category '{category}' not in {book}-book vocabulary, "
                f"fuzzy match → '{cat_fix}'"
            )
            category = cat_fix
        else:
            errors.append(
                f"Category '{category}' not in {book}-book vocabulary, "
                f"no close match found"
            )

    # Validate subcategory against the (possibly corrected) category
    sub_ok, sub_fix = validate_subcategory(subcategory, category, book, vocab)
    if not sub_ok:
        if sub_fix:
            errors.append(
                f"Subcategory '{subcategory}' not under '{category}', "
                f"fuzzy match → '{sub_fix}'"
            )
            subcategory = sub_fix
        else:
            errors.append(
                f"Subcategory '{subcategory}' not under '{category}', "
                f"no close match found"
            )

    # Validate element if provided and element_vocab is available
    # Element values are often descriptive labels, not strictly from chapter L3.
    # Report as warnings only — do not invalidate the row.
    if element and element_vocab:
        elem_ok, elem_fix = validate_element(element, category, subcategory, book, element_vocab)
        if not elem_ok:
            if elem_fix:
                warnings.append(
                    f"Element '{element}' not under '{subcategory}', "
                    f"fuzzy match → '{elem_fix}'"
                )
            else:
                warnings.append(
                    f"Element '{element}' not in closed vocab under '{subcategory}'"
                )

    return {
        "valid": len(errors) == 0,
        "discipline": discipline,
        "category": category,
        "subcategory": subcategory,
        "element": element,
        "errors": errors,
        "warnings": warnings,
    }


def validate_excel(input_path, db_dir, sheet="合并报表", lang="en"):
    """Audit an already-classified Excel file. Returns a validation report."""
    import openpyxl

    wb = openpyxl.load_workbook(input_path)
    ws = wb[sheet]
    vocab = load_closed_vocab(db_dir, lang)

    # Find classification columns by header row
    header_map = {}
    for c in range(1, ws.max_column + 1):
        h = ws.cell(row=layout.HEADER_ROW, column=c).value
        if h:
            name = " ".join(str(h).strip().split())
            if name in CLASS_COLS and name not in header_map:
                header_map[name] = c

    disc_col = header_map.get("Discipline")
    cat_col = header_map.get("Category")
    sub_col = header_map.get("Subcategory")
    elem_col = header_map.get("Element")

    if not all([disc_col, cat_col, sub_col]):
        print(f"Error: Could not find Discipline/Category/Subcategory columns in row {layout.HEADER_ROW}")
        return None

    elem_vocab = load_element_vocab(db_dir, lang) if elem_col else None

    report = []
    total = 0
    valid_count = 0
    invalid_count = 0

    for r in range(layout.DATA_START, ws.max_row + 1):
        disc = ws.cell(row=r, column=disc_col).value
        cat = ws.cell(row=r, column=cat_col).value
        sub = ws.cell(row=r, column=sub_col).value
        elem = ws.cell(row=r, column=elem_col).value if elem_col else None

        if not disc or not cat:
            continue
        total += 1

        result = validate_item(str(disc).strip(), str(cat).strip(),
                               str(sub).strip() if sub else "", vocab, lang,
                               element=str(elem).strip() if elem else "",
                               element_vocab=elem_vocab)
        if result["valid"] and not result.get("warnings"):
            valid_count += 1
        else:
            if not result["valid"]:
                invalid_count += 1
            else:
                # Valid with only element warnings — count as valid
                valid_count += 1
            report.append({
                "row": r,
                "discipline": result["discipline"],
                "category": result["category"],
                "subcategory": result["subcategory"],
                "element": result.get("element", ""),
                "errors": result["errors"],
                "warnings": result.get("warnings", []),
            })

    return {
        "total": total,
        "valid": valid_count,
        "invalid": invalid_count,
        "details": report,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate BOQ classification against coding DB vocabulary")
    parser.add_argument("input", help="Classified BOQ xlsx file")
    parser.add_argument("--db-dir",
                        default=r"E:\Code\Norms-AI\db",
                        help="Coding database directory")
    parser.add_argument("--lang", default="en", choices=["en", "zh"],
                        help="Language for vocabulary matching (default: en)")
    parser.add_argument("--sheet", default="合并报表", help="Sheet name")
    args = parser.parse_args()

    print(f"Loading vocab from: {args.db_dir}")
    vocab = load_closed_vocab(args.db_dir, args.lang)
    total_divs = sum(len(v) for v in vocab.values())
    total_subs = sum(sum(len(s) for s in v.values()) for v in vocab.values())
    print(f"  Divisions: {total_divs}, Sub-divisions: {total_subs}")

    report = validate_excel(args.input, args.db_dir, args.sheet, args.lang)
    if report is None:
        sys.exit(1)

    print(f"\n=== Validation Report ===")
    print(f"  Total classified rows: {report['total']}")
    print(f"  Valid:   {report['valid']}")
    print(f"  Invalid: {report['invalid']}")

    if report["details"]:
        print(f"\n=== Invalid Entries ===")
        for item in report["details"]:
            if item["errors"]:
                print(f"  Row {item['row']}:")
                print(f"    Discipline={item['discipline']} "
                      f"Category={item['category']} "
                      f"Subcategory={item['subcategory']}")
                for e in item["errors"]:
                    print(f"    ERROR: {e}")
                for w in item.get("warnings", []):
                    print(f"    WARN: {w}")

        out_file = Path(args.input).parent / "validation_report.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report["details"], f, ensure_ascii=False, indent=2)
        print(f"\nReport saved to: {out_file}")
    else:
        print("\n  All entries valid.")


if __name__ == "__main__":
    main()
