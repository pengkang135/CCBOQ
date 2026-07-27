# 记忆系统架构与文件布局

## 总体架构：三根支柱

```
┌──────────────────────────────────────────────────────────────────┐
│  支柱 A: OpenClaw          支柱 B: librarian         支柱 C: Hermes │
│  (接入层)                  (搜索引擎+存储)           (记忆引擎)     │
│                                                                  │
│  手机微信 → Gateway → Claude Code → librarian MCP → SQLite       │
│                              ↑                        ↓          │
│                         CLAUDE.md 归档指令          memory_entries│
│                                                       ↓          │
│                      Hermes 夜间分析 ←────────── sessions 表      │
└──────────────────────────────────────────────────────────────────┘
```

### 支柱 A: OpenClaw — 消息接入网关

OpenClaw Gateway 是 24 渠道消息网关，负责把手机微信/TG 的消息转发给 Claude Code。

**角色**: 接入层，所有外部消息的统一入口

**核心能力**:
- 微信 IM Bot 接入（`@tencent-weixin/openclaw-weixin` 插件）
- 内置 Cron 定时任务调度
- 会话管理 / DM 安全配对
- Claude Code 作为推理后端

**运行方式**: Windows 计划任务 `OpenClawGateway`（开机自启），listening on `127.0.0.1:18789`

### 支柱 B: librarian — 搜索引擎 + 知识存储

librarian 是 MCP 服务器，基于 SQLite FTS5 + 向量索引提供全文和语义搜索。存储所有记忆、文档摘要、session 记录。

**角色**: 搜索引擎 + 持久化存储。三支柱中唯一直接读写数据库的系统。

**核心能力**:
- FTS5 全文搜索（`search_summaries`）
- 向量语义搜索（`vec_search`、`hyb_search`）
- 时间衰减排序（Ebbinghaus 遗忘曲线变体）
- 多 Vault 知识库管理
- 记忆读写（`memory_write`、`memory_list`）
- 会话分析（`analyze_session`、`grow_session`、`suggest_memories`）
- 文档摄入/索引（`ingest_source`、`ingest_inbox`）

### 支柱 C: Hermes — 记忆进化引擎

Hermes 是夜间批处理 Pipeline，负责从 session 中提炼结构化记忆，实现三层记忆模型。

**角色**: 记忆引擎，自进化飞轮的核心

**核心能力**:
- 三层记忆: 工作记忆 → 情节记忆 → 语义记忆
- 夜间深度分析 session 数据
- 自动记忆策划（去重、合并、衰减）
- Skill 改进建议生成

**运行方式**: OpenClaw Cron `hermes-pipeline`（每日 3:47 AM），调用 `hermes.py --apply`

---

## 文件布局

### 1. librarian MCP 服务器代码

代码与数据分离架构（2026-05-17 迁移完成）：

```
# === 代码（全局位置，可跨项目复用） ===
C:\Users\Kevin\claude-code-config\mcp-servers\librarian\  ← 配置模板（Git 版本控制）
│   ├── requirements.txt
│   └── librarian_mcp\
│       ├── server.py               ← MCP tool 定义（@mcp.tool() 装饰器）
│       ├── service.py              ← 业务逻辑实现（搜索、衰减、记忆策划等）
│       ├── config.py               ← 配置管理（VAULT_ROOT 指向 F:\FeynmanLibrary）
│       ├── cli.py                  ← CLI 桥接（9 个命令组，供 OpenClaw exec 调用）
│       ├── hermes.py               ← Hermes 夜间分析脚本
│       ├── embedding.py            ← BGE 模型加载 + 向量编码
│       ├── vector_index.py         ← sqlite-vec 向量索引
│       ├── ingest.py               ← 文档摄入/索引
│       ├── maintenance.py          ← 维护工具（衰减、过期检测）
│       ├── price_extract.py        ← 价格数据提取
│       ├── models.py               ← Pydantic 数据模型
│       └── scripts/                ← 独立脚本
│           ├── vec_batch_reindex.py
│           ├── test_vec_search.py
│           └── extract_pdf_tables.py
│
C:\Users\Kevin\.claude\mcp-servers\librarian\  ← 运行时部署（setup.ps1 同步）
│   ├── .venv\                      ← Python 虚拟环境（sentence-transformers + torch + sqlite-vec）
│   ├── requirements.txt
│   └── librarian_mcp\              ← 代码副本（与 claude-code-config 同步）

# === 数据（保留在原 FeynmanLibrary 项目） ===
F:\FeynmanLibrary\
├── .library\
│   ├── library.db              ← SQLite 主数据库（FTS5 + 向量索引）
│   └── vaults.json             ← Vault 注册表
├── Knowledge\                   ← Feynman vault 的 Markdown 知识文件
├── DocWork\                     ← 文档工作区（PDF/DOCX 源文件 + 提取稿）
└── Librarian\
    ├── Memory\                  ← memory_entries 的 Markdown 文件
    │   ├── MEMORY_INDEX.md      ← 记忆索引
    │   └── mem-*.md             ← 单条记忆文件
    ├── SessionNotes\            ← session 笔记摘要
    └── AgentSkills\             ← 已审查通过的 Skills
```

