"""Version-gate y registro de migradores del config (SDD-05 §5.4).

El config declara su ``schema_version`` (SemVer). :func:`migrate` decide, al cargar, entre tres
caminos sin ambigüedad: igual a la versión del paquete → pasa tal cual; menor con migradores
encadenables → migra; menor sin migrador o mayor (config "del futuro") → falla ruidosamente.
**Nunca migra en silencio.** En la versión ``1.0.0`` el registro está **vacío** a propósito: es
el punto de extensión para futuros cambios de schema, con el mecanismo ya implementado completo.
La cadena es **lineal** por SemVer: cada migrador avanza estrictamente la versión y hay a lo sumo
uno por versión de origen (se valida al registrar, en *import time*). **Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from nikodym.core.exceptions import ConfigError, ConfigVersionError, MigrationNotFoundError

__all__ = ["SCHEMA_VERSION", "migrate", "migration"]

#: Versión del schema del config que entiende este paquete (debe coincidir con el default de
#: ``NikodymConfig.schema_version``).
SCHEMA_VERSION = "1.0.0"

#: Firma de un migrador: una transformación pura ``dict -> dict`` del config crudo.
Migrator = Callable[[dict[str, Any]], dict[str, Any]]

# Registro de migradores indexado por (origen, destino). VACÍO en 1.0.0 (punto de extensión).
_MIGRATORS: dict[tuple[str, str], Migrator] = {}

# SemVer de tres componentes numéricos (MAYOR.MENOR.PARCHE), la forma que tabula SDD-05 §5.4.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _parse(version: str) -> tuple[int, int, int]:
    """Parsea ``"MAYOR.MENOR.PARCHE"`` a una tupla de enteros comparable numéricamente.

    Permite comparar por valor, no lexicográficamente (``"1.10.0" > "1.9.0"``).

    Raises
    ------
    ConfigError
        Si ``version`` no es un SemVer de tres componentes numéricos (entrada malformada del
        usuario: nunca debe escapar un ``ValueError`` crudo fuera de la jerarquía NikodymError).
    """
    if not _SEMVER_RE.match(version):
        raise ConfigError(
            f"schema_version {version!r} no es SemVer válido: se espera "
            "'MAYOR.MENOR.PARCHE' con tres componentes numéricos."
        )
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def migration(from_version: str, to_version: str) -> Callable[[Migrator], Migrator]:
    """Registra un migrador puro ``dict -> dict`` para el salto ``from_version -> to_version``.

    Valida en *import time* la linealidad de la cadena: el destino avanza estrictamente sobre el
    origen y no existe ya otro migrador con el mismo origen (evita ciclos, pasos que no progresan
    y bifurcaciones que colgarían o desviarían :func:`migrate`).

    Parameters
    ----------
    from_version, to_version : str
        Versiones SemVer de origen y destino del migrador.

    Returns
    -------
    Callable[[Migrator], Migrator]
        Decorador que registra la función en :data:`_MIGRATORS` y la devuelve intacta.

    Raises
    ------
    ConfigError
        Si el destino no avanza sobre el origen, o si ya hay un migrador con ese origen.
    """
    if _parse(to_version) <= _parse(from_version):
        raise ConfigError(
            f"un migrador debe avanzar la versión: {from_version!r} -> {to_version!r} no progresa."
        )
    if any(src == from_version for src, _ in _MIGRATORS):
        raise ConfigError(
            f"ya existe un migrador con origen {from_version!r}: la cadena debe ser lineal "
            "(un solo migrador por versión de origen)."
        )

    def decorator(func: Migrator) -> Migrator:
        """Registra ``func`` y la devuelve sin envolver."""
        _MIGRATORS[(from_version, to_version)] = func
        return func

    return decorator


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Aplica el version-gate y la cadena de migradores a un config crudo.

    Parameters
    ----------
    raw : dict[str, Any]
        Config recién deserializado del YAML, antes de validar. Un dict sin ``schema_version``
        asume la versión base del paquete.

    Returns
    -------
    dict[str, Any]
        El config listo para ``NikodymConfig.model_validate`` (migrado si hacía falta).

    Raises
    ------
    ConfigError
        Si ``schema_version`` no es una cadena SemVer válida.
    ConfigVersionError
        Si ``schema_version`` es mayor que la del paquete (config "del futuro").
    MigrationNotFoundError
        Si falta un migrador para completar algún salto de versión necesario.
    """
    raw_version = raw.get("schema_version", SCHEMA_VERSION)
    if not isinstance(raw_version, str):
        raise ConfigError(
            f"schema_version debe ser una cadena SemVer, no {type(raw_version).__name__}."
        )
    target = _parse(SCHEMA_VERSION)
    if _parse(raw_version) == target:
        return raw
    if _parse(raw_version) > target:
        raise ConfigVersionError(
            f"schema_version {raw_version!r} es mayor que la del paquete ({SCHEMA_VERSION!r}): "
            "actualiza Nikodym para cargar este config."
        )
    migrated = raw
    cursor = raw_version
    while _parse(cursor) < target:
        step = next(((dst, fn) for (src, dst), fn in _MIGRATORS.items() if src == cursor), None)
        if step is None:
            raise MigrationNotFoundError(
                f"falta un migrador para saltar desde schema_version {cursor!r} "
                f"hacia {SCHEMA_VERSION!r}."
            )
        to_version, func = step
        migrated = func(migrated)
        cursor = to_version
    return migrated
