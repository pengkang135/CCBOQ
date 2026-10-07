"""Stage 1a: Pull all Thailand THB rates from CostSpread MongoDB into a compact JSON pool.

Filters:
    - country == "泰国"
    - currency == "THB"
    - price_incl_tax exists and > 0 (skip empty/zero-priced items)
    - specialty NOT in {码头工程, 间接费}  (港工无关，间接费不用作物料匹配)

Output: temp/rate_pool_thb.json — 13k+ compact records.
"""
from pymongo import MongoClient
import json
from pathlib import Path

CONN = "mongodb://127.0.0.1:37117/cost_data_platform?directConnection=true"
EXCLUDE_SPECIALTY = {"码头工程", "间接费"}

def price_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

def main():
    client = MongoClient(CONN)
    db = client.cost_data_platform
    q = {
        "country": "泰国",
        "currency": "THB",
        "specialty": {"$nin": list(EXCLUDE_SPECIALTY)},
    }
    proj = {
        "_id": 1, "name": 1, "unit": 1,
        "price_incl_tax": 1, "price_excl_tax": 1,
        "specialty": 1, "projectName": 1, "supplier": 1,
        "date": 1, "bq": 1,
    }
    pool = []
    for doc in db.rates.find(q, proj):
        p_incl = price_num(doc.get("price_incl_tax"))
        p_excl = price_num(doc.get("price_excl_tax"))
        price = p_incl if p_incl and p_incl > 0 else p_excl
        if not price or price <= 0:
            continue
        supplier = doc.get("supplier")
        if isinstance(supplier, dict):
            supplier = supplier.get("name") or supplier.get("companyName") or ""
        pool.append({
            "id": str(doc["_id"]),
            "name": (doc.get("name") or "").strip(),
            "unit": (doc.get("unit") or "").strip(),
            "price_thb": round(price, 4),
            "specialty": doc.get("specialty") or "",
            "project": doc.get("projectName") or "",
            "supplier": (supplier or "").strip()[:40],
            "date": str(doc.get("date") or "")[:10],
        })
    out = Path(__file__).resolve().parent.parent / "rate_pool_thb.json"
    out.write_text(json.dumps(pool, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"pool size = {len(pool)}")
    print(f"written: {out}")
    print(f"file size KB = {out.stat().st_size // 1024}")

if __name__ == "__main__":
    main()
