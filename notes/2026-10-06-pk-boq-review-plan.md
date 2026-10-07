# pk-boq-review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `pk-boq-review` 技能：一条命令把 BOQ xlsx 生成为带审阅意见列的 HTML 审阅稿，用户改完保存，AI 一条命令读回完整的修改清单与意见。

**Architecture:** `review_html.py` 读 xlsx（全共享读字节 + openpyxl 取值与样式），渲染单文件 HTML，修改与意见由页内 JS 记录并在保存时写进内嵌的 `<script type="application/json" id="review-data">`。`review_read.py` 解析该数据块（旧格式退回比对 `data-orig`），校验源文件签名，变动时按编号重新定位。技能文档描述"生成 → 审阅保存 → 读回改版"循环。

**Tech Stack:** Python 3.13、openpyxl、pytest；原生 JS（File System Access API，退回下载）。

**Spec:** `C:\Users\Kevin\albedo-cfg\notes\2026-10-06-pk-boq-review-design.md`

## Global Constraints

- 技能模板目录：`C:\Users\Kevin\albedo-cfg\claude\skills\pk-boq-review\`；运行副本：`C:\Users\Kevin\.claude\skills\pk-boq-review\`（Task 3 复制同步）。
- 显示列恰为：行号、编号、英文描述、中文描述、单位、审阅意见（最右）；不显示工程量列。
- 数据块恰为 `<script type="application/json" id="review-data">`，JSON 中 `</` 一律写成 `<\/`。
- 审阅稿默认文件名：`<源文件名去扩展名>_审阅稿.html`，与源文件同目录。
- 工具栏恰为 4 个按钮：保存、复制变更清单、重置列宽、清除全部编辑。
- 禁止 Excel COM；openpyxl 只用于读（`data_only=True`），不保存任何 xlsx。
- 文本比较规范化：`\r\n`/`\r` → `\n`，不换行空格 → 空格，去掉行尾空白与首尾空白。
- 不写 emoji；默认不写注释，除非 WHY 不显而易见。
- 不做 git 提交：albedo-cfg 有他人未提交改动，提交由用户决定；各 Task 不含 commit 步骤。
- 临时文件放会话 scratchpad：`C:\Users\Kevin\AppData\Local\Temp\claude\C--Users-Kevin\8283d867-f37a-4f07-b48c-6fba11bfd47f\scratchpad\`。

## Review Focus

- 单元格含 `<`、`&`、引号、`</script>`：HTML 与数据块都不能被截断或注入 —— Task 1 `test_escaping_newline_formula`、Task 2 `test_roundtrip`（新值含 `</script>`）。
- 单元格含换行（Alt+Enter）：显示保留换行、比较不产生假修改 —— Task 1 `test_escaping_newline_formula`、Task 2 `test_roundtrip`。
- 编号或单位列是公式：显示缓存值，不显示 `=...` 公式文本 —— Task 1 `test_escaping_newline_formula`。
- 表体中重复出现的表头行（分页表头）：不进审阅稿 —— Task 1 `test_build_rows_and_meta`。
- 审阅期间源 xlsx 被插行：读回给出警告并定位到新行号 —— Task 2 `test_source_changed_relocates`。
- 用户取消"另存为"：内存与本地暂存不得前进到未写盘的版本，重开文件不丢编辑 —— Task 4 Step 4 浏览器检查。

---

### Task 1: 审阅稿生成器 review_html.py

**Files:**
- Create: `C:\Users\Kevin\albedo-cfg\claude\skills\pk-boq-review\scripts\review_html.py`
- Test: `C:\Users\Kevin\albedo-cfg\claude\skills\pk-boq-review\tests\test_review.py`

**Interfaces:**
- Produces:
  - `read_bytes(path: str) -> bytes`
  - `file_sig(path: str) -> dict`，键 `source_mtime`（ISO 秒）、`source_size`（int）
  - `load_workbook(path: str) -> openpyxl.Workbook`（`data_only=True`）
  - `find_header(ws, max_scan=30) -> (int|None, dict|None)`，dict 键 `code/en/zh/unit` → 列字母，`zh` 可为 None
  - `parse_cols(s: str) -> dict`，`"B,C,D,E"`，`-` 表示无此列
  - `read_rows(ws, header_row: int, cols: dict) -> list[dict]`，每项键 `r, code, en, zh, unit, fill, red, strike`
  - `render(rows: list[dict], dst: str, title: str, meta: dict) -> int`（`r` 为 0/None 的行渲染为"新"行，供重构脚本复用）
  - `build(src, sheet=None, header_row=None, cols=None, out=None) -> (str, int)`
  - CLI：`python review_html.py <xlsx> [--sheet] [--header-row] [--cols] [--out]`

- [ ] **Step 1: 写测试夹具与失败测试**

`tests/test_review.py`：

```python
import json
import os
import re
import subprocess
import sys
import time

import openpyxl
import pytest
from openpyxl.styles import Font, PatternFill

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

import review_html  # noqa: E402

ROWS = [
    ("A.01", "【Earthworks】", "【土方】", "", "333F4F", None),
    ("A.01.01", "《Excavation》", "《开挖》", "", "D9E1F2", None),
    ("A.01.01.001", "Trench excavation\ndepth ≤2m", "沟槽开挖\n深度≤2m", "m3", None, None),
    ("A.01.01.002", 'Backfill a<b & "c" </script>', "回填", "m3", "FFFF00", None),
    ("A.01.01.003", "Old item", "旧项目", "m2", None, "del"),
    (None, None, None, None, None, None),
    ("A.01.01.004", "Formula row", "公式行", "nr", None, "formula"),
]


def _fill(cell, rgb):
    cell.fill = PatternFill("solid", fgColor=rgb)


