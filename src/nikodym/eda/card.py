"""Sección EDA para el model card y reporte (SDD-27 §4; consumida por SDD-26).

``EdaCardSection`` resume los diagnósticos ya calculados por ``EdaStep`` para que ``report``
pueda leer un artefacto compacto y auditable. La construcción vive en ``EdaStep`` porque allí
coexisten los cinco sub-resultados EDA; este módulo no recalcula analizadores ni importa motores
gráficos.

Decisiones para revisión de Cami:
- Los nombres exactos del resumen quedan fijados como campos de ``EdaCardSection``.
- El recuento de flags de calidad se materializa como ``quality_flag_counts: dict[str, int]``
  sobre los tres flags booleanos ``near_constant``, ``near_unique`` y ``high_cardinality``.
  ``missing_rate`` queda excluido porque es una variable continua, no un flag.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["EdaCardSection"]


class EdaCardSection(BaseModel):
    """Resumen auditable del EDA para el model card y el reporte."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    overall_default_rate: float
    n_periods: int
    stability_flagged: bool
    stability_metric_used: str
    stability_threshold: float
    stability_value: float
    n_columns_profiled: int
    quality_flag_counts: dict[str, int]
    n_figures: int
