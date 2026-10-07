---
name: pk-boq-db-match
description: "BOQ 清单从报价数据库（CostSpread MongoDB rates 集合等）语义套价：LLM 分层团队协作 (Matcher + Reviewer + Auditor + Opus) + 术语表双语检索 + 家族归类批处理 + 候选去重。用于将 BOQ 项从数据库找对应 rate 单价填入 Q-Z 列。触发词：数据库套价、CostSpread 套价、rate 库匹配、BOQ 数据库查价、AI 套价、语义套价、BOQ 匹配报价库、找单价、大数据库套价。"
---

# PK BOQ — 数据库套价（LLM 语义匹配）

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


> 本技能处理 **BOQ 项 ↔ 报价数据库**（如 CostSpread 泰国 THB 池 12,000+ 条）的语义匹配，需 LLM 处理中英双语、单位换算、施工措施识别、无中生有兜底。

## 什么时候用

- BOQ 清单（英文描述居多）需要从报价数据库（rates 集合，含 12K+ 条中英混排 rate）找对应单价
- 单纯 keyword regex 命中率 < 70%（跨语言 + 规格差异 + 施工措施混入）
- 数据库规模大（>5K 条），不能全塞给 LLM

## 核心原则

**代码负责组织，LLM 负责判断，记忆负责学习，人工负责持续优化。**

价格库是乱的——中英混排、名称不统一、单位不一致。不存在"100% 纯规则命中"的东西，所有匹配判断必须过 LLM。

## 工作流

> 通用 8 阶段流水线（`pk-boq-ai-team` 模式 B）在数据库套价场景的实例化。
> 团队协同拓扑、模型分层铁律、各阶段产物详见 **[references/teamline_v1.2.md](references/teamline_v1.2.md)**（当前版本）。
> 历史版本: [v1.1](references/teamline_v1.1.md) | [v1.0](references/archive/teamline_v1.0.md)

| 阶段      | 做什么                                                       | 谁做                     |
| ------- | --------------------------------------------------------- | ---------------------- |
| ① 离线校准  | glossary / family / domain map / threshold / prompt 模板    | Opus（一次性）              |
| ② 编排路由  | Excel 读取 · 数据清洗 · 检索候选 · Mongo 聚合 · Family 分包 · Worker 调度 | Python（0 token，不做套价判断） |
| ③ 执行    | 全量 BOQ 项语义匹配，conf<0.75 升级④                                | Haiku ×N 并行            |
| ④ 复核    | 升级项 + 复杂项精修重判（独立信号）                                       | Sonnet                 |
| ⑤ 比对    | ③ vs ④ 跨模型比对：一致→通过，不一致→Conflict，no_match→⑥                | Sonnet                 |
| ⑥ 补搜    | 按 Family 分组批搜 Mongo，补救 30-50% no_match                    | Sonnet                 |
| ⑦ 仲裁    | Conflict / Zero Candidate / 跨语言 / Currency 终裁             | Opus（限量）               |
| ⑧ 回写+报告 | 按 BQ Code 写回 XLSX，验证，**强制生成 HTML 套价报告**（→ 源文件目录/套价报告/V{版本号}_AI套价报告.html），确认结果沉淀 Memory Base | Python + 人工            |

## 三项核心优化

| 优化 | 做什么 | 收益 |
|------|--------|------|
| **双语词表** | en2cn 524 词 + cn2en 195 组，`build_query_terms` 双向扩展 | 英文 BOQ 能命中纯中文 rate |
| **候选去重** | rate 池按 (normalized_name, unit) 聚合，取最新+均价 | 池大小 ↓70%+ (10716→3028) |
| **家族归类批处理** | BOQ 描述→35 产品家族，Auditor 按家族 1 次查询覆盖多项 | MongoDB 查询 82→27 次 |

## 分类字段复用（与 pk-boq-classify 协同）

**如果 BOQ 已带 Discipline/Category/Subcategory/Material/Spec 分类列（由 `pk-boq-classify` 产出），套价流程必须充分利用**：

- **Material** → 直接替代产品家族归类
- **Subcategory** → 缩小候选池范围（同子分部历史报价更相关）
- **Spec** → Matcher prompt 规格锚点，直接用于价格档位判别

## 铁律

1. **rate 池 API**：`price_incl_tax > 0` 才收，name 为空或纯数字剔除。**禁止 `len(name) >= 4` 过滤**——中文 2-3 字产品名会被误杀，`len < 2` 即可
2. **所有匹配判断必须过 LLM**：与套定额不同，价格库没有"纯规则 100% 命中"的东西。② Orchestrator 只做数据组织，不做任何套价判断
3. **单位换算硬约束**：kg↔t ÷1000；m2↔m3 需 BOQ 描述含厚度；混凝土 m3↔t 用 2.4 t/m3
4. **汇率换算按入价月**：非 THB 候选可入池，定案价按入价月份汇率（`temp/fx_rates.json`）换算。检索层只过滤国家不过滤币种
5. **写入前人工列保护**：人工单价列正数才跳过（用户真实单价）；=0/None/空串继续写 AI
6. **绝对不动源区/人工区**：只写 AI 写回区（默认 A-N 不动，列号以参数为准）
7. **总计行清零**：按配置的总计标识（默认 A=='总计'）写回跳过
8. **BQ Code 索引优先**：源文件行号会漂移，产物用 BQ Code (F 列) 索引最稳
9. **套价完成必须生成 HTML 报告**：回写 XLSX 后，必须在源文件同目录的「套价报告」文件夹内生成完整的 HTML 套价报告。使用通用脚本 `scripts/generate_pricing_report.py --config <项目config.json>` 生成，设计模板见 `references/report_template.html`。报告包含：汇总卡片（总项数/覆盖率/高中低分布）、mermaid 4层流水线拓扑图、按 Discipline 统计表、High/Medium 明细表、Low/Estimated 明细、No-match/Gap 清单。报告文件名格式：`{项目名}_AI套价报告.html`

