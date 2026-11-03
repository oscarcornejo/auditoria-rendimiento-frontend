"""Estilos y utilidades de hoja compartidos por perf_report_xlsx.py y reporte_sitio.py."""
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HDR_FILL = PatternFill("solid", fgColor="1F3864")
HDR_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
COLORES = {"Crítico": "F8696B", "Alto": "FFA366", "Medio": "FFEB84", "Bajo": "C6E0B4", "Info": "DDEBF7",
           "Bueno": "C6EFCE", "Necesita mejorar": "FFEB9C", "Pobre": "FFC7CE", "Sin dato": "EDEDED"}
COLORES_CHECK = {"No cumple": "FFC7CE", "Cumple": "C6EFCE", "Revisar manualmente": "FFEB9C"}


def encabezado(ws, cols, fila=1):
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=fila, column=i, value=c)
        cell.fill, cell.font, cell.border = HDR_FILL, HDR_FONT, BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = f"A{fila + 1}"


def ajustar(ws, anchos):
    for i, a in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(i)].width = a


def pintar_estado(ws, col_letter, n_filas, fila_ini=2, colores=COLORES):
    if n_filas < fila_ini:
        return
    rng = f"{col_letter}{fila_ini}:{col_letter}{n_filas}"
    for k, color in colores.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{k}"'],
                                                      fill=PatternFill("solid", fgColor=color)))


def tabla(ws, cols, filas, anchos=None):
    """Hoja simple: encabezado, filas con borde, filtro y anchos."""
    encabezado(ws, cols)
    for f in filas:
        ws.append(list(f))
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.border = BORDER
            c.alignment = Alignment(vertical="top", wrap_text=True)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(ws.max_row, 1)}"
    if anchos:
        ajustar(ws, anchos)
