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

El ensamblador del frame y el cálculo son públicos —:func:`assemble_stability_frame` y
:func:`compute_stability`— desde la enmienda VALIDACION-COTEJADA (D-VAL-16): el recálculo del PSI
de ``validation`` corre el mismo motor por la misma llamada, y no hay dos formas de recalcular.

El módulo evita importar ``pandas``, ``numpy``, ``pandera`` y ``sklearn`` en import time.
``nikodym.stability`` lo importa para ejecutar ``@register("standard", domain="stability")`` sin
contaminar el núcleo liviano; las dependencias tabulares se cargan dentro de ``execute`` y del
evaluador.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import (
    REGLA_TTD_NO_PUNTUADA,
    ArtifactKey,
    campo_de_card,
    card_publicada,
    entradas_fuera_del_ajuste,
)
from nikodym.stability.config import TEMPORAL_CANDIDATE_NAMES, StabilityConfig
from nikodym.stability.evaluator import StabilityEvaluator, psi_fuera_del_ajuste
from nikodym.stability.exceptions import StabilityDataError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent, AuditSink
    from nikodym.core.study import Study
    from nikodym.stability.results import StabilityResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditEvent: TypeAlias = Any
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any
    StabilityResult: TypeAlias = Any

__all__ = [
    "STABILITY_ARTIFACTS",
    "StabilityStep",
    "assemble_stability_frame",
    "compute_stability",
]

STABILITY_ARTIFACTS: Final[tuple[str, ...]] = (
    "psi_table",
    "stability_metrics",
    "result",
    "card",
    # Aditivo (enmienda PUNTUAR-POBLACION-TTD, D-TTD-4): el PSI del puntaje entre Desarrollo y
    # las operaciones fuera del ajuste, con el esquema de `psi_table`. Clave propia.
    "out_of_model_psi",
)
_SCORING_EXTRA_MESSAGE: Final = (
    "StabilityStep requiere pandas/numpy/pandera; instale nikodym[scoring]."
)
_POINTS_SUFFIX: Final = "__points"


