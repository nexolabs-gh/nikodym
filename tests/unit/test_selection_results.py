"""Tests de resultados de ``selection``: decisiones, model card y lazy exports."""

from __future__ import annotations

import math
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pydantic import ValidationError

from nikodym.binning.results import iv_band as binning_iv_band
from nikodym.selection import results as selection_results
from nikodym.selection.results import (
    SelectionCardSection,
    SelectionDecisionReason,
    SelectionResult,
    VariableSelectionDecision,
)


def test_variable_selection_decision_construible_frozen_y_extra_forbid() -> None:
    decision = _decision(
        "saldo",
        included=True,
        reason="business_include",
        iv=0.31,
        forced="include",
        detail="negocio conserva saldo por política interna",
    )

    assert decision.iv_band == "strong"
    assert decision.detail == "negocio conserva saldo por política interna"
    with pytest.raises(ValidationError, match="frozen"):
        decision.reason = "included"
    with pytest.raises(ValidationError):
        VariableSelectionDecision(
            feature="mora",
            woe_column="mora__woe",
            included=True,
            reason="otra_razon",
            iv=0.1,
            iv_band="medium",
            auc=None,
            gini=None,
            ks=None,
            max_abs_corr=None,
            max_corr_with=None,
            vif=None,
            max_csi=None,
        )
    with pytest.raises(ValidationError):
        VariableSelectionDecision(
            feature="mora",
            woe_column="mora__woe",
            included=True,
            reason="included",
            iv=0.1,
            iv_band="medium",
            auc=None,
            gini=None,
            ks=None,
            max_abs_corr=None,
            max_corr_with=None,
            vif=None,
            max_csi=None,
            detalle="campo extra",
        )
    with pytest.raises(ValidationError, match="iv_band no coincide"):
        VariableSelectionDecision(
            feature="mora",
            woe_column="mora__woe",
            included=True,
            reason="included",
            iv=0.1,
            iv_band="strong",
            auc=None,
            gini=None,
            ks=None,
            max_abs_corr=None,
            max_corr_with=None,
            vif=None,
            max_csi=None,
        )


def test_selection_result_construible_con_dataframes() -> None:
    result = _golden_result()

    assert result.candidate_features == ("saldo", "ingreso", "antiguedad", "mora")
    assert result.selected_features == ("saldo", "ingreso")
    assert_frame_equal(result.selected_woe_frame, _selected_woe_frame())
    assert_frame_equal(result.selection_table, _selection_table(result.decisions))
    assert result.decisions[2].reason == "low_iv"


def test_selection_card_section_from_result_golden_bit_identica() -> None:
    card = SelectionCardSection.from_result(
        _golden_result(),
        thresholds=_thresholds(),
        dependency_versions={
            "statsmodels": "0.14.6",
            "pandas": "2.3.3",
            "scikit-learn": "1.7.2",
        },
    )

    expected_dump = {
        "n_candidates": 4,
        "n_selected": 2,
        "n_excluded": 2,
        "thresholds": {
            "correlation.method": "pearson",
            "correlation.threshold": 0.75,
            "max_iv": 0.5,
            "max_iv_action": "flag",
            "min_iv": 0.02,
            "stability.stable_threshold": 0.1,
            "vif.threshold": 5.0,
        },
        "excluded_by_reason": {"low_iv": 1, "high_correlation": 1},
        "selected_features": ["saldo", "ingreso"],
        "high_iv_flags": ["ingreso"],
        "stability_flags": ["ingreso", "mora"],
        "max_abs_correlation_after_selection": 0.12,
        "max_vif_after_selection": 2.4,
        "dependency_versions": {
            "pandas": "2.3.3",
            "scikit-learn": "1.7.2",
            "statsmodels": "0.14.6",
        },
    }
    expected = SelectionCardSection(**expected_dump)
    assert card == expected
    assert card.model_dump(mode="json") == expected_dump


