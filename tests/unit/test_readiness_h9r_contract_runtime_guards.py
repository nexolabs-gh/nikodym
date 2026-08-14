from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.readiness_h9r import contracts as contracts_module
from scripts.readiness_h9r.contracts import (
    ATTEMPT_SIDECAR_FILENAMES,
    AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
    AUTHORIZATION_SCHEMA_VERSION,
    CAPS,
    POST_START_FAILURE_SCHEMA_VERSION,
    PRE_START_FAILURE_SCHEMA_VERSION,
    PROTOCOL_VERSION,
    ContractError,
    _read_canonical_control_object,
    _reconcile_native_pool_evidence,
    _validate_candidate_execution_chain,
    _validate_candidate_file_identity,
    _validate_candidate_http_execution_chain,
    _validate_execution_environment,
    _validate_git_sha,
    _validate_job_limits,
    _validate_post_start_source_identity,
    _validate_pre_start_handshake_source,
    _validate_preflight_guards,
    _validate_termination_classification_flags,
    _validate_ui_ingress_response_order,
    _validate_worker_result,
    attempt_id,
    authority_signing_bytes,
    authorization_consumption_path_digest,
    authorization_statement,
    canonical_json_bytes,
    canonical_json_sha256,
    claim_internal_authorization_release,
    internal_authorization_gate_json_schema,
    internal_authorization_precommit_json_schema,
    internal_authorization_release_json_schema,
    internal_authorization_release_paths,
    post_start_failure_json_schema,
    pre_start_failure_json_schema,
    read_json_object,
    sha256_bytes,
    trusted_authority_key_identity,
    validate_authorization_consumption,
    validate_boundary_events,
    validate_internal_authorization_gate,
    validate_internal_authorization_release,
    validate_native_pool_events,
    validate_post_start_failure_evidence,
    validate_pre_start_failure_evidence,
    validate_sha256,
    write_internal_authorization_precommit,
    write_internal_authorization_release_reservation,
)


def _digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


@pytest.mark.parametrize("invalid", ["A" + "1" * 63, "0" * 64, "f" * 64])
def test_sha256_runtime_exige_lowercase_canonico_sin_placeholder(invalid: str) -> None:
    with pytest.raises(ContractError, match=r"lowercase|placeholder"):
        validate_sha256(invalid, context="sha")


@pytest.mark.parametrize(
    ("context", "invalid"),
    [
        ("candidate.source_sha", "A" + "1" * 39),
        ("fixture.generator.source_commit", "F" * 64),
        ("candidate.source_sha", "0" * 40),
    ],
)
def test_sha_git_runtime_exige_lowercase_canonico_sin_placeholder(
    context: str, invalid: str
) -> None:
    with pytest.raises(ContractError, match="lowercase canónico"):
        _validate_git_sha(invalid, context=context)


