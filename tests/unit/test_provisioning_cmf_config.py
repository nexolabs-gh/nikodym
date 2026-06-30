"""Tests de ``CmfProvisioningConfig`` (SDD-15 §5) e integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from hypothesis import given, settings
from pydantic import ValidationError

import nikodym.provisioning.cmf as cmf_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.provisioning.cmf.config import (
    CmfExposureConfig,
    CmfGuaranteeConfig,
    CmfMatrixConfig,
    CmfPdMappingConfig,
    CmfProvisioningConfig,
)
from nikodym.provisioning.cmf.exceptions import (
    CmfCalculationError,
    CmfConfigError,
    CmfInputError,
    CmfMappingError,
    CmfMatrixError,
    CmfMissingRegulatoryDataError,
    CmfProvisioningError,
)
from nikodym.testing.strategies import _config_cls_for_domain, nikodym_config_strategy

GOLDEN_DEFAULT_CONFIG_HASH = "145f9c1d1d7674f0aec6c435774649ac97b7e98aad656b4f6e171155f15b747e"


@pytest.fixture(autouse=True)
def _capa_provisioning_cmf_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_CMF_CONFIG_CLS", CmfProvisioningConfig)


def _cmf_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-15 §5."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "as_of_date_col": "as_of_date",
        "portfolio_col": "cmf_portfolio",
        "debtor_id_col": "debtor_id",
        "category_col": "cmf_category",
        "days_past_due_col": "days_past_due",
        "product_type_col": "cmf_product_type",
        "matrices": {
            "active_version": "cmf_b1_b3_2025_01",
            "require_verified_rows": True,
            "fail_on_unmapped_contingent_type": True,
            "fail_on_source_mismatch": True,
        },
        "pd_mapping": {
            "pd_source_domain": "model",
            "pd_source_key": "raw_pd_frame",
            "pd_column": "pd_raw",
            "method": "provided_cmf_category",
            "pd_breaks": [],
            "categories": [],
        },
        "exposure": {
            "direct_exposure_col": "exposure_amount",
            "contingent_amount_col": "contingent_amount",
            "contingent_type_col": "contingent_type",
            "is_default_col": "is_default",
            "allow_negative_exposure": False,
            "rounding": "none",
        },
        "guarantees": {
            "enable_aval_substitution": True,
            "financial_guarantee_policy": "fail",
            "recoverable_amount_col": None,
            "require_recoverable_for_default": True,
        },
    }


def test_cmfprovisioningconfig_defaults_golden() -> None:
    """``CmfProvisioningConfig()`` construye sin argumentos y coincide con el golden."""
    assert CmfProvisioningConfig().model_dump(mode="json") == _cmf_defaults()


def test_round_trip_yaml_cmfprovisioningconfig() -> None:
    """Serializar y recargar ``CmfProvisioningConfig`` por YAML preserva igualdad exacta."""
    cfg = CmfProvisioningConfig(
        as_of_date_col="fecha_cierre",
        portfolio_col="cartera_cmf",
        debtor_id_col="rut_deudor",
        category_col="categoria_cmf",
        days_past_due_col="dias_mora",
        product_type_col="producto_cmf",
        matrices=CmfMatrixConfig(
            active_version="cmf_b1_b3_2025_01",
            require_verified_rows=False,
            fail_on_unmapped_contingent_type=False,
        ),
        pd_mapping=CmfPdMappingConfig(
            pd_source_domain="calibration",
            pd_source_key="calibrated_pd_frame",
            pd_column="pd_calibrated",
            method="pd_breaks",
            pd_breaks=(0.02, 0.10, 0.30),
            categories=("A1", "A4", "B2", "B4"),
        ),
        exposure=CmfExposureConfig(
            direct_exposure_col="saldo",
            contingent_amount_col="contingente",
            contingent_type_col="tipo_contingente",
            is_default_col="incumplimiento",
            allow_negative_exposure=True,
            rounding="currency_2dp",
        ),
        guarantees=CmfGuaranteeConfig(
            financial_guarantee_policy="use_recoverable_amount",
            recoverable_amount_col="recoverable_amount",
        ),
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert CmfProvisioningConfig.model_validate(yaml.safe_load(text)) == cfg


def test_nikodymconfig_provisioning_cmf_instancia() -> None:
    """Pasar una instancia ``CmfProvisioningConfig`` a ``NikodymConfig`` la conserva."""
    provisioning = CmfProvisioningConfig()
    cfg = NikodymConfig(provisioning_cmf=provisioning)
    assert isinstance(cfg.provisioning_cmf, CmfProvisioningConfig)
    assert cfg.provisioning_cmf is provisioning


def test_nikodymconfig_provisioning_cmf_dict_coacciona() -> None:
    """Un dict en ``provisioning_cmf`` se coacciona por el hook cargado."""
    cfg = NikodymConfig(provisioning_cmf={"exposure": {"rounding": "integer_currency"}})
    assert isinstance(cfg.provisioning_cmf, CmfProvisioningConfig)
    assert cfg.provisioning_cmf.exposure.rounding == "integer_currency"


def test_nikodymconfig_provisioning_cmf_none_explicito() -> None:
    """``provisioning_cmf=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(provisioning_cmf=None).provisioning_cmf is None


