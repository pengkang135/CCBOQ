---
name: pk-boq-quotation
description: >
  报价单数据导入全流程：将PDF/图片/Excel等原始报价文件转换为结构化数据，上传到MongoDB数据库并生成HTML报告，支持批量输出统一风格Excel材料价格表。
  触发条件：用户要求"导入报价单"、"整理报价文件"、"上传报价数据"、"处理供应商报价"、"提取报价"、"报价资料"、"人工单价"、"材料单价"、"价格表PDF"，或需要将报价单目录下的原始文件（PDF、JPG/PNG图片、Excel）转换入库。
  适用场景：CostSpread项目中将供应商原始报价单系统化导入数据库的工作流，涵盖文件转换、翻译、数据提取、上传、报告生成、批量Excel输出全链路。
---

# 报价单数据导入

> 工程造价约定、Excel 兼容性 → 见 `pk-boq` 技能
> Excel 结构探测、列自动检测 → 使用 `document-ingest` 技能

## 前置检查

1. 读取 `e:\Code\CostSpread\CLAUDE.md` 了解项目约定
2. MongoDB 连接: `mongodb://127.0.0.1:37117/cost_data_platform?directConnection=true`
3. Node 脚本执行需设置 `NODE_PATH="e:\Code\CostSpread\backend\node_modules"`

## 决策树

```
报价资料处理需求
  ├── 单份 PDF/图片/Excel → Step 1-5 全流程（转换→翻译→提取→上传→报告）
  ├── 多份同类文件 → 批量处理 → MongoDB 上传 + 批量 Excel 输出
  └── 仅需 Excel 输出 → 直接用 build_batch_excel.py（跳过 MongoDB）
```

## 工作流程

### Step 1: 扫描并转换源文件

遍历源目录及其子目录，按文件类型选择转换工具。**所有独立文件并行转换**：

| 文件类型 | 工具 | 目标格式 |
|----------|------|----------|
| PDF (.pdf) | `mcp__pdf2md__pdf_to_markdown` | Markdown |
| 图片 (.jpg/.png/.bmp) | `mcp__rapid-ocr__ocr_image` | Markdown |
| Excel (.xlsx/.xls) | `mcp__excel__excel_read_sheet` 或 document-ingest skill | 结构化数据 |

如OCR质量差（非拉丁字符），用 Read 工具直接查看图片交叉验证关键数值。

### Step 2: 翻译非英文内容

将非英文文本（泰文、阿拉伯文等）翻译为中文：

- **材料名称**: 保留英文技术术语，补充中文译名
- **规格描述**: 技术参数保持原文，说明性文字翻译
- **供应商信息**: 公司名、地址、联系人翻译为中文
- **备注/条款**: 完整翻译

遵循工程造价领域术语。常见泰文→中文翻译对：
- `คอนกรีตหยาบ` → 粗混凝土（垫层）
- `คอนกรีตโครงสร้าง` → 结构混凝土
- `คอนกรีตกำลังอัดสูง` → 高强混凝土
- `คอนกรีตโครงสร้างกันซึม` → 防水结构混凝土
- `พื้นคอนกรีตอัดแรง` → 预应力混凝土楼板
- `ราคาสุทธิ` → 净价
- `ใบเสนอราคา` → 报价单

### Step 3: 提取结构化数据

从转换+翻译后的内容提取每条报价记录。数据格式参见 `references/template-format.md`。

每条记录必须包含：
- `name` / `name_cn`: 材料英文名 / 中文名
- `features` / `features_cn`: 规格参数 / 中文规格
- `unit`: 单位
- `price_excl_tax`: 除税单价 (String)
- `price_incl_tax`: 含税单价 (String)
- `date`: 报价日期 (ISO 8601, 泰国佛历年 = 公历年 + 543)
- `currency`: 币种代码

额外提取: 供应商名称、联系人、电话、地址、项目名、源文件名、备注。

**价格计算**: 泰国报价通常标注 "Net Price (before VAT 7%)" → 含税价 = 除税价 × 1.07。若原始数据同时给含税和除税价，保留两者。V Concrete (V&P Global) 报价中已同时提供含税/除税价。

### Step 4: 组装JSON并上传 MongoDB

将数据组装为JSON（格式见 `scripts/upload-rates.js` 头部注释），写入临时文件后运行脚本：

