"""Tests de ``ValidationEvaluator`` (SDD-22 §4/§7): orquestación, goldens y ramas defensivas.

Cubre: la secuencia canónica §7 sobre un scorecard (discriminación/calibración/estabilidad) y sobre
un modelo IFRS 9 (backtesting), el semáforo recomputado con los cortes de config (nitpick B22.3) y
umbrales técnicos tomados de la config del evaluador (nitpicks B22.4/B22.5), la traducción de celdas
malformadas a ``ValidationDataError`` (nitpick B22.5) y la ausencia de ``NaN`` en los frames tidy.
"""

from __future__ import annotations

import math
from decimal import Decimal
from importlib import metadata
from typing import Any

import pandas as pd
import pytest

import nikodym.validation.evaluator as evaluator_module
from nikodym.validation.calibration_tests import binomial_by_grade, hosmer_lemeshow
from nikodym.validation.config import (
    BacktestingValidationConfig,
    CalibrationValidationConfig,
    DiscriminationValidationConfig,
    ValidationConfig,
)
from nikodym.validation.evaluator import ValidationEvaluator
from nikodym.validation.exceptions import ValidationConfigError, ValidationDataError
from nikodym.validation.results import (
    BacktestRecord,
    CalibrationTestRecord,
    GradeBinomialRecord,
    ValidationResult,
)

_INDEX = [f"r{i}" for i in range(120)]


def _analytic_frame(*, miscalibrated: bool = False) -> pd.DataFrame:
    """Frame analítico común: partición/target/pd_calibrated/grade sobre 120 operaciones."""
    partition = ["desarrollo"] * 60 + ["holdout"] * 30 + ["oot"] * 30
    # PD calibrada determinista en (0, 1) por operación.
    pd_calibrated = [0.02 + (index % 10) * 0.01 for index in range(120)]
    # Target: bien calibrado salvo en el modo miscalibrado (default sistemático alto).
    if miscalibrated:
        target = [1 if index % 2 == 0 else 0 for index in range(120)]
    else:
        target = [1 if index % 20 == 0 else 0 for index in range(120)]
    grade = ["A" if value < 0.06 else ("B" if value < 0.09 else "C") for value in pd_calibrated]
    return pd.DataFrame(
        {
            "partition": partition,
            "target": target,
            "pd_calibrated": pd_calibrated,
            "grade": grade,
        },
        index=_INDEX,
    )


def _fallback_frame() -> pd.DataFrame:
    """Frame con PD distintas por partición: el reúso de ``PerformanceEvaluator`` exige deciles."""
    blocks: list[pd.DataFrame] = []
    for partition, n, prefix in [("desarrollo", 60, "d"), ("holdout", 40, "h"), ("oot", 30, "o")]:
        pd_calibrated = [(index + 1) / (n + 2) for index in range(n)]
        target = [1 if index >= n // 2 else 0 for index in range(n)]
        for boundary in (n // 2 - 1, n // 2, n // 2 + 1):
            target[boundary] = 1 - target[boundary]
        blocks.append(
            pd.DataFrame(
                {
                    "partition": [partition] * n,
                    "target": target,
                    "pd_calibrated": pd_calibrated,
                    "grade": ["A"] * n,
                },
                index=[f"{prefix}{index}" for index in range(n)],
            )
        )
    return pd.concat(blocks)


def _performance_metrics() -> pd.DataFrame:
    """Artefacto ``discriminant_metrics`` de SDD-11 (columnas de §6)."""
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout", "oot"],
            "n_total": [60, 30, 30],
            "n_bad": [3, 1, 1],
            "auc": [0.78, 0.72, 0.69],
            "gini": [0.56, 0.44, 0.38],
            "ks": [0.41, 0.36, 0.31],
            "status": ["ok", "ok", "ok"],
        }
    )


