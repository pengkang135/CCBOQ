---
name: pk-boq-quotation
description: >
  报价单数据导入全流程：将PDF/图片/Excel/Word合同等原始报价文件转换为结构化数据，由填报子 agent 填、主会话审，两个独立上下文交叉核对后上传到 MongoDB，生成上传报告，支持批量输出统一风格Excel材料价格表。
  触发条件：用户要求"导入报价单"、"整理报价文件"、"上传报价数据"、"处理供应商报价"、"提取报价"、"报价资料"、"人工单价"、"材料单价"、"价格表PDF"、"合同报价表"、"合同单价入库"、"清单导入"、"BOQ导入"、"分包清单入库"、"综合单价入库"，或需要将报价单目录下的原始文件（PDF、JPG/PNG图片、Excel、Word合同、分包BOQ工作簿）转换入库。
  适用场景：CostSpread项目中将供应商原始报价单系统化导入数据库的工作流，涵盖文件转换、翻译、数据提取、预检、审核、上传、报告生成、批量Excel输出全链路。
---

# 报价单数据导入

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


> 工程造价约定、Excel 兼容性 → 见 `pk-boq` 技能
> 文档转中间格式的通用规则 → 见 `document-ingest` 技能。
> **但报价单导入的提取路径以本技能为准**（下方三级路径 + `probe_source.py`）——
> 两处都写会漂移，本技能的版本带实测数据与"价格不走 OCR"的铁律。

## 架构：填报 → 预检 → 审核 → 入库

```
  ⓿ 前置检查（主会话，动手前必做）
     批次号未被占用 · 该国税率已配 · probe_source.py 探明数据源
     BOQ 工作簿还要多一步：定 sheet 白名单
        │
        ▼
  ① data-preparer 子 agent（填报员）
     转换 → 翻译 → 结构化 → manifest.json + raw/
     无数据库写权限；读不准的标 uncertain
        │
        ▼
  ② precheck-manifest.js（代码，无 AI）
     格式 · 必填 · 类型 · 单位 · 价格溯源 · prepared 标识 · 批次撞车
     不过 → 退回①自己改
        │
        ▼
  ③ 审核 —— 主会话自己做，不派子 agent
     --analyze       → review-checklist.md（填进来的对不对）
     audit-recall.js → recall-report.md（该填的填了没）← 漏跑会被④拦
     逐条判断，写 review-notes.md
        │
        ├─ 需剔除 <10% → 剔除后上传，结论写明原因
        └─ 需剔除 ≥10% → 打回①重做
        │
        ├──────────────────────────┐
        ▼                          ▼（不必等入库）
  ④ import-manifest.js       ⑤ build_batch_excel.py
     --apply --review            出 Excel 价格表
     唯一写入口，只 insert        源: manifest-enriched
     带 importBatchId 可回滚      （③的 --analyze 产物）
     除税价反算依赖 taxrates 集合
        │                          │
        ▼                          │
  ⑥ build-upload-report.js         │
     出 HTML 上传报告               │
     源: MongoDB 按 importBatchId   │
     （不从中间文件拼，报告要反映    │
       库里到底存了什么）           │
        │                          │
        └────────────┬─────────────┘
                     ▼
  ⑦ archive-batch.js
     产物归档三处：报价单源目录 temp/<批次号>/、
     import-reports/<日期>/<批次号>/、staging 原样保留
     HTML 报告另复制到源目录根，方便直接打开
        │
        ▼
  ⑧ archive-source.js
     原件复制进 F:\BaiduSyncdisk\1.造价信息 归档库
     算 sha1，回写 rates.archiveRef（相对路径）
     供搜索端「打开原文件」反向定位
```

> 完整流程图（含各步产出物与打回路径）：`assets/workflow.svg`

**为什么填报和审核必须分开**：这类活不难，难在一个人干完全程时看不见自己的错。同一个上下文里，刚决定"这字段读不到就留空"的推理链，回头审的时候会用同样的理由认定留空合理。换一个 agent 就是换一份独立信号。

**为什么审核收回主会话、不派第三个 agent**：要发现"漏抽了整节报价""三个联系人只填了一个"，审核方必须同时握着源文和 manifest。派出去的审核 agent 只拿到 manifest，manifest 自身完全自洽，历史价比对也正常——它结构上就发现不了遗漏。主会话派了填报员、知道源目录在哪，是唯一能做遗漏检测的位置。

**代码守什么、AI 判什么**：类型污染这类事已经由 DB 层的 `$jsonSchema` validator 挡死（`validationLevel: strict`），无论从哪条路径写都拒。剩下的风险全是内容质量——价格读错一位、漏填、单位抄错，这些在类型上完全合法，只能靠两个独立 LLM 交叉核对。所以流程重心不在"堵口子"，在"填的人和审的人不是同一个"。

## 前置检查

