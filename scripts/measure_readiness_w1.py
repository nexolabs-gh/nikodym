"""Mide el fundamento productivo W1 desde un wheel instalado fuera del checkout.

El driver no importa Nikodym al cargar. Debe ejecutarse desde un venv clean-room, con cwd y
``nikodym.__file__`` fuera del repositorio, y recibe los bytes exactos del wheel que se instalaron.
S0 es ejecutable en CI/local; S1/S2 sólo cuentan como PASS si el hardware satisface H9.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import hashlib
import json
import math
import os
import platform
import secrets
import shutil
import signal
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Final, cast

SCHEMA_VERSION_V1: Final = "nikodym.readiness.w1.v1"
S3_SCHEMA_VERSION: Final = "nikodym.readiness.w1.v2"
S3_PROTOCOL_VERSION: Final = "nikodym.readiness.w1.supervisor.v1"
ROOT: Final = Path(__file__).resolve().parents[1]
MIB: Final = 1024**2
GIB: Final = 1024**3
PROFILES: Final[dict[str, dict[str, int]]] = {
    "S0-smoke": {
        "train_rows": 10_000,
        "batch_rows": 10_000,
        "variables": 25,
        "cardinality": 100,
        "logical_cpus": 1,
        "ram_gib": 4,
        "peak_gib": 4,
        "train_seconds": 300,
        "batch_seconds": 300,
        "batch_chunk_size": 257,
        "disk_free_gib": 2,
    },
    "S1-local": {
        "train_rows": 100_000,
        "batch_rows": 100_000,
        "variables": 50,
        "cardinality": 10_000,
        "logical_cpus": 8,
        "ram_gib": 16,
        "peak_gib": 12,
        "train_seconds": 900,
        "batch_seconds": 1_200,
        "batch_chunk_size": 4_096,
        "disk_free_gib": 8,
    },
    "S2-equipo": {
        "train_rows": 1_000_000,
        "batch_rows": 5_000_000,
        "variables": 100,
        "cardinality": 100_000,
        "logical_cpus": 16,
        "ram_gib": 32,
        "peak_gib": 24,
        "train_seconds": 2_700,
        "batch_seconds": 1_200,
        "batch_chunk_size": 10_000,
        "disk_free_gib": 60,
    },
}
# Memoria toma el peak contractual H9=B. CPU/wall confinan este probe de preflight —no redefinen
# los budgets de train/batch—: 5 min de CPU y 10 min wall dejan holgura frente al baseline ~10 s.
S3_LIMITS: Final[dict[str, int | float]] = {
    "memory_bytes": 24 * GIB,
    "cpu_seconds": 300,
    "wall_seconds": 600.0,
    "handshake_seconds": 30.0,
}
S3_EXPECTED_CLASSIFICATION: Final[dict[str, dict[str, str]]] = {
    "train_rows": {"999999": "accepted", "1000000": "accepted", "1000001": "rejected"},
    "train_variables": {"99": "accepted", "100": "accepted", "101": "rejected"},
    "train_cardinality": {
        "99999": "accepted",
        "100000": "accepted",
        "100001": "rejected",
    },
    "batch_rows": {"4999999": "accepted", "5000000": "accepted", "5000001": "rejected"},
}
_S3_MEMORY_EXIT_CODE: Final = 86
_S3_MEMORY_MARKER: Final = "NIKODYM_S3_MEMORY_LIMIT"
_S3_CPU_EXIT_CODE: Final = 87
_S3_CPU_MARKER: Final = "NIKODYM_S3_CPU_LIMIT"
_S3_TAIL_BYTES: Final = 4_096


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(MIB), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_json_exclusive(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(_canonical_json(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _read_json_object(path: Path) -> dict[str, Any]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(f"JSON de protocolo no es un objeto: {path}")
    return cast(dict[str, Any], raw)


def _stream_evidence(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > _S3_TAIL_BYTES:
            handle.seek(-_S3_TAIL_BYTES, os.SEEK_END)
        tail = handle.read()
    return {
        "bytes": size,
        "sha256": _sha256(path),
        "tail_utf8": tail.decode("utf-8", errors="replace"),
        "tail_truncated": size > _S3_TAIL_BYTES,
    }


def _classification_is_exact(value: Any) -> bool:
    return bool(value == S3_EXPECTED_CLASSIFICATION)


def _total_memory_bytes() -> int | None:
    if sys.platform == "win32":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None


def _peak_rss_bytes() -> int:
    if sys.platform == "win32":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_bool

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "GetProcessMemoryInfo falló")
        return int(counters.PeakWorkingSetSize)
    import resource

    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if sys.platform == "darwin" else raw * 1024


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobBasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class _JobEndOfTimeInformation(ctypes.Structure):
    _fields_ = [("EndOfJobTimeAction", ctypes.c_uint32)]


class _WindowsJob:
    _JOB_OBJECT_LIMIT_JOB_TIME: Final = 0x00000004
    _JOB_OBJECT_LIMIT_JOB_MEMORY: Final = 0x00000200
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: Final = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION: Final = 1
    _JOB_OBJECT_END_OF_JOB_TIME_INFORMATION: Final = 6
    _JOB_OBJECT_TERMINATE_AT_END_OF_JOB: Final = 0
    _PROCESS_TERMINATE: Final = 0x0001
    _PROCESS_SET_QUOTA: Final = 0x0100
    _PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
    _WAIT_OBJECT_0: Final = 0

    def __init__(self, *, memory_bytes: int, cpu_seconds: int) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows Job Object solicitado fuera de Windows")
        self._kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()
        raw_handle = self._kernel32.CreateJobObjectW(None, None)
        if not raw_handle:
            self._raise_last_error("CreateJobObjectW")
        self.handle = int(raw_handle)
        self._closed = False
        try:
            limits = _JobExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = (
                self._JOB_OBJECT_LIMIT_JOB_TIME
                | self._JOB_OBJECT_LIMIT_JOB_MEMORY
                | self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            limits.BasicLimitInformation.PerJobUserTimeLimit = cpu_seconds * 10_000_000
            limits.JobMemoryLimit = memory_bytes
            if not self._kernel32.SetInformationJobObject(
                ctypes.c_void_p(self.handle),
                self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                self._raise_last_error("SetInformationJobObject(limits)")
            action = _JobEndOfTimeInformation(self._JOB_OBJECT_TERMINATE_AT_END_OF_JOB)
            if not self._kernel32.SetInformationJobObject(
                ctypes.c_void_p(self.handle),
                self._JOB_OBJECT_END_OF_JOB_TIME_INFORMATION,
                ctypes.byref(action),
                ctypes.sizeof(action),
            ):
                self._raise_last_error("SetInformationJobObject(end_of_time)")
        except Exception:
            self.close()
            raise

    def _configure_signatures(self) -> None:
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self._kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self._kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        self._kernel32.SetInformationJobObject.restype = ctypes.c_bool
        self._kernel32.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        self._kernel32.QueryInformationJobObject.restype = ctypes.c_bool
        self._kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        self._kernel32.OpenProcess.restype = ctypes.c_void_p
        self._kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._kernel32.AssignProcessToJobObject.restype = ctypes.c_bool
        self._kernel32.IsProcessInJob.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_bool),
        ]
        self._kernel32.IsProcessInJob.restype = ctypes.c_bool
        self._kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._kernel32.TerminateJobObject.restype = ctypes.c_bool
        self._kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = ctypes.c_bool

    @staticmethod
    def _raise_last_error(context: str) -> None:
        code = ctypes.get_last_error()
        raise OSError(code, f"{context} falló")

    def _query(self, information_class: int, value: ctypes.Structure) -> None:
        if not self._kernel32.QueryInformationJobObject(
            ctypes.c_void_p(self.handle),
            information_class,
            ctypes.byref(value),
            ctypes.sizeof(value),
            None,
        ):
            self._raise_last_error(f"QueryInformationJobObject({information_class})")

    def assign(self, pid: int) -> None:
        access = (
            self._PROCESS_TERMINATE
            | self._PROCESS_SET_QUOTA
            | self._PROCESS_QUERY_LIMITED_INFORMATION
        )
        raw_process = self._kernel32.OpenProcess(access, False, pid)
        if not raw_process:
            self._raise_last_error("OpenProcess")
        process_handle = int(raw_process)
        try:
            if not self._kernel32.AssignProcessToJobObject(
                ctypes.c_void_p(self.handle), ctypes.c_void_p(process_handle)
            ):
                self._raise_last_error("AssignProcessToJobObject")
            in_job = ctypes.c_bool(False)
            if not self._kernel32.IsProcessInJob(
                ctypes.c_void_p(process_handle),
                ctypes.c_void_p(self.handle),
                ctypes.byref(in_job),
            ):
                self._raise_last_error("IsProcessInJob")
            if not in_job.value:
                raise RuntimeError("el worker no quedó dentro del Job Object")
        finally:
            self._kernel32.CloseHandle(ctypes.c_void_p(process_handle))

    def contains(self, pid: int) -> bool:
        access = self._PROCESS_QUERY_LIMITED_INFORMATION
        raw_process = self._kernel32.OpenProcess(access, False, pid)
        if not raw_process:
            self._raise_last_error("OpenProcess(contains)")
        process_handle = int(raw_process)
        try:
            in_job = ctypes.c_bool(False)
            if not self._kernel32.IsProcessInJob(
                ctypes.c_void_p(process_handle),
                ctypes.c_void_p(self.handle),
                ctypes.byref(in_job),
            ):
                self._raise_last_error("IsProcessInJob(contains)")
            return bool(in_job.value)
        finally:
            self._kernel32.CloseHandle(ctypes.c_void_p(process_handle))

    def effective_limits(self) -> dict[str, Any]:
        limits = _JobExtendedLimitInformation()
        self._query(self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, limits)
        return {
            "limit_flags": int(limits.BasicLimitInformation.LimitFlags),
            "job_memory_commit_limit_bytes": int(limits.JobMemoryLimit),
            "job_user_time_limit_100ns": int(limits.BasicLimitInformation.PerJobUserTimeLimit),
            "kill_on_job_close": bool(
                limits.BasicLimitInformation.LimitFlags & self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ),
            "end_of_job_time_action": "terminate",
        }

    def accounting(self) -> dict[str, Any]:
        basic = _JobBasicAccountingInformation()
        limits = _JobExtendedLimitInformation()
        self._query(self._JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, basic)
        self._query(self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, limits)
        return {
            "source": "windows_job_object",
            "total_user_time_100ns": int(basic.TotalUserTime),
            "total_kernel_time_100ns": int(basic.TotalKernelTime),
            "total_user_seconds": round(int(basic.TotalUserTime) / 10_000_000, 6),
            "total_kernel_seconds": round(int(basic.TotalKernelTime) / 10_000_000, 6),
            "total_page_fault_count": int(basic.TotalPageFaultCount),
            "total_processes": int(basic.TotalProcesses),
            "active_processes": int(basic.ActiveProcesses),
            "total_terminated_processes": int(basic.TotalTerminatedProcesses),
            "peak_process_memory_commit_bytes": int(limits.PeakProcessMemoryUsed),
            "peak_job_memory_commit_bytes": int(limits.PeakJobMemoryUsed),
        }

    def active_processes(self) -> int:
        basic = _JobBasicAccountingInformation()
        self._query(self._JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, basic)
        return int(basic.ActiveProcesses)

    def wait_empty(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.active_processes() == 0:
                return True
            time.sleep(0.01)
        return self.active_processes() == 0

    def is_signaled(self) -> bool:
        result = self._kernel32.WaitForSingleObject(ctypes.c_void_p(self.handle), 0)
        return int(result) == self._WAIT_OBJECT_0

    def terminate(self, exit_code: int) -> None:
        if not self._kernel32.TerminateJobObject(
            ctypes.c_void_p(self.handle), ctypes.c_uint32(exit_code)
        ):
            self._raise_last_error("TerminateJobObject")

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        self._kernel32.CloseHandle(ctypes.c_void_p(self.handle))


class _WindowsProcessHandle:
    _SYNCHRONIZE: Final = 0x00100000
    _PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
    _WAIT_OBJECT_0: Final = 0
    _WAIT_TIMEOUT: Final = 258

    def __init__(self, pid: int) -> None:
        self._kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        self._kernel32.OpenProcess.restype = ctypes.c_void_p
        self._kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        self._kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self._kernel32.GetExitCodeProcess.restype = ctypes.c_bool
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = ctypes.c_bool
        raw_handle = self._kernel32.OpenProcess(
            self._SYNCHRONIZE | self._PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not raw_handle:
            code = ctypes.get_last_error()
            raise OSError(code, "OpenProcess(worker) falló")
        self.handle = int(raw_handle)
        self._closed = False

    def wait(self, timeout_seconds: float) -> tuple[int | None, bool]:
        milliseconds = max(0, min(math.ceil(timeout_seconds * 1_000), 0xFFFFFFFE))
        observed = int(
            self._kernel32.WaitForSingleObject(
                ctypes.c_void_p(self.handle), ctypes.c_uint32(milliseconds)
            )
        )
        if observed == self._WAIT_TIMEOUT:
            return None, True
        if observed != self._WAIT_OBJECT_0:
            raise OSError(observed, "WaitForSingleObject(worker) devolvió estado inesperado")
        exit_code = ctypes.c_uint32()
        if not self._kernel32.GetExitCodeProcess(
            ctypes.c_void_p(self.handle), ctypes.byref(exit_code)
        ):
            code = ctypes.get_last_error()
            raise OSError(code, "GetExitCodeProcess falló")
        return int(exit_code.value), False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._kernel32.CloseHandle(ctypes.c_void_p(self.handle))


def _expected_effective_limits(backend: str, requested: dict[str, int | float]) -> dict[str, Any]:
    memory_bytes = int(requested["memory_bytes"])
    cpu_seconds = int(requested["cpu_seconds"])
    if backend == "windows_job_object":
        return {
            "limit_flags": (
                _WindowsJob._JOB_OBJECT_LIMIT_JOB_TIME
                | _WindowsJob._JOB_OBJECT_LIMIT_JOB_MEMORY
                | _WindowsJob._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ),
            "job_memory_commit_limit_bytes": memory_bytes,
            "job_user_time_limit_100ns": cpu_seconds * 10_000_000,
            "kill_on_job_close": True,
            "end_of_job_time_action": "terminate",
        }
    if backend == "posix_rlimit_process_group":
        return {
            "rlimit_as_soft_bytes": memory_bytes,
            "rlimit_as_hard_bytes": memory_bytes,
            "rlimit_cpu_soft_seconds": cpu_seconds,
            "rlimit_cpu_hard_seconds": cpu_seconds + 1,
            "session_leader": True,
            "process_group_is_pid": True,
        }
    raise RuntimeError(f"backend de supervisor desconocido: {backend}")


def _limit_semantics(backend: str) -> dict[str, str]:
    if backend == "windows_job_object":
        return {
            "memory": "job_wide_committed_memory",
            "cpu": "job_wide_user_time_periodically_enforced_may_overshoot",
            "wall": "supervisor_monotonic_deadline",
            "tree": "job_object_kill_on_close",
            "peak_rss": "working_set_separate_from_committed_memory",
        }
    return {
        "memory": "per_process_virtual_address_space_inherited_by_descendants",
        "cpu": "per_process_cpu_time_inherited_by_descendants",
        "wall": "supervisor_monotonic_deadline",
        "tree": "new_session_process_group_killpg",
        "peak_rss": "resident_set_separate_from_virtual_address_space",
    }


def _apply_posix_limits(requested: dict[str, int | float]) -> dict[str, Any]:
    if os.name != "posix":
        raise RuntimeError("RLIMIT solicitado fuera de POSIX")
    resource_module: Any = __import__("resource")
    posix_os: Any = os

    memory_bytes = int(requested["memory_bytes"])
    cpu_seconds = int(requested["cpu_seconds"])
    resource_module.setrlimit(resource_module.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource_module.setrlimit(resource_module.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    as_soft, as_hard = resource_module.getrlimit(resource_module.RLIMIT_AS)
    cpu_soft, cpu_hard = resource_module.getrlimit(resource_module.RLIMIT_CPU)
    pid = os.getpid()
    return {
        "rlimit_as_soft_bytes": int(as_soft),
        "rlimit_as_hard_bytes": int(as_hard),
        "rlimit_cpu_soft_seconds": int(cpu_soft),
        "rlimit_cpu_hard_seconds": int(cpu_hard),
        "session_leader": bool(posix_os.getsid(0) == pid),
        "process_group_is_pid": bool(posix_os.getpgrp() == pid),
    }


def _returncode_evidence(returncode: int | None) -> dict[str, Any]:
    if returncode is None:
        return {
            "raw": None,
            "signed": None,
            "uint32": None,
            "hex_uint32": None,
            "signal": None,
        }
    unsigned = returncode & 0xFFFFFFFF
    signed = (
        unsigned - 0x1_0000_0000
        if sys.platform == "win32" and unsigned >= 0x8000_0000
        else returncode
    )
    return {
        "raw": returncode,
        "signed": signed,
        "uint32": unsigned,
        "hex_uint32": f"0x{unsigned:08X}",
        "signal": -returncode if os.name == "posix" and returncode < 0 else None,
    }


def _wait_for_json(
    path: Path,
    *,
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
    allow_launcher_exit: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return _read_json_object(path)
        if not allow_launcher_exit and process.poll() is not None:
            raise RuntimeError(
                f"el worker terminó antes del handshake: returncode={process.returncode}"
            )
        time.sleep(0.01)
    raise TimeoutError(f"timeout esperando handshake: {path.name}")


def _posix_rusage_evidence(usage: Any) -> dict[str, Any]:
    max_rss = int(usage.ru_maxrss)
    peak_rss = max_rss if sys.platform == "darwin" else max_rss * 1024
    return {
        "source": "wait4_rusage_worker",
        "user_seconds": round(float(usage.ru_utime), 6),
        "system_seconds": round(float(usage.ru_stime), 6),
        "peak_rss_bytes": peak_rss,
        "minor_page_faults": int(usage.ru_minflt),
        "major_page_faults": int(usage.ru_majflt),
        "voluntary_context_switches": int(usage.ru_nvcsw),
        "involuntary_context_switches": int(usage.ru_nivcsw),
    }


def _wait_worker(
    process: subprocess.Popen[bytes], *, timeout_seconds: float
) -> tuple[int | None, dict[str, Any] | None, bool]:
    if os.name != "posix":
        try:
            return process.wait(timeout=timeout_seconds), None, False
        except subprocess.TimeoutExpired:
            return None, None, True

    if process.returncode is not None:
        return process.returncode, None, False
    posix_os: Any = os
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        waited_pid, status, usage = posix_os.wait4(process.pid, posix_os.WNOHANG)
        if waited_pid == process.pid:
            returncode = os.waitstatus_to_exitcode(status)
            process.returncode = returncode
            return returncode, _posix_rusage_evidence(usage), False
        time.sleep(0.01)
    return None, None, True


def _posix_group_alive(pgid: int) -> bool:
    posix_os: Any = os
    try:
        posix_os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_posix_group_empty(pgid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _posix_group_alive(pgid):
            return True
        time.sleep(0.01)
    return not _posix_group_alive(pgid)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        synchronize = 0x00100000
        raw_handle = kernel32.OpenProcess(synchronize, False, pid)
        if not raw_handle:
            return False
        handle = int(raw_handle)
        try:
            return int(kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0)) == 258
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _command_text(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value or None


def _hardware(workdir: Path) -> dict[str, Any]:
    logical = os.cpu_count() or 0
    physical: int | None = None
    cpu_model: str | None = None
    power_scheme: str | None = None
    if sys.platform == "win32":
        raw = _command_text(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$c=Get-CimInstance Win32_Processor | Select-Object -First 1 "
                    "Name,NumberOfCores,NumberOfLogicalProcessors; $c|ConvertTo-Json -Compress"
                ),
            ]
        )
        if raw:
            try:
                cpu = json.loads(raw)
                cpu_model = str(cpu["Name"]).strip()
                physical = int(cpu["NumberOfCores"])
                logical = int(cpu["NumberOfLogicalProcessors"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
        power_scheme = _command_text(["powercfg", "/getactivescheme"])
    elif sys.platform == "darwin":
        cpu_model = _command_text(["sysctl", "-n", "machdep.cpu.brand_string"])
        raw_physical = _command_text(["sysctl", "-n", "hw.physicalcpu"])
        if raw_physical and raw_physical.isdigit():
            physical = int(raw_physical)
    elif Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    memory = _total_memory_bytes()
    disk = shutil.disk_usage(workdir)
    return {
        "cpu_model": cpu_model or platform.processor() or "desconocido",
        "physical_cores": physical,
        "logical_cpus": logical,
        "memory_bytes": memory,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "power_scheme": power_scheme,
        "disk_total_bytes": disk.total,
        "disk_free_bytes_before": disk.free,
    }


def _installed_tree_hash(distribution: Any) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-tree.v1\0")
    selected = sorted(
        file for file in (distribution.files or ()) if file.parts and file.parts[0] == "nikodym"
    )
    if not selected:
        raise RuntimeError("la distribución instalada no enumera archivos nikodym")
    for relative in selected:
        path = Path(distribution.locate_file(relative))
        if not path.is_file():
            raise RuntimeError(f"archivo instalado ausente: {relative}")
        digest.update(str(relative).replace("\\", "/").encode() + b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _wheel_tree_hash(wheel: Path) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-tree.v1\0")
    with zipfile.ZipFile(wheel) as archive:
        selected = sorted(
            name
            for name in archive.namelist()
            if name.startswith("nikodym/") and not name.endswith("/")
        )
        if not selected:
            raise RuntimeError("el wheel no contiene el paquete nikodym")
        for relative in selected:
            digest.update(relative.encode() + b"\0")
            digest.update(hashlib.sha256(archive.read(relative)).digest())
    return digest.hexdigest()


def _wheel_metadata_hash(wheel: Path) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-metadata.v1\0")
    with zipfile.ZipFile(wheel) as archive:
        selected: list[tuple[str, str]] = []
        for name in archive.namelist():
            if ".dist-info/" not in name or name.endswith("/"):
                continue
            tail = name.split(".dist-info/", 1)[1]
            if tail in {"METADATA", "WHEEL", "entry_points.txt"} or tail.startswith("licenses/"):
                selected.append((tail, name))
        if not any(tail == "METADATA" for tail, _ in selected):
            raise RuntimeError("el wheel no contiene METADATA verificable")
        for tail, name in sorted(selected):
            digest.update(f"dist-info/{tail}".encode() + b"\0")
            digest.update(hashlib.sha256(archive.read(name)).digest())
    return digest.hexdigest()


def _installed_metadata_hash(distribution: Any) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-metadata.v1\0")
    selected: list[tuple[str, Path]] = []
    for relative in distribution.files or ():
        normalized = str(relative).replace("\\", "/")
        if ".dist-info/" not in normalized:
            continue
        tail = normalized.split(".dist-info/", 1)[1]
        if tail in {"METADATA", "WHEEL", "entry_points.txt"} or tail.startswith("licenses/"):
            path = Path(distribution.locate_file(relative))
            if path.is_file():
                selected.append((tail, path))
    if not any(tail == "METADATA" for tail, _ in selected):
        raise RuntimeError("la instalación no expone METADATA verificable")
    for tail, path in sorted(selected):
        digest.update(f"dist-info/{tail}".encode() + b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _cleanroom_identity(wheel: Path, sdist: Path, *, source_sha: str) -> dict[str, Any]:
    from importlib import metadata

    import nikodym
    from nikodym.core.build import (
        build_uv_lock_hash,
        installed_distribution_hash,
        runtime_environment_hash,
    )

    module = Path(nikodym.__file__).resolve()
    checkout_sha = _command_text(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    checkout_status = _command_text(["git", "-C", str(ROOT), "status", "--porcelain"])
    if checkout_sha != source_sha:
        raise RuntimeError(
            f"driver no proviene del SHA declarado: checkout={checkout_sha}, source={source_sha}"
        )
    if checkout_status:
        raise RuntimeError("el checkout del driver no está limpio")
    cwd = Path.cwd().resolve()
    if cwd.is_relative_to(ROOT):
        raise RuntimeError(f"el cwd clean-room quedó dentro del checkout: {cwd}")
    raw_pythonpath = os.environ.get("PYTHONPATH", "")
    if raw_pythonpath:
        raise RuntimeError("clean-room requiere PYTHONPATH vacío")
    if module.is_relative_to(ROOT):
        raise RuntimeError(f"clean-room importó Nikodym desde el checkout: {module}")
    if "site-packages" not in module.parts:
        raise RuntimeError(f"Nikodym no se resolvió desde site-packages: {module}")
    distribution = metadata.distribution("nikodym")
    expected_sdist_name = f"nikodym-{distribution.version}.tar.gz"
    if sdist.name != expected_sdist_name:
        raise RuntimeError(
            f"sdist no corresponde a la versión instalada: {sdist.name} != {expected_sdist_name}"
        )
    wheel_tree_hash = _wheel_tree_hash(wheel)
    installed_tree_hash = _installed_tree_hash(distribution)
    if wheel_tree_hash != installed_tree_hash:
        raise RuntimeError("el árbol instalado no coincide byte a byte con el wheel declarado")
    wheel_metadata_hash = _wheel_metadata_hash(wheel)
    installed_metadata_hash = _installed_metadata_hash(distribution)
    if wheel_metadata_hash != installed_metadata_hash:
        raise RuntimeError("la metadata instalada no coincide byte a byte con el wheel declarado")
    return {
        "wheel_name": wheel.name,
        "wheel_bytes": wheel.stat().st_size,
        "wheel_sha256": _sha256(wheel),
        "sdist_name": sdist.name,
        "sdist_bytes": sdist.stat().st_size,
        "sdist_sha256": _sha256(sdist),
        "nikodym_version": distribution.version,
        "nikodym_file": str(module),
        "wheel_tree_hash": wheel_tree_hash,
        "installed_tree_hash": installed_tree_hash,
        "installed_matches_wheel": True,
        "wheel_metadata_hash": wheel_metadata_hash,
        "installed_metadata_hash": installed_metadata_hash,
        "metadata_matches_wheel": True,
        "installed_distribution_hash": installed_distribution_hash(),
        "checkout_sha": checkout_sha,
        "checkout_clean": True,
        "cwd": str(cwd),
        "pythonpath_empty": True,
        "uv_lock_hash": build_uv_lock_hash(),
        "runtime_environment_hash": runtime_environment_hash(),
    }


def _validate_external_workdir(workdir: Path) -> Path:
    """Impide que el driver o el consumidor usen el checkout como área de trabajo."""
    resolved = workdir.resolve()
    if resolved.is_relative_to(ROOT):
        raise RuntimeError(f"el workdir clean-room quedó dentro del checkout: {resolved}")
    return resolved


def _schema_column(name: str, *, dtype: str = "int") -> dict[str, Any]:
    return {
        "name": name,
        "dtype": dtype,
        "nullable": False,
        "required": True,
        "coerce": True,
        "ge": None,
        "le": None,
        "isin": None,
        "unique": False,
    }


def _training_frame(profile: dict[str, int]) -> Any:
    import numpy as np
    import pandas as pd

    rows = profile["train_rows"]
    cardinality = profile["cardinality"]
    rng = np.random.default_rng(30_001)
    columns: dict[str, Any] = {}
    for position in range(profile["variables"]):
        if position == 0:
            ordinary = max(cardinality - 1, 1)
            values = (np.arange(rows, dtype="int64") % ordinary).astype("int32")
            special_support = min(100, rows - ordinary)
            if special_support < 2:
                raise RuntimeError("el perfil no permite soporte special con ambas clases")
            values[:special_support] = -88888
        else:
            values = rng.integers(0, cardinality, size=rows, dtype="int32")
        columns[f"x_{position:03d}"] = values
    bad_noise = rng.random(rows)
    bad_probability = np.where((columns["x_000"] % 100) < 12, 0.20, 0.04)
    bad_flag = (bad_noise < bad_probability).astype("int8")
    bad_flag[:special_support] = np.arange(special_support, dtype="int8") % 2
    columns["bad_flag"] = bad_flag
    occurrence_cycle = (np.arange(rows, dtype="int64") // ordinary) % 10
    columns["sample_split"] = np.where(
        occurrence_cycle < 7,
        "DEV",
        np.where(occurrence_cycle < 9, "HOLDOUT", "OOT"),
    )
    return pd.DataFrame(columns, index=pd.RangeIndex(rows, name="row_id"), copy=False)


def _config(profile: dict[str, int], *, report_dir: Path) -> Any:
    from nikodym.core.config import NikodymConfig
    from nikodym.core.config.schema import cargar_configs_de_dominio
    from nikodym.ui.presets import standard_preset

    cargar_configs_de_dominio()
    raw = standard_preset()["config"]
    features = [f"x_{position:03d}" for position in range(profile["variables"])]
    raw["run"]["steps"] = [
        "data",
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
        "report",
    ]
    raw["data"]["schema"]["columns"] = [
        *[_schema_column(feature) for feature in features],
        _schema_column("bad_flag"),
        _schema_column("sample_split", dtype="str"),
    ]
    raw["data"]["schema"]["index_col"] = "row_id"
    raw["data"]["missing"]["special_values"] = [
        {
            "columns": ["x_000"],
            "sentinels": [-88888],
            "label": "special_supported",
        },
        {"columns": ["x_001"], "sentinels": [-99999], "label": "special_apply_only"},
    ]
    raw["data"]["partition"] = {
        "strategy": {
            "type": "columna",
            "partition_col": "sample_split",
            "desarrollo": ["DEV"],
            "holdout": ["HOLDOUT"],
            "oot": ["OOT"],
        },
        "ttd_includes_excluded": True,
        "min_bads_per_partition": 30,
    }
    raw["binning"]["feature_columns"] = features
    raw["binning"]["categorical_columns"] = ["x_000"]
    raw["binning"]["max_n_prebins"] = 20
    raw["binning"]["max_n_bins"] = 6
    raw["binning"]["n_jobs"] = min(os.cpu_count() or 1, profile["variables"])
    raw["selection"]["min_iv"] = 0.0
    raw["selection"]["correlation"]["enabled"] = False
    raw["selection"]["vif"]["enabled"] = False
    raw["model"]["optimizer"] = "lbfgs"
    raw["model"]["stepwise"]["enabled"] = False
    raw["report"]["output_dir"] = str(report_dir)
    raw["report"]["formats"] = ["md"]
    raw["report"]["sections"]["required_sections"] = [
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
    ]
    return NikodymConfig.model_validate(raw)


def _write_batch(path: Path, profile: dict[str, int]) -> dict[str, Any]:
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = profile["batch_rows"]
    variables = profile["variables"]
    cardinality = profile["cardinality"]
    batch_rows = min(50_000, rows)
    rng = np.random.default_rng(30_002)
    writer: Any = None
    started = time.perf_counter()
    try:
        for start in range(0, rows, batch_rows):
            size = min(batch_rows, rows - start)
            columns: dict[str, Any] = {"row_id": np.arange(start, start + size, dtype="int64")}
            for position in range(variables):
                upper = max(cardinality - 1, 1) if position == 0 else cardinality
                values = rng.integers(0, upper, size=size, dtype="int32")
                if position == 0 and start <= rows // 2 - 1 < start + size:
                    values[rows // 2 - 1 - start] = -88888
                if position == 1 and start <= rows // 2 < start + size:
                    values[rows // 2 - start] = -99999
                columns[f"x_{position:03d}"] = values
            table = pa.table(columns)
            if writer is None:
                writer = pq.ParquetWriter(  # type: ignore[no-untyped-call]
                    path, table.schema, compression="zstd"
                )
            writer.write_table(table, row_group_size=batch_rows)
    finally:
        if writer is not None:
            writer.close()
    return {
        "rows": rows,
        "variables": variables,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "write_seconds": round(time.perf_counter() - started, 6),
    }


def _verify_batch(result: Any, *, expected_rows: int, expected_features: int) -> dict[str, Any]:
    import pandas as pd
    import pyarrow.parquet as pq

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    if manifest["rows"] != expected_rows or manifest["output_hash"] != result.output_hash:
        raise RuntimeError("el manifest batch no reconcilia con el resultado")
    expected_start = 0
    output_bytes = result.manifest_path.stat().st_size
    scored = 0
    not_scorable = 0
    null_failed = 0
    supported_special_scored = 0
    for number, chunk in enumerate(manifest["chunks"]):
        if chunk["chunk"] != number or chunk["start"] != expected_start:
            raise RuntimeError(f"gap/reorden en chunk {number}")
        expected_start = int(chunk["end"])
        if chunk["input_rows"] != chunk["end"] - chunk["start"]:
            raise RuntimeError(f"rango incoherente en chunk {number}")
        for view, expected_multiplier in (
            ("application", 1),
            ("woe", 1),
            ("trace", expected_features),
        ):
            descriptor = chunk["files"][view]
            path = result.output_dir / descriptor["path"]
            metadata = pq.ParquetFile(path).metadata  # type: ignore[no-untyped-call]
            expected_view_rows = int(chunk["input_rows"]) * expected_multiplier
            if (
                descriptor["sha256"] != _sha256(path)
                or descriptor["bytes"] != path.stat().st_size
                or descriptor["rows"] != expected_view_rows
                or metadata.num_rows != expected_view_rows
            ):
                raise RuntimeError(f"artefacto {view}/{number} no reconcilia")
            output_bytes += path.stat().st_size
        application_path = result.output_dir / chunk["files"]["application"]["path"]
        application = pd.read_parquet(
            application_path,
            columns=[
                "input_position",
                "scoring_status",
                "not_scorable_reason",
                "linear_predictor",
                "eta",
                "pd_raw",
                "score_unrounded",
                "score",
                "pd_calibrated",
            ],
        )
        positions = application["input_position"].to_numpy()
        if positions[0] != chunk["start"] or positions[-1] != chunk["end"] - 1:
            raise RuntimeError(f"posición física incoherente en chunk {number}")
        failures = application["scoring_status"].eq("not_scorable")
        scored += int((~failures).sum())
        not_scorable += int(failures.sum())
        if failures.any():
            null_failed += int(
                application.loc[
                    failures,
                    [
                        "linear_predictor",
                        "eta",
                        "pd_raw",
                        "score_unrounded",
                        "score",
                        "pd_calibrated",
                    ],
                ]
                .isna()
                .all(axis=1)
                .sum()
            )
            if (
                not application.loc[failures, "not_scorable_reason"]
                .str.contains("special_sin_soporte_en_fit")
                .all()
            ):
                raise RuntimeError("el special no soportado perdió su motivo estructurado")
        supported_position = expected_rows // 2 - 1
        supported = application["input_position"].eq(supported_position)
        if supported.any():
            numeric = application.loc[
                supported,
                [
                    "linear_predictor",
                    "eta",
                    "pd_raw",
                    "score_unrounded",
                    "score",
                    "pd_calibrated",
                ],
            ]
            trace_path = result.output_dir / chunk["files"]["trace"]["path"]
            trace = pd.read_parquet(
                trace_path,
                columns=["input_position", "feature", "raw_state", "bin_id"],
            )
            trace_special = trace.loc[
                trace["input_position"].eq(supported_position) & trace["feature"].eq("x_000")
            ]
            if (
                application.loc[supported, "scoring_status"].eq("scored").all()
                and numeric.notna().all(axis=None)
                and len(trace_special.index) == 1
                and trace_special["raw_state"].eq("special").all()
                and trace_special["bin_id"].notna().all()
            ):
                supported_special_scored += 1
    if expected_start != expected_rows or scored + not_scorable != expected_rows:
        raise RuntimeError("la salida batch no conserva una fila por entrada")
    if not_scorable != 1 or null_failed != 1 or supported_special_scored != 1:
        raise RuntimeError(
            "se esperaba un -88888 soportado y un -99999 no puntuable; "
            f"observado={supported_special_scored}/{not_scorable}/{null_failed}"
        )
    return {
        "chunks": len(manifest["chunks"]),
        "output_bytes": output_bytes,
        "scored_rows": scored,
        "not_scorable_rows": not_scorable,
        "supported_special_scored": True,
        "input_hash": result.input_hash,
        "output_hash": result.output_hash,
        "ranges_contiguous": True,
        "physical_hashes_verified": True,
    }


def _semantic_hash(bundle: Any, frame: Any, chunk_size: int) -> str:
    from pandas.util import hash_pandas_object

    digest = hashlib.sha256(b"nikodym.batch.output.v1\0")
    rows = len(frame.index)
    for start in range(0, rows, chunk_size):
        result = bundle.apply(frame.iloc[start : start + chunk_size])
        application = result.application_frame.copy(deep=False)
        application["input_position"] += start
        for column in application.select_dtypes(include="object").columns:
            if application[column].map(lambda value: isinstance(value, list | dict | tuple)).any():
                application[column] = application[column].map(
                    lambda value: (
                        _canonical_json(value).decode("utf-8")
                        if isinstance(value, list | dict | tuple)
                        else value
                    )
                )
        hashes = hash_pandas_object(
            application,
            index=False,
            encoding="utf8",
            hash_key="0123456789123456",
            categorize=True,
        ).to_numpy(dtype="<u8", copy=True)
        digest.update(hashes.tobytes())
    return digest.hexdigest()


def _s0_chunk_equivalence(bundle: Any, batch_path: Path, expected: str) -> dict[str, Any]:
    import pandas as pd

    frame = pd.read_parquet(batch_path).set_index("row_id", drop=False)
    hashes = {str(size): _semantic_hash(bundle, frame, size) for size in (257, 4_096, len(frame))}
    prefix = frame.iloc[:257]
    prefix_hashes = {str(size): _semantic_hash(bundle, prefix, size) for size in (1, 257)}
    if set(hashes.values()) != {expected} or len(set(prefix_hashes.values())) != 1:
        raise RuntimeError("la salida semántica cambia al variar chunks 1/257/4096/full")
    return {"full_input_hashes": hashes, "chunk_1_prefix_257_hashes": prefix_hashes}


def _negative_contracts(
    bundle: Any, bundle_path: Path, sample: Any, workdir: Path
) -> dict[str, Any]:
    from unittest.mock import patch

    from nikodym.binning.transformer import WoEBinner
    from nikodym.calibration.calibrator import PDCalibrator
    from nikodym.scorecard.bundle import FittedScorecardBundle
    from nikodym.scorecard.exceptions import ScorecardBundleError
    from nikodym.scorecard.scaler import PointsScaler

    def explode(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("apply intentó refit")

    with (
        patch.object(WoEBinner, "fit", explode),
        patch.object(PDCalibrator, "fit", explode),
        patch.object(PointsScaler, "fit", explode),
    ):
        bundle.apply(sample.iloc[:2])
    incomplete = workdir / "bundle-incompleto"
    shutil.copytree(bundle_path, incomplete)
    (incomplete / "bins.parquet").unlink()
    try:
        FittedScorecardBundle.load(incomplete)
    except ScorecardBundleError:
        incomplete_rejected = True
    else:
        incomplete_rejected = False
    if not incomplete_rejected:
        raise RuntimeError("un bundle incompleto fue aceptado")
    return {"anti_refit_spies": True, "incomplete_bundle_rejected": True}


async def _body_case(limit: int, *, declared: int | None, sent: int) -> dict[str, Any]:
    from fastapi import FastAPI, Request
    from starlette.responses import JSONResponse

    from nikodym.ui.security import install_body_limit
    from nikodym.ui.settings import UiConfig

    app = FastAPI()
    consumed = 0

    async def sink(request: Any) -> JSONResponse:
        nonlocal consumed
        async for chunk in request.stream():
            consumed += len(chunk)
        return JSONResponse({"consumed": consumed})

    sink.__annotations__["request"] = Request
    app.post("/")(sink)

    install_body_limit(
        app,
        UiConfig(
            deploy_mode="local",
            theme="auto",
            upload_max_mb=limit // MIB,
            workdir=str(Path.cwd() / ".nikodym-ui-limit"),
            exposed_sections=(),
            allow_live_execution=True,
        ),
    )
    requested = 0
    responses: list[dict[str, Any]] = []
    remaining = sent

    async def receive() -> dict[str, Any]:
        nonlocal requested, remaining
        requested += 1
        size = min(MIB, remaining)
        remaining -= size
        return {
            "type": "http.request",
            "body": b"x" * size,
            "more_body": remaining > 0,
        }

    async def send(message: dict[str, Any]) -> None:
        responses.append(message)

    headers = [(b"content-type", b"application/octet-stream")]
    if declared is not None:
        headers.append((b"content-length", str(declared).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 2),
    }
    await app(scope, receive, send)  # type: ignore[arg-type]
    status = [
        message["status"] for message in responses if message["type"] == "http.response.start"
    ]
    return {"status": status[0], "receive_calls": requested, "downstream_bytes": consumed}


def _ui_body_limit() -> dict[str, Any]:
    limit = 100 * MIB
    cases = {
        "content_length_n_minus_1": asyncio.run(
            _body_case(limit, declared=limit - 1, sent=limit - 1)
        ),
        "content_length_n": asyncio.run(_body_case(limit, declared=limit, sent=limit)),
        "content_length_n_plus_1": asyncio.run(
            _body_case(limit, declared=limit + 1, sent=limit + 1)
        ),
        "chunked_n_plus_1": asyncio.run(_body_case(limit, declared=None, sent=limit + 1)),
    }
    if cases["content_length_n_minus_1"]["status"] != 200:
        raise RuntimeError("N-1 fue rechazado")
    if cases["content_length_n"]["status"] != 200:
        raise RuntimeError("N fue rechazado")
    if cases["content_length_n_plus_1"] != {
        "status": 422,
        "receive_calls": 0,
        "downstream_bytes": 0,
    }:
        raise RuntimeError("Content-Length N+1 no fue rechazado antes del consumidor")
    chunked = cases["chunked_n_plus_1"]
    if chunked["status"] != 422 or chunked["downstream_bytes"] != limit:
        raise RuntimeError("chunked N+1 no cortó antes de entregar el byte N+1")
    return {"limit_bytes": limit, "cases": cases}


def _consume_request(request_path: Path) -> dict[str, Any]:
    """CR-02: load/apply/batch en un consumidor nuevo que sólo importa el wheel instalado."""
    import pandas as pd

    import nikodym
    from nikodym.scorecard.bundle import FittedScorecardBundle

    module = Path(nikodym.__file__).resolve()
    if module.is_relative_to(ROOT) or "site-packages" not in module.parts:
        raise RuntimeError(f"el consumidor resolvió Nikodym fuera de site-packages: {module}")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    bundle_path = Path(request["bundle_path"])
    sample_path = Path(request["sample_path"])
    source = Path(request["batch_source"])
    output_dir = Path(request["batch_output"])
    profile = request["profile"]
    loaded = FittedScorecardBundle.load(bundle_path)
    sample = pd.read_parquet(sample_path)

    started = time.perf_counter()
    cold = loaded.apply(sample)
    cold_seconds = time.perf_counter() - started
    started = time.perf_counter()
    hot = loaded.apply(sample)
    hot_seconds = time.perf_counter() - started
    pd.testing.assert_frame_equal(cold.application_frame, hot.application_frame)
    if cold.summary["input_rows"] != len(sample) or cold.summary["not_scorable_rows"] != 0:
        raise RuntimeError("apply limpio no conservó/puntuó todas las filas")
    first_application = cold.application_frame.iloc[0]
    first_trace = cold.trace_frame.loc[
        cold.trace_frame["input_position"].eq(0) & cold.trace_frame["feature"].eq("x_000")
    ]
    supported_special_scored = bool(
        first_application["scoring_status"] == "scored"
        and first_application[
            ["linear_predictor", "eta", "pd_raw", "score_unrounded", "score", "pd_calibrated"]
        ]
        .notna()
        .all()
        and len(first_trace.index) == 1
        and first_trace["raw_state"].eq("special").all()
        and first_trace["bin_id"].notna().all()
    )
    if not supported_special_scored:
        raise RuntimeError("CR-02 no puntuó el special con soporte congelado")
    negatives = _negative_contracts(loaded, bundle_path, sample, request_path.parent)

    started = time.perf_counter()
    batch = loaded.apply_file(
        source,
        output_dir,
        chunk_size=int(profile["batch_chunk_size"]),
        id_column="row_id",
    )
    batch_seconds = time.perf_counter() - started
    final_features = len(loaded.manifest["model"]["features"])
    verified = _verify_batch(
        batch,
        expected_rows=int(profile["batch_rows"]),
        expected_features=final_features,
    )
    chunk_equivalence = (
        _s0_chunk_equivalence(loaded, source, batch.output_hash)
        if request["profile_name"] == "S0-smoke"
        else None
    )
    return {
        "pid": os.getpid(),
        "nikodym_file": str(module),
        "bundle_hash": loaded.bundle_hash,
        "final_features": final_features,
        "apply": {
            "sample_rows": len(sample),
            "cold_seconds": round(cold_seconds, 6),
            "hot_seconds": round(hot_seconds, 6),
            "cold_under_2_seconds": cold_seconds <= 2.0,
            "hot_under_2_seconds": hot_seconds <= 2.0,
            "summary": dict(cold.summary),
            "supported_special_scored": True,
            "lineage": dict(cold.lineage),
            "negatives": negatives,
        },
        "batch": {
            "seconds": round(batch_seconds, 6),
            "chunk_size": int(profile["batch_chunk_size"]),
            **verified,
            "chunk_equivalence": chunk_equivalence,
        },
        "peak_rss_bytes": _peak_rss_bytes(),
    }


def _spawn_consumer(
    *,
    workdir: Path,
    bundle_path: Path,
    sample_path: Path,
    batch_source: Path,
    profile_name: str,
    profile: dict[str, int],
) -> dict[str, Any]:
    request = workdir / "consumer-request.json"
    output = workdir / "consumer-result.json"
    request.write_bytes(
        _canonical_json(
            {
                "bundle_path": str(bundle_path),
                "sample_path": str(sample_path),
                "batch_source": str(batch_source),
                "batch_output": str(workdir / "batch-output"),
                "profile_name": profile_name,
                "profile": profile,
            }
        )
        + b"\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--internal-consumer",
            str(request),
            str(output),
        ],
        cwd=workdir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=profile["batch_seconds"] + 300,
    )
    process_evidence = {
        "returncode": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
    }
    if completed.returncode != 0 or not output.is_file():
        raise RuntimeError(
            "el consumidor clean-room falló: "
            f"returncode={completed.returncode}; stderr={completed.stderr[-2_000:]}"
        )
    payload = _read_json_object(output)
    payload["process"] = process_evidence
    return payload


def _report_evidence(report_dir: Path) -> dict[str, Any]:
    files = sorted(path for path in report_dir.rglob("*") if path.is_file())
    suffixes = {path.suffix.lower() for path in files}
    if ".html" not in suffixes or ".qmd" not in suffixes:
        raise RuntimeError("CR-01 no publicó el informe HTML+QMD esperado")
    return {
        "files": [
            {
                "path": str(path.relative_to(report_dir)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
        "html_verified": True,
        "markdown_verified": True,
    }


def _run(
    profile_name: str,
    wheel: Path,
    sdist: Path,
    workdir: Path,
    source_sha: str,
) -> dict[str, Any]:
    import pandas as pd

    from nikodym.scorecard.bundle import fit_scorecard_bundle

    profile = PROFILES[profile_name]
    hardware = _hardware(workdir)
    memory = hardware["memory_bytes"] or 0
    eligible = (
        hardware["logical_cpus"] >= profile["logical_cpus"] and memory >= profile["ram_gib"] * GIB
    )
    if hardware["disk_free_bytes_before"] < profile["disk_free_gib"] * GIB:
        raise RuntimeError(
            f"disco insuficiente: requiere {profile['disk_free_gib']} GiB libres antes de medir"
        )
    identity = _cleanroom_identity(wheel, sdist, source_sha=source_sha)
    generated = _training_frame(profile)
    training_source = workdir / "training.csv"
    generated.to_csv(training_source, index=True)
    del generated
    frame = pd.read_csv(training_source, index_col="row_id")
    observed_cardinality = int(frame["x_000"].nunique())
    if observed_cardinality != profile["cardinality"]:
        raise RuntimeError(
            "el generador no materializó la cardinalidad categórica contractual: "
            f"esperado={profile['cardinality']}, observado={observed_cardinality}"
        )
    report_dir = workdir / "report"
    config = _config(profile, report_dir=report_dir)
    started = time.perf_counter()
    bundle = fit_scorecard_bundle(config, frame)
    train_seconds = time.perf_counter() - started
    bundle_path = bundle.save(workdir / "scorecard-bundle")
    targetless = frame.drop(columns=["bad_flag"])
    sample = targetless.iloc[: min(10_000, len(targetless))]
    sample_path = workdir / "consumer-sample.parquet"
    sample.to_parquet(sample_path)
    source = workdir / "portfolio.parquet"
    source_evidence = _write_batch(source, profile)
    consumer = _spawn_consumer(
        workdir=workdir,
        bundle_path=bundle_path,
        sample_path=sample_path,
        batch_source=source,
        profile_name=profile_name,
        profile=profile,
    )
    if consumer["bundle_hash"] != bundle.bundle_hash:
        raise RuntimeError("save/load en consumidor cambió el bundle_hash")
    final_features = int(consumer["final_features"])
    if final_features != profile["variables"]:
        raise RuntimeError(
            "el perfil no preservó la geometría final requerida: "
            f"esperado={profile['variables']}, observado={final_features}"
        )
    body_limit = _ui_body_limit() if profile_name == "S0-smoke" else None
    report = _report_evidence(report_dir)
    peak = max(_peak_rss_bytes(), int(consumer["peak_rss_bytes"]))
    disk_after = shutil.disk_usage(workdir).free
    budgets = {
        "train": train_seconds <= profile["train_seconds"],
        "batch": consumer["batch"]["seconds"] <= profile["batch_seconds"],
        "peak_rss": peak <= profile["peak_gib"] * GIB,
    }
    status = "pass" if eligible and all(budgets.values()) else "informative"
    if eligible and not all(budgets.values()):
        status = "fail"
    return {
        "schema_version": SCHEMA_VERSION_V1,
        "source_sha": source_sha,
        "driver_sha256": _sha256(Path(__file__)),
        "profile": profile_name,
        "profile_contract": profile,
        "profile_status": status,
        "hardware_eligible": eligible,
        "hardware": {**hardware, "disk_free_bytes_after": disk_after},
        "cleanroom": identity,
        "train": {
            "rows": profile["train_rows"],
            "variables": profile["variables"],
            "cardinality_observed": observed_cardinality,
            "categorical_cardinality_observed": observed_cardinality,
            "input_bytes_deep": int(frame.memory_usage(index=True, deep=True).sum()),
            "csv_bytes": training_source.stat().st_size,
            "csv_sha256": _sha256(training_source),
            "seconds": round(train_seconds, 6),
            "bundle_hash": bundle.bundle_hash,
            "bundle_manifest_sha256": _sha256(bundle_path / "manifest.json"),
            "bundle_rules_sha256": _sha256(bundle_path / "bins.parquet"),
            "final_features": final_features,
            "lineage_uv_lock_hash": bundle.manifest["fit_lineage"]["uv_lock_hash"],
            "lineage_runtime_environment_hash": bundle.manifest["fit_lineage"][
                "runtime_environment_hash"
            ],
            "report": report,
        },
        "apply": consumer["apply"],
        "batch_source": source_evidence,
        "batch": consumer["batch"],
        "consumer_process": {
            "pid": consumer["pid"],
            "nikodym_file": consumer["nikodym_file"],
            **consumer["process"],
        },
        "ui_body_limit": body_limit,
        "resources": {"peak_rss_bytes": peak},
        "budgets": budgets,
    }


def _run_s3_workload(
    wheel: Path,
    sdist: Path,
    workdir: Path,
    source_sha: str,
    bundle_path: Path,
) -> dict[str, Any]:
    """Hijo S3: prueba los cuatro techos H9=B sin declarar por sí mismo PASS."""
    from unittest.mock import patch

    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from nikodym.scorecard.bundle import FittedScorecardBundle, fit_scorecard_bundle
    from nikodym.scorecard.exceptions import ScorecardBundleError

    identity = _cleanroom_identity(wheel, sdist, source_sha=source_sha)

    class AcceptedPreflightError(Exception):
        pass

    def stop_before_engine(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AcceptedPreflightError

    def observed_fit(frame: Any, config: Any, *, rejection_fragment: str | None) -> str:
        try:
            with patch("nikodym.api.run", stop_before_engine):
                fit_scorecard_bundle(config, frame)
        except AcceptedPreflightError:
            if rejection_fragment is not None:
                raise RuntimeError(
                    f"N+1 fue aceptado; se esperaba rechazo con {rejection_fragment!r}"
                ) from None
            return "accepted"
        except ScorecardBundleError as exc:
            if rejection_fragment is None:
                raise RuntimeError(f"N-1/N fue rechazado por {exc}") from exc
            if rejection_fragment not in str(exc):
                raise RuntimeError(
                    "N+1 fue rechazado por una causa ajena al envelope: "
                    f"esperado={rejection_fragment!r}; observado={str(exc)!r}"
                ) from exc
            return "rejected"
        raise RuntimeError("el fit cruzó el preflight y llegó a ejecutar el motor")

    row_cases: dict[str, str] = {}
    for rows in (999_999, 1_000_000, 1_000_001):
        profile = {**PROFILES["S0-smoke"], "train_rows": rows, "variables": 1, "cardinality": 1}
        frame = pd.DataFrame(
            {"x_000": np.zeros(rows, dtype="int8"), "bad_flag": np.zeros(rows, dtype="int8")},
            index=pd.RangeIndex(rows, name="row_id"),
        )
        row_cases[str(rows)] = observed_fit(
            frame,
            _config(profile, report_dir=workdir / f"report-rows-{rows}"),
            rejection_fragment="filas=1,000,001" if rows > 1_000_000 else None,
        )

    variable_cases: dict[str, str] = {}
    for variables in (99, 100, 101):
        profile = {
            **PROFILES["S0-smoke"],
            "train_rows": 1,
            "variables": variables,
            "cardinality": 1,
        }
        frame = pd.DataFrame(
            {
                **{f"x_{position:03d}": np.zeros(1, dtype="int8") for position in range(variables)},
                "bad_flag": np.zeros(1, dtype="int8"),
            },
            index=pd.RangeIndex(1, name="row_id"),
        )
        config = _config(profile, report_dir=workdir / f"report-variables-{variables}")
        assert config.binning is not None
        config = config.model_copy(
            update={"binning": config.binning.model_copy(update={"feature_columns": "*"})}
        )
        variable_cases[str(variables)] = observed_fit(
            frame,
            config,
            rejection_fragment="variables=101" if variables > 100 else None,
        )

    cardinality_cases: dict[str, str] = {}
    for cardinality in (99_999, 100_000, 100_001):
        profile = {
            **PROFILES["S0-smoke"],
            "train_rows": cardinality,
            "variables": 1,
            "cardinality": cardinality,
        }
        frame = pd.DataFrame(
            {
                "x_000": np.arange(cardinality, dtype="int32"),
                "bad_flag": np.zeros(cardinality, dtype="int8"),
            },
            index=pd.RangeIndex(cardinality, name="row_id"),
        )
        cardinality_cases[str(cardinality)] = observed_fit(
            frame,
            _config(profile, report_dir=workdir / f"report-cardinality-{cardinality}"),
            rejection_fragment=(
                "cardinalidad de 'x_000'=100,001" if cardinality > 100_000 else None
            ),
        )

    loaded = FittedScorecardBundle.load(bundle_path)
    features = tuple(loaded.manifest["model"]["features"])
    batch_cases: dict[str, str] = {}
    for rows in (4_999_999, 5_000_000, 5_000_001):
        source = workdir / f"batch-limit-{rows}.parquet"
        writer: Any = None
        try:
            for start in range(0, rows, 100_000):
                size = min(100_000, rows - start)
                table = pa.table(
                    {
                        "row_id": np.arange(start, start + size, dtype="int64"),
                        **{feature: np.zeros(size, dtype="int8") for feature in features},
                    }
                )
                if writer is None:
                    writer = pq.ParquetWriter(  # type: ignore[no-untyped-call]
                        source, table.schema, compression="zstd"
                    )
                writer.write_table(table, row_group_size=100_000)
        finally:
            if writer is not None:
                writer.close()
        try:
            with patch.object(FittedScorecardBundle, "apply", stop_before_engine):
                loaded.apply_file(
                    source,
                    workdir / f"batch-limit-output-{rows}",
                    chunk_size=1,
                    id_column="row_id",
                )
        except AcceptedPreflightError:
            if rows > 5_000_000:
                raise RuntimeError("batch N+1 fue aceptado") from None
            batch_cases[str(rows)] = "accepted"
        except ScorecardBundleError as exc:
            if rows <= 5_000_000:
                raise RuntimeError(f"batch N-1/N fue rechazado por {exc}") from exc
            if "filas>5,000,000" not in str(exc):
                raise RuntimeError(
                    f"batch N+1 fue rechazado por una causa ajena: {str(exc)!r}"
                ) from exc
            batch_cases[str(rows)] = "rejected"
        else:
            raise RuntimeError("el batch cruzó el preflight y llegó a materializar salida")
    cases = {
        "train_rows": row_cases,
        "train_variables": variable_cases,
        "train_cardinality": cardinality_cases,
        "batch_rows": batch_cases,
    }
    if not _classification_is_exact(cases):
        raise RuntimeError(f"los límites S3 no respetan N-1/N/N+1: {cases!r}")
    return {
        "cleanroom": identity,
        "bundle_hash": loaded.bundle_hash,
        "limits": cases,
        "hardware": _hardware(workdir),
        "resources": {"peak_rss_bytes": _peak_rss_bytes()},
    }


class _LimitsNotAppliedError(RuntimeError):
    pass


class _SupervisorProtocolError(RuntimeError):
    pass


def _wait_for_child_json(path: Path, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return _read_json_object(path)
        time.sleep(0.01)
    raise TimeoutError(f"timeout del hijo esperando {path.name}")


def _run_supervisor_probe(mode: str, request: dict[str, Any]) -> dict[str, Any]:
    if mode == "probe-normal":
        return {"probe": mode, "completed": True, "peak_rss_bytes": _peak_rss_bytes()}
    if mode == "probe-wall":
        sentinel = Path(str(request["probe_sentinel_path"]))
        time.sleep(float(request["probe_delay_seconds"]))
        sentinel.write_text("wall escapó\n", encoding="utf-8")
        return {"probe": mode, "unexpected_completion": True}
    if mode == "probe-memory":
        requested = cast(dict[str, int | float], request["limits"])
        if sys.platform == "win32":
            memory_bytes = int(requested["memory_bytes"])
            ready_path = Path(str(request["probe_sentinel_path"])).with_name(
                "memory-descendant-ready.txt"
            )
            descendant_target = max(8 * MIB, int(memory_bytes * 0.45))
            parent_target = max(8 * MIB, int(memory_bytes * 0.55))
            code = "\n".join(
                [
                    "import os, pathlib, sys, time",
                    f"target = {descendant_target}",
                    "allocations = []",
                    "allocated = 0",
                    "try:",
                    "    while allocated < target:",
                    "        size = min(4 * 1024 * 1024, target - allocated)",
                    "        allocations.append(bytearray(size))",
                    "        allocated += size",
                    "except MemoryError:",
                    "    print('NIKODYM_S3_MEMORY_CHILD_EARLY', file=sys.stderr, flush=True)",
                    "    os._exit(90)",
                    f"pathlib.Path({str(ready_path)!r}).write_text('ready\\n', encoding='utf-8')",
                    "time.sleep(30.0)",
                ]
            )
            descendant = subprocess.Popen(
                [sys.executable, "-c", code],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=None,
                close_fds=True,
            )
            ready_deadline = time.monotonic() + 5.0
            while time.monotonic() < ready_deadline and not ready_path.is_file():
                if descendant.poll() is not None:
                    raise RuntimeError("el descendiente de memoria terminó antes de quedar listo")
                time.sleep(0.01)
            if not ready_path.is_file():
                raise TimeoutError("el descendiente de memoria no quedó listo")
            allocation_cap = parent_target
        else:
            allocation_cap = min(int(requested["memory_bytes"]) * 2, 512 * MIB)
        allocations: list[bytearray] = []
        allocated = 0
        try:
            while allocated < allocation_cap:
                allocations.append(bytearray(4 * MIB))
                allocated += 4 * MIB
        except MemoryError:
            print(_S3_MEMORY_MARKER, file=sys.stderr, flush=True)
            os._exit(_S3_MEMORY_EXIT_CODE)
        print("NIKODYM_S3_MEMORY_LIMIT_BYPASSED", file=sys.stderr, flush=True)
        os._exit(_S3_MEMORY_EXIT_CODE + 2)
    if mode == "probe-cpu":
        if os.name == "posix":
            posix_signal: Any = signal

            def cpu_limit_handler(signum: int, frame: Any) -> None:
                del signum, frame
                print(_S3_CPU_MARKER, file=sys.stderr, flush=True)
                os._exit(_S3_CPU_EXIT_CODE)

            signal.signal(posix_signal.SIGXCPU, cpu_limit_handler)
        accumulator = 0
        while True:
            accumulator = (accumulator * 33 + 17) & 0xFFFFFFFF
    if mode == "probe-descendant":
        sentinel = Path(str(request["probe_sentinel_path"]))
        delay = float(request["probe_delay_seconds"])
        code = (
            "import pathlib,time;"
            f"time.sleep({delay!r});"
            f"pathlib.Path({str(sentinel)!r}).write_text('orphan\\n',encoding='utf-8')"
        )
        descendant = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return {
            "probe": mode,
            "descendant_pid": descendant.pid,
            "sentinel_path": str(sentinel),
            "sentinel_delay_seconds": delay,
            "peak_rss_bytes": _peak_rss_bytes(),
        }
    raise RuntimeError(f"probe de supervisor desconocido: {mode}")


def _run_supervised_child(request_path: Path) -> int:
    request = _read_json_object(request_path)
    protocol = str(request.get("protocol_version"))
    nonce = str(request.get("nonce"))
    backend = str(request.get("backend"))
    limits = cast(dict[str, int | float], request["limits"])
    boot_path = Path(str(request["boot_path"]))
    ready_path = Path(str(request["ready_path"]))
    started_path = Path(str(request["started_path"]))
    start_path = Path(str(request["start_path"]))
    result_path = Path(str(request["result_path"]))
    handshake_seconds = float(limits["handshake_seconds"])
    driver_hash = _sha256(Path(__file__))
    pid = os.getpid()
    try:
        if protocol != S3_PROTOCOL_VERSION:
            raise _SupervisorProtocolError(f"protocolo inesperado: {protocol}")
        _write_json_exclusive(
            boot_path,
            {
                "protocol_version": S3_PROTOCOL_VERSION,
                "nonce": nonce,
                "worker_pid": pid,
                "driver_sha256": driver_hash,
                "heavy_work_started": False,
            },
        )
        if backend == "posix_rlimit_process_group":
            effective_limits = _apply_posix_limits(limits)
        elif backend == "windows_job_object":
            authorization = _wait_for_child_json(
                Path(str(request["authorization_path"])),
                timeout_seconds=handshake_seconds,
            )
            if authorization.get("nonce") != nonce or authorization.get("worker_pid") != pid:
                raise _SupervisorProtocolError("autorización Windows no reconcilia")
            raw_effective = authorization.get("effective_limits")
            if not isinstance(raw_effective, dict):
                raise _SupervisorProtocolError("autorización Windows sin límites efectivos")
            effective_limits = cast(dict[str, Any], raw_effective)
        else:
            raise _SupervisorProtocolError(f"backend desconocido: {backend}")

        start_token_absent_when_limits_applied = not start_path.exists()
        limits_applied_ns = time.monotonic_ns()
        _write_json_exclusive(
            ready_path,
            {
                "protocol_version": S3_PROTOCOL_VERSION,
                "nonce": nonce,
                "backend": backend,
                "worker_pid": pid,
                "driver_sha256": driver_hash,
                "effective_limits": effective_limits,
                "limits_applied_monotonic_ns": limits_applied_ns,
                "start_token_absent_when_limits_applied": (start_token_absent_when_limits_applied),
                "heavy_work_started": False,
            },
        )
        start = _wait_for_child_json(start_path, timeout_seconds=handshake_seconds)
        if start.get("nonce") != nonce or start.get("worker_pid") != pid:
            raise _SupervisorProtocolError("token START no reconcilia")
        start_observed_ns = time.monotonic_ns()
        _write_json_exclusive(
            started_path,
            {
                "protocol_version": S3_PROTOCOL_VERSION,
                "nonce": nonce,
                "worker_pid": pid,
                "start_token_observed_monotonic_ns": start_observed_ns,
                "limits_applied_before_start": bool(
                    start_token_absent_when_limits_applied
                    and limits_applied_ns <= start_observed_ns
                ),
            },
        )

        mode = str(request["mode"])
        if mode == "s3":
            workload = cast(dict[str, Any], request["workload"])
            payload = _run_s3_workload(
                Path(str(workload["wheel"])),
                Path(str(workload["sdist"])),
                Path(str(workload["workdir"])),
                str(workload["source_sha"]),
                Path(str(workload["bundle_path"])),
            )
        else:
            payload = _run_supervisor_probe(mode, request)
        result = {
            "protocol_version": S3_PROTOCOL_VERSION,
            "nonce": nonce,
            "worker_pid": pid,
            "driver_sha256": driver_hash,
            "status": "ok",
            "payload": payload,
            "start_token_observed_monotonic_ns": start_observed_ns,
        }
        _write_json_exclusive(result_path, result)
        print(json.dumps({"status": "ok", "worker_pid": pid}, sort_keys=True))
        return 0
    except MemoryError:
        print(_S3_MEMORY_MARKER, file=sys.stderr, flush=True)
        os._exit(_S3_MEMORY_EXIT_CODE)
    except Exception as exc:
        error_payload = {
            "protocol_version": S3_PROTOCOL_VERSION,
            "nonce": nonce,
            "worker_pid": pid,
            "driver_sha256": driver_hash,
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        if not result_path.exists():
            _write_json_exclusive(result_path, error_payload)
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


def _classify_supervisor_outcome(
    *,
    mode: str,
    returncode: int | None,
    timed_out: bool,
    protocol_outcome: str | None,
    stderr_tail: str,
    backend: str,
    accounting: dict[str, Any] | None,
    requested_limits: dict[str, int | float],
    child_result: dict[str, Any] | None,
    windows_job_signaled: bool,
) -> str:
    if protocol_outcome is not None:
        return protocol_outcome
    if timed_out:
        return "wall_timeout"
    if returncode == _S3_MEMORY_EXIT_CODE and _S3_MEMORY_MARKER in stderr_tail:
        if backend != "windows_job_object":
            return "memory_limit"
        if accounting is not None:
            peak_commit = int(accounting["peak_job_memory_commit_bytes"])
            memory_limit = int(requested_limits["memory_bytes"])
            total_processes = int(accounting["total_processes"])
            minimum_processes = 3 if mode == "probe-memory" else 1
            if peak_commit >= int(memory_limit * 0.70) and total_processes >= minimum_processes:
                return "memory_limit"
    if backend == "posix_rlimit_process_group" and returncode is not None:
        posix_signal: Any = signal
        cpu_signals = {int(posix_signal.SIGXCPU), int(posix_signal.SIGKILL)}
        if returncode == _S3_CPU_EXIT_CODE and _S3_CPU_MARKER in stderr_tail:
            return "cpu_limit"
        if returncode < 0 and -returncode in cpu_signals and accounting is not None:
            consumed = float(accounting["user_seconds"]) + float(accounting["system_seconds"])
            if consumed >= max(int(requested_limits["cpu_seconds"]) - 0.25, 0.0):
                return "cpu_limit"
    if backend == "windows_job_object" and returncode is not None and accounting is not None:
        quota_status = (returncode & 0xFFFFFFFF) == 0xC0000044
        consumed_100ns = int(accounting["total_user_time_100ns"])
        limit_100ns = int(requested_limits["cpu_seconds"]) * 10_000_000
        if windows_job_signaled and quota_status and consumed_100ns >= int(limit_100ns * 0.8):
            return "cpu_limit"
    if returncode == 0 and child_result is not None and child_result.get("status") == "ok":
        return "normal"
    if child_result is not None and child_result.get("status") == "error":
        return "child_error"
    if returncode not in (None, 0):
        return "termination_unclassified"
    return "protocol_error"


def _supervise_child(
    *,
    mode: str,
    workdir: Path,
    limits: dict[str, int | float],
    workload: dict[str, Any] | None = None,
    probe_delay_seconds: float = 1.0,
) -> dict[str, Any]:
    _validate_external_workdir(workdir)
    if int(limits["memory_bytes"]) <= 0 or int(limits["cpu_seconds"]) <= 0:
        raise ValueError("los límites de memoria/CPU deben ser positivos")
    if float(limits["wall_seconds"]) <= 0 or float(limits["handshake_seconds"]) <= 0:
        raise ValueError("los límites de wall/handshake deben ser positivos")

    backend = "windows_job_object" if sys.platform == "win32" else "posix_rlimit_process_group"
    expected_effective = _expected_effective_limits(backend, limits)
    nonce = secrets.token_hex(32)
    control = workdir / "supervisor-control"
    control.mkdir(parents=False, exist_ok=False)
    request_path = control / "request.json"
    boot_path = control / "boot.json"
    authorization_path = control / "limits-authorized.json"
    ready_path = control / "ready.json"
    start_path = control / "start.json"
    started_path = control / "started.json"
    result_path = control / "result.json"
    stdout_path = control / "stdout.bin"
    stderr_path = control / "stderr.bin"
    sentinel_path = control / "late-sentinel.txt"
    request = {
        "protocol_version": S3_PROTOCOL_VERSION,
        "nonce": nonce,
        "backend": backend,
        "mode": mode,
        "limits": limits,
        "boot_path": str(boot_path),
        "authorization_path": str(authorization_path),
        "ready_path": str(ready_path),
        "start_path": str(start_path),
        "started_path": str(started_path),
        "result_path": str(result_path),
        "probe_sentinel_path": str(sentinel_path),
        "probe_delay_seconds": probe_delay_seconds,
        "workload": workload,
    }
    _write_json_exclusive(request_path, request)
    driver_hash_start = _sha256(Path(__file__))
    environment = dict(os.environ)
    environment["PYTHONPATH"] = ""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--internal-s3-child",
        str(request_path),
    ]
    creationflags = 0
    start_new_session = backend == "posix_rlimit_process_group"
    job: _WindowsJob | None = None
    if backend == "windows_job_object":
        job = _WindowsJob(
            memory_bytes=int(limits["memory_bytes"]),
            cpu_seconds=int(limits["cpu_seconds"]),
        )

    process: subprocess.Popen[bytes] | None = None
    worker_handle: _WindowsProcessHandle | None = None
    boot: dict[str, Any] | None = None
    worker_pid: int | None = None
    ready: dict[str, Any] | None = None
    started: dict[str, Any] | None = None
    effective_limits: dict[str, Any] | None = None
    protocol_outcome: str | None = None
    protocol_error: str | None = None
    returncode: int | None = None
    launcher_returncode: int | None = None
    timed_out = False
    accounting_before: dict[str, Any] | None = None
    accounting_after: dict[str, Any] | None = None
    windows_job_signaled = False
    posix_rusage: dict[str, Any] | None = None
    descendants_before_cleanup = False
    expected_processes_before_cleanup: int | None = None
    untracked_processes_before_cleanup: int | None = None
    cleanup_action = "none"
    supervisor_started_at = time.monotonic()
    workload_started_at: float | None = None
    workload_deadline_at: float | None = None
    workload_finished_at: float | None = None
    try:
        with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
            process = subprocess.Popen(
                command,
                cwd=workdir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                close_fds=True,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
            try:
                if job is not None:
                    job.assign(process.pid)
                boot = _wait_for_json(
                    boot_path,
                    process=process,
                    timeout_seconds=float(limits["handshake_seconds"]),
                    allow_launcher_exit=job is not None,
                )
                if (
                    boot.get("protocol_version") != S3_PROTOCOL_VERSION
                    or boot.get("nonce") != nonce
                    or boot.get("driver_sha256") != driver_hash_start
                    or boot.get("heavy_work_started") is not False
                    or not isinstance(boot.get("worker_pid"), int)
                ):
                    raise _SupervisorProtocolError("BOOT del worker no reconcilia")
                worker_pid = int(boot["worker_pid"])
                if job is None and worker_pid != process.pid:
                    raise _SupervisorProtocolError("PID POSIX difiere del líder de sesión")
                if job is not None:
                    if not job.contains(worker_pid):
                        job.assign(worker_pid)
                    effective_limits = job.effective_limits()
                    if effective_limits != expected_effective:
                        raise _LimitsNotAppliedError(
                            "los límites consultados del Job no coinciden con lo solicitado"
                        )
                    _write_json_exclusive(
                        authorization_path,
                        {
                            "protocol_version": S3_PROTOCOL_VERSION,
                            "nonce": nonce,
                            "worker_pid": worker_pid,
                            "effective_limits": effective_limits,
                        },
                    )
                    worker_handle = _WindowsProcessHandle(worker_pid)
                ready = _wait_for_json(
                    ready_path,
                    process=process,
                    timeout_seconds=float(limits["handshake_seconds"]),
                    allow_launcher_exit=job is not None,
                )
                raw_ready_limits = ready.get("effective_limits")
                if not isinstance(raw_ready_limits, dict):
                    raise _LimitsNotAppliedError("READY no contiene límites efectivos")
                effective_limits = cast(dict[str, Any], raw_ready_limits)
                if (
                    ready.get("protocol_version") != S3_PROTOCOL_VERSION
                    or ready.get("nonce") != nonce
                    or ready.get("backend") != backend
                    or ready.get("worker_pid") != worker_pid
                    or ready.get("driver_sha256") != driver_hash_start
                    or ready.get("heavy_work_started") is not False
                    or ready.get("start_token_absent_when_limits_applied") is not True
                    or effective_limits != expected_effective
                ):
                    raise _LimitsNotAppliedError("READY no atestigua los límites exactos")
                limits_verified_ns = time.monotonic_ns()
                workload_started_at = time.monotonic()
                workload_deadline_at = workload_started_at + float(limits["wall_seconds"])
                _write_json_exclusive(
                    start_path,
                    {
                        "protocol_version": S3_PROTOCOL_VERSION,
                        "nonce": nonce,
                        "worker_pid": worker_pid,
                        "limits_verified_monotonic_ns": limits_verified_ns,
                    },
                )
                started_wait_seconds = min(
                    float(limits["handshake_seconds"]),
                    max(workload_deadline_at - time.monotonic(), 0.0),
                )
                if started_wait_seconds <= 0:
                    raise TimeoutError("wall timeout antes de observar STARTED")
                started = _wait_for_json(
                    started_path,
                    process=process,
                    timeout_seconds=started_wait_seconds,
                    allow_launcher_exit=job is not None,
                )
                if (
                    started.get("nonce") != nonce
                    or started.get("worker_pid") != worker_pid
                    or started.get("limits_applied_before_start") is not True
                    or int(ready["limits_applied_monotonic_ns"])
                    > int(started["start_token_observed_monotonic_ns"])
                ):
                    raise _SupervisorProtocolError("orden READY→START inválido")
            except TimeoutError as exc:
                protocol_error = str(exc)
                if workload_deadline_at is not None and time.monotonic() >= workload_deadline_at:
                    timed_out = True
                else:
                    protocol_outcome = "handshake_timeout"
            except _LimitsNotAppliedError as exc:
                protocol_outcome = "limits_not_applied"
                protocol_error = str(exc)
            except Exception as exc:
                protocol_outcome = "protocol_error"
                protocol_error = f"{type(exc).__name__}: {exc}"

            if protocol_outcome is None and not timed_out:
                if workload_deadline_at is None:
                    raise RuntimeError("deadline wall ausente después de START")
                remaining_wall = max(workload_deadline_at - time.monotonic(), 0.0)
                if remaining_wall <= 0:
                    timed_out = True
                elif worker_handle is not None:
                    returncode, timed_out = worker_handle.wait(remaining_wall)
                else:
                    returncode, posix_rusage, timed_out = _wait_worker(
                        process,
                        timeout_seconds=remaining_wall,
                    )
            if workload_started_at is not None:
                workload_finished_at = time.monotonic()

            if job is not None and process is not None and returncode is not None:
                try:
                    launcher_returncode = process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    launcher_returncode = None
            elif job is None:
                launcher_returncode = returncode

            if job is not None:
                accounting_before = job.accounting()
                windows_job_signaled = job.is_signaled()
                active_before_cleanup = job.active_processes()
                expected_processes_before_cleanup = 0
                if worker_pid is not None and returncode is None and _pid_alive(worker_pid):
                    expected_processes_before_cleanup += 1
                if (
                    process.pid != worker_pid
                    and launcher_returncode is None
                    and _pid_alive(process.pid)
                ):
                    expected_processes_before_cleanup += 1
                untracked_processes_before_cleanup = max(
                    active_before_cleanup - expected_processes_before_cleanup, 0
                )
                descendants_before_cleanup = untracked_processes_before_cleanup > 0
                if returncode is None or job.active_processes() > 0:
                    cleanup_action = "terminate_job_object"
                    job.terminate(0xE0000001)
                    if returncode is None and worker_handle is not None:
                        returncode, cleanup_timed_out = worker_handle.wait(5.0)
                        if cleanup_timed_out:
                            protocol_outcome = protocol_outcome or "cleanup_failed"
                    if not job.wait_empty(5.0):
                        protocol_outcome = protocol_outcome or "cleanup_failed"
                try:
                    launcher_returncode = process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    protocol_outcome = protocol_outcome or "cleanup_failed"
                accounting_after = job.accounting()
            elif process is not None:
                posix_os: Any = os
                posix_signal: Any = signal
                pgid = process.pid
                descendants_before_cleanup = _posix_group_alive(pgid)
                if returncode is None or descendants_before_cleanup:
                    cleanup_action = "killpg_sigkill"
                    with contextlib.suppress(ProcessLookupError):
                        posix_os.killpg(pgid, posix_signal.SIGKILL)
                    if returncode is None:
                        returncode, posix_rusage_after, _ = _wait_worker(
                            process, timeout_seconds=5.0
                        )
                        launcher_returncode = returncode
                        if posix_rusage is None:
                            posix_rusage = posix_rusage_after
                    if not _wait_posix_group_empty(pgid, 5.0):
                        protocol_outcome = protocol_outcome or "cleanup_failed"
                accounting_before = posix_rusage
                accounting_after = posix_rusage
    finally:
        if process is not None and returncode is None:
            if job is not None:
                with contextlib.suppress(OSError):
                    job.terminate(0xE0000002)
            else:
                posix_os = cast(Any, os)
                posix_signal = cast(Any, signal)
                with contextlib.suppress(ProcessLookupError):
                    posix_os.killpg(process.pid, posix_signal.SIGKILL)
                returncode, posix_rusage_final, cleanup_timed_out = _wait_worker(
                    process, timeout_seconds=5.0
                )
                launcher_returncode = returncode
                if posix_rusage is None:
                    posix_rusage = posix_rusage_final
                if cleanup_timed_out or not _wait_posix_group_empty(process.pid, 5.0):
                    protocol_outcome = protocol_outcome or "cleanup_failed"
        if job is not None:
            job.close()
        if worker_handle is not None:
            worker_handle.close()

    child_result: dict[str, Any] | None = None
    if result_path.is_file():
        try:
            child_result = _read_json_object(result_path)
        except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError) as exc:
            protocol_outcome = protocol_outcome or "protocol_error"
            protocol_error = protocol_error or f"RESULT ilegible: {type(exc).__name__}: {exc}"
    child_result_reconciled = bool(
        child_result is not None
        and child_result.get("protocol_version") == S3_PROTOCOL_VERSION
        and child_result.get("nonce") == nonce
        and child_result.get("worker_pid") == worker_pid
        and child_result.get("driver_sha256") == driver_hash_start
        and child_result.get("status") in {"ok", "error"}
    )
    if child_result is not None and not child_result_reconciled:
        protocol_outcome = protocol_outcome or "protocol_error"
        protocol_error = protocol_error or "RESULT no reconcilia protocolo/nonce/PID/hash"
    stdout = _stream_evidence(stdout_path)
    stderr = _stream_evidence(stderr_path)
    outcome = _classify_supervisor_outcome(
        mode=mode,
        returncode=returncode,
        timed_out=timed_out,
        protocol_outcome=protocol_outcome,
        stderr_tail=str(stderr["tail_utf8"]),
        backend=backend,
        accounting=accounting_before,
        requested_limits=limits,
        child_result=child_result,
        windows_job_signaled=windows_job_signaled,
    )
    descendant_pid: int | None = None
    sentinel_delay = 0.0
    if child_result is not None and child_result.get("status") == "ok":
        raw_payload = child_result.get("payload")
        if isinstance(raw_payload, dict) and isinstance(raw_payload.get("descendant_pid"), int):
            descendant_pid = int(raw_payload["descendant_pid"])
            sentinel_delay = float(raw_payload.get("sentinel_delay_seconds", 0.0))
    if descendant_pid is not None and sentinel_delay > 0:
        time.sleep(sentinel_delay + 0.25)
    descendant_alive_after = descendant_pid is not None and _pid_alive(descendant_pid)
    if job is not None:
        tree_alive_after_cleanup = bool(
            accounting_after is not None and accounting_after["active_processes"] > 0
        )
    elif process is not None:
        tree_alive_after_cleanup = _posix_group_alive(process.pid)
    else:
        tree_alive_after_cleanup = False
    tree_cleanup_complete = (
        not tree_alive_after_cleanup and not descendant_alive_after and not sentinel_path.exists()
    )
    driver_hash_end = _sha256(Path(__file__))
    result_evidence = (
        {
            "present": True,
            "bytes": result_path.stat().st_size,
            "sha256": _sha256(result_path),
            "status": child_result.get("status") if child_result is not None else None,
            "reconciled": child_result_reconciled,
        }
        if child_result is not None
        else {
            "present": False,
            "bytes": 0,
            "sha256": None,
            "status": None,
            "reconciled": False,
        }
    )
    peak_rss: int | None = None
    if child_result is not None and child_result.get("status") == "ok":
        raw_payload = child_result.get("payload")
        if isinstance(raw_payload, dict):
            raw_resources = raw_payload.get("resources")
            if isinstance(raw_resources, dict) and isinstance(
                raw_resources.get("peak_rss_bytes"), int
            ):
                peak_rss = int(raw_resources["peak_rss_bytes"])
            elif isinstance(raw_payload.get("peak_rss_bytes"), int):
                peak_rss = int(raw_payload["peak_rss_bytes"])
    if peak_rss is None and posix_rusage is not None:
        peak_rss = int(posix_rusage["peak_rss_bytes"])
    return {
        "protocol_version": S3_PROTOCOL_VERSION,
        "backend": backend,
        "qualification_supported": sys.platform != "darwin",
        "semantics": _limit_semantics(backend),
        "supervisor_pid": os.getpid(),
        "launcher_pid": process.pid if process is not None else None,
        "worker_pid": worker_pid,
        "process_group_id": (
            process.pid if process is not None and backend == "posix_rlimit_process_group" else None
        ),
        "requested_limits": limits,
        "effective_limits": effective_limits,
        "handshake": {
            "boot": boot,
            "ready": ready,
            "started": started,
            "limits_verified_before_start": bool(
                ready is not None
                and started is not None
                and ready.get("start_token_absent_when_limits_applied") is True
                and started.get("limits_applied_before_start") is True
                and ready.get("limits_applied_monotonic_ns", 0)
                <= started.get("start_token_observed_monotonic_ns", 0)
            ),
            "error": protocol_error,
        },
        "outcome": outcome,
        "returncode": _returncode_evidence(returncode),
        "worker_returncode": _returncode_evidence(returncode),
        "launcher_returncode": _returncode_evidence(launcher_returncode),
        "supervisor_wall_seconds": round(time.monotonic() - supervisor_started_at, 6),
        "workload_wall_seconds": (
            round(workload_finished_at - workload_started_at, 6)
            if workload_started_at is not None and workload_finished_at is not None
            else None
        ),
        "accounting_before_cleanup": accounting_before,
        "accounting_after_cleanup": accounting_after,
        "windows_job_signaled": windows_job_signaled,
        "peak_rss_bytes": peak_rss,
        "stdout": stdout,
        "stderr": stderr,
        "child_result": result_evidence,
        "tree_cleanup": {
            "descendants_detected_before_cleanup": descendants_before_cleanup,
            "expected_supervised_processes_before_cleanup": (expected_processes_before_cleanup),
            "untracked_processes_before_cleanup": untracked_processes_before_cleanup,
            "action": cleanup_action,
            "descendant_pid": descendant_pid,
            "tree_alive_after_cleanup": tree_alive_after_cleanup,
            "descendant_alive_after_cleanup": descendant_alive_after,
            "late_sentinel_absent": not sentinel_path.exists(),
            "complete": tree_cleanup_complete,
        },
        "driver_sha256": {
            "parent_start": driver_hash_start,
            "child_ready": ready.get("driver_sha256") if ready is not None else None,
            "parent_end": driver_hash_end,
            "all_equal": bool(
                ready is not None
                and driver_hash_start == ready.get("driver_sha256") == driver_hash_end
            ),
        },
        "_child_payload": child_result,
    }


def _s3_pass_conditions(
    supervision: dict[str, Any], workload: dict[str, Any] | None
) -> dict[str, bool]:
    accounting_present = isinstance(
        supervision.get("accounting_before_cleanup"), dict
    ) and isinstance(supervision.get("accounting_after_cleanup"), dict)
    peak_rss = supervision.get("peak_rss_bytes")
    backend = str(supervision.get("backend"))
    requested = supervision.get("requested_limits")
    effective = supervision.get("effective_limits")
    effective_limits_exact = bool(
        isinstance(requested, dict)
        and backend in {"windows_job_object", "posix_rlimit_process_group"}
        and effective == _expected_effective_limits(backend, requested)
    )
    return {
        "normal_termination": supervision["outcome"] == "normal",
        "returncode_zero": supervision["returncode"]["signed"] == 0,
        "launcher_returncode_zero": supervision["launcher_returncode"]["signed"] == 0,
        "backend_eligible": supervision.get("qualification_supported") is True,
        "effective_limits_exact": effective_limits_exact,
        "limits_verified_before_start": supervision["handshake"]["limits_verified_before_start"]
        is True,
        "driver_hashes_equal": supervision["driver_sha256"]["all_equal"] is True,
        "child_result_reconciled": supervision["child_result"]["reconciled"] is True,
        "accounting_present": accounting_present,
        "peak_rss_present": isinstance(peak_rss, int) and peak_rss > 0,
        "tree_cleanup_complete": supervision["tree_cleanup"]["complete"] is True,
        "classification_exact": bool(
            workload is not None and _classification_is_exact(workload.get("limits"))
        ),
    }


def _supervise_s3(
    wheel: Path,
    sdist: Path,
    workdir: Path,
    source_sha: str,
    bundle_path: Path,
) -> dict[str, Any]:
    if sys.platform == "darwin":
        raise RuntimeError(
            "S3 no inicia en Darwin: RLIMIT_AS queda sólo para diagnóstico y no demuestra "
            "un límite de memoria duro"
        )
    supervision = _supervise_child(
        mode="s3",
        workdir=workdir,
        limits=dict(S3_LIMITS),
        workload={
            "wheel": str(wheel),
            "sdist": str(sdist),
            "workdir": str(workdir),
            "source_sha": source_sha,
            "bundle_path": str(bundle_path),
        },
    )
    child_result = supervision.pop("_child_payload")
    workload: dict[str, Any] | None = None
    if isinstance(child_result, dict) and child_result.get("status") == "ok":
        raw_workload = child_result.get("payload")
        if isinstance(raw_workload, dict):
            workload = cast(dict[str, Any], raw_workload)
    pass_conditions = _s3_pass_conditions(supervision, workload)
    profile_status = "pass" if all(pass_conditions.values()) else "fail"
    payload: dict[str, Any] = {
        "schema_version": S3_SCHEMA_VERSION,
        "source_sha": source_sha,
        "driver_sha256": _sha256(Path(__file__)),
        "profile": "S3-limite",
        "profile_status": profile_status,
        "pass_conditions": pass_conditions,
        "supervisor": supervision,
    }
    if workload is not None:
        payload.update(workload)
    elif isinstance(child_result, dict):
        payload["child_error"] = {
            "status": child_result.get("status"),
            "error_type": child_result.get("error_type"),
            "error": child_result.get("error"),
        }
    return payload


def main() -> int:
    """Ejecuta un perfil y escribe evidencia canónica inmutable."""
    if len(sys.argv) == 3 and sys.argv[1] == "--internal-s3-child":
        return _run_supervised_child(Path(sys.argv[2]).resolve())
    if len(sys.argv) == 4 and sys.argv[1] == "--internal-consumer":
        request = Path(sys.argv[2]).resolve()
        output = Path(sys.argv[3]).resolve()
        try:
            payload = _consume_request(request)
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        output.write_bytes(_canonical_json(payload) + b"\n")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=(*PROFILES, "S3-limite"), required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--s3-bundle", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"la evidencia W1 no se sobrescribe: {args.output}")
    if not args.wheel.is_file():
        raise SystemExit(f"wheel ausente: {args.wheel}")
    if not args.sdist.is_file():
        raise SystemExit(f"sdist ausente: {args.sdist}")
    workdir = _validate_external_workdir(args.workdir)
    workdir.mkdir(parents=True, exist_ok=False)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    try:
        if args.profile == "S3-limite":
            if args.s3_bundle is None:
                raise RuntimeError("S3-limite exige --s3-bundle producido por S0")
            payload = _supervise_s3(
                args.wheel.resolve(),
                args.sdist.resolve(),
                workdir,
                args.source_sha,
                args.s3_bundle.resolve(),
            )
        else:
            payload = _run(
                args.profile,
                args.wheel.resolve(),
                args.sdist.resolve(),
                workdir,
                args.source_sha,
            )
        exit_code = 0 if payload["profile_status"] != "fail" else 1
    except Exception as exc:
        payload = {
            "schema_version": (
                S3_SCHEMA_VERSION if args.profile == "S3-limite" else SCHEMA_VERSION_V1
            ),
            "source_sha": args.source_sha,
            "driver_sha256": _sha256(Path(__file__)),
            "profile": args.profile,
            "profile_status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    payload["process"] = {
        "role": "supervisor" if args.profile == "S3-limite" else "driver",
        "pid": os.getpid(),
        "wall_seconds": round(time.perf_counter() - started_wall, 6),
        "cpu_seconds": round(time.process_time() - started_cpu, 6),
        "peak_rss_bytes": _peak_rss_bytes(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical_json(payload) + b"\n")
    print(json.dumps({"output": str(args.output), "status": payload["profile_status"]}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
