"""Tests de ``LogisticPDModel``: logística PD, stepwise, guards e import liviano."""

from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import textwrap
import warnings
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from sklearn.base import clone

import nikodym.model.estimator as estimator_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, MissingDependencyError, NotFittedError
from nikodym.model.config import (
    IvContributionConfig,
    ModelConfig,
    SignPolicyConfig,
    StepwiseConfig,
)
from nikodym.model.estimator import LogisticPDModel
from nikodym.model.exceptions import ModelFitError, ModelTransformError


def test_import_model_liviano_no_carga_estimator_ni_deps_pesadas() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.model

        blocked = [
            name for name in (
                "nikodym.model.estimator",
                "statsmodels",
                "sklearn",
                "scipy",
                "pandas",
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


def test_reexport_logistic_model_sin_sklearn_falla_con_missing_dependency() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.model
        from nikodym.core.exceptions import MissingDependencyError


        class BlockSklearn:
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "sklearn" or fullname.startswith("sklearn."):
                    raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
                return None


        sys.meta_path.insert(0, BlockSklearn())
        try:
            nikodym.model.LogisticPDModel
        except MissingDependencyError as exc:
            assert "instale nikodym[scoring]" in str(exc)
        else:
            raise AssertionError("LogisticPDModel no tradujo la ausencia de sklearn")
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


def test_import_estimator_sin_sklearn_cubre_rama_top_level(
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

    module_path = estimator_module.__file__
    assert module_path is not None
    spec = importlib.util.spec_from_file_location(
        "nikodym.model._missing_sklearn_estimator_test",
        module_path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        loader.exec_module(module)


def test_imports_perezosos_traducen_dependencias(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = estimator_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(estimator_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        estimator_module._import_pandas()

    def block_numpy(name: str) -> Any:
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name)

    monkeypatch.setattr(estimator_module.importlib, "import_module", block_numpy)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        estimator_module._import_numpy()

    def block_statsmodels(name: str) -> Any:
        if name == "statsmodels.discrete.discrete_model":
            raise ModuleNotFoundError("No module named 'statsmodels'", name="statsmodels")
        return real_import(name)

    monkeypatch.setattr(estimator_module.importlib, "import_module", block_statsmodels)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        estimator_module._import_statsmodels_components()

    def block_scipy_stats(name: str) -> Any:
        if name == "scipy.stats":
            raise ModuleNotFoundError("No module named 'scipy'", name="scipy")
        return real_import(name)

    monkeypatch.setattr(estimator_module.importlib, "import_module", block_scipy_stats)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        estimator_module._import_scipy_chi2_sf()

    def block_scipy_special(name: str) -> Any:
        if name == "scipy.special":
            raise ModuleNotFoundError("No module named 'scipy'", name="scipy")
        return real_import(name)

    monkeypatch.setattr(estimator_module.importlib, "import_module", block_scipy_special)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        estimator_module._import_scipy_expit()

    def block_dependency_versions(name: str) -> Any:
        if name == "statsmodels":
            raise ModuleNotFoundError("No module named 'statsmodels'", name="statsmodels")
        return real_import(name)

    monkeypatch.setattr(estimator_module.importlib, "import_module", block_dependency_versions)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        estimator_module._dependency_versions()


def test_from_config_clone_safe_set_params_y_not_fitted() -> None:
    cfg = ModelConfig(
        engine="glm_binomial",
        stepwise=StepwiseConfig(direction="forward", entry_p_value=0.02, min_features=1),
        sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
        iv_contribution=IvContributionConfig(threshold=1.0, action="flag"),
        force_include=("saldo",),
        fail_if_no_features=False,
    )

    model = LogisticPDModel.from_config(cfg)
    model_from_dict = LogisticPDModel.from_config(cfg.model_dump())
    cloned = clone(model)

    assert cloned.get_params()["engine"] == "glm_binomial"
    assert cloned.get_params()["entry_p_value"] == 0.02
    assert cloned.get_params()["force_include"] == ("saldo",)
    assert model_from_dict.get_params()["sign_policy"] == "flag"
    assert cloned.set_params(entry_p_value=0.03).get_params()["entry_p_value"] == 0.03

    with pytest.raises(NotFittedError, match="no está fiteado"):
        model.predict_pd(pd.DataFrame({"saldo__woe": [0.1]}))


def test_intercept_only_golden_manual() -> None:
    y = pd.Series([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], name="target")
    frame = pd.DataFrame(
        {"partition": ["desarrollo"] * len(y)},
        index=[f"c{i}" for i in range(len(y))],
    )
    y.index = frame.index

    model = LogisticPDModel(stepwise_direction="none").fit(
        frame,
        y,
        feature_names=(),
        woe_columns=(),
        iv_by_feature={},
    )

    expected_beta0 = math.log(3 / 7)
    expected_ll = 3 * math.log(0.3) + 7 * math.log(0.7)
    assert model.feature_names_in_ == ()
    assert model.final_features_ == ()
    assert model.coef_.shape == (1, 0)
    assert model.params_.to_dict() == pytest.approx({"const": expected_beta0})
    assert model.fit_statistics_.log_likelihood == pytest.approx(expected_ll)
    assert model.fit_statistics_.pseudo_r2_mcfadden == pytest.approx(0.0, abs=1e-8)

    proba = model.predict_proba(pd.DataFrame(index=frame.index))
    assert proba.shape == (10, 2)
    assert proba[:, 1].tolist() == pytest.approx([0.3] * 10)
    assert proba.sum(axis=1).tolist() == pytest.approx([1.0] * 10)


def test_logit_dos_variables_goldens_statsmodels_0146() -> None:
    frame, y = _two_feature_frame_target()
    model = LogisticPDModel(
        stepwise_direction="none",
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )

    assert model.params_.to_dict() == pytest.approx(
        {
            "const": -0.4214526621732901,
            "mora__woe": -1.733079848642081,
            "saldo__woe": -0.08930464404097496,
        }
    )
    assert model.bse_.to_dict() == pytest.approx(
        {
            "const": 0.7530219589521716,
            "mora__woe": 1.9655919036810643,
            "saldo__woe": 1.720898495099895,
        }
    )
    assert model.pvalues_.to_dict() == pytest.approx(
        {
            "const": 0.5756965196390356,
            "mora__woe": 0.3779342541852838,
            "saldo__woe": 0.9586129988561938,
        }
    )
    assert model.fit_statistics_.log_likelihood == pytest.approx(-8.2192982977839)
    assert model.fit_statistics_.null_log_likelihood == pytest.approx(-13.460233342014428)
    assert model.fit_statistics_.pseudo_r2_mcfadden == pytest.approx(0.38936435283566795)
    assert model.fit_statistics_.llr == pytest.approx(10.481870088461054)
    assert model.fit_statistics_.llr_p_value == pytest.approx(0.005295303177601422)
    assert model.final_features_ == ("mora", "saldo")
    assert model.dependency_versions_["statsmodels"] == "0.14.6"


def test_glm_binomial_mcfadden_usa_llf_llnull_explicito() -> None:
    frame = pd.DataFrame({"x__woe": [-2, -1, -0.5, 0.5, 1, 2, -1.5, 1.5, -0.2, 0.2, -1.2, 1.2]})
    y = pd.Series([1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1])

    model = LogisticPDModel(
        engine="glm_binomial",
        stepwise_direction="none",
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("x",),
        woe_columns=("x__woe",),
        iv_by_feature={"x": 0.1},
    )

    expected_r2 = 1 - (
        model.fit_statistics_.log_likelihood / model.fit_statistics_.null_log_likelihood
    )
    assert model.fit_statistics_.pseudo_r2_mcfadden == pytest.approx(expected_r2)
    assert model.fit_statistics_.optimizer == "irls"
    assert model.params_.to_dict() == pytest.approx(
        {"const": 1.6653345369377348e-16, "x__woe": -0.4925841048941102}
    )


def test_lr_test_golden_con_scipy_chi2_sf() -> None:
    frame, y = _two_feature_frame_target()
    full = LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag").fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )
    reduced = LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag").fit(
        frame,
        y,
        feature_names=("saldo",),
        woe_columns=("saldo__woe",),
        iv_by_feature={"saldo": 0.12},
    )

    lr_stat, lr_p = estimator_module._lr_values(
        llf_full=full.fit_statistics_.log_likelihood,
        llf_red=reduced.fit_statistics_.log_likelihood,
        df=1,
    )

    assert reduced.fit_statistics_.log_likelihood == pytest.approx(-8.630414800281029)
    assert lr_stat == pytest.approx(0.8222330049942563)
    assert lr_p == pytest.approx(0.36452809561449884)


def test_stepwise_determinista_independiente_del_orden_de_columnas() -> None:
    frame, y = _stepwise_frame_target()
    iv = {"informativa": 0.2, "ruido": 0.01, "redundante": 0.18}

    first = LogisticPDModel(iv_contribution_policy="flag").fit(
        frame.loc[:, ["informativa__woe", "ruido__woe", "redundante__woe"]],
        y,
        feature_names=("informativa", "ruido", "redundante"),
        woe_columns=("informativa__woe", "ruido__woe", "redundante__woe"),
        iv_by_feature=iv,
    )
    second = LogisticPDModel(iv_contribution_policy="flag").fit(
        frame.loc[:, ["ruido__woe", "redundante__woe", "informativa__woe"]],
        y,
        feature_names=("ruido", "redundante", "informativa"),
        woe_columns=("ruido__woe", "redundante__woe", "informativa__woe"),
        iv_by_feature=iv,
    )

    assert first.final_features_ == ("informativa",)
    assert second.final_features_ == first.final_features_
    assert [decision.model_dump() for decision in second.stepwise_trace_] == [
        decision.model_dump() for decision in first.stepwise_trace_
    ]


def test_signo_invertido_exclude_remueve_y_forzado_falla() -> None:
    frame, y = _sign_frame_target()
    iv = {"protectora": 0.1, "invertida": 0.1}

    model = LogisticPDModel(
        stepwise_direction="none",
        sign_policy="exclude",
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("protectora", "invertida"),
        woe_columns=("protectora__woe", "invertida__woe"),
        iv_by_feature=iv,
    )

    assert model.final_features_ == ("protectora",)
    assert model.stepwise_trace_[0].feature == "invertida"
    assert model.stepwise_trace_[0].action == "exclude"
    assert model.stepwise_trace_[0].criterion == "sign"

    with pytest.raises(ModelFitError, match=r"force_include.*signo contrario"):
        LogisticPDModel(
            stepwise_direction="none",
            force_include=("invertida",),
            iv_contribution_policy="flag",
        ).fit(
            frame,
            y,
            feature_names=("protectora", "invertida"),
            woe_columns=("protectora__woe", "invertida__woe"),
            iv_by_feature=iv,
        )


def test_iv_contribution_consume_iv_externo_y_acciones_exclude_fail() -> None:
    frame, y = _iv_frame_target()
    iv = {"dominante": 0.95, "secundaria": 0.03, "tercera": 0.02}

    model = LogisticPDModel(
        stepwise_direction="none",
        sign_policy="flag",
        iv_contribution_policy="exclude",
    ).fit(
        frame,
        y,
        feature_names=("dominante", "secundaria", "tercera"),
        woe_columns=("dominante__woe", "secundaria__woe", "tercera__woe"),
        iv_by_feature=iv,
    )

    assert model.final_features_ == ("secundaria", "tercera")
    assert model.iv_contribution_.to_dict("records") == [
        {
            "feature": "secundaria",
            "woe_column": "secundaria__woe",
            "iv": 0.03,
            "iv_contribution": 0.6,
        },
        {
            "feature": "tercera",
            "woe_column": "tercera__woe",
            "iv": 0.02,
            "iv_contribution": pytest.approx(0.4),
        },
    ]
    assert any(
        decision.feature == "dominante"
        and decision.criterion == "iv_contribution"
        and decision.action == "exclude"
        for decision in model.stepwise_trace_
    )

    flagged = LogisticPDModel(
        stepwise_direction="none",
        sign_policy="flag",
        iv_contribution_policy="flag",
    ).fit(
        frame.assign(dominante__woe=frame["dominante__woe"] * 0.01),
        y,
        feature_names=("dominante", "secundaria", "tercera"),
        woe_columns=("dominante__woe", "secundaria__woe", "tercera__woe"),
        iv_by_feature=iv,
    )
    assert flagged.iv_contribution_.set_index("feature").loc["dominante", "iv"] == 0.95
    assert flagged.iv_contribution_.set_index("feature").loc[
        "dominante", "iv_contribution"
    ] == pytest.approx(0.95)

    with pytest.raises(ModelFitError, match="IV-contribution supera"):
        LogisticPDModel(
            stepwise_direction="none",
            sign_policy="flag",
            iv_contribution_policy="fail",
        ).fit(
            frame,
            y,
            feature_names=("dominante", "secundaria", "tercera"),
            woe_columns=("dominante__woe", "secundaria__woe", "tercera__woe"),
            iv_by_feature=iv,
        )


def test_perfect_separation_y_no_convergencia_son_model_fit_error() -> None:
    separated_frame = pd.DataFrame({"x__woe": [-3, -2, -1, 1, 2, 3]})
    separated_y = pd.Series([1, 1, 1, 0, 0, 0])
    with pytest.raises(ModelFitError, match="separación perfecta"):
        LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag").fit(
            separated_frame,
            separated_y,
            feature_names=("x",),
            woe_columns=("x__woe",),
            iv_by_feature={"x": 0.1},
        )

    frame, y = _two_feature_frame_target()
    with pytest.raises(ModelFitError, match="converg"):
        LogisticPDModel(
            stepwise_direction="none",
            iv_contribution_policy="flag",
            fit_maxiter=1,
        ).fit(
            frame,
            y,
            feature_names=("saldo", "mora"),
            woe_columns=("saldo__woe", "mora__woe"),
            iv_by_feature={"saldo": 0.12, "mora": 0.08},
        )


def test_warning_ajeno_no_se_silencia() -> None:
    _, _, _, perfect_warning, convergence_warning, _ = (
        estimator_module._import_statsmodels_components()
    )

    with (
        pytest.raises(
            UserWarning,
            match="warning ajeno",
        ),
        estimator_module._statsmodels_warnings_as_errors(
            perfect_warning,
            convergence_warning,
        ),
    ):
        warnings.warn("warning ajeno", UserWarning, stacklevel=1)


def test_predict_proba_predict_pd_y_missing_columns_preservan_contrato() -> None:
    frame, y = _two_feature_frame_target()
    frame = frame.copy()
    frame.index = [f"id-{i:02d}" for i in range(len(frame))]
    y.index = frame.index
    model = LogisticPDModel(
        stepwise_direction="none",
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )

    scored = frame.assign(raw_saldo=range(len(frame)))
    proba = model.predict_proba(scored)
    pd_raw = model.predict_pd(scored)
    linear = model.decision_function(scored)

    assert proba.shape == (len(frame), 2)
    assert (proba >= 0.0).all()
    assert (proba <= 1.0).all()
    assert proba.sum(axis=1).tolist() == pytest.approx([1.0] * len(frame))
    assert pd_raw.index.tolist() == frame.index.tolist()
    assert linear.index.tolist() == frame.index.tolist()
    assert pd_raw.iloc[:3].tolist() == pytest.approx(
        [0.9134713467914698, 0.8582865049488898, 0.7780632242966812]
    )

    with pytest.raises(ModelTransformError, match=r"requeridas=.*faltantes=.*mora__woe"):
        model.predict_pd(scored.drop(columns=["mora__woe"]))
    nonfinite = scored.copy()
    nonfinite.loc[nonfinite.index[0], "mora__woe"] = math.inf
    with pytest.raises(ModelTransformError, match=r"WoE no finitas|WoE no finita"):
        model.predict_pd(nonfinite)


def test_validaciones_de_entrada_y_no_mutacion() -> None:
    frame, y = _two_feature_frame_target()
    original = frame.copy(deep=True)
    model = LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag")
    model.fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )
    assert_frame_equal(frame, original)

    with pytest.raises(ModelFitError, match="mismo largo"):
        LogisticPDModel().fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe", "mora__woe"),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="Faltan columnas WoE"):
        LogisticPDModel().fit(
            frame.drop(columns=["mora__woe"]),
            y,
            feature_names=("saldo", "mora"),
            woe_columns=("saldo__woe", "mora__woe"),
            iv_by_feature={"saldo": 0.12, "mora": 0.08},
        )
    with pytest.raises(ModelFitError, match="ambas clases"):
        LogisticPDModel().fit(
            frame,
            pd.Series([1] * len(frame)),
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="sample_weight"):
        LogisticPDModel(stepwise_direction="none").fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
            sample_weight=pd.Series([1.0] * len(frame)),
        )


def test_validaciones_adicionales_de_fit_y_config() -> None:
    frame, y = _two_feature_frame_target()
    numpy = estimator_module._import_numpy()
    candidates = estimator_module._candidate_specs(
        frame=frame,
        feature_names=("saldo",),
        woe_columns=("saldo__woe",),
        iv_by_feature={"saldo": 0.12},
        np=numpy,
    )

    with pytest.raises(ConfigError, match="Hiperparámetros inválidos"):
        LogisticPDModel(entry_p_value=2.0).fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match=r"pandas.DataFrame"):
        LogisticPDModel().fit(
            cast(Any, "no dataframe"),
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelTransformError, match=r"pandas.DataFrame"):
        (
            LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag")
            .fit(
                frame,
                y,
                feature_names=("saldo",),
                woe_columns=("saldo__woe",),
                iv_by_feature={"saldo": 0.12},
            )
            .predict_pd(cast(Any, "no dataframe"))
        )
    with pytest.raises(ModelFitError, match="DataFrame vacío"):
        LogisticPDModel().fit(
            frame.iloc[:0],
            y.iloc[:0],
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="misma cantidad"):
        LogisticPDModel().fit(
            frame,
            y.iloc[:-1],
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="sample_weight debe"):
        LogisticPDModel(engine="glm_binomial").fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
            sample_weight=pd.Series([1.0]),
        )

    duplicated = pd.DataFrame(
        [[1.0, 2.0], [0.5, 0.4], [-0.2, -0.1], [-0.5, -0.4]],
        columns=["saldo__woe", "saldo__woe"],
    )
    with pytest.raises(ModelFitError, match="duplicadas"):
        LogisticPDModel().fit(
            duplicated,
            pd.Series([1, 0, 1, 0]),
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="feature_names contiene duplicados"):
        LogisticPDModel().fit(
            frame,
            y,
            feature_names=("saldo", "saldo"),
            woe_columns=("saldo__woe", "mora__woe"),
            iv_by_feature={"saldo": 0.12, "mora": 0.08},
        )
    with pytest.raises(ModelFitError, match="woe_columns contiene duplicados"):
        LogisticPDModel().fit(
            frame,
            y,
            feature_names=("saldo", "mora"),
            woe_columns=("saldo__woe", "saldo__woe"),
            iv_by_feature={"saldo": 0.12, "mora": 0.08},
        )
    with pytest.raises(ModelFitError, match="no contiene el IV"):
        LogisticPDModel().fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={},
        )
    with pytest.raises(ModelFitError, match="IV inválido"):
        LogisticPDModel().fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": "no numerico"},
        )
    with pytest.raises(ModelFitError, match="IV debe ser finito"):
        LogisticPDModel().fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": math.inf},
        )
    with pytest.raises(ConfigError, match="se contradicen"):
        estimator_module._validate_force_overrides(
            LogisticPDModel(force_include=("saldo",), force_exclude=("saldo",)),
            candidates,
        )
    with pytest.raises(ModelFitError, match=r"overrides.*faltantes"):
        LogisticPDModel(force_include=("ausente",)).fit(
            frame,
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="Desarrollo"):
        LogisticPDModel().fit(
            frame.assign(partition="holdout"),
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="valores inválidos"):
        invalid_target = y.copy(deep=True)
        invalid_target.iloc[0] = 2
        LogisticPDModel().fit(
            frame,
            invalid_target,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )
    with pytest.raises(ModelFitError, match="WoE no finita"):
        LogisticPDModel().fit(
            frame.assign(saldo__woe=math.inf),
            y,
            feature_names=("saldo",),
            woe_columns=("saldo__woe",),
            iv_by_feature={"saldo": 0.12},
        )

    shuffled_y = y.copy(deep=True).iloc[::-1]
    shuffled_weights = pd.Series([1.0] * len(frame), index=frame.index[::-1])
    glm = LogisticPDModel(
        engine="glm_binomial",
        stepwise_direction="none",
        iv_contribution_policy="flag",
    ).fit(
        frame,
        shuffled_y,
        feature_names=("saldo",),
        woe_columns=("saldo__woe",),
        iv_by_feature={"saldo": 0.12},
        sample_weight=shuffled_weights,
    )
    assert glm.fit_statistics_.optimizer == "irls"


