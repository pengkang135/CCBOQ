---
name: excel-print-layout
description: Excel 打印排版修复——设置打印宽度（内容缩放一页宽）、插入竖向分页符（在锚点行之前/之后）、调整行高（修复合并单元格 wrap 文本显示不全、被截断）。当用户提到「分页符」「打印宽度」「一页宽」「缩放打印」「行高」「显示不全」「文字被截断/遮住」「合并单元格内容显示不出来」「AutoFit 失效」等，哪怕没明说 Excel，也要用本技能。所有写操作走纯 ZIP+lxml，绝不用 openpyxl 保存（会损坏文件）。
---

# Excel 打印排版

三个独立操作，可单独或组合使用：设置打印宽度、插入分页符、调整行高。核心价值是踩过一遍的坑——openpyxl 会损坏文件、AutoFit 对合并单元格无效、字符估算会高估——本技能用「纯 XML 写 + COM 实测」绕开这些坑。

## 铁律（动手前必读）

1. **绝不用 openpyxl 保存。** openpyxl `save()` 会丢掉媒体文件、printerSettings、webextensions、metadata、calcChain、sharedStrings，产物 Excel 可能打不开。openpyxl 只用来**读值/读样式**（`load_workbook`）；所有写操作走原生 ZIP+lxml 重写，其余 zip 条目原样搬运。四个脚本已经按这个原则写好，不要再引入 openpyxl 保存。
2. **AutoFit 对合并单元格无效。** 对合并单元格所在行调用 `AutoFit()` 会被重置回默认行高（约 13.8），不是按内容算。所以「临时单元格 AutoFit」才是测行高的正确手段（见下）。
3. **权威行高 = 临时单元格 AutoFit。** 在空行上按目标行的合并宽度 + 原字体排入文本，`WrapText=True`，再 AutoFit，读到的 RowHeight 就是 Excel 认可的 natural height。字符宽度估算对多行文本会系统性高估 1-2 行，只能做候选筛选，不能做最终值。
4. **分页符语义差 1。** OOXML `brk id=N` 表示「第 N 行之后分页」，新页首行 = N+1；COM `HPageBreaks.Location.Row` 返回的是「新页首行」。对比验证时要先 +1 再比。
5. **COM 集合迭代陷阱。** 不要用 `HPageBreaks(i)` 按索引取（会误报、可能抛异常），用 `for br in ws.HPageBreaks` 迭代。
6. **fitToWidth 会被 Excel 规范化为 scale。** XML 里写 `fitToWidth=1`，Excel 打开再保存会变成 `scale=N`，但 `sheetPr/pageSetUpPr fitToPage=1` 保留、打印宽度仍是 1 页。验证时以 COM 的 `PageSetup.FitToPagesWide` 为准。

## 环境

- Windows + 本机 Excel（COM 自动化 `pywin32`）
- Python 库：`openpyxl`（只读）、`lxml`、`pywin32`
- 中文路径/GBK 终端：脚本已内置 `sys.stdout` 重编码，bash 下 python `-c` 内联命令用单引号包裹

## 三个操作

### 操作 1 — 设置打印宽度（1 页宽）

让每张表横向缩放到一页宽，横向不溢出到第二页。

```bash
python scripts/page_layout.py "目标.xlsx" --fit-width 1
```

### 操作 2 — 插入分页符

让每页在锚点行处结束。锚点可用正则关键字自动定位，也可用行号显式指定：

```bash
# 在每个以「DATA ZONE」开头的行之后插分页符（该行留在本页底）
python scripts/page_layout.py "目标.xlsx" --break-after "^DATA ZONE"

# 在匹配行之前插分页符（匹配行成为新页首行）
python scripts/page_layout.py "目标.xlsx" --break-before "SCHEDULE \d+"

# 显式行号（1-based），在第 35、70、103 行之后插分页符
python scripts/page_layout.py "目标.xlsx" --rows "35,70,103"

# 组合：页宽 + 分页符一次搞定
python scripts/page_layout.py "目标.xlsx" --fit-width 1 --break-after "^页码块关键字"
```

> 正则用 `re.search`（**包含**匹配）。要精确锚定开头加 `^`、结尾加 `$`。例：`--break-after "DATA ZONE"` 会命中正文里任何提到 "DATA ZONE" 的行；`--break-after "^DATA ZONE"` 只命中以它开头的页脚行。

