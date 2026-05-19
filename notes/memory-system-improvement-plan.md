# 记忆系统改进实施方案

## 概述

**三根支柱架构**：OpenClaw（接入层）+ librarian（搜索引擎）+ Hermes（记忆引擎）。

```
┌──────────────────────────────────────────────────────────────────┐
│                        三根支柱架构                                │
│                                                                  │
│  支柱 A: OpenClaw          支柱 B: librarian        支柱 C: Hermes │
│  ┌──────────────────┐    ┌──────────────────┐    ┌────────────┐  │
│  │ 手机微信接入       │    │ FTS5 全文搜索     │    │ 三层记忆    │  │
│  │ 24渠道消息网关     │    │ 向量语义搜索     │    │ 自动策划    │  │
│  │ 内置 Cron 定时     │    │ 多 Vault 知识库   │    │ 自进化飞轮  │  │
│  │ Session 会话管理   │    │ 时间衰减排序     │    │ 跨会话模式  │  │
│  │ DM 安全配对        │    │ 文档摄入/索引    │    │ Skill 改进  │  │
│  │ Skills 市场        │    │ 价格数据查询     │    │ 夜间深度分析│  │
│  └────────┬─────────┘    └────────┬─────────┘    └─────┬──────┘  │
│           │                       │                     │         │
│           │    消息查询            │  结构化记忆          │         │
│           │◄─────────────────────►│◄───────────────────►│         │
│           │    Claude Code         │                     │         │
│           │    (推理引擎)          │                     │         │
│           └───────────────────────┴─────────────────────┘         │
│                                                                  │
│  数据流:                                                          │
│  手机微信 → OpenClaw Gateway → Claude Code → librarian 搜索       │
│  对话结束 → 摘要写入共享目录 → Hermes 夜间分析 → 记忆回写 librarian  │
│  每天凌晨 → OpenClaw Cron 或 Hermes → 索引维护 + 衰减重算          │
└──────────────────────────────────────────────────────────────────┘
```

基于对 FeynmanLibrary (SQLite FTS5 + 向量)、OpenClaw 生态 (Gateway 消息网关)、Hermes Agent (三层记忆+自进化飞轮) 三种方案的对比分析，制定以下 7 项渐进式改进方案。

改进遵循 **接入先行 → 搜索增强 → 记忆升级** 的递进路线。

---

## 总体路线图

```
Phase 0 (0-1周)     Phase 1 (1-3周)         Phase 2 (4-8周)        Phase 3 (9-14周)
┌──────────────┐   ┌─────────────────┐    ┌──────────────────┐    ┌────────────────────┐
│ 0. OpenClaw  │   │ 1. 周期性自动维护 │    │ 3. 通用知识库改造  │    │ 5. 自改进循环       │
│    手机接入   │ → │ 2. 自主记忆策划   │ →  │ 4. 时间衰减+频率   │ →  │ 6. Hermes 并行整合  │
│              │   │                  │    │                   │    │ 7. 三支柱联调       │
└──────────────┘   └─────────────────┘    └──────────────────┘    └────────────────────┘
```

---

## 实施进度（2026-05-16 更新）

> 最近审核: [progress-review-2026-05-15.md](review/progress-review-2026-05-15.md)

| 方案 | 完成度 | 状态 | 说明 |
|------|:---:|:----:|------|
| 方案0 OpenClaw 接入 | **85%** | 运行中 | WeChat IM Bot 已配置 |
| 方案1 周期性自动维护 | **95%** | 运行中 | 5 个 Cron job 全部验证通过，vec_reindex 已验证 |
| 方案2 自主记忆策划 | **90%** | 已修复 | ~~Hookify 不可行~~ → CLAUDE.md 指令 + MCP grow_session 工具链已验证通过 |
| 方案3 通用知识库改造 | **85%** | 代码已独立 | 代码已迁至 `~/.claude/mcp-servers/librarian/`，venv 已建，vaults.json 2 个 vault |
| 方案4 时间衰减+频率 | **95%** | 运行中 | 衰减排序已集成搜索, 访问计数待验证 |
| 方案5 自改进循环 | **85%** | 已修复 | analyze_session 工具链已验证通过, CLAUDE.md 指令替代 Hookify |
| 方案6 Hermes 整合 | **80%** | 待流入 | cli.py 9 个命令组 + Cron 夜间分析, 路径已更新至新 venv |
| 方案7 三支柱联调 | **30%** | 待验证 | 24h 稳定性, 端到端测试 |

### 分层完成度

```
代码层 (tools + cli.py + db schema):   ████████████████████████ 95%  (librarian MCP 已全局化)
触发层 (CLAUDE.md + Cron + 自动化):    ████████████████████░░░░ 90%  (Cron 路径全部更新)
数据层 (实际使用痕迹):                  ██░░░░░░░░░░░░░░░░░░░░   10%  (8 条记忆，积累缓慢)
```

### 2026-05-16 关键修复

**问题**: Hookify `action: warn` 在 stop 事件上无法驱动 Agent 执行 MCP 调用（Agent 在退出流程中无工具调用能力）。

**修复**: 
- 删除 3 条无效 Hookify 规则 (auto-memory-curation / auto-session-save / auto-skill-improvement)
- 在 CLAUDE.md 中新增「会话记忆归档」行为指令 —— Agent 在对话结束前主动调用 `save_session_note` → `grow_session` → `analyze_session`
- 工具链端到端验证通过: `cli.py session grow <session_id> true false` 成功将 memory_entries 从 14 条增至 18 条

### MCP 工具暴露方案说明

