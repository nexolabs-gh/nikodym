"""Curva de confiabilidad de calibración (reliability diagram) derivada en la capa ``ui``.

Artefacto rico **derivado** —no un número del motor— que proyecta la calibración a una curva
*predicho-vs-observado por bin*, por partición, con Brier y ECE. El motor V1 está congelado: este
módulo **no** lo toca ni lo importa; recibe el ``DataFrame`` ``calibrated_pd_frame`` ya
materializado (columnas ``partition``/``target``/``pd_calibrated``) y solo lo **agrega**. Respeta
la frontera *domain-agnostic* de :mod:`nikodym.ui` (test AST
``test_ui_no_importa_modulos_de_dominio``): importa solo pandas/numpy y la jerarquía de excepciones
de la propia capa ``ui``.

Determinismo (SDD-23 §11): binning por **deciles de igual frecuencia** con
:func:`pandas.qcut` (``duplicates="drop"``), orden canónico de particiones fijo y guard de finitud
sobre la salida. Nada depende de ``random`` ni del orden de hash.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from nikodym.ui.exceptions import UiSerializationError

__all__ = ["reliability_curve"]

# Orden canónico de particiones en la salida (SDD-10). Cualquier otra partición presente va después,
# en orden estable de aparición en el frame (determinista, independiente del orden de hash).
_CANONICAL_ORDER: tuple[str, ...] = ("desarrollo", "holdout", "oot")
# Intervalo de Wilson al 95 % (z = 1.96), fijado por el goal B35a (sin depender de scipy).
_WILSON_Z: float = 1.96


def reliability_curve(frame: pd.DataFrame, *, n_bins: int = 10) -> dict[str, Any]:
    """Proyecta ``calibrated_pd_frame`` a la curva de confiabilidad por partición (SDD-23 §6).

    Parameters
    ----------
    frame : pandas.DataFrame
        ``calibrated_pd_frame`` del motor de calibración. Se usan ``partition`` (etiqueta de
        partición), ``target`` (default observado 0/1) y ``pd_calibrated`` (PD calibrada predicha).
    n_bins : int, optional
        Número de deciles de igual frecuencia por partición (default 10). Si una partición tiene
        pocos valores únicos y ``qcut`` colapsa los bordes, se acepta el número de bins resultante
        (un único bin en el caso degenerado de un solo valor único).

    Returns
    -------
    dict
        ``{"strategy": "quantile", "n_bins": n_bins, "by_partition": [...]}``. ``by_partition`` es
        una **lista** en orden canónico (desarrollo, holdout, oot; otras al final, estable), una
        entrada por partición con ``n``/``brier``/``ece`` y sus ``bins`` (uno por bin, ascendente en
        PD). Las particiones con ``n == 0`` se excluyen. Sin ``NaN``/``Inf`` en la salida.
    """
    partition = frame["partition"].astype("string")
    pd_calibrated = frame["pd_calibrated"].to_numpy(dtype="float64", copy=True)
    target = frame["target"].to_numpy(dtype="float64", copy=True)

    observed = [str(value) for value in pd.unique(partition) if not pd.isna(value)]
    by_partition: list[dict[str, Any]] = []
    for name in _ordered_partitions(observed):
        mask = (partition == name).fillna(False).to_numpy(dtype=bool)
        n_partition = int(mask.sum())
        if n_partition == 0:  # partición sin filas (p. ej. categoría vacía): se excluye.
            continue
        part_pd = pd_calibrated[mask]
        part_target = target[mask]
        bins = _partition_bins(part_pd, part_target, n_bins)
        brier = float(np.mean((part_pd - part_target) ** 2))
        ece = float(
            sum(
                (item["n"] / n_partition)
                * abs(item["mean_predicted_pd"] - item["observed_default_rate"])
                for item in bins
            )
        )
        by_partition.append(
            {
                "partition": name,
                "n": n_partition,
                "brier": brier,
                "ece": ece,
                "bins": bins,
            }
        )

    result: dict[str, Any] = {
        "strategy": "quantile",
        "n_bins": n_bins,
        "by_partition": by_partition,
    }
    _ensure_finite(result)
    return result


def _ordered_partitions(observed: list[str]) -> list[str]:
    """Ordena las particiones presentes: canónicas primero, el resto estable por aparición."""
    canonical = [name for name in _CANONICAL_ORDER if name in observed]
    extra = [name for name in observed if name not in _CANONICAL_ORDER]
    return canonical + extra


def _partition_bins(part_pd: Any, part_target: Any, n_bins: int) -> list[dict[str, Any]]:
    """Calcula los bins (predicho/observado + Wilson) de una partición, ascendentes en PD."""
    codes, edges = _quantile_codes(part_pd, n_bins)
    bins: list[dict[str, Any]] = []
    for code in range(len(edges) - 1):
        selected = codes == code
        n_bin = int(selected.sum())
        if n_bin == 0:  # bucket vacío tras colapsar bordes duplicados: se omite (defensivo).
            continue
        observed_rate = float(part_target[selected].mean())
        mean_predicted = float(part_pd[selected].mean())
        ci_low, ci_high = _wilson_interval(n_bin, observed_rate)
        bins.append(
            {
                "bin": len(bins) + 1,
                "n": n_bin,
                "mean_predicted_pd": mean_predicted,
                "observed_default_rate": observed_rate,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "pd_lo": float(edges[code]),
                "pd_hi": float(edges[code + 1]),
            }
        )
    return bins


def _quantile_codes(part_pd: Any, n_bins: int) -> tuple[Any, Any]:
    """Deciles de igual frecuencia (``qcut``); un único bin si hay <2 valores únicos.

    Devuelve ``(codes, edges)`` con ``codes`` en ``0..k-1`` (código de bin por fila) y ``edges`` de
    largo ``k+1`` (bordes). Con un solo valor único ``qcut`` colapsaría; se usa un único bin
    ``[min, max]`` que cubre todas las filas (documentado en :func:`reliability_curve`).
    """
    if len(np.unique(part_pd)) < 2:
        codes = np.zeros(len(part_pd), dtype="int64")
        edges = np.array([float(part_pd.min()), float(part_pd.max())], dtype="float64")
        return codes, edges
    codes, edges = pd.qcut(part_pd, n_bins, duplicates="drop", labels=False, retbins=True)
    return np.asarray(codes, dtype="int64"), np.asarray(edges, dtype="float64")


def _wilson_interval(n: int, rate: float) -> tuple[float, float]:
    """Intervalo de Wilson 95 % (z = 1.96) sobre una tasa observada, recortado a ``[0, 1]``."""
    z2 = _WILSON_Z * _WILSON_Z
    denominator = 1.0 + z2 / n
    center = (rate + z2 / (2.0 * n)) / denominator
    margin = (_WILSON_Z / denominator) * math.sqrt(rate * (1.0 - rate) / n + z2 / (4.0 * n * n))
    return max(0.0, center - margin), min(1.0, center + margin)


def _ensure_finite(payload: Any) -> None:
    """Guard de finitud: falla ruidoso si la salida no es JSON estricto (``NaN``/``Inf``/opaco)."""
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise UiSerializationError(
            "el artefacto 'calibration.reliability' no es serializable a JSON estricto "
            f"(no-finito u objeto opaco detectado): {exc}."
        ) from exc
