"""
xlsx-purge — 在 ZIP/XML 层净化 xlsx，不依赖 Excel COM。

净化名称和断外链是两件事，用 --mode 分开：
  names  只清名称：坏的、垃圾的、没人引用的。指向外表但在用的名称原样保留，
         公式一律不动 —— 有时候就是需要引用外表
  links  只断外链：外部名称全删；引用外链或外部名称的公式先转成值把数据保住，
         再清 externalLinks / rels / Content_Types / calcChain 残留
  all    两者都做（默认）

性能：旧版有两处 O(n^2) —— 每条待删公式切一次尾串 text[end:]，每个替换重建一次
整串。6MB 的 sheet 配上万条外链公式要跑一分钟。现在定位用 find(pos)、替换攒成
ops 后一次 join，全程线性。
"""
import argparse
import os
import re
import sys
import zipfile
from collections import deque

SHEET_RE = re.compile(r'xl/worksheets/sheet\d+\.xml$')

# sheet 之外还会引用定义名称的 part。只读不改，用来补全在用判定 —— 漏扫这里
# 就会把透视表/图表正在用的名称当孤名删掉。pivotCacheRecords 不含名称引用且
# 动辄上百 MB，不在此列
REF_PART_RE = re.compile(
    r'xl/(?:pivotCache/pivotCacheDefinition\d+\.xml'
    r'|charts?/chart\d+\.xml'
    r'|tables/table\d+\.xml'
    r'|queryTables/queryTable\d+\.xml'
    r'|connections\.xml)$')

# pivotCache 的 <worksheetSource name="X"/>、图表的 <c:f>、表格的计算列公式。
# worksheetSource 的 name 是直接的名称引用，不是公式，不能走标识符扫描
SOURCE_NAME_RE = re.compile(r'<(?:\w+:)?worksheetSource\b[^>]*\bname="([^"]*)"')
FORMULA_TAG_RE = re.compile(
    r'<(?:\w+:)?(?:f|calculatedColumnFormula|totalsRowFormula)\b[^>]*>(.*?)'
    r'</(?:\w+:)?(?:f|calculatedColumnFormula|totalsRowFormula)>', re.DOTALL)

# [1]Sheet1!A1 里的 [1] 是 externalLink 索引。前置断言排掉 Table1[1] 这类结构化
# 表引用 —— 把它当外链会连正常公式一起粘死
EXT_REF_RE = re.compile(r'(?<![\w.])\[\d+\]')

ERROR_TOKENS = ('#REF!', '#VALUE!', '#N/A', '#NAME?', '#DIV/0!', '#NULL!', '#NUM!')

# 自闭合 <f .../>：[^/>]* 遇到 / 就停，后面必须紧跟 />
F_SC_RE = re.compile(r'<f\b([^/>]*)/>')
# 带内容的 <f ...>...</f>。属性里允许出现 / 但不能是收尾的 />，否则 <f t="shared"
# si="17"/> 会被当成开标签，(.*?)</f> 一路吞到下一个单元格，把中间夹着的公式整段
# 吃掉 —— 光在结果里跳过自闭合位置没用，finditer 已经把那段文本消耗掉了
F_CONTENT_RE = re.compile(r'<f\b((?:[^>/]|/(?!>))*)>(.*?)</f>', re.DOTALL)

DN_RE = re.compile(r'<definedName\s+([^>]*?)(?:/>|>(.*?)</definedName>)', re.DOTALL)
ATTR_NAME = re.compile(r'name="([^"]*)"')
SI_RE = re.compile(r'si="(\d+)"')
# 空字符串结果存成自闭合的 <v/>，只认 <v>...</v> 会把这一格当成「没有值」清空
V_RE = re.compile(r'<v[^>]*/>|<v[^>]*>(.*?)</v>', re.DOTALL)

# 定义名称不允许长得像单元格引用，Excel 建名称时就拦掉了。反过来说公式里的
# AA:AA、$AB$24 一定是引用不是名称 —— 不排掉就会拿列标去撞同名的待删名称，
# 把根本不碰外链的公式一起粘死
CELL_REF_RE = re.compile(r'^([A-Za-z]{1,3})(\d{1,7})?$')
COL_MAX = 16384
ROW_MAX = 1048576


def looks_like_cell_ref(name):
    m = CELL_REF_RE.match(name)
    if not m:
        return False
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    if not 1 <= col <= COL_MAX:
        return False
    row = m.group(2)
    return row is None or 1 <= int(row) <= ROW_MAX

