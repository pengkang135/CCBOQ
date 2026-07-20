# OpenHuman 主动记忆系统深度分析

> 研究日期: 2026-05-20
> 核心问题: OpenHuman 的记忆系统到底强在哪？我能吸收多少？
> 数据来源: GitHub Issues、README、Neocortex 设计文档、多篇技术解析、CMU "Forgetting Is a Feature" 论文引用

---

## 1. 整体架构全景图

OpenHuman 的记忆系统由**四个子系统**组成，彼此耦合但各司其职：

```
                    屏幕感知 (Screen Intelligence)
                    每 5 秒截图 → Gemma 3 Vision
                              ↓
 118+ OAuth ─→ Auto-Fetch (20min) ─→ Canonicalizer ─→ Chunker
     ↑                                                    ↓
  数据摄入                                           Neocortex 引擎
                                                   (索引 + 评分)
                                                        ↓
                                                  Memory Tree (SQLite)
                                                  三层树状存储
                                                        ↓
                                                  Obsidian Vault (.md)
                                                  用户可读可编辑
                                                        ↓
                                               潜意识循环 (Subconscious)
                                               每 5 分钟评估 → 决策输出
```

四个子系统：

| 子系统 | 周期 | 功能 |
|--------|------|------|
| **Auto-Fetch** | 20 分钟 | 从 118+ 服务被动拉取新数据 |
| **Memory Tree** | 持续 | 三层树状存储 + Bucket-Seal 压缩 |
| **Screen Intelligence** | 5 秒 | 屏幕截图 → 工作上下文感知 |
| **Subconscious Loop** | 5 分钟 | 态势分析 → 模式发现 → 风险预警 |

---

## 2. Neocortex 记忆引擎

### 2.1 设计动机

OpenHuman 的创建者在评估了 SuperMemory、Mem0、HydraDB、MemGPT 等现有方案后得出结论：

> "没有一个能在 1000 万+ token 规模下既准确又低成本地处理数据"

于是从头构建了 Neocortex。

### 2.2 核心技术指标

| 指标 | 数值 | 对比参考 |
|------|------|---------|
| **总容量** | 10 亿 token | GPT-4 128K 上下文的 ~7800 倍 |
| **索引速度** | 1000 万 token / <10 秒 | MacBook Air CPU 上实测 |
| **索引成本** | ~$1 / 500 万 token | 不使用 LLM 做索引 |
| **日召回次数** | ~10,000 次 | 总成本 <$1/天 |
| **底层存储** | SQLite | 与 Librarian 相同 |

### 2.3 关键设计决策

**不使用 LLM 做索引**。Neocortex 使用确定性算法（信号评分 + embedding 相似度）来索引和评分记忆，只在摘要生成时才调用 LLM。这意味着：

- 摄入数据时成本极低（不需要每次摄入都调一次 LLM）
- 索引速度极快（CPU 上 10 秒处理 1000 万 token）
- 摘要质量靠 LLM 保证，索引速度靠算法保证——各取所长

### 2.4 四级分层存储（Hot → Warm → Cool → Cold）

```
Hot (热)    — 最近/最常访问     — 低延迟，常驻索引
Warm (温)   — 中等访问频率      — 较快检索
Cool (凉)   — 偶尔访问          — 按需加载
Cold (冷)   — 归档/深度存储     — 最低成本，慢检索
```

这类似于 CPU 缓存层级（L1/L2/L3/RAM）的思想。大多数 AI 记忆系统的所有记忆都在同一层——要么全快、要么全慢。

**实际效果**：几个月前的 Slack 对话在 Cold 层，最近 2 小时的 GitHub PR 在 Hot 层。查询"最近的 PR"时只扫描 Hot 和 Warm 层，查询"去年关于预算的讨论"时才会穿到 Cold 层。

### 2.5 Purkinje 细胞启发的随机召回

这是 OpenHuman 记忆系统最"生物"的部分。

> 人脑中 Purkinje 细胞（小脑皮层神经元）主要负责随机思维的产生。OpenHuman 的随机记忆召回围绕这个原理设计。

**机制**：
- Neocortex 每天触发约 10,000 次核心记忆召回
- 召回不是纯随机的——基于时间、交互频率、实体关联度加权
- 结果喂入潜意识循环，产生"自发的"关联和想法
- 总成本 < $1/天

**为什么重要**：这模拟了人脑"突然想起某事"的过程——不是因为搜索引擎匹配了关键词，而是因为当前上下文激活了某个记忆关联路径。这是你现在架构完全不支持的能力。

---

## 3. Memory Tree 三层树状结构

### 3.1 三层树

