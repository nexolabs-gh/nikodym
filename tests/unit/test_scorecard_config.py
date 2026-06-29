"""Tests de ``ScorecardConfig`` (SDD-09 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.scorecard  # importa la capa: puebla el hook _SCORECARD_CONFIG_CLS
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError
from nikodym.scorecard.config import PointOverrideConfig, ScorecardConfig
from nikodym.scorecard.exceptions import (
    ScorecardError,
    ScorecardFitError,
    ScorecardTransformError,
)
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy

GOLDEN_DEFAULT_CONFIG_HASH = "14f7bbc8647aa4c4babf1011d35e2f55d22412026ead9318aab2cad54383bbe6"


@pytest.fixture(autouse=True)
def _capa_scorecard_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_SCORECARD_CONFIG_CLS", ScorecardConfig)


def _scorecard_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-09 §5."""
    return {
        "type": "standard",
        "pdo": 20.0,
        "target_score": 600.0,
        "target_odds": 50.0,
        "score_direction": "higher_is_lower_risk",
        "intercept_allocation": "uniform",
        "rounding_method": "nearest_integer",
        "output_suffix": "__points",
        "score_column": "score",
        "min_score": None,
        "max_score": None,
        "clip": False,
        "point_overrides": [],
    }


def test_scorecardconfig_defaults_golden() -> None:
    """``ScorecardConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert ScorecardConfig().model_dump(mode="json") == _scorecard_defaults()


def test_round_trip_yaml_scorecardconfig() -> None:
    """Serializar y recargar ``ScorecardConfig`` por YAML preserva igualdad exacta."""
    cfg = ScorecardConfig(
        pdo=30.0,
        target_score=650.0,
        target_odds=40.0,
        score_direction="higher_is_higher_risk",
        rounding_method="floor_integer",
        output_suffix="_pts",
        score_column="score_total",
        min_score=300.0,
        max_score=900.0,
        clip=True,
        point_overrides=(
            PointOverrideConfig(
                feature="ingreso",
                bin_label="(0, 1]",
                points=25,
                reason="alineamiento negocio",
            ),
        ),
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert ScorecardConfig.model_validate(raw) == cfg


def test_nikodymconfig_scorecard_instancia() -> None:
    """Pasar una instancia ``ScorecardConfig`` a ``NikodymConfig`` la conserva."""
    scorecard = ScorecardConfig()
    cfg = NikodymConfig(scorecard=scorecard)
    assert isinstance(cfg.scorecard, ScorecardConfig)
    assert cfg.scorecard is scorecard


def test_nikodymconfig_scorecard_dict_coacciona() -> None:
    """Un dict en ``scorecard`` se coacciona a ``ScorecardConfig`` por el hook cargado."""
    cfg = NikodymConfig(scorecard={"pdo": 25.0, "rounding_method": "none"})
    assert isinstance(cfg.scorecard, ScorecardConfig)
    assert cfg.scorecard.pdo == 25.0
    assert cfg.scorecard.rounding_method == "none"


def test_nikodymconfig_scorecard_none_explicito() -> None:
    """``scorecard=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(scorecard=None).scorecard is None


def test_nikodymconfig_scorecard_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``scorecard`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_SCORECARD_CONFIG_CLS", None)
    cfg = NikodymConfig(scorecard={"pdo": 20.0, "target_odds": 50.0})
    assert cfg.scorecard == {"pdo": 20.0, "target_odds": 50.0}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_scorecard_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``scorecard`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_SCORECARD_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(scorecard=blob)


@pytest.mark.parametrize(
    "scorecard",
    [
        ScorecardConfig(pdo=25.0),
        ScorecardConfig(target_score=650.0),
        ScorecardConfig(target_odds=40.0),
        ScorecardConfig(score_direction="higher_is_higher_risk"),
        ScorecardConfig(rounding_method="none"),
    ],
)
def test_config_hash_cambia_al_variar_scorecard(scorecard: ScorecardConfig) -> None:
    """``scorecard`` no es INFRA: escala, dirección y redondeo cambian la identidad."""
    base = config_hash(NikodymConfig(scorecard=ScorecardConfig()))
    variado = config_hash(NikodymConfig(scorecard=scorecard))
    assert "scorecard" not in INFRA_SECTIONS
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["scorecard"]))
def test_nikodym_config_strategy_genera_configs_scorecard_validos(
    cfg: NikodymConfig,
) -> None:
    """La estrategia pública genera configs raíz válidos con ``scorecard`` activo."""
    assert isinstance(cfg.scorecard, ScorecardConfig)
    assert cfg.scorecard.type == "standard"
    assert loads_config(dump_config(cfg)) == cfg


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"pdo": 0.0}, "mayores que 0"),
        ({"target_odds": 0.0}, "mayores que 0"),
        ({"output_suffix": ""}, "output_suffix"),
        ({"score_column": ""}, "score_column"),
        ({"score_column": "score__points"}, "terminar con output_suffix"),
        ({"min_score": 900.0, "max_score": 300.0}, "min_score"),
        ({"clip": True}, "clip=True"),
        (
            {
                "point_overrides": (
                    PointOverrideConfig(feature="ingreso", bin_label="a", points=1, reason="x"),
                    PointOverrideConfig(feature="ingreso", bin_label="a", points=2, reason="y"),
                )
            },
            "point_overrides",
        ),
    ],
)
def test_validaciones_invalidas_levantan_configerror(
    kwargs: dict[str, object],
    match: str,
) -> None:
    """Las invariantes de SDD-09 §5 fallan con ``ConfigError`` propio."""
    with pytest.raises(ConfigError, match=match):
        ScorecardConfig(**kwargs)


