"""Carga, migración y validación de configs desde YAML, y volcado legible inverso (SDD-05 §5.5).

:func:`load_config` lee un YAML, lo migra si su ``schema_version`` es anterior y lo valida a un
:class:`NikodymConfig` *frozen*; los errores de validación de Pydantic se envuelven en
:class:`ConfigError` con mensaje en español. :func:`dump_config` produce el YAML inverso en orden
de declaración (legible para revisores). El round-trip es invariante:
``load_config(dump_config(c)) == c``. Se usa **exclusivamente** ``yaml.safe_load``/``safe_dump``
(nunca ``yaml.load``: vector de ejecución arbitraria). **Estable (SemVer 1.x).**
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from nikodym.core.config.migration import migrate
from nikodym.core.config.schema import NikodymConfig
from nikodym.core.exceptions import ConfigError

if TYPE_CHECKING:
    import os

__all__ = ["dump_config", "load_config", "loads_config"]


def load_config(path: str | os.PathLike[str]) -> NikodymConfig:
    """Carga un :class:`NikodymConfig` desde un fichero YAML.

    Parameters
    ----------
    path : str or os.PathLike
        Ruta del fichero YAML del config.

    Returns
    -------
    NikodymConfig
        Config validado e inmutable.

    Raises
    ------
    ConfigError
        Si el YAML no cumple el schema (campo desconocido, tipo/rango erróneo).
    """
    return loads_config(Path(path).read_text(encoding="utf-8"))


def loads_config(text: str) -> NikodymConfig:
    """Carga un :class:`NikodymConfig` desde un string YAML.

    Parameters
    ----------
    text : str
        Contenido YAML del config (un mapeo en la raíz).

    Returns
    -------
    NikodymConfig
        Config validado e inmutable.

    Raises
    ------
    ConfigError
        Si el YAML no es un mapeo o no cumple el schema.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML del config malformado: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"el YAML del config debe ser un mapeo, no {type(raw).__name__}.")
    raw = migrate(raw)
    try:
        return NikodymConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"config inválido: {exc}") from exc


def dump_config(cfg: NikodymConfig, *, exclude_unset: bool = False) -> str:
    """Serializa un :class:`NikodymConfig` a YAML legible (orden de declaración).

    Parameters
    ----------
    cfg : NikodymConfig
        Config a volcar.
    exclude_unset : bool, default False
        Si es True, omite los campos que no fueron provistos explícitamente (toman su default al
        recargar). Hace el volcado **determinista frente al estado de imports** para las secciones
        de capa diferida (``report``/``audit``/``governance``/``validation``): un ``dict`` de
        entrada sin, p. ej., ``report.document`` produce el MISMO YAML se haya importado o no la
        capa que coacciona a ``ReportConfig`` (que materializaría ``document`` por default_factory).
        El default False conserva el volcado completo (lineage auditable de una corrida).

    Returns
    -------
    str
        YAML con las claves en orden de declaración y las tildes sin escapar.
    """
    payload = cfg.model_dump(mode="json", by_alias=True, exclude_unset=exclude_unset)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
