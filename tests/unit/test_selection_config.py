"""Tests de ``SelectionConfig`` (SDD-07 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.selection  # importa la capa: puebla el hook _SELECTION_CONFIG_CLS
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.selection.exceptions import (
    SelectionError,
    SelectionFitError,
    SelectionForcedVifConflictError,
    SelectionTransformError,
)
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy

# Golden nuevo tras añadir la sección computacional `model=None` al payload del config_hash.
GOLDEN_DEFAULT_CONFIG_HASH = "a49eb906df2316440ef7808d6a5e434339ed64f1f9fd682a2e2820a15145ee6f"


@pytest.fixture(autouse=True)
def _capa_selection_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_SELECTION_CONFIG_CLS", SelectionConfig)


def _selection_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-07 §5."""
    return {
        "type": "standard",
        "feature_columns": "*",
        "exclude_columns": [],
        "force_include": [],
        "force_exclude": [],
        "min_iv": 0.02,
        "max_iv": 0.5,
        "max_iv_action": "flag",
        "compute_univariate_metrics": True,
        "min_auc": None,
        "min_ks": None,
        "min_gini": None,
        "priority_order": ["iv", "auc", "ks", "name"],
        "correlation": {
            "enabled": True,
            "method": "pearson",
            "threshold": 0.75,
            "clustering_method": "none",
        },
        "vif": {
            "enabled": True,
            "threshold": 5.0,
            "add_intercept": True,
            "max_iterations": None,
        },
        "stability": {
            "enabled": True,
            "action": "report_only",
            "stable_threshold": 0.1,
            "review_threshold": 0.25,
            "smoothing": 1e-6,
        },
        "keep_structural_columns": True,
        "fail_if_no_features": True,
    }


def test_selectionconfig_defaults_golden() -> None:
    """``SelectionConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert SelectionConfig().model_dump(mode="json") == _selection_defaults()


def test_round_trip_yaml_selectionconfig() -> None:
    """Serializar y recargar ``SelectionConfig`` por YAML preserva igualdad exacta."""
    cfg = SelectionConfig(
        feature_columns=("ingreso", "saldo"),
        force_include=("ingreso",),
        force_exclude=("mora_ult_6m",),
        min_iv=0.03,
        max_iv_action="exclude",
        min_auc=0.6,
        correlation=CorrelationSelectionConfig(method="spearman", threshold=0.8),
        vif=VifSelectionConfig(threshold=7.0, max_iterations=4),
        stability=StabilitySelectionConfig(action="report_only", smoothing=1e-5),
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert SelectionConfig.model_validate(raw) == cfg


def test_nikodymconfig_selection_instancia() -> None:
    """Pasar una instancia ``SelectionConfig`` a ``NikodymConfig`` la conserva."""
    selection = SelectionConfig()
    cfg = NikodymConfig(selection=selection)
    assert isinstance(cfg.selection, SelectionConfig)
    assert cfg.selection is selection


def test_nikodymconfig_selection_dict_coacciona() -> None:
    """Un dict en ``selection`` se coacciona a ``SelectionConfig`` por el hook cargado."""
    cfg = NikodymConfig(selection={"min_iv": 0.04, "correlation": {"threshold": 0.8}})
    assert isinstance(cfg.selection, SelectionConfig)
    assert cfg.selection.min_iv == 0.04
    assert cfg.selection.correlation.threshold == 0.8


def test_nikodymconfig_selection_none_explicito() -> None:
    """``selection=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(selection=None).selection is None


