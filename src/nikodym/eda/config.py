"""Config declarativo de la capa ``eda`` (SDD-27 §5).

:class:`EdaConfig` es la sección ``eda`` de :class:`~nikodym.core.config.NikodymConfig`:
diagnóstico exploratorio orientado a riesgo de crédito, sin transformar el dataset para el modelo.
Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y
``frozen=True``); cada campo declara ``title``/``description`` y metadatos ``ui_*`` para que la UI
(SDD-23) sea un editor del mismo config. La sección es computacional, por lo que entra al
``config_hash`` global cuando está activa.

Desde la capa 3 del scorecard completo (D-SC-1) la sección se pinta en el formulario, así que sus
``title``/``description`` son **copy público** —la tabla §3.6 de la enmienda, revisada por Cami
contra la pantalla— y tres campos nombran columnas del archivo del usuario con ``column_role``.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.dataset_check import Requisito

__all__ = [
    "DefaultRateConfig",
    "EdaConfig",
    "QualityConfig",
    "SamplingConfig",
    "TemporalStabilityConfig",
    "UnivariateConfig",
]

_GRUPO_TASA = "Tasa de incumplimiento"
_GRUPO_ESTABILIDAD = "Estabilidad temporal"
_GRUPO_PERFILES = "Perfiles por variable"
_GRUPO_CALIDAD = "Calidad de datos"
_GRUPO_MUESTREO = "Muestreo"


class DefaultRateConfig(NikodymBaseConfig):
    """Configuración de tasa de incumplimiento por período o cohorte."""

    axis: Literal["period", "cohort"] = Field(
        default="period",
        title="Cómo se agrupa en el tiempo",
        description=(
            "Cómo se agrupa la tasa de incumplimiento en el tiempo: por la fecha de observación, "
            "en períodos, o por cohorte o añada. Si eliges fecha y no indicas cuál, el motor usa "
            "la única columna de fecha de tu archivo; si no hay ninguna y particionas por cohorte, "
            "usa esa cohorte y lo deja registrado. Con cohortes la señal de deterioro en el tiempo "
            "no se evalúa: no tienen un orden cronológico que el motor pueda inferir."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": _GRUPO_TASA,
            "ui_order": 1,
        },
    )
    date_col: str | None = Field(
        default=None,
        title="Columna de fecha de observación",
        description=(
            "La columna con la fecha de observación de cada operación. Tiene que ser de tipo fecha "
            "en tu esquema; si no lo es, la corrida se detiene antes de calcular."
        ),
        json_schema_extra={
            # La aporta el usuario, así que el preflight la reclama ANTES de correr — pero sólo
            # con el eje temporal: `columnas_inactivas()` la declara inerte con el eje de cohorte
            # (D-RAM-1, §0-15). En blanco, el motor infiere la única columna de fecha del archivo
            # o —sin fecha y con partición por cohorte— el eje pasa a la cohorte (D-SC-3).
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": _GRUPO_TASA,
            "ui_order": 2,
        },
    )
    period_freq: Literal["M", "Q", "Y"] = Field(
        default="M",
        title="Cada cuánto se agrupa",
        description="Cada cuánto se agrupa la fecha: por mes, por trimestre o por año.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": _GRUPO_TASA,
            "ui_order": 3,
        },
    )
    cohort_col: str | None = Field(
        default=None,
        title="Columna de cohorte o añada",
        description=(
            "La columna con la cohorte o añada de cada operación. Suele ser la misma con la que "
            "particionas tus datos."
        ),
        json_schema_extra={
            # Simétrica de `date_col`: rol de entrada, inerte con el eje temporal (D-RAM-1).
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": _GRUPO_TASA,
            "ui_order": 4,
        },
    )
    min_obs_per_period: int = Field(
        default=50,
        ge=1,
        title="Mínimo de operaciones por período",
        description=(
            "Un período con menos operaciones elegibles que esto se marca como poco fiable en la "
            "tabla. No se elimina: se ve, marcado."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": _GRUPO_TASA,
            "ui_order": 5,
        },
    )

    def columnas_inactivas(self) -> frozenset[str]:
        """La columna del eje que NO se usa es inerte (D-RAM-1, §0-15 del scorecard completo).

        Medido en ``default_rate.py::_resolve_group_frame``: el motor consume sólo la columna del
        eje activo —``date_col`` con ``axis="period"``, ``cohort_col`` con ``axis="cohort"``— y
        nunca la otra. Sin esta declaración, un valor residual en la columna del eje apagado haría
        que el preflight reclamara una columna que la corrida no abre: el falso positivo exacto
        que D-RAM-1 cierra. Con ``date_col`` en blanco el preflight no tiene columna que
        comprobar y el motor decide en la corrida, con su decisión en el trail (D-SC-3).
        """
        return frozenset({"cohort_col"}) if self.axis == "period" else frozenset({"date_col"})

    def requisitos_incumplidos(self, columnas: frozenset[str] | None) -> tuple[Requisito, ...]:
        """Invariantes que el motor exige y que sólo se descubrían corriendo (D-INV-1).

        La única que el preflight puede **afirmar** con lo que sabe: agrupar por cohorte sin decir
        qué columna es. ``_cohort_values`` levanta ``EdaError`` en el paso, con el pipeline entero
        de ``data`` ya pagado; no depende del archivo, así que se avisa aunque ``columnas`` sea
        ``None`` (D-INV-4 protege lo que se afirma del dataset, y esto no dice nada de él).

        ⚠️ La simétrica del eje temporal **no se declara**, a propósito. Con ``axis="period"`` y
        ``date_col`` en blanco la corrida sólo se detiene si el frame no tiene ninguna columna
        ``datetime`` **y** la partición no es por cohorte (D-SC-3). El preflight recibe nombres de
        columna, no tipos: un Parquet trae fechas nativas que ningún esquema declara, y afirmar
        «no tienes fecha» desde los nombres sería el falso positivo más caro del repo (D-INV-4).
        Anticiparlo de verdad exige que el perfil del dataset diga qué columnas son de fecha y que
        el contexto diga si la partición es por cohorte: es una extensión medida y pendiente.
        """
        del columnas  # no depende del dataset
        if self.axis != "cohort" or self.cohort_col is not None:
            return ()
        return (
            Requisito(
                path="cohort_col",
                declared="cohort",
                message=(
                    "Agrupas la tasa de incumplimiento por cohorte y no indicaste qué columna "
                    "trae la cohorte o añada, así que la corrida se detendrá al llegar al análisis "
                    "exploratorio. Indica la columna —suele ser la misma con la que particionas— "
                    "o agrupa por la fecha de observación."
                ),
            ),
        )


class TemporalStabilityConfig(NikodymBaseConfig):
    """Configuración del diagnóstico de estabilidad temporal descriptiva."""

    metric: Literal["cv", "max_relative_drift", "trend_slope"] = Field(
        default="cv",
        title="Indicador de estabilidad",
        description=(
            "Con qué indicador se mide cuánto se mueve la tasa de incumplimiento entre períodos: "
            "variación relativa, peor desvío o tendencia. Se compara con el umbral para avisar un "
            "posible redesarrollo."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": _GRUPO_ESTABILIDAD,
            "ui_order": 1,
        },
    )
    threshold: float = Field(
        default=0.25,
        ge=0.0,
        title="Umbral de aviso",
        description=(
            "Por encima de este valor se registra un aviso de posible redesarrollo. Es un umbral "
            "de exploración, no una regla: la corrida sigue."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": _GRUPO_ESTABILIDAD,
            "ui_order": 2,
        },
    )


class UnivariateConfig(NikodymBaseConfig):
    """Configuración de perfiles descriptivos por variable."""

    n_quantile_bins: int = Field(
        default=10,
        ge=2,
        le=50,
        title="Tramos por variable numérica",
        description=(
            "En cuántos tramos se parte cada variable numérica para ver su tasa de incumplimiento. "
            "Es sólo para describir; no es el binning que entra al modelo."
        ),
        json_schema_extra={
            "ui_widget": "slider",
            "ui_group": _GRUPO_PERFILES,
            "ui_order": 1,
        },
    )
    rare_level_threshold: float = Field(
        default=0.01,
        ge=0.0,
        le=0.5,
        title="Frecuencia mínima de un valor categórico",
        description=(
            "Los valores de una variable categórica con menos frecuencia que esto se agrupan bajo "
            "«otros», sólo para la tabla."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": _GRUPO_PERFILES,
            "ui_order": 2,
        },
    )
    compute_descriptive_iv: bool = Field(
        default=False,
        title="Calcular un poder predictivo orientativo",
        description=(
            "Calcula un poder predictivo orientativo por variable sobre estos tramos. No es el IV "
            "que decide el modelo: ése lo calcula el binning."
        ),
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": _GRUPO_PERFILES,
            "ui_order": 3,
        },
    )
    columns: tuple[str, ...] | None = Field(
        default=None,
        title="Columnas a describir",
        description=(
            "Qué columnas describir frente al incumplimiento. Con «Todas las columnas» se "
            "describen todas las de tu archivo salvo las estructurales (target, estado, "
            "partición, fecha y cohorte) y las que definen el incumplimiento; si eliges columnas, "
            "sólo ésas, y una selección vacía no describe ninguna. Define qué se describe, no qué "
            "entra al modelo."
        ),
        json_schema_extra={
            # 🔴 Sólo `None` significa «todas» (§0-23): una tupla vacía se respeta y produce cero
            # perfiles, y vaciar un multiselect corriente escribe `[]`. Por eso el control es el
            # widget anulable —la casilla «Todas las columnas» escribe nulo; desmarcada, la
            # lista— y no un multiselect a secas (D-SC-1).
            "column_role": "input",
            "ui_widget": "multiselect_o_todas",
            "ui_group": _GRUPO_PERFILES,
            "ui_order": 4,
        },
    )


class QualityConfig(NikodymBaseConfig):
    """Configuración de diagnóstico descriptivo de calidad de datos."""

    near_constant_threshold: float = Field(
        default=0.99,
        ge=0.5,
        le=1.0,
        title="Umbral de columna casi constante",
        description=(
            "Si un solo valor concentra al menos esta proporción de las filas con dato, la columna "
            "se marca como casi constante. Sólo se reporta."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": _GRUPO_CALIDAD,
            "ui_order": 1,
        },
    )
    high_cardinality_threshold: int = Field(
        default=50,
        ge=2,
        title="Umbral de alta cardinalidad",
        description=(
            "Una variable categórica con más valores distintos que esto se marca como de alta "
            "cardinalidad. Sólo se reporta."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": _GRUPO_CALIDAD,
            "ui_order": 2,
        },
    )


class SamplingConfig(NikodymBaseConfig):
    """Configuración de muestreo opcional para datasets grandes."""

    enabled: bool = Field(
        default=False,
        title="Muestrear para los perfiles por variable",
        description=(
            "Calcula los perfiles por variable y sus figuras sobre una muestra, para archivos "
            "grandes. La tasa de incumplimiento por período se calcula siempre sobre el total."
        ),
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": _GRUPO_MUESTREO,
            "ui_order": 1,
        },
    )
    max_rows: int = Field(
        default=500_000,
        ge=1000,
        title="Máximo de filas en la muestra",
        description="Cuántas filas entran a la muestra cuando el muestreo está activo.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": _GRUPO_MUESTREO,
            "ui_order": 2,
        },
    )


class EdaConfig(NikodymBaseConfig):
    """Describe la cartera antes de modelar: tasa de incumplimiento, perfiles y calidad de datos."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección EDA",
        description="Variante de la sección EDA; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    analysis_partition: Literal["desarrollo", "holdout", "oot", "todas"] = Field(
        default="desarrollo",
        title="Población a describir",
        description=(
            "Sobre qué parte de tu archivo se describe la cartera. De fábrica, la partición de "
            "desarrollo, que es donde se ajusta el modelo. Las operaciones fuera del modelo se "
            "cuentan, pero no entran en la tasa de incumplimiento."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 1},
    )
    default_rate: DefaultRateConfig = Field(
        default_factory=DefaultRateConfig,
        title=_GRUPO_TASA,
        description="Cómo se agrupa la tasa de incumplimiento observada en el tiempo.",
        json_schema_extra={"ui_widget": "section", "ui_group": _GRUPO_TASA, "ui_order": 2},
    )
    stability: TemporalStabilityConfig = Field(
        default_factory=TemporalStabilityConfig,
        title=_GRUPO_ESTABILIDAD,
        description="Con qué indicador y umbral se avisa un deterioro de la tasa en el tiempo.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": _GRUPO_ESTABILIDAD,
            "ui_order": 3,
        },
    )
    univariate: UnivariateConfig = Field(
        default_factory=UnivariateConfig,
        title=_GRUPO_PERFILES,
        description="Qué columnas se describen frente al incumplimiento y en cuántos tramos.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": _GRUPO_PERFILES,
            "ui_order": 4,
        },
    )
    quality: QualityConfig = Field(
        default_factory=QualityConfig,
        title=_GRUPO_CALIDAD,
        description="Umbrales de las marcas de calidad por columna; sólo se reportan.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": _GRUPO_CALIDAD,
            "ui_order": 5,
        },
    )
    sampling: SamplingConfig = Field(
        default_factory=SamplingConfig,
        title=_GRUPO_MUESTREO,
        description="Muestreo opcional de los perfiles cuando el archivo es muy grande.",
        json_schema_extra={"ui_widget": "section", "ui_group": _GRUPO_MUESTREO, "ui_order": 6},
    )
