# 主材表提炼 — 完整工作流详解

## 数据流概览

```
FHDI BOQ xlsx                config.json                  参考模板 xlsx
  (8 sheets, ~2000 rows)       (归类规则+层级)              (15列表头+配色)
        │                           │                            │
        ▼                           ▼                            │
  Phase 1: extract                   │                            │
   ┌──────────┐                     │                            │
   │ 叶节点提取 │                     │                            │
   │ 深度≥2   │                     │                            │
   │ 跳过LS    │                     │                            │
   └────┬─────┘                     │                            │
        │ items.json (~700条)        │                            │
        ▼                           ▼                            │
  Phase 2: consolidate                                            │
   ┌──────────────┐                                               │
   │ 关键词匹配    │                                               │
   │ 同类合并      │                                               │
   │ 剔除辅材      │                                               │
   │ 工程量取整    │                                               │
   └──────┬───────┘                                               │
          │ consolidated.json (~110条, 27中类)                     │
          ▼                                                       ▼
  Phase 3: format                                          模板样式引用
   ┌──────────────┐
   │ L1/L2 分级    │
   │ 规格拆分 [ ]  │
   │ 15列映射     │
   │ xlsxwriter   │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ MD (简要版)   │
   │ xlsx (格式版) │
   └──────────────┘
```

## Phase 1: 叶节点提取

### 输入
- 设计院 Schedule of Prices Excel（如 FHDI Schedule of Prices-FHDI-0512_v2.xlsx）
- 配置：`source.sheets`（要处理的 sheet 名）、`source.columns`（列索引映射）

### 处理逻辑

1. **遍历 sheet**：按 `config.source.sheets` 列表顺序处理
2. **识别叶节点**：
   - 编码深度（`.` 计数）≥ `min_depth`（通常为 2）
   - 或编码含 `ADD` 标记（补充条目）
3. **读取字段**：
   - Item No（A 列）、Description（B 列）、Unit（C 列）
   - Quantity：优先 D 列，D 列为空/0 时取 E 列
   - Spec：E 列或 F 列（视设计院格式而定）
4. **跳过条目**：
   - Quantity ≤ 0
   - 描述含 `exclude_keywords` 中任一关键词
   - 叶子节点但非实体材料（如 testing、commissioning）

### 输出
`items.json` — 叶节点数组：
```json
[
  {
    "item_no": "E.2.1", "desc": "Crane rail A120",
    "spec": "DIN536 A120 1050N/mm2", "unit": "t",
    "qty": 385.0, "sheet": "E-Quay"
  }
]
```

### 验证
- 总条目数应与源文件叶子节点数一致（允许 ±5% 因过滤差异）
- 打印 per-sheet 统计：`E-Quay: 85 items, F-Berthing: 42 items, ...`

## Phase 2: 合并归类

### 输入
- Phase 1 输出的 items.json
- `config.consolidation.groups` 归类规则

### 处理逻辑

1. **关键词匹配**：
   - 对每条 item，构造 `desc + ' ' + spec` 搜索文本
   - 遍历 groups 规则，找到第一个匹配的 group
   - `match_all: true` → 所有 keyword 必须出现；`match_all: false` → 任一出现

2. **同类合并**：
   - 同一 group 下的 items，按 `desc` 去重合并
   - 合并策略：保留首条描述，累加工程量
   - 如果 desc 不同但同类 → 输出警告供人工检查

3. **工程量处理**：
   - 应用 `quantity_factor`（默认 1.05，施工损耗）
   - 取整：> 100 取 50 的倍数，> 1000 取 100 的倍数
   详情参考代码实现

4. **辅材剔除**：
   - 同类条目数 < 2 且总量 < `min_quantity` 阈值 → 剔除
   - 单条 lot/sum 单位 → 剔除

### 输出
`consolidated.json` — 归类后的材料数组：
```json
[
  {
    "category": "钢管桩 Steel Pipe Piles",
    "items": [
      {"id": "M001", "desc": "钢管桩 Φ1000mm δ16mm API 5L X60", "unit": "t", "qty": 3350, "remark": ""}
    ]
  }
]
```

