"""Motor determinista de orquestación de provisiones: piso prudencial CMF vs IFRS 9 (SDD-17 §6/§7).

``ProvisioningOrchestrator`` es la **capa fina** que consume un ``CmfProvisionResult`` (SDD-15,
montos ``Decimal``) y un ``IfrsProvisionResult`` (SDD-16, montos ``float``), los alinea al **nivel
de comparación** declarado (``total`` / ``portfolio`` / ``segment`` / ``operation``), reconcilia sus
dominios numéricos preservando los originales y aplica ``reported = máximo(cmf, ifrs9)`` por celda
(regla dura ESPEC §5.4). Publica el comparativo auditable como :class:`ProvisionOrchestrationResult`
usando los DTOs de :mod:`nikodym.provisioning.results`; **no** recalcula PI/PDI/PE ni ECL.

Correctitud crítica (SDD-17 §3): el ECL IFRS 9 se agrega desde ``detail``/``ecl_records`` (por
operación, ya colapsado por escenario ``Σ_k w_k``), **nunca** desde ``summary`` (desglosado por
escenario), lo que duplicaría la masa. A nivel ``total`` se usa ``card.total_ecl_reported`` (ya
colapsado) y ``card.total_provision_amount`` (CMF).

El módulo **no importa** los paquetes ``cmf``/``ifrs9`` como código (solo referencia sus DTOs bajo
``TYPE_CHECKING``) ni ``pandas`` en top-level: ``pandas`` se resuelve perezosamente dentro de
``compare`` para preservar el núcleo liviano. El motor es **determinista** (sin RNG); normaliza
``-0.0 → 0.0`` y jamás publica ``NaN``/``inf``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias, cast

from nikodym.core.audit import AuditEvent
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.config import ProvisioningComparisonLevel, ProvisioningConfig
from nikodym.provisioning.exceptions import (
    ProvisioningAlignmentError,
    ProvisioningConfigError,
    ProvisioningCoverageError,
    ProvisioningInputError,
)
from nikodym.provisioning.results import (
    ProvisionBinding,
    ProvisionComparisonRecord,
    ProvisionComparisonSummary,
    ProvisionOrchestrationCard,
    ProvisionOrchestrationResult,
)

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.audit import AuditSink
    from nikodym.provisioning.cmf.results import CmfProvisionResult
    from nikodym.provisioning.ifrs9.results import IfrsProvisionResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditSink: TypeAlias = Any
    CmfProvisionResult: TypeAlias = Any
    IfrsProvisionResult: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["ProvisioningOrchestrator"]

_PROV_EXTRA_MESSAGE = "ProvisioningOrchestrator requiere pandas; instale las dependencias base."
_TOTAL_CELL_ID = "TOTAL"
_MAX_RULE_SOURCE = "ESPECIFICACIONES.md §5.4 (provisión reportada = máximo(CMF, IFRS 9))"

_COMPARISON_COLUMNS: tuple[str, ...] = (
    "cell_id",
    "level",
    "cmf_provision",
    "ifrs9_ecl",
    "reported_provision",
    "binding",
    "coverage",
    "warning_codes",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "level",
    "n_cells",
    "n_binding_cmf",
    "n_binding_ifrs9",
    "n_binding_tie",
    "total_cmf_provision",
    "total_ifrs9_ecl",
    "total_reported_provision",
    "warning_codes",
)

# Códigos de warning por celda (comparativo) y notas FALTA-DATO (card).
_WARN_FLOOR_INCOMPLETE = "piso_incompleto"
_WARN_IMPUTED_ZERO = "cobertura_imputada_cero"
_WARN_IFRS9_MISSING = "ifrs9_ausente"
_WARN_CMF_MISSING = "cmf_ausente"


class ProvisioningOrchestrator:
    """Combina provisión CMF (piso) e IFRS 9 (ECL) aplicando el máximo por nivel (SDD-17 §6/§7)."""

    config_cls: ClassVar[type[ProvisioningConfig]] = ProvisioningConfig

    def __init__(self, config: ProvisioningConfig) -> None:
        """Recibe la sección ``ProvisioningConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: ProvisioningConfig) -> ProvisioningOrchestrator:
        """Construye el orquestador desde ``NikodymConfig.provisioning`` (revalida si aplica)."""
        if not isinstance(cfg, ProvisioningConfig):
            cfg = ProvisioningConfig.model_validate(cfg)
        return cls(cfg)

    def compare(
        self,
        *,
        cmf: CmfProvisionResult | None,
        ifrs9: IfrsProvisionResult | None,
        as_of_date: str,
        audit: AuditSink | None = None,
    ) -> ProvisionOrchestrationResult:
        """Alinea, reconcilia y aplica ``reported = máximo(cmf, ifrs9)`` por celda, determinista."""
        pd_module: Any = _import_pandas()
        cfg = self.config
        as_of = _require_as_of_date(as_of_date)

        cmf_engine = cmf if cfg.consume_cmf else None
        ifrs9_engine = ifrs9 if cfg.consume_ifrs9 else None
        if cmf_engine is None and ifrs9_engine is None:
            raise ProvisioningInputError(
                "La orquestación de provisiones requiere al menos un motor (CMF o IFRS 9); "
                "ninguno está presente/habilitado."
            )
        if cfg.require_both and not (cmf_engine is not None and ifrs9_engine is not None):
            missing = "IFRS 9" if cmf_engine is not None else "CMF"
            raise ProvisioningInputError(
                f"require_both=True exige ambos motores; falta el resultado de {missing} "
                "(el piso prudencial presupone CMF e IFRS 9)."
            )

        both_engines = cmf_engine is not None and ifrs9_engine is not None
        engines_present: tuple[str, ...] = tuple(
            name
            for name, present in (
                ("cmf", cmf_engine is not None),
                ("ifrs9", ifrs9_engine is not None),
            )
            if present
        )

        cmf_cells: dict[str, Decimal] = {}
        ifrs9_cells: dict[str, float] = {}
        if cmf_engine is not None:
            cmf_cells = _cmf_cells(cmf_engine, cfg=cfg)
        if ifrs9_engine is not None:
            ifrs9_cells = _ifrs9_cells(ifrs9_engine, cfg=cfg)

        if cfg.comparison_level == "operation" and both_engines:
            _check_operation_alignment(cmf_cells, ifrs9_cells)

        falta_dato: list[str] = []
        if not both_engines:
            present = "cmf" if cmf_engine is not None else "ifrs9"
            falta_dato.append(
                f"FALTA-DATO-PROV-3: piso incompleto; solo el motor {present} está presente "
                "(require_both=False)."
            )

        records: list[ProvisionComparisonRecord] = []
        for cell_id in _ordered_cell_ids(cmf_cells, ifrs9_cells):
            records.append(
                _build_record(
                    cell_id,
                    cmf_cells.get(cell_id),
                    ifrs9_cells.get(cell_id),
                    cfg=cfg,
                    both_engines=both_engines,
                    falta_dato=falta_dato,
                )
            )

        summary_dto = _build_summary(records, level=cfg.comparison_level)
        card = ProvisionOrchestrationCard(
            as_of_date=as_of,
            comparison_level=cfg.comparison_level,
            engines_present=engines_present,
            n_cells=summary_dto.n_cells,
            n_binding_cmf=summary_dto.n_binding_cmf,
            n_binding_ifrs9=summary_dto.n_binding_ifrs9,
            n_binding_tie=summary_dto.n_binding_tie,
            total_cmf_provision=summary_dto.total_cmf_provision,
            total_ifrs9_ecl=summary_dto.total_ifrs9_ecl,
            total_reported_provision=summary_dto.total_reported_provision,
            cmf_matrix_version=(cmf_engine.card.matrix_version if cmf_engine is not None else None),
            ifrs9_term_structure_source=(
                ifrs9_engine.card.term_structure_source if ifrs9_engine is not None else None
            ),
            regulatory_sources=_regulatory_sources(cmf_engine),
            falta_dato=tuple(dict.fromkeys(falta_dato)),
            metric_sections=_metric_sections(cfg, records),
        )

        result = ProvisionOrchestrationResult(
            comparison=_comparison_frame(records, pd_module),
            summary=_summary_frame(summary_dto, pd_module),
            records=tuple(records),
            card=card,
            ifrs9_term_structure=(
                ifrs9_engine.term_structure() if ifrs9_engine is not None else None
            ),
        )
        _emit_audit(audit, cfg=cfg, card=card, engines=engines_present)
        return result


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_PROV_EXTRA_MESSAGE) from exc


