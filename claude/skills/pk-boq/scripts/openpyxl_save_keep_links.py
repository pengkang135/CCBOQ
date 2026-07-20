"""
openpyxl 保留外部链接缓存的辅助工具。

问题：openpyxl 的 load-modify-save 破坏两类外部链接相关的数据：
  A. xl/externalLinks/*.xml 的字节可能被重新序列化（部分版本）
  B. 关键 bug：sheet*.xml 里含外部引用（如 SUMIFS([2]Book!$G:$G,...)）的公式
     单元格，openpyxl 因无法计算而把 <v>value</v> 写成 <v></v> 空缓存。
     Excel 打开发现"公式声明有缓存但值为空"→与 externalLink*.xml 对不上→
     触发"已修复的记录"提示。

方案：
  1. 让 openpyxl 正常 save 到临时文件
  2. 从"参考版本"（未被 openpyxl 破坏的干净文件，一般是修改前的备份）
     读取 xl/externalLinks/*.xml 的原始字节 → overlay
  3. 修剪临时文件里所有 sheet*.xml：把 <f>...</f><v></v> 这种"空缓存"的
     <v></v> 元素整个删掉，让 Excel 视为"无缓存，请重算"

用法：
    from openpyxl_save_keep_links import save_keep_links

    wb = load_workbook('file.xlsx')
    ws = wb['BOQ']
    ws.cell(103, 4).value = '建筑拆除'
    save_keep_links(wb, dst='file.xlsx', link_source='file.xlsx')
"""
from __future__ import annotations
import os
import re
import tempfile
import zipfile
from pathlib import Path

# 匹配紧跟在 </f> 后的空 <v></v> 或 <v/>
_EMPTY_V_AFTER_F = re.compile(r'(</f>)(<v></v>|<v\s*/>)')


def _read_external_link_bytes(zip_path: str | Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not Path(zip_path).exists():
        return out
    with zipfile.ZipFile(zip_path, 'r') as z:
        for name in z.namelist():
            if name.startswith('xl/externalLinks/'):
                out[name] = z.read(name)
    return out


def _strip_empty_formula_cache(sheet_xml: bytes) -> tuple[bytes, int]:
    """删除公式单元格里的空 <v></v>。返回 (新内容, 删除个数)。"""
    text = sheet_xml.decode('utf-8', errors='replace')
    new_text, n = _EMPTY_V_AFTER_F.subn(r'\1', text)
    return new_text.encode('utf-8'), n


def save_keep_links(wb, dst: str | Path, link_source: str | Path | None = None) -> dict:
    """
    保存工作簿，保留外部链接完整性。

    Returns:
        dict: 统计信息 (empty_v_removed_per_sheet, ext_link_overlaid_count)
    """
    dst = Path(dst)
    if link_source is None:
        link_source = dst
    link_source = Path(link_source)

    # 1. 提前读原始外链字节（防止 dst == link_source 时 openpyxl 覆盖前来不及读）
    ext_bytes = _read_external_link_bytes(link_source)

    # 2. openpyxl 写到临时文件
    fd, tmp_path = tempfile.mkstemp(suffix='.xlsx', prefix='openpyxl_')
    os.close(fd)
    stats = {'ext_link_overlaid': 0, 'empty_v_removed': {}}
    try:
        wb.save(tmp_path)

        # 3. 读临时文件，处理 sheet*.xml，overlay 外链，写到 dst
        with zipfile.ZipFile(tmp_path, 'r') as ztmp:
            all_names = ztmp.namelist()
            all_data = {n: ztmp.read(n) for n in all_names}

        # 修剪 sheet*.xml 里的空 <v></v>
        for name in list(all_data.keys()):
            if re.match(r'^xl/worksheets/sheet\d+\.xml$', name):
                new_bytes, removed = _strip_empty_formula_cache(all_data[name])
                if removed:
                    all_data[name] = new_bytes
                    stats['empty_v_removed'][name] = removed

        # Overlay 外链
        for name, data in ext_bytes.items():
            all_data[name] = data
            stats['ext_link_overlaid'] += 1

        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
            for name, data in all_data.items():
                zout.writestr(name, data)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return stats


def repair_existing_file(path: str | Path) -> dict:
    """
    修复已被 openpyxl 破坏的现有文件（原地修复）：删除 sheet*.xml 里所有
    <f>...</f><v></v> 的空缓存 <v></v>。
    """
    path = Path(path)
    with zipfile.ZipFile(path, 'r') as z:
        all_data = {n: z.read(n) for n in z.namelist()}

    stats = {}
    for name in list(all_data.keys()):
        if re.match(r'^xl/worksheets/sheet\d+\.xml$', name):
            new_bytes, removed = _strip_empty_formula_cache(all_data[name])
            if removed:
                all_data[name] = new_bytes
                stats[name] = removed

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name, data in all_data.items():
            zout.writestr(name, data)
    return stats


def check_external_links(path: str | Path) -> dict:
    """诊断 xlsx 里外部链接的状况。"""
    p = Path(path)
    with zipfile.ZipFile(p, 'r') as z:
        names = z.namelist()
        ext_link_files = [n for n in names if n.startswith('xl/externalLinks/')]
        wb_xml = z.read('xl/workbook.xml').decode('utf-8', errors='replace')
        # 检查 sheet*.xml 里的空 <v>
        empty_v_count = 0
        for name in names:
            if re.match(r'^xl/worksheets/sheet\d+\.xml$', name):
                sheet = z.read(name).decode('utf-8', errors='replace')
                empty_v_count += len(_EMPTY_V_AFTER_F.findall(sheet))
    return {
        'file': str(p),
        'ext_link_files': len(ext_link_files),
        'workbook_has_externalReferences': '<externalReferences' in wb_xml,
        'empty_v_after_formula': empty_v_count,
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage:')
        print('  check:  python openpyxl_save_keep_links.py <xlsx>')
        print('  repair: python openpyxl_save_keep_links.py repair <xlsx>')
        sys.exit(1)

    if sys.argv[1] == 'repair' and len(sys.argv) >= 3:
        s = repair_existing_file(sys.argv[2])
        print(f'Repaired: {s}')
    else:
        print(check_external_links(sys.argv[1]))