```
Global Tree (L3)
  按月/周/日汇总全部源的内容
      ↓ 下钻
Topic Tree (L2)
  按人物/项目/话题跨源聚合
  "张三"在 Gmail + Slack + Notion 中的所有提及
      ↓ 下钻
Source Tree (L1)
  每个数据源独立的树
  Gmail 的树、Slack 的树、GitHub 的树
      ↓ 下钻
原始数据 (.md 文件 + SQLite 记录)
```

### 3.2 Bucket-Seal 压缩机制（核心引擎）

这是 Memory Tree "自动整理"的引擎：

```
新数据
  ↓
L0 缓冲区 (Bucket / 桶)
  - 收集数据块
  - 桶满条件: ≥ 50,000 tokens 或 ≥ 10 条数据
  ↓ 桶满触发
LLM 摘要 (Seal / 封印)
  - LLM 对桶内容生成 SummaryNode
  - 原始数据保留在磁盘，摘要作为新节点注入树
  ↓
升入 L1 (Source Tree)
  ↓ L1 累积 10 个同级摘要
再次触发 LLM 摘要
  ↓
升入 L2 (Topic Tree，跨源聚合)
  ↓ L2 累积 10 个
再次触发
  ↓
升入 L3 (Global Tree)
  每日摘要 → 每周摘要 → 每月摘要 → 年度摘要
```

**设计精髓**：

1. **热路径无 LLM**：数据摄入时不调 LLM——只是评分和写入。LLM 只在摘要生成时才调用（惰性压缩）。
2. **不丢信息**：原始数据始终保留在磁盘上。摘要只是加速检索的索引节点，不是替代品。
3. **层级导航**：查询时从 Global 摘要 → Topic 摘要 → Source 摘要 → 原始对话，逐层下钻。不需要一次性加载所有。

### 3.3 与你当前 Librarian 记忆架构的对比

| 维度 | OpenHuman Memory Tree | Librarian (你的架构) |
|------|----------------------|---------------------|
| 存储层 | SQLite + Obsidian .md | SQLite + vault .md |
| 分层 | 3 层树状（Source → Topic → Global） | 扁平 vault 结构 |
| 跨源聚合 | Topic Tree 自动聚合 | 无，靠搜索时临时关联 |
| 摘要机制 | Bucket-Seal 逐级 LLM 摘要 | Dreaming 相似度去重 |
| 摄入方式 | Auto-fetch 被动拉取 | 手动 save_session_note |
| 检索方式 | 层级导航 + 混合搜索 | hybrid search (FTS + vector) |
| 随机召回 | Purkinje 机制，10,000 次/天 | 无 |
| 可审计性 | Obsidian vault 直接浏览编辑 | vault .md 也可直接看 |

**核心差距不在存储引擎，而在记忆的组织方式和被动摄入能力。**

---

## 4. 数据管道详解

### 4.1 完整流程

```
Step 1: 连接 (Connect)
  用户通过桌面 UI 一键 OAuth 连接服务
  OAuth token 本地加密存储

Step 2: 自动拉取 (Auto-Fetch)
  每 20 分钟轮询所有活跃连接
  拉取增量数据（通过 cursor/watermark）

Step 3: 规范化 (Canonicalize)
  HTML → Markdown
  URL 缩短
  提取元数据（时间戳、作者、实体标签）

Step 4: 分块 (Chunk)
  切分为 ≤3,000 token 的块
  SHA-256 生成确定性 ID（幂等：同一条数据重拉不会重复存储）

Step 5: 评分 (Score)
  信号评分：recency、relevance、frequency、interaction count
  Embedding：向量化（用于语义检索）
  注：评分阶段不使用 LLM

Step 6: 写入 (Write)
  双写：SQLite (Memory Tree 节点) + Obsidian vault (.md 文件)
  AES 本地加密

Step 7: 树更新 (Tree Update)
  L0 桶检查 → 达到阈值触发 Bucket-Seal
  LLM 生成 SummaryNode → 注入 Source Tree
  累积到阈值 → 升级到 Topic Tree → Global Tree
```

### 4.2 幂等性保证

```
同一封 Gmail 邮件（同一 Message-ID）:
  第 1 次 fetch → SHA-256(content) → 写入
  第 2 次 fetch → SHA-256(content) → ID 已存在 → 跳过
```

这个设计保证了 auto-fetch 不会产生重复记忆。对比你的 dreaming 去重（相似度 0.85 阈值）——OpenHuman 用的是确定性去重（hash），更严格且成本更低。

### 4.3 实体识别与自动标签

