#!/usr/bin/env python
"""Build LLM classification prompts with closed-vocabulary constraints.

Every LLM classification call MUST use this module to inject valid
Category and Subcategory choices from the coding DB. This is the
enforcement layer that prevents LLM from inventing values.

Usage:
    from build_classification_prompt import build_prompt
    prompt = build_prompt(items, vocab, book="A")
"""

from validate_classification import load_closed_vocab


def _cand_name(c: dict) -> str:
    """候选的分部名。vocab 的键是英文，所以必须取 name_en —— 取 name 会拿到
    中文（"措施项目"），查英文键的 vocab 永远落空，Subcategory/Element 全空。"""
    return c.get("name_en") or c.get("name", "")


def _discipline_to_book(discipline: str) -> str:
    """Map discipline name to book letter."""
    mapping = {
        "Civil & Decoration": "A",
        "MEP Installation": "B",
        "External & Municipal": "C",
        "Marine & Waterway": "D",
        "Building Repair": "E",
        "Preliminaries & General": "PRELIM",
    }
    return mapping.get(discipline, "A")


def build_category_prompt(items: list[dict], vocab: dict) -> str:
    """Build a prompt asking the LLM to classify items into categories.

    Each item should have 'desc', 'candidates' (from route_result).
    The prompt includes ONLY valid category names from the coding DB.

    Returns a prompt string ready for Haiku/Sonnet API call.
    """
    # Collect all candidate divisions across all books
    all_divisions = []
    seen = set()
    for item in items:
        for book, cands in item.get("candidates", {}).items():
            if book == "hint" or not isinstance(cands, list):
                continue
            for c in cands:
                name = _cand_name(c)
                if name and name not in seen:
                    seen.add(name)
                    all_divisions.append((book, name))

    if not all_divisions:
        return ""

    lines = [
        "You are a construction cost estimator classifying BOQ items.",
        "",
        "For each item below, assign a Category from the following CLOSED list.",
        "You MUST pick exactly one Category from this list per item.",
        "Do NOT invent, translate, or rephrase any category name.",
        "",
        "Valid Categories:",
    ]
    for book, name in sorted(all_divisions):
        lines.append(f"  [{book}] {name}")

    lines.extend([
        "",
        "Items to classify:",
    ])
    for i, item in enumerate(items):
        lines.append(f"  [{i}] {item.get('desc', '')}")

    lines.extend([
        "",
        "Respond in JSON format:",
        '  [{"index": 0, "book": "A", "category": "exact category name from list"}, ...]',
        "",
        "Remember: category MUST be copied exactly from the Valid Categories list above.",
    ])
    return "\n".join(lines)


def build_subcategory_prompt(items: list[dict], vocab: dict, book: str,
                              category_en: str) -> str:
    """Build a prompt asking the LLM to select subcategories for items.

    `category_en` must be an English division name present in vocab[book].
    Only the sub_division names under that division are offered as choices.
    """
    subs = vocab.get(book, {}).get(category_en, [])
    if not subs:
        return ""

    lines = [
        "You are a construction cost estimator classifying BOQ items.",
        "",
        f"All items below belong to Category: {category_en}",
        "",
        "For each item, assign a Subcategory from the following CLOSED list.",
        "You MUST pick exactly one Subcategory from this list per item.",
        "Do NOT invent, translate, or rephrase any subcategory name.",
        "If no subcategory clearly matches, use an empty string.",
        "",
        "Valid Subcategories:",
    ]
    for s in subs:
        lines.append(f"  - {s}")

    lines.extend([
        "",
        "Items to classify:",
    ])
    for i, item in enumerate(items):
        lines.append(f"  [{i}] {item.get('desc', '')}")

    lines.extend([
        "",
        "Respond in JSON format:",
        '  [{"index": 0, "subcategory": "exact subcategory name from list or empty string"}, ...]',
        "",
        "Remember: subcategory MUST be copied exactly from the Valid Subcategories list, or be empty.",
    ])
    return "\n".join(lines)


