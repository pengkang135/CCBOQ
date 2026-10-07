# 拆分询价包 — BOQ 清单拆分工作流

将总承包 BOQ 清单按分包询价范围拆分为独立的询价清单文件。以基础清单模板为框架，从各设计院清单中提取对应分部/子分部，清理不相关项后组成分包询价 BOQ。

## 自动化脚本

优先使用 `split_inquiry_boq.py` 完成标准拆分。该脚本以 `combine.xlsx`（含 B101-B105、A_Prelims）为骨架，从各设计院清单中按 `--match` 模式匹配目标 sheet，完整复制（值 + 全部样式 + 列宽行高 + 合并单元格），自动修复 FHDI 表头 `#REF!` 错误。

```bash
python scripts/split_inquiry_boq.py \
    --template "Standards Pacakge/6. BOQ/Schedule of Prices-Breakdown(combine).xlsx" \
    --source "WTCC. Schedule of Prices - breakdown.xlsx" --label WTCC \
    --source "FHDI.Schedule of Prices-FHDI-0506-提交.xlsx" --label FHDI --fix-ref "1" \
    --match "E_Quay" \
    --output "SubContractor/2.2.1 Quay Works/6. BOQ/Schedule of Prices - breakdown.xlsx"
```

| 参数 | 说明 |
|------|------|
| `--template` | 基础模板 xlsx（含 B101-B105, A_Prelims 等通用 sheet） |
| `--source` | 设计院 BOQ 源文件路径（可重复指定） |
| `--label` | 设计院标签，与 `--source` 一一对应（如 WTCC/FHDI/SHCC） |
| `--fix-ref` | 对指定 `--source`（0-based index）启用表头 #REF! 修复，用逗号分隔（如 `"1"` 或 `"0,1"`) |
| `--match` | sheet 名称匹配模式（如 `E_Quay`） |
| `--output` | 输出 xlsx 路径 |

**核心规则**：以模板为骨架不修改模板格式；完整 sheet 复制保留所有列（WTCC 50 列、FHDI 48 列）；自动识别方案标识（OPT1/OPT2/方案一/方案二）；输出端 0 `#REF!` 错误。

仅在以下场景按下方手动流程操作：需要仅保留某子分部（而非完整 sheet）、需要修正公式行号、需要清理 B105 外部链接。

## 适用范围

任何需要从总承包 BOQ 中按专业分包范围提取清单项目、组装独立询价清单文件的场景。

## 标准文件结构

最终的询价清单文件与参考包的结构一致：

```
{包编号} {包名称}/
└── 1.BQ/
    └── Schedule of Prices - breakdown.xlsx    # 询价清单（唯一输出文件）
```

文件内部 sheet 结构：
- **通用 sheet**（来自基础模板）：B101 Preamble, B102 Cashflow, B103 Standby Rates, B104 Dayworks, B105 BoQ Grand Summary, A_Prelims
- **专业 sheet**（来自各设计院）：`{分部名}（序号.设计院-方案）` 格式，仅保留目标子分部

## 工作流

### Step 1: 确定目标范围

从询价包名称确定对应的 BOQ 分部/子分部/分项。需要理解 BOQ 的层级结构：

| 层级 | 示例 | 说明 |
|------|------|------|
| Class/分部 | Class E — Quay | 大类，对应一个 sheet |
| Section/子分部 | E.2 — Quay Furniture | 子分部，是拆分的最小保留单元 |
| Item/分项 | E.2.1 — Crane rail including fastening system | 具体清单条目 |

**识别方法**：
1. 在源文件的各设计院 sheet 中搜索关键词（如 `rail`, `钢轨`, `crane rail`）
2. 确定匹配项所在的子分部编码（如 `E.2`）
3. 确认该子分部下所有条目是否都属目标范围（是则全保留，否则可进一步删减）

**重要区分**：
- 同一 Class 下的不同于分部（如 E.1 Quay Structure vs E.2 Quay Furniture）→ 不相关的必须删除
- 同一子分部下的不同分项 → 不相关的可以删除
- 分部说明文字（Preamble/Notes/规格说明）→ 保留

### Step 2: 确定源文件

需要三类文件：

