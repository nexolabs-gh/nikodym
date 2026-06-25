"""Definición declarativa del target binario para la capa ``data`` (SDD-02 §4/§7).

``TargetDefinition`` deriva dos columnas auditables desde ``TargetConfig``:
``target`` nullable ``Int8`` (1=malo, 0=bueno, ``NA`` fuera de modelado) y
``label_status`` (``bueno``/``malo``/``indeterminado``/``excluido``). Las reglas se evalúan con el
mini-DSL estructurado de ``data.config`` y una allowlist cerrada de operadores, sin ``eval``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.core.audit import AuditEvent, AuditSink
from nikodym.core.exceptions import ConfigError, DataValidationError
from nikodym.data.config import ExclusionRule, Predicate, Rule, TargetConfig

__all__ = ["LabeledFrame", "TargetDefinition", "TargetSummary"]

LabelStatus: TypeAlias = Literal["bueno", "malo", "indeterminado", "excluido"]
ScalarValue: TypeAlias = bool | int | float | str
MembershipValue: TypeAlias = tuple[ScalarValue, ...]
PredicateValue: TypeAlias = ScalarValue | MembershipValue | None

STATUS_COL: Final = "label_status"
STATUS_VALUES: Final[tuple[LabelStatus, ...]] = (
    "bueno",
    "malo",
    "indeterminado",
    "excluido",
)
EXCLUSION_WINDOW_REASON: Final = "ventana_incompleta"
_ALLOWED_OPS: Final[set[str]] = {"==", "!=", "<", "<=", ">", ">=", "in", "notin", "isna", "notna"}
_ORDERED_OPS: Final[set[str]] = {"<", "<=", ">", ">="}
_SCALAR_OPS: Final[set[str]] = {"==", "!=", "<", "<=", ">", ">="}
_MEMBERSHIP_OPS: Final[set[str]] = {"in", "notin"}


class TargetSummary(BaseModel):
    """Resumen auditable de la etiqueta derivada."""

    class_counts: dict[str, int]
    bad_rate: float
    exclusions_by_reason: dict[str, int]
    ambiguous_rows: int


class LabeledFrame(BaseModel):
    """Resultado de etiquetar el ``DataFrame`` con target y estado de etiqueta."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    frame: pd.DataFrame
    target_col: str
    status_col: str
    summary: TargetSummary


