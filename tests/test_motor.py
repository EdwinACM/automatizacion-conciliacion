import dataclasses

from motor import CONCILIADA, DUP, R1, R2, R2B, R3, REVISION, conciliar


def correr(b, d, cfg):
    return conciliar(b, d, cfg)


def test_r1_exacta(cfg, mk):
    r = correr([mk("banco", "B1", 100)], [mk("contable", "D1", 100)], cfg)
    c = r.conciliadas[0]
    assert (c.regla, c.confianza, c.ids_doc) == (R1, 1.0, ("D1",))
    assert not r.revision and not r.pend_banco and not r.pend_doc


def test_r1_ignora_formato_de_referencia(cfg, mk):
    r = correr([mk("banco", "B1", 100, ref=" fac 0001234.")], [mk("contable", "D1", 100, ref="FAC-0001234")], cfg)
    assert r.conciliadas[0].regla == R1


def test_r2_redondeo(cfg, mk):
    r = correr([mk("banco", "B1", 100.03)], [mk("contable", "D1", 100)], cfg)
    c = r.conciliadas[0]
    assert c.regla == R2 and c.dif_centavos == 3 and 0.85 <= c.confianza < 1


def test_r2_fecha_en_ambos_sentidos(cfg, mk):
    for dia in (7, 13):
        r = correr([mk("banco", "B1", 100, dia=dia)], [mk("contable", "D1", 100)], cfg)
        assert r.conciliadas[0].regla == R2


def test_r2_fuera_de_tolerancia_queda_pendiente(cfg, mk):
    r = correr([mk("banco", "B1", 100, dia=14)], [mk("contable", "D1", 100)], cfg)   # 4 días
    assert not r.conciliadas and len(r.pend_banco) == 1 and len(r.pend_doc) == 1
    r = correr([mk("banco", "B1", 100.11)], [mk("contable", "D1", 100)], cfg)        # 11 centavos
    assert not r.conciliadas


def test_r2_limite_de_ambas_tolerancias_va_a_revision(cfg, mk):
    r = correr([mk("banco", "B1", 100.10, dia=13)], [mk("contable", "D1", 100)], cfg)
    assert not r.conciliadas
    c = r.revision[0]
    assert c.regla == R2 and c.estado == REVISION and cfg.umbral_revision <= c.confianza < cfg.umbral_auto


def test_umbrales_configurables(cfg, mk):
    laxo = dataclasses.replace(cfg, umbral_auto=0.75)
    r = correr([mk("banco", "B1", 100.10, dia=13)], [mk("contable", "D1", 100)], laxo)
    assert len(r.conciliadas) == 1
    estricto = dataclasses.replace(cfg, umbral_revision=0.95, umbral_auto=0.99)
    r = correr([mk("banco", "B1", 100.03)], [mk("contable", "D1", 100)], estricto)
    assert not r.conciliadas and not r.revision and len(r.pend_banco) == 1


def test_r2b_sin_referencia_siempre_a_revision(cfg, mk):
    r = correr([mk("banco", "B1", 100, ref="")], [mk("contable", "D1", 100, ref="FAC-77")], cfg)
    assert not r.conciliadas
    c = r.revision[0]
    assert c.regla == R2B and c.ids_doc == ("D1",) and c.confianza <= 0.70


def test_r2b_ambiguo_no_consume_documentos(cfg, mk):
    r = correr([mk("banco", "B1", 100, ref="")],
               [mk("contable", "D1", 100, ref="FAC-11"), mk("contable", "D2", 100, ref="FAC-22")], cfg)
    c = r.revision[0]
    assert c.ids_doc == ("D1", "D2") and "distintos" in c.detalle
    assert len(r.pend_doc) == 2


def test_r2b_cliente_distinto_no_propone(cfg, mk):
    r = correr([mk("banco", "B1", 100, ref="PAGO CLI0001", cliente="CLI0001")],
               [mk("contable", "D1", 100, ref="", cliente="CLI0002")], cfg)
    assert not r.revision and not r.conciliadas


def test_documentos_identicos_son_intercambiables(cfg, mk):
    b = [mk("banco", "B1", 100), mk("banco", "B2", 100)]
    d = [mk("contable", "D1", 100), mk("contable", "D2", 100)]
    r = correr(b, d, cfg)
    assert [(c.ids_banco, c.ids_doc) for c in r.conciliadas] == [(("B1",), ("D1",)), (("B2",), ("D2",))]
    assert not r.revision


def test_documento_no_se_usa_dos_veces(cfg, mk):
    # dos bancos con la misma referencia pero distinta fecha y un solo documento
    r = correr([mk("banco", "B1", 100, dia=10), mk("banco", "B2", 100, dia=11)], [mk("contable", "D1", 100)], cfg)
    usados = [i for c in r.conciliadas + r.revision for i in c.ids_doc]
    assert len(usados) == len(set(usados)) == 1
    assert len(r.pend_banco) == 1


def test_duplicado_va_a_revision(cfg, mk):
    r = correr([mk("banco", "B1", 100), mk("banco", "B2", 100)], [mk("contable", "D1", 100)], cfg)
    assert [c.ids_banco for c in r.conciliadas] == [("B1",)]
    d = r.revision[0]
    assert d.regla == DUP and d.ids_banco == ("B2",) and d.ids_doc == ("D1",) and d.confianza is None


