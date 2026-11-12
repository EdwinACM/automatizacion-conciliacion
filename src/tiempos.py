"""Comparación de tiempo manual estimado contra tiempo automatizado.

El tiempo automatizado de la máquina se mide en cada corrida. Todo lo demás son supuestos
declarados en Config (min_manual_por_partida y min_revision_por_caso). No son mediciones
de ningún proceso real y no deben leerse como un ahorro comprobado.
"""
from __future__ import annotations


def estimar(n_partidas: int, n_revision: int, seg_motor: float, cfg) -> dict:
    manual = n_partidas * cfg.min_manual_por_partida
    revision = n_revision * cfg.min_revision_por_caso
    automatizado = seg_motor / 60 + revision
    return {
        "supuesto_min_manual_por_partida": cfg.min_manual_por_partida,
        "supuesto_min_revision_por_caso": cfg.min_revision_por_caso,
        "manual_estimado_min": round(manual, 1),
        "motor_medido_seg": round(seg_motor, 3),
        "revision_humana_estimada_min": round(revision, 1),
        "automatizado_estimado_min": round(automatizado, 1),
        "nota": "Los minutos por partida son supuestos del proyecto, no mediciones. "
                "Solo el tiempo del motor es medido.",
    }
