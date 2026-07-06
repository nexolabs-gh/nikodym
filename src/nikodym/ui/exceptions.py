"""Jerarquía de excepciones de la capa ``ui`` (SDD-23 §4.3).

Toda excepción propia de la UI desciende de :class:`UiError` y, por tanto, de
:class:`~nikodym.core.exceptions.NikodymError`: ``except NikodymError`` captura cualquier fallo
de la librería sin enumerar clases. Los mensajes van en **español** e indican la acción, el
artefacto afectado y la causa; los identificadores/API se mantienen en inglés técnico.
"""

from __future__ import annotations

from nikodym.core.exceptions import NikodymError

__all__ = [
    "UiDatasetError",
    "UiDependencyError",
    "UiError",
    "UiSerializationError",
]


class UiError(NikodymError):
    """Raíz de las excepciones de la capa ``ui`` (subclase de ``NikodymError``)."""


class UiDatasetError(UiError):
    """Dataset sintético desconocido, subida inválida o ruta fuera del ``workdir``."""


class UiSerializationError(UiError):
    """Artefacto no serializable a JSON (p. ej. un no-finito colado); falla ruidoso defensivo."""


class UiDependencyError(UiError):
    """Falta el extra ``[ui]`` (fastapi/uvicorn); el mensaje pide ``instale nikodym[ui]``."""