OpenClaw v2026.5.7 的 Pi Agent 目前不支持原生 MCP tool bundling（该功能为 Feature Request #29053）。社区插件 `@aiwerk/openclaw-mcp-bridge` 与当前版本不兼容。

采用 **cli.py 扩展命令** 方案：将全部 librarian MCP 工具封装为 CLI 子命令，agent 通过 `exec` + `python cli.py <command>` 调用。这提供了与原生 MCP tool 等价的覆盖：

- `cli.py search/excerpt/list/price` — 搜索/检索（已有）
- `cli.py memory/memory search` — 记忆管理（已有）
- `cli.py session suggest/analyze/grow` — 会话分析与记忆策划（新增）
- `cli.py vault list/register` — 知识库注册管理（新增）
- `cli.py maintain recalc/stale/cleanup` — 维护操作（新增，Cron 任务使用）
- `cli.py vec search/hyb/reindex/stats` — 向量语义搜索（新增）
- `cli.py maintain recalc` 已成功执行：更新 124,688 passages + 14 memories

---

**目标**: 建立手机微信到本地 librarian 搜索引擎的消息通道，实现"用手机查电脑文件"。

**当前状态**: 完全没有手机接入能力。所有查询必须在电脑前通过 Claude Code CLI/IDE 完成。

### 0.1 为什么用 OpenClaw 而不是轻量 Bridge

| 维度 | 轻量 Telegram Bridge | 完整 OpenClaw |
|------|:---:|:---:|
| 微信支持 | ❌ 没有 | 腾讯官方 `@tencent-weixin` 插件 |
| 渠道数量 | 1 个 | 24 个随时可加 |
| 会话管理 | ❌ 无状态 | DM 策略/配对安全/多账户隔离 |
| MCP 集成 | ❌ 需自己写桥接 | `mcp.servers` 原生支持 stdio |
| Skills 复用 | ❌ 需重新开发 | 现有 9 个 Skills 直接迁移 |
| 内置 Cron | ❌ 依赖 CC CronCreate | 独立 Cron，直接调 MCP 工具 |
| Claude Code 作为后端 | ❌ 不支持 | `claude-cli` 后端 bundleMcp=true |
| 维护成本 | 低（自写代码） | 中（跟随上游更新） |

**结论**：完整 OpenClaw 的方案差距不在功能多寡，而在于它和 Claude Code / librarian MCP 的集成是原生的，不需要自己写桥接代码。

### 0.2 部署架构

```
┌──────────────────────────────────────────────────────────────┐
│                      Windows 电脑 (开机即运行)                   │
│                                                              │
│  你的手机                                                     │
│  微信                                                        │
│    │                                                         │
│    ▼                                                         │
│  ┌──────────────────────────────────────┐                    │
│  │        OpenClaw Gateway               │                    │
│  │        (计划任务自启动)                 │                    │
│  │                                       │                    │
│  │  渠道: WeChat (腾讯官方插件)              │                    │
│  │       Telegram (Bot API)              │                    │
│  │                                       │                    │
│  │  后端: claude-cli                      │                    │
│  │       bundleMcp: true                 │                    │
│  │                                       │                    │
│  │  内置 Cron:                            │                    │
│  │  - 索引维护                           │                    │
│  │  - 记忆衰减重算                        │                    │
│  │  - 过期文档检测                        │                    │
│  └──────────────┬───────────────────────┘                    │
│                 │                                            │
│                 ▼                                            │
│  ┌──────────────────────────────────────┐                    │
│  │  MCP 服务器（全部复用，不改代码）       │                    │
│  │  ├── librarian (FTS5+向量)            │                    │
│  │  ├── rapid-ocr (OCR识别)              │                    │
│  │  ├── serena (代码符号搜索)            │                    │
│  │  ├── shell (文件系统操作)             │                    │
│  │  ├── excel (电子表格)                 │                    │
│  │  ├── chrome-devtools (浏览器自动化)   │                    │
│  │  └── ... 其余 7 个 MCP               │                    │
│  └──────────────┬───────────────────────┘                    │
│                 │                                            │
│                 ▼                                            │
│  ┌──────────────────────────────────────┐                    │
│  │  FeynmanLibrary + 多 Vault            │                    │
│  │  SQLite FTS5 + 向量索引               │                    │
│  │  memory_entries + sessions            │                    │
│  └──────────────────────────────────────┘                    │
│                                                              │
│  ┌──────────────────────────────────────┐                    │
│  │  Claude Code (电脑上的日常交互)        │                    │
│  │  + openclaw-control-mcp              │                    │
│  │  → 可在 CC 里管理 Gateway、看消息记录  │                    │
│  └──────────────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────┘
```

### 0.3 安装步骤

**Step 1: 安装 OpenClaw**

```powershell
# 安装 Node 24（如果没有），然后：
npm install -g openclaw@latest
openclaw onboard --install-daemon
```

**Step 2: Windows 自启动**（OpenClaw 原生 daemon 仅支持 launchd/systemd，Windows 用计划任务）

```powershell
$action = New-ScheduledTaskAction -Execute "npx" `
  -Argument "openclaw gateway"
$trigger = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBattery -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "OpenClawGateway" `
  -Action $action -Trigger $trigger -Settings $settings
```

**Step 3: 接入微信**

```bash
openclaw plugins install "@tencent-weixin/openclaw-weixin"
openclaw config set plugins.entries.openclaw-weixin.enabled true
openclaw gateway restart
openclaw channels login --channel openclaw-weixin   # 手机微信扫码
openclaw pairing approve openclaw-weixin <CODE>     # 信任你自己的微信
```

