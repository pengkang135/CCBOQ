"""V2 Optimization 3+4a: Cluster BOQ items by product family, build per-family candidate
pools via CostSpread search API (primary) with static pool keyword fallback.

Pipeline:
    1. Pre-translate each BOQ description to Chinese keywords via glossary
    2. Classify each BOQ item into a product family via family_tags
    3. For each family, generate short keyword queries → CostSpread search API
       (uses search-dictionary.js for cross-language expansion + weighted field scoring)
    4. Fallback: keyword overlap scoring against static dedup pool if API unavailable
    5. Assign each BOQ item its per-item top-8 from its family pool (fuzzy re-rank)
    6. Rule-based auto-classify: provisional_sum → skip

Outputs:
    temp/v2_auto_matched.json   — items auto-classified (skip only)
    temp/v2_hard_items.json     — items needing LLM Matcher, with top-8 candidates
    temp/v2_family_stats.json   — for reporting
"""
import json, os, re, sys
from pathlib import Path
from collections import defaultdict, Counter
from rapidfuzz import process, fuzz

_script_dir = Path(__file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))
from costspread_search import costspread_search, costspread_search_multi

ROOT = Path(__file__).resolve().parent.parent
POOL = json.loads((ROOT / "v2_rate_pool_dedup.json").read_text(encoding="utf-8"))
GLOSS = json.loads((ROOT / "v2_glossary.json").read_text(encoding="utf-8"))
BOQ = json.loads((ROOT / "boq_items.json").read_text(encoding="utf-8"))

EN2CN = GLOSS["en2cn"]
FAMILY_TAGS = GLOSS["family_tags"]
# 双向材料词表（CN→EN 同义词组，来自 CostSpread 前端 search-dictionary）
CN2EN = GLOSS.get("cn2en", {})
SYN_EXACT = defaultdict(list)   # 英文同义词(小写) -> [中文key...]
SYN_PHRASES = []                # 多词英文同义词(小写, 中文key) 用于词级命中
for _cn, _en_list in CN2EN.items():
    for _en in _en_list:
        _enl = _en.lower()
        SYN_EXACT[_enl].append(_cn)
        if len(_enl.split()) > 1:
            SYN_PHRASES.append((_enl, _cn))

TOP_K_FAMILY_POOL = 40      # per family, keep top-40 candidates
TOP_K_PER_ITEM = 8           # per BOQ item, top-8 (dedup pool → fewer duplicates → smaller K OK)
MIN_CANDIDATE_SCORE = 12     # discard candidates below this score (saves Matcher token)

KNOWN_GAPS = {               # families with known poor rate-pool coverage → tag and skip LLM
    'earthwork', 'formwork', 'curtain_wall', 'glass', 'handrail',
    'fire_coating', 'steel_coating', 'insulation_board',
}

def translate_to_cn(desc: str) -> list:
    """Return list of Chinese keyword tokens found via glossary. Longer matches first."""
    d = desc.lower()
    hits = []
    for k in sorted(EN2CN.keys(), key=len, reverse=True):
        if k in d:
            cn = EN2CN[k]
            if cn not in hits:
                hits.append(cn)
    # Extract concrete grade specs (C15/C20/…)
    for m in re.findall(r"f'c\(mpa\)(\d+)|c(\d+)\s*concrete", desc.lower()):
        grade = m[0] or m[1]
        if grade and f"C{grade}" not in hits:
            hits.append(f"C{grade}")
    # Extract thickness (e.g. 20mm, 150 mm)
    for m in re.findall(r"(\d+)\s*mm", desc.lower()):
        if m and f"{m}mm" not in hits:
            hits.append(f"{m}mm")
    return hits

