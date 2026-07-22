"""Tests de ``FeatureSelector`` (SDD-07 §4/§7/§11)."""

from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import textwrap
from typing import Any, cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sklearn.base import clone

import nikodym.selection.selector as selector_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, MissingDependencyError, NotFittedError
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.selection.exceptions import SelectionFitError, SelectionTransformError
from nikodym.selection.selector import FeatureSelector


def test_import_selection_liviano_no_carga_selector_ni_deps_pesadas() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.selection

        blocked = [
            name for name in (
                "nikodym.selection.selector",
                "pandas",
                "sklearn",
                "statsmodels",
                "scipy",
                "optbinning",
            )
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
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_reexport_feature_selector_sin_sklearn_falla_con_missing_dependency() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.selection
        from nikodym.core.exceptions import MissingDependencyError


        class BlockSklearn:
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "sklearn" or fullname.startswith("sklearn."):
                    raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
                return None


        sys.meta_path.insert(0, BlockSklearn())
        try:
            nikodym.selection.FeatureSelector
        except MissingDependencyError as exc:
            assert "instale nikodym[scoring]" in str(exc)
        else:
            raise AssertionError("FeatureSelector no tradujo la ausencia de sklearn")
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_import_selector_sin_sklearn_cubre_rama_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockSklearn:
        def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
            del path, target
            if fullname == "sklearn" or fullname.startswith("sklearn."):
                raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")

    for name in [name for name in sys.modules if name == "sklearn" or name.startswith("sklearn.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [BlockSklearn(), *sys.meta_path])

    module_path = selector_module.__file__
    assert module_path is not None
    spec = importlib.util.spec_from_file_location(
        "nikodym.selection._missing_sklearn_selector_test",
        module_path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        loader.exec_module(module)


def test_imports_perezosos_traducen_dependencias_base_y_metricas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = selector_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(selector_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="pandas"):
        selector_module._import_pandas()

    def block_numpy(name: str) -> Any:
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name)

    monkeypatch.setattr(selector_module.importlib, "import_module", block_numpy)
    with pytest.raises(MissingDependencyError, match="numpy"):
        selector_module._import_numpy()

    def block_metrics(name: str) -> Any:
        if name == "sklearn.metrics":
            raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
        return real_import(name)

    monkeypatch.setattr(selector_module.importlib, "import_module", block_metrics)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        FeatureSelector(min_iv=0.0, vif_enabled=False).fit(
            _metric_frame(),
            target_col="target",
            partition_col="partition",
            binning_summary=_summary({"score": 0.12}),
            woe_column_map={"score": "score__woe"},
        )


def test_vif_sin_statsmodels_falla_con_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    real_import = selector_module.importlib.import_module

    def fake_import_module(name: str) -> Any:
        if name == "statsmodels.stats.outliers_influence":
            raise ModuleNotFoundError("No module named 'statsmodels'", name="statsmodels")
        return real_import(name)

    monkeypatch.setattr(selector_module.importlib, "import_module", fake_import_module)

    selector = FeatureSelector(min_iv=0.0, correlation_threshold=1.0)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        selector.fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )


def test_from_config_clone_safe_transform_y_not_fitted() -> None:
    cfg = SelectionConfig(
        min_iv=0.01,
        correlation=CorrelationSelectionConfig(threshold=0.8),
        vif=VifSelectionConfig(enabled=False),
        stability=StabilitySelectionConfig(enabled=False),
    )
    selector = FeatureSelector.from_config(cfg)
    selector_from_dict = FeatureSelector.from_config(cfg.model_dump())
    cloned = clone(selector)

    assert cloned.get_params()["min_iv"] == 0.01
    assert selector_from_dict.get_params()["min_iv"] == 0.01
    assert cloned.get_params()["correlation_threshold"] == 0.8
    assert cloned.set_params(min_iv=0.0).get_params()["min_iv"] == 0.0

    with pytest.raises(NotFittedError, match="no está fiteado"):
        selector.transform(_metric_frame())

    fitted = selector.fit(
        _metric_frame(),
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"score": 0.12}),
        woe_column_map={"score": "score__woe"},
    )
    transformed = fitted.transform(_metric_frame())
    assert transformed.index.tolist() == [0, 1, 2, 3]
    assert transformed.columns.tolist() == ["target", "partition", "score__woe"]

    with pytest.raises(SelectionTransformError, match="faltan: 'score__woe'"):
        fitted.transform(_metric_frame().drop(columns=["score__woe"]))

    nonfinite = _metric_frame()
    nonfinite.loc[0, "score__woe"] = math.inf
    with pytest.raises(SelectionTransformError, match="WoE no finita"):
        fitted.transform(nonfinite)

    sin_estructurales = FeatureSelector(
        min_iv=0.0,
        vif_enabled=False,
        stability_enabled=False,
        keep_structural_columns=False,
    ).fit(
        _metric_frame(),
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"score": 0.12}),
        woe_column_map={"score": "score__woe"},
    )
    assert sin_estructurales.transform(_metric_frame()).columns.tolist() == ["score__woe"]


