import json, sys
from pathlib import Path
import yaml

input_path = sys.argv[1] if len(sys.argv) > 1 else 'price_data_enriched.json'
output_path = sys.argv[2] if len(sys.argv) > 2 else 'price_inquiry.html'

# Load tariff rates
script_dir = Path(__file__).resolve().parent
yaml_path = script_dir.parent / 'references' / 'tariff_rates.yaml'
with open(yaml_path, 'r', encoding='utf-8') as f:
    tariff = yaml.safe_load(f)

categories = tariff['categories']

with open(input_path, 'r', encoding='utf-8') as f:
    all_data = json.load(f)

# ── Section-to-tariff-category matching ──
# Uses same keyword matching as enrich_prices.py
# Explicit section name → category_id mapping for ambiguous sections
_section_category_map = {
    'geosynthetics & pvd': 'plastics',
    'pipes & drainage': 'plastics',
    'di & ss pipes': 'industrial',
    'anticorrosive paint': 'industrial',
    'joints & accessories': 'default',
    'earthwork': 'default',
    'construction activities': 'default',
    'line marking': 'default',
    'mix filter': 'raw_materials',
    'gabion & reno mattress': 'raw_materials',
}

def match_tariff_category(section_name):
    """Match HTML section name to tariff category via explicit map then keyword fallback."""
    name = section_name.lower()
    if name in _section_category_map:
        cid = _section_category_map[name]
        for cat in categories:
            if cat['id'] == cid:
                return cat
    for cat in categories:
        for kw in cat['keywords']:
            if kw in name:
                return cat
    return categories[-1]  # default

# Build rate info line for a section
def rate_info_html(cat):
    """Generate the small rate info line below section header."""
    cd = cat['customs_duty']
    rd = cat['regulatory_duty']
    ait = cat['advance_income_tax']
    at = cat['advance_tax']
    fr = cat['freight_pct']
    cl = tariff['bangladesh']['clearance_pct']
    vat = tariff['bangladesh']['vat_rate']
    inland = tariff['bangladesh']['inland_transport_base_usd']

    hs = cat.get('hs_codes', [])
    hs_str = ' &middot; '.join(hs) if hs else 'varies'

    return (
        f'<div class="section-rates">'
        f'HS: {hs_str}<br>'
        f'Freight: {fr:.0%} &middot; '
        f'CD: {cd:.0%} &middot; '
        f'VAT: {vat:.0%} &middot; '
        f'AIT: {ait:.0%} &middot; '
        f'AT: {at:.0%} &middot; '
        f'RD: {rd:.0%} &middot; '
        f'Clearance: {cl:.0%} &middot; '
        f'Inland: ${inland}/t'
        f'</div>'
    )

