"""Tests de ``ProvisioningConfig`` (SDD-17 §5) e integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import nikodym.provisioning as provisioning_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.provisioning.config import ProvisioningConfig
from nikodym.provisioning.exceptions import (
    ProvisioningAlignmentError,
    ProvisioningConfigError,
    ProvisioningCoverageError,
    ProvisioningError,
    ProvisioningInputError,
)

# Golden del config_hash por defecto tras añadir la sección computacional `provisioning`.
GOLDEN_DEFAULT_CONFIG_HASH = "cbc42cfc02993f6646a744d66d2e0e348285e07761f59f434469afe2e8801610"
# Golden anterior (antes de B17.1, con provisioning_ifrs9 ya presente); el hash DEBE moverse.
GOLDEN_PREVIO_SIN_PROVISIONING = "c534dee874e28f6f6974d793dab65acaff7fa3d0bb9b0ae4d35fb318453b1af3"


@pytest.fixture(autouse=True)
def _capa_provisioning_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_CONFIG_CLS", ProvisioningConfig)


def _provisioning_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-17 §5.

    Los defaults de fuentes/regla son **retrocompatibles**: ``source_a='provisioning_cmf'`` y
    ``source_b='provisioning_ifrs9'`` reproducen el comportamiento histórico. Los ``consume_*`` de
    motor quedan DEPRECADOS y su default es ``None`` ("no informado"), no ``True``.
    """
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "source_a": "provisioning_cmf",
        "source_b": "provisioning_ifrs9",
        "rule": "max",
        "as_of_date_col": "as_of_date",
        "comparison_level": "total",
        "cmf_portfolio_col": "portfolio",
        "ifrs9_portfolio_col": "portfolio",
        "internal_portfolio_col": "portfolio",
        "portfolio_crosswalk": {},
        "segment_col": None,
        "row_id_col": "row_id",
        "consume_a": True,
        "consume_b": True,
        "consume_cmf": None,
        "consume_ifrs9": None,
        "require_both": True,
        "coverage_policy": "use_available",
        "numeric_reconciliation": "decimal_quantize",
        "tie_tolerance": 1e-9,
        "rounding": "none",
        "fail_on_falta_dato": True,
    }


def _config_no_trivial() -> ProvisioningConfig:
    """Config de orquestación no trivial que ejercita ramas válidas del schema."""
    return ProvisioningConfig(
        source_a="provisioning_cmf",
        source_b="provisioning_internal",
        rule="use_internal",
        as_of_date_col="fecha_cierre",
        comparison_level="portfolio",
        cmf_portfolio_col="cartera_cmf",
        ifrs9_portfolio_col="cartera_ifrs9",
        internal_portfolio_col="cartera_interna",
        portfolio_crosswalk={"comercial": "wholesale", "consumo": "retail"},
        segment_col="segmento",
        row_id_col="operacion_id",
        consume_a=True,
        consume_b=True,
        require_both=True,
        coverage_policy="fail",
        numeric_reconciliation="float_isclose",
        tie_tolerance=1e-6,
        rounding="currency_2dp",
        fail_on_falta_dato=False,
    )


# ─────────────────────────── defaults / round-trip ───────────────────────────


def test_provisioningconfig_defaults_golden() -> None:
    """``ProvisioningConfig()`` construye sin argumentos y coincide con el golden."""
    assert ProvisioningConfig().model_dump(mode="json") == _provisioning_defaults()


def test_round_trip_yaml_provisioningconfig() -> None:
    """Serializar y recargar ``ProvisioningConfig`` por YAML preserva igualdad exacta."""
    cfg = _config_no_trivial()
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert ProvisioningConfig.model_validate(yaml.safe_load(text)) == cfg


# ─────────────────────────── integración NikodymConfig ───────────────────────────


