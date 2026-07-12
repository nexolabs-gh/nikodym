"""Capa ``report`` de Nikodym: reportes auditables de scorecard (SDD-26).

Al importarse, registra :class:`ReportConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.report`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.report`` ni dependencias de render/IA. El paquete
importa ``report.step`` al final para ejecutar ``@register("standard", domain="report")`` sin
cargar Jinja2, WeasyPrint ni SDKs IA; los DTOs y componentes pesados se reexportan de forma
perezosa.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.report.config import (
    AiNarrationConfig,
    HtmlRenderConfig,
    PdfRenderConfig,
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
    "HtmlReportRenderer": ("nikodym.report.renderer", "HtmlReportRenderer"),
    "PdfReportRenderer": ("nikodym.report.renderer", "PdfReportRenderer"),
    "ReportInputBundle": ("nikodym.report.results", "ReportInputBundle"),
    "ReportManifest": ("nikodym.report.results", "ReportManifest"),
    "ReportResult": ("nikodym.report.results", "ReportResult"),
    "ReportSection": ("nikodym.report.results", "ReportSection"),
    "ReportStep": ("nikodym.report.step", "ReportStep"),
    "RuleBasedNarrator": ("nikodym.report.ai", "RuleBasedNarrator"),
    "render_pdf": ("nikodym.report.pdf", "render_pdf"),
}

__all__ = [
    "AIClient",
    "AINarrator",
    "AIRequest",
    "AIResponse",
    "AiNarrationBlock",
    "AiNarrationConfig",
    "HtmlRenderConfig",
    "HtmlReportRenderer",
    "PdfRenderConfig",
    "PdfReportRenderer",
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
    "ReportStep",
    "RuleBasedNarrator",
    "SectionPolicyConfig",
    "render_pdf",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="report") al importar
# `nikodym.report`, sin contaminar `import nikodym.core` ni cargar Jinja2/WeasyPrint/SDKs IA.
importlib.import_module("nikodym.report.step")


def __getattr__(name: str) -> Any:
    """Carga DTOs de ``report`` bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.report' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
