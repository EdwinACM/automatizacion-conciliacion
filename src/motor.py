"""Motor de conciliación por reglas en cascada.

Orden de las reglas (cada una trabaja solo con lo que las anteriores dejaron libre):
  R1  exacta                    referencia normalizada, monto y fecha iguales          confianza 1.00
  R2  tolerancia                misma referencia, monto y fecha dentro de tolerancia   0.97 menos penalizaciones
  R2B tolerancia sin referencia sin referencia útil en alguno de los lados, monto
                                igual y fecha cercana                                  máx. 0.70
  R3  uno a muchos              un abono del banco contra varios documentos del mismo
                                cliente cuya suma coincide                             0.92 menos penalizaciones

Resultado de cada propuesta según su confianza:
  >= umbral_auto            conciliada
  >= umbral_revision        cola de revisión humana (con la propuesta)
  empate entre candidatos distintos  cola de revisión (ambiguo), sin consumir documentos
  abonos repetidos          cola de revisión (posible duplicado)
Lo que ninguna regla resuelve queda como pendiente.
"""
from __future__ import annotations

import itertools
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from cargar import Partida
from config import Config

log = logging.getLogger("conciliacion.motor")

R1, R2, R2B, R3, DUP = "R1_EXACTA", "R2_TOLERANCIA", "R2B_SIN_REFERENCIA", "R3_UNO_A_MUCHOS", "DUPLICADO"
CONCILIADA, REVISION = "conciliada", "revision"


@dataclass(frozen=True)
class Coincidencia:
    regla: str
    ids_banco: tuple[str, ...]
    ids_doc: tuple[str, ...]
    confianza: float | None
    estado: str
    dif_centavos: int = 0
    dif_dias: int = 0
    detalle: str = ""


@dataclass
class Resultado:
    conciliadas: list[Coincidencia] = field(default_factory=list)
    revision: list[Coincidencia] = field(default_factory=list)
    pend_banco: list[Partida] = field(default_factory=list)
    pend_doc: list[Partida] = field(default_factory=list)


# ---------- puntuación ----------

def _puntaje_tolerancia(b: Partida, d: Partida, cfg: Config):
    if not b.ref_norm or b.ref_norm != d.ref_norm:
        return None
    dm = abs(b.monto - d.monto)
    dd = abs((b.fecha - d.fecha).days)
    if dm > cfg.tol_monto_centavos or dd > cfg.tol_dias:
        return None
    pen_monto = 0.10 * (dm / cfg.tol_monto_centavos) if cfg.tol_monto_centavos else 0.0
    return round(0.97 - pen_monto - 0.03 * dd, 4)


def _puntaje_exacta(b: Partida, d: Partida, cfg: Config):
    if b.ref_norm and b.ref_norm == d.ref_norm and b.monto == d.monto and b.fecha == d.fecha:
        return 1.0
    return None


def _puntaje_sin_ref(b: Partida, d: Partida, cfg: Config):
    if b.ref_norm and d.ref_norm:
        return None
    if b.monto != d.monto or (b.cliente and d.cliente and b.cliente != d.cliente):
        return None
    dd = abs((b.fecha - d.fecha).days)
    if dd > cfg.tol_dias:
        return None
    return round(0.70 - 0.03 * dd, 4)


# ---------- reglas uno a uno ----------

def _candidatos_por_ref(b, libres_d, indice):
    return [libres_d[i] for i in indice.get(b.ref_norm, ()) if i in libres_d] if b.ref_norm else []


def _candidatos_por_monto(b, libres_d, indice):
    return [libres_d[i] for i in indice.get(b.monto, ()) if i in libres_d]


def _regla_uno_a_uno(nombre, puntuar, por, libres_b, libres_d, cfg, res):
    clave = (lambda d: d.ref_norm) if por == "ref" else (lambda d: d.monto)
    indice = defaultdict(list)
    for d in libres_d.values():
        indice[clave(d)].append(d.id)
    cand = _candidatos_por_ref if por == "ref" else _candidatos_por_monto

    def puntuados(b):
        out = []
        for d in cand(b, libres_d, indice):
            s = puntuar(b, d, cfg)
            if s is not None:
                out.append((s, d))
        out.sort(key=lambda x: (-x[0], x[1].id))
        return out

    orden = []
    for b in libres_b.values():
        c = puntuados(b)
        if c:
            orden.append((-c[0][0], b.id))
    for _, bid in sorted(orden):
        b = libres_b[bid]
        c = puntuados(b)          # se recalcula: los documentos ya usados no cuentan
        if not c:
            continue
        mejor = c[0][0]
        empatados = [d for s, d in c if s == mejor]
        if len({d.clave_equivalencia for d in empatados}) > 1:
            res.revision.append(Coincidencia(
                nombre, (b.id,), tuple(d.id for d in empatados), mejor, REVISION,
                detalle=f"{len(empatados)} documentos distintos con la misma puntuación"))
            del libres_b[bid]
            continue
        d = empatados[0]
        if mejor < cfg.umbral_revision:
            continue
        estado = CONCILIADA if mejor >= cfg.umbral_auto else REVISION
        c_ = Coincidencia(nombre, (b.id,), (d.id,), mejor, estado, b.monto - d.monto,
                          (b.fecha - d.fecha).days,
                          "" if estado == CONCILIADA else "confianza por debajo del umbral automático")
        (res.conciliadas if estado == CONCILIADA else res.revision).append(c_)
        del libres_b[bid]
        del libres_d[d.id]


