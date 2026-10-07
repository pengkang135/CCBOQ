#!/usr/bin/env python
"""
源文件探测 —— 填报第一步跑这个，别自己现写探测代码。

它回答三个问题：
  1. 这批文件里谁是**数据源**（结构化、精确值）、谁是**佐证源**（扫描件，只用来核对）
  2. PDF 有没有文本层（有就别走 OCR，直接抽；没有才渲染）
  3. 日期线索在哪 —— 报价单常常没有日期栏，文档元数据里的 dcterms:modified 与
     lastModifiedBy 是唯一兜底，且 lastModifiedBy 与签字人一致时可采信

    python probe_source.py <文件或目录>

输出人读的报告 + 末尾一行 JSON（便于程序消费）。
"""
import sys, os, json, zipfile, re
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

DATA_EXT = {'.xlsx', '.xlsm', '.xls', '.csv'}
DOC_EXT = {'.pdf'}
WORD_EXT = {'.docx', '.docm'}
WORD_LEGACY_EXT = {'.doc'}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}

# 表头命中其一就当疑似价格表。宁可多报——报错了填报员扫一眼就排除，漏报了整张表没人看
PRICE_HEAD_HINTS = ('单价', '综合单价', '金额', '合价', '价格', '税',
                    'rate', 'price', 'amount', 'cost', 'sum', 'total')
# 暂定金额类表格不入库（同「整项/包干价不入库」），探测阶段先标出来
PROVISIONAL_HINTS = ('暂定', '暂列', '备用金', 'provisional', 'contingency', 'prime cost', 'p.c.')

# 我们自己往源目录里放的产出物，探测时要排除 —— 否则上传报告会被当成待处理源文件
OUTPUT_EXT = {'.html', '.htm', '.md', '.json'}
OUTPUT_NAME_HINTS = ('_上传报告', '_价格表', 'recall-report', 'review-notes',
                     'analysis-report', 'upload-report', 'manifest')


def probe_pdf(p):
    info = {'kind': 'pdf', 'pages': None, 'textChars': 0, 'hasTextLayer': False, 'meta': {}}
    try:
        import fitz
    except ImportError:
        info['error'] = 'PyMuPDF (fitz) 未安装'
        return info
    try:
        doc = fitz.open(p)
        info['pages'] = len(doc)
        text = "".join(pg.get_text() for pg in doc)
        info['textChars'] = len(text.strip())
        info['hasTextLayer'] = info['textChars'] > 0
        md = doc.metadata or {}
        for k in ('creationDate', 'modDate', 'author', 'producer', 'title'):
            if md.get(k):
                info['meta'][k] = md[k]
        doc.close()
    except Exception as e:
        info['error'] = f'{type(e).__name__}: {e}'
    return info


def read_ooxml_meta(p):
    """OOXML core 属性直接从 zip 读，不依赖 openpyxl。xlsx 与 docx 同为 OOXML，这段共用。"""
    meta = {}
    try:
        with zipfile.ZipFile(p) as z:
            if 'docProps/core.xml' in z.namelist():
                xml = z.read('docProps/core.xml').decode('utf-8', 'ignore')
                for tag in ('dcterms:modified', 'dcterms:created', 'cp:lastModifiedBy',
                            'dc:creator', 'cp:lastPrinted', 'dc:title'):
                    m = re.search(rf'<{tag}[^>]*>([^<]+)</{tag}>', xml)
                    if m:
                        meta[tag] = m.group(1)
    except Exception as e:
        meta['_error'] = f'{type(e).__name__}: {e}'
    return meta


def probe_xlsx(p):
    """读 sheet 概况与 OOXML 核心属性。元数据里的日期线索是报价单无日期栏时的唯一兜底。"""
    info = {'kind': 'excel', 'sheets': [], 'meta': {}}
    try:
        import fastexcel
        wb = fastexcel.read_excel(str(p))
        for name in wb.sheet_names:
            sh = wb.load_sheet_by_name(name)
            info['sheets'].append({'name': name, 'height': sh.height, 'width': sh.width})
    except Exception as e:
        info['sheetError'] = f'{type(e).__name__}: {e}'

    info['meta'] = read_ooxml_meta(p)
    return info


