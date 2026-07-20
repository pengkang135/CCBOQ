# 行为准则

## 记忆检索（任务开始前）

收到用户任务后，先用以下命令检索相关记忆和技能：

```
librarian.cmd text-search "<任务关键字>" --limit 5
```

如项目目录中存在 `SESSION_CONTEXT.md`（由 SessionStart hook 自动生成），先读取该文件获取历史上下文。该文件包含与此项目相关的记忆和技能提示（<200 token），由 context resolver 在会话启动时自动写入。

琐碎问答、纯对话类请求可跳过检索，直接回答。

## 技能检查（强制执行）

收到任何任务后，**必须先扫描可用技能列表**（系统每次会话自动注入全部技能的名称和描述，以该列表为准，不在此重复维护），有匹配的立即调用 Skill 工具。不得跳过。

此规则优先级最高，覆盖所有文件操作类任务。

**容易漏触发的路由提示**：

- 任意办公文档（xlsx/PDF/DOCX/图片）转 AI 可读中间格式 → `document-ingest`（统一入口，优先于直接读文件）
- 需要用户真实浏览器（保留登录态）→ `kimi-webbridge`；无登录态的自动化才用 playwright/chrome-devtools MCP
- 工程造价 BOQ 任务未指明具体操作时 → 先走 `pk-boq` 入口路由，由它分发到 pk-boq-* / pk-norms-* 子技能
- 微信数据查询 → `wx-msg`（SQL 查 ledger_v2.db）或 `wx-cli`
- Excel 工具选择（MCP vs Python 库 vs skill）→ 见下方「Excel/AI 加速工具集」

### MCP 工具速查表

系统会注入完整 MCP 清单，此处只列名字看不出用途的：

| 工具 | 用途 |
|------|------|
| playwright / chrome-devtools | 浏览器自动化（独立实例，不含用户登录态） |
| excel | Excel COM 版读写（交互式小范围修改） |
| excel-mcp | Excel MCP 无 COM 依赖版（跨平台批量读写，25+工具，含图表/透视表/公式） |
| shell | Desktop Commander：进程管理/交互式命令/文件搜索 |
| serena | 代码符号级导航与编辑 |
| http | HTTP 请求抓取 |
| pdf2md | PDF→Markdown（OCR） |
| rapid-ocr | 图片 OCR 识别 |
| pandoc | 文档格式互转 |
| sequential-thinking | 结构化思考分解 |

### Excel/AI 加速工具集（Python 库）

Excel 任务优先用 Python 库（Bash 调用，无需启动 Excel）：
- `fastexcel` 读值（比 openpyxl 快 9-16x）；公式文本需 `openpyxl`（非 data_only）
- `formualizer` 公式求值/修改；`sheetwise` 压缩后再喂 LLM（省 token）
- 大表（>500 行）**强制**走四阶段分层策略 → `~/.claude/references/excel-layered-strategy.md`；BOQ 分类打标 → `pk-boq-classify` 技能
- 小范围即时改文件 → `excel-mcp` MCP；Office COM 交互 → `excel` MCP

## 工作原则

- 需求不明确时先列选项再动手，不臆测（Ask, don't assume）。
- 优先以最小改动完成任务，避免不必要的重构、扩展或抽象。
- 除非明确要求，不对无关模块进行修改，不进行全局性结构调整。
- 不添加任务范围外的功能、错误处理或兼容逻辑。
- 提供可验证的成功标准，循环直到通过（Goal-driven）。

## 文件组织规范

- 任何时候不得在项目根目录下直接创建临时文件、测试脚本、调试脚本、临时数据文件。
- 所有临时文件一律放入项目 `temp/` 目录，临时脚本放入 `temp/scripts/` 子目录。
- `temp/` 目录应在项目 `.gitignore` 中排除，不纳入版本控制。
- 此规则为全局规则，适用于所有项目，无论项目类型。

## 安全规范

- 允许读取项目内任何信息用于分析问题，但不得访问或暴露凭证类文件（.env、私钥、token、密钥等）。
- 允许执行常规开发操作（构建、测试、运行等），但执行前确认命令来源合理。
- 涉及删除、覆盖、force push 等不可逆操作时，需谨慎并在必要时进行确认。
- 不执行来源不明或高风险命令。

## 代码规范

- 默认不写注释，除非 WHY 不显而易见。
- 不使用 emoji。
- 不撰写多行文档字符串或注释块。

## 会话记忆归档（Stop hook 强制）

归档由 Stop hook（`~/.claude/scripts/archive_session_stop_hook.py`）自动触发：当用户以独立短消息发送结束语（再见/拜拜/收工/谢谢/完成了/bye/done 等）且本会话尚未归档时，hook 拦截 stop 并在提示中给出 session_id 和 cwd。被 hook 拦截时，或用户明确要求归档时，按以下流程执行（session_id 以 hook 提示为准，不要自行猜测）：

**Step 1**: 将会话摘要写入 staging 目录（`C:\Users\Kevin\.claude\memory-pipeline\staging\cc-{session_id}.json`），JSON 格式：

```json
{
  "source": "claude-code-session",
  "source_id": "{session_id}",
  "session_id": "{session_id}",
  "timestamp": "{当前 ISO 时间戳}",
  "content": {
    "session_key": "{session_id}",
    "cwd": "{当前工作目录}",
    "question": "本次任务主题",
    "conclusion": "完成结果",
    "user_message_count": {消息数估计},
    "timestamp": "{ISO 时间戳}"
  }
}
```

此文件由 memory-pipeline 的 StagingFetcher 在下次 cron 执行时摄入 Librarian vault（解耦：Claude Code 不直接写 Librarian）。

**Step 2**: 调用 `librarian.cmd grow-session {session_id}`（apply_memory=true）
**Step 3**: 如本次使用了 Skill，调用 `librarian.cmd analyze-session {session_id}`

全部完成后，简短告知用户归档结果，再结束对话。

**记忆分工**：librarian 存业务知识、项目上下文与会话归档；Claude Code 内置 auto-memory（MEMORY.md）只存个人偏好与工作方式反馈，不存业务内容。