| 文件 | 用途 |
|------|------|
| 基础模板 | 提供通用 sheet（B101-B105, A_Prelims），作为输出工作簿的骨架 |
| 设计院 A 清单 | 提供该院版本的清单 sheet，含完整 BOQ 结构 |
| 设计院 B 清单 | 提供另一院版本的清单 sheet |
| 参考询价包 | 已完成的分包询价清单，用于验证输出结构和做法 |

### Step 3: 分析 sheet 结构

在复制前必须明确：

1. **各源 sheet 的完整行列范围**（max_row × max_column）
2. **目标子分部的精确行号边界**（起始行、SUBTOTAL 行）
3. **表头区域的行数**（通常 8-12 行，含项目信息 + 列标题 + Class 标题）
4. **各 sheet 的列布局差异**（不同设计院列数和位置可能不同，保持原样即可）

使用 openpyxl 读取结构：

```python
import openpyxl
wb = openpyxl.load_workbook(source_file)
ws = wb[sheet_name]
print(f'{sheet_name}: {ws.max_row} rows x {ws.max_column} cols')
# 搜索分部标记（E.1, E.2, SUBTOTAL 等）
```

### Step 4: 复制 sheet 到基础模板

**核心原则**：连同表单一起复制，不得破坏原表结构。复制完整 sheet 后再删除不相关项。

使用 openpyxl 跨工作簿复制 sheet，需要逐行复制单元格（值 + 样式）：

```python
from copy import copy

def copy_row(src_ws, src_row, dst_ws, dst_row):
    for col in range(1, src_ws.max_column + 1):
        src_cell = src_ws.cell(row=src_row, column=col)
        dst_cell = dst_ws.cell(row=dst_row, column=col)
        dst_cell.value = src_cell.value
        if src_cell.has_style:
            dst_cell.font = copy(src_cell.font)
            dst_cell.border = copy(src_cell.border)
            dst_cell.fill = copy(src_cell.fill)
            dst_cell.number_format = src_cell.number_format
            dst_cell.alignment = copy(src_cell.alignment)
```

复制内容：
- 表头区域（1 到表头末行）
- 目标子分部区域（分部标题行到 SUBTOTAL 行）
- 列宽、行高、合并单元格

**不复制**：目标子分部以外的所有行。

### Step 5: 公式行号修正

**关键问题**：从原始 sheet 复制到新位置后，公式中的行号引用仍然是原始行号，必须修正。

使用正则替换公式中的行号：

```python
import re

def adjust_formula(formula, old_row_start, new_row_start, row_count):
    if formula is None or not isinstance(formula, str) or not formula.startswith('='):
        return formula
    row_offset = new_row_start - old_row_start
    def replace_row(match):
        col_part = match.group(1)
        row_num = int(match.group(2))
        if old_row_start <= row_num < old_row_start + row_count:
            return f'{col_part}{row_num + row_offset}'
        return match.group(0)
    return re.sub(r'([A-Z]+)(\d+)', replace_row, formula)
```

验证修正后的公式：
- `SUM` 范围是否正确指向当前行
- `D{n}*G{n}` 乘法引用是否在正确行
- `SUBTOTAL` 范围是否正确覆盖所有条目行
- 跨 sheet 引用（如 `'B105 BoQ Grand Summary'!A1`）是否保持完整

### Step 6: 处理 #REF! 错误

FHDI 等设计院源文件的表头可能包含 `#REF!`（因源文件缺少对应 sheet）。复制到含有所需 sheet 的目标工作簿后，需手动修正：

```python
HEADER_FIX = {
    (1, 1): 'Project:',
    (1, 2): '{项目名称}',
    (3, 1): 'Contract:',
    (3, 2): '{合同名称}',
    (4, 1): 'Subject:',
    (4, 2): 'Part II - Volume B - Schedules',
    (5, 2): 'Item B105 - Schedule of Prices & Unit Rate Breakdown',
}
for (r, c), val in HEADER_FIX.items():
    cell = ws.cell(row=r, column=c)
    if cell.value is not None and '#REF!' in str(cell.value):
        cell.value = val
```

### Step 7: 清理 B105 Grand Summary

B105 通常含大量指向不存在 sheet 的外部工作簿引用（如 `'[1]B_Prep Works'!O41`）。参照参考文件的做法：

