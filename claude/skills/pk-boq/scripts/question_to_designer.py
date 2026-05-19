"""
生成致设计院的 BOQ 疑问表格（FHDI 格式）

工作流：先出 MD 中文版（表格形式，10列表头与正式 Excel 一致）供内部确认 → 确认后出 Excel 英文版对外发送。

输入：按 section 组织的 issues 列表
输出：10列 xlsx，含项目信息头、分段标题（合并单元格）、编号问题行

Usage:
    from question_to_designer import build_question_xlsx
    build_question_xlsx(config, sections, output_path)

xlsx 兼容性：
    使用 xlsxwriter（原生 Office 兼容），避免 openpyxl merge_cells 灰屏问题

写作规则：
    - Attachment Ref.: 可写清单文件名
    - Question: 简明，不写 OM/DI 编号
    - 数量比较: 设计清单量 vs 设计报告量（同源），不比招标清单
    - Ask By: 固定 "Peng Kang"
"""

import xlsxwriter
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class QuestionConfig:
    """疑问函配置。"""
    project_name: str = "Project Name"
    package: str = ""
    employer: str = ""
    qs_name: str = "Peng Kang"
    email_to: str = ""
    date: str = ""
    sheet_name: str = "1"
    # 列宽
    col_widths: list[int] = field(default_factory=lambda: [5, 9, 11, 17, 17, 55, 8, 22, 8, 9])
    # 列头
    col_headers: list[str] = field(default_factory=lambda: [
        "ITEM", "Date", "Disciplines", "BOQ Ref.", "Attachment Ref.",
        "QUESTION", "ASK BY", "ANSWER", "ANSWER BY", "ANSWER DATE",
    ])

    def __post_init__(self):
        if not self.date:
            self.date = datetime.now().strftime("%Y-%m-%d")


# ============================================================
# 主函数
# ============================================================

def build_question_xlsx(
    config: QuestionConfig,
    sections: list[dict],
    output_path: str,
):
    """
    生成疑问表格 xlsx。

    sections 结构:
    [
        {
            "title": "【BOQ Missing Items — High Impact】",
            "items": [
                {
                    "date": "2026-05-03",
                    "discipline": "C_Dredging",
                    "boq_ref": "C.1.1",
                    "attachment_ref": "Design Report §3.2",
                    "question": "Detailed question text in English...",
                    "ask_by": "",
                    "answer": "",
                    "answer_by": "",
                    "answer_date": "",
                },
                ...
            ],
        },
        ...
    ]
    """
    wb = xlsxwriter.Workbook(output_path)
    ws = wb.add_worksheet(config.sheet_name)

    # --- 格式定义 ---
    fmt_title = wb.add_format({
        'bold': True, 'font_size': 14,
        'align': 'center', 'valign': 'vcenter',
    })
    fmt_header_label = wb.add_format({
        'bold': True, 'font_size': 10,
        'bg_color': '#F2F2F2',
        'border': 1, 'valign': 'vcenter',
    })
    fmt_header_value = wb.add_format({
        'font_size': 10,
        'border': 1, 'valign': 'vcenter',
    })
    fmt_section = wb.add_format({
        'bold': True, 'font_size': 11, 'font_color': '#003366',
        'bg_color': '#DBEEF4',
        'border': 1, 'valign': 'vcenter',
    })
    fmt_col_header = wb.add_format({
        'bold': True, 'font_size': 10, 'font_color': '#003366',
        'bg_color': '#B8CCE4',
        'border': 1, 'align': 'center', 'valign': 'vcenter',
        'text_wrap': True,
    })
    fmt_item = wb.add_format({
        'font_size': 10,
        'border': 1, 'valign': 'top',
    })
    fmt_item_num = wb.add_format({
        'font_size': 10,
        'border': 1, 'valign': 'top', 'align': 'center',
    })
    fmt_item_wrap = wb.add_format({
        'font_size': 10,
        'border': 1, 'valign': 'top', 'text_wrap': True,
    })

    # --- 列宽 ---
    for i, w in enumerate(config.col_widths):
        ws.set_column(i, i, w)

    row = 0

    # --- 信息头 ---
    header_labels = [
        ("PROJECT:", config.project_name),
        ("PACKAGE:", config.package),
        ("EMPLOYER:", config.employer),
        ("QS:", config.qs_name),
        ("EMAIL TO:", config.email_to),
        ("DATE:", config.date),
    ]

    ws.merge_range(row, 0, row, 9, "QUERY LIST TABLES", fmt_title)
    row += 1

    for label, value in header_labels:
        ws.merge_range(row, 0, row, 0, label, fmt_header_label)
        ws.merge_range(row, 1, row, 9, value, fmt_header_value)
        row += 1

    row += 1  # 空行
    ws.merge_range(row, 0, row, 9, f"{config.project_name}  Question List", fmt_title)
    row += 2  # 空行

    # --- 列头 ---
    for ci, header in enumerate(config.col_headers):
        ws.write(row, ci, header, fmt_col_header)
    row += 1

    # --- 分段写入问题 ---
    item_num = 1

    for section in sections:
        # 分段标题行
        ws.merge_range(row, 0, row, 9, section["title"], fmt_section)
        row += 1

        for item in section.get("items", []):
            ws.write(row, 0, item_num, fmt_item_num)
            ws.write(row, 1, item.get("date", config.date), fmt_item)
            ws.write(row, 2, item.get("discipline", ""), fmt_item)
            ws.write(row, 3, item.get("boq_ref", ""), fmt_item)
            ws.write(row, 4, item.get("attachment_ref", ""), fmt_item)
            ws.write(row, 5, item.get("question", ""), fmt_item_wrap)
            ws.write(row, 6, item.get("ask_by", "Peng Kang"), fmt_item)
            ws.write(row, 7, item.get("answer", ""), fmt_item)
            ws.write(row, 8, item.get("answer_by", ""), fmt_item)
            ws.write(row, 9, item.get("answer_date", ""), fmt_item)
            item_num += 1
            row += 1

        row += 1  # section 间空行

    # 设行高
    ws.set_default_row(18)

    # 网格线
    ws.hide_gridlines(0)

    wb.close()
    print(f"疑问函已生成: {output_path} ({item_num - 1} 个问题)")
    return output_path


# ============================================================
# 示例配置
# ============================================================

if __name__ == "__main__":
    # 示例：替换为自己的项目配置和问题数据
    cfg = QuestionConfig(
        project_name="Laldia Container Terminal Project",
        package="",
        employer="Laldia Container Terminal Limited",
        qs_name="",
        email_to="",
    )

    sections = [
        {
            "title": "【Section 1 — BOQ Missing Items / High Impact】",
            "items": [
                {
                    "date": "2026-05-03",
                    "discipline": "C_Dredging",
                    "boq_ref": "C.1.1",
                    "attachment_ref": "Design Report §3.1",
                    "question": "The design report indicates dredging volume of 208,000m³ for berth pocket + turning basin. Current BOQ item C.1.1 only covers 150,000m³. Please confirm the scope and add turning basin dredging as a separate item or revise the quantity.",
                    "ask_by": "",
                    "answer": "",
                    "answer_by": "",
                    "answer_date": "",
                },
            ],
        },
    ]

    build_question_xlsx(cfg, sections, "question_to_designer_sample.xlsx")
