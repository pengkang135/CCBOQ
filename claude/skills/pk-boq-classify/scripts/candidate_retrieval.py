"""
候选池检索器 — 第 2 步 route_boq.py 的核心检索模块（技能级通用）

输入: BOQ Description (英文) + Dept1/2/3 上下文
输出: 从 A/B/C 册定额库按语义关键词召回的候选 division/sub_division 池

用法:
    from candidate_retrieval import retrieve_candidates
    pool = retrieve_candidates(
        descs=["Cast-in-situ concrete to bored piles", "Proof Drilling Test"],
        dept1="Substructure", dept2="Piling"
    )

策略:
1. 术语表 (references/taxonomy_v1.json en_zh_seed_glossary) 做英文→中文关键词展开
2. SQLite LIKE 模糊匹配 A/C 册 division/sub_division.name, B 册 chapter.chap_Name + chap_Name_EN
3. 按命中权重(dept1/2 匹配加分)取 top-K 分部,每个分部拉全部子分部作为候选
4. Dept1 明显是 Preliminaries/General 时,直接返回空候选池(标记 PRELIM 走规则处理)

路径配置:
- 定额库 db_dir/books 从 references/classification_rules.json 的 closed_vocab_source 读取
- 术语表从 references/taxonomy_v1.json 读取

未来升级:
- FTS5 全文索引 (norm_Name / norm_Name_EN) — 需先建索引
- 向量嵌入 (bge-m3) — 需离线跑一次入库
"""
from __future__ import annotations
import sqlite3
import json
import re
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REFS = _HERE.parent / "references"
_RULES = json.loads((_REFS / "classification_rules.json").read_text(encoding="utf-8"))
_TAXONOMY = json.loads((_REFS / "taxonomy_v1.json").read_text(encoding="utf-8"))

_DB_DIR = Path(_RULES["closed_vocab_source"]["db_dir"])
_BOOKS = _RULES["closed_vocab_source"]["books"]
DB_A = _DB_DIR / _BOOKS["A"]
DB_B = _DB_DIR / _BOOKS["B"]
DB_C = _DB_DIR / _BOOKS["C"]
DB_D = _DB_DIR / _BOOKS["D"]
DB_E = _DB_DIR / _BOOKS["E"]

GLOSSARY = _TAXONOMY["en_zh_seed_glossary"]

PRELIM_DEPT_MARKERS = {
    "preliminary", "preliminaries", "prelims", "prelimanaries",
    "general", "contract conditions",
    "投标", "常规", "合同条件", "前期",
}

