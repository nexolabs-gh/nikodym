"""Artefacto verificable del arnés H9R que nunca materializa ni emite START."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from .aggregate import validate_statistical_progression
from .artifacts import (
    AtomicOutputPublisher,
    JsonlRecorder,
    atomic_write_json_exclusive,
    canonical_tree_identity,
    census_roots,
    disk_footprint_summary,
    validate_census_against_filesystem,
    validate_output_manifest,
    verify_jsonl_sidecar,
)
from .contracts import (
    ADAPTER_IDS,
    AUTHORIZATION_SCHEMA_VERSION,
    CAPS,
    CLASSIFICATIONS,
    FLOW_SPECS,
    GEOMETRY_IDS,
    HARNESS_TEST_SCHEMA_VERSION,
    MIB,
    RUN_MIN_AVAILABLE_PHYSICAL_BYTES,
    RUN_MIN_COMMIT_HEADROOM_BYTES,
    RUN_MIN_DISK_FREE_BYTES,
    ContractError,
    aggregate_json_schema,
    attempt_id,
    attempt_json_schema,
    authority_signing_bytes,
    authorization_consumption_path_digest,
    authorization_statement,
    canonical_json_bytes,
    canonical_json_sha256,
    internal_authorization_gate_json_schema,
    internal_authorization_precommit_json_schema,
    internal_authorization_release_json_schema,
    post_start_failure_json_schema,
    pre_start_failure_json_schema,
    preflight_rejection_json_schema,
    read_json_object,
    robust_summary,
    sha256_bytes,
    sha256_file,
    trusted_authority_key_identity,
    validate_authority,
    validate_boundary_events,
    validate_preflight_rejection_evidence,
)
from .copy_gate import (
    CopyGateError,
    assert_documented_h9r_catalog,
    assert_documented_h9r_runtime_catalog,
    assert_no_h9r_capacity_copy,
    scan_capacity_claims,
)
from .supervisor import Handshake
from .telemetry import POOL_ENVIRONMENT_KEYS, SequenceSensor, TelemetrySampler
from .windows_job import (
    WindowsJob,
    current_process_affinity,
    first_cpu_mask,
    resume_suspended_process,
    system_memory_status,
)

CONTROL_IDS = (
    "authority_preflight",
    "fifth_cpu",
    "c_plus_one_small_cap",
    "short_deadline",
    "injected_memory_disk_guards",
    "frontier_pre_start_post_generation",
    "completeness_missing_extra",
    "order_duplicate_permuted",
    "atomic_crash",
    "sidecar_tampered_missing",
    "disk_allocation_temporaries",
    "statistics_missing_max_discard",
    "copy",
)

_CONTROL_FIELDS = {
    "green_before",
    "red_observed",
    "red_cause",
    "restoration",
    "green_after",
    "evidence",
}


def _assert_schema_objects_closed(node: Any, *, path: str = "$") -> int:
    """Exige que todo objeto del schema cierre claves, incluso dentro de arrays/$defs."""
    count = 0
    if isinstance(node, dict):
        if node.get("type") == "object":
            count += 1
            if node.get("additionalProperties") is not False:
                raise RuntimeError(f"objeto JSON Schema abierto: {path}")
        for key, value in node.items():
            count += _assert_schema_objects_closed(value, path=f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            count += _assert_schema_objects_closed(value, path=f"{path}[{index}]")
    return count


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _restoration_sha256(paths: Sequence[Path]) -> str:
    """Firma sólo bytes/rutas relativas del estado que un control debe restaurar."""
    material: list[dict[str, Any]] = []
    for ordinal, path in enumerate(paths):
        if path.is_dir():
            identity = canonical_tree_identity(path)
            material.append(
                {
                    "ordinal": ordinal,
                    "name": path.name,
                    "kind": "directory",
                    **identity,
                }
            )
        elif path.is_file():
            material.append(
                {
                    "ordinal": ordinal,
                    "name": path.name,
                    "kind": "file",
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        else:
            material.append(
                {
                    "ordinal": ordinal,
                    "name": path.name,
                    "kind": "absent",
                }
            )
    return str(canonical_json_sha256(material))


def _observe_red(
    operation: Callable[[], Any],
    *,
    expected_exception: type[Exception] = ContractError,
    contains: str | None = None,
) -> str:
    """Ejecuta el defecto y devuelve la causa exacta que produjo rojo."""
    try:
        operation()
    except expected_exception as exc:
        if contains is not None and contains not in str(exc):
            raise RuntimeError(
                f"causa roja inesperada: esperado={contains!r}, observado={str(exc)!r}"
            ) from exc
        return f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # pragma: no cover - distingue una falla del propio self-test.
        raise RuntimeError(
            f"el control produjo otra excepción: {type(exc).__name__}: {exc}"
        ) from exc
    raise RuntimeError("el defecto inyectado no produjo rojo")


def _control_result(
    *,
    red_causes: Sequence[str],
    before_sha256: str,
    after_sha256: str,
    restoration_scope: Sequence[str],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not red_causes or any(not cause for cause in red_causes):
        raise RuntimeError("control sin causa roja exacta")
    if before_sha256 != after_sha256:
        raise RuntimeError(
            f"restauración no fue byte-exacta: before={before_sha256}, after={after_sha256}"
        )
    result = {
        "green_before": True,
        "red_observed": True,
        "red_cause": list(red_causes),
        "restoration": {
            "scope": list(restoration_scope),
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "byte_exact": True,
        },
        "green_after": True,
        "evidence": dict(evidence),
    }
    if set(result) != _CONTROL_FIELDS:
        raise AssertionError("shape interno de control desincronizado")
    return result


def _harness_module_inventory(checkout_root: Path) -> list[dict[str, Any]]:
    """Censa driver y todos los módulos Python del paquete del arnés."""
    scripts_root = checkout_root / "scripts"
    paths = [scripts_root / "__init__.py", scripts_root / "measure_readiness_h9r.py"]
    paths.extend(sorted((scripts_root / "readiness_h9r").rglob("*.py")))
    if not paths or any(not path.is_file() or path.is_symlink() for path in paths):
        raise ContractError("censo de módulos H9R contiene ausencias o symlinks")
    return [
        {
            "relative_path": path.relative_to(checkout_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def _source_identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "present": True,
        "safe_regular_file": True,
        "rejection": None,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _control_authority_preflight(root: Path) -> dict[str, Any]:
    control_root = root / "authority-preflight"
    control_root.mkdir()
    unit = {
        "candidate_manifest_sha256": sha256_bytes(b"candidate-harness-test"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": sha256_bytes(b"fixture-harness-test"),
        "config_hash": sha256_bytes(b"config-harness-test"),
        "geometry_id": "G-",
        "cap_id": "C4",
        "attempt_ordinal": 1,
    }
    unit_path = control_root / "unit.json"
    _write_json(unit_path, unit)
    document_path = control_root / "protocol.md"
    document_path.write_bytes(b"H9R harness-test-only\n")
    tooling_path = control_root / "tooling.json"
    _write_json(tooling_path, {"mode": "harness-test-only"})
    schedule_path = control_root / "schedule.json"
    _write_json(schedule_path, {"mode": "synthetic-no-start"})
    document_hashes = {"protocol": sha256_file(document_path)}
    tooling_sha256 = sha256_file(tooling_path)
    schedule_sha256 = sha256_file(schedule_path)
    authorization_id = sha256_bytes(b"authority-id-harness-test")
    authorization_consumption_path = control_root / "authorization-consumption.json"
    authorization_consumption_path_sha256 = authorization_consumption_path_digest(
        authorization_consumption_path
    )
    authorization_path = control_root / "authorization.txt"
    authorization_bytes = authorization_statement(
        unit,
        authorization_id=authorization_id,
        authorization_consumption_path_sha256=authorization_consumption_path_sha256,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        schedule_position=0,
        scope="harness-test-only",
    )
    authorization_path.write_bytes(authorization_bytes)

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key_path = control_root / "authority-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    signer_sha256 = trusted_authority_key_identity(public_key_path)[1]
    authority: dict[str, Any] = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "scope": "harness-test-only",
        "start_authorized": False,
        "authorization_id": authorization_id,
        "authorization_consumption_path_sha256": (authorization_consumption_path_sha256),
        "authorized_unit": unit,
        "attempt_id": attempt_id(unit),
        "authorization_text_sha256": sha256_bytes(authorization_bytes),
        "document_sha256": document_hashes,
        "tooling_sha256": tooling_sha256,
        "schedule_sha256": schedule_sha256,
        "schedule_position": 0,
        "signer_public_key_sha256": signer_sha256,
        "signature_ed25519": "0" * 128,
    }
    authority["signature_ed25519"] = private_key.sign(authority_signing_bytes(authority)).hex()
    authority_path = control_root / "authority.json"
    _write_json(authority_path, authority)

    candidate_path = control_root / "candidate.json"
    fixture_path = control_root / "fixture.json"
    config_path = control_root / "config.json"
    prior_path = control_root / "prior-evidence.json"
    for path, payload in (
        (candidate_path, {"control": "candidate-not-executed"}),
        (fixture_path, {"control": "fixture-not-generated"}),
        (config_path, {"control": "config"}),
        (prior_path, []),
    ):
        if isinstance(payload, list):
            path.write_bytes(canonical_json_bytes(payload) + b"\n")
        else:
            _write_json(path, payload)

    launch_paths = {
        "unit": unit_path,
        "authority": authority_path,
        "authorization_text": authorization_path,
        "trusted_authority_public_key": public_key_path,
        "candidate_manifest": candidate_path,
        "fixture_manifest": fixture_path,
        "config": config_path,
        "schedule": schedule_path,
        "prior_evidence_paths": prior_path,
    }
    workdir = control_root / "workdir-never-created"
    rejection_path = control_root / "preflight-rejection.json"
    rejection = {
        "schema_version": "nikodym.readiness.h9r.preflight-rejection.v1",
        "phase": "preflight",
        "identity": {
            "unit": unit,
            "attempt_id": attempt_id(unit),
            "evidence_path": str(rejection_path.resolve()),
            "wall_time_finished_utc": "2026-08-13T00:00:00+00:00",
        },
        "launch_sources": {
            "unit_path": str(unit_path.resolve()),
            "authority_path": str(authority_path.resolve()),
            "authorization_text_path": str(authorization_path.resolve()),
            "trusted_authority_public_key_path": str(public_key_path.resolve()),
            "candidate_manifest_path": str(candidate_path.resolve()),
            "fixture_manifest_path": str(fixture_path.resolve()),
            "config_path": str(config_path.resolve()),
            "schedule_path": str(schedule_path.resolve()),
            "prior_evidence_paths_path": str(prior_path.resolve()),
            "document_paths": {"protocol": str(document_path.resolve())},
            "workdir": str(workdir.resolve()),
        },
        "observed": {
            "source_identities": {
                **{name: _source_identity(path) for name, path in launch_paths.items()},
                "document:protocol": _source_identity(document_path),
            },
            "workdir_state": {
                "path": str(workdir.resolve()),
                "existed_before": False,
                "exists_after": False,
                "entries_before": [],
                "entries_after": [],
            },
        },
        "termination": {
            "classification": "preflight_rejected",
            "start_count": 0,
            "ready_count": 0,
            "worker_spawned": False,
            "cleanup_complete": True,
            "workdir_removed": True,
        },
        "gates": {"no_start": True, "no_worker": True, "evidence_atomic": True},
        "reasons": ["defecto sintético anterior a cualquier worker"],
    }
    _write_json(rejection_path, rejection)
    handshake_state_path = control_root / "handshake-rejection-state.json"
    handshake_green_state = {
        "mode": "reject-only",
        "start_events": 0,
        "start_tokens_emitted": 0,
        "workload_started": False,
    }
    _write_json(handshake_state_path, handshake_green_state)
    state_paths = (authority_path, rejection_path, handshake_state_path)
    before_sha256 = _restoration_sha256(state_paths)

    def validate_green() -> dict[str, Any]:
        observed_authority = validate_authority(
            read_json_object(authority_path),
            unit,
            document_hashes=document_hashes,
            tooling_sha256=tooling_sha256,
            schedule_sha256=schedule_sha256,
            schedule_position=0,
            trusted_authority_public_key_path=public_key_path,
        )
        observed_rejection = validate_preflight_rejection_evidence(read_json_object(rejection_path))
        observed_handshake_state = read_json_object(handshake_state_path)
        if observed_handshake_state != handshake_green_state:
            raise ContractError("estado seguro del Handshake no fue restaurado")
        return {
            "scope": observed_authority["scope"],
            "start_authorized": observed_authority["start_authorized"],
            "preflight_classification": observed_rejection["termination"]["classification"],
            "start_tokens_emitted": observed_handshake_state["start_tokens_emitted"],
            "workload_started": observed_handshake_state["workload_started"],
        }

    green_before = validate_green()
    authority_original = authority_path.read_bytes()
    tampered_authority = read_json_object(authority_path)
    signature = str(tampered_authority["signature_ed25519"])
    tampered_authority["signature_ed25519"] = signature[:-1] + (
        "0" if signature[-1] != "0" else "1"
    )
    _write_json(authority_path, tampered_authority)
    authority_cause = _observe_red(
        lambda: validate_authority(
            read_json_object(authority_path),
            unit,
            document_hashes=document_hashes,
            tooling_sha256=tooling_sha256,
            schedule_sha256=schedule_sha256,
            schedule_position=0,
            trusted_authority_public_key_path=public_key_path,
        ),
        contains="firma Ed25519 de autoridad inválida",
    )
    authority_path.write_bytes(authority_original)

    rejection_original = rejection_path.read_bytes()
    tampered_rejection = read_json_object(rejection_path)
    cast(dict[str, Any], tampered_rejection["gates"])["no_start"] = False
    _write_json(rejection_path, tampered_rejection)
    preflight_cause = _observe_red(
        lambda: validate_preflight_rejection_evidence(read_json_object(rejection_path)),
        contains="gates del rechazo preflight no estan verdes",
    )
    rejection_path.write_bytes(rejection_original)

    expected_authority_digest = sha256_bytes(authorization_bytes)
    effective_limits = {
        "logical_cpu_count": 4,
        "affinity_mask": 15,
        "job_memory_commit_limit_bytes": CAPS["C4"],
        "group_affinities": [{"processor_group": 0, "affinity_mask": 15}],
        "kill_on_job_close": True,
        "affinity_enforced": True,
        "job_memory_enforced": True,
    }
    handshake_original = handshake_state_path.read_bytes()

    before_ready = Handshake(
        expected_authority_text_sha256=expected_authority_digest,
        expected_affinity_mask=15,
        expected_memory_bytes=CAPS["C4"],
        expected_processor_group=0,
    )
    _write_json(
        handshake_state_path,
        {
            **handshake_green_state,
            "mode": "injected-start-before-ready",
        },
    )
    start_before_ready_cause = _observe_red(
        lambda: before_ready.start(authorization_text_sha256=expected_authority_digest),
        contains="START antes de READY",
    )
    before_ready_start_events = sum(event["event"] == "start" for event in before_ready.events)
    if before_ready.state != "created" or before_ready_start_events != 0 or before_ready.events:
        raise RuntimeError("START-before-READY produjo token, evento o avance de estado")
    handshake_state_path.write_bytes(handshake_original)

    wrong_authority = Handshake(
        expected_authority_text_sha256=expected_authority_digest,
        expected_affinity_mask=15,
        expected_memory_bytes=CAPS["C4"],
        expected_processor_group=0,
    )
    wrong_authority.boot(pid=1)
    wrong_authority.limits_applied(effective_limits)
    wrong_authority.ready()
    _write_json(
        handshake_state_path,
        {
            **handshake_green_state,
            "mode": "injected-wrong-authority-digest",
        },
    )
    wrong_authority_cause = _observe_red(
        lambda: wrong_authority.start(
            authorization_text_sha256=sha256_bytes(b"wrong-authority-digest")
        ),
        contains="autoridad START no coincide",
    )
    wrong_authority_start_events = sum(
        event["event"] == "start" for event in wrong_authority.events
    )
    if wrong_authority.state != "ready" or wrong_authority_start_events != 0:
        raise RuntimeError("digest de autoridad incorrecto produjo token o evento START")
    handshake_state_path.write_bytes(handshake_original)

    after_sha256 = _restoration_sha256(state_paths)
    green_after = validate_green()
    if green_before != green_after:
        raise RuntimeError("authority/preflight no volvió al mismo resultado verde")
    return _control_result(
        red_causes=(
            authority_cause,
            preflight_cause,
            start_before_ready_cause,
            wrong_authority_cause,
        ),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=(
            "authority.json",
            "preflight-rejection.json",
            "handshake-rejection-state.json",
        ),
        evidence={
            **green_after,
            "signature_algorithm": "Ed25519",
            "trust_anchor": "ephemeral-harness-test-only",
            "protocol_start_tokens": 0,
            "worker_spawned": False,
            "handshake_rejections": {
                "start_before_ready": {
                    "final_state": before_ready.state,
                    "start_events": before_ready_start_events,
                    "start_token_emitted": False,
                    "workload_started": False,
                },
                "wrong_authority_digest": {
                    "final_state": wrong_authority.state,
                    "start_events": wrong_authority_start_events,
                    "start_token_emitted": False,
                    "workload_started": False,
                },
            },
        },
    )


def _empty_root_metrics(name: str) -> dict[str, Any]:
    return {
        "root": name,
        "logical_bytes": 0,
        "allocated_bytes": 0,
        "files": 0,
        "allocation_reliable": True,
        "allocation_sources": [],
    }


def _telemetry_sample(
    *,
    physical_available_bytes: int = 4 * 1024**3,
    commit_available_bytes: int = 4 * 1024**3,
    disk_free_bytes: int = 20 * 1024**3,
    logical_cpu_count: int = 4,
    affinity_mask: int = 15,
) -> dict[str, Any]:
    process_metric = {
        "pid": 10,
        "creation_time_100ns": 20,
        "cpu_user_100ns": 0,
        "cpu_kernel_100ns": 0,
        "page_fault_count": 0,
        "working_set_bytes": 0,
        "peak_working_set_bytes": 0,
        "pagefile_bytes": 0,
        "peak_pagefile_bytes": 0,
        "private_usage_bytes": 0,
        "logical_cpu_count_effective": logical_cpu_count,
        "affinity_mask": affinity_mask,
        "system_affinity_mask": affinity_mask,
        "processor_groups": [0],
        "io": {
            "read_operations": 0,
            "write_operations": 0,
            "other_operations": 0,
            "read_bytes": 0,
            "write_bytes": 0,
            "other_bytes": 0,
        },
    }
    supervisor_metric = copy.deepcopy(process_metric)
    supervisor_metric["pid"] = 12
    supervisor_metric["creation_time_100ns"] = 22
    return {
        "job": {
            "source": "windows_job_object",
            "total_user_time_100ns": 0,
            "total_kernel_time_100ns": 0,
            "total_user_seconds": 0.0,
            "total_kernel_seconds": 0.0,
            "total_page_fault_count": 0,
            "total_processes": 1,
            "active_processes": 1,
            "total_terminated_processes": 0,
            "peak_process_memory_commit_bytes": 0,
            "peak_job_memory_commit_bytes": 0,
            "current_job_memory_commit_bytes": 0,
            "memory_usage_information_supported": True,
            "io": {
                "read_operations": 0,
                "write_operations": 0,
                "other_operations": 0,
                "read_bytes": 0,
                "write_bytes": 0,
                "other_bytes": 0,
            },
        },
        "tree": {
            "pids": [10],
            "processes": [process_metric],
            "threads": [
                {
                    "pid": 10,
                    "tid": 11,
                    "creation_time_100ns": 21,
                    "affinity_mask": affinity_mask if logical_cpu_count <= 4 else 15,
                    "processor_group": 0,
                    "logical_cpu_count_effective": min(logical_cpu_count, 4),
                }
            ],
            "process_query_errors": [],
            "thread_query_errors": [],
        },
        "system_memory": {
            "physical_total_bytes": 8 * 1024**3,
            "physical_available_bytes": physical_available_bytes,
            "commit_limit_bytes": 8 * 1024**3,
            "commit_available_bytes": commit_available_bytes,
            "commit_used_bytes": 8 * 1024**3 - commit_available_bytes,
            "memory_load_percent": 50,
            "virtual_total_bytes": 16 * 1024**3,
            "virtual_available_bytes": 8 * 1024**3,
        },
        "system_cpu": {"user_100ns": 0, "kernel_100ns": 0, "idle_100ns": 0},
        "disk": {
            "volume_free_bytes": disk_free_bytes,
            "roots": {
                name: _empty_root_metrics(name)
                for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
            },
        },
        "external_processes": {
            "supervisor": supervisor_metric,
            "client": None,
            "client_job": None,
            "host_processes": {
                "processes": [],
                "query_errors": [],
                "coverage": {
                    "enumerated_process_count": 0,
                    "observed_process_count": 0,
                    "query_error_count": 0,
                    "expected_query_error_count": 0,
                    "unexpected_query_error_count": 0,
                    "snapshot_complete": True,
                },
            },
        },
        "native_pools": {name: "4" for name in POOL_ENVIRONMENT_KEYS},
    }


def _run_injected_sampler(
    samples: Sequence[Mapping[str, Any]],
    *,
    sidecar_path: Path,
    expected_affinity_mask: int = 15,
) -> dict[str, Any]:
    sampler = TelemetrySampler(
        sensor=SequenceSensor([copy.deepcopy(dict(sample)) for sample in samples]),
        sidecar_path=sidecar_path,
        expected_affinity_mask=expected_affinity_mask,
        expected_processor_group=0,
    )
    for _ in samples:
        sampler.sample_once()
    result = sampler.stop()
    verify_jsonl_sidecar(cast(Mapping[str, Any], result["sidecar"]))
    return {
        "classification": sampler.guard_classification,
        "reason": sampler.guard_reason,
        "records": cast(dict[str, Any], result["sidecar"])["records"],
    }


def _control_fifth_cpu(root: Path) -> dict[str, Any]:
    control_root = root / "fifth-cpu"
    control_root.mkdir()
    state_path = control_root / "sample.json"
    _write_json(state_path, _telemetry_sample())
    before_sha256 = _restoration_sha256((state_path,))

    green_before = _run_injected_sampler(
        [read_json_object(state_path)], sidecar_path=control_root / "green-before.jsonl"
    )
    if green_before["classification"] is not None:
        raise RuntimeError("muestra de cuatro CPU no fue verde")

    original = state_path.read_bytes()
    injected = read_json_object(state_path)
    process = cast(dict[str, Any], cast(dict[str, Any], injected["tree"])["processes"][0])
    process["logical_cpu_count_effective"] = 5
    process["affinity_mask"] = 31
    process["system_affinity_mask"] = 31
    _write_json(state_path, injected)
    red = _run_injected_sampler(
        [read_json_object(state_path)], sidecar_path=control_root / "red.jsonl"
    )
    if red["classification"] != "limits_not_applied" or not red["reason"]:
        raise RuntimeError("la quinta CPU inyectada no produjo limits_not_applied")
    red_cause = f"limits_not_applied: {red['reason']}"
    state_path.write_bytes(original)

    affinity = current_process_affinity()
    selected_mask = first_cpu_mask(affinity["process_mask"])
    selected_count = selected_mask.bit_count()
    if selected_count not in {1, 2, 3, 4}:
        raise ContractError("control de quinta CPU no pudo seleccionar entre una y cuatro CPU")
    with WindowsJob(memory_bytes=128 * MIB, affinity_mask=selected_mask) as job:
        kernel_limits = job.effective_limits()
    effective_outside_mask = int(kernel_limits["affinity_mask"]) & ~selected_mask
    if (
        kernel_limits["logical_cpu_count"] != selected_count
        or kernel_limits["affinity_mask"] != selected_mask
        or effective_outside_mask != 0
    ):
        raise RuntimeError("censo kernel efectivo expuso una quinta CPU")

    after_sha256 = _restoration_sha256((state_path,))
    green_after = _run_injected_sampler(
        [read_json_object(state_path)], sidecar_path=control_root / "green-after.jsonl"
    )
    if green_after != green_before:
        raise RuntimeError("control de quinta CPU no volvió a verde")
    return _control_result(
        red_causes=(red_cause,),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("sample.json",),
        evidence={
            "injected_logical_cpu_count": 5,
            "negative_injection": "synthetic-telemetry-fifth-cpu",
            "physical_fifth_cpu_required": False,
            "host_process_logical_cpu_count": affinity["process_mask"].bit_count(),
            "host_system_logical_cpu_count": affinity["system_mask"].bit_count(),
            "effective_logical_cpu_count": kernel_limits["logical_cpu_count"],
            "effective_affinity_mask": kernel_limits["affinity_mask"],
            "effective_outside_selected_mask": effective_outside_mask,
            "effective_fifth_cpu_visible": False,
        },
    )


def _small_cap_green(cap_bytes: int, affinity_mask: int) -> dict[str, Any]:
    with WindowsJob(memory_bytes=cap_bytes, affinity_mask=affinity_mask) as job:
        limits = job.effective_limits()
    if (
        limits["job_memory_commit_limit_bytes"] != cap_bytes
        or limits["logical_cpu_count"] != affinity_mask.bit_count()
        or limits["job_memory_enforced"] is not True
    ):
        raise RuntimeError("cap pequeño de control no quedó efectivo")
    return limits


def _control_c_plus_one(root: Path, checkout_root: Path) -> dict[str, Any]:
    control_root = root / "c-plus-one"
    control_root.mkdir()
    cap_bytes = 96 * MIB
    state_path = control_root / "request.json"
    _write_json(
        state_path,
        {"test_only_small_cap_bytes": cap_bytes, "mode": "effective-limit-check"},
    )
    before_sha256 = _restoration_sha256((state_path,))
    selected_mask = first_cpu_mask(current_process_affinity()["process_mask"])
    green_before = _small_cap_green(cap_bytes, selected_mask)
    memory_before = system_memory_status()

    original = state_path.read_bytes()
    _write_json(
        state_path,
        {
            "test_only_small_cap_bytes": cap_bytes,
            "mode": "VirtualAlloc-C-plus-one",
            "request_bytes": cap_bytes + 1,
        },
    )
    environment = {**os.environ, "NIKODYM_H9R_CONTROL_JOB_CAP_BYTES": str(cap_bytes)}
    child = subprocess.Popen(
        [sys.executable, "-m", "scripts.readiness_h9r.probes", "memory"],
        cwd=checkout_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x00000004,
    )
    violation: dict[str, Any] = {}
    try:
        with WindowsJob(memory_bytes=cap_bytes, affinity_mask=selected_mask) as job:
            job.assign(child.pid)
            resume_suspended_process(child.pid, job.api)
            stdout, stderr = child.communicate(timeout=20)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                violation = job.memory_limit_violation()
                if violation["job_memory_limit_violated"]:
                    break
                time.sleep(0.01)
            if child.returncode != 86 or stderr:
                raise RuntimeError(
                    "VirtualAlloc C+1 no devolvió el rechazo esperado: "
                    f"rc={child.returncode}, stdout={stdout!r}, stderr={stderr!r}"
                )
            if not violation.get("job_memory_limit_violated"):
                raise RuntimeError("el puerto de completion no observó el hard cap C+1")
            if not job.wait_empty(5):
                raise RuntimeError("probe C+1 dejó procesos en el Job")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    red_cause = (
        "job_memory_limit: Windows Job completion port observó VirtualAlloc(C+1) "
        f"con request_bytes={cap_bytes + 1}"
    )
    state_path.write_bytes(original)
    memory_after = system_memory_status()
    if (
        min(
            memory_before["physical_available_bytes"],
            memory_after["physical_available_bytes"],
            memory_before["commit_available_bytes"],
            memory_after["commit_available_bytes"],
        )
        <= RUN_MIN_COMMIT_HEADROOM_BYTES
    ):
        raise RuntimeError("control C+1 se ejecutó sin headroom seguro del host")
    after_sha256 = _restoration_sha256((state_path,))
    green_after = _small_cap_green(cap_bytes, selected_mask)
    if green_before != green_after:
        raise RuntimeError("cap pequeño no volvió al mismo verde")
    return _control_result(
        red_causes=(red_cause,),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("request.json",),
        evidence={
            "test_only_small_cap_bytes": cap_bytes,
            "requested_bytes": cap_bytes + 1,
            "probe_returncode": child.returncode,
            "hard_limit_message_observed": violation["hard_limit_message_observed"],
            "host_oom": False,
        },
    )


def _run_deadline_process(
    *,
    delay_seconds: float,
    deadline_seconds: float,
    affinity_mask: int,
) -> dict[str, Any]:
    child = subprocess.Popen(
        [sys.executable, "-c", f"import time;time.sleep({delay_seconds!r})"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x00000004,
    )
    timed_out = False
    try:
        with WindowsJob(memory_bytes=128 * MIB, affinity_mask=affinity_mask) as job:
            job.assign(child.pid)
            resume_suspended_process(child.pid, job.api)
            deadline = time.monotonic() + deadline_seconds
            while child.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    job.terminate(0xE00000D1)
                    break
                time.sleep(0.005)
            stdout, stderr = child.communicate(timeout=10)
            if not job.wait_empty(5):
                raise RuntimeError("deadline controlado dejó procesos en el Job")
            return {
                "classification": "watchdog_deadline" if timed_out else "completed",
                "returncode": child.returncode,
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
                "tree_empty": True,
            }
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def _control_short_deadline(root: Path) -> dict[str, Any]:
    control_root = root / "short-deadline"
    control_root.mkdir()
    state_path = control_root / "deadline.json"
    green_spec = {"delay_seconds": 0.01, "deadline_seconds": 1.0}
    _write_json(state_path, green_spec)
    before_sha256 = _restoration_sha256((state_path,))
    affinity_mask = first_cpu_mask(current_process_affinity()["process_mask"])
    green_before = _run_deadline_process(affinity_mask=affinity_mask, **green_spec)
    if green_before["classification"] != "completed":
        raise RuntimeError("deadline holgado no fue verde")

    original = state_path.read_bytes()
    red_spec = {"delay_seconds": 0.5, "deadline_seconds": 0.05}
    _write_json(state_path, red_spec)
    red = _run_deadline_process(affinity_mask=affinity_mask, **red_spec)
    if red["classification"] != "watchdog_deadline" or red["tree_empty"] is not True:
        raise RuntimeError("deadline pequeño no disparó watchdog con cleanup")
    red_cause = (
        f"watchdog_deadline: proceso controlado excedió {red_spec['deadline_seconds']:.6f} s"
    )
    state_path.write_bytes(original)
    after_sha256 = _restoration_sha256((state_path,))
    green_after = _run_deadline_process(affinity_mask=affinity_mask, **green_spec)
    if green_after["classification"] != "completed":
        raise RuntimeError("deadline restaurado no volvió a verde")
    return _control_result(
        red_causes=(red_cause,),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("deadline.json",),
        evidence={
            "test_only_deadline_seconds": red_spec["deadline_seconds"],
            "test_only_delay_seconds": red_spec["delay_seconds"],
            "cleanup_tree_empty": red["tree_empty"],
        },
    )


def _control_injected_guards(root: Path) -> dict[str, Any]:
    control_root = root / "injected-guards"
    control_root.mkdir()
    state_path = control_root / "sample.json"
    _write_json(state_path, _telemetry_sample())
    before_sha256 = _restoration_sha256((state_path,))
    green_before = _run_injected_sampler(
        [read_json_object(state_path)], sidecar_path=control_root / "green-before.jsonl"
    )
    if green_before["classification"] is not None:
        raise RuntimeError("muestra base de guardas no fue verde")
    original = state_path.read_bytes()

    memory_sample = read_json_object(state_path)
    system_memory = cast(dict[str, Any], memory_sample["system_memory"])
    system_memory["physical_available_bytes"] = RUN_MIN_AVAILABLE_PHYSICAL_BYTES - 1
    system_memory["commit_available_bytes"] = RUN_MIN_COMMIT_HEADROOM_BYTES - 1
    system_memory["commit_used_bytes"] = int(system_memory["commit_limit_bytes"]) - int(
        system_memory["commit_available_bytes"]
    )
    _write_json(state_path, memory_sample)
    memory_red = _run_injected_sampler(
        [read_json_object(state_path), read_json_object(state_path)],
        sidecar_path=control_root / "memory-red.jsonl",
    )
    if memory_red["classification"] != "safety_abort_system_memory":
        raise RuntimeError("guarda de memoria inyectada no produjo clasificación exacta")
    memory_cause = f"safety_abort_system_memory: {memory_red['reason']}"

    disk_sample = json.loads(original)
    cast(dict[str, Any], disk_sample["disk"])["volume_free_bytes"] = RUN_MIN_DISK_FREE_BYTES - 1
    _write_json(state_path, disk_sample)
    disk_red = _run_injected_sampler(
        [read_json_object(state_path)], sidecar_path=control_root / "disk-red.jsonl"
    )
    if disk_red["classification"] != "safety_abort_disk":
        raise RuntimeError("guarda de disco inyectada no produjo clasificación exacta")
    disk_cause = f"safety_abort_disk: {disk_red['reason']}"

    state_path.write_bytes(original)
    after_sha256 = _restoration_sha256((state_path,))
    green_after = _run_injected_sampler(
        [read_json_object(state_path)], sidecar_path=control_root / "green-after.jsonl"
    )
    if green_after != green_before:
        raise RuntimeError("guardas inyectadas no volvieron a verde")
    return _control_result(
        red_causes=(memory_cause, disk_cause),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("sample.json",),
        evidence={
            "memory_consecutive_samples": memory_red["records"],
            "disk_samples": disk_red["records"],
            "sensors": ["physical_available", "commit_available", "volume_free"],
        },
    )


def _control_frontier(root: Path) -> dict[str, Any]:
    control_root = root / "frontier"
    control_root.mkdir()
    state_path = control_root / "events.json"
    protected_identity = {
        "role": "input",
        "relative_name": "input.bin",
        "logical_bytes": 1,
        "sha256": sha256_bytes(b"frontier-input"),
    }
    protected = [
        {
            "logical_id": canonical_json_sha256(protected_identity),
            **protected_identity,
        }
    ]
    effective_limits = {
        "limit_flags": 1,
        "affinity_mask": 15,
        "logical_cpu_count": 4,
        "processor_group": 0,
        "group_affinities": [{"processor_group": 0, "affinity_mask": 15}],
        "job_memory_commit_limit_bytes": CAPS["C4"],
        "kill_on_job_close": True,
        "affinity_enforced": True,
        "job_memory_enforced": True,
    }
    green_events = [
        {
            "event": "boot",
            "monotonic_ns": 1,
            "pid": 123,
            "heavy_work_started": False,
        },
        {
            "event": "limits_applied",
            "monotonic_ns": 2,
            "effective_limits": effective_limits,
        },
        {"event": "ready", "monotonic_ns": 3, "heavy_work_started": False},
        {"event": "start", "monotonic_ns": 4},
        {
            "event": "first_open_or_byte",
            "monotonic_ns": 5,
            "kind": "first_open",
            "provider": "harness_owned_consumer_open_v1",
            "request_id": sha256_bytes(b"frontier-open-request"),
            "protected": protected,
            "broker_request_sha256": sha256_bytes(b"frontier-broker-request"),
            "nonce_commitment_sha256": sha256_bytes(b"frontier-nonce"),
            "candidate_process": {"pid": 321, "creation_time_100ns": 654},
        },
        {
            "event": "flush_complete",
            "monotonic_ns": 6,
            "artifact_count": 1,
            "logical_bytes": 1,
        },
        {
            "event": "hash_complete",
            "monotonic_ns": 7,
            "artifact_count": 1,
            "artifact_sha256": [sha256_bytes(b"frontier-output")],
        },
        {
            "event": "rename_complete",
            "monotonic_ns": 8,
            "path": "outputs/manifest.json",
            "sha256": sha256_bytes(b"frontier-manifest"),
        },
        {"event": "tree_empty", "monotonic_ns": 9},
    ]
    _write_json(state_path, {"synthetic_events": green_events})
    before_sha256 = _restoration_sha256((state_path,))

    def validate_state() -> dict[str, int]:
        value = read_json_object(state_path)["synthetic_events"]
        if not isinstance(value, list):
            raise ContractError("eventos sintéticos no son lista")
        return validate_boundary_events(
            [cast(dict[str, Any], event) for event in value], require_complete=True
        )

    green_before = validate_state()
    original = state_path.read_bytes()
    early = copy.deepcopy(green_events)
    first = next(event for event in early if event["event"] == "first_open_or_byte")
    early.remove(first)
    first["monotonic_ns"] = 4
    early.insert(3, first)
    for index, event in enumerate(early, start=1):
        event["monotonic_ns"] = index
    _write_json(state_path, {"synthetic_events": early})
    early_cause = _observe_red(validate_state, contains="orden de frontera")
    state_path.write_bytes(original)

    late_generation = copy.deepcopy(green_events)
    late_generation.insert(4, {"event": "fixture_generation", "monotonic_ns": 5})
    for index, event in enumerate(late_generation, start=1):
        event["monotonic_ns"] = index
    _write_json(state_path, {"synthetic_events": late_generation})
    generation_cause = _observe_red(validate_state, contains="fuera del catálogo")
    state_path.write_bytes(original)
    after_sha256 = _restoration_sha256((state_path,))
    green_after = validate_state()
    if green_before != green_after:
        raise RuntimeError("frontera sintética no volvió a verde")
    return _control_result(
        red_causes=(early_cause, generation_cause),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("events.json",),
        evidence={
            "synthetic_only": True,
            "protocol_start_tokens": 0,
            "materialized_units": 0,
            "validated_boundary_events": len(green_events),
        },
    )


def _build_output_root(root: Path) -> tuple[Path, list[str], dict[str, int], str]:
    output_root = root / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("first.json", "first", 0, b"[1,2]")
    publisher.publish("second.json", "second", 1, b"[3]")
    manifest = publisher.finalize()["manifest"]
    identities = ["first", "second"]
    counts = {"first": 2, "second": 1}
    golden = str(manifest["golden_observed_sha256"])
    validate_output_manifest(
        output_root,
        expected_identities=identities,
        expected_counts=counts,
        expected_golden_sha256=golden,
    )
    return output_root, identities, counts, golden


def _control_completeness(root: Path) -> dict[str, Any]:
    control_root = root / "completeness"
    control_root.mkdir()
    output_root, identities, counts, golden = _build_output_root(control_root)
    state_paths = (output_root,)
    before_sha256 = _restoration_sha256(state_paths)

    def validate_green() -> dict[str, Any]:
        manifest = validate_output_manifest(
            output_root,
            expected_identities=identities,
            expected_counts=counts,
            expected_golden_sha256=golden,
        )
        return {"artifacts": len(manifest["artifacts"]), "golden_sha256": golden}

    green_before = validate_green()
    missing_path = output_root / "first.json"
    missing_original = missing_path.read_bytes()
    missing_path.unlink()
    missing_cause = _observe_red(validate_green, contains="output manifestado: archivo ausente")
    missing_path.write_bytes(missing_original)
    extra_path = output_root / "unexpected.json"
    extra_path.write_bytes(b"[]")
    extra_cause = _observe_red(validate_green, contains="completitud bidireccional")
    extra_path.unlink()
    after_sha256 = _restoration_sha256(state_paths)
    green_after = validate_green()
    if green_before != green_after:
        raise RuntimeError("completitud no volvió al mismo verde")
    return _control_result(
        red_causes=(missing_cause, extra_cause),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("outputs/",),
        evidence={"expected_outputs": identities, "expected_counts": counts},
    )


def _control_order(root: Path) -> dict[str, Any]:
    control_root = root / "order"
    control_root.mkdir()
    output_root, identities, counts, golden = _build_output_root(control_root)
    manifest_path = output_root / "manifest.json"
    state_paths = (manifest_path,)
    before_sha256 = _restoration_sha256(state_paths)

    def validate_green() -> dict[str, Any]:
        manifest = validate_output_manifest(
            output_root,
            expected_identities=identities,
            expected_counts=counts,
            expected_golden_sha256=golden,
        )
        return {"ordinals": [item["ordinal"] for item in manifest["artifacts"]]}

    green_before = validate_green()
    original = manifest_path.read_bytes()
    duplicated = read_json_object(manifest_path)
    cast(list[dict[str, Any]], duplicated["artifacts"])[1]["ordinal"] = 0
    _write_json(manifest_path, duplicated)
    duplicate_cause = _observe_red(validate_green, contains="ordinal de output duplicado")
    manifest_path.write_bytes(original)
    permuted = read_json_object(manifest_path)
    cast(list[dict[str, Any]], permuted["artifacts"]).reverse()
    _write_json(manifest_path, permuted)
    permuted_cause = _observe_red(validate_green, contains="identidades/orden")
    manifest_path.write_bytes(original)
    after_sha256 = _restoration_sha256(state_paths)
    green_after = validate_green()
    if green_before != green_after:
        raise RuntimeError("orden no volvió al mismo verde")
    return _control_result(
        red_causes=(duplicate_cause, permuted_cause),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("manifest.json",),
        evidence={"expected_order": identities, "expected_ordinals": [0, 1]},
    )


def _publish_single_json(root: Path) -> dict[str, Any]:
    publisher = AtomicOutputPublisher(root)
    publisher.publish("result.json", "result", 0, b"[1]")
    manifest = publisher.finalize()["manifest"]
    return validate_output_manifest(
        root,
        expected_identities=["result"],
        expected_counts={"result": 1},
        expected_golden_sha256=str(manifest["golden_observed_sha256"]),
    )


def _control_atomic_crash(root: Path) -> dict[str, Any]:
    control_root = root / "atomic-crash"
    control_root.mkdir()
    state_path = control_root / "transaction.json"
    _write_json(state_path, {"interrupt_after": None})
    before_sha256 = _restoration_sha256((state_path,))
    green_before = _publish_single_json(control_root / "green-before")
    original = state_path.read_bytes()
    _write_json(state_path, {"interrupt_after": "flush"})
    interrupted_root = control_root / "interrupted"

    def interrupt(operation: str, path: Path) -> None:
        del path
        if operation == "flush":
            raise RuntimeError("interrupción controlada posterior a flush y anterior a rename")

    publisher = AtomicOutputPublisher(interrupted_root, event_callback=interrupt)
    atomic_cause = _observe_red(
        lambda: publisher.publish("result.json", "result", 0, b"[1]"),
        expected_exception=RuntimeError,
        contains="posterior a flush",
    )
    if (interrupted_root / "manifest.json").exists() or list(interrupted_root.rglob("*.partial")):
        raise RuntimeError("crash atómico dejó manifiesto o parcial")
    state_path.write_bytes(original)
    after_sha256 = _restoration_sha256((state_path,))
    green_after = _publish_single_json(control_root / "green-after")
    if len(green_before["artifacts"]) != len(green_after["artifacts"]):
        raise RuntimeError("publicador no volvió a verde tras crash")
    return _control_result(
        red_causes=(atomic_cause,),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("transaction.json",),
        evidence={
            "interrupt_point": "after_flush_before_rename",
            "partial_files_after_cleanup": 0,
            "final_manifest_present_after_crash": False,
        },
    )


def _control_sidecar(root: Path) -> dict[str, Any]:
    control_root = root / "sidecar"
    control_root.mkdir()
    sidecar_path = control_root / "samples.jsonl"
    recorder = JsonlRecorder(sidecar_path, name="selftest-sidecar")
    recorder.append({"sample_ordinal": 0})
    recorder.append({"sample_ordinal": 1})
    metadata = recorder.finalize()
    before_sha256 = _restoration_sha256((sidecar_path,))
    green_before = verify_jsonl_sidecar(metadata)
    original = sidecar_path.read_bytes()
    sidecar_path.write_bytes(original + b"{}\n")
    tampered_cause = _observe_red(
        lambda: verify_jsonl_sidecar(metadata), contains="bytes del sidecar"
    )
    sidecar_path.write_bytes(original)
    sidecar_path.unlink()
    missing_cause = _observe_red(
        lambda: verify_jsonl_sidecar(metadata), contains="ruta o ancestro ausente"
    )
    sidecar_path.write_bytes(original)
    after_sha256 = _restoration_sha256((sidecar_path,))
    green_after = verify_jsonl_sidecar(metadata)
    if green_before != green_after:
        raise RuntimeError("sidecar no volvió al mismo verde")
    return _control_result(
        red_causes=(tampered_cause, missing_cause),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("samples.jsonl",),
        evidence={"records": len(green_after), "format": "jsonl"},
    )


def _control_disk(root: Path) -> dict[str, Any]:
    control_root = root / "disk"
    control_root.mkdir()
    roots = {
        name: control_root / name
        for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
    }
    for path in roots.values():
        path.mkdir()
    (roots["inputs"] / "input.bin").write_bytes(b"input")
    (roots["scratch"] / "base.bin").write_bytes(b"base")
    observed_path = control_root / "observed.json"
    baseline = census_roots(roots)
    _write_json(observed_path, baseline)
    state_paths = (observed_path, *roots.values())
    before_sha256 = _restoration_sha256(state_paths)

    def validate_green() -> dict[str, dict[str, Any]]:
        return validate_census_against_filesystem(read_json_object(observed_path), roots)

    green_before = validate_green()
    original = observed_path.read_bytes()
    falsified = read_json_object(observed_path)
    scratch = cast(dict[str, Any], falsified["scratch"])
    scratch["allocated_bytes"] = int(scratch["allocated_bytes"]) + 1
    _write_json(observed_path, falsified)
    allocation_cause = _observe_red(validate_green, contains="no reconcilia")
    observed_path.write_bytes(original)

    temporary_path = roots["scratch"] / "peak-temporary.bin"
    temporary_path.write_bytes(b"temporary" * 1024)
    with_temporary = census_roots(roots)
    temporary_cause = _observe_red(validate_green, contains="no reconcilia")
    footprint = disk_footprint_summary(baseline, [baseline, with_temporary])
    if footprint["peak_incremental_allocated_bytes"] <= 0:
        raise RuntimeError("temporary no apareció en el high-water asignado")
    temporary_path.unlink()
    after_sha256 = _restoration_sha256(state_paths)
    green_after = validate_green()
    if green_before != green_after:
        raise RuntimeError("censo de disco no volvió al mismo verde")
    return _control_result(
        red_causes=(allocation_cause, temporary_cause),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("observed.json", "five-disk-roots"),
        evidence={
            "roots": sorted(roots),
            "temporary_peak_incremental_allocated_bytes": footprint[
                "peak_incremental_allocated_bytes"
            ],
            "allocation_reliable": all(
                bool(value["allocation_reliable"]) for value in green_after.values()
            ),
        },
    )


def _control_statistics(root: Path) -> dict[str, Any]:
    control_root = root / "statistics"
    control_root.mkdir()
    state_path = control_root / "statistics.json"
    values = [10.0, 11.0, 100.0]
    state = {
        "attempts": [
            {"attempt_ordinal": ordinal, "classification": "success"} for ordinal in range(1, 4)
        ],
        "values": values,
        "summary": robust_summary(values),
    }
    _write_json(state_path, state)
    before_sha256 = _restoration_sha256((state_path,))

    def validate_green() -> dict[str, Any]:
        observed = read_json_object(state_path)
        attempts = observed["attempts"]
        raw_values = observed["values"]
        declared = observed["summary"]
        if not isinstance(attempts, list) or not isinstance(raw_values, list):
            raise ContractError("statistics state no contiene listas")
        progression = validate_statistical_progression(
            [cast(dict[str, Any], attempt) for attempt in attempts], phase="screening"
        )
        rebuilt = robust_summary([float(value) for value in raw_values])
        if not isinstance(declared, dict):
            raise ContractError("statistics summary no es objeto")
        if declared.get("maximum") != max(float(value) for value in raw_values):
            raise ContractError("estadística descarta o altera el máximo observado")
        if declared != rebuilt:
            raise ContractError("estadística declarada no reconcilia con todas las observaciones")
        return {"progression": progression, "summary": rebuilt}

    green_before = validate_green()
    original = state_path.read_bytes()
    missing = read_json_object(state_path)
    cast(list[Any], missing["attempts"]).pop()
    _write_json(state_path, missing)
    missing_cause = _observe_red(validate_green, contains="screening exige exactamente 3 intentos")
    state_path.write_bytes(original)
    discarded = read_json_object(state_path)
    cast(dict[str, Any], discarded["summary"])["maximum"] = 11.0
    _write_json(state_path, discarded)
    maximum_cause = _observe_red(validate_green, contains="máximo observado")
    state_path.write_bytes(original)
    after_sha256 = _restoration_sha256((state_path,))
    green_after = validate_green()
    if green_before != green_after:
        raise RuntimeError("estadística no volvió al mismo verde")
    summary = cast(dict[str, Any], green_after["summary"])
    return _control_result(
        red_causes=(missing_cause, maximum_cause),
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("statistics.json",),
        evidence={
            "attempts": 3,
            "observations": summary["count"],
            "maximum": summary["maximum"],
            "u": summary["u"],
            "discarded_observations": 0,
        },
    )


def _control_copy(root: Path) -> dict[str, Any]:
    control_root = root / "copy"
    control_root.mkdir()
    readme = control_root / "README.md"
    readme.write_bytes(
        "El entorno H9R es una hipótesis de medición, no capacidad entregada.\n".encode()
    )
    before_sha256 = _restoration_sha256((readme,))
    green_before = assert_no_h9r_capacity_copy(control_root)
    original = readme.read_bytes()
    negative_variants = (
        ("4-core", "Delivered on a 4-core host.\n"),
        ("four-core", "Delivered on a four-core host.\n"),
        ("8-GB RAM", "Requires 8-GB RAM.\n"),
        ("eight GB RAM", "Requires eight GB RAM.\n"),
    )
    copy_causes: list[str] = []
    observed_variants: list[str] = []
    for expected_literal, injected_copy in negative_variants:
        readme.write_bytes(injected_copy.encode())
        findings = scan_capacity_claims((readme,))
        literals = [str(finding["literal"]) for finding in findings]
        if literals != [expected_literal]:
            raise RuntimeError(
                "censo de copy no detectó exactamente la variante inyectada: "
                f"esperado={expected_literal!r}, observado={literals!r}"
            )
        observed_variants.extend(literals)
        copy_causes.append(
            _observe_red(
                lambda: assert_no_h9r_capacity_copy(control_root),
                expected_exception=CopyGateError,
                contains="target H9R publicado como capacidad",
            )
        )
        readme.write_bytes(original)
    after_sha256 = _restoration_sha256((readme,))
    green_after = assert_no_h9r_capacity_copy(control_root)
    if green_before != green_after:
        raise RuntimeError("copy sintético no volvió al mismo verde")
    return _control_result(
        red_causes=copy_causes,
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        restoration_scope=("README.md",),
        evidence={
            "files_censused": green_after,
            "negative_variants": observed_variants,
            "repository_files_modified": 0,
        },
    )


def _kernel_cap_hypotheses() -> dict[str, dict[str, Any]]:
    affinity = current_process_affinity()
    selected_mask = first_cpu_mask(affinity["process_mask"])
    selected_count = selected_mask.bit_count()
    if selected_count not in {1, 2, 3, 4}:
        raise ContractError("host no permite confinar un conjunto de hasta cuatro CPU lógicas")
    observed: dict[str, dict[str, Any]] = {}
    for cap_id, cap_bytes in CAPS.items():
        with WindowsJob(memory_bytes=cap_bytes, affinity_mask=selected_mask) as job:
            effective = job.effective_limits()
            if (
                effective["job_memory_commit_limit_bytes"] != cap_bytes
                or effective["logical_cpu_count"] != selected_count
                or effective["affinity_mask"] != selected_mask
                or effective["kill_on_job_close"] is not True
            ):
                raise RuntimeError(f"límite kernel no reconcilia para {cap_id}")
            observed[cap_id] = effective
    return observed


def run_harness_self_test(
    *, checkout_root: Path, output_path: Path, harness_runtime: Mapping[str, Any]
) -> dict[str, Any]:
    """Ejecuta la matriz segura completa sin candidato, fixture, unidad ni token START."""
    if output_path.exists():
        raise FileExistsError(output_path)
    if sys.platform != "win32":
        raise ContractError("harness-test H9R calificable exige Windows Job Objects")
    checkout_root = checkout_root.resolve()
    schemas = {
        "attempt": attempt_json_schema(),
        "aggregate": aggregate_json_schema(),
        "preflight-rejection": preflight_rejection_json_schema(),
        "pre-start-failure": pre_start_failure_json_schema(),
        "post-start-failure": post_start_failure_json_schema(),
        "internal-authorization-precommit": internal_authorization_precommit_json_schema(),
        "internal-authorization-gate": internal_authorization_gate_json_schema(),
        "internal-authorization-release": internal_authorization_release_json_schema(),
    }
    schema_objects = {
        name: _assert_schema_objects_closed(schema) for name, schema in schemas.items()
    }
    catalog_sizes = assert_documented_h9r_catalog(checkout_root)
    runtime_catalog_sizes = assert_documented_h9r_runtime_catalog(
        checkout_root,
        caps=CAPS,
        geometry_ids=GEOMETRY_IDS,
        classifications=CLASSIFICATIONS,
        flow_specs=FLOW_SPECS,
        adapter_ids=ADAPTER_IDS,
    )
    if runtime_catalog_sizes != catalog_sizes:
        raise ContractError("catálogo estático y runtime H9R no producen el mismo censo")
    public_copy_files = assert_no_h9r_capacity_copy(checkout_root)
    module_inventory = _harness_module_inventory(checkout_root)
    cap_controls = _kernel_cap_hypotheses()

    temporary_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="nikodym-h9r-selftest-") as raw_temp:
        temporary_path = Path(raw_temp)
        controls = {
            "authority_preflight": _control_authority_preflight(temporary_path),
            "fifth_cpu": _control_fifth_cpu(temporary_path),
            "c_plus_one_small_cap": _control_c_plus_one(temporary_path, checkout_root),
            "short_deadline": _control_short_deadline(temporary_path),
            "injected_memory_disk_guards": _control_injected_guards(temporary_path),
            "frontier_pre_start_post_generation": _control_frontier(temporary_path),
            "completeness_missing_extra": _control_completeness(temporary_path),
            "order_duplicate_permuted": _control_order(temporary_path),
            "atomic_crash": _control_atomic_crash(temporary_path),
            "sidecar_tampered_missing": _control_sidecar(temporary_path),
            "disk_allocation_temporaries": _control_disk(temporary_path),
            "statistics_missing_max_discard": _control_statistics(temporary_path),
            "copy": _control_copy(temporary_path),
        }
        if tuple(controls) != CONTROL_IDS or any(
            set(control) != _CONTROL_FIELDS for control in controls.values()
        ):
            raise RuntimeError("matriz de controles no es exacta/cerrada")

    if temporary_path is None or temporary_path.exists():
        raise RuntimeError("TemporaryDirectory del harness-test no fue retirado")
    artifact = {
        "schema_version": HARNESS_TEST_SCHEMA_VERSION,
        "mode": "harness-test-only",
        "start_authorized": False,
        "start_tokens_emitted": 0,
        "materialized_start_units": 0,
        "candidate_workloads_executed": 0,
        "definitive_calibration_fixtures_generated": 0,
        "catalog": catalog_sizes,
        "public_copy_files_censused": public_copy_files,
        "schemas": {
            name: {
                "sha256": canonical_json_sha256(schema),
                "closed_object_count": schema_objects[name],
            }
            for name, schema in schemas.items()
        },
        "harness_modules": {
            "files": module_inventory,
            "count": len(module_inventory),
            "inventory_sha256": canonical_json_sha256(module_inventory),
        },
        "harness_runtime": copy.deepcopy(dict(harness_runtime)),
        "kernel_cap_hypotheses": cap_controls,
        "control_matrix_order": list(CONTROL_IDS),
        "controls": controls,
        "temporary_cleanup_complete": True,
    }
    atomic_write_json_exclusive(output_path, artifact)
    if read_json_object(output_path) != artifact:
        raise RuntimeError("artefacto harness-test final no reconcilia byte-semantics")
    return artifact
