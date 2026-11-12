import dataclasses
import json
import logging

import pytest
from openpyxl import Workbook, load_workbook

import auditoria
import conciliar
import evaluar
import generar_datos
import tiempos
from cargar import cargar
from comun import ErrorDeEntrada
from config import Config, ErrorDeConfiguracion


@pytest.fixture
def datos(tmp_path):
    d = tmp_path / "datos"
    generar_datos.generar(d)
    return d


# ---------- carga ----------

def _csv(ruta, filas, enc="id_mov,fecha_valor,monto,referencia,descripcion"):
    ruta.write_text(enc + "\n" + "\n".join(filas) + "\n", encoding="utf-8")
    return ruta


def test_carga_rechaza_filas_malas_sin_filtrar_valores(tmp_path, cfg):
    f = _csv(tmp_path / "b.csv", [
        "M1,2026-10-01,100.00,FAC-1,x",
        "M1,2026-10-01,100.00,FAC-1,x",        # id repetido
        ",2026-10-01,100.00,FAC-2,x",           # id vacío
        "M3,no-es-fecha,100.00,FAC-3,x",
        "M4,2026-10-01,SECRETO,FAC-4,x",
        "M5,2026-10-01,-5.00,FAC-5,x",
        "M6,2026-10-02,10.00,FAC-6,x",
        "M7,2026-10-02,10.00,FAC-7,x", "M8,2026-10-02,10.00,FAC-8,x", "M9,2026-10-02,10.00,FAC-9,x",
    ])
    c = cargar(f, "banco", dataclasses.replace(cfg))
    assert [p.id for p in c.partidas] == ["M1", "M6", "M7", "M8", "M9"]
    assert len(c.rechazadas) == 5
    assert all("SECRETO" not in m and "no-es-fecha" not in m for _, m in c.rechazadas)


def test_carga_columnas_faltantes(tmp_path, cfg):
    f = tmp_path / "b.csv"
    f.write_text("id_mov,monto\nM1,10\n", encoding="utf-8")
    with pytest.raises(ErrorDeEntrada, match="faltan columnas"):
        cargar(f, "banco", cfg)


def test_carga_extension_y_tamano_y_filas(tmp_path, cfg):
    malo = tmp_path / "b.txt"
    malo.write_text("x")
    with pytest.raises(ErrorDeEntrada, match="extensión"):
        cargar(malo, "banco", cfg)
    f = _csv(tmp_path / "b.csv", ["M1,2026-10-01,1,A,x", "M2,2026-10-01,1,A,x", "M3,2026-10-01,1,A,x"])
    with pytest.raises(ErrorDeEntrada, match="supera"):
        cargar(f, "banco", dataclasses.replace(cfg, max_filas=2))
    with pytest.raises(ErrorDeEntrada, match="MB"):
        cargar(f, "banco", dataclasses.replace(cfg, max_mb=0))
    with pytest.raises(FileNotFoundError):
        cargar(tmp_path / "no.csv", "banco", cfg)


def test_carga_mayoria_invalida_falla(tmp_path, cfg):
    f = _csv(tmp_path / "b.csv", ["M1,x,1,A,x", "M2,x,1,A,x", "M3,2026-10-01,1,A,x"])
    with pytest.raises(ErrorDeEntrada, match="más de la mitad"):
        cargar(f, "banco", cfg)


def test_carga_excel_con_celdas_vacias(tmp_path, cfg):
    wb = Workbook()
    ws = wb.active
    ws.append(["id_doc", "fecha_contable", "monto", "referencia", "cliente"])
    ws.append(["D1", None, 10, "FAC-1", "CLI0001"])
    ws.append(["D2", "2026-10-03", 10.5, None, None])
    ruta = tmp_path / "c.xlsx"
    wb.save(ruta)
    c = cargar(ruta, "contable", cfg)
    assert [p.id for p in c.partidas] == ["D2"] and len(c.rechazadas) == 1
    assert c.partidas[0].monto == 1050 and c.partidas[0].ref_norm == ""