**Step 4: 接入现有 MCP 服务器**

```json5
// ~/.openclaw/openclaw.json
{
  mcp: {
    servers: {
      librarian: {
        command: "C:\\Users\\Kevin\\.claude\\mcp-servers\\librarian\\.venv\\Scripts\\python.exe",
        args: ["-m", "librarian_mcp.server"],
        env: {
          PYTHONPATH: "C:\\Users\\Kevin\\.claude\\mcp-servers\\librarian",
          PYTHONUNBUFFERED: "1",
        },
      },
      // 其余 12 个 MCP 同理...
    },
  },

  // Claude Code 后端配置
  agents: {
    defaults: {
      cliBackends: {
        "claude-cli": {
          bundleMcp: true,   // 将 OpenClaw MCP 工具暴露给 Claude Code
        },
      },
    },
  },
}
```

**Step 5: 部署文件检索 Skill**

在 `~/.openclaw/workspace/skills/file-librarian/SKILL.md` 中写入搜索策略指令（同此前设计）。

### 0.4 MCP 和 Skills 迁移清单

| 现有资产 | 数量 | 迁移方式 | 工作量 |
|:---|:---|:---|:---:|
| MCP 服务器 | 13 个 | `mcp.servers` 直接复制（stdio 类型不改代码） | 10 分钟 |
| Skills | 9 个 | 复制到 `workspace/skills/` + 调整目录结构 | 15 分钟 |
| librarian MCP | 1 套 | 不改代码，配置指向即可 | 1 分钟 |
| FeynmanLibrary | 全部 | 不改，OpenClaw agent 通过 librarian 访问 | 0 |
| Hookify 规则 | - | 部分拆分为 OpenClaw Hook + Cron | 1 小时 |

**核心原则**：现有 MCP、Skills、索引体系**一件不丢，全部可用**。

### 0.5 记忆存储策略

**关键问题**：Claude Code 的 auto-memory 按会话隔离。电脑上的对话和手机上的对话会生成两套互不可见的 MEMORY.md。

**解决方案**：强制所有记忆走 librarian 作为唯一存储。

```
电脑 Claude Code ──→ librarian.memory_write ──→ SQLite
手机 → OpenClaw → Claude Code ──→ librarian.memory_search ──→ 同一 SQLite
```

在 file-librarian Skill 中明确指令：

```markdown
## 记忆规则

- 需要记忆任何内容时，调用 librarian.memory_write
- 需要回忆时，调用 librarian.memory_search
- 不得使用 Claude Code 内置的 auto-memory 系统
- 这确保手机和电脑上的记忆是同一份
```

### 0.6 日常使用场景

| 场景 | 路径 |
|:---|:---|
| 手机查文件 | 微信发消息 → OpenClaw Gateway → Claude Code → librarian.search_summaries → 微信回复 |
| 电脑写代码 | VS Code Claude Code 插件，和之前完全一样 |
| 凌晨自动维护 | OpenClaw 内置 Cron → 调 librarian.check_stale / vec_reindex |
| 手机追问 | 同一微信 session 内多轮对话，OpenClaw 维护上下文 |
| 电脑上看到手机对话 | Claude Code 内通过 openclaw-control-mcp 查看 session 记录 |

**预计耗时**: 1-3 天
**依赖**: Node 24
**风险**: 低 —— OpenClaw 和 Claude Code 独立运行，互不破坏现有工作流。唯一注意点是微信插件需要 `@tencent-weixin/openclaw-weixin` 与 OpenClaw 版本兼容。

---

## 改进方案 1：周期性自动维护

**目标**: 让知识库自动保持健康状态，无需人工干预。

**当前状态**: 摄入、检查、索引全手动。`maintenance.py` 中有 git 预检工具但未接入自动化。

### 1.1 CronCreate 定时任务

利用 Claude Code 内置的 `CronCreate` 工具，创建以下定时任务：

| 任务 | 频率 | 触发 prompt | 说明 |
|------|------|-------------|------|
| 检查过期文档 | 每 6 小时 | 调用 librarian `check_stale` tool，列出源文件被更新但索引未刷新的文档，自动 re-ingest | 避免索引陈旧 |
| 记忆整理 | 每日 | 扫描 memory_entries，对 30 天未访问的低活跃条目建议清理 | 防止记忆膨胀 |
| Skill 使用统计 | 每日 | 分析 session 记录，统计各 skill 被调用频率和出错率 | 为改进 5 提供数据 |
| 向量索引维护 | 每周 | 调用 `vec_reindex` 全量重建向量索引 | 保持语义检索质量 |
| 价格数据刷新 | 每月 | 检查 price_index 旧数据，提示人工更新 | 信息价时效性 |

### 1.2 Hookify 事件驱动维护

在 Hookify 规则引擎中增加维护规则：

```markdown
---
name: auto-stale-check
enabled: true
event: session_end
action: background
---
对话结束后自动检查是否有已打开但未同步的文档，
如有则提示运行 ingest 同步。
```

### 1.3 实施步骤

1. 在 `hookify.*.global.md` 中添加 session_end 事件规则
2. 用 `CronCreate` 逐一注册定时任务
3. 测试第一个「检查过期文档」任务
4. 监控一周后调整频率和参数

**预计耗时**: 2-3 天
**依赖**: 无
**风险**: 低 —— 所有操作只读或增量，不影响现有数据

---

## 改进方案 2：自主记忆策划提示

**目标**: Agent 在对话结束时能主动判断哪些内容值得沉淀为记忆，而非等人下指令。

**当前状态**: 记忆写入需要人工触发 `memory_write` tool 或调用 `grow_session` 时设置 `apply_memory=True`。