def _stability_metrics(*, review: bool = True) -> pd.DataFrame:
    """Artefacto ``stability_metrics`` de SDD-11 (columnas mínimas de §6)."""
    value_holdout = 0.18 if review else 0.05
    return pd.DataFrame(
        {
            "metric": ["score_psi", "score_psi"],
            "comparison": ["dev_vs_holdout", "dev_vs_oot"],
            "feature": ["score", "score"],
            "value": [0.05, value_holdout],
        }
    )


def _config(**overrides: Any) -> ValidationConfig:
    """Config de validación con HL de 5 grupos y mínimo bajo para fixtures pequeños."""
    calibration = CalibrationValidationConfig(hl_n_groups=5, min_rows_per_group=10)
    params: dict[str, Any] = {
        "families": ("discrimination", "calibration", "stability"),
        "calibration": calibration,
    }
    params.update(overrides)
    return ValidationConfig(**params)


# ─────────────────────────── scorecard end-to-end ───────────────────────────


def test_validate_scorecard_consume_y_semaforo_con_cortes_de_config() -> None:
    """Discriminación/calibración/estabilidad producen los DTOs; semáforo con cortes config."""
    cfg = _config()
    result = ValidationEvaluator.from_config(cfg).validate(
        calibrated_pd=_analytic_frame(),
        performance_metrics=_performance_metrics(),
        stability_metrics=_stability_metrics(),
        model_ref="scorecard",
    )

    assert isinstance(result, ValidationResult)
    assert result.card.families_run == ("discrimination", "calibration", "stability")
    assert result.card.model_ref == "scorecard"
    # Discriminación consumida byte a byte del artefacto.
    assert result.discrimination_records[0].source == "performance_artifact"
    assert result.discrimination_records[0].auc == pytest.approx(0.78)
    # HL por partición: reúsa el kernel (mismo estadístico) y re-sella la partición.
    hl = [r for r in result.calibration_records if r.test == "hosmer_lemeshow"]
    assert {r.partition for r in hl} == {"desarrollo", "holdout", "oot"}
    dev = _analytic_frame()[_analytic_frame()["partition"] == "desarrollo"]
    golden = hosmer_lemeshow(dev["target"].to_numpy(), dev["pd_calibrated"].to_numpy(), n_groups=5)
    dev_hl = next(r for r in hl if r.partition == "desarrollo")
    assert dev_hl.statistic == pytest.approx(golden.statistic)
    # El semáforo se recomputa con los cortes independientes de la config.
    for grade in result.grade_records:
        assert grade.traffic_light in ("green", "amber", "red")
    assert "FALTA-DATO-VAL-2" in result.card.falta_dato
    assert "FALTA-DATO-VAL-3" in result.card.falta_dato


def test_validate_estabilidad_review_da_overall_warn() -> None:
    """Un PSI consumido en banda review empuja el ``overall_status`` a ``warn``."""
    cfg = _config(families=("stability",))
    result = ValidationEvaluator.from_config(cfg).validate(
        stability_metrics=_stability_metrics(review=True),
    )
    assert result.card.overall_status == "warn"


def test_validate_miscalibrado_da_overall_fail_y_cuenta_fallos() -> None:
    """Una PD mal calibrada rechaza el Hosmer-Lemeshow y da ``overall_status='fail'``."""
    result = ValidationEvaluator.from_config(_config()).validate(
        calibrated_pd=_analytic_frame(miscalibrated=True),
        performance_metrics=_performance_metrics(),
        stability_metrics=_stability_metrics(review=False),
    )
    hl = [r for r in result.calibration_records if r.test == "hosmer_lemeshow"]
    assert any(r.decision == "fail" for r in hl)
    assert result.card.overall_status == "fail"
    assert result.card.n_failed >= 1