@register("standard", domain="stability")
class StabilityStep(AuditableMixin):
    """Orquesta estabilidad post-modelo y publica ``domain='stability'``."""

    name: str = "stability"
    requires: tuple[ArtifactKey, ...] = (
        ("scorecard", "score"),
        ("calibration", "calibrated_pd_frame"),
    )
    #: La ficha de la tarjeta lleva la orientación con que el puntaje fue construido (D-DIR-2). Va
    #: en ``optional_requires`` por la misma razón que en ``performance``: exigirla rompería el
    #: trabajo que trae el puntaje ya construido y sin ficha.
    optional_requires: tuple[ArtifactKey, ...] = (
        ("scorecard", "card"),
        ("binning", "bin_frame"),
        # La cadena fuera del ajuste (D-TTD-2 y D-TTD-4): el puntaje y la PD calibrada. Si la
        # calibración no pudo con esas filas, no se mide su representatividad.
        ("scorecard", "out_of_model_score"),
        ("calibration", "out_of_model_calibrated_pd_frame"),
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
        """Ejecuta stability determinista sin consumir ``rng`` y publica cuatro artefactos.

        El cálculo entero —ensamblar el frame y correr el evaluador— vive en
        :func:`compute_stability`, que es también lo que llama ``validation`` cuando recalcula el
        PSI (D-VAL-16): un solo camino, sin duplicar la alineación.
        """
        del rng
        cfg = _stability_config_from_study(study, fallback=self.config)
        result = compute_stability(study, cfg, audit=self._audit)
        out_of_model_psi = self._psi_fuera_del_ajuste(study, cfg)
        self._publish_artifacts(study, result, out_of_model_psi)
        return result

    def _psi_fuera_del_ajuste(self, study: Study, cfg: StabilityConfig) -> DataFrame:
        """Representatividad: el puntaje de Desarrollo frente al de fuera del ajuste (D-TTD-4).

        No es una comparación de ``comparisons``, no entra al veredicto y no detiene la corrida:
        sin la cadena completa la clave queda vacía, y si el cálculo falla, también, con la falla
        al trail.
        """
        entradas = entradas_fuera_del_ajuste(
            study,
            (
                ("scorecard", "out_of_model_score"),
                ("calibration", "out_of_model_calibrated_pd_frame"),
            ),
        )
        if entradas is None:
            return psi_fuera_del_ajuste(cfg, dev_scores=None, fuera_scores=None)
        fuera, calibrada = entradas
        try:
            # La cadena exige una sola población: el puntaje y la PD calibrada de las mismas filas
            # (revisión adversarial del código, pasada 1).
            if not fuera.index.sort_values().equals(calibrada.index.sort_values()):
                raise StabilityDataError(
                    "El puntaje y la PD calibrada fuera del ajuste no tienen el mismo índice."
                )
            score = study.artifacts.get("scorecard", "score")
            dev = score.loc[
                score["partition"].astype("string").eq("desarrollo").fillna(False).astype(bool),
                cfg.score_column,
            ]
            return psi_fuera_del_ajuste(
                cfg,
                dev_scores=dev.to_numpy(dtype="float64"),
                fuera_scores=fuera[cfg.score_column].to_numpy(dtype="float64"),
            )
        except Exception as exc:  # D-TTD-1 §1.6: fuera del ajuste nunca detiene la corrida
            self.log_decision(
                regla=REGLA_TTD_NO_PUNTUADA,
                umbral=self.name,
                valor={"filas": len(fuera.index), "causa": f"{type(exc).__name__}: {exc}"},
                accion="publicar_vacio",
            )
            return psi_fuera_del_ajuste(cfg, dev_scores=None, fuera_scores=None)

    def metrics(self, study: Study) -> dict[str, float | None]:
        """Publica el resumen métrico del dominio al namespace canónico (D-GOB-4).

        ``worst_psi`` es una REDUCCIÓN de ``max_psi_by_comparison`` (un ``dict`` por comparación):
        el peor caso es lo que gobierna la conclusión de estabilidad, y es la única forma de
        publicar un escalar sin elegir por la institución qué comparación importa. Sin ninguna
        comparación evaluable no hay peor caso, y la clave se omite en vez de valer ``0.0`` —que
        leería como «estabilidad perfecta», la lectura exactamente opuesta a la verdadera—.
        """
        card = card_publicada(study, "stability", "card")
        por_comparacion = campo_de_card(card, "max_psi_by_comparison")
        evaluables = (
            [
                valor
                for valor in por_comparacion.values()
                if isinstance(valor, int | float) and not isinstance(valor, bool)
            ]
            if isinstance(por_comparacion, Mapping)
            else []
        )
        return {
            "worst_psi": max(evaluables) if evaluables else None,
            "worst_csi_value": campo_de_card(card, "worst_csi_value"),
        }

    def metric_sections(self, study: Study) -> dict[str, object]:
        """Publica el payload estructurado CT-2 de la card, sin aplanar (D-GOB-3)."""
        secciones = campo_de_card(card_publicada(study, "stability", "card"), "metric_sections")
        return dict(secciones) if isinstance(secciones, Mapping) else {}

    def _publish_artifacts(
        self, study: Study, result: StabilityResult, out_of_model_psi: DataFrame
    ) -> None:
        """Publica los cuatro artefactos estables de ``stability`` y la representatividad."""
        study.artifacts.set("stability", "psi_table", result.psi_table.copy(deep=True))
        study.artifacts.set(
            "stability",
            "stability_metrics",
            result.stability_metrics.copy(deep=True),
        )
        study.artifacts.set("stability", "result", result.model_copy(deep=True))
        study.artifacts.set("stability", "card", result.card.model_copy(deep=True))
        study.artifacts.set("stability", "out_of_model_psi", out_of_model_psi)


def assemble_stability_frame(
    study: Study, config: StabilityConfig
) -> tuple[DataFrame, tuple[str, ...]]:
    """Arma el frame analítico de estabilidad desde los artefactos del ``Study`` (SDD-11 §4).

    Envuelve, sin cambiar una línea de cálculo, lo que ``StabilityStep.execute`` hacía antes de
    llamar al evaluador: lee ``scorecard.score`` y ``calibration.calibrated_pd_frame``, los bins
    congelados sólo con ``csi_source='woe_bins'``, exige que la dirección del score no contradiga
    la ficha del scorecard, abre ``data.frame`` sólo si el score no trae la columna temporal y
    alinea todo por índice. Devuelve el frame y las columnas ``<feature>__points`` (o ``__bin``)
    del CSI, en el orden estable que el evaluador espera.

    Es público desde la enmienda VALIDACION-COTEJADA (D-VAL-16) porque el recálculo del PSI de
    ``validation`` lo reutiliza: así el frame que recalcula es, fila a fila, el del paso de
    estabilidad. Lo que lee está declarado en
    :meth:`~nikodym.stability.config.StabilityConfig.requisitos_de_recalculo_declarados`.
    """
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
    csi_frame = _csi_frame(study, config=config, pd=pd)
    _require_direccion_coherente(study, config.score_direction)
    data_frame = _data_frame_for_temporal_if_needed(
        study,
        score=score,
        config=config,
        pd=pd,
    )
    return _assemble_stability_frame(
        score=score,
        calibrated_pd_frame=calibrated_pd_frame,
        csi_frame=csi_frame,
        data_frame=data_frame,
        config=config,
        pd=pd,
    )


def compute_stability(
    study: Study,
    config: StabilityConfig,
    *,
    audit: AuditSink | None = None,
) -> StabilityResult:
    """Ensambla el frame y corre ``StabilityEvaluator`` con ``config``: el cálculo, sin publicar.

    Es exactamente lo que ``StabilityStep.execute`` hace antes de escribir sus artefactos, y la
    **única** forma de recalcular el PSI dentro del motor: ``validation`` la llama con
    ``consume_stability=False`` (D-VAL-16) y proyecta ``result.stability_metrics`` con
    ``source='recomputed'``. Con la misma sección declarada, el frame recalculado es igual fila a
    fila al artefacto del paso —identidad, cantidad y ``value``—, porque es el mismo motor por la
    misma llamada; sin sección, la receta mínima produce las filas por partición y ninguna
    temporal.

    ``audit`` es el sink al que el evaluador emite sus decisiones. El paso de estabilidad pasa el
    suyo; el recálculo de ``validation`` no pasa ninguno: sus bandas las audita el propio paso de
    validación con su regla ``stability_psi``, y un trail con decisiones ``stability`` de un paso
    que no corrió describiría una corrida distinta de la ejecutada.
    """
    frame, feature_point_columns = assemble_stability_frame(study, config)
    evaluator = StabilityEvaluator.from_config(config)
    if audit is not None:
        evaluator._audit = audit
    return evaluator.evaluate(
        frame.copy(deep=True),
        score_column=config.score_column,
        pd_column=config.pd_column,
        partition_column=config.partition_column,
        feature_point_columns=feature_point_columns,
    )


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


def _require_direccion_coherente(study: Study, declarada: str) -> None:
    """Detiene la corrida si esta sección describe el puntaje al revés de como se construyó.

    Es el hermano de la guarda de ``performance`` (D-DIR-4), y aquí la consecuencia es distinta y
    hay que decirla bien: **este campo no entra a ningún cálculo** —PSI y CSI comparan
    distribuciones binadas y son invariantes al signo—, sino a la ficha que el informe publica. Con
    la respuesta contraria a la de la tarjeta, el mismo documento afirma dos orientaciones del mismo
    puntaje y el lector no tiene cómo saber cuál rige.

    Que no cambie una cifra no lo vuelve inocuo: el informe es el entregable, y una contradicción
    publicada en él es exactamente lo que este motor existe para no producir.

    La ficha se lee con :func:`~nikodym.core.steps.campo_de_card`, no con ``getattr``: una ficha
    inyectada por la puerta pública ``nikodym.run(..., artifacts=...)`` llega como ``Mapping`` y
    ``getattr`` devolvía ``None``, con lo que una dirección contraria pasaba en silencio (pasada 6
    de Codex sobre la enmienda VALIDACION-COTEJADA). Como el ensamblador se comparte con el
    recálculo de ``validation``, la guarda queda honesta para los dos.
    """
    if not study.artifacts.has("scorecard", "card"):
        return
    construida = campo_de_card(study.artifacts.get("scorecard", "card"), "score_direction")
    if construida is None or construida == declarada:
        return
    raise ConfigError(
        "La tarjeta de puntaje se construyó con una convención y la estabilidad la describe con "
        f"la contraria (la tarjeta declara '{construida}' y esta sección '{declarada}'). El "
        "informe publicaría las dos y nadie sabría cuál vale. Deja scorecard.score_direction y "
        "stability.score_direction con el mismo valor."
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


def _csi_frame(study: Study, *, config: StabilityConfig, pd: Any) -> DataFrame | None:
    """Obtiene etiquetas de bins sólo cuando son la fuente CSI elegida."""
    if config.csi_source == "score_points":
        return None
    if not study.artifacts.has("binning", "bin_frame"):
        raise StabilityDataError(
            "stability.csi_source='woe_bins' requiere el artefacto binning.bin_frame "
            "producido por los bins congelados del fit."
        )
    return _as_dataframe(study.artifacts.get("binning", "bin_frame"), pd, "binning.bin_frame").copy(
        deep=True
    )


def _assemble_stability_frame(
    *,
    score: DataFrame,
    calibrated_pd_frame: DataFrame,
    data_frame: DataFrame | None,
    config: StabilityConfig,
    pd: Any,
    csi_frame: DataFrame | None = None,
) -> tuple[DataFrame, tuple[str, ...]]:
    """Alinea score, PD calibrada y columna temporal por índice para el evaluator."""
    _validate_unique_columns(score, artifact="scorecard.score")
    _validate_unique_columns(calibrated_pd_frame, artifact="calibration.calibrated_pd_frame")
    _validate_unique_index(score, artifact="scorecard.score")
    _validate_unique_index(calibrated_pd_frame, artifact="calibration.calibrated_pd_frame")
    if data_frame is not None:
        _validate_unique_columns(data_frame, artifact="data.frame")
        _validate_unique_index(data_frame, artifact="data.frame")
    if csi_frame is not None:
        _validate_unique_columns(csi_frame, artifact="binning.bin_frame")
        _validate_unique_index(csi_frame, artifact="binning.bin_frame")

    score_point_columns = _feature_point_columns(score)
    feature_point_columns = (
        score_point_columns
        if csi_frame is None
        else _feature_bin_columns_for_score(score_point_columns, csi_frame)
    )
    _validate_required_columns(
        score,
        (
            (config.score_column, *feature_point_columns)
            if csi_frame is None
            else (config.score_column,)
        ),
        artifact="scorecard.score",
    )
    _validate_required_columns(
        calibrated_pd_frame,
        (config.partition_column, config.pd_column),
        artifact="calibration.calibrated_pd_frame",
    )
    _validate_aligned_indexes(score, calibrated_pd_frame)
    if csi_frame is not None:
        _validate_aligned_indexes(csi_frame, calibrated_pd_frame, left_name="binning.bin_frame")

    base = calibrated_pd_frame.loc[:, [config.partition_column, config.pd_column]].copy(deep=True)
    parts: list[DataFrame] = [
        base,
        score.loc[base.index, [config.score_column]].copy(deep=True),
    ]
    if feature_point_columns and csi_frame is None:
        parts.append(score.loc[base.index, list(feature_point_columns)].copy(deep=True))
    elif feature_point_columns:
        assert csi_frame is not None
        parts.append(csi_frame.loc[base.index, list(feature_point_columns)].copy(deep=True))

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


def _validate_aligned_indexes(
    score: DataFrame,
    calibrated_pd_frame: DataFrame,
    *,
    left_name: str = "scorecard.score",
) -> None:
    """Exige que score y PD calibrada cubran exactamente las mismas etiquetas."""
    missing_in_score = calibrated_pd_frame.index.difference(score.index)
    extra_score = score.index.difference(calibrated_pd_frame.index)
    if len(missing_in_score) or len(extra_score):
        raise StabilityDataError(
            f"{left_name} y calibration.calibrated_pd_frame no tienen el mismo índice: "
            f"faltan_en_score={missing_in_score.astype(str).tolist()}, "
            f"sobran_en_score={extra_score.astype(str).tolist()}."
        )


def _feature_point_columns(score: DataFrame) -> tuple[str, ...]:
    """Deriva columnas ``<feature>__points`` desde ``scorecard.score`` en orden estable."""
    return tuple(
        sorted(str(column) for column in score.columns if str(column).endswith(_POINTS_SUFFIX))
    )


def _feature_bin_columns_for_score(
    score_point_columns: tuple[str, ...], frame: DataFrame
) -> tuple[str, ...]:
    """Mapea sólo las features finales del scorecard a sus bins congelados.

    ``binning.bin_frame`` conserva todas las variables candidatas, incluidas las que selección o
    modelo descartaron. CSI por bins cambia la fuente de tramos, no el universo de variables del
    scorecard: por eso el orden y la pertenencia nacen de ``scorecard.score`` y nunca del frame de
    binning completo.
    """
    if not score_point_columns:
        raise StabilityDataError(
            "stability.csi_source='woe_bins' requiere columnas finales '<feature>__points' "
            "en scorecard.score."
        )
    columns = tuple(f"{column.removesuffix(_POINTS_SUFFIX)}__bin" for column in score_point_columns)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise StabilityDataError(
            "binning.bin_frame no contiene los bins congelados de todas las features finales: "
            f"faltan={missing!r}."
        )
    return columns


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
            if str(column).lower() in TEMPORAL_CANDIDATE_NAMES
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
