"""MCP server for pdf2md - expose pdf_to_markdown as an MCP tool."""

import asyncio
import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from pdf2md_core import pdf_to_markdown

app = Server("pdf2md")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="pdf_to_markdown",
            description=(
                "将PDF文件转换为Markdown格式。自动检测页面类型："
                "文字型PDF直接提取文字和格式，图片型/扫描件PDF通过OCR识别。"
                "支持混合型PDF（同时包含文字页和图片页）逐页分流处理。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "PDF文件的绝对路径。",
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "输出的Markdown文件路径（可选）。"
                            "如不提供，结果以文本形式返回。"
                        ),
                    },
                    "force_ocr": {
                        "type": "boolean",
                        "description": (
                            "是否强制对所有页面使用OCR（默认false）。"
                            "用于扫描件或图片型PDF。"
                        ),
                    },
                    "page_range": {
                        "type": "string",
                        "description": (
                            "指定转换的页面范围，如 '1-5,7,10-12'（1-based）。"
                            "不指定则转换全部页面。"
                        ),
                    },
                },
                "required": ["file_path"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    file_path = arguments.get("file_path", "")

    if not file_path or not Path(file_path).is_file():
        return [TextContent(type="text", text=f"错误: 找不到PDF文件 {file_path}")]

    if not file_path.lower().endswith(".pdf"):
        return [TextContent(type="text", text=f"错误: 不是PDF文件 {file_path}")]

    if name == "pdf_to_markdown":
        try:
            md = pdf_to_markdown(
                file_path,
                force_ocr=arguments.get("force_ocr", False),
                page_range=arguments.get("page_range"),
            )

            output_path = arguments.get("output_path", "")
            if output_path:
                Path(output_path).write_text(md, encoding="utf-8")
                return [TextContent(
                    type="text",
                    text=f"Markdown已保存到 {output_path} ({len(md)} 字符)",
                )]

            return [TextContent(type="text", text=md)]
        except Exception as e:
            return [TextContent(type="text", text=f"转换失败: {e}")]

    return [TextContent(type="text", text=f"未知工具: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream, app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
