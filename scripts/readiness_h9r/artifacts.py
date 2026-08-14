"""Atomicidad, sidecars y censos de disco del arnés H9R."""

from __future__ import annotations

import contextlib
import csv
import ctypes
import hashlib
import io
import json
import os
import secrets
import shutil
import stat
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, cast

from .contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_json_sha256,
    validate_sha256,
)

OUTPUT_MANIFEST_SCHEMA_VERSION = "nikodym.readiness.h9r.outputs.v1"
COUNT_SIDECAR_SCHEMA_VERSION = "nikodym.readiness.h9r.output-count.v1"
GOLDEN_OBSERVED_ALGORITHM = "canonical-output-inventory-sha256.v1"
OUTPUT_FORMAT_COUNTERS = {
    "jsonl": "jsonl-records.v1",
    "csv": "csv-data-rows.v1",
    "json": "json-array-items.v1",
    "parquet": "parquet-footer-rows.v1",
    # Este sidecar liga criptográficamente bytes y afirmación, pero no vuelve independiente al
    # contador que afirma la cardinalidad. El supervisor debe exigir un counter adapter autorizado
    # antes de considerar este modo estadísticamente calificable.
    "bin": "binary-hash-bound-count-attestation.v1",
}
FILESYSTEM_EVENT_OPERATIONS = frozenset({"create", "flush", "hash", "rename", "delete"})
MIB = 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class _WindowsFileStandardInfo(ctypes.Structure):
    """Layout ABI exacto de ``FILE_STANDARD_INFO`` (Win32)."""

    _fields_ = [
        ("allocation_size", ctypes.c_longlong),
        ("end_of_file", ctypes.c_longlong),
        ("number_of_links", ctypes.c_uint32),
        ("delete_pending", ctypes.c_ubyte),
        ("directory", ctypes.c_ubyte),
    ]


@dataclass(frozen=True)
class _DirectoryIdentity:
    path: Path
    device: int
    inode: int


def _absolute_without_following(path: Path) -> Path:
    """Normaliza una ruta absoluta sin resolver symlinks/junctions."""
    return Path(os.path.abspath(os.fspath(path)))


