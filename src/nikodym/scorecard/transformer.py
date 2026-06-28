"""Transformer sklearn-like de scorecard log-odds a puntos (SDD-09 §4).

La clase ``Scorecard`` añade la herencia de scikit-learn sobre el núcleo ``PointsScaler``. Este
módulo se carga bajo demanda desde ``nikodym.scorecard.__getattr__``; por eso la ausencia de
scikit-learn se traduce aquí a ``MissingDependencyError`` sin contaminar
``import nikodym.scorecard``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeAlias

from nikodym.core.exceptions import MissingDependencyError
from nikodym.scorecard.exceptions import ScorecardFitError
from nikodym.scorecard.scaler import PointsScaler

_SCORING_EXTRA_MESSAGE = "Scorecard requiere scikit-learn; instale nikodym[scoring]."

try:
    from sklearn.base import BaseEstimator, TransformerMixin  # type: ignore[import-untyped]
except ModuleNotFoundError as exc:
    raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.audit import AuditSink

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditSink: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["Scorecard"]


class Scorecard(PointsScaler, TransformerMixin, BaseEstimator):  # type: ignore[misc]
    """Transformer sklearn-like que publica puntos por variable y score total."""

    def fit_from_artifacts(
        self,
        *,
        model_result: object | None = None,
        binning_result: object | None = None,
        coefficients: DataFrame | None = None,
        final_features: tuple[str, ...] | None = None,
        final_woe_columns: tuple[str, ...] | None = None,
        binning_tables: Mapping[str, DataFrame] | None = None,
        woe_column_map: Mapping[str, str] | None = None,
        audit: AuditSink | None = None,
    ) -> Scorecard:
        """Ajusta el scorecard desde DTOs de ``model``/``binning`` o artefactos explícitos."""
        if model_result is not None:
            coefficients = _from_attr(model_result, "coefficients", coefficients)
            final_features = _from_attr(model_result, "final_features", final_features)
            final_woe_columns = _from_attr(model_result, "final_woe_columns", final_woe_columns)
        if binning_result is not None:
            binning_tables = _from_attr(binning_result, "tables", binning_tables)
            woe_column_map = _from_attr(binning_result, "woe_column_map", woe_column_map)

        if coefficients is None:
            raise ScorecardFitError("fit_from_artifacts requiere coefficients o model_result.")
        if final_features is None:
            raise ScorecardFitError("fit_from_artifacts requiere final_features o model_result.")
        if final_woe_columns is None:
            raise ScorecardFitError("fit_from_artifacts requiere final_woe_columns o model_result.")
        if binning_tables is None:
            raise ScorecardFitError("fit_from_artifacts requiere binning_tables o binning_result.")
        if woe_column_map is None:
            raise ScorecardFitError("fit_from_artifacts requiere woe_column_map o binning_result.")

        return self.fit(
            coefficients=coefficients,
            final_features=tuple(final_features),
            final_woe_columns=tuple(final_woe_columns),
            binning_tables=binning_tables,
            woe_column_map=woe_column_map,
            audit=audit,
        )


def _from_attr(objeto: object, nombre: str, actual: Any) -> Any:
    """Devuelve ``actual`` si ya existe; si no, lee un atributo estructural."""
    if actual is not None:
        return actual
    if not hasattr(objeto, nombre):
        raise ScorecardFitError(f"El artefacto no expone el atributo requerido: {nombre}.")
    return getattr(objeto, nombre)
