---
name: pk-norms-import
description: >
  定额书（BOQ Norms Book）PDF 全量结构化提取入库。
  将任意格式的定额PDF（文本型或图片型）按原书目录结构提取到 SQLite 数据库，
  通过浏览器查询和导航。涵盖完整 pipeline：结构解析 → 内容提取 → 入库 → 验证。
  支持多 Agent 并行加速。触发条件：用户提到"定额提取"、"定额PDF"、"定额入库"、
  "norms import"、"quota extraction"，或需要处理工程造价定额标准文件时。
---

# BOQ Norms Import

定额书 PDF 全流程结构化提取：PDF → 1D 数据 → SQLite → 浏览器。

## 首要决策：判断 PDF 类型

处理任何定额 PDF 前，**必须先判断类型**：

```python
import fitz
doc = fitz.open("目标.pdf")
page = doc[10]  # 取一页正文
blocks = page.get_text("dict")["blocks"]
img_blocks = sum(1 for b in blocks if b["type"] == 1)
text_blocks = sum(1 for b in blocks if b["type"] == 0)

if img_blocks == 0 and text_blocks > 0:
    pdf_type = "text"     # → Path A
elif img_blocks > 0 and text_blocks == 0:
    pdf_type = "image"    # → Path B
else:
    pdf_type = "mixed"    # → 按页分派
```

## 总体架构：三层四阶段

```
                    ┌── Layer 1: 结构层 (通用) ──┐
                    │  build_structure.py         │
                    │  目录解析·页面分类·章节映射    │
                    │  → structure.json           │
                    └──────────┬──────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
   Path A: 文本型 PDF     Path B: 图片型 PDF    Path M: 机械网格
   有文本层，PyMuPDF 直提   无文本层，走 OCR       纯算法，无 AI
         │                     │                     │
   ┌─────┴──────┐       ┌─────┴──────┐       ┌──────┴──────┐
   │坐标聚类(确定性)│       │PDF渲染+RapidOCR│       │bbox→2D grid │
   │cluster_cols │       │ ocr_all.py  │       │mechanical_  │
   │AI语义(LLM)  │       │ text_to_md  │       │grid_all.py  │
   │ai_extract   │       │ 坐标+规则    │       │grid→1D→DB   │
   └─────┴──────┘       └─────┴──────┘       │mechanical_  │
         │                     │              │grid_to_db   │
         └─────────────────────┼──────────────┘
                               │
                    ┌──────────┴──────────┐
                    │ Layer 3: 入库层 (通用) │
                    │  load_all_to_sqlite.py│
                    │  mechanical_grid_to_db│
                    │  → quota_data.sqlite  │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │ Layer 4: 验证层 (通用) │
                    │  verify_extraction.py │
                    │  db_clean.py          │
                    │  quota_browser.html   │
                    └──────────────────────┘
```

- **结构层**与 PDF 类型无关——目录解析、页面分类、章节映射对所有路径通用
- **内容提取层**三种路径可选——文本型走 PyMuPDF + AI，图片型走 OCR + 规则，机械网格走纯算法
- **入库层和验证层**统一——三种路径输出相同的 DB schema 和前端

## 四阶段执行流程

### Phase 1: 结构先行（纯算法，< 30 秒）

**目标**：建立全书完整地图，确保不遗漏任何一页。

```bash
python scripts/build_structure.py <pdf_path> --output output/structure.json
```

做的事：
1. **目录解析**：从目录页提取 章→节→分项 层级树 + 内部页码
2. **页码映射**：解析每页 `- N -` 页脚，建立内部页码→PDF页码映射
3. **页面分类**：逐页判定类型（见下方类型表）
4. **章节归属**：每页按其内部页码匹配到所属章/节/分项

产出 `structure.json`，每页都有 page_type、chapter、section、subsection。

页面类型分类规则：

| type | 判定特征 |
|------|---------|
| `cover` | 含"中华人民共和国行业标准"、"JTS"、"主编单位" |
| `blank` | 几乎无文字（< 5 个文本块） |
| `notice` | 含"公告"、"第X号" |
| `toc` | 含密集的"第X章"+"......"+页码模式 |
| `general_instruction` | 含"总说明"或"说明"，无表格结构 |
| `chapter_title` | 含"第X章"，页内文字 < 15 行，无5位定额编号 |
| `section_intro` | 含"第X节"或"说明"，无定额编号 |
| `quota_table` | 检测到 >= 3 个 5 位定额编号 |
| `continued_table` | 页眉/顶部含"续表"或"续前表" |
| `appendix` | 含"附加说明"或"附录" |

详见 [references/pipeline-structure.md](references/pipeline-structure.md)

### Phase 2: 内容提取（按 PDF 类型分派）

#### Path A: 文本型 PDF

