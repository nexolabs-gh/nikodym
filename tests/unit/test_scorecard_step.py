"""Tests de ``ScorecardStep``: contrato CT-1, auditoría, bordes e import liviano."""

from __future__ import annotations

import math
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
import nikodym.scorecard.step as step_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.study import Study
from nikodym.scorecard.config import PointOverrideConfig, ScorecardConfig
from nikodym.scorecard.exceptions import ScorecardFitError, ScorecardTransformError
from nikodym.scorecard.results import ScorecardCardSection, ScorecardResult
from nikodym.scorecard.step import SCORECARD_ARTIFACTS, ScorecardStep

FACTOR_GOLDEN = 28.85390081777927
OFFSET_GOLDEN = 487.1228762045055
SALDO_BAJO_POINTS = 233.1740338078522
SALDO_ALTO_POINTS = 256.2571544620756
MORA_BAJA_POINTS = 242.40728206954157
MORA_ALTA_POINTS = 263.18209065834264
SCORE_C1_EXACT = 475.58131587739376
SCORE_C2_EXACT = 519.4392451204183


def _config(**kwargs: Any) -> ScorecardConfig:
    """Config base del step con redondeo exacto salvo override explícito."""
    return ScorecardConfig(rounding_method="none", **kwargs)


def _tables() -> dict[str, pd.DataFrame]:
    """Tablas WoE sintéticas con dos variables y fila Totals defensiva."""
    return {
        "saldo": pd.DataFrame(
            {"Bin": ["bajo", "alto", "Totals"], "WoE": [-0.7, 0.3, 0.0]},
            index=[0, 1, "Totals"],
        ),
        "mora": pd.DataFrame(
            {"Bin": ["baja", "alta", "Totals"], "WoE": [-0.2, 0.4, 0.0]},
            index=[0, 1, "Totals"],
        ),
    }


def _summary() -> pd.DataFrame:
    """Summary mínimo que el step valida pero no usa para recalcular IV."""
    return pd.DataFrame({"name": ["saldo", "mora"], "iv": [0.12, 0.08]})


def _woe_frame(*, include_filtered: bool = True) -> pd.DataFrame:
    """Frame WoE canónico con dos filas modelables y una fuera de modelo opcional."""
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout"],
            "target": [1, 0],
            "saldo__woe": [-0.7, 0.3],
            "mora__woe": [-0.2, 0.4],
        },
        index=pd.Index(["c1", "c2"], name="loan_id"),
    )
    if not include_filtered:
        return frame
    outside = pd.DataFrame(
        {
            "partition": ["fuera_de_modelo"],
            "target": [1],
            "saldo__woe": [0.3],
            "mora__woe": [0.4],
        },
        index=pd.Index(["c3"], name="loan_id"),
    )
    return pd.concat([frame, outside], axis=0)


def _coefficients(*, include_intercept: bool = True) -> pd.DataFrame:
    """Coeficientes sintéticos del modelo logístico WoE."""
    rows: list[dict[str, object]] = []
    if include_intercept:
        rows.append({"feature": "intercept", "woe_column": "const", "beta": -0.4})
    rows.extend(
        [
            {"feature": "saldo", "woe_column": "saldo__woe", "beta": -0.8},
            {"feature": "mora", "woe_column": "mora__woe", "beta": -1.2},
        ]
    )
    return pd.DataFrame(rows)


def _raw_pd_frame(index: pd.Index | None = None) -> pd.DataFrame:
    """PD cruda alineada por índice, sin recalcular dentro de scorecard."""
    idx = pd.Index(["c1", "c2"], name="loan_id") if index is None else index
    base = pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout"],
            "target": [1, 0],
            "linear_predictor": [0.4, -1.12],
            "pd_raw": [1.0 / (1.0 + math.exp(-0.4)), 1.0 / (1.0 + math.exp(1.12))],
        },
        index=pd.Index(["c1", "c2"], name="loan_id"),
    )
    return base.loc[idx].copy(deep=True)