1. 读取 `e:\Code\CostSpread\CLAUDE.md` 了解项目约定
2. Node 脚本在容器内执行，无需本机 NODE_PATH
3. staging 目录：`e:\Code\CostSpread\backend\temp\import-staging\<批次号>\`
   （必须在 `backend/` 下，容器只挂载了 `./backend:/app`）

### ⓿ 动手前必做的几件事

a、b、c 每批都要做；d 只在源文件是 BOQ 工作簿时做。

**a. 确认批次号没被占用。** 批次号是 `YYYYMMDD-NN`，同一天多批很容易撞。

```bash
ls e:\Code\CostSpread\backend\temp\import-staging\
```

目录已存在且里面有 `upload-report.md`，说明该号已上传过一批，**换号**。实测中曾发生填报员按指定批次号写 manifest、覆盖掉已入库批次的原 manifest（靠它自己留的备份才救回）。precheck 现在会拦这种情况，但换号比被拦更省事。

**b. 确认该国税率已配，否则除税价会是 null。**

```bash
docker compose exec -T backend node /app/scripts/check/check-tax-rates.js
```

`taxrates` 集合没有该国条目时，导入器算不出缺失的那个税价，Excel 里除税价整列空白。孟加拉国就是入库之后才发现的，只能事后补税率再跑 `recalcTaxPrices.js` 重算。**先查比后补省事得多。**

新国家要加税率：在 `backend/scripts/init/seedTaxRates.js` 的 `ADDITIONS` 里加条目，注意 `taxes[]` 每项的 `deductible` 决定它是否参与除税价反算（流转税 true；预扣所得税看当地实务，孟加拉国的 AIT 计入采购成本所以是 true）。

**c. 探明哪份文件是数据源。**

```bash
python "C:\Users\Kevin\.claude\skills\pk-boq-quotation\scripts\probe_source.py" "<报价单目录>"
```

一次给出：每个文件的类型与规模、PDF 有没有文本层、同内容多格式的配对（哪份取数据、哪份仅作佐证）、以及 xlsx 元数据里的日期线索。**把结果一并交给填报员**，省掉它自己摸索——实测中那次摸索花了 6 分钟、95k tokens。

**d. 源文件是 BOQ 工作簿时，先定 sheet 白名单。**

`probe_source.py` 会列出每个工作簿的全部 sheet 名与行列数。BOQ 工作簿动辄 20+ 个 sheet，**其中大部分不该入库**：汇总表（`Total` / `Summary` / `2.0 Total CSA`）会与明细重复计价，开办费表（`Preliminaries`）是包干价不入单价库，厂商清单（`ML-*`）根本没有价格。

更要命的是**不同工作簿常有同名 sheet 且数值不同**。实测 Evolution DC-1 那批：`Civil Subcontractor BOQ.xlsx` 与 `MEP Subcontractor BOQ.xlsx` 都含 `EE-BOQ-Building`，同一行 SUMMARY 一个是 3260 万、一个是 3.19 亿——它们是不同标段/不同版本。两份都导会灌进互相矛盾的重复记录，而且**入库后极难分辨**（名称、单位、日期全一样）。

所以白名单必须由主会话显式定下来交给填报员，**不能让脚本自动全取**。判断依据：哪份工作簿对哪个专业才是权威报价方。定不下来就问用户，别猜。

## 决策树

```
报价资料处理需求
  ├── 需要入库 → 走下方完整流程（①②③④ + Excel + 报告）
  │     ├── PDF / 图片 / 单表 Excel 报价单
  │     │     → 填报员按三级路径逐条提取（Step 1-3 主线）
  │     ├── 纯扫描件（整批只有图片，无 Excel/文本层 PDF 兜底）
  │     │     → references/chain-scanned.md
  │     ├── 官方价格册（政府/机构公开发布的 SoR、材料价格表、信息价，采集器已归档）
     │     → references/chain-published-pricelist.md
     ├── Word 合同（.docx，报价表格嵌在条款正文里）
  │     │     → references/chain-word-contract.md
  │     └── 分包 BOQ 工作簿（多 sheet、千行级、Unit Rate 拆三列）
  │           → references/chain-boq-workbook.md（**提取脚本未落地，当前不可用**）
  ├── 仅需 Excel 输出 → Step 1-3 出 manifest，再跑一次 --analyze 得到
  │                     manifest-enriched.json，用它出 Excel（不写库）
  └── 仅查询已有价格 → 走"LLM 语义匹配"链路，不走本流程