def _require_as_of_date(as_of_date: str) -> str:
    """Valida que la fecha de cálculo heredada de los motores no esté vacía."""
    if not as_of_date.strip():
        raise ProvisioningInputError("compare requiere as_of_date no vacío.")
    return as_of_date


def _cmf_cells(cmf: CmfProvisionResult, *, cfg: ProvisioningConfig) -> dict[str, Decimal]:
    """Agrega la provisión CMF (``Decimal``) a las celdas del nivel declarado."""
    level = cfg.comparison_level
    if level == "total":
        return {_TOTAL_CELL_ID: _to_decimal(cmf.card.total_provision_amount)}
    if level == "operation":
        cells: dict[str, Decimal] = {}
        for record in cmf.records:
            key = str(record.row_id)
            if key in cells:
                raise ProvisioningInputError(
                    f"comparison_level='operation': row_id CMF duplicado {key!r} en records."
                )
            cells[key] = _to_decimal(record.provision_amount)
        return cells
    column = _level_column(cfg, engine="CMF")
    detail: Any = cmf.detail
    if column not in detail.columns:
        raise _missing_column_error(level, column, engine="CMF")
    grouped: dict[str, Decimal] = {}
    for key_value, provision in zip(
        detail[column].tolist(), detail["provision_amount"].tolist(), strict=True
    ):
        key = str(key_value)
        grouped[key] = grouped.get(key, Decimal("0")) + _to_decimal(provision)
    if level == "portfolio" and cfg.portfolio_crosswalk:
        grouped = _apply_crosswalk(grouped, cfg.portfolio_crosswalk)
    return grouped


