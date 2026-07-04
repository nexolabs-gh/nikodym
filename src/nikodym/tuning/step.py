"""Paso orquestable de la capa ``tuning`` (SDD-13 §7/§9; CT-1).

``TuningStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``tuning``: corre
la búsqueda de hiperparámetros con Optuna (:class:`~nikodym.tuning.optimizer.TuningOptimizer`) que
**hereda** de ``ml`` (SDD-12) el backend, la fuente de features y la monotonía, y publica las siete
claves estables bajo ``domain='tuning'``. Es el **gemelo** de ``ml`` que corre **antes**: entrega
los hiperparámetros ``θ*`` que ``ml`` consumirá para ajustar el challenger definitivo.

**``requires`` dinámicos (CT-1, SDD-13 §2/§6).** Las claves son las **mismas** que ``ml``, **menos**
``model.raw_pd_frame`` (``tuning`` no compara contra el campeón): siempre ``data.labels``/
``data.splits``; más ``binning.woe_frame``+``binning.result`` (``binning_woe``) o
``selection.selected_woe_frame``+``selected_woe_columns`` (``selection_woe``); con
``monotonic.mode='from_binning'`` se añade ``binning.tables``+``binning.result``. Como el motor
resuelve el step con ``TuningConfig`` (no ``MLConfig``), ``from_config`` declara los ``requires``
según los **defaults** de ``ml`` (``binning_woe`` + ``from_binning``); ``execute`` los **re-deriva**
desde la ``NikodymConfig.ml`` real y **re-valida** su presencia (CT-1). Un ``requires`` ausente
levanta :class:`~nikodym.core.exceptions.ArtifactNotFoundError` antes de la búsqueda.

**Monotonía correcta por variable (SDD-13 §7/§7.7).** La monotonía es una restricción
**regulatoria** fija durante la búsqueda, no un hiperparámetro. ``from_binning`` **deriva** la
dirección real por variable desde las tablas WoE de ``binning`` (``-1`` si la tendencia es monótona,
``0`` si no) y la pasa **explícita** al optimizador (misma deuda regulatoria resuelta que ``ml``: no
se reenvía el ``from_binning`` crudo que aplicaría ``-1`` uniforme).

**Núcleo liviano (SDD-13 §9).** El módulo **no** importa ``pandas``/``numpy``/``optuna`` ni el
``TuningOptimizer``/``MLChallenger`` en import time; ``nikodym.tuning`` lo importa sólo para
ejecutar ``@register('standard', domain='tuning')``. Todo lo pesado se carga **perezosamente**
dentro de ``execute``. El motor v1 es determinista y ``tuning`` **descarta** el ``rng`` por-paso
(``del rng``): su azar sale de ``SeedManager.int_seed_for('tuning')`` (Optuna exige un ``int``).

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.tuning.config import TuningConfig
from nikodym.tuning.exceptions import TuningConfigError, TuningDataError, TuningOptimizeError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.ml.config import MLConfig
    from nikodym.tuning.results import BackendParams, TuningResult
    from nikodym.tuning.search_space import SearchSpaceConfig

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series[Any]
else:
    AuditEvent: TypeAlias = Any
    Study: TypeAlias = Any
    MLConfig: TypeAlias = Any
    BackendParams: TypeAlias = Any
    TuningResult: TypeAlias = Any
    SearchSpaceConfig: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["TUNING_ARTIFACTS", "TuningStep"]

TUNING_ARTIFACTS: Final[tuple[str, ...]] = (
    "best_hyperparameters",
    "best_config",
    "best_estimator",
    "trials",
    "importance",
    "result",
    "card",
)
_TUNING_EXTRA_MESSAGE: Final = "TuningStep requiere pandas/numpy; instale nikodym[tuning]."
_DATA_DOMAIN: Final = "data"
_BINNING_DOMAIN: Final = "binning"
_SELECTION_DOMAIN: Final = "selection"
# Defaults heredados de ``MLConfig`` (SDD-12 §5): ``from_config`` no recibe la ``MLConfig``, así que
# declara los ``requires`` con estos defaults; ``execute`` los re-deriva desde la ``ml`` real.
_DEFAULT_FEATURE_SOURCE: Final = "binning_woe"
_DEFAULT_MONOTONIC_MODE: Final = "from_binning"
# Constraint por variable en espacio WoE cuando la tendencia del binning es monótona (SDD-13 §7.7).
_WOE_MONOTONE_DIRECTION: Final = -1
_WOE_FREE_DIRECTION: Final = 0
# Filas auxiliares de las tablas de binning que no participan de la tendencia de valor.
_NON_VALUE_BINS: Final[frozenset[str]] = frozenset({"Totals", "Total", "Special", "Missing"})


@register("standard", domain="tuning")
class TuningStep(AuditableMixin):
    """Orquesta la búsqueda de hiperparámetros y publica ``domain='tuning'`` (SDD-13 §4/§7)."""

    name: str = "tuning"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = tuple(("tuning", key) for key in TUNING_ARTIFACTS)

    def __init__(self, config: TuningConfig) -> None:
        """Construye el paso desde ``TuningConfig`` y declara ``requires`` con defaults de ``ml``.

        ``from_config`` no recibe la ``MLConfig``, así que los ``requires`` estáticos usan los
        defaults de ``ml`` (``binning_woe`` + ``from_binning``); :meth:`execute` los re-deriva y
        re-valida contra la ``NikodymConfig.ml`` real antes de la búsqueda (CT-1).
        """
        self.config = config
        self.requires = _requires_for(_DEFAULT_FEATURE_SOURCE, _DEFAULT_MONOTONIC_MODE)

    @classmethod
    def from_config(cls, cfg: TuningConfig) -> TuningStep:
        """Construye ``TuningStep`` desde ``NikodymConfig.tuning``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> TuningResult:
        """Busca ``θ*`` con Optuna, valida invariantes, audita y publica siete artefactos (§7)."""
        del rng  # tuning no consume el rng por-paso; su azar sale de int_seed_for('tuning') (§7.1)
        np = _import_numpy()
        pd = _import_pandas()

        tuning_cfg = _tuning_config_from_study(study, fallback=self.config)
        ml_cfg = _ml_config_from_study(study)
        if ml_cfg.feature_source == "data_raw":
            raise TuningConfigError(
                "feature_source='data_raw' está diferido (FALTA-DATO-ML-1): use 'binning_woe' o "
                "'selection_woe'. El modo crudo exige política de imputación por variable."
            )
        requires = _requires_for(ml_cfg.feature_source, ml_cfg.monotonic.mode)
        _require_present(study, requires)

        seed = study.seed_manager.int_seed_for("tuning")
        target_col, partition_col = _read_frame_metadata(study)
        feature_frame, feature_columns = _read_feature_frame(study, ml_cfg, pd)
        _validate_features(feature_frame, feature_columns, target_col, partition_col)

        x_dev, y_dev = _build_development(
            feature_frame, feature_columns, target_col, partition_col, ml_cfg
        )
        monotone_directions = self._resolve_monotone_directions(
            study, ml_cfg, feature_columns, pd, np
        )

        from nikodym.tuning.optimizer import TuningOptimizer

        optimizer = TuningOptimizer.from_config(tuning_cfg, ml_cfg)
        result = optimizer.optimize(
            x_dev, y_dev, seed=seed, monotone_directions=monotone_directions, audit=self._audit
        )

        _assert_best_config_only_hp(ml_cfg, result.best_config)
        space = tuning_cfg.resolve_search_space(ml_cfg)
        self._emit_decisions(
            tuning_cfg,
            ml_cfg,
            result,
            space=space,
            monotone_directions=monotone_directions,
            seed=seed,
        )
        _publish_artifacts(study, result)
        return result

    # --- monotonía derivada (deuda regulatoria B12.5/MLStep, SDD-13 §7.7) ----------------------

    def _resolve_monotone_directions(
        self, study: Study, ml_cfg: MLConfig, feature_columns: tuple[str, ...], pd: Any, np: Any
    ) -> dict[str, int] | None:
        """Deriva las direcciones de monotonía fijas para los trials (misma lógica que ``ml``).

        ``off`` ⇒ ``None`` (sin constraints); ``explicit`` ⇒ el mapa declarado; ``from_binning`` ⇒
        ``-1`` por variable WoE monótona y ``0`` si no monótona (inspecciona ``binning.tables``). No
        se reenvía el ``from_binning`` crudo (aplicaría ``-1`` uniforme, riesgo regulatorio).
        """
        mode = ml_cfg.monotonic.mode
        if mode == "off":
            return None
        if mode == "explicit":
            return {str(key): int(value) for key, value in ml_cfg.monotonic.explicit.items()}
        woe_column_map = _read_woe_column_map(study)
        tables = _read_binning_tables(study)
        return _derive_from_binning(feature_columns, woe_column_map, tables, pd=pd, np=np)

    # --- auditoría (§9) ------------------------------------------------------------------------

    def _emit_decisions(
        self,
        tuning_cfg: TuningConfig,
        ml_cfg: MLConfig,
        result: TuningResult,
        *,
        space: SearchSpaceConfig,
        monotone_directions: dict[str, int] | None,
        seed: int,
    ) -> None:
        """Registra el ``log_decision`` §9: sampler/espacio/objetivo/leakage/mejor/importancia."""
        meta = result.sampler_metadata
        self.log_decision(
            regla="tuning_sampler",
            umbral=tuning_cfg.optimizer.sampler,
            valor={
                "sampler": meta.sampler,
                "pruner": meta.pruner,
                "seed": int(seed),
                "n_trials_requested": int(meta.n_trials_requested),
                "optuna_version": meta.optuna_version,
            },
            accion="construir_estudio",
        )
        self.log_decision(
            regla="tuning_search_space",
            umbral=ml_cfg.backend,
            valor={
                "backend": ml_cfg.backend,
                "params": {name: spec.kind for name, spec in space.params.items()},
            },
            accion="resolver_espacio_busqueda",
        )
        self.log_decision(
            regla="tuning_objective",
            umbral=tuning_cfg.objective.metric,
            valor={
                "metric": meta.metric,
                "direction": meta.direction,
                "validation_strategy": tuning_cfg.validation.strategy,
                "n_folds": int(tuning_cfg.validation.n_folds),
            },
            accion="definir_objetivo",
        )
        constrained = sorted(
            name for name, direction in (monotone_directions or {}).items() if direction != 0
        )
        self.log_decision(
            regla="tuning_leakage",
            umbral=ml_cfg.train.fit_partition,
            valor={
                "fit_partition": ml_cfg.train.fit_partition,
                "holdout_oot_used": False,
                "monotone_constrained": constrained,
            },
            accion="confirmar_anti_leakage",
        )
        self.log_decision(
            regla="tuning_best",
            umbral=int(meta.n_trials_complete),
            valor={
                "best_value": float(result.best_value),
                "n_trials_complete": int(meta.n_trials_complete),
                "best_hyperparameters": _hyperparameters_dict(result.best_hyperparameters),
            },
            accion="seleccionar_mejor_trial",
        )
        self.log_decision(
            regla="tuning_importance",
            umbral=len(result.param_importances),
            valor={
                "importance": [
                    {"param": name, "importance": value} for name, value in result.param_importances
                ]
            },
            accion="registrar_importancia",
        )
        if not tuning_cfg.deterministic:
            self.log_decision(
                regla="tuning_determinism",
                umbral=True,
                valor={
                    "deterministic": False,
                    "n_jobs": int(tuning_cfg.n_jobs),
                    "timeout_seconds": tuning_cfg.optimizer.timeout_seconds,
                    "byte_reproducible": False,
                },
                accion="marcar_no_byte_reproducible",
            )


