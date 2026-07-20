# Rate 模型结构参考

## MongoDB 集合: `cost_data_platform.rates`

### 字段定义

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| country | String | **是** | 国家，如"泰国" |
| country_en | String | 否 | 国家英文名 |
| specialty | String | 否 | 专业分类，如"数据中心" |
| specialty_en | String | 否 | 专业英文 |
| city | String | 否 | 城市 |
| city_en | String | 否 | 城市英文 |
| name | String | **是** | 材料/服务名称 |
| name_en | String | 否 | 名称英文翻译 |
| features | String | 否 | 项目特征/规格描述 |
| features_en | String | 否 | 规格英文翻译 |
| unit | String | **是** | 单位 (m³, kg, m², 工日等) |
| unit_en | String | 否 | 单位英文 |
| price_excl_tax | String | 否 | 除税单价 |
| price_incl_tax | String | 否 | 含税单价 |
| currency | String | 否 | 币种 (THB, CNY, USD等) |
| date | Date | **是** | 报价日期 |
| supplier | String | 否 | 供应商名称 |
| supplier_en | String | 否 | 供应商英文名 |
| contact | String | 否 | 联系人 |
| phone | String | 否 | 联系电话 |
| address | String | 否 | 地址 |
| projectName | String | 否 | 项目名称 |
| projectName_en | String | 否 | 项目英文名 |
| fileName | String | 否 | 原始文件名/路径 |
| uploaderId | ObjectId | **是** | 上传者用户ID |
| uploaderNickname | String | **是** | 上传者昵称 |
| approverId | ObjectId | 否 | 审批者ID |
| approverNickname | String | 否 | 审批者昵称 |
| status | String | **是** | 状态: pending/approved/rejected |
| searchText | String | 否 | 双语搜索聚合字段 |
| fieldsTranslated | Boolean | 否 | 是否已翻译 |
| remarks | String | 否 | 备注 |

### 关键索引

- `{ country: 1 }`
- `{ specialty: 1 }`
- `{ name: 1 }`
- `{ date: 1 }`
- `{ supplier: 1 }`
- `{ status: 1, date: -1 }`
- `{ status: 1, country: 1, date: -1 }`

### price_excl_tax / price_incl_tax 价格字段

- 类型为 **String**（不是 Number），接受任意格式
- 至少有一个有值即可
- 若只提供 `price_excl_tax`，`price_incl_tax = price_excl_tax × 1.07` (泰国VAT 7%)
- 若只提供 `price_incl_tax`，`price_excl_tax = price_incl_tax / 1.07`
