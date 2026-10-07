#!/usr/bin/env python
"""NRM 五级 BOQ 层级化脚本。

Usage:
    python apply_hierarchy.py <input.xlsx> [--sheet SheetName]
        [--code-col B] [--desc-col C] [--qty-col D] [--unit-col E]

Output: <input> (in-place overwrite)
"""

import openpyxl, sys, io, re, os, argparse, json
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'pk-boq', 'scripts'))
from openpyxl_utils import clean_save


def col_letter_to_num(letter):
    return openpyxl.utils.column_index_from_string(letter.upper())


def parse_args():
    p = argparse.ArgumentParser(description='NRM 五级 BOQ 层级化')
    p.add_argument('input', help='输入 xlsx 文件路径')
    p.add_argument('--sheet', default=None, help='工作表名（默认第一个）')
    p.add_argument('--code-col', default='B', help='编号列字母 (default: B)')
    p.add_argument('--desc-col', default='C', help='描述列字母 (default: C)')
    p.add_argument('--qty-col', default='D', help='数量列字母 (default: D)')
    p.add_argument('--unit-col', default='E', help='单位列字母 (default: E)')
    p.add_argument('--label-col', default='U', help='层级标签列字母 (default: U)')
    p.add_argument('--export-review', action='store_true',
                   help='Export ambiguous Phase 2 rows as JSON for dual-model LLM review')
    p.add_argument('--review-file', default=None,
                   help='Review JSON output path (default: <input>_review.json)')
    p.add_argument('--force', action='store_true',
                   help='Bypass AI team pipeline requirement (>50 L4 items)')
    # ── v3 topology parameters ──────────────────────────────────────
    p.add_argument('--extract-skeleton', action='store_true',
                   help='Extract structure skeleton only (non-L4 rows + context) → skeleton.json; no classification')
    p.add_argument('--skeleton-file', default=None,
                   help='Skeleton JSON output path (default: <input>_skeleton.json)')
    p.add_argument('--rules', default=None,
                   help='Rules JSON file for batch classification (v3 Step 3); skips Phase 1-3 logic')
    p.add_argument('--unmatched-file', default=None,
                   help='Unmatched rows JSON output path (default: <input>_unmatched.json)')
    p.add_argument('--assignments', default=None,
                   help='Direct row-level assignments JSON from Step 2 Agent (v3); overrides rule matches')
    p.add_argument('--output', default=None,
                   help='Output xlsx path (default: overwrite input, no suffix)')
    p.add_argument('--delete-hidden-rows', action='store_true',
                   help='Delete hidden rows from the sheet before processing')
    return p.parse_args()


# ── NRM 5-Level Constants ──────────────────────────────────────────
L1, L2, L3, NOTE, L4 = 1, 2, 3, 5, 4

# Styles
sec_font = Font(name='Microsoft YaHei UI', size=11, bold=True, color='FF1A1A1A')
sec_fill = PatternFill(start_color='FFC6D9F1', end_color='FFC6D9F1', fill_type='solid')
cls_font = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FF1A1A1A')
cls_fill = PatternFill(start_color='FFEEF2FA', end_color='FFEEF2FA', fill_type='solid')
sub3_font = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FF1A1A1A')
sub3_fill = PatternFill(start_color='FFFBE5D6', end_color='FFFBE5D6', fill_type='solid')
note_font = Font(name='Microsoft YaHei UI', size=9, bold=True, color='FF1A1A1A')
note_fill = PatternFill()
item_font = Font(name='Microsoft YaHei UI', size=9, bold=False, color='FF1A1A1A')
BRACKETS = {L1: ('【', '】'), L2: ('《', '》'), L3: ('{', '}'), NOTE: ('', ''), L4: ('', '')}
FONTS    = {L1: sec_font, L2: cls_font, L3: sub3_font, NOTE: note_font, L4: item_font}
FILLS    = {L1: sec_fill, L2: cls_fill, L3: sub3_fill, NOTE: note_fill, L4: PatternFill()}
HEIGHTS  = {L1: 16.5, L2: 14.5, L3: 14.5, NOTE: 14.5, L4: 14.5}
OUTLINES = {L1: 0, L2: 1, L3: 2, NOTE: 3, L4: 3}
LABELS   = {L1: 'L1-一级', L2: 'L2-二级', L3: 'L3-三级', NOTE: 'Note-注释', L4: 'L4-条目'}


