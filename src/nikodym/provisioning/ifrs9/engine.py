"""Orquestador económico IFRS 9 / ECL: encadena PD PIT, LGD, EAD, staging y ECL (SDD-16 §7).

:class:`IfrsProvisioningEngine` ejecuta la **secuencia canónica** del SDD-16 §7 sobre una operación
o cartera: transforma la PD a base point-in-time (PIT), deriva los horizontes 12m/lifetime, estima
LGD y EAD, asigna el Stage IFRS 9 por SICR y evalúa la ECL marginal descontada a la EIR, ponderando
outputs por escenario. Reutiliza los motores puros de bloques previos —``vasicek_pit`` /
``marginal_to_horizon`` (``pd_pit``), :class:`~nikodym.provisioning.ifrs9.lgd.LgdEngine`,
:class:`~nikodym.provisioning.ifrs9.ead.EadEngine`,
:class:`~nikodym.provisioning.ifrs9.staging.StagingEngine` y
:class:`~nikodym.provisioning.ifrs9.ecl.EclEngine`— y ensambla el
:class:`~nikodym.provisioning.ifrs9.results.IfrsProvisionResult` (staging, detalle, term-structure
de ECL, resumen y card) que consume el step ``provisioning_ifrs9``.

Determinismo (SDD-16 §9): el motor v1 no tiene componentes estocásticos. No muta los insumos (copias
defensivas del ``frame``, la term-structure y la PD calibrada), preserva el orden del ``frame`` en
``staging``/``detail`` y normaliza ``-0.0`` a ``0.0`` (delegado a los DTO/DataFrame de ``results``).

``pandas``/``numpy`` (y ``scipy`` para Vasicek) se importan de forma perezosa dentro de los métodos:
ni ``import nikodym.core`` ni ``import nikodym.provisioning.ifrs9`` deben arrastrar esas
dependencias en top-level.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
from importlib import metadata
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9.config import IfrsProvisioningConfig
from nikodym.provisioning.ifrs9.ead import EadEngine
from nikodym.provisioning.ifrs9.ecl import EclEngine
from nikodym.provisioning.ifrs9.exceptions import (
    IfrsConfigError,
    IfrsInputError,
    IfrsTermStructureError,
)
from nikodym.provisioning.ifrs9.lgd import LgdEngine
from nikodym.provisioning.ifrs9.pd_pit import marginal_to_horizon, vasicek_pit
from nikodym.provisioning.ifrs9.results import (
    IfrsEclRecord,
    IfrsProvisionCard,
    IfrsProvisionResult,
    IfrsStageRecord,
)
from nikodym.provisioning.ifrs9.staging import StagingEngine

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditSink

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series
else:
    AuditSink: TypeAlias = Any
    NDArrayFloat: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["IfrsProvisioningEngine"]

# Etiqueta canónica del escenario único cuando la term-structure base (survival/markov) no puebla la
# columna ``scenario`` (queda ``None``); forward la puebla con nombres reales.
_SINGLE_SCENARIO_LABEL: str = "base"
# Columna de nombre fijo con la PD 12m anclada por SDD-10 cuando ``base_pd_source='calibration'``.
_CALIBRATED_PD_COLUMN: str = "pd_calibrated"
# Columnas del contrato tidy de term-structure que el motor exige antes de calcular (SDD-16 §6).
_TS_REQUIRED_COLUMNS: tuple[str, ...] = ("row_id", "period", "time_value", "pd_marginal")
# Columnas opcionales del contrato tidy que refuerzan las invariantes cuando están presentes.
_TS_SURVIVAL_COLUMN: str = "survival"
_TS_CUMULATIVE_COLUMN: str = "pd_cumulative"
_TS_SCENARIO_COLUMN: str = "scenario"
_TS_PD_BASIS_COLUMN: str = "pd_basis"
_TS_SCENARIO_WEIGHT_COLUMN: str = "scenario_weight"
# Etiqueta del escenario agregado en el resumen (la ECL reportada ya pondera todos los escenarios).
_SUMMARY_SCENARIO_LABEL: str = "all"
# Tolerancias de las invariantes tidy de la term-structure (SDD-16 §6).
_TS_INVARIANT_TOL: float = 1e-9
# Nombres de escenario vetados por el guard anti escenario medio (espejo de forward/SDD-20;
# cubre las tres fuentes porque se valida antes del branch por ``scenarios.source``).
_RESERVED_SCENARIO_NAMES: frozenset[str] = frozenset({"mean", "average", "weighted_mean_input"})
# La LGD condicionada que publica forward en la term-structure NO se consume en v1 (SDD-20
# FALTA-DATO-FWD-6, precedencia pendiente de SDD): el motor estima la LGD desde el ``frame``
# (``IfrsLgdConfig``) y declara el descarte con este aviso en vez de callarlo.
_TS_LGD_COLUMN: str = "lgd"
_WARNING_LGD_FORWARD_IGNORED: str = "FALTA-DATO-IFRS-6"

# Rótulo hermano de ``ecl_by_scenario`` en ``metric_sections``. Esa cifra y ``total_ecl_reported``
# difieren por construcción, pero salían pegadas en el anexo de auditoría sin nada que lo explicara
# —y una diferencia de ~2x sin rótulo se lee como descuadre contable. El texto viaja en el propio
# artefacto, no en la plantilla del informe, para que acompañe a la cifra dondequiera que se lea
# ``results`` (anexo, payload de la UI, consumidor externo).
_ECL_BY_SCENARIO_BASIS: str = (
    "Diagnóstico auditable de la term-structure (CT-2), no un desglose de total_ecl_reported: "
    "suma la ECL marginal descontada de cada escenario por separado, sin aplicar scenario_weights "
    "y sobre el horizonte completo de la curva, sin truncar Stage 1 a 12 meses. "
    "total_ecl_reported sí pondera por escenario y aplica ese corte por stage, de modo que ambas "
    "cifras no reconcilian entre sí: no deben sumarse ni compararse."
)

# Columnas canónicas de los artefactos (deben coincidir exactamente con ``results.py``, que las
# revalida al construir el ``IfrsProvisionResult``; una divergencia rompe los tests ruidosamente).
_STAGING_COLUMNS: tuple[str, ...] = (
    "row_id",
    "portfolio",
    "stage",
    "days_past_due",
    "pd_life_current",
    "pd_life_origination",
    "sicr_triggers",
    "low_credit_risk_exempt",
    "warning_codes",
)
_DETAIL_COLUMNS: tuple[str, ...] = (
    "row_id",
    "portfolio",
    "stage",
    "ead",
    "lgd",
    "eir",
    "pd_12m",
    "pd_life",
    "ecl_12m",
    "ecl_lifetime",
    "ecl_reported",
    "scenario_weights",
    "pd_basis",
    "warning_codes",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "portfolio",
    "stage",
    "scenario",
    "n_rows",
    "total_ead",
    "total_ecl_reported",
    "coverage_ratio",
    "warning_codes",
)

_NUMPY_MESSAGE: str = "IfrsProvisioningEngine requiere numpy; instale nikodym[scoring]."
_PANDAS_MESSAGE: str = "IfrsProvisioningEngine requiere pandas; instale nikodym[scoring]."


class IfrsProvisioningEngine:
    """Motor económico IFRS 9 que orquesta la secuencia canónica de la ECL (SDD-16 §7)."""

    config_cls: ClassVar[type[IfrsProvisioningConfig]] = IfrsProvisioningConfig

    def __init__(self, config: IfrsProvisioningConfig) -> None:
        """Inicializa el motor con la sección ``IfrsProvisioningConfig`` ya validada."""
        self._config = config

    @classmethod
    def from_config(cls, cfg: IfrsProvisioningConfig) -> Self:
        """Construye el motor desde ``IfrsProvisioningConfig`` (molde hermano ``from_config``)."""
        return cls(cfg)

    def calculate(
        self,
        frame: DataFrame,
        *,
        term_structure: DataFrame,
        calibrated_pd: DataFrame | None = None,
        as_of_date: str,
        audit: AuditSink | None = None,
    ) -> IfrsProvisionResult:
        """Calcula la ECL IFRS 9 por operación y ensambla el :class:`IfrsProvisionResult`.

        Parameters
        ----------
        frame
            DataFrame económico (exposición/drawn/límite, dpd, EIR, rating, LGD/recovery, flags). No
            se muta (copia defensiva).
        term_structure
            Term-structure tidy lifetime PD del proveedor configurado (survival/markov/forward),
            con al menos ``row_id``/``period``/``time_value``/``pd_marginal``. No se muta.
        calibrated_pd
            PD 12m anclada por SDD-10 (columna ``pd_calibrated``); obligatoria sólo cuando
            ``pd.base_pd_source='calibration'``.
        as_of_date
            Fecha de cálculo/cierre contable de la provisión (texto no vacío).
        audit
            Sink de auditoría opcional (el step orquestador registra las decisiones de §9).

        Returns
        -------
        IfrsProvisionResult
            Contenedor con ``staging``/``detail``/``ecl_term_structure``/``summary``, los registros
            por operación y la card CT-2.

        Raises
        ------
        IfrsTermStructureError
            Si la term-structure incumple el contrato tidy o sus invariantes.
        IfrsConfigError
            Si el modo PIT, la fuente de PD base o la fuente de escenarios exige insumos ausentes.
        IfrsInputError
            Si faltan columnas raíz del ``frame`` o los identificadores no son únicos/alineables.
        MissingDependencyError
            Si falta ``numpy`` o ``pandas``.
        """
        # El step orquestador registra las decisiones §9; el motor es puro y determinista.
        del audit
        numpy = _import_numpy()
        pandas = _import_pandas()
        config = self._config
        _validate_as_of_date(as_of_date)

        frame = _as_dataframe(frame, pandas, "data.frame").copy(deep=True)
        ts = _as_dataframe(term_structure, pandas, "term_structure").copy(deep=True)
        calibrated = (
            None
            if calibrated_pd is None
            else _as_dataframe(calibrated_pd, pandas, "calibrated_pd").copy(deep=True)
        )

        row_ids = _frame_row_ids(frame, config)
        portfolios = _frame_column_texts(frame, config.portfolio_col, "portfolio_col")
        eir_arr = _frame_float_column(frame, config.ecl.eir_col, "eir", numpy)

        _validate_term_structure(ts, numpy)
        ts = _prepare_term_structure(ts, config, numpy)
        _check_row_coverage(row_ids, [str(value) for value in ts["row_id"].to_numpy()])

        weights = self._resolve_weights(ts, numpy)
        pit_marginal = self._resolve_pit_marginal(ts, config, numpy)
        ts = ts.assign(pd_marginal=pit_marginal)

        pd_12m_by_rid, pd_life_by_rid = _weighted_horizons(ts, config, weights, pandas)
        if config.pd.base_pd_source == "calibration":
            pd_12m_by_rid = _calibrated_pd_12m(calibrated, row_ids, numpy)

        pd_life_arr = numpy.array([pd_life_by_rid[rid] for rid in row_ids], dtype=numpy.float64)
        pd_pit_arr = numpy.array([pd_12m_by_rid[rid] for rid in row_ids], dtype=numpy.float64)

        lgd_arr = self._estimate_lgd(frame, eir_arr, numpy, pandas)
        ead_arr, row_warnings = self._estimate_ead(frame, numpy)
        if _ts_lgd_present(ts):
            row_warnings = [(*codes, _WARNING_LGD_FORWARD_IGNORED) for codes in row_warnings]
        stage_arr, triggers, exempt = self._assign_staging(frame, pd_life_arr, pd_pit_arr, pandas)

        lgd_by_rid = dict(zip(row_ids, (float(value) for value in lgd_arr), strict=True))
        ead_by_rid = dict(zip(row_ids, (float(value) for value in ead_arr), strict=True))
        eir_by_rid = dict(zip(row_ids, (float(value) for value in eir_arr), strict=True))

        components = _components_frame(ts, row_ids, lgd_by_rid, ead_by_rid, pandas)
        ecl_ts, ecl_detail = EclEngine.from_config(config.ecl).compute(
            components,
            eir=pandas.Series(eir_arr, index=row_ids),
            stages=pandas.Series(stage_arr, index=row_ids),
            weights=weights,
            horizon_12m=config.pd.horizon_12m_periods,
        )

        pd_basis = "ttc" if config.pd.pit_mode == "ttc_only" else "pit"
        origination = _origination_pd_life(frame, config, numpy)
        context = _OperationContext(
            row_ids=row_ids,
            portfolios=portfolios,
            days_past_due=_frame_int_column(frame, config.staging.days_past_due_col, numpy),
            pd_life=pd_life_arr,
            pd_pit=pd_pit_arr,
            origination_pd_life=origination,
            lgd=lgd_by_rid,
            ead=ead_by_rid,
            eir=eir_by_rid,
            triggers=triggers,
            exempt=exempt,
            warnings=dict(zip(row_ids, row_warnings, strict=True)),
            weights=weights,
            pd_basis=pd_basis,
        )
        return self._assemble_result(
            context=context,
            ecl_detail=ecl_detail,
            ecl_term_structure=ecl_ts,
            as_of_date=as_of_date,
            pandas=pandas,
        )

    # --- Etapas económicas (reutilizan los motores puros de bloques previos) -------------------

    def _resolve_weights(self, ts: DataFrame, numpy: Any) -> dict[str, float]:
        """Resuelve los pesos de escenario según ``scenarios.source`` (SDD-16 §5/§7)."""
        scenarios_present = _ordered_unique(
            str(value) for value in ts[_TS_SCENARIO_COLUMN].tolist()
        )
        if self._config.scenarios.forbid_mean_scenario:
            reservados = sorted(
                name for name in scenarios_present if name.lower() in _RESERVED_SCENARIO_NAMES
            )
            if reservados:
                raise IfrsConfigError(
                    "forbid_mean_scenario=True veta escenarios medios reservados en la "
                    f"term-structure: {reservados} (se ponderan outputs por escenario, "
                    "nunca inputs macro promediados)."
                )
        source = self._config.scenarios.source
        if source == "single":
            if len(scenarios_present) != 1:
                raise IfrsConfigError(
                    "scenarios.source='single' exige exactamente un escenario en la "
                    f"term-structure; presentes={scenarios_present}."
                )
            return {scenarios_present[0]: 1.0}
        if source == "config":
            weights = {
                str(key): float(value) for key, value in self._config.scenarios.weights.items()
            }
            if set(weights) != set(scenarios_present):
                raise IfrsConfigError(
                    "scenarios.source='config' exige pesos que cubran exactamente los escenarios "
                    f"presentes (pesos={sorted(weights)}, escenarios={scenarios_present})."
                )
            return weights
        return _forward_weights(ts, scenarios_present, numpy)

    def _resolve_pit_marginal(
        self, ts: DataFrame, config: IfrsProvisioningConfig, numpy: Any
    ) -> NDArrayFloat:
        """Resuelve la PD marginal PIT según ``pit_mode`` (consume_pit/apply_vasicek/ttc_only)."""
        marginal = numpy.asarray(ts["pd_marginal"].to_numpy(), dtype=numpy.float64)
        pit_mode = config.pd.pit_mode
        if pit_mode == "ttc_only":
            return cast("NDArrayFloat", marginal)
        if pit_mode == "consume_pit":
            _require_pit_basis(ts)
            return cast("NDArrayFloat", marginal)
        return _apply_vasicek(ts, config, marginal, numpy)

    def _estimate_lgd(
        self, frame: DataFrame, eir_arr: NDArrayFloat, numpy: Any, pandas: Any
    ) -> NDArrayFloat:
        """Estima la LGD por operación con :class:`LgdEngine`, en orden del ``frame``."""
        eir_series = pandas.Series(eir_arr, index=frame.index)
        lgd_frame = LgdEngine.from_config(self._config.lgd).estimate(frame, eir=eir_series)
        return cast("NDArrayFloat", numpy.asarray(lgd_frame["lgd"].to_numpy(), dtype=numpy.float64))

    def _estimate_ead(
        self, frame: DataFrame, numpy: Any
    ) -> tuple[NDArrayFloat, list[tuple[str, ...]]]:
        """Estima el nivel de EAD por operación (constante por período) con :class:`EadEngine`."""
        ead_frame = EadEngine.from_config(self._config.ead).estimate(frame, periods=[1])
        level = numpy.asarray(ead_frame["ead"].to_numpy(), dtype=numpy.float64)
        warnings = [
            tuple(str(code) for code in codes) for codes in ead_frame["warning_codes"].tolist()
        ]
        return cast("NDArrayFloat", level), warnings

    def _assign_staging(
        self,
        frame: DataFrame,
        pd_life_arr: NDArrayFloat,
        pd_pit_arr: NDArrayFloat,
        pandas: Any,
    ) -> tuple[Any, list[tuple[str, ...]], list[bool]]:
        """Asigna el Stage IFRS 9 por operación con :class:`StagingEngine` (SICR/backstops)."""
        staging = StagingEngine.from_config(self._config.staging).assign(
            frame,
            pd_life=pandas.Series(pd_life_arr, index=frame.index),
            pd_pit=pandas.Series(pd_pit_arr, index=frame.index),
        )
        stages = staging["stage"].to_numpy()
        triggers = [
            tuple(str(code) for code in codes) for codes in staging["sicr_triggers"].tolist()
        ]
        exempt = [bool(flag) for flag in staging["low_credit_risk_exempt"].tolist()]
        return stages, triggers, exempt

    # --- Ensamblado de artefactos (SDD-16 §4/§6) ------------------------------------------------

    def _assemble_result(
        self,
        *,
        context: _OperationContext,
        ecl_detail: DataFrame,
        ecl_term_structure: DataFrame,
        as_of_date: str,
        pandas: Any,
    ) -> IfrsProvisionResult:
        """Construye ``staging``/``detail``/``summary``, los registros y la card (SDD-16 §4/§6)."""
        ecl_by_rid = {
            str(rid): (float(e12), float(elife), float(erep), int(stage))
            for rid, e12, elife, erep, stage in zip(
                ecl_detail["row_id"].tolist(),
                ecl_detail["ecl_12m"].tolist(),
                ecl_detail["ecl_lifetime"].tolist(),
                ecl_detail["ecl_reported"].tolist(),
                ecl_detail["stage"].tolist(),
                strict=True,
            )
        }
        staging_rows: list[dict[str, Any]] = []
        detail_rows: list[dict[str, Any]] = []
        stage_records: list[IfrsStageRecord] = []
        ecl_records: list[IfrsEclRecord] = []
        for index, rid in enumerate(context.row_ids):
            ecl_12m, ecl_lifetime, ecl_reported, stage = ecl_by_rid[rid]
            portfolio = context.portfolios[index]
            dpd = int(context.days_past_due[index])
            pd_life = float(context.pd_life[index])
            pd_12m = float(context.pd_pit[index])
            origination = (
                None
                if context.origination_pd_life is None
                else float(context.origination_pd_life[index])
            )
            warnings = context.warnings[rid]
            staging_rows.append(
                {
                    "row_id": rid,
                    "portfolio": portfolio,
                    "stage": stage,
                    "days_past_due": dpd,
                    "pd_life_current": pd_life,
                    "pd_life_origination": origination,
                    "sicr_triggers": context.triggers[index],
                    "low_credit_risk_exempt": context.exempt[index],
                    "warning_codes": warnings,
                }
            )
            detail_rows.append(
                {
                    "row_id": rid,
                    "portfolio": portfolio,
                    "stage": stage,
                    "ead": context.ead[rid],
                    "lgd": context.lgd[rid],
                    "eir": context.eir[rid],
                    "pd_12m": pd_12m,
                    "pd_life": pd_life,
                    "ecl_12m": ecl_12m,
                    "ecl_lifetime": ecl_lifetime,
                    "ecl_reported": ecl_reported,
                    "scenario_weights": dict(context.weights),
                    "pd_basis": context.pd_basis,
                    "warning_codes": warnings,
                }
            )
            stage_records.append(
                IfrsStageRecord(
                    row_id=rid,
                    stage=cast("Any", stage),
                    days_past_due=dpd,
                    pd_life_current=pd_life,
                    pd_life_origination=origination,
                    sicr_triggers=context.triggers[index],
                    low_credit_risk_exempt=context.exempt[index],
                    warnings=warnings,
                )
            )
            ecl_records.append(
                IfrsEclRecord(
                    row_id=rid,
                    stage=cast("Any", stage),
                    ead=context.ead[rid],
                    lgd=context.lgd[rid],
                    eir=context.eir[rid],
                    ecl_12m=ecl_12m,
                    ecl_lifetime=ecl_lifetime,
                    ecl_reported=ecl_reported,
                    scenario_weights=dict(context.weights),
                    pd_basis=cast("Any", context.pd_basis),
                    warnings=warnings,
                )
            )
        staging = pandas.DataFrame(staging_rows, columns=list(_STAGING_COLUMNS))
        detail = pandas.DataFrame(detail_rows, columns=list(_DETAIL_COLUMNS))
        summary = _summary_frame(detail_rows, pandas)
        card = self._build_card(
            detail_rows=detail_rows,
            weights=context.weights,
            pd_basis=context.pd_basis,
            as_of_date=as_of_date,
            ecl_term_structure=ecl_term_structure,
        )
        return IfrsProvisionResult(
            staging=staging,
            detail=detail,
            ecl_term_structure=ecl_term_structure,
            summary=summary,
            stage_records=tuple(stage_records),
            ecl_records=tuple(ecl_records),
            card=card,
        )

    def _build_card(
        self,
        *,
        detail_rows: list[dict[str, Any]],
        weights: dict[str, float],
        pd_basis: str,
        as_of_date: str,
        ecl_term_structure: DataFrame,
    ) -> IfrsProvisionCard:
        """Construye la ``IfrsProvisionCard`` CT-2 con totales, conteos y secciones métricas."""
        stages = [int(row["stage"]) for row in detail_rows]
        total_ead = sum(float(row["ead"]) for row in detail_rows)
        total_ecl = sum(float(row["ecl_reported"]) for row in detail_rows)
        falta_dato = _ordered_unique(
            code
            for row in detail_rows
            for code in row["warning_codes"]
            if str(code).startswith("FALTA-DATO")
        )
        metric_sections = {
            "staging_migration": {
                "stage_1": stages.count(1),
                "stage_2": stages.count(2),
                "stage_3": stages.count(3),
            },
            "ecl_by_scenario": _ecl_by_scenario(ecl_term_structure),
            "ecl_by_scenario_basis": _ECL_BY_SCENARIO_BASIS,
            "term_structure_summary": {
                "n_rows": len(ecl_term_structure.index),
                "n_scenarios": len(weights),
            },
        }
        return IfrsProvisionCard(
            as_of_date=as_of_date,
            term_structure_source=self._config.pd.term_structure_source,
            pit_mode=self._config.pd.pit_mode,
            n_rows=len(detail_rows),
            n_stage1=stages.count(1),
            n_stage2=stages.count(2),
            n_stage3=stages.count(3),
            total_ead=total_ead,
            total_ecl_reported=total_ecl,
            scenarios=tuple(weights),
            scenario_weights=dict(weights),
            dependency_versions=_dependency_versions(self._config),
            falta_dato=tuple(falta_dato),
            metric_sections=metric_sections,
        )


class _OperationContext:
    """Contexto por operación en orden del ``frame`` para ensamblar los artefactos (interno)."""

    def __init__(
        self,
        *,
        row_ids: list[str],
        portfolios: list[str],
        days_past_due: NDArrayFloat,
        pd_life: NDArrayFloat,
        pd_pit: NDArrayFloat,
        origination_pd_life: NDArrayFloat | None,
        lgd: dict[str, float],
        ead: dict[str, float],
        eir: dict[str, float],
        triggers: list[tuple[str, ...]],
        exempt: list[bool],
        warnings: dict[str, tuple[str, ...]],
        weights: dict[str, float],
        pd_basis: str,
    ) -> None:
        """Almacena las estructuras por operación ya alineadas al orden del ``frame``."""
        self.row_ids = row_ids
        self.portfolios = portfolios
        self.days_past_due = days_past_due
        self.pd_life = pd_life
        self.pd_pit = pd_pit
        self.origination_pd_life = origination_pd_life
        self.lgd = lgd
        self.ead = ead
        self.eir = eir
        self.triggers = triggers
        self.exempt = exempt
        self.warnings = warnings
        self.weights = weights
        self.pd_basis = pd_basis


# --- Helpers de contrato / extracción de columnas -------------------------------------------------


def _validate_as_of_date(as_of_date: str) -> None:
    """Exige una fecha de cálculo de texto no vacío (SDD-16 §4)."""
    if not isinstance(as_of_date, str) or not as_of_date.strip():
        raise IfrsInputError("as_of_date debe ser un texto no vacío.")


def _frame_row_ids(frame: DataFrame, config: IfrsProvisioningConfig) -> list[str]:
    """Deriva los identificadores de operación (``row_id_col`` o índice) y exige unicidad."""
    column = config.row_id_col
    if column is not None:
        if column not in frame.columns:
            raise IfrsInputError(f"row_id_col '{column}' no está en el frame.")
        raw = frame[column].tolist()
    else:
        raw = frame.index.tolist()
    row_ids = [str(value) for value in raw]
    if len(set(row_ids)) != len(row_ids):
        raise IfrsInputError("Los identificadores de operación (row_id) deben ser únicos.")
    return row_ids


def _frame_column_texts(frame: DataFrame, column: str, label: str) -> list[str]:
    """Extrae una columna de texto obligatoria del ``frame`` como lista de ``str``."""
    if column not in frame.columns:
        raise IfrsInputError(f"{label} '{column}' no está en el frame.")
    return [str(value) for value in frame[column].tolist()]


def _frame_float_column(frame: DataFrame, column: str, label: str, numpy: Any) -> NDArrayFloat:
    """Extrae una columna float64 finita obligatoria del ``frame``."""
    if column not in frame.columns:
        raise IfrsInputError(f"La columna '{column}' ({label}) no está en el frame.")
    return _to_float_array(frame[column].to_numpy(), label, numpy)


def _frame_int_column(frame: DataFrame, column: str, numpy: Any) -> NDArrayFloat:
    """Extrae una columna entera finita (días de mora) validada aguas arriba por el staging."""
    return _to_float_array(frame[column].to_numpy(), column, numpy)


def _origination_pd_life(
    frame: DataFrame, config: IfrsProvisioningConfig, numpy: Any
) -> NDArrayFloat | None:
    """Extrae la PD lifetime en origen si el gatillo cuantitativo la declara, o ``None``."""
    column = config.staging.origination_pd_life_col
    if column is None:
        return None
    return _frame_float_column(frame, column, "origination_pd_life", numpy)


def _validate_term_structure(ts: DataFrame, numpy: Any) -> None:
    """Valida el contrato tidy y las invariantes de la term-structure (SDD-16 §6)."""
    missing = [column for column in _TS_REQUIRED_COLUMNS if column not in ts.columns]
    if missing:
        raise IfrsTermStructureError(
            f"La term-structure debe contener {_TS_REQUIRED_COLUMNS}; "
            f"columnas faltantes: {missing}."
        )
    if ts.shape[0] == 0:
        raise IfrsTermStructureError("La term-structure no puede estar vacía.")
    marginal = _ts_float(ts, "pd_marginal", numpy)
    if bool(numpy.any((marginal < 0.0) | (marginal > 1.0))):
        raise IfrsTermStructureError("pd_marginal de la term-structure debe estar en [0, 1].")
    if _TS_SURVIVAL_COLUMN in ts.columns and _TS_CUMULATIVE_COLUMN in ts.columns:
        survival = _ts_float(ts, _TS_SURVIVAL_COLUMN, numpy)
        cumulative = _ts_float(ts, _TS_CUMULATIVE_COLUMN, numpy)
        if bool(numpy.any(numpy.abs(cumulative - (1.0 - survival)) > _TS_INVARIANT_TOL)):
            raise IfrsTermStructureError(
                "La term-structure rompe la invariante pd_cumulative = 1 - survival."
            )


def _ts_float(ts: DataFrame, column: str, numpy: Any) -> NDArrayFloat:
    """Extrae una columna float64 finita de la term-structure con error de contrato tidy."""
    try:
        array = numpy.asarray(ts[column].to_numpy(), dtype=numpy.float64)
    except (ValueError, TypeError) as exc:
        raise IfrsTermStructureError(
            f"La columna '{column}' de la term-structure debe ser numérica."
        ) from exc
    if not bool(numpy.all(numpy.isfinite(array))):
        raise IfrsTermStructureError(f"La columna '{column}' de la term-structure debe ser finita.")
    return cast("NDArrayFloat", array)


def _prepare_term_structure(ts: DataFrame, config: IfrsProvisioningConfig, numpy: Any) -> DataFrame:
    """Normaliza la columna ``scenario`` y trunca por ``max_lifetime`` (SDD-16 §7)."""
    scenario = [
        _SINGLE_SCENARIO_LABEL if value is None or _is_missing(value) else str(value)
        for value in (
            ts[_TS_SCENARIO_COLUMN].tolist()
            if _TS_SCENARIO_COLUMN in ts.columns
            else [None] * ts.shape[0]
        )
    ]
    period = _ts_float(ts, "period", numpy)
    if bool(numpy.any(period < 1.0)) or bool(numpy.any(period != numpy.floor(period))):
        raise IfrsTermStructureError(
            "period de la term-structure debe ser un entero mayor o igual a 1."
        )
    prepared = ts.copy(deep=True)
    prepared[_TS_SCENARIO_COLUMN] = scenario
    max_lifetime = config.pd.max_lifetime_periods
    if max_lifetime is not None:
        prepared = prepared.loc[period <= max_lifetime].copy(deep=True)
        if prepared.shape[0] == 0:
            raise IfrsTermStructureError(
                f"No quedan períodos con period <= max_lifetime={max_lifetime} en la "
                "term-structure."
            )
    return prepared


def _is_missing(value: Any) -> bool:
    """Indica si un escalar de ``scenario`` es un faltante (``NaN``) sin importar pandas."""
    return isinstance(value, float) and math.isnan(value)


def _ts_lgd_present(ts: DataFrame) -> bool:
    """Indica si la term-structure trae una columna ``lgd`` con al menos un valor no nulo.

    Forward publica la columna toda-``None`` cuando el satellite no proyecta LGD; ese caso no
    cuenta como LGD forward presente (no habría nada que descartar).
    """
    if _TS_LGD_COLUMN not in ts.columns:
        return False
    return bool(ts[_TS_LGD_COLUMN].notna().any())


def _require_pit_basis(ts: DataFrame) -> None:
    """Exige que la term-structure venga etiquetada ``pd_basis='pit'`` para ``consume_pit``."""
    if _TS_PD_BASIS_COLUMN not in ts.columns:
        raise IfrsConfigError(
            "pit_mode='consume_pit' exige una term-structure PIT (columna pd_basis='pit'); "
            "la term-structure entrante no la trae (¿es TTC de survival/markov?)."
        )
    basis = {str(value) for value in ts[_TS_PD_BASIS_COLUMN].tolist()}
    if basis != {"pit"}:
        raise IfrsConfigError(
            "pit_mode='consume_pit' exige pd_basis='pit' en toda la term-structure; "
            f"observado={sorted(basis)}."
        )


def _forbid_pit_basis(ts: DataFrame) -> None:
    """Rechaza aplicar Vasicek sobre una term-structure ya PIT (guard anti doble ajuste macro).

    Espejo de :func:`_require_pit_basis`: columna ``pd_basis`` ausente (survival/markov) o toda
    ``'ttc'`` pasa; cualquier otro conjunto (``'pit'`` de forward, mixto o faltantes) se rechaza.
    """
    if _TS_PD_BASIS_COLUMN not in ts.columns:
        return
    basis = {str(value) for value in ts[_TS_PD_BASIS_COLUMN].tolist()}
    if basis != {"ttc"}:
        raise IfrsConfigError(
            "pit_mode='apply_vasicek' sólo admite term-structures TTC; la entrante declara "
            f"pd_basis={sorted(basis)} (¿curvas PIT de forward? use pit_mode='consume_pit' "
            "para evitar el doble ajuste macro)."
        )


def _apply_vasicek(
    ts: DataFrame, config: IfrsProvisioningConfig, marginal: NDArrayFloat, numpy: Any
) -> NDArrayFloat:
    """Transforma la PD TTC a PIT con Vasicek monofactorial (``rho`` escalar, ``Z``) (SDD-16 §3)."""
    _forbid_pit_basis(ts)
    rho = config.pd.rho
    if rho is None:
        raise IfrsConfigError(
            "pit_mode='apply_vasicek' exige un rho escalar (pd.rho) en tiempo de cálculo."
        )
    column = config.pd.systemic_factor_col
    if column is None or column not in ts.columns:
        raise IfrsConfigError(
            "pit_mode='apply_vasicek' exige la columna del factor sistémico Z "
            "(pd.systemic_factor_col) en la term-structure."
        )
    z = _ts_float(ts, column, numpy)
    return vasicek_pit(marginal, rho=rho, z=z)


def _forward_weights(ts: DataFrame, scenarios_present: list[str], numpy: Any) -> dict[str, float]:
    """Extrae los pesos por escenario de la columna ``scenario_weight`` de forward (SDD-16 §5)."""
    if _TS_SCENARIO_WEIGHT_COLUMN not in ts.columns:
        raise IfrsConfigError(
            "scenarios.source='forward' exige la columna scenario_weight en la term-structure."
        )
    weight = _ts_float(ts, _TS_SCENARIO_WEIGHT_COLUMN, numpy)
    scenarios = [str(value) for value in ts[_TS_SCENARIO_COLUMN].tolist()]
    resolved: dict[str, float] = {}
    for name, value in zip(scenarios, (float(item) for item in weight), strict=True):
        if name in resolved and resolved[name] != value:
            raise IfrsConfigError(
                f"El peso del escenario '{name}' no es constante en la term-structure de forward."
            )
        resolved[name] = value
    return {name: resolved[name] for name in scenarios_present}


def _weighted_horizons(
    ts: DataFrame,
    config: IfrsProvisioningConfig,
    weights: dict[str, float],
    pandas: Any,
) -> tuple[dict[str, float], dict[str, float]]:
    """Deriva y pondera por escenario la PD 12m/lifetime por operación (SDD-16 §7)."""
    ts_pd = ts.loc[:, ["row_id", _TS_SCENARIO_COLUMN, "period", "pd_marginal"]].copy(deep=True)
    horizons = marginal_to_horizon(ts_pd, horizon_periods=config.pd.horizon_12m_periods)
    weight_series = horizons[_TS_SCENARIO_COLUMN].map(weights)
    weighted = pandas.DataFrame(
        {
            "row_id": [str(value) for value in horizons["row_id"].to_numpy()],
            "_pd_12m": horizons["pd_12m"].to_numpy() * weight_series.to_numpy(),
            "_pd_life": horizons["pd_life"].to_numpy() * weight_series.to_numpy(),
        }
    )
    grouped = weighted.groupby("row_id", sort=False, dropna=False).agg(
        pd_12m=("_pd_12m", "sum"), pd_life=("_pd_life", "sum")
    )
    pd_12m = {str(rid): float(value) for rid, value in grouped["pd_12m"].items()}
    pd_life = {str(rid): float(value) for rid, value in grouped["pd_life"].items()}
    return pd_12m, pd_life


def _calibrated_pd_12m(
    calibrated: DataFrame | None, row_ids: list[str], numpy: Any
) -> dict[str, float]:
    """Ancla la PD 12m a la PD calibrada de SDD-10 (``base_pd_source='calibration'``)."""
    if calibrated is None:
        raise IfrsConfigError(
            "base_pd_source='calibration' exige el frame de PD calibrada "
            "(calibration.calibrated_pd_frame)."
        )
    if _CALIBRATED_PD_COLUMN not in calibrated.columns:
        raise IfrsConfigError(
            f"El frame de PD calibrada debe contener la columna '{_CALIBRATED_PD_COLUMN}'."
        )
    keys = [str(index) for index in calibrated.index]
    values = _to_float_array(
        calibrated[_CALIBRATED_PD_COLUMN].to_numpy(), _CALIBRATED_PD_COLUMN, numpy
    )
    mapping = dict(zip(keys, (float(value) for value in values), strict=True))
    missing = [rid for rid in row_ids if rid not in mapping]
    if missing:
        raise IfrsConfigError(f"El frame de PD calibrada no cubre las operaciones: {missing}.")
    return {rid: mapping[rid] for rid in row_ids}


def _components_frame(
    ts: DataFrame,
    row_ids: list[str],
    lgd_by_rid: dict[str, float],
    ead_by_rid: dict[str, float],
    pandas: Any,
) -> DataFrame:
    """Arma la malla tidy de componentes para ``EclEngine`` en orden del ``frame`` (SDD-16 §7)."""
    order = {rid: index for index, rid in enumerate(row_ids)}
    ts_row_ids = [str(value) for value in ts["row_id"].to_numpy()]
    components = pandas.DataFrame(
        {
            "row_id": ts_row_ids,
            "scenario": [str(value) for value in ts[_TS_SCENARIO_COLUMN].tolist()],
            "period": ts["period"].to_numpy(),
            "time_value": ts["time_value"].to_numpy(),
            "pd_marginal": ts["pd_marginal"].to_numpy(),
            "lgd": [lgd_by_rid[rid] for rid in ts_row_ids],
            "ead": [ead_by_rid[rid] for rid in ts_row_ids],
            "_order": [order[rid] for rid in ts_row_ids],
        }
    )
    components = components.sort_values(
        ["_order", "scenario", "period"], kind="mergesort"
    ).reset_index(drop=True)
    return cast("DataFrame", components.drop(columns="_order"))


def _summary_frame(detail_rows: list[dict[str, Any]], pandas: Any) -> DataFrame:
    """Agrega el resumen por ``portfolio`` x ``stage`` con cobertura y warnings (SDD-16 §6)."""
    groups: dict[tuple[str, int], dict[str, Any]] = {}
    for row in detail_rows:
        key = (str(row["portfolio"]), int(row["stage"]))
        bucket = groups.setdefault(
            key,
            {"n_rows": 0, "total_ead": 0.0, "total_ecl_reported": 0.0, "warnings": []},
        )
        bucket["n_rows"] += 1
        bucket["total_ead"] += float(row["ead"])
        bucket["total_ecl_reported"] += float(row["ecl_reported"])
        bucket["warnings"].extend(row["warning_codes"])
    summary_rows: list[dict[str, Any]] = []
    for portfolio, stage in sorted(groups):
        bucket = groups[(portfolio, stage)]
        total_ead = float(bucket["total_ead"])
        total_ecl = float(bucket["total_ecl_reported"])
        coverage = total_ecl / total_ead if total_ead > 0.0 else 0.0
        summary_rows.append(
            {
                "portfolio": portfolio,
                "stage": stage,
                "scenario": _SUMMARY_SCENARIO_LABEL,
                "n_rows": int(bucket["n_rows"]),
                "total_ead": total_ead,
                "total_ecl_reported": total_ecl,
                "coverage_ratio": coverage,
                "warning_codes": tuple(_ordered_unique(bucket["warnings"])),
            }
        )
    return cast("DataFrame", pandas.DataFrame(summary_rows, columns=list(_SUMMARY_COLUMNS)))


def _ecl_by_scenario(ecl_term_structure: DataFrame) -> dict[str, float]:
    """Suma la ECL marginal (sin ponderar) por escenario como diagnóstico auditable CT-2."""
    grouped = ecl_term_structure.groupby("scenario", sort=True, dropna=False)["ecl_marginal"].sum()
    return {str(scenario): float(value) for scenario, value in grouped.items()}


def _check_row_coverage(frame_row_ids: list[str], ts_row_ids: list[str]) -> None:
    """Exige que la term-structure cubra exactamente las operaciones del ``frame``."""
    frame_set = set(frame_row_ids)
    ts_set = set(ts_row_ids)
    if frame_set != ts_set:
        faltan = sorted(frame_set - ts_set)
        sobran = sorted(ts_set - frame_set)
        raise IfrsTermStructureError(
            "La term-structure debe cubrir exactamente las operaciones del frame "
            f"(sin curva={faltan}, sin operación={sobran})."
        )


def _ordered_unique(values: Any) -> list[str]:
    """Devuelve los elementos únicos preservando el orden de aparición (determinismo)."""
    return list(dict.fromkeys(str(value) for value in values))


def _to_float_array(values: Any, name: str, numpy: Any) -> NDArrayFloat:
    """Castea a float64 y exige valores finitos, mapeando fallos a ``IfrsInputError``."""
    try:
        array = numpy.asarray(values, dtype=numpy.float64)
    except (ValueError, TypeError) as exc:
        raise IfrsInputError(f"El campo '{name}' debe ser numérico.") from exc
    if not bool(numpy.all(numpy.isfinite(array))):
        raise IfrsInputError(f"El campo '{name}' debe contener sólo valores finitos.")
    return cast("NDArrayFloat", array)


def _as_dataframe(value: Any, pandas: Any, artifact: str) -> DataFrame:
    """Valida que un insumo sea un ``pandas.DataFrame`` antes de leerlo."""
    if isinstance(value, pandas.DataFrame):
        return cast("DataFrame", value)
    raise IfrsInputError(
        f"El insumo '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _dependency_versions(config: IfrsProvisioningConfig) -> dict[str, str]:
    """Recolecta versiones de dependencias según los enfoques ejercidos (auditoría §9)."""
    distributions = {"pandas": "pandas", "numpy": "numpy"}
    if config.pd.pit_mode == "apply_vasicek":
        distributions["scipy"] = "scipy"
    if config.lgd.method in ("beta_regression", "fractional_response"):
        distributions["statsmodels"] = "statsmodels"
    versions: dict[str, str] = {}
    for public_name, distribution in distributions.items():
        try:
            versions[public_name] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[public_name] = "no_instalado"
    return versions


def _import_numpy() -> Any:
    """Importa ``numpy`` bajo demanda para preservar el import liviano del núcleo."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_NUMPY_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa ``pandas`` bajo demanda para preservar el import liviano del núcleo."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_PANDAS_MESSAGE) from exc
