"""Núcleo (``core``) de Nikodym: fundación *stateful* y agnóstica al dominio (SDD-01).

Aloja el estado del experimento (``Study``), el config declarativo, el ``Registry``, la
siembra determinista (:class:`~nikodym.core.seeding.SeedManager`), el lineage y la jerarquía de
excepciones. ``core`` no depende de scikit-learn ni de ningún backend pesado (D-CORE-1). La
superficie pública se re-exporta aquí a medida que se construyen los submódulos de la Fundación.
"""

from nikodym.core.artifacts import ArtifactStore
from nikodym.core.audit import (
    AuditEvent,
    AuditKind,
    AuditSink,
    FanOutSink,
    InMemoryAuditSink,
    NullAuditSink,
)
from nikodym.core.base import (
    BaseECLModel,
    BaseForecaster,
    BaseNikodymEstimator,
    BaseProvisionModel,
    BaseSurvivalEstimator,
    NikodymClassifier,
    NikodymTransformer,
)
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
from nikodym.core.lineage import LineageBundle, RunContext
from nikodym.core.mixins import AuditableMixin, SerializationMixin
from nikodym.core.registry import REGISTRY, Registry, register
from nikodym.core.results import ECLResultLike, ProvisionResultLike
from nikodym.core.seeding import SeedManager
from nikodym.core.steps import ArtifactKey, Step, StepAdapter
from nikodym.core.study import Study

__all__ = [
    "INFRA_SECTIONS",
    "REGISTRY",
    "SCHEMA_VERSION",
    "ArtifactExistsError",
    "ArtifactKey",
    "ArtifactNotFoundError",
    "ArtifactStore",
    "AuditEvent",
    "AuditKind",
    "AuditSink",
    "AuditableMixin",
    "BaseECLModel",
    "BaseForecaster",
    "BaseNikodymEstimator",
    "BaseProvisionModel",
    "BaseSurvivalEstimator",
    "ConfigError",
    "ConfigVersionError",
    "DataValidationError",
    "DuplicateRegistrationError",
    "ECLResultLike",
    "FanOutSink",
    "InMemoryAuditSink",
    "LineageBundle",
    "MigrationNotFoundError",
    "MissingDependencyError",
    "NikodymBaseConfig",
    "NikodymClassifier",
    "NikodymConfig",
    "NikodymError",
    "NikodymTransformer",
    "NotFittedError",
    "NullAuditSink",
    "ProvisionResultLike",
    "Registry",
    "RegistryError",
    "RegulatoryError",
    "ReproConfig",
    "ReproducibilityError",
    "RunConfig",
    "RunContext",
    "SeedManager",
    "SerializationMixin",
    "Step",
    "StepAdapter",
    "Study",
    "UnknownComponentError",
    "UntrustedStudyError",
    "config_hash",
    "dump_config",
    "load_config",
    "loads_config",
    "migrate",
    "migration",
    "register",
]
