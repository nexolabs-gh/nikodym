"""Particiones deterministas para la capa ``data`` (SDD-02 §4/§7).

``Partitioner`` asigna cada observación etiquetada a
``desarrollo``/``holdout``/``oot``/``fuera_de_modelo`` y agrega el rol booleano
``ttd``. La identidad de partición depende de ``root_seed`` + índice de fila mediante
``blake2b`` estable, nunca del orden posicional del ``DataFrame`` ni del estado del
``Generator``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, TypeAlias, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.audit import AuditEvent, AuditSink
from nikodym.core.exceptions import ConfigError, DataValidationError
from nikodym.data.config import (
    CohortSplitConfig,
    PartitionConfig,
    RandomSplitConfig,
    TemporalSplitConfig,
)
from nikodym.data.target import LabeledFrame

__all__ = ["Partition", "PartitionResult", "Partitioner"]

PARTITION_COL: Final = "partition"
TTD_COL: Final = "ttd"
MODELABLE_STATUS: Final = ("bueno", "malo")
NON_MODELABLE_STATUS: Final = ("indeterminado", "excluido")
STATUS_VALUES: Final = (*MODELABLE_STATUS, *NON_MODELABLE_STATUS)
_HASH_PERSON: Final = b"nikodym"
_UINT64_DENOMINATOR: Final = 2**64

StrategyConfig: TypeAlias = TemporalSplitConfig | RandomSplitConfig | CohortSplitConfig
Splitter: TypeAlias = Callable[[pd.DataFrame, StrategyConfig, int, np.random.Generator], pd.Series]


class Partition(StrEnum):
    """Particiones disjuntas de modelado y bolsa explícita fuera de modelo."""

    DESARROLLO = "desarrollo"
    HOLDOUT = "holdout"
    OOT = "oot"
    FUERA_DE_MODELO = "fuera_de_modelo"


class PartitionResult(BaseModel):
    """Resultado auditable de asignar particiones y rol TTD."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    frame: pd.DataFrame
    partition_col: str = PARTITION_COL
    ttd_col: str = TTD_COL
    sizes: dict[str, int]
    bad_rates: dict[str, float]
    strategy_used: str