# Dept2 强信号路由表 —— 按上方英文标题(regex)决定强制拉入的分部
# 每条: (regex, [(册, division_code_or_None)]) None=拉全部
DEPT2_ROUTER: list[tuple[re.Pattern, list[tuple[str, str | None]]]] = [
    # 缩写章节强信号（HK SMM 常见：ST=结构, AR=建筑装饰, SN=信号/弱电, EE=电气, AC=空调, EQ=设备家具）
    (re.compile(r"\d+-\d+\s+ST\b", re.I),
     [("A", "A.01"), ("A", "A.03"), ("A", "A.04"), ("A", "A.06"), ("A", "A.07"), ("A", "A.08"), ("A", "A.10")]),
    (re.compile(r"\d+-\d+\s+AR\b", re.I),
     [("A", "A.06"), ("A", "A.11"), ("A", "A.20"), ("A", "A.21"), ("A", "A.22"), ("A", "A.23"), ("A", "A.24"), ("A", "A.25"), ("A", "A.26")]),
    (re.compile(r"\d+-\d+\s+SN\b", re.I), [("B", "06"), ("B", "07"), ("B", "13"), ("B", "12")]),
    (re.compile(r"\d+-\d+\s+EE\b", re.I), [("B", "06"), ("B", "13")]),
    (re.compile(r"\d+-\d+\s+AC\b", re.I), [("B", "09")]),
    (re.compile(r"\d+-\d+\s+EQ\b|EQUIPMENT/FURNITURE", re.I), [("A", "A.24"), ("B", "12")]),
    (re.compile(r"\d+-\d+\s+ID\b|INTERIOR DECORATION", re.I),
     [("A", "A.20"), ("A", "A.21"), ("A", "A.22"), ("A", "A.23"), ("A", "A.24"), ("B", "12")]),
    (re.compile(r"PILING|BORED PILE|PILE FOUNDATION", re.I), [("A", "A.03")]),
    (re.compile(r"REINFORCED CONCRETE|R\.C\.|\bRC\b|CONCRETE WORKS|REINFORCEMENT", re.I), [("A", "A.04")]),
    (re.compile(r"PRECAST", re.I), [("A", "A.05")]),
    (re.compile(r"MASONRY|BRICKWORK|BLOCK.*WALL|BLOCKWORK", re.I), [("A", "A.06")]),
    (re.compile(r"METAL WORKS?|STEELWORK|STRUCTURAL STEEL|IRONMONGERY", re.I), [("A", "A.07")]),
    (re.compile(r"WOODWORK|CARPENTRY|JOINERY|TIMBER", re.I), [("A", "A.08")]),
    (re.compile(r"ROOFING|ROOF WORKS?", re.I), [("A", "A.10"), ("A", "A.11")]),
    (re.compile(r"WATERPROOF|DAMP.PROOF|TANKING", re.I), [("A", "A.11")]),
    (re.compile(r"INSULAT|THERMAL|ACOUSTIC|FIRESTOP", re.I), [("A", "A.12")]),
    (re.compile(r"\bDOOR|WINDOW|IRONMONGERY|BALUSTRADE|HANDRAIL", re.I), [("A", "A.20"), ("A", "A.07")]),
    (re.compile(r"CURTAIN WALL|EXTERNAL WALL FINISH|CLADDING|FACADE", re.I), [("A", "A.21")]),
    (re.compile(r"FLOOR FINISH|FLOORING|SCREED", re.I), [("A", "A.22")]),
    (re.compile(r"WALL FINISH|PARTITION|WALL DECOR", re.I), [("A", "A.23")]),
    (re.compile(r"CEILING", re.I), [("A", "A.24")]),
    (re.compile(r"\bPAINT|COATING|WALLPAPER", re.I), [("A", "A.25")]),
    (re.compile(r"\bSANITARY\s+FIT|FITMENT|FURNITURE|WORKTOP", re.I), [("A", "A.26"), ("B", "12")]),
    (re.compile(r"OTHER WORKS|CABINETRY", re.I), [("A", "A.26")]),
    (re.compile(r"MONITORING|INSTRUMENTATION|监测|仪表|观测", re.I), [("A", "A.31"), ("B", "08")]),
    (re.compile(r"DEMOLITION|REMOVAL", re.I), [("A", "A.30")]),
    (re.compile(r"EARTHWORK|EXCAVATION|BACKFILL", re.I), [("A", "A.01"), ("C", "C.01")]),
    (re.compile(r"SUBSTRUCTURE|BASEMENT|FOUNDATION WORKS?", re.I), [("A", "A.01"), ("A", "A.02"), ("A", "A.03"), ("A", "A.04")]),
    (re.compile(r"EXTERNAL WORKS?|SITE WORKS?|SITEWORKS", re.I),
     [("C", None), ("A", "A.31"), ("A", "A.01"), ("A", "A.04"), ("A", "A.06"), ("A", "A.20"), ("A", "A.23")]),

    # B册 MEP
    (re.compile(r"MECHANIC(AL)? PLANT", re.I), [("B", "03")]),
    (re.compile(r"THERMAL PLANT|BOILER", re.I), [("B", "04")]),
    (re.compile(r"STATIC EQUIP|PROCESS TANK|PRESSURE VESSEL", re.I), [("B", "05")]),
    (re.compile(r"ELECTRIC|LV|MV|HV|POWER|SUBSTATION|GENERATOR|UPS|SWITCHGEAR|BUSBAR|CABLE TRAY|LIGHTING", re.I), [("B", "06")]),
    (re.compile(r"BAS|BMS|BUILDING (AUTOMAT|MANAG|INTELLIGEN)|SECURITY|CCTV|ACCESS CONTROL|PA SYSTEM|INTERCOM|IPTV|MATV", re.I), [("B", "07")]),
    (re.compile(r"INSTRUMENT|\bDCS\b|SCADA|PLC(?![A-Z])", re.I), [("B", "08")]),
    (re.compile(r"HVAC|VENTILAT|AIR.CONDITION|\bDUCT|CHILLER|COOLING TOWER|AHU|FCU|CRAC|CRAH|EXHAUST", re.I), [("B", "09")]),
    (re.compile(r"INDUSTRIAL (PIPE|PIPING)|PROCESS PIPING", re.I), [("B", "10")]),
    (re.compile(r"FIRE\s*(PROTECT|SUPPRESS|ALARM|FIGHT)|SPRINKLER|FM200|FM.200|NOVEC|GAS SUPPRESSION|WATER MIST", re.I), [("B", "11")]),
    (re.compile(r"PLUMBING|DRAINAGE|SANITARY(?!\s+FIT)|WATER SUPPLY|HOT WATER|GAS SUPPLY|HEATING(?!\s+VALUE)", re.I), [("B", "12")]),
    (re.compile(r"TELECOM|COMMUNICATION|CABLING|STRUCTURED CABLING|\bFIBRE|\bFIBER|DATA CABLE", re.I), [("B", "13")]),
    (re.compile(r"CORROSION|ANTI.CORROS|PROTECTIVE COAT", re.I), [("B", "14"), ("A", "A.23")]),

    # C册 室外
    (re.compile(r"ROAD|PAVEMENT|CARRIAGEWAY", re.I), [("C", "C.02")]),
    (re.compile(r"MANHOLE|CULVERT|CATCH BASIN|STORM DRAIN|SEWER", re.I), [("C", "C.05")]),
    (re.compile(r"STREET LIGHT|EXTERNAL LIGHT|OUTDOOR LIGHT", re.I), [("C", "C.08")]),
    (re.compile(r"LANDSCAP|PLANTING|LAWN|TURF|SHRUB|TREE", re.I), [("C", "C.20")]),
    (re.compile(r"FENCE|BOUNDARY WALL|\bGATE\b|GUARDHOUSE", re.I), [("A", "A.31"), ("C", "C.20")]),
]


