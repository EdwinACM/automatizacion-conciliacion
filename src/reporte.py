"""Reporte Excel: Resumen, Conciliadas, Revision, Pendientes y Bitacora."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from comun import celda_segura, con_reintentos

ENC_FONT = Font(bold=True, color="FFFFFF")
ENC_FILL = PatternFill("solid", fgColor="305496")
FORMATO_MONTO = "#,##0.00"


def _tabla(ws, encabezados, filas, montos=()):
    ws.append(encabezados)
    for c in ws[1]:
        c.font, c.fill = ENC_FONT, ENC_FILL
    for fila in filas:
        ws.append([celda_segura(v) for v in fila])
    for idx in montos:
        for celda in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            celda[0].number_format = FORMATO_MONTO
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions
    for i, enc in enumerate(encabezados, start=1):
        ancho = max([len(str(enc))] + [len(str(c.value)) for c in ws[get_column_letter(i)][1:60] if c.value is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(ancho + 2, 60)


def _m(centavos):
    return None if centavos is None else centavos / 100


def construir(res, banco, doc, resumen: dict, bitacora: list[tuple[str, str, str]]) -> Workbook:
    pb = {p.id: p for p in banco}
    pd_ = {p.id: p for p in doc}
    wb = Workbook()

    ws = wb.active
    ws.title = "Resumen"
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 44
    ws.append(["Concepto", "Valor"])
    for c in ws[1]:
        c.font, c.fill = ENC_FONT, ENC_FILL
    for k, v in resumen.items():
        if v == "":
            ws.append([celda_segura(k)])
            ws.cell(ws.max_row, 1).font = Font(bold=True)
        else:
            ws.append([celda_segura(k), celda_segura(v)])
            ws.cell(ws.max_row, 2).alignment = Alignment(horizontal="left", wrap_text=True)

    def filas_coinc(lista):
        for n, c in enumerate(lista, start=1):
            mb = sum(pb[i].monto for i in c.ids_banco)
            md = sum(pd_[i].monto for i in c.ids_doc if i in pd_)
            yield [n, c.regla, c.confianza, ";".join(c.ids_banco), ";".join(c.ids_doc),
                   pb[c.ids_banco[0]].fecha, _m(mb), _m(md) if c.ids_doc and c.estado == "conciliada" else None,
                   _m(c.dif_centavos), c.dif_dias, c.detalle]

    enc = ["n", "regla", "confianza", "id_mov", "ids_doc", "fecha_valor", "monto_banco",
           "monto_contable", "diferencia", "dif_dias", "detalle"]
    _tabla(wb.create_sheet("Conciliadas"), enc, filas_coinc(res.conciliadas), montos=(7, 8, 9))

    def filas_rev():
        for n, c in enumerate(res.revision, start=1):
            b = pb[c.ids_banco[0]]
            yield [n, c.regla, c.confianza, ";".join(c.ids_banco), ";".join(c.ids_doc), b.fecha,
                   _m(b.monto), c.detalle, "Pendiente de decisión humana"]
    _tabla(wb.create_sheet("Revision"),
           ["n", "regla", "confianza_propuesta", "id_mov", "ids_doc_candidatos", "fecha_valor",
            "monto_banco", "motivo", "estado"], filas_rev(), montos=(7,))

    def filas_pend():
        for p in res.pend_banco:
            yield ["banco", p.id, p.fecha, _m(p.monto), p.ref_original, "Sin documento contable que coincida"]
        for p in res.pend_doc:
            yield ["contable", p.id, p.fecha, _m(p.monto), p.ref_original, "Sin movimiento bancario que coincida"]
    _tabla(wb.create_sheet("Pendientes"), ["origen", "id", "fecha", "monto", "referencia", "motivo"],
           filas_pend(), montos=(4,))

    _tabla(wb.create_sheet("Bitacora"), ["marca_tiempo_utc", "nivel", "evento"], bitacora)
    return wb


def guardar_atomico(wb: Workbook, destino: Path, intentos: int, espera: float, log=None) -> None:
    """Escribe a un temporal en la misma carpeta y luego renombra, para no dejar un archivo a medias."""
    destino = Path(destino)

    def escribir():
        destino.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=destino.parent, suffix=".tmp")
        os.close(fd)
        try:
            wb.save(tmp)
            os.replace(tmp, destino)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    con_reintentos(escribir, intentos, espera, log=log)