### 2.1 核心机制

在 Claude Code session 结束时，通过 Hook (Stop 事件) 触发一个「记忆策划」prompt，让 Agent:

1. 回顾本次对话的关键决策、新知识、用户偏好变化
2. 对比现有 memory_entries，识别：
   - **新增**: 之前不知道的信息
   - **更新**: 已有记忆需要修正的部分
   - **过时**: 不再适用的旧记忆
3. 调用 librarian `memory_write` 写入变更

### 2.2 Hookify 规则设计

```markdown
---
name: auto-memory-curation
enabled: true
event: stop
action: prompt
conditions:
  - field: session_duration
    operator: greater_than
    value: 60
---
本对话结束。请回顾以下内容并决定是否需要写入记忆：

1. 本次解决了哪些问题？用的是什么方法？
2. 用户表达了哪些偏好或使用习惯？
3. 有哪些信息对未来的对话有帮助？

如果以上任一项有意义且记忆中尚无记载，请调用 librarian 的
memory_write 工具写入。不需要写入临时性的、仅本次有用的信息。
```

### 2.3 防止记忆污染的策略

- **最短对话时长过滤**: 少于 60 秒的对话不触发（忽略简单问答）
- **去重检查**: 写入前用 FTS5 搜索已有记忆，相似度 > 0.8 则跳过或更新
- **用户确认模式** (初期): 初期 `action: prompt` 让 Agent 建议但需用户确认，稳定后改为 `action: background`
- **类型约束**: 只写入 user/memory 类型，不写入临时/TODO 内容

### 2.4 实施步骤

1. 在 librarian 中添加 `suggest_memories` tool —— 输入 session_key，输出建议的 memory 条目
2. 创建 Hookify 规则触发记忆策划
3. 初期用 `action: prompt` 模式跑一周，观察记忆质量
4. 根据准确率决定是否切换到 `action: background`

**预计耗时**: 3-5 天
**依赖**: 无，librarian 已有 session 和 memory API
**风险**: 中 —— 可能产生冗余记忆，需要调优去重阈值

---

## 改进方案 3：通用知识库改造

**目标**: 将 librarian MCP 从 FeynmanLibrary 单一项目解耦，变为跨项目的通用个人知识库。

**当前状态**: librarian 硬绑定了 FeynmanLibrary 项目路径，PYTHONPATH 指向 `.trae`，其他项目无法使用。

### 3.1 架构改造

```
改造前:                          改造后:
FeynmanLibrary/                   ~/.claude/knowledge-base/
├── .trae/librarian_mcp/         ├── librarian_mcp/          ← 独立 MCP 代码
├── Knowledge/          →        ├── vaults/
├── Librarian/Memory/   →        │   ├── feynman/            ← 原 FeynmanLibrary
└── .library/library.db →        │   ├── engineering/         ← 新项目可按需增加
                                 │   └── personal/
                                 └── data/library.db         ← 所有 vault 共用
```

### 3.2 多 Vault 支持

在 `config.py` 中增加多 vault 配置：

```python
VAULTS = {
    "feynman": {
        "path": "F:/FeynmanLibrary",
        "name": "Feynman 知识库",
        "description": "工程技术和造价领域知识",
        "types": ["knowledge", "prices", "sessions"],
    },
    "engineering": {
        "path": "E:/Projects/Engineering",
        "name": "工程项目",
        "description": "各工程项目文档和笔记",
        "types": ["knowledge"],
    },
    "personal": {
        "path": os.path.expanduser("~/Documents/Notes"),
        "name": "个人笔记",
        "description": "日常学习和记录",
        "types": ["knowledge", "sessions"],
    },
}
```

### 3.3 改造要点

| 改造项 | 说明 |
|--------|------|
| 路径参数化 | 所有硬编码路径改为配置驱动，vault 路径可动态注册 |
| 搜索跨 Vault | `search_summaries` 增加 `vault` 参数，支持跨 vault 联合搜索 |
| 独立安装 | MCP 代码独立于 FeynmanLibrary，作为独立包安装到 `~/.claude/mcp-servers/` |
| 向后兼容 | 默认 vault 仍指向 FeynmanLibrary，现有功能不变 |
| 接入方式 | 其他项目通过 `.mcp.json` 的 `env.VAULT` 指定默认 vault |

### 3.4 实施步骤

1. ~~将 `librarian_mcp` 代码复制到 `~/.claude/mcp-servers/librarian/`~~（已完成 2026-05-17）
2. 重构 `config.py`，引入 `VAULTS` 字典替代硬编码路径
3. 在 `server.py` 中添加 `register_vault` / `list_vaults` MCP tool
4. 更新 `.mcp.json` 中 librarian 的启动参数
5. 测试原 FeynmanLibrary 功能不变
6. 在新项目中测试跨 vault 检索

**预计耗时**: 2-3 周
**依赖**: 无
**风险**: 中 —— 涉及路径重构，需要充分测试确保不破坏现有索引

---

## 改进方案 4：时间衰减 + 访问频率跟踪

**目标**: 让活跃的记忆自动提升权重，陈旧的记忆自然降权，模拟人脑的遗忘曲线。

**当前状态**: 所有 passage 使用固定 priority 权重（100/90/40/20），不随时间或访问频率变化。

### 4.1 衰减模型设计

采用 **Ebbinghaus 遗忘曲线变体** 结合访问频率修正：

```
score = priority_base × time_decay × access_boost

time_decay    = e^(-λ × days_since_last_access)
access_boost  = 1 + α × log(1 + access_count)
```

