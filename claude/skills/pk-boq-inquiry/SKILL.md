---
name: pk-boq-inquiry
description: "询价包拆分与主材表提炼：BOQ清单拆分（分包询价清单）、图纸资料分发（按关键词筛选分发到标准化目录）、主材表提炼/市场询价表生成（BOQ→提取叶节点→合并归类→剔除辅材→分级询价表）。当用户需要拆分询价包、制作分包询价清单、分发图纸、提炼主材、制作市场询价表时使用。"
license: Proprietary. LICENSE.txt has complete terms
---

# PK BOQ — 询价包与主材表

> 清单合并/对比/校验等核心操作 → 触发 `pk-boq` 技能
> 工程造价约定、Excel 兼容性、BOQ 层级体系 → 见 `pk-boq` 技能

## 触发词速查

| 触发词 | 对应 |
|--------|------|
| 拆分询价表、制作询价清单、分包询价清单、提取BOQ子分部 | `split_inquiry_boq.py` |
| 分发图纸、准备询价资料、询价包目录 | 图纸分发（手工流程） |
| 主材表、材料清单、材料汇总、市场询价表、合并主材 | `build_inquiry_materials.py` |

## 决策树

```mermaid
flowchart TD
    START["询价资料/主材需求"] --> Q1{"任务类型？"}

    Q1 -->|"拆分询价包"| Q2{"需要什么？"}
    Q2 -->|"从总承包BOQ提取子分部"| I1["split_inquiry_boq.py<br/>以combine.xlsx为骨架"]
    Q2 -->|"筛选分发图纸"| I2["图纸分发<br/>find -iname 关键词匹配<br/>复制保持源层级"]
    Q2 -->|"完整询价包"| I3["先 BOQ 拆分<br/>再图纸分发"]

    Q1 -->|"主材表/市场询价"| Q3{"设计院数量？"}
    Q3 -->|"单设计院"| M1["直接走三阶段"]
    Q3 -->|"多设计院"| M2["先 pk-boq compare_boq<br/>选基准院 → 再三阶段"]
    Q3 -->|"有中间产物"| M3["--phase 2 或 3 续跑"]

    M1 --> PIPE
    M2 --> PIPE

    subgraph PIPE["build_inquiry_materials.py 三阶段"]
        P1["Phase 1: 提取<br/>BOQ → 叶节点<br/>跳过LS/总价项"] --> P2["Phase 2: 合并归类<br/>关键词匹配<br/>合并同类材料<br/>剔除辅材<br/>×1.05取整"] --> P3["Phase 3: 格式化<br/>L1/L2 分级<br/>规格→项目特征<br/>15列模板输出"]
    end

    style I3 fill:#fce4ec
    style PIPE fill:#e8f5e9
```

## split_inquiry_boq.py — BOQ 清单拆分

从总承包 BOQ 提取子分部，以基础模板为骨架组装独立询价清单。

```bash
python ../pk-boq/scripts/split_inquiry_boq.py \
    --template "combine.xlsx" \
    --source "WTCC.xlsx" --label WTCC \
    --source "FHDI.xlsx" --label FHDI --fix-ref "1" \
    --match "E_Quay" \
    --output "output.xlsx"
```

关键规则：以模板为骨架、完整复制列结构、Section（如 E.2）为最小保留单元、多方案都保留。

详细工作流 → [../pk-boq/references/inquiry_package_boq.md](../pk-boq/references/inquiry_package_boq.md)

## 图纸分发

按文件名关键词匹配分发图纸到标准化目录结构，不打开文件读取内容。

```bash
# 搜索示例
find <源目录> -iname "*关键词*"
```

核心规则：
- 用 `find -iname` 搜索（不用 MCP search），双语关键词并行
- 编号文件先查图纸索引再选图，无直接匹配选结构图或总图
- 每次分发前检查参考包的完整目录结构
- 复制保持源层级，不扁平化

标准目录结构：`{包编号} {包名称}/ → 1.BQ/ 2.Employer's documents/ 3.Tender Design/ 4.PER/ 5.Site surveys/`

详细工作流 → [../pk-boq/references/inquiry_package_splitting.md](../pk-boq/references/inquiry_package_splitting.md)

## build_inquiry_materials.py — 主材表/市场询价表

三阶段流水线，从设计院 BOQ 到分级市场询价表：

```bash
python ../pk-boq/scripts/build_inquiry_materials.py \
    --source <BOQ.xlsx> --config <config.json> \
    --template <模板.xlsx> -o <输出目录>
```

可 `--phase 1/2/3` 分阶段续跑。Phase 1 输出 `items.json`，Phase 2 输出 `consolidated.json`，Phase 3 输出最终 .xlsx + .md。

配置文件格式和归类规则 → [../pk-boq/references/consolidation_rules.md](../pk-boq/references/consolidation_rules.md)
完整工作流 → [../pk-boq/references/material_inquiry_workflow.md](../pk-boq/references/material_inquiry_workflow.md)

## 参考索引

| 文档 | 内容 |
|------|------|
| [../pk-boq/references/inquiry_package_boq.md](../pk-boq/references/inquiry_package_boq.md) | BOQ 清单拆分完整工作流 |
| [../pk-boq/references/inquiry_package_splitting.md](../pk-boq/references/inquiry_package_splitting.md) | 图纸分发完整工作流 |
| [../pk-boq/references/consolidation_rules.md](../pk-boq/references/consolidation_rules.md) | 主材归类规则编写指南 |
| [../pk-boq/references/material_inquiry_workflow.md](../pk-boq/references/material_inquiry_workflow.md) | 主材表提炼完整工作流 |
| [../pk-boq/references/scripts_reference.md](../pk-boq/references/scripts_reference.md) | 完整 CLI 参数参考 |
