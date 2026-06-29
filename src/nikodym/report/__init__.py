"""Capa ``report`` de Nikodym: reportes auditables de scorecard (SDD-26).

Al importarse, registra :class:`ReportConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.report`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.report`` ni dependencias de render/IA. Los DTOs de
resultados se reexportan de forma perezosa; ``report.step`` se añadirá en un bloque posterior.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.report.config import (
    AiNarrationConfig,
    HtmlRenderConfig,
    QuartoRenderConfig,
    ReportConfig,
    SectionPolicyConfig,
)
from nikodym.report.exceptions import (
    ReportAIError,
    ReportDependencyError,
    ReportError,
    ReportExportError,
    ReportInputError,
    ReportRenderError,
)

# Registra la clase real del sub-config report en el hook de `core`.
_schema._REPORT_CONFIG_CLS = ReportConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "AIClient": ("nikodym.report.ai", "AIClient"),
    "AINarrator": ("nikodym.report.ai", "AINarrator"),
    "AIRequest": ("nikodym.report.ai", "AIRequest"),
    "AIResponse": ("nikodym.report.ai", "AIResponse"),
    "AiNarrationBlock": ("nikodym.report.results", "AiNarrationBlock"),
    "ReportBuilder": ("nikodym.report.builder", "ReportBuilder"),
    "ReportInputBundle": ("nikodym.report.results", "ReportInputBundle"),
    "ReportManifest": ("nikodym.report.results", "ReportManifest"),
    "ReportResult": ("nikodym.report.results", "ReportResult"),
    "ReportSection": ("nikodym.report.results", "ReportSection"),
    "RuleBasedNarrator": ("nikodym.report.ai", "RuleBasedNarrator"),
}

__all__ = [
    "AIClient",
    "AINarrator",
    "AIRequest",
    "AIResponse",
    "AiNarrationBlock",
    "AiNarrationConfig",
    "HtmlRenderConfig",
    "QuartoRenderConfig",
    "ReportAIError",
    "ReportBuilder",
    "ReportConfig",
    "ReportDependencyError",
    "ReportError",
    "ReportExportError",
    "ReportInputBundle",
    "ReportInputError",
    "ReportManifest",
    "ReportRenderError",
    "ReportResult",
    "ReportSection",
    "RuleBasedNarrator",
    "SectionPolicyConfig",
]


def __getattr__(name: str) -> Any:
    """Carga DTOs de ``report`` bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.report' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
