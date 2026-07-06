"""Tests del ``ExplainStep`` (SDD-14 §7/§9/§11): orquestación de la explicabilidad unificada.

La mitad ML se ejercita con un ``shap`` **fake** (módulo en ``sys.modules``) y un ``MLChallenger``
**fake** con la superficie sklearn-like mínima, de modo que se cubre el 100% del cableado **sin**
instalar ``shap``; la mitad scorecard es analítica exacta y corre sin ``shap``. El orden del
pipeline (``explain`` tras ``ml``) y el consumo de artefactos aguas arriba se prueban vía
``Study.run``. Cubre los ``requires`` dinámicos (CT-1), la degradación best-effort del scorecard,
la consistencia de puntos de SDD-09 con el término ``alpha/n`` (deuda B14.4(3)), la falla ruidosa
del contrato del estimador (deuda B14.4(2)), el import liviano y el no-reúso de Shapley.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.core.study as study_module
import nikodym.explain as explain_pkg
import nikodym.explain.step as step_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.explain.config import ExplainConfig, LocalScopeConfig, MLExplainerConfig
from nikodym.explain.exceptions import ExplainConfigError, ExplainDataError
from nikodym.explain.step import EXPLAIN_ARTIFACTS, ExplainStep
from nikodym.ml.config import MLConfig

GOLDEN_DEFAULT_CONFIG_HASH = "2dc342f1fd7be6d5ec32bca5a4c3cc4badf1da11f6876b280f7ca9662f857f3e"
_FEATURES = ("f0__woe", "f1__woe")
_INTERCEPT = 0.1
_COEF = (0.8, -0.5)


# ═══════════════════════════ fakes de shap y challenger ═══════════════════════════
def _install_fake_shap(
    monkeypatch: pytest.MonkeyPatch, *, version: str | None = "0.99.0-fake"
) -> types.ModuleType:
    """Instala un ``shap`` fake con explainers lineales exactos (``phi = X·coef`` y ``phi0``)."""
    module = types.ModuleType("shap")
    if version is not None:
        module.__version__ = version  # type: ignore[attr-defined]

    class _FakeExplainer:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.expected_value = _INTERCEPT

        def shap_values(self, X: Any, **kwargs: Any) -> Any:  # noqa: N803
            matrix = np.asarray(X.to_numpy() if hasattr(X, "to_numpy") else X, dtype="float64")
            return matrix * np.asarray(_COEF, dtype="float64")

    module.TreeExplainer = _FakeExplainer  # type: ignore[attr-defined]
    module.LinearExplainer = _FakeExplainer  # type: ignore[attr-defined]
    module.KernelExplainer = _FakeExplainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", module)
    return module


class _FakeChallenger:
    """Emula la API sklearn-like de ``MLChallenger`` consistente con el ``shap`` fake lineal."""

    def __init__(self, *, backend: str = "xgboost", space: str = "log_odds") -> None:
        self.backend = backend
        self.feature_names_in_ = _FEATURES
        self.estimator_ = object()
        self.classes_ = np.array([0, 1])
        self._space = space
        if backend == "svm":
            self.hyperparameters = SimpleNamespace(kernel="linear")

    def predict_pd(self, X: Any) -> Any:  # noqa: N803
        matrix = np.asarray(X.loc[:, list(_FEATURES)].to_numpy(), dtype="float64")
        margin = _INTERCEPT + matrix @ np.asarray(_COEF, dtype="float64")
        if self._space == "log_odds":
            return 1.0 / (1.0 + np.exp(-margin))
        return np.clip(margin, 1e-9, 1.0 - 1e-9)


# ═══════════════════════════ builders de artefactos ═══════════════════════════
def _woe_frame() -> pd.DataFrame:
    """Frame WoE con particiones desarrollo/holdout y valores que dejan la PD en (0, 1)."""
    rows: list[dict[str, Any]] = []
    for partition in ("desarrollo", "holdout"):
        for i in range(6):
            rows.append(
                {
                    "partition": partition,
                    "target": i % 2,
                    "f0__woe": 0.1 * i - 0.3,
                    "f1__woe": 0.2 - 0.05 * i,
                }
            )
    return pd.DataFrame(rows)


def _pd_frame(woe: pd.DataFrame) -> pd.DataFrame:
    """PD del challenger indexada como ``woe`` (contexto y priorización ``top_by_pd``)."""
    matrix = woe.loc[:, list(_FEATURES)].to_numpy(dtype="float64")
    margin = _INTERCEPT + matrix @ np.asarray(_COEF, dtype="float64")
    return pd.DataFrame(
        {
            "partition": woe["partition"].to_numpy(),
            "target": woe["target"].to_numpy(),
            "pd_hat": 1.0 / (1.0 + np.exp(-margin)),
        },
        index=woe.index,
    )


def _coefficients() -> pd.DataFrame:
    """Coeficientes del campeón: intercepto + dos features WoE (SDD-08)."""
    return pd.DataFrame(
        [
            {"feature": "intercept", "woe_column": "const", "beta": 0.4},
            {"feature": "f0", "woe_column": "f0__woe", "beta": 0.8},
            {"feature": "f1", "woe_column": "f1__woe", "beta": -0.5},
        ]
    )


def _woe_tables() -> dict[str, pd.DataFrame]:
    """Tablas WoE por atributo (nombre/bin), con una fila agregada a saltar."""
    return {
        "f0": pd.DataFrame({"Bin": ["b0", "b1", "Totals"], "WoE": [-0.3, 0.3, np.nan]}),
        "f1": pd.DataFrame({"Bin": ["c0", "c1"], "WoE": [0.2, -0.05]}),
    }


def _scorecard_table(
    *, factor: float, offset: float, alpha: float, drop_alpha: bool = False
) -> pd.DataFrame:
    """Tabla de puntos SDD-09 con ``raw_points`` reconstruible; ``drop_alpha`` omite ``alpha/n``."""
    n_variables = 2
    intercept_share = alpha / n_variables
    offset_share = offset / n_variables
    rows: list[dict[str, Any]] = []
    for feature, woe_column, beta, woe in (
        ("f0", "f0__woe", 0.8, -0.3),
        ("f0", "f0__woe", 0.8, 0.3),
        ("f1", "f1__woe", -0.5, 0.2),
        ("f1", "f1__woe", -0.5, -0.05),
    ):
        component = beta * woe + (0.0 if drop_alpha else intercept_share)
        raw_points = offset_share - factor * component
        rows.append(
            {
                "feature": feature,
                "woe_column": woe_column,
                "bin_label": f"{woe:+.2f}",
                "woe": woe,
                "beta": beta,
                "intercept_share": intercept_share,
                "raw_points": raw_points,
                "points": round(raw_points),
            }
        )
    return pd.DataFrame(rows)


def _scorecard_result(*, factor: float = 20.0, offset: float = 600.0) -> SimpleNamespace:
    """``scorecard.result`` con el escalamiento necesario para la consistencia (SDD-09)."""
    return SimpleNamespace(
        factor=factor,
        offset=offset,
        score_direction="higher_is_lower_risk",
        points_columns=("f0_points", "f1_points"),
    )


def _binning_summary() -> pd.DataFrame:
    """``binning.summary`` con IV por variable (best-effort para la comparativa)."""
    return pd.DataFrame({"name": ["f0", "f1"], "iv": [0.3, 0.1]})


def _study(
    explain_cfg: ExplainConfig,
    *,
    with_ml: bool = True,
    with_scorecard: bool = False,
    backend: str = "xgboost",
    space: str = "log_odds",
    deterministic: bool = True,
    scorecard_table: pd.DataFrame | None = None,
    with_scorecard_result: bool = True,
    feature_source: str = "binning_woe",
) -> Study:
    """Construye un ``Study`` con el sink en memoria y los artefactos aguas arriba inyectados."""
    ml_cfg = MLConfig(feature_source=feature_source) if with_ml else None
    study = Study(NikodymConfig(explain=explain_cfg, ml=ml_cfg))
    study.set_audit_sink(InMemoryAuditSink())
    woe = _woe_frame()
    study.artifacts.set("data", "labels", SimpleNamespace(target_col="target"))
    study.artifacts.set("data", "splits", SimpleNamespace(partition_col="partition"))
    # binning.woe_frame siempre está (binning corre aguas arriba de selection/ml en el pipeline).
    study.artifacts.set("binning", "woe_frame", woe)
    if feature_source == "selection_woe":
        study.artifacts.set("selection", "selected_woe_frame", woe)
        study.artifacts.set("selection", "selected_woe_columns", list(_FEATURES))
    if with_ml:
        study.artifacts.set("ml", "estimator", _FakeChallenger(backend=backend, space=space))
        study.artifacts.set(
            "ml", "backend_metadata", SimpleNamespace(deterministic=deterministic, backend=backend)
        )
        study.artifacts.set("ml", "pd_frame", _pd_frame(woe))
    if with_scorecard:
        table = (
            scorecard_table
            if scorecard_table is not None
            else _scorecard_table(factor=20.0, offset=600.0, alpha=0.8)
        )
        study.artifacts.set("model", "coefficients", _coefficients())
        study.artifacts.set("scorecard", "scorecard", table)
        study.artifacts.set("binning", "tables", _woe_tables())
        study.artifacts.set("binning", "summary", _binning_summary())
        if with_scorecard_result:
            study.artifacts.set("scorecard", "result", _scorecard_result())
    return study


def _decisions(study: Study) -> dict[str, dict[str, Any]]:
    """Indexa las decisiones auditadas por regla (última gana) para inspección."""
    sink = study.artifacts._audit
    assert isinstance(sink, InMemoryAuditSink)
    return {
        event.payload["regla"]: event.payload
        for event in sink.events
        if event.kind == "decision" and "regla" in event.payload
    }


# ═══════════════════════════ registro, contrato, orden, import liviano ═══════════════════════════
def test_registro_contrato_orden_hash_e_import_liviano() -> None:
    """``ExplainStep`` queda registrado, con el contrato y el orden canónico, sin mover el hash."""
    cfg = ExplainConfig()
    step = ExplainStep.from_config(cfg)
    assert REGISTRY.resolve("explain", "standard") is ExplainStep
    assert explain_pkg.__getattr__("ExplainStep") is ExplainStep
    assert step.config is cfg
    assert step.name == "explain"
    assert step.provides == tuple(("explain", key) for key in EXPLAIN_ARTIFACTS)
    assert len(EXPLAIN_ARTIFACTS) == 7
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order[order.index("ml") + 1] == "explain"
    assert order.index("explain") > order.index("scorecard")
    assert study_module._DOMAIN_MODULES["explain"] == "nikodym.explain"
    assert study_module._DOMAIN_CONFIG_CLASSES["explain"] == (
        "nikodym.explain.config",
        "ExplainConfig",
    )
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
    assert NikodymConfig().explain is None


def test_import_guard_no_arrastra_pesados() -> None:
    """``import nikodym.explain`` no deja shap/matplotlib/numba/llvmlite/sklearn/pandas/numpy."""
    code = (
        "import nikodym.core, sys;"
        "assert 'nikodym.explain' not in sys.modules;"
        "import nikodym.explain;"
        "blocked=[m for m in ('shap','matplotlib','numba','llvmlite','sklearn','pandas','numpy') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'ExplainStep' in nikodym.explain.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_emit_reenvia_al_sink() -> None:
    """``emit`` reenvía un evento al sink inyectado (el step puede actuar como AuditSink)."""
    from datetime import UTC, datetime

    from nikodym.core.audit import AuditEvent

    step = ExplainStep.from_config(ExplainConfig())
    sink = InMemoryAuditSink()
    step._audit = sink
    step.emit(
        AuditEvent(kind="decision", step="explain", payload={"regla": "x"}, ts=datetime.now(tz=UTC))
    )
    assert sink.events[-1].payload == {"regla": "x"}


# ═══════════════════════════ requires dinámicos (CT-1) ═══════════════════════════
@pytest.mark.parametrize(
    ("targets", "feature_source", "esperado"),
    [
        (
            "both",
            "binning_woe",
            (
                ("data", "labels"),
                ("data", "splits"),
                ("ml", "estimator"),
                ("ml", "backend_metadata"),
                ("ml", "pd_frame"),
                ("binning", "woe_frame"),
            ),
        ),
        (
            "ml",
            "selection_woe",
            (
                ("data", "labels"),
                ("data", "splits"),
                ("ml", "estimator"),
                ("ml", "backend_metadata"),
                ("ml", "pd_frame"),
                ("selection", "selected_woe_frame"),
                ("selection", "selected_woe_columns"),
            ),
        ),
        (
            "scorecard",
            "binning_woe",
            (
                ("data", "labels"),
                ("data", "splits"),
                ("model", "coefficients"),
                ("scorecard", "scorecard"),
                ("binning", "tables"),
                ("binning", "woe_frame"),
            ),
        ),
    ],
)
def test_requires_dinamico(targets: str, feature_source: str, esperado: tuple[Any, ...]) -> None:
    """``requires`` compone las claves correctas por targets y feature_source (§2/§6)."""
    assert step_module._requires_for(targets, feature_source) == esperado


def test_from_config_requires_usa_defaults_ml() -> None:
    """``from_config`` (sin ``MLConfig``) declara ``requires`` con la fuente por defecto binning."""
    step = ExplainStep.from_config(ExplainConfig(targets="ml"))
    assert ("binning", "woe_frame") in step.requires
    assert ("ml", "estimator") in step.requires


def test_requires_ausente_levanta_artifact_not_found() -> None:
    """Un ``requires`` ausente en el store ⇒ ``ArtifactNotFoundError`` antes de ejecutar (CT-1)."""
    study = _study(ExplainConfig(targets="ml"))
    study.artifacts._store.pop(("ml", "pd_frame"), None)
    with pytest.raises(ArtifactNotFoundError, match="pd_frame"):
        study.run_step("explain")


# ═══════════════════════════ end-to-end: 7 claves, ML + scorecard ═══════════════════════════
def test_end_to_end_both_publica_siete_claves(monkeypatch: pytest.MonkeyPatch) -> None:
    """``targets='both'`` con ML (fake shap) + scorecard publica las 7 claves e invariantes (§7)."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="both"), with_scorecard=True)
    result = study.run_step("explain")

    for key in EXPLAIN_ARTIFACTS:
        assert study.artifacts.has("explain", key)
    # ``execute`` publica una copia profunda; el resultado retornado es equivalente en contenido.
    assert study.artifacts.get("explain", "result").shap_global == result.shap_global
    # shap_global concatena ML (source_model='ml') y scorecard (source_model='scorecard').
    sources = {record.source_model for record in result.shap_global}
    assert sources == {"ml", "scorecard"}
    # scope local = holdout (6 filas), reason codes por observación.
    assert len(result.shap_local) == 6
    assert result.reason_codes == result.shap_local
    assert result.scorecard_contributions is not None
    assert not result.scorecard_contributions.empty
    # comparativa scorecard-vs-ML sobre features compartidas.
    assert {record.feature for record in result.comparison} == set(_FEATURES)
    assert result.explainer_metadata.scorecard_explained is True
    assert result.explainer_metadata.ml_explainer_kind == "tree"
    assert result.term_structure() is None
    # figura SHAP summary emitida (matplotlib perezoso).
    dependence = result.card.metric_sections["shap_dependence"]
    assert dependence["emitted"] is True
    assert isinstance(dependence["figure_png_base64"], str) and dependence["figure_png_base64"]


