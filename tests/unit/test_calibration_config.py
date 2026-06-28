"""Tests de ``CalibrationConfig`` (SDD-10 §5) y su integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.calibration  # importa la capa: puebla el hook _CALIBRATION_CONFIG_CLS
from nikodym.calibration.calibrator import PDCalibrator
from nikodym.calibration.config import CalibrationConfig
from nikodym.calibration.exceptions import (
    CalibrationError,
    CalibrationFitError,
    CalibrationOffsetExceededError,
    CalibrationTransformError,
)
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy

GOLDEN_DEFAULT_CONFIG_HASH = "5c0ebb9f0b4dacd2fef57c828f5de5bce7ea50a80f0ceca54a0071b5f11f9aa6"


@pytest.fixture(autouse=True)
def _capa_calibration_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_CALIBRATION_CONFIG_CLS", CalibrationConfig)


def _calibration_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-10 §5."""
    return {
        "type": "standard",
        "method": "intercept_offset",
        "target_pd": 0.05,
        "anchor_kind": "through_the_cycle",
        "anchor_source": "development_observed",
        "fit_partition": "desarrollo",
        "target_tolerance": 1e-12,
        "max_abs_offset": None,
        "max_iter": 100,
        "min_fit_rows": 30,
        "require_both_classes_for_supervised": True,
        "pd_raw_column": "pd_raw",
        "linear_predictor_column": "linear_predictor",
        "pd_calibrated_column": "pd_calibrated",
        "linear_predictor_calibrated_column": "linear_predictor_calibrated",
        "partition_column": "partition",
        "target_column": "target",
    }


def test_calibrationconfig_defaults_golden() -> None:
    """``CalibrationConfig()`` construye sin argumentos y coincide bit a bit con el golden."""
    assert CalibrationConfig().model_dump(mode="json") == _calibration_defaults()


def test_round_trip_yaml_calibrationconfig() -> None:
    """Serializar y recargar ``CalibrationConfig`` por YAML preserva igualdad exacta."""
    cfg = CalibrationConfig(
        method="isotonic",
        target_pd=0.07,
        anchor_kind="point_in_time",
        anchor_source="historical_default_rate",
        target_tolerance=1e-10,
        max_iter=250,
        min_fit_rows=100,
        pd_raw_column="pd_base",
        linear_predictor_column="logit_base",
        pd_calibrated_column="pd_final",
        linear_predictor_calibrated_column="logit_final",
        partition_column="particion",
        target_column="malo_12m",
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert CalibrationConfig.model_validate(raw) == cfg


def test_round_trip_yaml_default_ancla_media_observada_desarrollo() -> None:
    """El default YAML usa ``development_observed`` y ancla a la media Dev del target."""
    pd = pytest.importorskip("pandas")
    cfg = CalibrationConfig()
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    loaded = CalibrationConfig.model_validate(yaml.safe_load(text))
    eta = [-2.4, -1.8, -1.1, -0.6, -0.2, 0.3, 0.8, 1.4] * 5
    target = [0, 0, 0, 1, 0, 1, 0, 1] * 5
    expected_rate = sum(target) / len(target)
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo"] * len(eta),
            "target": target,
            "linear_predictor": eta,
            "pd_raw": [_sigmoid(value) for value in eta],
        }
    )

    calibrator = PDCalibrator.from_config(loaded).fit(frame)
    calibrated = calibrator.transform(frame)

    assert loaded.anchor_source == "development_observed"
    assert loaded.target_pd == 0.05
    assert calibrator.target_pd_ == pytest.approx(expected_rate)
    assert calibrated["pd_calibrated"].mean() == pytest.approx(
        expected_rate,
        abs=loaded.target_tolerance,
    )


def test_nikodymconfig_calibration_instancia() -> None:
    """Pasar una instancia ``CalibrationConfig`` a ``NikodymConfig`` la conserva."""
    calibration = CalibrationConfig()
    cfg = NikodymConfig(calibration=calibration)
    assert isinstance(cfg.calibration, CalibrationConfig)
    assert cfg.calibration is calibration


def test_nikodymconfig_calibration_dict_coacciona() -> None:
    """Un dict en ``calibration`` se coacciona a ``CalibrationConfig`` por el hook cargado."""
    cfg = NikodymConfig(calibration={"target_pd": 0.04, "method": "platt_scaling"})
    assert isinstance(cfg.calibration, CalibrationConfig)
    assert cfg.calibration.target_pd == 0.04
    assert cfg.calibration.method == "platt_scaling"