def _flatten_glossary(section: dict) -> list[tuple[str, list[str]]]:
    return [(en.lower(), zh_list) for en, zh_list in section.items() if en != "note"]


A_GLOSS = _flatten_glossary(GLOSSARY["civil_A"])
B_GLOSS = _flatten_glossary(GLOSSARY["mep_B"])
C_GLOSS = _flatten_glossary(GLOSSARY["external_C"])
D_GLOSS = _flatten_glossary(GLOSSARY["marine_D"])
E_GLOSS = _flatten_glossary(GLOSSARY["repair_E"])


def _match_keywords(text: str, gloss: list[tuple[str, list[str]]]) -> list[str]:
    """英文关键词 → 中文同义词命中 (词边界避免子串误伤)。

    中文描述走同义词直接子串命中 —— 词边界那套只对英文有意义，中文不分词。
    对英文清单零影响：英文描述里不会出现中文词。
    """
    text_l = text.lower()
    hits: list[str] = []
    for en, zh_terms in gloss:
        if any(zh and zh in text for zh in zh_terms):
            hits.extend(zh_terms)
            continue
        for token in re.split(r"[/\s]+", en):
            token = token.strip()
            if len(token) >= 4 and re.search(rf"\b{re.escape(token)}\b", text_l):
                hits.extend(zh_terms)
                break
    return hits


def _route(dept_blob: str | None) -> dict[str, set[str | None]]:
    """dept1+dept2+dept3 强信号: 返回 {'A': {'A.03', ...}, 'B': {'06'}, 'C': set()}"""
    forced: dict[str, set[str | None]] = {b: set() for b in "ABCDE"}
    if not dept_blob:
        return forced
    for pat, targets in DEPT2_ROUTER:
        if pat.search(dept_blob):
            for book, code in targets:
                forced.setdefault(book, set()).add(code)
    return forced


