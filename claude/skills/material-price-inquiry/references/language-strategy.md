# Language Strategy for Material Price Inquiry

## Why Bilingual Search is Mandatory

Engineering and construction materials are **highly localized**. Key reasons:

1. **Local suppliers don't publish in English** — They use their native language on their websites, social media, and local business directories
2. **English-only finds export/trader pages** — Prices are FOB/CIF with export markup, not local market prices
3. **Price difference can be 20-50%** — Local sources typically much cheaper than international
4. **Availability differs** — Some materials may only be available locally or only internationally

## Search Priority

```
Local sources (native language) > Regional neighbors > International sources
```

Each material must have **at least 1 local-language source**.

## Keyword Preparation (Before Spawning Agents)

For the target country, prepare English + local language keyword pairs for the material categories. Examples:

**Bangladesh (Bengali):**

| Material | English | Bengali |
|---|---|---|
| Ready-mix concrete | ready mix concrete price | রেডি মিক্স কংক্রিটের দাম |
| Steel rebar | steel rebar price | রডের দাম |
| Cement | cement price | সিমেন্টের দাম |
| Sand/aggregate | sand aggregate price | বালির দাম |
| Supplier | building material supplier | নির্মাণ সামগ্রী সরবরাহকারী |
| Price list | price list | মূল্য তালিকা |

**Vietnam (Vietnamese):**

| Material | English | Vietnamese |
|---|---|---|
| Steel pipe | steel pipe price | giá ống thép |
| Concrete | ready mix concrete price | giá bê tông tươi |
| Supplier | construction material supplier | nhà cung cấp vật liệu xây dựng |

**Middle East (Arabic):**

| Material | English | Arabic |
|---|---|---|
| Concrete | ready mix concrete price | سعر الخرسانة الجاهزة |
| Steel | steel price | سعر الحديد |
| Supplier | building materials supplier | مورد مواد البناء |

## Agent Prompt Must Include

Each agent's prompt should contain:
1. English keywords (5-8 per material group)
2. Local language keywords (5-8, with English gloss)
3. Explicit instruction: "搜索优先级：本地来源 > 区域来源 > 国际来源"
4. Explicit instruction: "每种材料至少 1 条本地来源"

## Verification Check

Master verification includes: "每种材料是否至少有 1 条本地语言来源（language field = local code）"

## When Local Search Returns Nothing

If local language search genuinely yields no results:
- Mark the gap in the agent report
- Note: "本地语言搜索未返回有效价格页面，说明本地供应商不在公开网络发布价格"
- Still include local suppliers found (even without prices) as "无公开报价" entries with contact info for direct RFQ
