# Language Strategy for Material Price Inquiry

## Why Trilingual Search (English + Local + Chinese) is Mandatory

Engineering and construction materials market has three distinct layers:

1. **Local suppliers (native language)** — Local market prices, often cheapest for bulk materials (sand, aggregate, concrete). Local suppliers don't publish in English.
2. **Chinese manufacturers (Chinese)** — China is the world's largest exporter of construction materials, especially steel, pipes, precast concrete, fasteners, machinery. Chinese factory prices are typically EXW/FOB and 30-60% lower than English-language trade platforms for the same product. Chinese manufacturers publish prices on 1688.com, Made-in-China, and industry B2B sites — almost exclusively in Chinese.
3. **International traders (English)** — Trade platforms like Alibaba (intl), IndiaMART. Prices are CIF with export markup, typically higher than factory-direct.

**Price hierarchy (lowest → highest):**
```
Chinese factory EXW < Local market < International trader FOB/CIF
```

**Critical insight:** If a material is manufactured (steel pipes, PHC piles, bolts, pumps, valves, electrical), there is almost certainly a Chinese factory making it with a published price. English-only search misses this entire layer.

Each material must have **at least 1 local-language source** AND **at least 1 Chinese-language search attempt** (even if the material is not Chinese-made — to check for price benchmarks).

## Search Priority

```
Local sources (native language) > Chinese manufacturers (中文) > International sources (English)
```

## Keyword Preparation (Before Spawning Agents)

For each material, prepare keyword triples: English + local language + Chinese.

**Bangladesh (Bengali) + Chinese:**

| Material | English | Bengali | Chinese |
|---|---|---|---|
| Ready-mix concrete | ready mix concrete price | রেডি মিক্স কংক্রিটের দাম | 商品混凝土 价格 |
| Steel tubular pile | steel tubular pile API 5L | স্টিল পাইপের দাম | API 5L 钢管桩 价格 厂家 |
| PHC pile | PHC pile prestressed | পিএইচসি পাইলের দাম | PHC管桩 价格 厂家 |
| Steel rebar | steel rebar price | রডের দাম | 螺纹钢 价格 钢厂 |
| Cement | cement price | সিমেন্টের দাম | 水泥 价格 |
| HDPE pipe | HDPE pipe price | এইচডিপিই পাইপের দাম | HDPE管 价格 厂家 |
| Geotextile | geotextile fabric price | জিওটেক্সটাইলের দাম | 土工布 价格 厂家 |
| Steel pile shoe | steel pile shoe price | - | 钢管桩靴 桩尖 价格 |
| Shear connector | shear connector stud | - | 剪力钉 剪力连接件 价格 |
| Steel mesh | steel reinforcement mesh B785 | - | 钢筋网片 B785 价格 |
| Ductile iron pipe | DI pipe DN600 K9 | - | 球墨铸铁管 DN600 K9级 |
| SS pipe | stainless steel pipe SS316 | - | SS316不锈钢管 DN150 |
| Armour rock | armour rock boulder | - | 护面块石 大块石 价格 |
| Supplier | building material supplier | নির্মাণ সামগ্রী সরবরাহকারী | 厂家 供应商 批发 |
| Price list | price list | মূল্য তালিকা | 报价 价格表 |

**Vietnam (Vietnamese) + Chinese:**

| Material | English | Vietnamese | Chinese |
|---|---|---|---|
| Steel pipe | steel pipe price | giá ống thép | 钢管 价格 厂家 |
| Concrete | ready mix concrete price | giá bê tông tươi | 商品混凝土 价格 |

**Middle East (Arabic) + Chinese:**

| Material | English | Arabic | Chinese |
|---|---|---|---|
| Concrete | ready mix concrete price | سعر الخرسانة الجاهزة | 商品混凝土 价格 |
| Steel | steel price | سعر الحديد | 钢材 价格 钢厂 |

## Agent Prompt Must Include

Each agent's prompt should contain:
1. English keywords (5-8 per material group)
2. Local language keywords (5-8, with English gloss)
3. **Chinese keywords** (5-8, with English gloss) — mandatory for all manufactured materials
4. Explicit instruction: "搜索优先级：中文厂家直供 > 本地来源 > 国际来源"
5. Explicit instruction: "每种材料至少 1 条中文来源（如属工业制成品）"

## Verification Check

Master verification includes:
- "每种材料是否有至少 1 条本地语言来源（language field = local code）"
- "每种工业制成品是否有至少 1 条中文来源（language field 包含 zh）"

## When Local/Chinese Search Returns Nothing

If local language search genuinely yields no results:
- Mark the gap in the agent report
- Note: "本地语言搜索未返回有效价格页面，说明本地供应商不在公开网络发布价格"
- Still include local suppliers found (even without prices) as "无公开报价" entries with contact info for direct RFQ

If Chinese search yields no results:
- Mark the gap in the agent report
- Note: "中文平台搜索未找到该规格产品的公开报价"
- This is unusual for standard manufactured goods — flag for manual review
