# OpenClaw vs Claude Code 能力差异对比

两者共用 Claude CLI 作为执行引擎，差异在于**外围能力矩阵**——MCP 工具、Skills、通道接入、记忆系统和身份层。

## 总览

| 维度 | OpenClaw (Alice) | Claude Code |
|------|-----------------|-------------|
| 定位 | 桌面 AI 伴侣，多通道接入 | 开发助手，CLI/IDE 直接交互 |
| 执行后端 | Claude CLI（`--bare -p` 模式） | Claude CLI（交互式 / VSCode 扩展） |
| 模型 | `claude-sonnet-4-6`（via DeepSeek 代理） | `deepseek-v4-pro`（opus 槽位） |
| setting-sources | `user`（仅加载 `~/.claude/CLAUDE.md`） | 默认（user + project 两级） |

---

## 1. MCP 工具

这是最大的能力差距——Claude Code 的工具箱是 OpenClaw 的 **5 倍以上**。

| MCP 服务 | OpenClaw | Claude Code | 能力差异 |
|----------|:--------:|:-----------:|---------|
| rapid-ocr | Y | Y | — |
| pdf2md | Y | Y | — |
| wxdb | Y | — | OpenClaw 独有（微信数据库直读，via mcp-sqlite） |
| filesystem | — | Y | C/E/F 盘全量文件读写 |
| shell | — | Y | 任意 shell 命令执行 |
| git | — | Y | Git 全操作 |
| http | — | Y | HTTP 请求/网页抓取 |
| mongodb | — | Y | MongoDB 数据库操作 |
| sqlite | — | Y | SQLite 数据库操作 |
| excel | — | Y | Excel 读写/格式化 |
| playwright | — | Y | 浏览器自动化 |
| ssh | — | Y | SSH 远程连接 |
| docker | — | Y | Docker 容器管理 |
| pandoc | — | Y | 文档格式转换 |
| chrome-devtools | — | Y | Chrome DevTools 性能分析 |
| sequential-thinking | — | Y | 结构化多步推理 |
| serena | — | Y | 代码符号级分析/重构 |

**关键差距**：OpenClaw 没有 shell 和 filesystem MCP，意味着她不能执行命令、不能读写文件系统（除了通过 Claude CLI 内置的 Bash/Read/Write 工具，这些权限受限）。

---

## 2. Skills 生态

| | OpenClaw | Claude Code |
|------|:--------:|:-----------:|
| 数量 | 3 | 20+ |
| 来源 | workspace/skills/ | ~/.claude/skills/ + 插件内置 |

**OpenClaw skills**（3 个）:
- `file-librarian` — 文件管理/知识库操作
- `search-cc-history` — 搜索 Claude Code 会话历史
- `wx-dashboard` — 微信数据面板

**Claude Code 独有 skills**（部分）:
- `pk-boq` / `pk-boq-inquiry` / `pk-boq-quotation` — 造价清单处理
- `material-price-inquiry` — 材料价格查询
- `translation-agent` — 翻译工作流
- `document-ingest` — 文档摄入
- `pptx` / `docx` / `xlsx` — Office 文档处理
- `thinking-in-files` — 大任务文件外化思考
- `wx-cli` / `wx-msg` — 微信数据库 CLI 工具

---

## 3. 通道接入

| 通道 | OpenClaw | Claude Code |
|------|:--------:|:-----------:|
| CLI 交互 | — | Y（原生） |
| VSCode 扩展 | — | Y |
| 微信 | Y（pairing 模式，openclaw-weixin 插件） | — |
| Telegram | Y（已配置但 disabled） | — |

OpenClaw 的核心价值之一是**微信通道**——主人可以通过微信发消息让 Alice 执行任务。Claude Code 没有消息通道，纯 CLI/IDE 交互。

---

## 4. 身份/人设系统

| 维度 | OpenClaw | Claude Code |
|------|---------|-------------|
| 身份层 | 4 层 workspace 文件（SOUL/IDENTITY/USER/AGENTS.md） | 无（即 Claude 默认身份） |
| 名字 | Alice | Claude |
| 人设注入 | bootstrap（每次启动，最多 20000 chars） | 无 |
| 关系系统 | 主人/其他人 二元权限 | 无 |
| TTS 语音 | edge-tts（zh-TW-HsiaoYuNeural，+30% rate） | 无 |

OpenClaw 的身份层是她区别于普通 Claude CLI 实例的关键——她是"角色扮演"，Claude Code 是"工具使用"。

---

## 5. 记忆架构

两者共享 **librarian** 知识库（FTS5 + 向量），但上层记忆不同：

