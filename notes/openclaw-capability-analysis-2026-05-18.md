# OpenClaw 能力分析报告 (2026-05-18 更新)

## 架构概览

```
微信/Telegram → OpenClaw Gateway (18789) → claude-cli runtime → DeepSeek API
                                                  ↑
                                           SOUL.md + AGENTS.md
                                           librarian MCP (35 tools)
                                           Claude Code 全部内置工具
```

- **Gateway**: OpenClaw 2026.5.17 (999b634)
- **Agent Runtime**: claude-cli (Claude Code CLI, `--bare` mode)
- **Primary Model**: DeepSeek V4 Flash (1M context)
- **Fallback Model**: DeepSeek V4 Pro (200K context)
- **MCP 直连**: librarian (35 tools, 绕过 bridge 超时)
- **会话持久化**: `--resume` + liveSession stdio
- **进程管理**: Windows Scheduled Task（`openclaw gateway install`）
- **维护 Fork**: `E:\Code\openclaw-fork`（idleTimeoutMs 可配置化）

---

## 一、当前能力

### 1.1 消息通道

| 通道                   | 状态 | 说明                                |
| ---------------------- | ---- | ----------------------------------- |
| 微信 (openclaw-weixin) | 启用 | 群聊 + 私聊，DM 需 pairing          |
| Telegram               | 启用 | botToken 已配置，block streaming 关闭 |

#### 微信通道多模态能力（已确认）

经源码分析 `@tencent-weixin/openclaw-weixin@2.4.3`，微信插件**完整支持**以下消息类型：

| 消息类型 | 接收 | 发送 | 说明                              |
| -------- | :--: | :--: | --------------------------------- |
| TEXT     |  是  |  是  | 文本消息                          |
| IMAGE    |  是  |  是  | 图片（decryptedPicPath → MediaPath） |
| VIDEO    |  是  |  是  | 视频（video/mp4）                 |
| FILE     |  是  |  是  | 文件（application/octet-stream）  |
| VOICE    |  是  |  是  | 语音（audio/wav）                 |

- 接收流程：CDN 下载 → 解密 → 本地临时文件 → dispatch 到 agent pipeline
- 结合 rapid-ocr MCP 可实现图片 OCR 识别
- 结合 pdf2md MCP 可实现 PDF 文档解析

### 1.2 Agent 引擎 (claude-cli runtime)

通过 `--bare` 模式运行 Claude Code CLI，获得完整 agent 能力：

- **内置工具**: Read, Write, Edit, Bash(PowerShell), Glob, Grep, WebSearch, WebFetch, Agent, Task, Skill 等
- **librarian MCP**: hyb_search, vec_search, get_excerpt, open_note, memory_write, save_session_note 等 35 个工具
- **16 个 Claude Code 插件**: superpowers, frontend-design, context7, github, playwright, feature-dev, code-review 等
- **联网能力**: WebSearch + WebFetch（通过 DeepSeek API）
- **文件系统**: C:\, E:\, F:\（含 OneDrive）
- **子 Agent 系统**: Explore, Plan, general-purpose, code-review 等

### 1.3 角色系统 (Alice)

- `SOUL.md` — 角色定义（Alice，彭康的助手）
- `AGENTS.md` — 行为准则和工具使用指令
- 通过 `--append-system-prompt-file` 原生注入
- Fingerprint 机制：修改 SOUL.md/AGENTS.md 自动触发 session 重建
- 全局 CLAUDE.md 行为准则覆盖所有项目

### 1.4 记忆系统 (memory-core + active-memory + dreaming)

#### memory-core 插件（记忆存储与检索）

- **后端**: SQLite + sqlite-vec 向量扩展（当前 0.09 MB）
- **索引**: 对 `MEMORY.md` 和 `memory/*.md` 自动分块、嵌入、建向量索引
- **搜索**: 混合搜索（BM25 + 向量相似度），MMR 去重，时间衰减加权
- **文件监听**: 文件变更自动重新索引
- **工具**: `memory_search`（语义搜索）、`memory_get`（精确读取）

#### active-memory 插件（主动记忆召回）

