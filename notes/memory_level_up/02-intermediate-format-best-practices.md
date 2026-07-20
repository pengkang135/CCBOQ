# 各种资料的最近中间件格式分析

> 研究日期: 2026-05-20
> 核心论点: Markdown 不是万能中间格式。不同数据源应该选择最适合其语义结构的中间格式，在保留信息密度的同时让 LLM 最高效地理解和检索。

---

## 1. 核心原则：中间格式的选择标准

在数据源 → 中间格式 → LLM 这条管道里，中间格式需要满足三个目标：

| 目标 | 说明 |
|------|------|
| **语义保真** | 不丢失数据原有的结构和关系 |
| **Token 效率** | 用最少的 token 传达最多的信息 |
| **可检索性** | 向量检索和全文搜索都能命中关键信息 |

Markdown 对纯文本文档是好的，但对 Excel、数据库、代码仓库等结构化数据，Markdown 会丢失类型信息、公式、关系约束——而这些东西正是 LLM 理解数据的关键。

---

## 2. 分类型推荐的中间格式

### 2.1 电子邮件 → 结构化 Markdown + 元数据 JSON

```
推荐格式: { meta: {...}, thread: [...], body: "markdown" }
```

邮件天然有两层：元数据（发件人、时间、主题、Message-ID）和正文。单纯 Markdown 会丢失线程关系和消息引用。

**推荐结构**：

```json
{
  "message_id": "<msg123@example.com>",
  "in_reply_to": "<msg122@example.com>",
  "from": {"name": "张三", "email": "zhangsan@example.com"},
  "to": ["李四 <lisi@example.com>"],
  "cc": [],
  "date": "2026-05-20T10:30:00+08:00",
  "subject": "Q3 预算评审",
  "thread_position": 3,
  "labels": ["预算", "Q3"],
  "body_md": "## 会议纪要\n\n1. 确认 Q3 预算总额...",
  "attachments": [
    {"name": "预算表.xlsx", "hash": "sha256:abc123", "type": "spreadsheet"}
  ]
}
```

**为什么不是纯 Markdown**：
- 邮件线程（threading）需要通过 `in_reply_to` 和 `references` 头来重建，这是纯 Markdown 做不到的
- 标签/文件夹信息对检索很重要，应作为结构化元数据保留
- 附件引用需要独立追踪（附件应该用自己的中间格式处理）

**Token 效率**：元数据 JSON 约 50-100 token，正文按实际长度计算。相比把 From/To/Date 展开成 Markdown 段落节省约 30%。

---

### 2.2 Excel / 电子表格 → Semantic JSON（带 schema）

```
推荐格式: { schema: {...}, data: [[...]], formulas: {...}, pivot_info: {...} }
```

**核心问题**：Excel 有公式、单元格引用、数据类型、合并单元格、数据验证规则、条件格式。Markdown 表格只能表达"最终显示值"，丢失了计算逻辑。

**推荐结构**：

```json
{
  "sheet_name": "Q3预算",
  "schema": {
    "columns": [
      {"col": "A", "header": "科目", "type": "string"},
      {"col": "B", "header": "预算金额", "type": "currency", "unit": "CNY"},
      {"col": "C", "header": "实际支出", "type": "currency", "unit": "CNY"},
      {"col": "D", "header": "偏差率", "type": "formula", "expression": "=(C-B)/B"}
    ]
  },
  "data": [
    [null, null, null, null],
    ["办公用品", 50000, 48700, -0.026],
    ["差旅费", 120000, 135000, 0.125]
  ],
  "formulas": {
    "D2:D100": "=(C{i}-B{i})/B{i}"
  },
  "named_ranges": {
    "预算总额": "B2:B100",
    "实际总额": "C2:C100"
  },
  "merged_cells": ["A1:D1"],
  "conditional_formatting": [
    {"range": "D2:D100", "rule": ">0.1", "style": "red_fill"}
  ]
}
```