def test_nikodymconfig_calibration_none_explicito() -> None:
    """``calibration=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(calibration=None).calibration is None


def test_nikodymconfig_calibration_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``calibration`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_CALIBRATION_CONFIG_CLS", None)
    cfg = NikodymConfig(calibration={"target_pd": 0.04, "method": "intercept_offset"})
    assert cfg.calibration == {"target_pd": 0.04, "method": "intercept_offset"}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_calibration_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``calibration`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_CALIBRATION_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(calibration=blob)


@pytest.mark.parametrize(
    "calibration",
    [
        CalibrationConfig(method="platt_scaling"),
        CalibrationConfig(target_pd=0.04),
        CalibrationConfig(anchor_kind="point_in_time", anchor_source="business_input"),
        CalibrationConfig(target_tolerance=1e-10),
    ],
)
def test_config_hash_cambia_al_variar_calibration(calibration: CalibrationConfig) -> None:
    """``calibration`` no es INFRA: método, ancla y tolerancia cambian la identidad."""
    base = config_hash(NikodymConfig(calibration=CalibrationConfig()))
    variado = config_hash(NikodymConfig(calibration=calibration))
    assert "calibration" not in INFRA_SECTIONS
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["calibration"]))
def test_nikodym_config_strategy_genera_configs_calibration_validos(
    cfg: NikodymConfig,
) -> None:
    """La estrategia pública genera configs raíz válidos con ``calibration`` activo."""
    assert isinstance(cfg.calibration, CalibrationConfig)
    assert cfg.calibration.type == "standard"
    assert loads_config(dump_config(cfg)) == cfg


@pytest.mark.parametrize("target_pd", [0.0, 1.0, math.nan, math.inf, True])
def test_target_pd_invalido_levanta_configerror(target_pd: object) -> None:
    """``target_pd`` debe estar en ``(0, 1)`` y no admite bool ni no finitos."""
    with pytest.raises(ConfigError, match="target_pd"):
        CalibrationConfig(target_pd=target_pd)  # type: ignore[arg-type]


@pytest.mark.parametrize("target_tolerance", [0.0, -1e-12, math.inf, True])
def test_target_tolerance_invalida_levanta_configerror(target_tolerance: object) -> None:
    """``target_tolerance`` debe ser positiva, finita y no booleana."""
    with pytest.raises(ConfigError, match="target_tolerance"):
        CalibrationConfig(target_tolerance=target_tolerance)  # type: ignore[arg-type]


def test_max_abs_offset_none_es_valido() -> None:
    """``max_abs_offset=None`` conserva el comportamiento audit-only por defecto."""
    assert CalibrationConfig(max_abs_offset=None).max_abs_offset is None


@pytest.mark.parametrize("max_abs_offset", [0.0, -1e-12, math.nan, math.inf, True, "-1"])
def test_max_abs_offset_invalido_levanta_configerror(max_abs_offset: object) -> None:
    """``max_abs_offset`` opcional exige número finito estrictamente positivo."""
    with pytest.raises(ConfigError, match="max_abs_offset"):
        CalibrationConfig(max_abs_offset=max_abs_offset)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_iter": 0},
        {"max_iter": True},
        {"min_fit_rows": 0},
    ],
)
def test_contadores_invalidos_levantan_configerror(kwargs: dict[str, object]) -> None:
    """``max_iter`` y ``min_fit_rows`` exigen enteros mayores o iguales a 1."""
    with pytest.raises(ConfigError, match="mayores o iguales a 1"):
        CalibrationConfig(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"pd_raw_column": " "}, "vacías"),
        ({"pd_calibrated_column": "pd_raw"}, "colisionar"),
        (
            {"anchor_kind": "point_in_time", "anchor_source": "external_regulatory"},
            "point_in_time",
        ),
        (
            {"method": "isotonic", "require_both_classes_for_supervised": False},
            "require_both_classes",
        ),
    ],
)
def test_invariantes_invalidas_levantan_configerror(
    kwargs: dict[str, object],
    match: str,
) -> None:
    """Las invariantes de SDD-10 §5/§8 fallan con ``ConfigError`` propio."""
    with pytest.raises(ConfigError, match=match):
        CalibrationConfig(**kwargs)


def test_calibration_finitud_after_validator_defensiva() -> None:
    """El validador final también protege floats no finitos si entran por construcción baja."""
    cfg = CalibrationConfig.model_construct(target_pd=math.inf)
    with pytest.raises(ConfigError, match="target_pd"):
        cfg._check_invariantes()


def test_calibration_strings_numericos_convertibles_pasan_por_pydantic() -> None:
    """Los validadores custom dejan a Pydantic coaccionar strings numéricos válidos."""
    cfg = CalibrationConfig(
        target_pd="0.04",  # type: ignore[arg-type]
        target_tolerance="1e-10",  # type: ignore[arg-type]
    )
    assert cfg.target_pd == 0.04
    assert cfg.target_tolerance == 1e-10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("method", "beta_calibration"),
        ("anchor_kind", "cycle_average"),
        ("anchor_source", "cmf_universal"),
        ("fit_partition", "holdout"),
    ],
)
def test_literales_invalidos_rechazados_por_pydantic(field: str, value: object) -> None:
    """Literales fuera de contrato violan restricciones Pydantic antes del runtime."""
    with pytest.raises(ValidationError):
        CalibrationConfig(**{field: value})


def test_campos_calibration_tienen_metadatos_ui() -> None:
    """Todos los campos de config calibration declaran metadata de UI para SDD-23."""
    for nombre, campo in CalibrationConfig.model_fields.items():
        extra = campo.json_schema_extra
        assert campo.title is not None, f"CalibrationConfig.{nombre} sin title"
        assert campo.description is not None, f"CalibrationConfig.{nombre} sin description"
        assert isinstance(extra, dict), f"CalibrationConfig.{nombre} sin ui_*"
        assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_calibration_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``calibration`` cuelgan de la raíz propia de la capa."""
    for error_cls in (CalibrationError, CalibrationFitError, CalibrationTransformError):
        with pytest.raises(CalibrationError, match="fallo calibration"):
            raise error_cls("fallo calibration")
    with pytest.raises(CalibrationFitError, match="max_abs_offset") as exc_info:
        raise CalibrationOffsetExceededError(
            offset=2.5,
            max_abs_offset=1.0,
            method="intercept_offset",
            partition="desarrollo",
        )
    assert exc_info.value.offset == 2.5
    assert exc_info.value.max_abs_offset == 1.0
    assert exc_info.value.method == "intercept_offset"
    assert exc_info.value.partition == "desarrollo"


