"""Provisiones de Nikodym: motores (estándar / interno / IFRS 9) y su orquestación.

Son **motores separados**: :mod:`nikodym.provisioning.cmf` (método **estándar** del B-1,
``PE = PI·PDI·Exposición``), :mod:`nikodym.provisioning.internal` (método **interno** del B-1 §3,
``Exposición · PD · LGD`` por grupo homogéneo, SDD-28) e :mod:`nikodym.provisioning.ifrs9` (ECL).
Esta capa fina (SDD-17) compara **dos fuentes configurables** y aplica la regla declarada. La regla
que exige la norma chilena —Cap. B-1, hoja 10-11 (Circular N° 2.346)— es ``max(estándar, interno)``
**por entidad**, o el interno directamente si está evaluado y no objetado (``rule='use_internal'``);
comparar contra el ECL de NIIF 9 es un comparativo entre marcos, no una exigencia local (Cap. A-2
num. 5).

Al importarse, este paquete registra :class:`ProvisioningConfig` en el hook diferido de
:mod:`nikodym.core.config.schema` e importa :mod:`nikodym.provisioning.step` para ejecutar
``@register("standard", domain="provisioning")`` del :class:`ProvisioningStep`. Así
``NikodymConfig.provisioning`` se valida como sub-config real y el step queda disponible en el
``REGISTRY`` sin que ``import nikodym.core`` arrastre ``nikodym.provisioning`` ni dependencias
tabulares pesadas. Ni los DTOs, ni el orchestrator, ni el step importan ``pandas`` al cargar el
módulo (``pandas`` se usa perezosamente dentro de ``compare``), de modo que
``import nikodym.provisioning`` sigue siendo liviano.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from nikodym.core.config import schema as _schema
from nikodym.provisioning.config import (
    ProvisioningComparisonLevel,
    ProvisioningConfig,
    ProvisioningCoveragePolicy,
    ProvisioningNumericReconciliation,
    ProvisioningRoundingPolicy,
    ProvisioningRule,
    ProvisioningSource,
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
    "ProvisioningRule",
    "ProvisioningSource",
    "ProvisioningStep",
]
