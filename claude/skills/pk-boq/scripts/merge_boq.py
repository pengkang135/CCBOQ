"""
工程量清单（BOQ）合并工具

将 Schedule of Prices 工作簿中的分部分项工程量清单合并到单一汇总表。
- 筛选分部分项清单 sheet（排除开办费、汇总、计日工、报价说明等）
- 自动检测列布局（标准/移位），归一化到统一列结构
- 取消合并单元格，保留所有原始数据
- 删除空行、Excel错误行、汇总行（SUBTOTAL/TOTAL/% COST/DITTO 等）
- 输出平坦数据（无层级格式），仅 sheet 标题行用蓝色背景标识
- 合并完成后自动调用 pk-boq-hierarchy/apply_hierarchy.py 应用 NRM 五级层级化
"""
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
import xlsxwriter
from openpyxl.worksheet.worksheet import Worksheet


# ── 样式常量 ──────────────────────────────────────────────

FONT_NAME = "Microsoft YaHei UI"
FONT_COLOR = "#1A1A1A"
HEADER_FILL = "#1F4E79"
NUM_FORMAT = '#,##0.00'
DATA_FONT_SIZE = 9
L1_FILL = "#C6D9F1"
L1_HEIGHT = 24
DATA_HEIGHT = 16


# ── 配置 ──────────────────────────────────────────────

SKIP_SHEET_PATTERNS: list[str] = [
    "Preamble", "Cashflow", "Standby Rates", "Dayworks",
    "Grand Summary", "BoQ Grand Summary",
]

PRELIMS_PREFIXES: tuple[str, ...] = ("A_", "A0", "A.", "Prelims", "Preliminaries")

REMOVE_PATTERNS: re.Pattern = re.compile(
    r"^\s*(SUBTOTAL|TOTAL|% COST|CARRIED FORWARD|BROUGHT FORWARD|DITTO|PAGE\s*TOTAL)\b",
    re.IGNORECASE,
)

HEADER_SKIP_KEYWORDS: tuple[str, ...] = (
    "Project:", "Contract:", "Subject:", "Part II", "Item B105",
    "Schedule of Prices", "Tender No",
)

DISCLAIMER_KEYWORDS: tuple[str, ...] = (
    "Bill of Quantities is based on",
    "Employer's Requirements",
    "Tenderer's responsibility",
    "All quantities stated are to be verified",
    "The Employer will accept no liability",
    "Tenderer shall separately list",
)

EXCEL_ERRORS: frozenset[str] = frozenset({
    "#REF!", "#VALUE!", "#N/A", "#DIV/0!", "#NAME?", "#NULL!",
})

COL_ITEM = 1
COL_DESC = 2
COL_UNIT = 3
COL_QTY = 4


# ── 辅助函数 ──────────────────────────────────────────

def _unmerge_and_fill(ws: Worksheet) -> None:
    merged = list(ws.merged_cells.ranges)
    for mrange in merged:
        top_left_val = ws.cell(row=mrange.min_row, column=mrange.min_col).value
        ws.unmerge_cells(str(mrange))
        for r in range(mrange.min_row, mrange.max_row + 1):
            for c in range(mrange.min_col, mrange.max_col + 1):
                if r == mrange.min_row and c == mrange.min_col:
                    continue
                ws.cell(row=r, column=c).value = top_left_val


def _cell_str(ws: Worksheet, row: int, col: int) -> str:
    val = ws.cell(row=row, column=col).value
    return str(val).strip() if val is not None else ""


def _is_excel_error(val: str) -> bool:
    return val in EXCEL_ERRORS


def _row_all_empty(ws: Worksheet, row: int, max_col: int) -> bool:
    for c in range(1, max_col + 1):
        if _cell_str(ws, row, c):
            return False
    return True


def _is_remove_row(text: str) -> bool:
    return bool(REMOVE_PATTERNS.search(text))


