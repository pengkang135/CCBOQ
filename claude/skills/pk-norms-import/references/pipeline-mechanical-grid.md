# Path M: Mechanical Grid (纯机械网格填充法)

纯确定性算法，从 PDF bbox 坐标数据直接生成 2D 网格 → 1D 记录 → SQLite。不依赖 AI/LLM，不依赖启发式规则。

## 适用场景

| 场景 | 推荐路径 |
|------|---------|
| 文本型 PDF，AI API 不可用/太贵 | Path M |
| 图片型 PDF，OCR 坐标数据已有 | Path M（替代 text_to_md.py 的表格识别） |
| 文本型 PDF，表格结构复杂需要语义理解 | Path A（AI） |
| 需要最快速度处理大批量页面 | Path M |

**核心优势**: 零 API 调用、确定性可复现、毫秒级/页。

**核心局限**: 属性名/值的语义理解不如 AI（用关键词匹配替代），不适合表头结构极度不规则的表格。

## 数据流

```
PDF bbox 坐标数据 (.json)
  → mechanical_grid_all.py  →  2D grid JSON (填充后)
  → mechanical_grid_to_db.py  →  SQLite (quota_table + quota_item)
  → gen_viewer_html.py  →  HTML 可视化页面
```

## 算法概述

### Step 1: 行分组 (row grouping)

按 y 坐标聚类，容差 5px，同属一行的 text blocks 归并。

### Step 2: 列检测 (column detection)

两阶段列检测：

**Phase 1 — 值列 (value columns)**: 从 5 位定额编号 (`\d{5}`) 的 x 位置聚类出值列锚点。每个值列对应一个定额编号。

**Phase 2 — 固定列 (fixed columns)**: 值列左侧的文本块按 left-edge 聚类。包括：序号列、费用项目列、单位列、代码列。

### Step 3: 合并行处理 (multi-line row merging)

数据行可能跨多行（长文本换行）。算法：
- 标记数据行 (is_data) vs 续行
- 每个续行按 y 坐标就近分配到最近的数据行
- 固定列区域的续行文本按从上到下拼接
- 值列区域的续行文本按坐标列对齐

### Step 4: 网格填充 (grid filling)

"先写先得" (first-writer-wins) 填充策略：
- 合并单元格 (colspan > 1)：文本块中心落在哪个列就写入哪个列，同时标记跨越的列范围
- 窄文本：按中心点分配到列
- 宽文本（跨越多列）：按 bbox 重叠面积最大的列分配
- 空白/dash 占位：`－` 或 `—` 自动识别

### Step 5: 2D → 1D (grid_to_1d)

数据驱动列识别（不依赖表头标签）：

1. **值列识别**: header 行中含 `\d{5}` 的列
2. **代码列识别**: data 行中 `\d{11,12}` 匹配最多的固定列
3. **单位列识别**: data 行中单位正则匹配最多的固定列
4. **费用项目列**: 剩余固定列（排除序号列）
5. Fallback: 数据不足时回退到表头标签匹配 ("代码"、"单位")

每个值列 × 每行费用项目 = 一条 1D 记录。

### Step 6: 续表链处理

- `is_continued_table()`: 检测 header 行中是否有 5 位定额编号
- `build_chain_groups()`: 连续页面分组为 (主页, [续表1, 续表2, ...]) 链
- 续表继承主页的表头结构（属性维度、定额编号列）
- 整个链合并写入一个 `quota_table`，记录数 = 每页记录数之和

## 关键脚本

| 脚本 | 位置 | 作用 |
|------|------|------|
| `mechanical_grid_all.py` | `scripts/` | 主提取脚本：坐标→2D grid JSON |
| `mechanical_grid_to_db.py` | `scripts/` | 桥接脚本：2D grid JSON→SQLite |
| `gen_viewer_html.py` | Norms-AI `temp/scripts/` | HTML 可视化生成器（含 grid_to_1d） |

## 运行方式

```bash
# Step M1: 坐标→2D grid JSON (在 Norms-AI 项目中)
cd Norms-AI
python temp/scripts/mechanical_grid_all.py \
    --text-dir output/intermediate/text/ \
    --pages 84,85,86,87,296,297,515,597,726,727 \
    --output temp/

# Step M2: 2D grid JSON→SQLite (使用技能脚本)
python scripts/mechanical_grid_to_db.py \
    --grid-dir Norms-AI/temp/ \
    --structure Norms-AI/output/structure.json \
    --db Norms-AI/output/quota_data.sqlite
```

## DB Schema 兼容性

Path M 写入的 `quota_table` 和 `quota_item` 与 Path A/B 完全兼容：

| 字段 | Path M 值 | 说明 |
|------|----------|------|
| `quota_table.source` | `mechanical_grid` | 区分于 AI 提取 |
| `quota_item.ocr_source` | `mechanical_grid` | 区分于 OCR 来源 |
| `quota_item.data_quality` | `mechanical_grid` | 区分于 AI 提取质量标记 |
| `quota_item.attr1_label~4_label` | 关键词匹配 | 比 AI 提取粗糙 |

## 属性标签提取

机械方法不做语义理解，属性标签通过关键词匹配推断：

```python
# 匹配包含这些关键词的表头文本
keywords = ['类别', '级别', '类型', '容', '吨位', '长', '距', '径']
```

短文本 (≤6 字符) 也会作为候选属性名。这比 AI 精度低，但覆盖面广。

## 验证

`mechanical_grid_to_db.py` 入库后自动打印：
- 总表数、总条目数
- 独立定额编号数
- 每链的页数和条目数

额外验证可运行：
```bash
python temp/scripts/validate_1d.py  # 1D 输出完整性校验
```
