"""Subpaquete de configuración declarativa de Nikodym (SDD-01 §4-5, SDD-05 §5).

Re-exporta la superficie pública del config: el schema (:class:`NikodymConfig` y sus secciones),
la identidad por :func:`config_hash`, la carga/volcado YAML (:func:`load_config` /
:func:`dump_config`) y el mecanismo de migración (:func:`migrate`, :func:`migration`).
"""

from nikodym.core.config.hashing import INFRA_SECTIONS, config_hash
from nikodym.core.config.loader import dump_config, load_config, loads_config
from nikodym.core.config.migration import SCHEMA_VERSION, migrate, migration
from nikodym.core.config.schema import (
    NikodymBaseConfig,
    NikodymConfig,
    ReproConfig,
    RunConfig,
)

__all__ = [
    "INFRA_SECTIONS",
    "SCHEMA_VERSION",
    "NikodymBaseConfig",
    "NikodymConfig",
    "ReproConfig",
    "RunConfig",
    "config_hash",
    "dump_config",
    "load_config",
    "loads_config",
    "migrate",
    "migration",
]
