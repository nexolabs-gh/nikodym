"""Identidad criptográfica del config: ``config_hash`` y las secciones excluidas (SDD-01 §5).

``config_hash`` es el SHA-256 del JSON canónico de las secciones **computacionales** del config
(datos + método + semilla). Excluye las secciones de infraestructura (:data:`INFRA_SECTIONS`):
cambiar el nombre del estudio, el destino de tracking o el reporte **no** altera la identidad de
la corrida, lo que mantiene idempotente el inventario de modelos. El hash es canónico y estable
entre versiones de Pydantic/Python y entre máquinas: el orden de claves lo fija
``json.dumps(sort_keys=True)``, no el orden de declaración de los campos.

Además de las secciones INFRA, se excluye la **ruta** del dataset (``data.load.source``): es un dato
incidental, no la identidad LÓGICA de la corrida. El :func:`data_hash` ya captura el **contenido**
del dataset, así que el mismo dato en otra ruta (o el preset con ``source=None`` frente a la corrida
con la ruta real) debe producir el MISMO ``config_hash``. Incluir la ruta era un defecto que rompía
esa equivalencia y desalineaba el hash entre la app y el informe.

**Estabilidad (SemVer):** el algoritmo de canonicalización es estable dentro de 1.x. La exclusión de
``data.load.source`` se introdujo en **1.4.0** como corrección de defecto: recalcula la identidad de
los configs que fijaban una ruta de dataset (antes la ruta contaminaba el hash). El hash del config
por defecto no cambia (``data`` es ``None``).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nikodym.core.config.schema import NikodymConfig

__all__ = ["INFRA_SECTIONS", "config_hash"]

# Secciones de infraestructura excluidas del config_hash (no afectan la identidad de la corrida).
INFRA_SECTIONS: frozenset[str] = frozenset({"name", "governance", "audit", "tracking", "report"})


def _hash_exclude() -> dict[str, Any]:
    """Exclusión efectiva del hash: las secciones INFRA completas + la ruta ``data.load.source``.

    Se construye por llamada (dict mutable) para no exponer un singleton mutable. La ruta del
    dataset se excluye de forma **anidada** (``{"data": {"load": {"source": True}}}``): sólo cae ese
    campo, el resto de ``data`` (panel transversal, columnas, particiones…) sí entra a la identidad.
    """
    exclude: dict[str, Any] = dict.fromkeys(INFRA_SECTIONS, True)
    exclude["data"] = {"load": {"source": True}}
    return exclude


def config_hash(cfg: NikodymConfig) -> str:
    """Devuelve el SHA-256 hex (64 chars) del JSON canónico de las secciones computacionales.

    Parameters
    ----------
    cfg : NikodymConfig
        Config ya validado del que derivar la identidad.

    Returns
    -------
    str
        Digest hexadecimal SHA-256 del config sin las :data:`INFRA_SECTIONS` ni la ruta
        ``data.load.source`` (la identidad depende del CONTENIDO del dato, vía ``data_hash``, no de
        su ubicación en disco).
    """
    payload = cfg.model_dump(mode="json", by_alias=True, exclude=_hash_exclude())
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