**为什么不是 Markdown 表格**：
- Markdown 表格不区分"显示值"和"公式"，agent 看到 `-2.6%` 但不知道这是 `=(C-B)/B` 算出来的
- 命名范围（Named Range）和跨表引用在 Markdown 中完全丢失
- Schema 级别的列类型信息让 LLM 知道"这列是货币"而不是"这列是数字"
- 数据验证规则（如"预算金额必须 > 0"）是领域约束，应保留

**Token 效率对比**：
- Markdown 表格：`| 科目 | 预算金额 | 实际支出 | 偏差率 |\n| 办公用品 | 50000 | 48700 | -0.026 |` ≈ 30 token/行
- Semantic JSON：同一信息量，但多了公式和类型信息，≈ 40-50 token/行
- 多出的 10-20 token 换来的是 LLM 可以真正"理解"这个表格的计算逻辑

**特殊情况：数据透视表**
```json
{
  "pivot_table": {
    "source": "原始数据!A1:F5000",
    "rows": ["部门", "科目"],
    "columns": ["季度"],
    "values": [{"field": "金额", "aggregate": "sum"}],
    "filters": [{"field": "年份", "value": "2026"}]
  }
}
```
透视表的"语义"在于分组和聚合规则，展开成静态表格会丢失这种结构。

---

### 2.3 日历事件 → iCalendar/JSON 结构化

```
推荐格式: 标准 iCalendar (RFC 5545) 或等效 JSON
```

日历事件的本质是一组结构化字段（时间、地点、参与者、重复规则）。Markdown 段落描述"下周三下午 3 点在会议室 A 开会"对 LLM 可读，但对机器检索效率低。

**推荐结构**（iCal JSON 等效）：

```json
{
  "uid": "event-456@calendar",
  "summary": "Q3 预算评审会",
  "start": "2026-05-22T15:00:00+08:00",
  "end": "2026-05-22T16:00:00+08:00",
  "location": "会议室 A",
  "organizer": "张三",
  "attendees": ["李四", "王五"],
  "rrule": "FREQ=WEEKLY;COUNT=4",
  "description_md": "讨论 Q3 预算分配方案，请提前准备部门预算表。"
}
```

**Token 优化技巧**（来自 TokenJuice 的做法）：
- 时间用 ISO 8601 而非自然语言（`15:00+08:00` vs `下午三点北京时间`）
- 重复规则用 RRULE 而非展开（`FREQ=WEEKLY` vs 列出所有 4 次的具体日期）

---

### 2.4 代码仓库 / PR / Issue → Markdown + 元数据 JSON

```
推荐格式: { meta: {repo, branch, pr_number, ...}, body_md: "...", files: [...] }
```

**这个用 Markdown 是合适的**。代码注释、PR 描述、Issue 讨论本身就是文本。但需要保留的元数据包括：
- 仓库名、分支名、PR 编号
- 文件变更列表（文件名 + diff stat）
- 标签、里程碑、assignee
- CI 状态

```json
{
  "repo": "org/backend",
  "pr_number": 3421,
  "title": "fix: race condition in order processing",
  "author": "张三",
  "status": "open",
  "labels": ["bug", "high-priority"],
  "ci_status": "failing",
  "files_changed": [
    {"path": "src/order/processor.go", "additions": 15, "deletions": 3},
    {"path": "src/order/processor_test.go", "additions": 45, "deletions": 0}
  ],
  "body_md": "## Summary\n\nFixes a race condition when...",
  "review_comments_md": [
    {"reviewer": "李四", "file": "src/order/processor.go:42", "comment": "这里应该用 atomic 操作"}
  ]
}
```

---

### 2.5 聊天记录 → Threaded JSON

```
推荐格式: 每个会话一个 JSON 数组，每条消息带 timestamp + sender + reply_to
```

