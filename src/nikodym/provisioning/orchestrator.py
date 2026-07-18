"""Motor determinista de orquestación de provisiones: dos fuentes configurables (SDD-17 §6/§7).

``ProvisioningOrchestrator`` es la **capa fina** que consume **dos resultados de provisión
cualesquiera** —``provisioning_cmf`` (método estándar del B-1, montos ``Decimal``),
``provisioning_internal`` (método interno del B-1 §3, montos ``Decimal``) y ``provisioning_ifrs9``
(ECL, montos ``float``)—, los alinea al **nivel de comparación** declarado (``total`` /
``portfolio`` / ``segment`` / ``operation``), reconcilia sus dominios numéricos preservando los
originales y aplica la **regla declarada** por celda:

- ``rule='max'`` → ``reported = máximo(a, b)``. Entre **estándar e interno**, a nivel ``total`` y
  bajo el precontrato de una institución por corrida, esto representa la norma citada:
  Cap. B-1, hoja 10-11 (Circular N° 2.346), *"el mayor valor obtenido entre el respectivo método
  estándar y el método interno"*, **por institución**. Nikodym no valida hoy que el perímetro de la
  corrida contenga una sola institución. Entre CMF e IFRS 9 es un **comparativo entre marcos
  contables**, no una exigencia
  chilena (Cap. A-2 num. 5 excluye el deterioro de NIIF 9 sobre las colocaciones).
- ``rule='use_internal'`` → ``reported = interno``, aunque la otra fuente sea mayor. Sólo representa
  el otro modo
  del mismo párrafo del B-1: *"En el caso de uso de los métodos internos evaluados y no objetados
  (…) la constitución de provisiones se efectuará de acuerdo con los resultados de su aplicación"*,
  cuando el par es estándar/interno, el nivel es ``total`` y la institución acredita esa condición;
  Nikodym no verifica la evaluación/no objeción.

Publica el comparativo auditable como :class:`ProvisionOrchestrationResult` usando los DTOs de
:mod:`nikodym.provisioning.results`; **no** recalcula PI/PDI/PE, ECL ni el método interno.

Correctitud crítica (SDD-17 §3): los montos se agregan desde ``detail``/``records``, **nunca** desde
``summary``. El ``summary`` del ECL IFRS 9 está desglosado **por escenario**, de modo que sumarlo
duplicaría la masa; ``detail``/``ecl_records`` ya vienen colapsados por escenario (``Σ_k w_k``). A
nivel ``total`` se usa el total de la card de cada fuente (ya colapsado).

El módulo **no importa** los paquetes de motores como código (solo referencia sus DTOs bajo
``TYPE_CHECKING``) ni ``pandas`` en top-level: ``pandas`` se resuelve perezosamente dentro de
``compare`` para preservar el núcleo liviano. El motor es **determinista** (sin RNG); normaliza
``-0.0 → 0.0`` y jamás publica ``NaN``/``inf``.

**Experimental (fuera de la garantía SemVer 1.x).**
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
from nikodym.provisioning.config import (
    CMF_SOURCE,
    IFRS9_SOURCE,
    INTERNAL_SOURCE,
    SOURCE_NAMES,
    ProvisioningComparisonLevel,
    ProvisioningConfig,
    ProvisioningSource,
)
from nikodym.provisioning.exceptions import (
    ProvisioningAlignmentError,
    ProvisioningConfigError,
    ProvisioningCoverageError,
    ProvisioningInputError,
)
from nikodym.provisioning.results import (
    ProvisionAmount,
    ProvisionBinding,
    ProvisionComparisonRecord,
    ProvisionComparisonSummary,
    ProvisionCoverage,
    ProvisionOrchestrationCard,
    ProvisionOrchestrationResult,
)

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any

# Los resultados de las fuentes entran como artefactos opacos del ``ArtifactStore``: el orquestador
# valida su estructura por acceso (``card``/``detail``/``records``), sin importar los motores.
SourceResult: TypeAlias = Any

__all__ = ["ProvisioningOrchestrator"]

_PROV_EXTRA_MESSAGE = "ProvisioningOrchestrator requiere pandas; instale las dependencias base."
_TOTAL_CELL_ID = "TOTAL"

# Fuentes normativas de cada regla. La regla del máximo NO es "el piso prudencial de la CMF" entre
# CMF e IFRS 9 (eso era una cita circular a un markdown interno): es estándar vs. interno, y está en
# el Compendio. Cuando la comparación no es la que la norma exige, se dice explícitamente.
_B1_MAX_RULE_SOURCE = (
    "CNC (CMF) Cap. B-1, hoja 10-11 (Circular N° 2.346): la constitución de provisiones considera "
    "el mayor valor obtenido entre el método estándar y el método interno, por cada institución en "
    "Chile que consolida con el banco. Nikodym supone una institución por corrida y no valida ese "
    "perímetro."
)
_B1_INTERNAL_RULE_SOURCE = (
    "CNC (CMF) Cap. B-1, hoja 10-11 (Circular N° 2.346): con métodos internos evaluados y no "
    "objetados, la constitución de provisiones se efectúa de acuerdo con los resultados de su "
    "aplicación (el método interno, no el máximo). La institución debe acreditar la evaluación/no "
    "objeción; Nikodym no la verifica."
)
_B1_DIAGNOSTIC_RULE_SOURCE = (
    "Comparativo diagnóstico SIN binding B-1: aunque las fuentes sean método estándar CMF e "
    "interno, los niveles portfolio/segment/operation no representan la regla por institución."
)
_CROSS_FRAMEWORK_RULE_SOURCE = (
    "Comparativo entre marcos contables SIN norma chilena que lo exija: el Cap. A-2 num. 5 del CNC "
    "excluye el deterioro (NIIF 9 §5.5) sobre las colocaciones y los créditos contingentes, cuyos "
    "criterios fija la CMF en los Cap. B-1 a B-3."
)

# Etiquetas legibles de cada fuente para los mensajes de error.
_SOURCE_LABELS: dict[str, str] = {
    CMF_SOURCE: "CMF",
    INTERNAL_SOURCE: "método interno",
    IFRS9_SOURCE: "IFRS 9",
}
# Fuentes cuyo dominio numérico es ``Decimal`` (exactitud regulatoria); IFRS 9 publica ``float``.
_DECIMAL_SOURCES: frozenset[str] = frozenset({CMF_SOURCE, INTERNAL_SOURCE})
# Atributo de la card con el total de la fuente y columna de monto de su ``detail``.
_TOTAL_ATTRS: dict[str, str] = {
    CMF_SOURCE: "total_provision_amount",
    INTERNAL_SOURCE: "total_internal_provision",
    IFRS9_SOURCE: "total_ecl_reported",
}
_AMOUNT_COLUMNS: dict[str, str] = {
    CMF_SOURCE: "provision_amount",
    INTERNAL_SOURCE: "provision_amount",
    IFRS9_SOURCE: "ecl_reported",
}

_COMPARISON_COLUMNS: tuple[str, ...] = (
    "cell_id",
    "level",
    "source_a",
    "source_b",
    "provision_a",
    "provision_b",
    "reported_provision",
    "binding",
    "coverage",
    "warning_codes",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "level",
    "source_a",
    "source_b",
    "n_cells",
    "n_binding_a",
    "n_binding_b",
    "n_binding_tie",
    "total_provision_a",
    "total_provision_b",
    "total_reported_provision",
    "warning_codes",
)

# Códigos de warning por celda (comparativo) y notas FALTA-DATO (card).
_WARN_COMPARISON_INCOMPLETE = "comparacion_incompleta"
_WARN_FLOOR_INCOMPLETE_LEGACY = "piso_incompleto"
_WARN_IMPUTED_ZERO = "cobertura_imputada_cero"


class ProvisioningOrchestrator:
    """Compara dos fuentes de provisión y aplica la regla declarada por celda (SDD-17 §6/§7)."""

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
        result_a: SourceResult | None,
        result_b: SourceResult | None,
        as_of_date: str,
        audit: AuditSink | None = None,
    ) -> ProvisionOrchestrationResult:
        """Aplica la regla (``max`` / ``use_internal``) por celda, determinista.

        ``result_a`` y ``result_b`` son los resultados publicados por ``cfg.source_a`` y
        ``cfg.source_b`` respectivamente (posicionales por ranura, no por motor).
        """
        pd_module: Any = _import_pandas()
        cfg = self.config
        as_of = _require_as_of_date(as_of_date)
        source_a, source_b = cfg.sources
        name_a, name_b = SOURCE_NAMES[source_a], SOURCE_NAMES[source_b]

        engine_a = result_a if cfg.consume_source_a else None
        engine_b = result_b if cfg.consume_source_b else None
        if engine_a is None and engine_b is None:
            raise ProvisioningInputError(
                "La orquestación de provisiones requiere al menos un motor "
                f"({_SOURCE_LABELS[source_a]} o {_SOURCE_LABELS[source_b]}); ninguno está "
                "presente/habilitado."
            )
        if cfg.require_both and not (engine_a is not None and engine_b is not None):
            faltante = source_b if engine_a is not None else source_a
            raise ProvisioningInputError(
                "require_both=True exige ambas fuentes; falta el resultado de "
                f"{_SOURCE_LABELS[faltante]} (la regla presupone las dos)."
            )

        both_engines = engine_a is not None and engine_b is not None
        engines_present: tuple[str, ...] = tuple(
            name
            for name, present in ((name_a, engine_a is not None), (name_b, engine_b is not None))
            if present
        )

        cells_a: dict[str, ProvisionAmount] = (
            _source_cells(engine_a, source=source_a, cfg=cfg) if engine_a is not None else {}
        )
        cells_b: dict[str, ProvisionAmount] = (
            _source_cells(engine_b, source=source_b, cfg=cfg) if engine_b is not None else {}
        )
        if cfg.comparison_level == "portfolio" and cfg.portfolio_crosswalk:
            cells_a = _apply_crosswalk(cells_a, cfg.portfolio_crosswalk)
        if cfg.comparison_level == "operation" and both_engines:
            _check_operation_alignment(cells_a, cells_b, source_a=source_a, source_b=source_b)

        falta_dato: list[str] = []
        if not both_engines:
            presente = name_a if engine_a is not None else name_b
            falta_dato.append(
                f"FALTA-DATO-PROV-3: comparación incompleta; solo el motor {presente} está "
                "presente "
                "(require_both=False)."
            )

        records = [
            _build_record(
                cell_id,
                cells_a.get(cell_id),
                cells_b.get(cell_id),
                cfg=cfg,
                sources=(source_a, source_b),
                both_engines=both_engines,
                falta_dato=falta_dato,
            )
            for cell_id in _ordered_cell_ids(cells_a, cells_b)
        ]

        summary_dto = _build_summary(
            records, level=cfg.comparison_level, name_a=name_a, name_b=name_b
        )
        card = ProvisionOrchestrationCard(
            as_of_date=as_of,
            comparison_level=cfg.comparison_level,
            rule=cfg.rule,
            source_a=name_a,
            source_b=name_b,
            engines_present=engines_present,
            binding=records[0].binding if len(records) == 1 else None,
            n_cells=summary_dto.n_cells,
            n_binding_a=summary_dto.n_binding_a,
            n_binding_b=summary_dto.n_binding_b,
            n_binding_tie=summary_dto.n_binding_tie,
            total_provision_a=summary_dto.total_provision_a,
            total_provision_b=summary_dto.total_provision_b,
            total_reported_provision=summary_dto.total_reported_provision,
            cmf_matrix_version=_card_attr(
                engine_a, engine_b, cfg=cfg, source=CMF_SOURCE, attr="matrix_version"
            ),
            ifrs9_term_structure_source=_card_attr(
                engine_a, engine_b, cfg=cfg, source=IFRS9_SOURCE, attr="term_structure_source"
            ),
            internal_method=_card_attr(
                engine_a, engine_b, cfg=cfg, source=INTERNAL_SOURCE, attr="method"
            ),
            regulatory_sources=_regulatory_sources(engine_a, engine_b, cfg=cfg),
            falta_dato=tuple(dict.fromkeys(falta_dato)),
            metric_sections=_metric_sections(cfg, records, name_a=name_a, name_b=name_b),
        )

        ifrs9_engine = _engine_for(engine_a, engine_b, cfg=cfg, source=IFRS9_SOURCE)
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
    """Valida que la fecha de cálculo heredada de las fuentes no esté vacía."""
    if not as_of_date.strip():
        raise ProvisioningInputError("compare requiere as_of_date no vacío.")
    return as_of_date


def _engine_for(
    engine_a: SourceResult | None,
    engine_b: SourceResult | None,
    *,
    cfg: ProvisioningConfig,
    source: ProvisioningSource,
) -> SourceResult | None:
    """Devuelve el resultado de la ranura que ocupa ``source``, o ``None`` si no participa."""
    if cfg.source_a == source:
        return engine_a
    if cfg.source_b == source:
        return engine_b
    return None


def _card_attr(
    engine_a: SourceResult | None,
    engine_b: SourceResult | None,
    *,
    cfg: ProvisioningConfig,
    source: ProvisioningSource,
    attr: str,
) -> str | None:
    """Lee un atributo de procedencia de la card de ``source`` si esa fuente participa."""
    engine = _engine_for(engine_a, engine_b, cfg=cfg, source=source)
    if engine is None:
        return None
    return cast(str, getattr(engine.card, attr))


def _source_cells(
    result: SourceResult, *, source: ProvisioningSource, cfg: ProvisioningConfig
) -> dict[str, ProvisionAmount]:
    """Agrega los montos de una fuente a las celdas del nivel declarado, en su propio dominio.

    Nunca lee ``summary``: el del ECL IFRS 9 está desglosado por escenario y duplicaría la masa
    (SDD-17 §3). El total sale de la card (ya colapsado) y el resto de ``detail``/``records``.
    """
    level = cfg.comparison_level
    es_decimal = source in _DECIMAL_SOURCES
    if level == "total":
        total = getattr(result.card, _TOTAL_ATTRS[source])
        return {_TOTAL_CELL_ID: _to_decimal(total) if es_decimal else _to_float(total)}
    if level == "operation":
        return _operation_cells(result, source=source, es_decimal=es_decimal)
    return _grouped_cells(result, source=source, cfg=cfg, es_decimal=es_decimal)


def _operation_cells(
    result: SourceResult, *, source: ProvisioningSource, es_decimal: bool
) -> dict[str, ProvisionAmount]:
    """Agrega por operación desde los ``records`` de la fuente (una fila por ``row_id``)."""
    label = _SOURCE_LABELS[source]
    registros = result.ecl_records if source == IFRS9_SOURCE else result.records
    atributo = "ecl_reported" if source == IFRS9_SOURCE else "provision_amount"
    cells: dict[str, ProvisionAmount] = {}
    for record in registros:
        key = str(record.row_id)
        if key in cells:
            raise ProvisioningInputError(
                f"comparison_level='operation': row_id {label} duplicado {key!r} en los registros."
            )
        monto = getattr(record, atributo)
        cells[key] = _to_decimal(monto) if es_decimal else _to_float(monto)
    return cells


def _grouped_cells(
    result: SourceResult, *, source: ProvisioningSource, cfg: ProvisioningConfig, es_decimal: bool
) -> dict[str, ProvisionAmount]:
    """Agrega por cartera o segmento desde el ``detail`` de la fuente."""
    column = _level_column(cfg, source=source)
    detail: Any = result.detail
    if column not in detail.columns:
        raise _missing_column_error(cfg.comparison_level, column, source=source)
    amount_column = _AMOUNT_COLUMNS[source]
    if es_decimal:
        grouped: dict[str, ProvisionAmount] = {}
        for key_value, monto in zip(
            detail[column].tolist(), detail[amount_column].tolist(), strict=True
        ):
            key = str(key_value)
            previo = cast(Decimal, grouped.get(key, Decimal("0")))
            grouped[key] = previo + _to_decimal(monto)
        return grouped
    acumulado: dict[str, list[float]] = {}
    for key_value, monto in zip(
        detail[column].tolist(), detail[amount_column].tolist(), strict=True
    ):
        acumulado.setdefault(str(key_value), []).append(_to_float(monto))
    return {key: math.fsum(values) for key, values in acumulado.items()}


def _level_column(cfg: ProvisioningConfig, *, source: ProvisioningSource) -> str:
    """Resuelve la columna de agrupación (cartera o segmento) de la fuente para el nivel actual."""
    if cfg.comparison_level == "portfolio":
        return cfg.portfolio_col_for(source)
    # segment: columna única provista por el usuario (config garantiza que no es None).
    assert cfg.segment_col is not None
    return cfg.segment_col


def _missing_column_error(
    level: ProvisioningComparisonLevel, column: str, *, source: ProvisioningSource
) -> ProvisioningConfigError | ProvisioningAlignmentError:
    """Construye el error por columna de agrupación ausente en el detalle de la fuente."""
    label = _SOURCE_LABELS[source]
    if level == "segment":
        return ProvisioningConfigError(
            f"comparison_level='segment' exige que segment_col={column!r} exista en el detalle "
            f"{label}; no está presente."
        )
    return ProvisioningAlignmentError(
        f"comparison_level='portfolio': la columna de cartera {column!r} no está en el detalle "
        f"{label}; las taxonomías no son reconciliables."
    )


def _apply_crosswalk(
    cells: dict[str, ProvisionAmount], crosswalk: dict[str, str]
) -> dict[str, ProvisionAmount]:
    """Remapea las carteras de la fuente A a la taxonomía de la fuente B, sumando colisiones."""
    remapped: dict[str, ProvisionAmount] = {}
    for key, value in cells.items():
        mapped = crosswalk.get(key, key)
        previo = remapped.get(mapped)
        if previo is None:
            remapped[mapped] = value
        elif isinstance(previo, Decimal) and isinstance(value, Decimal):
            remapped[mapped] = previo + value
        else:
            remapped[mapped] = math.fsum((float(previo), float(value)))
    return remapped


def _check_operation_alignment(
    cells_a: dict[str, ProvisionAmount],
    cells_b: dict[str, ProvisionAmount],
    *,
    source_a: ProvisioningSource,
    source_b: ProvisioningSource,
) -> None:
    """Exige perímetros de operación reconciliables entre ambas fuentes (SDD-17 §6 caveat)."""
    if set(cells_a) != set(cells_b):
        solo_a = sorted(set(cells_a) - set(cells_b))
        solo_b = sorted(set(cells_b) - set(cells_a))
        raise ProvisioningAlignmentError(
            "comparison_level='operation': los perímetros de operación no son reconciliables; "
            f"solo-{_SOURCE_LABELS[source_a]}={solo_a!r}, "
            f"solo-{_SOURCE_LABELS[source_b]}={solo_b!r}."
        )


def _ordered_cell_ids(
    cells_a: dict[str, ProvisionAmount], cells_b: dict[str, ProvisionAmount]
) -> tuple[str, ...]:
    """Devuelve las celdas en orden canónico estable (unión ordenada de claves)."""
    return tuple(sorted(set(cells_a) | set(cells_b)))


def _zero_for(source: ProvisioningSource) -> ProvisionAmount:
    """Cero en el dominio numérico de la fuente (``Decimal`` o ``float``)."""
    return Decimal("0") if source in _DECIMAL_SOURCES else 0.0


def _build_record(
    cell_id: str,
    val_a: ProvisionAmount | None,
    val_b: ProvisionAmount | None,
    *,
    cfg: ProvisioningConfig,
    sources: tuple[ProvisioningSource, ProvisioningSource],
    both_engines: bool,
    falta_dato: list[str],
) -> ProvisionComparisonRecord:
    """Construye el registro de una celda aplicando la regla, el binding y la cobertura."""
    source_a, source_b = sources
    name_a, name_b = SOURCE_NAMES[source_a], SOURCE_NAMES[source_b]
    if val_a is not None and val_b is not None:
        return _both_record(cell_id, val_a=val_a, val_b=val_b, cfg=cfg, sources=sources)

    faltante = source_b if val_a is not None else source_a
    if not both_engines:
        return _only_record(
            cell_id,
            val_a=val_a,
            val_b=val_b,
            cfg=cfg,
            sources=sources,
            # ``piso_incompleto`` se conserva como alias legacy por el contrato aditivo CT-2.
            warnings=(_WARN_COMPARISON_INCOMPLETE, _WARN_FLOOR_INCOMPLETE_LEGACY),
        )
    if cfg.coverage_policy == "fail":
        cubierta = _SOURCE_LABELS[source_a] if val_a is not None else _SOURCE_LABELS[source_b]
        raise ProvisioningCoverageError(
            f"comparison_level={cfg.comparison_level!r}: la celda {cell_id!r} está cubierta solo "
            f"por {cubierta}; coverage_policy='fail'."
        )
    if cfg.coverage_policy == "treat_missing_as_zero":
        falta_dato.append(
            f"FALTA-DATO-PROV: celda {cell_id!r} imputó 0 al motor {SOURCE_NAMES[faltante]} "
            "(treat_missing_as_zero)."
        )
        return _both_record(
            cell_id,
            val_a=val_a if val_a is not None else _zero_for(source_a),
            val_b=val_b if val_b is not None else _zero_for(source_b),
            cfg=cfg,
            sources=sources,
            warnings=(_WARN_IMPUTED_ZERO,),
        )
    falta_dato.append(
        f"FALTA-DATO-PROV-1: celda {cell_id!r} sin contraparte {SOURCE_NAMES[faltante]}."
    )
    ausente = name_b if val_a is not None else name_a
    return _only_record(
        cell_id,
        val_a=val_a,
        val_b=val_b,
        cfg=cfg,
        sources=sources,
        warnings=(f"{ausente}_ausente",),
    )


def _both_record(
    cell_id: str,
    *,
    val_a: ProvisionAmount,
    val_b: ProvisionAmount,
    cfg: ProvisioningConfig,
    sources: tuple[ProvisioningSource, ProvisioningSource],
    warnings: tuple[str, ...] = (),
) -> ProvisionComparisonRecord:
    """Construye un registro con cobertura ``both``: reconcilia y aplica la regla con binding."""
    name_a, name_b = SOURCE_NAMES[sources[0]], SOURCE_NAMES[sources[1]]
    reported, binding = _apply_rule(val_a, val_b, cfg=cfg, name_a=name_a, name_b=name_b)
    return ProvisionComparisonRecord(
        cell_id=cell_id,
        level=cfg.comparison_level,
        source_a=name_a,
        source_b=name_b,
        provision_a=val_a,
        provision_b=val_b,
        reported_provision=_apply_rounding(reported, cfg.rounding),
        binding=binding,
        coverage="both",
        warnings=warnings,
    )


def _only_record(
    cell_id: str,
    *,
    val_a: ProvisionAmount | None,
    val_b: ProvisionAmount | None,
    cfg: ProvisioningConfig,
    sources: tuple[ProvisioningSource, ProvisioningSource],
    warnings: tuple[str, ...],
) -> ProvisionComparisonRecord:
    """Construye un registro de cobertura parcial (``<fuente>_only``) con la fuente disponible."""
    name_a, name_b = SOURCE_NAMES[sources[0]], SOURCE_NAMES[sources[1]]
    presente = name_a if val_a is not None else name_b
    disponible = val_a if val_a is not None else val_b
    assert disponible is not None
    binding = cast(ProvisionBinding, f"{presente}_only")
    return ProvisionComparisonRecord(
        cell_id=cell_id,
        level=cfg.comparison_level,
        source_a=name_a,
        source_b=name_b,
        provision_a=val_a,
        provision_b=val_b,
        reported_provision=_apply_rounding(_as_decimal(disponible), cfg.rounding),
        binding=binding,
        coverage=cast(ProvisionCoverage, f"{presente}_only"),
        warnings=warnings,
    )


def _as_decimal(value: ProvisionAmount) -> Decimal:
    """Vista ``Decimal`` del monto (dominio de reporte), sin destruir el original de la fuente."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _as_float(value: ProvisionAmount) -> float:
    """Vista ``float`` del monto (dominio económico) para comparar entre dominios distintos."""
    return float(value)