def probe_docx(p):
    """列出全部表格与形态。合同类文档的报价表散在条款正文里，表格清单是定位它的唯一线索。"""
    info = {'kind': 'word', 'paragraphs': 0, 'tables': [], 'meta': {}}
    try:
        import docx
    except ImportError:
        info['error'] = 'python-docx 未安装'
        return info
    try:
        d = docx.Document(str(p))
        info['paragraphs'] = len(d.paragraphs)
        for i, t in enumerate(d.tables):
            head = [c.text.strip() for c in t.rows[0].cells] if t.rows else []
            # 暂定金额常写在描述列而非表头，整行扫；限前 60 行，够判定又不至于拖慢大表
            blob = ' '.join(c.text for r in t.rows[:60] for c in r.cells).lower()
            info['tables'].append({
                'index': i,
                'rows': len(t.rows),
                'cols': len(t.columns),
                'header': head[:8],
                'priceLike': any(h in ' '.join(head).lower() for h in PRICE_HEAD_HINTS),
                'provisional': any(h in blob for h in PROVISIONAL_HINTS),
            })
    except Exception as e:
        info['error'] = f'{type(e).__name__}: {e}'
    info['meta'] = read_ooxml_meta(p)
    return info


def probe_image(p):
    info = {'kind': 'image'}
    try:
        from PIL import Image
        with Image.open(p) as im:
            info['size'] = f'{im.width}x{im.height}'
            info['mode'] = im.mode
    except Exception as e:
        info['error'] = f'{type(e).__name__}: {e}'
    return info


def probe(p):
    ext = p.suffix.lower()
    if ext in DOC_EXT:
        return probe_pdf(p)
    if ext in DATA_EXT:
        return probe_xlsx(p) if ext != '.csv' else {'kind': 'csv'}
    if ext in WORD_EXT:
        return probe_docx(p)
    if ext in WORD_LEGACY_EXT:
        return {'kind': 'word_legacy'}
    if ext in IMG_EXT:
        return probe_image(p)
    return {'kind': 'other'}


def suggest_route(rec):
    k, ext = rec['kind'], rec['ext']
    if k == 'excel' or ext == '.csv':
        return '1 数据源', 'fastexcel 读值。不要用 openpyxl 读值（慢 9-16 倍）'
    if k == 'pdf':
        if rec.get('hasTextLayer'):
            return '1 数据源', 'pdfplumber 抽文本，不要 OCR'
        return '2/3 佐证源', 'fitz 渲染 200dpi → rapidocr 粗读定位 → 关键区域裁图核验（extract_region.py）'
    if k == 'word':
        tabs = rec.get('tables', [])
        n = sum(1 for t in tabs if t['priceLike'])
        return '1 数据源', (f'python-docx 按 doc.tables 单元格坐标取数'
                            f'（{len(tabs)} 张表，{n} 张疑似价格表）。'
                            f'不要转 Markdown 再解析——合并单元格会被摊平、跨页续表会拼错行')
    if k == 'word_legacy':
        return '-', '老 .doc 格式 python-docx 读不了 → 先 pandoc 转 .docx，别硬啃'
    if k == 'image':
        return '2/3 佐证源', 'rapidocr 粗读定位 → 关键区域裁图用 paddleocr'
    return '-', '未知类型，人工确认'


