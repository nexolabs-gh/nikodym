"""Constantes y derivaciones canónicas para manifiestos de ``report``."""

from __future__ import annotations

import hashlib
from typing import Final

from nikodym.report.config import ReportConfig
from nikodym.report.results import ReportInputBundle

REPORT_TEMPLATE_VERSION: Final = "1.0.0"
REPORT_TITLE: Final = "Reporte scorecard"


def html_report_id(bundle: ReportInputBundle, config: ReportConfig) -> str:
    """Deriva el identificador estable del reporte HTML desde contenido lógico."""
    raw = f"{bundle.lineage.config_hash}:{config.html.template_id}:{config.basename}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
