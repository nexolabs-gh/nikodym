"""Paso orquestable de la capa ``validation`` (SDD-22 §4/§7/§9; CT-1).

``ValidationStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``validation``: lee los artefactos de las familias activas (calibración/discriminación/estabilidad
/backtesting), arma el frame analítico común (§6) sin mutar aguas arriba, delega en
:class:`~nikodym.validation.evaluator.ValidationEvaluator`, emite las decisiones auditables (§9) y
publica las seis claves estables bajo ``domain='validation'``.

**``requires`` dinámicos (CT-1, patrón SDD-16 §4).** ``from_config`` compone las dependencias según
las familias activas y los toggles de config: ``calibration`` exige ``calibration``+``data.labels``;
``discrimination`` **prefiere** ``performance.discriminant_metrics`` (o cae a ``calibration``
+``data.labels`` con ``consume_performance=False``); ``stability`` exige
``stability.stability_metrics``+``psi_table``; ``backtesting`` (sólo si ``enabled``) exige
``provisioning_ifrs9.detail``+``staging``+``data.frame``. Un ``requires`` ausente levanta
:class:`~nikodym.core.exceptions.ArtifactNotFoundError` **antes** de ejecutar.

El módulo evita importar ``pandas``/``numpy``/``scipy``/``sklearn`` en import time.
``nikodym.validation`` lo importa para ejecutar ``@register("standard", domain="validation")`` sin
contaminar el núcleo liviano; el evaluador (y con él pandas/numpy) se importa **perezosamente**
dentro de ``execute``. El motor v1 es determinista: ``execute`` descarta el ``rng``.

**Nota data.labels (nitpick c).** ``('data','labels')`` es un :class:`LabeledFrame` (SDD-02), no un
``DataFrame``: se extrae ``.frame``/``.target_col`` correctamente. El ``detail`` de
``provisioning_ifrs9`` puede traer celdas ``Decimal``/``float``: el evaluador las convierte a float.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.validation.config import ValidationConfig
from nikodym.validation.exceptions import ValidationDataError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.validation.results import ValidationResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditEvent: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Study: TypeAlias = Any
    ValidationResult: TypeAlias = Any

__all__ = ["VALIDATION_ARTIFACTS", "ValidationStep"]

VALIDATION_ARTIFACTS: Final[tuple[str, ...]] = (
    "discrimination",
    "calibration",
    "stability",
    "backtesting",
    "result",
    "card",
)
_SCORING_EXTRA_MESSAGE: Final = (
    "ValidationStep requiere pandas/numpy/scipy; instale nikodym[scoring]."
)
_CALIBRATION_DOMAIN: Final = "calibration"
_DATA_DOMAIN: Final = "data"
_PERFORMANCE_DOMAIN: Final = "performance"
_STABILITY_DOMAIN: Final = "stability"
_IFRS9_DOMAIN: Final = "provisioning_ifrs9"
_ROW_ID_COLUMN: Final = "row_id"


@register("standard", domain="validation")
class ValidationStep(AuditableMixin):
    """Orquesta la validación avanzada y publica ``domain='validation'``."""

    name: str = "validation"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = tuple(("validation", key) for key in VALIDATION_ARTIFACTS)

    def __init__(self, config: ValidationConfig) -> None:
        """Construye el paso desde la sección ``ValidationConfig`` y arma ``requires`` (CT-1)."""
        self.config = config
        self.requires = _requires_for(config)

    @classmethod
    def from_config(cls, cfg: ValidationConfig) -> ValidationStep:
        """Construye ``ValidationStep`` desde ``NikodymConfig.validation``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> ValidationResult:
        """Ejecuta la validación determinista sin consumir ``rng`` y publica seis artefactos."""
        del rng  # El evaluador v1 es determinista (SDD-22 §9): se descarta el azar.
        pd = _import_pandas()
        from nikodym.validation.evaluator import ValidationEvaluator

        cfg = _validation_config_from_study(study, fallback=self.config)
        requires = _requires_for(cfg)
        _require_present(study, requires)
        families = _active_families(cfg)

        analytic = self._read_analytic_frame(study, cfg, families, pd)
        performance_metrics = self._read_performance_metrics(study, cfg, families, pd)
        stability_metrics = self._read_stability_metrics(study, families, pd)
        ifrs9_detail, realised = self._read_backtesting_inputs(study, cfg, families, pd)

        result = ValidationEvaluator.from_config(cfg).validate(
            calibrated_pd=analytic,
            performance_metrics=performance_metrics,
            stability_metrics=stability_metrics,
            ifrs9_detail=ifrs9_detail,
            realised=realised,
            model_ref=_model_ref(study),
        )
        self._emit_decisions(result)
        self._publish_artifacts(study, result)
        return result

    # --- lectura de artefactos por familia -----------------------------------------------------

    def _read_analytic_frame(
        self, study: Study, cfg: ValidationConfig, families: frozenset[str], pd: Any
    ) -> DataFrame | None:
        """Arma el frame analítico común (§6) si alguna familia lo necesita, sin mutar upstream."""
        if not _needs_analytic_frame(cfg, families):
            return None
        calibrated = _as_dataframe(
            study.artifacts.get(_CALIBRATION_DOMAIN, "calibrated_pd_frame"),
            pd,
            "calibration.calibrated_pd_frame",
        )
        labeled = study.artifacts.get(_DATA_DOMAIN, "labels")
        return _assemble_analytic_frame(calibrated, labeled, cfg, pd)

    def _read_performance_metrics(
        self, study: Study, cfg: ValidationConfig, families: frozenset[str], pd: Any
    ) -> DataFrame | None:
        """Lee ``performance.discriminant_metrics`` cuando la discriminación lo consume."""
        if "discrimination" not in families or not cfg.discrimination.consume_performance:
            return None
        return _as_dataframe(
            study.artifacts.get(_PERFORMANCE_DOMAIN, "discriminant_metrics"),
            pd,
            "performance.discriminant_metrics",
        )

    def _read_stability_metrics(
        self, study: Study, families: frozenset[str], pd: Any
    ) -> DataFrame | None:
        """Lee ``stability.stability_metrics`` para la familia de estabilidad."""
        if "stability" not in families:
            return None
        return _as_dataframe(
            study.artifacts.get(_STABILITY_DOMAIN, "stability_metrics"),
            pd,
            "stability.stability_metrics",
        )

    def _read_backtesting_inputs(
        self, study: Study, cfg: ValidationConfig, families: frozenset[str], pd: Any
    ) -> tuple[DataFrame | None, DataFrame | None]:
        """Alinea ``provisioning_ifrs9.detail`` y ``data.frame`` por ``row_id`` (backtesting)."""
        if "backtesting" not in families or not cfg.backtesting.enabled:
            return None, None
        detail = _as_dataframe(
            study.artifacts.get(_IFRS9_DOMAIN, "detail"),
            pd,
            "provisioning_ifrs9.detail",
        )
        data_frame = _as_dataframe(
            study.artifacts.get(_DATA_DOMAIN, "frame"),
            pd,
            "data.frame",
        )
        return _align_backtesting_inputs(detail, data_frame)

    # --- auditoría (§9) ------------------------------------------------------------------------

    def _emit_decisions(self, result: ValidationResult) -> None:
        """Registra el ``log_decision`` §9: tests fallados, semáforo, PSI, reúso y FALTA-DATO."""
        for record in result.calibration_records:
            if record.test == "hosmer_lemeshow" and record.decision == "fail":
                self.log_decision(
                    regla="calibration_hosmer_lemeshow",
                    umbral=record.alpha,
                    valor={
                        "partition": record.partition,
                        "statistic": record.statistic,
                        "p_value": record.p_value,
                    },
                    accion="revisar_calibracion",
                )
        for grade in result.grade_records:
            if grade.traffic_light != "green":
                self.log_decision(
                    regla="calibration_semaforo",
                    umbral=grade.alpha,
                    valor={
                        "grade": grade.grade,
                        "p_value": grade.p_value,
                        "traffic_light": grade.traffic_light,
                    },
                    accion="vigilar_calibracion_por_grado",
                )
        self._emit_not_evaluable_grade_decisions(result)
        for backtest in result.backtest_records:
            if backtest.decision == "fail":
                self.log_decision(
                    regla=f"backtesting_{backtest.parameter}",
                    umbral=backtest.alpha,
                    valor={
                        "segment": backtest.segment,
                        "statistic": backtest.statistic,
                        "p_value": backtest.p_value,
                    },
                    accion="revisar_parametro_ifrs9",
                )
        self._emit_stability_decisions(result)
        if any(record.source == "recomputed" for record in result.discrimination_records):
            self.log_decision(
                regla="discrimination_source",
                umbral="performance_artifact",
                valor="recomputed",
                accion="reusar_performance_evaluator",
            )
        for gap in result.card.falta_dato:
            self.log_decision(
                regla="validation_falta_dato",
                umbral=self.config.fail_on_falta_dato,
                valor=gap,
                accion="trazar_brecha_metodologica",
            )

    def _emit_not_evaluable_grade_decisions(self, result: ValidationResult) -> None:
        """Audita cada grado bajo mínimo omitido del semáforo/verdicto (SDD-22 §6/§8/§9).

        Los grados con ``n < min_rows_per_group`` no producen semáforo (falta de potencia): el
        evaluador los excluye de ``grade_records`` y los expone en ``metric_sections`` para dejar
        traza. Aquí se emite el ``log_decision`` §9 que documenta la omisión sin veredicto engañoso.
        """
        section = result.card.metric_sections.get("validation", {})
        for grade in section.get("not_evaluable_grades", ()):
            self.log_decision(
                regla="calibration_grade_not_evaluable",
                umbral=grade.get("min_rows"),
                valor={
                    "grade": grade.get("grade"),
                    "n": grade.get("n"),
                    "observed_defaults": grade.get("observed_defaults"),
                },
                accion="omitir_grado_sin_potencia",
            )

    def _emit_stability_decisions(self, result: ValidationResult) -> None:
        """Registra una decisión por fila de estabilidad en banda review/redevelop (§9)."""
        stability = result.stability
        if stability.shape[0] == 0:
            return
        for row in stability.itertuples(index=False):
            if row.band in ("review", "redevelop"):
                self.log_decision(
                    regla="stability_psi",
                    umbral=(row.stable_threshold, row.review_threshold),
                    valor={"feature": row.feature, "value": row.value, "band": row.band},
                    accion="vigilar_estabilidad",
                )

    # --- publicación ---------------------------------------------------------------------------

    def _publish_artifacts(self, study: Study, result: ValidationResult) -> None:
        """Publica las seis claves estables del dominio ``validation`` (copias defensivas)."""
        study.artifacts.set("validation", "discrimination", result.discrimination.copy(deep=True))
        study.artifacts.set("validation", "calibration", result.calibration.copy(deep=True))
        study.artifacts.set("validation", "stability", result.stability.copy(deep=True))
        study.artifacts.set("validation", "backtesting", result.backtesting.copy(deep=True))
        study.artifacts.set("validation", "result", result.model_copy(deep=True))
        study.artifacts.set("validation", "card", result.card.model_copy(deep=True))