def test_nikodymconfig_provisioning_instancia() -> None:
    """Pasar una instancia ``ProvisioningConfig`` a ``NikodymConfig`` la conserva."""
    provisioning = ProvisioningConfig()
    cfg = NikodymConfig(provisioning=provisioning)
    assert isinstance(cfg.provisioning, ProvisioningConfig)
    assert cfg.provisioning is provisioning


def test_nikodymconfig_provisioning_dict_coacciona() -> None:
    """Un dict en ``provisioning`` se coacciona por el hook cargado."""
    cfg = NikodymConfig(provisioning={"comparison_level": "operation"})
    assert isinstance(cfg.provisioning, ProvisioningConfig)
    assert cfg.provisioning.comparison_level == "operation"


def test_nikodymconfig_provisioning_none_explicito() -> None:
    """``provisioning=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(provisioning=None).provisioning is None


def test_nikodymconfig_provisioning_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``provisioning`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_CONFIG_CLS", None)
    cfg = NikodymConfig(provisioning={"comparison_level": "total"})
    assert cfg.provisioning == {"comparison_level": "total"}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_provisioning_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``provisioning`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_PROVISIONING_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(provisioning=blob)


# ─────────────────────────── validaciones de columnas ───────────────────────────


@pytest.mark.parametrize(
    "field",
    [
        "as_of_date_col",
        "cmf_portfolio_col",
        "ifrs9_portfolio_col",
        "internal_portfolio_col",
        "row_id_col",
    ],
)
def test_columnas_raiz_vacias_levantan(field: str) -> None:
    """Las columnas raíz no pueden quedar vacías."""
    with pytest.raises(ProvisioningConfigError, match="provisioning"):
        ProvisioningConfig(**{field: " "})


def test_segment_col_vacia_si_informada_levanta() -> None:
    """``segment_col`` no puede quedar en blanco si se informa."""
    with pytest.raises(ProvisioningConfigError, match="provisioning"):
        ProvisioningConfig(segment_col=" ")


def test_operation_exige_row_id_col_presente() -> None:
    """``comparison_level='operation'`` exige ``row_id_col`` presente (alineable)."""
    with pytest.raises(ProvisioningConfigError, match="provisioning"):
        ProvisioningConfig(comparison_level="operation", row_id_col=" ")


def test_operation_con_row_id_col_construye() -> None:
    """``comparison_level='operation'`` con ``row_id_col`` presente construye."""
    cfg = ProvisioningConfig(comparison_level="operation", row_id_col="operacion_id")
    assert cfg.comparison_level == "operation"


# ─────────────────────────── validaciones de crosswalk ───────────────────────────


@pytest.mark.parametrize("crosswalk", [{"": "retail"}, {"comercial": " "}])
def test_crosswalk_clave_o_valor_vacio_levanta(crosswalk: dict[str, str]) -> None:
    """``portfolio_crosswalk`` no admite claves ni valores vacíos."""
    with pytest.raises(ProvisioningConfigError, match="portfolio_crosswalk"):
        ProvisioningConfig(portfolio_crosswalk=crosswalk)


# ─────────────────────────── nivel de comparación ───────────────────────────


def test_segment_sin_segment_col_levanta() -> None:
    """``comparison_level='segment'`` exige ``segment_col`` no nulo."""
    with pytest.raises(ProvisioningConfigError, match="segment_col no nulo"):
        ProvisioningConfig(comparison_level="segment")


def test_segment_con_segment_col_construye() -> None:
    """``comparison_level='segment'`` con ``segment_col`` (y carteras homónimas) construye."""
    cfg = ProvisioningConfig(comparison_level="segment", segment_col="segmento")
    assert cfg.segment_col == "segmento"


@pytest.mark.parametrize("level", ["portfolio", "segment"])
def test_taxonomias_distintas_sin_crosswalk_levantan(level: str) -> None:
    """Carteras con taxonomías distintas sin crosswalk exigen crosswalk (fail_on_falta_dato)."""
    with pytest.raises(ProvisioningConfigError, match="portfolio_crosswalk"):
        ProvisioningConfig(
            comparison_level=level,
            segment_col="segmento",
            cmf_portfolio_col="cartera_cmf",
            ifrs9_portfolio_col="cartera_ifrs9",
        )


def test_taxonomias_distintas_con_crosswalk_construye() -> None:
    """Carteras con taxonomías distintas y crosswalk explícito construyen."""
    cfg = ProvisioningConfig(
        comparison_level="portfolio",
        cmf_portfolio_col="cartera_cmf",
        ifrs9_portfolio_col="cartera_ifrs9",
        portfolio_crosswalk={"comercial": "wholesale"},
    )
    assert cfg.portfolio_crosswalk == {"comercial": "wholesale"}


def test_taxonomias_distintas_sin_fail_on_falta_dato_difiere() -> None:
    """Con ``fail_on_falta_dato=False`` la brecha de taxonomía se difiere (no falla en config)."""
    cfg = ProvisioningConfig(
        comparison_level="portfolio",
        cmf_portfolio_col="cartera_cmf",
        ifrs9_portfolio_col="cartera_ifrs9",
        fail_on_falta_dato=False,
    )
    assert cfg.portfolio_crosswalk == {}


def test_portfolio_con_columnas_homonimas_construye() -> None:
    """``comparison_level='portfolio'`` con la misma columna en ambos motores no exige crosswalk."""
    cfg = ProvisioningConfig(comparison_level="portfolio")
    assert cfg.comparison_level == "portfolio"


# ─────────────────────────── fuentes configurables y regla (SDD-28) ───────────────────────────


def test_source_a_igual_a_source_b_levanta() -> None:
    """Comparar una fuente consigo misma no es una comparación."""
    with pytest.raises(ProvisioningConfigError, match="no pueden ser la misma fuente"):
        ProvisioningConfig(source_a="provisioning_cmf", source_b="provisioning_cmf")


def test_fuentes_estandar_vs_interno_construyen() -> None:
    """La comparación que exige la norma chilena (estándar vs. interno) es declarable."""
    cfg = ProvisioningConfig(source_a="provisioning_cmf", source_b="provisioning_internal")
    assert cfg.sources == ("provisioning_cmf", "provisioning_internal")
    assert cfg.rule == "max"
    assert cfg.consume_source_a is True
    assert cfg.consume_source_b is True


def test_rule_use_internal_sin_metodo_interno_levanta() -> None:
    """``rule='use_internal'`` sin ``provisioning_internal`` entre las fuentes es incoherente."""
    with pytest.raises(ProvisioningConfigError, match="rule='use_internal' exige"):
        ProvisioningConfig(
            source_a="provisioning_cmf", source_b="provisioning_ifrs9", rule="use_internal"
        )


def test_rule_use_internal_con_metodo_interno_construye() -> None:
    """``rule='use_internal'`` con el método interno entre las fuentes construye."""
    cfg = ProvisioningConfig(source_b="provisioning_internal", rule="use_internal")
    assert cfg.rule == "use_internal"


def test_portfolio_col_for_resuelve_por_fuente() -> None:
    """Cada fuente declara la columna de cartera de su propio ``detail``."""
    cfg = ProvisioningConfig(
        cmf_portfolio_col="cartera_cmf",
        ifrs9_portfolio_col="cartera_ifrs9",
        internal_portfolio_col="cartera_interna",
        portfolio_crosswalk={"comercial": "wholesale"},
    )
    assert cfg.portfolio_col_for("provisioning_cmf") == "cartera_cmf"
    assert cfg.portfolio_col_for("provisioning_ifrs9") == "cartera_ifrs9"
    assert cfg.portfolio_col_for("provisioning_internal") == "cartera_interna"


# ─────────────────────────── fuentes consumidas ───────────────────────────


def test_ambas_fuentes_desactivadas_levanta() -> None:
    """``consume_a=False`` y ``consume_b=False`` no dejan nada que orquestar."""
    with pytest.raises(ProvisioningConfigError, match="nada que orquestar"):
        ProvisioningConfig(consume_a=False, consume_b=False, require_both=False)


@pytest.mark.parametrize(("consume_a", "consume_b"), [(True, False), (False, True)])
def test_require_both_con_una_sola_fuente_levanta(consume_a: bool, consume_b: bool) -> None:
    """``require_both=True`` con una sola fuente configurada es una contradicción declarativa."""
    with pytest.raises(ProvisioningConfigError, match="require_both"):
        ProvisioningConfig(consume_a=consume_a, consume_b=consume_b)


@pytest.mark.parametrize(("consume_a", "consume_b"), [(True, False), (False, True)])
def test_require_both_false_con_una_sola_fuente_construye(consume_a: bool, consume_b: bool) -> None:
    """``require_both=False`` con una sola fuente degrada a passthrough sin error."""
    cfg = ProvisioningConfig(consume_a=consume_a, consume_b=consume_b, require_both=False)
    assert cfg.require_both is False


# ─────────────────────── retrocompatibilidad: consume_* deprecados ───────────────────────


@pytest.mark.parametrize(
    ("legacy", "esperado_a", "esperado_b"),
    [
        ({"consume_cmf": False}, False, True),
        ({"consume_ifrs9": False}, True, False),
    ],
)
def test_consume_legacy_se_respeta_y_avisa(
    legacy: dict[str, bool], esperado_a: bool, esperado_b: bool
) -> None:
    """``consume_cmf``/``consume_ifrs9`` siguen funcionando, pero emiten ``DeprecationWarning``."""
    with pytest.warns(DeprecationWarning, match="DEPRECADO"):
        cfg = ProvisioningConfig(require_both=False, **legacy)
    assert cfg.consume_source_a is esperado_a
    assert cfg.consume_source_b is esperado_b


def test_consume_legacy_manda_sobre_el_generico() -> None:
    """Informado el flag deprecado de un dominio, manda sobre el ``consume_*`` de su ranura."""
    with pytest.warns(DeprecationWarning):
        cfg = ProvisioningConfig(consume_a=False, consume_cmf=True)
    assert cfg.consume_source_a is True  # consume_cmf (deprecado) gana sobre consume_a


def test_consume_legacy_ambos_false_levanta() -> None:
    """Los deprecados también validan el "nada que orquestar" (retrocompatibilidad exacta)."""
    with (
        pytest.warns(DeprecationWarning),
        pytest.raises(ProvisioningConfigError, match="nada que orquestar"),
    ):
        ProvisioningConfig(consume_cmf=False, consume_ifrs9=False, require_both=False)


def test_consume_legacy_de_dominio_que_no_es_fuente_levanta() -> None:
    """``consume_ifrs9`` con IFRS 9 fuera de las fuentes es un error de config, no un no-op."""
    with pytest.raises(ProvisioningConfigError, match="consume_ifrs9 solo aplica"):
        ProvisioningConfig(source_b="provisioning_internal", consume_ifrs9=False)


def test_consume_legacy_sobrevive_al_round_trip() -> None:
    """El deprecado ``None`` (no informado) no se confunde con ``True`` al re-validar (round-trip).

    Es el bug que un default ``bool=True`` habría introducido: tras ``model_dump`` el flag deprecado
    parecería "informado" y pisaría el ``consume_*`` genérico del usuario.
    """
    cfg = ProvisioningConfig(consume_a=False, require_both=False)
    recargado = ProvisioningConfig.model_validate(cfg.model_dump(mode="json"))
    assert recargado == cfg
    assert recargado.consume_source_a is False


# ─────────────────────────── restricciones Pydantic ───────────────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "internal"),
        ("comparison_level", "debtor"),
        ("coverage_policy", "assume_max"),
        ("numeric_reconciliation", "float_round"),
        ("rounding", "bankers"),
        ("tie_tolerance", -1e-9),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(field: str, value: object) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        ProvisioningConfig(**{field: value})


def test_tie_tolerance_cero_valido() -> None:
    """``tie_tolerance=0`` respeta ``ge=0.0`` (empate exacto)."""
    assert ProvisioningConfig(tie_tolerance=0.0).tie_tolerance == 0.0


# ─────────────────────────── config_hash ───────────────────────────


def test_config_hash_default_con_provisioning_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``provisioning=None``."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_se_movio_por_seccion_provisioning() -> None:
    """Añadir ``provisioning`` movió el golden respecto al valor previo (no es regresión)."""
    assert GOLDEN_DEFAULT_CONFIG_HASH != GOLDEN_PREVIO_SIN_PROVISIONING
    assert config_hash(NikodymConfig()) != GOLDEN_PREVIO_SIN_PROVISIONING


@pytest.mark.parametrize(
    "provisioning",
    [
        ProvisioningConfig(comparison_level="operation"),
        ProvisioningConfig(coverage_policy="treat_missing_as_zero"),
        ProvisioningConfig(numeric_reconciliation="float_isclose"),
        ProvisioningConfig(rounding="currency_2dp"),
        ProvisioningConfig(tie_tolerance=1e-6),
        ProvisioningConfig(portfolio_crosswalk={"comercial": "wholesale"}),
        ProvisioningConfig(source_b="provisioning_internal"),
        ProvisioningConfig(source_b="provisioning_internal", rule="use_internal"),
    ],
)
def test_config_hash_cambia_al_variar_provisioning(provisioning: ProvisioningConfig) -> None:
    """``provisioning`` no es INFRA: fuentes/regla/nivel/cobertura/reconciliación mueven el hash."""
    base = config_hash(NikodymConfig(provisioning=ProvisioningConfig()))
    variado = config_hash(NikodymConfig(provisioning=provisioning))
    assert "provisioning" not in INFRA_SECTIONS
    assert variado != base


# ─────────────────────────── metadata UI + API pública ───────────────────────────


def test_campos_provisioning_tienen_metadatos_ui() -> None:
    """Todos los campos de config de orquestación declaran metadata de UI para SDD-23."""
    for nombre, campo in ProvisioningConfig.model_fields.items():
        extra = campo.json_schema_extra
        assert campo.title is not None, f"ProvisioningConfig.{nombre} sin title"
        assert campo.description is not None, f"ProvisioningConfig.{nombre} sin description"
        assert isinstance(extra, dict), f"ProvisioningConfig.{nombre} sin ui_*"
        assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_provisioning_public_api_minimo() -> None:
    """El paquete de orquestación expone config y excepciones de B17.1."""
    assert provisioning_pkg.ProvisioningConfig is ProvisioningConfig
    assert provisioning_pkg.ProvisioningError is ProvisioningError
    assert "ProvisioningConfig" in provisioning_pkg.__all__


def test_provisioning_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``provisioning`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        ProvisioningError,
        ProvisioningConfigError,
        ProvisioningInputError,
        ProvisioningAlignmentError,
        ProvisioningCoverageError,
    ):
        assert issubclass(error_cls, NikodymError)
    assert issubclass(ProvisioningAlignmentError, ProvisioningInputError)


# ─────────────────────────── import liviano ───────────────────────────


def test_import_provisioning_config_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.provisioning.config`` registra hook sin arrastrar stack pesado."""
    code = (
        "import nikodym.provisioning.config, nikodym.core, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.provisioning.config import ProvisioningConfig;"
        "bloqueados=[m for m in "
        "('nikodym.data','pandera','pyarrow','pandas','nikodym.tracking','mlflow') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(provisioning={'comparison_level': 'operation'});"
        "assert isinstance(cfg.provisioning, ProvisioningConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_provisioning_como_blob_opaco_sin_importar_la_capa() -> None:
    """El core acepta ``provisioning`` JSON/dict sin importar la capa de orquestación."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(provisioning={'comparison_level': 'total'});"
        "assert cfg.provisioning == {'comparison_level': 'total'};"
        "assert 'nikodym.provisioning' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
