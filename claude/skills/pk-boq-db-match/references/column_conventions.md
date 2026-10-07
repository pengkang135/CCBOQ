# BOQ 列布局约定

本技能约定 BOQ 主表（如 `UniqueBQ`）的列布局：

## 主表列（A-N）—— **AI 绝不改动**

| 列 | 内容 | 说明 |
|---|---|---|
| A | Discipline | 大专业（土建工程 / 装饰工程 / 室外工程 / 钢结构工程 / 安装工程） |
| B | Category | 分类 |
| C | Subcategory | 子分类 |
| D | Description (英文) | BOQ 描述文本，可能含厚度/规格 |
| E | Unit | 单位（m2 / m3 / kg / t / No. / Set / Item / …） |
| F | **BQ Code** | 唯一编号，如 `AUTOMATIC_BASIN_FAUCET_NO`。**跨行漂移时稳定索引** |
| G | Quantity | 工程量数值 |
| H | 平均费率 Rate | 旧 AI 或 pivot 计算值 |
| I | 金额 Amount | 合价 |
| J, K | (空白) | 分隔 |
| L | BQ Code (重复) | 用户人工套价区的关联键 |
| M | 人工搜索名称 | 用户手工填 |
| N | **人工套价** | 用户手工价。**保护规则**：仅当 N 是**正数**时才跳过 AI 写入 |

## AI 套价区（O-W）—— **本技能写入**

| 列 | 内容 | 类型 |
|---|---|---|
| O | 置信度 | high / medium / low / estimated / no_match / construction_only / skip |
| P | 匹配名称 | 从 rate 池匹配到的 name |
| Q | 匹配单位 | 从 rate 池匹配到的 unit |
| R | 不含税单价 | 数值 (THB)，如换算则填换算后 |
| S | 币种 | "THB" |
| T | 项目名称 | rate 来源项目（Galaxy Peak DC 优先） |
| U | 供应商 | rate 供应商 |
| V | 报价日期 | rate 日期 |
| W | 匹配说明 | AI 推理理由，含单位换算逻辑 |

## 章节头 vs Leaf 项识别

- **Leaf**：G > 0（有数量）→ 有物料价可套
- **章节头**：G 为空或 0 → 不套价
- **总计行**：A == "总计" → 显式 `skip`，清空 O-W

## 表头行

- 通常在 Excel row 4（有 4 行透视表标题）
- 数据从 row 5 开始
- 用 openpyxl 时 `ws.cell(row=r, column=n)`；用 fastexcel 时 iloc[r-1, c-1]

## 关键校验

写入前必须：
1. 读取所有 leaf 行的 A / F / G / N
2. 若 A == '总计' 或 F 为空 → 跳过
3. 若 N > 0 (正数) → 跳过，保护用户手工价
4. 若 N=0 / None / "" / 公式串 → 视为未填，允许 AI 写 O-W