def test_selection_card_section_from_result_no_muta_resultado_ni_parametros() -> None:
    result = _golden_result()
    original_selected = result.selected_woe_frame.copy(deep=True)
    original_table = result.selection_table.copy(deep=True)
    original_corr = result.correlation_matrix.copy(deep=True)
    original_vif = result.vif_table.copy(deep=True)
    original_stability = result.stability_table.copy(deep=True)
    original_decisions = result.decisions
    thresholds = _thresholds()
    dependency_versions = {"statsmodels": "0.14.6", "pandas": "2.3.3"}
    original_thresholds = dict(thresholds)
    original_versions = dict(dependency_versions)

    SelectionCardSection.from_result(
        result,
        thresholds=thresholds,
        dependency_versions=dependency_versions,
    )

    assert_frame_equal(result.selected_woe_frame, original_selected)
    assert_frame_equal(result.selection_table, original_table)
    assert_frame_equal(result.correlation_matrix, original_corr)
    assert_frame_equal(result.vif_table, original_vif)
    assert_frame_equal(result.stability_table, original_stability)
    assert result.decisions == original_decisions
    assert thresholds == original_thresholds
    assert dependency_versions == original_versions


def test_selection_card_section_normaliza_menos_cero_en_agregados_float() -> None:
    decision_saldo = _decision("saldo", included=True, reason="included", iv=0.12, vif=-0.0)
    decision_ingreso = _decision("ingreso", included=True, reason="included", iv=0.11, vif=None)
    result = _result(
        decisions=(decision_saldo, decision_ingreso),
        candidate_features=("saldo", "ingreso"),
        candidate_woe_columns=("saldo__woe", "ingreso__woe"),
        selected_features=("saldo", "ingreso"),
        selected_woe_columns=("saldo__woe", "ingreso__woe"),
        correlation_matrix=pd.DataFrame(
            [[1.0, -0.0], [-0.0, 1.0]],
            index=["saldo__woe", "ingreso__woe"],
            columns=["saldo__woe", "ingreso__woe"],
        ),
    )

    card = SelectionCardSection.from_result(
        result,
        thresholds={"max_iv": None, "stability.stable_threshold": None},
        dependency_versions={},
    )

    assert card.max_abs_correlation_after_selection == 0.0
    assert math.copysign(1.0, card.max_abs_correlation_after_selection) == 1.0
    assert card.max_vif_after_selection == 0.0
    assert math.copysign(1.0, card.max_vif_after_selection) == 1.0


def test_selection_card_section_orden_determinista_ante_decisions_y_features_reordenadas() -> None:
    base = _golden_result()
    reordenado = _result(
        decisions=tuple(reversed(base.decisions)),
        candidate_features=base.candidate_features,
        candidate_woe_columns=base.candidate_woe_columns,
        selected_features=("ingreso", "saldo"),
        selected_woe_columns=("ingreso__woe", "saldo__woe"),
        correlation_matrix=base.correlation_matrix,
    )

    card_base = SelectionCardSection.from_result(
        base,
        thresholds=_thresholds(),
        dependency_versions={"statsmodels": "0.14.6", "pandas": "2.3.3"},
    )
    card_reordenada = SelectionCardSection.from_result(
        reordenado,
        thresholds={
            "vif.threshold": 5.0,
            "stability.stable_threshold": 0.1,
            "min_iv": 0.02,
            "max_iv_action": "flag",
            "max_iv": 0.5,
            "correlation.threshold": 0.75,
            "correlation.method": "pearson",
        },
        dependency_versions={"pandas": "2.3.3", "statsmodels": "0.14.6"},
    )

    assert card_reordenada == card_base


