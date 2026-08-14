"""Confinamiento Windows Job Object y sensores nativos del arnés H9R."""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from typing import IO, Any, Final

from .contracts import MAX_LOGICAL_CPUS, ContractError


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


class _JobMemoryUsageInformation(ctypes.Structure):
    _fields_ = [("JobMemory", ctypes.c_ulonglong), ("PeakJobMemoryUsed", ctypes.c_ulonglong)]


class _JobNotificationLimitInformation(ctypes.Structure):
    _fields_ = [
        ("IoReadBytesLimit", ctypes.c_ulonglong),
        ("IoWriteBytesLimit", ctypes.c_ulonglong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("JobMemoryLimit", ctypes.c_ulonglong),
        ("RateControlTolerance", ctypes.c_int),
        ("RateControlToleranceInterval", ctypes.c_int),
        ("LimitFlags", ctypes.c_uint32),
    ]


class _JobLimitViolationInformation(ctypes.Structure):
    _fields_ = [
        ("LimitFlags", ctypes.c_uint32),
        ("ViolationLimitFlags", ctypes.c_uint32),
        ("IoReadBytes", ctypes.c_ulonglong),
        ("IoReadBytesLimit", ctypes.c_ulonglong),
        ("IoWriteBytes", ctypes.c_ulonglong),
        ("IoWriteBytesLimit", ctypes.c_ulonglong),
        ("PerJobUserTime", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("JobMemory", ctypes.c_ulonglong),
        ("JobMemoryLimit", ctypes.c_ulonglong),
        ("RateControlTolerance", ctypes.c_int),
        ("RateControlToleranceLimit", ctypes.c_int),
    ]


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    def as_int(self) -> int:
        return (int(self.dwHighDateTime) << 32) | int(self.dwLowDateTime)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _GroupAffinity(ctypes.Structure):
    _fields_ = [
        ("Mask", ctypes.c_size_t),
        ("Group", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 3),
    ]


class _JobAssociateCompletionPort(ctypes.Structure):
    _fields_ = [("CompletionKey", ctypes.c_void_p), ("CompletionPort", ctypes.c_void_p)]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
    ]


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _MibTcpRowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("dwState", ctypes.c_uint32),
        ("dwLocalAddr", ctypes.c_uint32),
        ("dwLocalPort", ctypes.c_uint32),
        ("dwRemoteAddr", ctypes.c_uint32),
        ("dwRemotePort", ctypes.c_uint32),
        ("dwOwningPid", ctypes.c_uint32),
    ]


class WindowsApi:
    """Binding mínimo y tipado dinámicamente a kernel32/psapi."""

    PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000
    PROCESS_SET_QUOTA: Final = 0x0100
    PROCESS_TERMINATE: Final = 0x0001
    PROCESS_SET_INFORMATION: Final = 0x0200
    THREAD_QUERY_LIMITED_INFORMATION: Final = 0x0800
    THREAD_SUSPEND_RESUME: Final = 0x0002
    TH32CS_SNAPTHREAD: Final = 0x00000004
    TH32CS_SNAPPROCESS: Final = 0x00000002
    INVALID_HANDLE_VALUE: Final = ctypes.c_void_p(-1).value

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("el backend H9R calificable exige Windows")
        self.kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi: Any = ctypes.WinDLL("psapi", use_last_error=True)
        self.iphlpapi: Any = ctypes.WinDLL("iphlpapi", use_last_error=True)
        self._configure()

    def _configure(self) -> None:
        k32 = self.kernel32
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        k32.SetInformationJobObject.restype = ctypes.c_bool
        k32.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        k32.QueryInformationJobObject.restype = ctypes.c_bool
        k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.AssignProcessToJobObject.restype = ctypes.c_bool
        k32.IsProcessInJob.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_bool),
        ]
        k32.IsProcessInJob.restype = ctypes.c_bool
        k32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.TerminateJobObject.restype = ctypes.c_bool
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = ctypes.c_bool
        k32.GetProcessAffinityMask.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k32.GetProcessAffinityMask.restype = ctypes.c_bool
        k32.GetProcessGroupAffinity.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ushort),
            ctypes.POINTER(ctypes.c_ushort),
        ]
        k32.GetProcessGroupAffinity.restype = ctypes.c_bool
        k32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        k32.SetProcessAffinityMask.restype = ctypes.c_bool
        k32.GetProcessTimes.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
        ]
        k32.GetProcessTimes.restype = ctypes.c_bool
        k32.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IoCounters)]
        k32.GetProcessIoCounters.restype = ctypes.c_bool
        k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
        k32.GlobalMemoryStatusEx.restype = ctypes.c_bool
        k32.GetSystemTimes.argtypes = [
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
        ]
        k32.GetSystemTimes.restype = ctypes.c_bool
        k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
        k32.Thread32First.restype = ctypes.c_bool
        k32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
        k32.Thread32Next.restype = ctypes.c_bool
        k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32W)]
        k32.Process32FirstW.restype = ctypes.c_bool
        k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32W)]
        k32.Process32NextW.restype = ctypes.c_bool
        k32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        k32.OpenThread.restype = ctypes.c_void_p
        k32.GetThreadGroupAffinity.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GroupAffinity)]
        k32.GetThreadGroupAffinity.restype = ctypes.c_bool
        k32.GetThreadTimes.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
        ]
        k32.GetThreadTimes.restype = ctypes.c_bool
        k32.GetCurrentThread.argtypes = []
        k32.GetCurrentThread.restype = ctypes.c_void_p
        k32.GetActiveProcessorGroupCount.argtypes = []
        k32.GetActiveProcessorGroupCount.restype = ctypes.c_ushort
        k32.GetActiveProcessorCount.argtypes = [ctypes.c_ushort]
        k32.GetActiveProcessorCount.restype = ctypes.c_uint32
        k32.ResumeThread.argtypes = [ctypes.c_void_p]
        k32.ResumeThread.restype = ctypes.c_uint32
        k32.CreateIoCompletionPort.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
        ]
        k32.CreateIoCompletionPort.restype = ctypes.c_void_p
        k32.GetQueuedCompletionStatus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint32,
        ]
        k32.GetQueuedCompletionStatus.restype = ctypes.c_bool
        self.psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCountersEx),
            ctypes.c_uint32,
        ]
        self.psapi.GetProcessMemoryInfo.restype = ctypes.c_bool
        self.iphlpapi.GetExtendedTcpTable.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_bool,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint32,
        ]
        self.iphlpapi.GetExtendedTcpTable.restype = ctypes.c_uint32

    @staticmethod
    def raise_last_error(context: str) -> None:
        """Eleva el último error Win32 con contexto estable."""
        code = ctypes.get_last_error()
        raise OSError(code, f"{context} falló")

    def open_process(self, pid: int, *, write_affinity: bool = False) -> int:
        """Abre un proceso con el mínimo derecho solicitado."""
        access = self.PROCESS_QUERY_LIMITED_INFORMATION
        if write_affinity:
            access |= self.PROCESS_SET_INFORMATION
        raw = self.kernel32.OpenProcess(access, False, pid)
        if not raw:
            self.raise_last_error(f"OpenProcess({pid})")
        return int(raw)

    def close_handle(self, handle: int) -> None:
        """Cierra un handle nativo."""
        if not self.kernel32.CloseHandle(ctypes.c_void_p(handle)):
            self.raise_last_error("CloseHandle")