def test_fit_filtra_desarrollo_sin_leakage_de_holdout() -> None:
    dev_frame, y = _two_feature_frame_target()
    frame = pd.concat(
        [dev_frame, dev_frame.assign(saldo__woe=999.0, mora__woe=-999.0)],
        ignore_index=True,
    )
    frame["partition"] = ["desarrollo"] * len(dev_frame) + ["holdout"] * len(dev_frame)
    target = pd.concat([y, 1 - y], ignore_index=True)

    clean = LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag").fit(
        dev_frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )
    leaked = LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag").fit(
        frame,
        target,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )

    assert_series_equal(leaked.params_, clean.params_)
    assert leaked.fit_statistics_ == clean.fit_statistics_


def test_auditoria_predict_y_no_intercept() -> None:
    frame, y = _stepwise_frame_target()
    audit = InMemoryAuditSink()
    model = LogisticPDModel(iv_contribution_policy="flag").fit(
        frame,
        y,
        feature_names=("informativa", "ruido", "redundante"),
        woe_columns=("informativa__woe", "ruido__woe", "redundante__woe"),
        iv_by_feature={"informativa": 0.2, "ruido": 0.01, "redundante": 0.18},
        audit=audit,
    )
    assert audit.events
    assert model.predict(frame).tolist()[:3] == [1, 1, 1]

    no_intercept = LogisticPDModel(
        fit_intercept=False,
        stepwise_direction="none",
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("informativa",),
        woe_columns=("informativa__woe",),
        iv_by_feature={"informativa": 0.2},
    )
    assert no_intercept.intercept_.tolist() == [0.0]
    assert "const" not in no_intercept.coefficient_table_["woe_column"].tolist()
    assert no_intercept.decision_function(frame).iloc[0] > 0.0


