# Agent Internal Workflow

Each sub-agent (A, B, C) follows this exact workflow.

## 1. Receive Prompt

Agent prompt must contain:
- Material list with full specs (code, name, description, unit)
- Search keywords (English + local language + Chinese)
- Price reference ranges
- Output file path for part_N.json
- Explicit prohibitions (no fabrication, no fake URLs, no homepage-only URLs)

## 2. Search Phase (Trilingual Parallel)

```
WebSearch (Chinese keywords, 3-5 queries) — Chinese manufacturers first
  +
WebSearch (local language keywords, 3-5 queries)
  +
WebSearch (English keywords, 3-5 queries)
  → Merge results
  → Deduplicate
  → Sort by: Chinese factory sources > local sources > international sources
```

## 3. Candidate Screening

For each candidate URL, open the page and check:
- [ ] Page loads successfully
- [ ] Page contains price numbers (not just product specs)
- [ ] Price is for the right material (not a different spec/grade)
- [ ] Supplier information is visible

If any check fails → skip to next candidate.

## 4. Recording

For each valid candidate:
```
Record:
  - supplier: Full company name from page
  - contact: Phone/email/website from page
  - location: City, Country
  - price_usd: Convert local currency to USD at current rate
  - unit: Match material unit
  - source: 1-line summary of what page says
  - url: Full URL to exact page
  - type: Classify (供应商报价/平台参考/市场参考)
  - language: Source language (zh for Chinese, en+zh for bilingual sources)
```

## 5. WebFetch Verification

For each recorded entry:
```
WebFetch(url)
  → HTTP 200? ✓ continue / ✗ discard
  → Page body contains price numbers? ✓ record / ✗ discard
  → Price roughly matches recorded value? ✓ keep / ✗ mark for review
```

## 6. Gap Handling

If a material has < 3 valid quotes:
- Fill what you have (minimum 1)
- Mark empty slots as:
  ```json
  {
    "material_id": "M0XX",
    "material_name": "...",
    "supplier": "未找到公开报价的供应商",
    "contact": "",
    "location": "",
    "price_usd": null,
    "unit": "...",
    "source": "该材料在公开网络上未找到足够供应商报价，建议直接联系本地供应商询价",
    "url": "",
    "type": "无公开报价",
    "language": ""
  }
  ```
- **Never fabricate to fill 3 slots**

## 7. Write Output

Write `part_N.json` as valid JSON array. Report:
- Total quotes found
- Quotes with prices vs. without
- Local source count
- Chinese source count
- Any anomalies or issues found
- Recommendations for master verification