def _study_with_artifacts(
    *,
    config: ScorecardConfig | None = None,
    tables: dict[str, pd.DataFrame] | None = None,
    summary: pd.DataFrame | None = None,
    woe_frame: pd.DataFrame | None = None,
    binning_result: object | None = None,
    estimator: object | None = None,
    final_features: tuple[str, ...] = ("saldo", "mora"),
    final_woe_columns: tuple[str, ...] = ("saldo__woe", "mora__woe"),
    coefficients: pd.DataFrame | None = None,
    raw_pd_frame: pd.DataFrame | None = None,
) -> Study:
    """Construye un ``Study`` con los nueve artefactos upstream del contrato."""
    cfg = config or _config()
    study = Study(NikodymConfig(scorecard=cfg))
    study.artifacts.set("binning", "tables", _tables() if tables is None else tables)
    study.artifacts.set("binning", "summary", _summary() if summary is None else summary)
    study.artifacts.set(
        "binning",
        "woe_frame",
        _woe_frame() if woe_frame is None else woe_frame,
    )
    study.artifacts.set(
        "binning",
        "result",
        binning_result
        if binning_result is not None
        else SimpleNamespace(woe_column_map={"saldo": "saldo__woe", "mora": "mora__woe"}),
    )
    study.artifacts.set(
        "model",
        "estimator",
        estimator if estimator is not None else SimpleNamespace(fit_intercept=True),
    )
    study.artifacts.set("model", "final_features", final_features)
    study.artifacts.set("model", "final_woe_columns", final_woe_columns)
    study.artifacts.set(
        "model",
        "coefficients",
        _coefficients() if coefficients is None else coefficients,
    )
    study.artifacts.set(
        "model",
        "raw_pd_frame",
        _raw_pd_frame() if raw_pd_frame is None else raw_pd_frame,
    )
    return study


def test_from_config_y_contrato_step_exacto() -> None:
    """``ScorecardStep`` expone el contrato CT-1 exacto del SDD-09."""
    cfg = _config()
    step = ScorecardStep.from_config(cfg)

    assert isinstance(step, ScorecardStep)
    assert step.config is cfg
    assert step.name == "scorecard"
    assert step.requires == (
        ("binning", "tables"),
        ("binning", "summary"),
        ("binning", "woe_frame"),
        ("binning", "result"),
        ("model", "estimator"),
        ("model", "final_features"),
        ("model", "final_woe_columns"),
        ("model", "coefficients"),
        ("model", "raw_pd_frame"),
    )
    assert step.provides == tuple(("scorecard", key) for key in SCORECARD_ARTIFACTS)