def test_validate_frames_tidy_sin_nan_y_columnas_canonicas() -> None:
    """Los frames publicados nunca contienen ``NaN`` y respetan las columnas canónicas de §6."""
    result = ValidationEvaluator.from_config(_config()).validate(
        calibrated_pd=_analytic_frame(),
        performance_metrics=_performance_metrics(),
        stability_metrics=_stability_metrics(),
    )
    for frame in (result.discrimination, result.calibration, result.backtesting):
        for column in frame.columns:
            for value in frame[column].tolist():
                assert not (isinstance(value, float) and math.isnan(value)), column


def test_validate_reproducible_bit_identical() -> None:
    """Dos corridas con los mismos insumos producen tablas idénticas (determinismo §9)."""

    def run() -> dict[str, Any]:
        result = ValidationEvaluator.from_config(_config()).validate(
            calibrated_pd=_analytic_frame(),
            performance_metrics=_performance_metrics(),
            stability_metrics=_stability_metrics(),
        )
        return {
            "calibration": result.calibration.to_dict("split"),
            "discrimination": result.discrimination.to_dict("split"),
            "card": result.card.model_dump(mode="json"),
        }

    assert run() == run()


# ─────────────────────────── discriminación (reúso / fallback) ───────────────────────────


def test_validate_discriminacion_fallback_reusa_performance_evaluator() -> None:
    """Con ``consume_performance=False`` la discriminación reúsa ``PerformanceEvaluator``."""
    cfg = _config(
        families=("discrimination",),
        discrimination=DiscriminationValidationConfig(consume_performance=False),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_fallback_frame())
    assert result.discrimination_records
    assert all(r.source == "recomputed" for r in result.discrimination_records)


def test_validate_discriminacion_fallback_sin_frame_falla() -> None:
    """El fallback de discriminación exige el frame analítico; su ausencia es error de datos."""
    cfg = _config(
        families=("discrimination",),
        discrimination=DiscriminationValidationConfig(consume_performance=False),
    )
    with pytest.raises(ValidationDataError, match="frame de PD calibrada"):
        ValidationEvaluator.from_config(cfg).validate(calibrated_pd=None)


def test_validate_discriminacion_celda_malformada_es_validation_data_error() -> None:
    """Una celda malformada del artefacto consumido se traduce a ``ValidationDataError``."""
    cfg = _config(families=("discrimination",))
    metrics = _performance_metrics()
    metrics["n_total"] = metrics["n_total"].astype(object)
    metrics.loc[0, "n_total"] = "no-numérico"
    with pytest.raises(ValidationDataError, match="celdas malformadas"):
        ValidationEvaluator.from_config(cfg).validate(
            calibrated_pd=_analytic_frame(), performance_metrics=metrics
        )


# ─────────────────────────── calibración ───────────────────────────


def test_validate_calibracion_sin_frame_falla() -> None:
    """La calibración exige el frame de PD calibrada."""
    cfg = _config(families=("calibration",))
    with pytest.raises(ValidationDataError, match="frame de PD calibrada"):
        ValidationEvaluator.from_config(cfg).validate(calibrated_pd=None)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("drop_pd", "requiere la columna 'pd_calibrated'"),
        ("empty", "no puede estar vacío"),
        ("pd_out_of_range", "intervalo abierto"),
        ("target_non_binary", "binaria 0/1"),
    ],
)
def test_validate_calibracion_frame_invalido(mutation: str, match: str) -> None:
    """El frame analítico de calibración rechaza columnas ausentes, vacío, PD y target inválidos."""
    frame = _analytic_frame()
    if mutation == "drop_pd":
        frame = frame.drop(columns=["pd_calibrated"])
    elif mutation == "empty":
        frame = frame.iloc[0:0]
    elif mutation == "pd_out_of_range":
        frame.loc["r0", "pd_calibrated"] = 1.0
    else:
        frame.loc["r0", "target"] = 2
    cfg = _config(families=("calibration",))
    with pytest.raises(ValidationDataError, match=match):
        ValidationEvaluator.from_config(cfg).validate(calibrated_pd=frame)