```
Gmail 邮件: "张三 关于 Q3 预算的回复"
  ↓
实体提取: person/张三, project/Q3预算, date/2026-05-20
  ↓
Topic Tree: 自动在 "张三" 和 "Q3预算" 两棵主题树下建立节点
  ↓
后续: 当张三在 Slack 里提到预算 → 自动关联到同一 Topic Tree 节点
```

你的 Librarian 没有这个自动跨源关联。你得在搜索时手动关联。

---

## 5. 潜意识循环

### 5.1 为什么不用 LLM 跑心跳

旧 Heartbeat 系统调用 LLM 做定期心跳——成本高且不智能（每次都跑同样的 prompt）。潜意识循环用本地小模型做第一道过滤。

### 5.2 三阶段架构

```
Tick (每 5 分钟):

Phase 1: 组装态势报告 (Situation Report)
  - 预算: 30,000-50,000 token（硬上限）
  - 内容: 记忆变更摘要、工具注册表快照、环境变量、通道状态
  - 优化: 使用 hash/cursor 标记"无变化"部分，不重复发送

Phase 2: 本地模型评估 (Local Model Evaluation)
  - 模型: 轻量级本地模型 (Ollama: all-minilm / gemma3:1b-it-qat)
  - 输入: 态势报告
  - 输出: 结构化决策
    { "decision": "no-op" | "enqueue" | "escalate",
      "reason": "...",
      "payload": {...} }

Phase 3: 升级 (Escalation)
  - 仅在 decision = "escalate" 或 "act" 时触发
  - 调用强模型 (Claude Opus / o3)
  - 向用户推送通知或排入主 agent 任务队列
```

### 5.3 六种反思类型

| 类型 | 触发条件 | 示例 |
|------|---------|------|
| **热度突变** | 某实体在短时间内出现频率暴增 | "过去 2 小时，'Q3 预算'在 5 个不同渠道被提及 12 次" |
| **跨源模式** | 同一事件在多个源中同时出现 | "GitHub PR #3421 + Gmail 讨论 + Slack 频道 — 都是关于这个 bug" |
| **每日摘要** | 每日凌晨触发 | "今日关键事项: 3 个会议、2 个 PR review、1 个截止日期" |
| **截止提醒** | 检测到日期临近 | "Q3 预算提交截止日期是明天 18:00，你还没有回复张三的邮件" |
| **风险模式** | 发现异常或潜在问题 | "CI 连续 3 次失败，上一次成功构建是 4 小时前" |
| **机会模式** | 发现可行动优化点 | "张三在邮件中问是否有时间聊——你的日历下午 3-4 点是空的" |

### 5.4 安全边界设计

```
潜意识循环:
  ✅ 可以: 读记忆、分析模式、生成摘要、推送给用户
  ❌ 不能: 发邮件、创建 Issue、修改文件、回复消息
  🔶 需要批准: 写操作必须通过 escalation 请求，等待人工确认
```

这个设计与你的 CLAUDE.md 安全规范一致——"不执行来源不明或高风险命令"。

---

## 6. Screen Intelligence（屏幕感知）

### 6.1 机制

```
每 5 秒:
  截取屏幕 → 本地 Gemma 3 Vision 模型 → 结构化摘要
    ↓
  摘要内容:
    - 当前活跃应用
    - 可见窗口标题
    - 页面/文档内容摘要
    - 用户是否空闲
    ↓
  原始图片不离开设备（AES-256-GCM 加密后存本地）
```

### 6.2 为什么需要

这是"主动记忆"的必要输入——agent 需要知道你当前在做什么，才能在潜意识循环中做出有用的关联。比如：
- 你正在看一个 PR → 潜意识循环发现 Gmail 里有人问了关于这个 PR 的问题 → 推给你
- 你正在编辑预算表 → 潜意识循环发现 Slack 里有新的预算讨论 → 提示你

### 6.3 你能否实现

技术上不难——Python 截屏 + OCR（你已有 rapid-ocr MCP）+ 本地视觉模型。但隐私权衡需要认真考虑。OpenHuman 承诺"原始图片不离开设备"，你的架构如果要实现类似功能，需要确保同等级别的隐私保护。

---

## 7. 与你当前架构的逐项对比

