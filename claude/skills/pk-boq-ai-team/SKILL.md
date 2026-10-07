---
name: pk-boq-ai-team
description: "PK BOQ 大表 AI 团队协作统一技能（合并原 multi-agent-collab 速查手册 + team_pipeline + pk-boq-strategy 数据前端）。第0步数据前端（fastexcel读→区域聚合→分片，token省60-100x）；模式A：6种通用拓扑选型（星型/流水线/采集器/网状/链式/树形）；模式B：8阶段分层流水线（Opus校准→脚本路由0token→按档执行Haiku/Sonnet/纯规则→跨模型比对→Opus限量仲裁→回写+dry-run预检）。套价、套定额、分类、分级及任何需要多AI角色协作的大表任务都用得上。触发词：多agent、团队协作、拓扑、星型、流水线、树形、分工、按档分流、Opus校准、仲裁、分层、聚合、大表处理、BOQ策略。"
license: Proprietary. LICENSE.txt has complete terms
---

# PK BOQ — AI 团队协作统一技能

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


统一管理两种协作能力：**通用拓扑库**（6 种组织架构按决策表选型）+ **8 阶段分层流水线**（大表 + 规则可脚本化 + LLM 语义判断任务的工程化深化，源自 `pk-boq-classify` 的 team_pipeline，是"流水线多轮 + 星型"的深化形态）。

## 什么时候用

任何需要"多个 AI 角色协作完成任务"的场景：

- **大表处理（>50 行）**：分类 / 套价 / 套定额 / 分级
- **同一对象多视角审视**：代码审查（安全/性能/可维护）、竞品分析、多语言翻译审校
- **分阶段流水线任务**：下游依赖上游产出（调研→合成→把关）
- **大规模并行（8+ agent）**：单 Lead 直接管理所有人不可行

## 第 0 步：数据前端（原 pk-boq-strategy）

进入任何模式前，先按数据前端处理大表：**fastexcel 读 → sheetwise 压缩 → 区域聚合 → 分片**，token 节省 60-100x。铁律：读用 fastexcel、先聚合后 LLM、LLM 只输出规则不碰 Excel、无层级不分类。复杂度分级：<50 行直接处理；50-5000 行聚合分片；>500 行走 `pk-boq-json-workflow`。完整文档见 [references/data-front-end.md](references/data-front-end.md)。

```
第 0 步 数据前端:  fastexcel读 → 区域聚合(3000行→50组) → 分片
     ↓ 压缩后的聚合模式
8 阶段流水线:     ① Opus校准 → ② 路由 → ③④⑤ 执行 → ⑥ 比对 → ⑦ 仲裁 → ⑧ 回写
```

**静态源缓存**：定额库/闭词表等固定来源（如企业定额库清单框架）几乎不变，提前聚合一次存缓存 JSON，任务时直接加载，不重复聚合（详见 data-front-end.md 静态源缓存节）。

## 两种模式

### 模式 A：拓扑选型（通用）

从 6 种拓扑中按任务特征选型，按选定的架构组织 agent。见 [references/topology-library.md](references/topology-library.md)。

| 拓扑 | 信息流 | 核心价值 | 适用 |
|---|---|---|---|
| 星型单轮 | 无通信，并行 | 多视角独立 | 同对象多视角审视 |
| 流水线多轮 | 无通信，阶段串行 | 工序化质量控制 | 分阶段、每阶段要综合 |
| 数据采集器 | 无通信，工具化 | 信息搜集提速 | 纯搜集，自己判断 |
| 网状辩论 | 有通信，全连接 | 观点碰撞 | 无标准答案的正反交锋 |
| 链式接力 | 有通信，单向链 | 递增精炼 | 一对一递进加工 |
| 树形分层 | 有通信，树状 | 规模扩展 | 8+ agent 管不过来 |

### 模式 B：8 阶段分层流水线（深化）

当任务同时满足 **规则可脚本化 + 需要 LLM 语义判断 + 大表**，直接走 8 阶段流水线：

```
① 离线校准（Opus·一次性）   定规则/阈值/路由/prompt模板/黄金集
② 脚本路由（纯代码·0 token）  判定(skip/暂定/唯一) → 检索候选 → 按候选数分档
③ 轻量执行（Haiku）    ← LOW 档 2-3 候选
④ 语义执行（Sonnet）   ← HIGH 档 4+ 候选/近似
⑤ 纯规则自动（代码）   ← UNIQUE/SKIP 直接写回，不走 LLM
⑥ 跨模型一致性比对     ③④ 输出比对：一致→通过，不一致→冲突池
⑦ Opus 仲裁（限量）   只仲裁冲突池/零候选/高风险项
⑧ 回写+报告+人工确认  未决项→人工队列 → 沉淀回①
```

这是"流水线多轮 + 阶段内星型"的工程化深化，各阶段职责、脚本对应、成本控制见 [references/layered-pipeline.md](references/layered-pipeline.md)。

## 决策表：模式 A 还是 B

