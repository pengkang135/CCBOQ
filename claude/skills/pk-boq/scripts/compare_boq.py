# -*- coding: utf-8 -*-
"""多份 BOQ 清单工程量对比分析（通用版，与具体项目/单位无关）

Usage:
    python compare_boq.py --list "A.xlsx|甲方|MergeSheet|code=1,desc=2,unit=3,qty=4" \
                          --list "B.xlsx|乙方|MergeSheet|code=1,desc=2,unit=3,qty=6" [-o out.md]
    python compare_boq.py --config lists.json

    第一份 --list 为对比基准。也可作为模块导入:
    from compare_boq import BOQComparator, ListSpec
"""
import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict, OrderedDict
from difflib import SequenceMatcher

# BOQ 混合类型列会触发 fastexcel 的 dtype 回退警告，逐行读取本就按字符串处理，噪音无意义
logging.getLogger("fastexcel").setLevel(logging.ERROR)

import fastexcel

# ── 正则 ──────────────────────────────────────────────
# 分组/条目编码：形如 C、C.1、C.1.2、1.2.3
CODE_RE = re.compile(r"^([A-Za-z]+\d*|\d+)(?:\.\d+)*$")
# 前后不许是字母，但允许紧跟数字：B.2.9ADD 算 ADD 项，ADDITIONAL 不算
ADD_RE = re.compile(r"(?<![A-Za-z])ADD(?![A-Za-z])", re.IGNORECASE)
# 分组标识只认短记号（B、F3、12），排除 ADD/RunWay/scheme 这类填在编码列的说明词
GROUP_TOKEN_RE = re.compile(r"^(?:[A-Za-z]\d{0,2}|\d{1,3})$")

# pk-boq 层级符号约定：L1【】 L2《》 L3{}，见 pk-boq-hierarchy 技能
HIER_MARKS = ((1, "【", "】"), (2, "《", "》"), (3, "{", "}"))
UNGROUPED = "(未分组)"

DEFAULT_COLS = {"code": 1, "desc": 2, "unit": 3, "qty": 4}
DEFAULT_SHEET = "MergeSheet"