def test_nikodymconfig_selection_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``selection`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_SELECTION_CONFIG_CLS", None)
    cfg = NikodymConfig(selection={"min_iv": 0.02, "correlation": {"threshold": 0.75}})
    assert cfg.selection == {"min_iv": 0.02, "correlation": {"threshold": 0.75}}


def test_nikodymconfig_selection_core_only_rechaza_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``selection`` rechaza sets porque romperían el ``config_hash``."""
    monkeypatch.setattr(_schema_mod, "_SELECTION_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(selection={"columnas": {"a", "b"}})


def test_config_hash_cambia_al_variar_min_iv_selection() -> None:
    """``selection`` no es INFRA: cambiar ``min_iv`` cambia la identidad computacional."""
    base = config_hash(NikodymConfig(selection=SelectionConfig()))
    variado = config_hash(NikodymConfig(selection=SelectionConfig(min_iv=0.03)))
    assert "selection" not in INFRA_SECTIONS
    assert variado != base


def test_config_hash_cambia_al_variar_correlation_threshold_selection() -> None:
    """Cambiar el umbral de correlación también cambia el ``config_hash``."""
    base = config_hash(NikodymConfig(selection=SelectionConfig()))
    variado = config_hash(
        NikodymConfig(
            selection=SelectionConfig(correlation=CorrelationSelectionConfig(threshold=0.8))
        )
    )
    assert variado != base


def test_config_hash_cambia_al_variar_vif_threshold_selection() -> None:
    """Cambiar el umbral VIF también cambia el ``config_hash``."""
    base = config_hash(NikodymConfig(selection=SelectionConfig()))
    variado = config_hash(
        NikodymConfig(selection=SelectionConfig(vif=VifSelectionConfig(threshold=7.0)))
    )
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["selection"]))
def test_nikodym_config_strategy_genera_configs_selection_validos(
    cfg: NikodymConfig,
) -> None:
    """La estrategia pública genera configs raíz válidos con ``selection`` activa y serializable."""
    assert isinstance(cfg.selection, SelectionConfig)
    assert cfg.selection.type == "standard"
    assert loads_config(dump_config(cfg)) == cfg


def test_force_include_y_force_exclude_en_conflicto_levanta_configerror() -> None:
    """Una variable no puede estar forzada a incluirse y excluirse a la vez."""
    with pytest.raises(ConfigError, match="force_include y force_exclude"):
        SelectionConfig(force_include=("ingreso",), force_exclude=("ingreso", "saldo"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_iv", -0.01),
        ("max_iv", -0.01),
        ("min_auc", 0.49),
        ("min_auc", 1.01),
        ("min_ks", -0.01),
        ("min_gini", 1.01),
    ],
)
def test_rangos_invalidos_rechazados_por_pydantic(field: str, value: object) -> None:
    """Valores fuera de rango violan restricciones Pydantic antes del runtime."""
    with pytest.raises(ValidationError):
        SelectionConfig(**{field: value})


def test_rangos_subconfig_invalidos_rechazados_por_pydantic() -> None:
    """Los sub-configs de correlación, VIF y estabilidad también exponen rangos duros."""
    with pytest.raises(ValidationError):
        CorrelationSelectionConfig(threshold=1.01)
    with pytest.raises(ValidationError):
        VifSelectionConfig(threshold=0.99)
    with pytest.raises(ValidationError):
        StabilitySelectionConfig(smoothing=0.0)


def test_campos_selection_tienen_metadatos_ui() -> None:
    """Todos los campos de config selection declaran metadata de UI para SDD-23."""
    modelos = (
        CorrelationSelectionConfig,
        VifSelectionConfig,
        StabilitySelectionConfig,
        SelectionConfig,
    )
    for modelo in modelos:
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_selection_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``selection`` cuelgan de la raíz propia de la capa."""
    for error_cls in (
        SelectionError,
        SelectionFitError,
        SelectionForcedVifConflictError,
        SelectionTransformError,
    ):
        with pytest.raises(SelectionError, match="fallo selection"):
            raise error_cls("fallo selection")


def test_import_selection_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.selection`` registra el hook sin arrastrar scoring ni stack tabular."""
    code = (
        "import nikodym.selection, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.selection.config import SelectionConfig;"
        "bloqueados=[m for m in ('sklearn','statsmodels','scipy','pandas','optbinning') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(selection={'min_iv': 0.03});"
        "assert isinstance(cfg.selection, SelectionConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_selection_como_blob_opaco_sin_importar_selection() -> None:
    """El core acepta ``selection`` JSON/dict sin importar ``nikodym.selection``."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(selection={'min_iv': 0.02});"
        "assert cfg.selection == {'min_iv': 0.02};"
        "assert 'nikodym.selection' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_schema_coacciona_selection_y_roundtrip_sin_step() -> None:
    """B7.1 cablea sólo el config: schema coacciona y el YAML round-tripea sin ``SelectionStep``."""
    cfg = NikodymConfig(selection={"min_iv": 0.04})
    recargado = loads_config(dump_config(cfg))

    assert isinstance(cfg.selection, SelectionConfig)
    assert cfg.selection.min_iv == 0.04
    assert recargado == cfg


def test_selection_getattr_desconocido_levanta_attributeerror() -> None:
    """La reexportación perezosa falla con ``AttributeError`` para nombres desconocidos."""
    atributo = "no_existe"
    with pytest.raises(AttributeError, match="no_existe"):
        getattr(nikodym.selection, atributo)


def test_selection_getattr_carga_export_perezoso(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ruta positiva de ``__getattr__`` carga y cachea un símbolo bajo demanda."""
    atributo = "SelectionConfigLazy"
    monkeypatch.setitem(
        nikodym.selection._LAZY_EXPORTS,
        atributo,
        ("nikodym.selection.config", "SelectionConfig"),
    )
    try:
        assert getattr(nikodym.selection, atributo) is SelectionConfig
        assert getattr(nikodym.selection, atributo) is SelectionConfig
    finally:
        monkeypatch.delattr(nikodym.selection, atributo, raising=False)


def test_config_cls_for_domain_resuelve_selection() -> None:
    """El helper interno resuelve ``SelectionConfig`` cuando ``selection`` pobló su hook."""
    assert _config_cls_for_domain("selection") is SelectionConfig


def test_config_hash_default_con_selection_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``selection`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
