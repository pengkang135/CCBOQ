# BOQ / 工程文档翻译已知陷阱

机器翻译（Google Translate / LLM）在处理工程量清单和施工文档时的常见错误模式。

## 审校方法论

**审校机器翻译的 BOQ 文本时，优先检查标题和短名词短语。** 最常见的失败模式是将建筑/工程领域术语误译为日常英语含义。长句通常翻译质量尚可，但 2-4 个单词的章节标题和材料/工序名称错误率最高。

## 陷阱列表

### 材料与工序名称

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Concrete work | 具体工作 | 混凝土工程 | "concrete" = 混凝土，非"具体的" |
| Concrete | 具体的 | 混凝土 | 独立出现时更易误译 |
| Earth work | 地球工作 | 土方工程 | "earth" = 土方，非"地球" |
| Reinforcement work | 加固工作 | 钢筋工程 | "reinforcement" = 钢筋，非"加固" |
| Steel Structure work | 钢结构工作 | 钢结构工程 | "work" 在 BOQ 上下文中 = 工程 |
| Architecture work | 建筑工作 | 建筑工程 | 同上 |
| Structure work | 结构工作 | 结构工程 | 同上 |
| Miscellaneous work | 杂项工作 | 杂项工程 | 同上 |
| Miscellenous work | — | 杂项工程 | 注意源文件拼写错误（应为 Miscellaneous）|
| Formwork | 模板 | 模板 | 此项通常翻译正确 |
| Reinforcing bar / Rebar | 钢筋 | 钢筋 | 此项通常翻译正确 |

### 建筑与设施名称

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Louvre (Ventilation) | 卢浮宫 | 百叶（通风） | 建筑构件，非巴黎博物馆 |
| Lashing Welfare Block | 捆绑福利块 | 加固福利楼 | "lashing" = 加固（集装箱），"welfare" = 福利设施 |
| Lashing Storage | 捆绑存储 | 加固材料储存 | 同上 |
| Lashing Dojo | — | 加固训练场 | "dojo" 此处为训练场所 |
| Guard hut | 守卫小屋 | 警卫亭 | 港口安保岗亭 |
| Troubleshooting Office | 疑难解答办公室 | 故障排除办公室 | 港口运营维护办公室 |
| Load Bank foundation | 负载银行基础 | 负载箱基础 | 电气测试设备 |
| Air Vessel | 空气容器 | 储气罐 | 消防/给水系统组件 |
| Gate Complex | — | 闸口综合体 | 港口术语 |

### 家具与装修

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Loose furniture | 松动的家具 | 活动家具 | FF&E 项目，非"松动" |
| Baseboard | 底板 | 踢脚线 | 装修术语 |
| Skirting | 踢脚线 | 踢脚线 | 此项通常翻译正确 |

### 章节标题

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Miscellaneous | 各种各样的 | 杂项 | BOQ 章节标题 |
| Preliminaries | — | 前期工程/开办费 | 需根据上下文选择 |
| General | — | 总则/一般要求 | 需根据章节层级选择 |

## 常见词根陷阱

这些词在一般英语和工程英语中含义不同：

| 英文词 | 一般含义 | 工程/BOQ 含义 |
|--------|---------|-------------|
| concrete | 具体的 | 混凝土 |
| earth | 地球 | 土方 |
| reinforcement | 加固 | 钢筋 |
| lashing | 捆绑 | 加固（集装箱固定） |
| bank | 银行 | 负载箱 / 组 |
| vessel | 容器/船舶 | 储气罐 / 压力容器 |
| louvre | 卢浮宫 | 百叶 |
| course | 课程 | （铺面）层 |
| finishing | 完成 | 饰面/装修 |
| furniture | 家具 | 附属设施（quay furniture = 码头附属设施）|

