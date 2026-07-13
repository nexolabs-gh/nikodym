"""Tests de ``IfrsProvisioningConfig`` (SDD-16 §5) e integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import nikodym.provisioning.ifrs9 as ifrs9_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsEclConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsProvisioningConfig,
    IfrsScenarioConfig,
    IfrsStagingConfig,
)
from nikodym.provisioning.ifrs9.exceptions import (
    IfrsConfigError,
    IfrsEadError,
    IfrsEclError,
    IfrsInputError,
    IfrsLgdError,
    IfrsPdError,
    IfrsProvisioningError,
    IfrsStagingError,
    IfrsTermStructureError,
)

# Golden del config_hash por defecto tras añadir la sección computacional `provisioning_ifrs9`.
GOLDEN_DEFAULT_CONFIG_HASH = "cbc42cfc02993f6646a744d66d2e0e348285e07761f59f434469afe2e8801610"
# Golden anterior (antes de B16.1); el hash DEBE moverse respecto a este valor.
GOLDEN_PREVIO_SIN_IFRS9 = "145f9c1d1d7674f0aec6c435774649ac97b7e98aad656b4f6e171155f15b747e"


@pytest.fixture(autouse=True)
def _capa_provisioning_ifrs9_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_IFRS9_CONFIG_CLS", IfrsProvisioningConfig)


def _ifrs9_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-16 §5."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "as_of_date_col": "as_of_date",
        "row_id_col": None,
        "portfolio_col": "portfolio",
        "pd": {
            "term_structure_source": "survival",
            "base_pd_source": "term_structure",
            "pit_mode": "consume_pit",
            "rho": None,
            "rho_col": None,
            "systemic_factor_col": None,
            "horizon_12m_periods": 12,
            "max_lifetime_periods": None,
        },
        "lgd": {
            "method": "provided",
            "lgd_col": "lgd",
            "recovery_col": None,
            "lgd_floor": 0.0,
            "lgd_cap": 1.0,
            "covariate_cols": [],
            "workout_discount": "eir",
        },
        "ead": {
            "method": "ccf",
            "ead_col": "ead",
            "drawn_col": "drawn",
            "limit_col": "credit_limit",
            "ccf_col": None,
            "ccf_value": None,
            "exposure_profile_col": None,
        },
        "staging": {
            "sicr_pd_ratio_threshold": 2.0,
            "sicr_pd_pit_backstop_multiple": 3.0,
            "dpd_sicr_backstop": 30,
            "dpd_default_backstop": 90,
            "days_past_due_col": "days_past_due",
            "is_default_col": "is_default",
            "origination_pd_life_col": None,
            "rating_col": None,
            "origination_rating_col": None,
            "notch_downgrade_threshold": None,
            "stage_override_col": None,
            "low_credit_risk_exemption": False,
            "low_credit_risk_col": None,
        },
        "scenarios": {
            "source": "forward",
            "weights": {},
            "forbid_mean_scenario": True,
        },
        "ecl": {
            "eir_col": "eir",
            "discount_convention": "annual_eir_year_fraction",
            "stage3_direct": False,
            "rounding": "none",
        },
        "fail_on_falta_dato": True,
    }


def _config_no_trivial() -> IfrsProvisioningConfig:
    """Config IFRS 9 no trivial que ejercita ramas válidas de todos los sub-configs."""
    return IfrsProvisioningConfig(
        as_of_date_col="fecha_cierre",
        row_id_col="operacion_id",
        portfolio_col="cartera",
        pd=IfrsPdConfig(
            term_structure_source="forward",
            base_pd_source="calibration",
            pit_mode="apply_vasicek",
            rho=0.15,
            systemic_factor_col="z_factor",
            horizon_12m_periods=4,
            max_lifetime_periods=120,
        ),
        lgd=IfrsLgdConfig(
            method="beta_regression",
            recovery_col="recovery",
            lgd_floor=0.05,
            lgd_cap=0.95,
            covariate_cols=("ltv", "region"),
            workout_discount="contractual",
        ),
        ead=IfrsEadConfig(
            method="ccf",
            drawn_col="saldo",
            limit_col="cupo",
            ccf_value=0.5,
        ),
        staging=IfrsStagingConfig(
            sicr_pd_ratio_threshold=2.5,
            sicr_pd_pit_backstop_multiple=3.5,
            origination_pd_life_col="pd_life_origen",
            rating_col="rating",
            origination_rating_col="rating_origen",
            notch_downgrade_threshold=3,
            stage_override_col="watchlist",
            low_credit_risk_exemption=True,
            low_credit_risk_col="grado_inversion",
        ),
        scenarios=IfrsScenarioConfig(
            source="config",
            weights={"base": 0.6, "adverso": 0.3, "severo": 0.1},
        ),
        ecl=IfrsEclConfig(
            eir_col="tasa_efectiva",
            discount_convention="period_eir",
            stage3_direct=True,
            rounding="currency_2dp",
        ),
        fail_on_falta_dato=False,
    )


# ─────────────────────────── defaults / round-trip ───────────────────────────


def test_ifrsprovisioningconfig_defaults_golden() -> None:
    """``IfrsProvisioningConfig()`` construye sin argumentos y coincide con el golden."""
    assert IfrsProvisioningConfig().model_dump(mode="json") == _ifrs9_defaults()


def test_round_trip_yaml_ifrsprovisioningconfig() -> None:
    """Serializar y recargar ``IfrsProvisioningConfig`` por YAML preserva igualdad exacta."""
    cfg = _config_no_trivial()
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert IfrsProvisioningConfig.model_validate(yaml.safe_load(text)) == cfg


# ─────────────────────────── integración NikodymConfig ───────────────────────────


def test_nikodymconfig_provisioning_ifrs9_instancia() -> None:
    """Pasar una instancia ``IfrsProvisioningConfig`` a ``NikodymConfig`` la conserva."""
    provisioning = IfrsProvisioningConfig()
    cfg = NikodymConfig(provisioning_ifrs9=provisioning)
    assert isinstance(cfg.provisioning_ifrs9, IfrsProvisioningConfig)
    assert cfg.provisioning_ifrs9 is provisioning


def test_nikodymconfig_provisioning_ifrs9_dict_coacciona() -> None:
    """Un dict en ``provisioning_ifrs9`` se coacciona por el hook cargado."""
    cfg = NikodymConfig(provisioning_ifrs9={"ecl": {"rounding": "integer_currency"}})
    assert isinstance(cfg.provisioning_ifrs9, IfrsProvisioningConfig)
    assert cfg.provisioning_ifrs9.ecl.rounding == "integer_currency"


def test_nikodymconfig_provisioning_ifrs9_none_explicito() -> None:
    """``provisioning_ifrs9=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(provisioning_ifrs9=None).provisioning_ifrs9 is None