def test_validate_calibracion_hl_bajo_minimo_es_not_evaluable() -> None:
    """Una partición con menos filas que ``min_rows_per_group`` deja el HL ``not_evaluable``."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=40, binomial_by_grade=False
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    hl = [r for r in result.calibration_records if r.test == "hosmer_lemeshow"]
    holdout = next(r for r in hl if r.partition == "holdout")  # 30 filas < 40
    assert holdout.decision == "not_evaluable"
    assert holdout.p_value is None


def test_validate_calibracion_sin_binomial_ni_brier_solo_hl() -> None:
    """Con binomial/Brier apagados sólo se publican filas Hosmer-Lemeshow."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=10, brier=False, binomial_by_grade=False
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    assert {r.test for r in result.calibration_records} == {"hosmer_lemeshow"}
    assert result.grade_records == ()
    assert result.card.falta_dato == ()


def test_validate_calibracion_binomial_bcbs_no_marca_jeffreys() -> None:
    """El test binomial (BCBS) marca sólo FALTA-DATO-VAL-2 (semáforo), no el de Jeffreys."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=10, pd_test="binomial"
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    assert result.card.falta_dato == ("FALTA-DATO-VAL-2",)
    assert all(r.z_stat is not None for r in result.grade_records)


def _thin_grade_frame() -> pd.DataFrame:
    """Frame con un grado delgado (``n=3``, 2 defaults sobre PD baja) y un grado sano (``n=60``).

    El grado ``thin`` subestima brutalmente la PD: ``binomial_by_grade`` le daría semáforo rojo
    (→ fail) sin la puerta ``min_rows``. El grado ``bulk`` está bien calibrado (verde).
    """
    thin = {"partition": ["desarrollo"] * 3, "target": [1, 1, 0], "pd_calibrated": [0.05] * 3}
    # bulk: 60 obligados, PD 0.05, 2 defaults (dr 0.033 <= 0.05) → bien/conservador → verde.
    bulk = {
        "partition": ["desarrollo"] * 60,
        "target": [1 if index < 2 else 0 for index in range(60)],
        "pd_calibrated": [0.05] * 60,
    }
    frame = pd.DataFrame(
        {
            "partition": thin["partition"] + bulk["partition"],
            "target": thin["target"] + bulk["target"],
            "pd_calibrated": thin["pd_calibrated"] + bulk["pd_calibrated"],
            "grade": ["thin"] * 3 + ["bulk"] * 60,
        },
        index=[f"t{i}" for i in range(63)],
    )
    return frame


def test_validate_grado_bajo_minimo_no_contamina_verdicto() -> None:
    """Regresión B22.6: un grado sin potencia (n < min_rows) queda not_evaluable, no voltea fail.

    Un grado delgado (pocos obligados, defaults altos) que SIN la puerta ``min_rows`` obtendría
    semáforo rojo → ``fail`` NO debe emitir semáforo/decisión engañosa, ni voltear el verdicto a
    ``fail``, ni inflar ``n_failed``: queda ``not_evaluable`` auditado (SDD-22 §6/§7.4d/§8).
    """
    frame = _thin_grade_frame()
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=30, brier=False, hosmer_lemeshow=False
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=frame)

    # El grado delgado NO aparece entre los grade_records evaluables (sin semáforo engañoso).
    assert {r.grade for r in result.grade_records} == {"bulk"}
    assert all(r.traffic_light == "green" for r in result.grade_records)
    # Queda auditado como not_evaluable en la puerta CT-2, con conteos honestos y sin semáforo.
    not_evaluable = result.card.metric_sections["validation"]["not_evaluable_grades"]
    assert [g["grade"] for g in not_evaluable] == ["thin"]
    assert not_evaluable[0]["n"] == 3 and not_evaluable[0]["status"] == "not_evaluable"
    assert "traffic_light" not in not_evaluable[0] and "p_value" not in not_evaluable[0]
    # No contamina el verdicto ni el conteo de fallos/tests.
    assert result.card.overall_status != "fail"
    assert result.card.n_failed == 0
    assert result.card.n_tests == 1  # sólo el grado sano cuenta como test
    # El frame tidy no publica el grado delgado (paralelo frame↔records intacto).
    assert list(result.calibration["grade"]) == ["bulk"]
    # Prueba de que SIN la puerta el grado delgado habría sido rojo → fail: el kernel lo marca rojo.
    raw = binomial_by_grade(
        frame,
        grade_col="grade",
        pd_col="pd_calibrated",
        target_col="target",
        test="jeffreys",
        alpha=0.05,
    )
    thin_raw = next(r for r in raw if r.grade == "thin")
    assert thin_raw.n == 3 and thin_raw.traffic_light == "red"


# ─────────────────────────── estabilidad ───────────────────────────


def test_validate_estabilidad_celda_malformada_es_validation_data_error() -> None:
    """Una celda de PSI no numérica en el artefacto consumido se traduce a error de datos."""
    cfg = _config(families=("stability",))
    metrics = _stability_metrics()
    metrics["value"] = metrics["value"].astype(object)
    metrics.loc[0, "value"] = "no-numérico"
    with pytest.raises(ValidationDataError, match="celdas malformadas"):
        ValidationEvaluator.from_config(cfg).validate(stability_metrics=metrics)


# ─────────────────────────── backtesting ───────────────────────────


def _ifrs9_detail(*, decimals: bool = True) -> pd.DataFrame:
    """Artefacto ``provisioning_ifrs9.detail`` con row_id/portfolio/pd_12m/lgd/ead (SDD-16 §6)."""
    n = 80
    segment = ["retail"] * 40 + ["sme"] * 40
    pd_est: list[Any] = [Decimal("0.05")] * n if decimals else [0.05] * n
    lgd_est: list[Any] = [Decimal("0.45")] * n if decimals else [0.45] * n
    ead_est: list[Any] = [Decimal("1000")] * n if decimals else [1000.0] * n
    return pd.DataFrame(
        {
            "row_id": [f"r{i}" for i in range(n)],
            "portfolio": segment,
            "pd_12m": pd_est,
            "lgd": lgd_est,
            "ead": ead_est,
        },
        index=[f"r{i}" for i in range(n)],
    )


def _realised(*, underestimated: bool = True) -> pd.DataFrame:
    """Columnas de resultado realizado con **dispersión genuina**, alineadas al ``detail``.

    LGD/EAD varían por operación (spread real) sesgados por encima de lo estimado cuando
    ``underestimated``: el t-test tiene desviación muestral genuina y no depende de ruido de punto
    flotante (evita el falso rechazo de dispersión estructural cero).
    """
    n = 80
    shift = 0.05 if underestimated else 0.0
    spread = [0.02 * ((index % 3) - 1) for index in range(n)]
    return pd.DataFrame(
        {
            "realised_default": [1.0 if index % 20 == 0 else 0.0 for index in range(n)],
            "realised_lgd": [0.45 + shift + spread[index] for index in range(n)],
            "realised_ead": [
                1000.0 + shift * 1000.0 + 1000.0 * spread[index] for index in range(n)
            ],
        },
        index=[f"r{i}" for i in range(n)],
    )


def test_validate_backtesting_ttest_y_binomial_por_segmento() -> None:
    """El backtesting corre t-test para LGD/EAD y binomial/Jeffreys para PD por segmento (§7)."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=_ifrs9_detail(), realised=_realised(underestimated=True)
    )
    tests = {(r.parameter, r.segment): r for r in result.backtest_records}
    assert set(tests) == {
        ("pd", "retail"),
        ("pd", "sme"),
        ("lgd", "retail"),
        ("lgd", "sme"),
        ("ead", "retail"),
        ("ead", "sme"),
    }
    assert tests[("lgd", "retail")].test == "t_test"
    assert tests[("pd", "retail")].test == "jeffreys"
    # Dispersión genuina + sesgo al alza → el t-test de LGD rechaza legítimamente (no por ruido).
    assert tests[("lgd", "retail")].decision == "fail"
    assert "FALTA-DATO-VAL-1" in result.card.falta_dato
    assert "FALTA-DATO-VAL-3" in result.card.falta_dato


