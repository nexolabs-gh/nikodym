"""Muestreo CPU/memoria/disco a 250 ms y guardas externas H9R."""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from .artifacts import JsonlRecorder, census_roots, volume_free_bytes
from .contracts import (
    MAX_SAMPLE_GAP_SECONDS,
    RUN_MIN_AVAILABLE_PHYSICAL_BYTES,
    RUN_MIN_COMMIT_HEADROOM_BYTES,
    RUN_MIN_DISK_FREE_BYTES,
    SAMPLE_INTERVAL_SECONDS,
    ContractError,
)
from .windows_job import (
    WindowsExternalJob,
    WindowsJob,
    process_metrics,
    process_tree_snapshot,
    system_cpu_times,
    system_memory_status,
    system_process_resource_snapshot,
)

POOL_ENVIRONMENT_KEYS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


class Sensor(Protocol):
    """Fuente inyectable para controles de guardas sin presionar el host."""

    def sample(self) -> dict[str, Any]:
        """Devuelve una muestra completa o lanza si el sensor falló."""


class LiveWindowsSensor:
    """Sensor calificable que separa Job, procesos, sistema, disco y supervisor."""

    def __init__(
        self,
        *,
        job: WindowsJob,
        roots: Mapping[str, Path],
        volume_path: Path,
        pool_environment: Mapping[str, str],
        client_pid: int | None = None,
        client_job: WindowsExternalJob | None = None,
    ) -> None:
        self.job = job
        self.roots = dict(roots)
        self.volume_path = volume_path
        self.supervisor_pid = os.getpid()
        self.pool_environment = dict(pool_environment)
        self.client_pid = client_pid
        self.client_job = client_job

    def sample(self) -> dict[str, Any]:
        """Toma una observación kernel/filesystem sin transformar outputs."""
        tree = process_tree_snapshot(self.job)
        client: dict[str, Any] | None = None
        if self.client_pid is not None:
            try:
                client = process_metrics(self.client_pid, self.job.api)
            except OSError as exc:
                # El cliente puede haber terminado entre dos muestras; su Job externo conserva
                # accounting autoritativo y el supervisor reconcilia el return code/cleanup.
                client = {
                    "pid": self.client_pid,
                    "terminated_between_samples": True,
                    "query_error": str(exc),
                }
        client_job_snapshot: dict[str, Any] | None = None
        if self.client_job is not None:
            client_job_snapshot = {
                "accounting": self.client_job.accounting(),
                "tree": process_tree_snapshot(self.client_job),
            }
        excluded_pids = {self.supervisor_pid}
        excluded_pids.update(
            int(pid) for pid in cast(list[int], tree.get("pids", [])) if isinstance(pid, int)
        )
        if self.client_pid is not None:
            excluded_pids.add(self.client_pid)
        if client_job_snapshot is not None:
            client_tree = cast(Mapping[str, Any], client_job_snapshot["tree"])
            excluded_pids.update(
                int(pid)
                for pid in cast(list[int], client_tree.get("pids", []))
                if isinstance(pid, int)
            )
        host_processes = system_process_resource_snapshot(
            excluded_pids=excluded_pids, api=self.job.api
        )
        return {
            "job": self.job.accounting(),
            "tree": tree,
            "system_memory": system_memory_status(self.job.api),
            "system_cpu": system_cpu_times(self.job.api),
            "disk": {
                "volume_free_bytes": volume_free_bytes(self.volume_path),
                "roots": census_roots(self.roots),
            },
            "external_processes": {
                "supervisor": process_metrics(self.supervisor_pid, self.job.api),
                "client": client,
                "client_job": client_job_snapshot,
                "host_processes": host_processes,
            },
            "native_pools": dict(self.pool_environment),
        }


class SequenceSensor:
    """Sensor determinista usado por controles negativos; nunca es evidencia de calibración."""

    def __init__(self, samples: list[dict[str, Any] | BaseException]) -> None:
        self._samples = samples
        self._index = 0

    def sample(self) -> dict[str, Any]:
        """Entrega la siguiente muestra y repite la última si se agota la secuencia."""
        if not self._samples:
            raise RuntimeError("SequenceSensor no tiene muestras")
        index = min(self._index, len(self._samples) - 1)
        self._index += 1
        value = self._samples[index]
        if isinstance(value, BaseException):
            raise value
        return dict(value)


def _working_set_sum(tree: Mapping[str, Any]) -> int:
    raw_processes = tree.get("processes")
    if not isinstance(raw_processes, list):
        return 0
    return sum(
        int(process.get("working_set_bytes", 0))
        for process in raw_processes
        if isinstance(process, dict)
    )


def _max_thread_count(tree: Mapping[str, Any]) -> int:
    threads = tree.get("threads")
    return len(threads) if isinstance(threads, list) else 0


_DISK_ROOTS = frozenset({"inputs", "bundle", "scratch", "outputs", "telemetry"})
_INCREMENTAL_DISK_ROOTS = frozenset({"scratch", "outputs", "telemetry"})
_HOST_DISK_NOISE_TOLERANCE_BYTES = 16 * 1024 * 1024
_HOST_CPU_CONTAMINATION_FRACTION = 0.90
_HOST_COMMIT_CONTAMINATION_BYTES = 64 * 1024 * 1024
_HOST_QUERY_ERROR_CATEGORIES = frozenset(
    {"protected_or_system", "process_exited", "unexpected_query_failure"}
)
_PROCESS_METRIC_FIELDS = frozenset(
    {
        "pid",
        "creation_time_100ns",
        "cpu_user_100ns",
        "cpu_kernel_100ns",
        "page_fault_count",
        "working_set_bytes",
        "peak_working_set_bytes",
        "pagefile_bytes",
        "peak_pagefile_bytes",
        "private_usage_bytes",
        "affinity_mask",
        "system_affinity_mask",
        "logical_cpu_count_effective",
        "processor_groups",
        "io",
    }
)
_IO_COUNTER_FIELDS = frozenset(
    {
        "read_operations",
        "write_operations",
        "other_operations",
        "read_bytes",
        "write_bytes",
        "other_bytes",
    }
)
_CUMULATIVE_PROCESS_FIELDS = (
    "cpu_user_100ns",
    "cpu_kernel_100ns",
    "page_fault_count",
    "peak_working_set_bytes",
    "peak_pagefile_bytes",
)


