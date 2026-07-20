---
name: pk-boq-classify
description: "BOQ分类标签审核与修正。对已自动分类的BOQ清单，按{}区域提取、聚合去重分类模式、LLM语义审核、批量回写Excel。触发词：BOQ分类审核、分类标签修正、classified BOQ review、分类错误检查、按区域审核分类、BOQ reclassify。也可用于首次对未分类BOQ按区域打Discipline/Category/Subcategory标签。"
---

# pk-boq-classify — BOQ分类标签审核与修正

对已自动分类（或待分类）的BOQ清单，按 `{}` 区域上下文审核 Discipline/Category/Subcategory 标签正确性并批量修正。

## 核心思路

自动分类器（关键词/YAML规则）缺少区域上下文理解，典型错误：

- "Steel Pipe" → MEP/Plumbing，实际是窗框钢管 → Architectural/Doors & Windows
- "plaster finish" → Decoration/Plaster，实际描述砌体墙 → Architectural/Masonry
- "Grille bars" → MEP/HVAC，实际是窗户格栅 → Architectural/Doors & Windows

**解决方案**：按 `{}` 区域提取 → 聚合去重分类模式 → LLM 理解区域语义审核 → 批量回写。

## 决策入口

```
BOQ分类需求
├── 已有自动分类，需审核修正 → 本技能主流程
├── 未分类，需从零打标签 → 本技能主流程（current分类为空）
├── 只需查特定区域有哪些分类 → extract_regions.py --raw
└── 已有修正清单JSON，只需回写 → 直接 batch_correct.py
```

## 主流程（四阶段）

### Stage 1: 结构探查（fastexcel）

不可跳过。确认分类列位置和区域分布：

```python
import fastexcel
wb = fastexcel.read_excel("classified.xlsx")
sheet = wb.load_sheet("ZOO BQ")  # 或用户指定的sheet
df = sheet.to_pandas()
# 确认列映射：B列=描述(索引1), M列=Discipline(12), N=Category(13), O=Subcategory(14)
```

如分类列位置与默认不同，记下实际列索引供后续脚本使用。

### Stage 2: 区域提取 + 聚合去重

用 `extract_regions.py` 提取所有（或指定）`{}` 区域，按分类模式聚合去重：

```bash
# 提取全部区域，按分类模式聚合
python scripts/extract_regions.py "classified.xlsx" -o regions.json

# 只看特定区域
python scripts/extract_regions.py "classified.xlsx" --region "{Wall surface material}" -o wall_surface.json

# 输出原始行（不聚合，用于小区域直接LLM审核）
python scripts/extract_regions.py "classified.xlsx" --region "{Window Works}" --raw -o window_raw.json
```

**聚合原理**：同一区域内 `{Discipline, Category, Subcategory}` 相同的行合并为一条模式记录（含 count + 3个样本描述），150+ 行可压缩到 5-10 条模式。

### Stage 3: LLM 语义审核

**3a. 加载定额库参考字典（可选但推荐）**

根据BOQ专业加载对应册的 L1-L2 分类大纲作参考（见 [quota_db_schema.md](references/quota_db_schema.md)）：

```sql
-- 用 sqlite MCP 工具查询
SELECT d.code, d.name as L1, s.sub_code, s.name as L2
FROM divisions d
JOIN sub_divisions s ON s.division_code = d.code
ORDER BY d.code, s.sub_code
```

一般加载对应1-2册的大纲即可（<2k token）。

**3b. 提交聚合模式给 LLM 审核**

将聚合后的 JSON 中的 `classification_patterns` 提交给 LLM，附带：

1. **区域上下文**（`header` 字段 — 如 `{Wall surface material}`、`{Window Works}`）
2. **分类模式列表**（每条：discipline/category/subcategory + count + 3个样本描述）
3. **定额库 L1-L2 大纲**作参考字典

LLM 审核要点：
- 描述内容是否与 `{}` 区域上下文匹配？
- 分类是否符合定额库的标准层级逻辑？
- 同一区域内是否有分类不一致的同类项？

**3c. 输出修正指令**

LLM 输出结构化修正 JSON：