def test_validate_backtesting_constante_es_not_evaluable() -> None:
    """LGD/EAD realizados constantes → dispersión nula → ``not_evaluable`` reproducible (§8)."""
    constante = pd.DataFrame(
        {
            "realised_default": [1.0 if index % 20 == 0 else 0.0 for index in range(80)],
            "realised_lgd": [0.55] * 80,
            "realised_ead": [1100.0] * 80,
        },
        index=[f"r{i}" for i in range(80)],
    )
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=_ifrs9_detail(), realised=constante
    )
    ttest = [r for r in result.backtest_records if r.parameter in ("lgd", "ead")]
    assert ttest and all(r.decision == "not_evaluable" for r in ttest)


def test_validate_backtesting_deshabilitado_difiere_a_falta_dato() -> None:
    """Backtesting en families sin ``enabled`` y ``fail_on_falta_dato=False`` difiere el dato."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=False),
        fail_on_falta_dato=False,
    )
    result = ValidationEvaluator.from_config(cfg).validate()
    assert result.backtest_records == ()
    assert any("enabled=False" in gap for gap in result.card.falta_dato)


def test_validate_backtesting_sin_insumos_falla_con_fail_on_falta_dato() -> None:
    """Con ``fail_on_falta_dato=True`` la ausencia de insumos IFRS 9 falla ruidosamente."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True),
    )
    with pytest.raises(ValidationConfigError, match=r"provisioning_ifrs9\.detail"):
        ValidationEvaluator.from_config(cfg).validate(ifrs9_detail=None, realised=_realised())