def test_auc_ks_gini_golden_manual_risk_score_menos_woe() -> None:
    selector = FeatureSelector(
        min_iv=0.0,
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        _metric_frame(),
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"score": 0.12}),
        woe_column_map={"score": "score__woe"},
    )

    row = selector.selection_table_.iloc[0].to_dict()
    assert row["auc"] == pytest.approx(0.75)
    assert row["gini"] == pytest.approx(0.50)
    assert row["ks"] == pytest.approx(0.50)
    assert row["iv"] == pytest.approx(0.12)
    assert row["iv_band"] == "medium"
    assert selector.selected_features_ == ("score",)


def test_correlacion_perfecta_retiene_mayor_iv_y_no_muta_inputs() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    original_frame = frame.copy(deep=True)
    original_summary = summary.copy(deep=True)
    original_map = dict(woe_map)

    selector = FeatureSelector(
        min_iv=0.0,
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )

    assert selector.selected_features_ == ("x2", "x3")
    x1 = selector.selection_table_.set_index("feature").loc["x1"]
    assert x1["reason"] == "high_correlation"
    assert x1["max_corr_with"] == "x2"
    assert x1["max_abs_corr"] == pytest.approx(1.0)
    assert selector.correlation_matrix_.loc["x2__woe", "x1__woe"] == pytest.approx(1.0)
    assert_frame_equal(frame, original_frame)
    assert_frame_equal(summary, original_summary)
    assert woe_map == original_map


def test_vif_infinito_captura_runtimewarning_y_excluye_redundante() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    selector = FeatureSelector(
        min_iv=0.0,
        correlation_threshold=1.0,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )

    assert selector.selected_features_ == ("x2", "x3")
    removed = selector.vif_table_.loc[selector.vif_table_["removed"]].iloc[0]
    assert removed["feature"] == "x1"
    assert math.isinf(float(removed["vif"]))
    assert removed["reason"] == "high_vif"
    assert selector.selection_table_.set_index("feature").loc["x1", "reason"] == "high_vif"


def test_overrides_force_include_force_exclude_audit_y_errores() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    summary = summary.assign(iv=[0.01, 0.40, 0.15])
    audit = InMemoryAuditSink()

    selector = FeatureSelector(
        min_iv=0.20,
        force_include=("x1",),
        force_exclude=("x3",),
        correlation_enabled=False,
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
        audit=audit,
    )
    table = selector.selection_table_.set_index("feature")

    assert bool(table.loc["x1", "included"]) is True
    assert table.loc["x1", "reason"] == "business_include"
    assert table.loc["x1", "forced"] == "include"
    assert bool(table.loc["x3", "included"]) is False
    assert table.loc["x3", "reason"] == "business_exclude"
    assert {event.payload["regla"] for event in audit.events} == {
        "business_include",
        "business_exclude",
    }

    with pytest.raises(SelectionFitError, match="'fantasma'"):
        FeatureSelector(force_include=("fantasma",)).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )

    nonfinite = frame.copy(deep=True)
    nonfinite.loc[0, "x1__woe"] = math.inf
    with pytest.raises(SelectionFitError, match=r"Overrides.*no finitas"):
        FeatureSelector(force_include=("x1",)).fit(
            nonfinite,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )


