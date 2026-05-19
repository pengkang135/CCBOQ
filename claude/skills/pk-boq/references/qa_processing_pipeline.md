# Q&A 答疑处理全流程

从原始业主澄清回复文件到最终分类汇总输出的完整处理管线。

## 流程图

```
原始 Excel (English, 4 列)                    PDF 业主回复表
    │                                              │
    ├── Query SET 1 (290 items)                    │
    └── Query SET 2 (102 items)                    │
           │                                       │
           └────────────┬──────────────────────────┘
                        │ PDF → Markdown (Pandoc/MarkItDown)
                        ▼
              双语 Markdown (EN + CN, 6 列)
                        │
                        ├── Flash 初译 → Pro 审校（双模型翻译）
                        ▼
              qa_classify.py（分类 + 成本标签）
                        │
                        ├── 关键字打分 → 5 大分类
                        ├── 高频/中频词匹配 → 成本影响（高/中/低）
                        ├── 人工覆盖修正
                        └── 待回复自动升级
                        │
                        ▼
              Bilingual .md + .xlsx（Overview + Detailed）
                        │
                        ├── 1st round: 290 items (Dual-party mode)
                        └── 1st+2nd round: 390 items (Single-party mode)
           │
           ▼
  重要性重评估（雇主回答内容分析）
           │
           ├── 范围确认/否认
           ├── 技术标准引用
           ├── 价格影响判断
           └── 实质性回答评分
           │
           ▼
  交叉引用提取（5 种引用类型）
           │
           ├── Query-to-query（参见 #N）
           ├── PER 引用（PER#XXX）
           ├── 文档引用（Document/Volume）
           ├── 图纸引用（Drawing/APM）
           └── 条款引用（Sub-Clause/Clause）
           │
           ▼
  雇主回复影响总结（Summary sheet）
           │
           └── 范围/价格影响条目筛选 → 新建 Sheet
```

## 1. 输入源文件

### 1.1 原始 Excel（业主端）

| 文件 | 条目数 | 格式 |
|------|--------|------|
| `Query SET 1_ANSWERED.xlsx` | 290 | 4 列: Item \| Question reference \| Bidders Question \| Employers Answer |
| `Query SET 2.xlsx` | 102 | 同上 |

- 全部英文，无中文翻译
- Question reference 列标注招标文件引用路径（如 `Part II - Volume A - Contract Agreement & Conditions`）
- 注意：SET 1 存在更新版 `updated Q66.xlsx`（Q66 回答被修改）

### 1.2 PDF 业主回复表

业主以 PDF 形式提供正式的 Query Management Form，每页一个表格行。需要先转换为 Markdown 再处理。

转换工具：Pandoc 或 MarkItDown（Librarian MCP 处理器）。

```
输入：PDF
输出：Markdown（4 列表格: Item | Question reference | Bidders Question | Employers Answer）
```

## 2. 翻译阶段

### 2.1 双模型协作翻译

遵循项目多模型配置（见 CLAUDE.md），翻译采用 Flash→Pro 两级流程：

```
EN-only Markdown (4 列)
    │
    ▼
Flash (deepseek-v4-flash) 第一遍
    ├── 翻译 Question (EN→CN)
    └── 翻译 Answer (EN→CN)
    │
    ▼
Pro (DeepSeek-v4-pro) 审校
    ├── 纠正术语错误
    ├── 统一专业词汇（如 "Employer" → "雇主"）
    └── 修正工程术语翻译
    │
    ▼
双语 Markdown (6 列)
Item | Query Ref | Question (EN) | Answer (EN) | Question (CN) | Answer (CN)
```

### 2.2 翻译注意事项

- **合同术语**：需保持前后一致。如 "Sub-Clause" → "第X款"，"Particular Conditions" → "特殊条件"
- **技术术语**：PHC 桩、PVD、STS 岸桥、RTG 等缩写保留不译
- **长文本**：部分 Question/Answer 字段超长（>500字符），需要完整翻译不截断

### 2.3 输出文件

```
{原始文件名}_双语_翻译版.md
```

示例：
- `1. Part I - Volume A - Appendix II - Query Management form_Query SET 1_ANSWERED_双语_翻译版.md`
- `2. Q66-...updated Q66_双语_翻译版.md`（Q66 更新版）

## 3. 分类阶段 (qa_classify.py)

### 3.1 输入格式

6 列 Markdown 表格：

```
| Item | Query Ref | Question (EN) | Answer (EN) | Question (CN) | Answer (CN) |
```

### 3.2 分类方法