def test_control_candidate_rechaza_hardlink_y_reabre_tras_restaurar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = tmp_path / "telemetry" / "control" / "candidate-result.json"
    control.parent.mkdir(parents=True)
    payload = {"schema_version": "control-test.v1", "value": 1}
    raw = canonical_json_bytes(payload) + b"\n"
    control.write_bytes(raw)
    alias = tmp_path / "candidate-result-hardlink.json"
    try:
        os.link(control, alias)
    except OSError as exc:  # pragma: no cover - volumen sin soporte de hardlinks
        pytest.skip(f"hardlinks no disponibles: {exc}")
    identity = {
        "path": str(control),
        "logical_bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }
    real_reader = contracts_module.read_json_object
    real_sha256_file = contracts_module.sha256_file
    opened = False
    hashed = False

    def forbidden_reader(_path: Path) -> dict[str, Any]:
        nonlocal opened
        opened = True
        raise AssertionError("el control hardlinked no debe abrirse")

    def forbidden_hash(_path: Path, *, chunk_size: int = 1024 * 1024) -> str:
        del chunk_size
        nonlocal hashed
        hashed = True
        raise AssertionError("el control hardlinked no debe hashearse")

    monkeypatch.setattr(contracts_module, "read_json_object", forbidden_reader)
    monkeypatch.setattr(contracts_module, "sha256_file", forbidden_hash)
    with pytest.raises(ContractError, match="hardlinks prohibidos"):
        _read_canonical_control_object(control, context="control")
    with pytest.raises(ContractError, match="hardlinks prohibidos"):
        _validate_candidate_file_identity(
            identity,
            expected_path=control,
            context="candidate control",
        )
    assert opened is False and hashed is False
    monkeypatch.setattr(contracts_module, "read_json_object", real_reader)
    monkeypatch.setattr(contracts_module, "sha256_file", real_sha256_file)
    alias.unlink()
    assert _read_canonical_control_object(control, context="control") == payload
    assert (
        _validate_candidate_file_identity(
            identity,
            expected_path=control,
            context="candidate control",
        )
        == identity
    )


def _unit() -> dict[str, object]:
    return {
        "candidate_manifest_sha256": _digest("candidate"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": _digest("fixture"),
        "config_hash": _digest("config"),
        "geometry_id": "G-",
        "cap_id": "C4",
        "attempt_ordinal": 1,
    }


def _job_limits() -> dict[str, object]:
    return {
        "limit_flags": 0x2200,
        "affinity_mask": 0b1111,
        "logical_cpu_count": 4,
        "processor_group": 0,
        "group_affinities": [{"processor_group": 0, "affinity_mask": 0b1111}],
        "job_memory_commit_limit_bytes": CAPS["C4"],
        "kill_on_job_close": True,
        "affinity_enforced": True,
        "job_memory_enforced": True,
    }


def _candidate_chain_fixture() -> dict[str, Any]:
    from scripts.readiness_h9r.adapters import (
        ADAPTER_RESULT_SCHEMA_VERSION,
        CANDIDATE_RESULT_SCHEMA_VERSION,
        CANDIDATE_START_SCHEMA_VERSION,
        CONSUMER_OPEN_REQUEST_SCHEMA_VERSION,
        candidate_execution_request,
    )

    attempt = _digest("candidate-attempt")
    protected_identity = {
        "role": "input",
        "relative_name": "input.bin",
        "logical_bytes": 1,
        "sha256": _digest("candidate-input"),
    }
    protected = [
        {
            "logical_id": canonical_json_sha256(protected_identity),
            **protected_identity,
        }
    ]
    nonce = "1" * 64
    request_id = canonical_json_sha256(
        {"attempt_id": attempt, "operation": "OPEN", "protected": protected}
    )
    broker = {
        "protocol_version": "nikodym.readiness.h9r.consumer-open.v1",
        "host": "127.0.0.1",
        "port": 20_001,
        "nonce": nonce,
        "nonce_commitment_sha256": sha256_bytes(bytes.fromhex(nonce)),
        "request_id": request_id,
    }
    normalized_request = {
        "attempt_id": attempt,
        "mode": "batch",
        "script": {
            "path": "C:/candidate/entry.py",
            "relative_path": "entry.py",
            "logical_bytes": 1,
            "sha256": _digest("candidate-script"),
        },
        "runtime": {"candidate_root": Path("C:/candidate")},
        "input_contract": {
            "protocol_version": "nikodym.readiness.h9r.consumer-open.v1",
            "protected": protected,
            "max_open_requests": 1,
        },
        "broker": broker,
        "paths": {
            "staging": Path("C:/work/scratch/consumer-staging"),
            "candidate_outputs": Path("C:/work/scratch/consumer-staging/candidate-outputs.json"),
            "brokered_inputs_json": Path("C:/work/scratch/candidate-runtime/brokered-inputs.json"),
            "service_ready": Path("C:/work/scratch/candidate-runtime/service-ready.json"),
        },
        "argv_template": [
            "${BROKERED_INPUTS_JSON}",
            "${STAGING_ROOT}",
            "${ADAPTER_RESULT}",
        ],
        "service": None,
        "workload_deadline_seconds": 1.0,
    }
    candidate_request_raw = {"signed_candidate_request": True}
    candidate_request_sha = canonical_json_sha256(candidate_request_raw)
    normalized_request["candidate_request_sha256"] = candidate_request_sha
    harness_runtime_snapshot = {
        "import_roots": [
            {
                "name": "threadpoolctl",
                "path": "C:/snapshot/import-roots/threadpoolctl.py",
            }
        ]
    }
    execution_request = candidate_execution_request(
        normalized_request,
        harness_runtime_snapshot=harness_runtime_snapshot,
    )
    execution_payload = canonical_json_bytes(execution_request) + b"\n"
    execution_identity = {
        "path": "C:/work/telemetry/control/candidate-execution.json",
        "logical_bytes": len(execution_payload),
        "sha256": sha256_bytes(execution_payload),
    }
    process = {"pid": 321, "creation_time_100ns": 654}
    candidate_start = {
        "schema_version": CANDIDATE_START_SCHEMA_VERSION,
        "attempt_id": attempt,
        "candidate_request_sha256": candidate_request_sha,
        "candidate_execution_request": copy.deepcopy(execution_identity),
        "candidate_process": copy.deepcopy(process),
    }
    candidate_result = {
        "schema_version": CANDIDATE_RESULT_SCHEMA_VERSION,
        "attempt_id": attempt,
        "candidate_request_sha256": candidate_request_sha,
        "candidate_execution_request": copy.deepcopy(execution_identity),
        "candidate_process": copy.deepcopy(process),
        "service_ready": None,
        "native_pools_observation": {
            "path": "C:/work/telemetry/control/native-pools-observation.json",
            "logical_bytes": 1,
            "sha256": _digest("native-pools-observation"),
        },
        "total_processes": 1,
        "candidate_process_census": {
            "source": "windows_job_completion_port_v1",
            "total_processes": 1,
            "processes": [copy.deepcopy(process)],
        },
        "candidate_job_accounting": {
            "source": "windows_job_object",
            "total_user_time_100ns": 10,
            "total_kernel_time_100ns": 20,
            "total_user_seconds": 0.000001,
            "total_kernel_seconds": 0.000002,
            "total_page_fault_count": 1,
            "total_processes": 1,
            "active_processes": 0,
            "total_terminated_processes": 1,
            "peak_process_memory_commit_bytes": 1,
            "peak_job_memory_commit_bytes": 1,
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
        "returncode": 0,
        "tree_quiescent": True,
        "tree_empty_monotonic_ns": 400,
    }
    wire = {
        "schema_version": CONSUMER_OPEN_REQUEST_SCHEMA_VERSION,
        "attempt_id": attempt,
        "operation": "OPEN",
        "request_id": request_id,
        "nonce": nonce,
        "protected": protected,
    }
    open_binding = {
        "request_id": request_id,
        "protected": protected,
        "broker_request_sha256": canonical_json_sha256(wire),
        "nonce_commitment_sha256": broker["nonce_commitment_sha256"],
        "candidate_process": copy.deepcopy(process),
    }
    consumer_start = {
        "event": "first_open_or_byte",
        "monotonic_ns": 200,
        "kind": "first_open",
        "provider": "harness_owned_consumer_open_v1",
        **open_binding,
    }
    audit_events = [
        {
            "event": "broker_ready",
            "monotonic_ns": 150,
            "protected_count": 1,
        },
        {
            "event": "consumer_open_brokered",
            "monotonic_ns": 250,
            **copy.deepcopy(open_binding),
        },
    ]
    output_manifest_sha = _digest("output-manifest")
    adapter_result = {
        "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
        "attempt_id": attempt,
        "candidate_execution": copy.deepcopy(candidate_result),
        "http_exchange": None,
        "output_manifest_sha256": output_manifest_sha,
    }
    return {
        "candidate_request_raw": candidate_request_raw,
        "candidate_request": normalized_request,
        "harness_runtime_snapshot": harness_runtime_snapshot,
        "candidate_request_payload_sha256": candidate_request_sha,
        "execution_request": execution_request,
        "execution_request_identity": execution_identity,
        "candidate_start": candidate_start,
        "candidate_result": candidate_result,
        "native_pools_observation": copy.deepcopy(candidate_result["native_pools_observation"]),
        "adapter_result": adapter_result,
        "consumer_start": consumer_start,
        "audit_events": audit_events,
        "expected_attempt_id": attempt,
        "expected_output_manifest_sha256": output_manifest_sha,
        "start_monotonic_ns": 100,
        "first_publisher_monotonic_ns": 500,
    }


def test_candidate_chain_liga_request_open_proceso_quiescencia_y_publisher() -> None:
    values = _candidate_chain_fixture()
    assert _validate_candidate_execution_chain(**values) == values["candidate_result"]


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("execution_payload", "serialización cerrada"),
        ("output_capability", "serialización cerrada"),
        ("process_reuse", "candidate request/proceso"),
        ("broker_hash", "candidate request/proceso"),
        ("result_identity", "start/result"),
        ("adapter_embed", "adapter-result"),
        ("native_pools_binding", "start/result"),
        ("kernel_process_count", "Job hijo quiescente"),
        ("kernel_census_reuse", "process census"),
        ("kernel_memory_sensor", "JobMemoryUsageInformation"),
        ("broker_ready_order", "orden/deadline"),
        ("deadline", "orden/deadline"),
        ("publisher_race", "orden/deadline"),
    ),
)
def test_candidate_chain_rechaza_spoof_y_publicacion_antes_de_quiescencia(
    mutation: str, match: str
) -> None:
    values = _candidate_chain_fixture()
    if mutation == "execution_payload":
        values["execution_request"]["attempt_id"] = _digest("otro")
    elif mutation == "output_capability":
        values["execution_request"]["paths"]["outputs"] = "C:/work/outputs"
    elif mutation == "process_reuse":
        values["consumer_start"]["candidate_process"]["creation_time_100ns"] += 1
    elif mutation == "broker_hash":
        values["consumer_start"]["broker_request_sha256"] = _digest("forged-open")
    elif mutation == "result_identity":
        values["candidate_result"]["candidate_execution_request"]["sha256"] = _digest(
            "forged-execution"
        )
    elif mutation == "adapter_embed":
        values["adapter_result"]["candidate_execution"]["tree_empty_monotonic_ns"] += 1
    elif mutation == "native_pools_binding":
        values["candidate_result"]["native_pools_observation"]["sha256"] = _digest("forged-pools")
    elif mutation == "kernel_process_count":
        values["candidate_result"]["candidate_job_accounting"]["total_processes"] = 2
    elif mutation == "kernel_census_reuse":
        values["candidate_result"]["candidate_process_census"]["processes"][0][
            "creation_time_100ns"
        ] += 1
    elif mutation == "kernel_memory_sensor":
        values["candidate_result"]["candidate_job_accounting"][
            "memory_usage_information_supported"
        ] = False
    elif mutation == "broker_ready_order":
        values["audit_events"][0]["monotonic_ns"] = 201
    elif mutation == "deadline":
        values["candidate_request"]["workload_deadline_seconds"] = 1e-9
    else:
        values["first_publisher_monotonic_ns"] = 399
    with pytest.raises(ContractError, match=match):
        _validate_candidate_execution_chain(**values)


def _candidate_http_chain_fixture() -> dict[str, Any]:
    from scripts.readiness_h9r.adapters import (
        CANDIDATE_SERVICE_READY_SCHEMA_VERSION,
        HTTP_EXCHANGE_SCHEMA_VERSION,
        UI_FIRST_BYTE_SCHEMA_VERSION,
        candidate_execution_request,
    )

    values = _candidate_chain_fixture()
    request = values["candidate_request"]
    request["mode"] = "http-service"
    request["broker"] = None
    request["service"] = {
        "host": "127.0.0.1",
        "port": 20_002,
        "ready_timeout_seconds": 10.0,
    }
    execution = candidate_execution_request(
        request,
        harness_runtime_snapshot=values["harness_runtime_snapshot"],
    )
    execution_bytes = canonical_json_bytes(execution) + b"\n"
    execution_identity = {
        "path": "C:/work/telemetry/control/candidate-execution.json",
        "logical_bytes": len(execution_bytes),
        "sha256": sha256_bytes(execution_bytes),
    }
    process = copy.deepcopy(values["candidate_result"]["candidate_process"])
    service_ready = {
        "schema_version": CANDIDATE_SERVICE_READY_SCHEMA_VERSION,
        "attempt_id": values["expected_attempt_id"],
        "candidate_request_sha256": values["candidate_request_payload_sha256"],
        "candidate_process": process,
        "host": "127.0.0.1",
        "port": 20_002,
        "ready_monotonic_ns": 160,
    }
    ready_bytes = canonical_json_bytes(service_ready) + b"\n"
    service_ready_identity = {
        "path": "C:/work/scratch/candidate-runtime/service-ready.json",
        "logical_bytes": len(ready_bytes),
        "sha256": sha256_bytes(ready_bytes),
    }
    request_id = _digest("ui-request")
    body = {
        "path": "C:/work/inputs/ui-request.bin",
        "logical_bytes": 12,
        "sha256": _digest("ui-request-body"),
    }
    service_descriptor_sha = _digest("ui-service-descriptor")
    endpoint_sha = _digest("ui-endpoint")
    page = {
        "identity": "first_verifiable_page",
        "relative_path": "first-page.html",
        "logical_bytes": 9,
        "sha256": _digest("first-page"),
    }
    expected_ingress = {
        "path": "/calibrate",
        "request_id": request_id,
        "body": body,
        "service_descriptor_sha256": service_descriptor_sha,
        "endpoint_sha256": endpoint_sha,
    }
    expected_service = {
        **request["service"],
        "first_page_oracle": {
            "kind": "response-body-sha256-v1",
            "expected_status": 200,
            "content_type": "text/html",
            "response_body_bytes": 21,
            "response_body_sha256": _digest("ui-response"),
            "first_verifiable_page": page,
        },
    }
    http_exchange = {
        "schema_version": HTTP_EXCHANGE_SCHEMA_VERSION,
        "attempt_id": values["expected_attempt_id"],
        "candidate_request_sha256": values["candidate_request_payload_sha256"],
        "request_id": request_id,
        "service_descriptor_sha256": service_descriptor_sha,
        "endpoint_sha256": endpoint_sha,
        "candidate_process": process,
        "service_ready": service_ready_identity,
        "request": {
            "method": "POST",
            "path": "/calibrate",
            "body_bytes": 12,
            "body_sha256": body["sha256"],
            "first_byte_to_service_monotonic_ns": 200,
        },
        "response": {
            "status": 200,
            "content_type": "text/html",
            "body_bytes": 21,
            "body_sha256": expected_service["first_page_oracle"]["response_body_sha256"],
            "first_byte_from_service_monotonic_ns": 260,
        },
        "first_verifiable_page": page,
        "non_transforming": True,
    }
    exchange_bytes = canonical_json_bytes(http_exchange) + b"\n"
    http_exchange_identity = {
        "path": "C:/work/telemetry/control/candidate-http-exchange.json",
        "logical_bytes": len(exchange_bytes),
        "sha256": sha256_bytes(exchange_bytes),
    }
    values["execution_request"] = execution
    values["execution_request_identity"] = execution_identity
    values["candidate_start"]["candidate_execution_request"] = copy.deepcopy(execution_identity)
    values["candidate_result"]["candidate_execution_request"] = copy.deepcopy(execution_identity)
    values["candidate_result"]["service_ready"] = copy.deepcopy(service_ready_identity)
    values["adapter_result"]["candidate_execution"] = copy.deepcopy(values["candidate_result"])
    values["adapter_result"]["http_exchange"] = copy.deepcopy(http_exchange_identity)
    values["consumer_start"] = {
        "event": "first_open_or_byte",
        "monotonic_ns": 200,
        "kind": "first_byte",
        "provider": "harness_owned_candidate_http_ingress_v1",
        "request_id": request_id,
        "request_body_bytes": 12,
        "request_body_sha256": body["sha256"],
        "service_descriptor_sha256": service_descriptor_sha,
        "endpoint_sha256": endpoint_sha,
        "non_transforming": True,
    }
    values["audit_events"] = [{"event": "broker_ready", "monotonic_ns": 120, "protected_count": 1}]
    values.update(
        {
            "service_ready_identity": service_ready_identity,
            "service_ready": service_ready,
            "http_exchange_identity": http_exchange_identity,
            "http_exchange": http_exchange,
            "ui_response_event": {
                "schema_version": UI_FIRST_BYTE_SCHEMA_VERSION,
                "attempt_id": values["expected_attempt_id"],
                "event": "first_byte",
                "monotonic_ns": 300,
                "request_id": request_id,
            },
            "expected_ingress": expected_ingress,
            "expected_service": expected_service,
            "output_manifest": {
                "artifacts": [
                    {
                        "identity": page["identity"],
                        "relative_path": page["relative_path"],
                        "logical_bytes": page["logical_bytes"],
                        "sha256": page["sha256"],
                    }
                ]
            },
        }
    )
    return values


def test_candidate_http_chain_liga_servicio_response_y_pagina_real() -> None:
    values = _candidate_http_chain_fixture()
    assert _validate_candidate_http_execution_chain(**values) == values["candidate_result"]


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("ready_process", "service-ready"),
        ("boundary_timestamp", "boundary UI"),
        ("response_before_ingress", "orden causal"),
        ("client_before_service", "response first-byte"),
        ("non_transforming", "HTTP exchange"),
        ("page_output", "first-page oracle"),
        ("exchange_binding", "adapter-result"),
    ),
)
def test_candidate_http_chain_rechaza_spoof_causal(mutation: str, match: str) -> None:
    values = _candidate_http_chain_fixture()
    if mutation == "ready_process":
        values["service_ready"]["candidate_process"]["creation_time_100ns"] += 1
    elif mutation == "boundary_timestamp":
        values["consumer_start"]["monotonic_ns"] += 1
    elif mutation == "response_before_ingress":
        values["http_exchange"]["response"]["first_byte_from_service_monotonic_ns"] = 199
    elif mutation == "client_before_service":
        values["ui_response_event"]["monotonic_ns"] = 259
    elif mutation == "non_transforming":
        values["http_exchange"]["non_transforming"] = False
    elif mutation == "page_output":
        values["output_manifest"]["artifacts"][0]["sha256"] = _digest("otra-pagina")
    else:
        values["adapter_result"]["http_exchange"]["sha256"] = _digest("otro-exchange")
    with pytest.raises(ContractError, match=match):
        _validate_candidate_http_execution_chain(**values)