def test_end_to_end_reproducible_byte_a_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dos corridas con misma semilla y datos ⇒ shap_global/reason_codes idénticos (§9)."""
    _install_fake_shap(monkeypatch)
    primero = _study(ExplainConfig(targets="ml"), with_scorecard=False).run_step("explain")
    segundo = _study(ExplainConfig(targets="ml"), with_scorecard=False).run_step("explain")
    assert primero.shap_global == segundo.shap_global
    assert primero.reason_codes == segundo.reason_codes


def test_pipeline_default_ordena_explain_tras_ml_y_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """El pipeline por defecto pone ``explain`` tras ``ml``; ``Study.run`` lo corre (§2)."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="both"), with_scorecard=True)
    # el pipeline por defecto (secciones activas ml + explain) ordena ml antes que explain.
    names = study._default_step_names()
    assert names.index("ml") < names.index("explain")
    # explain corre por el orquestador (Study.run) consumiendo los artefactos aguas arriba de ml.
    study.run(["explain"])
    assert study.run_context.status == "done"
    for key in EXPLAIN_ARTIFACTS:
        assert study.artifacts.has("explain", key)
    result = study.artifacts.get("explain", "result")
    assert result.explainer_metadata.ml_explainer_kind == "tree"
    assert {record.source_model for record in result.shap_global} == {"ml", "scorecard"}