```

**分叉只在①的内部**：换的是填报员用什么工具把源文变成 manifest，不是换流程。填报员仍是 `data-preparer` 子 agent，审核仍在主会话，两个独立上下文一个不少。

> **不要拿原始 manifest 直接出 Excel**。原始 manifest 只有源文件上有的那个税价，另一个是 `null`，生成的表格除税价会是一片 0。必须先 `--analyze` 得到 `manifest-enriched.json`（税价已反算、单位已归一、分类已判定）。

---

## 上下文纪律

一次 Mirsarai WTP 多批导入实测：26 小时、**1,795 次 API 调用**（主会话 998 + 7 个子 agent 797）、
cache_read 累计 **1.97 亿 tokens**、读图 **76 张 2,865 万字符**。
复盘出七条，没有一条是能力问题，全是纪律问题。

> 注意分布：**填报（子 agent）读了 60 张图 2,194 万字符，审核（主会话）只有 16 张 672 万**——
> 填报是审核的 3.3 倍。所以别想着"合并审核省 token"，该省的在填报侧。
> 审核经手的全部文本（checklist + recall + analysis + notes）合计才 4 万字节，
> **一张整页图就抵 11 个批次的审核文本**。

**一批一个会话。** 那次 5 个批次串在同一会话，上下文被前面批次的历史撑到 13 万，
之后每一次调用都要重读一遍。实测主会话在 67k 与 165k 之间锯齿式往返、**自动压缩了 18 次**，
中位上下文 13.2 万——1.97 亿里的绝大部分就是这么来的。
**前一批 `--apply` 完成、报告归档之后就开新会话**，别接着做下一批。

**核验出文本，不出图。** 落款联系方式、日期、盖章的核验，跑 `extract_region.py --ocr paddle`
看它打印的文本行就够了，**不要再 Read 那张图**。实测 30 秒内连读 3 张整页缩略图
= 38.6 万 tokens，同样内容的 OCR 文本不到 1k——**差两个数量级**。

**脚本存的图是留痕，不是给你读的。** `scan_price_table.py` 的 `_p1_table`、`extract_region.py`
不带 `--ocr` 时的裁图，存下来只为日后人工复核——**脚本已经把全部读数和校验结论打印出来了**。
那次填报员把 `_p1_table.png` 读回上下文（单张 56-63 万字符），而同样的内容就在脚本输出里。
两个脚本现在都会在存图时明确标注"不要 Read"并打出 token 代价。

**绝大多数情况一张图都不用读。** 表格读数用 `scan_price_table.py` 整页跑（不给 `--rel` 即可，
行列由 bbox 聚类自己还原）；落款、日期、联系方式用 `extract_region.py --find "关键词" --ocr paddle`
自动定位出文本。**只有版面怪到 `--find` 也找不着时，才用 `--thumb` 看一眼挑坐标，挑完就别再读。**
那次 `_crop_sig.png` 被读了 4 次、3 次、3 次——同一张落款裁图反复进上下文。

**非读不可的图必须是 jpg。** 两个脚本已统一输出 jpg，缩略图 72dpi/quality 60（48 KB ≈ 1.7 万 tokens）。
那次自写脚本用 `dpi=180` 存 png，单张 663,600 字符 ≈ 16 万 tokens，**差近 10 倍**。
**`raw/` 里同时有 png 和 jpg 时，永远读 jpg。**

**别自己现写 render/crop/ocr 脚本。** 那次在批次目录里写了 `_render.py`、`_crop.py`、`_ocr.py`、
`_extract.py`，每一个的产物都比技能自带脚本更费。三个自带脚本就是为消灭这类重复劳动写的，
**缺功能就提出来改脚本，不要临时顶一个**。

**同一个中间文件只读一次。** 那次 `review-notes.md` 读了 7 次、同一条 Bash 命令跑了 14 次、
`--apply` 跑了 6 次。审核阶段的产物读进来就记住，别反复 Read；`--apply` 失败先看报错，
不要直接重跑。

---

## Step 1-3：填报（派 data-preparer 子 agent）

派发 `data-preparer` 子 agent 完成转换、翻译、结构化。它的详细规则见 `.claude/agents/data-preparer.md`，要点：

> **模型别名有坑**：agent 定义里写的是 `model: sonnet`，但本环境的 `sonnet` 与 `haiku` 别名都会解析到不可用的模型（报 "There's an issue with the selected model"），**只有 `opus` 能起来**。派发时如遇此错，用 `model: "opus"` 覆盖，并把实际模型填进 `prepared.model`。
>
> 这不影响流程正确性——"填的人和审的人不是同一个"靠的是两个独立上下文，换模型只是额外一层独立信号。但要如实记录用的是哪个模型。

### 转换：先定角色，再选工具

同一批常有 Excel 和 PDF 两份同内容文件。**不要两个都全量提取**，先判角色：

| 载体 | 角色 | 取数工具 |
|---|---|---|
| Excel / CSV | 数据源 | `fastexcel` 读值（禁 openpyxl 读值，慢 9-16 倍） |
| 有文本层的 PDF | 数据源 | `pdfplumber.extract_tables()` 按表格列抽（**不要 `extract_text().split('\n')` 硬切**）|
| **Word `.docx`** | **数据源** | **`python-docx` 按 `doc.tables` 单元格坐标取** |
| 扫描 PDF / 图片 | 佐证源；**无其他来源时降级为数据源** | 有数据源时只提它没有的（签字人、联系方式、盖章、日期、手写批注）；**纯扫描件批次走 `scan_price_table.py` 三档采信**，见 [chain-scanned.md](references/chain-scanned.md) |

`.doc` 老二进制格式 `python-docx` 读不了，先 `pandoc` 转 `.docx`，不要硬啃。

**PDF 提取表格一律用表格抽取，不要按行硬切。** 有文本层的用 `pdfplumber.extract_tables(table_settings={'vertical_strategy':'lines','horizontal_strategy':'lines'})`（有线表格）或 `{'vertical_strategy':'text'}`（无线表格）；仍不行转 `pdf2docx` 后 `python-docx` 读 `doc.tables`。
`pypdf/fitz` 的 `extract_text().split('\n')` 只在一行一价的巧合版式上碰对；有表格线/多列时会串行——西部省材料价表是前者，西北省 HSR（`CODE | DESCRIPTION | UNIT | Rate`）是后者，按行切会把费率张冠李戴。
**不要手写行列坐标/逐行切分解析器**，那是最后手段。

**有数据源时，价格一律从数据源取，不走 OCR。** 三级路径：

| 层级 | 手段 | 用途 | 实测成本 |
|---|---|---|---|
| 0 | `probe_source.py <目录>` | 定角色、探文本层、列 Word 表格清单、取元数据日期线索 | <1s |
| 1 | `fastexcel` 读值；**PDF 表格用 `pdfplumber.extract_tables()`**（无线表格→`text` 策略或 `pdf2docx`→`python-docx`）；Word 用 `python-docx` 的 `doc.tables` | 全部结构化数据 | ~0.1s |
| 2 | `extract_region.py --find "关键词" --ocr paddle` | **自动定位 + 精读出文本，全程不出图** | 约 1k token |
| 3 | `extract_region.py --page N --thumb` | **兜底**：版面太怪、`--find` 找不到时才看一眼挑坐标 | 48 KB ≈ 1.7 万 token |

> **第 2 级是首选，第 3 级是例外。** 位置能算出来就不要看出来——整页 rapidocr 粗读
> （2.6s、零 token）返回带坐标的文本行，匹配关键词就知道目标在哪。实测拿同一张报价表：
> `--find` 出文本约 1k token，而把脚本存的裁图 Read 回来是 14 万 —— **差约 140 倍**。
> 「先看缩略图挑坐标」原本是工具要求 `--rel` 逼出来的，不是任务需要。
>
> `--find` 会同时打印 rapidocr（中文准）与 paddleocr（数字准）两份读数，互为交叉校验。

**别自己现写探测与裁图代码**，这两个脚本就是为省掉重复造轮子写的：

```bash
S="C:\Users\Kevin\.claude\skills\pk-boq-quotation\scripts"
python "$S\probe_source.py" "<报价单目录>"
python "$S\extract_region.py" "<扫描件.pdf>" --page 1 --thumb
python "$S\extract_region.py" "<扫描件.pdf>" --page 1 --rel 0,0.62,0.62,0.22 --ocr paddle --tag _sig
```

`--rel` 用相对坐标（0~1），不必先知道页面像素尺寸。裁图存到源文件同级 `raw/`，路径打印在最后，可直接用 Read 工具看图。

本地库均已安装：`fitz`、**`pdfplumber`（含 `extract_tables`）**、`pypdf`、`pdfminer.six`、`pypdfium2`、`pdf2docx`、`pdf2image`、`rapidocr_onnxruntime`、`paddleocr`、`fastexcel`、`openpyxl`、`xlsxwriter`、`python-docx`、`PIL`。
（表格抽取未装现成工具如 `camelot`/`docling`/`marker`/`MinerU`；要用手先装，但 `pdfplumber.extract_tables` 已足够应付政府价格册的规则表。）
**`mcp__pdf2md__*` 与 `mcp__rapid-ocr__*` 在本环境不存在，不要调用。**

OCR 引擎实测（同一份扫描件）：

| 范围 | 引擎 | 耗时 | 价格 | 关键信息 |
|---|---|---|---|---|
| 全页 200dpi | `rapidocr` | 6.4s | 3/6 | 3/4（邮箱 `pdl305`→`pdi305`） |
| 全页 200dpi | `paddleocr` | 107.5s | 4/6 | 4/4 |
| **落款裁图**（占页 13.6%） | `paddleocr` | **35.2s** | — | 签字人/职务/手机全对 |

裁图后比全页快 3 倍且更准，这是第 3 级只喂裁图的原因。`paddleocr` 在本机必须 `PaddleOCR(lang='en', enable_mkldnn=False)`，默认 onednn 后端会崩（脚本已处理）。

**没有任何单一 OCR 能可靠读全价格**（最好 4/6）。所以铁律是「**单一 OCR 读数不得直接入库**」——不是"扫描件不能用"。有 Excel 兜底时根本不必冒这个险；没有兜底时靠交叉验证把错误变成可见的分歧，见下方「纯扫描件」专节。

不要跳过 0-2 直接对全页做视觉转录——实测那样跑一次 6 分钟、95k tokens，而价格 Excel 里全都有。**注意这禁的是全页视觉转录，不是裁图 vision**：小裁图上的 vision 约 1.5k token，是双引擎分歧时最划算的第三方仲裁。

### 四条分链：按载体选，见对应 reference

决策树分到哪条就读哪一个，**不要三个都读**——它们互斥，一个批次只走一条。
②③④⑤⑥⑦⑧ 与主线完全相同，一步不减。

| 链 | 何时走 | 要领 | 详见 |
|---|---|---|---|
| **纯扫描件** | 整批只有图片/扫描 PDF，无 Excel 或文本层 PDF 兜底 | 双引擎交叉 + 算术闭合，三档采信写进 `priceVerify` | [chain-scanned.md](references/chain-scanned.md) |
| **Word 合同** | 源文件是 `.docx`，报价表嵌在条款里 | 走 `doc.tables` 单元格坐标，不转 Markdown；`priceSource=project`，条款必须留痕 | [chain-word-contract.md](references/chain-word-contract.md) |
| **官方价格册** | 政府/机构公开发布的价格册，由采集器下载归档（人工、机械、材料混在一张表里） | 脚本只转换、填报员做语义判断、单位换算与分类修正由导入器与回归集负责 | [chain-published-pricelist.md](references/chain-published-pricelist.md) |
| **分包 BOQ 工作簿** | 多 sheet、千行级，Unit Rate 拆三列 | 脚本按列位抽，LLM 不碰数字。**提取脚本尚未落地，当前不可用** | [chain-boq-workbook.md](references/chain-boq-workbook.md) |

### 日期缺失时的兜底

报价单常常没有日期栏。查完抬头、签署区、页脚仍找不到时，读文档元数据：xlsx 的 `dcterms:modified`、`cp:lastModifiedBy`、`cp:lastPrinted`。**若 `lastModifiedBy` 与报价签字人一致，`modified` 时间可作为定稿日期采信**（这次 Laldia 项目就是这么定的）。

用元数据推出来的日期**必须标 `uncertain`**，写清证据链。`date` 是 validator 必填字段，留 null 预检过不了，所以只能推——但推了就要标。

### 翻译

非英文（泰文、阿拉伯文等）翻译为中文；材料名保留英文术语并补中文译名，技术参数保持原文。
**泰国佛历年 = 公历年 + 543**，日期换算勿漏。
泰文对照表见 [references/translation-glossary.md](references/translation-glossary.md)。

### 结构化成 manifest.json

写入 `backend/temp/import-staging/<批次号>/manifest.json`：

```json
{
  "batch": "20260812-01",
  "prepared": { "by": "data-preparer", "model": "<实际使用的模型>", "at": "2026-08-12T10:30:00+08:00" },
  "project": { "country": "泰国", "city": "曼谷", "projectName": "...", "specialty": "数据中心" },
  "source": { "files": ["XX报价单.pdf"], "conversionMethod": "PDF→Markdown" },
  "items": [
    {
      "name": "球阀 Ball Valve",
      "features": "DN50 青铜丝扣",
      "unit": "个",
      "price_incl_tax": 23256,
      "price_excl_tax": null,
      "currency": "THB",
      "date": "2026-08-01",
      "supplier": "XX机电有限公司",
      "contact": "", "phone": "", "address": "",
      "sourceRef": {
        "file": "XX报价单.pdf", "page": 3, "row": 17,
        "rawText": "Ball Valve (Bronze Screwed) dia.50mm    23,256 THB/ea"
      }
    }
  ]
}
```

**Excel 源**：`sourceRef` 用 `sheet` + `row` 代替 `page`——`page` 留 `null`，`sheet` 填工作表名。
反例：某批次只填了 `{file, row}`，35783 条库里就有 513 条靠 (file,row) 定位不到
具体是哪张表（`附件2材料费` 与 `附件6临时设施` 都有 r31）。回填脚本：
`backend/scripts/cleanup/backfill-source-sheet.js --batch <批次号>`（从 `raw/<sheet名>.txt` 反查，默认 dry-run）。

**BOQ 链的 manifest 差异**（只多这些，其余完全一致）：

```json
"source": {
  "files": ["MEP Subcontractor BOQ.xlsx"],
  "conversionMethod": "fastexcel 按合并表头子列提取",
  "dataType": "bq_unit_price",
  "sheets": ["EE-BOQ-Building", "ME-BOQ-ME"],
  "taxBasis": "excl"
}
```

`source.dataType` 是批次级默认值，`items[].dataType` 逐条覆盖它。三个取值：

| dataType | 取自哪一列 | 导入器判成 |
|---|---|---|
| `bq_unit_price` | Total | `resourceType=composite`（综合单价） |
| `bq_material_price` | Material | `resourceType=material`（材料价） |
| `bq_labour_price` | Labour | `resourceType=labor`（人工价） |

三者的 `priceSource` 都是 `project`。BOQ 报价通常标 "Not including tax"，所以 `taxBasis` 一般是 `excl`，含税价由导入器按国别税率反算。

**填写铁律**：

| 规则 | 说明 |
|---|---|
| 只填源文件读得到的 | `resourceType` / `category` / `priceSource` / `searchText` / 归一化单位 **一律不填**，导入器会算，填了也忽略 |
| `dataType` 只有 BOQ 链填 | 三值见上表。它是分类器的**权威信号**，优先于一切名称猜测——所以 `resourceType` 仍然不填，让它由 `dataType` 推出。PDF 链不填 `dataType`，走名称判定 |
| **整项/包干价不入库** | 单位是 `Ls` / `Item` / `Lot` / `Sum` / `项` / `式` 的行一律不填。它们不是"每单位价格"，作为单价展示会误导搜索并扭曲统计（历史上删过 705 条这类记录） |
| **实报实销不入库** | 标着"实报实销""据实结算""at cost""reimbursable"的行没有单价，不填。与上一条同理 |
| **扫描件链：`priceVerify` 必填** | 取值 `arith` / `dual` / `none`，由 `scan_price_table.py` 给出。它记录这个数字凭什么可信——没有它，日后没人能判断一个 OCR 来的价格该不该信 |
| 单位填原样 | 源文件写 `sqm` 就填 `sqm`，归一化由代码做 |
| 税价只填有的那个 | 泰国报价常见 "Net Price (before VAT 7%)"，只填 `price_excl_tax`，另一个留 `null`，导入器按国别税率反算 |
| **读不到留 null，不要填 0** | 填 `0` 会被当成"不要钱"，比缺失更糟。436 条零价就是老脚本 `\|\| '0'` 造成的 |
| **读得到但读不准，标 `uncertain`** | 与"读不到"是两回事：给出最可能的值，同时用一句话写明疑在哪、倾向哪个、依据是什么。标了会进审核优先清单 |
| `sourceRef` 每条必填 | `rawText` 是审核比对的依据、幻觉检测的判据，也是召回核对能覆盖到源文的前提 |
| **Excel 源：`sourceRef.sheet` 必填** | 填工作表名（PDF/图片源留空），`page` 留 null。`row` 是该 sheet 内的**物理行号**——不同 sheet 的行号会撞号，只给 (file, row) 回溯时会指到错的工作表：一本工作簿里「附件2材料费!r31」与「附件6临时设施!r31」是两条毫不相干的记录。同一 sheet 同一行也可以出多条记录（如人工费每行出「中方」「属地」两条），回头定位要连 `name` 一起用 |
| **Excel 源：名称先重建分级小标题** | 按标记列逐行取数时，明细行的 B 列经常放的是**规格**而不是品名（「最大尺寸175 × 230mm」「尺寸100 × 140mm；单个停车位」「C25」），脱离上一级小节标题就不知道是什么东西。**先把 `A 列 = 1 / 1.2 / 1.2.3` 的大类 / 小节 / 明细三级结构重建出来**，再定名：品名取自小节标题，规格进 `features`。反例见本批 16 条打回记录——只取 B 列会让标识牌变成一串尺寸。`pk-boq-merge` 的分级章节规则同理 |
| `prepared` 块必填 | 缺了预检直接不过——它标记这是子 agent 填的，不是主会话自己填的 |
| 转换产物留在 `raw/` | 必须是 `.md`/`.txt`。召回核对要拿它跟 manifest 反向比对，空目录这道检查就跑不了 |
| **合同链：条款必须留痕** | 合同来源的条目，`remarks` 记下限定该单价的条款原文（"综合单价含XX"、"量变超10%重议"等）。确实没有就写明"合同未附加条件"。**单价脱离条款入库等于埋雷**——日后查价的人只看得到数字 |
| **合同链：暂定金额不入库** | 暂定金额 / Provisional Sum / 暂列金 / 备用金 表一律不填，与上面「整项/包干价不入库」同理，它不是单价。`probe_source.py` 会把这类表标出来 |

### 自检（填报员自己跑）

```bash
cd e:\Code\CostSpread && docker compose exec -T backend \
  node /app/scripts/import/precheck-manifest.js /app/temp/import-staging/<批次号>/manifest.json
