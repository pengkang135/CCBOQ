# 团队协同拓扑（Team Line）

> 本技能是通用 8 阶段流水线（**`pk-boq-ai-team`** 模式 B）在数据库套价场景的实例化。
> 核心原则：**代码负责组织，LLM 负责判断，记忆负责学习，人工负责持续优化**。
> 与套定额不同——价格库是乱的（中英混排、名称不统一、单位不一致），不存在 100% 纯规则匹配的东西，所有匹配判断必须过 LLM。

```
                 ┌────────────────────────────────────────────┐
                 │          Memory Base（持续学习）            │
                 │ glossary │ family │ cases │ prompt │ rule │
                 └──────────────▲───────────────▲────────────┘
                                │               │
                        人工反馈 │               │ Opus 校准
                                │               │

┌────────────────────────────────────────────────────────────────────┐
│ ① Opus Calibration（离线 · 一次性 · 不计入线上成本）                │
│ 黄金集 · Prompt · Family 定义 · Domain Map · Threshold · Red Line  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ ② Orchestrator（Python · 纯代码 · 0 token）                        │
│                                                                    │
│ Excel 读取 · 数据清洗 · 检索候选 · Mongo 聚合 · Family 分包         │
│ Worker 调度 · 结果合并                                              │
│                                                                    │
│ **不做任何套价判断**——只负责数据组织和分发                            │
└──────┬─────────────────────────────────────────────────────────────┘
       │
       │ Star Parallel（按 Family 分包，互不通信）
       ▼
┌────────────────────────────────────────────────────────────────────┐
│                 ③ Haiku Worker × N                                │
│                                                                    │
│ Package A  │  Package B  │  Package C  │  ...                      │
│                                                                    │
│ 每个 Worker 独立完成：                                              │
│ • 理解 BOQ 描述（中英双语）                                        │
│ • 比较候选池（top-8 candidates）                                   │
│ • 判断规格档位（DB16 vs DB20 价差 40%）                            │
│ • 判断单位相容（kg↔t, m2↔m3 厚度桥接）                            │
│ • 语义匹配（系统价 vs 材料价区分）                                  │
│ • 输出 confidence + reasoning                                      │
│                                                                    │
│ 输出状态：high / medium / low / estimated / no_match               │
└──────────────┬─────────────────────────────────────────────────────┘
               │
     conf<0.75 │ 低置信升级（Haiku 不硬撑）
               ▼
┌────────────────────────────────────────────────────────────────────┐
│             ④ Sonnet Reviewer（独立信号 · 不同模型）                │
│                                                                    │
│ Second Opinion — 防止 Haiku 系统性误判传递                          │
│                                                                    │
│ • 重判 conf<0.75 的升级项                                          │
│ • 处理 4+ 候选的复杂项                                             │
│ • 跨规格判别（如 DB16 vs DB20 价差）                               │
│ • 跨语言精修（英文 BOQ ↔ 中文 rate name）                          │
│ • 重新评分                                                         │
│                                                                    │
│ 输出：high / medium / low / estimated / no_match                   │
└──────────────┬─────────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────────┐
│              ⑤ Compare Agent（跨模型比对 · Sonnet）                 │
│                                                                    │
│ ③ Haiku vs ④ Sonnet 输出比对                                      │
│                                                                    │
│ 一致 ──────────────► PASS（直接采纳）                               │
│ 不一致 ────────────► Conflict Pool → ⑦ Opus 仲裁                   │
│ no_match ──────────► ⑥ Auditor 补搜                                │
└───────┬───────────────────────────────────────┬────────────────────┘
        │                                       │
        │                                       ▼
        │                    ┌──────────────────────────────────────┐
        │                    │      ⑥ Auditor Agent（Sonnet）       │
        │                    │                                      │
        │                    │ 按 Family 分组 → 1 次 Mongo 查询     │
        │                    │ 覆盖整个家族的多项 no_match           │
        │                    │                                      │
        │                    │ 给 LLM 更多上下文（放宽检索范围）      │
        │                    │                                      │
        │                    │ Recovery: 补救 30-50% no_match        │
        │                    │ 仍未匹配 → ⑦                          │
        │                    └──────────────┬───────────────────────┘
        │                                   │
        └───────────────────────┬───────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│              ⑦ Opus Final Decision（限量 · 只裁争议）               │
│                                                                    │
│ Conflict Pool / Zero Candidate / Cross-Language                    │
│ Currency 终裁 / Complex Engineering                                │
│                                                                    │
│ 最终决策 → 人工确认 → 沉淀回 ① + Memory Base                       │
└──────────────┬─────────────────────────────────────────────────────┘
               ▼
┌────────────────────────────────────────────────────────────────────┐
│              ⑧ Writer + Validation + Report（Python + 人工）        │
│                                                                    │
│ 按 BQ Code 索引写回 _AI版.xlsx Q-Z 列                               │
│ 验证：A-N diff=0 / 人工区不变 / 总计行清零                          │
│ 单位换算修复（rebar t→kg / m2↔m3 厚度）                            │
│ HTML 报告 + Metrics                                                │
│                                                                    │
│ Confirmed Cases → Memory Base（人工确认结果沉淀）                   │
└────────────────────────────────────────────────────────────────────┘
```

