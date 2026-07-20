# Alice 记忆系统全面改造 — 实施计划

> 版本: v1.0
> 日期: 2026-05-21
> 状态: 待审批
> 依赖: [01-target-architecture.md](./01-target-architecture.md)（目标架构 & 风险评估）

---

## 目录

1. [改造总览](#1-改造总览)
2. [前置条件](#2-前置条件)
3. [目录结构规划](#3-目录结构规划)
4. [Phase 1: 基础管道](#4-phase-1-基础管道)
5. [Phase 2: 摘要引擎](#5-phase-2-摘要引擎)
6. [Phase 3: 潜意识循环](#6-phase-3-潜意识循环)
7. [Phase 4: 高级特性](#7-phase-4-高级特性远期)
8. [文件清单](#8-文件清单)
9. [配置变更清单](#9-配置变更清单)
10. [回滚方案](#10-回滚方案)
11. [验收标准](#11-验收标准)

---

## 1. 改造总览

### 1.1 一句话目标

**Alice 从"被动响应的聊天机器人"升级为"24/7 运行的记忆引擎"**：自动摄入多源数据、自动组织分层摘要、自动发现模式并主动推送给用户。

### 1.2 四个 Phase

```
Phase 1 ──────── Phase 2 ────────── Phase 3 ──────── Phase 4
基础管道          摘要+多源+屏幕感知    潜意识+推送       高级特性
(1-2周)           (2-3周)              (3-4周)           (远期)

管道骨架搭建      Bucket-Seal          态势评估          Topic Tree
微信自动摄入      Claude Haiku 驱动     主动推送          多模型路由
Staging 目录      L0→L1 摘要            扩展 MCP 源       连续上下文
中间格式分流      实体提取              屏幕感知完整版
                  GitHub+Gmail MCP
                  屏幕感知窗口追踪

零 LLM 依赖      引入 Claude API        引入推送          按需推进
零用户感知        后台透明               用户可感知
```

### 1.3 核心设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 运行载体 | Alice (OpenClaw) | 24/7 运行，有 cron 引擎，有微信通道 |
| 写入权限 | Alice 唯一写入，Claude Code 只读 | 消除 SQLite 锁冲突 |
| 管道模式 | 单 cron job 串行 | 各阶段天然依赖，分开跑是错的 |
| LLM 策略 | 全链路 Claude CLI（OpenClaw 后端） | 无需管理本地模型，统一 API 后端 |
| 摘要模型 | Claude Haiku（默认）→ Sonnet（复杂跨源） | 成本最优：Haiku $0.25/$1.25 per MTok |
| 评估模型 | Claude Haiku | 轻量级态势评估，极低延迟和成本 |
| 屏幕分析 | Claude Haiku Vision | 截图描述，图片分析后立即删除 |
| 中间格式 | 按数据源分流 (Threaded JSON / Semantic JSON / Markdown) | 保留语义结构 |
| 解耦方式 | Staging 目录 | Claude Code 不直接写 Librarian |
| 数据源接入 | MCP 优先 + OAuth 补充 | MCP 更开放、更专业 |

---

## 2. 前置条件

### 2.1 必须可用

| 组件 | 用途 | 状态 |
|------|------|------|
| wx-cli | 微信数据库查询 | 已有，确认 CLI 独立可用 |
| Claude CLI (`claude`) | LLM 推理后端（Phase 2+） | OpenClaw 已配置，确认可从脚本调用 |
| Anthropic API (via DeepSeek 代理) | Claude Haiku/Sonnet/Opus 调用 | OpenClaw `models.providers` 已配置 |
| GitHub MCP | GitHub PR/Issue/Notification 拉取 | 已配置（`~/.mcp.json`），确认可用 |
| `E:\Code\FeynmanLibrary\.venv` | Librarian Python API | 已配置，确认可导入 |

### 2.2 Phase 2 前需新增的 MCP 服务器

| MCP 服务器 | 数据源 | 接入方式 | 优先级 |
|-----------|--------|---------|-------|
| Gmail MCP | Gmail 邮件 | Google API / OAuth | 高 |
| Microsoft Graph MCP | Outlook, Teams, OneDrive | Microsoft Graph API | 中 |
| Telegram MCP | Telegram 消息 | Telegram Bot API | 中 |
| Notion MCP | Notion 工作区 | Notion API | 中 |
| WhatsApp MCP | WhatsApp 消息 | WhatsApp Business API | 低 |

### 2.3 必须确认

- [ ] wx-cli 命令行可直接调用（不依赖 Claude Code MCP 包装）
- [ ] `E:\Code\FeynmanLibrary\.venv` 可导入 Librarian 的 Python API
- [ ] Alice cron 引擎正常工作（检查最近 cron 执行日志）
- [ ] Claude CLI 可从命令行独立调用（`claude -p "hello" --model haiku`）
- [ ] DeepSeek 代理 API key 有效（验证 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_BASE_URL`）

### 2.4 必须理解

- Librarian 的 vault 写入机制：直接写 `.md` 到 vault 目录 vs 通过 ingest API
- Alice cron session 的生命周期：24h 保留后状态是否丢失
- wx-cli 的数据模型：消息表结构、时间戳格式、对话 ID 体系
- Claude CLI 的调用方式：`claude -p "prompt" --model haiku --max-tokens 500`

---

## 3. 目录结构规划

### 3.1 新增目录

```
~/.openclaw/
├── memory-pipeline/              ← 新建：管道脚本根目录
│   ├── __init__.py
│   ├── pipeline.py               ← 主入口（cron 调用此文件）
│   ├── config.yaml               ← 管道配置
│   ├── llm.py                    ← Claude CLI 调用封装（统一 LLM 接口）
│   ├── fetch/
│   │   ├── __init__.py
│   │   ├── base.py               ← Fetcher 基类 (cursor 管理)
│   │   ├── wechat.py             ← Phase 1: 微信消息拉取
│   │   ├── staging.py            ← Phase 1: staging 目录读取
│   │   ├── github.py             ← Phase 2: GitHub MCP 拉取
│   │   ├── gmail.py              ← Phase 2: Gmail MCP 拉取
│   │   ├── graph_api.py          ← Phase 3: Outlook/Teams/OneDrive (Microsoft Graph)
│   │   ├── telegram.py           ← Phase 3: Telegram MCP 拉取
│   │   ├── notion.py             ← Phase 3: Notion MCP 拉取
│   │   └── whatsapp.py           ← Phase 3: WhatsApp MCP 拉取
│   ├── canonicalize/
│   │   ├── __init__.py
│   │   ├── router.py             ← 格式检测 + 分流
│   │   ├── wechat_to_json.py     ← Phase 1: 微信 → Threaded JSON
│   │   ├── excel_to_json.py      ← Phase 2: Excel → Semantic JSON
│   │   ├── email_to_json.py      ← Phase 2: 邮件 → JSON + MD
│   │   ├── chat_to_json.py       ← Phase 3: Telegram/WhatsApp → Threaded JSON
│   │   ├── entities.py           ← Phase 2: 实体提取
│   │   └── common.py             ← 共享工具
│   ├── chunk/
│   │   ├── __init__.py
│   │   └── chunker.py            ← 分块 + SHA-256 去重
│   ├── store/
│   │   ├── __init__.py
│   │   └── writer.py             ← 写入 Librarian vault
│   ├── summarize/
│   │   ├── __init__.py
│   │   └── bucket_seal.py        ← Phase 2: Bucket-Seal 引擎 (Claude CLI)
│   ├── evaluate/
│   │   ├── __init__.py
│   │   └── evaluator.py          ← Phase 3: 潜意识评估 (Claude CLI)
│   ├── screen/                    ← 新建：屏幕感知
│   │   ├── __init__.py
│   │   ├── window_tracker.py     ← Phase 2: 活动窗口追踪（零 LLM）
│   │   └── screenshot.py         ← Phase 3: 截图 + Haiku Vision 分析
│   ├── notify/
│   │   ├── __init__.py
│   │   └── push.py               ← Phase 3: 微信/Telegram 推送
│   ├── db/
│   │   └── state.sqlite           ← 管道状态数据库 (cursor、桶计数等)
│   └── tests/
│       ├── test_chunker.py
│       ├── test_wechat_fetch.py
│       └── test_bucket_seal.py
├── staging/                       ← 新建：解耦目录
│   └── .gitkeep
└── openclaw.json                  ← 修改：新增 cron job
```

### 3.2 管道状态数据库 (state.sqlite)

```
表: cursors
  source    TEXT PRIMARY KEY   -- "wechat", "github", "email", "staging"
  position  TEXT               -- 最后摄入位置 (时间戳/消息ID/watermark)
  updated   TEXT               -- ISO 时间戳

表: buckets
  level     TEXT               -- "L0" / "L1" / "L2"
  source    TEXT               -- 数据源或 Topic ID
  count     INTEGER            -- 当前桶内条目数
  token_sum INTEGER            -- 当前桶内 token 总数
  last_seal TEXT               -- 上次封印时间 (NULL 表示从未)

表: hashes
  content_hash TEXT PRIMARY KEY -- SHA-256
  ingested_at TEXT              -- ISO 时间戳
  ttl         TEXT              -- 可选过期时间

表: entities
  name       TEXT               -- 实体名
  type       TEXT               -- "person" / "project" / "topic"
  first_seen TEXT
  last_seen  TEXT
  frequency  INTEGER
```

---

## 4. Phase 1: 基础管道

> **目标**: 微信消息自动流入 Librarian，零手动操作。中间格式按数据源分流（非全转 MD）。
> **时间**: 1-2 周
> **风险**: 极低（不涉及 LLM，不改 Alice 对话逻辑）
> **用户感知**: 无（纯后台运行）

### 4.1 实施步骤

#### Step 1.1: 创建 staging 目录 & 改造 save_session_note

**改动文件**: Claude Code hook / skill 中的 `save_session_note` 调用逻辑

**操作**:
1. 创建 `~/.openclaw/staging/` 目录
2. 修改 `save_session_note` 的目标：不再直接写入 Librarian Memory/ vault，改为写一个 JSON 文件到 `~/.openclaw/staging/`
3. JSON 格式:

```json
{
  "source": "claude-code-session",
  "session_id": "abc123",
  "timestamp": "2026-05-21T10:30:00+08:00",
  "question": "用户提问摘要",
  "conclusion": "完成结果",
  "key_points": ["关键点1", "关键点2"],
  "model_judgement": null,
  "raw_transcript_path": "C:/Users/Kevin/.claude/projects/.../xxx.jsonl"
}
```

**验证**: Claude Code 会话结束后，检查 `~/.openclaw/staging/` 下出现新 JSON 文件。

---

#### Step 1.2: 搭建管道骨架 (pipeline.py + config.yaml)

**新建文件**: `memory-pipeline/pipeline.py`, `memory-pipeline/config.yaml`

**pipeline.py 核心逻辑**:
```python
def run():
    config = load_config()
    fetchers = init_fetchers(config)  # 按配置启用/禁用各数据源

    for fetcher in fetchers:
        items = fetcher.fetch_incremental()
        for item in items:
            canonical = canonicalize(item)
            chunks = chunk(canonical)
            for chunk in chunks:
                write_to_vault(chunk, config.vault_path)
            fetcher.update_cursor(item.position)
```

**config.yaml 结构**:
```yaml
pipeline:
  interval_minutes: 30

fetchers:
  wechat:
    enabled: true
    cursor_key: "wechat"
  staging:
    enabled: true
    staging_dir: "~/.openclaw/staging/"
  github:
    enabled: false   # Phase 3 启用
  email:
    enabled: false   # Phase 3 启用

vaults:
  memory_path: "C:/Users/Kevin/.claude/knowledge/Memory/"
  feynman_path: "F:/FeynmanLibrary/"

dedup:
  method: "sha256"
  db_path: "~/.openclaw/memory-pipeline/db/state.sqlite"

logging:
  level: "INFO"
  file: "~/.openclaw/memory-pipeline/pipeline.log"
```

**验证**: `python pipeline.py` 手动执行一次，检查日志输出 "Pipeline completed: 0 items ingested"。

---

#### Step 1.3: 实现 Fetcher 基类 + 微信拉取

**新建文件**: `memory-pipeline/fetch/base.py`, `memory-pipeline/fetch/wechat.py`, `memory-pipeline/fetch/staging.py`

**Fetcher 基类核心接口**:
```python
class BaseFetcher:
    def fetch_incremental(self) -> list[RawItem]:
        """从 cursor 位置开始拉取增量数据"""
    def update_cursor(self, position: str):
        """更新 cursor"""
    def get_cursor(self) -> str | None:
        """读取上次 cursor"""
```

**微信 Fetcher 实现要点**:
1. 调用 wx-cli 查询自上次 cursor 以来的新消息
2. cursor 使用消息时间戳
3. 每条消息封装为 `RawItem(source="wechat", raw_data=..., timestamp=...)`
4. 过滤掉已删除/撤回的消息（wx-cli 可能标记）

**Staging Fetcher 实现要点**:
1. 扫描 `staging/` 目录下的 JSON 文件
2. 按文件名排序（时间戳）
3. 处理后移动到 `staging/archived/`（或删除）

**验证**: 手动运行 `python pipeline.py`，检查日志显示实际摄入的微信消息数量。

---

#### Step 1.4: 实现 Canonicalizer（微信 → Threaded JSON）

**新建文件**: `memory-pipeline/canonicalize/router.py`, `memory-pipeline/canonicalize/wechat_to_json.py`, `memory-pipeline/canonicalize/common.py`

**分流逻辑**（参考 [02-intermediate-format-best-practices.md](../02-intermediate-format-best-practices.md)）:
```python
CANONICALIZERS = {
    "wechat":          wechat_to_json.convert,      # Threaded JSON
    "telegram":        chat_to_json.convert,         # Threaded JSON
    "whatsapp":        chat_to_json.convert,         # Threaded JSON
    "github_pr":       github_to_json.convert,       # JSON + MD
    "github_issue":    github_to_json.convert,       # JSON + MD
    "gmail":           email_to_json.convert,        # JSON + MD
    "outlook":         email_to_json.convert,        # JSON + MD
    "excel":           excel_to_json.convert,        # Semantic JSON
    "notion":          notion_to_json.convert,       # JSON + MD
    "onedrive_file":   file_to_md.convert,           # Markdown (文档类)
    "screen_capture":  screen_to_json.convert,       # JSON + 描述
    "claude-code-session": session_to_json.convert,  # 结构化摘要 JSON
}
```

**微信 → Threaded JSON 结构**（参考 [02-intermediate-format-best-practices.md](../02-intermediate-format-best-practices.md) 2.5 节）:

```python
{
    "session_id": "wx_group_12345",
    "session_name": "项目组-核心群",
    "type": "group",
    "messages": [
        {
            "id": 1001,
            "timestamp": "2026-05-20T10:00:00+08:00",
            "sender": "wxid_bbb",
            "type": "text",
            "content": "预算表改好了",
            "reply_to": None
        }
    ]
}
```

**验证**: 手动输入一段 wx-cli 返回的原始微信消息，检查 Canonicalizer 输出结构。

---

#### Step 1.5: 实现 Chunker（分块 + 去重）

**新建文件**: `memory-pipeline/chunk/chunker.py`, `memory-pipeline/db/state.sqlite`（建表脚本）

**核心逻辑**:
1. **分块**: 超过 3000 token 的记录切分为多个 chunk，每个 chunk 保留源引用
2. **去重**: SHA-256(content) 查 `hashes` 表，已存在则跳过
3. **幂等**: 同一条微信消息重复拉取（cursor 回退），hash 命中后直接跳过

**Chunk 输出结构**:
```python
{
    "chunk_id": "sha256:abc123",
    "source": "wechat",
    "source_id": "wx_group_12345",
    "index": 0,          # chunk 序号（长内容拆分为多个 chunk）
    "total_chunks": 1,
    "token_count": 245,
    "content": "Threaded JSON 的 markdown 渲染版本",  # 存入 vault 的可读文本
    "structured": {...},  # 原始 Threaded JSON（保留语义）
    "entities": [],       # Phase 2 填充
    "timestamp": "2026-05-20T10:00:00+08:00"
}
```

**验证**: 输入同一段微信对话两次，第二次运行应显示 0 条新摄入（全部 hash 命中）。

---

#### Step 1.6: 实现 Writer（写入 Librarian vault）

**新建文件**: `memory-pipeline/store/writer.py`

**核心逻辑**:
1. 将 chunk 渲染为 markdown 文件，写入对应 vault 的 Memory/ 目录
2. 文件命名: `{source}/{YYYY-MM}/{DD}/{chunk_id}.md`
3. 写入后触发 Librarian 增量索引（调用 Librarian Python API 或写入 marker 文件）

**写入路径示例**:
```
C:/Users/Kevin/.claude/knowledge/Memory/
├── wechat/
│   └── 2026-05/
│       └── 21/
│           ├── sha256-abc123.md
│           └── sha256-def456.md
├── staging/                      # staging 摄入后也到这里
│   └── 2026-05/
│       └── 21/
│           └── session-xyz789.md
└── _index/                       # 管道元数据
    └── ingestion_log.jsonl
```

**验证**: 完整跑通一条微信消息的摄入链路，去 Librarian 确认可以 `hyb_search` 搜到。

---

#### Step 1.7: 配置 Alice cron job

**修改文件**: `~/.openclaw/openclaw.json` → `cron.jobs`

**新增 cron job**:
```json
{
    "id": "memory-pipeline",
    "schedule": "*/30 * * * *",
    "command": "C:/Users/Kevin/AppData/Local/Programs/Python/Python313/python.exe C:/Users/Kevin/.openclaw/memory-pipeline/pipeline.py",
    "timeout": 300000,
    "enabled": true
}
```

**注意**:
- 使用 Python 313（OpenClaw TTS 已经用此版本），避免 Python 版本碎片化
- timeout 5 分钟：正常摄入 1-2 分钟足够，5 分钟留给异常情况
- 不需要改 `maxConcurrentRuns`：只有一个 pipeline job，天然串行

**验证**: 等 30 分钟，检查 `pipeline.log` 是否有 "Pipeline completed"。

---

### 4.2 Phase 1 完成标志

- [ ] `save_session_note` 写入 staging 目录而非直接写 Librarian
- [ ] Alice cron 每 30 分钟自动执行管道
- [ ] 微信新消息在 30 分钟内出现在 Librarian 搜索结果中
- [ ] 同一消息不会重复摄入（SHA-256 去重生效）
- [ ] `pipeline.log` 记录每次执行的统计（拉取数、摄入数、跳过数）
- [ ] 原有功能不受影响：Claude Code 检索正常、Alice 微信对话正常

---

## 5. Phase 2: 摘要引擎 + 多数据源 + 屏幕感知

> **目标**: 自动将碎片记忆压缩为分层摘要（Claude Haiku 驱动），加入实体提取、GitHub/Gmail 数据源、屏幕窗口追踪。
> **时间**: 2-3 周
> **前提**: Phase 1 稳定运行 ≥ 3 天，管道无误
> **风险**: 中（首次引入 Claude API 调用，需确认成本和稳定性）

### 5.1 实施步骤

#### Step 2.1: 实现 Claude CLI 调用封装

**新建文件**: `memory-pipeline/llm.py`

**核心逻辑**:
```python
import subprocess, json

def claude(prompt: str, model: str = "haiku", max_tokens: int = 500,
           temperature: float = 0.3) -> str:
    """通过 Claude CLI 调用 API（走 OpenClaw 配置的 DeepSeek 代理）"""
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", model,
         "--max-tokens", str(max_tokens), "--temperature", str(temperature),
         "--output-format", "text"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise LLMCallError(f"Claude CLI failed: {result.stderr}")
    return result.stdout.strip()

def claude_json(prompt: str, model: str = "haiku", **kwargs) -> dict:
    """调用 Claude 并解析 JSON 输出"""
    json_prompt = f"{prompt}\n\nRespond ONLY with valid JSON, no markdown fences."
    response = claude(json_prompt, model=model, **kwargs)
    # 容错：尝试提取 JSON 段
    return extract_json(response)
```

**降级策略**:
```python
def claude_with_fallback(prompt, model="haiku", fallback=None, **kwargs):
    """Claude API 不可用时返回 fallback 值，不抛异常"""
    try:
        return claude(prompt, model=model, **kwargs)
    except LLMCallError as e:
        logger.warning(f"Claude call failed: {e}")
        return fallback
```

**验证**: `python -c "from llm import claude; print(claude('say hello', model='haiku', max_tokens=20))"`

---

#### Step 2.2: 实现 Bucket-Seal 引擎（Claude CLI 版）

**新建文件**: `memory-pipeline/summarize/bucket_seal.py`

**核心逻辑**:
```python
from llm import claude_json, claude_with_fallback

class BucketSealEngine:
    def check_and_seal(self, level: str = "L0"):
        buckets = self.get_buckets_at_level(level)
        for bucket in buckets:
            if bucket.count >= self.threshold_count or \
               bucket.token_sum >= self.threshold_tokens:
                summary = self.generate_summary(bucket)
                if summary:  # LLM 调用失败时返回 None
                    self.inject_summary(summary, level="L1")
                    self.reset_bucket(bucket)

    def generate_summary(self, bucket):
        """调用 Claude Haiku 生成摘要"""
        prompt = self.build_summary_prompt(bucket.items)
        result = claude_with_fallback(
            prompt, model="haiku", max_tokens=500,
            fallback=None  # 失败时不生成摘要，等下次
        )
        if result is None:
            return None
        return claude_json(result)
```

**摘要 Prompt 模板**（同上，略）

**阈值配置**（config.yaml）:
```yaml
bucket_seal:
  L0:
    count_threshold: 10
    token_threshold: 50000
    model: "haiku"          # Claude Haiku — 便宜快速
  L1:
    count_threshold: 10
    token_threshold: 100000
    model: "sonnet"         # Claude Sonnet — 跨源聚合需更强推理
  cost:
    max_daily_spend: 0.50   # 日预算上限
    budget_reset_hour: 0    # UTC+8 零点重置
```

**验证**: 手动向 L0 桶注入 10 条测试记忆，触发 `check_and_seal`，检查生成的摘要 JSON。

---

#### Step 2.3: 接入 GitHub + Gmail MCP 数据源

**新建文件**: `memory-pipeline/fetch/github.py`, `memory-pipeline/fetch/gmail.py`

**GitHub Fetcher**: 通过已有 GitHub MCP 拉取
- 内容: @mentions、新 Issue/PR、CI 状态变更
- cursor: 最后拉取的 notification ID / updated_at

**Gmail Fetcher**: 通过 Gmail MCP 拉取（Phase 2 前置条件中安装）
- 内容: 新邮件（INBOX）、已发送（SENT）
- cursor: 最后拉取的 internalDate
- 过滤: 仅拉取最近 7 天，避免首次运行拉全量

**config.yaml 更新**:
```yaml
fetchers:
  github:
    enabled: true
    cursor_key: "github_notifications"
    max_per_run: 20
  gmail:
    enabled: true
    cursor_key: "gmail"
    max_per_run: 10
    lookback_days: 7
```

---

#### Step 2.4: 实现屏幕感知 — 窗口追踪

**新建文件**: `memory-pipeline/screen/window_tracker.py`

**核心逻辑**（零 LLM 成本）:
```python
import ctypes, time, json
from ctypes import wintypes

class WindowTracker:
    def get_active_window_info(self) -> dict:
        """获取当前活动窗口信息"""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, title, length + 1)

        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        return {
            "timestamp": datetime.now().isoformat(),
            "window_title": title.value,
            "process_name": self.get_process_name(pid.value),
            "hwnd": hwnd
        }

    def track(self, callback):
        """事件循环：窗口切换时触发回调"""
        last_hwnd = None
        while True:
            info = self.get_active_window_info()
            if info["hwnd"] != last_hwnd:
                callback(info)  # 窗口切换 → 记录日志
                last_hwnd = info["hwnd"]
            time.sleep(1)  # 1 秒轮询（可改为事件驱动）
```

**输出**: 时序化的窗口活动日志，写入 `~/.openclaw/memory-pipeline/db/window_activity.jsonl`

**config.yaml 更新**:
```yaml
screen:
  window_tracking:
    enabled: true
    log_path: "~/.openclaw/memory-pipeline/db/window_activity.jsonl"
    blacklist_apps: []  # 不记录的窗口标题关键词
```

**验证**: 运行 window_tracker 30 秒，切换几个窗口，检查日志输出。

---

#### Step 2.5: 实现实体提取

**新建文件**: `memory-pipeline/canonicalize/entities.py`

**Phase 2 策略**: 先用规则匹配（正则 + 已知实体表），不用 LLM。

```python
class EntityExtractor:
    def __init__(self):
        self.known_people = self.load_people_list()     # 从已有的 contacts/微信通讯录
        self.known_projects = self.load_project_list()  # 从 BOQ/造价项目名提取
        self.patterns = [
            (r"预算|造价|清单|定额", "topic/造价"),
            (r"GitHub|PR|Issue|commit", "topic/开发"),
            (r"微信|Telegram|OpenClaw", "topic/工具"),
        ]

    def extract(self, text: str) -> list[Entity]:
        entities = []
        for pattern, entity_type in self.patterns:
            for match in re.finditer(pattern, text):
                entities.append(Entity(name=match.group(), type=entity_type))
        return entities
```

**已知实体表种子数据** (`config.yaml`):
```yaml
entities:
  seed:
    people:
      - "彭康"
      - "张三"      # 替换为实际微信联系人
    projects:
      - "Librarian"
      - "OpenClaw"
      - "Alice记忆改造"
```

**验证**: 输入一段微信对话文本，检查实体提取输出。

---

#### Step 2.6: 集成到管道

**修改文件**: `pipeline.py`

管道末尾加入:
```python
# Phase 2 新增
if config.bucket_seal.enabled:
    entities = entity_extractor.extract_all(results)
    for entity in entities:
        upsert_entity(entity)

    bucket_seal_engine.check_and_seal(level="L0")
    # L1 仅在 L0 封印后才检查（减少 API 调用）
    if bucket_seal_engine.just_sealed("L0"):
        bucket_seal_engine.check_and_seal(level="L1")

if config.screen.window_tracking.enabled:
    window_tracker.flush_to_file()  # 上一周期的窗口活动日志
```

**验证**: 管道运行 48 小时后（足够积累到阈值），检查 Memory/ 目录下出现摘要文件。

---

### 5.2 Phase 2 完成标志

- [ ] Bucket-Seal L0→L1 摘要自动生成（Claude Haiku 驱动）
- [ ] 摘要文件可通过 Librarian 检索
- [ ] 实体表随摄入逐步增长（person/project/topic）
- [ ] GitHub PR/Issue/Notification 自动流入 Librarian
- [ ] Gmail 新邮件自动流入 Librarian
- [ ] 窗口活动日志持续记录
- [ ] 摘要 API 调用日均成本 <$0.30
- [ ] LLM 调用失败时不阻塞管道（降级为跳过摘要）

---

## 6. Phase 3: 潜意识循环 + 主动推送 + 屏幕感知完整版

> **目标**: 自动发现模式、主动推送通知。用户第一次"感受到"改造的效果。
> **时间**: 3-4 周
> **前提**: Phase 2 稳定运行 ≥ 1 周，Bucket-Seal 摘要积累足够
> **风险**: 中高（引入推送，用户可感知；需调优推送质量避免骚扰）

### 6.1 实施步骤

#### Step 3.1: 实现潜意识评估（Claude CLI 版）

**新建文件**: `memory-pipeline/evaluate/evaluator.py`

**核心逻辑**:
```python
from llm import claude_json, claude_with_fallback

class SubconsciousEvaluator:
    REFLECTION_TYPES = [
        "heat_spike",       # 热度突变
        "cross_source",     # 跨源模式
        "deadline_alert",   # 截止提醒
        "daily_digest",     # 每日摘要
    ]

    def evaluate(self, recent_changes: list) -> EvaluationResult:
        # Step 1: 规则层（快速、零成本）
        rule_result = self.rule_based_check(recent_changes)
        if rule_result.confidence > 0.8:
            return rule_result

        # Step 2: Claude Haiku（仅在规则层不确定时）
        if self.budget_exceeded():
            return EvaluationResult.no_op("budget exceeded")

        prompt = self.build_evaluation_prompt(recent_changes)
        response = claude_with_fallback(
            prompt, model="haiku", max_tokens=200,
            fallback='{"decision":"no_op","reason":"LLM unavailable"}' 
        )
        return self.parse_response(response)
```

**评估 Prompt 模板**:
```
你是一个态势评估助手。以下是过去 30 分钟内记忆系统的变更摘要。

请判断是否需要通知用户。评估维度：
1. 同一话题是否在多个来源中出现？（跨源信号）
2. 是否检测到截止日期或紧急事项？
3. 是否有值得用户关注的异常模式？
4. 窗口活动是否表明用户在切换上下文？

输出 JSON：
{
  "decision": "no_op" | "alert" | "escalate",
  "reason": "简短原因（20字以内）",
  "confidence": 0.0 ~ 1.0,
  "message": "如果 decision=alert，这里写推送内容（50字以内）"
}

近期变更摘要：
{summaries}
```

**规则层预处理**（降级策略：API 不可用时）:
```python
def rule_based_check(self, changes):
    # 规则1: 同一实体在 ≥3 个不同源出现 → alert
    # 规则2: 文本匹配到截止日期模式 → alert  
    # 规则3: 窗口切换到新应用 > 5 分钟 → 记录上下文切换
    # 规则4: 连续 3 次评估都 no-op → 什么都不做
    # 其他: 交给 Claude Haiku 判断
```

---

#### Step 3.2: 实现屏幕感知 — 截图分析

**新建文件**: `memory-pipeline/screen/screenshot.py`

**核心逻辑**:
```python
from llm import claude_json

class ScreenCapture:
    def __init__(self):
        self.blacklist = self.load_blacklist()  # 银行、密码管理器等

    def capture_and_analyze(self) -> dict | None:
        info = window_tracker.get_active_window_info()

        # 黑名单检查
        if any(kw in info["window_title"].lower() for kw in self.blacklist):
            return None

        # 截图
        img_path = self.take_screenshot()  # 调用 Windows API 或 pyautogui

        # Claude Haiku Vision 分析
        result = claude_json(
            prompt="描述这个屏幕截图的内容：可见的应用、正在进行的任务、关键信息。20字以内。",
            model="haiku",
            image_path=img_path,
            max_tokens=100
        )

        # 立即删除原始截图（隐私保护）
        os.remove(img_path)

        return {
            "timestamp": datetime.now().isoformat(),
            "window_title": info["window_title"],
            "process_name": info["process_name"],
            "visual_description": result.get("description"),
            "detected_apps": result.get("apps", []),
            "active_task": result.get("task")
        }
```

**触发策略**（config.yaml）:
```yaml
screen:
  screenshot:
    enabled: true
    trigger_on_window_switch: true    # 窗口切换时截图
    max_interval_seconds: 300         # 最长每 5 分钟截图一次
    blacklist_apps:
      - "银行"
      - "支付宝"
      - "微信支付"
      - "Bitwarden"
      - "1Password"
    delete_after_analysis: true       # 分析后立即删除
```

**验证**: 手动触发一次截图分析，检查输出 JSON 和截图是否已删除。

---

#### Step 3.3: 实现主动推送

**新建文件**: `memory-pipeline/notify/push.py`

**推送通道**: Alice 微信（主）+ Telegram（备用）

```python
def push_to_user(message: str, channel: str = "weixin"):
    """通过 Alice 的消息通道推送给用户"""
    notification_file = Path("~/.openclaw/workspace/pending_notifications.jsonl")
    with open(notification_file, "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "channel": channel,
            "source": "subconscious-loop",
            "priority": "normal"
        }) + "\n")
```

**推送频率限制**:
```yaml
notify:
  max_per_day: 5
  cooldown_minutes: 60
  quiet_hours: "23:00-07:00"
  channels:
    primary: "weixin"
    fallback: "telegram"
```

**推送模板**（根据反射类型）:
```python
TEMPLATES = {
    "heat_spike": "[热度] 话题「{topic}」在{source_count}个源中同时出现",
    "cross_source": "[关联] {description}",
    "deadline_alert": "[截止] {event} — {time_remaining}",
    "daily_digest": "[日报] {date} 共 {count} 条新记忆，{summary}",
}
```

**验证**: 手动写入一条测试通知，确认 Alice 微信能收到并转发。

---

#### Step 3.4: 扩展 MCP 数据源

**新建文件**: `memory-pipeline/fetch/graph_api.py`, `memory-pipeline/fetch/telegram.py`, `memory-pipeline/fetch/notion.py`, `memory-pipeline/fetch/whatsapp.py`

| Fetcher | MCP 服务器 | 拉取内容 | cursor |
|---------|-----------|---------|--------|
| graph_api.py | Microsoft Graph MCP | Outlook 邮件、Teams 消息、OneDrive 文件变更 | lastModifiedDateTime |
| telegram.py | Telegram MCP | 私聊 + 群组消息 | update_id |
| notion.py | Notion MCP | 数据库/页面变更 | last_edited_time |
| whatsapp.py | WhatsApp MCP | 消息 | message_id |

**分阶段启用**（降低风险）:
```yaml
fetchers:
  outlook:
    enabled: true        # Phase 3 首先启用
  telegram:
    enabled: true        # Phase 3 首先启用
  teams:
    enabled: false       # 按需启用
  notion:
    enabled: false       # 按需启用
  whatsapp:
    enabled: false       # 按需启用
  onedrive:
    enabled: false       # 按需启用
```

---

#### Step 3.5: 集成到管道

**修改文件**: `pipeline.py`

管道末尾加入:
```python
# Phase 3 新增
if config.subconscious.enabled:
    if not budget_exceeded():
        recent = get_recent_changes(minutes=30)

        # 加入屏幕上下文
        if config.screen.screenshot.enabled:
            screen_ctx = screen_capture.capture_and_analyze()
            if screen_ctx:
                recent.append(screen_ctx)

        result = evaluator.evaluate(recent)

        if result.decision in ("alert", "escalate"):
            if notify.should_send(result):
                notify.push_to_user(result.message)
                log.info(f"Push sent: {result.reason}")

        if result.decision == "escalate":
            enqueue_escalation(result)
    else:
        log.info(f"Budget exceeded, skipping evaluation")
```

---

### 6.2 Phase 3 完成标志

- [ ] 收到第一条由潜意识循环触发的主动推送
- [ ] 推送内容准确、不骚扰（符合频率限制）
- [ ] 跨源模式检测生效（如 GitHub PR + 微信讨论 + 屏幕上下文同时出现时推送）
- [ ] 屏幕截图分析工作正常，原始图片分析后删除
- [ ] Claude API 不可用时降级为纯规则判断，不报错
- [ ] 推送可追溯：每次推送在日志中记录触发原因和置信度
- [ ] 日均 API 成本 <$0.50（含摘要+评估+屏幕分析）
- [ ] Outlook + Telegram 数据源正常流入

---

## 7. Phase 4: 高级特性（远期）

> **目标**: 多源 Topic Tree 聚合、多模型路由。
> **时间**: 按需推进，不与 Phase 1-3 绑定。
> **前提**: Phase 1-3 稳定运行 ≥ 1 个月。

### 7.1 候选特性

| 特性 | 优先级 | 说明 |
|------|-------|------|
| L2 Topic Tree 跨源聚合 | 中 | 将多个 Source 级摘要按 Topic 自动聚合 |
| 多模型路由 | 中 | 简单任务走 Haiku，复杂分析走 Sonnet/Opus |
| 屏幕感知连续上下文 | 中 | 从"离散截图"升级为"连续活动建模"，跨窗口切换关联上下文 |
| Memory 可视化面板 | 低 | WXDashboard 里加一个记忆健康状态面板 |
| 自动标签补全 | 低 | LLM 对未识别实体进行补充标注 |
| 记忆衰减 | 低 | 超过 N 天未访问的记忆降低检索权重 |

### 7.2 不做

- 四级存储 (Hot/Warm/Cool/Cold) — 记忆量级远不需要
- 本地模型推理 — 全链路 Claude API，不管理本地模型

---

## 8. 文件清单

### 8.1 新建文件（按 Phase）

| Phase | 文件 | 类型 | 说明 |
|-------|------|------|------|
| 1 | `~/.openclaw/memory-pipeline/__init__.py` | Python | 包初始化 |
| 1 | `~/.openclaw/memory-pipeline/pipeline.py` | Python | 管道主入口 |
| 1 | `~/.openclaw/memory-pipeline/config.yaml` | YAML | 管道配置 |
| 1 | `~/.openclaw/memory-pipeline/fetch/__init__.py` | Python | |
| 1 | `~/.openclaw/memory-pipeline/fetch/base.py` | Python | Fetcher 基类 |
| 1 | `~/.openclaw/memory-pipeline/fetch/wechat.py` | Python | 微信拉取 |
| 1 | `~/.openclaw/memory-pipeline/fetch/staging.py` | Python | staging 读取 |
| 1 | `~/.openclaw/memory-pipeline/canonicalize/__init__.py` | Python | |
| 1 | `~/.openclaw/memory-pipeline/canonicalize/router.py` | Python | 格式分流（12 种格式） |
| 1 | `~/.openclaw/memory-pipeline/canonicalize/wechat_to_json.py` | Python | 微信 → Threaded JSON |
| 1 | `~/.openclaw/memory-pipeline/canonicalize/common.py` | Python | 共享工具 |
| 1 | `~/.openclaw/memory-pipeline/chunk/__init__.py` | Python | |
| 1 | `~/.openclaw/memory-pipeline/chunk/chunker.py` | Python | 分块+去重 |
| 1 | `~/.openclaw/memory-pipeline/store/__init__.py` | Python | |
| 1 | `~/.openclaw/memory-pipeline/store/writer.py` | Python | 写入 vault |
| 1 | `~/.openclaw/memory-pipeline/db/schema.sql` | SQL | 建表语句 |
| 1 | `~/.openclaw/staging/.gitkeep` | 空文件 | 目录占位 |
| 2 | `~/.openclaw/memory-pipeline/llm.py` | Python | Claude CLI 调用封装 |
| 2 | `~/.openclaw/memory-pipeline/summarize/__init__.py` | Python | |
| 2 | `~/.openclaw/memory-pipeline/summarize/bucket_seal.py` | Python | Bucket-Seal 引擎（Claude CLI） |
| 2 | `~/.openclaw/memory-pipeline/canonicalize/entities.py` | Python | 实体提取 |
| 2 | `~/.openclaw/memory-pipeline/canonicalize/excel_to_json.py` | Python | Excel → Semantic JSON |
| 2 | `~/.openclaw/memory-pipeline/canonicalize/email_to_json.py` | Python | 邮件 → JSON+MD |
| 2 | `~/.openclaw/memory-pipeline/fetch/github.py` | Python | GitHub MCP 拉取 |
| 2 | `~/.openclaw/memory-pipeline/fetch/gmail.py` | Python | Gmail MCP 拉取 |
| 2 | `~/.openclaw/memory-pipeline/screen/__init__.py` | Python | |
| 2 | `~/.openclaw/memory-pipeline/screen/window_tracker.py` | Python | 窗口追踪（零 LLM） |
| 3 | `~/.openclaw/memory-pipeline/evaluate/__init__.py` | Python | |
| 3 | `~/.openclaw/memory-pipeline/evaluate/evaluator.py` | Python | 潜意识评估（Claude CLI） |
| 3 | `~/.openclaw/memory-pipeline/screen/screenshot.py` | Python | 截图+Vision 分析 |
| 3 | `~/.openclaw/memory-pipeline/notify/__init__.py` | Python | |
| 3 | `~/.openclaw/memory-pipeline/notify/push.py` | Python | 主动推送 |
| 3 | `~/.openclaw/memory-pipeline/fetch/graph_api.py` | Python | Outlook/Teams/OneDrive |
| 3 | `~/.openclaw/memory-pipeline/fetch/telegram.py` | Python | Telegram 拉取 |
| 3 | `~/.openclaw/memory-pipeline/fetch/notion.py` | Python | Notion 拉取 |
| 3 | `~/.openclaw/memory-pipeline/fetch/whatsapp.py` | Python | WhatsApp 拉取 |
| 3 | `~/.openclaw/memory-pipeline/canonicalize/chat_to_json.py` | Python | Telegram/WhatsApp → Threaded JSON |

### 8.2 修改文件

| Phase | 文件 | 改动 |
|-------|------|------|
| 1 | `~/.openclaw/openclaw.json` | `cron.jobs` 新增 memory-pipeline |
| 1 | Claude Code `save_session_note` 逻辑 | 目标改为 staging 目录 |
| 1 | `~/.claude/CLAUDE.md` | 更新记忆架构章节 |
| 2 | `~/.openclaw/openclaw.json` | 可能需加 Claude API 相关 env |
| 3 | `~/.openclaw/openclaw.json` | 可能需加通知通道配置 |

---

## 9. 配置变更清单

### 9.1 openclaw.json 变更

```diff
{
  "cron": {
    "enabled": true,
    "maxConcurrentRuns": 1,        // 不变：单管道不需要并发
+   "jobs": [
+     {
+       "id": "memory-pipeline",
+       "schedule": "7,37 * * * *",    // 每 30 分钟，避开整点和半点高峰
+       "command": "C:/Users/Kevin/AppData/Local/Programs/Python/Python313/python.exe C:/Users/Kevin/.openclaw/memory-pipeline/pipeline.py",
+       "timeout": 300000,             // 5 分钟
+       "enabled": true
+     }
+   ]
  }
}
```

注意：cron 用 `7,37` 而非 `*/30`，避免和 OpenHuman 等系统在整点撞车。

### 9.2 不需要改的

| 配置项 | 原因 |
|--------|------|
| cron.maxConcurrentRuns | 只有一个 pipeline job，串行即可 |
| cron.sessionRetention | 管道脚本是一次性执行，不依赖 session |
| memory-core dreaming | Bucket-Seal 和 dreaming 并行不冲突 |
| active-memory 插件 | 继续用，推送走独立 notify 模块 |

### 9.3 新增 MCP 服务器配置

需要在 `~/.mcp.json` 和 `~/.claude/.mcp.json` 中新增的 MCP 服务器（Phase 2-3）:

| MCP 服务器 | 配置方式 | Phase |
|-----------|---------|-------|
| Gmail | Google API OAuth MCP | 2 |
| Microsoft Graph | Azure AD App + MCP | 3 |
| Telegram | Bot Token MCP | 3 |
| Notion | Notion Integration MCP | 3 |
| WhatsApp | Business API MCP | 3 |

---

## 10. 回滚方案

### 10.1 每个 Phase 的回滚

| Phase | 回滚操作 | 影响 |
|-------|---------|------|
| 1 | ① 移除 cron job ② 恢复 save_session_note 直接写 Librarian ③ staging 目录保留（不删，下次可用） | 退回手动归档 |
| 2 | ① `config.yaml` 中设 `bucket_seal.enabled: false` ② 已有的摘要文件保留不动 | 退回扁平 vault，无摘要 |
| 3 | ① `config.yaml` 中设 `subconscious.enabled: false` ② 推送开关关闭 | 退回被动检索，无推送 |

### 10.2 数据安全

- staging 目录中的文件**不会因回滚丢失**——它们只是 JSON 文件
- 已写入 Librarian 的 vault 文件**不受影响**——回滚只是停止新写入

### 10.3 最坏情况

**如果管道脚本产生错误数据写入 Librarian**:
1. 停止 cron job
2. 检查 `pipeline.log` 定位错误时间点
3. Librarian vault 中的 `.md` 文件按时间目录组织，删除对应时间段的文件
4. 触发 Librarian 重新索引

---

## 11. 验收标准

### 11.1 功能验收

| 验收项 | Phase | 标准 |
|--------|-------|------|
| 微信自动摄入 | 1 | 新消息 30 分钟内可检索 |
| 会话自动归档 | 1 | Claude Code 结束 → staging → Librarian（全自动） |
| 去重 | 1 | 同一消息重复拉取零增量摄入 |
| 中间格式分流 | 1 | 微信→Threaded JSON，Excel→Semantic JSON，邮件→JSON+MD |
| Bucket-Seal 摘要 | 2 | L0 积累到 10 条后自动生成摘要（Claude Haiku） |
| 实体提取 | 2 | 已知人物/项目/话题自动识别 |
| GitHub 数据源 | 2 | PR/Issue/Notification 自动流入 |
| Gmail 数据源 | 2 | 新邮件自动流入 |
| 窗口追踪 | 2 | 活动窗口日志持续记录 |
| 潜意识评估 | 3 | 每 30 分钟运行一次，日志可见 |
| 屏幕截图分析 | 3 | 窗口切换时截图→Haiku Vision→原文删除 |
| 主动推送 | 3 | 检测到跨源模式时推微信 |
| 降级 | 3 | Claude API 不可用时规则层继续工作，不报错 |
| 多 MCP 源 | 3 | Outlook + Telegram 正常流入 |

### 11.2 非功能验收

| 验收项 | 标准 |
|--------|------|
| 管道执行时间 | < 3 分钟（含 LLM 调用） |
| 管道内存占用 | < 500MB（Python 进程） |
| Claude API 调用时间 | 摘要 < 15 秒，评估 < 5 秒，截图分析 < 10 秒 |
| 日志可读性 | 每次执行输出一行摘要统计 |
| 日均 API 成本 | <$0.50（Haiku 为主，按实际调用量计） |
| 截图隐私 | 原始图片分析后立即删除，无残留 |
| 对现有系统影响 | Claude Code 检索延迟无明显增加 |
| Alice 微信对话 | 不受影响（管道在独立进程中运行） |

---

## 附录 A: 关键依赖关系

```
wx-cli (已有)
  └─ Phase 1: wechat.py 调用 wx-cli CLI

Librarian Python API
  └─ Phase 1: writer.py 导入 Librarian 模块写 vault

Claude CLI (已有 — OpenClaw 后端)
  └─ Phase 2: llm.py 封装 claude 命令行调用
  └─ Phase 2: bucket_seal.py 通过 llm.py 调用 Haiku/Sonnet
  └─ Phase 3: evaluator.py 通过 llm.py 调用 Haiku
  └─ Phase 3: screenshot.py 通过 llm.py 调用 Haiku Vision

GitHub MCP (已有)
  └─ Phase 2: github.py 调用 GitHub MCP 拉取 notification/PR/Issue

Gmail MCP (Phase 2 新增)
  └─ Phase 2: gmail.py 调用 Gmail MCP 拉取邮件

Microsoft Graph MCP (Phase 3 新增)
  └─ Phase 3: graph_api.py 调用 Graph MCP 拉取 Outlook/Teams/OneDrive

Telegram MCP (Phase 3 新增)
  └─ Phase 3: telegram.py 调用 Telegram MCP 拉取消息

Notion MCP (Phase 3 新增)
  └─ Phase 3: notion.py 调用 Notion MCP 拉取页面变更

OpenClaw cron (已有)
  └─ Phase 1: openclaw.json 新增 cron job
  └─ Phase 3: push.py 写入 pending_notifications.jsonl

None 新增 pip 依赖（全用现有环境 + stdlib + Windows API）
```

## 附录 B: 与现有 OpenHuman 分析报告的对应

| 本计划的 Phase | 来源报告 | 吸收内容 |
|---------------|---------|---------|
| Phase 1 (基础管道) | 04 报告 §2.1 Neocortex + §4 数据管道 | 自动摄入管道、SHA-256 去重、cursor 增量 |
| Phase 1 (Staging) | 04 报告 §2.1 幂等性保证 | 数据写入前解耦 |
| Phase 1 (中间格式分流) | 02 报告 §2 分类型推荐 + §4 分流架构 | Threaded JSON、Semantic JSON、JSON+MD，不全转 MD |
| Phase 2 (Bucket-Seal) | 04 报告 §3 Memory Tree | 桶积累→LLM 摘要→逐级升级（改用 Claude Haiku） |
| Phase 2 (实体提取) | 04 报告 §4.3 实体识别 | 自动标签 + 跨源关联 |
| Phase 2 (屏幕窗口追踪) | 03 报告 §2.4 Screen Intelligence | 窗口追踪（调整频率：5秒→事件驱动） |
| Phase 2 (GitHub+Gmail) | 01 报告 §2 Composio 118+ OAuth | Gmail、GitHub（MCP 优先，OAuth 补充） |
| Phase 3 (潜意识) | 04 报告 §5 潜意识循环 | 态势评估、六种反思类型、降级策略（改用 Claude Haiku） |
| Phase 3 (屏幕截图) | 03 报告 §2.4 Screen Intelligence | 截图+Vision 分析（调整频率：5秒→窗口切换+5min） |
| Phase 3 (主动推送) | 04 报告 §5.4 安全边界 | 只推送不行动 |
| Phase 3 (多 MCP 源) | 01 报告 §2 OAuth 集成 | Outlook、Teams、Telegram、WhatsApp、Notion、OneDrive |
| 整体架构 | 03 报告 §7 可借鉴的点 | MCP 优于 QuickJS Skills，不照搬 OpenHuman |
