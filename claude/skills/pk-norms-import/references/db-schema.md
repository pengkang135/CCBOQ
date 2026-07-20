# 数据库 Schema 参考

## ER 关系

```
document (1)
  │
chapter (N) ── parent_id (自引用, 4级层级)
  │
  ├── page_index (N) ── 每页索引, 关联 chapter
  │     │
  │     ├── section_text (N) ── 文字页内容
  │     │
  │     └── quota_table (N) ── 定额表元数据
  │           │
  │           └── quota_item (N) ── 定额条目
  │
  └── section_text (N) ── 章/节说明 (可选关联 chapter)
```

## 表定义

### document

```sql
CREATE TABLE document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,          -- 书名
    doc_number TEXT,              -- 标准号, 如 "JTS/T 276-1-2019"
    publisher TEXT,               -- 出版社
    publish_year INTEGER,         -- 出版年份
    total_pages INTEGER,          -- 总页数
    pdf_path TEXT,                -- 源 PDF 路径
    pdf_type TEXT,                -- "text" | "image" | "mixed"
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### chapter

```sql
CREATE TABLE chapter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,          -- 章/节/分项名
    level INTEGER NOT NULL,       -- 1=章, 2=节, 3=分项, 4=子项
    parent_id INTEGER,            -- 父章节 ID (自引用)
    sort_order INTEGER,           -- 同级排序
    start_page INTEGER,           -- 起始内部页码
    end_page INTEGER,             -- 结束内部页码
    pdf_start INTEGER,            -- 起始 PDF 页码
    pdf_end INTEGER,              -- 结束 PDF 页码
    code_range TEXT,              -- 定额编号范围, 如 "10001-10048"
    FOREIGN KEY (parent_id) REFERENCES chapter(id)
);
```

层级示例：
```
id=1  level=1  title="第一章 土石方工程"         parent_id=NULL
id=2  level=2  title="第一节 陆上开挖工程"        parent_id=1
id=3  level=3  title="一、一般土方"               parent_id=2
```

对于无节的章（如第5、6章），分项直接挂在章下（level=3, parent_id=章ID）。

### page_index

中枢表，每页一条记录：

```sql
CREATE TABLE page_index (
    page INTEGER PRIMARY KEY,     -- PDF 页码 (1-based)
    internal_page INTEGER,        -- 原书内部页码 (页脚 - N -)
    page_type TEXT NOT NULL,      -- cover|blank|notice|toc|general_instruction|
                                  -- chapter_title|section_intro|quota_table|
                                  -- continued_table|appendix
    chapter_id INTEGER,           -- 关联 chapter.id
    table_id INTEGER,             -- 关联 quota_table.id (仅 quota_table/continued_table)
    text_preview TEXT,            -- 页面文字前 100 字符
    ocr_status TEXT,              -- "extracted" | "pending" | "failed"
    FOREIGN KEY (chapter_id) REFERENCES chapter(id),
    FOREIGN KEY (table_id) REFERENCES quota_table(id)
);
```

### section_text

```sql
CREATE TABLE section_text (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER,           -- 可选, 关联所属章节
    page INTEGER NOT NULL,        -- PDF 页码
    type TEXT NOT NULL,           -- notice|toc|general_instruction|
                                  -- chapter_title|section_intro|appendix
    title TEXT,                   -- 标题
    content TEXT,                 -- 正文 (Markdown 格式)
    FOREIGN KEY (chapter_id) REFERENCES chapter(id)
);
```

### quota_table

```sql
CREATE TABLE quota_table (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER,           -- 所属 chapter (通常 level 3 分项)
    section_title TEXT,           -- 节名
    subsection_title TEXT,        -- 分项标题
    work_content TEXT,            -- 工程内容
    unit TEXT,                    -- 表的整体计量单位
    page INTEGER NOT NULL,        -- 首页 PDF 页码
    header_json TEXT,             -- JSON: attr_dimensions + cost_items 定义
    row_count INTEGER,            -- 定额编号列数
    col_count INTEGER,            -- 费用项目行数
    continued_from INTEGER,       -- 续表: 首页的 quota_table.id
    source TEXT,                  -- "pymupdf_text" | "rapidocr" | "ai_vision"
    FOREIGN KEY (chapter_id) REFERENCES chapter(id)
);
```

header_json 格式：
```json
{
  "attr_dimensions": [
    {"name": "土壤类别", "values": ["Ⅰ～Ⅱ", "Ⅲ～Ⅳ", "Ⅰ～Ⅱ", "Ⅲ～Ⅳ"]},
    {"name": "开挖类型", "values": ["地槽", "地槽", "地坑", "地坑"]},
    {"name": "支护方式", "values": ["无挡土板", "无挡土板", "有挡土板", "有挡土板"]}
  ],
  "cost_items": [
    {"name": "人工", "unit": "工日", "code": "192000010001"},
    {"name": "板枋材", "unit": "m³", "code": "190503002020"}
  ]
}
```

### quota_item

```sql
CREATE TABLE quota_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER NOT NULL,    -- 所属 quota_table
    page INTEGER NOT NULL,        -- PDF 页码
    quota_code TEXT NOT NULL,     -- 定额编号, 如 "10018"
    sort_order INTEGER,           -- 排序

    -- 属性维度 (最多4个, 超过4个时完整信息在 quota_table.header_json)
    attr_level1 TEXT,             -- 属性值1
    attr_level2 TEXT,             -- 属性值2
    attr_level3 TEXT,             -- 属性值3
    attr_level4 TEXT,             -- 属性值4
    attr1_label TEXT,             -- 属性名1
    attr2_label TEXT,             -- 属性名2
    attr3_label TEXT,             -- 属性名3
    attr4_label TEXT,             -- 属性名4

    -- 费用项目
    cost_item TEXT NOT NULL,      -- 费用项目名 (人工/板枋材/基价...)
    cost_item_unit TEXT,          -- 费用项目单位 (工日/m³/元...)
    code TEXT,                    -- 费用项目代码 (10+位数字)
    amount REAL,                  -- 数量 (NULL 表示不适用)

    -- 元数据
    ocr_source TEXT,              -- "pymupdf_text" | "rapidocr" | "ai_vision"
    data_quality TEXT,            -- "ai_extracted" | "manual_verified" | "rule_extracted"

    FOREIGN KEY (table_id) REFERENCES quota_table(id)
);