# ─────────────────────────── helpers de contrato (CT-1) ───────────────────────────


def _active_families(config: ValidationConfig) -> frozenset[str]:
    """Devuelve el conjunto de familias activas declaradas en la config."""
    return frozenset(config.families)


def _needs_analytic_frame(config: ValidationConfig, families: frozenset[str]) -> bool:
    """Indica si alguna familia exige el frame analítico (calibración o fallback discriminación)."""
    if "calibration" in families:
        return True
    return "discrimination" in families and not config.discrimination.consume_performance


def _requires_for(config: ValidationConfig) -> tuple[ArtifactKey, ...]:
    """Compone las claves ``requires`` dinámicas según familias y toggles (CT-1, SDD-22 §4)."""
    families = _active_families(config)
    requires: list[ArtifactKey] = []
    if "calibration" in families:
        requires.append((_CALIBRATION_DOMAIN, "calibrated_pd_frame"))
        requires.append((_DATA_DOMAIN, "labels"))
    if "discrimination" in families:
        if config.discrimination.consume_performance:
            requires.append((_PERFORMANCE_DOMAIN, "discriminant_metrics"))
        else:
            requires.append((_CALIBRATION_DOMAIN, "calibrated_pd_frame"))
            requires.append((_DATA_DOMAIN, "labels"))
    if "stability" in families:
        requires.append((_STABILITY_DOMAIN, "stability_metrics"))
        requires.append((_STABILITY_DOMAIN, "psi_table"))
    if "backtesting" in families and config.backtesting.enabled:
        requires.append((_IFRS9_DOMAIN, "detail"))
        requires.append((_IFRS9_DOMAIN, "staging"))
        requires.append((_DATA_DOMAIN, "frame"))
    # Dedup preservando el orden de aparición (calibración y fallback comparten calibration+labels).
    return tuple(dict.fromkeys(requires))


