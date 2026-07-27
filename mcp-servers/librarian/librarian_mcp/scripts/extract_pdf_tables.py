from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import pandas as pd
import pdfplumber

try:
    import camelot  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    camelot = None

try:
    import tabula  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tabula = None


TABLE_SETTINGS_CANDIDATES = [
    {},
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
    },
    {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "min_words_vertical": 2,
        "min_words_horizontal": 1,
    },
]

ENGINE_ORDER = (
    "pdfplumber",
    "camelot_lattice",
    "tabula_lattice",
    "camelot_stream",
    "tabula_stream",
)

ENGINE_MODES = {
    "auto": ENGINE_ORDER,
    "auto_lattice": (
        "camelot_lattice",
        "tabula_lattice",
        "pdfplumber",
        "camelot_stream",
        "tabula_stream",
    ),
}

JAVA_HOME_CANDIDATES = sorted((Path(r"C:\Program Files\Java")).glob("jdk-*"), reverse=True) if Path(r"C:\Program Files\Java").exists() else []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract tables from PDF into csv/xlsx/markdown preview.")
    parser.add_argument("--input", required=True, help="Source PDF path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--stem", help="Override output file stem")
    parser.add_argument("--source-name", help="Override displayed source filename")
    parser.add_argument(
        "--engine",
        default="auto_lattice",
        choices=tuple(ENGINE_MODES) + ENGINE_ORDER,
        help="Table extraction engine. Default tries multiple engines in order.",
    )
    return parser.parse_args()


