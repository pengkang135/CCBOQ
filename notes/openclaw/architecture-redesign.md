# Claude Code 记忆与进化架构

## 定位：和 Hermes 比，这套方案是什么

Hermes 的核心护城河是**拥有 agent loop**——控制迭代预算、中途注入 nudge、fork 后台审查 agent、多模型路由、子代理并行。这些都是靠"自己开车"才能做到的事。

这套方案**不拥有 agent loop**——Claude Code 已经是最好的执行引擎，不需要重造。方案的目标是给 Claude Code **补上它缺失的能力**：持久跨会话记忆、工具模式提炼、上下文自动注入、远程微信接入。

| | Hermes | 这套方案 |
|---|---|---|
| agent loop | 自己写（run_agent.py 10700行） | Claude Code 原生（不碰） |
| 工具 | 40+ Python native + MCP 外挂 | 16 MCP 服务器，MCP 是一等公民 |
| 工具调用质量 | 取决于路由到的模型 | Claude #1 benchmark，固定最高质量 |
| 执行后端 | local/docker/SSH/modal/daytona/singularity 六种 | local（MCP 在宿主机） |
| 模型 | 200+ 模型，按任务路由 | Claude only |
| 成本 | 便宜模型做简单操作，贵的做推理 | 全部走 Claude，无分层 |
| 记忆容量 | MEMORY.md ≤2200 字 + USER.md ≤1375 字 | 多 vault 无上限（FeynmanLibrary + knowledge + business-cards + BaiduSyncdisk） |
| 记忆检索 | FTS5 关键词 | FTS5 + 向量 + decay 衰减评分 |
| 记忆加工 | 直接写 .md | 完整 pipeline（fetch→canonicalize→chunk→write→bucket-seal→evaluate）+ LLM 提取 |
| 实时进化 | nudge engine（每10轮触发）+ 自动 skill 创建 | 无（没有 loop 就没有 mid-turn hook） |
| 离线进化 | 无跨会话分析 | pattern analyzer（编辑距离）+ skill extractor（LLM 批量） |
| 安全 | 五层防线 | Claude Code 内置权限模型 |
| 造价领域工具 | 无，需自定义 Python handler | rapid-ocr/pdf2md/pandoc/excel/wx-cli 已就绪 |

---

## 硬天花板——哪些事做不到

不是"暂时没实现"，是**架构上做不到**：

1. **不能中途介入**。Claude 在跑多轮工具调用时，外部系统完全旁观。不能在它踩坑时提醒"换个方法"，不能在它跑偏时说"你之前在 X 项目做过类似的事"。
2. **不能控制迭代预算**。无法限制"这个任务最多跑 20 步"，无法防止死循环耗尽 token。
3. **不能多模型路由**。全部走 Claude，无法把机械操作（读文件、写公式）交给便宜模型。
4. **不能 fork 子代理并行**。Claude Code 的 Agent 工具可以派子代理，但无共享预算、无结果合并、无代理间通信。
5. **进化是离线批量的**。技能提炼发生在会话结束后，不是实时的。无法做到"这次踩的坑，这次就学会"。

---

## 真优势——哪些事 Hermes 做不到

1. **MCP 生态即插即用**。rapid-ocr 识别中文扫描件、pdf2md 转换标书、pandoc 做格式互转、excel MCP 处理造价表——这些都是已有的、可直接用的 MCP 服务器。Hermes 需要自己写 Python handler。
2. **记忆深度和广度不在一个量级**。2200 字的 MEMORY.md 无法承载造价领域的知识积累（定额标准、历史项目数据、价格信息、法规变更）。多 vault 架构可以无限积累，decay scoring 自动淘汰陈旧信息，向量检索支持语义匹配。
3. **外部观察的独特视角**。因为不拥有 loop，所以能**跨会话、跨项目**看到模式。Hermes 的 memory 是 per-session 冻结的，看不出"你最近 20 次 Excel 操作都在修同一个公式错误"——外部 pattern analyzer 可以。
4. **Claude 模型质量是固定上限，但也是极高的下限**。不会出现工具调用失败因为"路由到了更便宜的模型"。

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                   Claude Code (不修改)                    │
│                                                         │
│  IDE 直接使用                CLI headless (微信/远程)      │
│  16 MCP 全能力              16 MCP 全能力                 │
│  交互式 agent loop           --bare -p stream-json       │
│       │                           │                     │
│       └───────────┬───────────────┘                     │
│                   │                                     │
│        会话 JSONL 写入 ~/.claude/projects/                │
│        包含完整 tool_use / tool_result 序列               │
└───────────────────┬─────────────────────────────────────┘
                    │ 事后读取（pipeline cron 30min）
                    ▼
