---
name: pk-norms-import-excel
description: >
  Import Excel-based quota/norms databases into SQLite. Handles merged cells,
  horizontal table layout, multi-dimensional attribute headers, and continued tables.
  Use when the user provides an Excel version of a construction quota/norms standard
  (JTS/T port engineering norms, civil BOQ norms, etc.) and wants structured
  database import. Triggers: "import Excel norms", "Excel定额导入", "Excel版定额库",
  "导入Excel定额", "Excel norms to database".
allowed-tools: Bash
metadata:
  updated_at: 2026-06-14
---

# Excel 定额库 → SQLite 导入

将 Excel 版定额标准结构化导入 Norms-AI SQLite 数据库。与 `pk-norms-import`（PDF 路径）共享 DB Schema 和浏览器。

## 两种文件格式

| 格式 | 文件示例 | 特征 | 解析脚本 |
|------|---------|------|---------|
| 单Sheet横向表 | JTS/T 276-1-2019 主定额 | 单Sheet，14362行×36列，5位定额编号在数据列顶 | `parse_tables.py` |
| 多Sheet纵向表 | JTS/T 276-3-2019 参考定额 | 87 Sheet，每Sheet一个表(10列)，多Sheet链为续表 | `extract_ref_final.py` |

## 工作流（4步流水线）

```
Excel .xlsx
  │
  ├── Step 1: excel_to_grid.py
  │   直接 XML 解析 → 填充合并单元格 → _grid.json
  │   绕过 openpyxl（兼容性问题），用 zipfile + defusedxml
  │
  ├── Step 1b: grid_to_md.py（可选检查）
  │   按章节生成 MD 表格 → 人工检查合并单元格填充正确性
  │
  ├── Step 2+3: 解析（按文件类型选择）
  │   ├── 单Sheet横向表 → parse_tables.py → _parsed.json
  │   └── 多Sheet纵向表 → extract_ref_final.py → _parsed.json
  │       （含目录解析 + 章节结构 + 属性维度 + 定额单位 + 注释）
  │
  ├── Step 4: load_to_sqlite.py
  │   document → chapter → section_text → norms_table → norms_item
  │
  └── Step 5: verify_import.py
      数据质量验证
```

## 快速开始

```bash
cd C:\Users\Kevin\.claude\skills\pk-norms-import-excel\scripts

# 主定额（单Sheet）
python excel_to_grid.py "主定额.xlsx"
python parse_tables.py "主定额_grid.json"
python load_to_sqlite.py "主定额_parsed.json"

# 参考定额（多Sheet）
python excel_to_grid.py "参考定额.xlsx"
python extract_ref_final.py "参考定额_grid.json"
python load_to_sqlite.py "参考定额_parsed.json" --title "..." --doc-number "..."

# 验证
python verify_import.py
```

## 各步骤详解

### Step 1: excel_to_grid.py

直接解析 Excel 内部 XML，填充合并单元格。**不依赖 openpyxl**（该库无法处理这些文件的某些 XML 格式）。

```bash
python excel_to_grid.py "input.xlsx"              # → input_grid.json
python excel_to_grid.py "input.xlsx" -o out.json  # 指定输出
```

**关键技术**：
- `zipfile` + `defusedxml.ElementTree` 解析 `xl/worksheets/sheet1.xml`
- 解析 `xl/sharedStrings.xml` 获取字符串
- 按"先写先得"规则填充合并区域（同 `mechanical_grid_all.py` 算法）
- 输出 `{ sheets: { "Sheet1": { rows: [{row, cells: {A:..., B:...}}] } } }`

### Step 1b: grid_to_md.py

将填充后的网格按章节分割为可读 Markdown 表格，用于人工检查合并单元格填充是否正确。

```bash
python grid_to_md.py "input_grid.json"             # → input_grid_md_pages/
```

### Step 2+3A: parse_tables.py（单Sheet横向表）

适用于 JTS/T 276-1-2019 主定额。识别横向布局：
- 描述列(A-J): 顺序号、项目名称、单位
- 数据列(K-AJ): 5位定额编号作表头、数值作数据
- 属性维度行在表头和数据行之间
- 续表标记在段首

```bash
python parse_tables.py "input_grid.json"           # → input_parsed.json
```

### Step 2+3B: extract_ref_final.py（多Sheet纵向表）

适用于 JTS/T 276-3-2019 参考定额。**AI 分析驱动的解析器**，处理：

