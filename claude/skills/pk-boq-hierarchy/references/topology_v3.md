# v3 工作流拓扑

核心思路：**先让一个 Agent 抬头看完整个森林，画出地图；再按地图批量施工；最后抽查边界。**

```
merge_boq.py 输出
       ↓
Step 1: 提取结构骨架（脚本）
  apply_hierarchy.py --extract-skeleton
  筛掉所有 L4 数据行，输出 ~200 行骨架 JSON
       ↓
Step 2: 全局结构分析（单 Agent）
  读骨架 JSON → 识别跨 Sheet 重复模式
  → 输出两份文件：
    ① rules.json（结构性规则，~10 条）— 格式/位置特征，跨项目通用
    ② assignments.json（行级赋值）— 需语义判断的行直接用三问判定法定级
       ↓
Step 3: 规则 + 赋值批量应用（脚本）
  apply_hierarchy.py --rules rules.json --assignments assignments.json
  规则先匹配 → 赋值覆写 → 未命中行标记
       ↓          ↓
   ~95% 命中    ~5% 未命中
  直接分级     unmatched.json
       ↓          ↓
       └──────────┴──→ Step 4: 边界抽查（单 Agent）
                       读未命中行 → 逐条判定
                       → 输出补充修正
                            ↓
                       五级层级化 xlsx
```

## 规则边界（关键约束）

**规则只能描述格式/位置特征，不能包含语义名词匹配。**

| 允许（structural patterns） | 禁止（semantic keywords） |
|---|---|
| `^\d+\.\d+\s*[-–]\s*.+` → L2 | `HOUSE,ROOM,TANK` → L2 |
| `has_unit_qty` → L4 | `PUMP HOUSE` → L2 |
| `all_caps_no_number` → L3 | `EXCAVATION` → L3 |
| `desc_starts: "Allow for"` → Note | `SUBSTATION` → L2 |

**为什么**：规则集的目标是跨项目复用。具体名词换一个项目就失效，本质上是把 LLM 该做的语义理解退化成了字符串匹配。

正确的做法：Step 2 Agent 遇到 ALL-CAPS 行时，用三问判定法直接判断该行是 L2 还是 L3，输出到 `assignments.json`：

```json
{
  "assignments": [
    {"xl_row": 245, "level": "L2", "reason": "PUMP HOUSE: Q1独立建筑, Q2多专业, Q3可独立排程"},
    {"xl_row": 312, "level": "L3", "reason": "EXTERNAL ROADS: Q1否(区域分类), 封顶L3"},
    {"xl_row": 480, "level": "L3", "reason": "EXCAVATION: 施工工序非独立交付物"}
  ]
}
```

## 为什么 Step 2 只需 1 个 Agent

v1 用 3 个 Agent 围攻同一份数据是因为每个 Agent 都低头看逐行数据，需要互相纠错。

v3 不需要：
1. Step 2 做的是"归纳"不是"纠错" — 识别模式、判断归属是理解任务
2. 骨架信息量小 — ~200 行（去掉了 1000+ 行 L4 数据），1 个 Agent 能完整读完
3. 输出可审计 — 规则有误在 Step 4 未命中率上会体现

当 Step 4 未命中行 >50 或存在明显矛盾时，拆成多个 Agent 并行审查。这是异常分支，不是默认路径。

## 深度嵌套判定：三问框架（L2 vs L3）

用于区分"独立交付物（值得 L2）"和"分类类别（封顶 L3）"。

子项究竟是父项的**组成部分**（施工工序），还是父项的**子分类**（种类细分）？

```
PUMP HOUSE ──组成部分──→ EARTHWORK        PUMP HOUSE 是"一栋建筑"
                ├──→ RC WORKS              EARTHWORK 是它的施工分部
                ├──→ WALL FINISHES
                └──→ MEP

EXTERNAL ROADS ──子分类──→ CARRIAGEWAYS    EXTERNAL ROADS 是"一类工程"
                    ├──→ FOOTPATHS         CARRIAGEWAYS 是它的子类型
                    └──→ NON-CARRIAGEWAY
```

### 三问判定

| 问题 | 判定逻辑 | PUMP HOUSE | EXTERNAL ROADS |
|------|----------|-------------|----------------|
| **Q1 资产测试** | 有明确物理边界的、可独立命名的构筑物/建筑/系统？ | Yes | No |
| **Q2 多专业测试** | 子项跨越多个施工专业（土方+混凝土+装修+MEP）？ | Yes | No |
| **Q3 独立排程测试** | 能在另一份 BOQ 中作为独立的 Schedule 出现？ | Yes | No |

- 三问全 Yes → **L2**（独立交付物/工作包）
- 一个或以上 No → **L3**（分类子类别），封顶 L3 不再提升
- 无法判断 → 标记 `confidence: low`，交 Step 4 逐条审查

这套规则依赖 LLM 的世界知识（"水泵房是独立建筑吗？"），不依赖具体 BOQ 的项目名称。换一个 BOQ 出现 `SUBSTATION BUILDING` vs `LANDSCAPING`，同样适用。
