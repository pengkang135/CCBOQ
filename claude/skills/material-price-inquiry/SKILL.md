---
name: material-price-inquiry
description: |
  Generic online material price inquiry from Excel inquiry sheet. Reads material list from Excel → spawns 3 sub-agents for parallel search (English + local language + Chinese trilingual) → verifies URLs during search → master re-verifies each part on completion → merges to HTML + JSON output. Use when user asks to search market prices for construction materials, equipment, or any procurement items from a structured inquiry list (Excel spreadsheet). Triggers on requests like "查价", "询价", "market inquiry", "price inquiry", "网上询价", "材料询价", "找供应商报价".
---

# Material Price Inquiry

Generic skill for conducting online market price surveys from a structured material inquiry spreadsheet. Uses parallel multi-agent architecture with bilingual search and inline verification.

## Core Workflow

```
1. Read Excel → extract material section (specified by user)
2. Divide materials into 3 groups for parallel agents
3. Spawn Agent A, B, C simultaneously (3 tool calls in single message)
4. Each agent: bilingual search → verify → write part_N.json
5. Master: verify each part as it arrives (stream, not batch)
6. All verified → merge → generate HTML + JSON output
```

## Step 1: Read Input Excel

Use document-ingest to extract materials from the inquiry spreadsheet.

```bash
# Quick overview of workbook structure
python ../document-ingest/scripts/excel_to_ast.py "inquiry.xlsx" --mode workbook_summary

# Semantic analysis — auto-detects headers, data regions, categories
python ../document-ingest/scripts/excel_to_ast.py "inquiry.xlsx" --mode semantic_analysis \
    --sheet "Sheet1" -o inquiry_ast.json
```

Read `inquiry_ast.json` to identify:
- `semantic.regions.header_tree.nodes` — column structure (code, name, spec, unit)
- `semantic.regions.data_tables` — material data regions with row counts
- Natural sub-category boundaries for dividing into 3 agent groups

For large sheets (>300 rows), add `--max-rows 300` to limit output. For known/small sheets, `--mode sheet_ast` is sufficient.

## Step 2: Divide Materials

Distribute materials across 3 agents. Strategy:
- Group by sub-category when possible (keeps agent context coherent)
- If roughly even, 3-5 materials per agent is ideal
- If one sub-category is tiny (2-3 materials), merge with nearest sub-category

## Step 3: Spawn 3 Agents in Parallel

All 3 Agent tool calls in ONE message with `run_in_background: true`.

Each agent prompt must be self-contained:
- Material list (code, name, specs, unit)
- Search language strategy (see [language-strategy.md](references/language-strategy.md))
- **Chinese keywords** (5-8 per material group, with English gloss) — mandatory for all manufactured materials
- Price reference ranges for anomaly detection
- Output path: `{output_dir}/part_N.json`
- Data format: see [data-format.md](references/data-format.md)
- What NOT to do: fabricate, fake URLs, homepage-only URLs

## Step 4: Agent Internal Workflow

Each agent follows [workflow.md](references/workflow.md):

```
WebSearch (English) + WebSearch (local language) → parallel
  → Filter candidates → open pages
    → Confirm price numbers visible
      → WebFetch verify URL reachable + price present
        → Record: supplier, contact, price_usd, source, url, type, language
        → Pass ✓ / Fail ✗ (try next candidate)
  → Write part_N.json
```

**Critical rules for agents:**
- Always search in project country's local language AND Chinese, not just English
- Construction materials are highly local — English-only yields expensive, scarce results
- Chinese manufacturers are the world's largest exporters of construction materials — Chinese search is mandatory for all manufactured goods
- Search priority: Chinese manufacturers (中文) > Local sources (native language) > International sources (English)
- At least 1 local source AND 1 Chinese source per manufactured material
- If < 3 suppliers found: mark gaps as `"无公开报价"`, do NOT fabricate
- Every URL must point to a page showing actual prices, not product pages or homepages

## Step 5: Master Verification

When any agent completes, immediately:
1. Read part_N.json
2. Verify [1] URLs non-empty + valid format
3. Verify [2] WebFetch each unique URL → HTTP 200
4. Verify [3] price_usd in reasonable range (flag outliers)
5. Verify [4] supplier/contact not empty or placeholder
6. Verify [5] each material has ≥1 local source
7. If issues found → spawn correction agent for that part only
8. If all ✓ → mark part verified

## Step 6: Merge Outputs

Run `scripts/merge_outputs.py` which executes a 3-step pipeline:

```
Step 1: Merge part_A.json + part_B.json + part_C.json → price_data.json
Step 2: Enrich — estimate EXW/FOB/CIF/DDP for each quote → price_data_enriched.json
Step 3: Generate HTML report with delivery-term pricing table → price_inquiry.html
```

```
{output_dir}/
├── price_data.json           # Combined JSON (all materials × 3 quotes)
├── price_data_enriched.json  # With origin, price_basis, 4 delivery term prices
├── price_inquiry.html        # Full HTML report (blue-white tech theme)
├── part_A.json               # Agent A intermediate result (audit trail)
├── part_B.json               # Agent B intermediate result
└── part_C.json               # Agent C intermediate result
```

### HTML Report Features

