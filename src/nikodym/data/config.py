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
**Estable (SemVer 1.x).**
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

    sep: str = Field(
        default=",",
        title="Separador",
        description="Delimitador de campos del CSV.",
        json_schema_extra={
            "ui_help": "Carácter que separa las columnas en el CSV de origen (coma, punto y "
            "coma, tabulador). Cámbialo si el archivo no viene separado por comas o la carga "
            "sale con columnas mal partidas.",
        },
    )
    decimal: str = Field(
        default=".",
        title="Separador decimal",
        description="Carácter del punto decimal.",
        json_schema_extra={
            "ui_help": "Símbolo que marca los decimales en los valores numéricos del CSV. "
            "Cámbialo a coma si el extracto viene en formato regional con coma decimal, o los "
            "números se leerán mal.",
        },
    )
    encoding: str = Field(
        default="utf-8",
        title="Codificación",
        description="Codificación de texto del fichero.",
        json_schema_extra={
            "ui_help": "Codificación de texto del archivo (utf-8 por defecto). Cámbiala si el "
            "CSV viene de un sistema legado y aparecen caracteres corruptos (tildes, ñ) al "
            "cargar.",
        },
    )


class LoadingConfig(NikodymBaseConfig):
    """Origen y formato del dataset crudo a cargar."""

    source: str | None = Field(
        default=None,
        title="Ruta del dataset",
        description="Ruta a CSV/Parquet/Excel; None si se inyecta un DataFrame en memoria por API.",
        json_schema_extra={
            "ui_help": "Ruta al archivo CSV, Parquet o Excel (.xlsx) que se va a cargar. Déjala "
            "vacía si el dataset se entrega directamente por código/API en vez de apuntar a un "
            "archivo.",
        },
    )
    file_format: Literal["auto", "csv", "parquet", "excel"] = Field(
        default="auto",
        title="Formato",
        description="'auto' infiere el formato por la extensión.",
        json_schema_extra={
            "ui_help": "Formato del archivo de origen. 'auto' lo infiere por la extensión "
            "(.csv/.parquet/.xlsx); fíjalo explícito si el archivo no trae una extensión estándar. "
            "Excel solo se admite con backend 'pandas'.",
        },
    )
    backend: Literal["pandas", "polars"] = Field(
        default="pandas",
        title="Backend de carga",
        description=(
            "Motor de lectura del archivo; 'polars' acelera datasets grandes y el resultado "
            "siempre se entrega como pandas."
        ),
        json_schema_extra={
            "ui_help": "Motor interno de lectura. 'pandas' es el estándar; 'polars' acelera la "
            "carga de datasets muy grandes, pero el resultado siempre se entrega como pandas.",
        },
    )
    csv_options: CsvOptions = Field(
        default_factory=CsvOptions,
        title="Opciones CSV",
        description="Parámetros de lectura del CSV.",
        json_schema_extra={
            "ui_help": "Parámetros de lectura específicos del CSV (separador, decimal, "
            "codificación). Solo aplica cuando el archivo de origen es CSV.",
        },
    )


