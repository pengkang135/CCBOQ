---
name: pk-boq-price-build
description: "人材机价格表构建。将搜集的原始人材机数据按BOQ四级层级分类整理，生成带分级标题和行分组的格式化价格汇总表。触发词：人材机分类、人材机价格表、直接费汇总、材料分类整理、价格表制作、build price sheet、classify materials。"
---

# pk-boq-price-build — 人材机价格表构建

将各类来源的人材机数据（劳务、材料、机械），按预定义大纲分类整理为 BOQ 格式的价格汇总表。

## 触发词

| 中文 | English |
|------|---------|
| 人材机分类 / 人材机价格表 / 人材机分级 | build price sheet |
| 直接费汇总 / 直接费表 | classify materials/labor/equipment |
| 材料分类整理 / 价格表制作 | generate price summary |

## 工作流

```
原始数据.xlsx → 加载YAML规则 → 逐行分类 → L3自动检测 → 层级排序 → 格式化输出 → 价格表.xlsx
```

## 输入

| 列 | 必填 | 说明 |
|----|------|------|
| 专业 | 是 | 原始分类：人工费/材料费/机械费，用于一级分流 |
| 名称 | 是 | 材料/设备/工种名称，用于关键词匹配 |
| 项目特征 | 否 | 补充描述 |
| 单位 | 否 | 计量单位 |
| 除税单价 | 否 | 单价（数字） |
| 税金 | 否 | 单位税金 |
| 含税单价 | 否 | 含税单价 |
| 备注 | 否 | 用于中籍人员月薪判断等 |

## 配置文件

本项目只定义「分类什么」，不重复定义「怎么格式化」。

| 文件 | 用途 |
|------|------|
| `config/hierarchy_template.yaml` | 价格表分级大纲：定义有哪些【L1】《L2》{L3} |
| `config/classification_rules.yaml` | 分类规则：关键词→类别映射，有序首匹配 |

## 引用规则

以下从 pk-boq 族继承，本技能不重复定义：

| 规则 | 来源 |
|------|------|
| 四级层级 `【】→《》→{}→条目` | [boq_hierarchy_rules.md](../references/boq_hierarchy_rules.md) |
| Outline level: L1=0, L2=1, L3=2, L4=3 | 同上 |
| 样式常量 (fill/font/size) | 同上 |
| Excel 兼容性：xlsxwriter 优先，无合并单元格 | [excel_compatibility.md](../references/excel_compatibility.md) |
| 输出命名：`{YYYY-MM-DD}_价格表_{内容}.xlsx` | [boq_conventions.md](../references/boq_conventions.md) |

## 分类流程

### Step 1: 一级分流（按「专业」列）

```
专业含"人工费" → 【人工费】
专业含"材料费" → 【材料费】
专业含"机械费" → 【机械费】
```

### Step 2: 二级分流（按名称关键词）

按 `classification_rules.yaml` 中定义的规则顺序逐条匹配，首匹配胜出。

### Step 3: 三级检测

二级分类项目数 > 30 时，自动启用三级子分类（通过关键词或 L3 分类器函数）。

### Step 4: L3 补充

部分二级分类分类函数不直接返回 L3（如《周转材料》），通过 `extra_l3_map` 根据行数据重新计算 L3。

## 脚本用法

```bash
python scripts/build_price_sheet.py <input.xlsx> [options]

参数:
  input.xlsx              原始人材机数据文件
  -o, --output PATH       输出文件路径（默认：与输入同目录，加 _分级版 后缀）
  -s, --supplier TEXT     供应商/成本来源名称
  -d, --date TEXT         日期标记（默认：YYYY年M月）
  -c, --config-dir PATH   配置文件目录（默认：../config/）
  --no-l3                 禁用自动L3检测
```

示例：
```bash
python scripts/build_price_sheet.py 人材机直接费汇总.xlsx \
  -s "二航局Laldia集装箱码头投标成本价" -d "2026年6月"
```

## 输出格式

- 15 列：编号、专业、名称、项目特征、单位、除税单价、税金、含税单价、日期、币种、供应商、联系人、电话、地址、备注
- 分级标题写在「名称」列，L1 在「编号」列写 'P'
- 无合并单元格
- 行分组（outline level）支持 Excel 原生 +/- 折叠
- 配色：L1 `#C6D9F1` / L2 `#EEF2FA` / L3 `#FBE5D6` / L4 无填充

## 扩展新类别

1. 在 `hierarchy_template.yaml` 中添加 L1/L2/L3 节点
2. 在 `classification_rules.yaml` 中添加匹配规则（注意优先级顺序）
3. 如需特殊 L3 分类逻辑，在 `build_price_sheet.py` 中添加 L3 分类器函数
