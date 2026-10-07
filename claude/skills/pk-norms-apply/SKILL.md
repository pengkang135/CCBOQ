---
name: pk-norms-apply
description: "BOQ套定额同步维护：唯一项表 → 主清单回写（BQ Code精确匹配）。按列名自动定位，不依赖列号。触发词：套定额同步、定额回写、norm sync。"
license: Proprietary. LICENSE.txt has complete terms
---

# pk-norms-apply — BOQ 定额套用与同步维护

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


## 数据流

```
主清单 (Master BOQ, 万行级明细)          唯一项表 (Unique items, 千行级)
┌────────────────────────────┐            ┌──────────────────────────────────┐
│ N: BQ Code (公式列)         │            │ H: BQ Code (透视表行标签)          │
│ O: Norm Code ◀── 回写 ─────│─ BQ Code ─│ M: Norm Code2 (手动套定额/修正)    │
│ P: Norm Name ◀── 回写 ─────│─ lookup ─ │ N: Norm Name2 (手动套定额/修正)    │
│                            │            │ O: Unit2     (手动填写)            │
└────────────────────────────┘            │ F: Norm Code (透视内，回写后可见)  │
                                          │ G: Norm Name (透视内，回写后可见)  │
                                          └──────────────────────────────────┘
```

唯一项表右侧的 Norm Code2 / Norm Name2 / Unit2 是手动填报区（透视表外静态列），脚本按**列名**自动定位。

Sheet 名称因文件而异，由 `_norms_config.json` 记录，`discover_config.py` 自动探测并生成。

## BQ Code 公式（主清单 N 列）

```
=LOWER(REGEXREPLACE(TRIM(T), "[^\w\s]", "")) & "|" & LOWER(TRIM(W))
```

去除描述中所有标点符号后小写化，以 `|` 拼接单位。T+W 唯一性 99.97%。

Python 端同步时用 B 列（原始描述）复制 T 列的正则逻辑（去除编号前缀），加上 W 列（leaf unit），计算 BQ Code，不依赖公式缓存值。

## 操作流程

### 1. 配置发现（换新文件时）

```bash
python scripts/discover_config.py <workbook.xlsx>
```

自动识别哪个 sheet 是主清单（万行级、含 Quantity 列）、哪个是唯一项表（千行级、含 BQ Code 列）。如有多候选会打印警告，此时需人工确认并修改 JSON。

### 2. 手动套定额

在唯一项表的 **Norm Code2** / **Norm Name2** / **Unit2** 列手动填写定额编号、名称、单位。优先填 Norm Code2。

### 3. 回写到主清单

跟我说"同步"，脚本自动：
1. 按列名扫描唯一项表 → 定位 Norm Code2 / Norm Name2 / BQ Code
2. 按列名扫描主清单 → 定位 Norm Code / Norm Name / Description / Unit
3. 以 BQ Code 精确匹配，将手动填写的定额号写入主清单对应列

```bash
python scripts/sync_norms.py <workbook.xlsx> [--dry-run]
```

### 4. 刷新透视表

回写后在 Excel 中刷新唯一项表的透视表，F/G 列即显示最新的 Norm Code / Norm Name。

### 5. 增量修正

直接修改 Norm Code2 / Norm Name2 列，再次 sync 覆盖。

## 列名自动定位

脚本不硬编码列号，运行时扫描 header 行按列名定位：

| 表 | 查找的列名 | 策略 |
|----|-----------|------|
| 唯一项表 | Norm Code2, Norm Name2, Unit2 | 优先精确匹配 "2" 后缀，回退到最右侧匹配 |
| 唯一项表 | BQ Code | 首次匹配 |
| 主清单 | Norm Code, Norm Name | 首次匹配 |
| 主清单 | Description | 首次匹配（含编号前缀的原始描述） |
| 主清单 | Unit | 最右侧匹配（leaf unit） |
| 主清单 | Quantity | 首次匹配 |

只要列头文字不变（忽略大小写、空格、下划线），列位置可任意调整。

## 配置文件

```json
{
  "master_sheet": "ZOO BQ",
  "master_header_row": 3,
  "master_data_start": 5,
  "unique_bq_sheet": "UniqueBQ",
  "unique_bq_header_row": 4,
  "unique_bq_data_start": 5
}
```

仅记录 sheet 名和起始行，列位置完全由运行时按列名自动检测。

## 脚本清单

| 脚本 | 作用 |
|------|------|
| `discover_config.py` | 自动探测 workbook 结构，生成配置文件 |
| `sync_norms.py` | 唯一项表 Norm Code2 → 主清单 Norm Code 回写 |

## 关键设计

- **列名定位**：不硬编码列号，按 header 名自动查找，列移位不受影响
- **B 列读取**：从主清单 B 列（原始描述）Python 端计算 BQ Code，不依赖 N/T 列公式缓存值
- **手动列在透视表外**：Norm Code2 / Norm Name2 / Unit2 不参与透视，刷新不丢数据、不错位
- **幂等**：B+W 列是静态文本，可在任意代输出文件上重复运行
- **无定额BQ依赖**：唯一项表直接作为定额编辑界面，不需要中间快照表