def test_pagos_repetidos_legitimos_no_son_duplicado(cfg, mk):
    r = correr([mk("banco", "B1", 100), mk("banco", "B2", 100)],
               [mk("contable", "D1", 100), mk("contable", "D2", 100)], cfg)
    assert len(r.conciliadas) == 2 and not r.revision


def test_duplicado_sin_original_conciliado(cfg, mk):
    r = correr([mk("banco", "B1", 100), mk("banco", "B2", 100)], [], cfg)
    assert r.revision[0].regla == DUP and "tampoco" in r.revision[0].detalle
    assert [p.id for p in r.pend_banco] == ["B1"]


def test_duplicado_sin_referencia_no_se_marca(cfg, mk):
    r = correr([mk("banco", "B1", 100, ref=""), mk("banco", "B2", 100, ref="")], [], cfg)
    assert not r.revision and len(r.pend_banco) == 2


def test_r3_uno_a_muchos(cfg, mk):
    b = [mk("banco", "B1", 600, ref="PAGO CLI0005", cliente="CLI0005")]
    d = [mk("contable", f"D{i}", m, ref=f"FAC-{i}00", cliente="CLI0005") for i, m in ((1, 100), (2, 200), (3, 300))]
    r = correr(b, d, cfg)
    c = r.conciliadas[0]
    assert c.regla == R3 and c.ids_doc == ("D1", "D2", "D3") and c.dif_centavos == 0
    assert c.confianza >= cfg.umbral_auto and not r.pend_doc


def test_r3_con_diferencia_de_redondeo(cfg, mk):
    b = [mk("banco", "B1", 300.05, ref="PAGO CLI0005", cliente="CLI0005")]
    d = [mk("contable", "D1", 100, ref="FAC-1", cliente="CLI0005"), mk("contable", "D2", 200, ref="FAC-2", cliente="CLI0005")]
    c = correr(b, d, cfg).conciliadas[0]
    assert c.dif_centavos == 5


def test_r3_ambiguo_va_a_revision_sin_consumir(cfg, mk):
    b = [mk("banco", "B1", 30, ref="PAGO CLI0005", cliente="CLI0005")]
    d = [mk("contable", f"D{i}", m, ref=f"FAC-{i}0", cliente="CLI0005") for i, m in ((1, 10), (2, 20), (3, 10), (4, 10))]
    r = correr(b, d, cfg)
    assert not r.conciliadas and r.revision[0].regla == R3 and "combinaciones" in r.revision[0].detalle
    assert len(r.pend_doc) == 4


def test_r3_exige_mismo_cliente_y_ventana(cfg, mk):
    b = [mk("banco", "B1", 300, ref="PAGO CLI0005", cliente="CLI0005")]
    otro = [mk("contable", "D1", 100, ref="FAC-1", cliente="CLI0006"), mk("contable", "D2", 200, ref="FAC-2", cliente="CLI0005")]
    assert not correr(b, otro, cfg).conciliadas
    lejos = [mk("contable", "D1", 100, ref="FAC-1", cliente="CLI0005", dia=1), mk("contable", "D2", 200, ref="FAC-2", cliente="CLI0005")]
    assert not correr(b, lejos, cfg).conciliadas


def test_r3_sin_cliente_no_agrupa(cfg, mk):
    b = [mk("banco", "B1", 300, ref="PAGO")]
    d = [mk("contable", "D1", 100, ref="FAC-1", cliente="CLI0005"), mk("contable", "D2", 200, ref="FAC-2", cliente="CLI0005")]
    r = correr(b, d, cfg)
    assert not r.conciliadas and len(r.pend_banco) == 1


def test_r3_respeta_tope_de_documentos(cfg, mk):
    chico = dataclasses.replace(cfg, max_docs_grupo=2)
    b = [mk("banco", "B1", 600, ref="PAGO CLI0005", cliente="CLI0005")]
    d = [mk("contable", f"D{i}", m, ref=f"FAC-{i}00", cliente="CLI0005") for i, m in ((1, 100), (2, 200), (3, 300))]
    assert not correr(b, d, chico).conciliadas


def test_pendientes_sin_contraparte(cfg, mk):
    r = correr([mk("banco", "B1", 100, ref="FAC-1")], [mk("contable", "D1", 555, ref="FAC-9")], cfg)
    assert len(r.pend_banco) == 1 and len(r.pend_doc) == 1 and not r.conciliadas


def test_entradas_vacias(cfg):
    r = correr([], [], cfg)
    assert not (r.conciliadas or r.revision or r.pend_banco or r.pend_doc)


def test_cascada_prefiere_exacta_sobre_tolerancia(cfg, mk):
    b = [mk("banco", "B1", 100)]
    d = [mk("contable", "D1", 100.02), mk("contable", "D2", 100)]
    c = correr(b, d, cfg).conciliadas[0]
    assert c.regla == R1 and c.ids_doc == ("D2",)


def test_resultado_es_determinista(cfg, mk):
    b = [mk("banco", f"B{i}", 100 + i, ref=f"FAC-{i}") for i in range(20)]
    d = [mk("contable", f"D{i}", 100 + i, ref=f"FAC-{i}") for i in range(20)]
    assert correr(b, d, cfg) == correr(list(reversed(b)), list(reversed(d)), cfg)
