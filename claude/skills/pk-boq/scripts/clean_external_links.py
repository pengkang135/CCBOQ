"""
Clean xlsx file at ZIP/XML level:
  - Strip all external link definitions (xl/externalLinks/)
  - Paste cells referencing bad defined names as values, then remove bad names
  - Clean .rels files referring to external links
  - Clean calcChain of value-pasted cells
  - Backup original file before cleaning

Hybrid approach: ET for accurate detection, regex/text for modification
(preserves original XML structure to avoid Excel crashes).

Usage: python clean_external_links.py <file.xlsx> [-o output.xlsx] [--no-backup]
"""
import zipfile, os, sys, shutil, argparse, re
from xml.etree import ElementTree as ET

SPREADSHEET_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
SHEET_RE = re.compile(r'xl/worksheets/sheet(\d+)\.xml$')
EXT_REF_RE = re.compile(r'\[\d+\]')

EXCEL_BUILTINS = {
    'SUM', 'IF', 'AND', 'OR', 'NOT', 'TRUE', 'FALSE',
    'AVERAGE', 'COUNT', 'COUNTA', 'COUNTIF', 'COUNTIFS',
    'SUMIF', 'SUMIFS', 'SUMPRODUCT', 'VLOOKUP', 'HLOOKUP',
    'XLOOKUP', 'INDEX', 'MATCH', 'CHOOSE', 'OFFSET',
    'INDIRECT', 'ROW', 'COLUMN', 'ROWS', 'COLUMNS',
    'MIN', 'MAX', 'LARGE', 'SMALL', 'RANK',
    'LEFT', 'RIGHT', 'MID', 'LEN', 'TRIM', 'CONCATENATE',
    'TEXT', 'VALUE', 'DATE', 'YEAR', 'MONTH', 'DAY',
    'TODAY', 'NOW', 'ISERROR', 'ISNA', 'IFERROR',
    'ROUND', 'ROUNDUP', 'ROUNDDOWN', 'INT', 'MOD',
    'ABS', 'SQRT', 'POWER', 'PI', 'CELL', 'TYPE',
    'HYPERLINK', 'TRANSPOSE', 'SUBTOTAL', 'AGGREGATE',
}
_ERROR_TOKENS = ('#REF!', '#VALUE!', '#N/A', '#NAME?', '#DIV/0!', '#NULL!', '#NUM!')
_FORMULA_SPLIT_RE = re.compile(r'[+\-*/^&<>=(),:;{}\[\]\"\'!\s]+')
# External reference patterns (used standalone, complementing '[' check)
_EXT_PROTO_RE = re.compile(r'file://|https?://')
_EXT_UNC_RE = re.compile(r'\\\\[a-zA-Z]')
_EXT_ABS_PATH_RE = re.compile(r"[A-Za-z]:\\")


def is_skip_name(name):
    if not name:
        return True
    if len(name) == 1 and name.isascii() and name.isalpha():
        return True
    if name.isdigit():
        return True
    if name.upper() in EXCEL_BUILTINS:
        return True
    return False