def make_boq(path, insert_after=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BQ"
    ws["B1"] = "Fixture BOQ"
    ws["B3"], ws["C3"], ws["D3"], ws["E3"] = "No.", "Description", "中文描述", "Unit"
    rows = list(ROWS)
    if insert_after is not None:
        rows.insert(insert_after, ("A.01.01.009", "Inserted", "插入", "m", None, None))
    r = 4
    for code, en, zh, unit, rgb, flag in rows:
        if code is not None:
            ws.cell(r, 2, code)
            ws.cell(r, 3, en)
            ws.cell(r, 4, zh)
            ws.cell(r, 5, unit)
            if rgb:
                _fill(ws.cell(r, 2), rgb)
                _fill(ws.cell(r, 3), rgb)
            if flag == "del":
                ws.cell(r, 3).font = Font(color="FF0000", strike=True)
            if flag == "formula":
                ws.cell(r, 5).value = "=E6"
        r += 1
    ws.cell(r, 2, "No.")
    ws.cell(r, 3, "Description")
    ws.cell(r, 4, "中文描述")
    ws.cell(r, 5, "Unit")
    wb.save(path)


@pytest.fixture
def boq(tmp_path):
    p = tmp_path / "Fixture BOQ_v1.xlsx"
    make_boq(str(p))
    return str(p)


DATA_RE = re.compile(r'<script type="application/json" id="review-data">(.*?)</script>', re.S)


def read_data(html_path):
    t = open(html_path, encoding="utf-8").read()
    return t, json.loads(DATA_RE.search(t).group(1))


def test_read_bytes_matches(boq):
    assert review_html.read_bytes(boq) == open(boq, "rb").read()


def test_find_header(boq):
    ws = review_html.load_workbook(boq)["BQ"]
    assert review_html.find_header(ws) == (3, {"code": "B", "en": "C", "zh": "D", "unit": "E"})


def test_build_rows_and_meta(boq):
    dst, n = review_html.build(boq)
    assert os.path.basename(dst) == "Fixture BOQ_v1_审阅稿.html"
    assert n == 6
    t, d = read_data(dst)
    assert t.count('data-orig="No."') == 0
    classes = re.findall(r'<tr class="([^"]*)" data-r="([^"]+)"', t)
    assert classes == [("chapter", "4"), ("subchap", "5"), ("", "6"), ("modrow", "7"), ("delrow", "8"), ("", "10")]
    m = d["meta"]
    assert (m["sheet"], m["header_row"], m["cols"]) == ("BQ", 3, {"code": "B", "en": "C", "zh": "D", "unit": "E"})
    assert m["source_size"] == os.path.getsize(boq)
    assert m["out_name"] == "Fixture BOQ_v1_审阅稿.html"
    assert d["review"] == {"saved_at": None, "edits": [], "comments": []}
    assert t.count("<button") == 4
    assert t.count('data-c="note"') == 6


def test_escaping_newline_formula(boq):
    dst, _ = review_html.build(boq)
    t, d = read_data(dst)
    assert 'data-orig="Backfill a&lt;b &amp; &quot;c&quot; &lt;/script&gt;"' in t
    assert 'data-orig="沟槽开挖\n深度≤2m"' in t
    assert "=E6" not in t
    assert d["meta"]["sheet"] == "BQ"


def test_header_not_found(tmp_path):
    p = tmp_path / "x.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = "hello"
    wb.save(p)
    with pytest.raises(SystemExit):
        review_html.build(str(p))


def test_cols_override(boq):
    dst, n = review_html.build(boq, header_row=3, cols=review_html.parse_cols("B,C,-,E"))
    _, d = read_data(dst)
    assert d["meta"]["cols"]["zh"] is None
    assert n == 6


def test_large_sheet_fast(tmp_path):
    p = tmp_path / "big.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["No.", "Description", "中文描述", "Unit"])
    for i in range(6000):
        ws.append(["A.%05d" % i, "Item %d" % i, "项目%d" % i, "m2"])
    wb.save(p)
    t0 = time.time()
    _, n = review_html.build(str(p))
    assert n == 6000
    assert time.time() - t0 < 15


def test_cli(boq):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "review_html.py"), boq],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert os.path.exists(boq[:-5] + "_审阅稿.html")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review && python -m pytest tests -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'review_html'`）

- [ ] **Step 3: 实现 review_html.py**

```python
# -*- coding: utf-8 -*-
"""BOQ 清单 -> HTML 审阅稿：编号/英文描述/中文描述/单位 + 审阅意见列；修改与意见保存在内嵌 review-data。"""
import argparse
import datetime
import html
import io
import json
import os
import sys

import openpyxl

TOOL = "pk-boq-review 1.0"
FIELDS = ("code", "en", "zh", "unit")
CODE_KEYS = {"no.", "no", "code", "item", "item no.", "编号", "序号"}
UNIT_KEYS = {"unit", "units", "单位"}
FILL_CLASS = {"333F4F": "chapter", "D9E1F2": "subchap", "FBE5D6": "subhead"}
MARK_CLASS = {"C6EFCE": "newrow", "FFFF00": "modrow"}