def _record_object(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{context} no es objeto")
    return value


def _record_non_negative_int(value: Any, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{context} no es entero no negativo")
    return value


def _record_non_negative_number(value: Any, *, context: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ContractError(f"{context} no es número no negativo finito")
    return float(value)


def _validate_io_counters(value: Any, *, context: str) -> dict[str, int]:
    counters = _record_object(value, context=context)
    if set(counters) != _IO_COUNTER_FIELDS:
        raise ContractError(f"{context} no tiene los seis contadores exactos")
    return {
        name: _record_non_negative_int(counters[name], context=f"{context}.{name}")
        for name in sorted(_IO_COUNTER_FIELDS)
    }


def _validate_process_metric_rows(value: Any, *, context: str) -> list[dict[str, Any]]:
    """Cierra ProcessMemory/Times/I/O/Affinity para cada identidad PID+creation."""
    if not isinstance(value, list):
        raise ContractError(f"{context} no es lista")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item = _record_object(raw, context=f"{context}[{index}]")
        if set(item) != _PROCESS_METRIC_FIELDS:
            raise ContractError(f"{context}[{index}] no tiene campos instrumentales exactos")
        integers = {
            name: _record_non_negative_int(item[name], context=f"{context}[{index}].{name}")
            for name in _PROCESS_METRIC_FIELDS - {"processor_groups", "io"}
        }
        raw_groups = item["processor_groups"]
        if not isinstance(raw_groups, list):
            raise ContractError(f"{context}[{index}].processor_groups no es lista")
        groups = [
            _record_non_negative_int(group, context=f"{context}[{index}].processor_groups")
            for group in raw_groups
        ]
        io = _validate_io_counters(item["io"], context=f"{context}[{index}].io")
        if (
            integers["pid"] < 1
            or integers["creation_time_100ns"] < 1
            or integers["affinity_mask"] < 1
            or integers["system_affinity_mask"] < 1
            or integers["logical_cpu_count_effective"] < 1
            or integers["affinity_mask"].bit_count() != integers["logical_cpu_count_effective"]
            or bool(integers["affinity_mask"] & ~integers["system_affinity_mask"])
            or not groups
            or groups != sorted(set(groups))
            or integers["peak_working_set_bytes"] < integers["working_set_bytes"]
            or integers["peak_pagefile_bytes"] < integers["pagefile_bytes"]
        ):
            raise ContractError(f"{context}[{index}] contiene identidad/contadores imposibles")
        normalized.append({**integers, "processor_groups": groups, "io": io})
    expected_order = sorted(
        normalized,
        key=lambda item: (item["pid"], item["creation_time_100ns"]),
    )
    identities = {(item["pid"], item["creation_time_100ns"]) for item in normalized}
    pids = {item["pid"] for item in normalized}
    if (
        normalized != expected_order
        or len(identities) != len(normalized)
        or len(pids) != len(normalized)
    ):
        raise ContractError(f"{context} repite PID/creation o no tiene orden canónico")
    return normalized


def _validate_process_query_errors(value: Any, *, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError(f"{context} no es lista")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item = _record_object(raw, context=f"{context}[{index}]")
        if set(item) != {"pid", "error"}:
            raise ContractError(f"{context}[{index}] no tiene campos exactos")
        pid = _record_non_negative_int(item["pid"], context=f"{context}[{index}].pid")
        if pid < 1 or not isinstance(item["error"], str) or not item["error"]:
            raise ContractError(f"{context}[{index}] no acredita PID/error")
        normalized.append({"pid": pid, "error": item["error"]})
    if normalized != sorted(normalized, key=lambda item: item["pid"]) or len(
        {item["pid"] for item in normalized}
    ) != len(normalized):
        raise ContractError(f"{context} repite PID o no tiene orden canónico")
    return normalized


def _validate_thread_query_errors(value: Any, *, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError(f"{context} no es lista")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item = _record_object(raw, context=f"{context}[{index}]")
        if set(item) != {"pid", "tid", "error"}:
            raise ContractError(f"{context}[{index}] no tiene campos exactos")
        pid = _record_non_negative_int(item["pid"], context=f"{context}[{index}].pid")
        tid = _record_non_negative_int(item["tid"], context=f"{context}[{index}].tid")
        if pid < 1 or tid < 1 or not isinstance(item["error"], str) or not item["error"]:
            raise ContractError(f"{context}[{index}] no acredita PID/TID/error")
        normalized.append({"pid": pid, "tid": tid, "error": item["error"]})
    if normalized != sorted(normalized, key=lambda item: (item["pid"], item["tid"])) or len(
        {(item["pid"], item["tid"]) for item in normalized}
    ) != len(normalized):
        raise ContractError(f"{context} repite PID/TID o no tiene orden canónico")
    return normalized


def _root_allocated_bytes(roots: Mapping[str, Any], name: str, *, context: str) -> int:
    root = _record_object(roots.get(name), context=f"{context}.{name}")
    return _record_non_negative_int(
        root.get("allocated_bytes"), context=f"{context}.{name}.allocated_bytes"
    )


def _root_logical_bytes(roots: Mapping[str, Any], name: str, *, context: str) -> int:
    root = _record_object(roots.get(name), context=f"{context}.{name}")
    return _record_non_negative_int(
        root.get("logical_bytes"), context=f"{context}.{name}.logical_bytes"
    )


def _client_working_set(record: Mapping[str, Any]) -> int:
    external = _record_object(record["external_processes"], context="external_processes")
    raw_client = external.get("client")
    if not isinstance(raw_client, Mapping):
        return 0
    return int(raw_client.get("working_set_bytes", 0))


def _client_job_peak(record: Mapping[str, Any]) -> int:
    external = _record_object(record["external_processes"], context="external_processes")
    raw_client_job = external.get("client_job")
    if not isinstance(raw_client_job, Mapping):
        return 0
    accounting = _record_object(raw_client_job.get("accounting"), context="client_job.accounting")
    return int(accounting["peak_job_memory_commit_bytes"])


def _validate_host_process_rows(value: Any, *, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError(f"{context} no es lista")
    expected = {
        "pid",
        "creation_time_100ns",
        "image_name",
        "cpu_user_100ns",
        "cpu_kernel_100ns",
        "private_usage_bytes",
        "working_set_bytes",
        "io",
    }
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        process = _record_object(raw, context=f"{context}[{index}]")
        if set(process) != expected:
            raise ContractError(f"{context}[{index}] no tiene campos host exactos")
        row = {
            name: _record_non_negative_int(process[name], context=f"{context}[{index}].{name}")
            for name in expected - {"image_name", "io"}
        }
        image_name = process["image_name"]
        if (
            row["pid"] < 1
            or row["creation_time_100ns"] < 1
            or not isinstance(image_name, str)
            or not image_name
        ):
            raise ContractError(f"{context}[{index}] no acredita identidad host")
        normalized.append(
            {
                **row,
                "image_name": image_name,
                "io": _validate_io_counters(process["io"], context=f"{context}[{index}].io"),
            }
        )
    expected_order = sorted(normalized, key=lambda item: (item["pid"], item["creation_time_100ns"]))
    identities = {(item["pid"], item["creation_time_100ns"]) for item in normalized}
    if normalized != expected_order or len(identities) != len(normalized):
        raise ContractError(f"{context} repite PID+creation o no tiene orden canónico")
    return normalized


def _host_process_counters(record: Mapping[str, Any]) -> dict[tuple[int, int], dict[str, int]]:
    """Extrae contadores acumulados por identidad PID+creation, sin confiar en resúmenes."""
    external = _record_object(record.get("external_processes"), context="external_processes")
    host = _record_object(external.get("host_processes"), context="host_processes")
    processes = _validate_host_process_rows(
        host.get("processes"), context="host_processes.processes"
    )
    counters: dict[tuple[int, int], dict[str, int]] = {}
    for index, raw_process in enumerate(processes):
        process = _record_object(raw_process, context=f"host_processes[{index}]")
        identity = (
            _record_non_negative_int(process.get("pid"), context=f"host[{index}].pid"),
            _record_non_negative_int(
                process.get("creation_time_100ns"), context=f"host[{index}].creation_time_100ns"
            ),
        )
        if identity in counters:
            raise ContractError("host_processes repite identidad PID+creation")
        io_counters = _record_object(process["io"], context=f"host[{index}].io")
        counters[identity] = {
            "cpu_100ns": _record_non_negative_int(
                process.get("cpu_user_100ns"), context=f"host[{index}].cpu_user_100ns"
            )
            + _record_non_negative_int(
                process.get("cpu_kernel_100ns"), context=f"host[{index}].cpu_kernel_100ns"
            ),
            "private_usage_bytes": _record_non_negative_int(
                process.get("private_usage_bytes"),
                context=f"host[{index}].private_usage_bytes",
            ),
            "write_bytes": _record_non_negative_int(
                io_counters.get("write_bytes"),
                context=f"host[{index}].io.write_bytes",
            ),
        }
    return counters


def _validate_host_process_coverage(
    host: Mapping[str, Any],
    *,
    previous_host: Mapping[tuple[int, int], Mapping[str, int]] | None,
    context: str,
) -> tuple[bool, str | None]:
    processes = host.get("processes")
    errors = host.get("query_errors")
    coverage = _record_object(host.get("coverage"), context=f"{context}.coverage")
    if not isinstance(processes, list) or not isinstance(errors, list):
        raise ContractError(f"{context}: processes/query_errors no son listas")
    required_coverage = {
        "enumerated_process_count",
        "observed_process_count",
        "query_error_count",
        "expected_query_error_count",
        "unexpected_query_error_count",
        "snapshot_complete",
    }
    if set(coverage) != required_coverage:
        raise ContractError(f"{context}.coverage no tiene campos exactos")
    counts = {
        name: _record_non_negative_int(coverage[name], context=f"{context}.coverage.{name}")
        for name in required_coverage - {"snapshot_complete"}
    }
    if not isinstance(coverage["snapshot_complete"], bool):
        raise ContractError(f"{context}.coverage.snapshot_complete no es booleano")
    if (
        counts["observed_process_count"] != len(processes)
        or counts["query_error_count"] != len(errors)
        or counts["enumerated_process_count"] != len(processes) + len(errors)
        or counts["expected_query_error_count"] + counts["unexpected_query_error_count"]
        != len(errors)
    ):
        raise ContractError(f"{context}.coverage no reconcilia el censo host")
    unexpected = 0
    prior_pids = {identity[0] for identity in previous_host or {}}
    material_prior_error = False
    error_pids: list[int] = []
    for index, raw_error in enumerate(errors):
        error = _record_object(raw_error, context=f"{context}.query_errors[{index}]")
        if set(error) != {"pid", "image_name", "category", "winerror", "error"}:
            raise ContractError(f"{context}.query_errors[{index}] no tiene campos exactos")
        pid = _record_non_negative_int(error["pid"], context=f"{context}.query_errors[{index}].pid")
        if pid < 1:
            raise ContractError(f"{context}.query_errors[{index}].pid no es positivo")
        error_pids.append(pid)
        if not isinstance(error["image_name"], str) or not isinstance(error["error"], str):
            raise ContractError(f"{context}.query_errors[{index}] no contiene texto")
        category = error["category"]
        if category not in _HOST_QUERY_ERROR_CATEGORIES:
            raise ContractError(f"{context}.query_errors[{index}].category desconocida")
        winerror = error["winerror"]
        if winerror is not None and (
            isinstance(winerror, bool) or not isinstance(winerror, int) or winerror < 0
        ):
            raise ContractError(f"{context}.query_errors[{index}].winerror inválido")
        unexpected += category == "unexpected_query_failure"
        material_prior_error = material_prior_error or pid in prior_pids
    process_pids = {
        int(process["pid"])
        for process in _validate_host_process_rows(processes, context=f"{context}.processes")
    }
    if error_pids != sorted(set(error_pids)) or process_pids & set(error_pids):
        raise ContractError(f"{context}: PIDs observados/errores se repiten o solapan")
    if counts["unexpected_query_error_count"] != unexpected or coverage[
        "snapshot_complete"
    ] is not (unexpected == 0):
        raise ContractError(f"{context}.coverage no deriva de query_errors")
    if unexpected:
        return False, "snapshot host contiene errores de consulta inesperados"
    if material_prior_error:
        return False, "un PID host previamente medido dejó de ser consultable"
    return True, None


def _positive_host_deltas(
    previous: Mapping[tuple[int, int], Mapping[str, int]],
    current: Mapping[tuple[int, int], Mapping[str, int]],
) -> dict[str, int]:
    totals = {"cpu_100ns": 0, "private_usage_bytes": 0, "write_bytes": 0}
    for identity, counters in current.items():
        before = previous.get(identity, {})
        for name in totals:
            totals[name] += max(0, int(counters[name]) - int(before.get(name, 0)))
    return totals


def _system_nonidle_cpu_100ns(record: Mapping[str, Any]) -> int:
    cpu = _record_object(record.get("system_cpu"), context="system_cpu")
    user = _record_non_negative_int(cpu.get("user_100ns"), context="system_cpu.user_100ns")
    kernel = _record_non_negative_int(cpu.get("kernel_100ns"), context="system_cpu.kernel_100ns")
    idle = _record_non_negative_int(cpu.get("idle_100ns"), context="system_cpu.idle_100ns")
    return user + max(0, kernel - idle)


def _owned_cpu_100ns(record: Mapping[str, Any]) -> int:
    job = _record_object(record.get("job"), context="job")
    total = _record_non_negative_int(
        job.get("total_user_time_100ns"), context="job.total_user_time_100ns"
    ) + _record_non_negative_int(
        job.get("total_kernel_time_100ns"), context="job.total_kernel_time_100ns"
    )
    external = _record_object(record.get("external_processes"), context="external_processes")
    supervisor = _record_object(external.get("supervisor"), context="external_processes.supervisor")
    total += _record_non_negative_int(
        supervisor.get("cpu_user_100ns"), context="supervisor.cpu_user_100ns"
    ) + _record_non_negative_int(
        supervisor.get("cpu_kernel_100ns"), context="supervisor.cpu_kernel_100ns"
    )
    raw_client_job = external.get("client_job")
    if isinstance(raw_client_job, Mapping):
        accounting = _record_object(
            raw_client_job.get("accounting"), context="client_job.accounting"
        )
        total += _record_non_negative_int(
            accounting.get("total_user_time_100ns"), context="client_job.total_user_time_100ns"
        ) + _record_non_negative_int(
            accounting.get("total_kernel_time_100ns"),
            context="client_job.total_kernel_time_100ns",
        )
    else:
        raw_client = external.get("client")
        if isinstance(raw_client, Mapping) and "cpu_user_100ns" in raw_client:
            total += _record_non_negative_int(
                raw_client.get("cpu_user_100ns"), context="client.cpu_user_100ns"
            ) + _record_non_negative_int(
                raw_client.get("cpu_kernel_100ns"), context="client.cpu_kernel_100ns"
            )
    return total


def _job_memory_usage_information(accounting: Mapping[str, Any], *, context: str) -> int | None:
    """Valida la bicondicional del contador JobMemoryUsageInformation."""
    supported = accounting.get("memory_usage_information_supported")
    if not isinstance(supported, bool):
        raise ContractError(f"{context}.memory_usage_information_supported no es booleano")
    current = accounting.get("current_job_memory_commit_bytes")
    if supported:
        return _record_non_negative_int(
            current, context=f"{context}.current_job_memory_commit_bytes"
        )
    if current is not None:
        raise ContractError(f"{context}: unsupported exige current_job_memory_commit_bytes null")
    return None


def _owned_commit_bytes(record: Mapping[str, Any]) -> int:
    job = _record_object(record.get("job"), context="job")
    total = _job_memory_usage_information(job, context="job") or 0
    external = _record_object(record.get("external_processes"), context="external_processes")
    supervisor = _record_object(external.get("supervisor"), context="supervisor")
    total += _record_non_negative_int(
        supervisor.get("private_usage_bytes"), context="supervisor.private_usage_bytes"
    )
    raw_client_job = external.get("client_job")
    if isinstance(raw_client_job, Mapping):
        accounting = _record_object(
            raw_client_job.get("accounting"), context="client_job.accounting"
        )
        total += _job_memory_usage_information(accounting, context="client_job") or 0
    else:
        raw_client = external.get("client")
        if isinstance(raw_client, Mapping):
            total += _record_non_negative_int(
                raw_client.get("private_usage_bytes"), context="client.private_usage_bytes"
            )
    return total


def derive_consumer_window_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    boundary_events: Sequence[Mapping[str, Any]],
    ready_monotonic_ns: int,
    tree_empty_monotonic_ns: int,
    baseline_roots: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deriva ventana exacta y cobertura bracket sin recortar máximos globales."""
    records, _ = _split_sensor_records(records)
    if not records:
        raise ContractError("ventana consumidor exige muestras crudas")
    if set(baseline_roots) != _DISK_ROOTS:
        raise ContractError("ventana consumidor exige las cinco raíces baseline")
    starts = [event for event in boundary_events if event.get("event") == "first_open_or_byte"]
    ends = [event for event in boundary_events if event.get("event") == "rename_complete"]
    if len(starts) != 1 or len(ends) != 1:
        raise ContractError("ventana consumidor exige first-open/byte y rename exactos")
    provider = starts[0].get("provider")
    if provider not in {
        "harness_owned_consumer_open_v1",
        "harness_owned_candidate_http_ingress_v1",
    }:
        raise ContractError("ventana consumidor carece de provider harness-owned")
    start_ns = _record_non_negative_int(
        starts[0].get("monotonic_ns"), context="consumer_window.start_monotonic_ns"
    )
    end_ns = _record_non_negative_int(
        ends[0].get("monotonic_ns"), context="consumer_window.end_monotonic_ns"
    )
    ready_ns = _record_non_negative_int(ready_monotonic_ns, context="consumer_window.ready_ns")
    empty_ns = _record_non_negative_int(
        tree_empty_monotonic_ns, context="consumer_window.tree_empty_ns"
    )
    if not ready_ns <= start_ns <= end_ns <= empty_ns:
        raise ContractError("ventana consumidor cae fuera de READY→árbol vacío")
    normalized = [
        _validate_resource_sample_shape(raw, context=f"consumer_window.records[{index}]")
        for index, raw in enumerate(records)
    ]
    for index, record in enumerate(normalized):
        _validate_tree_snapshot(
            record.get("tree"), context=f"consumer_window.records[{index}].tree"
        )
    timestamps = [
        _record_non_negative_int(
            record.get("monotonic_ns"), context="consumer_window.record.monotonic_ns"
        )
        for record in normalized
    ]
    if timestamps != sorted(timestamps):
        raise ContractError("ventana consumidor recibe muestras fuera de orden")
    before = [record for record in normalized if int(record["monotonic_ns"]) <= start_ns]
    after = [record for record in normalized if int(record["monotonic_ns"]) >= end_ns]
    inside = [record for record in normalized if start_ns <= int(record["monotonic_ns"]) <= end_ns]
    if not before or not after:
        raise ContractError("ventana consumidor carece de brackets READY/tree-empty")
    start_bracket = before[-1]
    end_bracket = after[0]
    selected_by_ordinal: dict[int, Mapping[str, Any]] = {}
    for record in (start_bracket, *inside, end_bracket):
        ordinal = _record_non_negative_int(
            record.get("sample_ordinal"), context="consumer_window.sample_ordinal"
        )
        selected_by_ordinal[ordinal] = record
    sample_ordinals = sorted(selected_by_ordinal)
    # Los brackets forman parte de la cobertura declarada. Excluirlos cuando hay una muestra
    # interior perdería máximos ocurridos entre el último tick interior y la publicación final.
    peak_records = list(selected_by_ordinal.values())
    baseline_allocated = sum(
        _root_allocated_bytes(
            cast(Mapping[str, Any], baseline_roots), name, context="consumer_window.baseline"
        )
        for name in _INCREMENTAL_DISK_ROOTS
    )

    def incremental_allocated(record: Mapping[str, Any]) -> int:
        roots = _record_object(
            _record_object(record.get("disk"), context="consumer_window.disk").get("roots"),
            context="consumer_window.disk.roots",
        )
        observed = sum(
            _root_allocated_bytes(roots, name, context="consumer_window.disk.roots")
            for name in _INCREMENTAL_DISK_ROOTS
        )
        return max(0, observed - baseline_allocated)

    def job_cpu(record: Mapping[str, Any]) -> int:
        job = _record_object(record.get("job"), context="consumer_window.job")
        return _record_non_negative_int(
            job.get("total_user_time_100ns"), context="consumer_window.job.user"
        ) + _record_non_negative_int(
            job.get("total_kernel_time_100ns"), context="consumer_window.job.kernel"
        )

    window = {
        "provider": provider,
        "start_monotonic_ns": start_ns,
        "end_monotonic_ns": end_ns,
        "wall_seconds": (end_ns - start_ns) / 1_000_000_000,
        "sample_ordinals": sample_ordinals,
        "records": len(sample_ordinals),
        "coverage": {
            "start_bracket_ordinal": int(start_bracket["sample_ordinal"]),
            "end_bracket_ordinal": int(end_bracket["sample_ordinal"]),
            "inside_sample_ordinals": [int(record["sample_ordinal"]) for record in inside],
            "start_gap_ns": start_ns - int(start_bracket["monotonic_ns"]),
            "end_gap_ns": int(end_bracket["monotonic_ns"]) - end_ns,
            "resolution": "inside_samples" if inside else "bracketed",
        },
        "peak_tree_working_set_bytes": max(
            _working_set_sum(_record_object(record.get("tree"), context="consumer_window.tree"))
            for record in peak_records
        ),
        # PeakJobMemoryUsed es acumulativo para toda la vida del Job. Este nombre evita
        # atribuir causalmente a la ventana lo ocurrido antes de su frontera inicial.
        "peak_job_memory_commit_bytes_observed_during_window": max(
            _record_non_negative_int(
                _record_object(record.get("job"), context="consumer_window.job").get(
                    "peak_job_memory_commit_bytes"
                ),
                context="consumer_window.job.peak_commit",
            )
            for record in peak_records
        ),
        "peak_incremental_allocated_bytes": max(
            incremental_allocated(record) for record in peak_records
        ),
        "total_job_cpu_delta_100ns": max(0, job_cpu(end_bracket) - job_cpu(start_bracket)),
    }
    overhead = {
        "ready_to_consumer_seconds": (start_ns - ready_ns) / 1_000_000_000,
        "consumer_to_tree_empty_seconds": (empty_ns - end_ns) / 1_000_000_000,
        "envelope_records": len(normalized),
    }
    return window, overhead


def _validate_sensor_failure_record(record: Mapping[str, Any], *, context: str) -> str:
    expected = {
        "record_type",
        "sample_ordinal",
        "monotonic_ns",
        "wall_time_utc",
        "sensor_duration_seconds",
        "gap_seconds",
        "failure",
        "guard_classification",
        "guard_reason",
    }
    if set(record) != expected or record.get("record_type") != "sensor_failure":
        raise ContractError(f"{context}: terminal de sensor no tiene campos exactos")
    _record_non_negative_int(record.get("sample_ordinal"), context=f"{context}.sample_ordinal")
    _record_non_negative_int(record.get("monotonic_ns"), context=f"{context}.monotonic_ns")
    if not isinstance(record.get("wall_time_utc"), str) or not record["wall_time_utc"]:
        raise ContractError(f"{context}.wall_time_utc no es texto")
    _record_non_negative_number(
        record.get("sensor_duration_seconds"), context=f"{context}.sensor_duration_seconds"
    )
    _record_non_negative_number(record.get("gap_seconds"), context=f"{context}.gap_seconds")
    failure = _record_object(record.get("failure"), context=f"{context}.failure")
    if set(failure) != {"kind", "deadline_seconds", "error_type", "message"}:
        raise ContractError(f"{context}.failure no tiene campos exactos")
    if failure["kind"] not in {"timeout", "exception"}:
        raise ContractError(f"{context}.failure.kind fuera del catálogo")
    deadline = failure["deadline_seconds"]
    if failure["kind"] == "timeout":
        _record_non_negative_number(deadline, context=f"{context}.failure.deadline_seconds")
        if float(deadline) <= 0 or failure["error_type"] is not None:
            raise ContractError(f"{context}.failure timeout no reconcilia")
    elif deadline is not None or not isinstance(failure["error_type"], str):
        raise ContractError(f"{context}.failure exception no reconcilia")
    message = failure["message"]
    if not isinstance(message, str) or not message:
        raise ContractError(f"{context}.failure.message no es texto")
    if record["guard_classification"] != "evidence_incomplete" or record["guard_reason"] != message:
        raise ContractError(f"{context}: guarda terminal no deriva del fallo")
    return message


def _split_sensor_records(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], str | None]:
    samples: list[Mapping[str, Any]] = []
    terminal_reason: str | None = None
    for index, raw in enumerate(records):
        record = _record_object(raw, context=f"records[{index}]")
        if record.get("record_type") == "sensor_failure":
            if terminal_reason is not None or index != len(records) - 1:
                raise ContractError("terminal de sensor debe ser único y último")
            terminal_reason = _validate_sensor_failure_record(record, context=f"records[{index}]")
        else:
            if "record_type" in record:
                raise ContractError(f"records[{index}].record_type fuera del catálogo")
            samples.append(record)
    if terminal_reason is not None:
        terminal = _record_object(records[-1], context="records[-1]")
        if terminal["sample_ordinal"] != len(samples):
            raise ContractError("terminal de sensor no reconcilia sample_ordinal")
        if samples and int(terminal["monotonic_ns"]) < int(samples[-1]["monotonic_ns"]):
            raise ContractError("terminal de sensor retrocede reloj monotónico")
    return samples, terminal_reason


def _validate_thread_identities(value: Any, *, context: str) -> list[dict[str, int]]:
    """Cierra PID+TID+creation para que un TID reutilizado no parezca el mismo hilo."""
    if not isinstance(value, list):
        raise ContractError(f"{context}: se esperaba lista")
    normalized: list[dict[str, int]] = []
    expected_fields = {
        "pid",
        "tid",
        "creation_time_100ns",
        "processor_group",
        "affinity_mask",
        "logical_cpu_count_effective",
    }
    for index, raw in enumerate(value):
        item = _record_object(raw, context=f"{context}[{index}]")
        if set(item) != expected_fields:
            raise ContractError(f"{context}[{index}]: identidad TID no tiene campos exactos")
        normalized_item = {
            name: _record_non_negative_int(item.get(name), context=f"{context}[{index}].{name}")
            for name in expected_fields
        }
        if (
            normalized_item["pid"] < 1
            or normalized_item["tid"] < 1
            or normalized_item["creation_time_100ns"] < 1
            or not 1 <= normalized_item["logical_cpu_count_effective"] <= 4
            or normalized_item["affinity_mask"] < 1
            or normalized_item["affinity_mask"].bit_count()
            != normalized_item["logical_cpu_count_effective"]
        ):
            raise ContractError(f"{context}[{index}]: identidad/afinidad TID inválida")
        normalized.append(normalized_item)
    expected_order = sorted(
        normalized,
        key=lambda item: (
            item["pid"],
            item["tid"],
            item["creation_time_100ns"],
        ),
    )
    identities = {(item["pid"], item["tid"], item["creation_time_100ns"]) for item in normalized}
    live_ids = {(item["pid"], item["tid"]) for item in normalized}
    if (
        normalized != expected_order
        or len(identities) != len(normalized)
        or len(live_ids) != len(normalized)
    ):
        raise ContractError(f"{context}: TIDs duplicados o fuera de orden PID/TID/creation")
    return normalized


def _validate_tree_snapshot(
    value: Any,
    *,
    context: str,
) -> tuple[list[dict[str, Any]], list[dict[str, int]]]:
    tree = _record_object(value, context=context)
    expected = {
        "pids",
        "processes",
        "threads",
        "process_query_errors",
        "thread_query_errors",
    }
    if set(tree) != expected:
        raise ContractError(f"{context} no tiene campos exactos de censo PID/TID")
    raw_pids = tree["pids"]
    if not isinstance(raw_pids, list):
        raise ContractError(f"{context}.pids no es lista")
    pids = [
        _record_non_negative_int(pid, context=f"{context}.pids[{index}]")
        for index, pid in enumerate(raw_pids)
    ]
    if any(pid < 1 for pid in pids) or pids != sorted(set(pids)):
        raise ContractError(f"{context}.pids repite PID o no tiene orden canónico")
    processes = _validate_process_metric_rows(tree["processes"], context=f"{context}.processes")
    threads = _validate_thread_identities(tree["threads"], context=f"{context}.threads")
    process_errors = _validate_process_query_errors(
        tree["process_query_errors"], context=f"{context}.process_query_errors"
    )
    thread_errors = _validate_thread_query_errors(
        tree["thread_query_errors"], context=f"{context}.thread_query_errors"
    )
    process_pids = {item["pid"] for item in processes}
    error_pids = {item["pid"] for item in process_errors}
    if process_pids & error_pids or process_pids | error_pids != set(pids):
        raise ContractError(f"{context}: pids no reconcilia processes/query_errors")
    if any(item["pid"] not in set(pids) for item in (*threads, *thread_errors)):
        raise ContractError(f"{context}: un TID no pertenece a los PIDs censados")
    return processes, threads


def validate_process_tree_snapshot(value: Any, *, context: str) -> dict[str, Any]:
    """Valida el censo kernel cerrado usado por Job candidato y Job cliente."""
    tree = _record_object(value, context=context)
    _validate_tree_snapshot(tree, context=context)
    return dict(tree)


def _validate_job_accounting(
    value: Any,
    *,
    context: str,
    source: str,
) -> dict[str, Any]:
    accounting = _record_object(value, context=context)
    expected = {
        "source",
        "total_user_time_100ns",
        "total_kernel_time_100ns",
        "total_user_seconds",
        "total_kernel_seconds",
        "total_page_fault_count",
        "total_processes",
        "active_processes",
        "total_terminated_processes",
        "peak_process_memory_commit_bytes",
        "peak_job_memory_commit_bytes",
        "current_job_memory_commit_bytes",
        "memory_usage_information_supported",
        "io",
    }
    if source == "windows_external_cleanup_job":
        expected.add("root_pid")
    if set(accounting) != expected or accounting["source"] != source:
        raise ContractError(f"{context} no tiene accounting/source exactos")
    integer_names = expected - {
        "source",
        "root_pid",
        "total_user_seconds",
        "total_kernel_seconds",
        "current_job_memory_commit_bytes",
        "memory_usage_information_supported",
        "io",
    }
    normalized = {
        name: _record_non_negative_int(accounting[name], context=f"{context}.{name}")
        for name in integer_names
    }
    user_seconds = _record_non_negative_number(
        accounting["total_user_seconds"], context=f"{context}.total_user_seconds"
    )
    kernel_seconds = _record_non_negative_number(
        accounting["total_kernel_seconds"], context=f"{context}.total_kernel_seconds"
    )
    if not math.isclose(
        user_seconds,
        normalized["total_user_time_100ns"] / 10_000_000,
        rel_tol=0.0,
        abs_tol=1e-12,
    ) or not math.isclose(
        kernel_seconds,
        normalized["total_kernel_time_100ns"] / 10_000_000,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ContractError(f"{context}: segundos no derivan de ticks 100ns")
    current = _job_memory_usage_information(accounting, context=context)
    if current is not None and current > normalized["peak_job_memory_commit_bytes"]:
        raise ContractError(f"{context}: JobMemory actual supera PeakJobMemoryUsed")
    if normalized["active_processes"] > normalized["total_processes"]:
        raise ContractError(f"{context}: active_processes supera total_processes")
    if source == "windows_external_cleanup_job":
        root_pid = accounting["root_pid"]
        if root_pid is not None and (
            isinstance(root_pid, bool) or not isinstance(root_pid, int) or root_pid < 1
        ):
            raise ContractError(f"{context}.root_pid no es PID positivo/null")
    _validate_io_counters(accounting["io"], context=f"{context}.io")
    return dict(accounting)


def _validate_root_census(value: Any, *, context: str) -> dict[str, Any]:
    root = _record_object(value, context=context)
    expected = {
        "root",
        "logical_bytes",
        "allocated_bytes",
        "files",
        "allocation_reliable",
        "allocation_sources",
    }
    if set(root) != expected or not isinstance(root["root"], str) or not root["root"]:
        raise ContractError(f"{context} no tiene censo de raíz exacto")
    for name in ("logical_bytes", "allocated_bytes", "files"):
        _record_non_negative_int(root[name], context=f"{context}.{name}")
    if not isinstance(root["allocation_reliable"], bool):
        raise ContractError(f"{context}.allocation_reliable no es booleano")
    sources = root["allocation_sources"]
    if (
        not isinstance(sources, list)
        or any(not isinstance(source, str) or not source for source in sources)
        or sources != sorted(set(sources))
    ):
        raise ContractError(f"{context}.allocation_sources no es catálogo ordenado")
    return dict(root)


def _validate_native_pool_environment(value: Any, *, context: str) -> dict[str, str]:
    environment = _record_object(value, context=context)
    if set(environment) != set(POOL_ENVIRONMENT_KEYS):
        raise ContractError(f"{context} no enumera las seis variables exactas")
    normalized: dict[str, str] = {}
    for name in POOL_ENVIRONMENT_KEYS:
        raw = environment[name]
        if not isinstance(raw, str) or raw not in {"1", "2", "3", "4"}:
            raise ContractError(f"{context}.{name} no es entero textual 1..4")
        normalized[name] = raw
    return normalized


def _validate_host_attribution_shape(value: Any, *, context: str) -> dict[str, Any]:
    attribution = _record_object(value, context=context)
    expected = {
        "unattributed_cpu_100ns",
        "unattributed_commit_growth_bytes",
        "proven_external",
        "unattributed_observed",
        "proven_processes",
    }
    if set(attribution) != expected:
        raise ContractError(f"{context} no tiene campos exactos")
    cpu = _record_non_negative_int(
        attribution["unattributed_cpu_100ns"], context=f"{context}.unattributed_cpu_100ns"
    )
    commit = _record_non_negative_int(
        attribution["unattributed_commit_growth_bytes"],
        context=f"{context}.unattributed_commit_growth_bytes",
    )
    if not isinstance(attribution["proven_external"], bool) or not isinstance(
        attribution["unattributed_observed"], bool
    ):
        raise ContractError(f"{context}: flags no son booleanos")
    processes = attribution["proven_processes"]
    if not isinstance(processes, list):
        raise ContractError(f"{context}.proven_processes no es lista")
    normalized_processes: list[dict[str, Any]] = []
    process_fields = {
        "pid",
        "creation_time_100ns",
        "image_name",
        "cpu_delta_100ns",
        "private_growth_bytes",
        "write_growth_bytes",
    }
    for index, raw in enumerate(processes):
        process = _record_object(raw, context=f"{context}.proven_processes[{index}]")
        if set(process) != process_fields:
            raise ContractError(f"{context}.proven_processes[{index}] no tiene campos exactos")
        row = {
            name: _record_non_negative_int(
                process[name], context=f"{context}.proven_processes[{index}].{name}"
            )
            for name in process_fields - {"image_name"}
        }
        if (
            row["pid"] < 1
            or row["creation_time_100ns"] < 1
            or not isinstance(process["image_name"], str)
            or not process["image_name"]
            or not any(
                row[name]
                for name in ("cpu_delta_100ns", "private_growth_bytes", "write_growth_bytes")
            )
        ):
            raise ContractError(f"{context}.proven_processes[{index}] no prueba deriva")
        normalized_processes.append({**row, "image_name": process["image_name"]})
    expected_order = sorted(
        normalized_processes, key=lambda item: (item["pid"], item["creation_time_100ns"])
    )
    if normalized_processes != expected_order or len(
        {(item["pid"], item["creation_time_100ns"]) for item in normalized_processes}
    ) != len(normalized_processes):
        raise ContractError(f"{context}.proven_processes repite identidad o no está ordenado")
    if attribution["proven_external"] is not bool(normalized_processes) or attribution[
        "unattributed_observed"
    ] is not bool(cpu or commit):
        raise ContractError(f"{context}: flags no derivan de contadores/lista")
    return dict(attribution)


def _validate_resource_sample_shape(value: Any, *, context: str) -> Mapping[str, Any]:
    record = _record_object(value, context=context)
    expected = {
        "sample_ordinal",
        "monotonic_ns",
        "wall_time_utc",
        "sensor_duration_seconds",
        "gap_seconds",
        "job",
        "tree",
        "system_memory",
        "system_cpu",
        "disk",
        "external_processes",
        "native_pools",
        "host_attribution",
        "guard_classification",
        "guard_reason",
    }
    if set(record) != expected:
        raise ContractError(f"{context} no tiene campos exactos de muestra resources")
    if not isinstance(record["wall_time_utc"], str) or not record["wall_time_utc"]:
        raise ContractError(f"{context}.wall_time_utc no es texto")
    _record_non_negative_int(record["sample_ordinal"], context=f"{context}.sample_ordinal")
    _record_non_negative_int(record["monotonic_ns"], context=f"{context}.monotonic_ns")
    _record_non_negative_number(
        record["sensor_duration_seconds"], context=f"{context}.sensor_duration_seconds"
    )
    _record_non_negative_number(record["gap_seconds"], context=f"{context}.gap_seconds")
    _validate_job_accounting(record["job"], context=f"{context}.job", source="windows_job_object")
    _validate_tree_snapshot(record["tree"], context=f"{context}.tree")
    memory = _record_object(record["system_memory"], context=f"{context}.system_memory")
    memory_fields = {
        "physical_total_bytes",
        "physical_available_bytes",
        "commit_limit_bytes",
        "commit_available_bytes",
        "commit_used_bytes",
        "memory_load_percent",
        "virtual_total_bytes",
        "virtual_available_bytes",
    }
    if set(memory) != memory_fields:
        raise ContractError(f"{context}.system_memory no tiene campos exactos")
    memory_values = {
        name: _record_non_negative_int(memory[name], context=f"{context}.system_memory.{name}")
        for name in memory_fields
    }
    if (
        memory_values["physical_available_bytes"] > memory_values["physical_total_bytes"]
        or memory_values["commit_available_bytes"] > memory_values["commit_limit_bytes"]
        or memory_values["commit_used_bytes"]
        != memory_values["commit_limit_bytes"] - memory_values["commit_available_bytes"]
        or memory_values["virtual_available_bytes"] > memory_values["virtual_total_bytes"]
        or memory_values["memory_load_percent"] > 100
    ):
        raise ContractError(f"{context}.system_memory contiene totales incoherentes")
    cpu = _record_object(record["system_cpu"], context=f"{context}.system_cpu")
    if set(cpu) != {"idle_100ns", "kernel_100ns", "user_100ns"}:
        raise ContractError(f"{context}.system_cpu no tiene campos exactos")
    for name in cpu:
        _record_non_negative_int(cpu[name], context=f"{context}.system_cpu.{name}")
    disk = _record_object(record["disk"], context=f"{context}.disk")
    if set(disk) != {"volume_free_bytes", "roots"}:
        raise ContractError(f"{context}.disk no tiene campos exactos")
    _record_non_negative_int(disk["volume_free_bytes"], context=f"{context}.disk.volume_free_bytes")
    roots = _record_object(disk["roots"], context=f"{context}.disk.roots")
    if set(roots) != _DISK_ROOTS:
        raise ContractError(f"{context}.disk.roots no enumera cinco raíces")
    for name in sorted(_DISK_ROOTS):
        _validate_root_census(roots[name], context=f"{context}.disk.roots.{name}")
    external = _record_object(record["external_processes"], context=f"{context}.external_processes")
    if set(external) != {"supervisor", "client", "client_job", "host_processes"}:
        raise ContractError(f"{context}.external_processes no tiene campos exactos")
    _validate_process_metric_rows(
        [external["supervisor"]], context=f"{context}.external_processes.supervisor"
    )
    client = external["client"]
    if client is not None:
        client_object = _record_object(client, context=f"{context}.external_processes.client")
        if set(client_object) == {"pid", "terminated_between_samples", "query_error"}:
            pid = _record_non_negative_int(
                client_object["pid"], context=f"{context}.external_processes.client.pid"
            )
            if (
                pid < 1
                or client_object["terminated_between_samples"] is not True
                or not isinstance(client_object["query_error"], str)
                or not client_object["query_error"]
            ):
                raise ContractError(f"{context}.external_processes.client terminal inválido")
        else:
            _validate_process_metric_rows(
                [client_object], context=f"{context}.external_processes.client"
            )
    client_job = external["client_job"]
    if client_job is not None:
        client_job_object = _record_object(
            client_job, context=f"{context}.external_processes.client_job"
        )
        if set(client_job_object) != {"accounting", "tree"}:
            raise ContractError(f"{context}.external_processes.client_job no es exacto")
        _validate_job_accounting(
            client_job_object["accounting"],
            context=f"{context}.external_processes.client_job.accounting",
            source="windows_external_cleanup_job",
        )
        _validate_tree_snapshot(
            client_job_object["tree"], context=f"{context}.external_processes.client_job.tree"
        )
    host = _record_object(
        external["host_processes"], context=f"{context}.external_processes.host_processes"
    )
    if set(host) != {"processes", "query_errors", "coverage"}:
        raise ContractError(f"{context}.external_processes.host_processes no es exacto")
    _validate_host_process_rows(
        host["processes"], context=f"{context}.external_processes.host_processes.processes"
    )
    _validate_native_pool_environment(record["native_pools"], context=f"{context}.native_pools")
    _validate_host_attribution_shape(
        record["host_attribution"], context=f"{context}.host_attribution"
    )
    guard = record["guard_classification"]
    reason = record["guard_reason"]
    if guard is not None and (not isinstance(guard, str) or not guard):
        raise ContractError(f"{context}.guard_classification no es texto/null")
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise ContractError(f"{context}.guard_reason no es texto/null")
    if (guard is None) is not (reason is None):
        raise ContractError(f"{context}: guard_classification/reason no son bicondicionales")
    return record


def _derive_expected_host_attribution(
    record: Mapping[str, Any],
    *,
    previous_attribution: Mapping[str, int] | None,
    previous_host_processes: Mapping[tuple[int, int], Mapping[str, int | str]] | None,
) -> tuple[
    dict[str, Any],
    dict[str, int],
    dict[tuple[int, int], dict[str, int | str]],
]:
    system_cpu = _record_object(record["system_cpu"], context="sample.system_cpu")
    system_memory = _record_object(record["system_memory"], context="sample.system_memory")
    external = _record_object(record["external_processes"], context="sample.external_processes")
    current = {
        "system_busy_100ns": int(system_cpu["user_100ns"])
        + int(system_cpu["kernel_100ns"])
        - int(system_cpu["idle_100ns"]),
        # Los helpers compartidos usan accounting del Job cliente completo cuando existe. El PID
        # raíz es sólo fallback sin Job, por lo que nunca se duplica dentro de este total.
        "owned_cpu_100ns": _owned_cpu_100ns(record),
        "system_commit_used_bytes": int(system_memory["commit_used_bytes"]),
        "owned_commit_bytes": _owned_commit_bytes(record),
    }
    attribution: dict[str, Any] = {
        "unattributed_cpu_100ns": 0,
        "unattributed_commit_growth_bytes": 0,
        "proven_external": False,
        "unattributed_observed": False,
        "proven_processes": [],
    }
    if previous_attribution is not None:
        system_busy_delta = max(
            0, current["system_busy_100ns"] - previous_attribution["system_busy_100ns"]
        )
        known_cpu_delta = max(
            0,
            current["owned_cpu_100ns"] - previous_attribution["owned_cpu_100ns"],
        )
        commit_delta = max(
            0,
            current["system_commit_used_bytes"] - previous_attribution["system_commit_used_bytes"],
        )
        known_commit_delta = max(
            0,
            current["owned_commit_bytes"] - previous_attribution["owned_commit_bytes"],
        )
        attribution["unattributed_cpu_100ns"] = max(0, system_busy_delta - known_cpu_delta)
        attribution["unattributed_commit_growth_bytes"] = max(0, commit_delta - known_commit_delta)
        attribution["unattributed_observed"] = bool(
            attribution["unattributed_cpu_100ns"] or attribution["unattributed_commit_growth_bytes"]
        )
    host = _record_object(external["host_processes"], context="sample.host_processes")
    host_rows = _validate_host_process_rows(
        host["processes"], context="sample.host_processes.processes"
    )
    current_host: dict[tuple[int, int], dict[str, int | str]] = {}
    for process in host_rows:
        io = _record_object(process["io"], context="sample.host_processes.io")
        identity = (int(process["pid"]), int(process["creation_time_100ns"]))
        current_host[identity] = {
            "pid": identity[0],
            "creation_time_100ns": identity[1],
            "image_name": str(process["image_name"]),
            "cpu_user_100ns": int(process["cpu_user_100ns"]),
            "cpu_kernel_100ns": int(process["cpu_kernel_100ns"]),
            "private_usage_bytes": int(process["private_usage_bytes"]),
            "write_bytes": int(io["write_bytes"]),
        }
    if previous_host_processes is not None:
        proven: list[dict[str, int | str]] = []
        for identity, process in sorted(current_host.items()):
            previous = previous_host_processes.get(identity)
            current_cpu = int(process["cpu_user_100ns"]) + int(process["cpu_kernel_100ns"])
            previous_cpu = (
                int(previous["cpu_user_100ns"]) + int(previous["cpu_kernel_100ns"])
                if previous is not None
                else 0
            )
            cpu_delta = max(0, current_cpu - previous_cpu)
            private_growth = max(
                0,
                int(process["private_usage_bytes"])
                - (int(previous["private_usage_bytes"]) if previous is not None else 0),
            )
            write_growth = max(
                0,
                int(process["write_bytes"])
                - (int(previous["write_bytes"]) if previous is not None else 0),
            )
            if cpu_delta or private_growth or write_growth:
                proven.append(
                    {
                        "pid": int(process["pid"]),
                        "creation_time_100ns": int(process["creation_time_100ns"]),
                        "image_name": str(process["image_name"]),
                        "cpu_delta_100ns": cpu_delta,
                        "private_growth_bytes": private_growth,
                        "write_growth_bytes": write_growth,
                    }
                )
        attribution["proven_processes"] = proven
        attribution["proven_external"] = bool(proven)
    return attribution, current, current_host


def _validate_process_counters_monotonic(
    processes: Sequence[Mapping[str, Any]],
    *,
    previous: dict[tuple[int, int], dict[str, int]],
    context: str,
) -> None:
    for index, process in enumerate(processes):
        identity = (int(process["pid"]), int(process["creation_time_100ns"]))
        counters = {name: int(process[name]) for name in _CUMULATIVE_PROCESS_FIELDS}
        io = _record_object(process["io"], context=f"{context}[{index}].io")
        counters.update({f"io.{name}": int(io[name]) for name in _IO_COUNTER_FIELDS})
        prior = previous.get(identity)
        if prior is not None and any(counters[name] < prior[name] for name in counters):
            raise ContractError(f"{context}[{index}] retrocede un contador acumulativo")
        previous[identity] = counters


def derive_telemetry_guard(
    records: Sequence[Mapping[str, Any]],
    *,
    baseline_roots: Mapping[str, Mapping[str, Any]],
    baseline_volume_free_bytes: int | None,
    expected_affinity_mask: int | None,
    expected_processor_group: int | None,
    max_gap_seconds: float = MAX_SAMPLE_GAP_SECONDS,
) -> tuple[str | None, str | None]:
    """Recalcula la primera guarda sólo desde sensores crudos y límites atestiguados."""
    sample_records, terminal_reason = _split_sensor_records(records)
    if terminal_reason is not None:
        # Recorre también las muestras completas para no permitir que el terminal tape sensores
        # malformados. La causa terminal prevalece porque impide completar la observación.
        if sample_records:
            derive_telemetry_guard(
                sample_records,
                baseline_roots=baseline_roots,
                baseline_volume_free_bytes=baseline_volume_free_bytes,
                expected_affinity_mask=expected_affinity_mask,
                expected_processor_group=expected_processor_group,
                max_gap_seconds=max_gap_seconds,
            )
        return ("evidence_incomplete", terminal_reason)
    records = sample_records
    if not records:
        return ("evidence_incomplete", "no se capturaron muestras")
    if set(baseline_roots) != _DISK_ROOTS:
        raise ContractError("baseline de telemetry no enumera las cinco raíces")
    if baseline_volume_free_bytes is not None:
        _record_non_negative_int(baseline_volume_free_bytes, context="baseline_volume_free_bytes")
    if max_gap_seconds <= 0:
        raise ContractError("max_gap_seconds debe ser positivo")

    baseline_allocated = sum(
        _root_allocated_bytes(
            cast(Mapping[str, Any], baseline_roots), name, context="baseline_roots"
        )
        for name in _INCREMENTAL_DISK_ROOTS
    )
    first_record = _record_object(records[0], context="records[0]")
    first_disk = _record_object(first_record.get("disk"), context="records[0].disk")
    volume_baseline = (
        baseline_volume_free_bytes
        if baseline_volume_free_bytes is not None
        else _record_non_negative_int(
            first_disk.get("volume_free_bytes"), context="records[0].disk.volume_free_bytes"
        )
    )
    first_memory = _record_object(
        first_record.get("system_memory"), context="records[0].system_memory"
    )
    first_physical = _record_non_negative_int(
        first_memory.get("physical_available_bytes"),
        context="records[0].system_memory.physical_available_bytes",
    )
    first_commit = _record_non_negative_int(
        first_memory.get("commit_available_bytes"),
        context="records[0].system_memory.commit_available_bytes",
    )
    previous_monotonic_ns: int | None = None
    previous_host: dict[tuple[int, int], dict[str, int]] | None = None
    previous_system_nonidle: int | None = None
    previous_owned_cpu: int | None = None
    previous_system_commit_used: int | None = None
    previous_owned_commit: int | None = None
    baseline_host: dict[tuple[int, int], dict[str, int]] | None = None
    previous_candidate_processes: dict[tuple[int, int], dict[str, int]] = {}
    previous_declared_attribution: dict[str, int] | None = None
    previous_declared_host: dict[tuple[int, int], dict[str, int | str]] | None = None
    expected_pool_environment: dict[str, str] | None = None
    low_memory_samples = 0
    high_external_cpu_samples = 0
    high_unattributed_cpu_samples = 0
    high_unattributed_commit_samples = 0

    for index, raw_record in enumerate(records):
        record = _validate_resource_sample_shape(raw_record, context=f"records[{index}]")
        pool_environment = _validate_native_pool_environment(
            record["native_pools"], context=f"records[{index}].native_pools"
        )
        if expected_pool_environment is None:
            expected_pool_environment = pool_environment
        elif pool_environment != expected_pool_environment:
            raise ContractError("native_pools cambia entre muestras")
        if expected_affinity_mask is not None and any(
            int(value) != expected_affinity_mask.bit_count() for value in pool_environment.values()
        ):
            return ("limits_not_applied", "variables de pools no coinciden con CPU efectiva")
        expected_attribution, attribution_state, host_state = _derive_expected_host_attribution(
            record,
            previous_attribution=previous_declared_attribution,
            previous_host_processes=previous_declared_host,
        )
        if record["host_attribution"] != expected_attribution:
            raise ContractError("host_attribution no deriva de contadores crudos")
        previous_declared_attribution = attribution_state
        previous_declared_host = host_state
        monotonic_ns = _record_non_negative_int(
            record.get("monotonic_ns"), context=f"records[{index}].monotonic_ns"
        )
        gap_seconds = (
            0.0
            if previous_monotonic_ns is None
            else (monotonic_ns - previous_monotonic_ns) / 1_000_000_000
        )
        previous_monotonic_ns = monotonic_ns
        duration = _record_non_negative_number(
            record.get("sensor_duration_seconds"),
            context=f"records[{index}].sensor_duration_seconds",
        )
        if gap_seconds > max_gap_seconds or duration > max_gap_seconds:
            return ("evidence_incomplete", "muestra ausente o sensor bloqueado por más de 2 s")

        job_accounting = _record_object(record.get("job"), context=f"records[{index}].job")
        if _job_memory_usage_information(job_accounting, context=f"records[{index}].job") is None:
            return (
                "evidence_incomplete",
                "JobMemoryUsageInformation no está soportado para el Job candidato",
            )

        external = _record_object(
            record.get("external_processes"), context=f"records[{index}].external_processes"
        )
        raw_client_job = external.get("client_job")
        if isinstance(raw_client_job, Mapping):
            client_accounting = _record_object(
                raw_client_job.get("accounting"),
                context=f"records[{index}].client_job.accounting",
            )
            if (
                _job_memory_usage_information(
                    client_accounting,
                    context=f"records[{index}].client_job.accounting",
                )
                is None
            ):
                return (
                    "evidence_incomplete",
                    "JobMemoryUsageInformation no está soportado para el Job cliente",
                )
        host_processes = _record_object(
            external.get("host_processes"), context=f"records[{index}].host_processes"
        )
        coverage_complete, coverage_reason = _validate_host_process_coverage(
            host_processes,
            previous_host=previous_host,
            context=f"records[{index}].host_processes",
        )
        if not coverage_complete:
            return (
                "evidence_incomplete",
                coverage_reason or "cobertura de atribución host incompleta",
            )
        host = _host_process_counters(record)
        if baseline_host is None:
            baseline_host = host
        host_delta = (
            {"cpu_100ns": 0, "private_usage_bytes": 0, "write_bytes": 0}
            if previous_host is None
            else _positive_host_deltas(previous_host, host)
        )
        cumulative_host = _positive_host_deltas(baseline_host, host)
        previous_host = host
        system_nonidle = _system_nonidle_cpu_100ns(record)
        owned_cpu = _owned_cpu_100ns(record)
        system_delta = (
            0
            if previous_system_nonidle is None
            else max(0, system_nonidle - previous_system_nonidle)
        )
        owned_delta = 0 if previous_owned_cpu is None else max(0, owned_cpu - previous_owned_cpu)
        previous_system_nonidle = system_nonidle
        previous_owned_cpu = owned_cpu

        system = _record_object(
            record.get("system_memory"), context=f"records[{index}].system_memory"
        )
        physical = _record_non_negative_int(
            system.get("physical_available_bytes"),
            context=f"records[{index}].physical_available_bytes",
        )
        commit = _record_non_negative_int(
            system.get("commit_available_bytes"),
            context=f"records[{index}].commit_available_bytes",
        )
        commit_used = _record_non_negative_int(
            system.get("commit_used_bytes"),
            context=f"records[{index}].commit_used_bytes",
        )
        owned_commit = _owned_commit_bytes(record)
        system_commit_delta = (
            0
            if previous_system_commit_used is None
            else max(0, commit_used - previous_system_commit_used)
        )
        owned_commit_delta = (
            0 if previous_owned_commit is None else max(0, owned_commit - previous_owned_commit)
        )
        previous_system_commit_used = commit_used
        previous_owned_commit = owned_commit
        low_memory = (
            physical < RUN_MIN_AVAILABLE_PHYSICAL_BYTES or commit < RUN_MIN_COMMIT_HEADROOM_BYTES
        )
        low_memory_samples = low_memory_samples + 1 if low_memory else 0
        if low_memory_samples >= 2:
            # La guarda puede cruzarse por RAM física o por headroom de commit. Atribuirla a otro
            # proceso exige que su crecimiento privado explique la presión realmente observada;
            # una RAM estable no puede convertir cualquier delta externo de un byte en causalidad
            # cuando lo que cayó fue el commit del sistema.
            observed_drop = max(0, first_physical - physical, first_commit - commit)
            if (
                cumulative_host["private_usage_bytes"] > 0
                and cumulative_host["private_usage_bytes"] >= observed_drop
            ):
                return (
                    "host_contamination",
                    "crecimiento privado externo explica el cruce de la guarda de memoria",
                )
            return (
                "safety_abort_system_memory",
                "memoria física o commit bajo el piso durante dos muestras consecutivas",
            )

        disk = _record_object(record.get("disk"), context=f"records[{index}].disk")
        volume_free = _record_non_negative_int(
            disk.get("volume_free_bytes"), context=f"records[{index}].disk.volume_free_bytes"
        )
        if volume_free < RUN_MIN_DISK_FREE_BYTES:
            return ("safety_abort_disk", "espacio libre del volumen bajo 1 GiB")
        roots = _record_object(disk.get("roots"), context=f"records[{index}].disk.roots")
        allocated_now = sum(
            _root_allocated_bytes(roots, name, context=f"records[{index}].disk.roots")
            for name in _INCREMENTAL_DISK_ROOTS
        )
        volume_consumed = max(0, volume_baseline - volume_free)
        own_growth = max(0, allocated_now - baseline_allocated)
        external_loss = max(0, volume_consumed - own_growth)
        if external_loss > _HOST_DISK_NOISE_TOLERANCE_BYTES:
            return (
                "evidence_incomplete",
                "pérdida material del volumen no pudo atribuirse a las raíces; "
                "los bytes I/O globales por PID no acreditan volumen o path",
            )

        tree = _record_object(record.get("tree"), context=f"records[{index}].tree")
        processes, normalized_threads = _validate_tree_snapshot(
            tree, context=f"records[{index}].tree"
        )
        _validate_process_counters_monotonic(
            processes,
            previous=previous_candidate_processes,
            context=f"records[{index}].tree.processes",
        )
        if tree.get("process_query_errors") or tree.get("thread_query_errors"):
            return (
                "evidence_incomplete",
                "no se pudo consultar íntegramente un PID/TID del Job",
            )
        for process in processes:
            item = _record_object(process, context=f"records[{index}].tree.processes[]")
            effective = item.get("logical_cpu_count_effective")
            mask = item.get("affinity_mask")
            groups = item.get("processor_groups")
            if (
                isinstance(effective, bool)
                or not isinstance(effective, int)
                or not 1 <= effective <= 4
                or isinstance(mask, bool)
                or not isinstance(mask, int)
                or mask <= 0
                or mask.bit_count() != effective
                or (expected_affinity_mask is not None and mask != expected_affinity_mask)
                or not isinstance(groups, list)
                or (expected_processor_group is not None and groups != [expected_processor_group])
            ):
                return ("limits_not_applied", "un PID observa CPU/grupo fuera del conjunto")
        for item in normalized_threads:
            mask = item["affinity_mask"]
            group = item["processor_group"]
            if (
                isinstance(mask, bool)
                or not isinstance(mask, int)
                or mask <= 0
                or (expected_affinity_mask is not None and bool(mask & ~expected_affinity_mask))
                or (expected_processor_group is not None and group != expected_processor_group)
            ):
                return ("limits_not_applied", "un TID observa CPU/grupo fuera del conjunto")

        interval_100ns = max(0.0, gap_seconds * 10_000_000)
        high_external_cpu = bool(
            interval_100ns > 0
            and host_delta["cpu_100ns"] >= interval_100ns * _HOST_CPU_CONTAMINATION_FRACTION
        )
        high_external_cpu_samples = high_external_cpu_samples + 1 if high_external_cpu else 0
        if high_external_cpu_samples >= 2:
            return (
                "host_contamination",
                "CPU externa atribuida por PID+creation ocupó una CPU durante dos muestras",
            )
        unattributed_cpu = max(0, system_delta - owned_delta - host_delta["cpu_100ns"])
        high_unattributed_cpu = bool(
            interval_100ns > 0
            and unattributed_cpu >= interval_100ns * _HOST_CPU_CONTAMINATION_FRACTION
        )
        high_unattributed_cpu_samples = (
            high_unattributed_cpu_samples + 1 if high_unattributed_cpu else 0
        )
        if high_unattributed_cpu_samples >= 2:
            return (
                "host_contamination",
                "CPU global material no atribuida persistió durante dos muestras",
            )
        unattributed_commit = max(
            0,
            system_commit_delta - owned_commit_delta - host_delta["private_usage_bytes"],
        )
        high_unattributed_commit = unattributed_commit >= _HOST_COMMIT_CONTAMINATION_BYTES
        high_unattributed_commit_samples = (
            high_unattributed_commit_samples + 1 if high_unattributed_commit else 0
        )
        if high_unattributed_commit_samples >= 2:
            return (
                "host_contamination",
                "commit global material no atribuido persistió durante dos muestras",
            )
    return (None, None)


def summarize_telemetry_records(
    records: Sequence[Mapping[str, Any]],
    *,
    baseline_roots: Mapping[str, Mapping[str, Any]],
    baseline_volume_free_bytes: int | None = None,
    interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
    expected_affinity_mask: int | None = None,
    expected_processor_group: int | None = None,
    terminal_guard_classification: str | None = None,
    terminal_guard_reason: str | None = None,
) -> dict[str, Any]:
    """Reconstruye el summary completo exclusivamente desde muestras crudas.

    ``baseline_roots`` es la observación pre-START firmada en la evidencia. Los high-water,
    identidades de procesos y campos del cliente se recalculan; ningún máximo declarado por el
    productor del agregado se acepta como entrada.
    """
    if not records:
        raise ContractError("summary completo exige al menos una muestra cruda")
    all_records = list(records)
    sample_records, terminal_failure_reason = _split_sensor_records(all_records)
    if not sample_records:
        if terminal_failure_reason is None:
            raise ContractError("summary completo exige al menos una muestra de sensores")
        if terminal_guard_classification not in {None, "evidence_incomplete"} or (
            terminal_guard_reason is not None and terminal_guard_reason != terminal_failure_reason
        ):
            raise ContractError("guarda terminal contradice el fallo crudo del sensor")
        return {
            "records": 0,
            "guard_classification": "evidence_incomplete",
            "guard_reason": terminal_failure_reason,
        }
    records = sample_records
    if set(baseline_roots) != _DISK_ROOTS:
        raise ContractError("baseline de telemetry no enumera las cinco raíces")
    _record_non_negative_number(interval_seconds, context="sample_interval_seconds")
    if interval_seconds <= 0:
        raise ContractError("sample_interval_seconds debe ser positivo")

    normalized: list[Mapping[str, Any]] = []
    previous_monotonic_ns: int | None = None
    observed_process_identities: set[tuple[int, int]] = set()
    observed_client_identities: set[tuple[int, int]] = set()
    observed_guard: str | None = None
    observed_guard_reason: str | None = None
    derived_gaps: list[float] = []

    for index, raw_record in enumerate(records):
        record = _validate_resource_sample_shape(raw_record, context=f"records[{index}]")
        if (
            _record_non_negative_int(
                record.get("sample_ordinal"), context=f"records[{index}].sample_ordinal"
            )
            != index
        ):
            raise ContractError("sample_ordinal no es exacto/contiguo")
        monotonic_ns = _record_non_negative_int(
            record.get("monotonic_ns"), context=f"records[{index}].monotonic_ns"
        )
        if previous_monotonic_ns is not None and monotonic_ns < previous_monotonic_ns:
            raise ContractError("monotonic_ns no es no-decreciente")
        expected_gap = (
            0.0
            if previous_monotonic_ns is None
            else (monotonic_ns - previous_monotonic_ns) / 1_000_000_000
        )
        previous_monotonic_ns = monotonic_ns
        observed_gap = _record_non_negative_number(
            record.get("gap_seconds"), context=f"records[{index}].gap_seconds"
        )
        if not math.isclose(observed_gap, expected_gap, rel_tol=0.0, abs_tol=1e-12):
            raise ContractError(f"records[{index}].gap_seconds no deriva de monotonic_ns")
        derived_gaps.append(expected_gap)
        _record_non_negative_number(
            record.get("sensor_duration_seconds"),
            context=f"records[{index}].sensor_duration_seconds",
        )

        tree = _record_object(record.get("tree"), context=f"records[{index}].tree")
        processes, _threads = _validate_tree_snapshot(tree, context=f"records[{index}].tree")
        observed_process_identities.update(
            (int(process["pid"]), int(process["creation_time_100ns"])) for process in processes
        )

        disk = _record_object(record.get("disk"), context=f"records[{index}].disk")
        roots = _record_object(disk.get("roots"), context=f"records[{index}].disk.roots")
        if set(roots) != _DISK_ROOTS:
            raise ContractError(f"records[{index}] omite o añade una raíz de disco")
        _record_non_negative_int(
            disk.get("volume_free_bytes"), context=f"records[{index}].disk.volume_free_bytes"
        )

        job = _record_object(record.get("job"), context=f"records[{index}].job")
        _job_memory_usage_information(job, context=f"records[{index}].job")
        _record_non_negative_int(
            job.get("peak_job_memory_commit_bytes"),
            context=f"records[{index}].job.peak_job_memory_commit_bytes",
        )
        system = _record_object(
            record.get("system_memory"), context=f"records[{index}].system_memory"
        )
        for name in ("physical_available_bytes", "commit_available_bytes"):
            _record_non_negative_int(
                system.get(name), context=f"records[{index}].system_memory.{name}"
            )
        external = _record_object(
            record.get("external_processes"), context=f"records[{index}].external_processes"
        )
        supervisor = _record_object(
            external.get("supervisor"),
            context=f"records[{index}].external_processes.supervisor",
        )
        _record_non_negative_int(
            supervisor.get("working_set_bytes"),
            context=f"records[{index}].external_processes.supervisor.working_set_bytes",
        )
        raw_client = external.get("client")
        if raw_client is not None:
            client = _record_object(
                raw_client, context=f"records[{index}].external_processes.client"
            )
            if "working_set_bytes" in client:
                _record_non_negative_int(
                    client["working_set_bytes"],
                    context=f"records[{index}].external_processes.client.working_set_bytes",
                )
            if "pid" in client and "creation_time_100ns" in client:
                observed_client_identities.add(
                    (
                        _record_non_negative_int(
                            client["pid"],
                            context=f"records[{index}].external_processes.client.pid",
                        ),
                        _record_non_negative_int(
                            client["creation_time_100ns"],
                            context=(
                                f"records[{index}].external_processes.client.creation_time_100ns"
                            ),
                        ),
                    )
                )
        raw_client_job = external.get("client_job")
        if raw_client_job is not None:
            client_job = _record_object(
                raw_client_job, context=f"records[{index}].external_processes.client_job"
            )
            client_accounting = _record_object(
                client_job.get("accounting"),
                context=f"records[{index}].external_processes.client_job.accounting",
            )
            _job_memory_usage_information(
                client_accounting,
                context=f"records[{index}].external_processes.client_job.accounting",
            )
            _record_non_negative_int(
                client_accounting.get("peak_job_memory_commit_bytes"),
                context=(
                    f"records[{index}].external_processes.client_job.accounting."
                    "peak_job_memory_commit_bytes"
                ),
            )
            client_processes, _client_threads = _validate_tree_snapshot(
                client_job.get("tree"),
                context=f"records[{index}].external_processes.client_job.tree",
            )
            for client_index, client_process in enumerate(client_processes):
                observed_client_identities.add(
                    (
                        _record_non_negative_int(
                            client_process.get("pid"),
                            context=f"records[{index}].client_job.processes[{client_index}].pid",
                        ),
                        _record_non_negative_int(
                            client_process.get("creation_time_100ns"),
                            context=(
                                f"records[{index}].client_job.processes[{client_index}]."
                                "creation_time_100ns"
                            ),
                        ),
                    )
                )

        raw_guard = record.get("guard_classification")
        raw_reason = record.get("guard_reason")
        if raw_guard is not None and not isinstance(raw_guard, str):
            raise ContractError("guard_classification de muestra no es texto/null")
        if raw_reason is not None and not isinstance(raw_reason, str):
            raise ContractError("guard_reason de muestra no es texto/null")
        if observed_guard is not None and raw_guard != observed_guard:
            raise ContractError("una guarda activada desaparece o cambia en muestras posteriores")
        if raw_guard is not None:
            observed_guard = raw_guard
            observed_guard_reason = raw_reason
        normalized.append(record)

    guard_classification, guard_reason = derive_telemetry_guard(
        all_records,
        baseline_roots=baseline_roots,
        baseline_volume_free_bytes=baseline_volume_free_bytes,
        expected_affinity_mask=expected_affinity_mask,
        expected_processor_group=expected_processor_group,
    )
    if terminal_failure_reason is not None:
        observed_guard = "evidence_incomplete"
        observed_guard_reason = terminal_failure_reason
    if observed_guard != guard_classification or observed_guard_reason != guard_reason:
        raise ContractError("guarda declarada no deriva de sensores crudos")
    if (
        terminal_guard_classification is not None
        and terminal_guard_classification != guard_classification
    ):
        raise ContractError("guarda terminal contradice los sensores crudos")
    if terminal_guard_reason is not None and terminal_guard_reason != guard_reason:
        raise ContractError("razón terminal contradice los sensores crudos")
    if terminal_guard_classification is None and terminal_guard_reason is not None:
        raise ContractError("terminal_guard_reason carece de clasificación")
    if guard_classification is None and guard_reason is not None:
        raise ContractError("guard_reason carece de clasificación")

    baseline_allocated = {
        name: _root_allocated_bytes(
            cast(Mapping[str, Any], baseline_roots), name, context="baseline_roots"
        )
        for name in _DISK_ROOTS
    }
    root_high_water: dict[str, dict[str, int]] = {}
    for name in sorted(_DISK_ROOTS):
        peak_allocated = max(
            _root_allocated_bytes(
                _record_object(
                    _record_object(record["disk"], context="record.disk")["roots"],
                    context="record.disk.roots",
                ),
                name,
                context="record.disk.roots",
            )
            for record in normalized
        )
        peak_logical = max(
            _root_logical_bytes(
                _record_object(
                    _record_object(record["disk"], context="record.disk")["roots"],
                    context="record.disk.roots",
                ),
                name,
                context="record.disk.roots",
            )
            for record in normalized
        )
        root_high_water[name] = {
            "peak_logical_bytes": peak_logical,
            "peak_allocated_bytes": peak_allocated,
            "peak_incremental_allocated_bytes": max(0, peak_allocated - baseline_allocated[name]),
        }

    baseline_incremental = sum(baseline_allocated[name] for name in _INCREMENTAL_DISK_ROOTS)
    peak_incremental = max(
        0,
        max(
            sum(
                _root_allocated_bytes(
                    _record_object(
                        _record_object(record["disk"], context="record.disk")["roots"],
                        context="record.disk.roots",
                    ),
                    name,
                    context="record.disk.roots",
                )
                for name in _INCREMENTAL_DISK_ROOTS
            )
            - baseline_incremental
            for record in normalized
        ),
    )

    return {
        "records": len(normalized),
        "sample_interval_seconds": float(interval_seconds),
        "max_gap_seconds": max(derived_gaps),
        "peak_job_memory_commit_bytes": max(
            int(_record_object(record["job"], context="record.job")["peak_job_memory_commit_bytes"])
            for record in normalized
        ),
        "peak_tree_working_set_bytes": max(
            _working_set_sum(_record_object(record["tree"], context="record.tree"))
            for record in normalized
        ),
        "peak_supervisor_working_set_bytes": max(
            int(
                _record_object(
                    _record_object(
                        record["external_processes"], context="record.external_processes"
                    )["supervisor"],
                    context="record.external_processes.supervisor",
                )["working_set_bytes"]
            )
            for record in normalized
        ),
        "peak_client_working_set_bytes": max(_client_working_set(record) for record in normalized),
        "peak_client_job_commit_bytes": max(_client_job_peak(record) for record in normalized),
        "minimum_physical_available_bytes": min(
            int(
                _record_object(record["system_memory"], context="record.system_memory")[
                    "physical_available_bytes"
                ]
            )
            for record in normalized
        ),
        "minimum_commit_available_bytes": min(
            int(
                _record_object(record["system_memory"], context="record.system_memory")[
                    "commit_available_bytes"
                ]
            )
            for record in normalized
        ),
        "minimum_volume_free_bytes": min(
            int(_record_object(record["disk"], context="record.disk")["volume_free_bytes"])
            for record in normalized
        ),
        "maximum_threads_observed": max(
            _max_thread_count(_record_object(record["tree"], context="record.tree"))
            for record in normalized
        ),
        "observed_process_identities": [
            {"pid": pid, "creation_time_100ns": creation}
            for pid, creation in sorted(observed_process_identities)
        ],
        "observed_client_process_identities": [
            {"pid": pid, "creation_time_100ns": creation}
            for pid, creation in sorted(observed_client_identities)
        ],
        "root_high_water": root_high_water,
        "peak_incremental_allocated_bytes": peak_incremental,
        "guard_classification": guard_classification,
        "guard_reason": guard_reason,
    }


class TelemetrySampler:
    """Muestrea desde READY hasta árbol vacío y dispara guardas fail-closed."""

    def __init__(
        self,
        *,
        sensor: Sensor,
        sidecar_path: Path,
        interval_seconds: float = SAMPLE_INTERVAL_SECONDS,
        max_gap_seconds: float = MAX_SAMPLE_GAP_SECONDS,
        baseline_roots: Mapping[str, Mapping[str, Any]] | None = None,
        baseline_volume_free: int | None = None,
        expected_affinity_mask: int | None = None,
        expected_processor_group: int | None = None,
    ) -> None:
        if interval_seconds <= 0 or max_gap_seconds <= interval_seconds:
            raise ValueError("interval/max_gap inválidos")
        self.sensor = sensor
        self.recorder = JsonlRecorder(sidecar_path)
        self.interval_seconds = interval_seconds
        self.max_gap_seconds = max_gap_seconds
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._done = threading.Event()
        self._first_record = threading.Event()
        self._samples: list[dict[str, Any]] = []
        self._classification: str | None = None
        self._reason: str | None = None
        self._last_monotonic_ns: int | None = None
        self._baseline_roots = (
            {name: dict(raw) for name, raw in baseline_roots.items()}
            if baseline_roots is not None
            else None
        )
        self._baseline_volume_free = baseline_volume_free
        self.expected_affinity_mask = expected_affinity_mask
        self.expected_processor_group = expected_processor_group
        self._previous_attribution: dict[str, int] | None = None
        self._previous_host_processes: dict[tuple[int, int], dict[str, int | str]] | None = None

    @property
    def guard_classification(self) -> str | None:
        """Clasificación que debe detener el Job, si existe."""
        return self._classification

    @property
    def guard_reason(self) -> str | None:
        """Razón causal observada por el sensor."""
        return self._reason

    def start(self) -> None:
        """Inicia el único writer del sidecar."""
        if self._thread is not None:
            raise RuntimeError("sampler ya iniciado")
        self._thread = threading.Thread(target=self._run, name="nikodym-h9r-telemetry", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        """Detiene, espera y finaliza metadatos del sidecar."""
        self._stop.set()
        if self._thread is not None:
            # El watchdog de lectura termina el único writer aunque un sensor OS quede bloqueado.
            self._thread.join(max(timeout_seconds, self.max_gap_seconds + 0.25))
            if self._thread.is_alive():
                self._classification = "evidence_incomplete"
                self._reason = "el sampler no terminó dentro del cleanup"
                # Fsync+close congela bytes antes del error; un append tardío falla cerrado.
                self.recorder.finalize()
                raise TimeoutError(self._reason)
        metadata = self.recorder.finalize()
        return {"sidecar": metadata, "summary": self.summary()}

    def wait_guard(self, timeout_seconds: float) -> bool:
        """Espera una guarda o el fin natural del sampler."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._classification is not None:
                return True
            if self._done.is_set():
                return False
            time.sleep(min(0.01, self.interval_seconds))
        return self._classification is not None

    def wait_first_sample(self, timeout_seconds: float) -> dict[str, Any]:
        """Espera una muestra completa; un terminal del sensor nunca cuenta como muestra."""
        if timeout_seconds <= 0:
            raise ValueError("timeout de primera muestra debe ser positivo")
        if not self._first_record.wait(timeout_seconds):
            raise TimeoutError("telemetría no produjo una primera muestra dentro del deadline")
        if not self._samples or self._samples[0].get("record_type") == "sensor_failure":
            raise ContractError(self._reason or "telemetría falló antes de su primera muestra")
        return dict(self._samples[0])

    def _set_guard(self, classification: str, reason: str) -> None:
        if self._classification is None:
            self._classification = classification
            self._reason = reason

    def _run(self) -> None:
        next_deadline = time.monotonic()
        try:
            while not self._stop.is_set():
                if not self._sample_once_bounded():
                    break
                next_deadline += self.interval_seconds
                delay = next_deadline - time.monotonic()
                if delay > 0:
                    self._stop.wait(delay)
                else:
                    next_deadline = time.monotonic()
        except Exception as exc:
            reason = f"sensor falló: {type(exc).__name__}: {exc}"
            self._set_guard("evidence_incomplete", reason)
            self._record_sensor_failure(
                kind="exception",
                reason=reason,
                deadline_seconds=None,
                error_type=type(exc).__name__,
            )
        finally:
            self._done.set()

    def _sample_once_bounded(self) -> bool:
        """Aísla una lectura bloqueable; sólo este thread conserva autoridad para escribir."""
        started_ns = time.monotonic_ns()
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def read_sensor() -> None:
            try:
                outcome["payload"] = self.sensor.sample()
            except BaseException as exc:  # pragma: no cover - transferido al writer.
                outcome["error"] = exc
            finally:
                outcome["finished_ns"] = time.monotonic_ns()
                completed.set()

        reader = threading.Thread(
            target=read_sensor,
            name="nikodym-h9r-sensor-read",
            daemon=True,
        )
        reader.start()
        if not completed.wait(self.max_gap_seconds):
            reason = f"sensor bloqueado durante más de {self.max_gap_seconds:.6f} s"
            self._set_guard("evidence_incomplete", reason)
            self._record_sensor_failure(
                kind="timeout",
                reason=reason,
                deadline_seconds=self.max_gap_seconds,
                error_type=None,
            )
            return False
        error = outcome.get("error")
        if isinstance(error, BaseException):
            raise error
        payload = outcome.get("payload")
        if not isinstance(payload, dict):
            raise ContractError("sensor no devolvió un objeto")
        self._record_payload(
            started_ns=started_ns,
            finished_ns=int(outcome["finished_ns"]),
            payload=payload,
        )
        return True

    def _record_sensor_failure(
        self,
        *,
        kind: str,
        reason: str,
        deadline_seconds: float | None,
        error_type: str | None,
    ) -> None:
        """Persist a closed terminal cause even when the first sample fails."""
        failed_at_ns = time.monotonic_ns()
        previous_ns = int(self._samples[-1]["monotonic_ns"]) if self._samples else failed_at_ns
        causal_record = {
            "record_type": "sensor_failure",
            "sample_ordinal": len(self._samples),
            "monotonic_ns": failed_at_ns,
            "wall_time_utc": datetime.now(UTC).isoformat(),
            "sensor_duration_seconds": (
                float(deadline_seconds) if deadline_seconds is not None else 0.0
            ),
            "gap_seconds": (failed_at_ns - previous_ns) / 1_000_000_000,
            "failure": {
                "kind": kind,
                "deadline_seconds": deadline_seconds,
                "error_type": error_type,
                "message": reason,
            },
            "guard_classification": "evidence_incomplete",
            "guard_reason": reason,
        }
        _validate_sensor_failure_record(causal_record, context="sensor_failure")
        self._samples.append(causal_record)
        self.recorder.append(causal_record)
        self._first_record.set()

    def sample_once(self) -> dict[str, Any]:
        """Toma una muestra, evalúa guardas y la persiste."""
        started_ns = time.monotonic_ns()
        try:
            payload = self.sensor.sample()
            finished_ns = time.monotonic_ns()
            return self._record_payload(
                started_ns=started_ns,
                finished_ns=finished_ns,
                payload=payload,
            )
        except Exception as exc:
            reason = f"sensor falló: {type(exc).__name__}: {exc}"
            self._set_guard("evidence_incomplete", reason)
            try:
                if not self._samples or self._samples[-1].get("record_type") != "sensor_failure":
                    self._record_sensor_failure(
                        kind="exception",
                        reason=reason,
                        deadline_seconds=None,
                        error_type=type(exc).__name__,
                    )
            finally:
                # Ninguna excepción de sensor, evaluación ni escritura puede dejar abierto el
                # único descriptor del sidecar.
                self.recorder.finalize()
            raise

    def _record_payload(
        self, *, started_ns: int, finished_ns: int, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Único punto writer: deriva guardas y persiste una lectura ya concluida."""
        if self._last_monotonic_ns is not None:
            gap_seconds = (started_ns - self._last_monotonic_ns) / 1_000_000_000
            if gap_seconds > self.max_gap_seconds:
                self._set_guard(
                    "evidence_incomplete",
                    f"muestra ausente durante {gap_seconds:.6f} s",
                )
        else:
            gap_seconds = 0.0
        self._last_monotonic_ns = started_ns
        sample = {
            "sample_ordinal": len(self._samples),
            "monotonic_ns": started_ns,
            "wall_time_utc": datetime.now(UTC).isoformat(),
            "sensor_duration_seconds": (finished_ns - started_ns) / 1_000_000_000,
            "gap_seconds": gap_seconds,
            **payload,
            "guard_classification": None,
            "guard_reason": None,
        }
        self._evaluate(sample)
        sample["guard_classification"] = self._classification
        sample["guard_reason"] = self._reason
        self._samples.append(sample)
        self.recorder.append(sample)
        self._first_record.set()
        return sample

    def _evaluate(self, sample: Mapping[str, Any]) -> None:
        self._evaluate_host_attribution(sample)
        disk = _record_object(sample.get("disk"), context="sample.disk")
        roots = _record_object(disk.get("roots"), context="sample.disk.roots")
        if self._baseline_roots is None:
            self._baseline_roots = {
                name: dict(_record_object(roots.get(name), context=f"sample.disk.roots.{name}"))
                for name in _DISK_ROOTS
            }
        if self._baseline_volume_free is None:
            self._baseline_volume_free = _record_non_negative_int(
                disk.get("volume_free_bytes"), context="sample.disk.volume_free_bytes"
            )
        classification, reason = derive_telemetry_guard(
            [*self._samples, sample],
            baseline_roots=self._baseline_roots,
            baseline_volume_free_bytes=self._baseline_volume_free,
            expected_affinity_mask=self.expected_affinity_mask,
            expected_processor_group=self.expected_processor_group,
            max_gap_seconds=self.max_gap_seconds,
        )
        if classification is not None and reason is not None:
            self._set_guard(classification, reason)

    def _evaluate_host_attribution(self, sample: Mapping[str, Any]) -> None:
        """Prueba deriva CPU/commit externa por diferencias de contadores acumulados."""
        attribution, current, current_host = _derive_expected_host_attribution(
            sample,
            previous_attribution=self._previous_attribution,
            previous_host_processes=self._previous_host_processes,
        )
        self._previous_host_processes = current_host
        self._previous_attribution = current
        if isinstance(sample, dict):
            sample["host_attribution"] = attribution

    def summary(self) -> dict[str, Any]:
        """Deriva peaks/high-water sin eliminar muestras."""
        if not self._samples:
            return {
                "records": 0,
                "guard_classification": self._classification or "evidence_incomplete",
                "guard_reason": self._reason or "no se capturaron muestras",
            }
        sample_records, _ = _split_sensor_records(self._samples)
        baseline_roots = self._baseline_roots
        if baseline_roots is None and sample_records:
            first_disk = _record_object(sample_records[0].get("disk"), context="samples[0].disk")
            first_roots = _record_object(first_disk.get("roots"), context="samples[0].disk.roots")
            baseline_roots = {
                name: dict(
                    _record_object(first_roots.get(name), context=f"samples[0].disk.roots.{name}")
                )
                for name in _DISK_ROOTS
            }
        return summarize_telemetry_records(
            self._samples,
            # Un terminal causal sin muestras retorna antes de consultar raíces.
            baseline_roots=baseline_roots or {},
            baseline_volume_free_bytes=self._baseline_volume_free,
            interval_seconds=self.interval_seconds,
            expected_affinity_mask=self.expected_affinity_mask,
            expected_processor_group=self.expected_processor_group,
            terminal_guard_classification=self._classification,
            terminal_guard_reason=self._reason,
        )
