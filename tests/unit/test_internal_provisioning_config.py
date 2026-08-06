"""Tests de ``InternalProvisioningConfig``: invariantes cruzados y cableado con ``NikodymConfig``.

Un enum declarado sin ruta real degrada en silencio y una columna declarada que el motor nunca abre
es una mentira del config: ambas cosas se validan aquí (SDD-28 §5.1).
"""

from __future__ import annotations

from typing import Annotated, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from nikodym.core.config import NikodymConfig
from nikodym.core.config.hashing import INFRA_SECTIONS
from nikodym.provisioning.internal import (
    InternalConfigError,
    InternalLgdGroupHistorical,
    InternalLgdProvided,
    InternalProvisioningConfig,
)


def test_defaults_del_metodo_interno() -> None:
    """Los defaults son los de SDD-28 §5.1: PD calibrada, bandas de score y pd_lgd."""
    cfg = InternalProvisioningConfig()

    assert cfg.schema_version == "1.0.0"
    assert cfg.type == "standard"
    assert cfg.as_of_date_col == "as_of_date"
    assert cfg.portfolio_col == "portfolio"
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
    assert cfg.lgd == InternalLgdProvided(lgd_col="lgd", lgd_floor=0.0, lgd_cap=1.0)


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
    """La LGD exige columna no vacía y ``lgd_floor <= lgd_cap``, en TODA rama de la unión.

    Las validaciones viven en la base común (D-LGD-1), así que se comprueban sobre las dos ramas:
    un validador que sólo cubriera la rama por defecto dejaría la otra sin red, y la forma de la
    unión existe precisamente para que las ramas crezcan.
    """
    for rama in (InternalLgdProvided, InternalLgdGroupHistorical):
        with pytest.raises(InternalConfigError, match="lgd_col no puede estar vacío"):
            rama(lgd_col=" ")
        with pytest.raises(InternalConfigError, match="no puede superar"):
            rama(lgd_floor=0.6, lgd_cap=0.5)
        with pytest.raises(ValidationError):
            rama(lgd_cap=1.5)
        with pytest.raises(ValidationError):
            rama(lgd_floor=-0.1)

    cfg = InternalLgdGroupHistorical(lgd_floor=0.1, lgd_cap=0.9)
    assert cfg.method == "group_historical"


def test_la_lgd_se_contesta_eligiendo_una_forma_y_el_discriminador_manda() -> None:
    """La sección se coacciona a la RAMA que nombra `method`, no a una clase plana (D-LGD-1)."""
    cfg = InternalProvisioningConfig.model_validate(
        {"lgd": {"method": "group_historical", "lgd_col": "severidad"}}
    )
    assert isinstance(cfg.lgd, InternalLgdGroupHistorical)
    assert cfg.lgd.lgd_col == "severidad"
    # Un `method` que no es rama no cae en una rama por defecto: la unión lo rechaza.
    with pytest.raises(ValidationError):
        InternalProvisioningConfig.model_validate({"lgd": {"method": "inexistente"}})


def test_seccion_es_computacional_y_se_coacciona_desde_dict() -> None:
    """``provisioning_internal`` entra al ``config_hash`` y se valida como sub-config real."""
    assert "provisioning_internal" not in INFRA_SECTIONS

    root = NikodymConfig(provisioning_internal={"grouping": "segment", "group_col": "segmento"})

    assert isinstance(root.provisioning_internal, InternalProvisioningConfig)
    assert root.provisioning_internal.group_col == "segmento"
    assert NikodymConfig().provisioning_internal is None

    ya_validado = InternalProvisioningConfig()
    assert NikodymConfig(provisioning_internal=ya_validado).provisioning_internal is ya_validado


def _es_union_de_submodelos(anotacion: object) -> bool:
    """``True`` si el campo es una unión discriminada de submodelos (y no un simple escalar)."""
    if get_origin(anotacion) is Annotated:
        anotacion = get_args(anotacion)[0]
    ramas = [
        rama
        for rama in get_args(anotacion)
        if isinstance(rama, type) and issubclass(rama, BaseModel)
    ]
    return len(ramas) > 1


def test_ui_metadata_en_cada_campo() -> None:
    """Cada campo declara ``title`` y metadatos ``ui_*``: la UI es un editor del mismo config.

    🔴 Con UNA excepción, que este gate convierte en regla en vez de en agujero: **un campo cuyo
    schema es una unión discriminada NO puede declarar `ui_widget`**. En `form-engine.ts` el alias
    del campo se resuelve ANTES de mirar el discriminador, así que cualquier widget declarado gana
    sobre el renderizador de uniones; con `section` —el que este campo traía— el mapeo cae en
    `group`, que sobre una unión no encuentra `properties` y pinta el fieldset «Sin campos.». Es el
    defecto que `form-engine.ts` ya documenta para `binning.variable_overrides`, y el precedente
    vivo —`PartitionConfig.strategy`— declara `ui_help` y ningún widget.

    Escrito como regla y no como lista de exentos: el día que nazca otra unión, el gate la cubre
    sola. Y se comprueba en los DOS sentidos, para que «no declara widget» no se confunda con «no
    declara nada».
    """
    for name, field in InternalProvisioningConfig.model_fields.items():
        assert field.title, name
        assert field.description, name
        extra = field.json_schema_extra
        assert isinstance(extra, dict), name
        assert {"ui_group", "ui_order"} <= set(extra), name
        if _es_union_de_submodelos(field.annotation):
            assert "ui_widget" not in extra, (
                f"{name}: una unión discriminada no puede declarar ui_widget — el alias gana sobre "
                "el renderizador de uniones y el formulario sale con «Sin campos.»"
            )
            assert extra.get("ui_help"), f"{name}: sin widget, la ayuda es lo único que orienta"
        else:
            assert "ui_widget" in extra, name
