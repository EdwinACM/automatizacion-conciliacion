import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cargar import Partida  # noqa: E402
from comun import normalizar_ref  # noqa: E402
from config import Config  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    return Config(dir_datos=tmp_path / "datos", dir_salidas=tmp_path / "salidas",
                  dir_auditoria=tmp_path / "auditoria", espera_seg=0.0)


def P(lado, ident, monto, dia=10, ref="FAC-1234", cliente=None):
    """Partida de prueba; monto en pesos con decimales."""
    return Partida(lado, ident, date(2026, 10, dia), round(monto * 100), ref, normalizar_ref(ref), cliente)


@pytest.fixture
def mk():
    return P