def test_predict_ramas_no_finitas(monkeypatch: pytest.MonkeyPatch) -> None:
    frame, y = _two_feature_frame_target()
    model = LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag").fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )

    model.coef_[0, 0] = math.inf
    with pytest.raises(ModelTransformError, match="predictor lineal"):
        model.decision_function(frame)
    model.coef_[0, 0] = -1.733079848642081

    monkeypatch.setattr(
        estimator_module,
        "_import_scipy_expit",
        lambda: lambda values: [math.inf for _ in values],
    )
    with pytest.raises(ModelTransformError, match="PD cruda"):
        model.predict_pd(frame)

    def fake_predict_pd(scoring_frame: pd.DataFrame) -> pd.Series:
        return pd.Series([math.inf] * len(scoring_frame), index=scoring_frame.index)

    monkeypatch.setattr(model, "predict_pd", fake_predict_pd)
    with pytest.raises(ModelTransformError, match="predict_proba"):
        model.predict_proba(frame)


def test_stepwise_backward_lr_both_y_guardas() -> None:
    frame, y = _two_feature_frame_target()
    backward = LogisticPDModel(
        stepwise_direction="backward",
        exit_p_value=0.5,
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )
    assert any(decision.action == "remove" for decision in backward.stepwise_trace_)

    backward_lr = LogisticPDModel(
        stepwise_direction="backward",
        stepwise_criterion="lr_test",
        exit_p_value=0.3,
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )
    assert any(decision.lr_stat is not None for decision in backward_lr.stepwise_trace_)

    forced = LogisticPDModel(
        stepwise_direction="backward",
        force_include=("saldo", "mora"),
        sign_policy="flag",
        iv_contribution_policy="flag",
        iv_contribution_threshold=1.0,
    ).fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )
    assert forced.final_features_ == ("mora", "saldo")

    with pytest.raises(ModelFitError, match="max_iter"):
        LogisticPDModel(max_iter=1, iv_contribution_policy="flag").fit(
            *_stepwise_frame_target(),
            feature_names=("informativa", "ruido", "redundante"),
            woe_columns=("informativa__woe", "ruido__woe", "redundante__woe"),
            iv_by_feature={"informativa": 0.2, "ruido": 0.01, "redundante": 0.18},
        )

    lr_forward = LogisticPDModel(
        stepwise_direction="forward",
        stepwise_criterion="lr_test",
        entry_p_value=1.0,
        iv_contribution_policy="flag",
    ).fit(
        frame,
        y,
        feature_names=("saldo", "mora"),
        woe_columns=("saldo__woe", "mora__woe"),
        iv_by_feature={"saldo": 0.12, "mora": 0.08},
    )
    assert lr_forward.stepwise_trace_[0].lr_stat is not None

    both_estimator = LogisticPDModel(stepwise_criterion="both", entry_p_value=0.5, exit_p_value=0.5)
    forward_eval = estimator_module.ForwardEvaluation(
        feature="x",
        p_value=0.4,
        wald_p_value=0.4,
        lr_p_value=0.6,
        lr_stat=0.2,
        beta=-0.1,
    )
    backward_eval = estimator_module.BackwardEvaluation(
        feature="x",
        p_value=0.6,
        wald_p_value=0.4,
        lr_p_value=0.6,
        lr_stat=0.2,
        beta=-0.1,
    )
    assert estimator_module._passes_entry(both_estimator, forward_eval) is False
    assert estimator_module._fails_exit(both_estimator, backward_eval) is True
    assert estimator_module._selection_p_value("both", 0.4, 0.3) == 0.4
    assert estimator_module._selection_p_value("lr_test", 0.4, 0.3) == 0.3
    with pytest.raises(ModelFitError, match="LR-test no produjo"):
        estimator_module._selection_p_value("lr_test", 0.4, None)


