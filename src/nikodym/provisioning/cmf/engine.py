"""Motor base de provisiones regulatorias CMF B-1 (SDD-15 §4/§7).

``CmfProvisioningEngine`` calcula provisiones deterministas sobre exposiciones directas,
contingentes B-3, sustitución proporcional por avales y guardrails de garantías financieras usando
las matrices versionadas de ``provisioning.cmf``.

El módulo mantiene import liviano: ``pandas`` y ``Decimal`` se resuelven bajo demanda dentro de
``calculate``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias, cast

from pydantic import ValidationError

from nikodym.core.audit import AuditEvent
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.provisioning.cmf.config import CmfProvisioningConfig
from nikodym.provisioning.cmf.exceptions import (
    CmfCalculationError,
    CmfInputError,
    CmfMappingError,
    CmfMatrixError,
    CmfMissingRegulatoryDataError,
    CmfProvisioningError,
)
from nikodym.provisioning.cmf.matrices import (
    CmfMatrixBundle,
    CmfMatrixRow,
    load_cmf_matrices,
)
from nikodym.provisioning.cmf.results import (
    CmfPortfolioSummary,
    CmfProvisionCard,
    CmfProvisionRecord,
    CmfProvisionResult,
)

if TYPE_CHECKING:
    from decimal import Decimal

    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["CmfProvisioningEngine"]

_CMF_EXTRA_MESSAGE = "CmfProvisioningEngine requiere pandas; instale las dependencias base."
_PE_CONSISTENCY_TOLERANCE_PERCENT = "0.0001"
_HUNDRED = "100"
_ZERO = "0"
_DETAIL_COLUMNS: tuple[str, ...] = (
    "portfolio",
    "method",
    "cmf_category",
    "matrix_id",
    "matrix_row_id",
    "direct_exposure_amount",
    "contingent_exposure_amount",
    "exposure_amount",
    "pd_source_value",
    "pi_percent",
    "pdi_percent",
    "pe_percent",
    "provision_amount",
    "guarantee_treatment",
    "ccf_percent",
    "warning_codes",
    "source_reference",
    "matrix_version",
)
_SUMMARY_COLUMNS: tuple[str, ...] = (
    "portfolio",
    "method",
    "cmf_category",
    "n_rows",
    "total_exposure_amount",
    "total_provision_amount",
    "weighted_pe_percent",
    "matrix_version",
    "warning_codes",
)
_PORTFOLIO_ORDER: tuple[str, ...] = (
    "commercial_individual",
    "commercial_group_leasing",
    "commercial_group_student",
    "commercial_group_generic_factoring",
    "consumer",
    "housing",
)
_INDIVIDUAL_PERFORMING_MATRIX = "commercial_individual_performing_v2014"
_INDIVIDUAL_DEFAULT_MATRIX = "commercial_individual_default_v2014"
_LEASING_MATRIX = "commercial_group_leasing_v2018"
_STUDENT_MATRIX = "commercial_group_student_v2018"
_GENERIC_MATRIX = "commercial_group_generic_factoring_v2020"
_CONSUMER_MATRIX = "consumer_standard_v2025"
_HOUSING_MATRIX = "housing_pvg_v2018"
_GUARANTEE_SUBSTITUTION_MATRIX = "commercial_group_guarantee_substitution_v2018"
_GUARANTEE_AVAL_MATRIX = "guarantee_aval_quality_v2018"
_CONTINGENT_MATRIX = "contingent_b3_v2016"
_AVAL_COVERAGE_COL = "aval_coverage_pct"
_AVAL_RATING_SCALE_COL = "aval_rating_scale"
_AVAL_RATING_CATEGORY_COL = "aval_rating_category"
_CONTINGENT_SUBTYPE_COL = "contingent_subtype"
_FINANCIAL_GUARANTEE_AMOUNT_COLS = (
    "financial_guarantee_amount",
    "financial_guarantee_value",
    "financial_guarantee_fair_value",
)
_FINANCIAL_GUARANTEE_FLAG_COLS = (
    "financial_guarantee_requires_haircut",
    "requires_financial_guarantee_haircut",
)
_FINANCIAL_GUARANTEE_TYPE_COLS = (
    "guarantee_type",
    "guarantee_kind",
    "guarantee_class",
    "financial_guarantee_type",
)
_FINANCIAL_GUARANTEE_TYPE_VALUES = frozenset(
    {"financial", "financial_guarantee", "garantia_financiera", "garantía_financiera"}
)
_CATEGORIES_ORDER: tuple[str, ...] = (
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "B1",
    "B2",
    "B3",
    "B4",
    "C1",
    "C2",
    "C3",
    "C4",
    "C5",
    "C6",
)
_PRODUCT_ALIASES: Mapping[str, str] = {
    "creditos_en_cuotas": "installment_loans",
    "installment_loans": "installment_loans",
    "tarjetas_lineas_otros": "cards_lines_other",
    "cards_lines_other": "cards_lines_other",
    "leasing_auto": "leasing_auto",
}
_BOOLEAN_YES = frozenset({"1", "true", "t", "yes", "y", "si", "sí"})
_BOOLEAN_NO = frozenset({"0", "false", "f", "no", "n"})


class CmfProvisioningEngine:
    """Calcula provisiones CMF B-1/B-3 con garantías verificadas o fail-fast."""

    config_cls: ClassVar[type[CmfProvisioningConfig]] = CmfProvisioningConfig

    def __init__(self, config: CmfProvisioningConfig, *, matrices: CmfMatrixBundle) -> None:
        """Recibe config validado y bundle normativo ya cargado."""
        self.config = config
        self.matrices = matrices

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> CmfProvisioningEngine:
        """Construye el motor y carga las matrices CMF activas por config."""
        if not isinstance(cfg, CmfProvisioningConfig):
            cfg = CmfProvisioningConfig.model_validate(cfg)
        return cls(cfg, matrices=load_cmf_matrices(cfg.matrices))

    def calculate(
        self,
        frame: DataFrame,
        *,
        pd_frame: DataFrame | None = None,
        as_of_date: str,
        audit: AuditSink | None = None,
    ) -> CmfProvisionResult:
        """Calcula detalle, resumen y card CMF preservando orden e índice del input."""
        from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

        pd = _import_pandas()
        decimal = DecimalRuntime(
            decimal_cls=Decimal,
            invalid_operation_cls=InvalidOperation,
            rounding_half_up=ROUND_HALF_UP,
            zero=Decimal(_ZERO),
            hundred=Decimal(_HUNDRED),
            pe_tolerance=Decimal(_PE_CONSISTENCY_TOLERANCE_PERCENT),
        )
        cfg = _validate_runtime_config(self.config)
        data = _as_dataframe(frame, pd=pd)
        _validate_base_contract(data, cfg=cfg)
        pd_categories = _resolve_pd_categories(
            cfg,
            data,
            pd_frame=pd_frame,
            pd=pd,
            decimal=decimal,
        )
        consumer_states = _consumer_states(data, cfg=cfg, pd=pd, decimal=decimal)

        records: list[CmfProvisionRecord] = []
        detail_rows: list[dict[str, object]] = []
        detail_index: list[object] = []
        for row_id, row in data.iterrows():
            context = RowContext(
                row_id=row_id,
                row=row,
                pd_category=pd_categories.get(row_id),
                consumer_state=consumer_states.get(row_id),
            )
            exposure = _resolve_exposure(
                context,
                cfg=cfg,
                bundle=self.matrices,
                decimal=decimal,
                pd=pd,
            )
            _enforce_financial_guarantee_policy(
                context,
                exposure=exposure,
                cfg=cfg,
                decimal=decimal,
                pd=pd,
                matrix_version=self.matrices.manifest.version,
            )
            resolved = _resolve_provision(
                context,
                exposure=exposure.exposure_amount,
                cfg=cfg,
                bundle=self.matrices,
                decimal=decimal,
                pd=pd,
            )
            resolved = _apply_guarantee_substitution(
                context,
                resolution=resolved,
                exposure=exposure.exposure_amount,
                cfg=cfg,
                bundle=self.matrices,
                decimal=decimal,
                pd=pd,
                matrix_version=self.matrices.manifest.version,
            )
            rounded_provision = _round_provision(
                resolved.provision_amount,
                policy=cfg.exposure.rounding,
                decimal=decimal,
            )
            record = CmfProvisionRecord(
                row_id=str(row_id),
                portfolio=resolved.portfolio,
                method=resolved.method,
                exposure_amount=exposure.exposure_amount,
                direct_exposure_amount=exposure.direct_exposure_amount,
                contingent_exposure_amount=exposure.contingent_exposure_amount,
                pi_percent=resolved.pi_percent,
                pdi_percent=resolved.pdi_percent,
                pe_percent=resolved.pe_percent,
                provision_amount=rounded_provision,
                matrix_id=resolved.matrix_id,
                matrix_row_id=resolved.matrix_row_id,
                cmf_category=resolved.cmf_category,
                pd_source_value=(
                    None if context.pd_category is None else context.pd_category.pd_value
                ),
                guarantee_treatment=resolved.guarantee_treatment,
                warnings=(*exposure.warnings, *resolved.warnings),
            )
            records.append(record)
            detail_rows.append(
                _detail_row(
                    record,
                    source_reference=resolved.source_reference,
                    matrix_version=self.matrices.manifest.version,
                    ccf_percent=exposure.ccf_percent,
                )
            )
            detail_index.append(row_id)

        detail = pd.DataFrame(detail_rows, columns=list(_DETAIL_COLUMNS))
        detail.index = pd.Index(detail_index, name=data.index.name)
        summary = _summary_frame(records, matrix_version=self.matrices.manifest.version, pd=pd)
        card = _card(
            records,
            as_of_date=as_of_date,
            matrix_bundle=self.matrices,
            summary=summary,
            decimal=decimal,
        )
        result = CmfProvisionResult(
            detail=detail,
            summary=summary,
            records=tuple(records),
            card=card,
            matrix_bundle=self.matrices,
        )
        _emit_audit(audit, cfg=cfg, result=result)
        return result


@dataclass(frozen=True)
class DecimalRuntime:
    """Dependencias de ``decimal`` importadas dentro de ``calculate``."""

    decimal_cls: type[Decimal]
    invalid_operation_cls: type[Exception]
    rounding_half_up: str
    zero: Decimal
    hundred: Decimal
    pe_tolerance: Decimal


@dataclass(frozen=True)
class PdCategory:
    """Categoría CMF asignada desde ``pd_breaks`` y valor PD auditado."""

    category: str
    pd_value: Decimal


@dataclass(frozen=True)
class ConsumerState:
    """Estado regulatorio consolidado a nivel deudor para consumo."""

    days_past_due_bucket: str
    has_housing_loan: str
    system_dpd30: str
    is_default: bool


@dataclass(frozen=True)
class ExposureResolution:
    """Exposición directa más contingente B-3 convertida."""

    direct_exposure_amount: Decimal
    contingent_exposure_amount: Decimal
    exposure_amount: Decimal
    ccf_percent: Decimal | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RowContext:
    """Fila de entrada más contexto regulatorio precomputado."""

    row_id: object
    row: Any
    pd_category: PdCategory | None
    consumer_state: ConsumerState | None


@dataclass(frozen=True)
class CmfLookupKey:
    """Clave exacta de búsqueda de matriz CMF."""

    matrix_id: str
    dimensions: tuple[tuple[str, str], ...]

    @classmethod
    def from_dimensions(cls, matrix_id: str, dimensions: Mapping[str, str]) -> CmfLookupKey:
        """Normaliza dimensiones a orden determinista para trazabilidad."""
        return cls(matrix_id=matrix_id, dimensions=tuple(sorted(dimensions.items())))

    def as_dict(self) -> dict[str, str]:
        """Devuelve las dimensiones como dict para comparar contra ``CmfMatrixRow``."""
        return dict(self.dimensions)


@dataclass(frozen=True)
class ProvisionResolution:
    """Resultado regulatorio calculado para una fila."""

    portfolio: str
    method: str
    cmf_category: str | None
    matrix_id: str
    matrix_row_id: str
    pi_percent: Decimal | None
    pdi_percent: Decimal | None
    pe_percent: Decimal
    provision_amount: Decimal
    source_reference: str
    guarantee_treatment: str = "none"
    warnings: tuple[str, ...] = ()


def _import_pandas() -> Any:
    """Importa pandas localmente y traduce ausencias a mensaje accionable."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_CMF_EXTRA_MESSAGE) from exc