def is_empty(val):
    return val is None or str(val).strip() in ('', 'None', 'nan')


# 说明性措辞：命中即判定该行是说明文字（Note），不是标题
HEADING_NEG_PAT = re.compile(
    r'\b(shall|includ\w*|refer\w*|measured|in\s+accordance|accordance|'
    r'allowance|allow(ed|ing)?\s+for|allow\s+for|deemed|provided|'
    r'compl(y|ies|ying)|unless|as\s+(described|specified|shown|per|detailed)|'
    r'according\s+to|rate[s]?\s+(shall|include\w*|are|to\b)|note[:\s])',
    re.IGNORECASE)


def has_chinese(desc):
    """检测是否包含中文内容（用于识别双语行 → 语义歧义）"""
    return bool(re.search(r'[一-鿿]', desc))

def looks_like_heading(desc):
    """保守判定：仅当描述明显像标题时返回 True。
    偏向判为说明——BOQ 中说明文字远多于中间层标题，且说明被误标题化
    会污染 classify 的 Dept 追溯，代价高于真标题偶尔降 Note。"""
    s = desc.strip()
    if not s:
        return False
    if HEADING_NEG_PAT.search(s):        # 说明性措辞 → 说明
        return False
    if re.search(r'[.。;；]\s*$', s):      # 句末标点(完整句子) → 说明
        return False
    if len(s) > 60:                       # 标题通常简短
        return False
    if len(re.findall(r'\S+', s)) > 10:   # 词数过多 → 说明
        return False
    # 含中文 → 可能是设计院注释/翻译/过渡说明，脚本无力判断语义，
    # 标记为歧义交 LLM 审查；此处保守返回 False 避免误升标题
    if has_chinese(s):
        return False
    return True


def _validate_output(out_path, src_path, ws, col_desc, col_unit, col_qty, min_row, max_row):
    """验证输出：行数一致性、L4条目完整性、随机抽检。"""
    import random
    print(f'\n── 输出验证 ──')

    wb_out = openpyxl.load_workbook(out_path)
    ws_out = wb_out[ws.title] if ws.title in wb_out.sheetnames else wb_out[wb_out.sheetnames[0]]

    # 1. 行数校验
    src_rows = max_row - min_row + 1
    out_rows = ws_out.max_row - 1  # exclude header
    status = 'PASS' if out_rows == src_rows else 'FAIL'
    print(f'  行数校验: 输入 {src_rows} → 输出 {out_rows} [{status}]')

    # 2. L4条目数校验
    src_l4 = sum(1 for r in range(min_row, max_row + 1)
                 if not is_empty(ws.cell(row=r, column=col_unit).value)
                 and not is_empty(ws.cell(row=r, column=col_qty).value))
    out_l4 = sum(1 for r in range(2, ws_out.max_row + 1)
                 if not is_empty(ws_out.cell(row=r, column=col_unit).value)
                 and not is_empty(ws_out.cell(row=r, column=col_qty).value))
    l4_status = 'PASS' if out_l4 == src_l4 else 'FAIL'
    print(f'  L4条目数: 输入 {src_l4} → 输出 {out_l4} [{l4_status}]')

    # 3. 随机抽检 5 行
    sample_rows = sorted(random.sample(range(min_row, max_row + 1), min(5, src_rows)))
    print(f'  抽检行: {sample_rows}')
    for r in sample_rows:
        src_desc = str(ws.cell(row=r, column=col_desc).value or '')[:80]
        out_desc = str(ws_out.cell(row=r, column=col_desc).value or '')[:80]
        match = 'OK' if src_desc in out_desc or out_desc in src_desc else 'MISMATCH'
        print(f'    Row {r}: [{match}] src=[{src_desc}]')
        if match == 'MISMATCH':
            print(f'           out=[{out_desc}]')

    # 4. 空描述检查（不应有空 desc 的数据行）
    empty_in_output = 0
    for r in range(2, ws_out.max_row + 1):
        u = ws_out.cell(row=r, column=col_unit).value
        q = ws_out.cell(row=r, column=col_qty).value
        d = ws_out.cell(row=r, column=col_desc).value
        if (not is_empty(u) and not is_empty(q)) and is_empty(d):
            empty_in_output += 1
    if empty_in_output:
        print(f'  警告: {empty_in_output} 行有 unit+qty 但描述为空')
    else:
        print(f'  空描述检查: PASS')

    print(f'── 验证完成 ──\n')
    wb_out.close()


