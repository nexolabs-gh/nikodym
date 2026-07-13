"""Motor del **método interno** de provisiones del Capítulo B-1 de la CMF (SDD-28 §3.3/§4.1).

La norma (B-1 §3, Circular N° 2.346) dice, textualmente, que los bancos *"segmentarán a los
deudores en grupos homogéneos (…) asociando a cada grupo una determinada probabilidad de
incumplimiento y un porcentaje de recuperación basado en un análisis histórico fundamentado. El
monto de provisiones a constituir se obtendrá multiplicando el monto total de colocaciones del grupo
respectivo por los porcentajes de incumplimiento estimado y de pérdida dado el incumplimiento"*. Es
decir, para cada grupo homogéneo ``g``::

    provisión(g) = Exposición(g) · PD(g) · LGD(g)

y la norma admite también estimar **directamente** la tasa de pérdida esperada del grupo, sin
descomponerla (``method='direct_loss_rate'``). Ambos caminos están implementados: un enum declarado
sin ruta real degrada en silencio.

Decisiones de agregación (SDD-28 no las fija; se documentan porque un validador las pregunta):

* **PD y LGD del grupo se ponderan por exposición**, no por conteo. La norma aplica los porcentajes
  al *monto total de colocaciones del grupo*, así que el promedio simple sub-representaría a las
  operaciones grandes y la provisión del grupo dejaría de ser la pérdida esperada de su cartera.
* **``lgd.method='group_historical'`` usa la media SIMPLE** de la severidad observada del grupo y la
  aplica a todas sus operaciones: una severidad histórica no se pondera por la exposición *de hoy*.
  ``lgd.method='provided'`` conserva la LGD propia de cada operación y pondera por exposición.
* **Los grupos homogéneos viven DENTRO de una cartera** (la norma exige que la pérdida estimada
  guarde relación con el *tipo de cartera*): con ``grouping='score_band'`` los cuantiles de PD se
  calculan por cartera, y la llave de un grupo es ``(portfolio, group_id)``.
* **La provisión es una cifra del GRUPO.** El detalle por operación es el prorrateo de esa cifra por
  participación de exposición (reparto por resto mayor, exacto al centavo), no ``E·PD·LGD`` de la
  fila. Corolario que un validador pregunta: ``E(g)·PD(g)·LGD(g)`` **no** es ``Σ E_i·pd_i·lgd_i``;
  difieren en la covarianza PD-LGD *dentro* del grupo. La norma asocia a cada grupo **una** PD y
  **un** porcentaje de pérdida y multiplica por el *monto total de colocaciones del grupo*, así que
  el motor sigue la primera fórmula. Ambas coinciden exactamente cuando el grupo es de verdad
  homogéneo — y la brecha entre ellas es, precisamente, el diagnóstico de una mala agrupación.
* La aritmética contable es ``Decimal`` con precisión explícita: la cifra se compara contra la del
  método estándar, que también es ``Decimal``. Los cuantiles de banda sí usan ``float`` porque son
  un **ranking** (no entran en ninguna suma de dinero).

El módulo mantiene el import liviano: ``pandas`` se resuelve bajo demanda dentro de ``calculate``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import TYPE_CHECKING, Any, ClassVar, TypeAlias, cast

from nikodym.core.audit import AuditEvent
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.internal.config import InternalProvisioningConfig
from nikodym.provisioning.internal.exceptions import (
    InternalCalculationError,
    InternalInputError,
)
from nikodym.provisioning.internal.results import (
    DETAIL_COLUMNS,
    GROUP_COLUMNS,
    SUMMARY_COLUMNS,
    InternalProvisionCard,
    InternalProvisionRecord,
    InternalProvisionResult,
)

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["InternalProvisioningEngine"]

_INTERNAL_EXTRA_MESSAGE = (
    "InternalProvisioningEngine requiere pandas; instale las dependencias base."
)
_ZERO = Decimal("0")
_ONE = Decimal("1")
# Precisión de trabajo: los cocientes ponderados (PD y LGD del grupo) rara vez terminan, y una
# cartera bancaria en CLP roza los 12 dígitos enteros. 50 dígitos dejan margen de sobra bajo el
# redondeo contable final, y fijarla explícitamente hace la corrida reproducible entre máquinas.
_PRECISION = 50
_FALTA_DATO = "FALTA-DATO"
_BANDAS_COLAPSADAS = "BANDAS-COLAPSADAS"
_GRUPO_SIN_EXPOSICION = "GRUPO-SIN-EXPOSICION"
_PD_LGD = "pd_lgd"
_GROUP_HISTORICAL = "group_historical"
_SCORE_BAND = "score_band"
_QUANTUM_BY_POLICY: dict[str, Decimal | None] = {
    "none": None,
    "currency_2dp": Decimal("0.01"),
    "integer_currency": Decimal("1"),
}


class InternalProvisioningEngine:
    """Calcula la provisión del método interno por grupo homogéneo (B-1 §3)."""

    config_cls: ClassVar[type[InternalProvisioningConfig]] = InternalProvisioningConfig

    def __init__(self, config: InternalProvisioningConfig) -> None:
        """Recibe el config ya validado de la sección ``provisioning_internal``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> InternalProvisioningEngine:
        """Construye el motor desde ``NikodymConfig.provisioning_internal``."""
        if not isinstance(cfg, InternalProvisioningConfig):
            cfg = InternalProvisioningConfig.model_validate(cfg)
        return cls(cfg)

    def calculate(
        self,
        frame: DataFrame,
        *,
        pd_frame: DataFrame,
        as_of_date: str,
        audit: AuditSink | None = None,
    ) -> InternalProvisionResult:
        """Calcula detalle, grupos, resumen y card del método interno, sin consumir azar."""
        pandas = _import_pandas()
        cfg = self.config
        with localcontext() as context:
            context.prec = _PRECISION
            result = _calculate(cfg, frame, pd_frame=pd_frame, as_of_date=as_of_date, pandas=pandas)
        _emit_audit(audit, cfg=cfg, result=result)
        return result


