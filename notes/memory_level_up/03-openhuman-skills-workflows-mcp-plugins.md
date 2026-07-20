# OpenHuman Skills、工作流、MCP、插件配置报告

> 研究日期: 2026-05-20
> 数据来源: GitHub Issues、README、源码架构、Composio 文档、lerim MCP 项目

---

## 1. Skills 系统

### 1.1 架构概览

OpenHuman 的 Skills 系统是一个**沙箱化 QuickJS (QJS) 运行时**——本质上是 OpenHuman 的插件系统。

```
Skill 代码 (TypeScript) → 编译 → QuickJS 沙箱执行
                              ↓
                    @openhuman/sdk 包提供 API
                              ↓
                    注册到 ~/.openhuman/ 工作区
```

### 1.2 技术细节

| 维度 | 详情 |
|------|------|
| **运行时** | QuickJS (QJS) — 沙箱化 JavaScript |
| **SDK** | `@openhuman/sdk` npm 包 |
| **安装位置** | `~/.openhuman/` 工作区路径 |
| **社区仓库** | `github.com/tinyhumansai/openhuman-skills` |
| **工具超时** | 硬编码 120s（Issue #214 提出应可配置） |
| **事件循环** | 每 5ms 轮询工具完成状态 |
| **调试工具** | REPL（Issue #92 设计中） |

### 1.3 官方 Skills（v0.54.0 已确认）

| Skill | 功能 | 状态 |
|-------|------|------|
| `server-ping` | 参考/演示 skill，模板 | 稳定 |
| `notion` | 完整 Notion 工作区集成（读写、搜索、数据库操作） | 稳定 |
| `gmail` | Gmail 读写 + 自动摘要 | 稳定 |

### 1.4 Skill 代码结构

```typescript
import { SkillDefinition } from "@openhuman/sdk";

export const skill: SkillDefinition = {
  id: "my-skill",
  name: "My Custom Skill",
  version: "1.0.0",

  // 生命周期
  async onInit() { /* 初始化逻辑 */ },

  // 注册工具（每个工具 = 一个 typed function，暴露给 agent）
  tools: [{
    name: "fetch_data",
    description: "从自定义源获取数据",
    parameters: {
      type: "object",
      properties: {
        url: { type: "string" }
      }
    },
    async execute({ url }) { /* 工具实现 */ }
  }],

  // 定时调度（cron 表达式）
  schedules: [
    { cron: "*/30 * * * *", handler: "fetchLatestUpdates" }
  ]
};
```

### 1.5 Skill CLI / REPL（设计中，Issue #92）

```
skill list              → 列出所有已安装 skills
skill run <id>          → 调用指定 skill
skill install <path>    → 安装 skill
rpc call <method>       → 原始 JSON-RPC 调用（调试用）
config show             → 显示当前配置
config set <key> <val>  → 动态修改配置
help                    → 命令参考
```

REPL 底层对接的是 OpenHuman 的内部 JSON-RPC API（`openhuman_core`、`core_server`、controller registry）。

---

## 2. 核心工作流

### 2.1 自动摄取管道（Auto-Fetch Pipeline）

这是 OpenHuman 区别于其他 agent harness 的最核心工作流：

```
┌──────────────────────────────────────────────────────┐
│              每 20 分钟触发一次                         │
│                                                      │
│  活跃 OAuth 连接 → 拉取最新数据 → TokenJuice 压缩      │
│       ↓                                              │
│  Canonicalizer（标准化为 Markdown）                    │
│       ↓                                              │
│  Chunker（切分为 ≤3000 token 的块，SHA-256 生成 ID）    │
│       ↓                                              │
│  Scorer（信号评分 + embedding）                        │
│       ↓                                              │
│  Memory Tree（SQLite + Obsidian .md vault）            │
└──────────────────────────────────────────────────────┘
```

**与你的架构对比**：你目前没有被动摄取管道。Claude Code 对话结束后需要你手动触发 `save_session_note` → `grow_session` 才能归档。OpenHuman 是零操作的。

### 2.2 模型路由（Model Routing）

```
任务进入
  ├─ 复杂推理（代码分析、长篇写作）→ Claude Opus / o3
  ├─ 快速查询（简单问答、查找）    → GPT-4o-mini / Haiku
  ├─ 图片理解                     → Vision 模型
  └─ 隐私敏感（可选）              → 本地 Ollama 模型
```

