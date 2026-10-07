---
name: pk-boq-hierarchy
description: "BOQ清单NRM五级层级化：L1【】、L2《》、L3{}、Note加粗无括号、L4清单项。核心规则：有单位+数量→强制L4；L3必须有子项否则降Note。与pk-boq-classify不同：classify打业务分类标签，hierarchy打层级结构符号。"
license: Proprietary. LICENSE.txt has complete terms
---

# PK BOQ — 层级化（NRM 五级）

> **禁止用 Excel COM 处理表格**（BOQ 技能族硬规则）：不准启动 Excel 来读写、标记、插行、刷新或校验表格，`win32com` 和 COM 版 `excel` MCP 都不行 —— 它会抢占用户正开着的 Excel 实例、逼用户关文件等脚本、还比纯脚本慢。读值用 `fastexcel`，公式文本和保留格式改单元格用 `openpyxl`，插列/插行/搬 sheet/透视表这类结构操作走 zip+XML 层。这是**全局硬规则**（见 `~/.claude/CLAUDE.md` 的「Excel/AI 加速工具集」硬前置），不限 BOQ；BOQ 场景的具体替代做法见 [pk-boq/SKILL.md](../pk-boq/SKILL.md)。


按 NRM 规则给 BOQ 清单分级。与 `pk-boq-classify` 的区别：hierarchy 打层级符号（【】《》{}），classify 打业务分类标签。

## NRM 五级体系

| 层级 | 标记 | 判定 | 样式 |
|------|------|------|------|
| L1 | `【】` | Schedule 边界标记 | 蓝底 `FFC6D9F1` 11pt 粗体 |
| L2 | `《》` | 章节标签 `X.X - Description` 或 B 列 `X.0` 编码 | 浅蓝底 `FFEEF2FA` 10pt 粗体 |
| L3 | `{}` | 有 L4 子项的中间标题 | 浅橙底 `FFFBE5D6` 10pt 粗体 |
| Note | 无括号 | 无单位+无数量+无子项的文本 | **底色不动**（保留原色）9pt 粗体 |
| L4 | 无括号 | **有单位 + 有数量 → 强制 L4** | **底色不动**（保留原色）9pt 常规 |

**禁止清除 Note/L4 的原底色。** 只有 L1/L2/L3 标题行刷层级色，Note 和 L4 行的 `fill` 一律不赋值——原清单标黄的待确认项、标红的异常项是人工信息，必须活到最后。代码里体现为 `cell.fill = FILLS[lv]` 外层的 `if lv in (L1, L2, L3)` 守卫，**不要去掉这个守卫**；`FILLS` 里 `NOTE`/`L4` 那两个空 `PatternFill()` 是历史遗留的死条目，一旦守卫失效就会把底色刷成空白。

> 注意：字体是无条件统一的（`cell.font = FONTS[lv]` 无守卫），所以**用字体颜色做的人工标注会被抹掉**，只有背景色标注能保住。

---

## 工作流（v3）

> 完整拓扑、规则边界约束、三问判定框架（L2 vs L3）→ [references/topology_v3.md](references/topology_v3.md)

```
merge_boq.py 输出
       ↓
Step 1: --extract-skeleton  → skeleton.json（~200行，去L4数据）
       ↓
Step 2: 单Agent读骨架 → rules.json + assignments.json
       ↓
Step 3: --rules + --assignments 批量应用 → 层级化 xlsx + unmatched.json
       ↓
Step 4: 单Agent审查 unmatched.json → 修正 → 最终输出
```

---

## 脚本

`scripts/apply_hierarchy.py`

```bash
# Step 1: 骨架提取
python scripts/apply_hierarchy.py <input.xlsx> --extract-skeleton

# Step 3: 规则+赋值应用
python scripts/apply_hierarchy.py <input.xlsx> \
    --rules rules.json \
    [--assignments assignments.json] \
    [--unmatched-file unmatched.json]
```

通用参数：`--desc-col C` `--code-col B` `--qty-col E` `--unit-col D` `--output out.xlsx`

处理顺序：规则先匹配 → 赋值覆写（优先级更高）→ 剩余未命中行标记为 Note/L4。

**输出命名规则**：默认直接覆盖输入文件（就地修改，不加 `_层级化` 后缀）。如需保留原文件，用 `--output` 指定输出路径。

**隐藏行处理**：运行层级化之前，先检测输入文件中是否有隐藏行。如有隐藏行，必须询问用户是否删除，得到确认后传 `--delete-hidden-rows` 执行。禁止在用户未确认的情况下自动删除隐藏行。

**验证**：脚本保存后自动执行 4 项验证：
1. 行数校验 — 输入/输出行数是否一致
2. L4 条目数 — 有单位+数量的清单项数量是否一致
3. 随机抽检 5 行 — 描述内容是否完整保留
4. 空描述检查 — L4 行是否误清空了描述

---

## rules.json 格式

只有结构性/格式规则，**禁止语义名词匹配**。需语义判断的行走 `assignments.json`。

```json
{
  "rules": [
    {"id": "R01", "pattern_type": "desc_regex",   "pattern_spec": "^\\d+\\.\\d+\\s*[-–]\\s*.+", "level": "L2", "confidence": "high"},
    {"id": "R02", "pattern_type": "code_regex",    "pattern_spec": "^\\d+\\.\\d+$",              "level": "L2", "confidence": "high"},
    {"id": "R03", "pattern_type": "has_unit_qty",  "pattern_spec": "",                           "level": "L4", "confidence": "high"},
    {"id": "R04", "pattern_type": "desc_contains", "pattern_spec": "preamble notes",             "level": "Note", "confidence": "high"}
  ]
}
```

支持的 pattern_type：`desc_exact` `desc_regex` `desc_contains` `desc_starts` `desc_empty` `code_regex` `all_caps_no_number` `has_unit_qty` `pagination`

## assignments.json 格式

Step 2 Agent 对需语义判断的行直接输出行级定级，覆盖规则匹配结果。

```json
{
  "assignments": [
    {"xl_row": 245, "level": "L2", "reason": "PUMP HOUSE: Q1独立建筑, Q2多专业, Q3可独立排程"},
    {"xl_row": 312, "level": "L3", "reason": "EXTERNAL ROADS: Q1否(区域分类), 封顶L3"}
  ]
}
```

字段：`xl_row` (1-based Excel行号) `level` (L1/L2/L3/Note/L4) `reason` (判定依据)

## 参考

- 样式常量、行高边框：`references/boq_hierarchy_rules.md`
- v3 拓扑详解 + 三问框架：`references/topology_v3.md`
