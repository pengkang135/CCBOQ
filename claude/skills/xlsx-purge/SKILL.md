---
name: xlsx-purge
description: "净化 xlsx：清定义名称（未使用的、#REF! 坏掉的、HTML 实体垃圾名）、断外部链接（引用外链的公式先转值保住数据）、清 ZIP 级残留（externalLinks/rels/Content_Types/calcChain）。ZIP/XML 底层直接操作，无需 Excel COM。净化名称和断外链是分开的两件事，用 --mode 选：names 只清名称不动公式、links 只断外链、all 两者都做。当用户需要净化名称、清理定义名称、删除无用名称、清除外部链接、清理Excel外部链接、去除外部引用、剥离链接、断链、粘死外链数据、干净xlsx、修复Excel打开时弹出更新链接提示导致卡死时使用。"
license: Proprietary. LICENSE.txt has complete terms
---

# XLSX Purge

ZIP/XML 层净化 xlsx，不依赖 Excel COM。对应 QSBar 插件的「净化名称」和「删除外部链接」两个按钮。

## 先选模式

| 用户说 | `--mode` | 做什么 |
|--------|---------|--------|
| 净化名称、清定义名称、删无用名称 | `names` | 只清名称。**公式一律不动，外链原样保留**。指向外表但在用的名称也保留 |
| 清外部链接、断链、去外部引用 | `links` | 断外链。外部名称全删；引用外链或外部名称的公式先转值把数据保住；清 ZIP 残留。**未使用的正常名称不碰** |
| 清理干净、两个都要、没说清 | `all`（默认） | 两者都做 |

分开的理由：有时候就是需要引用外表。`names` 只清真正没人用的和坏掉的。

## 执行

净化 + 验证两条命令，2.5MB / 10 万条名称的文件全程约 3 秒：

```bash
python scripts/xlsx_purge.py "file.xlsx" "out.xlsx" --mode links
python scripts/verify.py "file.xlsx" "out.xlsx" --mode links
```

| 参数 | 说明 |
|------|------|
| `input` | 输入 .xlsx（必填） |
| `output` | 输出路径（可选，默认 `{input}_clean.xlsx`），不得与输入相同 |
| `--mode` | `names` / `links` / `all`（默认 `all`） |
| `--quiet` | 只输出体积统计 |

多文件逐一调用，各自独立验证。**必须用原始文件**，不在已部分清理的文件上重复跑。

## 验证（交付前强制）

跑一条命令，八项一次查完：

```bash
python scripts/verify.py "原文件.xlsx" "产物.xlsx" --mode links
```

`--mode` 跟净化时保持一致（决定要不要查外链三项）。超大文件可加 `--sample 5` 只比对前 5 个 sheet。输出 `ALL PASS (8/8)` 才算完，任何一项 FAIL 都会打印具体位置。

**不要另写比对脚本。** 值比对走 XML 层的缓存值，用 fastexcel / openpyxl 读回来比会因为 dtype/NaN 推断产生几十格假 differ —— 为这个假阳性排查过三分钟，换了三种读法才确认数据其实一格没变。同理 `customXml` 这类 part 常常声明 UTF-8 实为 UTF-16 BOM，原文件就 parse 不了，verify 已按「原来能 parse、现在不能」对比着报，不必理会。

查的八项：

| # | 检查项 | `names` | `links` / `all` |
|---|--------|:-------:|:---------------:|
| 1 | 逐格值比对与原文件一致 | 必须 | 必须 |
| 2 | 全部 XML parse 通过 | 必须 | 必须 |
| 3 | definedName 不含错误标记 | 必须 | 必须 |
| 4 | 孤立 shared formula = 0 | 必须 | 必须 |
| 5 | `t="str"` 单元格都还带 `<f>` | 必须 | 必须 |
| 6 | externalLinks 条目数 = 0 | — | 必须 |
| 7 | workbook.xml 无 `<externalReferences>` | — | 必须 |
| 8 | 残留 `[N]` 外部引用 = 0 | — | 必须 |

第 1 项最关键：转值只是把公式换成它自己算出的缓存值，任何一格数值变化都说明有 bug。verify 顺带打印净化前后的 `definedNames / extParts / [N]refs` 对照，不需要另跑探测命令。

用户手动确认：Excel 打开不弹「更新链接」、不进修复循环、抽查公式与数据正常。

## 判定规则

名称逐实例判定，同名不同 body 分开看。

| 类别 | `names` | `links` |
|------|:-------:|:-------:|
| `_xlfn` / `_xlpm` / `_xlcn`（新函数占位、LAMBDA 参数、数据连接） | 保留 | 保留 |
| `_xlnm` / `Print_Area` 等内置 | 坏则删 | 坏或外部则删 |
| 长得像单元格引用（`AA`、`AB1`）或纯数字 | 保留 | 保留 |
| 空 body 或含 `&quot;` 实体（HTML 粘贴残渣） | 删 | 删 |
| 含 `#REF!` `#NAME?` 等错误标记 | 删 | 删 |
| 指向外部文件 | 未使用才删 | 全删 |
| 正常且被引用 | 保留 | 保留 |
| 正常但没人引用 | 删 | 保留 |

**外部判定**：body 含 `:\` `\\` `://`，或 `[...]` 里是纯数字索引 / 工作簿扩展名 / 带路径分隔符。`Table1[列名]` 这类结构化表引用不算。外部性沿名称链传播 —— 引用了外部名称的名称同样算外部。

**在用判定**：扫全部 sheet 的公式、数据验证 `formula1/2`、条件格式 `formula`，切出标识符查名称表。工作表名和字符串常量先剥离，紧跟 `(` 的是函数调用，单元格引用形式不算名称。在用关系沿名称链正向传播。

sheet 之外还要扫 pivotCacheDefinition 的 `<worksheetSource name="X"/>`（透视表数据源，是裸名称不是公式）、图表 `<c:f>`、表格的计算列/汇总行公式、queryTable 和 connections —— 漏扫这些，透视表和图表正在用的名称会被当孤名删掉。

**公式转值**（仅 `links` / `all`）：命中 `[N]` 外部引用，或引用了待删的外部/坏/垃圾名称。没人引用的名称不进这个集合 —— 万一在用判定漏了，也不至于大面积粘死正常公式。shared formula 整组一起转，单元格本身从不删除。

## 相关

- 改脚本前先读 [references/implementation-notes.md](references/implementation-notes.md)，那里记着 12 个踩过的坑
- 清理是 `document-ingest`、`pk-boq-merge` 等后续处理的前置步骤
