"""
第 2 步：脚本判定 + 分档路由（纯代码 · 0 token）

读 BOQ Excel，逐行判定路由类别，并按 Dept 分组从定额库闭词表检索候选，
按候选分部数分档，决定后续 LLM 调用层级。本脚本不写回、不调 LLM。

路由类别:
  SKIP      空 desc / 页眉 / 章节标题 → 直接跳过，不写回
  PRELIM    开办费章节内条款 → 开办费（不检索）
  SUM       暂定金额项(provisional sums) → 按章节对应分部直接分类
  PATTERN   规则库 patterns 命中(带 discipline) → 直接分类
  UNIQUE    唯一命中(候选分部==1) → 纯规则直接写回 (0 token)
  LOW       2-3 候选分部 → Haiku
  HIGH      4+ 候选分部 → Sonnet
  ZERO      零候选/异常 → Opus 仲裁 / 人工

用法:
    python route_boq.py -i BOQ.xlsx [--sheet 合并报表] [--header-row 3] \
        [--start-row N] [--cols desc:5,unit:6,qty:7] \
        [-o route_result.json]

通用性: 列位和数据起始行都从表头行实时解析，不写死 —— 模板改版列字母就会变，
写死的列号会读到编号列而不是描述列，结果全是 ZERO 档。--cols 只在表头认不出时兜底。
行号约定: openpyxl 读取，JSON row N = Excel row N（偏移 0，勿用 fastexcel to_pandas 核对）。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

import layout
from candidate_retrieval import retrieve_candidates, PRELIM_DEPT_MARKERS

_HERE = Path(__file__).resolve().parent
_RULES_PATH = _HERE.parent / "references" / "classification_rules.json"

HEADER_PATTERN = re.compile(r"^\s*[\{【《][^\}】》]+[\}】》]\s*$")
ALL_CAPS_HEADER = re.compile(r"^[A-Z0-9\s,\-&/\(\)]{6,}$")
TOTAL_LINE = re.compile(r"^(subtotal|total)\b", re.I)


def load_rules() -> dict:
    return json.loads(_RULES_PATH.read_text(encoding="utf-8"))


def is_header(desc: str) -> bool:
    if not desc:
        return True
    d = desc.strip()
    if HEADER_PATTERN.match(d):
        return True
    if ALL_CAPS_HEADER.match(d) and not any(c.isdigit() for c in d[:3]):
        return True
    return False


def is_prelim(dept1: str | None, dept2: str | None) -> bool:
    blob = " ".join(filter(None, [dept1, dept2])).lower()
    return any(m in blob for m in PRELIM_DEPT_MARKERS)


SRC_HEADERS = {"desc": "Description", "unit": "Unit", "qty": "Quantity"}


def _norm(v) -> str:
    return " ".join(str(v).replace("\n", " ").split()) if v is not None else ""


def open_sheet(wb, sheet: str | None):
    if sheet and sheet not in wb.sheetnames:
        wb.close()
        raise SystemExit(f"工作簿无 sheet {sheet!r}，现有: {wb.sheetnames}")
    return wb[sheet] if sheet else wb[wb.sheetnames[0]]


def read_header(path: Path, sheet: str | None, header_row: int) -> dict[str, int]:
    """表头名 -> 列号。同名列取最左的那个（原清单里 Unit / Rate 常有重名）。"""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = open_sheet(wb, sheet)
    header: dict[str, int] = {}
    for row in ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True):
        for i, v in enumerate(row, start=1):
            name = _norm(v)
            if name and name not in header:
                header[name] = i
        break
    wb.close()
    return header


def resolve_cols(header: dict[str, int], override: dict[str, int],
                 header_row: int) -> dict[str, int]:
    """列位按表头名定位。写死列号在模板改版后必错位，所以只把 --cols 当兜底。"""
    cols = {k: header[h] for k, h in SRC_HEADERS.items() if h in header}
    cols.update(override)
    missing = [SRC_HEADERS[k] for k in SRC_HEADERS if k not in cols]
    if missing:
        raise SystemExit(
            f"表头行第 {header_row} 行找不到列 {missing}；现有表头: {sorted(header)}。\n"
            f"表头行不对就用 --header-row，认不出列名就用 --cols desc:5,unit:6,qty:7 指定。")
    return cols


def detect_start_row(path: Path, sheet: str | None, header_row: int,
                     desc_col: int, probe: int = 30) -> int:
    """数据起始行 = 表头行之后第一个描述非空的行。

    模板是表头 3、数据 5（中间空一行留给 Main Key 的锚点），原清单可能表头 1、
    数据 2 —— 写死起始行不是漏掉前几行就是把表头读成数据。
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = open_sheet(wb, sheet)
    found = header_row + 1
    for r, row in enumerate(
        ws.iter_rows(min_row=header_row + 1, max_row=header_row + probe,
                     min_col=desc_col, max_col=desc_col, values_only=True),
        start=header_row + 1,
    ):
        if _norm(row[0]):
            found = r
            break
    wb.close()
    return found