def test_nikodymconfig_provisioning_cmf_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``provisioning_cmf`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_CMF_CONFIG_CLS", None)
    cfg = NikodymConfig(provisioning_cmf={"exposure": {"rounding": "integer_currency"}})
    assert cfg.provisioning_cmf == {"exposure": {"rounding": "integer_currency"}}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_provisioning_cmf_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``provisioning_cmf`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_CMF_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(provisioning_cmf=blob)


def test_pd_breaks_validos_normalizan_menos_cero() -> None:
    """``pd_breaks`` acepta cortes crecientes y normaliza ``-0.0`` a ``0.0``."""
    cfg = CmfPdMappingConfig(
        method="pd_breaks",
        pd_breaks=(-0.0, 0.10),
        categories=("A1", "A3", "B2"),
    )
    assert cfg.pd_breaks == (0.0, 0.10)


def test_pd_breaks_no_finito_levanta_cmfconfigerror() -> None:
    """``pd_breaks`` rechaza floats no finitos antes de entrar al hash."""
    with pytest.raises(CmfConfigError, match="números finitos"):
        CmfPdMappingConfig._normaliza_pd_breaks((math.nan,))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        (
            {"method": "pd_breaks", "pd_breaks": (0.20, 0.10), "categories": ("A1", "B1", "B4")},
            "estrictamente creciente",
        ),
        (
            {"method": "pd_breaks", "pd_breaks": (0.20,), "categories": ("A1",)},
            "len\\(categories\\)",
        ),
        (
            {"method": "pd_breaks", "pd_breaks": (0.20,), "categories": ("A1", " ")},
            "categorías CMF",
        ),
        ({"pd_source_key": " "}, "pd_mapping"),
    ],
)
def test_pd_mapping_invalido_levanta_cmfconfigerror(
    kwargs: dict[str, object],
    match: str,
) -> None:
    """Las reglas de ``pd_breaks`` y columnas PD fallan con ``CmfConfigError``."""
    with pytest.raises(CmfConfigError, match=match):
        CmfPdMappingConfig(**kwargs)


def test_provided_cmf_category_exige_category_col_no_vacio() -> None:
    """El modo standalone exige ``category_col`` no vacío en config."""
    cfg = CmfProvisioningConfig(category_col="cmf_category")
    assert cfg.pd_mapping.method == "provided_cmf_category"
    with pytest.raises(CmfConfigError, match="category_col"):
        CmfProvisioningConfig(category_col=" ")


def test_fail_on_unmapped_contingent_type_presente_y_bool() -> None:
    """``fail_on_unmapped_contingent_type`` existe, default True y exige booleano."""
    cfg = CmfMatrixConfig()
    assert cfg.fail_on_unmapped_contingent_type is True
    assert (
        CmfMatrixConfig(fail_on_unmapped_contingent_type=False).fail_on_unmapped_contingent_type
        is False
    )
    with pytest.raises(ValidationError):
        CmfMatrixConfig(fail_on_unmapped_contingent_type=None)  # type: ignore[arg-type]


def test_allow_negative_exposure_default_false_y_bool() -> None:
    """``allow_negative_exposure`` default False y exige booleano."""
    cfg = CmfExposureConfig()
    assert cfg.allow_negative_exposure is False
    assert CmfExposureConfig(allow_negative_exposure=True).allow_negative_exposure is True
    with pytest.raises(ValidationError):
        CmfExposureConfig(allow_negative_exposure=None)  # type: ignore[arg-type]


def test_use_recoverable_amount_exige_recoverable_amount_col() -> None:
    """La política ``use_recoverable_amount`` exige columna de recupero definida."""
    valid = CmfGuaranteeConfig(
        financial_guarantee_policy="use_recoverable_amount",
        recoverable_amount_col="recoverable_amount",
    )
    assert valid.recoverable_amount_col == "recoverable_amount"
    with pytest.raises(CmfConfigError, match="recoverable_amount_col"):
        CmfGuaranteeConfig(financial_guarantee_policy="use_recoverable_amount")
    with pytest.raises(CmfConfigError, match="vacío"):
        CmfGuaranteeConfig(recoverable_amount_col=" ")


@pytest.mark.parametrize(
    ("factory", "kwargs", "match"),
    [
        (CmfProvisioningConfig, {"as_of_date_col": " "}, "provisioning_cmf"),
        (CmfExposureConfig, {"direct_exposure_col": " "}, "exposure"),
    ],
)
def test_columnas_vacias_levantan_cmfconfigerror(
    factory: type[CmfProvisioningConfig] | type[CmfExposureConfig],
    kwargs: dict[str, object],
    match: str,
) -> None:
    """Las columnas declarativas no pueden quedar vacías."""
    with pytest.raises(CmfConfigError, match=match):
        factory(**kwargs)


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (CmfPdMappingConfig, "pd_source_domain", "tracking"),
        (CmfPdMappingConfig, "method", "pd_direct"),
        (CmfPdMappingConfig, "pd_breaks", (-0.01,)),
        (CmfExposureConfig, "rounding", "pesos"),
        (CmfGuaranteeConfig, "financial_guarantee_policy", "estimate"),
        (CmfProvisioningConfig, "type", "internal"),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    factory: type[CmfPdMappingConfig]
    | type[CmfExposureConfig]
    | type[CmfGuaranteeConfig]
    | type[CmfProvisioningConfig],
    field: str,
    value: object,
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        factory(**{field: value})


