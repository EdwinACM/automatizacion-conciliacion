"""Genera dos fuentes sintéticas y una verdad de terreno, de forma reproducible (semilla 42).

Fuentes:
  datos/banco.csv        movimientos bancarios (CSV)
  datos/contable.xlsx    registro contable interno (Excel)
  datos/verdad_terreno.csv  qué debería pasar con cada partida (solo para evaluar)

Todo es inventado: nombres de clientes ficticios (CLI0001...), referencias aleatorias.
"""
from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config  # noqa: E402

SEMILLA = 42
INICIO = date(2026, 10, 1)

# casos y cuántos se generan
N_EXACTA, N_SUCIA, N_REDONDEO, N_FECHA, N_LIMITE = 60, 20, 10, 10, 3
N_DUPLICADO, N_GRUPO, N_SIN_REF = 6, 8, 4
N_SOLO_BANCO, N_SOLO_DOC = 8, 8


def _fmt_monto_banco(rng, centavos: int) -> str:
    texto = f"{centavos / 100:.2f}"
    if rng.random() < 0.10:
        return f"${centavos / 100:,.2f}"
    return texto


def _ref_sucia(rng, n: int) -> str:
    variantes = [
        f"fac-{n:07d} ", f"REF. {n:07d}", f"Pago FAC {n}", f"FAC–{n:07d}",
        f" {n:07d}", f"fact {n:07d}", f"FAC-{n:07d}.",
    ]
    return rng.choice(variantes)


