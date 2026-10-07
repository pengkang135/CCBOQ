# Rate 模型结构参考

MongoDB 集合 `cost_data_platform.rates`，对应 `E:\Code\CostSpread\backend\models\Rate.js`。

> **填报员必读**：下面分两张表。第一张是你要填的，第二张**一律不要填**——
> 那些是业务规则的产物，由导入器统一计算。规则会演进，导入器算的可以改规则重跑；
> 填报固化进数据的日后无法统一修正。

---

## 一、源文件事实（填报员填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | String | **是** | 材料/服务名称 |
| `features` | String | 否 | 项目特征/规格描述 |
| `unit` | String | **是** | 单位。**填源文件原样**（源文件写 `sqm` 就填 `sqm`），归一化由导入器做 |
| `price_incl_tax` | **Number** | 二选一 | 含税单价 |
| `price_excl_tax` | **Number** | 二选一 | 除税单价 |
| `currency` | String | **是** | 币种（THB / CNY / USD…） |
| `date` | **Date** | **是** | 报价日期。**泰国佛历年 = 公历年 + 543** |
| `country` | String | **是** | 国家 |
| `city` | String | 否 | 城市 |
| `specialty` | String | 否 | 专业。税率计算依赖它，勿臆造 |
| `supplier` | **String** | 否 | 供应商名。**必须是字符串，不能是对象** |
| `contact` / `phone` / `address` | String | 否 | 联系方式 |
| `projectName` | String | 否 | 项目名称 |
| `remarks` | String | 否 | 备注 |
| `sourceRef` | Object | **是** | `{ file, page, row, rawText }` |

### 价格字段的两条铁律

**1. 类型是 Number，不是 String。**

历史上这份文档曾写成 String，导致大批价格以字符串入库。现在 `rates` 集合有数据库层
validator，**字符串价格会被直接拒绝**。

**2. 读不到填 `null`，绝不要填 `0`。**

填 `0` 会被当成"这东西不要钱"，比缺失更糟——436 条零价记录就是老脚本 `|| '0'` 造成的，
最终 308 条只能删除。

只填源文件上真实存在的那个税价，另一个留 `null`。导入器会按国别税率反算
（泰国 VAT 7%：含税 = 除税 × 1.07）。

### sourceRef.rawText 的特殊要求

预检会**自动比对你解析出的价格是否真的出现在 `rawText` 里**。原文写 `888` 却填了
`8880`，会被当场标进异常清单。

因此 `rawText` 必须截取到**包含价格的那一行**，不能只截品名行。

这是唯一不依赖历史数据的价格防线——新品类首次入库时，历史价比对和批内自比都失效，
只有它还能发现 OCR 错读。

---

## 二、业务派生（导入器算，填报员勿填）

| 字段 | 类型 | 由谁产生 |
|------|------|---------|
| `resourceType` | Enum | 分类器：`material` / `labor` / `machinery` / `composite` / `indirect` |
| `category` | String | 分类器，12 类材料大类，仅 material 有值 |
| `priceSource` | Enum | 校验器：`published` 信息价（无需供应商）/ `quotation` 报价（供应商必填）/ `project` |
| `unit_raw` | String | 归一化前的原始单位 |
| `searchText` | String | 双语搜索聚合 |
| `classifyMeta` | Object | 分类置信度与来源 |
| `priceSourceMeta` | Object | 来源判定依据 |
| `importBatchId` | String | 批次号，用于整批回滚 |
| `needsReview` | Boolean | 价格异常时自动标记 |
| `uploaderId` / `uploaderNickname` | ObjectId / String | 导入器写入 |
| `status` | Enum | 固定 `approved` |
| `name_en` / `features_en` / `supplier_en` 等 | String | 翻译富化环节产生 |

---

## 三、数据库层强制约束

`rates` 集合已启用 `$jsonSchema` validator（`validationAction: error`），**由 mongod
服务端执行，任何客户端都绕不过**——包括 `strict:false` 的 Mongoose 模型、原生驱动、
mongosh 手敲。

以下写法会被数据库直接拒绝：

| 违规 | 例子 |
|---|---|
| `date` 非 Date 型 | `"2026-07-29"` |
| 价格非数值 | `"100.50"` |
| `supplier` 为对象 | `{ name: "机电局" }` |
| `uploaderId` 非 ObjectId | `"697ae529..."` |
| 缺 `uploaderId` | — |
| `resourceType` / `priceSource` 取值越界 | 自造枚举值 |

这几种写法正是历史上 9,335 条类型污染与 436 条零价的成因，现已在数据库层永久封死。

---

## 四、关键索引

```
{ country: 1 }                                   { status: 1, date: -1 }
{ specialty: 1 }                                 { status: 1, country: 1, date: -1 }
{ name: 1 }                                      { status: 1, resourceType: 1, category: 1, date: -1 }
{ date: 1 }                                      { status: 1, country: 1, resourceType: 1, date: -1 }
{ supplier: 1 }                                  { importBatchId: 1 }
{ resourceType: 1 }  { category: 1 }             { needsReview: 1 }  { priceSource: 1 }
```

完整字段定义以 `backend/models/Rate.js` 为准，本文档只覆盖导入相关部分。