# ── esquema ───────────────────────────────────────────────────────────────────
class ColumnSpec(NikodymBaseConfig):
    """Especificación declarativa de una columna esperada del dataset."""

    name: str = Field(
        ...,
        title="Nombre de columna",
        description="Identificador de la columna.",
        json_schema_extra={
            "ui_help": "Nombre exacto de la columna tal como aparece en el dataset (incluidas "
            "mayúsculas/minúsculas).",
        },
    )
    dtype: Literal["int", "float", "str", "bool", "category", "datetime"] = Field(
        ...,
        title="Tipo",
        description="Tipo de dato que debe tener la columna.",
        json_schema_extra={
            "ui_help": "Tipo de dato que debe tener la columna. La validación falla (o "
            "coerciona, si 'Coercionar tipo' está activo) cuando el dato real no calza.",
        },
    )
    nullable: bool = Field(
        default=True,
        title="Admite nulos",
        description="Si False, un nulo viola la validación.",
        json_schema_extra={
            "ui_help": "Permite valores vacíos/nulos en esta columna. Desactívalo para columnas "
            "obligatorias donde un nulo indica un problema de calidad de datos.",
        },
    )
    required: bool = Field(
        default=True,
        title="Obligatoria",
        description="Si False y ausente, se omite sin error ('strict' lo respeta).",
        json_schema_extra={
            "ui_help": "Exige que la columna exista en el dataset. Si la desactivas y la "
            "columna falta, se omite sin error.",
        },
    )
    coerce: bool = Field(
        default=False,
        title="Coercionar tipo",
        description="Convierte la columna al tipo declarado durante la validación.",
        json_schema_extra={
            "ui_help": "Convierte el dato al tipo declarado en vez de solo validarlo (p.ej. "
            "texto '10' a número). Útil si el origen no garantiza tipos limpios, pero puede "
            "esconder errores de formato si se abusa de ella.",
        },
    )
    ge: float | None = Field(
        default=None,
        title="Mínimo (>=)",
        description="Cota inferior inclusiva del valor.",
        json_schema_extra={
            "ui_help": "Valor mínimo permitido (inclusive). Déjalo vacío si la columna no tiene "
            "piso lógico.",
        },
    )
    le: float | None = Field(
        default=None,
        title="Máximo (<=)",
        description="Cota superior inclusiva del valor.",
        json_schema_extra={
            "ui_help": "Valor máximo permitido (inclusive). Déjalo vacío si la columna no tiene "
            "techo lógico.",
        },
    )
    isin: tuple[str, ...] | None = Field(
        default=None,
        title="Valores permitidos (categórico)",
        description="Conjunto cerrado de valores admitidos.",
        json_schema_extra={
            "ui_help": "Lista cerrada de valores admitidos para una columna categórica. "
            "Cualquier valor fuera de esta lista se marca como incumplimiento del esquema.",
        },
    )
    unique: bool = Field(
        default=False,
        title="Valores únicos",
        description="Exige unicidad de los valores de la columna.",
        json_schema_extra={
            "ui_help": "Exige que todos los valores de la columna sean distintos entre sí "
            "(p.ej. un identificador de cliente).",
        },
    )


class SchemaConfig(NikodymBaseConfig):
    """Esquema declarativo del dataset: columnas esperadas, estrictez e índice."""

    columns: tuple[ColumnSpec, ...] = Field(
        default_factory=tuple,
        title="Columnas esperadas",
        description="Especificación de cada columna del dataset.",
        json_schema_extra={
            "ui_help": "Catálogo de columnas que el motor espera encontrar en el dataset, con "
            "su tipo y reglas. Es la base de la validación de esquema antes de seguir el "
            "pipeline.",
        },
    )
    strict: Literal[True, False, "filter"] = Field(
        default=False,
        title="Estrictez de columnas",
        description="True: solo las declaradas; 'filter': descarta extras; False: permite extras.",
        json_schema_extra={
            "ui_help": "Qué hacer con columnas del dataset que no están en el catálogo: exigir "
            "que no existan (True), descartarlas en silencio ('filter'), o dejarlas pasar sin "
            "tocarlas (False).",
        },
    )
    ordered: bool = Field(
        default=False,
        title="Validar orden de columnas",
        description="Exige el orden declarado de columnas.",
        json_schema_extra={
            "ui_help": "Exige que las columnas aparezcan en el mismo orden en que se declararon "
            "aquí. Actívalo solo si el orden es relevante para tu proceso.",
        },
    )
    index_col: str | None = Field(
        default=None,
        title="Columna índice",
        description="Columna que actúa de identificador de observación (índice).",
        json_schema_extra={
            "ui_help": "Nombre del índice del DataFrame (no una columna normal) que identifica "
            "cada observación. Debe existir y ser único; si el identificador vive como columna "
            "común, decláralo en 'Columnas esperadas' o en 'Llave(s) de unicidad', no aquí.",
        },
    )
    unique_keys: tuple[str, ...] | None = Field(
        default=None,
        title="Llave(s) de unicidad de fila",
        description="Columnas cuya combinación debe ser única por fila.",
        json_schema_extra={
            "ui_help": "Columna o combinación de columnas que debe identificar de forma única "
            "cada fila (p.ej. cliente + fecha). Filas repetidas en esa combinación hacen fallar "
            "la validación.",
        },
    )


