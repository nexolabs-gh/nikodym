"""Tests de ``validation.stability`` (SDD-22 §3.3/§7/§11).

Cubre el contrato de reúso-no-reimplementación: el consumo del artefacto ``stability_metrics`` copia
el PSI byte a byte, el fallback por reúso de ``StabilityEvaluator`` reproduce el MISMO número que el
consumo, el mapeo de bandas PSI a verdicto (``<stable`` estable / ``[stable,review)`` vigilar /
``>=review`` redesarrollar) y un test AST que verifica que no se reimplementa el PSI (sin ``log``).
"""

from __future__ import annotations

import ast
import inspect
import math
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.validation.stability as stability
from nikodym.stability.evaluator import StabilityEvaluator
from nikodym.validation.config import StabilityValidationConfig
from nikodym.validation.exceptions import ValidationDataError
from nikodym.validation.stability import (
    evaluate_stability,
    stability_from_artifact,
    stability_recomputed,
)

_REDEVELOP_SCORES = [1, 1, 1, 1, 1, 1, 1, 1, 6, 10]
_EV_KWARGS = {
    "psi_bins": 2,
    "temporal_axis": "none",
    "include_pd_stability": True,
    "comparisons": ("dev_vs_holdout",),
}


def _two_partition_frame(holdout_scores: list[float]) -> pd.DataFrame:
    dev = pd.DataFrame(
        {
            "partition": ["desarrollo"] * 10,
            "score": [float(value) for value in range(1, 11)],
            "pd_calibrated": [round(0.01 * value, 2) for value in range(1, 11)],
        },
        index=[f"d{index}" for index in range(10)],
    )
    holdout_n = len(holdout_scores)
    holdout = pd.DataFrame(
        {
            "partition": ["holdout"] * holdout_n,
            "score": [float(value) for value in holdout_scores],
            "pd_calibrated": [0.05] * holdout_n,
        },
        index=[f"h{index}" for index in range(holdout_n)],
    )
    return pd.concat([dev, holdout])


def _stability_artifact(frame: pd.DataFrame) -> pd.DataFrame:
    evaluator = StabilityEvaluator(
        psi_stable_threshold=0.10, psi_review_threshold=0.25, **_EV_KWARGS
    )
    result = evaluator.evaluate(
        frame,
        score_column="score",
        pd_column="pd_calibrated",
        partition_column="partition",
        feature_point_columns=(),
    )
    return result.stability_metrics


def _by_key(frame: pd.DataFrame) -> dict[tuple[str, str, str], float]:
    return {
        (row.metric, row.comparison, row.feature): row.value
        for row in frame.itertuples(index=False)
    }


# ────────────────── consumo byte a byte y fallback == consumo ───────────────


def test_consumo_y_fallback_igualan_el_psi_byte_a_byte() -> None:
    frame = _two_partition_frame(_REDEVELOP_SCORES)
    artifact = _stability_artifact(frame)

    consumed = stability_from_artifact(artifact)
    recomputed = stability_recomputed(frame, feature_point_columns=(), evaluator_kwargs=_EV_KWARGS)

    art_values = {
        (metric, comparison, feature): value
        for metric, comparison, feature, value in artifact[
            ["metric", "comparison", "feature", "value"]
        ].itertuples(index=False)
    }
    consumed_values = _by_key(consumed)
    recomputed_values = _by_key(recomputed)

    assert set(consumed_values) == set(art_values)
    assert ("score_psi", "dev_vs_holdout", "score") in art_values
    for key, artifact_value in art_values.items():
        assert consumed_values[key] == float(artifact_value)  # consumo == artefacto (byte a byte)
        assert recomputed_values[key] == consumed_values[key]  # fallback == consumo

    assert set(consumed["source"]) == {"stability_artifact"}
    assert set(recomputed["source"]) == {"recomputed"}
    assert tuple(consumed.columns) == stability._STABILITY_OUTPUT_COLUMNS


def test_consumo_verdicto_coincide_con_sdd11_si_umbrales_coinciden() -> None:
    frame = _two_partition_frame(_REDEVELOP_SCORES)
    artifact = _stability_artifact(frame)

    consumed = stability_from_artifact(artifact)

    score_row = consumed[consumed["metric"] == "score_psi"].iloc[0]
    artifact_score = artifact[artifact["metric"] == "score_psi"].iloc[0]
    assert score_row["value"] == pytest.approx(0.41588831)
    assert score_row["band"] == "redevelop" == artifact_score["band"]
    assert score_row["action"] == "redesarrollar"
    assert score_row["decision"] == "fail"
    assert score_row["status"] == "ok"


# ──────────────────────── mapeo de bandas a verdicto ────────────────────────


def _psi_metrics(values: list[object]) -> pd.DataFrame:
    n = len(values)
    return pd.DataFrame(
        {
            "metric": ["score_psi"] * n,
            "comparison": ["dev_vs_holdout"] * n,
            "feature": ["score"] * n,
            "value": values,
        }
    )


def test_mapeo_de_bandas_psi_a_verdicto() -> None:
    metrics = _psi_metrics([0.0, 0.05, 0.10, 0.15, 0.25, 0.40, math.nan])

    out = stability_from_artifact(metrics)  # defaults 0.10 / 0.25

    assert out["band"].tolist() == [
        "stable",
        "stable",
        "review",
        "review",
        "redevelop",
        "redevelop",
        "not_evaluable",
    ]
    assert out["action"].tolist() == [
        "none",
        "none",
        "vigilar",
        "vigilar",
        "redesarrollar",
        "redesarrollar",
        "none",
    ]
    assert out["decision"].tolist() == [
        "pass",
        "pass",
        "warn",
        "warn",
        "fail",
        "fail",
        "not_evaluable",
    ]
    assert out["status"].tolist() == ["ok", "ok", "ok", "ok", "ok", "ok", "not_evaluable"]
    values = out["value"].tolist()
    assert values[:6] == [0.0, 0.05, 0.10, 0.15, 0.25, 0.40]  # PSI verbatim
    assert math.isnan(values[6])
    assert out["stable_threshold"].tolist() == [0.10] * 7
    assert out["review_threshold"].tolist() == [0.25] * 7