def read_rows(path: Path, sheet: str | None, cols: dict[str, int],
              start_row: int, end_row: int) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if sheet is None:
        sheet = wb.sheetnames[0]
    ws = wb[sheet]
    max_row = min(end_row, ws.max_row) if end_row else ws.max_row
    rows = []
    for r, row in enumerate(
        ws.iter_rows(min_row=start_row, max_row=max_row,
                     min_col=1, max_col=max(cols.values()), values_only=True),
        start=start_row,
    ):
        desc = row[cols["desc"] - 1]
        rec = {"row": r, "desc": (str(desc).strip() if desc is not None else "")}
        for name, col in cols.items():
            if name != "desc":
                v = row[col - 1]
                rec[name] = str(v).strip() if v is not None else ""
        rows.append(rec)
    wb.close()
    return rows


def derive_dept(rows: list[dict]) -> list[dict]:
    """从 desc 列的层级符号【】《》{} 推导 dept1/2/3（L1/L2/L3 父级栈）。
    适用于没有独立 Dept 列、层级用符号表达的 BOQ。"""
    l1 = l2 = l3 = ""
    for rec in rows:
        s = rec["desc"].strip()
        if s.startswith("【"):
            l1 = re.sub(r"[【】]", "", s)
            l2 = l3 = ""
        elif s.startswith("《"):
            l2 = re.sub(r"[《》]", "", s)
            l3 = ""
        elif s.startswith("{"):
            l3 = re.sub(r"[{}]", "", s)
        rec["dept1"], rec["dept2"], rec["dept3"] = l1, l2, l3
    return rows


def classify_by_rules(rules: dict, rec: dict) -> dict | None:
    """返回直接命中规则的分类结果，未命中返回 None。
    顺序: 暂定金额 → patterns（带 discipline）。
    搜索范围: desc + dept1/2/3（标题上下文提供关键信号，如 Firestopping 只在 dept3 出现）"""
    desc = rec["desc"]
    dept_ctx = " ".join(filter(None, [rec.get("dept1"), rec.get("dept2"), rec.get("dept3")]))
    search_text = f"{desc} {dept_ctx}"
    # 暂定金额项（仅匹配 desc，不匹配 dept）
    m = re.match(rules["provisional_sums_rule"]["regex"], desc, re.I)
    if m:
        tgt = rules["provisional_sums_rule"]["mapping"].get(m.group(1))
        if tgt:
            return {"route": "SUM", "reason": f"暂列金→{tgt['category_name']}", **tgt}
        return {"route": "PRELIM", "reason": "合同级兜底项，保留开办费",
                "discipline": "PRELIM", "category_code": "", "category_name": "开办费"}
    # patterns 规则（带 discipline 才自动匹配）
    for p in rules["patterns"]:
        if p.get("discipline") is None:
            continue
        if re.search(p["pattern"], search_text, re.I if p.get("flags") == "i" else 0):
            result = {"route": "PATTERN", "reason": p["reason"],
                      "discipline": p["discipline"], "category_code": p.get("category_code") or "",
                      "category_name": p.get("category_name") or ""}
            for en_key in ("discipline_en", "category_name_en", "subcategory_name_en"):
                if en_key in p and p[en_key]:
                    result[en_key] = p[en_key]
            return result
    return None


def bucket_by_divisions(pool: dict, routing: dict) -> tuple[str, str]:
    n = sum(len(pool.get(k, [])) for k in ("A", "B", "C"))
    if n == 0:
        return "ZERO", f"零候选({n} 分部) → Opus 仲裁/人工"
    if n <= routing["unique_max_divisions"]:
        return "UNIQUE", f"唯一命中({n} 分部) → 纯规则直接写回"
    if n <= routing["low_max_divisions"]:
        return "LOW", f"{n} 候选分部 → Haiku"
    return "HIGH", f"{n} 候选分部 → Sonnet"


