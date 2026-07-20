#!/usr/bin/env python3
"""Phase A3: AI semantic extraction via LLM API.
Reads clustered JSON, calls Claude API to understand table header semantics,
outputs 1D structured data.

Usage:
  python ai_extract_page.py --clustered-dir output/clustered/ --output output/extracted/
  python ai_extract_page.py --clustered-dir output/clustered/ --output output/extracted/ --pages 44-100
  python ai_extract_page.py --clustered-dir output/clustered/ --output output/extracted/ --model claude-sonnet-4-6
"""

import json, sys, re, os, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def build_full_prompt(clustered):
    """Build prompt for a full quota_table page."""
    return f"""你是一个工程造价定额数据的结构化提取器。

给你一页定额表的列对齐数据。每列的 header_texts 是从上到下的表头文本序列，
数据行中 values 是每列对应的数值（null 表示"—"或空白）。

请输出这个页面的完整 1D 结构化数据。只输出 JSON，不要解释。

## 你需要做的事

1. 分析每列 header_texts 的文本序列，推断属性维度
   - 跨列相同的文本通常是属性名标签
   - 列间取值不同的文本是属性值
   - 同一 y 层级的文本属于同一属性维度
   - 融合标签（如"斗容2.0m³"）需拆分为属性名+属性值

2. 构建 attr_dimensions 数组，每个元素包含 name 和 values（与 code_columns 顺序对应）

3. 处理同名费用项目（如"其他材料"出现两次且单位不同）
   - cost_items 中分别列出
   - items 中费用项目名改为"其他材料(元)"和"其他材料(%)"

4. 展开为 items：每个定额编号 x 每行费用项目 = 一条记录

## 输出格式

{{
  "page_type": "quota_table",
  "subsection": "{clustered.get('subsection', '')}",
  "work_content": "{clustered.get('work_content', '')}",
  "unit": "{clustered.get('unit', '')}",
  "attr_dimensions": [
    {{"name": "<属性名>", "values": ["<列1值>", "<列2值>", ...]}}
  ],
  "cost_items": [
    {{"name": "<费用项目名>", "unit": "<单位>", "code": "<代码>"}}
  ],
  "items": [
    {{
      "quota_code": "<定额编号>",
      "attr_<属性名1>": "<值>",
      "<费用项目名>": <数值或null>
    }}
  ]
}}

## 关键规则

1. 属性不遗漏：header_texts 中除"定额编号"外的每个层级分类都要提取为独立属性维度
2. 属性名用中文：从表头文本推断，如"地槽/地坑"→"开挖类型"
3. 每个定额编号 x 每行费用项目 = 一条 items 记录
4. null != 0：表格中的"—"、"－"、空白输出 null
5. unit 是整表的计量单位，不是费用项目单位
6. 只输出 JSON

## 输入数据

{json.dumps(clustered, ensure_ascii=False, indent=2)}
"""


def build_continued_prompt(clustered, prev_result):
    """Build prompt for a continued_table page."""
    prev_context = {
        'attr_dimensions': prev_result.get('attr_dimensions', []),
        'cost_items': prev_result.get('cost_items', []),
        'subsection': prev_result.get('subsection', ''),
        'unit': prev_result.get('unit', ''),
    }
    return f"""你是一个工程造价定额数据的结构化提取器。

这是一个**续前表**页面。以下是前页的提取结果（含 attr_dimensions 和 cost_items 定义）：

{json.dumps(prev_context, ensure_ascii=False, indent=2)}

以下是本页的列对齐数据。本页只有数据行，表头结构继承自前页。

{json.dumps(clustered, ensure_ascii=False, indent=2)}

请提取本页的 items，沿用前页的 attr_dimensions 和 cost_items 定义。
只输出 JSON，不要解释。

## 输出格式

{{
  "page_type": "continued_table",
  "items": [
    {{
      "quota_code": "<定额编号>",
      "attr_<属性名1>": "<值>",
      "<费用项目名>": <数值或null>
    }}
  ]
}}
"""