- 在每次回复前通过 `before_prompt_build` hook 触发
- 运行阻塞式子 agent（超时 15s），搜索相关记忆注入 prompt
- 熔断器保护：连续 3 次超时后冷却 60s
- 可通过 `/active-memory off` 按 session 或全局关闭

**已配置参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `promptStyle` | `balanced` | 平衡召回模式 |
| `allowedChatTypes` | `["direct", "group"]` | 私聊+群聊均生效 |

#### Dreaming 系统（记忆进化）

Cron 驱动的记忆整合流水线，分三个阶段：

| 阶段        | 功能                                                        |
| ----------- | ----------------------------------------------------------- |
| Light Sleep | 回顾近期 daily notes，去重相似条目，写入摘要                |
| REM Sleep   | 跨条目模式识别，发现重复主题和关联                          |
| Deep Sleep  | 按频率/相关性/多样性/时效性评分，将高分记忆提升到 MEMORY.md |

**已配置参数：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `timezone` | `Asia/Bangkok` | 时区 |
| `phases.light.lookbackDays` | `3` | 轻睡回溯窗口 |
| `phases.light.dedupeSimilarity` | `0.85` | 去重相似度阈值 |
| `phases.deep.minScore` | `0.4` | 深睡最低晋升分数 |
| `phases.deep.recencyHalfLifeDays` | `10` | 记忆半衰期 |
| `phases.rem.minPatternStrength` | `0.7` | REM 模式识别阈值 |

**记忆流向**：

```
对话 → Memory Flush → memory/YYYY-MM-DD.md
              → Short-term Recall Tracking
              → Dreaming cron → 评分排序 → 提升到 MEMORY.md
              → 向量索引更新 → 下次对话可检索
```

### 1.5 技能进化系统 (skill-workshop)

技能工作坊已启用，实现 **检测→提案→审批→应用** 闭环：

- **启发式捕获**: 扫描用户消息中的修正模式（"下次记得"、"以后都这样"等）
- **LLM 审查**: 每 15 轮或 8 次工具调用后运行子 agent 分析对话 transcript
- **安全管理**: 7 条安全规则扫描（prompt-injection、密钥泄露等）
- **技能存储**: `skills/{skillName}/SKILL.md`，含 YAML frontmatter

### 1.6 知识库 (librarian MCP)

通过 `--mcp-config` 直连 Claude Code MCP：

- 混合搜索（全文 + 向量）
- 记忆读写与技能草稿管理
- 会话笔记保存/增长/分析
- 知识衰减管理
- 多 vault 支持

### 1.7 会话管理

- `idleTimeoutMs`: 已从默认 10 分钟扩展到 **3600000ms（1 小时）**，通过 OpenClaw 源码修改实现可配置化
- 上下文满时自动 `session_expired` 捕获 + 种子历史重建
- Fingerprint 变更自动重建 session

#### idleTimeoutMs 源码修改

在 `E:\Code\openclaw-fork` 中完成了三层修改：

| 文件 | 修改 |
|------|------|
| `src/config/types.agent-defaults.ts` | `CliBackendConfig` 类型添加 `idleTimeoutMs?: number` |
| `src/config/zod-schema.core.ts` | `CliBackendSchema` 添加 `idleTimeoutMs: z.number().int().min(60000).max(3600000).optional()` |
| `src/agents/cli-runner/claude-live-session.ts` | `createClaudeLiveSession` 读取配置值，`scheduleIdleClose` 使用 `session.idleTimeoutMs` |

### 1.8 消息呈现

- Block streaming: 按 chunk 聚合输出
- Coalesce: idle 500ms 后合并不完整输出
- TTS: edge-tts (zh-TW-HsiaoYuNeural, rate=+30%, pitch=+10Hz)

### 1.9 定时任务（6 个 Cron Job）

| Job | 调度 | 时区 | 说明 |
|-----|------|------|------|
| `maintenance-decay-cleanup` | `0 10 * * *`（每日 10:00） | Asia/Bangkok | librarian decay_cleanup，清理低分条目 |
| `nightly-session-analysis` | `37 10 * * *`（每日 10:37） | Asia/Bangkok | Hermes 会话分析 + 记忆提取 |
| `hermes-pipeline` | `47 11 * * *`（每日 11:47） | Asia/Bangkok | Hermes pipeline 完整执行 |
| `librarian-decay-stale` | `13 */6 * * *`（每 6 小时） | UTC | 衰减重算 + 过期检测（静默） |
| `maintenance-vec-reindex` | `0 14 * * 0`（周日 14:00） | Asia/Bangkok | 向量索引重建 |
| `Memory Dreaming Promotion` | `0 3 * * *`（每日 03:00） | Asia/Bangkok | memory-core 自动管理，记忆晋升 |