| 记忆层 | OpenClaw | Claude Code |
|--------|---------|-------------|
| 会话级 | `memory/YYYY-MM-DD.md` 每日日志（crash-safe） | SESSION_CONTEXT.md（SessionStart hook 生成） |
| 短期 | ESSENCE.md（7 天精炼块，pipeline 自动生成） | — |
| 长期 | librarian（hyb_search / search_summaries） | librarian（共享同一套基础设施） |
| 自主记忆 | memory-core dreaming（light/deep/rem 三层） | — |
| 上下文注入 | active-memory 插件（每次对话自动检索） | SessionStart hook → resolve-context.cmd |
| 会话归档 | save_session_note + grow_session | staging/cc-{id}.json → StagingFetcher 异步摄入 |

**差异**：OpenClaw 有"自主记忆整理"能力（dreaming 管线），可以在空闲时主动精炼记忆。Claude Code 的归档是被动的——结束对话时将摘要写入 staging，由 memory-pipeline 定时摄入。

---

## 6. 插件系统

| 插件 | OpenClaw | Claude Code |
|------|:--------:|:-----------:|
| memory-core | Y | — |
| active-memory | Y | — |
| skill-workshop | Y | — |
| tts-local-cli | Y | — |
| talk-voice | Y | — |
| frontend-design | — | Y |
| context7 | — | Y |
| github | — | Y |
| playwright | — | Y |
| commit-commands | — | Y |
| feature-dev | — | Y |
| code-review | — | Y |
| code-modernization | — | Y |
| pr-review-toolkit | — | Y |
| hookify | — | Y |
| superpowers | — | Y |
| skill-creator | — | Y |
| chrome-devtools-mcp | — | Y |

OpenClaw 的插件偏"运行时增强"（记忆、TTS、技能创作），Claude Code 的插件偏"开发流程增强"（代码审查、PR 工具包、前端设计）。

---

## 7. 权限与安全

| 维度 | OpenClaw | Claude Code |
|------|---------|-------------|
| 权限模型 | 二元（主人/其他人），AGENTS.md 定义 | settings.json allow/ask/defaultMode |
| 沙箱 | off | 默认 sandbox |
| 文件访问 | 受限于 Claude CLI 内置工具权限 | C/E/F 盘全量（filesystem MCP） |
| 命令执行 | 受限于 Claude CLI 内置 Bash 权限 | shell MCP + Bash（几乎无限制） |
| 破坏性操作 | 需确认，trash > rm | ask 列表控制（rm/del/taskkill 需确认） |

---

## 8. 运行时特性

| 特性 | OpenClaw | Claude Code |
|------|:--------:|:-----------:|
| Cron 定时任务 | Y（完整引擎，含重试/退避） | Y（CronCreate/CronDelete，session 级或 durable） |
| Hooks | — | Y（SessionStart/Stop/PermissionRequest） |
| Thinking mode | 默认 off | 可用 |
| Block streaming | Y（微信通道，合并分块发送） | —（交互式不需要） |
| 多会话恢复 | `--resume {sessionId}` | 原生支持 |
| 音效反馈 | — | Y（Stop/PermissionRequest hook 播放 mp3） |

---

## 9. 实际能力场景对比

| 场景 | OpenClaw | Claude Code |
|------|---------|-------------|
| "帮我写代码" | 受限（无 serena 符号分析，无 git 操作） | 完整支持 |
| "帮我搜微信聊天记录" | Y（wxdb MCP） | Y（wx-cli/wx-msg skills） |
| "帮我查材料价格" | 需手动调用 price_query | Y（material-price-inquiry skill） |
| "帮我处理 BOQ 清单" | — | Y（pk-boq skills） |
| "帮我操作 MongoDB" | — | Y |
| "帮我翻译文档" | — | Y（translation-agent skill） |
| "帮我在微信上回复主人" | Y（核心功能） | — |
| "帮我定时执行任务" | Y（cron engine） | Y（CronCreate） |
| "帮我分析网页性能" | — | Y（chrome-devtools MCP） |
| "帮我 SSH 到服务器" | — | Y |
| "用语音读出回复" | Y（TTS） | — |
| "自动整理记忆" | Y（memory-core dreaming） | — |

---

## 10. 总结

OpenClaw 和 Claude Code 是**互补关系**，不是替代关系：

- **Claude Code 是"全能工具箱"**：16 个 MCP 服务、20+ skills、16 个插件，覆盖开发全流程。适合在 IDE/CLI 中做重度开发工作。
- **OpenClaw 是"随身助手"**：轻量 MCP（3 个）、人设系统、微信通道、自主记忆整理。适合日常碎片化交互和通过手机微信下达任务。

**OpenClaw 最大的限制**是没有 shell/filesystem/git 等核心开发 MCP，这意味着她无法替代 Claude Code 做开发工作。她的强项是"人在外面，用手机微信让 Alice 搜个聊天记录/查个价格/整理邮件"这种轻量场景。

**Claude Code 最大的限制**是没有消息通道——只能坐在电脑前用 CLI 或 IDE 交互。

两者的记忆层通过 librarian 打通——Alice 可以通过 `search-cc-history` skill 读取 Claude Code 的历史会话，形成"CC 干活、Alice 知道"的协作模式。
