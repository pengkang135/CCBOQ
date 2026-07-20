# Path A: 文本型 PDF 内容提取详细流程

适用于有文本层的 PDF（如 JTS/T 276-1-2019）。

## 数据流

```
PDF
 │
 ├── A1: PyMuPDF 全量文本提取
 │   extract_text_all.py
 │   → output/text/page_0001.json ~ page_0914.json
 │
 ├── A2: 坐标聚类 + 列对齐
 │   cluster_columns.py
 │   → output/clustered/page_XXXX.json
 │
 └── A3: AI 语义理解
     ai_extract_page.py
     → output/extracted/page_XXXX.json
```

## A1: PyMuPDF 文本+坐标提取

### 实现

```python
import fitz

def extract_page(doc, pg):
    page = doc[pg]
    blocks = page.get_text("dict")["blocks"]
    lines = []
    for block in blocks:
        if block["type"] != 0:  # skip images
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if text:
                    lines.append({
                        "text": text,
                        "x": round(span["bbox"][0], 1),
                        "y": round(span["bbox"][1], 1),
                    })
    return {
        "page": pg + 1,  # 1-based
        "source": "pymupdf_text",
        "lines": lines
    }
```

### 关键参数

- 坐标精度保留 0.1px
- 过滤图片 block（type != 0）
- span bbox 使用左上角 (x0, y0) 作为定位点

## A2: 坐标聚类 + 列对齐

这是**纯确定性算法**，不需要 AI。目标是将文本块组织为"每列的表头文本序列 + 每行的数据值列映射"。

### 算法步骤

#### 1. 行分组

按 y 坐标（tolerance ±5）将文本块分组为行：

```python
def group_by_y(lines, tolerance=5):
    groups = []
    for line in sorted(lines, key=lambda l: (l["y"], l["x"])):
        placed = False
        for grp in groups:
            if abs(grp[0]["y"] - line["y"]) <= tolerance:
                grp.append(line)
                placed = True
                break
        if not placed:
            groups.append([line])
    for grp in groups:
        grp.sort(key=lambda l: l["x"])
    groups.sort(key=lambda g: g[0]["y"])
    return groups
```

#### 2. 页面元数据提取

从顶部行（前 5 行）提取：

```python
def extract_page_meta(groups):
    subsection = ""
    work_content = ""
    unit = ""
    for grp in groups[:5]:
        text = "".join(l["text"].strip() for l in grp)
        if re.match(r'^[一二三四五六七八九十]+、', text):
            subsection = text
        elif "工程内容" in text or "工作内容" in text:
            work_content = text.replace("工程内容：", "").replace("工作内容：", "")
        elif re.match(r'^\d+\.?\d*\s*(m|㎡|m²|m³|km|t|kg|元)', text):
            unit = text
    return subsection, work_content, unit
```

#### 3. 定额编号列检测

找到包含"定额编号"文本的行，行中所有 5 位数字即为定额编号列：

```python
def find_code_columns(groups):
    for grp in groups:
        if any("定额编号" in l["text"] for l in grp):
            codes = []
            for l in grp:
                t = l["text"].strip()
                if re.match(r'^\d{5}$', t):
                    codes.append({"code": t, "x": l["x"]})
            return sorted(codes, key=lambda c: c["x"])
    return []
```

#### 4. 表头列内文本收集

在表头区域（定额编号行以上的行）中，将每个文本块按其 x 坐标分配到最近的列：

```python
def collect_header_texts(groups, code_columns, header_start_idx):
    header_texts = {c["code"]: [] for c in code_columns}

    # 计算列边界：相邻 code x 的中点
    col_boundaries = []
    for i in range(len(code_columns) - 1):
        mid = (code_columns[i]["x"] + code_columns[i+1]["x"]) / 2
        col_boundaries.append(mid)

    for grp in groups[:header_start_idx]:
        for l in grp:
            t = l["text"].strip()
            if not t or re.match(r'^\d{5}$', t) or t == "定额编号":
                continue
            # 找到最近的列
            for j, c in enumerate(code_columns):
                left = col_boundaries[j-1] if j > 0 else 0
                right = col_boundaries[j] if j < len(col_boundaries) else 9999
                if left <= l["x"] <= right:
                    header_texts[c["code"]].append({
                        "text": t,
                        "y": l["y"]
                    })
                    break

    # 每列内按 y 排序
    for code in header_texts:
        header_texts[code].sort(key=lambda h: h["y"])

    return header_texts
```

#### 5. 数据行识别

以数字序号（1, 2, 3...）开头的行是数据行。

费用项目的识别：
- texts[0] = 序号
- texts[1] = 费用项目名（人工、板枋材、基价等）
- texts 中匹配单位关键词（工日、m³、元、%、台班等）
- texts 中匹配 10 位以上数字 = 代码
- 其余数字 = 各列的数值（按 x 坐标匹配到列）

