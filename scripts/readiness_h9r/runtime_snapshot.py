"""Snapshot content-addressed del runtime confiable del arnés H9R.

Este módulo usa sólo stdlib. Materializa fuentes ya revalidadas por el supervisor y raíces
importables cerradas por RECORD; no ejecuta ningún workload ni importa el runtime candidato.
"""

from __future__ import annotations

import atexit
import base64
import csv
import ctypes
import hashlib
import io
import json
import os
import shutil
import stat
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Final

SCHEMA_VERSION: Final = "nikodym.readiness.h9r.harness-source-snapshot.v1"
PRODUCT_DISTRIBUTIONS: Final = {
    "cffi": (
        "2.0.0",
        "d3733a258254cb55c974b149428097a2d3f8b2947c1121cd32224e36219b584d",
        ("cffi", "_cffi_backend.cp312-win_amd64.pyd"),
    ),
    "cryptography": (
        "48.0.1",
        "c881c7c02476c61a6bb2195a355779608a083e69ac55c55a02377264d1e0be74",
        ("cryptography",),
    ),
    "pyarrow": (
        "24.0.0",
        "7b0759bc29bb677442b619a642542f6489491cd9389a1a9454be69c2a9e1c772",
        ("pyarrow", "pyarrow.libs"),
    ),
    "threadpoolctl": (
        "3.6.0",
        "21fd60a7b59ad0785db0d87b7f45a58b9c6961097749168c577efa5b1619e95e",
        ("threadpoolctl.py",),
    ),
}
EXPECTED_IMPORT_ROOTS: Final = frozenset(
    {"_cffi_backend", "cffi", "cryptography", "pyarrow", "threadpoolctl"}
)
_REPARSE_FLAG: Final = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
_WINDOWS_GENERIC_READ: Final = 0x80000000
_WINDOWS_FILE_SHARE_READ: Final = 0x00000001
_WINDOWS_OPEN_EXISTING: Final = 3
_WINDOWS_FILE_ATTRIBUTE_NORMAL: Final = 0x00000080
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000
_WINDOWS_READ_CONTROL: Final = 0x00020000
_WINDOWS_WRITE_DAC: Final = 0x00040000
_WINDOWS_TOKEN_QUERY: Final = 0x00000008
_WINDOWS_TOKEN_USER: Final = 1
_WINDOWS_ERROR_INSUFFICIENT_BUFFER: Final = 122
_WINDOWS_SE_FILE_OBJECT: Final = 1
_WINDOWS_DACL_SECURITY_INFORMATION: Final = 0x00000004
_WINDOWS_UNPROTECTED_DACL_SECURITY_INFORMATION: Final = 0x20000000
_WINDOWS_PROTECTED_DACL_SECURITY_INFORMATION: Final = 0x80000000
_WINDOWS_SE_DACL_AUTO_INHERITED: Final = 0x0400
_WINDOWS_SE_DACL_PROTECTED: Final = 0x1000
_WINDOWS_DENY_ACCESS: Final = 3
_WINDOWS_TRUSTEE_IS_SID: Final = 0
_WINDOWS_TRUSTEE_IS_USER: Final = 1
_WINDOWS_ACL_SIZE_INFORMATION: Final = 2
_WINDOWS_DIRECTORY_SEAL_ACCESS: Final = 0x00000002 | 0x00000004 | 0x00000040
_WINDOWS_KERNEL32: Any | None = None
_WINDOWS_ADVAPI32: Any | None = None


class RuntimeSnapshotError(RuntimeError):
    """El snapshot no puede considerarse inmutable ni content-addressed."""


class _WindowsSidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_uint32)]


class _WindowsTokenUser(ctypes.Structure):
    _fields_ = [("user", _WindowsSidAndAttributes)]


class _WindowsTrustee(ctypes.Structure):
    _fields_ = [
        ("multiple_trustee", ctypes.c_void_p),
        ("multiple_trustee_operation", ctypes.c_int),
        ("trustee_form", ctypes.c_int),
        ("trustee_type", ctypes.c_int),
        ("name", ctypes.c_void_p),
    ]


class _WindowsExplicitAccess(ctypes.Structure):
    _fields_ = [
        ("access_permissions", ctypes.c_uint32),
        ("access_mode", ctypes.c_int),
        ("inheritance", ctypes.c_uint32),
        ("trustee", _WindowsTrustee),
    ]


class _WindowsAclSizeInformation(ctypes.Structure):
    _fields_ = [
        ("ace_count", ctypes.c_uint32),
        ("acl_bytes_in_use", ctypes.c_uint32),
        ("acl_bytes_free", ctypes.c_uint32),
    ]


class _WindowsSecurityDescriptor(ctypes.Structure):
    _fields_ = [
        ("revision", ctypes.c_ubyte),
        ("sbz1", ctypes.c_ubyte),
        ("control", ctypes.c_uint16),
        ("owner", ctypes.c_void_p),
        ("group", ctypes.c_void_p),
        ("sacl", ctypes.c_void_p),
        ("dacl", ctypes.c_void_p),
    ]


class _WindowsAclSeal:
    """DACL original retenida para restauración exacta al liberar el lease."""

    def __init__(
        self,
        *,
        path: Path,
        handle: int,
        dacl: int,
        security_descriptor: int,
        sealed_dacl: int,
        dacl_fingerprint: bytes,
        descriptor_control: int,
    ) -> None:
        self.path = path
        self.handle = handle
        self.dacl = dacl
        self.security_descriptor = security_descriptor
        self.sealed_dacl = sealed_dacl
        self.dacl_fingerprint = dacl_fingerprint
        self.descriptor_control = descriptor_control

    def assert_restored(self) -> None:
        observed_control, observed_fingerprint = _windows_dacl_signature(self.handle)
        if (
            observed_control == self.descriptor_control
            and observed_fingerprint == self.dacl_fingerprint
        ):
            return
        expected_hash = hashlib.sha256(self.dacl_fingerprint).hexdigest()
        observed_hash = hashlib.sha256(observed_fingerprint).hexdigest()
        raise RuntimeSnapshotError(
            "DACL del snapshot no restauró exactamente: "
            f"{self.path}; control={self.descriptor_control:#06x}/"
            f"{observed_control:#06x}; sha256={expected_hash}/{observed_hash}"
        )

    def restore(self) -> None:
        if self.security_descriptor == 0:
            return
        advapi32 = _windows_advapi32()
        set_kernel_object_security: Any = advapi32.SetKernelObjectSecurity
        set_kernel_object_security.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        set_kernel_object_security.restype = ctypes.c_int
        restored = bool(
            set_kernel_object_security(
                ctypes.c_void_p(self.handle),
                _WINDOWS_DACL_SECURITY_INFORMATION,
                ctypes.c_void_p(self.security_descriptor),
            )
        )
        restore_error = ctypes.get_last_error()
        if not restored:
            raise RuntimeSnapshotError(
                f"no se pudo restaurar DACL del snapshot (winerror={restore_error})"
            )
        observed_control, observed_fingerprint = _windows_dacl_signature(self.handle)
        if (
            observed_control != self.descriptor_control
            or observed_fingerprint != self.dacl_fingerprint
        ) and self.descriptor_control & _WINDOWS_SE_DACL_AUTO_INHERITED:
            set_security_info: Any = advapi32.SetSecurityInfo
            set_security_info.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            set_security_info.restype = ctypes.c_uint32
            protection = (
                _WINDOWS_PROTECTED_DACL_SECURITY_INFORMATION
                if self.descriptor_control & _WINDOWS_SE_DACL_PROTECTED
                else _WINDOWS_UNPROTECTED_DACL_SECURITY_INFORMATION
            )
            status = int(
                set_security_info(
                    ctypes.c_void_p(self.handle),
                    _WINDOWS_SE_FILE_OBJECT,
                    _WINDOWS_DACL_SECURITY_INFORMATION | protection,
                    None,
                    None,
                    ctypes.c_void_p(self.dacl),
                    None,
                )
            )
            if status != 0:
                raise RuntimeSnapshotError(
                    f"no se pudo restaurar auto-herencia DACL del snapshot (winerror={status})"
                )
        self.assert_restored()

    def finalize(self) -> None:
        if self.security_descriptor != 0:
            _windows_local_free(self.security_descriptor)
            self.security_descriptor = 0
            self.dacl = 0
        if self.sealed_dacl != 0:
            _windows_local_free(self.sealed_dacl)
            self.sealed_dacl = 0