def _bit_count(value: int) -> int:
    return bin(value).count("1")


def first_cpu_mask(allowed_mask: int, count: int = MAX_LOGICAL_CPUS) -> int:
    """Selecciona en orden los primeros CPU permitidos sin inventar índices."""
    if allowed_mask <= 0 or count <= 0:
        raise ContractError("máscara o cantidad de CPU inválida")
    selected = 0
    for bit in range(ctypes.sizeof(ctypes.c_size_t) * 8):
        candidate = 1 << bit
        if allowed_mask & candidate:
            selected |= candidate
            if _bit_count(selected) == min(count, _bit_count(allowed_mask)):
                break
    if selected <= 0 or _bit_count(selected) > count:
        raise ContractError("no se pudo construir máscara CPU confinada")
    return selected


def current_process_affinity(api: WindowsApi | None = None) -> dict[str, int]:
    """Consulta la máscara vigente del proceso supervisor y del sistema."""
    api = api or WindowsApi()
    handle = api.open_process(os.getpid())
    try:
        process_mask = ctypes.c_size_t(0)
        system_mask = ctypes.c_size_t(0)
        if not api.kernel32.GetProcessAffinityMask(
            ctypes.c_void_p(handle), ctypes.byref(process_mask), ctypes.byref(system_mask)
        ):
            api.raise_last_error("GetProcessAffinityMask(supervisor)")
        return {"process_mask": int(process_mask.value), "system_mask": int(system_mask.value)}
    finally:
        api.close_handle(handle)


def processor_topology(api: WindowsApi | None = None) -> dict[str, Any]:
    """Enumera grupos activos y la afinidad primaria del hilo supervisor."""
    api = api or WindowsApi()
    group_count = int(api.kernel32.GetActiveProcessorGroupCount())
    if group_count < 1:
        api.raise_last_error("GetActiveProcessorGroupCount")
    counts = [int(api.kernel32.GetActiveProcessorCount(group)) for group in range(group_count)]
    affinity = _GroupAffinity()
    if not api.kernel32.GetThreadGroupAffinity(
        api.kernel32.GetCurrentThread(), ctypes.byref(affinity)
    ):
        api.raise_last_error("GetThreadGroupAffinity(supervisor)")
    return {
        "active_group_count": group_count,
        "active_processor_count_by_group": counts,
        "total_active_logical_processors": sum(counts),
        "primary_group": int(affinity.Group),
        "primary_group_affinity_mask": int(affinity.Mask),
    }