def test_validate_backtesting_columnas_realizadas_ausentes_falla() -> None:
    """Faltan columnas de resultado realizado declaradas → ``ValidationConfigError``."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )
    realised = _realised().drop(columns=["realised_lgd"])
    with pytest.raises(ValidationConfigError, match="columnas de resultado realizado"):
        ValidationEvaluator.from_config(cfg).validate(
            ifrs9_detail=_ifrs9_detail(), realised=realised
        )


def test_validate_backtesting_columnas_estimadas_ausentes_falla() -> None:
    """Faltan columnas estimadas (SDD-16) en el detail → ``ValidationConfigError``."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )
    detail = _ifrs9_detail().drop(columns=["ead"])
    with pytest.raises(ValidationConfigError, match="columnas estimadas"):
        ValidationEvaluator.from_config(cfg).validate(ifrs9_detail=detail, realised=_realised())


def test_validate_backtesting_indices_no_alineados_falla() -> None:
    """Estimado y realizado con índices distintos → ``ValidationDataError`` (sin merge ambiguo)."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )
    realised = _realised()
    realised.index = [f"x{i}" for i in range(len(realised))]
    with pytest.raises(ValidationDataError, match="no comparten índice"):
        ValidationEvaluator.from_config(cfg).validate(
            ifrs9_detail=_ifrs9_detail(), realised=realised
        )


def test_validate_backtesting_solo_pd_no_marca_ttest() -> None:
    """Con sólo PD activo el backtesting marca Jeffreys pero no el FALTA-DATO del t-test."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(
            enabled=True, segment_col="portfolio", parameters=("pd",)
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=_ifrs9_detail(), realised=_realised()
    )
    assert "FALTA-DATO-VAL-1" not in result.card.falta_dato
    assert "FALTA-DATO-VAL-3" in result.card.falta_dato


# ─────────────────────────── ramas defensivas y helpers puros ───────────────────────────


