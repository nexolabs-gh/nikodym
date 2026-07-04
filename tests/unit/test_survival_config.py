"""Tests de ``SurvivalConfig`` (SDD-18 §5) e integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import nikodym.survival as survival_pkg  # importa la capa: puebla el hook
from nikodym.core import study as study_module
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.survival.base import BaseSurvivalModel
from nikodym.survival.config import (
    CoxAftConfig,
    DiscreteHazardConfig,
    KaplanMeierConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalTimeGridConfig,
)
from nikodym.survival.exceptions import (
    SurvivalConfigError,
    SurvivalError,
    SurvivalFitError,
    SurvivalInputError,
    SurvivalLicenseError,
    SurvivalTransformError,
)
from nikodym.testing.strategies import _config_cls_for_domain

GOLDEN_DEFAULT_CONFIG_HASH = "0be3798f51c14940597f44e8fb8ac19ec23c88f9c2ab29d94fecd800e093902e"


@pytest.fixture(autouse=True)
def _capa_survival_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_SURVIVAL_CONFIG_CLS", SurvivalConfig)


def _input() -> SurvivalInputConfig:
    """Config de entrada mínima válida para survival."""
    return SurvivalInputConfig(duration_col="duration", event_col="event")


def _survival_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-18 §5."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "method": "discrete_hazard",
        "input": {
            "duration_col": "duration",
            "event_col": "event",
            "id_col": None,
            "segment_col": None,
            "pd_source": "model_raw",
            "pd_column": "pd_raw",
            "linear_predictor_column": "linear_predictor",
            "covariate_cols": [],
        },
        "time_grid": {
            "time_unit": "period",
            "horizon_periods": None,
            "evaluation_times": [],
        },
        "kaplan_meier": {
            "confidence_level": None,
            "confidence_transform": None,
        },
        "discrete_hazard": {
            "link": "logit",
            "include_period_dummies": True,
            "pd_role": "covariate",
            "min_events_per_period": None,
        },
        "cox_aft": {
            "ph_test_enabled": True,
            "ph_p_value_threshold": None,
            "aft_family": None,
        },
        "fail_on_falta_dato": True,
    }


def test_survivalconfig_defaults_golden_con_input_explicito() -> None:
    """``SurvivalConfig`` con input requerido coincide bit a bit con el golden."""
    assert SurvivalConfig(input=_input()).model_dump(mode="json") == _survival_defaults()


def test_round_trip_yaml_survivalconfig() -> None:
    """Serializar y recargar ``SurvivalConfig`` por YAML preserva igualdad exacta."""
    cfg = SurvivalConfig(
        method="cox_ph",
        input=SurvivalInputConfig(
            duration_col="meses_hasta_default",
            event_col="default_observado",
            id_col="account_id",
            segment_col="segmento",
            pd_source="calibration",
            pd_column="pd_calibrated",
            linear_predictor_column="linear_predictor_calibrated",
            covariate_cols=("ltv", "saldo"),
        ),
        time_grid=SurvivalTimeGridConfig(
            time_unit="month",
            horizon_periods=36,
            evaluation_times=(1.0, 12.0, 24.0),
        ),
        kaplan_meier=KaplanMeierConfig(
            confidence_level=0.95,
            confidence_transform="loglog",
        ),
        discrete_hazard=DiscreteHazardConfig(
            link="cloglog",
            include_period_dummies=False,
            pd_role="offset",
            min_events_per_period=3,
        ),
        cox_aft=CoxAftConfig(
            ph_test_enabled=False,
            ph_p_value_threshold=0.05,
            aft_family="weibull",
        ),
        fail_on_falta_dato=False,
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert SurvivalConfig.model_validate(raw) == cfg


def test_nikodymconfig_survival_instancia() -> None:
    """Pasar una instancia ``SurvivalConfig`` a ``NikodymConfig`` la conserva."""
    survival = SurvivalConfig(input=_input())
    cfg = NikodymConfig(survival=survival)
    assert isinstance(cfg.survival, SurvivalConfig)
    assert cfg.survival is survival


def test_nikodymconfig_survival_dict_coacciona() -> None:
    """Un dict en ``survival`` se coacciona a ``SurvivalConfig`` por el hook cargado."""
    cfg = NikodymConfig(
        survival={
            "input": {"duration_col": "months", "event_col": "default_flag"},
            "discrete_hazard": {"link": "cloglog"},
        }
    )
    assert isinstance(cfg.survival, SurvivalConfig)
    assert cfg.survival.input.duration_col == "months"
    assert cfg.survival.discrete_hazard.link == "cloglog"


def test_nikodymconfig_survival_none_explicito() -> None:
    """``survival=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(survival=None).survival is None