### FIDIC 合同术语（机器翻译高频误译）

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Taking-Over Certificate | 接管证书 | 接收证书 | FIDIC 专有术语，"接收"非"接管" |
| Taking Over | 接管/接手 | 接收 | 同上 |
| Performance Certificate | 性能证书 | 履约证书 | "performance"在合同语境 = 履约 |
| Performance Security | 性能保函 | 履约保证 | 同上 |
| Employer | 雇主/雇佣者 | 业主 | 国内工程惯例用"业主"，部分体系用"雇主" |
| Statement (at completion) | 声明 | 报表 | 付款语境中 = 报表/结算表 |
| Claim | 宣称/声称 | 索赔 | FIDIC 第20条专用 |
| Variation | 变化 | 变更 | FIDIC 第13条专用 |
| Determination | 确定 | 决定 | 工程师做出的决定（FIDIC 2017 第3.7条） |
| Extension of Time | 时间延长 | 工期延长 | EOT，FIDIC 第8.5条 |
| Time for Completion | 完成时间 | 竣工时间 | FIDIC 第8.2条 |
| Defects Notification Period | 缺陷通知期 | 缺陷通知期 | DNP（FIDIC 2017改称此名） |
| Defects Liability Period | 缺陷责任期 | 缺陷责任期 | DLP（FIDIC 1999用名，与DNP概念相似但不同） |
| Retention Money | 扣留款 | 保留金 | 扣留的金额，非"扣留"行为 |
| Delay Damages / Liquidated Damages | 约定违约金 | 误期损害赔偿金 | 提前约定的逾期损害赔偿 |
| Force Majeure | 不可抗力 | 不可抗力 | FIDIC 2017 改用"例外事件"(Exceptional Events)，旧版仍用此 |
| Consequential Loss | 相应损失 | 间接损失 | 免责条款关键术语 |
| Fitness for Purpose | 适用于目的 | 适用性 | 设计责任相关 |
| Instruction | 教学/指导 | 指示 | 工程师发出的正式指示 |
| Notice | 注意 | 通知 | 与"指示"不同——FIDIC中对两者的处理不同 |
| Time Bar | 时间禁止 | 逾期失权 | 索赔时限限制 |
| Condition Precedent | 前提条件 | 先决条件 | 索赔权利的前置条件 |
| Interim Payment Certificate | 临时付款证书 | 中期付款证书 | IPC |
| Final Statement | 最终声明 | 最终报表 | 合同结算用 |
| Daywork | 日工 | 计日工 | 按工日计价 |
| Provisional Sum | 暂定总额 | 暂列金额 | 业主预留款 |
| Prime Cost Sum | 主要成本总额 | 暂估价 | 指定分包/供货预留款 |
| Plant | 植物/工厂 | 工程设备 | FIDIC中对"Plant"的定义 = 永久工程的设备 |
| Contractor's Equipment | 承包商设备 | 施工机械 | 与"Plant"(工程设备)不同 |
| Unforeseeable Physical Conditions | 无法预见的物理条件 | 不可预见的物质条件 | FIDIC 第4.12条 |

### 港口/海事术语（机器翻译高频误译）

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Berthing pocket | 泊位口袋 | 泊位港池 | 船舶靠泊水域 |
| Dolphin | 海豚 | 靠船墩 | 独立系靠船结构 |
| Breasting dolphin | — | 靠船墩 | 用于船舶横向靠泊 |
| Mooring dolphin | — | 系泊墩 | 用于系缆 |
| Fender | 挡泥板 | 护舷 | 码头前沿防撞设施 |
| Bollard | 系船柱 | 系船柱 | 此项通常正确 |
| Quay wall | 码头墙 | 岸壁/码头岸壁 | 板桩/重力式码头结构 |
| Coping | 应对/顶部 | 压顶 | 胸墙顶部结构 |
| Apron | 围裙 | 码头前沿/前沿地带 | 码头操作区域 |
| Cold ironing | 冷熨烫 | 岸电 | 船舶靠泊后接岸电 |
| Shore power | 岸电 | 岸电 | 与Cold ironing同义 |
| Reefer | 冷藏工/冷藏间 | 冷藏箱 | 冷藏集装箱 |
| Lashing | 捆绑 | 加固（集装箱）| 集装箱系固 |
| Spreader | 传播器 | 吊具 | 集装箱装卸属具 |
| Reach stacker | 到达堆垛机 | 正面吊运机 | 集装箱堆场设备 |
| Scour protection | 擦洗保护 | 防冲刷 | 水流冲刷防护 |
| Sheet pile | 板桩 | 钢板桩 | 码头/围堰常用 |
| Revetment | 护岸 | 护岸 | 边坡防护结构 |
| Breakwater | — | 防波堤 | 港口防护结构 |
| Turning basin | 掉头盆 | 回旋水域/调头区 | 船舶回旋水域 |
| Navigational aid | 航行辅助 | 助航标志 | 浮标/灯标等 |
| Pilotage | 引航 | 引航/引水 | 进出港引航服务 |
| STS cranes | — | 岸桥 | Ship-to-Shore，码头前沿集装箱起重机 |
| E-RTGs | — | 电动轮胎式龙门吊 | Electric Rubber-Tyred Gantry，堆场起重机 |
| SPMT | — | 自行式模块运输车 | Self-Propelled Modular Transporter |

### 岩土工程术语（机器翻译高频误译）

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| SPT (Standard Penetration Test) | 标准渗透试验 | 标准贯入试验 | 原位测试 |
| CPT (Cone Penetration Test) | 锥体渗透试验 | 静力触探试验 | 原位测试 |
| Surcharge / Surcharging | 额外收费 | 堆载预压 | 软基处理 |
| PVD (Prefabricated Vertical Drain) | — | 预制竖向排水板 | 软基处理 |
| Stone columns | 石柱 | 碎石桩 | 地基处理（振动置换） |
| Vibrocompaction | 振动压实 | 振冲压实 | 砂土加密 |
| Consolidation | 合并 | 固结 | 土体排水压缩过程 |
| Settlement | 解决 | 沉降 | 地基沉降 |
| Liquefaction | 液化 | 液化 | 地震砂土液化 |
| Allowable bearing capacity | 容许承载能力 | 容许承载力 | 地基承载力 |
| PHC pile | — | PHC管桩 | 预应力高强度混凝土管桩 |
| Bored pile | 无聊的桩 | 钻孔灌注桩 | 灌注桩 |
| Driven pile | 驱动的桩 | 打入桩 | 打入桩 |
| Bored cast-in-situ pile | — | 钻孔灌注桩 | 灌注桩的正式名称 |
| Geotextile | 土工织物 | 土工布 | 地基处理材料 |
| Geogrid | — | 土工格栅 | 加固材料 |
| Lean concrete | 瘦的混凝土 | 贫混凝土 | 低强度找平层 |
| Blinding concrete | 失明混凝土 | 垫层混凝土 | 基础垫层 |
| Riprap | — | 抛石 | 防冲刷措施 |
| Gabion | — | 石笼/格宾 | 护岸结构 |