def _ifrs9_cells(ifrs9: IfrsProvisionResult, *, cfg: ProvisioningConfig) -> dict[str, float]:
    """Agrega el ECL IFRS 9 desde ``detail``/``ecl_records`` (nunca ``summary``), en ``float``."""
    level = cfg.comparison_level
    if level == "total":
        return {_TOTAL_CELL_ID: _to_float(ifrs9.card.total_ecl_reported)}
    if level == "operation":
        cells: dict[str, float] = {}
        for record in ifrs9.ecl_records:
            key = str(record.row_id)
            if key in cells:
                raise ProvisioningInputError(
                    f"comparison_level='operation': row_id IFRS 9 duplicado {key!r} en ecl_records."
                )
            cells[key] = _to_float(record.ecl_reported)
        return cells
    column = _level_column(cfg, engine="IFRS 9")
    detail: Any = ifrs9.detail
    if column not in detail.columns:
        raise _missing_column_error(level, column, engine="IFRS 9")
    grouped: dict[str, list[float]] = {}
    for key_value, ecl in zip(
        detail[column].tolist(), detail["ecl_reported"].tolist(), strict=True
    ):
        grouped.setdefault(str(key_value), []).append(_to_float(ecl))
    return {key: math.fsum(values) for key, values in grouped.items()}


