"""Compara el resultado del motor con la verdad de terreno del generador."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cargar import cargar  # noqa: E402
from config import Config  # noqa: E402
import motor  # noqa: E402


def evaluar(cfg: Config, banco: Path, contable: Path, verdad: Path) -> dict:
    res = motor.conciliar(cargar(banco, "banco", cfg).partidas, cargar(contable, "contable", cfg).partidas, cfg)
    estado_b = {i: "conciliada" for c in res.conciliadas for i in c.ids_banco}
    estado_b.update({i: "revision" for c in res.revision for i in c.ids_banco})
    pend_d = {p.id for p in res.pend_doc}
    docs_conc = {i for c in res.conciliadas for i in c.ids_doc}
    with Path(verdad).open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    total = ok = 0
    fallos = []
    falsos_auto = 0
    for r in filas:
        if r["lado"] == "banco":
            obtenido = estado_b.get(r["id"], "pendiente")
            esperado = r["esperado"]
            if obtenido == "conciliada" and esperado != "conciliada":
                falsos_auto += 1
        else:
            if r["esperado"] == "conciliada_por_revision":
                continue
            obtenido = "conciliada" if r["id"] in docs_conc else ("pendiente" if r["id"] in pend_d else "revision")
            esperado = r["esperado"]
            if esperado == "pendiente":
                obtenido = "pendiente" if r["id"] in pend_d else obtenido
        total += 1
        if obtenido == esperado:
            ok += 1
        else:
            fallos.append((r["lado"], r["id"], r["caso"], esperado, obtenido))
    return {"partidas_evaluadas": total, "coinciden": ok, "falsos_automaticos": falsos_auto, "fallos": fallos}


if __name__ == "__main__":
    cfg = Config.desde_entorno()
    r = evaluar(cfg, cfg.dir_datos / "banco.csv", cfg.dir_datos / "contable.xlsx", cfg.dir_datos / "verdad_terreno.csv")
    print(f"Evaluación contra la verdad de terreno: {r['coinciden']} de {r['partidas_evaluadas']} partidas "
          f"con el resultado esperado; conciliaciones automáticas incorrectas: {r['falsos_automaticos']}")
    for f in r["fallos"]:
        print("  diferencia:", *f)