def _apply_rule(
    val_a: ProvisionAmount,
    val_b: ProvisionAmount,
    *,
    cfg: ProvisioningConfig,
    name_a: str,
    name_b: str,
) -> tuple[Decimal, ProvisionBinding]:
    """Aplica la regla declarada y devuelve ``(reportado, fuente vinculante)``.

    ``use_internal``: manda el método interno aunque el estándar sea mayor (B-1, hoja 10-11). El
    config garantiza que el método interno es una de las fuentes.
    ``max``: reconcilia ``Decimal`` y ``float`` preservando los originales y toma el mayor; el
    empate se declara con ``tie_tolerance`` sobre la diferencia en el dominio económico.
    """
    if cfg.rule == "use_internal":
        interno = val_a if cfg.source_a == INTERNAL_SOURCE else val_b
        return _as_decimal(interno), cast(ProvisionBinding, SOURCE_NAMES[INTERNAL_SOURCE])

    float_a, float_b = _as_float(val_a), _as_float(val_b)
    diff = float_a - float_b
    if cfg.numeric_reconciliation == "decimal_quantize":
        dec_a, dec_b = _as_decimal(val_a), _as_decimal(val_b)
        reported = dec_a if dec_a >= dec_b else dec_b
    else:
        reported = Decimal(str(float_a if float_a >= float_b else float_b))
    binding: ProvisionBinding
    if abs(diff) <= cfg.tie_tolerance:
        binding = "tie"
    elif diff > 0:
        binding = cast(ProvisionBinding, name_a)
    else:
        binding = cast(ProvisionBinding, name_b)
    return reported, binding