def _read_bytes_shared(path):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    create = k.CreateFileW
    create.restype = wintypes.HANDLE
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    h = create(path, 0x80000000, 7, None, 3, 0, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise OSError("CreateFileW failed: %s" % path)
    try:
        buf = ctypes.create_string_buffer(1 << 20)
        got = wintypes.DWORD(0)
        out = bytearray()
        while k.ReadFile(h, buf, len(buf), ctypes.byref(got), None) and got.value:
            out += buf.raw[:got.value]
        return bytes(out)
    finally:
        k.CloseHandle(h)


def read_bytes(path):
    # Excel 打开时以全共享方式持有句柄，普通 open 会 PermissionError
    if os.name == "nt":
        try:
            return _read_bytes_shared(path)
        except OSError:
            pass
    with open(path, "rb") as f:
        return f.read()


def file_sig(path):
    st = os.stat(path)
    return {"source_mtime": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "source_size": st.st_size}


def load_workbook(path):
    return openpyxl.load_workbook(io.BytesIO(read_bytes(path)), data_only=True)


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def find_header(ws, max_scan=30):
    for row in ws.iter_rows(min_row=1, max_row=min(max_scan, ws.max_row)):
        found = {}
        for c in row:
            t = _text(c.value)
            if not t:
                continue
            low = t.lower()
            if low in CODE_KEYS and "code" not in found:
                found["code"] = c.column_letter
            elif "中文" in t and "zh" not in found:
                found["zh"] = c.column_letter
            elif low.startswith("description") and "en" not in found:
                found["en"] = c.column_letter
            elif low in UNIT_KEYS and "unit" not in found:
                found["unit"] = c.column_letter
        if {"code", "en", "unit"} <= set(found):
            found.setdefault("zh", None)
            return row[0].row, found
    return None, None


def parse_cols(s):
    parts = [p.strip().upper() for p in s.split(",")]
    if len(parts) != 4:
        raise SystemExit("--cols 需要 4 项：编号,英文,中文,单位，例如 B,C,D,E；无中文列写 -")
    return {f: (None if p in ("", "-") else p) for f, p in zip(FIELDS, parts)}


def fill_rgb(cell):
    f = cell.fill
    try:
        if f and f.patternType and f.fgColor is not None and f.fgColor.type == "rgb" and f.fgColor.rgb:
            return str(f.fgColor.rgb)[-6:].upper()
    except (AttributeError, TypeError):
        pass
    return None


def font_flags(cell):
    f = cell.font
    red = strike = False
    try:
        if f and f.color is not None and f.color.type == "rgb" and f.color.rgb:
            red = str(f.color.rgb)[-6:].upper() == "FF0000"
        strike = bool(f and f.strike)
    except (AttributeError, TypeError):
        pass
    return red, strike


def read_rows(ws, header_row, cols):
    labels = {f: _text(ws["%s%d" % (cols[f], header_row)].value) for f in FIELDS if cols.get(f)}
    rows = []
    for r in range(header_row + 1, ws.max_row + 1):
        vals = {f: (_text(ws["%s%d" % (cols[f], r)].value) if cols.get(f) else "") for f in FIELDS}
        if not any(vals.values()):
            continue
        if all(vals[f] == labels[f] for f in labels):
            continue
        en_cell = ws["%s%d" % (cols["en"], r)]
        red, strike = font_flags(en_cell)
        fill = fill_rgb(en_cell) or fill_rgb(ws["%s%d" % (cols["code"], r)])
        rows.append(dict(r=r, fill=fill, red=red, strike=strike, **vals))
    return rows


def row_class(x):
    if x.get("red") or x.get("strike"):
        return "delrow"
    fill = x.get("fill") or ""
    cls = FILL_CLASS.get(fill, "")
    if not cls:
        t = (x.get("en") or "") + (x.get("zh") or "")
        cls = "chapter" if "【" in t else "subchap" if "《" in t else "subhead" if "{" in t else ""
    return " ".join(c for c in (cls, MARK_CLASS.get(fill, "")) if c)


def _esc(v):
    return html.escape(v or "", quote=False)


def _attr(v):
    return html.escape(v or "", quote=True)


CSS = r"""<style>
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;display:flex;flex-direction:column;background:#eef1f5;color:#1f2937;font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;font-size:13px;line-height:1.5}
.bar{flex:none;background:#0f172a;color:#fff;padding:9px 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.bar b{font-size:15px;margin-right:6px}
.bar button{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:6px 11px;cursor:pointer;font-size:12.5px}
.bar button:hover{background:#1d4ed8}
.bar button.warn{background:#b91c1c}
.bar .src{font-size:12px;color:#cbd5e1}
.badge{background:#f59e0b;color:#111;border-radius:11px;padding:1px 9px;font-size:12px;font-weight:700}
.legend{flex:none;display:flex;gap:14px;flex-wrap:wrap;margin:9px 14px;font-size:12.5px;color:#334155}
.legend i{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:-2px;margin-right:5px;border:1px solid #cbd5e1}
.wrap{flex:1 1 auto;min-height:0;overflow:auto;background:#fff}
table{border-collapse:separate;border-spacing:0;table-layout:fixed}
th,td{border-right:1px solid #dfe3e8;border-bottom:1px solid #e8ecf1;padding:5px 8px;vertical-align:top;text-align:left;overflow-wrap:anywhere}
th:last-child,td:last-child{border-right:0}
thead th{position:sticky;top:0;z-index:10;background:#334155;color:#fff;text-align:center;font-weight:700}
th .rz{position:absolute;top:0;right:-3px;width:7px;height:100%;cursor:col-resize;z-index:11}
th .rz:hover{background:#93c5fd}
td.no{white-space:nowrap;font-family:Consolas,monospace;font-size:12px;color:#1d4ed8}
td.tx,td.note{white-space:pre-wrap}
td.zh{color:#334155}
td.unit{text-align:center;white-space:nowrap}
td.rn{text-align:right;color:#94a3b8;font-family:Consolas,monospace;font-size:11px;background:#f8fafc}
td.note{background:#fffbeb;color:#92400e}
tr.chapter td{background:#333F4F;color:#fff;font-weight:700}
tr.chapter td.no{color:#c7d2fe}
tr.subchap td{background:#D9E1F2;font-weight:600}
tr.subhead td{background:#FBE5D6;font-weight:600}
tr.newrow td{background:#C6EFCE}
tr.modrow td{background:#FFFF00}
tr.delrow td{background:#FFE1E1;color:#B91C1C;text-decoration:line-through}
tr td.note{text-decoration:none}
tr.noted td.rn{box-shadow:inset 3px 0 0 #d97706;color:#b45309;font-weight:700}
td[contenteditable]:focus{background:#fff;outline:2px solid #2563eb}
td.edited{box-shadow:inset 3px 0 0 #ea580c,inset 0 0 0 1px #fdba74}
.tip{position:fixed;right:14px;bottom:14px;background:#0f172a;color:#fff;padding:8px 12px;border-radius:8px;font-size:12.5px;opacity:0;transition:opacity .2s;z-index:30;max-width:460px}
.tip.on{opacity:.95}
</style>"""

JS = r"""<script>
var DATA=JSON.parse(document.getElementById('review-data').textContent);
function h32(s){var h=0;for(var i=0;i<s.length;i++){h=(h*31+s.charCodeAt(i))|0;}return (h>>>0).toString(36);}
var BASE=h32(DATA.meta.source+'|'+DATA.meta.source_mtime);
var LS_KEY='pkreview_'+BASE, LS_W='pkreview_w_'+BASE;
var edits={}, notes={};
function norm(s){return (s||'').replace(/\r\n?/g,'\n').replace(/\u00a0/g,' ').replace(/[ \t]+\n/g,'\n').trim();}
function tip(t){var e=document.getElementById('tip');e.textContent=t;e.classList.add('on');clearTimeout(e._t);e._t=setTimeout(function(){e.classList.remove('on');},3000);}
function vals(o){return Object.keys(o||{}).map(function(k){return o[k];});}
function sorted(a){return a.sort(function(x,y){return ((x.row||1e9)-(y.row||1e9))||String(x.col||'').localeCompare(String(y.col||''));});}
function rowOf(tr){var r=tr.dataset.r;return /^\d+$/.test(r)?parseInt(r,10):null;}
function cell(rid,c){return document.querySelector('tr[data-r="'+rid+'"] td[data-c="'+c+'"]');}
function updCnt(){document.getElementById('cntE').textContent=Object.keys(edits).length;document.getElementById('cntN').textContent=Object.keys(notes).length;}
function saveLS(){try{localStorage.setItem(LS_KEY,JSON.stringify({base:DATA.review.saved_at,edits:edits,notes:notes}));}catch(e){}}
function track(td){
  var tr=td.closest('tr'), rid=tr.dataset.r, c=td.dataset.c, cur=norm(td.innerText);
  if(c==='note'){
    var z=tr.querySelector('td[data-c="zh"]');
    if(cur){notes[rid]={rid:rid,row:rowOf(tr),code:tr.dataset.code,text:cur,desc:z?norm(z.dataset.orig):''};tr.classList.add('noted');}
    else{delete notes[rid];tr.classList.remove('noted');}
  }else{
    var o=norm(td.dataset.orig), k=rid+'|'+c;
    if(cur!==o){edits[k]={rid:rid,row:rowOf(tr),code:tr.dataset.code,col:c,old:o,new:cur};td.classList.add('edited');}
    else{delete edits[k];td.classList.remove('edited');}
  }
}
document.querySelectorAll('td[contenteditable]').forEach(function(td){td.addEventListener('input',function(){track(td);updCnt();saveLS();});});
function put(rid,c,text){var td=cell(rid,c);if(!td)return false;td.innerText=text;track(td);return true;}
function restore(){
  var st=null;
  try{var s=localStorage.getItem(LS_KEY);if(s){var o=JSON.parse(s);if(o.base===DATA.review.saved_at)st=o;}}catch(e){}
  var E=st?vals(st.edits):(DATA.review.edits||[]), N=st?vals(st.notes):(DATA.review.comments||[]), lost=0;
  E.forEach(function(x){if(!put(x.rid,x.col,x.new))lost++;});
  N.forEach(function(x){if(!put(x.rid,'note',x.text))lost++;});
  updCnt();
  if(lost)tip('有 '+lost+' 条记录找不到对应行');
  else if(st&&(E.length||N.length))tip('已恢复本机未保存的编辑');
}
function clearAll(){
  if(!confirm('清除全部修改和意见，恢复到生成时的内容？'))return;
  document.querySelectorAll('td[contenteditable]').forEach(function(td){td.innerText=td.dataset.orig;td.classList.remove('edited');});
  document.querySelectorAll('tr.noted').forEach(function(tr){tr.classList.remove('noted');});
  edits={};notes={};saveLS();updCnt();tip('已清除；保存后审阅稿里的记录也会清空');
}
function copyChanges(){
  var T='\t',N='\n',L=[];
  sorted(vals(edits)).forEach(function(x){L.push(['修改',x.row||'新',x.code,x.col,x.old.split(N).join(' '),x.new.split(N).join(' ')].join(T));});
  sorted(vals(notes)).forEach(function(x){L.push(['意见',x.row||'新',x.code,'',x.text.split(N).join(' '),''].join(T));});
  if(!L.length){tip('没有修改或意见');return;}
  navigator.clipboard.writeText(['类型','行','编号','列','原值/意见','新值'].join(T)+N+L.join(N)).then(function(){tip('已复制 '+L.length+' 条');},function(){tip('复制失败');});
}
function buildHTML(){
  var doc=document.documentElement.cloneNode(true);
  doc.querySelectorAll('td[contenteditable]').forEach(function(td){td.textContent=td.dataset.orig;td.classList.remove('edited');});
  doc.querySelectorAll('tr.noted').forEach(function(tr){tr.classList.remove('noted');});
  var t=doc.querySelector('#tip');if(t)t.className='tip';
  doc.querySelector('#review-data').textContent=JSON.stringify(DATA).replace(/<\//g,'<\\/');
  return '<!doctype html>\n'+doc.outerHTML;
}
async function saveFile(){
  var prev=DATA.review;
  DATA.review={saved_at:new Date().toISOString(),edits:sorted(vals(edits)),comments:sorted(vals(notes))};
  var html=buildHTML(), name=DATA.meta.out_name, msg='（修改 '+DATA.review.edits.length+' · 意见 '+DATA.review.comments.length+'）';
  if(window.showSaveFilePicker){
    try{
      var h=await window.showSaveFilePicker({suggestedName:name,types:[{description:'HTML 审阅稿',accept:{'text/html':['.html']}}]});
      var w=await h.createWritable();await w.write(html);await w.close();
      saveLS();tip('已保存：'+h.name+msg);return;
    }catch(e){
      if(e&&e.name==='AbortError'){DATA.review=prev;tip('已取消保存');return;}
    }
  }
  var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([html],{type:'text/html'}));a.download=name;a.click();
  saveLS();tip('已下载到「下载」文件夹：'+name+msg);
}
var cols=document.querySelectorAll('#t colgroup col');
var W=[56,120,0,0,70,0];
function applyW(){cols.forEach(function(c,i){c.style.width=W[i]+'px';});document.getElementById('t').style.width=W.reduce(function(a,b){return a+b;},0)+'px';}
function computeInit(){var rest=document.querySelector('.wrap').clientWidth-2-56-120-70;if(rest<400)rest=1000;W=[56,120,Math.round(rest*0.40),Math.round(rest*0.34),70,Math.round(rest*0.26)];applyW();}
function saveWidths(){try{localStorage.setItem(LS_W,JSON.stringify(W));}catch(e){}}
function loadWidths(){try{var s=localStorage.getItem(LS_W);if(s){var w=JSON.parse(s);if(w&&w.length===6&&w[2]>0){W=w;applyW();return;}}}catch(e){}computeInit();}
function resetWidths(){try{localStorage.removeItem(LS_W);}catch(e){}computeInit();saveWidths();tip('列宽已重置');}
document.querySelectorAll('#t thead th .rz').forEach(function(rz,i){
  rz.addEventListener('mousedown',function(e){
    e.preventDefault();e.stopPropagation();
    var startX=e.pageX,w0=W[i],sum=W[i]+W[i+1];
    document.body.style.userSelect='none';
    function mv(ev){var a=Math.max(40,Math.min(w0+ev.pageX-startX,sum-40));W[i]=a;W[i+1]=sum-a;applyW();}
    function up(){document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);document.body.style.userSelect='';saveWidths();}
    document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up);
  });
});
loadWidths();restore();
</script>"""

LEGEND = ('<div class="legend">'
          '<span><i style="background:#333F4F"></i>章【】</span>'
          '<span><i style="background:#D9E1F2"></i>节《》</span>'
          '<span><i style="background:#FBE5D6"></i>小标题{}</span>'
          '<span><i style="background:#FFFF00"></i>调整</span>'
          '<span><i style="background:#C6EFCE"></i>新增</span>'
          '<span><i style="background:#FFE1E1"></i>删除(红删除线)</span>'
          '<span><i style="background:#fdba74"></i>本次修改（橙框）</span>'
          '<span><i style="background:#fffbeb"></i>审阅意见（行号橙标）</span>'
          '<span style="color:#64748b">单元格可直接改 · 最右列写意见 · 拖表头右缘调列宽 · 改完点"保存"</span></div>')


def render(rows, dst, title, meta):
    data = {"meta": meta, "review": {"saved_at": None, "edits": [], "comments": []}}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    H = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<title>%s</title>' % html.escape(title), CSS, '</head><body>',
         '<div class="bar"><b>%s</b>' % _esc(title),
         '<button onclick="saveFile()">保存</button>',
         '<button onclick="copyChanges()">复制变更清单</button>',
         '<button onclick="resetWidths()">重置列宽</button>',
         '<button class="warn" onclick="clearAll()">清除全部编辑</button>',
         '<span>修改 <span class="badge" id="cntE">0</span> 处 · 意见 <span class="badge" id="cntN">0</span> 条</span>',
         '<span class="src">%s · %s</span></div>' % (_esc(os.path.basename(meta.get("source", ""))), _esc(meta.get("sheet", ""))),
         LEGEND,
         '<div class="wrap"><table id="t"><colgroup>'
         '<col data-k="rn"><col data-k="code"><col data-k="en"><col data-k="zh"><col data-k="unit"><col data-k="note">'
         '</colgroup><thead><tr>'
         '<th>行<span class="rz"></span></th><th>编号<span class="rz"></span></th>'
         '<th>Description<span class="rz"></span></th><th>中文描述<span class="rz"></span></th>'
         '<th>单位<span class="rz"></span></th><th>审阅意见</th></tr></thead><tbody>']
    n = 0
    for x in rows:
        n += 1
        r = x.get("r") or 0
        rid = str(r) if r else "n%d" % n
        cls = row_class(x)
        style = ""
        fill = x.get("fill")
        if fill and fill not in FILL_CLASS and fill not in MARK_CLASS and cls != "delrow":
            style = ' style="background:#%s"' % fill
        H.append('<tr class="%s" data-r="%s" data-code="%s"%s><td class="rn">%s</td>'
                 % (cls, rid, _attr(x.get("code")), style, r if r else "新"))
        for f, css in (("code", "no"), ("en", "tx"), ("zh", "tx zh"), ("unit", "unit")):
            v = x.get(f) or ""
            H.append('<td class="%s" contenteditable="true" data-c="%s" data-orig="%s">%s</td>'
                     % (css, f, _attr(v), _esc(v)))
        H.append('<td class="note" contenteditable="true" data-c="note" data-orig=""></td></tr>')
    H.append('</tbody></table></div><div class="tip" id="tip"></div>')
    H.append('<script type="application/json" id="review-data">%s</script>' % blob)
    H.append(JS)
    H.append('</body></html>')
    with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(H))
    return n