### 验证
- 打印每组条目数：`钢管桩: 3 items, PHC桩: 2 items, ...`
- 标注未匹配条目，建议完善规则或人工处理

## Phase 3: 模板格式化

### 输入
- Phase 2 输出的 consolidated.json
- `config.hierarchy.l1_groups` 层级映射
- 参考模板 xlsx（`市场询价表.xlsx` 的 `3.1价格表` sheet）

### 处理逻辑

1. **L1/L2 层级构建**：
   - L2 = consolidation groups 的 `name`
   - L1 = 根据 `l1_groups[].l2_keywords` 匹配 L2
   - 未匹配 L2 → 归入「其他 Miscellaneous」

2. **规格拆分**：
   - 正则提取 `desc` 中的 `[...]` 内容 →「项目特征」列（D 列）
   - 去除 `[...]` 后的 desc →「名称」列（C 列）

3. **15 列映射**：

| 输出列 | 来源 | 说明 |
|--------|------|------|
| A 编号 | `M{序号}` | 三位数递增编号 |
| B 专业 | `item.category` | 材料类别名 |
| C 名称 | `desc` 去 `[...]` | 材料名称 |
| D 项目特征 | `[...]` 内容 | 技术规格参数 |
| E 单位 | `item.unit` | 计量单位 |
| F 除税单价 | 留空 | 供供应商填写 |
| G 税金 | 留空 | 供计算 |
| H 含税单价 | 留空 | 供供应商填写 |
| I 日期 | 留空 | 供填写 |
| J 币种 | `USD` 或配置 | 默认 USD |
| K 供应商 | 留空 | 供询价后填写 |
| L 联系人 | 留空 | 供填写 |
| M 电话 | 留空 | 供填写 |
| N 地址 | 留空 | 供填写 |
| O 备注 | `item.remark` | 附加说明 |

4. **样式应用**（xlsxwriter）：
   - 标题行：`#FFF2CC` 黄底，10pt 粗体，合并 A-O
   - 表头行：`#FFF2CC` 黄底，8pt 粗体
   - L1 `【大类】`：`#333F50` 深蓝底，`#FFFFFF` 白字，8pt 粗体
   - L2 `《中类》`：`#DAE3F3` 浅蓝底，8pt 粗体
   - 数据行：白底，8pt，全边框 `#808080`
   - 数字列（F/G/H）：`#,##0.00` 会计格式
   - 列宽：A=7, B=14, C=28, D=24, E=6, F-I=9/6/9/8, J=5, K-M=10/6/10, N=10, O=18

### 输出
- `{date}_材料询价表.md` — 简要 Markdown 版
- `{date}_材料询价表.xlsx` — 完整格式化 Excel

### 验证
- 检查所有 M 编号唯一
- 检查 L1/L2 层级覆盖所有条目
- 检查规格拆分正确（带 `[...]` 的条目，D 列非空）
- Excel 在 Office 中打开无兼容性警告

## 边界情况处理

### 同编号重复
同一 Item No 在源文件中出现多次（如不同方案或结构段）：
- 按顺序保留首次出现
- 输出警告提示人工检查

### 材料描述差异
同一材料类别下，不同部位的描述略有差异：
- 保留第一条作为主描述
- 将差异标注在备注列

### 无规格材料
描述中无 `[...]` 规格标签：
- D 列（项目特征）留空
- C 列保留完整描述

### 跨 sheet 同一材料
同一材料出现在多个 sheet 中：
- 归类到相同 group
- 工程量累加
- 备注标注原 sheet 来源

## 新项目适配步骤

1. **收集源文件**：确定设计院 BOQ 路径、sheet 结构
2. **创建 config.json**：
   - 填写 `source.sheets` 和 `source.columns`
   - 设计 `consolidation.groups`（参考 Laldia 项目的 27 组规则）
   - 设计 `hierarchy.l1_groups`
3. **准备参考模板**：确保模板文件路径正确
4. **运行 Phase 1**：检查叶节点提取数量是否合理
5. **运行 Phase 2**：检查归类覆盖度，调整规则
6. **运行 Phase 3**：检查格式输出，微调列宽/配色
7. **验证**：在 Office Excel 中打开确认无警告