@dataclass(frozen=True)
class _RowInput:
    """Fila de entrada ya convertida a ``Decimal`` y validada.

    ``severity`` unifica los dos métodos del B-1: es la **LGD** de la operación con
    ``method='pd_lgd'`` y la **tasa de pérdida esperada** con ``method='direct_loss_rate'``. Ambas
    viven en [0, 1] y ambas se agregan al grupo ponderando por exposición.
    """

    row_id: str
    portfolio: str
    exposure: Decimal
    pd_value: Decimal
    severity: Decimal
    group_key: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _GroupAggregate:
    """Grupo homogéneo agregado: la unidad de cálculo que describe la norma."""

    portfolio: str
    group_id: str
    positions: tuple[int, ...]
    total_exposure: Decimal
    pd_group: Decimal
    severity_group: Decimal
    expected_loss_rate: Decimal
    provision: Decimal
    warnings: tuple[str, ...]


def _calculate(
    cfg: InternalProvisioningConfig,
    frame: DataFrame,
    *,
    pd_frame: DataFrame,
    as_of_date: str,
    pandas: Any,
) -> InternalProvisionResult:
    """Ejecuta el cálculo completo dentro del contexto ``Decimal`` de precisión fija."""
    data = _as_dataframe(frame, pandas=pandas, artifact="frame")
    if len(data.index) == 0:
        raise InternalInputError(
            "El método interno exige al menos una operación: el frame de entrada está vacío."
        )
    pd_by_row = _pd_by_row(pd_frame, cfg=cfg, index=data.index, pandas=pandas)
    rows = _parse_rows(data, cfg=cfg, pd_by_row=pd_by_row, pandas=pandas)
    group_ids, group_warnings = _assign_groups(rows, cfg=cfg, pandas=pandas)
    aggregates = _aggregate_groups(rows, group_ids=group_ids, cfg=cfg, warnings=group_warnings)
    records = _records(rows, aggregates=aggregates, cfg=cfg)

    detail = _detail_frame(records, index=data.index, pandas=pandas)
    groups = _groups_frame(aggregates, cfg=cfg, pandas=pandas)
    summary = _summary_frame(aggregates, pandas=pandas)
    card = _card(rows, aggregates=aggregates, cfg=cfg, as_of_date=as_of_date)
    return InternalProvisionResult(
        detail=detail,
        groups=groups,
        summary=summary,
        records=tuple(records),
        card=card,
    )


