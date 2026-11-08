"""授産売上金提出表を Excel（A4縦で印刷できる形）で作る。

rows は [{"date": date, "dest": str, "amount": int, "note": str}, ...]。
合計は Excel の計算式（SUM）なので、Excel で売上金を書き換えても合計が自動で変わる。
"""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins

FONT = "游ゴシック"
THIN = Side(style="thin", color="555555")
THICK = Side(style="medium", color="111111")
GRID = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="EDEDED")
BOX_FILL = PatternFill("solid", fgColor="F7F7F7")
MIN_ROWS = 20  # 表の行数（足りないときは増やす）。空いた行には Excel で手書き追加もできる


def _font(size=11, bold=False):
    return Font(name=FONT, size=size, bold=bold)


def build_xlsx(submit_date: date, office: str, no: str, rows: list[dict], title: str = "授産売上金提出表") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "売上金提出表"
    for col, width in zip("ABCDE", (15, 22, 22, 15, 22)):
        ws.column_dimensions[col].width = width

    # ---- タイトルと No. ----
    ws.merge_cells("A1:C1")
    ws["A1"] = title
    ws["A1"].font = _font(18, True)
    ws.row_dimensions[1].height = 34
    ws["D1"] = "No."
    ws["D1"].font = _font(11)
    ws["D1"].alignment = Alignment(horizontal="right", vertical="center")
    ws["E1"] = int(no) if str(no).isdigit() else no
    ws["E1"].font = _font(12)
    ws["E1"].border = GRID
    ws["E1"].fill = BOX_FILL
    ws["E1"].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    # ---- 提出日・事業所名・提出金合計 ----
    for cell, text in (("A3", "提出日"), ("B3", "事業所名"), ("D3", "提出金合計")):
        ws[cell] = text
        ws[cell].font = _font(10)
    ws.merge_cells("B4:C4")
    ws["A4"] = submit_date
    ws["A4"].number_format = "yyyy-mm-dd"
    ws["B4"] = office
    ws.row_dimensions[4].height = 26
    for col in "ABCD":
        c = ws[f"{col}4"]
        c.font = _font(12)
        c.border = GRID
        c.fill = BOX_FILL
        c.alignment = Alignment(vertical="center", horizontal="center" if col == "A" else "left", indent=0 if col == "A" else 1)

    # ---- 明細 ----
    head = 6
    ws.merge_cells(start_row=head, start_column=2, end_row=head, end_column=3)
    for col, text in zip("ABDE", ("受領日", "売上先", "売上金", "備考")):
        ws[f"{col}{head}"] = text
    ws.row_dimensions[head].height = 24
    for col in "ABCDE":
        c = ws[f"{col}{head}"]
        c.font = _font(10, True)
        c.fill = HEAD_FILL
        c.border = Border(left=THIN, right=THIN, top=THICK, bottom=THICK)
        c.alignment = Alignment(vertical="center", indent=1)

    first = head + 1
    count = max(MIN_ROWS, len(rows))
    last = first + count - 1
    for i in range(count):
        r = first + i
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
        ws.row_dimensions[r].height = 24
        if i < len(rows):
            row = rows[i]
            ws[f"A{r}"] = row["date"]
            ws[f"B{r}"] = row["dest"]
            ws[f"D{r}"] = int(row["amount"] or 0)
            ws[f"E{r}"] = row.get("note") or None
        for col in "ABCDE":
            c = ws[f"{col}{r}"]
            c.font = _font(11)
            c.border = GRID
            c.alignment = Alignment(vertical="center", indent=1 if col in "BE" else 0,
                                    horizontal={"A": "center", "D": "right"}.get(col, "left"))
        ws[f"A{r}"].number_format = "yyyy-mm-dd"
        ws[f"D{r}"].number_format = "#,##0"

    # ---- 合計（計算式なので Excel で書き換えても自動で変わる）----
    tot = last + 1
    ws.merge_cells(start_row=tot, start_column=1, end_row=tot, end_column=3)
    ws[f"A{tot}"] = "合計"
    ws[f"D{tot}"] = f"=SUM(D{first}:D{last})"
    ws.row_dimensions[tot].height = 26
    for col in "ABCDE":
        c = ws[f"{col}{tot}"]
        c.font = _font(12, True)
        c.border = Border(left=THIN, right=THIN, top=THICK, bottom=THICK)
        c.alignment = Alignment(vertical="center", horizontal="right" if col in "AD" else "left", indent=1)
    ws[f"D{tot}"].number_format = "#,##0"
    ws["D4"] = f"=D{tot}"
    ws["D4"].number_format = "#,##0"
    ws["D4"].alignment = Alignment(vertical="center", horizontal="right", indent=1)

    # ---- 印刷設定：A4 縦・横幅を1ページに合わせる ----
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins = PageMargins(left=0.5, right=0.5, top=0.7, bottom=0.7, header=0.3, footer=0.3)
    ws.print_area = f"A1:E{tot}"
    ws.print_title_rows = f"{head}:{head}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
