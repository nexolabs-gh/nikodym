"""Tests de ``ValidationStep`` (SDD-22 §4/§7/§9; CT-1): integración, auditoría e import liviano.

Cubre: la integración end-to-end sobre un scorecard (discriminación/calibración/estabilidad) y sobre
un modelo IFRS 9 (backtesting sobre ``provisioning_ifrs9.detail`` + staging + ``data.frame``), el
contrato CT-1 (``requires`` dinámicos y ``ArtifactNotFoundError`` ante ausencia), la extracción del
``LabeledFrame`` de ``data.labels`` (nitpick c), el ``log_decision`` §9, la no-mutación de datos
aguas arriba, el cableado en ``core.study`` y el import liviano (registro sin pandas/scipy/sklearn).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.core.study as study_module
import nikodym.validation as validation_pkg
import nikodym.validation.step as step_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.data.target import LabeledFrame, TargetSummary
from nikodym.testing import assert_bitwise_reproducible
from nikodym.validation.config import (
    BacktestingValidationConfig,
    CalibrationValidationConfig,
    DiscriminationValidationConfig,
    ValidationConfig,
)
from nikodym.validation.exceptions import ValidationDataError
from nikodym.validation.results import ValidationResult
from nikodym.validation.step import VALIDATION_ARTIFACTS, ValidationStep

_SCORECARD_INDEX = [f"c{i}" for i in range(90)]


# ─────────────────────────── fixtures scorecard ───────────────────────────


def _pd_values() -> list[float]:
    """PD calibradas distintas y monótonas en (0, 1): el reúso de deciles exige distintas."""
    return [0.02 + index * 0.005 for index in range(90)]


def _target_values() -> list[int]:
    """Target binario determinista con una tasa de default moderada."""
    return [1 if index % 9 == 0 else 0 for index in range(90)]


def _calibrated_pd_frame() -> pd.DataFrame:
    """Artefacto ``calibration.calibrated_pd_frame`` con partición/target/pd_calibrated."""
    partition = ["desarrollo"] * 40 + ["holdout"] * 25 + ["oot"] * 25
    return pd.DataFrame(
        {"partition": partition, "target": _target_values(), "pd_calibrated": _pd_values()},
        index=_SCORECARD_INDEX,
    )


def _labeled_frame() -> LabeledFrame:
    """Artefacto ``data.labels``: un :class:`LabeledFrame` (SDD-02), no un DataFrame (nitpick c)."""
    target = _target_values()
    grade = ["A" if value < 0.12 else ("B" if value < 0.30 else "C") for value in _pd_values()]
    frame = pd.DataFrame(
        {
            "target": target,
            "grade": grade,
            "label_status": ["malo" if value else "bueno" for value in target],
        },
        index=_SCORECARD_INDEX,
    )
    summary = TargetSummary(
        class_counts={"bueno": 80, "malo": 10},
        bad_rate=10.0 / 90.0,
        exclusions_by_reason={},
        ambiguous_rows=0,
    )
    return LabeledFrame(
        frame=frame, target_col="target", status_col="label_status", summary=summary
    )


def _discriminant_metrics() -> pd.DataFrame:
    """Artefacto ``performance.discriminant_metrics`` de SDD-11 (columnas de §6)."""
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout", "oot"],
            "n_total": [40, 25, 25],
            "n_bad": [3, 2, 1],
            "auc": [0.80, 0.74, 0.70],
            "gini": [0.60, 0.48, 0.40],
            "ks": [0.45, 0.38, 0.33],
            "status": ["ok", "ok", "ok"],
        }
    )


def _stability_metrics(*, review: bool = False) -> pd.DataFrame:
    """Artefacto ``stability.stability_metrics`` de SDD-11 (columnas mínimas de §6)."""
    return pd.DataFrame(
        {
            "metric": ["score_psi", "score_psi"],
            "comparison": ["dev_vs_holdout", "dev_vs_oot"],
            "feature": ["score", "score"],
            "value": [0.05, 0.18 if review else 0.04],
        }
    )


def _psi_table() -> pd.DataFrame:
    """Artefacto ``stability.psi_table`` (requerido por CT-1, no consumido por el evaluador v1)."""
    return pd.DataFrame({"comparison": ["dev_vs_holdout"], "psi": [0.05]})


def _scorecard_config(**overrides: Any) -> ValidationConfig:
    """Config de validación de scorecard con HL de 5 grupos y mínimo bajo."""
    params: dict[str, Any] = {
        "families": ("discrimination", "calibration", "stability"),
        "calibration": CalibrationValidationConfig(hl_n_groups=5, min_rows_per_group=10),
    }
    params.update(overrides)
    return ValidationConfig(**params)


def _scorecard_study(
    *,
    config: ValidationConfig | None = None,
    review: bool = False,
    include_performance: bool = True,
    include_stability: bool = True,
) -> Study:
    """Construye un ``Study`` con los artefactos de un scorecard listo para validar."""
    cfg = config or _scorecard_config()
    study = Study(NikodymConfig(validation=cfg))
    study.artifacts.set("calibration", "calibrated_pd_frame", _calibrated_pd_frame())
    study.artifacts.set("data", "labels", _labeled_frame())
    if include_performance:
        study.artifacts.set("performance", "discriminant_metrics", _discriminant_metrics())
    if include_stability:
        study.artifacts.set("stability", "stability_metrics", _stability_metrics(review=review))
        study.artifacts.set("stability", "psi_table", _psi_table())
    return study


# ─────────────────────────── fixtures IFRS 9 ───────────────────────────

_IFRS9_ROW_IDS = [f"r{i}" for i in range(60)]


def _ifrs9_detail() -> pd.DataFrame:
    """Artefacto ``provisioning_ifrs9.detail`` con row_id/portfolio/pd_12m/lgd/ead (SDD-16 §6)."""
    segment = ["retail"] * 30 + ["sme"] * 30
    return pd.DataFrame(
        {
            "row_id": _IFRS9_ROW_IDS,
            "portfolio": segment,
            "pd_12m": [0.05] * 60,
            "lgd": [0.45] * 60,
            "ead": [1000.0] * 60,
        },
        index=[f"detail{i}" for i in range(60)],
    )


def _ifrs9_staging() -> pd.DataFrame:
    """Artefacto ``provisioning_ifrs9.staging`` (requerido por CT-1, no consumido por v1)."""
    return pd.DataFrame({"row_id": _IFRS9_ROW_IDS, "stage": [1] * 60})


def _data_frame() -> pd.DataFrame:
    """Artefacto ``data.frame`` con resultado realizado de **dispersión genuina** (real).

    LGD/EAD realizados varían por operación y quedan sesgados por encima de lo estimado (0.45/1000):
    el t-test tiene dispersión real y rechaza legítimamente, no por ruido de punto flotante.
    """
    return pd.DataFrame(
        {
            "realised_default": [1.0 if index % 12 == 0 else 0.0 for index in range(60)],
            "realised_lgd": [0.50 + 0.05 * (index % 3) for index in range(60)],
            "realised_ead": [1050.0 + 30.0 * (index % 3) for index in range(60)],
        },
        index=_IFRS9_ROW_IDS,
    )


def _data_frame_realizado_constante() -> pd.DataFrame:
    """``data.frame`` con LGD/EAD realizados **constantes**: dispersión estructural nula (§8)."""
    return pd.DataFrame(
        {
            "realised_default": [1.0 if index % 12 == 0 else 0.0 for index in range(60)],
            "realised_lgd": [0.55] * 60,
            "realised_ead": [1080.0] * 60,
        },
        index=_IFRS9_ROW_IDS,
    )


def _ifrs9_config() -> ValidationConfig:
    """Config de validación de un modelo IFRS 9: sólo backtesting activo."""
    return ValidationConfig(
        families=("backtesting",),
        backtesting=BacktestingValidationConfig(enabled=True, segment_col="portfolio"),
    )


def _ifrs9_study(*, data_frame: pd.DataFrame | None = None) -> Study:
    """Construye un ``Study`` con los artefactos IFRS 9 listos para backtesting."""
    study = Study(NikodymConfig(validation=_ifrs9_config()))
    study.artifacts.set("provisioning_ifrs9", "detail", _ifrs9_detail())
    study.artifacts.set("provisioning_ifrs9", "staging", _ifrs9_staging())
    study.artifacts.set("data", "frame", _data_frame() if data_frame is None else data_frame)
    return study


# ─────────────────────────── contrato CT-1 y registro ───────────────────────────


def test_from_config_registro_y_requires_dinamicos_scorecard() -> None:
    """``ValidationStep`` expone los ``requires`` dinámicos del scorecard y las seis claves."""
    step = ValidationStep.from_config(_scorecard_config())
    assert REGISTRY.resolve("validation", "standard") is ValidationStep
    assert validation_pkg.ValidationStep is ValidationStep
    assert step.name == "validation"
    assert step.provides == tuple(("validation", key) for key in VALIDATION_ARTIFACTS)
    assert set(step.requires) == {
        ("calibration", "calibrated_pd_frame"),
        ("data", "labels"),
        ("performance", "discriminant_metrics"),
        ("stability", "stability_metrics"),
        ("stability", "psi_table"),
    }


def test_requires_discriminacion_fallback_pide_calibracion_y_labels() -> None:
    """Con ``consume_performance=False`` la discriminación exige calibración + labels."""
    cfg = ValidationConfig(
        families=("discrimination",),
        discrimination=DiscriminationValidationConfig(consume_performance=False),
    )
    step = ValidationStep.from_config(cfg)
    assert step.requires == (("calibration", "calibrated_pd_frame"), ("data", "labels"))


def test_requires_backtesting_pide_ifrs9_y_data_frame() -> None:
    """La familia backtesting habilitada exige detail/staging/data.frame (CT-1)."""
    step = ValidationStep.from_config(_ifrs9_config())
    assert step.requires == (
        ("provisioning_ifrs9", "detail"),
        ("provisioning_ifrs9", "staging"),
        ("data", "frame"),
    )


def test_requires_backtesting_deshabilitado_no_pide_artefactos() -> None:
    """Backtesting sin ``enabled`` (diferible) no impone artefactos IFRS 9 en ``requires``."""
    cfg = ValidationConfig(
        families=("stability",),
        backtesting=BacktestingValidationConfig(enabled=False),
    )
    step = ValidationStep.from_config(cfg)
    assert step.requires == (
        ("stability", "stability_metrics"),
        ("stability", "psi_table"),
    )


def test_requires_faltante_falla_con_artifactnotfounderror() -> None:
    """Si falta un artefacto requerido, CT-1 levanta ``ArtifactNotFoundError`` claro."""
    study = _scorecard_study()
    study.artifacts._store.pop(("data", "labels"))
    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'labels'\)"):
        study.run_step("validation")


def test_execute_directo_revalida_requires_antes_de_correr() -> None:
    """``execute`` re-valida CT-1 y levanta ``ArtifactNotFoundError`` antes de leer nada."""
    study = _scorecard_study()
    study.artifacts._store.pop(("performance", "discriminant_metrics"))
    step = ValidationStep.from_config(study.config.validation)
    with pytest.raises(ArtifactNotFoundError, match=r"\('performance', 'discriminant_metrics'\)"):
        step.execute(study, np.random.default_rng(0))


def test_core_study_cablea_validation_al_final() -> None:
    """``Study`` resuelve ``validation`` como dominio perezoso al final del orden por defecto."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order[-1] == "validation"
    assert order.index("validation") > order.index("performance")
    assert order.index("validation") > order.index("stability")
    assert order.index("validation") > order.index("provisioning_ifrs9")
    assert study_module._DOMAIN_MODULES["validation"] == "nikodym.validation"
    assert study_module._DOMAIN_CONFIG_CLASSES["validation"] == (
        "nikodym.validation.config",
        "ValidationConfig",
    )
    study = _scorecard_study()
    assert isinstance(study._resolve_step("validation"), ValidationStep)


