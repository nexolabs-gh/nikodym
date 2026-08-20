"""Preflight, handshake y supervisor fail-closed del arnés H9R."""

from __future__ import annotations

import contextlib
import copy
import csv
import ctypes
import hmac
import importlib.util
import json
import math
import os
import platform
import secrets
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, cast

from .adapters import (
    ADAPTER_DESCRIPTOR_SCHEMA_VERSION,
    ADAPTER_REQUEST_SCHEMA_VERSION,
    CANDIDATE_REQUEST_SCHEMA_VERSION,
    CONSUMER_OPEN_PROTOCOL_VERSION,
    LAUNCH_BINDING_SCHEMA_VERSION,
    UI_CLIENT_REQUEST_SCHEMA_VERSION,
    UI_FIRST_BYTE_SCHEMA_VERSION,
    _open_readonly_no_follow,
    _same_file_version,
    validate_adapter_audit,
    validate_adapter_request,
    validate_candidate_launch_request,
    validate_ui_client_request,
)
from .artifacts import (
    OUTPUT_FORMAT_COUNTERS,
    allocated_size,
    atomic_write_json_exclusive,
    binary_sidecar_metadata,
    canonical_tree_identity,
    census_roots,
    derive_output_record_count,
    disk_footprint_summary,
    final_inventory,
    jsonl_sidecar_metadata,
    validate_census_against_filesystem,
    validate_output_manifest,
    verify_jsonl_sidecar,
    verify_sidecar,
    volume_free_bytes,
    windows_volume_identity,
)
from .consumer import (
    reconstruct_consumer_sidecars,
)
from .contracts import (
    ADAPTER_IDS,
    ATTEMPT_SCHEMA_VERSION,
    AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
    CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256,
    CAPS,
    CONFIG_SCHEMA_VERSION,
    HANDSHAKE_DEADLINE_SECONDS,
    INTERNAL_AUTHORIZATION_ROLES,
    MAX_SAMPLE_GAP_SECONDS,
    POST_START_FAILURE_SCHEMA_VERSION,
    PRE_START_FAILURE_SCHEMA_VERSION,
    PREFLIGHT_DEADLINE_SECONDS,
    PREFLIGHT_MIN_AVAILABLE_PHYSICAL_BYTES,
    PREFLIGHT_MIN_COMMIT_HEADROOM_BYTES,
    PREFLIGHT_MIN_DISK_FREE_BYTES,
    PREFLIGHT_REJECTION_SCHEMA_VERSION,
    PROTOCOL_VERSION,
    RUN_MIN_AVAILABLE_PHYSICAL_BYTES,
    RUN_MIN_COMMIT_HEADROOM_BYTES,
    ContractError,
    attempt_id,
    authorization_consumption_path_digest,
    authorization_statement,
    canonical_json_bytes,
    canonical_json_sha256,
    claim_internal_authorization_release,
    flow_spec,
    internal_authorization_release_paths,
    read_json_object,
    reserve_internal_authorization_bundle,
    sha256_bytes,
    sha256_file,
    trusted_authority_key_identity,
    validate_attempt_evidence,
    validate_attempt_unit,
    validate_authority,
    validate_authorization_consumption,
    validate_boundary_events,
    validate_native_pool_events,
    validate_post_start_failure_evidence,
    validate_pre_start_failure_evidence,
    validate_preflight_rejection_evidence,
    validate_schedule,
    validate_sha256,
)
from .contracts import (
    validate_internal_authorization_gate as validate_internal_authorization_gate_contract,
)
from .runtime_snapshot import (
    RuntimeSnapshotError,
    materialize_harness_source_snapshot,
    validate_harness_source_snapshot,
)
from .telemetry import (
    POOL_ENVIRONMENT_KEYS,
    LiveWindowsSensor,
    TelemetrySampler,
    derive_consumer_window_summary,
)
from .windows_job import (
    WindowsApi,
    WindowsExternalJob,
    WindowsJob,
    _GroupAffinity,
    _JobExtendedLimitInformation,
    current_process_affinity,
    first_cpu_mask,
    process_metrics,
    processor_topology,
    resume_suspended_process,
    system_memory_status,
)
from .windows_sandbox import (
    LOW_INTEGRITY_SID,
    launch_suspended_low_integrity,
    low_integrity_primary_token,
    process_integrity_level,
)

CANDIDATE_SCHEMA_VERSION = "nikodym.readiness.h9r.candidate.v1"
CANDIDATE_ENVIRONMENT_SCHEMA_VERSION = "nikodym.readiness.h9r.candidate-environment.v1"
FIXTURE_SCHEMA_VERSION = "nikodym.readiness.h9r.fixture.v1"
WORKER_RESULT_SCHEMA_VERSION = "nikodym.readiness.h9r.worker-result.v1"
FIXTURE_COLUMNS_SCHEMA_VERSION = "nikodym.readiness.h9r.fixture-columns.v1"
FIXTURE_CATALOG_SCHEMA_VERSION = "nikodym.readiness.h9r.fixture-catalog.v1"
RUNTIME_PROVENANCE_SCHEMA_VERSION = "nikodym.readiness.h9r.runtime-provenance.v1"
INTERNAL_AUTHORIZATION_GATE_SCHEMA_VERSION = "nikodym.readiness.h9r.internal-authorization-gate.v1"
QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE = False
TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE = True
MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE = False
CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE = False
# Implementado el 2026-08-20: el candidato se crea con token primario de integridad Low y sólo sus
# tres raíces escribibles llevan etiqueta obligatoria Low. El censo se mide contra el sistema
# operativo antes de crear el proceso y se vuelve a medir tras la quiescencia.
CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE = True
CALIBRATION_START_DISABLED_REASON = (
    "qualifying_boundary_adapters_unavailable: faltan adapters firmados que entreguen inputs "
    "mediante un broker consumer-open y, para F-UI, un servicio real con página verificable; "
    "candidate_execution_material_lease_unimplemented: falta un snapshot sellado o leases "
    "no-follow continuos del ejecutable, árbol candidato e inputs desde su validación hasta la "
    "quiescencia; "
    "multiprocess_native_pool_observer_unimplemented: falta atestar pools por PID/creation-time "
    "para cada proceso del Job consumidor"
)
_SUPERVISOR_ABORT_EXIT_CODE = 0xE9
_CAPABILITY_ENVIRONMENT = {
    "worker": "NIKODYM_H9R_WORKER_CAPABILITY",
    "adapter": "NIKODYM_H9R_ADAPTER_CAPABILITY",
    "candidate": "NIKODYM_H9R_CANDIDATE_CAPABILITY",
    "ui-client": "NIKODYM_H9R_UI_CLIENT_CAPABILITY",
}
_PRE_START_TYPED_CLASSIFICATIONS = frozenset(
    {
        "limits_not_applied",
        "watchdog_deadline",
        "safety_abort_system_memory",
        "safety_abort_disk",
        "host_contamination",
        "host_oom",
        "cancelled",
        "supervisor_error",
        "invariant_failure",
        "orphan_detected",
        "evidence_incomplete",
    }
)


class _PreStartAbortError(ContractError):
    """Error pre-START con causa cerrada, independiente del texto diagnóstico."""

    def __init__(self, classification: str, message: str) -> None:
        if classification not in _PRE_START_TYPED_CLASSIFICATIONS:
            raise ValueError(f"clasificación pre-START inválida: {classification}")
        super().__init__(message)
        self.classification = classification


def calibration_start_implementation_blockers() -> tuple[str, ...]:
    """Enumera bloqueos de implementación que una autoridad externa no puede levantar."""
    blockers: list[str] = []
    if not QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE:
        blockers.append("qualifying_boundary_adapters_unavailable")
    if not CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE:
        blockers.append("candidate_execution_material_lease_unimplemented")
    if not CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE:
        blockers.append("candidate_output_os_isolation_unimplemented")
    if not TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE:
        blockers.append("trusted_harness_runtime_snapshot_unimplemented")
    if not MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE:
        blockers.append("multiprocess_native_pool_observer_unimplemented")
    return tuple(blockers)


def require_calibration_start_implementation_ready() -> None:
    """Falla antes de ejecutar bytes mientras falte cualquier pieza calificable."""
    blockers = calibration_start_implementation_blockers()
    if blockers:
        raise ContractError(f"{CALIBRATION_START_DISABLED_REASON}; blockers={','.join(blockers)}")


def _capability_commitment(secret: str, *, role: str, payload_sha256: str) -> str:
    if role not in _CAPABILITY_ENVIRONMENT:
        raise ContractError("rol de capability desconocido")
    if (
        len(secret) != 64
        or any(character not in "0123456789abcdef" for character in secret)
        or secret in {"0" * 64, "f" * 64}
    ):
        raise ContractError("secreto de capability inválido")
    payload = validate_sha256(payload_sha256, context=f"capability.{role}.payload_sha256")
    material = (
        bytes.fromhex(secret) + b"\0" + role.encode("ascii") + b"\0" + payload.encode("ascii")
    )
    return sha256_bytes(material)


def _issue_launch_capability(*, role: str, payload_sha256: str) -> tuple[str, str]:
    secret = secrets.token_hex(32)
    return secret, _capability_commitment(secret, role=role, payload_sha256=payload_sha256)


def consume_launch_capability(
    *, role: str, payload_sha256: str, expected_commitment_sha256: str
) -> None:
    """Consume y borra del entorno una capability efímera antes de cargar el runner."""
    if CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256 is None:
        raise ContractError(
            "subcomando interno cerrado: no existe fingerprint humano durable aprobado"
        )
    environment_name = _CAPABILITY_ENVIRONMENT.get(role)
    if environment_name is None:
        raise ContractError("rol de capability desconocido")
    secret = os.environ.pop(environment_name, None)
    if secret is None:
        raise ContractError(f"subcomando interno {role} sin capability del supervisor")
    expected = validate_sha256(
        expected_commitment_sha256, context=f"capability.{role}.commitment_sha256"
    )
    observed = _capability_commitment(secret, role=role, payload_sha256=payload_sha256)
    if not hmac.compare_digest(observed, expected):
        raise ContractError(f"capability de {role} no reconcilia request/launch")


def _current_worker_job_limits() -> dict[str, Any]:
    """Consulta desde el worker su Job efectivo; no confía sólo en el archivo del supervisor."""
    api = WindowsApi()
    process_handle = api.open_process(os.getpid())
    try:
        in_any_job = ctypes.c_bool(False)
        if not api.kernel32.IsProcessInJob(
            ctypes.c_void_p(process_handle), None, ctypes.byref(in_any_job)
        ):
            api.raise_last_error("IsProcessInJob(worker)")
        if not in_any_job.value:
            raise ContractError("limits_not_applied: worker no pertenece a un Job Object")
    finally:
        api.close_handle(process_handle)
    limits = _JobExtendedLimitInformation()
    if not api.kernel32.QueryInformationJobObject(
        None,
        WindowsJob.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
        None,
    ):
        api.raise_last_error("QueryInformationJobObject(worker limits)")
    group_array_type = _GroupAffinity * 64
    group_array = group_array_type()
    returned = ctypes.c_uint32(0)
    if not api.kernel32.QueryInformationJobObject(
        None,
        WindowsJob.JOB_OBJECT_GROUP_INFORMATION_EX,
        ctypes.byref(group_array),
        ctypes.sizeof(group_array),
        ctypes.byref(returned),
    ):
        api.raise_last_error("QueryInformationJobObject(worker groups)")
    flags = int(limits.BasicLimitInformation.LimitFlags)
    group_count = int(returned.value) // ctypes.sizeof(_GroupAffinity)
    return {
        "affinity_mask": int(limits.BasicLimitInformation.Affinity),
        "logical_cpu_count": int(limits.BasicLimitInformation.Affinity).bit_count(),
        "group_affinities": [
            {
                "processor_group": int(group_array[index].Group),
                "affinity_mask": int(group_array[index].Mask),
            }
            for index in range(group_count)
        ],
        "job_memory_commit_limit_bytes": int(limits.JobMemoryLimit),
        "kill_on_job_close": bool(flags & WindowsJob.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE),
        "affinity_enforced": bool(flags & WindowsJob.JOB_OBJECT_LIMIT_AFFINITY),
        "job_memory_enforced": bool(flags & WindowsJob.JOB_OBJECT_LIMIT_JOB_MEMORY),
    }


def _current_external_cleanup_job_controls() -> dict[str, Any]:
    """Atestigua que el cliente UI está en un Job kill-on-close sin caps del workload."""
    api = WindowsApi()
    process_handle = api.open_process(os.getpid())
    try:
        in_any_job = ctypes.c_bool(False)
        if not api.kernel32.IsProcessInJob(
            ctypes.c_void_p(process_handle), None, ctypes.byref(in_any_job)
        ):
            api.raise_last_error("IsProcessInJob(ui-client)")
        if not in_any_job.value:
            raise ContractError("ui-client no pertenece a cleanup Job")
    finally:
        api.close_handle(process_handle)
    limits = _JobExtendedLimitInformation()
    if not api.kernel32.QueryInformationJobObject(
        None,
        WindowsJob.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
        None,
    ):
        api.raise_last_error("QueryInformationJobObject(ui-client)")
    flags = int(limits.BasicLimitInformation.LimitFlags)
    observed = {
        "kill_on_job_close": bool(flags & WindowsJob.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE),
        "affinity_enforced": bool(flags & WindowsJob.JOB_OBJECT_LIMIT_AFFINITY),
        "job_memory_enforced": bool(flags & WindowsJob.JOB_OBJECT_LIMIT_JOB_MEMORY),
        "affinity_mask": int(limits.BasicLimitInformation.Affinity),
        "job_memory_limit_bytes": int(limits.JobMemoryLimit),
    }
    expected = {
        "kill_on_job_close": True,
        "affinity_enforced": False,
        "job_memory_enforced": False,
        "affinity_mask": 0,
        "job_memory_limit_bytes": 0,
    }
    if observed != expected:
        raise ContractError("ui-client no observa cleanup Job exacto")
    return observed


def _nominal_physical_memory_bytes() -> int:
    """Lee la RAM físicamente instalada; no la confunde con RAM visible/utilizable."""
    api = WindowsApi()
    installed_kib = ctypes.c_ulonglong(0)
    api.kernel32.GetPhysicallyInstalledSystemMemory.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
    api.kernel32.GetPhysicallyInstalledSystemMemory.restype = ctypes.c_bool
    if not api.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(installed_kib)):
        api.raise_last_error("GetPhysicallyInstalledSystemMemory")
    value = int(installed_kib.value) * 1024
    if value <= 0:
        raise ContractError("RAM nominal instalada no es atestiguable")
    return value


@dataclass(frozen=True)
class PreflightResult:
    """Atestación inmutable anterior a READY/START."""

    unit: dict[str, Any]
    attempt_id: str
    authority: dict[str, Any]
    candidate: dict[str, Any]
    fixture: dict[str, Any]
    config: dict[str, Any]
    schedule: dict[str, Any]
    environment: dict[str, Any]
    requested_limits: dict[str, Any]
    effective_limits: dict[str, Any]
    resource_guards: dict[str, Any]
    tooling: dict[str, Any]
    source_paths: dict[str, Any]
    workdir_path: str
    workdir_reservation: dict[str, Any] | None
    started_monotonic_ns: int
    elapsed_seconds: float

    def as_dict(self) -> dict[str, Any]:
        """Convierte la atestación a JSON."""
        return {
            "unit": self.unit,
            "attempt_id": self.attempt_id,
            "authority": self.authority,
            "candidate": self.candidate,
            "fixture": self.fixture,
            "config": self.config,
            "schedule": self.schedule,
            "environment": self.environment,
            "requested_limits": self.requested_limits,
            "effective_limits": self.effective_limits,
            "resource_guards": self.resource_guards,
            "tooling": self.tooling,
            "workdir_path": self.workdir_path,
            "workdir_reservation": self.workdir_reservation,
            "started_monotonic_ns": self.started_monotonic_ns,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True)
class _LaunchSourceCapture:
    """Bytes y versión de una launch source obtenidos por un único descriptor no-follow."""

    path: Path
    payload: bytes
    metadata: os.stat_result
    parent_metadata: os.stat_result
    raw_sha256: str
    json_value: dict[str, Any] | None


def _source_identity(path: Path, *, require_single_link: bool = True) -> dict[str, Any]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    present = os.path.lexists(absolute)
    is_reparse = bool(
        present and any(_is_reparse_or_symlink(item) for item in (absolute, *absolute.parents[:-1]))
    )
    link_count: int | None = None
    if present and not is_reparse and absolute.is_file():
        with contextlib.suppress(OSError):
            link_count = int(absolute.stat().st_nlink)
    safe_regular = bool(
        present
        and absolute.is_file()
        and not is_reparse
        and (not require_single_link or link_count == 1)
    )
    if not safe_regular:
        rejection = (
            "absent"
            if not present
            else "symlink_or_reparse_point"
            if is_reparse
            else "multiple_hardlinks"
            if require_single_link and link_count is not None and link_count != 1
            else "not_regular_file"
        )
        return {
            "path": str(absolute),
            "present": present,
            "safe_regular_file": False,
            "rejection": rejection,
            "bytes": None,
            "sha256": None,
        }
    return {
        "path": str(absolute),
        "present": True,
        "safe_regular_file": True,
        "rejection": None,
        "bytes": absolute.stat().st_size,
        "sha256": sha256_file(absolute),
    }


def _require_safe_regular_file(
    path: Path, *, context: str, require_single_link: bool = True
) -> Path:
    identity = _source_identity(path, require_single_link=require_single_link)
    if identity["safe_regular_file"] is not True:
        raise ContractError(
            f"{context}: fuente ausente/no regular/symlink/reparse ({identity['rejection']})"
        )
    absolute = path.absolute()
    for ancestor in (absolute, *absolute.parents[:-1]):
        if _is_reparse_or_symlink(ancestor):
            raise ContractError(f"{context}: ruta atraviesa symlink/reparse point: {ancestor}")
    return Path(str(identity["path"]))


def _ensure_regular_sidecar_exists(path: Path, *, context: str) -> bool:
    """Valida un sidecar vivo o crea uno vacío con O_EXCL y sin seguir enlaces."""
    destination = Path(os.path.abspath(path))
    _require_plain_directory(destination.parent, context=f"{context}.parent")
    if os.path.lexists(destination):
        identity = _source_identity(destination)
        if identity["safe_regular_file"] is not True:
            raise ContractError(f"{context}: sidecar existente inseguro ({identity['rejection']})")
        return False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(destination, flags, 0o600)
    except FileExistsError as exc:
        raise ContractError(f"{context}: carrera al crear sidecar exclusivo") from exc
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    identity = _source_identity(destination)
    if identity["safe_regular_file"] is not True or identity["bytes"] != 0:
        raise ContractError(f"{context}: sidecar vacío no quedó regular/exclusivo")
    return True


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if path.is_symlink():
        return True
    return bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _require_plain_directory(path: Path, *, context: str) -> Path:
    absolute = Path(os.path.abspath(path))
    for ancestor in (absolute, *absolute.parents):
        if _is_reparse_or_symlink(ancestor):
            raise ContractError(f"{context}: ruta atraviesa symlink/reparse point: {ancestor}")
    if not absolute.is_dir() or _is_reparse_or_symlink(absolute):
        raise ContractError(f"{context}: directorio ausente, symlink o reparse point")
    return absolute


