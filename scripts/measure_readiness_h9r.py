"""Driver del arnés H9R aprobado, sin autorización implícita de START.

Los subcomandos ``catalog`` y ``schemas`` son puramente declarativos. ``preflight`` valida una
unidad exacta y puede reservar su workdir, pero no crea START. ``attempt`` sólo existe para una
futura unidad que ya tenga autoridad humana exacta; no fue invocado durante la implementación del
arnés.
"""

from __future__ import annotations

import argparse
import atexit
import base64
import csv
import ctypes
import hashlib
import importlib.machinery
import io
import json
import os
import platform
import secrets
import shutil
import stat
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(os.path.abspath(__file__)).parents[1]

_SAFE_HARNESS_LOCK_SHA256 = "32c611ad4b1e061c14e1262548bf30346610d7529a6e4fb7bc52c68ec3540d24"
_SAFE_HARNESS_DISTRIBUTIONS = {
    "cryptography": (
        "48.0.1",
        "c881c7c02476c61a6bb2195a355779608a083e69ac55c55a02377264d1e0be74",
    ),
    "pypdf": (
        "6.14.2",
        "a232851fb6ec67b54ec1fc3ea42a7b4f4015f164aee34f69c561084c5a834096",
    ),
}
_PRODUCT_HARNESS_DISTRIBUTIONS = {
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
_HARNESS_TEST_EXTRA_DISTRIBUTIONS = {
    "pypdf": (
        "6.14.2",
        "a232851fb6ec67b54ec1fc3ea42a7b4f4015f164aee34f69c561084c5a834096",
        ("pypdf",),
    ),
}
_SAFE_HARNESS_IGNORED_TREE_PARTS = frozenset({"__pycache__"})
_REPARSE_FLAG = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
_WINDOWS_GENERIC_READ = 0x80000000
_WINDOWS_FILE_SHARE_READ = 0x00000001
_WINDOWS_OPEN_EXISTING = 3
_WINDOWS_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_WINDOWS_READ_CONTROL = 0x00020000
_WINDOWS_WRITE_DAC = 0x00040000
_WINDOWS_TOKEN_QUERY = 0x00000008
_WINDOWS_TOKEN_USER = 1
_WINDOWS_ERROR_INSUFFICIENT_BUFFER = 122
_WINDOWS_SE_FILE_OBJECT = 1
_WINDOWS_DACL_SECURITY_INFORMATION = 0x00000004
_WINDOWS_UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
_WINDOWS_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_WINDOWS_SE_DACL_AUTO_INHERITED = 0x0400
_WINDOWS_SE_DACL_PROTECTED = 0x1000
_WINDOWS_DENY_ACCESS = 3
_WINDOWS_TRUSTEE_IS_SID = 0
_WINDOWS_TRUSTEE_IS_USER = 1
_WINDOWS_ACL_SIZE_INFORMATION = 2
_WINDOWS_DIRECTORY_SEAL_ACCESS = 0x00000002 | 0x00000004 | 0x00000040
_WINDOWS_KERNEL32: Any | None = None
_WINDOWS_ADVAPI32: Any | None = None
_SAFE_HARNESS_RUNTIME: dict[str, Any] | None = None
_SAFE_HARNESS_SOURCE_SNAPSHOT: dict[str, Any] | None = None


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
        observed_control, observed_fingerprint = _windows_dacl_signature_stdlib(self.handle)
        if (
            observed_control == self.descriptor_control
            and observed_fingerprint == self.dacl_fingerprint
        ):
            return
        expected_hash = hashlib.sha256(self.dacl_fingerprint).hexdigest()
        observed_hash = hashlib.sha256(observed_fingerprint).hexdigest()
        raise SystemExit(
            "DACL del snapshot no restauró exactamente: "
            f"{self.path}; control={self.descriptor_control:#06x}/"
            f"{observed_control:#06x}; sha256={expected_hash}/{observed_hash}"
        )

    def restore(self) -> None:
        if self.security_descriptor == 0:
            return
        advapi32 = _windows_advapi32_stdlib()
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
            raise SystemExit(f"no se pudo restaurar DACL del snapshot (winerror={restore_error})")
        observed_control, observed_fingerprint = _windows_dacl_signature_stdlib(self.handle)
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
                raise SystemExit(
                    f"no se pudo restaurar auto-herencia DACL del snapshot (winerror={status})"
                )
        self.assert_restored()

    def finalize(self) -> None:
        if self.security_descriptor != 0:
            _windows_local_free_stdlib(self.security_descriptor)
            self.security_descriptor = 0
            self.dacl = 0
        if self.sealed_dacl != 0:
            _windows_local_free_stdlib(self.sealed_dacl)
            self.sealed_dacl = 0


class _WindowsSnapshotLease:
    """Handles no-follow que fijan bytes e identidades del snapshot en Windows."""

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
            raise SystemExit(f"lease Windows no puede activarse desde estado {self.state!r}")
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
            raise SystemExit(f"estado inválido del lease Windows: {self.state!r}")
        for index in range(len(self.handles) - 1, -1, -1):
            _close_windows_handle_stdlib(self.handles[index])
            del self.handles[index]
        for seal in self.acl_seals:
            seal.finalize()
        self.acl_seals.clear()
        self.state = "closed"


_WINDOWS_SNAPSHOT_LEASES: dict[tuple[str, str], _WindowsSnapshotLease] = {}


def _windows_kernel32_stdlib() -> Any:
    global _WINDOWS_KERNEL32
    if sys.platform != "win32":
        raise SystemExit("kernel32 no está disponible fuera de Windows")
    if _WINDOWS_KERNEL32 is None:
        _WINDOWS_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return _WINDOWS_KERNEL32


def _windows_advapi32_stdlib() -> Any:
    global _WINDOWS_ADVAPI32
    if sys.platform != "win32":
        raise SystemExit("advapi32 no está disponible fuera de Windows")
    if _WINDOWS_ADVAPI32 is None:
        _WINDOWS_ADVAPI32 = ctypes.WinDLL("advapi32", use_last_error=True)
    return _WINDOWS_ADVAPI32


def _windows_local_free_stdlib(pointer: int) -> None:
    if pointer == 0:
        return
    kernel32 = _windows_kernel32_stdlib()
    local_free: Any = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    remaining = local_free(ctypes.c_void_p(pointer))
    if remaining not in {None, 0}:
        error = ctypes.get_last_error()
        raise SystemExit(f"no se pudo liberar memoria de seguridad Windows (winerror={error})")


def _windows_dacl_fingerprint_stdlib(dacl: int) -> bytes:
    if dacl == 0:
        raise SystemExit("snapshot Windows tiene DACL nula no sellable")
    advapi32 = _windows_advapi32_stdlib()
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
        raise SystemExit(f"no se pudo leer DACL del snapshot (winerror={error})")
    return ctypes.string_at(dacl, int(information.acl_bytes_in_use))


def _windows_dacl_state_stdlib(handle: int) -> tuple[int, int, int, bytes]:
    """Devuelve DACL, descriptor dueño, control y bytes canónicos observados."""
    advapi32 = _windows_advapi32_stdlib()
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
            _windows_local_free_stdlib(descriptor_address)
        raise SystemExit(f"no se pudo obtener DACL del snapshot (winerror={status})")
    try:
        dacl_address = int(dacl.value or 0)
        if dacl_address == 0:
            raise SystemExit("snapshot Windows tiene DACL nula no sellable")
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
            raise SystemExit(f"no se pudo leer control del descriptor Windows (winerror={error})")
        return (
            dacl_address,
            descriptor_address,
            int(control.value),
            _windows_dacl_fingerprint_stdlib(dacl_address),
        )
    except BaseException:
        _windows_local_free_stdlib(descriptor_address)
        raise


def _windows_dacl_signature_stdlib(handle: int) -> tuple[int, bytes]:
    _, descriptor, control, fingerprint = _windows_dacl_state_stdlib(handle)
    try:
        return control, fingerprint
    finally:
        _windows_local_free_stdlib(descriptor)


def _windows_current_user_sid_stdlib() -> tuple[Any, int]:
    """Retiene el buffer TOKEN_USER y devuelve el SID del proceso actual."""
    kernel32 = _windows_kernel32_stdlib()
    advapi32 = _windows_advapi32_stdlib()
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
        raise SystemExit(f"no se pudo abrir token Windows del proceso (winerror={error})")
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
            raise SystemExit(f"no se pudo dimensionar TOKEN_USER Windows (winerror={first_error})")
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
            raise SystemExit(f"no se pudo leer TOKEN_USER Windows (winerror={error})")
        token_user = _WindowsTokenUser.from_buffer(buffer)
        sid = int(token_user.user.sid or 0)
        if sid == 0:
            raise SystemExit("TOKEN_USER Windows no contiene SID")
        return buffer, sid
    finally:
        _close_windows_handle_stdlib(token_handle)


def _apply_windows_directory_seal_stdlib(
    handle: int,
    *,
    path: Path,
    sid: int,
    seals: list[_WindowsAclSeal],
) -> _WindowsAclSeal:
    """Niega altas/bajas de hijos y conserva la DACL original para rollback exacto."""
    old_dacl, descriptor, control, fingerprint = _windows_dacl_state_stdlib(handle)
    advapi32 = _windows_advapi32_stdlib()
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
            raise SystemExit(f"no se pudo construir DACL sellada del snapshot (winerror={status})")
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
            raise SystemExit(
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
            raise SystemExit(f"no se pudo asociar DACL sellada del snapshot (winerror={error})")
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
            raise SystemExit(f"no se pudo aplicar DACL sellada del snapshot (winerror={error})")
        return seal
    except BaseException:
        if not ownership_transferred:
            _windows_local_free_stdlib(descriptor)
        raise
    finally:
        new_dacl_address = int(new_dacl.value or 0)
        if new_dacl_address:
            _windows_local_free_stdlib(new_dacl_address)


def _seal_windows_snapshot_directories_stdlib(
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
        raise SystemExit("censo Windows no contiene root del snapshot a sellar")
    sid_buffer, sid = _windows_current_user_sid_stdlib()
    try:
        for directory in targets:
            handle = handles_by_path.get(directory)
            if handle is None:
                raise SystemExit(f"falta handle Windows del directorio a sellar: {directory}")
            _apply_windows_directory_seal_stdlib(
                handle,
                path=directory,
                sid=sid,
                seals=seals,
            )
    finally:
        del sid_buffer


def _close_windows_handle_stdlib(handle: int) -> None:
    if sys.platform != "win32":
        return
    kernel32 = _windows_kernel32_stdlib()
    close_handle: Any = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    if not bool(close_handle(ctypes.c_void_p(handle))):
        error = ctypes.get_last_error()
        raise SystemExit(f"no se pudo cerrar handle del snapshot (winerror={error})")


def _release_snapshot_leases_for_tests() -> None:
    """Libera leases; un fallo conserva registry, handles y DACL para retry."""
    for key, lease in reversed(list(_WINDOWS_SNAPSHOT_LEASES.items())):
        lease.close()
        if _WINDOWS_SNAPSHOT_LEASES.get(key) is lease:
            del _WINDOWS_SNAPSHOT_LEASES[key]


atexit.register(_release_snapshot_leases_for_tests)


class _SnapshotLeaseReleaseError(RuntimeError):
    """La CLI no puede publicar éxito hasta liberar todos los leases exactamente."""


def _release_cli_snapshot_leases() -> None:
    """Libera en LIFO cross-module; ``atexit`` queda sólo como respaldo."""
    runtime_module = sys.modules.get("scripts.readiness_h9r.runtime_snapshot")
    if runtime_module is not None:
        runtime_release: Any = getattr(
            runtime_module,
            "_release_snapshot_leases_for_tests",
            None,
        )
        if runtime_release is not None:
            try:
                runtime_release()
            except BaseException as exc:
                raise _SnapshotLeaseReleaseError(
                    "falló liberación explícita del lease runtime H9R"
                ) from exc
    try:
        _release_snapshot_leases_for_tests()
    except BaseException as exc:
        raise _SnapshotLeaseReleaseError(
            "falló liberación explícita del lease bootstrap H9R"
        ) from exc


def _sha256_file_stdlib(path: Path) -> str:
    _, payload, _ = _read_bound_bytes_stdlib(path, context="archivo para SHA-256")
    return hashlib.sha256(payload).hexdigest()


def _safe_regular_file_stdlib(
    path: Path, *, context: str, require_single_link: bool = True
) -> Path:
    _reject_reparse_ancestors(path, context=context)
    absolute = Path(os.path.abspath(path))
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or bool(attributes & _REPARSE_FLAG):
        raise SystemExit(f"{context}: archivo ausente, symlink o reparse point")
    if require_single_link and int(getattr(info, "st_nlink", 1)) != 1:
        raise SystemExit(f"{context}: hardlink no permitido")
    return absolute


def _same_file_version_stdlib(left: os.stat_result, right: os.stat_result) -> bool:
    return bool(
        os.path.samestat(left, right)
        and int(left.st_size) == int(right.st_size)
        and int(getattr(left, "st_mtime_ns", 0)) == int(getattr(right, "st_mtime_ns", 0))
    )


def _assert_bound_file_version_stdlib(
    path: Path,
    expected: os.stat_result,
    *,
    context: str,
    require_single_link: bool = True,
) -> None:
    candidate = _safe_regular_file_stdlib(
        path,
        context=context,
        require_single_link=require_single_link,
    )
    if not _same_file_version_stdlib(expected, candidate.lstat()):
        raise SystemExit(f"{context}: el archivo cambió de versión")


def _read_bound_bytes_stdlib(
    path: Path,
    *,
    context: str,
    require_single_link: bool = True,
) -> tuple[Path, bytes, os.stat_result]:
    candidate = _safe_regular_file_stdlib(
        path,
        context=context,
        require_single_link=require_single_link,
    )
    before = candidate.lstat()
    with candidate.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not _same_file_version_stdlib(before, opened):
            raise SystemExit(f"{context}: el archivo cambió antes de la lectura")
        payload = handle.read()
        after_read = os.fstat(handle.fileno())
        if not _same_file_version_stdlib(opened, after_read) or len(payload) != int(
            after_read.st_size
        ):
            raise SystemExit(f"{context}: el archivo cambió durante la lectura")
    _assert_bound_file_version_stdlib(
        candidate,
        before,
        context=f"{context}: lectura final",
        require_single_link=require_single_link,
    )
    return candidate, payload, before


def _reject_reparse_directory(path: Path, *, context: str) -> Path:
    _reject_reparse_ancestors(path, context=context)
    absolute = Path(os.path.abspath(path))
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or bool(attributes & _REPARSE_FLAG):
        raise SystemExit(f"{context}: directorio ausente, symlink o reparse point")
    return absolute


def _closed_child_directories_stdlib(path: Path, *, context: str) -> set[str]:
    parent = _reject_reparse_directory(path, context=context)
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
                raise SystemExit(f"{context}: contiene entrada no-directorio/reparse")
            if entry.name in names:
                raise SystemExit(f"{context}: contiene nombre duplicado")
            names.add(entry.name)
    return names


def _reject_reparse_ancestors(path: Path, *, context: str) -> None:
    """Rechaza cualquier salto de nombre antes de resolver la ruta contractual."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            raise SystemExit(f"{context}: ruta o ancestro ausente") from exc
        attributes = int(getattr(info, "st_file_attributes", 0))
        if current.is_symlink() or bool(attributes & _REPARSE_FLAG):
            raise SystemExit(f"{context}: ruta o ancestro es symlink/reparse point")


def _plain_directory_identity_stdlib(
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
                    raise SystemExit(f"{context}: directorio o ancestro ausente") from None
                try:
                    current.mkdir(parents=False, exist_ok=False)
                except FileExistsError as exc:
                    raise SystemExit(f"{context}: carrera al crear directorio") from exc
                metadata = current.lstat()
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or current.is_symlink()
            or bool(attributes & _REPARSE_FLAG)
        ):
            raise SystemExit(f"{context}: directorio o ancestro no es plano")
    return absolute, int(metadata.st_dev), int(metadata.st_ino)


def _assert_same_plain_directory_stdlib(identity: tuple[Path, int, int], *, context: str) -> None:
    observed = _plain_directory_identity_stdlib(
        identity[0],
        context=context,
        create_missing=False,
    )
    if observed[1:] != identity[1:]:
        raise SystemExit(f"{context}: el directorio cambió de identidad")


def _require_absent_leaf_stdlib(path: Path, *, context: str) -> None:
    if os.path.lexists(Path(os.path.abspath(path))):
        raise SystemExit(f"{context}: destino ya existe")


def _harness_source_paths_stdlib(root: Path, *, allow_pycache: bool) -> list[Path]:
    scripts_root = _reject_reparse_directory(root / "scripts", context="scripts del arnés")
    package_root = _reject_reparse_directory(
        scripts_root / "readiness_h9r", context="paquete readiness_h9r"
    )
    expected = [scripts_root / "__init__.py", scripts_root / "measure_readiness_h9r.py"]
    with os.scandir(package_root) as entries:
        for entry in entries:
            attributes = int(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0))
            if entry.name == "__pycache__" and entry.is_dir(follow_symlinks=False):
                if allow_pycache:
                    continue
                raise SystemExit("snapshot H9R contiene __pycache__ no firmado")
            if (
                entry.is_symlink()
                or bool(attributes & _REPARSE_FLAG)
                or not entry.is_file(follow_symlinks=False)
                or not entry.name.endswith(".py")
            ):
                raise SystemExit(f"paquete H9R contiene entrada no catalogada: {entry.name}")
            expected.append(Path(entry.path))
    return sorted(expected, key=lambda path: path.relative_to(root).as_posix())


def _assert_closed_snapshot_root_stdlib(path: Path, *, context: str) -> None:
    root = _reject_reparse_directory(path, context=context)
    if _closed_child_directories_stdlib(root, context=context) != {"scripts", "import-roots"}:
        raise SystemExit(f"{context}: contiene entradas extra/faltantes")


def _assert_closed_snapshot_scripts_stdlib(path: Path, *, context: str) -> None:
    scripts_root = _reject_reparse_directory(path, context=context)
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
                raise SystemExit(f"{context}: contiene symlink/reparse point")
            if entry.is_file(follow_symlinks=False):
                kind = "file"
            elif entry.is_dir(follow_symlinks=False):
                kind = "directory"
            else:
                raise SystemExit(f"{context}: contiene entrada no regular")
            if entry.name in observed:
                raise SystemExit(f"{context}: contiene nombre duplicado")
            observed[entry.name] = kind
    if observed != expected:
        raise SystemExit(f"{context}: contiene entradas extra/faltantes")


def _tree_directories_stdlib(root: Path) -> list[Path]:
    root = _reject_reparse_directory(root, context="contenedor importable")
    directories = [root]
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                attributes = int(getattr(metadata, "st_file_attributes", 0))
                if entry.name == "__pycache__" and entry.is_dir(follow_symlinks=False):
                    raise SystemExit("root importable contiene __pycache__ no firmado")
                if entry.is_symlink() or bool(attributes & _REPARSE_FLAG):
                    raise SystemExit("root importable contiene symlink/reparse point")
                if entry.is_dir(follow_symlinks=False):
                    child = _reject_reparse_directory(
                        Path(entry.path),
                        context="directorio importable",
                    )
                    directories.append(child)
                    stack.append(child)
                elif entry.is_file(follow_symlinks=False):
                    _safe_regular_file_stdlib(
                        Path(entry.path),
                        context="payload importable",
                    )
                else:
                    raise SystemExit("root importable contiene entrada no regular")
    return sorted(directories, key=lambda item: str(item).casefold())


def _snapshot_lease_census_stdlib(
    *,
    manifest_path: Path,
    snapshot_root: Path,
    live_root: Path,
    import_root_names: set[str],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Censa las fuentes vivas/copiadas y todos los roots antes del cutoff Windows."""
    _assert_closed_snapshot_root_stdlib(snapshot_root, context="root del snapshot H9R")
    scripts_root = snapshot_root / "scripts"
    _assert_closed_snapshot_scripts_stdlib(
        scripts_root,
        context="directorio scripts del snapshot H9R",
    )
    snapshot_package = _reject_reparse_directory(
        scripts_root / "readiness_h9r",
        context="paquete del snapshot H9R",
    )
    snapshot_sources = _harness_source_paths_stdlib(snapshot_root, allow_pycache=False)
    live_sources = _harness_source_paths_stdlib(live_root, allow_pycache=True)
    live_scripts = _reject_reparse_directory(
        live_root / "scripts",
        context="scripts vivos del arnés",
    )
    live_package = _reject_reparse_directory(
        live_scripts / "readiness_h9r",
        context="paquete vivo del arnés",
    )
    import_root_parent = _reject_reparse_directory(
        snapshot_root / "import-roots",
        context="contenedor import-roots del snapshot",
    )
    if (
        _closed_child_directories_stdlib(
            import_root_parent,
            context="contenedor import-roots del snapshot",
        )
        != import_root_names
    ):
        raise SystemExit("contenedor import-roots tiene roots extra/faltantes")
    import_files: list[Path] = []
    import_directories: list[Path] = []
    for name in sorted(import_root_names):
        container = _reject_reparse_directory(
            import_root_parent / name,
            context=f"import root {name}",
        )
        import_files.extend(_tree_paths_stdlib(container))
        import_directories.extend(_tree_directories_stdlib(container))
    files = tuple(
        sorted(
            {
                Path(os.path.abspath(manifest_path)),
                *snapshot_sources,
                *live_sources,
                *import_files,
            },
            key=lambda item: str(item).casefold(),
        )
    )
    directories = tuple(
        sorted(
            {
                _reject_reparse_directory(snapshot_root, context="root del snapshot H9R"),
                _reject_reparse_directory(scripts_root, context="scripts del snapshot H9R"),
                snapshot_package,
                import_root_parent,
                _reject_reparse_directory(live_root, context="root vivo del arnés"),
                live_scripts,
                live_package,
                *import_directories,
            },
            key=lambda item: str(item).casefold(),
        )
    )
    return files, directories


def _open_windows_read_lease_stdlib(
    path: Path,
    *,
    directory: bool,
    context: str,
    handles: list[int],
    seal_children: bool = False,
) -> int:
    if sys.platform != "win32":
        raise SystemExit(f"{context}: lease Windows solicitado fuera de Windows")
    absolute = (
        _reject_reparse_directory(path, context=context)
        if directory
        else _safe_regular_file_stdlib(path, context=context)
    )
    before = absolute.lstat()
    kernel32 = _windows_kernel32_stdlib()
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
    if seal_children:
        if not directory:
            raise SystemExit(f"{context}: sólo un directorio puede sellar su censo")
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
        raise SystemExit(
            f"{context}: no se pudo adquirir lease Windows de sólo lectura (winerror={error})"
        )
    handle = int(raw_handle)
    handles.append(handle)
    after_path = (
        _reject_reparse_directory(absolute, context=f"{context}: post-lease")
        if directory
        else _safe_regular_file_stdlib(absolute, context=f"{context}: post-lease")
    )
    after = after_path.lstat()
    stable = (
        os.path.samestat(before, after) if directory else _same_file_version_stdlib(before, after)
    )
    if not stable:
        raise SystemExit(f"{context}: cambió al adquirir el lease Windows")
    return handle


def _acquire_windows_snapshot_lease_stdlib(
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
            raise SystemExit(f"lease Windows tiene cleanup pendiente en estado {lease.state!r}")
        if lease.files != files or lease.directories != directories:
            raise SystemExit("censo del snapshot difiere del lease Windows retenido")
        return lease, False
    snapshot_root = Path(os.path.abspath(root))
    snapshot_directories = {
        directory
        for directory in directories
        if directory == snapshot_root or directory.is_relative_to(snapshot_root)
    }
    directory_handles: dict[Path, int] = {}
    try:
        for directory in directories:
            handle = _open_windows_read_lease_stdlib(
                directory,
                directory=True,
                context=f"directorio bajo lease {directory}",
                handles=lease.handles,
                seal_children=directory in snapshot_directories,
            )
            directory_handles[directory] = handle
        for file_path in files:
            _open_windows_read_lease_stdlib(
                file_path,
                directory=False,
                context=f"archivo bajo lease {file_path}",
                handles=lease.handles,
            )
        _seal_windows_snapshot_directories_stdlib(
            directory_handles,
            root=root,
            directories=directories,
            seals=lease.acl_seals,
        )
    except BaseException:
        try:
            lease.close()
        except BaseException as rollback_error:
            raise SystemExit(
                "falló el rollback al adquirir el lease Windows; estado retenido para retry"
            ) from rollback_error
        if _WINDOWS_SNAPSHOT_LEASES.get(key) is lease:
            del _WINDOWS_SNAPSHOT_LEASES[key]
        raise
    return lease, True


def _commit_windows_snapshot_lease_stdlib(
    lease: _WindowsSnapshotLease | None,
    *,
    fresh: bool,
) -> None:
    if lease is None or not fresh:
        return
    if _WINDOWS_SNAPSHOT_LEASES.get(lease.key) is not lease:
        raise SystemExit("reserva del lease Windows cambió antes del commit")
    lease.activate()


def _rollback_windows_snapshot_lease_stdlib(lease: _WindowsSnapshotLease) -> None:
    """Cierra una reserva fresca; un fallo la deja alcanzable para retry."""
    lease.close()
    if _WINDOWS_SNAPSHOT_LEASES.get(lease.key) is lease:
        del _WINDOWS_SNAPSHOT_LEASES[lease.key]


def _assert_inventory_snapshot_stdlib(
    observed_paths: list[Path],
    expected_paths: list[Path],
    versions: Mapping[Path, os.stat_result],
    *,
    context: str,
) -> None:
    if observed_paths != expected_paths:
        raise SystemExit(f"{context}: el censo de archivos cambió")
    for path in observed_paths:
        identity = versions.get(path)
        if identity is None:
            raise SystemExit(f"{context}: falta versión atestiguada para {path}")
        _assert_bound_file_version_stdlib(path, identity, context=f"{context}: {path}")


def _source_inventory_snapshot_stdlib(
    root: Path, *, allow_pycache: bool
) -> tuple[
    list[dict[str, Any]],
    dict[str, bytes],
    list[Path],
    dict[Path, os.stat_result],
]:
    inventory: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    versions: dict[Path, os.stat_result] = {}
    paths = _harness_source_paths_stdlib(root, allow_pycache=allow_pycache)
    for path in paths:
        path, data, identity = _read_bound_bytes_stdlib(
            path,
            context=f"fuente H9R {path.name}",
        )
        relative = path.relative_to(root).as_posix()
        payloads[relative] = data
        versions[path] = identity
        inventory.append(
            {
                "relative_path": relative,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    _assert_inventory_snapshot_stdlib(
        _harness_source_paths_stdlib(root, allow_pycache=allow_pycache),
        paths,
        versions,
        context="fuentes H9R al cierre",
    )
    return inventory, payloads, paths, versions


def _source_inventory_stdlib(
    root: Path, *, allow_pycache: bool
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    inventory, payloads, _, _ = _source_inventory_snapshot_stdlib(
        root,
        allow_pycache=allow_pycache,
    )
    return inventory, payloads


def _canonical_json_stdlib(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _copy_safe_file(
    source: Path,
    destination: Path,
    *,
    require_source_single_link: bool = True,
) -> None:
    source = _safe_regular_file_stdlib(
        source,
        context="fuente de snapshot",
        require_single_link=require_source_single_link,
    )
    destination = Path(os.path.abspath(destination))
    parent_identity = _plain_directory_identity_stdlib(
        destination.parent,
        context="parent de snapshot",
        create_missing=True,
    )
    _require_absent_leaf_stdlib(destination, context="payload de snapshot")
    source_identity = source.lstat()
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        if not os.path.samestat(source_identity, os.fstat(input_handle.fileno())):
            raise SystemExit("fuente de snapshot cambió antes de copiar")
        destination_identity = os.fstat(output_handle.fileno())
        if int(getattr(destination_identity, "st_nlink", 1)) != 1:
            raise SystemExit("payload de snapshot nació con hardlinks")
        shutil.copyfileobj(input_handle, output_handle, 1024 * 1024)
        output_handle.flush()
        os.fsync(output_handle.fileno())
        if not os.path.samestat(source_identity, os.fstat(input_handle.fileno())):
            raise SystemExit("fuente de snapshot cambió durante la copia")
        if not os.path.samestat(destination_identity, os.fstat(output_handle.fileno())):
            raise SystemExit("payload de snapshot cambió durante la copia")
    _assert_same_plain_directory_stdlib(parent_identity, context="parent de snapshot copiado")
    copied = _safe_regular_file_stdlib(destination, context="payload copiado")
    if not os.path.samestat(destination_identity, copied.lstat()):
        raise SystemExit("payload copiado cambió de identidad")


def _write_safe_bytes_exclusive_stdlib(destination: Path, payload: bytes) -> None:
    destination = Path(os.path.abspath(destination))
    parent_identity = _plain_directory_identity_stdlib(
        destination.parent,
        context="parent de escritura segura",
        create_missing=True,
    )
    _require_absent_leaf_stdlib(destination, context="escritura segura")
    with destination.open("xb") as handle:
        identity = os.fstat(handle.fileno())
        if int(getattr(identity, "st_nlink", 1)) != 1:
            raise SystemExit("archivo seguro nació con hardlinks")
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        if not os.path.samestat(identity, os.fstat(handle.fileno())):
            raise SystemExit("archivo seguro cambió durante la escritura")
    _assert_same_plain_directory_stdlib(parent_identity, context="parent de escritura segura")
    published = _safe_regular_file_stdlib(destination, context="archivo seguro publicado")
    if not os.path.samestat(identity, published.lstat()):
        raise SystemExit("archivo seguro cambió de identidad")


def _copy_import_root(source: Path, destination: Path) -> None:
    if source.is_dir():
        _reject_reparse_directory(source, context="import root de snapshot")
        _require_absent_leaf_stdlib(destination, context="import root de snapshot")
        _plain_directory_identity_stdlib(
            destination,
            context="import root de snapshot",
            create_missing=True,
        )
        with os.scandir(source) as entries:
            for entry in entries:
                if entry.name == "__pycache__":
                    continue
                entry_path = Path(entry.path)
                attributes = int(
                    getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                )
                if entry.is_symlink() or bool(attributes & _REPARSE_FLAG):
                    raise SystemExit("import root contiene symlink/reparse point")
                if entry.is_dir(follow_symlinks=False):
                    _copy_import_root(entry_path, destination / entry.name)
                elif entry.is_file(follow_symlinks=False):
                    _copy_safe_file(
                        entry_path,
                        destination / entry.name,
                        require_source_single_link=False,
                    )
                else:
                    raise SystemExit("import root contiene entrada no regular")
    else:
        _copy_safe_file(source, destination, require_source_single_link=False)


def _record_file_identities(
    *, site_root: Path, distribution: str, version: str, expected_record_sha256: str
) -> dict[str, tuple[str | None, int | None]]:
    """Reabre un RECORD completo y verifica cada payload antes de snapshotearlo."""
    record, record_payload, record_identity = _read_bound_bytes_stdlib(
        site_root / f"{distribution}-{version}.dist-info" / "RECORD",
        context=f"RECORD productivo de {distribution}",
    )
    if hashlib.sha256(record_payload).hexdigest() != expected_record_sha256:
        raise SystemExit(f"RECORD productivo de {distribution} cambió")
    identities: dict[str, tuple[str | None, int | None]] = {}
    try:
        rows = csv.reader(io.StringIO(record_payload.decode("utf-8"), newline=""))
        for row in rows:
            if len(row) != 3 or not row[0] or row[0] in identities:
                raise SystemExit(f"RECORD productivo de {distribution} no es cerrado/único")
            relative = PurePosixPath(row[0])
            if relative.is_absolute() or ".." in relative.parts:
                raise SystemExit(f"RECORD productivo de {distribution} escapa site-packages")
            candidate, candidate_payload, candidate_identity = _read_bound_bytes_stdlib(
                site_root.joinpath(*relative.parts),
                context=f"{distribution}:{row[0]}",
                require_single_link=False,
            )
            if candidate == record:
                if row[1] or row[2]:
                    raise SystemExit(f"RECORD productivo de {distribution} autofirma RECORD")
                identities[row[0]] = (None, None)
                continue
            if not row[1].startswith("sha256=") or not row[2].isdigit():
                raise SystemExit(f"RECORD productivo de {distribution} omite hash/tamaño")
            observed_digest = hashlib.sha256(candidate_payload).digest()
            expected_digest = base64.urlsafe_b64decode(row[1][7:] + "==")
            if observed_digest != expected_digest or len(candidate_payload) != int(row[2]):
                raise SystemExit(f"RECORD productivo de {distribution} no reconcilia {row[0]}")
            _assert_bound_file_version_stdlib(
                candidate,
                candidate_identity,
                context=f"{distribution}:{row[0]} final",
                require_single_link=False,
            )
            identities[row[0]] = (row[1], int(row[2]))
    except UnicodeDecodeError as exc:
        raise SystemExit(f"RECORD productivo de {distribution} no es UTF-8") from exc
    _assert_bound_file_version_stdlib(
        record,
        record_identity,
        context=f"RECORD productivo de {distribution} final",
    )
    return identities


def _selected_import_root_entries(*, site_root: Path, root_name: str) -> set[str]:
    root = site_root / root_name
    if root.is_file():
        _safe_regular_file_stdlib(
            root, context=f"import root {root_name}", require_single_link=False
        )
        return {root_name}
    _reject_reparse_directory(root, context=f"import root {root_name}")
    observed: set[str] = set()
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.name == "__pycache__" and entry.is_dir(follow_symlinks=False):
                    continue
                attributes = int(
                    getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                )
                if entry.is_symlink() or bool(attributes & _REPARSE_FLAG):
                    raise SystemExit(f"import root {root_name} contiene symlink/reparse point")
                if entry.is_dir(follow_symlinks=False):
                    _reject_reparse_directory(path, context=f"import root {root_name}")
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    _safe_regular_file_stdlib(
                        path,
                        context=f"import root {root_name}",
                        require_single_link=False,
                    )
                    observed.add(path.relative_to(site_root).as_posix())
                else:
                    raise SystemExit(f"import root {root_name} contiene entrada no regular")
    return observed


def _assert_selected_import_roots_match_record(
    *, site_root: Path, roots: tuple[str, ...], record_entries: set[str]
) -> None:
    for root_name in roots:
        observed = _selected_import_root_entries(site_root=site_root, root_name=root_name)
        prefix = f"{root_name.rstrip('/')}/"
        expected = {
            entry for entry in record_entries if entry == root_name or entry.startswith(prefix)
        }
        if observed != expected:
            raise SystemExit(
                f"import root {root_name} no reconcilia RECORD; "
                f"missing={sorted(expected - observed)!r}; extra={sorted(observed - expected)!r}"
            )


def _assert_copied_import_root_matches_record(
    *,
    container: Path,
    root_name: str,
    record_entries: Mapping[str, tuple[str | None, int | None]],
) -> None:
    observed = _selected_import_root_entries(site_root=container, root_name=root_name)
    prefix = f"{root_name.rstrip('/')}/"
    expected = {
        relative
        for relative, identity in record_entries.items()
        if (relative == root_name or relative.startswith(prefix))
        and identity[0] is not None
        and identity[1] is not None
    }
    if observed != expected:
        raise SystemExit(
            f"import root copiado {root_name} no reconcilia RECORD; "
            f"missing={sorted(expected - observed)!r}; extra={sorted(observed - expected)!r}"
        )
    for relative in sorted(observed):
        candidate = _safe_regular_file_stdlib(
            container.joinpath(*PurePosixPath(relative).parts),
            context=f"payload copiado {relative}",
        )
        encoded_digest, expected_size = record_entries[relative]
        if encoded_digest is None or expected_size is None:
            raise SystemExit(f"payload copiado {relative} no tiene identidad RECORD")
        expected_digest = base64.urlsafe_b64decode(encoded_digest[7:] + "==")
        candidate, payload, identity = _read_bound_bytes_stdlib(
            candidate,
            context=f"payload copiado {relative}",
        )
        if hashlib.sha256(payload).digest() != expected_digest or len(payload) != expected_size:
            raise SystemExit(f"payload copiado {relative} no reconcilia bytes/tamaño RECORD")
        _assert_bound_file_version_stdlib(
            candidate,
            identity,
            context=f"payload copiado {relative} final",
        )


def _tree_paths_stdlib(root: Path) -> list[Path]:
    if root.is_file():
        return [_safe_regular_file_stdlib(root, context="import root copiado")]
    _reject_reparse_directory(root, context="import root copiado")
    observed: list[Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                attributes = int(
                    getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                )
                if entry.is_symlink() or bool(attributes & _REPARSE_FLAG):
                    raise SystemExit("import root copiado contiene symlink/reparse point")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    observed.append(_safe_regular_file_stdlib(path, context="import root copiado"))
                else:
                    raise SystemExit("import root copiado contiene entrada no regular")
    return sorted(observed, key=lambda path: path.relative_to(root).as_posix())


def _tree_identity_snapshot_stdlib(
    root: Path,
) -> tuple[dict[str, Any], list[Path], dict[Path, os.stat_result]]:
    files: list[dict[str, Any]] = []
    versions: dict[Path, os.stat_result] = {}
    paths = _tree_paths_stdlib(root)
    root_is_file = len(paths) == 1 and paths[0] == Path(os.path.abspath(root))
    for path in paths:
        path, payload, file_identity = _read_bound_bytes_stdlib(
            path,
            context="import root copiado",
        )
        versions[path] = file_identity
        files.append(
            {
                "relative_path": path.name if root_is_file else path.relative_to(root).as_posix(),
                "logical_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    files.sort(key=lambda item: str(item["relative_path"]))
    tree_identity: dict[str, Any] = {
        "files": len(files),
        "logical_bytes": sum(int(item["logical_bytes"]) for item in files),
        "tree_sha256": hashlib.sha256(_canonical_json_stdlib(files)).hexdigest(),
    }
    _assert_inventory_snapshot_stdlib(
        _tree_paths_stdlib(root),
        paths,
        versions,
        context=f"import root copiado al cierre {root}",
    )
    return tree_identity, paths, versions


def _tree_identity_stdlib(root: Path) -> dict[str, Any]:
    identity, _, _ = _tree_identity_snapshot_stdlib(root)
    return identity


def _prepare_harness_source_snapshot(
    prefix: Path,
    *,
    include_product_runtime: bool = False,
    include_harness_test_dependencies: bool = False,
) -> dict[str, Any]:
    prefix_identity = _plain_directory_identity_stdlib(
        prefix,
        context="pycache/bootstrap fresco",
        create_missing=False,
    )
    inventory, payloads = _source_inventory_stdlib(ROOT, allow_pycache=True)
    snapshot_root = prefix / "source-snapshot"
    _require_absent_leaf_stdlib(snapshot_root, context="root del snapshot H9R")
    snapshot_root.mkdir(exist_ok=False)
    _assert_same_plain_directory_stdlib(prefix_identity, context="pycache/bootstrap fresco")
    snapshot_identity = _plain_directory_identity_stdlib(
        snapshot_root,
        context="root del snapshot H9R",
        create_missing=False,
    )
    for relative, data in payloads.items():
        destination = snapshot_root / Path(relative)
        _write_safe_bytes_exclusive_stdlib(destination, data)
    observed, _ = _source_inventory_stdlib(snapshot_root, allow_pycache=False)
    if observed != inventory:
        raise SystemExit("snapshot H9R no reconcilia con sus fuentes")
    current, _ = _source_inventory_stdlib(ROOT, allow_pycache=True)
    if current != inventory:
        raise SystemExit("fuentes H9R cambiaron mientras se creaba el snapshot")
    import_root_directory = snapshot_root / "import-roots"
    _plain_directory_identity_stdlib(
        import_root_directory,
        context="contenedor de import roots",
        create_missing=True,
    )
    import_roots: list[dict[str, Any]] = []
    if include_product_runtime:
        if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
            raise SystemExit("el runtime firmado del arnés H9R exige Windows/CPython 3.12")
        live_site_root = ROOT / ".venv" / "Lib" / "site-packages"
        distributions = dict(_PRODUCT_HARNESS_DISTRIBUTIONS)
        if include_harness_test_dependencies:
            distributions.update(_HARNESS_TEST_EXTRA_DISTRIBUTIONS)
        for distribution, (version, expected_record_sha256, roots) in sorted(distributions.items()):
            record_entries = _record_file_identities(
                site_root=live_site_root,
                distribution=distribution,
                version=version,
                expected_record_sha256=expected_record_sha256,
            )
            _assert_selected_import_roots_match_record(
                site_root=live_site_root,
                roots=roots,
                record_entries=set(record_entries),
            )
            containers: dict[str, Path] = {}
            for name in roots:
                source = live_site_root / name
                logical_name = (
                    "_cffi_backend"
                    if name.startswith("_cffi_backend.")
                    else "pyarrow"
                    if name == "pyarrow.libs"
                    else Path(name).stem
                    if source.is_file()
                    else name
                )
                container = containers.setdefault(
                    logical_name, import_root_directory / logical_name
                )
                _plain_directory_identity_stdlib(
                    container,
                    context=f"contenedor importable {logical_name}",
                    create_missing=True,
                )
                destination = container / name
                _copy_import_root(source, destination)
                _assert_copied_import_root_matches_record(
                    container=container,
                    root_name=name,
                    record_entries=record_entries,
                )
            for logical_name, container in sorted(containers.items()):
                identity = _tree_identity_stdlib(container)
                import_roots.append(
                    {
                        "name": logical_name,
                        "kind": "import_parent",
                        "path": str(container),
                        **identity,
                    }
                )
    import_roots.sort(key=lambda item: str(item["name"]))
    source_manifest_sha256 = hashlib.sha256(_canonical_json_stdlib(inventory)).hexdigest()
    manifest_core = {
        "schema_version": "nikodym.readiness.h9r.harness-source-snapshot.v1",
        "root": str(snapshot_root),
        "files": inventory,
        "count": len(inventory),
        "import_roots": import_roots,
        "source_tooling_manifest_sha256": source_manifest_sha256,
    }
    manifest = {
        **manifest_core,
        "manifest_sha256": hashlib.sha256(_canonical_json_stdlib(manifest_core)).hexdigest(),
    }
    manifest_path = prefix / "source-snapshot-manifest.json"
    _assert_same_plain_directory_stdlib(snapshot_identity, context="root del snapshot final")
    _write_safe_bytes_exclusive_stdlib(
        manifest_path,
        _canonical_json_stdlib(manifest) + b"\n",
    )
    return _verify_harness_source_snapshot({**manifest, "manifest_path": str(manifest_path)})


def _verify_harness_source_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Fija un cutoff común del snapshot antes de permitir sus imports.

    Windows retiene handles ``no-follow`` con share READ para manifest, fuentes vivas/copiadas,
    import roots y sus directorios, y niega altas/bajas en cada directorio harness-owned. Fuera de
    Windows sólo se promete revalidación exacta al cierre.
    """
    expected = dict(raw)
    if set(expected) != {
        "schema_version",
        "root",
        "files",
        "count",
        "import_roots",
        "source_tooling_manifest_sha256",
        "manifest_sha256",
        "manifest_path",
    }:
        raise SystemExit("identidad del snapshot H9R no es cerrada")
    snapshot_root = Path(str(expected["root"]))
    raw_import_roots = expected["import_roots"]
    if not isinstance(raw_import_roots, list):
        raise SystemExit("import_roots del snapshot no es lista")
    observed_names: set[str] = set()
    for raw_root in raw_import_roots:
        if not isinstance(raw_root, dict):
            raise SystemExit("import root del snapshot no es objeto")
        if set(raw_root) != {
            "name",
            "kind",
            "path",
            "files",
            "logical_bytes",
            "tree_sha256",
        }:
            raise SystemExit("identidad de import root no es cerrada")
        name = raw_root.get("name")
        if not isinstance(name, str) or not name or name in observed_names:
            raise SystemExit("nombre de import root ausente o duplicado")
        observed_names.add(name)
        if raw_root.get("kind") != "import_parent":
            raise SystemExit("kind de import root no es el contractual")
        path = Path(str(raw_root.get("path")))
        expected_path = snapshot_root / "import-roots" / name
        if path != expected_path:
            raise SystemExit("import root no ocupa su contenedor contractual")
    source_tooling_manifest_sha256 = expected["source_tooling_manifest_sha256"]
    if (
        not isinstance(source_tooling_manifest_sha256, str)
        or len(source_tooling_manifest_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_tooling_manifest_sha256)
    ):
        raise SystemExit("source_tooling_manifest_sha256 no es SHA-256 canónico")
    manifest_path = Path(str(expected["manifest_path"]))
    lease_files, lease_directories = _snapshot_lease_census_stdlib(
        manifest_path=manifest_path,
        snapshot_root=snapshot_root,
        live_root=ROOT,
        import_root_names=observed_names,
    )
    lease, fresh_lease = _acquire_windows_snapshot_lease_stdlib(
        manifest_path=manifest_path,
        root=snapshot_root,
        files=lease_files,
        directories=lease_directories,
    )
    try:
        observed_lease_files, observed_lease_directories = _snapshot_lease_census_stdlib(
            manifest_path=manifest_path,
            snapshot_root=snapshot_root,
            live_root=ROOT,
            import_root_names=observed_names,
        )
        if observed_lease_files != lease_files or observed_lease_directories != lease_directories:
            raise SystemExit("censo del snapshot cambió al adquirir el lease")

        observed_snapshot, _, snapshot_paths, snapshot_versions = _source_inventory_snapshot_stdlib(
            snapshot_root,
            allow_pycache=False,
        )
        observed_live, _, live_paths, live_versions = _source_inventory_snapshot_stdlib(
            ROOT,
            allow_pycache=True,
        )
        if observed_snapshot != expected["files"] or observed_live != expected["files"]:
            raise SystemExit("snapshot o fuentes H9R cambiaron durante el comando")
        import_root_parent = snapshot_root / "import-roots"
        import_root_parent_identity = _plain_directory_identity_stdlib(
            import_root_parent,
            context="contenedor import-roots del snapshot",
            create_missing=False,
        )
        observed_import_roots: list[dict[str, Any]] = []
        import_root_snapshots: list[tuple[Path, list[Path], dict[Path, os.stat_result]]] = []
        for raw_root in raw_import_roots:
            name = str(raw_root["name"])
            path = snapshot_root / "import-roots" / name
            identity, tree_paths, tree_versions = _tree_identity_snapshot_stdlib(path)
            observed_import_roots.append(
                {
                    "name": name,
                    "kind": "import_parent",
                    "path": str(path),
                    **identity,
                }
            )
            import_root_snapshots.append((path, tree_paths, tree_versions))
        manifest_core = {
            "schema_version": expected["schema_version"],
            "root": expected["root"],
            "files": observed_snapshot,
            "count": len(observed_snapshot),
            "import_roots": observed_import_roots,
            "source_tooling_manifest_sha256": source_tooling_manifest_sha256,
        }
        manifest_path, manifest_payload, manifest_identity = _read_bound_bytes_stdlib(
            manifest_path,
            context="manifest del snapshot H9R bajo lease",
        )
        expected_manifest_without_path = {
            name: value for name, value in expected.items() if name != "manifest_path"
        }
        if (
            expected["schema_version"] != "nikodym.readiness.h9r.harness-source-snapshot.v1"
            or manifest_core != {name: expected[name] for name in manifest_core}
            or expected["manifest_sha256"]
            != hashlib.sha256(_canonical_json_stdlib(manifest_core)).hexdigest()
            or manifest_payload != _canonical_json_stdlib(expected_manifest_without_path) + b"\n"
        ):
            raise SystemExit("manifiesto del snapshot H9R no reconcilia")
        _assert_inventory_snapshot_stdlib(
            _harness_source_paths_stdlib(snapshot_root, allow_pycache=False),
            snapshot_paths,
            snapshot_versions,
            context="fuentes del snapshot antes de aceptar",
        )
        _assert_inventory_snapshot_stdlib(
            _harness_source_paths_stdlib(ROOT, allow_pycache=True),
            live_paths,
            live_versions,
            context="fuentes vivas antes de aceptar el snapshot",
        )
        for import_root, tree_paths, tree_versions in import_root_snapshots:
            _assert_inventory_snapshot_stdlib(
                _tree_paths_stdlib(import_root),
                tree_paths,
                tree_versions,
                context=f"import root antes de aceptar {import_root}",
            )
        _assert_same_plain_directory_stdlib(
            import_root_parent_identity,
            context="contenedor import-roots antes de aceptar",
        )
        _assert_bound_file_version_stdlib(
            manifest_path,
            manifest_identity,
            context="manifest del snapshot H9R final",
        )
        final_lease_files, final_lease_directories = _snapshot_lease_census_stdlib(
            manifest_path=manifest_path,
            snapshot_root=snapshot_root,
            live_root=ROOT,
            import_root_names=observed_names,
        )
        if final_lease_files != lease_files or final_lease_directories != lease_directories:
            raise SystemExit("censo del snapshot cambió al cierre global")
        _assert_inventory_snapshot_stdlib(
            _harness_source_paths_stdlib(snapshot_root, allow_pycache=False),
            snapshot_paths,
            snapshot_versions,
            context="fuentes del snapshot H9R al cierre global",
        )
        _commit_windows_snapshot_lease_stdlib(lease, fresh=fresh_lease)
        return expected
    except BaseException:
        if lease is not None and fresh_lease:
            _rollback_windows_snapshot_lease_stdlib(lease)
        raise


def _load_external_harness_snapshot(command: str) -> dict[str, Any] | None:
    internal_commands = {"_worker", "_adapter", "_candidate", "_ui_client"}
    manifest_raw = os.environ.get("NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST")
    digest_raw = os.environ.get("NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST_SHA256")
    if (manifest_raw is None) != (digest_raw is None):
        raise SystemExit("snapshot externo exige ruta y SHA-256 juntos")
    if manifest_raw is None:
        if command in internal_commands:
            raise SystemExit("executor interno exige snapshot externo pre-START")
        return None
    if command not in internal_commands:
        raise SystemExit("snapshot externo sólo es válido para un executor interno")
    if (
        digest_raw is None
        or len(digest_raw) != 64
        or any(character not in "0123456789abcdef" for character in digest_raw)
    ):
        raise SystemExit("SHA-256 externo del snapshot es inválido")
    manifest_path, manifest_bytes, manifest_identity = _read_bound_bytes_stdlib(
        Path(manifest_raw),
        context="manifest externo del snapshot",
    )
    if hashlib.sha256(manifest_bytes).hexdigest() != digest_raw:
        raise SystemExit("manifest externo del snapshot no reconcilia su SHA-256")
    try:
        payload: Any = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("manifest externo del snapshot no es JSON UTF-8") from exc
    if not isinstance(payload, dict) or manifest_bytes != _canonical_json_stdlib(payload) + b"\n":
        raise SystemExit("manifest externo del snapshot no es JSON canónico exacto")
    verified = _verify_harness_source_snapshot({**payload, "manifest_path": str(manifest_path)})
    _assert_bound_file_version_stdlib(
        manifest_path,
        manifest_identity,
        context="manifest externo del snapshot final",
    )
    if Path(os.path.abspath(str(verified["root"]))) != Path(os.path.abspath(ROOT)):
        raise SystemExit("driver interno no se ejecutó desde la raíz del snapshot")
    required_roots = {"_cffi_backend", "cffi", "cryptography", "pyarrow", "threadpoolctl"}
    if {str(item["name"]) for item in verified["import_roots"]} != required_roots:
        raise SystemExit("snapshot productivo no contiene los cinco import roots exactos")
    return verified


def _assert_snapshot_import_resolution(snapshot: Mapping[str, Any]) -> None:
    """Demuestra que cada import cerrado resolvería dentro de su contenedor firmado."""
    for raw in snapshot["import_roots"]:
        name = str(raw["name"])
        container = _reject_reparse_directory(Path(str(raw["path"])), context=f"import root {name}")
        spec = importlib.machinery.PathFinder.find_spec(name, sys.path)
        if spec is None or spec.origin is None:
            raise SystemExit(f"snapshot no resuelve import root firmado: {name}")
        candidates = [
            _safe_regular_file_stdlib(
                Path(spec.origin), context=f"origen resuelto de import {name}"
            )
        ]
        if spec.submodule_search_locations is not None:
            candidates.extend(
                _reject_reparse_directory(
                    Path(location), context=f"search location de import {name}"
                )
                for location in spec.submodule_search_locations
            )
        for candidate in candidates:
            try:
                candidate.relative_to(container)
            except ValueError as exc:
                raise SystemExit(f"import {name} resolvería fuera del snapshot firmado") from exc
        if name == "pyarrow" and not (container / "pyarrow.libs").is_dir():
            raise SystemExit("snapshot pyarrow omite su root DLL firmado")


def _assert_record_tree_closed(
    *, site_root: Path, record_entries: set[str], distribution_name: str
) -> None:
    """Censa en ambos sentidos los roots importables y dist-info del RECORD."""
    relevant_roots = (
        site_root / distribution_name,
        next(
            site_root / Path(entry).parts[0]
            for entry in sorted(record_entries)
            if Path(entry).parts[0].startswith(f"{distribution_name}-")
            and Path(entry).parts[0].endswith(".dist-info")
        ),
    )
    relevant_prefixes = tuple(f"{root.name}/" for root in relevant_roots)
    scoped_record_entries = {
        entry
        for entry in record_entries
        if entry == relevant_roots[0].name
        or entry == relevant_roots[1].name
        or entry.startswith(relevant_prefixes)
    }
    observed: set[str] = set()
    for root in relevant_roots:
        if not root.is_dir() or root.is_symlink():
            raise SystemExit(f"root de {distribution_name} ausente/no plano")
        stack = [root]
        while stack:
            directory = stack.pop()
            info = directory.lstat()
            attributes = int(getattr(info, "st_file_attributes", 0))
            reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            if directory.is_symlink() or bool(attributes & reparse_flag):
                raise SystemExit(f"árbol de {distribution_name} contiene reparse/symlink")
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if entry.name in _SAFE_HARNESS_IGNORED_TREE_PARTS:
                        if not entry.is_dir(follow_symlinks=False):
                            raise SystemExit(f"árbol de {distribution_name} suplanta __pycache__")
                        continue
                    if entry.is_symlink():
                        raise SystemExit(f"árbol de {distribution_name} contiene symlink")
                    entry_attributes = int(
                        getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                    )
                    if bool(entry_attributes & reparse_flag):
                        raise SystemExit(f"árbol de {distribution_name} contiene reparse point")
                    relative = path.relative_to(site_root).as_posix()
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        observed.add(relative)
                    else:
                        raise SystemExit(
                            f"árbol de {distribution_name} contiene entrada no regular"
                        )
    missing = scoped_record_entries - observed
    extra = observed - scoped_record_entries
    if missing or extra:
        raise SystemExit(
            f"árbol de {distribution_name} no reconcilia RECORD; "
            f"missing={sorted(missing)!r}; extra={sorted(extra)!r}"
        )


def _verify_safe_harness_dependencies(*, activate: bool) -> dict[str, Any]:
    """Verifica RECORD completo sin ejecutar ``site`` ni procesar ``.pth``."""
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise SystemExit("harness-test seguro exige runtime Windows/CPython 3.12 fijado")
    executable = _safe_regular_file_stdlib(Path(sys.executable), context="harness python")
    expected_venv = _reject_reparse_directory(ROOT / ".venv", context="venv del harness")
    if executable.parent.parent != expected_venv:
        raise SystemExit("harness-test exige el Python del .venv de este checkout")
    site_root = _reject_reparse_directory(
        expected_venv / "Lib" / "site-packages", context="site-packages del harness"
    )
    lock = _safe_regular_file_stdlib(ROOT / "uv.lock", context="uv.lock")
    if _sha256_file_stdlib(lock) != _SAFE_HARNESS_LOCK_SHA256:
        raise SystemExit("uv.lock del harness cambió")
    distributions: list[dict[str, Any]] = []
    for name, (version, expected_record_sha256) in sorted(_SAFE_HARNESS_DISTRIBUTIONS.items()):
        dist_info = _reject_reparse_directory(
            site_root / f"{name}-{version}.dist-info",
            context=f"distribución {name} {version}",
        )
        record, record_payload, record_identity = _read_bound_bytes_stdlib(
            dist_info / "RECORD",
            context=f"{name}.RECORD",
        )
        if hashlib.sha256(record_payload).hexdigest() != expected_record_sha256:
            raise SystemExit(f"RECORD de {name} cambió")
        try:
            rows = list(csv.reader(io.StringIO(record_payload.decode("utf-8"), newline="")))
        except UnicodeDecodeError as exc:
            raise SystemExit(f"RECORD de {name} no es UTF-8") from exc
        seen: set[str] = set()
        verified_files = 0
        for row in rows:
            if len(row) != 3 or not row[0] or row[0] in seen:
                raise SystemExit(f"RECORD de {name} no es cerrado/único")
            seen.add(row[0])
            relative = PurePosixPath(row[0])
            if (
                relative.is_absolute()
                or not relative.parts
                or any(
                    part in {"", ".", ".."} or "\\" in part or ":" in part
                    for part in relative.parts
                )
            ):
                raise SystemExit(f"RECORD de {name} escapa site-packages")
            candidate, candidate_payload, candidate_identity = _read_bound_bytes_stdlib(
                site_root.joinpath(*relative.parts),
                context=f"{name}:{row[0]}",
                require_single_link=False,
            )
            if candidate == record:
                if row[1] or row[2]:
                    raise SystemExit(f"RECORD de {name} debe autoexcluir su digest")
                continue
            if not row[1].startswith("sha256=") or not row[2].isdigit():
                raise SystemExit(f"RECORD de {name} omite hash/tamaño")
            observed_digest = hashlib.sha256(candidate_payload).digest()
            expected_digest = base64.urlsafe_b64decode(row[1][7:] + "==")
            if observed_digest != expected_digest or len(candidate_payload) != int(row[2]):
                raise SystemExit(f"RECORD de {name} no reconcilia {row[0]}")
            _assert_bound_file_version_stdlib(
                candidate,
                candidate_identity,
                context=f"{name}:{row[0]} final",
                require_single_link=False,
            )
            verified_files += 1
        _reject_reparse_directory(site_root / name, context=f"root importable de {name}")
        for collision in (site_root / f"{name}.py", site_root / f"{name}.pyc"):
            if os.path.lexists(collision):
                raise SystemExit(f"colisión importable no firmada para {name}")
        _assert_record_tree_closed(
            site_root=site_root,
            record_entries=seen,
            distribution_name=name,
        )
        _assert_bound_file_version_stdlib(
            record,
            record_identity,
            context=f"RECORD de {name} final",
        )
        distributions.append(
            {
                "name": name,
                "version": version,
                "dist_info_path": str(dist_info),
                "record": {
                    "path": str(record),
                    "bytes": len(record_payload),
                    "sha256": expected_record_sha256,
                },
                "verified_files": verified_files,
            }
        )
    if activate and str(site_root) not in sys.path:
        # Se agrega sin ejecutar site.py/.pth; stdlib permanece antes que el checkout.
        sys.path.append(str(site_root))
    _, executable_payload, executable_identity = _read_bound_bytes_stdlib(
        executable,
        context="harness python final",
    )
    _, lock_payload, lock_identity = _read_bound_bytes_stdlib(lock, context="uv.lock final")
    result = {
        "bootstrap_mode": "stdlib-record-verified-no-site-v1",
        "python_executable": {
            "path": str(executable),
            "bytes": len(executable_payload),
            "sha256": hashlib.sha256(executable_payload).hexdigest(),
        },
        "python_version": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "flags": {
            "isolated": sys.flags.isolated,
            "dont_write_bytecode": sys.dont_write_bytecode,
            "no_site": sys.flags.no_site,
        },
        "uv_lock": {
            "path": str(lock),
            "bytes": len(lock_payload),
            "sha256": _SAFE_HARNESS_LOCK_SHA256,
        },
        "site_packages_path": str(site_root),
        "distributions": distributions,
    }
    _assert_bound_file_version_stdlib(
        executable,
        executable_identity,
        context="harness python al cierre",
    )
    _assert_bound_file_version_stdlib(lock, lock_identity, context="uv.lock al cierre")
    return result


def _require_product_bootstrap_isolation() -> None:
    """Falla antes de importar tooling local si un comando ejecutable podría leer pyc ajeno."""
    if __name__ != "__main__" or len(sys.argv) < 2:
        return
    command = sys.argv[1]
    if command not in {
        "catalog",
        "schemas",
        "harness-test",
        "attempt",
        "preflight",
        "aggregate",
        "validate-aggregate",
        "_worker",
        "_adapter",
        "_ui_client",
        "_candidate",
    }:
        return
    prefix = (
        None
        if sys.pycache_prefix is None
        else _reject_reparse_directory(
            Path(os.path.abspath(sys.pycache_prefix)),
            context="pycache/bootstrap fresco",
        )
    )
    if (
        sys.flags.isolated != 1
        or sys.dont_write_bytecode != 1
        or sys.flags.no_site != 1
        or prefix is None
        or not prefix.is_dir()
        or any(prefix.iterdir())
    ):
        raise SystemExit(
            "comando ejecutable H9R exige -I -B -S -X pycache_prefix=<directorio fresco vacío>"
        )
    external_snapshot = _load_external_harness_snapshot(command)
    source_snapshot = (
        external_snapshot
        if external_snapshot is not None
        else _prepare_harness_source_snapshot(
            prefix,
            include_product_runtime=command
            in {
                "harness-test",
                "preflight",
                "attempt",
                "aggregate",
                "validate-aggregate",
            },
            include_harness_test_dependencies=command == "harness-test",
        )
    )
    for import_root in source_snapshot["import_roots"]:
        sys.path.append(str(import_root["path"]))
    sys.path.append(str(Path(str(source_snapshot["root"]))))
    _assert_snapshot_import_resolution(source_snapshot)
    global _SAFE_HARNESS_RUNTIME, _SAFE_HARNESS_SOURCE_SNAPSHOT
    _SAFE_HARNESS_SOURCE_SNAPSHOT = source_snapshot
    if command == "harness-test":
        _SAFE_HARNESS_RUNTIME = {
            **_verify_safe_harness_dependencies(activate=False),
            "source_snapshot": source_snapshot,
        }


_require_product_bootstrap_isolation()

if str(ROOT) not in sys.path and __name__ != "__main__":
    # Sólo las importaciones unitarias directas usan el checkout vivo; la CLI importa el snapshot.
    sys.path.append(str(ROOT))

from scripts.readiness_h9r.aggregate import build_aggregate, validate_aggregate  # noqa: E402
from scripts.readiness_h9r.artifacts import atomic_write_json_exclusive  # noqa: E402
from scripts.readiness_h9r.contracts import (  # noqa: E402
    ADAPTER_IDS,
    ATTEMPT_SCHEMA_VERSION,
    CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256,
    CAPS,
    CLASSIFICATIONS,
    FLOW_SPECS,
    GEOMETRY_IDS,
    aggregate_json_schema,
    attempt_json_schema,
    canonical_json_bytes,
    internal_authorization_gate_json_schema,
    internal_authorization_precommit_json_schema,
    internal_authorization_release_json_schema,
    post_start_failure_json_schema,
    pre_start_failure_json_schema,
    preflight_rejection_json_schema,
)
from scripts.readiness_h9r.copy_gate import (  # noqa: E402
    assert_documented_h9r_runtime_catalog,
)
from scripts.readiness_h9r.selftest import run_harness_self_test  # noqa: E402
from scripts.readiness_h9r.supervisor import (  # noqa: E402
    calibration_start_implementation_blockers,
    run_authorized_attempt,
    run_preflight,
    run_worker,
    write_preflight_rejection_evidence,
)

DOCUMENT_PATHS = {
    "proposal": ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md",
    "sdd30": ROOT / "docs/design/30-readiness-integral.md",
    "h9r_amendment": ROOT / "docs/design/_ENMIENDA-H9-ENTORNO-REPRESENTATIVO.md",
}


def catalog_payload() -> dict[str, Any]:
    """Devuelve el catálogo cerrado, sin materializar unidades START."""
    assert_documented_h9r_runtime_catalog(
        ROOT,
        caps=CAPS,
        geometry_ids=GEOMETRY_IDS,
        classifications=CLASSIFICATIONS,
        flow_specs=FLOW_SPECS,
        adapter_ids=ADAPTER_IDS,
    )
    calibration_start_blockers = []
    if CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256 is None:
        calibration_start_blockers.append("durable_calibration_authority_fingerprint_unpinned")
    calibration_start_blockers.extend(calibration_start_implementation_blockers())
    return {
        "caps_hypothesis_bytes": CAPS,
        "classifications": list(CLASSIFICATIONS),
        "consumer_adapters": {
            f"{flow_id}/{flow_step}": adapter_id
            for (flow_id, flow_step), adapter_id in sorted(ADAPTER_IDS.items())
        },
        "flow_id_count": len({spec.flow_id for spec in FLOW_SPECS}),
        "flow_step_count": len(FLOW_SPECS),
        "flows": [
            {
                "wave": spec.wave,
                "flow_id": spec.flow_id,
                "flow_step": spec.step,
                "workload_deadline_seconds": spec.workload_deadline_seconds,
                "geometries": spec.geometries,
                "outputs": list(spec.outputs),
            }
            for spec in FLOW_SPECS
        ],
        "calibration_start_enabled": not calibration_start_blockers,
        "calibration_start_blockers": calibration_start_blockers,
        "calibration_start_disabled_reason": "; ".join(calibration_start_blockers) or None,
        "materialized_start_units": 0,
    }


def _onedrive_root() -> Path | None:
    raw = os.environ.get("ONEDRIVE")
    return Path(raw) if raw else None


def _load_string_list(path: Path) -> list[str]:
    path, payload, identity = _read_bound_bytes_stdlib(
        path,
        context="lista JSON de entrada H9R",
    )
    raw: Any = json.loads(payload)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"se esperaba lista de strings: {path}")
    _assert_bound_file_version_stdlib(path, identity, context="lista JSON de entrada H9R final")
    return cast(list[str], raw)


def _read_json_object_safe(path: Path, *, context: str) -> dict[str, Any]:
    path, payload, identity = _read_bound_bytes_stdlib(path, context=context)
    try:
        raw: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON inválido: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"se esperaba objeto JSON: {path}")
    _assert_bound_file_version_stdlib(path, identity, context=f"{context} final")
    return cast(dict[str, Any], raw)


def _internal_workdir_from_request(request_path: Path) -> Path:
    """Deriva el workdir sin seguir links y exige la ubicación contractual del request."""
    request = _safe_regular_file_stdlib(request_path, context="request del executor interno")
    if request.parent.name != "control" or request.parent.parent.name != "telemetry":
        raise SystemExit("request interno no vive en telemetry/control")
    return _reject_reparse_directory(
        request.parent.parent.parent,
        context="workdir del executor interno",
    )


def _preflight_from_args(args: argparse.Namespace, *, reserve: bool) -> Any:
    unit = _read_json_object_safe(args.unit, context="unidad H9R")
    return run_preflight(
        unit=unit,
        authority_path=args.authority,
        trusted_authority_public_key_path=args.trusted_authority_public_key,
        authorization_text_path=args.authorization_text,
        candidate_manifest_path=args.candidate_manifest,
        fixture_manifest_path=args.fixture_manifest,
        config_path=args.config,
        schedule_path=args.schedule,
        prior_evidence_paths=[Path(path) for path in _load_string_list(args.prior_evidence_paths)],
        document_paths=DOCUMENT_PATHS,
        workdir=args.workdir,
        evidence_path=args.output,
        checkout_root=ROOT,
        onedrive_root=_onedrive_root(),
        reserve_workdir=reserve,
    )


def _add_attempt_identity_arguments(
    parser: argparse.ArgumentParser, *, require_consumption_path: bool = False
) -> None:
    parser.add_argument("--unit", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--trusted-authority-public-key", type=Path, required=True)
    parser.add_argument("--authorization-text", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--fixture-manifest", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--prior-evidence-paths", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    if require_consumption_path:
        parser.add_argument("--authorization-consumption-path", type=Path, required=True)


def _dispatch_cli(argv: list[str] | None = None) -> int:
    """Despacha acciones explícitas y falla si un destino ya existe."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog")
    schemas = subparsers.add_parser("schemas")
    schemas.add_argument("--directory", type=Path, required=True)
    harness_test = subparsers.add_parser("harness-test")
    harness_test.add_argument("--output", type=Path, required=True)
    preflight = subparsers.add_parser("preflight")
    _add_attempt_identity_arguments(preflight)
    attempt = subparsers.add_parser("attempt")
    _add_attempt_identity_arguments(attempt, require_consumption_path=True)
    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--cell-identity", type=Path, required=True)
    aggregate.add_argument("--expected-attempt-ids", type=Path, required=True)
    aggregate.add_argument("--attempt-evidence-paths", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    aggregate.add_argument("--trusted-authority-public-key", type=Path, required=True)
    validate_aggregate_parser = subparsers.add_parser("validate-aggregate")
    validate_aggregate_parser.add_argument("path", type=Path)
    validate_aggregate_parser.add_argument(
        "--trusted-authority-public-key", type=Path, required=True
    )
    worker = subparsers.add_parser("_worker")
    worker.add_argument("request", type=Path)
    worker.add_argument("capability_commitment_sha256")
    adapter = subparsers.add_parser("_adapter")
    adapter.add_argument("request", type=Path)
    adapter.add_argument("expected_sha256")
    adapter.add_argument("capability_commitment_sha256")
    adapter.add_argument("authorization_gate", type=Path)
    adapter.add_argument("trusted_authority_public_key", type=Path)
    ui_client = subparsers.add_parser("_ui_client")
    ui_client.add_argument("request", type=Path)
    ui_client.add_argument("expected_sha256")
    ui_client.add_argument("capability_commitment_sha256")
    ui_client.add_argument("authorization_gate", type=Path)
    ui_client.add_argument("trusted_authority_public_key", type=Path)
    candidate = subparsers.add_parser("_candidate")
    candidate.add_argument("request", type=Path)
    candidate.add_argument("expected_sha256")
    candidate.add_argument("capability_commitment_sha256")
    candidate.add_argument("authorization_gate", type=Path)
    candidate.add_argument("trusted_authority_public_key", type=Path)
    args = parser.parse_args(argv)
    if args.command == "catalog":
        payload = catalog_payload()
        serialized = canonical_json_bytes(payload).decode("utf-8")
        if _SAFE_HARNESS_SOURCE_SNAPSHOT is not None:
            _verify_harness_source_snapshot(_SAFE_HARNESS_SOURCE_SNAPSHOT)
        _release_cli_snapshot_leases()
        print(serialized)
        return 0
    if args.command == "schemas":
        schema_payloads = {
            "attempt.schema.json": attempt_json_schema(),
            "aggregate.schema.json": aggregate_json_schema(),
            "preflight-rejection.schema.json": preflight_rejection_json_schema(),
            "pre-start-failure.schema.json": pre_start_failure_json_schema(),
            "post-start-failure.schema.json": post_start_failure_json_schema(),
            "internal-authorization-precommit.schema.json": (
                internal_authorization_precommit_json_schema()
            ),
            "internal-authorization-gate.schema.json": (internal_authorization_gate_json_schema()),
            "internal-authorization-release.schema.json": (
                internal_authorization_release_json_schema()
            ),
        }
        if _SAFE_HARNESS_SOURCE_SNAPSHOT is not None:
            _verify_harness_source_snapshot(_SAFE_HARNESS_SOURCE_SNAPSHOT)
        _release_cli_snapshot_leases()
        _require_absent_leaf_stdlib(args.directory, context="directorio de schemas")
        _plain_directory_identity_stdlib(
            args.directory,
            context="directorio de schemas",
            create_missing=True,
        )
        for name, schema in schema_payloads.items():
            atomic_write_json_exclusive(args.directory / name, schema)
        return 0
    if args.command == "harness-test":
        if _SAFE_HARNESS_RUNTIME is None:
            raise RuntimeError("harness-test no tiene runtime externo verificado")
        output_parent = _plain_directory_identity_stdlib(
            args.output.parent,
            context="parent del artefacto harness-test",
            create_missing=False,
        )
        _require_absent_leaf_stdlib(args.output, context="artefacto harness-test")
        staging = args.output.with_name(
            f".{args.output.name}.h9r-pending-{os.getpid()}-{secrets.token_hex(8)}"
        )
        _require_absent_leaf_stdlib(staging, context="staging harness-test")
        try:
            artifact = run_harness_self_test(
                checkout_root=ROOT,
                output_path=staging,
                harness_runtime=_SAFE_HARNESS_RUNTIME,
            )
            final_runtime = {
                **_verify_safe_harness_dependencies(activate=False),
                "source_snapshot": _verify_harness_source_snapshot(
                    cast(Mapping[str, Any], _SAFE_HARNESS_RUNTIME["source_snapshot"])
                ),
            }
            if (
                final_runtime != _SAFE_HARNESS_RUNTIME
                or artifact["harness_runtime"] != final_runtime
            ):
                raise RuntimeError("runtime seguro cambió durante harness-test")
            if _read_json_object_safe(staging, context="staging harness-test final") != artifact:
                raise RuntimeError("staging harness-test cambió tras publicación interna")
            _, staged_bytes, _ = _read_bound_bytes_stdlib(
                staging,
                context="bytes finales del staging harness-test",
            )
            _release_cli_snapshot_leases()
            _assert_same_plain_directory_stdlib(
                output_parent,
                context="parent final del artefacto harness-test",
            )
            _require_absent_leaf_stdlib(args.output, context="artefacto harness-test final")
            _write_safe_bytes_exclusive_stdlib(args.output, staged_bytes)
            if (
                _read_json_object_safe(args.output, context="artefacto harness-test final")
                != artifact
            ):
                raise RuntimeError("harness-test final cambió tras publicación")
            return 0
        finally:
            if os.path.lexists(staging):
                staging_file = _safe_regular_file_stdlib(
                    staging,
                    context="staging harness-test a retirar",
                )
                staging_file.unlink()
    if args.command == "preflight":
        workdir_existed = os.path.lexists(args.workdir)
        try:
            result = _preflight_from_args(args, reserve=False)
            atomic_write_json_exclusive(args.output, result.as_dict())
            return 0
        except Exception as exc:
            write_preflight_rejection_evidence(
                unit_path=args.unit,
                authority_path=args.authority,
                authorization_text_path=args.authorization_text,
                trusted_authority_public_key_path=args.trusted_authority_public_key,
                candidate_manifest_path=args.candidate_manifest,
                fixture_manifest_path=args.fixture_manifest,
                config_path=args.config,
                schedule_path=args.schedule,
                prior_evidence_paths_path=args.prior_evidence_paths,
                document_paths=DOCUMENT_PATHS,
                workdir=args.workdir,
                evidence_path=args.output,
                workdir_existed_before=workdir_existed,
                reason=exc,
            )
            return 2
    if args.command == "attempt":
        workdir_existed = os.path.lexists(args.workdir)
        try:
            result = _preflight_from_args(args, reserve=True)
        except Exception as exc:
            write_preflight_rejection_evidence(
                unit_path=args.unit,
                authority_path=args.authority,
                authorization_text_path=args.authorization_text,
                trusted_authority_public_key_path=args.trusted_authority_public_key,
                candidate_manifest_path=args.candidate_manifest,
                fixture_manifest_path=args.fixture_manifest,
                config_path=args.config,
                schedule_path=args.schedule,
                prior_evidence_paths_path=args.prior_evidence_paths,
                document_paths=DOCUMENT_PATHS,
                workdir=args.workdir,
                evidence_path=args.output,
                workdir_existed_before=workdir_existed,
                reason=exc,
            )
            return 2
        attempt_evidence = run_authorized_attempt(
            preflight=result,
            workdir=args.workdir,
            evidence_path=args.output,
            driver_path=Path(os.path.abspath(__file__)),
            trusted_authority_public_key_path=args.trusted_authority_public_key,
            authorization_consumption_path=args.authorization_consumption_path,
        )
        return 0 if attempt_evidence.get("schema_version") == ATTEMPT_SCHEMA_VERSION else 3
    if args.command == "aggregate":
        cell_identity = _read_json_object_safe(args.cell_identity, context="identidad de celda")
        expected = _load_string_list(args.expected_attempt_ids)
        evidence_paths = _load_string_list(args.attempt_evidence_paths)
        raw_attempts = [
            _read_json_object_safe(Path(path), context="evidencia de intento agregada")
            for path in evidence_paths
        ]
        payload = build_aggregate(
            cell_identity=cell_identity,
            expected_attempt_ids=expected,
            attempts=cast(list[Mapping[str, Any]], raw_attempts),
            trusted_authority_public_key_path=args.trusted_authority_public_key,
        )
        atomic_write_json_exclusive(args.output, payload)
        reopened = _read_json_object_safe(args.output, context="agregado final")
        if reopened != payload:
            raise RuntimeError("aggregate final no reconcilia byte-exacto tras publicación")
        validate_aggregate(
            reopened,
            trusted_authority_public_key_path=args.trusted_authority_public_key,
        )
        return 0
    if args.command == "validate-aggregate":
        validate_aggregate(
            _read_json_object_safe(args.path, context="agregado a validar"),
            trusted_authority_public_key_path=args.trusted_authority_public_key,
        )
        return 0
    if args.command == "_worker":
        from scripts.readiness_h9r.supervisor import require_calibration_start_implementation_ready

        require_calibration_start_implementation_ready()
        return run_worker(args.request, args.capability_commitment_sha256)
    if args.command == "_adapter":
        from scripts.readiness_h9r.supervisor import require_calibration_start_implementation_ready

        require_calibration_start_implementation_ready()
        from scripts.readiness_h9r.adapters import run_adapter_request

        return run_adapter_request(
            args.request,
            args.expected_sha256,
            authorization_gate_path=args.authorization_gate,
            trusted_authority_public_key_path=args.trusted_authority_public_key,
            workdir=_internal_workdir_from_request(args.request),
            capability_commitment_sha256=args.capability_commitment_sha256,
        )
    if args.command == "_ui_client":
        from scripts.readiness_h9r.supervisor import require_calibration_start_implementation_ready

        require_calibration_start_implementation_ready()
        from scripts.readiness_h9r.adapters import run_ui_client_request

        return run_ui_client_request(
            args.request,
            args.expected_sha256,
            authorization_gate_path=args.authorization_gate,
            trusted_authority_public_key_path=args.trusted_authority_public_key,
            workdir=_internal_workdir_from_request(args.request),
            capability_commitment_sha256=args.capability_commitment_sha256,
        )
    if args.command == "_candidate":
        from scripts.readiness_h9r.supervisor import require_calibration_start_implementation_ready

        require_calibration_start_implementation_ready()
        from scripts.readiness_h9r.adapters import run_candidate_request

        return run_candidate_request(
            args.request,
            args.expected_sha256,
            authorization_gate_path=args.authorization_gate,
            trusted_authority_public_key_path=args.trusted_authority_public_key,
            workdir=_internal_workdir_from_request(args.request),
            capability_commitment_sha256=args.capability_commitment_sha256,
        )
    raise RuntimeError(f"subcomando no manejado: {args.command}")


def _run_cli_with_explicit_snapshot_release(argv: list[str] | None = None) -> int:
    """Libera leases antes de exponer el status final; ``atexit`` sólo respalda."""
    try:
        status = _dispatch_cli(argv)
    except _SnapshotLeaseReleaseError:
        # No reintentar aquí: la excepción debe determinar el exit code y el estado
        # retenido permite que el respaldo atexit (o un caller) restaure otra vez.
        raise
    except BaseException:
        _release_cli_snapshot_leases()
        raise
    _release_cli_snapshot_leases()
    return status


def main(argv: list[str] | None = None) -> int:
    """Punto único CLI/programático con liberación explícita fail-closed."""
    return _run_cli_with_explicit_snapshot_release(argv)


if __name__ == "__main__":
    raise SystemExit(main())