# ─────────────────────────── entrada: PD, columnas y rangos ───────────────────────────


def _pd_by_row(
    pd_frame: DataFrame,
    *,
    cfg: InternalProvisioningConfig,
    index: Any,
    pandas: Any,
) -> dict[Any, Any]:
    """Indexa la PD por etiqueta de fila exigiendo cobertura completa de la cartera.

    Se resuelve por etiqueta explícita (nunca asignando una ``Series`` a una columna, que alinearía
    por índice y dejaría ``NaN`` en silencio) y se exige que el índice del artefacto de PD sea único
    y cubra todas las operaciones del frame.
    """
    source = _as_dataframe(
        pd_frame,
        pandas=pandas,
        artifact=f"{cfg.pd_source}.pd_frame",
    )
    if cfg.pd_column not in source.columns:
        raise InternalInputError(
            f"El artefacto de PD ('{cfg.pd_source}') debe contener la columna "
            f"pd_column='{cfg.pd_column}'; columnas observadas="
            f"{[str(column) for column in source.columns]}."
        )
    if bool(source.index.has_duplicates):
        raise InternalInputError(
            f"El artefacto de PD ('{cfg.pd_source}') tiene etiquetas duplicadas en el índice: "
            "no se puede asignar una PD única por operación."
        )
    values = cast(Any, source[cfg.pd_column]).to_dict()
    missing = [label for label in index.tolist() if label not in values]
    if missing:
        raise InternalInputError(
            f"El artefacto de PD ('{cfg.pd_source}') no cubre {len(missing)} operaciones del "
            f"frame; primeras faltantes={[str(label) for label in missing[:5]]}."
        )
    return cast(dict[Any, Any], values)


def _parse_rows(
    data: DataFrame,
    *,
    cfg: InternalProvisioningConfig,
    pd_by_row: dict[Any, Any],
    pandas: Any,
) -> list[_RowInput]:
    """Convierte cada operación a ``Decimal`` validando rangos y aplicando piso/techo de LGD."""
    severity_col = cfg.lgd.lgd_col if cfg.method == _PD_LGD else cast(str, cfg.loss_rate_col)
    required = [cfg.portfolio_col, cfg.exposure_col, severity_col]
    if cfg.grouping != _SCORE_BAND:
        required.append(cast(str, cfg.group_col))
    _require_columns(data, tuple(required))

    floor = Decimal(str(cfg.lgd.lgd_floor))
    cap = Decimal(str(cfg.lgd.lgd_cap))
    rows: list[_RowInput] = []
    for label, row in data.iterrows():
        row_id = str(label)
        warnings: list[str] = []
        exposure = _required_decimal(
            _decimal_or_none(
                row[cfg.exposure_col], column=cfg.exposure_col, row_id=row_id, pandas=pandas
            ),
            column=cfg.exposure_col,
            row_id=row_id,
            cfg=cfg,
            warnings=warnings,
        )
        if exposure < _ZERO:
            raise InternalInputError(
                f"La exposición no puede ser negativa: columna='{cfg.exposure_col}', "
                f"fila={row_id!r}, valor={exposure}."
            )
        pd_value = _unit_interval(
            _required_decimal(
                _decimal_or_none(
                    pd_by_row[label], column=cfg.pd_column, row_id=row_id, pandas=pandas
                ),
                column=cfg.pd_column,
                row_id=row_id,
                cfg=cfg,
                warnings=warnings,
            ),
            column=cfg.pd_column,
            row_id=row_id,
        )
        severity = _unit_interval(
            _required_decimal(
                _decimal_or_none(
                    row[severity_col], column=severity_col, row_id=row_id, pandas=pandas
                ),
                column=severity_col,
                row_id=row_id,
                cfg=cfg,
                warnings=warnings,
            ),
            column=severity_col,
            row_id=row_id,
        )
        if cfg.method == _PD_LGD:
            severity = min(max(severity, floor), cap)
        rows.append(
            _RowInput(
                row_id=row_id,
                portfolio=_text(
                    row[cfg.portfolio_col],
                    column=cfg.portfolio_col,
                    row_id=row_id,
                    pandas=pandas,
                ),
                exposure=exposure,
                pd_value=pd_value,
                severity=severity,
                group_key=(
                    ""
                    if cfg.grouping == _SCORE_BAND
                    else _text(
                        row[cast(str, cfg.group_col)],
                        column=cast(str, cfg.group_col),
                        row_id=row_id,
                        pandas=pandas,
                    )
                ),
                warnings=tuple(warnings),
            )
        )
    return rows