def classify_family(desc: str) -> str:
    dl = desc.lower()
    # Order matters: check specific families first
    ordered = [
        "provisional_sum", "rebar", "formwork", "earthwork", "geotech",
        "fire_door", "door_other", "sanitary",
        "structural_steel", "steel_coating", "fire_coating",
        "concrete_grade", "block_wall", "waterproofing",
        "gypsum_board", "calcium_silicate_board", "acoustic_panel",
        "tile_finish", "stone_finish", "vinyl_flooring", "epoxy_flooring",
        "ceiling_system", "curtain_wall", "glass",
        "insulation_board", "wall_paint", "putty_screed",
        "handrail", "skirting", "pit_manhole", "trench_drain",
        "fence", "pavement_road", "misc_finish",
    ]
    for fam in ordered:
        for trigger in FAMILY_TAGS.get(fam, []):
            if trigger in dl:
                return fam
    return "no_family"

def norm_unit(u):
    if not u:
        return ""
    u = u.strip().lower().replace(" ", "").replace(".", "").replace("²", "2").replace("³", "3")
    aliases = {"sqm": "m2", "cum": "m3", "cbm": "m3", "kgs": "kg", "tonne": "ton",
               "t": "ton", "ea": "no", "each": "no", "pcs": "no", "pc": "no",
               "nos": "no", "sets": "set"}
    return aliases.get(u, u)

def unit_compat(u_boq, u_rate):
    b, r = norm_unit(u_boq), norm_unit(u_rate)
    if not b or not r:
        return 0.3
    if b == r:
        return 1.0
    fams = [{"m","mm","cm","米"}, {"m2","㎡"}, {"m3","立方"},
            {"kg","ton","吨"}, {"no","set","个","件","项","套","块","根","樘"}]
    for f in fams:
        if b in f and r in f:
            return 0.9
    return 0.4

def specialty_affinity(disc, sp):
    aff = {
        "土建工程": {"土建":1.0,"材料":0.7,"数据中心":0.6,"周转材料":0.5,"专业分包":0.5,"机械台班":0.3},
        "装饰工程": {"外立面":1.0,"数据中心":0.9,"材料":0.7,"专业分包":0.6,"土建":0.4},
        "室外工程": {"土建":0.9,"数据中心":0.7,"材料":0.6,"绿化":1.0,"标识标牌":0.9,"专业分包":0.7,"机电":0.3},
        "钢结构工程": {"材料":0.9,"数据中心":0.7,"专业分包":0.6,"土建":0.5},
        "安装工程": {"机电":1.0,"专业分包":0.7,"数据中心":0.6},
    }
    return aff.get(disc, {}).get(sp, 0.2)

# Auto-classify rules
def rule_classify(bq, family):
    """Return (status, reasoning) if this BOQ can be auto-classified, else (None, None)."""
    d = bq["description_en"]
    dl = d.lower()
    unit = bq.get("unit", "")

    if family == "provisional_sum":
        return "skip", "暂定金/开办费 (Allow a Provision pattern)"

    # All items go through LLM pipeline — no auto-skip for construction measures.
    # Formwork, excavation, backfill, testing, monitoring all have real costs
    # and the DB often contains reference rates (e.g. Formwork 389-543 THB/m2).
    # Only provisional_sum is auto-skipped.
    return None, None

def build_query_terms(bq):
    """Build EN + CN query terms for this BOQ item, with bidirectional dictionary expansion."""
    desc = bq["description_en"]
    en_terms = re.findall(r"\w+", desc.lower())
    en_terms = [w for w in en_terms if len(w) >= 3 and not w.isdigit()]
    cn_terms = translate_to_cn(desc)
    en_set = set(en_terms)
    cn_set = set(cn_terms)
    # EN→CN：英文词命中某中文词条的同义词（含多词同义词的词级命中）→ 补该中文叫法
    for en_w in en_terms:
        for cn in SYN_EXACT.get(en_w, []):
            cn_set.add(cn)
        for syn, cn in SYN_PHRASES:
            if en_w in syn.split():
                cn_set.add(cn)
    # CN→EN：中文词命中中文词条（相等或互相包含）→ 补其英文同义词
    for cn_w in list(cn_set):
        for key, en_list in CN2EN.items():
            if cn_w == key or (len(cn_w) >= 2 and (cn_w in key or key in cn_w)):
                for en in en_list:
                    en_set.add(en.lower())
    return list(en_set), list(cn_set)

