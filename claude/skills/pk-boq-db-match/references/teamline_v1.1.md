# Teamline v1.1 — db-match 套价管线拓扑

> 版本: v1.1 | 日期: 2026-08-06 | 项目: 泰国 CMI MOD2 数据中心 V17
>
> 本图是 db-match（BOQ → 报价数据库套价）8 阶段管线的权威拓扑。
> 上一版本: [archive/teamline_v1.0.md](archive/teamline_v1.0.md)

## 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.1 | 2026-08-06 | 三项 token 优化：① Matcher 最小执行包（208→80行，-60%）② 候选置信度预过滤（MIN_CANDIDATE_SCORE=12）③ 已知无覆盖家族标签（KNOWN_GAPS，跳过③④⑥⑦） |
| v1.0 | 2026-08-06 | 初始版本。移除 ⑤ 纯规则阶段和 construction_only 分支；② 检索层双源并行（CostSpread API + MongoDB）。 |

## Token 优化（v1.1 新增）

| # | 优化 | 位置 | 机制 | 省 token |
|---|------|------|------|---------|
| ① | Matcher 最小执行包 | `references/matcher_minimal_context.md` | Sub-agent 只拿 80 行核心规则（输出 schema + 材料红线 + 标号匹配 + 单位换算 + 家族提示），完整方法论留在路由脚本/SKILL.md | ~60%/次调用 |
| ② | 候选置信度预过滤 | `04_cluster_retrieve.py:rerank_for_item()` | `MIN_CANDIDATE_SCORE = 12`，低于阈值的候选剔除。全部低于阈值 → 空候选池 → 不发给 Matcher | ~15-25% 候选量 |
| ③ | 已知无覆盖标签 | `04_cluster_retrieve.py:main()` | `KNOWN_GAPS` = `{earthwork, formwork, curtain_wall, glass, handrail, fire_coating, steel_coating, insulation_board}` — 这些家族的项候选池为空时直接标 `known_gap` → ⑧，跳过③④⑥⑦ | ~8-15% 项零 token |

## 8 阶段管线

```
                    ┌──────────────────────────────────────────────────────────────┐
                    │  ① Opus 离线校准（一次性 · 规则更新时）                         │
                    │                                                              │
                    │  术语表 glossary_and_families.json  │  家族标签 family_tags   │
                    │  domain synonym map (48条种子)       │  分档阈值 conf≥0.85/0.6 │
                    │  红线规则（币种/单位换算/系统价vs材料价）                        │
                    │  search-dictionary.js（截桩头/场地平整/白蚁防治）               │
                    │  matcher_minimal_context.md（Sub-agent 最小执行包）             │
                    └────────────────────────────────────┬─────────────────────────┘
                                                         │
                                                         ▼
                    ┌──────────────────────────────────────────────────────────────┐
                    │  ② 脚本路由（Python · 0 token · 每次运行）                      │
                    │                                                              │
                    │  结构探针 → 拉池去重 → 提取 AI-todo → 家族归类                   │
                    │                                                              │
                    │  检索（双源并行）：                                              │
                    │  ┌─────────────────────────┐  ┌─────────────────────────┐     │
                    │  │ CostSpread API (新增)    │  │ MongoDB 关键词检索 (原有) │     │
                    │  │ docker exec → HTTP       │  │ pymongo 直连             │     │
                    │  │ 中英双语扩展 + 加权评分   │  │ 术语表预翻译 + keyword   │     │
                    │  │ name=100 synonym=60      │  │ domain synonym map      │     │
                    │  └───────────┬─────────────┘  └───────────┬─────────────┘     │
                    │              └──────────┬──────────────────┘                   │
                    │                         ▼                                     │
                    │              合并去重 → 候选池 (CostSpread优先, MongoDB兜底)     │
                    │                                                              │
                    │  Token 优化路由:                                                │
                    │  ┌─ MIN_CANDIDATE_SCORE=12 预过滤低分候选                       │
                    │  └─ KNOWN_GAPS 家族空候选 → 直接标 known_gap → ⑧ (跳过③④⑥⑦)   │
                    │                                                              │
                    │  分档：skip→⑧ │ 2-3候选→③ │ 4+候选→④ │ 零候选→⑦              │
                    │           known_gap→⑧ (跳过③④⑥⑦)                             │
                    └──────┬───────────┬──────────┬──────────────┬─────────────────┘
                           │           │          │              │
                          skip     2-3候选    4+多候选/       零候选
                           │      known_gap    低置信升级    (非known_gap)
                           │         │          │              │
                           │         ▼          ▼              │
                           │   ┌──────────────────────────┐      │
                           │   │  ③ Haiku Matcher ×N 星型   │      │
                           │   │  (最小执行包 80行, -60%)   │      │
                           │   │                            │      │
                           │   │  ┌────────┐┌────────┐     │      │
                           │   │  │ Pkg A  ││ Pkg B  │ ...  │      │
                           │   │  └───┬────┘└───┬────┘     │      │
                           │   │      └────┬────┘          │      │
                           │   │           │ conf<0.6 升级  │      │
                           │   │           ▼               │      │
                           │   │  ④ Sonnet 精修            │      │
                           │   └─────────────┬─────────────┘      │
                           │                 │                    │
                           │                 ▼                    │
                           │   ┌──────────────────────────────────┐│
                           │   │  ⑥ 跨模型比对 + Auditor 补搜      ││
                           │   │  (Sonnet · 独立信号)              ││
                           │   │                                  ││
                           │   │  ③ vs ④ 比对 → 冲突池            ││
                           │   │  no_match 按家族 MongoDB 补搜     ││
                           │   │  仍未匹配 → ⑦                    ││
                           │   └─────────────────┬────────────────┘│
                           │                     │                  │
                           │                     ▼                  │
                           │   ┌──────────────────────────────────┐ │
                           │   │  ⑦ Opus 仲裁（限量·只裁争议）     │ │
                           │   │                                  │ │
                           │   │  冲突池 / 双源矛盾 / 跨语言疑难    │◄┘
                           │   │  币种硬约束终裁 (非THB→汇率换算)   │
                           │   │  终裁 → 人工确认 → 沉淀回 ①       │
                           │   └─────────────────┬────────────────┘
                           │                     │
                           └─────────────────────┼──────────────────
                                                  │
                                                  ▼
                    ┌──────────────────────────────────────────────────────────────┐
                    │  ⑧ 回写 + 验证 + 报告（Python + 人工）                         │
                    │                                                              │
                    │  按 BQ Code 写入 _AI版.xlsx O-W 列                             │
                    │  验证: A-N diff=0 / 人工区 N列>0 跳过 / 总计行清零              │
                    │  单位换算修复 (rebar t→kg / m2↔m3) / HTML 报告                 │
                    │  known_gap 项 → 人工队列 → 沉淀回 ①                            │
                    └──────────────────────────────────────────────────────────────┘
```