- Cron 引擎已启用，支持重试（最多 3 次，指数退避 60s/120s/300s）
- 会话保留 24h
- 所有维护任务已从凌晨调整到白天时段

### 1.10 健康监控

三套 PowerShell 脚本实现基础运维监控：

| 脚本 | 功能 |
|------|------|
| `health-check.ps1` | 6 维度健康检查：端口、API、Cron、错误日志、内存、进程数。支持 `-Json` / `-Quiet`，输出到 `health-logs/` |
| `collect-usage.ps1` | 每日用量采集：`openclaw gateway usage-cost`、cron 状态、session 计数。JSONL + CSV 双格式 |
| `startup-health.ps1` | 启动时健康检查（Gateway LogonTrigger 触发），异常自动写入 `alerts.log` |

---

## 二、已解决的缺陷

| 缺陷 | 状态 | 解决方案 |
|------|:----:|------|
| idleTimeoutMs 硬编码 10min | 已修复 | 源码三层修改 + `openclaw.json` 配置为 3600000ms |
| 进程管理需管理员权限 | 已解决 | `openclaw gateway install` 安装为 Scheduled Task |
| 微信多模态输入支持未知 | 已确认 | 源码分析确认支持 TEXT/IMAGE/VIDEO/FILE/VOICE |
| skill-workshop 未启用 | 已启用 | `plugins.entries.skill-workshop.enabled = true` |
| active-memory 未启用 | 已启用 | `plugins.entries.active-memory.enabled = true` + 参数配置 |
| dreaming 参数未优化 | 已优化 | 时区、阈值、半衰期等 6 项参数已配置 |
| Telegram 通道未启用 | 已启用 | `channels.telegram.enabled = true` |
| Cron 凌晨执行（电脑非 24h） | 已调整 | 5 个手动 job 全部改为白天时段 |
| 无健康监控 | 已建立 | 3 个 PowerShell 脚本覆盖健康检查、用量采集、启动告警 |
| health-check cron 错误检测 bug | 已修复 | `$j.consecutiveErrors` → `$j.state.consecutiveErrors` |
| collect-usage cron 错误计数 bug | 已修复 | 同上 |

---

## 三、可拓展方向

### 3.1 高优先级

#### 3.1.1 Cron 错过窗口自动追补

当前若电脑在 cron 预定时间关机，任务会被跳过（`consecutiveSkipped` 递增）。可在 Gateway 启动时检查所有 cron job 的 `nextRunAtMs`，若已过期则立即执行。

#### 3.1.2 idleTimeoutMs 上游 PR

将 fork 中的三层源码修改提交 PR 到 OpenClaw 上游，消除维护 fork 的必要性。

#### 3.1.3 图片/文件输入落地

微信多模态能力已确认，可实际测试：
- 发送图片 → rapid-ocr MCP 识别文字 → agent 处理
- 发送 PDF → pdf2md MCP 转换 → agent 处理

### 3.2 中优先级

#### 3.2.1 监控与用量看板

- `collect-usage.ps1` 已采集每日用量数据（JSONL + CSV）
- 可接入 Grafana 或简单 HTML dashboard 可视化
- 设置告警：API 错误率阈值、Cron 连续失败通知

#### 3.2.2 多 Agent 并行

利用 OpenClaw `agents` 子系统创建多个隔离 agent：
- `alice` — 主助手（当前 main）
- `coder` — 专注代码任务
- `researcher` — 专注搜索和知识整理

每个 agent 独立 workspace、独立 session、独立 MCP 配置。

#### 3.2.3 Dreaming 调度优化

`Memory Dreaming Promotion` 仍为凌晨 3:00（memory-core 自动管理），与其他已改白天的 job 不一致。可考虑通过 memory-core 配置 `dreaming.frequency` 调整。