def build(src, sheet=None, header_row=None, cols=None, out=None):
    src = os.path.abspath(src)
    wb = load_workbook(src)
    hr = cc = ws = None
    for name in ([sheet] if sheet else wb.sheetnames):
        if name not in wb.sheetnames:
            raise SystemExit("工作表不存在：%s（现有：%s）" % (name, "、".join(wb.sheetnames)))
        ws = wb[name]
        auto_row, auto_cols = find_header(ws)
        hr, cc = header_row or auto_row, cols or auto_cols
        if hr and cc:
            break
    if not (hr and cc):
        raise SystemExit("未识别到表头（编号/Description/单位）。请用 --sheet、--header-row、--cols 指定。")
    rows = read_rows(ws, hr, cc)
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.abspath(out) if out else os.path.join(os.path.dirname(src), stem + "_审阅稿.html")
    meta = {"source": src, "sheet": ws.title, "header_row": hr, "cols": cc}
    meta.update(file_sig(src))
    meta.update({"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
                 "tool": TOOL, "out_name": os.path.basename(dst)})
    n = render(rows, dst, "%s · %s · 审阅稿" % (stem, ws.title), meta)
    return dst, n


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="BOQ xlsx -> HTML 审阅稿")
    ap.add_argument("xlsx")
    ap.add_argument("--sheet")
    ap.add_argument("--header-row", type=int)
    ap.add_argument("--cols", help="编号,英文,中文,单位 列字母，如 B,C,D,E；无中文列写 -")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    dst, n = build(a.xlsx, a.sheet, a.header_row, parse_cols(a.cols) if a.cols else None, a.out)
    print("审阅稿：%s（%d 行）" % (dst, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review && python -m pytest tests -q`
Expected: `8 passed`

---

### Task 2: 读回脚本 review_read.py

**Files:**
- Create: `C:\Users\Kevin\albedo-cfg\claude\skills\pk-boq-review\scripts\review_read.py`
- Modify: `C:\Users\Kevin\albedo-cfg\claude\skills\pk-boq-review\tests\test_review.py`（追加测试）

**Interfaces:**
- Consumes: Task 1 的 `review_html.file_sig`、`load_workbook`、`read_rows`，以及 `review-data` 结构：`meta{source, sheet, header_row, cols, source_mtime, source_size, out_name, ...}`，`review{saved_at, edits[{rid,row,code,col,old,new}], comments[{rid,row,code,text,desc}]}`。
- Produces:
  - `DATA_RE`（编译好的正则）
  - `norm(s) -> str`
  - `load(path) -> dict`（含 `meta`、`review`、`legacy: bool`）
  - `check_source(meta) -> (list[str], bool)`
  - `relocate(meta, items) -> list[dict]`，每项 `row, code, now_at: list[int]`
  - `report(data, warnings, moved) -> str`
  - `main(argv) -> int`；CLI：`python review_read.py <审阅稿.html> [--json 路径]`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_review.py` 末尾追加：

```python
import review_read  # noqa: E402

E1 = {"rid": "6", "row": 6, "code": "A.01.01.001", "col": "zh", "old": "沟槽开挖\n深度≤2m", "new": "沟槽开挖\n深度≤3m"}
E2 = {"rid": "7", "row": 7, "code": "A.01.01.002", "col": "en",
      "old": 'Backfill a<b & "c" </script>', "new": "Backfill </script> fixed"}
E3 = {"rid": "10", "row": 10, "code": "A.01.01.004", "col": "unit", "old": "", "new": " \u00a0"}
C1 = {"rid": "8", "row": 8, "code": "A.01.01.003", "text": "整行删除", "desc": "旧项目"}


def inject(dst, edits, comments, saved="2026-10-06T10:00:00Z"):
    t = open(dst, encoding="utf-8").read()
    m = DATA_RE.search(t)
    d = json.loads(m.group(1))
    d["review"] = {"saved_at": saved, "edits": edits, "comments": comments}
    blob = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    open(dst, "w", encoding="utf-8").write(t[:m.start(1)] + blob + t[m.end(1):])


def test_roundtrip(boq, capsys):
    dst, _ = review_html.build(boq)
    inject(dst, [E1, E2, E3], [C1])
    data = review_read.load(dst)
    assert [e["code"] for e in data["review"]["edits"]] == ["A.01.01.001", "A.01.01.002"]
    assert data["review"]["edits"][1]["new"] == "Backfill </script> fixed"
    assert review_read.check_source(data["meta"]) == ([], False)
    assert review_read.main([dst]) == 0
    out = capsys.readouterr().out
    assert "校验：通过" in out
    assert "整行删除" in out
    assert "深度≤3m" in out
    assert "合计：修改 2 处，意见 1 条" in out


def test_no_changes(boq, capsys):
    dst, _ = review_html.build(boq)
    review_read.main([dst])
    assert "审阅稿无修改" in capsys.readouterr().out


def test_source_changed_relocates(boq, tmp_path, capsys):
    dst, _ = review_html.build(boq)
    inject(dst, [E1], [C1])
    make_boq(boq, insert_after=1)
    out_json = tmp_path / "r.json"
    review_read.main([dst, "--json", str(out_json)])
    assert "审阅期间源文件已变动" in capsys.readouterr().out
    r = json.load(open(out_json, encoding="utf-8"))
    assert {(m["code"], tuple(m["now_at"])) for m in r["moved"]} == {("A.01.01.001", (7,)), ("A.01.01.003", (9,))}


def test_source_missing(boq, capsys):
    dst, _ = review_html.build(boq)
    os.remove(boq)
    review_read.main([dst])
    assert "源文件不存在" in capsys.readouterr().out


def test_legacy_format(tmp_path, capsys):
    p = tmp_path / "old.html"
    p.write_text('<table><tbody><tr class="" data-r="6"><td class="rn">6</td>'
                 '<td data-c="B" data-orig="A.01">A.01</td>'
                 '<td data-c="C" data-orig="Old">New text</td>'
                 '<td data-c="D" data-orig="中">中</td>'
                 '<td data-c="E" data-orig="m2">m2 </td></tr></tbody></table>', encoding="utf-8")
    data = review_read.load(str(p))
    assert data["legacy"] is True
    assert data["review"]["edits"] == [{"rid": "6", "row": 6, "code": "A.01", "col": "en", "old": "Old", "new": "New text"}]
    review_read.main([str(p)])
    assert "旧格式审阅稿" in capsys.readouterr().out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review && python -m pytest tests -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'review_read'`）

- [ ] **Step 3: 实现 review_read.py**

```python
# -*- coding: utf-8 -*-
"""读回 HTML 审阅稿：修改清单 + 审阅意见 + 源文件校验。"""
import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_html  # noqa: E402

DATA_RE = re.compile(r'<script type="application/json" id="review-data">(.*?)</script>', re.S)
LEGACY_COLS = {"B": "code", "C": "en", "D": "zh", "E": "unit"}
COL_NAME = {"code": "编号", "en": "英文描述", "zh": "中文描述", "unit": "单位"}


def norm(s):
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    return re.sub(r"[ \t]+\n", "\n", s).strip()


class _Legacy(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._tr = None
        self._td = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and "data-r" in a:
            self._tr = {"rid": a["data-r"], "cells": {}}
            self.rows.append(self._tr)
        elif tag == "td" and self._tr is not None and "data-c" in a:
            self._td = (a["data-c"], a.get("data-orig") or "")
            self._buf = []
        elif self._td is not None and (tag == "br" or (tag in ("div", "p") and self._buf)):
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag == "td" and self._td is not None:
            c, orig = self._td
            self._tr["cells"][c] = (orig, "".join(self._buf))
            self._td = None
        elif tag == "tr":
            self._tr = None

    def handle_data(self, d):
        if self._td is not None:
            self._buf.append(d)


def _legacy(text):
    p = _Legacy()
    p.feed(text)
    edits = []
    for row in p.rows:
        code = norm(row["cells"].get("B", row["cells"].get("code", ("", "")))[0])
        for c, (orig, cur) in row["cells"].items():
            if c == "note" or norm(orig) == norm(cur):
                continue
            edits.append({"rid": row["rid"], "row": int(row["rid"]) if row["rid"].isdigit() else None,
                          "code": code, "col": LEGACY_COLS.get(c, c), "old": norm(orig), "new": norm(cur)})
    return {"meta": {}, "review": {"saved_at": None, "edits": edits, "comments": []}, "legacy": True}


def load(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = DATA_RE.search(text)
    if not m:
        return _legacy(text)
    data = json.loads(m.group(1))
    rv = data.setdefault("review", {})
    rv["edits"] = [e for e in rv.get("edits") or [] if norm(e.get("old")) != norm(e.get("new"))]
    rv["comments"] = [c for c in rv.get("comments") or [] if norm(c.get("text"))]
    data["legacy"] = False
    return data


def check_source(meta):
    if not meta:
        return ["旧格式审阅稿：没有源文件信息，无法校验，请人工确认对应的 xlsx 版本"], False
    src = meta.get("source") or ""
    if not os.path.exists(src):
        return ["源文件不存在：%s" % src], False
    sig = review_html.file_sig(src)
    if sig["source_mtime"] != meta.get("source_mtime") or sig["source_size"] != meta.get("source_size"):
        return ["审阅期间源文件已变动（生成时 %s / %s 字节，现在 %s / %s 字节），行号可能错位，已按编号重新定位"
                % (meta.get("source_mtime"), meta.get("source_size"), sig["source_mtime"], sig["source_size"])], True
    return [], False


def relocate(meta, items):
    ws = review_html.load_workbook(meta["source"])[meta["sheet"]]
    rows = review_html.read_rows(ws, meta["header_row"], meta["cols"])
    by_row = {x["r"]: x["code"] for x in rows}
    by_code = {}
    for x in rows:
        if x["code"]:
            by_code.setdefault(x["code"], []).append(x["r"])
    out = []
    for it in items:
        if it.get("row") is None or by_row.get(it["row"]) == it.get("code"):
            continue
        out.append({"row": it["row"], "code": it.get("code"), "now_at": by_code.get(it.get("code") or "", [])})
    return out


def _cell(s):
    return norm(s).replace("|", "\\|").replace("\n", "<br>")


def _cut(s, n=40):
    s = norm(s).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def report(data, warnings, moved):
    meta, rv = data.get("meta") or {}, data["review"]
    L = ["# 审阅稿读回", ""]
    if meta:
        L.append("- 源文件：`%s`" % meta.get("source"))
        L.append("- 工作表：%s，表头第 %s 行，列 %s" % (meta.get("sheet"), meta.get("header_row"),
                                               "、".join("%s=%s" % (COL_NAME[k], v) for k, v in meta.get("cols", {}).items() if v)))
        L.append("- 保存时间：%s" % (rv.get("saved_at") or "未保存过"))
    L.append("- 校验：" + ("；".join(warnings) if warnings else "通过"))
    L.append("")
    if moved:
        L += ["## 行号错位", "", "| 原行 | 编号 | 现在所在行 |", "|---|---|---|"]
        L += ["| %s | %s | %s |" % (m["row"], m["code"], "、".join(map(str, m["now_at"])) or "找不到") for m in moved]
        L.append("")
    edits, comments = rv.get("edits") or [], rv.get("comments") or []
    if not edits and not comments:
        L.append("审阅稿无修改")
        return "\n".join(L)
    if edits:
        L += ["## 修改清单", "", "| 行 | 编号 | 列 | 原值 | 新值 |", "|---|---|---|---|---|"]
        L += ["| %s | %s | %s | %s | %s |" % (e.get("row") or "新", e.get("code"), COL_NAME.get(e.get("col"), e.get("col")),
                                            _cell(e.get("old")), _cell(e.get("new"))) for e in edits]
        L.append("")
    if comments:
        L += ["## 审阅意见", "", "| 行 | 编号 | 当前中文描述 | 意见 |", "|---|---|---|---|"]
        L += ["| %s | %s | %s | %s |" % (c.get("row") or "新", c.get("code"), _cell(_cut(c.get("desc"))), _cell(c.get("text")))
              for c in comments]
        L.append("")
    L.append("合计：修改 %d 处，意见 %d 条" % (len(edits), len(comments)))
    return "\n".join(L)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="读回 HTML 审阅稿")
    ap.add_argument("html")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    data = load(a.html)
    warnings, changed = check_source(data.get("meta"))
    moved = []
    if changed:
        try:
            moved = relocate(data["meta"], data["review"]["edits"] + data["review"]["comments"])
        except (KeyError, OSError, ValueError) as e:
            warnings.append("重新定位失败：%s" % e)
    print(report(data, warnings, moved))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"meta": data.get("meta"), "review": data["review"], "warnings": warnings,
                       "moved": moved, "legacy": data.get("legacy")}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review && python -m pytest tests -q`
Expected: `13 passed`

---

### Task 3: 技能文档、路由与同步

**Files:**
- Create: `C:\Users\Kevin\albedo-cfg\claude\skills\pk-boq-review\SKILL.md`
- Modify: `C:\Users\Kevin\albedo-cfg\claude\skills\pk-boq\SKILL.md`（json-workflow 表格行与 JSONWF 流程图行之后各插一行）
- Modify: `C:\Users\Kevin\.claude\skills\pk-boq\SKILL.md`（同上，两份分别改，不整份同步）
- Create（同步）: `C:\Users\Kevin\.claude\skills\pk-boq-review\`

**Interfaces:**
- Consumes: Task 1/2 的 CLI。

- [ ] **Step 1: 写 SKILL.md**

```markdown
---
name: pk-boq-review
description: 大改 BOQ 清单前的 HTML 审阅模式。把 xlsx 生成为 1:1 模拟清单格式的审阅稿（编号、英文描述、中文描述、单位 + 最右侧审阅意见列），用户在浏览器里直接改单元格、写意见、保存；AI 下一轮读回完整修改清单和意见，据此改出新版本 Excel。触发词：审阅稿、审阅模式、HTML 预览清单、大改清单、先在 HTML 上改、读审阅稿、读回审阅意见。
---

# pk-boq-review — 清单 HTML 审阅模式

只显示决定清单内容的四列（编号、英文描述、中文描述、单位），不显示工程量列。修改与意见保存在审阅稿内嵌的 `review-data` 数据块里，一个文件就是完整记录。

## 三步循环

1. **生成**：`python ~/.claude/skills/pk-boq-review/scripts/review_html.py "<清单.xlsx>"`
   - 输出 `<清单名>_审阅稿.html`，与 xlsx 同目录；按表头名自动识别列，识别不到时加 `--sheet`、`--header-row`、`--cols B,C,D,E`（无中文列写 `-`）。
   - 把审阅稿路径告诉用户，提示用 Edge/Chrome 打开。
2. **审阅**（用户操作）：改单元格（橙框）、在最右列写意见（行号橙标）、点"保存"，第一次在对话框里选到清单所在文件夹并覆盖原审阅稿。编辑过程自动暂存在浏览器本地。
3. **读回与改版**：`python ~/.claude/skills/pk-boq-review/scripts/review_read.py "<审阅稿.html>"`（加 `--json 路径` 输出结构化结果）
   - 校验有警告（源文件已变动、源文件不存在、旧格式）时先告诉用户，确认后再改。
   - 按知识库「工作/概览.md · BOQ 编制约定」的版本与标记约定改版：复制 vN 为 vN.1，在副本上改；文字修改写入并标黄，删除用红字删除线，新增标绿。
   - 意见里的结构性改动（插行、删行、移动、调层级）走 zip/XML 层（参考 `~/.claude/skills/pk-boq/scripts/xlsx_rowops.py`），禁止 Excel COM。
   - 改完对 vN.1 再生成审阅稿，进入下一轮。

## 页面

- 工具栏：保存、复制变更清单、重置列宽、清除全部编辑；计数"修改 N 处 · 意见 M 条"。
- 表头固定，列宽可拖（相邻两列此消彼长）。
- 保存走浏览器"另存为"（File System Access API），不支持时下载到「下载」文件夹。

## 复用

重构脚本可直接调用 `review_html.render(rows, dst, title, meta)`：`rows` 每项含 `r, code, en, zh, unit, fill, red, strike`，`r` 为 0 表示新增行（显示"新"）；`meta` 至少含 `source, sheet, header_row, cols, source_mtime, source_size, out_name`，其中 `source_mtime`、`source_size` 用 `review_html.file_sig(src)` 取得。
```

- [ ] **Step 2: pk-boq 路由两处插行**

两份 `pk-boq/SKILL.md` 各用 Edit：在
`| \`pk-boq-json-workflow\` | 大型清单增量修改 | ≥5000行 BOQ 反复调整时的 master JSONL + 分片工作流,xlsx 只作交付格式 |`
之后插入
`| \`pk-boq-review\` | HTML 审阅模式 | 大改清单前生成 1:1 审阅稿，用户改单元格、写意见、保存，AI 读回修改清单后改版 |`；
在
`    Q1 -->|"大清单反复改/多轮调整/上万行"| JSONWF["→ pk-boq-json-workflow"]`
之后插入
`    Q1 -->|"审阅稿/先在HTML上改/读回审阅意见"| REVIEW["→ pk-boq-review"]`。

- [ ] **Step 3: 同步并校验**

Run:
```bash
rm -rf /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review/tests/__pycache__ /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review/scripts/__pycache__ /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review/.pytest_cache
cp -r /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review /c/Users/Kevin/.claude/skills/
diff -rq /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq-review /c/Users/Kevin/.claude/skills/pk-boq-review && echo SYNCED
grep -c "pk-boq-review" /c/Users/Kevin/albedo-cfg/claude/skills/pk-boq/SKILL.md /c/Users/Kevin/.claude/skills/pk-boq/SKILL.md
cd /c/Users/Kevin/.claude/skills/pk-boq-review && python -m pytest tests -q
```
Expected: `SYNCED`；两份 pk-boq 各 `2`；`13 passed`。

---

### Task 4: 真实清单端到端验证与知识库更新

**Files:**
- 生成（交付物）: `F:\OneDrive - China Harbour Engineering Company Ltd\HO04-Tender 营销组织-LK26XX CIFC Project - Documents\2-3-3 工程量核算 Quantities\BOQ Prep\CIFC BOQ_v4.1_审阅稿.html`
- Modify: `F:\BaiduSyncdisk\30 知识库\工作\概览.md`（「大改清单先出 HTML 审阅稿」一条改为指向技能）
- Modify: `F:\BaiduSyncdisk\30 知识库\变更日志.md`

**Interfaces:**
- Consumes: Task 1–3 的 CLI 与页面行为。

- [ ] **Step 1: 用 CIFC v4.1 生成审阅稿**

Run: `python ~/.claude/skills/pk-boq-review/scripts/review_html.py "F:\OneDrive - China Harbour Engineering Company Ltd\HO04-Tender 营销组织-LK26XX CIFC Project - Documents\2-3-3 工程量核算 Quantities\BOQ Prep\CIFC BOQ_v4.1.xlsx"`
Expected: 打印 `审阅稿：...CIFC BOQ_v4.1_审阅稿.html（N 行）`，N 与旧版 `CIFC BOQ_v4.1 清单（B-E）.html` 的表体行数（减去重复表头 1 行）一致。

- [ ] **Step 2: 起本机临时 HTTP 服务并打开**

后台运行（`run_in_background`）：`cd "<BOQ Prep 目录>" && python -m http.server 8765 --bind 127.0.0.1`；内置浏览器 navigate `http://127.0.0.1:8765/CIFC%20BOQ_v4.1_%E5%AE%A1%E9%98%85%E7%A8%BF.html`。

- [ ] **Step 3: 页面脚本检查（javascript_tool）**

```js
var w=document.querySelector('.wrap');w.scrollTop=3000;await new Promise(r=>setTimeout(r,300));
var stuck=Math.abs(document.querySelector('thead th').getBoundingClientRect().top-w.getBoundingClientRect().top)<2;
var tds=document.querySelectorAll('#t tbody tr:not(.chapter) td[data-c="zh"]');
tds[0].innerText=tds[0].dataset.orig+'（测试）';tds[0].dispatchEvent(new Event('input'));
tds[1].innerText=tds[1].dataset.orig+'（测试）';tds[1].dispatchEvent(new Event('input'));
var n=document.querySelector('#t tbody tr td[data-c="note"]');n.innerText='测试意见';n.dispatchEvent(new Event('input'));
var prev=DATA.review;DATA.review={saved_at:'T',edits:sorted(vals(edits)),comments:sorted(vals(notes))};
var h=buildHTML();DATA.review=prev;
var doc=new DOMParser().parseFromString(h,'text/html');
var d=JSON.parse(doc.getElementById('review-data').textContent);
({stuck:stuck,buttons:[...document.querySelectorAll('.bar button')].map(b=>b.innerText),
  cntE:document.getElementById('cntE').textContent,cntN:document.getElementById('cntN').textContent,
  savedEdits:d.review.edits.length,savedNotes:d.review.comments.length,
  cloneClean:doc.querySelectorAll('td.edited,tr.noted').length===0,
  firstBodyCode:document.querySelector('#t tbody td[data-c="code"]').innerText})
```
Expected: `stuck:true`，按钮恰为 `["保存","复制变更清单","重置列宽","清除全部编辑"]`，`cntE:"2"`，`cntN:"1"`，`savedEdits:2`，`savedNotes:1`，`cloneClean:true`，`firstBodyCode` 不为 `No.`；`read_console_messages(onlyErrors)` 无报错。

- [ ] **Step 4: 重开与取消保存检查**

在页面执行：`window.showSaveFilePicker=async()=>{throw new DOMException('x','AbortError')};await saveFile();({savedAt:DATA.review.saved_at})` → Expected `savedAt:null`（取消后未前进）。然后 reload 页面，检查 `cntE` 为 `"2"`、`cntN` 为 `"1"`（本地暂存恢复），最后执行 `clearAll` 前先覆盖 `window.confirm=()=>true`，调用 `clearAll()` 清掉测试编辑，确认 `cntE`、`cntN` 为 `"0"`。

- [ ] **Step 5: 读回链路检查**

用 Python 把 Step 3 的同款记录注入审阅稿副本（scratchpad 内，测试里的 `inject` 逻辑），运行 `review_read.py <副本>`，Expected：校验通过、修改 2 处、意见 1 条。删除副本。停掉 HTTP 服务（TaskStop），关闭标签页。

- [ ] **Step 6: 更新知识库**

`工作/概览.md` 中以 `- **大改清单先出 HTML 审阅稿**` 开头的那一条，替换为：
`- **大改清单先出 HTML 审阅稿**：用 \`pk-boq-review\` 技能生成 \`<清单名>_审阅稿.html\`（编号、英文描述、中文描述、单位 + 审阅意见列），在浏览器里改单元格、写意见、保存，AI 下一轮读回后按版本与标记约定改版。（来源：用户 2026-10-06 本会话；技能 \`~/.claude/skills/pk-boq-review/\`）`
并在 `变更日志.md` 末尾追加：
`2026-10-06 | Claude Code | 工作/概览.md | 「大改清单先出 HTML 审阅稿」改为指向 pk-boq-review 技能 | 技能上线`

- [ ] **Step 7: 交用户手测保存对话框**

告诉用户：用 Edge 打开 `CIFC BOQ_v4.1_审阅稿.html`，改一格、写一条意见，点"保存"，在对话框里选到 `BOQ Prep` 文件夹并覆盖；然后告诉 AI"读审阅稿"，AI 运行 `review_read.py` 核对。
