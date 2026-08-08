"""Config declarativo de la capa ``provisioning.internal`` (SDD-28 §5.1).

:class:`InternalProvisioningConfig` es la sección ``provisioning_internal`` de
:class:`~nikodym.core.config.NikodymConfig`: el **método interno** del banco, o sea su propio
cálculo de provisiones, independiente del método estándar de su supervisor (en Chile, el Cap. B-1
§3 de la CMF lo exige explícitamente). El motor no conoce ninguna tabla de supervisor: es
jurisdiccionalmente neutro, y por eso su copy visible no cita ninguna norma. El motor
agrupa a los deudores en **grupos homogéneos** y aplica, por grupo,
``provisión = Exposición · PD · LGD`` (o directamente la tasa de pérdida esperada del grupo).

Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y
``frozen=True``); cada campo declara ``title``/``description`` y metadatos ``ui_*`` para que la UI
(SDD-23) sea un editor del mismo config. La sección es **computacional**: entra al ``config_hash``
global cuando está activa.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.dataset_check import Requisito
from nikodym.provisioning.internal.exceptions import InternalConfigError
from nikodym.provisioning.lgd import (
    WORKOUT_COST_COLUMN,
    WORKOUT_EAD_COLUMN,
    WORKOUT_RATE_COLUMN,
    WORKOUT_TIME_COLUMN,
)

InternalPdSourceDomain = Literal["calibration", "model"]
InternalGroupingMethod = Literal["score_band", "segment", "provided"]
#: Dominio de valores del discriminador de :data:`InternalLgdConfig`.
#:
#: ⚠️ Se amplía con las tres formas MODELADAS (D-LGD-4). Dejarlo en las dos observadas convertiría
#: un alias público llamado «el método de LGD del motor interno» en una afirmación falsa sobre tres
#: quintos de su dominio. No lo consume ninguna anotación del paquete —sólo se re-exporta
#: (`internal/__init__.py:31`)—, así que ampliarlo no estrecha ningún tipo existente.
InternalLgdMethod = Literal[
    "provided",
    "group_historical",
    "beta_regression",
    "fractional_response",
    "workout",
]
InternalProvisioningMethod = Literal["pd_lgd", "direct_loss_rate"]
InternalRoundingPolicy = Literal["none", "currency_2dp", "integer_currency"]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]

__all__ = [
    "InternalGroupingMethod",
    "InternalLgdBetaRegression",
    "InternalLgdConfig",
    "InternalLgdFractionalResponse",
    "InternalLgdGroupHistorical",
    "InternalLgdMethod",
    "InternalLgdModelada",
    "InternalLgdProvided",
    "InternalLgdWorkout",
    "InternalPdSourceDomain",
    "InternalProvisioningConfig",
    "InternalProvisioningMethod",
    "InternalRoundingPolicy",
]

#: Prefijo de la ruta de este dominio en ``NikodymConfig``, para anclar sus errores (D-EXI-5).
#:
#: ⚠️ En UN solo sitio y no repetido en cada ``raise``: la ruta que el error declara tiene que ser
#: **absoluta desde la raíz del config** —el ``except`` que la traduce vive en el endpoint y
#: atrapa la validación del ``NikodymConfig`` entero, así que ahí ya no se sabe qué sección la
#: emitió—, y eso ata al dominio con el nombre de su campo en la raíz. Repetirlo por `raise`
#: multiplicaría el sitio donde ese acoplamiento puede quedarse stale; concentrado aquí, lo
#: vigila un gate que exige que toda ruta declarada resuelva contra ``NikodymConfig``.
_LOC_SECCION: tuple[str, ...] = ("provisioning_internal",)

_GROUP_COL_GROUPINGS: tuple[str, ...] = ("segment", "provided")
# Las dos columnas entre las que un archivo puede volverse ambiguo (D-AMB-2): el default de
# fábrica de este motor tras D-JUR-8 y el que traía antes, que sigue siendo el del método estándar
# (`cmf/config.py`, D-SEG-9 enmendado). Un archivo con ambas no distingue una elección de un
# default, y son justo los dos nombres que conviven en un panel que corre los dos motores.
_COLUMNAS_CARTERA_AMBIGUAS: frozenset[str] = frozenset({"portfolio", "cmf_portfolio"})
_ROOT_COLUMN_FIELDS: tuple[str, ...] = (
    "as_of_date_col",
    "portfolio_col",
    "exposure_col",
    "pd_column",
)


class _InternalLgdComun(NikodymBaseConfig):
    """Lo que toda forma de resolver la LGD comparte: objetivo, piso y techo.

    No es una rama: es la base de la unión discriminada (D-LGD-1). Los tres campos viven aquí y no
    en cada rama porque ``_parse_rows`` los lee **incondicionalmente**
    (``internal/engine.py:261,266-267``), y con ``strict = true`` mypy sólo acepta ese acceso sobre
    una unión si **todas** sus ramas los declaran. No es una concesión al type checker: toda forma
    de obtener una severidad tiene objetivo, piso y techo.
    """

    lgd_col: str = Field(
        default="lgd",
        title="Columna LGD",
        description="Columna con la pérdida dado el incumplimiento observada por operación.",
        # `column_role` entra con las ramas modeladas (D-LGD-13) y no antes: hasta hoy TODA rama
        # leía esta columna, así que declararla inerte no era posible y el rol no habilitaba nada.
        # Ahora hay dos ramas que no la abren —recuperos nunca, y una regresión con la tasa de
        # recuperación informada—, y `columnas_inactivas()` sólo puede suprimir un campo que el
        # preflight inspeccione: sin rol, la supresión no suprimiría nada y la línea mentiría.
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "LGD",
            "ui_order": 2,
        },
    )
    lgd_floor: UnitInterval = Field(
        default=0.0,
        title="Piso de LGD",
        description="Piso explícito aplicado tras validar la LGD; nunca clipa un valor inválido.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LGD", "ui_order": 3},
    )
    lgd_cap: UnitInterval = Field(
        default=1.0,
        title="Techo de LGD",
        description="Techo explícito aplicado tras validar la LGD; nunca clipa un valor inválido.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LGD", "ui_order": 4},
    )

    @model_validator(mode="after")
    def _check_lgd(self) -> Self:
        """Valida columna no vacía y ``lgd_floor <= lgd_cap`` (SDD-28 §5.1)."""
        if not self.lgd_col.strip():
            raise InternalConfigError(
                "lgd.lgd_col no puede estar vacío.",
                loc=(*_LOC_SECCION, "lgd", "lgd_col"),  # D-EXI-5
            )
        # SIN `loc` a propósito (D-EXI-5): el piso y el techo se contradicen ENTRE SÍ y ninguno de
        # los dos es el equivocado, así que anclar en uno mandaría al usuario a un campo que
        # perfectamente puede ser el correcto.
        if self.lgd_floor > self.lgd_cap:
            raise InternalConfigError(
                f"lgd.lgd_floor ({self.lgd_floor}) no puede superar lgd.lgd_cap ({self.lgd_cap})."
            )
        return self


class InternalLgdProvided(_InternalLgdComun):
    """La severidad la trae el archivo y el grupo la resume ponderando por exposición."""

    method: Literal["provided"] = Field(
        default="provided",
        title="Método LGD",
        description=(
            "La LGD del grupo es la media de la columna PONDERADA POR EXPOSICIÓN, y en el detalle "
            "cada operación conserva la suya."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 1},
    )


class InternalLgdGroupHistorical(_InternalLgdComun):
    """La severidad la trae el archivo y el grupo la resume con una media simple."""

    method: Literal["group_historical"] = Field(
        default="group_historical",
        title="Método LGD",
        description=(
            "La LGD del grupo es la media SIMPLE (histórica) de la columna, y después se aplica "
            "igual a todas las operaciones del grupo."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 1},
    )


# ── Las tres formas MODELADAS: la severidad la ESTIMA el motor, no la trae el archivo ───────────
#
# Las dos ramas observadas de arriba resuelven la severidad DENTRO de `_parse_rows`, leyendo una
# celda. Estas tres delegan en `LgdEngine`, el mismo motor que usa IFRS 9, así que tienen que
# satisfacer su protocolo `LgdSpec` ENTERO — los once atributos, incluidos los que su propio
# enfoque no lee nunca.
#
# 🔴 **Cómo se satisface lo que la rama no usa: con `@property` inerte, no con un campo** (decisión
# del paso 4; las dos salidas evaluadas están en el §7 de la enmienda). Tres razones, ninguna de
# gusto:
#
# 1. **Es el precedente vivo.** `IfrsLgdConfig` —una clase plana— ya satisface el protocolo
#    publicando las cuatro columnas de recuperos como propiedades (`ifrs9/config.py:273-291`).
#    Partir el protocolo en dos obligaría a cambiar IFRS 9 sin ganar nada allí.
# 2. **Partir el protocolo metería en el sistema de tipos una decisión de RUNTIME.**
#    `LgdEngine.estimate` es una entrada ÚNICA que despacha sobre el *valor* de `method`
#    (`lgd.py:194-201`); con dos protocolos, `strict` exigiría estrechar un tipo *estático* dentro
#    de esa entrada, que es justo el acoplamiento que el protocolo estructural existe para evitar
#    («el motor no importa ninguna de las dos clases»).
# 3. **Una propiedad no entra al `model_dump`.** Un campo inerte sí: sería un control visible en el
#    formulario y escribible SIN EFECTO alguno — o sea exactamente la clase «campo declarado en una
#    rama inactiva» que esta unión acaba de cerrar de forma estructural. Hacerlo campo desharía el
#    motivo por el que se eligió la unión.
#
# 🔴 Y `recovery_col` NO vive en una base compartida, que fue el primer intento: es que SIGNIFICA
# COSAS DISTINTAS en cada rama. En las regresiones el motor calcula `LGD = 1 - recovery`, o sea una
# TASA en [0,1] (`lgd.py:203-210`, `:269-282`); en el enfoque de recuperos entra a
# `PV(recovery - cost)/EAD`, o sea un MONTO en la misma moneda que la exposición (`lgd.py:245-246`).
# Una descripción compartida sería falsa para una de las dos, y quien la creyera obtendría una
# severidad de 1,0 en toda su cartera SIN UN SOLO ERROR. Salió corriendo las cinco ramas de verdad;
# leyendo el código no se veía.


def _exigir_recovery_col_no_vacia(recovery_col: str | None) -> None:
    """Una cadena vacía no es «no la declaré»: es un config que el motor rechaza al ejecutarse.

    🔴 Y hace daño DOS veces, no una. Es la clase «opción que el config acepta y el motor rechaza»
    —el motor levanta ``LgdError`` buscando una columna llamada ``''``—, y además ``columnas_
    inactivas()`` decide por ``recovery_col is not None``, así que con ``''`` **suprime** el
    requisito de ``lgd_col`` en el preflight: le calla al usuario la única columna con la que su
    corrida podría haber funcionado.
    """
    if recovery_col is not None and not recovery_col.strip():
        raise InternalConfigError(
            "lgd.recovery_col no puede estar vacío: si no traes la recuperación, omite el campo "
            "en vez de dejarlo en blanco.",
            loc=(*_LOC_SECCION, "lgd", "recovery_col"),  # D-EXI-5
        )


class _InternalLgdRegresion(_InternalLgdComun):
    """Base de las dos formas que AJUSTAN un modelo de severidad sobre la propia cartera.

    ⚠️ El ajuste es **in-sample** (D-LGD-9): el motor ajusta y predice sobre las mismas filas
    (`lgd.py:258-267`). Es propiedad preexistente del motor —IFRS 9 la tiene hoy—, pero al ofrecerla
    en el motor que produce la cifra de provisión pasa a publicarse en la prosa del informe y en la
    traza de auditoría, en vez de vivir donde nadie la lee.
    """

    recovery_col: str | None = Field(
        default=None,
        title="Columna de tasa recuperada",
        description=(
            "Columna con el MONTO recuperado de cada operación, en la moneda de la exposición."
        ),
        json_schema_extra={
            "ui_help": (
                "Columna con el MONTO recuperado de cada operación, en la misma moneda que "
                "la exposición. No es una fracción: entra al valor presente que se divide "
                "por la exposición."
            ),
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "LGD",
            "ui_order": 5,
        },
    )
    covariate_cols: tuple[str, ...] = Field(
        default=(),
        title="Variables explicativas de la severidad",
        description=(
            "Columnas CRUDAS de tu archivo que explican la severidad. Nunca variables "
            "discretizadas del scorecard: ésas están codificadas contra el incumplimiento, que es "
            "otro objetivo."
        ),
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "multiselect",
            "ui_group": "LGD",
            "ui_order": 6,
        },
    )

    # ── Lo que una regresión NO lee: propiedades inertes que satisfacen el protocolo ────────────
    #
    # El motor sólo mira estos cinco atributos dentro de `_estimate_workout`/`_workout_rate`
    # (`lgd.py:212-256`), rama a la que una regresión no entra nunca. Van como propiedades por la
    # razón 3 del docstring de `_InternalLgdModelada`: un campo aquí sería un control que el
    # usuario puede mover sin que cambie una sola cifra.

    @property
    def workout_discount(self) -> str:
        """Inerte en las regresiones: el descuento sólo lo lee el enfoque de recuperos."""
        return "contractual"

    @property
    def workout_ead_col(self) -> str:
        """Inerte en las regresiones: sólo la lee el enfoque de recuperos."""
        return WORKOUT_EAD_COLUMN

    @property
    def workout_cost_col(self) -> str:
        """Inerte en las regresiones: sólo la lee el enfoque de recuperos."""
        return WORKOUT_COST_COLUMN

    @property
    def workout_time_col(self) -> str:
        """Inerte en las regresiones: sólo la lee el enfoque de recuperos."""
        return WORKOUT_TIME_COLUMN

    @property
    def workout_rate_col(self) -> str:
        """Inerte en las regresiones: sólo la lee el enfoque de recuperos."""
        return WORKOUT_RATE_COLUMN

    @model_validator(mode="after")
    def _check_regresion(self) -> Self:
        """Exige covariables no vacías: un ajuste sin variables explicativas no es un ajuste."""
        _exigir_recovery_col_no_vacia(self.recovery_col)
        vacias = [idx for idx, col in enumerate(self.covariate_cols) if not col.strip()]
        if vacias:
            raise InternalConfigError(
                f"lgd.covariate_cols no puede contener nombres vacíos: posiciones {vacias}.",
                loc=(*_LOC_SECCION, "lgd", "covariate_cols"),  # D-EXI-5
            )
        if not self.covariate_cols:
            raise InternalConfigError(
                "Modelar la severidad exige al menos una variable explicativa en "
                "lgd.covariate_cols.",
                # D-EXI-5: el error se ANCLA a su campo, para que el formulario pueda llevar ahí
                # al usuario en vez de dejarle un mensaje sin control. La ruta va absoluta desde la
                # raíz del config, y un gate exige que resuelva contra `NikodymConfig`.
                loc=(*_LOC_SECCION, "lgd", "covariate_cols"),
            )
        return self

    def columnas_inactivas(self) -> frozenset[str]:
        """La columna de LGD queda inerte cuando la recuperación viene informada (D-LGD-13).

        Mismo predicado que ``IfrsLgdConfig`` y por la misma razón medida: ``_regression_target``
        lee ``lgd_col`` **sólo si ``recovery_col is None``** (`lgd.py:269-282`). Dentro de una rama
        el ``method`` es constante, así que del condicional de IFRS 9 sólo sobrevive el predicado
        sobre el campo hermano.
        """
        return frozenset({"lgd_col"} if self.recovery_col is not None else set())


class InternalLgdBetaRegression(_InternalLgdRegresion):
    """La severidad se modela con una regresión beta sobre las variables que elijas."""

    method: Literal["beta_regression"] = Field(
        default="beta_regression",
        title="Método LGD",
        description=(
            "Ajusta una regresión BETA de la severidad sobre tus variables. Exige que la severidad "
            "observada esté ESTRICTAMENTE entre 0 y 1: una sola operación con recupero total o "
            "pérdida total detiene la corrida."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 1},
    )


class InternalLgdFractionalResponse(_InternalLgdRegresion):
    """La severidad se modela con una regresión fraccional, que admite los extremos 0 y 1."""

    method: Literal["fractional_response"] = Field(
        default="fractional_response",
        title="Método LGD",
        description=(
            "Ajusta una regresión FRACCIONAL de la severidad sobre tus variables. Admite "
            "operaciones con recupero total (0) y con pérdida total (1), que es lo normal en una "
            "cartera real."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 1},
    )


class InternalLgdWorkout(_InternalLgdComun):
    """La severidad se calcula descontando los recuperos y costos observados de cada operación.

    ⚠️ Sus tres insumos monetarios —lo recuperado, lo que costó recuperarlo y la exposición— van en
    la MISMA moneda y en montos, no en fracciones: el motor calcula
    ``1 - PV(recuperos - costos) / exposición`` (`lgd.py:245-246`). Es la diferencia con las ramas
    de regresión, donde la columna de recuperación es una tasa.
    """

    recovery_col: str | None = Field(
        default=None,
        title="Columna de monto recuperado",
        description=(
            "Columna con el MONTO recuperado de cada operación, en la moneda de la exposición."
        ),
        json_schema_extra={
            "ui_help": (
                "Columna con el MONTO recuperado de cada operación, en la misma moneda que la "
                "exposición. No es una fracción: entra al valor presente que se divide por la "
                "exposición."
            ),
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "LGD",
            "ui_order": 5,
        },
    )
    method: Literal["workout"] = Field(
        default="workout",
        title="Método LGD",
        description=(
            "Calcula la severidad como 1 menos el valor presente de lo recuperado neto de costos, "
            "dividido por la exposición. No ajusta ningún modelo: descuenta flujos observados."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 1},
    )
    workout_ead_col: str = Field(
        default=WORKOUT_EAD_COLUMN,
        title="Columna de exposición al incumplimiento",
        description="Columna por la que se divide el valor presente de lo recuperado.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "LGD",
            "ui_order": 6,
        },
    )
    workout_cost_col: str = Field(
        default=WORKOUT_COST_COLUMN,
        title="Columna de costos de recuperación",
        description=(
            "Columna con lo que costó recuperar. Si falta, la corrida se detiene: no se asume cero."
        ),
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "LGD",
            "ui_order": 7,
        },
    )
    workout_time_col: str = Field(
        default=WORKOUT_TIME_COLUMN,
        title="Columna de tiempo de recupero (años)",
        description="Columna con los años que tardó el recupero; es el exponente del descuento.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "LGD",
            "ui_order": 8,
        },
    )
    workout_rate_col: str = Field(
        default=WORKOUT_RATE_COLUMN,
        title="Columna de tasa de descuento",
        description="Columna con la tasa contractual a la que se descuentan los recuperos.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "LGD",
            "ui_order": 9,
        },
    )

    # ── Lo que el enfoque de recuperos NO lee ───────────────────────────────────────────────────

    @property
    def covariate_cols(self) -> tuple[str, ...]:
        """Inerte aquí: sólo las regresiones ajustan sobre covariables (`lgd.py:258-267`)."""
        return ()

    @property
    def workout_discount(self) -> str:
        """Fijo en `contractual`, y NO es un campo: el método interno no tiene concepto de EIR.

        🔴 Ofrecer `eir` sería publicar una opción que el motor rechaza al ejecutarse: el descuento
        a la tasa efectiva exige una serie de EIR por instrumento que sólo IFRS 9 produce y que
        `_severity_by_row` no puede pasar (`internal/engine.py`, la llamada va sin `eir=`). Es la
        clase de defecto que el abanico existe para impedir, la misma que `binning.solver='cp'`.
        Como propiedad, la opción **no existe** en vez de existir y morir.
        """
        return "contractual"

    @model_validator(mode="after")
    def _check_workout(self) -> Self:
        """Exige la columna de recuperación y nombres no vacíos en las cinco columnas que lee."""
        if self.recovery_col is None:
            raise InternalConfigError(
                "lgd.method='workout' exige recovery_col: sin lo recuperado no hay severidad que "
                "calcular.",
                loc=(*_LOC_SECCION, "lgd", "recovery_col"),  # D-EXI-5
            )
        _exigir_recovery_col_no_vacia(self.recovery_col)
        vacias = sorted(
            nombre
            for nombre in (
                "workout_ead_col",
                "workout_cost_col",
                "workout_time_col",
                "workout_rate_col",
            )
            if not str(getattr(self, nombre)).strip()
        )
        # SIN `loc` a propósito (D-EXI-5): el fallo acusa a UN CONJUNTO de columnas que sólo se
        # conoce en runtime, y el `loc` tiene que ser una ruta estática —el gate lo evalúa por AST—.
        # Anclar en la primera de la lista escondería las otras tres detrás de un solo campo.
        if vacias:
            raise InternalConfigError(f"lgd: estas columnas no pueden estar vacías: {vacias}.")
        return self

    def columnas_inactivas(self) -> frozenset[str]:
        """``lgd_col`` es SIEMPRE inerte aquí (D-LGD-13).

        El enfoque de recuperos no la lee en ninguna rama del motor —``_estimate_workout``
        (`lgd.py:212-247`) no la toca— y su validador ya exige ``recovery_col``, así que el
        predicado no depende de ningún hermano: es incondicional.
        """
        return frozenset({"lgd_col"})


#: La LGD del método interno se contesta ELIGIENDO UNA FORMA, no rellenando un campo (D-LGD-1).
#:
#: 🔴 La forma no es estética: es lo único que permite añadir formas nuevas —una severidad
#: MODELADA, con sus covariables— **sin mover la identidad**. Medido añadiendo una rama de verdad:
#: con una clase plana, un campo nuevo mueve el `config_hash` de F3 (857b06ee→31980950) y de F5, y
#: el de F3 está impreso dentro de la demo publicada, sin ningún gate que cruce las dos cosas. Con
#: la unión, los cuatro presets quedan byte a byte iguales. Mismo hecho que D-COL midió en su día
#: para `PartitionStrategy`.
#:
#: ⚠️ Efecto lateral que vale por sí solo: cierra ESTRUCTURALMENTE la clase «campo declarado en una
#: rama inactiva». Con una clase plana, las covariables de una regresión existirían —vacías y
#: mudas— para quien eligió `provided`; aquí no existen en ese config.
#:
#: ⚠️ El campo que la contiene NO declara `ui_widget`, y es a propósito: ver la nota en
#: `InternalProvisioningConfig.lgd`.
#: ⚠️ Las tres formas MODELADAS entran aquí y NO mueven la identidad de ningún preset: una rama
#: nueva de una unión discriminada no toca el `model_dump` de las ramas existentes, que es lo que
#: D-COL midió en su día para `PartitionStrategy` y lo que se volvió a medir aquí con los cuatro
#: `config_hash` como control negativo.
InternalLgdConfig = Annotated[
    InternalLgdProvided
    | InternalLgdGroupHistorical
    | InternalLgdBetaRegression
    | InternalLgdFractionalResponse
    | InternalLgdWorkout,
    Field(discriminator="method"),
]

#: Las tres ramas cuya severidad la produce :class:`~nikodym.provisioning.lgd.LgdEngine`.
#:
#: Es unión de clases CONCRETAS y no de la base común, porque el ``isinstance`` que la consume
#: (`internal/engine.py::_lgd_modelada`) tiene que estrechar a algo que mypy pueda comprobar contra
#: ``LgdSpec``: una base sin ``method`` ni atributos de recuperos no lo satisface por sí sola.
InternalLgdModelada = InternalLgdBetaRegression | InternalLgdFractionalResponse | InternalLgdWorkout


class InternalProvisioningConfig(NikodymBaseConfig):
    """Calcula las provisiones del método interno del banco por grupo homogéneo.

    Motor experimental: fuera de la garantía SemVer 1.x.
    """

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema provisioning_internal",
        description="Versión local del schema del método interno para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección provisioning_internal",
        description="Variante de la sección del método interno; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    as_of_date_col: str = Field(
        default="as_of_date",
        title="Fecha de cálculo",
        description="Columna con la fecha de cierre contable; debe traer un valor único.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 1,
        },
    )
    portfolio_col: str = Field(
        # D-JUR-8: el default deja de ser chileno. Este motor es jurisdiccionalmente neutro y su
        # estado de fábrica no puede pedir una columna con el nombre de un supervisor: el default
        # anterior ("cmf_portfolio") obligaba a un banco de cualquier otro país a renombrar su
        # columna para correr un cálculo que no conoce ninguna norma.
        # Se elige "portfolio" y no un nombre nuevo porque es el único candidato con precedente en
        # el repo: `ifrs9/config.py` ya lo usa como default de su propio `portfolio_col`, también
        # con `column_role: "input"`. La objeción escrita en D-SEG-9 —que "portfolio" es el nombre
        # de la columna de SALIDA del `detail`— ya está tolerada ahí, y alinear los dos motores
        # neutros pesa más que evitar una homonimia que el crosswalk resuelve por otro eje.
        # ⚠️ Ya NO coincide con el default del método estándar (cmf/config.py), y eso es
        # deliberado: ver la nota de D-SEG-9 allí.
        default="portfolio",
        title="Cartera",
        description=(
            "Columna con la cartera de cada exposición, en la taxonomía que use su institución. "
            "Debe ser la misma que consuma el método estándar con el que se compare."
        ),
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 2,
        },
    )
    portfolio_scheme: str | None = Field(
        default=None,
        title="Esquema de carteras",
        description=("Identificador de la taxonomía de carteras que usa la columna anterior."),
        json_schema_extra={
            "ui_help": (
                "Identificador de la taxonomía de carteras que usa la columna anterior. "
                "Declararlo permite comparar contra otro motor sin mapeo cuando ambos usan la "
                "misma taxonomía; si se omite, la comparación exige un mapeo explícito entre "
                "taxonomías."
            ),
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 21,
        },
    )
    exposure_col: str = Field(
        default="exposure_amount",
        title="Exposición",
        description="Columna con el monto de colocaciones; la misma exposición que ve el estándar.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 3,
        },
    )
    pd_source: InternalPdSourceDomain = Field(
        default="calibration",
        title="Fuente de PD",
        description=(
            "Dominio del artefacto de PD: calibration (PD calibrada, que es la que pide un "
            "cálculo de provisiones) o model (PD cruda del modelo)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "PD", "ui_order": 1},
    )
    # Vive en el frame de PD que produce otro paso, no en el archivo del usuario.
    pd_column: str = Field(
        default="pd_calibrated",
        title="Columna PD",
        description="Columna de PD dentro del artefacto de la fuente declarada en pd_source.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "PD",
            "ui_order": 2,
        },
    )
    grouping: InternalGroupingMethod = Field(
        default="score_band",
        title="Formación de grupos homogéneos",
        description=(
            "score_band: bandas por cuantil de PD dentro de cada cartera. "
            "segment/provided: grupos leídos de group_col (segmento de negocio o grupo ya formado)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Grupos", "ui_order": 1},
    )
    group_col: str | None = Field(
        default=None,
        title="Columna de grupo",
        description="Columna con el grupo homogéneo; obligatoria con grouping segment o provided.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Grupos",
            "ui_order": 2,
        },
    )
    n_score_bands: int = Field(
        default=10,
        ge=2,
        title="Número de bandas de score",
        description="Cantidad de bandas por cuantil de PD; solo aplica con grouping='score_band'.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Grupos", "ui_order": 3},
    )
    lgd: InternalLgdConfig = Field(
        default_factory=InternalLgdProvided,
        # El título ya no rotula un grupo sino el SELECTOR de la forma, que es lo que el
        # usuario lee: repetir «LGD» debajo del grupo «LGD» era el «Documento / Documento» que
        # este repo ya corrigió una vez.
        title="Cómo se obtiene la LGD",
        description="Configuración de la pérdida dado el incumplimiento del grupo homogéneo.",
        # 🔴 SIN `ui_widget`, y no es un olvido (D-LGD-1-bis). En `form-engine.ts` el alias
        # del campo gana ANTES de que se mire el discriminador, y `section` mapea a `group`,
        # que sobre una unión no encuentra `properties` y pinta el fieldset «Sin campos.» — el
        # defecto exacto que ese archivo ya documenta para `binning.variable_overrides`. El
        # precedente vivo de una unión en el formulario, `PartitionConfig.strategy`, declara
        # `ui_help` y ningún widget.
        json_schema_extra={
            "ui_help": (
                "Cómo se obtiene la severidad de cada grupo homogéneo: resumiendo la que trae tu "
                "archivo, o modelándola."
            ),
            "ui_group": "LGD",
            "ui_order": 1,
        },
    )
    method: InternalProvisioningMethod = Field(
        default="pd_lgd",
        title="Método de cálculo",
        description=(
            "pd_lgd: Exposición · PD · LGD por grupo. direct_loss_rate: tasa de pérdida esperada "
            "del grupo tomada directamente de loss_rate_col, sin descomponer."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Método", "ui_order": 1},
    )
    loss_rate_col: str | None = Field(
        default=None,
        title="Columna de tasa de pérdida",
        description=(
            "Columna con la pérdida esperada por unidad de exposición; exige direct_loss_rate."
        ),
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Método",
            "ui_order": 2,
        },
    )
    rounding: InternalRoundingPolicy = Field(
        default="currency_2dp",
        title="Redondeo de provisión",
        description="Política explícita de redondeo contable de la provisión publicada.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Método", "ui_order": 3},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante falta de dato",
        description=(
            "Activado: un nulo en exposición, PD, LGD o tasa de pérdida detiene la corrida con "
            "error. Desactivado: se imputa cero, la operación queda marcada como falta de dato y "
            "el resultado "
            "lo deja trazado."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Método", "ui_order": 4},
    )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida columnas no vacías y las dependencias cruzadas de SDD-28 §5.1.

        Un enum declarado sin ruta real degrada en silencio: por eso ``group_col`` y
        ``loss_rate_col`` son obligatorias cuando el modo las lee, y **prohibidas** cuando no las
        lee (una columna declarada que el motor nunca abre es una mentira del config).
        """
        _require_non_empty_strings(
            {field: getattr(self, field) for field in _ROOT_COLUMN_FIELDS},
            context="provisioning_internal",
        )
        # Los cuatro `raise` de aquí anclan en la COLUMNA y no en el modo (D-EXI-5), igual que el
        # precedente «lgd.method='workout' exige recovery_col»: en los dos primeros la columna es lo
        # que falta, y en los dos segundos es lo que sobra —el modo elegido nunca la abre, así que
        # una columna declarada ahí es una mentira del config y ES el campo que hay que vaciar—.
        if self.grouping in _GROUP_COL_GROUPINGS:
            if self.group_col is None or not self.group_col.strip():
                raise InternalConfigError(
                    f"grouping='{self.grouping}' exige group_col con el nombre de la columna "
                    "que trae el grupo homogéneo.",
                    loc=(*_LOC_SECCION, "group_col"),
                )
        elif self.group_col is not None:
            raise InternalConfigError(
                "grouping='score_band' forma los grupos desde la PD y nunca lee group_col: "
                "elimine group_col o cambie grouping a 'segment'/'provided'.",
                loc=(*_LOC_SECCION, "group_col"),
            )
        if self.method == "direct_loss_rate":
            if self.loss_rate_col is None or not self.loss_rate_col.strip():
                raise InternalConfigError(
                    "method='direct_loss_rate' exige loss_rate_col con la tasa de pérdida "
                    "esperada por operación.",
                    loc=(*_LOC_SECCION, "loss_rate_col"),
                )
        elif self.loss_rate_col is not None:
            raise InternalConfigError(
                "method='pd_lgd' descompone la pérdida en PD y LGD y nunca lee loss_rate_col: "
                "elimine loss_rate_col o cambie method a 'direct_loss_rate'.",
                loc=(*_LOC_SECCION, "loss_rate_col"),
            )
        return self

    def columnas_inactivas(self) -> frozenset[str]:
        """Con la tasa de pérdida directa, la subsección de LGD entera queda inerte (D-SUB-2).

        🔴 Vive aquí y no en las ramas de LGD porque **aquí está la condición**: el que decide si la
        severidad se descompone es ``method``, un campo de esta clase, y una rama no ve a su padre —
        ni debe—. Con ``direct_loss_rate`` el motor toma la tasa de ``loss_rate_col`` y no abre una
        sola columna de ``lgd`` (`internal/engine.py:279-281` y `:322`), así que exigirlas era rojo
        en pantalla sobre un config que corre bien: hasta **cinco** columnas con el enfoque de
        recuperos.

        Es lo que D-SUB-1 hizo expresable: al podar el subárbol, nombrar el submodelo basta.
        """
        return frozenset() if self.method == "pd_lgd" else frozenset({"lgd"})

    def requisitos_incumplidos(self, columnas: frozenset[str] | None) -> tuple[Requisito, ...]:
        """Avisa cuando el dataset trae DOS columnas de cartera y nadie eligió una (D-AMB-2).

        🔴 D-JUR-8 movió el default de ``portfolio_col`` de ``"cmf_portfolio"`` a ``"portfolio"``
        porque un motor neutro no puede pedir de fábrica la columna de un supervisor. Si el
        archivo trae **sólo** el nombre antiguo, la corrida muere con un error legible y todo
        bien. El caso que nadie veía es el otro: un archivo con **las dos** columnas cambia de
        agrupación en silencio —medido, 20 grupos y 840.182,29 pasan a 10 grupos y 839.451,51, con
        ``ok``, cero errores y cero avisos—, y ``check_dataset`` da ``compatible=True`` porque la
        columna que el config nombra existe de verdad. No estaba fallando: contestaba bien a otra
        pregunta.

        ⚠️ El caso no es de laboratorio: ``"portfolio"`` es también el default de
        ``provisioning_ifrs9.portfolio_col``, así que quien corre IFRS 9 **y** provisión interna
        sobre un mismo panel tiene las dos columnas por construcción.

        La ambigüedad es propiedad del **par** (config, dataset), no del config, y por eso vive
        aquí y no en ``_check_invariantes``. Avisa, no bloquea (D-AMB-4, sigue D-INV-3/D-PRE-5):
        elegir ``portfolio`` puede ser exactamente lo que el usuario quiere; lo que no puede es que
        nadie se lo haya dicho.
        """
        # Quien DECLARÓ la columna ya tomó la decisión: avisarle sería el aviso que se aprende a
        # ignorar (D-AMB-2, condición 1). Y sin los nombres no se afirma nada (D-INV-4).
        if "portfolio_col" in self.model_fields_set or columnas is None:
            return ()
        if not columnas >= _COLUMNAS_CARTERA_AMBIGUAS:
            return ()
        otra = next(iter(_COLUMNAS_CARTERA_AMBIGUAS - {self.portfolio_col}), "")
        return (
            Requisito(
                path="portfolio_col",
                declared=self.portfolio_col,
                # Copy público: sin código interno y sin nombrar ninguna norma. `cmf_portfolio`
                # aparece aquí como el nombre de una columna del archivo del usuario, nada más.
                message=(
                    f"Su archivo trae dos columnas que podrían ser la cartera: "
                    f"«{self.portfolio_col}» y «{otra}». La corrida usará "
                    f"«{self.portfolio_col}», que es el valor de fábrica y no una elección suya. "
                    f"Si la cartera es «{otra}», declárela en este campo: la agrupación de los "
                    "grupos homogéneos —y con ella la provisión— depende de cuál se use."
                ),
            ),
        )


def _require_non_empty_strings(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas declarativos no sean vacíos.

    SIN ``loc`` a propósito (D-EXI-5): acusa a un CONJUNTO de campos que sólo se conoce en runtime
    —hasta los cuatro de ``_ROOT_COLUMN_FIELDS``—, y el ``loc`` tiene que ser una ruta estática
    porque el gate lo evalúa por AST. Anclar en el primero escondería a los demás.
    """
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise InternalConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")
