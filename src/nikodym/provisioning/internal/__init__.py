"""Método **interno** de provisiones del Cap. B-1 de la CMF: ``Exposición · PD · LGD`` por grupo.

El B-1 §3 obliga a todo banco a mantener metodologías propias junto al método estándar (*"debiendo
por tanto disponer de ambos métodos"*) y describe el interno de forma literal: segmentar a los
deudores en **grupos homogéneos** y multiplicar el monto total de colocaciones de cada grupo por su
probabilidad de incumplimiento y su pérdida dado el incumplimiento. Esta capa es ese motor; la PD
sale del scorecard calibrado que Nikodym ya construye.

Al importarse, registra :class:`InternalProvisioningConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.provisioning_internal`` se valida como
sub-config real sin que ``import nikodym.core`` arrastre ``nikodym.provisioning`` ni dependencias
tabulares pesadas.

El paquete importa ``provisioning.internal.step`` al final para ejecutar ``@register("standard",
domain="provisioning_internal")`` sin cargar pandas ni el motor; los resultados y componentes con
dependencias de cálculo se reexportan de forma perezosa.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.provisioning.internal.config import (
    InternalGroupingMethod,
    InternalLgdConfig,
    InternalLgdMethod,
    InternalPdSourceDomain,
    InternalProvisioningConfig,
    InternalProvisioningMethod,
    InternalRoundingPolicy,
)
from nikodym.provisioning.internal.exceptions import (
    InternalCalculationError,
    InternalConfigError,
    InternalInputError,
    InternalProvisioningError,
)

# Registra la clase real del sub-config provisioning_internal en el hook de `core`.
_schema._PROVISIONING_INTERNAL_CONFIG_CLS = InternalProvisioningConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "INTERNAL_PROVISIONING_ARTIFACTS": (
        "nikodym.provisioning.internal.step",
        "INTERNAL_PROVISIONING_ARTIFACTS",
    ),
    "InternalProvisionCard": (
        "nikodym.provisioning.internal.results",
        "InternalProvisionCard",
    ),
    "InternalProvisionRecord": (
        "nikodym.provisioning.internal.results",
        "InternalProvisionRecord",
    ),
    "InternalProvisionResult": (
        "nikodym.provisioning.internal.results",
        "InternalProvisionResult",
    ),
    "InternalProvisioningEngine": (
        "nikodym.provisioning.internal.engine",
        "InternalProvisioningEngine",
    ),
    "InternalProvisioningStep": (
        "nikodym.provisioning.internal.step",
        "InternalProvisioningStep",
    ),
}

__all__ = [
    "INTERNAL_PROVISIONING_ARTIFACTS",
    "InternalCalculationError",
    "InternalConfigError",
    "InternalGroupingMethod",
    "InternalInputError",
    "InternalLgdConfig",
    "InternalLgdMethod",
    "InternalPdSourceDomain",
    "InternalProvisionCard",
    "InternalProvisionRecord",
    "InternalProvisionResult",
    "InternalProvisioningConfig",
    "InternalProvisioningEngine",
    "InternalProvisioningError",
    "InternalProvisioningMethod",
    "InternalProvisioningStep",
    "InternalRoundingPolicy",
]

# Import perezoso a nivel paquete para ejecutar @register("standard",
# domain="provisioning_internal") al importar `nikodym.provisioning.internal`, sin contaminar
# `import nikodym.core` ni cargar pandas o el motor.
importlib.import_module("nikodym.provisioning.internal.step")


def __getattr__(name: str) -> Any:
    """Carga componentes de ``provisioning.internal`` bajo demanda; preserva el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.provisioning.internal' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