def test_politicas_signo_iv_y_minimos() -> None:
    sign_frame, sign_y = _sign_frame_target()
    with pytest.raises(ModelFitError, match="Signo invertido"):
        LogisticPDModel(
            stepwise_direction="none",
            sign_policy="fail",
            iv_contribution_policy="flag",
        ).fit(
            sign_frame,
            sign_y,
            feature_names=("protectora", "invertida"),
            woe_columns=("protectora__woe", "invertida__woe"),
            iv_by_feature={"protectora": 0.1, "invertida": 0.1},
        )
    with pytest.raises(ModelFitError, match="sign_policy=exclude"):
        LogisticPDModel(
            stepwise_direction="none",
            force_include=("invertida",),
            fail_on_forced_inverted=False,
            iv_contribution_policy="flag",
        ).fit(
            sign_frame,
            sign_y,
            feature_names=("protectora", "invertida"),
            woe_columns=("protectora__woe", "invertida__woe"),
            iv_by_feature={"protectora": 0.1, "invertida": 0.1},
        )
    with pytest.raises(ModelFitError, match="mínimo"):
        estimator_module._validate_final_feature_count(
            LogisticPDModel(),
            (),
            candidate_count=1,
        )

    zero_iv = LogisticPDModel(
        stepwise_direction="none",
        iv_contribution_policy="flag",
    ).fit(
        sign_frame.loc[:, ["protectora__woe"]],
        sign_y,
        feature_names=("protectora",),
        woe_columns=("protectora__woe",),
        iv_by_feature={"protectora": 0.0},
    )
    assert zero_iv.iv_contribution_["iv_contribution"].isna().all()

    with pytest.raises(ModelFitError, match=r"sum\(iv\)==0"):
        LogisticPDModel(stepwise_direction="none").fit(
            sign_frame.loc[:, ["protectora__woe"]],
            sign_y,
            feature_names=("protectora",),
            woe_columns=("protectora__woe",),
            iv_by_feature={"protectora": 0.0},
        )
    with pytest.raises(ModelFitError, match="force_include"):
        LogisticPDModel(
            stepwise_direction="none",
            force_include=("protectora",),
            iv_contribution_policy="exclude",
        ).fit(
            sign_frame.loc[:, ["protectora__woe"]],
            sign_y,
            feature_names=("protectora",),
            woe_columns=("protectora__woe",),
            iv_by_feature={"protectora": 0.1},
        )