def _execution_environment() -> dict[str, object]:
    return {
        "platform": "win32",
        "windows_release": "11",
        "windows_version": "10.0.26100",
        "machine": "AMD64",
        "processor": "CPU model",
        "logical_cpus_host": 8,
        "processor_topology": {
            "active_group_count": 1,
            "active_processor_count_by_group": [8],
            "total_active_logical_processors": 8,
            "primary_group": 0,
            "primary_group_affinity_mask": 0xFF,
        },
        "affinity_before_confinement": {"process_mask": 0xFF, "system_mask": 0xFF},
        "system_memory": {
            "nominal_physical_bytes": 16_000,
            "physical_total_bytes": 15_000,
            "physical_visible_bytes": 15_000,
            "physical_available_bytes": 8_000,
            "commit_limit_bytes": 30_000,
            "commit_available_bytes": 20_000,
            "commit_used_bytes": 10_000,
            "memory_load_percent": 47,
            "virtual_total_bytes": 100_000,
            "virtual_available_bytes": 80_000,
        },
        "power_scheme": {"available": True, "returncode": 0, "stdout": "Balanced", "stderr": ""},
        "volume": {
            "path": "C:\\work",
            "free_bytes": 100_000,
            "volume_root": "C:\\",
            "volume_name": "System",
            "volume_serial": 1,
            "filesystem": "NTFS",
            "filesystem_flags": 1,
            "maximum_component_length": 255,
            "allocation_unit_bytes": 4096,
        },
        "native_pool_environment": {
            name: None
            for name in (
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "BLIS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
    }


def test_native_pools_vacio_es_censo_presente_no_observer_ausente() -> None:
    validate_native_pool_events(
        [
            {
                "event": "native_pools",
                "monotonic_ns": 1,
                "total_processes": 1,
                "processes": [
                    {
                        "pid": 10,
                        "creation_time_100ns": 20,
                        "environment": {
                            name: "4"
                            for name in (
                                "OMP_NUM_THREADS",
                                "MKL_NUM_THREADS",
                                "OPENBLAS_NUM_THREADS",
                                "NUMEXPR_NUM_THREADS",
                                "BLIS_NUM_THREADS",
                                "VECLIB_MAXIMUM_THREADS",
                            )
                        },
                        "libraries": [],
                        "process_thread_count": 1,
                    }
                ],
            }
        ]
    )
    with pytest.raises(ContractError, match="exactamente un censo"):
        validate_native_pool_events([])


def _native_pool_process(pid: int, creation: int) -> dict[str, object]:
    return {
        "pid": pid,
        "creation_time_100ns": creation,
        "environment": {
            name: "4"
            for name in (
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "BLIS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "libraries": [],
        "process_thread_count": 1,
        "source": {
            "path": f"C:/work/native-pools/process-{pid}-{creation}.json",
            "logical_bytes": 1,
            "sha256": _digest(f"native-process:{pid}:{creation}"),
        },
    }


def test_native_pools_liga_kernel_raiz_fuentes_y_sidecar_sin_paths() -> None:
    processes = [_native_pool_process(10, 20), _native_pool_process(11, 21)]
    process_census = [
        {"pid": process["pid"], "creation_time_100ns": process["creation_time_100ns"]}
        for process in processes
    ]
    aggregate = {
        "schema_version": "nikodym.readiness.h9r.native-pools-observation.v2",
        "candidate_execution_request_sha256": _digest("candidate-execution"),
        "total_processes": 2,
        "processes": processes,
    }
    sidecar = {
        "event": "native_pools",
        "monotonic_ns": 30,
        "total_processes": 2,
        "processes": [
            {name: process[name] for name in process if name != "source"} for process in processes
        ],
    }
    _reconcile_native_pool_evidence(
        candidate_process={"pid": 10, "creation_time_100ns": 20},
        expected_process_census=process_census,
        aggregate=aggregate,
        sidecar_event=sidecar,
    )

    forged_sidecar = copy.deepcopy(sidecar)
    forged_sidecar["processes"][1]["process_thread_count"] = 2
    with pytest.raises(ContractError, match="no deriva del agregado"):
        _reconcile_native_pool_evidence(
            candidate_process={"pid": 10, "creation_time_100ns": 20},
            expected_process_census=process_census,
            aggregate=aggregate,
            sidecar_event=forged_sidecar,
        )
    with pytest.raises(ContractError, match="omite el proceso raíz"):
        _reconcile_native_pool_evidence(
            candidate_process={"pid": 10, "creation_time_100ns": 99},
            expected_process_census=process_census,
            aggregate=aggregate,
            sidecar_event=sidecar,
        )
    forged_census = copy.deepcopy(process_census)
    forged_census[1]["creation_time_100ns"] = 22
    with pytest.raises(ContractError, match=r"censo kernel PID\+creation"):
        _reconcile_native_pool_evidence(
            candidate_process={"pid": 10, "creation_time_100ns": 20},
            expected_process_census=forged_census,
            aggregate=aggregate,
            sidecar_event=sidecar,
        )
    with pytest.raises(ContractError, match="total_processes kernel"):
        _reconcile_native_pool_evidence(
            candidate_process={"pid": 10, "creation_time_100ns": 20},
            expected_process_census=[
                *process_census,
                {"pid": 12, "creation_time_100ns": 22},
            ],
            aggregate=aggregate,
            sidecar_event=sidecar,
        )


def test_environment_runtime_cierra_topology_affinity_power_volume_y_pools() -> None:
    environment = _execution_environment()
    assert _validate_execution_environment(environment) == environment
    mutations = (
        ("processor_topology", "total_active_logical_processors", 7, "topology"),
        ("affinity_before_confinement", "process_mask", 0x100, "affinity"),
        ("power_scheme", "available", False, "power_scheme"),
        ("volume", "allocation_unit_bytes", 0, "allocation_unit"),
    )
    for section, name, value, match in mutations:
        altered = copy.deepcopy(environment)
        altered[section][name] = value
        with pytest.raises(ContractError, match=match):
            _validate_execution_environment(altered)
    pools = copy.deepcopy(environment)
    del pools["native_pool_environment"]["OMP_NUM_THREADS"]
    with pytest.raises(ContractError, match="censo exacto"):
        _validate_execution_environment(pools)


def test_preflight_guards_se_recalculan_de_fixture_entorno_y_pisos() -> None:
    environment = _execution_environment()
    environment["system_memory"]["physical_available_bytes"] = 3 * 1024**3
    environment["system_memory"]["commit_available_bytes"] = 3 * 1024**3
    environment["system_memory"]["commit_used_bytes"] = 30_000 - 3 * 1024**3
    environment["system_memory"]["commit_limit_bytes"] = 30_000
    # La helper recibe un environment ya validado; aquí focalizamos la causalidad de guards.
    environment["volume"]["free_bytes"] = 5 * 1024**3
    inputs = [{"allocated_bytes": 100}]
    bundle = {"allocated_bytes": 200}
    guards = {
        "physical_available_bytes": 3 * 1024**3,
        "commit_available_bytes": 3 * 1024**3,
        "allocated_inputs_bundle_bytes": 300,
        "disk_free_bytes": 5 * 1024**3,
        "disk_floor_bytes": 4 * 1024**3,
        "passed": True,
    }
    assert (
        _validate_preflight_guards(
            guards,
            environment=environment,
            fixture_inputs=inputs,
            fixture_bundle=bundle,
        )
        == guards
    )
    for name in (
        "physical_available_bytes",
        "commit_available_bytes",
        "allocated_inputs_bundle_bytes",
        "disk_free_bytes",
        "disk_floor_bytes",
    ):
        altered = copy.deepcopy(guards)
        altered[name] = 0
        with pytest.raises(ContractError, match="no deriva"):
            _validate_preflight_guards(
                altered,
                environment=environment,
                fixture_inputs=inputs,
                fixture_bundle=bundle,
            )
    low = copy.deepcopy(environment)
    low["system_memory"]["physical_available_bytes"] = 2 * 1024**3 - 1
    rejected = {**guards, "physical_available_bytes": 2 * 1024**3 - 1, "passed": False}
    with pytest.raises(ContractError, match="no deriva"):
        _validate_preflight_guards(
            rejected,
            environment=low,
            fixture_inputs=inputs,
            fixture_bundle=bundle,
        )


def test_ui_ingress_y_respuesta_tienen_relojes_causales_distintos() -> None:
    request = {
        "event": "first_open_or_byte",
        "monotonic_ns": 100,
        "kind": "first_byte",
        "provider": "harness_owned_candidate_http_ingress_v1",
        "request_id": _digest("request"),
        "request_body_bytes": 10,
        "request_body_sha256": _digest("body"),
        "service_descriptor_sha256": _digest("service"),
        "endpoint_sha256": _digest("endpoint"),
        "non_transforming": True,
    }
    delayed_response = {
        "event": "first_byte",
        "monotonic_ns": 500,
        "request_id": _digest("request"),
    }
    _validate_ui_ingress_response_order(request, delayed_response)
    early = {**delayed_response, "monotonic_ns": 99}
    with pytest.raises(ContractError, match="causalmente"):
        _validate_ui_ingress_response_order(request, early)
    wrong_request = {**delayed_response, "request_id": _digest("otro")}
    with pytest.raises(ContractError, match="causalmente"):
        _validate_ui_ingress_response_order(request, wrong_request)


@pytest.mark.parametrize(
    "provider",
    ("harness_owned_http_ingress_v1", "harness_test_http_ingress_v1"),
)
def test_boundary_productiva_rechaza_provider_ui_legacy_o_sintetico(provider: str) -> None:
    event = {
        "event": "first_open_or_byte",
        "monotonic_ns": 100,
        "kind": "first_byte",
        "provider": provider,
        "request_id": _digest("request"),
        "request_body_bytes": 10,
        "request_body_sha256": _digest("body"),
        "service_descriptor_sha256": _digest("service"),
        "endpoint_sha256": _digest("endpoint"),
        "non_transforming": True,
    }
    with pytest.raises(ContractError, match="servicio candidato"):
        validate_boundary_events([event])


def test_boundary_consumer_open_liga_solicitud_del_consumidor() -> None:
    protected_identity = {
        "role": "input",
        "relative_name": "input.bin",
        "logical_bytes": 1,
        "sha256": _digest("input"),
    }
    event = {
        "event": "first_open_or_byte",
        "monotonic_ns": 100,
        "kind": "first_open",
        "provider": "harness_owned_consumer_open_v1",
        "request_id": _digest("open-request"),
        "protected": [
            {
                "logical_id": canonical_json_sha256(protected_identity),
                **protected_identity,
            }
        ],
        "broker_request_sha256": _digest("broker-request"),
        "nonce_commitment_sha256": _digest("broker-nonce"),
        "candidate_process": {"pid": 123, "creation_time_100ns": 456},
    }
    prefix = [
        {"event": "boot", "monotonic_ns": 10, "pid": 1, "heavy_work_started": False},
        {
            "event": "limits_applied",
            "monotonic_ns": 20,
            "effective_limits": _job_limits(),
        },
        {"event": "ready", "monotonic_ns": 30, "heavy_work_started": False},
        {"event": "start", "monotonic_ns": 40},
    ]
    event["monotonic_ns"] = 50
    assert (
        validate_boundary_events([*prefix, event], require_complete=False)["first_open_or_byte"]
        == 4
    )
    spoofed = {**event, "provider": "harness_owned_preopen_v1"}
    with pytest.raises(ContractError, match="broker del consumidor"):
        validate_boundary_events([*prefix, spoofed], require_complete=False)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("missing_broker_hash", "campos faltantes"),
        ("caller_path", "extra"),
        ("spoof_logical_id", "no deriva"),
        ("invalid_nonce_commitment", "SHA-256"),
        ("invalid_candidate_process", "debe ser positivo"),
    ),
)
def test_boundary_consumer_open_rechaza_broker_no_ligado(mutation: str, match: str) -> None:
    protected_identity = {
        "role": "input",
        "relative_name": "input.bin",
        "logical_bytes": 1,
        "sha256": _digest("input"),
    }
    event: dict[str, Any] = {
        "event": "first_open_or_byte",
        "monotonic_ns": 50,
        "kind": "first_open",
        "provider": "harness_owned_consumer_open_v1",
        "request_id": _digest("open-request"),
        "protected": [
            {
                "logical_id": canonical_json_sha256(protected_identity),
                **protected_identity,
            }
        ],
        "broker_request_sha256": _digest("broker-request"),
        "nonce_commitment_sha256": _digest("broker-nonce"),
        "candidate_process": {"pid": 123, "creation_time_100ns": 456},
    }
    if mutation == "missing_broker_hash":
        del event["broker_request_sha256"]
    elif mutation == "caller_path":
        event["protected"][0]["path"] = "C:/fixture/input.bin"
    elif mutation == "spoof_logical_id":
        event["protected"][0]["logical_id"] = _digest("otro-logical-id")
    elif mutation == "invalid_nonce_commitment":
        event["nonce_commitment_sha256"] = "caller-chosen"
    else:
        event["candidate_process"]["pid"] = 0
    with pytest.raises(ContractError, match=match):
        validate_boundary_events([event], require_complete=False)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("kill_on_job_close", False, "control efectivo"),
        ("affinity_enforced", False, "control efectivo"),
        ("job_memory_enforced", False, "control efectivo"),
        ("logical_cpu_count", 5, "fuera de 1"),
        ("affinity_mask", 0, "debe ser positiva"),
        ("affinity_mask", 0b111, "no reconcilia logical_cpu_count"),
        ("job_memory_commit_limit_bytes", CAPS["C4"] + 1, "catálogo CAPS"),
    ],
)
def test_job_limits_rechaza_controles_autodeclarados_o_fuera_de_catalogo(
    field: str, value: object, match: str
) -> None:
    limits = _job_limits()
    limits[field] = value
    with pytest.raises(ContractError, match=match):
        _validate_job_limits(limits, context="limits")