def _require_columns(data: DataFrame, columns: tuple[str, ...]) -> None:
    """Exige las columnas que el config declara, con un mensaje que nombra la que falta."""
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise InternalInputError(
            f"Faltan columnas exigidas por provisioning_internal: {missing}. "
            f"Columnas observadas={[str(column) for column in data.columns]}."
        )


def _decimal_or_none(
    value: object,
    *,
    column: str,
    row_id: str,
    pandas: Any,
) -> Decimal | None:
    """Convierte un escalar a ``Decimal`` finito; ``None`` señala falta de dato, no error."""
    if _is_missing(value, pandas):
        return None
    if isinstance(value, bool):
        raise InternalInputError(
            f"La columna '{column}' debe ser numérica, no booleana: fila={row_id!r}."
        )
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        observed = Decimal(text)
    except InvalidOperation as exc:
        raise InternalInputError(
            f"La columna '{column}' debe contener números compatibles con Decimal: "
            f"fila={row_id!r}, valor={value!r}."
        ) from exc
    if not observed.is_finite():
        raise InternalInputError(
            f"La columna '{column}' debe contener sólo valores finitos: "
            f"fila={row_id!r}, valor={value!r}."
        )
    return _ZERO if observed.is_zero() else observed


def _required_decimal(
    value: Decimal | None,
    *,
    column: str,
    row_id: str,
    cfg: InternalProvisioningConfig,
    warnings: list[str],
) -> Decimal:
    """Aplica la política ``fail_on_falta_dato``: abortar, o imputar cero dejando traza."""
    if value is not None:
        return value
    if cfg.fail_on_falta_dato:
        raise InternalInputError(
            f"Falta el dato de '{column}' en la fila {row_id!r}. Con "
            "fail_on_falta_dato=False se imputa cero y se traza en la card."
        )
    if _FALTA_DATO not in warnings:
        warnings.append(_FALTA_DATO)
    return _ZERO


def _unit_interval(value: Decimal, *, column: str, row_id: str) -> Decimal:
    """Exige una probabilidad o severidad en [0, 1]: fuera de rango levanta, no se clipa."""
    if value < _ZERO or value > _ONE:
        raise InternalInputError(
            f"La columna '{column}' debe estar en [0, 1]; no se clipa en silencio: "
            f"fila={row_id!r}, valor={value}."
        )
    return value


def _text(value: object, *, column: str, row_id: str, pandas: Any) -> str:
    """Lee texto obligatorio (cartera o grupo): un nulo no se puede imputar."""
    if _is_missing(value, pandas):
        raise InternalInputError(f"La columna '{column}' no puede ser nula en la fila {row_id!r}.")
    text = str(value).strip()
    if not text:
        raise InternalInputError(
            f"La columna '{column}' no puede estar vacía en la fila {row_id!r}."
        )
    return text


def _is_missing(value: object, pandas: Any) -> bool:
    """Detecta nulos escalares sin disparar ambigüedad sobre objetos tabulares."""
    try:
        return bool(pandas.isna(value))
    except (TypeError, ValueError):
        return False