def _generate_search_queries(items):
    """Generate short keyword queries for CostSpread search from family items."""
    queries = []
    stopwords = {'with', 'from', 'that', 'this', 'shall', 'each', 'they',
                 'them', 'than', 'which', 'other', 'where', 'their', 'have',
                 'been', 'were', 'will', 'also', 'such', 'into'}
    for x in items:
        desc = x['description_en']
        dl = desc.lower()
        # Chinese keywords (via glossary translation + grade/spec extraction)
        cn_terms = translate_to_cn(desc)
        if cn_terms:
            queries.append(' '.join(cn_terms[:4]))
        # Short English keyword combinations (avoid full sentences)
        en_words = re.findall(r'\b[a-zA-Z]{4,}\b', dl)
        en_kw = [w for w in en_words if w not in stopwords][:4]
        if en_kw:
            queries.append(' '.join(en_kw[:3]))
        # For concrete items, extract grade + type keywords
        if 'f\'c' in dl or 'mpa' in dl or 'ksc' in dl or 'concrete' in dl:
            mpa, ksc = extract_concrete_grade(desc)
            if ksc:
                queries.append(f'concrete {ksc} ksc')
            elif mpa:
                queries.append(f'concrete {mpa} mpa')
    return queries


def build_family_pool(items, pool):
    """Build family candidate pool via CostSpread search (primary) with pool fallback."""
    queries = _generate_search_queries(items)
    if queries:
        # Use CostSpread API search
        raw = costspread_search_multi(
            list(set(queries)),  # dedup queries
            country="泰国",
            page_size=TOP_K_FAMILY_POOL,
        )
        if raw:
            family_pool = []
            ids_seen = set()
            for r in raw:
                rid = str(r.get('_id', ''))
                if rid in ids_seen:
                    continue
                ids_seen.add(rid)
                price = r.get('price_incl_tax', 0) or r.get('price_excl_tax', 0) or 0
                if price <= 0:
                    continue
                family_pool.append({
                    'name': r.get('name', ''),
                    'unit': r.get('unit', ''),
                    'price_thb': price,
                    'price_mean': price,
                    'specialty': r.get('specialty', ''),
                    'project': r.get('projectName', ''),
                    'supplier': r.get('supplier', ''),
                    'date': str(r.get('date', ''))[:10],
                    'id': rid[-16:],
                    'dup_count': 1,
                })
            if family_pool:
                return family_pool

    # Fallback: original keyword overlap scoring against static pool
    all_en = set()
    all_cn = set()
    for x in items:
        en, cn = build_query_terms(x)
        all_en.update(en)
        all_cn.update(cn)
    scored = []
    for r in pool:
        n = r["name"].lower()
        en_hits = sum(1 for kw in all_en if kw in n)
        cn_hits = sum(1 for kw in all_cn if kw in r["name"])
        if en_hits == 0 and cn_hits == 0:
            continue
        score = en_hits * 4 + cn_hits * 6
        if r.get("project") == "Galaxy Peak Data Center":
            score += 8
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:TOP_K_FAMILY_POOL]]

def extract_concrete_grade(desc: str) -> tuple:
    """Extract concrete grade from description. Returns (mpa_value, ksc_value) or (None, None)."""
    dl = desc.lower()
    # f'c(MPa)28, f'c 28 MPa, 28MPa, C28, C30
    m = re.search(r"f'?c\s*\(\s*mpa\s*\)\s*(\d+)", dl)
    if m:
        return (int(m.group(1)), None)
    m = re.search(r"(\d+)\s*mpa", dl)
    if m:
        mpa = int(m.group(1))
        return (mpa, mpa * 10)  # 28MPa ≈ 280ksc
    m = re.search(r"(\d+)\s*ksc", dl)
    if m:
        ksc = int(m.group(1))
        return (ksc / 10, ksc)  # 280ksc ≈ 28MPa
    m = re.search(r"\bc(\d{2})\b", dl)
    if m:
        return (int(m.group(1)), None)
    return (None, None)