def test_nikodymconfig_survival_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``survival`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_SURVIVAL_CONFIG_CLS", None)
    cfg = NikodymConfig(survival={"input": {"duration_col": "t", "event_col": "e"}})
    assert cfg.survival == {"input": {"duration_col": "t", "event_col": "e"}}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_survival_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``survival`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_SURVIVAL_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(survival=blob)


@pytest.mark.parametrize(
    "survival",
    [
        SurvivalConfig(input=_input(), method="kaplan_meier"),
        SurvivalConfig(
            input=_input(),
            discrete_hazard=DiscreteHazardConfig(link="cloglog"),
        ),
        SurvivalConfig(
            input=SurvivalInputConfig(
                duration_col="duration",
                event_col="event",
                pd_source="calibration",
                pd_column="pd_calibrated",
            )
        ),
        SurvivalConfig(
            input=SurvivalInputConfig(duration_col="months_to_event", event_col="default_flag")
        ),
        SurvivalConfig(input=_input(), time_grid=SurvivalTimeGridConfig(horizon_periods=24)),
    ],
)
def test_config_hash_cambia_al_variar_survival(survival: SurvivalConfig) -> None:
    """``survival`` no es INFRA: método, link, PD, columnas y horizonte cambian identidad."""
    base = config_hash(NikodymConfig(survival=SurvivalConfig(input=_input())))
    variado = config_hash(NikodymConfig(survival=survival))
    assert "survival" not in INFRA_SECTIONS
    assert variado != base


def test_duration_y_event_no_pueden_ser_la_misma_columna() -> None:
    """``duration_col`` y ``event_col`` deben identificar columnas distintas."""
    with pytest.raises(SurvivalConfigError, match="duration_col y event_col"):
        SurvivalInputConfig(duration_col="event", event_col="event")


def test_columnas_vacias_levantan_survivalconfigerror() -> None:
    """Las columnas declarativas y covariables no pueden quedar vacías."""
    with pytest.raises(SurvivalConfigError, match="input"):
        SurvivalInputConfig(duration_col=" ", event_col="event")
    with pytest.raises(SurvivalConfigError, match="covariables"):
        SurvivalInputConfig(duration_col="duration", event_col="event", covariate_cols=(" ",))
    with pytest.raises(SurvivalConfigError, match="time_unit"):
        SurvivalTimeGridConfig(time_unit=" ")


def test_method_aft_exige_aft_family() -> None:
    """``method='aft'`` exige familia AFT explícita."""
    with pytest.raises(SurvivalConfigError, match="aft_family"):
        SurvivalConfig(input=_input(), method="aft")


def test_confidence_level_exige_confidence_transform() -> None:
    """Kaplan-Meier no publica IC si falta la transformación declarada."""
    with pytest.raises(SurvivalConfigError, match="confidence_transform"):
        KaplanMeierConfig(confidence_level=0.95)


def test_pd_role_offset_exige_linear_predictor_column() -> None:
    """El rol ``offset`` exige columna de predictor lineal no vacía."""
    with pytest.raises(SurvivalConfigError, match="pd_role='offset'"):
        SurvivalConfig(
            input={
                "duration_col": "duration",
                "event_col": "event",
                "linear_predictor_column": " ",
            },
            discrete_hazard={"pd_role": "offset"},
        )


def test_validator_offset_acepta_instancia_y_no_dict() -> None:
    """El validator temprano deja pasar instancias ya resueltas y datos no dict."""
    raw = {"input": _input(), "discrete_hazard": {"pd_role": "offset"}}
    assert SurvivalConfig._check_offset_raw(raw) is raw
    assert SurvivalConfig._check_offset_raw("ya-validado") == "ya-validado"