```

退出码 0 = 可提交；1 = 看 `precheck-report.json` 改完再跑。**没过预检不要交回主会话。**

交回时要说清：批次号、条数、raw/ 路径、**标了 `uncertain` 的条目及原因**、源文里看到但没填的东西（整版条款、付款条件、第二联系人）及为什么没填。

---

## Step 4：审核与入库（主会话自己做，不派子 agent）

**这一步不要再派 agent。** 填报员已经用掉了那份独立信号，再派一个审核 agent 只会拿到同样的 manifest、得出同样自洽的结论，而且它看不到源文件——遗漏这类问题它结构上就发现不了。

### 4.1 跑两份报告

两份查的是不同的东西，**都要跑**——漏跑召回核对，`--apply` 会直接拒绝上传（它检查 `recall-report.json` 存在且不比 manifest 旧）：

```bash
# 填进来的对不对 —— 类型、价格溯源、历史价偏离、批内自比
docker compose exec -T backend \
  node /app/scripts/import/import-manifest.js /app/temp/import-staging/<批次号>/manifest.json --analyze

# 该填的填了没 —— 源文里有、manifest 里没有的
docker compose exec -T backend \
  node /app/scripts/import/audit-recall.js /app/temp/import-staging/<批次号>/manifest.json
```

产出：

| 文件 | 查什么 |
|---|---|
| **`review-checklist.md`** | 逐条待判异常，按严重度排序，含证据、原文、页行定位、建议 |
| **`recall-report.md`** | 源文里没被任何条目引用到的报价行、没填进 manifest 的联系方式 |
| `analysis-report.json` | 全批统计：不合规占比、异常数、资源类型与来源分布 |
| `manifest-enriched.json` | 补全派生值后的数据，供出 Excel 用 |

都**不写库**。`--analyze` 可以对已入库批次重跑（只有 `--apply` 拦重复导入），补了税率想重看除税价反算结果时用得上。

manifest 被打回改动过之后，两份报告都要重跑——`recall-report.json` 比 manifest 旧时 `--apply` 会拒绝，因为旧报告不再反映当前数据。

源文件确实无法转成文本（纯图片且 OCR 也读不出结构）时，用 `--skip-recall "<理由>"` 放行，理由会写进上传报告。**绕过可以，但要留痕**。

### 4.2 判 review-checklist（填进来的对不对）

逐条打勾，对照 `rawText` 和页行定位看。

> **回原文核对时不要 Read 整页图。** 这一步和 4.3 是全流程最容易烧 token 的地方——
> 要核对的是某一行某个数，而 Read 一张整页图是 10-16 万 tokens。
> 正确做法：`extract_region.py --rel <目标区域> --ocr paddle`，**看它打印的文本**。
> 详见「上下文纪律」。

| 现象 | 判断 |
|---|---|
| **解析值不在原文数字里**（原文 `888`、解析 `8880`） | OCR 错读或抄错行 → **剔除** |
| 偏离正好 10 倍 / 100 倍 | 小数点或千分位读错 → **剔除** |
| 填报员标注了 `uncertain` | 回原文核对。确认得了就保留并在结论里写依据，确认不了 → **剔除** |
| 偏离 3-5 倍但 `features` 明显不同规格 | 同名不同规格，工程材料常见（如"电缆"）→ **保留** |
| 库内无同类可比，但价格与原文一致 | 新品类首次入库 → **保留** |
| 名称是纯位号/编号（`- G01-MDB-FWU-A`） | 不是错数据，是缺信息 → **打回填报员补齐**，别剔除 |
| **名称是规格或裸标号**（`最大尺寸175 × 230mm`、`尺寸100 × 140mm；单个停车位`、`C25`） | Excel 源把 B 列规格当品名了 → **打回填报员按上一级小节标题补名**（规格保留进 `features`），别剔除也别硬留。这类往往一改名字就会在「同族离群」里浮出来，属正常 |
| 改过名的条目又报了同族离群 | 先回源核对算式（含税价、进口增加比例、汇率），算式对得上就是规格差异 → **保留** |
| 缺 supplier 但 `priceSource=published` | 信息价本就无供应商 → **不算缺陷** |

两条优先级：

1. **「价格与原文不符」压过一切统计性异常**。统计异常可能只是正常波动，但解析值对不上原文，说明数据在抽取环节就错了，跟价格合不合理无关
2. **偏离大不等于错**，一定结合 `features` 看

#### 纯扫描件链要换一种看法

没有「原文数字」可比，OCR 读数就是唯一的原文读法。改看 `priceVerify` 与算术闭合，
见 [references/chain-scanned.md](references/chain-scanned.md)。

#### BOQ 链要换一种看法

BOQ 走脚本取数，不会有「888 读成 8880」这类单点错读；**它的风险是整列定位错**，
表现为一整片系统性地错。判据见 [references/chain-boq-workbook.md](references/chain-boq-workbook.md)。

### 4.3 判 recall-report（该填的填了没）

这份清单里未被引用不等于漏填——小计行、表头、条款说明本来就不该入库。但**漏抽的报价行一定在里面**：

| 现象 | 动作 |
|---|---|
| 未引用行是小计/合计/表头/规格说明 | 正常，跳过 |
| 未引用行是完整的品名+单位+价格 | **漏抽** → 打回填报员补 |
| 整片连续的未引用行集中在某一页 | 多半是整节漏抽（翻页断了、表格没识别全）→ 打回 |
| 源文出现但未填入的联系方式 | 多联系人只填了一个 → 打回补齐，或在结论里说明为什么不填（如属其他项目） |

覆盖率低于 85% 且未引用行里明显有真报价，直接打回，不要逐条剔除。

#### BOQ 链不适用 85% 这条线

BOQ 的 `raw/` 里被有意跳过的行几乎全部命中 `audit-recall.js` 的「疑似报价行」标准，
覆盖率会落在 30% 上下，**这是设计使然，不是漏抽**。改用「`detail` 行 100% 被引用」等三条判据，
见 [references/chain-boq-workbook.md](references/chain-boq-workbook.md)。

### 4.4 决策

| 情况 | 动作 |
|---|---|
| 需剔除 + 需补填 < 10% | 剔除后上传，结论写明原因 |
| ≥ 10% | **打回填报员重做** |
| 问题集中在同一类（整批单位都错、整节漏抽） | 即使不到 10% 也打回——系统性错误逐条剔除治标不治本 |
| 存疑但拿不准 | 保留上传（会自动标 `needsReview`），在结论里点名让人抽查 |

打回时写 `reject-report.md`：打回原因与占比、5-10 条典型样例（带 `rawText` 与解析值对照）、建议从哪一步复查。**不要自己改 manifest**——改了就断了追溯链，数据有问题是打回填报员的事。

### 4.5 写审核结论

上传前必须写 `<批次目录>/review-notes.md`，**`review-checklist.md` 里每一条待判项都要在结论里被提及并给出处置**，格式随意但要能被 `第 N 条` 匹配到：

```markdown
# 审核结论  批次 20260812-01