# ─────────────────────────── integración end-to-end ───────────────────────────


def test_execute_scorecard_publica_seis_artefactos_y_no_consume_rng() -> None:
    """El step valida el scorecard, publica las seis claves y no consume el ``rng``."""
    study = _scorecard_study(review=True)
    step = ValidationStep.from_config(study.config.validation)
    result = step.execute(study, np.random.default_rng(20_260_703))

    assert isinstance(result, ValidationResult)
    for key in VALIDATION_ARTIFACTS:
        assert study.artifacts.has("validation", key)
    assert result.card.model_ref == "nikodym-study"
    assert result.card.families_run == ("discrimination", "calibration", "stability")
    # Discriminación consumida del artefacto de SDD-11 (source performance_artifact).
    assert {r.source for r in result.discrimination_records} == {"performance_artifact"}
    # Estabilidad consumida (una fila por métrica PSI de SDD-11).
    assert len(result.stability) == 2
    assert result.card.overall_status in {"pass", "warn", "fail"}
    assert_frame_equal(study.artifacts.get("validation", "calibration"), result.calibration)
    assert study.artifacts.get("validation", "card") == result.card


def test_execute_ifrs9_backtesting_sobre_detail_staging_y_data_frame() -> None:
    """El step corre el backtesting IFRS 9 alineando detail por row_id con data.frame."""
    study = _ifrs9_study()
    step = ValidationStep.from_config(study.config.validation)
    result = step.execute(study, np.random.default_rng(1))

    assert result.card.families_run == ("backtesting",)
    tests = {(r.parameter, r.segment) for r in result.backtest_records}
    assert tests == {
        ("pd", "retail"),
        ("pd", "sme"),
        ("lgd", "retail"),
        ("lgd", "sme"),
        ("ead", "retail"),
        ("ead", "sme"),
    }
    # LGD/EAD realizados > estimados con dispersión genuina → t-test rechaza legítimamente.
    lgd = next(r for r in result.backtest_records if r.parameter == "lgd" and r.segment == "retail")
    assert lgd.decision == "fail"
    assert study.artifacts.has("validation", "backtesting")


