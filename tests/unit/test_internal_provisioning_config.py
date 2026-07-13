"""Tests de ``InternalProvisioningConfig``: invariantes cruzados y cableado con ``NikodymConfig``.

Un enum declarado sin ruta real degrada en silencio y una columna declarada que el motor nunca abre
es una mentira del config: ambas cosas se validan aquí (SDD-28 §5.1).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nikodym.core.config import NikodymConfig
from nikodym.core.config.hashing import INFRA_SECTIONS
from nikodym.provisioning.internal import (
    InternalConfigError,
    InternalLgdConfig,
    InternalProvisioningConfig,
)


def test_defaults_del_metodo_interno() -> None:
    """Los defaults son los de SDD-28 §5.1: PD calibrada, bandas de score y pd_lgd."""
    cfg = InternalProvisioningConfig()

    assert cfg.schema_version == "1.0.0"
    assert cfg.type == "standard"
    assert cfg.as_of_date_col == "as_of_date"
    assert cfg.portfolio_col == "cmf_portfolio"
    assert cfg.exposure_col == "exposure_amount"
    assert cfg.pd_source == "calibration"
    assert cfg.pd_column == "pd_calibrated"
    assert cfg.grouping == "score_band"
    assert cfg.group_col is None
    assert cfg.n_score_bands == 10
    assert cfg.method == "pd_lgd"
    assert cfg.loss_rate_col is None
    assert cfg.rounding == "currency_2dp"
    assert cfg.fail_on_falta_dato is True
    assert cfg.lgd == InternalLgdConfig(
        method="provided", lgd_col="lgd", lgd_floor=0.0, lgd_cap=1.0
    )


def test_config_es_cerrado_y_frozen() -> None:
    """``extra='forbid'`` y ``frozen=True`` heredados de ``NikodymBaseConfig``."""
    with pytest.raises(ValidationError):
        InternalProvisioningConfig(campo_inexistente=1)

    cfg = InternalProvisioningConfig()
    with pytest.raises(ValidationError):
        cfg.n_score_bands = 5


@pytest.mark.parametrize("grouping", ["segment", "provided"])
def test_grouping_con_grupo_declarado_exige_group_col(grouping: str) -> None:
    """``segment``/``provided`` leen ``group_col``: sin ella el modo no tendría ruta real."""
    with pytest.raises(InternalConfigError, match="exige group_col"):
        InternalProvisioningConfig(grouping=grouping)
    with pytest.raises(InternalConfigError, match="exige group_col"):
        InternalProvisioningConfig(grouping=grouping, group_col="   ")

    cfg = InternalProvisioningConfig(grouping=grouping, group_col="segmento")
    assert cfg.group_col == "segmento"


def test_score_band_prohibe_group_col() -> None:
    """Declarar una columna que el motor nunca abre es una mentira del config."""
    with pytest.raises(InternalConfigError, match="nunca lee group_col"):
        InternalProvisioningConfig(grouping="score_band", group_col="segmento")


def test_direct_loss_rate_exige_loss_rate_col_y_pd_lgd_la_prohibe() -> None:
    """Los dos métodos del B-1 §3 exigen exactamente las columnas que leen."""
    with pytest.raises(InternalConfigError, match="exige loss_rate_col"):
        InternalProvisioningConfig(method="direct_loss_rate")
    with pytest.raises(InternalConfigError, match="exige loss_rate_col"):
        InternalProvisioningConfig(method="direct_loss_rate", loss_rate_col=" ")
    with pytest.raises(InternalConfigError, match="nunca lee loss_rate_col"):
        InternalProvisioningConfig(method="pd_lgd", loss_rate_col="tasa")

    cfg = InternalProvisioningConfig(method="direct_loss_rate", loss_rate_col="tasa_perdida")
    assert cfg.loss_rate_col == "tasa_perdida"


@pytest.mark.parametrize(
    "campo",
    ["as_of_date_col", "portfolio_col", "exposure_col", "pd_column"],
)
def test_columnas_raiz_no_pueden_estar_vacias(campo: str) -> None:
    """Un nombre de columna vacío es un config roto, no un default silencioso."""
    with pytest.raises(InternalConfigError, match=f"no pueden estar vacíos.*{campo}"):
        InternalProvisioningConfig(**{campo: "  "})


def test_n_score_bands_minimo_dos() -> None:
    """Menos de dos bandas no es una segmentación."""
    with pytest.raises(ValidationError):
        InternalProvisioningConfig(n_score_bands=1)


def test_lgd_config_valida_columna_y_piso_techo() -> None:
    """La LGD exige columna no vacía y ``lgd_floor <= lgd_cap``."""
    with pytest.raises(InternalConfigError, match="lgd_col no puede estar vacío"):
        InternalLgdConfig(lgd_col=" ")
    with pytest.raises(InternalConfigError, match="no puede superar"):
        InternalLgdConfig(lgd_floor=0.6, lgd_cap=0.5)
    with pytest.raises(ValidationError):
        InternalLgdConfig(lgd_cap=1.5)
    with pytest.raises(ValidationError):
        InternalLgdConfig(lgd_floor=-0.1)

    cfg = InternalLgdConfig(method="group_historical", lgd_floor=0.1, lgd_cap=0.9)
    assert cfg.method == "group_historical"


def test_seccion_es_computacional_y_se_coacciona_desde_dict() -> None:
    """``provisioning_internal`` entra al ``config_hash`` y se valida como sub-config real."""
    assert "provisioning_internal" not in INFRA_SECTIONS

    root = NikodymConfig(provisioning_internal={"grouping": "segment", "group_col": "segmento"})

    assert isinstance(root.provisioning_internal, InternalProvisioningConfig)
    assert root.provisioning_internal.group_col == "segmento"
    assert NikodymConfig().provisioning_internal is None

    ya_validado = InternalProvisioningConfig()
    assert NikodymConfig(provisioning_internal=ya_validado).provisioning_internal is ya_validado


def test_ui_metadata_en_cada_campo() -> None:
    """Cada campo declara ``title`` y metadatos ``ui_*``: la UI es un editor del mismo config."""
    for name, field in InternalProvisioningConfig.model_fields.items():
        assert field.title, name
        assert field.description, name
        extra = field.json_schema_extra
        assert isinstance(extra, dict), name
        assert {"ui_widget", "ui_group", "ui_order"} <= set(extra), name
