"""Tests del version-gate y la migración (SDD-05 §5.4): registro vacío y gate sin silencios."""

from collections.abc import Iterator
from typing import Any

import pytest

from nikodym.core.config import NikodymConfig, migrate, migration
from nikodym.core.config.migration import _MIGRATORS, SCHEMA_VERSION, _parse
from nikodym.core.exceptions import (
    ConfigError,
    ConfigVersionError,
    MigrationNotFoundError,
    NikodymError,
)


@pytest.fixture
def registro_limpio() -> Iterator[None]:
    """Aísla el registro global de migradores: lo vacía y lo restaura tras el test."""
    original = dict(_MIGRATORS)
    _MIGRATORS.clear()
    try:
        yield
    finally:
        _MIGRATORS.clear()
        _MIGRATORS.update(original)


def test_registro_vacio_en_v1() -> None:
    """El registro de migradores está vacío en 1.0.0 (DoD F0 d)."""
    assert _MIGRATORS == {}


def test_schema_version_coincide_con_default() -> None:
    """SCHEMA_VERSION coincide con el default del schema y con '1.0.0'."""
    assert SCHEMA_VERSION == "1.0.0" == NikodymConfig().schema_version


def test_migrate_version_igual_pasa() -> None:
    """Un config en la versión actual pasa tal cual."""
    raw = {"schema_version": "1.0.0", "name": "x"}
    assert migrate(raw) == raw


def test_migrate_sin_version_asume_actual() -> None:
    """Un dict sin schema_version asume la versión base y no levanta."""
    assert migrate({}) == {}


def test_migrate_version_futura_levanta() -> None:
    """Un config 'del futuro' (versión mayor) levanta ConfigVersionError."""
    with pytest.raises(ConfigVersionError):
        migrate({"schema_version": "2.0.0"})


def test_migrate_menor_sin_migrador_levanta() -> None:
    """Una versión anterior sin migrador registrado levanta MigrationNotFoundError."""
    with pytest.raises(MigrationNotFoundError):
        migrate({"schema_version": "0.9.0"})


def test_decorador_registra_y_encadena(registro_limpio: None) -> None:
    """@migration registra un migrador y migrate lo aplica para alcanzar la versión actual."""

    @migration("0.9.0", "1.0.0")
    def _subir(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "schema_version": "1.0.0", "migrado": True}

    resultado = migrate({"schema_version": "0.9.0"})
    assert resultado["migrado"] is True
    assert resultado["schema_version"] == "1.0.0"


def test_comparacion_semver_no_lexicografica() -> None:
    """La comparación es numérica: '1.10.0' es mayor que '1.9.0' (no lexicográfico)."""
    assert _parse("1.10.0") > _parse("1.9.0")


@pytest.mark.parametrize("malformada", ["abc", "1.0.0a1", "v1.0.0", "", "1.0", "1.0.0.0", "1.0.x"])
def test_migrate_version_malformada_levanta_nikodym_error(malformada: str) -> None:
    """Un schema_version no-SemVer levanta ConfigError, no un ValueError crudo."""
    with pytest.raises(NikodymError):
        migrate({"schema_version": malformada})
    with pytest.raises(ConfigError):
        migrate({"schema_version": malformada})


@pytest.mark.parametrize("no_str", [1.0, 100, True, None, ["1", "0", "0"]])
def test_migrate_schema_version_no_str_levanta(no_str: object) -> None:
    """Un schema_version que no es cadena levanta ConfigError (no se coacciona en silencio)."""
    with pytest.raises(ConfigError):
        migrate({"schema_version": no_str})


@pytest.mark.parametrize(("desde", "hasta"), [("1.0.0", "1.0.0"), ("1.1.0", "1.0.0")])
def test_migration_rechaza_no_avance(registro_limpio: None, desde: str, hasta: str) -> None:
    """@migration rechaza un migrador que no avanza la versión (evita ciclos y loops infinitos)."""
    with pytest.raises(ConfigError):
        migration(desde, hasta)


def test_migration_rechaza_origen_duplicado(registro_limpio: None) -> None:
    """@migration rechaza un segundo migrador con el mismo origen (cadena lineal)."""

    @migration("0.9.0", "1.0.0")
    def _primero(raw: dict[str, Any]) -> dict[str, Any]:
        return raw

    with pytest.raises(ConfigError):
        migration("0.9.0", "0.9.5")


def test_migrate_cadena_multisalto(registro_limpio: None) -> None:
    """migrate encadena varios migradores en orden hasta alcanzar la versión actual."""

    @migration("0.8.0", "0.9.0")
    def _a(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "schema_version": "0.9.0", "paso_a": True}

    @migration("0.9.0", "1.0.0")
    def _b(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "schema_version": "1.0.0", "paso_b": True}

    resultado = migrate({"schema_version": "0.8.0"})
    assert resultado["paso_a"] is True
    assert resultado["paso_b"] is True
    assert resultado["schema_version"] == "1.0.0"