def main() -> None:
    ap = argparse.ArgumentParser(description="BOQ 分类第 2 步：判定+分档路由（0 token）")
    ap.add_argument("-i", "--input", required=True, help="BOQ Excel 路径")
    ap.add_argument("--sheet", default="合并报表", help="sheet 名")
    ap.add_argument("--header-row", type=int, default=layout.HEADER_ROW,
                    help=f"表头行号（默认 {layout.HEADER_ROW}，工作台布局）")
    ap.add_argument("--start-row", type=int, default=0,
                    help="数据起始行（默认自动：表头行之后第一个描述非空的行）")
    ap.add_argument("--end-row", type=int, default=0, help="数据结束行（默认到表尾）")
    ap.add_argument("--cols", default="",
                    help="列配置 name:col 逗号分隔，仅在表头认不出时兜底，如 desc:5,unit:6,qty:7")
    ap.add_argument("-o", "--out", default="route_result.json", help="输出 JSON 路径")
    ap.add_argument("--rules", default=str(_RULES_PATH), help="技能规则库路径")
    ap.add_argument("--no-derive-dept", dest="derive_dept", action="store_false",
                    help="不从层级符号推导 dept1/2/3（报价工作台没有 Dept 列，默认要推）")
    ap.set_defaults(derive_dept=True)
    args = ap.parse_args()

    override = ({k: int(v) for k, v in (kv.split(":") for kv in args.cols.split(","))}
                if args.cols.strip() else {})
    src = Path(args.input)
    header = read_header(src, args.sheet, args.header_row)
    cols = resolve_cols(header, override, args.header_row)
    start_row = args.start_row or detect_start_row(
        src, args.sheet, args.header_row, cols["desc"])
    print(f"[step2] 表头行 {args.header_row} | 列 "
          + ", ".join(f"{k}={get_column_letter(v)}" for k, v in sorted(cols.items()))
          + f" | 数据起始行 {start_row}", file=sys.stderr)

    rules = json.loads(Path(args.rules).read_text(encoding="utf-8"))
    routing = rules["routing"]

    rows = read_rows(src, args.sheet, cols, start_row, args.end_row)
    if args.derive_dept:
        rows = derive_dept(rows)
    print(f"[step2] 读取 {len(rows)} 行", file=sys.stderr)

    # 分组检索候选池（同 dept1+dept2 共享一个池，避免逐行检索）
    ai_groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in rows:
        if rec["desc"] and not is_header(rec["desc"]) \
           and not is_prelim(rec.get("dept1"), rec.get("dept2")):
            ai_groups[(rec.get("dept1") or "_", rec.get("dept2") or "_")].append(rec)
    pool_cache: dict[tuple, dict] = {}
    for key, members in ai_groups.items():
        pool_cache[key] = retrieve_candidates(
            descs=[m["desc"] for m in members[:15]],
            dept1=members[0].get("dept1"), dept2=members[0].get("dept2"),
        )

    skip_pats = [
        (re.compile(p["pattern"], re.I if p.get("flags") == "i" else 0), p)
        for p in rules.get("skip_patterns", [])
    ]

    out_rows, pre_counts = [], Counter()
    for rec in rows:
        desc, d1, d2 = rec["desc"], rec.get("dept1"), rec.get("dept2")
        entry = {"row": rec["row"], "desc": desc,
                 "dept1": d1, "dept2": d2, "dept3": rec.get("dept3")}

        if not desc or is_header(desc) or TOTAL_LINE.match(desc):
            entry.update({"route": "SKIP", "reason": "页眉/章节标题/汇总行"})
        elif any(p[0].search(desc) for p in skip_pats):
            entry.update({"route": "SKIP", "reason": "章节说明文字（preamble notes）"})
        elif is_prelim(d1, d2):
            entry.update({"route": "PRELIM", "reason": "开办费章节", "discipline": "PRELIM"})
        else:
            direct = classify_by_rules(rules, rec)
            if direct:
                entry.update(direct)
            else:
                key = (d1 or "_", d2 or "_")
                pool = pool_cache.get(key, {"A": [], "B": [], "C": []})
                route, reason = bucket_by_divisions(pool, routing)
                entry.update({
                    "route": route, "reason": reason,
                    "candidates": {
                        k: [{"code": c["code"], "name": c["name"],
                             "name_en": c.get("name_en", c["name"]),
                             "n_subs": len(c.get("subs", [])),
                             "subs": [s.get("name_en", s["name"]) for s in c.get("subs", [])]}
                            for c in pool.get(k, [])]
                        for k in ("A", "B", "C")
                    },
                })
        pre_counts[entry["route"]] += 1
        out_rows.append(entry)

    result = {
        "meta": {"input": str(Path(args.input)), "sheet": args.sheet,
                 "rules_version": rules.get("version"),
                 "routing": routing, "offset_note": "row N = Excel row N (openpyxl, 偏移0)"},
        "rows": out_rows,
        "stats": dict(pre_counts),
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[step2] 已写 {out_path}", file=sys.stderr)
    print("[step2] 路由分布:", dict(pre_counts), file=sys.stderr)


if __name__ == "__main__":
    main()
