"""Paso orquestable de la capa ``ml`` (SDD-12 §7/§9; CT-1).

``MLStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``ml``: entrena el
challenger de machine learning (SVM / Random Forest / XGBoost / LightGBM / CatBoost, seleccionable
por config), predice su PD, la compara cabeza-a-cabeza contra el scorecard campeón **reusando** los
evaluadores de SDD-11 (nunca reimplementa AUC/Gini/KS/PSI), calibra opcionalmente **reusando**
``PDCalibrator`` (SDD-10), emite las decisiones auditables (§9) y publica las siete claves estables
bajo ``domain='ml'``.

**``requires`` dinámicos (CT-1, SDD-12 §2/§6).** ``from_config`` compone las dependencias según
``feature_source``: siempre ``data.labels``/``data.splits``/``model.raw_pd_frame``; más
``binning.woe_frame``+``binning.result`` (``binning_woe``) o
``selection.selected_woe_frame``+``selected_woe_columns`` (``selection_woe``); con
``monotonic.mode='from_binning'`` se añade ``binning.tables``+``binning.result`` para derivar la
monotonía por variable. Un ``requires`` ausente levanta
:class:`~nikodym.core.exceptions.ArtifactNotFoundError` **antes** de ejecutar.

**Consumo OPCIONAL de ``tuning`` (rev. aditiva SDD-13 §6, deuda B-ML-TUN).** Si el ``ArtifactStore``
contiene ``("tuning","best_config")`` al ejecutar (``tuning`` corre **antes** en el orden por
defecto), ``ml`` sustituye **sólo** sus ``hyperparameters`` por los tuneados ``θ*`` antes de
construir el challenger; el resto de la ``MLConfig`` efectiva queda invariante. Ausente ese
artefacto, ``ml`` usa ``cfg.hyperparameters`` y su comportamiento es **byte-idéntico** al de SDD-12.
Es un ``requires`` **opcional** (comprobación oportunista, **no** dependencia dura): una corrida sin
``tuning`` nunca falla por su ausencia. Mismo patrón aditivo con que ``validation`` consume la PD de
``ml`` (deuda B-VAL). La señal ``hyperparameters_source ∈ {"tuning", "config"}`` queda en la
decisión ``ml_backend`` y en la card para que el reporte distinga ``θ*`` de la config manual.

**Monotonía correcta por variable (SDD-12 §7).** El estimador (``from_binning``) aplica ``-1``
uniforme; el step **deriva** la dirección real por variable desde las tablas WoE de ``binning``
(``-1`` si la tendencia WoE es monótona, ``0`` si es no monótona/invertida) y la pasa **explícita**
al estimador, evitando forzar una constraint espuria (riesgo regulatorio).

**Núcleo liviano (SDD-12 §9).** El módulo **no** importa ``pandas``/``numpy`` ni los backends ML en
import time; ``nikodym.ml`` lo importa sólo para ejecutar ``@register('standard', domain='ml')``.
El estimador, los evaluadores, el calibrador y ``pandas``/``numpy`` se cargan **perezosamente**
dentro de ``execute``. El motor v1 es determinista pero ``ml`` **sí** consume el ``rng`` (el
estimador lo usa para el recorte de early stopping y la semilla del backend).

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.ml.config import ComparisonMetric, MLConfig, MonotonicMode
from nikodym.ml.exceptions import MLComparisonError, MLConfigError, MLDataError
from nikodym.ml.results import (
    Better,
    ComparisonSource,
    MLBackendMetadata,
    MLCardSection,
    MLComparisonRecord,
    MLResult,
)

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.ml.estimator import MLChallenger

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
else:
    AuditEvent: TypeAlias = Any
    Study: TypeAlias = Any
    MLChallenger: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["ML_ARTIFACTS", "MLStep"]

ML_ARTIFACTS: Final[tuple[str, ...]] = (
    "estimator",
    "pd_frame",
    "calibrated_pd_frame",
    "comparison",
    "backend_metadata",
    "result",
    "card",
)
_ML_EXTRA_MESSAGE: Final = "MLStep requiere pandas/numpy; instale nikodym[ml]."
_DATA_DOMAIN: Final = "data"
_MODEL_DOMAIN: Final = "model"
_BINNING_DOMAIN: Final = "binning"
_SELECTION_DOMAIN: Final = "selection"
# Dominio del artefacto opcional aguas arriba (θ* tuneado, rev. aditiva SDD-13 §6, deuda B-ML-TUN).
_TUNING_DOMAIN: Final = "tuning"
# Columnas internas del frame analítico de comparación (nombres estables, aislados del config).
_CMP_PARTITION: Final = "partition"
_CMP_TARGET: Final = "target"
_CMP_LINEAR: Final = "linear_predictor"
_CMP_PD: Final = "pd_raw"
# Columnas fijas del campeón en ``model.raw_pd_frame`` (SDD-08 §prov).
_CHAMPION_LINEAR: Final = "linear_predictor"
_CHAMPION_PD_RAW: Final = "pd_raw"
# Recorte estricto a (0, 1) para que evaluadores/calibrador (que exigen PD interior) acepten la PD
# del challenger, cuya predicción puede tocar 0/1 (hojas puras). Preserva ranking (clip monótono).
_PD_CLIP_EPS: Final = 1e-9
# Constraint por variable en espacio WoE cuando la tendencia del binning es monótona (SDD-12 §7).
_WOE_MONOTONE_DIRECTION: Final = -1
_WOE_FREE_DIRECTION: Final = 0
# Filas auxiliares de las tablas de binning que no participan de la tendencia de valor.
_NON_VALUE_BINS: Final[frozenset[str]] = frozenset({"Totals", "Total", "Special", "Missing"})
# Métricas de discriminación (performance) vs estabilidad (PSI) para el ruteo de evaluador (§7).
_DISCRIMINATION_METRICS: Final[tuple[ComparisonMetric, ...]] = ("auc", "gini", "ks")
_PSI_METRIC: Final = "psi"
# Mapa comparación temporal → partición representada en la brecha PSI (SDD-12 §6).
_PSI_COMPARISON_TO_PARTITION: Final[dict[str, str]] = {
    "dev_vs_holdout": "holdout",
    "dev_vs_oot": "oot",
}


@register("standard", domain="ml")
class MLStep(AuditableMixin):
    """Orquesta el challenger ML y publica ``domain='ml'`` (SDD-12 §4/§7)."""

    name: str = "ml"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = tuple(("ml", key) for key in ML_ARTIFACTS)

    def __init__(self, config: MLConfig) -> None:
        """Construye el paso desde la sección ``MLConfig`` y arma ``requires`` (CT-1)."""
        self.config = config
        self.requires = _requires_for(config)

    @classmethod
    def from_config(cls, cfg: MLConfig) -> MLStep:
        """Construye ``MLStep`` desde ``NikodymConfig.ml``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> MLResult:
        """Entrena, predice, compara, (opcional) calibra, audita y publica siete artefactos (§7)."""
        np = _import_numpy()
        pd = _import_pandas()
        from nikodym.ml.estimator import MLChallenger

        cfg = _ml_config_from_study(study, fallback=self.config)
        if cfg.feature_source == "data_raw":
            raise MLConfigError(
                "feature_source='data_raw' está diferido (FALTA-DATO-ML-1): use 'binning_woe' o "
                "'selection_woe'. El modo crudo exige política de imputación por variable."
            )
        cfg, hyperparameters_source = _apply_tuning_best_config(study, cfg)
        requires = _requires_for(cfg)
        _require_present(study, requires)

        target_col, partition_col = _read_frame_metadata(study)
        feature_frame, feature_columns = _read_feature_frame(study, cfg, pd)
        _validate_features(feature_frame, feature_columns, target_col, partition_col)
        raw_pd_frame = _read_champion_frame(study, target_col, partition_col, pd)

        monotonic_mode, monotonic_explicit = self._resolve_monotonic(
            study, cfg, feature_columns, pd, np
        )
        challenger = MLChallenger(
            backend=cfg.backend,
            hyperparameters=cfg.hyperparameters,
            monotonic_mode=monotonic_mode,
            monotonic_explicit=monotonic_explicit,
            monotonic_on_unsupported=cfg.monotonic.on_unsupported,
            validation_fraction=cfg.train.validation_fraction,
            early_stopping_rounds=cfg.train.early_stopping_rounds,
            require_both_classes=cfg.train.require_both_classes,
            deterministic=cfg.deterministic,
            n_threads=cfg.n_threads,
        )

        partition_series = feature_frame[partition_col].astype("string")
        fit_frame, fit_target = _fit_partition(
            feature_frame, feature_columns, partition_series, target_col, cfg
        )
        challenger.fit(fit_frame, fit_target, rng=rng, audit=self._audit)

        pd_frame = _predict_pd_frame(
            challenger,
            feature_frame,
            feature_columns,
            partition_series,
            partition_col,
            target_col,
            cfg,
            pd,
        )
        comparison = _compare_champion(
            cfg, pd_frame, raw_pd_frame, partition_col, target_col, pd, np
        )
        calibrated = _maybe_calibrate(study, cfg, pd_frame, pd, np)

        importances = _top_importances(challenger, cfg)
        backend_metadata = _build_backend_metadata(cfg, challenger, importances)
        card = _build_card(
            cfg, challenger, comparison, importances, hyperparameters_source=hyperparameters_source
        )
        result = MLResult(
            estimator=challenger,
            pd_frame=pd_frame,
            calibrated_pd_frame=calibrated,
            comparison=comparison,
            backend_metadata=backend_metadata,
            card=card,
        )

        self._emit_decisions(
            cfg,
            challenger,
            feature_columns=feature_columns,
            monotonic_mode=monotonic_mode,
            monotonic_explicit=monotonic_explicit,
            comparison=comparison,
            calibrated=calibrated is not None,
            hyperparameters_source=hyperparameters_source,
        )
        _publish_artifacts(
            study, challenger, pd_frame, calibrated, comparison, backend_metadata, result, card
        )
        return result

    # --- monotonía derivada (deuda crítica B12.4 nitpick #1, SDD-12 §7) ------------------------

    def _resolve_monotonic(
        self, study: Study, cfg: MLConfig, feature_columns: tuple[str, ...], pd: Any, np: Any
    ) -> tuple[MonotonicMode, dict[str, int] | None]:
        """Resuelve ``(mode, explicit)`` para el estimador traduciendo ``from_binning`` a explícito.

        ``from_binning`` deriva, por variable WoE, ``-1`` si su tendencia WoE es monótona y ``0`` si
        es no monótona (invertida/peak/valley), inspeccionando las tablas de ``binning`` (el
        estimador aplica ``-1`` uniforme e ignora esa excepción, SDD-12 §7).
        """
        mode = cfg.monotonic.mode
        if mode == "off":
            return "off", None
        if mode == "explicit":
            return "explicit", {
                str(key): int(value) for key, value in cfg.monotonic.explicit.items()
            }
        woe_column_map = _read_woe_column_map(study)
        tables = _read_binning_tables(study)
        directions = _derive_from_binning(feature_columns, woe_column_map, tables, pd=pd, np=np)
        return "explicit", directions

    # --- auditoría (§9) ------------------------------------------------------------------------

    def _emit_decisions(
        self,
        cfg: MLConfig,
        challenger: MLChallenger,
        *,
        feature_columns: tuple[str, ...],
        monotonic_mode: MonotonicMode,
        monotonic_explicit: dict[str, int] | None,
        comparison: tuple[MLComparisonRecord, ...],
        calibrated: bool,
        hyperparameters_source: str,
    ) -> None:
        """Registra el ``log_decision`` §9: backend/semilla/features/monotonía/train/comparación."""
        self.log_decision(
            regla="ml_backend",
            umbral=cfg.backend,
            valor={
                "backend": cfg.backend,
                "backend_version": challenger.backend_version_,
                "hyperparameters": _hyperparameters_dict(cfg),
                "hyperparameters_source": hyperparameters_source,
            },
            accion="entrenar_challenger",
        )
        self.log_decision(
            regla="ml_seed",
            umbral=int(challenger.seed_),
            valor={
                "seed": int(challenger.seed_),
                "n_threads": int(challenger.n_threads_),
                "deterministic": bool(challenger.deterministic_),
            },
            accion="sembrar_backend",
        )
        self.log_decision(
            regla="ml_feature_source",
            umbral=cfg.feature_source,
            valor={"feature_source": cfg.feature_source, "n_features": len(feature_columns)},
            accion="seleccionar_features",
        )
        zero_features = sorted(
            name for name, direction in (monotonic_explicit or {}).items() if direction == 0
        )
        self.log_decision(
            regla="ml_monotonic",
            umbral=cfg.monotonic.mode,
            valor={
                "config_mode": cfg.monotonic.mode,
                "effective_mode": monotonic_mode,
                "n_constrained": sum(
                    1 for direction in (monotonic_explicit or {}).values() if direction != 0
                ),
                "free_features": zero_features,
            },
            accion="aplicar_monotonia",
        )
        best_iteration = challenger.best_iteration_
        self.log_decision(
            regla="ml_train",
            umbral=cfg.train.fit_partition,
            valor={
                "fit_partition": cfg.train.fit_partition,
                "predict_partitions": list(cfg.train.predict_partitions),
                "validation_fraction": cfg.train.validation_fraction,
                "best_iteration": None if best_iteration is None else int(best_iteration),
            },
            accion="ajustar_challenger",
        )
        self.log_decision(
            regla="ml_comparison",
            umbral=cfg.comparison.tie_tolerance,
            valor={"records": [_comparison_payload(record) for record in comparison]},
            accion="comparar_campeon_vs_challenger",
        )
        self.log_decision(
            regla="ml_calibration",
            umbral=cfg.calibrate_challenger,
            valor={"calibrated": calibrated},
            accion="calibrar_challenger" if calibrated else "omitir_calibracion",
        )
        if not challenger.deterministic_:
            self.log_decision(
                regla="ml_determinism",
                umbral=True,
                valor={
                    "deterministic": False,
                    "n_threads": int(challenger.n_threads_),
                    "byte_reproducible": False,
                },
                accion="marcar_no_byte_reproducible",
            )