@pytest.mark.parametrize(
    "provisioning",
    [
        CmfProvisioningConfig(
            matrices=CmfMatrixConfig(active_version="cmf_b1_b3_2026_01"),
        ),
        CmfProvisioningConfig(
            pd_mapping=CmfPdMappingConfig(
                method="pd_breaks",
                pd_breaks=(0.05,),
                categories=("A1", "B1"),
            ),
        ),
        CmfProvisioningConfig(
            pd_mapping=CmfPdMappingConfig(
                method="pd_breaks",
                pd_breaks=(0.10,),
                categories=("A1", "B1"),
            ),
        ),
        CmfProvisioningConfig(
            guarantees=CmfGuaranteeConfig(financial_guarantee_policy="ignore_if_missing"),
        ),
        CmfProvisioningConfig(exposure=CmfExposureConfig(rounding="integer_currency")),
    ],
)
def test_config_hash_cambia_al_variar_provisioning_cmf(
    provisioning: CmfProvisioningConfig,
) -> None:
    """``provisioning_cmf`` no es INFRA: matrices, mapping, garantías y redondeo cambian hash."""
    base = config_hash(NikodymConfig(provisioning_cmf=CmfProvisioningConfig()))
    variado = config_hash(NikodymConfig(provisioning_cmf=provisioning))
    assert "provisioning_cmf" not in INFRA_SECTIONS
    assert variado != base


@settings(max_examples=12, deadline=None)
@given(cfg=nikodym_config_strategy(sections=["provisioning_cmf"]))
def test_nikodym_config_strategy_genera_configs_provisioning_cmf_validos(
    cfg: NikodymConfig,
) -> None:
    """La estrategia pública genera configs raíz válidos con ``provisioning_cmf`` activo."""
    assert isinstance(cfg.provisioning_cmf, CmfProvisioningConfig)
    assert cfg.provisioning_cmf.type == "standard"
    assert loads_config(dump_config(cfg)) == cfg


def test_campos_cmf_tienen_metadatos_ui() -> None:
    """Todos los campos de config CMF declaran metadata de UI para SDD-23."""
    for modelo in (
        CmfMatrixConfig,
        CmfPdMappingConfig,
        CmfExposureConfig,
        CmfGuaranteeConfig,
        CmfProvisioningConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_cmf_public_api_minimo() -> None:
    """El paquete CMF expone config y excepciones de B15.2."""
    assert cmf_pkg.CmfProvisioningConfig is CmfProvisioningConfig
    assert cmf_pkg.CmfMatrixError is CmfMatrixError
    assert "CmfProvisioningConfig" in cmf_pkg.__all__


def test_cmf_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``provisioning.cmf`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        CmfProvisioningError,
        CmfConfigError,
        CmfInputError,
        CmfMappingError,
        CmfMatrixError,
        CmfMissingRegulatoryDataError,
        CmfCalculationError,
    ):
        assert issubclass(error_cls, NikodymError)
    assert issubclass(CmfMissingRegulatoryDataError, CmfMatrixError)


def test_import_provisioning_cmf_config_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.provisioning.cmf.config`` registra hook sin arrastrar stack pesado."""
    code = (
        "import nikodym.provisioning.cmf.config, nikodym.core, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.provisioning.cmf.config import CmfProvisioningConfig;"
        "bloqueados=[m for m in "
        "('nikodym.data','pandera','pyarrow','pandas','nikodym.tracking','mlflow') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "assert 'nikodym.provisioning.cmf.matrices' not in sys.modules;"
        "cfg=NikodymConfig(provisioning_cmf={'exposure': {'rounding': 'currency_2dp'}});"
        "assert isinstance(cfg.provisioning_cmf, CmfProvisioningConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_provisioning_cmf_como_blob_opaco_sin_importar_cmf() -> None:
    """El core acepta ``provisioning_cmf`` JSON/dict sin importar la capa CMF."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(provisioning_cmf={'exposure': {'rounding': 'integer_currency'}});"
        "assert cfg.provisioning_cmf == {'exposure': {'rounding': 'integer_currency'}};"
        "assert 'nikodym.provisioning.cmf' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_config_cls_for_domain_resuelve_provisioning_cmf() -> None:
    """El helper interno resuelve ``CmfProvisioningConfig`` cuando el hook está poblado."""
    assert _config_cls_for_domain("provisioning_cmf") is CmfProvisioningConfig


def test_config_hash_default_con_provisioning_cmf_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``provisioning_cmf`` con valor None."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH
