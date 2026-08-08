"""Config declarativo de la capa ``markov`` (SDD-19 §5).

:class:`MarkovConfig` es la sección ``markov`` de
:class:`~nikodym.core.config.NikodymConfig`: estima matrices de transición discretas, generadores
continuos y term-structures de PD lifetime desde paneles de migración. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from itertools import pairwise
from math import isfinite
from typing import Any, Final, Literal, Self

from pydantic import Field, field_validator, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.markov.exceptions import MarkovConfigError

MarkovMethod = Literal["cohort", "duration"]
EmbeddingPolicy = Literal["diagnose", "regularize", "forbid"]
ProjectionMode = Literal["homogeneous", "period_matrices", "aalen_johansen"]

__all__ = [
    "EmbeddingPolicy",
    "MarkovConfig",
    "MarkovDynamicsConfig",
    "MarkovEstimationConfig",
    "MarkovInputConfig",
    "MarkovMethod",
    "MarkovStateConfig",
    "MarkovValidationConfig",
    "ProjectionMode",
]

#: Prefijo del ``loc`` de los errores de esta sección (D-EXI-5). Vive en UN solo sitio para que un
#: renombrado de la sección no haya que perseguirlo por cada ``raise``: la ruta que el error declara
#: es **absoluta desde la raíz del config** —el ``except`` que la traduce vive en el endpoint y
#: atrapa la validación del ``NikodymConfig`` entero, así que ahí ya no se sabe qué sección la
#: emitió—, y eso ata al dominio con el nombre de su campo en la raíz.
_LOC_SECCION: tuple[str, ...] = ("markov",)

_INPUT_COLUMN_FIELDS: tuple[str, ...] = (
    "id_col",
    "time_col",
    "state_col",
    "segment_col",
    "partition_col",
    "weight_col",
    "exposure_time_col",
    "transition_time_col",
)
_REQUIRED_INPUT_COLUMNS: tuple[str, ...] = ("id_col", "time_col", "state_col")


class MarkovInputConfig(NikodymBaseConfig):
    """Configuración de columnas de entrada para paneles de migración Markov."""

    id_col: str = Field(
        default=...,
        title="Identificador de entidad",
        description="Columna con identificador estable de entidad, cuenta o cliente.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 1},
    )
    time_col: str = Field(
        default=...,
        title="Período o timestamp de observación",
        description="Columna con período discreto o timestamp ordenable de observación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 2},
    )
    state_col: str = Field(
        default=...,
        title="Estado/rating observado",
        description="Columna con estado, rating o bucket observado en cada período.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 3},
    )
    segment_col: str | None = Field(
        default=None,
        title="Segmento/pool opcional",
        description="Columna opcional de segmento o pool para matrices separadas.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 4},
    )
    partition_col: str | None = Field(
        default="partition",
        title="Partición si existe",
        description="Columna opcional de partición para filtrar dev/holdout/oot.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 5},
    )
    weight_col: str | None = Field(
        default=None,
        title="Peso opcional de transición",
        description="Columna opcional de pesos si la estimación usa conteos ponderados.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 6},
    )
    exposure_time_col: str | None = Field(
        default=None,
        title="Tiempo en riesgo para duration",
        description="Columna opcional con tiempo en riesgo usado por method='duration'.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 7},
    )
    transition_time_col: str | None = Field(
        default=None,
        title="Tiempo exacto de transición",
        description="Columna opcional con tiempo exacto de evento para Aalen-Johansen.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrada", "ui_order": 8},
    )

    @model_validator(mode="before")
    @classmethod
    def _check_requeridos_raw(cls, data: Any) -> Any:
        """Valida temprano las columnas requeridas para levantar ``MarkovConfigError``."""
        if not isinstance(data, dict):
            return data
        missing = [field for field in _REQUIRED_INPUT_COLUMNS if field not in data]
        if missing:
            # Sin `loc` a propósito (D-EXI-5): `missing` es un CONJUNTO —las tres columnas pueden
            # faltar a la vez— y no hay un campo único que corregir. Vacío significa eso, no un
            # olvido; anclar en el primero mandaría al usuario a uno de los tres huecos.
            raise MarkovConfigError(f"Las columnas requeridas de input faltan: {missing}.")
        return data

    @model_validator(mode="after")
    def _check_columnas_input(self) -> Self:
        """Valida columnas no vacías y claves de identidad distintas."""
        _require_non_empty_strings(_column_values(self, _INPUT_COLUMN_FIELDS), context="input")
        required_values = [self.id_col.strip(), self.time_col.strip(), self.state_col.strip()]
        if len(set(required_values)) != len(required_values):
            # Sin `loc` a propósito (D-EXI-5): es una invariante ENTRE tres campos y cualquiera de
            # los dos que colisionan sirve para deshacerla, así que no hay culpable único.
            raise MarkovConfigError("id_col, time_col y state_col deben ser columnas distintas.")
        return self


class MarkovStateConfig(NikodymBaseConfig):
    """Configuración de estados canónicos y estados absorbentes Markov."""

    states: tuple[str, ...] = Field(
        default=...,
        min_length=2,
        title="Estados en orden canónico",
        description="Estados o ratings válidos, en el orden que define matrices y salidas.",
        json_schema_extra={"ui_widget": "text_list", "ui_group": "Estados", "ui_order": 1},
    )
    default_state: str = Field(
        default="default",
        title="Estado absorbente default",
        description="Estado que representa default y alimenta PD acumulada/marginal.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Estados", "ui_order": 2},
    )
    absorbing_states: tuple[str, ...] = Field(
        default=("default",),
        title="Estados absorbentes",
        description="Estados absorbentes; deben ser subconjunto de states e incluir default.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Estados", "ui_order": 3},
    )
    allow_unknown_states: bool = Field(
        default=False,
        title="Permitir estados fuera de catálogo",
        description="Si es False, estados no declarados fallan como error de input.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Estados", "ui_order": 4},
    )

    @model_validator(mode="after")
    def _check_estados(self) -> Self:
        """Valida unicidad, default y absorbentes de SDD-19 §5."""
        _require_non_empty_strings(
            {
                "default_state": self.default_state,
                **{f"states[{i}]": state for i, state in enumerate(self.states)},
            },
            context="states",
        )
        _require_non_empty_strings(
            {f"absorbing_states[{i}]": s for i, s in enumerate(self.absorbing_states)},
            context="absorbing_states",
        )
        if len(set(self.states)) != len(self.states):
            raise MarkovConfigError(
                "states no puede contener duplicados.",
                # D-EXI-5: el error se ANCLA a su campo, para que el formulario pueda llevar ahí al
                # usuario en vez de dejarle un mensaje sin control. La ruta va absoluta desde la
                # raíz del config, y un gate exige que resuelva contra `NikodymConfig`.
                loc=(*_LOC_SECCION, "states", "states"),
            )
        if self.default_state not in self.states:
            # El catálogo `states` es la autoridad —es el campo requerido, sin default de fábrica— y
            # `default_state` lo REFERENCIA con un placeholder ('default') que un panel real casi
            # siempre tiene que reapuntar. Por eso el ancla es el que referencia, no el catálogo.
            raise MarkovConfigError(
                "states debe contener default_state.",
                loc=(*_LOC_SECCION, "states", "default_state"),  # D-EXI-5
            )
        absorbing = set(self.absorbing_states)
        unknown_absorbing = sorted(absorbing - set(self.states))
        if unknown_absorbing:
            raise MarkovConfigError(
                f"absorbing_states debe ser subconjunto de states: {unknown_absorbing}.",
                loc=(*_LOC_SECCION, "states", "absorbing_states"),  # D-EXI-5
            )
        if self.default_state not in absorbing:
            # Aquí las dos comprobaciones anteriores ya pasaron: `default_state` está en `states` y
            # `absorbing_states` es subconjunto suyo. Lo único inconsistente que queda es que la
            # lista de absorbentes omita el estado default, así que el campo a corregir es ésa.
            raise MarkovConfigError(
                "absorbing_states debe contener default_state.",
                loc=(*_LOC_SECCION, "states", "absorbing_states"),  # D-EXI-5
            )
        return self


class MarkovEstimationConfig(NikodymBaseConfig):
    """Método, intervalo temporal y mínimos de conteo con que se estiman las transiciones."""

    method: MarkovMethod = Field(
        default="cohort",
        title="Método de estimación",
        description="Método para estimar la dinámica: cohort discreto o duration continuo.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Estimación", "ui_order": 1},
    )
    interval: float = Field(
        default=1.0,
        gt=0.0,
        title="Longitud del intervalo base",
        description="Longitud del intervalo temporal base (Δt) entre observaciones sucesivas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Estimación", "ui_order": 2},
    )
    use_weights: bool = Field(
        default=False,
        title="Usar weight_col si existe",
        description="Si es True, la estimación usa la columna declarada en input.weight_col.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Estimación", "ui_order": 3},
    )
    min_origin_count: int = Field(
        default=1,
        ge=1,
        title="Mínimo de salidas por estado no absorbente",
        description="Mínimo de observaciones origen para aceptar una fila no absorbente.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Estimación", "ui_order": 4},
    )

    @field_validator("interval", mode="before")
    @classmethod
    def _check_interval_finito(cls, value: Any) -> Any:
        """Rechaza intervalos no finitos antes de aplicar rangos Pydantic."""
        if _is_non_finite_number(value):
            raise MarkovConfigError(
                "estimation.interval debe ser un número finito.",
                loc=(*_LOC_SECCION, "estimation", "interval"),  # D-EXI-5
            )
        return value


class MarkovDynamicsConfig(NikodymBaseConfig):
    """Proyecta las matrices de transición a cada horizonte pedido.

    El estimador Aalen-Johansen se aplica solo cuando `projection_mode` vale `aalen_johansen`.
    """

    projection_mode: ProjectionMode = Field(
        default="homogeneous",
        title="Modo de proyección",
        description="Modo de proyección: homogéneo, matrices por período o Aalen-Johansen.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Dinámica", "ui_order": 1},
    )
    time_unit: str = Field(
        default="period",
        title="Unidad temporal declarada",
        description=(
            "Unidad de los intervalos, horizontes y tiempos de evaluación; por ejemplo "
            "'month' o 'year'."
        ),
        json_schema_extra={
            "ui_help": (
                "Unidad en que están expresados los intervalos, horizontes y tiempos de "
                "evaluación: 'year', 'month', 'quarter', 'semester', 'week' o 'day' (también "
                "en español). Viaja con la curva y el motor IFRS 9 la usa para descontar la "
                "pérdida esperada, así que declararla mal —o dejarla en el valor por defecto "
                "'period', que nombra un índice y no una duración— cambia la provisión. Si no "
                "la declara, IFRS 9 asume años y lo deja anotado en el resultado."
            ),
            "ui_widget": "text_input",
            "ui_group": "Dinámica",
            "ui_order": 2,
        },
    )
    horizon_periods: tuple[int, ...] = Field(
        default=(1, 2, 3, 4, 5),
        title="Horizontes discretos",
        description="Horizontes discretos positivos y estrictamente crecientes.",
        json_schema_extra={"ui_widget": "number_list", "ui_group": "Dinámica", "ui_order": 3},
    )
    evaluation_times: tuple[float, ...] = Field(
        default=(),
        title="Horizontes continuos",
        description="Tiempos continuos positivos y estrictamente crecientes.",
        json_schema_extra={"ui_widget": "number_list", "ui_group": "Dinámica", "ui_order": 4},
    )
    embedding_policy: EmbeddingPolicy = Field(
        default="diagnose",
        title="Política de embedding",
        description="Política ante embedding inválido: diagnosticar, regularizar o fallar.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Dinámica", "ui_order": 5},
    )

    @model_validator(mode="after")
    def _check_horizontes(self) -> Self:
        """Valida unidad temporal y horizontes crecientes de SDD-19 §5."""
        _require_non_empty_strings({"time_unit": self.time_unit}, context="dynamics")
        _require_strictly_increasing(self.horizon_periods, name="horizon_periods")
        _require_strictly_increasing(self.evaluation_times, name="evaluation_times")
        return self


class MarkovValidationConfig(NikodymBaseConfig):
    """Configuración de tolerancias numéricas de validación Markov."""

    stochastic_tol: float = Field(
        default=1e-10,
        gt=0.0,
        lt=1e-3,
        title="Tolerancia estocástica",
        description="Tolerancia para cierre de filas y valores dentro de [0, 1].",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 1},
    )
    generator_tol: float = Field(
        default=1e-10,
        gt=0.0,
        lt=1e-3,
        title="Tolerancia de generador",
        description="Tolerancia para filas conservativas y restricciones de generador.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 2},
    )
    imaginary_tol: float = Field(
        default=1e-10,
        gt=0.0,
        lt=1e-3,
        title="Tolerancia imaginaria",
        description="Tolerancia para partes imaginarias residuales en logm/expm.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 3},
    )
    normalize_within_tolerance: bool = Field(
        default=True,
        title="Normalizar dentro de tolerancia",
        description="Si es True, corrige residuos numéricos dentro de tolerancia y audita.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Validación", "ui_order": 4},
    )


#: El límite que `period_matrices` declara, en UN solo sitio. Lo levantan las dos superficies —el
#: validador del config (para quien llega por YAML o por código) y el paso (defensa en profundidad,
#: por si alguien construye el config sin validar)—, y dos redacciones del mismo límite le harían
#: creer al usuario que son dos cosas distintas.
_PERIOD_MATRICES_UNSUPPORTED: Final = (
    "projection_mode='period_matrices' no soportado aún: requiere estimación de matrices por "
    "período no homogéneas, no disponible en B19.x; use projection_mode='homogeneous' o "
    "projection_mode='aalen_johansen'."
)


class MarkovConfig(NikodymBaseConfig):
    """Estima matrices de transición y la curva de PD lifetime desde un panel de migraciones."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema markov",
        description="Versión local del schema de Markov para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección markov",
        description="Variante de la sección de Markov; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    input: MarkovInputConfig = Field(
        default_factory=lambda: MarkovInputConfig(id_col="id", time_col="time", state_col="state"),
        title="Entrada",
        description="Columnas de id, tiempo, estado, pesos y tiempos de evento.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Entrada", "ui_order": 1},
    )
    states: MarkovStateConfig = Field(
        default_factory=lambda: MarkovStateConfig(states=("performing", "default")),
        title="Estados",
        description="Catálogo canónico de estados, default y absorbentes.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Estados", "ui_order": 1},
    )
    estimation: MarkovEstimationConfig = Field(
        default_factory=MarkovEstimationConfig,
        title="Estimación",
        description="Método, intervalo, pesos y mínimo de observaciones origen.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Estimación", "ui_order": 1},
    )
    dynamics: MarkovDynamicsConfig = Field(
        default_factory=MarkovDynamicsConfig,
        title="Dinámica",
        description="Modo de proyección, horizontes y política de embedding.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Dinámica", "ui_order": 1},
    )
    validation: MarkovValidationConfig = Field(
        default_factory=MarkovValidationConfig,
        title="Validación",
        description="Tolerancias numéricas de cierre estocástico y generador.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Validación", "ui_order": 1},
    )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida invariantes cruzados de SDD-19 §5."""
        # D-EXI-5: en «X exige Y» el ancla es Y —lo que falta y hay que escribir—, no X. Mismo
        # criterio que el precedente «lgd.method='workout' exige recovery_col».
        if self.estimation.method == "duration" and self.input.exposure_time_col is None:
            raise MarkovConfigError(
                "method='duration' exige input.exposure_time_col.",
                loc=(*_LOC_SECCION, "input", "exposure_time_col"),
            )
        if (
            self.dynamics.projection_mode == "aalen_johansen"
            and self.input.transition_time_col is None
        ):
            raise MarkovConfigError(
                "projection_mode='aalen_johansen' exige input.transition_time_col.",
                loc=(*_LOC_SECCION, "input", "transition_time_col"),
            )
        if self.estimation.use_weights and self.input.weight_col is None:
            raise MarkovConfigError(
                "use_weights=True exige input.weight_col.",
                loc=(*_LOC_SECCION, "input", "weight_col"),
            )
        # 🔴 El config ACEPTABA una opción que el motor rechaza al proyectar (`markov/step.py`), así
        # que la corrida moría a mitad con el trabajo de estimación ya pagado. Es el caso más claro
        # de D-ABA-5: una opción no implementada se declara en el catálogo **y** la impide el
        # validador, porque quien usa esto como librería —por YAML o por código— nunca ve el
        # catálogo. El texto es el MISMO literal del motor: dos redacciones del mismo límite le
        # harían creer al usuario que son dos cosas distintas.
        if self.dynamics.projection_mode == "period_matrices":
            raise MarkovConfigError(
                _PERIOD_MATRICES_UNSUPPORTED,
                loc=(*_LOC_SECCION, "dynamics", "projection_mode"),  # D-EXI-5
            )
        return self


def _column_values(cfg: object, fields: tuple[str, ...]) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar strings no vacíos."""
    values: dict[str, str] = {}
    for field in fields:
        value = getattr(cfg, field)
        if value is not None:
            values[field] = value
    return values