参数说明：

| 参数 | 作用 |
|------|------|
| `--fit-width N` | fitToWidth = N，1 = 一页宽。不传则不动打印宽度 |
| `--break-after REGEX` | 匹配行的**之后**插分页符（该行留本页底），可多次 |
| `--break-before REGEX` | 匹配行的**之前**插分页符（该行成新页首行），可多次 |
| `--rows "35,70"` | 显式行号，在每个行号之后插分页符 |
| `--cols "A,B"` | 正则匹配时检查的列，默认 `A,B` |
| `--output OUT` | 输出路径；缺省则先备份 input 到同目录 `temp/` 后就地覆盖 |

> 通用性说明：脚本不内置任何项目特定标记（如 DATA ZONE、CARRIED）。每页底部那行「页码/汇总/脚标」在清单类文档里通常有固定关键字，把它作为 `--break-after` 的正则传进来即可。若无法用关键字描述，就用 `--rows` 显式行号。

### 操作 3 — 调整行高

修复合并单元格 + wrap 多行文本的行显示不全。三步：

```bash
# 第一步：COM 实测各行所需自然行高（输出 JSON）
python scripts/measure_row_heights.py "目标.xlsx"

# 第二步：纯 XML 写回（先自动备份）
python scripts/apply_row_heights.py "目标.xlsx" --measures "temp/row_heights_measured.json"

# 第三步：验证
python scripts/verify_layout.py "目标.xlsx" --measures "temp/row_heights_measured.json"
```

`measure_row_heights.py` 内部逻辑：openpyxl 读值找出「合并单元格或 wrap + 多行文本」且当前行高不足的行，逐行在临时单元格 AutoFit 实测。参数：

| 参数 | 作用 |
|------|------|
| `--output` | 实测 JSON 路径，缺省 `temp/row_heights_measured.json` |
| `--hpt-base` | 每行高度基数（默认 13.2，Times New Roman 10pt 的校准值，仅用于候选筛选，不影响最终实测值） |
| `--tolerance` | 实测超现行高多少 pt 才调整，默认 2.0 |

## 验证（三操作通用）

```bash
python scripts/verify_layout.py "目标.xlsx" \
    --measures "temp/row_heights_measured.json" \
    --expect-wide 1
```

验证三件事：行高抽查是否等于期望值、每 sheet 打印宽度是否为 1 页宽、XML 手动分页符与 Excel 实际分页是否一致（分页符位置自动 +1 对齐语义）。

## 已知权衡（要主动告知用户）

- **行高 vs 页高**：调高行高会让每页可容纳的行数变少——原来一页放 55 行，行高调对后可能只放 48 行，剩余内容被 Excel 自动挤到下一页。这时某个逻辑区段可能被拆到两页，甚至插入额外的自动分页。这是「内容显示全」与「A4 物理页高」的必然冲突，除非牺牲行高或改字体/列宽，否则无法两全。验证时若出现「分页不符」，先判断是不是自动分页侵入了手动分页区间，而不是脚本写错。
- **末尾孤立的锚点行**：`--break-after` 直接匹配锚点行时，最后一张表的页脚块（后面没有下一张表了）也会被加分页符，末尾可能多一个空页。若要精确到「只对后面还有内容的页脚块加分页」，先用行号或更严的正则，或接受这个无害的空页。
- **显式行号超出数据范围**：`--rows "50,100"` 会强制给每个 sheet 插第 50/100 行分页符，但 Summary/Collection 这类短表可能只有 20~30 行，分页符落在数据末尾之后的空行上会被 Excel 忽略，`verify_layout.py` 会报「手动分页符丢失」。属正常，不是脚本写错——真实用法里 `--break-after` 正则只命中存在的行，不会这样。用 `--rows` 时要确认行号落在目标 sheet 的实际数据范围内。

## 脚本清单

| 脚本 | 作用 | 依赖 |
|------|------|------|
| `scripts/page_layout.py` | 页宽 + 分页符（纯 XML） | openpyxl, lxml |
| `scripts/measure_row_heights.py` | 实测行高（openpyxl 读 + COM） | openpyxl, lxml, pywin32, Excel |
| `scripts/apply_row_heights.py` | 写回行高（纯 XML） | openpyxl, lxml |
| `scripts/verify_layout.py` | 验证（COM） | lxml, pywin32, Excel |
