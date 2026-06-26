"""Especificaciones declarativas de figuras para ``eda`` (SDD-27 §4/§6/§10).

``eda`` decide qué tablas agregadas conviene graficar, pero no renderiza imágenes ni importa
motores gráficos. SDD-26 (`report`) consumirá estas recetas y resolverá el backend visual.

DECISIÓN AUTÓNOMA (frontera, revisión de Cami): el contrato se fija con los campos de SDD-27
§4/§6. El extra y motor de gráficos quedan diferidos a SDD-25/26; este módulo no importa
matplotlib ni plotly.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Final, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.eda.default_rate import DefaultRateResult
from nikodym.eda.univariate import UnivariateResult

__all__ = ["FigureSpec"]

_DEFAULT_RATE_FIGURE_COLUMNS: Final = ("period", "default_rate")
_UNIVARIATE_FIGURE_COLUMNS: Final = ("tramo", "default_rate")


class FigureSpec(BaseModel):
    """Receta declarativa de figura para que ``report`` la renderice."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    kind: Literal["line", "bar", "heatmap"]
    title: str
    data: pd.DataFrame
    x: str
    y: str
    series: str | None = None


def _build_figure_specs(
    *,
    default_rate: DefaultRateResult,
    univariate: UnivariateResult,
) -> tuple[FigureSpec, ...]:
    """Construye las figuras especificadas por SDD-27 §6, sin renderizar."""
    figures: list[FigureSpec] = []
    if default_rate.axis == "period":
        figures.append(_default_rate_line(default_rate))
    figures.extend(_univariate_bars(univariate))
    return tuple(figures)


def _default_rate_line(default_rate: DefaultRateResult) -> FigureSpec:
    """Figura de línea de tasa de default por período."""
    data = default_rate.by_period.loc[:, list(_DEFAULT_RATE_FIGURE_COLUMNS)].copy(deep=True)
    return FigureSpec(
        kind="line",
        title="Tasa de default por período",
        data=data,
        x="period",
        y="default_rate",
    )


def _univariate_bars(univariate: UnivariateResult) -> tuple[FigureSpec, ...]:
    """Figuras de barras de tasa de default por tramo univariado."""
    return tuple(
        _univariate_bar(column, univariate.profiles[column])
        for column in _ordered_univariate_columns(univariate)
    )


def _ordered_univariate_columns(univariate: UnivariateResult) -> tuple[str, ...]:
    """Ordena por IV descriptivo si existe; si no, conserva el orden de perfilado."""
    if not univariate.descriptive_iv:
        return tuple(univariate.profiles)
    return tuple(
        sorted(
            univariate.profiles,
            key=lambda column: (-univariate.descriptive_iv.get(column, float("-inf")), column),
        )
    )


def _univariate_bar(column: str, profile: pd.DataFrame) -> FigureSpec:
    """Figura de barras para una columna perfilada."""
    data = profile.loc[:, list(_UNIVARIATE_FIGURE_COLUMNS)].copy(deep=True)
    return FigureSpec(
        kind="bar",
        title=f"Tasa de default por tramo: {column}",
        data=data,
        x="tramo",
        y="default_rate",
    )