def main():
    if len(sys.argv) < 2:
        print('用法: python probe_source.py <文件或目录>')
        sys.exit(2)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f'找不到: {target}')
        sys.exit(2)

    files = []
    if target.is_dir():
        for root, _dirs, names in os.walk(target):
            # 跳过我们自己产出的中间件目录，只看原件
            if any(part in ('temp', 'raw', '_converted') for part in Path(root).parts):
                continue
            for n in sorted(names):
                if n.startswith('~$'):
                    continue
                low = n.lower()
                if Path(low).suffix in OUTPUT_EXT or any(h.lower() in low for h in OUTPUT_NAME_HINTS):
                    continue  # 我们自己的产出物，不是待处理源文件
                files.append(Path(root) / n)
    else:
        files = [target]

    records = []
    for f in files:
        rec = {'path': str(f), 'name': f.name, 'ext': f.suffix.lower(),
               'sizeKB': round(f.stat().st_size / 1024)}
        rec.update(probe(f))
        rec['route'], rec['how'] = suggest_route(rec)
        records.append(rec)

    print(f'探测 {len(records)} 个文件：{target}\n')
    for r in records:
        print(f"  {r['name']}")
        print(f"    类型 {r['kind']}  {r['sizeKB']}KB", end='')
        if r['kind'] == 'pdf':
            print(f"  {r.get('pages')} 页  文本层 {'有 (' + str(r['textChars']) + ' 字符)' if r.get('hasTextLayer') else '无 → 扫描件'}")
        elif r['kind'] == 'excel':
            sh = ', '.join(f"{s['name']}({s['height']}×{s['width']})" for s in r.get('sheets', []))
            print(f"  sheets: {sh or '读取失败'}")
        elif r['kind'] == 'word':
            tabs = r.get('tables', [])
            print(f"  {r.get('paragraphs')} 段落  {len(tabs)} 张表")
            for t in tabs:
                mark = '价格表?' if t['priceLike'] else '       '
                flag = '  [暂定金额类，不入库]' if t['provisional'] else ''
                head = ' | '.join(h for h in t['header'] if h)[:70]
                print(f"      {mark} #{t['index']} {t['rows']}×{t['cols']}  {head}{flag}")
        elif r['kind'] == 'image':
            print(f"  {r.get('size', '?')}")
        else:
            print()
        print(f"    → {r['route']}：{r['how']}")
        if r.get('meta'):
            print(f"    元数据: " + '  '.join(f'{k}={v}' for k, v in r['meta'].items()))
        if r.get('error'):
            print(f"    [!] {r['error']}")
        print()

    # 同内容多格式配对。不能只按 stem 全等 —— 实际文件名常带编号前缀
    # （`3.1.1_Concrete_Schedule of Prices - BOQ.xlsx` 与
    #  `Concrete_Schedule of Prices - BOQ.pdf` 是同一份东西），所以用子串包含判断
    def same_content(a, b):
        sa, sb = Path(a['name']).stem.lower(), Path(b['name']).stem.lower()
        short, long_ = sorted((sa, sb), key=len)
        return len(short) >= 8 and short in long_

    groups, used = [], set()
    for i, r in enumerate(records):
        if i in used:
            continue
        grp = [r]
        used.add(i)
        for j in range(i + 1, len(records)):
            if j not in used and same_content(r, records[j]):
                grp.append(records[j])
                used.add(j)
        if len(grp) > 1:
            groups.append(grp)

    data_srcs = [r for r in records if r['route'].startswith('1')]
    if groups:
        print('同内容多格式（不要两份都全量提取）：')
        for grp in groups:
            print(f"  {' + '.join(r['name'] for r in grp)}")
            primary = next((r['name'] for r in grp if r['route'].startswith('1')), None)
            print(f"    数据源取 {primary or '（无结构化源，只能 OCR）'}，其余仅作佐证")
        print()

    # 日期线索汇总
    date_hints = []
    for r in records:
        m = r.get('meta', {})
        if m.get('dcterms:modified'):
            date_hints.append((r['name'], m.get('dcterms:modified'), m.get('cp:lastModifiedBy', ''), m.get('cp:lastPrinted', '')))
    if date_hints:
        print('日期线索（源文件无日期栏时的兜底，采信后必须标 uncertain）：')
        for name, mod, by, printed in date_hints:
            print(f"  {name}: modified={mod}  lastModifiedBy={by or '—'}  lastPrinted={printed or '—'}")
        print('  若 lastModifiedBy 与报价签字人一致，modified 可作为定稿日期采信\n')

    print('结论：数据源 ' + (', '.join(r['name'] for r in data_srcs) or '无（只能走 OCR，价格需逐条裁图核验）'))
    print('\n--- JSON ---')
    print(json.dumps({'target': str(target), 'files': records}, ensure_ascii=False))


if __name__ == '__main__':
    main()