| 参数 | 含义 | 建议初始值 |
|------|------|-----------|
| λ (decay_rate) | 衰减速度 | 0.01 (约 100 天后衰减至 0.37) |
| α (boost_factor) | 访问频率增益 | 0.3 |
| priority_base | 文档类型基础权重 | 沿用现有值 (100/90/40/20) |

### 4.2 数据库改造

在 `passages` 表和 `memory_entries` 表中增加字段：

```sql
ALTER TABLE passages ADD COLUMN access_count INTEGER DEFAULT 0;
ALTER TABLE passages ADD COLUMN last_access_at TEXT;
ALTER TABLE passages ADD COLUMN decay_score REAL DEFAULT 1.0;

ALTER TABLE memory_entries ADD COLUMN access_count INTEGER DEFAULT 0;
ALTER TABLE memory_entries ADD COLUMN last_access_at TEXT;
ALTER TABLE memory_entries ADD COLUMN decay_score REAL DEFAULT 1.0;
```

### 4.3 打分逻辑

在 `search_summaries` 的 SQL 查询中集成衰减分数：

```sql
SELECT ...,
  bm25(passage_fts) AS fts_score,
  passages.decay_score AS decay_score,
  (bm25(passage_fts) * passages.decay_score * passages.priority / 100.0) AS final_score
FROM passage_fts
JOIN passages ON passage_fts.passage_id = passages.id
WHERE passage_fts MATCH ?
ORDER BY final_score DESC
```

### 4.4 自动维护

- 每次 `get_excerpt` 调用，自动 `access_count += 1`、更新 `last_access_at`
- 每次 `search_summaries` 命中，对 Top-K 结果自动 `access_count += 1`
- 每日 Cron 任务重新计算所有条目的 `decay_score`

### 4.5 实施步骤

1. 在 `service.py` 中添加 ALTER TABLE 迁移
2. 修改 `search_summaries` 查询集成衰减分数
3. 修改 `get_excerpt`、`memory_list` 更新访问计数
4. 添加 `_recalc_decay_scores()` 方法
5. 创建每日 Cron 重算衰减分数
6. 手动测试搜索排序质量变化

**预计耗时**: 1 周
**依赖**: 无（增量改动，不影响现有数据）
**风险**: 低 —— 只是新增字段和排序调整

---

## 改进方案 5：Agent 自改进循环

**目标**: 让 Agent 在完成任务后自动分析表现、提炼经验、改进 Skill。

**当前状态**: Skill 有版本跟踪但改进靠人工。`grow_session` 可以建议 skill draft 但需人工审批。

### 5.1 自改进循环设计

参考 Hermes 的五环飞轮，设计简化版三环循环：

```
┌──────────────────────────────────────────────────┐
│                                                  │
│  ① 任务完成分析                                    │
│     └→ 提取: 成功策略 / 错误教训 / 新发现的工具用法     │
│              ↓                                    │
│  ② Skill 改进建议                                 │
│     └→ 对比现有 skill，生成 patch/draft              │
│              ↓                                    │
│  ③ 记忆更新                                       │
│     └→ 将关键发现写入 memory，关联 skill 版本         │
│              ↓                                    │
│  (回到①，下次任务受益)                              │
└──────────────────────────────────────────────────┘
```

### 5.2 实现方式 —— 新增 `analyze_session` MCP Tool

在 librarian 中新增 `analyze_session` 工具：

```python
@mcp.tool()
def analyze_session(
    session_key: str,
    auto_apply: bool = False
) -> dict:
    """
    分析对话 session，输出:
    - patterns: 重复出现的任务模式
    - wins: 成功的策略，可固化为 skill
    - pitfalls: 出错的地方，应加入 skill 的注意事项
    - skill_suggestions: 建议创建/修改的 skill 及具体 diff
    - memory_suggestions: 建议写入的记忆
    """
```

### 5.3 触发机制

通过 Hookify `stop` 事件触发，类似方案 2：

```markdown
---
name: auto-skill-improvement
enabled: true
event: stop
action: prompt
conditions:
  - field: session_duration
    operator: greater_than
    value: 300
  - field: tool_usage
    operator: contains
    value: skill
---
本次对话使用了 Skill，请分析是否有改进空间:
1. Skill 的步骤是否有遗漏或多余？
2. 是否有新的工具或方法可以替换旧步骤？
3. 用户的反馈是否指向某个步骤需要调整？

如有改进建议，使用 skill-creator 或直接编辑 skill 文件。
```

### 5.4 Skill 自改进安全机制

| 机制 | 说明 |
|------|------|
| **Git 版本控制** | librarian 已有 skill 版本表，每次改进自动增加版本记录 |
| **Diff 预览** | `auto_apply=False` 时仅输出建议 diff，由用户审批 |
| **回滚能力** | 保留旧版本文件路径，可一键回退 |
| **影响范围检测** | 改进前用 serena 的 `find_referencing_symbols` 检测 skill 被哪些项目引用 |
| **A/B 对比** | 新版本保存为 draft，人工验证后再 promote |

### 5.5 实施步骤

1. 在 librarian 中实现 `analyze_session` 方法
2. 创建 Hookify 规则，在长对话结束时触发分析
3. 初期 `auto_apply=False`，仅输出建议
4. 收集 2 周的改进建议数据，评估准确率
5. 准确率 > 80% 后考虑 `auto_apply=True` 自动更新

**预计耗时**: 2-3 周
**依赖**: 方案 1 (需 session 使用统计)、方案 2 (记忆策划为前置能力)
**风险**: 中高 —— Agent 自主修改 Skill 有破坏风险，初期必须人工审批

