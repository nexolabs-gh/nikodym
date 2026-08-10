"""Identidad reproducible de la fuente de build y del entorno runtime (SDD-30 W1)."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from functools import lru_cache
from importlib import metadata, resources
from pathlib import Path
from typing import Any, Final

from nikodym.core.exceptions import ReproducibilityError

__all__ = ["build_uv_lock_hash", "installed_distribution_hash", "runtime_environment_hash"]

_RESOURCE: Final = "_build_manifest.json"
_MANIFEST_KEYS: Final = frozenset({"schema_version", "uv_lock_name", "uv_lock_sha256"})


def build_uv_lock_hash() -> str:
    """Devuelve el hash de la fuente de build y verifica el lock cuando existe checkout."""
    try:
        raw = resources.files("nikodym").joinpath(_RESOURCE).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise ReproducibilityError(
            f"El manifiesto de build embebido '{_RESOURCE}' está ausente."
        ) from exc
    manifest = _parse_manifest(raw)
    expected = str(manifest["uv_lock_sha256"])
    checkout_root = Path(__file__).resolve().parents[3]
    lock = checkout_root / str(manifest["uv_lock_name"])
    pyproject = checkout_root / "pyproject.toml"
    checkout_marker = checkout_root / ".git"
    if pyproject.is_file() and checkout_marker.exists():
        if not lock.is_file():
            raise ReproducibilityError(
                f"El checkout contiene pyproject.toml pero no el lock canónico '{lock}'."
            )
        observed = _hash_file(lock)
        if observed != expected:
            raise ReproducibilityError(
                "El manifiesto de build no coincide con uv.lock: "
                f"esperado={expected}, observado={observed}."
            )
    return expected


@lru_cache(maxsize=1)
def installed_distribution_hash() -> str:
    """Hashea código importable y metadata estable de la instalación activa de Nikodym."""
    digest = hashlib.sha256(b"nikodym.installed-distribution.v1\0")
    package_root = Path(__file__).resolve().parents[1]
    package_files = sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    if not package_files:
        raise ReproducibilityError("La instalación activa no contiene archivos del paquete.")
    for package_path in package_files:
        relative = package_path.relative_to(package_root.parent).as_posix()
        digest.update(relative.encode() + b"\0")
        digest.update(bytes.fromhex(_hash_file(package_path)))

    distribution = metadata.distribution("nikodym")
    metadata_files: list[tuple[str, Path]] = []
    for distribution_file in distribution.files or ():
        normalized = str(distribution_file).replace("\\", "/")
        if ".dist-info/" not in normalized:
            continue
        tail = normalized.split(".dist-info/", 1)[1]
        if tail in {"METADATA", "WHEEL", "entry_points.txt"} or tail.startswith("licenses/"):
            metadata_path = Path(str(distribution.locate_file(distribution_file)))
            if metadata_path.is_file():
                metadata_files.append((tail, metadata_path))
    if not any(name == "METADATA" for name, _ in metadata_files):
        raise ReproducibilityError("La instalación activa no expone METADATA de Nikodym.")
    for name, path in sorted(metadata_files):
        digest.update(f"dist-info/{name}".encode() + b"\0")
        digest.update(bytes.fromhex(_hash_file(path)))
    return digest.hexdigest()


def runtime_environment_hash() -> str:
    """Hashea Python, plataforma y todas las distribuciones instaladas, sin timestamps."""
    distributions: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in distributions and distributions[normalized] != distribution.version:
            raise ReproducibilityError(
                f"Colisión de distribuciones instaladas tras normalización PEP 503: {normalized}."
            )
        distributions[normalized] = distribution.version
    payload = {
        "schema_version": 1,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "distributions": {name: distributions[name] for name in sorted(distributions)},
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        manifest = json.loads(text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReproducibilityError(
            f"El manifiesto de build no es JSON UTF-8 válido: {exc}."
        ) from exc
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise ReproducibilityError("El manifiesto de build no cumple el schema cerrado.")
    if manifest["schema_version"] != 1 or manifest["uv_lock_name"] != "uv.lock":
        raise ReproducibilityError(
            "El manifiesto de build declara una versión o lock no soportados."
        )
    digest = manifest["uv_lock_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ReproducibilityError("uv_lock_sha256 no es un SHA-256 hexadecimal.")
    if raw != _canonical_json(manifest) + b"\n":
        raise ReproducibilityError("El manifiesto de build no usa bytes JSON canónicos.")
    return manifest


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