def test_job_limits_reconcilia_afinidad_de_grupo() -> None:
    limits = _job_limits()
    limits["group_affinities"] = [{"processor_group": 1, "affinity_mask": 0b1111}]
    with pytest.raises(ContractError, match="afinidad por grupo"):
        _validate_job_limits(limits, context="limits")
    assert _validate_job_limits(_job_limits(), context="limits")["logical_cpu_count"] == 4


def _worker_ok() -> dict[str, object]:
    return {
        "schema_version": "nikodym.readiness.h9r.worker-result.v1",
        "attempt_id": _digest("attempt"),
        "status": "ok",
        "consumer_returncode_signed": 0,
        "consumer_returncode_unsigned": 0,
        "error": None,
    }


def test_worker_result_liga_variante_attempt_returncodes_y_clasificacion() -> None:
    worker = _worker_ok()
    assert (
        _validate_worker_result(
            worker,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=0,
            returncode_unsigned=0,
            client_returncode_signed=None,
            classification="success",
        )
        == worker
    )
    wrong_attempt = copy.deepcopy(worker)
    wrong_attempt["attempt_id"] = _digest("otro")
    with pytest.raises(ContractError, match="attempt_id"):
        _validate_worker_result(
            wrong_attempt,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=0,
            returncode_unsigned=0,
            client_returncode_signed=None,
            classification="success",
        )
    wrong_returncode = copy.deepcopy(worker)
    wrong_returncode["consumer_returncode_unsigned"] = 1
    with pytest.raises(ContractError, match="returncodes del consumidor"):
        _validate_worker_result(
            wrong_returncode,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=0,
            returncode_unsigned=0,
            client_returncode_signed=None,
            classification="success",
        )
    error_as_success = copy.deepcopy(worker)
    error_as_success.update(
        status="error",
        consumer_returncode_signed=2,
        consumer_returncode_unsigned=2,
        error="falló",
    )
    with pytest.raises(ContractError, match="success no deriva"):
        _validate_worker_result(
            error_as_success,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=2,
            returncode_unsigned=2,
            client_returncode_signed=None,
            classification="success",
        )


def test_worker_result_interno_es_cerrado_y_fallos_previos_admiten_null() -> None:
    internal = {
        "schema_version": "nikodym.readiness.h9r.worker-result.v1",
        "attempt_id": _digest("attempt"),
        "status": "error",
        "error_type": "RuntimeError",
        "error": "falló antes del consumidor",
        "traceback": "trace",
    }
    assert (
        _validate_worker_result(
            internal,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=1,
            returncode_unsigned=1,
            client_returncode_signed=None,
            classification="supervisor_error",
        )
        == internal
    )
    extra = {**internal, "consumer_returncode_signed": 1}
    with pytest.raises(ContractError, match="dos variantes cerradas"):
        _validate_worker_result(
            extra,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=1,
            returncode_unsigned=1,
            client_returncode_signed=None,
            classification="supervisor_error",
        )
    assert (
        _validate_worker_result(
            None,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=None,
            returncode_unsigned=None,
            client_returncode_signed=None,
            classification="limits_not_applied",
        )
        is None
    )
    with pytest.raises(ContractError, match="success no conserva"):
        _validate_worker_result(
            None,
            expected_attempt_id=_digest("attempt"),
            returncode_signed=None,
            returncode_unsigned=None,
            client_returncode_signed=None,
            classification="success",
        )