class WindowsJob:
    """Job Object con cap de commit, afinidad heredada y kill-on-close."""

    JOB_OBJECT_LIMIT_AFFINITY: Final = 0x00000010
    JOB_OBJECT_LIMIT_JOB_MEMORY: Final = 0x00000200
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = 0x00002000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: Final = 9
    JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION: Final = 1
    JOB_OBJECT_BASIC_PROCESS_ID_LIST: Final = 3
    JOB_OBJECT_MEMORY_USAGE_INFORMATION: Final = 28
    JOB_OBJECT_GROUP_INFORMATION_EX: Final = 14
    JOB_OBJECT_NOTIFICATION_LIMIT_INFORMATION: Final = 12
    JOB_OBJECT_LIMIT_VIOLATION_INFORMATION: Final = 13
    JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION: Final = 7
    JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO: Final = 4
    JOB_OBJECT_MSG_NEW_PROCESS: Final = 6
    JOB_OBJECT_MSG_EXIT_PROCESS: Final = 7
    JOB_OBJECT_MSG_ABNORMAL_EXIT_PROCESS: Final = 8
    JOB_OBJECT_MSG_JOB_MEMORY_LIMIT: Final = 10
    JOB_OBJECT_MSG_NOTIFICATION_LIMIT: Final = 11

    def __init__(self, *, memory_bytes: int, affinity_mask: int | None = None) -> None:
        if memory_bytes <= 0:
            raise ContractError("cap job-wide debe ser positivo")
        self.api = WindowsApi()
        available = current_process_affinity(self.api)["process_mask"]
        selected = first_cpu_mask(available) if affinity_mask is None else affinity_mask
        if selected & ~available:
            raise ContractError("la máscara CPU solicitada sale de la máscara del supervisor")
        if _bit_count(selected) < 1 or _bit_count(selected) > MAX_LOGICAL_CPUS:
            raise ContractError("la máscara CPU debe contener entre 1 y 4 CPU lógicas")
        raw_handle = self.api.kernel32.CreateJobObjectW(None, None)
        if not raw_handle:
            self.api.raise_last_error("CreateJobObjectW")
        self.handle = int(raw_handle)
        self._closed = False
        self._completion_messages: list[dict[str, int]] = []
        self._completion_port: int | None = None
        self.requested_memory_bytes = memory_bytes
        self.requested_affinity_mask = selected
        topology = processor_topology(self.api)
        self.requested_processor_group = int(topology["primary_group"])
        try:
            raw_port = self.api.kernel32.CreateIoCompletionPort(
                ctypes.c_void_p(self.api.INVALID_HANDLE_VALUE), None, 0, 1
            )
            if not raw_port:
                self.api.raise_last_error("CreateIoCompletionPort(H9R)")
            self._completion_port = int(raw_port)
            association = _JobAssociateCompletionPort()
            association.CompletionKey = self.handle
            association.CompletionPort = self._completion_port
            if not self.api.kernel32.SetInformationJobObject(
                ctypes.c_void_p(self.handle),
                self.JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION,
                ctypes.byref(association),
                ctypes.sizeof(association),
            ):
                self.api.raise_last_error("SetInformationJobObject(H9R completion port)")
            limits = _JobExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = (
                self.JOB_OBJECT_LIMIT_AFFINITY
                | self.JOB_OBJECT_LIMIT_JOB_MEMORY
                | self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            limits.BasicLimitInformation.Affinity = selected
            limits.JobMemoryLimit = memory_bytes
            if not self.api.kernel32.SetInformationJobObject(
                ctypes.c_void_p(self.handle),
                self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                self.api.raise_last_error("SetInformationJobObject(H9R)")
            group_affinity = _GroupAffinity()
            group_affinity.Mask = selected
            group_affinity.Group = self.requested_processor_group
            if not self.api.kernel32.SetInformationJobObject(
                ctypes.c_void_p(self.handle),
                self.JOB_OBJECT_GROUP_INFORMATION_EX,
                ctypes.byref(group_affinity),
                ctypes.sizeof(group_affinity),
            ):
                self.api.raise_last_error("SetInformationJobObject(H9R group affinity)")
            notification = _JobNotificationLimitInformation()
            notification.JobMemoryLimit = memory_bytes
            notification.LimitFlags = self.JOB_OBJECT_LIMIT_JOB_MEMORY
            if not self.api.kernel32.SetInformationJobObject(
                ctypes.c_void_p(self.handle),
                self.JOB_OBJECT_NOTIFICATION_LIMIT_INFORMATION,
                ctypes.byref(notification),
                ctypes.sizeof(notification),
            ):
                self.api.raise_last_error("SetInformationJobObject(H9R memory notification)")
            effective = self.effective_limits()
            if effective["job_memory_commit_limit_bytes"] != memory_bytes:
                raise RuntimeError("cap job-wide efectivo difiere del solicitado")
            if effective["affinity_mask"] != selected:
                raise RuntimeError("afinidad efectiva difiere de la solicitada")
            if effective["group_affinities"] != [
                {"processor_group": self.requested_processor_group, "affinity_mask": selected}
            ]:
                raise RuntimeError("afinidad efectiva por grupo difiere de la solicitada")
        except Exception:
            self.close()
            raise

    def _query(self, information_class: int, value: ctypes.Structure) -> None:
        if not self.api.kernel32.QueryInformationJobObject(
            ctypes.c_void_p(self.handle),
            information_class,
            ctypes.byref(value),
            ctypes.sizeof(value),
            None,
        ):
            self.api.raise_last_error(f"QueryInformationJobObject({information_class})")

    def assign(self, pid: int) -> None:
        """Asigna la raíz y acredita membresía antes de READY."""
        access = (
            self.api.PROCESS_QUERY_LIMITED_INFORMATION
            | self.api.PROCESS_SET_QUOTA
            | self.api.PROCESS_TERMINATE
        )
        raw_process = self.api.kernel32.OpenProcess(access, False, pid)
        if not raw_process:
            self.api.raise_last_error(f"OpenProcess(assign {pid})")
        process_handle = int(raw_process)
        try:
            if not self.api.kernel32.AssignProcessToJobObject(
                ctypes.c_void_p(self.handle), ctypes.c_void_p(process_handle)
            ):
                self.api.raise_last_error("AssignProcessToJobObject")
            in_job = ctypes.c_bool(False)
            if not self.api.kernel32.IsProcessInJob(
                ctypes.c_void_p(process_handle),
                ctypes.c_void_p(self.handle),
                ctypes.byref(in_job),
            ):
                self.api.raise_last_error("IsProcessInJob")
            if not in_job.value:
                raise RuntimeError("la raíz no quedó dentro del Job Object")
        finally:
            self.api.close_handle(process_handle)

    def effective_limits(self) -> dict[str, Any]:
        """Consulta los límites al kernel; no confía en la solicitud."""
        limits = _JobExtendedLimitInformation()
        self._query(self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, limits)
        flags = int(limits.BasicLimitInformation.LimitFlags)
        group_array_type = _GroupAffinity * 64
        group_array = group_array_type()
        returned = ctypes.c_uint32(0)
        if not self.api.kernel32.QueryInformationJobObject(
            ctypes.c_void_p(self.handle),
            self.JOB_OBJECT_GROUP_INFORMATION_EX,
            ctypes.byref(group_array),
            ctypes.sizeof(group_array),
            ctypes.byref(returned),
        ):
            self.api.raise_last_error("QueryInformationJobObject(group affinity)")
        group_count = int(returned.value) // ctypes.sizeof(_GroupAffinity)
        group_affinities = [
            {
                "processor_group": int(group_array[index].Group),
                "affinity_mask": int(group_array[index].Mask),
            }
            for index in range(group_count)
        ]
        return {
            "limit_flags": flags,
            "affinity_mask": int(limits.BasicLimitInformation.Affinity),
            "logical_cpu_count": _bit_count(int(limits.BasicLimitInformation.Affinity)),
            "processor_group": self.requested_processor_group,
            "group_affinities": group_affinities,
            "job_memory_commit_limit_bytes": int(limits.JobMemoryLimit),
            "kill_on_job_close": bool(flags & self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE),
            "affinity_enforced": bool(flags & self.JOB_OBJECT_LIMIT_AFFINITY),
            "job_memory_enforced": bool(flags & self.JOB_OBJECT_LIMIT_JOB_MEMORY),
        }

    def accounting(self) -> dict[str, Any]:
        """Consulta CPU, I/O, procesos y PeakJobMemoryUsed autoritativos."""
        basic = _JobBasicAccountingInformation()
        limits = _JobExtendedLimitInformation()
        memory = _JobMemoryUsageInformation()
        self._query(self.JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, basic)
        self._query(self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, limits)
        memory_supported = True
        try:
            self._query(self.JOB_OBJECT_MEMORY_USAGE_INFORMATION, memory)
        except OSError:
            memory_supported = False
        io = limits.IoInfo
        return {
            "source": "windows_job_object",
            "total_user_time_100ns": int(basic.TotalUserTime),
            "total_kernel_time_100ns": int(basic.TotalKernelTime),
            "total_user_seconds": int(basic.TotalUserTime) / 10_000_000,
            "total_kernel_seconds": int(basic.TotalKernelTime) / 10_000_000,
            "total_page_fault_count": int(basic.TotalPageFaultCount),
            "total_processes": int(basic.TotalProcesses),
            "active_processes": int(basic.ActiveProcesses),
            "total_terminated_processes": int(basic.TotalTerminatedProcesses),
            "peak_process_memory_commit_bytes": int(limits.PeakProcessMemoryUsed),
            "peak_job_memory_commit_bytes": int(limits.PeakJobMemoryUsed),
            "current_job_memory_commit_bytes": int(memory.JobMemory) if memory_supported else None,
            "memory_usage_information_supported": memory_supported,
            "io": {
                "read_operations": int(io.ReadOperationCount),
                "write_operations": int(io.WriteOperationCount),
                "other_operations": int(io.OtherOperationCount),
                "read_bytes": int(io.ReadTransferCount),
                "write_bytes": int(io.WriteTransferCount),
                "other_bytes": int(io.OtherTransferCount),
            },
        }

    def _drain_completion_messages(self, *, first_wait_timeout_ms: int = 0) -> list[dict[str, int]]:
        """Drena mensajes kernel; opcionalmente espera sólo por el primero."""
        if self._completion_port is None:
            raise RuntimeError("el Job no conserva puerto de finalización")
        if not 0 <= first_wait_timeout_ms <= 1_000:
            raise ValueError("first_wait_timeout_ms debe estar entre 0 y 1000")
        timeout_ms = first_wait_timeout_ms
        while True:
            message = ctypes.c_uint32(0)
            completion_key = ctypes.c_size_t(0)
            specific = ctypes.c_void_p()
            ctypes.set_last_error(0)
            succeeded = bool(
                self.api.kernel32.GetQueuedCompletionStatus(
                    ctypes.c_void_p(self._completion_port),
                    ctypes.byref(message),
                    ctypes.byref(completion_key),
                    ctypes.byref(specific),
                    timeout_ms,
                )
            )
            timeout_ms = 0
            if not succeeded:
                error = ctypes.get_last_error()
                if error == 258:  # WAIT_TIMEOUT: cola drenada.
                    break
                self.api.raise_last_error("GetQueuedCompletionStatus(H9R)")
            self._completion_messages.append(
                {
                    "message_id": int(message.value),
                    "completion_key": int(completion_key.value),
                    "message_specific_value": int(specific.value or 0),
                }
            )
        return [dict(item) for item in self._completion_messages]

    def completion_messages(self, *, wait_timeout_ms: int = 0) -> list[dict[str, int]]:
        """Devuelve el historial acumulado de eventos autoritativos del completion port."""
        return self._drain_completion_messages(first_wait_timeout_ms=wait_timeout_ms)

    def memory_limit_violation(self) -> dict[str, Any]:
        """Reconcilia mensajes kernel hard-limit y límites de notificación del Job."""
        messages = self._drain_completion_messages()
        violation = _JobLimitViolationInformation()
        self._query(self.JOB_OBJECT_LIMIT_VIOLATION_INFORMATION, violation)
        flags = int(violation.ViolationLimitFlags)
        hard_messages = [
            message
            for message in messages
            if message["message_id"] == self.JOB_OBJECT_MSG_JOB_MEMORY_LIMIT
        ]
        return {
            "source": "windows_job_completion_port_and_limit_violation_information",
            "limit_flags": int(violation.LimitFlags),
            "violation_limit_flags": flags,
            "job_memory_limit_violated": bool(hard_messages),
            "hard_limit_message_observed": bool(hard_messages),
            "violating_pids": sorted(
                {message["message_specific_value"] for message in hard_messages}
            ),
            "completion_messages": messages,
            "job_memory_bytes_at_violation": int(violation.JobMemory),
            "job_memory_limit_bytes": self.requested_memory_bytes,
        }

    def process_ids(self) -> list[int]:
        """Enumera PIDs vivos del Job con buffer dinámico."""
        capacity = 16
        while capacity <= 65_536:
            header_size = ctypes.sizeof(ctypes.c_uint32) * 2
            pointer_size = ctypes.sizeof(ctypes.c_size_t)
            buffer_size = header_size + pointer_size * capacity
            buffer = ctypes.create_string_buffer(buffer_size)
            if self.api.kernel32.QueryInformationJobObject(
                ctypes.c_void_p(self.handle),
                self.JOB_OBJECT_BASIC_PROCESS_ID_LIST,
                buffer,
                buffer_size,
                None,
            ):
                assigned = int(ctypes.c_uint32.from_buffer(buffer, 0).value)
                count = int(ctypes.c_uint32.from_buffer(buffer, 4).value)
                if count <= capacity:
                    values = ctypes.cast(
                        ctypes.byref(buffer, header_size), ctypes.POINTER(ctypes.c_size_t)
                    )
                    return [int(values[index]) for index in range(count)]
                capacity = max(capacity * 2, assigned)
                continue
            error = ctypes.get_last_error()
            if error != 122:  # ERROR_INSUFFICIENT_BUFFER
                raise OSError(error, "QueryInformationJobObject(process ids) falló")
            capacity *= 2
        raise RuntimeError("censo de PIDs excedió el límite defensivo")

    def wait_empty(self, timeout_seconds: float) -> bool:
        """Espera que el árbol quede vacío, con deadline monotónico."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if int(self.accounting()["active_processes"]) == 0:
                return True
            time.sleep(0.01)
        return int(self.accounting()["active_processes"]) == 0

    def terminate(self, exit_code: int) -> None:
        """Termina raíz y descendientes con un código no ambiguo."""
        if not self.api.kernel32.TerminateJobObject(
            ctypes.c_void_p(self.handle), ctypes.c_uint32(exit_code)
        ):
            self.api.raise_last_error("TerminateJobObject")

    def close(self) -> None:
        """Cierra el Job; KILL_ON_JOB_CLOSE evita huérfanos."""
        if getattr(self, "_closed", True):
            return
        pending_error: BaseException | None = None
        if self.handle:
            try:
                self.api.close_handle(self.handle)
                self.handle = 0
            except BaseException as exc:
                pending_error = exc
        if self._completion_port is not None:
            try:
                self.api.close_handle(self._completion_port)
                self._completion_port = None
            except BaseException as exc:
                if pending_error is None:
                    pending_error = exc
        self._closed = self.handle == 0 and self._completion_port is None
        if pending_error is not None:
            raise pending_error

    def __enter__(self) -> WindowsJob:
        """Devuelve el Job abierto."""
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Cierra el Job y activa kill-on-close si persistiera un hijo."""
        del exc_type, exc, traceback
        self.close()


class WindowsExternalJob:
    """Job de limpieza para un cliente UI externo al Job del workload.

    Este Job no impone afinidad ni memoria. Su única política es
    ``KILL_ON_JOB_CLOSE``: permite censar y limpiar el árbol del cliente sin
    mezclar su consumo con los límites job-wide del workload.
    """

    JOB_OBJECT_LIMIT_AFFINITY: Final = WindowsJob.JOB_OBJECT_LIMIT_AFFINITY
    JOB_OBJECT_LIMIT_JOB_MEMORY: Final = WindowsJob.JOB_OBJECT_LIMIT_JOB_MEMORY
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = WindowsJob.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: Final = WindowsJob.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION
    JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION: Final = (
        WindowsJob.JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION
    )
    JOB_OBJECT_BASIC_PROCESS_ID_LIST: Final = WindowsJob.JOB_OBJECT_BASIC_PROCESS_ID_LIST
    JOB_OBJECT_MEMORY_USAGE_INFORMATION: Final = WindowsJob.JOB_OBJECT_MEMORY_USAGE_INFORMATION

    def __init__(self) -> None:
        self.api = WindowsApi()
        raw_handle = self.api.kernel32.CreateJobObjectW(None, None)
        if not raw_handle:
            self.api.raise_last_error("CreateJobObjectW(cliente externo)")
        self.handle = int(raw_handle)
        self._closed = False
        self._assigned_root_pid: int | None = None
        try:
            limits = _JobExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.api.kernel32.SetInformationJobObject(
                ctypes.c_void_p(self.handle),
                self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                self.api.raise_last_error("SetInformationJobObject(cliente externo)")
            effective = self.effective_controls()
            if not effective["kill_on_job_close"]:
                raise RuntimeError("KILL_ON_JOB_CLOSE no quedó efectivo para el cliente externo")
            if effective["affinity_enforced"] or effective["job_memory_enforced"]:
                raise RuntimeError("el Job del cliente externo heredó un cap del workload")
            if effective["affinity_mask"] != 0 or effective["job_memory_limit_bytes"] != 0:
                raise RuntimeError("el Job del cliente externo expone límites no solicitados")
        except Exception:
            self.close()
            raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("el Job del cliente externo ya está cerrado")

    def _query(self, information_class: int, value: ctypes.Structure) -> None:
        self._ensure_open()
        if not self.api.kernel32.QueryInformationJobObject(
            ctypes.c_void_p(self.handle),
            information_class,
            ctypes.byref(value),
            ctypes.sizeof(value),
            None,
        ):
            self.api.raise_last_error(f"QueryInformationJobObject({information_class})")

    def effective_controls(self) -> dict[str, Any]:
        """Consulta al kernel que el Job sólo tenga la política de limpieza."""
        limits = _JobExtendedLimitInformation()
        self._query(self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, limits)
        flags = int(limits.BasicLimitInformation.LimitFlags)
        return {
            "limit_flags": flags,
            "kill_on_job_close": bool(flags & self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE),
            "affinity_enforced": bool(flags & self.JOB_OBJECT_LIMIT_AFFINITY),
            "job_memory_enforced": bool(flags & self.JOB_OBJECT_LIMIT_JOB_MEMORY),
            "affinity_mask": int(limits.BasicLimitInformation.Affinity),
            "job_memory_limit_bytes": int(limits.JobMemoryLimit),
        }

    def assign(self, pid: int) -> None:
        """Asigna una raíz suspendida y verifica su membresía antes de reanudarla."""
        self._ensure_open()
        if pid <= 0:
            raise ContractError("PID inválido para el cliente externo")
        if self._assigned_root_pid is not None:
            raise ContractError("el Job del cliente externo ya tiene una raíz asignada")
        access = (
            self.api.PROCESS_QUERY_LIMITED_INFORMATION
            | self.api.PROCESS_SET_QUOTA
            | self.api.PROCESS_TERMINATE
        )
        raw_process = self.api.kernel32.OpenProcess(access, False, pid)
        if not raw_process:
            self.api.raise_last_error(f"OpenProcess(assign cliente externo {pid})")
        process_handle = int(raw_process)
        try:
            if not self.api.kernel32.AssignProcessToJobObject(
                ctypes.c_void_p(self.handle), ctypes.c_void_p(process_handle)
            ):
                self.api.raise_last_error("AssignProcessToJobObject(cliente externo)")
            in_job = ctypes.c_bool(False)
            if not self.api.kernel32.IsProcessInJob(
                ctypes.c_void_p(process_handle),
                ctypes.c_void_p(self.handle),
                ctypes.byref(in_job),
            ):
                self.api.raise_last_error("IsProcessInJob(cliente externo)")
            if not in_job.value:
                raise RuntimeError("la raíz del cliente externo no quedó dentro del Job")
            if pid not in self.process_ids():
                raise RuntimeError("el censo del Job no contiene la raíz del cliente externo")
            self._assigned_root_pid = pid
        finally:
            self.api.close_handle(process_handle)

    def launch_suspended(
        self,
        command: Sequence[str | os.PathLike[str]],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdout: int | IO[bytes] | None = None,
        stderr: int | IO[bytes] | None = None,
    ) -> subprocess.Popen[bytes]:
        """Crea y asigna la raíz, que permanece suspendida para su censo y gate."""
        self._ensure_open()
        if not command:
            raise ContractError("comando vacío para el cliente externo")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            creationflags=0x00000004,  # CREATE_SUSPENDED
        )
        try:
            self.assign(process.pid)
        except BaseException:
            try:
                if self._assigned_root_pid == process.pid:
                    self.terminate(0xE0000003)
                else:
                    process.kill()
            finally:
                process.wait(timeout=10)
            raise
        return process

    def accounting(self) -> dict[str, Any]:
        """Consulta CPU, I/O y procesos del cliente, separados del workload."""
        basic = _JobBasicAccountingInformation()
        limits = _JobExtendedLimitInformation()
        memory = _JobMemoryUsageInformation()
        self._query(self.JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, basic)
        self._query(self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, limits)
        memory_supported = True
        try:
            self._query(self.JOB_OBJECT_MEMORY_USAGE_INFORMATION, memory)
        except OSError:
            memory_supported = False
        io = limits.IoInfo
        return {
            "source": "windows_external_cleanup_job",
            "root_pid": self._assigned_root_pid,
            "total_user_time_100ns": int(basic.TotalUserTime),
            "total_kernel_time_100ns": int(basic.TotalKernelTime),
            "total_user_seconds": int(basic.TotalUserTime) / 10_000_000,
            "total_kernel_seconds": int(basic.TotalKernelTime) / 10_000_000,
            "total_page_fault_count": int(basic.TotalPageFaultCount),
            "total_processes": int(basic.TotalProcesses),
            "active_processes": int(basic.ActiveProcesses),
            "total_terminated_processes": int(basic.TotalTerminatedProcesses),
            "peak_process_memory_commit_bytes": int(limits.PeakProcessMemoryUsed),
            "peak_job_memory_commit_bytes": int(limits.PeakJobMemoryUsed),
            "current_job_memory_commit_bytes": int(memory.JobMemory) if memory_supported else None,
            "memory_usage_information_supported": memory_supported,
            "io": {
                "read_operations": int(io.ReadOperationCount),
                "write_operations": int(io.WriteOperationCount),
                "other_operations": int(io.OtherOperationCount),
                "read_bytes": int(io.ReadTransferCount),
                "write_bytes": int(io.WriteTransferCount),
                "other_bytes": int(io.OtherTransferCount),
            },
        }

    def process_ids(self) -> list[int]:
        """Enumera todos los PIDs vivos del árbol del cliente externo."""
        self._ensure_open()
        capacity = 16
        while capacity <= 65_536:
            header_size = ctypes.sizeof(ctypes.c_uint32) * 2
            pointer_size = ctypes.sizeof(ctypes.c_size_t)
            buffer_size = header_size + pointer_size * capacity
            buffer = ctypes.create_string_buffer(buffer_size)
            if self.api.kernel32.QueryInformationJobObject(
                ctypes.c_void_p(self.handle),
                self.JOB_OBJECT_BASIC_PROCESS_ID_LIST,
                buffer,
                buffer_size,
                None,
            ):
                assigned = int(ctypes.c_uint32.from_buffer(buffer, 0).value)
                count = int(ctypes.c_uint32.from_buffer(buffer, 4).value)
                if count <= capacity:
                    values = ctypes.cast(
                        ctypes.byref(buffer, header_size), ctypes.POINTER(ctypes.c_size_t)
                    )
                    return [int(values[index]) for index in range(count)]
                capacity = max(capacity * 2, assigned)
                continue
            error = ctypes.get_last_error()
            if error != 122:  # ERROR_INSUFFICIENT_BUFFER
                raise OSError(error, "QueryInformationJobObject(cliente externo PIDs) falló")
            capacity *= 2
        raise RuntimeError("censo de PIDs del cliente externo excedió el límite defensivo")

    def census(self) -> dict[str, Any]:
        """Censa PID/TID y falla si alguna identidad viva no pudo consultarse."""
        self._ensure_open()
        tree = process_tree_snapshot(self)
        if tree["process_query_errors"] or tree["thread_query_errors"]:
            raise RuntimeError("censo incompleto del cliente externo")
        return {"accounting": self.accounting(), "tree": tree}

    def wait_empty(self, timeout_seconds: float) -> bool:
        """Espera vaciado completo con deadline monotónico; no oculta fallos de consulta."""
        self._ensure_open()
        if timeout_seconds < 0:
            raise ContractError("timeout de limpieza no puede ser negativo")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if int(self.accounting()["active_processes"]) == 0:
                return True
            time.sleep(0.01)
        return int(self.accounting()["active_processes"]) == 0

    def terminate(self, exit_code: int) -> None:
        """Termina de forma autoritativa la raíz y todos sus descendientes."""
        self._ensure_open()
        if not 0 <= exit_code <= 0xFFFFFFFF:
            raise ContractError("exit code del cliente externo fuera de rango")
        if not self.api.kernel32.TerminateJobObject(
            ctypes.c_void_p(self.handle), ctypes.c_uint32(exit_code)
        ):
            self.api.raise_last_error("TerminateJobObject(cliente externo)")

    def close(self, timeout_seconds: float = 5.0) -> None:
        """Vacía y cierra el Job; informa cualquier imposibilidad de acreditar cleanup."""
        if getattr(self, "_closed", True):
            return
        pending_error: BaseException | None = None
        try:
            if int(self.accounting()["active_processes"]) > 0:
                self.terminate(0xE0000001)
                if not self.wait_empty(timeout_seconds):
                    pending_error = RuntimeError(
                        "el Job del cliente externo no quedó vacío antes del cierre"
                    )
        except BaseException as exc:  # el cierre del handle sigue siendo obligatorio
            pending_error = exc
        finally:
            try:
                self.api.close_handle(self.handle)
                self.handle = 0
            except BaseException as close_error:
                if pending_error is None:
                    pending_error = close_error
            self._closed = self.handle == 0
        if pending_error is not None:
            raise pending_error

    def __enter__(self) -> WindowsExternalJob:
        """Devuelve el Job de limpieza abierto."""
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Cierra fail-closed aun si el bloque consumidor falla."""
        del exc_type, exc, traceback
        self.close()


def system_memory_status(api: WindowsApi | None = None) -> dict[str, int]:
    """Mide memoria física y headroom de commit visible del sistema."""
    api = api or WindowsApi()
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not api.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        api.raise_last_error("GlobalMemoryStatusEx")
    return {
        "physical_total_bytes": int(status.ullTotalPhys),
        "physical_available_bytes": int(status.ullAvailPhys),
        "commit_limit_bytes": int(status.ullTotalPageFile),
        "commit_available_bytes": int(status.ullAvailPageFile),
        "commit_used_bytes": int(status.ullTotalPageFile - status.ullAvailPageFile),
        "memory_load_percent": int(status.dwMemoryLoad),
        "virtual_total_bytes": int(status.ullTotalVirtual),
        "virtual_available_bytes": int(status.ullAvailVirtual),
    }


def process_metrics(pid: int, api: WindowsApi | None = None) -> dict[str, Any]:
    """Mide WS/private/pagefile, CPU, I/O, affinity y creation time por PID."""
    api = api or WindowsApi()
    handle = api.open_process(pid)
    try:
        memory = _ProcessMemoryCountersEx()
        memory.cb = ctypes.sizeof(memory)
        if not api.psapi.GetProcessMemoryInfo(
            ctypes.c_void_p(handle), ctypes.byref(memory), ctypes.sizeof(memory)
        ):
            api.raise_last_error(f"GetProcessMemoryInfo({pid})")
        creation = _FileTime()
        exit_time = _FileTime()
        kernel = _FileTime()
        user = _FileTime()
        if not api.kernel32.GetProcessTimes(
            ctypes.c_void_p(handle),
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            api.raise_last_error(f"GetProcessTimes({pid})")
        io = _IoCounters()
        if not api.kernel32.GetProcessIoCounters(ctypes.c_void_p(handle), ctypes.byref(io)):
            api.raise_last_error(f"GetProcessIoCounters({pid})")
        process_mask = ctypes.c_size_t(0)
        system_mask = ctypes.c_size_t(0)
        if not api.kernel32.GetProcessAffinityMask(
            ctypes.c_void_p(handle), ctypes.byref(process_mask), ctypes.byref(system_mask)
        ):
            api.raise_last_error(f"GetProcessAffinityMask({pid})")
        group_capacity = ctypes.c_ushort(64)
        groups = (ctypes.c_ushort * 64)()
        if not api.kernel32.GetProcessGroupAffinity(
            ctypes.c_void_p(handle), ctypes.byref(group_capacity), groups
        ):
            api.raise_last_error(f"GetProcessGroupAffinity({pid})")
        return {
            "pid": pid,
            "creation_time_100ns": creation.as_int(),
            "cpu_user_100ns": user.as_int(),
            "cpu_kernel_100ns": kernel.as_int(),
            "page_fault_count": int(memory.PageFaultCount),
            "working_set_bytes": int(memory.WorkingSetSize),
            "peak_working_set_bytes": int(memory.PeakWorkingSetSize),
            "pagefile_bytes": int(memory.PagefileUsage),
            "peak_pagefile_bytes": int(memory.PeakPagefileUsage),
            "private_usage_bytes": int(memory.PrivateUsage),
            "affinity_mask": int(process_mask.value),
            "system_affinity_mask": int(system_mask.value),
            "logical_cpu_count_effective": _bit_count(int(process_mask.value)),
            "processor_groups": [int(groups[index]) for index in range(group_capacity.value)],
            "io": {
                "read_operations": int(io.ReadOperationCount),
                "write_operations": int(io.WriteOperationCount),
                "other_operations": int(io.OtherOperationCount),
                "read_bytes": int(io.ReadTransferCount),
                "write_bytes": int(io.WriteTransferCount),
                "other_bytes": int(io.OtherTransferCount),
            },
        }
    finally:
        api.close_handle(handle)


def tcp_listener_owner_pid(host: str, port: int, api: WindowsApi | None = None) -> int | None:
    """Devuelve el PID dueño del listener IPv4 exacto, sin confiar en READY cooperativo."""
    if sys.platform != "win32":
        raise ContractError("censo de owner TCP exige Windows")
    if host != "127.0.0.1" or isinstance(port, bool) or not 1 <= port <= 65_535:
        raise ContractError("listener TCP debe ser loopback IPv4/puerto válido")
    api = api or WindowsApi()
    size = ctypes.c_uint32(0)
    insufficient_buffer = 122
    result = int(
        api.iphlpapi.GetExtendedTcpTable(
            None,
            ctypes.byref(size),
            False,
            socket.AF_INET,
            3,  # TCP_TABLE_OWNER_PID_LISTENER
            0,
        )
    )
    if result not in {0, insufficient_buffer} or size.value < ctypes.sizeof(ctypes.c_uint32):
        raise OSError(result, "GetExtendedTcpTable(size) falló")
    buffer = ctypes.create_string_buffer(size.value)
    result = int(
        api.iphlpapi.GetExtendedTcpTable(
            buffer,
            ctypes.byref(size),
            False,
            socket.AF_INET,
            3,
            0,
        )
    )
    if result != 0:
        raise OSError(result, "GetExtendedTcpTable(data) falló")
    count = int(ctypes.c_uint32.from_buffer_copy(buffer.raw[:4]).value)
    row_size = ctypes.sizeof(_MibTcpRowOwnerPid)
    expected_size = ctypes.sizeof(ctypes.c_uint32) + count * row_size
    if expected_size > size.value:
        raise ContractError("tabla TCP owner truncada")
    expected_address = int.from_bytes(socket.inet_aton(host), "little")
    owners: set[int] = set()
    for index in range(count):
        offset = ctypes.sizeof(ctypes.c_uint32) + index * row_size
        row = _MibTcpRowOwnerPid.from_buffer_copy(buffer.raw[offset : offset + row_size])
        observed_port = socket.ntohs(int(row.dwLocalPort) & 0xFFFF)
        if observed_port == port and int(row.dwLocalAddr) == expected_address:
            owners.add(int(row.dwOwningPid))
    if len(owners) > 1:
        raise ContractError("múltiples owners para listener TCP exacto")
    return next(iter(owners), None)


def _classify_process_query_error(exc: OSError) -> tuple[int | None, str]:
    """Normaliza WinError/errno; Python puede exponer AccessDenied sólo como errno=5."""
    raw_winerror = getattr(exc, "winerror", None)
    raw_errno = getattr(exc, "errno", None)
    code = raw_winerror if isinstance(raw_winerror, int) else raw_errno
    normalized_code = code if isinstance(code, int) and not isinstance(code, bool) else None
    normalized_error = str(exc).casefold()
    if (
        normalized_code in {5, 87}
        or "access is denied" in normalized_error
        or "acceso denegado" in normalized_error
    ):
        return normalized_code, "protected_or_system"
    if normalized_code in {6, 1168}:
        return normalized_code, "process_exited"
    return normalized_code, "unexpected_query_failure"


def system_process_resource_snapshot(
    *, excluded_pids: set[int], api: WindowsApi | None = None
) -> dict[str, Any]:
    """Censa procesos host accesibles para probar deriva externa nueva tras READY.

    El censo conserva errores por PID; nunca interpreta contadores globales no atribuidos como
    causalidad. Sólo una identidad ``PID + creation_time`` consultada directamente puede sustentar
    ``host_contamination``.
    """
    api = api or WindowsApi()
    raw_snapshot = api.kernel32.CreateToolhelp32Snapshot(api.TH32CS_SNAPPROCESS, 0)
    snapshot = int(raw_snapshot) if raw_snapshot else 0
    if not snapshot or snapshot == api.INVALID_HANDLE_VALUE:
        api.raise_last_error("CreateToolhelp32Snapshot(processes)")
    processes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    enumerated_process_count = 0
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(
            api.kernel32.Process32FirstW(ctypes.c_void_p(snapshot), ctypes.byref(entry))
        )
        while has_entry:
            pid = int(entry.th32ProcessID)
            if pid > 0 and pid not in excluded_pids:
                enumerated_process_count += 1
                try:
                    handle = api.open_process(pid)
                    try:
                        memory = _ProcessMemoryCountersEx()
                        memory.cb = ctypes.sizeof(memory)
                        if not api.psapi.GetProcessMemoryInfo(
                            ctypes.c_void_p(handle), ctypes.byref(memory), ctypes.sizeof(memory)
                        ):
                            api.raise_last_error(f"GetProcessMemoryInfo(host {pid})")
                        creation = _FileTime()
                        exit_time = _FileTime()
                        kernel = _FileTime()
                        user = _FileTime()
                        if not api.kernel32.GetProcessTimes(
                            ctypes.c_void_p(handle),
                            ctypes.byref(creation),
                            ctypes.byref(exit_time),
                            ctypes.byref(kernel),
                            ctypes.byref(user),
                        ):
                            api.raise_last_error(f"GetProcessTimes(host {pid})")
                        io = _IoCounters()
                        if not api.kernel32.GetProcessIoCounters(
                            ctypes.c_void_p(handle), ctypes.byref(io)
                        ):
                            api.raise_last_error(f"GetProcessIoCounters(host {pid})")
                        processes.append(
                            {
                                "pid": pid,
                                "creation_time_100ns": creation.as_int(),
                                "image_name": str(entry.szExeFile),
                                "cpu_user_100ns": user.as_int(),
                                "cpu_kernel_100ns": kernel.as_int(),
                                "private_usage_bytes": int(memory.PrivateUsage),
                                "working_set_bytes": int(memory.WorkingSetSize),
                                "io": {
                                    "read_operations": int(io.ReadOperationCount),
                                    "write_operations": int(io.WriteOperationCount),
                                    "other_operations": int(io.OtherOperationCount),
                                    "read_bytes": int(io.ReadTransferCount),
                                    "write_bytes": int(io.WriteTransferCount),
                                    "other_bytes": int(io.OtherTransferCount),
                                },
                            }
                        )
                    finally:
                        api.close_handle(handle)
                except OSError as exc:
                    winerror, category = _classify_process_query_error(exc)
                    error_text = str(exc)
                    errors.append(
                        {
                            "pid": pid,
                            "image_name": str(entry.szExeFile),
                            "category": category,
                            "winerror": winerror,
                            "error": error_text,
                        }
                    )
            entry.dwSize = ctypes.sizeof(entry)
            has_entry = bool(
                api.kernel32.Process32NextW(ctypes.c_void_p(snapshot), ctypes.byref(entry))
            )
    finally:
        api.close_handle(snapshot)
    processes.sort(key=lambda item: (int(item["pid"]), int(item["creation_time_100ns"])))
    errors.sort(key=lambda item: int(item["pid"]))
    unexpected = sum(error["category"] == "unexpected_query_failure" for error in errors)
    return {
        "processes": processes,
        "query_errors": errors,
        "coverage": {
            "enumerated_process_count": enumerated_process_count,
            "observed_process_count": len(processes),
            "query_error_count": len(errors),
            "expected_query_error_count": len(errors) - unexpected,
            "unexpected_query_error_count": unexpected,
            "snapshot_complete": unexpected == 0,
        },
    }


def thread_affinities(
    pids: set[int], api: WindowsApi | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Atestigua TID, PID, grupo y máscara efectiva para hilos vivos."""
    api = api or WindowsApi()
    raw_snapshot = api.kernel32.CreateToolhelp32Snapshot(api.TH32CS_SNAPTHREAD, 0)
    snapshot = int(raw_snapshot) if raw_snapshot else 0
    if not snapshot or snapshot == api.INVALID_HANDLE_VALUE:
        api.raise_last_error("CreateToolhelp32Snapshot(threads)")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(api.kernel32.Thread32First(ctypes.c_void_p(snapshot), ctypes.byref(entry)))
        while has_entry:
            pid = int(entry.th32OwnerProcessID)
            tid = int(entry.th32ThreadID)
            if pid in pids:
                raw_thread = api.kernel32.OpenThread(
                    api.THREAD_QUERY_LIMITED_INFORMATION, False, tid
                )
                if raw_thread:
                    thread_handle = int(raw_thread)
                    try:
                        affinity = _GroupAffinity()
                        creation = _FileTime()
                        exit_time = _FileTime()
                        kernel = _FileTime()
                        user = _FileTime()
                        times_ok = bool(
                            api.kernel32.GetThreadTimes(
                                ctypes.c_void_p(thread_handle),
                                ctypes.byref(creation),
                                ctypes.byref(exit_time),
                                ctypes.byref(kernel),
                                ctypes.byref(user),
                            )
                        )
                        affinity_ok = bool(
                            api.kernel32.GetThreadGroupAffinity(
                                ctypes.c_void_p(thread_handle), ctypes.byref(affinity)
                            )
                        )
                        if times_ok and affinity_ok:
                            rows.append(
                                {
                                    "pid": pid,
                                    "tid": tid,
                                    "creation_time_100ns": creation.as_int(),
                                    "processor_group": int(affinity.Group),
                                    "affinity_mask": int(affinity.Mask),
                                    "logical_cpu_count_effective": _bit_count(int(affinity.Mask)),
                                }
                            )
                        else:
                            errors.append(
                                {
                                    "pid": pid,
                                    "tid": tid,
                                    "error": (
                                        "GetThreadTimes/GetThreadGroupAffinity falló"
                                        if not times_ok and not affinity_ok
                                        else "GetThreadTimes falló"
                                        if not times_ok
                                        else "GetThreadGroupAffinity falló"
                                    ),
                                }
                            )
                    finally:
                        api.close_handle(thread_handle)
                else:
                    errors.append({"pid": pid, "tid": tid, "error": "OpenThread falló"})
            entry.dwSize = ctypes.sizeof(entry)
            has_entry = bool(
                api.kernel32.Thread32Next(ctypes.c_void_p(snapshot), ctypes.byref(entry))
            )
    finally:
        api.close_handle(snapshot)
    rows.sort(
        key=lambda item: (
            int(item["pid"]),
            int(item["tid"]),
            int(item["creation_time_100ns"]),
        )
    )
    errors.sort(key=lambda item: (int(item["pid"]), int(item["tid"])))
    return rows, errors


def _thread_ids(pid: int, api: WindowsApi) -> list[int]:
    raw_snapshot = api.kernel32.CreateToolhelp32Snapshot(api.TH32CS_SNAPTHREAD, 0)
    snapshot = int(raw_snapshot) if raw_snapshot else 0
    if not snapshot or snapshot == api.INVALID_HANDLE_VALUE:
        api.raise_last_error("CreateToolhelp32Snapshot(resume)")
    tids: list[int] = []
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = bool(api.kernel32.Thread32First(ctypes.c_void_p(snapshot), ctypes.byref(entry)))
        while has_entry:
            if int(entry.th32OwnerProcessID) == pid:
                tids.append(int(entry.th32ThreadID))
            entry.dwSize = ctypes.sizeof(entry)
            has_entry = bool(
                api.kernel32.Thread32Next(ctypes.c_void_p(snapshot), ctypes.byref(entry))
            )
    finally:
        api.close_handle(snapshot)
    return tids


def resume_suspended_process(pid: int, api: WindowsApi | None = None) -> list[int]:
    """Reanuda la raíz creada con CREATE_SUSPENDED después de asignarla al Job."""
    api = api or WindowsApi()
    tids = _thread_ids(pid, api)
    if len(tids) != 1:
        raise ContractError(f"raíz suspendida no tiene exactamente un hilo primario: {tids!r}")
    raw_thread = api.kernel32.OpenThread(api.THREAD_SUSPEND_RESUME, False, tids[0])
    if not raw_thread:
        api.raise_last_error("OpenThread(resume)")
    handle = int(raw_thread)
    try:
        previous = int(api.kernel32.ResumeThread(ctypes.c_void_p(handle)))
        if previous == 0xFFFFFFFF:
            api.raise_last_error("ResumeThread")
        if previous < 1:
            raise ContractError("la raíz no estaba suspendida antes de asignarla al Job")
    finally:
        api.close_handle(handle)
    return tids


def process_tree_snapshot(job: WindowsJob | WindowsExternalJob) -> dict[str, Any]:
    """Censa PID/TID con creation time para evitar reutilización de PID."""
    pids = sorted(job.process_ids())
    processes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for pid in pids:
        try:
            processes.append(process_metrics(pid, job.api))
        except OSError as exc:
            errors.append({"pid": pid, "error": str(exc)})
    processes.sort(key=lambda item: (int(item["pid"]), int(item["creation_time_100ns"])))
    errors.sort(key=lambda item: int(item["pid"]))
    threads, thread_errors = thread_affinities(set(pids), job.api)
    return {
        "pids": pids,
        "processes": processes,
        "threads": threads,
        "process_query_errors": errors,
        "thread_query_errors": thread_errors,
    }


def system_cpu_times(api: WindowsApi | None = None) -> dict[str, int]:
    """Mide CPU acumulada del host para evidenciar deriva externa sin inferir capacidad."""
    api = api or WindowsApi()
    idle = _FileTime()
    kernel = _FileTime()
    user = _FileTime()
    if not api.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        api.raise_last_error("GetSystemTimes")
    return {
        "idle_100ns": idle.as_int(),
        "kernel_100ns": kernel.as_int(),
        "user_100ns": user.as_int(),
    }


def try_expand_current_process_affinity(requested_mask: int) -> dict[str, Any]:
    """Probe negativo: intenta ampliar la afinidad y consulta el resultado efectivo."""
    api = WindowsApi()
    handle = api.open_process(os.getpid(), write_affinity=True)
    try:
        ctypes.set_last_error(0)
        succeeded = bool(
            api.kernel32.SetProcessAffinityMask(
                ctypes.c_void_p(handle), ctypes.c_size_t(requested_mask)
            )
        )
        error = ctypes.get_last_error()
        process_mask = ctypes.c_size_t(0)
        system_mask = ctypes.c_size_t(0)
        if not api.kernel32.GetProcessAffinityMask(
            ctypes.c_void_p(handle), ctypes.byref(process_mask), ctypes.byref(system_mask)
        ):
            api.raise_last_error("GetProcessAffinityMask(probe)")
        return {
            "requested_mask": requested_mask,
            "set_succeeded": succeeded,
            "last_error": error,
            "effective_mask": int(process_mask.value),
            "effective_logical_cpu_count": _bit_count(int(process_mask.value)),
        }
    finally:
        api.close_handle(handle)