def test_overrides_con_alias_woe_son_equivalentes_a_nombres_raw() -> None:
    """Raw y alias WoE producen la misma selección, decisión y auditoría."""
    frame, summary, woe_map = _canonical_frame_summary_map()
    summary = summary.assign(iv=[0.01, 0.40, 0.15])

    def fit_overrides(
        *, force_include: tuple[str, ...], force_exclude: tuple[str, ...]
    ) -> tuple[FeatureSelector, InMemoryAuditSink]:
        audit = InMemoryAuditSink()
        selector = FeatureSelector(
            min_iv=0.20,
            force_include=force_include,
            force_exclude=force_exclude,
            correlation_enabled=False,
            vif_enabled=False,
            stability_enabled=False,
        ).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
            audit=audit,
        )
        return selector, audit

    raw, raw_audit = fit_overrides(force_include=("x1",), force_exclude=("x3",))
    alias, alias_audit = fit_overrides(force_include=("x1__woe",), force_exclude=("x3__woe",))

    assert alias.selected_features_ == raw.selected_features_ == ("x2", "x1")
    assert alias.selected_woe_columns_ == raw.selected_woe_columns_
    assert alias.excluded_features_ == raw.excluded_features_
    assert alias.decisions_ == raw.decisions_
    assert_frame_equal(alias.selection_table_, raw.selection_table_)
    assert [event.model_dump(exclude={"ts"}) for event in alias_audit.events] == [
        event.model_dump(exclude={"ts"}) for event in raw_audit.events
    ]
    assert alias.get_params(deep=False)["force_include"] == ("x1__woe",)
    assert alias.get_params(deep=False)["force_exclude"] == ("x3__woe",)


@pytest.mark.parametrize("override", ["force_include", "force_exclude"])
def test_override_con_alias_woe_desconocido_falla(override: str) -> None:
    """Un alias WoE sin mapping falla para inclusión y exclusión forzadas."""
    frame, summary, woe_map = _canonical_frame_summary_map()
    force_include = ("fantasma__woe",) if override == "force_include" else ()
    force_exclude = ("fantasma__woe",) if override == "force_exclude" else ()

    with pytest.raises(SelectionFitError, match=rf"{override}.*'fantasma__woe'"):
        FeatureSelector(
            force_include=force_include,
            force_exclude=force_exclude,
        ).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )


@pytest.mark.parametrize(
    ("force_include", "force_exclude"),
    [("x1", "x1__woe"), ("x1__woe", "x1")],
)
def test_overrides_raw_y_alias_equivalentes_en_conflicto_fallan(
    force_include: str,
    force_exclude: str,
) -> None:
    """El conflicto se detecta después de canonicalizar ambos identificadores."""
    frame, summary, woe_map = _canonical_frame_summary_map()

    with pytest.raises(
        SelectionFitError,
        match=r"force_include y force_exclude.*misma feature raw.*'x1'",
    ):
        FeatureSelector(
            force_include=(force_include,),
            force_exclude=(force_exclude,),
        ).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )


def test_force_include_correlacionada_llega_a_conflicto_vif() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    with pytest.raises(SelectionFitError, match="force_include"):
        FeatureSelector(
            min_iv=0.0,
            force_include=("x1", "x2"),
            correlation_threshold=0.75,
            stability_enabled=False,
        ).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )


def test_force_include_desplaza_retenida_no_forzada_por_correlacion() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    selector = FeatureSelector(
        min_iv=0.0,
        force_include=("x1",),
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )
    table = selector.selection_table_.set_index("feature")

    assert selector.selected_features_ == ("x1", "x3")
    assert table.loc["x2", "reason"] == "high_correlation"
    assert table.loc["x2", "max_corr_with"] == "x1"