def material_class_penalty(desc: str, rate_name: str) -> float:
    """Penalize material class mismatches. Returns negative score penalty."""
    dl = desc.lower()
    rl = rate_name.lower()

    # Material class incompatibility rules
    incompat = [
        # (BOQ material indicators, incompatible rate indicators, penalty)
        (r'crushed\s*rock|subbase|sub\s*base|aggregate|gravel|crushed\s*stone',
         r'concrete|asphalt|mortar|grout|plaster', -30),
        (r'sand\s+blind', r'concrete|asphalt|reinforced', -30),
        (r'formwork|shuttering',
         r'concrete|mortar|block|brick', -20),
        (r'excavation|earthwork|backfill',
         r'formwork|concrete\s+road|concrete\s+base|asphalt', -20),
        (r'fine\s+aggregate\s+concrete|concrete\s+screed',
         r'plaster|mortar|grout|waterproof|render', -25),
    ]

    penalty = 0.0
    for boq_pat, rate_pat, pen in incompat:
        if re.search(boq_pat, dl) and re.search(rate_pat, rl):
            penalty += pen

    # Material class affinity (positive score for same material)
    compat = [
        (r'crushed\s*rock|subbase|aggregate|gravel|crushed\s*stone',
         r'crushed\s*rock|compacted|subbase|aggregate|gravel', 15),
        (r'formwork|shuttering',
         r'formwork|shuttering', 15),
        (r'lean\s*concrete|concrete\s*blind',
         r'lean\s*concrete|blind', 15),
    ]
    for boq_pat, rate_pat, bonus in compat:
        if re.search(boq_pat, dl) and re.search(rate_pat, rl):
            penalty += bonus

    return penalty

def grade_score(desc: str, rate_name: str) -> float:
    """Score concrete grade compatibility. Positive = compatible."""
    mpa, ksc = extract_concrete_grade(desc)
    if mpa is None:
        return 0.0

    rl = rate_name.lower()
    # Extract grade from rate name
    r_mpa = None
    m = re.search(r"(\d+)\s*mpa", rl)
    if m:
        r_mpa = int(m.group(1))
    else:
        m = re.search(r"(\d+)\s*ksc", rl)
        if m:
            r_mpa = int(m.group(1)) / 10
        else:
            m = re.search(r"\bc(\d{2})\b", rl)
            if m:
                r_mpa = int(m.group(1))

    if r_mpa is None:
        return -3.0  # rate has no grade info — slight penalty

    diff = abs(mpa - r_mpa)
    if diff == 0:
        return 15.0
    elif diff <= 4:
        return 10.0
    elif diff <= 8:
        return 3.0
    elif diff <= 15:
        return -5.0
    else:
        return -15.0  # grade way off

def rerank_for_item(bq, family_pool):
    """Given an item's family pool, rerank per-item and return top-K.
    V2.2: Added material class penalty + grade-first scoring for concrete items."""
    en_terms, cn_terms = build_query_terms(bq)
    desc_lc = bq["description_en"].lower()
    desc = bq["description_en"]
    scored = []
    for r in family_pool:
        n = r["name"].lower()
        f_en = fuzz.token_set_ratio(desc, r["name"])
        en_h = sum(1 for kw in en_terms if kw in n)
        cn_h = sum(1 for kw in cn_terms if kw in r["name"])
        uc = unit_compat(bq["unit"], r["unit"])
        sa = specialty_affinity(bq["discipline"], r["specialty"])
        proj = 4 if r.get("project") == "Galaxy Peak Data Center" else 0
        # New: material class penalty + grade score
        mat_pen = material_class_penalty(desc, r["name"])
        gs = grade_score(desc, r["name"])
        score = (f_en * 0.4 + en_h * 5 + cn_h * 7 + uc * 20 + sa * 10
                 + proj + mat_pen + gs)
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    filtered = [(s, r) for s, r in scored if s >= MIN_CANDIDATE_SCORE]
    if not filtered:
        return []
    return [r for _, r in filtered[:TOP_K_PER_ITEM]]