# ═══════════════════════════ targets='scorecard' sin shap ═══════════════════════════
def test_targets_scorecard_corre_sin_shap() -> None:
    """``targets='scorecard'`` explica el campeón sin importar ``shap`` (mitad analítica)."""
    sys.modules.pop("shap", None)
    study = _study(ExplainConfig(targets="scorecard"), with_ml=False, with_scorecard=True)
    result = study.run_step("explain")
    assert "shap" not in sys.modules
    assert result.scorecard_contributions is not None
    assert result.explainer_metadata.ml_explainer_kind is None
    assert result.explainer_metadata.scorecard_explained is True
    assert all(record.source_model == "scorecard" for record in result.shap_global)
    assert result.comparison == ()


@pytest.mark.skipif(
    importlib.util.find_spec("shap") is not None,
    reason="Prueba la puerta de dependencia con la ausencia REAL de shap; el job all-extras lo instala.",
)
def test_targets_ml_sin_shap_levanta_missing_dependency() -> None:
    """``targets='ml'`` sin el extra ``[explain]`` ⇒ ``MissingDependencyError`` con el extra."""
    sys.modules.pop("shap", None)
    study = _study(ExplainConfig(targets="ml"))
    with pytest.raises(MissingDependencyError, match=r"nikodym\[explain\]"):
        study.run_step("explain")