这是一个智能代理（dispatcher），不是一个模型列表。对用户透明——你不需要手动选择模型。

**与你的架构对比**：Claude Code 本身不支持多模型路由。OpenClaw 的 `openclaw.json` 有 models.providers 配置，但没有自动路由——你需要手动指定用哪个模型。

### 2.3 潜意识循环（Subconscious Loop）

替代了旧的 Heartbeat 系统（`src/openhuman/heartbeat/engine.rs` → `src/openhuman/subconscious/`）。

```
每 5 分钟一次 tick:
  Step 1: 组装态势报告（30-50k token 预算）
          包含: 记忆变更、工具注册表、环境变量、通道状态
          使用 hash/cursor 标记"无变化"的部分
  Step 2: 本地小模型评估 → 输出决策: no-op / enqueue / escalate
  Step 3: 仅在决策 = escalate 时调用强模型或排入主 agent 循环
```

**六种反思类型**：
1. **热度突变** — 某个实体/话题突然频繁出现
2. **跨源模式** — Gmail + Slack + GitHub 同时出现同一件事
3. **每日摘要** — 当日重要事件自动汇总
4. **截止提醒** — 检测到截止日期临近
5. **风险模式** — 发现异常或潜在问题
6. **机会模式** — 发现可行动的优化点

**安全边界**：只观察不行动。需要写操作时必须生成 escalation 请求，等待人工批准。

### 2.4 Screen Intelligence（屏幕感知）

```
每 5 秒截图 → 本地 Gemma 3 Vision 模型 → 结构化摘要
                                            ↓
                             当前工作上下文: 应用、可见内容
                                            ↓
                             原始图片不离开设备
```

这是一个**并行后台循环**，独立于潜意识循环运行。它让 agent 知道你当前在做什么（看什么网页、编辑什么文件、开什么会）。

---

## 3. MCP 集成

### 3.1 当前状态：无原生 MCP 支持

OpenHuman 的 README 没有任何 MCP（Model Context Protocol）相关描述。它的扩展模型是** Skills（QuickJS 沙箱）**，不是 MCP。

### 3.2 Lerim MCP 桥接

