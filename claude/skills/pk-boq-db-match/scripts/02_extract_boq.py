"""Stage 1b: Extract AI-todo BOQ items from UniqueBQ sheet.

AI-todo = leaf row (Qty > 0) AND N (人工套价) is None.
Output: temp/boq_items.json — 304 items.
"""
import json
from pathlib import Path
import openpyxl

SRC = Path(r"f:\BaiduSyncdisk\5.报价\2026-7 泰国CMI移动MOD2数据中心\4 BQ\2026-7-29 第二版\2026-07-29_CMI_MOD2_BOQ_合并报表_套价版.xlsx")
OUT = Path(__file__).resolve().parent.parent / "boq_items.json"

def as_str(v):
    if v is None:
        return ""
    return str(v).strip()

def main():
    wb = openpyxl.load_workbook(SRC, data_only=True, read_only=True)
    ws = wb["UniqueBQ"]
    items = []
    for r_idx, row in enumerate(ws.iter_rows(min_row=5, values_only=True), start=5):
        A, B, C, D, E, F, G, H, I, J, K, L, M, N = row[:14]
        if A == "总计":
            continue
        qty = None
        try:
            qty = float(G) if G is not None else None
        except (TypeError, ValueError):
            continue
        if not qty or qty <= 0:
            continue
        # N is not None → manually filled (even N=0). Skip.
        if N is not None:
            continue
        items.append({
            "excel_row": r_idx,
            "discipline": as_str(A),
            "category": as_str(B),
            "subcategory": as_str(C),
            "description_en": as_str(D),
            "unit": as_str(E),
            "bq_code": as_str(F) if F else as_str(L),
            "qty": qty,
            "old_rate": float(H) if isinstance(H, (int, float)) else None,
        })
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"AI-todo count = {len(items)}")
    print(f"written: {OUT}")
    # Distribution
    from collections import Counter
    disc = Counter(x["discipline"] for x in items)
    for d, n in disc.most_common():
        print(f"  {d}: {n}")

if __name__ == "__main__":
    main()
