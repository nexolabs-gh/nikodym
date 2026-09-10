"""Config declarativo de la capa ``validation`` (SDD-22 §5).

:class:`ValidationConfig` es la sección ``validation`` de
:class:`~nikodym.core.config.NikodymConfig`: la **validación formal** de un modelo del repo, que
consolida la discriminación (reúso de SDD-11), la estabilidad (reúso de SDD-11) y **añade** la
calibración (Hosmer-Lemeshow, binomial/Jeffreys por grado, Brier, semáforo) y el backtesting
realizado-vs-estimado (t-test LGD/EAD, binomial/Jeffreys PD). Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config.

La sección es **computacional, no infraestructura** (``validation`` ∉ ``INFRA_SECTIONS``): cambiar
las familias activas, el nº de deciles Hosmer-Lemeshow, el nivel de significancia, las bandas del
semáforo o el test de PD/LGD/EAD **cambia el ``config_hash`` global**. Al cablear B22.1 se mueve
``GOLDEN_DEFAULT_CONFIG_HASH`` (mismo precedente que ``provisioning_ifrs9``/``provisioning``).

Frontera B22.1: aquí solo viven el schema y sus validaciones determinables sin datos. La *presencia*
de artefactos/columnas aguas arriba es un contrato de runtime que valida el evaluador/step en
bloques posteriores (§6/§8), de modo que ``ValidationConfig()`` siga construyendo sin argumentos.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Literal, Self, get_args

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.dataset_check import Requisito
from nikodym.validation.exceptions import ValidationConfigError

ValidationFamily = Literal["discrimination", "calibration", "stability", "backtesting"]
DiscriminationPartition = Literal["desarrollo", "holdout", "oot"]
HlGrouping = Literal["deciles", "fixed_bands"]
PdTest = Literal["binomial", "jeffreys"]
BacktestParameter = Literal["pd", "lgd", "ead"]

__all__ = [
    "BacktestParameter",
    "BacktestingValidationConfig",
    "CalibrationValidationConfig",
    "DiscriminationPartition",
    "DiscriminationValidationConfig",
    "HlGrouping",
    "PdTest",
    "StabilityValidationConfig",
    "ValidationConfig",
    "ValidationFamily",
]


#: Qué columna realizada exige cada parámetro del backtesting (``evaluator.py``, §8 de SDD-22).
#:
#: Vive aquí y no dentro del método porque es el mapa que ata `parameters` con sus tres campos, y
#: un gate lo compara contra los `Literal` de :data:`BacktestParameter`: un parámetro nuevo sin su
#: columna dejaría `columnas_inactivas()` suprimiendo una columna que el motor sí abre, que es el
#: modo de fallo caro de D-RAM-3.
_COLUMNA_REALIZADA_POR_PARAMETRO: dict[str, str] = {
    "pd": "realised_pd_col",
    "lgd": "realised_lgd_col",
    "ead": "realised_ead_col",
}

#: Prefijo de la ruta de este dominio en ``NikodymConfig``, para anclar sus errores (D-EXI-5).
#: Vive en UN solo sitio y no repetido en cada ``raise``: la ruta que el error declara es
#: **absoluta desde la raíz del config**, así que ata al dominio con el nombre de su campo en la
#: raíz, y concentrarla aquí deja un único lugar donde ese acoplamiento puede quedarse stale.
_LOC_SECCION: tuple[str, ...] = ("validation",)


def _require_non_empty(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas declarativos no queden vacíos.

    D-EXI-5: su ``raise`` va **sin** ``loc``. El ofensor es cualquiera de las columnas que le pasa
    el llamador —y son dos subsecciones distintas, ``calibration`` y ``backtesting``— y el mensaje
    las enumera **todas**, así que no hay un campo único al que llevar al usuario. Pasar la ruta
    desde el llamador tampoco sirve: el gate que las vigila las evalúa **estáticamente** y sólo
    admite una tupla literal en el propio ``raise``.
    """
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise ValidationConfigError(f"Las columnas de {context} no pueden estar vacías: {empty}.")