## 待判项处置
- 第 17 条 镀锌钢管：填报员标注 uncertain（1510 或 151）。查原文第 3 页第 17 行，
  同页 DN40/DN65 分别为 1180/1890，1510 落在序列里 → **保留**
- 第 42 条 球阀：解析 8880，原文只有 888 → OCR 错读 → **剔除**
- 第 55 条 电缆：偏离历史价 4.2 倍，但 features 是 YJV22-4×240 而历史是 4×16
  → 规格不同属正常 → **保留**

## 召回核对
- 未引用行 23 行，逐行看过：19 行是小计与表头，4 行是同页重复的规格说明 → 无漏抽
- 源文 3 个电话已全部填入

## 结论
剔除 1 条（第 42 条），上传 118 条。第 55 条建议入库后抽查。
```

漏了任何一条待判项，`--apply` 会拒绝执行并列出漏了哪些。这不是防谁撒谎，是让审核有个必须真看过清单才写得出来的产出物。

### 4.6 上传

```bash
docker compose exec -T backend \
  node /app/scripts/import/import-manifest.js /app/temp/import-staging/<批次号>/manifest.json \
  --apply --review /app/temp/import-staging/<批次号>/review-notes.md --exclude 42
```

预检没过的会自动剔除，`--exclude` 只列审核判断要剔的。自动生成 `upload-report.md`：入库数、填报者标识、审核结论引用、剔除明细、待抽查清单、回滚命令。

导入器自动完成：单位归一化、缺失税价反算、`resourceType`/`category`/`priceSource` 判定、价格异常标 `needsReview`、打 `importBatchId`。

**写库只能走这一条路。** 不要用 mongosh、mongodb MCP 或临时脚本直连——不是因为拦得住，是因为绕过去就没有 `importBatchId`，出事回滚不了。

### 回滚

```bash
docker compose exec -T backend \
  node /app/scripts/import/rollback-import.js --batch <批次号> --apply