def test_valor_none_es_not_evaluable() -> None:
    metrics = pd.DataFrame(
        {
            "metric": ["score_psi", "pd_psi"],
            "comparison": ["dev_vs_holdout", "dev_vs_holdout"],
            "feature": ["score", "pd_calibrated"],
            "value": pd.Series([0.05, None], dtype=object),
        }
    )

    out = stability_from_artifact(metrics)

    assert out["band"].tolist() == ["stable", "not_evaluable"]
    assert out["status"].tolist() == ["ok", "not_evaluable"]
    assert math.isnan(out["value"].tolist()[1])


def test_umbrales_configurables_cambian_la_banda() -> None:
    metrics = _psi_metrics([0.08])

    default_out = stability_from_artifact(metrics)
    custom_out = stability_from_artifact(metrics, stable_threshold=0.05, review_threshold=0.30)

    assert default_out["band"].tolist() == ["stable"]  # 0.08 < 0.10
    assert custom_out["band"].tolist() == ["review"]  # 0.05 <= 0.08 < 0.30
    assert custom_out["stable_threshold"].tolist() == [0.05]
    assert custom_out["review_threshold"].tolist() == [0.30]


# ──────────────────────────── despachador ───────────────────────────────────


def test_despachador_consume_si_hay_artefacto() -> None:
    cfg = StabilityValidationConfig()
    artifact = _stability_artifact(_two_partition_frame(_REDEVELOP_SCORES))

    out = evaluate_stability(cfg, stability_metrics=artifact)

    assert set(out["source"]) == {"stability_artifact"}


def test_despachador_consume_stability_false_fuerza_fallback() -> None:
    cfg = StabilityValidationConfig(consume_stability=False)
    frame = _two_partition_frame(_REDEVELOP_SCORES)
    artifact = _stability_artifact(frame)

    out = evaluate_stability(
        cfg, stability_metrics=artifact, frame=frame, evaluator_kwargs=_EV_KWARGS
    )

    assert set(out["source"]) == {"recomputed"}


def test_despachador_cae_a_fallback_sin_artefacto() -> None:
    cfg = StabilityValidationConfig()
    frame = _two_partition_frame(_REDEVELOP_SCORES)

    out = evaluate_stability(cfg, frame=frame, evaluator_kwargs=_EV_KWARGS)

    assert set(out["source"]) == {"recomputed"}


def test_despachador_sin_insumos_es_error() -> None:
    cfg = StabilityValidationConfig()
    with pytest.raises(ValidationDataError, match="fallback"):
        evaluate_stability(cfg)


# ──────────────────────── validación de entradas ───────────────────────────


@pytest.mark.parametrize(
    ("stable", "review", "match"),
    [
        (0.25, 0.10, "estrictamente menor"),
        (0.10, 0.10, "estrictamente menor"),
        (-0.10, 0.25, "no pueden ser negativos"),
        (float("inf"), 0.25, "finitos"),
    ],
)
def test_umbrales_invalidos(stable: float, review: float, match: str) -> None:
    metrics = _psi_metrics([0.10])
    with pytest.raises(ValidationDataError, match=match):
        stability_from_artifact(metrics, stable_threshold=stable, review_threshold=review)


def test_from_artifact_rechaza_no_dataframe() -> None:
    with pytest.raises(ValidationDataError, match="pandas"):
        stability_from_artifact([1, 2, 3])  # type: ignore[arg-type]


def test_from_artifact_rechaza_columnas_faltantes() -> None:
    metrics = pd.DataFrame({"metric": ["score_psi"], "value": [0.10]})
    with pytest.raises(ValidationDataError, match="columnas requeridas"):
        stability_from_artifact(metrics)


# ──────────────────────────── no mutación ───────────────────────────────────


def test_from_artifact_no_muta_el_artefacto() -> None:
    metrics = _psi_metrics([0.0, 0.15, math.nan])
    original = metrics.copy(deep=True)

    stability_from_artifact(metrics)

    assert_frame_equal(metrics, original)


def test_recomputed_no_muta_el_frame() -> None:
    frame = _two_partition_frame(_REDEVELOP_SCORES)
    original = frame.copy(deep=True)

    stability_recomputed(frame, feature_point_columns=(), evaluator_kwargs=_EV_KWARGS)

    assert_frame_equal(frame, original)


# ───────────────────────── AST: no reimplementa PSI ─────────────────────────


def test_ast_no_reimplementa_psi() -> None:
    source = inspect.getsource(stability)
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)

    forbidden = {"log", "log1p", "log2", "log10"}
    assert not (called & forbidden), called & forbidden
    # Delegación explícita: la única vía de cálculo del PSI es reúsar el evaluador de SDD-11.
    assert "StabilityEvaluator" in source


# ──────────────────────────── import liviano ────────────────────────────────


def test_import_stability_no_arrastra_sklearn_ni_scipy() -> None:
    code = (
        "import sys;"
        "import nikodym.validation.stability as s;"
        "blocked=[m for m in ('scipy','sklearn','statsmodels') if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert callable(s.stability_from_artifact);"
        "assert callable(s.stability_recomputed)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
