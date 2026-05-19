# BOQ 层级、样式、分组规则

提取/合并 BOQ 清单时统一遵守本规则。所有脚本（merge_boq, extract_boq_by_keyword, split_inquiry_boq 等）的层级识别和样式输出应保持一致。

## 四级层级体系

| 层级 | 标记 | 编码特征 | 样式 | Fill | Font | Outline Level |
|------|------|---------|------|------|------|---------------|
| L1 | `【】` | `【...】` 在 A 或 B 列 | sec | `FFC6D9F1` | 11pt bold `FF1A1A1A` | 0 |
| L2 | `《》` | `《...》` 在 B 列, dots≤1 | cls | `FFEEF2FA` | 10pt bold `FF1A1A1A` | 1 |
| L3 | `{}` | `{...}` 在 B 列，或有子项的父级条目 | sub3 | `FFFBE5D6` | 10pt bold `FF1A1A1A` | 2 |
| L4 | 无标记 | 普通叶节点条目，无子项 | item | 无填充 | 9pt normal `FF1A1A1A` | 3 |

## L3 自动提升规则

当 L4 条目满足以下所有条件时，自动提升为 L3：
1. `rtype == 'item'`（非 section/class_header/subsection）
2. 存在至少一个后代条目（编码以 `父编码.` 开头且 dots 更多）
3. B 列无 `《》` 标记
4. B 列无 `{}` 标记

提升后行为：
- B 列描述自动包裹 `{}`
- 样式切换为 sub3（`FFFBE5D6` + 10pt bold）
- outline level 设为 2（子项为 3，可折叠）

## 样式常量定义

```python
# L1 section
sec_font  = Font(name='Microsoft YaHei UI', size=11, bold=True, color='FF1A1A1A')
sec_fill  = PatternFill(start_color='FFC6D9F1', end_color='FFC6D9F1', fill_type='solid')
sec_align = Alignment(vertical='center')

# L2 class/subsection
cls_font  = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FF1A1A1A')
cls_fill  = PatternFill(start_color='FFEEF2FA', end_color='FFEEF2FA', fill_type='solid')
cls_align = Alignment(vertical='center')

# L3 curly-brace subsection / promoted parent
sub3_font  = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FF1A1A1A')
sub3_fill  = PatternFill(start_color='FFFBE5D6', end_color='FFFBE5D6', fill_type='solid')
sub3_align = Alignment(vertical='center')

# L4 leaf item
item_font  = Font(name='Microsoft YaHei UI', size=9, bold=False, color='FF1A1A1A')
item_align = Alignment(vertical='center')
```

## 行高

| 层级 | 行高 |
|------|------|
| L1 | 16.5 |
| L2/L3/L4 | 14.5 |

## 边框

- 内部边框：`Side(style='thin', color='FFBFBFBF')`
- L4 叶节点：底部边框 + 左/右两侧（A 列左侧，M 列右侧）
- 表格外框：所有行 A 列左侧 + M 列右侧 + 第 1 行顶部 + 最后一行底部

## 检测函数

```python
is_section_delimiter(a_val, b_val)  # 【 in A or B
is_angle_header(val)                # starts with 《
is_curly_header(val)                # starts with {
is_valid_item(val)                  # matches ^[A-Z]\.\d+
is_class_header(val)                # matches ^Class\s+[A-Z]
```

## 编码 dots 计数

用于推断层级深度。`count_dots(code.replace('ADD', ''))`：
- 0 dots → L1/L2 级别
- 1 dot → L2/L3 级别
- 2+ dots → L3/L4 级别

## 检测优先级（outline level 判定）

```
ADD 条目              → ol=3
《》标记 + dots≤1     → ol=1 (L2)
{} 标记              → ol=2 (L3)
has_children         → ol=2 (L3 自动提升)
dots ≤ 1             → ol=2
dots > 1             → ol=3 (L4 叶节点)
```