def test_anti_leakage_holdout_solo_mueve_stability_table() -> None:
    base = _stability_frame()
    changed = base.copy(deep=True)
    changed.loc[changed["partition"].eq("holdout"), "a__woe"] = [1.0, 1.0, 1.0, 1.0]
    summary = _summary({"a": 0.20, "b": 0.10})
    woe_map = {"a": "a__woe", "b": "b__woe"}

    common_kwargs = {
        "target_col": "target",
        "partition_col": "partition",
        "binning_summary": summary,
        "woe_column_map": woe_map,
    }
    selector_base = FeatureSelector(
        min_iv=0.0,
        correlation_enabled=False,
        vif_enabled=False,
        stability_smoothing=1e-12,
    ).fit(base, **common_kwargs)
    selector_changed = FeatureSelector(
        min_iv=0.0,
        correlation_enabled=False,
        vif_enabled=False,
        stability_smoothing=1e-12,
    ).fit(changed, **common_kwargs)

    assert selector_base.selected_features_ == selector_changed.selected_features_
    assert (
        selector_base.selection_table_["reason"].tolist()
        == selector_changed.selection_table_["reason"].tolist()
    )
    assert_frame_equal(selector_base.correlation_matrix_, selector_changed.correlation_matrix_)
    assert not selector_base.stability_table_.equals(selector_changed.stability_table_)


def test_psi_csi_formula_bandas_golden_y_accion_exclude() -> None:
    selector = FeatureSelector(
        min_iv=0.0,
        correlation_enabled=False,
        vif_enabled=False,
        stability_smoothing=1e-12,
    ).fit(
        _stability_frame(),
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"a": 0.20, "b": 0.10}),
        woe_column_map={"a": "a__woe", "b": "b__woe"},
    )
    stability = selector.stability_table_.set_index("feature")

    assert stability.loc["a", "csi"] == pytest.approx(0.27465307216702745)
    assert stability.loc["a", "csi_band"] == "redevelop"
    assert stability.loc["b", "csi"] == pytest.approx(0.0)
    assert stability.loc["b", "csi_band"] == "stable"

    excluded = FeatureSelector(
        min_iv=0.0,
        correlation_enabled=False,
        vif_enabled=False,
        stability_action="exclude",
        stability_smoothing=1e-12,
    ).fit(
        _stability_frame(),
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"a": 0.20, "b": 0.10}),
        woe_column_map={"a": "a__woe", "b": "b__woe"},
    )
    assert excluded.selection_table_.set_index("feature").loc["a", "reason"] == "high_stability"
    assert excluded.selected_features_ == ("b",)


def test_n_dev_menor_o_igual_p_mas_uno_falla_en_vif() -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 0, 1, 1],
            "partition": ["desarrollo"] * 4,
            "x1__woe": [0.0, 1.0, 2.0, 3.0],
            "x2__woe": [1.0, 0.0, 3.0, 2.0],
            "x3__woe": [0.0, 1.0, 0.0, 1.0],
        }
    )
    with pytest.raises(SelectionFitError, match="n_dev=4, p=3"):
        FeatureSelector(min_iv=0.0, correlation_threshold=1.0).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=_summary({"x1": 0.2, "x2": 0.15, "x3": 0.1}),
            woe_column_map={"x1": "x1__woe", "x2": "x2__woe", "x3": "x3__woe"},
        )


def test_reordenar_filas_y_columnas_no_cambia_seleccion() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    selector_base = FeatureSelector(
        min_iv=0.0,
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )
    reordered = frame.loc[[5, 2, 7, 0, 3, 1, 6, 4, 8, 9, 10, 11], :]
    reordered = reordered.loc[:, ["x3__woe", "partition", "x1__woe", "target", "x2__woe"]]
    selector_reordered = FeatureSelector(
        min_iv=0.0,
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        reordered,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )

    assert selector_base.selected_features_ == selector_reordered.selected_features_
    assert (
        selector_base.selection_table_["reason"].tolist()
        == selector_reordered.selection_table_["reason"].tolist()
    )