# ---------- generador y evaluación ----------

def test_generador_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generar_datos.generar(a)
    generar_datos.generar(b)
    for n in ("banco.csv", "verdad_terreno.csv"):
        assert (a / n).read_bytes() == (b / n).read_bytes()
    ca, cb = (cargar(x / "contable.xlsx", "contable", Config()).partidas for x in (a, b))
    assert ca == cb


def test_evaluacion_contra_verdad_de_terreno(datos, cfg):
    e = evaluar.evaluar(cfg, datos / "banco.csv", datos / "contable.xlsx", datos / "verdad_terreno.csv")
    assert e["falsos_automaticos"] == 0
    assert e["fallos"] == [] and e["coinciden"] == e["partidas_evaluadas"]


def test_cada_caso_del_generador_aparece_en_los_datos(datos):
    casos = {l.split(",")[3] for l in (datos / "verdad_terreno.csv").read_text().splitlines()[1:]}
    esperados = {"exacta", "referencia_sucia", "redondeo", "fecha_desfasada", "limite_tolerancias",
                 "duplicado_original", "duplicado_copia", "uno_a_muchos", "uno_a_muchos_ambiguo",
                 "sin_referencia", "sin_referencia_ambiguo", "solo_banco", "solo_contable"}
    assert esperados <= casos


# ---------- corrida completa ----------

def test_dry_run_no_escribe_nada(datos, cfg):
    r = conciliar.ejecutar(datos / "banco.csv", datos / "contable.xlsx", cfg, dry_run=True)
    assert r["estado"] == "ensayo"
    assert not cfg.dir_salidas.exists() and not cfg.dir_auditoria.exists()


def test_idempotencia(datos, cfg):
    b, c = datos / "banco.csv", datos / "contable.xlsx"
    r1 = conciliar.ejecutar(b, c, cfg)
    contenido = r1["salida"].read_bytes()
    r2 = conciliar.ejecutar(b, c, cfg)
    assert (r1["estado"], r2["estado"]) == ("ejecutada", "omitida")
    assert len(auditoria.leer(cfg.dir_auditoria)) == 1
    assert len(list(cfg.dir_salidas.glob("*.xlsx"))) == 1
    assert r2["salida"].read_bytes() == contenido


def test_idempotencia_se_recupera_si_falta_el_reporte(datos, cfg):
    b, c = datos / "banco.csv", datos / "contable.xlsx"
    r1 = conciliar.ejecutar(b, c, cfg)
    r1["salida"].unlink()
    assert conciliar.ejecutar(b, c, cfg)["estado"] == "ejecutada"
    assert len(list(cfg.dir_salidas.glob("*.xlsx"))) == 1


def test_entrada_distinta_o_regla_distinta_genera_otra_corrida(datos, cfg):
    b, c = datos / "banco.csv", datos / "contable.xlsx"
    conciliar.ejecutar(b, c, cfg)
    b.write_text(b.read_text() + "MOV-999999,2026-10-30,12.34,FAC-0000001,extra\n")
    assert conciliar.ejecutar(b, c, cfg)["estado"] == "ejecutada"
    assert conciliar.ejecutar(b, c, dataclasses.replace(cfg, tol_dias=1))["estado"] == "ejecutada"
    assert len(list(cfg.dir_salidas.glob("*.xlsx"))) == 3


def test_reporte_tiene_las_hojas_y_cifras_coherentes(datos, cfg):
    r = conciliar.ejecutar(datos / "banco.csv", datos / "contable.xlsx", cfg)
    wb = load_workbook(r["salida"])
    assert wb.sheetnames == ["Resumen", "Conciliadas", "Revision", "Pendientes", "Bitacora"]
    res = r["resultado"]
    assert wb["Conciliadas"].max_row - 1 == len(res.conciliadas)
    assert wb["Revision"].max_row - 1 == len(res.revision)
    assert wb["Pendientes"].max_row - 1 == len(res.pend_banco) + len(res.pend_doc)
    assert wb["Bitacora"].max_row > 3
    textos = " ".join(str(c.value) for fila in wb["Resumen"].iter_rows() for c in fila)
    assert "supuestos declarados" in textos and "sintéticos" in textos


