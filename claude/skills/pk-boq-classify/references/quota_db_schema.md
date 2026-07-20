# 定额库分类字典参考

## 数据库位置

`F:\BaiduSyncdisk\2.清单定额\3 清单规范\企业定额\`

## 三册覆盖范围

| 文件 | 范围 | L1 分部数 | L2 子分部数 | L3/L4 条目数 |
|------|------|-----------|-------------|-------------|
| `A册 建筑装饰.sqlite` | 建筑装饰 | 22 | 98 | 472 |
| `B册 通用机电.sqlite` | 通用机电 | 14 | 136 | 1188 |
| `C册 市政园林.sqlite` | 市政园林 | 15 | 64 | 765 |

## 表结构

### divisions (L1 分部)

| 列 | 类型 | 说明 |
|----|------|------|
| code | TEXT | 分部编号 (e.g. `A.06`) |
| name | TEXT | 分部名称 (e.g. `砌筑工程`) |
| description | TEXT | 分部描述 |

### sub_divisions (L2 子分部)

| 列 | 类型 | 说明 |
|----|------|------|
| division_code | TEXT | 所属 L1 分部编号 |
| sub_code | TEXT | 子分部编号 (e.g. `01`) |
| name | TEXT | 子分部名称 (e.g. `砖砌体`) |

### items_gb (L3 分项 + L4 子项)

| 列 | 类型 | 说明 |
|----|------|------|
| division | TEXT | 所属 L2 子分部编号 |
| sub_level3 | TEXT | L3 分项 (e.g. `砖基础`) |
| name | TEXT | L4 子项名称 (e.g. `砖基础 水泥砂浆 M7.5`) |
| unit | TEXT | 计量单位 |
| item_feature | TEXT | 项目特征 |
| calc_rule | TEXT | 计算规则 |
| work_content | TEXT | 工作内容 |

## LLM 审核时的查询策略

### 按册加载 L1-L2 大纲

```sql
SELECT d.code, d.name, s.sub_code, s.name
FROM divisions d
JOIN sub_divisions s ON s.division_code = d.code
ORDER BY d.code, s.sub_code
```

### 按 BOQ 专业选择对应册

| BOQ Discipline | 对应定额册 |
|----------------|-----------|
| Architectural / Structural / Decoration | A册 建筑装饰 |
| MEP / HVAC / Plumbing / Electrical / ELV | B册 通用机电 |
| Infrastructure / Landscape | C册 市政园林 |

### LLM 上下文用量

全量 L1-L2 大纲约 30-50 行（<2k token），可直接注入 LLM prompt 作为分类参考字典。
L3-L4 明细仅在需要确认具体分类边界时才查询。
