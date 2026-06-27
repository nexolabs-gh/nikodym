"""Sub-config declarativo de la capa ``data`` (SDD-02 §5).

:class:`DataConfig` es la sección ``data`` de :class:`~nikodym.core.config.NikodymConfig`: carga,
validación de esquema, definición de *target* (mini-DSL declarativo), política de missing/special
y particiones. Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig`
(``extra='forbid'``, ``frozen=True``); cada campo declara ``title``/``description`` y los numéricos
sus cotas (``ge``/``le``), de modo que la UI (SDD-23) sea un editor del mismo objeto.

La estrategia de partición es una **unión discriminada anidada** (``data.partition.strategy``)
resuelta por un **factory local** de ``data`` (``_SPLITTERS``, SDD-02 §7), **no** por el Registry
global de ``core``: D-CONV-2 (``type`` == key del Registry) aplica solo a uniones de **nivel
sección**, no a las anidadas (SDD-05 §3). El mini-DSL (:class:`Predicate`/:class:`Rule`) compone
máscaras booleanas vectorizadas con una *allowlist* cerrada de operadores; **nunca** evalúa código
(``DataFrame.eval``/``eval``), lo que elimina por construcción el vector de inyección (D-DATA-6).
**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import ConfigDict, Field, model_validator

from nikodym.core.config import NikodymBaseConfig

__all__ = [
    "EXCLUSION_WINDOW_REASON",
    "CohortSplitConfig",
    "ColumnSpec",
    "CsvOptions",
    "DataConfig",
    "ExclusionRule",
    "LoadingConfig",
    "MissingConfig",
    "PartitionConfig",
    "PartitionStrategy",
    "PerformanceWindow",
    "Predicate",
    "RandomSplitConfig",
    "Rule",
    "SchemaConfig",
    "SpecialValueSpec",
    "TargetConfig",
    "TemporalSplitConfig",
]

EXCLUSION_WINDOW_REASON: Final = "ventana_incompleta"


# ── carga ─────────────────────────────────────────────────────────────────────
class CsvOptions(NikodymBaseConfig):
    """Opciones de lectura de un CSV (separadores y codificación)."""

    sep: str = Field(default=",", title="Separador", description="Delimitador de campos del CSV.")
    decimal: str = Field(
        default=".", title="Separador decimal", description="Carácter del punto decimal."
    )
    encoding: str = Field(
        default="utf-8", title="Codificación", description="Codificación de texto del fichero."
    )


class LoadingConfig(NikodymBaseConfig):
    """Origen y formato del dataset crudo a cargar."""

    source: str | None = Field(
        default=None,
        title="Ruta del dataset",
        description="Ruta a CSV/Parquet; None si se inyecta un DataFrame en memoria por API.",
    )
    file_format: Literal["auto", "csv", "parquet"] = Field(
        default="auto", title="Formato", description="'auto' infiere el formato por la extensión."
    )
    backend: Literal["pandas", "polars"] = Field(
        default="pandas",
        title="Backend de carga",
        description="polars opcional para grandes volúmenes (D-DATA-1); la API expone pandas.",
    )
    csv_options: CsvOptions = Field(
        default_factory=CsvOptions,
        title="Opciones CSV",
        description="Parámetros de lectura del CSV.",
    )


# ── esquema ───────────────────────────────────────────────────────────────────
class ColumnSpec(NikodymBaseConfig):
    """Especificación declarativa de una columna esperada del dataset."""

    name: str = Field(..., title="Nombre de columna", description="Identificador de la columna.")
    dtype: Literal["int", "float", "str", "bool", "category", "datetime"] = Field(
        ..., title="Tipo", description="Tipo lógico esperado (se traduce a un dtype de pandera)."
    )
    nullable: bool = Field(
        default=True, title="Admite nulos", description="Si False, un nulo viola la validación."
    )
    required: bool = Field(
        default=True,
        title="Obligatoria",
        description="Si False y ausente, se omite sin error ('strict' lo respeta).",
    )
    coerce: bool = Field(
        default=False,
        title="Coercionar tipo",
        description="Castea al dtype declarado durante la validación (pandera coerce).",
    )
    ge: float | None = Field(
        default=None, title="Mínimo (>=)", description="Cota inferior inclusiva del valor."
    )
    le: float | None = Field(
        default=None, title="Máximo (<=)", description="Cota superior inclusiva del valor."
    )
    isin: tuple[str, ...] | None = Field(
        default=None,
        title="Valores permitidos (categórico)",
        description="Conjunto cerrado de valores admitidos.",
    )
    unique: bool = Field(
        default=False,
        title="Valores únicos",
        description="Exige unicidad de los valores de la columna.",
    )


class SchemaConfig(NikodymBaseConfig):
    """Esquema declarativo del dataset: columnas esperadas, estrictez e índice."""

    columns: tuple[ColumnSpec, ...] = Field(
        default_factory=tuple,
        title="Columnas esperadas",
        description="Especificación de cada columna del dataset.",
    )
    strict: Literal[True, False, "filter"] = Field(
        default=False,
        title="Estrictez de columnas",
        description="True: solo las declaradas; 'filter': descarta extras; False: permite extras.",
    )
    ordered: bool = Field(
        default=False,
        title="Validar orden de columnas",
        description="Exige el orden declarado de columnas.",
    )
    index_col: str | None = Field(
        default=None,
        title="Columna índice",
        description="Columna que actúa de identificador de observación (índice).",
    )
    unique_keys: tuple[str, ...] | None = Field(
        default=None,
        title="Llave(s) de unicidad de fila",
        description="Columnas cuya combinación debe ser única por fila.",
    )


# ── target ────────────────────────────────────────────────────────────────────
class PerformanceWindow(NikodymBaseConfig):
    """Ventana de desempeño tras la fecha de observación (madurez del target)."""

    observation_date_col: str = Field(
        ..., title="Fecha de observación", description="Columna con la fecha de observación."
    )
    months: int = Field(
        default=12,
        ge=1,
        le=120,
        title="Meses de ventana de desempeño",
        description="Largo de la ventana.",
    )
    data_cutoff_col: str | None = Field(
        default=None,
        title="Fecha de corte de datos",
        description="Si se da, una ventana no madurada se marca 'excluido' por ventana incompleta.",
    )


# ── mini-DSL declarativo de reglas (NO expresiones pandas libres; D-DATA-6) ────
class Predicate(NikodymBaseConfig):
    """Comparación atómica ``columna op valor`` evaluada por un parser propio con *allowlist*."""

    col: str = Field(
        ..., title="Columna sobre la que opera", description="Nombre de la columna del predicado."
    )
    op: Literal["==", "!=", "<", "<=", ">", ">=", "in", "notin", "isna", "notna"] = Field(
        ...,
        title="Operador (allowlist cerrada)",
        description="Único conjunto permitido. 'isna'/'notna' ignoran 'value'.",
    )
    value: bool | int | float | str | tuple[bool | int | float | str, ...] | None = Field(
        default=None,
        title="Valor de comparación",
        description=(
            "Escalar para comparadores; tupla para 'in'/'notin'; None para 'isna'/'notna'. El "
            "modo de unión smart de Pydantic + el orden bool->int->float (lo más específico "
            "primero) evita la coerción (un `true` no se vuelve 1) y conserva list->tuple en el "
            "round-trip. (SDD-02 §5 pedía strict=True; Pydantic 2.13 no lo aplica a una unión.)"
        ),
    )


class Rule(NikodymBaseConfig):
    """Conjunción/disyunción de predicados (un nivel); se evalúa vectorizada, sin ``eval``."""

    all_of: tuple[Predicate, ...] = Field(
        default_factory=tuple,
        title="Predicados unidos por AND",
        description="Todos deben cumplirse.",
    )
    any_of: tuple[Predicate, ...] = Field(
        default_factory=tuple,
        title="Predicados unidos por OR",
        description="Al menos uno debe cumplirse.",
    )

    @model_validator(mode="after")
    def _regla_no_vacia(self) -> Rule:
        """Exige al menos un predicado: una regla vacía no tiene semántica (ConfigError)."""
        if not self.all_of and not self.any_of:
            raise ValueError("una Rule debe declarar al menos un predicado en 'all_of' o 'any_of'.")
        return self


class ExclusionRule(NikodymBaseConfig):
    """Regla de exclusión estructural con motivo nombrado (se registra en el audit-trail)."""

    name: str = Field(
        ..., title="Motivo de exclusión", description="Etiqueta del motivo (auditoría)."
    )
    rule: Rule = Field(
        ..., title="Regla de exclusión", description="Predicados que marcan la fila como excluida."
    )


class TargetConfig(NikodymBaseConfig):
    """Definición declarativa del target binario (bueno/malo/indeterminado/excluido)."""

    target_col: str = Field(
        default="target",
        title="Nombre de la columna target derivada",
        description="Columna 0/1 (NA si indeterminado/excluido) que produce la capa.",
    )
    bad_rule: Rule = Field(
        ...,
        title="Regla de 'malo'",
        description=(
            "Mini-DSL columna/op/valor, p.ej. all_of=[{col:dpd_12m, op:'>=', value:90}]. malo=1."
        ),
    )
    good_rule: Rule | None = Field(
        default=None,
        title="Regla de 'bueno'",
        description="Si None: bueno = NOT bad AND NOT indeterminate AND NOT excluded.",
    )
    indeterminate_rule: Rule | None = Field(
        default=None,
        title="Regla de 'indeterminado' (zona gris)",
        description="Mini-DSL; estas filas se excluyen del ajuste (target NA).",
    )
    exclusion_rules: tuple[ExclusionRule, ...] = Field(
        default_factory=tuple,
        title="Exclusiones estructurales",
        description="Reglas de exclusión con motivo nombrado.",
    )
    window: PerformanceWindow | None = Field(
        default=None,
        title="Ventana de desempeño",
        description="Si se da, las observaciones sin ventana madurada se excluyen.",
    )

    @model_validator(mode="after")
    def _exclusion_reasons_unicos_y_no_reservados(self) -> TargetConfig:
        """Rechaza duplicados en orden de declaración y colisiones con razones reservadas."""
        seen: set[str] = set()
        for exclusion in self.exclusion_rules:
            reason = exclusion.name
            if reason == EXCLUSION_WINDOW_REASON:
                raise ValueError(
                    "el motivo de exclusión 'ventana_incompleta' está reservado para la "
                    "ventana de desempeño incompleta; use otro ExclusionRule.name."
                )
            if reason in seen:
                raise ValueError(
                    f"motivo de exclusión duplicado: '{reason}'. Cada ExclusionRule.name debe "
                    "ser único para preservar la trazabilidad regulatoria."
                )
            seen.add(reason)
        return self


# ── missing / special values ──────────────────────────────────────────────────
class SpecialValueSpec(NikodymBaseConfig):
    """Catálogo de centinelas de una o varias columnas (special values)."""

    columns: tuple[str, ...] | Literal["*"] = Field(
        default="*",
        title="Columnas afectadas",
        description="'*' aplica a todas las columnas; o una tupla de nombres.",
    )
    sentinels: tuple[float | str, ...] = Field(
        ...,
        title="Centinelas",
        description=(
            "Valores que significan ausencia/no-aplica; se normalizan a NaN conservando etiqueta."
        ),
    )
    label: str = Field(
        ..., title="Etiqueta del special", description="Nombre del bin que usará binning (SDD-06)."
    )


class MissingConfig(NikodymBaseConfig):
    """Política de missing y special values del dataset."""

    special_values: tuple[SpecialValueSpec, ...] = Field(
        default_factory=tuple,
        title="Catálogo de special values",
        description="Centinelas a normalizar a NaN conservando su etiqueta.",
    )
    max_missing_rate: float = Field(
        default=0.99,
        ge=0.0,
        le=1.0,
        title="Tasa máxima de missing por columna",
        description=(
            "Columnas sobre el umbral se reportan como decisión (las elimina selection, no data)."
        ),
    )


# ── particiones (unión discriminada ANIDADA en data.partition.strategy) ────────
class TemporalSplitConfig(NikodymBaseConfig):
    """Partición temporal: OOT por fecha de corte; Dev/HO in-time."""

    type: Literal["temporal"] = Field(
        default="temporal",
        title="Tipo de estrategia",
        description="Discriminador del factory local _SPLITTERS.",
    )
    date_col: str = Field(
        ...,
        title="Columna de fecha para el corte OOT",
        description="Fecha que define el corte OOT.",
    )
    oot_from: str = Field(
        ...,
        title="Fecha inicio OOT (ISO 8601)",
        description="Filas con date_col >= oot_from van a OOT; el resto a Dev/HO.",
    )
    holdout_fraction: float = Field(
        default=0.2,
        ge=0.0,
        lt=1.0,
        title="Fracción Holdout dentro de in-time",
        description="Proporción reservada como Holdout del subconjunto in-time.",
    )


class RandomSplitConfig(NikodymBaseConfig):
    """Partición aleatoria estable Dev/HO/OOT (pseudo-OOT) por fracciones que suman 1."""

    type: Literal["random"] = Field(
        default="random",
        title="Tipo de estrategia",
        description="Discriminador del factory local _SPLITTERS.",
    )
    dev_fraction: float = Field(
        default=0.7,
        gt=0.0,
        lt=1.0,
        title="Fracción Desarrollo",
        description="Proporción de la partición Dev.",
    )
    holdout_fraction: float = Field(
        default=0.15,
        ge=0.0,
        lt=1.0,
        title="Fracción Holdout",
        description="Proporción de la partición HO.",
    )
    oot_fraction: float = Field(
        default=0.15,
        ge=0.0,
        lt=1.0,
        title="Fracción OOT (pseudo-OOT aleatorio)",
        description="Proporción reservada como OOT aleatorio.",
    )
    stratify_by: str | None = Field(
        default=None,
        title="Estratificar por columna",
        description="Columna por la que estratificar el sorteo (p.ej. target).",
    )

    @model_validator(mode="after")
    def _fracciones_suman_uno(self) -> RandomSplitConfig:
        """dev+holdout+oot debe sumar 1.0 (con tolerancia float); si no, ConfigError."""
        total = self.dev_fraction + self.holdout_fraction + self.oot_fraction
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"dev+holdout+oot debe sumar 1.0; suma observada = {total:.4f}.")
        return self


class CohortSplitConfig(NikodymBaseConfig):
    """Partición por cohorte (vintage): OOT = cohortes reservadas; Dev/HO in-cohort."""

    type: Literal["cohort"] = Field(
        default="cohort",
        title="Tipo de estrategia",
        description="Discriminador del factory local _SPLITTERS.",
    )
    cohort_col: str = Field(
        ..., title="Columna de cohorte", description="Columna de añada/vintage de cada observación."
    )
    oot_cohorts: tuple[str, ...] = Field(
        ...,
        title="Cohortes reservadas como OOT",
        description="Valores de cohorte que forman el OOT.",
    )
    holdout_fraction: float = Field(
        default=0.2,
        ge=0.0,
        lt=1.0,
        title="Fracción Holdout dentro de in-cohort",
        description="Proporción reservada como Holdout del subconjunto in-cohort.",
    )


PartitionStrategy = Annotated[
    TemporalSplitConfig | RandomSplitConfig | CohortSplitConfig,
    Field(discriminator="type"),
]
"""Unión discriminada anidada de la estrategia de partición (resuelta por ``_SPLITTERS``)."""


class PartitionConfig(NikodymBaseConfig):
    """Configuración de particiones: estrategia, rol TTD y piso de malos."""

    strategy: PartitionStrategy = Field(
        ...,
        title="Estrategia de partición",
        description="Una de temporal/random/cohort (por 'type').",
    )
    ttd_includes_excluded: bool = Field(
        default=True,
        title="TTD incluye indeterminados/excluidos",
        description=(
            "TTD = toda la población que pasó por la puerta (rol superpuesto a Dev/HO/OOT)."
        ),
    )
    min_bads_per_partition: int = Field(
        default=30,
        ge=0,
        title="Mínimo de malos por partición",
        description="Por debajo se emite DataValidationError (partición no evaluable).",
    )


# ── raíz del sub-config ────────────────────────────────────────────────────────
class DataConfig(NikodymBaseConfig):
    """Sección ``data`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-02 §5).

    Añade ``populate_by_name=True`` (no lo trae la base) para construir por nombre Python
    (``DataConfig(schema_=...)``) además de por alias YAML (``schema:``); la serialización
    canónica usa ``by_alias=True`` (clave ``schema`` en el ``config_hash``).
    """

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección de datos",
        description="== @register('standard', domain='data') (D-CONV-2).",
    )
    load: LoadingConfig = Field(
        default_factory=LoadingConfig, title="Carga", description="Origen y formato del dataset."
    )
    schema_: SchemaConfig = Field(
        default_factory=SchemaConfig,
        alias="schema",
        title="Esquema",
        description="Validación declarativa de columnas/tipos/rangos.",
    )
    missing: MissingConfig = Field(
        default_factory=MissingConfig,
        title="Missing/special",
        description="Política de missing y catálogo de special values.",
    )
    target: TargetConfig = Field(
        ..., title="Definición de target", description="Reglas declarativas de bueno/malo/excluido."
    )
    partition: PartitionConfig = Field(
        ..., title="Particiones", description="Estrategia de partición Dev/HO/OOT + rol TTD."
    )
