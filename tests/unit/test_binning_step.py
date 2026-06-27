"""Tests de ``BinningStep``: contrato CT-1, auditoría, no mutación y golden WoE/IV."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.binning.step as step_module
from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.exceptions import BinningFitError
from nikodym.binning.results import BinningCardSection, BinningResult
from nikodym.binning.step import BINNING_ARTIFACTS, BinningStep
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.study import Study
from nikodym.data.config import (
    CohortSplitConfig,
    DataConfig,
    PartitionConfig,
    PerformanceWindow,
    Predicate,
    Rule,
    TargetConfig,
)
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.data.special import MaskedFrame
from nikodym.data.target import LabeledFrame, TargetSummary


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita importar OR-Tools dentro del proceso pytest."""
    del fake_binning_process


def _index(n: int = 12) -> pd.Index:
    """Índice estable para fixtures de binning."""
    return pd.Index([f"op-{position:03d}" for position in range(n)], name="loan_id")


def _base_frame(*, target: list[int] | None = None) -> pd.DataFrame:
    """Frame ya etiquetado/particionado como lo publica ``DataStep``."""
    index = _index()
    target_values = target or [0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1]
    return pd.DataFrame(
        {
            "score": [0, 0, 1, 1, 2, 2, 3, 3, 0, 3, 1, 2],
            "segment": ["A", "A", "A", "A", "B", "B", "B", "B", "Z", "A", "B", "Z"],
            "constant": [7.0] * 12,
            "all_missing": [np.nan] * 12,
            "drop_me": list(range(12)),
            "obs_date": pd.date_range("2024-01-01", periods=12, freq="MS"),
            "cohort": ["dev"] * 8 + ["oot"] * 4,
            "target": pd.Series(target_values, index=index, dtype="Int8"),
            "label_status": pd.Categorical(["bueno", "bueno", "bueno", "malo"] * 3),
            PARTITION_COL: pd.Categorical(
                ["desarrollo"] * 8 + ["holdout", "holdout", "oot", "oot"]
            ),
            TTD_COL: [True] * 12,
        },
        index=index,
    )


def _target_summary(frame: pd.DataFrame) -> TargetSummary:
    """Resumen mínimo compatible con ``LabeledFrame``."""
    bad_mask = frame["target"].eq(1).fillna(False)
    return TargetSummary(
        class_counts={
            "bueno": int(frame["target"].eq(0).sum()),
            "malo": int(bad_mask.sum()),
            "indeterminado": 0,
            "excluido": 0,
        },
        bad_rate=float(bad_mask.mean()),
        exclusions_by_reason={},
        ambiguous_rows=0,
    )


def _data_config() -> DataConfig:
    """Config ``data`` que declara fecha/cohorte para excluirlas de features automáticas."""
    return DataConfig(
        target=TargetConfig(
            bad_rule=Rule(all_of=(Predicate(col="raw_bad", op="==", value=1),)),
            window=PerformanceWindow(observation_date_col="obs_date"),
        ),
        partition=PartitionConfig(
            strategy=CohortSplitConfig(cohort_col="cohort", oot_cohorts=("oot",)),
            min_bads_per_partition=0,
        ),
    )


