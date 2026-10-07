"""
净化产物自检 —— 8 项检查一次跑完，输出 PASS/FAIL。

值比对走 XML 层的缓存值，不用 fastexcel/openpyxl：转值只是删掉 <f> 留下 <v>，
值变没变在 XML 里看得一清二楚。用 Excel 读库反而会因为 dtype/NaN 推断制造几十格
假 differ —— 踩过一次，排查花掉三分钟。
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

SHEET_RE = re.compile(r'xl/worksheets/sheet\d+\.xml$')
EXT_REF_RE = re.compile(r'(?<![\w.])\[\d+\]')
ERROR_TOKENS = ('#REF!', '#VALUE!', '#N/A', '#NAME?', '#DIV/0!', '#NULL!', '#NUM!')

C_RE = re.compile(r'<c\b((?:[^>/]|/(?!>))*)(?:/>|>(.*?)</c>)', re.DOTALL)
R_ATTR = re.compile(r'\br="([^"]*)"')
T_ATTR = re.compile(r'\bt="([^"]*)"')
V_RE = re.compile(r'<v[^>]*/>|<v[^>]*>(.*?)</v>', re.DOTALL)
IS_RE = re.compile(r'<is>(.*?)</is>', re.DOTALL)
T_TEXT_RE = re.compile(r'<t[^>]*>(.*?)</t>', re.DOTALL)
F_SC_RE = re.compile(r'<f\b([^/>]*)/>')
F_CONTENT_RE = re.compile(r'<f\b((?:[^>/]|/(?!>))*)>(.*?)</f>', re.DOTALL)
SI_RE = re.compile(r'si="(\d+)"')


def cell_values(text, shared):
    """{单元格地址: 规范化后的值}。t="str" 转成 inlineStr 后值不变，两边都归一成字符串。"""
    out = {}
    for m in C_RE.finditer(text):
        attrs, body = m.group(1) or '', m.group(2) or ''
        rm = R_ATTR.search(attrs)
        if not rm:
            continue
        tm = T_ATTR.search(attrs)
        ctype = tm.group(1) if tm else 'n'

        if ctype == 'inlineStr':
            im = IS_RE.search(body)
            val = ''.join(T_TEXT_RE.findall(im.group(1))) if im else ''
        else:
            vm = V_RE.search(body)
            if vm is None:
                continue
            val = vm.group(1) or ''
            if ctype == 's':
                try:
                    val = shared[int(val)]
                except (ValueError, IndexError):
                    pass
            elif ctype == 'str':
                pass
            else:
                # 数值文本 "1.0" 与 "1" 是同一个值，规范化掉表示差异
                try:
                    val = repr(float(val))
                except ValueError:
                    pass
        out[rm.group(1)] = val
    return out


def shared_strings(z):
    if 'xl/sharedStrings.xml' not in z.namelist():
        return []
    text = z.read('xl/sharedStrings.xml').decode('utf-8', 'replace')
    return [''.join(T_TEXT_RE.findall(si))
            for si in re.findall(r'<si>(.*?)</si>', text, re.DOTALL)]


def check_values(src, dst, sample):
    with zipfile.ZipFile(src) as za, zipfile.ZipFile(dst) as zb:
        sa, sb = shared_strings(za), shared_strings(zb)
        names = sorted(n for n in za.namelist() if SHEET_RE.match(n))
        if sample:
            names = names[:sample]
        total = bad = 0
        detail = []
        for n in names:
            if n not in zb.namelist():
                detail.append('%s 在产物中缺失' % n)
                bad += 1
                continue
            a = cell_values(za.read(n).decode('utf-8', 'replace'), sa)
            b = cell_values(zb.read(n).decode('utf-8', 'replace'), sb)
            total += len(a)
            for ref, va in a.items():
                vb = b.get(ref)
                if vb != va:
                    bad += 1
                    if len(detail) < 10:
                        detail.append('%s!%s: %r -> %r' % (n.split('/')[-1], ref, va, vb))
    label = '逐格值比对（%d 格%s）' % (total, '，抽查 %d 个 sheet' % sample if sample else '')
    return bad == 0, label, detail


def _parses(z, n):
    try:
        ET.fromstring(z.read(n))
        return True
    except (ET.ParseError, KeyError):
        return False


def check_xml_parse(src, dst):
    """只报告「原来能 parse、现在不能」的 part。

    customXml 之类的 part 常常声明 UTF-8 实为 UTF-16 BOM，原文件就 parse 不了，
    脚本原样转存也不会变好 —— 报出来纯属噪声，上次为这个假阳性排查了三分钟。
    """
    bad = []
    with zipfile.ZipFile(src) as za, zipfile.ZipFile(dst) as zb:
        pre_bad = 0
        for n in zb.namelist():
            if not n.endswith('.xml') and not n.endswith('.rels'):
                continue
            if _parses(zb, n):
                continue
            if n in za.namelist() and not _parses(za, n):
                pre_bad += 1
                continue
            bad.append(n)
    label = '全部 XML parse 通过'
    if pre_bad:
        label += '（%d 个 part 原文件就 parse 不了，已排除）' % pre_bad
    return not bad, label, bad[:10]


def check_names_clean(dst):
    with zipfile.ZipFile(dst) as z:
        wb = z.read('xl/workbook.xml').decode('utf-8', 'replace')
    bad = [m.group(0)[:80] for m in
           re.finditer(r'<definedName\b[^>]*>[^<]*</definedName>', wb)
           if any(tok in m.group(0) for tok in ERROR_TOKENS)]
    return not bad, 'definedName 不含错误标记', bad[:10]


def check_orphan_shared(dst):
    orphans = []
    with zipfile.ZipFile(dst) as z:
        for n in sorted(x for x in z.namelist() if SHEET_RE.match(x)):
            text = z.read(n).decode('utf-8', 'replace')
            masters, slaves = set(), []
            for m in F_CONTENT_RE.finditer(text):
                a = m.group(1) or ''
                si = SI_RE.search(a)
                if si and 't="shared"' in a and 'ref="' in a:
                    masters.add(si.group(1))
            for m in F_SC_RE.finditer(text):
                a = m.group(1) or ''
                si = SI_RE.search(a)
                if si and 't="shared"' in a and 'ref="' not in a:
                    slaves.append(si.group(1))
            for si in slaves:
                if si not in masters:
                    orphans.append('%s si=%s' % (n.split('/')[-1], si))
    return not orphans, '孤立 shared formula = 0', orphans[:10]


def check_str_has_f(dst):
    bad = []
    with zipfile.ZipFile(dst) as z:
        for n in sorted(x for x in z.namelist() if SHEET_RE.match(x)):
            text = z.read(n).decode('utf-8', 'replace')
            for m in C_RE.finditer(text):
                attrs, body = m.group(1) or '', m.group(2) or ''
                if 't="str"' in attrs and '<f' not in body:
                    rm = R_ATTR.search(attrs)
                    bad.append('%s!%s' % (n.split('/')[-1], rm.group(1) if rm else '?'))
    return not bad, 't="str" 单元格都还带 <f>', bad[:10]


def check_links_gone(dst):
    with zipfile.ZipFile(dst) as z:
        parts = [n for n in z.namelist() if 'externalLinks/' in n]
        wb = z.read('xl/workbook.xml').decode('utf-8', 'replace')
        refs = 0
        hits = []
        for n in sorted(x for x in z.namelist() if SHEET_RE.match(x)):
            text = z.read(n).decode('utf-8', 'replace')
            found = EXT_REF_RE.findall(text)
            if found:
                refs += len(found)
                if len(hits) < 5:
                    hits.append('%s x%d' % (n.split('/')[-1], len(found)))
    yield not parts, 'externalLinks 条目数 = 0', ['%d 个残留' % len(parts)] if parts else []
    has = '<externalReferences' in wb
    yield not has, 'workbook.xml 无 <externalReferences>', ['仍存在'] if has else []
    yield refs == 0, '残留 [N] 外部引用 = 0', hits


def probe(path):
    with zipfile.ZipFile(path) as z:
        wb = z.read('xl/workbook.xml').decode('utf-8', 'replace')
        return {
            'extParts': len([n for n in z.namelist() if 'externalLinks' in n]),
            'extRefs': '<externalReferences' in wb,
            'definedNames': len(re.findall(r'<definedName\b', wb)),
            'bracketRefs': sum(
                len(EXT_REF_RE.findall(z.read(n).decode('utf-8', 'replace')))
                for n in z.namelist() if SHEET_RE.match(n)),
        }


def main():
    ap = argparse.ArgumentParser(description='Verify a purged xlsx against its source.')
    ap.add_argument('source')
    ap.add_argument('output')
    ap.add_argument('--mode', choices=('names', 'links', 'all'), default='all',
                    help='跑净化时用的 mode，决定要不要查外链三项')
    ap.add_argument('--sample', type=int, default=0,
                    help='只比对前 N 个 sheet（默认 0 = 全表）')
    args = ap.parse_args()

    for p in (args.source, args.output):
        if not os.path.exists(p):
            sys.exit('not found: %s' % p)

    before, after = probe(args.source), probe(args.output)
    print('Verify: %s -> %s' % (os.path.basename(args.source),
                                os.path.basename(args.output)))
    print('  before: definedNames=%d extParts=%d [N]refs=%d extRefs=%s'
          % (before['definedNames'], before['extParts'],
             before['bracketRefs'], before['extRefs']))
    print('  after : definedNames=%d extParts=%d [N]refs=%d extRefs=%s'
          % (after['definedNames'], after['extParts'],
             after['bracketRefs'], after['extRefs']))

    checks = [check_values(args.source, args.output, args.sample),
              check_xml_parse(args.source, args.output),
              check_names_clean(args.output),
              check_orphan_shared(args.output),
              check_str_has_f(args.output)]
    if args.mode in ('links', 'all'):
        checks.extend(check_links_gone(args.output))

    failed = 0
    for i, (ok, label, detail) in enumerate(checks, 1):
        print('  [%s] %d. %s' % ('PASS' if ok else 'FAIL', i, label))
        if not ok:
            failed += 1
            for d in detail:
                print('         %s' % d)

    print('  %s (%d/%d)' % ('ALL PASS' if not failed else '%d FAILED' % failed,
                            len(checks) - failed, len(checks)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
