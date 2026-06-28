"""Paso orquestable de la capa ``stability`` (SDD-11 §4/§7/§9; CT-1).

``StabilityStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``stability``: lee el score operacional publicado por ``scorecard`` y la PD calibrada publicada
por ``calibration``, arma el frame analítico mínimo que consume
:class:`~nikodym.stability.evaluator.StabilityEvaluator`, emite sus decisiones auditables y publica
PSI/CSI/métricas de estabilidad bajo ``domain='stability'``.

El contrato CT-1 se reduce al mínimo real no supervisado de B11.8: ``stability`` no lee
``data.labels`` ni ``model.final_features``. Los nombres de características para CSI se derivan de
las columnas ``<feature>__points`` de ``scorecard.score``. ``data.frame`` se consulta sólo en
``execute`` cuando la columna temporal/cohorte no viene propagada en ``scorecard.score``.

El módulo evita importar ``pandas``, ``numpy``, ``pandera`` y ``sklearn`` en import time.
``nikodym.stability`` lo importa para ejecutar ``@register("standard", domain="stability")`` sin
contaminar el núcleo liviano; las dependencias tabulares se cargan dentro de ``execute`` y del
evaluador.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.stability.config import StabilityConfig
from nikodym.stability.evaluator import StabilityEvaluator
from nikodym.stability.exceptions import StabilityDataError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.stability.results import StabilityResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditEvent: TypeAlias = Any
    DataFrame: TypeAlias = Any
    StabilityResult: TypeAlias = Any

__all__ = ["STABILITY_ARTIFACTS", "StabilityStep"]

STABILITY_ARTIFACTS: Final[tuple[str, ...]] = (
    "psi_table",
    "stability_metrics",
    "result",
    "card",
)
_SCORING_EXTRA_MESSAGE: Final = (
    "StabilityStep requiere pandas/numpy/pandera; instale nikodym[scoring]."
)
_POINTS_SUFFIX: Final = "__points"
_TEMPORAL_CANDIDATE_NAMES: Final[frozenset[str]] = frozenset(
    {"period", "periodo", "cohort", "cohorte"}
)


@register("standard", domain="stability")
class StabilityStep(AuditableMixin):
    """Orquesta estabilidad post-modelo y publica ``domain='stability'``."""

    name: str = "stability"
    requires: tuple[ArtifactKey, ...] = (
        ("scorecard", "score"),
        ("calibration", "calibrated_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = tuple(("stability", key) for key in STABILITY_ARTIFACTS)

    def __init__(self, config: StabilityConfig) -> None:
        """Construye el paso desde la sección ``StabilityConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: StabilityConfig) -> StabilityStep:
        """Construye ``StabilityStep`` desde ``NikodymConfig.stability``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> StabilityResult:
        """Ejecuta stability determinista sin consumir ``rng`` y publica cuatro artefactos."""
        del rng
        pd = _import_pandas()

        score = _as_dataframe(
            study.artifacts.get("scorecard", "score"),
            pd,
            "scorecard.score",
        ).copy(deep=True)
        calibrated_pd_frame = _as_dataframe(
            study.artifacts.get("calibration", "calibrated_pd_frame"),
            pd,
            "calibration.calibrated_pd_frame",
        ).copy(deep=True)

        cfg = _stability_config_from_study(study, fallback=self.config)
        data_frame = _data_frame_for_temporal_if_needed(
            study,
            score=score,
            config=cfg,
            pd=pd,
        )
        frame, feature_point_columns = _assemble_stability_frame(
            score=score,
            calibrated_pd_frame=calibrated_pd_frame,
            data_frame=data_frame,
            config=cfg,
            pd=pd,
        )
        evaluator = StabilityEvaluator.from_config(cfg)
        evaluator._audit = self._audit
        result = evaluator.evaluate(
            frame.copy(deep=True),
            score_column=cfg.score_column,
            pd_column=cfg.pd_column,
            partition_column=cfg.partition_column,
            feature_point_columns=feature_point_columns,
        )
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: StabilityResult) -> None:
        """Publica los cuatro artefactos estables del dominio ``stability``."""
        study.artifacts.set("stability", "psi_table", result.psi_table.copy(deep=True))
        study.artifacts.set(
            "stability",
            "stability_metrics",
            result.stability_metrics.copy(deep=True),
        )
        study.artifacts.set("stability", "result", result.model_copy(deep=True))
        study.artifacts.set("stability", "card", result.card.model_copy(deep=True))


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise StabilityDataError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _stability_config_from_study(
    study: Study,
    *,
    fallback: StabilityConfig,
) -> StabilityConfig:
    """Lee ``NikodymConfig.stability`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "stability", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, StabilityConfig):
        return raw_config
    return StabilityConfig.model_validate(raw_config)


def _data_frame_for_temporal_if_needed(
    study: Study,
    *,
    score: DataFrame,
    config: StabilityConfig,
    pd: Any,
) -> DataFrame | None:
    """Lee ``data.frame`` sólo si el score no trae la columna temporal requerida."""
    if config.temporal_axis == "none":
        return None
    if config.temporal_column is not None:
        if config.temporal_column in score.columns:
            return None
    elif _temporal_candidate_columns(score):
        return None

    return _as_dataframe(study.artifacts.get("data", "frame"), pd, "data.frame").copy(deep=True)


def _assemble_stability_frame(
    *,
    score: DataFrame,
    calibrated_pd_frame: DataFrame,
    data_frame: DataFrame | None,
    config: StabilityConfig,
    pd: Any,
) -> tuple[DataFrame, tuple[str, ...]]:
    """Alinea score, PD calibrada y columna temporal por índice para el evaluator."""
    _validate_unique_columns(score, artifact="scorecard.score")
    _validate_unique_columns(calibrated_pd_frame, artifact="calibration.calibrated_pd_frame")
    _validate_unique_index(score, artifact="scorecard.score")
    _validate_unique_index(calibrated_pd_frame, artifact="calibration.calibrated_pd_frame")
    if data_frame is not None:
        _validate_unique_columns(data_frame, artifact="data.frame")
        _validate_unique_index(data_frame, artifact="data.frame")

    feature_point_columns = _feature_point_columns(score)
    _validate_required_columns(
        score,
        (config.score_column, *feature_point_columns),
        artifact="scorecard.score",
    )
    _validate_required_columns(
        calibrated_pd_frame,
        (config.partition_column, config.pd_column),
        artifact="calibration.calibrated_pd_frame",
    )
    _validate_aligned_indexes(score, calibrated_pd_frame)

    base = calibrated_pd_frame.loc[:, [config.partition_column, config.pd_column]].copy(deep=True)
    parts: list[DataFrame] = [
        base,
        score.loc[base.index, [config.score_column]].copy(deep=True),
    ]
    if feature_point_columns:
        parts.append(score.loc[base.index, list(feature_point_columns)].copy(deep=True))

    temporal_columns = _temporal_columns_to_copy(
        score=score,
        data_frame=data_frame,
        config=config,
    )
    if temporal_columns:
        temporal_source = (
            score if all(column in score.columns for column in temporal_columns) else data_frame
        )
        if temporal_source is None:
            raise StabilityDataError(
                "stability requiere data.frame para recuperar la columna temporal ausente en "
                "scorecard.score."
            )
        _validate_required_columns(temporal_source, temporal_columns, artifact="data.frame")
        missing_in_data = base.index.difference(temporal_source.index)
        if len(missing_in_data):
            raise StabilityDataError(
                "data.frame no contiene todas las filas modelables requeridas por stability: "
                f"faltan={missing_in_data.astype(str).tolist()}."
            )
        parts.append(temporal_source.loc[base.index, list(temporal_columns)].copy(deep=True))

    return cast(DataFrame, pd.concat(parts, axis=1).copy(deep=True)), feature_point_columns


def _validate_aligned_indexes(score: DataFrame, calibrated_pd_frame: DataFrame) -> None:
    """Exige que score y PD calibrada cubran exactamente las mismas etiquetas."""
    missing_in_score = calibrated_pd_frame.index.difference(score.index)
    extra_score = score.index.difference(calibrated_pd_frame.index)
    if len(missing_in_score) or len(extra_score):
        raise StabilityDataError(
            "scorecard.score y calibration.calibrated_pd_frame no tienen el mismo índice: "
            f"faltan_en_score={missing_in_score.astype(str).tolist()}, "
            f"sobran_en_score={extra_score.astype(str).tolist()}."
        )


def _feature_point_columns(score: DataFrame) -> tuple[str, ...]:
    """Deriva columnas ``<feature>__points`` desde ``scorecard.score`` en orden estable."""
    return tuple(
        sorted(str(column) for column in score.columns if str(column).endswith(_POINTS_SUFFIX))
    )


def _temporal_columns_to_copy(
    *,
    score: DataFrame,
    data_frame: DataFrame | None,
    config: StabilityConfig,
) -> tuple[str, ...]:
    """Determina qué columnas temporales debe recibir el evaluator."""
    if config.temporal_axis == "none":
        return ()
    if config.temporal_column is not None:
        if config.temporal_column in score.columns:
            return (config.temporal_column,)
        if data_frame is None or config.temporal_column not in data_frame.columns:
            raise StabilityDataError(
                f"stability.temporal_column='{config.temporal_column}' no está en "
                "scorecard.score ni data.frame."
            )
        return (config.temporal_column,)

    score_candidates = _temporal_candidate_columns(score)
    if score_candidates:
        return score_candidates
    if data_frame is None:
        return ()
    return _temporal_candidate_columns(data_frame)


def _temporal_candidate_columns(frame: DataFrame) -> tuple[str, ...]:
    """Lista columnas candidatas de período/cohorte con orden determinista."""
    return tuple(
        sorted(
            str(column)
            for column in frame.columns
            if str(column).lower() in _TEMPORAL_CANDIDATE_NAMES
        )
    )


def _validate_unique_columns(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise StabilityDataError(f"{artifact} contiene columnas duplicadas: {joined}.")


def _validate_unique_index(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza índices duplicados antes de alinear artefactos."""
    if frame.index.is_unique:
        return
    duplicated = frame.index[frame.index.duplicated()].astype(str).tolist()
    joined = ", ".join(f"'{item}'" for item in duplicated[:5])
    raise StabilityDataError(f"{artifact} contiene índice duplicado; ejemplos: {joined}.")


def _validate_required_columns(
    frame: DataFrame,
    required: tuple[str, ...],
    *,
    artifact: str,
) -> None:
    """Valida presencia de columnas mínimas antes de ensamblar el frame."""
    missing = [column for column in required if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise StabilityDataError(f"{artifact} no contiene columnas requeridas: {joined}.")