def _query_a_or_c(
    db_path: Path,
    zh_keywords: list[str],
    forced_codes: set[str | None] | None = None,
) -> list[dict[str, Any]]:
    if not zh_keywords and not forced_codes:
        return []
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cats: dict[str, dict] = {}

    # 1) Dept2 强制拉入 (None = 拉全部分部)
    if forced_codes:
        if None in forced_codes:
            cur.execute("SELECT code,name,name_EN FROM division ORDER BY code")
        else:
            placeholders = ",".join(["?"] * len(forced_codes))
            cur.execute(
                f"SELECT code,name,name_EN FROM division WHERE code IN ({placeholders})",
                list(forced_codes),
            )
        for code, name, name_en in cur.fetchall():
            cats.setdefault(code, {"code": code, "name": name,
                                   "name_en": name_en or name, "subs": []})

    # 2) 关键词命中分部/子分部
    for kw in set(zh_keywords or []):
        cur.execute("SELECT code,name,name_EN FROM division WHERE name LIKE ?", (f"%{kw}%",))
        for code, name, name_en in cur.fetchall():
            cats.setdefault(code, {"code": code, "name": name,
                                   "name_en": name_en or name, "subs": []})
        cur.execute(
            "SELECT division_code,sub_code,name,name_EN FROM sub_division WHERE name LIKE ?",
            (f"%{kw}%",),
        )
        for div_code, sub_code, name, name_en in cur.fetchall():
            if div_code not in cats:
                cur.execute("SELECT code,name,name_EN FROM division WHERE code=?", (div_code,))
                row = cur.fetchone()
                if row:
                    cats[div_code] = {"code": row[0], "name": row[1],
                                      "name_en": row[2] or row[1], "subs": []}

    # 3) 补齐命中分部的全部子分部
    for div_code in list(cats):
        cur.execute(
            "SELECT sub_code,name,name_EN FROM sub_division WHERE division_code=?",
            (div_code,),
        )
        existing = {s["code"] for s in cats[div_code]["subs"]}
        for sub_code, name, name_en in cur.fetchall():
            if sub_code not in existing:
                cats[div_code]["subs"].append({"code": sub_code, "name": name,
                                               "name_en": name_en or name})
    con.close()
    return list(cats.values())


_CHAP_PREFIX = re.compile(r"^第[一二三四五六七八九十百]+章\s*")


def _query_chapter_tree(
    db_path: Path,
    zh_keywords: list[str],
    forced_codes: set[str | None] | None = None,
) -> list[dict[str, Any]]:
    """给只有 chapter 树、没有 sub_division 的册用（E 册房屋修缮）。

    L1 章节当 Category，L2 当 Subcategory。章名带「第X章 」前缀，剥掉再用 ——
    带着前缀的名字进闭词表，LLM 抄回来的值和库里对不上。
    """
    if not zh_keywords and not forced_codes:
        return []
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    l1 = {}
    for cid, code, name in cur.execute(
            "SELECT chap_ID,chap_code,chap_Name FROM chapter WHERE chap_PID=0 ORDER BY chap_code"):
        l1[cid] = {"code": code, "name": _CHAP_PREFIX.sub("", name or "").strip()}

    wanted = set()
    if forced_codes:
        if None in forced_codes:
            wanted = set(l1)
        else:
            wanted = {cid for cid, v in l1.items() if v["code"] in forced_codes}

    for kw in set(zh_keywords or []):
        for cid, v in l1.items():
            if kw in v["name"]:
                wanted.add(cid)
        for (pid,) in cur.execute(
                "SELECT DISTINCT chap_PID FROM chapter WHERE chap_Name LIKE ?", (f"%{kw}%",)):
            if pid in l1:
                wanted.add(pid)

    cats = []
    for cid in sorted(wanted, key=lambda i: l1[i]["code"]):
        subs = []
        for code, name in cur.execute(
                "SELECT chap_code,chap_Name FROM chapter WHERE chap_PID=? ORDER BY chap_code LIMIT 30", (cid,)):
            clean = _CHAP_PREFIX.sub("", name or "").strip()
            if clean:
                subs.append({"code": code, "name": clean, "name_en": clean})
        cats.append({"code": l1[cid]["code"], "name": l1[cid]["name"],
                     "name_en": l1[cid]["name"], "subs": subs})
    con.close()
    return cats