```

只删该批次自己插入的记录，不碰历史数据。

---

## Step 5：批量 Excel 输出

```bash
python "C:\Users\Kevin\.claude\skills\pk-boq-quotation\scripts\build_batch_excel.py" \
  <批次目录>/manifest-enriched.json \
  -o <output.xlsx> \
  --title "人材机价格表 — {项目名}" \
  --subtitle "报价日期: {日期范围} | 来源: {供应商列表}"
```

**用 `manifest-enriched.json`**（`--analyze` 的产物），不要用原始 manifest。脚本同时支持扁平 `items[]` 与旧版 `suppliers[].items[]` 两种结构。

Excel 输出规格（16 列 A-P）：

| 列 | 表头 | 列 | 表头 |
|----|------|----|------|
| A | 编号 | I | 日期 |
| B | 专业 | J | 币种 |
| C | 名称 | K | 供应商 |
| D | 项目特征 | L | 联系人 |
| E | 单位 | M | 电话 |
| F | 除税单价 | N | 地址 |
| G | 税金 | O | 备注 |
| H | 含税单价 | P | 来源 |

样式：标题行合并居中 14pt 加粗，表头蓝底(D9E1F2) 11pt 加粗，分组标题绿底(E2EFDA)，数据行 10pt，末尾汇总行含来源列表与价格统计。

## Step 6：HTML 上传报告

```bash
docker compose exec -T backend \
  node /app/scripts/import/build-upload-report.js --batch <批次号> \
  --out "/app/temp/import-staging/<批次号>/{项目简称}_上传报告.html"
