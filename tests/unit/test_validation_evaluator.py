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
from nikodym.validation.calibration_tests import binomial_by_grade, hosmer_lemeshow, traffic_light
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


#: Mínimo por grupo de los fixtures de este archivo. ``_analytic_frame`` reparte 60/30/30 filas y
#: ``hl_n_groups=5`` deja grupos de 12/6/6: desde D-VAL-17 el mínimo protege también cada grupo de
#: Hosmer-Lemeshow, así que con el mínimo 10 de antes ``holdout`` y ``oot`` quedarían sin veredicto
#: y los goldens de este archivo dejarían de medir lo que miden. Con 6 los tres HL siguen
#: evaluables y ningún número cambia (el mínimo no entra al estadístico); los grados (48/36/36)
#: tampoco se mueven.
_MIN_ROWS_FIXTURE = 6


def _config(**overrides: Any) -> ValidationConfig:
    """Config de validación con HL de 5 grupos y mínimo bajo para fixtures pequeños."""
    calibration = CalibrationValidationConfig(hl_n_groups=5, min_rows_per_group=_MIN_ROWS_FIXTURE)
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
    # D-VAL-13/15: el Jeffreys es el del BCE y el semáforo no tiene anclaje que verificar; ningún
    # código `FALTA-DATO-VAL-*` vuelve a la card.
    assert result.card.falta_dato == ()