def test_nikodymconfig_provisioning_ifrs9_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``provisioning_ifrs9`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_IFRS9_CONFIG_CLS", None)
    cfg = NikodymConfig(provisioning_ifrs9={"ecl": {"rounding": "integer_currency"}})
    assert cfg.provisioning_ifrs9 == {"ecl": {"rounding": "integer_currency"}}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_provisioning_ifrs9_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``provisioning_ifrs9`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_IFRS9_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(provisioning_ifrs9=blob)


# ─────────────────────────── validaciones de PD ───────────────────────────


@pytest.mark.parametrize("field", ["rho_col", "systemic_factor_col"])
def test_pd_columnas_opcionales_vacias_levantan(field: str) -> None:
    """Las columnas opcionales de PD no pueden quedar en blanco si se informan."""
    with pytest.raises(IfrsConfigError, match="pd"):
        IfrsPdConfig(**{field: " "})


# ─────────────────────────── validaciones de LGD ───────────────────────────


def test_lgd_col_vacia_levanta() -> None:
    """``lgd.lgd_col`` no puede quedar vacío."""
    with pytest.raises(IfrsConfigError, match="lgd"):
        IfrsLgdConfig(lgd_col=" ")


def test_lgd_recovery_col_vacia_levanta() -> None:
    """``lgd.recovery_col`` no puede quedar en blanco si se informa."""
    with pytest.raises(IfrsConfigError, match="lgd"):
        IfrsLgdConfig(recovery_col=" ")