# ── target ────────────────────────────────────────────────────────────────────
class PerformanceWindow(NikodymBaseConfig):
    """Ventana de desempeño tras la fecha de observación (madurez del target)."""

    observation_date_col: str = Field(
        ...,
        title="Fecha de observación",
        description="Columna con la fecha de observación.",
        json_schema_extra={
            "ui_help": "Columna con la fecha en que se observa a cada cliente/operación (el "
            "punto de partida de la ventana de desempeño).",
        },
    )
    months: int = Field(
        default=12,
        ge=1,
        le=120,
        title="Meses de ventana de desempeño",
        description="Largo de la ventana.",
        json_schema_extra={
            "ui_help": "Cuántos meses deben pasar desde la fecha de observación para "
            "considerar 'madura' la ventana de desempeño (p.ej. 12 para el estándar de 12 "
            "meses).",
        },
    )
    data_cutoff_col: str | None = Field(
        default=None,
        title="Fecha de corte de datos",
        description="Si se da, una ventana no madurada se marca 'excluido' por ventana incompleta.",
        json_schema_extra={
            "ui_help": "Columna con la fecha de corte de los datos disponibles. Si la "
            "declaras, las observaciones cuya ventana aún no maduró a esa fecha se excluyen "
            "automáticamente como 'ventana incompleta' (nunca se asumen buenas).",
        },
    )


# ── mini-DSL declarativo de reglas (NO expresiones pandas libres; D-DATA-6) ────
class Predicate(NikodymBaseConfig):
    """Comparación atómica ``columna op valor`` evaluada por un parser propio con *allowlist*."""

    col: str = Field(
        ...,
        title="Columna sobre la que opera",
        description="Nombre de la columna del predicado.",
        json_schema_extra={
            "ui_help": "Columna del dataset sobre la que se evalúa esta condición.",
        },
    )
    op: Literal["==", "!=", "<", "<=", ">", ">=", "in", "notin", "isna", "notna"] = Field(
        ...,
        title="Operador (allowlist cerrada)",
        description="Único conjunto permitido. 'isna'/'notna' ignoran 'value'.",
        json_schema_extra={
            "ui_help": "Comparación a aplicar sobre la columna: igual/distinto, mayor/menor, "
            "pertenece/no pertenece a una lista, o es nulo/no nulo. 'isna'/'notna' ignoran el "
            "campo 'Valor de comparación'.",
        },
    )
    value: bool | int | float | str | tuple[bool | int | float | str, ...] | None = Field(
        default=None,
        title="Valor de comparación",
        description=(
            "Escalar para los comparadores; lista de valores para 'in'/'notin'; vacío para "
            "'isna'/'notna'. El valor conserva su tipo original (un `true` no se convierte en 1)."
        ),
        json_schema_extra={
            "ui_help": "Valor contra el que se compara la columna. Para 'pertenece'/'no "
            "pertenece' ingresa una lista de valores; para 'es nulo'/'no es nulo' déjalo vacío.",
        },
    )


class Rule(NikodymBaseConfig):
    """Combina condiciones con AND (``all_of``) y/o OR (``any_of``), en un único nivel."""

    all_of: tuple[Predicate, ...] = Field(
        default_factory=tuple,
        title="Predicados unidos por AND",
        description="Todos deben cumplirse.",
        json_schema_extra={
            "ui_help": "Condiciones que deben cumplirse TODAS a la vez (AND) para que la regla "
            "se active.",
        },
    )
    any_of: tuple[Predicate, ...] = Field(
        default_factory=tuple,
        title="Predicados unidos por OR",
        description="Al menos uno debe cumplirse.",
        json_schema_extra={
            "ui_help": "Condiciones de las que basta que se cumpla AL MENOS UNA (OR) para que "
            "la regla se active. Si combinas con 'Predicados unidos por AND', ambos grupos "
            "deben cumplirse.",
        },
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
        ...,
        title="Motivo de exclusión",
        description="Etiqueta del motivo (auditoría).",
        json_schema_extra={
            "ui_help": "Nombre del motivo de exclusión, tal como quedará registrado en el "
            "rastro de auditoría (debe ser único entre todas las exclusiones).",
        },
    )
    rule: Rule = Field(
        ...,
        title="Regla de exclusión",
        description="Predicados que marcan la fila como excluida.",
        json_schema_extra={
            "ui_help": "Condición que, al cumplirse, marca la observación como excluida del "
            "modelamiento (fuera de bueno/malo/indeterminado).",
        },
    )


