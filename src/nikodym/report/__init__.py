"""Capa ``report`` de Nikodym: reportes auditables de scorecard (SDD-26).

Al importarse, registra :class:`ReportConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.report`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.report`` ni dependencias de render/IA. B26.1 solo
publica config y excepciones; ``report.step`` se añadirá en un bloque posterior.

**Experimental (SemVer 0.x).**
"""

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

__all__ = [
    "AiNarrationConfig",
    "HtmlRenderConfig",
    "QuartoRenderConfig",
    "ReportAIError",
    "ReportConfig",
    "ReportDependencyError",
    "ReportError",
    "ReportExportError",
    "ReportInputError",
    "ReportRenderError",
    "SectionPolicyConfig",
]
