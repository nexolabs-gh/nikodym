"""Config declarativo de la capa ``binning`` (SDD-06 §5).

:class:`BinningConfig` es la sección ``binning`` de
:class:`~nikodym.core.config.NikodymConfig`: binning supervisado óptimo, WoE e IV para la
scorecard de comportamiento. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada
campo declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un
editor del mismo config. La sección es computacional, por lo que entra al ``config_hash`` global
cuando está activa.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig

MonotonicTrend = Literal[
    "auto",
    "auto_heuristic",
    "auto_asc_desc",
    "ascending",
    "descending",
    "concave",
    "convex",
    "peak",
    "peak_heuristic",
    "valley",
    "valley_heuristic",
]

__all__ = ["BinningConfig", "MonotonicTrend", "VariableBinningConfig"]


class VariableBinningConfig(NikodymBaseConfig):
    """Overrides de binning para una variable específica."""

    name: str = Field(
        default=...,
        title="Variable",
        description="Nombre de la variable cruda a la que aplica este override.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Overrides por variable",
            "ui_order": 1,
            "ui_help": "Nombre exacto de la columna cruda a la que aplican los ajustes de esta "
            "fila; debe coincidir con el nombre en los datos.",
        },
    )
    dtype: Literal["numerical", "categorical", "auto"] = Field(
        default="auto",
        title="Tipo",
        description="'auto' deja que el transformer infiera el tipo; los otros valores lo fuerzan.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Overrides por variable",
            "ui_order": 2,
            "ui_help": "Fuerza el tipo de esta variable cuando la detección automática se "
            "equivoca (p. ej. un código guardado como número que en realidad es categórico).",
        },
    )
    monotonic_trend: MonotonicTrend | None = Field(
        default=None,
        title="Monotonía específica",
        description="Monotonía de event rate para esta variable; None usa el default global.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Overrides por variable",
            "ui_order": 3,
            "ui_help": "Anula la monotonía global solo para esta variable cuando su relación "
            "con el riesgo es distinta al resto (p. ej. una forma en U que pide 'valley').",
        },
    )
    max_n_bins: int | None = Field(
        default=None,
        ge=2,
        le=50,
        title="Máximo de bins específico",
        description="Número máximo de bins finales para esta variable; None usa el valor global.",
        json_schema_extra={
            "ui_widget": "slider",
            "ui_group": "Overrides por variable",
            "ui_order": 4,
            "ui_help": "Tope de bins propio de esta variable, por si necesita más o menos "
            "granularidad que el máximo global (p. ej. una variable muy predictiva).",
        },
    )
    min_bin_size: float | None = Field(
        default=None,
        ge=0.0,
        le=0.5,
        title="Tamaño mínimo específico",
        description="Fracción mínima por bin final para esta variable; None usa el valor global.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Overrides por variable",
            "ui_order": 5,
            "ui_help": "Tamaño mínimo de bin propio de esta variable; úsalo cuando su "
            "distribución (p. ej. muy concentrada) necesita un piso distinto al global.",
        },
    )
    cat_cutoff: float | None = Field(
        default=None,
        ge=0.0,
        le=0.5,
        title="Umbral rare levels específico",
        description=(
            "Frecuencia bajo la cual se agrupan niveles categóricos raros; None usa global."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Overrides por variable",
            "ui_order": 6,
            "ui_help": "Umbral de categoría rara propio de esta variable; úsalo cuando su "
            "cardinalidad o distribución de niveles difiere del resto de las variables.",
        },
    )


class BinningConfig(NikodymBaseConfig):
    """Sección ``binning`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-06 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección binning",
        description="== @register('standard', domain='binning') (D-CONV-2).",
        json_schema_extra={
            "ui_widget": "hidden",
            "ui_group": "General",
            "ui_order": 0,
            "ui_help": "Identificador interno del tipo de sección; no requiere edición.",
        },
    )
    feature_columns: tuple[str, ...] | Literal["*"] = Field(
        default="*",
        title="Variables candidatas",
        description="'*' = todas las no estructurales del frame de data.",
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Variables",
            "ui_order": 1,
            "ui_help": "Variables a binear. Deja '*' para incluir todas las columnas no "
            "estructurales del dataset, o elige una lista explícita para acotar el universo.",
        },
    )
    exclude_columns: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Variables excluidas",
        description="Columnas a excluir del binning aunque entren por feature_columns='*'.",
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Variables",
            "ui_order": 2,
            "ui_help": "Variables que se sacan del binning aunque queden incluidas por "
            "feature_columns='*'; útil para descartar columnas puntuales sin listar el resto.",
        },
    )
    categorical_columns: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Variables categóricas",
        description=(
            "Variables que OptBinning debe tratar como categóricas aunque pandas no lo infiera."
        ),
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Variables",
            "ui_order": 3,
            "ui_help": "Fuerza a que estas variables se traten como categóricas aunque su tipo "
            "de dato luzca numérico (p. ej. códigos de región guardados como enteros).",
        },
    )
    variable_overrides: tuple[VariableBinningConfig, ...] = Field(
        default_factory=tuple,
        title="Overrides por variable",
        description="Ajustes específicos de tipo, monotonía, número de bins o rare levels.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": "Variables",
            "ui_order": 4,
            "ui_help": "Ajustes específicos por variable que anulan, solo para las variables "
            "listadas, los valores globales de tipo, monotonía, bins o rare levels.",
        },
    )

    max_n_prebins: int = Field(
        default=20,
        ge=2,
        le=200,
        title="Máximo de prebins",
        description="Límite de prebins candidatos antes de resolver el binning óptimo.",
        json_schema_extra={
            "ui_widget": "slider",
            "ui_group": "Restricciones",
            "ui_order": 1,
            "ui_help": "Cantidad de cortes candidatos que se exploran antes de optimizar. Más "
            "prebins dan más flexibilidad para encontrar buenos cortes, a costa de más cómputo.",
        },
    )
    min_prebin_size: float = Field(
        default=0.05,
        gt=0.0,
        le=0.5,
        title="Tamaño mínimo de prebin",
        description="Fracción mínima de observaciones por prebin candidato.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Restricciones",
            "ui_order": 2,
            "ui_help": "Fracción mínima de observaciones que debe tener cada corte candidato. "
            "Subirlo evita prebins minúsculos y poco robustos en variables con colas largas.",
        },
    )
    min_n_bins: int | None = Field(
        default=None,
        ge=2,
        le=50,
        title="Mínimo de bins",
        description="Número mínimo de bins finales; None deja la decisión al solver.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Restricciones",
            "ui_order": 3,
            "ui_help": "Piso de bins finales por variable; deja None si prefieres que el solver "
            "decida libremente cuántos bins usar según lo que aporten a separar el riesgo.",
        },
    )
    max_n_bins: int | None = Field(
        default=8,
        ge=2,
        le=50,
        title="Máximo de bins",
        description="Número máximo de bins finales por variable.",
        json_schema_extra={
            "ui_widget": "slider",
            "ui_group": "Restricciones",
            "ui_order": 4,
            "ui_help": "Tope de bins (grupos) por variable tras optimizar. Menos bins = scorecard "
            "más robusta y estable; más bins captan no linealidades pero arriesgan sobreajuste.",
        },
    )
    min_bin_size: float | None = Field(
        default=0.05,
        ge=0.0,
        le=0.5,
        title="Tamaño mínimo de bin",
        description=(
            "Fracción mínima de observaciones por bin final; None usa el default del motor."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Restricciones",
            "ui_order": 5,
            "ui_help": "Fracción mínima de observaciones que debe tener cada bin final. Evita "
            "bins con pocos casos, donde el WoE queda inestable y poco confiable fuera de muestra.",
        },
    )
    min_bin_n_event: int | None = Field(
        default=1,
        ge=1,
        title="Mínimo de malos por bin",
        description="Mínimo de eventos/defaults requeridos en cada bin final.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Restricciones",
            "ui_order": 6,
            "ui_help": "Cantidad mínima de casos malos (eventos/default) exigida en cada bin "
            "final; protege contra bins con tan pocos eventos que el WoE queda mal estimado.",
        },
    )
    min_bin_n_nonevent: int | None = Field(
        default=1,
        ge=1,
        title="Mínimo de buenos por bin",
        description="Mínimo de no-eventos/no-defaults requeridos en cada bin final.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Restricciones",
            "ui_order": 7,
            "ui_help": "Misma protección que el mínimo de malos por bin, pero exigida sobre la "
            "cantidad de casos buenos (no-eventos) en cada bin final.",
        },
    )

    monotonic_trend: MonotonicTrend | None = Field(
        default="auto_asc_desc",
        title="Monotonía por defecto",
        description="Default Nikodym: escoger automáticamente event rate ascendente/descendente.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Monotonía",
            "ui_order": 1,
            "ui_help": "Forma de la relación entre cada variable y el riesgo que debe respetar "
            "el binning. Fuerza un valor solo si conoces de antemano el comportamiento esperado.",
        },
    )
    min_event_rate_diff: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        title="Diferencia mínima de event rate",
        description="Separación mínima de tasa de evento entre bins consecutivos.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Monotonía",
            "ui_order": 2,
            "ui_help": "Diferencia mínima de tasa de malos exigida entre bins vecinos. Subirlo "
            "evita bins casi idénticos en riesgo que no aportan poder discriminante real.",
        },
    )
    max_pvalue: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        title="p-valor máximo entre bins",
        description="Restricción opcional de p-valor máximo; None desactiva esta restricción.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Monotonía",
            "ui_order": 3,
            "ui_help": "Exige que la diferencia de riesgo entre bins sea estadísticamente "
            "significativa hasta este p-valor. Déjalo en None si no quieres esta restricción.",
        },
    )
    max_pvalue_policy: Literal["consecutive", "all"] = Field(
        default="consecutive",
        title="Política p-valor",
        description="Aplica la restricción de p-valor sobre bins consecutivos o todos los pares.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Monotonía",
            "ui_order": 4,
            "ui_help": "Define si la prueba de p-valor máximo se aplica solo entre bins vecinos "
            "('consecutive') o entre todos los pares de bins ('all', más exigente).",
        },
    )

    solver: Literal["cp", "mip"] = Field(
        default="mip",
        title="Solver",
        description=(
            "Solver de OptBinning para el binning óptimo. Default 'mip': el solver 'cp' se cuelga "
            "indefinidamente (ignora time_limit) sobre variables continuas con ortools>=9.12."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Solver",
            "ui_order": 1,
            "ui_help": "Motor de optimización de los cortes. Mantén 'mip': 'cp' está "
            "deshabilitado porque puede quedarse colgado indefinidamente en variables continuas.",
        },
    )
    mip_solver: Literal["bop", "cbc"] = Field(
        default="bop",
        title="MIP solver",
        description="Solver MIP transitivo cuando solver='mip'.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Solver",
            "ui_order": 2,
            "ui_help": "Implementación MIP concreta usada cuando 'solver' es 'mip'. Cámbiala "
            "solo por un motivo técnico puntual; el default funciona para la mayoría de los casos.",
        },
    )
    time_limit: int = Field(
        default=100,
        ge=1,
        le=3600,
        title="Límite de tiempo por variable (segundos)",
        description=(
            "Tiempo máximo de optimización por variable antes de evaluar status del solver."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Solver",
            "ui_order": 3,
            "ui_help": "Tiempo máximo que se le da al solver por variable antes de aceptar la "
            "mejor solución encontrada. Subirlo ayuda en variables difíciles, con más cómputo.",
        },
    )
    require_optimal: bool = Field(
        default=True,
        title="Exigir status óptimo",
        description="Si True, una solución no probada óptima falla ruidosamente.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Solver",
            "ui_order": 4,
            "ui_help": "Si está activo, una variable cuyo solver no probó una solución óptima "
            "se descarta en vez de publicarse subóptima. Recomendado mantenerlo activo.",
        },
    )
    n_jobs: int | None = Field(
        default=None,
        title="Paralelismo de BinningProcess",
        description="None = 1 core. Para reproducibilidad regulatoria se recomienda no usar -1.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Solver",
            "ui_order": 5,
            "ui_help": "Núcleos usados para binear variables en paralelo. Deja None (1 core) "
            "para reproducibilidad exacta entre corridas; -1 acelera pero puede variar resultados.",
        },
    )

    special_handling: Literal["separate", "as_missing"] = Field(
        default="separate",
        title="Tratamiento de special values",
        description="'separate' usa special_codes; 'as_missing' los deja como missing.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Missing y special",
            "ui_order": 1,
            "ui_help": "Cómo tratar los valores especiales (centinelas como 'sin información' o "
            "'no aplica'): 'separate' les da bin propio con WoE propio; 'as_missing' los fusiona "
            "con los faltantes.",
        },
    )
    metric_special: Literal["empirical"] | float = Field(
        default="empirical",
        title="WoE para special",
        description="'empirical' usa el WoE observado del bin special; un float fuerza ese valor.",
        json_schema_extra={
            "ui_widget": "number_or_select",
            "ui_group": "Missing y special",
            "ui_order": 2,
            "ui_help": "WoE del bin de valores especiales. 'empirical' usa el WoE calculado de "
            "los datos observados; un número lo fuerza manualmente (p. ej. para neutralizarlo).",
        },
    )
    metric_missing: Literal["empirical"] | float = Field(
        default="empirical",
        title="WoE para missing",
        description="'empirical' usa el WoE observado del bin missing; un float fuerza ese valor.",
        json_schema_extra={
            "ui_widget": "number_or_select",
            "ui_group": "Missing y special",
            "ui_order": 3,
            "ui_help": "WoE del bin de valores faltantes. 'empirical' usa el WoE calculado de "
            "los datos observados; un número lo fuerza manualmente.",
        },
    )
    cat_cutoff: float | None = Field(
        default=0.01,
        ge=0.0,
        le=0.5,
        title="Umbral de rare levels",
        description="Frecuencia bajo la cual OptBinning agrupa niveles categóricos raros.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Categóricas",
            "ui_order": 1,
            "ui_help": "Frecuencia mínima bajo la cual una categoría se considera rara y se "
            "agrupa con otras antes de optimizar; súbelo en variables con muchos niveles poco "
            "poblados.",
        },
    )
    cat_unknown: float | str | None = Field(
        default=None,
        title="Valor para categoría no vista",
        description="None en OptBinning asigna WoE neutral 0 cuando metric='woe'.",
        json_schema_extra={
            "ui_widget": "text_or_number",
            "ui_group": "Categóricas",
            "ui_order": 2,
            "ui_help": "WoE a usar cuando en producción aparece una categoría nunca vista en el "
            "ajuste. None asigna WoE neutral (0), tratándola como neutra respecto al riesgo.",
        },
    )
    split_digits: int | None = Field(
        default=None,
        ge=0,
        le=10,
        title="Dígitos de cortes",
        description=(
            "Número de decimales para representar cortes; None conserva precisión del motor."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Salida",
            "ui_order": 1,
            "ui_help": "Cantidad de decimales con que se redondean los puntos de corte "
            "numéricos. Deja None para conservar la precisión completa del solver.",
        },
    )
    output_suffix: str = Field(
        default="__woe",
        title="Sufijo de columnas WoE",
        description="Sufijo que se agrega al nombre crudo para las columnas transformadas a WoE.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Salida",
            "ui_order": 2,
            "ui_help": "Sufijo agregado al nombre de cada variable original para nombrar su "
            "columna transformada a WoE (p. ej. 'edad' pasa a 'edad__woe').",
        },
    )
    keep_structural_columns: bool = Field(
        default=True,
        title="Conservar columnas estructurales de data",
        description="Incluye columnas estructurales mínimas junto a las columnas WoE publicadas.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Salida",
            "ui_order": 3,
            "ui_help": "Si está activo, conserva columnas estructurales (como target o "
            "partición) junto a las columnas WoE en la salida, útil para trazabilidad posterior.",
        },
    )
    fail_on_non_binnable: bool = Field(
        default=False,
        title="Fallar ante variable no binneable",
        description="Si True, una variable constante, 100% missing o no soportada aborta el fit.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Salida",
            "ui_order": 4,
            "ui_help": "Si está activo, encontrar una variable constante, 100% vacía o no "
            "soportada detiene todo el ajuste con error; si está apagado, esa variable se omite "
            "y queda registrada como descartada.",
        },
    )

    @model_validator(mode="after")
    def _check_bin_range(self) -> Self:
        """Valida que el rango mínimo/máximo de bins sea coherente cuando ambos existen."""
        if (
            self.min_n_bins is not None
            and self.max_n_bins is not None
            and self.min_n_bins > self.max_n_bins
        ):
            raise ValueError("min_n_bins no puede ser mayor que max_n_bins.")
        return self