def test_validate_sin_familias_activas_falla() -> None:
    """Un config sin familias activas no puede validar."""
    cfg = ValidationConfig(families=())
    with pytest.raises(ValidationConfigError, match="al menos una familia"):
        ValidationEvaluator.from_config(cfg).validate()


def test_deep_copy_rechaza_no_dataframe() -> None:
    """El copiado defensivo rechaza entradas que no son DataFrame."""
    with pytest.raises(ValidationDataError, match=r"pandas\.DataFrame"):
        evaluator_module._deep_copy(object())  # type: ignore[arg-type]


def test_grade_row_z_none_publica_estadistico_cero() -> None:
    """Un grado sin ``z`` asintótico (Jeffreys) publica estadístico 0.0, no ``None``."""
    record = GradeBinomialRecord(
        grade="A",
        n=40,
        expected_pd=0.05,
        observed_defaults=2,
        observed_dr=0.05,
        test="jeffreys",
        p_value=0.5,
        z_stat=None,
        alpha=0.05,
        traffic_light="green",
    )
    row = evaluator_module._grade_row(record)
    assert row["statistic"] == 0.0
    assert row["decision"] == "pass"


def test_grade_row_red_es_fail() -> None:
    """Un grado en rojo se proyecta con decisión ``fail`` en el frame tidy."""
    record = GradeBinomialRecord(
        grade="C",
        n=40,
        expected_pd=0.05,
        observed_defaults=20,
        observed_dr=0.5,
        test="binomial",
        p_value=0.0001,
        z_stat=4.0,
        alpha=0.05,
        traffic_light="red",
    )
    row = evaluator_module._grade_row(record)
    assert row["statistic"] == 4.0
    assert row["decision"] == "fail"


@pytest.mark.parametrize(
    ("green", "amber", "red", "stability_decision", "expected"),
    [
        (2, 0, 0, "pass", "pass"),
        (1, 1, 0, "pass", "warn"),
        (1, 0, 1, "pass", "fail"),
        (2, 0, 0, "warn", "warn"),
        (2, 0, 0, "fail", "fail"),
    ],
)
def test_overall_status_combinaciones(
    green: int, amber: int, red: int, stability_decision: str, expected: str
) -> None:
    """El verdicto consolidado prioriza ``fail``, luego ``warn`` (ámbar/vigilar), luego ``pass``."""
    grades = (
        tuple(_grade("green") for _ in range(green))
        + tuple(_grade("amber") for _ in range(amber))
        + tuple(_grade("red") for _ in range(red))
    )
    stability = pd.DataFrame({"decision": [stability_decision]})
    status = evaluator_module._overall_status(
        calibration_records=(),
        grade_records=grades,
        backtest_records=(),
        stability_frame=stability,
    )
    assert status == expected


def test_overall_status_backtest_fail() -> None:
    """Un backtest rechazado también empuja el verdicto a ``fail``."""
    backtest = BacktestRecord(
        parameter="lgd",
        segment="retail",
        n=40,
        predicted_mean=0.45,
        realised_mean=0.6,
        test="t_test",
        statistic=3.0,
        p_value=0.001,
        alpha=0.05,
        one_sided=True,
        decision="fail",
    )
    status = evaluator_module._overall_status(
        calibration_records=(),
        grade_records=(),
        backtest_records=(backtest,),
        stability_frame=pd.DataFrame({"decision": []}),
    )
    assert status == "fail"


def _grade(light: str) -> GradeBinomialRecord:
    """Crea un ``GradeBinomialRecord`` mínimo con un semáforo dado para tests de verdicto."""
    return GradeBinomialRecord(
        grade="A",
        n=40,
        expected_pd=0.05,
        observed_defaults=2,
        observed_dr=0.05,
        test="jeffreys",
        p_value=0.5,
        z_stat=None,
        alpha=0.05,
        traffic_light=light,  # type: ignore[arg-type]
    )


