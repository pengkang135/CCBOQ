---
name: pk-boq-classify
description: "BOQ 清单业务分类：按 Description + Unit + 分级章节上下文，给每个条目判定 Discipline / SortKey / Category / Subcategory / Element 五列，取值受定额库五册闭词表约束，LLM 只能从候选池里选不能编造。走脚本路由分档（0 token）+ Haiku/Sonnet 按档分类 + Opus 仲裁 + 闭词表校验的流水线。分类的完成态是把五列插进 Excel 清单写回值（zip/XML 层插列，不丢 drawing/media），不是只产出 JSON 分析 —— 先产出 classification.json，再用 write_classification.py 插列写值，收尾交付已带分类列的 Excel 文件。触发词：BOQ分类、清单分类、打标签、打分类列、discipline、category、subcategory、element、套定额分部。原清单无分级符号先调 pk-boq-hierarchy。"
license: Proprietary. LICENSE.txt has complete terms
---

# pk-boq-classify — BOQ 业务分类

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


给 BOQ 的每个条目判定它属于定额库的哪个分部分项，填五个分类列，并把这五列插进 Excel 清单写回值。**分类不算完，直到列落进 Excel 文件。**

技能族里的位置：`pk-boq-hierarchy` 打层级符号 → **本技能分类 + 把五列插进 Excel 写回** → `pk-boq-workbench` 建工作台（分类列已由本技能填好）→ `pk-boq-db-match` / `pk-norms-match` 套价。

**分类的交付物是带分类列的 Excel 文件，不是一份 JSON 分析。** 分类的输入（Description + Unit + 分级章节）全在原清单里，不需要工作台存在；反过来工作台的三个透视表按 Discipline / SortKey / Category 分组汇总，分类列空着刷出来只有 `(空白)`。所以分类阶段就把列插进清单写回值，一次成型，也省掉二次写回。

## 核心工作

按 **Description + Unit + 所属分级章节**（`【】《》{}` 追溯出的上下文）判断，填这五列：

| 列 | 取值来源 |
|----|---------|
| Discipline | 定额库分册英文全名（A 建筑装饰 / B 通用安装 / C 市政园林 / D 水运工程 / E 房屋修缮） |
| SortKey | 定额库 `division.code`（A.04、B.10），PRELIM 行填 `PRELIM` |
| Category | 定额库 L1 `division.name` 闭词表 |
| Subcategory | 定额库 L2 `sub_division.name` 闭词表 |
| Element | 定额库 L3 `enterprise_item` / `chapter` 闭词表 |

后三列必须来自闭词表，LLM 只能从候选池里挑，不能翻译、改写、编造 —— 约束机制见下方「闭词表三层防线」。

## 执行铁律

**分类是 8 阶段流水线，不是跑一遍规则脚本**，后面接 ⑨ 闭词表校验、⑩ 写回 Excel 才算完成。规则引擎（阶段⑤）只处理 UNIQUE/PATTERN/SUM/PRELIM 这几类确定项，五列都必须经过 LLM 阶段（③ Haiku / ④ Sonnet / ⑦ Opus）校验或填充。

收尾时检查这五列的填充率。Element 大面积为空，就是漏跑了 LLM 阶段，不是"这些行没有对应分项"。

**写完 JSON 不算完，列没落进 Excel 就不算交付。** classification.json 是中间产物，最终交付物是插了分类列的 Excel 文件。

> 2026-08-08 Laldia 路桥 BQ 因为只跑规则引擎就收工，Element 全空、前三列也没经 LLM 校验，整批返工。规则引擎跑出 Discipline/Category/Subcategory 不等于分类完成。

行数只影响读表方式，不影响流水线阶段数：超过 500 行先走 `pk-boq-ai-team` 的数据前端（fastexcel 读 → 区域聚合 → LLM 分析聚合模式 → Python 批量回写，3000 行压到 50 组，token 省 60-100x）；小表直接读，但 8 个阶段一个都不能少。

## 流程

### 1. 前置检查

描述列要有 `【】《》{}` 分级符号 —— 章节上下文是分类的输入之一，没有先调 `pk-boq-hierarchy`。

输入可以是**原清单**（正常路径，表头常在第 1 行）也可以是**已建好的工作台**（补分类的场景，表头在第 3 行）。列位一律按表头名找，任何时候都不要按列字母定位。

### 2. 路由分档（0 token）

```bash
python scripts/route_boq.py -i <清单.xlsx> [--header-row 1] -o route_result.json
```