@pytest.mark.parametrize(
    ("classification", "trigger", "cleanup_complete", "timed_out", "cancelled"),
    [
        ("success", "watchdog_deadline", True, True, False),
        ("success", "cancelled", True, False, True),
        ("watchdog_deadline", None, True, True, False),
        ("cancelled", None, True, False, True),
        ("watchdog_deadline", "watchdog_deadline", True, True, True),
        ("consumer_error", "watchdog_deadline", True, True, False),
        ("consumer_error", "cancelled", True, False, True),
        ("orphan_detected", "watchdog_deadline", False, False, False),
        ("watchdog_deadline", "watchdog_deadline", False, True, False),
    ],
)
def test_trigger_timeout_cancelacion_y_orphan_conservan_causalidad(
    classification: str,
    trigger: str | None,
    cleanup_complete: bool,
    timed_out: bool,
    cancelled: bool,
) -> None:
    with pytest.raises(ContractError):
        _validate_termination_classification_flags(
            classification=classification,
            trigger_classification=trigger,
            cleanup_complete=cleanup_complete,
            timed_out=timed_out,
            cancelled=cancelled,
        )
    _validate_termination_classification_flags(
        classification="watchdog_deadline",
        trigger_classification="watchdog_deadline",
        cleanup_complete=True,
        timed_out=True,
        cancelled=False,
    )
    _validate_termination_classification_flags(
        classification="cancelled",
        trigger_classification="cancelled",
        cleanup_complete=True,
        timed_out=False,
        cancelled=True,
    )
    _validate_termination_classification_flags(
        classification="orphan_detected",
        trigger_classification="watchdog_deadline",
        cleanup_complete=False,
        timed_out=True,
        cancelled=False,
    )
    _validate_termination_classification_flags(
        classification="orphan_detected",
        trigger_classification=None,
        cleanup_complete=False,
        timed_out=False,
        cancelled=False,
    )


def _absent(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "present": False,
        "safe_regular_file": False,
        "rejection": "absent",
        "bytes": None,
        "sha256": None,
    }


def _causal_source(path: Path, payload: bytes | None) -> dict[str, object]:
    return {
        "snapshot": (
            None
            if payload is None
            else {"path": str(path), "bytes": len(payload), "sha256": sha256_bytes(payload)}
        ),
        "observed": _absent(path),
        "matches_snapshot": False,
    }


def _authority_fixture(
    tmp_path: Path,
) -> tuple[dict[str, Any], Path, Path, dict[str, object], dict[str, Any]]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    unit = _unit()
    receipt_path = tmp_path / "reservation.json"
    authorization_id = _digest("authorization")
    tooling_sha256 = _digest("tooling")
    schedule_seed = _digest("schedule-seed")
    schedule_units = [{**unit, "attempt_ordinal": ordinal} for ordinal in range(1, 4)]
    schedule_units.sort(
        key=lambda candidate: (
            sha256_bytes(f"{schedule_seed}\0{attempt_id(candidate)}".encode("ascii")),
            attempt_id(candidate),
        )
    )
    schedule = {
        "schema_version": "nikodym.readiness.h9r.schedule.v1",
        "phase": "screening",
        "permutation_algorithm": "sha256-key-sort-v1",
        "permutation_seed_sha256": schedule_seed,
        "cells": [{name: value for name, value in unit.items() if name != "attempt_ordinal"}],
        "units": schedule_units,
    }
    schedule_sha256 = canonical_json_sha256(schedule)
    schedule_position = [attempt_id(item) for item in schedule_units].index(attempt_id(unit))
    consumption_path_sha256 = authorization_consumption_path_digest(receipt_path)
    statement = authorization_statement(
        unit,
        authorization_id=authorization_id,
        authorization_consumption_path_sha256=consumption_path_sha256,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        schedule_position=schedule_position,
        scope="harness-test-only",
    )
    private_key = Ed25519PrivateKey.generate()
    public_key_path = tmp_path / "authority.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    authority: dict[str, Any] = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "scope": "harness-test-only",
        "start_authorized": False,
        "authorization_id": authorization_id,
        "authorization_consumption_path_sha256": consumption_path_sha256,
        "authorized_unit": unit,
        "attempt_id": attempt_id(unit),
        "authorization_text_sha256": sha256_bytes(statement),
        "document_sha256": {"protocol": _digest("protocol")},
        "tooling_sha256": tooling_sha256,
        "schedule_sha256": schedule_sha256,
        "schedule_position": schedule_position,
        "signer_public_key_sha256": trusted_authority_key_identity(public_key_path)[1],
        "signature_ed25519": "0" * 128,
    }
    authority["signature_ed25519"] = private_key.sign(authority_signing_bytes(authority)).hex()
    return authority, public_key_path, receipt_path, unit, schedule


def _receipt_wrapper(
    authority: dict[str, Any], receipt_path: Path, *, state: str
) -> dict[str, object]:
    receipt_payload = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": authority["authorization_id"],
        "attempt_id": authority["attempt_id"],
        "authority_sha256": canonical_json_sha256(authority),
        "state": state,
        "consumed_at_utc": None if state == "reserved" else "2026-08-13T00:00:00+00:00",
    }
    receipt_bytes = canonical_json_bytes(receipt_payload) + b"\n"
    return {
        "authorization_id": authority["authorization_id"],
        "authorization_consumption_path_sha256": authority["authorization_consumption_path_sha256"],
        "state": state,
        "consumed_at_utc": receipt_payload["consumed_at_utc"],
        "attempt_id": authority["attempt_id"],
        "authority_sha256": receipt_payload["authority_sha256"],
        "receipt": {
            "path": str(receipt_path),
            **(
                {"present": True, "safe_regular_file": True, "rejection": None}
                if state == "reserved"
                else {}
            ),
            "bytes": len(receipt_bytes),
            "sha256": sha256_bytes(receipt_bytes),
        },
    }


def test_receipt_one_shot_rechaza_hardlink_y_reabre_tras_restaurar(tmp_path: Path) -> None:
    authority, _key, receipt_path, unit, _schedule = _authority_fixture(tmp_path)
    consumption = _receipt_wrapper(authority, receipt_path, state="consumed")
    receipt_payload = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": consumption["authorization_id"],
        "attempt_id": consumption["attempt_id"],
        "authority_sha256": consumption["authority_sha256"],
        "state": "consumed",
        "consumed_at_utc": consumption["consumed_at_utc"],
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(canonical_json_bytes(receipt_payload) + b"\n")
    alias = tmp_path / "receipt-hardlink.json"
    try:
        os.link(receipt_path, alias)
    except OSError as exc:  # pragma: no cover - volumen sin soporte de hardlinks
        pytest.skip(f"hardlinks no disponibles: {exc}")
    with pytest.raises(ContractError, match="hardlinks prohibidos"):
        validate_authorization_consumption(
            consumption,
            authority=authority,
            expected_attempt_id=attempt_id(unit),
            verify_receipt=True,
        )
    alias.unlink()
    assert (
        validate_authorization_consumption(
            consumption,
            authority=authority,
            expected_attempt_id=attempt_id(unit),
            verify_receipt=True,
        )
        == consumption
    )


def _sidecars(tmp_path: Path) -> list[dict[str, object]]:
    names = (
        "resources",
        "boundary",
        "filesystem",
        "native_pools",
        "adapter_audit",
        "ui_first_byte",
        "worker_stdout",
        "worker_stderr",
        "client_boundary",
        "client_stdout",
        "client_stderr",
        "candidate_stdout",
        "candidate_stderr",
        "candidate_controller_stdout",
        "candidate_controller_stderr",
    )
    telemetry = tmp_path / "telemetry"
    return [
        {
            "name": name,
            "identity": _absent(telemetry / ATTEMPT_SIDECAR_FILENAMES[name]),
        }
        for name in names
    ]