微信/Slack/Telegram 等即时通讯的核心结构是：
- **线程关系**（谁回复谁）
- **时间线**（对话的节奏和间隔）
- **发送者身份**（群聊中的角色区分）
- **非文本内容**（图片、文件、语音、红包、小程序卡片）

```json
{
  "session_id": "wx_group_12345",
  "session_name": "项目组-核心群",
  "type": "group",
  "participants": [
    {"id": "wxid_aaa", "name": "彭康", "role": "群主"},
    {"id": "wxid_bbb", "name": "张三", "role": "成员"}
  ],
  "messages": [
    {
      "id": 1001,
      "timestamp": "2026-05-20T10:00:00+08:00",
      "sender": "wxid_bbb",
      "type": "text",
      "content": "预算表改好了，大家看看",
      "reply_to": null
    },
    {
      "id": 1002,
      "timestamp": "2026-05-20T10:05:00+08:00",
      "sender": "wxid_bbb",
      "type": "file",
      "file_ref": "files/预算表_v3.xlsx",
      "reply_to": null
    },
    {
      "id": 1003,
      "timestamp": "2026-05-20T10:10:00+08:00",
      "sender": "wxid_aaa",
      "type": "text",
      "content": "第三项的数字是不是不对？",
      "reply_to": 1001
    }
  ]
}
```

**为什么不是 Markdown**：
- 群聊的 reply_to 引用关系是理解讨论脉络的关键
- 发送者身份和时间间隔携带了大量社交信号
- 非文本消息（文件、图片、语音）的引用应该是指向独立资源的指针，不是内联 Markdown

---

### 2.6 PDF / 文档 → Markdown（这个确实是 MD 最合适）

```
推荐格式: Markdown（保留标题层级 + 表格 + 图片引用）
```

PDF 的内容本质上是"带格式的文本流"。标题、段落、列表、表格这些结构 Markdown 都能表达。但需要做到：
- 保留原始页码引用（用于回溯）
- 图片不嵌入 base64，而是引用外部文件路径
- 复杂表格保留合并单元格信息（必要时嵌入 mini-JSON）

---

### 2.7 数据库表 → JSON Schema + 采样数据

```
推荐格式: { schema: [...], sample_rows: [...], stats: {...} }
```

数据库表的"语义"是 schema + 统计特征，不是全量数据。

```json
{
  "table_name": "orders",
  "row_count": 5000000,
  "columns": [
    {"name": "id", "type": "bigint", "nullable": false, "primary_key": true},
    {"name": "user_id", "type": "bigint", "foreign_key": "users.id"},
    {"name": "amount", "type": "decimal(10,2)", "stats": {"min": 0.01, "max": 99999, "p50": 250, "p99": 8900}},
    {"name": "status", "type": "varchar(20)", "distinct_values": ["pending", "paid", "shipped", "cancelled"], "distribution": {"pending": 0.15, "paid": 0.60, "shipped": 0.20, "cancelled": 0.05}}
  ],
  "sample_rows": [
    {"id": 1, "user_id": 42, "amount": 299.00, "status": "paid"}
  ],
  "indexes": ["idx_orders_user_id", "idx_orders_status"],
  "create_table_sql": "CREATE TABLE orders (...)"
}
```

**核心价值**：LLM 通过 schema + 统计分布理解"这个表是什么"，通过 sample rows 理解"数据长什么样"，通过 create_table_sql 理解约束。不需要把 500 万行全喂进去。

---

### 2.8 图片 / 截图 → 描述 JSON + OCR 文本

```
推荐格式: { ocr_text: "...", visual_description: "...", entities: [...], layout: "..." }
```

图片需要两道处理：
1. OCR 提取文字（rapid-ocr 等）
2. 视觉模型生成描述（Gemma 3 vision 等，OpenHuman 正是这么做的）

