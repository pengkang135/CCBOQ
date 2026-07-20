"""
Clean xlsx external links.
- Cells: convert formulas with [N] external refs to values (never delete cells)
- Names: delete bad definedNames (errors, external refs, file paths)
- Key fix: self-closing <f/> and content <f>...</f> matched separately to avoid
  the [^>]* eating / and causing massive cross-cell consumption.
"""
import zipfile, os, sys, re

SHEET_RE = re.compile(r'xl/worksheets/sheet(\d+)\.xml$')
EXT_REF_RE = re.compile(r'\[\d+\]')
_ERROR_TOKENS = ('#REF!', '#VALUE!', '#N/A', '#NAME?', '#DIV/0!', '#NULL!', '#NUM!')
_EXT_PROTO_RE = re.compile(r'file://|https?://')
_EXT_UNC_RE = re.compile(r'\\\\[a-zA-Z]')
_EXT_ABS_PATH_RE = re.compile(r"[A-Za-z]:\\")

# Self-closing <f .../>  — [^/>]* stops at /, then /> must follow
_F_SC_RE = re.compile(r'<f\b([^/>]*)/>')
# Content <f ...>formula</f>
_F_CONTENT_RE = re.compile(r'<f\b([^>]*)>(.*?)</f>', re.DOTALL)


def is_bad_name_body(body):
    for tok in _ERROR_TOKENS:
        if tok in body:
            return True
    if '[' in body:
        return True
    if _EXT_PROTO_RE.search(body):
        return True
    if _EXT_UNC_RE.search(body):
        return True
    if _EXT_ABS_PATH_RE.search(body):
        return True
    return False


def clean_sheet_xml(text):
    """Remove <f> elements containing [N] external refs. Never delete cells."""
    cells_converted = 0
    orphans_fixed = 0

    # Collect all <f> positions, content, and attributes
    f_entries = []

    # Pass 1: Match self-closing <f .../>  (stops at / before >)
    sc_positions = set()
    for m in _F_SC_RE.finditer(text):
        attrs = m.group(1) or ''
        is_shared = 't="shared"' in attrs
        is_master = is_shared and 'ref="' in attrs
        is_slave = is_shared and 'ref="' not in attrs
        si_m = re.search(r'si="(\d+)"', attrs)
        si = si_m.group(1) if si_m else ''
        sc_positions.add(m.start())
        f_entries.append({
            'start': m.start(), 'end': m.end(),
            'attrs': attrs, 'content': '', 'has_ext_ref': False,
            'is_shared': is_shared, 'is_master': is_master,
            'is_slave': is_slave, 'si': si,
        })

    # Pass 2: Match <f ...>content</f>, skip positions already matched as self-closing
    for m in _F_CONTENT_RE.finditer(text):
        if m.start() in sc_positions:
            continue  # already handled as self-closing in pass 1
        attrs = m.group(1) or ''
        content = m.group(2) or ''
        has_ext = bool(EXT_REF_RE.search(content))
        is_shared = 't="shared"' in attrs
        is_master = is_shared and 'ref="' in attrs
        is_slave = is_shared and 'ref="' not in attrs
        si_m = re.search(r'si="(\d+)"', attrs)
        si = si_m.group(1) if si_m else ''
        f_entries.append({
            'start': m.start(), 'end': m.end(),
            'attrs': attrs, 'content': content, 'has_ext_ref': has_ext,
            'is_shared': is_shared, 'is_master': is_master,
            'is_slave': is_slave, 'si': si,
        })

    # Find master si values whose formulas have external refs
    master_si_to_remove = set()
    for e in f_entries:
        if e['has_ext_ref'] and e['is_master']:
            master_si_to_remove.add(e['si'])

    # Decide what to remove
    for e in f_entries:
        if e['has_ext_ref']:
            e['remove'] = True
        elif e['is_slave'] and e['si'] in master_si_to_remove:
            e['remove'] = True
            orphans_fixed += 1
        else:
            e['remove'] = False

    # Build replacement list: (start, end, replacement_text)
    ops = []
    for e in f_entries:
        if not e['remove']:
            continue
        start, end = e['start'], e['end']

        # Check if enclosing cell already has a <v> element after this <f>
        after_f = text[end:]
        next_c_end = after_f.find('</c>')
        between = after_f[:next_c_end] if next_c_end >= 0 else ''
        has_val = '<v>' in between or '<v ' in between

        replacement = '' if has_val else '<v>0</v>'
        ops.append((start, end, replacement))
        cells_converted += 1

    # Apply in reverse order (no position adjustment needed)
    for start, end, replacement in sorted(ops, key=lambda x: x[0], reverse=True):
        text = text[:start] + replacement + text[end:]

    return text, cells_converted, orphans_fixed