```

脚本**从 MongoDB 按 `importBatchId` 查询生成**，不从 manifest 拼接——报告的意义是反映
"库里到底存了什么"，从中间文件拼会掩盖入库环节的问题。

自动填充：项目概况、供应商分组明细、资源类型与价格来源分布、待抽查标记、数据来源页脚。

## Step 7：归档

```bash
node backend/scripts/import/archive-batch.js <批次号> --source-dir "<报价单源目录>"
```

产物落到三处，一处都不能少：

| 位置 | 为什么 |
|---|---|
| `<报价单源目录>/temp/<批次号>/` | 跟原件放在一起——日后翻到那份 PDF 就能看到当初怎么处理的、审核判了什么 |
| `import-reports/<日期>/<批次号>/` | 按日期横向查"某天导了哪些批次"。已加 `.gitignore`（含供应商价格与联系方式，不入库） |
| staging 原样保留 | 不删，随时可重跑 `--analyze` 或回滚 |

HTML 上传报告另复制一份到**源目录根**，打开报价单文件夹就能直接点开。

归档日期从批次号解析（`YYYYMMDD-NN`），不是当天——跨天补跑才不会归到错的日期目录。

**中间产物一律不删。** 召回核对依赖 `raw/`，审核复核依赖裁图，日后追溯依赖这一整套。

## Step 8：归档原件到百度盘（回写 archiveRef）

```bash
node backend/scripts/import/archive-source.js <批次号> \
  --source-dir "<报价单源目录>" \
  [--project-dir "1 海外人材机/2026/TH26-012-DP World"]
