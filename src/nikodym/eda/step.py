"""Paso orquestable de la capa ``eda`` (SDD-27 §4/§6/§7; CT-1).

``EdaStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``eda``:
lee los artefactos ya producidos por ``data``, selecciona la población de análisis, orquesta los
analizadores descriptivos y publica los seis artefactos estables del dominio ``eda``.

DECISIÓN AUTÓNOMA (frontera, revisión de Cami): ``splits`` no figura en ``requires`` porque sólo
se necesita cuando ``analysis_partition != "todas"``; el paso lo lee condicionalmente y filtra por
la columna de partición expuesta por SDD-02. Si SDD-02 añade accessors de partición en T2, este
punto puede reemplazarse de forma aditiva.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, get_args

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey, campo_de_card, card_publicada
from nikodym.data.config import CohortSplitConfig, TargetConfig
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.eda.card import EdaCardSection
from nikodym.eda.config import DefaultRateConfig, EdaConfig
from nikodym.eda.default_rate import (
    DefaultRateAnalyzer,
    DefaultRateResult,
    _validar_poblacion,
    datetime_columns,
    tasa_no_calculable,
    tasa_no_evaluable,
)
from nikodym.eda.exceptions import EdaError
from nikodym.eda.figures import FigureSpec, _build_figure_specs
from nikodym.eda.quality import _RESULT_COLUMNS as _COLUMNAS_CALIDAD
from nikodym.eda.quality import DataQualityProfiler, QualityFlag, QualityResult
from nikodym.eda.stability import StabilityResult, TemporalStabilityAnalyzer
from nikodym.eda.univariate import UnivariateProfiler, UnivariateResult

if TYPE_CHECKING:
    from nikodym.core.study import Study
    from nikodym.data.target import LabeledFrame

__all__ = ["EDA_ARTIFACTS", "EdaResult", "EdaStep"]

EDA_ARTIFACTS: Final[tuple[str, ...]] = (
    "default_rate",
    "stability",
    "univariate",
    "quality",
    "figures",
    "eda_card",
)
_QUALITY_FLAG_COLUMNS: Final[tuple[str, ...]] = get_args(QualityFlag)

#: Prefijo de la ruta de este dominio en ``NikodymConfig``, para anclar sus errores (D-EXI-5).
_LOC_SECCION: tuple[str, ...] = ("eda",)


class EdaResult(BaseModel):
    """Resultado agregado de ``EdaStep`` con los cinco sub-resultados EDA.

    ``axis_inferred`` es aditivo (D-SC-3): ``True`` cuando el eje de la tasa de incumplimiento no
    lo eligió el config sino el paso, tomando la cohorte con que el usuario particionó. El eje
    efectivo vive en ``default_rate.axis``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    default_rate: DefaultRateResult
    stability: StabilityResult
    univariate: UnivariateResult
    quality: QualityResult
    figures: tuple[FigureSpec, ...]
    axis_inferred: bool = False


