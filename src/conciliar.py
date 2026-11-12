"""Corrida de conciliación.

Uso:
  python src/conciliar.py                      # usa datos/banco.csv y datos/contable.xlsx
  python src/conciliar.py --dry-run            # calcula y muestra el resumen sin escribir nada
  python src/conciliar.py --banco a.csv --contable b.xlsx

Los parámetros se leen de variables de entorno CONC_* (ver src/config.py).
Código de salida: 0 bien, 2 entrada o configuración inválida, 1 error al procesar.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auditoria  # noqa: E402
import motor  # noqa: E402
import reporte  # noqa: E402
import tiempos  # noqa: E402
from cargar import cargar  # noqa: E402
from comun import ErrorDeEntrada, con_reintentos, sha256_archivo  # noqa: E402
from config import Config, ErrorDeConfiguracion  # noqa: E402

log = logging.getLogger("conciliacion.corrida")


def _dinero(centavos: int) -> str:
    return f"{centavos / 100:,.2f}"


def ejecutar(banco_ruta: Path, contable_ruta: Path, cfg: Config, dry_run: bool = False) -> dict:
    bitacora: list[tuple[str, str, str]] = []

    def evento(nivel: str, msg: str):
        bitacora.append((datetime.now(timezone.utc).isoformat(timespec="seconds"), nivel, msg))
        getattr(log, nivel.lower())(msg)

    banco_ruta, contable_ruta = Path(banco_ruta), Path(contable_ruta)
    for r in (banco_ruta, contable_ruta):
        if not r.is_file():
            raise FileNotFoundError("archivo de entrada no encontrado")

    sha_b = con_reintentos(lambda: sha256_archivo(banco_ruta), cfg.reintentos, cfg.espera_seg, log=log)
    sha_c = con_reintentos(lambda: sha256_archivo(contable_ruta), cfg.reintentos, cfg.espera_seg, log=log)
    sha_cfg = auditoria.huella_config(cfg)
    clave = auditoria.clave_ejecucion(sha_b, sha_c, sha_cfg)
    salida = cfg.dir_salidas / f"conciliacion_{clave[:16]}.xlsx"

    if not dry_run:
        previa = auditoria.buscar(cfg.dir_auditoria, clave)
        if previa and salida.is_file() and sha256_archivo(salida) == previa["salida"]["sha256"]:
            log.info("Estas entradas y reglas ya se procesaron (corrida %s); no se hace nada", clave[:12])
            return {"estado": "omitida", "clave": clave, "salida": salida}

    evento("INFO", f"Inicio de corrida {clave[:12]} ({'ensayo' if dry_run else 'real'})")
    t0 = time.perf_counter()
    cb = cargar(banco_ruta, "banco", cfg)
    cc = cargar(contable_ruta, "contable", cfg)
    for nombre, c in (("banco", cb), ("contable", cc)):
        evento("INFO", f"Fuente {nombre}: {c.filas_leidas} filas leídas, {len(c.rechazadas)} rechazadas")
        for fila, motivo in c.rechazadas[:50]:
            evento("WARNING", f"Fuente {nombre} rechazó: {motivo}")
    res = motor.conciliar(cb.partidas, cc.partidas, cfg)
    seg = time.perf_counter() - t0

    por_regla_c = Counter(c.regla for c in res.conciliadas)
    por_regla_r = Counter(c.regla for c in res.revision)
    pb = {p.id: p for p in cb.partidas}
    pd_ = {p.id: p for p in cc.partidas}
    m_conc = sum(pb[i].monto for c in res.conciliadas for i in c.ids_banco)
    m_rev = sum(pb[i].monto for c in res.revision for i in c.ids_banco)
    m_pb = sum(p.monto for p in res.pend_banco)
    m_pd = sum(p.monto for p in res.pend_doc)
    n_part = len(cb.partidas) + len(cc.partidas)
    est = tiempos.estimar(n_part, len(res.revision), seg, cfg)

    resumen = {
        "Datos sintéticos y genéricos; no corresponden a ninguna institución": "",
        "Corrida": clave[:12],
        "Modo": "ensayo (sin escritura)" if dry_run else "real",
        "Entradas": "",
        "Movimientos bancarios (válidos / rechazados)": f"{len(cb.partidas)} / {len(cb.rechazadas)}",
        "Registros contables (válidos / rechazados)": f"{len(cc.partidas)} / {len(cc.rechazadas)}",
        "SHA-256 del archivo bancario": sha_b,
        "SHA-256 del archivo contable": sha_c,
        "Resultados": "",
        "Conciliadas automáticamente (grupos)": len(res.conciliadas),
        "En cola de revisión humana": len(res.revision),
        "Movimientos bancarios pendientes": len(res.pend_banco),
        "Registros contables pendientes": len(res.pend_doc),
        "Monto bancario conciliado": _dinero(m_conc),
        "Monto bancario en revisión": _dinero(m_rev),
        "Monto bancario pendiente": _dinero(m_pb),
        "Monto contable pendiente": _dinero(m_pd),
        "Conciliadas por regla": ", ".join(f"{k}: {v}" for k, v in sorted(por_regla_c.items())) or "ninguna",
        "En revisión por regla": ", ".join(f"{k}: {v}" for k, v in sorted(por_regla_r.items())) or "ninguna",
        "Reglas aplicadas": "",
        "Tolerancia de monto": _dinero(cfg.tol_monto_centavos),
        "Tolerancia de fecha (días)": cfg.tol_dias,
        "Ventana de agrupación (días)": cfg.dias_grupo,
        "Umbral automático / revisión": f"{cfg.umbral_auto} / {cfg.umbral_revision}",
        "Tiempo (supuestos declarados, no mediciones de un proceso real)": "",
        "Supuesto: minutos manuales por partida": est["supuesto_min_manual_por_partida"],
        "Supuesto: minutos de revisión por caso en cola": est["supuesto_min_revision_por_caso"],
        "Manual estimado (min)": est["manual_estimado_min"],
        "Motor, tiempo medido (s)": est["motor_medido_seg"],
        "Automatizado estimado con revisión (min)": est["automatizado_estimado_min"],
    }
    evento("INFO", f"Resultado: {len(res.conciliadas)} conciliadas, {len(res.revision)} en revisión, "
                   f"{len(res.pend_banco)} + {len(res.pend_doc)} pendientes")

    out = {"estado": "ensayo" if dry_run else "ejecutada", "clave": clave, "resumen": resumen,
           "resultado": res, "tiempos": est, "salida": salida, "rechazadas": len(cb.rechazadas) + len(cc.rechazadas)}
    if dry_run:
        evento("INFO", "Ensayo: no se escribió reporte ni registro de auditoría")
        return out

    wb = reporte.construir(res, cb.partidas, cc.partidas, resumen, bitacora)
    reporte.guardar_atomico(wb, salida, cfg.reintentos, cfg.espera_seg, log=log)
    sha_salida = sha256_archivo(salida)
    auditoria.registrar(cfg.dir_auditoria, {
        "clave_ejecucion": clave,
        "modo": "real",
        "entradas": [
            {"rol": "banco", "archivo": banco_ruta.name, "bytes": banco_ruta.stat().st_size,
             "sha256": sha_b, "filas": cb.filas_leidas, "rechazadas": len(cb.rechazadas)},
            {"rol": "contable", "archivo": contable_ruta.name, "bytes": contable_ruta.stat().st_size,
             "sha256": sha_c, "filas": cc.filas_leidas, "rechazadas": len(cc.rechazadas)},
        ],
        "sha256_reglas": sha_cfg,
        "reglas": cfg.huella_reglas(),
        "salida": {"archivo": salida.name, "sha256": sha_salida},
        "conteo": {"conciliadas": len(res.conciliadas), "revision": len(res.revision),
                   "pendientes_banco": len(res.pend_banco), "pendientes_contable": len(res.pend_doc)},
    }, cfg, log=log)
    log.info("Reporte %s escrito y auditoría registrada", salida.name)
    return out


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description="Conciliación de pagos (datos sintéticos)")
    ap.add_argument("--banco", type=Path)
    ap.add_argument("--contable", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="calcula sin escribir reporte ni auditoría")
    a = ap.parse_args(argv)
    try:
        cfg = Config.desde_entorno()
        banco = a.banco or cfg.dir_datos / "banco.csv"
        contable = a.contable or cfg.dir_datos / "contable.xlsx"
        r = ejecutar(banco, contable, cfg, dry_run=a.dry_run)
    except (ErrorDeEntrada, ErrorDeConfiguracion) as e:
        log.error("Entrada o configuración inválida: %s", e)
        return 2
    except FileNotFoundError:
        log.error("Archivo de entrada no encontrado")
        return 2
    except OSError as e:
        log.error("Error de archivo tras los reintentos: %s", e.strerror or type(e).__name__)
        return 1
    except Exception as e:  # noqa: BLE001 - se registra solo el tipo para no filtrar datos
        log.error("Error inesperado: %s", type(e).__name__)
        return 1
    if r["estado"] == "ensayo":
        for k, v in r["resumen"].items():
            if v != "":
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