```bash
# A1: 全量文本+坐标提取（已完成则跳过）
python scripts/extract_text_all.py --pdf <pdf_path> --output output/text/

# A2: 坐标聚类+列对齐（确定性算法，毫秒级/页）
python scripts/cluster_columns.py --text-dir output/text/ --output output/clustered/

# A3: AI 逐页语义理解（LLM API，~500ms/页，支持并行）
python scripts/ai_extract_page.py --clustered-dir output/clustered/ --output output/extracted/ \
    --structure output/structure.json --model claude-sonnet-4-6
```

详见 [references/pipeline-text.md](references/pipeline-text.md)

#### Path B: 图片型 PDF

```bash
# B1: PDF 渲染 + RapidOCR 多 pass 识别
python scripts/ocr_all.py --pdf <pdf_path> --output output/ocr/

# B2: OCR 文本 → 结构化 MD（含坐标辅助的表格识别）
python scripts/text_to_md.py --ocr-dir output/ocr/ --output output/md/ \
    --structure output/structure.json
```

详见 [references/pipeline-image.md](references/pipeline-image.md)

#### Path M: 机械网格 (Mechanical Grid)

纯确定性算法，从 bbox 坐标直接构建 2D 网格 → 1D 记录 → SQLite。不依赖 AI/LLM，零 API 调用。

**适用**: 已有 bbox 坐标数据（文本型或 OCR 后），需要快速、确定性可复现的提取。

```bash
# M1: bbox 坐标 → 2D grid JSON（行列填充 + 合并单元格展开）
python scripts/mechanical_grid_all.py \
    --text-dir output/intermediate/text/ \
    --pages <页码范围> \
    --output temp/

# M2: 2D grid JSON → SQLite（grid_to_1d + 续表链 + 直写 DB）
python scripts/mechanical_grid_to_db.py \
    --grid-dir temp/ \
    --structure output/structure.json \
    --db output/quota_data.sqlite
```

详见 [references/pipeline-mechanical-grid.md](references/pipeline-mechanical-grid.md)

### Phase 3: 入库

```bash
python scripts/load_all_to_sqlite.py \
    --extracted-dir output/extracted/ \
    --structure output/structure.json \
    --db output/quota_data.sqlite
```

写入顺序：`document → chapter → page_index → section_text / quota_table → quota_item`

详见 [references/db-schema.md](references/db-schema.md)

### Phase 4: 验证

```bash
python scripts/verify_extraction.py --db output/quota_data.sqlite --structure output/structure.json
```

验证项：

| 检查项 | 规则 | 不通过时的动作 |
|--------|------|---------------|
| 不遗漏 | page_index 总数 = PDF 总页数 | 列出缺失页，重新处理 |
| 属性完整性 | 每章 avg_attr >= 基准值 | 标记低质量章节，建议重提取 |
| 编号范围 | quota_code 范围与目录页声明交叉验证 | 列出范围外编号 |
| 章节层级 | chapter 树与 PDF 目录页人工对比 | 修正 TOC 解析 |

通过后启动浏览器：
```bash
python start.py --db output/quota_data.sqlite
```

### Phase 4.5: 数据库清洗

入库和验证通过后，运行清洗脚本确保数据质量：

```bash
# 执行全部清洗（单位规范、缺失回填、视图重建）
python scripts/db_clean.py output/quota_data.sqlite

# 仅校验不写入
python scripts/db_clean.py output/quota_data.sqlite --dry-run

# 仅输出校验报告
python scripts/db_clean.py output/quota_data.sqlite --validate
```

清洗内容：

| 步骤 | 说明 |
|------|------|
| 单位清洗 | 去除 `norms_table.unit` 中的中文描述（`10m³混凝土`→`10m³`），修正 OCR 误识别（`l`→`1`） |
| 缺失回填 | 从 `work_content` 尾部提取单位回填空单位行 |
| 视图重建 | 重建 `v_quota_name` 视图，确保 pk-norms-export 和 pk-norms-match 使用的列名一致 |
| 完整性检查 | 表数量、编号长度分布、章节层级 |

`load_all_to_sqlite.py` 在入库完成后会自动调用清洗步骤。

清洗规则配置在 [config/cleaning_rules.json](config/cleaning_rules.json)，可按数据库调整。

### 手动清洗

如需单独运行清洗（如修改了配置或数据库内容变更）：

```bash
python scripts/db_clean.py <db_path>
```

也可作为模块被 pk-norms-export 引用：
```python
from db_clean import clean_unit, extract_unit_from_work_content, clean_all
```

## 多 Agent 并行策略

Phase 1 完成后，Phase 2 可按章并行：

```
Phase 1 → structure.json
              │
    ┌─────────┼─────────┬─────────┬─────────┬─────────┐
    │         │         │         │         │         │
  Agent 1  Agent 2  Agent 3  Agent 4  Agent 5  Agent 6
  第1章     第2章     第3章     第4章     第5章     第6章
    │         │         │         │         │         │
    └─────────┴─────────┴─────────┴─────────┴─────────┘
                          │
              Phase 3: 合并入库 (单线程)
```

- 每章内串行（处理续表链），章间并行
- 总时间 ≈ 最大单章时间
- 用 `superpowers:dispatching-parallel-agents` 调度