def get_section(rec):
    mid = rec.get('material_id', '')
    mtype = rec.get('material_type', '')
    mname = rec.get('material_name', '')
    name = (mtype or mname or mid).lower()
    rules = [
        (['pvd', 'prefabricated vertical', 'vertical drain'], 'Geosynthetics & PVD'),
        (['geotextile', 'geotextil', '400gsm', '400g/m2', 'woven'], 'Geosynthetics & PVD'),
        (['steel tubular', 'api 5l x60', 'steel pipe pile', 'lsaw pipe'], 'Steel Tubular Piles'),
        (['phc pile', 'prestressed', 'spun pile'], 'PHC Piles'),
        (['pile shoe'], 'Steel Pile Shoes'),
        (['reinforcement', 'rebar', 'astm a615 rebar', 'deformed bar', 'reinforcing steel'], 'Reinforcement (ASTM A615)'),
        (['shear connector', 'shear stud'], 'Shear Connectors'),
        (['steel plate', 'astm a36'], 'Steel Plates'),
        (['steel mesh', 'b785', 'reinforcement mesh'], 'Steel Mesh (B785)'),
        (['ductile iron', 'di pipe', 'stainless steel', 'ss316'], 'DI & SS Pipes'),
        (['sand', 'fill sand', 'backfill'], 'Sand & Fill'),
        (['rock', 'armour', 'boulder', 'underlayer', 'stone 5', 'crushed', 'stone '], 'Rock & Stone'),
        (['rubble'], 'Rubble Stone'),
        (['mix filter', 'filter material'], 'Mix Filter'),
        (['gabion', 'reno mattress'], 'Gabion & Reno Mattress'),
        (['concrete 5000psi', 'concrete 4000psi', 'rmc', 'ready mix', 'site batch', 'concrete c32', 'concrete c35', 'concrete c25', 'concrete c30', 'cement opc', 'cement price', 'cement bag'], 'Concrete & Cement'),
        (['pavement', 'paver', 'block paving', 'block sett', 'heavy container', 'heavy duty concrete', 'rtg runway', 'yard road', 'tie in', 'gate complex'], 'Pavement'),
        (['kerb', 'barrier', 'edge restraint'], 'Kerb & Barriers'),
        (['concrete mattress'], 'Concrete Mattress'),
        (['box culvert', 'outfall'], 'Box Culvert & Outfall'),
        (['line marking', 'thermoplastic', 'lane', 'hatching', 'linemarking'], 'Line Marking'),
        (['excavation', 'earthwork'], 'Earthwork'),
        (['paint', 'anticorrosive', 'coating', 'ndft', 'epoxy', 'marine paint'], 'Anticorrosive Paint'),
        (['hdpe', 'drainage pipe', 'slot drain', 'gatic', 'upvc', 'ducting', 'corrugated', 'hdp pipe'], 'Pipes & Drainage'),
        (['expansion joint', 'water bar', 'waterstop', 'warning tape', 'draw rope'], 'Joints & Accessories'),
        (['compaction', 'tamping', 'vibroflotation', 'vibratory'], 'Construction Activities'),
    ]
    for keywords, section in rules:
        if any(k in name for k in keywords):
            return section
    return 'Other'

sections = {}
for rec in all_data:
    sec = get_section(rec)
    sections.setdefault(sec, []).append(rec)

sec_order = [
    'Geosynthetics & PVD', 'Steel Tubular Piles', 'PHC Piles', 'Steel Pile Shoes',
    'Reinforcement (ASTM A615)', 'Shear Connectors', 'Steel Plates', 'Steel Mesh (B785)',
    'DI & SS Pipes', 'Sand & Fill', 'Rock & Stone', 'Rubble Stone', 'Mix Filter',
    'Gabion & Reno Mattress', 'Concrete & Cement', 'Pavement', 'Kerb & Barriers',
    'Concrete Mattress', 'Box Culvert & Outfall', 'Line Marking',
    'Anticorrosive Paint', 'Pipes & Drainage', 'Joints & Accessories',
    'Earthwork', 'Construction Activities', 'Other',
]

total = len(all_data)
with_price = sum(1 for r in all_data if r.get('price_ddp') is not None)
unpriced = total - with_price

origins = {}
for r in all_data:
    o = r.get('origin', '??')
    origins[o] = origins.get(o, 0) + 1

sec_count = len(sections)
cn_count = origins.get('CN', 0)
in_count = origins.get('IN', 0)
bd_count = origins.get('BD', 0)

def fmt_price(val, is_bold=False):
    if val is None:
        return '<td class="td-na">—</td>'
    cls = 'td-price-bold' if is_bold else 'td-price'
    try:
        return f'<td class="{cls}">${float(val):,.2f}</td>'
    except:
        return f'<td class="{cls}">{val}</td>'

def badge_html(rtype):
    t = (rtype or '').lower()
    if '供应商' in t or 'supplier' in t:
        return '<span class="b b-s" title="Supplier quote">SQ</span>'
    elif '平台' in t or 'platform' in t:
        return '<span class="b b-p" title="Platform reference">PR</span>'
    elif '市场' in t or 'market' in t:
        return '<span class="b b-m" title="Market estimate">ME</span>'
    else:
        return '<span class="b b-r" title="No public price — RFQ needed">RFQ</span>'