def _apply_rounding(value: Decimal, rounding: str) -> Decimal:
    """Aplica el redondeo contable explícito de la provisión reportada (default ``none``)."""
    if rounding == "none":
        return value
    quantum = Decimal("0.01") if rounding == "currency_2dp" else Decimal("1")
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _total(amounts: list[ProvisionAmount]) -> Decimal:
    """Suma los montos de una fuente en su dominio (``fsum`` en float; exacta en ``Decimal``)."""
    if any(isinstance(amount, float) for amount in amounts):
        return Decimal(str(math.fsum(_as_float(amount) for amount in amounts)))
    return sum((cast(Decimal, amount) for amount in amounts), Decimal("0"))


def _build_summary(
    records: list[ProvisionComparisonRecord],
    *,
    level: ProvisioningComparisonLevel,
    name_a: str,
    name_b: str,
) -> ProvisionComparisonSummary:
    """Agrega los registros al resumen por nivel (totales ``Decimal`` y conteos por binding)."""
    amounts_a: list[ProvisionAmount] = []
    amounts_b: list[ProvisionAmount] = []
    reported_amounts: list[Decimal] = []
    warn_seen: list[str] = []
    n_a = n_b = n_tie = 0
    for record in records:
        if record.provision_a is not None:
            amounts_a.append(record.provision_a)
        if record.provision_b is not None:
            amounts_b.append(record.provision_b)
        reported_amounts.append(record.reported_provision)
        warn_seen.extend(record.warnings)
        if record.binding == name_a:
            n_a += 1
        elif record.binding == name_b:
            n_b += 1
        elif record.binding == "tie":
            n_tie += 1
    return ProvisionComparisonSummary(
        level=level,
        source_a=name_a,
        source_b=name_b,
        n_cells=len(records),
        n_binding_a=n_a,
        n_binding_b=n_b,
        n_binding_tie=n_tie,
        total_provision_a=_total(amounts_a),
        total_provision_b=_total(amounts_b),
        total_reported_provision=sum(reported_amounts, Decimal("0")),
        warnings=tuple(dict.fromkeys(warn_seen)),
    )