def test_grade_records_resellan_los_cortes_del_semaforo_junto_al_color() -> None:
    """(a) de la capa A (D-VAL-15): cada fila de grado lleva los cortes con que se decidió su color,
    tomados de la config —y distintos de ``alpha`` cuando la config los separa—. El kernel había
    decidido con ``alpha``/``0.2·alpha``; el resellado reescribe color Y cortes, nunca sólo el
    color: con cortes personalizados el resultado tiene que bastar para reconstruir el semáforo."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5,
            min_rows_per_group=_MIN_ROWS_FIXTURE,
            alpha=0.05,
            traffic_light_green_alpha=0.10,
            traffic_light_red_alpha=0.02,
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    assert len(result.grade_records) == 3
    for grade in result.grade_records:
        assert grade.alpha == 0.05
        assert (grade.green_alpha, grade.red_alpha) == (0.10, 0.02)
        assert grade.traffic_light == traffic_light(grade.p_value, green_alpha=0.10, red_alpha=0.02)


def test_el_resellado_pasa_por_la_validacion_del_dto() -> None:
    """Pasada 3 de Codex: ``model_copy(update=...)`` no revalida, así que un resellado incoherente
    habría producido un record con color y cortes contradictorios sin fallar. El resellado
    construye el record de nuevo y lo valida: forzar un color falso levanta ``ValidationError``."""
    from pydantic import ValidationError

    calib = CalibrationValidationConfig(
        traffic_light_green_alpha=0.10, traffic_light_red_alpha=0.02
    )
    record = evaluator_module._reseal_traffic_light(_grade("green"), calib)
    assert (record.green_alpha, record.red_alpha) == (0.10, 0.02)
    assert record.traffic_light == "green"

    # El resellado siempre decide un color coherente con el p-valor, así que la incoherencia que
    # demuestra que VALIDA es otra invariante del DTO: un ``model_copy`` que dejó más incumplidas
    # que operaciones pasa en silencio y el resellado lo acusa.
    roto = _grade("green").model_copy(update={"observed_defaults": 999})
    with pytest.raises(ValidationError, match="observed_defaults no puede exceder"):
        evaluator_module._reseal_traffic_light(roto, calib)


def test_la_tabla_y_la_card_publican_los_cortes_solo_cuando_corrio_el_contraste() -> None:
    """(b) de la capa A (D-VAL-15): ``calibration`` gana ``green_alpha``/``red_alpha`` al final
    —llenas en las filas de grado, nulas en Hosmer-Lemeshow y Brier— y
    ``metric_sections.validation.traffic_light_cuts`` lleva los dos cortes con el contraste por
    grado corrido y ``None`` sin él (la clave está siempre, como ``not_evaluable_grades``)."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5,
            min_rows_per_group=_MIN_ROWS_FIXTURE,
            traffic_light_green_alpha=0.10,
            traffic_light_red_alpha=0.02,
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    table = result.calibration
    assert list(table.columns)[-3:] == ["green_alpha", "red_alpha", "not_evaluable_reason"]
    por_grado = table[table["grade"] != "ALL"]
    assert por_grado["green_alpha"].tolist() == [0.10] * 3
    assert por_grado["red_alpha"].tolist() == [0.02] * 3
    agregadas = table[table["grade"] == "ALL"]
    assert agregadas["green_alpha"].tolist() == [None] * len(agregadas)
    assert agregadas["red_alpha"].tolist() == [None] * len(agregadas)
    section = result.card.metric_sections["validation"]
    assert section["traffic_light_cuts"] == {"green_alpha": 0.10, "red_alpha": 0.02}

    apagado = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=_MIN_ROWS_FIXTURE, binomial_by_grade=False
        ),
    )
    sin_contraste = ValidationEvaluator.from_config(apagado).validate(
        calibrated_pd=_analytic_frame()
    )
    assert "traffic_light_cuts" in sin_contraste.card.metric_sections["validation"]
    assert sin_contraste.card.metric_sections["validation"]["traffic_light_cuts"] is None
    assert list(sin_contraste.calibration.columns)[-3:] == [
        "green_alpha",
        "red_alpha",
        "not_evaluable_reason",
    ]
    assert sin_contraste.calibration["green_alpha"].tolist() == [None] * len(
        sin_contraste.calibration
    )


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
    """Una partición con menos filas que ``min_rows_per_group`` deja el HL ``not_evaluable``, con
    ``statistic`` nulo y la causa ``partition_below_min``; y desde D-VAL-17 una partición que sí
    cumple pero cuyos grupos no (60 filas en 5 grupos de 12 < 40) queda sin veredicto por
    ``group_below_min``."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=40, binomial_by_grade=False
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    hl = {r.partition: r for r in result.calibration_records if r.test == "hosmer_lemeshow"}
    holdout = hl["holdout"]  # 30 filas < 40
    assert holdout.decision == "not_evaluable"
    assert holdout.p_value is None
    assert holdout.statistic is None
    assert holdout.not_evaluable_reason == "partition_below_min"
    desarrollo = hl["desarrollo"]  # 60 filas >= 40, pero grupos de 12 < 40
    assert desarrollo.decision == "not_evaluable"
    assert desarrollo.statistic is None
    assert desarrollo.not_evaluable_reason == "group_below_min"
    # La tabla tidy dice lo mismo: estadístico nulo (nunca 0.0) y la causa en su columna.
    filas = result.calibration.set_index(["partition", "test"])
    assert filas.loc[("holdout", "hosmer_lemeshow"), "statistic"] is None
    assert filas.loc[("holdout", "hosmer_lemeshow"), "not_evaluable_reason"] == (
        "partition_below_min"
    )
    assert filas.loc[("desarrollo", "brier"), "not_evaluable_reason"] is None
    # Y la card enumera las tres particiones con su causa y sus números (la prosa y el panel leen
    # de aquí); sin grupos formados, ``min_group_size`` va nulo.
    section = result.card.metric_sections["validation"]
    assert section["not_evaluable_partitions"] == [
        {
            "partition": "desarrollo",
            "n": 60,
            "n_groups": 5,
            "min_group_size": 12,
            "min_rows": 40,
            "reason": "group_below_min",
        },
        {
            "partition": "holdout",
            "n": 30,
            "n_groups": 5,
            "min_group_size": None,
            "min_rows": 40,
            "reason": "partition_below_min",
        },
        {
            "partition": "oot",
            "n": 30,
            "n_groups": 5,
            "min_group_size": None,
            "min_rows": 40,
            "reason": "partition_below_min",
        },
    ]


def _particiones_de_cien() -> pd.DataFrame:
    """Tres particiones de 100 operaciones bien calibradas (PD 0,1; un default cada diez)."""
    n = 300
    return pd.DataFrame(
        {
            "partition": ["desarrollo"] * 100 + ["holdout"] * 100 + ["oot"] * 100,
            "target": [1 if index % 10 == 0 else 0 for index in range(n)],
            "pd_calibrated": [0.1] * n,
            "grade": ["A"] * n,
        },
        index=[f"c{i}" for i in range(n)],
    )


def test_validate_hl_con_grupos_bajo_el_minimo_queda_sin_veredicto_y_fuera_del_conteo() -> None:
    """D-VAL-17 con los defaults (10 grupos, mínimo 30): una partición de 100 operaciones recibía
    veredicto con grupos de 10 (§0-21 del scorecard completo). Ahora queda ``not_evaluable`` con
    su causa, ``n_tests`` no la cuenta y la card la enumera."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(binomial_by_grade=False),
    )
    frame = _particiones_de_cien().iloc[:100]
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=frame)
    hl = next(r for r in result.calibration_records if r.test == "hosmer_lemeshow")
    assert hl.decision == "not_evaluable"
    assert hl.statistic is None
    assert hl.not_evaluable_reason == "group_below_min"
    assert result.card.n_tests == 0
    assert result.card.n_failed == 0
    assert result.card.metric_sections["validation"]["not_evaluable_partitions"] == [
        {
            "partition": "desarrollo",
            "n": 100,
            "n_groups": 10,
            "min_group_size": 10,
            "min_rows": 30,
            "reason": "group_below_min",
        }
    ]
    # Con 300 operaciones los grupos son de 30 y el HL se evalúa como siempre.
    sobre_el_minimo = ValidationEvaluator.from_config(cfg).validate(
        calibrated_pd=_particiones_de_cien().assign(partition="desarrollo")
    )
    hl_ok = next(r for r in sobre_el_minimo.calibration_records if r.test == "hosmer_lemeshow")
    assert hl_ok.decision == "pass"
    assert hl_ok.statistic == pytest.approx(0.0, abs=1e-12)  # ajuste perfecto, con su redondeo
    assert sobre_el_minimo.card.n_tests == 1
    assert sobre_el_minimo.card.metric_sections["validation"]["not_evaluable_partitions"] == []


