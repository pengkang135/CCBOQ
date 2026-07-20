# AI Prompt 模板

## 设计原则

1. AI 只负责语义理解，不负责坐标运算
2. 输入必须是按列组织好的结构化文本，不是原始坐标
3. 输出必须是严格的 JSON，字段完整
4. 需要处理同名费用项目、跨列标题、融合标签等边界情况

## 完整页 Prompt

用于 quota_table 类型页。

```
你是一个工程造价定额数据的结构化提取器。

给你一页定额表的列对齐数据。每列的 header_texts 是从上到下的表头文本序列，
数据行中 values 是每列对应的数值（null 表示"—"或空白）。

请输出这个页面的完整 1D 结构化数据。只输出 JSON，不要解释。

## 输入说明

- code_columns: 每列包含定额编号和其上方表头的文本序列
- data_rows: 每行费用项目的名称/单位/代码和各列数值
- 已经知道 page、subsection、work_content、unit 等元数据

## 你需要做的事

1. 分析每列 header_texts 的文本序列，推断属性维度
   - 跨列相同的文本通常是属性名标签（如"土壤类别"在每列都出现）
   - 列间取值不同的文本是属性值（如列1="地槽"、列3="地坑"）
   - 同一 y 层级的文本属于同一属性维度
   - 融合标签（如"斗容2.0m³"）需拆分为属性名+属性值

2. 构建 attr_dimensions 数组，每个元素包含 name 和 values（与 code_columns 顺序对应）

3. 处理同名费用项目（如"其他材料"出现两次且单位不同）
   - cost_items 中分别列出
   - items 中费用项目名改为"其他材料(元)"和"其他材料(%)"

4. 展开为 items：每个定额编号 × 每行费用项目 = 一条记录

## 输出格式

{
  "page_type": "quota_table",
  "subsection": "<分项标题>",
  "work_content": "<工程内容>",
  "unit": "<计量单位>",
  "attr_dimensions": [
    {"name": "<属性名>", "values": ["<列1值>", "<列2值>", ...]}
  ],
  "cost_items": [
    {"name": "<费用项目名>", "unit": "<单位>", "code": "<代码>"}
  ],
  "items": [
    {
      "quota_code": "<定额编号>",
      "attr_<属性名1>": "<值>",
      "attr_<属性名2>": "<值>",
      "<费用项目名>": <数值或null>
    }
  ]
}

## 关键规则

1. 属性不遗漏：header_texts 中除"定额编号"外的每个层级分类都要提取为独立属性维度
2. 属性名用中文：从表头文本推断，如"地槽/地坑"→"开挖类型"
3. 每个定额编号 × 每行费用项目 = 一条 items 记录
4. null ≠ 0：表格中的"—"、"－"、空白输出 null
5. unit 是整表的计量单位，不是费用项目单位
6. 只输出 JSON

## 输入数据

{clustered_json}
```

## 续表 Prompt

```
你是一个工程造价定额数据的结构化提取器。

这是一个**续前表**页面。以下是前页的提取结果（含 attr_dimensions 和 cost_items 定义）：

{prev_result_json}

以下是本页的列对齐数据。本页只有数据行，表头结构继承自前页。

{clustered_json}

请提取本页的 items，沿用前页的 attr_dimensions 和 cost_items 定义。
只输出 JSON，不要解释。

## 输出格式

{
  "page_type": "continued_table",
  "items": [
    {
      "quota_code": "<定额编号>",
      "attr_<属性名1>": "<值>",
      ...
      "<费用项目名>": <数值或null>
    }
  ]
}
```

## 常见失败模式与重试策略

| 失败模式 | 检测方法 | 重试 prompt 补充 |
|----------|---------|-----------------|
| 遗漏属性维度 | attr_dimensions 为空或只有1个 | "表格有多个属性维度，请仔细检查表头文本序列中的每个y层级" |
| 属性名不合适 | 属性名与原文字面值相同 | "属性名应该是对该维度的描述，不应该是原文字面值" |
| items≠codes×cost | len(items) != n_codes * n_ci | "预期 {n} 条记录，当前只有 {m} 条，请补全所有定额编号×费用项目的组合" |
| 同名费用项目未区分 | cost_items 中有重名 | "同名费用项目应按单位区分，如'其他材料(元)'和'其他材料(%)'" |
| JSON 解析失败 | json.loads 异常 | 重试，prompt 开头加 "你上次的输出不是合法 JSON。请严格按格式输出。" |

重试逻辑：

```python
def extract_with_retry(prompt, max_retries=2):
    for attempt in range(max_retries + 1):
        response = call_claude_api(prompt)
        try:
            result = json.loads(response)
            errors = validate_result(result, expected_n_items)
            if not errors:
                return result
            prompt = build_retry_prompt(prompt, result, errors)
        except json.JSONDecodeError:
            prompt = "你上次的输出不是合法 JSON。请严格按格式输出。\n\n" + prompt
    return None  # 标记为需人工复核
```
