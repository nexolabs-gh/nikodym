"""Paso orquestable de la capa ``markov`` (SDD-19 §4/§7/§9; CT-1).

``MarkovStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``markov``:
consume ``data.frame``, ajusta matrices de transición o generadores, proyecta una term-structure
de PD lifetime compatible con ``survival`` y publica siete artefactos namespaced bajo
``domain='markov'``.

El módulo evita importar ``pandas``, ``numpy``, ``scipy`` y el motor de transición en import time.
``nikodym.markov`` lo importa para ejecutar ``@register("standard", domain="markov")`` sin
contaminar el núcleo liviano; las dependencias tabulares/numéricas se cargan dentro de
``execute``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from importlib import metadata
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.audit import AuditEvent
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.markov.config import MarkovConfig
from nikodym.markov.exceptions import MarkovInputError, MarkovTransformError
from nikodym.markov.results import EmbeddingDiagnostics, MarkovCard, MarkovDiagnostics, MarkovResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.markov.transition import TransitionMatrixEstimator

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
else:
    DataFrame: TypeAlias = Any
    Mapping: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    Sequence: TypeAlias = Any
    Study: TypeAlias = Any
    TransitionMatrixEstimator: TypeAlias = Any

__all__ = ["MARKOV_ARTIFACTS", "MarkovStep"]

MARKOV_ARTIFACTS: Final[tuple[str, ...]] = (
    "estimator",
    "transition_matrix",
    "term_structure",
    "generator",
    "diagnostics",
    "result",
    "card",
)
_TERM_STRUCTURE_COLUMNS: Final[tuple[str, ...]] = (
    "row_id",
    "segment",
    "partition",
    "period",
    "time_value",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "method",
    "pd_source",
    "scenario",
    "warning_codes",
)
_MARKOV_PANDAS_MESSAGE: Final = "MarkovStep requiere pandas; instale las dependencias base."
_MARKOV_NUMPY_MESSAGE: Final = "MarkovStep requiere numpy; instale las dependencias base."
_PERIOD_MATRICES_UNSUPPORTED: Final = (
    "projection_mode='period_matrices' no soportado aún: requiere estimación de matrices por "
    "período no homogéneas, no disponible en B19.x; use projection_mode='homogeneous' o "
    "projection_mode='aalen_johansen'."
)


@register("standard", domain="markov")
class MarkovStep(AuditableMixin):
    """Orquesta matrices Markov y publica ``domain='markov'``."""

    name: str = "markov"
    requires: tuple[ArtifactKey, ...] = (("data", "frame"),)
    provides: tuple[ArtifactKey, ...] = (
        ("markov", "estimator"),
        ("markov", "transition_matrix"),
        ("markov", "term_structure"),
        ("markov", "generator"),
        ("markov", "diagnostics"),
        ("markov", "result"),
        ("markov", "card"),
    )

    def __init__(self, config: MarkovConfig) -> None:
        """Construye el paso desde la sección ``MarkovConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: MarkovConfig) -> MarkovStep:
        """Construye ``MarkovStep`` desde ``NikodymConfig.markov``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` sin exponer el sink interno."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> MarkovResult:
        """Ejecuta Markov determinista sin consumir ``rng`` y publica siete artefactos."""
        del rng
        pd = _import_pandas()
        np = _import_numpy()

        cfg = _markov_config_from_study(study, fallback=self.config)
        _reject_unsupported_projection(cfg)
        frame = _as_dataframe(study.artifacts.get("data", "frame"), pd, "data.frame").copy(
            deep=True
        )
        estimator = _fit_estimator(frame.copy(deep=True), cfg=cfg)

        from nikodym.markov.term_structure import diagnose_embedding, markov_term_structure

        # M2: el embedding se diagnostica ANTES de proyectar para que, cuando la política
        # 'regularize' produzca un generador regularizado, la term-structure y el artefacto
        # generator lo reflejen de verdad (no un no-op con P^t crudo y generator=None).
        embedding = diagnose_embedding(
            estimator.transition_matrix_,
            delta_t=cfg.estimation.interval,
            config=cfg,
        )
        projected = _projected_matrices(
            frame.copy(deep=True),
            estimator=estimator,
            cfg=cfg,
            np=np,
            embedding=embedding,
        )
        term_structure = markov_term_structure(projected, config=cfg)
        transition_matrix = estimator.transition_matrix_frame_.copy(deep=True)
        generator = _generator_frame(estimator, embedding=embedding, cfg=cfg, np=np)
        diagnostics = _diagnostics_from_estimator(
            estimator,
            cfg=cfg,
            embedding=embedding,
            transition_matrix=transition_matrix,
            generator=generator,
            term_structure=term_structure,
        )
        card = _card_from_outputs(
            cfg=cfg,
            diagnostics=diagnostics,
            transition_matrix=transition_matrix,
            generator=generator,
            term_structure=term_structure,
        )
        result = MarkovResult(
            estimator=estimator,
            transition_matrix_frame=transition_matrix.copy(deep=True),
            generator_frame=None if generator is None else generator.copy(deep=True),
            term_structure_frame=term_structure.copy(deep=True),
            diagnostics=diagnostics,
            card=card,
        )
        self._log_markov_decisions(
            cfg=cfg,
            frame=frame,
            embedding=embedding,
            result=result,
        )
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: MarkovResult) -> None:
        """Publica las siete claves estables del dominio ``markov``."""
        study.artifacts.set("markov", "estimator", result.estimator)
        study.artifacts.set(
            "markov",
            "transition_matrix",
            result.transition_matrix_frame.copy(deep=True),
        )
        term_structure = result.term_structure_frame
        assert term_structure is not None
        study.artifacts.set("markov", "term_structure", term_structure.copy(deep=True))
        generator = result.generator_frame
        study.artifacts.set(
            "markov",
            "generator",
            None if generator is None else generator.copy(deep=True),
        )
        study.artifacts.set("markov", "diagnostics", result.diagnostics.model_copy(deep=True))
        study.artifacts.set("markov", "result", result.model_copy(deep=True))
        study.artifacts.set("markov", "card", result.card.model_copy(deep=True))

    def _log_markov_decisions(
        self,
        *,
        cfg: MarkovConfig,
        frame: DataFrame,
        embedding: EmbeddingDiagnostics,
        result: MarkovResult,
    ) -> None:
        """Registra las ocho secciones auditables exigidas por SDD-19 §9."""
        card = result.card
        transition_matrix = result.transition_matrix_frame
        generator = result.generator_frame
        term_structure = result.term_structure_frame
        assert term_structure is not None
        self.log_decision(
            regla="markov_method",
            umbral={
                "method": cfg.estimation.method,
                "projection_mode": cfg.dynamics.projection_mode,
                "time_unit": cfg.dynamics.time_unit,
            },
            valor={"interval": cfg.estimation.interval},
            accion="seleccionar_metodo_markov",
        )
        self.log_decision(
            regla="markov_states",
            umbral={"default_state": cfg.states.default_state},
            valor={
                "states": cfg.states.states,
                "absorbing_states": cfg.states.absorbing_states,
                "observed_states": tuple(dict.fromkeys(frame[cfg.input.state_col].astype(str))),
            },
            accion="validar_catalogo_estados",
        )
        self.log_decision(
            regla="markov_input_quality",
            umbral={"id_col": cfg.input.id_col, "time_col": cfg.input.time_col},
            valor={
                "n_entities": card.diagnostics.n_entities,
                "n_observations": card.diagnostics.n_observations,
                "n_transitions": card.diagnostics.n_transitions,
                "n_periods": card.diagnostics.n_periods,
            },
            accion="validar_panel_migraciones",
        )
        self.log_decision(
            regla="markov_transition_counts",
            umbral={"min_origin_count": cfg.estimation.min_origin_count},
            valor=_transition_counts_payload(transition_matrix),
            accion="contabilizar_transiciones",
        )
        self.log_decision(
            regla="markov_stochastic_validation",
            umbral={
                "stochastic_tol": cfg.validation.stochastic_tol,
                "normalize_within_tolerance": cfg.validation.normalize_within_tolerance,
            },
            valor=card.metric_sections["transition_matrix_summary"],
            accion="validar_matriz_estocastica",
        )
        self.log_decision(
            regla="markov_generator",
            umbral={"generator_tol": cfg.validation.generator_tol},
            valor=card.metric_sections["generator_summary"],
            accion="validar_generador_markov",
        )
        self.log_decision(
            regla="markov_embedding",
            umbral={"embedding_policy": cfg.dynamics.embedding_policy},
            valor=_embedding_payload(embedding),
            accion="diagnosticar_embedding",
        )
        self.log_decision(
            regla="markov_term_structure",
            umbral={"horizons": _horizons(cfg)},
            valor={
                **card.metric_sections["term_structure_summary"],
                "generator_rows": 0 if generator is None else len(generator.index),
                "term_structure_rows": len(term_structure.index),
            },
            accion="publicar_term_structure_markov",
        )


def _markov_config_from_study(study: Study, *, fallback: MarkovConfig) -> MarkovConfig:
    """Lee ``NikodymConfig.markov`` y usa el config del paso como respaldo."""
    raw_config = getattr(study.config, "markov", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, MarkovConfig):
        return raw_config
    return MarkovConfig.model_validate(raw_config)


def _fit_estimator(frame: DataFrame, *, cfg: MarkovConfig) -> TransitionMatrixEstimator:
    """Ajusta el estimador con import perezoso del motor Markov."""
    from nikodym.markov.transition import TransitionMatrixEstimator

    fit_cfg = _fit_config(cfg)
    return TransitionMatrixEstimator.from_config(fit_cfg).fit(frame.copy(deep=True))


def _fit_config(cfg: MarkovConfig) -> MarkovConfig:
    """Usa dinámica homogénea para el ajuste base cuando la proyección se calcula aparte."""
    if cfg.dynamics.projection_mode == "homogeneous":
        return cfg
    return cfg.model_copy(
        update={"dynamics": cfg.dynamics.model_copy(update={"projection_mode": "homogeneous"})}
    )


def _projected_matrices(
    frame: DataFrame,
    *,
    estimator: TransitionMatrixEstimator,
    cfg: MarkovConfig,
    np: Any,
    embedding: EmbeddingDiagnostics,
) -> Mapping[int | float, NDArrayFloat]:
    """Proyecta matrices acumuladas con las funciones libres de ``term_structure``."""
    _reject_unsupported_projection(cfg)
    horizons = _horizons(cfg)
    if cfg.dynamics.projection_mode == "aalen_johansen":
        from nikodym.markov.term_structure import aalen_johansen

        return aalen_johansen(frame.copy(deep=True), config=cfg)
    if _is_regularized_embedding(embedding):
        # M2: la política 'regularize' regularizó el generador. La PD publicada se proyecta desde
        # ese generador (P(0,t) = expm(Q_reg · t · Δt)) en vez del P^t crudo: el usuario pidió un
        # modelo continuo válido y P no embebía. Cuando P sí embebe (adjusted=False), este branch no
        # se activa y se conserva el P^t exacto.
        return _projected_from_regularized_generator(embedding, horizons=horizons, cfg=cfg, np=np)
    if cfg.estimation.method == "cohort":
        from nikodym.markov.term_structure import chapman_kolmogorov

        return cast(
            "Mapping[int | float, NDArrayFloat]",
            chapman_kolmogorov(
                [estimator.transition_matrix_],
                homogeneous=True,
                horizons=cast("Sequence[int]", horizons),
            ),
        )
    projected_frames = estimator.predict_transition(horizons=horizons)
    return {
        horizon: _matrix_from_transition_frame(projected_frame, cfg=cfg, np=np)
        for horizon, projected_frame in projected_frames.items()
    }


def _reject_unsupported_projection(cfg: MarkovConfig) -> None:
    """Falla ruidosamente para modos declarados que B19.x todavía no implementa."""
    if cfg.dynamics.projection_mode == "period_matrices":
        raise MarkovTransformError(_PERIOD_MATRICES_UNSUPPORTED)


def _matrix_from_transition_frame(frame: DataFrame, *, cfg: MarkovConfig, np: Any) -> NDArrayFloat:
    """Convierte la matriz tidy del estimador en arreglo denso ordenado por ``states``."""
    state_index = {state: index for index, state in enumerate(cfg.states.states)}
    matrix = np.zeros((len(cfg.states.states), len(cfg.states.states)), dtype="float64")
    records = cast("list[dict[str, Any]]", frame.to_dict("records"))
    for row in records:
        matrix[state_index[str(row["from_state"])], state_index[str(row["to_state"])]] = float(
            row["probability"]
        )
    matrix[matrix == 0.0] = 0.0
    return cast("NDArrayFloat", matrix)


def _horizons(cfg: MarkovConfig) -> tuple[int | float, ...]:
    """Resuelve horizontes declarativos en orden estable."""
    if cfg.dynamics.evaluation_times:
        return cfg.dynamics.evaluation_times
    return cfg.dynamics.horizon_periods


_GENERATOR_COLUMNS: Final[tuple[str, ...]] = (
    "from_state",
    "to_state",
    "intensity",
    "time_at_risk",
    "transition_count",
    "source",
)


def _is_regularized_embedding(embedding: EmbeddingDiagnostics) -> bool:
    """Indica si el embedding produjo un generador regularizado usable (política regularize)."""
    return (
        embedding.embedding_status == "regularized_principal_log"
        and embedding.generator_candidate is not None
    )


def _generator_frame(
    estimator: TransitionMatrixEstimator,
    *,
    embedding: EmbeddingDiagnostics,
    cfg: MarkovConfig,
    np: Any,
) -> DataFrame | None:
    """Publica el generador: el regularizado del embedding, el del método duration, o ``None``.

    M2: cuando la política 'regularize' regularizó el generador, se publica con
    ``source='regularized_embedding'`` en vez de dejar el artefacto en ``None`` mientras
    ``embedding_adjusted=True`` (flag que mentiría). El generador viene del log de la matriz, por lo
    que ``time_at_risk``/``transition_count`` no aplican (0.0; la columna ``source`` lo desambigua).
    """
    if _is_regularized_embedding(embedding):
        return _regularized_generator_frame(embedding, cfg=cfg, np=np)
    generator = estimator.generator_frame_
    if generator is None:
        return None
    return generator.copy(deep=True)


def _regularized_generator_frame(
    embedding: EmbeddingDiagnostics,
    *,
    cfg: MarkovConfig,
    np: Any,
) -> DataFrame:
    """Construye el generador regularizado del embedding en el formato tidy del artefacto."""
    pd = _import_pandas()
    generator = np.array(embedding.generator_candidate, dtype="float64", copy=True)
    states = cfg.states.states
    rows: list[dict[str, Any]] = []
    for from_index, from_state in enumerate(states):
        for to_index, to_state in enumerate(states):
            intensity = float(generator[from_index, to_index])
            rows.append(
                {
                    "from_state": from_state,
                    "to_state": to_state,
                    "intensity": 0.0 if intensity == 0.0 else intensity,
                    "time_at_risk": 0.0,
                    "transition_count": 0.0,
                    "source": "regularized_embedding",
                }
            )
    return cast("DataFrame", pd.DataFrame.from_records(rows, columns=_GENERATOR_COLUMNS))


def _projected_from_regularized_generator(
    embedding: EmbeddingDiagnostics,
    *,
    horizons: tuple[int | float, ...],
    cfg: MarkovConfig,
    np: Any,
) -> dict[int | float, NDArrayFloat]:
    """Proyecta ``P(0,t) = expm(Q_reg · t · Δt)`` desde el generador regularizado del embedding."""
    from nikodym.markov.term_structure import validate_transition_matrix

    expm = _import_expm()
    generator = np.array(embedding.generator_candidate, dtype="float64", copy=True)
    interval = cfg.estimation.interval
    projected: dict[int | float, NDArrayFloat] = {}
    for horizon in horizons:
        matrix = np.array(expm(generator * (float(horizon) * interval)), dtype="float64", copy=True)
        validate_transition_matrix(
            matrix,
            states=cfg.states.states,
            absorbing_states=cfg.states.absorbing_states,
            tol=cfg.validation.stochastic_tol,
        )
        matrix[matrix == 0.0] = 0.0
        projected[horizon] = cast("NDArrayFloat", matrix)
    return projected


def _diagnostics_from_estimator(
    estimator: TransitionMatrixEstimator,
    *,
    cfg: MarkovConfig,
    embedding: EmbeddingDiagnostics,
    transition_matrix: DataFrame,
    generator: DataFrame | None,
    term_structure: DataFrame,
) -> MarkovDiagnostics:
    """Construye diagnósticos finales incorporando embedding y tamaños publicados."""
    base = estimator.diagnostics_
    fit_statistics = base.fit_statistics
    fit_statistics.update(
        {
            "transition_matrix_rows": len(transition_matrix.index),
            "generator_rows": 0 if generator is None else len(generator.index),
            "term_structure_rows": len(term_structure.index),
        }
    )
    return MarkovDiagnostics(
        method=cfg.estimation.method,
        projection_mode=cfg.dynamics.projection_mode,
        states=cfg.states.states,
        default_state=cfg.states.default_state,
        absorbing_states=cfg.states.absorbing_states,
        n_entities=base.n_entities,
        n_observations=base.n_observations,
        n_transitions=base.n_transitions,
        n_periods=base.n_periods,
        stochastic_tol=cfg.validation.stochastic_tol,
        generator_tol=cfg.validation.generator_tol,
        embedding_status=embedding.embedding_status,
        embedding_flags=embedding.embedding_flags,
        embedding_adjusted=embedding.adjusted,
        embedding_distance_fro=embedding.distance_fro,
        fit_statistics=fit_statistics,
        warnings=base.warnings,
    )


def _card_from_outputs(
    *,
    cfg: MarkovConfig,
    diagnostics: MarkovDiagnostics,
    transition_matrix: DataFrame,
    generator: DataFrame | None,
    term_structure: DataFrame,
) -> MarkovCard:
    """Construye una ``MarkovCard`` CT-2 con secciones métricas aditivas."""
    metric_sections = {
        "transition_matrix_summary": _transition_matrix_summary(transition_matrix),
        "generator_summary": _generator_summary(generator),
        "embedding_diagnostics": {
            "status": diagnostics.embedding_status,
            "flags": diagnostics.embedding_flags,
            "adjusted": diagnostics.embedding_adjusted,
            "distance_fro": diagnostics.embedding_distance_fro,
        },
        "term_structure_summary": _term_structure_summary(term_structure),
    }
    return MarkovCard(
        method=cfg.estimation.method,
        projection_mode=cfg.dynamics.projection_mode,
        time_unit=cfg.dynamics.time_unit,
        horizon_periods=cfg.dynamics.horizon_periods,
        states=cfg.states.states,
        default_state=cfg.states.default_state,
        absorbing_states=cfg.states.absorbing_states,
        output_columns=_TERM_STRUCTURE_COLUMNS,
        diagnostics=diagnostics,
        dependency_versions=_dependency_versions(),
        falta_dato=tuple(code for code in diagnostics.warnings if code.startswith("FALTA-DATO")),
        metric_sections=metric_sections,
    )


def _transition_matrix_summary(frame: DataFrame) -> dict[str, Any]:
    """Resume la matriz de transición publicada sin serializar todo el frame."""
    return {
        "n_rows": len(frame.index),
        "n_periods": int(frame["period"].nunique(dropna=True)),
        "min_probability": float(frame["probability"].min()),
        "max_probability": float(frame["probability"].max()),
    }


def _generator_summary(frame: DataFrame | None) -> dict[str, Any]:
    """Resume el generador continuo; cohort conserva la key con valor ``None``."""
    if frame is None:
        return {"available": False, "n_rows": 0, "source": None}
    return {
        "available": True,
        "n_rows": len(frame.index),
        "source": tuple(dict.fromkeys(frame["source"].astype(str))),
    }


def _term_structure_summary(frame: DataFrame) -> dict[str, Any]:
    """Resume la salida lifetime PD compatible con ``survival``."""
    return {
        "n_rows": len(frame.index),
        "n_periods": int(frame["period"].nunique(dropna=True)),
        "max_pd_cumulative": float(frame["pd_cumulative"].max()),
        "max_pd_marginal": float(frame["pd_marginal"].max()),
    }


def _transition_counts_payload(frame: DataFrame) -> tuple[dict[str, Any], ...]:
    """Publica conteos ``N_ij``/``N_i`` en formato compacto para auditoría."""
    records = cast(
        "list[dict[str, Any]]",
        frame[["from_state", "to_state", "count", "origin_count"]].to_dict("records"),
    )
    return tuple(
        {
            "from_state": str(row["from_state"]),
            "to_state": str(row["to_state"]),
            "count": None if row["count"] is None else float(row["count"]),
            "origin_count": (None if row["origin_count"] is None else float(row["origin_count"])),
        }
        for row in records
    )


def _embedding_payload(embedding: EmbeddingDiagnostics) -> dict[str, Any]:
    """Serializa el diagnóstico de embedding sin incluir matrices densas."""
    return {
        "embedding_status": embedding.embedding_status,
        "embedding_flags": embedding.embedding_flags,
        "imaginary_norm": embedding.imaginary_norm,
        "distance_fro": embedding.distance_fro,
        "adjusted": embedding.adjusted,
    }


def _dependency_versions() -> dict[str, str]:
    """Resuelve versiones de dependencias sin importar sus módulos."""
    return {package: metadata.version(package) for package in ("pandas", "numpy", "scipy")}


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_MARKOV_PANDAS_MESSAGE) from exc


def _import_numpy() -> Any:
    """Importa ``numpy`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_MARKOV_NUMPY_MESSAGE) from exc


def _import_expm() -> Any:
    """Importa ``scipy.linalg.expm`` localmente para la proyección por generador regularizado."""
    try:
        return importlib.import_module("scipy.linalg").expm
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "MarkovStep con embedding regularizado requiere scipy.linalg; instale nikodym[markov]."
        ) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast("DataFrame", value)
    raise MarkovInputError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )
