# 四场景映射到 8 阶段流水线（模式 B）

四个已固化的场景技能，各自是 8 阶段流水线的一个实例化。做任务时先定位到场景技能，再按本表对照 8 阶段——缺的阶段按 layered-pipeline.md 补上。

## 总览

| 场景 | 场景技能 | 主要阶段 | 模型分工 |
|---|---|---|---|
| 分类 | pk-boq-classify | ①-⑧ 全链 | 执行 Haiku / 语义 Sonnet / 仲裁 Opus |
| 套价(DB) | pk-boq-db-match | ①-⑧ 全链（⑧回写列不同） | 执行 Haiku / 校验 Sonnet / 决策 Opus |
| 套定额 | pk-norms-match | ①-⑧ 全链（已升级） | 执行 Haiku/Sonnet / 审核 Sonnet / 仲裁 Opus |
| 分级 | pk-boq-hierarchy | ①-⑧ 全链（脚本 + Claude Code Agent） | 脚本判定 / 三 Agent 语义审查 / 主上下文仲裁 |

## 各场景的 ①-⑧ 实例

### 分类（pk-boq-classify）

| 阶段 | 实例化 |
|---|---|
| ① 校准 | `classification_rules.json`（term_map / provisional_sums_rule / skip_patterns / routing / patterns / offset）+ `taxonomy_v1.json`（闭词表）|
| ② 路由 | `route_boq.py`：跳过/暂定金额/唯一命中判定 + 闭词表候选检索 + 按候选分部数分档（1→UNIQUE、2-3→Haiku、4+→Sonnet、0→Opus/人工）|
| ③④⑤ | 分类列写回（Dept/Discipline/Category/Subcategory/Material/Spec），唯一/跳过直接写回 |
| ⑥ | ③④ 跨模型比对，一致自动通过，不一致进冲突池 |
| ⑦ | Opus 只仲裁冲突 + 零候选 + 高风险项 |
| ⑧ | 回写分类列 + 变更标记 + 报告；项目行号级覆写放各项目 `分类规则/`，通用规则沉淀回 ① |

### 套价（pk-boq-db-match）

| 阶段 | 实例化 |
|---|---|
| ① 校准 | 术语表 `glossary_and_families.json`（en2cn 524词 + cn2en 195组）+ 家族标签 `family_tags.json`（35家族）+ domain synonym map + 分档阈值(conf≥0.85/0.6) + 红线规则（币种硬约束/系统价vs材料价/单位换算） |
| ② 路由 | `route_price.py`：结构探针(fail-fast) + 数据准备(拉池/去重/检索/候选top-8) + 规则直定(skip/construction_only/基线直定) + 候选分档(2-3→Haiku / 4+→Sonnet / 零→Opus) |
| ③④⑤ | ③ Haiku×N 星型并行(2-3候选) conf<0.6 升级 ④ Sonnet 重判(4+候选/跨语言)；⑤ 规则直定项直接写回 0 token |
| ⑥ | ③④ 跨模型比对(一致→通过，不一致→冲突池) + Auditor 独立抽检 high 项 + no_match 家族批搜补救(MongoDB) |
| ⑦ | Opus 限量仲裁：冲突池 / 零候选 / 跨语言疑难 / 币种终裁 |
| ⑧ | 按 BQ Code 索引写回 _AI版.xlsx O-W 列 + 验证(A-N diff/人工区/总计行) + 单位换算修复 + HTML报告 + 人工确认沉淀回① |

### 套定额（pk-norms-match）

| 阶段 | 实例化 |
|---|---|
| ① 校准 | config.json（数据库路径 + chapter_mapping 章节映射 + boq_columns）+ 匹配阈值 + prompt 模板 |
| ② 路由 | 定额池构建（按章节查 SQLite，拼完整路径编码 `{册}.{章节}.{子目}`）+ 前置过滤（零工程量/标题行/概念单位）+ 按工程专业拆批 |
| ③④⑤ | 每 Agent 60-150 条（硬限制，超限自动拆批）；并发上限 5（分波次）；skip/无对应定额/单位不兼容分档 |
| ⑥ | 抽样审核 Agent（随机 10% 逆向验证，通过率 <80% 的 Agent 整批标"需人工复核"）|
| ⑦ | Opus 仲裁冲突项 / 单位不兼容降级项（黄色标记）|
| ⑧ | `write_results.py` 写 A/B 列定额编号+名称 + 合并 `merged_semantic_final.json` + 报告 |

### 分级（pk-boq-hierarchy）

| 阶段 | 实例化 |
|---|---|
| ① 校准 | 层级规则（`boq_hierarchy_rules.md`）+ Phase 1 增强硬规则（含「为方便」→ 封顶 L3、含「暂按下方设计」→ 封顶 L3）|
| ② 路由 | `apply_hierarchy.py --export-review`：有单位+数量→L4、编码→L2、括号→权威、噪声→Note；歧义行导出 review JSON |
| ③④⑤ | 三 Agent 语义审查（Claude Code `Agent` 工具，非外部API）：结构审查 + 语义审查 + 边界审查，各输出修正建议 JSON |
| ⑥ | 三 Agent 交叉比对：一致→通过，多数一致→采纳，三方分歧→进冲突池 |
| ⑦ | 主上下文仲裁冲突项 + 低置信项 |
| ⑧ | 从干净原始合并文件重建 xlsx（禁止叠改已有层级文件）|

> **注意**：分级审查使用 Claude Code 内置 Agent 工具，不是外部 API。流程中的①②⑤可在一次脚本运行中完成，③④⑤通过 Agent 工具并行调用，⑥⑦在主上下文中执行。

## 模型分层通用约定

| 角色 | 模型 | 职责 | 原则 |
|---|---|---|---|
| 执行 | Haiku（默认） | 干最多活，星型并行 | 便宜、量大；术语精确性要求高时 conf<0.6 升级 Sonnet |
| 校验 | Sonnet | 独立复核执行结果 | 换模型 = 独立信号，拦截执行层误判 |
| 决策 | Opus | 限量仲裁 | 只仲裁冲突/零候选/高风险，不做常规 |
| 纯规则 | Python | 跳过/唯一/暂定直接处理 | 0 token，命中率 100% |

## 跨场景复用检查清单

每次开新场景任务，对照以下问题定位是否缺阶段：

1. ① 有没有"Opus 离线校准"？——规则库/术语表/阈值/prompt 模板是否已固化，还是直接拍脑袋跑？
2. ② 路由脚本是否 0 token？——跳过/唯一/暂定是否被脚本消化，还是全送 LLM？
3. 分档是否生效？——按候选数/难度选模型（LOW→Haiku、HIGH→Sonnet），还是全员同一模型？
4. ⑥ 有没有独立校验？——校验模型是否与执行不同（独立信号）？
5. ⑦ Opus 是否限量？——只仲裁冲突/零候选，还是被拉去做常规？
6. ⑧ 人工确认是否沉淀回 ①？——下次运行能否自动复用，还是每次从零开始？
7. 切批是否按 token 预算？——还是按行数/章节切（小 slice 固定开销摊不薄，agent 数虚高）？
8. ⑧ 写回前是否 dry-run 预检？——覆盖率报表 + 闭词表校验，断层堵在写盘前，还是写回后返工？
9. agent prompt 是否裁剪？——只带闭词表/候选/行格式/输出约束，还是塞了完整技能说明（纯浪费）？