# ─────────────────────────── grupos homogéneos ───────────────────────────


def _assign_groups(
    rows: list[_RowInput],
    *,
    cfg: InternalProvisioningConfig,
    pandas: Any,
) -> tuple[list[str], dict[tuple[str, str], tuple[str, ...]]]:
    """Forma los grupos homogéneos y devuelve el ``group_id`` de cada operación.

    Con ``grouping='score_band'`` las bandas son cuantiles de la PD calculados **dentro de cada
    cartera**. Con ``segment``/``provided`` el grupo lo trae ``group_col``: ambos modos comparten
    ruta de cálculo y se distinguen por la **procedencia declarada** del grupo, que queda en la card
    y en el audit-trail (es lo que un validador lee para saber de dónde salieron los grupos).
    """
    if cfg.grouping != _SCORE_BAND:
        return [row.group_key for row in rows], {}

    group_ids = [""] * len(rows)
    warnings: dict[tuple[str, str], tuple[str, ...]] = {}
    positions_by_portfolio: dict[str, list[int]] = {}
    for position, row in enumerate(rows):
        positions_by_portfolio.setdefault(row.portfolio, []).append(position)

    for portfolio, positions in positions_by_portfolio.items():
        codes, collapsed = _quantile_codes(
            [rows[position].pd_value for position in positions],
            n_bands=cfg.n_score_bands,
            pandas=pandas,
        )
        for position, code in zip(positions, codes, strict=True):
            group_ids[position] = _band_label(code)
        if collapsed:
            for code in sorted(set(codes)):
                warnings[(portfolio, _band_label(code))] = (_BANDAS_COLAPSADAS,)
    return group_ids, warnings


def _quantile_codes(
    pd_values: list[Decimal],
    *,
    n_bands: int,
    pandas: Any,
) -> tuple[list[int], bool]:
    """Asigna cada PD a su banda por cuantil; devuelve además si las bandas colapsaron.

    Los bordes se delegan a ``pandas.qcut`` con ``duplicates='drop'``: los empates de PD colapsan
    bordes repetidos y pueden producir **menos bandas de las pedidas**. Eso no se esconde: se
    devuelve ``collapsed=True`` y el motor marca cada banda con ``BANDAS-COLAPSADAS``. La conversión
    a ``float`` es deliberada y segura: la banda es un **ranking**, no entra en ninguna suma de
    dinero (esa aritmética es íntegramente ``Decimal``).
    """
    if len(set(pd_values)) < 2:
        return [0] * len(pd_values), True
    codes = pandas.qcut(
        pandas.Series([float(value) for value in pd_values]),
        q=n_bands,
        labels=False,
        duplicates="drop",
    )
    resolved = [int(code) for code in cast(Any, codes).tolist()]
    return resolved, len(set(resolved)) < n_bands


def _band_label(code: int) -> str:
    """Etiqueta estable y ordenable de una banda de score (``banda_01`` … ``banda_NN``)."""
    return f"banda_{code + 1:02d}"


# ─────────────────────────── agregación y provisión del grupo ───────────────────────────


