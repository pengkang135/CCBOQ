"""V2 Finalize (no-writeback mode):
Merge all V2 outputs (auto + 3 Matchers + Auditor + rebar fix) → BQ-Code-keyed JSON + HTML report.

Since the source .xlsx is being live-edited by the user, we do NOT write to _AI版.xlsx.
Instead we produce standalone artifacts keyed by BQ Code (stable across row shifts).
"""
import json, html
from datetime import datetime
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(r"f:\BaiduSyncdisk\5.报价\2026-7 泰国CMI移动MOD2数据中心")
TEMP = ROOT / "temp"
REPORT_DIR = ROOT / "4 BQ" / "2026-7-29 第二版" / "2026-07-29_CMI_MOD2_BOQ_合并报表_套价版_套价报告"

STATUS_LABEL = {"high":"高置信","medium":"中置信","low":"低置信","estimated":"估值(换算)","no_match":"无匹配","construction_only":"施工措施","skip":"暂定金/开办费"}
STATUS_COLOR = {"high":"#27ae60","medium":"#f39c12","low":"#e74c3c","estimated":"#8e44ad","no_match":"#95a5a6","construction_only":"#7f8c8d","skip":"#7f8c8d"}

REBAR_ROWS = {54, 178, 268}

def load_flex(p):
    d = json.loads(p.read_text(encoding="utf-8"))
    return d["items"] if isinstance(d, dict) and "items" in d else d

def merge_all():
    merged = {}
    for name in ["v2_auto_matched.json", "v2_matcher_A.json", "v2_matcher_B.json", "v2_matcher_C.json"]:
        p = TEMP / name
        if not p.exists():
            continue
        for x in load_flex(p):
            merged[x["excel_row"]] = x
    # Apply rebar fix
    for r in REBAR_ROWS:
        m = merged.get(r)
        if m and m.get("matched_price_thb") and (m.get("matched_unit") or "").lower().replace(".","") in ("t","ton","tonne"):
            old = m["matched_price_thb"]
            m["matched_price_thb"] = round(float(old) / 1000, 4)
            m["matched_unit"] = "kg"
            m["reasoning"] = f"[REBAR FIX t→kg÷1000] {old} → {m['matched_price_thb']}/kg | " + (m.get("reasoning") or "")[:180]
    # Apply auditor
    audp = TEMP / "v2_auditor_out.json"
    if audp.exists():
        aud = json.loads(audp.read_text(encoding="utf-8"))
        for a in aud:
            r = a["excel_row"]
            if r not in merged:
                continue
            action = a.get("action", "confirm")
            if action == "redo":
                m = merged[r]
                m.update({
                    "matched_id": a.get("new_matched_id") or m.get("matched_id"),
                    "matched_name": a.get("new_matched_name") or m.get("matched_name"),
                    "matched_unit": a.get("new_matched_unit") or m.get("matched_unit"),
                    "matched_price_thb": a.get("new_matched_price_thb") or m.get("matched_price_thb"),
                    "converted_price_thb": a.get("new_converted_price_thb"),
                    "matched_project": a.get("new_matched_project") or m.get("matched_project"),
                    "matched_supplier": a.get("new_matched_supplier") or m.get("matched_supplier"),
                    "matched_date": a.get("new_matched_date") or m.get("matched_date"),
                    "status": a.get("new_status") or m.get("status"),
                    "reasoning": f"[Aud↺] {a.get('note','')[:100]} | {m.get('reasoning','')[:80]}",
                })
    return merged

def h(s):
    return html.escape(str(s) if s is not None else "")

def eff_price(rec):
    return rec.get("converted_price_thb") or rec.get("matched_price_thb")