def _validate_runtime_config(cfg: CmfProvisioningConfig) -> CmfProvisioningConfig:
    """Revalida config para que errores de instanciación sean propios de Nikodym."""
    try:
        return CmfProvisioningConfig.model_validate(cfg)
    except (ConfigError, ValidationError) as exc:
        raise ConfigError(f"Hiperparámetros inválidos para CmfProvisioningEngine: {exc}") from exc


def _as_dataframe(frame: object, *, pd: Any) -> DataFrame:
    """Valida tipo DataFrame y copia defensivamente."""
    if not isinstance(frame, pd.DataFrame):
        raise CmfInputError(
            "CmfProvisioningEngine.calculate requiere pandas.DataFrame; "
            f"tipo observado={type(frame).__name__}."
        )
    return cast(DataFrame, frame.copy(deep=True))


def _validate_base_contract(frame: DataFrame, *, cfg: CmfProvisioningConfig) -> None:
    """Valida índice, columnas base y carteras soportadas por el motor CMF."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        raise CmfInputError(f"El frame CMF contiene columnas duplicadas: {duplicated}.")
    if not frame.index.is_unique:
        raise CmfInputError("CmfProvisioningEngine requiere índice único.")
    _require_columns(
        frame,
        (cfg.portfolio_col, cfg.exposure.direct_exposure_col),
        portfolio="base",
        row_id="<prevalidación>",
    )


def _resolve_pd_categories(
    cfg: CmfProvisioningConfig,
    frame: DataFrame,
    *,
    pd_frame: DataFrame | None,
    pd: Any,
    decimal: DecimalRuntime,
) -> dict[object, PdCategory]:
    """Resuelve categorías desde ``pd_breaks`` sólo cuando la config lo exige."""
    if cfg.pd_mapping.method != "pd_breaks":
        return {}
    if pd_frame is None:
        raise CmfInputError("pd_mapping.method='pd_breaks' exige pd_frame.")
    pd_data = _as_dataframe(pd_frame, pd=pd)
    if not pd_data.index.is_unique:
        raise CmfInputError("pd_frame CMF requiere índice único.")
    _require_columns(
        pd_data,
        (cfg.pd_mapping.pd_column,),
        portfolio="pd_breaks",
        row_id="<pd_frame>",
    )
    missing_index = [idx for idx in frame.index if idx not in pd_data.index]
    if missing_index:
        raise CmfInputError(
            "pd_frame no contiene todas las filas provisionadas; "
            f"primer índice faltante={missing_index[0]!r}."
        )
    breaks = tuple(
        _decimal_from_value(value, column="pd_breaks", decimal=decimal)
        for value in cfg.pd_mapping.pd_breaks
    )
    categories: dict[object, PdCategory] = {}
    for row_id in frame.index:
        raw_pd = _decimal_from_value(
            pd_data.loc[row_id, cfg.pd_mapping.pd_column],
            column=cfg.pd_mapping.pd_column,
            decimal=decimal,
        )
        if raw_pd < decimal.zero or raw_pd > decimal.decimal_cls("1"):
            raise CmfInputError(f"PD fuera de [0, 1] en fila {row_id!r}: valor observado={raw_pd}.")
        position = sum(1 for cutoff in breaks if raw_pd > cutoff)
        categories[row_id] = PdCategory(
            category=cfg.pd_mapping.categories[position],
            pd_value=raw_pd,
        )
    return categories


def _consumer_states(
    frame: DataFrame,
    *,
    cfg: CmfProvisioningConfig,
    pd: Any,
    decimal: DecimalRuntime,
) -> dict[object, ConsumerState]:
    """Consolida días de mora y flags de consumo a nivel deudor.

    El incumplimiento del numeral 3.2 del Capítulo B-1 tiene tres causales: mora igual o
    superior a 90 días, refinanciamiento para dejar vigente una operación con más de 60
    días de atraso, y reestructuración forzosa o condonación parcial. Solo la primera es
    derivable de la mora; las otras dos las declara el banco en
    ``exposure.is_default_col``. La columna es opcional y sus nulos se leen como "no
    marcado": el flag solo puede sumar incumplimiento, nunca quitar el que impone la mora.
    """
    consumer = frame.loc[frame[cfg.portfolio_col].eq("consumer")].copy(deep=True)
    if len(consumer.index) == 0:
        return {}
    required = (
        cfg.debtor_id_col,
        cfg.days_past_due_col,
        "has_housing_loan_system",
        "system_dpd30_last_3m",
    )
    for row_id, _row in consumer.iterrows():
        _require_columns(consumer, required, portfolio="consumer", row_id=row_id)

    default_col = cfg.exposure.is_default_col
    declares_default = default_col in consumer.columns

    states: dict[object, ConsumerState] = {}
    for _debtor_id, debtor_frame in consumer.groupby(cfg.debtor_id_col, sort=False, dropna=False):
        max_dpd = max(
            _int_days(value, column=cfg.days_past_due_col, row_id=idx, decimal=decimal)
            for idx, value in debtor_frame[cfg.days_past_due_col].items()
        )
        has_housing = any(
            _bool_dimension(value, column="has_housing_loan_system", row_id=idx)
            for idx, value in debtor_frame["has_housing_loan_system"].items()
        )
        system_dpd30 = any(
            _bool_dimension(value, column="system_dpd30_last_3m", row_id=idx)
            for idx, value in debtor_frame["system_dpd30_last_3m"].items()
        )
        declared_default = declares_default and any(
            _bool_dimension(value, column=default_col, row_id=idx)
            for idx, value in debtor_frame[default_col].items()
            if not _is_missing(value, pd)
        )
        is_default = max_dpd >= 90 or declared_default
        state = ConsumerState(
            # El deudor declarado en incumplimiento con mora baja debe trazarse como tal:
            # si la categoría reportara su tramo de mora, la auditoría no vería el PI de 100 %.
            days_past_due_bucket=(
                "incumplimiento" if is_default else _consumer_dpd_bucket(max_dpd)
            ),
            has_housing_loan="yes" if has_housing else "no",
            system_dpd30="yes" if system_dpd30 else "no",
            is_default=is_default,
        )
        for row_id in debtor_frame.index:
            states[row_id] = state
    return states


def _direct_exposure(row: Any, *, cfg: CmfProvisioningConfig, decimal: DecimalRuntime) -> Decimal:
    """Lee exposición directa y aplica la política de saldos negativos."""
    exposure = _decimal_from_value(
        row[cfg.exposure.direct_exposure_col],
        column=cfg.exposure.direct_exposure_col,
        decimal=decimal,
    )
    if exposure < decimal.zero and not cfg.exposure.allow_negative_exposure:
        raise CmfInputError(
            "Exposición directa negativa no permitida por config: "
            f"columna={cfg.exposure.direct_exposure_col!r}, valor={exposure}."
        )
    return exposure


def _resolve_exposure(
    context: RowContext,
    *,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
    pd: Any,
) -> ExposureResolution:
    """Calcula exposición directa más contingente B-3 convertido."""
    direct_exposure = _direct_exposure(context.row, cfg=cfg, decimal=decimal)
    contingent_amount = _optional_decimal_from_row(
        context.row,
        cfg.exposure.contingent_amount_col,
        pd=pd,
        decimal=decimal,
    )
    if contingent_amount == decimal.zero:
        return ExposureResolution(
            direct_exposure_amount=direct_exposure,
            contingent_exposure_amount=decimal.zero,
            exposure_amount=direct_exposure,
            ccf_percent=None,
        )
    if contingent_amount < decimal.zero and not cfg.exposure.allow_negative_exposure:
        raise CmfInputError(
            "Exposición contingente negativa no permitida por config: "
            f"columna={cfg.exposure.contingent_amount_col!r}, valor={contingent_amount}."
        )
    contingent_row = _contingent_row(
        context,
        cfg=cfg,
        bundle=bundle,
        pd=pd,
        matrix_version=bundle.manifest.version,
    )
    matrix_ccf = _required_percent(
        contingent_row.ccf_percent,
        row=contingent_row,
        field_name="ccf_percent",
        decimal=decimal,
    )
    ccf = decimal.hundred if _is_default_for_contingent(context, cfg=cfg, pd=pd) else matrix_ccf
    contingent_exposure = contingent_amount * ccf / decimal.hundred
    total_exposure = direct_exposure + contingent_exposure
    return ExposureResolution(
        direct_exposure_amount=direct_exposure,
        contingent_exposure_amount=contingent_exposure,
        exposure_amount=total_exposure,
        ccf_percent=ccf,
    )


def _optional_decimal_from_row(
    row: Any,
    column: str,
    *,
    pd: Any,
    decimal: DecimalRuntime,
) -> Decimal:
    """Lee un Decimal opcional: columna ausente o nula equivale a cero."""
    if column not in row.index or _is_missing(row[column], pd):
        return decimal.zero
    return _decimal_from_value(row[column], column=column, decimal=decimal)


def _contingent_row(
    context: RowContext,
    *,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    pd: Any,
    matrix_version: str,
) -> CmfMatrixRow:
    """Busca el CCF B-3 por tipo contingente y subtipo cuando corresponde."""
    row = context.row
    if cfg.exposure.contingent_type_col not in row.index:
        raise CmfInputError(
            "Falta columna de tipo contingente B-3 para exposición contingente positiva: "
            f"cartera={row[cfg.portfolio_col]!r}, fila={context.row_id!r}, "
            f"columna={cfg.exposure.contingent_type_col!r}."
        )
    contingent_type = _text_value(
        row[cfg.exposure.contingent_type_col],
        column=cfg.exposure.contingent_type_col,
        row_id=context.row_id,
        pd=pd,
    )
    dimensions = {"contingent_type": contingent_type}
    if contingent_type == "otros_compromisos_credito":
        if _CONTINGENT_SUBTYPE_COL not in row.index or _is_missing(
            row[_CONTINGENT_SUBTYPE_COL],
            pd,
        ):
            return _raise_unmapped_contingent(
                context,
                cfg=cfg,
                observed=f"{contingent_type}|<sin_subtipo>",
                matrix_version=matrix_version,
            )
        dimensions["contingent_subtype"] = _text_value(
            row[_CONTINGENT_SUBTYPE_COL],
            column=_CONTINGENT_SUBTYPE_COL,
            row_id=context.row_id,
            pd=pd,
        )
    try:
        return _lookup_by_dimensions(bundle, _CONTINGENT_MATRIX, dimensions)
    except CmfMatrixError as exc:
        raise _unmapped_contingent_error(
            context,
            cfg=cfg,
            observed=str(dimensions),
            matrix_version=matrix_version,
        ) from exc


def _raise_unmapped_contingent(
    context: RowContext,
    *,
    cfg: CmfProvisioningConfig,
    observed: str,
    matrix_version: str,
) -> CmfMatrixRow:
    """Levanta o traduce un contingente no mapeado según config."""
    raise _unmapped_contingent_error(
        context,
        cfg=cfg,
        observed=observed,
        matrix_version=matrix_version,
    )


def _unmapped_contingent_error(
    context: RowContext,
    *,
    cfg: CmfProvisioningConfig,
    observed: str,
    matrix_version: str,
) -> CmfProvisioningError:
    """Construye el error regulatorio para contingentes B-3 sin fila verificada."""
    message = (
        "Tipo contingente B-3 no mapeado contra las ocho filas verificadas: "
        f"cartera={context.row[cfg.portfolio_col]!r}, regla=docs/normativa_cmf_parametros.md §6, "
        f"matrix_version={matrix_version!r}, valor_observado={observed}."
    )
    if cfg.matrices.fail_on_unmapped_contingent_type:
        return CmfMissingRegulatoryDataError(message)
    return CmfMappingError(message)


def _is_default_for_contingent(
    context: RowContext,
    *,
    cfg: CmfProvisioningConfig,
    pd: Any,
) -> bool:
    """Lee el flag de incumplimiento que fuerza CCF B-3 a 100 %."""
    row = context.row
    if cfg.exposure.is_default_col not in row.index or _is_missing(
        row[cfg.exposure.is_default_col],
        pd,
    ):
        raise CmfInputError(
            "Contingente B-3 exige indicador de incumplimiento para aplicar override normativo: "
            f"cartera={row[cfg.portfolio_col]!r}, fila={context.row_id!r}, "
            f"columna={cfg.exposure.is_default_col!r}."
        )
    return _bool_dimension(
        row[cfg.exposure.is_default_col],
        column=cfg.exposure.is_default_col,
        row_id=context.row_id,
    )


def _resolve_provision(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
    pd: Any,
) -> ProvisionResolution:
    """Despacha la resolución por cartera CMF soportada."""
    portfolio = _text_value(
        context.row[cfg.portfolio_col],
        column=cfg.portfolio_col,
        row_id=context.row_id,
        pd=pd,
    )
    if portfolio == "commercial_individual":
        return _resolve_commercial_individual(
            context,
            exposure=exposure,
            cfg=cfg,
            bundle=bundle,
            decimal=decimal,
            pd=pd,
        )
    if portfolio == "commercial_group_leasing":
        return _resolve_leasing(context, exposure=exposure, cfg=cfg, bundle=bundle, decimal=decimal)
    if portfolio == "commercial_group_student":
        return _resolve_student(context, exposure=exposure, cfg=cfg, bundle=bundle, decimal=decimal)
    if portfolio == "commercial_group_generic_factoring":
        return _resolve_generic_factoring(
            context,
            exposure=exposure,
            cfg=cfg,
            bundle=bundle,
            decimal=decimal,
        )
    if portfolio == "consumer":
        return _resolve_consumer(
            context,
            exposure=exposure,
            cfg=cfg,
            bundle=bundle,
            decimal=decimal,
        )
    if portfolio == "housing":
        return _resolve_housing(context, exposure=exposure, cfg=cfg, bundle=bundle, decimal=decimal)
    raise CmfMappingError(f"Cartera CMF no soportada por el motor CMF: {portfolio!r}.")


def _resolve_commercial_individual(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
    pd: Any,
) -> ProvisionResolution:
    """Resuelve cartera comercial individual A1-B4 o C1-C6."""
    category = _category_for_individual(context, exposure=exposure, cfg=cfg, decimal=decimal, pd=pd)
    if category.startswith("C"):
        if exposure == decimal.zero:
            raise CmfCalculationError("C1-C6 exige exposición mayor que cero para aplicar PP.")
        row = _lookup_exact(
            bundle,
            CmfLookupKey.from_dimensions(
                _INDIVIDUAL_DEFAULT_MATRIX,
                {
                    "portfolio_type": "default",
                    "category": category,
                    "expected_loss_range": _expected_loss_range(category),
                    "expected_loss_range_label": _expected_loss_range_label(category),
                },
            ),
        )
        pp = _required_percent(row.pp_percent, row=row, field_name="pp_percent", decimal=decimal)
        provision = exposure * pp / decimal.hundred
        return ProvisionResolution(
            portfolio="commercial_individual",
            method="default_pp",
            cmf_category=category,
            matrix_id=row.matrix_id,
            matrix_row_id=row.row_id,
            pi_percent=None,
            pdi_percent=None,
            pe_percent=pp,
            provision_amount=provision,
            source_reference=_source_reference(row),
        )

    row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _INDIVIDUAL_PERFORMING_MATRIX,
            {"portfolio_type": _portfolio_type(category), "category": category},
        ),
    )
    pi = _required_percent(row.pi_percent, row=row, field_name="pi_percent", decimal=decimal)
    pdi = _required_percent(row.pdi_percent, row=row, field_name="pdi_percent", decimal=decimal)
    pe = _required_percent(row.pe_percent, row=row, field_name="pe_percent", decimal=decimal)
    _check_pe_consistency(row=row, pi=pi, pdi=pdi, pe=pe, decimal=decimal)
    return _standard_resolution(
        portfolio="commercial_individual",
        category=category,
        matrix_row_id=row.row_id,
        matrix_id=row.matrix_id,
        source_reference=_source_reference(row),
        pi=pi,
        pdi=pdi,
        exposure=exposure,
        decimal=decimal,
    )


def _resolve_leasing(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
) -> ProvisionResolution:
    """Resuelve leasing comercial por mora, tipo de bien y PVB."""
    row = context.row
    _require_columns(
        row.to_frame().T,
        (cfg.days_past_due_col, "leasing_asset_type", "pvb"),
        portfolio="commercial_group_leasing",
        row_id=context.row_id,
    )
    asset_type = _canonical_asset(row["leasing_asset_type"])
    dpd_bucket = _dpd_bucket(
        _int_days(
            row[cfg.days_past_due_col],
            column=cfg.days_past_due_col,
            row_id=context.row_id,
            decimal=decimal,
        )
    )
    pvb_bucket = _pvb_bucket(_decimal_from_value(row["pvb"], column="pvb", decimal=decimal))
    pi_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _LEASING_MATRIX,
            {
                "row_type": "pi_by_dpd_asset",
                "days_past_due_bucket": dpd_bucket,
                "asset_type": asset_type,
            },
        ),
    )
    pdi_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _LEASING_MATRIX,
            {"row_type": "pdi_by_pvb_asset", "pvb_bucket": pvb_bucket, "asset_type": asset_type},
        ),
    )
    return _paired_standard_resolution(
        portfolio="commercial_group_leasing",
        category=f"{dpd_bucket}|{asset_type}|{pvb_bucket}",
        pi_row=pi_row,
        pdi_row=pdi_row,
        exposure=exposure,
        decimal=decimal,
    )


def _resolve_student(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
) -> ProvisionResolution:
    """Resuelve préstamos estudiantiles grupales."""
    row = context.row
    _require_columns(
        row.to_frame().T,
        (cfg.days_past_due_col, "student_payment_due", "student_loan_type"),
        portfolio="commercial_group_student",
        row_id=context.row_id,
    )
    payment_due = _yes_no(
        row["student_payment_due"],
        column="student_payment_due",
        row_id=context.row_id,
    )
    loan_type = _student_type(row["student_loan_type"])
    dpd_bucket = (
        _dpd_bucket(
            _int_days(
                row[cfg.days_past_due_col],
                column=cfg.days_past_due_col,
                row_id=context.row_id,
                decimal=decimal,
            )
        )
        if payment_due == "yes"
        else "n/a"
    )
    pi_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _STUDENT_MATRIX,
            {
                "row_type": "pi_by_due_dpd_type",
                "payment_due": payment_due,
                "days_past_due_bucket": dpd_bucket,
                "student_loan_type": loan_type,
            },
        ),
    )
    pdi_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _STUDENT_MATRIX,
            {
                "row_type": "pdi_by_due_type",
                "payment_due": payment_due,
                "student_loan_type": loan_type,
            },
        ),
    )
    return _paired_standard_resolution(
        portfolio="commercial_group_student",
        category=f"{payment_due}|{dpd_bucket}|{loan_type}",
        pi_row=pi_row,
        pdi_row=pdi_row,
        exposure=exposure,
        decimal=decimal,
    )


def _resolve_generic_factoring(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
) -> ProvisionResolution:
    """Resuelve comerciales genéricas/factoring por mora, PTVG y responsabilidad."""
    row = context.row
    _require_columns(
        row.to_frame().T,
        (cfg.days_past_due_col, "ptvg_bucket", "factoring_recourse_type"),
        portfolio="commercial_group_generic_factoring",
        row_id=context.row_id,
    )
    dpd_bucket = _dpd_bucket(
        _int_days(
            row[cfg.days_past_due_col],
            column=cfg.days_past_due_col,
            row_id=context.row_id,
            decimal=decimal,
        )
    )
    pdi_ptvg_bucket = _text_plain(row["ptvg_bucket"], column="ptvg_bucket", row_id=context.row_id)
    pi_ptvg_bucket = _pi_ptvg_bucket(pdi_ptvg_bucket, row)
    recourse_type = _recourse_type(row["factoring_recourse_type"])
    guarantee_status = "sin_garantia" if pdi_ptvg_bucket == "sin_garantia" else "con_garantia"
    pi_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _GENERIC_MATRIX,
            {
                "row_type": "pi_by_dpd_ptvg",
                "days_past_due_bucket": dpd_bucket,
                "ptvg_bucket": pi_ptvg_bucket,
            },
        ),
    )
    pdi_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _GENERIC_MATRIX,
            {
                "row_type": "pdi_by_ptvg_recourse",
                "guarantee_status": guarantee_status,
                "ptvg_bucket": pdi_ptvg_bucket,
                "recourse_type": recourse_type,
            },
        ),
    )
    return _paired_standard_resolution(
        portfolio="commercial_group_generic_factoring",
        category=f"{dpd_bucket}|{pdi_ptvg_bucket}|{recourse_type}",
        pi_row=pi_row,
        pdi_row=pdi_row,
        exposure=exposure,
        decimal=decimal,
    )


def _resolve_consumer(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
) -> ProvisionResolution:
    """Resuelve consumo con PI consolidada a nivel de deudor."""
    if context.consumer_state is None:
        raise CmfCalculationError("No se precomputó estado deudor para cartera consumer.")
    _require_columns(
        context.row.to_frame().T,
        (cfg.product_type_col,),
        portfolio="consumer",
        row_id=context.row_id,
    )
    product = _consumer_product(context.row[cfg.product_type_col])
    state = context.consumer_state
    pi_dimensions = (
        {"row_type": "pi_default", "debtor_default_status": "incumplimiento"}
        if state.is_default
        else {
            "row_type": "pi_by_debtor_state",
            "days_past_due_bucket": state.days_past_due_bucket,
            "has_housing_loan": state.has_housing_loan,
            "system_dpd30": state.system_dpd30,
        }
    )
    pi_row = _lookup_exact(bundle, CmfLookupKey.from_dimensions(_CONSUMER_MATRIX, pi_dimensions))
    pdi_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _CONSUMER_MATRIX,
            {
                "row_type": "pdi_by_product_housing",
                "has_housing_loan": state.has_housing_loan,
                "consumer_product_type": product,
            },
        ),
    )
    return _paired_standard_resolution(
        portfolio="consumer",
        category=f"{state.days_past_due_bucket}|{state.has_housing_loan}|{state.system_dpd30}",
        pi_row=pi_row,
        pdi_row=pdi_row,
        exposure=exposure,
        decimal=decimal,
    )


def _resolve_housing(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
) -> ProvisionResolution:
    """Resuelve vivienda PVG usando PE tabulada."""
    row = context.row
    _require_columns(
        row.to_frame().T,
        (cfg.days_past_due_col,),
        portfolio="housing",
        row_id=context.row_id,
    )
    pvg_bucket = _pvg_bucket_for_row(row, decimal=decimal)
    mora_bucket = _housing_mora_bucket(
        _int_days(
            row[cfg.days_past_due_col],
            column=cfg.days_past_due_col,
            row_id=context.row_id,
            decimal=decimal,
        )
    )
    matrix_row = _lookup_exact(
        bundle,
        CmfLookupKey.from_dimensions(
            _HOUSING_MATRIX,
            {"pvg_bucket": pvg_bucket, "mora_bucket": mora_bucket},
        ),
    )
    pi = _required_percent(
        matrix_row.pi_percent,
        row=matrix_row,
        field_name="pi_percent",
        decimal=decimal,
    )
    pdi = _required_percent(
        matrix_row.pdi_percent,
        row=matrix_row,
        field_name="pdi_percent",
        decimal=decimal,
    )
    pe = _required_percent(
        matrix_row.pe_percent,
        row=matrix_row,
        field_name="pe_percent",
        decimal=decimal,
    )
    _check_pe_consistency(row=matrix_row, pi=pi, pdi=pdi, pe=pe, decimal=decimal)
    return ProvisionResolution(
        portfolio="housing",
        method="pvg_tabulated_pe",
        cmf_category=f"{pvg_bucket}|{mora_bucket}",
        matrix_id=matrix_row.matrix_id,
        matrix_row_id=matrix_row.row_id,
        pi_percent=pi,
        pdi_percent=pdi,
        pe_percent=pe,
        provision_amount=exposure * pe / decimal.hundred,
        source_reference=_source_reference(matrix_row),
    )


def _apply_guarantee_substitution(
    context: RowContext,
    *,
    resolution: ProvisionResolution,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    bundle: CmfMatrixBundle,
    decimal: DecimalRuntime,
    pd: Any,
    matrix_version: str,
) -> ProvisionResolution:
    """Aplica sustitución proporcional por avales cuando la fila la declara."""
    if not cfg.guarantees.enable_aval_substitution:
        return resolution
    coverage = _optional_decimal_from_row(
        context.row,
        _AVAL_COVERAGE_COL,
        pd=pd,
        decimal=decimal,
    )
    if coverage == decimal.zero:
        return resolution
    if coverage < decimal.zero or coverage > decimal.hundred:
        raise CmfInputError(
            "Cobertura de aval fuera de [0, 100]: "
            f"cartera={resolution.portfolio!r}, regla=docs/normativa_cmf_parametros.md §2.d, "
            f"matrix_version={matrix_version!r}, valor_observado={coverage}."
        )
    _require_columns(
        context.row.to_frame().T,
        (_AVAL_RATING_SCALE_COL, _AVAL_RATING_CATEGORY_COL),
        portfolio=resolution.portfolio,
        row_id=context.row_id,
    )
    aval_row = _aval_quality_row(context, bundle=bundle, pd=pd)
    aval_pi = _required_percent(
        aval_row.pi_percent,
        row=aval_row,
        field_name="pi_percent",
        decimal=decimal,
    )
    aval_pdi = _required_percent(
        aval_row.pdi_percent,
        row=aval_row,
        field_name="pdi_percent",
        decimal=decimal,
    )
    aval_pe = aval_pi * aval_pdi / decimal.hundred
    method = (
        "metodo_2_pi_pdi"
        if resolution.pi_percent is not None and resolution.pdi_percent is not None
        else "metodo_1_pe_directa"
    )
    formula_row = _lookup_by_dimensions(
        bundle,
        _GUARANTEE_SUBSTITUTION_MATRIX,
        {"row_type": "formula", "method": method},
    )
    guaranteed_share = coverage / decimal.hundred
    unguaranteed_share = (decimal.hundred - coverage) / decimal.hundred
    if method == "metodo_2_pi_pdi":
        group_pi = resolution.pi_percent
        group_pdi = resolution.pdi_percent
        assert group_pi is not None and group_pdi is not None
        provision = (
            exposure * unguaranteed_share * group_pi / decimal.hundred * group_pdi / decimal.hundred
        ) + (exposure * guaranteed_share * aval_pe / decimal.hundred)
    else:
        provision = (exposure * unguaranteed_share * resolution.pe_percent / decimal.hundred) + (
            exposure * guaranteed_share * aval_pe / decimal.hundred
        )
    effective_pe = (
        provision / exposure * decimal.hundred if exposure != decimal.zero else decimal.zero
    )
    return replace(
        resolution,
        matrix_row_id=f"{resolution.matrix_row_id}|{formula_row.row_id}|{aval_row.row_id}",
        pe_percent=effective_pe,
        provision_amount=provision,
        source_reference=_join_source_texts(
            (
                resolution.source_reference,
                _source_reference(formula_row),
                _source_reference(aval_row),
            )
        ),
        guarantee_treatment="aval_substitution",
    )


def _aval_quality_row(context: RowContext, *, bundle: CmfMatrixBundle, pd: Any) -> CmfMatrixRow:
    """Busca PI/PDI del aval por categoría y escala de rating externo."""
    rating_scale = _normaliza_rating_scale(
        _text_value(
            context.row[_AVAL_RATING_SCALE_COL],
            column=_AVAL_RATING_SCALE_COL,
            row_id=context.row_id,
            pd=pd,
        )
    )
    rating_category = _normaliza_rating_category(
        _text_value(
            context.row[_AVAL_RATING_CATEGORY_COL],
            column=_AVAL_RATING_CATEGORY_COL,
            row_id=context.row_id,
            pd=pd,
        )
    )
    try:
        return _lookup_by_dimensions(
            bundle,
            _GUARANTEE_AVAL_MATRIX,
            {"rating_category": rating_category, "rating_scale": rating_scale},
        )
    except CmfMatrixError as exc:
        raise CmfMappingError(
            "Aval sin equivalencia de calidad crediticia verificada: "
            "regla=docs/normativa_cmf_parametros.md §5.2, "
            f"rating_scale={rating_scale!r}, rating_category={rating_category!r}."
        ) from exc


def _normaliza_rating_scale(value: str) -> str:
    """Normaliza escala de rating del aval a la dimensión versionada."""
    normalized = value.strip().lower()
    aliases = {
        "internacional": "international",
        "international": "international",
        "nacional": "national",
        "national": "national",
    }
    mapped = aliases.get(normalized)
    if mapped is None:
        raise CmfMappingError(f"Escala de rating de aval no soportada: {value!r}.")
    return mapped


def _normaliza_rating_category(value: str) -> str:
    """Normaliza espacios en categoría de rating sin alterar la escala normativa."""
    return value.strip().replace(" / ", "/")


def _enforce_financial_guarantee_policy(
    context: RowContext,
    *,
    exposure: ExposureResolution,
    cfg: CmfProvisioningConfig,
    decimal: DecimalRuntime,
    pd: Any,
    matrix_version: str,
) -> None:
    """Falla ante garantías financieras con haircuts pendientes salvo recupero explícito."""
    if not _requires_financial_guarantee_haircut(context.row, pd=pd, decimal=decimal):
        return
    policy = cfg.guarantees.financial_guarantee_policy
    if policy == "ignore_if_missing":
        return
    recoverable_col = _recoverable_column(context.row, cfg)
    recoverable = None
    if recoverable_col is not None and not _is_missing(context.row[recoverable_col], pd):
        recoverable = _decimal_from_value(
            context.row[recoverable_col],
            column=recoverable_col,
            decimal=decimal,
        )
    if policy == "use_recoverable_amount" and recoverable is not None:
        if recoverable < decimal.zero:
            raise CmfInputError(
                "recoverable_amount de garantía financiera no puede ser negativo: "
                f"fila={context.row_id!r}, valor_observado={recoverable}."
            )
        return
    raise CmfMissingRegulatoryDataError(
        "Garantía financiera requiere aforo/haircut no verificado: "
        f"cartera={context.row[cfg.portfolio_col]!r}, regla=docs/normativa_cmf_parametros.md §5.2, "
        f"matrix_version={matrix_version!r}, "
        f"valor_observado={_financial_guarantee_observed(context.row)}; "
        f"exposure_amount={exposure.exposure_amount}."
    )


def _requires_financial_guarantee_haircut(
    row: Any,
    *,
    pd: Any,
    decimal: DecimalRuntime,
) -> bool:
    """Detecta columnas explícitas que declaran garantía financiera."""
    for column in _FINANCIAL_GUARANTEE_FLAG_COLS:
        if column in row.index and not _is_missing(row[column], pd):
            return _bool_dimension(row[column], column=column, row_id=row.name)
    for column in _FINANCIAL_GUARANTEE_AMOUNT_COLS:
        if column in row.index and not _is_missing(row[column], pd):
            amount = _decimal_from_value(row[column], column=column, decimal=decimal)
            if amount < decimal.zero:
                raise CmfInputError(
                    f"La columna '{column}' no puede ser negativa para garantía financiera."
                )
            if amount > decimal.zero:
                return True
    for column in _FINANCIAL_GUARANTEE_TYPE_COLS:
        if column in row.index and not _is_missing(row[column], pd):
            observed = str(row[column]).strip().lower()
            if observed in _FINANCIAL_GUARANTEE_TYPE_VALUES:
                return True
    return False


def _financial_guarantee_observed(row: Any) -> str:
    """Resume el primer marcador de garantía financiera observado."""
    for column in (
        *_FINANCIAL_GUARANTEE_FLAG_COLS,
        *_FINANCIAL_GUARANTEE_AMOUNT_COLS,
        *_FINANCIAL_GUARANTEE_TYPE_COLS,
    ):
        if column in row.index:
            return f"{column}={row[column]!r}"
    return "<sin_columna_explicita>"


def _category_for_individual(
    context: RowContext,
    *,
    exposure: Decimal,
    cfg: CmfProvisioningConfig,
    decimal: DecimalRuntime,
    pd: Any,
) -> str:
    """Obtiene categoría individual provista, mapeada desde PD o derivada por recupero."""
    if context.pd_category is not None:
        return context.pd_category.category
    if cfg.category_col in context.row.index and not _is_missing(context.row[cfg.category_col], pd):
        return _text_value(
            context.row[cfg.category_col],
            column=cfg.category_col,
            row_id=context.row_id,
            pd=pd,
        )
    recoverable_col = _recoverable_column(context.row, cfg)
    if recoverable_col is None:
        raise CmfInputError(
            "Cartera comercial individual exige categoría CMF provista o recoverable_amount "
            "para encasillar C1-C6."
        )
    recoverable = _decimal_from_value(
        context.row[recoverable_col],
        column=recoverable_col,
        decimal=decimal,
    )
    if exposure == decimal.zero:
        raise CmfCalculationError("No se puede calcular tasa (E-R)/E con exposición cero.")
    loss_percent = (exposure - recoverable) * decimal.hundred / exposure
    return _category_from_loss_percent(loss_percent, decimal=decimal)


def _recoverable_column(row: Any, cfg: CmfProvisioningConfig) -> str | None:
    """Resuelve la columna de recupero explícita o el nombre canónico si existe."""
    configured = cfg.guarantees.recoverable_amount_col
    if configured is not None:
        return configured if configured in row.index else None
    return "recoverable_amount" if "recoverable_amount" in row.index else None


def _standard_resolution(
    *,
    portfolio: str,
    category: str | None,
    matrix_row_id: str,
    matrix_id: str,
    source_reference: str,
    pi: Decimal,
    pdi: Decimal,
    exposure: Decimal,
    decimal: DecimalRuntime,
) -> ProvisionResolution:
    """Construye resolución estándar ``E * PI/100 * PDI/100``."""
    pe = pi * pdi / decimal.hundred
    return ProvisionResolution(
        portfolio=portfolio,
        method="standard_b1",
        cmf_category=category,
        matrix_id=matrix_id,
        matrix_row_id=matrix_row_id,
        pi_percent=pi,
        pdi_percent=pdi,
        pe_percent=pe,
        provision_amount=exposure * pi / decimal.hundred * pdi / decimal.hundred,
        source_reference=source_reference,
    )


def _paired_standard_resolution(
    *,
    portfolio: str,
    category: str,
    pi_row: CmfMatrixRow,
    pdi_row: CmfMatrixRow,
    exposure: Decimal,
    decimal: DecimalRuntime,
) -> ProvisionResolution:
    """Combina una fila PI y una fila PDI de la misma matriz."""
    pi = _required_percent(pi_row.pi_percent, row=pi_row, field_name="pi_percent", decimal=decimal)
    pdi = _required_percent(
        pdi_row.pdi_percent,
        row=pdi_row,
        field_name="pdi_percent",
        decimal=decimal,
    )
    return _standard_resolution(
        portfolio=portfolio,
        category=category,
        matrix_row_id=f"{pi_row.row_id}|{pdi_row.row_id}",
        matrix_id=pi_row.matrix_id,
        source_reference=_join_sources((pi_row, pdi_row)),
        pi=pi,
        pdi=pdi,
        exposure=exposure,
        decimal=decimal,
    )


def _lookup_exact(bundle: CmfMatrixBundle, key: CmfLookupKey) -> CmfMatrixRow:
    """Busca una única fila de matriz por dimensiones exactas."""
    dimensions = key.as_dict()
    matches = [row for row in bundle.get_rows(key.matrix_id) if row.dimensions == dimensions]
    if len(matches) != 1:
        raise CmfMatrixError(
            "Lookup CMF no resolvió una fila exacta: "
            f"matrix_id={key.matrix_id!r}, dimensions={dimensions!r}, coincidencias={len(matches)}."
        )
    return matches[0]


def _lookup_by_dimensions(
    bundle: CmfMatrixBundle,
    matrix_id: str,
    dimensions: Mapping[str, str],
) -> CmfMatrixRow:
    """Busca una única fila que contenga las dimensiones regulatorias provistas."""
    matches = [
        row
        for row in bundle.get_rows(matrix_id)
        if all(row.dimensions.get(key) == value for key, value in dimensions.items())
    ]
    if len(matches) != 1:
        raise CmfMatrixError(
            "Lookup CMF por dimensiones parciales no resolvió una fila exacta: "
            f"matrix_id={matrix_id!r}, dimensions={dict(dimensions)!r}, "
            f"coincidencias={len(matches)}."
        )
    return matches[0]


def _required_percent(
    value: str | None,
    *,
    row: CmfMatrixRow,
    field_name: str,
    decimal: DecimalRuntime,
) -> Decimal:
    """Convierte porcentaje de matriz desde string normativo exacto."""
    if value is None:
        raise CmfMatrixError(
            f"Falta {field_name} en matrix_id={row.matrix_id!r}, row_id={row.row_id!r}."
        )
    return _decimal_from_text(value, column=field_name, row_id=row.row_id, decimal=decimal)


def _check_pe_consistency(
    *,
    row: CmfMatrixRow,
    pi: Decimal,
    pdi: Decimal,
    pe: Decimal,
    decimal: DecimalRuntime,
) -> None:
    """Verifica ``PE ≈ PI*PDI/100`` con tolerancia explícita de matriz."""
    expected = pi * pdi / decimal.hundred
    if abs(pe - expected) > decimal.pe_tolerance:
        raise CmfMatrixError(
            "PE inconsistente para "
            f"matrix_id={row.matrix_id!r}, row_id={row.row_id!r}: "
            f"PE={pe}, PI*PDI/100={expected}, "
            f"tolerancia={decimal.pe_tolerance}."
        )


def _decimal_from_value(value: object, *, column: str, decimal: DecimalRuntime) -> Decimal:
    """Convierte escalares de entrada a ``Decimal`` finito sin pasar por float binario."""
    if isinstance(value, bool):
        raise CmfInputError(f"La columna '{column}' debe ser numérica, no booleana.")
    text = str(value).strip().replace(",", ".")
    if not text:
        raise CmfInputError(f"La columna '{column}' contiene un valor vacío.")
    try:
        observed = decimal.decimal_cls(text)
    except decimal.invalid_operation_cls as exc:
        raise CmfInputError(
            f"La columna '{column}' debe contener números compatibles con Decimal: {value!r}."
        ) from exc
    if not observed.is_finite():
        raise CmfInputError(f"La columna '{column}' debe contener sólo valores finitos.")
    return decimal.zero if observed.is_zero() else observed


def _decimal_from_text(
    value: str,
    *,
    column: str,
    row_id: object,
    decimal: DecimalRuntime,
) -> Decimal:
    """Convierte strings regulatorios con coma decimal a ``Decimal``."""
    try:
        observed = decimal.decimal_cls(value.strip().replace(",", "."))
    except decimal.invalid_operation_cls as exc:
        raise CmfMatrixError(
            f"Porcentaje inválido en row_id={row_id!r}, campo={column}: {value!r}."
        ) from exc
    if not observed.is_finite() or observed < decimal.zero:
        raise CmfMatrixError(
            f"Porcentaje no finito o negativo en row_id={row_id!r}, campo={column}: {value!r}."
        )
    return decimal.zero if observed.is_zero() else observed


def _require_columns(
    frame: DataFrame,
    columns: tuple[str, ...],
    *,
    portfolio: str,
    row_id: object,
) -> None:
    """Exige columnas presentes antes de resolver una cartera."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise CmfInputError(
            f"Faltan columnas regulatorias para cartera={portfolio!r}, fila={row_id!r}: {missing}."
        )