def test_excel_no_deja_pasar_formulas(tmp_path, cfg):
    d = tmp_path / "datos"
    d.mkdir()
    _csv(d / "banco.csv", ['M1,2026-10-01,50.00,"=HYPERLINK(""http://x"")",+cmd', "M2,2026-10-01,60.00,@SUM(1),x"])
    wb = Workbook()
    ws = wb.active
    ws.append(["id_doc", "fecha_contable", "monto", "referencia", "cliente"])
    ws.append(["D1", "2026-10-01", 99, "-1+2", "CLI0001"])
    ws.append(["=D1", "2026-10-01", 98, "x", "CLI0001"])
    ws.cell(3, 1).data_type = "s"          # texto literal que empieza con "="
    wb.save(d / "contable.xlsx")
    r = conciliar.ejecutar(d / "banco.csv", d / "contable.xlsx", cfg)
    wb = load_workbook(r["salida"])
    for hoja in wb:
        for fila in hoja.iter_rows():
            for c in fila:
                assert c.data_type != "f", f"fórmula en {hoja.title}!{c.coordinate}"
    pend = [c.value for fila in wb["Pendientes"].iter_rows(min_row=2) for c in fila if isinstance(c.value, str)]
    assert any(v.startswith("'=") for v in pend) and any(v.startswith("'@") for v in pend)
    assert any(v.startswith("'-") for v in pend) and any(v.startswith("'=D1") for v in pend)


def test_error_de_entrada_no_deja_salidas(tmp_path, cfg):
    d = tmp_path / "datos"
    d.mkdir()
    (d / "banco.csv").write_text("a,b\n1,2\n")
    (d / "contable.xlsx").write_bytes(b"no es un excel")
    with pytest.raises(ErrorDeEntrada):
        conciliar.ejecutar(d / "banco.csv", d / "contable.xlsx", cfg)
    assert not list(cfg.dir_salidas.glob("*")) if cfg.dir_salidas.exists() else True
    assert not cfg.dir_auditoria.exists()


def test_reintento_al_guardar_reporte(datos, cfg, monkeypatch):
    import reporte
    from openpyxl import Workbook as WB
    original = WB.save
    fallos = {"n": 0}

    def inestable(self, nombre):
        if fallos["n"] < 2:
            fallos["n"] += 1
            raise PermissionError("bloqueado")
        return original(self, nombre)

    monkeypatch.setattr(WB, "save", inestable)
    monkeypatch.setattr("comun.time.sleep", lambda s: None)
    r = conciliar.ejecutar(datos / "banco.csv", datos / "contable.xlsx", cfg)
    assert r["estado"] == "ejecutada" and fallos["n"] == 2 and r["salida"].is_file()
    assert not list(cfg.dir_salidas.glob("*.tmp"))


def test_falla_persistente_no_deja_archivo_a_medias(datos, cfg, monkeypatch):
    from openpyxl import Workbook as WB

    def siempre(self, nombre):
        raise PermissionError("bloqueado")

    monkeypatch.setattr(WB, "save", siempre)
    monkeypatch.setattr("comun.time.sleep", lambda s: None)
    with pytest.raises(PermissionError):
        conciliar.ejecutar(datos / "banco.csv", datos / "contable.xlsx", cfg)
    assert not list(cfg.dir_salidas.glob("*"))
    assert auditoria.leer(cfg.dir_auditoria) == []


