"""Persistencia JSONL append-only del audit-trail (SDD-03 §4/§6)."""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import TextIO

from nikodym.audit.config import AuditConfig
from nikodym.audit.exceptions import AuditError
from nikodym.core.audit import AuditEvent

__all__ = ["JsonlAuditSink"]


class JsonlAuditSink:
    """Sink que persiste el audit-trail a un archivo JSONL append-only."""

    def __init__(
        self,
        path: str | Path,
        *,
        config: AuditConfig | None = None,
        flush_each: bool = True,
    ) -> None:
        """Abre ``path`` en modo append, creando directorios padres si hace falta."""
        self.path = Path(path)
        self.flush_each = config.flush_each if config is not None else flush_each
        self._handle: TextIO | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
        except OSError as exc:
            raise AuditError(f"No se pudo abrir el audit-trail '{self.path}': {exc}") from exc

    def emit(self, event: AuditEvent) -> None:
        """Serializa ``event`` como una línea JSON canónica y la añade al trail."""
        handle = self._open_handle()
        line = json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            handle.write(f"{line}\n")
            if self.flush_each:
                handle.flush()
        except OSError as exc:
            raise AuditError(f"No se pudo escribir en el audit-trail '{self.path}': {exc}") from exc

    def close(self) -> None:
        """Cierra el archivo de forma idempotente."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> JsonlAuditSink:
        """Devuelve el sink abierto para usarlo como context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Cierra el archivo al salir del context manager."""
        self.close()

    def _open_handle(self) -> TextIO:
        """Devuelve el handle abierto o falla ruidoso si ya fue cerrado."""
        if self._handle is None:
            raise AuditError(f"El audit-trail '{self.path}' ya está cerrado; no se puede emitir.")
        return self._handle
