# BOQ 分类 · 多智能体团队协作分工拓扑

> 大表（>500 行）强制按此拓扑执行。核心是第 2 步**脚本化路由**（纯代码 · 0 token）：
> 先按规则判定，再闭词表检索，按候选分部数分档，只把必要的行送 LLM，按候选数选便宜/贵的模型。

## 分工图

```
                 ┌─────────────────────────────────────────────────┐
                 │  ① Opus 离线校准（一次性 · 不计入线上成本）         │
                 │  归一化规则 · 检索策略 · 分类阈值 · 路由表          │
                 │  prompt 模板 · 黄金集校准                        │
                 └──────────────────────┬──────────────────────────┘
                                        │  规则 / 阈值 / 路由表
                                        ▼
                 ┌─────────────────────────────────────────────────┐
                 │  ② 脚本跑全表 → 判定（纯代码 · 0 token）           │
                 │  跳过项 / 暂定金额 / 唯一命中 / 2-3候选 / 4+近似   │
                 │  / 零候选异常                                    │
                 └─────┬────────────┬──────────────┬────────────────┘
                  跳过/暂定/唯一   2-3候选       4+多候选/近似      零候选/异常
                       │            │              │                │
                       ▼            ▼              ▼                │
               ┌──────────────┐ ┌──────────┐ ┌──────────────┐       │
               │ ⑤ 纯规则自动  │ │ ③ Haiku  │ │ ④ Sonnet     │       │
               │ 唯一命中/跳过 │ │ 关键字+   │ │ 语义推理      │       │
               │ 暂定金额项    │ │ 量纲敏感  │ │ 可拒绝 · 贵   │       │
               │ (不走 LLM)   │ │ 便宜      │ │              │       │
               └──────┬───────┘ └────┬─────┘ └──────┬───────┘       │
                      │               └──────┬───────┘               │
                      │                      ▼                       │
                      │         ┌──────────────────────────┐         │
                      │         │ ⑥ 跨模型一致性比对         │         │
                      │         │  一致 → 自动通过           │         │
                      │         │  不一致 → 冲突池           │         │
                      │         └──────────┬───────────────┘         │
                      │                    │                         │
                      │                    ▼                         │
                      │         ┌──────────────────────────┐         │
                      │         │ ⑦ Opus 仲裁（限量 · 只仲裁）│◄────────┘
                      │         │ 优先高风险/金额异常项       │
                      │         │ 产出最终判定 + 理由        │
                      │         └──────────┬───────────────┘
                      │                    │
                      ▼                    ▼
                 ┌───────────────────────────────────────────────┐
                 │  ⑧ 回写分类结果列 + 变更标记 + 分类报告          │
                 │  未决项 / 零候选 → 人工确认队列                  │
                 │  人工确认结果 → 沉淀回 ① 规则库/黄金集（下次复用）  │
                 └──────────────────────┬────────────────────────┘
                                        ▼
                 ┌───────────────────────────────────────────────┐
                 │  ⑨ 闭词表校验（纯代码）                         │
                 │  Category/Subcategory/Element 必须在定额库内     │
                 │  越界值 fuzzy 修正 → validation_errors.json     │
                 └──────────────────────┬────────────────────────┘
                                        ▼
                 ┌───────────────────────────────────────────────┐
                 │  ⑩ 交给 pk-boq-workbench 装配 + 交付检查        │
                 │  分类值随工作台一次写入 → 透视表刷新即有内容      │
                 └───────────────────────────────────────────────┘
```

①-⑧ 是分类流水线，全程只读原清单，产物是 `classification.json`；⑨⑩ 是交付收尾。

**工作台装配排在分类之后**，由 `pk-boq-workbench` 技能负责，不在本技能范围内 —— 透视表按 Discipline / SortKey / Category 分组汇总，分类列空着的话刷出来只有 `(空白)`；拿到分类结果再装配，一次成型。分类停在 ⑧ 只是把值算出来了，没有经过闭词表门禁。

## 各阶段职责