def test_main_codigos_de_salida(datos, tmp_path, monkeypatch):
    monkeypatch.setenv("CONC_DIR_SALIDAS", str(tmp_path / "s"))
    monkeypatch.setenv("CONC_DIR_AUDITORIA", str(tmp_path / "a"))
    assert conciliar.main(["--banco", str(datos / "banco.csv"), "--contable", str(datos / "contable.xlsx"), "--dry-run"]) == 0
    assert conciliar.main(["--banco", str(tmp_path / "no.csv"), "--contable", str(datos / "contable.xlsx")]) == 2
    monkeypatch.setenv("CONC_TOL_DIAS", "99")
    assert conciliar.main(["--dry-run"]) == 2


def test_logs_sin_rutas_ni_datos(datos, tmp_path, cfg, caplog):
    caplog.set_level(logging.INFO)
    conciliar.ejecutar(datos / "banco.csv", datos / "contable.xlsx", cfg)
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert str(tmp_path) not in texto and "/" not in texto.replace("/ ", "")
    assert "FAC-" not in texto and "CLI0" not in texto
    caplog.clear()
    with pytest.raises(FileNotFoundError):
        conciliar.ejecutar(tmp_path / "x.csv", datos / "contable.xlsx", cfg)


# ---------- auditoría ----------

def test_auditoria_hash_de_entradas_y_cadena(datos, cfg):
    conciliar.ejecutar(datos / "banco.csv", datos / "contable.xlsx", cfg)
    e = auditoria.leer(cfg.dir_auditoria)[0]
    from comun import sha256_archivo
    assert e["entradas"][0]["sha256"] == sha256_archivo(datos / "banco.csv")
    assert e["entradas"][1]["sha256"] == sha256_archivo(datos / "contable.xlsx")
    assert e["salida"]["sha256"] == sha256_archivo(cfg.dir_salidas / e["salida"]["archivo"])
    assert e["entradas"][0]["archivo"] == "banco.csv"
    assert str(datos) not in json.dumps(e)
    assert auditoria.verificar_cadena(cfg.dir_auditoria)[0]


def test_auditoria_detecta_manipulacion(datos, cfg):
    b = datos / "banco.csv"
    conciliar.ejecutar(b, datos / "contable.xlsx", cfg)
    b.write_text(b.read_text() + "MOV-999998,2026-10-30,1.00,FAC-0000002,x\n")
    conciliar.ejecutar(b, datos / "contable.xlsx", cfg)
    assert auditoria.verificar_cadena(cfg.dir_auditoria) == (True, "cadena íntegra")
    ruta = cfg.dir_auditoria / auditoria.NOMBRE
    lineas = ruta.read_text().splitlines()
    ruta.write_text(lineas[0].replace('"revision":15', '"revision":0') + "\n" + lineas[1] + "\n")
    assert auditoria.verificar_cadena(cfg.dir_auditoria)[0] is False
    ruta.write_text(lineas[1] + "\n")        # borrar la primera
    assert auditoria.verificar_cadena(cfg.dir_auditoria)[0] is False


# ---------- configuración y tiempos ----------

@pytest.mark.parametrize("var,valor", [("CONC_TOL_MONTO", "-1"), ("CONC_TOL_MONTO", "abc"), ("CONC_TOL_DIAS", "x"),
                                       ("CONC_REINTENTOS", "0"), ("CONC_REINTENTOS", "50"),
                                       ("CONC_UMBRAL_AUTO", "0.3"), ("CONC_MAX_CANDIDATOS", "40")])
def test_config_valida_entradas(var, valor):
    with pytest.raises(ErrorDeConfiguracion):
        Config.desde_entorno({var: valor})


def test_config_por_defecto_y_por_entorno():
    assert Config.desde_entorno({}).tol_monto_centavos == 10
    assert Config.desde_entorno({"CONC_TOL_MONTO": "0.25", "CONC_TOL_DIAS": "2"}).tol_monto_centavos == 25


def test_tiempos_declara_supuestos(cfg):
    t = tiempos.estimar(100, 10, 0.5, cfg)
    assert t["manual_estimado_min"] == 150.0 and t["revision_humana_estimada_min"] == 30.0
    assert t["motor_medido_seg"] == 0.5 and "supuestos" in t["nota"]
