# Data Format Specification

## JSON Output Structure

### Single Quote Record

```json
{
  "material_id": "M001",
  "material_name": "Full material name (bilingual: Chinese + English)",
  "supplier": "Full legal company name",
  "contact": "Phone | Email | Website URL",
  "location": "City, Country",
  "price_usd": 123.45,
  "unit": "m3 | t | m | m2 | nos | No | set | lot",
  "source": "Brief description of price origin, e.g. 'Mir Concrete C40 BDT 9,000/m3 ≈ $85/m3 Dhaka'",
  "url": "https://exact-page-url-with-price",
  "type": "供应商报价 | 平台参考 | 市场参考 | 无公开报价",
  "language": "en | bn | en+bn | vi | ar | etc",
  "note": "Optional. Any caveats: price year, exclusions, assumptions"
}
```

### price_usd

- `number` when price is known
- `null` when "无公开报价"

### type Field Values

| Type | Meaning | When to Use |
|---|---|---|
| `供应商报价` | Direct supplier quote | Price published on supplier's own website/catalog |
| `平台参考` | Platform reference | Price from Alibaba, IndiaMART, Made-in-China, etc. |
| `市场参考` | Market estimate | Aggregated/estimated from industry sources |
| `无公开报价` | No public price | Supplier identified but price not published online |

### language Field Values

- `"en"` — English source only
- `"bn"` — Bengali (local) source
- `"en+bn"` — Bilingual source or found via both
- Other codes: `"vi"` (Vietnamese), `"ar"` (Arabic), `"th"` (Thai), etc.

### unit Field Values

Standard units as they appear in the material specification:
- `m3` — cubic meter
- `t` — metric ton
- `m` — linear meter
- `m2` — square meter
- `nos` — number of pieces
- `No` — number (generic)
- `set` — complete set
- `lot` — project lot

## JSON File Structure

### part_N.json (Agent Output)

Array of quote objects for that agent's assigned materials.

### price_data.json (Final Combined)

Array of all quote objects from all 3 agents, sorted by material_id.

## HTML Output

- Bootstrap-free, inline CSS
- Material groups separated with sub-headers
- Every `source` field rendered as `<a href="url" target="_blank">` clickable link
- `type` field rendered as color-coded badge
- Summary stats at top (material count, quote count, date)

## Edge Cases

- **price_usd is null**: Display "需询价" or "Request Quote" in HTML
- **contact is generic** (e.g., "via Alibaba.com"): Acceptable for platform references
- **note field**: Include when price has significant caveats (different year, excludes key components, requires RFQ for exact spec)