def _level_column(cfg: ProvisioningConfig, *, engine: str) -> str:
    """Resuelve la columna de agrupación (cartera o segmento) del motor para el nivel actual."""
    if cfg.comparison_level == "portfolio":
        return cfg.cmf_portfolio_col if engine == "CMF" else cfg.ifrs9_portfolio_col
    # segment: columna única provista por el usuario (config garantiza que no es None).
    assert cfg.segment_col is not None
    return cfg.segment_col


def _missing_column_error(
    level: ProvisioningComparisonLevel, column: str, *, engine: str
) -> ProvisioningConfigError | ProvisioningAlignmentError:
    """Construye el error por columna de agrupación ausente en el detalle del motor."""
    if level == "segment":
        return ProvisioningConfigError(
            f"comparison_level='segment' exige que segment_col={column!r} exista en el detalle "
            f"{engine}; no está presente."
        )
    return ProvisioningAlignmentError(
        f"comparison_level='portfolio': la columna de cartera {column!r} no está en el detalle "
        f"{engine}; las taxonomías no son reconciliables."
    )


def _apply_crosswalk(cells: dict[str, Decimal], crosswalk: dict[str, str]) -> dict[str, Decimal]:
    """Remapea las carteras CMF a la taxonomía IFRS 9 vía crosswalk, sumando colisiones."""
    remapped: dict[str, Decimal] = {}
    for key, value in cells.items():
        mapped = crosswalk.get(key, key)
        remapped[mapped] = remapped.get(mapped, Decimal("0")) + value
    return remapped


def _check_operation_alignment(
    cmf_cells: dict[str, Decimal], ifrs9_cells: dict[str, float]
) -> None:
    """Exige perímetros de operación reconciliables entre ambos motores (SDD-17 §6 caveat)."""
    if set(cmf_cells) != set(ifrs9_cells):
        solo_cmf = sorted(set(cmf_cells) - set(ifrs9_cells))
        solo_ifrs9 = sorted(set(ifrs9_cells) - set(cmf_cells))
        raise ProvisioningAlignmentError(
            "comparison_level='operation': los perímetros de operación no son reconciliables; "
            f"solo-CMF={solo_cmf!r}, solo-IFRS 9={solo_ifrs9!r}."
        )


def _ordered_cell_ids(
    cmf_cells: dict[str, Decimal], ifrs9_cells: dict[str, float]
) -> tuple[str, ...]:
    """Devuelve las celdas en orden canónico estable (unión ordenada de claves)."""
    return tuple(sorted(set(cmf_cells) | set(ifrs9_cells)))


def _build_record(
    cell_id: str,
    cmf_val: Decimal | None,
    ifrs9_val: float | None,
    *,
    cfg: ProvisioningConfig,
    both_engines: bool,
    falta_dato: list[str],
) -> ProvisionComparisonRecord:
    """Construye el registro de una celda aplicando el máximo, el binding y la cobertura."""
    level = cfg.comparison_level
    if cmf_val is not None and ifrs9_val is not None:
        return _both_record(cell_id, level=level, cmf_val=cmf_val, ifrs9_val=ifrs9_val, cfg=cfg)

    missing = "ifrs9" if cmf_val is not None else "cmf"
    if not both_engines:
        return _only_record(
            cell_id,
            level=level,
            cmf_val=cmf_val,
            ifrs9_val=ifrs9_val,
            rounding=cfg.rounding,
            warnings=(_WARN_FLOOR_INCOMPLETE,),
        )
    if cfg.coverage_policy == "fail":
        cubierto = "CMF" if cmf_val is not None else "IFRS 9"
        raise ProvisioningCoverageError(
            f"comparison_level={level!r}: la celda {cell_id!r} está cubierta solo por {cubierto}; "
            "coverage_policy='fail'."
        )
    if cfg.coverage_policy == "treat_missing_as_zero":
        falta_dato.append(
            f"FALTA-DATO-PROV: celda {cell_id!r} imputó 0 al motor {missing} "
            "(treat_missing_as_zero)."
        )
        return _both_record(
            cell_id,
            level=level,
            cmf_val=cmf_val if cmf_val is not None else Decimal("0"),
            ifrs9_val=ifrs9_val if ifrs9_val is not None else 0.0,
            cfg=cfg,
            warnings=(_WARN_IMPUTED_ZERO,),
        )
    falta_dato.append(f"FALTA-DATO-PROV-1: celda {cell_id!r} sin contraparte {missing}.")
    warning = _WARN_IFRS9_MISSING if cmf_val is not None else _WARN_CMF_MISSING
    return _only_record(
        cell_id,
        level=level,
        cmf_val=cmf_val,
        ifrs9_val=ifrs9_val,
        rounding=cfg.rounding,
        warnings=(warning,),
    )