def test_filtros_hard_y_ramas_diagnosticas() -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 0, 1, 1],
            "partition": ["desarrollo"] * 4,
            "score__woe": [-0.4, -0.1, -0.2, -0.5],
        }
    )
    for kwargs, reason in (
        ({"min_iv": 0.70}, "low_iv"),
        ({"min_auc": 0.80}, "low_auc"),
        ({"min_ks": 0.60}, "low_ks"),
        ({"min_gini": 0.60}, "low_gini"),
        ({"max_iv": 0.50, "max_iv_action": "exclude"}, "high_iv"),
    ):
        selector = FeatureSelector(
            min_iv=kwargs.pop("min_iv", 0.0),
            vif_enabled=False,
            stability_enabled=False,
            fail_if_no_features=False,
            **kwargs,
        ).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=_summary({"score": 0.60}),
            woe_column_map={"score": "score__woe"},
        )
        assert selector.selection_table_.iloc[0]["reason"] == reason
        assert selector.selected_features_ == ()

    flagged = FeatureSelector(
        min_iv=0.0,
        max_iv=0.50,
        max_iv_action="flag",
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"score": 0.60}),
        woe_column_map={"score": "score__woe"},
    )
    assert flagged.selection_table_.iloc[0]["reason"] == "high_iv"
    assert flagged.selected_features_ == ("score",)


def test_detail_de_seleccion_va_con_seis_significativos() -> None:
    """El ``detail`` se lee en el informe: seis significativos, no la mantisa cruda del float.

    El anexo publicaba ``iv=0.650693017601 >= max_iv=0.5``, doce dígitos de una precisión que el
    IV no tiene. Se corta con ``.6g`` y no con ``.6f`` a propósito: el segundo caso comprueba que
    una cifra diminuta conserva su magnitud en vez de aplanarse a ``0.000000``, que es la lectura
    contraria a la verdad (un IV que no es cero pareciendo cero).
    """
    frame = pd.DataFrame(
        {
            "target": [0, 0, 1, 1],
            "partition": ["desarrollo"] * 4,
            "score__woe": [-0.4, -0.1, -0.2, -0.5],
        }
    )

    def _detail(iv: float) -> str:
        selector = FeatureSelector(
            min_iv=0.70,
            vif_enabled=False,
            stability_enabled=False,
            fail_if_no_features=False,
        ).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=_summary({"score": iv}),
            woe_column_map={"score": "score__woe"},
        )
        return cast("str", selector.selection_table_.iloc[0]["detail"])

    assert _detail(0.650693017601234) == "iv=0.650693 < min_iv=0.7"
    assert _detail(0.00000123456789) == "iv=1.23457e-06 < min_iv=0.7"


def test_constante_no_finita_metricas_desactivadas_y_empty_selection_allowed() -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 0, 1, 1],
            "partition": ["desarrollo"] * 4,
            "constante__woe": [1.0, 1.0, 1.0, 1.0],
            "no_finita__woe": [0.0, math.inf, 1.0, 2.0],
        }
    )
    selector = FeatureSelector(
        min_iv=0.0,
        compute_univariate_metrics=False,
        correlation_enabled=True,
        vif_enabled=False,
        stability_enabled=False,
        fail_if_no_features=False,
    )
    transformed = selector.fit_transform(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"constante": 0.20, "no_finita": 0.20}),
        woe_column_map={
            "constante": "constante__woe",
            "no_finita": "no_finita__woe",
        },
    )
    table = selector.selection_table_.set_index("feature")

    assert table.loc["constante", "reason"] == "constant_or_nonfinite"
    assert table.loc["no_finita", "reason"] == "constant_or_nonfinite"
    assert table["auc"].isna().all()
    assert selector.selected_features_ == ()
    assert transformed.columns.tolist() == ["target", "partition"]

    selector_metricas = FeatureSelector(
        min_iv=0.0,
        correlation_enabled=True,
        vif_enabled=False,
        stability_enabled=False,
        fail_if_no_features=False,
    ).fit_transform(
        frame[["target", "partition", "no_finita__woe"]],
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"no_finita": 0.20}),
        woe_column_map={"no_finita": "no_finita__woe"},
    )
    assert selector_metricas.columns.tolist() == ["target", "partition"]

    with pytest.raises(SelectionFitError, match="No quedó ninguna variable"):
        FeatureSelector(
            min_iv=0.0,
            correlation_enabled=True,
            vif_enabled=False,
            stability_enabled=False,
        ).fit(
            frame[["target", "partition", "constante__woe"]],
            target_col="target",
            partition_col="partition",
            binning_summary=_summary({"constante": 0.20}),
            woe_column_map={"constante": "constante__woe"},
        )

    with pytest.raises(SelectionFitError, match="force_include"):
        FeatureSelector(
            min_iv=0.0,
            force_include=("constante",),
            vif_enabled=False,
            stability_enabled=False,
        ).fit(
            frame[["target", "partition", "constante__woe"]],
            target_col="target",
            partition_col="partition",
            binning_summary=_summary({"constante": 0.20}),
            woe_column_map={"constante": "constante__woe"},
        )