def _text_value(value: object, *, column: str, row_id: object, pd: Any) -> str:
    """Lee texto obligatorio y rechaza nulos de pandas."""
    if _is_missing(value, pd):
        raise CmfInputError(f"La columna '{column}' no puede ser nula en fila {row_id!r}.")
    return _text_plain(value, column=column, row_id=row_id)


def _text_plain(value: object, *, column: str, row_id: object) -> str:
    """Normaliza texto obligatorio sin consultar pandas."""
    text = str(value).strip()
    if not text:
        raise CmfInputError(f"La columna '{column}' no puede estar vacía en fila {row_id!r}.")
    return text


def _is_missing(value: object, pd: Any) -> bool:
    """Detecta nulos escalares sin disparar ambigüedad sobre objetos tabulares."""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _int_days(value: object, *, column: str, row_id: object, decimal: DecimalRuntime) -> int:
    """Convierte días de mora a entero no negativo exacto."""
    days = _decimal_from_value(value, column=column, decimal=decimal)
    if days != days.to_integral_value() or days < decimal.zero:
        raise CmfInputError(
            f"La columna '{column}' debe contener días de mora enteros no negativos "
            f"en fila {row_id!r}: {value!r}."
        )
    return int(days)


def _bool_dimension(value: object, *, column: str, row_id: object) -> bool:
    """Convierte flags booleanos declarativos a bool."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _BOOLEAN_YES:
        return True
    if text in _BOOLEAN_NO:
        return False
    raise CmfInputError(f"La columna '{column}' debe ser booleana en fila {row_id!r}: {value!r}.")


def _yes_no(value: object, *, column: str, row_id: object) -> str:
    """Normaliza un flag a ``yes``/``no`` para dimensiones de matriz."""
    return "yes" if _bool_dimension(value, column=column, row_id=row_id) else "no"


def _dpd_bucket(days: int) -> str:
    """Tramo de mora B-1 para matrices comerciales grupales."""
    if days == 0:
        return "0"
    if days <= 29:
        return "1_29"
    if days <= 59:
        return "30_59"
    if days <= 89:
        return "60_89"
    return "incumplimiento"


def _consumer_dpd_bucket(days: int) -> str:
    """Tramo de mora de consumo vigente desde enero de 2025."""
    if days <= 7:
        return "0_7"
    if days <= 30:
        return "8_30"
    if days <= 60:
        return "31_60"
    if days <= 89:
        return "61_89"
    return "incumplimiento"


def _housing_mora_bucket(days: int) -> str:
    """Tramo de mora para vivienda PVG."""
    if days == 0:
        return "0"
    if days <= 29:
        return "1_29"
    if days <= 59:
        return "30_59"
    if days <= 89:
        return "60_89"
    return "incumplimiento"


def _portfolio_type(category: str) -> str:
    """Traduce A/B a tipo de cartera individual de la matriz."""
    if category.startswith("A"):
        return "normal"
    if category.startswith("B"):
        return "substandard"
    raise CmfMatrixError(f"Categoría individual no encontrada en matriz A1-B4: {category!r}.")


def _expected_loss_range(category: str) -> str:
    """Rango normativo esperado para C1-C6."""
    return {
        "C1": "hasta_3_percent",
        "C2": "gt_3_le_20_percent",
        "C3": "gt_20_le_30_percent",
        "C4": "gt_30_le_50_percent",
        "C5": "gt_50_le_80_percent",
        "C6": "gt_80_percent",
    }[category]


def _expected_loss_range_label(category: str) -> str:
    """Etiqueta normativa esperada para C1-C6."""
    return {
        "C1": "Hasta 3 %",
        "C2": "Mas de 3 % hasta 20 %",
        "C3": "Mas de 20 % hasta 30 %",
        "C4": "Mas de 30 % hasta 50 %",
        "C5": "Mas de 50 % hasta 80 %",
        "C6": "Mas de 80 %",
    }[category]


def _category_from_loss_percent(loss_percent: Decimal, *, decimal: DecimalRuntime) -> str:
    """Encasilla ``(E-R)/E`` en C1-C6."""
    if loss_percent <= decimal.decimal_cls("3"):
        return "C1"
    if loss_percent <= decimal.decimal_cls("20"):
        return "C2"
    if loss_percent <= decimal.decimal_cls("30"):
        return "C3"
    if loss_percent <= decimal.decimal_cls("50"):
        return "C4"
    if loss_percent <= decimal.decimal_cls("80"):
        return "C5"
    return "C6"


def _canonical_asset(value: object) -> str:
    """Normaliza tipo de bien de leasing."""
    asset = str(value).strip()
    if asset in {"inmobiliario", "no_inmobiliario"}:
        return asset
    raise CmfMappingError(f"Tipo de bien leasing no soportado: {asset!r}.")


def _pvb_bucket(value: Decimal) -> str:
    """Encasilla PVB en los tramos de leasing."""
    if value <= 40:
        return "pvb_le_40"
    if value <= 50:
        return "pvb_gt_40_le_50"
    if value <= 80:
        return "pvb_gt_50_le_80"
    if value <= 90:
        return "pvb_gt_80_le_90"
    return "pvb_gt_90"


def _student_type(value: object) -> str:
    """Normaliza tipo de crédito estudiantil."""
    loan_type = str(value).strip()
    if loan_type in {"cae", "corfo_otros"}:
        return loan_type
    raise CmfMappingError(f"Tipo de crédito estudiantil no soportado: {loan_type!r}.")


def _pi_ptvg_bucket(pdi_ptvg_bucket: str, row: Any) -> str:
    """Obtiene el tramo PTVG compatible con la fila PI."""
    if "ptvg_pi_bucket" in row.index:
        return str(row["ptvg_pi_bucket"]).strip()
    if pdi_ptvg_bucket == "sin_garantia":
        return "sin_garantia"
    if pdi_ptvg_bucket in {"con_garantia_ptvg_le_100", "con_garantia_ptvg_gt_100"}:
        return pdi_ptvg_bucket
    return "con_garantia_ptvg_le_100"


def _recourse_type(value: object) -> str:
    """Normaliza responsabilidad cedente de factoring."""
    recourse = str(value).strip()
    if recourse in {"sin_responsabilidad_cedente_o_generica", "con_responsabilidad_cedente"}:
        return recourse
    raise CmfMappingError(f"Tipo de responsabilidad cedente no soportado: {recourse!r}.")


def _consumer_product(value: object) -> str:
    """Normaliza producto de consumo a dimensión de matriz."""
    product = str(value).strip()
    mapped = _PRODUCT_ALIASES.get(product)
    if mapped is None:
        raise CmfMappingError(f"Producto de consumo no soportado: {product!r}.")
    return mapped


def _pvg_bucket_for_row(row: Any, *, decimal: DecimalRuntime) -> str:
    """Lee PVG directo o lo deriva desde saldo y valor de garantía hipotecaria."""
    if "pvg" in row.index:
        pvg = _decimal_from_value(row["pvg"], column="pvg", decimal=decimal)
    elif {"loan_balance", "mortgage_guarantee_value"} <= set(row.index):
        guarantee = _decimal_from_value(
            row["mortgage_guarantee_value"],
            column="mortgage_guarantee_value",
            decimal=decimal,
        )
        if guarantee == decimal.zero:
            raise CmfCalculationError("PVG no puede derivarse con garantía hipotecaria cero.")
        loan_balance = _decimal_from_value(
            row["loan_balance"],
            column="loan_balance",
            decimal=decimal,
        )
        pvg = loan_balance * decimal.hundred / guarantee
    else:
        raise CmfInputError("Vivienda exige columna pvg o loan_balance + mortgage_guarantee_value.")
    if pvg <= 40:
        return "pvg_le_40"
    if pvg <= 80:
        return "pvg_gt_40_le_80"
    if pvg <= 90:
        return "pvg_gt_80_le_90"
    return "pvg_gt_90"


def _source_reference(row: CmfMatrixRow) -> str:
    """Construye referencia interna a la fuente parametrizada."""
    return f"docs/normativa_cmf_parametros.md {row.source_ref}"


def _join_sources(rows: tuple[CmfMatrixRow, CmfMatrixRow]) -> str:
    """Une fuentes de filas PI/PDI preservando orden y sin duplicados."""
    sources: list[str] = []
    for row in rows:
        source = _source_reference(row)
        if source not in sources:
            sources.append(source)
    return "; ".join(sources)


def _join_source_texts(sources: tuple[str, ...]) -> str:
    """Une referencias ya construidas preservando orden y sin duplicados."""
    unique: list[str] = []
    for source in sources:
        if source not in unique:
            unique.append(source)
    return "; ".join(unique)


def _round_provision(
    value: Decimal,
    *,
    policy: str,
    decimal: DecimalRuntime,
) -> Decimal:
    """Aplica redondeo contable explícito sólo sobre la provisión publicable."""
    if policy == "none":
        return value
    quantum = decimal.decimal_cls("0.01") if policy == "currency_2dp" else decimal.decimal_cls("1")
    return value.quantize(quantum, rounding=decimal.rounding_half_up)


def _detail_row(
    record: CmfProvisionRecord,
    *,
    source_reference: str,
    matrix_version: str,
    ccf_percent: Decimal | None,
) -> dict[str, object]:
    """Convierte un record validado a la fila canónica de ``detail``."""
    return {
        "portfolio": record.portfolio,
        "method": record.method,
        "cmf_category": record.cmf_category,
        "matrix_id": record.matrix_id,
        "matrix_row_id": record.matrix_row_id,
        "direct_exposure_amount": record.direct_exposure_amount,
        "contingent_exposure_amount": record.contingent_exposure_amount,
        "exposure_amount": record.exposure_amount,
        "pd_source_value": record.pd_source_value,
        "pi_percent": record.pi_percent,
        "pdi_percent": record.pdi_percent,
        "pe_percent": record.pe_percent,
        "provision_amount": record.provision_amount,
        "guarantee_treatment": record.guarantee_treatment,
        "ccf_percent": ccf_percent,
        "warning_codes": record.warnings,
        "source_reference": source_reference,
        "matrix_version": matrix_version,
    }


def _summary_frame(
    records: list[CmfProvisionRecord],
    *,
    matrix_version: str,
    pd: Any,
) -> DataFrame:
    """Construye ``summary`` por cartera, método y categoría con orden canónico."""
    grouped: dict[tuple[str, str, str | None], list[CmfProvisionRecord]] = {}
    for record in records:
        key = (record.portfolio, record.method, record.cmf_category)
        grouped.setdefault(key, []).append(record)
    rows: list[dict[str, object]] = []
    index_values: list[str] = []
    for key in sorted(grouped, key=_summary_sort_key):
        portfolio, method, category = key
        bucket = grouped[key]
        total_exposure = sum(
            (record.exposure_amount for record in bucket),
            bucket[0].exposure_amount * 0,
        )
        total_provision = sum(
            (record.provision_amount for record in bucket),
            bucket[0].provision_amount * 0,
        )
        weighted_pe = (
            total_provision / total_exposure * 100 if total_exposure != 0 else total_exposure
        )
        rows.append(
            {
                "portfolio": portfolio,
                "method": method,
                "cmf_category": category,
                "n_rows": len(bucket),
                "total_exposure_amount": total_exposure,
                "total_provision_amount": total_provision,
                "weighted_pe_percent": weighted_pe,
                "matrix_version": matrix_version,
                "warning_codes": tuple(warning for record in bucket for warning in record.warnings),
            }
        )
        index_values.append(f"{portfolio}|{method}|{category or ''}")
    frame = pd.DataFrame(rows, columns=list(_SUMMARY_COLUMNS))
    frame.index = pd.Index(index_values, name="summary_id")
    return cast(DataFrame, frame)


def _summary_sort_key(key: tuple[str, str, str | None]) -> tuple[int, int, str, str]:
    """Ordena summary por cartera y categoría regulatoria."""
    portfolio, method, category = key
    portfolio_rank = _PORTFOLIO_ORDER.index(portfolio) if portfolio in _PORTFOLIO_ORDER else 999
    category_rank = _CATEGORIES_ORDER.index(category) if category in _CATEGORIES_ORDER else 999
    return (portfolio_rank, category_rank, method, category or "")


def _card(
    records: list[CmfProvisionRecord],
    *,
    as_of_date: str,
    matrix_bundle: CmfMatrixBundle,
    summary: DataFrame,
    decimal: DecimalRuntime,
) -> CmfProvisionCard:
    """Construye la card CMF agregada para governance/report."""
    total_exposure = sum((record.exposure_amount for record in records), decimal.zero)
    total_provision = sum((record.provision_amount for record in records), decimal.zero)
    portfolio_summaries = tuple(
        CmfPortfolioSummary(
            portfolio=str(portfolio),
            n_rows=len(bucket),
            total_exposure_amount=sum((record.exposure_amount for record in bucket), decimal.zero),
            total_provision_amount=sum(
                (record.provision_amount for record in bucket),
                decimal.zero,
            ),
            weighted_pe_percent=(
                sum((record.provision_amount for record in bucket), decimal.zero)
                / sum((record.exposure_amount for record in bucket), decimal.zero)
                * decimal.hundred
                if sum((record.exposure_amount for record in bucket), decimal.zero) != decimal.zero
                else decimal.zero
            ),
        )
        for portfolio, bucket in _records_by_portfolio(records)
    )
    sources = tuple(
        dict.fromkeys(
            f"docs/normativa_cmf_parametros.md {entry.source_ref}"
            for entry in matrix_bundle.manifest.matrices
            if entry.matrix_id in {record.matrix_id for record in records}
        )
    )
    return CmfProvisionCard(
        matrix_version=matrix_bundle.manifest.version,
        as_of_date=as_of_date,
        n_rows=len(records),
        total_exposure_amount=total_exposure,
        total_provision_amount=total_provision,
        portfolios=portfolio_summaries,
        regulatory_sources=sources,
        metric_sections={
            "cmf_b1_engine": {
                "matrix_sha256": matrix_bundle.manifest.yaml_sha256,
                "pe_consistency_tolerance_percent": _PE_CONSISTENCY_TOLERANCE_PERCENT,
                "summary_rows": len(summary.index),
                "scope": "b1_b3_aval_substitution_financial_guarantee_guardrails",
            }
        },
    )


def _records_by_portfolio(
    records: list[CmfProvisionRecord],
) -> tuple[tuple[str, tuple[CmfProvisionRecord, ...]], ...]:
    """Agrupa records por cartera preservando orden canónico."""
    grouped: dict[str, list[CmfProvisionRecord]] = {}
    for record in records:
        grouped.setdefault(record.portfolio, []).append(record)
    return tuple(
        (portfolio, tuple(grouped[portfolio]))
        for portfolio in sorted(
            grouped,
            key=lambda item: _PORTFOLIO_ORDER.index(item) if item in _PORTFOLIO_ORDER else 999,
        )
    )


def _emit_audit(
    audit: AuditSink | None,
    *,
    cfg: CmfProvisioningConfig,
    result: CmfProvisionResult,
) -> None:
    """Emitir una decisión compacta del cálculo si se inyectó sink."""
    if audit is None:
        return
    audit.emit(
        AuditEvent(
            kind="decision",
            step=None,
            payload={
                "regla": "cmf_b1_b3_engine",
                "umbral": {
                    "rounding": cfg.exposure.rounding,
                    "pe_tolerance_percent": _PE_CONSISTENCY_TOLERANCE_PERCENT,
                },
                "valor": {
                    "matrix_version": result.card.matrix_version,
                    "n_rows": result.card.n_rows,
                    "total_provision_amount": str(result.card.total_provision_amount),
                },
                "accion": "calcular_provision_cmf",
            },
            ts=datetime.now(UTC),
        )
    )
