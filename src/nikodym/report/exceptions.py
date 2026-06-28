"""Excepciones propias de la capa ``report`` (SDD-26 §4)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "ReportAIError",
    "ReportDependencyError",
    "ReportError",
    "ReportExportError",
    "ReportInputError",
    "ReportRenderError",
]


class ReportError(NikodymError):
    """Error base de la generación de reportes auditables."""


class ReportInputError(ReportError):
    """Error en las cards, tablas, lineage o secciones usadas para construir el reporte."""


class ReportRenderError(ReportError):
    """Error al renderizar el reporte en HTML u otro formato de lectura."""


class ReportExportError(ReportError):
    """Error al escribir o exportar artefactos del reporte."""


class ReportAIError(ReportError):
    """Error en la narrativa IA opcional del reporte."""


class ReportDependencyError(ReportError):
    """Error por dependencia opcional ausente o no disponible para el reporte."""