def test_clustering_connected_components_y_priority_order_duplicado() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    selector = FeatureSelector(
        min_iv=0.0,
        priority_order=("iv", "iv", "name"),
        clustering_method="connected_components",
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )

    assert selector.selected_features_ == ("x2", "x3")
    assert selector.selection_table_.set_index("feature").loc["x1", "reason"] == (
        "cluster_representative_lost"
    )


def test_smoke_camino_completo_con_sklearn_y_statsmodels_reales() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    selector = FeatureSelector(min_iv=0.0, correlation_threshold=1.0).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )

    assert selector.result_.selected_features == ("x2", "x3")
    assert selector.result_.selected_woe_frame.columns.tolist() == [
        "target",
        "partition",
        "x2__woe",
        "x3__woe",
    ]
    assert len(selector.decisions_) == 3


def test_vif_una_variable_e_intercepto_desactivado() -> None:
    selector = FeatureSelector(
        min_iv=0.0,
        correlation_enabled=False,
        stability_enabled=False,
        vif_add_intercept=False,
    ).fit(
        _metric_frame(),
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"score": 0.12}),
        woe_column_map={"score": "score__woe"},
    )

    assert selector.vif_table_.iloc[0]["vif"] == pytest.approx(1.0)


def test_vif_eliminacion_deja_una_variable_y_max_iterations() -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 0, 0, 1, 1, 1],
            "partition": ["desarrollo"] * 6,
            "x1__woe": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            "x2__woe": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    selector = FeatureSelector(
        min_iv=0.0,
        correlation_threshold=1.0,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=_summary({"x1": 0.20, "x2": 0.30}),
        woe_column_map={"x1": "x1__woe", "x2": "x2__woe"},
    )
    assert selector.selected_features_ == ("x2",)
    assert selector.vif_table_.loc[selector.vif_table_["removed"], "feature"].tolist() == ["x1"]

    frame3, summary3, woe_map3 = _canonical_frame_summary_map()
    limited = FeatureSelector(
        min_iv=0.0,
        correlation_threshold=1.0,
        stability_enabled=False,
        vif_max_iterations=1,
    ).fit(
        frame3,
        target_col="target",
        partition_col="partition",
        binning_summary=summary3,
        woe_column_map=woe_map3,
    )
    assert limited.vif_table_["iteration"].max() == 0


def test_vif_sin_intercepto_en_camino_multivariable() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    selector = FeatureSelector(
        min_iv=0.0,
        correlation_threshold=1.0,
        stability_enabled=False,
        vif_add_intercept=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )
    assert selector.selected_features_ == ("x2", "x3")