def test_validate_sin_ninguna_prueba_evaluable_no_dice_pasa() -> None:
    """§8-9: 100 filas por partición, 10 grupos, mínimo 30 y sólo calibración → todos los HL sin
    veredicto, ``n_tests == 0`` y estado ``not_evaluable``, nunca ``pass``.

    Control negativo preespecificado: devolver ``pass`` con ``n_tests == 0`` pone esto rojo.
    """
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(binomial_by_grade=False),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_particiones_de_cien())
    hl = [r for r in result.calibration_records if r.test == "hosmer_lemeshow"]
    assert len(hl) == 3 and all(r.decision == "not_evaluable" for r in hl)
    assert result.card.n_tests == 0
    assert result.card.overall_status == "not_evaluable"
    assert result.card.metric_sections["validation"]["overall_status"] == "not_evaluable"
    assert [
        p["partition"]
        for p in result.card.metric_sections["validation"]["not_evaluable_partitions"]
    ] == ["desarrollo", "holdout", "oot"]


def test_validate_solo_backtests_sin_potencia_es_not_evaluable() -> None:
    """Sólo backtesting con LGD/EAD constantes (dispersión nula) y PD estimada en cero (varianza
    binomial nula) → ninguna decisión evaluable: ``n_tests == 0`` y ``not_evaluable``.

    Hallazgo 1 de la pasada 8 de Codex sobre la enmienda: ``n_tests`` contaba también los
    backtests ``not_evaluable`` y el consolidado caía en ``pass``. Control negativo: volver a
    contarlos pone esto rojo.
    """
    detail = _ifrs9_detail(decimals=False)
    detail["pd_12m"] = 0.0
    constante = pd.DataFrame(
        {
            "realised_default": [0.0] * 80,
            "realised_lgd": [0.55] * 80,
            "realised_ead": [1100.0] * 80,
        },
        index=[f"r{i}" for i in range(80)],
    )
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )
    result = ValidationEvaluator.from_config(cfg).validate(ifrs9_detail=detail, realised=constante)
    assert result.backtest_records and all(
        r.decision == "not_evaluable" for r in result.backtest_records
    )
    assert result.card.n_tests == 0
    assert result.card.n_failed == 0
    assert result.card.overall_status == "not_evaluable"