def _study_with_data(
    *,
    frame: pd.DataFrame | None = None,
    config: BinningConfig | None = None,
    special_catalog: dict[str, list[Any]] | None = None,
) -> Study:
    """Construye un ``Study`` con artefactos ``data`` ya publicados."""
    data_frame = _base_frame() if frame is None else frame
    cfg = config or BinningConfig(
        feature_columns=("score",),
        solver="mip",
        max_n_prebins=4,
        max_n_bins=4,
        min_bin_size=0.1,
        time_limit=5,
        monotonic_trend=None,
    )
    study = Study(NikodymConfig(data=_data_config(), binning=cfg))
    labels = LabeledFrame(
        frame=data_frame.copy(deep=True),
        target_col="target",
        status_col="label_status",
        summary=_target_summary(data_frame),
    )
    splits = PartitionResult(
        frame=data_frame.copy(deep=True),
        partition_col=PARTITION_COL,
        ttd_col=TTD_COL,
        sizes={"desarrollo": 8, "holdout": 2, "oot": 2, "fuera_de_modelo": 0},
        bad_rates={"desarrollo": 0.5, "holdout": 0.5, "oot": 0.5, "fuera_de_modelo": 0.0},
        strategy_used="fixture",
    )
    mask = pd.DataFrame(False, index=data_frame.index, columns=data_frame.columns)
    special = MaskedFrame(
        frame=data_frame.copy(deep=True),
        special_mask=mask,
        special_catalog={} if special_catalog is None else special_catalog,
    )
    study.artifacts.set("data", "frame", data_frame)
    study.artifacts.set("data", "labels", labels)
    study.artifacts.set("data", "splits", splits)
    study.artifacts.set("data", "special", special)
    return study


def test_from_config_y_contrato_step_exacto() -> None:
    cfg = BinningConfig(feature_columns=("score",))
    step = BinningStep.from_config(cfg)

    assert isinstance(step, BinningStep)
    assert step.config is cfg
    assert step.name == "binning"
    assert step.requires == (
        ("data", "frame"),
        ("data", "labels"),
        ("data", "splits"),
        ("data", "special"),
    )
    assert step.provides == tuple(("binning", key) for key in BINNING_ARTIFACTS)


def test_feature_columns_star_excluye_estructurales_fechas_cohortes_y_exclude_columns() -> None:
    cfg = BinningConfig(
        feature_columns="*",
        exclude_columns=("drop_me", "constant", "all_missing"),
        categorical_columns=("segment",),
        solver="mip",
        max_n_prebins=4,
        max_n_bins=4,
        min_bin_size=0.1,
        time_limit=5,
        monotonic_trend=None,
    )
    study = _study_with_data(config=cfg)

    result = BinningStep.from_config(cfg).execute(study, np.random.default_rng(1))
    process = study.artifacts.get("binning", "process")

    assert process.feature_columns_ == ("score", "segment")
    assert set(result.woe_column_map) == {"score", "segment"}
    assert "obs_date" not in process.feature_columns_
    assert "cohort" not in process.feature_columns_


def test_feature_columns_inexistentes_fallan_con_lista_completa() -> None:
    cfg = BinningConfig(feature_columns=("score", "no_existe_1", "no_existe_2"))
    study = _study_with_data(config=cfg)

    with pytest.raises(BinningFitError, match=r"no_existe_1.*no_existe_2"):
        BinningStep.from_config(cfg).execute(study, np.random.default_rng(1))


def test_target_degenerado_en_desarrollo_falla_antes_de_fit() -> None:
    frame = _base_frame(target=[1] * 12)
    cfg = BinningConfig(feature_columns=("score",))
    study = _study_with_data(frame=frame, config=cfg)

    with pytest.raises(BinningFitError, match="Target degenerado"):
        BinningStep.from_config(cfg).execute(study, np.random.default_rng(1))


def test_log_decision_emite_decisiones_auditables_minimas() -> None:
    cfg = BinningConfig(
        feature_columns=("score", "constant", "all_missing", "segment"),
        categorical_columns=("segment",),
        solver="mip",
        max_n_prebins=4,
        max_n_bins=4,
        min_bin_size=0.1,
        time_limit=5,
        monotonic_trend=None,
    )
    study = _study_with_data(config=cfg, special_catalog={"score": [-999.0]})
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = BinningStep.from_config(cfg)
    step._audit = sink

    step.execute(study, np.random.default_rng(1))

    decisions = [event for event in sink.events if event.kind == "decision"]
    assert [event.payload["regla"] for event in decisions] == [
        "special_values",
        "variable_constante",
        "variable_all_missing",
        "bins_colapsados",
        "iv_sospechoso",
        "bins_colapsados",
        "iv_sospechoso",
        "categoria_no_vista",
    ]
    assert decisions[0].payload["valor"] == {
        "variable": "score",
        "conteo": 0,
        "codigos": [-999.0],
    }