def test_helpers_numericos_y_errores_simulados(monkeypatch: pytest.MonkeyPatch) -> None:
    pandas = estimator_module._import_pandas()
    numpy = estimator_module._import_numpy()
    frame, y = _two_feature_frame_target()
    candidates = estimator_module._candidate_specs(
        frame=frame,
        feature_names=("saldo",),
        woe_columns=("saldo__woe",),
        iv_by_feature={"saldo": 0.12},
        np=numpy,
    )
    estimator = LogisticPDModel(stepwise_direction="none", iv_contribution_policy="flag")

    class FakeWarning(Warning):
        pass

    class FakePerfectError(Exception):
        pass

    class ValueErrorModel:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def fit(self, **_kwargs: Any) -> object:
            raise ValueError("matriz inválida")

    monkeypatch.setattr(
        estimator_module,
        "_import_statsmodels_components",
        lambda: (
            ValueErrorModel,
            ValueErrorModel,
            ValueErrorModel,
            FakeWarning,
            FakeWarning,
            FakePerfectError,
        ),
    )
    with pytest.raises(ModelFitError, match="rechazó"):
        estimator_module._fit_statsmodels(
            estimator=estimator,
            frame=frame,
            target=y,
            sample_weight=None,
            features=("saldo",),
            candidates=candidates,
            pd=pandas,
            np=numpy,
        )

    class LinAlgModel:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def fit(self, **_kwargs: Any) -> object:
            raise numpy.linalg.LinAlgError("singular")

    monkeypatch.setattr(
        estimator_module,
        "_import_statsmodels_components",
        lambda: (
            LinAlgModel,
            LinAlgModel,
            LinAlgModel,
            FakeWarning,
            FakeWarning,
            FakePerfectError,
        ),
    )
    with pytest.raises(ModelFitError, match="invertir la matriz"):
        estimator_module._fit_statsmodels(
            estimator=estimator,
            frame=frame,
            target=y,
            sample_weight=None,
            features=("saldo",),
            candidates=candidates,
            pd=pandas,
            np=numpy,
        )

    class NonConvergedModel:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def fit(self, **_kwargs: Any) -> object:
            return SimpleNamespace(mle_retvals={"converged": False})

    monkeypatch.setattr(
        estimator_module,
        "_import_statsmodels_components",
        lambda: (
            NonConvergedModel,
            NonConvergedModel,
            NonConvergedModel,
            FakeWarning,
            FakeWarning,
            FakePerfectError,
        ),
    )
    with pytest.raises(ModelFitError, match="no convergió"):
        estimator_module._fit_statsmodels(
            estimator=estimator,
            frame=frame,
            target=y,
            sample_weight=None,
            features=("saldo",),
            candidates=candidates,
            pd=pandas,
            np=numpy,
        )

    with pytest.raises(ModelFitError, match="sin intercepto"):
        LogisticPDModel(fit_intercept=False, stepwise_direction="none").fit(
            pd.DataFrame(index=[0, 1, 2, 3]),
            pd.Series([0, 1, 0, 1]),
            feature_names=(),
            woe_columns=(),
            iv_by_feature={},
        )

    assert estimator_module._converged(SimpleNamespace()) is True
    assert estimator_module._n_iterations(SimpleNamespace(mle_retvals={"nit": 7})) == 7
    assert (
        estimator_module._n_iterations(
            SimpleNamespace(mle_retvals={"iterations": "x"}, fit_history={"iteration": 3})
        )
        == 3
    )
    assert estimator_module._n_iterations(SimpleNamespace()) is None
    assert estimator_module._series_from_result([1.0], ("x",), "params", pandas).to_dict() == {
        "x": 1.0
    }
    assert (
        estimator_module._conf_int_frame([[0.1, 0.2]], ("x",), pandas).loc[
            "x",
            "upper",
        ]
        == 0.2
    )
    with pytest.raises(ModelFitError, match="no finitos"):
        estimator_module._validate_finite_series(
            pandas.Series([math.inf]),
            "serie",
            numpy,
        )
    with pytest.raises(ModelFitError, match="no finitos"):
        estimator_module._validate_finite_frame(
            pandas.DataFrame({"x": [math.inf]}),
            "frame",
            numpy,
        )
    with pytest.raises(ModelFitError, match="llnull==0"):
        estimator_module._mcfadden_from_ll(-1.0, 0.0)
    with pytest.raises(ModelFitError, match="df positivo"):
        estimator_module._lr_values(llf_full=-1.0, llf_red=-2.0, df=0)
    with pytest.raises(ModelFitError, match="LR-test inválido"):
        estimator_module._lr_values(llf_full=-3.0, llf_red=-1.0, df=1)

    monkeypatch.setattr(estimator_module, "_import_scipy_chi2_sf", lambda: lambda *_args: math.inf)
    with pytest.raises(ModelFitError, match="p-value no finito"):
        estimator_module._lr_values(llf_full=-1.0, llf_red=-2.0, df=1)

    assert estimator_module._criterion_detail(None, 0.2) == "lr_p=0.2"
    with pytest.raises(ModelFitError, match="no es numérico"):
        estimator_module._finite_float("x", label="beta")
    with pytest.raises(ModelFitError, match="no es finito"):
        estimator_module._finite_float(math.inf, label="beta")