def test_validate_mixto_un_backtest_evaluable_decide_y_la_cobertura_lo_dice() -> None:
    """Un backtest evaluable junto a HL sin veredicto: el estado es el del evaluable y
    ``n_tests`` cuenta 1 (la cobertura del panel dice «1 de N»)."""
    cfg = _config(
        families=("calibration", "backtesting"),
        calibration=CalibrationValidationConfig(binomial_by_grade=False),
        backtesting=BacktestingValidationConfig(
            enabled=True, segment_col="portfolio", parameters=("lgd",)
        ),
    )
    detail = _ifrs9_detail(decimals=False).assign(portfolio="retail")
    result = ValidationEvaluator.from_config(cfg).validate(
        calibrated_pd=_particiones_de_cien(),
        ifrs9_detail=detail,
        realised=_realised(underestimated=True),
    )
    assert all(
        r.decision == "not_evaluable"
        for r in result.calibration_records
        if r.test == "hosmer_lemeshow"
    )
    assert [r.decision for r in result.backtest_records] == ["fail"]
    assert (result.card.n_tests, result.card.n_failed) == (1, 1)
    assert result.card.overall_status == "fail"


def test_validate_con_estabilidad_evaluable_y_sin_pruebas_el_estado_es_el_de_la_estabilidad() -> (
    None
):
    """Con ``n_tests == 0`` pero un PSI en banda de revisión, el estado sigue siendo ``warn``."""
    cfg = _config(
        families=("calibration", "stability"),
        calibration=CalibrationValidationConfig(binomial_by_grade=False),
    )
    result = ValidationEvaluator.from_config(cfg).validate(
        calibrated_pd=_particiones_de_cien(), stability_metrics=_stability_metrics(review=True)
    )
    assert result.card.n_tests == 0
    assert result.card.overall_status == "warn"


def test_test_counts_excluye_las_decisiones_no_evaluables_de_las_cuatro_familias() -> None:
    """``n_tests``/``n_failed`` cuentan decisiones evaluables: ni el Brier, ni un HL sin veredicto,
    ni un backtest ``not_evaluable`` entran."""
    hl_ok = CalibrationTestRecord(
        partition="desarrollo",
        test="hosmer_lemeshow",
        n_groups=10,
        degrees_of_freedom=8,
        statistic=20.0,
        p_value=0.01,
        alpha=0.05,
        decision="fail",
    )
    hl_ne = CalibrationTestRecord(
        partition="oot",
        test="hosmer_lemeshow",
        n_groups=10,
        degrees_of_freedom=8,
        statistic=None,
        p_value=None,
        alpha=None,
        decision="not_evaluable",
        not_evaluable_reason="group_below_min",
    )
    brier = CalibrationTestRecord(
        partition="oot",
        test="brier",
        n_groups=None,
        degrees_of_freedom=None,
        statistic=0.1,
        p_value=None,
        alpha=None,
        decision="not_evaluable",
    )
    bt_ne = BacktestRecord(
        parameter="lgd",
        segment="retail",
        n=40,
        predicted_mean=0.45,
        realised_mean=0.45,
        test="t_test",
        statistic=0.0,
        p_value=1.0,
        alpha=0.05,
        one_sided=True,
        decision="not_evaluable",
    )
    n_tests, n_failed = evaluator_module._test_counts(
        calibration_records=(hl_ok, hl_ne, brier),
        grade_records=(_grade("red"),),
        backtest_records=(bt_ne,),
    )
    assert (n_tests, n_failed) == (2, 2)
    assert (
        evaluator_module._overall_status(
            calibration_records=(hl_ne, brier),
            grade_records=(),
            backtest_records=(bt_ne,),
            stability_frame=pd.DataFrame({"decision": ["not_evaluable"]}),
        )
        == "not_evaluable"
    )