| 阶段 | 模型/工具 | 职责 | 交接物 | 触发条件 |
|------|-----------|------|--------|----------|
| ① 离线校准 | Opus | 定归一化规则、检索策略、分类阈值、路由表、prompt 模板；用黄金集校准 | 规则库 `classification_rules.json` + 术语表 `taxonomy_v1.json` | 一次性 / 每次规则更新 |
| ② 判定路由 | 纯代码 `route_boq.py` | 跳过项/暂定金额/唯一命中判定；闭词表候选检索；按候选分部数分档 | `route_result.json` | 每次运行，0 token |
| ③ 轻量分类 | Haiku | 2-3 候选分部内做关键字+量纲敏感选择 | 分类结果 | LOW 档 |
| ④ 语义分类 | Sonnet | 4+ 多候选/近似项做语义推理，可拒绝 | 分类结果 | HIGH 档 |
| ⑤ 纯规则自动 | 代码 | 唯一命中/跳过项/暂定金额项直接定案，不走 LLM | 定案条目进 classification.json | UNIQUE/SKIP/SUM |
| ⑥ 一致性比对 | 代码 | ③④ 输出跨模型比对（真独立信号）；一致自动通过，不一致进冲突池 | 通过项 / 冲突池 | ③④ 有输出 |
| ⑦ 仲裁 | Opus（限量） | 只仲裁冲突 + 零候选异常；优先高风险/金额异常项 | 最终判定 + 理由 | 冲突池 / ZERO |
| ⑧ 汇总 | Python + 人工 | 各档结果合并进 classification.json 的 items；未决项留在 pending | classification.json | 全部 |
| ⑨ 校验 | 代码 `validate_classification.py` | 闭词表门禁：越界值 fuzzy match 修正，不合法值全部记账 | 修正后 xlsx + `validation_errors.json` | 每次运行 |
| ⑩ 交付检查 | 代码 `pk-boq-workbench/scripts/verify_workbook.py` | 工作台结构 / 公式脚手架 / 分类填充率逐项 PASS-FAIL，退出码非 0 即未完工 | 检查报告（原样贴出） | 每次运行 |

## 与脚本的对应

| 阶段 | 脚本 | 位置 |
|------|------|------|
| ⑩ 工作台装配 | `pk-boq-workbench` 技能 | 另一个技能，不在本目录（`build_workbook.py --classification` + 模板都在那边） |
| ② 判定路由 | `route_boq.py` | `scripts/`（主入口：`python route_boq.py -i BOQ.xlsx`） |
| ② 检索模块 | `candidate_retrieval.py` | `scripts/`（route_boq 调用；含 Dept2 强信号路由表、英文→中文术语展开、五册 SQLite 检索） |
| ③④⑦ prompt 构建 | `build_classification_prompt.py` | `scripts/`（注入闭词表候选，LLM 只能从中选） |
| ⑤ 规则定案 | `classify_boq_engine.py` + `run_classify_pipeline.py` | `scripts/`（UNIQUE/PATTERN/SUM/PRELIM 直接定案进 classification.json，含 SortKey + Discipline 拆分） |
| ⑧ 批量修正 | `batch_correct.py` | `scripts/`（按 desc_regex 批改，人工/LLM 审核后回写） |
| ⑨ 闭词表校验 | `validate_classification.py` | `scripts/`（门禁 + fuzzy 修正 + `validation_errors.json`） |
| ① 规则库 | `classification_rules.json` | `references/`（技能级通用：term_map/暂列金/skip_patterns/routing/patterns/闭词表来源/偏移） |
| ① 术语表 | `taxonomy_v1.json` | `references/`（en_zh_seed_glossary 英文→中文关键词展开） |
| ① 定额库 schema | `quota_db_schema.md` | `references/`（5 册 L1/L2/L3 闭词表来源） |

阶段 ③④⑦ 没有固定脚本 —— 由 Claude 读 `route_result.json` 按 LOW/HIGH/ZERO 分档，用 `build_classification_prompt.py` 构建 prompt 后自行调用对应模型，结果按同样字段合并进 classification.json 的 items。

## 成本控制要点

- 第 2 步全程 0 token：判定 + 检索 + 分档都是代码。
- 唯一命中 / 跳过项 / 暂定金额项直接定案，不经过任何 LLM。
- 仅 LOW 调 Haiku、HIGH 调 Sonnet，按候选数选便宜/贵的模型。
- Opus 限量：只仲裁冲突池和零候选异常，不做常规分类。
- 人工确认结果沉淀回 ① 规则库/黄金集，下次运行自动复用，越用越准。

## 可复用引擎

流水线里三个纯代码组件是配置驱动、跨项目复用的，正常迭代只更新规则/配置，不改代码：

| 引擎 | 脚本 | 驱动方式 |
|------|------|----------|
| 脚本路由 | `route_boq.py` + `candidate_retrieval.py` | 更新 `classification_rules.json`（patterns/routing/mapping/skip_patterns）和 `taxonomy_v1.json` |
| 闭词表校验 | `validate_classification.py` | 更新 `UNIVERSAL_SUBCATEGORIES` 集合；定额库 SQLite 更新后自动生效 |
| SortKey + Discipline 拆分 | `classify_boq_engine.py` 的 `_finalize_item()` | SortKey 取 `category_code`；A 册按 division 编号区间拆分（A.01-A.19、A.30-A.33 → Civil，A.20-A.29 → Decoration） |

三者都不依赖 LLM，配置改完即时生效，无需重跑整条流程。