```json
[
  {
    "desc_regex": "Louver/vent.*Frame Steel.*Pipe Galvanized",
    "current_discipline": "MEP",
    "current_category": "Plumbing",
    "current_subcategory": "Steel Pipe",
    "new_discipline": "Architectural",
    "new_category": "Doors & Windows",
    "new_subcategory": "Steel Louver",
    "reason": "Under {Window Works}, louver vent frame is window component, not plumbing pipe"
  }
]
```

**regex 编写原则**：从样本描述中提取最能区分此类目的关键词组合，避免过宽（误匹配其他类目）或过窄（漏匹配同类变体）。

### Stage 4: 批量回写

```bash
python scripts/batch_correct.py "classified.xlsx" --corrections corrections.json

# 预览模式（不修改文件）
python scripts/batch_correct.py "classified.xlsx" --corrections corrections.json --dry-run

# 指定输出路径
python scripts/batch_correct.py "classified.xlsx" --corrections corrections.json -o output.xlsx
```

**安全机制**：每一条修正都同时匹配 `desc_regex` + 当前分类值（三元组），两个条件都满足才写入，避免误改。

## 脚本参数速查

### extract_regions.py

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `xlsx` | (必填) | 已分类 BOQ 文件路径 |
| `--sheet` | ZOO BQ | Sheet 名称 |
| `--region` | 无(全部) | 过滤区域 header 子串 |
| `--desc-col` | 1 | 描述列 0-based 索引 |
| `--disc-col` | 12 | Discipline 列 0-based |
| `--cat-col` | 13 | Category 列 0-based |
| `--subcat-col` | 14 | Subcategory 列 0-based |
| `-o` | stdout | 输出 JSON 路径 |
| `--raw` | false | 输出原始行而非聚合模式 |

### batch_correct.py

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `xlsx` | (必填) | BOQ 文件路径 |
| `--corrections` / `-c` | | 修正 JSON 文件路径 |
| `--inline` | | 内联 JSON 字符串 |
| `--sheet` | ZOO BQ | Sheet 名称 |
| `--desc-col` | 2 | 描述列 1-based 索引 |
| `--disc-col` | 13 | Discipline 列 1-based |
| `--cat-col` | 14 | Category 列 1-based |
| `--subcat-col` | 15 | Subcategory 列 1-based |
| `--dry-run` | false | 仅预览不修改 |
| `-o` | input_corrected.xlsx | 输出路径 |

## 从零分类（无现有标签）

当 BOQ 未分类时，跳过 current 字段匹配：

1. Stage 1-2 同上，提取区域和聚合描述模式
2. Stage 3: LLM 直接根据区域上下文 + 描述 + 定额库大纲分配 Discipline/Category/Subcategory
3. 修正 JSON 中 `current_discipline/category/subcategory` 留空 `""`，脚本匹配时 current 为空则跳过 current 校验，仅按 desc_regex 匹配

```bash
python scripts/batch_correct.py "unclassified.xlsx" --corrections classify_new.json
```

## 引用规则

以下从 pk-boq 族继承，本技能不重复定义：

| 规则 | 来源 |
|------|------|
| 四级层级 `【】→《》→{}→条目` | [boq_hierarchy_rules.md](../pk-boq/references/boq_hierarchy_rules.md) |
| 大表分层策略 Stage 1-4 | `~/.claude/references/excel-layered-strategy.md` |
| Excel 库选择：读 fastexcel，写 openpyxl | [excel_compatibility.md](../pk-boq/references/excel_compatibility.md) |
| 定额库 L1-L4 层级 | [quota_db_schema.md](references/quota_db_schema.md) |

## 与 pk-boq-price-build 的关系

| | pk-boq-price-build | pk-boq-classify |
|---|---|---|
| 分类方式 | YAML 关键词规则（机械） | LLM 语义理解（上下文） |
| 适用场景 | 人材机→标准费用大类 | BOQ条目→专业/分部/子分部 |
| 区域感知 | 无 | 按 `{}` 区域上下文判断 |
| 典型用法 | 先粗分 | 后审核修正 |
