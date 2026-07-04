"""Tests de ``ValidationConfig`` (SDD-22 §5) e integración con ``NikodymConfig``."""

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

import nikodym.validation as validation_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.validation.config import (
    BacktestingValidationConfig,
    CalibrationValidationConfig,
    DiscriminationValidationConfig,
    StabilityValidationConfig,
    ValidationConfig,
)
from nikodym.validation.exceptions import (
    BacktestError,
    CalibrationTestError,
    ValidationConfigError,
    ValidationDataError,
)
from nikodym.validation.exceptions import (
    ValidationError as NikodymValidationError,
)

# Golden del config_hash por defecto tras añadir la sección computacional `validation`.
GOLDEN_DEFAULT_CONFIG_HASH = "0be3798f51c14940597f44e8fb8ac19ec23c88f9c2ab29d94fecd800e093902e"
# Golden anterior (antes de B22.1, con provisioning ya presente); el hash DEBE moverse.
GOLDEN_PREVIO_SIN_VALIDATION = "2c8c7ccbeae14e121d4c69d34777146b984208192998b3098943d0321c827ddb"


@pytest.fixture(autouse=True)
def _capa_validation_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_VALIDATION_CONFIG_CLS", ValidationConfig)


def _validation_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-22 §5."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "families": ["discrimination", "calibration", "stability"],
        "discrimination": {
            "consume_performance": True,
            "partitions": ["desarrollo", "holdout", "oot"],
        },
        "calibration": {
            "hosmer_lemeshow": True,
            "hl_n_groups": 10,
            "hl_grouping": "deciles",
            "brier": True,
            "binomial_by_grade": True,
            "grade_col": "grade",
            "pd_test": "jeffreys",
            "alpha": 0.05,
            "traffic_light_green_alpha": 0.05,
            "traffic_light_red_alpha": 0.01,
            "target_column": "target",
            "pd_column": "pd_calibrated",
            "partition_column": "partition",
            "min_rows_per_group": 30,
        },
        "stability": {
            "consume_stability": True,
            "psi_stable_threshold": 0.10,
            "psi_review_threshold": 0.25,
        },
        "backtesting": {
            "enabled": False,
            "parameters": ["pd", "lgd", "ead"],
            "segment_col": "portfolio",
            "alpha": 0.05,
            "one_sided": True,
            "realised_pd_col": "realised_default",
            "realised_lgd_col": "realised_lgd",
            "realised_ead_col": "realised_ead",
            "pd_test": "jeffreys",
        },
        "fail_on_falta_dato": True,
    }


def _config_no_trivial() -> ValidationConfig:
    """Config de validación no trivial que ejercita ramas válidas del schema."""
    return ValidationConfig(
        families=("discrimination", "calibration", "stability", "backtesting"),
        discrimination=DiscriminationValidationConfig(
            consume_performance=False,
            partitions=("desarrollo", "oot"),
        ),
        calibration=CalibrationValidationConfig(
            hl_n_groups=8,
            pd_test="binomial",
            alpha=0.10,
            traffic_light_green_alpha=0.10,
            traffic_light_red_alpha=0.02,
            grade_col="grado",
            pd_column="pd_cal",
            target_column="malo",
            partition_column="muestra",
            min_rows_per_group=50,
        ),
        stability=StabilityValidationConfig(
            consume_stability=False,
            psi_stable_threshold=0.05,
            psi_review_threshold=0.20,
        ),
        backtesting=BacktestingValidationConfig(
            enabled=True,
            parameters=("pd", "lgd"),
            segment_col="cartera",
            alpha=0.10,
            one_sided=False,
            realised_pd_col="default_real",
            realised_lgd_col="lgd_real",
            realised_ead_col="ead_real",
            pd_test="binomial",
        ),
        fail_on_falta_dato=False,
    )


# ─────────────────────────── defaults / round-trip ───────────────────────────


def test_validationconfig_defaults_golden() -> None:
    """``ValidationConfig()`` construye sin argumentos y coincide con el golden."""
    assert ValidationConfig().model_dump(mode="json") == _validation_defaults()


def test_subconfigs_construyen_sin_argumentos() -> None:
    """Cada sub-config construye con defaults sin argumentos (DoD F0)."""
    assert DiscriminationValidationConfig().consume_performance is True
    assert CalibrationValidationConfig().hl_n_groups == 10
    assert StabilityValidationConfig().psi_stable_threshold == 0.10
    assert BacktestingValidationConfig().enabled is False


def test_round_trip_yaml_validationconfig() -> None:
    """Serializar y recargar ``ValidationConfig`` por YAML preserva igualdad exacta."""
    cfg = _config_no_trivial()
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert ValidationConfig.model_validate(yaml.safe_load(text)) == cfg


# ─────────────────────────── integración NikodymConfig ───────────────────────────


def test_nikodymconfig_validation_instancia() -> None:
    """Pasar una instancia ``ValidationConfig`` a ``NikodymConfig`` la conserva."""
    validation = ValidationConfig()
    cfg = NikodymConfig(validation=validation)
    assert isinstance(cfg.validation, ValidationConfig)
    assert cfg.validation is validation


