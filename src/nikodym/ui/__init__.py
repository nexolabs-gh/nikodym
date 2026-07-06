"""Capa ``ui`` (SDD-23): backend FastAPI + lógica pura del editor de config y visor.

``import nikodym.ui`` es **liviano**: expone las excepciones y :class:`UiConfig`, pero **NO**
importa FastAPI ni :mod:`nikodym.ui.server`. El import de FastAPI es **perezoso** y vive solo en
:func:`nikodym.ui.server.create_app` tras el extra ``[ui]``. El núcleo (``core``/dominios) nunca
importa esta capa (ESPEC §6.1); el backend es *domain-agnostic* (no importa ``binning``/``model``),
lee el schema de ``NikodymConfig`` y valida por reconstrucción (SDD-23 §1, §4.2).
"""

from nikodym.ui.exceptions import (
    UiDatasetError,
    UiDependencyError,
    UiError,
    UiSerializationError,
)
from nikodym.ui.settings import UiConfig

__all__ = [
    "UiConfig",
    "UiDatasetError",
    "UiDependencyError",
    "UiError",
    "UiSerializationError",
]
