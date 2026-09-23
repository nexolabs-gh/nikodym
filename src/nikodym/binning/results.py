"""Resultados del binning supervisado WoE/IV (SDD-06 §4).

``BinningResult`` y ``BinningCardSection`` son contenedores de salida: reciben tablas y métricas ya
calculadas por el futuro ``BinningStep``/``WoEBinner`` y no ejercen ``optbinning`` en runtime. Este
módulo puede importar ``pandas`` porque pertenece al dominio ``binning``; el paquete
``nikodym.binning`` lo reexporta de forma perezosa para preservar el import liviano.

Decisiones para revisión de Cami:
- La banda de IV se resuelve con un helper puro, fail-fast ante valores no defendibles.
- ``BinningCardSection.from_result`` deriva solo agregados deterministas del resultado recibido.
- ``optbinning_version`` entra como parámetro explícito; aquí no se importa ``optbinning``.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import math
from typing import Any, Literal, TypeAlias

import pandas as pd
from pydantic import BaseModel, ConfigDict

from nikodym.binning.exceptions import BinningError

IvBand: TypeAlias = Literal["none", "weak", "medium", "strong", "suspicious"]

#: Rótulo público de cada banda de IV: la **única** fuente de esas cinco palabras (D-SC-10). Son
#: las que el glosario del sitio ya publica; el slug sigue siendo el dato del JSON. El espejo del
#: panel de selección vive en ``web/src/lib/results-format.ts`` y lo gatea
#: ``tests/unit/test_vocabulario_en_pantalla.py`` en los dos sentidos.
IV_BAND_LABELS: dict[str, str] = {
    "none": "sin poder",
    "weak": "débil",
    "medium": "medio",
    "strong": "fuerte",
    "suspicious": "sospechoso",
}

__all__ = [
    "IV_BAND_LABELS",
    "AssignedBin",
    "BinningCardSection",
    "BinningResult",
    "BinningVariableSummary",
    "RareCategoryRegrouping",
    "iv_band",
]


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


class RareCategoryRegrouping(BaseModel):
    """Una categórica que el motor reagrupó para que su WoE exista (D-RAR-1/2).

    El corte de categorías raras dejó **un solo** nivel por debajo y ese nivel quedó sin una de las
    dos clases en las filas que se ajustaron: el grupo de «raras» que debía protegerlo era
    unitario. El motor reajustó esa columna **una vez** con el menor corte que deja dos niveles
    debajo. Los conteos son los del bin degenerado en la tabla del ajuste —las filas de
    desarrollo—, no los del archivo.

    El corte efectivo es un **resultado**, como el IV: el config guardado conserva el declarado y
    el ``config_hash`` identifica lo que el usuario declaró. La reproducibilidad la da que la regla
    es determinista.
    """

    model_config = ConfigDict(frozen=True)

    levels: tuple[str, ...]
    n_obs: int
    n_events: int
    declared_cat_cutoff: float | None
    effective_cat_cutoff: float


class AssignedBin(BaseModel):
    """Un bin de faltantes o especiales al que el motor **asignó** su WoE (D-FAL-1/2).

    El bin tenía operaciones y una de las dos clases en cero en las filas ajustadas, así que su WoE
    empírico no existe. Recibe el del tramo regular de mayor tasa de malos observada de la misma
    variable —el de menor WoE; ante un empate, la primera fila—, con IV 0 en su fila, y comparte
    sus puntos. Los conteos son **operaciones** de las filas ajustadas, sin pesos.
    """

    model_config = ConfigDict(frozen=True)

    variable: str
    bin: Literal["Missing", "Special"]
    n_obs: int
    n_events: int
    assigned_woe: float
    reference_bin: str


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
    excluded_by_target_rule: tuple[str, ...] = ()
    #: Aditivo (D-RAR-2): las categóricas que el motor reagrupó para que su WoE exista, con el
    #: corte declarado y el efectivo. Vacío en toda corrida en la que la regla no entró.
    rare_category_regroupings: dict[str, RareCategoryRegrouping] = {}
    #: Aditivo (D-FAL-2): una entrada por par (variable, bin) de faltantes o especiales cuyo WoE
    #: se asignó. Vacío en toda corrida en la que la regla no entró.
    assigned_bins: tuple[AssignedBin, ...] = ()

    def __setstate__(self, state: dict[Any, Any]) -> None:
        """Migra cards serializadas antes de la evidencia anti-fuga, de D-RAR y de D-FAL."""
        values = state.get("__dict__", {})
        faltantes: dict[str, object] = {
            campo: vacio
            for campo, vacio in (
                ("excluded_by_target_rule", ()),
                ("rare_category_regroupings", {}),
                ("assigned_bins", ()),
            )
            if campo not in values
        }
        if faltantes:
            state = {**state, "__dict__": {**values, **faltantes}}
        super().__setstate__(state)

    @classmethod
    def from_result(
        cls,
        result: BinningResult,
        *,
        special_handling: str,
        missing_handling: str,
        optbinning_version: str,
        excluded_by_target_rule: tuple[str, ...] = (),
        rare_category_regroupings: dict[str, RareCategoryRegrouping] | None = None,
        assigned_bins: tuple[AssignedBin, ...] = (),
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
            excluded_by_target_rule=excluded_by_target_rule,
            rare_category_regroupings=dict(rare_category_regroupings or {}),
            assigned_bins=tuple(assigned_bins),
        )