### 采购/商务术语（机器翻译高频误译）

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Letter of Award | 奖励信 | 中标函 | LOA |
| Letter of Acceptance | 接受信 | 中标通知书 | 与LOA等同 |
| Tender Submission | 投标提交 | 投标文件提交 | 含文件的含义 |
| RFP (Request for Proposals) | — | 招标文件 | 含招标要求、合同条件、技术规格 |
| Responsive Tender | 响应式投标 | 实质性响应投标 | 满足招标要求的投标 |
| Post-qualification | 后资格审查 | 资格后审 | 评标后审查 |
| Pre-qualification | 预资格审查 | 资格预审 | 招标前审查 |
| Expediting | 加速 | 催交 | 设备材料催交 |
| Dispatch | 派遣 | 发运 | 货物发运 |
| Offloading | 卸载 | 卸货 | 现场卸货 |
| Vendor | 自动售货机 | 供应商/供货商 | 材料设备供应商 |

### 机电/电气术语（机器翻译高频误译）

| 英文 | 错误翻译 | 正确翻译 | 说明 |
|------|---------|---------|------|
| Bus duct / Busbar | 公交车管道 | 母线槽/母线 | 配电系统 |
| Ring Main Unit (RMU) | 环形主单元 | 环网柜 | 配电设备 |
| Feeder pillar | 馈电柱 | 配电柱/馈线柱 | 户外配电 |
| Marshalling panel | 编组盘 | 汇接盘 | 信号接线 |
| Earthing / Grounding | 接地 | 接地 | 此项通常正确 |
| Equipotential bonding | 等电位捆绑 | 等电位联结 | 电气安全 |
| Lightning protection | 闪电保护 | 防雷 | 此项通常正确 |
| IP rating | IP评分 | 防护等级 | Ingress Protection |
| Switchgear | — | 开关柜 | 中压/低压配电设备 |
| Cable tray | 电缆盘 | 电缆桥架 | 电缆敷设支撑系统 |
| Load bank | 负载银行 | 负载箱 | 电气测试设备 |
| UPS | — | 不间断电源 | Uninterruptible Power Supply |
| Diesel Generator (DG) | — | 柴油发电机 | 备用电源 |
| Small power | 小功率 | 小电源（插座） | 一般用途插座回路 |
| Holding down bolt | 压住螺栓 | 地脚螺栓 | 设备固定 |
| Distribution board | — | 配电盘 | 终端配电 |
| 3P 4W | — | 三相四线制 | 3-Phase 4-Wire |
| VLRA battery | — | 阀控式铅酸蓄电池 | 免维护蓄电池 |
| Cable gland | 电缆腺体 | 电缆密封接头 | 电缆进出线密封 |
| Conduit | 导线 | 线管 | 电线保护管 |
| Corrosion category C5-M / CX | — | C5-M/CX腐蚀等级 | ISO 12944 大气腐蚀分类 |

### JSON编码陷阱（批量翻译特定）

| 问题 | 表现 | 修复方式 |
|------|------|---------|
| 中文文本中嵌入ASCII双引号 `"` | JSON解析失败（`Expecting ',' delimiter`） | 中文引号使用 `""`（U+201C/U+201D），翻译后必须用 `json.dump()` 而非字符串拼接写入 |
| Python字符串拼接构建JSON | 中文引号/换行符被破坏 | 始终使用 `json.dump(data, f, ensure_ascii=False, indent=2)` 序列化 |
| 混淆JSON结构引号与内容引号 | 检查脚本报错但人工读正常 | 规则：中文内容中引用英文术语时用 `""`，不要用 ASCII `"` |

## 使用方式

1. **翻译前**：在 `translate_direct.py` 中加载 `boq-glossary.json` 覆盖已知术语
2. **翻译后**：用 `polish_excel_en2zh.py --pitfalls` 对照此列表扫描和修正
3. **人工审校时**：逐条检查此列表，确认未出现对应错误翻译
4. **批量JSON翻译时**：所有agent必须用 `json.dump()` 写文件，禁止字符串拼接

1. **翻译前**：在 `translate_direct.py` 中加载 `boq-glossary.json` 覆盖已知术语
2. **翻译后**：用 `polish_excel_en2zh.py --pitfalls` 对照此列表扫描和修正
3. **人工审校时**：逐条检查此列表，确认未出现对应错误翻译