逐行判定 SKIP / PRELIM / SUM / PATTERN / UNIQUE / LOW / HIGH / ZERO，并从定额库闭词表检索候选分部。这一步纯代码，决定后面哪些行要花 LLM 的钱、花哪一档的钱。

**列位和数据起始行都从表头行实时解析**，不写死：按 `Description` / `Unit` / `Quantity` 三个表头名定位列，起始行取表头之后第一个描述非空的行。模板改版列字母变了、或者直接读原清单，都不用改脚本或传参。跑起来会打印实际解析到的列，核对一眼再往下走：

```
[step2] 表头行 3 | 列 desc=E, qty=G, unit=F | 数据起始行 5
```

表头行默认 3（工作台布局），原清单表头在第 1 行就加 `--header-row 1`。Dept1-3 不再是实体列，默认从层级符号推导。

**只有表头认不出时才用 `--cols` 兜底**，这时列号要用 openpyxl 数：fastexcel 会静默吞掉整列为空的前导列，两者列号能差一位，拿错的索引填 `--cols`，检索到的就是编号列而不是描述列，结果全是 ZERO 档。

**筛条目只看描述，不看工程量。** 聚合/分片时用 `qty > 0` 之类的条件过滤会漏掉量待定的真实报价条目（"Contractor's Supervision" 单位 Week、量空着等承包商填）—— 这些是要报价的，必须分类。有描述就纳入，量的有无与是否需要分类无关。

### 3. 按档分类

| 档位 | 处理 |
|------|------|
| SKIP / PRELIM / SUM / PATTERN / UNIQUE | 阶段⑤ 规则直接写回，不调 LLM |
| LOW（2-3 候选） | 阶段③ Haiku |
| HIGH（4+ 候选） | 阶段④ Sonnet |
| ZERO（零候选/异常） | 阶段⑦ Opus 仲裁或人工 |

③④ 结果做跨模型一致性比对（阶段⑥），不一致的进冲突池交 Opus 仲裁。完整拓扑和各阶段交接物见 `references/team_pipeline.md`。

规则档由 `run_classify_pipeline.py` 驱动 `classify_boq_engine.py` 跑，产出 `classification.json`；`_finalize_item()` 顺带处理 SortKey（取 `category_code`）和 A 册 Discipline 拆分（Civil / Decoration）。

```bash
python scripts/run_classify_pipeline.py <清单.xlsx> [--header-row 1] -o classification.json
```

JSON 分两段：`items` 是**规则已定案**的，`pending` 是待 LLM 的。引擎会把没匹配上的也标成 `Discipline: Unassigned` 塞回结果里，脚本已经把这类挡在 `items` 之外 —— 放进去就是假值，还会让填充率看着达标、掩盖漏跑 LLM。

阶段 ③④⑦ 定完的结果，按同样的字段格式合并进 `items`（键用表头名 `Discipline` / `SortKey` / `Category` / `Subcategory` / `Element`，每条带 `src_row` 和 `desc_head`）。

### 4. 闭词表校验（阶段 ⑨）

写回前先对 classification.json 的每个值过 `validate_item()`，拦截闭词表外的值并 fuzzy match 修正，不合法值记入 `validation_errors.json` 供人工复核 —— 0 违规才继续写回：

```python
from validate_classification import load_closed_vocab, load_element_vocab, validate_item
vocab = load_closed_vocab(DB_DIR, lang="en")
evocab = load_element_vocab(DB_DIR, lang="en")
# 对 items 逐条 validate_item(Discipline, Category, Subcategory, vocab, "en",
#                              element=Element, element_vocab=evocab)，全 valid 再写回
```

写回的是工作台（不是原清单）时，也能用 `validate_classification.py <工作台.xlsx>` 读表校验 —— 它按表头名找五列，但表头行 / 数据起始行写死工作台布局（第 3 / 5 行），原清单插列场景用上面的 JSON 校验。

### 5. 写回 Excel（阶段 ⑩）

分类的最终交付物是插了分类列的 Excel 文件，不是一份 JSON。写完 classification.json、闭词表校验通过后，把五列插进清单：

```bash
python scripts/write_classification.py <清单.xlsx> -c classification.json \
    [--sheet 合并报表] [--header-row 3] [-o 清单_分类.xlsx]
```