- 仅保留 `Class A — Preliminaries` 的公式引用（指向 `A_Prelims`，该 sheet 存在）
- 其余 Class B-I 的外部引用清空或设为 0
- 保留 `TOTAL ACCEPTED CONTRACT AMOUNT` 的 `SUM` 公式

### Step 8: 验证

必检项目：

```python
# 1. 零 #REF! 错误
for sheet in wb.sheetnames:
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and '#REF!' in str(cell.value):
                print(f'#REF! at {sheet}!{cell.coordinate}')

# 2. 每个专业 sheet 包含必要元素
# - 分部标题（如 "E.2 | Quay Furniture"）
# - 目标分项（如 "E.2.1 | Crane rail"）
# - SUBTOTAL 行
# - 公式无断裂引用

# 3. sheet 数量 = 6 个通用 + N 个专业 sheet
```

## 关键技术要点

### BOQ 层级识别

在源文件中搜索分部/子分部边界时，不同设计院格式略有差异：

| 设计院 | 分部标识 | 子分部标识 | SUBTOTAL 格式 |
|--------|---------|-----------|---------------|
| WTCC | `Class E` / `E.1` | `E.2` / `E.2.1` | `SUBTOTAL - {Section Name}` |
| FHDI | `Class E` / `E.1` | `E.2` / `E.2.1` | `SUBTOTAL - {Section Name}` |

子分部编码通常在 A 列，分部名称在 B 列。SUBTOTAL 的 B 列含 "SUBTOTAL -" 前缀。

### 多方案处理

同一设计院可能有多个方案（如 OPT.1 / OPT.2）或多个结构段（如方案一/二/三）：

- 检查各方案的同一子分部内容是否相同
- 内容相同的仍应分别保留各方案 sheet，分包商可能需要对照不同方案
- sheet 命名中包含方案标识：`E_Quay(1.WTCC-OPT1)` / `E_Quay(2.FHDI-F1)`

### Sheet 命名规范

Excel sheet 名限制 31 字符。命名模式：

```
{分部缩写}（{序号}.{设计院}-{方案标识}）

示例：
E_Quay(1.WTCC-OPT1)       # WTCC，方案1
E_Quay(2.FHDI-F1)          # FHDI，方案1
```

### openpyxl 公式修正陷阱

`delete_rows()` 后 openpyxl 不会自动调整公式中的行号引用。**不要**使用"复制全 sheet → delete_rows → 保存"的方法。应该：

1. 仅复制需要的行到新 sheet
2. 在复制时调整公式行号
3. 直接写入正确的行号

### Office Excel 兼容性

- 避免在保留大量合并单元格的情况下使用 `delete_rows()`
- 新增 sheet 用逐行复制的方式，不触发修复模式
- 最终文件应在 Office Excel（非 WPS）中验证能直接打开

## 常见问题

### Q: 什么时候保留整个分部 vs 仅保留子分部？
- 如果整个分部都与分包范围相关（如地基处理 = 整个 D 分部），保留完整 sheet
- 如果仅一个子分部相关（如钢轨 = E.2），仅保留该子分部
- 判断标准：分部下其他子分部是否可能由同一分包商供货

### Q: 基础模板的 B102 Cashflow 等 sheet 中还有外部引用怎么办？
B102/B103/B104 作为询价包的参考模板保留结构即可，其中的外部引用通常不影响主体功能。如果引用断裂严重，参照参考文件的做法清理。

### Q: 设计院 sheet 之间的列结构不同怎么处理？
保持各设计院原有列结构不变。不同设计院的列数、列位置（Unit Rate 在第几列等）差异是正常的，分包商需要对照原始清单格式。

## 输出文件清单

一次标准拆分输出：

```
{包编号} {包名称}/
└── 1.BQ/
    └── Schedule of Prices - breakdown.xlsx
        ├── B101 Preamble          （通用）
        ├── B102 Cashflow          （通用）
        ├── B103 Standby Rates     （通用）
        ├── B104 Dayworks          （通用）
        ├── B105 BoQ Grand Summary （通用，已清理外部链接）
        ├── A_Prelims              （通用）
        ├── {分部}(1.{院A}-{方案})  （仅目标子分部）
        ├── {分部}(1.{院A}-{方案2}) （如有）
        └── {分部}(2.{院B}-{方案})  （仅目标子分部）
```