```

把原件（PDF/Excel）**复制**进 `F:\BaiduSyncdisk\1.造价信息` 归档库（落在
`<项目目录>/报价文件/` 下，源文件原位保留，纯备份），算 sha1，按
`importBatchId` + `sourceRef.file` 回写 `rates.archiveRef`（存相对路径，POSIX 分隔符），
供搜索端「打开原文件」反向定位。产出 `staging/<批次号>/archive-manifest.json`。

- `--project-dir` 缺省时按 `manifest.project.projectName` 在
  `1 海外人材机/<年>/` 下自动匹配现有目录：唯一命中就用；0 个或多个命中报错退出，
  打印建议目录名（国家码 + 年后两位 + 最大序号+1），确认后重跑并加 `--project-dir`。
  **不自动建目录。**
- **`--source-dir` 给最外层那个目录就行**，脚本会往下递归找（跳过 `temp`/`raw`/`_converted`）。
  报价单目录几乎总是一家一个子目录（`2.DECHO Limited/`、`3.Dico Logistics/`…），
  不必也不该拆成多次、一家一个 `--source-dir` 跑——那样 `archive-manifest.json` 只会留下最后一次。
- 目标同名冲突：sha1 相同复用已有那份，不同加 `-2`/`-3` 后缀并存，任何情况不覆盖。
- `--dry-run` 只打印不落盘不写库；`--no-db` 落盘但不写库。
- 幂等：同批次重跑，relPath 相同则 `$set` 同值，目标已存在且 sha1 相同则跳过。

## Step 9：验证

验收标准见下方「质量标准」，这里只写需要动手查库的三条：

1. 按 `importBatchId` 查 MongoDB，条数与 `upload-report.md` 一致，并按供应商分组看分布
2. **除税价整列 null** → 该国税率没配。补 `taxrates` 后跑
   `recalcTaxPrices.js --country <国家> --apply` 重算，**并重新生成 Excel 与 HTML 报告**
3. `archiveRef.relPath` 非空且条数与入库一致；未匹配的按 `archive-manifest.json` 的警告逐条核对

向用户报告：批次号、入库条数、剔除条数及原因、需抽查条目、报告路径、Excel 路径、归档路径、归档 relPath。

## 质量标准

- 每条报价对应一条独立记录，同一材料不同规格分别记录
- 中文翻译覆盖材料名、规格、供应商信息、备注
- 价格保留原始小数位
- 每条必有 `sourceRef`，`rawText` 为源文原始片段
- **填报与审核由两个独立上下文完成**：manifest 带 `prepared.by`，审核在主会话，`review-notes.md` 逐条回应待判项
- **召回覆盖率 ≥ 85%**，未引用行已逐条看过并在审核结论里交代（**BOQ 链不适用此线**，见 [chain-boq-workbook.md](references/chain-boq-workbook.md)）
- 上传后源文件夹根目录必有 HTML 报告，从 MongoDB 查询生成
- Excel 与 HTML 报告数据同源
- **除税价与含税价都有值**，为 null 说明该国税率未配（处置见 Step 9 第 2 条）
- **产物已归档三处**，中间产物未删除
- **原件已归档并回写 archiveRef**：搜索端能「打开原文件」反向定位到归档盘原件
- 纯扫描件链另加三条：**每条价格带 `priceVerify`**（`arith`/`dual`/`none`）；**`none` 的必定同时标了 `uncertain`**；**版面行数与 manifest 条数的差额已逐行交代**（表头、合计、实报实销各几条）
- BOQ 链另加三条，见 [chain-boq-workbook.md](references/chain-boq-workbook.md)

## 参考资源

- `references/rate-model.md`：Rate 模型字段定义
- **分链 reference（决策树分到哪条读哪一个，不要三个都读）**
  - `references/chain-scanned.md`：纯扫描件链（双引擎 · 算术闭合 · 三档采信）
  - `references/chain-word-contract.md`：Word 合同链（doc.tables · 合同价语义）
  - `references/chain-boq-workbook.md`：分包 BOQ 工作簿链（**提取脚本未落地，当前不可用**）
  - `references/chain-published-pricelist.md`：官方价格册链（采集器归档 · 转换/填报分离 · 单位换算 · 分类回归集）
- `references/translation-glossary.md`：泰文等非英文对照表
- `scripts/probe_source.py`：源文件探测（定角色 · 探文本层 · Word 表格清单 · 元数据日期线索）
- `scripts/extract_region.py`：区域裁图 + OCR（第 3 级关键字段核验）
- `scripts/scan_price_table.py`：纯扫描件价格表读数 + 三档交叉验证（双引擎 · 算术闭合 · 排除项打标）
- `scripts/build_batch_excel.py`：批量 Excel 生成
- 项目侧 BOQ 提取：`scripts/import/boq/`（在 CostSpread 仓库内，不在本技能目录——它受版本控制，规则会演进）
  - `extract_boq_manifest.py`：BOQ 工作簿 → manifest（**尚未落地**，见 `docs/boq-excel-import-plan.md`）
  - `tests/`：表头解析与行分类的全部规则都固化在这里。**改脚本前先跑测试，改规则必须同步加测试**——BOQ 表头的那些坑（拼写错误、括号注释、列位漂移、`nan` 陷阱）写在文档里会过期，写在测试里不会
- `assets/workflow.svg`：完整工作流程图（浏览器直接打开，含深色模式）
- `assets/report-template.html`：HTML 报告模板
- 项目侧导入链：`backend/scripts/import/{precheck-manifest,import-manifest,audit-recall,archive-batch,archive-source,rollback-import}.js`
- 项目侧税率：`backend/scripts/init/seedTaxRates.js`（加国家）、`scripts/check/check-tax-rates.js`（巡检到期与缺口）、`scripts/cleanup/recalcTaxPrices.js`（税率口径变更后重算，`fix-missing-prices` 只补 null 碰不到旧税率算出的错值）
- 项目侧：`.claude/agents/data-preparer.md`（审核不再有对应 agent，由主会话执行 Step 4）