def _two_feature_frame_target() -> tuple[pd.DataFrame, pd.Series]:
    return (
        pd.DataFrame(
            {
                "saldo__woe": [
                    -2.0,
                    -1.6,
                    -1.3,
                    -1.1,
                    -0.8,
                    -0.4,
                    0.2,
                    0.5,
                    0.9,
                    1.2,
                    1.6,
                    2.0,
                    -1.8,
                    -0.6,
                    0.1,
                    0.7,
                    1.4,
                    -1.4,
                    0.3,
                    1.8,
                ],
                "mora__woe": [
                    -1.5,
                    -1.2,
                    -0.9,
                    0.1,
                    -0.4,
                    -0.2,
                    0.3,
                    0.6,
                    1.1,
                    1.4,
                    1.8,
                    2.2,
                    -1.7,
                    -0.8,
                    0.0,
                    0.8,
                    1.6,
                    -1.0,
                    0.2,
                    2.0,
                ],
            }
        ),
        pd.Series([1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 0, 1, 0, 0]),
    )


def _stepwise_frame_target() -> tuple[pd.DataFrame, pd.Series]:
    rows: list[dict[str, float]] = []
    labels: list[int] = []
    values = [
        -2.0,
        -1.8,
        -1.6,
        -1.4,
        -1.2,
        -1.0,
        -0.8,
        -0.6,
        -0.4,
        -0.2,
        0.0,
        0.2,
        0.4,
        0.6,
        0.8,
        1.0,
        1.2,
        1.4,
        1.6,
        1.8,
        2.0,
    ]
    for index, value in enumerate(values):
        probability = 1 / (1 + math.exp(1.4 * value))
        label = 1 if probability > 0.55 else 0
        if index in {3, 9, 16}:
            label = 1 - label
        labels.append(label)
        rows.append(
            {
                "informativa__woe": value,
                "ruido__woe": (((index * 7) % 11) - 5) / 5,
                "redundante__woe": (value * 0.95) + ((((index * 3) % 5) - 2) * 0.03),
            }
        )
    return pd.DataFrame(rows), pd.Series(labels)


