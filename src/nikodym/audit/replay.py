"""Replay del audit-trail JSONL persistido (SDD-03 §4/§8)."""

from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from nikodym.audit.exceptions import AuditError
from nikodym.core.audit import AuditEvent

__all__ = ["iter_trail", "read_trail"]


def iter_trail(path: str | Path) -> Iterator[AuditEvent]:
    """Itera eventos del trail, descartando líneas finales corruptas por crash."""
    ruta = Path(path)
    pending_tail_errors: list[int] = []
    last_error: BaseException | None = None
    try:
        with ruta.open(encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                try:
                    event = AuditEvent.model_validate(json.loads(line))
                except (json.JSONDecodeError, ValidationError) as exc:
                    pending_tail_errors.append(lineno)
                    last_error = exc
                    continue
                if pending_tail_errors:
                    first = pending_tail_errors[0]
                    raise AuditError(
                        f"Audit-trail '{ruta}' corrupto en línea intermedia {first}: "
                        "hay eventos válidos después de la corrupción."
                    ) from last_error
                yield event
    except OSError as exc:
        raise AuditError(f"No se pudo leer el audit-trail '{ruta}': {exc}") from exc

    if pending_tail_errors:
        warnings.warn(
            f"Se descartaron {len(pending_tail_errors)} línea(s) finales corruptas del "
            f"audit-trail '{ruta}'.",
            stacklevel=2,
        )


def read_trail(path: str | Path) -> list[AuditEvent]:
    """Lee todo el trail JSONL y devuelve una lista de ``AuditEvent`` revalidados."""
    return list(iter_trail(path))
