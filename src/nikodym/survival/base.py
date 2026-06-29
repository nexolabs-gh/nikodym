"""Contrato base para modelos de survival Nikodym (SDD-18 §4).

El paquete ``survival`` usa una API propia porque su entrada combina duración, evento y grilla
temporal; no calza con un único ``predict`` estilo sklearn. Este módulo mantiene solo tipos y
contratos livianos: no importa pandas, lifelines ni statsmodels en runtime.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar, Protocol, Self, runtime_checkable

from nikodym.survival.config import SurvivalConfig

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.audit import AuditSink

__all__ = ["BaseSurvivalModel"]


@runtime_checkable
class BaseSurvivalModel(Protocol):
    """Contrato mínimo para modelos de survival Nikodym."""

    config_cls: ClassVar[type[SurvivalConfig]]

    def fit(
        self,
        frame: pd.DataFrame,
        *,
        duration_col: str,
        event_col: str,
        covariate_cols: tuple[str, ...] = (),
        pd_frame: pd.DataFrame | None = None,
        audit: AuditSink | None = None,
    ) -> Self:
        """Ajusta el modelo survival sobre duración, evento y covariables declaradas."""
        ...

    def predict_survival(
        self,
        frame: pd.DataFrame,
        *,
        times: Sequence[int | float],
    ) -> pd.DataFrame:
        """Predice curvas de supervivencia ``S(t)`` en los tiempos solicitados."""
        ...

    def predict_hazard(
        self,
        frame: pd.DataFrame,
        *,
        times: Sequence[int | float],
    ) -> pd.DataFrame:
        """Predice hazards ``h(t)`` en los tiempos solicitados."""
        ...

    def term_structure(
        self,
        frame: pd.DataFrame,
        *,
        times: Sequence[int | float],
    ) -> pd.DataFrame:
        """Publica la term-structure tidy de PD lifetime para consumo aguas abajo."""
        ...