def test_execute_no_muta_frame_de_data() -> None:
    cfg = BinningConfig(feature_columns=("score",), solver="mip", monotonic_trend=None)
    study = _study_with_data(config=cfg)
    before = study.artifacts.get("data", "frame").copy(deep=True)

    BinningStep.from_config(cfg).execute(study, np.random.default_rng(1))

    assert_frame_equal(study.artifacts.get("data", "frame"), before)


def test_golden_woe_iv_result_y_binning_card() -> None:
    cfg = BinningConfig(
        feature_columns=("score",),
        solver="mip",
        max_n_prebins=4,
        max_n_bins=4,
        min_bin_size=0.1,
        time_limit=5,
        monotonic_trend=None,
    )
    study = _study_with_data(config=cfg)

    result = BinningStep.from_config(cfg).execute(study, np.random.default_rng(1))

    log3 = math.log(3.0)
    table = result.tables["score"]
    assert isinstance(result, BinningResult)
    assert table.loc[0, "Non-event"] == 3
    assert table.loc[0, "Event"] == 1
    assert table.loc[0, "WoE"] == pytest.approx(log3)
    assert table.loc[1, "WoE"] == pytest.approx(-log3)
    assert result.summary.loc[0, "iv"] == pytest.approx(log3)
    assert result.summary.loc[0, "iv_band"] == "suspicious"
    assert result.variable_summaries[0].iv == pytest.approx(log3)
    assert result.variable_summaries[0].iv_band == "suspicious"
    assert result.woe_frame.index.equals(_base_frame().index)
    assert result.woe_frame.columns.tolist() == [
        "target",
        "label_status",
        PARTITION_COL,
        TTD_COL,
        "score__woe",
    ]
    assert result.woe_frame.loc["op-000", "score__woe"] == pytest.approx(log3)
    assert result.woe_frame.loc["op-009", "score__woe"] == pytest.approx(-log3)
    assert np.isfinite(result.woe_frame["score__woe"].to_numpy(dtype="float64")).all()

    card = study.artifacts.get("binning", "binning_card")
    assert isinstance(card, BinningCardSection)
    assert card.n_variables_requested == 1
    assert card.iv_by_variable == {"score": pytest.approx(log3)}


def test_execute_con_keep_structural_columns_false_publica_solo_woe() -> None:
    cfg = BinningConfig(
        feature_columns=("score",),
        solver="mip",
        monotonic_trend=None,
        keep_structural_columns=False,
    )
    study = _study_with_data(config=cfg)

    result = BinningStep.from_config(cfg).execute(study, np.random.default_rng(1))

    assert result.woe_frame.columns.tolist() == ["score__woe"]


def test_target_sin_filas_entrenables_o_valores_invalidos_falla() -> None:
    empty_target = _base_frame(target=[0] * 12)
    empty_target["target"] = pd.Series([pd.NA] * 12, index=empty_target.index, dtype="Int8")
    cfg = BinningConfig(feature_columns=("score",))
    with pytest.raises(BinningFitError, match="No hay filas de Desarrollo"):
        BinningStep.from_config(cfg).execute(
            _study_with_data(frame=empty_target, config=cfg),
            np.random.default_rng(1),
        )

    invalid_target = _base_frame(target=[0, 0, 2, 1, 0, 1, 1, 1, 0, 1, 0, 1])
    invalid_target["target"] = invalid_target["target"].astype("int64")
    with pytest.raises(BinningFitError, match="valores observados inválidos"):
        BinningStep.from_config(cfg).execute(
            _study_with_data(frame=invalid_target, config=cfg),
            np.random.default_rng(1),
        )