def _require_non_empty_strings(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres declarativos no sean vacíos.

    Sus ``raise`` van sin ``loc`` (D-EXI-5) por dos razones que se acumulan: ``empty`` es una
    LISTA —varios campos pueden estar vacíos a la vez—, y el helper lo comparten cuatro contextos
    (``input``, ``states``, ``absorbing_states``, ``dynamics``) que cuelgan de subsecciones
    distintas, así que la ruta no es una constante de este módulo. Anclarlo exige cambiar la firma,
    que es más que añadir el kwarg.
    """
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise MarkovConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")


def _require_strictly_increasing(values: tuple[int, ...] | tuple[float, ...], *, name: str) -> None:
    """Valida que una secuencia numérica sea positiva y estrictamente creciente.

    Sus tres ``raise`` van sin ``loc`` (D-EXI-5): la ruta sería ``dynamics.<name>`` con ``name``
    **variable**, y el gate que vigila las rutas las evalúa de forma estática —un segmento que no
    sea literal entra en «inevaluables» y lo pone rojo—. Un ``loc`` que el gate no puede leer es
    una ruta sin vigilar, que es justo lo que ese gate existe para impedir.
    """
    non_finite = [idx for idx, value in enumerate(values) if not isfinite(value)]
    if non_finite:
        raise MarkovConfigError(f"{name} debe contener valores finitos: {non_finite}.")
    non_positive = [idx for idx, value in enumerate(values) if value <= 0]
    if non_positive:
        raise MarkovConfigError(f"{name} debe contener valores positivos: {non_positive}.")
    if any(next_value <= current for current, next_value in pairwise(values)):
        raise MarkovConfigError(f"{name} debe ser estrictamente creciente.")


def _is_non_finite_number(value: Any) -> bool:
    """Indica si un valor numérico serializable representa NaN o infinito."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return not isfinite(numeric)