def test_selection_card_section_filtra_correlaciones_nan_de_forma_determinista() -> None:
    decisions = (
        _decision("saldo", included=True, reason="included", iv=0.31),
        _decision("ingreso", included=True, reason="included", iv=0.22),
        _decision("antiguedad", included=True, reason="included", iv=0.12),
    )
    matrix = pd.DataFrame(
        [
            [1.0, math.nan, 0.4],
            [math.nan, 1.0, 0.9],
            [0.4, 0.9, 1.0],
        ],
        index=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
        columns=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
    )
    base = _result(
        decisions=decisions,
        candidate_features=("saldo", "ingreso", "antiguedad"),
        candidate_woe_columns=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
        selected_features=("saldo", "ingreso", "antiguedad"),
        selected_woe_columns=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
        correlation_matrix=matrix,
    )
    reordenado = _result(
        decisions=decisions,
        candidate_features=("saldo", "ingreso", "antiguedad"),
        candidate_woe_columns=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
        selected_features=("saldo", "ingreso", "antiguedad"),
        selected_woe_columns=("saldo__woe", "antiguedad__woe", "ingreso__woe"),
        correlation_matrix=matrix,
    )

    card_base = SelectionCardSection.from_result(base, thresholds={}, dependency_versions={})
    card_reordenada = SelectionCardSection.from_result(
        reordenado,
        thresholds={},
        dependency_versions={},
    )

    assert card_base.max_abs_correlation_after_selection == 0.9
    assert card_reordenada.max_abs_correlation_after_selection == 0.9
    assert card_reordenada.max_abs_correlation_after_selection == (
        card_base.max_abs_correlation_after_selection
    )

    all_nan = _result(
        decisions=decisions[:2],
        candidate_features=("saldo", "ingreso"),
        candidate_woe_columns=("saldo__woe", "ingreso__woe"),
        selected_features=("saldo", "ingreso"),
        selected_woe_columns=("saldo__woe", "ingreso__woe"),
        correlation_matrix=pd.DataFrame(
            [[1.0, math.nan], [math.nan, 1.0]],
            index=("saldo__woe", "ingreso__woe"),
            columns=("saldo__woe", "ingreso__woe"),
        ),
    )
    card_all_nan = SelectionCardSection.from_result(
        all_nan,
        thresholds={},
        dependency_versions={},
    )
    assert card_all_nan.max_abs_correlation_after_selection is None


def test_selection_card_section_filtra_vif_no_finito_de_forma_determinista() -> None:
    decisions = (
        _decision("saldo", included=True, reason="included", iv=0.31, vif=math.inf),
        _decision("ingreso", included=True, reason="included", iv=0.22, vif=4.5),
        _decision("antiguedad", included=True, reason="included", iv=0.12, vif=math.nan),
        _decision("mora", included=False, reason="high_vif", iv=0.11, vif=9.0),
    )
    result = _result(
        decisions=decisions,
        candidate_features=("saldo", "ingreso", "antiguedad", "mora"),
        candidate_woe_columns=("saldo__woe", "ingreso__woe", "antiguedad__woe", "mora__woe"),
        selected_features=("saldo", "ingreso", "antiguedad"),
        selected_woe_columns=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
        correlation_matrix=pd.DataFrame(
            [
                [1.0, 0.2, 0.3],
                [0.2, 1.0, 0.4],
                [0.3, 0.4, 1.0],
            ],
            index=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
            columns=("saldo__woe", "ingreso__woe", "antiguedad__woe"),
        ),
    )
    reordenado = _result(
        decisions=tuple(reversed(decisions)),
        candidate_features=result.candidate_features,
        candidate_woe_columns=result.candidate_woe_columns,
        selected_features=result.selected_features,
        selected_woe_columns=result.selected_woe_columns,
        correlation_matrix=result.correlation_matrix,
    )

    card = SelectionCardSection.from_result(result, thresholds={}, dependency_versions={})
    card_reordenada = SelectionCardSection.from_result(
        reordenado,
        thresholds={},
        dependency_versions={},
    )

    assert card.max_vif_after_selection == 4.5
    assert card_reordenada.max_vif_after_selection == 4.5
    assert card_reordenada.max_vif_after_selection == card.max_vif_after_selection

    all_non_finite = _result(
        decisions=(
            _decision("saldo", included=True, reason="included", iv=0.31, vif=math.inf),
            _decision("ingreso", included=True, reason="included", iv=0.22, vif=math.nan),
        ),
        candidate_features=("saldo", "ingreso"),
        candidate_woe_columns=("saldo__woe", "ingreso__woe"),
        selected_features=("saldo", "ingreso"),
        selected_woe_columns=("saldo__woe", "ingreso__woe"),
        correlation_matrix=pd.DataFrame(
            [[1.0, 0.2], [0.2, 1.0]],
            index=("saldo__woe", "ingreso__woe"),
            columns=("saldo__woe", "ingreso__woe"),
        ),
    )
    card_all_non_finite = SelectionCardSection.from_result(
        all_non_finite,
        thresholds={},
        dependency_versions={},
    )
    assert card_all_non_finite.max_vif_after_selection is None


