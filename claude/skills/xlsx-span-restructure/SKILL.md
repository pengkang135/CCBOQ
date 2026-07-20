---
name: xlsx-span-restructure
description: 按行内容 span 重叠规则重排 xlsx——同组行合并、组内去空列，把 PDF-转-Excel、OCR 转换、复杂排版粘贴等产生的"列位漂移/稀疏乱插"表格压紧成规整结构。领域无关（无关键词字典），保留单元格样式、行高列宽、合并单元格。当用户抱怨"Excel 列很乱、每行占的列不同、从 PDF 转出来的 Excel 结构混乱、想清理成整齐的列数"时使用。触发词：Excel 结构整理、列位压紧、去空列、清理 PDF 转 Excel、重排 xlsx、span 分组、restructure xlsx, clean messy excel, PDF-to-xlsx cleanup, compact columns。
---

# xlsx-span-restructure

## 什么时候用

**症状匹配**（源 xlsx 出现以下之一即适用）：

- 每行有内容的列位不一样——同一逻辑列的数据被 PDF 转换塞进了不同物理列（比如第 1 行在 B、D、K、N、Q 五列，第 2 行在 B、D、K、N 四列，第 3 行只在 D、K 两列）
- 表格页眉/页脚/续表头以宽 span 出现，把叙述段落也拉进了假表格里
- 存在跨页续表——同一张表在源文档里被印了多次表头
- 存在夹在数据之间的小节标题（单细胞 col A）需要作为分组分隔符
- 存在合并单元格但列位漂移，直接读入 pandas 得到全是 NaN 的稀疏矩阵

**不适用的场景**：

- 表格已经规整（每行都填相同列）→ 直接用 pandas / `xlsx` 技能
- 需要提取业务实体、按 schema 语义识别表头 → 用 `document-ingest`、`pk-boq-organize` 等下游语义技能。**本技能只做结构整理**，不识别业务含义。
- 有明确关键词/schema 字典可用于分表 → 本方法的替代品

**在 pipeline 中的定位**：
```
原始杂乱 xlsx  ->  [本技能]  ->  规整后的 xlsx  ->  下游语义处理（md / JSON / SQLite）
```

## 核心原理

**Span 重叠 + 单细胞离群断组**——不依赖任何关键词字典：

1. 每行计算 `(first_col, last_col)` 与非空列集合
2. **空行** → 关闭当前组
3. **单细胞离群断组**：若行仅有 1 个非空细胞、且该列**不在**当前组"多细胞行使用过的列集合"(`multi_cols`) 中 → 关闭当前组，独立成新组
4. 否则用 span overlap 判断：相邻行 span 有交集 → 归入同组，扩并集；完全脱开 → 断组
5. 多细胞行的非空列会累积到当前组的 `multi_cols`（用于步骤 3 的判据）
6. 每组内部去除空列（该列在组内所有行都空），按新列顺序紧凑输出
7. 所有组顺次堆叠到输出 sheet

**为什么需要"单细胞离群断组"**：某些规范里章节标题不在最左列（比如 GB 50500 的 `A.2 基础土石方` 在 col F 里），如果只用 span overlap，标题的 span (6,6) 落在数据表 span (1,14) 内部不会断组，导致数据表与章节标题被卷进一个大组，`used_cols` 并集把中间空列全带上。此规则专治此症。

**多细胞行的 col 在 `multi_cols` 里的单细胞行不会被断**——比如 NRM 2 数据表 `multi_cols = {A, B, C, D}`，续行 `B='2 Adjacent to the site.'`（单细胞 col B）仍被视为数据续行，不误断。

## 使用方式

**直接跑脚本**：

```bash
python scripts/stack_by_span.py <input.xlsx> [output.xlsx]
```

如未指定 output，默认输出到 `<input_basename>_stacked.xlsx`（同目录）。

**Python 调用**（脚本可作模块 import）：

```python
from stack_by_span import restructure
stats = restructure("messy.xlsx", "cleaned.xlsx")
# stats: {input, output, source_rows, source_cols, output_rows, groups, merges_preserved}
```

## 保留什么

跑完输出的 xlsx 保留：

- 每个单元格的字体、填充、边框、对齐（含 wrap_text 换行）、数字格式
- 每行的行高、每列的列宽（同一输出列取多源列的最大宽度）
- 合并单元格——**仅**在整个 merged range 完全落在同一组的行范围+使用列内时才迁移
- Sheet 名（沿用源 sheet 的第一个 sheet 名）

## 什么会丢失

- 空列会消失（本就是目的）
- 跨组边界的合并单元格会被丢弃（比如从表头到下一节 title 的合并——这本就不该合并）
- 多 sheet 源只处理 active sheet（第一个）——如需多 sheet，多次调用即可

## 输出统计

跑完打印：

```
source: 2260 rows x 18 cols
output: 2060 rows in 302 groups
merges preserved: 158
```

分组数是判断产出质量的重要信号：
- **组数 << 行数**（如 300 组对 2000 行，平均 6 行/组）→ 分组合理，产出干净
- **组数 ≈ 行数**（几乎每行一组）→ span 判据太严，数据可能每行都在漂移，检查源
- **组数很少**（如 2000 行只分 3 组）→ 大部分行 span 都覆盖整个表，可能源本身就规整、不需要本技能

## 常见后续处理

跑完本技能后，通常接下游语义处理：

- **转 md / JSON**：把整理后的 xlsx 交给 `document-ingest` 技能
- **识别表头**：用 `xlsx` 技能读入 pandas 分析
- **入 SQLite / 结构化**：按 schema 关键词做二次分表（这时**可以**用关键词字典了，因为列位已经规整）

## 局限性

- 只处理单 sheet（active sheet）——如需批处理多 sheet 文件，脚本外套循环
- 不识别业务表头语义——组间列位可能有偏移（不同组的组内 A 列意义可能不同）
- 依赖 openpyxl，处理 5000+ 行的大文件可能需要几秒到几十秒

## 参考实现细节

深入理解算法边界条件、调试异常输入时，见 `references/algorithm-notes.md`。