# ─────────────────────────── contrato de dependencias (CT-1) ───────────────────────────


def _requires_for(cfg: MLConfig) -> tuple[ArtifactKey, ...]:
    """Compone las claves ``requires`` según ``feature_source`` y ``monotonic.mode`` (§2/§6)."""
    requires: list[ArtifactKey] = [
        (_DATA_DOMAIN, "labels"),
        (_DATA_DOMAIN, "splits"),
        (_MODEL_DOMAIN, "raw_pd_frame"),
    ]
    source = cfg.feature_source
    if source == "binning_woe":
        requires += [(_BINNING_DOMAIN, "woe_frame"), (_BINNING_DOMAIN, "result")]
    elif source == "selection_woe":
        requires += [
            (_SELECTION_DOMAIN, "selected_woe_frame"),
            (_SELECTION_DOMAIN, "selected_woe_columns"),
        ]
    else:  # data_raw (Literal exhaustivo; el step lo rechaza en execute, FALTA-DATO-ML-1)
        requires += [(_DATA_DOMAIN, "frame")]
    if cfg.monotonic.mode == "from_binning" and source in {"binning_woe", "selection_woe"}:
        requires += [(_BINNING_DOMAIN, "tables"), (_BINNING_DOMAIN, "result")]
    return tuple(dict.fromkeys(requires))


