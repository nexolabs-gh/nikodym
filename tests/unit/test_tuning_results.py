"""Tests de resultados de ``tuning``: DTOs puros, orden estable, tidy e import perezoso (SDD-13)."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

import nikodym.tuning as tuning_pkg
from nikodym.core.base import NikodymClassifier
from nikodym.ml.config import MLConfig, XGBoostParams
from nikodym.tuning.results import (
    SamplerMetadata,
    TuningCardSection,
    TuningResult,
    TuningTrialRecord,
)


class _FakeChallenger(NikodymClassifier):
    """Emula el ``MLChallenger`` (subclase de ``NikodymClassifier``) que crea B12.4."""


# ─────────────────────────── helpers ───────────────────────────


def _sampler_metadata(**overrides: Any) -> SamplerMetadata:
    base: dict[str, Any] = {
        "sampler": "TPESampler",
        "pruner": "NopPruner",
        "seed": 12345,
        "n_trials_requested": 50,
        "n_trials_complete": 48,
        "optuna_version": "3.6.1",
        "direction": "maximize",
        "metric": "auc",
        "deterministic": True,
    }
    base.update(overrides)
    return SamplerMetadata(**base)


def _result(**overrides: Any) -> TuningResult:
    base: dict[str, Any] = {
        "best_hyperparameters": XGBoostParams(max_depth=4, learning_rate=0.03),
        "best_config": MLConfig(backend="xgboost"),
        "best_estimator": None,
        "best_value": 0.82,
        "trials": (
            TuningTrialRecord(
                number=0,
                params={"max_depth": 3, "learning_rate": 0.05},
                value=0.80,
                state="complete",
            ),
            TuningTrialRecord(
                number=1,
                params={"max_depth": 4, "learning_rate": 0.03},
                value=0.82,
                state="complete",
            ),
        ),
        "param_importances": (("learning_rate", 0.7), ("max_depth", 0.3)),
        "sampler_metadata": _sampler_metadata(),
        "card": TuningCardSection(summary={"best_value": 0.82}),
    }
    base.update(overrides)
    return TuningResult(**base)


# ─────────────────────────── TuningTrialRecord ───────────────────────────


def test_trial_record_golden_normaliza_menos_cero_frozen_y_extra() -> None:
    record = TuningTrialRecord(number=0, params={"lr": -0.0}, value=-0.0, state="complete")
    assert record.model_dump(mode="json") == {
        "number": 0,
        "params": {"lr": 0.0},
        "value": 0.0,
        "state": "complete",
    }
    assert math.copysign(1.0, record.value) == 1.0  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="frozen"):
        record.value = 1.0
    with pytest.raises(ValidationError):
        TuningTrialRecord(number=0, params={}, value=0.1, state="raro")
    with pytest.raises(ValidationError):
        TuningTrialRecord(number=0, params={}, value=0.1, state="complete", extra=1)  # type: ignore[call-arg]


def test_trial_record_valor_none_para_podado() -> None:
    record = TuningTrialRecord(number=2, params={"a": 1}, value=None, state="pruned")
    assert record.value is None
    assert record.state == "pruned"


def test_trial_record_rechaza_number_negativo_y_valor_no_finito() -> None:
    with pytest.raises(ValidationError):
        TuningTrialRecord(number=-1, params={}, value=0.1, state="complete")
    with pytest.raises(ValidationError, match="finitos"):
        TuningTrialRecord(number=0, params={}, value=float("nan"), state="complete")
    with pytest.raises(ValidationError, match="números reales"):
        TuningTrialRecord(number=0, params={}, value=True, state="complete")


def test_trial_record_params_no_mapping_rechazado() -> None:
    with pytest.raises(ValidationError):
        TuningTrialRecord(number=0, params=["no", "dict"], value=0.1, state="complete")  # type: ignore[arg-type]


# ─────────────────────────── SamplerMetadata ───────────────────────────


def test_sampler_metadata_golden_frozen_y_extra() -> None:
    meta = _sampler_metadata()
    assert meta.model_dump(mode="json") == {
        "sampler": "TPESampler",
        "pruner": "NopPruner",
        "seed": 12345,
        "n_trials_requested": 50,
        "n_trials_complete": 48,
        "optuna_version": "3.6.1",
        "direction": "maximize",
        "metric": "auc",
        "deterministic": True,
    }
    with pytest.raises(ValidationError, match="frozen"):
        meta.seed = 1
    with pytest.raises(ValidationError):
        _sampler_metadata(extra="x")


def test_sampler_metadata_texto_vacio_rechazado() -> None:
    with pytest.raises(ValidationError, match="no pueden estar vacíos"):
        _sampler_metadata(sampler="  ")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", -1),
        ("n_trials_requested", 0),
        ("n_trials_complete", -1),
        ("direction", "sideways"),
        ("metric", "f1"),
    ],
)
def test_sampler_metadata_rangos_y_literales(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _sampler_metadata(**{field: value})


# ─────────────────────────── TuningCardSection ───────────────────────────


def test_card_section_defaults_y_normaliza() -> None:
    card = TuningCardSection(summary={"best": -0.0})
    assert card.summary == {"best": 0.0}
    assert card.metric_sections == {}
    assert card.assumptions == ()
    assert card.limitations == ()


def test_card_section_metric_sections_deep_copy_y_no_finito() -> None:
    payload = {
        "optimization_history": [0.1, 0.2, -0.0],
        "importances": (("lr", 0.5),),
        "degenerado": float("inf"),
        "anidado": {"x": 1},
    }
    card = TuningCardSection(summary={}, metric_sections=payload)
    secciones = card.metric_sections
    assert secciones["optimization_history"] == [0.1, 0.2, 0.0]
    assert secciones["importances"] == (("lr", 0.5),)
    assert secciones["degenerado"] is None  # inf degradado a None (§9)
    # Copy-on-access: mutar la copia no afecta al DTO frozen.
    secciones["anidado"]["x"] = 99
    assert card.metric_sections["anidado"]["x"] == 1


def test_card_section_summary_copy_on_access() -> None:
    card = TuningCardSection(summary={"a": 1})
    copia = card.summary
    copia["a"] = 2
    assert card.summary["a"] == 1


def test_card_section_metric_sections_none_y_no_mapping() -> None:
    assert TuningCardSection(summary={}, metric_sections=None).metric_sections == {}  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TuningCardSection(summary={}, metric_sections=[1, 2])  # type: ignore[arg-type]


def test_card_section_summary_no_mapping_rechazado() -> None:
    """Un `summary` que no es Mapping se rechaza tras pasar por el normalizador."""
    with pytest.raises(ValidationError):
        TuningCardSection(summary=[1, 2])  # type: ignore[arg-type]


def test_card_section_summary_float_no_finito_rechazado() -> None:
    """Un float no finito en `summary` falla explícito (nunca se publica NaN/inf, §9)."""
    with pytest.raises(ValidationError, match="finitos"):
        TuningCardSection(summary={"x": float("inf")})


# ─────────────────────────── TuningResult ───────────────────────────


def test_result_construccion_y_tipos() -> None:
    result = _result()
    assert isinstance(result.best_hyperparameters, XGBoostParams)
    assert result.best_hyperparameters.max_depth == 4
    assert isinstance(result.best_config, MLConfig)
    assert result.best_estimator is None
    assert result.best_value == 0.82
    assert result.term_structure() is None


def test_result_best_estimator_no_none() -> None:
    result = _result(best_estimator=_FakeChallenger())
    assert isinstance(result.best_estimator, _FakeChallenger)


def test_result_frozen_y_extra_forbid() -> None:
    result = _result()
    with pytest.raises(ValidationError, match="frozen"):
        result.best_value = 0.9
    with pytest.raises(ValidationError):
        _result(campo_ajeno=1)


def test_result_best_value_normaliza_y_finito() -> None:
    assert math.copysign(1.0, _result(best_value=-0.0).best_value) == 1.0
    with pytest.raises(ValidationError, match="finitos"):
        _result(best_value=float("inf"))


def test_result_importances_orden_desc_y_desempate() -> None:
    result = _result(param_importances=[("b", 0.3), ("a", 0.3), ("c", 0.7)])
    # Desc por valor; empate 0.3 desempata lexicográfico (a antes que b).
    assert result.param_importances == (("c", 0.7), ("a", 0.3), ("b", 0.3))


def test_result_importances_desde_mapping() -> None:
    result = _result(param_importances={"x": 0.2, "y": 0.8})
    assert result.param_importances == (("y", 0.8), ("x", 0.2))


def test_result_importances_invalidas() -> None:
    with pytest.raises(ValidationError, match="repetir"):
        _result(param_importances=[("a", 0.1), ("a", 0.2)])
    with pytest.raises(ValidationError, match="negativas"):
        _result(param_importances=[("a", -0.1)])
    with pytest.raises(ValidationError, match="números reales"):
        _result(param_importances=[("a", True)])
    with pytest.raises(ValidationError, match="NaN ni inf"):
        _result(param_importances=[("a", float("inf"))])
    with pytest.raises(ValidationError, match="par"):
        _result(param_importances=[("a", 0.1, 0.2)])
    with pytest.raises(ValidationError):
        _result(param_importances=123)


def test_result_trials_frame_tidy() -> None:
    frame = _result().trials_frame()
    assert list(frame.columns) == [
        "number",
        "param_max_depth",
        "param_learning_rate",
        "value",
        "state",
    ]
    assert list(frame["number"]) == [0, 1]
    assert list(frame["param_max_depth"]) == [3, 4]
    assert list(frame["value"]) == [0.80, 0.82]
    assert list(frame["state"]) == ["complete", "complete"]


def test_result_trials_frame_sin_trials() -> None:
    frame = _result(trials=()).trials_frame()
    assert list(frame.columns) == ["number", "value", "state"]
    assert frame.empty


def test_result_term_structure_es_none() -> None:
    assert _result().term_structure() is None


# ─────────────────────────── reexport perezoso e import ───────────────────────────


def test_reexport_perezoso_desde_paquete() -> None:
    """Los DTOs se alcanzan vía `nikodym.tuning.<Nombre>` (reexport perezoso)."""
    assert tuning_pkg.TuningResult is TuningResult
    assert tuning_pkg.TuningTrialRecord is TuningTrialRecord
    assert tuning_pkg.SamplerMetadata is SamplerMetadata
    assert tuning_pkg.TuningCardSection is TuningCardSection


def test_reexport_atributo_desconocido_falla() -> None:
    with pytest.raises(AttributeError, match="no attribute"):
        _ = tuning_pkg.NoExiste  # type: ignore[attr-defined]


def test_import_results_no_arrastra_optuna_ni_backends() -> None:
    """`import nikodym.tuning.results` no carga optuna/pandas/backends en import time."""
    code = (
        "import nikodym.tuning.results, sys;"
        "bloqueados=[m for m in "
        "('optuna','pandas','numpy','sklearn','xgboost','lightgbm','catboost') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_trials_frame_es_dataframe() -> None:
    assert isinstance(_result().trials_frame(), pd.DataFrame)
