"""Config de auditoría persistente (SDD-03 §5)."""

from __future__ import annotations

from pydantic import Field

from nikodym.core.config import NikodymBaseConfig

__all__ = ["AuditConfig"]


class AuditConfig(NikodymBaseConfig):
    """Sub-config de infraestructura para audit-trail y snapshot de entorno."""

    enabled: bool = Field(
        default=True,
        title="Auditoría activa",
        description="Si False, el Study cae al NullAuditSink (sin persistencia de trail).",
    )
    trail_filename: str = Field(
        default="audit_trail.jsonl",
        title="Archivo del audit-trail",
        description="Nombre del JSONL dentro del directorio del run.",
    )
    flush_each: bool = Field(
        default=True,
        title="Flush por evento",
        description=(
            "True: durabilidad por evento (no se pierde el trail ante crash). "
            "False: buffer (más rápido)."
        ),
    )
    capture_environment: bool = Field(
        default=True,
        title="Capturar entorno",
        description="Registrar python/OS/library_versions/uv.lock hash.",
    )
    tracked_packages: tuple[str, ...] | None = Field(
        default=None,
        title="Paquetes a versionar",
        description=(
            "Subconjunto a capturar en library_versions. None = deps declaradas de nikodym."
        ),
    )