def clean_file(input_path, output_path):
    stats = {'ext_links': 0, 'names': 0, 'cells': 0, 'calcchain': 0, 'rels': 0}

    with zipfile.ZipFile(input_path, 'r') as zin:
        namelist = zin.namelist()
        all_data = {name: zin.read(name) for name in namelist}

    # Step 1: Identify bad definedNames (simple heuristic)
    bad_names = set()
    wb_data = all_data.get('xl/workbook.xml', b'')
    wb_text = wb_data.decode('utf-8', errors='replace')
    for m in re.finditer(r'<definedName\s+([^>]*?)(?:/>|>(.*?)</definedName>)', wb_text, re.DOTALL):
        attrs = m.group(1)
        body = m.group(2) or ''
        name_match = re.search(r'name="([^"]*)"', attrs)
        if not name_match:
            continue
        name = name_match.group(1)
        if is_skip_name(name):
            continue
        is_bad = False
        for tok in _ERROR_TOKENS:
            if tok in body:
                is_bad = True
                break
        if '[' in body:
            is_bad = True
        if _EXT_PROTO_RE.search(body):
            is_bad = True
        if _EXT_UNC_RE.search(body):
            is_bad = True
        if _EXT_ABS_PATH_RE.search(body):
            is_bad = True
        if is_bad:
            bad_names.add(name)
    print(f'  Found {len(bad_names)} bad definedNames for formula matching')

    bad_names_set = bad_names

    # Build mapping: sheet file number -> sheetId (for calcChain matching)
    sheet_file_to_sheet_id = {}
    if 'xl/workbook.xml' in all_data:
        rels_data = all_data.get('xl/_rels/workbook.xml.rels', b'')
        rels_text = rels_data.decode('utf-8', errors='replace')
        rid_to_target = {}
        for m in re.finditer(r'<Relationship[^>]*?Id="([^"]*)"[^>]*?Target="([^"]*)"', rels_text):
            rid_to_target[m.group(1)] = m.group(2)
        for m in re.finditer(r'<sheet\s+([^>]*?)/>', wb_text):
            sid_m = re.search(r'sheetId="(\d+)"', m.group(1))
            rid_m = re.search(r'r:id="([^"]*)"', m.group(1))
            if sid_m and rid_m and rid_m.group(1) in rid_to_target:
                target = rid_to_target[rid_m.group(1)]
                file_num_m = re.search(r'sheet(\d+)\.xml', target)
                if file_num_m:
                    sheet_file_to_sheet_id[file_num_m.group(1)] = sid_m.group(1)

    # Step 2: Parse each sheet with ET to find cells to convert + their si groups
    sheet_cells_converted = set()

    for name, data in sorted(all_data.items()):
        sm = SHEET_RE.match(name)
        if not sm:
            continue
        sheet_idx = sm.group(1)

        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue

        # Build si map: si -> set of cell refs (all cells in the shared formula group)
        si_map = {}
        for cell in root.iter('{%s}c' % SPREADSHEET_NS):
            f_el = cell.find('{%s}f' % SPREADSHEET_NS)
            if f_el is not None and f_el.get('t') == 'shared':
                si = f_el.get('si', '')
                if si:
                    si_map.setdefault(si, set()).add(cell.get('r', ''))

        # Find cells to convert: check for external refs or bad definedNames
        cells_to_convert = set()
        for cell in root.iter('{%s}c' % SPREADSHEET_NS):
            f_el = cell.find('{%s}f' % SPREADSHEET_NS)
            if f_el is None or not f_el.text:
                continue
            matched = False
            formula_text = f_el.text
            if EXT_REF_RE.search(formula_text):
                matched = True
            elif bad_names_set:
                tokens = _FORMULA_SPLIT_RE.split(formula_text)
                for token in tokens:
                    if token and token in bad_names_set:
                        matched = True
                        break
            if matched:
                ref = cell.get('r', '')
                if f_el.get('t') == 'shared':
                    si = f_el.get('si', '')
                    if si and si in si_map:
                        cells_to_convert.update(si_map[si])
                    else:
                        cells_to_convert.add(ref)
                elif ref:
                    cells_to_convert.add(ref)

        if not cells_to_convert:
            continue

        # Apply conversions using text manipulation (preserves XML structure)
        text = all_data[name].decode('utf-8', errors='replace')
        converted_cells = []

        for cell_ref in sorted(cells_to_convert):
            cell_pattern = re.compile(
                r'(<c\s+[^>]*?\br="' + re.escape(cell_ref) + r'"[^>]*>)(.*?)(</c>)',
                re.DOTALL
            )
            m = cell_pattern.search(text)
            if not m:
                continue

            prefix = m.group(1)
            content = m.group(2)
            suffix = m.group(3)

            # Remove <f> element
            fm = re.search(r'<f\b[^>]*(?:/>|>.*?</f>)', content, re.DOTALL)
            if fm:
                content = content[:fm.start()] + content[fm.end():]
                content = content.strip()

            # Ensure <v> exists with value
            if '<v>' not in content and '<v ' not in content:
                content += '<v>0</v>'

            replacement = prefix + content + suffix
            text = text[:m.start()] + replacement + text[m.end():]
            converted_cells.append(cell_ref)
            sheet_id = sheet_file_to_sheet_id.get(sheet_idx, sheet_idx)
            sheet_cells_converted.add((sheet_id, cell_ref))

        if converted_cells:
            all_data[name] = text.encode('utf-8')
            stats['cells'] += len(converted_cells)

    print(f'  Converted {stats["cells"]} cells to values across all sheets')

    # Step 2b: Fix orphan shared formulas (slaves without masters)
    total_orphan_fixed = 0
    for name, data in sorted(all_data.items()):
        sm = SHEET_RE.match(name)
        if not sm:
            continue
        sheet_idx = sm.group(1)
        text = data.decode('utf-8', errors='replace')
        if 't="shared"' not in text:
            continue

        master_sis = set()
        for m in re.finditer(r'<f\s+[^>]*t="shared"[^>]*ref="[^"]*"[^>]*si="(\d+)"', text):
            master_sis.add(m.group(1))

        orphan_cell_refs = []

        if not master_sis:
            for m in re.finditer(r'<c\s+[^>]*?\br="([^"]*)"[^>]*>.*?<f\s+[^>]*t="shared".*?</c>', text, re.DOTALL):
                orphan_cell_refs.append(m.group(1))
            text = re.sub(r'<f\s+[^>]*t="shared"[^>]*/>', '', text)
            text = re.sub(r'<f\s+[^>]*t="shared"[^>]*>.*?</f>', '', text)
        else:
            orphan_sis = set()
            for m in re.finditer(r'<f\s+[^>]*t="shared"[^>]*si="(\d+)"', text):
                si = m.group(1)
                if 'ref=' not in m.group(0) and si not in master_sis:
                    orphan_sis.add(si)

            if not orphan_sis:
                continue

            for si_val in sorted(orphan_sis, key=int):
                cell_pattern = re.compile(
                    r'<c\s+[^>]*?\br="([^"]*)"[^>]*>.*?<f\s+[^>]*t="shared"[^>]*si="'
                    + re.escape(si_val) + r'"[^>]*(?:/>|>.*?</f>).*?</c>',
                    re.DOTALL
                )
                for cm in cell_pattern.finditer(text):
                    orphan_cell_refs.append(cm.group(1))

                orphan_f_re = re.compile(
                    r'<f\s+[^>]*t="shared"[^>]*si="' + re.escape(si_val) + r'"[^>]*/>'
                    r'|<f\s+[^>]*t="shared"[^>]*si="' + re.escape(si_val) + r'"[^>]*>.*?</f>'
                )
                text = orphan_f_re.sub('', text)

        if orphan_cell_refs:
            text = re.sub(r'\s{2,}</c>', '</c>', text)
            all_data[name] = text.encode('utf-8')
            total_orphan_fixed += len(orphan_cell_refs)
            sheet_id = sheet_file_to_sheet_id.get(sheet_idx, sheet_idx)
            for ref in orphan_cell_refs:
                sheet_cells_converted.add((sheet_id, ref))

    if total_orphan_fixed:
        stats['orphans'] = total_orphan_fixed
        print(f'  Fixed {total_orphan_fixed} orphan shared formula cells')

    # Step 3: Clean workbook.xml — remove bad definedNames (text-based)
    wb_text = all_data['xl/workbook.xml'].decode('utf-8', errors='replace')
    removed = 0

    def replace_bad_dn(m):
        nonlocal removed
        body = m.group(2) if m.group(2) else ''
        attrs = m.group(1)
        is_bad = False
        for tok in _ERROR_TOKENS:
            if tok in body:
                is_bad = True
                break
        if '[' in body:
            is_bad = True
        if _EXT_PROTO_RE.search(body):
            is_bad = True
        if _EXT_UNC_RE.search(body):
            is_bad = True
        if _EXT_ABS_PATH_RE.search(body):
            is_bad = True
        if is_bad:
            removed += 1
            return ''
        return m.group(0)

    wb_text = re.sub(
        r'<definedName\s+([^>]*?)(?:/>|>(.*?)</definedName>)',
        replace_bad_dn, wb_text, flags=re.DOTALL
    )
    wb_text = re.sub(r'<definedNames[^>]*?>\s*</definedNames>', '', wb_text)
    wb_text = re.sub(r'<externalReferences[^>]*?/>', '', wb_text)
    wb_text = re.sub(r'<externalReferences>.*?</externalReferences>', '', wb_text, flags=re.DOTALL)
    wb_text = re.sub(r'\r\n\s*\r\n\s*\r\n', '\r\n\r\n', wb_text)

    all_data['xl/workbook.xml'] = wb_text.encode('utf-8')
    stats['names'] = removed
    print(f'  Removed {removed} bad definedNames')

    # Step 4: Clean calcChain (text-based)
    if 'xl/calcChain.xml' in all_data and sheet_cells_converted:
        cc_text = all_data['xl/calcChain.xml'].decode('utf-8', errors='replace')
        cc_removed = 0

        def replace_cc(m):
            nonlocal cc_removed
            attrs = m.group(0)
            i_m = re.search(r'\bi="(\d+)"', attrs)
            r_m = re.search(r'\br="([^"]*)"', attrs)
            if i_m and r_m and (i_m.group(1), r_m.group(1)) in sheet_cells_converted:
                cc_removed += 1
                return ''
            return m.group(0)

        cc_text = re.sub(r'<c\s+[^>]*?/>', replace_cc, cc_text)
        cc_text = re.sub(r'\r\n\s*\r\n\s*\r\n', '\r\n\r\n', cc_text)
        all_data['xl/calcChain.xml'] = cc_text.encode('utf-8')
        stats['calcchain'] = cc_removed
        print(f'  Removed {cc_removed} calcChain entries')

    # Step 5: Clean rels files (text-based)
    for name in list(all_data.keys()):
        if not name.endswith('.rels'):
            continue
        text = all_data[name].decode('utf-8', errors='replace')
        new_text = re.sub(r'<Relationship[^>]*?Type="[^"]*externalLink[^"]*"[^>]*?/>', '', text)
        if new_text != text:
            all_data[name] = new_text.encode('utf-8')
            stats['rels'] += 1

    # Step 6: Clean Content_Types (text-based)
    ct_text = all_data['[Content_Types].xml'].decode('utf-8', errors='replace')
    ct_text = re.sub(r'<Override[^>]*?PartName="/xl/externalLinks/[^"]*"[^>]*?/>', '', ct_text)
    all_data['[Content_Types].xml'] = ct_text.encode('utf-8')

    # Step 7: Write output
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name in namelist:
            if 'externalLinks/' in name or 'trash/' in name:
                if 'externalLinks/' in name:
                    stats['ext_links'] += 1
                continue
            if name not in all_data:
                continue
            zout.writestr(name, all_data[name])

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean external links from xlsx at ZIP/XML level')
    parser.add_argument('input', help='Input .xlsx file')
    parser.add_argument('-o', '--output', help='Output path (default: {input}_clean.xlsx)')
    parser.add_argument('--no-backup', action='store_true', help='Skip backup')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: File not found: {args.input}")
        sys.exit(1)

    output_path = args.output or args.input.replace('.xlsx', '_clean.xlsx')

    if not args.no_backup:
        backup_dir = os.path.join(os.path.dirname(args.input) or '.', '原始备份')
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, os.path.basename(args.input))
        if not os.path.exists(backup_path):
            shutil.copy2(args.input, backup_path)
            print(f"Backup: {backup_path}")

    print(f'Cleaning: {args.input}')
    stats = clean_file(args.input, output_path)
    orig_sz = os.path.getsize(args.input)
    new_sz = os.path.getsize(output_path)
    print(f'Stats: {stats}')
    print(f'Size: {orig_sz/1024:.0f}KB -> {new_sz/1024:.0f}KB ({(1-new_sz/orig_sz)*100:.1f}% reduced)')
    print(f'Output: {output_path}')