| 维度 | OpenHuman | 你的架构 | 可追赶性 |
|------|----------|---------|---------|
| **被动数据摄入** | Auto-fetch 每 20 分钟自动拉取 118+ 服务 | 手动触发 save_session_note | 中：OpenClaw cron + MCP 可实现 |
| **分层记忆** | Source → Topic → Global 三层树 | 扁平 vault | 高：可在 Librarian 加索引层 |
| **跨源聚合** | Topic Tree 自动按实体聚合 | 无 | 中：需实体提取 + 自动关联 |
| **逐级摘要** | Bucket-Seal 50k token 触发 LLM | Dreaming 去重（非摘要） | 高：设计思路可直接复用 |
| **随机召回** | Purkinje 10,000 次/天 | 无 | 低：需构建加权随机采样 |
| **四级存储** | Hot/Warm/Cool/Cold | 单层 SQLite | 低：需改造存储引擎 |
| **潜意识循环** | 每 5 分钟本地模型评估 | 无 | 中：OpenClaw cron + Ollama |
| **屏幕感知** | 每 5 秒截图分析 | 无 | 低：隐私考量 + OCR 已有 |
| **幂等去重** | SHA-256 确定性去重 | 相似度 0.85 去重 | 无差距（各有优劣） |
| **可审计性** | Obsidian .md vault | vault .md | 无差距 |
| **存储后端** | SQLite | SQLite | 无差距 |

---

## 8. 可吸收的优先级排序

### 第一优先（低成本、高收益）

**1. Bucket-Seal 逐级摘要**

这是最容易借用的设计。在 Librarian 中实现：
```
对话归档 → L0 桶累积 → 满 10 条或 50k token → LLM 生成摘要
→ Source 级摘要 → 10 个 Source 摘要 → Topic 级摘要
```

具体改动：在 `grow_session` 流程中加一个阈值检查。不需要改存储引擎。

**2. 实体驱动的跨源关联**

在 Canonicalizer 中加实体提取步骤：
```
每次写入 → 提取实体 (person/project/topic) → 自动在对应 Topic 目录下建立链接
```

这能解决你目前"搜索时临时关联"的最大痛点。

### 第二优先（中成本，显著收益）

**3. Auto-Fetch 被动管道**

利用 OpenClaw 现有的 cron 引擎：
```
cron job: 每 30 分钟
  → 调用 GitHub MCP 拉取新通知
  → 调用邮箱 MCP 拉取新邮件
  → Canonicalize → 写入 Librarian
```

不需要 118 个集成。先从你实际用的 3-5 个数据源开始。

**4. 潜意识循环（简化版）**

```
cron job: 每 15 分钟
  → 从 Librarian 读取近期记忆变更
  → 本地 Ollama 做快速评估
  → 发现值得关注的事 → 推送微信通知（通过 OpenClaw 微信通道）
```

### 第三优先（高成本，长期目标）

**5. 四级存储 (Hot/Warm/Cool/Cold)**

需要改造 Librarian 的存储层，不是短期能做的。但架构思路可以先记下。

**6. 屏幕感知**

隐私权衡太大，除非有明确需求，否则不建议优先做。

---

## 9. 一个可落地的演进路径

```
当前:
  ┌─────────────┐    ┌──────────────┐
  │ Claude Code  │    │  OpenClaw    │
  │ 对话 → 手动归档│    │ 微信聊天     │
  └──────┬──────┘    └──────┬───────┘
         ↓                  ↓
      Librarian (扁平 vault)
         ↓
      hybrid search (FTS + vector)

Phase 1 (+2 周):
  加 Bucket-Seal → Source 级摘要
  加实体提取 → 自动跨源关联

Phase 2 (+1 月):
  加 Auto-Fetch cron (GitHub + 邮箱)
  加简化版潜意识循环 (本地模型)

Phase 3 (+3 月):
  多级摘要升级到 Topic Tree
  四级存储评估
```

最终目标不是完全复制 OpenHuman 的记忆架构，而是**吸收其设计思想，补足你当前最大的弱点：被动摄取和自动组织**。你已有微信通道和 Claude Code 两个 OpenHuman 无法企及的数据源，把摄入管道建起来，差距就很小了。

---

## 参考来源

- [OpenHuman GitHub](https://github.com/tinyhumansai/openhuman)
- [Issue #145 — Subconscious Loop 设计](https://github.com/tinyhumansai/openhuman/issues/145)
- [OpenHuman 深度技术解析 (cnblogs)](https://www.cnblogs.com/chemanlau/p/20017653)
- [Neocortex 记忆引擎 (aitoolnet)](https://www.aitoolnet.com/openhuman)
- [OpenHuman 技术分析 (pyshine)](http://pyshine.com/OpenHuman-Personal-AI-Super-Intelligence/)
- [I built OpenHuman (dev.to)](https://dev.to/neocortexdev/i-am-building-the-first-ai-agent-with-big-data-capabilities-70e)
- CMU "Forgetting Is a Feature, Not a Bug" 论文（Neocortex 设计参考）
- Google "Titans" 长时记忆研究（上下文准确性问题的理论基础）