def main():
    args = parse_args()
    COL_CODE = col_letter_to_num(args.code_col)
    COL_DESC = col_letter_to_num(args.desc_col)
    COL_QTY  = col_letter_to_num(args.qty_col)
    COL_UNIT = col_letter_to_num(args.unit_col)
    COL_LABEL = col_letter_to_num(args.label_col)

    wb = openpyxl.load_workbook(args.input)
    ws = wb[args.sheet] if args.sheet else wb[wb.sheetnames[0]]
    min_row, max_row = ws.min_row + 1, ws.max_row

    # Auto-detect first data row: find first L1【】marker to skip header rows
    for _r in range(ws.min_row, min(ws.max_row + 1, ws.min_row + 20)):
        _v = ws.cell(row=_r, column=COL_DESC).value
        if _v and '【' in str(_v):
            min_row = _r
            break

    # ── Hidden Row Detection ──────────────────────────────────────────
    hidden_rows = []
    for _r in range(min_row, max_row + 1):
        if ws.row_dimensions[_r].hidden:
            hidden_rows.append(_r)

    if hidden_rows:
        # Build contiguous ranges for compact display
        ranges = []
        start = hidden_rows[0]
        end = hidden_rows[0]
        for h in hidden_rows[1:]:
            if h == end + 1:
                end = h
            else:
                ranges.append((start, end))
                start = end = h
        ranges.append((start, end))
        range_str = ', '.join(f'{s}-{t}' if s != t else str(s) for s, t in ranges)
        print(f'检测到 {len(hidden_rows)} 个隐藏行: {range_str}')

        if args.delete_hidden_rows:
            for _r in hidden_rows:
                ws.delete_rows(_r)
            # Recalculate max_row after deletion
            max_row = ws.max_row
            print(f'已删除 {len(hidden_rows)} 个隐藏行，剩余 {max_row - min_row + 1} 行')
        else:
            print(f'提示: 使用 --delete-hidden-rows 参数可自动删除这些隐藏行')
            print(f'      或手动在 Excel 中取消隐藏后重新运行')

    # ── AI Team Pipeline Enforcement ────────────────────────────────
    # Count L4 items (has unit + qty)
    l4_count = 0
    for _r in range(min_row, max_row + 1):
        _u = ws.cell(row=_r, column=COL_UNIT).value
        _q = ws.cell(row=_r, column=COL_QTY).value
        if (not is_empty(_u) and not is_empty(_q)):
            l4_count += 1

    # 分级以规则为主，不因行数硬退出（避免"脚本推给 ai-team、ai-team 又说这是规则活"的死结）。
    # 大表仅提示：歧义行可加 --export-review 导出后走 pk-boq-ai-team 复核。
    if l4_count > 50:
        print(f"NOTE: {l4_count} L4 items (>50). 分级按规则继续执行；")
        print(f"      如需对歧义行做 LLM 复核，加 --export-review 导出后交 pk-boq-ai-team。")

    print(f'L4 item count: {l4_count}')

    # ── Pre-process: 清除旧的 L2/L3 分级符号，保留 L1【】 ──────────────
    # 《》{} 是本技能上一轮自己加的，不是原始清单数据。旧判定可能有错，
    # 若信任它们（"括号权威"）会把上轮错误继承固化、永远洗不掉。分级前一律
    # strip 掉所有行的《》{}，基于干净描述重判。L1【】由 merge 阶段按含清单项
    # 的 sheet 数机械生成（确定，非语义猜测），保留；仅 pagination 行额外清
    # 【】（它不该是标题）。
    pagination_pat = r"\(cont'?d\)|sub\s*total|carried\s+forward|brought\s+forward"
    stripped_count = 0
    for _r in range(min_row, max_row + 1):
        _cell = ws.cell(row=_r, column=COL_DESC)
        _v = _cell.value
        if not _v:
            continue
        _orig = str(_v)
        _clean = _orig.replace('《', '').replace('》', '')
        _clean = re.sub(r'\{([^}]*)\}', r'\1', _clean).replace('{', '').replace('}', '')
        if re.search(pagination_pat, _orig, re.IGNORECASE):
            _clean = _clean.replace('【', '').replace('】', '')
        if _clean != _orig:
            _cell.value = _clean
            stripped_count += 1
    if stripped_count:
        print(f'Pre-process: 清除 {stripped_count} 行的旧 L2/L3 符号（《》{{}}），保留 L1【】')

    # ── v3 Step 1: Extract Skeleton (early exit) ────────────────────
    if args.extract_skeleton:
        skeleton_rows = []
        # Determine L1 boundaries (rows with 【 in desc)
        l1_rows = []
        for _r in range(min_row, max_row + 1):
            _d = str(ws.cell(row=_r, column=COL_DESC).value or '')
            if '【' in _d:
                l1_rows.append(_r)

        def _nearest_l1(r):
            best = None
            for l1r in l1_rows:
                if l1r <= r:
                    best = l1r
            return best

        for r in range(min_row, max_row + 1):
            u = ws.cell(row=r, column=COL_UNIT).value
            q = ws.cell(row=r, column=COL_QTY).value
            if (not is_empty(u) and not is_empty(q)):
                continue  # skip L4 data rows

            desc = str(ws.cell(row=r, column=COL_DESC).value or '').strip()
            if not desc:
                continue

            l1_r = _nearest_l1(r)
            sheet_ctx = ''
            if l1_r is not None:
                sheet_ctx = str(ws.cell(row=l1_r, column=COL_DESC).value or '').strip()

            prev_2, next_2 = [], []
            for rr in range(max(min_row, r - 2), r):
                pd = str(ws.cell(row=rr, column=COL_DESC).value or '').strip()
                if pd:
                    prev_2.append({'xl_row': rr, 'desc': pd})
            for rr in range(r + 1, min(max_row + 1, r + 3)):
                nd = str(ws.cell(row=rr, column=COL_DESC).value or '').strip()
                if nd:
                    next_2.append({'xl_row': rr, 'desc': nd})

            skeleton_rows.append({
                'xl_row': r,
                'desc': desc,
                'code': str(ws.cell(row=r, column=COL_CODE).value or '').strip(),
                'unit': str(u or '').strip(),
                'qty': str(q or '').strip(),
                'sheet_context': sheet_ctx,
                'prev_2': prev_2,
                'next_2': next_2,
            })

        skeleton = {
            'source': os.path.basename(args.input),
            'sheet': args.sheet or wb.sheetnames[0],
            'total_rows': max_row - min_row + 1,
            'skeleton_count': len(skeleton_rows),
            'l1_boundaries': [{'xl_row': lr, 'desc': str(ws.cell(row=lr, column=COL_DESC).value or '')}
                              for lr in l1_rows],
            'rows': skeleton_rows,
        }
        skel_path = args.skeleton_file or args.input.replace('.xlsx', '_skeleton.json')
        with open(skel_path, 'w', encoding='utf-8') as f:
            json.dump(skeleton, f, ensure_ascii=False, indent=2)
        print(f'Skeleton extracted: {len(skeleton_rows)} non-L4 rows → {skel_path}')
        wb.close()
        return

    def get_val(row, col):
        return ws.cell(row=row, column=col).value

    def desc_has(row, marker):
        v = get_val(row, COL_DESC)
        return marker in str(v or '')

    def desc_starts(row, marker):
        v = get_val(row, COL_DESC)
        return str(v or '').strip().startswith(marker)

    def has_unit_qty(row):
        u = get_val(row, COL_UNIT)
        q = get_val(row, COL_QTY)
        return (not is_empty(u) and not is_empty(q))

    def get_desc_str(row):
        d = get_val(row, COL_DESC)
        return str(d).strip() if d else ''

    def get_code_str(row):
        c = get_val(row, COL_CODE)
        return str(c).strip() if c else ''

    # ── v3 Step 3: Rules-based classification (replaces Phase 1-2) ──
    if args.rules:
        with open(args.rules, 'r', encoding='utf-8') as f:
            rules_data = json.load(f)
        rules_list = rules_data.get('rules', rules_data)

        level_map = {}
        reason_map = {}
        unmatched = []

        def _match_rule(row_idx, desc, code):
            for rule in rules_list:
                ptype = rule.get('pattern_type', '')
                pspec = rule.get('pattern_spec', '')
                if ptype == 'desc_exact' and desc == pspec:
                    return rule
                if ptype == 'desc_regex' and re.search(pspec, desc):
                    return rule
                if ptype == 'desc_contains' and pspec.lower() in desc.lower():
                    return rule
                if ptype == 'desc_starts' and desc.startswith(pspec):
                    return rule
                if ptype == 'all_caps_no_number':
                    if desc == desc.upper() and not re.search(r'\d', desc) and len(desc.split()) >= 1:
                        if not pspec:
                            return rule
                        keywords = [kw.strip().upper() for kw in pspec.split(',')]
                        desc_upper = desc.upper()
                        if any(kw in desc_upper for kw in keywords):
                            return rule
                if ptype == 'code_regex' and re.search(pspec, code):
                    return rule
                if ptype == 'has_unit_qty' and has_unit_qty(row_idx):
                    return rule
                if ptype == 'pagination' and re.search(
                        r"\(cont'?d\)|sub\s*total|carried\s+forward|brought\s+forward",
                        desc, re.IGNORECASE):
                    return rule
                if ptype == 'desc_empty' and not desc:
                    return rule
            return None

        LEVEL_MAP_NAME = {'L1': L1, 'L2': L2, 'L3': L3, 'Note': NOTE, 'L4': L4}

        for r in range(min_row, max_row + 1):
            desc = get_desc_str(r)
            code = get_code_str(r)
            rule = _match_rule(r, desc, code)

            if rule:
                lv_name = rule.get('level', 'Note')
                lv = LEVEL_MAP_NAME.get(lv_name, NOTE)
                level_map[r] = (lv, desc)
                reason_map[r] = f"rule:{rule.get('id','?')}:{rule.get('reason','')}"
            else:
                # Default: use has_unit_qty as fallback → L4, else Note
                if has_unit_qty(r):
                    level_map[r] = (L4, desc)
                    reason_map[r] = 'unmatched_forced_L4'
                else:
                    level_map[r] = (NOTE, desc)
                    reason_map[r] = 'unmatched_default_note'
                unmatched.append({
                    'xl_row': r,
                    'desc': desc,
                    'code': code,
                    'unit': str(get_val(r, COL_UNIT) or ''),
                    'qty': str(get_val(r, COL_QTY) or ''),
                })

        # Export unmatched rows
        unmatched_path = args.unmatched_file or args.input.replace('.xlsx', '_unmatched.json')
        with open(unmatched_path, 'w', encoding='utf-8') as f:
            json.dump({
                'source': os.path.basename(args.input),
                'total_rows': len(level_map),
                'unmatched_count': len(unmatched),
                'unmatched_rows': unmatched,
            }, f, ensure_ascii=False, indent=2)
        print(f'Rules applied: {len(level_map)} rows, {len(unmatched)} unmatched → {unmatched_path}')

        # ── Overlay direct row-level assignments from Step 2 Agent ─────
        if args.assignments:
            with open(args.assignments, 'r', encoding='utf-8') as f:
                assignments_data = json.load(f)
            assignments_list = assignments_data.get('assignments', assignments_data)
            overrides = 0
            for a in assignments_list:
                xl_row = a['xl_row']
                lv_name = a['level']
                lv = LEVEL_MAP_NAME.get(lv_name, NOTE)
                if xl_row in level_map:
                    old_lv, desc = level_map[xl_row]
                    if old_lv != lv:
                        level_map[xl_row] = (lv, desc)
                        reason_map[xl_row] = f"assignment:{a.get('reason','')}"
                        overrides += 1
                else:
                    desc = get_desc_str(xl_row)
                    level_map[xl_row] = (lv, desc)
                    reason_map[xl_row] = f"assignment:{a.get('reason','')}"
                    overrides += 1
            print(f'Assignments applied: {len(assignments_list)} rows, {overrides} overrides')

        # Apply formatting only — Seq col and layout preserved from merge output
        stats = {L1: 0, L2: 0, L3: 0, NOTE: 0, L4: 0}

        for r in sorted(level_map.keys()):
            lv, desc = level_map[r]
            l_open, l_close = BRACKETS[lv]

            if lv in (L1, L2, L3) and desc:
                already = desc.startswith('【') or desc.startswith('《') or desc.startswith('{')
                if not already:
                    ws.cell(row=r, column=COL_DESC).value = f'{l_open}{desc}{l_close}'

            for col in range(1, ws.max_column + 1):
                cell = ws.cell(row=r, column=col)
                cell.font = FONTS[lv]
                if lv in (L1, L2, L3):
                    cell.fill = FILLS[lv]

            ws.row_dimensions[r].height = HEIGHTS[lv]
            ws.row_dimensions[r].outline_level = OUTLINES[lv]
            stats[lv] += 1

        ws.column_dimensions[get_column_letter(COL_DESC)].width = 55

        # ── Re-apply header formatting ──────────────────────────────
        # openpyxl save corrupts xlsxwriter formatting on merged header cells.
        # Explicitly set header rows (before first L1 marker) to white-on-dark-blue
        # so clean_save writes correct styles regardless of merge state.
        header_font = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FFFFFFFF')
        header_fill = PatternFill(start_color='FF1F4E79', end_color='FF1F4E79', fill_type='solid')
        for _r in range(ws.min_row, min_row):
            for _c in range(1, ws.max_column + 1):
                _cell = ws.cell(row=_r, column=_c)
                _cell.font = header_font
                _cell.fill = header_fill
            ws.row_dimensions[_r].height = 28

        out_path = args.output or args.input
        clean_save(wb, out_path)

        # ── Validation ──────────────────────────────────────────────
        _validate_output(out_path, args.input, ws, COL_DESC, COL_UNIT, COL_QTY, min_row, max_row)

        print(f'\n层级统计 (NRM 五级 - rules-based):')
        for lv, name in [(L1, 'L1【】'), (L2, 'L2《》'), (L3, 'L3{}'), (NOTE, 'Note '), (L4, 'L4条目')]:
            print(f'  {name}: {stats[lv]} rows')
        print(f'Source: {args.input}')
        print(f'Output: {out_path}')
        wb.close()
        return

    # ── Phase 1: Initial Classification ────────────────────────────
    level_map = {}
    reason_map = {}  # row -> reason string for export-review
    for r in range(min_row, max_row + 1):
        desc = get_desc_str(r)
        code = get_code_str(r)

        if not desc:
            level_map[r] = (L4, desc)
            reason_map[r] = 'empty_desc'
            continue

        if has_unit_qty(r):
            level_map[r] = (L4, desc)
            reason_map[r] = 'has_unit_qty'
            continue

        # Pagination / subtotal — force Note regardless of brackets
        if re.search(r"\(cont'?d\)|sub\s*total|carried\s+forward|brought\s+forward",
                     desc, re.IGNORECASE):
            level_map[r] = (NOTE, desc)
            reason_map[r] = 'pagination'
            continue

        # Known NRM boilerplate — never a section header
        if re.search(r'preamble\s+notes|following\s+apply',
                     desc, re.IGNORECASE):
            level_map[r] = (NOTE, desc)
            reason_map[r] = 'blacklist_preamble'
            continue

        # L1 section number: "1 - Description" / "1 — Description"
        # 破折号后必须是字母/中文（排除 "3 - 5 days"、"1 - 2 coats" 等区间说明）
        if re.match(r'^\d+\s*[-–—]\s*[A-Za-z一-鿿]', desc):
            level_map[r] = (L1, desc)
            reason_map[r] = 'section_number_L1'
            continue

        # 【】保留为 L1（merge 阶段按含清单项的 sheet 数生成，确定）。
        # 注意：原「《→L2、{→L3」括号权威已删除——括号是本技能自加的、会
        # 继承上一轮的旧错。L2/L3 一律靠 Phase 2 结构（有无 L4 子项）重判。
        if desc_has(r, '【'):
            level_map[r] = (L1, desc)
            reason_map[r] = 'bracket_L1'
            continue

        if re.match(r'^\d+\.0$', code):
            level_map[r] = (L2, desc)
            reason_map[r] = 'code_X.0'
            continue

        # Section/sub-section codes: "A.1", "B.2.3", "G.13.4" — structural headers
        # Trust the code pattern over Chinese semantics; Phase 2 confirms via children
        if re.match(r'^[A-Z]\.\d+', code):
            level_map[r] = (L3, desc)
            reason_map[r] = 'code_section_L3_candidate'
            continue

        # Clause references: "X.XX Description" without unit/qty → Note
        if re.match(r'^\d+\.\d+\s+\w', desc):
            level_map[r] = (NOTE, desc)
            reason_map[r] = 'clause_reference'
            continue

        # 兜底：默认按说明文字(Note)处理，而非默认标题。
        # 仅当描述具备标题特征时才作为 L3 候选，交 Phase 2 做结构校验。
        # 这样"说明文字坐落在 L4 清单项上方"不再被 Phase 2 误确认成 L3 标题。
        if has_chinese(desc):
            # 含中文 → 可能是设计院注释/翻译。脚本无力判断语义，
            # 暂归 Note，导出给 LLM 审查是否为真标题
            level_map[r] = (NOTE, desc)
            reason_map[r] = 'cn_semantic_deferred'
        elif looks_like_heading(desc):
            level_map[r] = (L3, desc)  # candidate, Phase 2 decides
            reason_map[r] = 'L3_candidate'
        else:
            level_map[r] = (NOTE, desc)
            reason_map[r] = 'default_note_non_heading'

    print(f'Phase 1: classified {len(level_map)} rows')

    # ── Phase 2: Has-Children Check ────────────────────────────────
    # Boundaries: only L1/L2 stop upward search. L3 brackets are NOT
    # boundaries — a row with L3 children below it should be promoted to L2.
    boundaries = set()
    for r, (lv, _) in level_map.items():
        if lv in (L1, L2):
            boundaries.add(r)

    l2_promoted = 0   # promoted L3 candidate → L2 (has L3 children)
    l3_confirmed = 0  # confirmed L3 (has direct L4 children)
    demoted = 0       # demoted L3 candidate → Note (no children)
    for r in sorted(level_map.keys()):
        lv, desc = level_map[r]
        if lv != L3:
            continue
        if desc_starts(r, '{'):
            continue  # pre-existing bracket, authoritative

        first_hit = None  # None, 'L3', 'L4', 'boundary'
        for r2 in range(r + 1, max_row + 1):
            if r2 in boundaries:
                first_hit = 'boundary'
                break
            d2 = get_desc_str(r2)
            if d2.startswith('《') or '【' in d2:
                first_hit = 'boundary'
                break
            if r2 in level_map:
                lv2, _ = level_map[r2]
                if lv2 == L3 and desc_starts(r2, '{'):
                    first_hit = 'L3'
                    break
                if lv2 == L4:
                    first_hit = 'L4'
                    break

        if first_hit == 'L3':
            level_map[r] = (L2, desc)
            boundaries.add(r)
            reason_map[r] = 'promoted_L3→L2_has_L3_children'
            l2_promoted += 1
        elif first_hit == 'L4':
            reason_map[r] = 'confirmed_L3_has_L4_children'
            l3_confirmed += 1
        else:
            level_map[r] = (NOTE, desc)
            reason_map[r] = 'demoted_L3→Note_no_children'
            demoted += 1

    print(f'Phase 2: {l2_promoted} promoted L3→L2, {l3_confirmed} confirmed L3, {demoted} demoted→Note')

    # ── Phase 2b: L2 promotion for L3 rows whose first child is L3 ──
    # After Phase 2 confirms all L3s, re-scan: if an L3 row's first non-Note
    # child is a confirmed L3 (not L4), it should be L2 (groups sub-sections).
    l2b_promoted = 0
    for r in sorted(level_map.keys()):
        lv, desc = level_map[r]
        if lv != L3:
            continue
        first_l3_child = None
        first_l4_child = None
        for r2 in range(r + 1, max_row + 1):
            if r2 in boundaries:
                break
            d2 = get_desc_str(r2)
            if '【' in d2:
                break
            if r2 in level_map:
                lv2, _ = level_map[r2]
                if lv2 == L3:
                    first_l3_child = r2
                    break
                if lv2 == L4:
                    first_l4_child = r2
                    break
        if first_l3_child is not None and first_l4_child is None:
            level_map[r] = (L2, desc)
            boundaries.add(r)
            reason_map[r] = 'promoted_L3→L2_Phase2b_child_is_L3'
            l2b_promoted += 1
            l3_confirmed -= 1

    if l2b_promoted:
        print(f'Phase 2b: {l2b_promoted} more promoted L3→L2 (first child is L3, not L4)')

    # ── Phase 3: Apply Formatting ──────────────────────────────────
    # Apply formatting only — Seq col and layout preserved from merge output
    stats = {L1: 0, L2: 0, L3: 0, NOTE: 0, L4: 0}

    for r in sorted(level_map.keys()):
        lv, desc = level_map[r]
        l_open, l_close = BRACKETS[lv]

        if lv in (L1, L2, L3) and desc:
            already = desc.startswith('【') or desc.startswith('《') or desc.startswith('{')
            if not already:
                ws.cell(row=r, column=COL_DESC).value = f'{l_open}{desc}{l_close}'

        for col in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=col)
            cell.font = FONTS[lv]
            if lv in (L1, L2, L3):
                cell.fill = FILLS[lv]

        ws.row_dimensions[r].height = HEIGHTS[lv]
        ws.row_dimensions[r].outline_level = OUTLINES[lv]
        stats[lv] += 1

    ws.column_dimensions[get_column_letter(COL_DESC)].width = 55

    # ── Export Review JSON (for dual-model LLM cross-check) ───────
    if args.export_review:
        review_rows = []
        review_reasons = {
            'promoted_L3→L2_has_L3_children',
            'promoted_L3→L2_Phase2b_child_is_L3',
            'confirmed_L3_has_L4_children',
            'demoted_L3→Note_no_children',
            'blacklist_preamble',
            'clause_reference',
            'pagination',
            'default_note_non_heading',
            'cn_semantic_deferred',
        }
        for r in sorted(level_map.keys()):
            reason = reason_map.get(r, 'unknown')
            if reason not in review_reasons:
                continue
            lv, desc = level_map[r]
            # Collect context: up to 5 rows before and after
            ctx_before, ctx_after = [], []
            for rr in range(max(min_row, r - 5), r):
                ctx_before.append({
                    'row': rr,
                    'code': get_code_str(rr),
                    'desc': get_desc_str(rr),
                    'unit': str(get_val(rr, COL_UNIT) or ''),
                    'qty': str(get_val(rr, COL_QTY) or ''),
                    'level': LABELS.get(level_map.get(rr, (L4, ''))[0], '?'),
                })
            for rr in range(r + 1, min(max_row + 1, r + 6)):
                ctx_after.append({
                    'row': rr,
                    'code': get_code_str(rr),
                    'desc': get_desc_str(rr),
                    'unit': str(get_val(rr, COL_UNIT) or ''),
                    'qty': str(get_val(rr, COL_QTY) or ''),
                    'level': LABELS.get(level_map.get(rr, (L4, ''))[0], '?'),
                })
            review_rows.append({
                'row': r,
                'code': get_code_str(r),
                'desc': desc,
                'unit': str(get_val(r, COL_UNIT) or ''),
                'qty': str(get_val(r, COL_QTY) or ''),
                'script_level': LABELS[lv],
                'script_reason': reason,
                'context_before': ctx_before,
                'context_after': ctx_after,
            })

        review_json = {
            'source': os.path.basename(args.input),
            'sheet': args.sheet or wb.sheetnames[0],
            'columns': {
                'code': args.code_col,
                'desc': args.desc_col,
                'qty': args.qty_col,
                'unit': args.unit_col,
            },
            'total_rows': len(level_map),
            'stats': {LABELS[k]: v for k, v in stats.items()},
            'review_count': len(review_rows),
            'review_rows': review_rows,
        }
        review_path = args.review_file or args.input.replace('.xlsx', '_review.json')
        with open(review_path, 'w', encoding='utf-8') as f:
            json.dump(review_json, f, ensure_ascii=False, indent=2)
        print(f'Review JSON exported: {review_path} ({len(review_rows)} ambiguous rows)')

    # ── Re-apply header formatting ──────────────────────────────
    header_font = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FFFFFFFF')
    header_fill = PatternFill(start_color='FF1F4E79', end_color='FF1F4E79', fill_type='solid')
    for _r in range(ws.min_row, min_row):
        for _c in range(1, ws.max_column + 1):
            _cell = ws.cell(row=_r, column=_c)
            _cell.font = header_font
            _cell.fill = header_fill
        ws.row_dimensions[_r].height = 28

    out_path = args.output or args.input
    clean_save(wb, out_path)

    # ── Validation ──────────────────────────────────────────────
    _validate_output(out_path, args.input, ws, COL_DESC, COL_UNIT, COL_QTY, min_row, max_row)

    default_note_n = sum(1 for r in reason_map if reason_map[r] == 'default_note_non_heading')

    print(f'\n层级统计 (NRM 五级):')
    for lv, name in [(L1, 'L1【】'), (L2, 'L2《》'), (L3, 'L3{}'), (NOTE, 'Note '), (L4, 'L4条目')]:
        print(f'  {name}: {stats[lv]} rows')
    print(f'  其中默认按说明(Note)处理: {default_note_n} rows（无标题特征，未强标题化；'
          f'如疑有真标题被降级，--export-review 复核）')
    print(f'Source: {args.input}')
    print(f'Output: {out_path}')


if __name__ == '__main__':
    main()