def test_execute_ifrs9_backtesting_realizado_constante_es_not_evaluable() -> None:
    """LGD/EAD realizados constantes (dispersión estructural nula) → ``not_evaluable``, no ``fail``.

    Guarda contra el bug de reproducibilidad: dos parámetros con dispersión REAL cero (LGD y
    EAD, con errores estructuralmente idénticos) reciben el MISMO veredicto ``not_evaluable``, sin
    que el residuo ~1e-17 de la cancelación catastrófica los rechace por ruido (SDD-22 §8).
    """
    study = _ifrs9_study(data_frame=_data_frame_realizado_constante())
    result = ValidationStep.from_config(study.config.validation).execute(
        study, np.random.default_rng(1)
    )
    ttest_records = [r for r in result.backtest_records if r.parameter in ("lgd", "ead")]
    assert ttest_records  # hay contrastes t para LGD/EAD
    assert all(r.decision == "not_evaluable" for r in ttest_records)


def test_execute_discriminacion_fallback_recomputed_audita_reuso() -> None:
    """Sin performance, la discriminación reúsa el evaluador y audita ``source='recomputed'``."""
    cfg = _scorecard_config(
        families=("discrimination",),
        discrimination=DiscriminationValidationConfig(consume_performance=False),
    )
    study = _scorecard_study(config=cfg, include_performance=False, include_stability=False)
    sink = InMemoryAuditSink()
    step = ValidationStep.from_config(cfg)
    step._audit = sink
    result = step.execute(study, np.random.default_rng(2))

    assert {r.source for r in result.discrimination_records} == {"recomputed"}
    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "discrimination_source" in rules


