"""Prototipo fail-closed del runner propiedad del arnés para los adaptadores H9R.

Este módulo no autoriza ni materializa START. Su única responsabilidad es cerrar la frontera
ejecutable que usaría una unidad ya autorizada: un script exacto del árbol candidato escribe en
``staging`` y el runner reabre sus bytes antes de publicar outputs y sidecars finales. Esa ruta no
es calificable mientras la puerta central declare ausentes el lease continuo del material candidato
y el aislamiento OS de ``OUTPUT_ROOT`` frente al token candidato.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, Final, Protocol, cast

from .artifacts import (
    OUTPUT_FORMAT_COUNTERS,
    canonical_tree_identity,
    derive_output_record_count,
    validate_output_manifest,
)
from .consumer import (
    ConsumerBoundary,
    ConsumerPublisher,
    append_jsonl_event,
    prepare_jsonl_sidecar,
    record_native_pools,
    validate_consumer_boundary_events,
)
from .contracts import (
    ADAPTER_IDS,
    CANDIDATE_OUTPUT_ISOLATION_SCHEMA_VERSION,
    CANDIDATE_PROTECTED_ROOT_COUNT,
    CANDIDATE_WRITABLE_ROOT_COUNT,
    CAPS,
    PROTOCOL_VERSION,
    ContractError,
    canonical_json_bytes,
    canonical_json_sha256,
    flow_spec,
    read_json_object,
    sha256_file,
    validate_attempt_unit,
    validate_sha256,
)
from .contracts import (
    attempt_id as derive_attempt_id,
)
from .runtime_snapshot import validate_harness_source_snapshot
from .windows_job import (
    WindowsJob,
    process_metrics,
    resume_suspended_process,
    tcp_listener_owner_pid,
)
from .windows_sandbox import (
    DENIED_OPERATIONS,
    LOW_INTEGRITY_SID,
    SANDBOX_MECHANISM,
    SandboxProcess,
    apply_low_integrity_label,
    census_output_isolation,
    launch_suspended_low_integrity,
    low_integrity_primary_token,
    mandatory_label,
    probe_output_root_denial,
    process_integrity_level,
)

ADAPTER_DESCRIPTOR_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.adapter-implementation.v1"
ADAPTER_REQUEST_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.adapter-request.v1"
ADAPTER_RESULT_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.adapter-result.v1"
CANDIDATE_OUTPUTS_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.candidate-outputs.v1"
ADAPTER_AUDIT_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.adapter-input-audit.v1"
UI_FIRST_BYTE_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.ui-first-byte.v1"
UI_CLIENT_REQUEST_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.ui-client-request.v1"
COUNTER_ADAPTER_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.counter-adapter.v1"
COUNTER_RESULT_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.counter-result.v1"
CANDIDATE_REQUEST_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.candidate-launch-request.v1"
CANDIDATE_START_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.candidate-start.v1"
CANDIDATE_EXECUTION_REQUEST_SCHEMA_VERSION: Final = (
    "nikodym.readiness.h9r.candidate-execution-request.v1"
)
CANDIDATE_RESULT_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.candidate-result.v2"
CANDIDATE_SERVICE_READY_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.candidate-service-ready.v1"
HTTP_EXCHANGE_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.candidate-http-exchange.v1"
NATIVE_POOLS_PROCESS_OBSERVATION_SCHEMA_VERSION: Final = (
    "nikodym.readiness.h9r.native-pools-process-observation.v1"
)
NATIVE_POOLS_OBSERVATION_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.native-pools-observation.v2"
CONSUMER_OPEN_PROTOCOL_VERSION: Final = "nikodym.readiness.h9r.consumer-open.v1"
CONSUMER_OPEN_REQUEST_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.consumer-open-request.v1"
CONSUMER_OPEN_RESPONSE_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.consumer-open-response.v1"
LAUNCH_BINDING_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.launch-binding.v1"

DERIVABLE_OUTPUT_FORMATS: Final = frozenset(
    output_format for output_format in OUTPUT_FORMAT_COUNTERS if output_format != "bin"
)

# La interfaz binaria está diseñada, pero no hay ningún contador aprobado. Añadir un id aquí
# exigiría una aprobación humana nueva y una implementación independiente hash-bound.
AUTHORIZED_COUNTER_ADAPTER_IDS: Final[frozenset[str]] = frozenset()


@dataclass(frozen=True)
class AdapterSpec:
    """Identidad estática de una frontera ejecutable del protocolo aprobado."""

    flow_id: str
    flow_step: str
    adapter_id: str
    boundary_kind: str


ADAPTER_CATALOG: Final = (
    AdapterSpec("F-SCORE-TRAIN", "train", "nikodym.h9r.score_train.train.v1", "first_open"),
    AdapterSpec("F-SCORE-APPLY", "apply", "nikodym.h9r.score_apply.apply.v1", "first_open"),
    AdapterSpec("F-SCORE-BATCH", "batch", "nikodym.h9r.score_batch.batch.v1", "first_open"),
    AdapterSpec("F-UI", "run", "nikodym.h9r.ui.run.v1", "first_byte"),
    AdapterSpec("F-LGD-BASE", "run", "nikodym.h9r.lgd_base.run.v1", "first_open"),
    AdapterSpec("F-LGD-OOS", "fit", "nikodym.h9r.lgd_oos.fit.v1", "first_open"),
    AdapterSpec("F-LGD-OOS", "apply", "nikodym.h9r.lgd_oos.apply.v1", "first_open"),
    AdapterSpec("F-EAD-BASE", "run", "nikodym.h9r.ead_base.run.v1", "first_open"),
    AdapterSpec("F-EAD-T", "run", "nikodym.h9r.ead_t.run.v1", "first_open"),
    AdapterSpec("F-CMF-REFERENCE", "run", "nikodym.h9r.cmf_reference.run.v1", "first_open"),
    AdapterSpec("F-PD-SURVIVAL", "run", "nikodym.h9r.pd_survival.run.v1", "first_open"),
    AdapterSpec("F-PD-MARKOV", "run", "nikodym.h9r.pd_markov.run.v1", "first_open"),
    AdapterSpec("F-IFRS9", "run", "nikodym.h9r.ifrs9.run.v1", "first_open"),
    AdapterSpec("F-FORWARD-IFRS9", "run", "nikodym.h9r.forward_ifrs9.run.v1", "first_open"),
    AdapterSpec("F-STRESS-ECON", "run", "nikodym.h9r.stress_econ.run.v1", "first_open"),
)
ADAPTER_BY_KEY: Final = {(item.flow_id, item.flow_step): item for item in ADAPTER_CATALOG}
ADAPTER_BY_ID: Final = {item.adapter_id: item for item in ADAPTER_CATALOG}

_catalog_contract = {
    (flow_id, step): adapter_id for (flow_id, step), adapter_id in ADAPTER_IDS.items()
}
if len(ADAPTER_CATALOG) != 15 or ADAPTER_BY_KEY.keys() != _catalog_contract.keys():
    raise RuntimeError("catálogo de adaptadores H9R no contiene exactamente las 15 fronteras")
if any(ADAPTER_BY_KEY[key].adapter_id != value for key, value in _catalog_contract.items()):
    raise RuntimeError("catálogo de adaptadores H9R difiere del contrato de flujos")

_BINDING_FIELDS: Final = (
    "config_hash",
    "candidate_manifest_sha256",
    "fixture_manifest_sha256",
    "tooling_manifest_sha256",
)
_PLACEHOLDERS: Final = frozenset(
    {
        "${BROKERED_INPUTS_JSON}",
        "${STAGING_ROOT}",
        "${ADAPTER_RESULT}",
        "${SERVICE_HOST}",
        "${SERVICE_PORT}",
        "${SERVICE_READY}",
    }
)
_REQUIRED_WRITE_PLACEHOLDERS: Final = frozenset({"${STAGING_ROOT}", "${ADAPTER_RESULT}"})
_BATCH_PLACEHOLDERS: Final = frozenset({"${BROKERED_INPUTS_JSON}"})
_SERVICE_PLACEHOLDERS: Final = frozenset(
    {
        "${SERVICE_HOST}",
        "${SERVICE_PORT}",
        "${SERVICE_READY}",
        "${ATTEMPT_ID}",
        "${CANDIDATE_REQUEST_SHA256}",
    }
)
_CANDIDATE_FORBIDDEN_ENVIRONMENT_KEYS: Final = frozenset(
    {
        "NIKODYM_H9R_OUTPUT_ROOT",
        "NIKODYM_H9R_BOUNDARY_JSONL",
        "NIKODYM_H9R_FILESYSTEM_JSONL",
        "NIKODYM_H9R_NATIVE_POOLS_JSONL",
        "NIKODYM_H9R_ADAPTER_AUDIT_JSONL",
        "NIKODYM_H9R_UI_FIRST_BYTE_JSONL",
        "NIKODYM_H9R_WORKER_CAPABILITY",
        "NIKODYM_H9R_ADAPTER_CAPABILITY",
        "NIKODYM_H9R_CANDIDATE_CAPABILITY",
        "NIKODYM_H9R_UI_CLIENT_CAPABILITY",
    }
)


def _require_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context}: se esperaba un objeto")
    return value


def _require_exact(value: Mapping[str, Any], fields: Sequence[str], *, context: str) -> None:
    expected = set(fields)
    observed = set(value)
    if observed != expected:
        raise ContractError(
            f"{context}: campos faltantes={sorted(expected - observed)!r}, "
            f"extra={sorted(observed - expected)!r}"
        )


def _require_text(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ContractError(f"{context}: texto no vacío inválido")
    return value


def _require_non_negative_int(value: Any, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{context}: entero no negativo inválido")
    return value


def _safe_relative(value: Any, *, context: str, suffix: str | None = None) -> str:
    raw = _require_text(value, context=context)
    relative = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if (
        "\\" in raw
        or relative.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or raw != relative.as_posix()
        or not relative.parts
        or any(part in {"", ".", ".."} or ":" in part for part in relative.parts)
    ):
        raise ContractError(f"{context}: ruta relativa POSIX insegura")
    if suffix is not None and relative.suffix.casefold() != suffix:
        raise ContractError(f"{context}: extensión esperada {suffix!r}")
    return raw


def _absolute_path(value: Any, *, context: str) -> Path:
    raw = _require_text(value, context=context)
    path = Path(raw)
    if not path.is_absolute():
        raise ContractError(f"{context}: se esperaba ruta absoluta")
    absolute = Path(os.path.abspath(path))
    _reject_reparse_ancestors(absolute, context=context)
    return absolute


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _reject_reparse_ancestors(path: Path, *, context: str) -> None:
    """Rechaza el nombre y todo ancestro existente sin seguir el enlace."""
    absolute = Path(os.path.abspath(path))
    for candidate in (absolute, *absolute.parents):
        if (candidate.exists() or os.path.lexists(candidate)) and _is_reparse(candidate):
            raise ContractError(f"{context}: la ruta atraviesa symlink/reparse point: {candidate}")


def _require_plain_directory(path: Path, *, context: str) -> Path:
    absolute = Path(os.path.abspath(path))
    _reject_reparse_ancestors(absolute, context=context)
    if not absolute.is_dir() or _is_reparse(absolute):
        raise ContractError(f"{context}: directorio ausente, symlink o reparse point")
    return absolute


def _plain_tree_inventory(root: Path, *, context: str) -> tuple[list[Path], list[Path]]:
    """Censa archivos/directorios sin atravesar enlaces ni aceptar hardlinks."""
    root = _require_plain_directory(root, context=context)
    pending = [root]
    files: list[Path] = []
    directories: list[Path] = []
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
            if entry.is_symlink() or bool(
                int(getattr(metadata, "st_file_attributes", 0))
                & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            ):
                raise ContractError(f"{context}: contiene symlink/reparse point")
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(candidate)
                pending.append(candidate)
            elif stat.S_ISREG(metadata.st_mode):
                if metadata.st_nlink != 1:
                    raise ContractError(f"{context}: contiene hardlink")
                files.append(candidate)
            else:
                raise ContractError(f"{context}: contiene nodo no regular")
    return (
        sorted(files, key=lambda path: path.relative_to(root).as_posix()),
        sorted(directories, key=lambda path: path.relative_to(root).as_posix()),
    )


def _path_is_within(path: Path, root: Path) -> bool:
    absolute = os.path.normcase(os.path.abspath(path))
    absolute_root = os.path.normcase(os.path.abspath(root))
    try:
        return os.path.commonpath((absolute, absolute_root)) == absolute_root
    except ValueError:
        return False


def _paths_overlap(left: Path, right: Path) -> bool:
    return _path_is_within(left, right) or _path_is_within(right, left)


def _same_file_version(left: os.stat_result, right: os.stat_result) -> bool:
    return bool(
        os.path.samestat(left, right)
        and int(left.st_size) == int(right.st_size)
        and int(getattr(left, "st_mtime_ns", 0)) == int(getattr(right, "st_mtime_ns", 0))
    )


def _open_readonly_no_follow(path: Path) -> BinaryIO:
    """Abre el leaf sin seguir reparse points; el caller liga además lstat↔fstat."""
    if sys.platform == "win32":
        import msvcrt

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
        generic_read = 0x80000000
        file_share_read = 0x00000001
        open_existing = 3
        file_flag_open_reparse_point = 0x00200000
        file_flag_sequential_scan = 0x08000000
        handle = kernel32.CreateFileW(
            str(path),
            generic_read,
            file_share_read,
            None,
            open_existing,
            file_flag_open_reparse_point | file_flag_sequential_scan,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in {None, invalid_handle}:
            code = ctypes.get_last_error()
            raise OSError(code, f"CreateFileW no-follow falló: {path}")
        try:
            descriptor = msvcrt.open_osfhandle(
                int(handle), os.O_RDONLY | getattr(os, "O_BINARY", 0)
            )
        except BaseException:
            kernel32.CloseHandle(handle)
            raise
        return cast(BinaryIO, os.fdopen(descriptor, "rb", closefd=True))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    return cast(BinaryIO, os.fdopen(descriptor, "rb", closefd=True))


def _read_bound_regular_file(
    path: Path,
    *,
    context: str,
    expected_logical_bytes: int,
    expected_sha256: str,
    before_read: Callable[[], None] | None = None,
) -> bytes:
    """Consume una sola versión single-link, con no-follow e identidad causal completa."""
    candidate = Path(os.path.abspath(path))
    _reject_reparse_ancestors(candidate, context=context)
    try:
        parent_before = candidate.parent.lstat()
        before = candidate.lstat()
    except OSError as exc:
        raise ContractError(f"{context}: archivo o parent ausente") from exc
    attributes = int(getattr(before, "st_file_attributes", 0))
    if (
        not stat.S_ISREG(before.st_mode)
        or candidate.is_symlink()
        or bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))
    ):
        raise ContractError(f"{context}: archivo no regular o symlink/reparse point")
    if int(getattr(before, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: hardlink prohibido")
    if int(before.st_size) != expected_logical_bytes:
        raise ContractError(f"{context}: logical_bytes no reconcilia")
    try:
        with _open_readonly_no_follow(candidate) as handle:
            opened = os.fstat(handle.fileno())
            if not _same_file_version(before, opened):
                raise ContractError(f"{context}: identidad cambió antes de leer")
            if int(getattr(opened, "st_nlink", 1)) != 1:
                raise ContractError(f"{context}: descriptor abrió un hardlink")
            if before_read is not None:
                before_read()
            payload = handle.read()
            after_read = os.fstat(handle.fileno())
            if not _same_file_version(opened, after_read) or len(payload) != int(
                after_read.st_size
            ):
                raise ContractError(f"{context}: archivo cambió durante la lectura")
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError(f"{context}: apertura no-follow falló") from exc
    _reject_reparse_ancestors(candidate, context=f"{context}.final")
    try:
        parent_after = candidate.parent.lstat()
        after_path = candidate.lstat()
    except OSError as exc:
        raise ContractError(f"{context}: path desapareció tras la lectura") from exc
    if not os.path.samestat(parent_before, parent_after):
        raise ContractError(f"{context}: parent cambió de identidad")
    if not _same_file_version(before, after_path):
        raise ContractError(f"{context}: path cambió de identidad o versión")
    if int(getattr(after_path, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: path terminó como hardlink")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ContractError(f"{context}: SHA-256 no reconcilia")
    return payload


def _file_identity(
    raw: Any,
    *,
    context: str,
    verify_content: bool,
    root: Path | None = None,
) -> dict[str, Any]:
    entry = _require_mapping(raw, context=context)
    _require_exact(entry, ("path", "logical_bytes", "sha256"), context=context)
    path = _absolute_path(entry["path"], context=f"{context}.path")
    if root is not None and not _path_is_within(path, root):
        raise ContractError(f"{context}: archivo escapa de su raíz")
    if not path.is_file() or _is_reparse(path):
        raise ContractError(f"{context}: archivo ausente, symlink o reparse point")
    metadata = path.stat()
    if metadata.st_nlink != 1:
        raise ContractError(f"{context}: hardlink prohibido")
    logical_bytes = _require_non_negative_int(
        entry["logical_bytes"], context=f"{context}.logical_bytes"
    )
    if metadata.st_size != logical_bytes:
        raise ContractError(f"{context}: logical_bytes no reconcilia")
    expected_sha256 = validate_sha256(entry["sha256"], context=f"{context}.sha256")
    if verify_content and sha256_file(path) != expected_sha256:
        raise ContractError(f"{context}: SHA-256 no reconcilia")
    return {"path": str(path), "logical_bytes": logical_bytes, "sha256": expected_sha256}


def _validate_bindings(raw: Any, *, context: str) -> dict[str, str]:
    bindings = _require_mapping(raw, context=context)
    _require_exact(bindings, _BINDING_FIELDS, context=context)
    return {
        name: validate_sha256(bindings[name], context=f"{context}.{name}")
        for name in _BINDING_FIELDS
    }


def adapter_spec(flow_id: str, flow_step: str) -> AdapterSpec:
    """Resuelve una de las quince fronteras; no deriva ids nuevos por convención."""
    try:
        return ADAPTER_BY_KEY[(flow_id, flow_step)]
    except KeyError as exc:
        raise ContractError(f"adaptador fuera del catálogo: {flow_id}/{flow_step}") from exc


def _validate_protected_contract(raw: Any, *, context: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ContractError(f"{context}: protected debe ser lista no vacía")
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(raw):
        item = _require_mapping(value, context=f"{context}[{index}]")
        _require_exact(
            item,
            ("logical_id", "role", "relative_name", "logical_bytes", "sha256"),
            context=f"{context}[{index}]",
        )
        role = item["role"]
        if role not in {"input", "bundle", "config"}:
            raise ContractError(f"{context}[{index}].role fuera del catálogo")
        relative_name = _safe_relative(
            item["relative_name"], context=f"{context}[{index}].relative_name"
        )
        logical_bytes = _require_non_negative_int(
            item["logical_bytes"], context=f"{context}[{index}].logical_bytes"
        )
        digest = validate_sha256(item["sha256"], context=f"{context}[{index}].sha256")
        logical_id = validate_sha256(item["logical_id"], context=f"{context}[{index}].logical_id")
        expected_id = canonical_json_sha256(
            {
                "role": role,
                "relative_name": relative_name,
                "logical_bytes": logical_bytes,
                "sha256": digest,
            }
        )
        if logical_id != expected_id:
            raise ContractError(f"{context}[{index}].logical_id no deriva de la identidad")
        normalized.append(
            {
                "logical_id": logical_id,
                "role": role,
                "relative_name": relative_name,
                "logical_bytes": logical_bytes,
                "sha256": digest,
            }
        )
    logical_ids = [str(item["logical_id"]) for item in normalized]
    if logical_ids != sorted(set(logical_ids)):
        raise ContractError(f"{context}: protected está duplicado o fuera de orden")
    return normalized


def _validate_input_contract(raw: Any, *, context: str) -> dict[str, Any]:
    contract = _require_mapping(raw, context=context)
    _require_exact(
        contract,
        ("protocol_version", "protected", "max_open_requests"),
        context=context,
    )
    if (
        contract["protocol_version"] != CONSUMER_OPEN_PROTOCOL_VERSION
        or contract["max_open_requests"] != 1
    ):
        raise ContractError(f"{context}: protocolo/cardinalidad OPEN inválidos")
    return {
        "protocol_version": CONSUMER_OPEN_PROTOCOL_VERSION,
        "protected": _validate_protected_contract(
            contract["protected"], context=f"{context}.protected"
        ),
        "max_open_requests": 1,
    }


def _validate_service_contract(raw: Any, *, expected_outputs: Sequence[str]) -> dict[str, Any]:
    service = _require_mapping(raw, context="adapter.service")
    _require_exact(
        service,
        ("host", "port", "ready_timeout_seconds", "first_page_oracle"),
        context="adapter.service",
    )
    if service["host"] != "127.0.0.1":
        raise ContractError("adapter.service.host debe ser loopback IPv4 exacto")
    port = service["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ContractError("adapter.service.port inválido")
    timeout = service["ready_timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise ContractError("adapter.service.ready_timeout_seconds inválido")
    oracle = _require_mapping(
        service["first_page_oracle"], context="adapter.service.first_page_oracle"
    )
    _require_exact(
        oracle,
        (
            "kind",
            "expected_status",
            "content_type",
            "response_body_bytes",
            "response_body_sha256",
            "first_verifiable_page",
        ),
        context="adapter.service.first_page_oracle",
    )
    if oracle["kind"] != "response-body-sha256-v1":
        raise ContractError("first_page_oracle.kind fuera del catálogo")
    status = oracle["expected_status"]
    if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status <= 299:
        raise ContractError("first_page_oracle.expected_status inválido")
    content_type = _require_text(oracle["content_type"], context="first_page_oracle.content_type")
    response_bytes = _require_non_negative_int(
        oracle["response_body_bytes"], context="first_page_oracle.response_body_bytes"
    )
    response_sha = validate_sha256(
        oracle["response_body_sha256"], context="first_page_oracle.response_body_sha256"
    )
    page = _require_mapping(
        oracle["first_verifiable_page"], context="first_page_oracle.first_verifiable_page"
    )
    _require_exact(
        page,
        ("identity", "relative_path", "logical_bytes", "sha256"),
        context="first_page_oracle.first_verifiable_page",
    )
    identity = _require_text(page["identity"], context="first_page_oracle.page.identity")
    if identity not in expected_outputs:
        raise ContractError("first_page_oracle page no pertenece a outputs esperados")
    return {
        "host": "127.0.0.1",
        "port": port,
        "ready_timeout_seconds": float(timeout),
        "first_page_oracle": {
            "kind": "response-body-sha256-v1",
            "expected_status": status,
            "content_type": content_type,
            "response_body_bytes": response_bytes,
            "response_body_sha256": response_sha,
            "first_verifiable_page": {
                "identity": identity,
                "relative_path": _safe_relative(
                    page["relative_path"], context="first_page_oracle.page.relative_path"
                ),
                "logical_bytes": _require_non_negative_int(
                    page["logical_bytes"], context="first_page_oracle.page.logical_bytes"
                ),
                "sha256": validate_sha256(page["sha256"], context="first_page_oracle.page.sha256"),
            },
        },
    }


def validate_adapter_descriptor(
    raw: Mapping[str, Any],
    *,
    candidate_root: Path,
    expected_flow_id: str,
    expected_flow_step: str,
    expected_bindings: Mapping[str, str],
) -> dict[str, Any]:
    """Valida un script exacto; nunca acepta módulos, entrypoints o comandos libres."""
    descriptor = dict(raw)
    _require_exact(
        descriptor,
        (
            "schema_version",
            "attempt_id",
            "unit",
            "adapter_id",
            "flow_id",
            "flow_step",
            "boundary_kind",
            "bindings",
            "input_contract",
            "implementation",
            "expected",
        ),
        context="adapter descriptor",
    )
    if descriptor["schema_version"] != ADAPTER_DESCRIPTOR_SCHEMA_VERSION:
        raise ContractError("adapter descriptor usa otro schema")
    descriptor_attempt_id = validate_sha256(
        descriptor["attempt_id"], context="adapter descriptor.attempt_id"
    )
    unit = validate_attempt_unit(
        _require_mapping(descriptor["unit"], context="adapter descriptor.unit")
    )
    if derive_attempt_id(unit) != descriptor_attempt_id:
        raise ContractError("adapter descriptor no liga attempt_id y unidad exacta")
    if (
        unit["flow_id"] != expected_flow_id
        or unit["flow_step"] != expected_flow_step
        or unit["candidate_manifest_sha256"] != expected_bindings["candidate_manifest_sha256"]
        or unit["fixture_manifest_sha256"] != expected_bindings["fixture_manifest_sha256"]
        or unit["config_hash"] != expected_bindings["config_hash"]
    ):
        raise ContractError("unidad del descriptor no reconcilia con frontera/bindings")
    spec = adapter_spec(expected_flow_id, expected_flow_step)
    if (
        descriptor["flow_id"] != spec.flow_id
        or descriptor["flow_step"] != spec.flow_step
        or descriptor["adapter_id"] != spec.adapter_id
        or descriptor["boundary_kind"] != spec.boundary_kind
    ):
        raise ContractError("adapter descriptor no coincide con la frontera cerrada")
    bindings = _validate_bindings(descriptor["bindings"], context="adapter.bindings")
    if bindings != dict(expected_bindings):
        raise ContractError("adapter descriptor no está ligado a config/candidate/tooling")
    input_contract = _validate_input_contract(
        descriptor["input_contract"], context="adapter.input_contract"
    )
    expected_identities = list(flow_spec(spec.flow_id, spec.flow_step).expected_output_identities)
    expected = _require_mapping(descriptor["expected"], context="adapter descriptor.expected")
    _require_exact(
        expected,
        ("identities", "counts", "golden_sha256"),
        context="adapter descriptor.expected",
    )
    if expected["identities"] != expected_identities:
        raise ContractError("adapter descriptor no declara los outputs exactos del flujo")
    counts_raw = _require_mapping(expected["counts"], context="adapter descriptor.expected.counts")
    if set(counts_raw) != set(expected_identities):
        raise ContractError("descriptor expected.counts no cubre los outputs exactos")
    expected_normalized = {
        "identities": expected_identities,
        "counts": {
            identity: _require_non_negative_int(
                counts_raw[identity], context=f"adapter descriptor.expected.counts.{identity}"
            )
            for identity in expected_identities
        },
        "golden_sha256": validate_sha256(
            expected["golden_sha256"], context="adapter descriptor.expected.golden_sha256"
        ),
    }
    implementation = _require_mapping(
        descriptor["implementation"], context="adapter.implementation"
    )
    expected_kind = (
        "candidate_http_service"
        if spec.boundary_kind == "first_byte"
        else "candidate_brokered_script"
    )
    expected_implementation_fields = (
        "kind",
        "script",
        "argv_template",
        "isolation_flags",
        *(("service",) if expected_kind == "candidate_http_service" else ()),
    )
    _require_exact(
        implementation,
        expected_implementation_fields,
        context="adapter.implementation",
    )
    if implementation["kind"] != expected_kind:
        raise ContractError(f"adapter exige implementation.kind={expected_kind}")
    if implementation["isolation_flags"] != ["-I", "-B", "-S"]:
        raise ContractError("adapter implementation no declara -I -B -S exacto")
    script = _require_mapping(implementation["script"], context="adapter.script")
    _require_exact(script, ("relative_path", "bytes", "sha256"), context="adapter.script")
    relative_script = _safe_relative(
        script["relative_path"], context="adapter.script.relative_path", suffix=".py"
    )
    script_path = (candidate_root / Path(relative_script)).resolve(strict=False)
    if not _path_is_within(script_path, candidate_root):
        raise ContractError("script del adapter escapa del árbol candidato")
    normalized_script = _file_identity(
        {
            "path": str(script_path),
            "logical_bytes": script["bytes"],
            "sha256": script["sha256"],
        },
        context="adapter.script",
        verify_content=True,
        root=candidate_root,
    )
    argv_template = implementation["argv_template"]
    if not isinstance(argv_template, list) or not all(
        isinstance(argument, str) and argument and "\x00" not in argument
        for argument in argv_template
    ):
        raise ContractError("adapter.argv_template no es una lista cerrada de textos")
    placeholders: list[str] = []
    for argument in argv_template:
        if "${" in argument:
            if argument not in _PLACEHOLDERS:
                raise ContractError(f"placeholder de adapter no permitido: {argument!r}")
            placeholders.append(argument)
        elif Path(argument).is_absolute():
            raise ContractError("argv literal no puede introducir una ruta absoluta")
    if not _REQUIRED_WRITE_PLACEHOLDERS.issubset(placeholders):
        raise ContractError("adapter debe recibir staging y adapter-result")
    if any(placeholders.count(item) != 1 for item in _REQUIRED_WRITE_PLACEHOLDERS):
        raise ContractError("staging/adapter-result deben aparecer exactamente una vez")
    placeholder_set = frozenset(placeholders)
    if expected_kind == "candidate_brokered_script":
        if not _BATCH_PLACEHOLDERS.issubset(placeholder_set) or _SERVICE_PLACEHOLDERS.intersection(
            placeholder_set
        ):
            raise ContractError("adapter batch exige brokered-inputs y prohíbe placeholders UI")
        service = None
    else:
        if not _SERVICE_PLACEHOLDERS.issubset(placeholder_set) or _BATCH_PLACEHOLDERS.intersection(
            placeholder_set
        ):
            raise ContractError("adapter UI exige host/port/ready y prohíbe brokered-inputs")
        service = _validate_service_contract(
            implementation["service"], expected_outputs=expected_identities
        )
    return {
        **descriptor,
        "attempt_id": descriptor_attempt_id,
        "unit": unit,
        "bindings": bindings,
        "input_contract": input_contract,
        "implementation": {
            "kind": expected_kind,
            "script": {
                "relative_path": relative_script,
                "bytes": script["bytes"],
                "sha256": script["sha256"],
                "path": normalized_script["path"],
            },
            "argv_template": list(argv_template),
            "isolation_flags": ["-I", "-B", "-S"],
            **({"service": service} if service is not None else {}),
        },
        "expected": expected_normalized,
    }


def _validate_launch_material(raw: Any) -> dict[str, Any]:
    material = _require_mapping(raw, context="candidate.launch_material")
    _require_exact(
        material,
        (
            "schema_version",
            "protocol_version",
            "attempt_id",
            "unit",
            "adapter_descriptor_sha256",
            "harness_runtime_snapshot_sha256",
            "candidate_manifest_sha256",
            "fixture_manifest_sha256",
            "config_hash",
            "tooling_manifest_sha256",
            "workdir_sha256",
            "paths",
        ),
        context="candidate.launch_material",
    )
    if material["schema_version"] != LAUNCH_BINDING_SCHEMA_VERSION:
        raise ContractError("candidate launch_material usa otro schema")
    if material["protocol_version"] != PROTOCOL_VERSION:
        raise ContractError("candidate launch_material usa otro protocolo")
    unit = validate_attempt_unit(
        _require_mapping(material["unit"], context="candidate.launch_material.unit")
    )
    attempt = validate_sha256(
        material["attempt_id"], context="candidate.launch_material.attempt_id"
    )
    if derive_attempt_id(unit) != attempt:
        raise ContractError("candidate launch_material no liga unidad/attempt_id")
    for name in (
        "adapter_descriptor_sha256",
        "harness_runtime_snapshot_sha256",
        "candidate_manifest_sha256",
        "fixture_manifest_sha256",
        "config_hash",
        "tooling_manifest_sha256",
        "workdir_sha256",
    ):
        validate_sha256(material[name], context=f"candidate.launch_material.{name}")
    if (
        material["candidate_manifest_sha256"] != unit["candidate_manifest_sha256"]
        or material["fixture_manifest_sha256"] != unit["fixture_manifest_sha256"]
        or material["config_hash"] != unit["config_hash"]
    ):
        raise ContractError("candidate launch_material no liga hashes de unidad")
    paths = _require_mapping(material["paths"], context="candidate.launch_material.paths")
    _require_exact(
        paths,
        (
            "staging",
            "candidate_outputs",
            "adapter_result",
            "candidate_stdout",
            "candidate_stderr",
            "candidate_controller_stdout",
            "candidate_controller_stderr",
            "candidate_start",
            "candidate_result",
        ),
        context="candidate.launch_material.paths",
    )
    normalized_paths = {
        name: str(_absolute_path(paths[name], context=f"candidate.launch_material.paths.{name}"))
        for name in paths
    }
    if len(set(normalized_paths.values())) != len(normalized_paths):
        raise ContractError("candidate launch_material paths se solapan")
    return {**material, "attempt_id": attempt, "unit": unit, "paths": normalized_paths}


def _validate_candidate_broker(
    raw: Any, *, attempt_id: str, contract: Mapping[str, Any]
) -> dict[str, Any]:
    broker = _require_mapping(raw, context="candidate.broker")
    _require_exact(
        broker,
        (
            "protocol_version",
            "host",
            "port",
            "nonce",
            "nonce_commitment_sha256",
            "request_id",
        ),
        context="candidate.broker",
    )
    if (
        broker["protocol_version"] != CONSUMER_OPEN_PROTOCOL_VERSION
        or broker["host"] != "127.0.0.1"
    ):
        raise ContractError("candidate broker protocolo/host inválido")
    port = broker["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ContractError("candidate broker port inválido")
    nonce = broker["nonce"]
    if (
        not isinstance(nonce, str)
        or len(nonce) != 64
        or any(character not in "0123456789abcdef" for character in nonce)
        or nonce in {"0" * 64, "f" * 64}
    ):
        raise ContractError("candidate broker nonce inválido")
    commitment = validate_sha256(
        broker["nonce_commitment_sha256"], context="candidate.broker.nonce_commitment"
    )
    if commitment != hashlib.sha256(bytes.fromhex(nonce)).hexdigest():
        raise ContractError("candidate broker nonce commitment no deriva del secreto")
    protected = list(cast(Sequence[Mapping[str, Any]], contract["protected"]))
    request_id = validate_sha256(broker["request_id"], context="candidate.broker.request_id")
    if request_id != canonical_json_sha256(
        {"attempt_id": attempt_id, "operation": "OPEN", "protected": protected}
    ):
        raise ContractError("candidate broker request_id no deriva del OPEN exacto")
    return {
        "protocol_version": CONSUMER_OPEN_PROTOCOL_VERSION,
        "host": "127.0.0.1",
        "port": port,
        "nonce": nonce,
        "nonce_commitment_sha256": commitment,
        "request_id": request_id,
    }


def _validate_candidate_service_launch(raw: Any) -> dict[str, Any]:
    service = _require_mapping(raw, context="candidate.service")
    _require_exact(service, ("host", "port", "ready_timeout_seconds"), context="candidate.service")
    if service["host"] != "127.0.0.1":
        raise ContractError("candidate service host debe ser loopback IPv4")
    port = service["port"]
    timeout = service["ready_timeout_seconds"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ContractError("candidate service port inválido")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise ContractError("candidate service ready_timeout_seconds inválido")
    return {"host": "127.0.0.1", "port": port, "ready_timeout_seconds": float(timeout)}


def validate_candidate_launch_request(
    raw: Mapping[str, Any], *, require_fresh_pycache: bool = True
) -> dict[str, Any]:
    """Valida el request del child cleanroom; nunca abre inputs ni ejecuta el candidato."""
    request = dict(raw)
    _require_exact(
        request,
        (
            "schema_version",
            "attempt_id",
            "mode",
            "bindings",
            "launch_material",
            "script",
            "runtime",
            "input_contract",
            "broker",
            "paths",
            "argv_template",
            "service",
            "workload_deadline_seconds",
        ),
        context="candidate request",
    )
    if request["schema_version"] != CANDIDATE_REQUEST_SCHEMA_VERSION:
        raise ContractError("candidate request usa otro schema")
    attempt = validate_sha256(request["attempt_id"], context="candidate.attempt_id")
    mode = request["mode"]
    if mode not in {"batch", "http-service"}:
        raise ContractError("candidate.mode fuera del catálogo")
    launch_material = _validate_launch_material(request["launch_material"])
    if launch_material["attempt_id"] != attempt:
        raise ContractError("candidate request y launch_material difieren en attempt_id")
    workload_deadline_seconds = request["workload_deadline_seconds"]
    expected_workload_deadline = flow_spec(
        str(cast(dict[str, Any], launch_material["unit"])["flow_id"]),
        str(cast(dict[str, Any], launch_material["unit"])["flow_step"]),
    ).workload_deadline_seconds
    if (
        isinstance(workload_deadline_seconds, bool)
        or not isinstance(workload_deadline_seconds, (int, float))
        or float(workload_deadline_seconds) != expected_workload_deadline
    ):
        raise ContractError("candidate workload_deadline_seconds no deriva del flujo")
    bindings = _require_mapping(request["bindings"], context="candidate.bindings")
    _require_exact(
        bindings,
        ("launch_binding_sha256", "harness_runtime_snapshot_sha256"),
        context="candidate.bindings",
    )
    launch_sha = validate_sha256(
        bindings["launch_binding_sha256"], context="candidate.bindings.launch_binding_sha256"
    )
    snapshot_sha = validate_sha256(
        bindings["harness_runtime_snapshot_sha256"],
        context="candidate.bindings.harness_runtime_snapshot_sha256",
    )
    if (
        launch_sha != canonical_json_sha256(launch_material)
        or snapshot_sha != launch_material["harness_runtime_snapshot_sha256"]
    ):
        raise ContractError("candidate bindings no derivan del launch_material")
    runtime = _validate_runtime_paths(request["runtime"], include_job_limits=True)
    memory_bytes = runtime["job_memory_commit_limit_bytes"]
    affinity_mask = runtime["affinity_mask"]
    script = _require_mapping(request["script"], context="candidate.script")
    _require_exact(script, ("relative_path", "logical_bytes", "sha256"), context="candidate.script")
    relative_script = _safe_relative(
        script["relative_path"], context="candidate.script.relative_path", suffix=".py"
    )
    script_path = (cast(Path, runtime["candidate_root"]) / relative_script).resolve(strict=False)
    script_identity = _file_identity(
        {
            "path": str(script_path),
            "logical_bytes": script["logical_bytes"],
            "sha256": script["sha256"],
        },
        context="candidate.script",
        verify_content=True,
        root=cast(Path, runtime["candidate_root"]),
    )
    input_contract = _validate_input_contract(
        request["input_contract"], context="candidate.input_contract"
    )
    paths = _require_mapping(request["paths"], context="candidate.paths")
    _require_exact(
        paths,
        (
            "staging",
            "candidate_outputs",
            "adapter_result",
            "brokered_inputs_json",
            "pycache",
            "stdout",
            "stderr",
            "controller_stdout",
            "controller_stderr",
            "service_ready",
            "candidate_start",
            "candidate_result",
        ),
        context="candidate.paths",
    )
    normalized_paths = {
        name: _absolute_path(value, context=f"candidate.paths.{name}")
        for name, value in paths.items()
    }
    staging = normalized_paths["staging"]
    if normalized_paths["candidate_outputs"] != staging / "candidate-outputs.json":
        raise ContractError("candidate outputs no deriva del staging cerrado")
    control_root = normalized_paths["candidate_start"].parent
    workdir = staging.parent.parent
    candidate_runtime_root = workdir / "scratch" / "candidate-runtime"
    if (
        normalized_paths["brokered_inputs_json"] != candidate_runtime_root / "brokered-inputs.json"
        or normalized_paths["service_ready"] != candidate_runtime_root / "service-ready.json"
        or normalized_paths["candidate_start"] != control_root / "candidate-start.json"
        or normalized_paths["candidate_result"] != control_root / "candidate-result.json"
        or normalized_paths["adapter_result"] != control_root / "adapter-result.json"
        or control_root != staging.parent.parent / "telemetry" / "control"
        or normalized_paths["pycache"] != workdir / "scratch" / "python-cache" / "candidate-child"
        or normalized_paths["stdout"] != workdir / "telemetry" / "candidate.stdout.bin"
        or normalized_paths["stderr"] != workdir / "telemetry" / "candidate.stderr.bin"
        or normalized_paths["controller_stdout"]
        != workdir / "telemetry" / "candidate-controller.stdout.bin"
        or normalized_paths["controller_stderr"]
        != workdir / "telemetry" / "candidate-controller.stderr.bin"
    ):
        raise ContractError("candidate start/result no derivan del control root cerrado")
    pycache = normalized_paths["pycache"]
    if not pycache.is_dir() or _is_reparse(pycache):
        raise ContractError("candidate child pycache_prefix no está presente/seguro")
    if require_fresh_pycache and any(pycache.iterdir()):
        raise ContractError("candidate child pycache_prefix no está fresco/vacío")
    launch_paths = cast(dict[str, str], launch_material["paths"])
    if {
        "staging": str(staging),
        "candidate_outputs": str(normalized_paths["candidate_outputs"]),
        "adapter_result": str(normalized_paths["adapter_result"]),
        "candidate_stdout": str(normalized_paths["stdout"]),
        "candidate_stderr": str(normalized_paths["stderr"]),
        "candidate_controller_stdout": str(normalized_paths["controller_stdout"]),
        "candidate_controller_stderr": str(normalized_paths["controller_stderr"]),
        "candidate_start": str(normalized_paths["candidate_start"]),
        "candidate_result": str(normalized_paths["candidate_result"]),
    } != launch_paths:
        raise ContractError("candidate paths no reconcilian launch_binding")
    argv = request["argv_template"]
    if not isinstance(argv, list) or not all(
        isinstance(item, str) and item and "\x00" not in item for item in argv
    ):
        raise ContractError("candidate argv_template inválido")
    allowed_placeholders = _REQUIRED_WRITE_PLACEHOLDERS | (
        _BATCH_PLACEHOLDERS if mode == "batch" else _SERVICE_PLACEHOLDERS
    )
    observed_placeholders = {item for item in argv if item.startswith("${")}
    if observed_placeholders != allowed_placeholders or any(
        argv.count(item) != 1 for item in allowed_placeholders
    ):
        raise ContractError("candidate argv_template no contiene placeholders exactos")
    if any(Path(item).is_absolute() for item in argv if not item.startswith("${")):
        raise ContractError("candidate argv literal no puede ser ruta absoluta")
    broker: dict[str, Any] | None
    service: dict[str, Any] | None
    if mode == "batch":
        if request["service"] is not None:
            raise ContractError("candidate batch prohíbe service")
        broker = _validate_candidate_broker(
            request["broker"], attempt_id=attempt, contract=input_contract
        )
        service = None
    else:
        if request["broker"] is not None:
            raise ContractError("candidate http-service prohíbe broker OPEN")
        service = _validate_candidate_service_launch(request["service"])
        broker = None
    return {
        "schema_version": CANDIDATE_REQUEST_SCHEMA_VERSION,
        "candidate_request_sha256": canonical_json_sha256(request),
        "attempt_id": attempt,
        "mode": mode,
        "bindings": {
            "launch_binding_sha256": launch_sha,
            "harness_runtime_snapshot_sha256": snapshot_sha,
        },
        "launch_material": launch_material,
        "script": {
            "relative_path": relative_script,
            "logical_bytes": script_identity["logical_bytes"],
            "sha256": script_identity["sha256"],
            "path": script_identity["path"],
        },
        "runtime": {
            **runtime,
            "job_memory_commit_limit_bytes": memory_bytes,
            "affinity_mask": affinity_mask,
        },
        "input_contract": input_contract,
        "broker": broker,
        "paths": normalized_paths,
        "argv_template": list(argv),
        "service": service,
        "workload_deadline_seconds": float(workload_deadline_seconds),
    }


def _validate_candidate_controller_launch(
    raw: Any,
    *,
    expected_attempt_id: str,
    expected_tooling_manifest_sha256: str,
    require_fresh_candidate_pycache: bool,
) -> dict[str, Any]:
    launch = _require_mapping(raw, context="adapter.candidate_launch")
    _require_exact(
        launch,
        (
            "python_executable",
            "driver",
            "candidate_request",
            "candidate_request_payload_sha256",
            "capability_commitment_sha256",
            "authorization_gate_path",
            "trusted_authority_public_key_path",
            "harness_runtime_snapshot",
        ),
        context="adapter.candidate_launch",
    )
    python_identity = _file_identity(
        launch["python_executable"],
        context="adapter.candidate_launch.python_executable",
        verify_content=True,
    )
    driver_identity = _file_identity(
        launch["driver"], context="adapter.candidate_launch.driver", verify_content=True
    )
    driver_path = Path(cast(str, driver_identity["path"]))
    if driver_path.name != "measure_readiness_h9r.py":
        raise ContractError("candidate launch driver no es el driver H9R cerrado")
    request_identity = _file_identity(
        launch["candidate_request"],
        context="adapter.candidate_launch.candidate_request",
        verify_content=True,
    )
    request_path = Path(cast(str, request_identity["path"]))
    request_value = read_json_object(request_path)
    if request_path.read_bytes() != canonical_json_bytes(request_value) + b"\n":
        raise ContractError("candidate request del launch no es JSON canónico exacto")
    payload_sha = validate_sha256(
        launch["candidate_request_payload_sha256"],
        context="adapter.candidate_launch.request_payload_sha256",
    )
    if canonical_json_sha256(request_value) != payload_sha:
        raise ContractError("candidate launch no liga payload del request")
    candidate_request = validate_candidate_launch_request(
        request_value, require_fresh_pycache=require_fresh_candidate_pycache
    )
    if candidate_request["attempt_id"] != expected_attempt_id:
        raise ContractError("candidate launch no liga attempt_id del adapter")
    snapshot_identity = _file_identity(
        launch["harness_runtime_snapshot"],
        context="adapter.candidate_launch.harness_runtime_snapshot",
        verify_content=True,
    )
    snapshot_path = Path(cast(str, snapshot_identity["path"]))
    snapshot = validate_harness_source_snapshot(
        manifest_path=snapshot_path,
        expected_manifest_sha256=cast(str, snapshot_identity["sha256"]),
        expected_source_tooling_manifest_sha256=expected_tooling_manifest_sha256,
    )
    if (
        cast(dict[str, Any], candidate_request["bindings"])["harness_runtime_snapshot_sha256"]
        != snapshot_identity["sha256"]
    ):
        raise ContractError("candidate request no liga snapshot del controller")
    gate_path = _absolute_path(
        launch["authorization_gate_path"], context="adapter.candidate_launch.gate"
    )
    trusted_key = _absolute_path(
        launch["trusted_authority_public_key_path"],
        context="adapter.candidate_launch.trusted_key",
    )
    capability = validate_sha256(
        launch["capability_commitment_sha256"],
        context="adapter.candidate_launch.capability_commitment_sha256",
    )
    return {
        "python_executable": python_identity,
        "driver": driver_identity,
        "candidate_request": request_identity,
        "candidate_request_payload_sha256": payload_sha,
        "capability_commitment_sha256": capability,
        "authorization_gate_path": gate_path,
        "trusted_authority_public_key_path": trusted_key,
        "harness_runtime_snapshot": snapshot_identity,
        "harness_runtime_snapshot_value": snapshot["value"],
        "candidate_request_value": candidate_request,
    }


_CANDIDATE_BOOTSTRAP = r"""
import json, os, runpy, socket, sys, threading

