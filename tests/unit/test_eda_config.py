"""Tests de ``EdaConfig`` (SDD-27 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.eda  # noqa: F401  — importa la capa: puebla el hook _EDA_CONFIG_CLS
from nikodym.core.config import INFRA_SECTIONS, NikodymConfig, config_hash, loads_config
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError
from nikodym.eda.config import (
    DefaultRateConfig,
    EdaConfig,
    QualityConfig,
    SamplingConfig,
    TemporalStabilityConfig,
    UnivariateConfig,
)
from nikodym.eda.exceptions import EdaError
from nikodym.testing.strategies import nikodym_config_strategy


@pytest.fixture(autouse=True)
def _capa_eda_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado (vista con capa ``eda``) sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_EDA_CONFIG_CLS", EdaConfig)


def _eda_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-27 §5."""
    return {
        "type": "standard",
        "analysis_partition": "desarrollo",
        "default_rate": {
            "axis": "period",
            "date_col": None,
            "period_freq": "M",
            "cohort_col": None,
            "min_obs_per_period": 50,
        },
        "stability": {
            "metric": "cv",
            "threshold": 0.25,
        },
        "univariate": {
            "n_quantile_bins": 10,
            "rare_level_threshold": 0.01,
            "compute_descriptive_iv": False,
            "columns": None,
        },
        "quality": {
            "near_constant_threshold": 0.99,
            "high_cardinality_threshold": 50,
        },
        "sampling": {
            "enabled": False,
            "max_rows": 500_000,
        },
    }


def test_edaconfig_defaults_golden() -> None:
    """``EdaConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert EdaConfig().model_dump(mode="json") == _eda_defaults()


def test_round_trip_yaml_edaconfig() -> None:
    """Serializar y recargar ``EdaConfig`` por YAML preserva igualdad exacta."""
    cfg = EdaConfig(
        analysis_partition="holdout",
        default_rate=DefaultRateConfig(axis="cohort", cohort_col="vintage"),
        univariate=UnivariateConfig(n_quantile_bins=8, columns=("ingreso", "saldo")),
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert EdaConfig.model_validate(raw) == cfg


def test_nikodymconfig_eda_instancia() -> None:
    """Pasar una instancia ``EdaConfig`` a ``NikodymConfig`` la conserva."""
    eda = EdaConfig()
    cfg = NikodymConfig(eda=eda)
    assert isinstance(cfg.eda, EdaConfig)
    assert cfg.eda is eda


def test_nikodymconfig_eda_dict_coacciona() -> None:
    """Un dict en ``eda`` se coacciona a ``EdaConfig`` por el hook cargado."""
    cfg = NikodymConfig(eda={"univariate": {"n_quantile_bins": 12}})
    assert isinstance(cfg.eda, EdaConfig)
    assert cfg.eda.univariate.n_quantile_bins == 12


def test_nikodymconfig_eda_none_explicito() -> None:
    """``eda=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(eda=None).eda is None


def test_nikodymconfig_eda_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``eda`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_EDA_CONFIG_CLS", None)
    cfg = NikodymConfig(eda={"analysis_partition": "desarrollo"})
    assert cfg.eda == {"analysis_partition": "desarrollo"}


def test_nikodymconfig_eda_core_only_rechaza_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``eda`` rechaza sets porque romperían el ``config_hash``."""
    monkeypatch.setattr(_schema_mod, "_EDA_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(eda={"columnas": {"a", "b"}})


def test_config_hash_cambia_al_variar_campo_eda() -> None:
    """``eda`` no es INFRA: cambiar un campo de EDA cambia la identidad computacional."""
    base = config_hash(NikodymConfig(eda=EdaConfig()))
    variado = config_hash(
        NikodymConfig(eda=EdaConfig(univariate=UnivariateConfig(n_quantile_bins=20)))
    )
    assert "eda" not in INFRA_SECTIONS
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["eda"]))
def test_nikodym_config_strategy_genera_configs_eda_validos(cfg: NikodymConfig) -> None:
    """La estrategia pública genera configs raíz válidos con sección ``eda`` activa."""
    assert isinstance(cfg.eda, EdaConfig)
    assert cfg.eda.type == "standard"


def test_n_quantile_bins_uno_rechazado_por_pydantic() -> None:
    """``n_quantile_bins=1`` viola ``ge=2`` y se rechaza antes del runtime."""
    with pytest.raises(ValidationError):
        UnivariateConfig(n_quantile_bins=1)


def test_n_quantile_bins_uno_rechazado_por_loader() -> None:
    """El loader YAML envuelve la validación de ``eda`` inválido en ``ConfigError``."""
    with pytest.raises(ConfigError):
        loads_config(
            """
eda:
  univariate:
    n_quantile_bins: 1
"""
        )


def test_campos_eda_tienen_metadatos_ui() -> None:
    """Todos los campos de config EDA declaran metadata de UI para SDD-23."""
    modelos = (
        DefaultRateConfig,
        TemporalStabilityConfig,
        UnivariateConfig,
        QualityConfig,
        SamplingConfig,
        EdaConfig,
    )
    for modelo in modelos:
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_eda_error_desciende_de_nikodym_error() -> None:
    """``EdaError`` es la raíz de errores propios de la capa EDA."""
    with pytest.raises(EdaError, match="fallo descriptivo"):
        raise EdaError("fallo descriptivo")


def test_import_core_liviano_e_import_eda_registra_step_en_proceso_fresco() -> None:
    """``core`` sigue liviano; ``import nikodym.eda`` registra ``EdaStep``."""
    code = (
        "import nikodym.core, sys;"
        "bloqueados=[m for m in ('pandas','pandera','pyarrow') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "import nikodym.eda;"
        "from nikodym.core.registry import REGISTRY;"
        "assert REGISTRY.resolve('eda','standard').__name__ == 'EdaStep'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