脚本 zip/XML 层手术：清单最右侧隔一空列插入 Discipline / SortKey / Category / Subcategory / Element 五列，按 `src_row` 写值，其余部件（图片、图表、drawing）字节级保留，输出新文件、源清单不修改。表头样式和数据样式从源清单现有表头、描述列动态取，不写死 s 值 —— 分类列是文本，样式跟描述列走，不能跟编号列走。

写回之前先自查两件事：`pending` 是不是已经清空（还有内容就是 LLM 阶段没跑完）、`items` 条数与清单里的有效条目数是否对得上 —— 写回脚本会对这两项直接报错拦下。

**补分类的旁路**：目标已经是建好的工作台、五个 AI 列已就位、只想填值时，用 `run_classify_pipeline.py --write-back <工作台.xlsx>` 直接填值，跳过插列。

> **补分类填值最大的坑：分类列后面还跟着 AI 列（AI Rate / AI Amount），改写单元格必须原位改 `<v>` 或按列号排序，不能"删旧单元格 + 追加到 `</row>` 前"。** 工作台列布局是 `[... 分类列 AO~AS][AI 列 AT/AU]`，分类列不是行尾。若删掉旧 AO~AS 单元格再往行尾追加新单元格，新单元格会跑到 AU 之后，一行内 `<c>` 顺序变成 `...AN AU AO AP AQ`。Excel 严格要求 row 内 `<c>` 按列字母升序，乱序的单元格被静默忽略 → 分类列在 Excel 里整列空白；LibreOffice 按 `r` 属性定位、宽容乱序 → 反而能看到。**症状就是"Excel 看不到、LibreOffice 看得到"。** 正确做法：定位原 AO~AS 单元格的位置原位改 `<v>` 值，或提取该行全部 `<c>` 按列号升序重排后回填。自闭合 `<c .../>` 用正则提取时要注意交替顺序——`<c\b[^>]*/>` 要排在 `<c\b[^>]*>.*?</c>` 之前，否则 `[^>]*` 会把 `/>` 里的 `/` 吞掉、把自闭合格和下一个格并成一个、漏排 33 行。写回后用 openpyxl 读一遍确认五列有值（openpyxl 按列号读、能读到值，但它不验顺序，Excel 打开才是真验收）。

### 6. 交付检查

收工前必须独立验证写回的文件，把输出**原样贴给用户**，不要转述成"已完成"：

- 读回新文件，逐行比对五个分类列的值与 classification.json 是否一致（`src_row` 直接等于 Excel 行号）；
- 原清单区抽查若干数据格，确认一个单元格都没被改动；
- 部件级对比：新文件除目标 sheet 的 XML 外，其余部件与源文件逐字节一致（drawing / media 没丢）；
- 用 fastexcel 独立引擎再读一遍，确认不依赖生成方式也能正常读值。

写回的是工作台（不是原清单）时，改用 `pk-boq-workbench` 的检查脚本验结构 + 填充率：

```bash
python ~/.claude/skills/pk-boq-workbench/scripts/verify_workbook.py <工作台.xlsx> --expect-rows <源清单条目数>
```

五个分类列有 FAIL 就是没做完：填充率低说明漏跑 LLM 阶段，回步骤 3；Element 单独低是词表没覆盖，按册整册注入重跑（见下）。结构类的检查项红了是工作台没装全，回 `pk-boq-workbench`。

## 闭词表三层防线

Discipline 对应定额库分册，Category / Subcategory / Element 必须来自定额库 `division` / `sub_division` / `chapter`（或 `enterprise_item`）闭词表。

| 防线 | 时机 | 机制 | 工具 |
|------|------|------|------|
| 1. Prompt 注入 | LLM 调用前 | 候选名称写进 prompt，明确 "You MUST pick from this list. Do NOT invent, translate, or rephrase." | `build_classification_prompt.py` 的 `build_full_prompt()` |
| 2. 校验门禁 | 写回前 | 每个值过 `validate_item()`，闭词表外的 fuzzy match 修正 | `validate_classification.py` |
| 3. 审计报告 | 写回后 | 不合法值记入 `validation_errors.json` | `validate_classification.py` |

防线 1 不能省。构建 prompt 时从 `route_result.json` 的 candidates 取 `name_en` 和 `subs`，完整写进 prompt —— 直接用 `build_full_prompt(items, vocab, element_vocab)` 就自带这套逻辑。要 Element 就必须传第三个参数（`load_element_vocab()` 的返回值）；不传就没有 element 清单可抄，LLM 只能留空或编造。V3 版本跳过这一层，产出 431 条编造值（"RC Foundations & Plinths" 之类），全靠人工返工。