def _require_present(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Exige que cada artefacto ``requires`` (CT-1) esté en el ``ArtifactStore``."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'ml' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


# ─────────────────────── consumo opcional de tuning (rev. aditiva B-ML-TUN) ───────────────────────


def _apply_tuning_best_config(study: Study, cfg: MLConfig) -> tuple[MLConfig, str]:
    """Sustituye ``hyperparameters`` por los de ``tuning.best_config`` si el artefacto está.

    ``requires`` **opcional** (SDD-13 §6, deuda B-ML-TUN): si ``("tuning","best_config")`` existe en
    el ``ArtifactStore`` (``tuning`` corrió antes), toma **sólo** ``best_config.hyperparameters``
    (``θ*``) y los reemplaza en la ``MLConfig`` efectiva vía ``model_copy`` (el resto invariante;
    defensivo aunque el productor ya garantice el invariante SDD-13 §6). Ausente el artefacto,
    devuelve ``cfg`` intacto y el comportamiento es byte-idéntico a SDD-12. Devuelve
    ``(cfg_efectiva, source)`` con ``source ∈ {"tuning", "config"}``.
    """
    if not study.artifacts.has(_TUNING_DOMAIN, "best_config"):
        return cfg, "config"
    best_config = _as_ml_config(study.artifacts.get(_TUNING_DOMAIN, "best_config"))
    tuned = cfg.model_copy(update={"hyperparameters": best_config.hyperparameters})
    return tuned, "tuning"


def _as_ml_config(value: object) -> MLConfig:
    """Valida que ``tuning.best_config`` sea una ``MLConfig`` antes de leer sus hiperparámetros."""
    if isinstance(value, MLConfig):
        return value
    raise MLDataError(
        f"El artefacto 'tuning.best_config' debe ser una MLConfig (SDD-13 §6); "
        f"tipo observado={type(value).__name__}."
    )


# ─────────────────────────── lectura de artefactos ───────────────────────────


def _read_frame_metadata(study: Study) -> tuple[str, str]:
    """Extrae ``target_col``/``partition_col`` de ``data.labels``/``data.splits`` (SDD-02)."""
    labels = study.artifacts.get(_DATA_DOMAIN, "labels")
    splits = study.artifacts.get(_DATA_DOMAIN, "splits")
    target_col = getattr(labels, "target_col", None)
    partition_col = getattr(splits, "partition_col", None)
    if not isinstance(target_col, str):
        raise MLDataError(
            "El artefacto ('data', 'labels') debe exponer target_col: str (LabeledFrame de SDD-02)."
        )
    if not isinstance(partition_col, str):
        raise MLDataError(
            "El artefacto ('data', 'splits') debe exponer partition_col: str (PartitionResult)."
        )
    return target_col, partition_col


def _read_feature_frame(study: Study, cfg: MLConfig, pd: Any) -> tuple[DataFrame, tuple[str, ...]]:
    """Lee el frame de features y sus columnas WoE según ``feature_source`` (copia defensiva)."""
    if cfg.feature_source == "binning_woe":
        frame = _as_dataframe(
            study.artifacts.get(_BINNING_DOMAIN, "woe_frame"), pd, "binning.woe_frame"
        )
        woe_column_map = _read_woe_column_map(study)
        columns = tuple(woe for woe in woe_column_map.values() if woe in frame.columns)
    else:  # selection_woe (data_raw se rechaza antes en execute)
        frame = _as_dataframe(
            study.artifacts.get(_SELECTION_DOMAIN, "selected_woe_frame"),
            pd,
            "selection.selected_woe_frame",
        )
        columns = _as_string_tuple(
            study.artifacts.get(_SELECTION_DOMAIN, "selected_woe_columns"),
            "selection.selected_woe_columns",
        )
    return frame.copy(deep=True), columns


def _read_champion_frame(study: Study, target_col: str, partition_col: str, pd: Any) -> DataFrame:
    """Lee y valida ``model.raw_pd_frame`` (PD cruda del campeón para la comparación)."""
    frame = _as_dataframe(
        study.artifacts.get(_MODEL_DOMAIN, "raw_pd_frame"), pd, "model.raw_pd_frame"
    )
    required = (partition_col, target_col, _CHAMPION_LINEAR, _CHAMPION_PD_RAW)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise MLDataError(f"model.raw_pd_frame no contiene columnas requeridas: {joined}.")
    return frame.copy(deep=True)


def _read_woe_column_map(study: Study) -> dict[str, str]:
    """Lee ``woe_column_map`` (feature cruda → columna ``<feature>__woe``) de ``binning.result``."""
    result = study.artifacts.get(_BINNING_DOMAIN, "result")
    woe_column_map = getattr(result, "woe_column_map", None)
    if not isinstance(woe_column_map, dict) or not woe_column_map:
        raise MLDataError(
            "El artefacto ('binning', 'result') debe exponer woe_column_map: dict no vacío."
        )
    return {str(key): str(value) for key, value in woe_column_map.items()}


def _read_binning_tables(study: Study) -> dict[str, Any]:
    """Lee ``binning.tables`` (una tabla WoE por feature) para derivar la monotonía."""
    tables = study.artifacts.get(_BINNING_DOMAIN, "tables")
    if not isinstance(tables, dict) or not tables:
        raise MLDataError(
            "El artefacto ('binning', 'tables') debe ser un dict no vacío de tablas WoE "
            "por feature."
        )
    return {str(key): value for key, value in tables.items()}


# ─────────────────────────── monotonía derivada del binning ───────────────────────────


def _derive_from_binning(
    feature_columns: tuple[str, ...],
    woe_column_map: dict[str, str],
    tables: dict[str, Any],
    *,
    pd: Any,
    np: Any,
) -> dict[str, int]:
    """Traduce cada columna WoE a ``-1`` (tendencia monótona) o ``0`` (no monótona) desde su tabla.

    Invierte ``woe_column_map`` para localizar la feature cruda de cada columna ``<feature>__woe``
    y clasifica su tabla de binning: si los WoE de sus bins de valor son monótonos, la constraint
    ``-1`` (PD no creciente en WoE) es válida; si no, se libera con ``0`` (SDD-12 §7).
    """
    inverse = {woe: raw for raw, woe in woe_column_map.items()}
    directions: dict[str, int] = {}
    for woe_column in feature_columns:
        raw = inverse.get(woe_column)
        if raw is None or raw not in tables:
            raise MLDataError(
                f"No se pudo mapear la columna WoE '{woe_column}' a su tabla de binning para "
                "derivar la monotonía (woe_column_map/tables inconsistentes)."
            )
        directions[woe_column] = _woe_monotone_direction(tables[raw], pd=pd, np=np)
    return directions


def _woe_monotone_direction(table: Any, *, pd: Any, np: Any) -> int:
    """Devuelve ``-1`` si el WoE de los bins de valor es monótono, ``0`` si no (SDD-12 §7)."""
    if not hasattr(table, "columns"):
        raise MLDataError("Cada entrada de binning.tables debe ser un pandas.DataFrame.")
    missing = [column for column in ("Bin", "WoE") if column not in table.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise MLDataError(f"La tabla de binning no contiene columnas requeridas: {joined}.")
    bin_labels = table["Bin"].astype(str)
    index_labels = pd.Index(table.index).astype(str)
    value_mask = ~(bin_labels.isin(_NON_VALUE_BINS) | (index_labels == "Totals"))
    woe = pd.to_numeric(table.loc[value_mask.to_numpy(), "WoE"], errors="coerce").to_numpy(
        dtype="float64", copy=True
    )
    woe = woe[np.isfinite(woe)]
    if woe.size <= 1:
        return _WOE_MONOTONE_DIRECTION
    diffs = np.diff(woe)
    non_decreasing = bool((diffs >= 0.0).all())
    non_increasing = bool((diffs <= 0.0).all())
    return _WOE_MONOTONE_DIRECTION if (non_decreasing or non_increasing) else _WOE_FREE_DIRECTION


# ─────────────────────────── entrenamiento y predicción ───────────────────────────


def _validate_features(
    frame: DataFrame,
    feature_columns: tuple[str, ...],
    target_col: str,
    partition_col: str,
) -> None:
    """Valida columnas de features presentes, no vacías y sin colisión con partición/target."""
    if not feature_columns:
        raise MLDataError(
            "MLStep no encontró columnas de features WoE para entrenar el challenger."
        )
    for column in (partition_col, target_col):
        if column not in frame.columns:
            raise MLDataError(
                f"El frame de features no contiene la columna estructural '{column}'."
            )
    missing = [column for column in feature_columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise MLDataError(f"El frame de features no contiene columnas de features: {joined}.")
    if partition_col in feature_columns or target_col in feature_columns:
        raise MLDataError(
            "Las columnas de features no pueden incluir la partición ni el target del pipeline."
        )


def _fit_partition(
    frame: DataFrame,
    feature_columns: tuple[str, ...],
    partition_series: Series,
    target_col: str,
    cfg: MLConfig,
) -> tuple[DataFrame, Series]:
    """Selecciona la partición de ajuste con target no nulo (anti-leakage, como el campeón)."""
    mask = (partition_series.eq(cfg.train.fit_partition) & frame[target_col].notna()).to_numpy()
    fit_frame = frame.loc[mask, list(feature_columns)].copy(deep=True)
    fit_target = frame.loc[mask, target_col].copy(deep=True)
    return fit_frame, fit_target


def _predict_pd_frame(
    challenger: MLChallenger,
    frame: DataFrame,
    feature_columns: tuple[str, ...],
    partition_series: Series,
    partition_col: str,
    target_col: str,
    cfg: MLConfig,
    pd: Any,
) -> DataFrame:
    """Predice ``pd_hat`` en ``predict_partitions`` y arma ``pd_frame`` alineado por índice (§6)."""
    mask = partition_series.isin(list(cfg.train.predict_partitions)).to_numpy()
    predict_frame = frame.loc[mask, list(feature_columns)]
    if len(predict_frame.index) == 0:
        raise MLDataError(
            "Ninguna fila en predict_partitions "
            f"{list(cfg.train.predict_partitions)} para predecir la PD del challenger."
        )
    pd_hat = challenger.predict_pd(predict_frame)
    pd_frame = pd.DataFrame(
        {
            cfg.partition_column: frame.loc[mask, partition_col].to_numpy(),
            cfg.target_column: frame.loc[mask, target_col].to_numpy(),
            cfg.pd_hat_column: pd_hat,
        },
        index=predict_frame.index,
    )
    return cast(DataFrame, pd_frame)


# ─────────────────────────── comparación campeón vs challenger (reúso SDD-11) ───────────────────


def _compare_champion(
    cfg: MLConfig,
    pd_frame: DataFrame,
    raw_pd_frame: DataFrame,
    partition_col: str,
    target_col: str,
    pd: Any,
    np: Any,
) -> tuple[MLComparisonRecord, ...]:
    """Compara discriminación (AUC/Gini/KS) y estabilidad (PSI) reusando los evaluadores SDD-11."""
    metrics = tuple(cfg.comparison.metrics)
    comparison_partitions = tuple(cfg.comparison.partitions)
    tolerance = cfg.comparison.tie_tolerance

    champion = _champion_analytic(raw_pd_frame, partition_col, target_col, pd)
    challenger = _challenger_analytic(pd_frame, cfg, pd, np)
    _check_index_alignment(champion, challenger, comparison_partitions)

    records: list[MLComparisonRecord] = []
    discrimination = tuple(metric for metric in metrics if metric in _DISCRIMINATION_METRICS)
    if discrimination:
        champion_disc = _discrimination(champion)
        challenger_disc = _discrimination(challenger)
        for partition in comparison_partitions:
            for metric in discrimination:
                champion_value = champion_disc.get(partition, {}).get(metric)
                challenger_value = challenger_disc.get(partition, {}).get(metric)
                record = _make_record(
                    partition,
                    metric,
                    champion_value,
                    challenger_value,
                    tolerance,
                    source="performance_evaluator",
                )
                if record is not None:
                    records.append(record)
    if _PSI_METRIC in metrics:
        champion_psi = _stability(champion)
        challenger_psi = _stability(challenger)
        for partition in comparison_partitions:
            record = _make_record(
                partition,
                _PSI_METRIC,
                champion_psi.get(partition),
                challenger_psi.get(partition),
                tolerance,
                source="stability_evaluator",
            )
            if record is not None:
                records.append(record)
    return tuple(records)


def _champion_analytic(
    raw_pd_frame: DataFrame, partition_col: str, target_col: str, pd: Any
) -> DataFrame:
    """Arma el frame analítico del campeón (PD cruda, target no nulo) para los evaluadores."""
    frame = pd.DataFrame(
        {
            _CMP_PARTITION: raw_pd_frame[partition_col].to_numpy(),
            _CMP_TARGET: raw_pd_frame[target_col].to_numpy(),
            _CMP_LINEAR: raw_pd_frame[_CHAMPION_LINEAR].to_numpy(),
            _CMP_PD: raw_pd_frame[_CHAMPION_PD_RAW].to_numpy(),
        },
        index=raw_pd_frame.index,
    )
    return cast(DataFrame, frame.loc[frame[_CMP_TARGET].notna()].copy(deep=True))


def _challenger_analytic(pd_frame: DataFrame, cfg: MLConfig, pd: Any, np: Any) -> DataFrame:
    """Arma el frame analítico del challenger recortando ``pd_hat`` a (0, 1) sin alterar ranking."""
    pd_hat = pd_frame[cfg.pd_hat_column].to_numpy(dtype="float64", copy=True)
    pd_interior = np.clip(pd_hat, _PD_CLIP_EPS, 1.0 - _PD_CLIP_EPS)
    linear = np.log(pd_interior / (1.0 - pd_interior))
    frame = pd.DataFrame(
        {
            _CMP_PARTITION: pd_frame[cfg.partition_column].to_numpy(),
            _CMP_TARGET: pd_frame[cfg.target_column].to_numpy(),
            _CMP_LINEAR: linear,
            _CMP_PD: pd_interior,
        },
        index=pd_frame.index,
    )
    return cast(DataFrame, frame.loc[frame[_CMP_TARGET].notna()].copy(deep=True))


def _check_index_alignment(
    champion: DataFrame, challenger: DataFrame, partitions: tuple[str, ...]
) -> None:
    """Exige que campeón y challenger cubran las mismas filas modelables (SDD-12 §6/§8)."""
    wanted = list(partitions)
    champion_index = set(champion.loc[champion[_CMP_PARTITION].astype("string").isin(wanted)].index)
    challenger_index = set(
        challenger.loc[challenger[_CMP_PARTITION].astype("string").isin(wanted)].index
    )
    if champion_index != challenger_index:
        diff = len(champion_index ^ challenger_index)
        raise MLComparisonError(
            "Los índices modelables de campeón y challenger no coinciden en las particiones "
            f"comparadas (filas distintas={diff}): comparación no apples-to-apples."
        )


def _discrimination(frame: DataFrame) -> dict[str, dict[str, Any]]:
    """Evalúa AUC/Gini/KS por partición reusando ``PerformanceEvaluator`` (SDD-11)."""
    from nikodym.performance.evaluator import PerformanceEvaluator

    evaluator = PerformanceEvaluator(evaluation_source="pd_calibrated")
    result = evaluator.evaluate(
        frame,
        score_column=_CMP_LINEAR,
        pd_column=_CMP_PD,
        target_column=_CMP_TARGET,
        partition_column=_CMP_PARTITION,
    )
    metrics: dict[str, dict[str, Any]] = {}
    for record in result.discriminant_records:
        metrics[str(record.partition)] = {
            "auc": record.auc,
            "gini": record.gini,
            "ks": record.ks,
        }
    return metrics


def _stability(frame: DataFrame) -> dict[str, Any]:
    """Evalúa PSI (dev vs holdout/oot) reusando ``StabilityEvaluator`` (SDD-11, sin recalcular)."""
    from nikodym.stability.evaluator import StabilityEvaluator

    evaluator = StabilityEvaluator(temporal_axis="none")
    result = evaluator.evaluate(
        frame,
        score_column=_CMP_LINEAR,
        pd_column=_CMP_PD,
        partition_column=_CMP_PARTITION,
        feature_point_columns=(),
    )
    psi_by_partition: dict[str, Any] = {}
    for record in result.metric_records:
        partition = _PSI_COMPARISON_TO_PARTITION.get(str(record.comparison))
        if record.metric == "score_psi" and partition is not None:
            psi_by_partition[partition] = record.value
    return psi_by_partition


def _make_record(
    partition: str,
    metric: ComparisonMetric,
    champion_value: Any,
    challenger_value: Any,
    tolerance: float,
    *,
    source: ComparisonSource,
) -> MLComparisonRecord | None:
    """Construye un ``MLComparisonRecord`` finito o ``None`` si falta un valor evaluable (§6)."""
    if not _is_finite(champion_value) or not _is_finite(challenger_value):
        return None
    champion = float(champion_value)
    challenger = float(challenger_value)
    delta = challenger - champion
    better = _better(metric, delta, tolerance)
    return MLComparisonRecord(
        partition=partition,
        metric=metric,
        champion_value=champion,
        challenger_value=challenger,
        delta=delta,
        better=better,
        source=source,
    )


def _better(metric: ComparisonMetric, delta: float, tolerance: float) -> Better:
    """Decide el ganador con la tolerancia de empate; PSI premia el menor (más estable, §6)."""
    if abs(delta) <= tolerance:
        return "tie"
    if metric == _PSI_METRIC:
        return "challenger" if delta < 0.0 else "champion"
    return "challenger" if delta > 0.0 else "champion"


# ─────────────────────────── calibración opcional (reúso SDD-10) ───────────────────────────


def _maybe_calibrate(
    study: Study, cfg: MLConfig, pd_frame: DataFrame, pd: Any, np: Any
) -> DataFrame | None:
    """Calibra la PD del challenger reusando ``PDCalibrator`` (SDD-10) si se pide (§7 paso 11)."""
    if not cfg.calibrate_challenger or not cfg.output.publish_calibrated_pd:
        return None
    from nikodym.calibration.calibrator import PDCalibrator

    cal_cfg = _calibration_config_from_study(study)
    pd_hat = pd_frame[cfg.pd_hat_column].to_numpy(dtype="float64", copy=True)
    pd_interior = np.clip(pd_hat, _PD_CLIP_EPS, 1.0 - _PD_CLIP_EPS)
    linear = np.log(pd_interior / (1.0 - pd_interior))
    raw = pd.DataFrame(
        {
            cal_cfg.partition_column: pd_frame[cfg.partition_column].to_numpy(),
            cal_cfg.target_column: pd_frame[cfg.target_column].to_numpy(),
            cal_cfg.linear_predictor_column: linear,
            cal_cfg.pd_raw_column: pd_interior,
        },
        index=pd_frame.index,
    )
    raw = raw.loc[raw[cal_cfg.target_column].notna()].copy(deep=True)
    calibrator = PDCalibrator.from_config(cal_cfg)
    calibrator.fit(raw.copy(deep=True))
    calibrated = calibrator.transform(raw.copy(deep=True))
    return calibrated


def _calibration_config_from_study(study: Study) -> Any:
    """Lee ``NikodymConfig.calibration`` o instancia el default para calibrar el challenger."""
    from nikodym.calibration.config import CalibrationConfig

    raw_config = getattr(study.config, "calibration", None)
    if raw_config is None:
        return CalibrationConfig()
    if isinstance(raw_config, CalibrationConfig):
        return raw_config
    return CalibrationConfig.model_validate(raw_config)


# ─────────────────────────── DTOs de salida (SDD-12 §4) ───────────────────────────


def _top_importances(challenger: MLChallenger, cfg: MLConfig) -> tuple[tuple[str, float], ...]:
    """Selecciona las top-k importancias nativas (gain/split) descendentes por valor (§6)."""
    if not cfg.output.publish_feature_importances:
        return ()
    items = sorted(
        challenger.feature_importances_.items(), key=lambda pair: (-float(pair[1]), str(pair[0]))
    )
    top = items[: cfg.output.top_k_importances]
    return tuple((str(name), float(value)) for name, value in top)


def _build_backend_metadata(
    cfg: MLConfig, challenger: MLChallenger, importances: tuple[tuple[str, float], ...]
) -> MLBackendMetadata:
    """Ensambla ``MLBackendMetadata`` desde los atributos fiteados del challenger (§4/§9)."""
    return MLBackendMetadata(
        backend=cfg.backend,
        backend_version=str(challenger.backend_version_),
        hyperparameters=_hyperparameters_dict(cfg),
        seed=int(challenger.seed_),
        n_threads=int(challenger.n_threads_),
        deterministic=bool(challenger.deterministic_),
        best_iteration=(
            None if challenger.best_iteration_ is None else int(challenger.best_iteration_)
        ),
        feature_importances=importances,
        monotone_constraints=_monotone_pairs(challenger),
    )


def _build_card(
    cfg: MLConfig,
    challenger: MLChallenger,
    comparison: tuple[MLComparisonRecord, ...],
    importances: tuple[tuple[str, float], ...],
    *,
    hyperparameters_source: str = "config",
) -> MLCardSection:
    """Ensambla la tarjeta CT-2 con curvas de comparación, importancias y determinismo (§9)."""
    summary: dict[str, str | int | float | bool] = {
        "backend": cfg.backend,
        "backend_version": str(challenger.backend_version_),
        "feature_source": cfg.feature_source,
        "hyperparameters_source": hyperparameters_source,
        "n_features": len(challenger.feature_names_in_),
        "seed": int(challenger.seed_),
        "n_threads": int(challenger.n_threads_),
        "deterministic": bool(challenger.deterministic_),
        "n_comparison_records": len(comparison),
    }
    if challenger.best_iteration_ is not None:
        summary["best_iteration"] = int(challenger.best_iteration_)
    metric_sections: dict[str, Any] = {
        "comparison_curves": [_comparison_payload(record) for record in comparison],
        "feature_importances": [
            {"feature": name, "importance": value} for name, value in importances
        ],
        "determinism": {
            "deterministic": bool(challenger.deterministic_),
            "n_threads": int(challenger.n_threads_),
            "byte_reproducible": bool(challenger.deterministic_),
        },
    }
    limitations: tuple[str, ...] = (
        "ML es challenger, no reemplaza al scorecard campeón (regulatorio).",
    )
    if not challenger.deterministic_:
        limitations += (
            "Modo performance multihilo: el resultado no es byte-reproducible (GBDT multihilo).",
        )
    assumptions: tuple[str, ...] = (
        "Discriminación comparada sobre PD cruda (invariante a la calibración).",
    )
    return MLCardSection(
        summary=summary,
        metric_sections=metric_sections,
        assumptions=assumptions,
        limitations=limitations,
    )


def _monotone_pairs(challenger: MLChallenger) -> tuple[tuple[str, int], ...]:
    """Empareja nombres de features con sus constraints aplicadas (orden de columnas de X, §6)."""
    constraints = tuple(challenger.monotone_constraints_)
    if not constraints:
        return ()
    names = tuple(challenger.feature_names_in_)
    return tuple(
        (str(name), int(direction)) for name, direction in zip(names, constraints, strict=True)
    )


def _hyperparameters_dict(cfg: MLConfig) -> dict[str, str | int | float | bool | None]:
    """Vuelca los hiperparámetros efectivos del backend a un dict de escalares (auditoría/card)."""
    params = cfg.hyperparameters
    if params is None:  # pragma: no cover - MLConfig siempre resuelve los defaults del backend
        return {}
    return cast("dict[str, str | int | float | bool | None]", params.model_dump())


def _comparison_payload(record: MLComparisonRecord) -> dict[str, Any]:
    """Proyecta un ``MLComparisonRecord`` a un dict serializable (auditoría/card)."""
    return {
        "partition": record.partition,
        "metric": record.metric,
        "champion_value": record.champion_value,
        "challenger_value": record.challenger_value,
        "delta": record.delta,
        "better": record.better,
        "source": record.source,
    }


# ─────────────────────────── publicación ───────────────────────────


def _publish_artifacts(
    study: Study,
    challenger: MLChallenger,
    pd_frame: DataFrame,
    calibrated: DataFrame | None,
    comparison: tuple[MLComparisonRecord, ...],
    backend_metadata: MLBackendMetadata,
    result: MLResult,
    card: MLCardSection,
) -> None:
    """Publica las siete claves estables del dominio ``ml`` (copias defensivas)."""
    study.artifacts.set("ml", "estimator", challenger)
    study.artifacts.set("ml", "pd_frame", pd_frame.copy(deep=True))
    study.artifacts.set(
        "ml",
        "calibrated_pd_frame",
        None if calibrated is None else calibrated.copy(deep=True),
    )
    study.artifacts.set("ml", "comparison", comparison)
    study.artifacts.set("ml", "backend_metadata", backend_metadata.model_copy(deep=True))
    study.artifacts.set("ml", "result", result.model_copy(deep=True))
    study.artifacts.set("ml", "card", card.model_copy(deep=True))


# ─────────────────────────── utilidades de import/config/datos ───────────────────────────


def _import_numpy() -> Any:
    """Importa ``numpy`` localmente para preservar el import liviano del paquete ``ml``."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError(_ML_EXTRA_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete ``ml``."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:  # pragma: no cover - pandas es dep base de data
        raise MissingDependencyError(_ML_EXTRA_MESSAGE) from exc


def _ml_config_from_study(study: Study, *, fallback: MLConfig) -> MLConfig:
    """Lee ``NikodymConfig.ml`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "ml", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, MLConfig):
        return raw_config
    return MLConfig.model_validate(raw_config)


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise MLDataError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_string_tuple(value: object, artifact: str) -> tuple[str, ...]:
    """Valida un artefacto ``tuple[str, ...]`` (p.ej. ``selection.selected_woe_columns``)."""
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(cast("list[str]", list(value)))
    raise MLDataError(
        f"El artefacto '{artifact}' debe ser tuple[str, ...]; "
        f"tipo observado={type(value).__name__}."
    )


def _is_finite(value: Any) -> bool:
    """Indica si ``value`` es un número real finito (excluye ``None``/``NaN``/``inf``/``bool``)."""
    if value is None or isinstance(value, bool):
        return False
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(candidate)