def _regulatory_sources(
    engine_a: SourceResult | None, engine_b: SourceResult | None, *, cfg: ProvisioningConfig
) -> tuple[str, ...]:
    """Compone las fuentes regulatorias: la de la regla aplicada más las heredadas del CMF."""
    sources: list[str] = [_rule_source(cfg)]
    cmf = _engine_for(engine_a, engine_b, cfg=cfg, source=CMF_SOURCE)
    if cmf is not None:
        sources.extend(cmf.card.regulatory_sources)
    return tuple(dict.fromkeys(sources))


def _rule_source(cfg: ProvisioningConfig) -> str:
    """Cita B-1 sólo para estándar/interno a nivel total; los demás casos son diagnósticos."""
    is_standard_internal = set(cfg.sources) == {CMF_SOURCE, INTERNAL_SOURCE}
    is_b1_binding = is_standard_internal and cfg.comparison_level == "total"
    if is_b1_binding and cfg.rule == "use_internal":
        return _B1_INTERNAL_RULE_SOURCE
    if is_b1_binding:
        return _B1_MAX_RULE_SOURCE
    if is_standard_internal:
        return _B1_DIAGNOSTIC_RULE_SOURCE
    return _CROSS_FRAMEWORK_RULE_SOURCE


def _metric_sections(
    cfg: ProvisioningConfig,
    records: list[ProvisionComparisonRecord],
    *,
    name_a: str,
    name_b: str,
) -> dict[str, Any]:
    """Construye el payload CT-2 aditivo (regla, fuentes, nivel y binding de fuente A)."""
    counts = {
        name_a: sum(1 for r in records if r.binding == name_a),
        name_b: sum(1 for r in records if r.binding == name_b),
        "tie": sum(1 for r in records if r.binding == "tie"),
        f"{name_a}_only": sum(1 for r in records if r.binding == f"{name_a}_only"),
        f"{name_b}_only": sum(1 for r in records if r.binding == f"{name_b}_only"),
    }
    binding_ratio = _source_a_binding_ratio(counts[name_a], len(records))
    return {
        "provisioning_orchestration": {
            "rule": cfg.rule,
            "source_a": name_a,
            "source_b": name_b,
            "comparison_level": cfg.comparison_level,
            "numeric_reconciliation": cfg.numeric_reconciliation,
            "tie_tolerance": cfg.tie_tolerance,
            "rounding": cfg.rounding,
            "source_a_binding_ratio": binding_ratio,
            # Alias legacy preservado por CT-2; semánticamente equivale a source_a_binding_ratio.
            "floor_bite_ratio": binding_ratio,
            "binding_counts": counts,
        }
    }