def is_reparse_or_symlink(path: Path) -> bool:
    """Detecta symlinks y cualquier reparse point de Windows sin seguirlo."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _reject_reparse_ancestors(path: Path, *, context: str, require_leaf: bool = True) -> None:
    """Rechaza redirecciones en toda la ruta ya existente, incluida la raíz contractual."""
    absolute = _absolute_without_following(path)
    current = Path(absolute.anchor)
    parts = absolute.parts[1:] if require_leaf else absolute.parts[1:-1]
    for part in parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise ContractError(f"{context}: ruta o ancestro ausente: {current}") from exc
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if current.is_symlink() or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT):
            raise ContractError(f"{context}: ruta o ancestro es reparse point/symlink: {current}")


def _regular_files_no_reparse(root: Path) -> list[Path]:
    """Enumera archivos regulares sin atravesar ninguna redirección del filesystem."""
    root = _absolute_without_following(root)
    _reject_reparse_ancestors(root, context="raíz contractual")
    if is_reparse_or_symlink(root):
        raise ContractError(f"reparse point prohibido en raíz contractual: {root}")
    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise ContractError(f"la raíz contractual no es directorio regular: {root}")

    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            raise ContractError(f"no se pudo censar directorio contractual: {directory}") from exc
        for entry in entries:
            candidate = Path(entry.path)
            try:
                # ``DirEntry.stat`` reporta ``st_nlink=0`` en CPython/Windows; ``lstat`` sobre
                # la ruta léxica conserva el conteo autoritativo sin seguir el leaf.
                metadata = candidate.lstat()
            except OSError as exc:
                raise ContractError(
                    f"no se pudo atestiguar entrada contractual: {candidate}"
                ) from exc
            attributes = int(getattr(metadata, "st_file_attributes", 0))
            if entry.is_symlink() or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT):
                raise ContractError(f"reparse point prohibido dentro del intento: {candidate}")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(candidate)
            elif stat.S_ISREG(metadata.st_mode):
                if int(getattr(metadata, "st_nlink", 1)) != 1:
                    raise ContractError(f"hardlink prohibido dentro del intento: {candidate}")
                files.append(candidate)
            else:
                raise ContractError(f"entrada no regular prohibida dentro del intento: {candidate}")
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _assert_bound_tree_snapshot(
    root: Path,
    expected_paths: Sequence[Path],
    expected_versions: Mapping[Path, os.stat_result],
    *,
    context: str,
) -> None:
    """Repite censo exacto y liga la versión de cada leaf antes de aceptar el árbol."""
    observed = _regular_files_no_reparse(root)
    if observed != list(expected_paths):
        raise ContractError(f"{context}: el censo de archivos cambió")
    for path in observed:
        version = expected_versions.get(path)
        if version is None:
            raise ContractError(f"{context}: falta versión atestiguada para {path}")
        _assert_bound_file_version(path, version, context=f"{context}: {path}")


def _safe_output_relative_path(raw: object, *, context: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise ContractError(f"{context}: relative_path inválido")
    relative = PurePosixPath(raw)
    windows_relative = PureWindowsPath(raw)
    if (
        relative.is_absolute()
        or windows_relative.is_absolute()
        or bool(windows_relative.drive)
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ContractError(f"{context}: relative_path escapa outputs")
    if relative.as_posix() != raw:
        raise ContractError(f"{context}: relative_path no es canónico")
    return relative


def _safe_existing_output_file(
    output_root: Path, raw_relative: object, *, context: str
) -> tuple[str, Path]:
    relative = _safe_output_relative_path(raw_relative, context=context)
    root = _absolute_without_following(output_root)
    _reject_reparse_ancestors(root, context=context)
    candidate = root.joinpath(*relative.parts)
    current = root
    if is_reparse_or_symlink(current):
        raise ContractError(f"{context}: output_root es reparse/symlink")
    for part in relative.parts:
        current /= part
        if is_reparse_or_symlink(current):
            raise ContractError(f"{context}: ruta atraviesa reparse/symlink")
    try:
        metadata = candidate.lstat()
    except FileNotFoundError as exc:
        raise ContractError(f"{context}: archivo ausente") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ContractError(f"{context}: no es archivo regular")
    if int(getattr(metadata, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: hardlink prohibido")
    return relative.as_posix(), candidate


def _safe_existing_sidecar_file(path: Path, *, context: str) -> Path:
    """Reabre un sidecar regular sin seguir redirecciones ni aceptar hardlinks."""
    candidate = _absolute_without_following(path)
    _reject_reparse_ancestors(candidate, context=context)
    try:
        metadata = candidate.lstat()
    except FileNotFoundError as exc:
        raise ContractError(f"{context}: sidecar ausente: {candidate}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ContractError(f"{context}: sidecar no es archivo regular: {candidate}")
    if int(getattr(metadata, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: sidecar con hardlinks prohibidos: {candidate}")
    return candidate


def _same_file_version(left: os.stat_result, right: os.stat_result) -> bool:
    return bool(
        os.path.samestat(left, right)
        and int(left.st_size) == int(right.st_size)
        and int(getattr(left, "st_mtime_ns", 0)) == int(getattr(right, "st_mtime_ns", 0))
    )


def _assert_bound_file_version(path: Path, expected: os.stat_result, *, context: str) -> None:
    parent_identity = _plain_directory_identity(
        path.parent,
        context=f"{context}: parent",
        create_missing=False,
    )
    observed = _require_bound_regular_file(
        path,
        context=context,
        parent_identity=parent_identity,
        expected_metadata=expected,
    )
    if not _same_file_version(expected, observed):
        raise ContractError(f"{context}: el archivo cambió de versión")


def _read_bound_file_bytes(path: Path, *, context: str) -> tuple[Path, bytes, os.stat_result]:
    """Lee una sola versión del archivo y prueba descriptor, leaf y parent antes/después."""
    candidate = _safe_existing_sidecar_file(path, context=context)
    parent_identity = _plain_directory_identity(
        candidate.parent,
        context=f"{context}: parent",
        create_missing=False,
    )
    before = candidate.lstat()
    with candidate.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not _same_file_version(before, opened):
            raise ContractError(f"{context}: el archivo cambió antes de la lectura")
        payload = handle.read()
        after_read = os.fstat(handle.fileno())
        if not _same_file_version(opened, after_read) or len(payload) != int(after_read.st_size):
            raise ContractError(f"{context}: el archivo cambió durante la lectura")
    _assert_same_plain_directory(parent_identity, context=f"{context}: parent final")
    after_path = _require_bound_regular_file(
        candidate,
        context=f"{context}: archivo final",
        parent_identity=parent_identity,
        expected_metadata=before,
    )
    if not _same_file_version(before, after_path):
        raise ContractError(f"{context}: el archivo cambió después de la lectura")
    return candidate, payload, after_path


def _hash_bound_file(
    path: Path,
    *,
    context: str,
    deadline_monotonic: float | None = None,
) -> tuple[Path, int, str, os.stat_result]:
    """Hashea por bloques una sola versión descriptor-bound y revalida leaf/parent."""
    candidate = _safe_existing_sidecar_file(path, context=context)
    parent_identity = _plain_directory_identity(
        candidate.parent,
        context=f"{context}: parent",
        create_missing=False,
    )
    before = candidate.lstat()
    digest = hashlib.sha256()
    logical_bytes = 0
    with candidate.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not _same_file_version(before, opened):
            raise ContractError(f"{context}: el archivo cambió antes del hash")
        for block in iter(lambda: handle.read(MIB), b""):
            if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
                raise ContractError("preflight_rejected: preflight excedió 300 s durante hashing")
            logical_bytes += len(block)
            digest.update(block)
        after_hash = os.fstat(handle.fileno())
        if not _same_file_version(opened, after_hash) or logical_bytes != int(after_hash.st_size):
            raise ContractError(f"{context}: el archivo cambió durante el hash")
    _assert_same_plain_directory(parent_identity, context=f"{context}: parent final")
    after_path = _require_bound_regular_file(
        candidate,
        context=f"{context}: archivo final",
        parent_identity=parent_identity,
        expected_metadata=before,
    )
    if not _same_file_version(before, after_path):
        raise ContractError(f"{context}: el archivo cambió después del hash")
    return candidate, logical_bytes, digest.hexdigest(), after_path


def _emit_filesystem_event(
    callback: Callable[[str, Path], None] | None, operation: str, path: Path
) -> None:
    if operation not in FILESYSTEM_EVENT_OPERATIONS:  # pragma: no cover - defensa interna
        raise ContractError(f"operación filesystem fuera del catálogo: {operation}")
    if callback is not None:
        callback(operation, path)


def _plain_directory_identity(
    path: Path, *, context: str, create_missing: bool
) -> _DirectoryIdentity:
    """Recorre léxicamente una raíz y crea sólo componentes ausentes no redirigidos."""
    absolute = _absolute_without_following(path)
    current = Path(absolute.anchor)
    parts = absolute.parts[1:]
    for part in (None, *parts):
        if part is not None:
            current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if not create_missing or part is None:
                raise ContractError(
                    f"{context}: directorio o ancestro ausente: {current}"
                ) from None
            try:
                current.mkdir(parents=False, exist_ok=False)
            except FileExistsError as exc:
                raise ContractError(
                    f"{context}: carrera al reservar directorio: {current}"
                ) from exc
            metadata = current.lstat()
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or current.is_symlink()
            or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)
        ):
            raise ContractError(
                f"{context}: directorio/ancestro redirigido o no regular: {current}"
            )
    return _DirectoryIdentity(
        path=absolute,
        device=int(metadata.st_dev),
        inode=int(metadata.st_ino),
    )


def _assert_same_plain_directory(identity: _DirectoryIdentity, *, context: str) -> None:
    observed = _plain_directory_identity(
        identity.path,
        context=context,
        create_missing=False,
    )
    if (observed.device, observed.inode) != (identity.device, identity.inode):
        raise ContractError(f"{context}: el directorio cambió de identidad")


def _require_absent_leaf(path: Path, *, context: str) -> None:
    candidate = _absolute_without_following(path)
    if os.path.lexists(candidate):
        raise FileExistsError(f"{context}: destino inmutable ya existe: {candidate}")


def _require_bound_regular_file(
    path: Path,
    *,
    context: str,
    parent_identity: _DirectoryIdentity,
    expected_metadata: os.stat_result | None = None,
) -> os.stat_result:
    _assert_same_plain_directory(parent_identity, context=context)
    candidate = _safe_existing_sidecar_file(path, context=context)
    observed = candidate.lstat()
    if expected_metadata is not None and not os.path.samestat(expected_metadata, observed):
        raise ContractError(f"{context}: el archivo cambió de identidad")
    return observed


def _remove_partial(path: Path, callback: Callable[[str, Path], None] | None) -> None:
    """Elimina un parcial conocido y registra el hecho después del unlink efectivo."""
    if not os.path.lexists(path):
        return
    metadata = path.lstat()
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)
    ):
        raise ContractError(f"parcial inesperado no regular/reparse: {path}")
    path.unlink()
    _emit_filesystem_event(callback, "delete", path)


def _move_file_exclusive(source: Path, destination: Path) -> str:
    """Publica sin overwrite y devuelve el mecanismo observado."""
    if sys.platform == "win32":
        kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        kernel32.MoveFileExW.restype = ctypes.c_bool
        movefile_write_through = 0x00000008
        if not kernel32.MoveFileExW(str(source), str(destination), movefile_write_through):
            code = ctypes.get_last_error()
            raise OSError(code, f"MoveFileExW exclusivo falló: {destination}")
        return "windows_rename_write_through_no_replace"
    # El arnés calificable es Windows. Este fallback conserva exclusividad para los unit tests de
    # otros runners, pero su evidencia no puede promover una medición H9R.
    os.link(source, destination)
    linked_identity = destination.lstat()
    try:
        source.unlink()
    except BaseException:
        if os.path.lexists(destination):
            observed = destination.lstat()
            if os.path.samestat(linked_identity, observed):
                destination.unlink()
        raise
    return "portable_link_unlink_test_only"


def _quarantine_failed_publication(
    path: Path,
    *,
    published_identity: os.stat_result,
    parent_identity: _DirectoryIdentity,
    event_callback: Callable[[str, Path], None] | None,
) -> Path | None:
    """Retira el nombre final fallido sólo si aún apunta al inode que publicó el arnés."""
    _assert_same_plain_directory(parent_identity, context="parent de cuarentena")
    if not os.path.lexists(path):
        return None
    observed = path.lstat()
    attributes = int(getattr(observed, "st_file_attributes", 0))
    if (
        not stat.S_ISREG(observed.st_mode)
        or path.is_symlink()
        or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)
        or not os.path.samestat(published_identity, observed)
    ):
        # El nombre fue sustituido por un objeto ajeno: nunca lo borramos ni lo movemos.
        return None
    quarantine = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.failed.quarantine"
    )
    _require_absent_leaf(quarantine, context="cuarentena de publicación fallida")
    _move_file_exclusive(path, quarantine)
    _emit_filesystem_event(event_callback, "rename", quarantine)
    _assert_same_plain_directory(parent_identity, context="parent después de cuarentena")
    return quarantine


def _publish_exclusive(
    path: Path,
    writer: Callable[[BinaryIO], None],
    *,
    event_callback: Callable[[str, Path], None] | None,
) -> dict[str, Any]:
    """Publica bytes mediante un parent léxico estable y un único archivo temporal."""
    path = _absolute_without_following(path)
    parent_identity = _plain_directory_identity(
        path.parent,
        context="parent de publicación exclusiva",
        create_missing=True,
    )
    _require_absent_leaf(path, context="publicación exclusiva")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.partial")
    _require_absent_leaf(temporary, context="temporal de publicación exclusiva")
    publication_method: str | None = None
    temporary_metadata: os.stat_result | None = None
    moved_to_destination = False
    publication_completed = False
    published_origin: os.stat_result | None = None
    try:
        with temporary.open("xb") as handle:
            _emit_filesystem_event(event_callback, "create", temporary)
            temporary_metadata = os.fstat(handle.fileno())
            if int(getattr(temporary_metadata, "st_nlink", 1)) != 1:
                raise ContractError("el temporal de publicación nació con hardlinks")
            _require_bound_regular_file(
                temporary,
                context="temporal de publicación exclusiva",
                parent_identity=parent_identity,
                expected_metadata=temporary_metadata,
            )
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
            _emit_filesystem_event(event_callback, "flush", temporary)
            post_write = os.fstat(handle.fileno())
            if not os.path.samestat(temporary_metadata, post_write):
                raise ContractError("el temporal cambió de identidad durante la escritura")
        temporary_path, temporary_bytes, temporary_sha256, temporary_identity = _hash_bound_file(
            temporary,
            context="temporal antes del hash",
        )
        if temporary_path != temporary or not _same_file_version(
            post_write,
            temporary_identity,
        ):
            raise ContractError("el temporal cambió de versión antes del hash")
        _emit_filesystem_event(event_callback, "hash", temporary)
        _assert_same_plain_directory(parent_identity, context="parent antes del rename")
        _require_absent_leaf(path, context="destino antes del rename")
        publication_method = _move_file_exclusive(temporary, path)
        moved_to_destination = True
        published_origin = post_write
        _emit_filesystem_event(event_callback, "rename", path)
        published = _require_bound_regular_file(
            path,
            context="destino publicado",
            parent_identity=parent_identity,
            expected_metadata=post_write,
        )
        published_path, published_bytes, published_sha256, published_identity = _hash_bound_file(
            path,
            context="destino publicado final",
        )
        if (
            published_path != path
            or not os.path.samestat(published, published_identity)
            or published_bytes != temporary_bytes
            or published_sha256 != temporary_sha256
        ):
            raise ContractError("los bytes publicados no reconcilian con el temporal atestiguado")
        _assert_bound_file_version(
            published_path,
            published_identity,
            context="destino publicado antes de devolver metadatos",
        )
        publication_completed = True
        return {
            "path": str(path),
            "logical_bytes": published_bytes,
            "sha256": temporary_sha256,
            "publication_method": publication_method,
        }
    finally:
        with contextlib.suppress(FileNotFoundError):
            _remove_partial(temporary, event_callback)
        if moved_to_destination and not publication_completed and published_origin is not None:
            _quarantine_failed_publication(
                path,
                published_identity=published_origin,
                parent_identity=parent_identity,
                event_callback=event_callback,
            )


def atomic_write_bytes_exclusive(
    path: Path,
    payload: bytes,
    *,
    event_callback: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Escribe en el mismo directorio, hace flush/fsync y publica sin sobrescribir."""

    def write_payload(handle: BinaryIO) -> None:
        handle.write(payload)

    return _publish_exclusive(
        path,
        write_payload,
        event_callback=event_callback,
    )


