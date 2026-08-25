"""Lease anti-sustitución del material de ejecución candidato (``windows_share_mode_lease_v1``).

Implementa la pieza 1 de la enmienda aprobada de congelación del material candidato
(D-LEA-1…D-LEA-9, D-LEA-14 y D-LEA-15): un handle del kernel por archivo y por directorio con
``GENERIC_READ`` y ``FILE_SHARE_READ`` como único modo compartido, sin seguir reparse points,
adquirido parent-first y **antes** del primer hash del conjunto, con hash a través del handle
retenido, cotejo por volumen y file ID contra una enumeración independiente, censo de streams
alternos y matriz cerrada de volumen. Falla cerrado: si un solo elemento no puede congelarse,
no queda ningún handle vivo.

Sólo stdlib. El cuerpo del módulo importa en Linux/macOS; toda llamada WinAPI se gatea en
tiempo de llamada, como en el resto del arnés.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .contracts import (
    CANDIDATE_MATERIAL_LEASE_MECHANISM,
    ContractError,
    canonical_json_sha256,
    validate_sha256,
)

_GENERIC_READ: Final = 0x80000000
_FILE_SHARE_READ: Final = 0x00000001
_OPEN_EXISTING: Final = 3
_FILE_ATTRIBUTE_NORMAL: Final = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000
_FILE_ATTRIBUTE_DIRECTORY: Final = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# Placeholders de Cloud Files y material offline: fuera de la matriz medida (D-LEA-15).
_FILE_ATTRIBUTE_OFFLINE: Final = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN: Final = 0x00040000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: Final = 0x00400000
_UNQUALIFIED_ATTRIBUTES: Final = (
    _FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_OPEN | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)
_FILE_STREAM_INFO_CLASS: Final = 7
_FILE_STANDARD_INFO_CLASS: Final = 1
_FILE_ID_INFO_CLASS: Final = 18
_ERROR_HANDLE_EOF: Final = 38
_ERROR_MORE_DATA: Final = 234
_DRIVE_FIXED: Final = 3
_QUALIFIED_FILESYSTEM: Final = "NTFS"
_DEFAULT_FILE_STREAMS: Final = ("::$DATA",)
_MIB: Final = 1024 * 1024

_KERNEL32: Any = None


class MaterialLeaseError(ContractError):
    """Fallo fail-closed del lease de material candidato."""


class LeaseAcquisitionError(MaterialLeaseError):
    """La adquisición del lease no pudo congelar un elemento del conjunto."""


class LeaseCoverageError(MaterialLeaseError):
    """El cotejo del conjunto congelado no reconcilia con el inventario canónico."""


class LeaseStreamError(MaterialLeaseError):
    """Un elemento del conjunto congelado expone streams no predeterminados (D-LEA-14)."""


class LeaseVolumeError(MaterialLeaseError):
    """El material reside fuera de la matriz cerrada de volumen (D-LEA-15)."""


class LeaseOrderError(MaterialLeaseError):
    """Se violó el orden contractual lease→hash→liberación (D-LEA-8)."""


class LeaseReleaseError(MaterialLeaseError):
    """La liberación del lease no quedó verificada.

    ``pending_handles`` conserva los handles cuyo cierre falló para que el dueño pueda
    reintentar el cleanup en vez de perder la referencia (hallazgo de revisión A.1).
    """

    def __init__(self, message: str, *, pending_handles: tuple[int, ...] = ()) -> None:
        super().__init__(message)
        self.pending_handles = pending_handles


@dataclass(frozen=True)
class _HandleIdentity:
    """Identidad por handle en las dos convenciones que publica CPython según su versión.

    Medido: 3.12+ deriva ``st_dev``/``st_ino`` de ``FILE_ID_INFO`` —serial de 64 bits y los
    64 bits bajos del ``FileId`` de 128—, mientras 3.11 los deriva de
    ``BY_HANDLE_FILE_INFORMATION`` —serial de 32 bits e índice de 64—. El lease no elige por
    versión: conserva ambas y acepta la que reconcilie con el ``stat`` observado.
    """

    attributes: int
    number_of_links: int
    volume_serial: int
    file_index: int
    logical_bytes: int
    classic_volume_serial: int
    classic_file_index: int

    def resolve_against(self, metadata: os.stat_result) -> tuple[int, int] | None:
        """Devuelve ``(serial, index)`` en la convención de este ``stat``, o ``None``."""
        observed = (int(metadata.st_dev), int(metadata.st_ino))
        for candidate in (
            (self.volume_serial, self.file_index),
            (self.classic_volume_serial, self.classic_file_index),
        ):
            if candidate == observed:
                return candidate
        return None


@dataclass(frozen=True)
class _LeasedEntry:
    relative_path: str
    kind: str
    path: Path
    handle: int
    volume_serial: int
    file_index: int
    logical_bytes: int


class _WindowsFileStandardInfo(ctypes.Structure):
    """Layout ABI exacto de ``FILE_STANDARD_INFO`` (Win32)."""

    _fields_ = [
        ("allocation_size", ctypes.c_longlong),
        ("end_of_file", ctypes.c_longlong),
        ("number_of_links", ctypes.c_uint32),
        ("delete_pending", ctypes.c_ubyte),
        ("directory", ctypes.c_ubyte),
    ]


class _WindowsFileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _WindowsByHandleFileInformation(ctypes.Structure):
    """Layout ABI exacto de ``BY_HANDLE_FILE_INFORMATION`` (Win32)."""

    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time", _WindowsFileTime),
        ("last_access_time", _WindowsFileTime),
        ("last_write_time", _WindowsFileTime),
        ("volume_serial_number", ctypes.c_uint32),
        ("file_size_high", ctypes.c_uint32),
        ("file_size_low", ctypes.c_uint32),
        ("number_of_links", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


class _WindowsFileIdInfo(ctypes.Structure):
    """Layout ABI exacto de ``FILE_ID_INFO`` (Win32).

    Medido en esta torre (Python 3.12.10): ``st_dev`` es el serial de volumen de 64 bits de
    esta estructura y ``st_ino`` son los 64 bits bajos de su ``FileId`` de 128; el serial
    clásico de 32 bits de ``GetVolumeInformationByHandleW`` son los 32 bits bajos del de 64.
    """

    _fields_ = [
        ("volume_serial_number", ctypes.c_ulonglong),
        ("file_id", ctypes.c_ubyte * 16),
    ]


def _require_windows(context: str) -> None:
    if sys.platform != "win32":
        raise MaterialLeaseError(f"{context}: el lease de material candidato exige Windows")


def _kernel32() -> Any:
    """Carga kernel32 una sola vez y fija los prototipos que usa el lease."""
    global _KERNEL32
    _require_windows("kernel32")
    if _KERNEL32 is not None:
        return _KERNEL32
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
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.ReadFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = ctypes.c_int
    kernel32.SetFilePointerEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        ctypes.c_uint32,
    ]
    kernel32.SetFilePointerEx.restype = ctypes.c_int
    kernel32.GetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_WindowsByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = ctypes.c_int
    kernel32.GetFileInformationByHandleEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.GetFileInformationByHandleEx.restype = ctypes.c_int
    kernel32.GetVolumeInformationByHandleW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel32.GetVolumeInformationByHandleW.restype = ctypes.c_int
    kernel32.GetVolumePathNameW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
    ]
    kernel32.GetVolumePathNameW.restype = ctypes.c_int
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint32
    _KERNEL32 = kernel32
    return kernel32


def _absolute_without_following(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reparse_bit(metadata: os.stat_result) -> bool:
    return bool(int(getattr(metadata, "st_file_attributes", 0)) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _check_deadline(deadline_monotonic: float | None, path: Path) -> None:
    if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
        raise MaterialLeaseError(
            f"preflight_rejected: el lease del material excedió el deadline: {path}"
        )


def _open_lease_handle(path: Path, *, directory: bool) -> int:
    """Abre el handle contractual del lease (D-LEA-2) sin seguir reparse points."""
    kernel32 = _kernel32()
    flags = _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_ATTRIBUTE_NORMAL
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    raw_handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if raw_handle in {None, invalid_handle}:
        code = ctypes.get_last_error()
        raise LeaseAcquisitionError(f"no se pudo adquirir el lease: {path} (winerror={code})")
    return int(raw_handle)


def _close_handle(handle: int) -> int:
    """Cierra un handle; devuelve 0 en éxito o el winerror del fallo."""
    kernel32 = _kernel32()
    if not kernel32.CloseHandle(handle):
        return int(ctypes.get_last_error())
    return 0


def _close_handles(handles: Sequence[int]) -> list[tuple[int, int]]:
    """Cierra cada handle y devuelve ``(handle, winerror)`` por falla; nunca lanza a medias."""
    failures: list[tuple[int, int]] = []
    for handle in handles:
        code = _close_handle(handle)
        if code:
            failures.append((handle, code))
    return failures


def _reject_reparse_ancestors(path: Path, *, context: str) -> None:
    """Rechaza reparse points en toda la ruta del conjunto, incluida su raíz."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise LeaseAcquisitionError(f"{context}: ruta o ancestro ausente: {current}") from exc
        if current.is_symlink() or _reparse_bit(metadata):
            raise LeaseAcquisitionError(
                f"{context}: reparse point en la ruta del conjunto: {current}"
            )