def clean_file(input_path, output_path):
    stats = {'ext_links': 0, 'names': 0, 'cells': 0, 'orphans': 0, 'calcchain': 0, 'rels': 0}

    with zipfile.ZipFile(input_path, 'r') as zin:
        namelist = zin.namelist()
        all_data = {name: zin.read(name) for name in namelist}

    # Step 1: Collect bad definedNames
    wb_text = all_data['xl/workbook.xml'].decode('utf-8', errors='replace')
    bad_names = set()
    for m in re.finditer(r'<definedName\s+([^>]*?)(?:/>|>(.*?)</definedName>)', wb_text, re.DOTALL):
        attrs = m.group(1)
        body = m.group(2) or ''
        name_match = re.search(r'name="([^"]*)"', attrs)
        if not name_match:
            continue
        name = name_match.group(1)
        if len(name) <= 2 and name.isascii() and (name.isalpha() or name.isdigit()):
            continue
        if is_bad_name_body(body):
            bad_names.add(name)
    print(f'  Bad definedNames: {len(bad_names)}')

    # Step 2: Process each sheet
    for zname in sorted(all_data.keys()):
        if not SHEET_RE.match(zname):
            continue
        text = all_data[zname].decode('utf-8', errors='replace')
        new_text, converted, orphans = clean_sheet_xml(text)
        if new_text != text:
            all_data[zname] = new_text.encode('utf-8')
        stats['cells'] += converted
        stats['orphans'] += orphans

    print(f'  Cells converted: {stats["cells"]}')
    print(f'  Orphan shared formulas fixed: {stats["orphans"]}')

    # Step 3: Remove bad definedNames
    def remove_bad_dn(m):
        nonlocal stats
        body = m.group(2) if m.group(2) else ''
        if is_bad_name_body(body):
            stats['names'] += 1
            return ''
        return m.group(0)

    wb_text = re.sub(
        r'<definedName\s+([^>]*?)(?:/>|>(.*?)</definedName>)',
        remove_bad_dn, wb_text, flags=re.DOTALL
    )
    wb_text = re.sub(r'<definedNames[^>]*?>\s*</definedNames>', '', wb_text)
    wb_text = re.sub(r'<externalReferences[^>]*?/>', '', wb_text)
    wb_text = re.sub(r'<externalReferences>.*?</externalReferences>', '', wb_text, flags=re.DOTALL)
    wb_text = re.sub(r'\n\s*\n\s*\n', '\n\n', wb_text)
    all_data['xl/workbook.xml'] = wb_text.encode('utf-8')
    print(f'  Names removed: {stats["names"]}')

    # Step 4: Clean rels
    for rname in list(all_data.keys()):
        if not rname.endswith('.rels'):
            continue
        text = all_data[rname].decode('utf-8', errors='replace')
        new_text = re.sub(r'<Relationship[^>]*?Type="[^"]*externalLink[^"]*"[^>]*?/>', '', text)
        if new_text != text:
            all_data[rname] = new_text.encode('utf-8')
            stats['rels'] += 1

    # Step 5: Clean Content_Types
    if '[Content_Types].xml' in all_data:
        ct_text = all_data['[Content_Types].xml'].decode('utf-8', errors='replace')
        ct_text = re.sub(r'<Override[^>]*?PartName="/xl/externalLinks/[^"]*"[^>]*?/>', '', ct_text)
        all_data['[Content_Types].xml'] = ct_text.encode('utf-8')

    # Step 6: Delete calcChain (Excel will rebuild)
    if 'xl/calcChain.xml' in all_data:
        del all_data['xl/calcChain.xml']
        stats['calcchain'] = 1

    # Step 7: Write output, skip externalLinks
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for zname in namelist:
            if 'externalLinks/' in zname:
                stats['ext_links'] += 1
                continue
            if zname not in all_data:
                continue
            zout.writestr(zname, all_data[zname])

    print(f'  External links skipped: {stats["ext_links"]}')
    return stats


if __name__ == '__main__':
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else input_path.replace('.xlsx', '_clean.xlsx')
    print(f'Cleaning: {os.path.basename(input_path)}')
    stats = clean_file(input_path, output_path)
    orig_sz = os.path.getsize(input_path)
    new_sz = os.path.getsize(output_path)
    print(f'Stats: {stats}')
    print(f'Size: {orig_sz/1024:.0f}KB -> {new_sz/1024:.0f}KB ({(1-new_sz/orig_sz)*100:.1f}% reduced)')
    print(f'Output: {output_path}')