def compact_cand(r):
    return {
        "n": r["name"][:70].replace("\n"," | "),
        "u": r["unit"],
        "p": r["price_thb"],
        "p_avg": r.get("price_mean", r["price_thb"]),
        "s": r["specialty"],
        "pj": (r["project"] or "")[:22],
        "sup": (r["supplier"] or "")[:20],
        "d": (r["date"] or "")[:10],
        "id": r["id"][-8:],
        "dup": r.get("dup_count", 1),
    }

def main():
    # Group BOQ items by family
    by_family = defaultdict(list)
    fam_map = {}
    for bq in BOQ:
        fam = classify_family(bq["description_en"])
        by_family[fam].append(bq)
        fam_map[bq["excel_row"]] = fam

    fam_counts = {fam: len(items) for fam, items in by_family.items()}
    print("Family distribution:")
    for fam, n in sorted(fam_counts.items(), key=lambda x: -x[1]):
        print(f"  {fam}: {n}")

    # For each family, build a shared candidate pool
    family_pools = {}
    for fam, items in by_family.items():
        if fam in ("provisional_sum",):
            continue  # skip, no matching needed
        family_pools[fam] = build_family_pool(items, POOL)
        print(f"family '{fam}': {len(items)} items → pool {len(family_pools[fam])}")

    # Auto-classify or assign per-item candidates
    auto_matched = []
    hard_items = []
    for bq in BOQ:
        fam = fam_map[bq["excel_row"]]
        status, note = rule_classify(bq, fam)
        if status:
            auto_matched.append({
                "excel_row": bq["excel_row"],
                "status": status,
                "family": fam,
                "matched_id": None,
                "matched_name": None,
                "matched_unit": None,
                "matched_price_thb": None,
                "converted_price_thb": None,
                "matched_project": None,
                "matched_supplier": None,
                "matched_date": None,
                "similarity": 0.0,
                "reasoning": f"[rule-auto] {note}",
            })
            continue
        # Needs LLM matcher
        pool = family_pools.get(fam, [])
        top = rerank_for_item(bq, pool) if pool else []
        # Known-gap families with zero/no candidates → tag and skip LLM (③④⑥⑦), go directly to ⑧
        if not top and fam in KNOWN_GAPS:
            auto_matched.append({
                "excel_row": bq["excel_row"],
                "status": "known_gap",
                "family": fam,
                "matched_id": None,
                "matched_name": None,
                "matched_unit": None,
                "matched_price_thb": None,
                "converted_price_thb": None,
                "matched_project": None,
                "matched_supplier": None,
                "matched_date": None,
                "similarity": 0.0,
                "reasoning": f"[known-gap] {fam} family has poor rate-pool coverage — needs specialist quotation",
            })
            continue
        hard_items.append({
            "excel_row": bq["excel_row"],
            "family": fam,
            "boq": {
                "row": bq["excel_row"],
                "disc": bq["discipline"],
                "cat": bq.get("category", ""),
                "sub": bq.get("subcategory", ""),
                "desc": bq["description_en"][:200],
                "cn_kw": " ".join(translate_to_cn(bq["description_en"]))[:150],
                "unit": bq["unit"],
                "qty": bq["qty"],
            },
            "top_candidates": [compact_cand(r) for r in top],
        })

    (ROOT / "v2_auto_matched.json").write_text(
        json.dumps(auto_matched, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "v2_hard_items.json").write_text(
        json.dumps(hard_items, ensure_ascii=False), encoding="utf-8")

    # Family stats
    stats = {
        "auto_matched": len(auto_matched),
        "hard": len(hard_items),
        "family_counts": fam_counts,
        "auto_by_status": Counter(x["status"] for x in auto_matched),
    }
    (ROOT / "v2_family_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print()
    print(f"Auto-classified: {len(auto_matched)} ({dict(Counter(x['status'] for x in auto_matched))})")
    print(f"Hard (need LLM): {len(hard_items)}")
    print(f"Hard file size: {(ROOT / 'v2_hard_items.json').stat().st_size // 1024} KB")

if __name__ == "__main__":
    main()