def _pin_ancestors(root: Path, *, handles: list[int]) -> list[_LeasedEntry]:
    """Retiene un handle no-follow por cada ancestro de ``root``, desde el ancla del volumen.

    Sin esto, el lease es vulnerable a una interposición transitoria: medido en esta torre,
    un handle abierto **a través** de una junction no fija esa junction, de modo que un
    tercero puede retirarla y recolocarla para que la ruta vuelva a resolver a un árbol real
    no leaseado mientras el lease retiene un señuelo byte-idéntico. Un handle retenido sobre
    cada componente sí lo impide: borrar o renombrar un directorio con handle vivo falla.

    Coste colateral medido en esta torre, y acotado a propósito: mientras el lease vive,
    crear archivos y subdirectorios dentro de un ancestro fijado sigue **permitido**, pero
    *mover* una entrada hacia él y borrar o renombrar el propio ancestro quedan bloqueados
    con ``winerror=32``. Es el precio de cerrar la sustitución por la ruta; el ancla vive
    bajo el temp del arnés, no en superficies compartidas del sistema.
    """
    pinned: list[_LeasedEntry] = []
    current = Path(root.anchor)
    for part in root.parts[1:-1]:
        current = current / part
        try:
            before = current.lstat()
        except FileNotFoundError as exc:
            raise LeaseAcquisitionError(f"ancestro del ancla ausente: {current}") from exc
        if current.is_symlink() or _reparse_bit(before):
            raise LeaseAcquisitionError(f"reparse point en un ancestro del ancla: {current}")
        handle = _open_lease_handle(current, directory=True)
        handles.append(handle)
        identity = _census_handle_identity(handle, current)
        if identity.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise LeaseAcquisitionError(f"reparse point capturado en un ancestro: {current}")
        if not identity.attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise LeaseAcquisitionError(f"un ancestro del ancla dejó de ser directorio: {current}")
        resolved = identity.resolve_against(before)
        if resolved is None:
            raise LeaseAcquisitionError(f"un ancestro del ancla cambió al fijarlo: {current}")
        serial, index = resolved
        pinned.append(
            _LeasedEntry(
                relative_path=str(current),
                kind="ancestor",
                path=current,
                handle=handle,
                volume_serial=serial,
                file_index=index,
                logical_bytes=0,
            )
        )
    return pinned