def test_core_study_cablea_scorecard_en_orden_por_defecto() -> None:
    """``Study`` resuelve ``scorecard`` como dominio perezoso después de ``model``."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order[order.index("model") + 1] == "scorecard"
    assert study_module._DOMAIN_MODULES["scorecard"] == "nikodym.scorecard"
    assert study_module._DOMAIN_CONFIG_CLASSES["scorecard"] == (
        "nikodym.scorecard.config",
        "ScorecardConfig",
    )

    study = Study(NikodymConfig(scorecard=ScorecardConfig()))

    assert study._default_step_names() == ["scorecard"]
    assert isinstance(study._resolve_step("scorecard"), ScorecardStep)


def test_execute_publica_result_card_goldens_versiones_y_no_consume_rng(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El step delega puntos al scaler, alinea PD cruda y publica copias defensivas."""
    versions = {"pandas": "2.3.3", "numpy": "2.4.6"}
    monkeypatch.setattr(step_module.metadata, "version", lambda name: versions[name])
    study = _study_with_artifacts()
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = ScorecardStep.from_config(study.config.scorecard)
    step._audit = sink

    result = step.execute(study, object())

    assert isinstance(result, ScorecardResult)
    assert isinstance(study.artifacts.get("scorecard", "card"), ScorecardCardSection)
    for key in SCORECARD_ARTIFACTS:
        assert study.artifacts.has("scorecard", key)
    assert result.factor == pytest.approx(FACTOR_GOLDEN)
    assert result.offset == pytest.approx(OFFSET_GOLDEN)
    assert result.card.dependency_versions == versions
    assert result.points_columns == ("saldo__points", "mora__points")

    scorecard = result.scorecard.set_index(["feature", "bin_label"])
    assert scorecard.loc[("saldo", "bajo"), "raw_points"] == pytest.approx(SALDO_BAJO_POINTS)
    assert scorecard.loc[("saldo", "alto"), "points"] == pytest.approx(SALDO_ALTO_POINTS)
    assert scorecard.loc[("mora", "baja"), "raw_points"] == pytest.approx(MORA_BAJA_POINTS)
    assert scorecard.loc[("mora", "alta"), "points"] == pytest.approx(MORA_ALTA_POINTS)

    score = result.score
    assert score.index.tolist() == ["c1", "c2"]
    assert score.columns.tolist() == [
        "partition",
        "target",
        "linear_predictor",
        "pd_raw",
        "saldo__points",
        "mora__points",
        "score",
    ]
    assert score["score"].tolist() == pytest.approx([SCORE_C1_EXACT, SCORE_C2_EXACT])
    assert [event.payload["regla"] for event in sink.events if event.kind == "decision"] == [
        "scorecard_fuera_de_modelo"
    ]


def test_execute_no_muta_artefactos_upstream() -> None:
    """Las entradas de model/binning se copian antes de ajustar y transformar."""
    study = _study_with_artifacts()
    tables_before = {
        feature: table.copy(deep=True)
        for feature, table in study.artifacts.get("binning", "tables").items()
    }
    summary_before = study.artifacts.get("binning", "summary").copy(deep=True)
    woe_before = study.artifacts.get("binning", "woe_frame").copy(deep=True)
    coefficients_before = study.artifacts.get("model", "coefficients").copy(deep=True)
    raw_before = study.artifacts.get("model", "raw_pd_frame").copy(deep=True)

    ScorecardStep.from_config(study.config.scorecard).execute(study, np.random.default_rng(1))

    for feature, table in study.artifacts.get("binning", "tables").items():
        assert_frame_equal(table, tables_before[feature])
    assert_frame_equal(study.artifacts.get("binning", "summary"), summary_before)
    assert_frame_equal(study.artifacts.get("binning", "woe_frame"), woe_before)
    assert_frame_equal(study.artifacts.get("model", "coefficients"), coefficients_before)
    assert_frame_equal(study.artifacts.get("model", "raw_pd_frame"), raw_before)