def _aggregate_groups(
    rows: list[_RowInput],
    *,
    group_ids: list[str],
    cfg: InternalProvisioningConfig,
    warnings: dict[tuple[str, str], tuple[str, ...]],
) -> list[_GroupAggregate]:
    """Aplica ``provisión(g) = Exposición(g) · PD(g) · LGD(g)`` sobre cada grupo homogéneo."""
    buckets: dict[tuple[str, str], list[int]] = {}
    for position, group_id in enumerate(group_ids):
        buckets.setdefault((rows[position].portfolio, group_id), []).append(position)

    quantum = _QUANTUM_BY_POLICY[cfg.rounding]
    simple_mean_severity = cfg.method == _PD_LGD and cfg.lgd.method == _GROUP_HISTORICAL
    aggregates: list[_GroupAggregate] = []
    for key in sorted(buckets):
        portfolio, group_id = key
        positions = buckets[key]
        members = [rows[position] for position in positions]
        exposures = [member.exposure for member in members]
        total_exposure = sum(exposures, _ZERO)

        group_warnings = list(warnings.get(key, ()))
        if total_exposure == _ZERO:
            group_warnings.append(_GRUPO_SIN_EXPOSICION)
        for member in members:
            for warning in member.warnings:
                if warning not in group_warnings:
                    group_warnings.append(warning)

        pd_group = _weighted_mean(
            [member.pd_value for member in members], exposures, total_exposure
        )
        severities = [member.severity for member in members]
        severity_group = (
            _simple_mean(severities)
            if simple_mean_severity
            else _weighted_mean(severities, exposures, total_exposure)
        )
        expected_loss_rate = pd_group * severity_group if cfg.method == _PD_LGD else severity_group
        aggregates.append(
            _GroupAggregate(
                portfolio=portfolio,
                group_id=group_id,
                positions=tuple(positions),
                total_exposure=total_exposure,
                pd_group=pd_group,
                severity_group=severity_group,
                expected_loss_rate=expected_loss_rate,
                provision=_round(total_exposure * expected_loss_rate, quantum),
                warnings=tuple(group_warnings),
            )
        )
    return aggregates


def _weighted_mean(values: list[Decimal], weights: list[Decimal], total: Decimal) -> Decimal:
    """Media ponderada por exposición; sin exposición cae a la media simple (grupo con provisión 0).

    Un grupo cuya exposición total es cero no tiene ponderadores: su provisión es cero de todos
    modos, y publicar la media simple de su PD/LGD conserva la caracterización del grupo en vez de
    inventar un cero.
    """
    if total == _ZERO:
        return _simple_mean(values)
    weighted = sum((value * weight for value, weight in zip(values, weights, strict=True)), _ZERO)
    return weighted / total


def _simple_mean(values: list[Decimal]) -> Decimal:
    """Media simple: la severidad histórica de un grupo no se pondera por la exposición de hoy."""
    return sum(values, _ZERO) / Decimal(len(values))


def _round(value: Decimal, quantum: Decimal | None) -> Decimal:
    """Aplica el redondeo contable explícito declarado en el config."""
    if quantum is None:
        return value
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _allocate(total: Decimal, weights: list[Decimal], quantum: Decimal | None) -> list[Decimal]:
    """Reparte la provisión del grupo entre sus operaciones, proporcional a la exposición.

    Con redondeo contable el prorrateo se cierra por **resto mayor** (Hare): cada operación recibe
    su parte truncada al céntimo y los céntimos sobrantes van a las de mayor resto (desempate por
    orden de entrada, determinista). Así ``Σ detalle == provisión(g)`` **exactamente**, que es la
    identidad que un validador cuadra primero.
    """
    total_weight = sum(weights, _ZERO)
    if total_weight == _ZERO or total == _ZERO:
        return [_ZERO for _ in weights]

    exact = [total * weight / total_weight for weight in weights]
    if quantum is None:
        allocations = list(exact)
        allocations[-1] = total - sum(allocations[:-1], _ZERO)
        return allocations

    allocations = [value.quantize(quantum, rounding=ROUND_DOWN) for value in exact]
    remainder = total - sum(allocations, _ZERO)
    order = sorted(
        range(len(weights)),
        key=lambda position: (-(exact[position] - allocations[position]), position),
    )
    position_index = 0
    while remainder > _ZERO and position_index < len(order):
        allocations[order[position_index]] += quantum
        remainder -= quantum
        position_index += 1
    if sum(allocations, _ZERO) != total:
        raise InternalCalculationError(
            "El prorrateo de la provisión del grupo no cuadra con su total: "
            f"total={total}, repartido={sum(allocations, _ZERO)}, quantum={quantum}."
        )
    return allocations


# ─────────────────────────── artefactos publicados ───────────────────────────