基于关键字打分 + 人工覆盖的混合分类：

#### 5 大分类

| 分类 | 英文 | 典型判断依据 |
|------|------|------------|
| 商务/合同条款类 | Commercial & Contractual | contract_score ≥ 3 |
| 技术/设计类 | Technical & Design | tech_score ≥ 3 |
| 范围/界面类 | Scope & Interface | scope_score ≥ 3 |
| 施工组织/现场条件类 | Construction Planning & Site Conditions | const_score ≥ 4 且 > tech_score |
| 投标文件/程序类 | Tender Documents & Procedures | bid_score ≥ 2 |

#### 关键字列表

- `CONTRACT_KW`：管辖法、仲裁、保险、履约保证金、索赔、终止等
- `SCOPE_KW` + `SCOPE_RE`：范围、界面、边界、not in scope、by others 等
- `TECH_KW`：设计、规范、图纸、结构、岩土、桩基、电气、疏浚等
- `CONST_KW`：施工方法、临时设施、营地、通道、进度、许可等
- `BID_KW`：投标、招标、提交、澄清、资格预审、格式、模板等

#### 成本影响标签

- `HIGH_COST_PATS`：地震、PGA、安全系数降低、not in scope、赔偿、保证金、等待答复等
- `MED_COST_PATS`：方法、临时、荷载、参数、不一致、进度等
- 分类特定阈值：商务类 high≥1 即为高，技术类 high≥3 才为高
- 待回复自动升级：低→中，中→高

#### 人工覆盖

`MANUAL_OVERRIDES` 字典通过 Item 编号强制指定分类，用于关键字匹配不准的边界案例。

### 3.3 输出

#### Markdown (.md)

结构：
```
# {Project} — Query Classification Summary / 答疑分类汇总
## 1. Overview / 分类概览
    (5 行统计表: Category | Total | High | Medium | Low)
## 2. Detailed Classification / 详细分类
    (按分类分节，每节内按成本→Item排序)
```

#### Excel (.xlsx)

通过 `md_to_xlsx.py` 从 Markdown 转换生成，单 sheet。

### 3.4 双回复方模式 vs 单方模式

- **双回复方** (`qa_classify.py file1.md file2.md`)：两轮答疑来源对比，标注差异条目
- **单方模式** (`qa_classify.py file1.md`)：单一来源，输出 5 列（去掉 Response 2）

第一轮采用双回复方（两方回答对比），第二轮合并后采用单方模式（只有业主最终回答）。

## 4. 两轮合并

### 4.1 合并策略

```
1st round (290 items) + 2nd round (102 items) = 390 items
```

合并后统一使用单方模式运行 `qa_classify.py`。

### 4.2 合并文件结构

| Sheet | 内容 |
|-------|------|
| Overview | A1:E10 分类统计表 |
| Detailed | A1:F403，390 条答疑，按 5 分类排序 |

Detailed 列：`# | Query (CN) | Cost | Response (CN) | Question (EN) | Response (EN)`

### 4.3 初始分类结果

| 成本等级 | 数量 |
|----------|------|
| 高 (High) | 29 |
| 中 (Medium) | 146 |
| 低 (Low) | 215 |

## 5. 重要性重评估

原始分类基于问题文本和回答文本的关键词匹配，但雇主的实际回答内容可能确认或修改了承包范围、技术标准，从而产生额外的成本影响。重评估根据雇主回答的具体内容调整重要性。

### 5.1 评估维度

| 维度 | 权重 | 判断依据 |
|------|------|---------|
| 范围确认 | +2 ~ +3 | "confirmed", "in scope", "contractor shall", "承包商负责" |
| 范围否认 | +2 | "not in scope", "by others", "excluded" — 范围澄清对报价同样重要 |
| 技术标准引用 | +1 | "shall comply with", "in accordance with", "refer to" |
| 价格影响 | +2 | "cost", "contractor's cost", "承包商承担" |
| 实质性回答 | +1 | 回答长度 > 100 字符且有具体技术/商务内容 |

### 5.2 评分规则

- ≥ 4 分 → 高
- ≥ 2 分 → 中
- < 2 分 → 低

### 5.3 重评估结果

| 成本等级 | 调整前 | 调整后 | 变化 |
|----------|--------|--------|------|
| 高 (High) | 29 | 64 | +35 |
| 中 (Medium) | 146 | 171 | +25 |
| 低 (Low) | 215 | 155 | -60 |

## 6. 交叉引用提取

答疑中存在多种类型的交叉引用，需要提取招标文件原文帮助理解上下文。

### 6.1 引用类型