def _census_handle_identity(handle: int, path: Path) -> _HandleIdentity:
    """Atestigua atributos, enlaces, volumen y file ID a través del handle retenido.

    El serial de volumen y el file ID salen de ``FILE_ID_INFO`` porque son los ejes que
    CPython 3.12 publica como ``st_dev``/``st_ino`` (medido en la torre writer); el índice
    clásico de 64 bits de ``BY_HANDLE_FILE_INFORMATION`` debe reconciliar con ellos.
    """
    kernel32 = _kernel32()
    identity = _WindowsByHandleFileInformation()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(identity)):
        code = ctypes.get_last_error()
        raise LeaseAcquisitionError(f"GetFileInformationByHandle falló: {path} (winerror={code})")
    file_id_info = _WindowsFileIdInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle, _FILE_ID_INFO_CLASS, ctypes.byref(file_id_info), ctypes.sizeof(file_id_info)
    ):
        code = ctypes.get_last_error()
        raise LeaseAcquisitionError(f"FILE_ID_INFO falló: {path} (winerror={code})")
    file_id = int.from_bytes(bytes(file_id_info.file_id), "little")
    classic_index = (int(identity.file_index_high) << 32) | int(identity.file_index_low)
    volume_serial = int(file_id_info.volume_serial_number)
    classic_serial = int(identity.volume_serial_number)
    if file_id != classic_index or (volume_serial & 0xFFFFFFFF) != classic_serial:
        raise LeaseAcquisitionError(f"identidad por handle no reconcilia entre APIs: {path}")
    return _HandleIdentity(
        attributes=int(identity.attributes),
        number_of_links=int(identity.number_of_links),
        volume_serial=volume_serial,
        file_index=file_id,
        logical_bytes=(int(identity.file_size_high) << 32) | int(identity.file_size_low),
        classic_volume_serial=classic_serial,
        classic_file_index=classic_index,
    )


def _census_streams_by_handle(handle: int, path: Path) -> tuple[str, ...]:
    """Enumera los streams del elemento por el handle retenido (D-LEA-14)."""
    kernel32 = _kernel32()
    buffer_bytes = 64 * 1024
    while True:
        buffer = ctypes.create_string_buffer(buffer_bytes)
        if kernel32.GetFileInformationByHandleEx(
            handle, _FILE_STREAM_INFO_CLASS, buffer, buffer_bytes
        ):
            payload = buffer.raw
            break
        code = ctypes.get_last_error()
        if code == _ERROR_HANDLE_EOF:
            return ()
        if code == _ERROR_MORE_DATA:
            buffer_bytes *= 4
            continue
        raise LeaseStreamError(f"censo de streams falló: {path} (winerror={code})")
    names: list[str] = []
    offset = 0
    while True:
        next_offset = int.from_bytes(payload[offset : offset + 4], "little")
        name_bytes = int.from_bytes(payload[offset + 4 : offset + 8], "little")
        name_start = offset + 24
        name = payload[name_start : name_start + name_bytes].decode("utf-16-le")
        names.append(name)
        if next_offset == 0:
            return tuple(names)
        offset += next_offset


def _require_default_streams(streams: tuple[str, ...], path: Path, *, directory: bool) -> None:
    """Rechaza todo stream no predeterminado del elemento congelado (D-LEA-14)."""
    allowed: tuple[str, ...] = () if directory else _DEFAULT_FILE_STREAMS
    for name in streams:
        if name not in allowed:
            raise LeaseStreamError(
                f"stream no predeterminado en el conjunto congelado: {path}: {name}"
            )


