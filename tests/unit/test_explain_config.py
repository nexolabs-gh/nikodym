"""Tests de ``ExplainConfig`` (SDD-14 §5) e integración con ``NikodymConfig`` (B14.1)."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import nikodym.explain as explain_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.explain.config import (
    ExplainConfig,
    ExplainOutputConfig,
    LocalScopeConfig,
    MLExplainerConfig,
    ReasonCodesConfig,
    ScorecardExplainConfig,
)
from nikodym.explain.exceptions import (
    ExplainBackendError,
    ExplainConfigError,
    ExplainDataError,
    ExplainDeterminismError,
    ExplainError,
    ExplainExplainerError,
    ExplainReasonCodeError,
)

# Golden del config_hash por defecto tras añadir la sección computacional `explain` (B14.1).
GOLDEN_DEFAULT_CONFIG_HASH = "2dc342f1fd7be6d5ec32bca5a4c3cc4badf1da11f6876b280f7ca9662f857f3e"
# Golden anterior (antes de B14.1, con ml/tuning ya presentes); el hash DEBE moverse.
GOLDEN_PREVIO_SIN_EXPLAIN = "0be3798f51c14940597f44e8fb8ac19ec23c88f9c2ab29d94fecd800e093902e"


@pytest.fixture(autouse=True)
def _capa_explain_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_EXPLAIN_CONFIG_CLS", ExplainConfig)


def _manual_default_hash() -> str:
    """Recalcula el golden sin llamar a ``config_hash`` (canonicalización replicada)."""
    payload = NikodymConfig().model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─────────────────────────── defaults §5 ───────────────────────────


def test_explain_config_defaults_golden() -> None:
    """Los defaults defendibles de SDD-14 §5 coinciden campo a campo (D-EXP)."""
    assert ExplainConfig().model_dump(mode="json") == {
        "type": "standard",
        "schema_version": "1.0.0",
        "targets": "both",
        "explainer": {
            "ml_explainer": "auto",
            "feature_perturbation": "tree_path_dependent",
            "background_size": 100,
            "background_partition": "desarrollo",
            "check_additivity": True,
            "nsamples": "auto",
        },
        "contribution_space": "log_odds",
        "reason_codes": {
            "top_n": 5,
            "include_protective": False,
            "min_abs_contribution": 0.0,
            "adverse_direction": "increases_pd",
        },
        "local_scope": {
            "strategy": "sample",
            "sample_size": 200,
            "partition": "holdout",
            "top_by_pd": False,
        },
        "scorecard": {
            "baseline": "population_mean",
            "baseline_partition": "desarrollo",
        },
        "output": {
            "publish_local": True,
            "top_k_global": 30,
            "top_k_comparison": 15,
            "emit_figures": True,
        },
        "deterministic": True,
        "n_threads": 1,
        "target_column": "target",
        "partition_column": "partition",
        "pd_hat_column": "pd_hat",
    }


def test_explain_config_frozen_y_extra_forbid() -> None:
    """``ExplainConfig`` es inmutable y cerrado (SDD-05)."""
    cfg = ExplainConfig()
    with pytest.raises(ValidationError):
        ExplainConfig(campo_inexistente=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        cfg.targets = "ml"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (MLExplainerConfig, {"ml_explainer": "tree"}),
        (MLExplainerConfig, {"nsamples": 500}),
        (ReasonCodesConfig, {"top_n": 3, "include_protective": True}),
        (LocalScopeConfig, {"strategy": "all"}),
        (ScorecardExplainConfig, {"baseline": "neutral_zero"}),
        (ExplainOutputConfig, {"emit_figures": False}),
        (ExplainConfig, {"targets": "scorecard"}),
    ],
)
def test_sub_configs_aceptan_overrides_validos(factory: type[Any], kwargs: dict[str, Any]) -> None:
    """Cada sub-config acepta overrides válidos dentro de sus cotas."""
    instancia = factory(**kwargs)
    for clave, valor in kwargs.items():
        assert getattr(instancia, clave) == valor


# ─────────────────────────── validaciones §5 ───────────────────────────


def test_kernel_forzado_determinista_multihilo_falla() -> None:
    """Kernel forzado + determinismo byte-a-byte + n_threads>1 ⇒ ExplainConfigError (D-EXP-det)."""
    with pytest.raises(ExplainConfigError, match="kernel"):
        ExplainConfig(
            explainer=MLExplainerConfig(ml_explainer="kernel"),
            deterministic=True,
            n_threads=4,
        )


@pytest.mark.parametrize(
    "cfg_kwargs",
    [
        # Kernel forzado pero single-thread: OK (byte-reproducible).
        {
            "explainer": MLExplainerConfig(ml_explainer="kernel"),
            "deterministic": True,
            "n_threads": 1,
        },
        # Kernel forzado multihilo pero sin exigir determinismo: OK (modo performance).
        {
            "explainer": MLExplainerConfig(ml_explainer="kernel"),
            "deterministic": False,
            "n_threads": 8,
        },
        # Tree/Linear/auto exactos: multihilo NO se restringe aunque deterministic=True.
        {
            "explainer": MLExplainerConfig(ml_explainer="tree"),
            "deterministic": True,
            "n_threads": 8,
        },
        {
            "explainer": MLExplainerConfig(ml_explainer="linear"),
            "deterministic": True,
            "n_threads": 8,
        },
        {
            "explainer": MLExplainerConfig(ml_explainer="auto"),
            "deterministic": True,
            "n_threads": 8,
        },
    ],
)
def test_determinismo_solo_restringe_kernel_forzado(cfg_kwargs: dict[str, Any]) -> None:
    """Solo el Kernel forzado se restringe; Tree/Linear/auto son exactos aun multihilo (§5)."""
    cfg = ExplainConfig(**cfg_kwargs)
    assert isinstance(cfg, ExplainConfig)


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (ExplainConfig, "targets", "todo"),
        (ExplainConfig, "type", "custom"),
        (ExplainConfig, "contribution_space", "odds"),
        (ExplainConfig, "n_threads", 0),
        (ExplainConfig, "n_threads", 257),
        (MLExplainerConfig, "ml_explainer", "deep"),
        (MLExplainerConfig, "feature_perturbation", "shuffled"),
        (MLExplainerConfig, "background_size", 0),
        (MLExplainerConfig, "background_size", 100_001),
        (ReasonCodesConfig, "top_n", 0),
        (ReasonCodesConfig, "top_n", 51),
        (ReasonCodesConfig, "min_abs_contribution", -0.1),
        (ReasonCodesConfig, "adverse_direction", "decreases_pd"),
        (LocalScopeConfig, "strategy", "everything"),
        (LocalScopeConfig, "sample_size", 0),
        (LocalScopeConfig, "sample_size", 1_000_001),
        (ScorecardExplainConfig, "baseline", "mediana"),
        (ExplainOutputConfig, "top_k_global", 0),
        (ExplainOutputConfig, "top_k_comparison", 0),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    factory: type[Any],
    field: str,
    value: object,
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        factory(**{field: value})


def test_nsamples_acepta_auto_y_entero() -> None:
    """``nsamples`` admite el literal 'auto' o un entero (Kernel SHAP)."""
    assert MLExplainerConfig().nsamples == "auto"
    assert MLExplainerConfig(nsamples=256).nsamples == 256


# ─────────────────────────── round-trip YAML ───────────────────────────


def test_round_trip_yaml_preserva_config() -> None:
    """Dump→load YAML preserva targets/explainer/reason_codes (SDD-05)."""
    original = ExplainConfig(
        targets="ml",
        explainer=MLExplainerConfig(ml_explainer="tree", background_size=250),
        reason_codes=ReasonCodesConfig(top_n=7, include_protective=True),
        contribution_space="probability",
    )
    texto = yaml.safe_dump(original.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    recargado = ExplainConfig.model_validate(yaml.safe_load(texto))
    assert recargado == original


# ─────────────────────────── config_hash ───────────────────────────


def test_config_hash_default_con_explain_none_golden_no_tautologico() -> None:
    """El golden por defecto incluye ``explain=None`` con cálculo independiente."""
    assert _manual_default_hash() == GOLDEN_DEFAULT_CONFIG_HASH
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_se_movio_por_seccion_explain() -> None:
    """Añadir ``explain`` movió el golden respecto al valor previo (no es regresión)."""
    assert GOLDEN_DEFAULT_CONFIG_HASH != GOLDEN_PREVIO_SIN_EXPLAIN
    assert config_hash(NikodymConfig()) != GOLDEN_PREVIO_SIN_EXPLAIN


def test_config_hash_es_puramente_aditivo_sobre_explain() -> None:
    """Quitar ``explain:null`` del payload default reproduce el hash previo (aditivo)."""
    payload = NikodymConfig().model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    assert payload["explain"] is None
    del payload["explain"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    previo = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert previo == GOLDEN_PREVIO_SIN_EXPLAIN


def test_explain_no_esta_en_infra_sections() -> None:
    """``explain`` es computacional: no se excluye del config_hash."""
    assert "explain" not in INFRA_SECTIONS


@pytest.mark.parametrize(
    "explain",
    [
        ExplainConfig(targets="ml"),
        ExplainConfig(explainer=MLExplainerConfig(ml_explainer="tree")),
        ExplainConfig(explainer=MLExplainerConfig(background_size=250)),
        ExplainConfig(reason_codes=ReasonCodesConfig(top_n=10)),
        ExplainConfig(contribution_space="probability"),
        ExplainConfig(local_scope=LocalScopeConfig(strategy="all")),
        ExplainConfig(scorecard=ScorecardExplainConfig(baseline="neutral_zero")),
        ExplainConfig(output=ExplainOutputConfig(top_k_global=10)),
    ],
)
def test_config_hash_cambia_al_variar_explain(explain: ExplainConfig) -> None:
    """``explain`` no es INFRA: explainer/targets/top_n/unidad/background mueven el hash."""
    base = config_hash(NikodymConfig(explain=ExplainConfig()))
    variado = config_hash(NikodymConfig(explain=explain))
    assert "explain" not in INFRA_SECTIONS
    assert variado != base


# ─────────────────────── integración con NikodymConfig ───────────────────────


def test_nikodymconfig_explain_none_explicito() -> None:
    """``explain=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(explain=None).explain is None


