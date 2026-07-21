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

IFRS9_DOCUMENT_TITLE: Final = "Informe de Provisiones IFRS 9 / ECL"
"""Título del documento cuando la corrida es IFRS 9 sin scorecard (SDD-16): titular esa corrida
«Validación de Scorecard» describiría un documento que no es."""

PROVISIONING_DOCUMENT_TITLE: Final = "Informe de Provisiones y Validación de Scorecard"
"""Título cuando la corrida calculó scorecard **y** provisiones. El caso IFRS 9 puro ya tenía su
título, pero una corrida de provisiones que además corre el scorecard que las alimenta —el preset
de provisiones CMF, por ejemplo— caía al título por defecto y se entregaba como «Informe de
Validación de Scorecard», sin nombrar en la portada ni en el pie de sus 60 páginas aquello por lo
que el usuario la corrió. No nombra el marco (CMF/IFRS 9/interno) a propósito: una misma corrida
puede traer más de uno, y el capítulo de provisiones ya declara cuál aplicó."""


def html_report_id(bundle: ReportInputBundle, config: ReportConfig) -> str:
    """Deriva el identificador estable del reporte HTML desde contenido lógico."""
    raw = f"{bundle.lineage.config_hash}:{config.html.template_id}:{config.basename}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
