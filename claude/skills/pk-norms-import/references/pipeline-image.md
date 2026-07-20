# Path B: 图片型 PDF 内容提取详细流程

适用于扫描版 PDF（无文本层），如 2004 版定额。

## 数据流

```
PDF
 │
 ├── B1: PDF 渲染 + RapidOCR 多 pass 识别
 │   ocr_all.py
 │   → output/ocr/page_0001.json ~ page_NNNN.json
 │
 └── B2: OCR 文本 + 坐标 → 结构化 MD
     text_to_md.py
     → output/md/page_XXXX.md
```

## B1: OCR 提取

### OCR 引擎：RapidOCR (ONNX)

```python
from rapidocr_onnxruntime import RapidOCR

engine = RapidOCR()

def ocr_page(image):
    result, _ = engine(image)
    # result: [[bbox, text, confidence], ...]
    # bbox: [[x0,y0], [x1,y1], [x2,y2], [x3,y3]]
    return result
```

### 多 Pass 策略

| Pass | 参数 | 目的 |
|------|------|------|
| base | 2x 缩放 | 正常文本 |
| hires | 3x 缩放 | 小字/表格 |
| contrast | 2x + 对比度 1.5 | 浅色/模糊文本 |

三个 pass 的结果通过 IoU 去重合并。

```python
def ocr_page_multi_pass(image):
    all_results = []

    # Pass 1: base
    img_2x = scale_image(image, 2.0)
    r1 = engine(img_2x)[0]
    all_results.extend(normalize_bbox(r1, 2.0))

    # Pass 2: hires
    img_3x = scale_image(image, 3.0)
    r2 = engine(img_3x)[0]
    all_results.extend(normalize_bbox(r2, 3.0))

    # Pass 3: contrast
    img_ct = adjust_contrast(scale_image(image, 2.0), 1.5)
    r3 = engine(img_ct)[0]
    all_results.extend(normalize_bbox(r3, 2.0))

    # IoU 去重：保留置信度最高的
    merged = iou_deduplicate(all_results, iou_threshold=0.6)
    return merged
```

### 输出格式

```json
{
  "page": 42,
  "source": "rapidocr",
  "width": 2480,
  "height": 3508,
  "lines": [
    {"text": "四、人力挖地槽", "x": 213, "y": 125, "confidence": 0.95},
    {"text": "定额编号", "x": 151, "y": 385, "confidence": 0.92}
  ]
}
```

坐标归一化到 PDF 磅 (point) 坐标系。

## B2: OCR 文本 → 结构化 MD

### 挑战

与文本型 PDF 不同，OCR 输出的坐标精度和文本一致性较差：
- 同一行文字可能被 OCR 识别为不同行（y 坐标波动大）
- 表格线可能在 OCR 结果中产生噪点文本（`│`、`─`）
- 数字和小数点的识别不完整

### 策略：先粗定位再精细解析

#### 1. 表格区域检测

利用表格线检测（如果有）或文本密度分析来定位表格边界。

```python
def detect_table_regions(lines):
    # 检测连续数字/小数点密度高的区域
    y_groups = group_by_y(lines, tolerance=10)
    table_rows = []
    for grp in y_groups:
        numeric_count = sum(1 for l in grp if re.match(r'^[\d.]+$', l["text"]))
        if numeric_count >= 3:
            table_rows.append(grp)
    return table_rows
```

#### 2. 降级到文本型 Path A 流程

OCR 后有坐标的文本块，可以复用 Path A 的 A2（坐标聚类）和 A3（AI 语义理解）逻辑，但需要调整参数：

- y 行分组 tolerance 从 5 增加到 10
- 定额编号检测增加模糊匹配（允许 OCR 将 10018 识别为 "10018" 或 "1 0 0 1 8"）
- AI prompt 中增加 OCR 噪声容忍说明

#### 3. 备选：纯 AI 方案

当 OCR 坐标质量太差时，可以将页面渲染为图片，直接传给多模态 LLM：

```python
def extract_with_vision_ai(image, prev_context=None):
    # 将页面图片编码为 base64
    img_b64 = base64.b64encode(image_to_bytes(image)).decode()

    response = call_claude_api(
        system="你是工程造价定额数据提取器...",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "data": img_b64}},
                {"type": "text", "text": build_vision_prompt(prev_context)}
            ]
        }],
        model="claude-sonnet-4-6"
    )
    return json.loads(response)
```

此方案每页约 2000-5000 token 图片 + 1000 token 文本输入，费用约为文本方案的 3-5 倍。

## MD 输出格式

与文本型 PDF 输出统一：

```markdown
---
page: 80
pdf_page: 80
internal_page: 55
type: quota_table
chapter: "第一章 土石方工程"
section: "第一节 陆上开挖工程"
subsection: "一般土方"
source: rapidocr
record_count: 54
continued_from: null
---

| 定额编号 | 土壤类别 | 开挖类型 | 支护方式 | 费用项目 | 单位 | 代码 | 数量 |
|----------|---------|---------|---------|---------|------|------|------|
| 10018 | Ⅰ～Ⅱ | 地槽 | 无挡土板 | 人工 | 工日 | 192000010001 | 10.37 |
| 10018 | Ⅰ～Ⅱ | 地槽 | 无挡土板 | 板枋材 | m³ | 190503002020 | |
| ... | | | | | | | |
```

## 入库

图片型 PDF 的 MD 与文本型 PDF 的 MD 格式完全一致，使用同一个入库脚本 `load_all_to_sqlite.py`，按 frontmatter 的 `source` 字段区分数据来源。
