"""Tests de Kaplan-Meier survival: fórmula manual, bordes y contratos SDD-18."""

from __future__ import annotations

import math
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.survival.kaplan_meier as km_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import NotFittedError
from nikodym.survival import KaplanMeierSurvivalModel as ExportedKaplanMeierSurvivalModel
from nikodym.survival.base import BaseSurvivalModel
from nikodym.survival.config import (
    KaplanMeierConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalTimeGridConfig,
)
from nikodym.survival.exceptions import (
    SurvivalConfigError,
    SurvivalInputError,
    SurvivalTransformError,
)
from nikodym.survival.kaplan_meier import KaplanMeierSurvivalModel

_TERM_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "partition",
    "period",
    "time_value",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "method",
    "pd_source",
    "scenario",
    "warning_codes",
)
_CURVE_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "period",
    "time_value",
    "survival",
    "survival_lower",
    "survival_upper",
    "greenwood_variance",
)
_HAZARD_COLUMNS: tuple[str, ...] = (
    "row_id",
    "segment",
    "period",
    "time_value",
    "hazard",
    "link",
    "linear_predictor_hazard",
)


def test_kaplan_meier_golden_manual_greenwood_no_muta_y_publica_frames() -> None:
    frame = _km_frame()
    original = frame.copy(deep=True)
    audit = InMemoryAuditSink()

    model = KaplanMeierSurvivalModel.from_config(_cfg()).fit(
        frame,
        duration_col="duration",
        event_col="event",
        audit=audit,
    )
    survival = model.predict_survival(frame, times=[1, 2, 3, 4])
    hazards = model.predict_hazard(frame, times=[1, 2, 3, 4])
    term = model.term_structure(frame, times=[1, 2, 3, 4])

    expected_survival = pd.DataFrame(
        {
            "row_id": [None, None, None, None],
            "segment": [None, None, None, None],
            "period": [1, 2, 3, 4],
            "time_value": [1.0, 2.0, 3.0, 4.0],
            "survival": [0.8, 0.6, 0.3, 0.3],
            "survival_lower": [None, None, None, None],
            "survival_upper": [None, None, None, None],
            "greenwood_variance": [0.03200000, 0.04800000, 0.05700000, 0.05700000],
        },
        index=pd.Index(["__all__|1", "__all__|2", "__all__|3", "__all__|4"], name="curve_id"),
    )
    expected_hazards = pd.DataFrame(
        {
            "row_id": [None, None, None, None],
            "segment": [None, None, None, None],
            "period": [1, 2, 3, 4],
            "time_value": [1.0, 2.0, 3.0, 4.0],
            "hazard": [0.2, 0.25, 0.5, 0.0],
            "link": [None, None, None, None],
            "linear_predictor_hazard": [None, None, None, None],
        },
        index=pd.Index(["__all__|1", "__all__|2", "__all__|3", "__all__|4"], name="curve_id"),
    )
    expected_term = pd.DataFrame(
        {
            "row_id": [None, None, None, None],
            "segment": [None, None, None, None],
            "partition": [None, None, None, None],
            "period": [1, 2, 3, 4],
            "time_value": [1.0, 2.0, 3.0, 4.0],
            "hazard": [0.2, 0.25, 0.5, 0.0],
            "survival": [0.8, 0.6, 0.3, 0.3],
            "pd_marginal": [0.2, 0.2, 0.3, 0.0],
            "pd_cumulative": [0.2, 0.4, 0.7, 0.7],
            "method": ["kaplan_meier"] * 4,
            "pd_source": ["none"] * 4,
            "scenario": [None, None, None, None],
            "warning_codes": [("FALTA-DATO-SUR-3",)] * 4,
        },
        index=pd.Index(["__all__|1", "__all__|2", "__all__|3", "__all__|4"], name="curve_id"),
    )

    assert isinstance(model, BaseSurvivalModel)
    assert_frame_equal(survival, expected_survival, check_dtype=False, atol=1e-12, rtol=1e-12)
    assert_frame_equal(hazards, expected_hazards, check_dtype=False, atol=1e-12, rtol=1e-12)
    assert_frame_equal(term, expected_term, check_dtype=False, atol=1e-12, rtol=1e-12)
    assert tuple(term.columns) == _TERM_COLUMNS
    assert tuple(survival.columns) == _CURVE_COLUMNS
    assert tuple(hazards.columns) == _HAZARD_COLUMNS
    assert term["survival"].is_monotonic_decreasing
    assert (term["pd_marginal"] >= 0.0).all()
    assert term["pd_cumulative"].tolist() == pytest.approx((1.0 - term["survival"]).tolist())
    assert term["pd_marginal"].sum() == pytest.approx(term["pd_cumulative"].iloc[-1])
    assert_frame_equal(frame, original)
    assert [event.payload["regla"] for event in audit.events] == [
        "survival_input_quality",
        "survival_km_greenwood",
    ]


