"""Aislamiento OS del candidato H9R mediante integridad obligatoria de Windows.

Este módulo no autoriza ni materializa START. Sólo provee la primitiva que impide **en el sistema
operativo** —no por detección posterior— que el token del candidato cree, borre o reemplace
``OUTPUT_ROOT`` y su manifiesto: el child se lanza con un token primario de integridad *Low* y sólo
los directorios que el contrato le concede llevan etiqueta obligatoria *Low* heredable. El resto
del workdir conserva la integridad media del arnés y queda fuera de su alcance de escritura.

La lectura no se restringe: la política obligatoria por defecto es ``NO_WRITE_UP``, así que el
candidato sigue abriendo inputs, bundle y su propio runtime instalado.

Sólo stdlib, sin ``ctypes.wintypes`` ni ``msvcrt`` en el import: el paquete debe seguir siendo
importable en Linux/macOS aunque estas rutas sólo califiquen en Windows.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import stat
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from .contracts import (
    CANDIDATE_DENIED_OPERATIONS,
    CANDIDATE_LOW_INTEGRITY_SID,
    CANDIDATE_MEDIUM_INTEGRITY_SID,
    CANDIDATE_SANDBOX_MECHANISM,
    ContractError,
)

# Reexportados desde `contracts` para que la cadena durable y la capa Windows compartan un único
# literal: la primera los verifica sin poder importar este módulo.
LOW_INTEGRITY_SID: Final = CANDIDATE_LOW_INTEGRITY_SID
MEDIUM_INTEGRITY_SID: Final = CANDIDATE_MEDIUM_INTEGRITY_SID
SANDBOX_MECHANISM: Final = CANDIDATE_SANDBOX_MECHANISM
LOW_LABEL_SDDL: Final = "S:(ML;OICI;NW;;;LW)"
EMPTY_LABEL_SDDL: Final = "S:"
DENIED_OPERATIONS: Final = CANDIDATE_DENIED_OPERATIONS
_FILE_ATTRIBUTE_REPARSE_POINT: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_TOKEN_QUERY: Final = 0x0008
_TOKEN_DUPLICATE: Final = 0x0002
_TOKEN_ASSIGN_PRIMARY: Final = 0x0001
_TOKEN_ADJUST_DEFAULT: Final = 0x0080
_TOKEN_ADJUST_SESSIONID: Final = 0x0100
_TOKEN_SANDBOX_ACCESS: Final = (
    _TOKEN_QUERY
    | _TOKEN_DUPLICATE
    | _TOKEN_ASSIGN_PRIMARY
    | _TOKEN_ADJUST_DEFAULT
    | _TOKEN_ADJUST_SESSIONID
)
_PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
_SECURITY_IMPERSONATION: Final = 2
_TOKEN_PRIMARY: Final = 1
_TOKEN_INTEGRITY_LEVEL: Final = 25
_SE_GROUP_INTEGRITY: Final = 0x00000020
_SDDL_REVISION_1: Final = 1
_SE_FILE_OBJECT: Final = 1
_LABEL_SECURITY_INFORMATION: Final = 0x00000010
_ERROR_INSUFFICIENT_BUFFER: Final = 122
_CREATE_SUSPENDED: Final = 0x00000004
_CREATE_UNICODE_ENVIRONMENT: Final = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT: Final = 0x00080000
_STARTF_USESTDHANDLES: Final = 0x00000100
_HANDLE_FLAG_INHERIT: Final = 0x00000001
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST: Final = 0x00020002
_STILL_ACTIVE: Final = 259
_WAIT_TIMEOUT: Final = 0x00000102
_WAIT_OBJECT_0: Final = 0x00000000
_INFINITE: Final = 0xFFFFFFFF
_DESKTOP: Final = "WinSta0\\Default"
_MANDATORY_LABEL_ACE_SID_OFFSET: Final = 8

_KERNEL32: Any | None = None
_ADVAPI32: Any | None = None


class SandboxError(ContractError):
    """El aislamiento OS del candidato no puede acreditarse."""


class _SidAndAttributes(ctypes.Structure):
    _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32))


class _TokenMandatoryLabel(ctypes.Structure):
    _fields_ = (("Label", _SidAndAttributes),)


class _StartupInfoExW(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.c_uint32),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32),
        ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32),
        ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32),
        ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_uint16),
        ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
        ("lpAttributeList", ctypes.c_void_p),
    )


class _ProcessInformation(ctypes.Structure):
    _fields_ = (
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint32),
        ("dwThreadId", ctypes.c_uint32),
    )


class _AclHeader(ctypes.Structure):
    _fields_ = (
        ("AclRevision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("AclSize", ctypes.c_uint16),
        ("AceCount", ctypes.c_uint16),
        ("Sbz2", ctypes.c_uint16),
    )


def _require_windows(context: str) -> None:
    if sys.platform != "win32":
        raise SandboxError(f"{context}: el aislamiento OS del candidato exige Windows")


def _kernel32() -> Any:
    global _KERNEL32
    if _KERNEL32 is None:
        _require_windows("kernel32")
        library: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        library.GetCurrentProcess.argtypes = []
        library.GetCurrentProcess.restype = ctypes.c_void_p
        library.CloseHandle.argtypes = [ctypes.c_void_p]
        library.CloseHandle.restype = ctypes.c_bool
        library.LocalFree.argtypes = [ctypes.c_void_p]
        library.LocalFree.restype = ctypes.c_void_p
        library.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        library.WaitForSingleObject.restype = ctypes.c_uint32
        library.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.GetExitCodeProcess.restype = ctypes.c_bool
        library.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        library.TerminateProcess.restype = ctypes.c_bool
        library.SetHandleInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        library.SetHandleInformation.restype = ctypes.c_bool
        library.GetHandleInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.GetHandleInformation.restype = ctypes.c_bool
        library.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        library.InitializeProcThreadAttributeList.restype = ctypes.c_bool
        library.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        library.UpdateProcThreadAttribute.restype = ctypes.c_bool
        library.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        library.DeleteProcThreadAttributeList.restype = None
        library.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        library.OpenProcess.restype = ctypes.c_void_p
        _KERNEL32 = library
    return _KERNEL32


def _advapi32() -> Any:
    global _ADVAPI32
    if _ADVAPI32 is None:
        _require_windows("advapi32")
        library: Any = ctypes.WinDLL("advapi32", use_last_error=True)
        library.OpenProcessToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.OpenProcessToken.restype = ctypes.c_bool
        library.DuplicateTokenEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.DuplicateTokenEx.restype = ctypes.c_bool
        library.SetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        library.SetTokenInformation.restype = ctypes.c_bool
        library.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.GetTokenInformation.restype = ctypes.c_bool
        library.ConvertStringSidToSidW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.ConvertStringSidToSidW.restype = ctypes.c_bool
        library.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        library.ConvertSidToStringSidW.restype = ctypes.c_bool
        library.GetLengthSid.argtypes = [ctypes.c_void_p]
        library.GetLengthSid.restype = ctypes.c_uint32
        library.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_bool
        library.GetSecurityDescriptorSacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_int),
        ]
        library.GetSecurityDescriptorSacl.restype = ctypes.c_bool
        library.SetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        library.SetNamedSecurityInfoW.restype = ctypes.c_uint32
        library.GetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.GetNamedSecurityInfoW.restype = ctypes.c_uint32
        library.GetAce.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.GetAce.restype = ctypes.c_bool
        library.CreateProcessAsUserW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        library.CreateProcessAsUserW.restype = ctypes.c_bool
        _ADVAPI32 = library
    return _ADVAPI32


def _raise_last_error(context: str) -> None:
    raise SandboxError(f"{context}: error Windows {ctypes.get_last_error()}")


def _require(ok: object, context: str) -> None:
    if not ok:
        _raise_last_error(context)


def _close_handle(handle: int) -> None:
    if handle and not _kernel32().CloseHandle(ctypes.c_void_p(handle)):
        _raise_last_error("CloseHandle")


def _local_free(pointer: ctypes.c_void_p) -> None:
    if pointer:
        _kernel32().LocalFree(pointer)


def _string_sid(pointer: ctypes.c_void_p) -> str:
    text = ctypes.c_wchar_p()
    _require(
        _advapi32().ConvertSidToStringSidW(pointer, ctypes.byref(text)),
        "ConvertSidToStringSidW",
    )
    value = text.value
    _local_free(ctypes.cast(text, ctypes.c_void_p))
    if not value:
        raise SandboxError("ConvertSidToStringSidW devolvió cadena vacía")
    return value


@contextlib.contextmanager
def _string_sid_pointer(value: str) -> Iterator[ctypes.c_void_p]:
    pointer = ctypes.c_void_p()
    _require(
        _advapi32().ConvertStringSidToSidW(value, ctypes.byref(pointer)),
        f"ConvertStringSidToSidW({value})",
    )
    try:
        yield pointer
    finally:
        _local_free(pointer)


def token_integrity_level(token: int) -> str:
    """Devuelve el SID textual del nivel de integridad efectivo de un token abierto."""
    library = _advapi32()
    size = ctypes.c_uint32(0)
    library.GetTokenInformation(
        ctypes.c_void_p(token), _TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size)
    )
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or size.value == 0:
        _raise_last_error("GetTokenInformation(IntegrityLevel, tamaño)")
    buffer = ctypes.create_string_buffer(size.value)
    _require(
        library.GetTokenInformation(
            ctypes.c_void_p(token),
            _TOKEN_INTEGRITY_LEVEL,
            buffer,
            size,
            ctypes.byref(size),
        ),
        "GetTokenInformation(IntegrityLevel)",
    )
    label = ctypes.cast(buffer, ctypes.POINTER(_TokenMandatoryLabel)).contents
    return _string_sid(ctypes.c_void_p(label.Label.Sid))


def process_integrity_level(pid: int) -> str:
    """Reabre un PID vivo y atestigua el nivel de integridad efectivo de su token."""
    if pid <= 0:
        raise SandboxError("PID inválido para atestiguar integridad")
    handle = _kernel32().OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    _require(handle, f"OpenProcess({pid})")
    token = ctypes.c_void_p()
    try:
        _require(
            _advapi32().OpenProcessToken(
                ctypes.c_void_p(handle), _TOKEN_QUERY, ctypes.byref(token)
            ),
            "OpenProcessToken(candidate)",
        )
    finally:
        _close_handle(int(handle))
    try:
        return token_integrity_level(int(token.value or 0))
    finally:
        _close_handle(int(token.value or 0))


@contextlib.contextmanager
def low_integrity_primary_token() -> Iterator[int]:
    """Duplica el token propio como primario y lo baja a integridad *Low*.

    No exige privilegios de administrador: bajar la integridad de una copia del token propio es
    una operación permitida a cualquier proceso. El handle se cierra siempre al salir y la
    integridad efectiva se vuelve a leer del kernel antes de entregarlo.
    """
    library = _advapi32()
    current = ctypes.c_void_p()
    _require(
        library.OpenProcessToken(
            _kernel32().GetCurrentProcess(), _TOKEN_SANDBOX_ACCESS, ctypes.byref(current)
        ),
        "OpenProcessToken(self)",
    )
    duplicated = ctypes.c_void_p()
    try:
        _require(
            library.DuplicateTokenEx(
                current,
                _TOKEN_SANDBOX_ACCESS,
                None,
                _SECURITY_IMPERSONATION,
                _TOKEN_PRIMARY,
                ctypes.byref(duplicated),
            ),
            "DuplicateTokenEx",
        )
    finally:
        _close_handle(int(current.value or 0))
    token = int(duplicated.value or 0)
    try:
        with _string_sid_pointer(LOW_INTEGRITY_SID) as sid:
            label = _TokenMandatoryLabel()
            label.Label.Sid = sid
            label.Label.Attributes = _SE_GROUP_INTEGRITY
            _require(
                library.SetTokenInformation(
                    ctypes.c_void_p(token),
                    _TOKEN_INTEGRITY_LEVEL,
                    ctypes.byref(label),
                    ctypes.sizeof(_TokenMandatoryLabel) + library.GetLengthSid(sid),
                ),
                "SetTokenInformation(IntegrityLevel=Low)",
            )
        observed = token_integrity_level(token)
        if observed != LOW_INTEGRITY_SID:
            raise SandboxError(f"el token candidato no quedó en integridad Low: {observed}")
        yield token
    finally:
        _close_handle(token)


def mandatory_label(path: Path) -> str | None:
    """Reabre la etiqueta obligatoria efectiva de una ruta.

    ``None`` significa integridad media: Windows no materializa una etiqueta explícita para ese
    nivel y su ausencia **es** el nivel medio. El censo del arnés usa esa distinción en ambos
    sentidos, así que la función no inventa un SID cuando la etiqueta falta.
    """
    resolved = path.resolve()
    library = _advapi32()
    descriptor = ctypes.c_void_p()
    sacl = ctypes.c_void_p()
    code = library.GetNamedSecurityInfoW(
        str(resolved),
        _SE_FILE_OBJECT,
        _LABEL_SECURITY_INFORMATION,
        None,
        None,
        None,
        ctypes.byref(sacl),
        ctypes.byref(descriptor),
    )
    if code != 0:
        raise SandboxError(f"GetNamedSecurityInfoW(label) falló con {code}: {resolved}")
    try:
        if not sacl:
            return None
        header = ctypes.cast(sacl, ctypes.POINTER(_AclHeader)).contents
        if header.AceCount == 0:
            return None
        ace = ctypes.c_void_p()
        _require(library.GetAce(sacl, 0, ctypes.byref(ace)), "GetAce")
        return _string_sid(ctypes.c_void_p((ace.value or 0) + _MANDATORY_LABEL_ACE_SID_OFFSET))
    finally:
        _local_free(descriptor)


def apply_low_integrity_label(directory: Path) -> None:
    """Marca un directorio como escribible por el candidato con etiqueta *Low* heredable."""
    resolved = directory.resolve()
    if not resolved.is_dir():
        raise SandboxError(f"destino de etiqueta inexistente o no plano: {resolved}")
    library = _advapi32()
    descriptor = ctypes.c_void_p()
    size = ctypes.c_uint32()
    _require(
        library.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            LOW_LABEL_SDDL, _SDDL_REVISION_1, ctypes.byref(descriptor), ctypes.byref(size)
        ),
        "ConvertStringSecurityDescriptorToSecurityDescriptorW",
    )
    try:
        present = ctypes.c_int()
        sacl = ctypes.c_void_p()
        defaulted = ctypes.c_int()
        _require(
            library.GetSecurityDescriptorSacl(
                descriptor,
                ctypes.byref(present),
                ctypes.byref(sacl),
                ctypes.byref(defaulted),
            ),
            "GetSecurityDescriptorSacl",
        )
        if not present.value:
            raise SandboxError("el descriptor de etiqueta Low no expone SACL")
        code = library.SetNamedSecurityInfoW(
            str(resolved),
            _SE_FILE_OBJECT,
            _LABEL_SECURITY_INFORMATION,
            None,
            None,
            None,
            sacl,
        )
        if code != 0:
            raise SandboxError(f"SetNamedSecurityInfoW(label) falló con {code}: {resolved}")
    finally:
        _local_free(descriptor)
    observed = mandatory_label(resolved)
    if observed != LOW_INTEGRITY_SID:
        raise SandboxError(f"la etiqueta Low no quedó efectiva en {resolved}: {observed}")


class SandboxProcess:
    """Proceso candidato creado suspendido con el token de integridad *Low* del arnés."""

    def __init__(self, handle: int, thread_handle: int, pid: int) -> None:
        self._handle = handle
        self._thread_handle = thread_handle
        self.pid = pid
        self.returncode: int | None = None

    @property
    def thread_handle(self) -> int:
        """Handle del hilo principal suspendido, necesario para reanudarlo."""
        return self._thread_handle

    def poll(self) -> int | None:
        """Devuelve el código de salida si el proceso ya terminó, o ``None``.

        La vivencia se decide señalizando el objeto proceso, no comparando contra
        ``STILL_ACTIVE``: el candidato elige su propio código de salida y 259 es un valor
        legítimo que, interpretado como "sigue vivo", colgaría la limpieza.
        """
        if self.returncode is not None:
            return self.returncode
        library = _kernel32()
        if library.WaitForSingleObject(ctypes.c_void_p(self._handle), 0) != _WAIT_OBJECT_0:
            return None
        code = ctypes.c_uint32()
        _require(
            library.GetExitCodeProcess(ctypes.c_void_p(self._handle), ctypes.byref(code)),
            "GetExitCodeProcess",
        )
        self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        """Espera la terminación; agotar el plazo levanta ``subprocess.TimeoutExpired``."""
        if self.returncode is not None:
            return self.returncode
        milliseconds = _INFINITE if timeout is None else max(0, int(timeout * 1000))
        result = _kernel32().WaitForSingleObject(ctypes.c_void_p(self._handle), milliseconds)
        if result == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(cmd="h9r-candidate", timeout=timeout or 0.0)
        if result != _WAIT_OBJECT_0:
            _raise_last_error("WaitForSingleObject")
        code = self.poll()
        if code is None:
            raise SandboxError("el proceso señalizó terminación sin código de salida")
        return code

    def kill(self, exit_code: int = 1) -> None:
        """Termina el proceso; no falla si ya había terminado."""
        if self.poll() is not None:
            return
        _kernel32().TerminateProcess(ctypes.c_void_p(self._handle), exit_code)

    def close(self) -> None:
        """Cierra los handles propios; es idempotente y no filtra si el primero falla."""
        thread_handle, self._thread_handle = self._thread_handle, 0
        process_handle, self._handle = self._handle, 0
        try:
            _close_handle(thread_handle)
        finally:
            _close_handle(process_handle)


@contextlib.contextmanager
def terminated_on_exit(
    process: SandboxProcess, *, grace_seconds: float = 10.0
) -> Iterator[SandboxProcess]:
    """Garantiza que el hijo no sobreviva al bloque, salga éste como salga.

    ``close()`` sólo suelta handles. Si el proceso sigue vivo —suspendido porque falló la
    atestación de integridad antes de reanudarlo, o corriendo todavía tras un timeout— cerrar el
    handle lo deja huérfano y **ya sin forma de matarlo**, porque el único handle con
    ``PROCESS_TERMINATE`` era el que se acaba de cerrar. Terminar antes de cerrar es lo que hace
    recuperable un fallo del probe en vez de contaminar la limpieza y los reintentos siguientes.
    """
    try:
        yield process
    finally:
        try:
            if process.poll() is None:
                process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired, SandboxError):
                    process.wait(timeout=grace_seconds)
        finally:
            process.close()


def _environment_block(environment: Mapping[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    if any("\0" in name or "\0" in value for name, value in environment.items()):
        raise SandboxError("el entorno del candidato contiene NUL")
    if any(not name or "=" in name for name in environment):
        raise SandboxError("el entorno del candidato contiene un nombre inválido")
    ordered = sorted(environment.items(), key=lambda item: item[0].upper())
    return ctypes.create_unicode_buffer(
        "".join(f"{name}={value}\0" for name, value in ordered) + "\0"
    )


@contextlib.contextmanager
def _inheritable_handle_list(handles: Sequence[int]) -> Iterator[ctypes.Array[ctypes.c_char]]:
    """Construye la lista explícita de handles heredables del hijo.

    ``bInheritHandles=True`` sin esta lista filtraría al candidato cualquier handle heredable del
    arnés. La lista cerrada es la forma documentada de heredar exactamente los declarados.
    """
    library = _kernel32()
    size = ctypes.c_size_t(0)
    library.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    if size.value == 0:
        _raise_last_error("InitializeProcThreadAttributeList(tamaño)")
    buffer = ctypes.create_string_buffer(size.value)
    _require(
        library.InitializeProcThreadAttributeList(buffer, 1, 0, ctypes.byref(size)),
        "InitializeProcThreadAttributeList",
    )
    try:
        array = (ctypes.c_void_p * len(handles))(*[ctypes.c_void_p(item) for item in handles])
        _require(
            library.UpdateProcThreadAttribute(
                buffer,
                0,
                _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                array,
                ctypes.sizeof(array),
                None,
                None,
            ),
            "UpdateProcThreadAttribute(HANDLE_LIST)",
        )
        yield buffer
    finally:
        library.DeleteProcThreadAttributeList(buffer)


def launch_suspended_low_integrity(
    command: Sequence[str],
    *,
    token: int,
    cwd: Path,
    environment: Mapping[str, str],
    stdout_fd: int,
    stderr_fd: int,
) -> SandboxProcess:
    """Crea el candidato suspendido con el token *Low* y exactamente tres handles heredados.

    ``stdin`` se ata a ``NUL``; ``stdout``/``stderr`` reciben descriptores ya abiertos por el
    arnés. El candidato escribe su salida cruda por un handle heredado, no por un acceso nuevo al
    árbol: por eso ``telemetry`` puede seguir siendo inalcanzable para su token.
    """
    _require_windows("launch_suspended_low_integrity")
    import msvcrt

    if not command:
        raise SandboxError("el comando del candidato está vacío")
    if any("\0" in item for item in command):
        raise SandboxError("el comando del candidato contiene NUL")
    library = _kernel32()
    information = _ProcessInformation()
    restore: list[tuple[int, int]] = []
    stdin_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        handles = [
            msvcrt.get_osfhandle(stdin_fd),
            msvcrt.get_osfhandle(stdout_fd),
            msvcrt.get_osfhandle(stderr_fd),
        ]
        # La herencia se restaura siempre: marcarla y dejarla puesta expondría los mismos handles
        # a cualquier proceso que el arnés cree después.
        previous_flags: list[int] = []
        for handle in handles:
            flags = ctypes.c_uint32()
            _require(
                library.GetHandleInformation(ctypes.c_void_p(handle), ctypes.byref(flags)),
                "GetHandleInformation",
            )
            previous_flags.append(int(flags.value))
            _require(
                library.SetHandleInformation(
                    ctypes.c_void_p(handle), _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT
                ),
                "SetHandleInformation(INHERIT)",
            )
        restore.extend(zip(handles, previous_flags, strict=True))
        with _inheritable_handle_list(handles) as attributes:
            startup = _StartupInfoExW()
            startup.cb = ctypes.sizeof(_StartupInfoExW)
            startup.lpDesktop = _DESKTOP
            startup.dwFlags = _STARTF_USESTDHANDLES
            startup.hStdInput = ctypes.c_void_p(handles[0])
            startup.hStdOutput = ctypes.c_void_p(handles[1])
            startup.hStdError = ctypes.c_void_p(handles[2])
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            _require(
                _advapi32().CreateProcessAsUserW(
                    ctypes.c_void_p(token),
                    None,
                    subprocess.list2cmdline(list(command)),
                    None,
                    None,
                    True,
                    _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT | _EXTENDED_STARTUPINFO_PRESENT,
                    _environment_block(environment),
                    str(cwd.resolve()),
                    ctypes.byref(startup),
                    ctypes.byref(information),
                ),
                "CreateProcessAsUserW",
            )
    finally:
        # ``stdin`` era exclusivo de este lanzamiento; los otros dos pertenecen al llamador y
        # recuperan exactamente los flags que tenían.
        stdin_handle = msvcrt.get_osfhandle(stdin_fd)
        for handle, previous in restore:
            if handle != stdin_handle:
                library.SetHandleInformation(
                    ctypes.c_void_p(handle),
                    _HANDLE_FLAG_INHERIT,
                    previous & _HANDLE_FLAG_INHERIT,
                )
        os.close(stdin_fd)
    return SandboxProcess(
        int(information.hProcess or 0),
        int(information.hThread or 0),
        int(information.dwProcessId),
    )


# Un bit por verbo, en el orden exacto de `CANDIDATE_DENIED_OPERATIONS`. Cada `try` captura sólo
# `PermissionError`: cualquier otro desenlace propaga, el intérprete sale distinto de cero y el
# probe queda rojo. El código de salida es la máscara de lo que el candidato **sí** alcanzó, así
# que 0 es la única lectura que acredita denegación completa.
_DENIAL_PROBE_CODE: Final = (
    "import os,sys\n"
    "root, sentinel = sys.argv[1], sys.argv[2]\n"
    "alcanzado = 0\n"
    "try:\n"
    "    os.mkdir(root)\n"
    "    alcanzado |= 1\n"
    "except PermissionError:\n"
    "    pass\n"
    "try:\n"
    "    with open(sentinel + '.creado', 'xb') as nuevo:\n"
    "        nuevo.write(b'x')\n"
    "    alcanzado |= 2\n"
    "except PermissionError:\n"
    "    pass\n"
    "try:\n"
    "    os.remove(sentinel)\n"
    "    alcanzado |= 4\n"
    "except PermissionError:\n"
    "    pass\n"
    "try:\n"
    "    os.replace(sentinel, sentinel + '.suplantado')\n"
    "    alcanzado |= 8\n"
    "except PermissionError:\n"
    "    pass\n"
    "try:\n"
    "    with open(sentinel, 'r+b') as existente:\n"
    "        existente.seek(0)\n"
    "        existente.write(b'FALSIFICADO')\n"
    "        existente.truncate()\n"
    "    alcanzado |= 16\n"
    "except PermissionError:\n"
    "    pass\n"
    "sys.exit(alcanzado)\n"
)


def probe_output_root_denial(
    output_root: Path, *, python_executable: Path, timeout_seconds: float = 60.0
) -> dict[str, Any]:
    """Mide la denegación real del sistema operativo antes de crear el candidato.

    Que la etiqueta quede escrita no prueba que el volumen la *aplique*: un filesystem podría
    aceptar la llamada sin imponer la política obligatoria. Este doble sintético del arnés —nunca
    el runtime candidato— ejerce con un token de integridad Low toda la matriz
    ``CANDIDATE_DENIED_OPERATIONS`` dentro del contenedor de ``OUTPUT_ROOT``: crear el directorio,
    crear un archivo nuevo, borrar un archivo existente, reemplazarlo por rename y sobrescribir su
    contenido en sitio.

    Las tres primeras sólo ejercen accesos sobre el **directorio**; las dos últimas ejercen
    ``FILE_WRITE_DATA`` sobre un archivo ya existente, que es el acceso con el que se falsificaría
    un manifiesto publicado en vez de reemplazarlo. Medir sólo los verbos de directorio dejaría esa
    puerta sin evidencia. Las cinco deben devolver ``PermissionError``; cualquier otro desenlace
    deja el intento sin garantía.
    """
    _require_windows("probe_output_root_denial")
    from .windows_job import resume_suspended_process

    if output_root.exists():
        raise SandboxError("OUTPUT_ROOT existe antes del probe de denegación")
    parent = output_root.parent
    if not parent.is_dir():
        raise SandboxError(f"el padre de OUTPUT_ROOT no es un directorio plano: {parent}")
    sentinel = parent / f".h9r-denial-sentinel-{os.getpid()}-{time.monotonic_ns()}"
    if sentinel.exists():
        raise SandboxError("el centinela del probe de denegación ya existe")
    sentinel.write_bytes(b"centinela del arnes")
    command = [
        str(python_executable),
        "-I",
        "-B",
        "-S",
        "-c",
        _DENIAL_PROBE_CODE,
        str(output_root),
        str(sentinel),
    ]
    stdout_fd = os.open(os.devnull, os.O_WRONLY)
    stderr_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        with low_integrity_primary_token() as token:
            process = launch_suspended_low_integrity(
                command,
                token=token,
                cwd=parent,
                environment={"SYSTEMROOT": os.environ["SYSTEMROOT"]},
                stdout_fd=stdout_fd,
                stderr_fd=stderr_fd,
            )
            with terminated_on_exit(process):
                effective = process_integrity_level(process.pid)
                if effective != LOW_INTEGRITY_SID:
                    raise SandboxError(f"el probe de denegación no quedó en Low: {effective}")
                resume_suspended_process(process.pid)
                returncode = process.wait(timeout=timeout_seconds)
    finally:
        os.close(stdout_fd)
        os.close(stderr_fd)
        intact = sentinel.is_file() and sentinel.read_bytes() == b"centinela del arnes"
        sentinel.unlink(missing_ok=True)
        (parent / f"{sentinel.name}.suplantado").unlink(missing_ok=True)
        (parent / f"{sentinel.name}.creado").unlink(missing_ok=True)
    if returncode != 0 or output_root.exists() or not intact:
        raise SandboxError(
            "el sistema operativo no denegó alguna de las operaciones "
            f"{list(DENIED_OPERATIONS)} dentro del contenedor de OUTPUT_ROOT "
            f"(máscara={returncode}, presente={output_root.exists()}, "
            f"centinela_intacto={intact})"
        )
    return {
        "performed": True,
        "probe_integrity_sid": LOW_INTEGRITY_SID,
        "denied_operations": list(DENIED_OPERATIONS),
        "returncode": returncode,
    }


def clear_mandatory_label(directory: Path) -> None:
    """Retira la etiqueta obligatoria explícita, devolviendo la ruta al nivel medio.

    Sólo la usan los controles negativos: la ruta productiva etiqueta directorios recién creados
    dentro de un workdir fresco y nunca necesita revertir. Existe para que el control del
    self-test restaure de verdad lo que mutó, en vez de declarar una restauración vacía.
    """
    resolved = directory.resolve()
    if not resolved.is_dir():
        raise SandboxError(f"destino de etiqueta inexistente o no plano: {resolved}")
    library = _advapi32()
    descriptor = ctypes.c_void_p()
    size = ctypes.c_uint32()
    _require(
        library.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            EMPTY_LABEL_SDDL, _SDDL_REVISION_1, ctypes.byref(descriptor), ctypes.byref(size)
        ),
        "ConvertStringSecurityDescriptorToSecurityDescriptorW(vacío)",
    )
    try:
        present = ctypes.c_int()
        sacl = ctypes.c_void_p()
        defaulted = ctypes.c_int()
        _require(
            library.GetSecurityDescriptorSacl(
                descriptor,
                ctypes.byref(present),
                ctypes.byref(sacl),
                ctypes.byref(defaulted),
            ),
            "GetSecurityDescriptorSacl(vacío)",
        )
        code = library.SetNamedSecurityInfoW(
            str(resolved),
            _SE_FILE_OBJECT,
            _LABEL_SECURITY_INFORMATION,
            None,
            None,
            None,
            sacl,
        )
        if code != 0:
            raise SandboxError(f"SetNamedSecurityInfoW(sin etiqueta) falló con {code}: {resolved}")
    finally:
        _local_free(descriptor)
    observed = mandatory_label(resolved)
    if observed is not None:
        raise SandboxError(f"la etiqueta no se retiró de {resolved}: {observed}")


def _assert_no_unexpected_low_labels(*, container: Path, writable_roots: Sequence[Path]) -> int:
    """Cierra el censo en el otro sentido: ninguna etiqueta obligatoria fuera de las declaradas.

    Enumerar sólo las raíces nombradas probaría que están bien, no que sean las **únicas**. El
    recorrido cubre **archivos y directorios**: la integridad obligatoria protege cada objeto y no
    se deriva de la etiqueta de su padre, así que un archivo etiquetado bajo un padre de
    integridad media seguiría siendo escribible por el candidato. No desciende dentro de las
    raíces escribibles —allí la etiqueta se hereda por diseño— y exige integridad media en todo lo
    demás del contenedor, incluido el snapshot de fuentes del arnés desde el que corre el driver.

    Reparse points y hardlinks son condiciones rojas, no entradas a saltar: una redirección haría
    que el censo midiera un objeto distinto del que el candidato alcanzaría por esa ruta, y un
    hardlink daría un segundo nombre —fuera del subárbol censado— al mismo contenido etiquetado.
    """
    declared = {str(root.resolve()) for root in writable_roots}
    inspected = 0
    pending = [container.resolve()]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            children = sorted(entries, key=lambda entry: entry.name.casefold())
        for entry in children:
            path = Path(entry.path)
            inspected += 1
            try:
                # `lstat` sobre la ruta léxica: no sigue el leaf y conserva el conteo de enlaces,
                # que `DirEntry.stat` reporta como 0 en CPython/Windows.
                metadata = path.lstat()
            except OSError as exc:
                raise SandboxError(f"no se pudo atestiguar la entrada del censo: {path}") from exc
            attributes = int(getattr(metadata, "st_file_attributes", 0))
            if entry.is_symlink() or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT):
                raise SandboxError(f"reparse point prohibido dentro del contenedor: {path}")
            if str(path) in declared:
                continue
            if stat.S_ISREG(metadata.st_mode) and int(getattr(metadata, "st_nlink", 1)) != 1:
                raise SandboxError(f"hardlink prohibido dentro del contenedor: {path}")
            observed = mandatory_label(path)
            if observed is not None:
                raise SandboxError(
                    f"etiqueta obligatoria inesperada fuera de las raíces declaradas: {path} "
                    f"({observed})"
                )
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
    return inspected


def census_output_isolation(
    *,
    output_root: Path,
    writable_roots: Sequence[Path],
    protected_roots: Sequence[Path],
    denial_probe: Mapping[str, Any],
) -> dict[str, Any]:
    """Censa la etiqueta de cada raíz en ambos sentidos antes de crear el candidato.

    Devuelve el censo firmable. Falla si una raíz escribible no lleva etiqueta *Low* efectiva, si
    una raíz protegida sí la lleva, o si ``OUTPUT_ROOT`` ya existe: en los tres casos la garantía
    del sistema operativo dejaría de ser cierta y el intento no puede continuar.

    El tercer sentido lo cierra ``_assert_no_unexpected_low_labels``, que recorre el contenedor
    entero —archivos incluidos— para exigir que las raíces declaradas sean las **únicas**
    etiquetadas, y publica cuántos objetos examinó.
    """
    _require_windows("census_output_isolation")
    if not writable_roots or not protected_roots:
        raise SandboxError("el censo de aislamiento exige ambas listas no vacías")
    probe = dict(denial_probe)
    if probe.get("performed") is not True or probe.get("returncode") != 0:
        raise SandboxError("el censo exige un probe de denegación efectivamente ejecutado")
    if output_root.exists():
        raise SandboxError("OUTPUT_ROOT existe antes de que el publisher lo cree")
    # La superposición se resuelve antes de leer etiquetas: si no, una raíz declarada en ambas
    # listas fallaría por su etiqueta y ocultaría el error real de declaración.
    overlapping = sorted(
        {str(root.resolve()) for root in writable_roots}
        & {str(root.resolve()) for root in protected_roots}
    )
    if overlapping:
        raise SandboxError(f"raíz declarada escribible y protegida a la vez: {overlapping[0]}")
    writable: dict[str, str] = {}
    for root in writable_roots:
        observed = mandatory_label(root)
        if observed != LOW_INTEGRITY_SID:
            raise SandboxError(f"raíz escribible sin etiqueta Low efectiva: {root} ({observed})")
        writable[str(root.resolve())] = observed
    protected: dict[str, None] = {}
    for root in protected_roots:
        if mandatory_label(root) is not None:
            raise SandboxError(f"raíz protegida con etiqueta obligatoria explícita: {root}")
        protected[str(root.resolve())] = None
    inspected = _assert_no_unexpected_low_labels(
        container=output_root.parent, writable_roots=[Path(name) for name in writable]
    )
    return {
        "mechanism": SANDBOX_MECHANISM,
        "candidate_token_integrity_sid": LOW_INTEGRITY_SID,
        "writable_roots": dict(sorted(writable.items())),
        "protected_roots": dict(sorted(protected.items())),
        "output_root": str(output_root),
        "output_root_present": False,
        # Publicar la amplitud del recorrido convierte "el censo corrió" en "el censo examinó N
        # objetos": un censo que dejara de recorrer el subárbol caería a cero y sería visible en la
        # evidencia firmada en vez de pasar como verde silencioso.
        "container_objects_inspected": inspected,
        "denial_probe": probe,
        "observed_monotonic_ns": time.monotonic_ns(),
    }
