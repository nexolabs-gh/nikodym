"""Tests de la función pura ``reliability_curve`` (curva de confiabilidad de calibración, B35a).

Se ejercita el módulo *domain-agnostic* ``nikodym.ui.reliability`` con ``DataFrame`` sintéticos y
CONTROLADOS: calibración perfecta (ECE≈0, puntos sobre la diagonal), mal calibrada (ECE>0),
intervalo de Wilson, invariante de conteo por partición, exclusión de particiones vacías y
determinismo byte-a-byte. No requiere el motor ni FastAPI.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from nikodym.ui.reliability import reliability_curve

_BIN_KEYS = {
    "bin",
    "n",
    "mean_predicted_pd",
    "observed_default_rate",
    "ci_low",
    "ci_high",
    "pd_lo",
    "pd_hi",
}


def _perfect_frame(partition: str = "desarrollo") -> pd.DataFrame:
    """10 grupos de 20 filas; ``pd_calibrated`` = tasa observada exacta del grupo (diagonal).

    El grupo ``b`` (``b`` en ``0..9``) tiene 20 filas con ``pd = (b+1)/20`` y ``b+1`` defaults, así
    la tasa observada ``= (b+1)/20 = pd``. ``qcut`` en 10 deciles reparte cada valor único a su bin.
    """
    pds: list[float] = []
    targets: list[int] = []
    for b in range(10):
        pd_value = (b + 1) / 20.0
        n_bad = b + 1
        pds.extend([pd_value] * 20)
        targets.extend([1] * n_bad + [0] * (20 - n_bad))
    return pd.DataFrame(
        {"partition": [partition] * len(pds), "target": targets, "pd_calibrated": pds}
    )


def _miscalibrated_frame() -> pd.DataFrame:
    """Predicho alto pero NINGÚN default observado → |pred - obs| > 0 en todo bin (ECE>0)."""
    pds = [(b + 1) / 20.0 for b in range(10) for _ in range(20)]
    return pd.DataFrame(
        {"partition": ["desarrollo"] * len(pds), "target": [0] * len(pds), "pd_calibrated": pds}
    )


# ─────────────────────────────── shape y orden ───────────────────────────────


def test_shape_y_orden_canonico() -> None:
    """La salida trae strategy/n_bins/by_partition (lista) en orden dev, holdout, oot."""
    frames = [_perfect_frame("desarrollo"), _perfect_frame("holdout"), _perfect_frame("oot")]
    frame = pd.concat(frames, ignore_index=True)

    curve = reliability_curve(frame)

    assert curve["strategy"] == "quantile"
    assert curve["n_bins"] == 10
    assert isinstance(curve["by_partition"], list)
    assert [part["partition"] for part in curve["by_partition"]] == ["desarrollo", "holdout", "oot"]
    for part in curve["by_partition"]:
        assert set(part) == {"partition", "n", "brier", "ece", "bins"}
        for item in part["bins"]:
            assert set(item) == _BIN_KEYS
        # los bins van en orden ascendente de PD y numerados 1..k.
        assert [item["bin"] for item in part["bins"]] == list(range(1, len(part["bins"]) + 1))
        pd_his = [item["pd_hi"] for item in part["bins"]]
        assert pd_his == sorted(pd_his)


def test_orden_estable_particiones_extra() -> None:
    """Particiones no canónicas van al final, en orden de aparición (estable, no por hash)."""
    frame = pd.concat(
        [_perfect_frame("zeta"), _perfect_frame("oot"), _perfect_frame("alfa")],
        ignore_index=True,
    )
    orden = [part["partition"] for part in reliability_curve(frame)["by_partition"]]
    assert orden == ["oot", "zeta", "alfa"]


# ─────────────────────────────── calibración perfecta vs mala ───────────────────────────────


def test_calibracion_perfecta_ece_cero_y_sobre_diagonal() -> None:
    """pred==obs por bin → ECE≈0, Brier finito y cada punto sobre la diagonal."""
    curve = reliability_curve(_perfect_frame())
    part = curve["by_partition"][0]

    assert part["ece"] == pytest.approx(0.0, abs=1e-12)
    for item in part["bins"]:
        assert item["mean_predicted_pd"] == pytest.approx(item["observed_default_rate"], abs=1e-12)
    # Brier = media((pd - target)^2): finito y no negativo.
    assert part["brier"] >= 0.0
    assert np.isfinite(part["brier"])


def test_calibracion_mala_ece_positivo() -> None:
    """Predicho > 0 y observado 0 → ECE estrictamente positivo."""
    curve = reliability_curve(_miscalibrated_frame())
    part = curve["by_partition"][0]

    assert part["ece"] > 0.0
    for item in part["bins"]:
        assert item["observed_default_rate"] == 0.0
        assert item["mean_predicted_pd"] > 0.0


# ─────────────────────────────── Wilson e invariantes ───────────────────────────────


def test_wilson_contiene_la_tasa_y_esta_en_cero_uno() -> None:
    """Wilson 95 %: 0 ≤ ci_low ≤ observado ≤ ci_high ≤ 1 en todo bin y partición."""
    frame = pd.concat(
        [_perfect_frame("desarrollo"), _miscalibrated_frame().assign(partition="oot")],
        ignore_index=True,
    )
    for part in reliability_curve(frame)["by_partition"]:
        for item in part["bins"]:
            obs = item["observed_default_rate"]
            assert 0.0 <= item["ci_low"] <= obs <= item["ci_high"] <= 1.0


def test_suma_de_n_por_particion_igual_a_filas() -> None:
    """Σ n_bin = n_particion = filas de esa partición (ninguna fila se pierde ni duplica)."""
    frame = pd.concat([_perfect_frame("desarrollo"), _perfect_frame("oot")], ignore_index=True)
    conteos = frame["partition"].value_counts().to_dict()
    for part in reliability_curve(frame)["by_partition"]:
        assert sum(item["n"] for item in part["bins"]) == part["n"]
        assert part["n"] == conteos[part["partition"]]


def test_excluye_particion_con_n_cero() -> None:
    """Una categoría de partición sin filas (n=0) NO aparece en la salida."""
    partition = pd.Categorical(["desarrollo"] * 200, categories=["desarrollo", "holdout", "oot"])
    frame = _perfect_frame()
    frame["partition"] = partition  # holdout/oot son categorías vacías (n=0).

    orden = [part["partition"] for part in reliability_curve(frame)["by_partition"]]
    assert orden == ["desarrollo"]


def test_pocos_unicos_colapsa_a_un_bin() -> None:
    """Partición con un solo valor único de PD → qcut colapsaría; se acepta un único bin."""
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo"] * 10,
            "target": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
            "pd_calibrated": [0.3] * 10,
        }
    )
    part = reliability_curve(frame)["by_partition"][0]
    assert len(part["bins"]) == 1
    item = part["bins"][0]
    assert item["n"] == 10
    assert item["mean_predicted_pd"] == pytest.approx(0.3)
    assert item["observed_default_rate"] == pytest.approx(0.5)
    assert item["pd_lo"] == pytest.approx(0.3)
    assert item["pd_hi"] == pytest.approx(0.3)


# ─────────────────────────────── determinismo y finitud ───────────────────────────────


def test_determinismo_byte_a_byte() -> None:
    """Misma entrada → misma salida byte-a-byte (JSON estricto, sin NaN/Inf)."""
    frame = pd.concat(
        [_perfect_frame("desarrollo"), _perfect_frame("holdout"), _perfect_frame("oot")],
        ignore_index=True,
    )
    primera = json.dumps(reliability_curve(frame), allow_nan=False, sort_keys=True)
    segunda = json.dumps(reliability_curve(frame), allow_nan=False, sort_keys=True)
    assert primera == segunda