def test_lgd_covariate_vacia_levanta() -> None:
    """``lgd.covariate_cols`` no puede contener nombres vacíos."""
    with pytest.raises(IfrsConfigError, match="covariate_cols"):
        IfrsLgdConfig(method="beta_regression", covariate_cols=("ltv", " "))


def test_lgd_floor_mayor_que_cap_levanta() -> None:
    """``lgd.lgd_floor`` no puede exceder ``lgd.lgd_cap``."""
    with pytest.raises(IfrsConfigError, match="lgd_floor"):
        IfrsLgdConfig(lgd_floor=0.8, lgd_cap=0.5)


@pytest.mark.parametrize("method", ["beta_regression", "fractional_response"])
def test_lgd_beta_fractional_exige_covariables(method: str) -> None:
    """Los enfoques beta/fractional exigen covariables no vacías."""
    with pytest.raises(IfrsConfigError, match="covariate_cols"):
        IfrsLgdConfig(method=method)


def test_lgd_workout_exige_recovery_col() -> None:
    """El enfoque workout exige ``recovery_col`` para la identidad LGD=1-recovery."""
    with pytest.raises(IfrsConfigError, match="workout"):
        IfrsLgdConfig(method="workout")
    assert IfrsLgdConfig(method="workout", recovery_col="recovery").recovery_col == "recovery"


# ─────────────────────────── validaciones de EAD ───────────────────────────


@pytest.mark.parametrize("field", ["ead_col", "drawn_col", "limit_col"])
def test_ead_columnas_obligatorias_vacias_levantan(field: str) -> None:
    """Las columnas obligatorias de EAD no pueden quedar vacías."""
    with pytest.raises(IfrsConfigError, match="ead"):
        IfrsEadConfig(**{field: " "})


@pytest.mark.parametrize("field", ["ccf_col"])
def test_ead_columnas_opcionales_vacias_levantan(field: str) -> None:
    """Las columnas opcionales de EAD no pueden quedar en blanco si se informan."""
    with pytest.raises(IfrsConfigError, match="ead"):
        IfrsEadConfig(**{field: " "})


def test_ead_exposure_profile_col_diferido_ct3_levanta() -> None:
    """Informar ``exposure_profile_col`` levanta: perfil EAD(t) diferido a CT-3.

    Guard fail-fast en construcción del config: una columna escalar no representa
    EAD(t) por período, así que se rechaza en vez de aplanarla a constante sin aviso
    (degradación silenciosa con etiqueta falsa). El panel EAD(t) real está diferido a
    CT-3 (SDD-16); el despliegue constante honesto con aviso ``FALTA-DATO-IFRS-4`` sigue
    disponible sin ``exposure_profile_col``.
    """
    with pytest.raises(IfrsConfigError, match="diferido a CT-3") as exc_info:
        IfrsEadConfig(exposure_profile_col="perfil_ead")
    mensaje = str(exc_info.value)
    # Mensaje accionable: nombra la alternativa honesta (EAD constante + aviso) y el diferido.
    assert "FALTA-DATO-IFRS-4" in mensaje
    assert "no se soporta en v1" in mensaje


def test_ead_ccf_ambas_fuentes_levanta() -> None:
    """``ead.method='ccf'`` no admite ccf_col y ccf_value a la vez."""
    with pytest.raises(IfrsConfigError, match="ccf_col o ccf_value"):
        IfrsEadConfig(method="ccf", ccf_col="ccf", ccf_value=0.5)


def test_ead_ccf_fuente_unica_ok() -> None:
    """``ead.method='ccf'`` admite exactamente una fuente CCF (col o value)."""
    assert IfrsEadConfig(method="ccf", ccf_col="ccf").ccf_col == "ccf"
    assert IfrsEadConfig(method="ccf", ccf_value=0.4).ccf_value == 0.4


def test_ead_default_y_provided_construyen() -> None:
    """El default (ccf sin fuente) y ``method='provided'`` construyen sin argumentos extra."""
    assert IfrsEadConfig().method == "ccf"
    assert IfrsEadConfig(method="provided").method == "provided"