class _WindowsSnapshotLease:
    """Handles kernel retenidos que congelan identidades y bytes ya censados."""

    def __init__(
        self,
        *,
        key: tuple[str, str],
        files: tuple[Path, ...],
        directories: tuple[Path, ...],
        handles: list[int],
        acl_seals: list[_WindowsAclSeal],
    ) -> None:
        self.key = key
        self.files = files
        self.directories = directories
        self.handles = handles
        self.acl_seals = acl_seals
        self.state = "acquiring"

    def activate(self) -> None:
        if self.state != "acquiring":
            raise RuntimeSnapshotError(
                f"lease Windows no puede activarse desde estado {self.state!r}"
            )
        self.state = "active"

    def close(self) -> None:
        if self.state == "closed":
            return
        if self.state in {"acquiring", "active", "restoring"}:
            self.state = "restoring"
            seals = list(self.acl_seals)
            for seal in reversed(seals):
                seal.restore()
            for seal in seals:
                seal.assert_restored()
            self.state = "restored"
        elif self.state != "restored":
            raise RuntimeSnapshotError(f"estado inválido del lease Windows: {self.state!r}")
        for index in range(len(self.handles) - 1, -1, -1):
            _close_windows_handle(self.handles[index])
            del self.handles[index]
        for seal in self.acl_seals:
            seal.finalize()
        self.acl_seals.clear()
        self.state = "closed"


_WINDOWS_SNAPSHOT_LEASES: dict[tuple[str, str], _WindowsSnapshotLease] = {}


def _windows_kernel32() -> Any:
    global _WINDOWS_KERNEL32
    if sys.platform != "win32":
        raise RuntimeSnapshotError("kernel32 no está disponible fuera de Windows")
    if _WINDOWS_KERNEL32 is None:
        _WINDOWS_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _WINDOWS_KERNEL32


def _windows_advapi32() -> Any:
    global _WINDOWS_ADVAPI32
    if sys.platform != "win32":
        raise RuntimeSnapshotError("advapi32 no está disponible fuera de Windows")
    if _WINDOWS_ADVAPI32 is None:
        _WINDOWS_ADVAPI32 = ctypes.WinDLL("advapi32", use_last_error=True)
    return _WINDOWS_ADVAPI32


def _windows_local_free(pointer: int) -> None:
    if pointer == 0:
        return
    kernel32 = _windows_kernel32()
    local_free: Any = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    remaining = local_free(ctypes.c_void_p(pointer))
    if remaining not in {None, 0}:
        error = ctypes.get_last_error()
        raise RuntimeSnapshotError(
            f"no se pudo liberar memoria de seguridad Windows (winerror={error})"
        )


def _windows_dacl_fingerprint(dacl: int) -> bytes:
    if dacl == 0:
        raise RuntimeSnapshotError("snapshot Windows tiene DACL nula no sellable")
    advapi32 = _windows_advapi32()
    get_acl_information: Any = advapi32.GetAclInformation
    get_acl_information.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    get_acl_information.restype = ctypes.c_int
    information = _WindowsAclSizeInformation()
    ok = bool(
        get_acl_information(
            ctypes.c_void_p(dacl),
            ctypes.byref(information),
            ctypes.sizeof(information),
            _WINDOWS_ACL_SIZE_INFORMATION,
        )
    )
    if not ok:
        error = ctypes.get_last_error()
        raise RuntimeSnapshotError(f"no se pudo leer DACL del snapshot (winerror={error})")
    return ctypes.string_at(dacl, int(information.acl_bytes_in_use))