class TargetConfig(NikodymBaseConfig):
    """Definición declarativa del target binario (bueno/malo/indeterminado/excluido)."""

    target_col: str = Field(
        default="target",
        title="Nombre de la columna target derivada",
        description="Columna 0/1 generada; vacía si la observación es indeterminada o excluida.",
        json_schema_extra={
            "ui_help": "Nombre de la columna 0/1 que el motor va a crear con el resultado del "
            "etiquetado (vacía si la observación es indeterminada o excluida).",
        },
    )
    bad_rule: Rule = Field(
        ...,
        title="Regla de 'malo'",
        description=(
            "Condición que marca la observación como 'malo' (target = 1), p. ej. "
            "all_of=[{col: dpd_12m, op: '>=', value: 90}]."
        ),
        json_schema_extra={
            "ui_help": "Condición que define cuándo una observación es 'malo' (p.ej. mora >= 90 "
            "días). Es la regla central del target: 1 = malo.",
        },
    )
    good_rule: Rule | None = Field(
        default=None,
        title="Regla de 'bueno'",
        description="Si None: bueno = NOT bad AND NOT indeterminate AND NOT excluded.",
        json_schema_extra={
            "ui_help": "Condición que define cuándo una observación es 'bueno'. Si la dejas "
            "vacía, se considera bueno todo lo que no sea malo, indeterminado ni excluido.",
        },
    )
    indeterminate_rule: Rule | None = Field(
        default=None,
        title="Regla de 'indeterminado' (zona gris)",
        description="Estas filas quedan con el target vacío y se excluyen del ajuste.",
        json_schema_extra={
            "ui_help": "Condición de zona gris: observaciones que no son claramente buenas ni "
            "malas y por eso se excluyen del ajuste del modelo (target queda vacío), aunque "
            "quedan trazadas como 'indeterminado'.",
        },
    )
    exclusion_rules: tuple[ExclusionRule, ...] = Field(
        default_factory=tuple,
        title="Exclusiones estructurales",
        description="Reglas de exclusión con motivo nombrado.",
        json_schema_extra={
            "ui_help": "Reglas adicionales que sacan observaciones del modelamiento por motivos "
            "estructurales (p.ej. fraude, cliente relacionado), cada una con un nombre propio "
            "para la auditoría.",
        },
    )
    window: PerformanceWindow | None = Field(
        default=None,
        title="Ventana de desempeño",
        description="Si se da, las observaciones sin ventana madurada se excluyen.",
        json_schema_extra={
            "ui_help": "Ventana de desempeño mínima que debe cumplir una observación antes de "
            "evaluarse. Si la dejas vacía, no se exige maduración temporal.",
        },
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
        json_schema_extra={
            "ui_help": "Columnas a las que aplica este catálogo de centinelas. '*' aplica a "
            "todas las columnas del dataset.",
        },
    )
    sentinels: tuple[float | str, ...] = Field(
        ...,
        title="Centinelas",
        description=(
            "Valores que significan ausencia/no-aplica; se normalizan a NaN conservando etiqueta."
        ),
        json_schema_extra={
            "ui_help": "Valores que en realidad significan 'sin dato' o 'no aplica' aunque no "
            "vengan vacíos (p.ej. -999, 'N/A'). Se convierten a nulo conservando su etiqueta "
            "para que binning les asigne un bin propio.",
        },
    )
    label: str = Field(
        ...,
        title="Etiqueta del special",
        description="Nombre del bin propio que binning asignará a estos valores.",
        json_schema_extra={
            "ui_help": "Nombre con el que este special value aparecerá como bin propio en el "
            "binning, en vez de mezclarse con los nulos comunes.",
        },
    )


class MissingConfig(NikodymBaseConfig):
    """Política de missing y special values del dataset."""

    special_values: tuple[SpecialValueSpec, ...] = Field(
        default_factory=tuple,
        title="Catálogo de special values",
        description="Centinelas a normalizar a NaN conservando su etiqueta.",
        json_schema_extra={
            "ui_help": "Catálogo de valores centinela (p.ej. -999, 'N/A') a normalizar a nulo "
            "antes de seguir el pipeline, conservando su etiqueta original.",
        },
    )
    max_missing_rate: float = Field(
        default=0.99,
        ge=0.0,
        le=1.0,
        title="Tasa máxima de missing por columna",
        description=(
            "Las columnas por sobre el umbral se reportan como decisión en el audit-trail; "
            "ninguna etapa las elimina automáticamente por este umbral."
        ),
        json_schema_extra={
            "ui_help": "Umbral de tasa de nulos por columna a partir del cual se reporta como "
            "decisión a revisar. No elimina la columna automáticamente; esa decisión la toma la "
            "selección de variables.",
        },
    )