@register("standard", domain="eda")
class EdaStep(AuditableMixin):
    """Orquesta EDA y publica artefactos ``domain='eda'`` sin mutar ``data``."""

    name: str = "eda"
    requires: tuple[ArtifactKey, ...] = (("data", "frame"), ("data", "labels"))
    provides: tuple[ArtifactKey, ...] = tuple(("eda", key) for key in EDA_ARTIFACTS)

    def __init__(self, config: EdaConfig) -> None:
        """Construye el paso desde la sección ``EdaConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: EdaConfig) -> EdaStep:
        """Construye ``EdaStep`` desde ``NikodymConfig.eda``."""
        return cls(cfg)

    def execute(self, study: Study, rng: np.random.Generator) -> EdaResult:
        """Ejecuta default_rate → stability → univariate → quality → figures.

        ``EdaStep`` sólo lee el dominio ``data`` y sólo escribe el dominio ``eda``. Para
        particiones, lee ``("data", "splits")`` de forma condicional cuando
        ``analysis_partition`` no es ``"todas"``; esa clave no entra en ``requires`` por decisión
        de frontera documentada en el módulo.

        🔴 **Nunca levanta** (D-SC-19). El análisis exploratorio es descriptivo y ninguna etapa
        del modelo lo necesita, así que un error aquí cuesta un sub-análisis, no la corrida: la
        preparación, la tasa por período, la estabilidad, los perfiles y la calidad fallan **por
        separado**, cada uno publica su versión vacía y su causa va a ``failed_analyses`` de la
        card, al trail y —como alerta— a las superficies. El paso publica siempre sus seis
        artefactos. Se atrapa cualquier excepción, pero una que no sea ``EdaError`` —un defecto
        del motor— se publica con su tipo, para que no quede escondida. Las piezas
        (``DefaultRateAnalyzer``, los perfiladores), usadas sueltas, siguen levantando.
        """
        fallos: dict[str, str] = {}

        def anotar(sub_analisis: str, exc: BaseException) -> None:
            fallos[sub_analisis] = _causa(exc)

        try:
            frame = _as_dataframe(study.artifacts.get("data", "frame"))
            labels = _as_labeled_frame(study.artifacts.get("data", "labels"))
            frame_part = self._partition_frame(study, frame)
            target_col = labels.target_col
            # Una población rota —vacía, con índice duplicado o sin la columna del target— se
            # detecta UNA vez, aquí: los tres sub-análisis que la leen salen con la misma causa, en
            # vez de que la calidad la describa como si nada y los otros dos fallen por separado.
            _validar_poblacion(frame_part, target_col=target_col)
            profile_frame = self._sample_if_needed(frame_part, rng)
            default_rate_config, axis_inferred, sin_eje = self._resolve_axis(study, frame_part)
            columns = _resolve_univariate_columns(
                frame_part,
                target_col,
                labels.status_col,
                self.config,
                default_rate_config=default_rate_config,
                label_columns=_label_defining_columns(study),
            )
        except Exception as exc:  # D-SC-19: sin población no hay qué describir
            for sub_analisis in ("default_rate", "univariate", "quality"):
                anotar(sub_analisis, exc)
            return self._publicar(
                study,
                default_rate=tasa_no_calculable(
                    None, target_col=None, axis=self.config.default_rate.axis
                ),
                stability=None,
                univariate=_perfiles_vacios(),
                quality=_calidad_vacia(),
                axis_inferred=False,
                fallos=fallos,
            )

        try:
            if sin_eje:
                # D-SC-17: no hay eje con que agrupar y tampoco contradicción que denunciar. La
                # tasa se publica «no evaluable» con su causa y la corrida sigue.
                default_rate = tasa_no_evaluable(
                    frame_part,
                    target_col=target_col,
                    axis=default_rate_config.axis,
                    reason="sin_eje_temporal",
                )
                # La decisión va DESPUÉS de construir el resultado: si la población no valida,
                # el trail no registra una degradación que no ocurrió; esa falla la anota D-SC-19.
                self.log_decision(
                    regla="tasa_por_periodo",
                    umbral="una columna de fecha o una cohorte declarada",
                    valor="sin eje temporal",
                    accion="no_evaluable",
                )
            else:
                default_rate = DefaultRateAnalyzer.from_config(default_rate_config).compute(
                    frame_part,
                    target_col=target_col,
                    audit=self._audit,
                )
        except Exception as exc:  # D-SC-19: la tasa falla sola
            anotar("default_rate", exc)
            default_rate = tasa_no_calculable(
                frame_part, target_col=target_col, axis=default_rate_config.axis
            )

        try:
            stability: StabilityResult | None = TemporalStabilityAnalyzer.from_config(
                self.config.stability
            ).assess(default_rate, audit=self._audit)
        except Exception as exc:  # D-SC-19: una unidad de fallo propia
            anotar("stability", exc)
            stability = None

        try:
            univariate = UnivariateProfiler.from_config(self.config.univariate).profile(
                profile_frame,
                target_col=target_col,
                columns=columns,
                audit=self._audit,
            )
        except Exception as exc:  # D-SC-19: los perfiles fallan solos
            anotar("univariate", exc)
            univariate = _perfiles_vacios()

        try:
            # La calidad es del ARCHIVO: las cuatro columnas que produce ``data`` (target
            # derivado, estado de la etiqueta, partición y rol TTD) no se diagnostican —sobre
            # desarrollo, la partición y el TTD salían «casi constante» por construcción—. Las del
            # usuario, incluidas la fecha, la cohorte y la que define la etiqueta, sí (decisión de
            # Cami, 2026-09-12).
            quality = DataQualityProfiler.from_config(self.config.quality).profile(
                profile_frame.drop(
                    columns=[
                        column
                        for column in (target_col, labels.status_col, PARTITION_COL, TTD_COL)
                        if column in profile_frame.columns
                    ]
                ),
                audit=self._audit,
            )
        except Exception as exc:  # D-SC-19: la calidad falla sola
            anotar("quality", exc)
            quality = _calidad_vacia()

        return self._publicar(
            study,
            default_rate=default_rate,
            stability=stability,
            univariate=univariate,
            quality=quality,
            axis_inferred=axis_inferred,
            fallos=fallos,
        )

    def _publicar(
        self,
        study: Study,
        *,
        default_rate: DefaultRateResult,
        stability: StabilityResult | None,
        univariate: UnivariateResult,
        quality: QualityResult,
        axis_inferred: bool,
        fallos: dict[str, str],
    ) -> EdaResult:
        """Arma el resultado, la card y el trail de lo que falló, y publica los seis artefactos.

        Una estabilidad que no llegó a calcularse —porque falló ella o porque no hubo con qué— se
        construye aquí con su causa: ``tasa_no_calculable`` si lo caído fue la tasa entera,
        ``no_calculable`` si fue la estabilidad sola. Las figuras son una receta pura sobre lo que
        sí se calculó; si aun así fallan, se publican sin ninguna.

        🔴 Esta es la red de las redes, así que tampoco puede levantar (revisión adversarial del
        código, pasada 1): con la preparación caída, la estabilidad se deriva aquí de la tasa
        degradada, y si ese cálculo fallara el paso se llevaría la corrida después de haber
        atrapado todo lo demás. Si falla, la estabilidad se anota como caída con su causa.
        """
        analizador = TemporalStabilityAnalyzer.from_config(self.config.stability)
        if stability is None and "stability" not in fallos:
            try:
                stability = analizador.assess(default_rate, audit=None)
            except Exception as exc:  # D-SC-19: la red final tampoco detiene la corrida
                fallos["stability"] = _causa(exc)
        if stability is None:
            stability = analizador.no_calculable()
        try:
            figures = _build_figure_specs(default_rate=default_rate, univariate=univariate)
        except Exception as exc:  # D-SC-19: un defecto del motor no se esconde (pasada 2)
            # Publicar «0 figuras» sin causa sería un negativo que nadie midió. Los gráficos del
            # informe salen de las tablas y no se pierden; lo que se pierde son las recetas.
            fallos["figures"] = _causa(exc)
            figures = ()
        # `DecisionRecord` no cambia (RUNBOOK §12.2-11): el tipo de una excepción inesperada ya
        # viaja en la causa —«error inesperado del motor (KeyError): …»—, que va al `umbral`.
        for sub_analisis, causa in fallos.items():
            self.log_decision(
                regla="analisis_exploratorio_parcial",
                umbral=causa,
                valor=sub_analisis,
                accion="no_evaluable",
            )
        result = EdaResult(
            default_rate=default_rate,
            stability=stability,
            univariate=univariate,
            quality=quality,
            figures=figures,
            axis_inferred=axis_inferred,
        )
        eda_card = self._build_eda_card(result=result, fallos=fallos)
        self._publish_artifacts(study, result, eda_card)
        return result

    def _resolve_axis(
        self, study: Study, frame_part: pd.DataFrame
    ) -> tuple[DefaultRateConfig, bool, bool]:
        """El config de la tasa que corre, si el eje lo decidió el paso, y si no hay eje.

        Devuelve ``(config, axis_inferred, sin_eje)``. El tercero es D-SC-17.

        Regla nueva de SDD-27 §7.2/§8, del mismo tipo que la inferencia de ``date_col`` que ya
        existe («la única columna datetime»): con ``axis="period"`` y ``date_col`` en blanco, si el
        frame **no tiene ninguna columna de fecha** y el usuario particionó **por cohorte**, el eje
        pasa a esa cohorte —``data.partition.strategy.cohort_col``— y la decisión queda en el trail.
        No se inventa un eje: se usa el que el usuario ya declaró para particionar. Es lo que deja
        correr ``eda`` con sus defaults sobre una cartera sin fecha, que era el caso del preset F1
        (§0-1 del scorecard completo).

        Sin fecha y sin cohorte declarada **no hay eje**, y desde D-SC-17 eso deja de ser un error:
        no se contradice nada de lo que el usuario declaró —``date_col=None`` es el default y
        significa «infiere», así que el config está completo y lo que falta es el dato—, de modo
        que la tasa sale «no evaluable» con causa y la corrida sigue. Hasta la 1.19.0 esto
        levantaba ``EdaError`` y con él morían `eda` y las nueve etapas siguientes, sobre el caso
        que SDD-31 §8 declara soportado. Una fecha declarada que falte, una que no sea datetime, o
        más de una columna datetime, siguen siendo asunto del analizador, que ya los rechaza con su
        mensaje: ahí sí hay una declaración que el archivo desmiente.
        """
        config = self.config.default_rate
        if config.axis != "period" or config.date_col is not None or datetime_columns(frame_part):
            return config, False, False
        cohort_col = _declared_cohort_column(study)
        if cohort_col is None:
            return config, False, True
        self.log_decision(
            regla="eje_eda_inferido",
            umbral="sin columna de fecha y partición por cohorte",
            valor=cohort_col,
            accion="usar_cohorte",
        )
        return config.model_copy(update={"axis": "cohort", "cohort_col": cohort_col}), True, False

    def metrics(self, study: Study) -> dict[str, float | None]:
        """Publica el resumen métrico del dominio al namespace canónico (D-GOB-4, respuesta 6).

        Proyección directa de la card: la tasa de incumplimiento observada, cuántos períodos o
        cohortes la componen y si la señal temporal quedó marcada. ``stability_flagged`` viaja como
        ``1.0``/``0.0`` porque el canal sólo admite ``float`` finito (D-GOB-2) y un ``bool`` lo
        rechaza como contrato roto; ``NaN`` en la tasa —sin elegibles— se omite, no se rellena.
        """
        card = card_publicada(study, "eda", "eda_card")
        flagged = campo_de_card(card, "stability_flagged")
        # D-SC-19 §1.3: lo que FALLÓ no se publica como negativo. Una estabilidad caída —o sin
        # tasa de la que colgar— no es «estable» (0.0), y una tasa caída no tiene «0 períodos». Las
        # causas esperadas de antes (cohorte, pocos períodos, …) conservan su 0.0: cambiarlo
        # movería el `results.metrics` de corridas que hoy terminan.
        estabilidad_caida = campo_de_card(card, "stability_not_evaluable_reason") in (
            "no_calculable",
            "tasa_no_calculable",
        )
        tasa_caida = campo_de_card(card, "default_rate_not_evaluable_reason") == "no_calculable"
        return {
            "overall_default_rate": campo_de_card(card, "overall_default_rate"),
            "n_periods": None if tasa_caida else campo_de_card(card, "n_periods"),
            "stability_flagged": (
                None if flagged is None or estabilidad_caida else float(bool(flagged))
            ),
        }

    def _partition_frame(self, study: Study, frame: pd.DataFrame) -> pd.DataFrame:
        """Selecciona la partición configurada usando el contrato actual de SDD-02."""
        if self.config.analysis_partition == "todas":
            return frame.copy(deep=True)

        splits = study.artifacts.get("data", "splits")
        if not isinstance(splits, PartitionResult):
            raise EdaError(
                "EdaStep requiere ('data', 'splits') como PartitionResult para filtrar "
                f"analysis_partition='{self.config.analysis_partition}'."
            )
        partition_col = splits.partition_col
        if partition_col not in frame.columns:
            raise EdaError(
                "La partición EDA requiere que el frame de data contenga la columna "
                f"'{partition_col}'."
            )
        partition_mask = frame[partition_col].astype("string").eq(self.config.analysis_partition)
        selected = frame.loc[partition_mask.fillna(False).astype("bool")].copy(deep=True)
        if selected.empty:
            raise EdaError(
                f"La partición '{self.config.analysis_partition}' no tiene filas para EDA."
            )
        return selected

    def _sample_if_needed(self, frame_part: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        """Aplica muestreo opt-in y registra una sola decisión auditable cuando ocurre."""
        max_rows = self.config.sampling.max_rows
        n_original = len(frame_part)
        if not self.config.sampling.enabled or n_original <= max_rows:
            return frame_part.copy(deep=True)

        self.log_decision(
            regla="muestreo_eda",
            umbral=max_rows,
            valor=n_original,
            accion="muestrear",
        )
        return frame_part.sample(n=max_rows, random_state=rng).copy(deep=True)

    def _build_eda_card(
        self, *, result: EdaResult, fallos: Mapping[str, str] | None = None
    ) -> EdaCardSection:
        """Construye el resumen EDA leyendo campos ya calculados por ``EdaResult``.

        🔴 Lo que FALLÓ no se publica como resultado negativo (D-SC-19 §1.3): con la calidad caída,
        ``quality_flag_counts`` sale **vacío** y no con ceros, que se leerían «el archivo no tiene
        problemas de calidad».
        """
        fallos = dict(fallos or {})
        by_column = result.quality.by_column
        return EdaCardSection(
            overall_default_rate=result.default_rate.overall_rate,
            n_periods=len(result.default_rate.by_period),
            stability_flagged=result.stability.flagged,
            stability_metric_used=result.stability.metric_used,
            stability_threshold=result.stability.threshold,
            stability_value=float(getattr(result.stability, result.stability.metric_used)),
            n_columns_profiled=len(result.univariate.profiles),
            quality_flag_counts=(
                {}
                if "quality" in fallos
                else {flag: int(by_column[flag].sum()) for flag in _QUALITY_FLAG_COLUMNS}
            ),
            n_figures=len(result.figures),
            axis=result.default_rate.axis,
            axis_inferred=result.axis_inferred,
            stability_not_evaluable_reason=result.stability.not_evaluable_reason,
            default_rate_not_evaluable_reason=result.default_rate.not_evaluable_reason,
            failed_analyses=fallos,
        )

    def _publish_artifacts(self, study: Study, result: EdaResult, eda_card: EdaCardSection) -> None:
        """Publica los seis artefactos estables del dominio ``eda``."""
        study.artifacts.set("eda", "default_rate", result.default_rate)
        study.artifacts.set("eda", "stability", result.stability)
        study.artifacts.set("eda", "univariate", result.univariate)
        study.artifacts.set("eda", "quality", result.quality)
        study.artifacts.set("eda", "figures", result.figures)
        study.artifacts.set("eda", "eda_card", eda_card)


def _causa(exc: BaseException) -> str:
    """La causa de un sub-análisis caído, en palabras (D-SC-19).

    Un ``EdaError`` trae un mensaje ya redactado para una persona. Cualquier otra excepción es un
    defecto del motor: se degrada igual —la regla es «nunca detiene la corrida»— pero se publica
    con su tipo, para que no quede escondida detrás de un «no se pudo calcular».
    """
    if isinstance(exc, EdaError):
        return str(exc)
    return f"error inesperado del motor ({type(exc).__name__}): {exc}"


def _perfiles_vacios() -> UnivariateResult:
    """Perfiles sin ninguna variable: el mismo estado legal que produce ``columns=()``."""
    return UnivariateResult(profiles={}, descriptive_iv={})


def _calidad_vacia() -> QualityResult:
    """La tabla de calidad sin filas y con sus siete columnas: sus consumidores leen columnas."""
    return QualityResult(by_column=pd.DataFrame(columns=list(_COLUMNAS_CALIDAD)))


def _as_dataframe(value: object) -> pd.DataFrame:
    """Valida el artefacto ``data.frame`` antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return value
    raise EdaError("El artefacto ('data', 'frame') debe ser un pandas.DataFrame.")