---

## 改进方案 6：Hermes 三支柱整合

**目标**: 将 Hermes Agent 整合进 OpenClaw + librarian 架构，形成完整的三支柱系统：OpenClaw（接入）→ librarian（搜索）→ Hermes（记忆进化）。

**当前状态**: 完全未开始。上一版方案 6 的架构图中只有 Claude Code + Hermes，缺少 OpenClaw 接入层。

### 6.1 三支柱完整架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Windows 电脑 (开机即运行)                      │
│                                                                      │
│  ┌──────────────────────────┐     ┌──────────────────────────┐       │
│  │   支柱 A: OpenClaw        │     │   支柱 B: librarian       │       │
│  │   (接入层)                │     │   (搜索引擎)              │       │
│  │                          │     │                          │       │
│  │  ┌────────────────────┐  │     │  ┌────────────────────┐  │       │
│  │  │ WeChat (腾讯插件)   │  │     │  │ FTS5 全文搜索       │  │       │
│  │  │ Telegram / WhatsApp│  │     │  │ 向量语义搜索        │  │       │
│  │  │ 24 渠道随时扩展     │  │     │  │ 多 Vault 联合检索   │  │       │
│  │  └────────┬───────────┘  │     │  │ 时间衰减排序        │  │       │
│  │           │              │     │  │ 价格数据查询        │  │       │
│  │  ┌────────▼───────────┐  │     │  │ memory_entries     │  │       │
│  │  │ Gateway 会话管理    │  │     │  │ sessions 记录      │  │       │
│  │  │ DM配对/多Agent路由  │  │     │  └────────────────────┘  │       │
│  │  └────────┬───────────┘  │     │                          │       │
│  │           │              │     └────────────┬─────────────┘       │
│  │  ┌────────▼───────────┐  │                  │                     │
│  │  │ 内置 Cron 定时维护  │  │                  │                     │
│  │  │ Claude Code 后端   │  │                  │                     │
│  │  │ 13 个 MCP 服务器   │  │                  │                     │
│  │  │ 9+ Skills          │  │                  │                     │
│  │  └────────────────────┘  │                  │                     │
│  └────────────┬─────────────┘                  │                     │
│               │                                │                     │
│               │   查询请求                      │                     │
│               │◄───────────────────────────────►│                     │
│               │   搜索结果                      │                     │
│               │                                │                     │
│               │   写入记忆                      │                     │
│               │────────────────────────────────►│                     │
│               │                                │                     │
│  ┌────────────┴────────────────────────────────┴────────────────┐    │
│  │                    支柱 C: Hermes Agent (记忆引擎)              │    │
│  │                                                                │    │
│  │  ┌──────────────────────────────────────────────────────────┐ │    │
│  │  │  三层记忆结构                                              │ │    │
│  │  │                                                          │ │    │
│  │  │  ① 工作记忆 (Working)    → 当前对话上下文，结束自动清空      │ │    │
│  │  │  ② 情节记忆 (Episodic)   → 对话摘要，自动总结，按时间衰减    │ │    │
│  │  │  ③ 语义记忆 (Semantic)   → 压缩后的长期知识，去重+冲突解决   │ │    │
│  │  └──────────────────────────────────────────────────────────┘ │    │
│  │                                                                │    │
│  │  ┌──────────────────────────────────────────────────────────┐ │    │
│  │  │  五环自进化飞轮                                            │ │    │
│  │  │                                                          │ │    │
│  │  │  ① 观察 → ② 分析 → ③ 提炼 → ④ 验证 → ⑤ 固化 → 回到①    │ │    │
│  │  │  监控   模式识别  Skill/Memory  A/B对比  写入librarian       │ │    │
│  │  └──────────────────────────────────────────────────────────┘ │    │
│  │                                                                │    │
│  │  输入: 共享目录中的新 session 摘要                               │    │
│  │  输出: 结构化记忆 + 改进后的 Skill，写入 librarian               │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                     共享知识目录                               │    │
│  │  ~/.claude/knowledge/                                        │    │
│  │  ├── sessions/    ← Hook Stop 自动写入对话摘要                 │    │
│  │  ├── memory/      ← Hermes 提炼的结构化记忆                    │    │
│  │  └── skills/      ← Hermes 改进后的 Skill（可选）              │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.2 三支柱的职责分工

| 职责 | 支柱 A: OpenClaw | 支柱 B: librarian | 支柱 C: Hermes |
|------|:---:|:---:|:---:|
| 手机消息接入 | **主** | — | — |
| 渠道管理 (微信/Telegram/...) | **主** | — | — |
| 会话管理 / DM 安全 | **主** | — | — |
| 定时维护 (Cron) | **主** | — | 辅 (夜间分析) |
| 全文搜索 (FTS5) | — | **主** | — |
| 向量语义搜索 | — | **主** | — |
| 多 Vault 知识库 | — | **主** | — |
| 时间衰减排序 | — | **主** | — |
| 文档摄入/索引 | — | **主** | — |
| 三层记忆结构 | — | — | **主** |
| 自动记忆策划 | — | 存储 | **主** |
| 跨会话模式识别 | — | — | **主** |
| Skill 自改进 | — | 存储 | **主** |
| 夜间深度分析 | — | — | **主** |
| Claude Code 推理 | **主**（作为后端） | — | — |

### 6.3 数据流：一次完整的"手机查文件 + 记忆沉淀"过程