# ── particiones (unión discriminada ANIDADA en data.partition.strategy) ────────
class TemporalSplitConfig(NikodymBaseConfig):
    """Partición temporal: OOT por fecha de corte; Dev/HO in-time."""

    type: Literal["temporal"] = Field(
        default="temporal",
        title="Tipo de estrategia",
        description="Identifica la estrategia como partición temporal.",
        json_schema_extra={
            "ui_help": "Identifica esta estrategia como partición temporal; normalmente lo fija "
            "el selector de la UI, no se edita a mano.",
        },
    )
    date_col: str = Field(
        ...,
        title="Columna de fecha para el corte OOT",
        description="Fecha que define el corte OOT.",
        json_schema_extra={
            "ui_help": "Columna de fecha que define el corte entre datos dentro y fuera de "
            "tiempo (OOT).",
        },
    )
    oot_from: str = Field(
        ...,
        title="Fecha inicio OOT (ISO 8601)",
        description="Filas con date_col >= oot_from van a OOT; el resto a Dev/HO.",
        json_schema_extra={
            "ui_help": "Fecha desde la cual las observaciones van al conjunto OOT (fuera de "
            "tiempo). Todo lo anterior queda disponible para Desarrollo/Holdout.",
        },
    )
    holdout_fraction: float = Field(
        default=0.2,
        ge=0.0,
        lt=1.0,
        title="Fracción Holdout dentro de in-time",
        description="Proporción reservada como Holdout del subconjunto in-time.",
        json_schema_extra={
            "ui_help": "Proporción del conjunto dentro de tiempo (no-OOT) que se reserva como "
            "Holdout; el resto queda en Desarrollo.",
        },
    )


class RandomSplitConfig(NikodymBaseConfig):
    """Partición aleatoria estable Dev/HO/OOT (pseudo-OOT) por fracciones que suman 1."""

    type: Literal["random"] = Field(
        default="random",
        title="Tipo de estrategia",
        description="Identifica la estrategia como partición aleatoria.",
        json_schema_extra={
            "ui_help": "Identifica esta estrategia como partición aleatoria; normalmente lo "
            "fija el selector de la UI, no se edita a mano.",
        },
    )
    dev_fraction: float = Field(
        default=0.7,
        gt=0.0,
        lt=1.0,
        title="Fracción Desarrollo",
        description="Proporción de la partición Dev.",
        json_schema_extra={
            "ui_help": "Proporción de observaciones que va al conjunto de Desarrollo (donde se "
            "ajusta el modelo).",
        },
    )
    holdout_fraction: float = Field(
        default=0.15,
        ge=0.0,
        lt=1.0,
        title="Fracción Holdout",
        description="Proporción de la partición HO.",
        json_schema_extra={
            "ui_help": "Proporción de observaciones que va al conjunto de Holdout (validación "
            "out-of-sample dentro de la misma muestra).",
        },
    )
    oot_fraction: float = Field(
        default=0.15,
        ge=0.0,
        lt=1.0,
        title="Fracción OOT (pseudo-OOT aleatorio)",
        description="Proporción reservada como OOT aleatorio.",
        json_schema_extra={
            "ui_help": "Proporción de observaciones que va al conjunto OOT aleatorio "
            "(pseudo fuera-de-tiempo, no un corte temporal real). Las tres fracciones deben "
            "sumar 1.0.",
        },
    )
    stratify_by: str | None = Field(
        default=None,
        title="Estratificar por columna",
        description="Columna por la que estratificar el sorteo (p.ej. target).",
        json_schema_extra={
            "ui_help": "Columna por la que estratificar el sorteo de particiones (típicamente "
            "el target), para mantener proporciones similares de malos en cada conjunto.",
        },
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
        description="Identifica la estrategia como partición por cohorte.",
        json_schema_extra={
            "ui_help": "Identifica esta estrategia como partición por cohorte; normalmente lo "
            "fija el selector de la UI, no se edita a mano.",
        },
    )
    cohort_col: str = Field(
        ...,
        title="Columna de cohorte",
        description="Columna de añada/vintage de cada observación.",
        json_schema_extra={
            "ui_help": "Columna que identifica la cohorte o añada (vintage) de cada observación "
            "(p.ej. mes de originación).",
        },
    )
    oot_cohorts: tuple[str, ...] = Field(
        ...,
        title="Cohortes reservadas como OOT",
        description="Valores de cohorte que forman el OOT.",
        json_schema_extra={
            "ui_help": "Cohortes que se reservan íntegramente como OOT. El resto de las "
            "cohortes se reparte entre Desarrollo y Holdout.",
        },
    )
    holdout_fraction: float = Field(
        default=0.2,
        ge=0.0,
        lt=1.0,
        title="Fracción Holdout dentro de in-cohort",
        description="Proporción reservada como Holdout del subconjunto in-cohort.",
        json_schema_extra={
            "ui_help": "Proporción de las cohortes que NO son OOT que se reserva como Holdout; "
            "el resto queda en Desarrollo.",
        },
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
        json_schema_extra={
            "ui_help": "Cómo se dividen los datos en Desarrollo/Holdout/OOT: por fecha de corte "
            "(temporal), por cohorte/vintage, o por sorteo aleatorio.",
        },
    )
    ttd_includes_excluded: bool = Field(
        default=True,
        title="TTD incluye indeterminados/excluidos",
        description=(
            "TTD = toda la población que pasó por la puerta (rol superpuesto a Dev/HO/OOT)."
        ),
        json_schema_extra={
            "ui_help": "Si se activa, el conjunto TTD (through-the-door, toda la población que "
            "pasó por la puerta) incluye también a los indeterminados/excluidos, no solo a los "
            "modelables.",
        },
    )
    min_bads_per_partition: int = Field(
        default=30,
        ge=0,
        title="Mínimo de malos por partición",
        description=(
            "Por debajo de este mínimo la corrida se detiene con error: la partición no es "
            "evaluable."
        ),
        json_schema_extra={
            "ui_help": "Mínimo de casos malos que debe tener cada partición para considerarse "
            "evaluable. Si alguna partición queda por debajo, el motor detiene el proceso en "
            "vez de entregar un conjunto poco confiable.",
        },
    )