def test_execute_emite_log_decision_semaforo_hl_backtest_y_falta_dato() -> None:
    """El step emite las decisiones §9: semáforo, HL fallado, PSI review y FALTA-DATO."""
    # Cortes de semáforo agresivos para forzar bandas ámbar/rojo de forma determinista.
    cfg = _scorecard_config(
        calibration=CalibrationValidationConfig(
            hl_n_groups=5,
            min_rows_per_group=10,
            traffic_light_green_alpha=0.99,
            traffic_light_red_alpha=0.90,
        ),
    )
    study = _scorecard_study(config=cfg, review=True)
    sink = InMemoryAuditSink()
    step = ValidationStep.from_config(cfg)
    step._audit = sink
    step.execute(study, np.random.default_rng(3))

    rules = {event.payload["regla"] for event in sink.events if event.kind == "decision"}
    assert "calibration_semaforo" in rules
    assert "stability_psi" in rules
    assert "validation_falta_dato" in rules


def test_execute_audita_grado_bajo_minimo_como_not_evaluable() -> None:
    """Regresión B22.6: un grado bajo ``min_rows`` se excluye del verdicto y se audita con §9.

    Con ``min_rows_per_group=25`` el grado ``A`` (20 filas) queda sin potencia: no produce semáforo,
    no aparece en ``grade_records`` y emite ``log_decision`` ``calibration_grade_not_evaluable``.
    """
    cfg = _scorecard_config(
        families=("calibration",),
        calibration=CalibrationValidationConfig(
            hl_n_groups=5, min_rows_per_group=25, brier=False, hosmer_lemeshow=False
        ),
    )
    study = _scorecard_study(config=cfg, include_performance=False, include_stability=False)
    sink = InMemoryAuditSink()
    step = ValidationStep.from_config(cfg)
    step._audit = sink
    result = step.execute(study, np.random.default_rng(7))

    # El grado A (20 < 25) queda fuera de los grade_records evaluables y auditado not_evaluable.
    assert "A" not in {r.grade for r in result.grade_records}
    not_evaluable = result.card.metric_sections["validation"]["not_evaluable_grades"]
    assert [g["grade"] for g in not_evaluable] == ["A"]
    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "calibration_grade_not_evaluable" in rules
    # El grado sin potencia no voltea el verdicto.
    assert result.card.overall_status != "fail"