def _windows_dacl_state(handle: int) -> tuple[int, int, int, bytes]:
    """Devuelve DACL, descriptor dueño, control y bytes canónicos observados."""
    advapi32 = _windows_advapi32()
    get_security_info: Any = advapi32.GetSecurityInfo
    get_security_info.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security_info.restype = ctypes.c_uint32
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = int(
        get_security_info(
            ctypes.c_void_p(handle),
            _WINDOWS_SE_FILE_OBJECT,
            _WINDOWS_DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
    )
    descriptor_address = int(descriptor.value or 0)
    if status != 0 or descriptor_address == 0:
        if descriptor_address:
            _windows_local_free(descriptor_address)
        raise RuntimeSnapshotError(f"no se pudo obtener DACL del snapshot (winerror={status})")
    try:
        dacl_address = int(dacl.value or 0)
        if dacl_address == 0:
            raise RuntimeSnapshotError("snapshot Windows tiene DACL nula no sellable")
        get_descriptor_control: Any = advapi32.GetSecurityDescriptorControl
        get_descriptor_control.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        get_descriptor_control.restype = ctypes.c_int
        control = ctypes.c_uint16()
        revision = ctypes.c_uint32()
        ok = bool(
            get_descriptor_control(
                ctypes.c_void_p(descriptor_address),
                ctypes.byref(control),
                ctypes.byref(revision),
            )
        )
        if not ok:
            error = ctypes.get_last_error()
            raise RuntimeSnapshotError(
                f"no se pudo leer control del descriptor Windows (winerror={error})"
            )
        return (
            dacl_address,
            descriptor_address,
            int(control.value),
            _windows_dacl_fingerprint(dacl_address),
        )
    except BaseException:
        _windows_local_free(descriptor_address)
        raise


def _windows_dacl_signature(handle: int) -> tuple[int, bytes]:
    _, descriptor, control, fingerprint = _windows_dacl_state(handle)
    try:
        return control, fingerprint
    finally:
        _windows_local_free(descriptor)


def _windows_current_user_sid() -> tuple[Any, int]:
    """Retiene el buffer TOKEN_USER y devuelve el SID del proceso actual."""
    kernel32 = _windows_kernel32()
    advapi32 = _windows_advapi32()
    get_current_process: Any = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = ctypes.c_void_p
    open_process_token: Any = advapi32.OpenProcessToken
    open_process_token.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    open_process_token.restype = ctypes.c_int
    token = ctypes.c_void_p()
    if not bool(
        open_process_token(
            get_current_process(),
            _WINDOWS_TOKEN_QUERY,
            ctypes.byref(token),
        )
    ):
        error = ctypes.get_last_error()
        raise RuntimeSnapshotError(f"no se pudo abrir token Windows del proceso (winerror={error})")
    token_handle = int(token.value or 0)
    try:
        get_token_information: Any = advapi32.GetTokenInformation
        get_token_information.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        get_token_information.restype = ctypes.c_int
        required = ctypes.c_uint32()
        ctypes.set_last_error(0)
        first = bool(
            get_token_information(
                ctypes.c_void_p(token_handle),
                _WINDOWS_TOKEN_USER,
                None,
                0,
                ctypes.byref(required),
            )
        )
        first_error = ctypes.get_last_error()
        if first or first_error != _WINDOWS_ERROR_INSUFFICIENT_BUFFER or required.value == 0:
            raise RuntimeSnapshotError(
                f"no se pudo dimensionar TOKEN_USER Windows (winerror={first_error})"
            )
        buffer = ctypes.create_string_buffer(int(required.value))
        if not bool(
            get_token_information(
                ctypes.c_void_p(token_handle),
                _WINDOWS_TOKEN_USER,
                buffer,
                required,
                ctypes.byref(required),
            )
        ):
            error = ctypes.get_last_error()
            raise RuntimeSnapshotError(f"no se pudo leer TOKEN_USER Windows (winerror={error})")
        token_user = _WindowsTokenUser.from_buffer(buffer)
        sid = int(token_user.user.sid or 0)
        if sid == 0:
            raise RuntimeSnapshotError("TOKEN_USER Windows no contiene SID")
        return buffer, sid
    finally:
        _close_windows_handle(token_handle)


def _apply_windows_directory_seal(
    handle: int,
    *,
    path: Path,
    sid: int,
    seals: list[_WindowsAclSeal],
) -> _WindowsAclSeal:
    """Niega altas/bajas de hijos y conserva la DACL original para rollback exacto."""
    old_dacl, descriptor, control, fingerprint = _windows_dacl_state(handle)
    advapi32 = _windows_advapi32()
    set_entries: Any = advapi32.SetEntriesInAclW
    set_entries.argtypes = [
        ctypes.c_uint32,
        ctypes.POINTER(_WindowsExplicitAccess),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    set_entries.restype = ctypes.c_uint32
    trustee = _WindowsTrustee(
        None,
        0,
        _WINDOWS_TRUSTEE_IS_SID,
        _WINDOWS_TRUSTEE_IS_USER,
        ctypes.c_void_p(sid),
    )
    access = _WindowsExplicitAccess(
        _WINDOWS_DIRECTORY_SEAL_ACCESS,
        _WINDOWS_DENY_ACCESS,
        0,
        trustee,
    )
    new_dacl = ctypes.c_void_p()
    ownership_transferred = False
    try:
        status = int(
            set_entries(
                1,
                ctypes.byref(access),
                ctypes.c_void_p(old_dacl),
                ctypes.byref(new_dacl),
            )
        )
        if status != 0 or not new_dacl.value:
            raise RuntimeSnapshotError(
                f"no se pudo construir DACL sellada del snapshot (winerror={status})"
            )
        initialize_descriptor: Any = advapi32.InitializeSecurityDescriptor
        initialize_descriptor.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        initialize_descriptor.restype = ctypes.c_int
        set_descriptor_dacl: Any = advapi32.SetSecurityDescriptorDacl
        set_descriptor_dacl.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        set_descriptor_dacl.restype = ctypes.c_int
        set_kernel_object_security: Any = advapi32.SetKernelObjectSecurity
        set_kernel_object_security.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        set_kernel_object_security.restype = ctypes.c_int
        absolute_descriptor = _WindowsSecurityDescriptor()
        if not bool(initialize_descriptor(ctypes.byref(absolute_descriptor), 1)):
            error = ctypes.get_last_error()
            raise RuntimeSnapshotError(
                f"no se pudo inicializar descriptor sellado del snapshot (winerror={error})"
            )
        if not bool(
            set_descriptor_dacl(
                ctypes.byref(absolute_descriptor),
                1,
                new_dacl,
                0,
            )
        ):
            error = ctypes.get_last_error()
            raise RuntimeSnapshotError(
                f"no se pudo asociar DACL sellada del snapshot (winerror={error})"
            )
        seal = _WindowsAclSeal(
            path=path,
            handle=handle,
            dacl=old_dacl,
            security_descriptor=descriptor,
            sealed_dacl=int(new_dacl.value or 0),
            dacl_fingerprint=fingerprint,
            descriptor_control=control,
        )
        seals.append(seal)
        ownership_transferred = True
        descriptor = 0
        new_dacl.value = None
        if not bool(
            set_kernel_object_security(
                ctypes.c_void_p(handle),
                _WINDOWS_DACL_SECURITY_INFORMATION,
                ctypes.byref(absolute_descriptor),
            )
        ):
            error = ctypes.get_last_error()
            raise RuntimeSnapshotError(
                f"no se pudo aplicar DACL sellada del snapshot (winerror={error})"
            )
        return seal
    except BaseException:
        if not ownership_transferred:
            _windows_local_free(descriptor)
        raise
    finally:
        new_dacl_address = int(new_dacl.value or 0)
        if new_dacl_address:
            _windows_local_free(new_dacl_address)


def _seal_windows_snapshot_directories(
    handles_by_path: Mapping[Path, int],
    *,
    root: Path,
    directories: tuple[Path, ...],
    seals: list[_WindowsAclSeal],
) -> None:
    """Sella sólo dirs harness-owned; nunca el checkout vivo ni telemetría."""
    snapshot_root = Path(os.path.abspath(root))
    targets = tuple(
        directory
        for directory in directories
        if directory == snapshot_root or directory.is_relative_to(snapshot_root)
    )
    if snapshot_root not in targets:
        raise RuntimeSnapshotError("censo Windows no contiene root del snapshot a sellar")
    sid_buffer, sid = _windows_current_user_sid()
    try:
        for directory in targets:
            handle = handles_by_path.get(directory)
            if handle is None:
                raise RuntimeSnapshotError(
                    f"falta handle Windows del directorio a sellar: {directory}"
                )
            _apply_windows_directory_seal(
                handle,
                path=directory,
                sid=sid,
                seals=seals,
            )
    finally:
        del sid_buffer


def _close_windows_handle(handle: int) -> None:
    if sys.platform != "win32":
        return
    kernel32 = _windows_kernel32()
    close_handle: Any = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    if not bool(close_handle(ctypes.c_void_p(handle))):
        error = ctypes.get_last_error()
        raise RuntimeSnapshotError(f"no se pudo cerrar handle del snapshot (winerror={error})")


def _release_snapshot_leases_for_tests() -> None:
    """Libera leases; un fallo conserva registry, handles y DACL para retry."""
    for key, lease in reversed(list(_WINDOWS_SNAPSHOT_LEASES.items())):
        lease.close()
        if _WINDOWS_SNAPSHOT_LEASES.get(key) is lease:
            del _WINDOWS_SNAPSHOT_LEASES[key]


atexit.register(_release_snapshot_leases_for_tests)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    _, payload, _ = _read_bound_bytes(path, context="archivo para SHA-256")
    return _sha256_bytes(payload)


def _validate_sha256(value: object, *, context: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeSnapshotError(f"{context} no es SHA-256 canónico")
    return value


def _reject_reparse_ancestors(path: Path, *, context: str, require_leaf: bool = True) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    parts = absolute.parts[1:] if require_leaf else absolute.parts[1:-1]
    for part in parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            raise RuntimeSnapshotError(f"{context}: ruta o ancestro ausente") from exc
        attributes = int(getattr(info, "st_file_attributes", 0))
        if current.is_symlink() or bool(attributes & _REPARSE_FLAG):
            raise RuntimeSnapshotError(f"{context}: ruta o ancestro es symlink/reparse point")


def _safe_file(path: Path, *, context: str, require_single_link: bool = True) -> Path:
    _reject_reparse_ancestors(path, context=context)
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or attributes & _REPARSE_FLAG:
        raise RuntimeSnapshotError(f"{context}: no es archivo regular plano")
    if require_single_link and int(getattr(info, "st_nlink", 1)) != 1:
        raise RuntimeSnapshotError(f"{context}: hardlink no permitido")
    return Path(os.path.abspath(path))


def _same_file_version(left: os.stat_result, right: os.stat_result) -> bool:
    return bool(
        os.path.samestat(left, right)
        and int(left.st_size) == int(right.st_size)
        and int(getattr(left, "st_mtime_ns", 0)) == int(getattr(right, "st_mtime_ns", 0))
    )


def _assert_bound_file_version(
    path: Path,
    expected: os.stat_result,
    *,
    context: str,
    require_single_link: bool = True,
) -> None:
    candidate = _safe_file(
        path,
        context=context,
        require_single_link=require_single_link,
    )
    observed = candidate.lstat()
    if not _same_file_version(expected, observed):
        raise RuntimeSnapshotError(f"{context}: el archivo cambió de versión")


def _read_bound_bytes(
    path: Path,
    *,
    context: str,
    require_single_link: bool = True,
) -> tuple[Path, bytes, os.stat_result]:
    candidate = _safe_file(
        path,
        context=context,
        require_single_link=require_single_link,
    )
    before = candidate.lstat()
    with candidate.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not _same_file_version(before, opened):
            raise RuntimeSnapshotError(f"{context}: el archivo cambió antes de la lectura")
        payload = handle.read()
        after_read = os.fstat(handle.fileno())
        if not _same_file_version(opened, after_read) or len(payload) != int(after_read.st_size):
            raise RuntimeSnapshotError(f"{context}: el archivo cambió durante la lectura")
    _assert_bound_file_version(
        candidate,
        before,
        context=f"{context}: lectura final",
        require_single_link=require_single_link,
    )
    return candidate, payload, before


def _safe_directory(path: Path, *, context: str) -> Path:
    _reject_reparse_ancestors(path, context=context)
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or attributes & _REPARSE_FLAG:
        raise RuntimeSnapshotError(f"{context}: no es directorio plano")
    return Path(os.path.abspath(path))


def _closed_child_directories(path: Path, *, context: str) -> set[str]:
    parent = _safe_directory(path, context=context)
    names: set[str] = set()
    with os.scandir(parent) as entries:
        for entry in entries:
            metadata = entry.stat(follow_symlinks=False)
            attributes = int(getattr(metadata, "st_file_attributes", 0))
            if (
                entry.is_symlink()
                or bool(attributes & _REPARSE_FLAG)
                or not entry.is_dir(follow_symlinks=False)
            ):
                raise RuntimeSnapshotError(f"{context}: contiene entrada no-directorio/reparse")
            if entry.name in names:
                raise RuntimeSnapshotError(f"{context}: contiene nombre duplicado")
            names.add(entry.name)
    return names


def _assert_closed_scripts_directory(path: Path, *, context: str) -> None:
    scripts_root = _safe_directory(path, context=context)
    expected = {
        "__init__.py": "file",
        "measure_readiness_h9r.py": "file",
        "readiness_h9r": "directory",
    }
    observed: dict[str, str] = {}
    with os.scandir(scripts_root) as entries:
        for entry in entries:
            metadata = entry.stat(follow_symlinks=False)
            attributes = int(getattr(metadata, "st_file_attributes", 0))
            if entry.is_symlink() or bool(attributes & _REPARSE_FLAG):
                raise RuntimeSnapshotError(f"{context}: contiene symlink/reparse point")
            if entry.is_file(follow_symlinks=False):
                kind = "file"
            elif entry.is_dir(follow_symlinks=False):
                kind = "directory"
            else:
                raise RuntimeSnapshotError(f"{context}: contiene entrada no regular")
            if entry.name in observed:
                raise RuntimeSnapshotError(f"{context}: contiene nombre duplicado")
            observed[entry.name] = kind
    if observed != expected:
        raise RuntimeSnapshotError(f"{context}: contiene entradas extra/faltantes")


def _assert_closed_snapshot_root(path: Path, *, context: str) -> None:
    root = _safe_directory(path, context=context)
    expected = {"scripts", "import-roots"}
    observed = _closed_child_directories(root, context=context)
    if observed != expected:
        raise RuntimeSnapshotError(f"{context}: contiene entradas extra/faltantes")


def _tree_directories(root: Path) -> list[Path]:
    root = _safe_directory(root, context="contenedor importable")
    directories = [root]
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                attributes = int(getattr(metadata, "st_file_attributes", 0))
                if entry.name == "__pycache__" and entry.is_dir(follow_symlinks=False):
                    raise RuntimeSnapshotError("root importable contiene __pycache__ no firmado")
                if entry.is_symlink() or bool(attributes & _REPARSE_FLAG):
                    raise RuntimeSnapshotError("root importable contiene symlink/reparse point")
                if entry.is_dir(follow_symlinks=False):
                    child = _safe_directory(Path(entry.path), context="directorio importable")
                    directories.append(child)
                    stack.append(child)
                elif entry.is_file(follow_symlinks=False):
                    _safe_file(Path(entry.path), context="payload importable")
                else:
                    raise RuntimeSnapshotError("root importable contiene entrada no regular")
    return sorted(directories, key=lambda item: str(item).casefold())


def _snapshot_lease_census(
    *,
    manifest_path: Path,
    root: Path,
    import_root_names: set[str],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Censa exactamente todo lo que debe quedar estable durante la aceptación."""
    _assert_closed_snapshot_root(root, context="root del snapshot")
    scripts_root = root / "scripts"
    _assert_closed_scripts_directory(
        scripts_root,
        context="directorio scripts del snapshot",
    )
    package_root = _safe_directory(
        scripts_root / "readiness_h9r",
        context="paquete H9R del snapshot",
    )
    source_files = _source_files(root, allow_pycache=False)
    import_root_parent = _safe_directory(
        root / "import-roots",
        context="contenedor import-roots del snapshot",
    )
    if (
        _closed_child_directories(
            import_root_parent,
            context="contenedor import-roots del snapshot",
        )
        != import_root_names
    ):
        raise RuntimeSnapshotError("contenedor import-roots tiene roots extra/faltantes")
    import_files: list[Path] = []
    import_directories: list[Path] = []
    for name in sorted(import_root_names):
        container = _safe_directory(
            import_root_parent / name,
            context=f"import root {name}",
        )
        import_files.extend(_walk_files(container, relative_to=container))
        import_directories.extend(_tree_directories(container))
    files = tuple(
        sorted(
            {Path(os.path.abspath(manifest_path)), *source_files, *import_files},
            key=lambda item: str(item).casefold(),
        )
    )
    directories = tuple(
        sorted(
            {
                _safe_directory(root, context="root del snapshot"),
                _safe_directory(scripts_root, context="scripts del snapshot"),
                package_root,
                import_root_parent,
                *import_directories,
            },
            key=lambda item: str(item).casefold(),
        )
    )
    return files, directories


def _open_windows_read_lease(
    path: Path,
    *,
    directory: bool,
    context: str,
    handles: list[int],
) -> int:
    """Abre el leaf sin seguir reparse points y niega WRITE/DELETE a otros opens."""
    if sys.platform != "win32":
        raise RuntimeSnapshotError(f"{context}: lease Windows solicitado fuera de Windows")
    absolute = (
        _safe_directory(path, context=context) if directory else _safe_file(path, context=context)
    )
    before = absolute.lstat()
    kernel32 = _windows_kernel32()
    create_file: Any = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    flags = _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT | _WINDOWS_FILE_ATTRIBUTE_NORMAL
    if directory:
        flags |= _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
    desired_access = _WINDOWS_GENERIC_READ
    if directory:
        desired_access |= _WINDOWS_READ_CONTROL | _WINDOWS_WRITE_DAC
    raw_handle = create_file(
        str(absolute),
        desired_access,
        _WINDOWS_FILE_SHARE_READ,
        None,
        _WINDOWS_OPEN_EXISTING,
        flags,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if raw_handle in {None, invalid_handle}:
        error = ctypes.get_last_error()
        raise RuntimeSnapshotError(
            f"{context}: no se pudo adquirir lease Windows de sólo lectura (winerror={error})"
        )
    handle = int(raw_handle)
    handles.append(handle)
    after_path = (
        _safe_directory(absolute, context=f"{context}: post-lease")
        if directory
        else _safe_file(absolute, context=f"{context}: post-lease")
    )
    after = after_path.lstat()
    stable = os.path.samestat(before, after) if directory else _same_file_version(before, after)
    if not stable:
        raise RuntimeSnapshotError(f"{context}: cambió al adquirir el lease Windows")
    return handle


def _acquire_windows_snapshot_lease(
    *,
    manifest_path: Path,
    root: Path,
    files: tuple[Path, ...],
    directories: tuple[Path, ...],
) -> tuple[_WindowsSnapshotLease | None, bool]:
    if sys.platform != "win32":
        return None, False
    key = (
        os.path.normcase(str(Path(os.path.abspath(manifest_path)))),
        os.path.normcase(str(Path(os.path.abspath(root)))),
    )
    candidate = _WindowsSnapshotLease(
        key=key,
        files=files,
        directories=directories,
        handles=[],
        acl_seals=[],
    )
    lease = _WINDOWS_SNAPSHOT_LEASES.setdefault(key, candidate)
    if lease is not candidate:
        if lease.state != "active":
            raise RuntimeSnapshotError(
                f"lease Windows tiene cleanup pendiente en estado {lease.state!r}"
            )
        if lease.files != files or lease.directories != directories:
            raise RuntimeSnapshotError("censo del snapshot difiere del lease Windows retenido")
        return lease, False
    directory_handles: dict[Path, int] = {}
    try:
        for directory in directories:
            handle = _open_windows_read_lease(
                directory,
                directory=True,
                context=f"directorio bajo lease {directory}",
                handles=lease.handles,
            )
            directory_handles[directory] = handle
        for file_path in files:
            _open_windows_read_lease(
                file_path,
                directory=False,
                context=f"archivo bajo lease {file_path}",
                handles=lease.handles,
            )
        _seal_windows_snapshot_directories(
            directory_handles,
            root=root,
            directories=directories,
            seals=lease.acl_seals,
        )
    except BaseException:
        try:
            lease.close()
        except BaseException as rollback_error:
            raise RuntimeSnapshotError(
                "falló el rollback al adquirir el lease Windows; estado retenido para retry"
            ) from rollback_error
        if _WINDOWS_SNAPSHOT_LEASES.get(key) is lease:
            del _WINDOWS_SNAPSHOT_LEASES[key]
        raise
    return lease, True


def _commit_windows_snapshot_lease(lease: _WindowsSnapshotLease | None, *, fresh: bool) -> None:
    if lease is None or not fresh:
        return
    if _WINDOWS_SNAPSHOT_LEASES.get(lease.key) is not lease:
        raise RuntimeSnapshotError("reserva del lease Windows cambió antes del commit")
    lease.activate()


def _rollback_windows_snapshot_lease(lease: _WindowsSnapshotLease) -> None:
    """Cierra una reserva fresca; un fallo la deja alcanzable para retry."""
    lease.close()
    if _WINDOWS_SNAPSHOT_LEASES.get(lease.key) is lease:
        del _WINDOWS_SNAPSHOT_LEASES[lease.key]


def _plain_directory_identity(
    path: Path, *, context: str, create_missing: bool
) -> tuple[Path, int, int]:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    metadata = current.lstat()
    for part in (None, *absolute.parts[1:]):
        if part is not None:
            current /= part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                if not create_missing:
                    raise RuntimeSnapshotError(
                        f"{context}: directorio o ancestro ausente: {current}"
                    ) from None
                try:
                    current.mkdir(parents=False, exist_ok=False)
                except FileExistsError as exc:
                    raise RuntimeSnapshotError(
                        f"{context}: carrera al crear directorio: {current}"
                    ) from exc
                metadata = current.lstat()
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if not stat.S_ISDIR(metadata.st_mode) or current.is_symlink() or attributes & _REPARSE_FLAG:
            raise RuntimeSnapshotError(
                f"{context}: directorio o ancestro redirigido/no regular: {current}"
            )
    return absolute, int(metadata.st_dev), int(metadata.st_ino)


def _assert_same_plain_directory(identity: tuple[Path, int, int], *, context: str) -> None:
    observed = _plain_directory_identity(
        identity[0],
        context=context,
        create_missing=False,
    )
    if observed[1:] != identity[1:]:
        raise RuntimeSnapshotError(f"{context}: el directorio cambió de identidad")


def _require_absent_leaf(path: Path, *, context: str) -> None:
    if os.path.lexists(Path(os.path.abspath(path))):
        raise RuntimeSnapshotError(f"{context}: destino ya existe")


def _source_files(source_root: Path, *, allow_pycache: bool) -> list[Path]:
    scripts_root = _safe_directory(source_root / "scripts", context="scripts fuente")
    package = _safe_directory(scripts_root / "readiness_h9r", context="paquete H9R fuente")
    files = [scripts_root / "__init__.py", scripts_root / "measure_readiness_h9r.py"]
    with os.scandir(package) as entries:
        for entry in entries:
            if entry.name == "__pycache__" and entry.is_dir(follow_symlinks=False):
                if allow_pycache:
                    continue
                raise RuntimeSnapshotError("snapshot H9R contiene __pycache__ no firmado")
            if (
                entry.is_symlink()
                or not entry.is_file(follow_symlinks=False)
                or not entry.name.endswith(".py")
            ):
                raise RuntimeSnapshotError(
                    f"paquete H9R fuente contiene entrada no catalogada: {entry.name}"
                )
            files.append(Path(entry.path))
    return sorted(files, key=lambda path: path.relative_to(source_root).as_posix())


def _assert_inventory_snapshot(
    observed_paths: list[Path],
    expected_paths: list[Path],
    versions: Mapping[Path, os.stat_result],
    *,
    context: str,
) -> None:
    if observed_paths != expected_paths:
        raise RuntimeSnapshotError(f"{context}: el censo de archivos cambió")
    for path in observed_paths:
        identity = versions.get(path)
        if identity is None:
            raise RuntimeSnapshotError(f"{context}: falta versión atestiguada para {path}")
        _assert_bound_file_version(path, identity, context=f"{context}: {path}")


def _source_inventory_snapshot(
    source_root: Path,
    *,
    allow_pycache: bool = False,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Path],
    list[Path],
    dict[Path, os.stat_result],
]:
    inventory: list[dict[str, Any]] = []
    sources: dict[str, Path] = {}
    versions: dict[Path, os.stat_result] = {}
    paths = _source_files(source_root, allow_pycache=allow_pycache)
    for source in paths:
        source, payload, identity = _read_bound_bytes(source, context="fuente H9R")
        relative = source.relative_to(source_root).as_posix()
        sources[relative] = source
        versions[source] = identity
        inventory.append(
            {
                "relative_path": relative,
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
        )
    _assert_inventory_snapshot(
        _source_files(source_root, allow_pycache=allow_pycache),
        paths,
        versions,
        context="inventario de fuentes H9R al cierre",
    )
    return inventory, sources, paths, versions


def _source_inventory(
    source_root: Path,
    *,
    allow_pycache: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    inventory, sources, _, _ = _source_inventory_snapshot(
        source_root,
        allow_pycache=allow_pycache,
    )
    return inventory, sources


def _record_entries(
    *, site_root: Path, distribution: str, version: str, expected_record_sha256: str
) -> dict[str, tuple[bytes | None, int | None]]:
    record, record_payload, record_identity = _read_bound_bytes(
        site_root / f"{distribution}-{version}.dist-info" / "RECORD",
        context=f"RECORD de {distribution}",
    )
    if _sha256_bytes(record_payload) != expected_record_sha256:
        raise RuntimeSnapshotError(f"RECORD de {distribution} cambió")
    seen: dict[str, tuple[bytes | None, int | None]] = {}
    try:
        rows = csv.reader(io.StringIO(record_payload.decode("utf-8"), newline=""))
        for row in rows:
            if len(row) != 3 or not row[0] or row[0] in seen:
                raise RuntimeSnapshotError(f"RECORD de {distribution} no es cerrado/único")
            relative = PurePosixPath(row[0])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeSnapshotError(f"RECORD de {distribution} escapa site-packages")
            candidate, candidate_payload, candidate_identity = _read_bound_bytes(
                site_root.joinpath(*relative.parts),
                context=f"{distribution}:{row[0]}",
                # uv puede instalar payloads wheel mediante hardlinks. Sólo se aceptan aquí:
                # quedan ligados byte/tamaño a RECORD y se copian a un root nuevo single-link.
                require_single_link=False,
            )
            if candidate == record:
                if row[1] or row[2]:
                    raise RuntimeSnapshotError(f"RECORD de {distribution} autofirma RECORD")
                seen[row[0]] = (None, None)
                continue
            if not row[1].startswith("sha256=") or not row[2].isdigit():
                raise RuntimeSnapshotError(f"RECORD de {distribution} omite hash/tamaño")
            observed_digest = hashlib.sha256(candidate_payload).digest()
            expected_digest = base64.urlsafe_b64decode(row[1][7:] + "==")
            if observed_digest != expected_digest or len(candidate_payload) != int(row[2]):
                raise RuntimeSnapshotError(f"RECORD de {distribution} no reconcilia {row[0]}")
            _assert_bound_file_version(
                candidate,
                candidate_identity,
                context=f"{distribution}:{row[0]} final",
                require_single_link=False,
            )
            seen[row[0]] = (expected_digest, int(row[2]))
    except UnicodeDecodeError as exc:
        raise RuntimeSnapshotError(f"RECORD de {distribution} no es UTF-8") from exc
    _assert_bound_file_version(record, record_identity, context=f"RECORD de {distribution} final")
    return seen


def _walk_files(
    root: Path,
    *,
    relative_to: Path,
    require_single_link: bool = True,
    allow_pycache: bool = False,
) -> list[Path]:
    _safe_directory(root, context="root importable")
    files: list[Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.name == "__pycache__" and entry.is_dir(follow_symlinks=False):
                    if allow_pycache:
                        continue
                    raise RuntimeSnapshotError("root importable contiene __pycache__ no firmado")
                attributes = int(
                    getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                )
                if entry.is_symlink() or attributes & _REPARSE_FLAG:
                    raise RuntimeSnapshotError("root importable contiene symlink/reparse point")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    _safe_file(
                        path,
                        context="payload importable",
                        require_single_link=require_single_link,
                    )
                    files.append(path)
                else:
                    raise RuntimeSnapshotError("root importable contiene entrada no regular")
    return sorted(files, key=lambda path: path.relative_to(relative_to).as_posix())


def _selected_entries(*, site_root: Path, root_name: str) -> set[str]:
    root = site_root / root_name
    if root.is_file():
        _safe_file(
            root,
            context=f"import root {root_name}",
            require_single_link=False,
        )
        return {root_name}
    return {
        path.relative_to(site_root).as_posix()
        for path in _walk_files(
            root,
            relative_to=site_root,
            require_single_link=False,
            allow_pycache=True,
        )
    }


def _copy_file_exclusive(
    source: Path,
    destination: Path,
    *,
    require_source_single_link: bool = True,
) -> None:
    source = _safe_file(
        source,
        context="payload fuente del snapshot",
        require_single_link=require_source_single_link,
    )
    parent_identity = _plain_directory_identity(
        destination.parent,
        context="parent de payload copiado",
        create_missing=True,
    )
    destination = Path(os.path.abspath(destination))
    _require_absent_leaf(destination, context="payload copiado")
    source_identity = source.lstat()
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        if not os.path.samestat(source_identity, os.fstat(input_handle.fileno())):
            raise RuntimeSnapshotError("payload fuente cambió antes de copiar")
        destination_identity = os.fstat(output_handle.fileno())
        if int(getattr(destination_identity, "st_nlink", 1)) != 1:
            raise RuntimeSnapshotError("payload copiado nació con hardlinks")
        shutil.copyfileobj(input_handle, output_handle, 1024 * 1024)
        output_handle.flush()
        os.fsync(output_handle.fileno())
        if not os.path.samestat(source_identity, os.fstat(input_handle.fileno())):
            raise RuntimeSnapshotError("payload fuente cambió durante la copia")
        if not os.path.samestat(destination_identity, os.fstat(output_handle.fileno())):
            raise RuntimeSnapshotError("payload destino cambió durante la copia")
    _assert_same_plain_directory(parent_identity, context="parent de payload copiado")
    copied = _safe_file(destination, context="payload copiado")
    if not os.path.samestat(destination_identity, copied.lstat()):
        raise RuntimeSnapshotError("payload copiado cambió de identidad")


def _copy_root(source: Path, destination: Path) -> None:
    if source.is_file():
        _copy_file_exclusive(source, destination, require_source_single_link=False)
        return
    _safe_directory(source, context="import root fuente")
    _plain_directory_identity(
        destination,
        context="import root copiado",
        create_missing=True,
    )
    for source_file in _walk_files(
        source,
        relative_to=source,
        require_single_link=False,
        allow_pycache=True,
    ):
        _copy_file_exclusive(
            source_file,
            destination / source_file.relative_to(source),
            require_source_single_link=False,
        )


def _assert_copied_root_matches_record(
    *,
    container: Path,
    original_root_name: str,
    record_entries: Mapping[str, tuple[bytes | None, int | None]],
) -> None:
    target = container / original_root_name
    copied_files = (
        [_safe_file(target, context="payload copiado")]
        if target.is_file()
        else _walk_files(target, relative_to=container)
    )
    observed_entries = {copied.relative_to(container).as_posix() for copied in copied_files}
    prefix = f"{original_root_name.rstrip('/')}/"
    expected_entries = {
        relative
        for relative, identity in record_entries.items()
        if (relative == original_root_name or relative.startswith(prefix))
        and identity[0] is not None
        and identity[1] is not None
    }
    if observed_entries != expected_entries:
        raise RuntimeSnapshotError(
            f"payload copiado no reconcilia censo RECORD; "
            f"missing={sorted(expected_entries - observed_entries)!r}; "
            f"extra={sorted(observed_entries - expected_entries)!r}"
        )
    for copied in copied_files:
        relative = copied.relative_to(container).as_posix()
        if (
            not relative.startswith(f"{original_root_name.rstrip('/')}/")
            and relative != original_root_name
        ):
            raise RuntimeSnapshotError("payload copiado no deriva del root importable")
        expected = record_entries.get(relative)
        if expected is None or expected[0] is None or expected[1] is None:
            raise RuntimeSnapshotError(f"payload copiado no figura firmado en RECORD: {relative}")
        copied, payload, identity = _read_bound_bytes(copied, context="payload copiado RECORD")
        if hashlib.sha256(payload).digest() != expected[0] or len(payload) != expected[1]:
            raise RuntimeSnapshotError(f"payload copiado no reconcilia RECORD: {relative}")
        _assert_bound_file_version(copied, identity, context="payload copiado RECORD final")


def _tree_identity_snapshot(
    container: Path,
) -> tuple[dict[str, Any], list[Path], dict[Path, os.stat_result]]:
    files: list[dict[str, Any]] = []
    versions: dict[Path, os.stat_result] = {}
    paths = _walk_files(container, relative_to=container)
    for path in paths:
        path, payload, file_identity = _read_bound_bytes(path, context="payload de tree identity")
        versions[path] = file_identity
        files.append(
            {
                "relative_path": path.relative_to(container).as_posix(),
                "logical_bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
        )
    tree_identity: dict[str, Any] = {
        "files": len(files),
        "logical_bytes": sum(int(item["logical_bytes"]) for item in files),
        "tree_sha256": _sha256_bytes(_canonical_json(files)),
    }
    _assert_inventory_snapshot(
        _walk_files(container, relative_to=container),
        paths,
        versions,
        context=f"tree identity al cierre {container}",
    )
    return tree_identity, paths, versions


def _tree_identity(container: Path) -> dict[str, Any]:
    identity, _, _ = _tree_identity_snapshot(container)
    return identity


def _manifest_identity(manifest_path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _canonical_json(value) + b"\n"
    return {
        "path": str(manifest_path),
        "bytes": len(payload),
        "sha256": _sha256_bytes(payload),
        "value": dict(value),
    }


def materialize_harness_source_snapshot(
    *,
    destination_root: Path,
    manifest_path: Path,
    source_tooling_manifest_sha256: str,
    include_product_runtime: bool = True,
) -> dict[str, Any]:
    """Materializa fuentes/imports bajo roots nuevos y publica el manifiesto por O_EXCL."""
    source_tooling_manifest_sha256 = _validate_sha256(
        source_tooling_manifest_sha256, context="source_tooling_manifest_sha256"
    )
    destination_root = Path(os.path.abspath(destination_root))
    manifest_path = Path(os.path.abspath(manifest_path))
    try:
        destination_parent = _plain_directory_identity(
            destination_root.parent,
            context="parent de snapshot",
            create_missing=False,
        )
        manifest_parent = _plain_directory_identity(
            manifest_path.parent,
            context="parent del manifest snapshot",
            create_missing=False,
        )
    except RuntimeSnapshotError as exc:
        raise RuntimeSnapshotError(
            "parents de snapshot y manifest deben existir antes de reservar"
        ) from exc
    _require_absent_leaf(destination_root, context="destino de snapshot")
    _require_absent_leaf(manifest_path, context="manifest de snapshot")
    source_root = _safe_directory(
        Path(__file__).parents[2],
        context="checkout fuente del snapshot",
    )
    source_inventory, source_files = _source_inventory(source_root, allow_pycache=True)
    destination_root.mkdir(parents=False, exist_ok=False)
    _assert_same_plain_directory(destination_parent, context="parent de snapshot reservado")
    destination_identity = _plain_directory_identity(
        destination_root,
        context="destino de snapshot reservado",
        create_missing=False,
    )
    for relative, source in source_files.items():
        _copy_file_exclusive(source, destination_root / PurePosixPath(relative))
    import_root_directory = destination_root / "import-roots"
    _plain_directory_identity(
        import_root_directory,
        context="contenedor de import roots",
        create_missing=True,
    )
    import_roots: list[dict[str, Any]] = []
    if include_product_runtime:
        if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
            raise RuntimeSnapshotError(
                "el runtime firmado del arnés H9R exige Windows/CPython 3.12"
            )
        harness_python = _safe_file(Path(sys.executable), context="Python del arnés")
        site_root = _safe_directory(
            harness_python.parent.parent / "Lib" / "site-packages",
            context="site-packages del arnés",
        )
        for distribution, (version, record_sha256, roots) in sorted(PRODUCT_DISTRIBUTIONS.items()):
            record_entries = _record_entries(
                site_root=site_root,
                distribution=distribution,
                version=version,
                expected_record_sha256=record_sha256,
            )
            containers: dict[str, tuple[Path, list[str]]] = {}
            for root_name in roots:
                observed = _selected_entries(site_root=site_root, root_name=root_name)
                prefix = f"{root_name.rstrip('/')}/"
                expected = {
                    entry
                    for entry in record_entries
                    if entry == root_name or entry.startswith(prefix)
                }
                if observed != expected:
                    raise RuntimeSnapshotError(f"import root {root_name} no reconcilia RECORD")
                logical_name = (
                    "_cffi_backend"
                    if root_name.startswith("_cffi_backend.")
                    else "pyarrow"
                    if root_name == "pyarrow.libs"
                    else Path(root_name).stem
                    if (site_root / root_name).is_file()
                    else root_name
                )
                container, copied_names = containers.setdefault(
                    logical_name, (import_root_directory / logical_name, [])
                )
                _plain_directory_identity(
                    container,
                    context=f"contenedor importable {logical_name}",
                    create_missing=True,
                )
                _copy_root(site_root / root_name, container / root_name)
                copied_names.append(root_name)
            for logical_name, (container, copied_names) in sorted(containers.items()):
                for root_name in copied_names:
                    _assert_copied_root_matches_record(
                        container=container,
                        original_root_name=root_name,
                        record_entries=record_entries,
                    )
                import_roots.append(
                    {
                        "name": logical_name,
                        "kind": "import_parent",
                        "path": str(container),
                        **_tree_identity(container),
                    }
                )
    import_roots.sort(key=lambda item: str(item["name"]))
    observed_sources, _ = _source_inventory(destination_root, allow_pycache=False)
    if observed_sources != source_inventory:
        raise RuntimeSnapshotError("fuentes copiadas no reconcilian el snapshot")
    final_source_inventory, _ = _source_inventory(source_root, allow_pycache=True)
    if final_source_inventory != source_inventory:
        raise RuntimeSnapshotError("fuentes H9R cambiaron mientras se materializaba el snapshot")
    core = {
        "schema_version": SCHEMA_VERSION,
        "root": str(destination_root),
        "files": source_inventory,
        "count": len(source_inventory),
        "import_roots": import_roots,
        "source_tooling_manifest_sha256": source_tooling_manifest_sha256,
    }
    value = {**core, "manifest_sha256": _sha256_bytes(_canonical_json(core))}
    payload = _canonical_json(value) + b"\n"
    _assert_same_plain_directory(destination_identity, context="snapshot antes del manifest")
    _assert_same_plain_directory(manifest_parent, context="parent del manifest snapshot")
    _require_absent_leaf(manifest_path, context="manifest de snapshot")
    with manifest_path.open("xb") as handle:
        manifest_identity = os.fstat(handle.fileno())
        if int(getattr(manifest_identity, "st_nlink", 1)) != 1:
            raise RuntimeSnapshotError("manifest de snapshot nació con hardlinks")
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        if not os.path.samestat(manifest_identity, os.fstat(handle.fileno())):
            raise RuntimeSnapshotError("manifest de snapshot cambió durante la escritura")
    _assert_same_plain_directory(manifest_parent, context="parent del manifest publicado")
    published_manifest = _safe_file(manifest_path, context="manifest de snapshot publicado")
    if not os.path.samestat(manifest_identity, published_manifest.lstat()):
        raise RuntimeSnapshotError("manifest de snapshot cambió de identidad")
    identity = _manifest_identity(manifest_path, value)
    return validate_harness_source_snapshot(
        manifest_path=manifest_path,
        expected_manifest_sha256=identity["sha256"],
        expected_source_tooling_manifest_sha256=source_tooling_manifest_sha256,
    )


def validate_harness_source_snapshot(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    expected_source_tooling_manifest_sha256: str,
) -> dict[str, Any]:
    """Valida y, en Windows, retiene un lease kernel hasta el fin del proceso.

    El cutoff común nace después de abrir manifest, fuentes, payloads importables y directorios
    con ``OPEN_REPARSE_POINT`` y share READ, y de negar temporalmente altas/bajas en todos los
    directorios harness-owned. En otros sistemas se conserva el cierre exacto, sin afirmar la
    inmutabilidad posterior que un descriptor POSIX no impone.
    """
    expected_manifest_sha256 = _validate_sha256(
        expected_manifest_sha256, context="expected_manifest_sha256"
    )
    expected_source_tooling_manifest_sha256 = _validate_sha256(
        expected_source_tooling_manifest_sha256,
        context="expected_source_tooling_manifest_sha256",
    )
    manifest_path, manifest_bytes, _ = _read_bound_bytes(
        manifest_path,
        context="manifest del snapshot",
    )
    if _sha256_bytes(manifest_bytes) != expected_manifest_sha256:
        raise RuntimeSnapshotError("SHA-256 externo del manifest no reconcilia")
    try:
        parsed: Any = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSnapshotError("manifest del snapshot no es JSON UTF-8") from exc
    if not isinstance(parsed, dict) or manifest_bytes != _canonical_json(parsed) + b"\n":
        raise RuntimeSnapshotError("manifest del snapshot no es JSON canónico exacto")
    value = dict(parsed)
    if set(value) != {
        "schema_version",
        "root",
        "files",
        "count",
        "import_roots",
        "source_tooling_manifest_sha256",
        "manifest_sha256",
    }:
        raise RuntimeSnapshotError("manifest del snapshot no es cerrado")
    if value["schema_version"] != SCHEMA_VERSION:
        raise RuntimeSnapshotError("schema_version del snapshot no coincide")
    if value["source_tooling_manifest_sha256"] != expected_source_tooling_manifest_sha256:
        raise RuntimeSnapshotError("snapshot no liga el tooling esperado")
    core = {name: item for name, item in value.items() if name != "manifest_sha256"}
    if value["manifest_sha256"] != _sha256_bytes(_canonical_json(core)):
        raise RuntimeSnapshotError("manifest_sha256 interno no reconcilia")
    root = Path(str(value["root"]))
    raw_roots = value["import_roots"]
    if not isinstance(raw_roots, list):
        raise RuntimeSnapshotError("import_roots del snapshot no es lista")
    names: set[str] = set()
    for raw in raw_roots:
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "kind",
            "path",
            "files",
            "logical_bytes",
            "tree_sha256",
        }:
            raise RuntimeSnapshotError("identidad de import root no es cerrada")
        name = raw["name"]
        if not isinstance(name, str) or not name or name in names:
            raise RuntimeSnapshotError("nombre de import root ausente/duplicado")
        names.add(name)
        path = Path(str(raw["path"]))
        if path != root / "import-roots" / name or raw["kind"] != "import_parent":
            raise RuntimeSnapshotError("import root no ocupa su contenedor contractual")
    lease_files, lease_directories = _snapshot_lease_census(
        manifest_path=manifest_path,
        root=root,
        import_root_names=names,
    )
    lease, fresh_lease = _acquire_windows_snapshot_lease(
        manifest_path=manifest_path,
        root=root,
        files=lease_files,
        directories=lease_directories,
    )
    try:
        manifest_path, leased_manifest_bytes, manifest_identity = _read_bound_bytes(
            manifest_path,
            context="manifest del snapshot bajo lease",
        )
        if leased_manifest_bytes != manifest_bytes:
            raise RuntimeSnapshotError("manifest del snapshot cambió antes del cutoff")
        observed_lease_files, observed_lease_directories = _snapshot_lease_census(
            manifest_path=manifest_path,
            root=root,
            import_root_names=names,
        )
        if observed_lease_files != lease_files or observed_lease_directories != lease_directories:
            raise RuntimeSnapshotError("censo del snapshot cambió al adquirir el lease")

        scripts_root = root / "scripts"
        scripts_root_identity = _plain_directory_identity(
            scripts_root,
            context="directorio scripts del snapshot",
            create_missing=False,
        )
        observed_sources, _, source_paths, source_versions = _source_inventory_snapshot(
            root,
            allow_pycache=False,
        )
        if observed_sources != value["files"] or value["count"] != len(observed_sources):
            raise RuntimeSnapshotError("inventario de fuentes del snapshot no reconcilia")
        observed_roots: list[dict[str, Any]] = []
        root_snapshots: list[tuple[Path, list[Path], dict[Path, os.stat_result]]] = []
        import_root_parent = root / "import-roots"
        import_root_parent_identity = _plain_directory_identity(
            import_root_parent,
            context="contenedor import-roots del snapshot",
            create_missing=False,
        )
        for raw in raw_roots:
            name = str(raw["name"])
            path = root / "import-roots" / name
            tree_identity, tree_paths, tree_versions = _tree_identity_snapshot(path)
            observed_roots.append(
                {
                    "name": name,
                    "kind": "import_parent",
                    "path": str(path),
                    **tree_identity,
                }
            )
            root_snapshots.append((path, tree_paths, tree_versions))
        if observed_roots != raw_roots:
            raise RuntimeSnapshotError("import roots del snapshot no reconcilian")
        pyarrow_roots = [item for item in observed_roots if item["name"] == "pyarrow"]
        if pyarrow_roots and not (Path(str(pyarrow_roots[0]["path"])) / "pyarrow.libs").is_dir():
            raise RuntimeSnapshotError("snapshot pyarrow omite su root DLL firmado")
        _assert_inventory_snapshot(
            _source_files(root, allow_pycache=False),
            source_paths,
            source_versions,
            context="fuentes del snapshot antes de aceptar",
        )
        for import_root, tree_paths, tree_versions in root_snapshots:
            _assert_inventory_snapshot(
                _walk_files(import_root, relative_to=import_root),
                tree_paths,
                tree_versions,
                context=f"import root antes de aceptar {import_root}",
            )
        _assert_same_plain_directory(
            import_root_parent_identity,
            context="contenedor import-roots antes de aceptar",
        )
        _assert_same_plain_directory(
            scripts_root_identity,
            context="directorio scripts antes de aceptar",
        )
        identity = _manifest_identity(manifest_path, value)
        _assert_bound_file_version(
            manifest_path,
            manifest_identity,
            context="manifest del snapshot final",
        )
        final_lease_files, final_lease_directories = _snapshot_lease_census(
            manifest_path=manifest_path,
            root=root,
            import_root_names=names,
        )
        if final_lease_files != lease_files or final_lease_directories != lease_directories:
            raise RuntimeSnapshotError("censo del snapshot cambió al cierre global")
        _assert_inventory_snapshot(
            _source_files(root, allow_pycache=False),
            source_paths,
            source_versions,
            context="fuentes del snapshot al cierre global",
        )
        _commit_windows_snapshot_lease(lease, fresh=fresh_lease)
        return identity
    except BaseException:
        if lease is not None and fresh_lease:
            _rollback_windows_snapshot_lease(lease)
        raise


__all__ = [
    "EXPECTED_IMPORT_ROOTS",
    "RuntimeSnapshotError",
    "materialize_harness_source_snapshot",
    "validate_harness_source_snapshot",
]
