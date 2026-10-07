# 行为准则

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

系统会注入完整 MCP 清单，此处只列名字看不出用途的。以每次会话实际注入的 MCP 清单为准，本表可能滞后：

| 工具 | 用途 |
|------|------|
| playwright / chrome-devtools | 浏览器自动化（独立实例，不含用户登录态） |
| excel | ~~Excel COM 版读写~~ **禁用**（COM，会抢用户的 Excel，见下方硬前置） |
| fastexcel | Excel 快速读值 MCP（本地脚本，读数据首选） |
| excel-mcp | Excel MCP 无 COM 依赖版（跨平台批量读写，25+工具，含图表/透视表/公式） |
| shell | Desktop Commander：进程管理/交互式命令/文件搜索 |
| serena | 代码符号级导航与编辑 |
| http | HTTP 请求抓取 |
| pdf2md | PDF→Markdown（OCR） |
| rapid-ocr | 图片 OCR 识别 |
| pandoc | 文档格式互转（anydoc 替代，更快更准，14 格式） |
| sequential-thinking | 结构化思考分解 |

### Excel/AI 加速工具集（Python 库）

> **硬前置：禁止用 Excel COM 处理表格。任何时候、任何项目、任何技能都不准。**
> 不准 `win32com.client.Dispatch/DispatchEx("Excel.Application")`，不准 COM 版 `excel` MCP，
> 不准任何间接拉起 `EXCEL.EXE` 的做法 —— 读、写、上色、插行、刷新、校验，一律不行。
>
> 理由是它跟用户抢 Excel：`Dispatch` 会附着到用户正开着的实例，脚本一跑就接管用户手里的表、
> 弹窗、抢焦点（`Visible = False` 对已有实例还无效）；用户得先关文件、等脚本、再打开，
> 一条命令的事变成来回操作；约 8 秒固定启动开销，比纯脚本还慢；异常退出残留 `EXCEL.EXE`
> 占着文件；headless / cron 直接跑不了。**明明有更好的工具，没有任何理由起 Excel。**
>
> 替代：读值 `fastexcel`；公式文本和保留格式改单元格 `openpyxl`；新建 `xlsxwriter`；
> 插行插列、搬 sheet、透视表、定义名称、清部件走 **zip + XML 层**（其余部件字节级复制）；
> 让透视表出数写 `refreshOnLoad="1"`，用户打开时 Excel 自己刷新；验证产物用脚本核对，
> 不要开 Excel 看。范例：`~/.claude/skills/pk-boq-workbench/scripts/build_workbook.py`
> （套模板、插列、写公式、带透视表，一次 Excel 都没起）、
> `~/.claude/skills/pk-boq/scripts/xlsx_rowops.py`（插行 + 公式行引用平移 + 整行上色）。
>
> 「openpyxl 的 `insert_rows` 会破坏公式」不是用 COM 的理由 —— 解法是 zip/XML 层插行后
> 自己平移行号。唯一例外：用户明确说"用 Excel 打开确认一下"，此时必须 `DispatchEx`
> （独立实例，不碰用户的文件）+ `Visible = False` + `finally` 里 `Quit()`，做完即退。

> **硬前置：读 Excel 数据值 → fastexcel。禁止先用 openpyxl 读值。**
> 违反此条会导致 9-16x 的性能劣化，用户已多次指出，不得再犯。

> **硬前置：任何 Excel 动手前先读前 100 行过一眼**（列出 sheet 名 + 每个目标 sheet dump 前 100 行），看清表头行号、列含义、中英文分列、合并单元格、隐藏行再动手。禁止只抽样几行就下结论、禁止没看结构就上复杂工具。

Excel 任务优先用 Python 库（Bash 调用，无需启动 Excel）：
- `fastexcel` 读值（比 openpyxl 快 9-16x）；**仅公式文本/写回保留格式用 `openpyxl`**
- `anydoc` (firecrawl-anydoc) 文档→Markdown 转换（Word/PPT/RTF/EPUB 等 14 格式），~5ms，比 pandoc 快 20x、质量更高，跨项目通用
- `formualizer` 公式求值/修改；`sheetwise` 压缩后再喂 LLM（省 token）
- 大表（>500 行）**强制**走数据前端（四阶段）→ `pk-boq-ai-team` 技能；完整分层策略见 `~/.claude/references/excel-layered-strategy.md`；BOQ 清单分类 → `pk-boq-classify`（只读清单产出 classification.json），建报价工作台/套模板/插列 → `pk-boq-workbench`（`--classification` 把分类值一并写入）。**顺序是先分类后建台** —— 透视表按分类列汇总，分类空着刷出来只有 (空白)
- 小范围即时改文件 → `excel-mcp` MCP（无 COM 依赖）；行级插入/上色 → `pk-boq/scripts/xlsx_rowops.py`
- `excel` MCP 是 COM 版，**按上方硬前置禁用**，不要因为"只改一格"就破例

### PDF / Word 文档工具选择

> **硬前置：先判载体、再选工具。禁止手写行列坐标 / 逐行切分的解析器** —— 那是最后手段，写之前先说明为什么下面全都用不了。