class Partitioner:
    """Asigna particiones Dev/HO/OOT de forma estable por observación."""

    def __init__(self, config: PartitionConfig) -> None:
        """Construye el particionador con ``DataConfig.partition``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: PartitionConfig) -> Partitioner:
        """Construye un particionador desde ``PartitionConfig``."""
        return cls(cfg)

    def split(
        self,
        lf: LabeledFrame,
        *,
        root_seed: int,
        rng: np.random.Generator,
        audit: AuditSink | None = None,
    ) -> PartitionResult:
        """Particiona un ``LabeledFrame`` sin mutar el frame de entrada.

        Parameters
        ----------
        lf : LabeledFrame
            Resultado de ``TargetDefinition.apply`` con columnas target y ``label_status``.
        root_seed : int
            Semilla raíz cruda: ancla la identidad estable por observación.
        rng : numpy.random.Generator
            Generador derivado por ``core``; reservado para sorteos auxiliares deterministas.
        audit : AuditSink or None
            Sumidero opcional para emitir decisiones de estrategia y resumen.

        Returns
        -------
        PartitionResult
            Copia del frame con ``partition`` categórico y ``ttd`` booleano.

        Raises
        ------
        ConfigError
            Si la estrategia no existe en el factory local o su config es inconsistente.
        DataValidationError
            Si faltan columnas, hay particiones vacías o se viola el piso de malos.
        """
        _validate_labeled_frame(lf)
        _validate_output_columns(lf.frame)

        frame = lf.frame.copy(deep=True)
        modelable_mask = _modelable_mask(frame, lf.target_col, lf.status_col)
        modelable_frame = frame.loc[modelable_mask]

        strategy = self.config.strategy
        splitter = _SPLITTERS.get(strategy.type)
        if splitter is None:
            raise ConfigError(
                f"Estrategia de partición desconocida en factory local: type='{strategy.type}'."
            )

        assigned = pd.Series(
            Partition.FUERA_DE_MODELO.value,
            index=frame.index,
            dtype="object",
        )
        if not modelable_frame.empty:
            assigned.loc[modelable_frame.index] = splitter(
                modelable_frame, strategy, root_seed, rng
            )

        frame[PARTITION_COL] = pd.Categorical(
            assigned,
            categories=[partition.value for partition in Partition],
        )
        frame[TTD_COL] = _ttd_mask(frame[PARTITION_COL], self.config.ttd_includes_excluded)

        sizes = _partition_sizes(frame[PARTITION_COL])
        bad_counts = _bad_counts(frame, lf.target_col)
        bad_rates = _bad_rates(sizes, bad_counts)
        _validate_non_empty_partitions(sizes, self.config.strategy)
        _validate_min_bads(
            sizes,
            bad_counts,
            self.config.min_bads_per_partition,
            strategy.type,
        )

        result = PartitionResult(
            frame=frame,
            sizes=sizes,
            bad_rates=bad_rates,
            strategy_used=strategy.type,
        )
        _emit_audit(
            audit,
            strategy_used=strategy.type,
            sizes=sizes,
            bad_rates=bad_rates,
            fuera_de_modelo=sizes[Partition.FUERA_DE_MODELO.value],
        )
        return result

    def suggest(self, lf: LabeledFrame) -> PartitionConfig:
        """Sugiere una ``PartitionConfig`` editable según señales temporales simples."""
        frame = lf.frame
        date_col = _first_datetime_column(frame)
        if date_col is not None:
            dates = frame[date_col].dropna().sort_values(kind="mergesort")
            position = min(len(dates) - 1, max(0, int(np.floor((len(dates) - 1) * 0.8))))
            oot_from = cast(pd.Timestamp, dates.iloc[position]).date().isoformat()
            return _suggested_config(
                self.config,
                TemporalSplitConfig(date_col=date_col, oot_from=oot_from),
            )

        cohort_col = _first_cohort_column(frame)
        if cohort_col is not None:
            cohorts = sorted(str(value) for value in frame[cohort_col].dropna().unique())
            oot_cohorts = tuple(cohorts[-2:] if len(cohorts) > 1 else cohorts[-1:])
            return _suggested_config(
                self.config,
                CohortSplitConfig(cohort_col=cohort_col, oot_cohorts=oot_cohorts),
            )

        return _suggested_config(
            self.config,
            RandomSplitConfig(stratify_by=lf.target_col),
        )


def _split_temporal(
    frame: pd.DataFrame,
    strategy: StrategyConfig,
    root_seed: int,
    rng: np.random.Generator,
) -> pd.Series:
    """Aplica OOT por corte temporal y Dev/HO por hash dentro del período in-time."""
    del rng
    if not isinstance(strategy, TemporalSplitConfig):  # pragma: no cover
        raise ConfigError("Factory de partición temporal recibió una config incompatible.")

    _validate_datetime_column(frame, strategy.date_col)
    dates = frame[strategy.date_col]
    if dates.isna().any():
        raise DataValidationError(
            "La partición temporal requiere fechas no nulas en filas modelables: "
            f"columna='{strategy.date_col}'."
        )

    cutoff = _coerce_cutoff(strategy.oot_from, dates)
    oot_mask = dates.ge(cutoff).fillna(False).astype("bool")
    in_time = ~oot_mask
    assignments = pd.Series(Partition.DESARROLLO.value, index=frame.index, dtype="object")
    assignments.loc[oot_mask] = Partition.OOT.value
    holdout_mask = in_time & (_uniform_by_index(frame.index, root_seed) < strategy.holdout_fraction)
    assignments.loc[holdout_mask] = Partition.HOLDOUT.value
    _validate_temporal_precedence(dates, assignments)
    return assignments


def _split_random(
    frame: pd.DataFrame,
    strategy: StrategyConfig,
    root_seed: int,
    rng: np.random.Generator,
) -> pd.Series:
    """Aplica fracciones Dev/HO/OOT con identidad estable por índice."""
    del rng
    if not isinstance(strategy, RandomSplitConfig):  # pragma: no cover - protegido por _SPLITTERS.
        raise ConfigError("Factory de partición random recibió una config incompatible.")

    if strategy.stratify_by is not None:
        if strategy.stratify_by not in frame.columns:
            raise DataValidationError(
                "La estrategia random declara stratify_by sobre una columna inexistente: "
                f"columna='{strategy.stratify_by}'."
            )
        return _split_random_stratified(frame, strategy, root_seed)

    uniforms = _uniform_by_index(frame.index, root_seed)
    holdout_cut = strategy.dev_fraction + strategy.holdout_fraction
    assignments = pd.Series(Partition.OOT.value, index=frame.index, dtype="object")
    assignments.loc[uniforms < holdout_cut] = Partition.HOLDOUT.value
    assignments.loc[uniforms < strategy.dev_fraction] = Partition.DESARROLLO.value
    return assignments


def _split_cohort(
    frame: pd.DataFrame,
    strategy: StrategyConfig,
    root_seed: int,
    rng: np.random.Generator,
) -> pd.Series:
    """Aplica OOT por cohorte reservada y Dev/HO por hash en las cohortes in-time."""
    del rng
    if not isinstance(strategy, CohortSplitConfig):  # pragma: no cover - protegido por _SPLITTERS.
        raise ConfigError("Factory de partición cohort recibió una config incompatible.")
    if strategy.cohort_col not in frame.columns:
        raise DataValidationError(
            "La estrategia cohort referencia una columna inexistente: "
            f"columna='{strategy.cohort_col}'."
        )

    oot_mask = frame[strategy.cohort_col].isin(strategy.oot_cohorts).fillna(False).astype("bool")
    in_time = ~oot_mask
    assignments = pd.Series(Partition.DESARROLLO.value, index=frame.index, dtype="object")
    assignments.loc[oot_mask] = Partition.OOT.value
    holdout_mask = in_time & (_uniform_by_index(frame.index, root_seed) < strategy.holdout_fraction)
    assignments.loc[holdout_mask] = Partition.HOLDOUT.value
    return assignments


def _split_random_stratified(
    frame: pd.DataFrame, strategy: RandomSplitConfig, root_seed: int
) -> pd.Series:
    """Asigna fracciones por estrato con umbrales estables por observación."""
    assert strategy.stratify_by is not None
    assignments = pd.Series(index=frame.index, dtype="object")
    uniforms = _uniform_by_index(frame.index, root_seed)
    holdout_cut = strategy.dev_fraction + strategy.holdout_fraction

    for _, group in frame.groupby(strategy.stratify_by, dropna=False, sort=False, observed=False):
        group_uniforms = uniforms.loc[group.index]
        assignments.loc[group.index] = Partition.OOT.value
        assignments.loc[group_uniforms[group_uniforms < holdout_cut].index] = (
            Partition.HOLDOUT.value
        )
        assignments.loc[group_uniforms[group_uniforms < strategy.dev_fraction].index] = (
            Partition.DESARROLLO.value
        )

    return assignments


def _validate_labeled_frame(lf: LabeledFrame) -> None:
    """Valida columnas estructurales del resultado de target."""
    missing = [
        column for column in (lf.target_col, lf.status_col) if column not in lf.frame.columns
    ]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise DataValidationError(
            f"El LabeledFrame no contiene columna(s) requeridas para particionar: {joined}."
        )

    observed = set(lf.frame[lf.status_col].dropna().astype(str))
    invalid = sorted(observed - set(STATUS_VALUES))
    if invalid:
        joined = ", ".join(f"'{value}'" for value in invalid)
        raise DataValidationError(
            f"El LabeledFrame contiene label_status fuera del contrato de data: {joined}."
        )


def _validate_output_columns(df: pd.DataFrame) -> None:
    """Evita sobrescribir columnas estructurales del cliente."""
    collisions = [column for column in (PARTITION_COL, TTD_COL) if column in df.columns]
    if collisions:
        joined = ", ".join(f"'{column}'" for column in collisions)
        raise DataValidationError(
            "La partición intentaría sobrescribir columna(s) existentes: "
            f"{joined}. Remueva esas columnas antes de particionar."
        )


def _modelable_mask(frame: pd.DataFrame, target_col: str, status_col: str) -> pd.Series:
    """Determina filas elegibles por estado bueno/malo y target no nulo."""
    status_modelable = frame[status_col].astype(str).isin(MODELABLE_STATUS)
    target_present = frame[target_col].notna()
    return (status_modelable & target_present).fillna(False).astype("bool")


def _validate_datetime_column(frame: pd.DataFrame, column: str) -> None:
    """Valida existencia y dtype datetime para estrategia temporal."""
    if column not in frame.columns:
        raise DataValidationError(
            f"La estrategia temporal referencia una columna inexistente: columna='{column}'."
        )
    if not pd.api.types.is_datetime64_any_dtype(frame[column].dtype):
        raise DataValidationError(
            "La estrategia temporal requiere una columna datetime antes de comparar el corte OOT; "
            f"columna='{column}', dtype={frame[column].dtype}."
        )


def _coerce_cutoff(oot_from: str, dates: pd.Series) -> pd.Timestamp:
    """Parsea ``oot_from`` y alinea zona horaria con la serie observada."""
    try:
        cutoff = pd.Timestamp(oot_from)
    except ValueError as exc:
        raise ConfigError(
            "La estrategia temporal declara oot_from inválido; use una fecha ISO 8601: "
            f"oot_from='{oot_from}'."
        ) from exc

    timezone = getattr(dates.dt, "tz", None)
    if timezone is not None and cutoff.tzinfo is None:
        return cutoff.tz_localize(timezone)
    if timezone is None and cutoff.tzinfo is not None:
        return cutoff.tz_convert(None)
    return cutoff


def _validate_temporal_precedence(dates: pd.Series, assignments: pd.Series) -> None:
    """Verifica que Dev/HO precedan estrictamente a OOT."""
    oot_dates = dates.loc[assignments == Partition.OOT.value]
    in_time_dates = dates.loc[
        assignments.isin([Partition.DESARROLLO.value, Partition.HOLDOUT.value])
    ]
    if oot_dates.empty or in_time_dates.empty:
        return
    if in_time_dates.max() >= oot_dates.min():
        raise DataValidationError(
            "La partición temporal violó el orden esperado: "
            "las fechas de desarrollo/holdout deben preceder al OOT."
        )


def _uniform_by_index(index: pd.Index, root_seed: int) -> pd.Series:
    """Genera ``uniform01`` estable a partir de ``root_seed`` y el índice de observación."""
    values = [_stable_uniform(root_seed, value) for value in index]
    return pd.Series(values, index=index, dtype="float64")


def _stable_uniform(root_seed: int, index_value: object) -> float:
    """Convierte ``blake2b(f'{root_seed}:{idx}')`` en un float de ``[0, 1)``."""
    token = f"{root_seed}:{_stable_index_token(index_value)}".encode()
    digest = hashlib.blake2b(token, digest_size=8, person=_HASH_PERSON).digest()
    integer = int.from_bytes(digest, byteorder="little", signed=False)
    return integer / _UINT64_DENOMINATOR


def _stable_index_token(value: object) -> str:
    """Serializa índices para hashing estable y normaliza ``-0.0`` a ``0.0``."""
    if isinstance(value, tuple):
        return "(" + ",".join(_stable_index_token(item) for item in value) + ")"
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        if numeric == 0.0:
            return "0.0"
        return repr(numeric)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _ttd_mask(partitions: pd.Series, includes_excluded: bool) -> pd.Series:
    """Construye el rol TTD superpuesto según la política configurada."""
    if includes_excluded:
        return pd.Series(True, index=partitions.index, dtype=bool)
    return partitions.ne(Partition.FUERA_DE_MODELO.value).fillna(False).astype("bool")


def _partition_sizes(partitions: pd.Series) -> dict[str, int]:
    """Cuenta filas por cada valor de ``Partition`` conservando claves explícitas."""
    return {partition.value: int(partitions.eq(partition.value).sum()) for partition in Partition}


def _bad_counts(frame: pd.DataFrame, target_col: str) -> dict[str, int]:
    """Cuenta malos por partición a partir de ``target == 1``."""
    bad_mask = frame[target_col].eq(1).fillna(False).astype("bool")
    return {
        partition.value: int((frame[PARTITION_COL].eq(partition.value) & bad_mask).sum())
        for partition in Partition
    }


def _bad_rates(sizes: Mapping[str, int], bad_counts: Mapping[str, int]) -> dict[str, float]:
    """Calcula tasa de malos, con ``0.0`` cuando el denominador es cero."""
    return {
        partition.value: bad_counts[partition.value] / sizes[partition.value]
        if sizes[partition.value] > 0
        else 0.0
        for partition in Partition
    }


def _validate_non_empty_partitions(sizes: Mapping[str, int], strategy: StrategyConfig) -> None:
    """Falla si una partición requerida por la estrategia quedó vacía."""
    required = _required_model_partitions(strategy)
    empty = [partition for partition in required if sizes[partition.value] == 0]
    if empty:
        joined = ", ".join(partition.value for partition in empty)
        raise DataValidationError(
            "La estrategia de partición produjo partición(es) vacía(s): "
            f"{joined}. Revise cortes/fracciones o amplíe la muestra."
        )


def _required_model_partitions(strategy: StrategyConfig) -> tuple[Partition, ...]:
    """Lista particiones que deben existir para la estrategia declarada."""
    if isinstance(strategy, RandomSplitConfig):
        pairs = (
            (Partition.DESARROLLO, strategy.dev_fraction),
            (Partition.HOLDOUT, strategy.holdout_fraction),
            (Partition.OOT, strategy.oot_fraction),
        )
        return tuple(partition for partition, fraction in pairs if fraction > 0.0)
    if isinstance(strategy, TemporalSplitConfig):
        values = [Partition.DESARROLLO, Partition.OOT]
        if strategy.holdout_fraction > 0.0:
            values.append(Partition.HOLDOUT)
        return tuple(values)
    values = [Partition.DESARROLLO, Partition.OOT]
    assert isinstance(strategy, CohortSplitConfig)
    if strategy.holdout_fraction > 0.0:
        values.append(Partition.HOLDOUT)
    return tuple(values)


def _validate_min_bads(
    sizes: Mapping[str, int],
    bad_counts: Mapping[str, int],
    min_bads_per_partition: int,
    strategy_type: str,
) -> None:
    """Verifica el piso de malos por partición evaluable."""
    if min_bads_per_partition == 0:
        return

    violations = [
        (partition, bad_counts[partition.value])
        for partition in (Partition.DESARROLLO, Partition.HOLDOUT, Partition.OOT)
        if sizes[partition.value] > 0 and bad_counts[partition.value] < min_bads_per_partition
    ]
    if violations:
        details = ", ".join(f"{partition.value}={observed}" for partition, observed in violations)
        raise DataValidationError(
            "Piso de malos por partición no alcanzado: "
            f"estrategia='{strategy_type}', mínimo={min_bads_per_partition}, observado={details}. "
            "Reduzca particiones, baje el piso o amplíe la ventana/muestra."
        )


def _first_datetime_column(frame: pd.DataFrame) -> str | None:
    """Encuentra una columna datetime con al menos dos fechas distintas."""
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_datetime64_any_dtype(series.dtype) and series.dropna().nunique() >= 2:
            return str(column)
    return None


def _first_cohort_column(frame: pd.DataFrame) -> str | None:
    """Encuentra una columna plausible de cohorte/vintage para sugerencias editables."""
    candidates = {"cohort", "cohorte", "vintage", "anada", "añada"}
    for column in frame.columns:
        normalized = str(column).lower()
        if normalized in candidates and frame[column].dropna().nunique() >= 1:
            return str(column)
    return None


def _suggested_config(current: PartitionConfig, strategy: StrategyConfig) -> PartitionConfig:
    """Preserva opciones globales al proponer una estrategia editable."""
    return PartitionConfig(
        strategy=strategy,
        ttd_includes_excluded=current.ttd_includes_excluded,
        min_bads_per_partition=current.min_bads_per_partition,
    )


def _emit_audit(
    audit: AuditSink | None,
    *,
    strategy_used: str,
    sizes: Mapping[str, int],
    bad_rates: Mapping[str, float],
    fuera_de_modelo: int,
) -> None:
    """Emitir decisiones de estrategia, exclusiones y resumen de particiones."""
    _log_decision(
        audit,
        regla="partition_strategy",
        umbral=strategy_used,
        valor=strategy_used,
        accion="aplicar_estrategia",
    )
    if fuera_de_modelo > 0:
        _log_decision(
            audit,
            regla="fuera_de_modelo",
            umbral=NON_MODELABLE_STATUS,
            valor=fuera_de_modelo,
            accion="excluir_de_modelado",
        )
    _log_decision(
        audit,
        regla="partition_summary",
        umbral="sizes_bad_rates",
        valor={"sizes": dict(sizes), "bad_rates": dict(bad_rates)},
        accion="reportar_particiones",
    )


def _log_decision(
    audit: AuditSink | None, *, regla: str, umbral: object, valor: object, accion: str
) -> None:
    """Emitir un evento ``decision`` con la forma del ``AuditableMixin`` de ``core``."""
    if audit is None:
        return

    audit.emit(
        AuditEvent(
            kind="decision",
            step=None,
            payload={"regla": regla, "umbral": umbral, "valor": valor, "accion": accion},
            ts=datetime.now(UTC),
        )
    )


_SPLITTERS: Final[dict[str, Splitter]] = {
    "temporal": _split_temporal,
    "random": _split_random,
    "cohort": _split_cohort,
}