def normalize_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_search_text(value: object) -> str:
    text = normalize_cell(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def header_key(value: object) -> str:
    text = normalize_search_text(value).lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def trim_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return rows
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    keep_indexes = [idx for idx in range(width) if any(row[idx] for row in padded)]
    if not keep_indexes:
        return padded
    return [[row[idx] for idx in keep_indexes] for row in padded]


def normalize_rows(raw_rows: Iterable[Iterable[object]]) -> list[list[str]]:
    rows = [[normalize_cell(cell) for cell in row] for row in raw_rows if row]
    rows = [row for row in rows if any(cell for cell in row)]
    return trim_empty_columns(rows)


def unique_headers(values: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for idx, value in enumerate(values, start=1):
        base = re.sub(r"\s+", " ", value).strip() or f"col_{idx}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        headers.append(base if count == 1 else f"{base}_{count}")
    return headers


def header_score(row: list[str]) -> int:
    nonempty = sum(1 for cell in row if cell)
    longish = sum(1 for cell in row if len(re.sub(r"\W+", "", cell, flags=re.UNICODE)) >= 2)
    return nonempty + longish


def rows_to_dataframe(rows: list[list[str]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    if len(padded) == 1:
        headers = unique_headers([f"col_{idx}" for idx in range(1, width + 1)])
        return pd.DataFrame(padded, columns=headers)

    first_score = header_score(padded[0])
    second_score = header_score(padded[1]) if len(padded) > 1 else -1
    use_first_row_as_header = first_score >= second_score and first_score >= max(2, width // 2)

    if use_first_row_as_header:
        headers = unique_headers(padded[0])
        body = padded[1:] or [[""] * width]
    else:
        headers = unique_headers([f"col_{idx}" for idx in range(1, width + 1)])
        body = padded
    return pd.DataFrame(body, columns=headers)


def dataframe_to_rows(df: pd.DataFrame) -> list[list[str]]:
    normalized = df.fillna("").astype(str)
    has_meaningful_headers = any(
        value and not re.fullmatch(r"(Unnamed:\s*\d+|col_\d+|\d+)", value)
        for value in [normalize_cell(column) for column in normalized.columns]
    )
    rows = normalized.values.tolist()
    if has_meaningful_headers:
        rows = [[normalize_cell(column) for column in normalized.columns]] + rows
    return normalize_rows(rows)


def extract_pdfplumber_tables(page: pdfplumber.page.Page) -> list[pd.DataFrame]:
    for settings in TABLE_SETTINGS_CANDIDATES:
        tables = page.extract_tables(table_settings=settings)
        normalized_tables = [normalize_rows(table) for table in tables if table]
        normalized_tables = [table for table in normalized_tables if table and len(table) >= 2]
        if normalized_tables:
            return [rows_to_dataframe(table) for table in normalized_tables]
    return []


def extract_camelot_tables(source: Path, page_index: int, flavor: str) -> list[pd.DataFrame]:
    if camelot is None:
        return []
    tables = camelot.read_pdf(str(source), pages=str(page_index), flavor=flavor, suppress_stdout=True)
    dataframes = [rows_to_dataframe(dataframe_to_rows(table.df)) for table in tables]
    return [df for df in dataframes if not df.empty]


def extract_tabula_tables(source: Path, page_index: int, lattice: bool) -> list[pd.DataFrame]:
    if tabula is None:
        return []
    if "JAVA_HOME" not in os.environ:
        java_home = next((candidate for candidate in JAVA_HOME_CANDIDATES if (candidate / "bin" / "server" / "jvm.dll").exists()), None)
        if java_home is not None:
            os.environ["JAVA_HOME"] = str(java_home)
            os.environ["PATH"] = str(java_home / "bin") + ";" + os.environ.get("PATH", "")
    dataframes = tabula.read_pdf(
        str(source),
        pages=page_index,
        multiple_tables=True,
        lattice=lattice,
        stream=not lattice,
        guess=False,
        silent=True,
    )
    normalized = [rows_to_dataframe(dataframe_to_rows(df)) for df in dataframes if df is not None]
    return [df for df in normalized if not df.empty]


def extract_page_tables(source: Path, page_index: int, page: pdfplumber.page.Page, engine: str) -> tuple[str, list[pd.DataFrame]]:
    engine_candidates = ENGINE_MODES.get(engine, (engine,))
    for candidate in engine_candidates:
        try:
            if candidate == "pdfplumber":
                tables = extract_pdfplumber_tables(page)
            elif candidate == "camelot_lattice":
                tables = extract_camelot_tables(source, page_index, "lattice")
            elif candidate == "camelot_stream":
                tables = extract_camelot_tables(source, page_index, "stream")
            elif candidate == "tabula_lattice":
                tables = extract_tabula_tables(source, page_index, lattice=True)
            elif candidate == "tabula_stream":
                tables = extract_tabula_tables(source, page_index, lattice=False)
            else:
                tables = []
        except Exception:
            tables = []
        if tables:
            return candidate, tables
    return "none", []


def dataframe_preview(df: pd.DataFrame, row_limit: int = 8) -> str:
    preview = df.head(row_limit).fillna("")
    headers = [str(column).replace("\n", "<br>") for column in preview.columns]
    rows = [
        [str(value).replace("\n", "<br>") for value in row]
        for row in preview.astype(str).itertuples(index=False, name=None)
    ]
    table_lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    table_lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(table_lines)


def detect_column_roles(df: pd.DataFrame) -> dict[str, str]:
    headers = [str(column) for column in df.columns]
    keys = {header: header_key(header) for header in headers}
    role_keywords = {
        "material": ("材料名称及规格", "材料名称", "名称及规格", "材料名", "材料", "名称", "规格"),
        "unit": ("单位",),
        "price": ("市场价", "信息价", "单价", "价格", "市场价格"),
        "note": ("备注", "厂家", "品牌", "产地", "说明"),
    }
    roles: dict[str, str] = {}
    for role, keywords in role_keywords.items():
        for header, key in keys.items():
            if any(keyword in key for keyword in keywords):
                roles[role] = header
                break

    if "material" not in roles:
        for header in headers:
            if header not in roles.values() and header_key(header) not in {"", "col1", "col2", "col3", "col4"}:
                roles["material"] = header
                break
    return roles


def parse_price_value(value: object) -> str:
    text = normalize_search_text(value)
    text = re.sub(r"(?<=\d)\s*[.．]\s*(?=\d)", ".", text)
    text = re.sub(r"(?<=\d)\s*,\s*(?=\d{3}\b)", "", text)
    text = text.replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def build_record_rows(table_entries: list[dict[str, object]]) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for entry in table_entries:
        df: pd.DataFrame = entry["df"]  # type: ignore[assignment]
        roles = detect_column_roles(df)
        material_col = roles.get("material")
        price_col = roles.get("price")
        if not material_col or not price_col:
            continue

        unit_col = roles.get("unit")
        note_col = roles.get("note")
        leftover_cols = [column for column in df.columns if column not in {material_col, price_col, unit_col, note_col}]

        for _, row in df.iterrows():
            material = normalize_search_text(row.get(material_col, ""))
            unit = normalize_search_text(row.get(unit_col, "")) if unit_col else ""
            price_text = normalize_search_text(row.get(price_col, ""))
            price_value = parse_price_value(price_text)
            note_parts: list[str] = []
            if note_col:
                note_value = normalize_search_text(row.get(note_col, ""))
                if note_value:
                    note_parts.append(note_value)
            for column in leftover_cols:
                extra_value = normalize_search_text(row.get(column, ""))
                if extra_value:
                    note_parts.append(f"{normalize_search_text(column)}={extra_value}")
            note = " | ".join(note_parts)

            material_key = header_key(material)
            if not material or not price_value:
                continue
            if material == unit:
                continue
            if material == price_text or header_key(price_text) == material_key:
                continue
            if material_key in {"材料名称及规格", "材料名称", "材料", "名称", "规格", "市场价", "价格"}:
                continue
            if len(material_key) < 2:
                continue

            records.append(
                {
                    "material_name": material,
                    "unit": unit,
                    "price_text": price_text,
                    "price_value": price_value,
                    "note": note,
                    "page": entry["page"],
                    "table_slug": entry["table_slug"],
                    "engine": entry["engine"],
                }
            )

    if not records:
        return pd.DataFrame(
            columns=["material_name", "unit", "price_text", "price_value", "note", "page", "table_slug", "engine"]
        )

    records_df = pd.DataFrame(records).drop_duplicates().sort_values(
        by=["material_name", "price_value", "page", "table_slug"],
        kind="stable",
    )
    return records_df.reset_index(drop=True)


def build_lookup_markdown(source_name: str, records_df: pd.DataFrame) -> str:
    lines = [
        "# 价格检索索引",
        "",
        f"- 原始文件：`{source_name}`",
        f"- 可检索记录数：{len(records_df)}",
        "- 字段：材料名称、单位、市场价、备注、页码、表格编号、命中引擎",
        "",
        "## 检索记录",
        "",
    ]
    for row in records_df.itertuples(index=False):
        lookup_key = " ".join(part for part in [row.material_name, row.price_value, row.unit] if part and part != "-")
        parts = [
            f"材料名称={row.material_name}",
            f"单位={row.unit or '-'}",
            f"市场价={row.price_value}",
            f"备注={row.note or '-'}",
            f"页码={row.page}",
            f"表格={row.table_slug}",
            f"引擎={row.engine}",
            f"检索键={lookup_key}",
        ]
        lines.append("- " + " | ".join(parts))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    source = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = args.stem or source.stem
    source_name = args.source_name or source.name
    csv_dir = output_dir / f"{stem}_tables"
    csv_dir.mkdir(parents=True, exist_ok=True)
    workbook_path = output_dir / f"{stem}.xlsx"
    markdown_path = output_dir / f"{stem}.md"
    records_csv_path = output_dir / f"{stem}.records.csv"
    records_workbook_path = output_dir / f"{stem}.records.xlsx"
    lookup_markdown_path = output_dir / f"{stem}.lookup.md"
    manifest_path = output_dir / f"{stem}.manifest.json"

    page_summaries: list[str] = []
    table_count = 0
    engine_usage: dict[str, int] = {}
    table_entries: list[dict[str, object]] = []

    with pdfplumber.open(str(source)) as pdf:
        xlsx_writer = None
        try:
            xlsx_writer = pd.ExcelWriter(workbook_path, engine="openpyxl")
        except Exception:
            pass
        try:
            for page_index, page in enumerate(pdf.pages, start=1):
                engine_name, tables = extract_page_tables(source, page_index, page, args.engine)
                if not tables:
                    continue
                engine_usage[engine_name] = engine_usage.get(engine_name, 0) + len(tables)

                page_summaries.append(f"## 第 {page_index} 页")
                page_summaries.append("")
                page_summaries.append(f"- 识别表格数：{len(tables)}")
                page_summaries.append(f"- 命中引擎：`{engine_name}`")
                page_summaries.append("")

                for table_index, df in enumerate(tables, start=1):
                    if df.empty:
                        continue
                    table_count += 1
                    table_slug = f"page_{page_index:03d}_table_{table_index:02d}"
                    csv_path = csv_dir / f"{table_slug}.csv"
                    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                    if xlsx_writer is not None:
                        try:
                            sheet_name = f"p{page_index}_t{table_index}"[:31]
                            df.to_excel(xlsx_writer, sheet_name=sheet_name, index=False)
                        except Exception:
                            pass
                    table_entries.append(
                        {
                            "page": page_index,
                            "table_slug": table_slug,
                            "engine": engine_name,
                            "rows": len(df),
                            "columns": len(df.columns),
                            "df": df.copy(),
                        }
                    )

                    page_summaries.append(f"### {table_slug}")
                    page_summaries.append("")
                    page_summaries.append(f"- CSV：`{csv_path.name}`")
                    page_summaries.append(f"- 行数：{len(df)}")
                    page_summaries.append(f"- 列数：{len(df.columns)}")
                    page_summaries.append("")
                    page_summaries.append(dataframe_preview(df))
                    page_summaries.append("")
        finally:
            if xlsx_writer is not None:
                try:
                    xlsx_writer.close()
                except Exception:
                    pass

    markdown_lines = [
        "# 表格提取结果",
        "",
        f"- 原始文件：`{source_name}`",
        f"- Excel 汇总：`{workbook_path.name}`",
        f"- CSV 目录：`{csv_dir.name}`",
        f"- 引擎模式：`{args.engine}`",
        f"- 识别表格总数：{table_count}",
        "",
    ]

    if engine_usage:
        markdown_lines.append("## 引擎统计")
        markdown_lines.append("")
        for engine_name, count in sorted(engine_usage.items()):
            markdown_lines.append(f"- `{engine_name}`：{count} 个表")
        markdown_lines.append("")

    if table_count == 0:
        markdown_lines.extend(
            [
                "## 结果说明",
                "",
                "- 未识别到稳定表格。",
                "- 这通常意味着该 PDF 需要 OCR 或更重的版面分析流程。",
                "",
            ]
        )
    else:
        markdown_lines.extend(page_summaries)

    markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    records_df = build_record_rows(table_entries)
    if not records_df.empty:
        records_df.to_csv(records_csv_path, index=False, encoding="utf-8-sig")
        table_summary_df = pd.DataFrame(
            [
                {
                    "page": entry["page"],
                    "table_slug": entry["table_slug"],
                    "engine": entry["engine"],
                    "rows": entry["rows"],
                    "columns": entry["columns"],
                }
                for entry in table_entries
            ]
        )
        try:
            with pd.ExcelWriter(records_workbook_path, engine="openpyxl") as writer:
                records_df.to_excel(writer, sheet_name="records", index=False)
                table_summary_df.to_excel(writer, sheet_name="tables", index=False)
        except Exception:
            pass
        lookup_markdown_path.write_text(build_lookup_markdown(source_name, records_df), encoding="utf-8")

    manifest = {
        "source_name": source_name,
        "engine_mode": args.engine,
        "table_count": table_count,
        "engine_usage": engine_usage,
        "records_count": int(len(records_df)),
        "artifacts": {
            "preview_markdown": markdown_path.name,
            "raw_workbook": workbook_path.name,
            "raw_csv_dir": csv_dir.name,
            "records_csv": records_csv_path.name if records_csv_path.exists() else None,
            "records_workbook": records_workbook_path.name if records_workbook_path.exists() else None,
            "lookup_markdown": lookup_markdown_path.name if lookup_markdown_path.exists() else None,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
