---
name: pk-boq-price-match
description: "BOQ 清单单价套价：将源清单（报价文件）中的单价按项目编号+名称+单位匹配到目标清单（单位必须完全一致），写入单价和合价公式列。适用于两个清单报表间转套单价、不同方案报价对比、任意两份BOQ间的价格匹配。典型触发词：套价、转单价、匹配单价、套价格、填写单价、报价套用、引用XX单价、XX价格填到XX清单、两个清单对价格。"
---

# PK BOQ — 单价套价

> 清单合并/整理 → `pk-boq-organize` | 对比校验 → `pk-boq-compare`
> 工程造价约定、Excel 兼容性 → `pk-boq` 技能

## 工作流程（七阶段）

```
1. 探测源清单 → 识别列结构 + 章节层级（顶级字母编号/描述关键词）
2. 探测目标清单 → 识别列结构 + 章节层级（【】/《》/{} 或编号层级）
3. 章节映射：提取关键词，建立源→目标章节对应关系
4. 章节内匹配（两级，范围限定在当前章节内）：
   a. 编号精确匹配（含名称校验 score ≥ 50%）
   b. 名称模糊匹配（token_sort_ratio ≥ 85%，单位必须一致）
5. 写入前验证：
   a. 完整性：源清单全部叶子节点 BOQ工程量 总和 ≈ 匹配项工程量总和
   b. 合理性：目标清单合价合计与源清单合价合计偏差 ≤ 50%
   c. 按章节输出匹配统计，定位未匹配项原因（单位不匹配/名称差异/结构性缺项）
6. 写入目标文件：
   - 单价为硬编码数值（全部匹配项写入）
   - 合价 = 单价 × Qty（Excel 公式），仅源有合价值的项才写入
   - 源清单无对应章节的行留空
7. .xlsm 安全：检测并修复 Qty 列的 PRODUCT 公式（openpyxl 不保留 .xlsm 公式）
```

验证不通过时应向用户报告未匹配项和偏差，按章节逐项说明原因，由用户决定是否继续。

## 脚本

```bash
python scripts/transfer_prices.py \
  --source source.xlsx --source-sheet "报价清单" \
  --target target.xlsm --target-sheet "FHDI清单" \
  --source-col-no A --source-col-name B --source-col-unit D --source-col-price F --source-col-qty E \
  --target-col-no D --target-col-name E --target-col-unit F --target-col-qty I \
  --schemes "原案-钢管桩" "代案-PHC桩" \
  --output output.xlsm
```

| 参数 | 说明 |
|------|------|
| `--source` | 源清单文件（提供单价的一方） |
| `--source-sheet` | 源清单 sheet 名（单方案时）；多方案时每个方案名作为 sheet 名 |
| `--source-col-no/name/unit/price/qty` | 源清单列映射（Excel 列字母，如 A, B） |
| `--target` | 目标清单文件（接收单价的一方） |
| `--target-col-no/name/unit/qty` | 目标清单列映射 |
| `--schemes` | 方案名称列表，每个方案插入两列（单价+合价） |
| `--target-true-qty-col` | 目标清单实际工程量列（用于修复 Qty 公式，如 G） |
| `--target-factor-col` | 目标清单放大系数列（用于修复 Qty 公式，如 H） |
| `--dry-run` | 仅验证匹配，不写入文件 |
| `--header-rows` | 表头行数（默认 4） |

## Python API

```python
from transfer_prices import (
    extract_src_with_chapters,    # 带章节归属的源条目提取
    extract_tgt_with_chapters,    # 带章节归属的目标条目提取
    map_chapters,                 # 源→目标章节映射
    match_item_in_chapter,        # 章节内单项匹配
    verify_match_per_chapter,     # 按章节验证
)

src_items = extract_src_with_chapters('source.xlsx', 'Sheet1', ...)
tgt_items, chap_map = extract_tgt_with_chapters('target.xlsm', 'BOQ', ...)
chapter_map = map_chapters(src_items, tgt_items)  # {'D': 'D', 'E': 'E', ...}

target_row = match_item_in_chapter(src_items[0], tgt_items, chapter_map)
report = verify_match_per_chapter(src_items, tgt_items, chapter_map)
```

