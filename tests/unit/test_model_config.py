"""Tests de ``ModelConfig`` (SDD-08 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.model  # importa la capa: puebla el hook _MODEL_CONFIG_CLS
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError
from nikodym.model.config import (
    IvContributionConfig,
    ModelConfig,
    SignPolicyConfig,
    StepwiseConfig,
)
from nikodym.model.exceptions import ModelError, ModelFitError, ModelTransformError
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy

GOLDEN_DEFAULT_CONFIG_HASH = "33e1dcce02a205cb2bc0fcfb1341c80b5251c5b2e6e478e4ecd392f67f0cf746"


@pytest.fixture(autouse=True)
def _capa_model_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_MODEL_CONFIG_CLS", ModelConfig)


def _model_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-08 §5."""
    return {
        "type": "standard",
        "engine": "logit",
        "fit_intercept": True,
        "optimizer": "newton",
        "fit_maxiter": 100,
        "tol": 1e-8,
        "alpha": 0.05,
        "stepwise": {
            "enabled": True,
            "direction": "bidirectional",
            "criterion": "wald_pvalue",
            "entry_p_value": 0.05,
            "exit_p_value": 0.05,
            "max_iter": 100,
            "min_features": 1,
        },
        "sign_policy": {
            "expected_beta_sign": "negative",
            "action": "exclude",
            "fail_on_forced_inverted": True,
        },
        "iv_contribution": {"threshold": 0.9, "action": "exclude"},
        "force_include": [],
        "force_exclude": [],
        "fail_if_no_features": True,
    }


def test_modelconfig_defaults_golden() -> None:
    """``ModelConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert ModelConfig().model_dump(mode="json") == _model_defaults()


def test_round_trip_yaml_modelconfig() -> None:
    """Serializar y recargar ``ModelConfig`` por YAML preserva igualdad exacta."""
    cfg = ModelConfig(
        engine="glm_binomial",
        optimizer="bfgs",
        fit_maxiter=150,
        tol=1e-7,
        alpha=0.1,
        stepwise=StepwiseConfig(
            direction="forward",
            criterion="both",
            entry_p_value=0.04,
            exit_p_value=0.08,
            max_iter=25,
            min_features=2,
        ),
        sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
        iv_contribution=IvContributionConfig(threshold=0.85, action="fail"),
        force_include=("ingreso",),
        force_exclude=("mora_ult_6m",),
        fail_if_no_features=False,
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert ModelConfig.model_validate(raw) == cfg


def test_stepwise_direction_none_normaliza_enabled_false() -> None:
    """``direction='none'`` es alias explícito de ``enabled=False``."""
    cfg = StepwiseConfig(direction="none", enabled=True)
    assert cfg.direction == "none"
    assert cfg.enabled is False


def test_stepwise_validator_acepta_instancia_existente() -> None:
    """La normalización deja pasar instancias ya validadas sin reconstruirlas."""
    cfg = StepwiseConfig()
    assert StepwiseConfig._normaliza_direction_none(cfg) is cfg


def test_nikodymconfig_model_instancia() -> None:
    """Pasar una instancia ``ModelConfig`` a ``NikodymConfig`` la conserva."""
    model = ModelConfig()
    cfg = NikodymConfig(model=model)
    assert isinstance(cfg.model, ModelConfig)
    assert cfg.model is model


def test_nikodymconfig_model_dict_coacciona() -> None:
    """Un dict en ``model`` se coacciona a ``ModelConfig`` por el hook cargado."""
    cfg = NikodymConfig(
        model={
            "engine": "glm_binomial",
            "stepwise": {"entry_p_value": 0.04},
            "iv_contribution": {"threshold": 0.8},
        }
    )
    assert isinstance(cfg.model, ModelConfig)
    assert cfg.model.engine == "glm_binomial"
    assert cfg.model.stepwise.entry_p_value == 0.04
    assert cfg.model.iv_contribution.threshold == 0.8


def test_nikodymconfig_model_none_explicito() -> None:
    """``model=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(model=None).model is None


def test_nikodymconfig_model_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``model`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_MODEL_CONFIG_CLS", None)
    cfg = NikodymConfig(model={"engine": "logit", "stepwise": {"entry_p_value": 0.05}})
    assert cfg.model == {"engine": "logit", "stepwise": {"entry_p_value": 0.05}}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_model_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``model`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_MODEL_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(model=blob)