# ─────────────────────────── validaciones de staging ───────────────────────────


def test_staging_days_past_due_col_vacia_levanta() -> None:
    """``staging.days_past_due_col`` no puede quedar vacío."""
    with pytest.raises(IfrsConfigError, match="staging"):
        IfrsStagingConfig(days_past_due_col=" ")


def test_staging_columna_opcional_vacia_levanta() -> None:
    """Una columna opcional de staging no puede quedar en blanco si se informa."""
    with pytest.raises(IfrsConfigError, match="staging"):
        IfrsStagingConfig(rating_col=" ")


def test_staging_dpd_default_menor_que_sicr_levanta() -> None:
    """``dpd_default_backstop`` debe ser >= ``dpd_sicr_backstop``."""
    with pytest.raises(IfrsConfigError, match="dpd_default_backstop"):
        IfrsStagingConfig(dpd_sicr_backstop=60, dpd_default_backstop=45)


def test_staging_notch_sin_rating_actual_levanta() -> None:
    """El downgrade por notches exige ``rating_col``."""
    with pytest.raises(IfrsConfigError, match="notch_downgrade_threshold"):
        IfrsStagingConfig(notch_downgrade_threshold=2, origination_rating_col="rating_origen")


def test_staging_notch_sin_rating_origen_levanta() -> None:
    """El downgrade por notches exige ``origination_rating_col`` (segunda columna de rating)."""
    with pytest.raises(IfrsConfigError, match="notch_downgrade_threshold"):
        IfrsStagingConfig(notch_downgrade_threshold=2, rating_col="rating")


def test_staging_notch_con_ambos_ratings_ok() -> None:
    """El downgrade por notches con ambas columnas de rating construye."""
    cfg = IfrsStagingConfig(
        notch_downgrade_threshold=2, rating_col="rating", origination_rating_col="rating_origen"
    )
    assert cfg.notch_downgrade_threshold == 2


# ─────────────────────────── validaciones de escenarios ───────────────────────────


def test_scenarios_source_config_weights_vacios_levanta() -> None:
    """``scenarios.source='config'`` exige weights no vacíos."""
    with pytest.raises(IfrsConfigError, match="weights no vacíos"):
        IfrsScenarioConfig(source="config")


def test_scenarios_weights_nombre_vacio_levanta() -> None:
    """Los pesos de escenario no pueden tener nombres vacíos."""
    with pytest.raises(IfrsConfigError, match="nombres de escenario vacíos"):
        IfrsScenarioConfig(source="config", weights={" ": 1.0})


def test_scenarios_weights_no_finito_levanta() -> None:
    """Los pesos de escenario deben ser finitos."""
    with pytest.raises(IfrsConfigError, match="pesos finitos"):
        IfrsScenarioConfig(source="config", weights={"base": math.inf})


def test_scenarios_weights_no_positivos_levanta() -> None:
    """Los pesos de escenario deben ser estrictamente positivos."""
    with pytest.raises(IfrsConfigError, match="estrictamente positivos"):
        IfrsScenarioConfig(source="config", weights={"base": 1.5, "adverso": -0.5})


def test_scenarios_weights_no_suman_uno_levanta() -> None:
    """Los pesos de escenario deben sumar 1."""
    with pytest.raises(IfrsConfigError, match="debe sumar 1"):
        IfrsScenarioConfig(source="config", weights={"base": 0.6, "adverso": 0.3})


def test_scenarios_source_config_valido_ok() -> None:
    """``scenarios.source='config'`` con pesos válidos construye."""
    cfg = IfrsScenarioConfig(source="config", weights={"base": 0.7, "adverso": 0.3})
    assert cfg.weights == {"base": 0.7, "adverso": 0.3}


@pytest.mark.parametrize("source", ["forward", "single"])
def test_scenarios_source_no_config_ignora_weights(source: str) -> None:
    """Con ``source`` distinto de config no se validan los pesos (se ignoran)."""
    assert IfrsScenarioConfig(source=source).source == source


# ─────────────────────────── validaciones de ECL ───────────────────────────


