# 数据库 Schema

Norms-AI SQLite 数据库完整表结构。Excel 导入复用此 Schema，与 PDF 导入共享同一数据库。

## 核心表

### document — 文档元数据
| 列 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| title | TEXT NOT NULL | 书名 |
| doc_number | TEXT | 标准号（如 JTS/T 276-1-2019） |
| publisher | TEXT | 出版社 |
| effective_date | TEXT | 生效日期 |
| total_pages | INTEGER | 总页数 |
| created_at | TEXT | 创建时间戳 |

### chapter — 四级章节层级
| 列 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| parent_id | INTEGER FK | 自引用（父章节） |
| sort_order | INTEGER | 同级排序 |
| level | INTEGER | 1=章, 2=节, 3=子节 |
| title | TEXT NOT NULL | 章节名称 |
| subtitle | TEXT | 副标题 |
| toc_page | INTEGER | 目录页码 |
| start_page | INTEGER | 起始页 |
| end_page | INTEGER | 结束页 |
| is_appendix | INTEGER | 是否附录 |

### section_text — 文字页面内容
| 列 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| chapter_id | INTEGER FK | 所属章节 |
| page | INTEGER | 页码 |
| seq_no | INTEGER | 序号 |
| type | TEXT | 类型 |
| content | TEXT NOT NULL | 正文内容 |

### norms_table — 定额表元数据
| 列 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| chapter_id | INTEGER FK | 所属章节 |
| section_title | TEXT | 节标题 |
| subsection_title | TEXT | 子节标题 |
| work_content | TEXT | 工程内容描述 |
| unit | TEXT | 计量单位 |
| page | INTEGER | 页码 |
| seq_on_page | INTEGER | 页内序号 |
| header_json | TEXT NOT NULL | JSON: 属性维度 + 费用项目 |
| row_count | INTEGER | 行数 |
| col_count | INTEGER | 列数 |

### norms_item — 定额条目（1D 长格式）
| 列 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| table_id | INTEGER FK | 所属表 |
| page | INTEGER | 页码 |
| norms_code | TEXT NOT NULL | 定额编号（5位） |
| sort_order | INTEGER | 排序 |
| attr_level1~4 | TEXT | 属性值（最多4级） |
| attr1_label~4_label | TEXT | 属性名 |
| cost_item | TEXT NOT NULL | 费用项目名称 |
| cost_item_unit | TEXT | 费用项目单位 |
| amount | REAL | 数值（NULL=不适用） |
| ocr_source | TEXT | 来源标记 |
| data_quality | TEXT | 数据质量标记 |

### page_index — 页面索引（中枢表）
| 列 | 类型 | 说明 |
|------|------|------|
| page | INTEGER PK | 页码 |
| page_type | TEXT NOT NULL | 页面类型 |
| chapter_id | INTEGER FK | 所属章节 |
| table_id | INTEGER FK | 所属表 |
| appendix_id | INTEGER FK | 所属附录 |
| text_preview | TEXT | 文本预览 |
| ocr_status | TEXT | 处理状态 |
| ocr_lines | INTEGER | OCR行数 |
| ocr_confidence | REAL | OCR置信度 |

## 辅助表

### appendix_table — 附录表
### appendix_row — 附录行
### ocr_block — OCR原始块

## 索引

- `idx_norms_code` ON norms_item(norms_code)
- `idx_norms_table` ON norms_item(table_id)
- `idx_page_type` ON page_index(page_type)
- `idx_ocr_page` ON ocr_block(page)

## 入库顺序

```
document → chapter → page_index → section_text / norms_table → norms_item
```

（必须按照外键依赖顺序写入）