def test_selection_card_section_sin_candidatas() -> None:
    result = _result(
        decisions=(),
        candidate_features=(),
        candidate_woe_columns=(),
        selected_features=(),
        selected_woe_columns=(),
        correlation_matrix=pd.DataFrame(),
    )

    card = SelectionCardSection.from_result(result, thresholds={}, dependency_versions={})

    assert card == SelectionCardSection(
        n_candidates=0,
        n_selected=0,
        n_excluded=0,
        thresholds={},
        excluded_by_reason={},
        selected_features=(),
        high_iv_flags=(),
        stability_flags=(),
        max_abs_correlation_after_selection=None,
        max_vif_after_selection=None,
        dependency_versions={},
    )


def test_selection_card_section_excluded_by_reason_con_todos_los_motivos() -> None:
    reasons: tuple[SelectionDecisionReason, ...] = (
        "included",
        "business_exclude",
        "business_include",
        "low_iv",
        "high_iv",
        "low_auc",
        "low_ks",
        "low_gini",
        "high_correlation",
        "high_vif",
        "cluster_representative_lost",
        "constant_or_nonfinite",
        "missing_binning_artifact",
        "forced_conflict",
        "high_stability",
    )
    decisions = tuple(
        _decision(f"feature_{index:02d}", included=False, reason=reason, iv=0.01)
        for index, reason in enumerate(reasons)
    )
    result = _result(
        decisions=decisions,
        candidate_features=tuple(decision.feature for decision in decisions),
        candidate_woe_columns=tuple(decision.woe_column for decision in decisions),
        selected_features=(),
        selected_woe_columns=(),
        correlation_matrix=pd.DataFrame(),
    )

    card = SelectionCardSection.from_result(result, thresholds={}, dependency_versions={})

    assert card.excluded_by_reason == {reason: 1 for reason in reasons}


def test_selection_results_reutiliza_iv_band_de_binning() -> None:
    assert selection_results.iv_band is binning_iv_band
    decision = _decision("iv_medio", included=True, reason="included", iv=0.10)
    assert decision.iv_band == "medium"


def test_selection_lazy_exports_publicos_no_arrastran_pandas_hasta_acceder_results() -> None:
    code = (
        "import sys;"
        "import nikodym.selection as selection;"
        "assert 'pandas' not in sys.modules, 'pandas cargado antes del lazy export';"
        "symbols=('SelectionDecisionReason','VariableSelectionDecision',"
        "'SelectionResult','SelectionCardSection');"
        "loaded=[getattr(selection, name) for name in symbols];"
        "assert loaded[2].__name__ == 'SelectionResult';"
        "assert 'pandas' in sys.modules;"
        "blocked=[m for m in ('sklearn','statsmodels','scipy','optbinning') if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def _decision(
    feature: str,
    *,
    included: bool,
    reason: SelectionDecisionReason,
    iv: float,
    auc: float | None = 0.70,
    gini: float | None = 0.40,
    ks: float | None = 0.30,
    max_abs_corr: float | None = None,
    max_corr_with: str | None = None,
    vif: float | None = None,
    max_csi: float | None = None,
    forced: str | None = None,
    detail: str | None = None,
) -> VariableSelectionDecision:
    return VariableSelectionDecision(
        feature=feature,
        woe_column=f"{feature}__woe",
        included=included,
        reason=reason,
        iv=iv,
        iv_band=binning_iv_band(iv),
        auc=auc,
        gini=gini,
        ks=ks,
        max_abs_corr=max_abs_corr,
        max_corr_with=max_corr_with,
        vif=vif,
        max_csi=max_csi,
        forced=forced,
        detail=detail,
    )


