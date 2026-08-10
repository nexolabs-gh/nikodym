"""Config declarativo de la capa ``stability`` (SDD-11 §5).

:class:`StabilityConfig` es la sección ``stability`` de
:class:`~nikodym.core.config.NikodymConfig`: monitoreo determinista de PSI del score/PD, CSI de
características finales y estabilidad temporal post-modelo. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional, por lo que entra al ``config_hash`` global cuando está
activa.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.dataset_check import ContextoConfig, Requisito
from nikodym.core.exceptions import ConfigError

#: Nombres que el evaluador acepta como columna de período/cohorte cuando ``temporal_column`` va
#: vacía. Vive **aquí y no en el evaluador** desde la enmienda INVARIANTES-PREVIAS: el aviso y el
#: motor tienen que mirar exactamente el mismo conjunto, o el aviso mentiría en cuanto uno de los
#: dos creciera. Misma lección que el gate de `column_role` (`e688280`): medir el footprint real,
#: no una lista escrita al lado.
TEMPORAL_CANDIDATE_NAMES: frozenset[str] = frozenset({"period", "periodo", "cohort", "cohorte"})

ScoreDirection = Literal["higher_is_lower_risk", "higher_is_higher_risk"]
StabilityComparison = Literal["dev_vs_holdout", "dev_vs_oot"]
TemporalAxis = Literal["none", "period", "cohort"]
TemporalFrequency = Literal["M", "Q", "Y"]
CsiSource = Literal["score_points", "woe_bins"]

__all__ = [
    "TEMPORAL_CANDIDATE_NAMES",
    "CsiSource",
    "ScoreDirection",
    "StabilityComparison",
    "StabilityConfig",
    "TemporalAxis",
    "TemporalFrequency",
]

#: Prefijo de la ruta de este dominio en ``NikodymConfig``, para anclar sus errores (D-EXI-5).
#: Vive en UN solo sitio y no repetido en cada ``raise``: la ruta que el error declara es
#: **absoluta desde la raíz del config**, así que ata al dominio con el nombre de su campo en la
#: raíz, y concentrarla aquí deja un único lugar donde ese acoplamiento puede quedarse stale.
_LOC_SECCION: tuple[str, ...] = ("stability",)

_COLUMN_FIELDS: tuple[str, ...] = (
    "score_column",
    "pd_column",
    "partition_column",
)


class StabilityConfig(NikodymBaseConfig):
    """Mide la estabilidad del score y de la PD calibrada con PSI y CSI."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema stability",
        description="Versión local del schema de stability para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección stability",
        description="Variante de la sección de estabilidad; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    score_column: str = Field(
        default="score",
        title="Columna score",
        description="Columna con el score operacional publicado por scorecard.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 1,
        },
    )
    pd_column: str = Field(
        default="pd_calibrated",
        title="Columna PD calibrada",
        description="Columna con la probabilidad de default calibrada post-modelo.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 2,
        },
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna que identifica Desarrollo, Holdout y OOT.",
        json_schema_extra={
            "column_role": "derived",
            "ui_widget": "text_input",
            "ui_group": "Columnas",
            "ui_order": 3,
        },
    )
    score_direction: ScoreDirection = Field(
        default="higher_is_lower_risk",
        title="Dirección del score",
        description="Define si un score mayor representa menor riesgo o mayor riesgo.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Ranking", "ui_order": 1},
    )
    psi_bins: int = Field(
        default=10,
        ge=2,
        le=50,
        title="Bins para PSI de score",
        description="Cantidad de bins definidos en Desarrollo para comparar score/PD.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 1},
    )
    csi_bins: int = Field(
        default=10,
        ge=2,
        le=50,
        title="Bins para CSI si no hay puntos discretos",
        description="Cantidad de bins para CSI cuando la fuente no provee puntos discretos.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 2},
    )
    psi_stable_threshold: float = Field(
        default=0.10,
        ge=0.0,
        title="Umbral PSI de revisión",
        description=(
            "Por debajo de este valor el PSI se considera estable; al alcanzarlo o superarlo "
            "inicia la banda de revisión."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 3},
    )
    psi_review_threshold: float = Field(
        default=0.25,
        ge=0.0,
        title="Umbral PSI de redesarrollo",
        description="Al alcanzar o superar este valor, el PSI gatilla redesarrollo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 4},
    )
    smoothing: float = Field(
        default=1e-6,
        gt=0.0,
        title="Suavizado de proporciones",
        description="Valor positivo aplicado a proporciones cero en PSI/CSI.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Métricas", "ui_order": 5},
    )
    comparisons: tuple[StabilityComparison, ...] = Field(
        default=("dev_vs_holdout", "dev_vs_oot"),
        title="Comparaciones de estabilidad",
        description="Pares de particiones a comparar usando Desarrollo como población esperada.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Población", "ui_order": 1},
    )
    temporal_axis: TemporalAxis = Field(
        default="period",
        title="Eje temporal del score",
        description="Eje usado para estabilidad temporal: período, cohorte o ninguno.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Temporal", "ui_order": 1},
    )
    temporal_column: str | None = Field(
        default=None,
        title="Columna de período/cohorte",
        description=(
            "Columna del eje temporal; vacía la infiere de los datos si hay una sola candidata."
        ),
        json_schema_extra={
            "ui_help": (
                "Si se deja vacía y el eje temporal no es 'none', se infiere de los datos "
                "cuando hay una sola columna candidata; si hay varias o ninguna, la corrida "
                "se detiene con error."
            ),
            "column_role": "input",
            "ui_widget": "text_input",
            "ui_group": "Temporal",
            "ui_order": 2,
        },
    )
    temporal_freq: TemporalFrequency = Field(
        default="M",
        title="Frecuencia temporal",
        description=(
            "Frecuencia de agregación para estabilidad temporal: mensual, trimestral o anual."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Temporal", "ui_order": 3},
    )
    include_pd_stability: bool = Field(
        default=True,
        title="Incluir estabilidad de PD calibrada",
        description="Activa el cálculo de PSI sobre la PD calibrada además del score.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Métricas", "ui_order": 6},
    )
    csi_source: CsiSource = Field(
        default="score_points",
        title="Fuente de CSI",
        description="Fuente de las distribuciones del CSI: puntos o bins WoE congelados.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Métricas", "ui_order": 7},
    )

    @model_validator(mode="after")
    def _check_invariantes(self) -> Self:
        """Valida columnas, umbrales y decisiones diferidas de SDD-11 §5."""
        columns = _column_values(self)
        vacias = [nombre for nombre, columna in columns.items() if not columna.strip()]
        if vacias:
            # D-EXI-5: SIN `loc` a propósito. El ofensor es cualquiera de las columnas que
            # `_column_values` reúne y el mensaje las enumera **todas**, así que no hay un campo
            # único al que llevar al usuario; anclar en uno elegido a dedo lo mandaría al que no
            # era.
            raise ConfigError(f"Las columnas de stability no pueden estar vacías: {vacias}.")

        normalizadas: dict[str, str] = {}
        duplicadas: list[tuple[str, str, str]] = []
        for nombre, columna in columns.items():
            clave = columna.strip()
            previo = normalizadas.get(clave)
            if previo is not None:
                duplicadas.append((previo, nombre, clave))
            normalizadas[clave] = nombre
        if duplicadas:
            # D-EXI-5: SIN `loc` a propósito. Es un invariante ENTRE campos —dos columnas con el
            # mismo nombre— y no hay culpable único: cualquiera de las dos sirve para deshacer la
            # colisión, así que la ruta vacía dice la verdad.
            raise ConfigError(f"Las columnas de stability no pueden colisionar: {duplicadas}.")

        _require_finite("psi_stable_threshold", self.psi_stable_threshold)
        _require_finite("psi_review_threshold", self.psi_review_threshold)
        _require_finite("smoothing", self.smoothing)

        if self.psi_stable_threshold >= self.psi_review_threshold:
            # D-EXI-5: SIN `loc` a propósito. Es un invariante ENTRE dos umbrales: se arregla
            # bajando uno o subiendo el otro, y cuál de los dos está mal lo sabe el usuario y no
            # el motor. Anclar en uno le escondería la mitad de la decisión.
            raise ConfigError(
                "psi_stable_threshold debe ser estrictamente menor que psi_review_threshold."
            )
        return self

    def requisitos_incumplidos(self, columnas: frozenset[str] | None) -> tuple[Requisito, ...]:
        """Invariantes que esta sección impone y que la corrida rechazaría (D-INV-1).

        No son validaciones de forma —de eso se encarga ``_check_invariantes``— sino exigencias
        sobre la **combinación** de campos y sobre el dataset, que hasta ahora sólo se descubrían
        pagando la corrida entera: el caso de origen de la enmienda moría en el paso 8 de 10 con el
        preflight y ``check_pipeline`` en verde.
        """
        requisitos: list[Requisito] = []

        # El eje temporal exige una columna de período. `_resolve_temporal_column` la busca primero
        # en `temporal_column` y, si está vacía, la INFIERE por nombre entre las candidatas; si
        # no halla ninguna (o halla varias) aborta el paso. Que `temporal_column` esté vacía es su
        # default, así que el caso llega solo a cualquiera con un dataset sin columna temporal.
        if self.temporal_axis != "none" and self.temporal_column is None and columnas is not None:
            # `columnas is not None`: sin los nombres no se puede afirmar nada (D-INV-4).
            candidatas = sorted(c for c in columnas if c.lower() in TEMPORAL_CANDIDATE_NAMES)
            if not candidatas:
                requisitos.append(
                    Requisito(
                        path="temporal_axis",
                        declared=self.temporal_axis,
                        # El texto nombra el literal que el usuario VE en el selector (`none`),
                        # no su traducción: verificado en vivo que las opciones se pintan crudas,
                        # y mandarlo a buscar un «ninguno» que no existe es peor que no decir nada.
                        message=(
                            f"La estabilidad temporal está activada (eje «{self.temporal_axis}») y "
                            f"el dataset no trae ninguna columna de período o cohorte, así que la "
                            f"corrida se detendrá al llegar a estabilidad. Pon el eje temporal en "
                            f"«none», o indica la columna de período en el campo de al lado."
                        ),
                    )
                )
            elif len(candidatas) > 1:
                nombres = ", ".join(f"«{c}»" for c in candidatas)
                requisitos.append(
                    Requisito(
                        path="temporal_column",
                        declared=self.temporal_axis,
                        message=(
                            f"El dataset trae más de una columna que podría ser el período "
                            f"({nombres}) y el motor no elige por ti. Indica cuál usar en este "
                            f"campo, o desactiva el eje temporal."
                        ),
                    )
                )

        # `comparisons` es una tupla y el evaluador rechaza los repetidos: cada comparación produce
        # una fila del informe y dos iguales serían dos filas idénticas con distinto significado.
        if len(set(self.comparisons)) != len(self.comparisons):
            requisitos.append(
                Requisito(
                    path="comparisons",
                    declared=", ".join(self.comparisons),
                    message=(
                        "Hay comparaciones de estabilidad repetidas. Deja una sola vez cada par de "
                        "particiones que quieras comparar."
                    ),
                )
            )

        return tuple(requisitos)

    def requisitos_incumplidos_por_contexto(
        self, contexto: ContextoConfig
    ) -> tuple[Requisito, ...]:
        """Avisa si esta sección describe el puntaje al revés de como se construyó (D-DIR-5).

        ⚠️ **Aquí la consecuencia no es un número invertido: es un documento que se contradice.**
        Medido, el motor de estabilidad no lee este campo en ningún cálculo —PSI y CSI comparan
        distribuciones binadas y son invariantes al signo—; el valor viaja del config a la ficha y
        de ahí al informe. Con la respuesta contraria a la de la tarjeta, el mismo documento afirma
        dos orientaciones distintas del mismo puntaje, y el lector no tiene cómo saber cuál rige.
        """
        declarada = contexto.direccion_del_score
        if declarada is None or declarada == self.score_direction:
            return ()
        return (
            Requisito(
                path="score_direction",
                declared=self.score_direction,
                message=(
                    "Estás describiendo el puntaje con la convención contraria a la que usaste "
                    "para construir la tarjeta. El informe publicaría las dos, y quien lo lea no "
                    "sabría cuál vale. Deja las dos con la misma respuesta a «un puntaje más alto, "
                    "¿es mejor o peor cliente?»."
                ),
            ),
        )


def _column_values(cfg: StabilityConfig) -> dict[str, str]:
    """Devuelve nombres de columnas configurados para validar colisiones."""
    columns: dict[str, str] = {nombre: getattr(cfg, nombre) for nombre in _COLUMN_FIELDS}
    if cfg.temporal_column is not None:
        columns["temporal_column"] = cfg.temporal_column
    return columns


def _require_finite(nombre: str, valor: float) -> None:
    """Valida finitud para campos float que participan del ``config_hash``.

    D-EXI-5: su ``raise`` va **sin** ``loc``. Lo llaman tres campos distintos
    (``psi_stable_threshold``, ``psi_review_threshold`` y ``smoothing``) y el nombre del ofensor
    llega como **dato**, así que un ancla literal aquí sería la correcta para uno y falsa para los
    otros dos. Pasarla desde el llamador tampoco sirve: el gate que vigila estas rutas las evalúa
    **estáticamente** y sólo admite una tupla literal en el propio ``raise``.
    """
    if not math.isfinite(valor):
        raise ConfigError(f"{nombre} debe ser un número finito.")
