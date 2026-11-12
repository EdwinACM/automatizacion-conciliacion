"""Utilidades compartidas: conversión de montos y fechas, normalización de referencias,
hash de archivos, reintentos acotados y saneamiento de celdas para Excel."""
from __future__ import annotations

import hashlib
import math
import re
import time
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path


class ErrorDeEntrada(ValueError):
    """Entrada inválida. Los mensajes no incluyen valores de los datos ni rutas."""


# ---------- montos y fechas ----------

def a_centavos(valor) -> int:
    """Convierte a centavos enteros. Acepta '$1,234.50', números y Decimal."""
    if valor is None or isinstance(valor, bool):
        raise ErrorDeEntrada("monto vacío o de tipo no válido")
    if isinstance(valor, float):
        if not math.isfinite(valor):
            raise ErrorDeEntrada("monto no finito")
        texto = repr(valor)
    else:
        texto = str(valor)
    texto = texto.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not texto:
        raise ErrorDeEntrada("monto vacío")
    try:
        d = Decimal(texto)
    except InvalidOperation:
        raise ErrorDeEntrada("monto no numérico") from None
    if not d.is_finite() or abs(d) > Decimal("1e12"):
        raise ErrorDeEntrada("monto fuera de rango")
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


_FECHA_DMY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def a_fecha(valor) -> date:
    """Acepta date, datetime, 'AAAA-MM-DD' y 'DD/MM/AAAA'."""
    if isinstance(valor, datetime):
        resultado = valor.date()
    elif isinstance(valor, date):
        resultado = valor
    elif isinstance(valor, str):
        texto = valor.strip()
        try:
            m = _FECHA_DMY.match(texto)
            resultado = (date(int(m[3]), int(m[2]), int(m[1])) if m
                         else date.fromisoformat(texto[:10]))
        except ValueError:
            raise ErrorDeEntrada("fecha con formato no válido") from None
    else:
        raise ErrorDeEntrada("fecha vacía o de tipo no válido")
    if not 2000 <= resultado.year <= 2100:
        raise ErrorDeEntrada("fecha fuera de rango")
    return resultado


# ---------- referencias ----------

_RUIDO = {"REF", "REFERENCIA", "FAC", "FACT", "FACTURA", "PAGO", "PGO", "NO", "NUM",
          "TRANSFERENCIA", "ABONO", "DEPOSITO"}
_CLIENTE = re.compile(r"CLI\s*-?\s*(\d{1,6})")
_LOTE = re.compile(r"LOTE\s*-?\s*\d+")


def _ascii_mayus(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    return texto.encode("ascii", "ignore").decode("ascii").upper()


def extraer_cliente(texto) -> str | None:
    """Devuelve el código de cliente normalizado (CLI0042) si aparece en el texto."""
    if texto is None:
        return None
    m = _CLIENTE.search(_ascii_mayus(texto))
    return f"CLI{int(m[1]):04d}" if m else None


def normalizar_ref(texto) -> str:
    """Quita prefijos, separadores, mayúsculas y ceros a la izquierda.
    'fac-0001234 ' y 'REF. 1234' dan '1234'. Sin dígitos, deja las letras que no sean ruido."""
    if texto is None:
        return ""
    t = _ascii_mayus(texto)
    t = _CLIENTE.sub(" ", t)
    t = _LOTE.sub(" ", t)
    corridas = re.findall(r"\d+", t)
    if corridas:
        return max(corridas, key=len).lstrip("0") or "0"
    palabras = [p for p in re.findall(r"[A-Z]+", t) if p not in _RUIDO]
    return "".join(palabras)


# ---------- archivos ----------

def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with Path(ruta).open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ---------- reintentos ----------

def con_reintentos(fn, intentos=3, espera=0.5, dormir=time.sleep, log=None):
    """Ejecuta fn() hasta `intentos` veces ante OSError transitorios (con espera exponencial
    topada a 5 s). Un archivo inexistente o un error de validación no se reintenta."""
    intentos = max(1, min(int(intentos), 5))
    for n in range(1, intentos + 1):
        try:
            return fn()
        except FileNotFoundError:
            raise
        except OSError as e:
            if n == intentos:
                raise
            if log:
                log.warning("Intento %d de %d falló (%s); se reintenta", n, intentos, type(e).__name__)
            dormir(min(espera * 2 ** (n - 1), 5.0))


# ---------- Excel ----------

_PREFIJOS_PELIGROSOS = ("=", "+", "-", "@")


def celda_segura(valor):
    """Evita inyección de fórmulas: texto que empieza con = + - @ (o control) se prefija con '."""
    if isinstance(valor, str):
        inicio = valor.lstrip(" ")[:1]
        if inicio in _PREFIJOS_PELIGROSOS or inicio in ("\t", "\r", "\n") or valor[:1] in ("\t", "\r", "\n"):
            return "'" + valor
    return valor
