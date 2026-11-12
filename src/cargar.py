"""Lectura y validación de las dos fuentes. Las filas inválidas se rechazan y se cuentan;
los mensajes dicen fila y columna, nunca el valor."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from comun import ErrorDeEntrada, a_centavos, a_fecha, con_reintentos, extraer_cliente, normalizar_ref
from config import Config

EXTENSIONES = {".csv", ".xlsx"}
COLUMNAS_BANCO = ["id_mov", "fecha_valor", "monto", "referencia", "descripcion"]
COLUMNAS_CONTABLE = ["id_doc", "fecha_contable", "monto", "referencia", "cliente"]
MAX_LARGO_TEXTO = 200


@dataclass(frozen=True)
class Partida:
    lado: str                 # "banco" o "contable"
    id: str
    fecha: date
    monto: int                # centavos
    ref_original: str
    ref_norm: str
    cliente: str | None

    @property
    def clave_equivalencia(self):
        """Dos partidas con la misma clave son intercambiables para el motor."""
        return (self.ref_norm, self.monto, self.fecha, self.cliente)


@dataclass
class Carga:
    partidas: list[Partida]
    rechazadas: list[tuple[int, str]] = field(default_factory=list)   # (fila, motivo)
    filas_leidas: int = 0


def _leer_crudo(ruta: Path, cfg: Config) -> pd.DataFrame:
    ruta = Path(ruta)
    if ruta.suffix.lower() not in EXTENSIONES:
        raise ErrorDeEntrada("extensión no permitida (solo .csv y .xlsx)")
    if not ruta.is_file():
        raise FileNotFoundError("archivo de entrada no encontrado")
    if ruta.stat().st_size > cfg.max_mb * 1024 * 1024:
        raise ErrorDeEntrada(f"archivo mayor a {cfg.max_mb} MB")

    def leer():
        if ruta.suffix.lower() == ".csv":
            return pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="utf-8-sig",
                               nrows=cfg.max_filas + 1)
        return pd.read_excel(ruta, engine="openpyxl", dtype=object, nrows=cfg.max_filas + 1)

    try:
        df = con_reintentos(leer, cfg.reintentos, cfg.espera_seg)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError, KeyError) as e:
        raise ErrorDeEntrada(f"no se pudo interpretar el archivo ({type(e).__name__})") from None
    if len(df) > cfg.max_filas:
        raise ErrorDeEntrada(f"el archivo supera {cfg.max_filas} filas")
    return df


def _texto(valor) -> str:
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    return str(valor).strip()[:MAX_LARGO_TEXTO]


def cargar(ruta: Path, lado: str, cfg: Config) -> Carga:
    if lado == "banco":
        cols, c_id, c_fecha = COLUMNAS_BANCO, "id_mov", "fecha_valor"
    elif lado == "contable":
        cols, c_id, c_fecha = COLUMNAS_CONTABLE, "id_doc", "fecha_contable"
    else:
        raise ValueError("lado desconocido")

    df = _leer_crudo(ruta, cfg)
    df.columns = [str(c).strip().lower() for c in df.columns]
    faltan = [c for c in cols if c not in df.columns]
    if faltan:
        raise ErrorDeEntrada(f"faltan columnas en la fuente {lado}: {', '.join(faltan)}")

    carga = Carga(partidas=[], filas_leidas=len(df))
    vistos: set[str] = set()
    for pos, fila in enumerate(df.to_dict("records"), start=2):   # fila 1 es el encabezado
        fila = {k: (None if (not isinstance(v, str) and pd.isna(v)) else v) for k, v in fila.items()}
        try:
            ident = _texto(fila[c_id])
            if not ident:
                raise ErrorDeEntrada(f"fila {pos}: identificador vacío")
            if ident in vistos:
                raise ErrorDeEntrada(f"fila {pos}: identificador repetido")
            try:
                fecha = a_fecha(fila[c_fecha])
                monto = a_centavos(fila["monto"])
            except ErrorDeEntrada as e:
                raise ErrorDeEntrada(f"fila {pos}: {e}") from None
            if monto <= 0:
                raise ErrorDeEntrada(f"fila {pos}: el monto debe ser positivo")
            ref = _texto(fila["referencia"])
            if lado == "banco":
                cliente = extraer_cliente(f"{ref} {_texto(fila['descripcion'])}")
            else:
                cliente = extraer_cliente(_texto(fila["cliente"]))
            vistos.add(ident)
            carga.partidas.append(Partida(lado, ident, fecha, monto, ref, normalizar_ref(ref), cliente))
        except ErrorDeEntrada as e:
            carga.rechazadas.append((pos, str(e)))

    if carga.filas_leidas and len(carga.rechazadas) > carga.filas_leidas // 2:
        raise ErrorDeEntrada(f"más de la mitad de las filas de {lado} son inválidas")
    return carga
