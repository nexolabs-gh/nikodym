"""Capa ``selection`` de Nikodym: selección pre-modelo de variables WoE (SDD-07).

Al importarse, registra :class:`SelectionConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.selection`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.selection`` ni dependencias de scoring. La
lógica de selección (``selector.py``/``step.py``) se materializa en B7.3; esta capa inicial deja la
superficie preparada con reexportación perezosa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    SelectionPriority,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.selection.exceptions import (
    SelectionError,
    SelectionFitError,
    SelectionTransformError,
)

# Registra la clase real del sub-config selection en el hook de `core`.
_schema._SELECTION_CONFIG_CLS = SelectionConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "FeatureSelector": ("nikodym.selection.selector", "FeatureSelector"),
    "SelectionCardSection": ("nikodym.selection.results", "SelectionCardSection"),
    "SelectionDecisionReason": ("nikodym.selection.results", "SelectionDecisionReason"),
    "SelectionResult": ("nikodym.selection.results", "SelectionResult"),
    "VariableSelectionDecision": (
        "nikodym.selection.results",
        "VariableSelectionDecision",
    ),
}

__all__ = [
    "CorrelationSelectionConfig",
    "FeatureSelector",
    "SelectionCardSection",
    "SelectionConfig",
    "SelectionDecisionReason",
    "SelectionError",
    "SelectionFitError",
    "SelectionPriority",
    "SelectionResult",
    "SelectionTransformError",
    "StabilitySelectionConfig",
    "VariableSelectionDecision",
    "VifSelectionConfig",
]


def __getattr__(name: str) -> Any:
    """Carga componentes pesados de selection bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.selection' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