def test_nikodymconfig_validation_dict_coacciona() -> None:
    """Un dict en ``validation`` se coacciona por el hook cargado."""
    cfg = NikodymConfig(validation={"families": ["calibration"]})
    assert isinstance(cfg.validation, ValidationConfig)
    assert cfg.validation.families == ("calibration",)


def test_nikodymconfig_validation_none_explicito() -> None:
    """``validation=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(validation=None).validation is None


def test_nikodymconfig_validation_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``validation`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_VALIDATION_CONFIG_CLS", None)
    cfg = NikodymConfig(validation={"families": ["calibration"]})
    assert cfg.validation == {"families": ["calibration"]}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_validation_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``validation`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_VALIDATION_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(validation=blob)


# ─────────────────────────── validaciones de columnas ───────────────────────────


@pytest.mark.parametrize("field", ["grade_col", "pd_column", "target_column", "partition_column"])
def test_columnas_calibracion_vacias_levantan(field: str) -> None:
    """Las columnas de calibración no pueden quedar vacías."""
    with pytest.raises(ValidationConfigError, match="calibration"):
        CalibrationValidationConfig(**{field: " "})


def test_columnas_calibracion_colisionan_levantan() -> None:
    """Las columnas de calibración no pueden colisionar entre sí."""
    with pytest.raises(ValidationConfigError, match="colisionar"):
        CalibrationValidationConfig(grade_col="x", pd_column="x")


@pytest.mark.parametrize(
    "field", ["segment_col", "realised_pd_col", "realised_lgd_col", "realised_ead_col"]
)
def test_columnas_backtesting_vacias_levantan(field: str) -> None:
    """Las columnas de backtesting no pueden quedar vacías."""
    with pytest.raises(ValidationConfigError, match="backtesting"):
        BacktestingValidationConfig(**{field: " "})


def test_columnas_backtesting_colisionan_levantan() -> None:
    """Las columnas realizadas de backtesting no pueden colisionar entre sí."""
    with pytest.raises(ValidationConfigError, match="colisionar"):
        BacktestingValidationConfig(realised_pd_col="x", realised_lgd_col="x")


# ─────────────────────────── semáforo / bandas ───────────────────────────


def test_semaforo_rojo_no_menor_que_verde_levanta() -> None:
    """``traffic_light_red_alpha`` debe ser estrictamente menor que el corte verde."""
    with pytest.raises(ValidationConfigError, match="traffic_light_red_alpha"):
        CalibrationValidationConfig(traffic_light_green_alpha=0.05, traffic_light_red_alpha=0.05)


def test_psi_stable_no_menor_que_review_levanta() -> None:
    """``psi_stable_threshold`` debe ser estrictamente menor que ``psi_review_threshold``."""
    with pytest.raises(ValidationConfigError, match="psi_stable_threshold"):
        StabilityValidationConfig(psi_stable_threshold=0.25, psi_review_threshold=0.25)


def test_hl_grouping_fixed_bands_reservado_levanta() -> None:
    """``hl_grouping='fixed_bands'`` está reservado y aún no soportado."""
    with pytest.raises(ValidationConfigError, match="fixed_bands"):
        CalibrationValidationConfig(hl_grouping="fixed_bands")


# ─────────────────────────── coherencia families/backtesting ───────────────────────────


def test_backtesting_en_families_sin_enabled_falla() -> None:
    """``'backtesting' ∈ families`` con ``enabled=False`` y ``fail_on_falta_dato`` falla."""
    with pytest.raises(ValidationConfigError, match="backtesting"):
        ValidationConfig(families=("calibration", "backtesting"))


def test_backtesting_en_families_sin_enabled_difiere_a_falta_dato() -> None:
    """Con ``fail_on_falta_dato=False`` la brecha se difiere a FALTA-DATO (no falla)."""
    cfg = ValidationConfig(families=("calibration", "backtesting"), fail_on_falta_dato=False)
    assert "backtesting" in cfg.families
    assert cfg.backtesting.enabled is False


def test_backtesting_en_families_con_enabled_construye() -> None:
    """``'backtesting' ∈ families`` con ``enabled=True`` construye sin brecha."""
    cfg = ValidationConfig(
        families=("calibration", "backtesting"),
        backtesting=BacktestingValidationConfig(enabled=True),
    )
    assert cfg.backtesting.enabled is True


# ─────────────────────────── literales y rangos Pydantic ───────────────────────────


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (CalibrationValidationConfig, "hl_n_groups", 4),
        (CalibrationValidationConfig, "hl_n_groups", 21),
        (CalibrationValidationConfig, "hl_grouping", "quintiles"),
        (CalibrationValidationConfig, "pd_test", "chi2"),
        (CalibrationValidationConfig, "alpha", 0.0),
        (CalibrationValidationConfig, "alpha", 0.5),
        (CalibrationValidationConfig, "traffic_light_green_alpha", 0.0),
        (CalibrationValidationConfig, "traffic_light_green_alpha", 1.0),
        (CalibrationValidationConfig, "min_rows_per_group", 0),
        (StabilityValidationConfig, "psi_stable_threshold", -0.1),
        (BacktestingValidationConfig, "alpha", 0.5),
        (BacktestingValidationConfig, "pd_test", "ttest"),
        (DiscriminationValidationConfig, "partitions", ("dev",)),
        (ValidationConfig, "type", "custom"),
        (ValidationConfig, "families", ("unknown",)),
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


# ─────────────────────────── config_hash ───────────────────────────


def test_config_hash_default_con_validation_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``validation=None``."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_se_movio_por_seccion_validation() -> None:
    """Añadir ``validation`` movió el golden respecto al valor previo (no es regresión)."""
    assert GOLDEN_DEFAULT_CONFIG_HASH != GOLDEN_PREVIO_SIN_VALIDATION
    assert config_hash(NikodymConfig()) != GOLDEN_PREVIO_SIN_VALIDATION


def test_config_hash_es_puramente_aditivo_sobre_validation() -> None:
    """Quitar ``validation:null`` (y las secciones posteriores) reproduce el hash previo (aditivo).

    B12.1 añadió ``ml:null`` y B13.2 ``tuning:null`` DESPUÉS de ``validation`` en el schema; para
    reconstruir el estado inmediatamente anterior a ``validation`` hay que retirar las tres claves
    computacionales nuevas.
    """
    payload = NikodymConfig().model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    assert payload["validation"] is None
    assert payload["ml"] is None
    assert payload["tuning"] is None
    del payload["validation"]
    del payload["ml"]
    del payload["tuning"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    previo = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert previo == GOLDEN_PREVIO_SIN_VALIDATION


@pytest.mark.parametrize(
    "validation",
    [
        ValidationConfig(families=("calibration",)),
        ValidationConfig(calibration=CalibrationValidationConfig(hl_n_groups=8)),
        ValidationConfig(calibration=CalibrationValidationConfig(alpha=0.10)),
        ValidationConfig(calibration=CalibrationValidationConfig(traffic_light_green_alpha=0.10)),
        ValidationConfig(calibration=CalibrationValidationConfig(pd_test="binomial")),
        ValidationConfig(stability=StabilityValidationConfig(psi_stable_threshold=0.05)),
        ValidationConfig(discrimination=DiscriminationValidationConfig(consume_performance=False)),
        ValidationConfig(backtesting=BacktestingValidationConfig(enabled=True)),
    ],
)
def test_config_hash_cambia_al_variar_validation(validation: ValidationConfig) -> None:
    """``validation`` no es INFRA: familias/deciles/alpha/bandas/test/enabled cambian el hash."""
    base = config_hash(NikodymConfig(validation=ValidationConfig()))
    variado = config_hash(NikodymConfig(validation=validation))
    assert "validation" not in INFRA_SECTIONS
    assert variado != base


# ─────────────────────────── metadata UI + API pública ───────────────────────────


def test_campos_validation_tienen_metadatos_ui() -> None:
    """Todos los campos de config de validación declaran metadata de UI para SDD-23."""
    for modelo in (
        DiscriminationValidationConfig,
        CalibrationValidationConfig,
        StabilityValidationConfig,
        BacktestingValidationConfig,
        ValidationConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_validation_public_api_minimo() -> None:
    """El paquete de validación expone config y excepciones de B22.1."""
    assert validation_pkg.ValidationConfig is ValidationConfig
    assert validation_pkg.ValidationError is NikodymValidationError
    assert "ValidationConfig" in validation_pkg.__all__
    assert "ValidationError" in validation_pkg.__all__


def test_validation_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``validation`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        NikodymValidationError,
        ValidationConfigError,
        ValidationDataError,
        CalibrationTestError,
        BacktestError,
    ):
        assert issubclass(error_cls, NikodymError)
        assert issubclass(error_cls, NikodymValidationError)


def test_validation_getattr_desconocido_levanta() -> None:
    """Un atributo desconocido del paquete levanta ``AttributeError``."""
    with pytest.raises(AttributeError, match="validation"):
        _ = validation_pkg.no_existe  # type: ignore[attr-defined]


# ─────────────────────────── import liviano ───────────────────────────


def test_import_validation_config_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.validation.config`` registra hook sin arrastrar stack pesado."""
    code = (
        "import nikodym.validation.config, nikodym.core, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.validation.config import ValidationConfig;"
        "bloqueados=[m for m in "
        "('pandas','pandera','pyarrow','scipy','sklearn','nikodym.tracking','mlflow') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(validation={'families': ['calibration']});"
        "assert isinstance(cfg.validation, ValidationConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_validation_como_blob_opaco_sin_importar_la_capa() -> None:
    """El core acepta ``validation`` JSON/dict sin importar la capa de validación."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(validation={'families': ['calibration']});"
        "assert cfg.validation == {'families': ['calibration']};"
        "assert 'nikodym.validation' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