def atomic_write_json_exclusive(path: Path, value: Any) -> dict[str, Any]:
    """Publica JSON canónico terminado en newline."""
    return atomic_write_bytes_exclusive(path, canonical_json_bytes(value) + b"\n")


class JsonlRecorder:
    """Sidecar JSONL exclusivo con conteo y digest al cierre."""

    def __init__(self, path: Path, *, name: str | None = None) -> None:
        self.path = _absolute_without_following(path)
        self._parent_identity = _plain_directory_identity(
            self.path.parent,
            context="parent del sidecar JSONL",
            create_missing=True,
        )
        _require_absent_leaf(self.path, context="sidecar JSONL")
        self.name = name or path.stem
        self._handle: BinaryIO = self.path.open("xb")
        self._file_identity = os.fstat(self._handle.fileno())
        try:
            _require_bound_regular_file(
                self.path,
                context="sidecar JSONL recién creado",
                parent_identity=self._parent_identity,
                expected_metadata=self._file_identity,
            )
        except Exception:
            self._handle.close()
            with contextlib.suppress(FileNotFoundError):
                _remove_partial(self.path, None)
            raise
        self._records = 0
        self._closed = False

    def _assert_bound(self, *, context: str) -> None:
        if self._closed:
            raise RuntimeError("sidecar ya cerrado")
        handle_metadata = os.fstat(self._handle.fileno())
        if not os.path.samestat(self._file_identity, handle_metadata):
            raise ContractError(f"{context}: el descriptor cambió de identidad")
        _require_bound_regular_file(
            self.path,
            context=context,
            parent_identity=self._parent_identity,
            expected_metadata=self._file_identity,
        )

    def append(self, value: Mapping[str, Any]) -> None:
        """Agrega un registro canónico y lo hace visible al lector."""
        self._assert_bound(context="sidecar JSONL antes de append")
        self._handle.write(canonical_json_bytes(dict(value)) + b"\n")
        self._handle.flush()
        self._assert_bound(context="sidecar JSONL después de append")
        self._records += 1

    def finalize(self) -> dict[str, Any]:
        """Hace fsync, cierra y devuelve metadatos verificables."""
        if not self._closed:
            self._assert_bound(context="sidecar JSONL antes de finalize")
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._assert_bound(context="sidecar JSONL después de fsync")
            self._handle.close()
            self._closed = True
        _require_bound_regular_file(
            self.path,
            context="sidecar JSONL finalizado",
            parent_identity=self._parent_identity,
            expected_metadata=self._file_identity,
        )
        path, payload, identity = _read_bound_file_bytes(
            self.path,
            context="sidecar JSONL finalizado",
        )
        metadata = {
            "name": self.name,
            "path": str(path),
            "format": "jsonl",
            "records": self._records,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        _assert_bound_file_version(path, identity, context="sidecar JSONL finalizado final")
        return metadata

    def close(self) -> None:
        """Cierra el descriptor aunque la captura haya fallado."""
        if not self._closed:
            self._handle.close()
            self._closed = True

    def __enter__(self) -> JsonlRecorder:
        """Devuelve el recorder abierto."""
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Cierra el recorder al abandonar el contexto."""
        del exc_type, exc, traceback
        self.close()


def _parse_canonical_jsonl(payload: bytes, *, context: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(payload.splitlines(keepends=True), start=1):
        if not raw_line.endswith(b"\n"):
            raise ContractError(f"{context}: falta newline final en línea {line_number}")
        try:
            raw: Any = json.loads(raw_line)
            canonical = canonical_json_bytes(raw) + b"\n"
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ContractError(f"{context}: JSON inválido en línea {line_number}") from exc
        if not isinstance(raw, dict):
            raise ContractError(f"{context}: registro no es objeto en línea {line_number}")
        if raw_line != canonical:
            raise ContractError(f"{context}: registro no es canónico en línea {line_number}")
        records.append(cast(dict[str, Any], raw))
    return records


def _parse_canonical_json_object(payload: bytes, *, context: str) -> dict[str, Any]:
    try:
        raw: Any = json.loads(payload)
        canonical = canonical_json_bytes(raw) + b"\n"
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractError(f"{context}: JSON inválido") from exc
    if not isinstance(raw, dict):
        raise ContractError(f"{context}: JSON no es objeto")
    if payload != canonical:
        raise ContractError(f"{context}: JSON no es canónico con newline final")
    return cast(dict[str, Any], raw)


def _read_canonical_json_object_file(path: Path, *, context: str) -> dict[str, Any]:
    candidate, payload, identity = _read_bound_file_bytes(path, context=context)
    parsed = _parse_canonical_json_object(payload, context=context)
    _assert_bound_file_version(candidate, identity, context=f"{context}: lectura final")
    return parsed


def verify_jsonl_sidecar(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Relee un sidecar y reconcilia bytes, hash y cardinalidad."""
    required = {"name", "path", "format", "records", "bytes", "sha256"}
    if set(metadata) != required or metadata.get("format") != "jsonl":
        raise ContractError("metadatos JSONL no tienen campos/formato exactos")
    path, payload, identity = _read_bound_file_bytes(
        Path(str(metadata.get("path"))),
        context="verificación JSONL",
    )
    if metadata.get("bytes") != len(payload):
        raise ContractError("bytes del sidecar no reconcilian")
    if metadata.get("sha256") != hashlib.sha256(payload).hexdigest():
        raise ContractError("SHA-256 del sidecar no reconcilia")
    records = _parse_canonical_jsonl(payload, context="verificación JSONL")
    if metadata.get("records") != len(records):
        raise ContractError("cardinalidad del sidecar no reconcilia")
    _assert_bound_file_version(path, identity, context="verificación JSONL final")
    return records


def jsonl_sidecar_metadata(path: Path, *, name: str) -> dict[str, Any]:
    """Reconstruye metadatos de un JSONL cerrado y prueba su parseabilidad/cardinalidad."""
    path, payload, identity = _read_bound_file_bytes(path, context="metadatos JSONL")
    records = len(_parse_canonical_jsonl(payload, context="metadatos JSONL"))
    metadata = {
        "name": name,
        "path": str(path),
        "format": "jsonl",
        "records": records,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    _assert_bound_file_version(path, identity, context="metadatos JSONL finales")
    return metadata


def binary_sidecar_metadata(path: Path, *, name: str) -> dict[str, Any]:
    """Firma un sidecar binario existente sin inventar cardinalidad semántica."""
    path, payload, identity = _read_bound_file_bytes(path, context="metadatos binarios")
    metadata = {
        "name": name,
        "path": str(path),
        "format": "binary",
        "records": 1,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    _assert_bound_file_version(path, identity, context="metadatos binarios finales")
    return metadata


def verify_sidecar(metadata: Mapping[str, Any]) -> None:
    """Reabre un sidecar, reconcilia bytes/hash y, para JSONL, todos sus registros."""
    if metadata.get("format") == "jsonl":
        verify_jsonl_sidecar(metadata)
        return
    required = {"name", "path", "format", "records", "bytes", "sha256"}
    if set(metadata) != required or metadata.get("format") != "binary":
        raise ContractError("metadatos de sidecar no tienen campos/formato exactos")
    path, payload, identity = _read_bound_file_bytes(
        Path(str(metadata.get("path"))),
        context="verificación binaria",
    )
    if metadata.get("records") != 1:
        raise ContractError("sidecar binario debe declarar un registro opaco")
    if metadata.get("bytes") != len(payload):
        raise ContractError("bytes del sidecar binario no reconcilian")
    if metadata.get("sha256") != hashlib.sha256(payload).hexdigest():
        raise ContractError("SHA-256 del sidecar binario no reconcilia")
    _assert_bound_file_version(path, identity, context="verificación binaria final")


def _windows_file_storage_size(path: Path, expected: os.stat_result) -> tuple[int, int]:
    class _FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", ctypes.c_uint32),
            ("creation_time", _FileTime),
            ("last_access_time", _FileTime),
            ("last_write_time", _FileTime),
            ("volume_serial_number", ctypes.c_uint32),
            ("file_size_high", ctypes.c_uint32),
            ("file_size_low", ctypes.c_uint32),
            ("number_of_links", ctypes.c_uint32),
            ("file_index_high", ctypes.c_uint32),
            ("file_index_low", ctypes.c_uint32),
        ]

    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.GetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = ctypes.c_int
    kernel32.GetFileInformationByHandleEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.GetFileInformationByHandleEx.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    file_read_attributes = 0x0080
    share_read_write_delete = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    file_flag_open_reparse_point = 0x00200000
    handle = kernel32.CreateFileW(
        str(path),
        file_read_attributes,
        share_read_write_delete,
        None,
        open_existing,
        file_flag_open_reparse_point,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in {None, invalid_handle}:
        code = ctypes.get_last_error()
        raise OSError(code, f"CreateFileW no-follow falló: {path}")
    try:
        identity = _ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(identity)):
            code = ctypes.get_last_error()
            raise OSError(code, f"GetFileInformationByHandle falló: {path}")
        standard = _WindowsFileStandardInfo()
        file_standard_info = 1
        if not kernel32.GetFileInformationByHandleEx(
            handle,
            file_standard_info,
            ctypes.byref(standard),
            ctypes.sizeof(standard),
        ):
            code = ctypes.get_last_error()
            raise OSError(code, f"GetFileInformationByHandleEx falló: {path}")
        file_index = (int(identity.file_index_high) << 32) | int(identity.file_index_low)
        logical_bytes = (int(identity.file_size_high) << 32) | int(identity.file_size_low)
        if (
            bool(int(identity.attributes) & _FILE_ATTRIBUTE_REPARSE_POINT)
            or bool(int(identity.attributes) & 0x10)
            or int(identity.number_of_links) != 1
            or int(standard.number_of_links) != 1
            or bool(standard.delete_pending)
            or bool(standard.directory)
            or file_index != int(expected.st_ino)
            or logical_bytes != int(expected.st_size)
            or int(standard.end_of_file) != logical_bytes
            or int(standard.allocation_size) < logical_bytes
        ):
            raise ContractError(f"identidad/almacenamiento del archivo cambió: {path}")
        return logical_bytes, int(standard.allocation_size)
    finally:
        if not kernel32.CloseHandle(handle):
            code = ctypes.get_last_error()
            raise OSError(code, f"CloseHandle falló al censar: {path}")


def file_storage_size(path: Path) -> tuple[int, int, bool, str]:
    """Liga tamaño lógico/asignado a un leaf plano y estable durante la consulta."""
    candidate = _safe_existing_sidecar_file(path, context="censo de almacenamiento")
    before = candidate.lstat()
    if sys.platform == "win32":
        logical, allocated = _windows_file_storage_size(candidate, before)
        source = "GetFileInformationByHandleEx.FileStandardInfo"
        reliable = True
    else:
        blocks = getattr(before, "st_blocks", None)
        logical = int(before.st_size)
        allocated = blocks * 512 if isinstance(blocks, int) else logical
        source = (
            "st_blocks_test_only" if isinstance(blocks, int) else "logical_fallback_unqualified"
        )
        reliable = False
    rebound = _safe_existing_sidecar_file(candidate, context="censo de almacenamiento final")
    after = rebound.lstat()
    if not os.path.samestat(before, after) or int(before.st_size) != int(after.st_size):
        raise ContractError(f"archivo cambió durante el censo de almacenamiento: {candidate}")
    return logical, allocated, reliable, source


def allocated_size(path: Path) -> tuple[int, bool, str]:
    """Obtiene bytes asignados y declara si la fuente es calificable."""
    _, allocated, reliable, source = file_storage_size(path)
    return allocated, reliable, source


@dataclass(frozen=True)
class RootCensus:
    """Censo lógico/asignado de una raíz contractual."""

    root: str
    logical_bytes: int
    allocated_bytes: int
    files: int
    allocation_reliable: bool
    allocation_sources: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Convierte a JSON sin perder la calificación del sensor."""
        return {
            "root": self.root,
            "logical_bytes": self.logical_bytes,
            "allocated_bytes": self.allocated_bytes,
            "files": self.files,
            "allocation_reliable": self.allocation_reliable,
            "allocation_sources": list(self.allocation_sources),
        }


def census_root(root: Path) -> RootCensus:
    """Censa recursivamente sin seguir symlinks ni reparse points."""
    root = _absolute_without_following(root)
    if not os.path.lexists(root):
        return RootCensus(str(root), 0, 0, 0, True, ())
    logical = 0
    allocated = 0
    files = 0
    reliable = True
    sources: set[str] = set()
    for candidate in _regular_files_no_reparse(root):
        logical_bytes, assigned, qualified, source = file_storage_size(candidate)
        logical += logical_bytes
        allocated += assigned
        files += 1
        reliable = reliable and qualified
        sources.add(source)
    return RootCensus(str(root), logical, allocated, files, reliable, tuple(sorted(sources)))


def census_roots(roots: Mapping[str, Path]) -> dict[str, dict[str, Any]]:
    """Censa exactamente las raíces nombradas por el protocolo."""
    return {name: census_root(path).as_dict() for name, path in sorted(roots.items())}


def validate_census_against_filesystem(
    observed: Mapping[str, Any], roots: Mapping[str, Path]
) -> dict[str, dict[str, Any]]:
    """Recalcula el censo y detecta allocation falsa o una raíz excluida."""
    required_roots = {"inputs", "bundle", "scratch", "outputs", "telemetry"}
    if set(roots) != required_roots or set(observed) != required_roots:
        raise ContractError(
            f"raíces de disco incompletas: esperadas={sorted(required_roots)!r}, "
            f"paths={sorted(roots)!r}, evidencia={sorted(observed)!r}"
        )
    actual = census_roots(roots)
    if actual != dict(observed):
        raise ContractError("censo lógico/asignado no reconcilia con el filesystem")
    if not all(bool(value["allocation_reliable"]) for value in actual.values()):
        raise ContractError("allocation size no es calificable en esta plataforma/filesystem")
    return actual


def disk_footprint_summary(
    baseline: Mapping[str, Mapping[str, Any]],
    samples: Sequence[Mapping[str, Mapping[str, Any]]],
) -> dict[str, int]:
    """Reconcilia footprint total y high-water incremental sin omitir temporales."""
    required_roots = {"inputs", "bundle", "scratch", "outputs", "telemetry"}
    if set(baseline) != required_roots:
        raise ContractError("baseline de disco no enumera las cinco raíces")
    if not samples:
        raise ContractError("footprint exige al menos una muestra")
    for index, sample in enumerate(samples):
        if set(sample) != required_roots:
            raise ContractError(f"muestra {index} omite o añade una raíz de disco")
    inputs_bundle = sum(
        int(baseline[name].get("allocated_bytes", 0)) for name in ("inputs", "bundle")
    )
    baseline_incremental = sum(
        int(baseline[name].get("allocated_bytes", 0))
        for name in ("scratch", "outputs", "telemetry")
    )
    peak_incremental = max(
        0,
        max(
            sum(
                int(sample[name].get("allocated_bytes", 0))
                for name in ("scratch", "outputs", "telemetry")
            )
            - baseline_incremental
            for sample in samples
        ),
    )
    return {
        "allocated_inputs_bundle_bytes": inputs_bundle,
        "peak_incremental_allocated_bytes": peak_incremental,
        "footprint_total_bytes": inputs_bundle + peak_incremental,
    }


def volume_free_bytes(path: Path) -> int:
    """Mide espacio libre del volumen que contiene ``path``."""
    existing = _absolute_without_following(path)
    while not os.path.lexists(existing) and existing.parent != existing:
        existing = existing.parent
    _reject_reparse_ancestors(existing, context="ruta para espacio libre")
    return int(shutil.disk_usage(existing).free)


def windows_volume_identity(path: Path) -> dict[str, Any]:
    """Atestigua volumen, filesystem y unidad de asignación calificables en Windows."""
    if sys.platform != "win32":
        raise ContractError("identidad de volumen calificable exige Windows")
    existing = _absolute_without_following(path)
    while not os.path.lexists(existing) and existing.parent != existing:
        existing = existing.parent
    _reject_reparse_ancestors(existing, context="ruta para identidad de volumen")
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetVolumePathNameW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel32.GetVolumePathNameW.restype = ctypes.c_bool
    kernel32.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel32.GetVolumeInformationW.restype = ctypes.c_bool
    kernel32.GetDiskFreeSpaceW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.GetDiskFreeSpaceW.restype = ctypes.c_bool
    root_buffer = ctypes.create_unicode_buffer(32_768)
    if not kernel32.GetVolumePathNameW(str(existing.resolve()), root_buffer, len(root_buffer)):
        raise OSError(ctypes.get_last_error(), "GetVolumePathNameW falló")
    filesystem_buffer = ctypes.create_unicode_buffer(256)
    volume_name_buffer = ctypes.create_unicode_buffer(256)
    serial = ctypes.c_uint32(0)
    max_component = ctypes.c_uint32(0)
    flags = ctypes.c_uint32(0)
    if not kernel32.GetVolumeInformationW(
        root_buffer.value,
        volume_name_buffer,
        len(volume_name_buffer),
        ctypes.byref(serial),
        ctypes.byref(max_component),
        ctypes.byref(flags),
        filesystem_buffer,
        len(filesystem_buffer),
    ):
        raise OSError(ctypes.get_last_error(), "GetVolumeInformationW falló")
    sectors_per_cluster = ctypes.c_uint32(0)
    bytes_per_sector = ctypes.c_uint32(0)
    free_clusters = ctypes.c_uint32(0)
    total_clusters = ctypes.c_uint32(0)
    if not kernel32.GetDiskFreeSpaceW(
        root_buffer.value,
        ctypes.byref(sectors_per_cluster),
        ctypes.byref(bytes_per_sector),
        ctypes.byref(free_clusters),
        ctypes.byref(total_clusters),
    ):
        raise OSError(ctypes.get_last_error(), "GetDiskFreeSpaceW falló")
    return {
        "volume_root": root_buffer.value,
        "volume_name": volume_name_buffer.value,
        "volume_serial": int(serial.value),
        "filesystem": filesystem_buffer.value,
        "filesystem_flags": int(flags.value),
        "maximum_component_length": int(max_component.value),
        "allocation_unit_bytes": int(sectors_per_cluster.value * bytes_per_sector.value),
    }


def final_inventory(root: Path, *, exclude: Sequence[Path] = ()) -> list[dict[str, Any]]:
    """Hashea el inventario final y preserva orden relativo estable."""
    root = _absolute_without_following(root)
    excluded = {_absolute_without_following(path) for path in exclude}
    inventory: list[dict[str, Any]] = []
    paths = _regular_files_no_reparse(root)
    versions: dict[Path, os.stat_result] = {}
    for path in paths:
        if _absolute_without_following(path) in excluded:
            versions[path] = path.lstat()
            continue
        path, payload_bytes, payload_sha256, identity = _hash_bound_file(
            path,
            context=f"inventario final {path}",
        )
        logical, assigned, reliable, source = file_storage_size(path)
        if logical != payload_bytes:
            raise ContractError(f"inventario final mezcló versiones del archivo: {path}")
        _assert_bound_file_version(path, identity, context=f"inventario final ligado {path}")
        versions[path] = identity
        inventory.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "logical_bytes": logical,
                "allocated_bytes": assigned,
                "allocation_reliable": reliable,
                "allocation_source": source,
                "sha256": payload_sha256,
            }
        )
    final_paths = _regular_files_no_reparse(root)
    if final_paths != paths:
        raise ContractError("el árbol cambió durante el inventario final")
    for path, identity in versions.items():
        _assert_bound_file_version(path, identity, context=f"inventario final al cierre {path}")
    _assert_bound_tree_snapshot(
        root,
        paths,
        versions,
        context="inventario final al cerrar el árbol",
    )
    return inventory


def canonical_tree_identity(
    root: Path, *, deadline_monotonic: float | None = None
) -> dict[str, Any]:
    """Firma un árbol por rutas relativas, bytes y SHA, sin incluir su ubicación volátil."""
    root = _absolute_without_following(root)
    entries: list[dict[str, Any]] = []
    versions: dict[Path, os.stat_result] = {}
    logical_bytes = 0
    try:
        paths = _regular_files_no_reparse(root)
    except FileNotFoundError as exc:
        raise ContractError(f"árbol instalado ausente: {root}") from exc
    for path in paths:
        path, size, payload_sha256, identity = _hash_bound_file(
            path,
            context=f"identidad de árbol instalado {path}",
            deadline_monotonic=deadline_monotonic,
        )
        versions[path] = identity
        entries.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "bytes": size,
                "sha256": payload_sha256,
            }
        )
        logical_bytes += size
    final_paths = _regular_files_no_reparse(root)
    if final_paths != paths:
        raise ContractError("el árbol instalado cambió durante su atestado")
    for path, identity in versions.items():
        _assert_bound_file_version(
            path,
            identity,
            context=f"identidad de árbol instalado al cierre {path}",
        )
    _assert_bound_tree_snapshot(
        root,
        paths,
        versions,
        context="árbol instalado al cerrar su atestado",
    )
    from .contracts import canonical_json_sha256

    return {
        "files": len(entries),
        "logical_bytes": logical_bytes,
        "sha256": canonical_json_sha256(entries),
    }


def _resolve_output_format(relative_path: str, explicit: str | None) -> str:
    """Resuelve un formato cerrado; no adivina extensiones desconocidas."""
    if explicit is not None:
        if explicit not in OUTPUT_FORMAT_COUNTERS:
            raise ContractError(f"formato de output fuera del catálogo: {explicit!r}")
        return explicit
    suffix = Path(relative_path).suffix.casefold().removeprefix(".")
    if suffix not in OUTPUT_FORMAT_COUNTERS:
        raise ContractError(
            f"extensión de output sin contador cerrado: {relative_path!r}; "
            f"formatos={sorted(OUTPUT_FORMAT_COUNTERS)!r}"
        )
    return suffix


def _derive_output_record_count_payload(payload: bytes, *, output_format: str) -> int:
    if output_format not in OUTPUT_FORMAT_COUNTERS:
        raise ContractError(f"formato de output fuera del catálogo: {output_format!r}")
    if output_format == "bin":
        raise ContractError("bin es opaco: su conteo exige sidecar firmado")
    if output_format == "jsonl":
        records = 0
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError("JSONL no es UTF-8") from exc
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
            if not line.endswith("\n"):
                raise ContractError(f"JSONL sin newline final en línea {line_number}")
            if not line.strip():
                raise ContractError(f"JSONL contiene línea vacía en {line_number}")
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractError(f"JSONL inválido en línea {line_number}") from exc
            records += 1
        return records
    if output_format == "csv":
        try:
            reader = csv.reader(io.StringIO(payload.decode("utf-8"), newline=""), strict=True)
            header = next(reader, None)
            if header is None or not header or any(not column for column in header):
                raise ContractError("CSV no contiene header completo")
            if len(set(header)) != len(header):
                raise ContractError("CSV contiene columnas duplicadas")
            records = 0
            for row_number, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    raise ContractError(f"CSV fila {row_number} no reconcilia con el header")
                records += 1
            return records
        except UnicodeDecodeError as exc:
            raise ContractError("CSV no es UTF-8") from exc
        except csv.Error as exc:
            raise ContractError("CSV inválido") from exc
    if output_format == "json":
        try:
            value: Any = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("JSON de output inválido") from exc
        if not isinstance(value, list):
            raise ContractError("JSON contable debe ser un array top-level")
        return len(value)
    if output_format == "parquet":
        try:
            import pyarrow.parquet as pq

            parquet_file_type: Any = pq.ParquetFile
            metadata: Any = parquet_file_type(io.BytesIO(payload)).metadata
        except Exception as exc:
            raise ContractError("Parquet no se puede reabrir para derivar filas") from exc
        if metadata is None or metadata.num_rows < 0:
            raise ContractError("footer Parquet no expone num_rows válido")
        return int(metadata.num_rows)
    raise AssertionError("catálogo de formatos desincronizado")  # pragma: no cover


def derive_output_record_count(path: Path, *, output_format: str) -> int:
    """Reabre una sola versión del output y deriva su cardinalidad cerrada."""
    candidate, payload, identity = _read_bound_file_bytes(
        path,
        context="output para derivar conteo",
    )
    records = _derive_output_record_count_payload(payload, output_format=output_format)
    _assert_bound_file_version(candidate, identity, context="output tras derivar conteo")
    return records


def derive_golden_observed_sha256(artifacts: Sequence[Mapping[str, Any]]) -> str:
    """Deriva el golden de inventario/bytes; nunca consume una ruta elegida por el adaptador."""
    material: list[dict[str, Any]] = []
    for expected_ordinal, artifact in enumerate(artifacts):
        if artifact.get("ordinal") != expected_ordinal:
            raise ContractError("golden no puede derivarse de ordinales discontinuos")
        material.append(
            {
                "relative_path": artifact.get("relative_path"),
                "identity": artifact.get("identity"),
                "ordinal": artifact.get("ordinal"),
                "format": artifact.get("format"),
                "record_count": artifact.get("record_count"),
                "logical_bytes": artifact.get("logical_bytes"),
                "sha256": artifact.get("sha256"),
                "count_evidence": artifact.get("count_evidence"),
            }
        )
    result: str = canonical_json_sha256(material)
    return result


class AtomicOutputPublisher:
    """Utilidad del adaptador consumidor: artefactos primero, manifiesto al final."""

    def __init__(
        self,
        output_root: Path,
        *,
        event_callback: Callable[[str, Path], None] | None = None,
    ) -> None:
        self.output_root = _absolute_without_following(output_root)
        parent_identity = _plain_directory_identity(
            self.output_root.parent,
            context="parent de outputs",
            create_missing=False,
        )
        _require_absent_leaf(self.output_root, context="destino de outputs")
        self.output_root.mkdir(parents=False, exist_ok=False)
        _assert_same_plain_directory(parent_identity, context="parent de outputs reservado")
        self._output_root_identity = _plain_directory_identity(
            self.output_root,
            context="destino de outputs",
            create_missing=False,
        )
        self._artifacts: list[dict[str, Any]] = []
        self._auxiliary_paths: set[str] = set()
        self._finalized = False
        self._event_callback = event_callback

    @property
    def artifacts(self) -> tuple[dict[str, Any], ...]:
        """Expone una copia inmutable de los artefactos ya publicados."""
        return tuple(dict(item) for item in self._artifacts)

    def _validate_destination(
        self, relative_path: str, identity: str, ordinal: int, output_format: str
    ) -> tuple[Path, Path]:
        if self._finalized:
            raise RuntimeError("el manifiesto final ya fue publicado")
        portable_relative = _safe_output_relative_path(relative_path, context="destino de output")
        relative = Path(*portable_relative.parts)
        if not isinstance(identity, str) or not identity:
            raise ContractError("identidad de output vacía")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise ContractError("ordinal de output inválido")
        if output_format not in OUTPUT_FORMAT_COUNTERS:
            raise ContractError(f"formato de output fuera del catálogo: {output_format!r}")
        if any(item["identity"] == identity for item in self._artifacts):
            raise ContractError(f"identidad de output duplicada: {identity}")
        if any(item["relative_path"] == relative.as_posix() for item in self._artifacts):
            raise ContractError(f"ruta de output duplicada: {relative.as_posix()}")
        if relative.as_posix() == "manifest.json":
            raise ContractError("manifest.json está reservado para publicación final")
        if relative.as_posix() in self._auxiliary_paths:
            raise ContractError(f"ruta de output colisiona con sidecar: {relative.as_posix()}")
        _assert_same_plain_directory(
            self._output_root_identity,
            context="destino de outputs",
        )
        destination = self.output_root / relative
        return relative, destination

    def _publish_stream(
        self,
        *,
        source: BinaryIO,
        relative_path: str,
        identity: str,
        ordinal: int,
        output_format: str,
        binary_record_count: int | None,
    ) -> dict[str, Any]:
        relative, destination = self._validate_destination(
            relative_path, identity, ordinal, output_format
        )
        if output_format != "bin" and binary_record_count is not None:
            raise ContractError(
                f"{output_format}: record_count externo prohibido; se deriva del formato"
            )
        if output_format == "bin" and (
            isinstance(binary_record_count, bool)
            or not isinstance(binary_record_count, int)
            or binary_record_count < 0
        ):
            raise ContractError("bin exige record_count no negativo para su sidecar firmado")
        chunks: list[dict[str, Any]] = []
        offset = 0

        def write_output(output: BinaryIO) -> None:
            nonlocal offset
            while True:
                block = source.read(MIB)
                if not block:
                    break
                output.write(block)
                chunks.append(
                    {
                        "ordinal": len(chunks),
                        "offset": offset,
                        "logical_bytes": len(block),
                        "sha256": hashlib.sha256(block).hexdigest(),
                    }
                )
                offset += len(block)

        publication = _publish_exclusive(
            destination,
            write_output,
            event_callback=self._event_callback,
        )
        _assert_same_plain_directory(
            self._output_root_identity,
            context="destino de outputs después de publicar",
        )
        _, assigned, reliable, allocation_source = file_storage_size(destination)
        output_sha256 = str(publication["sha256"])
        record_count, count_evidence = self._count_evidence(
            destination=destination,
            relative=relative,
            identity=identity,
            output_format=output_format,
            output_sha256=output_sha256,
            binary_record_count=binary_record_count,
        )
        artifact = {
            "relative_path": relative.as_posix(),
            "identity": identity,
            "ordinal": ordinal,
            "format": output_format,
            "record_count": record_count,
            "count_evidence": count_evidence,
            "logical_bytes": publication["logical_bytes"],
            "allocated_bytes": assigned,
            "allocation_reliable": reliable,
            "allocation_source": allocation_source,
            "sha256": output_sha256,
            "chunks": chunks,
        }
        artifact["reconciliation_sha256"] = canonical_json_sha256(
            {
                key: artifact[key]
                for key in (
                    "relative_path",
                    "identity",
                    "ordinal",
                    "format",
                    "record_count",
                    "count_evidence",
                    "logical_bytes",
                    "sha256",
                    "chunks",
                )
            }
        )
        self._artifacts.append(artifact)
        return artifact

    def _count_evidence(
        self,
        *,
        destination: Path,
        relative: Path,
        identity: str,
        output_format: str,
        output_sha256: str,
        binary_record_count: int | None,
    ) -> tuple[int, dict[str, Any]]:
        """Deriva el conteo o publica una atestación hash-bound para bytes opacos."""
        counter_id = OUTPUT_FORMAT_COUNTERS[output_format]
        if output_format != "bin":
            if binary_record_count is not None:
                raise ContractError(
                    f"{output_format}: record_count externo prohibido; se deriva del formato"
                )
            records = derive_output_record_count(destination, output_format=output_format)
            return records, {
                "mode": "derived",
                "counter_id": counter_id,
                "records": records,
                "output_sha256": output_sha256,
                "sidecar": None,
            }
        if (
            isinstance(binary_record_count, bool)
            or not isinstance(binary_record_count, int)
            or binary_record_count < 0
        ):
            raise ContractError("bin exige record_count no negativo para su sidecar firmado")
        sidecar_relative = Path(relative.as_posix() + ".count.json")
        sidecar_text = sidecar_relative.as_posix()
        if sidecar_text in self._auxiliary_paths or any(
            item["relative_path"] == sidecar_text for item in self._artifacts
        ):
            raise ContractError(f"sidecar de conteo duplicado: {sidecar_text}")
        sidecar_path = self.output_root / sidecar_relative
        payload = {
            "schema_version": COUNT_SIDECAR_SCHEMA_VERSION,
            "counter_id": counter_id,
            "identity": identity,
            "relative_path": relative.as_posix(),
            "output_sha256": output_sha256,
            "records": binary_record_count,
        }
        metadata = atomic_write_bytes_exclusive(
            sidecar_path,
            canonical_json_bytes(payload) + b"\n",
            event_callback=self._event_callback,
        )
        self._auxiliary_paths.add(sidecar_text)
        _assert_same_plain_directory(
            self._output_root_identity,
            context="destino de outputs después del sidecar",
        )
        return binary_record_count, {
            "mode": "hash_bound_attestation",
            "counter_id": counter_id,
            "records": binary_record_count,
            "output_sha256": output_sha256,
            "sidecar": {
                "relative_path": sidecar_text,
                "logical_bytes": metadata["logical_bytes"],
                "sha256": metadata["sha256"],
            },
        }

    def publish(
        self,
        relative_path: str,
        identity: str,
        ordinal: int,
        payload: bytes,
        *,
        output_format: str | None = None,
        record_count: int | None = None,
    ) -> dict[str, Any]:
        """Publica bytes pequeños; los adaptadores grandes deben usar ``publish_file``."""
        return self._publish_stream(
            source=io.BytesIO(payload),
            relative_path=relative_path,
            identity=identity,
            ordinal=ordinal,
            output_format=_resolve_output_format(relative_path, output_format),
            binary_record_count=record_count,
        )

    def publish_file(
        self,
        relative_path: str,
        identity: str,
        ordinal: int,
        source_path: Path,
        *,
        output_format: str | None = None,
        record_count: int | None = None,
    ) -> dict[str, Any]:
        """Publica un archivo por bloques sin materializarlo completo en RAM."""
        source_path = _safe_existing_sidecar_file(source_path, context="source output")
        source_identity = source_path.lstat()
        with source_path.open("rb") as source_handle:
            if not os.path.samestat(source_identity, os.fstat(source_handle.fileno())):
                raise ContractError("source output cambió antes de copiarlo")
            published = self._publish_stream(
                source=source_handle,
                relative_path=relative_path,
                identity=identity,
                ordinal=ordinal,
                output_format=_resolve_output_format(relative_path, output_format),
                binary_record_count=record_count,
            )
            if not os.path.samestat(source_identity, os.fstat(source_handle.fileno())):
                raise ContractError("source output cambió durante la copia")
            _safe_existing_sidecar_file(source_path, context="source output después de copiar")
            return published

    def finalize(self) -> dict[str, Any]:
        """Publica al final con golden derivado exclusivamente del inventario de outputs."""
        if self._finalized:
            raise RuntimeError("manifiesto ya publicado")
        _reject_reparse_ancestors(self.output_root, context="destino de outputs")
        ordered = sorted(self._artifacts, key=lambda value: int(value["ordinal"]))
        if [value["ordinal"] for value in ordered] != list(range(len(ordered))):
            raise ContractError("ordinales de outputs no son contiguos desde cero")
        golden_observed = derive_golden_observed_sha256(ordered)
        manifest = {
            "schema_version": OUTPUT_MANIFEST_SCHEMA_VERSION,
            "golden_observed_algorithm": GOLDEN_OBSERVED_ALGORITHM,
            "golden_observed_sha256": golden_observed,
            "artifacts": ordered,
        }
        manifest_path = self.output_root / "manifest.json"
        _assert_same_plain_directory(
            self._output_root_identity,
            context="destino de outputs antes del manifiesto",
        )
        metadata = atomic_write_bytes_exclusive(
            manifest_path,
            canonical_json_bytes(manifest) + b"\n",
            event_callback=self._event_callback,
        )
        _assert_same_plain_directory(
            self._output_root_identity,
            context="destino de outputs después del manifiesto",
        )
        self._finalized = True
        return {"manifest": manifest, "metadata": metadata}


def validate_output_manifest(
    output_root: Path,
    *,
    expected_identities: Sequence[str],
    expected_counts: Mapping[str, int] | None = None,
    expected_golden_sha256: str | None = None,
) -> dict[str, Any]:
    """Valida completitud bidireccional, orden, bytes y hashes del output final."""
    output_root = _absolute_without_following(output_root)
    _, manifest_path = _safe_existing_output_file(
        output_root,
        "manifest.json",
        context="manifiesto final",
    )
    manifest_identity = manifest_path.lstat()
    manifest = _read_canonical_json_object_file(
        manifest_path,
        context="manifiesto final",
    )
    if set(manifest) != {
        "schema_version",
        "golden_observed_algorithm",
        "golden_observed_sha256",
        "artifacts",
    }:
        raise ContractError("campos del manifiesto de outputs no son exactos")
    if manifest["schema_version"] != OUTPUT_MANIFEST_SCHEMA_VERSION:
        raise ContractError("schema del manifiesto de outputs inesperado")
    if manifest["golden_observed_algorithm"] != GOLDEN_OBSERVED_ALGORITHM:
        raise ContractError("algoritmo del golden observado inesperado")
    observed_golden = validate_sha256(
        manifest["golden_observed_sha256"], context="outputs.golden_observed_sha256"
    )
    if expected_golden_sha256 is not None and observed_golden != validate_sha256(
        expected_golden_sha256, context="expected_golden_sha256"
    ):
        raise ContractError("golden observado no coincide con el fixture firmado")
    raw_artifacts = manifest["artifacts"]
    if not isinstance(raw_artifacts, list):
        raise ContractError("artifacts no es lista")
    artifacts = [cast(dict[str, Any], item) for item in raw_artifacts if isinstance(item, dict)]
    if len(artifacts) != len(raw_artifacts):
        raise ContractError("artifact no es objeto")
    identities = [artifact.get("identity") for artifact in artifacts]
    if len(set(expected_identities)) != len(expected_identities):
        raise ContractError("expected_identities contiene duplicados")
    if identities != list(expected_identities):
        raise ContractError("identidades/orden de outputs no reconcilian")
    if expected_counts is not None and set(expected_counts) != set(expected_identities):
        raise ContractError("expected_counts no tiene el mismo dominio cerrado de identidades")
    expected_paths: set[str] = set()
    validated_versions: dict[Path, os.stat_result] = {manifest_path: manifest_identity}
    for expected_ordinal, artifact in enumerate(artifacts):
        if set(artifact) != {
            "relative_path",
            "identity",
            "ordinal",
            "format",
            "record_count",
            "count_evidence",
            "logical_bytes",
            "allocated_bytes",
            "allocation_reliable",
            "allocation_source",
            "sha256",
            "chunks",
            "reconciliation_sha256",
        }:
            raise ContractError("campos de artifact no son exactos")
        if artifact.get("ordinal") != expected_ordinal:
            raise ContractError("ordinal de output duplicado o permutado")
        relative, path = _safe_existing_output_file(
            output_root, artifact.get("relative_path"), context="output manifestado"
        )
        if relative in expected_paths or relative == "manifest.json":
            raise ContractError("relative_path de output duplicado o reservado")
        expected_paths.add(relative)
        path, output_payload, output_identity = _read_bound_file_bytes(
            path,
            context=f"output manifestado {relative}",
        )
        identity = artifact.get("identity")
        output_format = artifact.get("format")
        if not isinstance(output_format, str) or output_format not in OUTPUT_FORMAT_COUNTERS:
            raise ContractError(f"{relative}: formato fuera del catálogo")
        derived_count, auxiliary_path, auxiliary_version = _validate_count_evidence(
            output_root=output_root,
            path=path,
            output_payload=output_payload,
            artifact=artifact,
        )
        if artifact.get("record_count") != derived_count:
            raise ContractError(f"{identity}: record_count no deriva de su evidencia")
        if auxiliary_path is not None:
            if auxiliary_path in expected_paths or auxiliary_path == "manifest.json":
                raise ContractError("sidecar de conteo colisiona con otro output")
            expected_paths.add(auxiliary_path)
        if auxiliary_version is not None:
            validated_versions[auxiliary_version[0]] = auxiliary_version[1]
        if expected_counts is not None and artifact.get("record_count") != expected_counts.get(
            str(identity)
        ):
            raise ContractError(f"{identity}: record_count no reconcilia")
        logical, assigned, reliable, source = file_storage_size(path)
        checks = {
            "logical_bytes": len(output_payload),
            "allocated_bytes": assigned,
            "allocation_reliable": reliable,
            "allocation_source": source,
            "sha256": hashlib.sha256(output_payload).hexdigest(),
        }
        if logical != len(output_payload):
            raise ContractError(f"{relative}: tamaño lógico cambió entre handle y allocation")
        for key, expected in checks.items():
            if artifact.get(key) != expected:
                raise ContractError(f"{relative}: {key} no reconcilia")
        chunks = artifact.get("chunks")
        if not isinstance(chunks, list):
            raise ContractError(f"{relative}: chunks no es lista")
        offset = 0
        for chunk_ordinal, raw_chunk in enumerate(chunks):
            if not isinstance(raw_chunk, dict) or set(raw_chunk) != {
                "ordinal",
                "offset",
                "logical_bytes",
                "sha256",
            }:
                raise ContractError(f"{relative}: chunk no tiene campos exactos")
            length = raw_chunk["logical_bytes"]
            if (
                raw_chunk["ordinal"] != chunk_ordinal
                or raw_chunk["offset"] != offset
                or isinstance(length, bool)
                or not isinstance(length, int)
                or length <= 0
            ):
                raise ContractError(f"{relative}: chunks duplicados/permutados")
            block = output_payload[offset : offset + length]
            if len(block) != length or hashlib.sha256(block).hexdigest() != raw_chunk["sha256"]:
                raise ContractError(f"{relative}: hash de chunk no reconcilia")
            offset += length
        if offset != len(output_payload):
            raise ContractError(f"{relative}: chunks omiten bytes finales")
        reconciliation = canonical_json_sha256(
            {
                key: artifact[key]
                for key in (
                    "relative_path",
                    "identity",
                    "ordinal",
                    "format",
                    "record_count",
                    "count_evidence",
                    "logical_bytes",
                    "sha256",
                    "chunks",
                )
            }
        )
        if artifact.get("reconciliation_sha256") != reconciliation:
            raise ContractError(f"{relative}: reconciliación de orden/conteo no coincide")
        _assert_bound_file_version(
            path,
            output_identity,
            context=f"output manifestado {relative} final",
        )
        validated_versions[path] = output_identity
    derived_golden = derive_golden_observed_sha256(artifacts)
    if observed_golden != derived_golden:
        raise ContractError("golden observado no deriva del inventario/contenido de outputs")
    actual_files = _regular_files_no_reparse(output_root)
    actual_paths = {
        path.relative_to(_absolute_without_following(output_root)).as_posix()
        for path in actual_files
        if path != _absolute_without_following(manifest_path)
    }
    if actual_paths != expected_paths:
        raise ContractError(
            f"completitud bidireccional falla: faltan={sorted(expected_paths - actual_paths)!r}, "
            f"extra={sorted(actual_paths - expected_paths)!r}"
        )
    partials = [path for path in actual_files if path.name.endswith(".partial")]
    if partials:
        raise ContractError(f"outputs parciales persisten: {partials!r}")
    for path, version in validated_versions.items():
        _assert_bound_file_version(path, version, context=f"artefacto final {path.name}")
    final_files = _regular_files_no_reparse(output_root)
    final_paths = {
        path.relative_to(_absolute_without_following(output_root)).as_posix()
        for path in final_files
        if path != _absolute_without_following(manifest_path)
    }
    if final_paths != expected_paths or any(path.name.endswith(".partial") for path in final_files):
        raise ContractError("el árbol de outputs cambió después del censo/validación final")
    _assert_bound_tree_snapshot(
        output_root,
        final_files,
        validated_versions,
        context="árbol de outputs al cierre",
    )
    return manifest


def _validate_count_evidence(
    *,
    output_root: Path,
    path: Path,
    output_payload: bytes,
    artifact: Mapping[str, Any],
) -> tuple[int, str | None, tuple[Path, os.stat_result] | None]:
    """Reabre la evidencia causal del contador y devuelve cardinalidad + auxiliar."""
    raw = artifact.get("count_evidence")
    if not isinstance(raw, dict) or set(raw) != {
        "mode",
        "counter_id",
        "records",
        "output_sha256",
        "sidecar",
    }:
        raise ContractError("count_evidence no tiene campos exactos")
    output_format = str(artifact["format"])
    if raw["counter_id"] != OUTPUT_FORMAT_COUNTERS[output_format]:
        raise ContractError("counter_id no coincide con el formato")
    if raw["output_sha256"] != artifact.get("sha256"):
        raise ContractError("count_evidence no está ligado al hash del output")
    records = raw["records"]
    if isinstance(records, bool) or not isinstance(records, int) or records < 0:
        raise ContractError("count_evidence.records inválido")
    if output_format != "bin":
        if raw["mode"] != "derived" or raw["sidecar"] is not None:
            raise ContractError("formato derivable no puede usar sidecar de conteo")
        actual = _derive_output_record_count_payload(
            output_payload,
            output_format=output_format,
        )
        if actual != records:
            raise ContractError("conteo derivado no reconcilia con count_evidence")
        return actual, None, None
    if raw["mode"] != "hash_bound_attestation":
        raise ContractError("bin exige count_evidence ligado por hash a un sidecar")
    sidecar = raw["sidecar"]
    if not isinstance(sidecar, dict) or set(sidecar) != {
        "relative_path",
        "logical_bytes",
        "sha256",
    }:
        raise ContractError("sidecar de conteo no tiene campos exactos")
    relative, sidecar_path = _safe_existing_output_file(
        output_root, sidecar["relative_path"], context="sidecar de conteo"
    )
    sidecar_path, sidecar_payload, sidecar_identity = _read_bound_file_bytes(
        sidecar_path,
        context="sidecar de conteo",
    )
    sidecar_logical, _, _, _ = file_storage_size(sidecar_path)
    if sidecar["logical_bytes"] != sidecar_logical or sidecar_logical != len(sidecar_payload):
        raise ContractError("bytes del sidecar de conteo no reconcilian")
    if sidecar["sha256"] != hashlib.sha256(sidecar_payload).hexdigest():
        raise ContractError("hash del sidecar de conteo no reconcilia")
    payload = _parse_canonical_json_object(
        sidecar_payload,
        context="sidecar de conteo",
    )
    if set(payload) != {
        "schema_version",
        "counter_id",
        "identity",
        "relative_path",
        "output_sha256",
        "records",
    }:
        raise ContractError("payload del sidecar de conteo no tiene campos exactos")
    expected_payload = {
        "schema_version": COUNT_SIDECAR_SCHEMA_VERSION,
        "counter_id": OUTPUT_FORMAT_COUNTERS["bin"],
        "identity": artifact.get("identity"),
        "relative_path": artifact.get("relative_path"),
        "output_sha256": artifact.get("sha256"),
        "records": records,
    }
    if payload != expected_payload:
        raise ContractError("sidecar de conteo no está ligado al output/identidad")
    _assert_bound_file_version(
        sidecar_path,
        sidecar_identity,
        context="sidecar de conteo final",
    )
    return records, relative, (sidecar_path, sidecar_identity)
