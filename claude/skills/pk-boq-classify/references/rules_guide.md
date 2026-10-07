# 分类规则库使用指南

分类和修正必须加载 `references/classification_rules.json`（技能级通用规则，跨项目复用）。人工审核发现的修正先写进规则库再应用，不要散落成脚本里的硬编码 —— 规则库是唯一会被下次运行自动复用的地方。

## 规则库内容

| 键 | 作用 |
|----|------|
| `closed_vocab_source` | 定额库 5 册闭词表来源。Category/Subcategory 必须出自定额库，禁止 LLM 自由生成 |
| `term_map` | Discipline 文字映射。不带分册前缀（不写"A册·"）；PRELIM 用"开办费"不用"前期与合同条款" |
| `provisional_sums_rule` | 章节暂列金/兜底项按 X 归对应分部（"Allow a provision…X WORKS" → X 分部），不塞开办费/措施项目；无章节名的合同级兜底项才留开办费 |
| `skip_patterns` | 说明文字/无条目行识别（如 "In addition to the preamble notes" 这类章节说明），直接 SKIP 不写回 |
| `routing` | 阶段②候选分档阈值：候选分部数 1 → UNIQUE 直接写回、2-3 → Haiku、4+ → Sonnet、0 → Opus/人工 |
| `patterns` | 词 → 分部映射。如防白蚁→土方 A.01、防火封堵→保温隔热 A.12、无障碍标识→其他装饰 A.24、泥浆池砌体→砌筑 A.06、XPS 保温板→保温隔热 A.12、DTA 砂浆→砂浆类 |
| `offset` | 分类行号 = Excel 行号（偏移 0） |

## 行号核对的坑

核对行号时用 openpyxl 读实际单元格，**不要用 fastexcel 的 `to_pandas()`** —— 它会吞掉前导行，制造 +1 的假偏移，照着改会把整批分类挪错一行。

（常规读值仍然优先 fastexcel，只有行号核对这一步例外。）

## 新增规则流程

1. 确认这条规则是"词/模式 → 定额库分部"的**通用**映射，不是某项目独有
2. 写入 `references/classification_rules.json` 的 `patterns` 或 `provisional_sums_rule.mapping`
3. 用 `scripts/batch_correct.py` 应用到已分类数据
4. 更新项目侧的「分类修正记录」

项目特定的行号级覆写不并入技能库，放各项目 `5 项目信息/分类规则/classification_rules.json`（引用技能库 + 行级覆写）。判断标准很简单：换个项目还成立的进技能库，只对这份表成立的留在项目里。

## 术语表

`references/taxonomy_v1.json` 的 `en_zh_seed_glossary` 负责英文→中文关键词展开，`candidate_retrieval.py` 检索定额库前先过这一层。英文 BOQ 检索不到候选时，多半是术语表缺词，补词比改检索逻辑有效。

## 定额库

闭词表来源为 `E:\Code\Norms-AI\db\` 下的五册 SQLite：

| 册 | Discipline | 库文件 | 词表层级 |
|----|-----------|--------|---------|
| A | Civil & Decoration（写回时拆 Civil / Decoration） | 企业定额_A册_建筑装饰.sqlite | division → sub_division → enterprise_item |
| B | MEP Installation | 企业定额_B册_通用安装.sqlite | chapter 树（表里也有 sub_division，但检索走 chapter） |
| C | Municipal & Landscape | 企业定额_C册_市政园林.sqlite | division → sub_division → enterprise_item |
| D | Marine Works | 企业定额_D册_水运工程.sqlite | division → sub_division → enterprise_item |
| E | Building Repair & Renovation | 企业定额_E册_房屋修缮.sqlite | chapter 树（sub_division / enterprise_item 均为空） |

册名和文件名由 `classification_rules.json` 的 `closed_vocab_source.books` 定义，`candidate_retrieval.py` 从那里读，不在代码里硬编码。加册只改 JSON。

表结构见 `quota_db_schema.md`。SQLite 更新后闭词表自动生效，不需要改代码或重跑规则。