def test_execute_no_muta_artefactos_upstream() -> None:
    """Las entradas de calibración, labels, performance y stability se copian antes de validar."""
    study = _scorecard_study(review=True)
    calibrated_before = study.artifacts.get("calibration", "calibrated_pd_frame").copy(deep=True)
    labels_before = study.artifacts.get("data", "labels").frame.copy(deep=True)
    performance_before = study.artifacts.get("performance", "discriminant_metrics").copy(deep=True)
    stability_before = study.artifacts.get("stability", "stability_metrics").copy(deep=True)

    ValidationStep.from_config(study.config.validation).execute(study, np.random.default_rng(4))

    assert_frame_equal(study.artifacts.get("calibration", "calibrated_pd_frame"), calibrated_before)
    assert_frame_equal(study.artifacts.get("data", "labels").frame, labels_before)
    assert_frame_equal(
        study.artifacts.get("performance", "discriminant_metrics"), performance_before
    )
    assert_frame_equal(study.artifacts.get("stability", "stability_metrics"), stability_before)


def test_execute_ifrs9_no_muta_detail_ni_data_frame() -> None:
    """El backtesting no muta ``provisioning_ifrs9.detail`` ni ``data.frame`` aguas arriba."""
    study = _ifrs9_study()
    detail_before = study.artifacts.get("provisioning_ifrs9", "detail").copy(deep=True)
    data_before = study.artifacts.get("data", "frame").copy(deep=True)

    ValidationStep.from_config(study.config.validation).execute(study, np.random.default_rng(5))

    assert_frame_equal(study.artifacts.get("provisioning_ifrs9", "detail"), detail_before)
    assert_frame_equal(study.artifacts.get("data", "frame"), data_before)


