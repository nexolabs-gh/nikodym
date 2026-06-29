"""Tests de ``DataConfig`` (SDD-02 §5) y su integración con ``NikodymConfig`` (endurecimiento B2a).

Cubre: árbol Pydantic (defaults, ``extra='forbid'``, ``frozen``), alias ``schema`` con
``populate_by_name``, unión discriminada anidada de la estrategia de partición, los
``model_validator`` (fracciones que suman 1, regla no vacía), y la coerción/validación de la
sección ``data`` de ``NikodymConfig`` vía el hook ``_DATA_CONFIG_CLS`` (golden ``config_hash``
invariante con ``data=None``; identidad sensible a ``data`` poblado; round-trip YAML por alias).
"""

import pytest
from pydantic import ValidationError

import nikodym.data  # noqa: F401  — importa la capa: puebla el hook _DATA_CONFIG_CLS
from nikodym.core.config import (
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.data.config import (
    CohortSplitConfig,
    DataConfig,
    PartitionConfig,
    Predicate,
    RandomSplitConfig,
    Rule,
    SchemaConfig,
    TargetConfig,
    TemporalSplitConfig,
)

# Golden de NikodymConfig() por defecto (idéntico a tests/repro/test_config_hash_golden.py): B11.5
# añadió la clave computacional `stability=None`; cargar `data` no debe moverlo adicionalmente.
GOLDEN_DEFAULT_CONFIG_HASH = "0e1016e38154a09a93e3e4b1a551b71afa06b257b58f6081ce2f4e24fb4e4c69"


@pytest.fixture(autouse=True)
def _capa_data_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado (vista con capa ``data``) sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_DATA_CONFIG_CLS", DataConfig)


def _bad_rule() -> Rule:
    """Regla de 'malo' mínima válida (mora >= 90)."""
    return Rule(all_of=(Predicate(col="max_dpd_12m", op=">=", value=90),))


def _data_config_minimo() -> DataConfig:
    """``DataConfig`` mínimo válido: target con bad_rule + partición random 70/15/15."""
    return DataConfig(
        target=TargetConfig(bad_rule=_bad_rule()),
        partition=PartitionConfig(strategy=RandomSplitConfig()),
    )


# ── DataConfig: estructura ────────────────────────────────────────────────────
def test_dataconfig_minimo_valido() -> None:
    """Construye el sub-config mínimo y trae los defaults defendibles del SDD-02 §5."""
    cfg = _data_config_minimo()
    assert cfg.type == "standard"
    assert cfg.load.backend == "pandas"
    assert cfg.schema_.strict is False
    assert cfg.missing.max_missing_rate == 0.99
    assert isinstance(cfg.partition.strategy, RandomSplitConfig)
    assert cfg.partition.min_bads_per_partition == 30


def test_dataconfig_extra_forbid() -> None:
    """``extra='forbid'`` de la base se hereda al añadir ``populate_by_name`` (merge de config)."""
    with pytest.raises(ValidationError):
        DataConfig(
            target=TargetConfig(bad_rule=_bad_rule()),
            partition=PartitionConfig(strategy=RandomSplitConfig()),
            campo_inexistente=1,  # type: ignore[call-arg]
        )


def test_dataconfig_frozen() -> None:
    """El sub-config es inmutable (``frozen`` heredado de la base)."""
    cfg = _data_config_minimo()
    with pytest.raises(ValidationError):
        cfg.type = "otro"  # type: ignore[misc]


def test_schema_alias_por_nombre_y_por_alias() -> None:
    """``schema_`` se acepta por nombre Python y por alias ``schema``; serializa por alias."""
    por_nombre = DataConfig(
        target=TargetConfig(bad_rule=_bad_rule()),
        partition=PartitionConfig(strategy=RandomSplitConfig()),
        schema_=SchemaConfig(strict=True),
    )
    por_alias = DataConfig.model_validate(
        {
            "target": {"bad_rule": {"all_of": [{"col": "max_dpd_12m", "op": ">=", "value": 90}]}},
            "partition": {"strategy": {"type": "random"}},
            "schema": {"strict": True},
        }
    )
    assert por_nombre.schema_.strict is True
    assert por_alias.schema_.strict is True
    volcado = por_nombre.model_dump(mode="json", by_alias=True)
    assert "schema" in volcado and "schema_" not in volcado


# ── unión discriminada anidada de la estrategia ───────────────────────────────
def test_estrategia_temporal() -> None:
    """``type='temporal'`` resuelve a :class:`TemporalSplitConfig`."""
    cfg = PartitionConfig(
        strategy={"type": "temporal", "date_col": "fecha", "oot_from": "2024-01-01"}  # type: ignore[arg-type]
    )
    assert isinstance(cfg.strategy, TemporalSplitConfig)
    assert cfg.strategy.holdout_fraction == 0.2


def test_estrategia_cohort() -> None:
    """``type='cohort'`` resuelve a :class:`CohortSplitConfig`."""
    cfg = PartitionConfig(
        strategy={"type": "cohort", "cohort_col": "vintage", "oot_cohorts": ("2024Q1",)}  # type: ignore[arg-type]
    )
    assert isinstance(cfg.strategy, CohortSplitConfig)


def test_estrategia_tipo_desconocido_levanta() -> None:
    """Un discriminador fuera de la allowlist levanta ``ValidationError``."""
    with pytest.raises(ValidationError):
        PartitionConfig(strategy={"type": " inexistente"})  # type: ignore[arg-type]


# ── model_validators ──────────────────────────────────────────────────────────
def test_random_fracciones_suman_uno_ok() -> None:
    """Fracciones que suman 1.0 construyen sin error."""
    estrategia = RandomSplitConfig(dev_fraction=0.6, holdout_fraction=0.2, oot_fraction=0.2)
    assert estrategia.dev_fraction == 0.6


def test_random_fracciones_no_suman_uno_levanta() -> None:
    """Fracciones que no suman 1.0 -> ``ValidationError`` con la suma observada."""
    with pytest.raises(ValidationError) as info:
        RandomSplitConfig(dev_fraction=0.6, holdout_fraction=0.3, oot_fraction=0.3)
    assert "debe sumar 1.0" in str(info.value)


def test_rule_no_vacia_ok() -> None:
    """Una regla con al menos un predicado es válida."""
    assert _bad_rule().all_of[0].op == ">="


def test_rule_vacia_levanta() -> None:
    """Una ``Rule`` sin ``all_of`` ni ``any_of`` -> ``ValidationError``."""
    with pytest.raises(ValidationError) as info:
        Rule()
    assert "al menos un predicado" in str(info.value)


def test_predicate_value_strict_no_coacciona_bool() -> None:
    """``value`` es strict: un bool no se coacciona a int (no altera la máscara)."""
    pred = Predicate(col="flag", op="==", value=True)
    assert pred.value is True and isinstance(pred.value, bool)


# ── integración con NikodymConfig (hook poblado) ──────────────────────────────
def test_nikodymconfig_data_instancia() -> None:
    """Pasar una instancia ``DataConfig`` a ``NikodymConfig`` la conserva (rama isinstance)."""
    data = _data_config_minimo()
    cfg = NikodymConfig(data=data)
    assert isinstance(cfg.data, DataConfig)
    assert cfg.data is data


def test_nikodymconfig_data_dict_coacciona() -> None:
    """Un dict en ``data`` se coacciona a ``DataConfig`` (rama model_validate)."""
    cfg = NikodymConfig(
        data={
            "target": {"bad_rule": {"all_of": [{"col": "max_dpd_12m", "op": ">=", "value": 90}]}},
            "partition": {"strategy": {"type": "random"}},
        }
    )
    assert isinstance(cfg.data, DataConfig)
    assert isinstance(cfg.data.partition.strategy, RandomSplitConfig)


def test_nikodymconfig_data_extra_forbid() -> None:
    """Un campo extra dentro de la sección ``data`` se rechaza (extra=forbid de DataConfig)."""
    with pytest.raises(ValidationError):
        NikodymConfig(
            data={
                "target": {"bad_rule": {"all_of": [{"col": "x", "op": ">=", "value": 1}]}},
                "partition": {"strategy": {"type": "random"}},
                "zzz": 1,
            }
        )


def test_nikodymconfig_data_none_explicito() -> None:
    """``data=None`` explícito pasa por el validador y queda None (rama None)."""
    cfg = NikodymConfig(data=None)
    assert cfg.data is None


# ── identidad (config_hash) ───────────────────────────────────────────────────
def test_config_hash_data_none_invariante() -> None:
    """Importar la capa ``data`` y endurecer el campo NO mueve el golden (data=None -> null)."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_cambia_con_data_poblado() -> None:
    """``data`` es sección computacional (no INFRA): poblarla cambia la identidad de la corrida."""
    con_data = config_hash(NikodymConfig(data=_data_config_minimo()))
    assert con_data != GOLDEN_DEFAULT_CONFIG_HASH


# ── round-trip YAML ───────────────────────────────────────────────────────────
def test_round_trip_yaml_con_data() -> None:
    """``loads_config(dump_config(cfg))`` con sección ``data`` preserva igualdad e identidad."""
    cfg = NikodymConfig(name="scorecard", data=_data_config_minimo())
    recargado = loads_config(dump_config(cfg))
    assert recargado == cfg
    assert config_hash(recargado) == config_hash(cfg)
    assert isinstance(recargado.data, DataConfig)