def _to_number(val: str):
    if not val:
        return val
    clean = val.strip().replace(",", "").replace(" ", "")
    if not clean:
        return val
    try:
        f = float(clean)
        return int(f) if f == int(f) and "." not in clean else f
    except ValueError:
        return val


def _find_design_qty_col(ws: Worksheet, header_row: int, max_col: int) -> int:
    """返回 Design Quantity 列的 1-based 索引，若不存在则返回 0。"""
    for row in (header_row, header_row + 1):
        for c in range(1, max_col + 1):
            val = _cell_str(ws, row, c).lower()
            if "design" in val and "quantity" in val:
                return c
    return 0


def _read_headers(ws: Worksheet, header_row: int, max_col: int) -> list[str]:
    """从源表读取动态表头，处理双行表头合并。"""
    headers = []
    for c in range(1, max_col + 1):
        h1 = _cell_str(ws, header_row, c)
        h2 = _cell_str(ws, header_row + 1, c) if header_row + 1 <= (ws.max_row or 50) else ""
        if h1 and h2 and h1.lower() != h2.lower():
            headers.append(f"{h1}\n{h2}")
        elif h1:
            headers.append(h1)
        elif h2:
            headers.append(h2)
        else:
            headers.append("")
    while headers and not headers[-1]:
        headers.pop()
    return headers


# ── 主类 ──────────────────────────────────────────────