### 3.3 低优先级

#### 3.3.1 流式进度展示

- 将 `blockStreamingBreak` 改为更短间隔
- 或启用 streaming mode（`blockStreamingDefault: "off"`）
- 代价: 微信消息刷屏

#### 3.3.2 Active Memory 进一步微调

- `promptStyle`: 可在 `balanced` / `recall-heavy` / `contextual` 间切换实验
- `queryMode`: 当前默认 `"recent"`，可尝试 `"full"` 提高召回率

---

## 四、当前配置摘要

### openclaw.json 关键配置

```jsonc
{
  "gateway": {
    "mode": "local",
    "port": 18789,
    "bind": "loopback",
    "auth": { "mode": "token" }
  },
  "agents": {
    "defaults": {
      "workspace": "~/.openclaw/workspace",
      "model": {
        "primary": "anthropic/claude-sonnet-4-6",
        "fallbacks": ["anthropic/claude-opus-4-7"]
      },
      "sandbox": { "mode": "off" },
      "skills": ["file-librarian"],
      "cliBackends": {
        "claude-cli": {
          "idleTimeoutMs": 3600000  // 1 小时 warm standby
        }
      }
    }
  },
  "channels": {
    "openclaw-weixin": { "enabled": true, "dmPolicy": "pairing" },
    "telegram": { "enabled": true }
  },
  "cron": {
    "enabled": true,
    "maxConcurrentRuns": 1,
    "retry": { "maxAttempts": 3, "backoffMs": [60000, 120000, 300000] }
  },
  "plugins": {
    "entries": {
      "memory-core": {
        "enabled": true,
        "config": {
          "dreaming": {
            "enabled": true,
            "timezone": "Asia/Bangkok",
            "phases": {
              "light": { "lookbackDays": 3, "dedupeSimilarity": 0.85 },
              "deep": { "minScore": 0.4, "recencyHalfLifeDays": 10 },
              "rem": { "minPatternStrength": 0.7 }
            }
          }
        }
      },
      "active-memory": {
        "enabled": true,
        "config": {
          "enabled": true,
          "promptStyle": "balanced",
          "allowedChatTypes": ["direct", "group"]
        }
      },
      "skill-workshop": { "enabled": true }
    }
  }
}
```

### 模型配置

| Provider | 模型 | 用途 |
|----------|------|------|
| anthropic (via DeepSeek API) | `claude-opus-4-7` | fallback |
| anthropic (via DeepSeek API) | `claude-sonnet-4-6` | primary |
| anthropic (via DeepSeek API) | `deepseek-v4-pro` | 备选 |
| anthropic (via DeepSeek API) | `deepseek-v4-flash` | 备选 |
| deepseek (native) | `deepseek-v4-flash` | cron job 专用 |
| deepseek (native) | `deepseek-v4-pro` | 备选 |
| deepseek (native) | `deepseek-chat` | 备选 |

---

## 五、记忆与技能进化能力总结

| 系统 | 能力 | 自动化程度 | 配置状态 |
|------|------|:---:|:---:|
| memory-core | 向量化存储、混合搜索、时间衰减 | 全自动 | 已优化 |
| active-memory | 回复前主动召回相关记忆 | 全自动 | 已配置 |
| Dreaming | 记忆去重、模式识别、评分提升 | cron 自动 | 已配置 |
| skill-workshop | 行为模式检测、技能提案、安全审查 | 启发式+LLM 自动 | 已启用 |
| librarian | 精细知识管理、会话归档、技能草稿 | 手动/半自动 | 运行中 |

---

## 六、维护与更新

### 应用配置变更

```bash
openclaw config set plugins.entries.<plugin>.config.<path> <value>
openclaw gateway restart
```

### 更新 OpenClaw

```bash
npm install -g openclaw@latest
# 若 idleTimeoutMs PR 未合并，需重新应用 fork 修改并构建
cd E:\Code\openclaw-fork
git pull upstream main
pnpm build
pnpm link --global
```

### 健康检查

```bash
powershell -NoProfile -File C:\Users\Kevin\.openclaw\health-check.ps1
powershell -NoProfile -File C:\Users\Kevin\.openclaw\health-check.ps1 -Json
```