# ═══════════════════════════ degradación best-effort del scorecard ═══════════════════════════
def test_targets_both_sin_scorecard_degrada(monkeypatch: pytest.MonkeyPatch) -> None:
    """``both`` sin scorecard ⇒ ``explain_scorecard_skipped`` + ``scorecard_contributions=None``."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="both"), with_scorecard=False)
    result = study.run_step("explain")
    reglas = {
        event.payload.get("regla")
        for event in study.artifacts._audit.events  # type: ignore[attr-defined]
        if event.kind == "decision"
    }
    assert "explain_scorecard_skipped" in reglas
    assert result.scorecard_contributions is None
    assert result.explainer_metadata.scorecard_explained is False
    assert _decisions(study)["explain_targets"]["valor"]["scorecard_skipped"] is True


# ═══════════════════════════ consistencia de puntos SDD-09 (deuda B14.4(3)) ═══════════════════════
def test_scorecard_consistencia_puntos_considera_alpha_sobre_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La consistencia reconstruye ``points`` con el término ``alpha/n`` de SDD-09 §7."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="both"), with_scorecard=True)
    study.run_step("explain")
    consistency = _decisions(study)["explain_scorecard"]["valor"]["points_consistency"]
    assert consistency["verified"] is True
    assert consistency["alpha_over_n_considered"] is True
    assert consistency["max_abs_gap"] == pytest.approx(0.0, abs=1e-9)


def test_scorecard_consistencia_falla_si_puntos_ignoran_alpha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Puntos calculados **sin** ``alpha/n`` ⇒ la consistencia los detecta inconsistentes."""
    _install_fake_shap(monkeypatch)
    tabla = _scorecard_table(factor=20.0, offset=600.0, alpha=0.8, drop_alpha=True)
    study = _study(ExplainConfig(targets="both"), with_scorecard=True, scorecard_table=tabla)
    study.run_step("explain")
    consistency = _decisions(study)["explain_scorecard"]["valor"]["points_consistency"]
    assert consistency["verified"] is False
    assert consistency["max_abs_gap"] > 1e-6