def _query_b(
    zh_keywords: list[str],
    forced_codes: set[str | None] | None = None,
) -> list[dict[str, Any]]:
    if not zh_keywords and not forced_codes:
        return []
    con = sqlite3.connect(DB_B)
    cur = con.cursor()
    top_hits: dict[int, dict] = {}

    def _include_top(root_id: int) -> None:
        if root_id in top_hits:
            return
        cur.execute("SELECT chap_code,chap_Name,chap_Name_EN FROM chapter WHERE chap_ID=?", (root_id,))
        row = cur.fetchone()
        if not row:
            return
        top_hits[root_id] = {"code": row[0], "name": row[1],
                             "name_en": row[2] or row[1], "subs": []}
        cur.execute(
            "SELECT chap_code,chap_Name,chap_Name_EN FROM chapter WHERE chap_PID=? ORDER BY chap_Index LIMIT 20",
            (root_id,),
        )
        top_hits[root_id]["subs"] = [
            {"code": c, "name": n, "name_en": ne or n}
            for c, n, ne in cur.fetchall()
        ]

    # 1) Dept2 强制拉入
    if forced_codes:
        if None in forced_codes:
            cur.execute("SELECT chap_ID FROM chapter WHERE chap_PID IS NULL OR chap_PID=0")
            for (rid,) in cur.fetchall():
                _include_top(rid)
        else:
            for code in forced_codes:
                cur.execute("SELECT chap_ID FROM chapter WHERE chap_code=? AND (chap_PID IS NULL OR chap_PID=0)", (code,))
                row = cur.fetchone()
                if row:
                    _include_top(row[0])

    # 2) 关键词命中 → 追溯到顶层
    for kw in set(zh_keywords or []):
        cur.execute(
            "SELECT chap_ID,chap_PID FROM chapter WHERE (chap_Name LIKE ? OR chap_Name_EN LIKE ?)",
            (f"%{kw}%", f"%{kw}%"),
        )
        for chap_id, chap_pid in cur.fetchall():
            root_id = _b_root(cur, chap_id, chap_pid)
            if root_id:
                _include_top(root_id)
    con.close()
    return list(top_hits.values())


def _b_root(cur, chap_id: int, chap_pid: int | None) -> int | None:
    guard = 0
    while chap_pid and guard < 10:
        cur.execute(
            "SELECT chap_ID,chap_PID FROM chapter WHERE chap_ID=?",
            (chap_pid,),
        )
        row = cur.fetchone()
        if not row:
            return chap_id
        chap_id, chap_pid = row
        guard += 1
    return chap_id


def retrieve_candidates(
    descs: list[str],
    dept1: str | None = None,
    dept2: str | None = None,
    dept3: str | None = None,
) -> dict[str, Any]:
    joined = " ".join(descs)
    dept_blob = " ".join(filter(None, [dept1, dept2, dept3])).lower()

    if any(m in dept_blob for m in PRELIM_DEPT_MARKERS):
        return {"A": [], "B": [], "C": [], "D": [], "E": [], "hint": "PRELIM"}

    forced = _route(dept_blob)

    # 关键词搜索加上 Dept3 (含 {子标题}) 作为额外语料
    search_text = " ".join(filter(None, [joined, dept3 or ""]))
    a_kw = _match_keywords(search_text, A_GLOSS)
    b_kw = _match_keywords(search_text, B_GLOSS)
    c_kw = _match_keywords(search_text, C_GLOSS)
    d_kw = _match_keywords(search_text, D_GLOSS)
    e_kw = _match_keywords(search_text, E_GLOSS)

    return {
        "A": _query_a_or_c(DB_A, a_kw, forced["A"]),
        "B": _query_b(b_kw, forced["B"]),
        "C": _query_a_or_c(DB_C, c_kw, forced["C"]),
        # D 册有 division/sub_division，走和 A/C 一样的两级查询；
        # E 册没有 sub_division，只能从 chapter 树取，和 B 册一个路子
        "D": _query_a_or_c(DB_D, d_kw, forced.get("D")),
        "E": _query_chapter_tree(DB_E, e_kw, forced.get("E")),
        "hint": None,
        "forced_by_dept2": {k: sorted(v, key=str) for k, v in forced.items() if v},
    }


if __name__ == "__main__":
    demo = [
        "Cast-in-situ concrete to bored (rotary-drilled) piles, f'c(MPa)25",
        "Formwork to Pad Foundations",
    ]
    pool = retrieve_candidates(demo, dept1="Substructure", dept2="Piling")
    print(json.dumps(pool, ensure_ascii=False, indent=2))
