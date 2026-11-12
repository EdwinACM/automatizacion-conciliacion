"""Un solo comando: genera los datos sintéticos, concilia, evalúa y verifica la auditoría."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auditoria  # noqa: E402
import conciliar  # noqa: E402
import evaluar  # noqa: E402
import generar_datos  # noqa: E402
from config import Config  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
    cfg = Config.desde_entorno()
    print("\n=== 1. Datos sintéticos ===")
    g = generar_datos.generar(cfg.dir_datos)
    print(f"{g['banco']} movimientos bancarios y {g['contable']} registros contables")
    banco, contable = cfg.dir_datos / "banco.csv", cfg.dir_datos / "contable.xlsx"
    print("\n=== 2. Ensayo (sin escribir) ===")
    conciliar.ejecutar(banco, contable, cfg, dry_run=True)
    print("\n=== 3. Corrida real ===")
    r = conciliar.ejecutar(banco, contable, cfg)
    print("\n=== 4. Segunda corrida (debe omitirse) ===")
    r2 = conciliar.ejecutar(banco, contable, cfg)
    print(f"Estado de la segunda corrida: {r2['estado']}")
    print("\n=== 5. Evaluación y auditoría ===")
    e = evaluar.evaluar(cfg, banco, contable, cfg.dir_datos / "verdad_terreno.csv")
    print(f"{e['coinciden']} de {e['partidas_evaluadas']} partidas con el resultado esperado; "
          f"conciliaciones automáticas incorrectas: {e['falsos_automaticos']}")
    for f in e["fallos"]:
        print("  diferencia:", *f)
    print("Auditoría:", auditoria.verificar_cadena(cfg.dir_auditoria)[1])
    if "tiempos" in r:
        t = r["tiempos"]
        print(f"Tiempo: manual estimado {t['manual_estimado_min']} min (supuesto), motor medido {t['motor_medido_seg']} s, "
              f"automatizado estimado con revisión {t['automatizado_estimado_min']} min (supuesto)")