def test_scorecard_consistencia_no_verificable_sin_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin ``scorecard.result`` la consistencia queda no verificable (best-effort, no rompe)."""
    _install_fake_shap(monkeypatch)
    study = _study(
        ExplainConfig(targets="scorecard"),
        with_ml=False,
        with_scorecard=True,
        with_scorecard_result=False,
    )
    study.run_step("explain")
    consistency = _decisions(study)["explain_scorecard"]["valor"]["points_consistency"]
    assert consistency["verified"] is None


# ═══════════════════════════ contrato del estimador (deuda B14.4(2)) ═══════════════════════════
def test_estimator_sin_contrato_levanta_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ml.estimator`` sin ``feature_names_in_``/``predict_pd`` ⇒ falla ruidosa (SDD-14 §8)."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"))
    study.artifacts.set("ml", "estimator", object(), overwrite=True)
    with pytest.raises(ExplainDataError, match="feature_names_in_ y predict_pd"):
        study.run_step("explain")


# ═══════════════════════════ config y validaciones de runtime ═══════════════════════════
def test_targets_ml_sin_seccion_ml_levanta_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``targets='ml'`` con artefactos ml pero **sin** sección ``ml`` ⇒ ``ExplainConfigError``."""
    _install_fake_shap(monkeypatch)
    woe = _woe_frame()
    study = Study(NikodymConfig(explain=ExplainConfig(targets="ml")))  # ml section None
    study.set_audit_sink(InMemoryAuditSink())
    study.artifacts.set("data", "labels", SimpleNamespace(target_col="target"))
    study.artifacts.set("data", "splits", SimpleNamespace(partition_col="partition"))
    study.artifacts.set("binning", "woe_frame", woe)
    study.artifacts.set("ml", "estimator", _FakeChallenger())
    study.artifacts.set("ml", "backend_metadata", SimpleNamespace(deterministic=True))
    study.artifacts.set("ml", "pd_frame", _pd_frame(woe))
    with pytest.raises(ExplainConfigError, match="challenger"):
        study.run_step("explain")


def test_feature_source_data_raw_diferido() -> None:
    """``ml.feature_source='data_raw'`` está diferido ⇒ ``ExplainConfigError`` (FALTA-DATO-ML-1)."""
    study = _study(ExplainConfig(targets="ml"))
    study.config = study.config.model_copy(update={"ml": MLConfig(feature_source="data_raw")})
    with pytest.raises(ExplainConfigError, match="data_raw"):
        study.run_step("explain")


def test_labels_sin_target_col_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """``data.labels`` sin ``target_col`` ⇒ ``ExplainDataError`` (contrato SDD-02)."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"))
    study.artifacts.set("data", "labels", SimpleNamespace(), overwrite=True)
    with pytest.raises(ExplainDataError, match="target_col"):
        study.run_step("explain")


def test_splits_sin_partition_col_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """``data.splits`` sin ``partition_col`` ⇒ ``ExplainDataError`` (contrato SDD-02)."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"))
    study.artifacts.set("data", "splits", SimpleNamespace(), overwrite=True)
    with pytest.raises(ExplainDataError, match="partition_col"):
        study.run_step("explain")


def test_woe_frame_sin_columnas_features_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ``woe_frame`` sin columnas ``*__woe`` ⇒ ``ExplainDataError`` (no hay features)."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"))
    study.artifacts.set(
        "binning",
        "woe_frame",
        pd.DataFrame({"partition": ["holdout"], "target": [1]}),
        overwrite=True,
    )
    with pytest.raises(ExplainDataError, match="features WoE"):
        study.run_step("explain")