```json
{
  "source": "screenshot_20260520_103000.png",
  "ocr_text": "项目进度表\n已完成: 12/20\n延期: 3",
  "visual_description": "一个项目管理仪表盘截图，左侧是任务列表，右侧是甘特图",
  "detected_entities": ["项目进度表", "仪表盘"],
  "layout": "two_column",
  "captured_at": "2026-05-20T10:30:00+08:00"
}
```

OpenHuman 的 Screen Intelligence 就采用这个模型：每 5 秒截图 → 本地 Gemma 3 视觉模型 → 结构化摘要。原始图片不离开设备。

---

## 3. 总览表

| 数据类型 | 推荐中间格式 | MD 是否合适 | 核心原因 |
|---------|------------|-----------|---------|
| 电子邮件 | JSON + MD | 部分 | 需要线程关系、标签元数据 |
| Excel/电子表格 | Semantic JSON | **否** | 公式、引用、类型信息丢失 |
| 日历事件 | iCal JSON | 否 | 重复规则、时区、参与者结构化 |
| 代码/PR/Issue | JSON + MD | **是** | 文本为主，少量元数据补充 |
| 聊天记录 | Threaded JSON | 否 | 线程、发送者、非文本消息 |
| PDF/文档 | Markdown | **是** | 最佳场景 |
| 数据库表 | JSON Schema | 否 | Schema > 全量数据 |
| 图片/截图 | JSON + OCR | 否 | 需视觉描述和 OCR 双层 |
| 网页内容 | Markdown | **是** | Readability 提取后的最佳格式 |
| 语音转录 | Markdown | **是** | 本质是文本流 |
| API 响应 | JSON | **是（原生）** | 已经是结构化数据 |

---

## 4. 对 Librarian 架构的建议

当前 Librarian 的 Canonicalizer（规范化器）把所有数据源统一转 Markdown——这是 OpenHuman 的做法。但如本报告所示，对不同数据源应该使用不同的中间格式。

**建议的分流架构**：

```
数据源 → 格式检测器
  ├─ text/plain, text/html, text/markdown → Markdown（保留）
  ├─ application/pdf, image/* → OCR + Vision → Markdown + JSON
  ├─ spreadsheet (xlsx, csv) → Semantic JSON → 存入时生成 Markdown 预览
  ├─ email (eml, mbox) → JSON + MD
  ├─ chat (微信, Telegram) → Threaded JSON
  ├─ calendar (ics, caldav) → iCal JSON
  └─ database (sqlite, pg) → JSON Schema + samples

所有格式统一存入 Librarian vault，同时保留原始文件。
检索时根据格式类型使用不同的 embedding 策略。
```

**渐进实施路径**：
1. 先做 Excel → Semantic JSON（这是你造价工作的核心场景）
2. 再做聊天记录 → Threaded JSON（微信通道有现成数据）
3. 最后做邮件和日历（优先级低，因为你主要通过微信和 Claude Code 交互）

---

## 5. OpenHuman 的 TokenJuice 给你什么启发

TokenJuice 的压缩管道：

```
HTML → Markdown → URL 缩短 → 非 ASCII 剥离 → 去冗余 → 喂 LLM
```

这条管道**只适用于 HTML/网页类数据**。对 Excel 它无能为力——因为你不能把 `=SUM(B2:B100)` 压缩成 Markdown 表格后还保留公式语义。

TokenJuice 的三层规则系统（内置 → 用户 → 项目）值得借鉴：
- **内置规则**：通用转换（HTML→MD）
- **用户规则**：个人偏好（"保留 CJK 字符"）
- **项目规则**：领域特定（"Excel 转 Semantic JSON 时保留公式"）

---

## 参考来源

- [OpenHuman TokenJuice 模块](https://github.com/vincentkoc/tokenjuice)
- Composio 工具目录中各数据类型的 auth 和 API 格式
- iCalendar RFC 5545 标准
- OpenHuman README — Canonicalizer 和 Chunker 设计