# ── raíz del sub-config ────────────────────────────────────────────────────────
class DataConfig(NikodymBaseConfig):
    """Carga el dataset, valida su esquema, define el target y arma las particiones."""

    # ``populate_by_name=True`` (no lo trae la base) permite construir por nombre Python
    # (``DataConfig(schema_=...)``) además de por alias YAML (``schema:``); la serialización
    # canónica usa ``by_alias=True`` (clave ``schema`` en el ``config_hash``).
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección de datos",
        description="Variante de la sección de datos; hoy solo existe la estándar.",
        json_schema_extra={
            "ui_help": "Identificador fijo de esta sección como 'standard'; normalmente no se "
            "edita a mano.",
        },
    )
    load: LoadingConfig = Field(
        default_factory=LoadingConfig,
        title="Carga",
        description="Origen y formato del dataset.",
        json_schema_extra={
            "ui_help": "Configuración de origen y formato del dataset a cargar (ruta, tipo de "
            "archivo, opciones de CSV).",
        },
    )
    schema_: SchemaConfig = Field(
        default_factory=SchemaConfig,
        alias="schema",
        title="Esquema",
        description="Validación declarativa de columnas/tipos/rangos.",
        json_schema_extra={
            "ui_help": "Definición de las columnas esperadas, sus tipos y reglas de validación "
            "(esquema del dataset).",
        },
    )
    missing: MissingConfig = Field(
        default_factory=MissingConfig,
        title="Missing/special",
        description="Política de missing y catálogo de special values.",
        json_schema_extra={
            "ui_help": "Política de valores especiales y nulos: qué centinelas normalizar y a "
            "partir de qué tasa de missing avisar.",
        },
    )
    target: TargetConfig = Field(
        ...,
        title="Definición de target",
        description="Reglas declarativas de bueno/malo/excluido.",
        json_schema_extra={
            "ui_help": "Reglas que definen cómo se etiqueta cada observación como bueno, malo, "
            "indeterminado o excluido.",
        },
    )
    partition: PartitionConfig = Field(
        ...,
        title="Particiones",
        description="Estrategia de partición Dev/HO/OOT + rol TTD.",
        json_schema_extra={
            "ui_help": "Cómo se dividen las observaciones en Desarrollo, Holdout y OOT para "
            "entrenar y validar el modelo.",
        },
    )