def test_woe_frame_no_dataframe_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ``binning.woe_frame`` no tabular ⇒ ``ExplainDataError``."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"))
    study.artifacts.set("binning", "woe_frame", object(), overwrite=True)
    with pytest.raises(ExplainDataError, match="pandas"):
        study.run_step("explain")


def test_selection_columns_no_tuple_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """``selection.selected_woe_columns`` no ``tuple[str, ...]`` ⇒ ``ExplainDataError``."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"), feature_source="selection_woe")
    study.artifacts.set("selection", "selected_woe_columns", [1, 2, 3], overwrite=True)
    with pytest.raises(ExplainDataError, match="tuple"):
        study.run_step("explain")


def test_binning_tables_no_dict_levanta() -> None:
    """``binning.tables`` que no es un dict ⇒ ``ExplainDataError`` (mitad scorecard)."""
    study = _study(ExplainConfig(targets="scorecard"), with_ml=False, with_scorecard=True)
    study.artifacts.set("binning", "tables", ["no", "es", "dict"], overwrite=True)
    with pytest.raises(ExplainDataError, match="dict no vacío"):
        study.run_step("explain")


# ═══════════════════════════ scope local, background y publicación ═══════════════════════════
def test_scope_selection_woe_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """La fuente ``selection_woe`` alimenta la mitad ML con las columnas seleccionadas."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"), feature_source="selection_woe")
    result = study.run_step("explain")
    assert len(result.shap_global) == len(_FEATURES)


@pytest.mark.parametrize("strategy", ["partition", "all", "none"])
def test_scope_strategies(monkeypatch: pytest.MonkeyPatch, strategy: str) -> None:
    """Las estrategias de scope publican (o no, con 'none') las explicaciones locales (§5)."""
    _install_fake_shap(monkeypatch)
    cfg = ExplainConfig(targets="ml", local_scope=LocalScopeConfig(strategy=strategy))
    result = _study(cfg).run_step("explain")
    if strategy == "none":
        assert result.shap_local == ()
        assert result.reason_codes == ()
    else:
        assert len(result.shap_local) > 0
    assert len(result.shap_global) == len(_FEATURES)


def test_scope_sample_top_by_pd(monkeypatch: pytest.MonkeyPatch) -> None:
    """``top_by_pd`` prioriza las observaciones de mayor PD del scope (usa ``ml.pd_frame``)."""
    _install_fake_shap(monkeypatch)
    cfg = ExplainConfig(
        targets="ml",
        local_scope=LocalScopeConfig(strategy="sample", sample_size=3, top_by_pd=True),
    )
    result = _study(cfg).run_step("explain")
    assert len(result.shap_local) == 3


def test_scope_particion_vacia_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un scope local sobre una partición sin filas ⇒ ``ExplainDataError``."""
    _install_fake_shap(monkeypatch)
    cfg = ExplainConfig(targets="ml", local_scope=LocalScopeConfig(partition="inexistente"))
    with pytest.raises(ExplainDataError, match="no tiene filas"):
        _study(cfg).run_step("explain")


def test_baseline_particion_vacia_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una partición de baseline del scorecard sin filas ⇒ ``ExplainDataError``."""
    _install_fake_shap(monkeypatch)
    from nikodym.explain.config import ScorecardExplainConfig

    cfg = ExplainConfig(
        targets="both", scorecard=ScorecardExplainConfig(baseline_partition="inexistente")
    )
    with pytest.raises(ExplainDataError, match="baseline"):
        _study(cfg, with_scorecard=True).run_step("explain")


