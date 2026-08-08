"""Config declarativo de la capa ``scorecard`` (SDD-09 §5).

:class:`ScorecardConfig` es la sección ``scorecard`` de
:class:`~nikodym.core.config.NikodymConfig`: escalamiento determinista de log-odds a puntos de
scorecard desde el modelo logístico PD. Toda clase hereda de
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

ScoreDirection = Literal["higher_is_lower_risk", "higher_is_higher_risk"]
RoundingMethod = Literal["none", "nearest_integer", "floor_integer", "ceil_integer"]
InterceptAllocation = Literal["uniform"]

__all__ = [
    "InterceptAllocation",
    "PointOverrideConfig",
    "RoundingMethod",
    "ScoreDirection",
    "ScorecardConfig",
]

#: Prefijo del ``loc`` de los errores de esta sección (D-EXI-5). Vive en un solo sitio para que un
#: renombrado de la sección no haya que perseguirlo por cada ``raise``: la ruta que el error declara
#: es **absoluta desde la raíz del config** —el ``except`` que la traduce vive en el endpoint y
#: atrapa la validación del ``NikodymConfig`` entero, así que ahí ya no se sabe qué sección la
#: emitió—, y eso ata el dominio con el nombre de su campo en la raíz. Un gate exige que toda ruta
#: declarada resuelva contra ``NikodymConfig``.
_LOC_SECCION: tuple[str, ...] = ("scorecard",)


class PointOverrideConfig(NikodymBaseConfig):
    """Override manual auditado para una pareja ``feature``/``bin_label``."""

    feature: str = Field(
        default=...,
        title="Variable",
        description="Nombre de la variable cuyo bin recibe un override manual de puntos.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Overrides",
            "ui_order": 1,
            "ui_help": (
                "Nombre exacto de la variable, tal como aparece en el modelo, cuyo bin se "
                "fuerza manualmente."
            ),
        },
    )
    bin_label: str = Field(
        default=...,
        title="Bin",
        description="Etiqueta del bin al que se le fuerza un puntaje publicado.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Overrides",
            "ui_order": 2,
            "ui_help": (
                "Etiqueta exacta del bin, tal como aparece en la tabla de binning de esa "
                "variable. Si no calza exactamente, el override no se aplica."
            ),
        },
    )
    points: int | float = Field(
        default=...,
        title="Puntos forzados",
        description="Puntos publicados para la pareja variable/bin indicada.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Overrides",
            "ui_order": 3,
            "ui_help": (
                "Puntaje que se publica para esta variable/bin en vez del calculado por "
                "fórmula a partir del WoE y el coeficiente."
            ),
        },
    )
    reason: str = Field(
        default=...,
        title="Justificación",
        description="Razón auditable que explica por qué el override manual es necesario.",
        json_schema_extra={
            "ui_widget": "text_area",
            "ui_group": "Overrides",
            "ui_order": 4,
            "ui_help": (
                "Explicación obligatoria de por qué se fuerza este puntaje manualmente; "
                "queda registrada para auditoría y no puede quedar vacía."
            ),
        },
    )

    @model_validator(mode="after")
    def _check_override_valido(self) -> Self:
        """Valida que el override sea auditable y numéricamente finito.

        D-EXI-5: sus dos ``raise`` van **SIN** ``loc``, y no es un olvido. Esta clase es un ELEMENTO
        de ``scorecard.point_overrides``, que es una tupla: la ruta del campo que el usuario tiene
        que corregir lleva el índice de la fila, que esta clase no conoce, y
        ``("scorecard", "point_overrides", "reason")`` **no resuelve** —medido contra el resolvedor
        del gate—. Una ruta que no existe es peor que no anclar. Anclar la lista entera tampoco
        sirve: mandaría al campo equivocado —el contenedor, no la celda— y además metería la ruta
        del padre dentro de una clase pública que el padre podría dejar de usar en silencio.
        """
        if not self.reason.strip():
            raise ConfigError("point_overrides.reason no puede estar vacío.")
        if isinstance(self.points, float) and not math.isfinite(self.points):
            raise ConfigError("point_overrides.points debe ser un número finito.")
        return self


class ScorecardConfig(NikodymBaseConfig):
    """Traduce el log-odds del modelo a puntos de scorecard."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección scorecard",
        description="Variante de la sección de scorecard; hoy solo existe la estándar.",
        json_schema_extra={
            "ui_widget": "hidden",
            "ui_group": "General",
            "ui_order": 0,
            "ui_help": "Identificador interno del tipo de sección; no requiere edición.",
        },
    )
    pdo: float = Field(
        default=20.0,
        gt=0.0,
        title="PDO",
        description="Puntos necesarios para duplicar los odds definidos por la dirección.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Escala",
            "ui_order": 1,
            "ui_help": (
                "Cuántos puntos de score se necesitan para duplicar el ratio de buenos "
                "sobre malos (odds). Un PDO menor hace el score más sensible: la misma "
                "diferencia de riesgo se traduce en más puntos de separación."
            ),
        },
    )
    target_score: float = Field(
        default=600.0,
        title="Score objetivo",
        description="Score asignado a una observación con los odds objetivo configurados.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Escala",
            "ui_order": 2,
            "ui_help": (
                "Puntaje que recibe una observación cuyos odds de buenos/malos son "
                "exactamente los odds objetivo. Es el punto de anclaje de toda la escala."
            ),
        },
    )
    target_odds: float = Field(
        default=50.0,
        gt=0.0,
        title="Odds objetivo buenos/malos",
        description="Odds de referencia asociados al score objetivo según la dirección.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Escala",
            "ui_order": 3,
            "ui_help": (
                "Odds buenos/malos (ej. 50 significa 50 buenos por cada malo) usados como "
                "referencia para anclar la escala junto con el score objetivo."
            ),
        },
    )
    score_direction: ScoreDirection = Field(
        default="higher_is_lower_risk",
        title="Dirección del score",
        description="Define si un score mayor representa menor riesgo o mayor riesgo.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Escala",
            "ui_order": 4,
            "ui_help": (
                "Define si un score más alto significa menor riesgo (convención habitual) "
                "o mayor riesgo. Cambiarlo invierte el sentido de todos los puntajes."
            ),
        },
    )
    intercept_allocation: InterceptAllocation = Field(
        default="uniform",
        title="Distribución del intercepto",
        description="Distribuye el intercepto de forma uniforme entre variables finales.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Escala",
            "ui_order": 5,
            "ui_help": (
                "Cómo se reparte el intercepto del modelo entre las variables finales al "
                "calcular los puntos. Hoy solo existe reparto uniforme (a partes iguales)."
            ),
        },
    )
    rounding_method: RoundingMethod = Field(
        default="nearest_integer",
        title="Redondeo de puntos",
        description="Método para publicar puntos por atributo a partir de puntos crudos.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Publicación",
            "ui_order": 1,
            "ui_help": (
                "Cómo se redondean los puntos calculados por fórmula antes de publicarlos: "
                "sin redondeo, al entero más cercano, hacia abajo o hacia arriba. Afecta el "
                "puntaje final, no solo su presentación."
            ),
        },
    )
    output_suffix: str = Field(
        default="__points",
        title="Sufijo columnas de puntos",
        description="Sufijo usado para crear una columna de puntos por variable final.",
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": "Salida",
            "ui_order": 1,
            "ui_help": (
                "Texto que se agrega al nombre de cada variable para nombrar su columna de "
                "puntos (variable + este sufijo). No puede quedar vacío."
            ),
        },
    )
    score_column: str = Field(
        default="score",
        title="Columna score total",
        description="Nombre de la columna que contendrá el score total por registro.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Salida",
            "ui_order": 2,
            "ui_help": (
                "Nombre de la columna con el puntaje total por registro (suma de los "
                "puntos de todas las variables). No puede coincidir en terminación con el "
                "sufijo de puntos ni quedar vacío."
            ),
        },
    )
    min_score: float | None = Field(
        default=None,
        title="Score mínimo permitido",
        description="Límite inferior opcional para diagnóstico o clipping del score total.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Rango",
            "ui_order": 1,
            "ui_help": (
                "Puntaje mínimo de referencia para detectar scores fuera de rango. Si "
                "además se activa recortar, los scores por debajo se ajustan a este valor."
            ),
        },
    )
    max_score: float | None = Field(
        default=None,
        title="Score máximo permitido",
        description="Límite superior opcional para diagnóstico o clipping del score total.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Rango",
            "ui_order": 2,
            "ui_help": (
                "Puntaje máximo de referencia para detectar scores fuera de rango. Si "
                "además se activa recortar, los scores por encima se ajustan a este valor."
            ),
        },
    )
    clip: bool = Field(
        default=False,
        title="Recortar scores fuera de rango",
        description=(
            "Si está activado, recorta el puntaje total a los límites configurados y lo deja "
            "auditado."
        ),
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Rango",
            "ui_order": 3,
            "ui_help": (
                "Si se activa, los scores fuera de los límites mínimo/máximo se recortan a "
                "esos límites y la operación queda auditada. Requiere haber definido al "
                "menos un límite."
            ),
        },
    )
    point_overrides: tuple[PointOverrideConfig, ...] = Field(
        default_factory=tuple,
        title="Overrides manuales de puntos",
        description="Overrides manuales auditables por pareja variable/bin; vacío por defecto.",
        json_schema_extra={
            "ui_widget": "table",
            "ui_group": "Overrides",
            "ui_order": 1,
            "ui_help": (
                "Lista de overrides manuales de puntaje por variable/bin, cada uno con su "
                "justificación auditada. Vacía por defecto: el scorecard se calcula "
                "íntegramente por fórmula."
            ),
        },
    )

    @field_validator("pdo", "target_odds", mode="before")
    @classmethod
    def _check_positivo(cls, valor: Any) -> Any:
        """Falla con ``ConfigError`` para los positivos estrictos del SDD-09 §5.

        D-EXI-5: **SIN** ``loc``. El validador lo comparten DOS campos y su mensaje nombra a los
        dos; cuál de ellos trae el valor inválido sólo se sabe en runtime, así que un ancla literal
        aquí sería la correcta para uno y falsa para el otro —y el gate que vigila estas rutas las
        evalúa estáticamente, de modo que una ruta calculada tampoco es una opción—. Mismo trato que
        ``_check_enteros_positivos`` de ``calibration/config.py``.
        """
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            observado = float(valor)
            if not math.isfinite(observado) or observado <= 0.0:
                raise ConfigError("pdo y target_odds deben ser números finitos mayores que 0.")
        return valor

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida invariantes de nombres, rango y overrides definidos por SDD-09 §5."""
        # D-EXI-5: el `raise` va AQUÍ y no dentro del helper, para que el `loc` sea una tupla
        # literal. El gate que vigila estas rutas las evalúa **estáticamente** y rechaza un último
        # tramo variable —con razón: una ruta que el gate no puede leer es una ruta sin vigilar—.
        # Por eso el helper devuelve el mensaje en vez de levantarlo.
        if msg := _mensaje_si_no_finito("target_score", self.target_score):
            raise ConfigError(msg, loc=(*_LOC_SECCION, "target_score"))
        if self.min_score is not None and (
            msg := _mensaje_si_no_finito("min_score", self.min_score)
        ):
            raise ConfigError(msg, loc=(*_LOC_SECCION, "min_score"))
        if self.max_score is not None and (
            msg := _mensaje_si_no_finito("max_score", self.max_score)
        ):
            raise ConfigError(msg, loc=(*_LOC_SECCION, "max_score"))
        if not self.output_suffix.strip():
            raise ConfigError(
                "output_suffix no puede estar vacío.",
                # D-EXI-5: el valor inválido es el de ESTE campo, así que el formulario puede
                # llevar al usuario justo al input donde lo escribió.
                loc=(*_LOC_SECCION, "output_suffix"),
            )
        if not self.score_column.strip():
            raise ConfigError(
                "score_column no puede estar vacío.",
                loc=(*_LOC_SECCION, "score_column"),  # D-EXI-5
            )
        if self.score_column.endswith(self.output_suffix):
            # D-EXI-5: SIN `loc` a propósito. Es un invariante ENTRE dos campos —el nombre de la
            # columna total y el sufijo con que se nombran las columnas por variable— y se deshace
            # editando cualquiera de los dos: quien puso el sufijo corto puede tener razón y quien
            # nombró la columna también. Anclar en uno elegiría por el usuario.
            raise ConfigError("score_column no puede terminar con output_suffix.")
        if (
            self.min_score is not None
            and self.max_score is not None
            and self.min_score >= self.max_score
        ):
            # D-EXI-5: SIN `loc`, misma razón: los dos extremos se contradicen entre sí y se arregla
            # bajando uno o subiendo el otro; cuál está mal lo sabe el usuario, no el motor.
            raise ConfigError("min_score debe ser menor que max_score.")
        if self.clip and self.min_score is None and self.max_score is None:
            # D-EXI-5: SIN `loc`. Es un «X exige Y» cuya Y es una DISYUNCIÓN —basta `min_score` o
            # `max_score`—, y encima se satisface también apagando `clip`. Anclar en uno de los tres
            # llevaría al campo que no era dos de cada tres veces.
            raise ConfigError("clip=True exige configurar min_score o max_score.")

        vistos: set[tuple[str, str]] = set()
        for override in self.point_overrides:
            clave = (override.feature, override.bin_label)
            if clave in vistos:
                raise ConfigError(
                    "point_overrides no puede repetir la misma pareja "
                    f"(feature, bin_label): {clave!r}.",
                    # D-EXI-5: la repetición es una propiedad de la LISTA entera, así que el campo
                    # al que pertenece el error es `point_overrides` y no una fila suelta —cuya
                    # ruta con índice, medida, no resuelve—.
                    loc=(*_LOC_SECCION, "point_overrides"),
                )
            vistos.add(clave)
        return self

    def direccion_del_score_declarada(self) -> str:
        """Declara con qué orientación esta sección construye el puntaje (D-DIR-5).

        Es el protocolo ``METODO_CONVENCION_SCORE`` del preflight, por convención de nombre y no por
        herencia, igual que ``requisitos_incumplidos``. Existe para que el núcleo **no** tenga que
        leer ``config.scorecard.score_direction``: con la sección opaca —el estado por defecto— ese
        atributo sería una clave de ``dict``, y el núcleo pasaría a conocer el vocabulario de un
        dominio, que es justo lo que D-INV-1 rechazó.

        Quien la construye es quien la declara: `scorecard` es la única sección que **fabrica** el
        puntaje (`scaler.py:536-553` decide el signo de cada punto con este valor). `performance` y
        `stability` sólo lo miden, y por eso preguntan en vez de declarar.
        """
        return self.score_direction


def _mensaje_si_no_finito(nombre: str, valor: float) -> str | None:
    """Mensaje de error si ``valor`` no es finito, o ``None`` si lo es.

    D-EXI-5: **devuelve** el mensaje en vez de levantarlo para que el ``raise`` —y con él su ``loc``
    literal— viva en el llamador. Un ``loc`` armado con el parámetro ``nombre`` sería correcto en
    runtime y **no verificable estáticamente**, que es justo lo que el gate de rutas rechaza para
    que ninguna quede sin vigilar. Los campos son float y participan del ``config_hash``.
    """
    return None if math.isfinite(valor) else f"{nombre} debe ser un número finito."