def test_nikodymconfig_coacciona_dict_a_explain_config() -> None:
    """Con el hook cargado, un ``dict`` se coacciona a :class:`ExplainConfig`."""
    cfg = NikodymConfig(explain={"targets": "scorecard", "reason_codes": {"top_n": 8}})
    assert isinstance(cfg.explain, ExplainConfig)
    assert cfg.explain.targets == "scorecard"
    assert cfg.explain.reason_codes.top_n == 8


def test_nikodymconfig_pasa_instancia_explain_tal_cual() -> None:
    """Una instancia ya validada de ``ExplainConfig`` pasa por el validador sin recrearse."""
    explain = ExplainConfig(targets="ml")
    cfg = NikodymConfig(explain=explain)
    assert cfg.explain is explain


def test_nikodymconfig_explain_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``explain`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_EXPLAIN_CONFIG_CLS", None)
    cfg = NikodymConfig(explain={"targets": "ml"})
    assert cfg.explain == {"targets": "ml"}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_explain_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``explain`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_EXPLAIN_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(explain=blob)


# ─────────────────────────── metadata UI + API pública ───────────────────────────


def test_campos_explain_tienen_metadatos_ui() -> None:
    """Todos los campos de config de explain declaran metadata de UI para SDD-23."""
    for modelo in (
        MLExplainerConfig,
        ReasonCodesConfig,
        LocalScopeConfig,
        ScorecardExplainConfig,
        ExplainOutputConfig,
        ExplainConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_explain_public_api_minimo() -> None:
    """El paquete de explain expone config y excepciones de B14.1."""
    assert explain_pkg.ExplainConfig is ExplainConfig
    assert explain_pkg.ExplainError is ExplainError
    assert "ExplainConfig" in explain_pkg.__all__
    assert "ExplainError" in explain_pkg.__all__


def test_explain_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``explain`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        ExplainError,
        ExplainConfigError,
        ExplainDataError,
        ExplainBackendError,
        ExplainExplainerError,
        ExplainReasonCodeError,
        ExplainDeterminismError,
    ):
        assert issubclass(error_cls, NikodymError)
        assert issubclass(error_cls, ExplainError)


def test_explain_jerarquia_de_excepciones() -> None:
    """La jerarquía §4 respeta las relaciones de subclase declaradas."""
    assert issubclass(ExplainExplainerError, ExplainBackendError)
    assert not issubclass(ExplainConfigError, ExplainBackendError)


# ─────────────────────────── import liviano (núcleo) ───────────────────────────

_MODULOS_PESADOS = (
    "numpy",
    "pandas",
    "pandera",
    "pyarrow",
    "scipy",
    "sklearn",
    "shap",
    "matplotlib",
    "numba",
    "llvmlite",
    "xgboost",
    "lightgbm",
    "catboost",
    "optuna",
    "mlflow",
)


def test_import_explain_config_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.explain.config`` registra el hook sin arrastrar shap ni tabulares."""
    pesados = ",".join(f"'{m}'" for m in _MODULOS_PESADOS)
    code = (
        "import nikodym.explain, nikodym.core, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.explain.config import ExplainConfig;"
        f"bloqueados=[m for m in ({pesados},) if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(explain={'targets': 'ml'});"
        "assert isinstance(cfg.explain, ExplainConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_explain_como_blob_opaco_sin_importar_la_capa() -> None:
    """El core acepta ``explain`` JSON/dict sin importar la capa de explicabilidad."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(explain={'targets': 'ml'});"
        "assert cfg.explain == {'targets': 'ml'};"
        "assert 'nikodym.explain' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