def main():
    boq = {b["excel_row"]: b for b in json.loads((TEMP / "boq_items.json").read_text(encoding="utf-8"))}
    merged = merge_all()

    # Build BQ-Code-keyed output (Code is stable across row shifts)
    by_code = {}
    orphan = []  # items without BQ code
    for r, m in merged.items():
        b = boq.get(r, {})
        code = b.get("bq_code") or ""
        entry = {
            "bq_code": code,
            "original_excel_row": r,
            "discipline": b.get("discipline", ""),
            "category": b.get("category", ""),
            "subcategory": b.get("subcategory", ""),
            "description_en": b.get("description_en", ""),
            "boq_unit": b.get("unit", ""),
            "boq_qty": b.get("qty", 0),
            "status": m.get("status"),
            "family": m.get("family", ""),
            "matched_name": m.get("matched_name"),
            "matched_unit": m.get("matched_unit"),
            "matched_price_thb": m.get("matched_price_thb"),
            "converted_price_thb": m.get("converted_price_thb"),
            "eff_price_thb": eff_price(m),
            "matched_project": m.get("matched_project"),
            "matched_supplier": m.get("matched_supplier"),
            "matched_date": m.get("matched_date"),
            "reasoning": (m.get("reasoning") or "")[:300],
        }
        if code:
            by_code[code] = entry
        else:
            orphan.append(entry)

    # Save
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_json = REPORT_DIR / f"V2_results_by_bqcode_{ts}.json"
    out_json.write_text(json.dumps({
        "by_bq_code": by_code,
        "orphan_no_code": orphan,
        "generated": ts,
        "note": "BQ-Code-keyed results. Look up your row by F column code, not by row number (source may have shifted).",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"BQ-Code-keyed JSON: {out_json.name} ({out_json.stat().st_size // 1024} KB, {len(by_code)} entries + {len(orphan)} orphans)")

    # HTML report — same format as before but linked by BQ Code
    rows = []
    for e in list(by_code.values()) + orphan:
        rows.append(e)
    rows.sort(key=lambda x: x["original_excel_row"])

    cur = Counter(r["status"] for r in rows)
    disc_stats = {}
    fam_stats = {}
    for r in rows:
        disc_stats.setdefault(r["discipline"] or "?", Counter())[r["status"]] += 1
        fam_stats.setdefault(r["family"] or "?", Counter())[r["status"]] += 1

    total = len(rows)
    matched = cur.get("high",0) + cur.get("medium",0) + cur.get("low",0) + cur.get("estimated",0)
    match_rate = round(100 * matched / max(total, 1), 1)

    detail_rows = []
    for r in rows:
        col = STATUS_COLOR.get(r["status"], "#95a5a6")
        badge = f'<span style="background:{col};color:white;padding:2px 6px;border-radius:3px;font-size:10px;">{STATUS_LABEL.get(r["status"], r["status"])}</span>'
        ep = r["eff_price_thb"]
        pd = f"{ep:,.2f}" if ep else "—"
        detail_rows.append(f'''<tr data-status="{r['status']}" data-disc="{h(r['discipline'])}" data-fam="{h(r['family'])}">
<td class="mono">{h(r['bq_code'][:35])}</td>
<td class="num">{r['original_excel_row']}</td>
<td>{h(r['discipline'])}</td>
<td class="fam">{h(r['family'])}</td>
<td class="desc" title="{h(r['description_en'])}">{h(r['description_en'][:60])}</td>
<td>{h(r['boq_unit'])}</td>
<td class="num">{r['boq_qty']:,.1f}</td>
<td>{badge}</td>
<td class="desc" title="{h(r['matched_name'] or '')}">{h((r['matched_name'] or '')[:50])}</td>
<td>{h(r['matched_unit'] or '')}</td>
<td class="price">{pd}</td>
<td class="reason" title="{h(r['reasoning'])}">{h(r['reasoning'][:80])}</td>
</tr>''')

    disc_rows = []
    for d, cnt in sorted(disc_stats.items()):
        tot = sum(cnt.values())
        m = cnt.get("high",0) + cnt.get("medium",0) + cnt.get("low",0) + cnt.get("estimated",0)
        rate = round(100*m/tot, 1) if tot else 0
        disc_rows.append(f'<tr><td><strong>{h(d)}</strong></td><td class="num">{tot}</td>'
                         f'<td class="num">{cnt.get("high",0)}</td><td class="num">{cnt.get("medium",0)}</td>'
                         f'<td class="num">{cnt.get("low",0)}</td><td class="num">{cnt.get("estimated",0)}</td>'
                         f'<td class="num">{cnt.get("no_match",0)}</td><td class="num">{cnt.get("construction_only",0)}</td>'
                         f'<td class="num">{cnt.get("skip",0)}</td><td class="num">{rate}%</td></tr>')

    fam_rows = []
    for f, cnt in sorted(fam_stats.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(cnt.values())
        m = cnt.get("high",0) + cnt.get("medium",0) + cnt.get("low",0) + cnt.get("estimated",0)
        rate = round(100*m/tot, 1) if tot else 0
        fam_rows.append(f'<tr><td>{h(f)}</td><td class="num">{tot}</td>'
                        f'<td class="num">{cnt.get("high",0)}</td><td class="num">{cnt.get("medium",0)}</td>'
                        f'<td class="num">{cnt.get("low",0)}</td><td class="num">{cnt.get("estimated",0)}</td>'
                        f'<td class="num">{cnt.get("no_match",0)}</td><td class="num">{rate}%</td></tr>')

    ts_h = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_html = REPORT_DIR / f"BQ匹配报告_V2_{ts}.html"
    html_out = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>BQ V2 报告 — {ts}</title>
<style>
body{{font-family:'Microsoft YaHei','PingFang SC',sans-serif;margin:0;padding:20px;background:#f5f6fa;color:#2c3e50;}}
.container{{max-width:1900px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#8e44ad,#3498db);color:white;padding:24px 32px;border-radius:8px;margin-bottom:20px;}}
.header h1{{margin:0 0 8px 0;font-size:22px;}} .header p{{margin:4px 0;opacity:0.9;font-size:13px;}}
.notice{{background:#fff3cd;border:1px solid #ffc107;color:#856404;padding:12px 16px;border-radius:6px;margin-bottom:20px;font-size:13px;}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px;}}
.card{{background:white;border-radius:8px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.08);}}
.card .num{{font-size:26px;font-weight:700;margin:4px 0;}} .card .label{{font-size:12px;color:#7f8c8d;}}
.section{{background:white;border-radius:8px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08);}}
.section h2{{margin:0 0 12px 0;font-size:16px;border-bottom:2px solid #8e44ad;padding-bottom:8px;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:#34495e;color:white;padding:8px 6px;text-align:left;position:sticky;top:0;z-index:1;}}
td{{padding:6px;border-bottom:1px solid #ecf0f1;vertical-align:top;}}
tr:hover{{background:#eef5fb!important;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}}
.mono{{font-family:'Consolas','Menlo',monospace;font-size:10px;color:#2980b9;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.desc{{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.fam{{font-size:10px;color:#8e44ad;font-weight:600;}}
.price{{text-align:right;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap;}}
.reason{{max-width:320px;font-size:10px;color:#7f8c8d;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.filters{{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;}}
.filters select,.filters input{{padding:6px 10px;border:1px solid #ddd;border-radius:4px;font-size:12px;}}
.detail-table{{max-height:850px;overflow-y:auto;}}
tr[data-status="no_match"]{{background:#fff5f5;}} tr[data-status="low"]{{background:#fffbf0;}}
tr[data-status="construction_only"]{{background:#f8f9fa;}} tr[data-status="estimated"]{{background:#faf5ff;}}
</style></head><body><div class="container">

<div class="header">
<h1>CMI MOD2 泰国数据中心 — BQ 匹配报告 <span style="background:#e74c3c;padding:2px 8px;border-radius:4px;font-size:14px;">V2</span></h1>
<p>V2 优化: 术语表 389 词 · 家族归类 35 类 · rate 池去重 (10716→3028, 省 71.7%) · 规则自动分类 · Sonnet 只处理疑难 · 家族批搜 Auditor</p>
<p>生成时间: {ts_h}</p>
</div>

<div class="notice">
<strong>⚠ 说明</strong>：用户在实时编辑源文件 <code>套价版.xlsx</code>，行号已发生位移。本报告的"原行号"仅供参考，请通过 <code>BQ Code</code>（F 列，第一列蓝色单元格）在你的当前文件中定位对应行。
配套 JSON <code>V2_results_by_bqcode_{ts}.json</code> 已按 BQ Code 索引，可用作查表。
</div>

<div class="cards">
<div class="card"><div class="label">AI 处理项</div><div class="num" style="color:#2c3e50">{total}</div></div>
<div class="card"><div class="label">High</div><div class="num" style="color:#27ae60">{cur.get('high',0)}</div></div>
<div class="card"><div class="label">Medium</div><div class="num" style="color:#f39c12">{cur.get('medium',0)}</div></div>
<div class="card"><div class="label">Low</div><div class="num" style="color:#e74c3c">{cur.get('low',0)}</div></div>
<div class="card"><div class="label">Estimated</div><div class="num" style="color:#8e44ad">{cur.get('estimated',0)}</div></div>
<div class="card"><div class="label">No Match</div><div class="num" style="color:#95a5a6">{cur.get('no_match',0)}</div></div>
<div class="card"><div class="label">施工措施</div><div class="num" style="color:#7f8c8d">{cur.get('construction_only',0)}</div></div>
<div class="card"><div class="label">Skip</div><div class="num" style="color:#7f8c8d">{cur.get('skip',0)}</div></div>
<div class="card"><div class="label">匹配率</div><div class="num" style="color:#8e44ad">{match_rate}%</div></div>
</div>

<div class="section"><h2>按专业分布</h2>
<table><thead><tr><th>专业</th><th>总计</th><th>High</th><th>Medium</th><th>Low</th><th>Est</th><th>NoMatch</th><th>施工</th><th>Skip</th><th>匹配率</th></tr></thead>
<tbody>{''.join(disc_rows)}</tbody></table></div>

<div class="section"><h2>按家族分布</h2>
<table><thead><tr><th>家族</th><th>总计</th><th>High</th><th>Medium</th><th>Low</th><th>Est</th><th>NoMatch</th><th>匹配率</th></tr></thead>
<tbody>{''.join(fam_rows)}</tbody></table></div>

<div class="section"><h2>匹配明细（{total} 条，按 BQ Code 索引）</h2>
<div class="filters">
<label>置信度:<select id="fs"><option value="">全部</option>
<option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
<option value="estimated">Estimated</option><option value="no_match">No Match</option>
<option value="construction_only">施工措施</option><option value="skip">Skip</option></select></label>
<label>专业:<select id="fd"><option value="">全部</option>
{''.join(f'<option value="{h(d)}">{h(d)}</option>' for d in sorted(disc_stats.keys()))}</select></label>
<label>家族:<select id="ff"><option value="">全部</option>
{''.join(f'<option value="{h(f)}">{h(f)}</option>' for f in sorted(fam_stats.keys()))}</select></label>
<label>关键字:<input id="fk" placeholder="搜索行内容或 BQ Code"></label>
<span id="rc" style="font-size:12px;color:#7f8c8d;padding:6px;"></span>
</div>
<div class="detail-table"><table><thead><tr><th>BQ Code</th><th>原行</th><th>专业</th><th>家族</th><th>BOQ 描述</th><th>单位</th><th>数量</th><th>置信度</th><th>匹配名称</th><th>单位</th><th>THB 单价</th><th>匹配理由</th></tr></thead>
<tbody>{''.join(detail_rows)}</tbody></table></div>
</div>

<div style="text-align:center;color:#95a5a6;font-size:11px;padding:16px;">
V2 分层 LLM 流水线 | 由于源文件正被人工编辑，请以 BQ Code 为准查表
</div></div>
<script>
const rows = document.querySelectorAll('.detail-table tbody tr');
const fs=document.getElementById('fs'),fd=document.getElementById('fd'),ff=document.getElementById('ff'),fk=document.getElementById('fk'),rc=document.getElementById('rc');
function apply(){{
  const s=fs.value,d=fd.value,f=ff.value,k=fk.value.toLowerCase();
  let v=0;rows.forEach(r=>{{const ok=(!s||r.dataset.status===s)&&(!d||r.dataset.disc===d)&&(!f||r.dataset.fam===f)&&(!k||r.textContent.toLowerCase().includes(k));r.style.display=ok?'':'none';if(ok)v++;}});
  rc.textContent=`显示 ${{v}} / {total} 行`;
}}
[fs,fd,ff].forEach(e=>e.addEventListener('change',apply));fk.addEventListener('input',apply);apply();
</script>
</body></html>"""

    out_html.write_text(html_out, encoding="utf-8")
    print(f"HTML: {out_html.name} ({out_html.stat().st_size // 1024} KB)")

    # Console summary
    print()
    print("=" * 60)
    print(f"V2 分档: {dict(cur)}")
    print(f"匹配率: {match_rate}%")
    print(f"BQ Code 覆盖: {len(by_code)} 有 code, {len(orphan)} 无 code")
    print("=" * 60)

if __name__ == "__main__":
    main()
