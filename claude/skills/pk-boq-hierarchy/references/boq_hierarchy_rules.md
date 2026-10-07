# BOQ 层级、样式、分组规则（NRM 五级）

提取/合并 BOQ 清单时统一遵守本规则。所有脚本（merge_boq, extract_boq_by_keyword, split_inquiry_boq 等）的层级识别和样式输出应保持一致。

## NRM 五级体系

| 层级 | 标记 | 判定特征 | 样式 | Fill | Font | Outline Level |
|------|------|---------|------|------|------|---------------|
| L1 | `【】` | 已有 `【` 标记，或 L1 编码 | sec | `FFC6D9F1` | 11pt bold `FF1A1A1A` | 0 |
| L2 | `《》` | `X.0` 编码 / `《` 标记 | cls | `FFEEF2FA` | 10pt bold `FF1A1A1A` | 1 |
| L3 | `{}` | 有 L4 子项的中间标题 | sub3 | `FFFBE5D6` | 10pt bold `FF1A1A1A` | 2 |
| Note | 无括号 | 分页标记/无子项文本 | item | 无填充 | 9pt bold underline `FF1A1A1A` | 3 |
| L4 | 无括号 | 有单位+有数量 清单项 | item | 无填充 | 9pt normal `FF1A1A1A` | 3 |

## 核心判定规则（优先级从高到低）

### 规则 1：有单位 + 有数量 → 强制 L4

```python
has_unit = unit_col is not None and str(unit_col).strip() not in ('', 'None', 'nan')
has_qty  = qty_col is not None and str(qty_col).strip() not in ('', 'None', 'nan')
if has_unit and has_qty:
    level = 4  # 强制 L4，不参与标题分级
```

### 规则 2：分页/小计标记 → 强制 Note

含以下模式的文本行（不区分大小写），直接定为 Note，不参与标题分级：

```python
if re.search(r'\(cont[\'']d\)|sub\s*total|carried\s+forward|brought\s+forward',
             desc, re.IGNORECASE):
    level = 5  # Note
```

匹配项：
- `(Cont'd)` / `(CONT'D)` — 跨页续行标记
- `Subtotal` / `Sub Total` — 分页小计行
- `Carried Forward` / `Brought Forward` — 承前/接后标记

### 规则 3：已有括号标记 → 权威保留

C 列描述文本中已有括号时，保留原标记，不重复包裹，直接按标记定级：
- 含 `【` → L1
- 以 `《` 开头 → L2
- 以 `{` 开头 → L3

### 规则 4：B 列编码 → L2

```python
if re.match(r'^\d+\.0$', code_str):  # e.g., "1.0", "18.0"
    level = 2
```

### 规则 5：Has-Children 检查 → L3 vs Note 分界

对无单位、无数量、无括号的候选行，向下查找至下一个边界行（L1/L2/已有括号行）：

```python
def has_l4_children(row_num, boundary_rows):
    for r in range(row_num + 1, max_row + 1):
        if r in boundary_rows:
            return False  # 遇到边界，无子项
        if level_map[r] == L4:
            return True   # 找到 L4 子项
    return False

if has_l4_children(row_num):
    level = 3   # L3，加 {}
else:
    level = 5   # Note，加粗无括号
```

### 规则 6：NRM 模板文本黑名单 → 强制 Note

以下 NRM 固定模板文本，无论是否有子项，强制 Note：

```python
# 6a. 模板引导语
if re.search(r'preamble\s+notes|following\s+apply',
             desc, re.IGNORECASE):
    level = 5  # Note
```

匹配项：
- `In addition to the preamble notes, the following apply specifically to this Contract:`
- `The following apply to the Works:` 等变体

### 规则 7：条款引用模式 → 强制 Note

```python
# 6b. Clause references without unit/qty
if re.match(r'^\d+\.\d+\s+\w', desc):
    level = 5  # Note
```

匹配项：
- `2.01 Employer's Requirements` — 引用合同条款
- `1.05 Design Responsibility` — 设计责任条款引用

注意：此规则在 `has_unit_qty()` 之后执行，L4 清单项（如 `4.0 mm Thick...`）因有单位+数量已被规则 1 拦截，不会误判。

### 规则 8：NRM 特征识别（辅助判定，已合并到规则 6/7）

开办费/Preliminaries（附表1）下的条款描述行，已被规则 6/7 覆盖。

## L3 与 Note 的核心区别

| | L3 | Note |
|---|---|---|
| 有 L4 子项 | Y | N |
| 括号 | `{}` | 无 |
| 字体 | 10pt bold | 9pt bold underline |
| 底色 | 浅橙 `FFFBE5D6` | 无填充 |
| 边框 | 无 | 细边框 (同 L4) |
| outline level | 2 | 3 (同 L4) |
| 用途 | 分组标题 | 分页标记/补充描述 |

## 样式常量定义

```python
# L1 section
sec_font  = Font(name='Microsoft YaHei UI', size=11, bold=True, color='FF1A1A1A')
sec_fill  = PatternFill(start_color='FFC6D9F1', end_color='FFC6D9F1', fill_type='solid')

# L2 class/subsection
cls_font  = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FF1A1A1A')
cls_fill  = PatternFill(start_color='FFEEF2FA', end_color='FFEEF2FA', fill_type='solid')

# L3 curly-brace subsection
sub3_font  = Font(name='Microsoft YaHei UI', size=10, bold=True, color='FF1A1A1A')
sub3_fill  = PatternFill(start_color='FFFBE5D6', end_color='FFFBE5D6', fill_type='solid')

# Note — pagination/guidance text (L4 peer, bold+underline, no fill)
note_font  = Font(name='Microsoft YaHei UI', size=9, bold=True, underline='single', color='FF1A1A1A')
note_fill  = PatternFill()  # no background

# L4 leaf item
item_font  = Font(name='Microsoft YaHei UI', size=9, bold=False, color='FF1A1A1A')
```

## 行高

| 层级 | 行高 |
|------|------|
| L1 | 16.5 |
| L2/L3/Note/L4 | 14.5 |

## 边框

- 内部边框：`Side(style='thin', color='FFBFBFBF')`
- L4 叶节点 / Note：四周细边框
- L1/L2/L3：无边框

## 编码 dots 计数（辅助规则）

用于推断层级深度：
- 0 dots → L1/L2 级别
- 1 dot → L2/L3 级别
- 2+ dots → L3/L4 级别

## Phase 1 检测优先级（逐行判定，命中即停止）

```
1. 描述为空              → L4
2. 有单位+有数量          → L4 (强制)
3. 已有括号标记           → L1【】/ L2《》/ L3{} (权威)
4. B 列 X.0 编码         → L2
5. 分页/小计标记          → Note  — (Cont'd)、Subtotal、Carried Forward
6. NRM 模板黑名单         → Note  — preamble notes, following apply
7. 条款引用模式           → Note  — X.XX Description (无单位/数量)
8. 其他                  → 有标题特征(短/无句末句号/无 shall·include·refer 等说明词) → L3 候选 (Phase 2 判定)；
                          否则默认 Note（说明文字）。默认按说明处理，标题需举证，避免说明文字被标题化
```

## Phase 2 Has-Children 判定

```
L3 候选行 → 向下查找至边界行 (L1/L2/已有《或【):
  遇 L3-bracketed {行  → 提升为 L2 (分组 L3 子节)
  遇 L4 行             → 确认 L3 (有直接子项)
  遇边界/结束           → 降级 Note (无子项)
```