def _as_labeled_frame(value: object) -> LabeledFrame:
    """Valida el artefacto ``data.labels`` sin importar tipos en runtime de ``core``."""
    from nikodym.data.target import LabeledFrame

    if isinstance(value, LabeledFrame):
        return value
    raise EdaError("El artefacto ('data', 'labels') debe ser un LabeledFrame.")


def _resolve_univariate_columns(
    frame: pd.DataFrame,
    target_col: str,
    status_col: str,
    config: EdaConfig,
    *,
    default_rate_config: DefaultRateConfig | None = None,
    label_columns: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Resuelve features para perfiles; respeta ``UnivariateConfig.columns`` si viene definida.

    Sólo ``None`` significa «todas» (§0-23): una tupla vacía se respeta y produce cero perfiles.
    """
    if config.univariate.columns is not None:
        return config.univariate.columns

    structural = _structural_columns(
        frame,
        target_col,
        status_col,
        config,
        default_rate_config=default_rate_config,
        label_columns=label_columns,
    )
    return tuple(str(column) for column in frame.columns if str(column) not in structural)


def _structural_columns(
    frame: pd.DataFrame,
    target_col: str,
    status_col: str,
    config: EdaConfig,
    *,
    default_rate_config: DefaultRateConfig | None = None,
    label_columns: tuple[str, ...] = (),
) -> set[str]:
    """Columnas que EDA no trata como features cuando el alcance es «todas» (``columns=None``).

    Tres familias: las que produce ``data`` (target, estado, partición, TTD), las del eje de la
    tasa —la fecha o la cohorte **efectivas**, incluida la cohorte inferida por D-SC-3, y toda
    columna datetime— y, desde la capa 3 del scorecard completo (§8-8, respuesta 8 de Cami), las
    que **definen la etiqueta**: describir ``bad_flag`` frente al incumplimiento daba una tasa
    0 %/100 % por tramo. Quien las pida por su nombre en ``columns`` las obtiene igual.
    """
    axis_config = config.default_rate if default_rate_config is None else default_rate_config
    columns = {target_col, status_col, PARTITION_COL, TTD_COL, *label_columns}
    if axis_config.date_col is not None:
        columns.add(axis_config.date_col)
    if axis_config.cohort_col is not None:
        columns.add(axis_config.cohort_col)
    # DECISIÓN AUTÓNOMA (frontera, revisión de Cami): si date_col se infiere, se excluyen todas
    # las columnas datetime para no perfilar accidentalmente la fecha estructural como feature.
    columns.update(datetime_columns(frame))
    return columns


def _declared_cohort_column(study: Study) -> str | None:
    """La cohorte con que el usuario particionó, o ``None`` si no particionó por cohorte.

    Se lee del config y no del artefacto de particiones: ``PartitionResult`` publica la
    estrategia usada pero no su columna. Se aceptan la forma tipada y el *blob* opaco del núcleo
    liviano, que es como puede viajar ``data`` antes de que su capa se importe.
    """
    strategy = _partition_strategy(study)
    if isinstance(strategy, CohortSplitConfig):
        return strategy.cohort_col
    if isinstance(strategy, Mapping) and strategy.get("type") == "cohort":
        cohort_col = strategy.get("cohort_col")
        return cohort_col if isinstance(cohort_col, str) and cohort_col else None
    return None


def _partition_strategy(study: Study) -> object:
    data = study.config.data
    if isinstance(data, Mapping):
        partition = data.get("partition")
        return partition.get("strategy") if isinstance(partition, Mapping) else None
    partition = getattr(data, "partition", None)
    return getattr(partition, "strategy", None)


def _label_defining_columns(study: Study) -> tuple[str, ...]:
    """Las columnas de las reglas de «malo» y «bueno», leídas de ``data.target`` si está tipada."""
    data = study.config.data
    target = data.get("target") if isinstance(data, Mapping) else getattr(data, "target", None)
    if isinstance(target, TargetConfig):
        return target.columnas_que_definen_la_etiqueta()
    if isinstance(target, Mapping):
        return TargetConfig.model_validate(target).columnas_que_definen_la_etiqueta()
    return ()
