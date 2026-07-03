"""Provisiones de Nikodym: motores CMF/IFRS 9 y su orquestación (piso prudencial).

Son **dos motores separados** (ESPEC §5.4): :mod:`nikodym.provisioning.cmf`
(``PE = PI·PDI·Exposición``, B-1) e :mod:`nikodym.provisioning.ifrs9` (ECL). La provisión reportada
es el **máximo** de ambos (piso prudencial CMF), que orquesta esta capa fina (SDD-17).

Al importarse, este paquete registra :class:`ProvisioningConfig` en el hook diferido de
:mod:`nikodym.core.config.schema` e importa :mod:`nikodym.provisioning.step` para ejecutar
``@register("standard", domain="provisioning")`` del :class:`ProvisioningStep`. Así
``NikodymConfig.provisioning`` se valida como sub-config real y el step queda disponible en el
``REGISTRY`` sin que ``import nikodym.core`` arrastre ``nikodym.provisioning`` ni dependencias
tabulares pesadas. Ni los DTOs, ni el orchestrator, ni el step importan ``pandas`` al cargar el
módulo (``pandas`` se usa perezosamente dentro de ``compare``), de modo que
``import nikodym.provisioning`` sigue siendo liviano.

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
from nikodym.provisioning.orchestrator import ProvisioningOrchestrator
from nikodym.provisioning.results import (
    ProvisionComparisonRecord,
    ProvisionComparisonSummary,
    ProvisionOrchestrationCard,
    ProvisionOrchestrationResult,
)
from nikodym.provisioning.step import PROVISIONING_ARTIFACTS, ProvisioningStep

# Registra la clase real del sub-config `provisioning` en el hook de `core`. El import de `step`
# (arriba) ejecuta @register("standard", domain="provisioning") sin cargar pandas.
_schema._PROVISIONING_CONFIG_CLS = ProvisioningConfig

__all__ = [
    "PROVISIONING_ARTIFACTS",
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
    "ProvisioningOrchestrator",
    "ProvisioningRoundingPolicy",
    "ProvisioningStep",
]
