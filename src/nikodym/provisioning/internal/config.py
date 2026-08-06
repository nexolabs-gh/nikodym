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

InternalPdSourceDomain = Literal["calibration", "model"]
InternalGroupingMethod = Literal["score_band", "segment", "provided"]
InternalLgdMethod = Literal["provided", "group_historical"]
InternalProvisioningMethod = Literal["pd_lgd", "direct_loss_rate"]
InternalRoundingPolicy = Literal["none", "currency_2dp", "integer_currency"]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]

__all__ = [
    "InternalGroupingMethod",
    "InternalLgdConfig",
    "InternalLgdGroupHistorical",
    "InternalLgdMethod",
    "InternalLgdProvided",
    "InternalPdSourceDomain",
    "InternalProvisioningConfig",
    "InternalProvisioningMethod",
    "InternalRoundingPolicy",
]

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
        json_schema_extra={"ui_widget": "text_input", "ui_group": "LGD", "ui_order": 2},
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
            raise InternalConfigError("lgd.lgd_col no puede estar vacío.")
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
InternalLgdConfig = Annotated[
    InternalLgdProvided | InternalLgdGroupHistorical,
    Field(discriminator="method"),
]


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
        description=(
            "Identificador de la taxonomía de carteras que usa la columna anterior. Declararlo "
            "permite comparar contra otro motor sin mapeo cuando ambos usan la misma taxonomía; "
            "si se omite, la comparación exige un mapeo explícito entre taxonomías."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 21},
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
        description="Columna con la pérdida esperada por peso expuesto; exige direct_loss_rate.",
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
        if self.grouping in _GROUP_COL_GROUPINGS:
            if self.group_col is None or not self.group_col.strip():
                raise InternalConfigError(
                    f"grouping='{self.grouping}' exige group_col con el nombre de la columna "
                    "que trae el grupo homogéneo."
                )
        elif self.group_col is not None:
            raise InternalConfigError(
                "grouping='score_band' forma los grupos desde la PD y nunca lee group_col: "
                "elimine group_col o cambie grouping a 'segment'/'provided'."
            )
        if self.method == "direct_loss_rate":
            if self.loss_rate_col is None or not self.loss_rate_col.strip():
                raise InternalConfigError(
                    "method='direct_loss_rate' exige loss_rate_col con la tasa de pérdida "
                    "esperada por operación."
                )
        elif self.loss_rate_col is not None:
            raise InternalConfigError(
                "method='pd_lgd' descompone la pérdida en PD y LGD y nunca lee loss_rate_col: "
                "elimine loss_rate_col o cambie method a 'direct_loss_rate'."
            )
        return self

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
    """Valida que los nombres de columnas declarativos no sean vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise InternalConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")