def basis_tag(basis):
    m = {'EXW': 'EXW', 'FOB': 'FOB', 'CIF': 'CIF', 'DDP': 'DDP', 'LOCAL': 'DDP'}
    return m.get(basis, basis or '')

html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Laldia Terminal — Material Price Inquiry</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #f4f7fb;
  --surface: #fff;
  --border: #e2e8f0;
  --border-hover: #cbd5e1;
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --accent: #2563eb;
  --accent-light: #eff6ff;
  --blue: #2563eb;
  --blue-light: #eff6ff;
  --green: #059669;
  --green-light: #ecfdf5;
  --red: #dc2626;
  --red-light: #fef2f2;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text-primary);
  font-family: 'Bricolage Grotesque', system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

/* ── Toolbar ── */
.toolbar {
  position: sticky; top: 0; z-index: 100;
  background: rgba(255,255,255,0.96);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 10px 24px;
  display: flex; align-items: center; gap: 16px;
  flex-wrap: wrap;
}
.toolbar-brand {
  font-size: 14px; font-weight: 700; color: var(--text-primary);
  letter-spacing: -0.02em; white-space: nowrap;
  border-right: 1px solid var(--border); padding-right: 16px; margin-right: 4px;
}
.toolbar-meta {
  display: flex; gap: 16px; font-size: 11px; color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace; flex-wrap: wrap;
}
.toolbar-meta strong { color: var(--text-secondary); font-weight: 600; }
.toolbar-nav {
  display: flex; gap: 3px; flex-wrap: wrap; margin-left: auto;
  max-height: 28px; overflow: hidden;
}
.toolbar-nav a {
  font-size: 10px; font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted); text-decoration: none;
  padding: 2px 7px; border-radius: 4px;
  border: 1px solid transparent; white-space: nowrap;
  transition: all 0.15s;
}
.toolbar-nav a:hover { color: var(--text-primary); background: var(--border); }

/* ── Hero ── */
.hero {
  padding: 28px 24px 20px; max-width: 1600px; margin: 0 auto;
}
.hero h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.03em; }
.hero-sub { font-size: 12px; color: var(--text-muted); margin-top: 6px; display: flex; gap: 20px; flex-wrap: wrap; }

/* ── Stats ── */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: 8px; padding: 0 24px 16px; max-width: 1600px; margin: 0 auto;
}
.stat {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px;
}
.stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }
.stat-value { font-size: 1.4rem; font-weight: 700; letter-spacing: -0.02em; margin-top: 2px; }
.stat-value.accent { color: var(--accent); }