class BOQMerger:
    def __init__(self, source_path: str | Path, columns: dict | None = None):
        self.source_path = Path(source_path)
        self.wb = openpyxl.load_workbook(self.source_path, data_only=True)

        # Column mapping (1-based), overridable via --columns
        cols = columns or {}
        self.col_item = cols.get("item", COL_ITEM)
        self.col_desc = cols.get("desc", COL_DESC)
        self.col_unit = cols.get("unit", COL_UNIT)
        self.col_qty = cols.get("qty", COL_QTY)
        self.col_data_start = cols.get("data_start", 5)

    # ── Sheet 筛选 ──

    def _is_boq_sheet(self, name: str) -> bool:
        for pat in SKIP_SHEET_PATTERNS:
            if pat.lower() in name.lower():
                return False
        return True

    def _is_prelims(self, name: str) -> bool:
        for prefix in PRELIMS_PREFIXES:
            if name.lower().startswith(prefix.lower()):
                return True
        return False

    # ── 表头定位 ──

    def _find_header_row(self, ws: Worksheet, max_col: int) -> int:
        for r in range(1, min(ws.max_row or 200, 200) + 1):
            for c in range(1, max_col + 1):
                if "Item Description" in _cell_str(ws, r, c):
                    return r
        return 0

    def _find_data_start(self, ws: Worksheet, max_col: int) -> int:
        header_row = self._find_header_row(ws, max_col)
        if header_row == 0:
            return 1
        for r in range(header_row + 1, min(ws.max_row or 500, 500) + 1):
            val_a = _cell_str(ws, r, self.col_item)
            val_b = _cell_str(ws, r, self.col_desc)
            if not val_a and not val_b:
                continue
            if _is_excel_error(val_a) or _is_excel_error(val_b):
                continue
            if self._is_info_header(val_a) or self._is_info_header(val_b):
                continue
            if "Item Description" in val_a or "Item Description" in val_b:
                continue
            return r
        return header_row + 1

    def _is_info_header(self, row_text: str) -> bool:
        for kw in HEADER_SKIP_KEYWORDS:
            if kw.lower() in row_text.lower():
                return True
        return False

    def _is_disclaimer(self, val_b: str) -> bool:
        for kw in DISCLAIMER_KEYWORDS:
            if kw.lower() in val_b.lower():
                return True
        return False

    # ── 隐藏行检测 ──

    @staticmethod
    def _detect_hidden_rows(ws: Worksheet, start_row: int = 1) -> list[int]:
        """返回指定 sheet 中数据区域内隐藏行的行号列表。"""
        hidden = []
        for r in range(start_row, (ws.max_row or 1) + 1):
            if ws.row_dimensions[r].hidden:
                hidden.append(r)
        return hidden

    # ── 行分类 (仅噪声过滤，不做层级判定) ──
    # 层级化由 apply_hierarchy.py 统一处理，不在合并阶段做简化分级

    def _classify_row(
        self, ws: Worksheet, row: int, max_col: int,
        qty_col: int | None = None,
    ) -> dict:
        if qty_col is None:
            qty_col = self.col_qty
        val_a = _cell_str(ws, row, self.col_item)
        val_b = _cell_str(ws, row, self.col_desc)
        val_c = _cell_str(ws, row, self.col_unit)
        val_d = _cell_str(ws, row, qty_col)

        if not val_a and not val_b and not val_c and not val_d:
            return {"action": "remove"}

        if _is_excel_error(val_a) or _is_excel_error(val_b):
            return {"action": "remove"}

        if self._is_info_header(val_a) or self._is_info_header(val_b):
            return {"action": "remove"}

        if "Item Description" in val_a or "Item Description" in val_b:
            return {"action": "remove"}

        # SUBTOTAL/TOTAL rows are legitimate L4 data — keep them.
        # Hierarchy script R01c classifies them as L4.
        if _is_remove_row(val_a) or _is_remove_row(val_b):
            return {"action": "keep",
                    "code": val_a, "desc": val_b,
                    "unit": val_c, "quantity": val_d}

        if self._is_disclaimer(val_b):
            return {"action": "remove"}
        if not val_a and not val_c and not val_d:
            word_count = len(val_b.split())
            if word_count > 25:
                return {"action": "remove"}

        return {"action": "keep",
                "code": val_a, "desc": val_b,
                "unit": val_c, "quantity": val_d}

    # ── 主流程 ──

    def merge(self, output_path: Optional[str | Path] = None,
              keep_source_sheets: bool = False,
              delete_hidden_rows: bool = False) -> Path:
        if output_path is None:
            stem = self.source_path.stem
            output_path = self.source_path.parent / f"{datetime.now().strftime('%Y-%m-%d')}_BQMerge_{stem}.xlsx"
        else:
            output_path = Path(output_path)

        # ── Phase 1: 读取 & 分类 (openpyxl) ──
        all_sheets = self.wb.sheetnames
        boq_sheets: list[str] = []
        for name in all_sheets:
            if self._is_boq_sheet(name) and not self._is_prelims(name):
                boq_sheets.append(name)

        # 动态检测表头：遍历所有 sheet 取最大列数
        dynamic_headers: list[str] = []

        for name in boq_sheets:
            ws = self.wb[name]
            sheet_max_col = ws.max_column or 50
            header_row = self._find_header_row(ws, sheet_max_col)
            if header_row:
                hdrs = _read_headers(ws, header_row, sheet_max_col)
                if len(hdrs) > len(dynamic_headers):
                    dynamic_headers = hdrs

        if not dynamic_headers:
            dynamic_headers = ["Item", "Item Description", "Unit", "Quantity",
                               "Unit Rate\n(in USD excl. Taxes)",
                               "Labour", "Plant", "Material", "Subcontractor",
                               "Others / Consultants",
                               "Off-Site Overheads (Local & Head Office)",
                               "Local & Head Office Profit",
                               "Total Price\n(in USD excl. Taxes)"]

        global_max_col = len(dynamic_headers)
        # 统一数量列表头为 "Quantity"
        if global_max_col > 3:
            dynamic_headers[3] = "Quantity"
        all_rows: list[tuple[list, int]] = []  # (row_data, level)

        # ── Hidden Row Detection (pre-scan all BOQ sheets) ─────────
        all_hidden: dict[str, list[int]] = {}
        for sheet_name in boq_sheets:
            ws = self.wb[sheet_name]
            header_row = self._find_header_row(ws, ws.max_column or global_max_col)
            if not header_row:
                continue
            data_start = self._find_data_start(ws, ws.max_column or global_max_col)
            hidden = self._detect_hidden_rows(ws, data_start)
            if hidden:
                all_hidden[sheet_name] = hidden

        if all_hidden:
            total_hidden = sum(len(v) for v in all_hidden.values())
            print(f'\n检测到 {total_hidden} 个隐藏行，分布在 {len(all_hidden)} 个 sheet:')
            for sn, rows in all_hidden.items():
                ranges = []
                start = rows[0]; end = rows[0]
                for h in rows[1:]:
                    if h == end + 1:
                        end = h
                    else:
                        ranges.append(f'{start}-{end}' if start != end else str(start))
                        start = end = h
                ranges.append(f'{start}-{end}' if start != end else str(start))
                print(f'  [{sn}] {len(rows)} 行: {", ".join(ranges)}')

            if delete_hidden_rows:
                for sheet_name, rows in all_hidden.items():
                    ws = self.wb[sheet_name]
                    _unmerge_and_fill(ws)  # dissolve merged cells before row deletion
                    for r in sorted(rows, reverse=True):
                        ws.delete_rows(r)
                print(f'已删除 {total_hidden} 个隐藏行\n')
            else:
                print('提示: 使用 --delete-hidden-rows 参数可自动删除这些隐藏行\n')

        for sheet_name in boq_sheets:
            ws = self.wb[sheet_name]
            _unmerge_and_fill(ws)

            sheet_max_col = ws.max_column or global_max_col
            header_row = self._find_header_row(ws, sheet_max_col)

            start_row = self._find_data_start(ws, sheet_max_col)
            if start_row == 1:
                continue

            # 检测本 sheet 的数量列：优先 Design Quantity，其次默认 col_qty
            design_qty_col = 0
            if header_row:
                design_qty_col = _find_design_qty_col(ws, header_row, sheet_max_col)
            qty_col = design_qty_col if design_qty_col else self.col_qty

            title_row = [None] * global_max_col
            title_row[1] = f"【{sheet_name}】"
            all_rows.append((title_row, 1))

            for r in range(start_row, (ws.max_row or 500) + 1):
                if _row_all_empty(ws, r, sheet_max_col):
                    continue

                info = self._classify_row(ws, r, sheet_max_col, qty_col)
                if info["action"] == "remove":
                    continue

                desc = info["desc"]

                # 保留全部源列：A-D(分类用) + E 起全部数据列
                raw_row = [info["code"], desc, info["unit"], info["quantity"]]
                for c in range(self.col_data_start, sheet_max_col + 1):
                    if c == design_qty_col:
                        raw_row.append(None)
                    else:
                        val = _cell_str(ws, r, c)
                        if _is_excel_error(val):
                            val = ""
                        raw_row.append(val)

                # 补齐到统一列数
                while len(raw_row) < global_max_col:
                    raw_row.append("")

                # 数值转换（Quantity 列起，含 Tender/Design Qty、Unit Rate 等）
                for ci in range(3, len(raw_row)):
                    if raw_row[ci]:
                        raw_row[ci] = _to_number(raw_row[ci])
                    elif raw_row[ci] == "":
                        raw_row[ci] = None

                all_rows.append((raw_row, 0))

        self.wb.close()

        # ── Phase 2: 写入 (xlsxwriter) ──
        out_wb = xlsxwriter.Workbook(str(output_path), {'constant_memory': False})
        out_ws = out_wb.add_worksheet("MergeSheet")

        l1_fmt = out_wb.add_format({
            'font_name': FONT_NAME,
            'font_color': FONT_COLOR,
            'bold': True,
            'font_size': 10,
            'bg_color': L1_FILL,
            'valign': 'vcenter',
        })
        data_fmt = out_wb.add_format({
            'font_name': FONT_NAME,
            'font_color': FONT_COLOR,
            'font_size': DATA_FONT_SIZE,
            'valign': 'vcenter',
        })
        data_num_fmt = out_wb.add_format({
            'font_name': FONT_NAME,
            'font_color': FONT_COLOR,
            'font_size': DATA_FONT_SIZE,
            'valign': 'vcenter',
            'num_format': NUM_FORMAT,
        })
        header_fmt = out_wb.add_format({
            'font_name': FONT_NAME,
            'bold': True,
            'font_color': '#FFFFFF',
            'bg_color': HEADER_FILL,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'font_size': 10,
        })

        used_cols = global_max_col

        # 写表头（动态）
        out_ws.set_row(0, 32, header_fmt)
        for ci in range(used_cols):
            hdr = dynamic_headers[ci] if ci < len(dynamic_headers) else ""
            out_ws.write(0, ci, hdr, header_fmt)

        # 写数据行：L1 sheet 标题行用蓝色背景，其余统一平坦格式
        for i, (row_data, level) in enumerate(all_rows):
            xl_row = i + 2
            is_l1 = (level == 1)
            out_ws.set_row(xl_row, L1_HEIGHT if is_l1 else DATA_HEIGHT)
            for ci, val in enumerate(row_data):
                if ci >= used_cols:
                    break
                if is_l1:
                    fmt = l1_fmt
                elif ci >= 3:
                    fmt = data_num_fmt
                else:
                    fmt = data_fmt
                if val is not None:
                    out_ws.write(xl_row, ci, val, fmt)

        # 列宽
        col_widths = {0: 18, 1: 60, 2: 8}
        for c in range(3, used_cols):
            col_widths[c] = 14
        for c, w in col_widths.items():
            out_ws.set_column(c, c, w)

        # 冻结 + 筛选
        out_ws.freeze_panes(1, 0)
        out_ws.autofilter(0, 0, len(all_rows) + 1, used_cols - 1)

        # 源分表（纯数据，无格式）
        if keep_source_sheets:
            for name in boq_sheets:
                src_ws = self.wb[name] if name in self.wb.sheetnames else None
                if src_ws is None:
                    tmp_wb = openpyxl.load_workbook(self.source_path, data_only=True)
                    src_ws = tmp_wb[name]
                else:
                    tmp_wb = None

                safe_name = name[:31]
                dst_ws = out_wb.add_worksheet(safe_name)
                _unmerge_and_fill(src_ws)
                for r in range(1, (src_ws.max_row or 100) + 1):
                    for c in range(0, (src_ws.max_column or 20)):
                        val = src_ws.cell(row=r, column=c + 1).value
                        if val is not None:
                            dst_ws.write(r - 1, c, val)

                if tmp_wb:
                    tmp_wb.close()

        out_wb.close()
        return output_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="合并工程量清单 (BOQ)")
    parser.add_argument("source", help="源 Excel 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出文件路径")
    parser.add_argument("--keep-source-sheets", action="store_true",
                        help="在输出中保留原始分表（默认不保留）")
    parser.add_argument("--columns", default=None,
                        help='列映射 JSON，例如: \'{"item":1,"desc":2,"unit":3,"qty":4,"data_start":5}\'')
    parser.add_argument("--delete-hidden-rows", action="store_true",
                        help="删除源 sheet 中的隐藏行后再合并")
    args = parser.parse_args()

    columns_config = None
    if args.columns:
        import json as _json
        columns_config = _json.loads(args.columns)

    merger = BOQMerger(args.source, columns=columns_config)
    out = merger.merge(
        output_path=args.output,
        keep_source_sheets=args.keep_source_sheets,
        delete_hidden_rows=args.delete_hidden_rows,
    )
    print(f"Merged → {out}")

    hierarchy_script = (
        Path(__file__).resolve().parent.parent.parent
        / "pk-boq-hierarchy" / "scripts" / "apply_hierarchy.py"
    )
    if hierarchy_script.exists():
        print("Applying NRM 5-level hierarchy (pk-boq-hierarchy)...")
        subprocess.run(
            [sys.executable, str(hierarchy_script), str(out)],
            check=False,
        )
    else:
        print(f"Warning: hierarchy script not found at {hierarchy_script}")


if __name__ == "__main__":
    main()
