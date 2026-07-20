# 报价资料处理全流程

从 PDF 报价资料到标准化 Excel 报价表、再到 Librarian 价格数据库入库的端到端处理管线。

## 流程概览

```
PDF 报价资料（单份或多份）
  │
  ├── Phase 1: PDF → MD 提取
  │   读取 PDF 文字/表格 → 整理为结构化 Markdown
  │   输出：每份 PDF 对应的 .md 文件（source note）
  │
  ├── Phase 2: 数据抽取 → Excel
  │   从 MD 提取结构化数据 → 定义 ALL_DATA 元组列表
  │   → build_quotation_xlsx.py 生成标准化 Excel
  │   输出：人材机价格表 .xlsx（含来源列、分组标题行）
  │
  └── Phase 3: Librarian 入库
      将 MD source note ingest 到图书馆
      → query_material_price 可检索报价数据
```

## Phase 1: PDF → MD 提取

### 输入

PDF 报价资料，通常包含：
- 价格表（表格形式，含名称/规格/单位/单价/日期等列）
- 技术说明/项目特征描述
- 元信息（发布机构、生效日期、法律依据等）

### 处理步骤

1. **提取文字**：用 PyMuPDF (fitz) 或 markitdown 提取 PDF 文本
2. **识别结构**：定位表格区域、提取行列数据
3. **整理 MD**：按以下结构写 Markdown 文件

### MD 输出规范

```markdown
# 标题（含公告编号/年份）

**日期**: YYYY-MM-DD
**生效日期**: YYYY-MM-DD
**发布**: 来源机构
**法律依据**: 适用法规（如有）

---

## 费率表

| # | 名称 | 等级 | 单价（单位/天） |
|---|------|------|------------------|
| 1.1 | 职业名称 | 1级 | **400** |

---

## 项目特征说明

### 1.1 职业名称
- **1级 (400单位/天)**: 技能描述...
- **2级 (500单位/天)**: 技能描述...
```

### 关键原则

- **保留原文信息**：不删减技术描述，项目特征是后续校验的依据
- **统一日期格式**：YYYY-MM-DD
- **标注货币单位**：铢/天、元/t、美元/gal 等
- **编码体系**：若原文无编码，按 `组号-职业序号-等级` 分配，如 `L-N3-001`

## Phase 2: 数据抽取 → Excel

### 数据文件格式

创建 Python 数据文件（如 `merge_data.py`），定义 `ALL_DATA` 列表。

**短格式（8 元组）**：

```python
ALL_DATA = [
    ("分组名", "编码", "专业", "名称", "项目特征描述",
     单价(int/float), "YYYY-MM-DD", "来源文件名.pdf"),
]
```

**长格式（12 元组）**：

```python
ALL_DATA = [
    ("分组名", "编码", "专业", "名称", "项目特征描述",
     "单位", 单价, "YYYY-MM-DD", "币种",
     "来源文件名.pdf", "供应商", "备注"),
]
```

### 编码建议

| 编码格式 | 适用场景 |
|----------|---------|
| `L-N3-001` | 人工费（Labor），公告 N3，序号 001 |
| `M-N4-001` | 材料费（Material），公告 N4，序号 001 |
| `E-N5-001` | 设备费（Equipment），公告 N5，序号 001 |

### 生成 Excel

```bash
# 方式 1：直接执行数据文件
python merge_data.py

# 方式 2：CLI 调用通用脚本
python build_quotation_xlsx.py \
  --data merge_data.py \
  -o output.xlsx \
  --title "人材机价格表 — XXX" \
  --subtitle "P【人工费】- XXX"
```

### Excel 输出规格

| 特性 | 说明 |
|------|------|
| 模板 | 人材机价格表，16 列 (A-P) |
| 标题行 | Row 1 合并单元格，14pt 加粗 |
| 表头行 | Row 2，蓝底 D9E1F2，11pt 加粗 |
| 副标题 | Row 3，9pt 加粗 |
| 分组标题 | 绿底 E2EFDA，合并行，《组名》格式 |
| 数据行 | 10pt，居中/左对齐按列类型 |
| 来源列 | P 列，记录 PDF 文件名 |
| 汇总行 | 末尾，来源列表 + 价格统计 |
| 列宽 | A:16 B:14 C:40 D:60 E:8 F:12 G:10 H:12 I:14 J:8 K:22 L:6 M:6 N:8 O:30 P:40 |

## Phase 3: Librarian 入库

### 入库 MD source note

```bash
# 方式 1：MCP 工具
mcp__librarian__ingest_source "DocWork/.../xxx.md"

# 方式 2：CLI
python -m librarian_mcp.cli ingest "DocWork/.../xxx.md" --reindex
```

### 验证可检索

```bash
python -m librarian_mcp.cli query-material-price "TIG焊工"
# 或通过 MCP 工具：mcp__librarian__query_material_price
```

### 入库后效果

- `query_material_price "关键字"` 可检索到对应条目
- `list_price_sources` 列出该 MD 为一个价格数据源
- 索引按 source_note 关联，更新 PDF 后 reindex 即可刷新

## 多源合并场景

当有多份同类 PDF（如不同年份的同一公告系列）：

1. 每份 PDF → 独立 MD（Phase 1）
2. 定义一个数据文件，定义多个 `*_DATA` 列表，合并为 `ALL_DATA`
3. 按时间顺序排列 `ALL_DATA = DATA_OLD + DATA_NEW`
4. 每条记录来源列标注对应 PDF 文件名
5. 生成单一合并 Excel → 入库所有 MD

## 与 pk-boq 其他流程的关系

```
报价资料处理（本流程）
  └── 产出：标准化人工/材料/设备单价表
        └── 可供 merge_boq.py 引用
              └── 作为套定额/组价的价格依据
```
