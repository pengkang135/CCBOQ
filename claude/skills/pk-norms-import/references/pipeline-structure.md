# 结构层详细流程 (Phase 1)

结构层与 PDF 类型无关，是两种路径的共用基础。

## 输入

- PDF 文件路径
- （可选）已知的章节页码范围

## 输出

`output/structure.json`：

```json
{
  "document": {
    "title": "沿海港口水工建筑工程定额",
    "doc_number": "JTS/T 276-1-2019",
    "total_pages": 914
  },
  "page_map": {
    "1": {"type": "cover", "pdf_page": 1},
    "44": {
      "type": "quota_table",
      "pdf_page": 44,
      "internal_page": 19,
      "chapter": "第一章 土石方工程",
      "section": "第一节 陆上开挖工程",
      "subsection": "一、一般土方"
    },
    "198": {"type": "blank", "pdf_page": 198}
  },
  "chapters": [
    {
      "id": 1, "level": 1,
      "title": "第一章 土石方工程",
      "internal_start": 5, "internal_end": 173,
      "pdf_start": 30, "pdf_end": 198,
      "children": [
        {
          "id": 2, "level": 2,
          "title": "第一节 陆上开挖工程",
          "internal_start": 18, "internal_end": 78,
          "pdf_start": 43, "pdf_end": 104,
          "children": [
            {
              "id": 3, "level": 3,
              "title": "一、一般土方",
              "codes": ["10001-10048"],
              "pdf_start": 43, "pdf_end": 51
            }
          ]
        }
      ]
    }
  ]
}
```

## Step 1.1: 目录解析

目录页通常在前 20 页内，是全书结构的权威来源。

### 解析策略

1. 从 page_type=toc 的页面提取文本
2. 解析目录行格式：
   ```
   第一章 土石方工程 .............................................. (5)
     说明 ......................................................... (7)
     第一节 陆上开挖工程 ......................................... (18)
       一、一般土方 .............................................. (18)
   ```
3. 从缩进量判断层级：
   - 无缩进，"第X章" → level 1
   - 1 级缩进，"第X节" → level 2
   - 2 级缩进，"一、二、三..." → level 3
   - 3 级缩进，"1. 2. 3..." → level 4（具体定额项）

### 提取正则

```python
CHAPTER_RE = re.compile(r'^第([一二三四五六七八九十]+)章\s+(.+?)\s+\.+\s+\((\d+)\)')
SECTION_RE = re.compile(r'^第([一二三四五六七八九十]+)节\s+(.+?)\s+\.+\s+\((\d+)\)')
SUBSECTION_RE = re.compile(r'^([一二三四五六七八九十]+)、(.+?)\s+\.+\s+\((\d+)\)')
ITEM_RE = re.compile(r'^(\d+)\.\s+(.+?)\s+\.+\s+\((\d+)\)')
```

### chinese_to_int 辅助函数

```python
CN_NUM = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
def chinese_to_int(s):
    if s in CN_NUM:
        return CN_NUM[s]
    if s.startswith('十'):
        return 10 + (CN_NUM.get(s[1], 0) if len(s) > 1 else 0)
    if '十' in s:
        a, b = s.split('十')
        return CN_NUM[a] * 10 + (CN_NUM.get(b, 0) if b else 0)
    return 0
```

## Step 1.2: 页码映射

书页脚有 `- N -` 格式的内部页码（N 是原书页码，非 PDF 页码）。

```python
FOOTER_RE = re.compile(r'^\s*-\s*(\d{1,3})\s*-\s*$')
```

对每页的底部行（y > page_height * 0.9）匹配此模式，建立 `internal_page → pdf_page` 映射。

## Step 1.3: 页面分类

对每一页，按优先级依次判定：

```python
def classify_page(lines, page_num):
    full_text = "".join(l["text"] for l in lines)
    text_count = len([l for l in lines if l["text"].strip()])

    if text_count < 5:
        return "blank"

    if page_num <= 3 and ("行业标准" in full_text or "主编单位" in full_text):
        return "cover"

    if "公告" in full_text and "第" in full_text and "号" in full_text:
        return "notice"

    if full_text.count("第") >= 5 and "......" in full_text.replace(" ", ""):
        return "toc"

    if "总说明" in full_text and not has_quota_codes(lines):
        return "general_instruction"

    if re.search(r'^第[一二三四五六七八九十]+章', full_text) and text_count < 15:
        return "chapter_title"

    if "续表" in full_text or "续前表" in full_text:
        return "continued_table"

    if "附加说明" in full_text or "附录" in full_text:
        return "appendix"

    if has_quota_codes(lines):
        return "quota_table"

    if re.search(r'第[一二三四五六七八九十]+节', full_text) or "说明" in full_text:
        return "section_intro"

    return "general_instruction"  # fallback
```

### 定额编号检测

```python
def has_quota_codes(lines):
    codes = [l["text"].strip() for l in lines if re.match(r'^\d{5}$', l["text"].strip())]
    return len(codes) >= 3
```

## Step 1.4: 章节归属

对每页根据其 internal_page 匹配到目录树中的章节。

```python
def assign_chapter(internal_page, chapter_tree):
    for ch in chapter_tree:
        if ch["internal_start"] <= internal_page <= ch["internal_end"]:
            for sec in ch.get("children", []):
                if sec["internal_start"] <= internal_page <= sec["internal_end"]:
                    for sub in sec.get("children", []):
                        if sub.get("pdf_start", 0) <= internal_page <= sub.get("pdf_end", 9999):
                            return ch["title"], sec["title"], sub["title"]
                    return ch["title"], sec["title"], None
            return ch["title"], None, None
    return None, None, None
```

## 验证

1. page_map 总数 = PDF 总页数
2. 每页 internal_page 递增（跳过空白页）
3. 目录树的最大 internal_page 不超过 PDF 最大 internal_page
4. 至少检测到与目录页声明一致的章数