## 常见坑

详见 **[references/pitfalls.md](references/pitfalls.md)**。高频问题：钢筋 t/kg 错位、手工套价被覆盖、中文 name_cn 漏查、非 THB 价未换算、domain map 覆盖不足。

## 调用方式

```bash
# Stage 1: 数据准备
python scripts/01_pull_rate_pool.py --conn "mongodb://..." --country 泰国 --currency THB --out temp/rate_pool.json
python scripts/02_extract_boq.py --xlsx "套价版.xlsx" --sheet UniqueBQ --header-row 4 ... --out temp/boq_items.json
python scripts/03_dedup_pool.py --pool temp/rate_pool.json --out temp/pool_dedup.json

# Stage 2: 编排路由（纯数据组织，不做套价判断）
python scripts/04_cluster_retrieve.py --pool temp/pool_dedup.json --boq temp/boq_items.json ... --out temp/route_result_pricing.json
python scripts/05_split_packages.py --route temp/route_result_pricing.json --out-prefix temp/pkg_

# Stage 3: Haiku Workers ×N 并行（Agent tool, subagent_type=general-purpose, model=haiku）
# Prompt: references/matcher_prompt.md
# Input: temp/pkg_A.json, pkg_B.json, pkg_C.json ...
# Output: temp/matcher_A.json, matcher_B.json, matcher_C.json ...

# Stage 4: Sonnet Reviewer（Agent tool, model=sonnet）
# 输入: ③ 中 conf<0.75 的升级项 + 4+候选复杂项
# Output: temp/reviewer_out.json

# Stage 5-6: Compare + Auditor（Agent tool, model=sonnet）
# Prompt: references/auditor_prompt.md
# ③ vs ④ 比对 + no_match 按 Family 批搜 Mongo
# Output: temp/auditor_out.json

# Stage 7: Opus 仲裁（Agent tool, model=opus）
# 只裁 Conflict Pool / Zero Candidate / 跨语言 / Currency

# Stage 8: 回写+报告
python scripts/06_writeback_by_code.py --src "套价版.xlsx" --dst "套价版_AI版.xlsx" --by-code temp/results_by_code.json
# ↓ 强制步骤：生成 HTML 套价报告到源文件同目录的「套价报告」文件夹（铁律 #9）
python scripts/generate_pricing_report.py --config temp/report_config.json
```

## 输出契约

```json
{
  "excel_row": 178,
  "family": "rebar",
  "status": "high|medium|low|estimated|no_match",
  "matched_id": "abc123ef",
  "matched_name": "钢筋制作与安装",
  "matched_unit": "kg",
  "matched_price_thb": 20.30,
  "converted_price_thb": null,
  "matched_project": "Galaxy Peak Data Center",
  "matched_supplier": "二航三",
  "matched_date": "2026-07-29",
  "similarity": 0.92,
  "reasoning": "..."
}
```

Auditor 覆盖记录带 `action: "redo|downgrade|confirm"` 和 `new_*` 前缀字段。

## 参考文件

- `references/team_line.md` — 团队协同拓扑 + 模型分层铁律 + 与套定额的关键区别
- `references/pitfalls.md` — 22 条实测坑位 + Domain Map 覆盖不足修复方法
- `references/glossary_and_families.json` — 双语词表 + 35 家族触发词（脚本数据源）
- `references/domain_synonym_map.json` — 48 条 domain map 种子数据（脚本数据源）
- `references/column_conventions.md` — BOQ 列布局约定
- `references/matcher_prompt.md` — Matcher sub-agent 提示词模板（含完整单位换算规则）
- `references/auditor_prompt.md` — Auditor sub-agent 提示词模板（含完整家族批搜关键字表）
- `references/report_template.html` — HTML 套价报告设计模板（V19 终版，含完整 CSS/mermaid 拓扑图/sticky 表头/自适应换行/居中布局）

## 术语表交叉引用

本技能的 `references/glossary_and_families.json` 与 `translation-agent` 的两份术语表**用途不同、不建议合并**：

| 术语表 | 粒度 | 方向 | 目的 |
|---|---|---|---|
| **本技能 glossary_and_families.json** | 原子关键字 (concrete, gypsum) | EN→CN | 构建 DB 检索查询 |
| `translation-agent/references/nrm-glossary.json` | QS/合约术语（综合单价、暂列金额） | CN→EN | 商务/合约文档翻译 |
| `translation-agent/references/boq-glossary.json` | BOQ 全句/章节标题 (600+ 港工项条目) | EN→CN | BOQ 文档翻译 |

**协同用法**：如项目已用 `translation-agent` 翻译过 BOQ，可把术语补进本技能的 en2cn 词表（港工/水工/特种材料等覆盖不足领域）。本技能的 `family_tags` 对 translation-agent 无直接用途（搜索层概念）。

**已知一致性**：`lean concrete → 贫混凝土` 与 NRM 通用做法对齐。避免 `素混凝土`（应对应 `plain concrete`，两者非同物）。

## 相关技能

- `pk-boq` — BOQ 入口路由
- `pk-boq-ai-team` — >500 行 BOQ 处理策略 + AI 团队协作
- `pk-boq-quotation` — 报价单导入 CostSpread
- `translation-agent` — BOQ 文档翻译（术语表交叉引用见 `references/glossary_xref.md`）