def _sign_frame_target() -> tuple[pd.DataFrame, pd.Series]:
    frame = pd.DataFrame(
        {
            "protectora__woe": [
                -2,
                -1.5,
                -1,
                -0.5,
                0,
                0.5,
                1,
                1.5,
                2,
                -1.2,
                0.8,
                1.8,
                -0.8,
                0.2,
                1.1,
                -1.7,
            ],
            "invertida__woe": [
                2,
                -1,
                1,
                -2,
                0,
                1.5,
                -0.5,
                2.2,
                -1.5,
                0.4,
                1.2,
                -0.8,
                0.7,
                -1.2,
                1.9,
                -0.3,
            ],
        }
    )
    linear = (0.9 * frame["invertida__woe"]) - (0.9 * frame["protectora__woe"])
    y = linear.gt(0).astype("int64")
    y.iloc[[3, 10]] = 1 - y.iloc[[3, 10]]
    return frame, cast(pd.Series, y)


def _iv_frame_target() -> tuple[pd.DataFrame, pd.Series]:
    frame, y = _two_feature_frame_target()
    frame = frame.rename(columns={"saldo__woe": "dominante__woe", "mora__woe": "secundaria__woe"})
    frame["tercera__woe"] = [
        0.4,
        -0.7,
        1.2,
        -1.1,
        0.9,
        -0.2,
        1.5,
        -1.4,
        0.1,
        -0.5,
        1.0,
        -1.7,
        0.8,
        -0.9,
        1.7,
        -0.1,
        0.6,
        -1.3,
        0.3,
        -0.4,
    ]
    return frame, y
