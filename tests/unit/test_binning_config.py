"""Tests de ``BinningConfig`` (SDD-06 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.binning  # importa la capa: puebla el hook _BINNING_CONFIG_CLS
from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.exceptions import BinningError, BinningFitError, BinningTransformError
from nikodym.core.config import INFRA_SECTIONS, NikodymConfig, config_hash, loads_config
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy


@pytest.fixture(autouse=True)
def _capa_binning_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_BINNING_CONFIG_CLS", BinningConfig)


def _binning_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-06 §5."""
    return {
        "type": "standard",
        "feature_columns": "*",
        "exclude_columns": [],
        "categorical_columns": [],
        "variable_overrides": [],
        "max_n_prebins": 20,
        "min_prebin_size": 0.05,
        "min_n_bins": None,
        "max_n_bins": 8,
        "min_bin_size": 0.05,
        "min_bin_n_event": 1,
        "min_bin_n_nonevent": 1,
        "monotonic_trend": "auto_asc_desc",
        "min_event_rate_diff": 0.0,
        "max_pvalue": None,
        "max_pvalue_policy": "consecutive",
        "solver": "mip",
        "mip_solver": "bop",
        "time_limit": 100,
        "require_optimal": True,
        "n_jobs": None,
        "special_handling": "separate",
        "metric_special": "empirical",
        "metric_missing": "empirical",
        "cat_cutoff": 0.01,
        "cat_unknown": None,
        "split_digits": None,
        "output_suffix": "__woe",
        "keep_structural_columns": True,
        "fail_on_non_binnable": False,
    }


def test_binningconfig_defaults_golden() -> None:
    """``BinningConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert BinningConfig().model_dump(mode="json") == _binning_defaults()


def test_round_trip_yaml_binningconfig() -> None:
    """Serializar y recargar ``BinningConfig`` por YAML preserva igualdad exacta."""
    cfg = BinningConfig(
        feature_columns=("ingreso", "saldo"),
        categorical_columns=("segmento",),
        variable_overrides=(
            VariableBinningConfig(
                name="saldo",
                dtype="numerical",
                monotonic_trend="descending",
                max_n_bins=6,
                min_bin_size=0.1,
            ),
        ),
        max_n_bins=6,
        monotonic_trend="ascending",
        n_jobs=1,
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert BinningConfig.model_validate(raw) == cfg


def test_nikodymconfig_binning_instancia() -> None:
    """Pasar una instancia ``BinningConfig`` a ``NikodymConfig`` la conserva."""
    binning = BinningConfig()
    cfg = NikodymConfig(binning=binning)
    assert isinstance(cfg.binning, BinningConfig)
    assert cfg.binning is binning


def test_nikodymconfig_binning_dict_coacciona() -> None:
    """Un dict en ``binning`` se coacciona a ``BinningConfig`` por el hook cargado."""
    cfg = NikodymConfig(binning={"max_n_bins": 7})
    assert isinstance(cfg.binning, BinningConfig)
    assert cfg.binning.max_n_bins == 7


def test_nikodymconfig_binning_none_explicito() -> None:
    """``binning=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(binning=None).binning is None


