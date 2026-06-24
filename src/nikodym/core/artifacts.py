"""Almacén *namespaced* de artefactos de una corrida (SDD-01 §4/§6/§7).

El :class:`ArtifactStore` guarda los productos intermedios de un ``Study`` bajo una clave
``(domain, key)`` en memoria, y emite un :class:`~nikodym.core.audit.AuditEvent` ``"artifact"`` por
cada escritura (creación o sobrescritura) hacia el *sink* inyectado por el ``Study``. La
serialización a disco (pickle/joblib) se **difiere a F3** (deuda con *owner* del Hito 0): en F0 el
*store* es sólo la estructura ``(domain, key) → valor`` en memoria.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nikodym.core.audit import AuditEvent, AuditSink, NullAuditSink
from nikodym.core.exceptions import ArtifactExistsError, ArtifactNotFoundError

__all__ = ["ArtifactStore"]


class ArtifactStore:
    """Contenedor *namespaced* ``(domain, key) → valor`` con traza de auditoría por escritura.

    El ``Study`` inyecta el *sink* de auditoría; si no se pasa, cae a ``NullAuditSink`` (nunca
    ``None``), de modo que emitir es siempre seguro. ``get`` devuelve el **mismo** objeto guardado
    (identidad, sin copia defensiva).
    """

    def __init__(self, audit: AuditSink | None = None) -> None:
        self._store: dict[tuple[str, str], Any] = {}
        self._audit: AuditSink = audit if audit is not None else NullAuditSink()

    def set(self, domain: str, key: str, value: Any, *, overwrite: bool = False) -> None:
        """Escribe ``value`` bajo ``(domain, key)`` y emite un ``AuditEvent`` ``"artifact"``.

        Si la clave ya existe y ``overwrite=False``, levanta
        :class:`~nikodym.core.exceptions.ArtifactExistsError`. El ``payload`` del evento distingue
        creación de sobrescritura con el campo ``overwrite`` (trazabilidad SR 11-7). Convención del
        evento ``"artifact"``: ``step`` lleva el ``domain`` del artefacto (no el paso que lo
        escribió) y ``payload`` el ``(domain, key)`` completo; SDD-03 lo consume sin adivinar.
        """
        clave = (domain, key)
        ya_existe = clave in self._store
        if ya_existe and not overwrite:
            raise ArtifactExistsError(
                f"Artefacto ('{domain}', '{key}') ya existe; pase overwrite=True para reescribir."
            )
        self._store[clave] = value
        self._audit.emit(
            AuditEvent(
                kind="artifact",
                step=domain,
                payload={"domain": domain, "key": key, "overwrite": ya_existe},
                ts=datetime.now(UTC),
            )
        )

    def get(self, domain: str, key: str) -> Any:
        """Devuelve el artefacto ``(domain, key)`` (el mismo objeto); ausente → error."""
        clave = (domain, key)
        if clave not in self._store:
            raise ArtifactNotFoundError(
                f"No existe el artefacto ('{domain}', '{key}') en el ArtifactStore."
            )
        return self._store[clave]

    def has(self, domain: str, key: str) -> bool:
        """Indica si la clave ``(domain, key)`` está presente."""
        return (domain, key) in self._store

    def keys(self) -> list[tuple[str, str]]:
        """Lista las claves ``(domain, key)`` presentes, en orden de inserción."""
        return list(self._store)
