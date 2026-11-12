from datetime import date, datetime

import pytest

from comun import (ErrorDeEntrada, a_centavos, a_fecha, celda_segura, con_reintentos,
                   extraer_cliente, normalizar_ref, sha256_archivo)


@pytest.mark.parametrize("valor,esperado", [
    ("1234.50", 123450), ("$1,234.50", 123450), (10, 1000), (0.1 + 0.2, 30), (" 5 ", 500),
    ("100.005", 10001), ("-3.00", -300),
])
def test_a_centavos_validos(valor, esperado):
    assert a_centavos(valor) == esperado


@pytest.mark.parametrize("valor", [None, "", "abc", float("nan"), float("inf"), True, "1e15", "NaN"])
def test_a_centavos_invalidos(valor):
    with pytest.raises(ErrorDeEntrada):
        a_centavos(valor)


def test_a_fecha_formatos():
    assert a_fecha("2026-10-05") == date(2026, 10, 5)
    assert a_fecha("05/10/2026") == date(2026, 10, 5)
    assert a_fecha(datetime(2026, 10, 5, 13, 0)) == date(2026, 10, 5)


@pytest.mark.parametrize("valor", [None, "", "31/02/2026", "ayer", "1999-01-01", 20261005])
def test_a_fecha_invalidas(valor):
    with pytest.raises(ErrorDeEntrada):
        a_fecha(valor)


@pytest.mark.parametrize("sucia", ["fac-0001234 ", "REF. 0001234", "Pago FAC 1234", "FAC–0001234",
                                   " 0001234", "fact 0001234", "FAC-0001234."])
def test_normaliza_referencias_sucias(sucia):
    assert normalizar_ref(sucia) == normalizar_ref("FAC-0001234") == "1234"


def test_normaliza_casos_borde():
    assert normalizar_ref(None) == ""
    assert normalizar_ref("") == ""
    assert normalizar_ref("PAGO CLI0007 LOTE 12") == ""
    assert normalizar_ref("0000") == "0"
    assert normalizar_ref("ref abc") == "ABC"


def test_extraer_cliente():
    assert extraer_cliente("PAGO cli-7 LOTE 3") == "CLI0007"
    assert extraer_cliente("sin cliente") is None
    assert extraer_cliente(None) is None


@pytest.mark.parametrize("texto", ["=1+1", "+cmd", "-2+3", "@SUMA(A1)", " =HOLA", "\t=x"])
def test_celda_segura_prefija(texto):
    assert celda_segura(texto).startswith("'")


def test_celda_segura_no_toca_lo_normal():
    assert celda_segura("FAC-1") == "FAC-1"
    assert celda_segura(-5.0) == -5.0
    assert celda_segura(None) is None


def test_reintentos_se_recupera():
    llamadas = []

    def fn():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise PermissionError("bloqueado")
        return "ok"

    esperas = []
    assert con_reintentos(fn, intentos=3, espera=0.5, dormir=esperas.append) == "ok"
    assert len(llamadas) == 3
    assert esperas == [0.5, 1.0]


def test_reintentos_acotados():
    llamadas = []

    def fn():
        llamadas.append(1)
        raise OSError("falla")

    with pytest.raises(OSError):
        con_reintentos(fn, intentos=99, espera=0, dormir=lambda s: None)
    assert len(llamadas) == 5          # el tope duro es 5


def test_reintentos_no_repite_archivo_inexistente_ni_validacion():
    n = []

    def falta():
        n.append(1)
        raise FileNotFoundError

    with pytest.raises(FileNotFoundError):
        con_reintentos(falta, intentos=3, dormir=lambda s: None)
    assert len(n) == 1

    def invalido():
        n.append(1)
        raise ErrorDeEntrada("x")

    with pytest.raises(ErrorDeEntrada):
        con_reintentos(invalido, intentos=3, dormir=lambda s: None)
    assert len(n) == 2


def test_sha256(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"abc")
    assert sha256_archivo(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