def _query_volume_by_handle(handle: int, path: Path) -> dict[str, Any]:
    """Atestigua filesystem y volumen por el handle raíz, y el tipo de unidad por su raíz."""
    kernel32 = _kernel32()
    volume_name = ctypes.create_unicode_buffer(256)
    filesystem_name = ctypes.create_unicode_buffer(256)
    serial = ctypes.c_uint32(0)
    max_component = ctypes.c_uint32(0)
    flags = ctypes.c_uint32(0)
    if not kernel32.GetVolumeInformationByHandleW(
        handle,
        volume_name,
        len(volume_name),
        ctypes.byref(serial),
        ctypes.byref(max_component),
        ctypes.byref(flags),
        filesystem_name,
        len(filesystem_name),
    ):
        code = ctypes.get_last_error()
        raise LeaseVolumeError(f"GetVolumeInformationByHandleW falló: {path} (winerror={code})")
    volume_root = ctypes.create_unicode_buffer(32_768)
    if not kernel32.GetVolumePathNameW(str(path), volume_root, len(volume_root)):
        code = ctypes.get_last_error()
        raise LeaseVolumeError(f"GetVolumePathNameW falló: {path} (winerror={code})")
    drive_type = int(kernel32.GetDriveTypeW(volume_root.value))
    return {
        "filesystem": str(filesystem_name.value),
        "volume_serial": int(serial.value),
        "volume_root": str(volume_root.value),
        "drive_type": drive_type,
    }


def _require_qualified_volume(volume: Mapping[str, Any], entries: Sequence[_LeasedEntry]) -> None:
    """Aplica la matriz cerrada de volumen (D-LEA-15): NTFS local y un solo volumen."""
    filesystem = str(volume["filesystem"])
    if filesystem != _QUALIFIED_FILESYSTEM:
        raise LeaseVolumeError(f"filesystem no calificado por la matriz de volumen: {filesystem!r}")
    drive_type = int(volume["drive_type"])
    if drive_type != _DRIVE_FIXED:
        raise LeaseVolumeError(f"unidad no calificada por la matriz de volumen: tipo {drive_type}")
    root_serial = entries[0].volume_serial
    if (root_serial & 0xFFFFFFFF) != int(volume["volume_serial"]):
        raise LeaseVolumeError("serial del volumen no reconcilia entre handle raíz y volumen")
    for entry in entries:
        if entry.volume_serial != root_serial:
            raise LeaseVolumeError(f"material multivolumen no calificado: {entry.relative_path}")


def _hash_through_handle(
    handle: int, path: Path, *, deadline_monotonic: float | None
) -> tuple[int, str]:
    """Hashea el elemento a través del handle retenido, sin reabrir por ruta (D-LEA-7)."""
    kernel32 = _kernel32()
    position = ctypes.c_longlong(0)
    if not kernel32.SetFilePointerEx(handle, 0, ctypes.byref(position), 0):
        code = ctypes.get_last_error()
        raise MaterialLeaseError(f"SetFilePointerEx falló: {path} (winerror={code})")
    digest = hashlib.sha256()
    logical_bytes = 0
    buffer = ctypes.create_string_buffer(_MIB)
    read_count = ctypes.c_uint32(0)
    while True:
        _check_deadline(deadline_monotonic, path)
        if not kernel32.ReadFile(handle, buffer, _MIB, ctypes.byref(read_count), None):
            code = ctypes.get_last_error()
            raise MaterialLeaseError(f"ReadFile bajo lease falló: {path} (winerror={code})")
        chunk = int(read_count.value)
        if chunk == 0:
            break
        digest.update(buffer.raw[:chunk])
        logical_bytes += chunk
    standard = _WindowsFileStandardInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle, _FILE_STANDARD_INFO_CLASS, ctypes.byref(standard), ctypes.sizeof(standard)
    ):
        code = ctypes.get_last_error()
        raise MaterialLeaseError(f"censo estándar bajo lease falló: {path} (winerror={code})")
    if int(standard.end_of_file) != logical_bytes or bool(standard.delete_pending):
        raise MaterialLeaseError(f"el archivo cambió durante el hash bajo lease: {path}")
    return logical_bytes, digest.hexdigest()