1. **目录解析**：从 Sheet6-7 提取章节树（第一章→一、爆破挤淤...）
2. **总说明**：Sheet8 提取为 `section_text`
3. **章节边界**：Sheet10(第一章), Sheet24(第二章), Sheet60(第三章)...
4. **属性维度**：
   - 表头行 A=顺序号, B=定额编号 → E+ 列数字为定额编号
   - 后续行 A=顺序号, B=项目 → 区分标签行和数值行
   - 标签行判定：所有 E+ 列同值 且 含中文量词（长/宽/高/深/径/截面/级/类/别/土/岩/型）
   - 数值行：按列对应定额编号
5. **定额单位**：从工程内容行末尾提取（支持 "100m³", "10 根", "1t", "10000m²" 等）
6. **注释**：全宽行以"注"开头
7. **续表链**："续表"开头的 Sheet 继承上一表的编码和属性

```bash
python extract_ref_final.py "input_grid.json"      # → input_parsed.json
```

**输出结构**：
```json
{
  "toc": {"第一章": {"title": "第一章 土石方工程", "sections": [...]}},
  "text_content": [{"type": "general_instruction", "title": "总说明", "content": "..."}],
  "documents": [{
    "tables": [{
      "chapter": "第二章",
      "section_title": "一、水上打大直径钢管桩",
      "subsection": "1. 桩径 φ180cm",
      "work_content": "工程内容：装船，运输，打桩，稳桩夹桩。",
      "unit": "10根",
      "quota_codes": ["13","14","15","16","17","18"],
      "attr_labels": ["桩长（m）", "土壤级别"],
      "attr_values": [{"E":"40","F":"40",...}, {"E":"一","F":"二",...}],
      "notes": ["注：本定额以运距 1km 内为准..."],
      "items": [{"quota_code":"13","cost_item":"人工","amount":32.01,...}]
    }]
  }]
}
```

### Step 4: load_to_sqlite.py

写入 Norms-AI 数据库，与 PDF 导入共用 Schema。

```bash
python load_to_sqlite.py "input_parsed.json"                   # 追加模式
python load_to_sqlite.py "input_parsed.json" --db custom.db    # 指定数据库
python load_to_sqlite.py "input_parsed.json" --title "..." --doc-number "..." 
```

自动处理：TOC→chapter 树、text_content→section_text、table→norms_table+norms_item、属性填充到 attr_level1~4。

### Step 5: verify_import.py

```bash
python verify_import.py                      # 使用默认数据库
```

检查项：文档数、章节结构、条目覆盖率、基价覆盖率、属性覆盖率、编码有效性。

## 已验证的数据质量

JTS/T 276-1-2019 主定额（单Sheet）：
- 330 表，39,393 条，1,271 编码

JTS/T 276-3-2019 参考定额（多Sheet）：
- 44 表，1,914 条，86 编码
- 单位提取：39/44 (88%)
- 属性提取：25/44 (57%，其余为无维度简单表)

## 关键技术决策

1. **直接 XML 解析**：绕过 openpyxl 兼容性问题
2. **合并单元格填充**：先写先得，同 `mechanical_grid_all.py` 算法
3. **属性标签识别**：中文量词判断（长/宽/高/深/径/截面/级/类/别/土/岩/型）
4. **定额单位提取**：工程内容末尾的数字+单位组合，支持空格分隔（"10 根"→"10根"），至少1位数字+至少1个字母/中文
5. **目录驱动章节**：TOC→chapter 树，Sheet号→章节映射
6. **复用现有 Schema**：与 PDF 导入共存于同一数据库

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 合并单元格值缺失 | openpyxl 不填充合并区域 | 用 excel_to_grid.py 的 XML 直接填充 |
| 定额编号被属性值覆盖 | B="项目"行数字值被误认为编码 | extract_ref_final.py 区分标签行和值行 |
| 单位 "10 根" 未被识别 | 空格拆分导致匹配失败 | find_unit 组合最后3个 token |
| 单位 "1t" 未被识别 | 原正则要求2位以上数字 | 放宽为1位数字+1个字母/中文 |
| 所有表 page=0 | 未设置行范围 | extract_ref_final.py 分配序号页码 |
| /api/notes 404 | 文件路径不存在 | start.py 改为从 DB header_json 读取 |
| 章节名含省略号 | TOC 原文有 "............." | re.sub 去除省略号和页码 |

## 参数速查

| 脚本 | 必选参数 | 常用可选参数 |
|------|---------|-------------|
| excel_to_grid.py | file | -o |
| grid_to_md.py | grid_json | -o |
| parse_tables.py | grid_json | -o |
| extract_ref_final.py | grid_json | -o |
| load_to_sqlite.py | parsed_json | --db, --title, --doc-number, --source |
| verify_import.py | (none) | --db |

## 参考

- [references/db-schema.md](references/db-schema.md) — 完整数据库 Schema
