"""V2 Optimization 2: Deduplicate rate pool by (normalized_name, unit).

For each (name, unit) group, keep the LATEST date entry, but also record min/mean/max
prices from the group. Reduces context load per Matcher significantly.

Output: temp/v2_rate_pool_dedup.json
"""
import json, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "rate_pool_thb.json"
OUT = ROOT / "v2_rate_pool_dedup.json"

def norm_name(n):
    n = re.sub(r"\s+", " ", n.strip().lower())
    # Strip common variant markers
    n = re.sub(r"\s*[\(\[（【].*?[\)\]）】]\s*", " ", n).strip()
    return n[:120]

def norm_unit(u):
    if not u:
        return ""
    u = u.strip().lower().replace(" ", "").replace(".", "")
    u = u.replace("²", "2").replace("³", "3")
    aliases = {"sqm": "m2", "sq": "m2", "cum": "m3", "cbm": "m3",
               "kgs": "kg", "tonne": "ton", "tonnes": "ton", "t": "ton",
               "ea": "no", "each": "no", "pcs": "no", "pc": "no",
               "nos": "no", "sets": "set"}
    return aliases.get(u, u)

def valid(r):
    n = r["name"].strip()
    if len(n) < 4:
        return False
    if n.replace(".", "").replace(",", "").replace(" ", "").isdigit():
        return False
    return True

def main():
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    pool = [r for r in pool if valid(r)]
    groups = defaultdict(list)
    for r in pool:
        key = (norm_name(r["name"]), norm_unit(r["unit"]))
        groups[key].append(r)

    dedup = []
    for (nn, nu), items in groups.items():
        items.sort(key=lambda x: x.get("date", ""), reverse=True)
        prices = [x["price_thb"] for x in items if x.get("price_thb")]
        rep = dict(items[0])  # latest entry as representative
        rep["price_min"] = min(prices) if prices else rep["price_thb"]
        rep["price_max"] = max(prices) if prices else rep["price_thb"]
        rep["price_mean"] = round(sum(prices) / len(prices), 2) if prices else rep["price_thb"]
        rep["dup_count"] = len(items)
        rep["norm_name"] = nn
        rep["norm_unit"] = nu
        dedup.append(rep)

    OUT.write_text(json.dumps(dedup, ensure_ascii=False), encoding="utf-8")
    print(f"pool {len(pool)} → dedup {len(dedup)} ({100*(1-len(dedup)/len(pool)):.1f}% reduction)")
    print(f"file size: {OUT.stat().st_size // 1024} KB")

if __name__ == "__main__":
    main()