## 核心算法：多维表转一维

定额表的核心挑战：表头有多层属性维度 × 多列定额编号 × 多行费用项目。

```
原始表格（2D）                             输出（1D）
┌────────────────────────────┐
│         地槽        地坑    │         每条记录 =
│      无挡    有挡  无挡  有挡 │         1个定额编号
│      ⅠⅡ    ⅢⅣ  ⅠⅡ    ⅢⅣ │         + 完整属性组合
├────────────────────────────┤         + 1行费用项目值
│10018 10019 10020 10021     │
│ 人工  10.37 21.38 12.96 ... │   →    10018, 地槽, 无挡土板, Ⅰ～Ⅱ, 人工, 10.37
│ 板枋材  —    —    0.71 ... │        10018, 地槽, 无挡土板, Ⅰ～Ⅱ, 板枋材, null
│ 基价  1023 1987 1302 ...   │        10019, 地槽, 无挡土板, Ⅲ～Ⅳ, 人工, 21.38
└────────────────────────────┘        ...
```

n 个定额编号 × m 行费用项目 = n×m 条 1D 记录。

详细算法见 [references/multi-dim-to-1d.md](references/multi-dim-to-1d.md)

## AI 的作用边界

AI **只负责语义理解**——从已对齐的列表头文本序列中推断属性名和属性值。

坐标聚类、列对齐、数据行识别全部由确定性算法完成。AI 的输入不是原始坐标，而是已按列组织好的结构化文本：

```
列1 (10018): [地槽, 无挡土板, 土壤类别, Ⅰ～Ⅱ]
列2 (10019): [地槽, 无挡土板, Ⅲ～Ⅳ]
列3 (10020): [地坑, 有挡土板, Ⅰ～Ⅱ]
列4 (10021): [地坑, 有挡土板, Ⅲ～Ⅳ]
```

从这种输入推断属性语义是 AI 的强项。完整 prompt 模板见 [references/ai-prompt.md](references/ai-prompt.md)

## 数据库 Schema

6 张核心表：

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `document` | 文档元数据 | title, doc_number, total_pages |
| `chapter` | 四级章节层级 | parent_id (自引用), level, title, start_page, end_page |
| `page_index` | **中枢表**，每页索引 | page_type, chapter_id, table_id, internal_page |
| `section_text` | 说明文字/目录/公告 | chapter_id, page, type, content |
| `quota_table` | 定额表元数据 | chapter_id, header_json, unit, row_count |
| `quota_item` | 定额条目 (1D) | quota_code, attr_level1~4, cost_item, unit, code, amount |

详见 [references/db-schema.md](references/db-schema.md)

## 不遗漏检查清单

处理任何定额书时必须覆盖：

- [ ] 封面/版权页 → document 表
- [ ] 公告/修订说明 → section_text 表
- [ ] 目录页 → chapter 表层级树来源
- [ ] 总说明 → section_text 表
- [ ] 每章章标题 → chapter 表条目
- [ ] 每章章说明 → section_text 表
- [ ] 每节节说明 → section_text 表
- [ ] 每个定额表首页 → quota_table + quota_item
- [ ] 每个定额续表 → quota_item（继承前页 table_id）
- [ ] 附录/附加说明 → section_text 表
- [ ] 空白页 → page_index（type=blank）
- [ ] 每页页脚内部页码 `- N -` → page_index.internal_page

## 关键文件

| 文件 | 作用 |
|------|------|
| `scripts/build_structure.py` | Phase 1: 结构解析 |
| `scripts/extract_text_all.py` | Path A1: 文本提取 |
| `scripts/cluster_columns.py` | Path A2: 坐标聚类 |
| `scripts/ai_extract_page.py` | Path A3: AI 语义提取 |
| `scripts/ocr_all.py` | Path B1: OCR 提取 |
| `scripts/text_to_md.py` | Path B2: OCR→MD |
| `scripts/mechanical_grid_all.py` | Path M1: bbox→2D grid JSON |
| `scripts/mechanical_grid_to_db.py` | Path M2: grid JSON→SQLite |
| `scripts/load_all_to_sqlite.py` | Phase 3: 入库（含自动清洗） |
| `scripts/verify_extraction.py` | Phase 4: 提取验证 |
| `scripts/db_clean.py` | Phase 4.5: 数据库清洗（也供 pk-norms-export 引用） |
| `config/cleaning_rules.json` | 清洗规则配置（单位模式、OCR修正、视图SQL） |
| `assets/quota_browser.html` | 前端浏览器模板 |
| `references/pipeline-structure.md` | 结构层详细流程 |
| `references/pipeline-text.md` | Path A 详细流程 |
| `references/pipeline-image.md` | Path B 详细流程 |
| `references/pipeline-mechanical-grid.md` | Path M 详细流程 |
| `references/db-schema.md` | 数据库 Schema 参考 |
| `references/multi-dim-to-1d.md` | 多维转一维算法详解 |
| `references/ai-prompt.md` | AI Prompt 模板 |
