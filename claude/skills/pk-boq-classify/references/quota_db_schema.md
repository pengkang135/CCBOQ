# 定额库分类字典参考

## 数据库位置

`E:\Code\Norms-AI\db\`（5 册主引用源）

## 五册覆盖范围

行数为 2026-08-25 实测值，库更新后会变，以实际查询为准。

| 文件 | 范围 | division (L1) | sub_division (L2) | enterprise_item (L3/L4) | chapter |
|------|------|---:|---:|---:|---:|
| `企业定额_A册_建筑装饰.sqlite` | 建筑装饰 | 20 | 107 | 593 | 683 |
| `企业定额_B册_通用安装.sqlite` | 通用安装 | 14 | 136 | 1188 | 1338 |
| `企业定额_C册_市政园林.sqlite` | 市政园林 | 15 | 64 | 825 | 1019 |
| `企业定额_D册_水运工程.sqlite` | 水运工程 | 10 | 22 | 404 | 471 |
| `企业定额_E册_房屋修缮.sqlite` | 房屋修缮 | 13 | 0 | 0 | 1637 |

A / C / D 三册走 `division → sub_division → enterprise_item` 三层检索；B / E 走 chapter 树 —— E 册的 sub_division 和 enterprise_item 是空表，只能走 chapter。

## 统一表结构（2026-08 起，5 册对齐）

### `division`（L1 分部）

| 列 | 类型 | 说明 |
|----|------|------|
| code | TEXT | 分部编号（e.g. `A.06`） |
| name | TEXT | 分部名称 |
| name_EN | TEXT | 英文译名 |
| description | TEXT | 分部描述 |
| description_EN | TEXT | 英文描述 |

### `sub_division`（L2 子分部）

| 列 | 类型 | 说明 |
|----|------|------|
| division_code | TEXT | 所属 L1 分部编号 |
| sub_code | TEXT | 子分部编号 |
| name | TEXT | 子分部名称 |
| name_EN | TEXT | 英文译名 |

### `enterprise_item`（L3 分项 + L4 子项，企业清单项）

| 列 | 类型 | 说明 |
|----|------|------|
| code | TEXT | 清单编号 |
| division | TEXT | 所属 L2 子分部编号 |
| sub_level3 | TEXT | L3 分项 |
| name | TEXT | L4 子项名称 |
| name_EN | TEXT | 英文名称 |
| unit | TEXT | 计量单位 |
| item_feature / _EN | TEXT | 项目特征（中/英） |
| calc_rule / _EN | TEXT | 计算规则（中/英） |
| work_content / _EN | TEXT | 工作内容（中/英） |
| chap_ID | INTEGER | 定额章节链接 |

### `nrm_item`（英标 NRM 清单，反向翻译目标）

`name / name_ZH`、`level_one / level_one_ZH`、`level_two / level_two_ZH`、`nrm_section_title / nrm_section_title_ZH`

## LLM 审核时的查询策略

### 按册加载 L1-L2 大纲（含英文）

```sql
SELECT d.code, d.name, d.name_EN, s.sub_code, s.name, s.name_EN
FROM division d
JOIN sub_division s ON s.division_code = d.code
ORDER BY d.code, s.sub_code
```

### 按 BOQ 专业选择对应册

| BOQ Discipline | 对应定额册 |
|----------------|-----------|
| Architectural / Structural / Decoration | A 册 建筑装饰 |
| MEP / HVAC / Plumbing / Electrical / ELV | B 册 通用安装 |
| Infrastructure / Landscape | C 册 市政园林 |
| Marine / Port / Waterway | D 册 水运工程 |

### LLM 上下文用量

全量 L1-L2 大纲约 30-50 行（<2k token），可直接注入 LLM prompt 作为分类参考字典。
L3-L4 明细仅在需要确认具体分类边界时才查询 `enterprise_item`。

## 术语一致性辅助

`glossary.sqlite`（同目录）提供 26K+ 中英术语对，可 ATTACH 后作为翻译/审核参考。

## E 册（房屋修缮）的结构差异

E 册只有 `division`(13) 和 `chapter`(1637)，`sub_division` 和 `enterprise_item` 都是 0 行。
闭词表因此走 chapter 树：L1 章节当 Category、L2 当 Subcategory、L3 当 Element，
章名的「第X章 」前缀要剥掉再入表 —— 带前缀的名字进闭词表，LLM 抄回来的值和库里对不上。

`validate_classification.py` 的 `_has_sub_divisions()` 自动判定走哪条路，
`candidate_retrieval.py` 里 E 册走 `_query_chapter_tree()`（和 B 册一个路子）。

E 册的 `name_EN` / `chap_Name_EN` 目前整列为 NULL，**英文清单套不了 E 册**
（`load_closed_vocab(lang="en")` 对该册返回空并给出 WARN）。术语库 `glossary.sqlite`
只覆盖 13 个分部里的 3 个、1496 条章名里的 43 条，回填解决不了，需要在 Norms-AI
项目里正式翻译。译名一旦补上，本技能侧无需任何改动即可生效。