def build_full_prompt(items: list[dict], vocab: dict,
                      element_vocab: dict | None = None) -> str:
    """Build a combined prompt for Discipline + Category + Subcategory + Element.

    This is the recommended entry point for single-pass LLM classification.
    It lists ALL valid categories from the candidates and ALL valid
    subcategories under each, forcing the LLM to pick from closed vocabulary.

    `element_vocab` comes from validate_classification.load_element_vocab() and is
    {book: {category: {subcategory: [elements]}}}. Pass it whenever the response
    format asks for an Element — without it the LLM has no element list to copy
    from and will either leave the column empty or invent values.
    """
    candidate_set = {}
    for item in items:
        for book, cands in item.get("candidates", {}).items():
            if book == "hint" or not isinstance(cands, list):
                continue
            for c in cands:
                name = _cand_name(c)
                if name and (book, name) not in candidate_set:
                    candidate_set[(book, name)] = c

    if not candidate_set:
        return ""

    # Build the category→subcategories index from vocab.
    # vocab is authoritative; the candidate's own `subs` is the fallback for
    # books/divisions the vocab loader skipped (e.g. E 册无英文译名).
    cat_with_subs = {}
    for (book, cat_name), cand in candidate_set.items():
        subs = vocab.get(book, {}).get(cat_name) or cand.get("subs") or []
        cat_with_subs[(book, cat_name)] = subs

    lines = [
        "You are a construction cost estimator classifying BOQ items for a data center project.",
        "",
        "## CRITICAL RULE — CLOSED VOCABULARY",
        "All Category and Subcategory values MUST come from the lists below.",
        "You are FORBIDDEN from inventing, translating, abbreviating, or rephrasing.",
        "Copy values EXACTLY as they appear. An empty subcategory is allowed.",
        "",
        "## Valid Categories and their Subcategories",
    ]

    for (book, cat_name), subs in sorted(cat_with_subs.items()):
        lines.append(f"\n### [{book}] {cat_name}")
        if not subs:
            lines.append("  (no subcategories — leave Subcategory empty)")
            continue
        elems_of_cat = (element_vocab or {}).get(book, {}).get(cat_name, {})
        for s in subs:
            lines.append(f"  - Subcategory: {s}")
            for e in elems_of_cat.get(s, []):
                lines.append(f"      * {e}")

    lines.extend([
        "",
        "## Items to Classify",
    ])
    for i, item in enumerate(items):
        lines.append(f"\n[{i}] Description: {item.get('desc', '')}")

    lines.extend([
        "",
        "## Response Format",
        "Return a JSON array, one object per item:",
        '[',
        '  {',
        '    "index": 0,',
        '    "book": "A",                    // one of: A, B, C, D, E',
        '    "category": "exact name",       // MUST be from the Valid Categories list',
        '    "subcategory": "exact name",    // MUST be from that category\'s subcategories, or ""',
        '    "element": "exact name"         // MUST be from that subcategory\'s elements, or ""',
        '  },',
        '  ...',
        ']',
        "",
        "Work top-down: Category first, then a Subcategory listed under it, then an",
        "Element listed under that Subcategory. Never mix levels across Categories.",
        "" if element_vocab else
        'No element lists were supplied above — return "" for every element.',
        "",
        "## Discipline Mapping",
        'A = "Civil & Decoration"',
        'B = "MEP Installation"',
        'C = "External & Municipal"',
        'D = "Marine & Waterway"',
        'E = "Building Repair"        // 中文清单专用，E 册无英文译名',
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    import json, sys
    from pathlib import Path

    from validate_classification import load_element_vocab

    db_dir = r"E:\Code\Norms-AI\db"
    vocab = load_closed_vocab(db_dir, lang="en")
    element_vocab = load_element_vocab(db_dir, lang="en")

    # Demo: show what gets injected. Note candidates carry BOTH `name` (中文)
    # and `name_en` — only name_en matches the vocab keys.
    demo_items = [{
        "desc": "Formwork to Pad Foundations, waterproof concrete f'c 32MPa",
        "candidates": {
            "A": [
                {"code": "A.04", "name": "现浇混凝土及钢筋",
                 "name_en": "Cast-in-place Concrete and Reinforcement", "n_subs": 4,
                 "subs": ["Foundations and Pile Caps", "Columns", "Beams", "Slabs"]},
            ],
            "B": [],
            "C": [],
        },
    }]

    prompt = build_full_prompt(demo_items, vocab, element_vocab)
    print(prompt)
    print(f"\n--- Prompt length: {len(prompt)} chars ---")
