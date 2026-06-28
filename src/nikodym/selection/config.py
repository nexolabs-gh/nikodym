"""Config declarativo de la capa ``selection`` (SDD-07 §5).

:class:`SelectionConfig` es la sección ``selection`` de
:class:`~nikodym.core.config.NikodymConfig`: filtros pre-modelo auditables sobre variables WoE ya
publicadas por ``binning``. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError

SelectionPriority = Literal["iv", "auc", "ks", "gini", "name"]

__all__ = [
    "CorrelationSelectionConfig",
    "SelectionConfig",
    "SelectionPriority",
    "StabilitySelectionConfig",
    "VifSelectionConfig",
]


class CorrelationSelectionConfig(NikodymBaseConfig):
    """Configuración del filtro por correlación entre columnas WoE candidatas."""

    enabled: bool = Field(
        default=True,
        title="Filtrar por correlación",
        description="Activa el descarte de variables WoE con correlación absoluta alta.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Correlación",
            "ui_order": 1,
        },
    )
    method: Literal["pearson", "spearman", "kendall"] = Field(
        default="pearson",
        title="Método de correlación",
        description="Método usado sobre Desarrollo para medir asociación entre columnas WoE.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Correlación",
            "ui_order": 2,
        },
    )
    threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        title="Umbral |rho|",
        description="Si |rho| supera este valor, se conserva la variable con mayor prioridad.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Correlación",
            "ui_order": 3,
        },
    )
    clustering_method: Literal["none", "connected_components"] = Field(
        default="none",
        title="Clustering por correlación",
        description="Agrupación opcional por componentes conectados del grafo de correlación.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Correlación",
            "ui_order": 4,
        },
    )


class VifSelectionConfig(NikodymBaseConfig):
    """Configuración del filtro iterativo por multicolinealidad VIF."""

    enabled: bool = Field(
        default=True,
        title="Filtrar por VIF",
        description="Activa el descarte iterativo de variables con VIF sobre el umbral.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "VIF", "ui_order": 1},
    )
    threshold: float = Field(
        default=5.0,
        ge=1.0,
        title="Umbral VIF",
        description="VIF máximo aceptado para variables retenidas tras la poda iterativa.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "VIF", "ui_order": 2},
    )
    add_intercept: bool = Field(
        default=True,
        title="Agregar intercepto en regresiones auxiliares",
        description="Si True, agrega constante explícita antes de calcular VIF por feature.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "VIF", "ui_order": 3},
    )
    max_iterations: int | None = Field(
        default=None,
        ge=1,
        title="Máximo de iteraciones",
        description="Límite opcional de rondas de eliminación por VIF; None itera hasta cumplir.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "VIF", "ui_order": 4},
    )


class StabilitySelectionConfig(NikodymBaseConfig):
    """Configuración del diagnóstico PSI/CSI por característica."""

    enabled: bool = Field(
        default=True,
        title="Calcular PSI/CSI por característica",
        description="Activa el diagnóstico de estabilidad por variable/bin contra Desarrollo.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Estabilidad",
            "ui_order": 1,
        },
    )
    action: Literal["report_only", "exclude"] = Field(
        default="report_only",
        title="Acción ante inestabilidad",
        description="'report_only' evita usar Holdout/OOT como criterio activo de inclusión.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Estabilidad",
            "ui_order": 2,
        },
    )
    stable_threshold: float = Field(
        default=0.10,
        ge=0.0,
        title="PSI/CSI estable hasta",
        description="Valor bajo el cual la característica se reporta como estable.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Estabilidad",
            "ui_order": 3,
        },
    )
    review_threshold: float = Field(
        default=0.25,
        ge=0.0,
        title="PSI/CSI revisar hasta",
        description="Valor bajo el cual la característica queda en banda de revisión.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Estabilidad",
            "ui_order": 4,
        },
    )
    smoothing: float = Field(
        default=1e-6,
        gt=0.0,
        title="Suavizado de proporciones",
        description="Suavizado positivo aplicado antes de ln(actual/expected) en PSI/CSI.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Estabilidad",
            "ui_order": 5,
        },
    )


class SelectionConfig(NikodymBaseConfig):
    """Sección ``selection`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-07 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección selection",
        description="== @register('standard', domain='selection') (D-CONV-2).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    feature_columns: tuple[str, ...] | Literal["*"] = Field(
        default="*",
        title="Variables candidatas",
        description="'*' = todas las variables seleccionadas por el proceso de binning.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 1},
    )
    exclude_columns: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Exclusiones técnicas",
        description="Columnas WoE o features a excluir antes de aplicar filtros de selección.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 2},
    )
    force_include: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Forzar inclusión",
        description=(
            "Variables que negocio exige conservar salvo que sean inexistentes o inválidas."
        ),
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 3},
    )
    force_exclude: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Forzar exclusión",
        description="Variables que negocio exige descartar siempre antes del modelo.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 4},
    )

    min_iv: float = Field(
        default=0.02,
        ge=0.0,
        title="IV mínimo",
        description="Umbral mínimo de Information Value final publicado por binning.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "IV", "ui_order": 1},
    )
    max_iv: float | None = Field(
        default=0.50,
        ge=0.0,
        title="IV sospechoso",
        description="Umbral de IV alto a flaggear o excluir; None desactiva esta regla.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "IV", "ui_order": 2},
    )
    max_iv_action: Literal["flag", "exclude"] = Field(
        default="flag",
        title="Acción ante IV alto",
        description="Acción ante IV superior a max_iv: marcar para revisión o excluir.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "IV", "ui_order": 3},
    )

    compute_univariate_metrics: bool = Field(
        default=True,
        title="Calcular AUC/KS/Gini univariado",
        description="Calcula métricas univariadas en Desarrollo usando score de riesgo -WoE.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Métricas univariadas",
            "ui_order": 1,
        },
    )
    min_auc: float | None = Field(
        default=None,
        ge=0.5,
        le=1.0,
        title="AUC mínimo",
        description="Filtro opcional por AUC univariado; None lo deja solo como diagnóstico.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Métricas univariadas",
            "ui_order": 2,
        },
    )
    min_ks: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        title="KS mínimo",
        description="Filtro opcional por KS univariado; None lo deja solo como diagnóstico.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Métricas univariadas",
            "ui_order": 3,
        },
    )
    min_gini: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        title="Gini mínimo",
        description="Filtro opcional por Gini univariado; None lo deja solo como diagnóstico.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Métricas univariadas",
            "ui_order": 4,
        },
    )

    priority_order: tuple[SelectionPriority, ...] = Field(
        default=("iv", "auc", "ks", "name"),
        title="Orden de prioridad para desempates",
        description="Ranking determinista para conservar variables ante correlación o VIF.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Ranking", "ui_order": 1},
    )
    correlation: CorrelationSelectionConfig = Field(
        default_factory=CorrelationSelectionConfig,
        title="Correlación",
        description="Parámetros del filtro por correlación entre columnas WoE.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Correlación", "ui_order": 1},
    )
    vif: VifSelectionConfig = Field(
        default_factory=VifSelectionConfig,
        title="VIF",
        description="Parámetros del filtro iterativo por multicolinealidad.",
        json_schema_extra={"ui_widget": "section", "ui_group": "VIF", "ui_order": 1},
    )
    stability: StabilitySelectionConfig = Field(
        default_factory=StabilitySelectionConfig,
        title="Estabilidad",
        description="Parámetros del diagnóstico PSI/CSI pre-modelo por característica.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Estabilidad", "ui_order": 1},
    )
    keep_structural_columns: bool = Field(
        default=True,
        title="Conservar columnas estructurales",
        description="Incluye columnas estructurales junto a las columnas WoE seleccionadas.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 1},
    )
    fail_if_no_features: bool = Field(
        default=True,
        title="Fallar si no queda ninguna variable",
        description="Si True, una selección vacía aborta en vez de publicar solo diagnóstico.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 2},
    )

    @model_validator(mode="after")
    def _check_force_overrides_disjuntos(self) -> Self:
        """Valida que una variable no esté simultáneamente forzada a incluir y excluir."""
        conflicto = sorted(set(self.force_include) & set(self.force_exclude))
        if conflicto:
            raise ConfigError(
                "force_include y force_exclude no pueden compartir variables; "
                f"conflicto={conflicto}."
            )
        return self