# ─────────────────────────── contrato de dependencias (CT-1) ───────────────────────────


def _requires_for(feature_source: str, monotonic_mode: str) -> tuple[ArtifactKey, ...]:
    """Compone las claves ``requires`` según ``feature_source``/``monotonic_mode`` (§2/§6).

    Son las **mismas** que ``ml`` **menos** ``model.raw_pd_frame`` (``tuning`` no compara contra el
    campeón). El motor resuelve ``TuningStep`` con ``TuningConfig``, así que ``from_config`` invoca
    esta función con los defaults de ``ml`` y ``execute`` la re-invoca con la ``ml`` real.
    """
    requires: list[ArtifactKey] = [
        (_DATA_DOMAIN, "labels"),
        (_DATA_DOMAIN, "splits"),
    ]
    if feature_source == "binning_woe":
        requires += [(_BINNING_DOMAIN, "woe_frame"), (_BINNING_DOMAIN, "result")]
    elif feature_source == "selection_woe":
        requires += [
            (_SELECTION_DOMAIN, "selected_woe_frame"),
            (_SELECTION_DOMAIN, "selected_woe_columns"),
        ]
    else:  # data_raw (Literal exhaustivo; el step lo rechaza en execute, FALTA-DATO-ML-1)
        requires += [(_DATA_DOMAIN, "frame")]
    if monotonic_mode == "from_binning" and feature_source in {"binning_woe", "selection_woe"}:
        requires += [(_BINNING_DOMAIN, "tables"), (_BINNING_DOMAIN, "result")]
    return tuple(dict.fromkeys(requires))