def _require_no_collision(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas declarativos no colisionen entre sí.

    D-EXI-5: su ``raise`` va **sin** ``loc``, por partida doble. Es un invariante ENTRE campos
    —dos columnas con el mismo nombre, y cualquiera de las dos deshace la colisión— y además el
    helper lo comparten dos subsecciones, así que ni siquiera el prefijo sería único.
    """
    normalizadas: dict[str, str] = {}
    duplicadas: list[tuple[str, str, str]] = []
    for nombre, columna in values.items():
        clave = columna.strip()
        previo = normalizadas.get(clave)
        if previo is not None:
            duplicadas.append((previo, nombre, clave))
        normalizadas[clave] = nombre
    if duplicadas:
        raise ValidationConfigError(
            f"Las columnas de {context} no pueden colisionar: {duplicadas}."
        )


class DiscriminationValidationConfig(NikodymBaseConfig):
    """Reporta la discriminación (AUC, Gini, KS) con el motor de la etapa de desempeño."""

    consume_performance: bool = Field(
        default=True,
        title="Reusar las métricas de discriminación ya calculadas",
        description=(
            "Reutiliza el AUC, el Gini y el KS que ya calculó la etapa de desempeño. Apagado, "
            "los vuelve a calcular con el mismo motor, nunca con otra fórmula."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Discriminación", "ui_order": 1},
    )
    partitions: tuple[DiscriminationPartition, ...] = Field(
        default=("desarrollo", "holdout", "oot"),
        title="Particiones a validar",
        description=(
            "Sobre qué particiones se reporta la discriminación: desarrollo, holdout y fuera "
            "de tiempo."
        ),
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Discriminación", "ui_order": 2},
    )


class CalibrationValidationConfig(NikodymBaseConfig):
    """Mide la calibración: Hosmer-Lemeshow, binomial/Jeffreys, Brier score y semáforo."""

    hosmer_lemeshow: bool = Field(
        default=True,
        title="Ejecutar Hosmer-Lemeshow",
        description=(
            "Comprueba con la prueba de Hosmer-Lemeshow que la PD predicha coincide con la "
            "observada, por grupos de PD."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Calibración", "ui_order": 1},
    )
    hl_n_groups: int = Field(
        default=10,
        ge=5,
        le=20,
        title="Nº de grupos HL (deciles)",
        description=(
            "En cuántos grupos de PD se parte la cartera para la prueba de Hosmer-Lemeshow. "
            "La convención estándar es diez."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Calibración", "ui_order": 2},
    )
    # D-SUB (D-SC-7): oculto. De sus dos valores, `_check_calibration` rechaza `fixed_bands`
    # —«no soportado: exige bandas declaradas»—, así que en pantalla sería un selector con una
    # sola opción usable: una subsección inerte cuyo otro valor sólo produce un error. Se expone
    # cuando las bandas fijas existan, con el gate de su rama.
    hl_grouping: HlGrouping = Field(
        default="deciles",
        title="Criterio de agrupación HL",
        description="Agrupación del Hosmer-Lemeshow; las bandas fijas están reservadas.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Calibración", "ui_order": 3},
    )
    brier: bool = Field(
        default=True,
        title="Calcular Brier score",
        description=(
            "Calcula el puntaje de Brier por partición: el error cuadrático medio entre la PD "
            "predicha y lo que ocurrió. Más bajo es mejor."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Calibración", "ui_order": 3},
    )
    binomial_by_grade: bool = Field(
        default=True,
        title="Test binomial/Jeffreys por grado",
        description=(
            "Contrasta, grado por grado, si los incumplimientos observados caben en la PD "
            "estimada. Exige una columna de grado de rating en tu archivo. Los cortes del "
            "semáforo y la convención exacta de la prueba están declarados como brecha del "
            "motor: el resultado sale con ese aviso."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Calibración", "ui_order": 4},
    )
    grade_col: str = Field(
        default="grade",
        title="Columna de grado de rating",
        description="La columna de tu archivo con el grado de rating de cada operación.",
        json_schema_extra={
            # La aporta el usuario, así que el preflight la reclama ANTES de correr — pero sólo
            # cuando esta rama corre: `columnas_inactivas()` la declara inerte con el contraste
            # por grado apagado, que es como la traen el preset F1 y los dos trabajos (D-RAM-1).
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 5,
        },
    )
    pd_test: PdTest = Field(
        default="jeffreys",
        title="Test de PD por grado",
        description=(
            "Qué prueba se usa por grado: la de Jeffreys, que se comporta bien cuando un grado "
            "no tiene incumplimientos, o la binomial clásica."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Calibración", "ui_order": 6},
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=0.5,
        title="Nivel de significancia",
        description=(
            "Nivel de significancia de las pruebas de calibración. Cinco por ciento es el estándar."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Calibración", "ui_order": 7},
    )
    traffic_light_green_alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        title="Corte verde/ámbar (p-valor)",
        description="Por encima de este p-valor el grado queda en verde; por debajo, en ámbar.",
        json_schema_extra={
            "ui_help": (
                "Por encima de este p-valor el grado queda en verde; por debajo, en ámbar. Es un "
                "default institucional, no un umbral fijado por norma: fíjelo según su "
                "política de validación."
            ),
            "ui_widget": "number_input",
            "ui_group": "Semáforo",
            "ui_order": 8,
        },
    )
    traffic_light_red_alpha: float = Field(
        default=0.01,
        gt=0.0,
        lt=1.0,
        title="Corte ámbar/rojo (p-valor)",
        description=(
            "Por debajo de este p-valor el grado queda en rojo. Tiene que ser menor que el corte "
            "del verde."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Semáforo", "ui_order": 9},
    )
    # 🔴 D-SUB (D-SC-7): las tres pasan a ocultas, y NO por ser internas sino por ser INERTES en
    # el formulario. Nombran columnas de `calibration.calibrated_pd_frame`, el artefacto que el
    # propio motor produce con nombres fijos —`target`, `pd_calibrated`, `partition`—, así que
    # ningún otro valor corre desde una corrida por formulario: escribirlo sólo produce «El frame
    # de calibración requiere la columna …». Tampoco llevan `column_role`: no las aporta el
    # usuario, y reclamárselas sería un aviso falso.
    #
    # ⚠️ Su reverso, medido en la capa 2: por eso `validation` NO entra a «Validar un modelo
    # existente». En ese trabajo la PD entra por la puerta de artefactos con las columnas que el
    # usuario les puso y el backend NO las renombra (`ui/routes.py::_materializar_externos`), así
    # que la validación formal exigiría justo estos tres campos — y están ocultos. El DAG sí
    # resuelve (medido con `check_pipeline`); lo que no hay es dónde nombrar esas columnas.
    target_column: str = Field(
        default="target",
        title="Columna target binario",
        description="Columna con el resultado binario del artefacto interno de PD calibrada.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Columnas", "ui_order": 2},
    )
    pd_column: str = Field(
        default="pd_calibrated",
        title="Columna PD calibrada",
        description="Columna con la PD calibrada del artefacto interno que produce el motor.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Columnas", "ui_order": 3},
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna de partición del artefacto interno de PD calibrada.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Columnas", "ui_order": 4},
    )
    min_rows_per_group: int = Field(
        default=30,
        ge=1,
        title="Mínimo de operaciones para evaluar",
        description=(
            "Mínimo de operaciones para evaluar: bajo ese mínimo no hay prueba y el resultado "
            "queda marcado como no evaluado."
        ),
        json_schema_extra={
            "ui_help": (
                "Mínimo de operaciones para evaluar: una partición entera con menos que esto no "
                "recibe la prueba de Hosmer-Lemeshow, y un grado de rating con menos que esto no "
                "recibe el test por grado. Quedan marcados como no evaluados en vez de dar un "
                "número engañoso. No se aplica a cada grupo de PD dentro de la prueba de "
                "Hosmer-Lemeshow."
            ),
            "ui_widget": "number_input",
            "ui_group": "Calibración",
            "ui_order": 10,
        },
    )

    @model_validator(mode="after")
    def _check_calibration(self) -> Self:
        """Valida columnas, semáforo y la agrupación HL de SDD-22 §5."""
        columns = {
            "grade_col": self.grade_col,
            "pd_column": self.pd_column,
            "target_column": self.target_column,
            "partition_column": self.partition_column,
        }
        _require_non_empty(columns, context="calibration")
        _require_no_collision(columns, context="calibration")
        if self.traffic_light_red_alpha >= self.traffic_light_green_alpha:
            # D-EXI-5: SIN `loc` a propósito. Es un invariante ENTRE los dos cortes del semáforo:
            # se arregla bajando uno o subiendo el otro, y cuál de los dos está mal es política de
            # validación del usuario, no algo que el motor pueda decidir por él.
            raise ValidationConfigError(
                "traffic_light_red_alpha debe ser estrictamente menor que "
                "traffic_light_green_alpha (rojo más estricto que ámbar)."
            )
        if self.hl_grouping == "fixed_bands":
            raise ValidationConfigError(
                "hl_grouping='fixed_bands' aún no está soportado: exige bandas declaradas "
                "(reservado; use el default 'deciles').",
                # D-EXI-5: el valor inválido es el de ESTE campo. Desde que el campo es `hidden`
                # (D-SUB, D-SC-7) el formulario ya no puede llevar a nadie ahí —no lo pinta—, pero
                # el ancla sigue siendo la correcta para quien escribe el YAML por código, que es
                # el único camino que hoy alcanza este error.
                loc=(*_LOC_SECCION, "calibration", "hl_grouping"),
            )
        return self

    def columnas_inactivas(self) -> frozenset[str]:
        """La columna de grado sólo se lee con el contraste por grado encendido (D-RAM-1).

        Medido en `evaluator.py::_grade_records`: sale por `if not calib.binomial_by_grade` antes
        de tocar el frame, y ninguna otra rama de la calibración mira `grade_col`. Sin esta
        declaración, darle `column_role` habría hecho que el preflight reclamara «grade» en el
        preset F1 y en los dos trabajos del scorecard, que traen el contraste apagado — el falso
        positivo exacto que D-RAM-1 cierra.

        Las otras tres columnas de esta subsección no entran: no llevan rol, porque nombran el
        artefacto que produce el motor y no el archivo del usuario (ver su comentario).
        """
        return frozenset() if self.binomial_by_grade else frozenset({"grade_col"})


class StabilityValidationConfig(NikodymBaseConfig):
    """Reporta el PSI con el mismo motor de la etapa de estabilidad."""

    # 🔴 D-SUB (D-SC-7): oculto porque apagarlo ABORTA la corrida, no porque sea interno.
    # Medido: `ValidationStep.execute` pasa la PD calibrada, las métricas de desempeño y las de
    # estabilidad, pero nunca el frame de estabilidad, y el recálculo lo exige — así que el único
    # valor que corre desde el formulario es el encendido. Se expone cuando ese cableado exista,
    # con su gate de filas `source="recomputed"`.
    consume_stability: bool = Field(
        default=True,
        title="Reusar el PSI ya calculado",
        description="Toma el PSI que ya calculó la etapa de estabilidad.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Estabilidad", "ui_order": 1},
    )
    psi_stable_threshold: float = Field(
        default=0.10,
        ge=0.0,
        title="Umbral PSI de revisión",
        description=(
            "Por debajo de este PSI la población se considera estable; desde este valor entra en "
            "la banda de revisión."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Estabilidad", "ui_order": 2},
    )
    psi_review_threshold: float = Field(
        default=0.25,
        ge=0.0,
        title="Umbral PSI de redesarrollo",
        description=(
            "Desde este PSI la banda es la de redesarrollo. Tiene que ser mayor que el umbral de "
            "revisión."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Estabilidad", "ui_order": 3},
    )

    @model_validator(mode="after")
    def _check_stability(self) -> Self:
        """Valida el orden de las bandas PSI de SDD-22 §5."""
        if self.psi_stable_threshold >= self.psi_review_threshold:
            # D-EXI-5: SIN `loc` a propósito. Es un invariante ENTRE dos umbrales: se arregla
            # bajando uno o subiendo el otro, y cuál de los dos está mal lo sabe el usuario y no
            # el motor. Anclar en uno le escondería la mitad de la decisión.
            raise ValidationConfigError(
                "psi_stable_threshold debe ser estrictamente menor que psi_review_threshold."
            )
        return self


class BacktestingValidationConfig(NikodymBaseConfig):
    """Contrasta lo realizado contra lo estimado en IFRS 9 (LGD/EAD y PD)."""

    enabled: bool = Field(
        default=False,
        title="Ejecutar backtesting IFRS 9",
        description=(
            "Compara lo estimado por IFRS 9 con lo que de verdad ocurrió. Exige que la corrida "
            "calcule IFRS 9 y que tu archivo traiga las columnas con el resultado realizado. La "
            "forma exacta de la prueba de severidad y exposición está declarada como brecha del "
            "motor: el resultado sale con ese aviso."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Backtesting", "ui_order": 1},
    )
    parameters: tuple[BacktestParameter, ...] = Field(
        default=("pd", "lgd", "ead"),
        title="Parámetros a backtestear",
        description="Qué parámetros se contrastan: la PD, la severidad o la exposición.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Backtesting", "ui_order": 2},
    )
    # 🔴 D-SUB (D-SC-7): oculta, y sin `column_role`, porque NO es una columna del archivo del
    # usuario. El evaluador la lee del lado estimado —el detalle de IFRS 9—, y ese motor publica
    # siempre esa columna como `portfolio` aunque la entrada se llame de otro modo por
    # `provisioning_ifrs9.portfolio_col`. Un rol de entrada habría dado un aviso falso con una
    # cartera renombrada, y renombrar este campo para callarlo habría roto el consumo del
    # artefacto.
    segment_col: str = Field(
        default="portfolio",
        title="Segmento de agregación",
        description="Columna de segmento del detalle IFRS 9 sobre la que se agrega el backtesting.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Columnas", "ui_order": 1},
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=0.5,
        title="Nivel de significancia",
        description="Nivel de significancia de las pruebas de backtesting.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Backtesting", "ui_order": 6},
    )
    one_sided: bool = Field(
        default=True,
        title="Contraste unilateral (subestimación)",
        description=(
            "Para la severidad y la exposición: prueba sólo si el parámetro se subestimó, que es "
            "lo que le importa al supervisor; apagado, prueba desvíos en los dos sentidos. La "
            "prueba de la PD es siempre unilateral y este ajuste no la cambia."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Backtesting", "ui_order": 7},
    )
    realised_pd_col: str = Field(
        default="realised_default",
        title="Default realizado (0/1)",
        description=(
            "La columna de tu archivo que dice si la operación incumplió de verdad en el período "
            "de desempeño."
        ),
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 3,
        },
    )
    realised_lgd_col: str = Field(
        default="realised_lgd",
        title="LGD realizada",
        description="La columna con la severidad que de verdad se observó.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 4,
        },
    )
    realised_ead_col: str = Field(
        default="realised_ead",
        title="EAD realizada a default",
        description="La columna con la exposición que de verdad había al incumplir.",
        json_schema_extra={
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 5,
        },
    )
    pd_test: PdTest = Field(
        default="jeffreys",
        title="Test de PD",
        description="Qué prueba se usa para la PD: la de Jeffreys o la binomial clásica.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Backtesting", "ui_order": 8},
    )

    @model_validator(mode="after")
    def _check_backtesting(self) -> Self:
        """Valida que las columnas de resultado realizado no queden vacías ni colisionen."""
        columns = {
            "segment_col": self.segment_col,
            "realised_pd_col": self.realised_pd_col,
            "realised_lgd_col": self.realised_lgd_col,
            "realised_ead_col": self.realised_ead_col,
        }
        _require_non_empty(columns, context="backtesting")
        _require_no_collision(columns, context="backtesting")
        return self

    def columnas_inactivas(self) -> frozenset[str]:
        """Columnas realizadas que esta configuración de backtesting no abre (D-RAM-1).

        Dos condiciones anidadas, las dos leídas del motor (`evaluator.py::
        _required_realised_columns`): con el backtesting apagado el evaluador no entra a la
        familia y **ninguna** de las tres se lee; encendido, cada columna se lee sólo si su
        parámetro está elegido —un backtesting de PD sola no abre la severidad ni la exposición—.

        `segment_col` NO entra, y no por olvido: no lleva rol, porque la lee del detalle de IFRS 9
        y no del archivo del usuario (ver su comentario).
        """
        if not self.enabled:
            return frozenset(_COLUMNA_REALIZADA_POR_PARAMETRO.values())
        return frozenset(
            campo
            for parametro, campo in _COLUMNA_REALIZADA_POR_PARAMETRO.items()
            if parametro not in self.parameters
        )


class ValidationConfig(NikodymBaseConfig):
    """Valida el modelo con calibración y backtesting, y lo resume en un semáforo."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema validation",
        description="Versión local del schema de validación para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección validation",
        description="Variante de la sección de validación; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    families: tuple[ValidationFamily, ...] = Field(
        default=("discrimination", "calibration", "stability"),
        title="Familias de validación activas",
        description=(
            "Qué familias de pruebas corren: discriminación, calibración, estabilidad y "
            "backtesting. El backtesting viene apagado: necesita el cálculo IFRS 9 y las "
            "columnas con lo que de verdad ocurrió."
        ),
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "General", "ui_order": 2},
    )
    discrimination: DiscriminationValidationConfig = Field(
        default_factory=DiscriminationValidationConfig,
        title="Discriminación",
        description=(
            "Reporta la discriminación (AUC, Gini, KS) tomándola de la etapa de desempeño o "
            "calculándola con ese mismo motor, nunca con otra fórmula."
        ),
        json_schema_extra={"ui_widget": "section", "ui_group": "Discriminación", "ui_order": 1},
    )
    calibration: CalibrationValidationConfig = Field(
        default_factory=CalibrationValidationConfig,
        title="Calibración",
        description=(
            "Mide la calibración con Hosmer-Lemeshow, el contraste binomial/Jeffreys por grado, "
            "el Brier score y un semáforo."
        ),
        json_schema_extra={"ui_widget": "section", "ui_group": "Calibración", "ui_order": 1},
    )
    stability: StabilityValidationConfig = Field(
        default_factory=StabilityValidationConfig,
        title="Estabilidad",
        # La frase decía «o calculándolo con ese mismo motor»: esa rama no está cableada y su
        # interruptor pasó a oculto (D-SUB, arriba), así que prometerla en pantalla habría sido
        # vender una capacidad que la corrida no alcanza.
        description="Reporta el PSI con el mismo motor de la etapa de estabilidad.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Estabilidad", "ui_order": 1},
    )
    backtesting: BacktestingValidationConfig = Field(
        default_factory=BacktestingValidationConfig,
        title="Backtesting IFRS 9",
        description=(
            "Contrasta lo realizado contra lo estimado en IFRS 9 (t-test de LGD/EAD, "
            "binomial/Jeffreys de PD)."
        ),
        json_schema_extra={"ui_widget": "section", "ui_group": "Backtesting", "ui_order": 1},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante brechas críticas de dato",
        description=(
            "Detiene la corrida cuando la validación emite un aviso declarado que le corresponde "
            "gobernar a tu institución: la familia de backtesting elegida sin activarla, o el "
            "backtesting activo sin las columnas de resultado realizado en tu archivo. Apagado, "
            "el aviso queda registrado, esa prueba se omite y la corrida sigue. No afecta a la "
            "columna de grado de rating: si falta, la corrida se detiene siempre."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "General", "ui_order": 3},
    )

    @model_validator(mode="after")
    def _check_validation(self) -> Self:
        """Valida la coherencia entre ``families`` y el backtesting (SDD-22 §5)."""
        if (
            "backtesting" in self.families
            and not self.backtesting.enabled
            and self.fail_on_falta_dato
        ):
            # D-CRP6-6: el mensaje nombra su marca, como sus pares. Sin el código, esta carencia
            # no aparecía en el volcado de auditoría al mismo nivel que las demás. El número sigue
            # la familia VAL sin reutilizar el 1-3, ya tomados por `FALTA-DATO-VAL-*`: son marcas
            # distintas y el par no colisiona, pero dos «VAL-1» en la misma página se leen mal.
            raise ValidationConfigError(
                "DATO-INSTITUCIONAL-VAL-4: families incluye 'backtesting' pero "
                "backtesting.enabled=False; el backtesting IFRS 9 exige enabled=True y las "
                "columnas realizadas declaradas (o fail_on_falta_dato=False para registrarlo "
                "como brecha de datos en vez de detener la corrida).",
                # D-EXI-5: «X exige Y» ancla en Y —lo que FALTA—, no en la opción que lo exige.
                # El mensaje ofrece tres salidas, pero la exigencia que nombra es `enabled=True`;
                # mismo criterio que «lgd.method='workout' exige recovery_col».
                loc=(*_LOC_SECCION, "backtesting", "enabled"),
            )
        return self

    def columnas_inactivas(self) -> frozenset[str]:
        """La subsección entera de cada familia que no corre (D-RAM-1 + D-SUB-1).

        🔴 **Es la primera declaración del repo que nombra SUBMODELOS y no columnas sueltas**, y
        hace falta porque la condición vive un nivel arriba de los campos que apaga: quien decide
        si la calibración lee `grade_col` no es `binomial_by_grade` sino, antes que él, `families`.
        Medido en `evaluator.py::validate`: cada familia entra por `if "<familia>" in
        self.families`, así que una familia deseleccionada no abre ninguna columna aunque sus
        flags queden encendidos — y quedan, porque deseleccionar una familia no los apaga.

        El preflight poda el campo **y su subárbol** cuando el padre lo declara inactivo
        (`dataset_check.py::_declaraciones`, D-SUB-1), que es exactamente lo que hace falta aquí.

        Las cuatro familias se llaman igual que sus cuatro sub-configs, y eso no es casualidad
        sino el contrato que un gate fija: una familia nueva sin su sub-config —o al revés— haría
        que este método suprimiera de más o de menos, en silencio.
        """
        return frozenset(get_args(ValidationFamily)) - frozenset(self.families)

    def requisitos_incumplidos(self, columnas: frozenset[str] | None) -> tuple[Requisito, ...]:
        """Invariantes que el evaluador exige y que sólo se descubrían corriendo (D-INV-1).

        ``families`` vacío es el caso caro: el campo no tiene ``min_length``, ``_check_validation``
        sólo mira la coherencia backtesting↔enabled, y ``validation`` corre **penúltimo** en el F1
        — así que un ``if`` de una línea tumbaba la corrida con todo el cómputo ya pagado.
        """
        del columnas  # no depende del dataset
        if self.families:
            return ()
        return (
            Requisito(
                path="families",
                declared="(ninguna)",
                message=(
                    "No hay ninguna familia de validación activa, y la validación no puede correr "
                    "vacía. Elige al menos una (discriminación, calibración o estabilidad) o "
                    "apaga la sección entera."
                ),
            ),
        )