def test_validate_calibracion_sin_binomial_ni_brier_solo_hl() -> None:
    """Con binomial/Brier apagados sólo se publican filas Hosmer-Lemeshow."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5,
            min_rows_per_group=_MIN_ROWS_FIXTURE,
            brier=False,
            binomial_by_grade=False,
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    assert {r.test for r in result.calibration_records} == {"hosmer_lemeshow"}
    assert result.grade_records == ()
    assert result.card.falta_dato == ()


def test_validate_calibracion_binomial_bcbs_sigue_sin_marca() -> None:
    """El test binomial (BCBS WP14) coincide con la fuente y no lleva marca; con D-VAL-15 tampoco
    la lleva ya el semáforo, así que la card sale sin aviso alguno."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=_MIN_ROWS_FIXTURE, pd_test="binomial"
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    assert result.card.falta_dato == ()
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
    # D-VAL-13/14: el t-test y el Jeffreys son los del BCE (cotejo de §2 de la enmienda); el
    # backtesting que corrió no declara ninguna brecha del motor.
    assert result.card.falta_dato == ()


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


def test_validate_backtesting_columnas_estimadas_ausentes_marca_brecha_del_motor() -> None:
    """Sin las columnas que produce IFRS 9, la carencia es de Nikodym: ``FALTA-DATO``.

    Rotularla ``DATO-INSTITUCIONAL`` diría que el dato lo debe aportar el banco, y lo que falta es
    una salida del propio motor.
    """
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
        fail_on_falta_dato=False,
    )
    detail = _ifrs9_detail().drop(columns=["ead"])
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=detail, realised=_realised()
    )
    aviso = next(gap for gap in result.card.falta_dato if "columnas estimadas" in gap)
    assert aviso.startswith("FALTA-DATO:")


def test_validate_backtesting_columnas_realizadas_ausentes_marca_input_institucional() -> None:
    """Las columnas de resultado realizado las trae el banco: ``DATO-INSTITUCIONAL``."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
        fail_on_falta_dato=False,
    )
    realised = _realised().drop(columns=["realised_lgd"])
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=_ifrs9_detail(), realised=realised
    )
    aviso = next(gap for gap in result.card.falta_dato if "resultado realizado" in gap)
    assert aviso.startswith("DATO-INSTITUCIONAL:")


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


def test_validate_backtesting_solo_pd_no_declara_brechas() -> None:
    """Con sólo PD activo el backtesting corre el Jeffreys del BCE y no declara brecha alguna."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(
            enabled=True, segment_col="portfolio", parameters=("pd",)
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=_ifrs9_detail(), realised=_realised()
    )
    assert result.card.falta_dato == ()
    assert {r.parameter for r in result.backtest_records} == {"pd"}


# ─────────────────────────── ramas defensivas y helpers puros ───────────────────────────


def test_validate_sin_familias_activas_falla() -> None:
    """Un config sin familias activas no puede validar."""
    cfg = ValidationConfig(families=())
    with pytest.raises(ValidationConfigError, match="al menos una familia"):
        ValidationEvaluator.from_config(cfg).validate()


def test_cada_familia_seleccionada_decide_que_tabla_trae_filas() -> None:
    """`families` despacha, familia por familia, y una deseleccionada no publica nada (D-SC-7).

    🔴 Es el invariante del que cuelga ``ValidationConfig.columnas_inactivas()``: si una familia
    ausente pudiera abrir columnas, declarar su sub-config inerte silenciaría el preflight sobre
    algo que el motor sí lee — el falso negativo caro de D-RAM-3. Aquí se mide en el motor, con
    los MISMOS insumos en todas las corridas: lo único que cambia es `families`.

    Se prueba en los dos sentidos por familia (con ella, hay filas; sin ella, la tabla va vacía) y
    con la card, que declara exactamente las familias corridas.
    """
    insumos: dict[str, Any] = {
        "calibrated_pd": _analytic_frame(),
        "performance_metrics": _performance_metrics(),
        "stability_metrics": _stability_metrics(),
    }
    tabla_de = {
        "discrimination": lambda r: r.discrimination,
        "calibration": lambda r: r.calibration,
        "stability": lambda r: r.stability,
    }

    for familia, tabla in tabla_de.items():
        sola = ValidationEvaluator.from_config(_config(families=(familia,))).validate(**insumos)
        assert not tabla(sola).empty, f"{familia} seleccionada y su tabla llega vacía"
        assert sola.card.families_run == (familia,)
        for otra, otra_tabla in tabla_de.items():
            if otra != familia:
                assert otra_tabla(sola).empty, (
                    f"{otra} NO está en families y su tabla trae filas: el despacho por familia "
                    "no es el que `columnas_inactivas()` supone"
                )

    # El backtesting es la cuarta y no se puede pedir sola con estos insumos —exige IFRS 9—, así
    # que su cara medida es la simétrica: sin la familia, su tabla va vacía aunque `enabled` esté
    # encendido, que es exactamente el config que §0-12 describe (flags vivos, familia fuera).
    con_flag_vivo = ValidationEvaluator.from_config(
        _config(
            families=("discrimination",),
            backtesting=BacktestingValidationConfig(enabled=True),
        )
    ).validate(**insumos)
    assert con_flag_vivo.backtesting.empty
    assert con_flag_vivo.card.families_run == ("discrimination",)


