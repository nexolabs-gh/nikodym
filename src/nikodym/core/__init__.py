"""Núcleo (``core``) de Nikodym: fundación *stateful* y agnóstica al dominio (SDD-01).

Aloja el estado del experimento (``Study``), el config declarativo, el ``Registry``, la
siembra determinista (:class:`~nikodym.core.seeding.SeedManager`), el lineage y la jerarquía de
excepciones. ``core`` no depende de scikit-learn ni de ningún backend pesado (D-CORE-1). La
superficie pública se re-exporta aquí a medida que se construyen los submódulos de la Fundación.
"""

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
    "ArtifactExistsError",
    "ArtifactNotFoundError",
    "ConfigError",
    "ConfigVersionError",
    "DataValidationError",
    "DuplicateRegistrationError",
    "MigrationNotFoundError",
    "MissingDependencyError",
    "NikodymError",
    "NotFittedError",
    "RegistryError",
    "RegulatoryError",
    "ReproducibilityError",
    "SeedManager",
    "UnknownComponentError",
    "UntrustedStudyError",
]
