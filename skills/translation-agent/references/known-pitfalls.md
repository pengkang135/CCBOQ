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

## 使用方式

1. **翻译前**：在 `translate_direct.py` 中加载 `boq-glossary.json` 覆盖已知术语
2. **翻译后**：用 `polish_excel_en2zh.py --pitfalls` 对照此列表扫描和修正
3. **人工审校时**：逐条检查此列表，确认未出现对应错误翻译
