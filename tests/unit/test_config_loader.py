"""Tests del loader YAML (SDD-05 §5.5): round-trip, errores en ConfigError y safe_load."""

from pathlib import Path

import pytest

from nikodym.core.config import (
    NikodymConfig,
    ReproConfig,
    config_hash,
    dump_config,
    load_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import ConfigError, ConfigVersionError


@pytest.fixture(autouse=True)
def _vista_core_solo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vista *core-only*: sin capas de dominio cargadas, sus secciones son blobs opacos.

    Neutraliza hooks poblados *process-wide* al importar dominios en otros tests para probar el
    loader del núcleo en aislamiento; el round-trip con configs reales se cubre en sus módulos.
    """
    monkeypatch.setattr(_schema_mod, "_DATA_CONFIG_CLS", None)
    monkeypatch.setattr(_schema_mod, "_EDA_CONFIG_CLS", None)
    monkeypatch.setattr(_schema_mod, "_AUDIT_CONFIG_CLS", None)
    monkeypatch.setattr(_schema_mod, "_GOVERNANCE_CONFIG_CLS", None)
    monkeypatch.setattr(_schema_mod, "_TRACKING_CONFIG_CLS", None)


def test_round_trip_string() -> None:
    """load(dump(c)) == c por valor (DoD F0 c)."""
    cfg = NikodymConfig(name="estudio", repro=ReproConfig(seed=7))
    assert loads_config(dump_config(cfg)) == cfg


def test_round_trip_fichero(tmp_path: Path) -> None:
    """El round-trip también vale desde un fichero en disco."""
    cfg = NikodymConfig(repro=ReproConfig(seed=13))
    destino = tmp_path / "config.yaml"
    destino.write_text(dump_config(cfg), encoding="utf-8")
    assert load_config(destino) == cfg


def test_round_trip_preserva_config_hash() -> None:
    """El round-trip preserva la identidad por config_hash."""
    cfg = NikodymConfig(repro=ReproConfig(seed=99))
    assert config_hash(loads_config(dump_config(cfg))) == config_hash(cfg)


def test_dump_orden_de_declaracion() -> None:
    """dump_config respeta el orden de declaración (schema_version antes que repro)."""
    texto = dump_config(NikodymConfig())
    assert texto.index("schema_version") < texto.index("repro")


def test_load_yaml_vacio_da_defaults() -> None:
    """Un YAML vacío (None) se normaliza a {} y produce el config por defecto."""
    assert loads_config("") == NikodymConfig()


def test_load_campo_desconocido_envuelve_en_config_error() -> None:
    """Un campo extra levanta ConfigError (envuelve el ValidationError de Pydantic)."""
    with pytest.raises(ConfigError):
        loads_config("campo_raro: 1\n")


def test_load_tipo_erroneo_envuelve_en_config_error() -> None:
    """Un tipo inválido (seed no entero) levanta ConfigError."""
    with pytest.raises(ConfigError):
        loads_config("repro:\n  seed: no_es_entero\n")


def test_load_raiz_no_mapeo_levanta_config_error() -> None:
    """Un YAML cuya raíz no es un mapeo (p. ej. una lista) levanta ConfigError."""
    with pytest.raises(ConfigError):
        loads_config("- a\n- b\n")


def test_load_usa_safe_load() -> None:
    """El loader usa safe_load: un tag peligroso no instancia objetos, da ConfigError."""
    with pytest.raises(ConfigError):
        loads_config("repro: !!python/object/apply:os.system ['echo inseguro']\n")


def test_load_yaml_malformado_envuelve_en_config_error() -> None:
    """Un YAML sintácticamente roto se envuelve en ConfigError, no escapa como YAMLError crudo."""
    with pytest.raises(ConfigError):
        loads_config("clave: : : roto\n")


def test_load_version_futura_via_loader() -> None:
    """El version-gate propaga por el loader: un config 'del futuro' levanta ConfigVersionError."""
    with pytest.raises(ConfigVersionError):
        loads_config("schema_version: '2.0.0'\n")


def test_round_trip_data_poblada() -> None:
    """Un config con data poblada sobrevive el round-trip por valor y por config_hash."""
    cfg = NikodymConfig(data={"load": {"source": "x.parquet"}})
    recargado = loads_config(dump_config(cfg))
    assert recargado == cfg
    assert config_hash(recargado) == config_hash(cfg)


def test_dump_unicode_sin_escapar() -> None:
    """Las tildes se serializan legibles (allow_unicode), no escapadas."""
    texto = dump_config(NikodymConfig(name="estudio café"))
    assert "café" in texto