def _capture_launch_source(
    path: Path, *, context: str, canonical_json: bool
) -> _LaunchSourceCapture:
    """Abre una launch source una vez y liga bytes, JSON y path a ese descriptor."""
    candidate = Path(os.path.abspath(path))
    parent = _require_plain_directory(candidate.parent, context=f"{context}.parent")
    parent_before = parent.lstat()
    try:
        before = candidate.lstat()
    except OSError as exc:
        raise ContractError(f"{context}: launch source ausente") from exc
    attributes = int(getattr(before, "st_file_attributes", 0))
    if not stat.S_ISREG(before.st_mode) or candidate.is_symlink() or bool(attributes & 0x400):
        raise ContractError(f"{context}: launch source no regular o symlink/reparse")
    if int(getattr(before, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: hardlink prohibido")
    try:
        with _open_readonly_no_follow(candidate) as handle:
            opened = os.fstat(handle.fileno())
            if not _same_file_version(before, opened):
                raise ContractError(f"{context}: identidad cambió antes de leer")
            if int(getattr(opened, "st_nlink", 1)) != 1:
                raise ContractError(f"{context}: descriptor abrió un hardlink")
            payload = handle.read()
            after_read = os.fstat(handle.fileno())
            if not _same_file_version(opened, after_read) or len(payload) != int(
                after_read.st_size
            ):
                raise ContractError(f"{context}: launch source cambió durante la lectura")
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError(f"{context}: apertura no-follow falló") from exc
    parent_after = _require_plain_directory(parent, context=f"{context}.parent-final").lstat()
    try:
        after_path = candidate.lstat()
    except OSError as exc:
        raise ContractError(f"{context}: launch source desapareció") from exc
    if not os.path.samestat(parent_before, parent_after):
        raise ContractError(f"{context}: parent cambió de identidad")
    if not _same_file_version(before, after_path):
        raise ContractError(f"{context}: path cambió de identidad o versión")
    if int(getattr(after_path, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: path terminó como hardlink")
    json_value: dict[str, Any] | None = None
    if canonical_json:
        try:
            raw: Any = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"{context}: JSON UTF-8 inválido") from exc
        json_value = _require_mapping(raw, context=context)
        if payload != canonical_json_bytes(json_value) + b"\n":
            raise ContractError(f"{context}: JSON no es canónico exacto con LF")
    return _LaunchSourceCapture(
        path=candidate,
        payload=payload,
        metadata=after_path,
        parent_metadata=parent_after,
        raw_sha256=sha256_bytes(payload),
        json_value=json_value,
    )


def _launch_capture_version(capture: _LaunchSourceCapture) -> dict[str, Any]:
    return {
        "path": str(capture.path),
        "device": int(capture.metadata.st_dev),
        "inode": int(capture.metadata.st_ino),
        "bytes": int(capture.metadata.st_size),
        "mtime_ns": int(getattr(capture.metadata, "st_mtime_ns", 0)),
        "parent_device": int(capture.parent_metadata.st_dev),
        "parent_inode": int(capture.parent_metadata.st_ino),
        "raw_sha256": capture.raw_sha256,
    }


def _capture_launch_sources(paths: Mapping[str, Path]) -> dict[str, _LaunchSourceCapture]:
    canonical_names = {
        "authority",
        "candidate_manifest",
        "fixture_manifest",
        "config",
        "schedule",
    }
    return {
        name: _capture_launch_source(
            path,
            context=f"launch.{name}",
            canonical_json=name in canonical_names,
        )
        for name, path in paths.items()
    }


def _assert_launch_captures_current(
    captures: Mapping[str, _LaunchSourceCapture],
    *,
    expected_versions: Mapping[str, Any] | None = None,
    context: str,
) -> None:
    """Recaptura causalmente antes de ejecutar bytes y exige la misma versión exacta."""
    for name, capture in captures.items():
        observed = _capture_launch_source(
            capture.path,
            context=f"{context}.{name}",
            canonical_json=capture.json_value is not None,
        )
        expected = (
            _launch_capture_version(capture)
            if expected_versions is None
            else cast(Mapping[str, Any], expected_versions[name])
        )
        if (
            _launch_capture_version(observed) != dict(expected)
            or observed.payload != capture.payload
            or observed.json_value != capture.json_value
        ):
            raise ContractError(f"{context}.{name}: launch source cambió de versión")


@contextlib.contextmanager
def _captured_trust_anchor(capture: _LaunchSourceCapture) -> Iterator[Path]:
    """Entrega a validadores path-based una copia exclusiva de los bytes ya capturados."""
    if capture.json_value is not None:
        raise ContractError("trust anchor capturado no puede ser JSON")
    with tempfile.TemporaryDirectory(prefix="nikodym-h9r-trust-") as raw_directory:
        directory = _require_plain_directory(Path(raw_directory), context="trust-snapshot.parent")
        snapshot = directory / "authority-public.pem"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(snapshot, flags, 0o600)
        try:
            view = memoryview(capture.payload)
            written = 0
            while written < len(view):
                advanced = os.write(descriptor, view[written:])
                if advanced <= 0:  # pragma: no cover - defensa de I/O regular.
                    raise ContractError("trust snapshot no pudo persistir todos sus bytes")
                written += advanced
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        reopened = _capture_launch_source(
            snapshot,
            context="trust-snapshot",
            canonical_json=False,
        )
        if reopened.payload != capture.payload:
            raise ContractError("trust snapshot no reconcilia con la captura")
        yield reopened.path


def _reject_reparse_tree(root: Path, *, context: str) -> None:
    resolved_root = _require_plain_directory(root, context=context)
    for current, directories, files in os.walk(resolved_root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            candidate = current_path / name
            if _is_reparse_or_symlink(candidate):
                raise ContractError(f"{context}: symlink/reparse point prohibido: {candidate}")


def _plain_tree_files(root: Path, *, context: str) -> list[Path]:
    """Enumera archivos regulares con scandir no-follow y falla ante todo nodo ambiguo."""
    root = _require_plain_directory(root, context=context)
    pending = [root]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError as exc:
            raise ContractError(f"{context}: no se pudo censar {directory}") from exc
        for entry in entries:
            candidate = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ContractError(f"{context}: no se pudo atestiguar {candidate}") from exc
            if entry.is_symlink() or bool(int(getattr(metadata, "st_file_attributes", 0)) & 0x400):
                raise ContractError(f"{context}: symlink/reparse point prohibido: {candidate}")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(candidate)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(candidate)
            else:
                raise ContractError(f"{context}: nodo no regular prohibido: {candidate}")
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _workdir_entries(path: Path, *, exclude: Path | None = None) -> list[str]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not os.path.lexists(absolute):
        return []
    if _is_reparse_or_symlink(absolute):
        return ["<root:symlink_or_reparse_point>"]
    try:
        metadata = absolute.lstat()
    except OSError as exc:
        return [f"<root:unreadable:{type(exc).__name__}>"]
    if not stat.S_ISDIR(metadata.st_mode):
        return ["<root:not_directory>"]
    excluded = (
        os.path.normcase(os.path.abspath(os.fspath(exclude))) if exclude is not None else None
    )
    pending = [absolute]
    observed: list[str] = []
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError as exc:
            observed.append(
                f"{directory.relative_to(absolute).as_posix()}/<unreadable:{type(exc).__name__}>"
            )
            continue
        for entry in entries:
            candidate = Path(entry.path)
            if excluded is not None and os.path.normcase(os.path.abspath(candidate)) == excluded:
                continue
            relative = candidate.relative_to(absolute).as_posix()
            try:
                entry_metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                observed.append(f"{relative}<unreadable:{type(exc).__name__}>")
                continue
            if entry.is_symlink() or bool(
                int(getattr(entry_metadata, "st_file_attributes", 0)) & 0x400
            ):
                observed.append(f"{relative}<symlink_or_reparse_point>")
            elif stat.S_ISDIR(entry_metadata.st_mode):
                observed.append(relative)
                pending.append(candidate)
            elif stat.S_ISREG(entry_metadata.st_mode):
                observed.append(relative)
            else:
                observed.append(f"{relative}<not_regular>")
    return sorted(observed)


def write_preflight_rejection_evidence(
    *,
    unit_path: Path,
    authority_path: Path,
    authorization_text_path: Path,
    trusted_authority_public_key_path: Path,
    candidate_manifest_path: Path,
    fixture_manifest_path: Path,
    config_path: Path,
    schedule_path: Path,
    prior_evidence_paths_path: Path,
    document_paths: Mapping[str, Path],
    workdir: Path,
    evidence_path: Path,
    workdir_existed_before: bool,
    reason: BaseException | str,
) -> dict[str, Any]:
    """Persistir un rechazo de preflight separado, sin inventar READY/START ni un attempt."""
    resolved_workdir = workdir.resolve()
    resolved_evidence = evidence_path.resolve()
    control_root = resolved_workdir / "telemetry" / "control"
    start_count = int((control_root / "start.json").exists())
    ready_count = int((control_root / "ready.json").exists())
    worker_spawned = any(
        (control_root / name).exists()
        for name in (
            "boot.json",
            "limits-applied.json",
            "ready.json",
            "start.json",
            "worker-result.json",
        )
    )
    no_start = start_count == 0 and ready_count == 0
    no_worker = not worker_spawned
    evidence_atomic = not os.path.lexists(resolved_evidence)
    if not no_start or not no_worker:
        raise ContractError("rechazo preflight prohibido: READY/START/worker ya fue observado")
    if not evidence_atomic:
        raise ContractError("destino inmutable del rechazo preflight ya existe")
    entries_before = _workdir_entries(resolved_workdir)
    cleanup_errors: list[str] = []
    # Este emisor no reserva el workdir y, por ello, nunca lo borra. En particular, un path que
    # apareció entre el censo del CLI y este cierre puede pertenecer a otro proceso. La única
    # limpieza destructiva admisible vive en ``run_preflight``, junto al owner marker que creó.
    evidence_inside_workdir = _path_is_within(resolved_evidence, resolved_workdir)
    if evidence_inside_workdir and not resolved_workdir.exists():
        # El único contenido durable permitido tras el cleanup será la propia evidencia, excluida
        # del censo para evitar una identidad JSON autorreferente.
        resolved_evidence.parent.mkdir(parents=True, exist_ok=True)
    entries_after = _workdir_entries(
        resolved_workdir,
        exclude=resolved_evidence if evidence_inside_workdir else None,
    )
    expected_after = entries_before
    cleanup_complete = entries_after == expected_after
    try:
        unit = validate_attempt_unit(read_json_object(unit_path))
        unit_identity: dict[str, Any] | None = unit
        unit_attempt_id: str | None = attempt_id(unit)
    except Exception:
        unit_identity = None
        unit_attempt_id = None
    sources: dict[str, Path] = {
        "unit": unit_path,
        "authority": authority_path,
        "authorization_text": authorization_text_path,
        "trusted_authority_public_key": trusted_authority_public_key_path,
        "candidate_manifest": candidate_manifest_path,
        "fixture_manifest": fixture_manifest_path,
        "config": config_path,
        "schedule": schedule_path,
        "prior_evidence_paths": prior_evidence_paths_path,
    }
    sources.update({f"document:{name}": path for name, path in sorted(document_paths.items())})
    rejection_reasons = [str(reason) or type(reason).__name__, *cleanup_errors]
    payload = {
        "schema_version": PREFLIGHT_REJECTION_SCHEMA_VERSION,
        "phase": "preflight",
        "identity": {
            "unit": unit_identity,
            "attempt_id": unit_attempt_id,
            "evidence_path": str(resolved_evidence),
            "wall_time_finished_utc": datetime.now(UTC).isoformat(),
        },
        "launch_sources": {
            "unit_path": str(unit_path.resolve()),
            "authority_path": str(authority_path.resolve()),
            "authorization_text_path": str(authorization_text_path.resolve()),
            "trusted_authority_public_key_path": str(trusted_authority_public_key_path.resolve()),
            "candidate_manifest_path": str(candidate_manifest_path.resolve()),
            "fixture_manifest_path": str(fixture_manifest_path.resolve()),
            "config_path": str(config_path.resolve()),
            "schedule_path": str(schedule_path.resolve()),
            "prior_evidence_paths_path": str(prior_evidence_paths_path.resolve()),
            "document_paths": {
                name: str(path.resolve()) for name, path in sorted(document_paths.items())
            },
            "workdir": str(resolved_workdir),
        },
        "observed": {
            "source_identities": {name: _source_identity(path) for name, path in sources.items()},
            "workdir_state": {
                "path": str(resolved_workdir),
                "existed_before": workdir_existed_before,
                "exists_after": resolved_workdir.exists(),
                "entries_before": entries_before,
                "entries_after": entries_after,
            },
        },
        "termination": {
            "classification": "preflight_rejected",
            "start_count": start_count,
            "ready_count": ready_count,
            "worker_spawned": worker_spawned,
            "cleanup_complete": cleanup_complete,
            "workdir_removed": not resolved_workdir.exists(),
        },
        "gates": {
            "no_start": no_start,
            "no_worker": no_worker,
            "evidence_atomic": evidence_atomic,
        },
        "reasons": rejection_reasons,
    }
    validate_preflight_rejection_evidence(payload)
    atomic_write_json_exclusive(resolved_evidence, payload)
    reopened = read_json_object(resolved_evidence)
    if reopened != payload:
        raise ContractError("rechazo preflight no reconcilia tras publicación")
    validate_preflight_rejection_evidence(reopened)
    return payload


def _require_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context}: se esperaba objeto")
    return cast(dict[str, Any], value)


def _portable_relative_path(relative_value: Any, *, context: str) -> PurePosixPath:
    if not isinstance(relative_value, str) or not relative_value:
        raise ContractError(f"{context}: relative_path inválido")
    relative = PurePosixPath(relative_value)
    windows = PureWindowsPath(relative_value)
    if (
        "\x00" in relative_value
        or "\\" in relative_value
        or str(relative) != relative_value
        or relative.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in relative.parts)
        or any(":" in part for part in relative.parts)
    ):
        raise ContractError(f"{context}: ruta no es relativa POSIX canónica")
    return relative


def _golden_output_relative_path(
    relative_value: Any, *, output_format: Any, context: str
) -> PurePosixPath:
    relative = _portable_relative_path(relative_value, context=context)
    if output_format == "bin" or output_format not in OUTPUT_FORMAT_COUNTERS:
        raise ContractError("golden usa formato opaco o fuera del catálogo de counters")
    if relative.suffix != f".{output_format}":
        raise ContractError("golden relative_path no coincide con su formato")
    return relative


def _resolve_relative(root: Path, relative_value: Any, *, context: str) -> Path:
    relative = _portable_relative_path(relative_value, context=context)
    resolved_root = _require_plain_directory(root, context=f"{context}.root")
    lexical = resolved_root.joinpath(*relative.parts)
    current = resolved_root
    for part in relative.parts:
        current /= part
        if os.path.lexists(current) and _is_reparse_or_symlink(current):
            raise ContractError(f"{context}: symlink/reparse point prohibido: {current}")
    resolved = lexical.resolve()
    boundary = str(resolved_root).rstrip("\\/") + os.sep
    if resolved == resolved_root or not str(resolved).startswith(boundary):
        raise ContractError(f"{context}: ruta escapa de su raíz")
    return resolved


def _verify_file_entry(
    entry: Mapping[str, Any],
    *,
    root: Path,
    context: str,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    required = {"relative_path", "bytes", "sha256"}
    if set(entry) != required:
        raise ContractError(f"{context}: campos de archivo no son exactos")
    path = _resolve_relative(root, entry["relative_path"], context=context)
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise ContractError(f"{context}: archivo ausente: {path}")
    if path.stat().st_nlink != 1:
        raise ContractError(f"{context}: hardlink prohibido: {path}")
    size = entry["bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ContractError(f"{context}: bytes inválidos")
    if size != path.stat().st_size:
        raise ContractError(f"{context}: bytes no reconcilian")
    expected_hash = validate_sha256(entry["sha256"], context=f"{context}.sha256")
    if sha256_file(path, deadline_monotonic=deadline_monotonic) != expected_hash:
        raise ContractError(f"{context}: SHA-256 no reconcilia")
    assigned, reliable, source = allocated_size(path)
    return {
        "path": str(path),
        "relative_path": str(entry["relative_path"]),
        "bytes": size,
        "allocated_bytes": assigned,
        "allocation_reliable": reliable,
        "allocation_source": source,
        "sha256": expected_hash,
    }


def _verify_fixture_file_entry(
    entry: Mapping[str, Any],
    *,
    root: Path,
    context: str,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    required = {
        "relative_path",
        "format",
        "rows",
        "expanded_rows",
        "logical_bytes",
        "allocated_bytes",
        "sha256",
    }
    if set(entry) != required:
        raise ContractError(f"{context}: campos de artefacto fixture no son exactos")
    path = _resolve_relative(root, entry["relative_path"], context=context)
    if not path.is_file() or _is_reparse_or_symlink(path):
        raise ContractError(f"{context}: archivo ausente: {path}")
    if path.stat().st_nlink != 1:
        raise ContractError(f"{context}: hardlink prohibido: {path}")
    if not isinstance(entry["format"], str) or not entry["format"]:
        raise ContractError(f"{context}: formato inválido")
    for key in ("rows", "expanded_rows"):
        value = entry[key]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ContractError(f"{context}: {key} inválido")
    logical = entry["logical_bytes"]
    allocated = entry["allocated_bytes"]
    if (
        isinstance(logical, bool)
        or not isinstance(logical, int)
        or logical < 0
        or isinstance(allocated, bool)
        or not isinstance(allocated, int)
        or allocated < 0
    ):
        raise ContractError(f"{context}: bytes lógico/asignado inválidos")
    assigned, reliable, source = allocated_size(path)
    expected_hash = validate_sha256(entry["sha256"], context=f"{context}.sha256")
    if logical != path.stat().st_size or allocated != assigned:
        raise ContractError(f"{context}: bytes lógico/asignado no reconcilian")
    if sha256_file(path, deadline_monotonic=deadline_monotonic) != expected_hash:
        raise ContractError(f"{context}: SHA-256 no reconcilia")
    if not reliable:
        raise ContractError(f"{context}: allocation size no calificable")
    return {
        **dict(entry),
        "path": str(path),
        "allocation_reliable": True,
        "allocation_source": source,
    }


_RUNTIME_PROBE = r"""
import csv
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

candidate_root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(candidate_root))
import nikodym

distribution = importlib.metadata.distribution("nikodym")
files = list(distribution.files or [])
metadata_rel = [
    str(item)
    for item in files
    if str(item).replace("\\", "/").endswith(".dist-info/METADATA")
]
record_rel = [
    str(item)
    for item in files
    if str(item).replace("\\", "/").endswith(".dist-info/RECORD")
]
if len(metadata_rel) != 1 or len(record_rel) != 1:
    raise RuntimeError("distribution nikodym no expone METADATA/RECORD exactos")
metadata_path = Path(distribution.locate_file(metadata_rel[0])).resolve()
record_path = Path(distribution.locate_file(record_rel[0])).resolve()
package_path = Path(nikodym.__file__).resolve()
record_rows = list(csv.reader(record_path.read_text(encoding="utf-8", newline="").splitlines()))
payload = {
    "distribution": "nikodym",
    "version": distribution.version,
    "distribution_root": str(Path(distribution.locate_file("")).resolve()),
    "dist_info_path": str(metadata_path.parent),
    "metadata_path": str(metadata_path),
    "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    "record_path": str(record_path),
    "record_sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
    "record_rows": record_rows,
    "imported_package_path": str(package_path),
    "imported_package_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
    "no_site": sys.flags.no_site == 1,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
"""


def _path_is_within(path: Path, root: Path) -> bool:
    """Compara rutas resueltas sin aceptar prefijos textuales hermanos."""
    resolved = path.resolve()
    resolved_root = root.resolve()
    return resolved == resolved_root or resolved_root in resolved.parents


def _run_candidate_probe_in_job(
    command: Sequence[str],
    *,
    timeout: float,
    memory_bytes: int,
    affinity_mask: int,
    env: Mapping[str, str],
    capture_root: Path,
    deadline_monotonic: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta el probe autorizado suspendido, confinado y con integridad Low, sin emitir START.

    El probe también ejecuta bytes del candidato, así que hereda el mismo aislamiento OS que el
    consumidor: token de integridad Low y captura por handles ya abiertos por el arnés. Sin esto,
    la garantía sobre ``OUTPUT_ROOT`` tendría un agujero pre-START.
    """
    # La autoridad humana no puede levantar por sí sola las fronteras todavía ausentes, ni
    # siquiera para este lanzamiento pre-START.
    require_calibration_start_implementation_ready()
    if timeout <= 0:
        raise ContractError("deadline del probe candidato agotado")
    if deadline_monotonic is not None and deadline_monotonic <= time.monotonic():
        raise ContractError("deadline del probe candidato agotado antes de crear el proceso")
    stdout_path = capture_root / "probe.stdout.bin"
    stderr_path = capture_root / "probe.stderr.bin"
    with (
        WindowsJob(memory_bytes=memory_bytes, affinity_mask=affinity_mask) as probe_job,
        stdout_path.open("xb") as stdout_handle,
        stderr_path.open("xb") as stderr_handle,
    ):
        with low_integrity_primary_token() as probe_token:
            process = launch_suspended_low_integrity(
                list(command),
                token=probe_token,
                cwd=capture_root,
                environment=dict(env),
                stdout_fd=stdout_handle.fileno(),
                stderr_fd=stderr_handle.fileno(),
            )
        try:
            probe_job.assign(process.pid)
            effective_integrity = process_integrity_level(process.pid)
            if effective_integrity != LOW_INTEGRITY_SID:
                raise ContractError(
                    "limits_not_applied: el probe candidato no quedó en integridad Low efectiva "
                    f"({effective_integrity})"
                )
            if deadline_monotonic is not None:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise ContractError("deadline del probe candidato agotado antes de resume")
                timeout = min(timeout, remaining)
            resume_suspended_process(process.pid, probe_job.api)
            returncode = process.wait(timeout=timeout)
        except BaseException:
            with contextlib.suppress(Exception):
                probe_job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
            with contextlib.suppress(Exception):
                process.wait(timeout=10)
            raise
        finally:
            process.close()
        if not probe_job.wait_empty(10.0):
            probe_job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
            raise ContractError("probe candidato dejó procesos huérfanos")
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=returncode,
        # stdout debe ser JSON canónico exacto y se decodifica estricto. stderr es diagnóstico del
        # candidato: su codificación depende del host, así que no puede tumbar al supervisor con
        # una excepción sin clasificar.
        stdout=stdout_path.read_bytes().decode("utf-8"),
        stderr=stderr_path.read_bytes().decode("utf-8", errors="replace"),
    )


def _probe_candidate_runtime(
    *,
    python_executable: Path,
    installed_tree_root: Path,
    wheel_path: Path,
    lock_path: Path,
    installed_tree_sha256: str,
    memory_bytes: int,
    affinity_mask: int,
    deadline_monotonic: float | None,
) -> dict[str, Any]:
    """Prueba con ``-I -B`` que wheel, lock, RECORD e import describen la misma instalación."""
    require_calibration_start_implementation_ready()
    timeout = 30.0
    if deadline_monotonic is not None:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise ContractError("deadline del probe candidato agotado antes de crear el proceso")
        timeout = min(timeout, remaining)
    with tempfile.TemporaryDirectory(prefix="nikodym-h9r-probe-pycache-") as cache:
        completed = _run_candidate_probe_in_job(
            [
                str(python_executable),
                "-I",
                "-B",
                "-S",
                "-X",
                f"pycache_prefix={cache}",
                "-c",
                _RUNTIME_PROBE,
                str(installed_tree_root.resolve()),
            ],
            timeout=timeout,
            memory_bytes=memory_bytes,
            affinity_mask=affinity_mask,
            env={
                key: os.environ[key]
                for key in ("SYSTEMDRIVE", "SYSTEMROOT", "WINDIR")
                if key in os.environ
            },
            capture_root=Path(cache),
            deadline_monotonic=deadline_monotonic,
        )
    if completed.returncode != 0:
        raise ContractError(
            "runtime candidato no importa nikodym de forma aislada: "
            f"returncode={completed.returncode}; stderr={completed.stderr[-2000:]!r}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ContractError("probe de runtime no produjo un único objeto JSON")
    try:
        raw: Any = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ContractError("probe de runtime produjo JSON inválido") from exc
    probe = _require_mapping(raw, context="runtime.probe")
    required = {
        "distribution",
        "version",
        "distribution_root",
        "dist_info_path",
        "metadata_path",
        "metadata_sha256",
        "record_path",
        "record_sha256",
        "record_rows",
        "imported_package_path",
        "imported_package_sha256",
        "no_site",
    }
    if set(probe) != required or probe["distribution"] != "nikodym" or probe["no_site"] is not True:
        raise ContractError("probe de runtime no tiene campos/distribución exactos")
    tree_root = installed_tree_root.resolve()
    distribution_root = Path(str(probe["distribution_root"])).resolve()
    dist_info_path = Path(str(probe["dist_info_path"])).resolve()
    metadata_path = Path(str(probe["metadata_path"])).resolve()
    record_path = Path(str(probe["record_path"])).resolve()
    imported_path = Path(str(probe["imported_package_path"])).resolve()
    if distribution_root != tree_root:
        raise ContractError("distribution_root aislado no coincide con installed_tree")
    for name, path in (
        ("dist-info", dist_info_path),
        ("METADATA", metadata_path),
        ("RECORD", record_path),
        ("import nikodym", imported_path),
    ):
        if not _path_is_within(path, tree_root) or not path.exists():
            raise ContractError(f"runtime {name} escapa o falta en installed_tree")
    if metadata_path.parent != dist_info_path or record_path.parent != dist_info_path:
        raise ContractError("METADATA/RECORD no pertenecen al dist-info observado")
    for name, path in (
        ("metadata", metadata_path),
        ("record", record_path),
        ("import", imported_path),
    ):
        observed = sha256_file(path, deadline_monotonic=deadline_monotonic)
        raw_digest = (
            probe[f"{name}_sha256"] if name != "import" else probe["imported_package_sha256"]
        )
        declared = validate_sha256(raw_digest, context=f"runtime.probe.{name}")
        if observed != declared:
            raise ContractError(f"runtime {name} cambió durante el probe")
    rows = probe["record_rows"]
    if (
        not isinstance(rows, list)
        or not rows
        or not all(
            isinstance(row, list) and len(row) == 3 and all(isinstance(item, str) for item in row)
            for row in rows
        )
    ):
        raise ContractError("RECORD del runtime no tiene filas CSV exactas")
    imported_relative = imported_path.relative_to(tree_root).as_posix()
    imported_rows = [row for row in rows if str(row[0]).replace("\\", "/") == imported_relative]
    if len(imported_rows) != 1 or not imported_rows[0][1].startswith("sha256="):
        raise ContractError("RECORD no liga exactamente el módulo nikodym importado")
    import base64

    encoded = imported_rows[0][1].removeprefix("sha256=")
    padding = "=" * (-len(encoded) % 4)
    if base64.urlsafe_b64decode(encoded + padding).hex() != probe["imported_package_sha256"]:
        raise ContractError("hash RECORD del módulo importado no reconcilia")
    if imported_rows[0][2] != str(imported_path.stat().st_size):
        raise ContractError("bytes RECORD del módulo importado no reconcilian")

    wheel_sha256 = sha256_file(wheel_path, deadline_monotonic=deadline_monotonic)
    try:
        with zipfile.ZipFile(wheel_path) as wheel:
            names = wheel.namelist()
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
            package_names = [name for name in names if name == "nikodym/__init__.py"]
            if (
                len(metadata_names) != 1
                or len(record_names) != 1
                or package_names != ["nikodym/__init__.py"]
            ):
                raise ContractError("wheel no contiene METADATA/RECORD/package exactos")
            wheel_metadata = wheel.read(metadata_names[0])
            wheel_import_sha = sha256_bytes(wheel.read(package_names[0]))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise ContractError("wheel candidato no es un wheel ZIP calificable") from exc
    from email.parser import BytesParser

    metadata = BytesParser().parsebytes(wheel_metadata)
    if str(metadata.get("Name", "")).casefold().replace("_", "-") != "nikodym":
        raise ContractError("wheel METADATA no identifica distribución nikodym")
    if metadata.get("Version") != probe["version"]:
        raise ContractError("wheel y distribution instalada difieren en versión")
    if sha256_bytes(wheel_metadata) != probe["metadata_sha256"]:
        raise ContractError("METADATA instalada no coincide byte a byte con wheel")
    if wheel_import_sha != probe["imported_package_sha256"]:
        raise ContractError("import nikodym no coincide byte a byte con wheel")
    import tomllib

    try:
        lock_value: Any = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractError("lock candidato no es TOML UTF-8 calificable") from exc
    if not isinstance(lock_value, dict):
        raise ContractError("lock candidato no contiene objeto top-level")
    raw_packages = lock_value.get("package")
    if not isinstance(raw_packages, list):
        raise ContractError("lock candidato no enumera [[package]]")
    nikodym_packages = [
        package
        for package in raw_packages
        if isinstance(package, dict)
        and str(package.get("name", "")).casefold().replace("_", "-") == "nikodym"
    ]
    if len(nikodym_packages) != 1:
        raise ContractError("lock no contiene exactamente un package nikodym")
    locked_package = cast(dict[str, Any], nikodym_packages[0])
    if locked_package.get("version") != probe["version"]:
        raise ContractError("lock y runtime difieren en versión nikodym")

    def locked_hashes(value: Any, *, key: str | None = None) -> set[str]:
        observed: set[str] = set()
        if isinstance(value, dict):
            for child_key, child in value.items():
                observed.update(locked_hashes(child, key=str(child_key)))
        elif isinstance(value, list):
            for child in value:
                observed.update(locked_hashes(child, key=key))
        elif isinstance(value, str) and key in {"hash", "sha256"}:
            normalized = value.removeprefix("sha256:").removeprefix("sha256=")
            if len(normalized) == 64:
                observed.add(normalized.lower())
        return observed

    if wheel_sha256 not in locked_hashes(locked_package):
        raise ContractError("lock no contiene el SHA-256 exacto del wheel candidato")
    probe_payload_sha256 = canonical_json_sha256(probe)
    return {
        "probe_schema_version": RUNTIME_PROVENANCE_SCHEMA_VERSION,
        "isolation_flags": ["-I", "-B", "-S"],
        "no_site": True,
        "distribution": "nikodym",
        "version": str(probe["version"]),
        "distribution_root": str(distribution_root),
        "dist_info_path": str(dist_info_path),
        "metadata_sha256": str(probe["metadata_sha256"]),
        "record_sha256": str(probe["record_sha256"]),
        "record_entries": len(rows),
        "imported_package_path": str(imported_path),
        "imported_package_sha256": str(probe["imported_package_sha256"]),
        "installed_tree_sha256": validate_sha256(
            installed_tree_sha256, context="runtime.installed_tree.sha256"
        ),
        "wheel_sha256": wheel_sha256,
        "lock_sha256": sha256_file(lock_path, deadline_monotonic=deadline_monotonic),
        "probe_payload_sha256": probe_payload_sha256,
    }


def _validate_declared_runtime_provenance(
    value: Mapping[str, Any],
    *,
    installed_tree_root: Path,
    installed_tree_sha256: str,
    wheel_sha256: str,
    lock_sha256: str,
) -> dict[str, Any]:
    """Valida bindings de provenance sin ejecutar el Python del candidato."""
    required = {
        "probe_schema_version",
        "isolation_flags",
        "no_site",
        "distribution",
        "version",
        "distribution_root",
        "dist_info_path",
        "metadata_sha256",
        "record_sha256",
        "record_entries",
        "imported_package_path",
        "imported_package_sha256",
        "installed_tree_sha256",
        "wheel_sha256",
        "lock_sha256",
        "probe_payload_sha256",
    }
    if set(value) != required:
        raise ContractError("candidate.runtime.provenance no tiene campos exactos")
    if value["probe_schema_version"] != RUNTIME_PROVENANCE_SCHEMA_VERSION:
        raise ContractError("candidate.runtime.provenance usa otro schema")
    if (
        value["isolation_flags"] != ["-I", "-B", "-S"]
        or value["no_site"] is not True
        or value["distribution"] != "nikodym"
    ):
        raise ContractError("candidate.runtime.provenance no acredita aislamiento/distribución")
    if not isinstance(value["version"], str) or not value["version"]:
        raise ContractError("candidate.runtime.provenance.version inválida")
    record_entries = value["record_entries"]
    if (
        isinstance(record_entries, bool)
        or not isinstance(record_entries, int)
        or record_entries < 1
    ):
        raise ContractError("candidate.runtime.provenance.record_entries inválido")
    tree_root = installed_tree_root.resolve()
    if Path(str(value["distribution_root"])).resolve() != tree_root:
        raise ContractError("provenance distribution_root no coincide con installed_tree")
    for name in ("dist_info_path", "imported_package_path"):
        path = Path(str(value[name])).resolve()
        if not _path_is_within(path, tree_root) or not path.exists():
            raise ContractError(f"provenance {name} escapa o falta en installed_tree")
    for name in (
        "metadata_sha256",
        "record_sha256",
        "imported_package_sha256",
        "installed_tree_sha256",
        "wheel_sha256",
        "lock_sha256",
        "probe_payload_sha256",
    ):
        validate_sha256(value[name], context=f"candidate.runtime.provenance.{name}")
    expected_bindings = {
        "installed_tree_sha256": installed_tree_sha256,
        "wheel_sha256": wheel_sha256,
        "lock_sha256": lock_sha256,
    }
    if any(value[name] != expected for name, expected in expected_bindings.items()):
        raise ContractError("provenance no liga árbol/wheel/lock vivos")
    return dict(value)


def _validate_source_revision(value: Any, *, context: str) -> str:
    """Exige revisión lowercase real y rechaza placeholders 0/f."""
    if (
        not isinstance(value, str)
        or len(value) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in value)
        or value in {"0" * len(value), "f" * len(value)}
    ):
        raise ContractError(f"{context} inválido/no canónico/placeholder")
    return value


def validate_candidate_manifest_passive(
    manifest: Mapping[str, Any],
    *,
    expected_sha256: str,
    manifest_root: Path,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Reconcilia manifiesto y artefactos sin ejecutar código del candidato."""
    required = {"schema_version", "source_sha", "wheel", "sdist", "lock", "runtime"}
    if set(manifest) != required:
        raise ContractError("campos del manifiesto candidato no son exactos")
    if manifest["schema_version"] != CANDIDATE_SCHEMA_VERSION:
        raise ContractError("schema candidato inesperado")
    source_sha = _validate_source_revision(manifest["source_sha"], context="source_sha candidato")
    actual_manifest_hash = canonical_json_sha256(manifest)
    if actual_manifest_hash != expected_sha256:
        raise ContractError("candidate_manifest_sha256 no reconcilia con JSON canónico")
    runtime = _require_mapping(manifest["runtime"], context="candidate.runtime")
    if set(runtime) != {"python_executable", "environment", "installed_tree", "provenance"}:
        raise ContractError("candidate.runtime no tiene campos exactos")
    python_executable = _verify_file_entry(
        _require_mapping(runtime["python_executable"], context="runtime.python_executable"),
        root=manifest_root,
        context="runtime.python_executable",
        deadline_monotonic=deadline_monotonic,
    )
    environment = _verify_file_entry(
        _require_mapping(runtime["environment"], context="runtime.environment"),
        root=manifest_root,
        context="runtime.environment",
        deadline_monotonic=deadline_monotonic,
    )
    installed_tree = _require_mapping(runtime["installed_tree"], context="runtime.installed_tree")
    if set(installed_tree) != {"relative_path", "files", "logical_bytes", "sha256"}:
        raise ContractError("candidate.runtime.installed_tree no tiene campos exactos")
    tree_root = _resolve_relative(
        manifest_root, installed_tree["relative_path"], context="runtime.installed_tree"
    )
    _reject_reparse_tree(tree_root, context="runtime.installed_tree")
    actual_tree = canonical_tree_identity(tree_root, deadline_monotonic=deadline_monotonic)
    declared_tree = {key: installed_tree[key] for key in ("files", "logical_bytes", "sha256")}
    validate_sha256(declared_tree["sha256"], context="runtime.installed_tree.sha256")
    if declared_tree != actual_tree:
        raise ContractError("identidad del árbol instalado no reconcilia")
    environment_value = read_json_object(Path(str(environment["path"])))
    if set(environment_value) != {
        "schema_version",
        "distribution",
        "source_sha",
        "python_executable_relative_path",
        "python_executable_sha256",
        "installed_tree_relative_path",
        "installed_tree_sha256",
    }:
        raise ContractError("candidate runtime environment no tiene campos exactos")
    if environment_value["schema_version"] != CANDIDATE_ENVIRONMENT_SCHEMA_VERSION:
        raise ContractError("candidate runtime environment usa otro schema")
    if environment_value["distribution"] != "nikodym":
        raise ContractError("candidate runtime environment no identifica nikodym")
    expected_environment = {
        "source_sha": source_sha,
        "python_executable_relative_path": manifest["runtime"]["python_executable"][
            "relative_path"
        ],
        "python_executable_sha256": python_executable["sha256"],
        "installed_tree_relative_path": installed_tree["relative_path"],
        "installed_tree_sha256": actual_tree["sha256"],
    }
    if any(environment_value[key] != expected for key, expected in expected_environment.items()):
        raise ContractError("candidate runtime environment no liga ejecutable/árbol/source")
    wheel = _verify_file_entry(
        _require_mapping(manifest["wheel"], context="candidate.wheel"),
        root=manifest_root,
        context="wheel",
        deadline_monotonic=deadline_monotonic,
    )
    sdist = _verify_file_entry(
        _require_mapping(manifest["sdist"], context="candidate.sdist"),
        root=manifest_root,
        context="sdist",
        deadline_monotonic=deadline_monotonic,
    )
    lock = _verify_file_entry(
        _require_mapping(manifest["lock"], context="candidate.lock"),
        root=manifest_root,
        context="lock",
        deadline_monotonic=deadline_monotonic,
    )
    declared_provenance = _validate_declared_runtime_provenance(
        _require_mapping(runtime["provenance"], context="candidate.runtime.provenance"),
        installed_tree_root=tree_root,
        installed_tree_sha256=str(actual_tree["sha256"]),
        wheel_sha256=str(wheel["sha256"]),
        lock_sha256=str(lock["sha256"]),
    )
    return {
        "manifest_sha256": actual_manifest_hash,
        "manifest_root": str(manifest_root.resolve()),
        "source_sha": source_sha,
        "wheel": wheel,
        "sdist": sdist,
        "lock": lock,
        "runtime": {
            "python_executable": python_executable,
            "environment": environment,
            "installed_tree": {
                **dict(installed_tree),
                "path": str(tree_root),
            },
            "provenance": declared_provenance,
        },
    }


def _require_distinct_harness_and_candidate_runtimes(
    *, candidate: Mapping[str, Any], tooling: Mapping[str, Any]
) -> None:
    candidate_python = cast(
        dict[str, Any], cast(dict[str, Any], candidate["runtime"])["python_executable"]
    )
    harness_python = cast(
        dict[str, Any], cast(dict[str, Any], tooling["harness_runtime"])["python_executable"]
    )
    candidate_path = Path(str(candidate_python["path"]))
    harness_path = Path(str(harness_python["path"]))
    if os.path.normcase(os.path.abspath(candidate_path)) == os.path.normcase(
        os.path.abspath(harness_path)
    ) or (
        candidate_python["sha256"] == harness_python["sha256"]
        and int(candidate_python["bytes"]) == int(harness_python["bytes"])
    ):
        raise ContractError("candidate Python debe ser distinto del runtime confiable del arnés")


def _validate_candidate_manifest_after_authority(
    manifest: Mapping[str, Any],
    *,
    expected_sha256: str,
    manifest_root: Path,
    memory_bytes: int,
    affinity_mask: int,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Valida pasivamente y luego prueba el runtime aislado tras autoridad válida."""
    normalized = validate_candidate_manifest_passive(
        manifest,
        expected_sha256=expected_sha256,
        manifest_root=manifest_root,
        deadline_monotonic=deadline_monotonic,
    )
    runtime = cast(dict[str, Any], normalized["runtime"])
    installed_tree = cast(dict[str, Any], runtime["installed_tree"])
    observed_provenance = _probe_candidate_runtime(
        python_executable=Path(str(cast(dict[str, Any], runtime["python_executable"])["path"])),
        installed_tree_root=Path(str(installed_tree["path"])),
        wheel_path=Path(str(cast(dict[str, Any], normalized["wheel"])["path"])),
        lock_path=Path(str(cast(dict[str, Any], normalized["lock"])["path"])),
        installed_tree_sha256=str(installed_tree["sha256"]),
        memory_bytes=memory_bytes,
        affinity_mask=affinity_mask,
        deadline_monotonic=deadline_monotonic,
    )
    if runtime["provenance"] != observed_provenance:
        raise ContractError("provenance declarada no reconcilia con runtime aislado/wheel/lock")
    return normalized


# Superficie pública deliberadamente pasiva: validar evidencia/manifiestos nunca ejecuta el
# runtime candidato. Sólo ``run_preflight`` y su revalidación, tras firma válida, llaman al helper
# privado activo.
validate_candidate_manifest = validate_candidate_manifest_passive


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Rechaza claves JSON duplicadas en vez de aceptar silenciosamente la última."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"input JSON dimensional repite la clave {key!r}")
        result[key] = value
    return result


def _iter_json_array_objects(path: Path) -> Iterator[dict[str, Any]]:
    """Decodifica incrementalmente un array JSON sin materializar el fixture completo."""
    decoder = json.JSONDecoder(object_pairs_hook=_unique_json_object)
    with path.open("r", encoding="utf-8", newline="") as handle:
        buffer = ""
        position = 0
        eof = False

        def fill() -> None:
            nonlocal buffer, position, eof
            if position:
                buffer = buffer[position:]
                position = 0
            chunk = handle.read(64 * 1024)
            if chunk:
                buffer += chunk
            else:
                eof = True

        fill()
        while True:
            while position >= len(buffer) and not eof:
                fill()
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position < len(buffer):
                break
            if eof:
                raise ContractError("input JSON dimensional vacío")
        if buffer[position] != "[":
            raise ContractError("input JSON dimensional debe ser un array")
        position += 1
        expect_value = True
        observed = 0
        while True:
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer) or eof:
                    break
                fill()
            if position < len(buffer) and buffer[position] == "]":
                position += 1
                if expect_value and observed:
                    raise ContractError("input JSON dimensional termina tras coma")
                break
            if not expect_value:
                if position >= len(buffer) or buffer[position] != ",":
                    raise ContractError("input JSON dimensional carece de separador")
                position += 1
                expect_value = True
                continue
            while True:
                try:
                    value, end = decoder.raw_decode(buffer, position)
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise ContractError("input JSON dimensional truncado/inválido") from exc
                    fill()
            if not isinstance(value, dict):
                raise ContractError("input JSON dimensional debe contener objetos")
            position = end
            observed += 1
            expect_value = False
            yield dict(value)
        while True:
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position < len(buffer):
                raise ContractError("input JSON dimensional contiene bytes tras el array")
            if eof:
                break
            fill()


def _fixture_tabular_rows(path: Path, file_format: str) -> Iterator[dict[str, Any]]:
    """Itera formatos cerrados por lotes; nunca convierte Parquet/JSONL/CSV completo a memoria."""
    if file_format == "csv":

        def csv_rows() -> Iterator[dict[str, Any]]:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise ContractError("input CSV dimensional carece de encabezado")
                if len(reader.fieldnames) != len(set(reader.fieldnames)):
                    raise ContractError("input CSV dimensional repite columnas en el encabezado")
                for row in reader:
                    if None in row:
                        raise ContractError(
                            "input CSV dimensional contiene columnas sin encabezado"
                        )
                    yield dict(row)

        return csv_rows()
    if file_format == "jsonl":

        def jsonl_rows() -> Iterator[dict[str, Any]]:
            with path.open("r", encoding="utf-8", newline="") as handle:
                for line in handle:
                    try:
                        value: Any = json.loads(line, object_pairs_hook=_unique_json_object)
                    except json.JSONDecodeError as exc:
                        raise ContractError("input JSONL dimensional inválido") from exc
                    if not isinstance(value, dict):
                        raise ContractError("input JSONL dimensional debe contener objetos")
                    yield dict(value)

        return jsonl_rows()
    if file_format == "json":
        return _iter_json_array_objects(path)
    if file_format == "parquet":
        try:
            import pyarrow.parquet as pq
        except Exception as exc:
            raise ContractError("pyarrow no disponible para reabrir Parquet") from exc

        def parquet_rows() -> Iterator[dict[str, Any]]:
            try:
                parquet: Any = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
                names = list(parquet.schema_arrow.names)
                if len(names) != len(set(names)):
                    raise ContractError("input Parquet dimensional repite columnas")
                for batch in parquet.iter_batches(batch_size=65_536):
                    for row in cast(list[dict[str, Any]], batch.to_pylist()):
                        yield dict(row)
            except Exception as exc:
                raise ContractError("input Parquet no se pudo reabrir dimensionalmente") from exc

        return parquet_rows()
    raise ContractError(f"formato de input no derivable dimensionalmente: {file_format!r}")


def _normalize_fixture_value(value: Any, dtype: str, *, csv_text: bool) -> Any:
    """Normaliza un valor por dtype para que CSV/JSON/Parquet deriven igual geometría."""
    normalized = dtype.casefold()
    if value is None:
        raise ContractError("valor nulo no declarado como missing")
    if normalized in {"str", "string", "category", "categorical", "datetime", "date"}:
        if not isinstance(value, str):
            raise ContractError(f"valor no reconcilia dtype {dtype!r}")
        return value
    if normalized in {"int", "integer", "int64"}:
        if isinstance(value, bool):
            raise ContractError(f"valor booleano no reconcilia dtype {dtype!r}")
        if isinstance(value, int):
            return value
        if csv_text and isinstance(value, str):
            try:
                parsed = int(value)
            except ValueError:
                pass
            else:
                if str(parsed) == value.strip():
                    return parsed
        raise ContractError(f"valor no reconcilia dtype {dtype!r}")
    if normalized in {"float", "float64", "number", "numerical"}:
        if isinstance(value, bool):
            raise ContractError(f"valor booleano no reconcilia dtype {dtype!r}")
        parsed_float: float
        if isinstance(value, (int, float)):
            parsed_float = float(value)
        elif csv_text and isinstance(value, str):
            try:
                parsed_float = float(value)
            except ValueError:
                raise ContractError(f"valor no reconcilia dtype {dtype!r}") from None
        else:
            raise ContractError(f"valor no reconcilia dtype {dtype!r}")
        if not math.isfinite(parsed_float):
            raise ContractError(f"valor no finito no reconcilia dtype {dtype!r}")
        return parsed_float
    if normalized in {"bool", "boolean"}:
        if isinstance(value, bool):
            return value
        if csv_text and isinstance(value, str):
            lowered = value.casefold()
            if lowered in {"true", "1"}:
                return True
            if lowered in {"false", "0"}:
                return False
        raise ContractError(f"valor no reconcilia dtype {dtype!r}")
    if normalized in {"bytes", "binary"}:
        if isinstance(value, (bytes, str)):
            return value.hex() if isinstance(value, bytes) else value
        raise ContractError(f"valor no reconcilia dtype {dtype!r}")
    raise ContractError(f"dtype de fixture no soportado por el oráculo: {dtype!r}")


def _scan_primary_fixture(
    *,
    path: Path,
    file_format: str,
    schema_columns: Sequence[Mapping[str, Any]],
    need_max_cardinality: bool,
    need_periods: bool,
    deadline_monotonic: float | None,
    catalog_value: Mapping[str, Any],
    scratch_root: Path,
) -> tuple[int, int | None, int | None]:
    """Recorre el primario una sola vez y derrama distincts a SQLite temporal."""
    expected_columns = [str(column["name"]) for column in schema_columns]
    expected_set = set(expected_columns)
    features = [
        str(column["name"])
        for column in schema_columns
        if str(column["role"]).casefold() in {"feature", "variable", "covariate"}
    ]
    periods = [
        str(column["name"])
        for column in schema_columns
        if str(column["role"]).casefold() == "period"
    ]
    if need_max_cardinality and not features:
        raise ContractError("max_cardinality exige columnas feature en fixture schema")
    if need_periods and len(periods) != 1:
        raise ContractError("periods exige exactamente una columna role=period")
    dtype_by_name = {str(column["name"]): str(column["dtype"]) for column in schema_columns}
    missing_values = cast(list[Any], catalog_value["missing_values"])
    special_values = cast(list[Any], catalog_value["special_values"])

    def declared_value(value: Any, dtype: str, declared: Sequence[Any], *, csv_text: bool) -> bool:
        if value is None:
            return any(item is None for item in declared)
        if (isinstance(value, float) and math.isnan(value)) or (
            isinstance(value, str) and value.casefold() == "nan"
        ):
            return any(isinstance(item, str) and item.casefold() == "nan" for item in declared)
        try:
            normalized_value = _normalize_fixture_value(value, dtype, csv_text=csv_text)
        except ContractError:
            return False
        for item in declared:
            try:
                normalized_item = _normalize_fixture_value(
                    item, dtype, csv_text=isinstance(item, str)
                )
            except ContractError:
                continue
            if normalized_value == normalized_item:
                return True
        return False

    row_count = 0
    max_cardinality: int | None = None
    period_cardinality: int | None = None
    safe_scratch = _require_plain_directory(scratch_root, context="geometry.scratch_root")
    if any(safe_scratch.iterdir()):
        raise ContractError("geometry scratch debe estar vacío antes del scan")
    database_path = safe_scratch / "distinct.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        try:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE distinct_values ("
                "dimension TEXT NOT NULL, value_sha256 TEXT NOT NULL, "
                "PRIMARY KEY (dimension, value_sha256)) WITHOUT ROWID"
            )
            for row in _fixture_tabular_rows(path, file_format):
                row_count += 1
                if row_count % 8_192 == 0:
                    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                        raise ContractError("deadline agotado al derivar geometría material")
                    connection.commit()
                if set(row) != expected_set:
                    missing = sorted(expected_set - set(row))
                    extra = sorted(set(row) - expected_set)
                    raise ContractError(
                        "columnas del input primario no reconcilian con fixture_schema; "
                        f"faltan={missing}, sobran={extra}"
                    )
                normalized_row: dict[str, Any] = {}
                for column_name in expected_columns:
                    value = row[column_name]
                    dtype = dtype_by_name[column_name]
                    if declared_value(
                        value,
                        dtype,
                        missing_values,
                        csv_text=file_format == "csv",
                    ):
                        continue
                    try:
                        normalized_row[column_name] = _normalize_fixture_value(
                            value, dtype, csv_text=file_format == "csv"
                        )
                    except ContractError as exc:
                        raise ContractError(
                            f"input primario no reconcilia dtype de {column_name!r}: {dtype!r}"
                        ) from exc
                for dimension_name, column_name in (
                    [(f"feature:{name}", name) for name in features] if need_max_cardinality else []
                ) + ([("period", periods[0])] if need_periods else []):
                    raw_value = row[column_name]
                    dtype = dtype_by_name[column_name]
                    if declared_value(
                        raw_value,
                        dtype,
                        missing_values,
                        csv_text=file_format == "csv",
                    ):
                        continue
                    value = normalized_row[column_name]
                    # Los especiales declarados siguen participando en cardinalidad: son valores
                    # materiales del dominio, no ausencias. Su presencia queda ligada al catálogo
                    # firmado por el hash fuente de la geometría.
                    if declared_value(
                        raw_value,
                        dtype,
                        special_values,
                        csv_text=file_format == "csv",
                    ):
                        encoded = canonical_json_bytes({"special": value})
                    else:
                        encoded = canonical_json_bytes(value)
                    connection.execute(
                        "INSERT OR IGNORE INTO distinct_values"
                        "(dimension, value_sha256) VALUES (?, ?)",
                        (dimension_name, sha256_bytes(encoded)),
                    )
            connection.commit()
            if row_count == 0:
                raise ContractError("input primario dimensional no puede estar vacío")
            if need_max_cardinality:
                counts = connection.execute(
                    "SELECT dimension, COUNT(*) FROM distinct_values "
                    "WHERE dimension LIKE 'feature:%' GROUP BY dimension"
                ).fetchall()
                if len(counts) != len(features):
                    raise ContractError("no se pudo derivar cardinalidad de cada feature")
                max_cardinality = max(int(item[1]) for item in counts)
            if need_periods:
                period_cardinality = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM distinct_values WHERE dimension='period'"
                    ).fetchone()[0]
                )
        finally:
            connection.close()
    finally:
        for candidate in sorted(safe_scratch.iterdir(), reverse=True):
            if candidate.is_file() and not _is_reparse_or_symlink(candidate):
                candidate.unlink()
            else:
                raise ContractError("geometry scratch contiene artefacto no atribuible")
        if any(safe_scratch.iterdir()):
            raise ContractError("geometry scratch no quedó byte-exacto tras el scan")
    return row_count, max_cardinality, period_cardinality


def _derive_fixture_geometry(
    *,
    dimensions: Mapping[str, Any],
    inputs: Sequence[Mapping[str, Any]],
    geometry_source: Mapping[str, Any],
    schema_columns: Sequence[Mapping[str, Any]],
    catalog_value: Mapping[str, Any],
    fixture_schema_sha256: str,
    catalog_sha256: str,
    deadline_monotonic: float | None,
    geometry_scratch_root: Path,
) -> dict[str, Any]:
    input_identities = sorted(
        (
            {
                "relative_path": str(item["relative_path"]),
                "logical_bytes": int(item["logical_bytes"]),
                "sha256": str(item["sha256"]),
            }
            for item in inputs
        ),
        key=lambda item: str(item["relative_path"]),
    )
    primary_candidates = [
        item
        for item in inputs
        if item["relative_path"] == geometry_source["primary_input_relative_path"]
        and item["sha256"] == geometry_source["primary_input_sha256"]
    ]
    if len(primary_candidates) != 1:
        raise ContractError("geometry_source no identifica exactamente un input primario")
    primary = primary_candidates[0]
    primary_rows, max_cardinality, period_cardinality = _scan_primary_fixture(
        path=Path(str(primary["path"])),
        file_format=str(primary["format"]),
        schema_columns=schema_columns,
        need_max_cardinality="max_cardinality" in dimensions,
        need_periods="periods" in dimensions,
        deadline_monotonic=deadline_monotonic,
        catalog_value=catalog_value,
        scratch_root=geometry_scratch_root,
    )
    if primary.get("rows") != primary_rows:
        raise ContractError("fixture input primario rows no deriva del contenido reabierto")
    for item in inputs:
        if item is primary:
            continue
        count = derive_output_record_count(
            Path(str(item["path"])), output_format=str(item["format"])
        )
        if item.get("rows") != count:
            raise ContractError("fixture input.rows no deriva del contenido reabierto")
    feature_names = sorted(
        str(column["name"])
        for column in schema_columns
        if str(column["role"]).casefold() in {"feature", "variable", "covariate"}
    )
    derivations: dict[str, Any] = {}
    observed: dict[str, int] = {}
    for name in (key for key in dimensions if key != "expanded_rows"):
        algorithm: str
        if name in {"rows", "operations", "observations", "transitions"}:
            value = primary_rows
            algorithm = "input-data-record-count.v1"
        elif name == "variables":
            value = len(feature_names)
            algorithm = "fixture-schema-feature-columns.v1"
        elif name == "max_cardinality":
            if max_cardinality is None:
                raise ContractError("max_cardinality no pudo derivarse")
            value = max_cardinality
            algorithm = "input-data-max-distinct.v1"
        elif name == "periods":
            if period_cardinality is None:
                raise ContractError("periods no pudo derivarse")
            value = period_cardinality
            algorithm = "input-period-cardinality.v1"
        elif name == "scenarios":
            value = len(cast(list[Any], catalog_value["scenarios"]))
            algorithm = "fixture-catalog-scenario-cardinality.v1"
        elif name == "payload_bytes":
            if len(inputs) != 1:
                raise ContractError("payload UI exige un único input protegido")
            value = int(primary["logical_bytes"])
            algorithm = "ui-request-body-bytes.v1"
        else:  # pragma: no cover - catálogo de geometrías cerrado por contracts.
            raise ContractError(f"dimensión sin oráculo material: {name}")
        observed[name] = value
        if name in {"variables"}:
            sources = [fixture_schema_sha256]
        elif name in {"scenarios"}:
            sources = [catalog_sha256]
        else:
            sources = [str(primary["sha256"])]
        derivations[name] = {
            "algorithm": algorithm,
            "value": value,
            "source_sha256": sources,
        }
    if "expanded_rows" in dimensions:
        factor_names = [key for key in ("operations", "periods", "scenarios") if key in dimensions]
        if len(factor_names) < 2 or any(name not in observed for name in factor_names):
            raise ContractError("expanded_rows carece de dimensiones producto derivadas")
        expanded = 1
        for factor_name in factor_names:
            expanded *= observed[factor_name]
        observed["expanded_rows"] = expanded
        derivations["expanded_rows"] = {
            "algorithm": "dimensions-product.v1",
            "value": expanded,
            "source_sha256": sorted(
                {
                    digest
                    for factor_name in factor_names
                    for digest in derivations[factor_name]["source_sha256"]
                }
            ),
        }
    if observed != dict(dimensions):
        raise ContractError("geometría declarada no coincide con inputs/schema/catálogo reabiertos")
    return {
        "provider": "harness_reopened_inputs_v1",
        "input_set_sha256": canonical_json_sha256(input_identities),
        "primary_input": {
            "relative_path": primary["relative_path"],
            "logical_bytes": primary["logical_bytes"],
            "sha256": primary["sha256"],
        },
        "dimensions": observed,
        "derivations": derivations,
    }


def validate_fixture_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_sha256: str,
    manifest_root: Path,
    deadline_monotonic: float | None = None,
    _allow_harness_test_declared_geometry: bool = False,
    _verify_geometry_material: bool = True,
    _trusted_geometry_observed: Mapping[str, Any] | None = None,
    geometry_scratch_root: Path | None = None,
) -> dict[str, Any]:
    """Reconcilia fixture congelado sin permitir hashes placeholder."""
    if _verify_geometry_material and _trusted_geometry_observed is not None:
        raise ContractError("geometry observada externa no puede sustituir el scan material")
    if (
        not _verify_geometry_material
        and _trusted_geometry_observed is None
        and not _allow_harness_test_declared_geometry
    ):
        raise ContractError("verificación pasiva exige geometry_observed contractual confiable")
    if _allow_harness_test_declared_geometry and _verify_geometry_material:
        raise ContractError("bypass sintético no puede declarar scan material")
    required = {
        "schema_version",
        "flow_id",
        "flow_step",
        "geometry_id",
        "fixture_schema",
        "config",
        "config_hash",
        "root_seed",
        "sub_seed",
        "sub_seed_sha256",
        "generator",
        "dimensions",
        "geometry_source",
        "inputs_root",
        "inputs",
        "bundle_root",
        "bundle",
        "catalog",
        "expected",
        "contains_customer_data",
        "demo_fixture",
    }
    if set(manifest) != required:
        raise ContractError("campos del manifiesto fixture no son exactos")
    if manifest["schema_version"] != FIXTURE_SCHEMA_VERSION:
        raise ContractError("schema fixture inesperado")
    if canonical_json_sha256(manifest) != expected_sha256:
        raise ContractError("fixture_manifest_sha256 no reconcilia con JSON canónico")
    flow_id = manifest["flow_id"]
    flow_step = manifest["flow_step"]
    geometry_id = manifest["geometry_id"]
    if not isinstance(flow_id, str) or not isinstance(flow_step, str):
        raise ContractError("flow/step del fixture inválidos")
    spec = flow_spec(flow_id, flow_step)
    if geometry_id not in spec.geometries:
        raise ContractError("geometry_id del fixture no pertenece al flujo")
    validate_sha256(manifest["config_hash"], context="fixture.config_hash")
    if manifest["root_seed"] != 20240706:
        raise ContractError("root_seed no coincide con el protocolo")
    sub_seed_digest = sha256_bytes(f"h9r-cal-v1\0{flow_id}\0{geometry_id}".encode())
    expected_sub_seed = int(sub_seed_digest[:16], 16)
    if manifest["sub_seed_sha256"] != sub_seed_digest or manifest["sub_seed"] != expected_sub_seed:
        raise ContractError("sub-seed no deriva exactamente de flow/geometry")
    if manifest["contains_customer_data"] is not False or manifest["demo_fixture"] is not False:
        raise ContractError("fixture contiene datos de cliente o pertenece a demo")
    dimensions = _require_mapping(manifest["dimensions"], context="fixture.dimensions")
    if dimensions != dict(spec.geometries[str(geometry_id)]):
        raise ContractError("dimensiones del fixture no coinciden exactamente con la geometría")
    geometry_source = _require_mapping(
        manifest["geometry_source"], context="fixture.geometry_source"
    )
    if set(geometry_source) != {"primary_input_relative_path", "primary_input_sha256"}:
        raise ContractError("fixture.geometry_source no tiene binding primario exacto")
    validate_sha256(
        geometry_source["primary_input_sha256"], context="fixture.geometry_source.sha256"
    )
    fixture_schema = _verify_fixture_file_entry(
        _require_mapping(manifest["fixture_schema"], context="fixture.fixture_schema"),
        root=manifest_root,
        context="fixture_schema",
        deadline_monotonic=deadline_monotonic,
    )
    schema_value = read_json_object(Path(str(fixture_schema["path"])))
    if Path(str(fixture_schema["path"])).read_bytes() != canonical_json_bytes(schema_value) + b"\n":
        raise ContractError("fixture_schema debe usar JSON canónico con newline final")
    if set(schema_value) != {"schema_version", "columns"} or not isinstance(
        schema_value["columns"], list
    ):
        raise ContractError("schema de fixture no declara schema_version/columns")
    if schema_value["schema_version"] != FIXTURE_COLUMNS_SCHEMA_VERSION:
        raise ContractError("schema_version de columnas del fixture inesperado")
    column_names: list[str] = []
    for column in schema_value["columns"]:
        if not isinstance(column, dict) or set(column) != {"name", "dtype", "role"}:
            raise ContractError("columna de fixture no declara name/dtype/role exactos")
        if not all(isinstance(column[key], str) and column[key] for key in column):
            raise ContractError("columna de fixture contiene metadatos vacíos")
        column_names.append(str(column["name"]))
    if len(set(column_names)) != len(column_names):
        raise ContractError("schema de fixture contiene columnas duplicadas")
    config_entry = _verify_fixture_file_entry(
        _require_mapping(manifest["config"], context="fixture.config"),
        root=manifest_root,
        context="fixture.config",
        deadline_monotonic=deadline_monotonic,
    )
    generator = _require_mapping(manifest["generator"], context="fixture.generator")
    if set(generator) != {"artifact", "source_commit"}:
        raise ContractError("generator no tiene campos exactos")
    generator_artifact = _verify_fixture_file_entry(
        _require_mapping(generator["artifact"], context="generator.artifact"),
        root=manifest_root,
        context="generator.artifact",
        deadline_monotonic=deadline_monotonic,
    )
    source_commit = _validate_source_revision(
        generator["source_commit"], context="commit del generador"
    )
    inputs_root = _resolve_relative(
        manifest_root, manifest["inputs_root"], context="fixture.inputs_root"
    )
    _reject_reparse_tree(inputs_root, context="fixture.inputs_root")
    raw_inputs = manifest["inputs"]
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ContractError("fixture.inputs debe ser una lista no vacía")
    inputs = [
        _verify_fixture_file_entry(
            _require_mapping(item, context="fixture.inputs[]"),
            root=manifest_root,
            context="fixture input",
            deadline_monotonic=deadline_monotonic,
        )
        for item in raw_inputs
    ]
    input_boundary = str(inputs_root).rstrip("\\/") + os.sep
    if any(not str(Path(str(item["path"]))).startswith(input_boundary) for item in inputs):
        raise ContractError("un input cae fuera de inputs_root")
    bundle_root = _resolve_relative(
        manifest_root, manifest["bundle_root"], context="fixture.bundle_root"
    )
    _reject_reparse_tree(bundle_root, context="fixture.bundle_root")
    raw_bundle = manifest["bundle"]
    bundle = None
    if raw_bundle is not None:
        bundle = _verify_fixture_file_entry(
            _require_mapping(raw_bundle, context="fixture.bundle"),
            root=manifest_root,
            context="fixture bundle",
            deadline_monotonic=deadline_monotonic,
        )
        bundle_boundary = str(bundle_root).rstrip("\\/") + os.sep
        if not str(Path(str(bundle["path"]))).startswith(bundle_boundary):
            raise ContractError("bundle cae fuera de bundle_root")
    catalog = _verify_fixture_file_entry(
        _require_mapping(manifest["catalog"], context="fixture.catalog"),
        root=manifest_root,
        context="fixture.catalog",
        deadline_monotonic=deadline_monotonic,
    )
    catalog_value = read_json_object(Path(str(catalog["path"])))
    if Path(str(catalog["path"])).read_bytes() != canonical_json_bytes(catalog_value) + b"\n":
        raise ContractError("fixture.catalog debe usar JSON canónico con newline final")
    catalog_fields = {
        "schema_version",
        "special_values",
        "missing_values",
        "categories",
        "scenarios",
        "segments",
        "assumptions",
    }
    if set(catalog_value) != catalog_fields:
        raise ContractError("catálogo del fixture no tiene campos exactos")
    if catalog_value["schema_version"] != FIXTURE_CATALOG_SCHEMA_VERSION:
        raise ContractError("schema_version del catálogo fixture inesperado")
    for name in catalog_fields - {"schema_version"}:
        if not isinstance(catalog_value[name], list):
            raise ContractError(f"fixture.catalog.{name} debe ser lista")
    primary_matches = [
        item
        for item in inputs
        if item["relative_path"] == geometry_source["primary_input_relative_path"]
        and item["sha256"] == geometry_source["primary_input_sha256"]
    ]
    if len(primary_matches) != 1:
        raise ContractError("geometry_source no identifica exactamente un input primario")
    primary_input = primary_matches[0]
    if _allow_harness_test_declared_geometry:
        geometry_observed = {
            "provider": "harness_test_declared_v1",
            "input_set_sha256": canonical_json_sha256(
                sorted(
                    (
                        {
                            "relative_path": str(item["relative_path"]),
                            "logical_bytes": int(item["logical_bytes"]),
                            "sha256": str(item["sha256"]),
                        }
                        for item in inputs
                    ),
                    key=lambda item: str(item["relative_path"]),
                )
            ),
            "dimensions": dict(dimensions),
            "primary_input": {
                "relative_path": geometry_source["primary_input_relative_path"],
                "logical_bytes": primary_input["logical_bytes"],
                "sha256": geometry_source["primary_input_sha256"],
            },
            "derivations": {
                name: {
                    "algorithm": "harness-test-declared.v1",
                    "value": value,
                    "source_sha256": sorted(str(item["sha256"]) for item in inputs),
                }
                for name, value in dimensions.items()
            },
        }
    elif not _verify_geometry_material:
        trusted = dict(cast(Mapping[str, Any], _trusted_geometry_observed))
        expected_primary = {
            "relative_path": str(primary_input["relative_path"]),
            "logical_bytes": int(primary_input["logical_bytes"]),
            "sha256": str(primary_input["sha256"]),
        }
        input_identities = sorted(
            (
                {
                    "relative_path": str(item["relative_path"]),
                    "logical_bytes": int(item["logical_bytes"]),
                    "sha256": str(item["sha256"]),
                }
                for item in inputs
            ),
            key=lambda item: str(item["relative_path"]),
        )
        if (
            trusted.get("provider") != "harness_reopened_inputs_v1"
            or trusted.get("primary_input") != expected_primary
            or trusted.get("input_set_sha256") != canonical_json_sha256(input_identities)
            or trusted.get("dimensions") != dict(dimensions)
        ):
            raise ContractError("geometry_observed confiable no liga inputs/dimensiones actuales")
        geometry_observed = trusted
    else:
        if geometry_scratch_root is None:
            raise ContractError("scan material exige geometry_scratch_root propiedad del arnés")
        geometry_observed = _derive_fixture_geometry(
            dimensions=dimensions,
            inputs=inputs,
            geometry_source=geometry_source,
            schema_columns=cast(list[Mapping[str, Any]], schema_value["columns"]),
            catalog_value=catalog_value,
            fixture_schema_sha256=str(fixture_schema["sha256"]),
            catalog_sha256=str(catalog["sha256"]),
            deadline_monotonic=deadline_monotonic,
            geometry_scratch_root=geometry_scratch_root,
        )
    expected = _require_mapping(manifest["expected"], context="fixture.expected")
    if set(expected) != {"identities", "counts", "golden"}:
        raise ContractError("fixture.expected no tiene campos exactos")
    if expected["identities"] != list(spec.expected_output_identities):
        raise ContractError("identidades esperadas no coinciden con el catálogo del flujo")
    counts = _require_mapping(expected["counts"], context="fixture.expected.counts")
    if set(counts) != set(spec.expected_output_identities) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        raise ContractError("conteos esperados no coinciden con outputs del flujo")
    golden = _verify_fixture_file_entry(
        _require_mapping(expected["golden"], context="fixture.expected.golden"),
        root=manifest_root,
        context="fixture.expected.golden",
        deadline_monotonic=deadline_monotonic,
    )
    golden_path = Path(str(golden["path"]))
    golden_bytes = golden_path.read_bytes()
    try:
        golden_value: Any = json.loads(golden_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("fixture.expected.golden no es JSON canónico") from exc
    if not isinstance(golden_value, list) or canonical_json_bytes(golden_value) != golden_bytes:
        raise ContractError("fixture.expected.golden debe ser una lista JSON canónica sin newline")
    if len(golden_value) != len(spec.expected_output_identities):
        raise ContractError("golden no contiene exactamente un output por identidad")
    observed_golden_identities: list[str] = []
    observed_golden_paths: list[str] = []
    for ordinal, raw_output in enumerate(golden_value):
        output = _require_mapping(raw_output, context=f"fixture.expected.golden[{ordinal}]")
        if set(output) != {
            "relative_path",
            "identity",
            "ordinal",
            "format",
            "record_count",
            "logical_bytes",
            "sha256",
            "count_evidence",
        }:
            raise ContractError("golden output no tiene campos exactos")
        identity = output["identity"]
        if identity != spec.expected_output_identities[ordinal] or output["ordinal"] != ordinal:
            raise ContractError("golden no conserva identidades/ordinales del catálogo")
        relative_path = output["relative_path"]
        output_format = output["format"]
        _golden_output_relative_path(
            relative_path,
            output_format=output_format,
            context=f"fixture.expected.golden[{ordinal}].relative_path",
        )
        record_count = output["record_count"]
        logical_bytes = output["logical_bytes"]
        if (
            isinstance(record_count, bool)
            or not isinstance(record_count, int)
            or record_count != counts[identity]
            or isinstance(logical_bytes, bool)
            or not isinstance(logical_bytes, int)
            or logical_bytes < 0
        ):
            raise ContractError("golden no reconcilia conteo/bytes")
        output_sha256 = validate_sha256(
            output["sha256"], context=f"fixture.expected.golden[{ordinal}].sha256"
        )
        count_evidence = _require_mapping(
            output["count_evidence"], context=f"fixture.expected.golden[{ordinal}].count_evidence"
        )
        if count_evidence != {
            "mode": "derived",
            "counter_id": OUTPUT_FORMAT_COUNTERS[output_format],
            "records": record_count,
            "output_sha256": output_sha256,
            "sidecar": None,
        }:
            raise ContractError("golden count_evidence no es derivable e independiente")
        observed_golden_identities.append(str(identity))
        observed_golden_paths.append(relative_path)
    if len(set(observed_golden_identities)) != len(observed_golden_identities) or len(
        set(observed_golden_paths)
    ) != len(observed_golden_paths):
        raise ContractError("golden contiene identidades o paths duplicados")
    return {
        "manifest_sha256": expected_sha256,
        "manifest_root": str(manifest_root.resolve()),
        "flow_id": flow_id,
        "flow_step": flow_step,
        "geometry_id": geometry_id,
        "fixture_schema": fixture_schema,
        "config": config_entry,
        "config_hash": manifest["config_hash"],
        "root_seed": manifest["root_seed"],
        "sub_seed": manifest["sub_seed"],
        "sub_seed_sha256": sub_seed_digest,
        "generator": {"artifact": generator_artifact, "source_commit": source_commit},
        "dimensions": dict(dimensions),
        "geometry_source": dict(geometry_source),
        "geometry_observed": geometry_observed,
        "inputs_root": str(inputs_root),
        "inputs": inputs,
        "bundle_root": str(bundle_root),
        "bundle": bundle,
        "catalog": catalog,
        "expected": {
            "identities": list(expected["identities"]),
            "counts": dict(counts),
            "golden": golden,
        },
        "contains_customer_data": False,
        "demo_fixture": False,
    }


def validate_external_workdir(
    path: Path, *, checkout_root: Path, onedrive_root: Path | None
) -> Path:
    """Exige un destino nuevo, vacío, fuera de checkout y OneDrive."""
    resolved = path.resolve()
    checkout = checkout_root.resolve()
    checkout_boundary = str(checkout).rstrip("\\/") + os.sep
    if resolved == checkout or str(resolved).startswith(checkout_boundary):
        raise ContractError("workdir H9R cae dentro del checkout")
    if onedrive_root is not None:
        onedrive = onedrive_root.resolve()
        onedrive_boundary = str(onedrive).rstrip("\\/") + os.sep
        if resolved == onedrive or str(resolved).startswith(onedrive_boundary):
            raise ContractError("workdir H9R cae dentro de OneDrive")
    if resolved.exists():
        raise ContractError("workdir H9R debe ser inexistente o directorio vacío")
    return resolved


@contextlib.contextmanager
def _owned_geometry_scratch(*, workdir: Path, attempt_id_value: str) -> Iterator[Path]:
    """Reserva y elimina un scratch de preflight en el mismo volumen que el workdir."""
    parent = _require_plain_directory(workdir.parent, context="geometry.workdir_parent")
    if _is_reparse_or_symlink(parent):
        raise ContractError("geometry scratch no puede vivir bajo reparse point")
    nonce = secrets.token_hex(32)
    root = parent / f".nikodym-h9r-geometry-{attempt_id_value[:16]}-{nonce}"
    marker = root / ".owner.json"
    scan = root / "scan"
    payload = {
        "schema_version": "nikodym.readiness.h9r.geometry-scratch.v1",
        "attempt_id": attempt_id_value,
        "nonce": nonce,
        "path_sha256": sha256_bytes(
            str(root.absolute()).replace("\\", "/").casefold().encode("utf-8")
        ),
    }
    root.mkdir(exist_ok=False)
    try:
        atomic_write_json_exclusive(marker, payload)
        scan.mkdir(exist_ok=False)
        baseline_free = volume_free_bytes(root)
        if baseline_free < PREFLIGHT_MIN_DISK_FREE_BYTES:
            raise ContractError("geometry scratch carece del piso de disco de preflight")
        yield scan
        if any(scan.iterdir()):
            raise ContractError("geometry scratch conserva bytes tras el scan")
    finally:
        cleanup_error: BaseException | None = None
        try:
            if (
                _require_plain_directory(root, context="geometry scratch cleanup") != root.resolve()
                or _is_reparse_or_symlink(marker)
                or read_json_object(marker) != payload
            ):
                raise ContractError("geometry scratch perdió su owner marker")
            allowed = {marker.resolve(), scan.resolve()}
            observed = {item.resolve() for item in root.iterdir()}
            if observed != allowed or any(scan.iterdir()):
                raise ContractError("geometry scratch contiene artefactos no atribuibles")
            scan.rmdir()
            marker.unlink()
            root.rmdir()
        except BaseException as exc:  # cleanup es parte del gate, incluso durante otro fallo.
            cleanup_error = exc
        if cleanup_error is not None:
            raise ContractError(
                f"geometry scratch no pudo limpiarse: {cleanup_error}"
            ) from cleanup_error


def _validate_workdir_reservation(
    preflight: PreflightResult,
    supplied_workdir: Path,
    *,
    require_initial_census: bool,
) -> tuple[Path, Path]:
    """Reabre la reserva exclusiva sin seguir junctions ni aceptar contenido concurrente."""
    reservation = preflight.workdir_reservation
    if reservation is None:
        raise ContractError("attempt exige reserva durable del workdir creada por preflight")
    if set(reservation) != {
        "reservation_id",
        "owner_marker",
        "owner_payload",
        "expected_initial_entries",
        "checkout_root",
        "onedrive_root",
    }:
        raise ContractError("reserva del workdir no tiene campos exactos")
    supplied_absolute = supplied_workdir.absolute()
    for ancestor in (supplied_absolute, *supplied_absolute.parents[:-1]):
        if _is_reparse_or_symlink(ancestor):
            raise ContractError(f"workdir atraviesa symlink/reparse point: {ancestor}")
    workdir = _require_plain_directory(supplied_absolute, context="attempt.workdir")
    if workdir != Path(preflight.workdir_path).resolve():
        raise ContractError("workdir del attempt difiere de la reserva de preflight")
    checkout_root = Path(str(reservation["checkout_root"]))
    onedrive_raw = reservation["onedrive_root"]
    onedrive_root = None if onedrive_raw is None else Path(str(onedrive_raw))
    if _path_is_within(workdir, checkout_root) or (
        onedrive_root is not None and _path_is_within(workdir, onedrive_root)
    ):
        raise ContractError("workdir reservado cayó dentro de checkout/OneDrive")
    _reject_reparse_tree(workdir, context="attempt.workdir reservado")
    marker_value = _require_mapping(
        reservation["owner_marker"], context="workdir_reservation.owner_marker"
    )
    if set(marker_value) != {"path", "bytes", "sha256"}:
        raise ContractError("owner marker no tiene identidad exacta")
    marker = Path(str(marker_value["path"]))
    if marker.resolve() != workdir / ".h9r-reservation-owner.json":
        raise ContractError("owner marker no pertenece a la raíz reservada")
    marker_identity = _source_identity(marker)
    if (
        marker_identity["safe_regular_file"] is not True
        or marker_identity["bytes"] != marker_value["bytes"]
        or marker_identity["sha256"] != marker_value["sha256"]
        or read_json_object(marker) != reservation["owner_payload"]
    ):
        raise ContractError("owner marker del workdir cambió o fue sustituido")
    owner_payload = _require_mapping(
        reservation["owner_payload"], context="workdir_reservation.owner_payload"
    )
    expected_path_sha256 = sha256_bytes(str(workdir).replace("\\", "/").casefold().encode("utf-8"))
    if (
        owner_payload.get("attempt_id") != preflight.attempt_id
        or owner_payload.get("reservation_id") != reservation["reservation_id"]
        or owner_payload.get("workdir_path_sha256") != expected_path_sha256
    ):
        raise ContractError("owner marker no liga attempt/reserva/ruta exactos")
    if require_initial_census:
        entries = _workdir_entries(workdir)
        expected_entries = reservation["expected_initial_entries"]
        if not isinstance(expected_entries, list) or entries != expected_entries:
            raise ContractError("workdir reservado contiene entradas concurrentes/no esperadas")
    return workdir, marker


def _release_workdir_reservation(preflight: PreflightResult, workdir: Path) -> None:
    """Retira el marker sólo tras reabrir su propiedad exacta en el cierre terminal."""
    _, marker = _validate_workdir_reservation(preflight, workdir, require_initial_census=False)
    marker.unlink()
    if os.path.lexists(marker):
        raise ContractError("owner marker siguió presente tras liberar la reserva")


def tooling_identity(
    document_paths: Mapping[str, Path], *, deadline_monotonic: float | None = None
) -> dict[str, Any]:
    """Firma el driver y cada módulo del arnés; ningún import ejecutable queda implícito."""
    for name, path in document_paths.items():
        _require_safe_regular_file(path, context=f"tooling.document.{name}")
    scripts_root = Path(__file__).resolve().parents[1]
    driver = scripts_root / "measure_readiness_h9r.py"
    module_root = Path(__file__).resolve().parent
    files = [
        scripts_root / "__init__.py",
        driver,
        *sorted(module_root.glob("*.py"), key=lambda path: path.name),
    ]
    for path in files:
        _require_safe_regular_file(path, context="tooling.file")
    entries = [
        {
            "relative_path": path.relative_to(scripts_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path, deadline_monotonic=deadline_monotonic),
        }
        for path in files
    ]
    import_roots: list[dict[str, Any]] = []
    root_kinds = {
        "_cffi_backend": "file",
        "cffi": "package_tree",
        "cryptography": "package_tree",
        "pyarrow": "package_tree",
        "threadpoolctl": "file",
    }
    for name in sorted(root_kinds):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise ContractError(f"runtime del arnés no localiza import root {name!r}")
        kind = root_kinds[name]
        if kind == "package_tree":
            if spec.submodule_search_locations is None:
                raise ContractError(f"runtime del arnés esperaba package tree para {name!r}")
            locations = [Path(item).resolve() for item in spec.submodule_search_locations]
            if len(locations) != 1:
                raise ContractError(f"runtime del arnés no tiene raíz única para {name!r}")
            root = _require_plain_directory(locations[0], context=f"harness_runtime.{name}")
            _reject_reparse_tree(root, context=f"harness_runtime.{name}")
            selected_roots = [root]
            if name == "pyarrow":
                pyarrow_libraries = _require_plain_directory(
                    root.parent / "pyarrow.libs",
                    context="harness_runtime.pyarrow.libs",
                )
                _reject_reparse_tree(pyarrow_libraries, context="harness_runtime.pyarrow.libs")
                selected_roots.append(pyarrow_libraries)
            import_files: list[dict[str, Any]] = []
            for selected_root in selected_roots:
                for candidate in _plain_tree_files(
                    selected_root, context=f"harness_runtime.{name}.payload_tree"
                ):
                    safe_candidate = _require_safe_regular_file(
                        candidate,
                        context=f"harness_runtime.{name}.payload",
                        require_single_link=False,
                    )
                    import_files.append(
                        {
                            "relative_path": safe_candidate.relative_to(root.parent).as_posix(),
                            "logical_bytes": safe_candidate.stat().st_size,
                            "sha256": sha256_file(
                                safe_candidate,
                                deadline_monotonic=deadline_monotonic,
                            ),
                        }
                    )
            import_files.sort(key=lambda item: str(item["relative_path"]))
            identity = {
                "files": len(import_files),
                "logical_bytes": sum(int(item["logical_bytes"]) for item in import_files),
                "sha256": canonical_json_sha256(import_files),
            }
        else:
            root = _require_safe_regular_file(
                Path(spec.origin),
                context=f"harness_runtime.{name}",
                require_single_link=False,
            )
            byte_count = root.stat().st_size
            file_manifest = [
                {
                    "relative_path": root.name,
                    "logical_bytes": byte_count,
                    "sha256": sha256_file(root, deadline_monotonic=deadline_monotonic),
                }
            ]
            identity = {
                "files": 1,
                "logical_bytes": byte_count,
                "sha256": canonical_json_sha256(file_manifest),
            }
        import_roots.append(
            {
                "name": name,
                "kind": kind,
                "path": str(root),
                "files": int(cast(int, identity["files"])),
                "logical_bytes": int(cast(int, identity["logical_bytes"])),
                "tree_sha256": str(identity["sha256"]),
            }
        )
    harness_python = _require_safe_regular_file(
        Path(sys.executable), context="harness_runtime.python_executable"
    )
    harness_runtime = {
        "python_executable": {
            "path": str(harness_python),
            "bytes": harness_python.stat().st_size,
            "sha256": sha256_file(harness_python, deadline_monotonic=deadline_monotonic),
        },
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "import_roots": import_roots,
    }
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "files": entries,
        "harness_runtime": harness_runtime,
    }
    return {
        **manifest,
        "manifest_sha256": canonical_json_sha256(manifest),
        "document_sha256": {
            name: sha256_file(path, deadline_monotonic=deadline_monotonic)
            for name, path in sorted(document_paths.items())
        },
        "document_paths": {
            name: str(path.resolve()) for name, path in sorted(document_paths.items())
        },
    }


def validate_harness_config(
    config: Mapping[str, Any],
    *,
    config_root: Path,
    candidate_root: Path,
    unit: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Liga adapter, runtime lógico, argumentos y outputs al config_hash autorizado."""
    required = {
        "schema_version",
        "flow_id",
        "flow_step",
        "geometry_id",
        "consumer",
        "external_client",
        "flow_config",
    }
    if set(config) != required or config["schema_version"] != CONFIG_SCHEMA_VERSION:
        raise ContractError("config H9R no tiene schema/campos exactos")
    for key in ("flow_id", "flow_step", "geometry_id"):
        if config[key] != unit[key]:
            raise ContractError(f"config y unidad difieren en {key}")
    if not isinstance(config["flow_config"], dict):
        raise ContractError("flow_config debe ser un objeto")

    def normalize_entrypoint(raw: Any, *, context: str) -> dict[str, Any]:
        entrypoint = _require_mapping(raw, context=context)
        kind = entrypoint.get("kind")
        if kind != "candidate_installed_script" or set(entrypoint) != {
            "kind",
            "relative_path",
            "sha256",
        }:
            raise ContractError(f"{context}: sólo candidate_installed_script es válido")
        relative = entrypoint["relative_path"]
        pure_relative = PurePosixPath(relative) if isinstance(relative, str) else None
        if (
            not isinstance(relative, str)
            or not relative
            or pure_relative is None
            or pure_relative.is_absolute()
            or relative != pure_relative.as_posix()
            or any(part in {"", ".", ".."} or ":" in part for part in pure_relative.parts)
            or pure_relative.suffix.casefold() != ".py"
        ):
            raise ContractError(f"{context}: relative_path de script inválido")
        script_path = _resolve_relative(candidate_root, relative, context=context)
        if not script_path.is_file() or script_path.is_symlink():
            raise ContractError(f"{context}: script candidato ausente o symlink")
        expected_sha256 = validate_sha256(entrypoint["sha256"], context=f"{context}.sha256")
        if sha256_file(script_path) != expected_sha256:
            raise ContractError(f"{context}: script candidato no reconcilia SHA-256")
        return {
            "kind": kind,
            "relative_path": str(relative),
            "logical_bytes": script_path.stat().st_size,
            "sha256": expected_sha256,
            "path": str(script_path),
        }

    allowed_placeholders = {
        "${BROKERED_INPUTS_JSON}",
        "${SERVICE_HOST}",
        "${SERVICE_PORT}",
        "${SERVICE_READY}",
        "${ATTEMPT_ID}",
        "${CANDIDATE_REQUEST_SHA256}",
        "${STAGING_ROOT}",
        "${ADAPTER_RESULT}",
    }

    def normalize_arguments(raw: Any, *, context: str) -> list[str]:
        if not isinstance(raw, list) or not all(
            isinstance(argument, str) and argument and "\x00" not in argument for argument in raw
        ):
            raise ContractError(f"{context}: argumentos inválidos")
        for argument in raw:
            if "${" in argument and argument not in allowed_placeholders:
                raise ContractError(f"{context}: placeholder no permitido: {argument}")
            if "${" not in argument and Path(argument).is_absolute():
                raise ContractError(f"{context}: argumento literal no puede ser ruta absoluta")
        return cast(list[str], list(raw))

    consumer = _require_mapping(config["consumer"], context="config.consumer")
    if set(consumer) != {
        "adapter_id",
        "entrypoint",
        "arguments",
        "expected_output_identities",
    }:
        raise ContractError("config.consumer no tiene campos exactos")
    adapter_id = ADAPTER_IDS[(str(unit["flow_id"]), str(unit["flow_step"]))]
    if consumer["adapter_id"] != adapter_id:
        raise ContractError("config.consumer.adapter_id no coincide con la frontera cerrada")
    normalized_entrypoint = normalize_entrypoint(
        consumer["entrypoint"], context="config.consumer.entrypoint"
    )
    arguments = normalize_arguments(consumer["arguments"], context="config.consumer")
    if any(arguments.count(name) != 1 for name in ("${STAGING_ROOT}", "${ADAPTER_RESULT}")):
        raise ContractError(
            "config.consumer debe recibir staging y adapter-result exactamente una vez"
        )
    if str(unit["flow_id"]) == "F-UI":
        expected_boundary_arguments = {
            "${SERVICE_HOST}",
            "${SERVICE_PORT}",
            "${SERVICE_READY}",
            "${ATTEMPT_ID}",
            "${CANDIDATE_REQUEST_SHA256}",
        }
        forbidden_boundary_arguments = {"${BROKERED_INPUTS_JSON}"}
    else:
        expected_boundary_arguments = {"${BROKERED_INPUTS_JSON}"}
        forbidden_boundary_arguments = {
            "${SERVICE_HOST}",
            "${SERVICE_PORT}",
            "${SERVICE_READY}",
            "${ATTEMPT_ID}",
            "${CANDIDATE_REQUEST_SHA256}",
        }
    if any(arguments.count(name) != 1 for name in expected_boundary_arguments) or any(
        name in arguments for name in forbidden_boundary_arguments
    ):
        raise ContractError("config.consumer no declara la frontera broker/service exacta")
    expected = consumer["expected_output_identities"]
    spec = flow_spec(str(unit["flow_id"]), str(unit["flow_step"]))
    if expected != list(spec.expected_output_identities):
        raise ContractError("outputs del config no coinciden con el catálogo")
    if expected != fixture["expected"]["identities"]:
        raise ContractError("outputs del config no coinciden con el fixture")
    raw_client = config["external_client"]
    normalized_client: dict[str, Any] | None
    if str(unit["flow_id"]) == "F-UI":
        client = _require_mapping(raw_client, context="config.external_client")
        if set(client) != {
            "adapter_id",
            "loopback_host",
            "port",
            "path",
            "method",
            "timeout_seconds",
            "expected_status",
        }:
            raise ContractError("config.external_client no tiene campos exactos")
        if client["adapter_id"] != "nikodym.h9r.ui.external_client.v1":
            raise ContractError("adapter_id del cliente UI no coincide con el catálogo")
        if client["loopback_host"] not in {"127.0.0.1", "localhost"}:
            raise ContractError("cliente UI sólo admite loopback explícito")
        if client["method"] != "POST":
            raise ContractError("cliente UI sólo admite POST")
        for name, low, high in (
            ("port", 1, 65535),
            ("expected_status", 200, 299),
        ):
            value = client[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ContractError(f"config.external_client.{name} inválido")
        if (
            not isinstance(client["path"], str)
            or not client["path"].startswith("/")
            or client["path"].startswith("//")
            or "#" in client["path"]
            or "\r" in client["path"]
            or "\n" in client["path"]
            or "\x00" in client["path"]
            or not isinstance(client["timeout_seconds"], (int, float))
            or isinstance(client["timeout_seconds"], bool)
            or not 0 < float(client["timeout_seconds"]) <= 60
        ):
            raise ContractError("path/timeout del cliente UI inválidos")
        normalized_client = {
            **dict(client),
            "timeout_seconds": float(client["timeout_seconds"]),
        }
    else:
        if raw_client is not None:
            raise ContractError("sólo F-UI puede declarar cliente externo")
        normalized_client = None
    normalized_flow_config = dict(cast(dict[str, Any], config["flow_config"]))
    raw_service = normalized_flow_config.get("h9r_candidate_service")
    if str(unit["flow_id"]) == "F-UI":
        service = _require_mapping(raw_service, context="config.flow_config.h9r_candidate_service")
        if set(service) != {
            "host",
            "port",
            "ready_timeout_seconds",
            "first_page_oracle",
        }:
            raise ContractError("h9r_candidate_service no tiene campos exactos")
        if service["host"] != "127.0.0.1":
            raise ContractError("servicio candidato UI debe escuchar loopback IPv4")
        if service["port"] == cast(dict[str, Any], normalized_client)["port"]:
            raise ContractError("proxy externo y servicio candidato requieren puertos distintos")
    elif raw_service is not None:
        raise ContractError("sólo F-UI puede declarar h9r_candidate_service")
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "flow_id": unit["flow_id"],
        "flow_step": unit["flow_step"],
        "geometry_id": unit["geometry_id"],
        "consumer": {
            "adapter_id": adapter_id,
            "entrypoint": normalized_entrypoint,
            "arguments": list(arguments),
            "expected_output_identities": list(expected),
        },
        "external_client": normalized_client,
        "flow_config": normalized_flow_config,
    }


def _power_scheme() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["powercfg.exe", "/GETACTIVESCHEME"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": str(exc)}
    return {
        "available": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _cpu_model() -> str:
    """Lee el modelo de CPU expuesto por Windows y falla si no puede atestiguarlo."""
    if sys.platform != "win32":
        raise ContractError("modelo CPU calificable exige Windows")
    import winreg

    path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            raw, _ = winreg.QueryValueEx(key, "ProcessorNameString")
    except OSError as exc:
        raise ContractError("preflight_rejected: no se pudo atestiguar modelo CPU") from exc
    if not isinstance(raw, str) or not raw.strip():
        raise ContractError("preflight_rejected: modelo CPU vacío")
    return raw.strip()


def run_preflight(
    *,
    unit: Mapping[str, Any],
    authority_path: Path,
    trusted_authority_public_key_path: Path,
    authorization_text_path: Path,
    candidate_manifest_path: Path,
    fixture_manifest_path: Path,
    config_path: Path,
    schedule_path: Path,
    prior_evidence_paths: Sequence[Path],
    document_paths: Mapping[str, Path],
    workdir: Path,
    evidence_path: Path,
    checkout_root: Path,
    onedrive_root: Path | None,
    reserve_workdir: bool,
) -> PreflightResult:
    """Ejecuta todos los checks anteriores a READY, sin abrir inputs del consumidor."""
    started_monotonic_ns = time.monotonic_ns()
    started = time.monotonic()
    preflight_deadline = started + PREFLIGHT_DEADLINE_SECONDS
    normalized_unit = validate_attempt_unit(unit)
    spec = flow_spec(str(normalized_unit["flow_id"]), str(normalized_unit["flow_step"]))
    resolved_workdir = validate_external_workdir(
        workdir, checkout_root=checkout_root, onedrive_root=onedrive_root
    )
    if os.path.lexists(evidence_path):
        raise ContractError("destino de evidencia ya existe")
    launch_files = {
        "authority": authority_path,
        "trusted_authority_public_key": trusted_authority_public_key_path,
        "authorization_text": authorization_text_path,
        "candidate_manifest": candidate_manifest_path,
        "fixture_manifest": fixture_manifest_path,
        "config": config_path,
        "schedule": schedule_path,
    }
    launch_captures = _capture_launch_sources(launch_files)
    for index, path in enumerate(prior_evidence_paths):
        _require_safe_regular_file(path, context=f"launch.prior_evidence[{index}]")
    for name, path in document_paths.items():
        _require_safe_regular_file(path, context=f"launch.document.{name}")

    candidate_manifest = cast(dict[str, Any], launch_captures["candidate_manifest"].json_value)
    fixture_manifest = cast(dict[str, Any], launch_captures["fixture_manifest"].json_value)
    config = cast(dict[str, Any], launch_captures["config"].json_value)
    schedule_value = cast(dict[str, Any], launch_captures["schedule"].json_value)
    candidate_manifest_sha256 = canonical_json_sha256(candidate_manifest)
    if candidate_manifest_sha256 != normalized_unit["candidate_manifest_sha256"]:
        raise ContractError("candidate_manifest_sha256 no reconcilia con JSON canónico")
    fixture_manifest_sha256 = canonical_json_sha256(fixture_manifest)
    if fixture_manifest_sha256 != normalized_unit["fixture_manifest_sha256"]:
        raise ContractError("fixture_manifest_sha256 no reconcilia con JSON canónico")
    config_hash = canonical_json_sha256(config)
    if config_hash != normalized_unit["config_hash"]:
        raise ContractError("config_hash no reconcilia con JSON canónico")
    live_tooling = tooling_identity(document_paths, deadline_monotonic=preflight_deadline)
    live_document_hashes = cast(dict[str, str], live_tooling["document_sha256"])
    authority = cast(dict[str, Any], launch_captures["authority"].json_value)
    schedule_sha256, schedule_position = validate_schedule(schedule_value, normalized_unit)
    with _captured_trust_anchor(
        launch_captures["trusted_authority_public_key"]
    ) as trusted_key_snapshot:
        validated_authority = validate_authority(
            authority,
            normalized_unit,
            document_hashes=live_document_hashes,
            tooling_sha256=str(live_tooling["manifest_sha256"]),
            schedule_sha256=schedule_sha256,
            schedule_position=schedule_position,
            trusted_authority_public_key_path=trusted_key_snapshot,
        )
        trusted_key_sha256 = trusted_authority_key_identity(trusted_key_snapshot)[1]
    observed_authorization = launch_captures["authorization_text"].payload
    expected_authorization = authorization_statement(
        normalized_unit,
        authorization_id=str(validated_authority["authorization_id"]),
        authorization_consumption_path_sha256=str(
            validated_authority["authorization_consumption_path_sha256"]
        ),
        tooling_sha256=str(live_tooling["manifest_sha256"]),
        schedule_sha256=schedule_sha256,
        schedule_position=schedule_position,
        scope=str(validated_authority["scope"]),
    )
    if observed_authorization != expected_authorization:
        raise ContractError("texto de autorización no nombra exactamente unidad/tooling/scope")
    if sha256_bytes(observed_authorization) != authority["authorization_text_sha256"]:
        raise ContractError("texto de autorización no reconcilia")
    if reserve_workdir and (
        validated_authority["scope"] != "calibration-start"
        or validated_authority["start_authorized"] is not True
    ):
        raise ContractError(
            "preflight_rejected: el subcomando attempt exige autoridad START exacta"
        )
    if validated_authority["scope"] == "calibration-start":
        try:
            require_calibration_start_implementation_ready()
        except ContractError as exc:
            raise ContractError(f"preflight_rejected: {exc}") from exc
    if sys.platform != "win32":
        raise ContractError("preflight H9R calificable exige Windows")
    affinity = current_process_affinity()
    selected_mask = first_cpu_mask(affinity["process_mask"])
    cap_id = str(normalized_unit["cap_id"])
    from .aggregate import validate_campaign_progress

    with _captured_trust_anchor(
        launch_captures["trusted_authority_public_key"]
    ) as trusted_key_snapshot:
        campaign_progress = validate_campaign_progress(
            schedule=schedule_value,
            current_unit=normalized_unit,
            prior_evidence_paths=prior_evidence_paths,
            trusted_authority_public_key_path=trusted_key_snapshot,
        )
    # La separación de runtimes es una propiedad pasiva y debe cerrarse antes de cualquier
    # ejecución del Python candidato. El probe activo no puede ser el primer lugar que detecte que
    # el manifiesto reutiliza el runtime confiable del arnés.
    passive_candidate = validate_candidate_manifest_passive(
        candidate_manifest,
        expected_sha256=str(normalized_unit["candidate_manifest_sha256"]),
        manifest_root=launch_captures["candidate_manifest"].path.parent,
        deadline_monotonic=preflight_deadline,
    )
    _require_distinct_harness_and_candidate_runtimes(
        candidate=passive_candidate, tooling=live_tooling
    )
    # Sólo una autoridad Ed25519 válida puede habilitar el probe del runtime declarado.
    if (
        validated_authority["scope"] == "calibration-start"
        and validated_authority["start_authorized"] is True
        and CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256 is not None
    ):
        _assert_launch_captures_current(
            launch_captures,
            context="preflight.before_candidate_probe",
        )
        candidate = _validate_candidate_manifest_after_authority(
            candidate_manifest,
            expected_sha256=str(normalized_unit["candidate_manifest_sha256"]),
            manifest_root=launch_captures["candidate_manifest"].path.parent,
            memory_bytes=CAPS[cap_id],
            affinity_mask=selected_mask,
            deadline_monotonic=preflight_deadline,
        )
    else:
        candidate = passive_candidate
    allow_declared_geometry = (
        validated_authority["scope"] == "harness-test-only" and reserve_workdir is False
    )
    if allow_declared_geometry:
        fixture = validate_fixture_manifest(
            fixture_manifest,
            expected_sha256=str(normalized_unit["fixture_manifest_sha256"]),
            manifest_root=launch_captures["fixture_manifest"].path.parent,
            deadline_monotonic=preflight_deadline,
            _allow_harness_test_declared_geometry=True,
            _verify_geometry_material=False,
        )
    else:
        with _owned_geometry_scratch(
            workdir=resolved_workdir,
            attempt_id_value=attempt_id(normalized_unit),
        ) as geometry_scratch:
            fixture = validate_fixture_manifest(
                fixture_manifest,
                expected_sha256=str(normalized_unit["fixture_manifest_sha256"]),
                manifest_root=launch_captures["fixture_manifest"].path.parent,
                deadline_monotonic=preflight_deadline,
                geometry_scratch_root=geometry_scratch,
            )
    for key in ("flow_id", "flow_step", "geometry_id", "config_hash"):
        fixture_key = "config_hash" if key == "config_hash" else key
        unit_key = "flow_step" if key == "flow_step" else key
        if fixture[fixture_key] != normalized_unit[unit_key]:
            raise ContractError(f"fixture y unidad difieren en {key}")
    config_entry_path = Path(str(fixture["config"]["path"]))
    if launch_captures["config"].path != config_entry_path:
        raise ContractError("config_path no coincide con el config firmado por el fixture")
    normalized_config = validate_harness_config(
        config,
        config_root=launch_captures["config"].path.parent,
        candidate_root=Path(
            str(cast(dict[str, Any], candidate["runtime"])["installed_tree"]["path"])
        ),
        unit=normalized_unit,
        fixture=fixture,
    )
    requested_limits = {
        "logical_cpu_count": selected_mask.bit_count(),
        "affinity_mask": selected_mask,
        "job_memory_commit_limit_bytes": CAPS[cap_id],
        "preflight_deadline_seconds": PREFLIGHT_DEADLINE_SECONDS,
        "handshake_deadline_seconds": HANDSHAKE_DEADLINE_SECONDS,
        "workload_deadline_seconds": spec.workload_deadline_seconds,
    }
    with WindowsJob(memory_bytes=CAPS[cap_id], affinity_mask=selected_mask) as probe_job:
        effective_limits = probe_job.effective_limits()
    observed_memory = system_memory_status()
    memory = {
        **observed_memory,
        "nominal_physical_bytes": _nominal_physical_memory_bytes(),
        "physical_visible_bytes": observed_memory["physical_total_bytes"],
    }
    if memory["physical_available_bytes"] < PREFLIGHT_MIN_AVAILABLE_PHYSICAL_BYTES:
        raise ContractError("preflight_rejected: memoria física disponible bajo 2 GiB")
    if memory["commit_available_bytes"] < PREFLIGHT_MIN_COMMIT_HEADROOM_BYTES:
        raise ContractError("preflight_rejected: headroom de commit bajo 2 GiB")
    allocated_inputs_bundle = sum(int(item["allocated_bytes"]) for item in fixture["inputs"])
    if fixture["bundle"] is not None:
        allocated_inputs_bundle += int(cast(dict[str, Any], fixture["bundle"])["allocated_bytes"])
    disk_floor = max(PREFLIGHT_MIN_DISK_FREE_BYTES, 3 * allocated_inputs_bundle)
    disk_free = volume_free_bytes(resolved_workdir)
    if disk_free < disk_floor:
        raise ContractError(
            f"preflight_rejected: disco libre {disk_free} B bajo piso {disk_floor} B"
        )
    tooling = {
        **live_tooling,
        "launch_sources": {
            "authority": {
                "path": str(launch_captures["authority"].path),
                "identity_kind": "canonical_json_sha256",
                "sha256": canonical_json_sha256(authority),
            },
            "authorization_text": {
                "path": str(launch_captures["authorization_text"].path),
                "identity_kind": "raw_file_sha256",
                "sha256": launch_captures["authorization_text"].raw_sha256,
            },
            "trusted_authority_public_key": {
                "path": str(launch_captures["trusted_authority_public_key"].path),
                "identity_kind": "ed25519_public_key_sha256",
                "sha256": trusted_key_sha256,
            },
            "candidate_manifest": {
                "path": str(launch_captures["candidate_manifest"].path),
                "identity_kind": "canonical_json_sha256",
                "sha256": str(normalized_unit["candidate_manifest_sha256"]),
            },
            "fixture_manifest": {
                "path": str(launch_captures["fixture_manifest"].path),
                "identity_kind": "canonical_json_sha256",
                "sha256": str(normalized_unit["fixture_manifest_sha256"]),
            },
            "config": {
                "path": str(launch_captures["config"].path),
                "identity_kind": "canonical_json_sha256",
                "sha256": config_hash,
            },
            "schedule": {
                "path": str(launch_captures["schedule"].path),
                "identity_kind": "canonical_json_sha256",
                "sha256": schedule_sha256,
            },
        },
    }
    power_scheme = _power_scheme()
    if power_scheme.get("available") is not True:
        raise ContractError("preflight_rejected: power scheme no atestiguable")
    environment = {
        "platform": sys.platform,
        "windows_release": platform.release(),
        "windows_version": platform.version(),
        "machine": platform.machine(),
        "processor": _cpu_model(),
        "logical_cpus_host": os.cpu_count(),
        "processor_topology": processor_topology(),
        "affinity_before_confinement": affinity,
        "system_memory": memory,
        "power_scheme": power_scheme,
        "volume": {
            "path": str(resolved_workdir),
            "free_bytes": disk_free,
            **windows_volume_identity(resolved_workdir),
        },
        "native_pool_environment": {key: os.environ.get(key) for key in POOL_ENVIRONMENT_KEYS},
    }
    elapsed = time.monotonic() - started
    if elapsed > PREFLIGHT_DEADLINE_SECONDS:
        raise ContractError("preflight_rejected: preflight excedió 300 s")
    _assert_launch_captures_current(
        launch_captures,
        context="preflight.final_launch_sources",
    )
    workdir_reservation: dict[str, Any] | None = None
    if reserve_workdir:
        created = False
        reservation_id = secrets.token_hex(32)
        owner_marker = resolved_workdir / ".h9r-reservation-owner.json"
        owner_payload = {
            "schema_version": "nikodym.readiness.h9r.workdir-reservation.v1",
            "attempt_id": attempt_id(normalized_unit),
            "reservation_id": reservation_id,
            "workdir_path_sha256": sha256_bytes(
                str(resolved_workdir).replace("\\", "/").casefold().encode("utf-8")
            ),
        }
        try:
            resolved_workdir.mkdir(parents=True, exist_ok=False)
            created = True
            atomic_write_json_exclusive(owner_marker, owner_payload)
            for name in ("scratch", "telemetry"):
                (resolved_workdir / name).mkdir()
            (resolved_workdir / "telemetry" / "control").mkdir()
            for name in (
                "home",
                "tmp",
                "python-cache",
                "xdg-cache",
                "matplotlib",
                "numba",
                "joblib",
            ):
                (resolved_workdir / "scratch" / name).mkdir()
            elapsed = time.monotonic() - started
            if elapsed > PREFLIGHT_DEADLINE_SECONDS:
                raise ContractError("preflight_rejected: reserva excedió 300 s")
            if read_json_object(owner_marker) != owner_payload:
                raise ContractError("owner marker del workdir mutó durante la reserva")
            marker_identity = _source_identity(owner_marker)
            workdir_reservation = {
                "reservation_id": reservation_id,
                "owner_marker": {
                    "path": str(owner_marker.resolve()),
                    "bytes": marker_identity["bytes"],
                    "sha256": marker_identity["sha256"],
                },
                "owner_payload": owner_payload,
                "expected_initial_entries": _workdir_entries(resolved_workdir),
                "checkout_root": str(checkout_root.resolve()),
                "onedrive_root": None if onedrive_root is None else str(onedrive_root.resolve()),
            }
        except Exception:
            if created and owner_marker.is_file() and not _is_reparse_or_symlink(owner_marker):
                with contextlib.suppress(OSError, ContractError):
                    if (
                        _require_plain_directory(
                            resolved_workdir, context="cleanup.workdir reservado"
                        )
                        == resolved_workdir
                        and read_json_object(owner_marker) == owner_payload
                    ):
                        shutil.rmtree(resolved_workdir)
            raise
    _assert_launch_captures_current(
        launch_captures,
        context="preflight.return_launch_sources",
    )
    return PreflightResult(
        unit=normalized_unit,
        attempt_id=attempt_id(normalized_unit),
        authority=validated_authority,
        candidate=candidate,
        fixture=fixture,
        config={
            "path": str(launch_captures["config"].path),
            "config_hash": config_hash,
            "value": normalized_config,
        },
        schedule={
            "path": str(launch_captures["schedule"].path),
            "sha256": schedule_sha256,
            "position": schedule_position,
            "value": schedule_value,
            "campaign_progress": campaign_progress,
        },
        environment=environment,
        requested_limits=requested_limits,
        effective_limits=effective_limits,
        resource_guards={
            "physical_available_bytes": memory["physical_available_bytes"],
            "commit_available_bytes": memory["commit_available_bytes"],
            "allocated_inputs_bundle_bytes": allocated_inputs_bundle,
            "disk_free_bytes": disk_free,
            "disk_floor_bytes": disk_floor,
            "passed": True,
        },
        tooling=tooling,
        source_paths={
            "authority": str(launch_captures["authority"].path),
            "authorization_text": str(launch_captures["authorization_text"].path),
            "trusted_authority_public_key": str(
                launch_captures["trusted_authority_public_key"].path
            ),
            "candidate_manifest": str(launch_captures["candidate_manifest"].path),
            "fixture_manifest": str(launch_captures["fixture_manifest"].path),
            "config": str(launch_captures["config"].path),
            "schedule": str(launch_captures["schedule"].path),
            "prior_evidence": [str(path.resolve()) for path in prior_evidence_paths],
            "capture_versions": {
                name: _launch_capture_version(capture) for name, capture in launch_captures.items()
            },
        },
        workdir_path=str(resolved_workdir),
        workdir_reservation=workdir_reservation,
        started_monotonic_ns=started_monotonic_ns,
        elapsed_seconds=elapsed,
    )


class Handshake:
    """Máquina de estados que prohíbe START antes de límites/READY/autoridad."""

    def __init__(
        self,
        *,
        expected_authority_text_sha256: str,
        expected_affinity_mask: int,
        expected_memory_bytes: int,
        expected_processor_group: int,
    ) -> None:
        self.expected_authority_text_sha256 = validate_sha256(
            expected_authority_text_sha256, context="handshake authority"
        )
        self.events: list[dict[str, Any]] = []
        self.expected_affinity_mask = expected_affinity_mask
        self.expected_memory_bytes = expected_memory_bytes
        self.expected_processor_group = expected_processor_group
        self._state = "created"
        self._ready_ns: int | None = None

    @property
    def state(self) -> str:
        """Devuelve el estado cerrado actual."""
        return self._state

    def _event(self, name: str, **extra: Any) -> None:
        self.events.append({"event": name, "monotonic_ns": time.monotonic_ns(), **extra})

    def boot(self, *, pid: int) -> None:
        """Registra que la raíz existe, todavía sin trabajo pesado."""
        if self._state != "created":
            raise ContractError("BOOT fuera de orden")
        self._state = "booted"
        self._event("boot", pid=pid, heavy_work_started=False)

    def limits_applied(self, effective_limits: Mapping[str, Any]) -> None:
        """Registra límites consultados al kernel, no la solicitud."""
        if self._state != "booted":
            raise ContractError("limits_applied fuera de orden")
        if effective_limits.get("logical_cpu_count") not in {1, 2, 3, 4}:
            raise ContractError("limits_not_applied: CPU efectiva inválida")
        if (
            effective_limits.get("affinity_mask") != self.expected_affinity_mask
            or effective_limits.get("job_memory_commit_limit_bytes") != self.expected_memory_bytes
            or effective_limits.get("group_affinities")
            != [
                {
                    "processor_group": self.expected_processor_group,
                    "affinity_mask": self.expected_affinity_mask,
                }
            ]
            or effective_limits.get("kill_on_job_close") is not True
            or effective_limits.get("affinity_enforced") is not True
            or effective_limits.get("job_memory_enforced") is not True
        ):
            raise ContractError("limits_not_applied: límites efectivos no reconcilian")
        self._state = "limits_applied"
        self._event("limits_applied", effective_limits=dict(effective_limits))

    def ready(self) -> None:
        """Emitir READY sólo tras atestiguar los límites."""
        if self._state != "limits_applied":
            raise ContractError("READY fuera de orden")
        self._state = "ready"
        self._ready_ns = time.monotonic_ns()
        self.events.append(
            {"event": "ready", "monotonic_ns": self._ready_ns, "heavy_work_started": False}
        )

    def start(self, *, authorization_text_sha256: str) -> dict[str, Any]:
        """Crea START sólo tras READY y match exacto de autoridad."""
        if self._state != "ready" or self._ready_ns is None:
            raise ContractError("START antes de READY (error interno del supervisor)")
        observed = validate_sha256(authorization_text_sha256, context="START authority")
        if observed != self.expected_authority_text_sha256:
            raise ContractError("autoridad START no coincide (error interno del supervisor)")
        now_ns = time.monotonic_ns()
        elapsed = (now_ns - self._ready_ns) / 1_000_000_000
        if elapsed > HANDSHAKE_DEADLINE_SECONDS:
            raise ContractError("handshake READY→START excedió 60 s")
        self._state = "started"
        token = {
            "protocol_version": PROTOCOL_VERSION,
            "authorization_text_sha256": observed,
            "ready_monotonic_ns": self._ready_ns,
            "start_monotonic_ns": now_ns,
        }
        self.events.append({"event": "start", "monotonic_ns": now_ns})
        return token


def _read_canonical_control(path: Path, *, context: str) -> dict[str, Any]:
    """Reabre un control regular single-link y exige JSON canónico con LF."""
    safe = _require_safe_regular_file(path, context=context)
    payload = safe.read_bytes()
    try:
        raw: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{context}: JSON inválido") from exc
    value = _require_mapping(raw, context=context)
    if payload != canonical_json_bytes(value) + b"\n":
        raise ContractError(f"{context}: JSON no es canónico exacto")
    observed = _source_identity(safe)
    if (
        observed["safe_regular_file"] is not True
        or observed["bytes"] != len(payload)
        or observed["sha256"] != sha256_bytes(payload)
    ):
        raise ContractError(f"{context}: control cambió durante la reapertura")
    return value


def _wait_json(
    path: Path, *, timeout_seconds: float, process: subprocess.Popen[bytes]
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if os.path.lexists(path):
            return _read_canonical_control(path, context=f"handshake {path.name}")
        if process.poll() is not None:
            raise RuntimeError(f"worker terminó antes de producir {path.name}")
        time.sleep(0.01)
    raise TimeoutError(f"worker no produjo {path.name}")


def _worker_environment(cpu_count: int, *, workdir: Path) -> dict[str, str]:
    allowed_host_keys = (
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "WINDIR",
    )
    environment = {key: os.environ[key] for key in allowed_host_keys if key in os.environ}
    scratch = workdir / "scratch"
    environment.update(
        {
            "HOME": str(scratch / "home"),
            "USERPROFILE": str(scratch / "home"),
            "TMP": str(scratch / "tmp"),
            "TEMP": str(scratch / "tmp"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(scratch / "python-cache"),
            "XDG_CACHE_HOME": str(scratch / "xdg-cache"),
            "MPLCONFIGDIR": str(scratch / "matplotlib"),
            "NUMBA_CACHE_DIR": str(scratch / "numba"),
            "JOBLIB_TEMP_FOLDER": str(scratch / "joblib"),
        }
    )
    for key in POOL_ENVIRONMENT_KEYS:
        environment[key] = str(cpu_count)
    return environment


def _revalidate_preflight(
    preflight: PreflightResult,
    *,
    trusted_authority_public_key_path: Path,
    active_candidate_probe: bool = True,
) -> None:
    """Rehashea autoridad, tooling, candidato, fixture y config inmediatamente antes de START."""
    normalized_unit = validate_attempt_unit(preflight.unit)
    if normalized_unit != preflight.unit or attempt_id(normalized_unit) != preflight.attempt_id:
        raise ContractError("unidad/attempt_id mutó después del preflight")
    source_paths = {
        name: Path(str(preflight.source_paths[name]))
        for name in (
            "authority",
            "authorization_text",
            "trusted_authority_public_key",
            "candidate_manifest",
            "fixture_manifest",
            "config",
            "schedule",
        )
    }
    launch_captures = _capture_launch_sources(source_paths)
    raw_expected_versions = preflight.source_paths.get("capture_versions")
    if not isinstance(raw_expected_versions, dict) or set(raw_expected_versions) != set(
        launch_captures
    ):
        raise ContractError("preflight no conserva versiones exactas de launch sources")
    for name, capture in launch_captures.items():
        if _launch_capture_version(capture) != raw_expected_versions[name]:
            raise ContractError(f"revalidate.launch.{name}: identidad/versión cambió")
    external_trusted_key = Path(os.path.abspath(trusted_authority_public_key_path))
    if external_trusted_key != launch_captures["trusted_authority_public_key"].path:
        raise ContractError("trust anchor externo no coincide con el preflight")
    prior_evidence_paths = [
        Path(str(path)) for path in cast(list[str], preflight.source_paths["prior_evidence"])
    ]
    for index, path in enumerate(prior_evidence_paths):
        _require_safe_regular_file(path, context=f"revalidate.prior_evidence[{index}]")
    document_paths = {
        name: Path(str(path_value))
        for name, path_value in cast(dict[str, str], preflight.tooling["document_paths"]).items()
    }
    live_tooling = tooling_identity(document_paths)
    for key in (
        "protocol_version",
        "files",
        "harness_runtime",
        "manifest_sha256",
        "document_sha256",
    ):
        if live_tooling[key] != preflight.tooling[key]:
            raise ContractError(f"tooling.{key} cambió después del preflight")
    schedule_value = cast(dict[str, Any], launch_captures["schedule"].json_value)
    schedule_sha256, schedule_position = validate_schedule(schedule_value, normalized_unit)
    if (
        schedule_sha256 != preflight.schedule["sha256"]
        or schedule_position != preflight.schedule["position"]
        or schedule_value != preflight.schedule["value"]
    ):
        raise ContractError("schedule cambió después del preflight")
    authority_source = cast(dict[str, Any], launch_captures["authority"].json_value)
    with _captured_trust_anchor(
        launch_captures["trusted_authority_public_key"]
    ) as trusted_key_snapshot:
        rebuilt_authority = validate_authority(
            authority_source,
            normalized_unit,
            document_hashes=cast(dict[str, str], live_tooling["document_sha256"]),
            tooling_sha256=str(live_tooling["manifest_sha256"]),
            schedule_sha256=schedule_sha256,
            schedule_position=schedule_position,
            trusted_authority_public_key_path=trusted_key_snapshot,
        )
        _, trusted_key_sha256 = trusted_authority_key_identity(trusted_key_snapshot)
    if rebuilt_authority != preflight.authority:
        raise ContractError("autoridad firmada cambió/mutó después del preflight")
    expected_authorization = authorization_statement(
        normalized_unit,
        authorization_id=str(rebuilt_authority["authorization_id"]),
        authorization_consumption_path_sha256=str(
            rebuilt_authority["authorization_consumption_path_sha256"]
        ),
        tooling_sha256=str(live_tooling["manifest_sha256"]),
        schedule_sha256=schedule_sha256,
        schedule_position=schedule_position,
        scope=str(rebuilt_authority["scope"]),
    )
    authorization_bytes = launch_captures["authorization_text"].payload
    if authorization_bytes != expected_authorization:
        raise ContractError("texto de autorización no nombra unidad/tooling/schedule exactos")
    if sha256_bytes(authorization_bytes) != preflight.authority["authorization_text_sha256"]:
        raise ContractError("texto de autorización cambió después del preflight")
    if trusted_key_sha256 != preflight.authority["signer_public_key_sha256"]:
        raise ContractError("trust anchor Ed25519 cambió después del preflight")
    candidate_source = cast(dict[str, Any], launch_captures["candidate_manifest"].json_value)
    fixture_source = cast(dict[str, Any], launch_captures["fixture_manifest"].json_value)
    config_source = cast(dict[str, Any], launch_captures["config"].json_value)
    if canonical_json_sha256(candidate_source) != preflight.unit["candidate_manifest_sha256"]:
        raise ContractError("manifiesto candidato cambió después del preflight")
    passive_candidate = validate_candidate_manifest_passive(
        candidate_source,
        expected_sha256=str(preflight.unit["candidate_manifest_sha256"]),
        manifest_root=launch_captures["candidate_manifest"].path.parent,
    )
    _require_distinct_harness_and_candidate_runtimes(
        candidate=passive_candidate, tooling=live_tooling
    )
    if active_candidate_probe:
        if (
            preflight.authority.get("scope") != "calibration-start"
            or CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256 is None
        ):
            raise ContractError("probe activo exige autoridad humana calibration-start")
        _assert_launch_captures_current(
            launch_captures,
            expected_versions=cast(Mapping[str, Any], raw_expected_versions),
            context="revalidate.before_candidate_probe",
        )
        rebuilt_candidate = _validate_candidate_manifest_after_authority(
            candidate_source,
            expected_sha256=str(preflight.unit["candidate_manifest_sha256"]),
            manifest_root=launch_captures["candidate_manifest"].path.parent,
            memory_bytes=int(preflight.requested_limits["job_memory_commit_limit_bytes"]),
            affinity_mask=int(preflight.requested_limits["affinity_mask"]),
        )
    else:
        rebuilt_candidate = passive_candidate
    if rebuilt_candidate != preflight.candidate:
        raise ContractError("instalación aislada del candidato cambió después del preflight")
    if canonical_json_sha256(fixture_source) != preflight.unit["fixture_manifest_sha256"]:
        raise ContractError("manifiesto fixture cambió después del preflight")
    rebuilt_fixture = validate_fixture_manifest(
        fixture_source,
        expected_sha256=str(normalized_unit["fixture_manifest_sha256"]),
        manifest_root=launch_captures["fixture_manifest"].path.parent,
        _verify_geometry_material=False,
        _trusted_geometry_observed=cast(Mapping[str, Any], preflight.fixture["geometry_observed"]),
        _allow_harness_test_declared_geometry=preflight.authority.get("scope")
        == "harness-test-only"
        and not active_candidate_probe,
    )
    if rebuilt_fixture != preflight.fixture:
        raise ContractError("fixture cambió después del preflight")
    if canonical_json_sha256(config_source) != preflight.unit["config_hash"]:
        raise ContractError("config cambió después del preflight")
    rebuilt_config = validate_harness_config(
        config_source,
        config_root=launch_captures["config"].path.parent,
        candidate_root=Path(
            str(cast(dict[str, Any], rebuilt_candidate["runtime"])["installed_tree"]["path"])
        ),
        unit=normalized_unit,
        fixture=rebuilt_fixture,
    )
    if rebuilt_config != preflight.config["value"]:
        raise ContractError("config normalizado cambió después del preflight")
    if canonical_json_sha256(schedule_value) != preflight.schedule["sha256"]:
        raise ContractError("schedule cambió después del preflight")
    from .aggregate import validate_campaign_progress

    with _captured_trust_anchor(
        launch_captures["trusted_authority_public_key"]
    ) as trusted_key_snapshot:
        observed_campaign = validate_campaign_progress(
            schedule=schedule_value,
            current_unit=normalized_unit,
            prior_evidence_paths=prior_evidence_paths,
            trusted_authority_public_key_path=trusted_key_snapshot,
        )
    if observed_campaign != preflight.schedule["campaign_progress"]:
        raise ContractError("evidencia previa de campaña cambió después del preflight")
    for section in ("wheel", "sdist", "lock"):
        entry = cast(dict[str, Any], preflight.candidate[section])
        if (
            Path(str(entry["path"])).stat().st_size != entry["bytes"]
            or sha256_file(Path(str(entry["path"]))) != entry["sha256"]
        ):
            raise ContractError(f"candidate.{section} cambió después del preflight")
    runtime = cast(dict[str, Any], preflight.candidate["runtime"])
    for section in ("python_executable", "environment"):
        entry = cast(dict[str, Any], runtime[section])
        path = Path(str(entry["path"]))
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise ContractError(f"candidate.runtime.{section} cambió después del preflight")
    tree = cast(dict[str, Any], runtime["installed_tree"])
    if canonical_tree_identity(Path(str(tree["path"]))) != {
        key: tree[key] for key in ("files", "logical_bytes", "sha256")
    }:
        raise ContractError("árbol instalado cambió después del preflight")
    for collection_name in (
        "fixture_schema",
        "config",
        "catalog",
    ):
        entry = cast(dict[str, Any], preflight.fixture[collection_name])
        path = Path(str(entry["path"]))
        assigned, reliable, _ = allocated_size(path)
        if (
            not reliable
            or path.stat().st_size != entry["logical_bytes"]
            or assigned != entry["allocated_bytes"]
            or sha256_file(path) != entry["sha256"]
        ):
            raise ContractError(f"fixture.{collection_name} cambió después del preflight")
    fixture_entries = [*cast(list[dict[str, Any]], preflight.fixture["inputs"])]
    if preflight.fixture["bundle"] is not None:
        fixture_entries.append(cast(dict[str, Any], preflight.fixture["bundle"]))
    fixture_entries.extend(
        [
            cast(dict[str, Any], preflight.fixture["generator"])["artifact"],
            cast(dict[str, Any], preflight.fixture["expected"])["golden"],
        ]
    )
    for entry in fixture_entries:
        path = Path(str(entry["path"]))
        assigned, reliable, _ = allocated_size(path)
        if (
            not reliable
            or path.stat().st_size != entry["logical_bytes"]
            or assigned != entry["allocated_bytes"]
            or sha256_file(path) != entry["sha256"]
        ):
            raise ContractError(f"artefacto fixture cambió después del preflight: {path}")
    scripts_root = Path(__file__).resolve().parents[1]
    for entry in cast(list[dict[str, Any]], preflight.tooling["files"]):
        path = scripts_root / str(entry["relative_path"])
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise ContractError(f"tooling cambió después del preflight: {path}")
    for name, path_value in cast(dict[str, str], preflight.tooling["document_paths"]).items():
        if sha256_file(Path(path_value)) != preflight.tooling["document_sha256"][name]:
            raise ContractError(f"documento cambió después del preflight: {name}")
    _assert_launch_captures_current(
        launch_captures,
        expected_versions=cast(Mapping[str, Any], raw_expected_versions),
        context="revalidate.final_launch_sources",
    )


def _adapter_bindings(preflight: PreflightResult) -> dict[str, str]:
    """Liga los descriptores dinámicos sólo a material ya autorizado."""
    return {
        "config_hash": str(preflight.unit["config_hash"]),
        "candidate_manifest_sha256": str(preflight.unit["candidate_manifest_sha256"]),
        "fixture_manifest_sha256": str(preflight.unit["fixture_manifest_sha256"]),
        "tooling_manifest_sha256": str(preflight.tooling["manifest_sha256"]),
    }


def _protected_input_contract(preflight: PreflightResult) -> dict[str, Any]:
    protected: list[dict[str, Any]] = []

    def append(role: str, entry: Mapping[str, Any]) -> None:
        identity = {
            "role": role,
            "relative_name": str(entry["relative_path"]),
            "logical_bytes": int(entry["logical_bytes"]),
            "sha256": str(entry["sha256"]),
        }
        protected.append({"logical_id": canonical_json_sha256(identity), **identity})

    for entry in cast(list[dict[str, Any]], preflight.fixture["inputs"]):
        append("input", entry)
    bundle = preflight.fixture["bundle"]
    if bundle is not None:
        append("bundle", cast(dict[str, Any], bundle))
    append("config", cast(dict[str, Any], preflight.fixture["config"]))
    protected.sort(key=lambda item: str(item["logical_id"]))
    return {
        "protocol_version": CONSUMER_OPEN_PROTOCOL_VERSION,
        "protected": protected,
        "max_open_requests": 1,
    }


def _build_adapter_descriptor(preflight: PreflightResult) -> dict[str, Any]:
    config = cast(dict[str, Any], preflight.config["value"])
    consumer = cast(dict[str, Any], config["consumer"])
    entrypoint = cast(dict[str, Any], consumer["entrypoint"])
    expected = cast(dict[str, Any], preflight.fixture["expected"])
    golden = cast(dict[str, Any], expected["golden"])
    is_ui = preflight.unit["flow_id"] == "F-UI"
    implementation: dict[str, Any] = {
        "kind": "candidate_http_service" if is_ui else "candidate_brokered_script",
        "script": {
            "relative_path": entrypoint["relative_path"],
            "bytes": entrypoint["logical_bytes"],
            "sha256": entrypoint["sha256"],
        },
        "argv_template": list(consumer["arguments"]),
        "isolation_flags": ["-I", "-B", "-S"],
    }
    if is_ui:
        flow_config = cast(dict[str, Any], config["flow_config"])
        implementation["service"] = dict(cast(dict[str, Any], flow_config["h9r_candidate_service"]))
    return {
        "schema_version": ADAPTER_DESCRIPTOR_SCHEMA_VERSION,
        "attempt_id": preflight.attempt_id,
        "unit": dict(preflight.unit),
        "adapter_id": consumer["adapter_id"],
        "flow_id": preflight.unit["flow_id"],
        "flow_step": preflight.unit["flow_step"],
        "boundary_kind": "first_byte" if is_ui else "first_open",
        "bindings": _adapter_bindings(preflight),
        "input_contract": _protected_input_contract(preflight),
        "implementation": implementation,
        "expected": {
            "identities": list(expected["identities"]),
            "counts": dict(cast(dict[str, int], expected["counts"])),
            "golden_sha256": golden["sha256"],
        },
    }


def _logical_file_identity(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(Path(str(entry["path"])).resolve()),
        "logical_bytes": int(entry["logical_bytes"]),
        "sha256": str(entry["sha256"]),
    }


def _materialize_attempt_harness_snapshot(
    preflight: PreflightResult, *, scratch_root: Path, control_root: Path
) -> dict[str, Any]:
    snapshot_root = scratch_root / "harness-runtime-snapshot"
    manifest_path = control_root / "harness-runtime-snapshot.json"
    try:
        snapshot = materialize_harness_source_snapshot(
            destination_root=snapshot_root,
            manifest_path=manifest_path,
            source_tooling_manifest_sha256=str(preflight.tooling["manifest_sha256"]),
            include_product_runtime=True,
        )
    except RuntimeSnapshotError as exc:
        raise ContractError(f"snapshot del runtime del arnés no es calificable: {exc}") from exc
    value = cast(dict[str, Any], snapshot["value"])
    snapshot_files = [
        {
            "relative_path": str(item["relative_path"])[len("scripts/") :],
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in cast(list[dict[str, Any]], value["files"])
        if str(item["relative_path"]).startswith("scripts/")
    ]
    if snapshot_files != cast(list[dict[str, Any]], preflight.tooling["files"]):
        raise ContractError("snapshot no reconcilia el inventario de fuentes H9R firmado")
    live_roots = {
        str(item["name"]): {name: item[name] for name in ("files", "logical_bytes", "tree_sha256")}
        for item in cast(
            list[dict[str, Any]],
            cast(dict[str, Any], preflight.tooling["harness_runtime"])["import_roots"],
        )
    }
    snapshot_roots = {
        str(item["name"]): {name: item[name] for name in ("files", "logical_bytes", "tree_sha256")}
        for item in cast(list[dict[str, Any]], value["import_roots"])
    }
    if snapshot_roots != live_roots:
        raise ContractError("snapshot no reconcilia import roots firmados del arnés")
    reopened = validate_harness_source_snapshot(
        manifest_path=Path(str(snapshot["path"])),
        expected_manifest_sha256=str(snapshot["sha256"]),
        expected_source_tooling_manifest_sha256=str(preflight.tooling["manifest_sha256"]),
    )
    return reopened


def _reserve_candidate_broker_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        port = int(cast(tuple[str, int], probe.getsockname())[1])
    finally:
        probe.close()
    return port


def _build_candidate_request(
    preflight: PreflightResult,
    *,
    descriptor: Mapping[str, Any],
    descriptor_identity: Mapping[str, Any],
    snapshot_identity: Mapping[str, Any],
    paths: Mapping[str, Path],
    workdir: Path,
) -> dict[str, Any]:
    runtime = cast(dict[str, Any], preflight.candidate["runtime"])
    candidate_python = cast(dict[str, Any], runtime["python_executable"])
    installed_tree = cast(dict[str, Any], runtime["installed_tree"])
    implementation = cast(dict[str, Any], descriptor["implementation"])
    input_contract = cast(dict[str, Any], descriptor["input_contract"])
    launch_paths = {
        "staging": str(paths["staging"]),
        "candidate_outputs": str(paths["candidate_outputs"]),
        "adapter_result": str(paths["adapter_result"]),
        "candidate_stdout": str(paths["candidate_stdout"]),
        "candidate_stderr": str(paths["candidate_stderr"]),
        "candidate_controller_stdout": str(paths["candidate_controller_stdout"]),
        "candidate_controller_stderr": str(paths["candidate_controller_stderr"]),
        "candidate_start": str(paths["candidate_start"]),
        "candidate_result": str(paths["candidate_result"]),
    }
    launch_material = {
        "schema_version": LAUNCH_BINDING_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "attempt_id": preflight.attempt_id,
        "unit": dict(preflight.unit),
        "adapter_descriptor_sha256": str(descriptor_identity["sha256"]),
        "harness_runtime_snapshot_sha256": str(snapshot_identity["sha256"]),
        "candidate_manifest_sha256": str(preflight.unit["candidate_manifest_sha256"]),
        "fixture_manifest_sha256": str(preflight.unit["fixture_manifest_sha256"]),
        "config_hash": str(preflight.unit["config_hash"]),
        "tooling_manifest_sha256": str(preflight.tooling["manifest_sha256"]),
        "workdir_sha256": _path_digest(workdir),
        "paths": launch_paths,
    }
    is_ui = preflight.unit["flow_id"] == "F-UI"
    broker: dict[str, Any] | None = None
    service: dict[str, Any] | None = None
    if is_ui:
        service = {
            name: implementation["service"][name]
            for name in ("host", "port", "ready_timeout_seconds")
        }
    else:
        nonce = secrets.token_hex(32)
        protected = cast(list[dict[str, Any]], input_contract["protected"])
        broker = {
            "protocol_version": CONSUMER_OPEN_PROTOCOL_VERSION,
            "host": "127.0.0.1",
            "port": _reserve_candidate_broker_port(),
            "nonce": nonce,
            "nonce_commitment_sha256": sha256_bytes(bytes.fromhex(nonce)),
            "request_id": canonical_json_sha256(
                {
                    "attempt_id": preflight.attempt_id,
                    "operation": "OPEN",
                    "protected": protected,
                }
            ),
        }
    request = {
        "schema_version": CANDIDATE_REQUEST_SCHEMA_VERSION,
        "attempt_id": preflight.attempt_id,
        "mode": "http-service" if is_ui else "batch",
        "bindings": {
            "launch_binding_sha256": canonical_json_sha256(launch_material),
            "harness_runtime_snapshot_sha256": str(snapshot_identity["sha256"]),
        },
        "launch_material": launch_material,
        "script": {
            "relative_path": cast(dict[str, Any], implementation["script"])["relative_path"],
            "logical_bytes": cast(dict[str, Any], implementation["script"])["bytes"],
            "sha256": cast(dict[str, Any], implementation["script"])["sha256"],
        },
        "runtime": {
            "candidate_root": str(Path(str(installed_tree["path"]))),
            "candidate_tree_sha256": str(installed_tree["sha256"]),
            "python_executable": {
                "path": str(Path(str(candidate_python["path"]))),
                "logical_bytes": int(candidate_python["bytes"]),
                "sha256": str(candidate_python["sha256"]),
            },
            "isolation_flags": ["-I", "-B", "-S"],
            "job_memory_commit_limit_bytes": int(
                preflight.requested_limits["job_memory_commit_limit_bytes"]
            ),
            "affinity_mask": int(preflight.requested_limits["affinity_mask"]),
        },
        "input_contract": input_contract,
        "broker": broker,
        "paths": {
            "staging": str(paths["staging"]),
            "candidate_outputs": str(paths["candidate_outputs"]),
            "adapter_result": str(paths["adapter_result"]),
            "brokered_inputs_json": str(paths["brokered_inputs_json"]),
            "pycache": str(paths["candidate_child_pycache"]),
            "stdout": str(paths["candidate_stdout"]),
            "stderr": str(paths["candidate_stderr"]),
            "controller_stdout": str(paths["candidate_controller_stdout"]),
            "controller_stderr": str(paths["candidate_controller_stderr"]),
            "service_ready": str(paths["service_ready"]),
            "candidate_start": str(paths["candidate_start"]),
            "candidate_result": str(paths["candidate_result"]),
        },
        "argv_template": list(cast(list[str], implementation["argv_template"])),
        "service": service,
        "workload_deadline_seconds": flow_spec(
            str(preflight.unit["flow_id"]), str(preflight.unit["flow_step"])
        ).workload_deadline_seconds,
    }
    return validate_candidate_launch_request(request)


def _build_adapter_request(
    preflight: PreflightResult,
    *,
    descriptor_identity: Mapping[str, Any],
    paths: Mapping[str, Path],
    candidate_launch: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = cast(dict[str, Any], preflight.candidate["runtime"])
    python_executable = cast(dict[str, Any], runtime["python_executable"])
    installed_tree = cast(dict[str, Any], runtime["installed_tree"])
    config = cast(dict[str, Any], preflight.config["value"])
    consumer = cast(dict[str, Any], config["consumer"])
    expected = cast(dict[str, Any], preflight.fixture["expected"])
    golden = cast(dict[str, Any], expected["golden"])
    bundle = preflight.fixture["bundle"]
    client = cast(dict[str, Any] | None, config["external_client"])
    input_entries = cast(list[dict[str, Any]], preflight.fixture["inputs"])
    ui_ingress: dict[str, Any] | None = None
    if client is not None:
        if len(input_entries) != 1:
            raise ContractError("F-UI exige un único body input firmado")
        body = _logical_file_identity(input_entries[0])
        request_id = canonical_json_sha256(
            {
                "attempt_id": preflight.attempt_id,
                "method": "POST",
                "host": "127.0.0.1"
                if client["loopback_host"] == "localhost"
                else client["loopback_host"],
                "port": client["port"],
                "path": client["path"],
                "body_sha256": body["sha256"],
                "body_bytes": body["logical_bytes"],
            }
        )
        ui_ingress = {
            "loopback_host": client["loopback_host"],
            "port": client["port"],
            "path": client["path"],
            "timeout_seconds": client["timeout_seconds"],
            "expected_status": client["expected_status"],
            "request_id": request_id,
            "body": body,
            "service_descriptor_sha256": str(descriptor_identity["sha256"]),
            "endpoint_sha256": canonical_json_sha256(
                {
                    "method": "POST",
                    "loopback_host": "127.0.0.1"
                    if client["loopback_host"] == "localhost"
                    else client["loopback_host"],
                    "port": client["port"],
                    "path": client["path"],
                    "expected_status": client["expected_status"],
                    "request_id": request_id,
                    "body": body,
                }
            ),
        }
    return {
        "schema_version": ADAPTER_REQUEST_SCHEMA_VERSION,
        "attempt_id": preflight.attempt_id,
        "flow_id": preflight.unit["flow_id"],
        "flow_step": preflight.unit["flow_step"],
        "adapter_id": consumer["adapter_id"],
        "bindings": _adapter_bindings(preflight),
        "descriptor": {
            "path": str(Path(str(descriptor_identity["path"])).resolve()),
            "logical_bytes": int(descriptor_identity["logical_bytes"]),
            "sha256": str(descriptor_identity["sha256"]),
        },
        "runtime": {
            "candidate_root": str(Path(str(installed_tree["path"])).resolve()),
            "candidate_tree_sha256": installed_tree["sha256"],
            "python_executable": {
                "path": str(Path(str(python_executable["path"])).resolve()),
                "logical_bytes": int(python_executable["bytes"]),
                "sha256": python_executable["sha256"],
            },
            "isolation_flags": ["-I", "-B", "-S"],
            "job_memory_commit_limit_bytes": int(
                preflight.requested_limits["job_memory_commit_limit_bytes"]
            ),
            "affinity_mask": int(preflight.requested_limits["affinity_mask"]),
        },
        "paths": {
            "fixture_root": str(Path(str(preflight.fixture["manifest_root"])).resolve()),
            "inputs_root": str(Path(str(preflight.fixture["inputs_root"])).resolve()),
            "inputs": [
                _logical_file_identity(item)
                for item in cast(list[dict[str, Any]], preflight.fixture["inputs"])
            ],
            "bundle_root": str(Path(str(preflight.fixture["bundle_root"])).resolve()),
            "bundle": None
            if bundle is None
            else _logical_file_identity(cast(dict[str, Any], bundle)),
            "config": _logical_file_identity(cast(dict[str, Any], preflight.fixture["config"])),
            "staging": str(paths["staging"].resolve()),
            "candidate_outputs": str(paths["candidate_outputs"].resolve()),
            "adapter_result": str(paths["adapter_result"].resolve()),
            "outputs": str(paths["outputs"].resolve()),
            "boundary": str(paths["boundary"].resolve()),
            "filesystem_events": str(paths["filesystem_events"].resolve()),
            "native_pools": str(paths["native_pools"].resolve()),
            "audit": str(paths["adapter_audit"].resolve()),
            "ui_first_byte": str(paths["ui_first_byte"].resolve()),
        },
        "ui_ingress": ui_ingress,
        "expected": {
            "identities": list(expected["identities"]),
            "counts": dict(cast(dict[str, int], expected["counts"])),
            "golden_observed_sha256": golden["sha256"],
        },
        "counter_adapter": None,
        "candidate_launch": dict(candidate_launch),
    }


def _build_ui_client_request(
    preflight: PreflightResult, *, first_byte_path: Path
) -> dict[str, Any] | None:
    config = cast(dict[str, Any], preflight.config["value"])
    raw_client = config["external_client"]
    if raw_client is None:
        return None
    client = cast(dict[str, Any], raw_client)
    inputs = cast(list[dict[str, Any]], preflight.fixture["inputs"])
    if len(inputs) != 1:
        raise ContractError("F-UI exige un único body input firmado")
    body = _logical_file_identity(inputs[0])
    normalized_host = (
        "127.0.0.1" if client["loopback_host"] == "localhost" else client["loopback_host"]
    )
    request_id = canonical_json_sha256(
        {
            "attempt_id": preflight.attempt_id,
            "method": "POST",
            "host": normalized_host,
            "port": client["port"],
            "path": client["path"],
            "body_sha256": body["sha256"],
            "body_bytes": body["logical_bytes"],
        }
    )
    return {
        "schema_version": UI_CLIENT_REQUEST_SCHEMA_VERSION,
        "attempt_id": preflight.attempt_id,
        "method": client["method"],
        "loopback_host": client["loopback_host"],
        "port": client["port"],
        "path": client["path"],
        "timeout_seconds": client["timeout_seconds"],
        "expected_status": client["expected_status"],
        "body": body,
        "request_id": request_id,
        "first_byte_path": str(first_byte_path.resolve()),
    }


def _runtime_descriptor_identity(publication: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(Path(str(publication["path"])).resolve()),
        "bytes": int(publication["logical_bytes"]),
        "sha256": str(publication["sha256"]),
    }


def _verify_runtime_descriptors(descriptors: Mapping[str, Any]) -> None:
    names = (
        "adapter_descriptor",
        "adapter_request",
        "candidate_request",
        "harness_runtime_snapshot",
        "ui_client_request",
    )
    if set(descriptors) != set(names):
        raise ContractError("censo de descriptores runtime no es exacto")
    for name in names:
        raw = descriptors[name]
        if raw is None:
            if name != "ui_client_request":
                raise ContractError(f"descriptor runtime obligatorio ausente: {name}")
            continue
        entry = _require_mapping(raw, context=f"tooling.runtime_descriptors.{name}")
        if set(entry) != {"path", "bytes", "sha256"}:
            raise ContractError(f"identidad runtime no es exacta: {name}")
        path = Path(str(entry["path"]))
        source = _source_identity(path)
        if (
            source["safe_regular_file"] is not True
            or source["bytes"] != entry["bytes"]
            or source["sha256"] != entry["sha256"]
        ):
            raise ContractError(f"descriptor runtime cambió: {name}")
        value = read_json_object(path)
        if path.read_bytes() != canonical_json_bytes(value) + b"\n":
            raise ContractError(f"descriptor runtime no usa JSON canónico: {name}")


def _closed_adapter_command(
    raw_launch: Mapping[str, Any], *, expected_attempt_id: str
) -> list[str]:
    """Reconstruye el único comando worker permitido; nunca consume argv declarado."""
    launch = dict(raw_launch)
    if set(launch) != {
        "python_executable",
        "driver",
        "adapter_request",
        "adapter_request_payload_sha256",
        "capability_commitment_sha256",
        "authorization_gate_path",
        "trusted_authority_public_key_path",
        "harness_runtime_snapshot",
    }:
        raise ContractError("adapter_launch no tiene campos exactos")

    def verify_identity(raw: Any, *, context: str) -> dict[str, Any]:
        identity = _require_mapping(raw, context=context)
        if set(identity) != {"path", "bytes", "sha256"}:
            raise ContractError(f"{context}: identidad no tiene campos exactos")
        expected_bytes = identity["bytes"]
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            raise ContractError(f"{context}.bytes inválido")
        expected_sha256 = validate_sha256(identity["sha256"], context=f"{context}.sha256")
        source = _source_identity(Path(str(identity["path"])))
        if (
            source["safe_regular_file"] is not True
            or source["bytes"] != expected_bytes
            or source["sha256"] != expected_sha256
        ):
            raise ContractError(f"{context}: archivo cambió o no es regular seguro")
        return {
            "path": source["path"],
            "bytes": expected_bytes,
            "sha256": expected_sha256,
        }

    python_identity = verify_identity(
        launch["python_executable"], context="adapter_launch.python_executable"
    )
    driver_identity = verify_identity(launch["driver"], context="adapter_launch.driver")
    request_identity = verify_identity(
        launch["adapter_request"], context="adapter_launch.adapter_request"
    )
    adapter_request_path = Path(str(request_identity["path"]))
    adapter_request = read_json_object(adapter_request_path)
    if adapter_request_path.read_bytes() != canonical_json_bytes(adapter_request) + b"\n":
        raise ContractError("adapter request del launch no usa JSON canónico")
    payload_sha256 = validate_sha256(
        launch["adapter_request_payload_sha256"],
        context="adapter_launch.adapter_request_payload_sha256",
    )
    if canonical_json_sha256(adapter_request) != payload_sha256:
        raise ContractError("adapter request del launch no reconcilia su payload")
    if adapter_request.get("attempt_id") != expected_attempt_id:
        raise ContractError("adapter request del launch no liga attempt_id")
    candidate_launch = _require_mapping(
        adapter_request.get("candidate_launch"), context="adapter request.candidate_launch"
    )
    if candidate_launch.get("python_executable") != {
        "path": python_identity["path"],
        "logical_bytes": python_identity["bytes"],
        "sha256": python_identity["sha256"],
    }:
        raise ContractError("adapter launch no usa el Python del controller firmado")
    snapshot_identity = verify_identity(
        launch["harness_runtime_snapshot"],
        context="adapter_launch.harness_runtime_snapshot",
    )
    bindings = _require_mapping(adapter_request.get("bindings"), context="adapter request.bindings")
    snapshot = validate_harness_source_snapshot(
        manifest_path=Path(str(snapshot_identity["path"])),
        expected_manifest_sha256=str(snapshot_identity["sha256"]),
        expected_source_tooling_manifest_sha256=str(bindings["tooling_manifest_sha256"]),
    )
    expected_driver = (
        Path(str(cast(dict[str, Any], snapshot["value"])["root"]))
        / "scripts"
        / "measure_readiness_h9r.py"
    )
    if Path(str(driver_identity["path"])) != expected_driver:
        raise ContractError("adapter_launch.driver no pertenece al snapshot atestiguado")
    capability_commitment = validate_sha256(
        launch["capability_commitment_sha256"],
        context="adapter_launch.capability_commitment_sha256",
    )
    gate_path = Path(str(launch["authorization_gate_path"])).resolve()
    trusted_key_path = Path(str(launch["trusted_authority_public_key_path"])).resolve()
    request_workdir = adapter_request_path.resolve().parents[2]
    if not _path_is_within(gate_path, request_workdir):
        raise ContractError("adapter launch gate cae fuera del workdir")
    return [
        str(python_identity["path"]),
        "-I",
        "-B",
        "-S",
        "-X",
        f"pycache_prefix={request_workdir / 'scratch' / 'python-cache' / 'adapter'}",
        str(expected_driver),
        "_adapter",
        str(adapter_request_path),
        payload_sha256,
        capability_commitment,
        str(Path(str(launch["authorization_gate_path"])).resolve()),
        str(trusted_key_path),
    ]


def _build_ui_client_command(
    preflight: PreflightResult,
    *,
    driver_path: Path,
    request_path: Path,
    request_sha256: str,
    capability_commitment_sha256: str,
    authorization_gate_path: Path,
    trusted_authority_public_key_path: Path,
) -> list[str]:
    runtime = cast(dict[str, Any], preflight.tooling["harness_runtime"])
    executable = str(cast(dict[str, Any], runtime["python_executable"])["path"])
    return [
        executable,
        "-I",
        "-B",
        "-S",
        "-X",
        "pycache_prefix="
        f"{request_path.resolve().parents[2] / 'scratch' / 'python-cache' / 'ui-client'}",
        str(driver_path.resolve()),
        "_ui_client",
        str(request_path.resolve()),
        validate_sha256(request_sha256, context="ui_client_request_sha256"),
        validate_sha256(
            capability_commitment_sha256,
            context="ui_client.capability_commitment_sha256",
        ),
        str(authorization_gate_path.resolve()),
        str(trusted_authority_public_key_path.resolve()),
    ]


def _launch_external_client_assigned_suspended(
    *,
    job: WindowsExternalJob,
    command: Sequence[str],
    workdir: Path,
    environment: Mapping[str, str],
    stdout_handle: Any,
    stderr_handle: Any,
) -> tuple[subprocess.Popen[bytes], dict[str, Any], dict[str, Any]]:
    """Lanza y censa la raíz UI mientras continúa suspendida; el caller decide reanudar."""
    process = subprocess.Popen(
        list(command),
        cwd=workdir,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=stdout_handle,
        stderr=stderr_handle,
        close_fds=True,
        creationflags=0x00000004,
    )
    try:
        job.assign(process.pid)
        accounting = job.accounting()
        census = job.census()
    except BaseException:
        with contextlib.suppress(Exception):
            if process.pid in job.process_ids():
                job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
            else:
                process.kill()
        with contextlib.suppress(Exception):
            process.wait(timeout=10)
        raise
    return process, accounting, census


def _quarantine_final_manifest(output_root: Path, scratch_root: Path) -> dict[str, Any] | None:
    if not os.path.lexists(output_root):
        return None
    safe_output_root = _require_plain_directory(output_root, context="quarantine.output_root")
    safe_scratch_root = _require_plain_directory(scratch_root, context="quarantine.scratch_root")
    manifest_path = safe_output_root / "manifest.json"
    if not os.path.lexists(manifest_path):
        return None
    manifest = _require_safe_regular_file(manifest_path, context="quarantine.final_manifest")
    if manifest.parent != safe_output_root:
        raise ContractError("manifiesto final no pertenece al output_root plano")
    quarantine = safe_scratch_root / "invalid-final-manifest.json"
    if os.path.lexists(quarantine):
        raise ContractError("quarantine de manifiesto ya existe")
    os.replace(manifest, quarantine)
    quarantined = _require_safe_regular_file(quarantine, context="quarantine.manifest_publicado")
    return {
        "original_path": str(manifest),
        "quarantine_path": str(quarantined),
        "sha256": sha256_file(quarantined),
    }


def _verify_quarantined_manifest(metadata: Mapping[str, Any]) -> None:
    if set(metadata) != {"original_path", "quarantine_path", "sha256"}:
        raise ContractError("metadata de quarantine no es exacta")
    original = Path(str(metadata["original_path"]))
    quarantine = _require_safe_regular_file(
        Path(str(metadata["quarantine_path"])), context="quarantine.manifest"
    )
    if os.path.lexists(original):
        raise ContractError("quarantine conserva manifiesto en la ruta final")
    if sha256_file(quarantine) != validate_sha256(metadata["sha256"], context="quarantine.sha256"):
        raise ContractError("quarantine no conserva bytes/hash exactos")


def _flush_fsync(handle: Any) -> None:
    """Fuerza bytes visibles antes de conservar metadata de un stream hijo."""
    if handle.closed:
        return
    handle.flush()
    os.fsync(handle.fileno())


def _validate_authorization_consumption_path(
    path: Path, *, authority: Mapping[str, Any], workdir: Path
) -> Path:
    if not path.is_absolute():
        raise ContractError("ruta de consumo de autorización debe ser absoluta")
    lexical = Path(os.path.abspath(path))
    for candidate in (lexical, *lexical.parents):
        if os.path.lexists(candidate) and _is_reparse_or_symlink(candidate):
            raise ContractError(f"ruta de consumo atraviesa symlink/reparse point: {candidate}")
    expected_digest = validate_sha256(
        authority.get("authorization_consumption_path_sha256"),
        context="authority.authorization_consumption_path_sha256",
    )
    if authorization_consumption_path_digest(lexical) != expected_digest:
        raise ContractError("ruta de consumo no coincide con binding firmado")
    checkout_root = Path(__file__).resolve().parents[2]
    if _path_is_within(lexical, checkout_root) or _path_is_within(lexical, workdir):
        raise ContractError("receipt one-shot debe quedar fuera de checkout/workdir/output")
    onedrive_raw = os.environ.get("ONEDRIVE")
    if onedrive_raw and _path_is_within(lexical, Path(onedrive_raw)):
        raise ContractError("receipt one-shot debe quedar fuera de OneDrive")
    parent = lexical.parent
    _require_plain_directory(parent, context="authorization_consumption.parent")
    if os.path.lexists(lexical):
        raise ContractError("autorización ya reservada/consumida; replay rechazado")
    return lexical


def _reserve_authorization_consumption(
    *, preflight: PreflightResult, path: Path, workdir: Path
) -> dict[str, Any]:
    receipt_path = _validate_authorization_consumption_path(
        path, authority=preflight.authority, workdir=workdir
    )
    reserved = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": str(preflight.authority["authorization_id"]),
        "attempt_id": preflight.attempt_id,
        "authority_sha256": canonical_json_sha256(preflight.authority),
        "state": "reserved",
        "consumed_at_utc": None,
    }
    atomic_write_json_exclusive(receipt_path, reserved)
    if read_json_object(receipt_path) != reserved:
        raise ContractError("reserva one-shot no reconcilia tras publicación")
    return {"path": receipt_path, "reserved": reserved}


def _replace_json_write_through(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(dict(value)) + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if sys.platform == "win32":
            kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
            kernel32.MoveFileExW.restype = ctypes.c_bool
            if not kernel32.MoveFileExW(str(temporary), str(path), 0x1 | 0x8):
                raise OSError(ctypes.get_last_error(), "MoveFileExW receipt falló")
        else:  # pragma: no cover - fallback unitario; H9R calificable exige Windows.
            os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _consume_authorization(
    reservation: Mapping[str, Any],
    *,
    preflight: PreflightResult,
    emergency_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt_path = Path(str(reservation["path"]))
    reserved = _require_mapping(reservation.get("reserved"), context="consumption.reserved")
    _require_safe_regular_file(receipt_path, context="authorization_consumption.reserved")
    if read_json_object(receipt_path) != reserved:
        raise ContractError("reserva one-shot cambió antes de START")
    consumed_at_utc = datetime.now(UTC).isoformat()
    receipt_payload = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": str(preflight.authority["authorization_id"]),
        "attempt_id": preflight.attempt_id,
        "authority_sha256": canonical_json_sha256(preflight.authority),
        "state": "consumed",
        "consumed_at_utc": consumed_at_utc,
    }
    receipt_bytes = canonical_json_bytes(receipt_payload) + b"\n"
    consumption = {
        "authorization_id": str(preflight.authority["authorization_id"]),
        "authorization_consumption_path_sha256": str(
            preflight.authority["authorization_consumption_path_sha256"]
        ),
        "state": "consumed",
        "consumed_at_utc": consumed_at_utc,
        "attempt_id": preflight.attempt_id,
        "authority_sha256": canonical_json_sha256(preflight.authority),
        "receipt": {
            "path": str(receipt_path.resolve()),
            "bytes": len(receipt_bytes),
            "sha256": sha256_bytes(receipt_bytes),
        },
    }
    # Write-ahead causal: if the durable replace succeeds but a later read/stat fails, the
    # terminal path can reconcile the exact consumed bytes instead of reporting "reserved".
    if emergency_state is not None:
        emergency_state["authorization_consumption_expected"] = copy.deepcopy(consumption)
        emergency_state["authorization_consumption_write_attempted"] = True
    _replace_json_write_through(receipt_path, receipt_payload)
    if emergency_state is not None:
        emergency_state["authorization_consumption_snapshot"] = copy.deepcopy(consumption)
    if read_json_object(receipt_path) != receipt_payload:
        raise ContractError("receipt one-shot no reconcilia tras consumo")
    validate_authorization_consumption(
        consumption,
        authority=preflight.authority,
        expected_attempt_id=preflight.attempt_id,
        verify_receipt=True,
    )
    return consumption


def _jsonl_sidecar_metadata(path: Path, *, name: str) -> dict[str, Any]:
    return jsonl_sidecar_metadata(path, name=name)


def _validate_ui_first_byte_events(
    events: Sequence[Mapping[str, Any]], *, preflight: PreflightResult
) -> None:
    if preflight.unit["flow_id"] != "F-UI":
        if events:
            raise ContractError("ui_first_byte no puede tener eventos fuera de F-UI")
        return
    if len(events) > 1:
        raise ContractError("ui_first_byte contiene más de un evento")
    if not events:
        return
    event = events[0]
    if set(event) != {
        "schema_version",
        "attempt_id",
        "event",
        "monotonic_ns",
        "request_id",
    }:
        raise ContractError("ui_first_byte no tiene campos exactos")
    monotonic_ns = event["monotonic_ns"]
    if (
        event["schema_version"] != UI_FIRST_BYTE_SCHEMA_VERSION
        or event["attempt_id"] != preflight.attempt_id
        or event["event"] != "first_byte"
        or isinstance(monotonic_ns, bool)
        or not isinstance(monotonic_ns, int)
        or monotonic_ns < 0
        or not isinstance(event["request_id"], str)
        or not event["request_id"]
    ):
        raise ContractError("ui_first_byte no reconcilia con el intento")


def _classify_windows_oom_exit(
    unsigned_returncode: Any,
    *,
    job_memory_limit_violated: bool,
    system_oom_evidence: bool,
) -> tuple[str, str] | None:
    if unsigned_returncode not in {0xC0000017, 0xC000012D}:
        return None
    if job_memory_limit_violated:
        return "job_memory_limit", "notificación kernel del límite de memoria Job"
    if system_oom_evidence:
        return "host_oom", "evento kernel/sistema acredita agotamiento de memoria host"
    return (
        "evidence_incomplete",
        "código Windows OOM sin evidencia kernel/sistema causal; host_oom no acreditado",
    )


def _system_oom_evidence_from_samples(
    records: Sequence[Mapping[str, Any]],
    *,
    termination_monotonic_ns: int | None,
    job_memory_limit_violated: bool,
) -> bool:
    """Deriva OOM host sólo de una muestra crítica causal y ausencia de notificación Job."""
    if job_memory_limit_violated or termination_monotonic_ns is None or not records:
        return False
    last = records[-1]
    sample_ns = last.get("monotonic_ns")
    system = last.get("system_memory")
    if (
        isinstance(sample_ns, bool)
        or not isinstance(sample_ns, int)
        or not isinstance(system, Mapping)
        or sample_ns > termination_monotonic_ns
        or termination_monotonic_ns - sample_ns > 2_000_000_000
    ):
        return False
    physical: Any = system.get("physical_available_bytes")
    commit: Any = system.get("commit_available_bytes")
    load: Any = system.get("memory_load_percent")
    if any(
        isinstance(value, bool) or not isinstance(value, int) for value in (physical, commit, load)
    ):
        return False
    return bool(
        load >= 99
        and (physical < RUN_MIN_AVAILABLE_PHYSICAL_BYTES or commit < RUN_MIN_COMMIT_HEADROOM_BYTES)
    )


def _classify_worker_error_from_runtime(
    worker_result: Mapping[str, Any],
    *,
    memory_violation: Mapping[str, Any],
    resource_records: Sequence[Mapping[str, Any]],
    termination_monotonic_ns: int | None,
) -> tuple[str, str] | None:
    """Ruta real del supervisor: el NTSTATUS nunca se autoatestigua como host_oom."""
    violated = bool(memory_violation.get("job_memory_limit_violated"))
    return _classify_windows_oom_exit(
        worker_result.get("consumer_returncode_unsigned"),
        job_memory_limit_violated=violated,
        system_oom_evidence=_system_oom_evidence_from_samples(
            resource_records,
            termination_monotonic_ns=termination_monotonic_ns,
            job_memory_limit_violated=violated,
        ),
    )


def _path_digest(path: Path) -> str:
    return sha256_bytes(str(path.resolve()).replace("\\", "/").casefold().encode("utf-8"))


def _request_paths_within_workdir(role: str, payload: Mapping[str, Any], workdir: Path) -> bool:
    raw_paths = payload.get("paths")
    paths = raw_paths if isinstance(raw_paths, Mapping) else {}
    if role == "worker":
        values = list(paths.values())
    elif role == "adapter":
        values = [
            paths.get(name)
            for name in (
                "staging",
                "candidate_outputs",
                "adapter_result",
                "outputs",
                "boundary",
                "filesystem_events",
                "native_pools",
                "audit",
                "ui_first_byte",
            )
        ]
    elif role == "candidate":
        values = list(paths.values())
    elif role == "ui-client":
        values = [payload.get("first_byte_path")]
    else:
        return False
    return bool(values) and all(
        isinstance(value, str) and _path_is_within(Path(value), workdir) for value in values
    )


def _build_internal_authorization_gate(
    *,
    preflight: PreflightResult,
    workdir: Path,
    worker_request: Mapping[str, Any],
    adapter_request: Mapping[str, Any],
    candidate_request: Mapping[str, Any],
    ui_client_request: Mapping[str, Any] | None,
    capability_commitment_sha256: Mapping[str, str | None],
    internal_authorization_precommit: Mapping[str, Any],
    supervisor_instance_nonce: str,
    authorization_consumption: Mapping[str, Any],
    start_path: Path,
) -> dict[str, Any]:
    source_paths = {
        name: Path(str(preflight.source_paths[name]))
        for name in (
            "authority",
            "authorization_text",
            "trusted_authority_public_key",
            "schedule",
        )
    }
    start = _reopen_start_identity(preflight, start_path)
    scripts_root = Path(__file__).resolve().parents[1]
    worker_core = dict(worker_request)
    worker_core.pop("authorization_gate", None)
    return {
        "schema_version": INTERNAL_AUTHORIZATION_GATE_SCHEMA_VERSION,
        "attempt_id": preflight.attempt_id,
        "unit": preflight.unit,
        "authority": preflight.authority,
        "bindings": {
            "workdir_path": str(workdir.resolve()),
            "workdir_sha256": _path_digest(workdir),
            "worker_request_core_sha256": canonical_json_sha256(worker_core),
            "adapter_request_sha256": canonical_json_sha256(adapter_request),
            "candidate_request_sha256": canonical_json_sha256(candidate_request),
            "ui_client_request_sha256": None
            if ui_client_request is None
            else canonical_json_sha256(ui_client_request),
            "worker_capability_commitment_sha256": capability_commitment_sha256["worker"],
            "adapter_capability_commitment_sha256": capability_commitment_sha256["adapter"],
            "candidate_capability_commitment_sha256": capability_commitment_sha256["candidate"],
            "ui_client_capability_commitment_sha256": capability_commitment_sha256["ui-client"],
        },
        "sources": {name: _source_identity(path) for name, path in source_paths.items()},
        "tooling": {
            "protocol_version": preflight.tooling["protocol_version"],
            "harness_runtime": preflight.tooling["harness_runtime"],
            "files": [
                {
                    **dict(item),
                    "path": str((scripts_root / str(item["relative_path"])).resolve()),
                }
                for item in cast(list[dict[str, Any]], preflight.tooling["files"])
            ],
            "manifest_sha256": preflight.tooling["manifest_sha256"],
            "document_sha256": preflight.tooling["document_sha256"],
            "document_paths": preflight.tooling["document_paths"],
        },
        "internal_authorization_precommit": dict(internal_authorization_precommit),
        "supervisor_instance_nonce": supervisor_instance_nonce,
        "authorization_consumption": dict(authorization_consumption),
        "start": start,
    }


def consume_internal_authorization_gate(
    *,
    gate_path: Path,
    role: str,
    payload: Mapping[str, Any],
    capability_commitment_sha256: str,
    trusted_authority_public_key_path: Path,
    workdir: Path,
) -> dict[str, Any]:
    """Valida autoridad material, atestigua Job y reclama el rol O_EXCL."""
    gate_file = _require_safe_regular_file(gate_path, context="internal_authorization_gate")
    gate = read_json_object(gate_file)
    if gate_file.read_bytes() != canonical_json_bytes(gate) + b"\n":
        raise ContractError("internal authorization gate no usa JSON canónico")
    request_payload = dict(payload)
    if role == "worker":
        request_payload.pop("authorization_gate", None)
    request_sha256 = canonical_json_sha256(request_payload)
    normalized = validate_internal_authorization_gate_contract(
        gate,
        expected_role=role,
        expected_request_payload_sha256=request_sha256,
        expected_capability_commitment_sha256=capability_commitment_sha256,
        expected_workdir_path=workdir,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        verify_artifacts=True,
    )
    if not _request_paths_within_workdir(role, payload, workdir):
        raise ContractError("request interno contiene rutas fuera del workdir autorizado")
    if role in {"worker", "adapter", "candidate"}:
        observed = _current_worker_job_limits()
        unit = cast(dict[str, Any], normalized["unit"])
        if (
            observed["logical_cpu_count"] > 4
            or observed["job_memory_commit_limit_bytes"] != CAPS[str(unit["cap_id"])]
            or observed["affinity_enforced"] is not True
            or observed["job_memory_enforced"] is not True
            or observed["kill_on_job_close"] is not True
        ):
            raise ContractError("executor interno no atestigua Job/cap/afinidad autorizados")
    else:
        _current_external_cleanup_job_controls()
    consumption = cast(dict[str, Any], normalized["authorization_consumption"])
    receipt = cast(dict[str, Any], consumption["receipt"])
    claim_internal_authorization_release(
        gate=normalized,
        role=role,
        request_payload_sha256=request_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        authorization_consumption_path=Path(str(receipt["path"])),
    )
    return normalized


def _validate_harness_driver(
    preflight: PreflightResult, supplied_driver_path: Path
) -> tuple[Path, dict[str, Any]]:
    expected = Path(__file__).resolve().parents[1] / "measure_readiness_h9r.py"
    if supplied_driver_path.resolve() != expected.resolve():
        raise ContractError("driver_path no coincide con el driver propiedad del arnés")
    identity = _source_identity(expected)
    if identity["safe_regular_file"] is not True:
        raise ContractError("driver del arnés no es archivo regular seguro")
    declared = [
        entry
        for entry in cast(list[dict[str, Any]], preflight.tooling["files"])
        if entry.get("relative_path") == "measure_readiness_h9r.py"
    ]
    if len(declared) != 1 or (
        declared[0].get("bytes") != identity["bytes"]
        or declared[0].get("sha256") != identity["sha256"]
    ):
        raise ContractError("driver del arnés no reconcilia con tooling firmado")
    return expected.resolve(), {
        "path": identity["path"],
        "bytes": identity["bytes"],
        "sha256": identity["sha256"],
    }


def _wait_for_pre_start_telemetry_sample(
    sampler: TelemetrySampler, *, preflight_deadline: float
) -> dict[str, Any]:
    """Exige una muestra completa y JobMemoryUsageInformation antes de consumir autoridad."""
    remaining = preflight_deadline - time.monotonic()
    if remaining <= 0:
        raise _PreStartAbortError(
            "watchdog_deadline",
            "deadline pre-START venció antes de la primera muestra",
        )
    first_sample = sampler.wait_first_sample(min(MAX_SAMPLE_GAP_SECONDS + 0.25, remaining))
    first_job = _require_mapping(first_sample.get("job"), context="telemetry.first.job")
    if (
        first_job.get("memory_usage_information_supported") is not True
        or isinstance(first_job.get("current_job_memory_commit_bytes"), bool)
        or not isinstance(first_job.get("current_job_memory_commit_bytes"), int)
    ):
        raise _PreStartAbortError(
            "limits_not_applied",
            "JobMemoryUsageInformation no acredita commit actual antes de START",
        )
    return first_sample


def _remaining_before_deadline(deadline: float, *, context: str) -> float:
    """Falla cerrado antes de reanudar o lanzar bytes si el deadline ya venció."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _PreStartAbortError("watchdog_deadline", f"deadline vencido {context}")
    return remaining


def _resume_suspended_before_deadline(
    pid: int, api: Any, *, deadline: float, context: str
) -> list[int]:
    """Reanuda sólo después de comprobar el deadline absoluto en el mismo paso."""
    _remaining_before_deadline(deadline, context=context)
    return resume_suspended_process(pid, api)


def _raise_pre_start_guard_if_needed(
    sampler: TelemetrySampler,
    *,
    memory_status: Mapping[str, Any],
    workdir: Path,
    phase: str,
) -> None:
    """Convierte cada guarda pre-START en una causa tipada y no en texto ambiguo."""
    guard = sampler.guard_classification
    if guard is not None:
        classification = (
            guard if guard in _PRE_START_TYPED_CLASSIFICATIONS else "evidence_incomplete"
        )
        raise _PreStartAbortError(
            classification,
            f"pre-START guard {phase}: {sampler.guard_reason or guard}",
        )
    if (
        memory_status.get("physical_available_bytes", 0) < RUN_MIN_AVAILABLE_PHYSICAL_BYTES
        or memory_status.get("commit_available_bytes", 0) < RUN_MIN_COMMIT_HEADROOM_BYTES
    ):
        raise _PreStartAbortError(
            "safety_abort_system_memory",
            f"pre-START memoria bajo piso {phase}",
        )
    if volume_free_bytes(workdir) < 1024**3:
        raise _PreStartAbortError(
            "safety_abort_disk",
            f"pre-START disco bajo piso {phase}",
        )


def _consume_authorization_before_start(
    reservation: Mapping[str, Any],
    *,
    preflight: PreflightResult,
    preflight_deadline: float,
    emergency_state: dict[str, Any],
) -> dict[str, Any]:
    """Mantiene el deadline como última barrera fallible antes del replace one-shot."""
    if time.monotonic() >= preflight_deadline:
        raise _PreStartAbortError(
            "watchdog_deadline",
            "deadline pre-START venció antes de consumir autorización",
        )
    return _consume_authorization(
        reservation,
        preflight=preflight,
        emergency_state=emergency_state,
    )


def _run_authorized_attempt_inner(
    *,
    preflight: PreflightResult,
    workdir: Path,
    evidence_path: Path,
    driver_path: Path,
    trusted_authority_public_key_path: Path,
    authorization_consumption_path: Path,
    emergency_state: dict[str, Any],
) -> dict[str, Any]:
    """Ejecuta una unidad ya autorizada; esta función no fue invocada en el cierre pre-START.

    El worker raíz se limita antes de READY. El START se materializa únicamente después de
    reconciliar la autoridad exacta ya validada por :func:`run_preflight`.
    """
    require_calibration_start_implementation_ready()
    _revalidate_preflight(
        preflight,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
    )
    preflight = copy.deepcopy(preflight)
    emergency_state["authority_snapshot"] = copy.deepcopy(preflight.authority)
    emergency_state["start_published"] = False
    if (
        preflight.authority.get("scope") != "calibration-start"
        or preflight.authority.get("start_authorized") is not True
    ):
        raise ContractError("la autoridad no permite START de calibración")
    driver_path, _ = _validate_harness_driver(preflight, driver_path)
    workdir, _ = _validate_workdir_reservation(preflight, workdir, require_initial_census=True)
    if evidence_path.resolve() != workdir / "attempt.json":
        raise ContractError("la evidencia final debe ser workdir/attempt.json")
    if os.path.lexists(evidence_path):
        raise ContractError("destino de evidencia ya existe")
    authorization_reservation: dict[str, Any] | None = None
    authorization_consumption: dict[str, Any] | None = None
    control = workdir / "telemetry" / "control"
    telemetry_root = workdir / "telemetry"
    scratch_root = workdir / "scratch"
    output_root = workdir / "outputs"
    request_path = control / "worker-request.json"
    boot_path = control / "boot.json"
    limits_path = control / "limits-applied.json"
    ready_path = control / "ready.json"
    start_path = control / "start.json"
    result_path = control / "worker-result.json"
    adapter_descriptor_path = control / "adapter-descriptor.json"
    adapter_request_path = control / "adapter-request.json"
    candidate_request_path = control / "candidate-request.json"
    ui_client_request_path = control / "ui-client-request.json"
    authorization_gate_path = control / "internal-authorization-gate.json"
    boundary_path = telemetry_root / "boundary.jsonl"
    filesystem_path = telemetry_root / "filesystem-events.jsonl"
    pools_path = telemetry_root / "native-pools.jsonl"
    adapter_audit_path = telemetry_root / "adapter-audit.jsonl"
    ui_first_byte_path = telemetry_root / "ui-first-byte.jsonl"
    client_boundary_path = telemetry_root / "client-boundary.jsonl"
    telemetry_path = telemetry_root / "resources.jsonl"
    stdout_path = telemetry_root / "worker.stdout.bin"
    stderr_path = telemetry_root / "worker.stderr.bin"
    client_stdout_path = telemetry_root / "client.stdout.bin"
    client_stderr_path = telemetry_root / "client.stderr.bin"
    staging_root = scratch_root / "consumer-staging"
    candidate_runtime_root = scratch_root / "candidate-runtime"
    candidate_outputs_path = staging_root / "candidate-outputs.json"
    brokered_inputs_path = candidate_runtime_root / "brokered-inputs.json"
    service_ready_path = candidate_runtime_root / "service-ready.json"
    adapter_result_path = control / "adapter-result.json"
    candidate_start_path = control / "candidate-start.json"
    candidate_result_path = control / "candidate-result.json"
    candidate_stdout_path = telemetry_root / "candidate.stdout.bin"
    candidate_stderr_path = telemetry_root / "candidate.stderr.bin"
    candidate_controller_stdout_path = telemetry_root / "candidate-controller.stdout.bin"
    candidate_controller_stderr_path = telemetry_root / "candidate-controller.stderr.bin"
    for cache_role in ("worker", "adapter", "candidate", "candidate-child", "ui-client"):
        cache_path = scratch_root / "python-cache" / cache_role
        cache_path.mkdir(exist_ok=False)
    snapshot = _materialize_attempt_harness_snapshot(
        preflight, scratch_root=scratch_root, control_root=control
    )
    emergency_state["harness_runtime_snapshot_sha256"] = str(snapshot["sha256"])
    roots = {
        "inputs": Path(str(preflight.fixture["inputs_root"])),
        "bundle": Path(str(preflight.fixture["bundle_root"])),
        "scratch": scratch_root,
        "outputs": output_root,
        "telemetry": telemetry_root,
    }
    resolved_roots = {name: path.resolve() for name, path in roots.items()}
    for left_name, left in resolved_roots.items():
        for right_name, right in resolved_roots.items():
            if left_name >= right_name:
                continue
            left_boundary = str(left).rstrip("\\/") + os.sep
            right_boundary = str(right).rstrip("\\/") + os.sep
            if (
                left == right
                or str(left).startswith(right_boundary)
                or str(right).startswith(left_boundary)
            ):
                raise ContractError(f"raíces de disco solapadas: {left_name}/{right_name}")
    if output_root.exists():
        raise ContractError("outputs debe ser inexistente antes de READY")
    baseline_disk = census_roots(roots)
    if not all(bool(value["allocation_reliable"]) for value in baseline_disk.values()):
        raise ContractError("baseline de allocation size no es calificable")
    baseline_volume_free = volume_free_bytes(workdir)
    boundary_path.open("xb").close()
    filesystem_path.open("xb").close()
    pools_path.open("xb").close()
    adapter_audit_path.open("xb").close()
    if preflight.unit["flow_id"] != "F-UI":
        ui_first_byte_path.open("xb").close()
    client_boundary_path.open("xb").close()
    paths = {
        "outputs": output_root,
        "boundary": boundary_path,
        "filesystem_events": filesystem_path,
        "native_pools": pools_path,
        "adapter_audit": adapter_audit_path,
        "ui_first_byte": ui_first_byte_path,
        "client_boundary": client_boundary_path,
        "staging": staging_root,
        "candidate_outputs": candidate_outputs_path,
        "brokered_inputs_json": brokered_inputs_path,
        "service_ready": service_ready_path,
        "candidate_start": candidate_start_path,
        "candidate_result": candidate_result_path,
        "candidate_stdout": candidate_stdout_path,
        "candidate_stderr": candidate_stderr_path,
        "candidate_controller_stdout": candidate_controller_stdout_path,
        "candidate_controller_stderr": candidate_controller_stderr_path,
        "candidate_child_pycache": scratch_root / "python-cache" / "candidate-child",
        "adapter_result": adapter_result_path,
    }
    config_value = cast(dict[str, Any], preflight.config["value"])
    consumer_config = cast(dict[str, Any], config_value["consumer"])
    expected_output_identities = cast(list[str], consumer_config["expected_output_identities"])
    adapter_descriptor = _build_adapter_descriptor(preflight)
    descriptor_publication = atomic_write_json_exclusive(
        adapter_descriptor_path, adapter_descriptor
    )
    candidate_request = _build_candidate_request(
        preflight,
        descriptor=adapter_descriptor,
        descriptor_identity=descriptor_publication,
        snapshot_identity=snapshot,
        paths=paths,
        workdir=workdir,
    )
    candidate_request_publication = atomic_write_json_exclusive(
        candidate_request_path, candidate_request
    )
    candidate_request_sha256 = canonical_json_sha256(candidate_request)
    candidate_capability_secret, candidate_capability_commitment = _issue_launch_capability(
        role="candidate", payload_sha256=candidate_request_sha256
    )
    snapshot_value = cast(dict[str, Any], snapshot["value"])
    snapshot_driver_path = (
        Path(str(snapshot_value["root"])) / "scripts" / "measure_readiness_h9r.py"
    )
    snapshot_driver_source = _source_identity(snapshot_driver_path)
    if snapshot_driver_source["safe_regular_file"] is not True:
        raise ContractError("driver del snapshot no es archivo regular seguro")
    harness_runtime = cast(dict[str, Any], preflight.tooling["harness_runtime"])
    harness_python = cast(dict[str, Any], harness_runtime["python_executable"])
    candidate_launch = {
        "python_executable": {
            "path": str(Path(str(harness_python["path"]))),
            "logical_bytes": int(harness_python["bytes"]),
            "sha256": str(harness_python["sha256"]),
        },
        "driver": {
            "path": str(snapshot_driver_path),
            "logical_bytes": int(snapshot_driver_source["bytes"]),
            "sha256": str(snapshot_driver_source["sha256"]),
        },
        "candidate_request": {
            "path": str(candidate_request_publication["path"]),
            "logical_bytes": int(candidate_request_publication["logical_bytes"]),
            "sha256": str(candidate_request_publication["sha256"]),
        },
        "candidate_request_payload_sha256": candidate_request_sha256,
        "capability_commitment_sha256": candidate_capability_commitment,
        "authorization_gate_path": str(authorization_gate_path),
        "trusted_authority_public_key_path": str(trusted_authority_public_key_path.resolve()),
        "harness_runtime_snapshot": {
            "path": str(snapshot["path"]),
            "logical_bytes": int(snapshot["bytes"]),
            "sha256": str(snapshot["sha256"]),
        },
    }
    adapter_request = _build_adapter_request(
        preflight,
        descriptor_identity=descriptor_publication,
        paths=paths,
        candidate_launch=candidate_launch,
    )
    validate_adapter_request(adapter_request)
    request_publication = atomic_write_json_exclusive(adapter_request_path, adapter_request)
    adapter_request_sha256 = canonical_json_sha256(adapter_request)
    adapter_capability_secret, adapter_capability_commitment = _issue_launch_capability(
        role="adapter", payload_sha256=adapter_request_sha256
    )
    adapter_launch = {
        "python_executable": {
            "path": str(Path(str(harness_python["path"]))),
            "bytes": int(harness_python["bytes"]),
            "sha256": str(harness_python["sha256"]),
        },
        "driver": {
            "path": str(snapshot_driver_path),
            "bytes": int(snapshot_driver_source["bytes"]),
            "sha256": str(snapshot_driver_source["sha256"]),
        },
        "adapter_request": _runtime_descriptor_identity(request_publication),
        "adapter_request_payload_sha256": adapter_request_sha256,
        "capability_commitment_sha256": adapter_capability_commitment,
        "authorization_gate_path": str(authorization_gate_path),
        "trusted_authority_public_key_path": str(trusted_authority_public_key_path.resolve()),
        "harness_runtime_snapshot": {
            "path": str(snapshot["path"]),
            "bytes": int(snapshot["bytes"]),
            "sha256": str(snapshot["sha256"]),
        },
    }
    _closed_adapter_command(adapter_launch, expected_attempt_id=preflight.attempt_id)
    ui_client_request = _build_ui_client_request(preflight, first_byte_path=ui_first_byte_path)
    ui_client_publication: dict[str, Any] | None = None
    external_client_command: list[str] | None = None
    ui_client_capability_secret: str | None = None
    ui_client_capability_commitment: str | None = None
    if ui_client_request is not None:
        validate_ui_client_request(ui_client_request)
        ui_client_publication = atomic_write_json_exclusive(
            ui_client_request_path, ui_client_request
        )
        ui_client_request_sha256 = canonical_json_sha256(ui_client_request)
        ui_client_capability_secret, ui_client_capability_commitment = _issue_launch_capability(
            role="ui-client", payload_sha256=ui_client_request_sha256
        )
        external_client_command = _build_ui_client_command(
            preflight,
            driver_path=snapshot_driver_path,
            request_path=ui_client_request_path,
            request_sha256=ui_client_request_sha256,
            capability_commitment_sha256=ui_client_capability_commitment,
            authorization_gate_path=authorization_gate_path,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
    runtime_descriptors = {
        "adapter_descriptor": _runtime_descriptor_identity(descriptor_publication),
        "adapter_request": _runtime_descriptor_identity(request_publication),
        "candidate_request": _runtime_descriptor_identity(candidate_request_publication),
        "harness_runtime_snapshot": {
            "path": str(snapshot["path"]),
            "bytes": int(snapshot["bytes"]),
            "sha256": str(snapshot["sha256"]),
        },
        "ui_client_request": None
        if ui_client_publication is None
        else _runtime_descriptor_identity(ui_client_publication),
    }
    _verify_runtime_descriptors(runtime_descriptors)
    attempt_tooling = {**preflight.tooling, "runtime_descriptors": runtime_descriptors}
    request = {
        "protocol_version": PROTOCOL_VERSION,
        "attempt_id": preflight.attempt_id,
        "adapter_launch": adapter_launch,
        "paths": {
            "boot": str(boot_path),
            "limits": str(limits_path),
            "ready": str(ready_path),
            "start": str(start_path),
            "result": str(result_path),
            "boundary": str(boundary_path),
            "filesystem_events": str(filesystem_path),
            "native_pools": str(pools_path),
            "outputs": str(output_root),
        },
        "handshake_deadline_seconds": HANDSHAKE_DEADLINE_SECONDS,
        "preflight_deadline_seconds": PREFLIGHT_DEADLINE_SECONDS,
        "expected_output_identities": list(expected_output_identities),
        "authorization_gate": {
            "path": str(authorization_gate_path),
            "trusted_authority_public_key_path": str(trusted_authority_public_key_path.resolve()),
        },
    }
    atomic_write_json_exclusive(request_path, request)
    worker_request_sha256 = canonical_json_sha256(request)
    worker_capability_secret, worker_capability_commitment = _issue_launch_capability(
        role="worker", payload_sha256=worker_request_sha256
    )
    capability_commitment_sha256: dict[str, str | None] = {
        "worker": worker_capability_commitment,
        "adapter": adapter_capability_commitment,
        "candidate": candidate_capability_commitment,
        "ui-client": None if ui_client_request is None else ui_client_capability_commitment,
    }
    worker_core = dict(request)
    worker_core.pop("authorization_gate", None)
    request_payload_sha256: dict[str, str | None] = {
        "worker": canonical_json_sha256(worker_core),
        "adapter": adapter_request_sha256,
        "candidate": candidate_request_sha256,
        "ui-client": None
        if ui_client_request is None
        else canonical_json_sha256(ui_client_request),
    }
    _validate_authorization_consumption_path(
        authorization_consumption_path,
        authority=preflight.authority,
        workdir=workdir,
    )
    supervisor_instance_nonce = secrets.token_hex(32)
    internal_bundle = reserve_internal_authorization_bundle(
        authority=preflight.authority,
        unit=preflight.unit,
        tooling_sha256=str(preflight.tooling["manifest_sha256"]),
        schedule_sha256=str(preflight.authority["schedule_sha256"]),
        workdir_path=workdir,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        supervisor_instance_nonce=supervisor_instance_nonce,
        authorization_consumption_path=authorization_consumption_path,
    )
    precommit_publication = cast(dict[str, Any], internal_bundle["precommit"])
    internal_authorization_precommit = {
        "path": str(precommit_publication["path"]),
        "bytes": Path(str(precommit_publication["path"])).stat().st_size,
        "sha256": str(precommit_publication["sha256"]),
    }
    authorization_reservation = _reserve_authorization_consumption(
        preflight=preflight,
        path=authorization_consumption_path,
        workdir=workdir,
    )
    emergency_state["authorization_reservation_snapshot"] = copy.deepcopy(
        _observe_authorization_reservation(preflight, authorization_consumption_path)
    )
    limits_requested = preflight.requested_limits
    cap_bytes = int(limits_requested["job_memory_commit_limit_bytes"])
    affinity_mask = int(limits_requested["affinity_mask"])
    handshake = Handshake(
        expected_authority_text_sha256=str(preflight.authority["authorization_text_sha256"]),
        expected_affinity_mask=affinity_mask,
        expected_memory_bytes=cap_bytes,
        expected_processor_group=int(preflight.effective_limits["processor_group"]),
    )
    worker_environment = _worker_environment(
        int(limits_requested["logical_cpu_count"]), workdir=workdir
    )
    worker_environment[_CAPABILITY_ENVIRONMENT["worker"]] = worker_capability_secret
    worker_environment[_CAPABILITY_ENVIRONMENT["adapter"]] = adapter_capability_secret
    worker_environment[_CAPABILITY_ENVIRONMENT["candidate"]] = candidate_capability_secret
    worker_environment["NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST"] = str(snapshot["path"])
    worker_environment["NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST_SHA256"] = str(snapshot["sha256"])
    client_environment = dict(worker_environment)
    client_environment.pop(_CAPABILITY_ENVIRONMENT["worker"], None)
    client_environment.pop(_CAPABILITY_ENVIRONMENT["adapter"], None)
    client_environment.pop(_CAPABILITY_ENVIRONMENT["candidate"], None)
    if ui_client_capability_secret is not None:
        client_environment[_CAPABILITY_ENVIRONMENT["ui-client"]] = ui_client_capability_secret
    stdout_handle = stdout_path.open("xb")
    stderr_handle = stderr_path.open("xb")
    client_stdout_handle = client_stdout_path.open("xb")
    client_stderr_handle = client_stderr_path.open("xb")
    process: subprocess.Popen[bytes] | None = None
    client_process: subprocess.Popen[bytes] | None = None
    job: WindowsJob | None = None
    client_job: WindowsExternalJob | None = None
    sampler: TelemetrySampler | None = None
    live_sensor: LiveWindowsSensor | None = None
    classification: str | None = None
    classification_reasons: list[str] = []
    timed_out = False
    final_manifest_quarantine: dict[str, Any] | None = None
    worker_result: dict[str, Any] | None = None
    accounting: dict[str, Any] = {}
    effective_limits: dict[str, Any] = {}
    tree_empty = False
    client_tree_empty = external_client_command is None
    returncode: int | None = None
    client_returncode: int | None = None
    sidecars: list[dict[str, Any]] = []
    sampler_summary: dict[str, Any] = {}
    memory_violation: dict[str, Any] = {}
    output_manifest: dict[str, Any] | None = None
    tree_empty_ns: int | None = None
    cancelled = False
    client_accounting: dict[str, Any] | None = None
    client_census: dict[str, Any] | None = None
    client_initial_processes: list[dict[str, Any]] = []
    preflight_deadline = preflight.started_monotonic_ns / 1_000_000_000 + PREFLIGHT_DEADLINE_SECONDS
    try:
        _closed_adapter_command(adapter_launch, expected_attempt_id=preflight.attempt_id)
        job = WindowsJob(memory_bytes=cap_bytes, affinity_mask=affinity_mask)
        emergency_state["job"] = job
        require_calibration_start_implementation_ready()
        _remaining_before_deadline(preflight_deadline, context="antes de crear el worker")
        process = subprocess.Popen(
            [
                str(harness_python["path"]),
                "-I",
                "-B",
                "-S",
                "-X",
                f"pycache_prefix={scratch_root / 'python-cache' / 'worker'}",
                str(snapshot_driver_path),
                "_worker",
                str(request_path),
                worker_capability_commitment,
            ],
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            cwd=workdir,
            env=worker_environment,
            close_fds=True,
            creationflags=0x00000004,  # CREATE_SUSPENDED: asignar Job antes de ejecutar un byte.
        )
        emergency_state["process"] = process
        try:
            job.assign(process.pid)
        except Exception as exc:
            raise _PreStartAbortError(
                "limits_not_applied",
                f"no se pudo asignar la raíz suspendida al Job: {exc}",
            ) from exc
        handshake.boot(pid=process.pid)
        effective_limits = job.effective_limits()
        emergency_state["effective_limits_snapshot"] = copy.deepcopy(effective_limits)
        handshake.limits_applied(effective_limits)
        resumed_tids = _resume_suspended_before_deadline(
            process.pid,
            job.api,
            deadline=preflight_deadline,
            context="antes de reanudar el worker",
        )
        remaining_preflight = preflight_deadline - time.monotonic()
        if remaining_preflight <= 0:
            raise _PreStartAbortError(
                "watchdog_deadline", "deadline pre-START excedido antes de BOOT"
            )
        boot = _wait_json(boot_path, timeout_seconds=remaining_preflight, process=process)
        if (
            boot.get("attempt_id") != preflight.attempt_id
            or boot.get("pid") != process.pid
            or boot.get("heavy_work_started") is not False
        ):
            raise _PreStartAbortError("limits_not_applied", "BOOT no reconcilia identidad/estado")
        atomic_write_json_exclusive(
            limits_path,
            {
                "protocol_version": PROTOCOL_VERSION,
                "attempt_id": preflight.attempt_id,
                "effective_limits": effective_limits,
                "resumed_primary_tids": resumed_tids,
            },
        )
        remaining_preflight = preflight_deadline - time.monotonic()
        if remaining_preflight <= 0:
            raise _PreStartAbortError(
                "watchdog_deadline", "deadline pre-START excedido antes de READY"
            )
        ready = _wait_json(ready_path, timeout_seconds=remaining_preflight, process=process)
        if ready.get("attempt_id") != preflight.attempt_id:
            raise _PreStartAbortError("limits_not_applied", "READY no reconcilia attempt_id")
        if ready.get("effective_affinity_mask") != affinity_mask:
            raise _PreStartAbortError("limits_not_applied", "READY observa otra afinidad")
        if ready.get("processor_groups") != [effective_limits["processor_group"]]:
            raise _PreStartAbortError("limits_not_applied", "READY observa otro grupo")
        if ready.get("native_pool_environment") != {
            key: worker_environment[key] for key in POOL_ENVIRONMENT_KEYS
        }:
            raise _PreStartAbortError("limits_not_applied", "pools nativos no reconcilian")
        handshake.ready()
        live_sensor = LiveWindowsSensor(
            job=job,
            roots=roots,
            volume_path=workdir,
            pool_environment={key: worker_environment[key] for key in POOL_ENVIRONMENT_KEYS},
        )
        sampler = TelemetrySampler(
            sensor=live_sensor,
            sidecar_path=telemetry_path,
            baseline_roots=baseline_disk,
            baseline_volume_free=baseline_volume_free,
            expected_affinity_mask=affinity_mask,
            expected_processor_group=int(effective_limits["processor_group"]),
        )
        sampler.start()
        _wait_for_pre_start_telemetry_sample(sampler, preflight_deadline=preflight_deadline)
        _revalidate_preflight(
            preflight,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
        _verify_runtime_descriptors(runtime_descriptors)
        _validate_workdir_reservation(preflight, workdir, require_initial_census=False)
        _raise_pre_start_guard_if_needed(
            sampler,
            memory_status=system_memory_status(),
            workdir=workdir,
            phase="antes de consumir autorización",
        )
        _raise_pre_start_guard_if_needed(
            sampler,
            memory_status=system_memory_status(),
            workdir=workdir,
            phase="inmediatamente antes de START",
        )
        # No ejecutar sensores ni código susceptible de fallo entre el consumo one-shot y START:
        # la segunda guarda queda inmediatamente antes de ambas escrituras durables.
        if authorization_reservation is None:  # pragma: no cover - defensa de secuencia.
            raise ContractError("reserva de autorización ausente antes de START")
        authorization_consumption = _consume_authorization_before_start(
            authorization_reservation,
            preflight=preflight,
            preflight_deadline=preflight_deadline,
            emergency_state=emergency_state,
        )
        emergency_state["authorization_consumption_snapshot"] = copy.deepcopy(
            authorization_consumption
        )
        start_token = handshake.start(
            authorization_text_sha256=str(preflight.authority["authorization_text_sha256"])
        )
        start_value = {**start_token, "attempt_id": preflight.attempt_id}
        expected_start = _expected_start_identity(path=start_path, value=start_value)
        emergency_state["start_expected_snapshot"] = copy.deepcopy(expected_start)
        emergency_state["start_write_attempted"] = True
        atomic_write_json_exclusive(
            start_path,
            start_value,
        )
        # El rename exclusivo ya es el hecho durable. Marcarlo antes de cualquier relectura
        # fallible impide clasificar como pre-START un token que sí quedó publicado.
        emergency_state["start_snapshot"] = copy.deepcopy(expected_start)
        emergency_state["start_published"] = True
        if _reopen_start_identity(preflight, start_path) != expected_start:
            raise ContractError("START durable no reconcilia con su identidad write-ahead")
        workload_deadline = float(start_token["start_monotonic_ns"]) / 1_000_000_000 + float(
            limits_requested["workload_deadline_seconds"]
        )
        _remaining_before_deadline(workload_deadline, context="después de publicar START")
        gate = _build_internal_authorization_gate(
            preflight=preflight,
            workdir=workdir,
            worker_request=request,
            adapter_request=adapter_request,
            candidate_request=candidate_request,
            ui_client_request=ui_client_request,
            capability_commitment_sha256=capability_commitment_sha256,
            internal_authorization_precommit=internal_authorization_precommit,
            supervisor_instance_nonce=supervisor_instance_nonce,
            authorization_consumption=authorization_consumption,
            start_path=start_path,
        )
        # El gate es el único release visible para los hijos; se publica al final para que cada
        # reserva O_EXCL ya exista cuando worker/UI puedan observarlo.
        _remaining_before_deadline(workload_deadline, context="antes de publicar el gate interno")
        atomic_write_json_exclusive(authorization_gate_path, gate)
        if external_client_command is not None:
            _closed_adapter_command(adapter_launch, expected_attempt_id=preflight.attempt_id)
            client_job = WindowsExternalJob()
            emergency_state["client_job"] = client_job
            try:
                _remaining_before_deadline(
                    workload_deadline, context="antes de crear el cliente UI"
                )
                (
                    client_process,
                    client_accounting,
                    client_census,
                ) = _launch_external_client_assigned_suspended(
                    job=client_job,
                    command=external_client_command,
                    workdir=workdir,
                    environment=client_environment,
                    stdout_handle=client_stdout_handle,
                    stderr_handle=client_stderr_handle,
                )
                emergency_state["client_process"] = client_process
                # La identidad raíz se obtiene mientras el único hilo sigue suspendido: ni un
                # cliente efímero ni un fallo temprano pueden escapar del censo inicial.
                initial_tree = cast(dict[str, Any], client_census.get("tree", {}))
                client_initial_processes = [
                    dict(item)
                    for item in cast(list[dict[str, Any]], initial_tree.get("processes", []))
                ]
                _resume_suspended_before_deadline(
                    client_process.pid,
                    client_job.api,
                    deadline=workload_deadline,
                    context="antes de reanudar el cliente UI",
                )
            except Exception as exc:
                if client_process is not None:
                    with contextlib.suppress(Exception):
                        client_job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                    with contextlib.suppress(Exception):
                        client_process.wait(timeout=10)
                raise ContractError(
                    f"limits_not_applied: cliente externo no quedó confinado a cleanup Job: {exc}"
                ) from exc
            live_sensor.client_pid = client_process.pid
            live_sensor.client_job = client_job
            _flush_fsync(client_stdout_handle)
            _flush_fsync(client_stderr_handle)
        cleanup_deadline: float | None = None
        while int(job.accounting()["active_processes"]) > 0 or (
            client_job is not None and int(client_job.accounting()["active_processes"]) > 0
        ):
            now = time.monotonic()
            if cleanup_deadline is not None and now >= cleanup_deadline:
                classification = "orphan_detected"
                if not any("deadline de cleanup" in reason for reason in classification_reasons):
                    classification_reasons.append(
                        "Job no acreditó árbol vacío dentro del deadline de cleanup"
                    )
                break
            if sampler.guard_classification is not None:
                classification = sampler.guard_classification
                classification_reasons.append(sampler.guard_reason or "guarda sin razón")
                job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                if client_job is not None:
                    client_job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                cleanup_deadline = cleanup_deadline or time.monotonic() + 10.0
                time.sleep(0.01)
                continue
            if now >= workload_deadline:
                timed_out = True
                classification = "watchdog_deadline"
                classification_reasons.append("deadline externo START→árbol vacío")
                job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                if client_job is not None:
                    client_job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                cleanup_deadline = cleanup_deadline or time.monotonic() + 10.0
                time.sleep(0.01)
                continue
            if cleanup_deadline is not None and time.monotonic() >= cleanup_deadline:
                classification = "orphan_detected"
                classification_reasons.append(
                    "Job no acredito arbol vacio dentro del deadline de cleanup"
                )
                break
            time.sleep(0.025)
        tree_empty = int(job.accounting()["active_processes"]) == 0
        client_tree_empty = bool(
            client_job is None or int(client_job.accounting()["active_processes"]) == 0
        )
        if tree_empty and client_tree_empty:
            tree_empty_ns = time.monotonic_ns()
        with contextlib.suppress(subprocess.TimeoutExpired):
            returncode = process.wait(timeout=10)
        if returncode is None:
            returncode = process.poll()
        if client_process is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                client_returncode = client_process.wait(timeout=10)
            if client_returncode is None:
                client_returncode = client_process.poll()
        if client_job is not None:
            client_accounting = client_job.accounting()
            client_census = client_job.census()
        if not tree_empty:
            job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
            tree_empty = job.wait_empty(10.0)
            classification = "orphan_detected"
            classification_reasons.append("el árbol no quedó vacío tras terminar la raíz")
        accounting = job.accounting()
        memory_violation = job.memory_limit_violation()
        if sampler is not None:
            sampler_result = sampler.stop()
            sidecars.append(cast(dict[str, Any], sampler_result["sidecar"]))
            sampler_summary = cast(dict[str, Any], sampler_result["summary"])
        stdout_handle.flush()
        stderr_handle.flush()
        os.fsync(stdout_handle.fileno())
        os.fsync(stderr_handle.fileno())
        stdout_handle.close()
        stderr_handle.close()
        if result_path.is_file():
            worker_result = read_json_object(result_path)
        try:
            _revalidate_preflight(
                preflight,
                trusted_authority_public_key_path=trusted_authority_public_key_path,
            )
            _verify_runtime_descriptors(runtime_descriptors)
        except ContractError as exc:
            classification = "invariant_failure"
            classification_reasons.append(f"artefactos de lanzamiento cambiaron: {exc}")
        if classification is None:
            if memory_violation.get("job_memory_limit_violated") is True:
                classification = "job_memory_limit"
                classification_reasons.append("notificación kernel del límite de memoria Job")
            elif (
                returncode == 0
                and (client_returncode is None or client_returncode == 0)
                and worker_result is not None
                and worker_result.get("status") == "ok"
            ):
                try:
                    output_manifest = validate_output_manifest(
                        output_root,
                        expected_identities=expected_output_identities,
                        expected_counts=cast(
                            dict[str, int], preflight.fixture["expected"]["counts"]
                        ),
                        expected_golden_sha256=str(
                            preflight.fixture["expected"]["golden"]["sha256"]
                        ),
                    )
                except ContractError as exc:
                    classification = "invariant_failure"
                    classification_reasons.append(str(exc))
            elif client_returncode not in {None, 0}:
                classification = "consumer_error"
                classification_reasons.append(f"cliente externo devolvió {client_returncode}")
            elif worker_result is not None and worker_result.get("status") == "error":
                oom_records: list[dict[str, Any]] = []
                with contextlib.suppress(ContractError):
                    oom_records = _read_boundary_events(telemetry_path, allow_missing=True)
                oom = _classify_worker_error_from_runtime(
                    worker_result,
                    memory_violation=memory_violation,
                    resource_records=oom_records,
                    termination_monotonic_ns=tree_empty_ns,
                )
                if oom is None:
                    classification = "consumer_error"
                    classification_reasons.append(str(worker_result.get("error")))
                else:
                    classification, reason = oom
                    classification_reasons.append(reason)
            else:
                classification = "evidence_incomplete"
                classification_reasons.append("terminación sin resultado clasificable")
    except KeyboardInterrupt:
        cancelled = True
        classification = "cancelled"
        classification_reasons.append("cancelación humana/externa observada")
        if job is not None:
            with contextlib.suppress(Exception):
                job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
    except _PreStartAbortError as exc:
        classification = exc.classification
        classification_reasons.append(str(exc))
        if job is not None:
            with contextlib.suppress(Exception):
                job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
    except ContractError as exc:
        classification = "invariant_failure"
        classification_reasons.append(str(exc))
        if job is not None:
            with contextlib.suppress(Exception):
                job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
    except Exception as exc:
        classification = "supervisor_error"
        classification_reasons.append(f"{type(exc).__name__}: {exc}")
        classification_reasons.append(traceback.format_exc())
        if job is not None:
            with contextlib.suppress(Exception):
                job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
    finally:
        if sampler is not None and not sidecars:
            try:
                sampler_result = sampler.stop()
                sidecars.append(cast(dict[str, Any], sampler_result["sidecar"]))
                sampler_summary = cast(dict[str, Any], sampler_result["summary"])
            except TimeoutError as exc:
                # stop() cierra el único descriptor writer antes de lanzar: desde aquí los
                # bytes son inmutables aunque el sensor bloqueado tarde en devolver.
                classification = "evidence_incomplete"
                classification_reasons.append(str(exc))
            except Exception as exc:
                classification = "evidence_incomplete"
                classification_reasons.append(
                    f"freeze/finalize del sampler falló: {type(exc).__name__}: {exc}"
                )
        if job is not None:
            try:
                if int(job.accounting()["active_processes"]) > 0:
                    job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                tree_empty = job.wait_empty(2.0)
                accounting = job.accounting()
                memory_violation = job.memory_limit_violation()
                emergency_state["job_accounting"] = accounting
            except Exception as exc:
                tree_empty = False
                classification = "orphan_detected"
                classification_reasons.append(f"cleanup del Job principal falló: {exc}")
            try:
                job.close()
            except Exception as exc:
                tree_empty = False
                classification = "orphan_detected"
                classification_reasons.append(f"close del Job principal falló: {exc}")
        elif process is not None and process.poll() is None:
            # La raíz se creó suspendida; si la asignación al Job falló, sólo existe ese
            # proceso y se elimina antes de producir evidencia.
            with contextlib.suppress(Exception):
                process.kill()
                process.wait(timeout=10)
            tree_empty = process.poll() is not None
            if not tree_empty:
                classification = "orphan_detected"
                classification_reasons.append(
                    "cleanup de raíz suspendida sin Job no acreditó árbol vacío"
                )
        elif process is None:
            tree_empty = True
        if client_job is not None:
            try:
                if int(client_job.accounting()["active_processes"]) > 0:
                    client_job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                client_tree_empty = client_job.wait_empty(2.0)
                client_accounting = client_job.accounting()
                client_census = client_job.census()
                emergency_state["client_accounting"] = client_accounting
            except Exception as exc:
                client_tree_empty = False
                if classification not in {"watchdog_deadline", "cancelled"}:
                    classification = "orphan_detected"
                classification_reasons.append(f"cleanup del cliente externo falló: {exc}")
            try:
                client_job.close()
            except Exception as exc:
                client_tree_empty = False
                classification = "orphan_detected"
                classification_reasons.append(f"close del cliente externo falló: {exc}")
        elif client_process is None:
            client_tree_empty = True
        if tree_empty and client_tree_empty and tree_empty_ns is None:
            tree_empty_ns = time.monotonic_ns()
        if not stdout_handle.closed:
            try:
                _flush_fsync(stdout_handle)
            except OSError as exc:
                classification = "evidence_incomplete"
                classification_reasons.append(f"fsync stdout worker falló: {exc}")
            stdout_handle.close()
        if not stderr_handle.closed:
            try:
                _flush_fsync(stderr_handle)
            except OSError as exc:
                classification = "evidence_incomplete"
                classification_reasons.append(f"fsync stderr worker falló: {exc}")
            stderr_handle.close()
        if not client_stdout_handle.closed:
            try:
                _flush_fsync(client_stdout_handle)
            except OSError as exc:
                classification = "evidence_incomplete"
                classification_reasons.append(f"fsync stdout cliente falló: {exc}")
            client_stdout_handle.close()
        if not client_stderr_handle.closed:
            try:
                _flush_fsync(client_stderr_handle)
            except OSError as exc:
                classification = "evidence_incomplete"
                classification_reasons.append(f"fsync stderr cliente falló: {exc}")
            client_stderr_handle.close()
        emergency_state["worker_tree_empty"] = tree_empty
        emergency_state["client_tree_empty"] = client_tree_empty
    try:
        _closed_adapter_command(adapter_launch, expected_attempt_id=preflight.attempt_id)
    except ContractError as exc:
        classification = "invariant_failure"
        classification_reasons.append(f"driver/launch cambió al cierre: {exc}")
    _ensure_regular_sidecar_exists(telemetry_path, context="resources sidecar")
    _ensure_regular_sidecar_exists(stdout_path, context="worker stdout sidecar")
    _ensure_regular_sidecar_exists(stderr_path, context="worker stderr sidecar")
    _ensure_regular_sidecar_exists(client_stdout_path, context="client stdout sidecar")
    _ensure_regular_sidecar_exists(client_stderr_path, context="client stderr sidecar")
    for candidate_log_path in (
        candidate_stdout_path,
        candidate_stderr_path,
        candidate_controller_stdout_path,
        candidate_controller_stderr_path,
    ):
        _ensure_regular_sidecar_exists(
            candidate_log_path, context=f"candidate log {candidate_log_path.name}"
        )
    for reserved_sidecar in (
        boundary_path,
        filesystem_path,
        pools_path,
        adapter_audit_path,
        ui_first_byte_path,
        client_boundary_path,
    ):
        created = _ensure_regular_sidecar_exists(
            reserved_sidecar, context=f"reserved sidecar {reserved_sidecar.name}"
        )
        if not created:
            continue
        if not (
            reserved_sidecar == ui_first_byte_path
            and preflight.unit["flow_id"] == "F-UI"
            and classification != "success"
        ):
            classification = "evidence_incomplete"
            classification_reasons.append(
                f"sidecar reservado desapareció y fue repuesto vacío: {reserved_sidecar.name}"
            )
    if classification is None and output_manifest is not None:
        # Fijar el candidato a success antes de validar sidecars obliga a exigir sus máquinas
        # completas; cualquier sidecar defectuoso degrada la clasificación a continuación.
        classification = "success"
    sidecars = [
        _jsonl_sidecar_metadata(telemetry_path, name="resources"),
        _jsonl_sidecar_metadata(boundary_path, name="boundary"),
        _jsonl_sidecar_metadata(filesystem_path, name="filesystem"),
        _jsonl_sidecar_metadata(pools_path, name="native_pools"),
        _jsonl_sidecar_metadata(adapter_audit_path, name="adapter_audit"),
        _jsonl_sidecar_metadata(ui_first_byte_path, name="ui_first_byte"),
        binary_sidecar_metadata(stdout_path, name="worker_stdout"),
        binary_sidecar_metadata(stderr_path, name="worker_stderr"),
        _jsonl_sidecar_metadata(client_boundary_path, name="client_boundary"),
        binary_sidecar_metadata(client_stdout_path, name="client_stdout"),
        binary_sidecar_metadata(client_stderr_path, name="client_stderr"),
        binary_sidecar_metadata(candidate_stdout_path, name="candidate_stdout"),
        binary_sidecar_metadata(candidate_stderr_path, name="candidate_stderr"),
        binary_sidecar_metadata(
            candidate_controller_stdout_path, name="candidate_controller_stdout"
        ),
        binary_sidecar_metadata(
            candidate_controller_stderr_path, name="candidate_controller_stderr"
        ),
    ]
    sidecars_reconciled = False
    consumer_sidecars: dict[str, list[dict[str, Any]]] = {
        "boundary_events": [],
        "filesystem_events": [],
    }
    try:
        for sidecar in sidecars:
            verify_sidecar(sidecar)
        native_pool_events = verify_jsonl_sidecar(sidecars[3])
        if classification == "success":
            validate_native_pool_events(native_pool_events)
        elif native_pool_events:
            try:
                validate_native_pool_events(native_pool_events)
            except ContractError as exc:
                classification_reasons.append(
                    f"native-pools secundario no reemplaza causa primaria: {exc}"
                )
        adapter_audit_events = verify_jsonl_sidecar(sidecars[4])
        if adapter_audit_events or classification == "success":
            validate_adapter_audit(adapter_audit_path, require_success=classification == "success")
        ui_first_byte_events = verify_jsonl_sidecar(sidecars[5])
        _validate_ui_first_byte_events(ui_first_byte_events, preflight=preflight)
        if verify_jsonl_sidecar(sidecars[8]):
            raise ContractError("client_boundary reservado debe permanecer vacío")
        consumer_sidecars = reconstruct_consumer_sidecars(
            boundary_metadata=sidecars[1],
            filesystem_metadata=sidecars[2],
            output_root=output_root,
            manifest=output_manifest,
            require_complete=classification == "success",
        )
        if (
            preflight.unit["flow_id"] == "F-UI"
            and classification == "success"
            and not ui_first_byte_events
        ):
            raise ContractError("F-UI success exige primer byte de respuesta observado por cliente")
        if ui_first_byte_events:
            response_first_byte = ui_first_byte_events[0]
            matching_boundary = [
                event
                for event in consumer_sidecars["boundary_events"]
                if event.get("event") == "first_open_or_byte"
                and event.get("kind") == "first_byte"
                and event.get("provider") == "harness_owned_candidate_http_ingress_v1"
                and event.get("request_id") == response_first_byte["request_id"]
                and isinstance(event.get("monotonic_ns"), int)
                and int(event["monotonic_ns"]) <= int(response_first_byte["monotonic_ns"])
            ]
            if len(matching_boundary) != 1:
                raise ContractError(
                    "respuesta F-UI no reconcilia causalmente con el ingress del consumidor"
                )
        sidecars_reconciled = True
    except ContractError as exc:
        classification = "evidence_incomplete"
        classification_reasons.append(str(exc))
    if sampler_summary.get("guard_classification") is not None:
        guard_classification = str(sampler_summary["guard_classification"])
        guard_reason = str(sampler_summary.get("guard_reason"))
        if classification is None:
            classification = guard_classification
            classification_reasons.append(guard_reason)
        elif classification != guard_classification:
            classification_reasons.append(
                f"guarda secundaria {guard_classification} no reemplaza causa primaria: "
                f"{guard_reason}"
            )
    observed_processes = cast(
        list[dict[str, Any]], sampler_summary.get("observed_process_identities", [])
    )
    if accounting and int(accounting.get("total_processes", 0)) != len(observed_processes):
        classification = "evidence_incomplete"
        classification_reasons.append("censo PID+creation-time no cubre TotalProcesses del Job")
    observed_client_processes = cast(
        list[dict[str, Any]], sampler_summary.get("observed_client_process_identities", [])
    )
    observed_client_identity_set = {
        (int(item["pid"]), int(item["creation_time_100ns"])) for item in observed_client_processes
    }
    observed_client_identity_set.update(
        (int(item["pid"]), int(item["creation_time_100ns"]))
        for item in client_initial_processes
        if isinstance(item.get("pid"), int) and isinstance(item.get("creation_time_100ns"), int)
    )
    observed_client_processes = [
        {"pid": pid, "creation_time_100ns": creation}
        for pid, creation in sorted(observed_client_identity_set)
    ]
    if sampler_summary:
        sampler_summary["observed_client_process_identities"] = observed_client_processes
    if client_accounting and int(client_accounting.get("total_processes", 0)) != len(
        observed_client_processes
    ):
        classification = "evidence_incomplete"
        classification_reasons.append(
            "censo PID+creation-time no cubre TotalProcesses del cliente externo"
        )
    if classification is None:
        classification = "success" if output_manifest is not None else "evidence_incomplete"
    if classification != "success":
        final_manifest_quarantine = _quarantine_final_manifest(output_root, scratch_root)
    boundary_events = consumer_sidecars["boundary_events"]
    client_boundary_events = _read_boundary_events(client_boundary_path, allow_missing=True)
    observed_events = [*handshake.events, *boundary_events, *client_boundary_events]
    if tree_empty_ns is not None:
        observed_events.append({"event": "tree_empty", "monotonic_ns": tree_empty_ns})
    observed_events.sort(key=lambda event: int(event["monotonic_ns"]))
    try:
        validate_boundary_events(observed_events, require_complete=classification == "success")
    except ContractError as exc:
        classification = "invariant_failure" if boundary_events else "evidence_incomplete"
        classification_reasons.append(str(exc))
    if not tree_empty or not client_tree_empty:
        classification = "orphan_detected"
        if not any("orphan" in reason.casefold() for reason in classification_reasons):
            classification_reasons.append("árbol principal o cliente no quedó vacío")
    if classification != "success" and final_manifest_quarantine is None:
        final_manifest_quarantine = _quarantine_final_manifest(output_root, scratch_root)
    if final_manifest_quarantine is not None:
        _verify_quarantined_manifest(final_manifest_quarantine)
    final_manifest_present = (output_root / "manifest.json").is_file()
    _release_workdir_reservation(preflight, workdir)
    emergency_state["workdir_reservation_released"] = True
    final_disk = census_roots(roots)
    validate_census_against_filesystem(final_disk, roots)
    disk_reconciled = True
    resource_records = verify_jsonl_sidecar(sidecars[0])
    if sampler_summary and consumer_sidecars["boundary_events"]:
        try:
            ready_ns = next(
                (
                    int(event["monotonic_ns"])
                    for event in handshake.events
                    if event["event"] == "ready"
                ),
                None,
            )
            consumer_window, overhead = derive_consumer_window_summary(
                resource_records,
                boundary_events=consumer_sidecars["boundary_events"],
                ready_monotonic_ns=cast(int, ready_ns),
                tree_empty_monotonic_ns=cast(int, tree_empty_ns),
                baseline_roots=baseline_disk,
            )
            sampler_summary["consumer_window"] = consumer_window
            sampler_summary["overhead"] = overhead
        except ContractError as exc:
            classification = "evidence_incomplete"
            classification_reasons.append(str(exc))
    disk_samples = [
        cast(dict[str, Any], cast(dict[str, Any], record["disk"])["roots"])
        for record in resource_records
        if isinstance(record.get("disk"), dict)
        and isinstance(cast(dict[str, Any], record["disk"]).get("roots"), dict)
    ]
    # El último censo no puede perder un pico ocurrido entre la última muestra y árbol vacío.
    disk_samples.append(final_disk)
    footprint = disk_footprint_summary(baseline_disk, disk_samples)
    output_inventory = final_inventory(output_root) if output_root.exists() else []
    classification, trigger_classification, cancelled = _normalize_termination_trigger(
        classification,
        timed_out=timed_out,
        cancelled=cancelled,
        cleanup_complete=tree_empty and client_tree_empty,
        reasons=classification_reasons,
    )
    authority_exact = (
        preflight.authority.get("scope") == "calibration-start"
        and preflight.authority.get("start_authorized") is True
    )
    limits_effective = bool(
        effective_limits
        and effective_limits.get("job_memory_commit_limit_bytes") == cap_bytes
        and effective_limits.get("affinity_mask") == affinity_mask
        and effective_limits.get("group_affinities")
        == [
            {
                "processor_group": effective_limits.get("processor_group"),
                "affinity_mask": affinity_mask,
            }
        ]
    )
    if authorization_consumption is None:
        raise ContractError(
            "intento terminó antes de consumir START; autorización queda reservada y no replayable"
        )
    evidence = {
        "schema_version": ATTEMPT_SCHEMA_VERSION,
        "identity": {
            "attempt_id": preflight.attempt_id,
            "unit": preflight.unit,
            "evidence_path": str(evidence_path.resolve()),
            "wall_time_finished_utc": datetime.now(UTC).isoformat(),
            "preflight_started_monotonic_ns": preflight.started_monotonic_ns,
            "ready_monotonic_ns": next(
                (event["monotonic_ns"] for event in handshake.events if event["event"] == "ready"),
                None,
            ),
            "start_monotonic_ns": next(
                (event["monotonic_ns"] for event in handshake.events if event["event"] == "start"),
                None,
            ),
            "tree_empty_monotonic_ns": tree_empty_ns,
        },
        "authority": preflight.authority,
        "authorization_consumption": authorization_consumption,
        "candidate": preflight.candidate,
        "tooling": attempt_tooling,
        "fixture": preflight.fixture,
        "environment": preflight.environment,
        "limits": {
            "requested": preflight.requested_limits,
            "effective": effective_limits,
            "logical_cpu_count_effective": effective_limits.get("logical_cpu_count"),
            "job_memory_commit_limit_bytes_effective": effective_limits.get(
                "job_memory_commit_limit_bytes"
            ),
            "ready_before_start": _ready_before_start(handshake.events),
            "guards": preflight.resource_guards,
        },
        "boundary": {
            "provider": (
                "harness_owned_candidate_http_ingress_v1"
                if preflight.unit["flow_id"] == "F-UI"
                else "harness_owned_consumer_open_v1"
            ),
            "events": observed_events,
            "consumer_sidecar_present": bool(boundary_events or client_boundary_events),
        },
        "resources": {
            "job_accounting": accounting,
            "external_client": {
                "declared": external_client_command is not None,
                "command_sha256": None
                if external_client_command is None
                else canonical_json_sha256(external_client_command),
                "accounting": client_accounting,
                "final_census": client_census,
            },
            "memory_limit_violation": memory_violation,
            "summary": sampler_summary,
            "sidecars": sidecars,
            "disk_baseline_volume_free_bytes": baseline_volume_free,
            "disk_baseline": baseline_disk,
            "disk_final": final_disk,
            "disk_footprint": footprint,
        },
        "outputs": {
            "final_manifest_present": final_manifest_present,
            "expected_identities": list(expected_output_identities),
            "manifest": output_manifest if classification == "success" else None,
            "inventory": output_inventory,
            "quarantined_invalid_manifest": final_manifest_quarantine,
        },
        "termination": {
            "returncode_signed": returncode,
            "returncode_unsigned": None if returncode is None else returncode & 0xFFFFFFFF,
            "client_returncode_signed": client_returncode,
            "client_returncode_unsigned": None
            if client_returncode is None
            else client_returncode & 0xFFFFFFFF,
            "cleanup_complete": tree_empty and client_tree_empty,
            "tree_empty": tree_empty,
            "client_tree_empty": client_tree_empty,
            "trigger_classification": trigger_classification,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "worker_result": worker_result,
        },
        "gates": {
            "authority_exact": authority_exact,
            "preflight_passed": bool(preflight.resource_guards.get("passed")),
            "limits_effective": limits_effective,
            "sidecars_reconciled": sidecars_reconciled,
            "disk_reconciled": disk_reconciled,
            "output_completeness_bidirectional": classification == "success",
            "atomic_publication": bool(
                (classification == "success" and final_manifest_present)
                or (classification != "success" and not final_manifest_present)
            ),
        },
        "result": {
            "classification": classification,
            "statistically_eligible": classification == "success",
            "reasons": classification_reasons,
        },
    }
    validate_attempt_evidence(
        evidence,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        verify_artifacts=True,
        _verify_evidence_self_binding=False,
    )
    atomic_write_json_exclusive(evidence_path, evidence)
    reopened_evidence = read_json_object(evidence_path)
    if reopened_evidence != evidence:
        raise ContractError("artefacto final de evidencia no reconcilia tras publicación")
    validate_attempt_evidence(
        reopened_evidence,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        verify_artifacts=True,
    )
    return evidence


def _observe_authorization_reservation(preflight: PreflightResult, path: Path) -> dict[str, Any]:
    expected_path_digest = str(preflight.authority["authorization_consumption_path_sha256"])
    if authorization_consumption_path_digest(path) != expected_path_digest:
        raise ContractError("ruta de reserva pre-START no coincide con la autoridad")
    identity = _source_identity(path)
    if not os.path.lexists(path):
        return {
            "authorization_id": preflight.authority["authorization_id"],
            "authorization_consumption_path_sha256": expected_path_digest,
            "state": "absent",
            "consumed_at_utc": None,
            "attempt_id": preflight.attempt_id,
            "authority_sha256": canonical_json_sha256(preflight.authority),
            "receipt": identity,
        }
    receipt_path = _require_safe_regular_file(path, context="pre-start.receipt")
    receipt = read_json_object(receipt_path)
    expected_base = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": preflight.authority["authorization_id"],
        "attempt_id": preflight.attempt_id,
        "authority_sha256": canonical_json_sha256(preflight.authority),
    }
    state = receipt.get("state")
    consumed_at = receipt.get("consumed_at_utc")
    if state == "reserved" and consumed_at is None:
        expected = {**expected_base, "state": "reserved", "consumed_at_utc": None}
    elif state == "consumed" and isinstance(consumed_at, str) and consumed_at:
        expected = {
            **expected_base,
            "state": "consumed",
            "consumed_at_utc": consumed_at,
        }
    else:
        raise ContractError("receipt pre-START no está reservado/consumido válidamente")
    if receipt != expected or receipt_path.read_bytes() != canonical_json_bytes(expected) + b"\n":
        raise ContractError("reserva pre-START viva no reconcilia con autoridad/unidad")
    return {
        "authorization_id": receipt["authorization_id"],
        "authorization_consumption_path_sha256": expected_path_digest,
        "state": state,
        "consumed_at_utc": consumed_at,
        "attempt_id": receipt["attempt_id"],
        "authority_sha256": receipt["authority_sha256"],
        "receipt": identity,
    }


def _reopen_start_values(
    *, attempt_id_value: str, authority: Mapping[str, Any], path: Path
) -> dict[str, Any]:
    start_path = _require_safe_regular_file(path, context="emergency.start")
    start = read_json_object(start_path)
    if set(start) != {
        "protocol_version",
        "authorization_text_sha256",
        "ready_monotonic_ns",
        "start_monotonic_ns",
        "attempt_id",
    }:
        raise ContractError("emergency: START no tiene campos exactos")
    if (
        start["protocol_version"] != PROTOCOL_VERSION
        or start["attempt_id"] != attempt_id_value
        or start["authorization_text_sha256"] != authority["authorization_text_sha256"]
        or isinstance(start["start_monotonic_ns"], bool)
        or not isinstance(start["start_monotonic_ns"], int)
        or start["start_monotonic_ns"] < 0
        or isinstance(start["ready_monotonic_ns"], bool)
        or not isinstance(start["ready_monotonic_ns"], int)
        or start["ready_monotonic_ns"] < 0
        or start["ready_monotonic_ns"] > start["start_monotonic_ns"]
    ):
        raise ContractError("emergency: START no liga autoridad/unidad exactas")
    if start_path.read_bytes() != canonical_json_bytes(start) + b"\n":
        raise ContractError("emergency: START no usa JSON canónico")
    return {
        **start,
        "path": str(start_path),
        "bytes": start_path.stat().st_size,
        "sha256": sha256_file(start_path),
    }


def _reopen_start_identity(preflight: PreflightResult, path: Path) -> dict[str, Any]:
    return _reopen_start_values(
        attempt_id_value=preflight.attempt_id,
        authority=preflight.authority,
        path=path,
    )


def _expected_start_identity(*, path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    payload = canonical_json_bytes(dict(value)) + b"\n"
    return {
        **dict(value),
        "path": str(path.resolve()),
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _live_file_matches_snapshot(snapshot: Mapping[str, Any]) -> bool:
    """Compara bytes durables sin convertir un fallo causal en otra excepción terminal."""
    try:
        path = _require_safe_regular_file(
            Path(str(snapshot["path"])), context="emergency.durable_snapshot"
        )
        expected_bytes = int(snapshot["bytes"])
        expected_sha256 = validate_sha256(
            snapshot["sha256"], context="emergency.durable_snapshot.sha256"
        )
        return path.stat().st_size == expected_bytes and sha256_file(path) == expected_sha256
    except (ContractError, OSError, TypeError, ValueError):
        return False


def _reconcile_emergency_durable_state(
    *,
    preflight: PreflightResult,
    authorization_consumption_path: Path,
    start_path: Path,
    emergency_state: dict[str, Any],
) -> None:
    """Reconcilia replaces/renames que pudieron persistir antes de una excepción inyectada."""
    expected_consumption_raw = emergency_state.get("authorization_consumption_expected")
    if isinstance(expected_consumption_raw, Mapping):
        expected_consumption = dict(expected_consumption_raw)
        receipt = _require_mapping(
            expected_consumption.get("receipt"),
            context="emergency.authorization_consumption_expected.receipt",
        )
        if _live_file_matches_snapshot(receipt):
            emergency_state["authorization_consumption_snapshot"] = copy.deepcopy(
                expected_consumption
            )
            try:
                observed_reservation = _observe_authorization_reservation(
                    preflight, authorization_consumption_path
                )
            except (ContractError, OSError):
                observed_reservation = None
            if observed_reservation is not None and observed_reservation.get("state") == "consumed":
                emergency_state["authorization_reservation_snapshot"] = copy.deepcopy(
                    observed_reservation
                )

    expected_start_raw = emergency_state.get("start_expected_snapshot")
    if isinstance(expected_start_raw, Mapping):
        expected_start = dict(expected_start_raw)
        if Path(
            str(expected_start.get("path", ""))
        ).resolve() == start_path.resolve() and _live_file_matches_snapshot(expected_start):
            emergency_state["start_snapshot"] = copy.deepcopy(expected_start)
            emergency_state["start_published"] = True


def _move_plain_file_exclusive_write_through(source: Path, destination: Path) -> None:
    """Mueve un control regular sin seguir enlaces ni reemplazar el destino."""
    _require_safe_regular_file(source, context="unexpected_start.source")
    _require_plain_directory(source.parent, context="unexpected_start.source_parent")
    _require_plain_directory(destination.parent, context="unexpected_start.destination_parent")
    if os.path.lexists(destination):
        raise ContractError("quarantine START ya existe")
    if sys.platform != "win32":  # pragma: no cover - H9R calificable exige Windows.
        raise ContractError("quarantine START atómico exige Windows")
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.MoveFileExW.restype = ctypes.c_bool
    movefile_write_through = 0x8
    if not kernel32.MoveFileExW(str(source), str(destination), movefile_write_through):
        raise OSError(ctypes.get_last_error(), "MoveFileExW quarantine START falló")


def _quarantine_unexpected_pre_start_token(
    *,
    preflight: PreflightResult,
    workdir: Path,
    authorization_consumption_path: Path,
    emergency_state: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Aparta un START ajeno sólo si gate y cuatro claims siguen causalmente ausentes."""
    control = workdir / "telemetry" / "control"
    start_path = control / "start.json"
    observed_start = _source_identity(start_path)
    if observed_start["present"] is not True:
        return None
    if observed_start["safe_regular_file"] is not True:
        raise ContractError("START inesperado no es un archivo regular seguro")
    original_snapshot = {
        "path": observed_start["path"],
        "bytes": observed_start["bytes"],
        "sha256": observed_start["sha256"],
    }
    gate_path = control / "internal-authorization-gate.json"
    gate_identity = _source_identity(gate_path)
    if gate_identity["present"] is True:
        raise ContractError("START inesperado coexistía con gate interno")
    role_claim_paths: dict[str, Path] = {}
    for role in INTERNAL_AUTHORIZATION_ROLES:
        _reserved_path, claimed_path = internal_authorization_release_paths(
            authorization_consumption_path,
            attempt_id_value=preflight.attempt_id,
            role=role,
        )
        identity = _source_identity(claimed_path)
        if identity["present"] is True:
            raise ContractError(f"START inesperado coexistía con claim {role}")
        role_claim_paths[role] = claimed_path
    quarantine_path = workdir / "scratch" / "invalid-pre-start-token.json"
    _move_plain_file_exclusive_write_through(start_path, quarantine_path)
    start_after = _source_identity(start_path)
    quarantined = _source_identity(quarantine_path)
    if (
        start_after["present"] is not False
        or quarantined["safe_regular_file"] is not True
        or quarantined["bytes"] != original_snapshot["bytes"]
        or quarantined["sha256"] != original_snapshot["sha256"]
    ):
        raise ContractError("quarantine START no reconcilia el movimiento durable")
    return {
        "original_snapshot": original_snapshot,
        "quarantined": quarantined,
        "moved_atomically": True,
        "worker_created": emergency_state.get("process") is not None,
        "authorization_gate": _source_identity(gate_path),
        "role_claims": {
            role: _source_identity(role_claim_paths[role]) for role in INTERNAL_AUTHORIZATION_ROLES
        },
    }


def _attempt_emergency_cleanup(state: Mapping[str, Any]) -> dict[str, Any]:
    cleanup_errors: list[str] = []
    accounting: dict[str, Any] = {
        "worker": state.get("job_accounting"),
        "client": state.get("client_accounting"),
    }

    def empty_tree(prefix: str) -> bool:
        declared = state.get(f"{prefix}_tree_empty")
        if declared is True:
            return True
        job = state.get("job" if prefix == "worker" else "client_job")
        if job is not None:
            try:
                if int(job.accounting()["active_processes"]) > 0:
                    job.terminate(_SUPERVISOR_ABORT_EXIT_CODE)
                empty = bool(job.wait_empty(5.0))
                accounting[prefix] = job.accounting()
                return empty
            except Exception as exc:
                cleanup_errors.append(f"{prefix} Job cleanup: {type(exc).__name__}: {exc}")
        process = state.get("process" if prefix == "worker" else "client_process")
        if process is None:
            return prefix == "client"
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            return process.poll() is not None
        except Exception as exc:
            cleanup_errors.append(f"{prefix} root cleanup: {type(exc).__name__}: {exc}")
            return False

    worker_empty = empty_tree("worker")
    client_empty = empty_tree("client")
    return {
        "worker_tree_empty": worker_empty,
        "client_tree_empty": client_empty,
        "cleanup_complete": worker_empty and client_empty and not cleanup_errors,
        "job_accounting": accounting["worker"],
        "client_accounting": accounting["client"],
        "errors": cleanup_errors,
    }


def _attempt_emergency_cleanup_once(state: Mapping[str, Any]) -> dict[str, Any]:
    """Ejecuta la limpieza una vez y conserva su snapshot para toda ruta terminal."""
    existing = state.get("emergency_cleanup_snapshot")
    if isinstance(existing, Mapping):
        return copy.deepcopy(dict(existing))
    cleanup = _attempt_emergency_cleanup(state)
    if isinstance(state, dict):
        state["emergency_cleanup_snapshot"] = copy.deepcopy(cleanup)
    return cleanup


def _observed_or_error(function: Any) -> dict[str, Any]:
    try:
        return {"available": True, "value": function(), "error": None}
    except Exception as exc:
        return {
            "available": False,
            "value": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _causal_source_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    inline = {
        "path": str(Path(str(identity["path"])).resolve()),
        "bytes": int(identity["bytes"]),
        "sha256": validate_sha256(identity["sha256"], context="causal snapshot sha256"),
    }
    path = Path(str(inline["path"]))
    observed = _source_identity(path)
    matches = bool(
        observed["safe_regular_file"] is True
        and observed["bytes"] == inline["bytes"]
        and observed["sha256"] == inline["sha256"]
    )
    return {"snapshot": inline, "observed": observed, "matches_snapshot": matches}


def _optional_causal_source_identity(
    *, path: Path, snapshot: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Conserva la fuente viva aunque aún no existiera un snapshot durable."""
    if snapshot is None:
        return {
            "snapshot": None,
            "observed": _source_identity(path),
            "matches_snapshot": False,
        }
    return _causal_source_identity(snapshot)


def _authority_causal_source(authority: Mapping[str, Any], *, path: Path) -> dict[str, Any]:
    serialized = canonical_json_bytes(authority) + b"\n"
    return _causal_source_identity(
        {
            "path": str(path.resolve()),
            "bytes": len(serialized),
            "sha256": sha256_bytes(serialized),
        }
    )


def _publish_post_start_failure(
    *,
    preflight: PreflightResult,
    workdir: Path,
    evidence_path: Path,
    trusted_authority_public_key_path: Path,
    authorization_consumption_path: Path,
    emergency_state: Mapping[str, Any],
    error: BaseException,
) -> dict[str, Any]:
    # La limpieza precede cualquier relectura: una fuente causal corrupta no puede dejar Jobs.
    cleanup = _attempt_emergency_cleanup_once(emergency_state)
    workdir = workdir.resolve()
    if evidence_path.resolve() != workdir / "attempt.json":
        raise ContractError("evidencia terminal debe ser workdir/attempt.json") from error
    if os.path.lexists(evidence_path):
        raise ContractError("attempt final ya existe; emergency nunca lo sobrescribe") from error
    authority = copy.deepcopy(
        _require_mapping(
            emergency_state.get("authority_snapshot", preflight.authority),
            context="emergency.authority_snapshot",
        )
    )
    consumption = copy.deepcopy(
        _require_mapping(
            emergency_state.get("authorization_consumption_snapshot"),
            context="emergency.authorization_consumption_snapshot",
        )
    )
    start = copy.deepcopy(
        _require_mapping(emergency_state.get("start_snapshot"), context="emergency.start_snapshot")
    )
    telemetry = workdir / "telemetry"
    sidecar_paths = [
        ("resources", telemetry / "resources.jsonl"),
        ("boundary", telemetry / "boundary.jsonl"),
        ("filesystem", telemetry / "filesystem-events.jsonl"),
        ("native_pools", telemetry / "native-pools.jsonl"),
        ("adapter_audit", telemetry / "adapter-audit.jsonl"),
        ("ui_first_byte", telemetry / "ui-first-byte.jsonl"),
        ("worker_stdout", telemetry / "worker.stdout.bin"),
        ("worker_stderr", telemetry / "worker.stderr.bin"),
        ("client_boundary", telemetry / "client-boundary.jsonl"),
        ("client_stdout", telemetry / "client.stdout.bin"),
        ("client_stderr", telemetry / "client.stderr.bin"),
        ("candidate_stdout", telemetry / "candidate.stdout.bin"),
        ("candidate_stderr", telemetry / "candidate.stderr.bin"),
        ("candidate_controller_stdout", telemetry / "candidate-controller.stdout.bin"),
        ("candidate_controller_stderr", telemetry / "candidate-controller.stderr.bin"),
    ]
    roots = {
        "inputs": Path(str(preflight.fixture["inputs_root"])),
        "bundle": Path(str(preflight.fixture["bundle_root"])),
        "scratch": workdir / "scratch",
        "outputs": workdir / "outputs",
        "telemetry": telemetry,
    }
    traceback_value = "".join(traceback.format_exception(error))
    payload = {
        "schema_version": POST_START_FAILURE_SCHEMA_VERSION,
        "phase": "post-start-terminal",
        "identity": {
            "attempt_id": preflight.attempt_id,
            "unit": preflight.unit,
            "evidence_path": str(evidence_path.resolve()),
            "wall_time_finished_utc": datetime.now(UTC).isoformat(),
        },
        "authority": authority,
        "execution_context": {
            "environment": copy.deepcopy(preflight.environment),
            "candidate": copy.deepcopy(preflight.candidate),
            "tooling": {
                "protocol_version": preflight.tooling["protocol_version"],
                "manifest_sha256": preflight.tooling["manifest_sha256"],
                "document_sha256": copy.deepcopy(preflight.tooling["document_sha256"]),
                "harness_runtime": copy.deepcopy(preflight.tooling["harness_runtime"]),
                "harness_runtime_snapshot_sha256": validate_sha256(
                    emergency_state.get("harness_runtime_snapshot_sha256"),
                    context="emergency.harness_runtime_snapshot_sha256",
                ),
            },
            "limits": {
                "requested": copy.deepcopy(preflight.requested_limits),
                "effective": copy.deepcopy(
                    _require_mapping(
                        emergency_state.get("effective_limits_snapshot"),
                        context="emergency.effective_limits_snapshot",
                    )
                ),
            },
            "schedule": copy.deepcopy(
                _require_mapping(
                    preflight.schedule.get("value"),
                    context="emergency.execution_context.schedule",
                )
            ),
        },
        "authorization_consumption": consumption,
        "start": start,
        "cause": {
            "stage": "terminal_publication",
            "error_type": type(error).__name__,
            "message": str(error) or type(error).__name__,
            "traceback_sha256": sha256_bytes(traceback_value.encode("utf-8")),
        },
        "cleanup": cleanup,
        "observed": {
            "causal_sources": {
                "authority": _authority_causal_source(
                    authority, path=Path(str(preflight.source_paths["authority"]))
                ),
                "authorization_consumption": _causal_source_identity(
                    cast(dict[str, Any], consumption["receipt"])
                ),
                "start": _causal_source_identity(start),
            },
            "sidecars": [
                {"name": name, "identity": _source_identity(path)} for name, path in sidecar_paths
            ],
            "output_inventory": _observed_or_error(lambda: final_inventory(workdir / "outputs")),
            "final_manifest": _source_identity(workdir / "outputs" / "manifest.json"),
            "quarantined_manifest": _source_identity(
                workdir / "scratch" / "invalid-final-manifest.json"
            ),
            "disk_final": _observed_or_error(lambda: census_roots(roots)),
        },
        "gates": {
            "start_observed": True,
            "authorization_consumed": True,
            "evidence_atomic": True,
        },
        "result": {"classification": "evidence_incomplete", "statistically_eligible": False},
    }
    allow_test_authority = preflight.authority.get("scope") == "harness-test-only"
    validate_post_start_failure_evidence(
        payload,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        allow_harness_test_authority=allow_test_authority,
    )
    atomic_write_json_exclusive(evidence_path, payload)
    reopened = read_json_object(evidence_path)
    if reopened != payload:
        raise ContractError("post-start-failure no reconcilia tras publicación") from error
    validate_post_start_failure_evidence(
        reopened,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        verify_artifacts=True,
        allow_harness_test_authority=allow_test_authority,
    )
    return payload


def _pre_start_classification(error: BaseException) -> str:
    if isinstance(error, KeyboardInterrupt):
        return "cancelled"
    if isinstance(error, _PreStartAbortError):
        return error.classification
    if isinstance(error, TimeoutError):
        return "watchdog_deadline"
    if isinstance(error, ContractError):
        return "invariant_failure"
    return "supervisor_error"


def _normalize_termination_trigger(
    classification: str,
    *,
    timed_out: bool,
    cancelled: bool,
    cleanup_complete: bool,
    reasons: list[str],
) -> tuple[str, str | None, bool]:
    """Conserva el trigger causal aunque un cleanup incompleto termine como orphan."""
    trigger: str | None = None
    if timed_out:
        trigger = "watchdog_deadline"
        cancelled = False
    elif cancelled:
        trigger = "cancelled"
    if trigger is None:
        return classification, None, cancelled
    final = trigger if cleanup_complete else "orphan_detected"
    if classification != final:
        reasons.append(
            f"clasificación secundaria {classification} no reemplaza trigger {trigger}; "
            f"final={final}"
        )
    return final, trigger, cancelled


def _publish_pre_start_failure(
    *,
    preflight: PreflightResult,
    workdir: Path,
    evidence_path: Path,
    trusted_authority_public_key_path: Path,
    authorization_consumption_path: Path,
    emergency_state: Mapping[str, Any],
    error: BaseException,
) -> dict[str, Any]:
    # La limpieza es el primer acto: una fuente causal rota nunca puede retener Jobs vivos.
    cleanup = _attempt_emergency_cleanup_once(emergency_state)
    if os.path.lexists(evidence_path):
        raise ContractError("evidencia terminal ya existe") from error
    if emergency_state.get("start_published") is True:
        raise ContractError("pre-start failure prohíbe un START publicado") from error
    unexpected_start_quarantine = _quarantine_unexpected_pre_start_token(
        preflight=preflight,
        workdir=workdir,
        authorization_consumption_path=authorization_consumption_path,
        emergency_state=emergency_state,
    )
    authority = copy.deepcopy(
        _require_mapping(
            emergency_state.get("authority_snapshot", preflight.authority),
            context="emergency.authority_snapshot",
        )
    )
    reservation_snapshot = emergency_state.get("authorization_reservation_snapshot")
    try:
        live_reservation = _observe_authorization_reservation(
            preflight, authorization_consumption_path
        )
    except (ContractError, OSError):
        live_reservation = None
    if live_reservation is not None and live_reservation.get("state") == "consumed":
        reservation = live_reservation
    elif reservation_snapshot is not None:
        reservation = copy.deepcopy(
            _require_mapping(
                reservation_snapshot,
                context="emergency.authorization_reservation_snapshot",
            )
        )
    elif live_reservation is not None:
        reservation = live_reservation
    else:
        # Sin snapshot previo, vuelve a elevar el error causal: no se puede fabricar estado.
        reservation = _observe_authorization_reservation(preflight, authorization_consumption_path)
    try:
        _release_workdir_reservation(preflight, workdir)
    except Exception as cleanup_error:
        cleanup["cleanup_complete"] = False
        cast(list[str], cleanup["errors"]).append(
            f"workdir reservation cleanup: {type(cleanup_error).__name__}: {cleanup_error}"
        )
    telemetry = workdir / "telemetry"
    control = telemetry / "control"
    handshake_paths = {
        "boot": control / "boot.json",
        "limits_applied": control / "limits-applied.json",
        "ready": control / "ready.json",
        "start": control / "start.json",
    }
    sidecar_paths = [
        ("resources", telemetry / "resources.jsonl"),
        ("boundary", telemetry / "boundary.jsonl"),
        ("filesystem", telemetry / "filesystem-events.jsonl"),
        ("native_pools", telemetry / "native-pools.jsonl"),
        ("adapter_audit", telemetry / "adapter-audit.jsonl"),
        ("ui_first_byte", telemetry / "ui-first-byte.jsonl"),
        ("worker_stdout", telemetry / "worker.stdout.bin"),
        ("worker_stderr", telemetry / "worker.stderr.bin"),
        ("client_boundary", telemetry / "client-boundary.jsonl"),
        ("client_stdout", telemetry / "client.stdout.bin"),
        ("client_stderr", telemetry / "client.stderr.bin"),
        ("candidate_stdout", telemetry / "candidate.stdout.bin"),
        ("candidate_stderr", telemetry / "candidate.stderr.bin"),
        ("candidate_controller_stdout", telemetry / "candidate-controller.stdout.bin"),
        ("candidate_controller_stderr", telemetry / "candidate-controller.stderr.bin"),
    ]
    classification = _pre_start_classification(error)
    if unexpected_start_quarantine is not None:
        classification = "invariant_failure"
    traceback_value = "".join(traceback.format_exception(error))
    payload = {
        "schema_version": PRE_START_FAILURE_SCHEMA_VERSION,
        "phase": "pre-start-terminal",
        "identity": {
            "attempt_id": preflight.attempt_id,
            "unit": preflight.unit,
            "evidence_path": str(evidence_path.resolve()),
            "wall_time_finished_utc": datetime.now(UTC).isoformat(),
        },
        "authority": authority,
        "authorization_reservation": reservation,
        "cause": {
            "classification": classification,
            "error_type": type(error).__name__,
            "message": str(error) or type(error).__name__,
            "traceback_sha256": sha256_bytes(traceback_value.encode("utf-8")),
        },
        "cleanup": cleanup,
        "observed": {
            "causal_sources": {
                "authority": _authority_causal_source(
                    authority, path=Path(str(preflight.source_paths["authority"]))
                ),
                "authorization_consumption": _optional_causal_source_identity(
                    path=authorization_consumption_path,
                    snapshot=None
                    if reservation["state"] == "absent"
                    else cast(dict[str, Any], reservation["receipt"]),
                ),
                "start": _optional_causal_source_identity(
                    path=handshake_paths["start"], snapshot=None
                ),
            },
            "handshake": {name: _source_identity(path) for name, path in handshake_paths.items()},
            "sidecars": [
                {"name": name, "identity": _source_identity(path)} for name, path in sidecar_paths
            ],
            "unexpected_start_quarantine": unexpected_start_quarantine,
        },
        "gates": {
            "start_observed": False,
            "workload_started": False,
            "authorization_reserved": reservation["state"] == "reserved",
            "evidence_atomic": True,
        },
        "result": {"classification": classification, "statistically_eligible": False},
    }
    allow_test = preflight.authority.get("scope") == "harness-test-only"
    validate_pre_start_failure_evidence(
        payload,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        allow_harness_test_authority=allow_test,
    )
    atomic_write_json_exclusive(evidence_path, payload)
    reopened = read_json_object(evidence_path)
    if reopened != payload:
        raise ContractError("pre-start failure no reconcilia tras publicación") from error
    validate_pre_start_failure_evidence(
        reopened,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        verify_artifacts=True,
        allow_harness_test_authority=allow_test,
    )
    return payload


def run_authorized_attempt(
    *,
    preflight: PreflightResult,
    workdir: Path,
    evidence_path: Path,
    driver_path: Path,
    trusted_authority_public_key_path: Path,
    authorization_consumption_path: Path,
) -> dict[str, Any]:
    """Ejecuta el intento y publica evidencia terminal separada si falla tras START."""
    require_calibration_start_implementation_ready()
    emergency_state: dict[str, Any] = {}
    try:
        return _run_authorized_attempt_inner(
            preflight=preflight,
            workdir=workdir,
            evidence_path=evidence_path,
            driver_path=driver_path,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
            authorization_consumption_path=authorization_consumption_path,
            emergency_state=emergency_state,
        )
    except BaseException as exc:
        _attempt_emergency_cleanup_once(emergency_state)
        _reconcile_emergency_durable_state(
            preflight=preflight,
            authorization_consumption_path=authorization_consumption_path,
            start_path=workdir.resolve() / "telemetry" / "control" / "start.json",
            emergency_state=emergency_state,
        )
        if os.path.lexists(evidence_path):
            raise
        if emergency_state.get("start_published") is not True:
            return _publish_pre_start_failure(
                preflight=preflight,
                workdir=workdir.resolve(),
                evidence_path=evidence_path.resolve(),
                trusted_authority_public_key_path=trusted_authority_public_key_path,
                authorization_consumption_path=authorization_consumption_path,
                emergency_state=emergency_state,
                error=exc,
            )
        return _publish_post_start_failure(
            preflight=preflight,
            workdir=workdir.resolve(),
            evidence_path=evidence_path.resolve(),
            trusted_authority_public_key_path=trusted_authority_public_key_path,
            authorization_consumption_path=authorization_consumption_path,
            emergency_state=emergency_state,
            error=exc,
        )


def _ready_before_start(events: Sequence[Mapping[str, Any]]) -> bool:
    names = [event.get("event") for event in events]
    return "ready" in names and "start" in names and names.index("ready") < names.index("start")


def _read_boundary_events(path: Path, *, allow_missing: bool = False) -> list[dict[str, Any]]:
    if not os.path.lexists(path):
        if allow_missing:
            return []
        raise ContractError("sidecar de frontera ausente")
    safe = _require_safe_regular_file(path, context="sidecar de frontera")
    payload = safe.read_bytes()
    events: list[dict[str, Any]] = []
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("boundary JSONL no es UTF-8") from exc
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        if not line.endswith("\n") or not line.strip():
            raise ContractError(f"boundary JSONL truncado en línea {line_number}")
        try:
            raw: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"boundary JSONL inválido en línea {line_number}") from exc
        if not isinstance(raw, dict):
            raise ContractError(f"boundary evento no es objeto en línea {line_number}")
        if line.encode("utf-8") != canonical_json_bytes(raw) + b"\n":
            raise ContractError(f"boundary evento no es canónico en línea {line_number}")
        events.append(cast(dict[str, Any], raw))
    observed = _source_identity(safe)
    if (
        observed["safe_regular_file"] is not True
        or observed["bytes"] != len(payload)
        or observed["sha256"] != sha256_bytes(payload)
    ):
        raise ContractError("boundary JSONL cambió durante la reapertura")
    return events


def run_worker(request_path: Path, capability_commitment_sha256: str) -> int:
    """Worker interno: espera límites y START antes de abrir/ejecutar el consumidor."""
    require_calibration_start_implementation_ready()
    request_path = Path(os.path.abspath(request_path))
    request = _read_canonical_control(request_path, context="worker request")
    request_payload_sha256 = canonical_json_sha256(request)
    consume_launch_capability(
        role="worker",
        payload_sha256=request_payload_sha256,
        expected_commitment_sha256=capability_commitment_sha256,
    )
    expected_pycache = (
        request_path.resolve().parents[2] / "scratch" / "python-cache" / "worker"
    ).resolve()
    if (
        sys.flags.isolated != 1
        or sys.dont_write_bytecode != 1
        or sys.flags.no_site != 1
        or sys.pycache_prefix is None
        or Path(sys.pycache_prefix).resolve() != expected_pycache
        or not expected_pycache.is_dir()
        or _is_reparse_or_symlink(expected_pycache)
        or any(expected_pycache.iterdir())
    ):
        raise ContractError("worker no usa -I -B -S y pycache_prefix fresco exactos")
    if set(request) != {
        "protocol_version",
        "attempt_id",
        "adapter_launch",
        "paths",
        "handshake_deadline_seconds",
        "preflight_deadline_seconds",
        "expected_output_identities",
        "authorization_gate",
    }:
        raise ContractError("worker request no tiene campos exactos")
    if request["protocol_version"] != PROTOCOL_VERSION:
        raise ContractError("worker request usa otro protocolo")
    paths = _require_mapping(request.get("paths"), context="worker.paths")
    if set(paths) != {
        "boot",
        "limits",
        "ready",
        "start",
        "result",
        "boundary",
        "filesystem_events",
        "native_pools",
        "outputs",
    }:
        raise ContractError("worker.paths no tiene campos exactos")
    attempt = str(request.get("attempt_id"))
    boot_path = Path(str(paths["boot"]))
    limits_path = Path(str(paths["limits"]))
    ready_path = Path(str(paths["ready"]))
    start_path = Path(str(paths["start"]))
    result_path = Path(str(paths["result"]))
    boundary_path = Path(str(paths["boundary"]))
    filesystem_path = Path(str(paths["filesystem_events"]))
    pools_path = Path(str(paths["native_pools"]))
    deadline = float(request["handshake_deadline_seconds"])
    try:
        atomic_write_json_exclusive(
            boot_path,
            {
                "protocol_version": PROTOCOL_VERSION,
                "attempt_id": attempt,
                "pid": os.getpid(),
                "heavy_work_started": False,
            },
        )
        limits = _wait_for_file_without_work(limits_path, deadline)
        effective = _require_mapping(limits.get("effective_limits"), context="worker limits")
        observed_job = _current_worker_job_limits()
        for key in (
            "affinity_mask",
            "logical_cpu_count",
            "group_affinities",
            "job_memory_commit_limit_bytes",
            "kill_on_job_close",
            "affinity_enforced",
            "job_memory_enforced",
        ):
            if observed_job[key] != effective.get(key):
                raise ContractError(
                    f"limits_not_applied: worker observa otro Job/límite efectivo: {key}"
                )
        observed = process_metrics(os.getpid())
        if observed["affinity_mask"] != effective["affinity_mask"]:
            raise ContractError("limits_not_applied: worker observa otra máscara")
        if observed["processor_groups"] != [effective["processor_group"]]:
            raise ContractError("limits_not_applied: worker observa otro grupo")
        atomic_write_json_exclusive(
            ready_path,
            {
                "protocol_version": PROTOCOL_VERSION,
                "attempt_id": attempt,
                "pid": os.getpid(),
                "effective_affinity_mask": observed["affinity_mask"],
                "processor_groups": observed["processor_groups"],
                "native_pool_environment": {
                    key: os.environ.get(key) for key in POOL_ENVIRONMENT_KEYS
                },
                "heavy_work_started": False,
            },
        )
        start = _wait_for_file_without_work(start_path, deadline)
        if start.get("attempt_id") != attempt:
            raise ContractError("token START no reconcilia")
        gate_launch = _require_mapping(
            request.get("authorization_gate"), context="worker.authorization_gate"
        )
        if set(gate_launch) != {
            "path",
            "trusted_authority_public_key_path",
        }:
            raise ContractError("worker authorization_gate no tiene campos exactos")
        gate_path = Path(str(gate_launch["path"]))
        _wait_for_file_without_work(gate_path, deadline)
        consume_internal_authorization_gate(
            gate_path=gate_path,
            role="worker",
            payload=request,
            capability_commitment_sha256=capability_commitment_sha256,
            trusted_authority_public_key_path=Path(
                str(gate_launch["trusted_authority_public_key_path"])
            ),
            workdir=request_path.resolve().parents[2],
        )
        environment = dict(os.environ)
        environment.update(
            {
                "NIKODYM_H9R_ATTEMPT_ID": attempt,
                "NIKODYM_H9R_BOUNDARY_JSONL": str(boundary_path),
                "NIKODYM_H9R_FILESYSTEM_JSONL": str(filesystem_path),
                "NIKODYM_H9R_NATIVE_POOLS_JSONL": str(pools_path),
                "NIKODYM_H9R_OUTPUT_ROOT": str(paths["outputs"]),
            }
        )
        raw_launch = _require_mapping(request.get("adapter_launch"), context="adapter_launch")
        adapter_command = _closed_adapter_command(raw_launch, expected_attempt_id=attempt)
        completed = subprocess.run(
            adapter_command,
            check=False,
            env=environment,
            stdin=subprocess.DEVNULL,
        )
        result = {
            "schema_version": WORKER_RESULT_SCHEMA_VERSION,
            "attempt_id": attempt,
            "status": "ok" if completed.returncode == 0 else "error",
            "consumer_returncode_signed": completed.returncode,
            "consumer_returncode_unsigned": completed.returncode & 0xFFFFFFFF,
            "error": None if completed.returncode == 0 else "consumer devolvió no-cero",
        }
        atomic_write_json_exclusive(result_path, result)
        return completed.returncode
    except Exception as exc:
        with contextlib.suppress(FileExistsError):
            atomic_write_json_exclusive(
                result_path,
                {
                    "schema_version": WORKER_RESULT_SCHEMA_VERSION,
                    "attempt_id": attempt,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


def _wait_for_file_without_work(path: Path, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if os.path.lexists(path):
            return _read_canonical_control(path, context=f"worker control {path.name}")
        time.sleep(0.01)
    raise TimeoutError(f"handshake esperando {path.name}")
