# Algorithm notes for xlsx-span-restructure

## Span 定义与边界情况

**Row span** = `(min_col, max_col)` where col is 1-based index of a cell whose stripped string value is non-empty.

- 全空行 → span = None → 关闭当前组
- 只在 col A 有值 → span = (1, 1)
- 稀疏行（B、D、K 有值）→ span = (2, 11)——**包含中间的空列**

关键：span 描述的是"最左非空到最右非空"的**闭区间**，不是"填充的列集合"。这样 (2,11) 和 (5,7) 认为有重叠（都覆盖 5-7），会归为同组。

## Overlap 判据

```python
def spans_overlap(a, b):
    return not (a[1] < b[0] or b[1] < a[0])
```

两个区间 `[a0,a1]` 和 `[b0,b1]` 只要不完全脱开就算重叠。相邻但不相交（如 `[1,3]` 和 `[4,6]`）→ 不重叠 → 断组。

## 组的 span 是并集

每加入一行，组的 span 扩展为 `(min(current.first, new.first), max(current.last, new.last))`。这样后续行只要跟**累积并集**有交集就归入，不必跟第一行严格对齐。

**副作用**：一旦组的 span 扩到很宽，后续窄 span 的行更容易被吸入。这在实践中是好事——同一张表的所有稀疏行都能进来。

**极端情况**：如果一整块内容首尾行 span 拼起来能覆盖整个 sheet 宽度，就会形成一个巨大的组。此时建议检查源是否有段落文本被误当作 span——考虑预处理时先剔除页眉页脚。

## 断组信号

三种情况断组：

1. **空行** → span=None
2. **新行 span 与当前组累积 span 完全脱开**（不相交）
3. **单细胞离群**：新行只有 1 个非空细胞，其列不在当前组的 `multi_cols` 集合中

**`multi_cols` 定义**：组内所有**多细胞行**的非空列之并集。单细胞行不贡献到 `multi_cols`。

**为什么需要规则 3**：
- Span 判据处理不了"章节标题在中间列"的情况。比如 GB 50500 中 `A.2 基础土石方` 位于 col F，spanning (6,6)。数据表 span (1,14) 包含 (6,6)，span overlap 不会断组。
- 数据表的 `multi_cols` = {A, C, E, J, L, N}（六列固定表头位置）。col F ∉ multi_cols → 触发规则 3 → 正确断组。

**为什么不误断 NRM 2 的续行**：
- NRM 2 数据表 `multi_cols` = {A, B, C, D}（表头四列）。
- 续行如 `B='2 Adjacent to the site.'`（单细胞 col B）：col B ∈ multi_cols → 不断组。

**关键**：`multi_cols` 是"数据表用了哪些列"的结构化画像，单细胞离群判据用它区分"数据行"和"边界标记"，全程无关键词。

**没被列出的情况**（不断组）：
- 新行 span 大于当前组累积 span，但相交 → 继续同组，并集扩展
- 新行 span 完全被当前组累积 span 包含 → 继续同组
- 新行 span 部分重叠、部分超出 → 继续同组，并集扩展
- 单细胞行的列**在** `multi_cols` 内 → 视为数据续行，继续同组

## 组内去空列的语义

组的**使用列**（used_cols）= 组内所有行的非空 col 索引之并集。

去空列 = 只保留 used_cols，按原顺序映射到 1, 2, 3, ...。

这保证：
- 组内行的**相对列位不变**（比如原本在 col B 的都还在同一新列）
- 组间**绝对列位可能变**（组 1 的原 col B → 新 col A；组 2 的原 col C → 新 col A）——这是可以接受的，因为组是独立的表

## 合并单元格迁移规则

仅当 `(merged_range.min_row, min_col, max_row, max_col)` 完全落在同一组的行范围 + used_cols 内时，才迁移到输出。

**丢弃的情况**：
- 合并跨越两个组的边界（分组时被切开）
- 合并的列不在 used_cols 内（应该不会发生，因为合并的列必然有内容）

行号偏移：`new_row = group_first_out_row + (source_row - group_start_source_row)`

## 样式复制

用 `copy(src.font)` 等——每属性单独复制。不用 `src._style` 因为跨 workbook 的 style array 索引不通用。

只在源单元格 `has_style=True` 时才复制，避免为空单元格分配无用样式对象。

## Openpyxl 陷阱

- **不能用 read_only 模式**——read_only 会丢样式对象和合并单元格信息
- **iter_rows 返回稀疏结果**——空单元格在遍历里会出现为 EmptyCell，判空要看 `cell.value`
- **column_dimensions[letter]** 返回默认值即使列没有显式宽度——判 `if w and w > 0` 才安全
- **merged_cells.ranges** 是 iterable of MergedCellRange，`.min_row/max_row/min_col/max_col` 都是 1-based

## 内存

全量加载源到内存（rows 列表）——因为要多次遍历（一次分组、每组一次写出+合并）。5000 行 × 20 列 ≈ 100k 单元格，占用约 30MB，一般 xlsx 处理没问题。10 万行以上的可能需要改成流式，但那种规模的 xlsx 已经很少见。

## 不做的事

- **不做去重**——重复行会被保留（比如跨页续印的表头会出现多次）
- **不做数据类型转换**——单元格 value 原样传递
- **不做行合并**——每源行 = 一输出行
- **不识别语义**——不知道哪行是表头、哪行是数据

需要以上任一功能时，应该在本技能产出的规整 xlsx 上用下游技能处理，而不是塞进本技能。
