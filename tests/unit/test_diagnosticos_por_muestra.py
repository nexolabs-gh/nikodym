"""Los dos artefactos aditivos del banco (enmienda FLUJO-GUIADO-SCORECARD §3.6, D-FLU-6).

``("selection", "iv_by_partition")`` y ``("binning", "event_rate_by_partition")`` nacen aparte,
con clave propia y estos goldens: las tablas estables de F1 no cambian de esquema (lo vigilan
sus propios tests) y aquí se prueban la metodología y los casos borde —muestra con una sola
clase, tramo con pocas filas, ``Special``/``Missing``, empates, tendencia no monótona— con frames
mínimos escritos a mano, para que cada número sea verificable a ojo.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from nikodym.binning.diagnostics import (
    EVENT_RATE_BY_PARTITION_COLUMNS,
    MIN_FILAS_POR_TRAMO,
    event_rate_by_partition,
)
from nikodym.binning.step import BINNING_ARTIFACTS, BinningStep
from nikodym.selection.diagnostics import IV_BY_PARTITION_COLUMNS, iv_by_partition
from nikodym.selection.step import SELECTION_ARTIFACTS, SelectionStep


def _frame(filas: list[tuple[str, str, int]]) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """``(tramo, muestra, malo)`` por fila → bin_frame, target y partition alineados."""
    index = pd.Index([f"op-{i:04d}" for i in range(len(filas))], name="loan_id")
    bin_frame = pd.DataFrame({"x__bin": [f[0] for f in filas]}, index=index).astype("string")
    target = pd.Series([f[2] for f in filas], index=index, dtype="float64")
    partition = pd.Series([f[1] for f in filas], index=index, dtype="object")
    return bin_frame, target, partition


def _repetir(tramo: str, muestra: str, n: int, malos: int) -> list[tuple[str, str, int]]:
    return [(tramo, muestra, 1)] * malos + [(tramo, muestra, 0)] * (n - malos)


# ─────────────────────────────── IV por muestra ───────────────────────────────


def test_el_iv_por_muestra_aplica_la_formula_de_sdd_06_sobre_cada_muestra() -> None:
    filas = (
        _repetir("A", "desarrollo", 100, 10)
        + _repetir("B", "desarrollo", 100, 40)
        + _repetir("A", "oot", 50, 25)
        + _repetir("B", "oot", 50, 25)
    )
    bin_frame, target, partition = _frame(filas)
    tabla = iv_by_partition(bin_frame=bin_frame, target=target, partition=partition)
    assert list(tabla.columns) == list(IV_BY_PARTITION_COLUMNS)
    assert tabla["partition"].tolist() == ["desarrollo", "oot"]  # holdout ausente → sin fila
    dev = tabla.set_index("partition").loc["desarrollo"]
    # Desarrollo: buenos 90/150 en A y 60/150 en B; malos 10/50 y 40/50.
    esperado = (90 / 150 - 10 / 50) * math.log((90 / 150) / (10 / 50)) + (
        60 / 150 - 40 / 50
    ) * math.log((60 / 150) / (40 / 50))
    assert dev["n"] == 200 and dev["n_bad"] == 50
    assert float(dev["iv"]) == pytest.approx(esperado, abs=1e-15)
    # Fuera de tiempo las dos distribuciones son iguales: IV exactamente cero.
    assert float(tabla.set_index("partition").loc["oot", "iv"]) == 0.0
    assert tabla["not_evaluable_reason"].isna().all()


def test_una_muestra_con_una_sola_clase_no_tiene_iv_y_lo_dice() -> None:
    bin_frame, target, partition = _frame(
        _repetir("A", "desarrollo", 40, 10) + _repetir("A", "holdout", 30, 0)
    )
    tabla = iv_by_partition(bin_frame=bin_frame, target=target, partition=partition)
    holdout = tabla.set_index("partition").loc["holdout"]
    assert pd.isna(holdout["iv"])
    assert holdout["not_evaluable_reason"] == "single_class"
    assert holdout["n"] == 30 and holdout["n_bad"] == 0


def test_un_tramo_sin_malos_o_sin_buenos_no_aporta_al_iv() -> None:
    """Como OptBinning con un tramo vacío: el logaritmo no existe, el aporte es cero."""
    bin_frame, target, partition = _frame(
        _repetir("A", "desarrollo", 50, 10)
        + _repetir("B", "desarrollo", 50, 20)
        + _repetir("Missing", "desarrollo", 20, 0)
    )
    tabla = iv_by_partition(bin_frame=bin_frame, target=target, partition=partition)
    # Los 20 buenos de Missing entran al total de buenos (40 + 30 + 20 = 90) aunque el tramo
    # no aporte; los malos son 30.
    esperado = (40 / 90 - 10 / 30) * math.log((40 / 90) / (10 / 30)) + (
        30 / 90 - 20 / 30
    ) * math.log((30 / 90) / (20 / 30))
    assert float(tabla["iv"].iloc[0]) == pytest.approx(esperado, abs=1e-15)


def test_las_filas_sin_target_no_cuentan() -> None:
    bin_frame, target, partition = _frame(
        _repetir("A", "desarrollo", 40, 10) + _repetir("B", "desarrollo", 40, 20)
    )
    target.iloc[:5] = float("nan")
    tabla = iv_by_partition(bin_frame=bin_frame, target=target, partition=partition)
    assert tabla["n"].iloc[0] == 75


# ─────────────────────────── tasa de malos por tramo y muestra ───────────────────────────


def _tablas(*etiquetas: str) -> dict[str, pd.DataFrame]:
    """La tabla de binning de desarrollo, con el orden de los tramos y la fila de totales."""
    return {"x": pd.DataFrame({"Bin": [*etiquetas, "Special", "Missing", ""]})}


def test_la_inversion_se_evalua_contra_la_tendencia_de_desarrollo() -> None:
    n = MIN_FILAS_POR_TRAMO
    filas = (
        _repetir("[0, 1)", "desarrollo", n, 20)
        + _repetir("[1, 2)", "desarrollo", n, 10)
        + _repetir("[2, inf)", "desarrollo", n, 5)
        + _repetir("[0, 1)", "oot", n, 10)
        + _repetir("[1, 2)", "oot", n, 15)  # sube donde debía bajar: invierte
        + _repetir("[2, inf)", "oot", n, 15)  # empate con el anterior: no invierte
    )
    bin_frame, target, partition = _frame(filas)
    tabla = event_rate_by_partition(
        bin_frame=bin_frame,
        target=target,
        partition=partition,
        tables=_tablas("[0, 1)", "[1, 2)", "[2, inf)"),
        trends={"x": "descending"},
    )
    assert list(tabla.columns) == list(EVENT_RATE_BY_PARTITION_COLUMNS)
    oot = tabla[tabla["partition"] == "oot"].set_index("bin_label")
    assert oot["bin_id"].tolist() == [0, 1, 2]
    assert pd.isna(oot.loc["[0, 1)", "inverts"])  # el primero no tiene con qué compararse
    assert oot.loc["[1, 2)", "inverts"] is True or bool(oot.loc["[1, 2)", "inverts"])
    assert not bool(oot.loc["[2, inf)", "inverts"])
    dev = tabla[tabla["partition"] == "desarrollo"].set_index("bin_label")
    assert not dev["inverts"].iloc[1:].astype(bool).any()
    assert dev["event_rate"].tolist() == pytest.approx([20 / n, 10 / n, 5 / n])


def test_un_tramo_con_pocas_filas_no_se_evalua_ni_el_que_lo_sigue() -> None:
    n = MIN_FILAS_POR_TRAMO
    filas = (
        _repetir("[0, 1)", "holdout", n, 5)
        + _repetir("[1, 2)", "holdout", n - 1, 20)  # bajo el mínimo
        + _repetir("[2, inf)", "holdout", n, 2)
    )
    bin_frame, target, partition = _frame(filas)
    tabla = event_rate_by_partition(
        bin_frame=bin_frame,
        target=target,
        partition=partition,
        tables=_tablas("[0, 1)", "[1, 2)", "[2, inf)"),
        trends={"x": "ascending"},
    )
    holdout = tabla.set_index("bin_label")
    assert holdout["n"].tolist() == [n, n - 1, n]
    assert holdout["inverts"].isna().all(), "sin tramo anterior evaluable no hay veredicto"


def test_un_tramo_ausente_en_la_muestra_se_publica_vacio_y_reinicia_la_cadena() -> None:
    """A-B-C en desarrollo y B sin filas en OOT: C no se compara con A (Codex sobre A2)."""
    n = MIN_FILAS_POR_TRAMO
    filas = (
        _repetir("[0, 1)", "desarrollo", n, 5)
        + _repetir("[1, 2)", "desarrollo", n, 10)
        + _repetir("[2, inf)", "desarrollo", n, 15)
        + _repetir("[0, 1)", "oot", n, 20)
        + _repetir("[2, inf)", "oot", n, 5)  # baja respecto de A, pero B no está: sin veredicto
    )
    bin_frame, target, partition = _frame(filas)
    tabla = event_rate_by_partition(
        bin_frame=bin_frame,
        target=target,
        partition=partition,
        tables=_tablas("[0, 1)", "[1, 2)", "[2, inf)"),
        trends={"x": "ascending"},
    )
    oot = tabla[tabla["partition"] == "oot"].set_index("bin_label")
    assert oot.index.tolist() == ["[0, 1)", "[1, 2)", "[2, inf)"]
    assert oot.loc["[1, 2)", "n"] == 0 and oot.loc["[1, 2)", "n_bad"] == 0
    assert pd.isna(oot.loc["[1, 2)", "event_rate"])
    assert oot["inverts"].isna().all()


def test_special_y_missing_se_publican_pero_no_se_comparan() -> None:
    n = MIN_FILAS_POR_TRAMO
    filas = (
        _repetir("[0, 1)", "desarrollo", n, 2)
        + _repetir("Special", "desarrollo", n, 25)
        + _repetir("[1, inf)", "desarrollo", n, 10)
        + _repetir("Missing", "desarrollo", n, 0)
    )
    bin_frame, target, partition = _frame(filas)
    tabla = event_rate_by_partition(
        bin_frame=bin_frame,
        target=target,
        partition=partition,
        tables=_tablas("[0, 1)", "[1, inf)"),
        trends={"x": "ascending"},
    )
    por_tramo = tabla.set_index("bin_label")
    assert set(por_tramo.index) == {"[0, 1)", "[1, inf)", "Special", "Missing"}
    assert pd.isna(por_tramo.loc["Special", "inverts"])
    assert pd.isna(por_tramo.loc["Missing", "inverts"])
    # [1, inf) sube respecto de [0, 1): con tendencia ascendente no invierte, y Special no medió.
    assert not bool(por_tramo.loc["[1, inf)", "inverts"])
    assert por_tramo.loc["Special", "event_rate"] == pytest.approx(25 / n)


def test_sin_tendencia_monotona_no_hay_veredicto_pero_si_tasas() -> None:
    n = MIN_FILAS_POR_TRAMO
    filas = _repetir("[a]", "desarrollo", n, 3) + _repetir("[b]", "desarrollo", n, 9)
    bin_frame, target, partition = _frame(filas)
    # Las etiquetas categóricas del bin_frame llevan comillas; la tabla no.
    bin_frame["x__bin"] = bin_frame["x__bin"].map({"[a]": "['a']", "[b]": "['b']"}).astype("string")
    tabla = event_rate_by_partition(
        bin_frame=bin_frame,
        target=target,
        partition=partition,
        tables=_tablas("[a]", "[b]"),
        trends={},
    )
    assert tabla["inverts"].isna().all()
    assert tabla["bin_id"].tolist() == [0, 1]
    assert tabla["event_rate"].tolist() == pytest.approx([3 / n, 9 / n])


def test_los_dos_artefactos_estan_declarados_en_provides_y_bin_frame_es_opcional() -> None:
    assert ("binning", "event_rate_by_partition") in BinningStep.provides
    # Tras el diagnóstico sólo vienen claves aditivas posteriores (D-TTD-2, D-TTD-5, D-CPY-3).
    posteriores = BINNING_ARTIFACTS[BINNING_ARTIFACTS.index("event_rate_by_partition") + 1 :]
    assert posteriores == ("out_of_model_woe_frame", "unseen_categories", "bin_edges")
    assert ("selection", "iv_by_partition") in SelectionStep.provides
    assert SELECTION_ARTIFACTS[-1] == "iv_by_partition"
    assert SelectionStep.optional_requires == (("binning", "bin_frame"),)
    assert ("binning", "bin_frame") not in SelectionStep.requires