### 2. OpenClaw Gateway

```
C:\Users\Kevin\.openclaw\
├── openclaw.json               ← Gateway 主配置（MCP、agent、cron、provider）
├── cron\
│   ├── jobs.json               ← Cron 任务定义（5 个 job）
│   └── jobs-state.json         ← Cron 执行状态（耗时、成功/失败）
├── agents\                      ← Agent 定义
├── devices\                     ← 已配对设备
├── logs\                        ← Gateway 运行日志
└── workspace\
    └── skills\file-librarian\  ← file-librarian Skill（搜索策略指令）
        └── SKILL.md
```

### 3. Claude Code 配置（触发层）

```
C:\Users\Kevin\.claude\
├── CLAUDE.md                   ← 全局行为准则 + 会话记忆归档指令
├── settings.json               ← 权限/hooks/env/插件/模型
└── knowledge\                   ← 共享知识目录（Kevin Knowledge Hub vault）
    ├── sessions\                ← Session 摘要存放目录（当前为空）
    └── claude-code-settings-guide.md
```

### 4. 配置模板仓库

```
C:\Users\Kevin\claude-code-config\
├── mcp-servers\
│   └── librarian\                     ← librarian MCP 代码模板（Git 版本控制）
│       ├── requirements.txt
│       └── librarian_mcp\             ← 17 个 .py 文件 + scripts/
├── note\
│   ├── memory-system-improvement-plan.md   ← 原始改进计划
│   ├── memory-system-architecture.md       ← 本文档
│   └── review\                             ← 各次进度审核报告
│       ├── progress-review-2026-05-15.md
│       ├── progress-review-2026-05-16.md
│       └── progress-review-2026-05-17.md
├── settings.json.template
├── settings.local.json
└── .mcp.json
```

---

## 数据流

### 日常使用（白天）

```
手机微信发消息
    → OpenClaw Gateway (port 18789)
    → Agent 路由到 Claude Code session
    → Claude Code 推理
    → 调用 librarian MCP tool（search_summaries / get_excerpt / memory_list）
    → SQLite FTS5 搜索
    → 结果返回微信

电脑 Claude Code 直接使用
    → Claude Code 内置 MCP 客户端
    → 直接调用 librarian MCP tool
    → 同一 SQLite 数据库（跨渠道记忆共享）
```

### 对话归档（对话结束时）

```
对话结束（用户说"再见"/"谢谢"/"好的" 等）
    → CLAUDE.md 归档指令触发
    → Step 1: save_session_note → 写入 session 摘要到 librarian
    → Step 2: grow_session (apply_memory=true) → 自动策划记忆
    → Step 3: analyze_session (如果使用了 Skill) → 分析改进空间
```

### 夜间维护（凌晨）

```
1. 02:37 AM — nightly-session-analysis
   → 扫描 sessions 目录，执行 analyze + suggest + apply

2. 03:00 AM — maintenance-decay-cleanup
   → decay_cleanup(dry_run=false)，清理低于阈值的条目

3. 03:47 AM — hermes-pipeline
   → hermes.py --apply，从 session 提炼结构化记忆

4. 每 6 小时 :13 — librarian-decay-stale
   → recalc_decay(target=all) + check_stale

5. 每周日 04:00 AM — maintenance-vec-reindex
   → vec_reindex(target="all")，重建向量索引
```

---

## 两个 Vault

| Vault | 路径 | 类型 | 用途 |
|--------|------|------|------|
| Feynman Knowledge Vault | `F:\FeynmanLibrary` | knowledge, prices, sessions | 工程技术和造价领域知识库 |
| Kevin Knowledge Hub | `C:\Users\Kevin\.claude\knowledge` | knowledge, sessions | 个人知识库聚合目录 |

---

## 关键技术参数

| 参数 | 值 | 说明 |
|------|------|------|
| 向量维度 | 512 | sqlite-vec 索引 |
| 衰减公式 | `e^(-λ × days) × (1 + α × log(1 + access_count))` | λ=0.01, α=0.3 |
| 数据库 | SQLite `F:\FeynmanLibrary\.library\library.db` | 单文件 |
| 搜索引擎 | FTS5 (全文) + sqlite-vec (语义) | 混合搜索 |
| Cron 调度器 | OpenClaw 内置 Cron | 非 CC CronCreate |
| MCP 传输 | stdio（CC 直接连接，指向 `~/.claude/mcp-servers/librarian/.venv`）/ exec+cli.py（OpenClaw Cron 桥接） | 双路径 |
| librarn MCP 位置 | 代码: `~/.claude/mcp-servers/librarian/`，数据: `F:\FeynmanLibrary\` | 代码/数据分离 |