```
时间线:  白天 10:00                          凌晨 03:00          第二天
────────────────────────────────────────────────────────────────────────

[T+0s]  你在微信发 "找混凝土规范的关键参数"
[T+1s]  OpenClaw Gateway 收到 → 认证通过 → 路由到 Claude Code session
[T+2s]  Claude Code 推理 → 调用 librarian.search_summaries("混凝土 规范")
[T+3s]  librarian FTS5 搜索 → 返回 5 条结果（按 decay_score 排序）
[T+5s]  Claude Code 整理结果 → 微信回复你摘要
[T+10s] 你追问 "把第三个打开看看" → session 上下文在，Agent 知道"第三个"是什么
[T+15s] Claude Code 调用 librarian.get_excerpt → 返回详情

[对话结束]
[T+1h]  Hook Stop → 写 session 摘要到 ~/knowledge/sessions/day-2026-05-14-001.json

[T+12h] Hermes 夜间 Cron 触发
        → 读取新 session 摘要
        → 分析: "用户频繁查找混凝土相关规范 → 可能是正在进行的项目"
        → 提炼语义记忆: "Kevin 当前关注: 混凝土工程验收规范"
        → 写入 librarian.memory_write
        → 检测到 file-librarian Skill 在搜索规范类文档时可以自动添加相关 vault
        → 生成 Skill patch 保存为 draft

[T+13h] OpenClaw Cron: librarian.vec_reindex（纳入新记忆）
[T+13h] OpenClaw Cron: librarian.check_stale → re-ingest 过期文档

[第二天]
        你在电脑上问 Claude Code "上次说的混凝土规范"
        → librarian.memory_search("混凝土") → 命中昨晚 Hermes 写的记忆
        → librarian.search_summaries → 按更新后的 decay_score 排序
        → 你得到比昨天更好的结果
```

### 6.4 Hermes 如何防止"记忆越存越多变笨"

Hermes 的三层记忆天然解决了这个问题：

```
Claude Code auto-memory 的问题        Hermes 的解决方式
─────────────────────────────        ─────────────────
追加式写入，从不删除                  情节记忆有生命周期，过期自动衰减
原文存储，占用大量 token              语义记忆是压缩后的知识摘要
新旧记忆并存，可能矛盾                写入前去重，冲突时新信息覆盖旧
没有质量评估                          五环飞轮的"验证"阶段检查记忆质量
被动堆积                              主动策划，判断哪些值得长期保留
```

**具体到数据层面**：

| | Claude Code auto-memory | Hermes + librarian |
|:---|:---|:---|
| 3 个月后记忆条目 | ~200 条原文 | ~50 条压缩摘要 + 按 decay_score 排序 |
| 每次对话加载的 token | ~20,000-60,000 | ~500（只加载最相关的 3 条） |
| 矛盾记忆 | 两者都保留，Agent 困惑 | 写入前自动去重 |
| 过期记忆 | 手动清理 | 自然衰减到排序末尾，超过阈值自动归档 |

### 6.5 实施步骤

**阶段 A: 先跑通 Nightly Pipeline（本质是方案 2 + 方案 4 的自动化）**

1. 创建共享目录 `~/.claude/knowledge/sessions/`
2. 在 OpenClaw 中配置 session_end Hook（或 Claude Code Hookify），自动写 session 摘要
3. 在 librarian 中实现 `suggest_memories(session_key)` 方法
4. 配置 OpenClaw Cron 每日夜间运行记忆策划
5. 初期不自动写入，输出建议报告 → 人工审批

**阶段 B: 引入 Hermes 五环飞轮**

1. 在 WSL 或 Docker 中安装 Hermes Agent
2. Hermes 读取 `~/knowledge/sessions/` 中的新摘要
3. 配置 Hermes 定时任务：夜间分析 → 提炼记忆 → 回写 librarian
4. Hermes 生成 Skill 改进建议 → 保存为 draft → 人工审批
5. 逐步提高自动化程度（准确率 > 80% 后放开自动写入）

**阶段 C: 三支柱联调**

1. 验证：手机查文件 → 结果正确
2. 验证：记忆自动沉淀 → librarian 中可见
3. 验证：第二天搜索 → 受益于新记忆
4. 验证：Skill 自动改进 → draft 质量可用
5. 压力测试：100+ 条记忆下搜索延迟 < 500ms

### 6.6 和旧版方案 6 的区别

| | 旧版方案 6 | 新版方案 6 |
|:---|:---|:---|
| 接入层 | 只有 Claude Code | OpenClaw Gateway |
| 记忆来源 | 仅电脑上的对话 | 电脑 + 手机全渠道 |
| 记忆目标 | 写入 MEMORY.md 文件 | 写入 librarian SQLite |
| Hermes 角色 | 和 CC 平级的外脑 | 支柱 C，处理所有渠道的记忆 |
| 数据交换 | 共享目录（`~/knowledge/`） | 同一个共享目录，但现在三根支柱都读写它 |

**预计耗时**: 3-5 周
**依赖**: 方案 0 (OpenClaw 接入)、方案 2 (自主记忆策划) 已稳定运行、方案 3 (多 Vault) 完成、方案 4 (时间衰减) 完成
**风险**: 中高 —— Hermes 需要另外的 Python 环境（WSL/Docker），调试跨系统协作复杂。

---

## 改进方案 7：三支柱联调（收尾）

**目标**: 确保 OpenClaw + librarian + Hermes 三根支柱无摩擦协作，端到端验证。

**当前状态**: 三根支柱各自独立开发，尚未联合测试。

### 7.1 联调检查清单

