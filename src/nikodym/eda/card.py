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

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["EdaCardSection"]


class EdaCardSection(BaseModel):
    """Resumen auditable del EDA para el model card y el reporte.

    Los tres campos con default son aditivos (D-SC-5, §0-11 del scorecard completo): ``axis`` es
    el eje **efectivo** —el que ``DefaultRateResult`` usó, que con la inferencia de D-SC-3 puede
    ser la cohorte aunque el config diga ``period``—, ``axis_inferred`` dice si fue el motor quien
    lo decidió, y ``stability_not_evaluable_reason`` es la causa por la que la señal temporal no
    se evaluó, o ``None`` si se evaluó. Los tres viajan hasta el panel y la prosa del informe,
    que sin ellos leían ``stability_value = NaN`` sin poder decir por qué.
    """

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
    axis: Literal["period", "cohort"] = "period"
    axis_inferred: bool = False
    stability_not_evaluable_reason: (
        Literal["eje_cohorte", "pocos_periodos_evaluables", "tasa_media_cero"] | None
    ) = None
