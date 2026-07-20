---
name: pk-norms-export
description: "导出港口定额明细：根据定额编号列表，从SQLite数据库中提取完整定额子项，按《沿海港口水工建筑工程定额》六章编排，导出为VLOOKUP友好的Excel格式（A-BQ列，与3.3土建定额表结构一致）。适用于报价书中定额明细表的一键生成。"
---

# 港口定额明细导出

从SQLite定额库中按编号提取定额，按章编排导出为Excel格式，列结构与报价书中3.3土建定额表完全一致。

## 模板文件

`assets/quota_template.xlsx` 是导出格式的基准模板。所有导出必须与此模板的列结构（A-BQ）、表头（中英文双行）、冻结窗格（A4）完全一致。模板包含一章示例数据行供参考。

## 工作流

```
定额编号列表 → export_quota.py → 按章分组 → 查询SQLite → 资源子项转列 → Excel输出
```

## Step 1: 准备定额编号列表

JSON格式，支持两种形式：

**简化形式**（仅编号，自动查章）:
```json
["1278", "2612", "4042", "6021", "6001"]
```

**完整形式**（指定元数据）:
```json
[
  {
    "code": "1278",
    "chapter": "第一章 土石方工程",
    "section": "第二节 陆上铺填工程",
    "table": "二十三、码头及护岸后填砂",
    "unit": "m³",
    "en_name": "Sand Filling Behind Wharf"
  }
]
```

## Step 2: 运行导出脚本

```bash
python scripts/export_quota.py codes.json -o 港口定额_导出.xlsx
```

或从stdin：
```bash
echo '["1278","2612"]' | python scripts/export_quota.py --stdin -o output.xlsx
```

## 输出格式

输出Excel结构完全对标3.3土建定额表：

| 行 | 内容 |
|----|------|
| 1 | 英文表头: code, item_name, unit, description, type, content, rule, english_name, amount, quantity, rate, labour, materials, mech, qty1~55 |
| 2 | 中文表头: 定额编号, 项目名称, 单位, 项目特征, 分类指标, 工作内容, 计算规则, 英文名称, 成本合价, 工程量, 单价, 人工, 材料, 机械, 消耗量1~55 |
| 3+ | 按章编排的数据 |

**每章结构**：
- 章标题行（蓝色填充）：章编号 + 【章名称】 + 【英文名】
- 节标题行（含资源子列头）：消耗量列O-BQ显示该章特有的资源名称/单位
- 参考单价行（灰色）：留空供用户填写单价
- 数据行：每定额一行，A列定额编号，O-BQ列填入该子项消耗量

## 列布局（固定69列 A-BQ）

**固定列 A-N**：code/定额编号, item_name/项目名称, unit/单位, description/项目特征, type/分类指标, content/工作内容, rule/计算规则, english_name/英文名称, amount/成本合价, quantity/工程量, rate/单价, labour/人工, materials/材料, mech/机械

**消耗量列 O-BQ**（55列）：每章按资源出现顺序排列，人工在最前，材料其次，机械最后。列头显示资源名称和单位（如"人工\n工日"）。

## 数据库

定额数据库路径在 `config/db_config.json` → `db.path`（当前: `Norms-AI/output/db/norms_jts276-1-2019_excel.sqlite`）。

每个定额编号对应多个子项行（人工、各材料、各机械），脚本自动将子项按名称归类（人工/材料/机械），去除基价行，转置为列。

定额编号与章节对应：
- 1xxx → 第一章 土石方工程
- 2xxx → 第二章 基础工程
- 3xxx → 第三章 预制安装工程
- 4xxx → 第四章 现浇混凝土工程
- 5xxx → 第五章 钢结构工程
- 6xxx → 第六章 其他工程

## 数据库清洗

导出前自动校验 `norms_table.unit` 列质量。清洗逻辑来自 pk-norms-import 的 `db_clean` 模块：

- **单位清洗**: 去除中文描述（`10m³混凝土`→`10m³`），修正 OCR 误识别（`l`→`1`）
- **缺失回填**: 从 `work_content` 尾部提取单位回填空值
- **视图**: 依赖 `v_quota_name`，由 `db_clean.py` 自动维护

手动运行清洗：
```bash
python ../pk-norms-import/scripts/db_clean.py <db_path>
```

## 资源分类

子项自动分类为人工/材料/机械，决定消耗量列的排列顺序：
- **人工**: 人工, 潜水组
- **机械**: 含"机/船/车/泵/钻/搅拌/起重/装载/推土/压路/打桩/挖掘/自卸/拖轮/驳/发电/空压/电焊"等关键词
- **材料**: 其余（砂、石、混凝土、钢筋、型钢、炸药……）
