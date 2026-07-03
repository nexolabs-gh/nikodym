"""Provisiones de Nikodym: motores CMF/IFRS 9 y su orquestación (piso prudencial).

Son **dos motores separados** (ESPEC §5.4): :mod:`nikodym.provisioning.cmf`
(``PE = PI·PDI·Exposición``, B-1) e :mod:`nikodym.provisioning.ifrs9` (ECL). La provisión reportada
es el **máximo** de ambos (piso prudencial CMF), que orquesta esta capa fina (SDD-17).

Al importarse, este paquete registra :class:`ProvisioningConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.provisioning`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.provisioning`` ni dependencias tabulares pesadas.
B17.2 añade los DTOs puros de resultados (``results``); orchestrator y step llegan en los bloques
siguientes de SDD-17 (B17.3+). Los DTOs no importan ``pandas`` en runtime, de modo que
``import nikodym.provisioning`` sigue siendo liviano; **aún no** se registra el step.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from nikodym.core.config import schema as _schema
from nikodym.provisioning.config import (
    ProvisioningComparisonLevel,
    ProvisioningConfig,
    ProvisioningCoveragePolicy,
    ProvisioningNumericReconciliation,
    ProvisioningRoundingPolicy,
)
from nikodym.provisioning.exceptions import (
    ProvisioningAlignmentError,
    ProvisioningConfigError,
    ProvisioningCoverageError,
    ProvisioningError,
    ProvisioningInputError,
)
from nikodym.provisioning.results import (
    ProvisionComparisonRecord,
    ProvisionComparisonSummary,
    ProvisionOrchestrationCard,
    ProvisionOrchestrationResult,
)

# Registra la clase real del sub-config `provisioning` en el hook de `core`.
_schema._PROVISIONING_CONFIG_CLS = ProvisioningConfig

__all__ = [
    "ProvisionComparisonRecord",
    "ProvisionComparisonSummary",
    "ProvisionOrchestrationCard",
    "ProvisionOrchestrationResult",
    "ProvisioningAlignmentError",
    "ProvisioningComparisonLevel",
    "ProvisioningConfig",
    "ProvisioningConfigError",
    "ProvisioningCoverageError",
    "ProvisioningCoveragePolicy",
    "ProvisioningError",
    "ProvisioningInputError",
    "ProvisioningNumericReconciliation",
    "ProvisioningRoundingPolicy",
]
