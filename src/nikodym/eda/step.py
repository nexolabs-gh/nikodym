"""Paso orquestable de la capa ``eda`` (SDD-27 §4/§6/§7; CT-1).

``EdaStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``eda``:
lee los artefactos ya producidos por ``data``, selecciona la población de análisis, orquesta los
analizadores descriptivos y publica los cinco artefactos estables del dominio ``eda``.

DECISIÓN AUTÓNOMA (frontera, revisión de Cami): ``splits`` no figura en ``requires`` porque sólo
se necesita cuando ``analysis_partition != "todas"``; el paso lo lee condicionalmente y filtra por
la columna de partición expuesta por SDD-02. Si SDD-02 añade accessors de partición en T2, este
punto puede reemplazarse de forma aditiva.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.data.partition import PARTITION_COL, TTD_COL, PartitionResult
from nikodym.eda.config import EdaConfig
from nikodym.eda.default_rate import DefaultRateAnalyzer, DefaultRateResult
from nikodym.eda.exceptions import EdaError
from nikodym.eda.figures import FigureSpec, _build_figure_specs
from nikodym.eda.quality import DataQualityProfiler, QualityResult
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
)


class EdaResult(BaseModel):
    """Resultado agregado de ``EdaStep`` con los cinco artefactos EDA."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    default_rate: DefaultRateResult
    stability: StabilityResult
    univariate: UnivariateResult
    quality: QualityResult
    figures: tuple[FigureSpec, ...]


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
        columns = _resolve_univariate_columns(
            frame_part,
            target_col,
            labels.status_col,
            self.config,
        )

        default_rate = DefaultRateAnalyzer.from_config(self.config.default_rate).compute(
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
        )
        self._publish_artifacts(study, result)
        return result

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

    def _publish_artifacts(self, study: Study, result: EdaResult) -> None:
        """Publica los cinco artefactos estables del dominio ``eda``."""
        study.artifacts.set("eda", "default_rate", result.default_rate)
        study.artifacts.set("eda", "stability", result.stability)
        study.artifacts.set("eda", "univariate", result.univariate)
        study.artifacts.set("eda", "quality", result.quality)
        study.artifacts.set("eda", "figures", result.figures)


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
) -> tuple[str, ...]:
    """Resuelve features para perfiles; respeta ``UnivariateConfig.columns`` si viene definida."""
    if config.univariate.columns is not None:
        return config.univariate.columns

    structural = _structural_columns(frame, target_col, status_col, config)
    return tuple(str(column) for column in frame.columns if str(column) not in structural)


def _structural_columns(
    frame: pd.DataFrame,
    target_col: str,
    status_col: str,
    config: EdaConfig,
) -> set[str]:
    """Columnas producidas por ``data`` que EDA no trata como features."""
    columns = {target_col, status_col, PARTITION_COL, TTD_COL}
    if config.default_rate.date_col is not None:
        columns.add(config.default_rate.date_col)
    if config.default_rate.cohort_col is not None:
        columns.add(config.default_rate.cohort_col)
    # DECISIÓN AUTÓNOMA (frontera, revisión de Cami): si date_col se infiere, se excluyen todas
    # las columnas datetime para no perfilar accidentalmente la fecha estructural como feature.
    columns.update(
        str(column)
        for column in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[column].dtype)
    )
    return columns