def _require_present(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Exige que cada artefacto ``requires`` (CT-1) esté en el ``ArtifactStore``."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'tuning' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


# ─────────────────────────── lectura de artefactos ───────────────────────────


def _read_frame_metadata(study: Study) -> tuple[str, str]:
    """Extrae ``target_col``/``partition_col`` de ``data.labels``/``data.splits`` (SDD-02)."""
    labels = study.artifacts.get(_DATA_DOMAIN, "labels")
    splits = study.artifacts.get(_DATA_DOMAIN, "splits")
    target_col = getattr(labels, "target_col", None)
    partition_col = getattr(splits, "partition_col", None)
    if not isinstance(target_col, str):
        raise TuningDataError(
            "El artefacto ('data', 'labels') debe exponer target_col: str (LabeledFrame de SDD-02)."
        )
    if not isinstance(partition_col, str):
        raise TuningDataError(
            "El artefacto ('data', 'splits') debe exponer partition_col: str (PartitionResult)."
        )
    return target_col, partition_col


def _read_feature_frame(
    study: Study, ml_cfg: MLConfig, pd: Any
) -> tuple[DataFrame, tuple[str, ...]]:
    """Lee el frame de features y sus columnas WoE según ``ml.feature_source`` (copia defensiva)."""
    if ml_cfg.feature_source == "binning_woe":
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


def _read_woe_column_map(study: Study) -> dict[str, str]:
    """Lee ``woe_column_map`` (feature cruda → columna ``<feature>__woe``) de ``binning.result``."""
    result = study.artifacts.get(_BINNING_DOMAIN, "result")
    woe_column_map = getattr(result, "woe_column_map", None)
    if not isinstance(woe_column_map, dict) or not woe_column_map:
        raise TuningDataError(
            "El artefacto ('binning', 'result') debe exponer woe_column_map: dict no vacío."
        )
    return {str(key): str(value) for key, value in woe_column_map.items()}


def _read_binning_tables(study: Study) -> dict[str, Any]:
    """Lee ``binning.tables`` (una tabla WoE por feature) para derivar la monotonía."""
    tables = study.artifacts.get(_BINNING_DOMAIN, "tables")
    if not isinstance(tables, dict) or not tables:
        raise TuningDataError(
            "El artefacto ('binning', 'tables') debe ser un dict no vacío de tablas WoE "
            "por feature."
        )
    return {str(key): value for key, value in tables.items()}


# ─────────────────────────── monotonía derivada del binning (§7.7) ───────────────────────────


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
    ``-1`` (PD no creciente en WoE) es válida; si no, se libera con ``0`` (SDD-13 §7.7).
    """
    inverse = {woe: raw for raw, woe in woe_column_map.items()}
    directions: dict[str, int] = {}
    for woe_column in feature_columns:
        raw = inverse.get(woe_column)
        if raw is None or raw not in tables:
            raise TuningDataError(
                f"No se pudo mapear la columna WoE '{woe_column}' a su tabla de binning para "
                "derivar la monotonía (woe_column_map/tables inconsistentes)."
            )
        directions[woe_column] = _woe_monotone_direction(tables[raw], pd=pd, np=np)
    return directions


def _woe_monotone_direction(table: Any, *, pd: Any, np: Any) -> int:
    """Devuelve ``-1`` si el WoE de los bins de valor es monótono, ``0`` si no (SDD-13 §7.7)."""
    if not hasattr(table, "columns"):
        raise TuningDataError("Cada entrada de binning.tables debe ser un pandas.DataFrame.")
    missing = [column for column in ("Bin", "WoE") if column not in table.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise TuningDataError(f"La tabla de binning no contiene columnas requeridas: {joined}.")
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


# ─────────────────────────── construcción de la población de búsqueda ───────────────────────────


def _validate_features(
    frame: DataFrame,
    feature_columns: tuple[str, ...],
    target_col: str,
    partition_col: str,
) -> None:
    """Valida columnas de features presentes, no vacías y sin colisión con partición/target."""
    if not feature_columns:
        raise TuningDataError(
            "TuningStep no encontró columnas de features WoE para la búsqueda de hiperparámetros."
        )
    for column in (partition_col, target_col):
        if column not in frame.columns:
            raise TuningDataError(
                f"El frame de features no contiene la columna estructural '{column}'."
            )
    missing = [column for column in feature_columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise TuningDataError(f"El frame de features no contiene columnas de features: {joined}.")
    if partition_col in feature_columns or target_col in feature_columns:
        raise TuningDataError(
            "Las columnas de features no pueden incluir la partición ni el target del pipeline."
        )


def _build_development(
    frame: DataFrame,
    feature_columns: tuple[str, ...],
    target_col: str,
    partition_col: str,
    ml_cfg: MLConfig,
) -> tuple[DataFrame, Series]:
    """Filtra ``desarrollo`` (``ml.train.fit_partition``) con target no nulo (anti-leakage §6/§7.6).

    ``X_dev`` lleva **sólo** las columnas de features (nunca partición/target). ``holdout``/``oot``
    jamás entran: el optimizador sólo ve estas filas. La validación de clases/folds la hace el
    optimizador (:meth:`TuningOptimizer.optimize`), que levanta ``TuningDataError``.
    """
    partition_series = frame[partition_col].astype("string")
    mask = (partition_series.eq(ml_cfg.train.fit_partition) & frame[target_col].notna()).to_numpy()
    x_dev = frame.loc[mask, list(feature_columns)].copy(deep=True)
    y_dev = frame.loc[mask, target_col].copy(deep=True)
    if len(x_dev.index) == 0:
        raise TuningDataError(
            f"Ninguna fila en la partición de ajuste '{ml_cfg.train.fit_partition}' con target no "
            "nulo para la búsqueda de hiperparámetros."
        )
    return x_dev, y_dev


# ─────────────────────────── invariantes de salida (§6/§7.14) ───────────────────────────


def _assert_best_config_only_hp(ml_cfg: MLConfig, best_config: MLConfig) -> None:
    """Verifica que ``best_config`` difiera de ``ml`` **sólo** en ``hyperparameters`` (§6)."""
    if _config_without_hyperparameters(ml_cfg) != _config_without_hyperparameters(best_config):
        raise TuningOptimizeError(
            "best_config difiere de la config 'ml' en algo más que 'hyperparameters': la búsqueda "
            "sólo puede tunear los hiperparámetros del challenger (invariante SDD-13 §6)."
        )


def _config_without_hyperparameters(cfg: MLConfig) -> dict[str, Any]:
    """Vuelca la ``MLConfig`` a dict excluyendo ``hyperparameters`` (para comparar el resto)."""
    payload = cfg.model_dump()
    payload.pop("hyperparameters", None)
    return payload


# ─────────────────────────── publicación ───────────────────────────


def _publish_artifacts(study: Study, result: TuningResult) -> None:
    """Publica las siete claves estables del dominio ``tuning`` (copias defensivas)."""
    study.artifacts.set(
        "tuning", "best_hyperparameters", result.best_hyperparameters.model_copy(deep=True)
    )
    study.artifacts.set("tuning", "best_config", result.best_config.model_copy(deep=True))
    study.artifacts.set("tuning", "best_estimator", result.best_estimator)
    study.artifacts.set("tuning", "trials", result.trials)
    study.artifacts.set("tuning", "importance", result.param_importances)
    study.artifacts.set("tuning", "result", result.model_copy(deep=True))
    study.artifacts.set("tuning", "card", result.card.model_copy(deep=True))


# ─────────────────────────── utilidades de import/config/datos ───────────────────────────


def _import_numpy() -> Any:
    """Importa ``numpy`` localmente para preservar el import liviano del paquete ``tuning``."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError(_TUNING_EXTRA_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete ``tuning``."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:  # pragma: no cover - pandas es dep base de data
        raise MissingDependencyError(_TUNING_EXTRA_MESSAGE) from exc


def _tuning_config_from_study(study: Study, *, fallback: TuningConfig) -> TuningConfig:
    """Lee ``NikodymConfig.tuning`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "tuning", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, TuningConfig):
        return raw_config
    return TuningConfig.model_validate(raw_config)


def _ml_config_from_study(study: Study) -> MLConfig:
    """Lee ``NikodymConfig.ml`` (obligatoria: sin challenger no hay hiperparámetros que tunear)."""
    from nikodym.ml.config import MLConfig as _MLConfig

    raw_config = getattr(study.config, "ml", None)
    if raw_config is None:
        raise TuningConfigError(
            "tuning requiere una sección 'ml' activa (no hay challenger que tunear): declare 'ml' "
            "en el config o retire 'tuning'."
        )
    if isinstance(raw_config, _MLConfig):
        return raw_config
    return _MLConfig.model_validate(raw_config)


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise TuningDataError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_string_tuple(value: object, artifact: str) -> tuple[str, ...]:
    """Valida un artefacto ``tuple[str, ...]`` (p.ej. ``selection.selected_woe_columns``)."""
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(cast("list[str]", list(value)))
    raise TuningDataError(
        f"El artefacto '{artifact}' debe ser tuple[str, ...]; "
        f"tipo observado={type(value).__name__}."
    )


def _hyperparameters_dict(params: BackendParams) -> dict[str, str | int | float | bool | None]:
    """Vuelca los hiperparámetros ganadores a un dict de escalares (auditoría)."""
    return cast("dict[str, str | int | float | bool | None]", params.model_dump())
