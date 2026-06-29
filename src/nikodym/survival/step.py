"""Paso orquestable de la capa ``survival`` (SDD-18 §4/§7/§9; CT-1).

``SurvivalStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``survival``. Su dependencia dura real es ``data.frame`` + ``model.raw_pd_frame`` (SDD-02 +
SDD-08): SDD-01/SDD-05 son base implícita de orquestación/config y no aparecen como artefactos
``requires``. El paso valida prerequisitos condicionales, delega el ajuste a los modelos ya
implementados y publica estimador, term-structure, curvas, hazards, diagnósticos, resultado y card
bajo ``domain='survival'``.

El módulo evita importar ``pandas``, ``lifelines``, ``statsmodels`` y motores de survival en import
time. ``nikodym.survival`` lo importa para ejecutar ``@register("standard", domain="survival")``
sin contaminar el núcleo liviano; las dependencias tabulares/estadísticas se cargan dentro de
``execute``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.audit import AuditEvent
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.survival.config import SurvivalConfig, SurvivalMethod
from nikodym.survival.exceptions import SurvivalConfigError, SurvivalInputError
from nikodym.survival.results import SurvivalCard, SurvivalDiagnostics, SurvivalResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.survival.base import BaseSurvivalModel

    DataFrame: TypeAlias = pd.DataFrame
else:
    BaseSurvivalModel: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Sequence: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["SURVIVAL_ARTIFACTS", "SurvivalStep"]

SURVIVAL_ARTIFACTS: Final[tuple[str, ...]] = (
    "estimator",
    "term_structure",
    "survival_curves",
    "hazards",
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
_SCORING_EXTRA_MESSAGE: Final = (
    "SurvivalStep requiere statsmodels para method='discrete_hazard'; instale nikodym[scoring]."
)
_SURVIVAL_EXTRA_MESSAGE: Final = (
    "SurvivalStep requiere lifelines para method='kaplan_meier', 'cox_ph' o 'aft'; "
    "instale nikodym[survival]."
)
_PANDAS_EXTRA_MESSAGE: Final = "SurvivalStep requiere pandas; instale las dependencias base."
_PARTITION_COL: Final = "partition"
_CALIBRATION_SOURCE: Final = "calibration"
_MODEL_RAW_SOURCE: Final = "model_raw"
_NO_PD_SOURCE: Final = "none"
_NO_TIME_GRID_WARNING: Final = "FALTA-DATO-SUR-1"


@register("standard", domain="survival")
class SurvivalStep(AuditableMixin):
    """Orquesta modelos survival y publica ``domain='survival'``."""

    name: str = "survival"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
        ("model", "raw_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = tuple(("survival", key) for key in SURVIVAL_ARTIFACTS)

    def __init__(self, config: SurvivalConfig) -> None:
        """Construye el paso desde la sección ``SurvivalConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: SurvivalConfig) -> SurvivalStep:
        """Construye ``SurvivalStep`` desde ``NikodymConfig.survival``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` a los modelos survival."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> SurvivalResult:
        """Ejecuta survival determinista sin consumir ``rng`` y publica siete artefactos."""
        del rng
        pd = _import_pandas()

        cfg = _survival_config_from_study(study, fallback=self.config)
        data_frame = _as_dataframe(study.artifacts.get("data", "frame"), pd, "data.frame").copy(
            deep=True
        )
        model_raw_frame = _as_dataframe(
            study.artifacts.get("model", "raw_pd_frame"),
            pd,
            "model.raw_pd_frame",
        ).copy(deep=True)
        _require_method_dependency(cfg.method)
        pd_frame, pd_context = _pd_frame_for_config(
            study,
            cfg=cfg,
            model_raw_frame=model_raw_frame,
            pd=pd,
        )
        _validate_frame_contracts(data_frame, pd_frame, cfg=cfg)
        pd_context.update(_pd_match_context(data_frame, pd_frame, cfg=cfg))

        times, time_context = _time_grid_from_config_or_data(data_frame, cfg=cfg)
        model = _new_model(cfg)
        fitted = model.fit(
            data_frame.copy(deep=True),
            duration_col=cfg.input.duration_col,
            event_col=cfg.input.event_col,
            covariate_cols=cfg.input.covariate_cols,
            pd_frame=pd_frame.copy(deep=True),
            audit=self,
        )
        term_structure = fitted.term_structure(data_frame.copy(deep=True), times=times)
        term_structure = _with_step_warnings(term_structure, time_context["warnings"])
        survival_curves = fitted.predict_survival(data_frame.copy(deep=True), times=times)
        hazards = fitted.predict_hazard(data_frame.copy(deep=True), times=times)
        warnings = _warning_codes(term_structure)
        diagnostics = _diagnostics_from_model(fitted, cfg=cfg, term_structure=term_structure)
        card = _card_from_model(
            fitted,
            cfg=cfg,
            diagnostics=diagnostics,
            term_structure=term_structure,
            pd_context=pd_context,
            time_context=time_context,
            warnings=warnings,
        )
        result = SurvivalResult(
            estimator=fitted,
            term_structure_frame=term_structure.copy(deep=True),
            survival_curve_frame=survival_curves.copy(deep=True),
            hazard_frame=hazards.copy(deep=True),
            diagnostics=diagnostics,
            card=card,
        )
        self._log_survival_decisions(
            cfg=cfg,
            data_frame=data_frame,
            pd_context=pd_context,
            time_context=time_context,
            diagnostics=diagnostics,
            card=card,
            result=result,
        )
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: SurvivalResult) -> None:
        """Publica los siete artefactos estables del dominio ``survival``."""
        study.artifacts.set("survival", "estimator", result.estimator)
        if result.term_structure_frame is not None:
            study.artifacts.set(
                "survival",
                "term_structure",
                result.term_structure_frame.copy(deep=True),
            )
        else:
            study.artifacts.set("survival", "term_structure", None)
        study.artifacts.set(
            "survival",
            "survival_curves",
            result.survival_curve_frame.copy(deep=True),
        )
        study.artifacts.set("survival", "hazards", result.hazard_frame.copy(deep=True))
        study.artifacts.set("survival", "diagnostics", result.diagnostics.model_copy(deep=True))
        study.artifacts.set("survival", "result", result.model_copy(deep=True))
        study.artifacts.set("survival", "card", result.card.model_copy(deep=True))

    def _log_survival_decisions(
        self,
        *,
        cfg: SurvivalConfig,
        data_frame: DataFrame,
        pd_context: dict[str, Any],
        time_context: dict[str, Any],
        diagnostics: SurvivalDiagnostics,
        card: SurvivalCard,
        result: SurvivalResult,
    ) -> None:
        """Registra decisiones auditables exigidas por SDD-18 §9."""
        self.log_decision(
            regla="survival_method",
            umbral={
                "method": cfg.method,
                "link": cfg.discrete_hazard.link if cfg.method == "discrete_hazard" else None,
                "aft_family": cfg.cox_aft.aft_family if cfg.method == "aft" else None,
            },
            valor={
                "pd_source": cfg.input.pd_source,
                "duration_col": cfg.input.duration_col,
                "event_col": cfg.input.event_col,
                "covariate_cols": cfg.input.covariate_cols,
            },
            accion="seleccionar_modelo_survival",
        )
        self.log_decision(
            regla="survival_time_grid",
            umbral={
                "time_unit": cfg.time_grid.time_unit,
                "horizon_periods": cfg.time_grid.horizon_periods,
                "evaluation_times": cfg.time_grid.evaluation_times,
            },
            valor=time_context,
            accion="resolver_grilla_survival",
        )
        self.log_decision(
            regla="survival_input_quality",
            umbral={"duration_col": cfg.input.duration_col, "event_col": cfg.input.event_col},
            valor={
                "n_rows": diagnostics.n_rows,
                "n_events": diagnostics.n_events,
                "n_censored": diagnostics.n_censored,
                "max_observed_time": diagnostics.max_observed_time,
            },
            accion="validar_input_survival",
        )
        self.log_decision(
            regla="survival_pd_source",
            umbral={"pd_source": cfg.input.pd_source},
            valor=pd_context,
            accion="alinear_fuente_pd",
        )
        self.log_decision(
            regla="survival_person_period",
            umbral={"method": cfg.method},
            valor=card.metric_sections.get("person_period", {}),
            accion="trazar_person_period",
        )
        self.log_decision(
            regla="survival_km_greenwood",
            umbral={"method": cfg.method},
            valor=card.metric_sections.get("km_greenwood", {}),
            accion="trazar_greenwood_km",
        )
        self.log_decision(
            regla="survival_schoenfeld",
            umbral={"method": cfg.method, "ph_test_enabled": cfg.cox_aft.ph_test_enabled},
            valor=diagnostics.schoenfeld_test,
            accion="trazar_schoenfeld",
        )
        self.log_decision(
            regla="survival_aft",
            umbral={"method": cfg.method, "aft_family": cfg.cox_aft.aft_family},
            valor=card.metric_sections.get("aft", {}),
            accion="trazar_aft",
        )
        term = result.term_structure_frame
        self.log_decision(
            regla="survival_result",
            umbral="publicar_artefactos_survival",
            valor={
                "term_structure_rows": 0 if term is None else len(term.index),
                "survival_curve_rows": len(result.survival_curve_frame.index),
                "hazard_rows": len(result.hazard_frame.index),
                "falta_dato": card.falta_dato,
            },
            accion="publicar_resultado_survival",
        )


def _survival_config_from_study(study: Study, *, fallback: SurvivalConfig) -> SurvivalConfig:
    """Lee ``NikodymConfig.survival`` y usa el config del paso como respaldo."""
    raw_config = getattr(study.config, "survival", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, SurvivalConfig):
        return raw_config
    return SurvivalConfig.model_validate(raw_config)


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_PANDAS_EXTRA_MESSAGE) from exc


def _require_method_dependency(method: SurvivalMethod) -> None:
    """Valida dependencias estadísticas condicionales con mensajes de extras."""
    if method == "discrete_hazard":
        try:
            importlib.import_module("statsmodels.genmod.generalized_linear_model")
        except ModuleNotFoundError as exc:
            raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
        return
    try:
        importlib.import_module("lifelines")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SURVIVAL_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise SurvivalInputError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _pd_frame_for_config(
    study: Study,
    *,
    cfg: SurvivalConfig,
    model_raw_frame: DataFrame,
    pd: Any,
) -> tuple[DataFrame, dict[str, Any]]:
    """Resuelve y alinea la fuente PD declarada preservando ``partition`` desde F1."""
    if cfg.input.pd_source == _CALIBRATION_SOURCE:
        if not study.artifacts.has("calibration", "calibrated_pd_frame"):
            raise ArtifactNotFoundError(
                "pd_source='calibration' exige el artefacto "
                "('calibration', 'calibrated_pd_frame') antes de calcular survival."
            )
        source = _as_dataframe(
            study.artifacts.get("calibration", "calibrated_pd_frame"),
            pd,
            "calibration.calibrated_pd_frame",
        ).copy(deep=True)
        source_name = "calibration.calibrated_pd_frame"
    else:
        source = model_raw_frame.copy(deep=True)
        source_name = "model.raw_pd_frame"

    merged = source.copy(deep=True)
    if _PARTITION_COL not in merged.columns and _PARTITION_COL in model_raw_frame.columns:
        _validate_unique_index(model_raw_frame, artifact="model.raw_pd_frame")
        missing_raw_index = [
            str(index) for index in merged.index if index not in model_raw_frame.index
        ]
        if missing_raw_index:
            raise SurvivalInputError(
                "calibration.calibrated_pd_frame contiene filas sin match en model.raw_pd_frame: "
                f"{missing_raw_index}."
            )
        merged[_PARTITION_COL] = model_raw_frame.loc[merged.index, _PARTITION_COL]

    pd_column = _pd_source_column(cfg)
    linear_column = cfg.input.linear_predictor_column
    coverage_column = pd_column or linear_column if linear_column in merged.columns else pd_column
    return merged, {
        "pd_source": cfg.input.pd_source,
        "source_artifact": source_name,
        "pd_column": pd_column,
        "linear_predictor_column": linear_column if linear_column in merged.columns else None,
        "pd_rows": len(merged.index),
        "pd_coverage": None,
        "rows_without_match": (),
        "coverage_column": coverage_column,
    }


def _validate_frame_contracts(
    data_frame: DataFrame, pd_frame: DataFrame, *, cfg: SurvivalConfig
) -> None:
    """Valida índice único, columnas mínimas y cobertura PD antes de delegar al motor."""
    _validate_unique_index(data_frame, artifact="data.frame")
    _validate_unique_index(pd_frame, artifact="pd_frame")
    missing_columns = [
        column
        for column in (cfg.input.duration_col, cfg.input.event_col, *cfg.input.covariate_cols)
        if column not in data_frame.columns
    ]
    if cfg.input.segment_col is not None and cfg.input.segment_col not in data_frame.columns:
        missing_columns.append(cfg.input.segment_col)
    if cfg.input.id_col is not None and cfg.input.id_col not in data_frame.columns:
        missing_columns.append(cfg.input.id_col)
    if missing_columns:
        raise SurvivalInputError(f"Faltan columnas requeridas para survival: {missing_columns}.")

    missing_index = [str(index) for index in data_frame.index if index not in pd_frame.index]
    if missing_index:
        raise SurvivalInputError(
            "model.raw_pd_frame/calibration no cubre filas de survival: "
            f"pd_source='{cfg.input.pd_source}', filas_sin_match={missing_index}."
        )


def _pd_match_context(
    data_frame: DataFrame, pd_frame: DataFrame, *, cfg: SurvivalConfig
) -> dict[str, Any]:
    """Calcula cobertura de PD por índice para auditoría."""
    rows_without_match = tuple(
        str(index) for index in data_frame.index if index not in pd_frame.index
    )
    coverage_column = _pd_source_column(cfg)
    if coverage_column is None:
        coverage = (
            1.0 - (len(rows_without_match) / len(data_frame.index))
            if len(data_frame.index)
            else 1.0
        )
    elif coverage_column in pd_frame.columns:
        aligned = pd_frame.loc[data_frame.index, coverage_column]
        coverage = float(cast(Any, aligned.notna()).mean())
    else:
        coverage = 0.0
    return {
        "pd_coverage": _clean_float(coverage),
        "rows_without_match": rows_without_match,
    }


def _validate_unique_index(frame: DataFrame, *, artifact: str) -> None:
    """Valida índices únicos para evitar uniones PD ambiguas."""
    if not frame.index.is_unique:
        duplicated = [str(value) for value in frame.index[frame.index.duplicated()].unique()]
        raise SurvivalInputError(
            f"El índice de '{artifact}' debe ser único; duplicados={duplicated}."
        )


def _pd_source_column(cfg: SurvivalConfig) -> str | None:
    """Devuelve la columna PD usada por el modelo, si aplica."""
    if cfg.input.pd_source == _NO_PD_SOURCE or cfg.discrete_hazard.pd_role == "none":
        return None
    if cfg.discrete_hazard.pd_role == "offset":
        return cfg.input.linear_predictor_column
    return cfg.input.pd_column


def _time_grid_from_config_or_data(
    frame: DataFrame,
    *,
    cfg: SurvivalConfig,
) -> tuple[tuple[int | float, ...], dict[str, Any]]:
    """Resuelve la grilla temporal del step antes de predecir."""
    fallback_warning: str | None = None
    if cfg.time_grid.evaluation_times:
        raw_times: Sequence[int | float] = cfg.time_grid.evaluation_times
        source = "evaluation_times"
    elif cfg.time_grid.horizon_periods is not None:
        raw_times = tuple(range(1, cfg.time_grid.horizon_periods + 1))
        source = "horizon_periods"
    else:
        raw_times = _observed_times(frame, duration_col=cfg.input.duration_col)
        source = "observed_times"
        fallback_warning = _NO_TIME_GRID_WARNING
    times = tuple(raw_times)
    return times, {
        "source": source,
        "time_unit": cfg.time_grid.time_unit,
        "horizon_periods": cfg.time_grid.horizon_periods,
        "evaluation_times": cfg.time_grid.evaluation_times,
        "resolved_times": times,
        "warnings": () if fallback_warning is None else (fallback_warning,),
    }


def _observed_times(frame: DataFrame, *, duration_col: str) -> tuple[float, ...]:
    """Extrae tiempos observados positivos en orden ascendente estable."""
    observed = tuple(
        sorted(
            {
                _clean_float(float(value))
                for value in cast(Any, frame[duration_col].dropna().tolist())
            }
        )
    )
    if not observed:
        raise SurvivalInputError(
            "No hay tiempos observados no nulos para resolver la grilla: "
            f"duration_col='{duration_col}'."
        )
    return observed


def _new_model(cfg: SurvivalConfig) -> BaseSurvivalModel:
    """Instancia el modelo survival configurado con imports perezosos."""
    if cfg.method == "kaplan_meier":
        from nikodym.survival.kaplan_meier import KaplanMeierSurvivalModel

        return KaplanMeierSurvivalModel.from_config(cfg)
    if cfg.method == "discrete_hazard":
        from nikodym.survival.discrete_hazard import DiscreteTimeHazardModel

        return DiscreteTimeHazardModel.from_config(cfg)
    if cfg.method == "cox_ph":
        from nikodym.survival.cox_aft import CoxPHSurvivalModel

        return CoxPHSurvivalModel.from_config(cfg)
    if cfg.method == "aft":
        from nikodym.survival.cox_aft import AFTSurvivalModel

        return AFTSurvivalModel.from_config(cfg)
    raise SurvivalConfigError(f"Método survival no soportado: {cfg.method!r}.")


def _diagnostics_from_model(
    model: BaseSurvivalModel,
    *,
    cfg: SurvivalConfig,
    term_structure: DataFrame,
) -> SurvivalDiagnostics:
    """Construye diagnósticos finales incorporando warnings de predicción."""
    existing = getattr(model, "diagnostics_", None)
    warnings = _warning_codes(term_structure)
    if isinstance(existing, SurvivalDiagnostics):
        return existing.model_copy(update={"warnings": warnings}, deep=True)
    return SurvivalDiagnostics(
        method=cfg.method,
        n_rows=int(getattr(model, "n_rows_", 0)),
        n_events=int(getattr(model, "n_events_", 0)),
        n_censored=int(getattr(model, "n_censored_", 0)),
        max_observed_time=float(getattr(model, "max_observed_time_", 0.0)),
        link=cfg.discrete_hazard.link if cfg.method == "discrete_hazard" else None,
        schoenfeld_test=getattr(model, "schoenfeld_test_", None),
        aft_family=cfg.cox_aft.aft_family if cfg.method == "aft" else None,
        fit_statistics=_fit_statistics_from_model(model),
        warnings=warnings,
    )


def _card_from_model(
    model: BaseSurvivalModel,
    *,
    cfg: SurvivalConfig,
    diagnostics: SurvivalDiagnostics,
    term_structure: DataFrame,
    pd_context: dict[str, Any],
    time_context: dict[str, Any],
    warnings: tuple[str, ...],
) -> SurvivalCard:
    """Construye una ``SurvivalCard`` CT-2 con secciones métricas aditivas."""
    n_periods = int(cast(Any, term_structure["period"]).nunique(dropna=True))
    metric_sections = _metric_sections(
        model,
        cfg=cfg,
        term_structure=term_structure,
        pd_context=pd_context,
        time_context=time_context,
    )
    return SurvivalCard(
        method=cfg.method,
        pd_source=cfg.input.pd_source,
        duration_col=cfg.input.duration_col,
        event_col=cfg.input.event_col,
        time_unit=cfg.time_grid.time_unit,
        n_rows=diagnostics.n_rows,
        n_events=diagnostics.n_events,
        n_periods=n_periods,
        output_columns=_TERM_STRUCTURE_COLUMNS,
        diagnostics=diagnostics,
        dependency_versions=_dependency_versions_for_method(cfg.method),
        falta_dato=tuple(code for code in warnings if code.startswith("FALTA-DATO")),
        metric_sections=metric_sections,
    )


def _fit_statistics_from_model(model: BaseSurvivalModel) -> dict[str, Any]:
    """Extrae estadísticas de ajuste publicadas por el estimador si existen."""
    stats = getattr(model, "fit_statistics_", {})
    return dict(stats) if isinstance(stats, dict) else {}


def _metric_sections(
    model: BaseSurvivalModel,
    *,
    cfg: SurvivalConfig,
    term_structure: DataFrame,
    pd_context: dict[str, Any],
    time_context: dict[str, Any],
) -> dict[str, Any]:
    """Puebla las secciones CT-2 principales sin imponer un schema cerrado."""
    sections: dict[str, Any] = {
        "term_structure_summary": _term_structure_summary(term_structure),
        "schoenfeld": getattr(model, "schoenfeld_test_", None) or {},
        "km_greenwood": _km_greenwood_section(model, cfg=cfg),
        "person_period": _person_period_section(model),
        "pd_source": pd_context,
        "time_grid": time_context,
    }
    if cfg.method == "aft":
        sections["aft"] = {
            "aft_family": cfg.cox_aft.aft_family,
            "fit_statistics": _fit_statistics_from_model(model),
        }
    return sections


def _term_structure_summary(term_structure: DataFrame) -> dict[str, Any]:
    """Resume la salida lifetime PD publicada."""
    if term_structure.empty:
        return {"n_rows": 0, "n_periods": 0}
    return {
        "n_rows": len(term_structure.index),
        "n_periods": int(cast(Any, term_structure["period"]).nunique(dropna=True)),
        "max_pd_cumulative": _clean_float(float(cast(Any, term_structure["pd_cumulative"]).max())),
        "min_survival": _clean_float(float(cast(Any, term_structure["survival"]).min())),
    }


def _person_period_section(model: BaseSurvivalModel) -> dict[str, Any]:
    """Extrae el resumen person-period cuando el método lo publica."""
    rows = getattr(model, "person_period_rows_", None)
    events_by_period = getattr(model, "events_by_period_", None)
    if rows is None and events_by_period is None:
        return {}
    return {
        "n_rows": rows,
        "events_by_period": dict(events_by_period or {}),
    }


def _km_greenwood_section(model: BaseSurvivalModel, *, cfg: SurvivalConfig) -> dict[str, Any]:
    """Resume la configuración/estado Greenwood de Kaplan-Meier si aplica."""
    if cfg.method != "kaplan_meier":
        return {}
    curves = getattr(model, "curves_", ())
    return {
        "confidence_level": cfg.kaplan_meier.confidence_level,
        "confidence_transform": cfg.kaplan_meier.confidence_transform,
        "n_curves": len(curves),
        "warnings": getattr(model, "warning_codes_", ()),
    }


def _warning_codes(frame: DataFrame) -> tuple[str, ...]:
    """Extrae códigos únicos de ``warning_codes`` preservando orden de aparición."""
    if "warning_codes" not in frame.columns:
        return ()
    warnings: list[str] = []
    for raw in cast(Any, frame["warning_codes"]).tolist():
        if isinstance(raw, (tuple, list)):
            warnings.extend(str(item) for item in raw)
        elif raw not in (None, ""):
            warnings.append(str(raw))
    return tuple(dict.fromkeys(warnings))


def _with_step_warnings(frame: DataFrame, warnings: tuple[str, ...]) -> DataFrame:
    """Añade warnings resueltos por el step a la tabla tidy sin perder códigos del motor."""
    if not warnings or "warning_codes" not in frame.columns:
        return frame
    copied = frame.copy(deep=True)
    copied["warning_codes"] = [
        tuple(dict.fromkeys((*_as_warning_tuple(raw), *warnings)))
        for raw in cast(Any, copied["warning_codes"]).tolist()
    ]
    return copied


def _as_warning_tuple(raw: object) -> tuple[str, ...]:
    """Normaliza una celda ``warning_codes`` a tupla de texto."""
    if isinstance(raw, (tuple, list)):
        return tuple(str(item) for item in raw)
    if raw in (None, ""):
        return ()
    return (str(raw),)


def _dependency_versions_for_method(method: SurvivalMethod) -> dict[str, str]:
    """Devuelve versiones de dependencias relevantes sin importar motores adicionales."""
    packages = ["pandas", "numpy"]
    if method == "discrete_hazard":
        packages.append("statsmodels")
    else:
        packages.append("lifelines")
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions


def _clean_float(value: float) -> float:
    """Normaliza ``-0.0`` como ``0.0``."""
    if value == 0.0:
        return 0.0
    return value