# \w 而不是 [A-Za-z0-9_]。定义名称可以是中文、泰文、韩文，用 ASCII 字符类会让
# 「B价」这种名称永远匹配不上，被当成没人用的删掉 —— 静默的数据损坏
IDENT_RE = re.compile(r'[\w.\\]+', re.UNICODE)

# sheet XML 里字符串常量存成 &quot;...&quot;，只认裸引号的话常量内容会被当标识符扫
QUOTED_RE = re.compile(
    r"'(?:[^']|'')*'"
    r'|"(?:[^"]|"")*"'
    r'|&quot;(?:(?!&quot;).)*&quot;',
    re.DOTALL)

BUILTIN_SHORT = {'Print_Area', 'Print_Titles', '_FilterDatabase', 'FilterDatabase',
                 'Criteria', 'Extract', 'Database', 'Consolidate_Area', 'Sheet_Title'}

WB_EXTS = ('.xls', '.xlsx', '.xlsm', '.xlsb', '.xlt', '.xltx', '.xltm',
           '.csv', '.et', '.ett', '.dbf')


# --------------------------------------------------------------------------
# 名称判定
# --------------------------------------------------------------------------

def is_never_delete(name):
    # _xlfn 是当前版本不认识的新函数占位，_xlpm 是 LAMBDA 参数，_xlcn 归数据连接所有。
    # 它们的 body 正常情况下就是 #NAME?，删掉直接破坏公式
    return name.startswith(('_xlfn', '_xlpm', '_xlcn'))


def is_builtin(name):
    return name.startswith('_xlnm') or name in BUILTIN_SHORT


def is_skip_name(name):
    # 长得像单元格引用或纯数字的名称一律留着不动，也不拿它去匹配公式：
    # 公式里满地都是 AA:AA、$B$3，撞上就会误伤
    return name.isdigit() or looks_like_cell_ref(name)


def is_junk_body(body):
    # body 里出现字面 &quot; 实体说明这条名称是从 HTML 粘过来的残渣，真 RefersTo 不长这样
    return (not body) or ('&quot;' in body)


def is_bad_body(body):
    return any(tok in body for tok in ERROR_TOKENS)


def _bracket_tokens(body):
    i = 0
    while True:
        i = body.find('[', i)
        if i < 0:
            return
        j = body.find(']', i + 1)
        if j < 0:
            return
        yield body[i + 1:j]
        i = j + 1


def is_external_body(body):
    """指向别的文件才算外部。Table1[列名] 这类结构化引用不算。"""
    if ':\\' in body or '\\\\' in body or '://' in body:
        return True
    for tok in _bracket_tokens(body):
        if tok.isdigit():
            return True
        if tok.lower().endswith(WB_EXTS):
            return True
        if '\\' in tok or ':' in tok:
            return True
    return False


def scan_identifiers(text):
    if not text:
        return
    if "'" in text or '"' in text or '&quot;' in text:
        text = QUOTED_RE.sub("''", text)
    for m in IDENT_RE.finditer(text):
        end = m.end()
        # 紧跟左括号的是函数调用不是名称引用。工作簿里存在名为 IF 的垃圾名称时，
        # 每个 =IF(...) 都会把它判成在用，永远删不掉
        if end < len(text) and text[end] == '(':
            continue
        yield m.group()


def match_names(text, lookup):
    hits = set()
    for ident in scan_identifiers(text):
        key = lookup.get(ident.lower())
        if key:
            hits.add(key)
    return hits


# --------------------------------------------------------------------------
# 公式转值
# --------------------------------------------------------------------------

def iter_f_elements(text):
    """一次切出全部 <f>，自闭合的和带内容的分开识别。"""
    sc_positions = set()
    entries = []
    for m in F_SC_RE.finditer(text):
        attrs = m.group(1) or ''
        sc_positions.add(m.start())
        entries.append(_f_entry(m.start(), m.end(), attrs, ''))
    for m in F_CONTENT_RE.finditer(text):
        if m.start() in sc_positions:
            continue
        entries.append(_f_entry(m.start(), m.end(), m.group(1) or '', m.group(2) or ''))
    return entries


def _f_entry(start, end, attrs, content):
    shared = 't="shared"' in attrs
    si = SI_RE.search(attrs)
    return {
        'start': start, 'end': end, 'attrs': attrs, 'content': content,
        'shared': shared,
        'master': shared and 'ref="' in attrs,
        'slave': shared and 'ref="' not in attrs,
        'si': si.group(1) if si else '',
    }