def call_claude_api(prompt, model="claude-sonnet-4-6", max_tokens=4096):
    """Call Claude API. Requires ANTHROPIC_API_KEY in environment."""
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def validate_result(result, n_codes, n_cost_items):
    """Validate AI output. Returns list of error messages."""
    errors = []
    expected = n_codes * n_cost_items
    actual = len(result.get('items', []))
    if actual != expected:
        errors.append(f"Expected {expected} items (={n_codes} codes x {n_cost_items} cost_items), got {actual}")
    if not result.get('attr_dimensions'):
        errors.append("No attr_dimensions found")
    return errors


def build_retry_prompt(original_prompt, failed_result, errors):
    """Augment prompt with error details for retry."""
    error_text = "\n".join(f"- {e}" for e in errors)
    return f"""你上次的输出有以下问题：

{error_text}

上次输出:
{json.dumps(failed_result, ensure_ascii=False, indent=2)[:500]}

请修正这些问题并重新输出。只输出 JSON。

{original_prompt}"""


def extract_page(clustered, prev_result=None, model="claude-sonnet-4-6"):
    """Extract one page via AI, with retry logic."""
    n_codes = len(clustered.get('code_columns', []))
    n_cost_items = len(clustered.get('data_rows', []))

    if clustered.get('is_continued') and prev_result:
        prompt = build_continued_prompt(clustered, prev_result)
        expected_cost_items = len(prev_result.get('cost_items', []))
    else:
        prompt = build_full_prompt(clustered)
        expected_cost_items = n_cost_items

    for attempt in range(3):
        try:
            response_text = call_claude_api(prompt, model=model)
            # Extract JSON from response (may be wrapped in ```json blocks)
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)
            result = json.loads(response_text)

            errors = validate_result(result, n_codes, expected_cost_items)
            if not errors:
                return result

            if attempt < 2:
                prompt = build_retry_prompt(prompt, result, errors)

        except json.JSONDecodeError:
            if attempt < 2:
                prompt = "你上次的输出不是合法 JSON。请严格按格式输出。\n\n" + prompt
        except Exception as e:
            print(f"  API error (attempt {attempt+1}): {e}")
            if attempt >= 2:
                raise

    return None


def main():
    import argparse
    ap = argparse.ArgumentParser(description='AI-powered semantic extraction from clustered data')
    ap.add_argument('--clustered-dir', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--pages')
    ap.add_argument('--model', default='claude-sonnet-4-6')
    ap.add_argument('--structure', help='structure.json for chapter context')
    args = ap.parse_args()

    clustered_dir = Path(args.clustered_dir)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.pages:
        if '-' in args.pages:
            start, end = args.pages.split('-')
            pages = list(range(int(start), int(end) + 1))
        else:
            pages = [int(args.pages)]
    else:
        pages = []
        for fpath in sorted(clustered_dir.glob('page_*.json')):
            m = re.match(r'page_(\d+)\.json', fpath.name)
            if m:
                pages.append(int(m.group(1)))

    prev_result = None
    processed = 0
    failed = []

    for pg in sorted(pages):
        fpath = clustered_dir / f'page_{pg:04d}.json'
        if not fpath.exists():
            continue

        with open(fpath, 'r', encoding='utf-8') as f:
            clustered = json.load(f)

        if not clustered.get('code_columns'):
            prev_result = None
            continue

        print(f"Page {pg}...", end=' ', flush=True)
        result = extract_page(clustered, prev_result, model=args.model)

        if result is None:
            print("FAILED")
            failed.append(pg)
            prev_result = None
            continue

        result['page'] = pg
        out_path = out_dir / f'page_{pg:04d}.json'
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if result.get('page_type') == 'quota_table':
            prev_result = result

        processed += 1
        n_items = len(result.get('items', []))
        n_attrs = len(result.get('attr_dimensions', []))
        print(f"{n_items} items, {n_attrs} attrs")

    print(f"\nExtracted: {processed} pages")
    if failed:
        print(f"Failed ({len(failed)}): {failed}")


if __name__ == '__main__':
    main()
