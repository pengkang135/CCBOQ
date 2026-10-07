# 官方价格册链（Schedule of Rates / Material Price List / 信息价）

适用：政府或权威机构公开发布的价格册，由采集器（`backend/scripts/harvest`）下载归档，不是供应商报价。典型：斯里兰卡各省 BSR/材料价格表、孟加拉 PWD/LGED SoR、泰国 TPSO 分府建材价。`priceSource` 一律 `published`，`supplier` 填发布机构。

与主线完全相同的部分：填报与审核是两个独立上下文，预检 → `--analyze` → `audit-recall` → `review-notes` → `--apply` → 归档。这条链只改「填报」这一步怎么做。

## 为什么要单列一条链

2026-10-01 西部省材料价格表第一次导入出过事：自写脚本既做解析又决定资源类型，再自己审核入库，2,586 条里 20 条机械租赁和按天计价的人工被标成材料、钢筋钢丝被归进管材、`L.ft` 的圆钢没法跟钢筋比价。整批回滚重做。教训：

1. **解析脚本只做转换，语义判断交填报员。** 脚本不决定资源类型、不译名、不换算单位。
2. **价格册 = 人工 + 机械 + 材料三种东西混在一张表里**，且按版面小节分组。靠名称规则分类必错，要让填报员看小节标题判断。
3. **单位不可比等于没入库。** 英尺、磅、Cube、包装规格必须折成 m / kg / L / m³，否则同一材料跨来源没法比价。

## 流程

```
采集器归档原件（5 官方信息价/<国家>/<来源>/<文件>__<sha8>.pdf，_待处理.jsonl 里有一条）
  │
  ① 转换（确定性脚本，如 backend/workers/parse/lk_wp_material.py）
  │   抽取工具：有文本层 + **有线表格** → `pdfplumber.extract_tables()` 按列抽；
  │             无线表格 → `table_settings={'vertical_strategy':'text'}` 或 `pdf2docx`→`python-docx`。
  │   **不要用 `extract_text().split('\n')` 硬切**（只在一行一价的巧合版式上碰对；
  │   西北省 HSR 的 `CODE | DESCRIPTION | UNIT | Rate` 表格会串行——实测按行切 156 条、抽表 495 条）。
  │   产出 <批次目录>/raw/rows.jsonl（逐行 {row,page,section,name,unit_raw,price,raw}）
  │        raw/*.md（全文）、skipped.json（跳过行及原因）、source-meta.json、archive-map.json
  │   序号必须严格连续、末页序号对得上，否则报错退出，不静默丢项
  │
  ② 填报（data-preparer 子 agent，按行段并行，约 200 行一段）
  │   规则写成文件交给它们：labeling-instructions.md
  │   产出 labels-N.json：{row, zh, rt, cat, uncertain}
  │   同一份价格册在多个地区/版本里名称相同时，只标一份，其余按 row 对位复用
  │
  ③ 合成 manifest（build_manifest.py，不做语义判断，缺标注的行直接报错）
  │   unit = 原文单位，price = 原文价格（含税/不含税按表头），name = 英文 + 中文译名
  │   suggest = 填报员给的 {resourceType, category}，**不是权威值**，只用于对照分类器
  │
  ④ precheck → --analyze（多出一类「分类分歧」）→ audit-recall → 主会话审核 → --apply
  │
  ⑤ archive-link-harvest.js <批次号> --staging <目录名>   # 回写 archiveRef，不复制文件
```

## 关键约定

| 事项 | 做法 |
|---|---|
| 资源类型与类别 | manifest 里仍然**不填**权威值。填报员的判断放 `suggest`，导入器分类器照常算，两者不一致进「分类分歧」清单 |
| 分类分歧怎么处理 | 按模式成组看：明确是分类器错的 → 修 `resource-classifier.js` / `config/material-categories.js`，并把这批入 `fixtures/golden-*.json` 回归集；库内没有专属类目的边界品类（卫生洁具、木材） → 按分类器放行，在审核结论里写明 |
| 单位换算 | 一律由导入器按 `config/unit-conversion.js` 做，原单位进 `unit_raw`，换算记录进 `unitConversion`。manifest 里不要自己换算 |
| 价格溯源 | 校验用的是 manifest 原值，所以换算不影响 `rawText` 比对 |
| 一行多个价格 | 列标题能确定的（如 AZ150/AZ200 两种镀层）展开成多条；确定不了的（铝型材 BR/NA/PC 三种表面处理）进 `skipped.json`，**不猜** |
| 缺单位或缺价格 | 进 `skipped.json`，不入库 |
| 同一份价格册的多个地区 | 价格不同、名称相同。入库后搜索会出现同名多价，靠 `city` 区分。前端卡片是否展示地区需另行确认 |
| 模型别名 | 2026-10-01 实测 `opus`、`fable` 别名解析到不存在的模型，**不传 model 或传 `sonnet` 可用**；`prepared.model` 如实记录 |

## 回归集

`backend/scripts/check/fixtures/golden-*.json` 的标准答案来源有两条：填报员与分类器一致（两个独立判断），或主会话按模式裁定的分歧。争议品类不入集，免得把争议当标准。改分类规则后必须同时跑：

```bash
node backend/scripts/check/check-classifier-golden.js
node backend/scripts/check/category-accuracy-eval.js
```

重新生成回归集：`python backend/scripts/check/build-golden-lk-wp.py <批次目录>`。

## 容易踩的坑

- **在命令行里用 Python 改含 `\b` 的正则时，经过 shell 转义会变成退格字符 (0x08)**，用 `chr(92)+'b'` 拼，改完用 `grep -c $'\x08'` 查一遍。
- 批次号与 staging 目录名可以不同（回滚后重导用 `-v2`），`archive-link-harvest.js` 用 `--staging` 指定目录。
- 回滚后的批次号能直接重用吗：回滚只删记录，precheck 对 `upload-report.md` 的撞号检查看的是 staging 目录，换批次号最省事。
