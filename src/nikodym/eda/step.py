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
from nikodym.eda.default_rate import DefaultRateAnalyzer, DefaultRateResult, datetime_columns
from nikodym.eda.exceptions import EdaError
from nikodym.eda.figures import FigureSpec, _build_figure_specs
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
        """
        frame = _as_dataframe(study.artifacts.get("data", "frame"))
        labels = _as_labeled_frame(study.artifacts.get("data", "labels"))
        frame_part = self._partition_frame(study, frame)
        profile_frame = self._sample_if_needed(frame_part, rng)
        target_col = labels.target_col
        default_rate_config, axis_inferred = self._resolve_axis(study, frame_part)
        columns = _resolve_univariate_columns(
            frame_part,
            target_col,
            labels.status_col,
            self.config,
            default_rate_config=default_rate_config,
            label_columns=_label_defining_columns(study),
        )

        default_rate = DefaultRateAnalyzer.from_config(default_rate_config).compute(
            frame_part,
            target_col=target_col,
            audit=self._audit,
        )
        stability = TemporalStabilityAnalyzer.from_config(self.config.stability).assess(
            default_rate,
            audit=self._audit,
        )
        univariate = UnivariateProfiler.from_config(self.config.univariate).profile(
            profile_frame,
            target_col=target_col,
            columns=columns,
            audit=self._audit,
        )
        quality = DataQualityProfiler.from_config(self.config.quality).profile(
            profile_frame,
            audit=self._audit,
        )
        figures = _build_figure_specs(default_rate=default_rate, univariate=univariate)
        result = EdaResult(
            default_rate=default_rate,
            stability=stability,
            univariate=univariate,
            quality=quality,
            figures=figures,
            axis_inferred=axis_inferred,
        )
        eda_card = self._build_eda_card(result=result)
        self._publish_artifacts(study, result, eda_card)
        return result

    def _resolve_axis(
        self, study: Study, frame_part: pd.DataFrame
    ) -> tuple[DefaultRateConfig, bool]:
        """El config de la tasa que de verdad corre, y si el eje lo decidió el paso (D-SC-3).

        Regla nueva de SDD-27 §7.2/§8, del mismo tipo que la inferencia de ``date_col`` que ya
        existe («la única columna datetime»): con ``axis="period"`` y ``date_col`` en blanco, si el
        frame **no tiene ninguna columna de fecha** y el usuario particionó **por cohorte**, el eje
        pasa a esa cohorte —``data.partition.strategy.cohort_col``— y la decisión queda en el trail.
        No se inventa un eje: se usa el que el usuario ya declaró para particionar. Es lo que deja
        correr ``eda`` con sus defaults sobre una cartera sin fecha, que era el caso del preset F1
        (§0-1 del scorecard completo).

        Sin fecha y sin cohorte declarada el error es el de siempre, ahora **anclado al campo**
        (D-VIS): ``eda.default_rate.date_col``. Una fecha declarada que falte, o más de una columna
        datetime, siguen siendo asunto del analizador, que ya los rechaza con su mensaje.
        """
        config = self.config.default_rate
        if config.axis != "period" or config.date_col is not None or datetime_columns(frame_part):
            return config, False
        cohort_col = _declared_cohort_column(study)
        if cohort_col is None:
            raise EdaError(
                "La tasa de default por período requiere una columna de fecha, y el archivo no "
                "trae ninguna; declárela en eda.default_rate.date_col, o particiona por cohorte "
                "para que el eje la tome de ahí, o usa axis='cohort'.",
                loc=(*_LOC_SECCION, "default_rate", "date_col"),
            )
        self.log_decision(
            regla="eje_eda_inferido",
            umbral="sin columna de fecha y partición por cohorte",
            valor=cohort_col,
            accion="usar_cohorte",
        )
        return config.model_copy(update={"axis": "cohort", "cohort_col": cohort_col}), True

    def metrics(self, study: Study) -> dict[str, float | None]:
        """Publica el resumen métrico del dominio al namespace canónico (D-GOB-4, respuesta 6).

        Proyección directa de la card: la tasa de incumplimiento observada, cuántos períodos o
        cohortes la componen y si la señal temporal quedó marcada. ``stability_flagged`` viaja como
        ``1.0``/``0.0`` porque el canal sólo admite ``float`` finito (D-GOB-2) y un ``bool`` lo
        rechaza como contrato roto; ``NaN`` en la tasa —sin elegibles— se omite, no se rellena.
        """
        card = card_publicada(study, "eda", "eda_card")
        flagged = campo_de_card(card, "stability_flagged")
        return {
            "overall_default_rate": campo_de_card(card, "overall_default_rate"),
            "n_periods": campo_de_card(card, "n_periods"),
            "stability_flagged": None if flagged is None else float(bool(flagged)),
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

    def _build_eda_card(self, *, result: EdaResult) -> EdaCardSection:
        """Construye el resumen EDA leyendo campos ya calculados por ``EdaResult``."""
        by_column = result.quality.by_column
        return EdaCardSection(
            overall_default_rate=result.default_rate.overall_rate,
            n_periods=len(result.default_rate.by_period),
            stability_flagged=result.stability.flagged,
            stability_metric_used=result.stability.metric_used,
            stability_threshold=result.stability.threshold,
            stability_value=float(getattr(result.stability, result.stability.metric_used)),
            n_columns_profiled=len(result.univariate.profiles),
            quality_flag_counts={
                flag: int(by_column[flag].sum()) for flag in _QUALITY_FLAG_COLUMNS
            },
            n_figures=len(result.figures),
            axis=result.default_rate.axis,
            axis_inferred=result.axis_inferred,
            stability_not_evaluable_reason=result.stability.not_evaluable_reason,
        )

    def _publish_artifacts(self, study: Study, result: EdaResult, eda_card: EdaCardSection) -> None:
        """Publica los seis artefactos estables del dominio ``eda``."""
        study.artifacts.set("eda", "default_rate", result.default_rate)
        study.artifacts.set("eda", "stability", result.stability)
        study.artifacts.set("eda", "univariate", result.univariate)
        study.artifacts.set("eda", "quality", result.quality)
        study.artifacts.set("eda", "figures", result.figures)
        study.artifacts.set("eda", "eda_card", eda_card)


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