def generar(destino: Path | None = None, semilla: int = SEMILLA) -> dict:
    cfg = Config.desde_entorno()
    destino = Path(destino) if destino else cfg.dir_datos
    destino.mkdir(parents=True, exist_ok=True)
    rng = random.Random(semilla)

    banco, doc, verdad = [], [], []
    montos_usados: set[int] = set()
    refs_usadas: set[int] = set()

    def monto_nuevo(minimo=15_000, maximo=9_000_000) -> int:
        while True:
            m = rng.randrange(minimo, maximo)
            if m not in montos_usados:
                montos_usados.add(m)
                return m

    def ref_nueva() -> int:
        while True:
            r = rng.randrange(1000, 9_999_999)
            if r not in refs_usadas:
                refs_usadas.add(r)
                return r

    def cliente() -> str:
        return f"CLI{rng.randrange(1, 41):04d}"

    cont = {"b": 0, "d": 0}

    def nuevo_b(fecha, monto, ref, desc="ABONO POR TRANSFERENCIA") -> str:
        cont["b"] += 1
        i = f"MOV-{cont['b']:06d}"
        banco.append({"id_mov": i, "fecha_valor": fecha, "monto": monto, "referencia": ref, "descripcion": desc})
        return i

    def nuevo_d(fecha, monto, ref, cli) -> str:
        cont["d"] += 1
        i = f"DOC-{cont['d']:06d}"
        doc.append({"id_doc": i, "fecha_contable": fecha, "monto": monto, "referencia": ref, "cliente": cli})
        return i

    def fecha_base() -> date:
        return INICIO + timedelta(days=rng.randrange(0, 28))

    def caso(lado, ident, contra, nombre, esperado):
        verdad.append({"lado": lado, "id": ident, "contraparte": contra, "caso": nombre, "esperado": esperado})

    # 1. coincidencia exacta y 2. referencia sucia
    for k in range(N_EXACTA + N_SUCIA):
        f, m, r = fecha_base(), monto_nuevo(), ref_nueva()
        sucia = k >= N_EXACTA
        ref_b = _ref_sucia(rng, r) if sucia else f"FAC-{r:07d}"
        b = nuevo_b(f, m, ref_b)
        d = nuevo_d(f, m, f"FAC-{r:07d}", cliente())
        nombre = "referencia_sucia" if sucia else "exacta"
        caso("banco", b, d, nombre, "conciliada")
        caso("contable", d, b, nombre, "conciliada")

    # 3. redondeo (1 a 5 centavos)
    for _ in range(N_REDONDEO):
        f, m, r = fecha_base(), monto_nuevo(), ref_nueva()
        dif = rng.choice([-5, -3, -1, 1, 2, 5])
        b = nuevo_b(f, m + dif, f"FAC-{r:07d}")
        d = nuevo_d(f, m, f"FAC-{r:07d}", cliente())
        caso("banco", b, d, "redondeo", "conciliada")
        caso("contable", d, b, "redondeo", "conciliada")

    # 4. fecha valor desfasada (1 a 3 días, hacia ambos lados)
    for _ in range(N_FECHA):
        f, m, r = fecha_base(), monto_nuevo(), ref_nueva()
        desfase = rng.choice([-3, -2, -1, 1, 2, 3])
        b = nuevo_b(f + timedelta(days=desfase), m, f"FAC-{r:07d}")
        d = nuevo_d(f, m, f"FAC-{r:07d}", cliente())
        caso("banco", b, d, "fecha_desfasada", "conciliada")
        caso("contable", d, b, "fecha_desfasada", "conciliada")

    # 5. en el límite de ambas tolerancias: la confianza queda baja y va a revisión
    for _ in range(N_LIMITE):
        f, m, r = fecha_base(), monto_nuevo(), ref_nueva()
        b = nuevo_b(f + timedelta(days=3), m + 10, f"FAC-{r:07d}")
        d = nuevo_d(f, m, f"FAC-{r:07d}", cliente())
        caso("banco", b, d, "limite_tolerancias", "revision")
        caso("contable", d, b, "limite_tolerancias", "revision")

    # 6. pago duplicado: el banco registra dos veces el mismo abono
    for _ in range(N_DUPLICADO):
        f, m, r = fecha_base(), monto_nuevo(), ref_nueva()
        b1 = nuevo_b(f, m, f"FAC-{r:07d}")
        b2 = nuevo_b(f, m, f"FAC-{r:07d}")
        d = nuevo_d(f, m, f"FAC-{r:07d}", cliente())
        caso("banco", b1, d, "duplicado_original", "conciliada")
        caso("banco", b2, d, "duplicado_copia", "revision")
        caso("contable", d, b1, "duplicado_original", "conciliada")

    # 7. un pago contra varias facturas (el banco trae el código de cliente)
    for _ in range(N_GRUPO):
        f, cli = fecha_base(), cliente()
        partes = [monto_nuevo(10_000, 3_000_000) for _ in range(rng.randrange(2, 5))]
        b = nuevo_b(f, sum(partes), f"PAGO {cli} LOTE {rng.randrange(1, 99)}", "ABONO MULTIPLE")
        ds = [nuevo_d(f - timedelta(days=rng.randrange(0, 3)), p, f"FAC-{ref_nueva():07d}", cli) for p in partes]
        caso("banco", b, ";".join(ds), "uno_a_muchos", "conciliada")
        for d in ds:
            caso("contable", d, b, "uno_a_muchos", "conciliada")

    # 7b. un pago que admite dos combinaciones distintas de facturas: queda en revisión
    f, cli = fecha_base(), "CLI0099"
    b = nuevo_b(f, 30_000, f"PAGO {cli} LOTE 7", "ABONO MULTIPLE")
    ds = [nuevo_d(f, p, f"FAC-{ref_nueva():07d}", cli) for p in (10_000, 20_000, 10_000, 10_000)]
    caso("banco", b, ";".join(ds), "uno_a_muchos_ambiguo", "revision")
    for d in ds:
        caso("contable", d, b, "uno_a_muchos_ambiguo", "pendiente")

    # 8. abono sin referencia: se propone por monto y fecha, pero con confianza baja
    for _ in range(N_SIN_REF):
        f, m, r = fecha_base(), monto_nuevo(), ref_nueva()
        b = nuevo_b(f + timedelta(days=rng.choice([0, 1])), m, "")
        d = nuevo_d(f, m, f"FAC-{r:07d}", cliente())
        caso("banco", b, d, "sin_referencia", "revision")
        caso("contable", d, b, "sin_referencia", "conciliada_por_revision")

    # 8b. abono sin referencia que coincide con dos documentos: ambiguo
    f, m = fecha_base(), monto_nuevo()
    b = nuevo_b(f, m, "")
    ds = [nuevo_d(f, m, f"FAC-{ref_nueva():07d}", cliente()) for _ in range(2)]
    caso("banco", b, ";".join(ds), "sin_referencia_ambiguo", "revision")
    for d in ds:
        caso("contable", d, b, "sin_referencia_ambiguo", "pendiente")

    # 9. partidas sin contraparte
    for _ in range(N_SOLO_BANCO):
        b = nuevo_b(fecha_base(), monto_nuevo(), f"FAC-{ref_nueva():07d}")
        caso("banco", b, "", "solo_banco", "pendiente")
    for _ in range(N_SOLO_DOC):
        d = nuevo_d(fecha_base(), monto_nuevo(), f"FAC-{ref_nueva():07d}", cliente())
        caso("contable", d, "", "solo_contable", "pendiente")

    # las filas se mezclan para que el orden no ayude al motor
    rng.shuffle(banco)
    rng.shuffle(doc)

    with (destino / "banco.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id_mov", "fecha_valor", "monto", "referencia", "descripcion"])
        for r in banco:
            w.writerow([r["id_mov"], r["fecha_valor"].isoformat(), _fmt_monto_banco(rng, r["monto"]),
                        r["referencia"], r["descripcion"]])

    wb = Workbook()
    ws = wb.active
    ws.title = "registro"
    ws.append(["id_doc", "fecha_contable", "monto", "referencia", "cliente"])
    for r in doc:
        ws.append([r["id_doc"], r["fecha_contable"], r["monto"] / 100, r["referencia"], r["cliente"]])
    wb.save(destino / "contable.xlsx")

    with (destino / "verdad_terreno.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["lado", "id", "contraparte", "caso", "esperado"])
        w.writeheader()
        w.writerows(sorted(verdad, key=lambda x: (x["lado"], x["id"])))

    return {"banco": len(banco), "contable": len(doc), "destino": destino}


if __name__ == "__main__":
    r = generar()
    print(f"Datos sintéticos generados: {r['banco']} movimientos bancarios y {r['contable']} registros contables")