| 任务特征 | 模式 |
|---|---|
| 同一件事需要多个独立视角 | A → 星型单轮 |
| 分几个阶段，后一步依赖前一步 | A → 流水线多轮 / 链式接力 |
| 只需要收集信息，自己判断 | A → 数据采集器 |
| 需要不同观点正面交锋 | A → 网状辩论 |
| 活太多，一个人管不过来 | A → 树形分层 |
| **大表 + 规则可脚本化 + LLM 语义判断** | **B → 8 阶段流水线** |

B 模式与 A 模式不冲突：B 是"流水线多轮 + 阶段内星型"的预设实现，执行时内部每个阶段可能再嵌套星型（如 ③ 执行层 Haiku×N 并行）。

## 核心原则（两模式共用）

> **最大教训**：不同环节必须由不同角色 + 不同模型把关——**设计者、执行者、审核者、决策者**。
> 换模型 = 独立信号，防止 **AI 自己说服自己**（同模型自我确认偏差：V6 曾 Matcher 与 Auditor 同用
> Sonnet，Rinsing Spray→Spray Paint 的误配在校验层同样通过，说明同一个脑子复核自己拦不住自己）。
> 执行 Haiku 的误判必须由 Sonnet 独立信号拦截，决策 Opus 只做终裁，绝不与执行者共用同一模型走完整流程。

1. **角色分工把关**：设计者（Opus·定规则）→ 执行者（Haiku·跑量）→ 审核者（Sonnet·复核）→ 决策者（Opus·终裁）。四个角色盯不同环节，互相独立，互不补台。
2. **换模型 = 独立信号**：执行 / 校验 / 决策用不同模型（Haiku/Sonnet/Opus），防止错误推理在同模型内传递。
3. **0 token 优先**：脚本能判的绝不给 LLM。判定 + 检索 + 分档全代码。
4. **贵模型限量**：Opus 只仲裁冲突池 / 零候选 / 高风险，不做常规执行。
5. **按候选数 / 难度选模型**：唯一命中直接写回，2-3 候选 Haiku，4+ 候选 / 近似 Sonnet，零候选 / 冲突 Opus。
6. **人工确认沉淀回规则库**：未决项由人兜底，结果写回① 规则库 / 黄金集，下次自动复用，越用越准。
7. **⑧ 写回前 dry-run 预检**：写盘前出一份行级覆盖率报表 + 闭词表校验，断层堵在写盘前（ZOO 分类 B 册 903 行 unmapped 教训），不通过就阻止写回。
8. **token 预算切 slice + ① Opus 设计 sub-agent 最小上下文**：按 token 预算切（不按行数）；**sub-agent 不拿完整技能上下文**，只拿 ① Opus 预先裁剪的最小执行包（闭词表/候选池 + 行格式 + 输出约束 + 本批数据），完整方法论留在规则库/路由脚本层，不逐份拷贝给每个 agent。⑥⑦ 只在分歧/低置信时触发（详见 layered-pipeline.md 成本控制）。

## 四场景映射（已固化的场景技能）

| 场景 | 场景技能 | ① 校准产物 | ② 路由脚本 | ③④ 执行 | ⑥⑦ 校验仲裁 |
|---|---|---|---|---|---|
| 分类 | pk-boq-classify | classification_rules.json + taxonomy_v1 | route_boq.py | Haiku 轻量 / Sonnet 语义 | 跨模型比对 + Opus 仲裁 |
| 套价(DB) | pk-boq-db-match | 术语表 + 家族标签 + domain map + 分档阈值 + 红线规则 | route_price.py (结构探针+规则直定+候选分档) | Haiku×N 并行 + Sonnet 精修 | 跨模型比对 + Auditor 补搜 + Opus 仲裁 |
| 套定额 | pk-norms-match | 章节映射 + 匹配阈值 | 定额池构建 + 分档 | Haiku/Sonnet 按批 | 抽样审核 + Opus 仲裁 |
| 分级 | pk-boq-hierarchy | 层级规则 + Phase 1 硬规则 | apply_hierarchy 判定 | 脚本机械判定 + 三 Agent 语义审查（Claude Code Agent 工具，非外部API） | 三 Agent 交叉比对 + 主上下文仲裁 |

> **分级场景已从「几乎全规则」升级为「脚本+Agent 审查」**：脚本 Phase 1 硬规则（含「为方便」→封顶 L3 等语义噪声过滤）→ Phase 2-3 结构判定 → `--export-review` 导出歧义行 → 三 Agent 独立审查 → 主上下文仲裁回写。详见 `pk-boq-hierarchy/SKILL.md`。

详细映射见 [references/scenario-mapping.md](references/scenario-mapping.md)。

## 与其他技能的关系

| 技能 | 关系 |
|---|---|
| `pk-boq-classify` | B 模式首个落地场景，team_pipeline 即 8 阶段原版 |
| `pk-boq-db-match` | 四角色 + 模型分层（执行 Haiku/校验 Sonnet/决策 Opus），B 模式套价变体 |
| `pk-norms-match` | 套定额场景，已升级为 8 阶段范式 |
| `pk-boq-hierarchy` | 分级场景，脚本机械判定 + 三 Agent 语义审查 + 主上下文仲裁 |
| `pk-boq-strategy` | 已并入本技能（数据前端，见 references/data-front-end.md）；完整大表策略见 `~/.claude/references/excel-layered-strategy.md` |