def _records(
    rows: list[_RowInput],
    *,
    aggregates: list[_GroupAggregate],
    cfg: InternalProvisioningConfig,
) -> list[InternalProvisionRecord]:
    """Construye el registro por operación con la provisión del grupo ya prorrateada."""
    quantum = _QUANTUM_BY_POLICY[cfg.rounding]
    is_pd_lgd = cfg.method == _PD_LGD
    use_group_severity = is_pd_lgd and cfg.lgd.method == _GROUP_HISTORICAL
    by_position: dict[int, InternalProvisionRecord] = {}
    for aggregate in aggregates:
        members = [rows[position] for position in aggregate.positions]
        allocations = _allocate(
            aggregate.provision,
            [member.exposure for member in members],
            quantum,
        )
        for position, member, allocation in zip(
            aggregate.positions, members, allocations, strict=True
        ):
            severity = aggregate.severity_group if use_group_severity else member.severity
            by_position[position] = InternalProvisionRecord(
                row_id=member.row_id,
                portfolio=member.portfolio,
                group_id=aggregate.group_id,
                exposure_amount=member.exposure,
                pd=member.pd_value,
                lgd=severity if is_pd_lgd else None,
                loss_rate=member.pd_value * severity if is_pd_lgd else member.severity,
                provision_amount=allocation,
                warnings=(*member.warnings, *_group_only_warnings(aggregate, member)),
            )
    return [by_position[position] for position in range(len(rows))]


def _group_only_warnings(aggregate: _GroupAggregate, member: _RowInput) -> tuple[str, ...]:
    """Propaga a la operación los avisos que nacieron en su grupo, sin duplicar los propios."""
    return tuple(warning for warning in aggregate.warnings if warning not in member.warnings)


def _detail_frame(
    records: list[InternalProvisionRecord],
    *,
    index: Any,
    pandas: Any,
) -> DataFrame:
    """Arma ``detail`` preservando el orden y el índice de las operaciones de entrada."""
    frame = pandas.DataFrame(
        [
            {
                "row_id": record.row_id,
                "portfolio": record.portfolio,
                "group_id": record.group_id,
                "exposure_amount": record.exposure_amount,
                "pd": record.pd,
                "lgd": record.lgd,
                "loss_rate": record.loss_rate,
                "provision_amount": record.provision_amount,
                "warning_codes": record.warnings,
            }
            for record in records
        ],
        columns=list(DETAIL_COLUMNS),
    )
    frame.index = pandas.Index(index.tolist(), name=index.name)
    return cast(DataFrame, frame)


def _groups_frame(
    aggregates: list[_GroupAggregate],
    *,
    cfg: InternalProvisioningConfig,
    pandas: Any,
) -> DataFrame:
    """Arma ``groups``: una fila por grupo homogéneo, la tabla que la norma describe."""
    is_pd_lgd = cfg.method == _PD_LGD
    frame = pandas.DataFrame(
        [
            {
                "group_id": aggregate.group_id,
                "portfolio": aggregate.portfolio,
                "n_operations": len(aggregate.positions),
                "total_exposure": aggregate.total_exposure,
                "pd_group": aggregate.pd_group,
                "lgd_group": aggregate.severity_group if is_pd_lgd else None,
                "expected_loss_rate": aggregate.expected_loss_rate,
                "provision_amount": aggregate.provision,
                "warning_codes": aggregate.warnings,
            }
            for aggregate in aggregates
        ],
        columns=list(GROUP_COLUMNS),
    )
    frame.index = pandas.Index(
        [f"{aggregate.portfolio}|{aggregate.group_id}" for aggregate in aggregates],
        name="group_key",
    )
    return cast(DataFrame, frame)


