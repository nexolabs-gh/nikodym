"""Tests de resultados de ``calibration``: DTOs puros, copias y lazy exports."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.calibration.results as calibration_results
from nikodym.calibration.config import (
    AnchorKind as ConfigAnchorKind,
)
from nikodym.calibration.config import (
    AnchorSource as ConfigAnchorSource,
)
from nikodym.calibration.config import (
    CalibrationMethod as ConfigCalibrationMethod,
)
from nikodym.calibration.results import (
    CalibrationCardSection,
    CalibrationParameters,
    CalibrationResult,
)


def test_calibration_parameters_golden_frozen_extra_y_copias() -> None:
    knots = [[-0.0, 0.03125], [1.5, -0.0]]
    parameters = _parameters(
        offset=-0.0,
        slope=None,
        intercept=-0.0,
        isotonic_knots=knots,
        post_offset=-0.0,
        target_tolerance=-0.0,
        achieved_mean_pd_dev=-0.0,
        raw_mean_pd_dev=-0.0,
        observed_default_rate_dev=-0.0,
    )

    expected_dump = {
        "method": "intercept_offset",
        "target_pd": 0.0525,
        "anchor_kind": "through_the_cycle",
        "anchor_source": "business_input",
        "fit_partition": "desarrollo",
        "offset": 0.0,
        "slope": None,
        "intercept": 0.0,
        "isotonic_knots": [[0.0, 0.03125], [1.5, 0.0]],
        "post_offset": 0.0,
        "target_tolerance": 0.0,
        "achieved_mean_pd_dev": 0.0,
        "raw_mean_pd_dev": 0.0,
        "observed_default_rate_dev": 0.0,
        "n_fit": 120,
    }
    assert parameters.model_dump(mode="json") == expected_dump
    assert CalibrationParameters.model_validate(parameters.model_dump()) == parameters
    assert math.copysign(1.0, parameters.offset) == 1.0
    assert math.copysign(1.0, parameters.intercept) == 1.0
    assert math.copysign(1.0, parameters.isotonic_knots[0][0]) == 1.0

    knots[0][0] = 99.0
    first_knots = parameters.isotonic_knots
    second_knots = parameters.isotonic_knots
    assert first_knots == ((0.0, 0.03125), (1.5, 0.0))
    assert second_knots == first_knots
    assert second_knots is not first_knots

    with pytest.raises(ValidationError, match="frozen"):
        parameters.offset = 1.0
    with pytest.raises(ValidationError):
        _parameters(extra="no permitido")


def test_calibration_card_section_golden_metric_sections_y_dependency_versions() -> None:
    metric_sections: dict[str, Any] = {
        "diagnostico": {
            "delta": -0.0,
            "serie": [math.inf, math.nan, -0.0],
            "tupla": (-0.0,),
            "nested": {"valor": -0.0},
            "nota": "ok",
        }
    }
    dependency_versions = {"sklearn": "1.7.2", "pandas": "2.3.3", "scipy": "1.14.1"}
    card = _card(
        target_pd=-0.0,
        raw_mean_pd_dev=-0.0,
        calibrated_mean_pd_dev=-0.0,
        observed_default_rate_dev=-0.0,
        offset=-0.0,
        slope=-0.0,
        intercept=-0.0,
        dependency_versions=dependency_versions,
        metric_sections=metric_sections,
    )

    expected_dump = {
        "method": "intercept_offset",
        "target_pd": 0.0,
        "anchor_kind": "through_the_cycle",
        "anchor_source": "business_input",
        "fit_partition": "desarrollo",
        "n_fit": 120,
        "raw_mean_pd_dev": 0.0,
        "calibrated_mean_pd_dev": 0.0,
        "observed_default_rate_dev": 0.0,
        "offset": 0.0,
        "slope": 0.0,
        "intercept": 0.0,
        "ranking_preserved": True,
        "ties_created": 0,
        "pd_raw_column": "pd_raw",
        "pd_calibrated_column": "pd_calibrated",
        "dependency_versions": {"pandas": "2.3.3", "scipy": "1.14.1", "sklearn": "1.7.2"},
        "metric_sections": {
            "diagnostico": {
                "delta": 0.0,
                "serie": [None, None, 0.0],
                "tupla": [0.0],
                "nested": {"valor": 0.0},
                "nota": "ok",
            }
        },
    }
    assert card.model_dump(mode="json") == expected_dump
    assert CalibrationCardSection.model_validate(card.model_dump()) == card
    assert list(card.dependency_versions) == ["pandas", "scipy", "sklearn"]
    assert math.copysign(1.0, card.metric_sections["diagnostico"]["delta"]) == 1.0

    dependency_versions["pandas"] = "mutado"
    metric_sections["diagnostico"]["delta"] = 99.0
    card.dependency_versions["pandas"] = "mutado"
    card.metric_sections["diagnostico"]["delta"] = 88.0
    assert card.dependency_versions == {
        "pandas": "2.3.3",
        "scipy": "1.14.1",
        "sklearn": "1.7.2",
    }
    assert card.metric_sections["diagnostico"]["delta"] == 0.0

    with pytest.raises(ValidationError, match="frozen"):
        card.ties_created = 1
    with pytest.raises(ValidationError):
        _card(extra="no permitido")


def test_card_metric_sections_default_none_e_invalido() -> None:
    assert _card().metric_sections == {}
    assert _card(metric_sections=None).metric_sections == {}
    with pytest.raises(ValidationError):
        _card(metric_sections=["no permitido"])


def test_calibration_result_envuelve_frame_canonico_con_copias_defensivas() -> None:
    frame = _calibrated_frame()
    result = _result(calibrated_pd_frame=frame)

    frame.loc["c1", "pd_calibrated"] = 0.99
    observed_frame = result.calibrated_pd_frame

    assert_frame_equal(observed_frame, _normalized_calibrated_frame())
    assert tuple(observed_frame.columns) == (
        "partition",
        "target",
        "linear_predictor",
        "pd_raw",
        "linear_predictor_calibrated",
        "pd_calibrated",
        "calibration_method",
        "anchor_kind",
    )
    assert math.copysign(1.0, observed_frame.loc["c1", "linear_predictor"]) == 1.0
    assert result.parameters == _parameters()
    assert result.card == _card()

    observed_frame.loc["c1", "pd_calibrated"] = 0.77
    assert_frame_equal(result.calibrated_pd_frame, _normalized_calibrated_frame())
    round_tripped = CalibrationResult.model_validate(
        {
            "calibrated_pd_frame": result.calibrated_pd_frame,
            "parameters": result.parameters.model_dump(),
            "card": result.card.model_dump(),
        }
    )
    assert_frame_equal(round_tripped.calibrated_pd_frame, result.calibrated_pd_frame)
    assert round_tripped.parameters == result.parameters
    assert round_tripped.card == result.card

    with pytest.raises(ValidationError, match="frozen"):
        result.parameters = _parameters(n_fit=99)
    with pytest.raises(ValidationError):
        _result(extra="no permitido")


def test_calibration_result_valida_dataframe_y_consistencia_card() -> None:
    with pytest.raises(ValidationError, match=r"pandas\.DataFrame"):
        _result(calibrated_pd_frame="no es DataFrame")
    with pytest.raises(ValidationError, match="columnas canónicas"):
        _result(calibrated_pd_frame=_calibrated_frame().drop(columns=["anchor_kind"]))
    with pytest.raises(ValidationError, match="target_pd"):
        _result(card=_card(target_pd=0.07))


def test_calibration_results_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.calibration as calibration;"
        "blocked=[m for m in ('pandas','scipy','sklearn') if m in sys.modules];"
        "assert not blocked, blocked;"
        "loaded=[getattr(calibration, name) for name in "
        "('CalibrationParameters','CalibrationCardSection','CalibrationResult')];"
        "assert loaded[-1].__name__ == 'CalibrationResult';"
        "blocked=[m for m in ('pandas','scipy','sklearn') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_results_module_expone_aliases_publicos_de_config() -> None:
    assert calibration_results.CalibrationMethod == ConfigCalibrationMethod
    assert calibration_results.AnchorKind == ConfigAnchorKind
    assert calibration_results.AnchorSource == ConfigAnchorSource
    assert "CalibrationParameters" in calibration_results.__all__
    assert "CalibrationCardSection" in calibration_results.__all__
    assert "CalibrationResult" in calibration_results.__all__


def _parameters(**updates: Any) -> CalibrationParameters:
    payload: dict[str, Any] = {
        "method": "intercept_offset",
        "target_pd": 0.0525,
        "anchor_kind": "through_the_cycle",
        "anchor_source": "business_input",
        "fit_partition": "desarrollo",
        "offset": 0.137194,
        "slope": None,
        "intercept": None,
        "isotonic_knots": (),
        "post_offset": None,
        "target_tolerance": 1e-12,
        "achieved_mean_pd_dev": 2.3e-15,
        "raw_mean_pd_dev": -0.0048,
        "observed_default_rate_dev": None,
        "n_fit": 120,
    }
    payload.update(updates)
    return CalibrationParameters(**payload)


def _card(**updates: Any) -> CalibrationCardSection:
    payload: dict[str, Any] = {
        "method": "intercept_offset",
        "target_pd": 0.0525,
        "anchor_kind": "through_the_cycle",
        "anchor_source": "business_input",
        "fit_partition": "desarrollo",
        "n_fit": 120,
        "raw_mean_pd_dev": -0.0048,
        "calibrated_mean_pd_dev": 2.3e-15,
        "observed_default_rate_dev": None,
        "offset": 0.137194,
        "slope": None,
        "intercept": None,
        "ranking_preserved": True,
        "ties_created": 0,
        "pd_raw_column": "pd_raw",
        "pd_calibrated_column": "pd_calibrated",
        "dependency_versions": {"pandas": "2.3.3"},
    }
    payload.update(updates)
    return CalibrationCardSection(**payload)


def _result(
    *,
    calibrated_pd_frame: Any | None = None,
    parameters: CalibrationParameters | None = None,
    card: CalibrationCardSection | None = None,
    extra: object | None = None,
) -> CalibrationResult:
    payload: dict[str, Any] = {
        "calibrated_pd_frame": (
            _calibrated_frame() if calibrated_pd_frame is None else calibrated_pd_frame
        ),
        "parameters": _parameters() if parameters is None else parameters,
        "card": _card() if card is None else card,
    }
    if extra is not None:
        payload["extra"] = extra
    return CalibrationResult(**payload)


def _calibrated_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout", "oot"],
            "target": [0.0, 1.0, 0.0],
            "linear_predictor": [-0.0, -2.1, -1.4],
            "pd_raw": [0.0477, 0.1091, 0.1978],
            "linear_predictor_calibrated": [-0.0, -1.962806, -1.262806],
            "pd_calibrated": [0.0525, 0.1232, 0.2205],
            "calibration_method": ["intercept_offset", "intercept_offset", "intercept_offset"],
            "anchor_kind": ["through_the_cycle", "through_the_cycle", "through_the_cycle"],
        },
        index=pd.Index(["c1", "c2", "c3"], name="cliente_id"),
    )


def _normalized_calibrated_frame() -> pd.DataFrame:
    return _normalize_frame(_calibrated_frame())


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy(deep=True)
    for column in normalized.select_dtypes(include=["float"]).columns:
        normalized[column] = normalized[column].mask(normalized[column] == 0.0, 0.0)
    return normalized
