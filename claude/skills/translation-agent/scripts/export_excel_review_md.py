import argparse
from pathlib import Path

import pandas as pd


def escape_md(value):
    if value is None:
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "<br>")
    text = text.replace("|", r"\|")
    return text.strip()


def export_review_markdown(file_path, src_col, tgt_col, output_path=None, sheet_name=None):
    xlsx_path = Path(file_path)
    if output_path:
        md_path = Path(output_path)
    else:
        md_path = xlsx_path.with_suffix("").with_name(f"{xlsx_path.stem}.review.md")

    df = pd.read_excel(xlsx_path, sheet_name=sheet_name if sheet_name else 0, engine="openpyxl")
    df = df.fillna("")

    headers = list(df.columns)
    if src_col >= len(headers) or tgt_col >= len(headers):
        raise IndexError("Column index out of range.")

    src_name = headers[src_col]
    tgt_name = headers[tgt_col]

    lines = []
    lines.append(f"# {xlsx_path.stem} Review Draft")
    lines.append("")
    lines.append(f"- Source file: `{xlsx_path.name}`")
    lines.append("- Purpose: Excel -> Markdown review draft for translation critique, polish, and QA before writing back to Excel")
    lines.append(f"- Source column: `{src_name}`")
    lines.append(f"- Target column: `{tgt_name}`")
    lines.append("")
    lines.append("| row | item | item_description_en | translation_zh | unit | quantity |")
    lines.append("| --- | --- | --- | --- | --- | --- |")

    item_col = "Item" if "Item" in headers else headers[0]
    unit_col = "Unit" if "Unit" in headers else ""
    qty_col = "Quantity" if "Quantity" in headers else ""

    for idx, row in df.iterrows():
        excel_row = idx + 2
        values = [
            excel_row,
            row.get(item_col, ""),
            row.get(src_name, ""),
            row.get(tgt_name, ""),
            row.get(unit_col, "") if unit_col else "",
            row.get(qty_col, "") if qty_col else "",
        ]
        non_row_values = values[1:]
        if all(str(v).strip() in {"", "nan"} for v in non_row_values):
            continue
        escaped = [escape_md(v) for v in values]
        lines.append(
            f"| {escaped[0]} | {escaped[1]} | {escaped[2]} | {escaped[3]} | {escaped[4]} | {escaped[5]} |"
        )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(md_path)
    print(f"rows={len(df)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path")
    parser.add_argument("--src-col", type=int, default=1)
    parser.add_argument("--tgt-col", type=int, default=2)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--sheet", type=str, default=None)
    args = parser.parse_args()

    export_review_markdown(
        args.file_path,
        src_col=args.src_col,
        tgt_col=args.tgt_col,
        output_path=args.output,
        sheet_name=args.sheet,
    )


if __name__ == "__main__":
    main()