def test_validadores_de_artefactos_fallan_con_mensajes_en_espanol() -> None:
    """Los helpers ``_as_*`` rechazan tipos inválidos con contexto del artefacto."""
    pd_mod = step_module._import_pandas()

    with pytest.raises(ScorecardFitError, match=r"pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd_mod, "binning.summary")
    with pytest.raises(ScorecardFitError, match="mapping de DataFrames"):
        step_module._as_tables(object(), pd_mod)
    with pytest.raises(ScorecardFitError, match="tabla no tabular"):
        step_module._as_tables({"saldo": object()}, pd_mod)
    with pytest.raises(ScorecardFitError, match=r"tuple\[str"):
        step_module._as_string_tuple(object(), "model", "final_features")
    with pytest.raises(ScorecardFitError, match="woe_column_map"):
        step_module._as_binning_result(object())
    with pytest.raises(ScorecardFitError, match="fit_intercept"):
        step_module._as_model_estimator(object())


def test_mapping_columnas_indices_y_config_dict_cubren_ramas_defensivas() -> None:
    """Validaciones puras del step cubren shape inválido antes del scaler."""
    fallback = _config()
    study = SimpleNamespace(
        config=SimpleNamespace(scorecard={"rounding_method": "nearest_integer"})
    )
    assert (
        step_module._scorecard_config_from_study(
            study,
            fallback=fallback,
        ).rounding_method
        == "nearest_integer"
    )
    assert (
        step_module._scorecard_config_from_study(
            Study(NikodymConfig()),
            fallback=fallback,
        )
        is fallback
    )

    with pytest.raises(ScorecardFitError, match="mismo largo"):
        step_module._validate_feature_mapping(("saldo",), ("saldo__woe", "mora__woe"), {})
    with pytest.raises(ScorecardFitError, match="al menos una"):
        step_module._validate_feature_mapping((), (), {})
    with pytest.raises(ScorecardFitError, match="duplicados"):
        step_module._validate_feature_mapping(
            ("saldo", "saldo"),
            ("saldo__woe", "otra__woe"),
            {"saldo": "saldo__woe"},
        )
    with pytest.raises(ScorecardFitError, match="duplicados"):
        step_module._validate_feature_mapping(
            ("saldo", "mora"),
            ("saldo__woe", "saldo__woe"),
            {"saldo": "saldo__woe", "mora": "saldo__woe"},
        )
    with pytest.raises(ScorecardFitError, match="no contiene"):
        step_module._validate_feature_mapping(("saldo",), ("saldo__woe",), {})
    with pytest.raises(ScorecardFitError, match="no coincide"):
        step_module._validate_feature_mapping(
            ("saldo",),
            ("saldo__woe",),
            {"saldo": "otra"},
        )

    duplicated_columns = pd.DataFrame([[1, 2]], columns=["x", "x"])
    with pytest.raises(ScorecardFitError, match="duplicadas"):
        step_module._validate_woe_frame_columns(duplicated_columns, ("x",))
    with pytest.raises(ScorecardFitError, match="columnas WoE finales"):
        step_module._validate_woe_frame_columns(pd.DataFrame({"x": [1.0]}), ("z",))

    raw = _raw_pd_frame()
    with pytest.raises(ScorecardFitError, match="columnas requeridas"):
        step_module._validate_raw_pd_frame(raw.drop(columns=["pd_raw"]))
    duplicate_index = pd.concat([raw, raw.iloc[[0]]])
    with pytest.raises(ScorecardFitError, match="índice duplicado"):
        step_module._validate_raw_pd_frame(duplicate_index)


def test_extract_coefficients_cubre_intercepto_y_coeficientes_invalidos() -> None:
    """El step falla temprano ante intercepto/coefs ambiguos o no defendibles."""
    features = ("saldo", "mora")
    woe_columns = ("saldo__woe", "mora__woe")

    assert (
        step_module._extract_coefficients(
            _coefficients(include_intercept=False),
            final_features=features,
            final_woe_columns=woe_columns,
            fit_intercept=False,
        )[1]
        == 0.0
    )
    with pytest.raises(ScorecardFitError, match="columnas requeridas"):
        step_module._extract_coefficients(
            pd.DataFrame({"feature": ["saldo"]}),
            final_features=features,
            final_woe_columns=woe_columns,
            fit_intercept=True,
        )
    with pytest.raises(ScorecardFitError, match="no contiene intercepto"):
        step_module._extract_coefficients(
            _coefficients(include_intercept=False),
            final_features=features,
            final_woe_columns=woe_columns,
            fit_intercept=True,
        )
    with pytest.raises(ScorecardFitError, match="más de una fila"):
        step_module._extract_coefficients(
            pd.concat(
                [
                    _coefficients(),
                    pd.DataFrame([{"feature": "intercept", "woe_column": "x", "beta": 0.0}]),
                ],
                ignore_index=True,
            ),
            final_features=features,
            final_woe_columns=woe_columns,
            fit_intercept=True,
        )
    with pytest.raises(ScorecardFitError, match="sin coeficiente"):
        step_module._extract_coefficients(
            _coefficients().loc[lambda df: df["feature"].ne("mora")].copy(deep=True),
            final_features=features,
            final_woe_columns=woe_columns,
            fit_intercept=True,
        )
    with pytest.raises(ScorecardFitError, match="ambiguo"):
        step_module._extract_coefficients(
            pd.concat(
                [
                    _coefficients(),
                    pd.DataFrame([{"feature": "saldo", "woe_column": "saldo__woe", "beta": -0.7}]),
                ],
                ignore_index=True,
            ),
            final_features=features,
            final_woe_columns=woe_columns,
            fit_intercept=True,
        )
    mismatch = _coefficients()
    mismatch.loc[mismatch["feature"].eq("saldo"), "woe_column"] = "otra"
    with pytest.raises(ScorecardFitError, match="mapping final"):
        step_module._extract_coefficients(
            mismatch,
            final_features=features,
            final_woe_columns=woe_columns,
            fit_intercept=True,
        )
    with pytest.raises(ScorecardFitError, match="no es numérico"):
        step_module._finite_float("x", "beta")
    with pytest.raises(ScorecardFitError, match="no es finito"):
        step_module._finite_float(math.inf, "beta")


def test_execute_cubre_bordes_del_sdd_09() -> None:
    """Los casos borde principales levantan la excepción propia esperada."""
    with pytest.raises(ScorecardFitError, match="sin tabla"):
        ScorecardStep.from_config(_config()).execute(
            _study_with_artifacts(tables={"saldo": _tables()["saldo"]}),
            np.random.default_rng(1),
        )
    with pytest.raises(ScorecardFitError, match="sin coeficiente"):
        ScorecardStep.from_config(_config()).execute(
            _study_with_artifacts(
                coefficients=_coefficients().loc[lambda df: df["feature"].ne("mora")],
            ),
            np.random.default_rng(1),
        )
    bad_tables = _tables()
    bad_tables["saldo"] = pd.DataFrame({"Bin": ["bajo"], "WoE": [math.nan]})
    with pytest.raises(ScorecardFitError, match="WoE no finito"):
        ScorecardStep.from_config(_config()).execute(
            _study_with_artifacts(tables=bad_tables),
            np.random.default_rng(1),
        )
    with pytest.raises(ScorecardTransformError, match="WoE no finita"):
        ScorecardStep.from_config(_config()).execute(
            _study_with_artifacts(
                woe_frame=_woe_frame(include_filtered=False).assign(saldo__woe=[math.inf, 0.3]),
            ),
            np.random.default_rng(1),
        )
    with pytest.raises(ScorecardTransformError, match="colisiones"):
        ScorecardStep.from_config(_config()).execute(
            _study_with_artifacts(woe_frame=_woe_frame(include_filtered=False).assign(score=0.0)),
            np.random.default_rng(1),
        )


def test_bin_no_visto_clip_override_y_modelo_una_variable_auditan() -> None:
    """Bordes no fatales quedan trazados y conservan salidas deterministas."""
    unseen_sink = InMemoryAuditSink()
    unseen = _study_with_artifacts(
        woe_frame=_woe_frame(include_filtered=False).assign(saldo__woe=[0.123, 0.3])
    )
    unseen.set_audit_sink(unseen_sink)
    unseen_step = ScorecardStep.from_config(unseen.config.scorecard)
    unseen_step._audit = unseen_sink
    unseen_step.execute(unseen, np.random.default_rng(1))
    assert "bin_no_visto" in {
        event.payload["regla"] for event in unseen_sink.events if event.kind == "decision"
    }

    for clip, expected_rule in [(True, "score_clip"), (False, "score_fuera_de_rango")]:
        sink = InMemoryAuditSink()
        study = _study_with_artifacts(
            config=_config(min_score=490.0, max_score=500.0, clip=clip),
            woe_frame=_woe_frame(include_filtered=False),
        )
        study.set_audit_sink(sink)
        clip_step = ScorecardStep.from_config(study.config.scorecard)
        clip_step._audit = sink
        clip_step.execute(study, np.random.default_rng(1))
        assert expected_rule in {
            event.payload["regla"] for event in sink.events if event.kind == "decision"
        }

    override = PointOverrideConfig(
        feature="saldo",
        bin_label="bajo",
        points=200,
        reason="homologacion manual",
    )
    override_study = _study_with_artifacts(config=_config(point_overrides=(override,)))
    override_result = ScorecardStep.from_config(override_study.config.scorecard).execute(
        override_study,
        np.random.default_rng(1),
    )
    assert override_result.scorecard.loc[0, "source"] == "override"

    one_feature = _study_with_artifacts(
        final_features=("saldo",),
        final_woe_columns=("saldo__woe",),
        tables={"saldo": _tables()["saldo"]},
        binning_result=SimpleNamespace(woe_column_map={"saldo": "saldo__woe"}),
        coefficients=_coefficients().loc[lambda df: df["feature"].ne("mora")],
        woe_frame=_woe_frame(include_filtered=False).drop(columns=["mora__woe"]),
    )
    one_result = ScorecardStep.from_config(one_feature.config.scorecard).execute(
        one_feature,
        np.random.default_rng(1),
    )
    assert one_result.card.n_variables == 1
    assert one_result.points_columns == ("saldo__points",)


def test_alineacion_versiones_import_y_helpers_defensivos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cubre ramas defensivas de alineación, versiones e import perezoso."""
    transformed = pd.DataFrame(
        {"saldo__points": [1.0], "score": [1.0]},
        index=pd.Index(["x"], name="loan_id"),
    )
    with pytest.raises(ScorecardFitError, match="mismo índice"):
        step_module._assemble_score_frame(
            transformed=transformed,
            raw_pd_frame=_raw_pd_frame(),
            points_columns=("saldo__points",),
            score_column="score",
        )
    with pytest.raises(ScorecardFitError, match="índice duplicado"):
        step_module._assemble_score_frame(
            transformed=pd.concat([transformed, transformed]),
            raw_pd_frame=pd.DataFrame(
                {
                    "partition": ["desarrollo"],
                    "target": [1],
                    "linear_predictor": [0.0],
                    "pd_raw": [0.5],
                },
                index=pd.Index(["x"], name="loan_id"),
            ),
            points_columns=("saldo__points",),
            score_column="score",
        )

    def fake_version(name: str) -> str:
        if name == "numpy":
            raise step_module.metadata.PackageNotFoundError(name)
        return f"v-{name}"

    monkeypatch.setattr(step_module.metadata, "version", fake_version)
    assert step_module._dependency_versions() == {"pandas": "v-pandas", "numpy": "no_instalado"}
    assert step_module._scale_parameters(_config()) == pytest.approx((FACTOR_GOLDEN, OFFSET_GOLDEN))
    normalized = step_module._normalize_float_frame(
        pd.DataFrame({"x": [-0.0, 1.0], "y": [1, 2]}),
        pd=pd,
    )
    assert math.copysign(1.0, normalized.loc[0, "x"]) == 1.0
    assert step_module._normalize_float(1.5) == 1.5
    no_partition = pd.DataFrame({"saldo__woe": [0.0]}, index=["x"])
    filtered = ScorecardStep.from_config(_config())._filter_modelable_rows(no_partition)
    assert_frame_equal(filtered, no_partition)
    filtered.loc["x", "saldo__woe"] = 99.0
    assert no_partition.loc["x", "saldo__woe"] == 0.0

    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="ScorecardStep requiere pandas"):
        step_module._import_pandas()


def test_import_scorecard_step_liviano_no_carga_tabulares_ni_scoring() -> None:
    """``import nikodym.scorecard`` registra el step sin arrastrar pandas/sklearn."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.scorecard
        from nikodym.core.registry import REGISTRY

        assert REGISTRY.resolve("scorecard", "standard").__name__ == "ScorecardStep"
        blocked = [
            name for name in ("pandas", "sklearn", "statsmodels", "scipy", "optbinning")
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
