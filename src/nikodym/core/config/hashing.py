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


def _coaccionar_secciones_opacas(cfg: NikodymConfig) -> NikodymConfig:
    """Devuelve el config con sus secciones de dominio coaccionadas (D-HASH-1).

    La identidad de una corrida es la del config que **se ejecutaría**, no la del que se escribió.
    Coaccionar una sección es *normalizarla*: materializa los defaults que el dict no traía y fija
    los tipos. Sin la capa importada no hay normalización, así que el mismo config produce dos
    digests distintos según el orden de los ``import`` del proceso — que es el defecto que esta
    función cierra.

    Es la misma semántica que el lineage ya adoptó al arreglar el P0 de ``edb3773`` (se congela
    **después** de resolver, o sea sobre el config coaccionado). Tener dos identidades para el mismo
    config conviviendo en la librería era la incoherencia.

    Camino rápido: si ninguna sección llegó opaca —el caso normal, con las capas ya importadas— se
    devuelve el config tal cual y no se importa nada.

    **``config_hash`` sigue siendo total** (D-HASH-8): si la coacción falla —una sección opaca con
    un campo inexistente o fuera de rango, que el blob aceptaba por no conocer su schema— se
    devuelve el config sin coaccionar en lugar de propagar el ``ValidationError``. Hacer fallable
    una función de identidad rompería llamadores que hoy funcionan (``/api/validate`` responde 200
    siempre; ``Study`` la usa al ensamblar el lineage). Y no se pierde nada: un config que no
    coacciona no se puede ejecutar, así que su identidad no ancla ninguna corrida — el mismo
    argumento de D-HASH-3. Quien reporta el error es el validador, no el hash.
    """
    # Import perezoso por la misma razón que en ``build_full_json_schema``: ``core.config`` no
    # arrastra dominios (núcleo liviano, SDD-23 §4.1/§9).
    from pydantic import ValidationError

    from nikodym.core.config.schema import NikodymConfig as _NikodymConfig
    from nikodym.core.config.schema import cargar_configs_de_dominio
    from nikodym.core.study import _DOMAIN_CONFIG_CLASSES

    if not any(isinstance(getattr(cfg, nombre, None), dict) for nombre in _DOMAIN_CONFIG_CLASSES):
        return cfg

    cargar_configs_de_dominio()
    try:
        return _NikodymConfig.model_validate(cfg.model_dump(mode="json", by_alias=True))
    except ValidationError:
        return cfg


def config_hash(cfg: NikodymConfig) -> str:
    """Devuelve el SHA-256 hex (64 chars) del JSON canónico de las secciones computacionales.

    Las secciones de dominio que lleguen **opacas** (un ``dict``, porque el proceso aún no importó
    esa capa) se coaccionan antes de canonicalizar, de modo que el digest no dependa del orden de
    los ``import``. Ver :func:`_coaccionar_secciones_opacas` y D-HASH-1.

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
    cfg = _coaccionar_secciones_opacas(cfg)
    payload = cfg.model_dump(mode="json", by_alias=True, exclude=_hash_exclude())
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