def test_errores_defensivos_de_contrato_de_entrada() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    duplicate_columns = pd.DataFrame(
        [[0, "desarrollo", 1.0, 2.0]],
        columns=["target", "partition", "x__woe", "x__woe"],
    )

    with pytest.raises(ConfigError, match="Hiperparámetros inválidos"):
        FeatureSelector(correlation_threshold=2.0).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match=r"pandas\.DataFrame"):
        FeatureSelector().fit(
            [],
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="duplicadas"):
        FeatureSelector().fit(
            duplicate_columns,
            target_col="target",
            partition_col="partition",
            binning_summary=_summary({"x": 0.2}),
            woe_column_map={"x": "x__woe"},
        )
    with pytest.raises(SelectionFitError, match="Faltan columnas"):
        FeatureSelector().fit(
            frame.drop(columns=["target"]),
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="binning_summary debe contener"):
        FeatureSelector().fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=pd.DataFrame({"feature": ["x1"], "iv": [0.2]}),
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="duplicadas"):
        FeatureSelector().fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=pd.DataFrame(
                {"name": ["x1", "x1"], "selected": [True, True], "iv": [0.2, 0.3]}
            ),
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="No hay variables candidatas"):
        FeatureSelector(feature_columns=("x1",), exclude_columns=("x1",)).fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="inexistente"):
        FeatureSelector().fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map={"x1": "missing__woe"},
        )


def test_errores_de_desarrollo_target_iv_y_reverse_mapping() -> None:
    frame, summary, woe_map = _canonical_frame_summary_map()
    empty_dev = frame.assign(partition=["holdout"] * len(frame))
    invalid_target = frame.copy(deep=True)
    invalid_target.loc[0, "target"] = 2
    degenerate_target = frame.copy(deep=True)
    degenerate_target.loc[degenerate_target["partition"].eq("desarrollo"), "target"] = 1

    with pytest.raises(SelectionFitError, match="Desarrollo no contiene"):
        FeatureSelector().fit(
            empty_dev,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="valores inválidos"):
        FeatureSelector().fit(
            invalid_target,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="Target degenerado"):
        FeatureSelector().fit(
            degenerate_target,
            target_col="target",
            partition_col="partition",
            binning_summary=summary,
            woe_column_map=woe_map,
        )
    with pytest.raises(SelectionFitError, match="iv inválido"):
        FeatureSelector().fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=pd.DataFrame({"name": ["x1"], "selected": [True], "iv": ["malo"]}),
            woe_column_map={"x1": "x1__woe"},
        )
    with pytest.raises(SelectionFitError, match="finito y no negativo"):
        FeatureSelector().fit(
            frame,
            target_col="target",
            partition_col="partition",
            binning_summary=pd.DataFrame({"name": ["x1"], "selected": [True], "iv": [-0.1]}),
            woe_column_map={"x1": "x1__woe"},
        )

    selector = FeatureSelector(
        feature_columns=("x1__woe", "x3"),
        exclude_columns=("x3__woe",),
        force_include=("x2__woe",),
        min_iv=0.0,
        correlation_threshold=1.0,
        vif_enabled=False,
        stability_enabled=False,
    ).fit(
        frame,
        target_col="target",
        partition_col="partition",
        binning_summary=summary,
        woe_column_map=woe_map,
    )
    assert selector.candidate_features_ == ("x1", "x2")


def test_helpers_de_auditoria_y_normalizacion() -> None:
    state = selector_module.CandidateState(feature="x", woe_column="x__woe", iv=0.2)
    values_by_reason = {
        "low_auc": 0.7,
        "low_ks": 0.3,
        "low_gini": 0.4,
        "high_correlation": 0.9,
        "high_vif": 9.0,
        "high_stability": 0.3,
        "constant_or_nonfinite": "detalle",
    }
    for reason, value in values_by_reason.items():
        state.reason = reason
        state.auc = 0.7
        state.ks = 0.3
        state.gini = 0.4
        state.max_abs_corr = 0.9
        state.vif = 9.0
        state.max_csi = 0.3
        state.detail = "detalle"
        assert selector_module._audit_value(state) == value

    assert selector_module._csi_band(0.20, stable_threshold=0.10, review_threshold=0.25) == "review"
    assert (
        selector_module._psi(
            pd.Series(dtype="float64"),
            pd.Series(dtype="float64"),
            smoothing=1e-6,
        )
        == 0.0
    )
    assert math.isnan(selector_module._normalize_float(math.nan))