第三方项目 [lerim](https://data.safetycli.com/packages/pypi/lerim/)（v0.3.0）提供了 OpenHuman 的 MCP 客户端配置生成：

```bash
lerim connect --mode mcp    # 自动生成 OpenHuman MCP 客户端配置
```

Lerim MCP Server 提供的工具：

| 工具 | 功能 |
|------|------|
| `context_brief` | 简要上下文检索 |
| `context_answer` | 上下文问答 |
| `context_search` | 语义搜索 |
| `records_listing` | 确定性记录列表 |
| `trace_submission` | 追踪注入 |
| `ingest/status` | 摄入状态查询 |

### 3.3 MCP 与 Skills 的定位对比

| 维度 | Skills (QuickJS) | MCP (Lerim) |
|------|-----------------|-------------|
| 集成方式 | 原生、内置 | 第三方桥接 |
| 运行环境 | QuickJS 沙箱 | 独立进程 |
| 扩展性 | 写 TypeScript 代码 | 通过 MCP 协议 |
| 成熟度 | v0.54.0，持续迭代 | v0.3.0，实验性 |
| 工具注册 | 编译时静态注册 | 运行时动态发现 |

**结论**：OpenHuman 选择了自建 Skills 系统而非采用 MCP 标准。短期看生态更可控，长期看可能面临与其他 agent 工具不兼容的问题。你的架构中 MCP 是核心扩展机制（13 个 MCP 服务器），这一点上你比 OpenHuman 更开放。

---

## 4. 插件系统

### 4.1 当前状态

OpenHuman **没有传统意义上的"插件"概念**。Skills 系统承担了插件的角色。在 README 的对比表中，它批评竞品 OpenClaw 是"Plugin-reliant"（依赖插件），言下之意是自己不需要插件——Skills 已经够了。

### 4.2 扩展机制总览

| 扩展方式 | 说明 | 对应你的架构 |
|---------|------|------------|
| Skills (QuickJS) | 自定义工具和定时任务 | MCP 服务器 |
| OAuth 集成 | 118+ 第三方服务连接 | 部分 MCP（如 GitHub MCP） |
| TokenJuice 规则 | 三层 JSON 配置文件 | settings.json |
| config.toml | 主配置文件 | openclaw.json / settings.json |
| REPL (待实现) | 运行时命令和控制 | /slash commands |

---

## 5. 配置系统

### 5.1 配置文件

| 文件 | 格式 | 用途 |
|------|------|------|
| `config.toml` | TOML | 主配置（记忆后端、模型选择等） |
| TokenJuice 内置规则 | JSON | 内置压缩规则 |
| `~/.config/tokenjuice/rules/` | JSON | 用户级压缩规则覆盖 |
| `.tokenjuice/rules/` | JSON | 项目级压缩规则覆盖 |

### 5.2 config.toml 已知选项

```toml
[memory]
backend = "agentmemory"  # 可选: "local" (默认) 或 "agentmemory" (共享记忆)

[models]
provider = "anthropic"   # openai / anthropic / ollama
local_endpoint = "http://localhost:11434"  # Ollama 端点

[integrations]
auto_fetch_interval = 20  # 分钟

[privacy]
local_only = false      # 完全离线模式
```

### 5.3 三层 TokenJuice 规则

```
内置规则 (内置 JSON)
  ↓ 按规则 ID 覆盖
用户规则 (~/.config/tokenjuice/rules/*.json)
  ↓ 按规则 ID 覆盖
项目规则 (.tokenjuice/rules/*.json)
```

这种三层设计的好处：不需要重新编译就能调整压缩策略。比如你可以在项目级规则中设置"保留所有中文字符，不剥离 CJK"。

---

## 6. 与你当前架构的对比

| 能力 | OpenHuman | 你的架构 | 差距 |
|------|----------|---------|------|
| Skills/扩展 | QuickJS Skills (3 个官方) | 13 个 MCP 服务器 + 全局 Skills | 你更强 |
| 工作流引擎 | 内置（auto-fetch, subconscious, screen） | 依赖 cron + 手动脚本 | OpenHuman 强 |
| MCP 支持 | 无原生支持（通过 lerim 桥接） | 完整的 MCP 生态 | 你更强 |
| 插件机制 | Skills = 插件 | MCP + Plugins | 你更灵活 |
| 配置文件 | config.toml + TokenJuice JSON | settings.json + .mcp.json + openclaw.json | 复杂度相当 |
| 定时任务 | 内置 cron（auto-fetch 20min, subconscious 5min, screen 5sec） | OpenClaw 有 cron 引擎 | 你的 cron 未充分利用 |
| REPL/CLI | 设计中 (v0.54.0+) | /slash commands | 功能相当 |
| 多模型路由 | 内置自动路由 | 无自动路由 | OpenHuman 强 |

---

## 7. 可借鉴的点

### 7.1 短期可采用的

- **TokenJuice 三层规则**：在 Librarian 的 Canonicalizer 中实现类似的规则覆盖系统。内置规则做 HTML→MD，用户规则保留 CJK，项目规则处理 Excel→JSON。

### 7.2 中期可借鉴的

- **配置文件简化**：你目前 config 散落在 settings.json、.mcp.json、openclaw.json、CLAUDE.md 四个地方。OpenHuman 用 config.toml 一个文件收拢核心配置。长期看可以合并。

- **内置工作流**：目前 auto-fetch 和 subconscious 是你架构完全没有的。替代方案不是重写——而是在 OpenClaw cron 引擎上加几个定时 job，实现类似的被动数据管道。

### 7.3 不需要学的

- **QuickJS Skills**：MCP 是更开放的标准。不需要从 MCP 降级到 QuickJS 沙箱。
- **REPL**：Claude Code 的 /slash 命令已经够好用。

---

## 参考来源

- [OpenHuman GitHub](https://github.com/tinyhumansai/openhuman)
- [Issue #92 — REPL 设计](https://github.com/tinyhumansai/openhuman/issues/92)
- [Issue #145 — Subconscious Loop](https://github.com/tinyhumansai/openhuman/issues/145)
- [Issue #214 — Tool Timeout 配置](https://github.com/tinyhumansai/openhuman/issues/214)
- [OpenHuman Skills 社区仓库](https://github.com/tinyhumansai/openhuman-skills)
- [Lerim MCP 项目](https://data.safetycli.com/packages/pypi/lerim/)
- [TokenJuice CLI 工具](https://github.com/vincentkoc/tokenjuice)