取值只能用 `name_en`。candidates 同时带中文 `name` 和英文 `name_en`，而 vocab 的键是英文 —— 拿 `name` 去查必然落空，所有类目退化成 "(no subcategories)"，Subcategory/Element 全空。

### 候选检索会漏册，必要时按册整册注入

候选检索按描述文本召回，召不回的册在 prompt 里根本不存在。LLM 判得出册、却看不到该册词表时只会留空。**分册判定这一层很稳，词表覆盖才是短板**，所以遇到 Element 大面积为空时改两轮跑：

1. 第 1 轮只取 LLM 的 `book` 字段（Toilet/UPS/LED→B 这类语义判断可靠）；
2. 按 book 重新分组，第 2 轮给每组注入**该册完整**三层词表（division → sub_division → enterprise_item/chapter）。单册规模可控，覆盖完整。

prompt 里留 `OUT-OF-BOOK` 逃生阀收集跨册误判，收尾交 Opus 跨五册仲裁（阶段⑦），顺带让它把 BOQ 前言、交叉引用（"To be included in section B"）、占位行（"Contractor to itemise"）判成 `NOT-APPLICABLE` —— 这类行不是工程条目，本就不该有分类，规则档也要用同样的正则剔除，别让 UNIQUE 档把它们标上。

> 2026-08-24 Laldia 建筑成本测算：第 1 轮 prompt 里 `### [B]` 段一条都没有（`grep -c` 为 0），Element 空缺率 72%-92%，整批返工。改按册注入后 Element 非空率 92%，闭词表校验 0 违规。

## 脚本

| 脚本 | 用途 |
|------|------|
| `route_boq.py` | 步骤 2：判定 + 分档路由（0 token）→ `route_result.json` |
| `candidate_retrieval.py` | 候选池检索：术语表英文→中文展开 + 五册 SQLite 检索（A/C/D 走 division 两级，B/E 走 chapter 树）+ Dept2 强信号路由（route_boq 调用） |
| `build_classification_prompt.py` | LLM prompt 构建器，强制注入闭词表候选 |
| `classify_boq_engine.py` | 分类引擎：闭词表匹配 + 写回，含 SortKey 和 Discipline 拆分 |
| `run_classify_pipeline.py` | 引擎驱动：读表 → 分类 → 产出 classification.json（`--write-back` 旁路直接填工作台五列） |
| `write_classification.py` | 步骤 5：zip/XML 层把五列插进清单最右侧写回值（原清单场景，不丢 drawing/media） |
| `validate_classification.py` | 闭词表校验 + fuzzy 修正 + 审计报告 |
| `batch_correct.py` | 按 desc_regex 批量修正分类列（人工/LLM 审核后回改） |
| `extract_regions.py` | 按 `{}` 区域抽取条目并聚合分类模式，供 LLM 复核 |
| `layout.py` | 工作台列位（写回 ai 列时用）。**迁移期副本**，权威版在 `pk-boq-workbench/scripts/layout.py`，改动要同步 |

阶段 ③④⑦ 没有脚本入口 —— 由 Claude 读 `route_result.json` 分档，用 `build_classification_prompt.py` 造 prompt 后自行调模型，结果过校验再写回。

遗留不再使用：`add_classification_columns.py`（旧的 16 列右侧插列模式，已由 `pk-boq-workbench` 取代）、`classify_boq.py`（早期劳务分包关键词分类，硬编码项目路径）、`postprocess_sortkey.py`（SortKey 和 Discipline 拆分已并入引擎）。

## 参考

| 文件 | 内容 |
|------|------|
| `references/team_pipeline.md` | 8 阶段拓扑、各阶段职责与交接物、成本控制、可复用引擎 |
| `references/rules_guide.md` | 规则库各键含义、新增规则流程、行号核对的坑、定额库对应关系 |
| `references/classification_rules.json` | 规则库本体（闭词表来源/术语映射/暂列金/skip/routing/patterns） |
| `references/taxonomy_v1.json` | 英文→中文关键词术语表 |
| `references/quota_db_schema.md` | 定额库 5 册表结构 |
| `~/.claude/skills/pk-boq-workbench/references/column_spec.md` | 工作台列布局（写回 ai 列要对列位时看这个） |
| `~/.claude/references/excel-layered-strategy.md` | 通用大表分层策略 |
