---
name: pk-boq-inquiry
description: "询价包与主材表。从BOQ清单提取叶节点材料、按关键词归类合并、输出带BOQ分级样式和行分组的市场询价表。触发词：询价包、主材表、材料询价、询价材料表、inquiry materials、material inquiry。"
---

# pk-boq-inquiry — 询价包与主材表

从设计院 BOQ 清单中提取材料叶节点，按关键词归类合并，输出带 BOQ 四级层级样式的市场询价表。

## 触发词

| 中文 | English |
|------|---------|
| 询价包 / 主材表 / 材料询价 | inquiry materials |
| 询价材料表 / 提炼主材 | material inquiry package |
| BOQ 材料拆分 / 图纸分发 | split inquiry BOQ |

## 工作流

```
BOQ源文件.xlsx → Phase 1: 叶节点提取 → Phase 2: 关键词归类合并 → Phase 3: 分级格式化输出 → 询价表.xlsx
```

### 工作流 A：关键词归类合并（通用）

适用于需要跨章节合并同类材料的场景，通过 `config.json` 定义归类规则。

### 工作流 B：FHDI清单直接提炼（保序）

适用于 FHDI 格式的 BOQ 清单，**保留原始层级结构**作为询价表的分级标题，不做跨章节归类合并。

```
FHDI BOQ → 状态机解析层级 → 叶节点过滤 → BOQ分级样式输出 → 询价表.xlsx
```

**适用条件**：
- BOQ 的 Name 列包含四级标记：`【L1】`、`《L2》`、`{L3}`
- 条目有有效编号（含 `.`）、数量 > 0、单位非 LS
- 不需要跨章节合并同类材料

**排除规则**：自动跳过含 `施工单位`、`材料关税`、`TOTAL` 的 L1 章节。

## extract_inquiry_from_fhdi.py 用法

```bash
python scripts/extract_inquiry_from_fhdi.py <FHDI清单.xlsx> [-o output.xlsx]
```

示例：
```bash
python scripts/extract_inquiry_from_fhdi.py \
  "(OUT2026-06-01)FHDI清单.xlsx" \
  -o "./FHDI_材料询价表.xlsx"
```

输出与 `build_inquiry_materials.py` 相同的 16 列 BOQ 格式，分级标题与源清单一致。

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/build_inquiry_materials.py` | 主材表提炼：三阶段流水线（提取→归类→格式化） |
| `scripts/split_inquiry_boq.py` | BOQ 清单拆分：按关键字拆分子清单 |
| `scripts/extract_inquiry_from_fhdi.py` | FHDI BOQ 直接提炼：保留原清单层级，按章节输出材料询价表 |

## build_inquiry_materials.py 用法

```bash
python scripts/build_inquiry_materials.py --source <BOQ.xlsx> --config <config.json> [options]

参数:
  --source PATH            BOQ 源文件路径（Phase 1）
  --config PATH            JSON 配置文件（必填）
  --ast PATH               document-ingest semantic_analysis JSON（自动检测列映射）
  --template PATH          参考模板 xlsx
  -o, --output DIR         输出目录（默认当前目录）
  --phase {1,2,3}          单独运行某阶段
  --items PATH             Phase 1 输出 JSON（Phase 2 输入）
  --consolidated PATH      Phase 2 输出 JSON（Phase 3 输入）
  --title TEXT             Excel 标题覆盖
  --no-md                  跳过 Markdown 输出
  --no-xlsx                跳过 xlsx 输出
```

示例：
```bash
python scripts/build_inquiry_materials.py \
  --source "FHDI Schedule of Prices.xlsx" \
  --config "inquiry_config.json" \
  -o "./output"
```

## 配置文件 (config.json)

```json
{
  "project": "项目名称",
  "source": {
    "sheets": ["E-Quay", "F-Berthing"],
    "columns": {"item_no": 0, "description": 1, "unit": 2, "quantity": 3, "spec": 4},
    "item_filter": {"min_depth": 2, "exclude_keywords": ["Lump Sum", "Provisional"]}
  },
  "consolidation": {
    "quantity_factor": 1.05,
    "groups": [
      {"name": "钢管桩", "keywords": ["钢管桩", "steel pipe pile"], "match_all": false}
    ]
  },
  "hierarchy": {
    "l1_groups": [
      {"name": "桩基与钢结构", "l2_keywords": ["钢管桩", "PHC桩", "钢筋"]}
    ]
  }
}
```

## 输出格式

与 `pk-boq-price-build` 相同的 BOQ 分级样式，多一列**数量**：

| 列 | 内容 |
|----|------|
| 编号 | M{序号} 三位数递增编号 |
| 专业 | 材料类别 |
| 名称 | 材料名称（去规格后缀） |
| 项目特征 | 规格参数 `[...]` |
| 单位 | 计量单位 |
| **数量** | 合并后工程量（含损耗系数取整） |
| 除税单价 | 留空，供供应商填写 |
| 税金 | 留空 |
| 含税单价 | 留空 |
| 日期 | 询价日期 |
| 币种 | USD |
| 供应商 | 留空 |
| 联系人 | 留空 |
| 电话 | 留空 |
| 地址 | 留空 |
| 备注 | 附加说明 |

## 分级样式

| 层级 | 标记 | Fill | Font | Outline Level |
|------|------|------|------|---------------|
| L1 | `【大类】` | `#C6D9F1` | 11pt bold | 0 |
| L2 | `《中类》` | `#EEF2FA` | 10pt bold | 1 |
| L3 | `{子类}` | `#FBE5D6` | 10pt bold | 2 |
| L4 | 数据行 | 无填充 | 9pt | 3（有L3时）/ 2（直接L2下） |

- 无合并单元格（xlsxwriter 生成，Office Excel 兼容）
- 行分组支持 Excel +/- 折叠
- 冻结尾行

## 引用规则

| 规则 | 来源 |
|------|------|
| 四级层级 `【】→《》→{}→条目` | [boq_hierarchy_rules.md](../references/boq_hierarchy_rules.md) |
| Outline level: L1=0, L2=1, L3=2, L4=3 | 同上 |
| 样式常量 (fill/font/size) | 同上 |
| Excel 兼容性：xlsxwriter 优先，无合并单元格 | [excel_compatibility.md](../references/excel_compatibility.md) |
| 输出命名：`{YYYY-MM-DD}_材料询价表.{ext}` | [boq_conventions.md](../references/boq_conventions.md) |
| 归类规则编写 | [consolidation_rules.md](../references/consolidation_rules.md) |

## 三阶段详解

详见 [material_inquiry_workflow.md](../references/material_inquiry_workflow.md) 和 [consolidation_rules.md](../references/consolidation_rules.md)。