def test_ecl_eir_col_vacia_levanta() -> None:
    """``ecl.eir_col`` no puede quedar vacío."""
    with pytest.raises(IfrsConfigError, match="ecl"):
        IfrsEclConfig(eir_col=" ")


# ─────────────────────────── validaciones raíz + PIT/Vasicek ───────────────────────────


@pytest.mark.parametrize("field", ["as_of_date_col", "portfolio_col"])
def test_root_columnas_vacias_levantan(field: str) -> None:
    """Las columnas raíz no pueden quedar vacías."""
    with pytest.raises(IfrsConfigError, match="provisioning_ifrs9"):
        IfrsProvisioningConfig(**{field: " "})


def test_root_row_id_col_vacia_levanta() -> None:
    """``row_id_col`` no puede quedar en blanco si se informa."""
    with pytest.raises(IfrsConfigError, match="provisioning_ifrs9"):
        IfrsProvisioningConfig(row_id_col=" ")


def test_apply_vasicek_sin_rho_levanta() -> None:
    """``pit_mode='apply_vasicek'`` exige rho o rho_col cuando se falla ante FALTA-DATO."""
    with pytest.raises(IfrsConfigError, match="rho"):
        IfrsProvisioningConfig(pd=IfrsPdConfig(pit_mode="apply_vasicek", systemic_factor_col="z"))


def test_apply_vasicek_sin_factor_sistemico_levanta() -> None:
    """``pit_mode='apply_vasicek'`` exige systemic_factor_col o escenarios forward para Z."""
    with pytest.raises(IfrsConfigError, match="systemic_factor_col"):
        IfrsProvisioningConfig(
            pd=IfrsPdConfig(pit_mode="apply_vasicek", rho=0.15),
            scenarios=IfrsScenarioConfig(source="single"),
        )


def test_apply_vasicek_completo_ok() -> None:
    """``pit_mode='apply_vasicek'`` con rho y factor sistémico construye."""
    cfg = IfrsProvisioningConfig(
        pd=IfrsPdConfig(pit_mode="apply_vasicek", rho=0.15, systemic_factor_col="z")
    )
    assert cfg.pd.pit_mode == "apply_vasicek"


def test_apply_vasicek_rho_con_escenarios_forward_ok() -> None:
    """``pit_mode='apply_vasicek'`` con rho y Z desde escenarios forward construye."""
    cfg = IfrsProvisioningConfig(
        pd=IfrsPdConfig(pit_mode="apply_vasicek", rho=0.15),
        scenarios=IfrsScenarioConfig(source="forward"),
    )
    assert cfg.scenarios.source == "forward"


def test_apply_vasicek_sin_fail_on_falta_dato_no_valida() -> None:
    """Con ``fail_on_falta_dato=False`` la brecha Vasicek se difiere (no falla en config)."""
    cfg = IfrsProvisioningConfig(
        pd=IfrsPdConfig(pit_mode="apply_vasicek"),
        scenarios=IfrsScenarioConfig(source="single"),
        fail_on_falta_dato=False,
    )
    assert cfg.pd.rho is None


# ─────────────────────────── restricciones Pydantic ───────────────────────────


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (IfrsPdConfig, "term_structure_source", "cohort"),
        (IfrsPdConfig, "pit_mode", "raw"),
        (IfrsPdConfig, "rho", 1.0),
        (IfrsPdConfig, "rho", -0.1),
        (IfrsPdConfig, "horizon_12m_periods", 0),
        (IfrsLgdConfig, "method", "ols"),
        (IfrsLgdConfig, "lgd_floor", 1.5),
        (IfrsEadConfig, "method", "ead_direct"),
        (IfrsEadConfig, "ccf_value", 1.5),
        (IfrsStagingConfig, "sicr_pd_ratio_threshold", 1.0),
        (IfrsStagingConfig, "dpd_sicr_backstop", -1),
        (IfrsStagingConfig, "notch_downgrade_threshold", 0),
        (IfrsScenarioConfig, "source", "mean"),
        (IfrsEclConfig, "discount_convention", "quarterly"),
        (IfrsProvisioningConfig, "type", "internal"),
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