def _summary_frame(aggregates: list[_GroupAggregate], *, pandas: Any) -> DataFrame:
    """Arma ``summary``: el agregado por cartera regulatoria."""
    rows: list[dict[str, object]] = []
    index: list[str] = []
    for portfolio in sorted({aggregate.portfolio for aggregate in aggregates}):
        bucket = [aggregate for aggregate in aggregates if aggregate.portfolio == portfolio]
        total_exposure = sum((aggregate.total_exposure for aggregate in bucket), _ZERO)
        total_provision = sum((aggregate.provision for aggregate in bucket), _ZERO)
        warnings: list[str] = []
        for aggregate in bucket:
            for warning in aggregate.warnings:
                if warning not in warnings:
                    warnings.append(warning)
        rows.append(
            {
                "portfolio": portfolio,
                "n_groups": len(bucket),
                "n_operations": sum(len(aggregate.positions) for aggregate in bucket),
                "total_exposure": total_exposure,
                "total_provision": total_provision,
                "weighted_expected_loss_rate": (
                    total_provision / total_exposure if total_exposure != _ZERO else _ZERO
                ),
                "warning_codes": tuple(warnings),
            }
        )
        index.append(portfolio)
    frame = pandas.DataFrame(rows, columns=list(SUMMARY_COLUMNS))
    frame.index = pandas.Index(index, name="portfolio_id")
    return cast(DataFrame, frame)


def _card(
    rows: list[_RowInput],
    *,
    aggregates: list[_GroupAggregate],
    cfg: InternalProvisioningConfig,
    as_of_date: str,
) -> InternalProvisionCard:
    """Construye la card del método interno para governance, orquestador y report."""
    total_exposure = sum((row.exposure for row in rows), _ZERO)
    total_provision = sum((aggregate.provision for aggregate in aggregates), _ZERO)
    warnings: list[str] = []
    for aggregate in aggregates:
        for warning in aggregate.warnings:
            if warning not in warnings:
                warnings.append(warning)
    groups_by_portfolio: dict[str, int] = {}
    for aggregate in aggregates:
        groups_by_portfolio[aggregate.portfolio] = (
            groups_by_portfolio.get(aggregate.portfolio, 0) + 1
        )
    return InternalProvisionCard(
        as_of_date=as_of_date,
        method=cfg.method,
        grouping=cfg.grouping,
        pd_source=cfg.pd_source,
        n_groups=len(aggregates),
        n_rows=len(rows),
        total_exposure=total_exposure,
        total_internal_provision=total_provision,
        falta_dato=tuple(row.row_id for row in rows if _FALTA_DATO in row.warnings),
        metric_sections={
            "provisioning_internal": {
                "norma": (
                    "CMF Cap. B-1 §3 (Circular N° 2.346): provisión = colocaciones del grupo · "
                    "PD estimada · pérdida dado el incumplimiento."
                ),
                "method": cfg.method,
                "grouping": cfg.grouping,
                "n_score_bands": cfg.n_score_bands if cfg.grouping == _SCORE_BAND else None,
                "lgd_method": cfg.lgd.method if cfg.method == _PD_LGD else None,
                "pd_aggregation": "exposure_weighted",
                "rounding": cfg.rounding,
                "groups_by_portfolio": dict(sorted(groups_by_portfolio.items())),
                "total_expected_loss_rate": str(
                    total_provision / total_exposure if total_exposure != _ZERO else _ZERO
                ),
                "warning_codes": tuple(warnings),
            }
        },
    )


# ─────────────────────────── infraestructura ───────────────────────────


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_INTERNAL_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, *, pandas: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular antes de leerlo."""
    if isinstance(value, pandas.DataFrame):
        return cast(DataFrame, value)
    raise InternalInputError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _emit_audit(
    audit: AuditSink | None,
    *,
    cfg: InternalProvisioningConfig,
    result: InternalProvisionResult,
) -> None:
    """Emitir la decisión compacta del cálculo si se inyectó un sink."""
    if audit is None:
        return
    audit.emit(
        AuditEvent(
            kind="decision",
            step=None,
            payload={
                "regla": "internal_b1_engine",
                "umbral": {
                    "method": cfg.method,
                    "grouping": cfg.grouping,
                    "lgd_method": cfg.lgd.method,
                    "rounding": cfg.rounding,
                },
                "valor": {
                    "n_groups": result.card.n_groups,
                    "n_rows": result.card.n_rows,
                    "total_exposure": str(result.card.total_exposure),
                    "total_internal_provision": str(result.card.total_internal_provision),
                },
                "accion": "calcular_provision_interna",
            },
            ts=datetime.now(UTC),
        )
    )