| 测试场景 | 预期行为 | 验证方式 |
|:---|:---|:---|
| 手机微信查文件 | 微信发消息 → 5 秒内收到搜索结果 | 实际用手机发消息测试 |
| 电脑 Claude Code 查文件 | 和之前完全一样，不受 OpenClaw 影响 | 正常使用 CC |
| 记忆跨渠道可见 | 手机上对话产生的记忆，电脑上也能查到 | librarian.memory_list 验证 |
| Cron 自动维护 | 凌晨自动 re-ingest + 衰减重算 | 次日检查日志 |
| Hermes 夜间分析 | 次日 librarian 中有新的结构化记忆 | 检查 memory_entries 表 |
| 搜索排序受益 | 活跃文档排序提升，陈旧文档下沉 | 对比衰减前后排序 |
| MCP 服务器无冲突 | OpenClaw 和 CC 各自的 MCP 实例不冲突 | 启动后检查进程 |
| OpenClaw 自启动 | 重启电脑后 Gateway 自动运行 | 重启后微信发消息测试 |

### 7.2 关键约束

- librarian MCP 同一时间只能有一个 Python 进程持有 SQLite 写锁。OpenClaw 和 Claude Code 不能各自启动两个 librarian 实例。**解决方法**：librarian MCP 只在 OpenClaw 的 `mcp.servers` 中定义，Claude Code 通过 `openclaw-control-mcp` 间接使用，或两个系统共用同一个 librarian 进程（通过 HTTP transport 暴露）。
- Hermes 写记忆时可能和 OpenClaw Cron 的维护任务冲突。**解决方法**：错开时间窗口（Hermes 03:00-03:30，librarian 维护 04:00-04:30）。

### 7.3 实施步骤

1. 先只开 OpenClaw + librarian（方案 0），关掉 Hermes → 验证手机查文件正常
2. 加入 Hermes Nightly Pipeline → 验证记忆自动沉淀
3. 开启 OpenClaw Cron 自动维护 → 验证不冲突
4. 跑一周 → 检查记忆质量 → 调整 Hermes 参数

**预计耗时**: 1 周
**依赖**: 方案 0 + 方案 2 + 方案 4 + 方案 6 全部完成
**风险**: 低 —— 每个支柱独立运行时已经验证过，联调主要是时间窗口和资源冲突问题。

---

## 实施优先级总结

```
         impact
           ↑
    高     │  方案0(OpenClaw)     方案6(Hermes)
           │  方案3(通用KB)       方案5(自改进)
           │  方案2(自主记忆)      方案7(联调)
           │
    低     │  方案1(自动维护)
           │                     方案4(衰减)
           │
           └──────────────────────────────────→ complexity
              低                  高
```

**推荐顺序**:

1. **方案 0** (第 1 周) —— OpenClaw 手机接入，立刻获得"手机查文件"能力，独立的可交付价值
2. **方案 1 + 方案 4** (第 2 周) —— 自动维护 + 时间衰减，两个改动最小、独立性强
3. **方案 2** (第 3 周) —— 自主记忆策划，依赖方案 1 的 Hook/Cron 基础
4. **方案 3** (第 4-5 周) —— 通用知识库改造，为 Hermes 的多 vault 集成铺路
5. **方案 5** (第 6-7 周) —— 自改进循环，依赖方案 2 的记忆能力和方案 3 的通用化
6. **方案 6** (第 8-12 周) —— Hermes 三支柱整合，依赖前面所有方案成熟
7. **方案 7** (第 13-14 周) —— 三支柱联调，端到端验证

**每个方案完成后都有可交付的独立价值**，不会因为后续方案延迟而白做。

---

## 成功指标

| 指标 | 当前 | Phase 0 后 | Phase 1 后 | 最终目标 (24 周) |
|------|------|-----------|-----------|----------------|
| 手机接入 | 无 | 微信可用 | — | 微信 + Telegram |
| 记忆条目数 | ~20 (手动) | ~20 | ~50 (自动策划) | 100+ (自动策划+去重) |
| 记忆检索命中率 | 手动调用 | 手动调用 | 每次对话 ≥ 2 条 | 每次对话 ≥ 3 条 |
| 记忆 token 开销 | ~2,000-6,000 | 不变 | ≤ 1,000 | ≤ 500 |
| Skill 自我改进次数 | 0 | 0 | 人工审批 | ≥ 10 次 (自动) |
| 过期文档检测 | 手动 | 手动 | 自动化 (6h 内) | 实时 (文件监听) |
| 跨项目知识可用 | 仅 Feynman | 仅 Feynman | ≥ 2 个 vault | ≥ 3 个 vault |
| Agent 自主学习循环 | 无 | 无 | 无 | 每日 1 次 |
| 搜索排序质量 | 固定 priority | 固定 priority | 衰减排序 | 衰减 + 频率 + 语义 |

---

## 附录：参考资源

- librarian 源码: `C:\Users\Kevin\.claude\mcp-servers\librarian\librarian_mcp\`（配置模板: `C:\Users\Kevin\claude-code-config\mcp-servers\librarian\`）
- 对比分析: `C:\Users\Kevin\claude-code-config\note\memory-comparison.md`
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- OpenClaw 记忆生态: https://github.com/coolmanns/openclaw-memory-architecture
- ClawMem (跨运行时记忆): https://www.npmjs.com/package/clawmem
- OpenClaw 主仓库: https://github.com/openclaw/openclaw
- OpenClaw 微信插件: https://docs.openclaw.ai/channels/wechat
- openclaw-control-mcp: https://www.npmjs.com/package/openclaw-control-mcp
- Claude Code 与 OpenClaw MCP/Skills 机制: https://developer.huawei.com/home/forum/hwc/thread-0212720909615464908-1-1.html
