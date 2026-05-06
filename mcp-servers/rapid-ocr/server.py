import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from rapidocr_onnxruntime import RapidOCR


ocr_engine = RapidOCR()
app = Server("rapid-ocr")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="ocr_image",
            description="OCR识别图片中的文字，返回markdown格式的文本。支持中英文混合识别。",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "图片文件的绝对路径。支持 png, jpg, jpeg, bmp, tiff, webp 等常见格式。"
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "text", "json"],
                        "description": "输出格式。markdown: 按段落组织; text: 纯文本; json: 包含位置信息的结构化数据。默认 markdown。"
                    }
                },
                "required": ["image_path"]
            }
        ),
        Tool(
            name="ocr_markdown",
            description="将图片直接转换为markdown文档。会自动识别标题、正文段落、表格结构，保留文档层次。适合将扫描件、截图转写为markdown。",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "图片文件的绝对路径。"
                    }
                },
                "required": ["image_path"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    image_path = arguments.get("image_path", "")

    if not image_path or not Path(image_path).is_file():
        return [TextContent(type="text", text=f"错误: 找不到图片文件 {image_path}")]

    if name == "ocr_image":
        output_format = arguments.get("output_format", "markdown")
        return await do_ocr_image(image_path, output_format)
    elif name == "ocr_markdown":
        return await do_ocr_markdown(image_path)
    else:
        return [TextContent(type="text", text=f"未知工具: {name}")]


async def do_ocr_image(image_path: str, output_format: str):
    result, elapse = ocr_engine(image_path)

    if result is None:
        return [TextContent(type="text", text="未能从图片中识别出文字。")]

    if output_format == "json":
        return [TextContent(
            type="text",
            text=json.dumps({"text_lines": result, "elapse_sec": elapse}, ensure_ascii=False, indent=2)
        )]

    lines = [item[1] for item in result]

    if output_format == "text":
        return [TextContent(type="text", text="\n".join(lines))]

    # markdown format: try to group lines into paragraphs
    paragraphs = group_into_paragraphs(result)
    md = build_markdown(paragraphs)
    return [TextContent(type="text", text=md)]


async def do_ocr_markdown(image_path: str):
    """更智能的markdown转换：尝试识别标题、段落、表格。"""
    result, _ = ocr_engine(image_path)

    if result is None:
        return [TextContent(type="text", text="未能从图片中识别出文字。")]

    paragraphs = group_into_paragraphs(result)
    md_lines = []
    prev_is_title = False

    for para in paragraphs:
        block = para["text"]
        center_x = para["center_x"]
        font_size = para["avg_height"]
        left_x = para["min_x"]
        img_width = max(line[1][2] for line in result)  # rough image width

        # Heuristic title detection: centered, larger font, or short text
        is_centered = abs(center_x - img_width / 2) < img_width * 0.15
        is_large = font_size > sum(p["avg_height"] for p in paragraphs) / len(paragraphs) * 1.2
        is_short = len(block) < 60 and not block.endswith((".", "。", "，", ","))

        if is_centered and is_large and is_short:
            level = 1 if font_size > 1.3 * (sum(p["avg_height"] for p in paragraphs) / len(paragraphs)) else 2
            md_lines.append(f"{'#' * level} {block}\n")
            prev_is_title = True
        elif is_centered and is_short and left_x > img_width * 0.15:
            # Centered short text, likely a sub-header
            md_lines.append(f"### {block}\n")
            prev_is_title = True
        else:
            if prev_is_title and not block.startswith("-"):
                md_lines.append(f"{block}\n")
            else:
                md_lines.append(f"{block}\n")
            prev_is_title = False

    return [TextContent(type="text", text="\n".join(md_lines))]


def group_into_paragraphs(result):
    """Group OCR text lines into paragraphs based on vertical spacing."""
    if not result:
        return []

    # result: list of [box, text, confidence] where box is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    sorted_lines = sorted(result, key=lambda r: (r[0][0][1], r[0][0][0]))
    if not sorted_lines:
        return []

    paragraphs = []
    current_para_lines = [sorted_lines[0]]
    gap_threshold = 0

    # Calculate average line height and gap
    heights = []
    gaps = []
    for i, item in enumerate(sorted_lines):
        box = item[0]
        height = box[2][1] - box[0][1]
        heights.append(height)
        if i > 0:
            prev_box = sorted_lines[i-1][0]
            gap = box[0][1] - prev_box[2][1]
            gaps.append(gap)

    avg_height = sum(heights) / len(heights) if heights else 20
    avg_gap = sum(gaps) / len(gaps) if gaps else avg_height * 0.3
    gap_threshold = max(avg_gap * 1.5, avg_height * 0.5)

    for i, item in enumerate(sorted_lines[1:], 1):
        prev_box = sorted_lines[i-1][0]
        current_box = item[0]
        gap = current_box[0][1] - prev_box[2][1]

        if gap > gap_threshold:
            # New paragraph
            txt = "".join(l[1] for l in current_para_lines)
            x_centers = [(l[0][0][0] + l[0][2][0]) / 2 for l in current_para_lines]
            min_x = min(l[0][0][0] for l in current_para_lines)
            heights_vals = [l[0][2][1] - l[0][0][1] for l in current_para_lines]
            paragraphs.append({
                "text": txt,
                "center_x": sum(x_centers) / len(x_centers),
                "avg_height": sum(heights_vals) / len(heights_vals),
                "min_x": min_x,
            })
            current_para_lines = [item]
        else:
            current_para_lines.append(item)

    # Last paragraph
    txt = "".join(l[1] for l in current_para_lines)
    x_centers = [(l[0][0][0] + l[0][2][0]) / 2 for l in current_para_lines]
    min_x = min(l[0][0][0] for l in current_para_lines)
    heights_vals = [l[0][2][1] - l[0][0][1] for l in current_para_lines]
    paragraphs.append({
        "text": txt,
        "center_x": sum(x_centers) / len(x_centers),
        "avg_height": sum(heights_vals) / len(heights_vals),
        "min_x": min_x,
    })

    return paragraphs


def build_markdown(paragraphs):
    """Build markdown from paragraphs, with simple heuristics."""
    lines = []
    for para in paragraphs:
        text = para["text"].strip()
        if not text:
            continue
        lines.append(f"{text}\n")
    return "\n".join(lines)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
