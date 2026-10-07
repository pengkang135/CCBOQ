import openpyxl, sys, io, re, os
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'pk-boq', 'scripts'))
from openpyxl_utils import clean_save

SRC = r'e:\Code\CostSpread\static\初始数据\价格库_一般价格表\泰国\成本数据库\(OUT2026-07-22)143劳务分包_层级化.xlsx'

# AI Team Pipeline Enforcement
force = '--force' in sys.argv
if len(sys.argv) > 1 and sys.argv[1] not in ('--force',):
    SRC = sys.argv[1]

wb = openpyxl.load_workbook(SRC)
ws = wb[wb.sheetnames[0]]

min_row = ws.min_row + 1
max_row = ws.max_row
data_end_col = ws.max_column

# Count L4 items
l4_count = sum(1 for r in range(min_row, max_row + 1)
               if ws.cell(row=r, column=21).value == 'L4-条目')

if l4_count > 50 and not force:
    print(f"ERROR: {l4_count} L4 items detected (>50).")
    print(f"This task requires the AI team pipeline (pk-boq-ai-team).")
    print(f"Use --force to bypass (not recommended for quality).")
    sys.exit(1)

print(f'L4 item count: {l4_count}')

# Phase 1: Build parent stack (L1/L2/L3 headers)
# Track nearest L1/L2/L3 per row
dept_map = {}  # row_num -> (dept1, dept2, dept3)
l1 = l2 = l3 = ''

for row_num in range(min_row, max_row + 1):
    h = ws.cell(row=row_num, column=8).value
    lvl = ws.cell(row=row_num, column=21).value
    h_str = str(h).strip() if h else ''

    # Update parent stack
    if lvl == 'L1-一级':
        l1 = re.sub(r'[【】]', '', h_str)
        l2 = l3 = ''
    elif lvl == 'L2-二级':
        l2 = re.sub(r'[《》]', '', h_str)
        l3 = ''
    elif lvl == 'L3-三级':
        l3 = re.sub(r'[{}]', '', h_str)

    dept_map[row_num] = (l1, l2, l3)

print(f'Parent trace complete: {len(dept_map)} rows')

# Phase 2: Classify each L4 row
# Insert columns after data_end_col + 1 (skip 1 col gap)
insert_col = data_end_col + 2  # V column (22)

# Headers
headers = ['Dept1', 'Dept2', 'Dept3', 'Discipline', 'Category', 'Subcategory',
           'Description', 'Material', 'Spec', 'Unit', 'Quantity']
header_font = Font(bold=True, size=10, color='FFFFFFFF')
header_fill = PatternFill(start_color='FF0077B6', end_color='FF0077B6', fill_type='solid')

for i, hdr in enumerate(headers):
    cell = ws.cell(row=1, column=insert_col + i)
    cell.value = hdr
    cell.font = header_font
    cell.fill = header_fill