def _both_record(
    cell_id: str,
    *,
    level: ProvisioningComparisonLevel,
    cmf_val: Decimal,
    ifrs9_val: float,
    cfg: ProvisioningConfig,
    warnings: tuple[str, ...] = (),
) -> ProvisionComparisonRecord:
    """Construye un registro con cobertura ``both``: reconcilia y aplica el máximo con binding."""
    reported, binding = _reconcile_both(cmf_val, ifrs9_val, cfg=cfg)
    return ProvisionComparisonRecord(
        cell_id=cell_id,
        level=level,
        cmf_provision=cmf_val,
        ifrs9_ecl=ifrs9_val,
        reported_provision=_apply_rounding(reported, cfg.rounding),
        binding=binding,
        coverage="both",
        warnings=warnings,
    )


def _only_record(
    cell_id: str,
    *,
    level: ProvisioningComparisonLevel,
    cmf_val: Decimal | None,
    ifrs9_val: float | None,
    rounding: str,
    warnings: tuple[str, ...],
) -> ProvisionComparisonRecord:
    """Construye un registro de cobertura parcial (``cmf_only``/``ifrs9_only``) del disponible."""
    if cmf_val is not None:
        return ProvisionComparisonRecord(
            cell_id=cell_id,
            level=level,
            cmf_provision=cmf_val,
            ifrs9_ecl=None,
            reported_provision=_apply_rounding(cmf_val, rounding),
            binding="cmf_only",
            coverage="cmf_only",
            warnings=warnings,
        )
    assert ifrs9_val is not None
    return ProvisionComparisonRecord(
        cell_id=cell_id,
        level=level,
        cmf_provision=None,
        ifrs9_ecl=ifrs9_val,
        reported_provision=_apply_rounding(Decimal(str(ifrs9_val)), rounding),
        binding="ifrs9_only",
        coverage="ifrs9_only",
        warnings=warnings,
    )


def _reconcile_both(
    cmf_val: Decimal, ifrs9_val: float, *, cfg: ProvisioningConfig
) -> tuple[Decimal, ProvisionBinding]:
    """Reconcilia ``Decimal`` (CMF) y ``float`` (IFRS 9); computa máximo y motor vinculante."""
    cmf_float = float(cmf_val)
    diff = cmf_float - ifrs9_val
    if cfg.numeric_reconciliation == "decimal_quantize":
        ifrs9_dec = Decimal(str(ifrs9_val))
        reported = cmf_val if cmf_val >= ifrs9_dec else ifrs9_dec
    else:
        reported = Decimal(str(cmf_float if cmf_float >= ifrs9_val else ifrs9_val))
    binding: ProvisionBinding
    if abs(diff) <= cfg.tie_tolerance:
        binding = "tie"
    elif diff > 0:
        binding = "cmf"
    else:
        binding = "ifrs9"
    return reported, binding