```python
def parse_data_rows(groups, code_columns, data_start_idx):
    data_rows = []
    for i in range(data_start_idx, len(groups)):
        grp = groups[i]
        texts = [l["text"].strip() for l in grp]
        if not texts or not re.match(r'^\d+$', texts[0]):
            continue

        name = texts[1] if len(texts) > 1 else ""
        unit = ""
        code = ""

        for l in grp:
            t = l["text"].strip()
            if t in ("工日", "m³", "元", "%", "kg", "t", "m²", "㎡",
                      "km", "m", "个", "套", "艘", "台", "台班", "班", "艘班", "组日"):
                unit = t
            elif re.match(r'^\d{10,}$', t):
                code = t

        # 数值匹配到列
        values = {}
        for l in grp:
            t = l["text"].strip()
            if t in ("－", "—"):
                val = None
            elif re.match(r'^-?\d+\.?\d*$', t):
                val = float(t)
            else:
                continue

            # 找到最近的 code 列
            best_code = None
            best_dist = 999
            for c in code_columns:
                dist = abs(l["x"] - c["x"])
                if dist < best_dist and dist < 100:
                    best_dist = dist
                    best_code = c["code"]
            if best_code:
                values[best_code] = val

        data_rows.append({
            "seq": int(texts[0]),
            "name": name,
            "unit": unit,
            "code": code,
            "values": values
        })

    return data_rows
```

#### 6. 续表检测

```python
def is_continued(groups):
    first_texts = "".join(l["text"] for l in groups[0])
    return "续表" in first_texts or "续前表" in first_texts
```

### A2 输出格式

```json
{
  "page": 47,
  "subsection": "四、人力挖地槽、地坑土方",
  "work_content": "挖土，修整边坡及底面，制作、安装及拆除挡土板，原土夯实。",
  "unit": "100m³",
  "is_continued": false,
  "code_columns": [
    {
      "code": "10018",
      "x": 313.4,
      "header_texts": [
        {"text": "地槽", "y": 97.4},
        {"text": "无挡土板", "y": 111.6},
        {"text": "土壤类别", "y": 125.6},
        {"text": "Ⅰ～Ⅱ", "y": 139.8}
      ]
    }
  ],
  "data_rows": [
    {
      "seq": 1,
      "name": "人工",
      "unit": "工日",
      "code": "192000010001",
      "values": {"10018": 10.37, "10019": 21.38, "10020": 12.96, "10021": 26.57}
    }
  ]
}
```

## A3: AI 语义理解

输入 A2 的 clustered JSON，调用 LLM API 输出 1D 结构化数据。

### 输入/输出

- 输入：`output/clustered/page_XXXX.json`
- 输出：`output/extracted/page_XXXX.json`（符合 DB 入库格式）

### 输出格式

```json
{
  "page": 47,
  "page_type": "quota_table",
  "subsection": "四、人力挖地槽、地坑土方",
  "work_content": "挖土，修整边坡及底面，制作、安装及拆除挡土板，原土夯实。",
  "unit": "100m³",
  "attr_dimensions": [
    {"name": "土壤类别", "values": ["Ⅰ～Ⅱ", "Ⅲ～Ⅳ", "Ⅰ～Ⅱ", "Ⅲ～Ⅳ"]},
    {"name": "开挖类型", "values": ["地槽", "地槽", "地坑", "地坑"]},
    {"name": "支护方式", "values": ["无挡土板", "无挡土板", "有挡土板", "有挡土板"]}
  ],
  "cost_items": [
    {"name": "人工", "unit": "工日", "code": "192000010001"},
    {"name": "板枋材", "unit": "m³", "code": "190503002020"},
    {"name": "基价", "unit": "元", "code": ""}
  ],
  "items": [
    {
      "quota_code": "10018",
      "attr_土壤类别": "Ⅰ～Ⅱ",
      "attr_开挖类型": "地槽",
      "attr_支护方式": "无挡土板",
      "人工": 10.37,
      "板枋材": null,
      "基价": 1023.50
    }
  ]
}
```

### API 调用逻辑

```python
def ai_extract_page(clustered_data, prev_result=None, model="claude-sonnet-4-6"):
    if clustered_data["is_continued"] and prev_result:
        prompt = build_continued_prompt(clustered_data, prev_result)
    else:
        prompt = build_full_prompt(clustered_data)

    response = call_claude_api(prompt, model=model)
    result = json.loads(response)

    # 验证
    n_codes = len(clustered_data["code_columns"])
    n_ci = len(result["cost_items"])
    expected_items = n_codes * n_ci
    if len(result["items"]) != expected_items:
        # 重试
        prompt = build_retry_prompt(clustered_data, result, expected_items)
        response = call_claude_api(prompt, model=model)
        result = json.loads(response)

    return result
```

Prompt 模板见 [ai-prompt.md](ai-prompt.md)

## 续表处理

续表链的逻辑：

```python
def process_chapter_sequentially(pages, model):
    prev_result = None
    results = {}
    for pg in pages:
        clustered = load_clustered(pg)
        if not clustered["code_columns"]:
            prev_result = None
            continue

        result = ai_extract_page(clustered, prev_result, model)

        if result["page_type"] == "quota_table":
            prev_result = result  # 非续表才传递

        results[pg] = result
    return results
```

续表页的 AI prompt 只包含数据行，不需要重复解析表头。

## 并行注意事项

如果使用按章并行策略，每章内的页面串行处理（处理续表链），章间独立并行。