class TargetDefinition:
    """Deriva la etiqueta binaria desde reglas declarativas con precedencia explícita."""

    def __init__(self, config: TargetConfig) -> None:
        """Construye la definición con las reglas declaradas en ``TargetConfig``."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: TargetConfig) -> TargetDefinition:
        """Construye una definición desde ``DataConfig.target`` / ``TargetConfig``."""
        return cls(cfg)

    def apply(self, df: pd.DataFrame, *, audit: AuditSink | None = None) -> LabeledFrame:
        """Etiqueta ``df`` en una copia defensiva y devuelve el contenedor auditable.

        Parameters
        ----------
        df : pandas.DataFrame
            Dataset validado sobre el que se evalúan las reglas de target. No se muta in-place.
        audit : AuditSink or None
            Sumidero opcional para emitir eventos ``decision`` por exclusiones y ambigüedades.

        Returns
        -------
        LabeledFrame
            Copia de ``df`` con ``target`` y ``label_status`` agregados, más resumen de clases.

        Raises
        ------
        ConfigError
            Si una regla está vacía, referencia columnas inexistentes, usa un operador fuera de la
            allowlist o compara valores incompatibles con el dtype de la columna.
        DataValidationError
            Si la ventana declara fechas no datetime, si las columnas de salida colisionan con el
            input, o si el resultado queda sin buenos o sin malos.
        """
        _validate_output_columns(df, self.config.target_col, STATUS_COL)
        frame = df.copy(deep=True)

        exclusion_masks = _exclusion_masks(df, self.config.exclusion_rules, self.config)
        raw_indeterminate_mask = _optional_rule_mask(df, self.config.indeterminate_rule)
        indeterminate_mask = (
            raw_indeterminate_mask if raw_indeterminate_mask is not None else _false_mask(df.index)
        )
        bad_mask = _eval_rule(df, self.config.bad_rule)
        good_mask = _optional_rule_mask(df, self.config.good_rule)
        ambiguous_rows = _count_ambiguous_rows(
            exclusion_masks=tuple(mask for _, mask in exclusion_masks),
            indeterminate_mask=raw_indeterminate_mask,
            bad_mask=bad_mask,
            good_mask=good_mask,
        )

        status = pd.Series("bueno", index=df.index, dtype="object")
        target = pd.Series(pd.NA, index=df.index, dtype="Int8")

        excluded_mask, exclusions_by_reason = _apply_exclusions(status, exclusion_masks, audit)
        indeterminate_final = indeterminate_mask & ~excluded_mask
        status.loc[indeterminate_final] = "indeterminado"

        available_for_bad = ~(excluded_mask | indeterminate_final)
        bad_final = bad_mask & available_for_bad
        status.loc[bad_final] = "malo"
        target.loc[bad_final] = 1

        available_for_good = available_for_bad & ~bad_final
        if good_mask is None:
            good_final = available_for_good
            unclassified_final = _false_mask(df.index)
        else:
            good_final = good_mask & available_for_good
            unclassified_final = available_for_good & ~good_final

        status.loc[good_final] = "bueno"
        target.loc[good_final] = 0
        status.loc[unclassified_final] = "indeterminado"

        if ambiguous_rows > 0:
            _log_decision(
                audit,
                regla="target_ambiguo",
                umbral="exclusion > indeterminado > malo > bueno",
                valor=ambiguous_rows,
                accion="resolver_por_precedencia",
            )

        frame[self.config.target_col] = target
        frame[STATUS_COL] = pd.Categorical(status, categories=STATUS_VALUES)
        summary = _build_summary(status, exclusions_by_reason, ambiguous_rows)
        return LabeledFrame(
            frame=frame,
            target_col=self.config.target_col,
            status_col=STATUS_COL,
            summary=summary,
        )


def _validate_output_columns(df: pd.DataFrame, target_col: str, status_col: str) -> None:
    """Evita sobrescribir columnas del cliente al agregar el target."""
    collisions = [column for column in (target_col, status_col) if column in df.columns]
    if collisions:
        joined = ", ".join(f"'{column}'" for column in collisions)
        raise DataValidationError(
            "La definición de target intentaría sobrescribir columna(s) existentes: "
            f"{joined}. Use otro target_col o remueva esas columnas antes de etiquetar."
        )


def _exclusion_masks(
    df: pd.DataFrame,
    exclusion_rules: tuple[ExclusionRule, ...],
    config: TargetConfig,
) -> list[tuple[str, pd.Series]]:
    """Calcula máscaras de exclusión en orden de precedencia determinista."""
    masks: list[tuple[str, pd.Series]] = []
    if config.window is not None and config.window.data_cutoff_col is not None:
        masks.append((EXCLUSION_WINDOW_REASON, _window_incomplete_mask(df, config)))

    for exclusion in exclusion_rules:
        masks.append((exclusion.name, _eval_rule(df, exclusion.rule)))

    return masks


def _window_incomplete_mask(df: pd.DataFrame, config: TargetConfig) -> pd.Series:
    """Marca filas cuya ventana de desempeño no maduró a la fecha de corte."""
    window = config.window
    assert window is not None
    assert window.data_cutoff_col is not None

    observation_col = window.observation_date_col
    cutoff_col = window.data_cutoff_col
    _validate_datetime_column(df, observation_col, "observation_date_col")
    _validate_datetime_column(df, cutoff_col, "data_cutoff_col")

    matured_until = df[observation_col] + pd.offsets.DateOffset(months=window.months)
    mask = matured_until > df[cutoff_col]
    return mask.fillna(False).astype("bool")


def _validate_datetime_column(df: pd.DataFrame, column: str, field_name: str) -> None:
    """Valida existencia y dtype datetime para columnas de ventana."""
    if column not in df.columns:
        raise DataValidationError(
            "La ventana de desempeño referencia una columna inexistente "
            f"en {field_name}='{column}'."
        )
    if not pd.api.types.is_datetime64_any_dtype(df[column].dtype):
        raise DataValidationError(
            "La ventana de desempeño requiere columnas datetime antes de evaluar madurez; "
            f"{field_name}='{column}' tiene dtype {df[column].dtype}."
        )


def _apply_exclusions(
    status: pd.Series, exclusion_masks: list[tuple[str, pd.Series]], audit: AuditSink | None
) -> tuple[pd.Series, dict[str, int]]:
    """Aplica exclusiones por motivo, con primera regla ganadora para el resumen."""
    excluded_mask = _false_mask(status.index)
    exclusions_by_reason: dict[str, int] = {}
    for reason, mask in exclusion_masks:
        new_exclusions = mask & ~excluded_mask
        count = int(new_exclusions.sum())
        if count == 0:
            continue

        status.loc[new_exclusions] = "excluido"
        excluded_mask = excluded_mask | new_exclusions
        exclusions_by_reason[reason] = count
        _log_decision(
            audit,
            regla="exclusion",
            umbral=reason,
            valor=count,
            accion="marcar_excluido",
        )
    return excluded_mask, exclusions_by_reason


def _optional_rule_mask(df: pd.DataFrame, rule: Rule | None) -> pd.Series | None:
    """Evalúa una regla opcional y conserva ``None`` cuando no fue declarada."""
    if rule is None:
        return None
    return _eval_rule(df, rule)


def _eval_rule(df: pd.DataFrame, rule: Rule) -> pd.Series:
    """Evalúa ``Rule`` como ``(AND all_of) AND (OR any_of)`` sin ``eval``."""
    _validate_rule(rule, df)
    all_mask = _true_mask(df.index)
    for predicate in rule.all_of:
        all_mask = all_mask & _eval_predicate(df, predicate)

    any_mask = _true_mask(df.index)
    if rule.any_of:
        any_mask = _false_mask(df.index)
        for predicate in rule.any_of:
            any_mask = any_mask | _eval_predicate(df, predicate)

    return (all_mask & any_mask).fillna(False).astype("bool")


def _validate_rule(rule: Rule, df: pd.DataFrame) -> None:
    """Valida estructura, columnas, operadores y compatibilidad de todos los predicados."""
    predicates = (*rule.all_of, *rule.any_of)
    if not predicates:
        raise ConfigError(
            "Regla de target vacía: declare al menos un predicado en all_of o any_of."
        )

    for predicate in predicates:
        _validate_predicate(predicate, df)


def _validate_predicate(predicate: Predicate, df: pd.DataFrame) -> None:
    """Valida un predicado antes de construir su máscara pandas."""
    op = str(predicate.op)
    if op not in _ALLOWED_OPS:
        raise ConfigError(
            "Operador de regla fuera de la allowlist cerrada: "
            f"columna='{predicate.col}', operador='{op}'."
        )
    if predicate.col not in df.columns:
        raise ConfigError(
            "Regla de target referencia una columna inexistente: "
            f"columna='{predicate.col}', operador='{op}'."
        )

    value = predicate.value
    if op in {"isna", "notna"}:
        return
    if op in _MEMBERSHIP_OPS:
        _validate_membership_value(predicate, value, df[predicate.col])
        return

    _validate_scalar_value(predicate, value, df[predicate.col])


def _validate_membership_value(
    predicate: Predicate, value: PredicateValue, series: pd.Series
) -> None:
    """Valida ``in``/``notin`` y cada elemento contra el dtype de la columna."""
    if not isinstance(value, tuple) or len(value) == 0:
        raise ConfigError(
            "Operador de pertenencia requiere una tupla no vacía en 'value': "
            f"columna='{predicate.col}', operador='{predicate.op}'."
        )
    for item in value:
        _validate_value_compatible(predicate, item, series, ordered=False)


def _validate_scalar_value(predicate: Predicate, value: PredicateValue, series: pd.Series) -> None:
    """Valida operadores escalares contra valor no nulo ni tuple."""
    if isinstance(value, tuple) or value is None:
        raise ConfigError(
            "Operador escalar requiere un valor escalar no nulo: "
            f"columna='{predicate.col}', operador='{predicate.op}'."
        )
    _validate_value_compatible(predicate, value, series, ordered=str(predicate.op) in _ORDERED_OPS)


def _validate_value_compatible(
    predicate: Predicate, value: ScalarValue, series: pd.Series, *, ordered: bool
) -> None:
    """Rechaza comparaciones dtype↔valor que pandas resolvería con warning/error opaco."""
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        if isinstance(value, bool) and not ordered:
            return
        _raise_incompatible_value(predicate, value, dtype)

    if pd.api.types.is_numeric_dtype(dtype):
        if isinstance(value, int | float) and not isinstance(value, bool):
            return
        _raise_incompatible_value(predicate, value, dtype)

    if pd.api.types.is_datetime64_any_dtype(dtype):
        _raise_incompatible_value(predicate, value, dtype)

    if _is_categorical_dtype(dtype):
        _validate_categorical_value(predicate, value, series, ordered=ordered)
        return

    if pd.api.types.is_object_dtype(dtype):
        _validate_object_value(predicate, value, series, ordered=ordered)
        return

    if pd.api.types.is_string_dtype(dtype):
        if isinstance(value, str) and not ordered:
            return
        _raise_incompatible_value(predicate, value, dtype)

    _raise_incompatible_value(predicate, value, dtype)


def _validate_categorical_value(
    predicate: Predicate, value: ScalarValue, series: pd.Series, *, ordered: bool
) -> None:
    """Valida categorías por igualdad/pertenencia, no por orden implícito."""
    if ordered:
        _raise_incompatible_value(predicate, value, series.dtype)
    categories = cast(pd.CategoricalDtype, series.dtype).categories
    compatible_types = tuple(type(category) for category in categories.dropna())
    if not compatible_types or isinstance(value, compatible_types):
        return
    _raise_incompatible_value(predicate, value, series.dtype)


def _validate_object_value(
    predicate: Predicate, value: ScalarValue, series: pd.Series, *, ordered: bool
) -> None:
    """Valida columnas object contra los tipos no nulos observados."""
    observed = series.dropna()
    if observed.empty:
        return
    if _all_observed_string(observed):
        if isinstance(value, str) and not ordered:
            return
        _raise_incompatible_value(predicate, value, series.dtype)
    if _all_observed_numeric(observed):
        if isinstance(value, int | float) and not isinstance(value, bool):
            return
        _raise_incompatible_value(predicate, value, series.dtype)
    if _all_observed_bool(observed):
        if isinstance(value, bool) and not ordered:
            return
        _raise_incompatible_value(predicate, value, series.dtype)
    _raise_incompatible_value(predicate, value, series.dtype)


def _all_observed_string(series: pd.Series) -> bool:
    """Detecta columnas object con valores no nulos puramente textuales."""
    return bool(series.map(lambda item: isinstance(item, str)).all())


def _all_observed_numeric(series: pd.Series) -> bool:
    """Detecta columnas object con valores no nulos puramente numéricos no booleanos."""
    return bool(
        series.map(lambda item: isinstance(item, int | float) and not isinstance(item, bool)).all()
    )


def _all_observed_bool(series: pd.Series) -> bool:
    """Detecta columnas object con valores no nulos puramente booleanos."""
    return bool(series.map(lambda item: isinstance(item, bool)).all())


def _raise_incompatible_value(predicate: Predicate, value: ScalarValue, dtype: object) -> None:
    """Levanta ``ConfigError`` con regla, valor y dtype incompatibles."""
    raise ConfigError(
        "Valor incompatible con el dtype de la columna en regla de target: "
        f"columna='{predicate.col}', operador='{predicate.op}', valor={value!r}, dtype={dtype}."
    )


def _eval_predicate(df: pd.DataFrame, predicate: Predicate) -> pd.Series:
    """Convierte un predicado validado a máscara booleana vectorizada."""
    series = df[predicate.col]
    op = str(predicate.op)

    if op == "isna":
        mask = series.isna()
    elif op == "notna":
        mask = series.notna()
    elif op == "in":
        values = predicate.value
        assert isinstance(values, tuple)
        mask = series.isin(values)
    elif op == "notin":
        values = predicate.value
        assert isinstance(values, tuple)
        mask = ~series.isin(values)
    else:
        value = predicate.value
        assert value is not None
        assert not isinstance(value, tuple)
        if op == "==":
            mask = series.eq(value)
        elif op == "!=":
            mask = series.ne(value)
        elif op == "<":
            mask = series.lt(value)
        elif op == "<=":
            mask = series.le(value)
        elif op == ">":
            mask = series.gt(value)
        elif op == ">=":
            mask = series.ge(value)
        else:  # pragma: no cover - `_validate_predicate` garantiza la allowlist antes de evaluar.
            raise ConfigError(
                "Operador de regla fuera de la allowlist cerrada: "
                f"columna='{predicate.col}', operador='{op}'."
            )
    return mask.fillna(False).astype("bool")


def _count_ambiguous_rows(
    *,
    exclusion_masks: tuple[pd.Series, ...],
    indeterminate_mask: pd.Series | None,
    bad_mask: pd.Series,
    good_mask: pd.Series | None,
) -> int:
    """Cuenta filas que activan más de una regla antes de aplicar precedencia."""
    masks = [*exclusion_masks, bad_mask]
    if indeterminate_mask is not None:
        masks.append(indeterminate_mask)
    if good_mask is not None:
        masks.append(good_mask)

    hits = pd.Series(0, index=bad_mask.index, dtype="int64")
    for mask in masks:
        hits = hits + mask.astype("int64")
    return int((hits > 1).sum())


def _build_summary(
    status: pd.Series, exclusions_by_reason: dict[str, int], ambiguous_rows: int
) -> TargetSummary:
    """Construye conteos por clase, tasa de malos y validaciones de entrenabilidad."""
    counts: dict[str, int] = {label: int((status == label).sum()) for label in STATUS_VALUES}
    good_count = counts["bueno"]
    bad_count = counts["malo"]
    if bad_count == 0 or good_count == 0:
        raise DataValidationError(
            "La definición de target produjo una clase vacía: "
            f"buenos={good_count}, malos={bad_count}. Se requiere al menos un bueno y un malo."
        )

    denominator = good_count + bad_count
    return TargetSummary(
        class_counts=counts,
        bad_rate=bad_count / denominator,
        exclusions_by_reason=exclusions_by_reason,
        ambiguous_rows=ambiguous_rows,
    )


def _true_mask(index: pd.Index) -> pd.Series:
    """Devuelve una máscara ``True`` con el mismo índice que el ``DataFrame``."""
    return pd.Series(True, index=index, dtype=bool)


def _false_mask(index: pd.Index) -> pd.Series:
    """Devuelve una máscara ``False`` con el mismo índice que el ``DataFrame``."""
    return pd.Series(False, index=index, dtype=bool)


def _is_categorical_dtype(dtype: object) -> bool:
    """Detecta dtype categórico sin usar helpers de pandas deprecados."""
    return isinstance(dtype, pd.CategoricalDtype)


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