def test_execute_reproducible_bit_identical() -> None:
    """Dos corridas del step con los mismos artefactos producen bytes idénticos (§9)."""

    def snapshot() -> dict[str, Any]:
        study = _scorecard_study(review=True)
        result = ValidationStep.from_config(study.config.validation).execute(
            study, np.random.default_rng(20_260_703)
        )
        return {
            "calibration": result.calibration.to_dict("split"),
            "discrimination": result.discrimination.to_dict("split"),
            "stability": result.stability.to_dict("split"),
            "card": result.card.model_dump(mode="json"),
        }

    assert_bitwise_reproducible(snapshot)


# ─────────────────────────── ensamblado y ramas defensivas ───────────────────────────


def test_assemble_analytic_frame_extrae_labeledframe(monkeypatch: pytest.MonkeyPatch) -> None:
    """El frame analítico toma pd/partición de calibración y target/grado del ``LabeledFrame``."""
    pd_mod = step_module._import_pandas()
    frame = step_module._assemble_analytic_frame(
        _calibrated_pd_frame(), _labeled_frame(), _scorecard_config(), pd_mod
    )
    assert list(frame.columns) == ["partition", "pd_calibrated", "target", "grade"]
    assert frame.index.equals(_calibrated_pd_frame().index)


def test_assemble_analytic_frame_sin_grade_omite_columna() -> None:
    """Si ``data.labels`` no trae grado, el frame analítico se arma sin la columna ``grade``."""
    pd_mod = step_module._import_pandas()
    labeled = _labeled_frame()
    labeled.frame.drop(columns=["grade"], inplace=True)
    frame = step_module._assemble_analytic_frame(
        _calibrated_pd_frame(), labeled, _scorecard_config(), pd_mod
    )
    assert "grade" not in frame.columns
    assert list(frame.columns) == ["partition", "pd_calibrated", "target"]


def test_read_labeled_frame_rechaza_objeto_no_labeledframe() -> None:
    """``data.labels`` que no es un LabeledFrame se rechaza con error de datos propio."""
    pd_mod = step_module._import_pandas()
    with pytest.raises(ValidationDataError, match="LabeledFrame"):
        step_module._read_labeled_frame(
            SimpleNamespace(frame=object(), target_col="target"), pd_mod
        )


def test_read_labeled_frame_rechaza_target_ausente() -> None:
    """Un LabeledFrame cuya columna target declarada no está en el frame es un error de datos."""
    pd_mod = step_module._import_pandas()
    labeled = SimpleNamespace(frame=pd.DataFrame({"grade": ["A"]}), target_col="target")
    with pytest.raises(ValidationDataError, match="columna target declarada"):
        step_module._read_labeled_frame(labeled, pd_mod)


def test_assemble_analytic_frame_calibracion_sin_columna_falla() -> None:
    """El frame de calibración sin ``pd_calibrated`` es un error de datos claro."""
    pd_mod = step_module._import_pandas()
    calibrated = _calibrated_pd_frame().drop(columns=["pd_calibrated"])
    with pytest.raises(ValidationDataError, match="columna requerida 'pd_calibrated'"):
        step_module._assemble_analytic_frame(
            calibrated, _labeled_frame(), _scorecard_config(), pd_mod
        )


def test_assemble_analytic_frame_labels_no_cubre_falla() -> None:
    """Si ``data.labels`` no cubre todas las operaciones de calibración, es error de datos."""
    pd_mod = step_module._import_pandas()
    labeled = _labeled_frame()
    labeled.frame.drop(index="c0", inplace=True)
    with pytest.raises(ValidationDataError, match="no cubre todas"):
        step_module._assemble_analytic_frame(
            _calibrated_pd_frame(), labeled, _scorecard_config(), pd_mod
        )


def test_assemble_analytic_frame_indice_duplicado_falla() -> None:
    """Un índice duplicado en la calibración impide alinear de forma reproducible."""
    pd_mod = step_module._import_pandas()
    calibrated = pd.concat([_calibrated_pd_frame(), _calibrated_pd_frame().iloc[[0]]])
    with pytest.raises(ValidationDataError, match="índice duplicado"):
        step_module._assemble_analytic_frame(
            calibrated, _labeled_frame(), _scorecard_config(), pd_mod
        )