def test_helpers_internos_de_ranking_correlacion_y_stability_forzada() -> None:
    pd_module = selector_module._import_pandas()
    states = {
        "a": selector_module.CandidateState(feature="a", woe_column="a__woe", iv=0.2),
        "b": selector_module.CandidateState(feature="b", woe_column="b__woe", iv=0.1),
    }
    states["a"].included = False
    matrix = pd.DataFrame(
        [[1.0, math.nan], [math.nan, 1.0]],
        index=["a__woe", "b__woe"],
        columns=["a__woe", "b__woe"],
    )

    assert selector_module._canonical_priorities(("iv",))[-1] == "name"
    assert selector_module._priority_metric(states["a"], "auc") == -math.inf
    assert selector_module._abs_corr("a", "b", states, matrix) is None
    assert selector_module._abs_corr("a", "b", states, pd.DataFrame()) is None

    selector_module._apply_correlation_pruning(
        states,
        ("a", "b"),
        pd.DataFrame(
            [[1.0, 0.9], [0.9, 1.0]],
            index=["a__woe", "b__woe"],
            columns=["a__woe", "b__woe"],
        ),
        threshold=0.75,
    )
    assert states["b"].included is True

    component_states = {
        name: selector_module.CandidateState(feature=name, woe_column=f"{name}__woe", iv=0.2)
        for name in ("a", "b", "c")
    }
    component_matrix = pd.DataFrame(
        [[1.0, 0.9, 0.9], [0.9, 1.0, 0.9], [0.9, 0.9, 1.0]],
        index=["a__woe", "b__woe", "c__woe"],
        columns=["a__woe", "b__woe", "c__woe"],
    )
    selector_module._apply_correlation_components(
        component_states,
        ("a", "b", "c"),
        component_matrix,
        threshold=0.75,
    )
    assert component_states["b"].reason == "cluster_representative_lost"

    selector_module._validate_forced_finite(
        {"a": states["a"]},
        pd.DataFrame({"a__woe": [0.0]}),
        ("fantasma",),
        (),
        np=selector_module._import_numpy(),
    )

    forced = selector_module.CandidateState(
        feature="a",
        woe_column="a__woe",
        iv=0.2,
        forced="include",
    )
    selector_module._apply_stability_action(
        {"a": forced},
        pd_module.DataFrame({"feature": ["a"], "csi": [0.30]}),
        action="exclude",
        review_threshold=0.25,
    )
    assert forced.included is True


def _metric_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "target": [0, 0, 1, 1],
            "partition": ["desarrollo"] * 4,
            "score__woe": [-0.4, -0.1, -0.2, -0.5],
        }
    )


def _canonical_frame_summary_map() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    frame = pd.DataFrame(
        {
            "target": [0, 0, 0, 0, 1, 1, 1, 1, 0, 1, 0, 1],
            "partition": ["desarrollo"] * 8 + ["holdout"] * 4,
            "x1__woe": [1.0, 1.0, 0.5, 0.5, -0.5, -0.5, -1.0, -1.0, 1.0, 0.5, -0.5, -1.0],
            "x2__woe": [2.0, 2.0, 1.0, 1.0, -1.0, -1.0, -2.0, -2.0, 2.0, 1.0, -1.0, -2.0],
            "x3__woe": [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, -1.0],
        }
    )
    summary = _summary({"x1": 0.20, "x2": 0.40, "x3": 0.15})
    woe_map = {"x1": "x1__woe", "x2": "x2__woe", "x3": "x3__woe"}
    return frame, summary, woe_map


def _stability_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "target": [0, 0, 1, 1, 0, 1, 0, 1],
            "partition": ["desarrollo"] * 4 + ["holdout"] * 4,
            "a__woe": [0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0],
            "b__woe": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
        }
    )


def _summary(iv_by_feature: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": list(iv_by_feature),
            "selected": [True] * len(iv_by_feature),
            "iv": list(iv_by_feature.values()),
        }
    )