/* ── Methodology ── */
.methodology {
  max-width: 1600px; margin: 0 auto; padding: 0 24px 16px;
}
.method-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px 20px;
}
.method-card h3 {
  font-size: 12px; font-weight: 600; margin-bottom: 10px;
  letter-spacing: -0.01em;
}
.method-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
}
.method-item {
  font-size: 11px; color: var(--text-secondary);
  padding: 6px 10px; background: #f4f7fb;
  border-radius: 5px;
  font-family: 'JetBrains Mono', monospace;
}
.method-item strong { color: var(--text-primary); font-weight: 600; }
.method-item .tag {
  display: inline-block; font-size: 9px; font-weight: 700;
  padding: 1px 5px; border-radius: 3px;
  margin-right: 4px;
}
.tag-exw { background: #eef2ff; color: #4338ca; }
.tag-fob { background: #eff6ff; color: #1e40af; }
.tag-cif { background: #eff6ff; color: #1e40af; }
.tag-ddp { background: #f0fdfa; color: #115e59; }

/* ── Legend ── */
.legend {
  max-width: 1600px; margin: 0 auto; padding: 0 24px 12px;
  font-size: 10px; color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}
.legend > div {
  display: flex; gap: 14px; flex-wrap: wrap; align-items: center;
}
.legend .b { margin-right: 2px; }

/* ── Sections ── */
.main { max-width: 1600px; margin: 0 auto; padding: 0 24px 60px; }

.section {
  margin-bottom: 20px;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface);
}
.section-header {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 18px 6px 18px;
  cursor: pointer; user-select: none;
  transition: background 0.15s;
}
.section-header:hover { background: #e8ecf1; }
.section-name { font-size: 13px; font-weight: 600; letter-spacing: -0.01em; }
.section-count {
  font-family: 'JetBrains Mono', monospace; font-size: 10px;
  color: var(--text-muted); background: #f4f7fb;
  padding: 2px 10px; border-radius: 10px;
}
.section-arrow { font-size: 10px; color: var(--text-muted); margin-left: auto; transition: transform 0.2s; }
.section-rates {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px; color: var(--text-muted);
  padding: 2px 18px 8px 18px;
  border-bottom: 1px solid var(--border);
  letter-spacing: -0.01em;
}

/* ── Tables ── */
.table-wrap { overflow-x: auto; }
table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 11.5px; }
thead th {
  font-family: 'JetBrains Mono', monospace; font-size: 9.5px;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--text-muted); text-align: right; padding: 8px 5px;
  background: #f1f5f9; border-bottom: 2px solid var(--border);
  white-space: nowrap;
  position: static;
}
thead th:first-child { text-align: left; padding-left: 12px; }
thead th.th-name { text-align: left; }
thead th.th-supplier { text-align: left; }
thead th.th-source { text-align: left; overflow: hidden; text-overflow: ellipsis; }
thead th.th-applies { text-align: left; }
thead th.th-price { color: var(--accent); font-weight: 600; font-size: 9px; }

thead th:nth-child(1), tbody td:nth-child(1) { width: 14%; min-width: 100px; }
thead th:nth-child(2), tbody td:nth-child(2) { width: 9%; }
thead th:nth-child(3), tbody td:nth-child(3) { width: 2.5%; }
thead th:nth-child(4), tbody td:nth-child(4) { width: 5%; }
thead th:nth-child(5), tbody td:nth-child(5) { width: 5%; }
thead th:nth-child(6), tbody td:nth-child(6) { width: 5%; }
thead th:nth-child(7), tbody td:nth-child(7) { width: 5%; }
thead th:nth-child(8), tbody td:nth-child(8) { width: 5.5%; }
thead th:nth-child(9), tbody td:nth-child(9) { width: 3%; }
thead th:nth-child(10), tbody td:nth-child(10) { width: 3%; }
thead th:nth-child(11), tbody td:nth-child(11) { width: 33%; }
thead th:nth-child(12), tbody td:nth-child(12) { width: 9.5%; }

tbody td {
  padding: 7px 5px;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: middle;
  text-align: right;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
tbody td:first-child { text-align: left; padding-left: 12px; }
tbody tr:hover td { background: #f0f4f8; }
tbody tr:last-child td { border-bottom: none; }

.td-name { font-family: 'Bricolage Grotesque', system-ui, sans-serif !important; font-weight: 500; color: var(--text-primary); font-size: 11.5px !important; text-align: left !important; }
.td-supplier { font-family: 'Bricolage Grotesque', system-ui, sans-serif !important; font-size: 10.5px !important; color: var(--text-secondary); text-align: left !important; }
.td-price { font-weight: 400; color: #94a3b8; white-space: nowrap; }
.td-price-bold { font-weight: 700; color: var(--accent); white-space: nowrap; }
.td-na { color: #94a3b8; font-style: italic; }
.td-origin { font-size: 9.5px; font-weight: 700; color: var(--text-muted); text-align: center !important; }

.td-source {
  font-family: 'Bricolage Grotesque', system-ui, sans-serif !important;
  font-size: 10px !important; color: var(--text-secondary); text-align: left !important;
  overflow: hidden; text-overflow: ellipsis;
}
.td-source a {
  color: inherit; text-decoration: none;
  transition: color 0.15s;
}
.td-source a:hover { color: var(--blue); }
.td-source .src-link-arrow { color: var(--text-muted); font-size: 9px; margin-left: 1px; }
.td-source a:hover .src-link-arrow { color: var(--blue); }
.td-source .src-tag {
  display: inline-block; font-size: 8px; font-weight: 700; font-family: 'JetBrains Mono', monospace;
  padding: 1px 4px; border-radius: 3px; margin-right: 4px;
  vertical-align: middle;
}
.src-fob { background: #eff6ff; color: #1e40af; }
.src-exw { background: #eef2ff; color: #4338ca; }
.src-cif { background: #eff6ff; color: #1e40af; }
.src-ddp { background: #f0fdfa; color: #115e59; }
.src-rfq { background: #fef2f2; color: #991b1b; }

.td-applies { font-size: 9px !important; color: var(--text-muted); text-align: left !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Badges ── */
.b {
  display: inline-block; font-family: 'JetBrains Mono', monospace;
  font-size: 8px; font-weight: 700; padding: 1px 5px; border-radius: 3px;
  letter-spacing: 0.04em;
}
.b-s { background: var(--blue-light); color: var(--blue); }
.b-p { background: var(--accent-light); color: var(--accent); }
.b-m { background: var(--green-light); color: var(--green); }
.b-r { background: var(--red-light); color: var(--red); }

/* ── Footer ── */
.footer {
  max-width: 1600px; margin: 0 auto; padding: 20px 24px 40px;
  border-top: 1px solid var(--border);
  font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--text-muted);
  display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px;
}

@media (max-width: 768px) {
  .toolbar { padding: 8px 12px; gap: 8px; }
  .hero, .stats, .main, .methodology, .legend { padding-left: 12px; padding-right: 12px; }
  .hero h1 { font-size: 1.2rem; }
  thead th, tbody td { padding: 5px 5px; font-size: 10px; }
  .toolbar-nav { display: none; }
}
</style>
</head>
<body>

<div class="toolbar">
  <span class="toolbar-brand">TH26-015 Laldia Terminal <span style="font-size:9px;background:var(--accent);color:#fff;padding:1px 6px;border-radius:3px;margin-left:6px;">v4</span></span>
  <span class="toolbar-meta">
    <span>Records <strong>__TOTAL__</strong></span>
    <span>Priced <strong>__WITH_PRICE__</strong></span>
    <span>Categories <strong>__SEC_COUNT__</strong></span>
    <span>2026-06-02</span>
    <span>1 USD ≈ 121 BDT / 85 INR / 7.2 CNY</span>
  </span>
  <span class="toolbar-nav">
'''

for s in sec_order:
    if s in sections and sections[s]:
        slug = s.lower().replace(' ','-').replace('(','').replace(')','').replace('/','-')
        html += f'<a href="#{slug}">{s}</a>\n'

html += '''  </span>
</div>

<div class="hero">
  <h1>Material Price Inquiry Report</h1>
  <div class="hero-sub">
    <span>Project TH26-015 · Chittagong, Bangladesh</span>
    <span>All prices in USD · DDP prices exclude VAT</span>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="stat-label">Total Records</div><div class="stat-value">__TOTAL__</div></div>
  <div class="stat"><div class="stat-label">DDP (ex. VAT)</div><div class="stat-value accent">__WITH_PRICE__</div></div>
  <div class="stat"><div class="stat-label">Need RFQ</div><div class="stat-value">__UNPRICED__</div></div>
  <div class="stat"><div class="stat-label">Categories</div><div class="stat-value">__SEC_COUNT__</div></div>
  <div class="stat"><div class="stat-label">Origin CN</div><div class="stat-value" style="font-size:1.2rem;">__CN_COUNT__</div></div>
  <div class="stat"><div class="stat-label">Origin IN</div><div class="stat-value" style="font-size:1.2rem;">__IN_COUNT__</div></div>
  <div class="stat"><div class="stat-label">Origin BD</div><div class="stat-value" style="font-size:1.2rem;">__BD_COUNT__</div></div>
</div>

'''

# Methodology section
html += '''<div class="methodology">
  <div class="method-card">
    <h3>Delivery Term Estimation Methodology</h3>
    <div class="method-grid">
      <div class="method-item">
        <span class="tag tag-exw">EXW</span> <strong>Ex-Works</strong><br>
        Factory gate price at supplier location.
      </div>
      <div class="method-item">
        <span class="tag tag-fob">FOB</span> <strong>Free On Board</strong><br>
        EXW + inland transport + port handling<br>
        <em>Factor: CN +4% / IN +2% / BD +2% / EU +5%</em>
      </div>
      <div class="method-item">
        <span class="tag tag-cif">CIF</span> <strong>Cost Insurance Freight</strong><br>
        FOB + sea freight + marine insurance to Chittagong<br>
        <em>Factor: Steel +8% / Heavy bulk +35% / Others +10-12%</em>
      </div>
      <div class="method-item">
        <span class="tag tag-ddp">DDP</span> <strong>Delivered Duty Paid (ex. VAT)</strong><br>
        CIF + CD + AIT + AT + RD + clearance + inland transport<br>
        <em>Excludes VAT (recoverable input tax) and AT (creditable advance tax). See section headers.</em>
      </div>
      <div class="method-item">
        <span class="tag tag-ddp">DDP</span> <strong>Delivered Duty Paid (inc. VAT)</strong><br>
        DDP ex.VAT + CIF &times; (1 + CD) &times; VAT<br>
        <em>Gross DDP including non-recoverable VAT for budgeting reference.</em>
      </div>
    </div>
  </div>
</div>

<div class="legend">
  <div>
    <span>Price type:</span>
    <span><span class="b b-s">SQ</span> Supplier Quote</span>
    <span><span class="b b-p">PR</span> Platform Reference</span>
    <span><span class="b b-m">ME</span> Market Estimate</span>
    <span><span class="b b-r">RFQ</span> No public price — RFQ needed</span>
    <span style="margin-left:12px;">Source tag = actual price basis found; <strong style="color:var(--accent);">bold</strong> = confirmed price column</span>
  </div>
  <div style="margin-top:4px;">
    <span>DDP (ex. VAT) = CIF &times; (1 + CD + AIT + AT + RD + Clearance) + Inland</span>
    <span style="margin-left:16px;">DDP (inc. VAT) = DDP ex.VAT + CIF &times; (1 + CD) &times; VAT</span>
    <span style="margin-left:16px;">CD: Customs Duty</span>
    <span style="margin-left:8px;">VAT: Value Added Tax</span>
    <span style="margin-left:8px;">AIT: Advance Income Tax</span>
    <span style="margin-left:8px;">AT: Advance Tax</span>
    <span style="margin-left:8px;">RD: Regulatory Duty</span>
  </div>
  <div style="margin-top:2px;">
    <span>EXW: Ex-Works</span>
    <span style="margin-left:8px;">FOB: Free On Board</span>
    <span style="margin-left:8px;">CIF: Cost Insurance Freight</span>
    <span style="margin-left:8px;">DDP: Delivered Duty Paid</span>
  </div>
</div>

<main class="main">
'''

for sec in sec_order:
    if sec not in sections or not sections[sec]:
        continue
    items = sections[sec]
    slug = sec.lower().replace(' ','-').replace('(','').replace(')','').replace('/','-')

    # Match tariff category for this section
    tariff_cat = match_tariff_category(sec)
    rate_line = rate_info_html(tariff_cat)

    html += f'''<div class="section" id="{slug}">
  <div class="section-header" onclick="var r=this.nextElementSibling;var t=r.nextElementSibling;r.style.display=r.style.display==='none'?'block':'none';t.style.display=t.style.display==='none'?'block':'none';var a=this.querySelector('.section-arrow');a.style.transform=r.style.display==='none'?'rotate(-90deg)':'rotate(0)'">
    <span class="section-name">{sec}</span>
    <span class="section-count">{len(items)}</span>
    <span class="section-arrow">&#9660;</span>
  </div>
  {rate_line}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th class="th-name">Material</th>
          <th class="th-supplier">Supplier</th>
          <th>Org</th>
          <th class="th-price">EXW</th>
          <th class="th-price">FOB</th>
          <th class="th-price">CIF</th>
          <th class="th-price">DDP<br><span style="font-weight:400;font-size:8px;">ex.VAT</span></th>
          <th class="th-price">DDP<br><span style="font-weight:400;font-size:8px;">inc.VAT</span></th>
          <th>Unit</th>
          <th>Type</th>
          <th class="th-source">Source</th>
          <th class="th-applies">Applies To</th>
        </tr>
      </thead>
      <tbody>
'''
    for rec in items:
        mtype = rec.get('material_type', '')
        mname = rec.get('material_name', '')
        mid = rec.get('material_id', '')
        name_display = mtype or mname or mid
        supplier = rec.get('supplier', '-')
        origin = rec.get('origin', '??')
        basis = rec.get('price_basis', '')
        unit = rec.get('unit', '')
        rtype = rec.get('type', '')
        source = rec.get('source', '')
        url = rec.get('url', '')
        applies = rec.get('applies_to', [])
        if isinstance(applies, list):
            applies_str = ', '.join(str(a) for a in applies[:8])
        else:
            applies_str = str(applies) if applies else str(mid) if mid else ''

        b_exw = (basis == 'EXW')
        b_fob = (basis == 'FOB')
        b_cif = (basis == 'CIF')
        b_ddp = (basis in ('DDP', 'LOCAL'))

        btag = basis or 'RFQ'
        tag_cls = {'EXW':'src-exw', 'FOB':'src-fob', 'CIF':'src-cif', 'DDP':'src-ddp', 'LOCAL':'src-ddp'}.get(btag, 'src-rfq')
        btag_disp = btag
        src_text = source[:90] if source else ''
        if url:
            src_html = f'<span class="src-tag {tag_cls}">{btag_disp}</span><a href="{url}" target="_blank" rel="noopener">{src_text}&thinsp;<span class="src-link-arrow">&#8599;</span></a>'
        else:
            src_html = f'<span class="src-tag {tag_cls}">{btag_disp}</span>{src_text}'

        html += f'''        <tr>
          <td class="td-name">{name_display[:90]}</td>
          <td class="td-supplier">{supplier[:60]}</td>
          <td class="td-origin">{origin}</td>
          {fmt_price(rec.get("price_exw"), b_exw)}
          {fmt_price(rec.get("price_fob"), b_fob)}
          {fmt_price(rec.get("price_cif"), b_cif)}
          {fmt_price(rec.get("price_ddp"), b_ddp)}
          {fmt_price(rec.get("price_ddp_inc_vat"))}
          <td style="color:var(--text-muted);">{unit}</td>
          <td>{badge_html(rtype)}</td>
          <td class="td-source">{src_html}</td>
          <td class="td-applies">{applies_str}</td>
        </tr>
'''

    html += '''      </tbody>
    </table>
  </div>
</div>

'''

html += '''</main>

<footer class="footer">
  <span>Generated 2026-06-02 · All prices estimated in USD · Chittagong, Bangladesh · DDP prices ex. VAT</span>
  <span>SQ=Supplier Quote · PR=Platform Reference · ME=Market Estimate · RFQ=Request for Quotation</span>
</footer>

</body>
</html>'''

html = html.replace('__TOTAL__', str(total))
html = html.replace('__WITH_PRICE__', str(with_price))
html = html.replace('__UNPRICED__', str(unpriced))
html = html.replace('__SEC_COUNT__', str(sec_count))
html = html.replace('__CN_COUNT__', str(cn_count))
html = html.replace('__IN_COUNT__', str(in_count))
html = html.replace('__BD_COUNT__', str(bd_count))

Path(output_path).parent.mkdir(parents=True, exist_ok=True)
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'HTML generated: {output_path} ({len(html):,} bytes)')