request_path = os.environ.pop("NIKODYM_H9R_CANDIDATE_REQUEST", None)
request_sha = os.environ.pop("NIKODYM_H9R_CANDIDATE_REQUEST_SHA256", None)
if request_path is None or request_sha is None:
    raise SystemExit("candidate bootstrap sin request")
import hashlib
raw = open(request_path, "rb").read()
if hashlib.sha256(raw).hexdigest() != request_sha:
    raise SystemExit("candidate request cambió")
request = json.loads(raw)
canonical = json.dumps(
    request,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
if raw != canonical + b"\n":
    raise SystemExit("candidate request no canónico")
paths = request["paths"]
observer = request["observer"]
sys.path.insert(0, observer["threadpoolctl_import_root"])
from threadpoolctl import threadpool_info as _trusted_threadpool_info
sys.path.pop(0)
replacements = {
    "${STAGING_ROOT}": paths["staging"],
    "${ADAPTER_RESULT}": paths["candidate_outputs"],
}
if request["mode"] == "batch":
    broker = request["broker"]
    wire = {
        "schema_version": "nikodym.readiness.h9r.consumer-open-request.v1",
        "attempt_id": request["attempt_id"],
        "operation": "OPEN",
        "request_id": broker["request_id"],
        "nonce": broker["nonce"],
        "protected": request["input_contract"]["protected"],
    }
    payload = json.dumps(
        wire,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    with socket.create_connection((broker["host"], broker["port"]), timeout=30.0) as connection:
        connection.sendall(payload)
        response = b""
        while not response.endswith(b"\n"):
            chunk = connection.recv(1024 * 1024)
            if not chunk:
                raise SystemExit("broker response truncado")
            response += chunk
    opened = json.loads(response)
    if opened["request_id"] != broker["request_id"]:
        raise SystemExit("broker response request_id distinto")
    brokered_path = paths["brokered_inputs_json"]
    with open(brokered_path, "xb") as handle:
        opened_payload = json.dumps(
            opened,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        handle.write(opened_payload + b"\n")
        handle.flush(); os.fsync(handle.fileno())
    replacements["${BROKERED_INPUTS_JSON}"] = brokered_path
else:
    service = request["service"]
    replacements.update({
        "${SERVICE_HOST}": service["host"],
        "${SERVICE_PORT}": str(service["port"]),
        "${SERVICE_READY}": paths["service_ready"],
        "${ATTEMPT_ID}": request["attempt_id"],
        "${CANDIDATE_REQUEST_SHA256}": request["candidate_request_sha256"],
    })
argv = [replacements.get(item, item) for item in request["argv_template"]]
for key in list(os.environ):
    if key.startswith("NIKODYM_H9R_"):
        raise SystemExit("entorno candidato filtró variable H9R reservada")
sys.argv = [request["script_path"], *argv]
sys.path[:] = [request["candidate_root"], *[item for item in sys.path if item]]
os.chdir(paths["staging"])
try:
    runpy.run_path(request["script_path"], run_name="__main__")
finally:
    observed = []
    seen = set()
    for raw_pool in _trusted_threadpool_info():
        library = raw_pool.get("internal_api") or raw_pool.get("prefix")
        version = raw_pool.get("version")
        threading_layer = raw_pool.get("threading_layer") or raw_pool.get("user_api")
        effective_threads = raw_pool.get("num_threads")
        identity = (library, version, threading_layer)
        if (
            not isinstance(library, str) or not library
            or not isinstance(version, str)
            or not isinstance(threading_layer, str)
            or isinstance(effective_threads, bool)
            or not isinstance(effective_threads, int)
            or not 1 <= effective_threads <= 4
            or identity in seen
        ):
            raise SystemExit("native pool observado no es cerrado/efectivo")
        seen.add(identity)
        observed.append({
            "library": library,
            "version": version,
            "threading_layer": threading_layer,
            "effective_threads": effective_threads,
        })
    observed.sort(key=lambda item: (
        item["library"], item["version"], item["threading_layer"]
    ))
    pool_keys = (
        "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
    )
    import ctypes
    class _FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]
        def value(self):
            return (int(self.high) << 32) | int(self.low)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_bool
    creation = _FileTime(); exit_time = _FileTime()
    kernel = _FileTime(); user = _FileTime()
    if not kernel32.GetProcessTimes(
        kernel32.GetCurrentProcess(),
        ctypes.byref(creation), ctypes.byref(exit_time),
        ctypes.byref(kernel), ctypes.byref(user),
    ):
        raise SystemExit("GetProcessTimes falló en observer candidate")
    pid = os.getpid()
    creation_time = creation.value()
    payload = {
        "schema_version": "nikodym.readiness.h9r.native-pools-process-observation.v1",
        "candidate_execution_request_sha256": request_sha,
        "pid": pid,
        "creation_time_100ns": creation_time,
        "environment": {key: os.environ.get(key) for key in pool_keys},
        "libraries": observed,
        "process_thread_count": threading.active_count(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    observation_path = os.path.join(
        observer["native_pools_root"],
        f"process-{pid}-{creation_time}.json",
    )
    with open(observation_path, "xb") as handle:
        handle.write(encoded); handle.flush(); os.fsync(handle.fileno())
"""


def _candidate_child_environment(
    request_path: Path,
    request_sha256: str,
    *,
    temp_root: Path,
    logical_cpu_count: int,
) -> dict[str, str]:
    """Construye allowlist; no hereda secrets, sidecars ni OUTPUT_ROOT del harness."""
    allowed_names = {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
    }
    environment = {
        name: value for name in sorted(allowed_names) if (value := os.environ.get(name)) is not None
    }
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    environment["PYTHONHASHSEED"] = "0"
    environment["TEMP"] = str(temp_root)
    environment["TMP"] = str(temp_root)
    environment["NUMBER_OF_PROCESSORS"] = str(logical_cpu_count)
    environment["NIKODYM_H9R_CANDIDATE_REQUEST"] = str(request_path.resolve())
    environment["NIKODYM_H9R_CANDIDATE_REQUEST_SHA256"] = request_sha256
    return environment


def candidate_execution_request(
    normalized: Mapping[str, Any], *, harness_runtime_snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Serializa sólo material que el child cleanroom necesita, sin autoridad/publisher."""
    runtime = cast(Mapping[str, Any], normalized["runtime"])
    script = cast(Mapping[str, Any], normalized["script"])
    paths = cast(Mapping[str, Path], normalized["paths"])
    broker = normalized["broker"]
    service = normalized["service"]
    roots = {
        str(item["name"]): item
        for item in cast(list[dict[str, Any]], harness_runtime_snapshot["import_roots"])
    }
    threadpoolctl_root = _require_mapping(
        roots.get("threadpoolctl"), context="candidate observer.threadpoolctl"
    )
    return {
        "schema_version": CANDIDATE_EXECUTION_REQUEST_SCHEMA_VERSION,
        "attempt_id": normalized["attempt_id"],
        "candidate_request_sha256": normalized["candidate_request_sha256"],
        "mode": normalized["mode"],
        "script_path": script["path"],
        "candidate_root": str(cast(Path, runtime["candidate_root"])),
        "script": {name: script[name] for name in ("relative_path", "logical_bytes", "sha256")},
        "input_contract": normalized["input_contract"],
        "broker": broker,
        "paths": {
            name: str(paths[name])
            for name in (
                "staging",
                "candidate_outputs",
                "brokered_inputs_json",
                "service_ready",
            )
        },
        "argv_template": normalized["argv_template"],
        "service": service,
        "observer": {
            "threadpoolctl_import_root": threadpoolctl_root["path"],
            "native_pools_root": str(paths["brokered_inputs_json"].parent / "native-pools"),
        },
    }


def _validate_native_pool_process_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    pool_keys = {
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    }
    environment = _require_mapping(
        value["environment"], context="candidate native-pools environment"
    )
    if set(environment) != pool_keys or any(
        not isinstance(item, str) or not item.isdigit() or not 1 <= int(item) <= 4
        for item in environment.values()
    ):
        raise ContractError("native-pools observation no acredita variables 1…4")
    raw_libraries = value["libraries"]
    if not isinstance(raw_libraries, list):
        raise ContractError("native-pools observation libraries no es lista")
    libraries: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_libraries):
        library = _require_mapping(raw, context=f"candidate native-pools libraries[{index}]")
        _require_exact(
            library,
            ("library", "version", "threading_layer", "effective_threads"),
            context=f"candidate native-pools libraries[{index}]",
        )
        effective = library["effective_threads"]
        raw_identity = (library["library"], library["version"], library["threading_layer"])
        if not all(isinstance(item, str) and item for item in raw_identity):
            raise ContractError("native-pools observation contiene identidad inválida")
        identity = cast(tuple[str, str, str], raw_identity)
        if (
            isinstance(effective, bool)
            or not isinstance(effective, int)
            or not 1 <= effective <= 4
            or identity in identities
        ):
            raise ContractError("native-pools observation contiene biblioteca inválida/duplicada")
        identities.add(identity)
        libraries.append(dict(library))
    expected_order = sorted(
        libraries,
        key=lambda item: (
            cast(str, item["library"]),
            cast(str, item["version"]),
            cast(str, item["threading_layer"]),
        ),
    )
    thread_count = value["process_thread_count"]
    if (
        libraries != expected_order
        or isinstance(thread_count, bool)
        or not isinstance(thread_count, int)
        or thread_count < 1
    ):
        raise ContractError("native-pools observation no está ordenada o thread count es inválido")
    return {
        "environment": environment,
        "libraries": libraries,
        "process_thread_count": thread_count,
    }


def validate_native_pool_process_observation(
    path: Path,
    *,
    candidate_execution_request_sha256: str,
    pid: int,
    creation_time_100ns: int,
) -> dict[str, Any]:
    """Reabre el reporte in-process de un PID/creation-time consumidor exacto."""
    value = _read_canonical_control(path, context="candidate native-pools process observation")
    _require_exact(
        value,
        (
            "schema_version",
            "candidate_execution_request_sha256",
            "pid",
            "creation_time_100ns",
            "environment",
            "libraries",
            "process_thread_count",
        ),
        context="candidate native-pools process observation",
    )
    if (
        value["schema_version"] != NATIVE_POOLS_PROCESS_OBSERVATION_SCHEMA_VERSION
        or value["candidate_execution_request_sha256"]
        != validate_sha256(
            candidate_execution_request_sha256,
            context="candidate native-pools execution request",
        )
        or value["pid"] != pid
        or value["creation_time_100ns"] != creation_time_100ns
    ):
        raise ContractError("native-pools process no liga execution request/PID/creation")
    normalized = _validate_native_pool_process_fields(value)
    return {
        **value,
        **normalized,
    }


def validate_native_pools_observation(
    path: Path,
    *,
    candidate_execution_request_sha256: str,
    native_pools_root: Path,
    expected_process_census: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Reabre el agregado controller-owned y prueba cobertura exacta PID/creation del Job."""
    value = _read_canonical_control(path, context="candidate native-pools aggregate")
    _require_exact(
        value,
        (
            "schema_version",
            "candidate_execution_request_sha256",
            "total_processes",
            "processes",
        ),
        context="candidate native-pools aggregate",
    )
    execution_sha = validate_sha256(
        candidate_execution_request_sha256,
        context="candidate native-pools aggregate execution request",
    )
    expected_identities: list[tuple[int, int]] = []
    for index, raw in enumerate(expected_process_census):
        process = _require_mapping(raw, context=f"candidate process census[{index}]")
        _require_exact(
            process,
            ("pid", "creation_time_100ns"),
            context=f"candidate process census[{index}]",
        )
        pid = process["pid"]
        creation = process["creation_time_100ns"]
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(creation, bool)
            or not isinstance(creation, int)
            or creation <= 0
        ):
            raise ContractError("candidate process census contiene identidad inválida")
        expected_identities.append((pid, creation))
    if not expected_identities or expected_identities != sorted(set(expected_identities)):
        raise ContractError("candidate process census no es único/canónico")
    total_processes = value["total_processes"]
    raw_processes = value["processes"]
    if (
        value["schema_version"] != NATIVE_POOLS_OBSERVATION_SCHEMA_VERSION
        or value["candidate_execution_request_sha256"] != execution_sha
        or isinstance(total_processes, bool)
        or not isinstance(total_processes, int)
        or total_processes < 1
        or total_processes != len(expected_identities)
        or not isinstance(raw_processes, list)
        or len(raw_processes) != total_processes
    ):
        raise ContractError("native-pools aggregate no liga request/cobertura kernel exacta")
    processes: list[dict[str, Any]] = []
    identities: set[tuple[int, int]] = set()
    root = _absolute_path(str(native_pools_root), context="candidate native-pools root")
    _require_plain_directory(root, context="candidate native-pools root")
    for index, raw in enumerate(raw_processes):
        process = _require_mapping(raw, context=f"candidate native-pools processes[{index}]")
        _require_exact(
            process,
            (
                "pid",
                "creation_time_100ns",
                "environment",
                "libraries",
                "process_thread_count",
                "source",
            ),
            context=f"candidate native-pools processes[{index}]",
        )
        pid = process["pid"]
        creation = process["creation_time_100ns"]
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(creation, bool)
            or not isinstance(creation, int)
            or creation <= 0
            or (pid, creation) in identities
        ):
            raise ContractError("native-pools aggregate repite/invalida PID+creation")
        identities.add((pid, creation))
        source = _file_identity(
            process["source"],
            context=f"candidate native-pools processes[{index}].source",
            verify_content=True,
            root=root,
        )
        expected_source_path = root / f"process-{pid}-{creation}.json"
        if Path(cast(str, source["path"])) != expected_source_path:
            raise ContractError("native-pools source no usa path derivado PID+creation")
        source_value = validate_native_pool_process_observation(
            expected_source_path,
            candidate_execution_request_sha256=execution_sha,
            pid=pid,
            creation_time_100ns=creation,
        )
        normalized = _validate_native_pool_process_fields(process)
        if any(source_value[name] != normalized[name] for name in normalized):
            raise ContractError("native-pools aggregate no coincide con su fuente per-process")
        processes.append({**process, **normalized, "source": source})
    if [(item["pid"], item["creation_time_100ns"]) for item in processes] != sorted(identities):
        raise ContractError("native-pools aggregate no está ordenado por PID+creation")
    if sorted(identities) != expected_identities:
        raise ContractError("native-pools aggregate no coincide con el censo kernel")
    return {**value, "processes": processes}


class _WaitableProcess(Protocol):
    """Superficie mínima que el censo necesita del proceso raíz del candidato.

    El arnés lanza el candidato con su propio token restringido, pero las pruebas del censo usan
    ``subprocess.Popen`` real. El protocolo estructural cubre ambos sin relajar el tipado.
    """

    pid: int

    def wait(self, timeout: float | None = ...) -> int:
        """Espera la terminación del proceso dentro del plazo indicado."""
        ...


def _capture_candidate_process_census(
    child_job: WindowsJob,
    process: _WaitableProcess,
    *,
    root_process: Mapping[str, Any],
    workload_deadline: float,
) -> tuple[int, dict[str, Any], dict[str, Any], int]:
    """Captura cada NEW_PROCESS mientras está vivo y prueba quiescencia antes de publicar."""
    root_pid = root_process.get("pid")
    root_creation = root_process.get("creation_time_100ns")
    if (
        isinstance(root_pid, bool)
        or not isinstance(root_pid, int)
        or root_pid != process.pid
        or isinstance(root_creation, bool)
        or not isinstance(root_creation, int)
        or root_creation <= 0
    ):
        raise ContractError("candidate root process no tiene identidad kernel cerrada")
    observed: dict[tuple[int, int], dict[str, int]] = {
        (root_pid, root_creation): {
            "pid": root_pid,
            "creation_time_100ns": root_creation,
        }
    }
    new_process_pids: list[int] = []
    processed_messages = 0
    final_accounting: dict[str, Any] | None = None

    def capture(pid: int) -> None:
        try:
            metrics = process_metrics(pid, child_job.api)
        except OSError:
            return
        creation = metrics.get("creation_time_100ns")
        if isinstance(creation, bool) or not isinstance(creation, int) or creation <= 0:
            raise ContractError("censo candidate observó creation time inválido")
        observed[(pid, creation)] = {
            "pid": pid,
            "creation_time_100ns": creation,
        }

    while True:
        remaining = workload_deadline - time.monotonic()
        if remaining <= 0:
            child_job.terminate(0xE0000004)
            raise ContractError("candidate agotó el deadline antes de quiescencia")
        wait_ms = min(10, max(0, int(remaining * 1_000)))
        messages = child_job.completion_messages(wait_timeout_ms=wait_ms)
        pending = messages[processed_messages:]
        processed_messages = len(messages)
        for message in pending:
            if message["message_id"] != child_job.JOB_OBJECT_MSG_NEW_PROCESS:
                continue
            pid = message["message_specific_value"]
            if pid <= 0:
                raise ContractError("completion port publicó NEW_PROCESS sin PID")
            new_process_pids.append(pid)
            capture(pid)
        for pid in child_job.process_ids():
            capture(pid)
        accounting = child_job.accounting()
        if accounting["active_processes"] == 0:
            final_accounting = accounting
            # El evento ACTIVE_PROCESS_ZERO precede el retorno contractual; un drenaje final
            # recoge cualquier NEW_PROCESS ya encolado sin esperar fuera del deadline.
            messages = child_job.completion_messages(wait_timeout_ms=0)
            for message in messages[processed_messages:]:
                if message["message_id"] == child_job.JOB_OBJECT_MSG_NEW_PROCESS:
                    pid = message["message_specific_value"]
                    if pid <= 0:
                        raise ContractError("completion port publicó NEW_PROCESS sin PID")
                    new_process_pids.append(pid)
                    capture(pid)
            break

    tree_empty_monotonic_ns = time.monotonic_ns()
    remaining = workload_deadline - time.monotonic()
    if remaining <= 0:
        raise ContractError("candidate agotó el deadline al cerrar su proceso raíz")
    try:
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        raise ContractError("candidate root no terminó pese a Job vacío") from exc
    if final_accounting is None:
        raise ContractError("candidate no produjo accounting final")
    total_processes = final_accounting.get("total_processes")
    identities = [observed[key] for key in sorted(observed)]
    if (
        isinstance(total_processes, bool)
        or not isinstance(total_processes, int)
        or total_processes < 1
        or len(new_process_pids) != total_processes
        or len(identities) != total_processes
        or sorted(new_process_pids) != sorted(item["pid"] for item in identities)
    ):
        raise ContractError(
            "evidence_incomplete: completion port no acreditó cada PID/creation del Job"
        )
    census = {
        "source": "windows_job_completion_port_v1",
        "total_processes": total_processes,
        "processes": identities,
    }
    return returncode, final_accounting, census, tree_empty_monotonic_ns


def _remaining_before_deadline(deadline: float, *, context: str) -> float:
    """Impide lanzar o reanudar el candidate fuera del deadline START."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ContractError(f"candidate agotó el deadline contractual {context}")
    return remaining


def _resume_suspended_before_deadline(
    pid: int, api: Any, *, deadline: float, context: str
) -> list[int]:
    """Reanuda el child únicamente si aún queda ventana contractual."""
    _remaining_before_deadline(deadline, context=context)
    return resume_suspended_process(pid, api)


def _candidate_output_isolation_plan(
    paths: Mapping[str, Path], *, candidate_root: Path, workdir: Path
) -> dict[str, Any]:
    """Deriva del layout cerrado qué raíces escribe el candidato y cuáles le quedan vedadas.

    Dos son las que su bootstrap escribe hoy: staging y el runtime del candidato
    —``brokered-inputs``, ``service-ready``, ``native-pools`` y ``TEMP``—. La tercera, su
    ``pycache_prefix``, queda escribible aunque el comando lleve ``-B``: si el script candidato
    reactivara la escritura de bytecode, debe fallar por su propio contrato y no por un permiso
    que el arnés le negó de más. Es un directorio propio, hermano de las cachés del arnés.

    Todo lo demás del workdir, incluido el padre de ``OUTPUT_ROOT``, el snapshot de fuentes desde
    el que corre el driver y ``telemetry``, conserva integridad media: por eso el token candidato
    no puede crear, borrar ni reemplazar nada allí.
    """
    staging = paths["staging"]
    derived_workdir = staging.parent.parent
    if derived_workdir != workdir.resolve():
        raise ContractError("el staging del candidato no deriva del workdir del intento")
    scratch = derived_workdir / "scratch"
    telemetry = derived_workdir / "telemetry"
    writable = [staging, scratch / "candidate-runtime", paths["pycache"]]
    protected = [
        derived_workdir,
        scratch,
        scratch / "python-cache",
        telemetry,
        telemetry / "control",
        candidate_root,
    ]
    return {
        "output_root": derived_workdir / "outputs",
        "writable_roots": writable,
        "protected_roots": protected,
    }


def run_candidate_request(
    request_path: Path,
    expected_sha256: str,
    *,
    authorization_gate_path: Path,
    trusted_authority_public_key_path: Path,
    workdir: Path,
    capability_commitment_sha256: str,
) -> int:
    """Reclama el rol candidate y ejecuta el child aislado en un Job anidado."""
    from .supervisor import (
        consume_internal_authorization_gate,
        consume_launch_capability,
        require_calibration_start_implementation_ready,
    )

    require_calibration_start_implementation_ready()
    expected_request_sha = validate_sha256(expected_sha256, context="candidate request esperado")
    consume_launch_capability(
        role="candidate",
        payload_sha256=expected_request_sha,
        expected_commitment_sha256=capability_commitment_sha256,
    )
    request_path = _absolute_path(str(request_path), context="candidate request path")
    request = _read_canonical_control(request_path, context="candidate request")
    if canonical_json_sha256(request) != expected_request_sha:
        raise ContractError("candidate request no reconcilia bytes/hash canónicos")
    authorization_gate = consume_internal_authorization_gate(
        gate_path=authorization_gate_path,
        role="candidate",
        payload=request,
        capability_commitment_sha256=capability_commitment_sha256,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        workdir=workdir,
    )
    start = cast(Mapping[str, Any], authorization_gate["start"])
    workload_deadline = int(start["start_monotonic_ns"]) / 1_000_000_000 + cast(
        float, request["workload_deadline_seconds"]
    )
    _remaining_before_deadline(workload_deadline, context="antes de validar el runtime aislado")
    _validate_pycache_isolation(workdir, role="candidate")
    normalized = validate_candidate_launch_request(request)
    snapshot_manifest_path = os.environ.get("NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST")
    snapshot_manifest_sha = os.environ.get("NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST_SHA256")
    if snapshot_manifest_path is None or snapshot_manifest_sha is None:
        raise ContractError("candidate controller no recibió snapshot atestiguado")
    gate_tooling = cast(dict[str, Any], authorization_gate["tooling"])
    snapshot = validate_harness_source_snapshot(
        manifest_path=Path(snapshot_manifest_path),
        expected_manifest_sha256=snapshot_manifest_sha,
        expected_source_tooling_manifest_sha256=cast(str, gate_tooling["manifest_sha256"]),
    )
    runtime = cast(dict[str, Any], normalized["runtime"])
    if (
        canonical_tree_identity(cast(Path, runtime["candidate_root"]))["sha256"]
        != runtime["candidate_tree_sha256"]
    ):
        raise ContractError("árbol candidato cambió antes del child")
    paths = cast(dict[str, Path], normalized["paths"])
    execution_request_path = workdir / "telemetry" / "control" / "candidate-execution.json"
    execution_request = candidate_execution_request(
        normalized,
        harness_runtime_snapshot=cast(dict[str, Any], snapshot["value"]),
    )
    native_pools_root = paths["brokered_inputs_json"].parent / "native-pools"
    native_pools_root.mkdir(parents=True, exist_ok=False)
    candidate_temp_root = paths["brokered_inputs_json"].parent / "temp"
    candidate_temp_root.mkdir(exist_ok=False)
    execution_payload = canonical_json_bytes(execution_request) + b"\n"
    with execution_request_path.open("xb") as handle:
        handle.write(execution_payload)
        handle.flush()
        os.fsync(handle.fileno())
    execution_sha = sha256_file(execution_request_path)
    execution_identity = {
        "path": str(execution_request_path.resolve()),
        "logical_bytes": execution_request_path.stat().st_size,
        "sha256": execution_sha,
    }
    isolation_plan = _candidate_output_isolation_plan(
        paths, candidate_root=cast(Path, runtime["candidate_root"]), workdir=workdir
    )
    for writable_root in cast(list[Path], isolation_plan["writable_roots"]):
        apply_low_integrity_label(writable_root)
    output_isolation_census = census_output_isolation(
        output_root=cast(Path, isolation_plan["output_root"]),
        writable_roots=cast(list[Path], isolation_plan["writable_roots"]),
        protected_roots=cast(list[Path], isolation_plan["protected_roots"]),
        # El doble sintético usa el Python del controller, nunca el runtime candidato: mide la
        # política del volumen, no el comportamiento del candidato.
        denial_probe=probe_output_root_denial(
            cast(Path, isolation_plan["output_root"]),
            python_executable=Path(sys.executable),
        ),
    )
    stdout_handle = paths["stdout"].open("xb")
    stderr_handle = paths["stderr"].open("xb")
    child_job = WindowsJob(
        memory_bytes=cast(int, runtime["job_memory_commit_limit_bytes"]),
        affinity_mask=cast(int, runtime["affinity_mask"]),
    )
    process: SandboxProcess | None = None
    try:
        _remaining_before_deadline(workload_deadline, context="antes de crear el child suspendido")
        command = [
            str(cast(dict[str, Any], runtime["python_executable"])["path"]),
            "-I",
            "-B",
            "-S",
            "-X",
            f"pycache_prefix={paths['pycache']}",
            "-c",
            _CANDIDATE_BOOTSTRAP,
        ]
        with low_integrity_primary_token() as candidate_token:
            process = launch_suspended_low_integrity(
                command,
                token=candidate_token,
                cwd=paths["staging"],
                environment=_candidate_child_environment(
                    execution_request_path,
                    execution_sha,
                    temp_root=candidate_temp_root,
                    logical_cpu_count=cast(int, runtime["affinity_mask"]).bit_count(),
                ),
                stdout_fd=stdout_handle.fileno(),
                stderr_fd=stderr_handle.fileno(),
            )
        child_job.assign(process.pid)
        effective_integrity = process_integrity_level(process.pid)
        if effective_integrity != LOW_INTEGRITY_SID:
            raise ContractError(
                "limits_not_applied: el candidato no quedó en integridad Low efectiva "
                f"({effective_integrity})"
            )
        output_isolation = {
            "schema_version": CANDIDATE_OUTPUT_ISOLATION_SCHEMA_VERSION,
            **output_isolation_census,
            "candidate_effective_integrity_sid": effective_integrity,
        }
        process_identity = process_metrics(process.pid, child_job.api)
        initial_accounting = child_job.accounting()
        if initial_accounting["memory_usage_information_supported"] is not True or not isinstance(
            initial_accounting["current_job_memory_commit_bytes"], int
        ):
            raise ContractError(
                "candidate Job no acredita JobMemoryUsageInformation antes de resume"
            )
        candidate_process = {
            "pid": process.pid,
            "creation_time_100ns": process_identity["creation_time_100ns"],
        }
        candidate_start = {
            "schema_version": CANDIDATE_START_SCHEMA_VERSION,
            "attempt_id": normalized["attempt_id"],
            "candidate_request_sha256": expected_request_sha,
            "candidate_execution_request": execution_identity,
            "candidate_process": candidate_process,
        }
        candidate_start_path = paths["candidate_start"]
        with candidate_start_path.open("xb") as handle:
            handle.write(canonical_json_bytes(candidate_start) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _resume_suspended_before_deadline(
            process.pid,
            child_job.api,
            deadline=workload_deadline,
            context="antes de reanudar el child",
        )
        (
            returncode,
            final_accounting,
            candidate_process_census,
            tree_empty_monotonic_ns,
        ) = _capture_candidate_process_census(
            child_job,
            process,
            root_process=candidate_process,
            workload_deadline=workload_deadline,
        )
        total_processes = final_accounting["total_processes"]
        native_pools_observation: dict[str, Any] | None = None
        service_ready_identity: dict[str, Any] | None = None
        if returncode == 0:
            census_processes = cast(list[dict[str, Any]], candidate_process_census["processes"])
            observed_processes: list[dict[str, Any]] = []
            expected_source_paths: set[Path] = set()
            for census_process in census_processes:
                pid = cast(int, census_process["pid"])
                creation = cast(int, census_process["creation_time_100ns"])
                source_path = native_pools_root / f"process-{pid}-{creation}.json"
                expected_source_paths.add(source_path)
                source_value = validate_native_pool_process_observation(
                    source_path,
                    candidate_execution_request_sha256=execution_sha,
                    pid=pid,
                    creation_time_100ns=creation,
                )
                source_identity = _file_identity(
                    {
                        "path": str(source_path),
                        "logical_bytes": source_path.stat().st_size,
                        "sha256": sha256_file(source_path),
                    },
                    context="candidate native-pools process source",
                    verify_content=True,
                    root=native_pools_root,
                )
                observed_processes.append(
                    {
                        "pid": pid,
                        "creation_time_100ns": creation,
                        "environment": source_value["environment"],
                        "libraries": source_value["libraries"],
                        "process_thread_count": source_value["process_thread_count"],
                        "source": source_identity,
                    }
                )
            observed_files, observed_directories = _plain_tree_inventory(
                native_pools_root, context="candidate native-pools root final"
            )
            if observed_directories or set(observed_files) != expected_source_paths:
                raise ContractError(
                    "evidence_incomplete: reporters native-pools faltan o contienen extras"
                )
            aggregate = {
                "schema_version": NATIVE_POOLS_OBSERVATION_SCHEMA_VERSION,
                "candidate_execution_request_sha256": execution_sha,
                "total_processes": total_processes,
                "processes": observed_processes,
            }
            observation_path = execution_request_path.with_name("native-pools-observation.json")
            with observation_path.open("xb") as handle:
                handle.write(canonical_json_bytes(aggregate) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            validate_native_pools_observation(
                observation_path,
                candidate_execution_request_sha256=execution_sha,
                native_pools_root=native_pools_root,
                expected_process_census=census_processes,
            )
            native_pools_observation = _file_identity(
                {
                    "path": str(observation_path),
                    "logical_bytes": observation_path.stat().st_size,
                    "sha256": sha256_file(observation_path),
                },
                context="candidate native-pools observation",
                verify_content=True,
            )
            if normalized["mode"] == "http-service":
                service = cast(dict[str, Any], normalized["service"])
                validate_candidate_service_ready(
                    paths["service_ready"],
                    attempt_id=cast(str, normalized["attempt_id"]),
                    candidate_request_sha256=expected_request_sha,
                    candidate_process=candidate_process,
                    service=service,
                )
                service_ready_identity = _control_identity(
                    paths["service_ready"], context="candidate service-ready final"
                )
        result = {
            "schema_version": CANDIDATE_RESULT_SCHEMA_VERSION,
            "attempt_id": normalized["attempt_id"],
            "candidate_request_sha256": expected_request_sha,
            "candidate_execution_request": execution_identity,
            "candidate_process": candidate_process,
            "output_isolation": output_isolation,
            "service_ready": service_ready_identity,
            "native_pools_observation": native_pools_observation,
            "total_processes": total_processes,
            "candidate_process_census": candidate_process_census,
            "candidate_job_accounting": final_accounting,
            "returncode": returncode,
            "tree_quiescent": True,
            "tree_empty_monotonic_ns": tree_empty_monotonic_ns,
        }
        result_path = paths["candidate_result"]
        with result_path.open("xb") as handle:
            handle.write(canonical_json_bytes(result) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return returncode
    finally:
        if process is not None:
            if process.poll() is None:
                child_job.terminate(0xE0000004)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=10)
            process.close()
        child_job.close()
        for log_handle in (stdout_handle, stderr_handle):
            if not log_handle.closed:
                log_handle.flush()
                os.fsync(log_handle.fileno())
        stdout_handle.close()
        stderr_handle.close()


def validate_counter_adapter_descriptor(
    raw: Mapping[str, Any],
    *,
    candidate_root: Path,
    expected_bindings: Mapping[str, str],
) -> dict[str, Any]:
    """Cierra la interfaz binaria y falla porque aún no existe un contador autorizado."""
    descriptor = dict(raw)
    _require_exact(
        descriptor,
        (
            "schema_version",
            "counter_id",
            "format",
            "bindings",
            "implementation",
            "result_contract",
        ),
        context="counter adapter",
    )
    if descriptor["schema_version"] != COUNTER_ADAPTER_SCHEMA_VERSION:
        raise ContractError("counter adapter usa otro schema")
    counter_id = _require_text(descriptor["counter_id"], context="counter_id")
    if descriptor["format"] != "bin":
        raise ContractError("counter adapter cerrado sólo aplica a bin")
    bindings = _validate_bindings(descriptor["bindings"], context="counter.bindings")
    if bindings != dict(expected_bindings):
        raise ContractError("counter adapter no está ligado a config/candidate/tooling")
    implementation = _require_mapping(
        descriptor["implementation"], context="counter.implementation"
    )
    _require_exact(implementation, ("kind", "script"), context="counter.implementation")
    if implementation["kind"] != "signed_python_script":
        raise ContractError("counter adapter no es un script firmado")
    script = _require_mapping(implementation["script"], context="counter.script")
    _require_exact(script, ("relative_path", "bytes", "sha256"), context="counter.script")
    relative = _safe_relative(
        script["relative_path"], context="counter.script.relative_path", suffix=".py"
    )
    script_path = (candidate_root / Path(relative)).resolve(strict=False)
    _file_identity(
        {
            "path": str(script_path),
            "logical_bytes": script["bytes"],
            "sha256": script["sha256"],
        },
        context="counter.script",
        verify_content=True,
        root=candidate_root,
    )
    result_contract = _require_mapping(
        descriptor["result_contract"], context="counter.result_contract"
    )
    _require_exact(
        result_contract, ("schema_version", "required_fields"), context="counter.result_contract"
    )
    if result_contract != {
        "schema_version": COUNTER_RESULT_SCHEMA_VERSION,
        "required_fields": ["schema_version", "counter_id", "output_sha256", "records"],
    }:
        raise ContractError("result_contract del counter no es el contrato cerrado")
    if counter_id not in AUTHORIZED_COUNTER_ADAPTER_IDS:
        raise ContractError(
            "bin no es calificable: no existe un counter adapter independiente autorizado"
        )
    return descriptor  # pragma: no cover - registro intencionalmente vacío


def _read_jsonl(path: Path, *, context: str) -> list[dict[str, Any]]:
    path = _absolute_path(str(path), context=f"{context}.path")
    if not path.is_file() or _is_reparse(path):
        raise ContractError(f"{context}: sidecar ausente, symlink o reparse point")
    if path.stat().st_nlink != 1:
        raise ContractError(f"{context}: hardlink prohibido")
    payload = path.read_bytes()
    events: list[dict[str, Any]] = []
    try:
        text = payload.decode("utf-8")
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
            if not line.endswith("\n") or not line.strip():
                raise ContractError(f"{context}: JSONL inválido en línea {line_number}")
            value: Any = json.loads(line)
            if not isinstance(value, dict):
                raise ContractError(f"{context}: evento no es objeto")
            if line.encode("utf-8") != canonical_json_bytes(value) + b"\n":
                raise ContractError(f"{context}: evento no usa JSON canónico")
            events.append(cast(dict[str, Any], value))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{context}: JSONL no es UTF-8/JSON válido") from exc
    _file_identity(
        {
            "path": str(path),
            "logical_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        context=context,
        verify_content=True,
    )
    return events


def validate_adapter_audit(path: Path, *, require_success: bool) -> list[dict[str, Any]]:
    """Reabre el sidecar del broker/proxy y valida su máquina de estados única."""
    events = _read_jsonl(path, context="adapter audit")
    if not events:
        if require_success:
            raise ContractError("adapter broker audit ausente en success")
        return []
    if len(events) > 2:
        raise ContractError("adapter broker audit contiene eventos extra")
    last_ns = -1
    for index, event in enumerate(events):
        monotonic_ns = event.get("monotonic_ns")
        if (
            event.get("schema_version") != ADAPTER_AUDIT_SCHEMA_VERSION
            or isinstance(monotonic_ns, bool)
            or not isinstance(monotonic_ns, int)
            or monotonic_ns < last_ns
        ):
            raise ContractError(f"adapter broker audit[{index}] no tiene schema/reloj")
        last_ns = monotonic_ns
        if index == 0:
            _require_exact(
                event,
                ("schema_version", "event", "monotonic_ns", "protected_count"),
                context="adapter broker audit ready",
            )
            if event["event"] != "broker_ready":
                raise ContractError("broker_ready debe iniciar adapter audit")
            _require_non_negative_int(
                event["protected_count"], context="adapter broker protected_count"
            )
        else:
            _require_exact(
                event,
                (
                    "schema_version",
                    "event",
                    "monotonic_ns",
                    "request_id",
                    "broker_request_sha256",
                    "nonce_commitment_sha256",
                    "candidate_process",
                    "protected",
                ),
                context="adapter broker audit OPEN",
            )
            if event["event"] != "consumer_open_brokered":
                raise ContractError("adapter broker audit contiene evento extra/desordenado")
            for name in (
                "request_id",
                "broker_request_sha256",
                "nonce_commitment_sha256",
            ):
                validate_sha256(event[name], context=f"adapter broker audit.{name}")
            process = _require_mapping(
                event["candidate_process"], context="adapter broker audit.candidate_process"
            )
            _require_exact(
                process,
                ("pid", "creation_time_100ns"),
                context="adapter broker audit.candidate_process",
            )
            _require_non_negative_int(process["pid"], context="adapter broker audit.pid")
            if process["pid"] <= 0:
                raise ContractError("adapter broker audit.pid debe ser positivo")
            _require_non_negative_int(
                process["creation_time_100ns"], context="adapter broker audit.creation_time_100ns"
            )
            protected = _validate_protected_contract(
                event["protected"], context="adapter broker audit.protected"
            )
            if events[0]["protected_count"] != len(protected):
                raise ContractError("adapter broker audit no reconcilia protected_count")
    if require_success and len(events) == 1 and events[0]["protected_count"] != 1:
        raise ContractError("adapter UI exige exactamente un body protegido")
    return events


def _prepare_sidecar(path: Path, *, context: str) -> None:
    try:
        prepare_jsonl_sidecar(path)
    except ContractError as exc:
        raise ContractError(f"{context}: sidecar previo no es seguro/vacío") from exc


def _validate_runtime_paths(raw: Any, *, include_job_limits: bool = False) -> dict[str, Any]:
    runtime = _require_mapping(raw, context="adapter.runtime")
    fields = (
        "candidate_root",
        "candidate_tree_sha256",
        "python_executable",
        "isolation_flags",
        *(("job_memory_commit_limit_bytes", "affinity_mask") if include_job_limits else ()),
    )
    _require_exact(runtime, fields, context="adapter.runtime")
    candidate_root = _require_plain_directory(
        _absolute_path(runtime["candidate_root"], context="runtime.candidate_root"),
        context="runtime.candidate_root",
    )
    python_executable = _file_identity(
        runtime["python_executable"],
        context="runtime.python_executable",
        verify_content=True,
    )
    if runtime["isolation_flags"] != ["-I", "-B", "-S"]:
        raise ContractError("runtime del adapter no declara aislamiento -I -B -S exacto")
    normalized = {
        "candidate_root": candidate_root,
        "candidate_tree_sha256": validate_sha256(
            runtime["candidate_tree_sha256"], context="runtime.candidate_tree_sha256"
        ),
        "python_executable": python_executable,
        "isolation_flags": ["-I", "-B", "-S"],
    }
    if include_job_limits:
        memory_bytes = runtime["job_memory_commit_limit_bytes"]
        affinity_mask = runtime["affinity_mask"]
        if memory_bytes not in CAPS.values():
            raise ContractError("candidate runtime cap fuera del catálogo")
        if (
            isinstance(affinity_mask, bool)
            or not isinstance(affinity_mask, int)
            or affinity_mask < 1
        ):
            raise ContractError("candidate runtime affinity_mask inválida")
        normalized.update(
            {
                "job_memory_commit_limit_bytes": memory_bytes,
                "affinity_mask": affinity_mask,
            }
        )
    return normalized


def _validate_paths(raw: Any, *, boundary_kind: str) -> dict[str, Any]:
    paths = _require_mapping(raw, context="adapter.paths")
    fields = (
        "fixture_root",
        "inputs_root",
        "inputs",
        "bundle_root",
        "bundle",
        "config",
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
    _require_exact(paths, fields, context="adapter.paths")
    fixture_root = _require_plain_directory(
        _absolute_path(paths["fixture_root"], context="paths.fixture_root"),
        context="paths.fixture_root",
    )
    inputs_root = _require_plain_directory(
        _absolute_path(paths["inputs_root"], context="paths.inputs_root"),
        context="paths.inputs_root",
    )
    bundle_root = _require_plain_directory(
        _absolute_path(paths["bundle_root"], context="paths.bundle_root"),
        context="paths.bundle_root",
    )
    if not _path_is_within(inputs_root, fixture_root) or not _path_is_within(
        bundle_root, fixture_root
    ):
        raise ContractError("inputs/bundle root escapan del fixture")
    if _paths_overlap(inputs_root, bundle_root):
        raise ContractError("inputs_root y bundle_root no pueden solaparse")
    raw_inputs = paths["inputs"]
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ContractError("adapter.paths.inputs debe ser lista no vacía")
    inputs = [
        _file_identity(
            item,
            context=f"adapter.paths.inputs[{index}]",
            verify_content=False,
            root=inputs_root,
        )
        for index, item in enumerate(raw_inputs)
    ]
    input_paths = [item["path"] for item in inputs]
    if len(set(input_paths)) != len(input_paths):
        raise ContractError("adapter.paths.inputs contiene rutas duplicadas")
    bundle = None
    if paths["bundle"] is not None:
        bundle = _file_identity(
            paths["bundle"],
            context="adapter.paths.bundle",
            verify_content=False,
            root=bundle_root,
        )
    config = _file_identity(
        paths["config"],
        context="adapter.paths.config",
        verify_content=False,
        root=fixture_root,
    )
    protected_paths = [Path(str(item["path"])) for item in inputs]
    protected_paths.append(Path(str(config["path"])))
    if bundle is not None:
        protected_paths.append(Path(str(bundle["path"])))
    if len(set(protected_paths)) != len(protected_paths):
        raise ContractError("config/input/bundle contienen la misma ruta física")
    staging = _absolute_path(paths["staging"], context="paths.staging")
    candidate_outputs = _absolute_path(
        paths["candidate_outputs"], context="paths.candidate_outputs"
    )
    adapter_result = _absolute_path(paths["adapter_result"], context="paths.adapter_result")
    outputs = _absolute_path(paths["outputs"], context="paths.outputs")
    if staging.exists() or outputs.exists():
        raise ContractError("staging y outputs deben ser inexistentes")
    if candidate_outputs != staging / "candidate-outputs.json":
        raise ContractError("candidate_outputs debe ser staging/candidate-outputs.json")
    if adapter_result != staging.parent.parent / "telemetry" / "control" / "adapter-result.json":
        raise ContractError("adapter_result no deriva del control root cerrado")
    if adapter_result.exists():
        raise ContractError("adapter_result debe ser inexistente antes del candidato")
    if (
        _paths_overlap(staging, outputs)
        or _paths_overlap(staging, fixture_root)
        or _paths_overlap(outputs, fixture_root)
    ):
        raise ContractError("staging/outputs/fixture no pueden solaparse")
    sidecars = {
        name: _absolute_path(paths[name], context=f"paths.{name}")
        for name in ("boundary", "filesystem_events", "native_pools", "audit")
    }
    if len(set(sidecars.values())) != len(sidecars) or any(
        _path_is_within(path, staging)
        or _path_is_within(path, outputs)
        or _path_is_within(path, fixture_root)
        for path in sidecars.values()
    ):
        raise ContractError("sidecars se solapan o caen dentro de fixture/staging/outputs")
    ui_first_byte = _absolute_path(paths["ui_first_byte"], context="paths.ui_first_byte")
    if (
        ui_first_byte in sidecars.values()
        or _path_is_within(ui_first_byte, staging)
        or _path_is_within(ui_first_byte, outputs)
        or _path_is_within(ui_first_byte, fixture_root)
    ):
        raise ContractError("ui_first_byte se solapa con fixture/control/staging/outputs")
    return {
        "fixture_root": fixture_root,
        "inputs_root": inputs_root,
        "inputs": inputs,
        "bundle_root": bundle_root,
        "bundle": bundle,
        "config": config,
        "staging": staging,
        "candidate_outputs": candidate_outputs,
        "adapter_result": adapter_result,
        "outputs": outputs,
        **sidecars,
        "ui_first_byte": ui_first_byte,
    }


def _validate_ui_ingress(
    raw: Any, *, paths: Mapping[str, Any], attempt_id: str
) -> dict[str, Any] | None:
    if raw is None:
        return None
    ingress = _require_mapping(raw, context="adapter.ui_ingress")
    _require_exact(
        ingress,
        (
            "loopback_host",
            "port",
            "path",
            "timeout_seconds",
            "expected_status",
            "request_id",
            "body",
            "service_descriptor_sha256",
            "endpoint_sha256",
        ),
        context="adapter.ui_ingress",
    )
    client_shape = validate_ui_client_request(
        {
            "schema_version": UI_CLIENT_REQUEST_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "method": "POST",
            **dict(ingress),
            "first_byte_path": str(cast(Path, paths["ui_first_byte"])),
        }
    )
    body = cast(dict[str, Any], client_shape["body"])
    input_identities = cast(list[dict[str, Any]], paths["inputs"])
    if len(input_identities) != 1 or body != input_identities[0]:
        raise ContractError("F-UI body debe ser el único input protegido exacto")
    service_descriptor_sha256 = validate_sha256(
        ingress["service_descriptor_sha256"], context="adapter.ui_ingress.service_descriptor"
    )
    endpoint_sha256 = validate_sha256(
        ingress["endpoint_sha256"], context="adapter.ui_ingress.endpoint"
    )
    expected_endpoint_sha256 = canonical_json_sha256(
        {
            "method": client_shape["method"],
            "loopback_host": client_shape["loopback_host"],
            "port": client_shape["port"],
            "path": client_shape["path"],
            "expected_status": client_shape["expected_status"],
            "request_id": client_shape["request_id"],
            "body": client_shape["body"],
        }
    )
    if endpoint_sha256 != expected_endpoint_sha256:
        raise ContractError("adapter.ui_ingress.endpoint_sha256 no deriva del endpoint exacto")
    return {
        name: client_shape[name]
        for name in (
            "loopback_host",
            "port",
            "path",
            "timeout_seconds",
            "expected_status",
            "request_id",
            "body",
        )
    } | {
        "service_descriptor_sha256": service_descriptor_sha256,
        "endpoint_sha256": endpoint_sha256,
    }


def validate_adapter_request(
    raw: Mapping[str, Any], *, require_fresh_candidate_pycache: bool = True
) -> dict[str, Any]:
    """Valida la solicitud cerrada sin ejecutar el script ni abrir inputs protegidos."""
    request = dict(raw)
    _require_exact(
        request,
        (
            "schema_version",
            "attempt_id",
            "flow_id",
            "flow_step",
            "adapter_id",
            "bindings",
            "descriptor",
            "runtime",
            "paths",
            "ui_ingress",
            "expected",
            "counter_adapter",
            "candidate_launch",
        ),
        context="adapter request",
    )
    if request["schema_version"] != ADAPTER_REQUEST_SCHEMA_VERSION:
        raise ContractError("adapter request usa otro schema")
    attempt_id = validate_sha256(request["attempt_id"], context="adapter.attempt_id")
    flow_id = _require_text(request["flow_id"], context="adapter.flow_id")
    flow_step = _require_text(request["flow_step"], context="adapter.flow_step")
    spec = adapter_spec(flow_id, flow_step)
    if request["adapter_id"] != spec.adapter_id:
        raise ContractError("adapter_id no coincide con flow/step")
    bindings = _validate_bindings(request["bindings"], context="adapter.bindings")
    runtime = _validate_runtime_paths(request["runtime"], include_job_limits=True)
    paths = _validate_paths(request["paths"], boundary_kind=spec.boundary_kind)
    ui_ingress = _validate_ui_ingress(request["ui_ingress"], paths=paths, attempt_id=attempt_id)
    if (spec.boundary_kind == "first_byte") != (ui_ingress is not None):
        raise ContractError("ui_ingress debe existir exactamente para F-UI")
    if _paths_overlap(runtime["candidate_root"], paths["fixture_root"]) or any(
        _path_is_within(runtime["candidate_root"], paths[name])
        or _path_is_within(paths[name], runtime["candidate_root"])
        for name in ("staging", "outputs")
    ):
        raise ContractError("el árbol candidato se solapa con fixture/staging/outputs")
    descriptor_entry = _file_identity(
        request["descriptor"],
        context="adapter.descriptor",
        verify_content=True,
    )
    descriptor_path = Path(str(descriptor_entry["path"]))
    descriptor_raw = read_json_object(descriptor_path)
    if descriptor_path.read_bytes() != canonical_json_bytes(descriptor_raw) + b"\n":
        raise ContractError("descriptor externo no usa JSON canónico con newline final")
    descriptor = validate_adapter_descriptor(
        descriptor_raw,
        candidate_root=runtime["candidate_root"],
        expected_flow_id=flow_id,
        expected_flow_step=flow_step,
        expected_bindings=bindings,
    )
    if descriptor["attempt_id"] != attempt_id:
        raise ContractError("descriptor externo y request difieren en attempt_id")
    expected = _require_mapping(request["expected"], context="adapter.expected")
    _require_exact(
        expected,
        ("identities", "counts", "golden_observed_sha256"),
        context="adapter.expected",
    )
    identities = list(flow_spec(flow_id, flow_step).expected_output_identities)
    if expected["identities"] != identities:
        raise ContractError("adapter.expected.identities no coincide con el flujo")
    counts_raw = _require_mapping(expected["counts"], context="adapter.expected.counts")
    if set(counts_raw) != set(identities):
        raise ContractError("adapter.expected.counts no cubre exactamente las identidades")
    counts = {
        identity: _require_non_negative_int(
            counts_raw[identity], context=f"adapter.expected.counts.{identity}"
        )
        for identity in identities
    }
    golden = validate_sha256(
        expected["golden_observed_sha256"], context="adapter.expected.golden_observed_sha256"
    )
    if descriptor["expected"] != {
        "identities": identities,
        "counts": counts,
        "golden_sha256": golden,
    }:
        raise ContractError("descriptor externo y request difieren en outputs esperados")
    counter_adapter = request["counter_adapter"]
    if counter_adapter is not None:
        validate_counter_adapter_descriptor(
            _require_mapping(counter_adapter, context="adapter.counter_adapter"),
            candidate_root=runtime["candidate_root"],
            expected_bindings=bindings,
        )
    candidate_launch = _validate_candidate_controller_launch(
        request["candidate_launch"],
        expected_attempt_id=attempt_id,
        expected_tooling_manifest_sha256=bindings["tooling_manifest_sha256"],
        require_fresh_candidate_pycache=require_fresh_candidate_pycache,
    )
    candidate_request = cast(dict[str, Any], candidate_launch["candidate_request_value"])
    candidate_paths = cast(dict[str, Path], candidate_request["paths"])
    if (
        candidate_request["input_contract"] != descriptor["input_contract"]
        or candidate_request["script"]["sha256"]
        != cast(dict[str, Any], descriptor["implementation"])["script"]["sha256"]
        or candidate_request["argv_template"]
        != cast(dict[str, Any], descriptor["implementation"])["argv_template"]
        or (candidate_request["mode"] == "http-service") != (spec.boundary_kind == "first_byte")
        or candidate_paths["staging"] != paths["staging"]
        or candidate_paths["candidate_outputs"] != paths["candidate_outputs"]
        or candidate_paths["adapter_result"] != paths["adapter_result"]
    ):
        raise ContractError("candidate launch no reconcilia descriptor/input/staging del adapter")
    return {
        "schema_version": ADAPTER_REQUEST_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "flow_id": flow_id,
        "flow_step": flow_step,
        "adapter_id": spec.adapter_id,
        "boundary_kind": spec.boundary_kind,
        "bindings": bindings,
        "descriptor": descriptor,
        "descriptor_entry": descriptor_entry,
        "runtime": runtime,
        "paths": paths,
        "ui_ingress": ui_ingress,
        "expected": {
            "identities": identities,
            "counts": counts,
            "golden_observed_sha256": golden,
        },
        "counter_adapter": None,
        "candidate_launch": candidate_launch,
    }


def validate_ui_first_byte(path: Path, *, attempt_id: str) -> dict[str, Any]:
    """Reabre y valida el único evento first-byte ligado al intento F-UI."""
    events = _read_jsonl(path, context="ui first byte")
    if len(events) != 1:
        raise ContractError("ui_first_byte debe contener exactamente un evento")
    event = events[0]
    _require_exact(
        event,
        ("schema_version", "attempt_id", "event", "monotonic_ns", "request_id"),
        context="ui first byte",
    )
    if (
        event["schema_version"] != UI_FIRST_BYTE_SCHEMA_VERSION
        or event["attempt_id"] != attempt_id
        or event["event"] != "first_byte"
    ):
        raise ContractError("ui_first_byte no reconcilia schema/attempt/evento")
    _require_non_negative_int(event["monotonic_ns"], context="ui_first_byte.monotonic_ns")
    _require_text(event["request_id"], context="ui_first_byte.request_id")
    return event


def validate_ui_client_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Cierra el cliente HTTP externo a loopback, sin redirects ni comando configurable."""
    request = dict(raw)
    _require_exact(
        request,
        (
            "schema_version",
            "attempt_id",
            "method",
            "loopback_host",
            "port",
            "path",
            "timeout_seconds",
            "expected_status",
            "body",
            "request_id",
            "first_byte_path",
        ),
        context="ui client request",
    )
    if request["schema_version"] != UI_CLIENT_REQUEST_SCHEMA_VERSION:
        raise ContractError("ui client request usa otro schema")
    attempt_id = validate_sha256(request["attempt_id"], context="ui client attempt_id")
    if request["method"] != "POST":
        raise ContractError("ui client sólo admite POST")
    host = _require_text(request["loopback_host"], context="ui client loopback_host")
    if host == "localhost":
        normalized_host = "127.0.0.1"
    else:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ContractError("ui client host no es loopback literal") from exc
        if not address.is_loopback or address.version != 4:
            raise ContractError("ui client sólo admite loopback IPv4")
        normalized_host = str(address)
    port = request["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ContractError("ui client port inválido")
    request_path = _require_text(request["path"], context="ui client path")
    if (
        not request_path.startswith("/")
        or request_path.startswith("//")
        or "#" in request_path
        or "\r" in request_path
        or "\n" in request_path
    ):
        raise ContractError("ui client path no es un origin-form seguro")
    timeout = request["timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < float(timeout) <= 60.0
    ):
        raise ContractError("ui client timeout debe estar en (0, 60]")
    expected_status = request["expected_status"]
    if (
        isinstance(expected_status, bool)
        or not isinstance(expected_status, int)
        or not 200 <= expected_status <= 299
    ):
        raise ContractError("ui client expected_status debe ser 2xx")
    first_byte_path = _absolute_path(
        request["first_byte_path"], context="ui client first_byte_path"
    )
    body = _file_identity(request["body"], context="ui client body", verify_content=False)
    request_id = validate_sha256(request["request_id"], context="ui client request_id")
    expected_request_id = canonical_json_sha256(
        {
            "attempt_id": attempt_id,
            "method": "POST",
            "host": normalized_host,
            "port": port,
            "path": request_path,
            "body_sha256": body["sha256"],
            "body_bytes": body["logical_bytes"],
        }
    )
    if request_id != expected_request_id:
        raise ContractError("ui client request_id no deriva del body/endpoint exactos")
    return {
        "schema_version": UI_CLIENT_REQUEST_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "method": "POST",
        "loopback_host": normalized_host,
        "port": port,
        "path": request_path,
        "timeout_seconds": float(timeout),
        "expected_status": expected_status,
        "body": body,
        "request_id": request_id,
        "first_byte_path": first_byte_path,
    }


class _NoRedirectConnection(http.client.HTTPConnection):
    """HTTPConnection concreto; ``http.client`` nunca sigue redirects por sí mismo."""


class _CandidateHttpProxy:
    """Proxy binario loopback hacia un servicio candidato; nunca fabrica respuesta."""

    def __init__(
        self,
        *,
        ingress: Mapping[str, Any],
        service: Mapping[str, Any],
        service_ready_path: Path,
        http_exchange_path: Path,
        candidate_start_path: Path,
        candidate_request_sha256: str,
        attempt_id: str,
        boundary: ConsumerBoundary,
    ) -> None:
        self.ingress = dict(ingress)
        self.service = dict(service)
        self.service_ready_path = service_ready_path
        self.http_exchange_path = http_exchange_path
        self.candidate_start_path = candidate_start_path
        self.candidate_request_sha256 = candidate_request_sha256
        self.attempt_id = attempt_id
        self.boundary = boundary
        self.finished = threading.Event()
        self.error: BaseException | None = None
        self.response: dict[str, Any] | None = None
        self.exchange_identity: dict[str, Any] | None = None
        self._candidate_process: dict[str, Any] | None = None
        self._service_ready_identity: dict[str, Any] | None = None
        self._listener_observed_monotonic_ns: int | None = None
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        server.bind((cast(str, self.ingress["loopback_host"]), cast(int, self.ingress["port"])))
        server.listen(1)
        server.settimeout(cast(float, self.ingress["timeout_seconds"]))
        self._server = server
        self._thread = threading.Thread(
            target=self._serve, name="h9r-candidate-http-proxy", daemon=False
        )
        self._thread.start()

    @staticmethod
    def _recv_until(connection: socket.socket, initial: bytes, marker: bytes) -> bytes:
        payload = initial
        while marker not in payload:
            if len(payload) > 64 * 1024:
                raise ContractError("headers HTTP exceden 64 KiB")
            chunk = connection.recv(64 * 1024)
            if not chunk:
                raise ContractError("HTTP truncado antes del fin de headers")
            payload += chunk
        return payload

    @staticmethod
    def _headers(raw: bytes, *, response: bool) -> tuple[str, dict[str, str]]:
        lines = raw.decode("iso-8859-1").split("\r\n")
        start_line = lines[0]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                raise ContractError("header HTTP mal formado")
            name, value = line.split(":", 1)
            key = name.strip().casefold()
            if key in headers:
                raise ContractError("header HTTP duplicado")
            headers[key] = value.strip()
        if headers.get("transfer-encoding") is not None:
            raise ContractError("proxy prohíbe transfer-encoding")
        if response and not start_line.startswith("HTTP/1.1 "):
            raise ContractError("status-line candidato inválida")
        return start_line, headers

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + cast(float, self.service["ready_timeout_seconds"])
        while time.monotonic() < deadline:
            if self.service_ready_path.is_file():
                start = _read_canonical_control(
                    self.candidate_start_path, context="candidate-start UI"
                )
                process = _require_mapping(
                    start.get("candidate_process"), context="candidate-start UI process"
                )
                if (
                    start.get("attempt_id") != self.attempt_id
                    or start.get("candidate_request_sha256") != self.candidate_request_sha256
                    or set(process) != {"pid", "creation_time_100ns"}
                ):
                    raise ContractError("candidate service-ready no reconcilia endpoint")
                ready = validate_candidate_service_ready(
                    self.service_ready_path,
                    attempt_id=self.attempt_id,
                    candidate_request_sha256=self.candidate_request_sha256,
                    candidate_process=process,
                    service=self.service,
                )
                observed = process_metrics(cast(int, process["pid"]))
                if observed["creation_time_100ns"] != process["creation_time_100ns"]:
                    raise ContractError("listener UI no liga proceso candidato vivo")
                owner_pid = tcp_listener_owner_pid(
                    cast(str, self.service["host"]), cast(int, self.service["port"])
                )
                if owner_pid != process["pid"]:
                    raise ContractError(
                        "listener UI no pertenece al PID/creation-time candidato atestiguado"
                    )
                listener_observed_ns = time.monotonic_ns()
                if cast(int, ready["ready_monotonic_ns"]) > listener_observed_ns:
                    raise ContractError("service-ready usa reloj posterior a su observación")
                self._candidate_process = dict(process)
                self._service_ready_identity = _control_identity(
                    self.service_ready_path, context="candidate service-ready"
                )
                self._listener_observed_monotonic_ns = listener_observed_ns
                return
            time.sleep(0.005)
        raise ContractError("servicio candidato no publicó READY dentro del deadline")

    def _serve(self) -> None:
        try:
            if self._server is None:  # pragma: no cover - invariante interno.
                raise RuntimeError("proxy no iniciado")
            client, _ = self._server.accept()
            with client:
                timeout = cast(float, self.ingress["timeout_seconds"])
                client.settimeout(timeout)
                first = client.recv(1)
                if len(first) != 1:
                    raise ContractError("proxy no recibió primer byte HTTP")
                body_identity = cast(dict[str, Any], self.ingress["body"])
                raw_request = self._recv_until(client, first, b"\r\n\r\n")
                request_headers, request_body = raw_request.split(b"\r\n\r\n", 1)
                request_line, headers = self._headers(request_headers, response=False)
                if request_line != f"POST {self.ingress['path']} HTTP/1.1":
                    raise ContractError("request-line no reconcilia POST/path")
                if headers.get("x-nikodym-request-id") != self.ingress["request_id"]:
                    raise ContractError("request_id HTTP no reconcilia")
                try:
                    content_length = int(headers.get("content-length", ""))
                except ValueError as exc:
                    raise ContractError("Content-Length inválido") from exc
                if content_length != body_identity["logical_bytes"]:
                    raise ContractError("Content-Length no reconcilia body firmado")
                self._wait_ready()
                backend = socket.create_connection(
                    (cast(str, self.service["host"]), cast(int, self.service["port"])),
                    timeout=timeout,
                )
                backend.settimeout(timeout)
                try:
                    # La frontera nace al entregar el primer byte al socket del servicio real,
                    # nunca al recibirlo en el proxy ni al observar la respuesta del cliente.
                    backend.sendall(raw_request[:1])
                    boundary_event = self.boundary.first_byte(
                        request_id=cast(str, self.ingress["request_id"]),
                        request_body_bytes=cast(int, body_identity["logical_bytes"]),
                        request_body_sha256=cast(str, body_identity["sha256"]),
                        service_descriptor_sha256=cast(
                            str, self.ingress["service_descriptor_sha256"]
                        ),
                        endpoint_sha256=cast(str, self.ingress["endpoint_sha256"]),
                    )
                    backend.sendall(raw_request[1:])
                    request_digest = hashlib.sha256(request_body)
                    observed_request = len(request_body)
                    while observed_request < content_length:
                        chunk = client.recv(min(1024 * 1024, content_length - observed_request))
                        if not chunk:
                            raise ContractError("request body truncado")
                        backend.sendall(chunk)
                        request_digest.update(chunk)
                        observed_request += len(chunk)
                    if (
                        observed_request != content_length
                        or request_digest.hexdigest() != body_identity["sha256"]
                    ):
                        raise ContractError("request body no reconcilia SHA/bytes")
                    first_response_byte = backend.recv(1)
                    first_response_ns = time.monotonic_ns()
                    if len(first_response_byte) != 1:
                        raise ContractError("servicio candidato cerró antes del primer byte")
                    raw_response = self._recv_until(backend, first_response_byte, b"\r\n\r\n")
                    response_headers, response_body = raw_response.split(b"\r\n\r\n", 1)
                    status_line, response_map = self._headers(response_headers, response=True)
                    status = int(status_line.split(" ", 2)[1])
                    try:
                        response_length = int(response_map.get("content-length", ""))
                    except ValueError as exc:
                        raise ContractError("response Content-Length inválido") from exc
                    oracle = cast(dict[str, Any], self.service["first_page_oracle"])
                    if (
                        response_length != oracle["response_body_bytes"]
                        or len(response_body) > response_length
                    ):
                        raise ContractError("response Content-Length no reconcilia oráculo/body")
                    client.sendall(raw_response)
                    response_digest = hashlib.sha256(response_body)
                    observed_response = len(response_body)
                    while observed_response < response_length:
                        chunk = backend.recv(min(1024 * 1024, response_length - observed_response))
                        if not chunk:
                            raise ContractError("response candidata truncada")
                        client.sendall(chunk)
                        response_digest.update(chunk)
                        observed_response += len(chunk)
                    content_type = response_map.get("content-type", "").split(";", 1)[0]
                    if (
                        status != oracle["expected_status"]
                        or content_type != oracle["content_type"]
                        or observed_response != oracle["response_body_bytes"]
                        or observed_response != response_length
                        or response_digest.hexdigest() != oracle["response_body_sha256"]
                    ):
                        raise ContractError("response no reconcilia first-page oracle")
                    response = {
                        "status": status,
                        "content_type": content_type,
                        "body_bytes": observed_response,
                        "body_sha256": response_digest.hexdigest(),
                        "first_byte_from_service_monotonic_ns": first_response_ns,
                    }
                    if (
                        self._candidate_process is None
                        or self._service_ready_identity is None
                        or self._listener_observed_monotonic_ns is None
                    ):  # pragma: no cover - _wait_ready establece los tres juntos.
                        raise RuntimeError("proxy perdió identidad del servicio candidato")
                    exchange = {
                        "schema_version": HTTP_EXCHANGE_SCHEMA_VERSION,
                        "attempt_id": self.attempt_id,
                        "candidate_request_sha256": self.candidate_request_sha256,
                        "request_id": self.ingress["request_id"],
                        "service_descriptor_sha256": self.ingress["service_descriptor_sha256"],
                        "endpoint_sha256": self.ingress["endpoint_sha256"],
                        "candidate_process": self._candidate_process,
                        "service_ready": self._service_ready_identity,
                        "request": {
                            "method": "POST",
                            "path": self.ingress["path"],
                            "body_bytes": body_identity["logical_bytes"],
                            "body_sha256": body_identity["sha256"],
                            "first_byte_to_service_monotonic_ns": boundary_event["monotonic_ns"],
                        },
                        "response": response,
                        "first_verifiable_page": oracle["first_verifiable_page"],
                        "non_transforming": True,
                    }
                    with self.http_exchange_path.open("xb") as handle:
                        handle.write(canonical_json_bytes(exchange) + b"\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    self.exchange_identity = _control_identity(
                        self.http_exchange_path, context="candidate HTTP exchange"
                    )
                    self.response = response
                finally:
                    backend.close()
        except BaseException as exc:
            self.error = exc
        finally:
            if self._server is not None:
                self._server.close()
            self.finished.set()

    def finish(self) -> dict[str, Any]:
        if not self.finished.wait(cast(float, self.ingress["timeout_seconds"])):
            self.close()
            raise ContractError("proxy HTTP agotó su deadline")
        if self._thread is not None:
            self._thread.join(timeout=0)
        if self.error is not None:
            raise ContractError(f"proxy HTTP falló: {self.error}") from self.error
        if self.response is None or self.exchange_identity is None:
            raise ContractError("proxy HTTP no acreditó respuesta real")
        return dict(self.exchange_identity)

    def close(self) -> None:
        if self._server is not None:
            with contextlib.suppress(OSError):
                self._server.close()


def _validate_pycache_isolation(workdir: Path, *, role: str) -> None:
    expected = (workdir.resolve() / "scratch" / "python-cache" / role).resolve()
    observed = sys.pycache_prefix
    if observed is None or Path(observed).resolve() != expected:
        raise ContractError(f"executor {role} no usa pycache_prefix fresco propiedad del arnés")
    if not expected.is_dir() or _is_reparse(expected) or any(expected.iterdir()):
        raise ContractError(f"pycache_prefix de {role} no está vacío/seguro")


def run_ui_client_request(
    request_path: Path,
    expected_sha256: str,
    *,
    authorization_gate_path: Path,
    trusted_authority_public_key_path: Path,
    workdir: Path,
    capability_commitment_sha256: str,
) -> int:
    """Executor público cerrado: valida y reclama autoridad antes de abrir el socket."""
    from .supervisor import (
        consume_launch_capability,
        require_calibration_start_implementation_ready,
    )

    require_calibration_start_implementation_ready()
    expected_request_sha = validate_sha256(expected_sha256, context="ui client request esperado")
    consume_launch_capability(
        role="ui-client",
        payload_sha256=expected_request_sha,
        expected_commitment_sha256=capability_commitment_sha256,
    )
    resolved_request = _absolute_path(str(request_path), context="ui-client request path")
    request = _read_canonical_control(resolved_request, context="ui-client request")
    if canonical_json_sha256(request) != expected_request_sha:
        raise ContractError("ui client request cambió después de ser firmado")
    canonical_request = canonical_json_bytes(request) + b"\n"
    from .supervisor import consume_internal_authorization_gate

    consume_internal_authorization_gate(
        gate_path=authorization_gate_path,
        role="ui-client",
        payload=request,
        capability_commitment_sha256=capability_commitment_sha256,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        workdir=workdir,
    )
    _validate_pycache_isolation(workdir, role="ui-client")
    # Ésta es la única ruta que toca red; no hay un callable executor sin gate.
    normalized = validate_ui_client_request(request)
    first_byte_path = cast(Path, normalized["first_byte_path"])
    if os.path.lexists(first_byte_path):
        raise ContractError("ui first-byte destino debe ser inexistente")
    deadline = time.monotonic() + cast(float, normalized["timeout_seconds"])
    connection: _NoRedirectConnection | None = None
    while connection is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ContractError("ui client agotó timeout esperando loopback")
        candidate_connection = _NoRedirectConnection(
            cast(str, normalized["loopback_host"]),
            cast(int, normalized["port"]),
            timeout=min(remaining, 1.0),
        )
        try:
            candidate_connection.connect()
        except OSError:
            candidate_connection.close()
            time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
            continue
        if candidate_connection.sock is None:  # pragma: no cover - defensa de stdlib.
            candidate_connection.close()
            raise ContractError("ui client conectó sin socket observable")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            candidate_connection.close()
            raise ContractError("ui client agotó timeout al conectar loopback")
        candidate_connection.sock.settimeout(remaining)
        connection = candidate_connection
    try:
        body = cast(dict[str, Any], normalized["body"])
        body_path = Path(str(body["path"]))
        if sha256_file(body_path) != body["sha256"]:
            raise ContractError("ui client body cambió antes del POST")
        connection.putrequest("POST", cast(str, normalized["path"]), skip_accept_encoding=True)
        connection.putheader("Connection", "close")
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(body["logical_bytes"]))
        connection.putheader("X-Nikodym-Request-Id", str(normalized["request_id"]))
        connection.endheaders()
        with body_path.open("rb") as body_handle:
            while chunk := body_handle.read(1024 * 1024):
                connection.send(chunk)
        response = connection.getresponse()
        if response.status != normalized["expected_status"]:
            raise ContractError(
                f"ui client status {response.status} != {normalized['expected_status']}"
            )
        first_byte = response.read(1)
        if len(first_byte) != 1:
            raise ContractError("ui client no recibió un primer byte de body")
        observed_ns = time.monotonic_ns()
        if resolved_request.read_bytes() != canonical_request:
            raise ContractError("ui client request cambió durante la solicitud")
        request_id = str(normalized["request_id"])
        _write_exclusive_regular_file(
            first_byte_path,
            canonical_json_bytes(
                {
                    "schema_version": UI_FIRST_BYTE_SCHEMA_VERSION,
                    "attempt_id": normalized["attempt_id"],
                    "event": "first_byte",
                    "monotonic_ns": observed_ns,
                    "request_id": request_id,
                }
            )
            + b"\n",
            context="ui first-byte sidecar",
        )
        while response.read(1024 * 1024):
            pass
    finally:
        connection.close()
    return 0


def _validate_initial_boundary(path: Path, *, boundary_kind: str) -> list[dict[str, Any]]:
    events = _read_jsonl(path, context="consumer boundary")
    if boundary_kind in {"first_open", "first_byte"}:
        validated = validate_consumer_boundary_events(events, require_complete=False)
        return [{str(key): value for key, value in event.items()} for event in validated]
    raise ContractError(f"boundary_kind fuera del catálogo: {boundary_kind}")


def _validate_result_inventory(
    result_path: Path,
    *,
    staging: Path,
    attempt_id: str,
    expected_identities: Sequence[str],
    expected_counts: Mapping[str, int],
    counter_adapter: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not result_path.is_file() or _is_reparse(result_path):
        raise ContractError("adapter-result ausente, symlink o reparse point")
    result = read_json_object(result_path)
    if result_path.read_bytes() != canonical_json_bytes(result) + b"\n":
        raise ContractError("adapter-result no usa JSON canónico con newline final")
    _require_exact(result, ("schema_version", "attempt_id", "outputs"), context="adapter-result")
    if (
        result["schema_version"] != CANDIDATE_OUTPUTS_SCHEMA_VERSION
        or result["attempt_id"] != attempt_id
    ):
        raise ContractError("adapter-result no reconcilia schema/attempt")
    raw_outputs = result["outputs"]
    if not isinstance(raw_outputs, list) or len(raw_outputs) != len(expected_identities):
        raise ContractError("adapter-result no tiene cardinalidad exacta")
    normalized: list[dict[str, Any]] = []
    sources: set[Path] = set()
    output_paths: set[str] = set()
    for ordinal, raw_output in enumerate(raw_outputs):
        output = _require_mapping(raw_output, context=f"adapter-result.outputs[{ordinal}]")
        _require_exact(
            output,
            ("identity", "source_relative_path", "output_relative_path", "format"),
            context=f"adapter-result.outputs[{ordinal}]",
        )
        identity = _require_text(output["identity"], context=f"output[{ordinal}].identity")
        if identity != expected_identities[ordinal]:
            raise ContractError("adapter-result identities no conservan orden exacto")
        source_relative = _safe_relative(
            output["source_relative_path"], context=f"output[{ordinal}].source_relative_path"
        )
        output_relative = _safe_relative(
            output["output_relative_path"], context=f"output[{ordinal}].output_relative_path"
        )
        output_format = _require_text(output["format"], context=f"output[{ordinal}].format")
        if output_format == "bin":
            if counter_adapter is None:
                raise ContractError(
                    "bin no es calificable hasta autorizar un counter adapter independiente"
                )
            raise ContractError("counter adapter bin aún no tiene implementación ejecutable")
        if output_format not in DERIVABLE_OUTPUT_FORMATS:
            raise ContractError(f"formato de output no derivable: {output_format!r}")
        if PurePosixPath(output_relative).suffix.casefold() != f".{output_format}":
            raise ContractError("formato y extensión de output no coinciden")
        source = (staging / Path(source_relative)).resolve(strict=False)
        if not _path_is_within(source, staging) or source == result_path:
            raise ContractError("source del adapter escapa de staging o es el resultado")
        if not source.is_file() or _is_reparse(source) or source.stat().st_nlink != 1:
            raise ContractError("source del adapter ausente, enlazado o reparse point")
        if source in sources or output_relative in output_paths:
            raise ContractError("adapter-result reutiliza source o ruta de output")
        sources.add(source)
        output_paths.add(output_relative)
        observed_count = derive_output_record_count(source, output_format=output_format)
        if observed_count != expected_counts[identity]:
            raise ContractError(f"{identity}: conteo reabierto no coincide con el fixture")
        normalized.append(
            {
                "identity": identity,
                "source": source,
                "source_relative_path": source_relative,
                "output_relative_path": output_relative,
                "format": output_format,
                "record_count": observed_count,
                "logical_bytes": source.stat().st_size,
                "sha256": sha256_file(source),
            }
        )
    files, directories = _plain_tree_inventory(staging, context="staging")
    observed_files = set(files)
    observed_dirs = {node.relative_to(staging).as_posix() for node in directories}
    if observed_files != {result_path, *sources}:
        raise ContractError("staging contiene archivos no declarados o incompletos")
    expected_dirs: set[str] = set()
    for item in normalized:
        parent = PurePosixPath(str(item["source_relative_path"])).parent
        while parent != PurePosixPath("."):
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    if observed_dirs != expected_dirs:
        raise ContractError("staging contiene directorios no declarados o vacíos")
    return normalized


def _verify_protected_files(paths: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = [*cast(list[dict[str, Any]], paths["inputs"]), cast(dict[str, Any], paths["config"])]
    bundle = paths["bundle"]
    if bundle is not None:
        entries.append(cast(dict[str, Any], bundle))
    observed: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        identity = _file_identity(entry, context=f"protected[{index}]", verify_content=True)
        observed.append(
            {
                "path": str(identity["path"]),
                "logical_bytes": int(identity["logical_bytes"]),
                "sha256": str(identity["sha256"]),
            }
        )
    return sorted(observed, key=lambda item: cast(str, item["path"]))


def _protected_material(
    paths: Mapping[str, Any], input_contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Reconcilia IDs lógicos con rutas que sólo conoce el broker confiable."""
    fixture_root = cast(Path, paths["fixture_root"])
    inputs_root = cast(Path, paths["inputs_root"])
    bundle_root = cast(Path, paths["bundle_root"])
    physical: list[tuple[str, str, Mapping[str, Any]]] = []
    for entry in cast(list[dict[str, Any]], paths["inputs"]):
        relative = Path(cast(str, entry["path"])).relative_to(inputs_root).as_posix()
        physical.append(("input", relative, entry))
    config = cast(dict[str, Any], paths["config"])
    physical.append(
        (
            "config",
            Path(cast(str, config["path"])).relative_to(fixture_root).as_posix(),
            config,
        )
    )
    bundle = cast(dict[str, Any] | None, paths["bundle"])
    if bundle is not None:
        physical.append(
            (
                "bundle",
                Path(cast(str, bundle["path"])).relative_to(bundle_root).as_posix(),
                bundle,
            )
        )
    material: list[dict[str, Any]] = []
    for role, relative_name, physical_entry in physical:
        logical_bytes = int(physical_entry["logical_bytes"])
        digest = cast(str, physical_entry["sha256"])
        logical_id = canonical_json_sha256(
            {
                "role": role,
                "relative_name": relative_name,
                "logical_bytes": logical_bytes,
                "sha256": digest,
            }
        )
        material.append(
            {
                "logical_id": logical_id,
                "role": role,
                "relative_name": relative_name,
                "logical_bytes": logical_bytes,
                "sha256": digest,
                "path": str(Path(cast(str, physical_entry["path"])).resolve()),
            }
        )
    material.sort(key=lambda item: cast(str, item["logical_id"]))
    logical = [
        {
            name: item[name]
            for name in (
                "logical_id",
                "role",
                "relative_name",
                "logical_bytes",
                "sha256",
            )
        }
        for item in material
    ]
    if logical != input_contract["protected"]:
        raise ContractError("input_contract no reconcilia con el material protegido exacto")
    return material


def _read_canonical_control(path: Path, *, context: str) -> dict[str, Any]:
    path = _absolute_path(str(path), context=f"{context}.path")
    if not path.is_file() or _is_reparse(path):
        raise ContractError(f"{context}: archivo ausente, symlink o reparse point")
    if path.stat().st_nlink != 1:
        raise ContractError(f"{context}: hardlink prohibido")
    value = read_json_object(path)
    if path.read_bytes() != canonical_json_bytes(value) + b"\n":
        raise ContractError(f"{context}: JSON no es canónico exacto")
    return value


def _write_exclusive_regular_file(path: Path, payload: bytes, *, context: str) -> None:
    """Publica bytes O_EXCL sin seguir un leaf dangling ni un ancestro reparse."""
    destination = _absolute_path(str(path), context=f"{context}.path")
    _require_plain_directory(destination.parent, context=f"{context}.parent")
    if os.path.lexists(destination):
        raise ContractError(f"{context}: destino ya existe o es enlace dangling")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(destination, flags, 0o600)
    except FileExistsError as exc:
        raise ContractError(f"{context}: carrera al crear destino exclusivo") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            destination.unlink()
        raise
    _file_identity(
        {
            "path": str(destination),
            "logical_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        context=context,
        verify_content=True,
    )


def _control_identity(path: Path, *, context: str) -> dict[str, Any]:
    """Reabre un control canónico y devuelve su identidad de bytes exactos."""
    _read_canonical_control(path, context=context)
    return _file_identity(
        {
            "path": str(Path(os.path.abspath(path))),
            "logical_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        },
        context=context,
        verify_content=True,
    )


def validate_candidate_service_ready(
    path: Path,
    *,
    attempt_id: str,
    candidate_request_sha256: str,
    candidate_process: Mapping[str, Any],
    service: Mapping[str, Any],
) -> dict[str, Any]:
    """Valida el READY durable emitido por el servicio candidato real."""
    value = _read_canonical_control(path, context="candidate service-ready")
    _require_exact(
        value,
        (
            "schema_version",
            "attempt_id",
            "candidate_request_sha256",
            "candidate_process",
            "host",
            "port",
            "ready_monotonic_ns",
        ),
        context="candidate service-ready",
    )
    expected = {
        "schema_version": CANDIDATE_SERVICE_READY_SCHEMA_VERSION,
        "attempt_id": validate_sha256(attempt_id, context="candidate service-ready.attempt_id"),
        "candidate_request_sha256": validate_sha256(
            candidate_request_sha256, context="candidate service-ready.request"
        ),
        "candidate_process": dict(candidate_process),
        "host": service["host"],
        "port": service["port"],
    }
    ready_ns = value["ready_monotonic_ns"]
    if (
        {name: value[name] for name in expected} != expected
        or isinstance(ready_ns, bool)
        or not isinstance(ready_ns, int)
        or ready_ns <= 0
    ):
        raise ContractError("candidate service-ready no reconcilia endpoint/attempt exactos")
    return value


def validate_candidate_http_exchange(
    path: Path,
    *,
    attempt_id: str,
    candidate_request_sha256: str,
    expected_ingress: Mapping[str, Any],
    expected_service: Mapping[str, Any],
    expected_candidate_process: Mapping[str, Any],
    expected_service_ready: Mapping[str, Any],
) -> dict[str, Any]:
    """Reabre el intercambio proxy→servicio y liga request, proceso, respuesta y oráculo."""
    value = _read_canonical_control(path, context="candidate HTTP exchange")
    _require_exact(
        value,
        (
            "schema_version",
            "attempt_id",
            "candidate_request_sha256",
            "request_id",
            "service_descriptor_sha256",
            "endpoint_sha256",
            "candidate_process",
            "service_ready",
            "request",
            "response",
            "first_verifiable_page",
            "non_transforming",
        ),
        context="candidate HTTP exchange",
    )
    if (
        value["schema_version"] != HTTP_EXCHANGE_SCHEMA_VERSION
        or value["attempt_id"] != validate_sha256(attempt_id, context="HTTP exchange attempt")
        or value["candidate_request_sha256"]
        != validate_sha256(candidate_request_sha256, context="HTTP exchange candidate request")
    ):
        raise ContractError("candidate HTTP exchange no liga schema/attempt/request")
    process = _require_mapping(value["candidate_process"], context="HTTP exchange process")
    _require_exact(process, ("pid", "creation_time_100ns"), context="HTTP exchange process")
    if process != dict(expected_candidate_process):
        raise ContractError("candidate HTTP exchange no liga PID/creation-time")
    ready_identity = _file_identity(
        value["service_ready"], context="HTTP exchange service-ready", verify_content=True
    )
    if ready_identity != dict(expected_service_ready):
        raise ContractError("candidate HTTP exchange no liga service-ready final")
    ready_value = validate_candidate_service_ready(
        Path(cast(str, ready_identity["path"])),
        attempt_id=attempt_id,
        candidate_request_sha256=candidate_request_sha256,
        candidate_process=process,
        service=expected_service,
    )
    request = _require_mapping(value["request"], context="HTTP exchange request")
    _require_exact(
        request,
        (
            "method",
            "path",
            "body_bytes",
            "body_sha256",
            "first_byte_to_service_monotonic_ns",
        ),
        context="HTTP exchange request",
    )
    boundary_ns = request["first_byte_to_service_monotonic_ns"]
    body = cast(Mapping[str, Any], expected_ingress["body"])
    if (
        request["method"] != "POST"
        or request["path"] != expected_ingress["path"]
        or request["body_bytes"] != body["logical_bytes"]
        or request["body_sha256"] != body["sha256"]
        or isinstance(boundary_ns, bool)
        or not isinstance(boundary_ns, int)
        or boundary_ns <= 0
        or boundary_ns < ready_value["ready_monotonic_ns"]
    ):
        raise ContractError("candidate HTTP exchange no acredita request no-transforming")
    response = _require_mapping(value["response"], context="HTTP exchange response")
    _require_exact(
        response,
        (
            "status",
            "content_type",
            "body_bytes",
            "body_sha256",
            "first_byte_from_service_monotonic_ns",
        ),
        context="HTTP exchange response",
    )
    first_response_ns = response["first_byte_from_service_monotonic_ns"]
    oracle = cast(Mapping[str, Any], expected_service["first_page_oracle"])
    if (
        response["status"] != oracle["expected_status"]
        or response["content_type"] != oracle["content_type"]
        or response["body_bytes"] != oracle["response_body_bytes"]
        or response["body_sha256"] != oracle["response_body_sha256"]
        or isinstance(first_response_ns, bool)
        or not isinstance(first_response_ns, int)
        or first_response_ns < boundary_ns
        or value["first_verifiable_page"] != oracle["first_verifiable_page"]
        or value["non_transforming"] is not True
        or value["request_id"] != expected_ingress["request_id"]
        or value["service_descriptor_sha256"] != expected_ingress["service_descriptor_sha256"]
        or value["endpoint_sha256"] != expected_ingress["endpoint_sha256"]
    ):
        raise ContractError("candidate HTTP exchange no reconcilia respuesta/oráculo")
    return value


class _ConsumerOpenBroker:
    """Prototipo de OPEN; no califica rutas mutables sin el lease continuo bloqueante."""

    def __init__(
        self,
        *,
        broker: Mapping[str, Any],
        attempt_id: str,
        protected: Sequence[Mapping[str, Any]],
        protected_material: Sequence[Mapping[str, Any]],
        candidate_start_path: Path,
        candidate_request_sha256: str,
        boundary: ConsumerBoundary,
        audit_path: Path,
    ) -> None:
        self.broker = dict(broker)
        self.attempt_id = attempt_id
        self.protected = [dict(item) for item in protected]
        self.material = [dict(item) for item in protected_material]
        self.candidate_start_path = candidate_start_path
        self.candidate_request_sha256 = candidate_request_sha256
        self.boundary = boundary
        self.audit_path = audit_path
        self.error: BaseException | None = None
        self.response: dict[str, Any] | None = None
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._finished = threading.Event()

    def start(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        server.bind((cast(str, self.broker["host"]), cast(int, self.broker["port"])))
        server.listen(1)
        server.settimeout(30.0)
        self._server = server
        self._thread = threading.Thread(
            target=self._serve, name="h9r-consumer-open-broker", daemon=False
        )
        self._thread.start()

    @staticmethod
    def _read_wire(connection: socket.socket) -> tuple[dict[str, Any], bytes]:
        payload = b""
        while not payload.endswith(b"\n"):
            chunk = connection.recv(64 * 1024)
            if not chunk:
                raise ContractError("consumer OPEN truncado")
            payload += chunk
            if len(payload) > 1024 * 1024:
                raise ContractError("consumer OPEN excede 1 MiB")
        try:
            raw: Any = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("consumer OPEN no es JSON UTF-8") from exc
        if not isinstance(raw, dict) or payload != canonical_json_bytes(raw) + b"\n":
            raise ContractError("consumer OPEN no es JSON canónico exacto")
        return cast(dict[str, Any], raw), payload

    def _candidate_process(self) -> dict[str, int]:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not self.candidate_start_path.is_file():
            time.sleep(0.005)
        start = _read_canonical_control(self.candidate_start_path, context="candidate-start")
        _require_exact(
            start,
            (
                "schema_version",
                "attempt_id",
                "candidate_request_sha256",
                "candidate_execution_request",
                "candidate_process",
            ),
            context="candidate-start",
        )
        if (
            start["schema_version"] != CANDIDATE_START_SCHEMA_VERSION
            or start["attempt_id"] != self.attempt_id
            or start["candidate_request_sha256"] != self.candidate_request_sha256
        ):
            raise ContractError("candidate-start no liga broker/request/attempt")
        _file_identity(
            start["candidate_execution_request"],
            context="candidate-start.execution_request",
            verify_content=True,
        )
        process = _require_mapping(start["candidate_process"], context="candidate-start.process")
        _require_exact(process, ("pid", "creation_time_100ns"), context="candidate-start.process")
        for name in process:
            if (
                isinstance(process[name], bool)
                or not isinstance(process[name], int)
                or process[name] <= 0
            ):
                raise ContractError(f"candidate-start.process.{name} inválido")
        return cast(dict[str, int], process)

    def _open_first_material(
        self, *, broker_request_sha256: str, candidate_process: Mapping[str, int]
    ) -> None:
        """Atestigua el primer input y emite la frontera antes del primer byte leído."""
        first = self.material[0]
        first_path = Path(cast(str, first["path"]))

        def emit_boundary() -> None:
            self.boundary.first_open(
                self.protected,
                request_id=cast(str, self.broker["request_id"]),
                broker_request_sha256=broker_request_sha256,
                nonce_commitment_sha256=cast(str, self.broker["nonce_commitment_sha256"]),
                candidate_process=candidate_process,
            )

        _read_bound_regular_file(
            first_path,
            context=f"consumer-open.{first['logical_id']}",
            expected_logical_bytes=cast(int, first["logical_bytes"]),
            expected_sha256=cast(str, first["sha256"]),
            before_read=emit_boundary,
        )

    def _serve(self) -> None:
        try:
            if self._server is None:  # pragma: no cover - invariante interno.
                raise RuntimeError("broker no iniciado")
            connection, _ = self._server.accept()
            with connection:
                connection.settimeout(30.0)
                wire, payload = self._read_wire(connection)
                expected = {
                    "schema_version": CONSUMER_OPEN_REQUEST_SCHEMA_VERSION,
                    "attempt_id": self.attempt_id,
                    "operation": "OPEN",
                    "request_id": self.broker["request_id"],
                    "nonce": self.broker["nonce"],
                    "protected": self.protected,
                }
                if wire != expected:
                    raise ContractError("consumer OPEN no reconcilia request/nonce/protected")
                broker_request_sha256 = hashlib.sha256(payload[:-1]).hexdigest()
                candidate_process = self._candidate_process()
                self._open_first_material(
                    broker_request_sha256=broker_request_sha256,
                    candidate_process=candidate_process,
                )
                for item in self.material[1:]:
                    path = Path(cast(str, item["path"]))
                    identity = _file_identity(
                        {
                            "path": str(path),
                            "logical_bytes": item["logical_bytes"],
                            "sha256": item["sha256"],
                        },
                        context=f"consumer-open.{item['logical_id']}",
                        verify_content=True,
                    )
                    if identity["path"] != str(path.resolve()):
                        raise ContractError("consumer OPEN resolvió otra ruta física")
                opened = [
                    {
                        "logical_id": item["logical_id"],
                        "path": item["path"],
                        "logical_bytes": item["logical_bytes"],
                        "sha256": item["sha256"],
                    }
                    for item in self.material
                ]
                response = {
                    "schema_version": CONSUMER_OPEN_RESPONSE_SCHEMA_VERSION,
                    "request_id": self.broker["request_id"],
                    "broker_request_sha256": broker_request_sha256,
                    "opened": opened,
                }
                connection.sendall(canonical_json_bytes(response) + b"\n")
                append_jsonl_event(
                    self.audit_path,
                    {
                        "schema_version": ADAPTER_AUDIT_SCHEMA_VERSION,
                        "event": "consumer_open_brokered",
                        "monotonic_ns": time.monotonic_ns(),
                        "request_id": self.broker["request_id"],
                        "broker_request_sha256": broker_request_sha256,
                        "nonce_commitment_sha256": self.broker["nonce_commitment_sha256"],
                        "candidate_process": candidate_process,
                        "protected": self.protected,
                    },
                )
                self.response = response
        except BaseException as exc:
            self.error = exc
        finally:
            if self._server is not None:
                self._server.close()
            self._finished.set()

    def finish(self, timeout_seconds: float) -> dict[str, Any]:
        if not self._finished.wait(timeout_seconds):
            self.close()
            raise ContractError("consumer OPEN broker agotó su deadline")
        if self._thread is not None:
            self._thread.join(timeout=0)
        if self.error is not None:
            raise ContractError(f"consumer OPEN broker falló: {self.error}") from self.error
        if self.response is None:
            raise ContractError("consumer OPEN broker no publicó respuesta")
        return dict(self.response)

    def close(self) -> None:
        if self._server is not None:
            with contextlib.suppress(OSError):
                self._server.close()


def _candidate_controller_environment(
    *,
    candidate_capability_secret: str,
    snapshot: Mapping[str, Any],
    workdir: Path,
    logical_cpu_count: int,
) -> dict[str, str]:
    """Crea un entorno mínimo para el controller; el child recibirá otra allowlist."""
    temp_root = workdir / "scratch" / "candidate-runtime" / "controller-temp"
    temp_root.mkdir(exist_ok=False)
    environment = _candidate_child_environment(
        Path("."),
        "0" * 64,
        temp_root=temp_root,
        logical_cpu_count=logical_cpu_count,
    )
    environment.pop("NIKODYM_H9R_CANDIDATE_REQUEST", None)
    environment.pop("NIKODYM_H9R_CANDIDATE_REQUEST_SHA256", None)
    environment["NIKODYM_H9R_CANDIDATE_CAPABILITY"] = candidate_capability_secret
    environment["NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST"] = cast(str, snapshot["path"])
    environment["NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST_SHA256"] = cast(str, snapshot["sha256"])
    return environment


def _candidate_controller_command(
    launch: Mapping[str, Any], *, workdir: Path
) -> tuple[list[str], dict[str, str]]:
    secret = os.environ.pop("NIKODYM_H9R_CANDIDATE_CAPABILITY", None)
    if secret is None:
        raise ContractError("adapter no recibió capability candidate del supervisor")
    request = cast(dict[str, Any], launch["candidate_request"])
    snapshot = cast(dict[str, Any], launch["harness_runtime_snapshot"])
    python = cast(dict[str, Any], launch["python_executable"])
    driver = cast(dict[str, Any], launch["driver"])
    command = [
        cast(str, python["path"]),
        "-I",
        "-B",
        "-S",
        "-X",
        f"pycache_prefix={workdir / 'scratch' / 'python-cache' / 'candidate'}",
        cast(str, driver["path"]),
        "_candidate",
        cast(str, request["path"]),
        cast(str, launch["candidate_request_payload_sha256"]),
        cast(str, launch["capability_commitment_sha256"]),
        str(cast(Path, launch["authorization_gate_path"])),
        str(cast(Path, launch["trusted_authority_public_key_path"])),
    ]
    return command, _candidate_controller_environment(
        candidate_capability_secret=secret,
        snapshot=snapshot,
        workdir=workdir,
        logical_cpu_count=cast(
            int,
            cast(
                dict[str, Any], cast(dict[str, Any], launch["candidate_request_value"])["runtime"]
            )["affinity_mask"],
        ).bit_count(),
    )


def _validate_candidate_process_census(
    raw: Any,
    *,
    root_process: Mapping[str, Any],
    total_processes: int,
) -> dict[str, Any]:
    census = _require_mapping(raw, context="candidate-result.process_census")
    _require_exact(
        census,
        ("source", "total_processes", "processes"),
        context="candidate-result.process_census",
    )
    raw_processes = census["processes"]
    if (
        census["source"] != "windows_job_completion_port_v1"
        or census["total_processes"] != total_processes
        or not isinstance(raw_processes, list)
        or len(raw_processes) != total_processes
    ):
        raise ContractError("candidate process census no liga accounting kernel")
    processes: list[dict[str, int]] = []
    identities: set[tuple[int, int]] = set()
    for index, raw_process in enumerate(raw_processes):
        process = _require_mapping(
            raw_process, context=f"candidate-result.process_census.processes[{index}]"
        )
        _require_exact(
            process,
            ("pid", "creation_time_100ns"),
            context=f"candidate-result.process_census.processes[{index}]",
        )
        pid = process["pid"]
        creation = process["creation_time_100ns"]
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(creation, bool)
            or not isinstance(creation, int)
            or creation <= 0
            or (pid, creation) in identities
        ):
            raise ContractError("candidate process census contiene identidad inválida/duplicada")
        identities.add((pid, creation))
        processes.append({"pid": pid, "creation_time_100ns": creation})
    if [(item["pid"], item["creation_time_100ns"]) for item in processes] != sorted(identities):
        raise ContractError("candidate process census no está ordenado canónicamente")
    root_identity = (root_process.get("pid"), root_process.get("creation_time_100ns"))
    if root_identity not in identities:
        raise ContractError("candidate process census omite la raíz exacta")
    return {**census, "processes": processes}


def _validate_output_isolation(raw: Any, *, output_root: Path, staging: Path) -> dict[str, Any]:
    """Reabre el censo de aislamiento y vuelve a medirlo contra el sistema operativo.

    No basta con que el candidato haya declarado la garantía: el adapter relee cada etiqueta
    después de la quiescencia, de modo que un candidato que hubiera conseguido reetiquetar una
    raíz protegida —o perder la suya— cae aquí y no llega al publisher.
    """
    isolation = _require_mapping(raw, context="candidate-result.output_isolation")
    _require_exact(
        isolation,
        (
            "schema_version",
            "mechanism",
            "candidate_token_integrity_sid",
            "candidate_effective_integrity_sid",
            "writable_roots",
            "protected_roots",
            "output_root",
            "output_root_present",
            "container_objects_inspected",
            "denial_probe",
            "observed_monotonic_ns",
        ),
        context="candidate-result.output_isolation",
    )
    observed_ns = isolation["observed_monotonic_ns"]
    inspected = isolation["container_objects_inspected"]
    if (
        isolation["schema_version"] != CANDIDATE_OUTPUT_ISOLATION_SCHEMA_VERSION
        or isolation["mechanism"] != SANDBOX_MECHANISM
        or isolation["candidate_token_integrity_sid"] != LOW_INTEGRITY_SID
        or isolation["candidate_effective_integrity_sid"] != LOW_INTEGRITY_SID
        or isolation["output_root_present"] is not False
        or isolation["output_root"] != str(output_root)
        or isinstance(inspected, bool)
        or not isinstance(inspected, int)
        or inspected <= 0
        or isinstance(observed_ns, bool)
        or not isinstance(observed_ns, int)
        or observed_ns <= 0
    ):
        raise ContractError("candidate-result.output_isolation no acredita el mecanismo OS")
    probe = _require_mapping(
        isolation["denial_probe"], context="candidate-result.output_isolation.denial_probe"
    )
    _require_exact(
        probe,
        ("performed", "probe_integrity_sid", "denied_operations", "returncode"),
        context="candidate-result.output_isolation.denial_probe",
    )
    if (
        probe["performed"] is not True
        or probe["probe_integrity_sid"] != LOW_INTEGRITY_SID
        or probe["denied_operations"] != list(DENIED_OPERATIONS)
        or probe["returncode"] != 0
    ):
        raise ContractError("output_isolation no acredita la denegación medida del sistema")
    writable = _require_mapping(
        isolation["writable_roots"], context="candidate-result.output_isolation.writable_roots"
    )
    protected = _require_mapping(
        isolation["protected_roots"], context="candidate-result.output_isolation.protected_roots"
    )
    if not writable or not protected or set(writable) & set(protected):
        raise ContractError("output_isolation declara raíces vacías o superpuestas")
    # Exigir sólo que `staging` y el padre de OUTPUT_ROOT aparezcan dejaría pasar una evidencia
    # que omitiera `candidate-runtime`, el `pycache_prefix` o `telemetry/control`: las raíces
    # restantes conservarían su etiqueta y el aislamiento quedaría acreditado con cobertura
    # parcial. El layout es cerrado, así que aquí se exige igualdad exacta contra él, no
    # pertenencia mínima. Las claves del censo son rutas resueltas: se comparan como tales.
    workdir = output_root.parent
    scratch = workdir / "scratch"
    telemetry = workdir / "telemetry"
    expected_writable = {
        str(staging.resolve()),
        str((scratch / "candidate-runtime").resolve()),
        str((scratch / "python-cache" / "candidate-child").resolve()),
    }
    expected_protected = {
        str(workdir.resolve()),
        str(scratch.resolve()),
        str((scratch / "python-cache").resolve()),
        str(telemetry.resolve()),
        str((telemetry / "control").resolve()),
    }
    if set(writable) != expected_writable:
        raise ContractError("output_isolation no declara exactamente las raíces escribibles")
    # La sexta protegida es el árbol candidato instalado, que no deriva del workdir: se exige que
    # sea exactamente una y que no caiga dentro de ninguna raíz escribible.
    extra_protected = set(protected) - expected_protected
    if not expected_protected <= set(protected) or len(extra_protected) != 1:
        raise ContractError("output_isolation no declara exactamente las raíces protegidas")
    candidate_root = Path(next(iter(extra_protected)))
    if any(
        candidate_root == Path(name) or candidate_root.is_relative_to(Path(name))
        for name in writable
    ):
        raise ContractError("output_isolation deja el árbol candidato bajo una raíz escribible")
    for name, value in writable.items():
        if value != LOW_INTEGRITY_SID or mandatory_label(Path(name)) != LOW_INTEGRITY_SID:
            raise ContractError(f"raíz escribible perdió la etiqueta Low efectiva: {name}")
    for name, value in protected.items():
        if value is not None or mandatory_label(Path(name)) is not None:
            raise ContractError(f"raíz protegida quedó con etiqueta obligatoria: {name}")
    return dict(isolation)


def _validate_candidate_execution(
    path: Path, *, attempt_id: str, candidate_request_sha256: str
) -> dict[str, Any]:
    result = _read_canonical_control(path, context="candidate-result")
    _require_exact(
        result,
        (
            "schema_version",
            "attempt_id",
            "candidate_request_sha256",
            "candidate_execution_request",
            "candidate_process",
            "output_isolation",
            "service_ready",
            "native_pools_observation",
            "total_processes",
            "candidate_process_census",
            "candidate_job_accounting",
            "returncode",
            "tree_quiescent",
            "tree_empty_monotonic_ns",
        ),
        context="candidate-result",
    )
    if (
        result["schema_version"] != CANDIDATE_RESULT_SCHEMA_VERSION
        or result["attempt_id"] != attempt_id
        or result["candidate_request_sha256"] != candidate_request_sha256
        or result["tree_quiescent"] is not True
    ):
        raise ContractError("candidate-result no liga request/attempt/quiescencia")
    execution_identity = _file_identity(
        result["candidate_execution_request"],
        context="candidate-result.execution_request",
        verify_content=True,
    )
    execution_value = _read_canonical_control(
        Path(cast(str, execution_identity["path"])), context="candidate execution request"
    )
    returncode = result["returncode"]
    total_processes = result["total_processes"]
    tree_empty_ns = result["tree_empty_monotonic_ns"]
    if (
        isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or isinstance(total_processes, bool)
        or not isinstance(total_processes, int)
        or total_processes < 1
        or isinstance(tree_empty_ns, bool)
        or not isinstance(tree_empty_ns, int)
        or tree_empty_ns <= 0
    ):
        raise ContractError("candidate-result returncode/reloj inválidos")
    process = _require_mapping(result["candidate_process"], context="candidate-result.process")
    _require_exact(process, ("pid", "creation_time_100ns"), context="candidate-result.process")
    for name in process:
        if (
            isinstance(process[name], bool)
            or not isinstance(process[name], int)
            or process[name] <= 0
        ):
            raise ContractError(f"candidate-result.process.{name} inválido")
    _validate_output_isolation(
        result["output_isolation"],
        output_root=path.parents[2] / "outputs",
        staging=path.parents[2] / "scratch" / "consumer-staging",
    )
    job_accounting = _require_mapping(
        result["candidate_job_accounting"], context="candidate-result.job_accounting"
    )
    if (
        job_accounting.get("source") != "windows_job_object"
        or job_accounting.get("total_processes") != total_processes
        or job_accounting.get("active_processes") != 0
        or job_accounting.get("memory_usage_information_supported") is not True
        or isinstance(job_accounting.get("current_job_memory_commit_bytes"), bool)
        or not isinstance(job_accounting.get("current_job_memory_commit_bytes"), int)
    ):
        raise ContractError("candidate-result no reconcilia accounting kernel del Job")
    process_census = _validate_candidate_process_census(
        result["candidate_process_census"],
        root_process=process,
        total_processes=total_processes,
    )
    observation = result["native_pools_observation"]
    if returncode == 0:
        if observation is None:
            raise ContractError("candidate-result exitoso omite native-pools observation")
        observation_identity = _file_identity(
            observation,
            context="candidate-result.native_pools_observation",
            verify_content=True,
        )
        if Path(cast(str, observation_identity["path"])) != path.with_name(
            "native-pools-observation.json"
        ):
            raise ContractError("candidate-result native-pools identity no usa path derivado")
        validate_native_pools_observation(
            Path(cast(str, observation_identity["path"])),
            candidate_execution_request_sha256=cast(str, execution_identity["sha256"]),
            native_pools_root=path.parents[2] / "scratch" / "candidate-runtime" / "native-pools",
            expected_process_census=cast(list[dict[str, Any]], process_census["processes"]),
        )
    elif observation is not None:
        raise ContractError("candidate-result fallido no puede acreditar observación final")
    service_ready = result["service_ready"]
    mode = execution_value.get("mode")
    if returncode == 0 and mode == "http-service":
        if service_ready is None:
            raise ContractError("candidate-result UI exitoso omite service-ready")
        ready_identity = _file_identity(
            service_ready, context="candidate-result.service_ready", verify_content=True
        )
        expected_ready_path = (
            path.parents[2] / "scratch" / "candidate-runtime" / "service-ready.json"
        )
        if Path(cast(str, ready_identity["path"])) != expected_ready_path:
            raise ContractError("candidate-result service-ready no usa path derivado")
        service = _require_mapping(
            execution_value.get("service"), context="candidate execution service"
        )
        validate_candidate_service_ready(
            expected_ready_path,
            attempt_id=attempt_id,
            candidate_request_sha256=candidate_request_sha256,
            candidate_process=process,
            service=service,
        )
    elif service_ready is not None:
        raise ContractError("candidate-result batch/fallido no puede acreditar service-ready")
    return {**result, "candidate_process_census": process_census}


def run_adapter_request(
    request_path: Path,
    expected_sha256: str,
    *,
    authorization_gate_path: Path,
    trusted_authority_public_key_path: Path,
    workdir: Path,
    capability_commitment_sha256: str,
) -> int:
    """Reclama el adapter sólo si la puerta acredita todas las fronteras OS pendientes."""
    from .supervisor import (
        consume_internal_authorization_gate,
        consume_launch_capability,
        require_calibration_start_implementation_ready,
    )

    require_calibration_start_implementation_ready()
    expected_request_sha = validate_sha256(expected_sha256, context="adapter request esperado")
    consume_launch_capability(
        role="adapter",
        payload_sha256=expected_request_sha,
        expected_commitment_sha256=capability_commitment_sha256,
    )
    resolved_request = _absolute_path(str(request_path), context="adapter request path")
    request = _read_canonical_control(resolved_request, context="adapter request")
    if canonical_json_sha256(request) != expected_request_sha:
        raise ContractError("adapter request cambió después de ser firmado")
    consume_internal_authorization_gate(
        gate_path=authorization_gate_path,
        role="adapter",
        payload=request,
        capability_commitment_sha256=capability_commitment_sha256,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        workdir=workdir,
    )
    _validate_pycache_isolation(workdir, role="adapter")
    normalized = validate_adapter_request(request)
    paths = cast(dict[str, Any], normalized["paths"])
    for name in ("boundary", "filesystem_events", "native_pools", "audit"):
        _prepare_sidecar(cast(Path, paths[name]), context=f"paths.{name}")
    ui_first_byte = cast(Path, paths["ui_first_byte"])
    if normalized["boundary_kind"] == "first_byte":
        if ui_first_byte.exists():
            raise ContractError("ui_first_byte debe ser creado por el cliente HTTP")
    else:
        _prepare_sidecar(ui_first_byte, context="paths.ui_first_byte")
    staging = cast(Path, paths["staging"])
    staging.mkdir(parents=True, exist_ok=False)
    boundary = ConsumerBoundary(
        cast(Path, paths["boundary"]), cast(Path, paths["filesystem_events"])
    )
    candidate_launch = cast(dict[str, Any], normalized["candidate_launch"])
    candidate_request = cast(dict[str, Any], candidate_launch["candidate_request_value"])
    candidate_request_sha = cast(str, candidate_launch["candidate_request_payload_sha256"])
    candidate_paths = cast(dict[str, Path], candidate_request["paths"])
    protected_material = _protected_material(
        paths, cast(dict[str, Any], candidate_request["input_contract"])
    )
    _verify_protected_files(paths)
    append_jsonl_event(
        cast(Path, paths["audit"]),
        {
            "schema_version": ADAPTER_AUDIT_SCHEMA_VERSION,
            "event": "broker_ready",
            "monotonic_ns": time.monotonic_ns(),
            "protected_count": len(protected_material),
        },
    )
    broker: _ConsumerOpenBroker | None = None
    ingress: _CandidateHttpProxy | None = None
    if normalized["boundary_kind"] == "first_open":
        broker = _ConsumerOpenBroker(
            broker=cast(dict[str, Any], candidate_request["broker"]),
            attempt_id=cast(str, normalized["attempt_id"]),
            protected=cast(
                list[dict[str, Any]],
                cast(dict[str, Any], candidate_request["input_contract"])["protected"],
            ),
            protected_material=protected_material,
            candidate_start_path=candidate_paths["candidate_start"],
            candidate_request_sha256=candidate_request_sha,
            boundary=boundary,
            audit_path=cast(Path, paths["audit"]),
        )
        broker.start()
    else:
        descriptor = cast(dict[str, Any], normalized["descriptor"])
        service = cast(
            dict[str, Any],
            cast(dict[str, Any], descriptor["implementation"])["service"],
        )
        ingress = _CandidateHttpProxy(
            ingress=cast(dict[str, Any], normalized["ui_ingress"]),
            service=service,
            service_ready_path=candidate_paths["service_ready"],
            http_exchange_path=workdir / "telemetry" / "control" / "candidate-http-exchange.json",
            candidate_start_path=candidate_paths["candidate_start"],
            candidate_request_sha256=candidate_request_sha,
            attempt_id=cast(str, normalized["attempt_id"]),
            boundary=boundary,
        )
        ingress.start()
    command, controller_environment = _candidate_controller_command(
        candidate_launch, workdir=workdir
    )
    controller_stdout = candidate_paths["controller_stdout"]
    controller_stderr = candidate_paths["controller_stderr"]
    try:
        with (
            controller_stdout.open("xb") as stdout_handle,
            controller_stderr.open("xb") as stderr_handle,
        ):
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    cwd=workdir,
                    env=controller_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout=cast(float, candidate_request["workload_deadline_seconds"]) + 30.0,
                )
            finally:
                for log_handle in (stdout_handle, stderr_handle):
                    log_handle.flush()
                    os.fsync(log_handle.fileno())
        if broker is not None:
            broker.finish(30.0)
        http_exchange_identity = ingress.finish() if ingress is not None else None
    finally:
        if broker is not None:
            broker.close()
        if ingress is not None:
            ingress.close()
    candidate_execution = _validate_candidate_execution(
        candidate_paths["candidate_result"],
        attempt_id=cast(str, normalized["attempt_id"]),
        candidate_request_sha256=candidate_request_sha,
    )
    if normalized["boundary_kind"] == "first_byte":
        if http_exchange_identity is None:
            raise ContractError("adapter UI omite HTTP exchange durable")
        service_ready_identity = _require_mapping(
            candidate_execution["service_ready"],
            context="adapter candidate service-ready",
        )
        validate_candidate_http_exchange(
            Path(cast(str, http_exchange_identity["path"])),
            attempt_id=cast(str, normalized["attempt_id"]),
            candidate_request_sha256=candidate_request_sha,
            expected_ingress=cast(dict[str, Any], normalized["ui_ingress"]),
            expected_service=cast(
                dict[str, Any],
                cast(dict[str, Any], normalized["descriptor"])["implementation"]["service"],
            ),
            expected_candidate_process=cast(
                dict[str, Any], candidate_execution["candidate_process"]
            ),
            expected_service_ready=service_ready_identity,
        )
    elif http_exchange_identity is not None:
        raise ContractError("adapter batch no puede acreditar HTTP exchange")
    if completed.returncode != 0:
        return completed.returncode
    observation_identity = _require_mapping(
        candidate_execution["native_pools_observation"],
        context="adapter candidate native-pools observation",
    )
    execution_identity = _require_mapping(
        candidate_execution["candidate_execution_request"],
        context="adapter candidate execution request",
    )
    total_processes = cast(int, candidate_execution["total_processes"])
    candidate_process_census = _require_mapping(
        candidate_execution["candidate_process_census"],
        context="adapter candidate process census",
    )
    native_pools = validate_native_pools_observation(
        Path(cast(str, observation_identity["path"])),
        candidate_execution_request_sha256=cast(str, execution_identity["sha256"]),
        native_pools_root=workdir / "scratch" / "candidate-runtime" / "native-pools",
        expected_process_census=cast(list[dict[str, Any]], candidate_process_census["processes"]),
    )
    sidecar_processes = [
        {
            name: process[name]
            for name in (
                "pid",
                "creation_time_100ns",
                "environment",
                "libraries",
                "process_thread_count",
            )
        }
        for process in cast(list[dict[str, Any]], native_pools["processes"])
    ]
    record_native_pools(
        cast(Path, paths["native_pools"]),
        total_processes=total_processes,
        processes=sidecar_processes,
    )
    validate_adapter_audit(cast(Path, paths["audit"]), require_success=True)
    _verify_protected_files(paths)
    if cast(Path, paths["filesystem_events"]).stat().st_size != 0:
        raise ContractError("candidate alcanzó el sidecar filesystem reservado")
    _validate_initial_boundary(
        cast(Path, paths["boundary"]), boundary_kind=cast(str, normalized["boundary_kind"])
    )
    expected = cast(dict[str, Any], normalized["expected"])
    outputs = _validate_result_inventory(
        cast(Path, paths["candidate_outputs"]),
        staging=staging,
        attempt_id=cast(str, normalized["attempt_id"]),
        expected_identities=cast(list[str], expected["identities"]),
        expected_counts=cast(dict[str, int], expected["counts"]),
        counter_adapter=cast(Mapping[str, Any] | None, normalized["counter_adapter"]),
    )
    if http_exchange_identity is not None:
        page = cast(
            dict[str, Any],
            cast(
                dict[str, Any],
                cast(dict[str, Any], normalized["descriptor"])["implementation"],
            )["service"]["first_page_oracle"]["first_verifiable_page"],
        )
        pages = [output for output in outputs if output["identity"] == page["identity"]]
        if len(pages) != 1 or {
            "relative_path": pages[0]["output_relative_path"],
            "logical_bytes": pages[0]["logical_bytes"],
            "sha256": pages[0]["sha256"],
        } != {
            "relative_path": page["relative_path"],
            "logical_bytes": page["logical_bytes"],
            "sha256": page["sha256"],
        }:
            raise ContractError("first-page oracle no reconcilia output real candidato")
    descriptor = cast(dict[str, Any], normalized["descriptor"])
    script_identity = cast(
        dict[str, Any], cast(dict[str, Any], descriptor["implementation"])["script"]
    )
    _file_identity(
        {
            "path": script_identity["path"],
            "logical_bytes": script_identity["bytes"],
            "sha256": script_identity["sha256"],
        },
        context="adapter.script.final",
        verify_content=True,
    )
    _file_identity(
        cast(dict[str, Any], normalized["descriptor_entry"]),
        context="adapter.descriptor.final",
        verify_content=True,
    )
    runtime = cast(dict[str, Any], normalized["runtime"])
    if (
        canonical_tree_identity(cast(Path, runtime["candidate_root"]))["sha256"]
        != runtime["candidate_tree_sha256"]
    ):
        raise ContractError("árbol candidato cambió durante el adapter")
    if cast(Path, paths["outputs"]).exists():
        raise ContractError("candidate alcanzó OUTPUT_ROOT fuera del publisher")
    candidate_tree_empty_ns = cast(int, candidate_execution["tree_empty_monotonic_ns"])
    publisher = ConsumerPublisher(cast(Path, paths["outputs"]), boundary)
    for ordinal, output in enumerate(outputs):
        publisher.publish_file(
            cast(str, output["output_relative_path"]),
            cast(str, output["identity"]),
            ordinal,
            cast(Path, output["source"]),
            output_format=cast(str, output["format"]),
        )
    publisher.finalize()
    final_boundary = _validate_initial_boundary(
        cast(Path, paths["boundary"]), boundary_kind=cast(str, normalized["boundary_kind"])
    )
    if candidate_tree_empty_ns > cast(int, final_boundary[-1]["monotonic_ns"]):
        raise ContractError("publisher terminó antes de la quiescencia candidate")
    validate_output_manifest(
        cast(Path, paths["outputs"]),
        expected_identities=cast(list[str], expected["identities"]),
        expected_counts=cast(dict[str, int], expected["counts"]),
        expected_golden_sha256=cast(str, expected["golden_observed_sha256"]),
    )
    adapter_result = {
        "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
        "attempt_id": normalized["attempt_id"],
        "candidate_execution": candidate_execution,
        "http_exchange": http_exchange_identity,
        "output_manifest_sha256": sha256_file(cast(Path, paths["outputs"]) / "manifest.json"),
    }
    with cast(Path, paths["adapter_result"]).open("xb") as handle:
        handle.write(canonical_json_bytes(adapter_result) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return 0


def adapter_protocol_schemas() -> dict[str, dict[str, Any]]:
    """Expone schemas cerrados auxiliares; la igualdad entre objetos se valida además en runtime."""
    return _adapter_protocol_schemas_v2()


def _adapter_protocol_schemas_v2() -> dict[str, dict[str, Any]]:
    """Modela los wire objects vigentes del child, broker, proxy y publisher."""
    sha = {
        "type": "string",
        "pattern": "^(?!0{64}$)(?!f{64}$)[0-9a-f]{64}$",
    }
    text = {"type": "string", "minLength": 1}
    non_negative = {"type": "integer", "minimum": 0}
    positive = {"type": "integer", "minimum": 1}
    port = {"type": "integer", "minimum": 1, "maximum": 65_535}

    def closed(properties: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": dict(properties),
            "required": list(properties),
        }

    def nullable(schema: Mapping[str, Any]) -> dict[str, Any]:
        return {"oneOf": [{"type": "null"}, dict(schema)]}

    def envelope(schema: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **dict(schema),
        }

    identity = closed({"path": text, "logical_bytes": non_negative, "sha256": sha})
    relative_file = closed({"relative_path": text, "bytes": non_negative, "sha256": sha})
    process_identity = closed({"pid": positive, "creation_time_100ns": positive})
    bindings = closed({name: sha for name in _BINDING_FIELDS})
    unit = closed(
        {
            "candidate_manifest_sha256": sha,
            "flow_id": {"enum": sorted({item.flow_id for item in ADAPTER_CATALOG})},
            "flow_step": {"enum": sorted({item.flow_step for item in ADAPTER_CATALOG})},
            "fixture_manifest_sha256": sha,
            "config_hash": sha,
            "geometry_id": {"enum": ["G-", "G0", "G+"]},
            "cap_id": {"enum": sorted(CAPS)},
            "attempt_ordinal": positive,
        }
    )
    protected = closed(
        {
            "logical_id": sha,
            "role": {"enum": ["input", "config", "bundle"]},
            "relative_name": text,
            "logical_bytes": non_negative,
            "sha256": sha,
        }
    )
    input_contract = closed(
        {
            "protocol_version": {"const": CONSUMER_OPEN_PROTOCOL_VERSION},
            "protected": {
                "type": "array",
                "items": protected,
                "minItems": 1,
                "uniqueItems": True,
            },
            "max_open_requests": {"const": 1},
        }
    )
    first_page = closed(
        {
            "identity": text,
            "relative_path": text,
            "logical_bytes": non_negative,
            "sha256": sha,
        }
    )
    oracle = closed(
        {
            "kind": {"const": "response-body-sha256-v1"},
            "expected_status": {"type": "integer", "minimum": 200, "maximum": 299},
            "content_type": text,
            "response_body_bytes": non_negative,
            "response_body_sha256": sha,
            "first_verifiable_page": first_page,
        }
    )
    service = closed(
        {
            "host": {"const": "127.0.0.1"},
            "port": port,
            "ready_timeout_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 60,
            },
        }
    )
    descriptor_service = closed({**service["properties"], "first_page_oracle": oracle})
    descriptor = closed(
        {
            "schema_version": {"const": ADAPTER_DESCRIPTOR_SCHEMA_VERSION},
            "attempt_id": sha,
            "unit": unit,
            "adapter_id": {"enum": sorted(ADAPTER_BY_ID)},
            "flow_id": {"enum": sorted({item.flow_id for item in ADAPTER_CATALOG})},
            "flow_step": {"enum": sorted({item.flow_step for item in ADAPTER_CATALOG})},
            "boundary_kind": {"enum": ["first_byte", "first_open"]},
            "bindings": bindings,
            "input_contract": input_contract,
            "implementation": closed(
                {
                    "kind": {
                        "enum": [
                            "candidate_brokered_script",
                            "candidate_http_service",
                        ]
                    },
                    "script": relative_file,
                    "argv_template": {
                        "type": "array",
                        "items": text,
                        "minItems": 1,
                    },
                    "isolation_flags": {"const": ["-I", "-B", "-S"]},
                    "service": nullable(descriptor_service),
                }
            ),
            "expected": closed(
                {
                    "identities": {"type": "array", "items": text, "minItems": 1},
                    "counts": {
                        "type": "object",
                        "additionalProperties": non_negative,
                        "minProperties": 1,
                    },
                    "golden_sha256": sha,
                }
            ),
        }
    )
    launch_path_names = (
        "staging",
        "candidate_outputs",
        "adapter_result",
        "candidate_stdout",
        "candidate_stderr",
        "candidate_controller_stdout",
        "candidate_controller_stderr",
        "candidate_start",
        "candidate_result",
    )
    launch_material = closed(
        {
            "schema_version": {"const": LAUNCH_BINDING_SCHEMA_VERSION},
            "protocol_version": {"const": PROTOCOL_VERSION},
            "attempt_id": sha,
            "unit": unit,
            "adapter_descriptor_sha256": sha,
            "harness_runtime_snapshot_sha256": sha,
            "candidate_manifest_sha256": sha,
            "fixture_manifest_sha256": sha,
            "config_hash": sha,
            "tooling_manifest_sha256": sha,
            "workdir_sha256": sha,
            "paths": closed({name: text for name in launch_path_names}),
        }
    )
    runtime = closed(
        {
            "candidate_root": text,
            "candidate_tree_sha256": sha,
            "python_executable": identity,
            "isolation_flags": {"const": ["-I", "-B", "-S"]},
            "job_memory_commit_limit_bytes": {
                "type": "integer",
                "enum": sorted(set(CAPS.values())),
            },
            "affinity_mask": positive,
        }
    )
    script = closed({"relative_path": text, "logical_bytes": non_negative, "sha256": sha})
    broker = closed(
        {
            "protocol_version": {"const": CONSUMER_OPEN_PROTOCOL_VERSION},
            "host": {"const": "127.0.0.1"},
            "port": port,
            "nonce": sha,
            "nonce_commitment_sha256": sha,
            "request_id": sha,
        }
    )
    candidate_path_names = (
        "staging",
        "candidate_outputs",
        "adapter_result",
        "brokered_inputs_json",
        "pycache",
        "stdout",
        "stderr",
        "controller_stdout",
        "controller_stderr",
        "service_ready",
        "candidate_start",
        "candidate_result",
    )
    candidate_launch_request = closed(
        {
            "schema_version": {"const": CANDIDATE_REQUEST_SCHEMA_VERSION},
            "attempt_id": sha,
            "mode": {"enum": ["batch", "http-service"]},
            "bindings": closed(
                {
                    "launch_binding_sha256": sha,
                    "harness_runtime_snapshot_sha256": sha,
                }
            ),
            "launch_material": launch_material,
            "script": script,
            "runtime": runtime,
            "input_contract": input_contract,
            "broker": nullable(broker),
            "paths": closed({name: text for name in candidate_path_names}),
            "argv_template": {"type": "array", "items": text, "minItems": 1},
            "service": nullable(service),
            "workload_deadline_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 10_800,
            },
        }
    )
    candidate_execution_request = closed(
        {
            "schema_version": {"const": CANDIDATE_EXECUTION_REQUEST_SCHEMA_VERSION},
            "attempt_id": sha,
            "candidate_request_sha256": sha,
            "mode": {"enum": ["batch", "http-service"]},
            "script_path": text,
            "candidate_root": text,
            "script": script,
            "input_contract": input_contract,
            "broker": nullable(broker),
            "paths": closed(
                {
                    name: text
                    for name in (
                        "staging",
                        "candidate_outputs",
                        "brokered_inputs_json",
                        "service_ready",
                    )
                }
            ),
            "argv_template": {"type": "array", "items": text, "minItems": 1},
            "service": nullable(service),
            "observer": closed({"threadpoolctl_import_root": text, "native_pools_root": text}),
        }
    )
    candidate_start = closed(
        {
            "schema_version": {"const": CANDIDATE_START_SCHEMA_VERSION},
            "attempt_id": sha,
            "candidate_request_sha256": sha,
            "candidate_execution_request": identity,
            "candidate_process": process_identity,
        }
    )
    environment = closed(
        {
            name: {"type": "string", "pattern": "^[1-4]$"}
            for name in (
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "BLIS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        }
    )
    library = closed(
        {
            "library": text,
            "version": text,
            "threading_layer": text,
            "effective_threads": {"type": "integer", "minimum": 1, "maximum": 4},
        }
    )
    process_fields: dict[str, Any] = {
        "pid": positive,
        "creation_time_100ns": positive,
        "environment": environment,
        "libraries": {"type": "array", "items": library, "uniqueItems": True},
        "process_thread_count": positive,
    }
    native_process = closed(
        {
            "schema_version": {"const": NATIVE_POOLS_PROCESS_OBSERVATION_SCHEMA_VERSION},
            "candidate_execution_request_sha256": sha,
            **process_fields,
        }
    )
    native_aggregate = closed(
        {
            "schema_version": {"const": NATIVE_POOLS_OBSERVATION_SCHEMA_VERSION},
            "candidate_execution_request_sha256": sha,
            "total_processes": positive,
            "processes": {
                "type": "array",
                "items": closed({**process_fields, "source": identity}),
                "minItems": 1,
                "uniqueItems": True,
            },
        }
    )
    service_ready = closed(
        {
            "schema_version": {"const": CANDIDATE_SERVICE_READY_SCHEMA_VERSION},
            "attempt_id": sha,
            "candidate_request_sha256": sha,
            "candidate_process": process_identity,
            "host": {"const": "127.0.0.1"},
            "port": port,
            "ready_monotonic_ns": positive,
        }
    )
    http_exchange = closed(
        {
            "schema_version": {"const": HTTP_EXCHANGE_SCHEMA_VERSION},
            "attempt_id": sha,
            "candidate_request_sha256": sha,
            "request_id": sha,
            "service_descriptor_sha256": sha,
            "endpoint_sha256": sha,
            "candidate_process": process_identity,
            "service_ready": identity,
            "request": closed(
                {
                    "method": {"const": "POST"},
                    "path": text,
                    "body_bytes": non_negative,
                    "body_sha256": sha,
                    "first_byte_to_service_monotonic_ns": positive,
                }
            ),
            "response": closed(
                {
                    "status": {"type": "integer", "minimum": 200, "maximum": 299},
                    "content_type": text,
                    "body_bytes": non_negative,
                    "body_sha256": sha,
                    "first_byte_from_service_monotonic_ns": positive,
                }
            ),
            "first_verifiable_page": first_page,
            "non_transforming": {"const": True},
        }
    )
    process_census = closed(
        {
            "source": {"const": "windows_job_completion_port_v1"},
            "total_processes": positive,
            "processes": {
                "type": "array",
                "items": process_identity,
                "minItems": 1,
                "uniqueItems": True,
            },
        }
    )
    io = closed(
        {
            name: non_negative
            for name in (
                "read_operations",
                "write_operations",
                "other_operations",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        }
    )
    accounting = closed(
        {
            "source": {"const": "windows_job_object"},
            "total_user_time_100ns": non_negative,
            "total_kernel_time_100ns": non_negative,
            "total_user_seconds": {"type": "number", "minimum": 0},
            "total_kernel_seconds": {"type": "number", "minimum": 0},
            "total_page_fault_count": non_negative,
            "total_processes": positive,
            "active_processes": {"const": 0},
            "total_terminated_processes": non_negative,
            "peak_process_memory_commit_bytes": non_negative,
            "peak_job_memory_commit_bytes": non_negative,
            "current_job_memory_commit_bytes": non_negative,
            "memory_usage_information_supported": {"const": True},
            "io": io,
        }
    )
    output_isolation = closed(
        {
            "schema_version": {"const": CANDIDATE_OUTPUT_ISOLATION_SCHEMA_VERSION},
            "mechanism": {"const": SANDBOX_MECHANISM},
            "candidate_token_integrity_sid": {"const": LOW_INTEGRITY_SID},
            "candidate_effective_integrity_sid": {"const": LOW_INTEGRITY_SID},
            "writable_roots": {
                "type": "object",
                "minProperties": CANDIDATE_WRITABLE_ROOT_COUNT,
                "maxProperties": CANDIDATE_WRITABLE_ROOT_COUNT,
                "additionalProperties": {"const": LOW_INTEGRITY_SID},
            },
            "protected_roots": {
                "type": "object",
                "minProperties": CANDIDATE_PROTECTED_ROOT_COUNT,
                "maxProperties": CANDIDATE_PROTECTED_ROOT_COUNT,
                "additionalProperties": {"type": "null"},
            },
            "output_root": text,
            "output_root_present": {"const": False},
            "container_objects_inspected": positive,
            "denial_probe": closed(
                {
                    "performed": {"const": True},
                    "probe_integrity_sid": {"const": LOW_INTEGRITY_SID},
                    "denied_operations": {"const": list(DENIED_OPERATIONS)},
                    "returncode": {"const": 0},
                }
            ),
            "observed_monotonic_ns": positive,
        }
    )
    candidate_result = closed(
        {
            "schema_version": {"const": CANDIDATE_RESULT_SCHEMA_VERSION},
            "attempt_id": sha,
            "candidate_request_sha256": sha,
            "candidate_execution_request": identity,
            "candidate_process": process_identity,
            "output_isolation": output_isolation,
            "service_ready": nullable(identity),
            "native_pools_observation": nullable(identity),
            "total_processes": positive,
            "candidate_process_census": process_census,
            "candidate_job_accounting": accounting,
            "returncode": {"type": "integer"},
            "tree_quiescent": {"const": True},
            "tree_empty_monotonic_ns": positive,
        }
    )
    adapter_paths = closed(
        {
            "fixture_root": text,
            "inputs_root": text,
            "inputs": {"type": "array", "items": identity, "minItems": 1},
            "bundle_root": text,
            "bundle": nullable(identity),
            "config": identity,
            "staging": text,
            "candidate_outputs": text,
            "adapter_result": text,
            "outputs": text,
            "boundary": text,
            "filesystem_events": text,
            "native_pools": text,
            "audit": text,
            "ui_first_byte": text,
        }
    )
    ui_ingress = closed(
        {
            "loopback_host": {"enum": ["127.0.0.1", "localhost"]},
            "port": port,
            "path": text,
            "timeout_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 60,
            },
            "expected_status": {"type": "integer", "minimum": 200, "maximum": 299},
            "request_id": sha,
            "body": identity,
            "service_descriptor_sha256": sha,
            "endpoint_sha256": sha,
        }
    )
    candidate_controller = closed(
        {
            "python_executable": identity,
            "driver": identity,
            "candidate_request": identity,
            "candidate_request_payload_sha256": sha,
            "capability_commitment_sha256": sha,
            "authorization_gate_path": text,
            "trusted_authority_public_key_path": text,
            "harness_runtime_snapshot": identity,
        }
    )
    adapter_request = closed(
        {
            "schema_version": {"const": ADAPTER_REQUEST_SCHEMA_VERSION},
            "attempt_id": sha,
            "flow_id": {"enum": sorted({item.flow_id for item in ADAPTER_CATALOG})},
            "flow_step": {"enum": sorted({item.flow_step for item in ADAPTER_CATALOG})},
            "adapter_id": {"enum": sorted(ADAPTER_BY_ID)},
            "bindings": bindings,
            "descriptor": identity,
            "runtime": runtime,
            "paths": adapter_paths,
            "ui_ingress": nullable(ui_ingress),
            "expected": closed(
                {
                    "identities": {"type": "array", "items": text, "minItems": 1},
                    "counts": {
                        "type": "object",
                        "additionalProperties": non_negative,
                        "minProperties": 1,
                    },
                    "golden_observed_sha256": sha,
                }
            ),
            "counter_adapter": {"type": "null"},
            "candidate_launch": candidate_controller,
        }
    )
    adapter_result = closed(
        {
            "schema_version": {"const": ADAPTER_RESULT_SCHEMA_VERSION},
            "attempt_id": sha,
            "candidate_execution": candidate_result,
            "http_exchange": nullable(identity),
            "output_manifest_sha256": sha,
        }
    )
    counter = closed(
        {
            "schema_version": {"const": COUNTER_ADAPTER_SCHEMA_VERSION},
            "counter_id": text,
            "format": {"const": "bin"},
            "bindings": bindings,
            "implementation": closed(
                {"kind": {"const": "signed_python_script"}, "script": relative_file}
            ),
            "result_contract": closed(
                {
                    "schema_version": {"const": COUNTER_RESULT_SCHEMA_VERSION},
                    "required_fields": {
                        "const": [
                            "schema_version",
                            "counter_id",
                            "output_sha256",
                            "records",
                        ]
                    },
                }
            ),
        }
    )
    ui_client = closed(
        {
            "schema_version": {"const": UI_CLIENT_REQUEST_SCHEMA_VERSION},
            "attempt_id": sha,
            "method": {"const": "POST"},
            "loopback_host": {"enum": ["127.0.0.1", "localhost"]},
            "port": port,
            "path": text,
            "timeout_seconds": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 60,
            },
            "expected_status": {"type": "integer", "minimum": 200, "maximum": 299},
            "body": identity,
            "request_id": sha,
            "first_byte_path": text,
        }
    )
    return {
        "adapter_descriptor": envelope(descriptor),
        "candidate_launch_request": envelope(candidate_launch_request),
        "candidate_execution_request": envelope(candidate_execution_request),
        "candidate_start": envelope(candidate_start),
        "native_pools_process_observation": envelope(native_process),
        "native_pools_observation": envelope(native_aggregate),
        "candidate_service_ready": envelope(service_ready),
        "candidate_http_exchange": envelope(http_exchange),
        "candidate_result": envelope(candidate_result),
        "adapter_request": envelope(adapter_request),
        "adapter_result": envelope(adapter_result),
        "counter_adapter": envelope(counter),
        "ui_client_request": envelope(ui_client),
    }