def test_dependency_versions_omite_libreria_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    """La recolección de versiones omite (no rompe) una dependencia ausente."""
    real_version = metadata.version

    def fake_version(name: str) -> str:
        if name == "scipy":
            raise metadata.PackageNotFoundError(name)
        return real_version(name)

    monkeypatch.setattr(evaluator_module.metadata, "version", fake_version)
    versions = evaluator_module._dependency_versions()
    assert "scipy" not in versions
    assert "pandas" in versions and "numpy" in versions


def test_stability_has_frame_vacio_es_falso() -> None:
    """Un frame de estabilidad vacío no registra ninguna decisión."""
    assert evaluator_module._stability_has(pd.DataFrame({"decision": []}), "fail") is False


def test_validate_calibracion_sin_hosmer_lemeshow_solo_brier() -> None:
    """Con Hosmer-Lemeshow apagado sólo se publica el Brier por partición."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=10, hosmer_lemeshow=False, binomial_by_grade=False
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    assert {r.test for r in result.calibration_records} == {"brier"}


def test_validate_backtesting_lgd_ead_sin_pd_no_marca_jeffreys() -> None:
    """Con sólo LGD/EAD el backtesting marca el t-test pero nunca el FALTA-DATO de Jeffreys."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(
            enabled=True, segment_col="portfolio", parameters=("lgd", "ead")
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=_ifrs9_detail(), realised=_realised()
    )
    assert "FALTA-DATO-VAL-1" in result.card.falta_dato
    assert "FALTA-DATO-VAL-3" not in result.card.falta_dato
    assert {r.parameter for r in result.backtest_records} == {"lgd", "ead"}


def test_validate_backtesting_realizado_ausente_falla() -> None:
    """El detail presente pero ``realised`` ausente levanta ``ValidationConfigError`` claro."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )
    with pytest.raises(ValidationConfigError, match=r"data\.frame con las columnas"):
        ValidationEvaluator.from_config(cfg).validate(ifrs9_detail=_ifrs9_detail(), realised=None)


def test_reseal_hosmer_lemeshow_not_evaluable_conserva_estado() -> None:
    """Re-sellar un HL ``not_evaluable`` sólo cambia la partición, no el veredicto."""
    record = CalibrationTestRecord(
        partition="ALL",
        test="hosmer_lemeshow",
        n_groups=5,
        degrees_of_freedom=3,
        statistic=0.0,
        p_value=None,
        alpha=None,
        decision="not_evaluable",
    )
    resealed = evaluator_module._reseal_hosmer_lemeshow(record, partition="oot", alpha=0.05)
    assert resealed.partition == "oot"
    assert resealed.decision == "not_evaluable"
    assert resealed.p_value is None


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_as_float_array_rechaza_no_finitos(value: float) -> None:
    """Una columna con valores no finitos se rechaza con error de datos propio."""
    frame = _analytic_frame()
    frame.loc["r0", "pd_calibrated"] = value
    cfg = _config(families=("calibration",))
    with pytest.raises(ValidationDataError, match="finitos"):
        ValidationEvaluator.from_config(cfg).validate(calibrated_pd=frame)


def test_as_float_array_rechaza_no_convertible() -> None:
    """Una columna no convertible a float64 se rechaza con error de datos propio."""
    frame = _analytic_frame()
    frame["pd_calibrated"] = frame["pd_calibrated"].astype(object)
    frame.loc["r0", "pd_calibrated"] = "no-numérico"
    cfg = _config(families=("calibration",))
    with pytest.raises(ValidationDataError, match="float64-compatible"):
        ValidationEvaluator.from_config(cfg).validate(calibrated_pd=frame)


def test_normalize_float_menos_cero() -> None:
    """La normalización numérica publica ``-0.0`` como ``0.0`` (reproducibilidad §9)."""
    assert evaluator_module._normalize_float(-0.0) == 0.0
    assert math.copysign(1.0, evaluator_module._normalize_float(-0.0)) == 1.0
    assert evaluator_module._normalize_float(0.5) == 0.5