def test_align_backtesting_sin_row_id_falla() -> None:
    """El detail sin ``row_id`` no puede alinearse con ``data.frame``."""
    pd_mod = step_module._import_pandas()  # noqa: F841 (documenta la dependencia perezosa)
    detail = _ifrs9_detail().drop(columns=["row_id"])
    with pytest.raises(ValidationDataError, match="row_id"):
        step_module._align_backtesting_inputs(detail, _data_frame())


def test_align_backtesting_data_frame_no_cubre_falla() -> None:
    """Si ``data.frame`` no cubre todas las operaciones del detail, se levanta error de datos."""
    detail = _ifrs9_detail()
    data_frame = _data_frame().drop(index="r0")
    with pytest.raises(ValidationDataError, match="no cubre todas"):
        step_module._align_backtesting_inputs(detail, data_frame)


def test_align_backtesting_indice_duplicado_falla() -> None:
    """Un ``data.frame`` con índice duplicado impide alinear el backtesting."""
    detail = _ifrs9_detail()
    data_frame = pd.concat([_data_frame(), _data_frame().iloc[[0]]])
    with pytest.raises(ValidationDataError, match="índice duplicado"):
        step_module._align_backtesting_inputs(detail, data_frame)


def test_as_dataframe_rechaza_no_dataframe() -> None:
    """Un artefacto tabular que no es DataFrame se rechaza con error de datos propio."""
    pd_mod = step_module._import_pandas()
    with pytest.raises(ValidationDataError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod, "calibration.calibrated_pd_frame")


def test_validation_config_from_study_ramas() -> None:
    """La resolución de config lee la sección, coacciona dict y cae al fallback standalone."""
    fallback = _scorecard_config()
    assert (
        step_module._validation_config_from_study(
            SimpleNamespace(config=SimpleNamespace(validation=None)), fallback=fallback
        )
        is fallback
    )
    resolved = step_module._validation_config_from_study(
        SimpleNamespace(config=SimpleNamespace(validation={"families": ["calibration"]})),
        fallback=fallback,
    )
    assert resolved.families == ("calibration",)
    assert (
        step_module._validation_config_from_study(
            SimpleNamespace(config=SimpleNamespace(validation=fallback)),
            fallback=ValidationConfig(),
        )
        is fallback
    )


def test_model_ref_sin_nombre_usa_default() -> None:
    """El ``model_ref`` cae a 'validation' si el config no tiene nombre utilizable."""
    assert (
        step_module._model_ref(SimpleNamespace(config=SimpleNamespace(name=None))) == "validation"
    )
    assert (
        step_module._model_ref(SimpleNamespace(config=SimpleNamespace(name="  "))) == "validation"
    )
    assert (
        step_module._model_ref(SimpleNamespace(config=SimpleNamespace(name="scorecard-x")))
        == "scorecard-x"
    )


def test_emit_permite_usar_step_como_sink() -> None:
    """El step reexpone ``emit`` para actuar como sumidero de auditoría si un motor lo requiere."""
    from datetime import UTC, datetime

    from nikodym.core.audit import AuditEvent

    step = ValidationStep.from_config(_scorecard_config())
    sink = InMemoryAuditSink()
    step._audit = sink
    step.emit(
        AuditEvent(kind="decision", step="validation", payload={"r": 1}, ts=datetime.now(UTC))
    )
    assert sink.events[-1].payload == {"r": 1}


# ─────────────────────────── import liviano ───────────────────────────


def test_import_pandas_ausente_es_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ausencia de pandas se traduce a ``MissingDependencyError`` accionable."""
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="ValidationStep requiere pandas"):
        step_module._import_pandas()


def test_import_validation_registra_step_sin_stack_pesado() -> None:
    """``import nikodym.validation`` registra el step sin cargar pandas/scipy/sklearn."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.validation
        from nikodym.core.registry import REGISTRY

        assert REGISTRY.resolve("validation", "standard").__name__ == "ValidationStep"
        blocked = [
            name
            for name in ("pandas", "numpy", "pandera", "scipy", "sklearn")
            if name in sys.modules
        ]
        assert blocked == [], blocked
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"
