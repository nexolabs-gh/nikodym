"""Config declarativo de la capa ``calibration`` (SDD-10 §5).

:class:`CalibrationConfig` es la sección ``calibration`` de
:class:`~nikodym.core.config.NikodymConfig`: calibración determinista de la PD cruda del modelo
logístico contra una tasa central aprobada. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import math
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError

CalibrationMethod = Literal["intercept_offset", "platt_scaling", "isotonic"]
AnchorKind = Literal["through_the_cycle", "point_in_time"]
AnchorSource = Literal[
    "business_input",
    "historical_default_rate",
    "development_observed",
    "external_regulatory",
]

__all__ = [
    "AnchorKind",
    "AnchorSource",
    "CalibrationConfig",
    "CalibrationMethod",
]

#: Prefijo del `loc` de los errores de esta sección (D-EXI-5). Vive en un solo sitio para que un
#: renombrado de la sección no haya que perseguirlo por cada `raise`.
_LOC_SECCION: tuple[str, ...] = ("calibration",)

_SUPERVISED_METHODS: frozenset[str] = frozenset({"platt_scaling", "isotonic"})
_EXPLICIT_ANCHOR_SOURCES: frozenset[str] = frozenset(
    {"business_input", "historical_default_rate", "external_regulatory"}
)
_COLUMN_FIELDS: tuple[str, ...] = (
    "pd_raw_column",
    "linear_predictor_column",
    "pd_calibrated_column",
    "linear_predictor_calibrated_column",
    "partition_column",
    "target_column",
)


class CalibrationConfig(NikodymBaseConfig):
    """Ajusta la PD cruda del modelo a una tasa central de anclaje aprobada."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección calibration",
        description="Variante de la sección de calibración; hoy solo existe la estándar.",
        json_schema_extra={
            "ui_widget": "hidden",
            "ui_group": "General",
            "ui_order": 0,
            "ui_help": "Identificador interno del tipo de sección; no requiere edición.",
        },
    )
    method: CalibrationMethod = Field(
        default="intercept_offset",
        title="Método de calibración",
        description="Método usado para transformar PD cruda en PD calibrada.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Método",
            "ui_order": 1,
            "ui_help": (
                "Cómo se pasa de PD cruda a PD calibrada: desplazamiento de intercepto (solo "
                "ajusta el nivel, preserva el orden de riesgo; es el default) o escalamiento de "
                "Platt / isotónica (ambos re-entrenan con el target de Desarrollo antes de "
                "anclar)."
            ),
        },
    )
    target_pd: float | None = Field(
        default=None,
        gt=0.0,
        lt=1.0,
        title="PD objetivo",
        description=("Tasa central de anclaje, entre 0 y 1."),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Ancla",
            "ui_order": 1,
            "ui_help": (
                "Tasa central (PD promedio) a la que se ancla la calibración, entre 0 y 1. Con la "
                "fuente development_observed se deja VACÍA: esa fuente la estima como el promedio "
                "de largo plazo observado en Desarrollo, así que fijar aquí un número es un "
                "error y la configuración lo rechaza en vez de descartarlo en silencio. Con "
                "'business_input', 'historical_default_rate' y 'external_regulatory' es "
                "OBLIGATORIA y explícita: esas fuentes no derivan la tasa de los datos, así que "
                "sin ella la "
                "configuración falla en vez de anclar a un número inventado."
            ),
        },
    )
    anchor_kind: AnchorKind = Field(
        default="through_the_cycle",
        title="Tipo de ancla",
        description="Define si el anclaje representa una visión TTC o PIT.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Ancla",
            "ui_order": 2,
            "ui_help": (
                "Etiqueta si la tasa de ancla representa una visión de largo plazo (through the "
                "cycle) o del momento actual (point in time). Debe ser coherente con la fuente "
                "elegida en anchor_source."
            ),
        },
    )
    anchor_source: AnchorSource = Field(
        default="development_observed",
        title="Fuente de la ancla",
        description=(
            "Origen auditable de la tasa central. Por default se deriva del target de Desarrollo "
            "como long-run average TTC."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Ancla",
            "ui_order": 3,
            "ui_help": (
                "De dónde sale la tasa central: puede fijarse a mano (negocio, histórico o "
                "regulatorio, informando PD objetivo) o calcularse sola como el promedio "
                "observado en Desarrollo (opción por defecto, sin PD objetivo)."
            ),
        },
    )
    fit_partition: Literal["desarrollo"] = Field(
        default="desarrollo",
        title="Partición de ajuste",
        description="Partición usada para ajustar la calibración; hoy solo puede ser Desarrollo.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Ajuste",
            "ui_order": 1,
            "ui_help": (
                "Partición usada para ajustar la calibración. Fija en Desarrollo en esta "
                "versión; no editable en la práctica."
            ),
        },
    )
    target_tolerance: float = Field(
        default=1e-12,
        gt=0.0,
        title="Tolerancia de media PD",
        description="Tolerancia máxima entre la media PD calibrada y la PD objetivo.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Ajuste",
            "ui_order": 2,
            "ui_help": (
                "Margen de error máximo tolerado entre la PD calibrada promedio y la PD "
                "objetivo. Si el ajuste no logra acercarse lo suficiente, el proceso falla en "
                "vez de publicar un número impreciso."
            ),
        },
    )
    max_abs_offset: float | None = Field(
        default=None,
        title="Máximo offset absoluto",
        description=(
            "Tope opcional del desplazamiento de reanclaje a la tasa central. En blanco se audita "
            "el offset extremo sin fallar; si se informa, debe ser finito y mayor que 0."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Ajuste",
            "ui_order": 3,
            "ui_help": (
                "Tope opcional al tamaño del desplazamiento usado para anclar la PD. Con un "
                "valor definido, un desplazamiento mayor hace fallar el ajuste; déjelo vacío "
                "para solo dejarlo registrado en auditoría sin bloquear."
            ),
        },
    )
    max_iter: int = Field(
        default=100,
        ge=1,
        title="Iteraciones máximas del solver",
        description="Máximo de iteraciones permitidas al resolver parámetros de calibración.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Ajuste",
            "ui_order": 4,
            "ui_help": (
                "Máximo de iteraciones que el solver numérico puede usar para encontrar el "
                "ajuste. Suba este valor solo si el ajuste falla por no converger."
            ),
        },
    )
    min_fit_rows: int = Field(
        default=30,
        ge=1,
        title="Mínimo de filas de Desarrollo",
        description="Guard técnico mínimo de filas en Desarrollo para aceptar el ajuste.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Ajuste",
            "ui_order": 5,
            "ui_help": (
                "Mínimo de filas de Desarrollo exigido para aceptar el ajuste; evita calibrar "
                "con una muestra demasiado chica."
            ),
        },
    )
    require_both_classes_for_supervised: bool = Field(
        default=True,
        title="Exigir ambas clases para Platt/isotónica",
        description="Si el método es supervisado, exige clases 0 y 1 en Desarrollo durante fit.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Ajuste",
            "ui_order": 6,
            "ui_help": (
                "Exige que Desarrollo tenga casos con y sin incumplimiento antes de ajustar "
                "Platt o isotónica. En esta versión debe mantenerse activado si se usa alguno "
                "de esos métodos."
            ),
        },
    )
    pd_raw_column: str = Field(
        default="pd_raw",
        title="Columna PD cruda",
        description="Columna de entrada con la probabilidad de default cruda del modelo.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 1,
            "ui_help": "Columna de entrada con la PD cruda (sin calibrar) que entrega el modelo.",
        },
    )
    linear_predictor_column: str = Field(
        default="linear_predictor",
        title="Columna logit crudo",
        description="Columna de entrada con el predictor lineal crudo del modelo.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 2,
            "ui_help": (
                "Columna de entrada con el logit (predictor lineal) crudo del modelo, antes de "
                "calibrar."
            ),
        },
    )
    pd_calibrated_column: str = Field(
        default="pd_calibrated",
        title="Columna PD calibrada",
        description="Columna de salida que contendrá la probabilidad de default calibrada.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 3,
            "ui_help": "Columna de salida donde queda escrita la PD ya calibrada.",
        },
    )
    linear_predictor_calibrated_column: str = Field(
        default="linear_predictor_calibrated",
        title="Columna logit calibrado",
        description="Columna de salida que contendrá el predictor lineal calibrado.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 4,
            "ui_help": "Columna de salida con el logit (predictor lineal) ya calibrado.",
        },
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna estructural que identifica Desarrollo, Holdout, OOT y exclusiones.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 5,
            "ui_help": (
                "Columna que indica a qué partición pertenece cada fila (Desarrollo, Holdout, "
                "OOT u otra); define qué filas se usan para el ajuste."
            ),
        },
    )
    target_column: str = Field(
        default="target",
        title="Columna target",
        description="Columna binaria 0/1 usada por métodos supervisados durante fit.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 6,
            "ui_help": (
                "Columna binaria de incumplimiento observado (0/1), usada para calcular la "
                "tasa central automática y para ajustar Platt e isotónica."
            ),
        },
    )

    @field_validator("target_pd", mode="before")
    @classmethod
    def _check_target_pd(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si ``target_pd`` no está estrictamente en ``(0, 1)``."""
        if isinstance(valor, bool):
            raise ConfigError(
                "target_pd debe ser un número finito estrictamente entre 0 y 1.",
                # D-EXI-5: el error se ANCLA a su campo, para que el formulario pueda llevar ahí al
                # usuario en vez de dejarle un mensaje sin control. La ruta va absoluta desde la
                # raíz del config, y un gate exige que resuelva contra `NikodymConfig`.
                loc=(*_LOC_SECCION, "target_pd"),
            )
        if isinstance(valor, (int, float)):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0 or observado >= 1.0:
                raise ConfigError(
                    "target_pd debe ser un número finito estrictamente entre 0 y 1.",
                    loc=(*_LOC_SECCION, "target_pd"),
                )
        return valor

    @field_validator("target_tolerance", mode="before")
    @classmethod
    def _check_target_tolerance(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si ``target_tolerance`` no es positivo y finito."""
        if isinstance(valor, bool):
            raise ConfigError(
                "target_tolerance debe ser un número finito mayor que 0.",
                loc=(*_LOC_SECCION, "target_tolerance"),
            )
        if isinstance(valor, (int, float)):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0:
                raise ConfigError(
                    "target_tolerance debe ser un número finito mayor que 0.",
                    loc=(*_LOC_SECCION, "target_tolerance"),
                )
        return valor

    @field_validator("max_abs_offset", mode="before")
    @classmethod
    def _check_max_abs_offset(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si ``max_abs_offset`` no es ``None`` o positivo finito."""
        if valor is None:
            return None
        if isinstance(valor, bool):
            raise ConfigError(
                "max_abs_offset debe ser None o un número finito mayor que 0.",
                loc=(*_LOC_SECCION, "max_abs_offset"),
            )
        if isinstance(valor, (int, float)):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0:
                raise ConfigError(
                    "max_abs_offset debe ser None o un número finito mayor que 0.",
                    loc=(*_LOC_SECCION, "max_abs_offset"),
                )
        return valor

    @field_validator("max_iter", "min_fit_rows", mode="before")
    @classmethod
    def _check_enteros_positivos(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` si los contadores enteros son menores que 1."""
        if isinstance(valor, bool):
            raise ConfigError("max_iter y min_fit_rows deben ser enteros mayores o iguales a 1.")
        if isinstance(valor, int) and valor < 1:
            raise ConfigError("max_iter y min_fit_rows deben ser enteros mayores o iguales a 1.")
        return valor

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida finitud, ancla y nombres de columnas definidos por SDD-10 §5/§8."""
        # D-EXI-5: el `raise` va AQUÍ y no dentro del helper, para que el `loc` sea una tupla
        # literal. El gate que vigila estas rutas las evalúa **estáticamente** y rechaza un último
        # tramo variable —con razón: una ruta que el gate no puede leer es una ruta sin vigilar—.
        # Por eso el helper devuelve el mensaje en vez de levantarlo.
        if self.target_pd is not None and (
            msg := _mensaje_si_no_finito("target_pd", self.target_pd)
        ):
            raise ConfigError(msg, loc=(*_LOC_SECCION, "target_pd"))
        if msg := _mensaje_si_no_finito("target_tolerance", self.target_tolerance):
            raise ConfigError(msg, loc=(*_LOC_SECCION, "target_tolerance"))
        if self.max_abs_offset is not None and (
            msg := _mensaje_si_no_positivo_finito("max_abs_offset", self.max_abs_offset)
        ):
            raise ConfigError(msg, loc=(*_LOC_SECCION, "max_abs_offset"))

        # ── Coherencia del ancla (SDD-10 §5): nunca etiquetar una salida con una fuente/visión que
        # no se corresponde con el número realmente usado (criterio: o se ancla de verdad, o falla).
        if self.anchor_kind == "point_in_time" and self.anchor_source == "development_observed":
            raise ConfigError(
                "anchor_kind='point_in_time' es incoherente con "
                "anchor_source='development_observed': la media observada de Desarrollo es una "
                "tasa de largo plazo (TTC) por definición; etiquetar esa salida como point_in_time "
                "sería una etiqueta falsa. Use anchor_kind='through_the_cycle' o una fuente PIT.",
                # D-EXI-5 con el criterio de D-ANC-3, el mismo de los dos `raise` de abajo: de los
                # dos campos que se contradicen sólo UNO puede haberlo escrito el usuario a
                # propósito. `anchor_source='development_observed'` es el DEFAULT de fábrica —puede
                # no haberlo tocado nunca— y `anchor_kind` viene en 'through_the_cycle', así que
                # 'point_in_time' es necesariamente un desvío suyo. Ahí es donde hay que llevarlo.
                loc=(*_LOC_SECCION, "anchor_kind"),
            )
        # SIN `loc` a propósito, y es el contraste que fija el criterio: aquí los DOS valores son
        # desvíos del usuario ('external_regulatory' tampoco es el default), así que ninguno es «el
        # equivocado» y el arreglo pasa por cualquiera de los dos. Anclar sería elegir por él.
        if self.anchor_kind == "point_in_time" and self.anchor_source == "external_regulatory":
            raise ConfigError(
                "anchor_kind='point_in_time' no es compatible con "
                "anchor_source='external_regulatory' en v1."
            )
        if self.anchor_source in _EXPLICIT_ANCHOR_SOURCES and self.target_pd is None:
            raise ConfigError(
                f"anchor_source='{self.anchor_source}' exige fijar target_pd explícito en (0, 1): "
                "esta fuente no deriva la tasa central de los datos y no existe un placeholder "
                "válido; sin target_pd no hay ancla (no se ancla al antiguo 0.05 por defecto).",
                # D-EXI-5: «X exige Y» ancla en Y —lo que falta—, no en la fuente que lo exige.
                loc=(*_LOC_SECCION, "target_pd"),
            )
        # D-ANC-1: el caso SIMÉTRICO del de arriba, y por el mismo criterio. La fuente que se lee de
        # los datos no admite un número que la contradiga: `fit` lo descartaba en silencio y el
        # informe publicaba la tasa observada bajo el rótulo del valor pedido. `target_pd` tiene
        # default `None`, así que un número aquí sólo puede haberlo escrito alguien a propósito
        # (D-ANC-3) — no hace falta `model_fields_set`.
        if self.anchor_source == "development_observed" and self.target_pd is not None:
            raise ConfigError(
                "anchor_source='development_observed' calcula la tasa central como el promedio "
                f"observado en Desarrollo, así que el target_pd={self.target_pd!r} que fijó no se "
                "usaría: la corrida anclaría a otro número sin avisar. Deje target_pd sin fijar, o "
                "elija la fuente que corresponda a ese número: 'business_input', "
                "'historical_default_rate' o 'external_regulatory'.",
                # D-EXI-5: ancla en `target_pd` y no en la fuente por la misma razón que el caso
                # simétrico de arriba —es el campo cuyo valor se está rechazando—, y porque su
                # default es `None`: un número ahí sólo puede haberlo escrito alguien a propósito
                # (D-ANC-3), mientras que la fuente puede seguir estando en su default de fábrica.
                loc=(*_LOC_SECCION, "target_pd"),
            )

        columns = _column_values(self)
        vacias = [nombre for nombre, columna in columns.items() if not columna.strip()]
        if vacias:
            raise ConfigError(f"Las columnas de calibration no pueden estar vacías: {vacias}.")

        normalizadas: dict[str, str] = {}
        duplicadas: list[tuple[str, str, str]] = []
        for nombre, columna in columns.items():
            clave = columna.strip()
            previo = normalizadas.get(clave)
            if previo is not None:
                duplicadas.append((previo, nombre, clave))
            normalizadas[clave] = nombre
        if duplicadas:
            raise ConfigError(f"Las columnas de calibration no pueden colisionar: {duplicadas}.")

        if self.method in _SUPERVISED_METHODS and not self.require_both_classes_for_supervised:
            raise ConfigError(
                "platt_scaling e isotonic requieren require_both_classes_for_supervised=True en "
                "v1.",
                # D-EXI-5: «X exige Y» ancla en Y —el interruptor que hay que activar—, no en el
                # método, que es una elección legítima.
                loc=(*_LOC_SECCION, "require_both_classes_for_supervised"),
            )

        return self


def _column_values(cfg: CalibrationConfig) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar colisiones."""
    return {nombre: getattr(cfg, nombre) for nombre in _COLUMN_FIELDS}


def _mensaje_si_no_finito(nombre: str, valor: float) -> str | None:
    """Mensaje de error si ``valor`` no es finito, o ``None`` si lo es.

    D-EXI-5: **devuelve** el mensaje en vez de levantarlo para que el ``raise`` —y con él su ``loc``
    literal— viva en el llamador. Un ``loc`` armado con el parámetro ``nombre`` sería correcto en
    runtime y **no verificable estáticamente**, que es justo lo que el gate de rutas rechaza para
    que ninguna quede sin vigilar. Los campos son float y participan del ``config_hash``.
    """
    return None if math.isfinite(valor) else f"{nombre} debe ser un número finito."


def _mensaje_si_no_positivo_finito(nombre: str, valor: float) -> str | None:
    """Mensaje de error si ``valor`` no es finito y > 0, o ``None`` si lo es (ver el gemelo)."""
    if math.isfinite(valor) and valor > 0.0:
        return None
    return f"{nombre} debe ser None o un número finito mayor que 0."
