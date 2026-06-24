"""Núcleo (``core``) de Nikodym: fundación *stateful* y agnóstica al dominio (SDD-01).

Aloja el estado del experimento (``Study``), el config declarativo, el ``Registry``, la
siembra determinista (:class:`~nikodym.core.seeding.SeedManager`), el lineage y la jerarquía de
excepciones. ``core`` no depende de scikit-learn ni de ningún backend pesado (D-CORE-1). La
superficie pública se re-exporta aquí a medida que se construyen los submódulos de la Fundación.
"""

from nikodym.core.config import (
    INFRA_SECTIONS,
    SCHEMA_VERSION,
    NikodymBaseConfig,
    NikodymConfig,
    ReproConfig,
    RunConfig,
    config_hash,
    dump_config,
    load_config,
    loads_config,
    migrate,
    migration,
)
from nikodym.core.exceptions import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    ConfigError,
    ConfigVersionError,
    DataValidationError,
    DuplicateRegistrationError,
    MigrationNotFoundError,
    MissingDependencyError,
    NikodymError,
    NotFittedError,
    RegistryError,
    RegulatoryError,
    ReproducibilityError,
    UnknownComponentError,
    UntrustedStudyError,
)
from nikodym.core.seeding import SeedManager

__all__ = [
    "INFRA_SECTIONS",
    "SCHEMA_VERSION",
    "ArtifactExistsError",
    "ArtifactNotFoundError",
    "ConfigError",
    "ConfigVersionError",
    "DataValidationError",
    "DuplicateRegistrationError",
    "MigrationNotFoundError",
    "MissingDependencyError",
    "NikodymBaseConfig",
    "NikodymConfig",
    "NikodymError",
    "NotFittedError",
    "RegistryError",
    "RegulatoryError",
    "ReproConfig",
    "ReproducibilityError",
    "RunConfig",
    "SeedManager",
    "UnknownComponentError",
    "UntrustedStudyError",
    "config_hash",
    "dump_config",
    "load_config",
    "loads_config",
    "migrate",
    "migration",
]