def _pre_start_payload(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    authority, key, receipt, unit, _schedule = _authority_fixture(tmp_path)
    payload: dict[str, Any] = {
        "schema_version": PRE_START_FAILURE_SCHEMA_VERSION,
        "phase": "pre-start-terminal",
        "identity": {
            "attempt_id": attempt_id(unit),
            "unit": unit,
            "evidence_path": str(tmp_path / "attempt.json"),
            "wall_time_finished_utc": "2026-08-13T00:00:00+00:00",
        },
        "authority": authority,
        "authorization_reservation": _receipt_wrapper(authority, receipt, state="reserved"),
        "cause": {
            "classification": "limits_not_applied",
            "error_type": "ContractError",
            "message": "falló antes de START",
            "traceback_sha256": _digest("trace"),
        },
        "cleanup": {
            "worker_tree_empty": True,
            "client_tree_empty": True,
            "cleanup_complete": True,
            "job_accounting": None,
            "client_accounting": None,
            "errors": [],
        },
        "observed": {
            "causal_sources": {
                "authority": _causal_source(
                    tmp_path / "authority.json", canonical_json_bytes(authority) + b"\n"
                ),
                "authorization_consumption": _causal_source(
                    receipt,
                    canonical_json_bytes(
                        {
                            "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
                            "authorization_id": authority["authorization_id"],
                            "attempt_id": authority["attempt_id"],
                            "authority_sha256": canonical_json_sha256(authority),
                            "state": "reserved",
                            "consumed_at_utc": None,
                        }
                    )
                    + b"\n",
                ),
                "start": _causal_source(tmp_path / "start.json", None),
            },
            "handshake": {
                "boot": _absent(tmp_path / "boot.json"),
                "limits_applied": _absent(tmp_path / "limits-applied.json"),
                "ready": _absent(tmp_path / "ready.json"),
                "start": _absent(tmp_path / "start.json"),
            },
            "sidecars": _sidecars(tmp_path),
            "unexpected_start_quarantine": None,
        },
        "gates": {
            "start_observed": False,
            "workload_started": False,
            "authorization_reserved": True,
            "evidence_atomic": True,
        },
        "result": {"classification": "limits_not_applied", "statistically_eligible": False},
    }
    return payload, key


def test_handshake_rechaza_swap_despues_de_identidad_y_restaura_byte_exacto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_attempt_id = _digest("attempt-handshake")
    boot_path = tmp_path / "boot.json"
    replacement_path = tmp_path / "boot-replacement.json"
    boot = {
        "protocol_version": PROTOCOL_VERSION,
        "attempt_id": expected_attempt_id,
        "pid": 123,
        "heavy_work_started": False,
    }
    replacement = {**boot, "pid": 456}
    expected_bytes = canonical_json_bytes(boot) + b"\n"
    boot_path.write_bytes(expected_bytes)
    replacement_path.write_bytes(canonical_json_bytes(replacement) + b"\n")
    source = {
        "path": str(boot_path),
        "present": True,
        "safe_regular_file": True,
        "rejection": None,
        "bytes": len(expected_bytes),
        "sha256": sha256_bytes(expected_bytes),
    }
    real_open = Path.open
    swapped = False

    def swap_before_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal swapped
        if not swapped and os.path.normcase(os.path.abspath(path)) == os.path.normcase(
            os.path.abspath(boot_path)
        ):
            os.replace(replacement_path, boot_path)
            swapped = True
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", swap_before_open)
        with pytest.raises(ContractError, match="cambió entre validación y apertura"):
            _validate_pre_start_handshake_source(
                source,
                name="boot",
                expected_attempt_id=expected_attempt_id,
                verify_artifact=True,
            )
    assert swapped is True

    boot_path.write_bytes(expected_bytes)
    assert boot_path.read_bytes() == expected_bytes
    assert (
        _validate_pre_start_handshake_source(
            source,
            name="boot",
            expected_attempt_id=expected_attempt_id,
            verify_artifact=True,
        )
        == source
    )


def _post_start_payload(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    from test_readiness_h9r_aggregate_reconciliation import _stable_environment_evidence

    authority, key, receipt, unit, schedule = _authority_fixture(tmp_path)
    consumption = _receipt_wrapper(authority, receipt, state="consumed")
    start_payload = {
        "protocol_version": PROTOCOL_VERSION,
        "authorization_text_sha256": authority["authorization_text_sha256"],
        "ready_monotonic_ns": 10,
        "start_monotonic_ns": 20,
        "attempt_id": attempt_id(unit),
    }
    start_bytes = canonical_json_bytes(start_payload) + b"\n"
    execution_context = _stable_environment_evidence()
    execution_context["candidate"]["manifest_sha256"] = unit["candidate_manifest_sha256"]
    execution_context["tooling"]["manifest_sha256"] = authority["tooling_sha256"]
    execution_context["tooling"]["document_sha256"] = authority["document_sha256"]
    execution_context["limits"]["requested"].update(
        {
            "preflight_deadline_seconds": 300.0,
            "handshake_deadline_seconds": 60.0,
            "workload_deadline_seconds": 7_200.0,
        }
    )
    execution_context["schedule"] = schedule
    payload: dict[str, Any] = {
        "schema_version": POST_START_FAILURE_SCHEMA_VERSION,
        "phase": "post-start-terminal",
        "identity": {
            "attempt_id": attempt_id(unit),
            "unit": unit,
            "evidence_path": str(tmp_path / "attempt.json"),
            "wall_time_finished_utc": "2026-08-13T00:00:00+00:00",
        },
        "authority": authority,
        "execution_context": execution_context,
        "authorization_consumption": consumption,
        "start": {
            **start_payload,
            "path": str(tmp_path / "start.json"),
            "bytes": len(start_bytes),
            "sha256": sha256_bytes(start_bytes),
        },
        "cause": {
            "stage": "terminal_publication",
            "error_type": "OSError",
            "message": "fsync falló",
            "traceback_sha256": _digest("trace"),
        },
        "cleanup": {
            "worker_tree_empty": True,
            "client_tree_empty": True,
            "cleanup_complete": True,
            "job_accounting": None,
            "client_accounting": None,
            "errors": [],
        },
        "observed": {
            "causal_sources": {
                "authority": _causal_source(
                    tmp_path / "authority.json", canonical_json_bytes(authority) + b"\n"
                ),
                "authorization_consumption": _causal_source(
                    receipt,
                    canonical_json_bytes(
                        {
                            "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
                            "authorization_id": authority["authorization_id"],
                            "attempt_id": authority["attempt_id"],
                            "authority_sha256": canonical_json_sha256(authority),
                            "state": "consumed",
                            "consumed_at_utc": consumption["consumed_at_utc"],
                        }
                    )
                    + b"\n",
                ),
                "start": _causal_source(tmp_path / "start.json", start_bytes),
            },
            "sidecars": _sidecars(tmp_path),
            "output_inventory": {"available": True, "value": [], "error": None},
            "final_manifest": _absent(tmp_path / "manifest.json"),
            "quarantined_manifest": _absent(tmp_path / "quarantine.json"),
            "disk_final": {"available": False, "value": None, "error": "censo falló"},
        },
        "gates": {
            "start_observed": True,
            "authorization_consumed": True,
            "evidence_atomic": True,
        },
        "result": {"classification": "evidence_incomplete", "statistically_eligible": False},
    }
    return payload, key


def test_emergency_schemas_son_publicos_y_productivos_por_defecto() -> None:
    assert pre_start_failure_json_schema()["$id"] == PRE_START_FAILURE_SCHEMA_VERSION
    assert post_start_failure_json_schema()["$id"] == POST_START_FAILURE_SCHEMA_VERSION
    pre_scope = pre_start_failure_json_schema()["properties"]["authority"]["properties"]["scope"]
    post_scope = post_start_failure_json_schema()["properties"]["authority"]["properties"]["scope"]
    assert pre_scope == post_scope == {"enum": ["calibration-start"]}
    assert pre_start_failure_json_schema(allow_harness_test_authority=True)["properties"][
        "authority"
    ]["properties"]["scope"] == {"enum": ["calibration-start", "harness-test-only"]}
    assert internal_authorization_gate_json_schema()["properties"]["authority"]["properties"][
        "scope"
    ] == {"enum": ["calibration-start"]}
    assert internal_authorization_release_json_schema()["properties"]["role"] == {
        "enum": ["worker", "adapter", "candidate", "ui-client"]
    }
    assert (
        internal_authorization_precommit_json_schema()["$id"]
        == "nikodym.readiness.h9r.internal-authorization-precommit.v1"
    )


def test_pre_start_failure_rechaza_scope_implicit_start_y_receipt_consumido(tmp_path: Path) -> None:
    payload, key = _pre_start_payload(tmp_path)
    with pytest.raises(ContractError, match="productivo prohíbe"):
        validate_pre_start_failure_evidence(payload, trusted_authority_public_key_path=key)
    assert (
        validate_pre_start_failure_evidence(
            payload,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
        == payload
    )
    uppercase_signature = copy.deepcopy(payload)
    uppercase_signature["authority"]["signature_ed25519"] = uppercase_signature["authority"][
        "signature_ed25519"
    ].upper()
    assert (
        uppercase_signature["authority"]["signature_ed25519"]
        != payload["authority"]["signature_ed25519"]
    )
    with pytest.raises(ContractError, match="64 bytes hex"):
        validate_pre_start_failure_evidence(
            uppercase_signature,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    placeholder_signature = copy.deepcopy(payload)
    placeholder_signature["authority"]["signature_ed25519"] = "0" * 128
    with pytest.raises(ContractError, match="64 bytes hex"):
        validate_pre_start_failure_evidence(
            placeholder_signature,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    uppercase_digest = copy.deepcopy(payload)
    uppercase_digest["authority"]["authorization_id"] = uppercase_digest["authority"][
        "authorization_id"
    ].upper()
    assert (
        uppercase_digest["authority"]["authorization_id"]
        != payload["authority"]["authorization_id"]
    )
    with pytest.raises(ContractError, match="lowercase canónico"):
        validate_pre_start_failure_evidence(
            uppercase_digest,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    started = copy.deepcopy(payload)
    started["observed"]["handshake"]["start"] = {
        "path": str(tmp_path / "start.json"),
        "present": True,
        "safe_regular_file": True,
        "rejection": None,
        "bytes": 1,
        "sha256": _digest("start"),
    }
    started["observed"]["causal_sources"]["start"]["observed"] = copy.deepcopy(
        started["observed"]["handshake"]["start"]
    )
    with pytest.raises(ContractError, match="START causalmente ausente"):
        validate_pre_start_failure_evidence(
            started,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    consumed = copy.deepcopy(payload)
    receipt_path = Path(consumed["authorization_reservation"]["receipt"]["path"])
    consumed["authorization_reservation"] = _receipt_wrapper(
        consumed["authority"], receipt_path, state="consumed"
    )
    consumed["authorization_reservation"]["receipt"].update(
        {"present": True, "safe_regular_file": True, "rejection": None}
    )
    consumed_receipt_payload = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": consumed["authority"]["authorization_id"],
        "attempt_id": consumed["authority"]["attempt_id"],
        "authority_sha256": canonical_json_sha256(consumed["authority"]),
        "state": "consumed",
        "consumed_at_utc": consumed["authorization_reservation"]["consumed_at_utc"],
    }
    consumed["observed"]["causal_sources"]["authorization_consumption"] = _causal_source(
        receipt_path, canonical_json_bytes(consumed_receipt_payload) + b"\n"
    )
    consumed["gates"]["authorization_reserved"] = False
    assert (
        validate_pre_start_failure_evidence(
            consumed,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
        == consumed
    )


def test_terminal_rechaza_sidecar_copia_fuera_del_workdir(tmp_path: Path) -> None:
    payload, key = _pre_start_payload(tmp_path)
    payload["observed"]["sidecars"][0]["identity"]["path"] = str(
        tmp_path.parent / "resources-copy.jsonl"
    )
    with pytest.raises(ContractError, match="path no deriva del workdir"):
        validate_pre_start_failure_evidence(
            payload,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )


def test_post_start_rechaza_sidecar_con_hardlink(tmp_path: Path) -> None:
    payload, key = _post_start_payload(tmp_path)
    resources = tmp_path / "telemetry" / ATTEMPT_SIDECAR_FILENAMES["resources"]
    resources.parent.mkdir()
    raw = b"{}\n"
    resources.write_bytes(raw)
    alias = tmp_path / "resources-hardlink.jsonl"
    try:
        os.link(resources, alias)
    except OSError as exc:  # pragma: no cover - volumen sin soporte de hardlinks
        pytest.skip(f"hardlinks no disponibles: {exc}")
    payload["observed"]["sidecars"][0]["identity"] = {
        "path": str(resources),
        "present": True,
        "safe_regular_file": True,
        "rejection": None,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }
    with pytest.raises(ContractError, match="hardlinks prohibidos"):
        validate_post_start_failure_evidence(
            payload,
            trusted_authority_public_key_path=key,
            verify_artifacts=True,
            allow_harness_test_authority=True,
        )


def test_identidad_terminal_acredita_rechazo_hardlink_y_lo_revalida(tmp_path: Path) -> None:
    source_path = tmp_path / "telemetry" / "resources.jsonl"
    source_path.parent.mkdir()
    source_path.write_bytes(b"{}\n")
    alias = tmp_path / "resources-hardlink.jsonl"
    try:
        os.link(source_path, alias)
    except OSError as exc:  # pragma: no cover - volumen sin soporte de hardlinks
        pytest.skip(f"hardlinks no disponibles: {exc}")
    identity = {
        "path": str(source_path),
        "present": True,
        "safe_regular_file": False,
        "rejection": "multiple_hardlinks",
        "bytes": None,
        "sha256": None,
    }
    assert (
        _validate_post_start_source_identity(identity, context="sidecar", verify_artifact=True)
        == identity
    )
    alias.unlink()
    with pytest.raises(ContractError, match="rechazo hardlink no reconcilia"):
        _validate_post_start_source_identity(identity, context="sidecar", verify_artifact=True)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("quarantine_hash", "conserva bytes/ruta"),
        ("gate_present", "authorization_gate no acredita ausencia"),
        ("candidate_claim_present", "role_claims.candidate no acredita ausencia"),
        ("wrong_classification", "clasificación causal cerrada"),
    ),
)
def test_pre_start_quarantine_liga_start_forjado_a_gate_y_claims_ausentes(
    tmp_path: Path, mutation: str, match: str
) -> None:
    payload, key = _pre_start_payload(tmp_path)
    start_path = Path(payload["observed"]["handshake"]["start"]["path"])
    receipt_path = Path(payload["authorization_reservation"]["receipt"]["path"])
    unexpected = b"forged-start\n"
    claim_paths = {
        role: internal_authorization_release_paths(
            receipt_path,
            attempt_id_value=str(payload["identity"]["attempt_id"]),
            role=role,
        )[1]
        for role in ("worker", "adapter", "candidate", "ui-client")
    }
    payload["observed"]["unexpected_start_quarantine"] = {
        "original_snapshot": {
            "path": str(start_path),
            "bytes": len(unexpected),
            "sha256": sha256_bytes(unexpected),
        },
        "quarantined": {
            "path": str(tmp_path / "scratch" / "invalid-pre-start-token.json"),
            "present": True,
            "safe_regular_file": True,
            "rejection": None,
            "bytes": len(unexpected),
            "sha256": sha256_bytes(unexpected),
        },
        "moved_atomically": True,
        "worker_created": True,
        "authorization_gate": _absent(tmp_path / "internal-authorization-gate.json"),
        "role_claims": {role: _absent(path) for role, path in claim_paths.items()},
    }
    payload["cause"]["classification"] = "invariant_failure"
    payload["result"]["classification"] = "invariant_failure"
    assert (
        validate_pre_start_failure_evidence(
            payload,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
        == payload
    )
    tampered = copy.deepcopy(payload)
    quarantine = tampered["observed"]["unexpected_start_quarantine"]
    if mutation == "quarantine_hash":
        quarantine["quarantined"]["sha256"] = _digest("otro")
    elif mutation == "gate_present":
        quarantine["authorization_gate"].update(
            {
                "present": True,
                "safe_regular_file": True,
                "rejection": None,
                "bytes": 1,
                "sha256": _digest("gate"),
            }
        )
    elif mutation == "candidate_claim_present":
        quarantine["role_claims"]["candidate"].update(
            {
                "present": True,
                "safe_regular_file": True,
                "rejection": None,
                "bytes": 1,
                "sha256": _digest("claim"),
            }
        )
    else:
        tampered["cause"]["classification"] = "limits_not_applied"
        tampered["result"]["classification"] = "limits_not_applied"
    with pytest.raises(ContractError, match=match):
        validate_pre_start_failure_evidence(
            tampered,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )


def test_post_start_failure_liga_start_consumo_gates_y_scope_explicito(tmp_path: Path) -> None:
    payload, key = _post_start_payload(tmp_path)
    with pytest.raises(ContractError, match="productivo prohíbe"):
        validate_post_start_failure_evidence(payload, trusted_authority_public_key_path=key)
    assert (
        validate_post_start_failure_evidence(
            payload,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
        == payload
    )
    wrong_start = copy.deepcopy(payload)
    wrong_start["start"]["attempt_id"] = _digest("otro")
    with pytest.raises(ContractError, match="token START"):
        validate_post_start_failure_evidence(
            wrong_start,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    gate = copy.deepcopy(payload)
    gate["gates"]["authorization_consumed"] = False
    with pytest.raises(ContractError, match="gates"):
        validate_post_start_failure_evidence(
            gate,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    other_host = copy.deepcopy(payload)
    other_host["execution_context"]["environment"]["windows_version"] = "10.0.other"
    assert (
        validate_post_start_failure_evidence(
            other_host,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
        == other_host
    )
    wrong_tooling = copy.deepcopy(payload)
    wrong_tooling["execution_context"]["tooling"]["manifest_sha256"] = _digest("other-tooling")
    with pytest.raises(ContractError, match="unidad/autoridad/deadlines"):
        validate_post_start_failure_evidence(
            wrong_tooling,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )


def _write_canonical(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _live_identity(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "present": True,
        "safe_regular_file": True,
        "rejection": None,
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _internal_gate_fixture(
    tmp_path: Path,
) -> tuple[dict[str, Any], Path, Path, Path, dict[str, str], dict[str, str]]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    unit = {**_unit(), "flow_id": "F-UI", "flow_step": "run"}
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    receipt_path = tmp_path / "consumption.json"
    tooling_file = tmp_path / "harness.py"
    tooling_file.write_text("VALUE = 1\n", encoding="utf-8")
    tooling_payload = tooling_file.read_bytes()
    manifest_files = [
        {
            "relative_path": "readiness_h9r/harness.py",
            "bytes": len(tooling_payload),
            "sha256": sha256_bytes(tooling_payload),
        }
    ]
    import_roots: list[dict[str, object]] = []
    root_kinds = {
        "_cffi_backend": "file",
        "cffi": "package_tree",
        "cryptography": "package_tree",
        "pyarrow": "package_tree",
        "threadpoolctl": "file",
    }
    for name, kind in sorted(root_kinds.items()):
        if kind == "file":
            root_path = tmp_path / f"{name}.py"
            root_path.write_text(f"NAME = {name!r}\n", encoding="utf-8")
            payload = root_path.read_bytes()
            entries: list[dict[str, object]] = [
                {
                    "relative_path": root_path.name,
                    "logical_bytes": len(payload),
                    "sha256": sha256_bytes(payload),
                }
            ]
            tree_sha256 = canonical_json_sha256(entries)
        else:
            root_path = tmp_path / name
            root_path.mkdir()
            module_path = root_path / "__init__.py"
            module_path.write_text(f"NAME = {name!r}\n", encoding="utf-8")
            selected_paths = [module_path]
            if name == "pyarrow":
                libs_path = tmp_path / "pyarrow.libs"
                libs_path.mkdir()
                library_path = libs_path / "arrow-test.dll"
                library_path.write_bytes(b"test-only")
                selected_paths.append(library_path)
            entries = [
                {
                    "relative_path": path.relative_to(tmp_path).as_posix(),
                    "logical_bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
                for path in sorted(selected_paths, key=lambda item: item.as_posix())
            ]
            payload = module_path.read_bytes()
            tree_sha256 = canonical_json_sha256(entries)
        import_roots.append(
            {
                "name": name,
                "kind": kind,
                "path": str(root_path.resolve()),
                "files": len(entries),
                "logical_bytes": sum(int(entry["logical_bytes"]) for entry in entries),
                "tree_sha256": tree_sha256,
            }
        )
    executable_path = Path(sys.executable).resolve()
    executable_payload = executable_path.read_bytes()
    harness_runtime = {
        "python_executable": {
            "path": str(executable_path),
            "bytes": len(executable_payload),
            "sha256": sha256_bytes(executable_payload),
        },
        "python_version": "test-only",
        "implementation": "CPython",
        "import_roots": import_roots,
    }
    tooling_manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "files": manifest_files,
        "harness_runtime": harness_runtime,
    }
    tooling_sha256 = canonical_json_sha256(tooling_manifest)
    document_path = tmp_path / "protocol.md"
    document_path.write_text("protocolo test-only\n", encoding="utf-8")
    document_hashes = {"protocol": sha256_bytes(document_path.read_bytes())}

    cell = {name: value for name, value in unit.items() if name != "attempt_ordinal"}
    schedule_seed = _digest("gate-schedule-seed")
    schedule_units = [{**cell, "attempt_ordinal": ordinal} for ordinal in range(1, 4)]
    schedule_units.sort(
        key=lambda candidate: (
            sha256_bytes(f"{schedule_seed}\0{attempt_id(candidate)}".encode("ascii")),
            attempt_id(candidate),
        )
    )
    schedule = {
        "schema_version": "nikodym.readiness.h9r.schedule.v1",
        "phase": "screening",
        "permutation_algorithm": "sha256-key-sort-v1",
        "permutation_seed_sha256": schedule_seed,
        "cells": [cell],
        "units": schedule_units,
    }
    schedule_path = tmp_path / "schedule.json"
    _write_canonical(schedule_path, schedule)
    schedule_sha256 = canonical_json_sha256(schedule)
    schedule_position = [attempt_id(item) for item in schedule_units].index(attempt_id(unit))

    private_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "authority.pem"
    key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    authorization_id = _digest("gate-authorization")
    consumption_path_sha256 = authorization_consumption_path_digest(receipt_path)
    statement = authorization_statement(
        unit,
        authorization_id=authorization_id,
        authorization_consumption_path_sha256=consumption_path_sha256,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        schedule_position=schedule_position,
        scope="harness-test-only",
    )
    statement_path = tmp_path / "authorization.txt"
    statement_path.write_bytes(statement)
    authority: dict[str, Any] = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "scope": "harness-test-only",
        "start_authorized": False,
        "authorization_id": authorization_id,
        "authorization_consumption_path_sha256": consumption_path_sha256,
        "authorized_unit": unit,
        "attempt_id": attempt_id(unit),
        "authorization_text_sha256": sha256_bytes(statement),
        "document_sha256": document_hashes,
        "tooling_sha256": tooling_sha256,
        "schedule_sha256": schedule_sha256,
        "schedule_position": schedule_position,
        "signer_public_key_sha256": trusted_authority_key_identity(key_path)[1],
        "signature_ed25519": "0" * 128,
    }
    authority["signature_ed25519"] = private_key.sign(authority_signing_bytes(authority)).hex()
    authority_path = tmp_path / "authority.json"
    _write_canonical(authority_path, authority)

    receipt_payload = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": authorization_id,
        "attempt_id": attempt_id(unit),
        "authority_sha256": canonical_json_sha256(authority),
        "state": "consumed",
        "consumed_at_utc": "2026-08-13T00:00:00+00:00",
    }
    _write_canonical(receipt_path, receipt_payload)
    consumption = {
        "authorization_id": authorization_id,
        "authorization_consumption_path_sha256": consumption_path_sha256,
        "state": "consumed",
        "consumed_at_utc": receipt_payload["consumed_at_utc"],
        "attempt_id": attempt_id(unit),
        "authority_sha256": canonical_json_sha256(authority),
        "receipt": {
            "path": str(receipt_path.resolve()),
            "bytes": receipt_path.stat().st_size,
            "sha256": sha256_bytes(receipt_path.read_bytes()),
        },
    }
    start_payload = {
        "protocol_version": PROTOCOL_VERSION,
        "authorization_text_sha256": authority["authorization_text_sha256"],
        "ready_monotonic_ns": 10,
        "start_monotonic_ns": 20,
        "attempt_id": attempt_id(unit),
    }
    start_path = tmp_path / "start.json"
    _write_canonical(start_path, start_payload)
    requests = {
        "worker": _digest("worker-request"),
        "adapter": _digest("adapter-request"),
        "candidate": _digest("candidate-request"),
        "ui-client": _digest("ui-request"),
    }
    capabilities = {
        "worker": _digest("worker-capability"),
        "adapter": _digest("adapter-capability"),
        "candidate": _digest("candidate-capability"),
        "ui-client": _digest("ui-capability"),
    }
    nonce = "12" * 32
    precommit = write_internal_authorization_precommit(
        authority=authority,
        unit=unit,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        workdir_path=workdir,
        request_payload_sha256=requests,
        capability_commitment_sha256=capabilities,
        supervisor_instance_nonce=nonce,
        authorization_consumption_path=receipt_path,
    )
    gate = {
        "schema_version": "nikodym.readiness.h9r.internal-authorization-gate.v1",
        "attempt_id": attempt_id(unit),
        "unit": unit,
        "authority": authority,
        "bindings": {
            "workdir_path": str(workdir.resolve()),
            "workdir_sha256": sha256_bytes(
                str(workdir.resolve()).replace("\\", "/").casefold().encode("utf-8")
            ),
            "worker_request_core_sha256": requests["worker"],
            "adapter_request_sha256": requests["adapter"],
            "candidate_request_sha256": requests["candidate"],
            "ui_client_request_sha256": requests["ui-client"],
            "worker_capability_commitment_sha256": capabilities["worker"],
            "adapter_capability_commitment_sha256": capabilities["adapter"],
            "candidate_capability_commitment_sha256": capabilities["candidate"],
            "ui_client_capability_commitment_sha256": capabilities["ui-client"],
        },
        "sources": {
            "authority": _live_identity(authority_path),
            "authorization_text": _live_identity(statement_path),
            "trusted_authority_public_key": _live_identity(key_path),
            "schedule": _live_identity(schedule_path),
        },
        "tooling": {
            "protocol_version": PROTOCOL_VERSION,
            "files": [{**manifest_files[0], "path": str(tooling_file.resolve())}],
            "harness_runtime": harness_runtime,
            "manifest_sha256": tooling_sha256,
            "document_sha256": document_hashes,
            "document_paths": {"protocol": str(document_path.resolve())},
        },
        "internal_authorization_precommit": {
            name: precommit[name] for name in ("path", "bytes", "sha256")
        },
        "supervisor_instance_nonce": nonce,
        "authorization_consumption": consumption,
        "start": {
            **start_payload,
            "path": str(start_path.resolve()),
            "bytes": start_path.stat().st_size,
            "sha256": sha256_bytes(start_path.read_bytes()),
        },
    }
    return gate, key_path, workdir, receipt_path, requests, capabilities


@pytest.mark.parametrize("role", ("worker", "adapter", "candidate", "ui-client"))
def test_internal_gate_y_claim_one_shot_rechazan_replay_por_rol(tmp_path: Path, role: str) -> None:
    gate, key, workdir, receipt, requests, capabilities = _internal_gate_fixture(tmp_path)
    with pytest.raises(ContractError, match="productivo prohíbe"):
        validate_internal_authorization_gate(
            gate,
            expected_role=role,
            expected_request_payload_sha256=requests[role],
            expected_capability_commitment_sha256=capabilities[role],
            expected_workdir_path=workdir,
            trusted_authority_public_key_path=key,
        )
    assert (
        validate_internal_authorization_gate(
            gate,
            expected_role=role,
            expected_request_payload_sha256=requests[role],
            expected_capability_commitment_sha256=capabilities[role],
            expected_workdir_path=workdir,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
        == gate
    )
    reservation = write_internal_authorization_release_reservation(
        precommit=read_json_object(Path(gate["internal_authorization_precommit"]["path"])),
        role=role,
        request_payload_sha256=requests[role],
        capability_commitment_sha256=capabilities[role],
        authorization_consumption_path=receipt,
    )
    assert (
        validate_internal_authorization_release(
            reservation["value"],
            precommit=read_json_object(Path(gate["internal_authorization_precommit"]["path"])),
            role=role,
            request_payload_sha256=requests[role],
            capability_commitment_sha256=capabilities[role],
            expected_state="reserved-pre-start",
        )
        == reservation["value"]
    )
    claim = claim_internal_authorization_release(
        gate=gate,
        role=role,
        request_payload_sha256=requests[role],
        capability_commitment_sha256=capabilities[role],
        authorization_consumption_path=receipt,
    )
    assert (
        validate_internal_authorization_release(
            claim["value"],
            precommit=read_json_object(Path(gate["internal_authorization_precommit"]["path"])),
            role=role,
            request_payload_sha256=requests[role],
            capability_commitment_sha256=capabilities[role],
            expected_state="consumed",
            gate=gate,
        )
        == claim["value"]
    )
    with pytest.raises(ContractError, match=r"replay|destino existe"):
        claim_internal_authorization_release(
            gate=gate,
            role=role,
            request_payload_sha256=requests[role],
            capability_commitment_sha256=capabilities[role],
            authorization_consumption_path=receipt,
        )
    reserved_path, claimed_path = internal_authorization_release_paths(
        receipt, attempt_id_value=str(gate["attempt_id"]), role=role
    )
    assert reserved_path.is_file() and claimed_path.is_file()


@pytest.mark.parametrize("target", ("precommit", "release"))
def test_internal_claim_rechaza_hardlink_antes_de_publicar_claim(
    tmp_path: Path, target: str
) -> None:
    gate, _key, _workdir, receipt, requests, capabilities = _internal_gate_fixture(tmp_path)
    reservation = write_internal_authorization_release_reservation(
        precommit=read_json_object(Path(gate["internal_authorization_precommit"]["path"])),
        role="worker",
        request_payload_sha256=requests["worker"],
        capability_commitment_sha256=capabilities["worker"],
        authorization_consumption_path=receipt,
    )
    _reserved_path, claimed_path = internal_authorization_release_paths(
        receipt, attempt_id_value=str(gate["attempt_id"]), role="worker"
    )
    target_path = (
        Path(gate["internal_authorization_precommit"]["path"])
        if target == "precommit"
        else Path(reservation["path"])
    )
    alias = tmp_path / f"{target}-hardlink.json"
    try:
        os.link(target_path, alias)
    except OSError as exc:  # pragma: no cover - volumen sin soporte de hardlinks
        pytest.skip(f"hardlinks no disponibles: {exc}")
    with pytest.raises(ContractError, match="hardlinks prohibidos"):
        claim_internal_authorization_release(
            gate=gate,
            role="worker",
            request_payload_sha256=requests["worker"],
            capability_commitment_sha256=capabilities["worker"],
            authorization_consumption_path=receipt,
        )
    assert not os.path.lexists(claimed_path)
    alias.unlink()
    claim = claim_internal_authorization_release(
        gate=gate,
        role="worker",
        request_payload_sha256=requests["worker"],
        capability_commitment_sha256=capabilities["worker"],
        authorization_consumption_path=receipt,
    )
    assert Path(claim["path"]) == claimed_path


def test_internal_gate_rechaza_request_workdir_tooling_y_start_ajenos(tmp_path: Path) -> None:
    gate, key, workdir, _receipt, requests, capabilities = _internal_gate_fixture(tmp_path)
    with pytest.raises(ContractError, match="payload exacto"):
        validate_internal_authorization_gate(
            gate,
            expected_role="worker",
            expected_request_payload_sha256=_digest("otro-request"),
            expected_capability_commitment_sha256=capabilities["worker"],
            expected_workdir_path=workdir,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    with pytest.raises(ContractError, match="workdir_path"):
        validate_internal_authorization_gate(
            gate,
            expected_role="worker",
            expected_request_payload_sha256=requests["worker"],
            expected_capability_commitment_sha256=capabilities["worker"],
            expected_workdir_path=tmp_path / "otro-workdir",
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
    tooling_path = Path(gate["tooling"]["files"][0]["path"])
    tooling_path.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(ContractError, match="identidad viva"):
        validate_internal_authorization_gate(
            gate,
            expected_role="worker",
            expected_request_payload_sha256=requests["worker"],
            expected_capability_commitment_sha256=capabilities["worker"],
            expected_workdir_path=workdir,
            trusted_authority_public_key_path=key,
            allow_harness_test_authority=True,
        )
