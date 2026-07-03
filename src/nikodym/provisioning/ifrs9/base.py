"""Contrato base del motor económico ECL Nikodym (SDD-16 §6 / ESPEC §6.1).

El motor IFRS 9 usa una API propia porque su salida no es un ``predict`` escalar sino una salida
económica multi-componente (staging, ECL 12m/lifetime, term-structure por escenario/período). Este
módulo mantiene solo tipos y contratos livianos: no importa ``pandas``, ``scipy`` ni
``statsmodels`` en runtime, para no romper el import liviano del núcleo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.audit import AuditSink
    from nikodym.provisioning.ifrs9.config import IfrsProvisioningConfig
    from nikodym.provisioning.ifrs9.results import IfrsProvisionResult

__all__ = ["BaseEclModel"]


@runtime_checkable
class BaseEclModel(Protocol):
    """Contrato mínimo del motor económico ECL Nikodym (ESPEC §6.1)."""

    config_cls: ClassVar[type[IfrsProvisioningConfig]]

    @classmethod
    def from_config(cls, cfg: IfrsProvisioningConfig) -> Self:
        """Construye el motor ECL desde su sub-config ``provisioning_ifrs9`` validado."""
        ...

    def calculate(
        self,
        frame: pd.DataFrame,
        *,
        term_structure: pd.DataFrame,
        calibrated_pd: pd.DataFrame | None = None,
        as_of_date: str,
        audit: AuditSink | None = None,
    ) -> IfrsProvisionResult:
        """Calcula la ECL IFRS 9 (PD PIT/lifetime, LGD, EAD, staging, motor ECL) por operación.

        Consume el ``frame`` económico y la ``term_structure`` lifetime tidy del proveedor
        configurado (survival/markov/forward), con ``calibrated_pd`` opcional como PD 12m base, y
        publica un :class:`~nikodym.provisioning.ifrs9.results.IfrsProvisionResult`.
        """
        ...