## 核心原则

**代码负责组织，LLM 负责判断，记忆负责学习，人工负责持续优化。**

- ② Orchestrator 只做数据组织（读 Excel、拉池、检索、分包、调度），**不做任何套价判断**
- ③④ 所有 BOQ 项都过 LLM 语义匹配——价格库没有"纯规则 100% 命中"的东西
- ③ Haiku 跑量（低成本），conf<0.75 自动升级 ④ Sonnet 重判（独立信号）
- ⑥ Auditor 按 Family 批搜，省 3-5x tool_use
- ⑦ Opus 限量：只裁争议，不做常规匹配
- 人工确认结果沉淀回 Memory Base（glossary / family / cases / prompt / rule）

## 与套定额的关键区别

| | 套定额（norms-match） | 套价（db-match） |
|---|---|---|
| 数据源 | 定额库（闭词表，结构化） | 价格库（中英混排，非结构化） |
| 匹配方式 | 有纯规则直定（skip/唯一命中） | **所有匹配必须过 LLM** |
| ⑤ 阶段 | 纯规则自动（0 token） | **不存在**——改为跨模型比对 |

## 模型分层铁律

**执行 Haiku / 校验 Sonnet / 决策 Opus**——三层不同模型，各自独立信号。

- Haiku conf<0.75 自动升级 Sonnet 重判（DB16 vs DB20 价差 40%，Haiku 不硬撑）
- Opus 限量：只做 ① 定规则 + ⑦ 仲裁冲突 / 终审分布，不做常规匹配
- 换模型 = 独立信号，防止 AI 自己说服自己

## 各阶段产物

| 阶段 | 输入 | 输出 |
|------|------|------|
| ① 校准 | 历史匹配数据 + 人工反馈 | glossary / family / domain map / threshold / prompt 模板 |
| ② 编排 | BOQ xlsx + rate pool MongoDB | `route_result_pricing.json`（候选池 + Family 分包） |
| ③ 执行 | route_result（按 Family 分包） | `matcher_*.json`（并行产出，conf + status + reasoning） |
| ④ 复核 | ③ 升级项 + 复杂项 | `reviewer_*.json`（精修后 high/medium/low/estimated/no_match） |
| ⑤ 比对 | ③ + ④ 输出 | 一致性报告 + Conflict Pool + ⑥ Auditor 输入 |
| ⑥ 补搜 | no_match 按 Family 分组 | Auditor 补搜结果（recovery 30-50%） |
| ⑦ 仲裁 | Conflict + Zero Candidate + 跨语言 | Opus 终裁结果（限量） |
| ⑧ 回写 | 全部匹配结果 (by BQ Code) | `_AI版.xlsx` + `report.html` + Metrics |
