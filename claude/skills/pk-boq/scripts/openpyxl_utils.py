"""
openpyxl clean-save utility: save workbook then ZIP-level clean [trash]/ and customXml.
Import and use clean_save(wb, path) instead of wb.save(path).
"""
import os, re, io, zipfile


def clean_save(workbook, path):
    """Save openpyxl workbook, then clean [trash]/ and customXml from the ZIP."""
    workbook.save(path)

    tmp = path + '.tmp'
    with zipfile.ZipFile(path, 'r') as zin:
        names = zin.namelist()
        junk = [n for n in names
                if 'trash' in n.lower() or 'Trash' in n or 'customXml' in n.lower()]
        keep = [n for n in names if n not in junk]

        if not junk:
            return  # already clean

        # Clean workbook.xml.rels
        wb_rels = zin.read('xl/_rels/workbook.xml.rels').decode('utf-8', errors='replace')
        wb_rels = re.sub(r'<Relationship[^>]*?customXml[^>]*?/>', '', wb_rels)

        # Clean [Content_Types].xml
        ct = zin.read('[Content_Types].xml').decode('utf-8', errors='replace')
        ct = re.sub(r'<Override[^>]*?customXml[^>]*?/>', '', ct)

        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            for name in keep:
                if name == 'xl/_rels/workbook.xml.rels':
                    zout.writestr(name, wb_rels)
                elif name == '[Content_Types].xml':
                    zout.writestr(name, ct)
                else:
                    zout.writestr(name, zin.read(name))

    os.replace(tmp, path)
    print(f'  clean_save: removed {len(junk)} junk entries')