def test_kaplan_meier_intervalos_plain_y_loglog_sin_warning_falta_dato() -> None:
    plain = KaplanMeierSurvivalModel.from_config(
        _cfg(confidence_level=0.95, confidence_transform="plain")
    ).fit(_km_frame(), duration_col="duration", event_col="event")
    loglog = KaplanMeierSurvivalModel.from_config(
        _cfg(confidence_level=0.95, confidence_transform="loglog")
    ).fit(_km_frame(), duration_col="duration", event_col="event")

    plain_curve = plain.predict_survival(_km_frame(), times=[1, 2, 3])
    loglog_curve = loglog.predict_survival(_km_frame(), times=[1, 2, 3])
    plain_term = plain.term_structure(_km_frame(), times=[1, 2, 3])

    assert plain_curve.loc["__all__|1", "survival_lower"] == pytest.approx(0.4493909837693675)
    assert plain_curve.loc["__all__|1", "survival_upper"] == 1.0
    for curve in (plain_curve, loglog_curve):
        for row in curve.itertuples(index=False):
            assert math.isfinite(row.survival_lower)
            assert math.isfinite(row.survival_upper)
            assert row.survival_lower <= row.survival <= row.survival_upper
            assert 0.0 <= row.survival_lower <= 1.0
            assert 0.0 <= row.survival_upper <= 1.0
    assert plain_term["warning_codes"].tolist() == [(), (), ()]


def test_censura_total_publica_supervivencia_plana_y_warning() -> None:
    frame = pd.DataFrame(
        {"duration": [1, 2, 3], "event": [0, 0, 0]},
        index=pd.Index(["a", "b", "c"], name="loan_id"),
    )
    model = KaplanMeierSurvivalModel.from_config(_cfg()).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )

    survival = model.predict_survival(frame, times=[1, 2, 3])
    term = model.term_structure(frame, times=[1, 2, 3])
    fallback_term = model.term_structure(frame, times=[])

    assert survival["survival"].tolist() == [1.0, 1.0, 1.0]
    assert survival["greenwood_variance"].tolist() == [0.0, 0.0, 0.0]
    assert term["hazard"].tolist() == [0.0, 0.0, 0.0]
    assert term["pd_marginal"].tolist() == [0.0, 0.0, 0.0]
    assert term["warning_codes"].tolist() == [
        ("FALTA-DATO-SUR-3", "FALTA-DATO-SUR-2"),
        ("FALTA-DATO-SUR-3", "FALTA-DATO-SUR-2"),
        ("FALTA-DATO-SUR-3", "FALTA-DATO-SUR-2"),
    ]
    assert fallback_term["time_value"].tolist() == [3.0]
    assert fallback_term["warning_codes"].iloc[0] == (
        "FALTA-DATO-SUR-3",
        "FALTA-DATO-SUR-1",
        "FALTA-DATO-SUR-2",
    )


