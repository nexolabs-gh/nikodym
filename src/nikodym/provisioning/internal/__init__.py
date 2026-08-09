"""Método **interno** de provisiones por tasa de pérdida del grupo homogéneo.

El cálculo es **jurisdiccionalmente neutro** y es el único componente de ``provisioning`` que lo es:
segmenta a los deudores en grupos homogéneos y multiplica la exposición de cada grupo por una tasa
de pérdida: descompuesta en PD · LGD o provista directamente. No conoce ninguna cartera
normativa ni ninguna tabla de supervisor, y su estado de fábrica tampoco los nombra. La PD puede
salir del scorecard calibrado o del modelo declarado; en la forma directa no multiplica la
provisión.

Como **evidencia** de que ese motor encaja donde se lo exige —y no como su definición—: el Cap. B-1
§3 del Compendio de la CMF de Chile obliga a todo banco a mantener metodologías propias junto al
método estándar (*"debiendo por tanto disponer de ambos métodos"*) y describe el interno en esos
mismos términos. El encuadre importa y ya costó una corrección: hasta el 2026-08-05 la sección de
este motor se titulaba «(Cap. B-1 §3)» en el formulario, frase que además de reducir el alcance
percibido era **falsa** —este motor no calcula el B-1—, y este docstring la repetía. La regla es la
del 2026-08-04: una jurisdicción nunca va en la propuesta de valor; va en la evidencia
(``docs_site/norma-local.md``, ``tests/unit/test_portada_sin_jurisdiccion.py``).

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
    InternalLgdBetaRegression,
    InternalLgdConfig,
    InternalLgdFractionalResponse,
    InternalLgdGroupHistorical,
    InternalLgdMethod,
    InternalLgdModelada,
    InternalLgdProvided,
    InternalLgdWorkout,
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
    "InternalLgdBetaRegression",
    "InternalLgdConfig",
    "InternalLgdFractionalResponse",
    "InternalLgdGroupHistorical",
    "InternalLgdMethod",
    "InternalLgdModelada",
    "InternalLgdProvided",
    "InternalLgdWorkout",
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