def formula_needs_flatten(content, doomed):
    if EXT_REF_RE.search(content):
        return True
    if not doomed:
        return False
    for ident in scan_identifiers(content):
        if ident.lower() in doomed:
            return True
    return False


def apply_ops(text, ops):
    """ops 为互不重叠的 (start, end, replacement)，一次拼出结果，不逐个重建整串。"""
    if not ops:
        return text
    ops.sort(key=lambda o: o[0])
    out = []
    pos = 0
    for start, end, rep in ops:
        out.append(text[pos:start])
        out.append(rep)
        pos = end
    out.append(text[pos:])
    return ''.join(out)


def _cell_op(text, entry):
    """把一个公式单元格改成静态值。返回 (start, end, replacement)。"""
    f_start, f_end = entry['start'], entry['end']

    c_start = text.rfind('<c', 0, f_start)
    tag_end = text.find('>', c_start) if c_start >= 0 else -1
    c_open = text[c_start:tag_end + 1] if tag_end >= 0 else ''

    c_close = text.find('</c>', f_end)
    tail = text[f_end:c_close] if c_close >= 0 else ''

    # t="str" 是「公式返回字符串」。删掉 <f> 后这个属性就不合法了，Excel 会报修复，
    # 必须改写成 inlineStr 才留得住那串文本
    if 't="str"' in c_open and c_close >= 0:
        vm = V_RE.search(tail)
        if vm is None:
            # 连缓存值都没有，留个不带类型的空格子
            return (c_start, c_close + 4, c_open.replace(' t="str"', '') + '</c>')
        # 公式返回空串时 <v/> 里没有内容，仍要写成空的 inlineStr，
        # 否则这一格从「空字符串」变成「真空单元格」
        return (c_start, c_close + 4,
                c_open.replace('t="str"', 't="inlineStr"')
                + '<is><t xml:space="preserve">%s</t></is>' % (vm.group(1) or '')
                + '</c>')

    # 其余类型（数值、布尔、错误值）保留缓存的 <v> 即可
    return (f_start, f_end, '' if V_RE.search(tail) else '<v>0</v>')


def flatten_formulas(text, doomed):
    """把引用外链或引用待删名称的公式转成值。单元格本身从不删除。"""
    entries = iter_f_elements(text)
    if not entries:
        return text, 0, 0

    doomed_masters = set()
    for e in entries:
        e['hit'] = formula_needs_flatten(e['content'], doomed) if e['content'] else False
        if e['hit'] and e['master']:
            doomed_masters.add(e['si'])

    converted = 0
    orphans = 0
    ops = []
    for e in entries:
        if e['hit']:
            pass
        elif e['slave'] and e['si'] in doomed_masters:
            # master 被转值后 slave 就成了没有主的孤儿，Excel 打开会报修复
            e['hit'] = True
            orphans += 1
        else:
            continue
        ops.append(_cell_op(text, e))
        converted += 1

    return apply_ops(text, ops), converted, orphans


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def parse_defined_names(wb_text):
    entries = []
    for m in DN_RE.finditer(wb_text):
        attrs = m.group(1)
        nm = ATTR_NAME.search(attrs)
        if not nm:
            continue
        body = (m.group(2) or '').strip()
        entries.append({
            'name': nm.group(1),
            'body': body,
            'span': m.span(),
            'external': is_external_body(body),
        })
    return entries


def build_lookup(entries):
    """只有干净的名称才进 lookup —— 坏的和外部的本来就要删，不参与在用判定。"""
    lookup = {}
    for e in entries:
        name, body = e['name'], e['body']
        if is_never_delete(name) or is_builtin(name) or is_skip_name(name):
            continue
        if is_junk_body(body) or is_bad_body(body) or e['external']:
            continue
        lookup.setdefault(name.lower(), name.lower())
    return lookup