- **Blue-white tech theme** — Clean professional styling with Slate palette
- **DDP ex. VAT** — All DDP prices exclude VAT (recoverable input tax)
- **Section rate info** — Each material category header shows applicable rates: Freight, CD, VAT, AIT, RD, Clearance, Inland transport
- **EXW / FOB / CIF / DDP (ex.VAT) / DDP (inc.VAT) five delivery terms** — Estimated from source price using logistics factors
- **Country codes** — CN / IN / BD origin labels
- **Source type badges** — SQ (Supplier Quote) / PR (Platform Reference) / ME (Market Estimate) / RFQ
- **Basis tag on source links** — EXW / FOB / CIF / DDP tag showing the actual price basis found
- **Bold = confirmed price** — Column matching `price_basis` is bolded; derived columns in muted grey
- **Collapsible sections** — Grouped by material category with collapse/expand toggle
- **Methodology section** — Explains EXW→FOB→CIF→DDP estimation factors
- **Legend row** — Explains SQ/PR/ME/RFQ badge meanings

### Enrichment Factors

All rates come from `references/tariff_rates.yaml` — the **single source of truth**. This file is read at runtime by both `enrich_prices.py` and `generate_price_report.py`. No rates are hardcoded in scripts.

**Before each inquiry**, update the YAML if tariff schedules have changed. Key sections:

- `bangladesh.clearance_pct` — customs clearance + port handling (default: 3%)
- `bangladesh.inland_transport_base_usd` — per ton/m3 (default: $5)
- `bangladesh.vat_rate` — standard VAT on (CIF + CD) (default: 15%)
- `origin_factors` — per-country EXW→FOB uplift and freight multiplier
- `categories[]` — per-material-type duty breakdown + freight percentage

**Bangladesh compound import tax structure (DDP ex-VAT):**

DDP (ex. VAT) = CIF × (1 + CD + AIT + AT + RD + clearance) + inland transport

DDP (inc. VAT) = DDP ex.VAT + CIF × (1 + CD) × VAT

VAT is excluded from DDP ex.VAT because it is recoverable input tax in Bangladesh. VAT = (CIF + CD) × 15%.

Current YAML categories (edit `tariff_rates.yaml` to update):

| Category ID | CD | AIT | AT | RD | Freight | Material Examples |
|-------------|-----|-----|-----|-----|---------|-------------------|
| industrial | 25% | 5% | 5% | 3% | 8% | Steel, pipes, paint, coating, SS, DI |
| plastics | 15% | 3% | 5% | 3% | 10% | HDPE, UPVC, geotextile, PVD |
| cement | 10% | 3% | 5% | 3% | 35% | Cement, concrete, pavers |
| raw_materials | 5% | 3% | 5% | 0% | 35% | Rock, stone, sand, aggregate |
| default | 15% | 3% | 5% | 0% | 12% | Other / unclassified materials |

Each category also has a `keywords` list used to match materials via their name/type text. Add new keywords to the YAML when new material types appear.

## Output Data Format

See [data-format.md](references/data-format.md) for complete specification.

### Base fields (from agents)

```json
{
  "material_id": "M001",
  "material_name": "Material name (English + local language)",
  "material_type": "Material type/category",
  "supplier": "Full company name",
  "contact": "Phone | Email | Website",
  "location": "City, Country",
  "price_usd": 123.45,
  "unit": "m3 / t / m / m2 / nos / No",
  "source": "Brief price source description",
  "url": "https://exact-price-page-url",
  "type": "供应商报价 | 平台参考 | 市场参考 | 无公开报价",
  "language": "en | bn | en+bn | etc",
  "note": "Optional caveats",
  "applies_to": ["M001", "M002"]
}
```

### Enriched fields (added by `enrich_prices.py`)

```json
{
  "origin": "CN | IN | BD | EU",
  "price_basis": "EXW | FOB | CIF | DDP",
  "price_exw": 100.00,
  "price_fob": 104.00,
  "price_cif": 112.32,
  "price_ddp": 140.40,
  "price_ddp_inc_vat": 158.65,
  "duty_category": "industrial | plastics | cement | raw_materials | default",
  "duty_components": {
    "customs_duty": 0.25,
    "vat_rate": 0.15,
    "advance_income_tax": 0.05,
    "advance_tax": 0.05,
    "regulatory_duty": 0.03,
    "clearance": 0.03,
    "freight_pct": 0.08,
    "inland_transport_usd": 5
  }
}
```

`price_ddp` is **ex-VAT** (excludes recoverable input VAT). `price_ddp_inc_vat` is the full delivered price including VAT. Individual tax components stored in `duty_components` for transparency.

## Language Strategy

**Default: trilingual search always (English + Local + Chinese).** See [language-strategy.md](references/language-strategy.md) for full guide.

Key principles:
- Engineering materials are highly localized. English-only search finds export/trader pages with FOB/CIF pricing — not local market prices. Local suppliers publish prices in their native language.
- China is the world's largest exporter of construction materials. Chinese factory EXW prices are typically 30-60% lower than English-language trade platforms. Chinese manufacturers publish prices almost exclusively in Chinese on 1688.com, Made-in-China, and industry B2B sites.
- If a material is manufactured (steel, pipes, PHC piles, bolts, pumps, valves, electrical), there is almost certainly a Chinese factory making it with a published price.

**Search priority:** Chinese manufacturers (中文) > Local sources (native language) > International sources (English).

## Acceptance Criteria

- [ ] All materials covered (specified section from Excel)
- [ ] Every quote URL accessible (HTTP 200) with price content
- [ ] No fabricated data (gaps explicitly marked)
- [ ] HTML has clickable hyperlinks for all price sources
- [ ] JSON structure complete, machine-readable
- [ ] Prices within reasonable ranges (anomalies annotated)
- [ ] Each manufactured material has ≥1 Chinese source (language field contains zh)
- [ ] Each material has ≥1 local source (language field = project country code)