def _source_a_binding_ratio(n_binding_a: int, n_cells: int) -> float | None:
    """Fracción de celdas vinculadas por la fuente A; ``None`` cuando no hay celdas.

    Es un diagnóstico neutral: la fuente A puede ser CMF, interna o IFRS 9. En nivel ``total`` sólo
    puede valer 0 o 1.
    """
    if n_cells == 0:
        return None
    return n_binding_a / n_cells


def _comparison_frame(records: list[ProvisionComparisonRecord], pd_module: Any) -> DataFrame:
    """Materializa el comparativo por celda con las columnas canónicas SDD-17 §6."""
    data = {
        "cell_id": [record.cell_id for record in records],
        "level": [record.level for record in records],
        "source_a": [record.source_a for record in records],
        "source_b": [record.source_b for record in records],
        "provision_a": [record.provision_a for record in records],
        "provision_b": [record.provision_b for record in records],
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
        "source_a": [summary.source_a],
        "source_b": [summary.source_b],
        "n_cells": [summary.n_cells],
        "n_binding_a": [summary.n_binding_a],
        "n_binding_b": [summary.n_binding_b],
        "n_binding_tie": [summary.n_binding_tie],
        "total_provision_a": [summary.total_provision_a],
        "total_provision_b": [summary.total_provision_b],
        "total_reported_provision": [summary.total_reported_provision],
        "warning_codes": [summary.warnings],
    }
    return cast(DataFrame, pd_module.DataFrame(data, columns=list(_SUMMARY_COLUMNS)))


