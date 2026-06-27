"""Resultados del binning supervisado WoE/IV (SDD-06 §4).

``BinningResult`` y ``BinningCardSection`` son contenedores de salida: reciben tablas y métricas ya
calculadas por el futuro ``BinningStep``/``WoEBinner`` y no ejercen ``optbinning`` en runtime. Este
módulo puede importar ``pandas`` porque pertenece al dominio ``binning``; el paquete
``nikodym.binning`` lo reexporta de forma perezosa para preservar el import liviano.

Decisiones para revisión de Cami:
- La banda de IV se resuelve con un helper puro, fail-fast ante valores no defendibles.
- ``BinningCardSection.from_result`` deriva solo agregados deterministas del resultado recibido.
- ``optbinning_version`` entra como parámetro explícito; aquí no se importa ``optbinning``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import math
from typing import Literal, TypeAlias

import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.binning.exceptions import BinningError

IvBand: TypeAlias = Literal["none", "weak", "medium", "strong", "suspicious"]

__all__ = ["BinningCardSection", "BinningResult", "BinningVariableSummary", "iv_band"]


def iv_band(iv: float) -> IvBand:
    """Clasifica el Information Value en bandas diagnósticas de SDD-06 §3.

    Fronteras con límite inferior inclusivo: ``none`` para IV < 0.02, ``weak`` para
    0.02 <= IV < 0.10, ``medium`` para 0.10 <= IV < 0.30, ``strong`` para
    0.30 <= IV < 0.50 y ``suspicious`` para IV >= 0.50. SDD-06 §8 confirma que
    IV=0 pertenece a ``none``.

    Raises
    ------
    BinningError
        Si ``iv`` es negativo, NaN o infinito.
    """
    if not math.isfinite(iv) or iv < 0.0:
        raise BinningError(f"IV inválido para banda diagnóstica: valor observado={iv!r}.")

    if iv < 0.02:
        return "none"
    if iv < 0.10:
        return "weak"
    if iv < 0.30:
        return "medium"
    if iv < 0.50:
        return "strong"
    return "suspicious"


class BinningVariableSummary(BaseModel):
    """Resumen auditable de una variable procesada por binning."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    name: str
    dtype: Literal["numerical", "categorical"]
    status: str
    selected: bool
    n_bins: int
    iv: float
    iv_band: IvBand
    monotonic_trend: str | None
    skipped_reason: str | None = None


class BinningResult(BaseModel):
    """Contenedor agregado de las salidas principales de ``binning``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    woe_frame: pd.DataFrame
    tables: dict[str, pd.DataFrame]
    summary: pd.DataFrame
    variable_summaries: tuple[BinningVariableSummary, ...]
    woe_column_map: dict[str, str]
    skipped_variables: dict[str, str]


class BinningCardSection(BaseModel):
    """Resumen compacto de ``binning`` para model card y reporte."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    n_variables_requested: int
    n_variables_binned: int
    n_variables_skipped: int
    iv_by_variable: dict[str, float]
    monotonicity_by_variable: dict[str, str | None]
    special_handling: str
    missing_handling: str
    optbinning_version: str

    @classmethod
    def from_result(
        cls,
        result: BinningResult,
        *,
        special_handling: str,
        missing_handling: str,
        optbinning_version: str,
    ) -> BinningCardSection:
        """Deriva una sección de model card sin recalcular ni mutar el resultado."""
        n_variables_binned = len(result.variable_summaries)
        n_variables_skipped = len(result.skipped_variables)
        return cls(
            n_variables_requested=n_variables_binned + n_variables_skipped,
            n_variables_binned=n_variables_binned,
            n_variables_skipped=n_variables_skipped,
            iv_by_variable={summary.name: summary.iv for summary in result.variable_summaries},
            monotonicity_by_variable={
                summary.name: summary.monotonic_trend for summary in result.variable_summaries
            },
            special_handling=special_handling,
            missing_handling=missing_handling,
            optbinning_version=optbinning_version,
        )
