# NRM Terms Reference

Use this reference when translating engineering, BOQ, quantity surveying, cost planning, procurement, or project control material.

This file is a decision aid, not a rigid dictionary. Prefer project-approved wording first. Use NRM-style wording when the source clearly matches UK-style measurement and cost management practice.

## Priority Order

1. Use client-approved or contract-defined terminology.
2. Use project glossary terms already confirmed in the current job.
3. Use the preferred wording in `nrm-glossary.json`.
4. Use the notes below when one Chinese term may map to multiple English choices.

## Core Rules

- Prefer commercially stable wording over literal wording.
- Keep the same term consistent across the whole file.
- Do not switch between US and UK wording in one deliverable.
- Use `bill of quantities`, `cost plan`, `unit rate`, `preliminaries`, `provisional sum`, and `unit of measurement` as default UK-style anchors when the context fits.
- Flag terms that change scope, cost, or liability instead of guessing.

## Common Decisions

| Chinese | Preferred English | Use Note |
|---|---|---|
| 工程量清单 | bill of quantities | Use `BOQ` only after the full term appears once. |
| 清单项目 | bill item | Use for an individual line item in the BOQ. |
| 分部分项工程量清单 | bill of quantities for measured work | Use when the source refers to measured work sections rather than preliminaries or provisional sums. |
| 计量 | measurement | Use for quantity measurement rules and remeasurement context. |
| 计量单位 | unit of measurement | Keep consistent with abbreviations in the schedule. |
| 工程量 | quantity | Use `measured quantity` when the context stresses verified measurement. |
| 综合单价 | unit rate | Use `composite rate` only when the build-up or all-in composition is being emphasized. |
| 单价分析 | rate build-up | Use for cost composition behind a rate. |
| 合价 | amount | Use for line-item extended value. |
| 暂列金额 | provisional sum | High-risk commercial term; do not replace casually. |
| 暂估价 | prime cost sum | Use only when the source matches allowance-type pricing for nominated supply or specialist scope. |
| 措施项目 | preliminaries | Use when the term covers temporary works, site establishment, management, and general obligations. |
| 前期费用 | pre-construction costs | Do not confuse with `preliminaries`; choose `preliminaries` only for tender or site-running context. |
| 成本计划 | cost plan | Use for stage-based cost planning under NRM-style practice. |
| 成本估算 | cost estimate | Use for estimate, not for structured cost plans. |
| 投标报价 | tender price | Use `tender sum` when referring to the aggregate tendered amount. |
| 招标文件 | tender documents | Use for the full procurement package. |
| 招标清单 | tender bill of quantities | Use when the BOQ forms part of the tender documents. |
| 合同价 | contract sum | Use for the agreed contract amount. |
| 合同变更 | variation | Use `change order` only if the contract system is clearly non-UK or user-specified. |
| 签证 | site instruction | Use cautiously; in some projects this may function more like a variation confirmation. |
| 工作范围 | scope of works | Keep stable in contracts and specifications. |
| 工作内容 | work content | Use for descriptive internal text, not formal contractual scope headings. |
| 规范 | specification | Use `specifications` when the source is plural. |
| 技术要求 | technical requirements | Use for performance or workmanship requirements. |
| 暂定项目 | provisional item | Use when the source is item-based rather than sum-based. |
| 漏项 | omission | Use for missing scope or missing items. |
| 清单漏项 | BOQ omission | High-risk term in claims or tender clarifications. |
| 工程界面 | interface | Use for trade or package interface. |
| 构件 | component | Use `element` when the document is cost-planning by elements rather than describing physical components. |
| 部件 | component part | Use when a smaller assembly part is intended. |
| 分项工程 | work item | Use for a discrete item of work. |
| 分部工程 | work section | Use for grouped sections of work. |
| 单位工程 | building | Use `building` or `unit of accommodation` depending on project context. |
| 土建工程 | civil and structural works | Use `building works` when the context is broad building scope rather than pure civil/structural scope. |
| 建筑工程 | building works | Prefer this for general architectural and building scope. |
| 装饰装修 | finishes | Use `fit-out works` only where tenant or interior fit-out is intended. |
| 机电工程 | MEP works | Expand once if the audience may not know the abbreviation. |
| 给排水 | plumbing and drainage | Use consistently across schedules. |
| 暖通 | HVAC | Expand once if needed as `heating, ventilation and air conditioning (HVAC)`. |
| 电气工程 | electrical works | Use `electrical installation` when the source stresses installation scope. |
| 消防工程 | fire protection works | Use `fire services` if the project uses that established term. |
| 基础 | substructure | Use `foundations` when the source refers specifically to foundation elements. |
| 主体结构 | superstructure | Core NRM cost-planning term. |
| 屋面 | roofing | Use `roof` only in plain descriptive prose. |
| 外立面 | facade | Use `external envelope` if the source clearly covers facade as a systems package. |
| 楼地面 | floor finishes | Use based on whether the source emphasizes finish trade rather than structural slab. |
| 墙面 | wall finishes | Use for finish trade context. |
| 天棚 | ceiling finishes | Use `ceiling` in plain descriptive contexts. |
| 模板 | formwork | |
| 脚手架 | scaffolding | |
| 钢筋 | reinforcement | Use `reinforcing steel` if the document is more formal or technical. |
| 混凝土 | concrete | |
| 砌体 | masonry | |
| 抹灰 | plastering | Use `rendering` for external wall finish context where appropriate. |
| 防水 | waterproofing | |
| 保温 | insulation | Use `thermal insulation` when precision is needed. |
| 材料损耗 | material wastage | Use `waste allowance` when referring to estimating or rate build-up assumptions. |
| 人工 | labour | Keep UK spelling in NRM-style output. |
| 材料 | materials | |
| 机械 | plant | Use `equipment` only when the source clearly means equipment rather than construction plant. |

## High-Risk Terms

Review these manually before final delivery:

- `综合单价`: may be `unit rate` or `composite rate`
- `前期费用`: may be `pre-construction costs` or `preliminaries`
- `构件`: may be `component` or `element`
- `基础`: may be `substructure` or `foundations`
- `签证`: may need project-specific wording
- `暂估价`: may not map cleanly unless the procurement mechanism is clear

## Usage Pattern

When translating engineering files:

1. Load `nrm-glossary.json` as the starting glossary.
2. Add project-specific terms on top of it.
3. Translate with the local model.
4. Review all high-risk terms manually.