def _require_present(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Exige que cada artefacto ``requires`` (CT-1) esté en el ``ArtifactStore``."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'validation' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _model_ref(study: Study) -> str:
    """Deriva la referencia al modelo validado desde el nombre del config (no vacía)."""
    name = getattr(study.config, "name", None)
    text = str(name).strip() if name is not None else ""
    return text or "validation"


# ─────────────────────────── ensamblado de frames ───────────────────────────


def _assemble_analytic_frame(
    calibrated: DataFrame, labeled: Any, config: ValidationConfig, pd: Any
) -> DataFrame:
    """Alinea la PD calibrada con el target/grado de ``data.labels`` por índice (§6, nitpick c)."""
    calib = config.calibration
    labels_frame, target_col = _read_labeled_frame(labeled, pd)
    _validate_unique_index(calibrated, artifact="calibration.calibrated_pd_frame")
    _validate_unique_index(labels_frame, artifact="data.labels.frame")
    for column in (calib.partition_column, calib.pd_column):
        if column not in calibrated.columns:
            raise ValidationDataError(
                f"calibration.calibrated_pd_frame no contiene la columna requerida '{column}'."
            )
    missing = calibrated.index.difference(labels_frame.index)
    if len(missing):
        raise ValidationDataError(
            "data.labels no cubre todas las operaciones de calibration.calibrated_pd_frame: "
            f"faltan={missing.astype(str).tolist()}."
        )
    aligned_labels = labels_frame.loc[calibrated.index]
    data: dict[str, Any] = {
        calib.partition_column: calibrated[calib.partition_column].to_numpy(),
        calib.pd_column: calibrated[calib.pd_column].to_numpy(),
        calib.target_column: aligned_labels[target_col].to_numpy(),
    }
    frame = pd.DataFrame(data, index=calibrated.index)
    if calib.grade_col in aligned_labels.columns:
        frame[calib.grade_col] = aligned_labels[calib.grade_col].to_numpy()
    return cast(DataFrame, frame)


def _read_labeled_frame(labeled: Any, pd: Any) -> tuple[DataFrame, str]:
    """Extrae ``.frame``/``.target_col`` de un :class:`LabeledFrame` (SDD-02); valida contrato."""
    frame = getattr(labeled, "frame", None)
    target_col = getattr(labeled, "target_col", None)
    if not isinstance(frame, pd.DataFrame) or not isinstance(target_col, str):
        raise ValidationDataError(
            "El artefacto data.labels debe ser un LabeledFrame (SDD-02) con .frame y .target_col; "
            f"tipo observado={type(labeled).__name__}."
        )
    if target_col not in frame.columns:
        raise ValidationDataError(
            f"data.labels.frame no contiene su columna target declarada '{target_col}'."
        )
    return frame, target_col


def _align_backtesting_inputs(
    detail: DataFrame, data_frame: DataFrame
) -> tuple[DataFrame, DataFrame]:
    """Indexa ``detail`` por ``row_id`` y reindexa ``data.frame`` para alinear el backtesting."""
    if _ROW_ID_COLUMN not in detail.columns:
        raise ValidationDataError(
            f"provisioning_ifrs9.detail no contiene la columna '{_ROW_ID_COLUMN}' para alinear el "
            "backtesting con data.frame."
        )
    indexed = detail.set_index(_ROW_ID_COLUMN)
    _validate_unique_index(indexed, artifact="provisioning_ifrs9.detail(row_id)")
    _validate_unique_index(data_frame, artifact="data.frame")
    missing = indexed.index.difference(data_frame.index)
    if len(missing):
        raise ValidationDataError(
            "data.frame no cubre todas las operaciones de provisioning_ifrs9.detail: "
            f"faltan={missing.astype(str).tolist()}."
        )
    realised = data_frame.loc[indexed.index]
    return indexed, realised


def _validate_unique_index(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza índices duplicados antes de alinear artefactos."""
    if frame.index.is_unique:
        return
    duplicated = frame.index[frame.index.duplicated()].astype(str).tolist()
    joined = ", ".join(f"'{item}'" for item in duplicated[:5])
    raise ValidationDataError(f"{artifact} contiene índice duplicado; ejemplos: {joined}.")


# ─────────────────────────── utilidades de import/config ───────────────────────────


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
    raise ValidationDataError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _validation_config_from_study(study: Study, *, fallback: ValidationConfig) -> ValidationConfig:
    """Lee ``NikodymConfig.validation`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "validation", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ValidationConfig):
        return raw_config
    return ValidationConfig.model_validate(raw_config)