def _acquire_directory_children(
    directory: Path, *, deadline_monotonic: float | None = None
) -> list[tuple[str, bool]]:
    """Enumera y clasifica los hijos directos para el adquisidor, en orden estable."""
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name.casefold())
    except OSError as exc:
        raise LeaseAcquisitionError(f"no se pudo censar el directorio: {directory}") from exc
    children: list[tuple[str, bool]] = []
    for entry in entries:
        candidate = Path(entry.path)
        _check_deadline(deadline_monotonic, candidate)
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise LeaseAcquisitionError(f"no se pudo inspeccionar: {candidate}") from exc
        if entry.is_symlink() or _reparse_bit(metadata):
            raise LeaseAcquisitionError(
                f"reparse point prohibido en el conjunto congelado: {candidate}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            children.append((entry.name, True))
        elif stat.S_ISREG(metadata.st_mode):
            if int(getattr(metadata, "st_nlink", 1)) != 1:
                raise LeaseAcquisitionError(
                    f"hardlink prohibido en el conjunto congelado: {candidate}"
                )
            children.append((entry.name, False))
        else:
            raise LeaseAcquisitionError(
                f"entrada no regular prohibida en el conjunto congelado: {candidate}"
            )
    return children


def _acquire_single(
    path: Path,
    relative_path: str,
    *,
    directory: bool,
    handles: list[int],
    deadline_monotonic: float | None,
) -> _LeasedEntry:
    """Congela un elemento: inspección, handle contractual y censo por el handle."""
    _check_deadline(deadline_monotonic, path)
    try:
        before = path.lstat()
    except OSError as exc:
        raise LeaseAcquisitionError(f"no se pudo inspeccionar: {path}") from exc
    if path.is_symlink() or _reparse_bit(before):
        raise LeaseAcquisitionError(f"reparse point prohibido en el conjunto congelado: {path}")
    if directory != stat.S_ISDIR(before.st_mode):
        raise LeaseAcquisitionError(f"el tipo del material cambió antes del lease: {path}")
    if not directory and int(getattr(before, "st_nlink", 1)) != 1:
        raise LeaseAcquisitionError(f"hardlink prohibido en el conjunto congelado: {path}")
    handle = _open_lease_handle(path, directory=directory)
    handles.append(handle)
    identity = _census_handle_identity(handle, path)
    if identity.attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise LeaseAcquisitionError(f"reparse point capturado por el lease: {path}")
    if bool(identity.attributes & _FILE_ATTRIBUTE_DIRECTORY) != directory:
        raise LeaseAcquisitionError(f"el tipo del material cambió al adquirir el lease: {path}")
    if identity.attributes & _UNQUALIFIED_ATTRIBUTES:
        raise LeaseVolumeError(f"material respaldado por nube u offline no calificado: {path}")
    if not directory and identity.number_of_links != 1:
        raise LeaseAcquisitionError(f"hardlink capturado por el lease: {path}")
    resolved = identity.resolve_against(before)
    if resolved is None or (not directory and identity.logical_bytes != int(before.st_size)):
        raise LeaseAcquisitionError(f"el material cambió al adquirir el lease: {path}")
    serial, index = resolved
    _require_default_streams(_census_streams_by_handle(handle, path), path, directory=directory)
    return _LeasedEntry(
        relative_path=relative_path,
        kind="directory" if directory else "file",
        path=path,
        handle=handle,
        volume_serial=serial,
        file_index=index,
        logical_bytes=0 if directory else identity.logical_bytes,
    )


def _verification_census(
    root: Path, *, deadline_monotonic: float | None = None
) -> tuple[dict[str, tuple[int, int, int]], dict[str, tuple[int, int]]]:
    """Enumera el árbol de forma independiente del adquisidor para el cotejo (D-LEA-6)."""
    files: dict[str, tuple[int, int, int]] = {}
    directories: dict[str, tuple[int, int]] = {}
    root_metadata = root.lstat()
    if root.is_symlink() or _reparse_bit(root_metadata):
        raise LeaseCoverageError(f"cotejo independiente: reparse point en el árbol: {root}")
    directories["."] = (int(root_metadata.st_dev), int(root_metadata.st_ino))
    pending: list[tuple[Path, str]] = [(root, ".")]
    while pending:
        directory, prefix = pending.pop()
        try:
            names = sorted(os.listdir(directory))
        except OSError as exc:
            raise LeaseCoverageError(
                f"cotejo independiente: no se pudo censar: {directory}"
            ) from exc
        for name in names:
            candidate = directory / name
            relative = name if prefix == "." else f"{prefix}/{name}"
            _check_deadline(deadline_monotonic, candidate)
            metadata = candidate.lstat()
            if candidate.is_symlink() or _reparse_bit(metadata):
                raise LeaseCoverageError(
                    f"cotejo independiente: reparse point en el árbol: {candidate}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                directories[relative] = (int(metadata.st_dev), int(metadata.st_ino))
                pending.append((candidate, relative))
            elif stat.S_ISREG(metadata.st_mode):
                if int(getattr(metadata, "st_nlink", 1)) != 1:
                    raise LeaseCoverageError(
                        f"cotejo independiente: hardlink en el árbol: {candidate}"
                    )
                files[relative] = (
                    int(metadata.st_dev),
                    int(metadata.st_ino),
                    int(metadata.st_size),
                )
            else:
                raise LeaseCoverageError(
                    f"cotejo independiente: entrada no regular en el árbol: {candidate}"
                )
    return files, directories


def _normalize_expected_entries(
    expected_entries: Sequence[Mapping[str, Any]], expected_tree_sha256: str
) -> dict[str, tuple[int, str]]:
    """Valida el inventario canónico recibido y su ligadura al digest agregado (D-LEA-5)."""
    if not expected_entries:
        raise LeaseCoverageError("inventario canónico vacío: no hay conjunto que congelar")
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(expected_entries):
        if set(entry) != {"relative_path", "bytes", "sha256"}:
            raise LeaseCoverageError(f"entrada {index} del inventario sin campos exactos")
        relative_path = entry["relative_path"]
        byte_count = entry["bytes"]
        if not isinstance(relative_path, str) or not relative_path:
            raise LeaseCoverageError(f"entrada {index} del inventario con relative_path inválido")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise LeaseCoverageError(f"entrada {index} del inventario con bytes inválidos")
        digest = validate_sha256(entry["sha256"], context=f"inventario[{index}].sha256")
        normalized.append({"relative_path": relative_path, "bytes": byte_count, "sha256": digest})
    ordered = [str(entry["relative_path"]) for entry in normalized]
    if ordered != sorted(set(ordered)):
        raise LeaseCoverageError("inventario canónico duplicado o fuera de orden")
    if canonical_json_sha256(normalized) != expected_tree_sha256:
        raise LeaseCoverageError("inventario canónico no liga con el digest agregado")
    return {
        str(entry["relative_path"]): (int(entry["bytes"]), str(entry["sha256"]))
        for entry in normalized
    }


def _verify_coverage(
    root: Path,
    entries: Sequence[_LeasedEntry],
    expected: Mapping[str, tuple[int, str]],
    *,
    deadline_monotonic: float | None = None,
) -> None:
    """Coteja lease, árbol e inventario en ambos sentidos, nombrando al ofensor (D-LEA-5/6)."""
    observed_files, observed_directories = _verification_census(
        root, deadline_monotonic=deadline_monotonic
    )
    expected_directories = {"."}
    for relative in expected:
        parts = relative.split("/")[:-1]
        prefix = ""
        for part in parts:
            prefix = part if not prefix else f"{prefix}/{part}"
            expected_directories.add(prefix)
    for relative in sorted(expected):
        if relative not in observed_files:
            raise LeaseCoverageError(f"archivo esperado ausente del árbol: {relative}")
    for relative in sorted(observed_files):
        if relative not in expected:
            raise LeaseCoverageError(f"alta no declarada en el conjunto congelado: {relative}")
    for relative in sorted(observed_directories):
        if relative not in expected_directories:
            raise LeaseCoverageError(
                f"directorio no declarado en el conjunto congelado: {relative}"
            )
    leased_files = {entry.relative_path: entry for entry in entries if entry.kind == "file"}
    leased_directories = {
        entry.relative_path: entry for entry in entries if entry.kind == "directory"
    }
    for relative in sorted(observed_files):
        if relative not in leased_files:
            raise LeaseCoverageError(f"presente en el árbol y no leaseado: {relative}")
    for relative in sorted(observed_directories):
        if relative not in leased_directories:
            raise LeaseCoverageError(f"presente en el árbol y no leaseado: {relative}")
    for relative in sorted(leased_files):
        if relative not in observed_files:
            raise LeaseCoverageError(
                f"leaseado y ausente de la enumeración independiente: {relative}"
            )
    for relative in sorted(leased_directories):
        if relative not in observed_directories:
            raise LeaseCoverageError(
                f"leaseado y ausente de la enumeración independiente: {relative}"
            )
    for relative, (device, inode, size) in observed_files.items():
        entry = leased_files[relative]
        declared_bytes = expected[relative][0]
        if (
            entry.volume_serial != device
            or entry.file_index != inode
            or entry.logical_bytes != size
            or declared_bytes != size
        ):
            raise LeaseCoverageError(f"identidad por volumen y file ID no reconcilia: {relative}")
    for relative, (device, inode) in observed_directories.items():
        entry = leased_directories[relative]
        if entry.volume_serial != device or entry.file_index != inode:
            raise LeaseCoverageError(f"identidad por volumen y file ID no reconcilia: {relative}")


class MaterialLease:
    """Conjunto congelado con handles retenidos: hash por handle y liberación verificada.

    Las instancias se construyen únicamente con :func:`acquire_material_lease`.
    """

    def __init__(
        self,
        *,
        root: Path,
        entries: tuple[_LeasedEntry, ...],
        expected: Mapping[str, tuple[int, str]],
        volume: Mapping[str, Any],
        acquisition_started_ns: int,
        acquisition_completed_ns: int,
        acquisition_started_monotonic_ns: int,
        ancestors: tuple[_LeasedEntry, ...] = (),
        first_hash_started_ns: int | None = None,
    ) -> None:
        self._root = root
        self._entries = entries
        self._ancestors = ancestors
        self._expected = dict(expected)
        self._volume = dict(volume)
        self._acquisition_started_ns = acquisition_started_ns
        self._acquisition_completed_ns = acquisition_completed_ns
        # Los hitos perf (QPC) separan lease→hash aun en árboles chicos; los monotónicos
        # comparten reloj con READY/START/quiescencia del supervisor para que la evidencia
        # pueda relacionar la liberación con esos momentos (D-LEA-18).
        self._acquisition_started_monotonic_ns = acquisition_started_monotonic_ns
        self._release_completed_monotonic_ns: int | None = None
        self._first_hash_started_ns = first_hash_started_ns
        self._hash_completed_ns: int | None = None
        self._release_completed_ns: int | None = None
        self._released = False
        # Handles todavía vivos: una liberación fallida los conserva para reintentar el
        # cierre en vez de declararlos liberados (fail-closed, hallazgo de revisión A.1).
        self._pending: dict[str, _LeasedEntry] = {
            entry.relative_path: entry for entry in (*entries, *ancestors)
        }
        # Una violación de streams detectada durante la liberación es terminal: sobrevive a
        # los reintentos de cierre para que un CloseHandle fallido no la borre.
        self._stream_violation: LeaseStreamError | None = None

    @property
    def root(self) -> Path:
        """Raíz absoluta del conjunto congelado."""
        return self._root

    @property
    def released(self) -> bool:
        """Si los handles del lease ya fueron liberados."""
        return self._released

    def _require_live(self) -> None:
        if self._released:
            raise LeaseOrderError("el lease fue liberado antes del hash del conjunto")
        if len(self._pending) != len(self._entries) + len(self._ancestors):
            raise LeaseOrderError("el lease tiene una liberación parcial en curso")

    def hash_and_verify(
        self, *, deadline_monotonic: float | None = None
    ) -> dict[str, dict[str, Any]]:
        """Hashea cada archivo por su handle retenido y reconcilia contra el inventario."""
        self._require_live()
        digests: dict[str, dict[str, Any]] = {}
        for entry in sorted(self._entries, key=lambda item: item.relative_path):
            if entry.kind != "file":
                continue
            if self._first_hash_started_ns is None:
                self._first_hash_started_ns = time.perf_counter_ns()
            logical_bytes, digest = _hash_through_handle(
                entry.handle, entry.path, deadline_monotonic=deadline_monotonic
            )
            declared_bytes, declared_sha256 = self._expected[entry.relative_path]
            if logical_bytes != declared_bytes or digest != declared_sha256:
                raise LeaseCoverageError(
                    f"material no reconcilia con el inventario: {entry.relative_path}"
                )
            digests[entry.relative_path] = {"logical_bytes": logical_bytes, "sha256": digest}
        self._hash_completed_ns = time.perf_counter_ns()
        return digests

    def verify_streams(self) -> None:
        """Repite el censo de streams por handle sobre todo el conjunto (D-LEA-14)."""
        self._require_live()
        self._census_pending_streams()

    def _census_pending_streams(self) -> None:
        for entry in self._pending.values():
            _require_default_streams(
                _census_streams_by_handle(entry.handle, entry.path),
                entry.path,
                directory=entry.kind in {"directory", "ancestor"},
            )

    def release(self) -> None:
        """Censa streams por última vez, libera todos los handles y verifica el cierre.

        El censo final es obligatorio (D-LEA-14): un ADS plantado tras la adquisición pone
        roja la liberación aunque los bytes hayan reconciliado. Un ``CloseHandle`` fallido
        conserva el handle como vivo y deja la liberación reintentable, nunca declarada.
        """
        if self._released:
            raise LeaseReleaseError("el lease ya fue liberado")
        try:
            self._census_pending_streams()
        except LeaseStreamError as error:
            self._stream_violation = error
        failures: list[str] = []
        for relative_path, entry in list(self._pending.items()):
            code = _close_handle(entry.handle)
            if code:
                failures.append(f"{relative_path} (winerror={code})")
            else:
                del self._pending[relative_path]
        if self._pending:
            raise LeaseReleaseError(
                f"la liberación del lease dejó handles vivos: {', '.join(failures)}",
                pending_handles=tuple(entry.handle for entry in self._pending.values()),
            )
        self._released = True
        self._release_completed_ns = time.perf_counter_ns()
        self._release_completed_monotonic_ns = time.monotonic_ns()
        if self._stream_violation is not None:
            raise self._stream_violation

    def attestation(self) -> dict[str, Any]:
        """Censo publicable del lease: mecanismo, volumen, orden y elementos (D-LEA-18).

        Cada archivo publica además el ``sha256`` del inventario canónico ya ligado al
        digest agregado (D-LEA-5), de modo que un consumidor durable pueda recomputar el
        digest del árbol desde el propio censo sin reabrir material vivo.
        """
        return {
            "mechanism": CANDIDATE_MATERIAL_LEASE_MECHANISM,
            "root": str(self._root),
            "volume": dict(self._volume),
            "files": sum(1 for entry in self._entries if entry.kind == "file"),
            "directories": sum(1 for entry in self._entries if entry.kind == "directory"),
            "pinned_ancestors": len(self._ancestors),
            "acquisition_started_perf_ns": self._acquisition_started_ns,
            "acquisition_completed_perf_ns": self._acquisition_completed_ns,
            "acquisition_started_monotonic_ns": self._acquisition_started_monotonic_ns,
            "first_hash_started_perf_ns": self._first_hash_started_ns,
            "hash_completed_perf_ns": self._hash_completed_ns,
            "released": self._released,
            "release_completed_perf_ns": self._release_completed_ns,
            "release_completed_monotonic_ns": self._release_completed_monotonic_ns,
            "entries": [
                {
                    "relative_path": entry.relative_path,
                    "kind": entry.kind,
                    "volume_serial": entry.volume_serial,
                    "file_index": entry.file_index,
                    "logical_bytes": entry.logical_bytes,
                    "sha256": (
                        self._expected[entry.relative_path][1] if entry.kind == "file" else None
                    ),
                }
                for entry in self._entries
            ],
        }


def acquire_material_lease(
    root: Path,
    *,
    expected_entries: Sequence[Mapping[str, Any]],
    expected_tree_sha256: str,
    deadline_monotonic: float | None = None,
) -> MaterialLease:
    """Congela el árbol bajo ``windows_share_mode_lease_v1`` antes de cualquier hash.

    Adquiere parent-first (D-LEA-4), falla cerrado sin dejar handles vivos (D-LEA-3),
    coteja cobertura e identidad contra una enumeración independiente y el inventario
    canónico (D-LEA-5, D-LEA-6), censa streams (D-LEA-14) y aplica la matriz de volumen
    (D-LEA-15). El hash del conjunto ocurre después, por :meth:`MaterialLease.hash_and_verify`
    sobre los handles retenidos (D-LEA-7, D-LEA-8).

    El ancla es contrato del llamador: los ancestros de ``root`` se censan sin reparse
    points al abrir y al cerrar la adquisición, pero su estabilidad posterior la debe
    garantizar quien posee el workdir (el cableado A.1c conserva la disciplina vigente de
    ``_require_plain_directory`` del supervisor sobre esa ruta).
    """
    _require_windows("acquire_material_lease")
    expected = _normalize_expected_entries(expected_entries, expected_tree_sha256)
    absolute_root = _absolute_without_following(root)
    # time.monotonic_ns() tiene granularidad ~15,6 ms en esta torre (medido): dejaría vacua la
    # invariante lease→hash sobre árboles chicos. perf_counter_ns (QPC) sí separa los hitos.
    # El gemelo monotónico comparte reloj con el supervisor para D-LEA-18.
    acquisition_started_ns = time.perf_counter_ns()
    acquisition_started_monotonic_ns = time.monotonic_ns()
    _reject_reparse_ancestors(absolute_root, context="ancla del lease")
    handles: list[int] = []
    try:
        ancestors = _pin_ancestors(absolute_root, handles=handles)
        entries: list[_LeasedEntry] = [
            _acquire_single(
                absolute_root,
                ".",
                directory=True,
                handles=handles,
                deadline_monotonic=deadline_monotonic,
            )
        ]
        pending: list[tuple[Path, str]] = [(absolute_root, ".")]
        while pending:
            directory, prefix = pending.pop(0)
            for name, is_directory in _acquire_directory_children(
                directory, deadline_monotonic=deadline_monotonic
            ):
                child = directory / name
                relative = name if prefix == "." else f"{prefix}/{name}"
                entries.append(
                    _acquire_single(
                        child,
                        relative,
                        directory=is_directory,
                        handles=handles,
                        deadline_monotonic=deadline_monotonic,
                    )
                )
                if is_directory:
                    pending.append((child, relative))
        volume = _query_volume_by_handle(entries[0].handle, absolute_root)
        _require_qualified_volume(volume, entries)
        acquisition_completed_ns = time.perf_counter_ns()
        _verify_coverage(absolute_root, entries, expected, deadline_monotonic=deadline_monotonic)
        # Segundo censo del ancla, ya con cada ancestro fijado por su propio handle: cierra
        # la ventana entre el censo inicial y el pin, y deja constancia de que la ruta sigue
        # siendo plana al terminar la adquisición.
        _reject_reparse_ancestors(absolute_root, context="ancla del lease al cierre")
        for ancestor in ancestors:
            observed = ancestor.path.lstat()
            if int(observed.st_ino) != ancestor.file_index or int(observed.st_dev) != (
                ancestor.volume_serial
            ):
                raise LeaseAcquisitionError(
                    f"un ancestro del ancla fue sustituido durante la adquisición: {ancestor.path}"
                )
        _check_deadline(deadline_monotonic, absolute_root)
    except BaseException as error:
        rollback_failures = _close_handles(handles)
        if rollback_failures:
            detail = ", ".join(f"handle={h} (winerror={c})" for h, c in rollback_failures)
            raise LeaseReleaseError(
                f"el rollback del lease dejó handles vivos: {detail}",
                pending_handles=tuple(h for h, _ in rollback_failures),
            ) from error
        raise
    return MaterialLease(
        root=absolute_root,
        entries=tuple(entries),
        ancestors=tuple(ancestors),
        expected=expected,
        volume=volume,
        acquisition_started_ns=acquisition_started_ns,
        acquisition_completed_ns=acquisition_completed_ns,
        acquisition_started_monotonic_ns=acquisition_started_monotonic_ns,
    )
