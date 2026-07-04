"""Tests de los DTOs de ``explain.results``: contrato frozen, orden estable e import liviano."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

import nikodym.explain.results as explain_results
from nikodym.explain.results import (
    DriverComparisonRecord,
    ExplainCardSection,
    ExplainerMetadata,
    ExplainResult,
    LocalExplanationRecord,
    ReasonCode,
    ShapGlobalRecord,
)


# ── helpers de construcción ───────────────────────────────────────────────────────────────────
def _reason_code(**overrides: Any) -> ReasonCode:
    kwargs: dict[str, Any] = {
        "rank": 1,
        "feature": "ingreso__woe",
        "direction": "increases_pd",
        "contribution": 0.4,
    }
    kwargs.update(overrides)
    return ReasonCode(**kwargs)


def _local(**overrides: Any) -> LocalExplanationRecord:
    kwargs: dict[str, Any] = {
        "row_key": "0",
        "partition": "holdout",
        "base_value": 0.1,
        "prediction": 0.5,
        "pd_hat": 0.62,
        "reason_codes": (
            _reason_code(rank=1, feature="a", contribution=0.4),
            _reason_code(rank=2, feature="b", contribution=-0.2, direction="decreases_pd"),
        ),
    }
    kwargs.update(overrides)
    return LocalExplanationRecord(**kwargs)


# ── ShapGlobalRecord ─────────────────────────────────────────────────────────────────────────
def test_shap_global_record_golden_normaliza_menos_cero_y_frozen() -> None:
    record = ShapGlobalRecord(
        feature="ingreso__woe",
        mean_abs_contribution=-0.0,
        mean_signed_contribution=-0.0,
        rank=1,
        source_model="ml",
    )
    assert record.model_dump(mode="json") == {
        "feature": "ingreso__woe",
        "mean_abs_contribution": 0.0,
        "mean_signed_contribution": 0.0,
        "rank": 1,
        "source_model": "ml",
    }
    assert math.copysign(1.0, record.mean_abs_contribution) == 1.0
    assert math.copysign(1.0, record.mean_signed_contribution) == 1.0
    with pytest.raises(ValidationError, match="frozen"):
        record.rank = 2


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("feature", "  ", "feature"),
        ("mean_abs_contribution", -0.5, "negativa"),
        ("mean_abs_contribution", float("nan"), "NaN"),
        ("mean_abs_contribution", True, "número real"),
        ("mean_signed_contribution", float("inf"), "finitos"),
        ("mean_signed_contribution", "x", "números reales"),
        ("rank", 0, "greater than or equal"),
        ("source_model", "otro", "Input should be"),
    ],
)
def test_shap_global_record_rechaza_valores_invalidos(field: str, value: Any, match: str) -> None:
    kwargs: dict[str, Any] = {
        "feature": "a",
        "mean_abs_contribution": 0.1,
        "mean_signed_contribution": 0.1,
        "rank": 1,
        "source_model": "ml",
    }
    kwargs[field] = value
    with pytest.raises(ValidationError, match=match):
        ShapGlobalRecord(**kwargs)


# ── ReasonCode ───────────────────────────────────────────────────────────────────────────────
def test_reason_code_direcciones_validas() -> None:
    assert _reason_code(contribution=0.4, direction="increases_pd").direction == "increases_pd"
    assert _reason_code(contribution=-0.4, direction="decreases_pd").direction == "decreases_pd"
    # Contribución nula: cualquier dirección es admisible (no hay signo que contradecir).
    assert _reason_code(contribution=0.0, direction="decreases_pd").contribution == 0.0
    assert _reason_code(contribution=-0.0, direction="increases_pd").bin_label is None
    assert _reason_code(bin_label="(0.0, 1.0]").bin_label == "(0.0, 1.0]"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"feature": " "}, "feature"),
        ({"contribution": float("nan")}, "finitos"),
        ({"contribution": 0.4, "direction": "decreases_pd"}, "positiva"),
        ({"contribution": -0.4, "direction": "increases_pd"}, "negativa"),
        ({"rank": 0}, "greater than or equal"),
    ],
)
def test_reason_code_rechaza_incoherencias(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _reason_code(**overrides)


# ── LocalExplanationRecord ─────────────────────────────────────────────────────────────────────
def test_local_record_golden_y_ranks_consecutivos() -> None:
    record = _local(base_value=-0.0, prediction=-0.0)
    assert math.copysign(1.0, record.base_value) == 1.0
    assert math.copysign(1.0, record.prediction) == 1.0
    assert tuple(code.rank for code in record.reason_codes) == (1, 2)
    # Sin reason codes es válido (scope sin drivers publicados).
    assert _local(reason_codes=()).reason_codes == ()


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"row_key": " "}, "no pueden estar"),
        ({"partition": ""}, "no pueden estar"),
        ({"base_value": float("nan")}, "finitos"),
        ({"prediction": float("inf")}, "finitos"),
        ({"pd_hat": float("nan")}, "finitos"),
        ({"pd_hat": 1.5}, "less than or equal"),
        ({"pd_hat": -0.1}, "greater than or equal"),
    ],
)
def test_local_record_rechaza_valores_invalidos(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _local(**overrides)


def test_local_record_ranks_no_consecutivos_falla() -> None:
    with pytest.raises(ValidationError, match="consecutivos"):
        _local(
            reason_codes=(
                _reason_code(rank=1, feature="a", contribution=0.4),
                _reason_code(rank=3, feature="b", contribution=0.2),
            )
        )


# ── DriverComparisonRecord ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("in_sc", "in_ml", "agreement"),
    [
        (True, True, "both"),
        (True, False, "scorecard_only"),
        (False, True, "ml_only"),
    ],
)
def test_driver_comparison_agreement_coherente(in_sc: bool, in_ml: bool, agreement: str) -> None:
    record = DriverComparisonRecord(
        feature="ingreso__woe",
        scorecard_rank=1 if in_sc else None,
        ml_rank=2 if in_ml else None,
        in_scorecard_topk=in_sc,
        in_ml_topk=in_ml,
        agreement=agreement,
    )
    assert record.agreement == agreement


def test_driver_comparison_rechaza_incoherencias() -> None:
    with pytest.raises(ValidationError, match="al menos un modelo"):
        DriverComparisonRecord(
            feature="a",
            in_scorecard_topk=False,
            in_ml_topk=False,
            agreement="both",
        )
    with pytest.raises(ValidationError, match="no coincide"):
        DriverComparisonRecord(
            feature="a",
            in_scorecard_topk=True,
            in_ml_topk=True,
            agreement="scorecard_only",
        )
    with pytest.raises(ValidationError, match="feature"):
        DriverComparisonRecord(
            feature=" ",
            in_scorecard_topk=True,
            in_ml_topk=False,
            agreement="scorecard_only",
        )
    with pytest.raises(ValidationError, match="greater than or equal"):
        DriverComparisonRecord(
            feature="a",
            scorecard_rank=0,
            in_scorecard_topk=True,
            in_ml_topk=False,
            agreement="scorecard_only",
        )


# ── ExplainerMetadata ──────────────────────────────────────────────────────────────────────────
def test_explainer_metadata_valida_y_rangos() -> None:
    meta = ExplainerMetadata(
        ml_explainer_kind="tree",
        scorecard_explained=True,
        shap_version="0.44.1",
        contribution_space="log_odds",
        background_size=None,
        seed=7,
        deterministic=True,
        top_n_reason_codes=5,
    )
    assert meta.background_size is None
    base: dict[str, Any] = {
        "ml_explainer_kind": None,
        "scorecard_explained": False,
        "shap_version": None,
        "contribution_space": "probability",
        "seed": 0,
        "deterministic": False,
        "top_n_reason_codes": 1,
    }
    for field, value in (("seed", -1), ("background_size", 0), ("top_n_reason_codes", 0)):
        with pytest.raises(ValidationError, match="greater than or equal"):
            ExplainerMetadata(**{**base, field: value})


# ── ExplainCardSection ─────────────────────────────────────────────────────────────────────────
def test_card_section_normaliza_copia_y_tolera_nan_en_metric_sections() -> None:
    card = ExplainCardSection(
        summary={"explainer": "tree", "seed": 7, "determinista": True, "cero": -0.0},
        metric_sections={
            "shap_summary": {"top": [1.0, -0.0, float("nan")], "par": (2.0,)},
            "nota": "texto",
            "flag": True,
        },
        assumptions=("aditividad log-odds",),
        limitations=("scope muestral",),
    )
    assert card.summary["cero"] == 0.0
    assert math.copysign(1.0, card.summary["cero"]) == 1.0
    # NaN en metric_sections degrada a None (no rompe), floats normalizan -0.0.
    assert card.metric_sections["shap_summary"]["top"] == [1.0, 0.0, None]
    assert card.metric_sections["shap_summary"]["par"] == (2.0,)
    # Copia defensiva: mutar la lectura no altera el interno.
    leido = card.metric_sections
    leido["shap_summary"]["top"].append(99.0)
    assert 99.0 not in card.metric_sections["shap_summary"]["top"]


def test_card_section_summary_nan_falla_y_metric_sections_no_mapping() -> None:
    with pytest.raises(ValidationError, match="finitos"):
        ExplainCardSection(summary={"malo": float("nan")})
    # summary no-mapping pasa por el validador (retorna el valor) y pydantic lo rechaza.
    with pytest.raises(ValidationError):
        ExplainCardSection(summary=[1, 2, 3])  # type: ignore[arg-type]
    # metric_sections no-mapping (lista) retorna el valor y pydantic lo rechaza.
    with pytest.raises(ValidationError):
        ExplainCardSection(summary={"a": 1}, metric_sections=[1, 2, 3])  # type: ignore[arg-type]
    # metric_sections=None explícito se coacciona a {} (rama None → {}).
    assert ExplainCardSection(summary={"a": 1}, metric_sections=None).metric_sections == {}
    # metric_sections por default (default_factory) también es {}.
    assert ExplainCardSection(summary={"a": 1}).metric_sections == {}


# ── ExplainResult ──────────────────────────────────────────────────────────────────────────────
def _explain_result(**overrides: Any) -> ExplainResult:
    shap_local = (
        _local(row_key="0"),
        _local(row_key="1", pd_hat=0.3),
    )
    kwargs: dict[str, Any] = {
        "shap_global": (
            ShapGlobalRecord(
                feature="a",
                mean_abs_contribution=0.4,
                mean_signed_contribution=0.4,
                rank=1,
                source_model="ml",
            ),
            ShapGlobalRecord(
                feature="b",
                mean_abs_contribution=0.2,
                mean_signed_contribution=-0.2,
                rank=2,
                source_model="ml",
            ),
        ),
        "shap_local": shap_local,
        "reason_codes": (shap_local[0],),
        "scorecard_contributions": None,
        "comparison": (
            DriverComparisonRecord(
                feature="a",
                scorecard_rank=1,
                ml_rank=1,
                in_scorecard_topk=True,
                in_ml_topk=True,
                agreement="both",
            ),
        ),
        "explainer_metadata": ExplainerMetadata(
            ml_explainer_kind="tree",
            scorecard_explained=False,
            shap_version="0.44.1",
            contribution_space="log_odds",
            background_size=None,
            seed=1,
            deterministic=True,
            top_n_reason_codes=5,
        ),
        "card": ExplainCardSection(summary={"explainer": "tree"}),
    }
    kwargs.update(overrides)
    return ExplainResult(**kwargs)


def test_explain_result_term_structure_none_y_frames() -> None:
    result = _explain_result()
    assert result.term_structure() is None

    global_frame = result.global_frame()
    assert list(global_frame.columns) == [
        "feature",
        "mean_abs_contribution",
        "mean_signed_contribution",
        "rank",
        "source_model",
    ]
    assert list(global_frame["feature"]) == ["a", "b"]

    rc_frame = result.reason_codes_frame()
    assert list(rc_frame.columns) == [
        "row_key",
        "rank",
        "feature",
        "direction",
        "contribution",
        "bin_label",
    ]
    # Solo la vista top-N (row_key "0") con sus 2 reason codes.
    assert list(rc_frame["row_key"]) == ["0", "0"]
    assert list(rc_frame["rank"]) == [1, 2]


def test_reason_codes_frame_vacio_conserva_columnas() -> None:
    solo = _local(row_key="0", reason_codes=())
    result = _explain_result(shap_local=(solo,), reason_codes=(solo,))
    rc_frame = result.reason_codes_frame()
    assert list(rc_frame.columns) == [
        "row_key",
        "rank",
        "feature",
        "direction",
        "contribution",
        "bin_label",
    ]
    assert len(rc_frame) == 0


def test_explain_result_reason_codes_debe_ser_vista_de_shap_local() -> None:
    fabricado = _local(row_key="fantasma")
    with pytest.raises(ValidationError, match="vista top-N"):
        _explain_result(reason_codes=(fabricado,))


def test_explain_result_scorecard_contributions_copia_y_valida() -> None:
    frame = pd.DataFrame(
        {
            "feature": ["a", "b"],
            "contribution": [0.4, -0.0],
            "points": [10.0, 5.0],
            "n": [1, 2],
        }
    )
    result = _explain_result(scorecard_contributions=frame)
    leido = result.scorecard_contributions
    assert leido is not None
    # -0.0 normalizado a 0.0 en columnas float.
    assert math.copysign(1.0, leido.loc[1, "contribution"]) == 1.0
    # Copia defensiva: mutar la lectura no altera el interno.
    leido.loc[0, "contribution"] = 999.0
    assert result.scorecard_contributions.loc[0, "contribution"] == 0.4
    # La columna de puntos (sin ceros) se copia sin tocar; la columna int no se normaliza.
    assert_frame_equal(
        result.scorecard_contributions[["feature", "points", "n"]],
        frame[["feature", "points", "n"]],
    )

    with pytest.raises(ValidationError, match="DataFrame o None"):
        _explain_result(scorecard_contributions=[1, 2, 3])


# ── import liviano (núcleo) ─────────────────────────────────────────────────────────────────────
def test_import_results_liviano_no_arrastra_shap_ni_tabulares() -> None:
    assert explain_results.__all__  # el módulo expone su API pública
    code = (
        "import nikodym.explain.results, sys;"
        "bloqueados=[m for m in ('shap','matplotlib','sklearn','pandas','numpy') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