CREATE INDEX idx_quota_item_code ON quota_item(quota_code);
CREATE INDEX idx_quota_item_cost ON quota_item(cost_item);
CREATE INDEX idx_quota_item_table ON quota_item(table_id);
CREATE INDEX idx_quota_item_page ON quota_item(page);
```

## 入库顺序

外键依赖关系决定了入库必须按以下顺序：

```
1. document       (无依赖)
2. chapter        (自引用 parent_id, 需先插父后插子)
3. page_index     (依赖 chapter, quota_table)
   ├── 先插非表格页 (无 quota_table 依赖)
   └── 再插定额表页
4. section_text   (可选关联 chapter_id)
5. quota_table    (依赖 chapter_id)
6. quota_item     (依赖 quota_table.id)
```

实现：

```python
def load_all(structure, extracted_dir, db_path):
    conn = sqlite3.connect(db_path)

    # 1. document
    insert_document(conn, structure["document"])

    # 2. chapter (按层级顺序: level 1 → 2 → 3 → 4)
    for ch in walk_chapters_bfs(structure["chapters"]):
        insert_chapter(conn, ch)

    # 3-5. 按 page_map 顺序处理每页
    for page_str, info in sorted(structure["page_map"].items(),
                                  key=lambda x: int(x[0])):
        if info["type"] in ("quota_table", "continued_table"):
            table_id = insert_quota_table(conn, info)
            insert_quota_items(conn, table_id, extracted_dir, int(page_str))
        elif info["type"] not in ("cover", "blank"):
            insert_section_text(conn, info)
        insert_page_index(conn, int(page_str), info)

    conn.commit()
    conn.close()
```

## 查询示例

### 按章节浏览定额条目

```sql
SELECT qi.quota_code, qi.attr_level1, qi.attr_level2,
       qi.cost_item, qi.amount
FROM quota_item qi
JOIN quota_table qt ON qt.id = qi.table_id
JOIN chapter c ON c.id = qt.chapter_id
WHERE c.title = '一、一般土方'
ORDER BY qi.quota_code, qi.sort_order;
```

### 按定额编号查询所有属性组合

```sql
SELECT DISTINCT quota_code, attr_level1, attr_level2, attr_level3
FROM quota_item
WHERE quota_code = '10018';
```

### 统计各章定额条目数

```sql
SELECT c1.title, COUNT(*) as item_count
FROM quota_item qi
JOIN quota_table qt ON qt.id = qi.table_id
JOIN chapter c ON c.id = qt.chapter_id
JOIN chapter c1 ON c1.id = COALESCE(
    (SELECT id FROM chapter WHERE id = c.parent_id AND level = 1),
    (SELECT id FROM chapter WHERE id = (SELECT parent_id FROM chapter WHERE id = c.parent_id) AND level = 1)
)
WHERE c1.level = 1
GROUP BY c1.title
ORDER BY c1.sort_order;
```

### 质量检查：零属性页面

```sql
SELECT qt.page, qt.subsection_title
FROM quota_table qt
WHERE (SELECT COUNT(DISTINCT attr1_label) FROM quota_item WHERE table_id = qt.id AND attr1_label != '') = 0
ORDER BY qt.page;
```