def test_publish_local_false_no_publica_locales(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``output.publish_local=False`` no se publican explicaciones locales, sólo globales."""
    _install_fake_shap(monkeypatch)
    from nikodym.explain.config import ExplainOutputConfig

    cfg = ExplainConfig(targets="ml", output=ExplainOutputConfig(publish_local=False))
    result = _study(cfg).run_step("explain")
    assert result.shap_local == ()
    assert len(result.shap_global) == len(_FEATURES)


def test_emit_figures_false_omite_png(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``emit_figures=False`` la sección dependence trae descriptores pero no PNG."""
    _install_fake_shap(monkeypatch)
    from nikodym.explain.config import ExplainOutputConfig

    cfg = ExplainConfig(targets="ml", output=ExplainOutputConfig(emit_figures=False))
    result = _study(cfg).run_step("explain")
    dependence = result.card.metric_sections["shap_dependence"]
    assert dependence["emitted"] is False
    assert "figure_png_base64" not in dependence


def test_background_partition_vacia_pasa_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ``background_partition`` sin filas se resuelve a ``None`` (no rompe con Tree exacto)."""
    _install_fake_shap(monkeypatch)
    cfg = ExplainConfig(
        targets="ml", explainer=MLExplainerConfig(background_partition="inexistente")
    )
    result = _study(cfg).run_step("explain")
    assert len(result.shap_global) == len(_FEATURES)


# ═══════════════════════════ auditoría y determinismo ═══════════════════════════
def test_determinismo_caveat_modelo_no_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si ``backend_metadata.deterministic=False`` el card hereda el caveat GBDT (§9)."""
    _install_fake_shap(monkeypatch)
    study = _study(ExplainConfig(targets="ml"), deterministic=False)
    result = study.run_step("explain")
    determinism = result.card.metric_sections["determinism"]
    assert determinism["model_deterministic"] is False
    assert determinism["byte_reproducible"] is False
    assert any("byte-reproducible" in item for item in result.card.limitations)
    assert "explain_determinism" in _decisions(study)


def test_top_n_mayor_que_features_se_acota(monkeypatch: pytest.MonkeyPatch) -> None:
    """``top_n`` > nº features se acota con ``log_decision`` (no error, §5/§8)."""
    _install_fake_shap(monkeypatch)
    from nikodym.explain.config import ReasonCodesConfig

    cfg = ExplainConfig(targets="ml", reason_codes=ReasonCodesConfig(top_n=10))
    study = _study(cfg)
    study.run_step("explain")
    decision = _decisions(study)["explain_reason_codes"]["valor"]
    assert decision["clamped"] is True
    assert decision["effective_top_n"] == len(_FEATURES)


def test_probability_space_svm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un backend sin margen log-odds (svm) degrada a probabilidad en la unidad de contribución."""
    _install_fake_shap(monkeypatch)
    cfg = ExplainConfig(targets="ml", explainer=MLExplainerConfig(check_additivity=False))
    study = _study(cfg, backend="svm", space="probability")
    result = study.run_step("explain")
    assert result.explainer_metadata.contribution_space == "probability"
    space_decision = _decisions(study)["explain_contribution_space"]["valor"]
    assert space_decision["effective_space"] == "probability"


# ═══════════════════════════ helpers puros y config ═══════════════════════════
def test_helpers_puros_bordes() -> None:
    """Cobertura de ramas borde de helpers puros (dependence vacío, ejemplo sin códigos)."""
    assert step_module._shap_dependence_section((), emit_figures=True) is None
    assert step_module._reason_codes_example(()) == []
    assert step_module._feature_source_requires("selection_woe") == [
        ("selection", "selected_woe_frame"),
        ("selection", "selected_woe_columns"),
    ]
    assert step_module._has_scaling_metadata(SimpleNamespace()) is False
    assert step_module._resolve_feature_source(None) == "binning_woe"
    # _build_card con shap_global vacío no adjunta la sección de figura (dependence None).
    card = step_module._build_card(
        ExplainConfig(),
        shap_global=(),
        shap_local=(),
        comparison=(),
        space="log_odds",
        ml_explainer_kind=None,
        scorecard_explained=False,
        explanation_deterministic=True,
        backend_metadata=None,
        seed=0,
    )
    assert "shap_dependence" not in card.metric_sections


def test_validate_features_columnas_faltantes() -> None:
    """``_validate_features`` falla si falta la partición/target o una columna de feature (§6)."""
    with pytest.raises(ExplainDataError, match="columna estructural"):
        step_module._validate_features(
            pd.DataFrame({"partition": [1], "f0__woe": [0.1]}), ("f0__woe",), "target", "partition"
        )
    with pytest.raises(ExplainDataError, match="columnas de features"):
        step_module._validate_features(
            pd.DataFrame({"partition": [1], "target": [1]}), ("f9__woe",), "target", "partition"
        )


def test_pd_hat_by_index_variantes() -> None:
    """``_pd_hat_by_index`` retorna ``None`` sin ``pd_frame``, con no-tabular o sin columna PD."""
    sin_frame = Study(NikodymConfig())
    assert step_module._pd_hat_by_index(sin_frame, ExplainConfig(), pd) is None
    no_tabular = Study(NikodymConfig())
    no_tabular.artifacts.set("ml", "pd_frame", object())
    assert step_module._pd_hat_by_index(no_tabular, ExplainConfig(), pd) is None
    sin_columna = Study(NikodymConfig())
    sin_columna.artifacts.set("ml", "pd_frame", pd.DataFrame({"x": [1]}))
    assert step_module._pd_hat_by_index(sin_columna, ExplainConfig(), pd) is None


def test_scorecard_consistencia_ramas() -> None:
    """``_scorecard_points_consistency``: tabla sin trazabilidad y result sin escalamiento."""
    sin_columnas = pd.DataFrame({"foo": [1]})
    resultado = step_module._scorecard_points_consistency(sin_columnas, Study(NikodymConfig()))
    assert resultado["verified"] is False
    tabla = _scorecard_table(factor=20.0, offset=600.0, alpha=0.8)
    study = Study(NikodymConfig())
    study.artifacts.set(
        "scorecard", "result", SimpleNamespace()
    )  # sin points_columns/factor/offset
    assert step_module._scorecard_points_consistency(tabla, study)["verified"] is None


def test_require_present_por_feature_source_re_derivada(monkeypatch: pytest.MonkeyPatch) -> None:
    """``execute`` re-deriva a la fuente real (selection) ausente ⇒ ``ArtifactNotFoundError``."""
    _install_fake_shap(monkeypatch)
    woe = _woe_frame()
    # ml.feature_source=selection_woe pero sólo hay binning.woe_frame (requires estático): el static
    # check pasa y execute re-deriva a selection.* (ausente) y falla ruidoso en _require_present.
    study = Study(
        NikodymConfig(
            explain=ExplainConfig(targets="ml"), ml=MLConfig(feature_source="selection_woe")
        )
    )
    study.set_audit_sink(InMemoryAuditSink())
    study.artifacts.set("data", "labels", SimpleNamespace(target_col="target"))
    study.artifacts.set("data", "splits", SimpleNamespace(partition_col="partition"))
    study.artifacts.set("binning", "woe_frame", woe)
    study.artifacts.set("ml", "estimator", _FakeChallenger())
    study.artifacts.set("ml", "backend_metadata", SimpleNamespace(deterministic=True))
    study.artifacts.set("ml", "pd_frame", _pd_frame(woe))
    with pytest.raises(ArtifactNotFoundError, match="selected_woe_frame"):
        study.run_step("explain")


def test_kernel_no_determinista_marca_caveat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un Kernel muestral con ``n_threads>1`` marca la explicación no byte-reproducible."""
    _install_fake_shap(monkeypatch)
    cfg = ExplainConfig(
        targets="ml",
        explainer=MLExplainerConfig(ml_explainer="kernel"),
        deterministic=False,
        n_threads=2,
    )
    result = _study(cfg).run_step("explain")
    assert result.explainer_metadata.deterministic is False
    assert any("Kernel" in item for item in result.card.limitations)


def test_explain_config_from_study_variantes() -> None:
    """``_explain_config_from_study`` acepta config del store, respaldo o dict validable."""
    fallback = ExplainConfig(targets="scorecard")
    vacio = Study(NikodymConfig())
    assert step_module._explain_config_from_study(vacio, fallback=fallback) is fallback
    con_dict = Study(NikodymConfig())
    con_dict.config = SimpleNamespace(explain={"targets": "ml"})  # type: ignore[assignment]
    assert step_module._explain_config_from_study(con_dict, fallback=fallback).targets == "ml"


def test_ml_config_from_study_variantes() -> None:
    """``_ml_config_from_study`` devuelve None sin ``ml`` y valida un dict como ``MLConfig``."""
    vacio = Study(NikodymConfig())
    assert step_module._ml_config_from_study(vacio) is None
    con_dict = Study(NikodymConfig())
    con_dict.config = SimpleNamespace(ml={"feature_source": "selection_woe"})  # type: ignore[assignment]
    assert step_module._ml_config_from_study(con_dict).feature_source == "selection_woe"


def test_binning_summary_best_effort_variantes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``binning.summary`` best-effort: ausente/no-tabular/sin columnas ⇒ ``None`` sin romper."""
    _install_fake_shap(monkeypatch)
    pd_mod = pd
    study = _study(ExplainConfig(targets="scorecard"), with_ml=False, with_scorecard=True)
    study.artifacts.set("binning", "summary", object(), overwrite=True)
    assert step_module._read_binning_summary(study, pd_mod) is None
    study.artifacts.set(
        "binning", "summary", pd_mod.DataFrame({"variable": ["f0"]}), overwrite=True
    )
    assert step_module._read_binning_summary(study, pd_mod) is None
    study.artifacts._store.pop(("binning", "summary"), None)
    assert step_module._read_binning_summary(study, pd_mod) is None


# ═══════════════════════════ estática: no reimplementa Shapley, sin optuna ni hash() ═══════════
def test_estatica_no_reimplementa_shapley_ni_optuna_ni_hash() -> None:
    """El step delega ``shap`` al motor: no lo importa, no reimplementa Shapley, ni usa hash()."""
    source = Path(step_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    # no importa shap directamente (lo hace el motor/explainers).
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "shap" not in imported
    assert "optuna" not in imported
    # no reimplementa el cálculo de valores de Shapley ni llama a shap_values.
    assert "shap_values" not in source
    assert not re.search(r"def\s+\w*shap\w*values", source, flags=re.IGNORECASE)
    # no usa el hash() builtin sensible a PYTHONHASHSEED en rutas de identidad (chequeo por AST).
    hash_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "hash"
    ]
    assert not hash_calls