- **有文本层 + 有线表格** → 首选 `pdfplumber.extract_tables(table_settings={'vertical_strategy':'lines','horizontal_strategy':'lines'})`，列按表头直接对齐。**不要用 `pypdf/fitz` 的 `extract_text().split('\n')` 硬切** —— 那只在一行一价的巧合版式上碰对；有表格线的会串行。实测同一份 HSR：按行切 156 条、抽表 495 条。
- **有文本层、无线表格 / 版式怪** → `table_settings={'vertical_strategy':'text'}`；仍不行 → `pdf2docx` 转 DOCX 后 `python-docx` 读 `doc.tables`；或 PyMuPDF `get_text('blocks')` 按块坐标聚列。
- **扫描件 / 图片** → `pk-boq-quotation` 的 `scan_price_table.py`（rapidocr + paddleocr 双引擎 + 算术闭合三档采信）。单一 OCR 读数不得直接入库。
- **Word** → `python-docx` 读 `doc.tables`（不转 Markdown 再解析）。
- **Excel** → 见上一节。
- **多格式同内容**：先定「哪份是数据源」，其余只作佐证，不要两份都全量抽。
- 本机已装：`pdfplumber`（含 `extract_tables`）、`PyMuPDF(fitz)`、`pypdf`、`pdfminer.six`、`pypdfium2`、`pdf2docx`、`pdf2image`、`paddleocr`、`rapidocr-onnxruntime`、`python-docx`。未装：`camelot`/`tabula`/`docling`/`marker`/`MinerU`/`unstructured`（要用先装）。

## 可用数据库

- **CostSpread 造价库**：`mongodb://127.0.0.1:37117/cost_data_platform` → `rates` 集合，海外人材机报价（泰国为主），1,000+ 条。使用前需启动 Rancher Desktop。
- **Norms-AI 定额库**（SQLite）：`E:\Code\Norms-AI\db\`，企业定额 A/C 册为主引用源，详见 `db/INDEX.md`。清单套价、定额查询直接用 sqlite MCP 查。
- **微信消息库**：SQLite `F:\WXDashboard\data\ledger_v2.db`，走 `wx-msg` 技能（`mcp__wxdb__*`，非 sqlite MCP）。

## 个人知识库

`F:\BaiduSyncdisk\30 知识库\`：关于我的事实（工作、个人与家庭、健康、投资、技术与工具环境），人工可维护的 Markdown。
- 触发：问到关于我的人/公司/项目背景/资质/健康/投资持仓/本机环境，任务需要长期背景，或我说"知识库""写进知识库"。
- 触发后先读该目录下 `AGENTS.md`（读写规则）再读 `索引.md`，不要遍历全库。
- 关于事实的纠正写进知识库；关于你该怎么做事的纠正写进本文件或技能。

## 工作原则

- **多Agent任务规划**：涉及多个 Agent 协作时，先调 `pk-boq-ai-team` 技能（已合并原 multi-agent-collaboration 速查手册 + team_pipeline 分层流水线 + pk-boq-strategy 数据前端），按决策表选拓扑（星型/流水线/采集器/网状/链式/树形/8阶段）。核心教训：不同环节用不同模型把关（设计 Opus / 执行 Haiku / 审核 Sonnet / 仲裁 Opus），换模型=独立信号，防 AI 自己说服自己。
- 需求不明确时先列选项再动手，不臆测（Ask, don't assume）。
- 优先以最小改动完成任务，避免不必要的重构、扩展或抽象。
- 除非明确要求，不对无关模块进行修改，不进行全局性结构调整。
- 不添加任务范围外的功能、错误处理或兼容逻辑。
- 提供可验证的成功标准，循环直到通过（Goal-driven）。
- 需求明确但方案不合理、或存在更简单路径时，先说出异议再执行，不默默照办。
- 修改已有文件时匹配原有的用词、排版和代码风格，不按自身偏好重排。
- 只清理自己操作造成的混乱；无关内容即使写得不好也不擅自改动。

## 文件组织规范

- 任何时候不得在项目根目录下直接创建临时文件、测试脚本、调试脚本、临时数据文件。
- 生成/输出的文件（含报告、校验日志）放在被修改源文件的同一目录下，与源文件关联，方便查找对比。
- 临时文件统一放入源文件所在目录的 `temp/` 子目录（即 `<源文件目录>/temp/`），临时脚本放入 `temp/scripts/`。
- 非编程文档（Excel/PDF/DOCX/图片等）的备份、结果、中间产物，一律放被处理源文件的同一目录下的 `temp/` 子目录，不得放项目根 `temp/`。
- 编程类中间产物（脚本、JSON、临时数据）可放项目根 `temp/`。
- 不默认输出到项目根目录的 `temp/`。
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

## 记忆

- 不做自动记忆管道。值得长期保留的经验沉淀到对应 skill 或 CLAUDE.md；auto-memory（MEMORY.md）只存个人偏好与工作方式反馈。
- 回忆过往工作时按需搜对话记录：Claude Code 在 `~/.claude/projects/*/*.jsonl`，pi 在 `~/.pi/agent/sessions/`。
- `librarian.cmd text-search "关键词"` 仅是 2026-06-17 前 Baidu 文档的全文检索，按需使用。