def _to_decimal(value: Any) -> Decimal:
    """Normaliza un monto de dominio exacto a ``Decimal`` finito y no negativo (§8)."""
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool) or not isinstance(value, Real):
        raise ProvisioningInputError(f"Monto no numérico (se esperaba Decimal): {value!r}.")
    else:
        result = Decimal(str(value))
    if not result.is_finite():
        raise ProvisioningInputError(f"Monto no finito (NaN/inf): {value!r}.")
    if result < 0:
        raise ProvisioningInputError(f"Monto negativo no permitido: {value!r}.")
    return result


def _to_float(value: Any) -> float:
    """Normaliza un monto de dominio económico a ``float`` finito y no negativo (§8)."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ProvisioningInputError(f"Monto no numérico (se esperaba float): {value!r}.")
    result = float(value)
    if not math.isfinite(result):
        raise ProvisioningInputError(f"Monto no finito (NaN/inf): {value!r}.")
    if result < 0:
        raise ProvisioningInputError(f"Monto negativo no permitido: {value!r}.")
    return result


def _emit_audit(
    audit: AuditSink | None,
    *,
    cfg: ProvisioningConfig,
    card: ProvisionOrchestrationCard,
    engines: tuple[str, ...],
) -> None:
    """Registra las decisiones auditables de la orquestación si se inyectó un sink (SDD-17 §9)."""
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
            {
                "engines_present": list(engines),
                "source_a": card.source_a,
                "source_b": card.source_b,
            },
            "determinar_fuentes_presentes",
        ),
        (
            "provisioning_reconciliation",
            {"numeric_reconciliation": cfg.numeric_reconciliation, "rounding": cfg.rounding},
            {"tie_tolerance": cfg.tie_tolerance},
            "reconciliar_dominios_numericos",
        ),
        (
            "provisioning_binding",
            {"rule": cfg.rule, "comparison_level": cfg.comparison_level},
            {
                "n_binding_a": card.n_binding_a,
                "n_binding_b": card.n_binding_b,
                "n_binding_tie": card.n_binding_tie,
                "binding": card.binding,
                "regulatory_sources": list(card.regulatory_sources),
            },
            # Token legacy preservado para consumidores de audit; el payload ya declara fuentes y
            # regla, por lo que no atribuye carácter normativo a comparativos entre marcos.
            "aplicar_regla_de_constitucion",
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
