"""Tests de ``StabilityConfig`` (SDD-11 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.stability as stability_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError, NikodymError
from nikodym.stability.config import StabilityConfig
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy

GOLDEN_DEFAULT_CONFIG_HASH = "046c75d4cc1be29232900a9e709a7da9288bf6478c9a83ec04b75d95dcb7d59f"


@pytest.fixture(autouse=True)
def _capa_stability_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_STABILITY_CONFIG_CLS", StabilityConfig)


def _stability_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-11 §5."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "score_column": "score",
        "pd_column": "pd_calibrated",
        "partition_column": "partition",
        "score_direction": "higher_is_lower_risk",
        "psi_bins": 10,
        "csi_bins": 10,
        "psi_stable_threshold": 0.10,
        "psi_review_threshold": 0.25,
        "smoothing": 1e-6,
        "comparisons": ["dev_vs_holdout", "dev_vs_oot"],
        "temporal_axis": "period",
        "temporal_column": None,
        "temporal_freq": "M",
        "include_pd_stability": True,
        "csi_source": "score_points",
    }


def test_stabilityconfig_defaults_golden() -> None:
    """``StabilityConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert StabilityConfig().model_dump(mode="json") == _stability_defaults()


def test_round_trip_yaml_stabilityconfig() -> None:
    """Serializar y recargar ``StabilityConfig`` por YAML preserva igualdad exacta."""
    cfg = StabilityConfig(
        score_column="score_total",
        pd_column="pd_final",
        partition_column="particion",
        score_direction="higher_is_higher_risk",
        psi_bins=20,
        csi_bins=12,
        psi_stable_threshold=0.05,
        psi_review_threshold=0.20,
        smoothing=1e-5,
        comparisons=("dev_vs_oot",),
        temporal_axis="cohort",
        temporal_column="cohorte",
        temporal_freq="Q",
        include_pd_stability=False,
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert StabilityConfig.model_validate(raw) == cfg


def test_nikodymconfig_stability_instancia() -> None:
    """Pasar una instancia ``StabilityConfig`` a ``NikodymConfig`` la conserva."""
    stability = StabilityConfig()
    cfg = NikodymConfig(stability=stability)
    assert isinstance(cfg.stability, StabilityConfig)
    assert cfg.stability is stability


def test_nikodymconfig_stability_dict_coacciona() -> None:
    """Un dict en ``stability`` se coacciona a ``StabilityConfig`` por el hook cargado."""
    cfg = NikodymConfig(stability={"psi_bins": 20, "temporal_axis": "none"})
    assert isinstance(cfg.stability, StabilityConfig)
    assert cfg.stability.psi_bins == 20
    assert cfg.stability.temporal_axis == "none"


def test_nikodymconfig_stability_none_explicito() -> None:
    """``stability=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(stability=None).stability is None


def test_nikodymconfig_stability_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``stability`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_STABILITY_CONFIG_CLS", None)
    cfg = NikodymConfig(stability={"psi_bins": 20, "temporal_axis": "none"})
    assert cfg.stability == {"psi_bins": 20, "temporal_axis": "none"}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_stability_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``stability`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_STABILITY_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(stability=blob)


@pytest.mark.parametrize(
    "stability",
    [
        StabilityConfig(psi_bins=20),
        StabilityConfig(csi_bins=20),
        StabilityConfig(psi_stable_threshold=0.05, psi_review_threshold=0.20),
        StabilityConfig(score_column="score_total"),
        StabilityConfig(score_direction="higher_is_higher_risk"),
        StabilityConfig(include_pd_stability=False),
    ],
)
def test_config_hash_cambia_al_variar_stability(stability: StabilityConfig) -> None:
    """``stability`` no es INFRA: bins, umbrales, columnas y fuente cambian la identidad."""
    base = config_hash(NikodymConfig(stability=StabilityConfig()))
    variado = config_hash(NikodymConfig(stability=stability))
    assert "stability" not in INFRA_SECTIONS
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["stability"]))
def test_nikodym_config_strategy_genera_configs_stability_validos(
    cfg: NikodymConfig,
) -> None:
    """La estrategia pública genera configs raíz válidos con ``stability`` activo."""
    assert isinstance(cfg.stability, StabilityConfig)
    assert cfg.stability.type == "standard"
    assert loads_config(dump_config(cfg)) == cfg


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"score_column": " "}, "vacías"),
        ({"pd_column": "score"}, "colisionar"),
        ({"temporal_column": " partition "}, "colisionar"),
    ],
)
def test_columnas_invalidas_levantan_configerror(
    kwargs: dict[str, object],
    match: str,
) -> None:
    """Las columnas de stability no pueden ser vacías ni colisionantes."""
    with pytest.raises(ConfigError, match=match):
        StabilityConfig(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"psi_stable_threshold": 0.25, "psi_review_threshold": 0.25}, "menor"),
        ({"psi_stable_threshold": 0.30, "psi_review_threshold": 0.25}, "menor"),
        ({"psi_stable_threshold": math.inf}, "finito"),
        ({"smoothing": math.inf}, "finito"),
    ],
)
def test_umbrales_invalidos_levantan_configerror(
    kwargs: dict[str, object],
    match: str,
) -> None:
    """Los umbrales de PSI deben ser finitos y estar ordenados estrictamente."""
    with pytest.raises(ConfigError, match=match):
        StabilityConfig(**kwargs)


def test_csi_source_woe_bins_queda_bloqueado_con_configerror() -> None:
    """``csi_source='woe_bins'`` falla hasta ratificar el contrato de binning."""
    with pytest.raises(ConfigError, match="woe_bins"):
        StabilityConfig(csi_source="woe_bins")


def test_stability_strings_numericos_convertibles_pasan_por_pydantic() -> None:
    """Los validadores custom dejan a Pydantic coaccionar strings numéricos válidos."""
    cfg = StabilityConfig(
        psi_bins="12",  # type: ignore[arg-type]
        psi_stable_threshold="0.05",  # type: ignore[arg-type]
        psi_review_threshold="0.20",  # type: ignore[arg-type]
    )
    assert cfg.psi_bins == 12
    assert cfg.psi_stable_threshold == 0.05
    assert cfg.psi_review_threshold == 0.20


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score_direction", "alto_es_bueno"),
        ("psi_bins", 1),
        ("psi_bins", 51),
        ("csi_bins", 1),
        ("csi_bins", 51),
        ("smoothing", 0.0),
        ("comparisons", ("dev_vs_train",)),
        ("temporal_axis", "fecha"),
        ("temporal_freq", "W"),
        ("csi_source", "points"),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    field: str,
    value: object,
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        StabilityConfig(**{field: value})


def test_campos_stability_tienen_metadatos_ui() -> None:
    """Todos los campos de config stability declaran metadata de UI para SDD-23."""
    for nombre, campo in StabilityConfig.model_fields.items():
        extra = campo.json_schema_extra
        assert campo.title is not None, f"StabilityConfig.{nombre} sin title"
        assert campo.description is not None, f"StabilityConfig.{nombre} sin description"
        assert isinstance(extra, dict), f"StabilityConfig.{nombre} sin ui_*"
        assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_stability_public_api_minimo() -> None:
    """El paquete expone config/excepciones con reexport perezoso."""
    assert stability_pkg.StabilityConfig is StabilityConfig
    assert "StabilityError" in stability_pkg.__all__
    assert stability_pkg.__getattr__("StabilityError").__name__ == "StabilityError"
    with pytest.raises(AttributeError, match="Unknown"):
        stability_pkg.__getattr__("Unknown")


def test_stability_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``stability`` cuelgan de la raíz propia de la librería."""
    for name in ("StabilityError", "StabilityDataError", "StabilityMetricError"):
        error_cls = getattr(stability_pkg, name)
        assert issubclass(error_cls, NikodymError)


def test_import_stability_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.stability`` registra el hook sin arrastrar stack tabular/scoring."""
    code = (
        "import nikodym.stability, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.stability.config import StabilityConfig;"
        "bloqueados=[m for m in "
        "('pandas','pandera','pyarrow','scipy','sklearn','mlflow') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(stability={'psi_bins': 12});"
        "assert isinstance(cfg.stability, StabilityConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_stability_como_blob_opaco_sin_importar_stability() -> None:
    """El core acepta ``stability`` JSON/dict sin importar ``nikodym.stability``."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(stability={'psi_bins': 20});"
        "assert cfg.stability == {'psi_bins': 20};"
        "assert 'nikodym.stability' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_config_cls_for_domain_resuelve_stability() -> None:
    """El helper interno resuelve ``StabilityConfig`` cuando ``stability`` pobló su hook."""
    assert _config_cls_for_domain("stability") is StabilityConfig


def test_config_hash_default_con_stability_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``stability`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