def test_nikodymconfig_binning_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``binning`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_BINNING_CONFIG_CLS", None)
    cfg = NikodymConfig(binning={"max_n_bins": 8, "monotonic_trend": "auto_asc_desc"})
    assert cfg.binning == {"max_n_bins": 8, "monotonic_trend": "auto_asc_desc"}


def test_nikodymconfig_binning_core_only_rechaza_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``binning`` rechaza sets porque romperían el ``config_hash``."""
    monkeypatch.setattr(_schema_mod, "_BINNING_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(binning={"columnas": {"a", "b"}})


def test_config_hash_cambia_al_variar_max_n_bins_binning() -> None:
    """``binning`` no es INFRA: cambiar ``max_n_bins`` cambia la identidad computacional."""
    base = config_hash(NikodymConfig(binning=BinningConfig()))
    variado = config_hash(NikodymConfig(binning=BinningConfig(max_n_bins=10)))
    assert "binning" not in INFRA_SECTIONS
    assert variado != base


def test_config_hash_cambia_al_variar_monotonic_trend_binning() -> None:
    """Cambiar monotonía de ``binning`` también cambia el ``config_hash``."""
    base = config_hash(NikodymConfig(binning=BinningConfig()))
    variado = config_hash(NikodymConfig(binning=BinningConfig(monotonic_trend="ascending")))
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["binning"]))
def test_nikodym_config_strategy_genera_configs_binning_validos(cfg: NikodymConfig) -> None:
    """La estrategia pública genera configs raíz válidos con sección ``binning`` activa."""
    assert isinstance(cfg.binning, BinningConfig)
    assert cfg.binning.type == "standard"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_n_bins", 1),
        ("min_bin_size", -0.01),
        ("min_bin_size", 0.51),
        ("max_n_prebins", 1),
        ("min_prebin_size", 0.0),
        ("time_limit", 0),
        ("split_digits", 11),
    ],
)
def test_rangos_invalidos_rechazados_por_pydantic(field: str, value: object) -> None:
    """Valores fuera de rango violan restricciones Pydantic antes del runtime."""
    with pytest.raises(ValidationError):
        BinningConfig(**{field: value})


def test_rango_minimo_mayor_que_maximo_rechazado() -> None:
    """``min_n_bins`` no puede superar ``max_n_bins``."""
    with pytest.raises(ValidationError, match="min_n_bins"):
        BinningConfig(min_n_bins=10, max_n_bins=3)


def test_rango_invalido_rechazado_por_loader() -> None:
    """El loader YAML envuelve la validación de ``binning`` inválido en ``ConfigError``."""
    with pytest.raises(ConfigError):
        loads_config(
            """
binning:
  max_n_bins: 1
"""
        )


def test_campos_binning_tienen_metadatos_ui() -> None:
    """Todos los campos de config binning declaran metadata de UI para SDD-23."""
    for modelo in (VariableBinningConfig, BinningConfig):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_binning_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``binning`` cuelgan de la raíz propia de la capa."""
    for error_cls in (BinningError, BinningFitError, BinningTransformError):
        with pytest.raises(BinningError, match="fallo binning"):
            raise error_cls("fallo binning")


def test_import_binning_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.binning`` registra el hook sin arrastrar scoring ni stack tabular."""
    code = (
        "import nikodym.binning, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.binning.config import BinningConfig;"
        "bloqueados=[m for m in ('optbinning','sklearn','pandas','pandera','pyarrow') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(binning={'max_n_bins': 6});"
        "assert isinstance(cfg.binning, BinningConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_binning_como_blob_opaco_sin_importar_binning() -> None:
    """El core acepta ``binning`` JSON/dict sin importar ``nikodym.binning``."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(binning={'max_n_bins': 8});"
        "assert cfg.binning == {'max_n_bins': 8};"
        "assert 'nikodym.binning' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_binning_getattr_desconocido_levanta_attributeerror() -> None:
    """La reexportación perezosa falla con ``AttributeError`` para nombres desconocidos."""
    atributo = "no_existe"
    with pytest.raises(AttributeError, match="no_existe"):
        getattr(nikodym.binning, atributo)


def test_binning_getattr_carga_export_perezoso(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ruta positiva de ``__getattr__`` carga y cachea un símbolo bajo demanda."""
    atributo = "BinningConfigLazy"
    monkeypatch.setitem(
        nikodym.binning._LAZY_EXPORTS,
        atributo,
        ("nikodym.binning.config", "BinningConfig"),
    )
    try:
        assert getattr(nikodym.binning, atributo) is BinningConfig
        assert getattr(nikodym.binning, atributo) is BinningConfig
    finally:
        monkeypatch.delattr(nikodym.binning, atributo, raising=False)


def test_config_cls_for_domain_resuelve_binning() -> None:
    """El helper interno resuelve ``BinningConfig`` cuando ``binning`` pobló su hook."""
    assert _config_cls_for_domain("binning") is BinningConfig