## 匹配算法细节

### 章节识别与映射（阶段 1-3）

**为什么要按章节匹配**：全局匹配容易产生跨章节误匹配（不同章节可能有相同编号但不同含义的条目）。章节约束后匹配精度显著提高。

**源清单章节识别**：按顶级编号层级检测章节头。常见模式：
- 单字母编号：`C` → DREDGING, `D` → RECLAMATION, `E` → QUAY
- 章节头特征：有代码、有描述、**无单位列**
- 叶子节点归属：数据行继承最近一次检测到的章节头

**目标清单章节识别**：按格式标记检测层次结构：
- `【...】` 一级章节（如 `【F-C_Dredging 】`）
- `《...》` 二级章节
- `{...}` 三级章节（方案/选项级别）

**章节映射**：从章节名称中提取关键标识符建立对应关系：
- 字母编号（C/D/E/F/I）— 最直接的映射键
- 工程描述关键词（Dredging/Reclamation/Quay/Yard/Gate）
- PER 编号（PER 003/004/005/006/009）

**多方案变体处理**：目标清单可能有多个方案变体（如 F-E_Quay 有 3 个【】章节），所有变体均套入相同单价。验证时按变体分开报告。

### 空名称继承

源清单中常有省略名称的子项（如混凝土章节下的钢筋子项）。处理方式：
```python
effective_no = no if no else last_no      # 空编号→继承上级编号
effective_name = name if name else last_name  # 空名称→继承上级名称
```
继承链在每次遇到非空编号/名称时更新。

### 叶子节点与匹配约束

**叶子节点**：同时有"单位"和"单价"的行。排除章节标题、汇总行（如`合计`/`Sub-Total`）。

**章节内两级匹配**（匹配范围限定在当前章节的目标条目内）：

| 优先级 | 方法 | 阈值 | 说明 |
|--------|------|------|------|
| 1 | 编号精确匹配 | 名称相似度 ≥ 50% | 在当前章节内查找；多个同名编号取名称最相似者 |
| 2 | 名称模糊匹配 | token_sort_ratio ≥ 85% | 在当前章节内查找；**单位必须完全一致**，仅在编号匹配失败时回退 |

**匹配三要素**：编号、名称、单位。其中**单位是硬约束** —— 无论哪级匹配，单位必须完全相等（case-insensitive），否则直接跳过。

**常见未匹配原因**（按章节报告）：
- **单位不匹配**：源 `[t]` vs 目标 `[m3]` — 通常因一方将钢筋/混凝土拆分而另一方合并计价
- **结构性缺项**：源有独立子项而目标无对应条目（如钢筋子项）
- **名称差异过大**：同一物料在两个清单中描述方式差异超过阈值

名称匹配使用 `rapidfuzz.fuzz.token_sort_ratio`（对词序不敏感）。名称预处理：`re.sub(r'\s+', ' ', s.strip())` 压缩多余空白。

## .xlsm 文件安全

openpyxl 加载/保存 .xlsm 时会损坏未缓存的公式单元格（如 `=PRODUCT(G,H)`）。处理方式：

1. 检测 Qty 列是否有公式
2. 从 TrueQty 列 × Factor 列在 Python 中重新计算 Qty 值
3. 写入前将公式替换为硬编码数值
4. 使用 `keep_vba=True` 保留 VBA 宏

如果目标文件 Qty 列已是硬编码值，此步骤无操作。

## 输出列

每个方案在目标清单最右侧插入 1-2 列：

| 列 | 英文标题 | 中文标题 | 内容 | 写入条件 |
|----|---------|---------|------|---------|
| 单价 | `{SchemeName} Unit Price` | `{SchemeName} 单价` | 匹配到的数值 | 全部匹配项 |
| 合价 | `{SchemeName} Amount` | `{SchemeName} 合价` | `=单价单元格*Qty单元格` | 仅源清单有合价值时 |

**合价选择性写入**：源清单中常有"单价已填、合价未填"的条目（施工类项目尤其常见）。写入前检查源清单合价列是否有值（`> 0`），无值的条目只写单价不写合价公式。

**无对应章节**：源清单无对应章节的目标行（如目标有 B/G/H 章节但源清单不覆盖），单价和合价列均留空。