def test_validadores_de_artefactos_y_columnas_fallan_con_mensaje_propio() -> None:
    pd_mod = step_module._import_pandas()
    frame = _base_frame()

    with pytest.raises(BinningFitError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod)
    with pytest.raises(BinningFitError, match="LabeledFrame"):
        step_module._as_labeled_frame(object())
    with pytest.raises(BinningFitError, match="PartitionResult"):
        step_module._as_partition_result(object())
    with pytest.raises(BinningFitError, match="MaskedFrame"):
        step_module._as_masked_frame(object())
    with pytest.raises(BinningFitError, match="estructurales"):
        step_module._validate_required_columns(frame.drop(columns=["target"]), ("target",))


def test_resolucion_features_sin_columnas_y_data_config_dict() -> None:
    pd_mod = step_module._import_pandas()
    frame = _base_frame()
    dict_config = {
        "target": {
            "window": {
                "observation_date_col": "obs_date",
                "data_cutoff_col": "cutoff_date",
            }
        },
        "partition": {"strategy": {"date_col": "split_date", "cohort_col": "cohort"}},
    }

    assert step_module._data_temporal_columns(None) == set()
    assert step_module._data_temporal_columns(dict_config) == {
        "obs_date",
        "cutoff_date",
        "split_date",
        "cohort",
    }
    with pytest.raises(BinningFitError, match="No hay columnas candidatas"):
        step_module._resolve_feature_columns(
            frame=frame,
            target_col="target",
            status_col="label_status",
            partition_col=PARTITION_COL,
            ttd_col=TTD_COL,
            config=BinningConfig(feature_columns=("score",), exclude_columns=("score",)),
            data_config=None,
            pd=pd_mod,
        )


def test_helpers_de_auditoria_cubren_solver_monotonia_iv_bajo_y_unknown_cero() -> None:
    cfg = BinningConfig(
        feature_columns=("score", "segment"),
        variable_overrides=(
            VariableBinningConfig(
                name="segment",
                monotonic_trend="descending",
                max_n_bins=3,
            ),
        ),
        monotonic_trend="ascending",
        max_n_bins=4,
    )
    step = BinningStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink
    pd_mod = step_module._import_pandas()

    step._log_skipped_variables(
        {
            "single": "single_class",
            "solver": "solver_status:FEASIBLE",
            "otra": "missing_summary",
        }
    )
    step._log_monotonicity_overrides(("score", "segment"))
    step._log_summary_diagnostics(
        pd.DataFrame(
            [
                {"name": "score", "selected": True, "iv": 0.0, "n_bins": 1},
                {"name": "segment", "selected": True, "iv": 0.10, "n_bins": 3},
                {"name": "skipped", "selected": False, "iv": 0.0, "n_bins": 0},
            ]
        ),
        pd_mod,
    )
    step._log_unknown_categories({"segment": 0, "other": 2})

    assert [event.payload["regla"] for event in sink.events] == [
        "variable_single_class",
        "solver_no_optimo",
        "monotonia_forzada",
        "monotonia_forzada",
        "bins_colapsados",
        "iv_bajo",
        "categoria_no_vista",
    ]
    assert step_module._effective_max_n_bins(cfg, cfg.variable_overrides[0]) == 3


def test_helpers_de_summary_version_y_optional_string(monkeypatch: pytest.MonkeyPatch) -> None:
    pd_mod = step_module._import_pandas()

    empty = pd.DataFrame(columns=["iv"])
    assert step_module._summary_with_fresh_iv_band(empty, pd_mod).empty
    with pytest.raises(BinningFitError, match="dtype no soportado"):
        step_module._summary_dtype("datetime")
    assert step_module._optional_string(None, pd_mod) is None
    assert step_module._optional_string(float("nan"), pd_mod) is None
    assert step_module._optional_string("", pd_mod) is None
    assert step_module._optional_string("<NA>", pd_mod) is None
    assert step_module._optional_string("ascending", pd_mod) == "ascending"

    def _raise_missing(_name: str) -> str:
        raise step_module.metadata.PackageNotFoundError

    monkeypatch.setattr(step_module.metadata, "version", _raise_missing)
    assert step_module._optbinning_version() == "no_instalado"