def test_import_calibration_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.calibration`` registra el hook sin arrastrar stack tabular/scoring."""
    code = (
        "import nikodym.calibration, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.calibration.config import CalibrationConfig;"
        "bloqueados=[m for m in ('pandas','scipy','sklearn') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(calibration={'target_pd': 0.04});"
        "assert isinstance(cfg.calibration, CalibrationConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_calibration_como_blob_opaco_sin_importar_calibration() -> None:
    """El core acepta ``calibration`` JSON/dict sin importar ``nikodym.calibration``."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(calibration={'target_pd': 0.04});"
        "assert cfg.calibration == {'target_pd': 0.04};"
        "assert 'nikodym.calibration' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_calibration_getattr_desconocido_levanta_attributeerror() -> None:
    """La reexportación perezosa falla con ``AttributeError`` para nombres desconocidos."""
    atributo = "no_existe"
    with pytest.raises(AttributeError, match="no_existe"):
        getattr(nikodym.calibration, atributo)


def test_calibration_getattr_carga_export_perezoso(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ruta positiva de ``__getattr__`` carga y cachea un símbolo bajo demanda."""
    atributo = "CalibrationConfigLazy"
    monkeypatch.setitem(
        nikodym.calibration._LAZY_EXPORTS,
        atributo,
        ("nikodym.calibration.config", "CalibrationConfig"),
    )
    try:
        assert getattr(nikodym.calibration, atributo) is CalibrationConfig
        assert getattr(nikodym.calibration, atributo) is CalibrationConfig
    finally:
        monkeypatch.delattr(nikodym.calibration, atributo, raising=False)


def test_config_cls_for_domain_resuelve_calibration() -> None:
    """El helper interno resuelve ``CalibrationConfig`` cuando ``calibration`` pobló su hook."""
    assert _config_cls_for_domain("calibration") is CalibrationConfig


def test_config_hash_default_con_calibration_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``calibration`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def _sigmoid(value: float) -> float:
    """Calcula sigmoid escalar para construir el fixture YAML sin depender del calibrador."""
    return 1.0 / (1.0 + math.exp(-value))