def test_survivalconfig_requiere_input() -> None:
    """``SurvivalConfig`` falla si no recibe duración y evento explícitos."""
    with pytest.raises(ValidationError):
        SurvivalConfig()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("config_cls", "kwargs"),
    [
        (SurvivalConfig, {"input": _input(), "method": "random_forest"}),
        (SurvivalTimeGridConfig, {"horizon_periods": 0}),
        (KaplanMeierConfig, {"confidence_level": 1.0, "confidence_transform": "plain"}),
        (DiscreteHazardConfig, {"link": "probit"}),
        (DiscreteHazardConfig, {"pd_role": "weight"}),
        (DiscreteHazardConfig, {"min_events_per_period": 0}),
        (CoxAftConfig, {"ph_p_value_threshold": 0.0}),
        (CoxAftConfig, {"aft_family": "exponential"}),
        (SurvivalConfig, {"input": _input(), "type": "custom"}),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    config_cls: type[object],
    kwargs: dict[str, object],
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        config_cls(**kwargs)


def test_campos_survival_tienen_metadatos_ui() -> None:
    """Todos los campos de config survival declaran metadata de UI para SDD-23."""
    for modelo in (
        SurvivalInputConfig,
        SurvivalTimeGridConfig,
        KaplanMeierConfig,
        DiscreteHazardConfig,
        CoxAftConfig,
        SurvivalConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_survival_public_api_minimo() -> None:
    """El paquete expone config, contrato base y excepciones de B18.1."""
    assert survival_pkg.SurvivalConfig is SurvivalConfig
    assert survival_pkg.BaseSurvivalModel is BaseSurvivalModel
    assert survival_pkg.SurvivalError is SurvivalError
    assert "SurvivalConfig" in survival_pkg.__all__


def test_survival_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``survival`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        SurvivalError,
        SurvivalConfigError,
        SurvivalInputError,
        SurvivalFitError,
        SurvivalTransformError,
        SurvivalLicenseError,
    ):
        assert issubclass(error_cls, NikodymError)
        with pytest.raises(SurvivalError, match="fallo survival"):
            raise error_cls("fallo survival")


def test_base_survival_model_runtime_checkable() -> None:
    """El Protocol acepta modelos con los cuatro métodos survival mínimos."""

    class DummySurvivalModel:
        """Modelo mínimo para verificar el contrato estructural en runtime."""

        config_cls = SurvivalConfig

        def fit(self, frame: object, **kwargs: object) -> object:
            """Ajuste mínimo de prueba."""
            del frame, kwargs
            return self

        def predict_survival(self, frame: object, **kwargs: object) -> object:
            """Predicción mínima de supervivencia."""
            del frame, kwargs
            return object()

        def predict_hazard(self, frame: object, **kwargs: object) -> object:
            """Predicción mínima de hazard."""
            del frame, kwargs
            return object()

        def term_structure(self, frame: object, **kwargs: object) -> object:
            """Term-structure mínima de prueba."""
            del frame, kwargs
            return object()

    assert isinstance(DummySurvivalModel(), BaseSurvivalModel)


def test_import_survival_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.survival`` registra hook sin arrastrar lifelines ni statsmodels."""
    code = (
        "import nikodym.survival, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.survival.config import SurvivalConfig;"
        "bloqueados=[m for m in ('lifelines','statsmodels','sksurv') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(survival={'input': {'duration_col': 't', 'event_col': 'e'}});"
        "assert isinstance(cfg.survival, SurvivalConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_survival_como_blob_opaco_sin_importar_survival() -> None:
    """El core acepta ``survival`` JSON/dict sin importar la capa survival."""
    code = (
        "from nikodym.core.config import NikodymConfig, dump_config;"
        "import sys;"
        "assert 'nikodym.survival' not in sys.modules;"
        "cfg=NikodymConfig(survival={'input': {'duration_col': 't', 'event_col': 'e'}});"
        "assert cfg.survival == {'input': {'duration_col': 't', 'event_col': 'e'}};"
        "texto=dump_config(cfg);"
        "assert 'survival:' in texto;"
        "assert 'nikodym.survival' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_config_cls_for_domain_resuelve_survival() -> None:
    """El helper interno resuelve ``SurvivalConfig`` cuando el hook está poblado."""
    assert _config_cls_for_domain("survival") is SurvivalConfig


def test_core_study_cablea_survival_en_orden_por_defecto() -> None:
    """``Study`` conoce ``survival`` después de F1 y antes de provisiones CMF."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("calibration") < order.index("survival") < order.index("provisioning_cmf")
    assert study_module._DOMAIN_MODULES["survival"] == "nikodym.survival"
    assert study_module._DOMAIN_CONFIG_CLASSES["survival"] == (
        "nikodym.survival.config",
        "SurvivalConfig",
    )


def test_dump_load_nikodymconfig_con_survival_idempotente() -> None:
    """``dump_config``/``loads_config`` preservan la sección ``survival`` cableada."""
    cfg = NikodymConfig(
        survival=SurvivalConfig(
            input=SurvivalInputConfig(
                duration_col="duration",
                event_col="event",
                covariate_cols=("saldo",),
            ),
            time_grid=SurvivalTimeGridConfig(horizon_periods=12),
        )
    )
    assert loads_config(dump_config(cfg)) == cfg


def test_config_hash_default_con_survival_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``survival`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