# ---------- uno a muchos ----------

def _regla_uno_a_muchos(libres_b, libres_d, cfg, res):
    for bid in sorted(libres_b):
        b = libres_b[bid]
        if not b.cliente:
            continue
        cands = [d for d in libres_d.values()
                 if d.cliente == b.cliente and abs((b.fecha - d.fecha).days) <= cfg.dias_grupo
                 and d.monto < b.monto + cfg.tol_monto_centavos]
        cands.sort(key=lambda d: (abs((b.fecha - d.fecha).days), d.id))
        if len(cands) < 2:
            continue
        if len(cands) > cfg.max_candidatos_grupo:
            log.warning("Un abono tiene %d candidatos; se usan los %d más cercanos en fecha",
                        len(cands), cfg.max_candidatos_grupo)
            cands = cands[: cfg.max_candidatos_grupo]
        soluciones = []
        for k in range(2, min(cfg.max_docs_grupo, len(cands)) + 1):
            for comb in itertools.combinations(cands, k):
                if abs(sum(d.monto for d in comb) - b.monto) <= cfg.tol_monto_centavos:
                    soluciones.append(comb)
        if not soluciones:
            continue
        formas = {tuple(sorted(Counter(d.clave_equivalencia for d in s).items(), key=repr)) for s in soluciones}
        if len(formas) > 1:
            ids = sorted({d.id for s in soluciones for d in s})
            res.revision.append(Coincidencia(
                R3, (b.id,), tuple(ids), 0.60, REVISION,
                detalle=f"{len(soluciones)} combinaciones posibles de documentos"))
            del libres_b[bid]
            continue
        sol = soluciones[0]
        dif = b.monto - sum(d.monto for d in sol)
        conf = 0.92 - 0.02 * (len(sol) - 2)
        if cfg.tol_monto_centavos:
            conf -= 0.10 * abs(dif) / cfg.tol_monto_centavos
        conf = round(conf, 4)
        dias = max(abs((b.fecha - d.fecha).days) for d in sol)
        estado = CONCILIADA if conf >= cfg.umbral_auto else REVISION
        if conf < cfg.umbral_revision:
            continue
        c_ = Coincidencia(R3, (b.id,), tuple(sorted(d.id for d in sol)), conf, estado, dif, dias,
                          f"{len(sol)} documentos del mismo cliente")
        (res.conciliadas if estado == CONCILIADA else res.revision).append(c_)
        del libres_b[bid]
        for d in sol:
            del libres_d[d.id]


# ---------- duplicados ----------

def _separar_duplicados(banco, doc):
    """Abonos del banco idénticos (referencia, monto y fecha) que superan al número de
    documentos con esa referencia y monto. Se aparta el sobrante antes de conciliar."""
    docs = Counter((d.ref_norm, d.monto) for d in doc)
    grupos = defaultdict(list)
    for b in sorted(banco, key=lambda p: p.id):
        if b.ref_norm:
            grupos[(b.ref_norm, b.monto, b.fecha)].append(b)
    duplicados = {}
    for (ref, monto, _), lista in grupos.items():
        sobran = len(lista) - docs.get((ref, monto), 0)
        if len(lista) > 1 and sobran > 0:
            for extra in lista[-sobran:] if docs.get((ref, monto), 0) else lista[1:]:
                duplicados[extra.id] = lista[0].id
    return duplicados


# ---------- orquestación ----------

def conciliar(banco: list[Partida], doc: list[Partida], cfg: Config) -> Resultado:
    res = Resultado()
    duplicados = _separar_duplicados(banco, doc)
    libres_b = {b.id: b for b in sorted(banco, key=lambda p: p.id) if b.id not in duplicados}
    libres_d = {d.id: d for d in sorted(doc, key=lambda p: p.id)}

    _regla_uno_a_uno(R1, _puntaje_exacta, "ref", libres_b, libres_d, cfg, res)
    _regla_uno_a_uno(R2, _puntaje_tolerancia, "ref", libres_b, libres_d, cfg, res)
    _regla_uno_a_uno(R2B, _puntaje_sin_ref, "monto", libres_b, libres_d, cfg, res)
    _regla_uno_a_muchos(libres_b, libres_d, cfg, res)

    por_banco = {i: c for c in res.conciliadas for i in c.ids_banco}
    for dup_id, orig_id in sorted(duplicados.items()):
        orig = por_banco.get(orig_id)
        res.revision.append(Coincidencia(
            DUP, (dup_id,), orig.ids_doc if orig else (), None, REVISION,
            detalle=(f"repite el abono {orig_id}" + (", ya conciliado con ese documento" if orig
                                                      else ", que tampoco quedó conciliado"))))

    res.pend_banco = sorted(libres_b.values(), key=lambda p: p.id)
    res.pend_doc = sorted(libres_d.values(), key=lambda p: p.id)
    res.conciliadas.sort(key=lambda c: c.ids_banco)
    res.revision.sort(key=lambda c: c.ids_banco)
    log.info("Motor: %d conciliadas, %d en revisión, %d pendientes banco, %d pendientes contables",
             len(res.conciliadas), len(res.revision), len(res.pend_banco), len(res.pend_doc))
    return res
