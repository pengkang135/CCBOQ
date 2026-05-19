# 归类规则编写指南

## 规则结构

每条归类规则对应一个材料中类（L2），定义如何从 BOQ 叶节点中识别该材料：

```json
{
  "name": "钢管桩 Steel Pipe Piles",
  "keywords": ["钢管桩", "steel pipe pile"],
  "match_all": true,
  "unit_override": "t",
  "note": ""
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 材料类别名称，建议中英双语，将成为 L2 标题 |
| `keywords` | [string] | 匹配关键词列表，大小写不敏感 |
| `match_all` | bool | `true`=全部关键词必须同时出现，`false`=任一出现即匹配 |
| `unit_override` | string\|null | 强制覆盖单位（如钢管桩统一用 "t"），`null` 保留源单位 |
| `note` | string | 附加说明（会写入 Excel 备注列或作为 MD 注释） |

## 匹配逻辑

### 匹配文本构造

匹配前，BOQ 条目的 Description 和 Specification 被合并为单一搜索文本：

```python
text = ' '.join((item['desc'] + ' ' + item['spec']).lower().split())
```

即：小写化 + 多余空白归一化 → 单行搜索文本。

### 匹配顺序

规则在 `consolidation.groups` 数组中的顺序即为匹配优先级。条目匹配到第一个规则后即停止（先匹配先得）。

**建议排序**：
1. 精确/特殊规则在前（窄范围，高确定性）
2. 宽泛/兜底规则在后（宽范围，低确定性）

### match_all vs match_any

| mode | 行为 | 示例场景 |
|------|------|---------|
| `match_all: true` | keywords 必须全部命中 | `["钢管桩", "API"]` → 只匹配 API 标准的钢管桩 |
| `match_all: false` | keywords 任一命中即可 | `["钢管桩"]` → 匹配所有钢管桩 |

### 未匹配条目

未匹配到任何规则的条目会被丢弃。在 Phase 2 输出中会统计：
- 已匹配条目数
- 未匹配条目数（供检查规则覆盖度）

## 关键词设计原则

### 1. 双语覆盖

中英文关键词并行，确保不因语言差异漏项：

```json
"keywords": ["混凝土", "concrete", "f'c="]
```

### 2. 规格锚点

对需要细分规格的材料，用规格特征作为关键词：

```json
// CX 体系防腐，按厚度分两档
{"name": "防腐涂层 CX 600μm", "keywords": ["钢管桩", "CX", "600"], "match_all": true}
{"name": "防腐涂层 CX 900μm", "keywords": ["钢管桩", "CX", "900"], "match_all": true}
```

### 3. 避让通用词

避免使用过于通用的关键词导致误匹配：

| 差 | 好 |
|----|----|
| `["pipe"]` → 会匹配所有管材 | `["HDPE管", "HDPE pipe"]` → 精确匹配 |
| `["steel"]` → 会匹配钢筋、钢管、钢结构 | `["钢管桩", "steel pipe pile"]` → 精确匹配 |

### 4. 复合词拆解

长术语拆为独立关键词，用 `match_all` 强制全部命中：

```json
// "球墨铸铁给水管 DN1600" → 拆为 3 个特征词
{"name": "球墨铸铁管", "keywords": ["球墨铸铁", "给水管", "DN1600"], "match_all": true}
```

## 常见归类模式

### 模式 A：通用归类（最常用）

同一大类材料不区分规格，全部归入一个中类：

```json
{"name": "钢筋 Reinforcement Steel", "keywords": ["钢筋", "ASTM A615", "reinforcement"], "match_all": false}
```

### 模式 B：规格拆分

材料规格差异大、单价差异大时，拆分为多个中类：

```json
{"name": "防腐涂层 CX 600μm", "keywords": ["钢管桩", "CX", "600"], "match_all": true},
{"name": "防腐涂层 CX 900μm", "keywords": ["钢管桩", "CX", "900"], "match_all": true}
```

### 模式 C：复合结构匹配

材料名中包含多个特征词才能确定唯一性：

```json
{"name": "双相不锈钢管 2205", "keywords": ["双相不锈钢", "2205"], "match_all": true}
```

### 模式 D：排除性匹配

先匹配特殊项，再用通用规则兜底。利用规则顺序：

```json
{"name": "不锈钢栏杆 SST316", "keywords": ["不锈钢", "栏杆", "SST316"], "match_all": true},
{"name": "钢结构", "keywords": ["钢结构", "steel structure", "钢平台", "钢梯"], "match_all": false}
```

## L1 层级映射

L1 大类在 `hierarchy.l1_groups` 中定义，通过 `l2_keywords` 将 L2 归属到 L1：

```json
{
  "hierarchy": {
    "l1_groups": [
      {
        "name": "桩基与钢结构 Piling & Structural Steel",
        "l2_keywords": ["钢管桩", "PHC桩", "钢筋", "钢材附件", "钢结构"]
      },
      {
        "name": "混凝土 Concrete",
        "l2_keywords": ["商品混凝土", "预制混凝土", "混凝土构件", "混凝土检查井"]
      }
    ]
  }
}
```

- `l2_keywords` 与 L2 `name` 做子串匹配
- 一个 L2 只归属到一个 L1（先匹配先得）
- 未归属的 L2 自动归入「其他 Miscellaneous」

## 辅材剔除规则

以下类型的条目在 Phase 2 中自动标记为辅材并剔除：

| 条件 | 理由 |
|------|------|
| 描述含 `Lump Sum` / `LS` / `Provisional` | 总价项，非材料量 |
| 单位为 `lot` / `sum` / `ps` 且数量 ≤ 1 | 整项计，无可比工程量 |
| 数量 < 参考阈值且同类 < 2 项 | 零星辅材，不值得单独询价 |
| 服务/人工类（含 `labour` / `install` / `testing` 等） | 非材料 |

阈值在 `config.source.item_filter` 中配置：

```json
"item_filter": {
  "min_depth": 2,
  "min_quantity": 10,
  "exclude_keywords": ["Lump Sum", "Provisional", "daywork", "testing"]
}
```
