---
name: material-price-inquiry
description: |
  Generic online material price inquiry from Excel inquiry sheet. Reads material list from Excel → spawns 3 sub-agents for parallel search (English + local language bilingual) → verifies URLs during search → master re-verifies each part on completion → merges to HTML + JSON output. Use when user asks to search market prices for construction materials, equipment, or any procurement items from a structured inquiry list (Excel spreadsheet). Triggers on requests like "查价", "询价", "market inquiry", "price inquiry", "网上询价", "材料询价", "找供应商报价".
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

Read the inquiry spreadsheet to identify:
- Target section (e.g., "混凝土", "桩基与钢结构")
- Material codes, names, specs, units
- Group boundaries for 3 agents

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
- Always search in project country's local language, not just English
- Construction materials are highly local — English-only yields expensive, scarce results
- Prioritize local sources > regional > international
- At least 1 local source per material
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

Run `scripts/merge_outputs.py` to generate:

```
{output_dir}/
├── price_data.json       # Combined JSON (all materials × 3 quotes)
├── price_inquiry.html     # Clickable HTML table with verification links
├── part_a.json            # Agent A intermediate result (audit trail)
├── part_b.json            # Agent B intermediate result
└── part_c.json            # Agent C intermediate result
```

## Output Data Format

See [data-format.md](references/data-format.md) for complete specification.

```json
{
  "material_id": "M001",
  "material_name": "Material name (English + local language)",
  "supplier": "Full company name",
  "contact": "Phone | Email | Website",
  "location": "City, Country",
  "price_usd": 123.45,
  "unit": "m3 / t / m / m2 / nos / No",
  "source": "Brief price source description",
  "url": "https://exact-price-page-url",
  "type": "供应商报价 | 平台参考 | 市场参考 | 无公开报价",
  "language": "en | bn | en+bn | etc",
  "note": "Optional caveats"
}
```

## Language Strategy

**Default: bilingual search always.** See [language-strategy.md](references/language-strategy.md) for full guide.

Key principle: Engineering materials are highly localized. English-only search finds export/trader pages with FOB/CIF pricing — not local market prices. Local suppliers publish prices in their native language.

**Search priority:** Local sources > regional neighbors > international sources.

## Acceptance Criteria

- [ ] All materials covered (specified section from Excel)
- [ ] Every quote URL accessible (HTTP 200) with price content
- [ ] No fabricated data (gaps explicitly marked)
- [ ] HTML has clickable hyperlinks for all price sources
- [ ] JSON structure complete, machine-readable
- [ ] Prices within reasonable ranges (anomalies annotated)
