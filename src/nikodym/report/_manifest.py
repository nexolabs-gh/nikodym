"""Constantes y derivaciones canónicas para manifiestos de ``report``."""

from __future__ import annotations

import hashlib
from typing import Final

from nikodym.report.config import ReportConfig
from nikodym.report.results import ReportInputBundle

REPORT_TEMPLATE_VERSION: Final = "1.0.0"
REPORT_TITLE: Final = "Reporte scorecard"
DOCUMENT_TITLE: Final = "Informe de Validación de Scorecard"
"""Título del **documento** (la portada y el H1), distinto de ``REPORT_TITLE`` (el del artefacto,
que viaja en el manifest). Vive aquí, y no en la plantilla HTML, porque los tres formatos —HTML,
``.qmd`` y ``.docx``— tienen que titular el informe igual."""


def html_report_id(bundle: ReportInputBundle, config: ReportConfig) -> str:
    """Deriva el identificador estable del reporte HTML desde contenido lógico."""
    raw = f"{bundle.lineage.config_hash}:{config.html.template_id}:{config.basename}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