def test_deep_copy_rechaza_no_dataframe() -> None:
    """El copiado defensivo rechaza entradas que no son DataFrame."""
    with pytest.raises(ValidationDataError, match=r"pandas\.DataFrame"):
        evaluator_module._deep_copy(object())  # type: ignore[arg-type]


def test_grade_row_z_none_publica_estadistico_nulo() -> None:
    """Un grado sin ``z`` asintótico (Jeffreys) publica estadístico nulo, no un ``0.0`` que se
    leería como «observado igual a esperado» (mismo defecto que el HL sin veredicto, D-VAL-17;
    hasta entonces la columna no admitía la ausencia)."""
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
        green_alpha=0.05,
        red_alpha=0.01,
    )
    row = evaluator_module._grade_row(record)
    assert row["statistic"] is None
    assert row["decision"] == "pass"
    con_z = evaluator_module._grade_row(record.model_copy(update={"z_stat": -0.48}))
    assert con_z["statistic"] == -0.48


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
        green_alpha=0.05,
        red_alpha=0.01,
    )
    row = evaluator_module._grade_row(record)
    assert row["statistic"] == 4.0
    assert row["decision"] == "fail"
    assert (row["green_alpha"], row["red_alpha"]) == (0.05, 0.01)


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
    """Crea un ``GradeBinomialRecord`` mínimo con un semáforo dado para tests de verdicto.

    El p-valor acompaña al color: el DTO exige que los cortes (0,05/0,01) expliquen el color.
    """
    p_value = {"green": 0.5, "amber": 0.03, "red": 0.001}[light]
    return GradeBinomialRecord(
        grade="A",
        n=40,
        expected_pd=0.05,
        observed_defaults=2,
        observed_dr=0.05,
        test="jeffreys",
        p_value=p_value,
        z_stat=None,
        alpha=0.05,
        traffic_light=light,  # type: ignore[arg-type]
        green_alpha=0.05,
        red_alpha=0.01,
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
    """Un frame de estabilidad vacío no registra ninguna decisión (la regla vive en ``results``,
    junto a la consolidación que el DTO exige; el evaluador la delega)."""
    from nikodym.validation import results as results_module

    assert results_module._stability_has(pd.DataFrame({"decision": []}), "fail") is False


def test_validate_calibracion_sin_hosmer_lemeshow_solo_brier() -> None:
    """Con Hosmer-Lemeshow apagado sólo se publica el Brier por partición."""
    cfg = _config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5,
            min_rows_per_group=_MIN_ROWS_FIXTURE,
            hosmer_lemeshow=False,
            binomial_by_grade=False,
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(calibrated_pd=_analytic_frame())
    assert {r.test for r in result.calibration_records} == {"brier"}


def test_validate_backtesting_lgd_ead_sin_pd_no_declara_brechas() -> None:
    """Con sólo LGD/EAD el backtesting corre el t-test del BCE y no declara brecha alguna."""
    cfg = _config(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(
            enabled=True, segment_col="portfolio", parameters=("lgd", "ead")
        ),
    )
    result = ValidationEvaluator.from_config(cfg).validate(
        ifrs9_detail=_ifrs9_detail(), realised=_realised()
    )
    assert result.card.falta_dato == ()
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
        statistic=None,
        p_value=None,
        alpha=None,
        decision="not_evaluable",
        not_evaluable_reason="degenerate_group",
    )
    resealed = evaluator_module._reseal_hosmer_lemeshow(record, partition="oot", alpha=0.05)
    assert resealed.partition == "oot"
    assert resealed.not_evaluable_reason == "degenerate_group"
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