def _apply_rounding(value: Decimal, rounding: str) -> Decimal:
    """Aplica el redondeo contable explícito del piso reportado (default ``none``)."""
    if rounding == "none":
        return value
    quantum = Decimal("0.01") if rounding == "currency_2dp" else Decimal("1")
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _build_summary(
    records: list[ProvisionComparisonRecord], *, level: ProvisioningComparisonLevel
) -> ProvisionComparisonSummary:
    """Agrega los registros al resumen por nivel (totales ``Decimal`` y conteos por binding)."""
    cmf_amounts: list[Decimal] = []
    ecl_amounts: list[float] = []
    reported_amounts: list[Decimal] = []
    warn_seen: list[str] = []
    n_cmf = n_ifrs9 = n_tie = 0
    for record in records:
        if record.cmf_provision is not None:
            cmf_amounts.append(record.cmf_provision)
        if record.ifrs9_ecl is not None:
            ecl_amounts.append(record.ifrs9_ecl)
        reported_amounts.append(record.reported_provision)
        warn_seen.extend(record.warnings)
        if record.binding == "cmf":
            n_cmf += 1
        elif record.binding == "ifrs9":
            n_ifrs9 += 1
        elif record.binding == "tie":
            n_tie += 1
    return ProvisionComparisonSummary(
        level=level,
        n_cells=len(records),
        n_binding_cmf=n_cmf,
        n_binding_ifrs9=n_ifrs9,
        n_binding_tie=n_tie,
        total_cmf_provision=sum(cmf_amounts, Decimal("0")),
        total_ifrs9_ecl=Decimal(str(math.fsum(ecl_amounts))),
        total_reported_provision=sum(reported_amounts, Decimal("0")),
        warnings=tuple(dict.fromkeys(warn_seen)),
    )


def _regulatory_sources(cmf: CmfProvisionResult | None) -> tuple[str, ...]:
    """Compone las fuentes regulatorias: la regla del máximo más las heredadas del CMF."""
    sources: list[str] = [_MAX_RULE_SOURCE]
    if cmf is not None:
        sources.extend(cmf.card.regulatory_sources)
    return tuple(dict.fromkeys(sources))


def _metric_sections(
    cfg: ProvisioningConfig, records: list[ProvisionComparisonRecord]
) -> dict[str, Any]:
    """Construye el payload CT-2 aditivo (nivel, reconciliación, ``floor_bite_ratio``)."""
    counts = {
        "cmf": sum(1 for r in records if r.binding == "cmf"),
        "ifrs9": sum(1 for r in records if r.binding == "ifrs9"),
        "tie": sum(1 for r in records if r.binding == "tie"),
        "cmf_only": sum(1 for r in records if r.binding == "cmf_only"),
        "ifrs9_only": sum(1 for r in records if r.binding == "ifrs9_only"),
    }
    return {
        "provisioning_orchestration": {
            "comparison_level": cfg.comparison_level,
            "numeric_reconciliation": cfg.numeric_reconciliation,
            "tie_tolerance": cfg.tie_tolerance,
            "rounding": cfg.rounding,
            "floor_bite_ratio": _floor_bite_ratio(counts["cmf"], len(records)),
            "binding_counts": counts,
        }
    }


def _floor_bite_ratio(n_binding_cmf: int, n_cells: int) -> float | None:
    """Fracción de celdas donde muerde el piso CMF; ``None`` si no hay celdas."""
    if n_cells == 0:
        return None
    return n_binding_cmf / n_cells


def _comparison_frame(records: list[ProvisionComparisonRecord], pd_module: Any) -> DataFrame:
    """Materializa el comparativo por celda con las columnas canónicas SDD-17 §6."""
    data = {
        "cell_id": [record.cell_id for record in records],
        "level": [record.level for record in records],
        "cmf_provision": [record.cmf_provision for record in records],
        "ifrs9_ecl": [record.ifrs9_ecl for record in records],
        "reported_provision": [record.reported_provision for record in records],
        "binding": [record.binding for record in records],
        "coverage": [record.coverage for record in records],
        "warning_codes": [record.warnings for record in records],
    }
    return cast(DataFrame, pd_module.DataFrame(data, columns=list(_COMPARISON_COLUMNS)))


