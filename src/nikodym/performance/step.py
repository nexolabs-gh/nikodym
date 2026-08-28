"""Paso orquestable de la capa ``performance`` (SDD-11 §4/§7/§9; CT-1).

``PerformanceStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``performance``: lee el score operacional publicado por ``scorecard`` y la PD calibrada publicada
por ``calibration``, arma el frame analítico mínimo que consume
:class:`~nikodym.performance.evaluator.PerformanceEvaluator`, emite sus decisiones auditables y
publica métricas discriminantes/tablas de gains bajo ``domain='performance'``.

El módulo evita importar ``pandas``, ``numpy``, ``pandera`` y ``sklearn`` en import time.
``nikodym.performance`` lo importa para ejecutar ``@register("standard", domain="performance")``
sin contaminar el núcleo liviano; las dependencias científicas se cargan dentro de ``execute`` y
del evaluador.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey, campo_de_card, card_publicada
from nikodym.performance.config import PerformanceConfig
from nikodym.performance.evaluator import PerformanceEvaluator
from nikodym.performance.exceptions import PerformanceDataError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.performance.results import PerformanceResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditEvent: TypeAlias = Any
    DataFrame: TypeAlias = Any
    PerformanceResult: TypeAlias = Any

__all__ = ["PERFORMANCE_ARTIFACTS", "PerformanceStep"]

PERFORMANCE_ARTIFACTS: Final[tuple[str, ...]] = (
    "performance_table",
    "discriminant_metrics",
    "result",
    "card",
)
_SCORING_EXTRA_MESSAGE: Final = (
    "PerformanceStep requiere pandas/numpy/pandera/scikit-learn; instale nikodym[scoring]."
)


@register("standard", domain="performance")
class PerformanceStep(AuditableMixin):
    """Orquesta desempeño post-modelo y publica ``domain='performance'``."""

    name: str = "performance"
    requires: tuple[ArtifactKey, ...] = (
        ("scorecard", "score"),
        ("calibration", "calibrated_pd_frame"),
    )
    #: La ficha de la tarjeta lleva la orientación con que el puntaje fue construido (D-DIR-2). Va
    #: en ``optional_requires`` y no en ``requires`` a propósito: exigirla rompería «Validar un
    #: modelo existente», que inyecta ``('scorecard','score')`` por la puerta de artefactos externos
    #: y no publica ninguna ficha. Es la diferencia entre «lo consumo si está» y «lo exijo».
    optional_requires: tuple[ArtifactKey, ...] = (("scorecard", "card"),)
    provides: tuple[ArtifactKey, ...] = tuple(("performance", key) for key in PERFORMANCE_ARTIFACTS)

    def __init__(self, config: PerformanceConfig) -> None:
        """Construye el paso desde la sección ``PerformanceConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: PerformanceConfig) -> PerformanceStep:
        """Construye ``PerformanceStep`` desde ``NikodymConfig.performance``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> PerformanceResult:
        """Ejecuta performance determinista sin consumir ``rng`` y publica cuatro artefactos."""
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

        cfg = _performance_config_from_study(study, fallback=self.config)
        _require_direccion_coherente(study, cfg.score_direction)
        frame = _assemble_performance_frame(
            score=score,
            calibrated_pd_frame=calibrated_pd_frame,
            config=cfg,
            pd=pd,
        )
        evaluator = PerformanceEvaluator.from_config(cfg)
        evaluator._audit = self._audit
        result = evaluator.evaluate(
            frame.copy(deep=True),
            score_column=cfg.score_column,
            pd_column=cfg.pd_column,
            target_column=cfg.target_column,
            partition_column=cfg.partition_column,
        )
        self._publish_artifacts(study, result)
        return result

    def metrics(self, study: Study) -> dict[str, float | None]:
        """Publica el resumen métrico del dominio al namespace canónico (D-GOB-4).

        🔴 Aquí hay REDUCCIÓN, no proyección: AUC, Gini y KS **no son campos escalares** de
        ``PerformanceCardSection`` —el único escalar declarado es ``n_deciles``—, sino que viven en
        ``max_metrics_by_partition``, un ``dict`` por partición. Se publica una clave por partición
        y métrica, ``auc_<partición>``, porque colapsar las particiones a un número exigiría elegir
        cuál manda y esa elección es institucional, no del motor.

        Una partición ``not_evaluable`` —cartera corta, sin ambas clases— trae ``None`` y el núcleo
        la OMITE. Es el caso real de una cartera pequeña, y publicar ``0.0`` ahí diría «AUC de
        0.0», que es peor que no decir nada.
        """
        card = card_publicada(study, "performance", "card")
        por_particion = campo_de_card(card, "max_metrics_by_partition")
        if not isinstance(por_particion, Mapping):
            return {}
        metricas: dict[str, float | None] = {}
        for particion, valores in por_particion.items():
            if not isinstance(valores, Mapping):
                continue
            for nombre in ("auc", "gini", "ks"):
                metricas[f"{nombre}_{particion}"] = valores.get(nombre)
        return metricas

    def metric_sections(self, study: Study) -> dict[str, object]:
        """Publica el payload estructurado CT-2 de la card, sin aplanar (D-GOB-3)."""
        secciones = campo_de_card(card_publicada(study, "performance", "card"), "metric_sections")
        return dict(secciones) if isinstance(secciones, Mapping) else {}

    def _publish_artifacts(self, study: Study, result: PerformanceResult) -> None:
        """Publica los cuatro artefactos estables del dominio ``performance``."""
        study.artifacts.set(
            "performance",
            "performance_table",
            result.performance_table.copy(deep=True),
        )
        study.artifacts.set(
            "performance",
            "discriminant_metrics",
            result.discriminant_metrics.copy(deep=True),
        )
        study.artifacts.set("performance", "result", result.model_copy(deep=True))
        study.artifacts.set("performance", "card", result.card.model_copy(deep=True))


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
    raise PerformanceDataError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _require_direccion_coherente(study: Study, declarada: str) -> None:
    """Detiene la corrida si esta sección mide el puntaje al revés de como se construyó (D-DIR-4).

    La orientación es propiedad **del puntaje**, no de quien lo mide, y quien lo construye la
    publica en su ficha. Si la sección declara la contraria, el resultado no es un fallo ruidoso: es
    un Gini invertido publicado en un informe con las cuatro superficies en verde. Medido sobre el
    preset F1: AUC 0,288 y Gini -0,424 en desarrollo.

    🔴 **Se detiene en vez de heredar en silencio, y ésa es la mitad importante.** Tomar la del
    artefacto y descartar lo que el usuario escribió sería el mecanismo de ``anchor_source`` visto
    desde el otro lado: el motor usando un valor y el config diciendo otro, sin que nadie lo sepa.

    Sin ficha —el puntaje entró por la puerta de artefactos externos— no hay con qué comparar y la
    sección manda sobre la suya, que es el caso de «Validar un modelo existente».
    """
    if not study.artifacts.has("scorecard", "card"):
        return
    card = study.artifacts.get("scorecard", "card")
    construida = getattr(card, "score_direction", None)
    if construida is None or construida == declarada:
        return
    raise ConfigError(
        "La tarjeta de puntaje se construyó con una convención y el desempeño se está midiendo "
        f"con la contraria (la tarjeta declara '{construida}' y esta sección '{declarada}'). "
        "Con las dos al revés los indicadores de discriminación salen invertidos. Deja "
        "scorecard.score_direction y performance.score_direction con el mismo valor."
    )


def _performance_config_from_study(
    study: Study,
    *,
    fallback: PerformanceConfig,
) -> PerformanceConfig:
    """Lee ``NikodymConfig.performance`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "performance", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, PerformanceConfig):
        return raw_config
    return PerformanceConfig.model_validate(raw_config)


def _assemble_performance_frame(
    *,
    score: DataFrame,
    calibrated_pd_frame: DataFrame,
    config: PerformanceConfig,
    pd: Any,
) -> DataFrame:
    """Alinea score y PD calibrada por índice y entrega el frame mínimo del evaluator."""
    _validate_unique_columns(score, artifact="scorecard.score")
    _validate_unique_columns(calibrated_pd_frame, artifact="calibration.calibrated_pd_frame")
    _validate_unique_index(score, artifact="scorecard.score")
    _validate_unique_index(calibrated_pd_frame, artifact="calibration.calibrated_pd_frame")
    _validate_required_columns(score, (config.score_column,), artifact="scorecard.score")
    _validate_required_columns(
        calibrated_pd_frame,
        (config.partition_column, config.target_column, config.pd_column),
        artifact="calibration.calibrated_pd_frame",
    )

    missing_in_score = calibrated_pd_frame.index.difference(score.index)
    extra_score = score.index.difference(calibrated_pd_frame.index)
    if len(missing_in_score) or len(extra_score):
        raise PerformanceDataError(
            "scorecard.score y calibration.calibrated_pd_frame no tienen el mismo índice: "
            f"faltan_en_score={missing_in_score.astype(str).tolist()}, "
            f"sobran_en_score={extra_score.astype(str).tolist()}."
        )

    base = calibrated_pd_frame.loc[
        :,
        [config.partition_column, config.target_column, config.pd_column],
    ].copy(deep=True)
    score_column = score.loc[base.index, [config.score_column]].copy(deep=True)
    return cast(DataFrame, pd.concat([base, score_column], axis=1).copy(deep=True))


def _validate_unique_columns(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza columnas duplicadas para evitar ambigüedad."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise PerformanceDataError(f"{artifact} contiene columnas duplicadas: {joined}.")


def _validate_unique_index(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza índices duplicados antes de alinear artefactos."""
    if frame.index.is_unique:
        return
    duplicated = frame.index[frame.index.duplicated()].astype(str).tolist()
    joined = ", ".join(f"'{item}'" for item in duplicated[:5])
    raise PerformanceDataError(f"{artifact} contiene índice duplicado; ejemplos: {joined}.")


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
        raise PerformanceDataError(f"{artifact} no contiene columnas requeridas: {joined}.")