def test_segmentos_y_grillas_de_configuracion() -> None:
    frame = pd.DataFrame(
        {
            "duration": [1, 2, 2, 3],
            "event": [1, 0, 1, 0],
            "segment": ["A", "A", "B", "B"],
        },
        index=pd.Index(["a1", "a2", "b1", "b2"], name="loan_id"),
    )
    cfg = _cfg(segment_col="segment", evaluation_times=(1.0, 2.0))
    model = KaplanMeierSurvivalModel.from_config(cfg).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )

    term = model.term_structure(frame.iloc[[2, 0]], times=[])
    horizon = KaplanMeierSurvivalModel.from_config(
        _cfg(time_grid=SurvivalTimeGridConfig(horizon_periods=2))
    ).fit(_km_frame(), duration_col="duration", event_col="event")

    assert term.index.tolist() == ["B|1", "B|2", "A|1", "A|2"]
    assert term["segment"].tolist() == ["B", "B", "A", "A"]
    assert term.loc["A|1", "survival"] == 0.5
    assert term.loc["B|2", "survival"] == 0.5
    assert horizon.term_structure(_km_frame(), times=[])["time_value"].tolist() == [1.0, 2.0]

    with pytest.raises(SurvivalInputError, match="segment_col='segment'"):
        model.predict_survival(frame.drop(columns=["segment"]), times=[1])
    with pytest.raises(SurvivalTransformError, match="Segmento no observado"):
        model.predict_survival(frame.assign(segment=["A", "C", "B", "B"]), times=[1])
    with pytest.raises(SurvivalInputError, match="missing"):
        KaplanMeierSurvivalModel.from_config(cfg).fit(
            frame.assign(segment=["A", None, "B", "B"]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="predicción"):
        model.predict_survival(frame.assign(segment=["A", None, "B", "B"]), times=[1])


def test_bordes_evento_total_tiempo_pre_evento_y_config_mapping() -> None:
    frame = pd.DataFrame(
        {"duration": [2, 2], "event": [1, 1]},
        index=pd.Index(["a", "b"], name="loan_id"),
    )
    cfg_payload = _cfg(confidence_level=0.95, confidence_transform="loglog").model_dump()
    model = KaplanMeierSurvivalModel(config=cfg_payload).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    mapped = KaplanMeierSurvivalModel.from_config(cfg_payload).fit(
        frame,
        duration_col="duration",
        event_col="event",
    )
    term = model.term_structure(frame, times=[1, 2])

    assert term["survival"].tolist() == [1.0, 0.0]
    assert term["hazard"].tolist() == [0.0, 1.0]
    assert model.predict_survival(frame, times=[2])["greenwood_variance"].tolist() == [0.0]
    assert model.predict_survival(frame, times=[2])["survival_lower"].tolist() == [0.0]
    assert mapped.term_structure(frame, times=[2])["survival"].tolist() == [0.0]


def test_constructor_sin_config_usa_pd_source_none_y_fallback_observado() -> None:
    model = KaplanMeierSurvivalModel().fit(_km_frame(), duration_col="duration", event_col="event")
    term = model.term_structure(_km_frame(), times=[])

    assert term["time_value"].tolist() == [1.0, 2.0, 3.0]
    assert term["pd_source"].tolist() == ["none", "none", "none"]
    assert term["warning_codes"].tolist() == [
        ("FALTA-DATO-SUR-3", "FALTA-DATO-SUR-1"),
        ("FALTA-DATO-SUR-3", "FALTA-DATO-SUR-1"),
        ("FALTA-DATO-SUR-3", "FALTA-DATO-SUR-1"),
    ]


def test_warning_fallback_no_queda_pegado_entre_predicciones() -> None:
    model = KaplanMeierSurvivalModel.from_config(_cfg()).fit(
        _km_frame(),
        duration_col="duration",
        event_col="event",
    )

    fallback = model.term_structure(_km_frame(), times=[])
    explicit_after_fallback = model.term_structure(_km_frame(), times=[1, 2, 3])
    repeated_explicit = model.term_structure(_km_frame(), times=[1, 2, 3])
    another = KaplanMeierSurvivalModel.from_config(_cfg()).fit(
        _km_frame(),
        duration_col="duration",
        event_col="event",
    )
    explicit_without_history = another.term_structure(_km_frame(), times=[1, 2, 3])

    assert all("FALTA-DATO-SUR-1" in codes for codes in fallback["warning_codes"])
    assert all(
        "FALTA-DATO-SUR-1" not in codes for codes in explicit_after_fallback["warning_codes"]
    )
    assert (
        explicit_after_fallback["warning_codes"].tolist()
        == repeated_explicit["warning_codes"].tolist()
    )
    assert (
        explicit_after_fallback["warning_codes"].tolist()
        == explicit_without_history["warning_codes"].tolist()
    )
    assert model.warning_codes_ == ("FALTA-DATO-SUR-3",)


def test_errores_de_configuracion_y_no_fiteado() -> None:
    with pytest.raises(SurvivalConfigError, match="method='kaplan_meier'"):
        KaplanMeierSurvivalModel.from_config(
            SurvivalConfig(input=SurvivalInputConfig(duration_col="duration", event_col="event"))
        )
    with pytest.raises(SurvivalConfigError, match="method='kaplan_meier'"):
        KaplanMeierSurvivalModel(
            config=SurvivalConfig(
                input=SurvivalInputConfig(duration_col="duration", event_col="event")
            )
        ).fit(_km_frame(), duration_col="duration", event_col="event")
    with pytest.raises(NotFittedError, match="no está fiteado"):
        KaplanMeierSurvivalModel.from_config(_cfg()).predict_survival(_km_frame(), times=[1])


def test_errores_de_input_columnas_indice_duracion_evento_y_covariables() -> None:
    frame = _km_frame()
    with pytest.raises(SurvivalInputError, match="Faltan columnas"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.drop(columns=["event"]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="cov"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame,
            duration_col="duration",
            event_col="event",
            covariate_cols=("cov",),
        )
    with pytest.raises(SurvivalInputError, match="índice"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.rename(index={"b": "a"}),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match=r"pandas\.DataFrame"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            "no-frame",  # type: ignore[arg-type]
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="booleana"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.assign(duration=[True, False, True, False, True]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="numérica"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.assign(duration=["1", "2", "2", "3", "4"]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="no positivos"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.assign(duration=[1.0, 2.0, 0.0, math.inf, 4.0]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="binario"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.assign(event=[0, 1, 2, 0, 1]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="0/1"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.assign(event=[True, False, True, False, True]),
            duration_col="duration",
            event_col="event",
        )
    with pytest.raises(SurvivalInputError, match="0/1"):
        KaplanMeierSurvivalModel.from_config(_cfg()).fit(
            frame.assign(event=["0", "1", "0", "1", "0"]),
            duration_col="duration",
            event_col="event",
        )


def test_errores_de_grilla_y_soporte() -> None:
    model = KaplanMeierSurvivalModel.from_config(_cfg()).fit(
        _km_frame(),
        duration_col="duration",
        event_col="event",
    )

    with pytest.raises(SurvivalTransformError, match="booleano"):
        model.term_structure(_km_frame(), times=[True])
    with pytest.raises(SurvivalTransformError, match="positivos"):
        model.term_structure(_km_frame(), times=[0])
    with pytest.raises(SurvivalTransformError, match="duplicados"):
        model.term_structure(_km_frame(), times=[1, 1])
    with pytest.raises(SurvivalTransformError, match="fuera del soporte"):
        model.term_structure(_km_frame(), times=[5])
    with pytest.raises(SurvivalTransformError, match=r"\[0, 1\]"):
        km_module._unit_float(1.2, field_name="hazard")
    with pytest.raises(SurvivalTransformError, match="no negativo"):
        km_module._non_negative_float(-0.1, field_name="greenwood_variance")


def test_import_survival_y_exports_no_cargan_dependencias_pesadas() -> None:
    code = (
        "import nikodym.survival, sys;"
        "blocked=[m for m in ('lifelines','statsmodels','sksurv','pandas') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'KaplanMeierSurvivalModel' in nikodym.survival.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert ExportedKaplanMeierSurvivalModel is KaplanMeierSurvivalModel
    assert "KaplanMeierSurvivalModel" in km_module.__all__


def _cfg(
    *,
    confidence_level: float | None = None,
    confidence_transform: str | None = None,
    segment_col: str | None = None,
    evaluation_times: tuple[float, ...] = (),
    time_grid: SurvivalTimeGridConfig | None = None,
) -> SurvivalConfig:
    return SurvivalConfig(
        method="kaplan_meier",
        input=SurvivalInputConfig(
            duration_col="duration",
            event_col="event",
            segment_col=segment_col,
            pd_source="none",
        ),
        time_grid=SurvivalTimeGridConfig(evaluation_times=evaluation_times)
        if time_grid is None
        else time_grid,
        kaplan_meier=KaplanMeierConfig(
            confidence_level=confidence_level,
            confidence_transform=confidence_transform,  # type: ignore[arg-type]
        ),
        fail_on_falta_dato=False,
    )


def _km_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"duration": [1, 2, 2, 3, 4], "event": [1, 0, 1, 1, 0]},
        index=pd.Index(["a", "b", "c", "d", "e"], name="loan_id"),
    )