def classify_item(desc, dept1, dept2, dept3):
    """Keyword + context based classification"""
    d = desc.lower()
    ctx = f'{dept1} {dept2} {dept3}'.lower()

    # Defaults
    discipline = '土建工程'
    category = '其他'
    subcategory = ''
    material = desc
    spec = ''

    # Discipline
    if any(w in ctx for w in ['钢结构', 'steel structure', 'structural steel', 'gantry']):
        discipline = '钢结构工程'
    elif any(w in ctx for w in ['mep', 'electrical', 'plumbing', 'fire', 'hvac', 'acmv', 'hydraulic', 'sanitary', 'drainage', 'lighting', 'cable', 'lift', 'elevator']):
        discipline = '安装工程'
    elif any(w in ctx for w in ['finish', 'decoration', 'plaster', 'tile', 'paint', 'ceiling', 'door', 'window', 'signage', 'floor']):
        discipline = '装饰工程'
    elif any(w in ctx for w in ['external', 'infrastructure', 'road', 'landscape', 'fencing', 'drain', 'sewer']):
        discipline = '室外工程'

    # Category
    if any(w in d for w in ['concrete', 'mpa', 'ksc', 'reinforced concrete', 'cement', 'screed', 'grout']):
        category = '混凝土'
    elif any(w in d for w in ['rebar', 'reinforc', 'db ', 'rb ', 'coupler', 'bar', 'mesh']):
        category = '钢筋'
    elif any(w in d for w in ['formwork', 'shuttering', 'mould', 'form']):
        category = '模板'
    elif any(w in d for w in ['excav', 'backfill', 'earthwork', 'compaction', 'trench']):
        category = '土方'
    elif any(w in d for w in ['block', 'brick', 'masonry', 'wall']):
        category = '砌筑'
    elif any(w in d for w in ['plaster', 'render', 'screed']):
        category = '抹灰'
    elif any(w in d for w in ['paint', 'coating', 'fire rate', 'blast']):
        category = '涂料'
    elif any(w in d for w in ['tile', 'floor finish', 'vinyl']):
        category = '地面'
    elif any(w in d for w in ['waterproof', 'membrane', 'tanking']):
        category = '防水'
    elif any(w in d for w in ['steel', 'beam', 'column', 'truss', 'purlin', 'bolt', 'weld', 'bracing', 'gantry', 'metal']):
        category = '钢结构'
    elif any(w in d for w in ['pipe', 'duct', 'conduit', 'cable', 'wire']):
        category = '管道/线缆'
    elif any(w in d for w in ['door', 'window', 'louver', 'ironmongery']):
        category = '门窗'
    elif any(w in d for w in ['ceiling', 'suspended']):
        category = '天花'
    elif any(w in d for w in ['scaffold', 'platform']):
        category = '脚手架'
    elif any(w in d for w in ['manhole', 'drain', 'duct bank']):
        category = '管沟/检查井'
    elif any(w in d for w in ['pile', 'bored', 'bore', 'driven']):
        category = '桩基'
    elif any(w in d for w in ['road', 'pavement', 'asphalt', 'kerb', 'curb']):
        category = '道路'
    elif any(w in d for w in ['fence', 'gate', 'bollard']):
        category = '围栏'
    elif any(w in d for w in ['signage', 'sign']):
        category = '标识'
    elif any(w in d for w in ['plant', 'tree', 'turf', 'landscape', 'soil']):
        category = '绿化'
    elif any(w in d for w in ['lift', 'elevator']):
        category = '电梯'
    elif any(w in d for w in ['pump', 'tank', 'chiller', 'fan', 'ahu', 'fcu']):
        category = '暖通设备'
    elif any(w in d for w in ['switchgear', 'panel', 'transformer', 'generator', 'db ', 'distribution']):
        category = '电气设备'
    elif any(w in d for w in ['fire', 'sprinkler', 'alarm', 'extinguish']):
        category = '消防'
    elif any(w in d for w in ['security', 'cctv', 'access control']):
        category = '弱电/安防'
    elif any(w in d for w in ['roof', 'slab', 'core']):
        category = '主体结构'

    # Subcategory
    if category == '混凝土':
        m = re.search(r'(\d+)\s*MPa', desc)
        subcategory = f'{m.group(1)}MPa' if m else ''
    elif category == '钢筋':
        m = re.search(r'(DB|RB)\s*(\d+)', desc, re.IGNORECASE)
        subcategory = f'{m.group(1)}{m.group(2)}mm' if m else ''
    elif category == '模板':
        if 'beam' in d: subcategory = '梁模板'
        elif 'column' in d: subcategory = '柱模板'
        elif 'wall' in d: subcategory = '墙模板'
        elif 'slab' in d: subcategory = '楼板模板'
        else: subcategory = '模板'
    elif category == '钢结构':
        if 'bolt' in d: subcategory = '螺栓'
        elif 'weld' in d: subcategory = '焊接'
        elif 'column' in d: subcategory = '钢柱'
        elif 'beam' in d: subcategory = '钢梁'
        else: subcategory = '钢结构'
    elif category == '土方':
        if 'excav' in d: subcategory = '开挖'
        elif 'backfill' in d: subcategory = '回填'
        else: subcategory = '土方'
    elif category == '涂料':
        if 'fire' in d: subcategory = '防火涂料'
        elif 'blast' in d: subcategory = '喷砂'
        else: subcategory = '涂料'

    # Material extraction
    if 'concrete' in d:
        material = '混凝土'
        if not spec:
            m = re.search(r'(\d+)\s*MPa', desc)
            if m: spec = f'{m.group(1)}MPa'
    elif any(w in d for w in ['db ', 'rb ', 'rebar', 'reinforc']):
        material = '钢筋'
        if not spec:
            m = re.search(r'(DB|RB)\s*(\d+)', desc, re.IGNORECASE)
            if m: spec = f'{m.group(1)}{m.group(2)}mm'
    elif 'bolt' in d:
        material = '螺栓'
        m = re.search(r'M(\d+)', desc)
        if m: spec = f'M{m.group(1)}'
    elif any(w in d for w in ['formwork', 'shuttering', 'mould']):
        material = '模板'
    elif 'paint' in d or 'coat' in d:
        material = '涂料'
    elif 'steel' in d:
        material = '钢材'

    return discipline, category, subcategory, material, spec

# Process L4 rows
classified = 0
for row_num in range(min_row, max_row + 1):
    lvl = ws.cell(row=row_num, column=21).value
    if lvl != 'L4-条目':
        continue

    h = ws.cell(row=row_num, column=8).value
    i = ws.cell(row=row_num, column=9).value   # unit
    j = ws.cell(row=row_num, column=10).value  # qty
    if not h: continue

    desc = str(h).strip()
    dept1, dept2, dept3 = dept_map.get(row_num, ('', '', ''))
    discipline, category, subcategory, material, spec = classify_item(desc, dept1, dept2, dept3)

    # Direct references: use Excel formulas to link to source cells
    desc_val = f'=H{row_num}'
    unit_val = f'=I{row_num}'
    qty_val  = f'=J{row_num}'

    vals = [dept1, dept2, dept3, discipline, category, subcategory,
            desc_val, material, spec, unit_val, qty_val]

    for offset, val in enumerate(vals):
        ws.cell(row=row_num, column=insert_col + offset).value = val

    classified += 1
    if classified <= 5:
        print(f'Row {row_num}: [{discipline}/{category}] {desc[:40]}')

# Column widths
for i in range(len(headers)):
    ws.column_dimensions[get_column_letter(insert_col + i)].width = 20

out_path = SRC.replace('_层级化.xlsx', '_classified.xlsx')
clean_save(wb, out_path)
print(f'\nClassified {classified} rows')
print(f'Saved: {out_path}')
