"""Protocols de salida económica de provisión/ECL (SDD-01 §4 ``results.py``, D-CORE-6, CT-2).

Define los contratos de **lectura** mínimos que report/governance consumen de un motor de
provisión, sin acoplar el núcleo a un tipo concreto: son ``Protocol`` (*structural typing*), no
*dataclasses* ni modelos Pydantic. Un tipo concreto en ``core`` invertiría la dependencia
(forzaría a ``provisioning/cmf`` e ``ifrs9`` a importar/heredar un tipo económico de ``core``) y
reabriría la circularidad que el Protocol resuelve (D-CORE-6). ``CMF`` e ``IFRS 9`` son dos motores
**separados** (§5.4); la herencia ``ECLResultLike`` ← ``ProvisionResultLike`` es solo reutilización
del contrato de lectura, no parentesco de dominio. ``core`` no importa pandas en *runtime*
(D-CORE-1): las anotaciones de ``pandas.DataFrame`` viven bajo ``TYPE_CHECKING``.

**Experimental (fuera de la garantía SemVer 1.x):** estos contratos crecen por extensión
aditiva (CT-2), nunca por ruptura, en las versiones 1.x. ``@runtime_checkable`` solo verifica
la *presencia* de los nombres (no tipos ni firmas), pensado para *asserts* defensivos; la
verificación estructural real es estática (mypy).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["ECLResultLike", "ProvisionResultLike"]


@runtime_checkable
class ProvisionResultLike(Protocol):
    """Contrato mínimo de la salida de provisión que leen report/governance.

    ``@runtime_checkable`` solo verifica la *presencia* de estos nombres (no tipos ni firmas),
    pensado para *asserts* defensivos; la verificación estructural real es estática (mypy --strict).
    ``core`` no calcula riesgo (§1): el invariante ``PE = PI·PDI·exposición`` lo valida el dominio
    (SDD-15), no este Protocol.
    """

    componentes: pd.DataFrame
    total: float
    por_cartera: Mapping[str, float]
    motor: str

    def to_frame(self) -> pd.DataFrame:
        """Vista tabular plana para report/export (no materializa hasta pedirlo)."""
        ...

    def term_structure(self) -> pd.DataFrame | None:
        """Puerta de extensión temporal (CT-2, Hito 0).

        Devuelve ``None`` si el motor no es multi-período (CMF agregado, scoring) y un
        ``DataFrame`` *tidy* ``[escenario, t, componente, valor]`` si lo es (ECL *lifetime*, F4). El
        *shape* interno lo fija SDD-16; aquí solo se garantiza que el contrato crezca por extensión
        (aditivo) y nunca por ruptura. report/governance lo consultan sin reabrir el motor.
        """
        ...


@runtime_checkable
class ECLResultLike(ProvisionResultLike, Protocol):
    """Salida específica de IFRS 9 (ECL); extiende el contrato de lectura de provisión.

    La herencia ``ECLResultLike`` ← ``ProvisionResultLike`` es reutilización del contrato de lectura
    (``total``/``componentes``/``to_frame``), **no** parentesco de dominio: CMF e IFRS 9 son dos
    motores separados (§5.4). SDD-17 compara fuentes configurables; el binding B-1 usa estándar
    CMF frente a método interno, no estos Protocols.
    Heredar también de ``Protocol`` es obligatorio para que ``ECLResultLike`` siga siendo protocolo.
    """

    por_instrumento: pd.DataFrame
    por_escenario: Mapping[str, float]