| 类型 | 正则示例 | 解析方式 |
|------|---------|---------|
| 问题间引用 | `See #71`, `参见#32` | 在当前数据中查找被引用的问题和回答 |
| PER 引用 | `PER#006E`, `BD-CGP-0001-PER-D01-APM-CGR-006C-03` | 在 `PER/*/` 缓存中查找 |
| 图纸引用 | `APM-056-01A-04`, `Drawing APM-056-07C-40` | 在 `Drawings/` 缓存中查找 |
| 条款引用 | `Sub-Clause 14.3`, `Clause 7.2.1` | 在 Volume A 缓存中查找 |
| 文档引用 | `Volume C`, `Appendix II` | 在招标文件目录中定位 |

### 6.2 招标文件缓存

缓存目录结构：
```
1 招标文件/
├── Volume A - Contract Agreement & Conditions/
├── Volume C - Employer's Requirements/
│   ├── PER/000 Scope_MD/ ~ 009 Gate Complex_MD/
│   └── Drawings/
└── Volume D - Information Documents/
```

共约 128 个 Markdown 文件用于交叉引用查询。

### 6.3 提取结果

- 问题间引用：全部解析（直接查找同数据源）
- PER/图纸引用：部分解析（取决于文件名与引用号的匹配度）
- 未解析引用标注 "需手动查找"

### 6.4 输出列

| 列 | 内容 |
|----|------|
| G: Tender Doc Excerpt / 招标文件原文摘要 | 引用的招标文件段落原文 |
| H: Excerpt Translation / 摘要中文翻译 | Flash 翻译的中文版本 |

## 7. 雇主回复影响总结

### 7.1 筛选条件

从 390 条中筛选出**对承包范围和价格有实质影响**的条目：

1. 范围确认/否认类回答
2. 技术标准/规范引用类回答
3. 价格/费用归属类回答
4. 实质性技术澄清（回答长度 > 200 字符）

### 7.2 输出

新 Sheet `雇主回复影响总结`：

- 115 条条目（高 40 条，中 75 条）
- 按成本等级 → 分类 → Item 排序
- 列：`# | Category | Question (CN) | Employer Answer (CN) | Cost Impact | Impact Summary | Scope/Price Implication`

## 8. 最终输出文件

```
20250505_orgnized_Bangladesh Laldia Project — Query Classification (1+2 round).xlsx
    ├── Overview: 分类统计
    └── Detailed: 390 条分类详情 (A-F)

20250505_orgnized_..._revised.xlsx
    ├── Overview: 重评估后统计
    ├── Detailed: 390 条 (A-H，含交叉引用)
    └── 雇主回复影响总结: 115 条范围/价格影响条目
```

## 9. 关键技术决策

### 9.1 openpyxl vs xlsxwriter

此流程处理的是**修改现有 Excel**，必须使用 openpyxl。但 openpyxl 的 `merge_cells + PatternFill` 组合会导致 Office Excel 触发修复模式。

**对策**：
- 读取用 openpyxl (data_only=True)
- 写入避免同时使用 merge_cells 和 PatternFill
- 新建文件尽量用 xlsxwriter

### 9.2 翻译缓存

Flash 翻译结果需保存为中间文件，Pro 审校后覆盖。对于长文本（>2000字符），分段翻译再拼接。

### 9.3 编码处理

Windows 终端 GBK 编码问题：脚本中需要 `sys.stdout.reconfigure(encoding='utf-8')` 确保中文输出不报错。

## 10. 脚本调用示例

```bash
# Step 1: PDF → Markdown (via Librarian MCP)
# 通过 mcp__librarian__ingest_source 或手动 Pandoc 转换

# Step 2: 翻译 (via translation-agent skill)
# 双模型协作，输出双语 markdown

# Step 3: 分类
python qa_classify.py \
  "1. Query SET 1_ANSWERED_双语_翻译版.md" \
  "2. Q66 updated Q66_双语_翻译版.md" \
  -o output_dir \
  --project "Bangladesh Laldia Project" \
  --prefix "20250423_"

# Step 4: 两轮合并后重新分类
python qa_classify.py \
  merged_bilingual.md \
  -o output_dir \
  --project "Bangladesh Laldia Project" \
  --prefix "20250505_"

# Step 5: 重要性重评估 + 交叉引用 + 影响总结
# 自定义脚本（见 _process_qa.py 逻辑）
python _process_qa.py \
  "20250505_orgnized_...xlsx" \
  --tender-dir "1 招标文件/" \
  --output "20250505_orgnized_..._revised.xlsx"
```
