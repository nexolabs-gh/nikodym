"""Identidad criptográfica del config: ``config_hash`` y las secciones excluidas (SDD-01 §5).

``config_hash`` es el SHA-256 del JSON canónico de las secciones **computacionales** del config
(datos + método + semilla). Excluye las secciones de infraestructura (:data:`INFRA_SECTIONS`):
cambiar el nombre del estudio, el destino de tracking o el reporte **no** altera la identidad de
la corrida, lo que mantiene idempotente el inventario de modelos. El hash es canónico y estable
entre versiones de Pydantic/Python y entre máquinas: el orden de claves lo fija
``json.dumps(sort_keys=True)``, no el orden de declaración de los campos.
**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nikodym.core.config.schema import NikodymConfig

__all__ = ["INFRA_SECTIONS", "config_hash"]

# Secciones de infraestructura excluidas del config_hash (no afectan la identidad de la corrida).
INFRA_SECTIONS: frozenset[str] = frozenset({"name", "governance", "audit", "tracking", "report"})


def config_hash(cfg: NikodymConfig) -> str:
    """Devuelve el SHA-256 hex (64 chars) del JSON canónico de las secciones computacionales.

    Parameters
    ----------
    cfg : NikodymConfig
        Config ya validado del que derivar la identidad.

    Returns
    -------
    str
        Digest hexadecimal SHA-256 del config sin las :data:`INFRA_SECTIONS`.
    """
    payload = cfg.model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