def _golden_decisions() -> tuple[VariableSelectionDecision, ...]:
    return (
        _decision(
            "saldo",
            included=True,
            reason="included",
            iv=0.31,
            auc=0.78,
            gini=0.56,
            ks=0.42,
            max_abs_corr=0.12,
            max_corr_with="ingreso",
            vif=1.8,
            max_csi=0.08,
        ),
        _decision(
            "ingreso",
            included=True,
            reason="business_include",
            iv=0.55,
            auc=0.74,
            gini=0.48,
            ks=0.35,
            max_abs_corr=0.12,
            max_corr_with="saldo",
            vif=2.4,
            max_csi=0.12,
            forced="include",
            detail="override de negocio documentado",
        ),
        _decision(
            "antiguedad",
            included=False,
            reason="low_iv",
            iv=0.015,
            auc=0.53,
            gini=0.06,
            ks=0.08,
            max_csi=0.02,
            detail="IV bajo mínimo configurado",
        ),
        _decision(
            "mora",
            included=False,
            reason="high_correlation",
            iv=0.20,
            auc=0.70,
            gini=0.40,
            ks=0.30,
            max_abs_corr=0.82,
            max_corr_with="saldo",
            max_csi=0.30,
            detail="correlación alta contra feature retenida",
        ),
    )


def _golden_result() -> SelectionResult:
    decisions = _golden_decisions()
    return _result(
        decisions=decisions,
        candidate_features=("saldo", "ingreso", "antiguedad", "mora"),
        candidate_woe_columns=("saldo__woe", "ingreso__woe", "antiguedad__woe", "mora__woe"),
        selected_features=("saldo", "ingreso"),
        selected_woe_columns=("saldo__woe", "ingreso__woe"),
        correlation_matrix=pd.DataFrame(
            [
                [1.0, -0.12, 0.20, 0.82],
                [-0.12, 1.0, 0.05, 0.11],
                [0.20, 0.05, 1.0, 0.18],
                [0.82, 0.11, 0.18, 1.0],
            ],
            index=("saldo__woe", "ingreso__woe", "antiguedad__woe", "mora__woe"),
            columns=("saldo__woe", "ingreso__woe", "antiguedad__woe", "mora__woe"),
        ),
    )


def _result(
    *,
    decisions: tuple[VariableSelectionDecision, ...],
    candidate_features: tuple[str, ...],
    candidate_woe_columns: tuple[str, ...],
    selected_features: tuple[str, ...],
    selected_woe_columns: tuple[str, ...],
    correlation_matrix: pd.DataFrame,
) -> SelectionResult:
    return SelectionResult(
        candidate_features=candidate_features,
        candidate_woe_columns=candidate_woe_columns,
        selected_features=selected_features,
        selected_woe_columns=selected_woe_columns,
        selected_woe_frame=_selected_woe_frame(selected_woe_columns),
        selection_table=_selection_table(decisions),
        correlation_matrix=correlation_matrix,
        vif_table=pd.DataFrame(
            {
                "feature": ["saldo", "ingreso"],
                "iteration": pd.Series([0, 0], dtype="int64"),
                "vif": [1.8, 2.4],
            }
        ),
        stability_table=pd.DataFrame(
            {
                "feature": ["saldo", "ingreso", "mora"],
                "sample": ["holdout", "holdout", "oot"],
                "csi": [0.08, 0.12, 0.30],
            }
        ),
        decisions=decisions,
    )


def _selected_woe_frame(
    selected_woe_columns: tuple[str, ...] = ("saldo__woe", "ingreso__woe"),
) -> pd.DataFrame:
    base = pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0], dtype="int64"),
            "partition": ["desarrollo", "desarrollo", "holdout"],
            "saldo__woe": [0.7, -0.4, 0.1],
            "ingreso__woe": [0.2, -0.1, 0.0],
            "antiguedad__woe": [0.1, 0.1, 0.1],
            "mora__woe": [0.8, -0.5, 0.3],
        },
        index=pd.Index(["c1", "c2", "c3"], name="cliente_id"),
    )
    return base.loc[:, ("target", "partition", *selected_woe_columns)]


def _selection_table(decisions: tuple[VariableSelectionDecision, ...]) -> pd.DataFrame:
    return pd.DataFrame([decision.model_dump(mode="json") for decision in decisions])


def _thresholds() -> dict[str, float | str | None]:
    return {
        "min_iv": 0.02,
        "max_iv": 0.50,
        "max_iv_action": "flag",
        "correlation.method": "pearson",
        "correlation.threshold": 0.75,
        "vif.threshold": 5.0,
        "stability.stable_threshold": 0.10,
    }
