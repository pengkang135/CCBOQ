"""CombineBQ 的行列布局 — 所有下游脚本共用一份，别再各自硬编码列号。

列位靠表头名找，不靠列号：模板改过好几版，硬编码列号每次都要跟着改，
漏改一处就是整批错位写回。

本文件是权威版。pk-boq-classify/scripts/layout.py 是迁移期副本，那边的
分类脚本还要写回工作台的 ai 列所以暂时需要它；改这里要同步改那边。
分类改成产出 classification.json、不再碰 Excel 之后，那份副本即可删除。
"""

SHEET = "CombineBQ"
HEADER_ROW = 3
FACTOR_ROW = 2
DATA_START = 4

AI_COLS = ["Discipline", "SortKey", "Category", "Subcategory", "Element"]
SRC_COLS = ["No.", "Description", "Unit", "Qty"]
KEY_COLS = ["Main Key", "BQ KEY", "CleanDescription"]
ANCHOR = "Description"
RATE_COLS = ["Norm Rate", "Norm Amount", "Ref Rate", "Ref Amount"]

# r1 的分组锚点。EXPORT / COST / SUBCONTRACTOR 三组里 Labor / Material /
# Equipment / Rate / Amount 全重名，只有配上组名才唯一。
GROUPS = ["EXPORT", "COST", "AI", "SUBCONTRACTOR"]

# 模板这一版把 Quantity 改名成 Qty，实际清单两种写法都有。不认别名的话：插列时
# 模板公式里的 Qty 列引用会留着模板列字母、静默指错列；交付检查会误报缺列。
ALIASES = {"Qty": ("Qty", "Quantity")}


def resolve(cols, name):
    """按别名在 cols（列名 -> 列号/列字母）里找 name，找不到返回 None。"""
    for alias in ALIASES.get(name, (name,)):
        if alias in cols:
            return cols[alias]
    return None


def find_columns(ws, header_row=HEADER_ROW):
    """表头名 -> 列号。同名列取最左的那个（原表里 Unit / Rate 常有重名）。"""
    cols = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        if v is None:
            continue
        name = str(v).strip().replace("\n", " ")
        name = " ".join(name.split())
        if name and name not in cols:
            cols[name] = c
    return cols


def require(cols, names):
    missing = [n for n in names if n not in cols]
    if missing:
        raise RuntimeError(
            f"{SHEET} 第 {HEADER_ROW} 行未找到列: {missing}。"
            f"现有表头: {sorted(cols)}")
    return {n: cols[n] for n in names}


def get_sheet(wb, name=None):
    """定位数据页。没指定名字就认表头锚点，不假定叫模板那个名。

    产物的数据页保留源清单自己的 sheet 名（装配是在源清单上插列，不是套模板
    重建），写死模板名只在源清单恰好同名时才对。
    """
    if name:
        if name in wb.sheetnames:
            return wb[name]
        raise RuntimeError(f"工作簿无 sheet {name!r}，现有: {wb.sheetnames}")

    for ws in wb.worksheets:
        if ANCHOR in find_columns(ws, HEADER_ROW):
            return ws
    if SHEET in wb.sheetnames:
        return wb[SHEET]
    raise RuntimeError(f"没有 sheet 的第 {HEADER_ROW} 行含 {ANCHOR!r}，"
                       f"现有: {wb.sheetnames}")


def row_kind(desc):
    d = (desc or "").strip()
    if d.startswith("【"):
        return "l1"
    if d.startswith("《"):
        return "l2"
    if d.startswith("{"):
        return "l3"
    return "item"


def strip_marks(desc):
    d = (desc or "").strip()
    for a, b in (("【", "】"), ("《", "》"), ("{", "}")):
        if d.startswith(a):
            return d.lstrip(a).rstrip(b).strip()
    return d
