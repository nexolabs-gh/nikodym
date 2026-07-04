"""Tests de ``PerformanceConfig`` (SDD-11 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.performance as performance_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError
from nikodym.performance.config import PerformanceConfig
from nikodym.performance.exceptions import (
    PerformanceDataError,
    PerformanceError,
    PerformanceMetricError,
)
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy

GOLDEN_DEFAULT_CONFIG_HASH = "0be3798f51c14940597f44e8fb8ac19ec23c88f9c2ab29d94fecd800e093902e"


@pytest.fixture(autouse=True)
def _capa_performance_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_PERFORMANCE_CONFIG_CLS", PerformanceConfig)


def _performance_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-11 §5."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "score_column": "score",
        "pd_column": "pd_calibrated",
        "target_column": "target",
        "partition_column": "partition",
        "score_direction": "higher_is_lower_risk",
        "evaluation_source": "pd_calibrated",
        "partitions": ["desarrollo", "holdout", "oot"],
        "n_deciles": 10,
        "min_rows_per_partition": 30,
        "min_events_per_partition": 1,
        "optional_thresholds": {},
    }


def test_performanceconfig_defaults_golden() -> None:
    """``PerformanceConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert PerformanceConfig().model_dump(mode="json") == _performance_defaults()


def test_round_trip_yaml_performanceconfig() -> None:
    """Serializar y recargar ``PerformanceConfig`` por YAML preserva igualdad exacta."""
    cfg = PerformanceConfig(
        score_column="score_total",
        pd_column="pd_final",
        target_column="malo_12m",
        partition_column="particion",
        score_direction="higher_is_higher_risk",
        evaluation_source="score",
        partitions=("desarrollo", "oot"),
        n_deciles=20,
        min_rows_per_partition=100,
        min_events_per_partition=5,
        optional_thresholds={"auc_min": 0.6, "ks_min": 0.2},
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert PerformanceConfig.model_validate(raw) == cfg


def test_nikodymconfig_performance_instancia() -> None:
    """Pasar una instancia ``PerformanceConfig`` a ``NikodymConfig`` la conserva."""
    performance = PerformanceConfig()
    cfg = NikodymConfig(performance=performance)
    assert isinstance(cfg.performance, PerformanceConfig)
    assert cfg.performance is performance


def test_nikodymconfig_performance_dict_coacciona() -> None:
    """Un dict en ``performance`` se coacciona a ``PerformanceConfig`` por el hook cargado."""
    cfg = NikodymConfig(performance={"n_deciles": 20, "evaluation_source": "score"})
    assert isinstance(cfg.performance, PerformanceConfig)
    assert cfg.performance.n_deciles == 20
    assert cfg.performance.evaluation_source == "score"


def test_nikodymconfig_performance_none_explicito() -> None:
    """``performance=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(performance=None).performance is None


def test_nikodymconfig_performance_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``performance`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_PERFORMANCE_CONFIG_CLS", None)
    cfg = NikodymConfig(performance={"n_deciles": 20, "evaluation_source": "score"})
    assert cfg.performance == {"n_deciles": 20, "evaluation_source": "score"}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_performance_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``performance`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_PERFORMANCE_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(performance=blob)


@pytest.mark.parametrize(
    "performance",
    [
        PerformanceConfig(n_deciles=20),
        PerformanceConfig(optional_thresholds={"auc_min": 0.6}),
        PerformanceConfig(evaluation_source="score"),
        PerformanceConfig(score_direction="higher_is_higher_risk"),
    ],
)
def test_config_hash_cambia_al_variar_performance(performance: PerformanceConfig) -> None:
    """``performance`` no es INFRA: deciles, umbrales y ranking cambian la identidad."""
    base = config_hash(NikodymConfig(performance=PerformanceConfig()))
    variado = config_hash(NikodymConfig(performance=performance))
    assert "performance" not in INFRA_SECTIONS
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["performance"]))
def test_nikodym_config_strategy_genera_configs_performance_validos(
    cfg: NikodymConfig,
) -> None:
    """La estrategia pública genera configs raíz válidos con ``performance`` activo."""
    assert isinstance(cfg.performance, PerformanceConfig)
    assert cfg.performance.type == "standard"
    assert loads_config(dump_config(cfg)) == cfg


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"score_column": " "}, "vacías"),
        ({"pd_column": "score"}, "colisionar"),
        ({"target_column": " partition "}, "colisionar"),
    ],
)
def test_columnas_invalidas_levantan_configerror(
    kwargs: dict[str, object],
    match: str,
) -> None:
    """Las columnas de performance no pueden ser vacías ni colisionantes."""
    with pytest.raises(ConfigError, match=match):
        PerformanceConfig(**kwargs)


@pytest.mark.parametrize(
    ("optional_thresholds", "match"),
    [
        ({"brier_max": 0.1}, "claves documentadas"),
        ({"auc_min": math.inf}, "finitos"),
        ({"auc_min": math.nan}, "finitos"),
        ({"auc_min": True}, "finitos"),
    ],
)
def test_optional_thresholds_invalidos_levantan_configerror(
    optional_thresholds: dict[str, object],
    match: str,
) -> None:
    """``optional_thresholds`` admite solo la allowlist documentada y valores finitos."""
    with pytest.raises(ConfigError, match=match):
        PerformanceConfig(optional_thresholds=optional_thresholds)


@pytest.mark.parametrize("optional_thresholds", [None, [("auc_min", 0.6)]])
def test_optional_thresholds_shape_invalido_pasa_a_pydantic(
    optional_thresholds: object,
) -> None:
    """Shapes no mapeables quedan en manos de Pydantic y no se silencian."""
    with pytest.raises(ValidationError):
        PerformanceConfig(optional_thresholds=optional_thresholds)


def test_performance_optional_thresholds_after_validator_defensiva() -> None:
    """El validador final protege instancias construidas por vías bajas."""
    cfg_clave = PerformanceConfig.model_construct(optional_thresholds={"brier_max": 0.1})
    with pytest.raises(ConfigError, match="claves documentadas"):
        cfg_clave._check_invariantes()

    cfg_finito = PerformanceConfig.model_construct(optional_thresholds={"auc_min": math.inf})
    with pytest.raises(ConfigError, match=r"optional_thresholds\.auc_min"):
        cfg_finito._check_invariantes()


def test_performance_strings_numericos_convertibles_pasan_por_pydantic() -> None:
    """Los validadores custom dejan a Pydantic coaccionar strings numéricos válidos."""
    cfg = PerformanceConfig(
        n_deciles="12",  # type: ignore[arg-type]
        optional_thresholds={"auc_min": "0.6"},  # type: ignore[dict-item]
    )
    assert cfg.n_deciles == 12
    assert cfg.optional_thresholds == {"auc_min": 0.6}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score_direction", "alto_es_bueno"),
        ("evaluation_source", "pd_raw"),
        ("partitions", ("train",)),
        ("n_deciles", 1),
        ("n_deciles", 51),
        ("min_rows_per_partition", 0),
        ("min_events_per_partition", 0),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    field: str,
    value: object,
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        PerformanceConfig(**{field: value})


def test_campos_performance_tienen_metadatos_ui() -> None:
    """Todos los campos de config performance declaran metadata de UI para SDD-23."""
    for nombre, campo in PerformanceConfig.model_fields.items():
        extra = campo.json_schema_extra
        assert campo.title is not None, f"PerformanceConfig.{nombre} sin title"
        assert campo.description is not None, f"PerformanceConfig.{nombre} sin description"
        assert isinstance(extra, dict), f"PerformanceConfig.{nombre} sin ui_*"
        assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_performance_public_api_minimo() -> None:
    """El paquete expone config/excepciones y el step perezoso en B11.4."""
    assert performance_pkg.PerformanceConfig is PerformanceConfig
    assert "PerformanceStep" in performance_pkg.__all__


def test_performance_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``performance`` cuelgan de la raíz propia de la capa."""
    for error_cls in (PerformanceError, PerformanceDataError, PerformanceMetricError):
        with pytest.raises(PerformanceError, match="fallo performance"):
            raise error_cls("fallo performance")


def test_import_performance_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.performance`` registra el hook sin arrastrar stack tabular/scoring."""
    code = (
        "import nikodym.performance, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.performance.config import PerformanceConfig;"
        "bloqueados=[m for m in "
        "('pandas','pandera','pyarrow','scipy','sklearn','mlflow') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(performance={'n_deciles': 12});"
        "assert isinstance(cfg.performance, PerformanceConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_performance_como_blob_opaco_sin_importar_performance() -> None:
    """El core acepta ``performance`` JSON/dict sin importar ``nikodym.performance``."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(performance={'n_deciles': 20});"
        "assert cfg.performance == {'n_deciles': 20};"
        "assert 'nikodym.performance' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_config_cls_for_domain_resuelve_performance() -> None:
    """El helper interno resuelve ``PerformanceConfig`` cuando ``performance`` pobló su hook."""
    assert _config_cls_for_domain("performance") is PerformanceConfig


def test_config_hash_default_con_performance_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``performance`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
