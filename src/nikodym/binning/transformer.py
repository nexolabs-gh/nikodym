"""Transformer WoE sobre OptBinning para scorecards de comportamiento (SDD-06 §4).

``WoEBinner`` es un wrapper sklearn-like fino sobre ``optbinning.BinningProcess``. Aprende cortes,
WoE e IV exclusivamente en los datos recibidos por ``fit`` y luego aplica esos bins sin recalcular
en ``transform``. La auditoría formal queda fuera de este módulo: B6.3 conserva la información en
atributos fiteados y B6.4 (`BinningStep`) emitirá los ``log_decision`` correspondientes.

Decisiones autónomas para revisión de Cami:
- ``max_pvalue``/``max_pvalue_policy`` se envían por ``binning_fit_params`` junto con
  ``min_event_rate_diff`` y los overrides por variable. OptBinning 0.20.0 también acepta los dos
  primeros en ``BinningProcess``, pero usar un único canal evita divergencias entre parámetros
  globales y específicos.
- ``min_bin_size=0.0`` y ``max_pvalue=0.0`` se interpretan como "sin restricción" y se mapean a
  ``None`` en ``fit`` porque OptBinning 0.20.0 rechaza cero aunque el schema Pydantic lo permita.
  La misma regla aplica a ``cat_cutoff=0.0``.
- ``split_digits`` se valida contra el límite real de OptBinning 0.20.0 (0..8) en runtime; el
  schema acepta hasta 10 y se mantiene sin romper hasta que Cami ratifique el ajuste.
- Para separar special values cuando ``data`` ya normalizó centinelas a ``NaN``, se reconstruye una
  vista temporal a partir de ``MaskedFrame.special_mask`` usando un centinela canónico por columna.
  No se muta ``X`` ni el ``MaskedFrame``. Si ``transform`` recibe filas cubiertas por la máscara
  fiteada, aplica la misma reconstrucción; si no, depende de que el frame traiga los centinelas
  crudos.
- Frontera B6.3/B6.4: ``feature_columns='*'`` aquí excluye solo columnas estructurales presentes y
  ``exclude_columns``. La resolución completa de fechas/cohortes/poblaciones la hará
  ``BinningStep``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
import warnings
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, cast

from nikodym.binning.config import BinningConfig, MonotonicTrend, VariableBinningConfig
from nikodym.binning.exceptions import BinningFitError, BinningTransformError
from nikodym.core.base import NikodymTransformer
from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import MissingDependencyError

_SCORING_EXTRA_MESSAGE = "WoEBinner requiere OptBinning; instale nikodym[scoring]."

try:
    from sklearn.base import BaseEstimator, TransformerMixin  # type: ignore[import-untyped]
except ModuleNotFoundError as exc:
    raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.data.special import MaskedFrame

    DataFrame: TypeAlias = pd.DataFrame
    Index: TypeAlias = pd.Index
    Series: TypeAlias = pd.Series
else:
    DataFrame: TypeAlias = Any
    Index: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["WoEBinner"]

_STRUCTURAL_COLUMNS: tuple[str, ...] = ("target", "label_status", "partition", "ttd")
_KNOWN_SKLEARN_FORCE_ALL_FINITE_WARNING = ".*force_all_finite.*"


class WoEBinner(TransformerMixin, BaseEstimator, NikodymTransformer):  # type: ignore[misc]
    """Wrapper sklearn-like sobre ``optbinning.BinningProcess`` para scorecard."""

    config_cls: ClassVar[type[BinningConfig]] = BinningConfig

    def __init__(
        self,
        *,
        feature_columns: tuple[str, ...] | Literal["*"] = "*",
        exclude_columns: tuple[str, ...] = (),
        categorical_columns: tuple[str, ...] = (),
        variable_overrides: tuple[VariableBinningConfig, ...] = (),
        max_n_prebins: int = 20,
        min_prebin_size: float = 0.05,
        min_n_bins: int | None = None,
        max_n_bins: int | None = 8,
        min_bin_size: float | None = 0.05,
        min_bin_n_event: int | None = 1,
        min_bin_n_nonevent: int | None = 1,
        monotonic_trend: MonotonicTrend | None = "auto_asc_desc",
        min_event_rate_diff: float = 0.0,
        max_pvalue: float | None = None,
        max_pvalue_policy: Literal["consecutive", "all"] = "consecutive",
        solver: Literal["cp", "mip"] = "mip",
        mip_solver: Literal["bop", "cbc"] = "bop",
        time_limit: int = 100,
        require_optimal: bool = True,
        n_jobs: int | None = None,
        special_handling: Literal["separate", "as_missing"] = "separate",
        metric_special: Literal["empirical"] | float = "empirical",
        metric_missing: Literal["empirical"] | float = "empirical",
        cat_cutoff: float | None = 0.01,
        cat_unknown: float | str | None = None,
        split_digits: int | None = None,
        output_suffix: str = "__woe",
        keep_structural_columns: bool = True,
        fail_on_non_binnable: bool = False,
    ) -> None:
        """Asigna hiperparámetros sin lógica para preservar el contrato sklearn."""
        self.feature_columns = feature_columns
        self.exclude_columns = exclude_columns
        self.categorical_columns = categorical_columns
        self.variable_overrides = variable_overrides
        self.max_n_prebins = max_n_prebins
        self.min_prebin_size = min_prebin_size
        self.min_n_bins = min_n_bins
        self.max_n_bins = max_n_bins
        self.min_bin_size = min_bin_size
        self.min_bin_n_event = min_bin_n_event
        self.min_bin_n_nonevent = min_bin_n_nonevent
        self.monotonic_trend = monotonic_trend
        self.min_event_rate_diff = min_event_rate_diff
        self.max_pvalue = max_pvalue
        self.max_pvalue_policy = max_pvalue_policy
        self.solver = solver
        self.mip_solver = mip_solver
        self.time_limit = time_limit
        self.require_optimal = require_optimal
        self.n_jobs = n_jobs
        self.special_handling = special_handling
        self.metric_special = metric_special
        self.metric_missing = metric_missing
        self.cat_cutoff = cat_cutoff
        self.cat_unknown = cat_unknown
        self.split_digits = split_digits
        self.output_suffix = output_suffix
        self.keep_structural_columns = keep_structural_columns
        self.fail_on_non_binnable = fail_on_non_binnable

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> WoEBinner:
        """Construye ``WoEBinner`` desde ``BinningConfig`` excluyendo el discriminador ``type``."""
        if not isinstance(cfg, BinningConfig):
            cfg = BinningConfig.model_validate(cfg)
        kwargs = cfg.model_dump(exclude={"type"})
        kwargs["variable_overrides"] = cfg.variable_overrides
        return cls(**kwargs)

    def fit(
        self,
        X: DataFrame,  # noqa: N803
        y: Series,
        *,
        special: MaskedFrame | None = None,
        sample_weight: Series | None = None,
    ) -> Self:
        """Ajusta bins supervisados WoE/IV sin mutar ``X``, ``y`` ni ``special``.

        Raises
        ------
        BinningFitError
            Si el target no es binario con ambas clases, si todas las variables son no binneables,
            si OptBinning no alcanza un estado aceptable o si alguna tabla publica WoE infinito.
        """
        pd = _import_pandas()
        np = _import_numpy()
        binning_process_cls = _import_binning_process()

        _validate_runtime_config(self)
        frame = _as_dataframe(X, pd, context="fit")
        target = _as_target_series(y, frame.index, pd)
        weights = _as_weight_series(sample_weight, frame.index, pd)
        _validate_unique_columns(frame, error_cls=BinningFitError)
        _validate_binary_target(target)

        requested_columns = _resolve_feature_columns(
            frame,
            self.feature_columns,
            self.exclude_columns,
        )
        _validate_overrides_exist(requested_columns, self.variable_overrides)

        working = frame.loc[:, list(requested_columns)].copy(deep=True)
        special_state = _prepare_special_state(
            special=special,
            columns=requested_columns,
            index=frame.index,
            special_handling=self.special_handling,
        )
        working = _apply_special_state(working, special_state, self.special_handling, pd)
        _validate_no_undeclared_infinite(
            working,
            special_state.codes,
            error_cls=BinningFitError,
            context="fit",
        )

        skipped: dict[str, str] = {}
        process_columns: list[str] = []
        for column in requested_columns:
            reason = _non_binnable_reason(working[column])
            if reason is None:
                process_columns.append(column)
                continue
            _record_skip(
                skipped,
                column,
                reason,
                fail_on_non_binnable=self.fail_on_non_binnable,
                error_cls=BinningFitError,
            )

        if not process_columns:
            raise BinningFitError(
                "No quedó ninguna variable binneable tras aplicar exclusiones y casos borde; "
                f"razones={skipped!r}."
            )

        categorical_variables = _categorical_variables_for_fit(
            frame=working,
            columns=process_columns,
            categorical_columns=self.categorical_columns,
            variable_overrides=self.variable_overrides,
        )
        fit_params = _build_binning_fit_params(self, process_columns, categorical_variables)
        special_codes = _special_codes_for_process(
            special_state.codes,
            process_columns,
            special_handling=self.special_handling,
        )
        process = binning_process_cls(
            variable_names=process_columns,
            max_n_prebins=self.max_n_prebins,
            min_prebin_size=self.min_prebin_size,
            min_n_bins=self.min_n_bins,
            max_n_bins=self.max_n_bins,
            min_bin_size=_none_if_zero(self.min_bin_size),
            categorical_variables=categorical_variables or None,
            special_codes=special_codes or None,
            split_digits=self.split_digits,
            binning_fit_params=fit_params,
            n_jobs=self.n_jobs,
            verbose=False,
        )

        try:
            with _suppress_known_optbinning_warnings():
                process.fit(
                    working.loc[:, process_columns],
                    target,
                    sample_weight=weights,
                    check_input=True,
                )
        except Exception as exc:
            raise BinningFitError(f"No se pudo ajustar OptBinning: {exc}") from exc

        tables, fitted_summary, binned_columns, fitted_dtypes = _collect_fitted_outputs(
            process=process,
            process_columns=process_columns,
            skipped=skipped,
            require_optimal=self.require_optimal,
            fail_on_non_binnable=self.fail_on_non_binnable,
            np=np,
            pd=pd,
        )
        if not binned_columns:
            raise BinningFitError(f"OptBinning no dejó variables publicables; razones={skipped!r}.")

        self.process_ = process
        self.feature_columns_ = tuple(binned_columns)
        self.process_columns_ = tuple(process_columns)
        self.skipped_variables_ = dict(skipped)
        self.tables_ = tables
        self.summary_ = _append_skipped_summary(
            fitted_summary,
            requested_columns=requested_columns,
            skipped=skipped,
            frame=working,
            pd=pd,
        )
        self.woe_column_map_ = {
            column: f"{column}{self.output_suffix}" for column in self.feature_columns_
        }
        self.special_codes_ = {column: list(values) for column, values in special_codes.items()}
        self.unknown_categories_ = {column: 0 for column in self.feature_columns_}
        self.category_levels_ = _category_levels(
            working,
            self.feature_columns_,
            fitted_dtypes,
            special_state.codes,
        )
        self._special_mask_ = special_state.mask
        self._special_fill_values_ = special_state.fill_values
        return self

    def transform(self, X: DataFrame) -> DataFrame:  # noqa: N803
        """Transforma variables crudas a columnas WoE usando bins fiteados previamente."""
        self._check_fitted()
        pd = _import_pandas()
        np = _import_numpy()

        frame = _as_dataframe(X, pd, context="transform")
        _validate_unique_columns(frame, error_cls=BinningTransformError)
        missing = [column for column in self.process_columns_ if column not in frame.columns]
        if missing:
            joined = ", ".join(f"'{column}'" for column in missing)
            raise BinningTransformError(
                f"El transform requiere las columnas usadas en fit; faltan: {joined}."
            )

        working = frame.loc[:, list(self.process_columns_)].copy(deep=True)
        transform_state = SpecialState(
            codes=self.special_codes_,
            mask=self._special_mask_,
            fill_values=self._special_fill_values_,
        )
        working = _apply_special_state(working, transform_state, self.special_handling, pd)
        _validate_no_undeclared_infinite(
            working,
            transform_state.codes,
            error_cls=BinningTransformError,
            context="transform",
        )
        self.unknown_categories_ = _count_unknown_categories(
            working,
            self.category_levels_,
            transform_state.codes,
        )

        try:
            with _suppress_known_optbinning_warnings():
                transformed = self.process_.transform(
                    working,
                    metric="woe",
                    metric_special=self.metric_special,
                    metric_missing=self.metric_missing,
                    check_input=True,
                )
        except Exception as exc:
            raise BinningTransformError(f"No se pudo transformar a WoE: {exc}") from exc

        woe = cast(DataFrame, transformed.loc[:, list(self.feature_columns_)].copy(deep=True))
        woe.rename(columns=self.woe_column_map_, inplace=True)
        for column in woe.columns:
            woe[column] = woe[column].astype("float64").map(_normalize_float)
            values = woe[column].to_numpy(dtype="float64", copy=False)
            if not bool(np.isfinite(values).all()):
                observed = woe.loc[~np.isfinite(values), column].iloc[0]
                raise BinningTransformError(
                    "La transformación WoE produjo un valor no finito: "
                    f"columna='{column}', valor observado={observed!r}."
                )

        if not self.keep_structural_columns:
            return woe

        structural = [column for column in _STRUCTURAL_COLUMNS if column in frame.columns]
        if not structural:
            return woe
        return cast(DataFrame, pd.concat([frame.loc[:, structural].copy(deep=True), woe], axis=1))

    def fit_transform(
        self,
        X: DataFrame,  # noqa: N803
        y: Series,
        **kwargs: Any,
    ) -> DataFrame:
        """Ajusta el binner y devuelve el ``woe_frame`` para el mismo ``X``."""
        return self.fit(X, y, **kwargs).transform(X)


class SpecialState:
    """Estado mínimo para reconstruir special values sin mutar el frame fuente."""

    def __init__(
        self,
        *,
        codes: dict[str, list[object]],
        mask: DataFrame | None,
        fill_values: dict[str, object],
    ) -> None:
        """Guarda códigos, máscara y centinela canónico por columna."""
        self.codes = codes
        self.mask = mask
        self.fill_values = fill_values


def _import_pandas() -> Any:
    """Importa pandas de forma local para mantener liviano ``import nikodym.binning``."""
    return importlib.import_module("pandas")


def _import_numpy() -> Any:
    """Importa numpy de forma local para mantener liviano ``import nikodym.binning``."""
    return importlib.import_module("numpy")


def _import_binning_process() -> type[Any]:
    """Importa ``BinningProcess`` y emite un error accionable si falta el extra."""
    try:
        optbinning = importlib.import_module("optbinning")
    except ImportError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc
    return cast("type[Any]", optbinning.BinningProcess)


def _validate_runtime_config(estimator: WoEBinner) -> None:
    """Revalida hiperparámetros y aplica límites reales de OptBinning 0.20.0."""
    estimator._validate_config()
    if estimator.split_digits is not None and estimator.split_digits > 8:
        raise BinningFitError(
            "OptBinning 0.20.0 admite split_digits entre 0 y 8; "
            f"valor observado={estimator.split_digits}."
        )


def _as_dataframe(df: object, pd: Any, *, context: str) -> DataFrame:
    """Valida el contrato de entrada tabular."""
    if not isinstance(df, pd.DataFrame):
        error_cls = BinningFitError if context == "fit" else BinningTransformError
        raise error_cls(
            f"WoEBinner.{context} requiere un pandas.DataFrame; tipo observado={type(df).__name__}."
        )
    if df.empty:
        error_cls = BinningFitError if context == "fit" else BinningTransformError
        raise error_cls(f"WoEBinner.{context} recibió un DataFrame vacío.")
    return cast(DataFrame, df.copy(deep=True))


def _as_target_series(y: object, index: Index, pd: Any) -> Series:
    """Coacciona ``y`` a ``Series`` alineada con ``X`` sin mutar el objeto recibido."""
    target = y.copy(deep=True) if isinstance(y, pd.Series) else pd.Series(y, index=index)
    if len(target) != len(index):
        raise BinningFitError(
            "El target debe tener la misma cantidad de filas que X: "
            f"len(y)={len(target)}, len(X)={len(index)}."
        )
    if not target.index.equals(index):
        target = target.reindex(index)
    return cast(Series, target)


def _as_weight_series(sample_weight: object, index: Index, pd: Any) -> Series | None:
    """Coacciona pesos opcionales y valida largo/alineación."""
    if sample_weight is None:
        return None
    if isinstance(sample_weight, pd.Series):
        weights = sample_weight.copy(deep=True)
    else:
        weights = pd.Series(sample_weight, index=index)
    if len(weights) != len(index):
        raise BinningFitError(
            "sample_weight debe tener la misma cantidad de filas que X: "
            f"len(sample_weight)={len(weights)}, len(X)={len(index)}."
        )
    if not weights.index.equals(index):
        weights = weights.reindex(index)
    return cast(Series, weights)


def _validate_unique_columns(frame: DataFrame, *, error_cls: type[Exception]) -> None:
    """Impide ambigüedad por columnas duplicadas."""
    duplicated = frame.columns[frame.columns.duplicated()].astype(str).tolist()
    if duplicated:
        joined = ", ".join(f"'{column}'" for column in duplicated)
        raise error_cls(f"WoEBinner requiere nombres de columnas únicos; duplicadas: {joined}.")


def _validate_binary_target(target: Series) -> None:
    """Valida target binario 0/1 con ambas clases antes de llamar a OptBinning."""
    invalid_mask = ~target.isin((0, 1))
    if bool(invalid_mask.any()):
        observed = sorted(str(value) for value in target.loc[invalid_mask].unique())
        raise BinningFitError(
            "El target de binning debe contener solo 0/1 sin nulos; "
            f"valores observados inválidos={observed}."
        )
    classes = set(int(value) for value in target.unique())
    if classes != {0, 1}:
        raise BinningFitError(
            "Target degenerado para binning: se requiere al menos un 0 y un 1; "
            f"clases observadas={sorted(classes)}."
        )


def _resolve_feature_columns(
    frame: DataFrame,
    feature_columns: tuple[str, ...] | Literal["*"],
    exclude_columns: tuple[str, ...],
) -> tuple[str, ...]:
    """Resuelve columnas candidatas preservando el orden del ``DataFrame``."""
    exclusions = {str(column) for column in exclude_columns}
    if feature_columns == "*":
        structural = set(_STRUCTURAL_COLUMNS)
        columns = tuple(
            str(column)
            for column in frame.columns
            if str(column) not in structural and str(column) not in exclusions
        )
    else:
        missing = [column for column in feature_columns if column not in frame.columns]
        if missing:
            joined = ", ".join(f"'{column}'" for column in missing)
            raise BinningFitError(
                f"BinningConfig.feature_columns declara columna(s) inexistente(s): {joined}."
            )
        columns = tuple(column for column in feature_columns if column not in exclusions)

    if not columns:
        raise BinningFitError(
            "No hay columnas candidatas para binning tras aplicar feature_columns/exclude_columns."
        )
    return columns


def _validate_overrides_exist(
    feature_columns: tuple[str, ...],
    variable_overrides: tuple[VariableBinningConfig, ...],
) -> None:
    """Falla si un override apunta a una variable fuera del set candidato."""
    feature_set = set(feature_columns)
    missing = [override.name for override in variable_overrides if override.name not in feature_set]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise BinningFitError(
            f"variable_overrides declara variable(s) que no serán binneadas: {joined}."
        )


def _prepare_special_state(
    *,
    special: MaskedFrame | None,
    columns: tuple[str, ...],
    index: Index,
    special_handling: str,
) -> SpecialState:
    """Extrae catálogo/máscara de ``MaskedFrame`` con copias defensivas."""
    if special is None or special_handling not in {"separate", "as_missing"}:
        return SpecialState(codes={}, mask=None, fill_values={})

    codes: dict[str, list[object]] = {
        column: list(special.special_catalog.get(column, []))
        for column in columns
        if special.special_catalog.get(column)
    }
    if not codes:
        return SpecialState(codes={}, mask=None, fill_values={})

    missing_mask_columns = [
        column for column in codes if column not in special.special_mask.columns
    ]
    if missing_mask_columns:
        joined = ", ".join(f"'{column}'" for column in missing_mask_columns)
        raise BinningFitError(
            "MaskedFrame.special_catalog y special_mask son inconsistentes; faltan columnas: "
            f"{joined}."
        )
    mask = special.special_mask.loc[:, list(codes)].copy(deep=True)
    if not index.isin(mask.index).all():
        raise BinningFitError(
            "MaskedFrame.special_mask no cubre todas las filas recibidas por fit."
        )
    fill_values: dict[str, object] = {column: values[0] for column, values in codes.items()}
    return SpecialState(codes=codes, mask=mask, fill_values=fill_values)


def _apply_special_state(
    frame: DataFrame,
    state: SpecialState,
    special_handling: str,
    pd: Any,
) -> DataFrame:
    """Reconstruye special values o los fusiona a missing sobre una copia de trabajo."""
    if state.mask is None:
        return frame

    result = frame.copy(deep=True)
    for column, fill_value in state.fill_values.items():
        if column not in result.columns or column not in state.mask.columns:
            continue
        common_index = result.index.intersection(state.mask.index)
        if common_index.empty:
            continue
        mask = state.mask.loc[common_index, column].fillna(False).astype("bool")
        if not bool(mask.any()):
            continue
        selected_index = mask[mask].index
        if special_handling == "separate":
            result.loc[selected_index, column] = cast(Any, fill_value)
        else:
            result.loc[selected_index, column] = pd.NA
    return result


def _special_codes_for_process(
    special_codes: dict[str, list[object]],
    process_columns: list[str],
    *,
    special_handling: str,
) -> dict[str, list[object]]:
    """Filtra ``special_codes`` a las variables realmente enviadas a OptBinning."""
    if special_handling != "separate":
        return {}
    return {
        column: list(special_codes[column]) for column in process_columns if column in special_codes
    }


def _validate_no_undeclared_infinite(
    frame: DataFrame,
    special_codes: dict[str, list[object]],
    *,
    error_cls: type[Exception],
    context: str,
) -> None:
    """Rechaza ``+/-inf`` salvo que estén declarados como special values."""
    np = _import_numpy()
    for column in frame.columns:
        series = frame[column]
        if not _is_numeric_series(series):
            continue
        values = series.to_numpy(dtype="float64", copy=False)
        infinite_mask = np.isinf(values)
        if not bool(infinite_mask.any()):
            continue
        allowed = {
            float(value)
            for value in special_codes.get(column, [])
            if isinstance(value, int | float) and math.isinf(float(value))
        }
        if math.inf in allowed and -math.inf in allowed:
            continue
        bad_count = 0
        for observed in values[infinite_mask]:
            if float(observed) not in allowed:
                bad_count += 1
        if bad_count:
            raise error_cls(
                f"WoEBinner.{context} recibió infinitos no declarados como special values: "
                f"columna='{column}', conteo={bad_count}."
            )


def _is_numeric_series(series: Series) -> bool:
    """Detecta series numéricas sin depender de pandas top-level."""
    return bool(series.dtype.kind in {"b", "i", "u", "f", "c"})


def _non_binnable_reason(series: Series) -> str | None:
    """Clasifica variables no binneables antes de llamar al solver."""
    if bool(series.isna().all()):
        return "all_missing"
    non_missing = series.dropna()
    if non_missing.nunique(dropna=True) <= 1:
        return "constant"
    return None


def _record_skip(
    skipped: dict[str, str],
    column: str,
    reason: str,
    *,
    fail_on_non_binnable: bool,
    error_cls: type[Exception],
) -> None:
    """Registra o falla ante una variable no binneable según config."""
    if fail_on_non_binnable:
        raise error_cls(f"Variable no binneable: columna='{column}', razón='{reason}'.")
    skipped[column] = reason


def _build_binning_fit_params(
    estimator: WoEBinner,
    process_columns: list[str],
    categorical_variables: list[str],
) -> dict[str, dict[str, object]]:
    """Construye kwargs por variable para ``OptimalBinning.set_params``.

    Fija el ``dtype`` explícito de cada variable (``numerical`` salvo las resueltas como
    categóricas por Nikodym). Es el fix de la causa raíz del P0: ``BinningProcess.fit`` con
    ``check_input=True`` pasa por ``sklearn.check_array(dtype=None)``, que colapsa un DataFrame
    heterogéneo (cualquier columna object mezclada con numéricas) a un único array ``object``.
    OptBinning entonces auto-detecta ``dtype == object`` para **todas** las columnas y trata las
    numéricas continuas como categóricas (colapsan a 1 bin, IV=0, y ``selection`` las descarta en
    silencio). Al declarar el ``dtype`` por variable, Nikodym es la única fuente de verdad y la
    detección de OptBinning deja de importar; es robusto entre plataformas y versiones de numpy.
    """
    categorical_set = set(categorical_variables)
    overrides = {override.name: override for override in estimator.variable_overrides}
    params: dict[str, dict[str, object]] = {}
    for column in process_columns:
        column_params: dict[str, object] = {
            "solver": estimator.solver,
            "mip_solver": estimator.mip_solver,
            "time_limit": estimator.time_limit,
            "min_event_rate_diff": estimator.min_event_rate_diff,
            "max_pvalue": _none_if_zero(estimator.max_pvalue),
            "max_pvalue_policy": estimator.max_pvalue_policy,
            "min_bin_n_event": estimator.min_bin_n_event,
            "min_bin_n_nonevent": estimator.min_bin_n_nonevent,
            "cat_cutoff": _none_if_zero(estimator.cat_cutoff),
            "cat_unknown": estimator.cat_unknown,
            "dtype": "categorical" if column in categorical_set else "numerical",
        }
        if estimator.monotonic_trend is not None:
            column_params["monotonic_trend"] = estimator.monotonic_trend

        override = overrides.get(column)
        if override is not None:
            if override.dtype != "auto":
                column_params["dtype"] = override.dtype
            if override.monotonic_trend is not None:
                column_params["monotonic_trend"] = override.monotonic_trend
            if override.max_n_bins is not None:
                column_params["max_n_bins"] = override.max_n_bins
            if override.min_bin_size is not None:
                column_params["min_bin_size"] = _none_if_zero(override.min_bin_size)
            if override.cat_cutoff is not None:
                column_params["cat_cutoff"] = _none_if_zero(override.cat_cutoff)
        params[column] = {key: value for key, value in column_params.items() if value is not None}
    return params


def _none_if_zero(value: float | int | None) -> float | int | None:
    """Mapea cero a ``None`` para parámetros donde OptBinning usa ``None`` como desactivación."""
    if value == 0:
        return None
    return value


def _categorical_variables_for_fit(
    *,
    frame: DataFrame,
    columns: list[str],
    categorical_columns: tuple[str, ...],
    variable_overrides: tuple[VariableBinningConfig, ...],
) -> list[str]:
    """Resuelve variables categóricas forzadas por config u override."""
    forced = set(categorical_columns)
    forced.update(
        override.name for override in variable_overrides if override.dtype == "categorical"
    )
    forced_numerical = {
        override.name for override in variable_overrides if override.dtype == "numerical"
    }
    forced.difference_update(forced_numerical)
    return [
        column
        for column in columns
        if column in forced
        or (column not in forced_numerical and _is_auto_categorical(frame[column]))
    ]


def _is_auto_categorical(series: Series) -> bool:
    """Detecta categóricas evidentes para ayudar a OptBinning con dtype object/string/category."""
    return bool(series.dtype.kind in {"O", "S", "U"} or str(series.dtype) in {"category", "string"})


def _collect_fitted_outputs(
    *,
    process: Any,
    process_columns: list[str],
    skipped: dict[str, str],
    require_optimal: bool,
    fail_on_non_binnable: bool,
    np: Any,
    pd: Any,
) -> tuple[dict[str, DataFrame], DataFrame, list[str], dict[str, str]]:
    """Construye tablas y resumen de variables fiteadas."""
    with _suppress_known_optbinning_warnings():
        raw_summary = process.summary().copy(deep=True)
    raw_summary["name"] = raw_summary["name"].astype(str)
    summary_by_name = raw_summary.set_index("name", drop=False)
    tables: dict[str, DataFrame] = {}
    rows: list[dict[str, object]] = []
    binned_columns: list[str] = []
    fitted_dtypes: dict[str, str] = {}

    for column in process_columns:
        if column not in summary_by_name.index:
            _record_skip(
                skipped,
                column,
                "missing_summary",
                fail_on_non_binnable=fail_on_non_binnable,
                error_cls=BinningFitError,
            )
            continue

        row = summary_by_name.loc[column]
        status = str(row["status"])
        dtype = str(row["dtype"])
        fitted_dtypes[column] = dtype
        if require_optimal and status != "OPTIMAL":
            _record_skip(
                skipped,
                column,
                f"solver_status:{status}",
                fail_on_non_binnable=fail_on_non_binnable,
                error_cls=BinningFitError,
            )
            continue

        with _suppress_known_optbinning_warnings():
            table = process.get_binned_variable(column).binning_table.build(add_totals=True)
        table = _normalize_numeric_dataframe(table.copy(deep=True), pd)
        _validate_finite_woe_table(column, table, np, pd)
        tables[column] = table
        binned_columns.append(column)
        rows.append(_summary_row(row, selected=True, skipped_reason=None))

    fitted_summary = cast(DataFrame, pd.DataFrame(rows))
    if not fitted_summary.empty:
        fitted_summary = _normalize_numeric_dataframe(fitted_summary, pd)
    return tables, fitted_summary, binned_columns, fitted_dtypes


def _summary_row(
    row: Series,
    *,
    selected: bool,
    skipped_reason: str | None,
) -> dict[str, object]:
    """Normaliza una fila de ``process.summary()`` y añade flags Nikodym."""
    iv = _safe_float(row.get("iv", 0.0))
    js = _safe_float(row.get("js", 0.0))
    gini = _safe_float(row.get("gini", 0.0))
    quality_score = _safe_float(row.get("quality_score", 0.0))
    iv = _normalize_float(iv)
    from nikodym.binning.results import iv_band

    band = iv_band(iv)
    return {
        "name": str(row["name"]),
        "dtype": str(row.get("dtype", "unknown")),
        "status": str(row.get("status", "SKIPPED")),
        "selected": bool(selected),
        "n_bins": int(row.get("n_bins", 0)),
        "iv": iv,
        "js": _normalize_float(js),
        "gini": _normalize_float(gini),
        "quality_score": _normalize_float(quality_score),
        "iv_band": band,
        "is_suspicious_iv": band == "suspicious",
        "is_zero_iv": iv == 0.0,
        "monotonic_trend": None,
        "skipped_reason": skipped_reason,
    }


def _append_skipped_summary(
    fitted_summary: DataFrame,
    *,
    requested_columns: tuple[str, ...],
    skipped: dict[str, str],
    frame: DataFrame,
    pd: Any,
) -> DataFrame:
    """Devuelve un resumen en orden de columnas solicitadas, incluyendo skips."""
    fitted_rows = {
        str(row["name"]): cast("dict[str, object]", dict(row))
        for row in fitted_summary.to_dict(orient="records")
    }
    rows: list[dict[str, object]] = []
    for column in requested_columns:
        if column in fitted_rows:
            rows.append(fitted_rows[column])
            continue
        reason = skipped.get(column)
        if reason is None:
            continue
        rows.append(
            {
                "name": column,
                "dtype": _dtype_label(frame[column]),
                "status": "SKIPPED",
                "selected": False,
                "n_bins": 0,
                "iv": 0.0,
                "js": 0.0,
                "gini": 0.0,
                "quality_score": 0.0,
                "iv_band": "none",
                "is_suspicious_iv": False,
                "is_zero_iv": True,
                "monotonic_trend": None,
                "skipped_reason": reason,
            }
        )
    return cast(DataFrame, pd.DataFrame(rows))


def _dtype_label(series: Series) -> str:
    """Etiqueta dtype en el vocabulario de summary."""
    return "numerical" if _is_numeric_series(series) else "categorical"


def _safe_float(value: object) -> float:
    """Convierte métricas faltantes o string vacío a float defendible."""
    if value is None or value == "":
        return 0.0
    return float(cast(Any, value))


def _normalize_numeric_dataframe(df: DataFrame, pd: Any) -> DataFrame:
    """Normaliza ``-0.0`` en columnas numéricas sin tocar strings de bins."""
    result = df.copy(deep=True)
    for column in result.columns:
        if not pd.api.types.is_float_dtype(result[column]):
            continue
        result[column] = result[column].map(lambda value: _normalize_float(float(value)))
    return result


def _validate_finite_woe_table(column: str, table: DataFrame, np: Any, pd: Any) -> None:
    """Falla si una tabla con observaciones conserva WoE no finito."""
    required = {"WoE", "Count", "Event", "Non-event"}
    if not required <= set(table.columns):
        raise BinningFitError(
            f"La tabla de OptBinning para '{column}' no contiene columnas requeridas: "
            f"{sorted(required)}."
        )
    woe = pd.to_numeric(table["WoE"], errors="coerce")
    count = pd.to_numeric(table["Count"], errors="coerce").fillna(0)
    is_totals = table.index.astype(str) == "Totals"
    finite_mask = np.isfinite(woe.to_numpy(dtype="float64", copy=True))
    invalid = (~finite_mask) & count.gt(0).to_numpy(dtype=bool, copy=True) & ~is_totals
    if bool(invalid.any()):
        observed = table.loc[invalid, "WoE"].iloc[0]
        raise BinningFitError(
            f"WoE no finito en tabla de binning: variable='{column}', valor observado={observed!r}."
        )
    event = pd.to_numeric(table["Event"], errors="coerce").fillna(0)
    nonevent = pd.to_numeric(table["Non-event"], errors="coerce").fillna(0)
    pure = (
        count.gt(0).to_numpy(dtype=bool, copy=True)
        & ~is_totals
        & (
            event.eq(0).to_numpy(dtype=bool, copy=True)
            | nonevent.eq(0).to_numpy(dtype=bool, copy=True)
        )
    )
    if bool(pure.any()):
        observed_row = table.loc[pure, ["Bin", "Non-event", "Event"]].iloc[0].to_dict()
        raise BinningFitError(
            "WoE no defendible por bin con una clase en cero: "
            f"variable='{column}', valor observado={observed_row!r}."
        )


def _category_levels(
    frame: DataFrame,
    feature_columns: Iterable[str],
    fitted_dtypes: dict[str, str],
    special_codes: dict[str, list[object]],
) -> dict[str, set[object]]:
    """Captura niveles categóricos vistos en fit para auditar categorías nuevas."""
    levels: dict[str, set[object]] = {}
    for column in feature_columns:
        if fitted_dtypes.get(column) != "categorical":
            continue
        series = frame[column]
        values = set(series.dropna().tolist())
        values.difference_update(special_codes.get(column, []))
        levels[column] = values
    return levels


def _count_unknown_categories(
    frame: DataFrame,
    category_levels: dict[str, set[object]],
    special_codes: dict[str, list[object]],
) -> dict[str, int]:
    """Cuenta niveles categóricos no vistos en fit para la última llamada a ``transform``."""
    counts: dict[str, int] = {}
    for column, known in category_levels.items():
        if column not in frame.columns:
            counts[column] = 0
            continue
        series = frame[column].dropna()
        if series.empty:
            counts[column] = 0
            continue
        special = set(special_codes.get(column, []))
        unknown_mask = ~series.isin(known | special)
        counts[column] = int(unknown_mask.sum())
    return counts


def _normalize_float(value: float) -> float:
    """Normaliza ``-0.0`` conservando NaN para validaciones posteriores."""
    if math.isnan(value):
        return value
    if value == 0.0:
        return 0.0
    return value


@contextmanager
def _suppress_known_optbinning_warnings() -> Iterator[None]:
    """Silencia warnings externos conocidos y ratificados de OptBinning 0.20.0."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_KNOWN_SKLEARN_FORCE_ALL_FINITE_WARNING,
            category=FutureWarning,
        )
        # Ratificado en SDD-06 §9: warning interno benigno del heurístico auto_asc_desc;
        # la tabla publicada igual pasa por `_validate_finite_woe_table`.
        warnings.filterwarnings(
            "ignore",
            message="invalid value encountered in scalar divide",
            category=RuntimeWarning,
            module=r"optbinning\.binning\.auto_monotonic",
        )
        yield
