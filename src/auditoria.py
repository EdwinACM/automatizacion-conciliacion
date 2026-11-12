"""Registro de auditoría: una línea JSON por corrida real, encadenada con hash.

Cada línea guarda el SHA-256 de los archivos de entrada (solo nombre, nunca la ruta),
el de la configuración de reglas, el del reporte generado y el hash de la línea anterior.
Si alguien edita o borra una línea intermedia, `verificar_cadena` lo detecta.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from comun import con_reintentos, sha256_texto

NOMBRE = "registro_auditoria.jsonl"
VERSION_ESQUEMA = 1


def _canonico(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def leer(dir_auditoria: Path) -> list[dict]:
    ruta = Path(dir_auditoria) / NOMBRE
    if not ruta.is_file():
        return []
    with ruta.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def huella_config(cfg) -> str:
    return sha256_texto(_canonico(cfg.huella_reglas()))


def clave_ejecucion(sha_banco: str, sha_contable: str, sha_config: str) -> str:
    return sha256_texto(f"{sha_banco}|{sha_contable}|{sha_config}|v{VERSION_ESQUEMA}")


def buscar(dir_auditoria: Path, clave: str) -> dict | None:
    for e in reversed(leer(dir_auditoria)):
        if e.get("clave_ejecucion") == clave:
            return e
    return None


def registrar(dir_auditoria: Path, entrada: dict, cfg, log=None) -> dict:
    dir_auditoria = Path(dir_auditoria)
    previas = leer(dir_auditoria)
    registro = dict(entrada)
    registro["version_esquema"] = VERSION_ESQUEMA
    registro["marca_tiempo"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    registro["secuencia"] = len(previas) + 1
    registro["hash_previo"] = previas[-1]["hash_entrada"] if previas else "0" * 64
    registro["hash_entrada"] = sha256_texto(_canonico(registro))

    def escribir():
        dir_auditoria.mkdir(parents=True, exist_ok=True)
        with (dir_auditoria / NOMBRE).open("a", encoding="utf-8") as f:
            f.write(_canonico(registro) + "\n")

    con_reintentos(escribir, cfg.reintentos, cfg.espera_seg, log=log)
    return registro


def verificar_cadena(dir_auditoria: Path) -> tuple[bool, str]:
    previo = "0" * 64
    for n, e in enumerate(leer(dir_auditoria), start=1):
        h = e.get("hash_entrada")
        cuerpo = {k: v for k, v in e.items() if k != "hash_entrada"}
        if e.get("secuencia") != n or e.get("hash_previo") != previo or sha256_texto(_canonico(cuerpo)) != h:
            return False, f"la entrada {n} no coincide con su hash"
        previo = h
    return True, "cadena íntegra"