```bash
cd e:\Code\CostSpread\backend && \
NODE_PATH="e:\Code\CostSpread\backend\node_modules" \
node "C:\Users\Kevin\.claude\skills\pk-boq-quotation\scripts\upload-rates.js" \
  <data.json> \
  --mongo-uri "mongodb://127.0.0.1:37117/cost_data_platform?directConnection=true" \
  --uploader-id "697ae529b6529f32ed704b5f" \
  --uploader-name "系统管理员01" \
  --report-dir "<源目录路径>"
```

data.json 核心结构：

```json
{
  "project": { "country": "泰国", "specialty": "数据中心", "city": "...", "projectName": "..." },
  "suppliers": [{
    "name": "Supplier Co., Ltd.",
    "name_cn": "供应商中文名",
    "contact": "...", "phone": "...", "address": "...", "address_cn": "...",
    "projectName": "...", "projectName_cn": "...",
    "sourceFile": "子目录/文件名.pdf",
    "remarks": "备注（中文）",
    "items": [{
      "name": "Material Name", "name_cn": "材料中文名",
      "features": "Spec in English", "features_cn": "中文规格",
      "unit": "m³",
      "price_excl_tax": "1234.56", "price_incl_tax": "1320.98",
      "date": "2026-03-16", "currency": "THB"
    }]
  }]
}
```

脚本自动: 去重（同国家+项目+时间段的旧记录）→ 插入新记录 → 生成HTML报告 → 保存中间JSON。

### Step 5: 批量 Excel 输出

将同一批次多个报价单输出为统一风格的 Excel 材料价格表（16列，人材机价格表格式）：

```bash
python "C:\Users\Kevin\.claude\skills\pk-boq-quotation\scripts\build_batch_excel.py" \
  <data.json> \
  -o <output.xlsx> \
  --title "人材机价格表 — {项目名}" \
  --subtitle "报价日期: {日期范围} | 来源: {供应商列表}"
```

Excel 输出规格（16 列 A-P）：

| 列 | 表头 | 说明 |
|----|------|------|
| A | 编号 | 序号 |
| B | 专业 | 专业分类 |
| C | 名称 | 材料/服务名称（中文） |
| D | 项目特征 | 规格、型号、性能参数 |
| E | 单位 | 计量单位 |
| F | 除税单价 | 不含税单价 |
| G | 税金 | 税额（除税价×税率） |
| H | 含税单价 | 含税单价 |
| I | 日期 | 报价日期 |
| J | 币种 | 货币类型 |
| K | 供应商 | 供应商名称 |
| L | 联系人 | 联系人姓名 |
| M | 电话 | 联系电话 |
| N | 地址 | 供应商地址 |
| O | 备注 | 附加信息 |
| P | 来源 | 原始文件名 |

样式: 标题行合并居中 14pt 加粗，表头蓝底(D9E1F2) 11pt 加粗，分组标题绿底(E2EFDA)，数据行 10pt，末尾汇总行含来源列表和价格统计。

### Step 6: 验证

上传后验证：
1. MongoDB 记录数: 查询 `rates` 集合确认
2. 按供应商分组统计确认分布
3. 确认 HTML 报告文件存在且数据正确
4. 如输出了 Excel，确认文件存在且条目数一致

向用户报告: 总记录数、各供应商记录数、平均单价、报告路径、Excel路径、中间文件路径。

## HTML报告

使用 `assets/report-template.html` 模板，`{{PLACEHOLDER}}` 替换生成。包含:
1. 统计摘要（4卡片）
2. 报价明细表（15列，与 `references/template-format.md` 的模板一致）
3. 供应商详细信息
4. 数据处理说明

## 中间格式文件

在源目录 `_converted/` 子目录保存:
- `uploaded-data.json`: 完整结构化数据
- 可选的 Markdown 汇总

## 质量标准

- 每条报价条目对应一条独立数据库记录，同一材料不同规格/编号分别记录
- 中文翻译覆盖材料名称、规格描述、供应商信息、备注条款
- 价格数值保留原始小数位数
- HTML报告表格列与 `references/template-format.md` 定义一致
- 同一批次上传前清理旧数据防止重复
- 批量 Excel 输出与 HTML 报告数据同源，确保一致性

## 参考资源

- `references/rate-model.md`: Rate 数据库模型完整字段定义
- `references/template-format.md`: 市场询价表模板格式（15列表头及示例）
- `scripts/upload-rates.js`: 数据上传+报告生成一键脚本
- `scripts/build_batch_excel.py`: 批量 Excel 材料价格表生成脚本（与 upload-rates.js 共用 data.json）
- `assets/report-template.html`: HTML报告模板