def collect_live(sheets, lookup, ref_parts=None):
    """扫公式、数据验证、条件格式，收集被引用到的名称。

    ref_parts 是 sheet 之外还会引用名称的 part（pivotCache / chart / table）。
    透视表的数据源是 <worksheetSource name="X"/>，那是个直接的名称引用，不出现
    在任何公式里 —— 不扫它，透视表正在用的名称会被判成孤名删掉，文件打开后
    透视表就失去数据源了。
    """
    live = set()
    if not lookup:
        return live
    for text in sheets.values():
        for e in iter_f_elements(text):
            if e['content']:
                live |= match_names(e['content'], lookup)
        for tag in ('formula1', 'formula2', 'formula'):
            for m in re.finditer(r'<%s>(.*?)</%s>' % (tag, tag), text, re.DOTALL):
                live |= match_names(m.group(1), lookup)
    for text in (ref_parts or {}).values():
        for m in SOURCE_NAME_RE.finditer(text):
            key = lookup.get(m.group(1).lower())
            if key:
                live.add(key)
        for m in FORMULA_TAG_RE.finditer(text):
            live |= match_names(m.group(1), lookup)
    return live


def propagate_live(live, entries, lookup):
    """名称链：在用名称引用到的名称同样算在用。"""
    body_by_name = {}
    for e in entries:
        body_by_name.setdefault(e['name'].lower(), []).append(e['body'])

    pending = deque(live)
    while pending:
        for body in body_by_name.get(pending.popleft(), []):
            for hit in match_names(body, lookup):
                if hit not in live:
                    live.add(hit)
                    pending.append(hit)


def propagate_external(entries):
    """
    名称 A 的 body 引用了指向外表的名称 B，断链删掉 B 之后 A 一样会坏。
    外部性必须沿引用链传下去，否则清完外链还剩一批 #NAME?。
    """
    all_names = {}
    for e in entries:
        all_names.setdefault(e['name'].lower(), e['name'].lower())

    referrers = {}
    external = set()
    queue = deque()
    for e in entries:
        if e['external']:
            key = e['name'].lower()
            if key not in external:
                external.add(key)
                queue.append(key)
        for hit in match_names(e['body'], all_names):
            referrers.setdefault(hit, []).append(e)

    while queue:
        for e in referrers.get(queue.popleft(), []):
            if e['external']:
                continue
            e['external'] = True
            key = e['name'].lower()
            if key not in external:
                external.add(key)
                queue.append(key)


def decide(entry, live, do_names, do_links):
    name, body = entry['name'], entry['body']
    if is_never_delete(name):
        return False, 'kept_never'
    if is_builtin(name):
        # 打印区域、打印标题这些完好时保留，坏掉或指向外表时照删
        if is_bad_body(body) or is_junk_body(body):
            return True, 'broken'
        if entry['external'] and do_links:
            return True, 'external'
        return False, 'kept_builtin'
    if is_junk_body(body):
        return True, 'junk'
    if is_bad_body(body):
        return True, 'broken'
    if entry['external']:
        if do_links:
            return True, 'external'
        if do_names and not is_skip_name(name) and name.lower() not in live:
            return True, 'unused_external'
        return False, 'kept_external_used'
    if is_skip_name(name):
        return False, 'kept_skip'
    if name.lower() in live:
        return False, 'kept_used'
    if do_names:
        return True, 'unused'
    return False, 'kept_unused'


