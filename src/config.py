"""Configuración del motor. Todo se lee de variables de entorno con valores por defecto."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


class ErrorDeConfiguracion(ValueError):
    pass


def _entero(env, nombre, defecto, minimo, maximo):
    crudo = env.get(nombre, str(defecto))
    try:
        valor = int(crudo)
    except ValueError:
        raise ErrorDeConfiguracion(f"{nombre} debe ser un entero") from None
    if not minimo <= valor <= maximo:
        raise ErrorDeConfiguracion(f"{nombre} debe estar entre {minimo} y {maximo}")
    return valor


def _decimal(env, nombre, defecto, minimo, maximo):
    crudo = env.get(nombre, str(defecto))
    try:
        valor = Decimal(crudo)
    except InvalidOperation:
        raise ErrorDeConfiguracion(f"{nombre} debe ser un número") from None
    if not valor.is_finite() or not Decimal(minimo) <= valor <= Decimal(maximo):
        raise ErrorDeConfiguracion(f"{nombre} debe estar entre {minimo} y {maximo}")
    return valor


@dataclass(frozen=True)
class Config:
    tol_monto_centavos: int = 10      # diferencia de monto aceptada (0.10)
    tol_dias: int = 3                 # diferencia de fecha aceptada en reglas uno a uno
    dias_grupo: int = 5               # ventana de fechas para agrupar uno a muchos
    umbral_auto: float = 0.85         # desde aquí se concilia sin revisión humana
    umbral_revision: float = 0.50     # entre este y el anterior va a la cola de revisión
    max_candidatos_grupo: int = 12    # tope de documentos que se combinan por pago
    max_docs_grupo: int = 5           # tope de documentos por pago
    reintentos: int = 3
    espera_seg: float = 0.5
    max_filas: int = 100_000
    max_mb: int = 20
    min_manual_por_partida: float = 1.5      # supuesto, ver docs/bitacora.md
    min_revision_por_caso: float = 3.0       # supuesto, ver docs/bitacora.md
    dir_datos: Path = RAIZ / "datos"
    dir_salidas: Path = RAIZ / "salidas"
    dir_auditoria: Path = RAIZ / "auditoria"

    @classmethod
    def desde_entorno(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        tol = _decimal(env, "CONC_TOL_MONTO", "0.10", "0", "5")
        auto = float(_decimal(env, "CONC_UMBRAL_AUTO", "0.85", "0.01", "1"))
        rev = float(_decimal(env, "CONC_UMBRAL_REVISION", "0.50", "0.01", "1"))
        if rev > auto:
            raise ErrorDeConfiguracion("CONC_UMBRAL_REVISION no puede superar a CONC_UMBRAL_AUTO")
        return cls(
            tol_monto_centavos=int(tol * 100),
            tol_dias=_entero(env, "CONC_TOL_DIAS", 3, 0, 10),
            dias_grupo=_entero(env, "CONC_DIAS_GRUPO", 5, 0, 30),
            umbral_auto=auto,
            umbral_revision=rev,
            max_candidatos_grupo=_entero(env, "CONC_MAX_CANDIDATOS", 12, 2, 16),
            max_docs_grupo=_entero(env, "CONC_MAX_DOCS_GRUPO", 5, 2, 8),
            reintentos=_entero(env, "CONC_REINTENTOS", 3, 1, 5),
            espera_seg=float(_decimal(env, "CONC_ESPERA_SEG", "0.5", "0", "5")),
            max_filas=_entero(env, "CONC_MAX_FILAS", 100_000, 1, 1_000_000),
            max_mb=_entero(env, "CONC_MAX_MB", 20, 1, 200),
            dir_datos=Path(env.get("CONC_DIR_DATOS", RAIZ / "datos")),
            dir_salidas=Path(env.get("CONC_DIR_SALIDAS", RAIZ / "salidas")),
            dir_auditoria=Path(env.get("CONC_DIR_AUDITORIA", RAIZ / "auditoria")),
        )

    def huella_reglas(self) -> dict:
        """Parámetros que cambian el resultado; entran en la clave de idempotencia."""
        return {
            "tol_monto_centavos": self.tol_monto_centavos,
            "tol_dias": self.tol_dias,
            "dias_grupo": self.dias_grupo,
            "umbral_auto": self.umbral_auto,
            "umbral_revision": self.umbral_revision,
            "max_candidatos_grupo": self.max_candidatos_grupo,
            "max_docs_grupo": self.max_docs_grupo,
        }