def test_config_hash_default_con_provisioning_ifrs9_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``provisioning_ifrs9=None``."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_se_movio_por_seccion_ifrs9() -> None:
    """Añadir ``provisioning_ifrs9`` movió el golden respecto al valor previo (no es regresión)."""
    assert GOLDEN_DEFAULT_CONFIG_HASH != GOLDEN_PREVIO_SIN_IFRS9
    assert config_hash(NikodymConfig()) != GOLDEN_PREVIO_SIN_IFRS9


@pytest.mark.parametrize(
    "provisioning",
    [
        IfrsProvisioningConfig(pd=IfrsPdConfig(term_structure_source="markov")),
        IfrsProvisioningConfig(pd=IfrsPdConfig(rho=0.15)),
        IfrsProvisioningConfig(pd=IfrsPdConfig(pit_mode="ttc_only")),
        IfrsProvisioningConfig(staging=IfrsStagingConfig(sicr_pd_ratio_threshold=2.5)),
        IfrsProvisioningConfig(
            scenarios=IfrsScenarioConfig(source="config", weights={"base": 0.7, "adverso": 0.3})
        ),
        IfrsProvisioningConfig(ecl=IfrsEclConfig(discount_convention="period_eir")),
    ],
)
def test_config_hash_cambia_al_variar_provisioning_ifrs9(
    provisioning: IfrsProvisioningConfig,
) -> None:
    """``provisioning_ifrs9`` no es INFRA: source/rho/pit/SICR/pesos/descuento cambian el hash."""
    base = config_hash(NikodymConfig(provisioning_ifrs9=IfrsProvisioningConfig()))
    variado = config_hash(NikodymConfig(provisioning_ifrs9=provisioning))
    assert "provisioning_ifrs9" not in INFRA_SECTIONS
    assert variado != base


# ─────────────────────────── metadata UI + API pública ───────────────────────────


def test_campos_ifrs9_tienen_metadatos_ui() -> None:
    """Todos los campos de config IFRS 9 declaran metadata de UI para SDD-23."""
    for modelo in (
        IfrsPdConfig,
        IfrsLgdConfig,
        IfrsEadConfig,
        IfrsStagingConfig,
        IfrsScenarioConfig,
        IfrsEclConfig,
        IfrsProvisioningConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_ifrs9_public_api_minimo() -> None:
    """El paquete IFRS 9 expone config y excepciones de B16.1."""
    assert ifrs9_pkg.IfrsProvisioningConfig is IfrsProvisioningConfig
    assert ifrs9_pkg.IfrsTermStructureError is IfrsTermStructureError
    assert "IfrsProvisioningConfig" in ifrs9_pkg.__all__


def test_ifrs9_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``provisioning.ifrs9`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        IfrsProvisioningError,
        IfrsConfigError,
        IfrsInputError,
        IfrsTermStructureError,
        IfrsPdError,
        IfrsLgdError,
        IfrsEadError,
        IfrsStagingError,
        IfrsEclError,
    ):
        assert issubclass(error_cls, NikodymError)
    assert issubclass(IfrsTermStructureError, IfrsInputError)


# ─────────────────────────── import liviano ───────────────────────────


def test_import_provisioning_ifrs9_config_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.provisioning.ifrs9.config`` registra hook sin arrastrar stack pesado."""
    code = (
        "import nikodym.provisioning.ifrs9.config, nikodym.core, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.provisioning.ifrs9.config import IfrsProvisioningConfig;"
        "bloqueados=[m for m in "
        "('nikodym.data','pandera','pyarrow','pandas','scipy','statsmodels',"
        "'nikodym.tracking','mlflow') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(provisioning_ifrs9={'ecl': {'rounding': 'currency_2dp'}});"
        "assert isinstance(cfg.provisioning_ifrs9, IfrsProvisioningConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_provisioning_ifrs9_como_blob_opaco_sin_importar_ifrs9() -> None:
    """El core acepta ``provisioning_ifrs9`` JSON/dict sin importar la capa IFRS 9."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(provisioning_ifrs9={'ecl': {'rounding': 'integer_currency'}});"
        "assert cfg.provisioning_ifrs9 == {'ecl': {'rounding': 'integer_currency'}};"
        "assert 'nikodym.provisioning.ifrs9' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