def _summary_frame(summary: ProvisionComparisonSummary, pd_module: Any) -> DataFrame:
    """Materializa el resumen por nivel con las columnas canónicas SDD-17 §6."""
    data = {
        "level": [summary.level],
        "n_cells": [summary.n_cells],
        "n_binding_cmf": [summary.n_binding_cmf],
        "n_binding_ifrs9": [summary.n_binding_ifrs9],
        "n_binding_tie": [summary.n_binding_tie],
        "total_cmf_provision": [summary.total_cmf_provision],
        "total_ifrs9_ecl": [summary.total_ifrs9_ecl],
        "total_reported_provision": [summary.total_reported_provision],
        "warning_codes": [summary.warnings],
    }
    return cast(DataFrame, pd_module.DataFrame(data, columns=list(_SUMMARY_COLUMNS)))


def _to_decimal(value: Any) -> Decimal:
    """Normaliza un monto CMF a ``Decimal`` finito y no negativo (defensa en profundidad §8)."""
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool) or not isinstance(value, Real):
        raise ProvisioningInputError(f"Monto CMF no numérico: {value!r}.")
    else:
        result = Decimal(str(value))
    if not result.is_finite():
        raise ProvisioningInputError(f"Monto CMF no finito (NaN/inf): {value!r}.")
    if result < 0:
        raise ProvisioningInputError(f"Monto CMF negativo no permitido: {value!r}.")
    return result


def _to_float(value: Any) -> float:
    """Normaliza un ECL IFRS 9 a ``float`` finito y no negativo (defensa en profundidad §8)."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ProvisioningInputError(f"ECL IFRS 9 no numérico: {value!r}.")
    result = float(value)
    if not math.isfinite(result):
        raise ProvisioningInputError(f"ECL IFRS 9 no finito (NaN/inf): {value!r}.")
    if result < 0:
        raise ProvisioningInputError(f"ECL IFRS 9 negativo no permitido: {value!r}.")
    return result


def _emit_audit(
    audit: AuditSink | None,
    *,
    cfg: ProvisioningConfig,
    card: ProvisionOrchestrationCard,
    engines: tuple[str, ...],
) -> None:
    """Registra las decisiones auditables del piso prudencial si se inyectó un sink (SDD-17 §9)."""
    if audit is None:
        return
    ts = datetime.now(UTC)
    decisions: tuple[tuple[str, Any, Any, str], ...] = (
        (
            "provisioning_level",
            cfg.comparison_level,
            {"portfolio_crosswalk": dict(cfg.portfolio_crosswalk), "n_cells": card.n_cells},
            "alinear_nivel_comparacion",
        ),
        (
            "provisioning_engines",
            {"require_both": cfg.require_both},
            {"engines_present": list(engines)},
            "determinar_motores_presentes",
        ),
        (
            "provisioning_reconciliation",
            {"numeric_reconciliation": cfg.numeric_reconciliation, "rounding": cfg.rounding},
            {"tie_tolerance": cfg.tie_tolerance},
            "reconciliar_dominios_numericos",
        ),
        (
            "provisioning_binding",
            cfg.comparison_level,
            {
                "n_binding_cmf": card.n_binding_cmf,
                "n_binding_ifrs9": card.n_binding_ifrs9,
                "n_binding_tie": card.n_binding_tie,
            },
            "aplicar_maximo_regulatorio",
        ),
        (
            "provisioning_coverage",
            cfg.coverage_policy,
            {
                "total_reported_provision": str(card.total_reported_provision),
                "falta_dato": list(card.falta_dato),
            },
            "resolver_cobertura_parcial",
        ),
    )
    for regla, umbral, valor, accion in decisions:
        audit.emit(
            AuditEvent(
                kind="decision",
                step=None,
                payload={"regla": regla, "umbral": umbral, "valor": valor, "accion": accion},
                ts=ts,
            )
        )