┌─────────────────────────────────────────────────────────┐
│               Memory Pipeline (现有，扩展)                │
│                                                         │
│  fetch/claude_code.py (现有)                             │
│    → 扫描 ~/.claude/projects/*.jsonl                    │
│    → 提取用户问题 + 助手回复                              │
│                                                         │
│  fetch/tool_events.py (新增)                             │
│    → 从同一批 JSONL 提取 tool_use/tool_result            │
│    → 重建工具调用序列                                    │
│                                                         │
│  analyze/pattern_analyzer.py (新增)                      │
│    → 编辑距离聚类工具名序列                               │
│    → 检测高频模式 (≥3次出现)                              │
│    → 零 LLM 成本，纯算法                                 │
│                                                         │
│  skills/extractor.py (新增)                              │
│    → ≥5次出现的高置信模式 → 调 DeepSeek 生成技能描述       │
│    → 写入 librarian skills index (status: draft)         │
│    → 批量夜间执行，用便宜模型                             │
│                                                         │
│  evaluate/evaluator.py (扩展)                            │
│    → 评估时附带 tool context                             │
│    → LLM 理解"做了什么"而不仅仅是"说了什么"               │
│                                                         │
│  现有阶段不变:                                            │
│    canonicalize → chunk (SHA-256去重) → write (librarian) │
│    → bucket-seal (10条/5000token/60min) → evaluate (LLM) │
│                                                         │
│  现有 dreaming 不变:                                      │
│    light dreaming / deep dreaming / REM                  │
│    → 新增 skill_discovery reflector                     │
└───────────────────┬─────────────────────────────────────┘
                    │ 写入
                    ▼
┌─────────────────────────────────────────────────────────┐
│             Librarian (现有，不修改核心)                   │
│                                                         │
│  FTS5 + 向量检索    decay 衰减评分                         │
│  Vaults: FeynmanLibrary / knowledge / business-cards      │
│  新增: skills index (技能索引)                            │
└───────────────────┬─────────────────────────────────────┘
                    │ 查询
                    ▼
┌─────────────────────────────────────────────────────────┐
│          Context Injector (新增)                         │
│                                                         │
│  在 Claude Code 会话开始前:                               │
│    1. 从用户消息提取关键字（规则，无 LLM）                  │
│    2. 查 librarian: top 2 记忆 + top 1 技能              │
│    3. 硬上限 3 条、200 token                             │
│    4. 注入到 CLAUDE.md 上下文（IDE）或 system prompt（CLI）│
│                                                         │
│  注入格式:                                                │
│    ## Relevant Context                                  │
│    - 上次 Excel 差异分析模式: ...                         │
│    - 相关记忆: 湖南项目定额标准 ...                        │
│                                                         │
│  不是指令，是参考线索。Claude 自行判断是否使用。             │
└─────────────────────────────────────────────────────────┘
```

---

## 微信远程接入（无需 OpenClaw）

OpenClaw 已决定弃用。微信接入需要的是一个**薄桥接**，不是完整的 agent gateway：

```
微信消息 → 薄桥接 → Claude CLI --bare -p → 回复 → 微信
              ↑
         (不注入人设，不阉割MCP，不截断stream-json)
```

**薄桥接只做三件事**：
1. 收微信消息 → 提取文本 → 调 `claude.exe --bare -p --output-format stream-json --mcp-config <完整16服务器配置>`
2. 解析 stream-json → 文本块推微信（保持 block streaming 体验） + **旁路写 tool event JSONL**
3. 发送回复回微信

**不做的事**：不注入人设、不管理会话（让 Claude CLI `--resume` 自己管）、不截断工具事件、不覆盖 MCP 配置。

实现路径有两个选择：
- **方案 A**：从 `E:\Code\openclaw-fork` 提取 WeChat 通道代码（monitor.ts + process-message.ts + send.ts），剥离 gateway/server 层，改成独立 Python 服务调用 wx-cli 收发消息 + 调 Claude CLI
- **方案 B**：用 Python 从零写——wx-cli 已有微信消息读写能力，Python subprocess 调 Claude CLI，更轻量

方案 B 更干净，但需要处理微信消息的长轮询/连接管理。方案 A 复用了已验证的微信通道代码但带着 TypeScript + OpenClaw 的技术债。

---

## 记忆怎么解决

**已有基础（不需要新建）**：

```
Claude Code 会话结束
  → 会话 JSONL 自动写入 ~/.claude/projects/
  → pipeline cron (30min) 触发
  → fetch/claude_code.py 扫描新 JSONL
  → 提取 question + conclusion
  → canonicalize → chunk (SHA-256 去重) → write (librarian)
  → bucket-seal (达到阈值) → evaluate (DeepSeek LLM 提取记忆)
  → 记忆写入 librarian vaults

用户用 librarian.cmd text-search "湖南项目定额" 立即可查
```

**需要扩展的（新增）**：

1. **tool event 采集**——从同一批 JSONL 中提取 tool_use/tool_result，重建完整的工具调用链。现有 `fetch/claude_code.py` 只取了 question+conclusion，中间的执行过程被丢弃了。
2. **evaluator tool context**——LLM 提取记忆时，不仅知道"用户问了X，我回了Y"，还知道"我读了文件A、改了公式B、跑了测试C"。
3. **pattern analyzer**——跨会话检测工具使用模式，纯算法，零 LLM 成本。

**不需要改的**：pipeline 主体、chunker 去重、bucket-seal 机制、librarian 存储和检索、dreaming 循环。

---

## 进化怎么解决

**核心矛盾**：真正的自进化需要拥有 agent loop（Hermes 路线）。但我们可以做到**跨会话的离线进化**——这个 Hermes 反而做不到。

### 三层进化机制

**第一层：记忆进化（已有，pipeline evaluate）**

```
会话完成 → bucket 累积 → 触发 LLM 提取 → 结构化记忆写入 librarian
```

这是现有的。每次 pipeline 运行都会提取新记忆。记忆会 decay、会合并、会通过 dreaming 精炼。

**第二层：模式进化（新增，pattern analyzer）**

```
N 次会话的 tool event JSONL
  → 编辑距离聚类 tool name 序列
  → 发现 "excel_read → bash_python → excel_write" 出现 7 次
  → 标记为候选模式 {pattern_id, tool_sequence, frequency, sessions}
```

不依赖 LLM，纯算法运行。跨会话的视角是 Hermes 不具备的——因为 Hermes memory 是 per-session 冻结的。

**第三层：技能进化（新增，skill extractor）**

```
高置信模式 (≥5次, ≥3个不同 session)
  → 用 DeepSeek 读取模式关联的所有 session 片段
  → 提炼为 SKILL.md:
      - 触发条件: "用户要求分析 Excel 差异"
      - 推荐工具: excel_read → bash_python → excel_write
      - 常见陷阱: "合并单元格需先 unmerge"
      - 示例 prompt: "对比两个 sheet 的差异并生成报告"
  → 写入 librarian skills index (status: draft)
  → 用户审查后可 promote 为 active
```

**做不到的（需要 agent loop 才能做的事）**：

- 实时的"你正在重复上次的错误"提醒
- 踩坑后立即修补 skill
- mid-session nudge（"试试 X 方法"）
- 子代理并行时的共享学习

**能做到的（外部观察的优势）**：

- "你最近 20 次 Excel 操作有 15 次在修 VLOOKUP 错误——要不要我写个标准操作流程？"
- "检测到 git 工作流模式：你总是在 commit 前跑 `npm test`"
- 跨项目知识迁移：A 项目的模式自动出现在 B 项目的 context injection 里

---

## 和 Hermes 比较: 真实优劣

### Hermes 强的维度

| 维度 | 为什么 |
|------|--------|
| 实时干预 | 有 loop 就能 mid-turn 注入 |
| 成本控制 | 多模型路由，便宜的做机械操作 |
| 后端多样性 | docker/SSH/modal 原生支持 |
| 安全纵深 | 五层防线 |
| RL 训练 | 执行轨迹反馈到模型微调 |
| 子代理并行 | delegate_task 共享预算 |

### 这套方案强的维度

| 维度 | 为什么 |
|------|--------|
| 工具生态深度 | 16 MCP 覆盖 git/docker/excel/mongodb/playwright/pandoc... Hermes 需逐个重写 |
| 工具调用准确性 | Claude 模型固定最高水准，不会因路由降级 |
| 记忆容量和语义 | 多 vault 无上限 + 向量检索 vs 2200 字 FTS5 |
| 跨会话模式发现 | 外部观察者视角，Hermes 的 per-session 记忆看不见 |
| 领域专用工具 | rapid-ocr/pdf2md/wx-cli 造价场景开箱即用 |
| 零模型训练成本 | 不需要 GRPO RL pipeline 和 GPU |

### 对造价场景的适配

造价工程师的典型工作流：
```
收到微信文件 → OCR识别 → 提取数据 → Excel分析 → 生成报告 → 归档知识
```

这套方案的优势：
- **微信是原生数据源**：wx-cli 直接读微信 DB，文件、消息、联系人全在 librarian 可检索
- **文档处理链完整**：rapid-ocr(扫描件) → pdf2md(标书) → pandoc(格式转换) → excel(造价表)
- **知识积累自然发生**：每次分析自动归档，跨项目可检索，decay 自动淘汰旧定额
- **不需要云后端**：全部本地，造价数据不出机器

Hermes 要做同样的事需要：
- 自己写微信接入（原生支持刚上线，成熟度未知）
- 自己写 OCR handler
- 自己写 Excel 分析逻辑（或接 MCP，但会变成它不擅长的外挂模式）
- 用 2200 字的 MEMORY.md 承载造价知识（不够用）

---

## 实施路径

三个独立可交付的模块，不依赖 OpenClaw：

### Step 1: Tool Event 提取

从已有的会话 JSONL 中提取 tool event，写入 staging，让 pipeline 摄入。

- **输入**：`~/.claude/projects/*.jsonl`（已有，Claude Code 自动生成）
- **输出**：`~/.openclaw/staging/tool-events-{session_id}.json`
- **改动**：`fetch/claude_code.py` 增加 tool event 提取逻辑
- **不依赖任何新基础设施**

### Step 2: Pattern Analyzer + Skill Extractor

- **输入**：librarian 中的 tool event 记忆
- **输出**：候选模式 + 技能草稿（写入 librarian skills index）
- **改动**：新增 `analyze/` 和 `skills/` 两个 Python 包
- **不依赖 Step 1 之外的任何东西**

### Step 3: Context Injector

- **输入**：用户当前消息
- **输出**：<200 token 的相关记忆/技能提示
- **改动**：新增 `context/resolver.py`
- **两种使用方式**：
  - IDE 模式：手动调 `librarian.cmd resolve-context "消息"` 查看建议，自行参考
  - CLI 模式：薄桥接自动注入到 Claude CLI 的 system prompt

### 可选: 微信薄桥接

如果需要远程通过微信使用 Claude Code：
- 方案 A：提取 OpenClaw 的微信通道代码，剥离 gateway 层
- 方案 B：Python 从零写，用 wx-cli + subprocess 调 Claude CLI

---

## 关键设计决策

1. **不拥有 agent loop 是约束，不是设计选择**。如果 Claude Code 暴露 mid-turn hook，方案会立刻加入实时 nudge。目前接受这个天花板。

2. **外部观察的独特视角是副产品，不是设计目标**。但因为不拥有 loop，反而获得了跨会话、跨项目的模式发现能力——这是 Hermes 架构上做不到的。

3. **记忆系统本身就是护城河**。pipeline + librarian + dreaming 的体系不是"给 Claude Code 打的补丁"，而是一个独立的知识管理系统。它比 Hermes 的 3 层记忆深得多，而且不绑定任何 agent。

4. **MCP 生态是执行力根基**。不自己写工具，而是接入 MCP 生态——每个新 MCP 服务器自动成为系统的新能力，不需要改代码。
