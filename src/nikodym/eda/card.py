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

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["FAILED_ANALYSIS_LABELS", "EdaCardSection", "failed_analysis_sentence"]

#: Lo que se dice de cada sub-análisis que no se pudo calcular (D-SC-20): sujeto y predicado,
#: concordados —las figuras van en plural—. Es el comienzo de la frase «… : <causa>» que el
#: resumen de la etapa, el panel y el informe escriben. El orden es el del paso, y es el orden en
#: que se listan las alertas. La preparación no tiene clave propia: si falla, falla cada uno de
#: los tres que la leen, con la misma causa.
FAILED_ANALYSIS_LABELS: Final[dict[str, str]] = {
    "default_rate": "La tasa de malos en el tiempo no se pudo calcular",
    "stability": "El deterioro de la tasa en el tiempo no se pudo calcular",
    "univariate": "La descripción de las columnas frente al incumplimiento no se pudo calcular",
    "quality": "La revisión de calidad del archivo no se pudo calcular",
    "figures": "Las figuras del análisis exploratorio no se pudieron calcular",
}


def failed_analysis_sentence(key: str, cause: str) -> str:
    """«<Sujeto> no se pudo calcular: «<causa>»», sin punto final (D-SC-20).

    Una sola fuente para el resumen de la etapa y el informe; el panel la replica en el front. La
    causa va **citada**: es el mensaje del motor tal cual, y como cita textual conserva su
    mayúscula inicial tras los dos puntos. Se le quita el punto final para que quien la use cierre
    la frase una sola vez. Una clave que el motor gane sin rótulo se dice igual, con su nombre:
    callarla escondería una falla.
    """
    inicio = FAILED_ANALYSIS_LABELS.get(key, f"{key} no se pudo calcular")
    return f"{inicio}: «{cause.strip().rstrip('.')}»"


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
        Literal[
            "eje_cohorte",
            "no_calculable",
            "pocos_periodos_evaluables",
            "sin_eje_temporal",
            "tasa_media_cero",
            "tasa_no_calculable",
        ]
        | None
    ) = None
    #: Aditivo (D-SC-17): la causa por la que la TASA no se pudo agrupar —sin columna de fecha ni
    #: cohorte declarada—, o ``None``. Va junto a ``n_periods = 0`` y a una ``by_period`` vacía, y
    #: es lo que el resumen de la etapa, la prosa del informe y el panel dicen en palabras en vez
    #: de publicar «agrupada por fecha de observación en 0 períodos».
    default_rate_not_evaluable_reason: Literal["sin_eje_temporal", "no_calculable"] | None = None
    #: Aditivo (D-SC-19/20): los sub-análisis que FALLARON, con su causa en palabras —claves
    #: ``default_rate``, ``stability``, ``univariate``, ``quality`` y ``figures``—. Vacío en toda
    #: corrida sana.
    #: El análisis exploratorio nunca detiene la corrida; esto es lo que dice qué no se calculó, y
    #: lo leen el resumen de la etapa (una alerta por clave), el panel y el informe.
    failed_analyses: dict[str, str] = {}
