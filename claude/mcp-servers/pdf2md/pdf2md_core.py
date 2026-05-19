"""PDF to Markdown converter with auto-detection of text vs image pages."""

import os
import tempfile
import warnings
from pathlib import Path
from typing import Optional

import fitz
from rapidocr_onnxruntime import RapidOCR

TEXT_THRESHOLD = 50  # min chars per page to classify as text-based
RENDER_DPI = 200     # DPI for rendering image pages for OCR


def _parse_page_range(page_range: str, total_pages: int) -> list[int]:
    """Parse page range string like '1-5,7,10-12' (1-based) to 0-based indices."""
    pages = []
    for part in page_range.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start) - 1, int(end)))
        else:
            pages.append(int(part) - 1)
    return [p for p in pages if 0 <= p < total_pages]


def _detect_page_type(page: fitz.Page) -> str:
    text = page.get_text("text") or page.get_text("blocks")
    if isinstance(text, list):
        text = " ".join(b[4] for b in text if b[6] == 0)
    return "text" if len(text.strip()) >= TEXT_THRESHOLD else "image"


def _extract_text_page(page: fitz.Page) -> str:
    text = page.get_text("text")
    if not text.strip():
        blocks = page.get_text("blocks")
        text = "\n".join(b[4] for b in blocks if b[6] == 0)
    return text.strip()


def _extract_image_page(page: fitz.Page, ocr: RapidOCR) -> str:
    pix = page.get_pixmap(dpi=RENDER_DPI)
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)

    try:
        pix.save(tmp_path)
        result, _ = ocr(tmp_path)
        if not result:
            return ""
        lines = [item[1] for item in result]
        return "\n".join(lines)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def pdf_to_markdown(
    pdf_path: str,
    force_ocr: bool = False,
    page_range: Optional[str] = None,
) -> str:
    """Convert a PDF file to markdown.

    Auto-detects text-based vs image-based pages. Text pages use pymupdf's
    built-in markdown extraction. Image pages are rendered and OCR'd.

    Args:
        pdf_path: Absolute path to the PDF file.
        force_ocr: If True, OCR every page (skip text extraction).
        page_range: Optional range like "1-5,7,10" (1-based, inclusive).

    Returns:
        Markdown string.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ocr = RapidOCR()

    doc = fitz.open(pdf_path)
    total = len(doc)

    if page_range:
        indices = _parse_page_range(page_range, total)
    else:
        indices = list(range(total))

    md_parts = []
    for i in indices:
        page = doc[i]
        if force_ocr:
            part = _extract_image_page(page, ocr)
        elif _detect_page_type(page) == "text":
            part = _extract_text_page(page)
        else:
            part = _extract_image_page(page, ocr)

        if part:
            md_parts.append(part)

    doc.close()
    return "\n\n---\n\n".join(md_parts)
