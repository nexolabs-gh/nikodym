"""Captura determinista del entorno de ejecución (SDD-03 §4/§7)."""

from __future__ import annotations

import platform as _platform
import warnings
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from nikodym.audit.hashing import hash_file

__all__ = ["DEFAULT_TRACKED_PACKAGES", "EnvironmentSnapshot", "capture_environment"]

DEFAULT_TRACKED_PACKAGES: tuple[str, ...] = (
    "nikodym",
    "numpy",
    "pandas",
    "pandera",
    "pyarrow",
    "pydantic",
    "joblib",
    "PyYAML",
)


class EnvironmentSnapshot(BaseModel):
    """Registro serializable del entorno que acompaña a una corrida."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    python_version: str
    platform: str
    library_versions: dict[str, str]
    uv_lock_hash: str | None
    captured_at: datetime


def capture_environment(
    *,
    packages: Sequence[str] | None = None,
    uv_lock_path: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
    version_provider: Callable[[str], str] | None = None,
    python_version_provider: Callable[[], str] | None = None,
    platform_provider: Callable[[], str] | None = None,
) -> EnvironmentSnapshot:
    """Captura versiones, plataforma, Python y hash de ``uv.lock``.

    Los proveedores son inyectables para que los tests fijen golden values exactos sin depender del
    entorno real del desarrollador.
    """
    paquetes = tuple(dict.fromkeys(packages or DEFAULT_TRACKED_PACKAGES))
    version = version_provider or metadata.version
    captured_now = (now or (lambda: datetime.now(UTC)))()
    lock_path = Path("uv.lock") if uv_lock_path is None else Path(uv_lock_path)

    return EnvironmentSnapshot(
        python_version=(python_version_provider or _platform.python_version)(),
        platform=(platform_provider or _platform.platform)(),
        library_versions=_library_versions(paquetes, version),
        uv_lock_hash=_uv_lock_hash(lock_path),
        captured_at=_as_utc(captured_now),
    )


def _library_versions(
    packages: Sequence[str], version_provider: Callable[[str], str]
) -> dict[str, str]:
    """Lee versiones instaladas y omite ausentes con warning explícito."""
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = version_provider(package)
        except metadata.PackageNotFoundError:
            warnings.warn(
                f"Paquete '{package}' ausente al capturar el entorno; se omite.",
                stacklevel=2,
            )
    return versions


def _uv_lock_hash(path: Path) -> str | None:
    """Hashea ``uv.lock`` si existe; si falta, registra warning y devuelve ``None``."""
    if not path.exists():
        warnings.warn(
            f"uv.lock no encontrado en '{path}'; el snapshot de entorno queda parcial.",
            stacklevel=2,
        )
        return None
    return hash_file(path)


def _as_utc(value: datetime) -> datetime:
    """Normaliza timestamps naive/aware a UTC para serialización estable."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