def safe_float(v):
    """安全转 float，None/NaN/空串/千分位逗号都容错"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "-"):
        return None
    try:
        return float(s.replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return None


def safe_str(v):
    """安全转 str，NaN 与 None 归一为空串"""
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def normalize_unit(u):
    """归一化单位"""
    u = safe_str(u)
    if not u:
        return ""
    low = u.lower()
    mapping = {
        "m3": "m³", "m2": "m²", "no.": "No.", "nos": "No.", "nr.": "No.",
        "ton": "t", "tonne": "t", "item": "Item", "ls": "LS", "l.s.": "LS",
        "lump sum": "LS", "lin.m": "m", "lm": "m", "rm": "m",
        "kg": "kg", "set": "set", "month": "month", "day": "day",
        "hour": "hr", "week": "wk", "mm": "mm", "cm": "cm",
    }
    if low in mapping:
        return mapping[low]
    if u in ("m³", "m²", "m", "No.", "t", "LS", "Item", "kg", "set",
             "month", "day", "hr", "wk", "mm", "cm", "%"):
        return u
    return u


def parse_item_code(code_str):
    """解析条目编码，返回 (去掉 ADD 标记的干净编码, is_add)"""
    code = safe_str(code_str)
    if not code:
        return "", False
    is_add = bool(ADD_RE.search(code))
    clean = ADD_RE.sub("", code).strip().rstrip(".-").rstrip()
    return clean, is_add


def extract_group_id(code, group_re=None):
    """从编码提取顶层分组标识。'Class C'→C，'C.1.2'→C，'1.2.3'→1"""
    code = safe_str(code)
    if not code:
        return None
    if group_re:
        m = group_re.search(code)
        return m.group(1) if m else None
    token = code.split()[-1] if code.split() else ""
    head = token.split(".")[0].strip()
    return head if head and CODE_RE.match(token) else None


def hierarchy_level(desc):
    """按 pk-boq 层级符号判断标题级别，返回 (级别或None, 去掉符号的文字)"""
    d = safe_str(desc)
    for lv, lo, hi in HIER_MARKS:
        if len(d) >= 2 and d.startswith(lo) and d.endswith(hi):
            return lv, d[1:-1].strip()
    return None, d


def code_depth(code):
    """编码层级深度。'Class B'→1，'B.1'→2，'B.1.1'→3"""
    parts = safe_str(code).split()
    return len(parts[-1].split(".")) if parts else 0


# ═══════════════════════════════════════════════════════
# 清单规格与读取
# ═══════════════════════════════════════════════════════

class ListSpec:
    """一份待对比清单的读取规格"""

    def __init__(self, file, label=None, sheet=DEFAULT_SHEET, cols=None):
        self.file = str(file)
        self.label = label or Path(file).stem
        self.sheet = sheet or DEFAULT_SHEET
        self.cols = dict(DEFAULT_COLS)
        if cols:
            self.cols.update(cols)

    @classmethod
    def from_cli(cls, spec):
        """解析 CLI 规格串: path[|label[|sheet[|code=1,desc=2,unit=3,qty=4]]]"""
        parts = [p.strip() for p in spec.split("|")]
        file = parts[0]
        label = parts[1] if len(parts) > 1 and parts[1] else None
        sheet = parts[2] if len(parts) > 2 and parts[2] else DEFAULT_SHEET
        cols = None
        if len(parts) > 3 and parts[3]:
            cols = {}
            for kv in parts[3].split(","):
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                cols[k.strip()] = int(v.strip())
        return cls(file, label, sheet, cols)

    @classmethod
    def from_dict(cls, d):
        return cls(d["file"], d.get("label"), d.get("sheet", DEFAULT_SHEET), d.get("cols"))

    def __repr__(self):
        return f"ListSpec({self.label}: {Path(self.file).name}!{self.sheet} {self.cols})"


def read_boq(spec):
    """按规格读取一份清单为原始行。列号 1-based"""
    if not Path(spec.file).exists():
        raise SystemExit(f"[错误] {spec.label}: 文件不存在 → {spec.file}")
    reader = fastexcel.read_excel(spec.file)
    if spec.sheet not in reader.sheet_names:
        raise SystemExit(
            f"[错误] {Path(spec.file).name} 中无 sheet '{spec.sheet}'。"
            f"可用: {', '.join(reader.sheet_names)}"
        )
    df = reader.load_sheet(spec.sheet, header_row=None).to_pandas()

    ci = {k: v - 1 for k, v in spec.cols.items()}
    ncol = df.shape[1]
    for k, i in ci.items():
        if i >= ncol:
            raise SystemExit(
                f"[错误] {spec.label}: {k} 列指定为第 {i + 1} 列，"
                f"但 sheet '{spec.sheet}' 只有 {ncol} 列"
            )

    rows = []
    for row_idx, vals in enumerate(df.itertuples(index=False, name=None), start=1):
        code = safe_str(vals[ci["code"]])
        desc = safe_str(vals[ci["desc"]])
        unit = normalize_unit(vals[ci["unit"]])
        qty = safe_float(vals[ci["qty"]])

        if not code and not desc and qty is None:
            continue
        if code.lower() in ("item", "item no.", "no.") and not qty:
            continue

        rows.append({"row": row_idx, "item_code": code, "desc": desc,
                     "unit": unit, "qty": qty})
    return rows


# ═══════════════════════════════════════════════════════
# 行分类与结构化
# ═══════════════════════════════════════════════════════

def classify_rows(raw_rows, source, group_re=None):
    """分类为 分组标题 / 小节标题 / BOQ 条目，并回填所属分组与小节。

    分组优先按 pk-boq 层级符号【】识别；清单没打层级符号时才退回形态推断
    （无单位无数量 + 编码是单段短记号）。条目一律沿用上方分组，不自行推断，
    否则 ADD / RunWay 这类填在编码列的说明词会各自伪造出一个分组。
    """
    current_group = None
    current_section = None
    classified = []

    for r in raw_rows:
        code, unit, qty = r["item_code"], r["unit"], r["qty"]
        level, clean_desc = hierarchy_level(r["desc"])
        gid = extract_group_id(code, group_re)
        depth = code_depth(code)
        is_blank = not unit and qty is None

        if level == 1:
            current_group = gid or clean_desc[:24] or UNGROUPED
            current_section = None
            classified.append({**r, "desc": clean_desc, "group_id": current_group,
                               "group_name": clean_desc, "section_id": None,
                               "kind": "group", "source": source})
            continue

        if level in (2, 3):
            if code and CODE_RE.match(code.split()[-1]):
                current_section = code
            classified.append({**r, "desc": clean_desc, "group_id": current_group,
                               "group_name": None, "section_id": current_section,
                               "kind": "section", "source": source})
            continue

        if is_blank:
            if gid and depth == 1 and GROUP_TOKEN_RE.match(gid):
                current_group = gid
                current_section = None
                classified.append({**r, "group_id": gid, "group_name": r["desc"],
                                   "section_id": None, "kind": "group", "source": source})
            elif code and depth <= 3 and CODE_RE.match(code.split()[-1]):
                current_section = code
                classified.append({**r, "group_id": current_group, "group_name": None,
                                   "section_id": current_section, "kind": "section",
                                   "source": source})
            continue

        clean_code, is_add = parse_item_code(code)
        classified.append({**r, "group_id": current_group, "group_name": None,
                           "section_id": current_section, "kind": "item", "source": source,
                           "is_add": is_add, "clean_code": clean_code})

    if not any(r["kind"] == "group" for r in classified):
        for r in classified:
            if r["kind"] == "item":
                r["group_id"] = extract_group_id(r["item_code"], group_re) or UNGROUPED
    else:
        for r in classified:
            if r["kind"] == "item" and not r["group_id"]:
                r["group_id"] = UNGROUPED

    return classified


def collect_group_names(classified_lists):
    """汇总各清单里的分组显示名，先到先得"""
    names = OrderedDict()
    for classified in classified_lists:
        for r in classified:
            if r["kind"] == "group" and r["group_id"] and r.get("group_name"):
                names.setdefault(r["group_id"], r["group_name"])
    return names


# ═══════════════════════════════════════════════════════
# 条目匹配引擎（三级降级）
# ═══════════════════════════════════════════════════════

def desc_similarity(a, b):
    """描述相似度，先剥离括号内容与标点再比"""
    if not a or not b:
        return 0.0

    def clean(s):
        s = s.lower()
        s = re.sub(r"[（(].*?[）)]", "", s)
        s = re.sub(r"\{.*?\}", "", s)
        s = re.sub(r"[^\w\s]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    return SequenceMatcher(None, clean(a), clean(b)).ratio()


def match_items(base_items, other_items, sim_threshold=0.75):
    """把 other 条目匹配到 base 条目。返回 {base_idx: [(item, confidence)]} 与未匹配项"""
    matches = defaultdict(list)
    unmatched = []

    base_by_section = defaultdict(list)
    for i, item in enumerate(base_items):
        sec = item.get("section_id") or ""
        sec_key = ".".join(sec.split(".")[:2])
        base_by_section[(item["group_id"], sec_key)].append((i, item))

    for oitem in other_items:
        grp = oitem["group_id"]
        osec = oitem.get("section_id") or ""
        osec_key = ".".join(osec.split(".")[:2])

        candidates = base_by_section.get((grp, osec_key), [])
        if not candidates:
            candidates = base_by_section.get((grp, ""), [])
        if not candidates:
            candidates = [pair for (g, _), items in base_by_section.items()
                          if g == grp for pair in items]
        if not candidates:
            unmatched.append(oitem)
            continue

        clean_ocode = oitem.get("clean_code", "")
        best_match, best_confidence = None, 0.0

        for bi, bitem in candidates:
            if clean_ocode and bitem.get("clean_code") == clean_ocode:
                best_match, best_confidence = bi, 1.0
                break

        if best_match is None and clean_ocode:
            for bi, bitem in candidates:
                bcode = bitem.get("clean_code", "")
                if bcode and bcode.startswith(clean_ocode + "."):
                    best_match, best_confidence = bi, 0.85
                    break

        if best_match is None:
            for bi, bitem in candidates:
                sim = desc_similarity(oitem.get("desc", ""), bitem.get("desc", ""))
                if sim > best_confidence:
                    best_match, best_confidence = bi, sim
            if best_confidence < sim_threshold:
                best_match = None

        if best_match is not None:
            matches[best_match].append((oitem, best_confidence))
        else:
            unmatched.append(oitem)

    return matches, unmatched


# ═══════════════════════════════════════════════════════
# 对比计算
# ═══════════════════════════════════════════════════════

def format_qty(v):
    """按量级分档格式化数量"""
    if v is None:
        return "-"
    if isinstance(v, float):
        if abs(v) >= 1e6:
            return f"{v:,.0f}"
        if abs(v) >= 1e3:
            return f"{v:,.1f}"
        if abs(v) >= 1:
            return f"{v:,.2f}"
        return f"{v:.4f}"
    return str(v)


def calc_diff(vals):
    """差异百分比 (max-min)/max*100，至少两个有效值才计算"""
    valid = [v for v in vals if v is not None and v > 0]
    if len(valid) < 2:
        return None
    mx, mn = max(valid), min(valid)
    return (mx - mn) / mx * 100 if mx else None


def build_comparison_rows(items_by_label, labels, sim_threshold=0.75):
    """以 labels[0] 为基准构建对比行，每行含各清单对应工程量"""
    base_label = labels[0]
    base_items = items_by_label[base_label]
    other_labels = labels[1:]

    matched, unmatched = {}, {}
    for lb in other_labels:
        matched[lb], unmatched[lb] = match_items(base_items, items_by_label[lb], sim_threshold)

    comp_rows = []
    for bi, bitem in enumerate(base_items):
        if bitem["qty"] is None:
            continue
        qtys = {base_label: bitem["qty"]}
        for lb in other_labels:
            hits = matched[lb].get(bi)
            qtys[lb] = max(hits, key=lambda x: x[1])[0]["qty"] if hits else None

        notes = []
        if bitem.get("is_add"):
            notes.append("ADD")
        missing = [lb for lb in other_labels if qtys[lb] is None]
        if missing:
            notes.append("；".join(f"{lb}无" for lb in missing))

        comp_rows.append({
            "group_id": bitem["group_id"], "section_id": bitem.get("section_id") or "",
            "item_code": bitem.get("item_code", ""), "desc": bitem.get("desc", ""),
            "unit": bitem.get("unit", ""), "qtys": qtys,
            "diff_pct": calc_diff(list(qtys.values())),
            "notes": ", ".join(notes), "is_add": bool(bitem.get("is_add")),
        })

    for lb in other_labels:
        for oitem in unmatched[lb]:
            if oitem["qty"] is None:
                continue
            qtys = {x: None for x in labels}
            qtys[lb] = oitem["qty"]
            comp_rows.append({
                "group_id": oitem["group_id"], "section_id": oitem.get("section_id") or "",
                "item_code": oitem.get("item_code", ""), "desc": oitem.get("desc", ""),
                "unit": oitem.get("unit", ""), "qtys": qtys, "diff_pct": None,
                "notes": f"{lb}独有", "is_add": bool(oitem.get("is_add")),
            })

    return comp_rows


def only_in(row, labels):
    """该行工程量是否仅出现在一份清单中，是则返回其标签"""
    present = [lb for lb in labels if row["qtys"].get(lb) is not None]
    return present[0] if len(present) == 1 else None


# ═══════════════════════════════════════════════════════
# Markdown 报告
# ═══════════════════════════════════════════════════════

class BOQComparator:
    """多份 BOQ 清单工程量对比分析器。

    Usage:
        comp = BOQComparator(project_name="My Project")
        comp.compare([ListSpec("a.xlsx", "甲"), ListSpec("b.xlsx", "乙")], "report.md")
    """

    def __init__(self, project_name="", report_date="", threshold=20.0,
                 sim_threshold=0.75, group_re=None, top_n=10):
        self.project_name = project_name
        self.report_date = report_date or datetime.now().strftime("%Y-%m-%d")
        self.threshold = threshold
        self.sim_threshold = sim_threshold
        self.group_re = re.compile(group_re) if group_re else None
        self.top_n = top_n
        self.labels = []
        self.group_names = {}
        self.groups = []

    def compare(self, specs, output_path=None):
        """执行对比分析并写出 Markdown 报告，返回输出路径"""
        if len(specs) < 2:
            raise SystemExit("[错误] 至少需要两份清单才能对比")

        labels, seen = [], set()
        for s in specs:
            lb = s.label
            n = 2
            while lb in seen:
                lb = f"{s.label}({n})"
                n += 1
            s.label = lb
            seen.add(lb)
            labels.append(lb)
        self.labels = labels

        output_path = Path(output_path) if output_path else (
            Path.cwd() / f"{self.report_date}_BOQ_Comparison_Report.md")

        print("=" * 70)
        print("BOQ 清单工程量对比分析")
        print("=" * 70)

        print("\n[1/4] 读取清单...")
        classified_lists, items_by_label = [], {}
        for s in specs:
            raw = read_boq(s)
            cls = classify_rows(raw, s.label, self.group_re)
            items = [r for r in cls if r["kind"] == "item"]
            classified_lists.append(cls)
            items_by_label[s.label] = items
            print(f"  {s.label}: 原始 {len(raw)} 行 → BOQ 条目 {len(items)} 项"
                  f"  ({Path(s.file).name}!{s.sheet})")

        self.group_names = collect_group_names(classified_lists)

        print("\n[2/4] 匹配条目（基准 = %s）..." % labels[0])
        comp_rows = build_comparison_rows(items_by_label, labels, self.sim_threshold)
        print(f"  生成 {len(comp_rows)} 个对比行")

        self.groups = sorted({r["group_id"] for r in comp_rows if r["group_id"]},
                             key=lambda g: (len(g), g))
        for g in self.groups:
            n = len([r for r in comp_rows if r["group_id"] == g])
            print(f"  分组 {g}: {n} 行")

        print("\n[3/4] 生成 Markdown 报告...")
        comp_rows.sort(key=lambda r: (r["group_id"] or "~", r["section_id"] or "",
                                      r["item_code"] or ""))
        content = "\n".join(self._build_report(comp_rows))

        output_path.write_text(content, encoding="utf-8")
        print(f"\n[4/4] 报告已生成: {output_path}")
        print(f"  文件大小: {output_path.stat().st_size:,} bytes")
        return str(output_path)

    def _group_title(self, g):
        name = self.group_names.get(g)
        return f"{g} - {name}" if name else str(g)

    def _fmt_diff(self, pct):
        """差异百分比展示，超阈值才加粗"""
        if pct is None:
            return "-"
        return f"**{pct:.0f}%**" if pct > self.threshold else f"{pct:.0f}%"

    def _build_report(self, comp_rows):
        rep = []
        if self.project_name:
            rep.append(f"# {self.project_name}")
        rep.append("# BOQ 清单工程量对比分析报告")
        rep.append("")
        rep.append(f"> **日期**: {self.report_date}")
        rep.append(f"> **对比清单**: {' / '.join(self.labels)}（共 {len(self.labels)} 份）")
        rep.append(f"> **比较基准**: 以 {self.labels[0]} 清单体系为基准，逐项匹配其余清单")
        rep.append(f"> **差异阈值**: {self.threshold:.0f}%（超过则在报告中加粗标注）")
        rep.append("")

        rep.append(self._summary_table(comp_rows))
        rep.append("")

        for i, g in enumerate(self.groups, start=2):
            print(f"  生成分组 {g}...")
            rep.append(self._group_section(comp_rows, g, i))
            rep.append("")

        rep.append(self._key_findings(comp_rows, len(self.groups) + 2))
        rep.append("")
        rep.append("---\n")
        rep.append("## 附录：图例说明\n")
        rep.append("| 标记 | 含义 |")
        rep.append("|------|------|")
        rep.append("| `[ADD]` | 基准清单外新增的条目 |")
        rep.append("| `-` | 该清单中无此条目或无工程量 |")
        rep.append(f"| **差异%** | (最大值-最小值)/最大值×100%，仅 2 份及以上有效值时计算 |")
        rep.append("| `XXX独有` | 仅该份清单有此条目 |")
        rep.append("| `XXX无` | 该份清单中无此条目 |")
        rep.append(f"| 差异>{self.threshold:.0f}% 加粗 | 各清单之间存在显著工程量偏差 |")
        return rep

    def _summary_table(self, comp_rows):
        lines = ["## 1. 总体概览\n"]
        head = "| 分组 | 名称 | " + " | ".join(f"{lb}条目" for lb in self.labels)
        head += f" | ADD项 | 差异>{self.threshold:.0f}%项 | 关键观察 |"
        lines.append(head)
        lines.append("|" + "---|" * (len(self.labels) + 5))

        for g in self.groups:
            crs = [r for r in comp_rows if r["group_id"] == g]
            counts = [len([r for r in crs if r["qtys"].get(lb) is not None])
                      for lb in self.labels]
            add_n = len([r for r in crs if r["is_add"]])
            gt_n = len([r for r in crs if r["diff_pct"] is not None
                        and r["diff_pct"] > self.threshold])

            obs = []
            if gt_n:
                obs.append(f"{gt_n}项差异>{self.threshold:.0f}%")
            if add_n:
                obs.append(f"{add_n}项ADD")
            lines.append(f"| {g} | {self.group_names.get(g, '')} | "
                         + " | ".join(str(c) for c in counts)
                         + f" | {add_n} | {gt_n} | {'; '.join(obs) or '基本一致'} |")
        return "\n".join(lines)

    def _group_section(self, comp_rows, g, idx):
        crs = [r for r in comp_rows if r["group_id"] == g]
        if not crs:
            return ""

        lines = [f"## {idx}. {self._group_title(g)}\n"]
        stat = " | ".join(
            f"{lb} {len([r for r in crs if r['qtys'].get(lb) is not None])} 项"
            for lb in self.labels)
        lines.append(f"**该组条目统计**: {stat} | ADD {len([r for r in crs if r['is_add']])} 项\n")

        lines.append("| # | Item Code | 项目描述 | Unit | "
                     + " | ".join(self.labels) + " | 差异% | 备注 |")
        lines.append("|---|-----------|---------|------|"
                     + "---|" * len(self.labels) + "------|------|")

        for n, r in enumerate(crs, start=1):
            code = r["item_code"]
            if r["is_add"] and not ADD_RE.search(code):
                code = f"{code} [ADD]"
            diff = self._fmt_diff(r["diff_pct"])
            qtys = " | ".join(format_qty(r["qtys"].get(lb)) for lb in self.labels)
            lines.append(f"| {n} | {code} | {r['desc'][:80]} | {r['unit']} | "
                         f"{qtys} | {diff} | {r['notes']} |")
        return "\n".join(lines)

    def _key_findings(self, comp_rows, idx):
        lines = [f"## {idx}. 关键发现\n"]

        with_diff = sorted((r for r in comp_rows if r["diff_pct"]),
                           key=lambda x: x["diff_pct"], reverse=True)[:self.top_n]
        if with_diff:
            lines.append(f"### 工程量差异最大的 {len(with_diff)} 项\n")
            lines.append("| # | Item Code | 项目描述 | Unit | "
                         + " | ".join(self.labels) + " | 差异% |")
            lines.append("|---|-----------|---------|------|"
                         + "---|" * len(self.labels) + "------|")
            for i, r in enumerate(with_diff, 1):
                qtys = " | ".join(format_qty(r["qtys"].get(lb)) for lb in self.labels)
                lines.append(f"| {i} | {r['item_code']} | {r['desc'][:60]} | "
                             f"{r['unit']} | {qtys} | {self._fmt_diff(r['diff_pct'])} |")
        else:
            lines.append("### 工程量差异\n\n各清单已匹配条目工程量完全一致。")

        lines.append("\n### 各清单独有条目统计\n")
        lines.append("| 分组 | " + " | ".join(f"{lb} 独有" for lb in self.labels) + " |")
        lines.append("|------|" + "---|" * len(self.labels))
        for g in self.groups:
            crs = [r for r in comp_rows if r["group_id"] == g]
            counts = defaultdict(int)
            for r in crs:
                lb = only_in(r, self.labels)
                if lb:
                    counts[lb] += 1
            if any(counts.values()):
                lines.append(f"| {g} | "
                             + " | ".join(str(counts[lb]) for lb in self.labels) + " |")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

def load_config(path):
    """读取 JSON 配置，返回 (specs, 顶层选项)"""
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    specs = [ListSpec.from_dict(d) for d in cfg.get("lists", [])]
    opts = {k: cfg[k] for k in ("project", "date", "threshold", "sim_threshold",
                                "group_re", "top_n", "output") if k in cfg}
    return specs, opts


def main():
    parser = argparse.ArgumentParser(
        description="多份 BOQ 清单工程量对比分析（第一份为基准）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
--list 规格串格式:
  path[|label[|sheet[|code=1,desc=2,unit=3,qty=4]]]     列号 1-based，省略部分用默认值
  默认 sheet=MergeSheet, code=1,desc=2,unit=3,qty=4

示例:
  # 两份清单，列位相同，走默认列映射
  python compare_boq.py --list "A.xlsx|甲方" --list "B.xlsx|乙方"

  # 三份清单，第三份工程量在第 6 列
  python compare_boq.py --list "A.xlsx|甲方" --list "B.xlsx|乙方" \\
                        --list "C.xlsx|丙方|MergeSheet|code=1,desc=2,unit=3,qty=6" \\
                        -o 对比报告.md --project "某港口项目"

  # sheet 名含中文时改用 JSON 配置，避开命令行编码问题
  python compare_boq.py --config lists.json
        """,
    )
    parser.add_argument("--list", dest="lists", action="append", default=[],
                        help="清单规格串，可重复；第一个为对比基准")
    parser.add_argument("--config", help="JSON 配置文件（sheet 名含中文时推荐）")
    parser.add_argument("-o", "--output", default=None,
                        help="输出 .md 路径（默认 {date}_BOQ_Comparison_Report.md）")
    parser.add_argument("--project", default="", help="项目名称（显示在报告标题）")
    parser.add_argument("--date", default="", help="报告日期（默认今日）")
    parser.add_argument("-t", "--threshold", type=float, default=20.0,
                        help="差异高亮阈值百分比（默认 20）")
    parser.add_argument("--sim-threshold", type=float, default=0.75,
                        help="描述相似度匹配下限（默认 0.75）")
    parser.add_argument("--group-re", default=None,
                        help="自定义分组提取正则，需含一个捕获组；默认取编码首段")
    parser.add_argument("--top-n", type=int, default=10,
                        help="关键发现中列出的最大差异项数（默认 10）")
    args = parser.parse_args()

    if args.config:
        specs, opts = load_config(args.config)
        specs += [ListSpec.from_cli(s) for s in args.lists]
    else:
        specs, opts = [ListSpec.from_cli(s) for s in args.lists], {}

    if len(specs) < 2:
        parser.error("至少需要两份清单：重复 --list 或用 --config 提供")

    def pick(name, cli_val, default):
        return cli_val if cli_val != default else opts.get(name, default)

    comp = BOQComparator(
        project_name=pick("project", args.project, ""),
        report_date=pick("date", args.date, ""),
        threshold=pick("threshold", args.threshold, 20.0),
        sim_threshold=pick("sim_threshold", args.sim_threshold, 0.75),
        group_re=pick("group_re", args.group_re, None),
        top_n=pick("top_n", args.top_n, 10),
    )
    comp.compare(specs, pick("output", args.output, None))


if __name__ == "__main__":
    main()