@pytest.mark.parametrize(
    "model",
    [
        ModelConfig(engine="glm_binomial"),
        ModelConfig(stepwise=StepwiseConfig(entry_p_value=0.04)),
        ModelConfig(sign_policy=SignPolicyConfig(action="flag")),
        ModelConfig(iv_contribution=IvContributionConfig(threshold=0.85)),
    ],
)
def test_config_hash_cambia_al_variar_model(model: ModelConfig) -> None:
    """``model`` no es INFRA: engine, stepwise, signos e IV cambian la identidad."""
    base = config_hash(NikodymConfig(model=ModelConfig()))
    variado = config_hash(NikodymConfig(model=model))
    assert "model" not in INFRA_SECTIONS
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["model"]))
def test_nikodym_config_strategy_genera_configs_model_validos(cfg: NikodymConfig) -> None:
    """La estrategia pública genera configs raíz válidos con ``model`` activo y serializable."""
    assert isinstance(cfg.model, ModelConfig)
    assert cfg.model.type == "standard"
    assert loads_config(dump_config(cfg)) == cfg


def test_force_include_y_force_exclude_en_conflicto_levanta_configerror() -> None:
    """Una variable no puede estar forzada a incluirse y excluirse a la vez."""
    with pytest.raises(ConfigError, match="force_include y force_exclude"):
        ModelConfig(force_include=("ingreso",), force_exclude=("ingreso", "saldo"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("engine", "sklearn"),
        ("optimizer", "powell"),
        ("fit_maxiter", 0),
        ("tol", 0.0),
        ("alpha", 0.0),
        ("alpha", 1.0),
    ],
)
def test_rangos_y_literales_invalidos_rechazados_por_pydantic(
    field: str,
    value: object,
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        ModelConfig(**{field: value})


def test_rangos_subconfig_invalidos_rechazados_por_pydantic() -> None:
    """Los sub-configs de stepwise, signos e IV también exponen rangos/literales duros."""
    with pytest.raises(ValidationError):
        StepwiseConfig(entry_p_value=-0.01)
    with pytest.raises(ValidationError):
        StepwiseConfig(min_features=0)
    with pytest.raises(ValidationError):
        SignPolicyConfig(action="warn")
    with pytest.raises(ValidationError):
        IvContributionConfig(threshold=1.01)


def test_campos_model_tienen_metadatos_ui() -> None:
    """Todos los campos de config model declaran metadata de UI para SDD-23."""
    modelos = (StepwiseConfig, SignPolicyConfig, IvContributionConfig, ModelConfig)
    for modelo in modelos:
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_model_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``model`` cuelgan de la raíz propia de la capa."""
    for error_cls in (ModelError, ModelFitError, ModelTransformError):
        with pytest.raises(ModelError, match="fallo model"):
            raise error_cls("fallo model")


def test_import_model_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.model`` registra el hook sin arrastrar scoring ni stack tabular."""
    code = (
        "import nikodym.model, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.model.config import ModelConfig;"
        "bloqueados=[m for m in ('statsmodels','sklearn','scipy','pandas') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(model={'engine': 'glm_binomial'});"
        "assert isinstance(cfg.model, ModelConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_model_como_blob_opaco_sin_importar_model() -> None:
    """El core acepta ``model`` JSON/dict sin importar ``nikodym.model``."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(model={'engine': 'logit'});"
        "assert cfg.model == {'engine': 'logit'};"
        "assert 'nikodym.model' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_model_getattr_desconocido_levanta_attributeerror() -> None:
    """La reexportación perezosa falla con ``AttributeError`` para nombres desconocidos."""
    atributo = "no_existe"
    with pytest.raises(AttributeError, match="no_existe"):
        getattr(nikodym.model, atributo)


def test_model_getattr_carga_export_perezoso(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ruta positiva de ``__getattr__`` carga y cachea un símbolo bajo demanda."""
    atributo = "ModelConfigLazy"
    monkeypatch.setitem(
        nikodym.model._LAZY_EXPORTS,
        atributo,
        ("nikodym.model.config", "ModelConfig"),
    )
    try:
        assert getattr(nikodym.model, atributo) is ModelConfig
        assert getattr(nikodym.model, atributo) is ModelConfig
    finally:
        monkeypatch.delattr(nikodym.model, atributo, raising=False)


def test_config_cls_for_domain_resuelve_model() -> None:
    """El helper interno resuelve ``ModelConfig`` cuando ``model`` pobló su hook."""
    assert _config_cls_for_domain("model") is ModelConfig


def test_config_hash_default_con_model_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``model`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
