# 数据前端（第 0 步 · 原 pk-boq-strategy）

> 数据怎么读、怎么压缩，再交给 8 阶段流水线。**完整文档**：
> `~/.claude/references/excel-layered-strategy.md`（本页为元策略摘要，详细触发条件/API/公式探测见完整文档）。

## 铁律

1. **读用 fastexcel**（9-16x），写用 openpyxl。>500 行禁止 openpyxl 遍历读。
2. **先聚合，后 LLM**。3000 行按 Dept 压缩到 50 组，token 节省 60-100x。
3. **LLM 只输出规则**，Python 逐行回写。LLM 不碰 Excel 写入。
4. **无层级不分类**。先跑 `pk-boq-hierarchy` 建立 Dept1/2/3 上下文。
5. **不按区域逐条拆 Agent**。按 Dept1/Dept2 贪心均衡拆包，Agent 数由 token 预算约束（见 layered-pipeline.md 成本控制），杜绝"431 区域 = 431 Agent"的内存爆炸。

## 四阶段（数据层）

```
Stage 1: 结构探查  → fastexcel 抽样（<2s, 零 token）
Stage 2: 区域聚合  → 按 Dept1/2/3 压缩去重（3000行→50组, 零 token）
Stage 3: LLM 分析  → 每组提交聚合模式, 并行 Agent（<60s, ~5K token）
Stage 4: 批量回写  → Python 解析规则逐行写入（<10s, 零 token）
```

## 聚合格式

```
区域: 【土建工程】→《Frame》→{Reinforced Concrete Beams}
├── "40MPa reinforced concrete" (15次)
├── "DB 12" (6次)
└── "Formwork to beams" (4次)
```

150+ 行 → 3 条模式。聚合 JSON 给 LLM，不展开原始行。

## 复杂度分级与路由

| 规模 | 策略 | LLM | 工具 |
|------|------|-----|------|
| <500 行 | 直接处理 | 聚合模式 | 各技能直接执行 |
| 500-5000 行 | 区域聚合 → 按 Dept1/Dept2 分片 → 按 token 预算限 Agent 数 | 聚合模式 | 本技能 + 各技能 |
| >5000 行 | 分片 JSONL 工作流 | 聚合+分片 | → `pk-boq-json-workflow` |

> `pk-boq-json-workflow` 是本策略在 >5000 行时的具体实现工具，不做独立决策。

## 各操作映射

| 操作 | 聚合维度 | LLM 输出 |
|------|---------|---------|
| classify | Dept1/2/3 | Discipline, Category, Subcategory, Material, Spec |
| hierarchy | G 列 + 单位/数量 | L1/L2/L3/L4 |
| norms-match | Dept + 描述 | 定额编号, 匹配度 |
| check | Dept + 描述 | 问题类型, 严重度 |

## 反模式（触发即中止）

- openpyxl 遍历 >500 行读取
- 原始行逐条发给 LLM
- 无层级直接分类
- 不聚合就并行
- LLM 直接改 Excel
- 用关键词/打分算法替代 LLM 做语义判断（Jaccard/编辑距离/token 重叠在语义层不可靠：`地砖` 和 `墙砖` token 高度重叠但业务完全不同；打分算法只能粗筛缩小候选范围，最终决策必须走 LLM）

## 静态源缓存（固定来源不重复聚合）

定额库（Norms-AI SQLite）、闭词表（`taxonomy_v1.json` / `classification_rules.json`）等**固定来源**——尤其企业定额库的**清单框架部分**（章节结构/闭词表）几乎不会变——在首次任务时聚合/导出一次，存缓存 JSON（如 `quota_framework_cache.json`），后续分类/套定额任务直接加载缓存，不重复查库聚合。

- 分类（pk-boq-classify）：定额库 4 册闭词表 → 缓存
- 套定额（pk-norms-match）：章节映射 + 定额池 → 缓存
- 失效时机：定额库版本/章节结构变更时才重新生成；任务前比对源库修改时间与缓存时间，超期才重建

```
首次: 定额库 → 章节/闭词表聚合 → 缓存 JSON（一次性）
后续: 直接加载缓存 → ② 路由 → ...（0 token，秒级）
```

## 与 8 阶段流水线的衔接

数据前端是 8 阶段流水线（layered-pipeline.md）之前的**第 0 步**：

```
第 0 步 数据前端（本页）：fastexcel 读 → sheetwise 压缩 → 区域聚合 → 分片
     ↓ 压缩后的聚合模式/分片
8 阶段 ① Opus 校准 → ② 路由 → ③④⑤ 执行 → ⑥ 比对 → ⑦ 仲裁 → ⑧ 回写
```

两者正交：数据前端管"数据怎么读/怎么压缩"（token 量），8 阶段管"agent 怎么协作"（多角色把关）。大表任务先走第 0 步压缩，再进 8 阶段。