def purge(input_path, output_path, mode='all', quiet=False):
    do_names = mode in ('names', 'all')
    do_links = mode in ('links', 'all')

    stats = {'mode': mode, 'ext_links': 0, 'cells': 0, 'orphans': 0, 'calcchain': 0,
             'rels': 0, 'names_removed': 0,
             'broken': 0, 'external': 0, 'junk': 0, 'unused': 0, 'unused_external': 0,
             'kept_used': 0, 'kept_external_used': 0, 'kept_builtin': 0,
             'kept_never': 0, 'kept_skip': 0, 'kept_unused': 0}

    def say(msg):
        if not quiet:
            print(msg)

    with zipfile.ZipFile(input_path, 'r') as zin:
        namelist = zin.namelist()
        wb_text = zin.read('xl/workbook.xml').decode('utf-8', 'replace')
        sheets = {n: zin.read(n).decode('utf-8', 'replace')
                  for n in namelist if SHEET_RE.match(n)}
        ref_parts = {n: zin.read(n).decode('utf-8', 'replace')
                     for n in namelist if REF_PART_RE.match(n)}

        entries = parse_defined_names(wb_text)
        propagate_external(entries)
        lookup = build_lookup(entries)
        live = collect_live(sheets, lookup, ref_parts)
        propagate_live(live, entries, lookup)

        for e in entries:
            e['delete'], reason = decide(e, live, do_names, do_links)
            stats[reason] = stats.get(reason, 0) + 1
            if e['delete']:
                stats['names_removed'] += 1

        # 这些名称一删，引用它们的公式就变 #NAME?。断链前先把公式转成值，
        # 单元格里缓存的最后一次计算结果才留得住。没人引用的名称不进这个集合 ——
        # 万一在用判定漏了，也不至于大面积粘死正常公式
        doomed = set()
        if do_links:
            for e in entries:
                if not e['delete']:
                    continue
                if is_skip_name(e['name']):
                    continue
                if e['external'] or is_bad_body(e['body']) or is_junk_body(e['body']):
                    doomed.add(e['name'].lower())

        if do_links:
            for zname in sheets:
                new_text, converted, orphans = flatten_formulas(sheets[zname], doomed)
                sheets[zname] = new_text
                stats['cells'] += converted
                stats['orphans'] += orphans
            say('  Cells flattened: %d (orphan shared formulas: %d)'
                % (stats['cells'], stats['orphans']))

        wb_text = apply_ops(wb_text, [(e['span'][0], e['span'][1], '')
                                      for e in entries if e['delete']])
        wb_text = re.sub(r'<definedNames[^>]*?>\s*</definedNames>', '', wb_text)
        if do_links:
            wb_text = re.sub(r'<externalReferences[^>]*?/>', '', wb_text)
            wb_text = re.sub(r'<externalReferences>.*?</externalReferences>', '',
                             wb_text, flags=re.DOTALL)

        say('  Names removed: %d (broken=%d, external=%d, junk=%d, unused=%d, unused_external=%d)'
            % (stats['names_removed'], stats['broken'], stats['external'],
               stats['junk'], stats['unused'], stats['unused_external']))
        say('  Names kept: used=%d, external_in_use=%d, builtin=%d, placeholder=%d, ambiguous=%d, unused=%d'
            % (stats['kept_used'], stats['kept_external_used'], stats['kept_builtin'],
               stats['kept_never'], stats['kept_skip'], stats['kept_unused']))

        drop_calcchain = do_links and stats['cells'] > 0

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for zname in namelist:
                if do_links and 'externalLinks/' in zname:
                    stats['ext_links'] += 1
                    continue
                if drop_calcchain and zname == 'xl/calcChain.xml':
                    stats['calcchain'] = 1
                    continue

                if zname == 'xl/workbook.xml':
                    zout.writestr(zname, wb_text.encode('utf-8'))
                elif zname in sheets:
                    zout.writestr(zname, sheets[zname].encode('utf-8'))
                elif zname.endswith('.rels'):
                    text = zin.read(zname).decode('utf-8', 'replace')
                    if do_links:
                        new_text = re.sub(
                            r'<Relationship[^>]*?Type="[^"]*externalLink[^"]*"[^>]*?/>',
                            '', text)
                        if new_text != text:
                            stats['rels'] += 1
                            text = new_text
                    zout.writestr(zname, text.encode('utf-8'))
                elif zname == '[Content_Types].xml' and do_links:
                    text = zin.read(zname).decode('utf-8', 'replace')
                    text = re.sub(
                        r'<Override[^>]*?PartName="/xl/externalLinks/[^"]*"[^>]*?/>',
                        '', text)
                    zout.writestr(zname, text.encode('utf-8'))
                else:
                    zout.writestr(zname, zin.read(zname))

    if do_links:
        say('  External link parts dropped: %d' % stats['ext_links'])
    return stats


def main():
    ap = argparse.ArgumentParser(
        description='Purge xlsx: defined names, external links, ZIP leftovers.')
    ap.add_argument('input')
    ap.add_argument('output', nargs='?')
    ap.add_argument('--mode', choices=('names', 'links', 'all'), default='all',
                    help='names=只清名称不动公式; links=只断外链; all=两者都做（默认）')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    output = args.output or re.sub(r'\.xlsx$', '', args.input, flags=re.I) + '_clean.xlsx'
    if os.path.abspath(output) == os.path.abspath(args.input):
        sys.exit('output must differ from input')

    print('Purging (%s): %s' % (args.mode, os.path.basename(args.input)))
    stats = purge(args.input, output, args.mode, args.quiet)

    orig = os.path.getsize(args.input)
    new = os.path.getsize(output)
    print('Size: %.0fKB -> %.0fKB (%.1f%% reduced)'
          % (orig / 1024, new / 1024, (1 - new / orig) * 100))
    print('Output: %s' % output)
    return stats


if __name__ == '__main__':
    main()