## 模型分层铁律

| 层级 | 角色 | 模型 | 职责 | 触发条件 |
|------|------|------|------|---------|
| ① | 设计者 | Opus | 定规则/阈值/路由/prompt模板/最小执行包 | 一次性/规则更新时 |
| ② | 路由 | Python | 双源检索 + 候选合并 + 分档 + 预过滤 + known_gap 路由 | 每次运行（0 token） |
| ③ | 执行者 | Haiku | 星型并行批量匹配（使用最小执行包） | 2-3 候选的常规项 |
| ④ | 执行者 | Sonnet | 重判升级项 + 复杂项 | 4+ 候选 / conf<0.6 升级 |
| ⑥ | 审核者 | Sonnet | 跨模型比对 + no_match 补搜 | ③④ 产出后 |
| ⑦ | 决策者 | Opus | 只裁争议 | 冲突池 / 零候选 / 双源矛盾 |
| ⑧ | 回写 | Python | 写回 + 验证 + 报告 | 全部定案后 |

**核心铁律：换模型 = 独立信号。** 执行 Haiku / 校验 Sonnet / 决策 Opus。同模型自我确认偏差——执行器误判必须由不同模型的校验层拦截。

## ② 检索双源说明

| 检索源 | 调用方式 | 强项 | 弱项 | 命中率 |
|--------|---------|------|------|--------|
| CostSpread API | `docker exec` → `/api/rates/search` | 物料级（混凝土标号/钢材规格/卫浴） | 施工活动/复杂系统 | ~60% |
| MongoDB | pymongo 直连 | 施工活动/跨语言语义匹配 | 物料精确规格不如 CostSpread | ~75% |

合并: CostSpread 优先，MongoDB 兜底，按 `_id` 去重。

## 各阶段脚本对应

| 阶段 | 脚本/Agent | 输入 | 输出 |
|------|-----------|------|------|
| ② | `04_cluster_retrieve.py` | BOQ items + rate pool | 候选池 + 家族分包 + known_gap 标签 |
| ③ | Haiku Agent (matcher_minimal_context.md) | 候选池 (2-3候选) | `matcher_*.json` |
| ④ | Sonnet Agent (matcher_minimal_context.md) | 升级项 + 复杂项 | `reviewer_*.json` |
| ⑥ | Sonnet Agent (auditor_prompt.md) | ③④ 输出 + no_match | 比对报告 + 补搜结果 |
| ⑦ | Opus Agent | 冲突池 + 零候选 | 终裁结果 |
| ⑧ | `06_writeback_by_code.py` | 全部匹配结果 | `_AI版.xlsx` |

## 与 v1.0 的区别

| | teamline_v1.0 | teamline_v1.1 |
|---|---|---|
| Matcher prompt | 208 行完整 prompt 每份拷贝 | 80 行最小执行包（省 ~60% token） |
| 候选过滤 | 无过滤，全部 top-8 发给 Matcher | MIN_CANDIDATE_SCORE=12 预过滤低分候选 |
| 零候选处理 | 全进 ⑦ Opus 仲裁 | KNOWN_GAPS 家族空候选直接标 known_gap → ⑧ |
| ③ 阶段 token | 完整 prompt 每 sub-agent | 最小执行包，省 ~60% |