def test_point_override_reason_vacio_levanta_configerror() -> None:
    """Cada override manual exige una justificación auditable no vacía."""
    with pytest.raises(ConfigError, match="reason"):
        PointOverrideConfig(feature="ingreso", bin_label="a", points=10, reason=" ")


def test_point_override_points_no_finito_levanta_configerror() -> None:
    """Un override manual no puede publicar puntos no finitos."""
    with pytest.raises(ConfigError, match="points"):
        PointOverrideConfig(feature="ingreso", bin_label="a", points=math.inf, reason="x")


def test_scorecard_campos_float_no_finitos_levantan_configerror() -> None:
    """Los floats que entran al hash canónico deben ser finitos."""
    with pytest.raises(ConfigError, match="target_score"):
        ScorecardConfig(target_score=math.inf)
    with pytest.raises(ConfigError, match="min_score"):
        ScorecardConfig(min_score=math.inf)
    with pytest.raises(ConfigError, match="max_score"):
        ScorecardConfig(max_score=math.inf)


def test_scorecard_positivo_convertible_pasa_por_pydantic() -> None:
    """El validador custom deja a Pydantic coaccionar strings numéricos válidos."""
    cfg = ScorecardConfig(pdo="25.0", target_odds="40.0")  # type: ignore[arg-type]
    assert cfg.pdo == 25.0
    assert cfg.target_odds == 40.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score_direction", "alto_es_bueno"),
        ("intercept_allocation", "iv_weighted"),
        ("rounding_method", "bankers"),
    ],
)
def test_literales_invalidos_rechazados_por_pydantic(field: str, value: object) -> None:
    """Literales fuera de contrato violan restricciones Pydantic antes del runtime."""
    with pytest.raises(ValidationError):
        ScorecardConfig(**{field: value})


def test_campos_scorecard_tienen_metadatos_ui() -> None:
    """Todos los campos de config scorecard declaran metadata de UI para SDD-23."""
    for modelo in (PointOverrideConfig, ScorecardConfig):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_scorecard_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``scorecard`` cuelgan de la raíz propia de la capa."""
    for error_cls in (ScorecardError, ScorecardFitError, ScorecardTransformError):
        with pytest.raises(ScorecardError, match="fallo scorecard"):
            raise error_cls("fallo scorecard")


def test_import_scorecard_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.scorecard`` registra el hook sin arrastrar scoring ni stack tabular."""
    code = (
        "import nikodym.scorecard, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.scorecard.config import ScorecardConfig;"
        "bloqueados=[m for m in ('statsmodels','sklearn','scipy','pandas','optbinning') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(scorecard={'pdo': 25.0});"
        "assert isinstance(cfg.scorecard, ScorecardConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_scorecard_como_blob_opaco_sin_importar_scorecard() -> None:
    """El core acepta ``scorecard`` JSON/dict sin importar ``nikodym.scorecard``."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(scorecard={'pdo': 20.0});"
        "assert cfg.scorecard == {'pdo': 20.0};"
        "assert 'nikodym.scorecard' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_scorecard_getattr_desconocido_levanta_attributeerror() -> None:
    """La reexportación perezosa falla con ``AttributeError`` para nombres desconocidos."""
    atributo = "no_existe"
    with pytest.raises(AttributeError, match="no_existe"):
        getattr(nikodym.scorecard, atributo)


def test_scorecard_getattr_carga_export_perezoso(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ruta positiva de ``__getattr__`` carga y cachea un símbolo bajo demanda."""
    atributo = "ScorecardConfigLazy"
    monkeypatch.setitem(
        nikodym.scorecard._LAZY_EXPORTS,
        atributo,
        ("nikodym.scorecard.config", "ScorecardConfig"),
    )
    try:
        assert getattr(nikodym.scorecard, atributo) is ScorecardConfig
        assert getattr(nikodym.scorecard, atributo) is ScorecardConfig
    finally:
        monkeypatch.delattr(nikodym.scorecard, atributo, raising=False)


def test_config_cls_for_domain_resuelve_scorecard() -> None:
    """El helper interno resuelve ``ScorecardConfig`` cuando ``scorecard`` pobló su hook."""
    assert _config_cls_for_domain("scorecard") is ScorecardConfig


def test_config_hash_default_con_scorecard_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``scorecard`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
