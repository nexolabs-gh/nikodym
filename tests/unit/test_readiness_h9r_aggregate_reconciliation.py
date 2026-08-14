from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from scripts.readiness_h9r import aggregate as aggregate_module
from scripts.readiness_h9r.aggregate import (
    _attempt_summary,
    _reopen_bound_attempt_source,
    derive_hypothesis_candidates,
    evaluate_bracket,
    validate_statistical_progression,
)
from scripts.readiness_h9r.artifacts import JsonlRecorder, disk_footprint_summary
from scripts.readiness_h9r.contracts import (
    CAPS,
    PROTOCOL_VERSION,
    SCHEDULE_SCHEMA_VERSION,
    ContractError,
    attempt_id,
    canonical_json_bytes,
    canonical_json_sha256,
    sha256_bytes,
)
from scripts.readiness_h9r.telemetry import (
    derive_consumer_window_summary,
    summarize_telemetry_records,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _roots(*, scratch_allocated: int = 0) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "root": name,
            "logical_bytes": scratch_allocated if name == "scratch" else 0,
            "allocated_bytes": scratch_allocated if name == "scratch" else 0,
            "files": 0,
            "allocation_reliable": True,
            "allocation_sources": [],
        }
        for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
    }


def _sample(
    ordinal: int,
    *,
    peak_job_commit: int,
    scratch_allocated: int,
    client_working_set: int,
    client_job_commit: int,
) -> dict[str, Any]:
    return {
        "sample_ordinal": ordinal,
        "monotonic_ns": 1_000_000_000 + ordinal * 250_000_000,
        "wall_time_utc": f"2026-08-13T00:00:0{ordinal}+00:00",
        "sensor_duration_seconds": 0.001,
        "gap_seconds": 0.0 if ordinal == 0 else 0.25,
        "job": {
            "source": "windows_job_object",
            "total_user_time_100ns": 0,
            "total_kernel_time_100ns": 0,
            "total_user_seconds": 0.0,
            "total_kernel_seconds": 0.0,
            "total_page_fault_count": ordinal,
            "total_processes": 1,
            "active_processes": 1,
            "total_terminated_processes": 0,
            "peak_process_memory_commit_bytes": peak_job_commit,
            "peak_job_memory_commit_bytes": peak_job_commit,
            "current_job_memory_commit_bytes": peak_job_commit,
            "memory_usage_information_supported": True,
            "io": {
                "read_operations": ordinal,
                "write_operations": ordinal,
                "other_operations": ordinal,
                "read_bytes": ordinal,
                "write_bytes": ordinal,
                "other_bytes": ordinal,
            },
        },
        "tree": {
            "pids": [10],
            "processes": [
                {
                    "pid": 10,
                    "creation_time_100ns": 100,
                    "cpu_user_100ns": 0,
                    "cpu_kernel_100ns": 0,
                    "page_fault_count": ordinal,
                    "working_set_bytes": 20 + ordinal,
                    "peak_working_set_bytes": 20 + ordinal,
                    "pagefile_bytes": 10 + ordinal,
                    "peak_pagefile_bytes": 10 + ordinal,
                    "private_usage_bytes": 10 + ordinal,
                    "logical_cpu_count_effective": 4,
                    "affinity_mask": 15,
                    "system_affinity_mask": 15,
                    "processor_groups": [0],
                    "io": {
                        "read_operations": ordinal,
                        "write_operations": ordinal,
                        "other_operations": ordinal,
                        "read_bytes": ordinal,
                        "write_bytes": ordinal,
                        "other_bytes": ordinal,
                    },
                }
            ],
            "threads": [
                {
                    "pid": 10,
                    "tid": 20 + index,
                    "creation_time_100ns": 200 + index,
                    "affinity_mask": 15,
                    "processor_group": 0,
                    "logical_cpu_count_effective": 4,
                }
                for index in range(ordinal + 1)
            ],
            "process_query_errors": [],
            "thread_query_errors": [],
        },
        "system_memory": {
            "physical_total_bytes": 16 * 1024**3,
            "physical_available_bytes": 8 * 1024**3 - ordinal,
            "commit_limit_bytes": 16 * 1024**3,
            "commit_available_bytes": 8 * 1024**3 - ordinal,
            "commit_used_bytes": 8 * 1024**3 + ordinal,
            "memory_load_percent": 50,
            "virtual_total_bytes": 128 * 1024**3,
            "virtual_available_bytes": 64 * 1024**3,
        },
        "disk": {
            "volume_free_bytes": 8 * 1024**3 - scratch_allocated,
            "roots": _roots(scratch_allocated=scratch_allocated),
        },
        "external_processes": {
            "supervisor": {
                "pid": 30,
                "creation_time_100ns": 300,
                "cpu_user_100ns": 0,
                "cpu_kernel_100ns": 0,
                "page_fault_count": ordinal,
                "working_set_bytes": 30 + ordinal,
                "peak_working_set_bytes": 30 + ordinal,
                "pagefile_bytes": 30 + ordinal,
                "peak_pagefile_bytes": 30 + ordinal,
                "private_usage_bytes": 30 + ordinal,
                "affinity_mask": 15,
                "system_affinity_mask": 15,
                "logical_cpu_count_effective": 4,
                "processor_groups": [0],
                "io": {
                    "read_operations": 0,
                    "write_operations": 0,
                    "other_operations": 0,
                    "read_bytes": 0,
                    "write_bytes": 0,
                    "other_bytes": 0,
                },
            },
            "client": {
                "pid": 40,
                "creation_time_100ns": 400,
                "cpu_user_100ns": 0,
                "cpu_kernel_100ns": 0,
                "page_fault_count": ordinal,
                "working_set_bytes": client_working_set,
                "peak_working_set_bytes": client_working_set,
                "pagefile_bytes": client_working_set,
                "peak_pagefile_bytes": client_working_set,
                "private_usage_bytes": client_working_set,
                "affinity_mask": 15,
                "system_affinity_mask": 15,
                "logical_cpu_count_effective": 4,
                "processor_groups": [0],
                "io": {
                    "read_operations": 0,
                    "write_operations": 0,
                    "other_operations": 0,
                    "read_bytes": 0,
                    "write_bytes": 0,
                    "other_bytes": 0,
                },
            },
            "client_job": {
                "accounting": {
                    "source": "windows_external_cleanup_job",
                    "root_pid": 40,
                    "peak_job_memory_commit_bytes": client_job_commit,
                    "current_job_memory_commit_bytes": client_job_commit,
                    "memory_usage_information_supported": True,
                    "total_user_time_100ns": 0,
                    "total_kernel_time_100ns": 0,
                    "total_user_seconds": 0.0,
                    "total_kernel_seconds": 0.0,
                    "total_page_fault_count": ordinal,
                    "total_processes": 1,
                    "active_processes": 1,
                    "total_terminated_processes": 0,
                    "peak_process_memory_commit_bytes": client_job_commit,
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
                    "pids": [40],
                    "processes": [
                        {
                            "pid": 40,
                            "creation_time_100ns": 400,
                            "cpu_user_100ns": 0,
                            "cpu_kernel_100ns": 0,
                            "page_fault_count": 0,
                            "working_set_bytes": client_working_set,
                            "peak_working_set_bytes": client_working_set,
                            "pagefile_bytes": client_job_commit,
                            "peak_pagefile_bytes": client_job_commit,
                            "private_usage_bytes": client_job_commit,
                            "affinity_mask": 15,
                            "system_affinity_mask": 15,
                            "logical_cpu_count_effective": 4,
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
                    ],
                    "threads": [],
                    "process_query_errors": [],
                    "thread_query_errors": [],
                },
            },
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
        "system_cpu": {"user_100ns": 0, "kernel_100ns": 0, "idle_100ns": 0},
        "native_pools": {
            "OMP_NUM_THREADS": "4",
            "MKL_NUM_THREADS": "4",
            "OPENBLAS_NUM_THREADS": "4",
            "NUMEXPR_NUM_THREADS": "4",
            "BLIS_NUM_THREADS": "4",
            "VECLIB_MAXIMUM_THREADS": "4",
        },
        "host_attribution": {
            "unattributed_cpu_100ns": 0,
            "unattributed_commit_growth_bytes": 0,
            "proven_external": False,
            "unattributed_observed": False,
            "proven_processes": [],
        },
        "guard_classification": None,
        "guard_reason": None,
    }


def _records() -> list[dict[str, Any]]:
    return [
        _sample(
            0,
            peak_job_commit=100,
            scratch_allocated=10,
            client_working_set=50,
            client_job_commit=60,
        ),
        _sample(
            1,
            peak_job_commit=250,
            scratch_allocated=50,
            client_working_set=70,
            client_job_commit=80,
        ),
    ]


def _stable_environment_evidence() -> dict[str, Any]:
    stable_file = {
        "path": "C:/runtime/file",
        "relative_path": "file",
        "bytes": 1,
        "allocated_bytes": 4096,
        "allocation_reliable": True,
        "allocation_source": "test",
        "sha256": _digest("file"),
    }
    return {
        "environment": {
            "platform": "win32",
            "windows_release": "11",
            "windows_version": "10.0.26100",
            "machine": "AMD64",
            "processor": "CPU",
            "logical_cpus_host": 8,
            "processor_topology": {
                "active_group_count": 1,
                "active_processor_count_by_group": [8],
                "total_active_logical_processors": 8,
                "primary_group": 0,
                "primary_group_affinity_mask": 255,
            },
            "affinity_before_confinement": {"process_mask": 255, "system_mask": 255},
            "system_memory": {
                "nominal_physical_bytes": 16_000,
                "physical_total_bytes": 15_000,
                "physical_visible_bytes": 15_000,
                "physical_available_bytes": 7_000,
                "commit_limit_bytes": 30_000,
                "commit_available_bytes": 20_000,
                "commit_used_bytes": 10_000,
                "memory_load_percent": 50,
                "virtual_total_bytes": 100_000,
                "virtual_available_bytes": 80_000,
            },
            "power_scheme": {
                "available": True,
                "returncode": 0,
                "stdout": "Balanced",
                "stderr": "",
            },
            "volume": {
                "path": "C:\\dynamic",
                "free_bytes": 100,
                "volume_root": "C:\\",
                "volume_name": "System",
                "volume_serial": 1,
                "filesystem": "NTFS",
                "filesystem_flags": 1,
                "maximum_component_length": 255,
                "allocation_unit_bytes": 4096,
            },
            "native_pool_environment": {
                "OMP_NUM_THREADS": "4",
                "MKL_NUM_THREADS": "4",
                "OPENBLAS_NUM_THREADS": "4",
                "NUMEXPR_NUM_THREADS": "4",
                "BLIS_NUM_THREADS": None,
                "VECLIB_MAXIMUM_THREADS": None,
            },
        },
        "candidate": {
            "manifest_sha256": _digest("candidate-manifest"),
            "manifest_root": "C:/candidate",
            "source_sha": "1" * 40,
            "wheel": {**stable_file, "sha256": _digest("wheel")},
            "sdist": {**stable_file, "sha256": _digest("sdist")},
            "lock": {**stable_file, "sha256": _digest("lock")},
            "runtime": {
                "python_executable": stable_file,
                "environment": stable_file,
                "installed_tree": {
                    "relative_path": "site-packages/nikodym",
                    "files": 1,
                    "logical_bytes": 1,
                    "sha256": _digest("tree"),
                    "path": "C:/candidate/site-packages/nikodym",
                },
                "provenance": {
                    "probe_schema_version": "nikodym.readiness.h9r.runtime-provenance.v1",
                    "isolation_flags": ["-I", "-B", "-S"],
                    "no_site": True,
                    "distribution": "nikodym",
                    "version": "1",
                    "distribution_root": "C:/candidate/site-packages",
                    "dist_info_path": "C:/candidate/site-packages/nikodym.dist-info",
                    "metadata_sha256": _digest("metadata"),
                    "record_sha256": _digest("record"),
                    "record_entries": 1,
                    "imported_package_path": "C:/candidate/site-packages/nikodym",
                    "imported_package_sha256": _digest("package"),
                    "installed_tree_sha256": _digest("tree"),
                    "wheel_sha256": _digest("wheel"),
                    "lock_sha256": _digest("lock"),
                    "probe_payload_sha256": _digest("probe"),
                },
            },
        },
        "tooling": {
            "protocol_version": PROTOCOL_VERSION,
            "manifest_sha256": _digest("tooling"),
            "document_sha256": {"protocol": _digest("document")},
            "harness_runtime": {
                "python_executable": {
                    "path": "C:/harness/python.exe",
                    "bytes": 1,
                    "sha256": _digest("harness-python"),
                },
                "python_version": "3.13.7",
                "implementation": "CPython",
                "import_roots": [
                    {
                        "name": name,
                        "kind": kind,
                        "path": f"C:/harness/site-packages/{name}",
                        "files": 1,
                        "logical_bytes": 1,
                        "tree_sha256": _digest(f"harness-root:{name}"),
                    }
                    for name, kind in (
                        ("_cffi_backend", "file"),
                        ("cffi", "package_tree"),
                        ("cryptography", "package_tree"),
                        ("pyarrow", "package_tree"),
                        ("threadpoolctl", "file"),
                    )
                ],
            },
            "harness_runtime_snapshot_sha256": _digest("harness-runtime-snapshot"),
        },
        "limits": {
            "requested": {
                "logical_cpu_count": 4,
                "affinity_mask": 15,
                "job_memory_commit_limit_bytes": CAPS["C4"],
                "preflight_deadline_seconds": 120,
                "handshake_deadline_seconds": 30,
                "workload_deadline_seconds": 600,
            },
            "effective": {
                "limit_flags": 0x2200,
                "affinity_mask": 15,
                "logical_cpu_count": 4,
                "processor_group": 0,
                "group_affinities": [{"processor_group": 0, "affinity_mask": 15}],
                "job_memory_commit_limit_bytes": CAPS["C4"],
                "kill_on_job_close": True,
                "affinity_enforced": True,
                "job_memory_enforced": True,
            },
        },
    }


def test_environment_identity_liga_tooling_documentos_y_excluye_headroom_dinamico() -> None:
    evidence = _stable_environment_evidence()
    baseline = aggregate_module._execution_environment_sha256(evidence)
    normal_attempt_shape = copy.deepcopy(evidence)
    snapshot_sha = normal_attempt_shape["tooling"].pop("harness_runtime_snapshot_sha256")
    normal_attempt_shape["tooling"]["runtime_descriptors"] = {
        "harness_runtime_snapshot": {
            "path": "C:/work/control/harness-runtime-snapshot.json",
            "bytes": 1,
            "sha256": snapshot_sha,
        }
    }
    normal_attempt_shape["tooling"]["files"] = []
    assert aggregate_module._execution_environment_sha256(normal_attempt_shape) == baseline
    dynamic = copy.deepcopy(evidence)
    dynamic["environment"]["volume"]["free_bytes"] = 1
    dynamic["environment"]["volume"]["path"] = "D:\\otro"
    dynamic["environment"]["system_memory"]["physical_available_bytes"] = 1
    assert aggregate_module._execution_environment_sha256(dynamic) == baseline
    for section, name in (("tooling", "manifest_sha256"),):
        altered = copy.deepcopy(evidence)
        altered[section][name] = _digest("tooling-drift")
        assert aggregate_module._execution_environment_sha256(altered) != baseline
    documents = copy.deepcopy(evidence)
    documents["tooling"]["document_sha256"]["protocol"] = _digest("doc-drift")
    assert aggregate_module._execution_environment_sha256(documents) != baseline
    harness_python = copy.deepcopy(evidence)
    harness_python["tooling"]["harness_runtime"]["python_executable"]["sha256"] = _digest(
        "harness-python-drift"
    )
    assert aggregate_module._execution_environment_sha256(harness_python) != baseline
    harness_root = copy.deepcopy(evidence)
    harness_root["tooling"]["harness_runtime"]["import_roots"][2]["tree_sha256"] = _digest(
        "harness-root-drift"
    )
    assert aggregate_module._execution_environment_sha256(harness_root) != baseline
    snapshot = copy.deepcopy(evidence)
    snapshot["tooling"]["harness_runtime_snapshot_sha256"] = _digest("snapshot-drift")
    assert aggregate_module._execution_environment_sha256(snapshot) != baseline


def test_builder_reabre_identity_evidence_path_y_rechaza_payload_a_path_b(tmp_path: Path) -> None:
    path = tmp_path / "attempt.json"
    payload_b = {"identity": {"evidence_path": str(path)}, "result": "B"}
    path.write_bytes(
        (
            json.dumps(payload_b, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    )
    assert _reopen_bound_attempt_source(payload_b) == payload_b
    payload_a = copy.deepcopy(payload_b)
    payload_a["result"] = "A"
    with pytest.raises(ContractError, match="payload de intento"):
        _reopen_bound_attempt_source(payload_a)
    path.write_text(json.dumps(payload_b), encoding="utf-8")
    with pytest.raises(ContractError, match="JSON no es canónico"):
        _reopen_bound_attempt_source(payload_b)


def test_builder_rechaza_hardlink_antes_de_abrir_evidencia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "attempt.json"
    payload = {"identity": {"evidence_path": str(path)}, "result": "B"}
    path.write_bytes(canonical_json_bytes(payload) + b"\n")
    alias = tmp_path / "attempt-hardlink.json"
    try:
        os.link(path, alias)
    except OSError as exc:  # pragma: no cover - volumen sin soporte de hardlinks
        pytest.skip(f"hardlinks no disponibles: {exc}")
    opened = False

    def forbidden_open(_path: Path, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal opened
        opened = True
        raise AssertionError("el destino no debe abrirse")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(ContractError, match="hardlinks prohibidos"):
        _reopen_bound_attempt_source(payload)
    assert opened is False


@pytest.mark.parametrize("kind", ("leaf", "ancestor"))
def test_builder_rechaza_reparse_antes_de_abrir_evidencia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root = tmp_path / "linked"
    if kind == "leaf":
        link_root.mkdir()
    else:
        try:
            os.symlink(real_root, link_root, target_is_directory=True)
        except OSError as exc:  # pragma: no cover - host sin privilegio de symlink
            pytest.skip(f"symlink de directorio no disponible: {exc}")
    evidence_path = link_root / "attempt.json"
    payload = {"identity": {"evidence_path": str(evidence_path)}, "result": "B"}
    real_path = real_root / "attempt.json"
    real_path.write_bytes(canonical_json_bytes(payload) + b"\n")
    if kind == "leaf":
        try:
            os.symlink(real_path, evidence_path)
        except OSError as exc:  # pragma: no cover - host sin privilegio de symlink
            pytest.skip(f"symlink de archivo no disponible: {exc}")
    opened = False

    def forbidden_open(_path: Path, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal opened
        opened = True
        raise AssertionError("el destino no debe abrirse")

    monkeypatch.setattr(Path, "open", forbidden_open)
    with pytest.raises(ContractError, match=r"reparse|symlink"):
        _reopen_bound_attempt_source(payload)
    assert opened is False


def test_builder_rechaza_swap_despues_de_identidad_y_restaura_byte_exacto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "attempt.json"
    replacement_path = tmp_path / "attempt-replacement.json"
    payload_a = {"identity": {"evidence_path": str(path)}, "result": "A"}
    payload_b = {"identity": {"evidence_path": str(path)}, "result": "B"}
    expected_bytes = canonical_json_bytes(payload_a) + b"\n"
    path.write_bytes(expected_bytes)
    replacement_path.write_bytes(canonical_json_bytes(payload_b) + b"\n")
    real_open = Path.open
    swapped = False

    def swap_before_open(target: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal swapped
        if not swapped and os.path.normcase(os.path.abspath(target)) == os.path.normcase(
            os.path.abspath(path)
        ):
            os.replace(replacement_path, path)
            swapped = True
        return real_open(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", swap_before_open)
        with pytest.raises(ContractError, match="cambió entre validación y apertura"):
            _reopen_bound_attempt_source(payload_a)
    assert swapped is True

    path.write_bytes(expected_bytes)
    assert path.read_bytes() == expected_bytes
    assert _reopen_bound_attempt_source(payload_a) == payload_a


def test_build_aggregate_no_admite_summary_sin_identity_productiva(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summarized = False

    def forbidden_summary(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal summarized
        summarized = True
        raise AssertionError("summary no debe invocarse")

    monkeypatch.setattr(aggregate_module, "_summarize_started_evidence", forbidden_summary)
    with pytest.raises(ContractError, match="carece de identity"):
        aggregate_module.build_aggregate(
            cell_identity={
                "candidate_manifest_sha256": _digest("candidate"),
                "flow_id": "F-SCORE-TRAIN",
                "flow_step": "train",
                "fixture_manifest_sha256": _digest("fixture"),
                "config_hash": _digest("config"),
                "geometry_id": "G-",
                "cap_id": "C4",
            },
            expected_attempt_ids=[_digest("attempt")],
            attempts=[{"attempt_id": _digest("attempt")}],
            trusted_authority_public_key_path=tmp_path / "unused-key.pem",
        )
    assert summarized is False


def test_summary_se_reconstruye_de_records_incluido_cliente_y_maximos() -> None:
    summary = summarize_telemetry_records(_records(), baseline_roots=_roots())
    assert summary["records"] == 2
    assert summary["peak_job_memory_commit_bytes"] == 250
    assert summary["peak_tree_working_set_bytes"] == 21
    assert summary["peak_client_working_set_bytes"] == 70
    assert summary["peak_client_job_commit_bytes"] == 80
    assert summary["maximum_threads_observed"] == 2
    assert summary["observed_process_identities"] == [{"pid": 10, "creation_time_100ns": 100}]
    assert summary["observed_client_process_identities"] == [
        {"pid": 40, "creation_time_100ns": 400}
    ]
    assert summary["peak_incremental_allocated_bytes"] == 50
    assert summary["root_high_water"]["scratch"] == {
        "peak_logical_bytes": 50,
        "peak_allocated_bytes": 50,
        "peak_incremental_allocated_bytes": 50,
    }


def test_summary_rechaza_cardinalidad_y_monotonicidad_alteradas() -> None:
    ordinal_gap = _records()
    ordinal_gap[1]["sample_ordinal"] = 2
    with pytest.raises(ContractError, match="sample_ordinal"):
        summarize_telemetry_records(ordinal_gap, baseline_roots=_roots())
    monotonic_reversed = _records()
    monotonic_reversed[1]["monotonic_ns"] = monotonic_reversed[0]["monotonic_ns"] - 1
    with pytest.raises(ContractError, match="no-decreciente"):
        summarize_telemetry_records(monotonic_reversed, baseline_roots=_roots())
    false_gap = _records()
    false_gap[1]["gap_seconds"] = 0.249
    with pytest.raises(ContractError, match="no deriva de monotonic_ns"):
        summarize_telemetry_records(false_gap, baseline_roots=_roots())


def test_consumer_window_incluye_brackets_y_nombra_peak_job_acumulativo() -> None:
    records = [
        _sample(
            ordinal,
            peak_job_commit=700 if ordinal < 3 else 900,
            scratch_allocated=10 + ordinal,
            client_working_set=1,
            client_job_commit=1,
        )
        for ordinal in range(4)
    ]
    for ordinal, record in enumerate(records):
        record["job"]["total_user_time_100ns"] = 100 + ordinal * 20
        record["job"]["total_user_seconds"] = record["job"]["total_user_time_100ns"] / 10_000_000
    records[-1]["tree"]["processes"][0]["working_set_bytes"] = 999
    records[-1]["tree"]["processes"][0]["peak_working_set_bytes"] = 999
    records[-1]["disk"]["roots"] = _roots(scratch_allocated=888)
    boundary = [
        {
            "event": "first_open_or_byte",
            "monotonic_ns": 1_125_000_000,
            "provider": "harness_owned_consumer_open_v1",
        },
        {"event": "rename_complete", "monotonic_ns": 1_625_000_000},
    ]
    window, _overhead = derive_consumer_window_summary(
        records,
        boundary_events=boundary,
        ready_monotonic_ns=900_000_000,
        tree_empty_monotonic_ns=2_000_000_000,
        baseline_roots=_roots(),
    )
    assert window["sample_ordinals"] == [0, 1, 2, 3]
    assert window["coverage"]["inside_sample_ordinals"] == [1, 2]
    assert window["peak_tree_working_set_bytes"] == 999
    assert window["peak_incremental_allocated_bytes"] == 888
    assert window["peak_job_memory_commit_bytes_observed_during_window"] == 900
    assert "peak_job_memory_commit_bytes" not in window
    assert window["total_job_cpu_delta_100ns"] == 60


def _evidence_with_sidecar(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    records = _records()
    recorder = JsonlRecorder(tmp_path / "resources.jsonl", name="resources")
    for record in records:
        recorder.append(record)
    metadata = recorder.finalize()
    baseline = _roots()
    baseline_volume_free = 8 * 1024**3
    summary = summarize_telemetry_records(
        records,
        baseline_roots=baseline,
        baseline_volume_free_bytes=baseline_volume_free,
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    boundary_events = [
        {"event": "ready", "monotonic_ns": 900_000_000},
        {"event": "start", "monotonic_ns": 950_000_000},
        {
            "event": "first_open_or_byte",
            "monotonic_ns": 1_000_000_000,
            "kind": "first_open",
            "provider": "harness_owned_consumer_open_v1",
            "request_id": "a" * 64,
            "protected": [],
        },
        {"event": "rename_complete", "monotonic_ns": 1_250_000_000},
        {"event": "tree_empty", "monotonic_ns": 1_500_000_000},
    ]
    consumer_window, overhead = derive_consumer_window_summary(
        records,
        boundary_events=boundary_events,
        ready_monotonic_ns=900_000_000,
        tree_empty_monotonic_ns=1_500_000_000,
        baseline_roots=baseline,
    )
    summary["consumer_window"] = consumer_window
    summary["overhead"] = overhead
    footprint = disk_footprint_summary(
        baseline,
        [*[record["disk"]["roots"] for record in records], records[-1]["disk"]["roots"]],
    )
    unit = {
        "candidate_manifest_sha256": _digest("candidate"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": _digest("fixture"),
        "config_hash": _digest("config"),
        "geometry_id": "G0",
        "cap_id": "C6",
        "attempt_ordinal": 1,
    }
    cell = {name: unit[name] for name in aggregate_module.CELL_IDENTITY_FIELDS}
    seed = _digest("screening-seed")
    units = [{**cell, "attempt_ordinal": ordinal} for ordinal in range(1, 4)]
    units.sort(
        key=lambda candidate: (
            sha256_bytes(f"{seed}\0{attempt_id(candidate)}".encode("ascii")),
            attempt_id(candidate),
        )
    )
    schedule = {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "phase": "screening",
        "permutation_algorithm": "sha256-key-sort-v1",
        "permutation_seed_sha256": seed,
        "cells": [cell],
        "units": units,
    }
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_bytes(canonical_json_bytes(schedule) + b"\n")
    schedule_digest = canonical_json_sha256(schedule)
    evidence = {
        "identity": {"unit": unit, "evidence_path": str(tmp_path / "attempt.json")},
        "authority": {
            "schedule_sha256": schedule_digest,
            "schedule_position": units.index(unit),
        },
        "tooling": {"launch_sources": {"schedule": {"path": str(schedule_path)}}},
        "limits": {"effective": {"affinity_mask": 15, "processor_group": 0}},
        "boundary": {"events": boundary_events},
        "resources": {
            "sidecars": [metadata],
            "summary": summary,
            "disk_baseline_volume_free_bytes": baseline_volume_free,
            "disk_baseline": baseline,
            "disk_final": copy.deepcopy(records[-1]["disk"]["roots"]),
            "disk_footprint": footprint,
            "job_accounting": {"peak_job_memory_commit_bytes": 300},
        },
        "result": {"classification": "success"},
    }
    return evidence, cell


def test_attempt_summary_rechaza_metricas_y_footprint_autofirmados(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted_key = tmp_path / "trusted-authority.pub"
    observed_keys: list[Path] = []

    def validate_stub(
        evidence: dict[str, Any],
        *,
        verify_artifacts: bool,
        trusted_authority_public_key_path: Path,
    ) -> dict[str, Any]:
        assert verify_artifacts is True
        observed_keys.append(trusted_authority_public_key_path)
        return evidence

    monkeypatch.setattr(aggregate_module, "validate_attempt_evidence", validate_stub)
    monkeypatch.setattr(
        aggregate_module,
        "_execution_environment_sha256",
        lambda _validated: _digest("execution-environment"),
    )
    evidence, cell = _evidence_with_sidecar(tmp_path)
    rebuilt = _attempt_summary(evidence, cell, trusted_authority_public_key_path=trusted_key)
    assert rebuilt["metrics"] == {
        "wall_seconds": 0.25,
        "peak_job_memory_commit_bytes": 300.0,
        "peak_incremental_allocated_bytes": 50.0,
    }

    altered_summary = copy.deepcopy(evidence)
    altered_summary["resources"]["summary"]["peak_job_memory_commit_bytes"] = 251
    with pytest.raises(ContractError, match=r"resources\.summary"):
        _attempt_summary(altered_summary, cell, trusted_authority_public_key_path=trusted_key)

    forged_guard = copy.deepcopy(evidence)
    forged_guard["resources"]["summary"]["guard_classification"] = "job_memory_limit"
    forged_guard["resources"]["summary"]["guard_reason"] = "declaración no causada"
    with pytest.raises(ContractError, match=r"resources\.summary"):
        _attempt_summary(forged_guard, cell, trusted_authority_public_key_path=trusted_key)

    altered_footprint = copy.deepcopy(evidence)
    altered_footprint["resources"]["disk_footprint"]["peak_incremental_allocated_bytes"] = 49
    with pytest.raises(ContractError, match="disk_footprint"):
        _attempt_summary(altered_footprint, cell, trusted_authority_public_key_path=trusted_key)

    altered_final_disk = copy.deepcopy(evidence)
    altered_final_disk["resources"]["disk_final"]["scratch"]["allocated_bytes"] = 100
    with pytest.raises(ContractError, match="disk_footprint"):
        _attempt_summary(altered_final_disk, cell, trusted_authority_public_key_path=trusted_key)

    final_only_footprint = copy.deepcopy(altered_final_disk)
    final_only_footprint["resources"]["disk_final"]["scratch"]["logical_bytes"] = 100
    baseline = final_only_footprint["resources"]["disk_baseline"]
    final_only_footprint["resources"]["disk_footprint"] = disk_footprint_summary(
        baseline,
        [
            *[record["disk"]["roots"] for record in _records()],
            final_only_footprint["resources"]["disk_final"],
        ],
    )
    rebuilt_final = _attempt_summary(
        final_only_footprint, cell, trusted_authority_public_key_path=trusted_key
    )
    assert rebuilt_final["metrics"]["peak_incremental_allocated_bytes"] == 100.0
    assert final_only_footprint["resources"]["summary"] == evidence["resources"]["summary"]

    accounting_below_sample = copy.deepcopy(evidence)
    accounting_below_sample["resources"]["job_accounting"]["peak_job_memory_commit_bytes"] = 249
    with pytest.raises(ContractError, match="muestreado excede"):
        _attempt_summary(
            accounting_below_sample, cell, trusted_authority_public_key_path=trusted_key
        )

    missing_accounting = copy.deepcopy(evidence)
    missing_accounting["resources"]["job_accounting"] = {}
    with pytest.raises(ContractError, match="carece de job_accounting"):
        _attempt_summary(missing_accounting, cell, trusted_authority_public_key_path=trusted_key)

    altered_cardinality = copy.deepcopy(evidence)
    altered_cardinality["resources"]["sidecars"][0]["records"] = 1
    with pytest.raises(ContractError, match="cardinalidad"):
        _attempt_summary(altered_cardinality, cell, trusted_authority_public_key_path=trusted_key)
    assert observed_keys == [trusted_key] * 9


def test_attempt_summary_rechaza_swap_del_schedule_y_restaura_byte_exacto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted_key = tmp_path / "trusted-authority.pub"

    def validate_stub(
        evidence: dict[str, Any],
        *,
        verify_artifacts: bool,
        trusted_authority_public_key_path: Path,
    ) -> dict[str, Any]:
        assert verify_artifacts is True
        assert trusted_authority_public_key_path == trusted_key
        return evidence

    monkeypatch.setattr(aggregate_module, "validate_attempt_evidence", validate_stub)
    monkeypatch.setattr(
        aggregate_module,
        "_execution_environment_sha256",
        lambda _validated: _digest("execution-environment"),
    )
    evidence, cell = _evidence_with_sidecar(tmp_path)
    schedule_path = Path(evidence["tooling"]["launch_sources"]["schedule"]["path"])
    expected_bytes = schedule_path.read_bytes()
    replacement_path = tmp_path / "schedule-replacement.json"
    replacement_path.write_bytes(canonical_json_bytes({"schema_version": "replacement.v1"}) + b"\n")
    real_open = Path.open
    swapped = False

    def swap_before_open(target: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal swapped
        if not swapped and os.path.normcase(os.path.abspath(target)) == os.path.normcase(
            os.path.abspath(schedule_path)
        ):
            os.replace(replacement_path, schedule_path)
            swapped = True
        return real_open(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", swap_before_open)
        with pytest.raises(ContractError, match="cambió entre validación y apertura"):
            _attempt_summary(evidence, cell, trusted_authority_public_key_path=trusted_key)
    assert swapped is True

    schedule_path.write_bytes(expected_bytes)
    assert schedule_path.read_bytes() == expected_bytes
    assert (
        _attempt_summary(evidence, cell, trusted_authority_public_key_path=trusted_key)[
            "schedule_sha256"
        ]
        == evidence["authority"]["schedule_sha256"]
    )


def _published_aggregate(
    geometry_id: str,
    *,
    fixture: str,
    config: str,
    candidate: str = "candidate",
    following: bool = False,
) -> dict[str, Any]:
    if following:
        schedules = {
            "screening": None,
            "confirmation": None,
            "bracket_following": _digest("bracket-schedule"),
        }
        count = 3
    elif geometry_id == "G0":
        schedules = {
            "screening": _digest("shared-screening-schedule"),
            "confirmation": _digest("candidate-confirmation-schedule"),
            "bracket_following": None,
        }
        count = 10
    else:
        schedules = {
            "screening": _digest("shared-screening-schedule"),
            "confirmation": None,
            "bracket_following": None,
        }
        count = 3
    return {
        "execution_environment_sha256": _digest("shared-execution-environment"),
        "cell_identity": {
            "candidate_manifest_sha256": _digest(candidate),
            "flow_id": "F-SCORE-TRAIN",
            "flow_step": "train",
            "fixture_manifest_sha256": _digest(fixture),
            "config_hash": _digest(config),
            "geometry_id": geometry_id,
            "cap_id": "C6",
        },
        "schedules": schedules,
        "attempts": [
            {
                "attempt_ordinal": ordinal,
                "classification": "job_memory_limit" if following else "success",
                "metrics": {
                    "wall_seconds": 10.0,
                    "peak_job_memory_commit_bytes": 100.0,
                    "peak_incremental_allocated_bytes": 10.0,
                },
            }
            for ordinal in range(1, count + 1)
        ],
        "statistics": {
            "wall_seconds": {"u": 10.0, "mad_star": 0.0, "stable": True},
            "peak_job_memory_commit_bytes": {"u": 100.0, "mad_star": 0.0, "stable": True},
            "peak_incremental_allocated_bytes": {"u": 10.0, "mad_star": 0.0, "stable": True},
        },
    }


def test_bracket_admite_fixture_y_config_propios_por_geometria(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted_key = tmp_path / "trusted-authority.pub"
    monkeypatch.setattr(
        aggregate_module,
        "validate_aggregate",
        lambda value, *, trusted_authority_public_key_path: value,
    )
    monkeypatch.setattr(
        aggregate_module,
        "evaluate_cell",
        lambda aggregate, *, phase, cap_id, trusted_authority_public_key_path: {
            "all_success": True,
            "eligible": phase == "confirmation",
        },
    )
    previous = _published_aggregate("G-", fixture="fixture-minus", config="config-minus")
    candidate = _published_aggregate("G0", fixture="fixture-zero", config="config-zero")
    following = _published_aggregate(
        "G+", fixture="fixture-plus", config="config-plus", following=True
    )
    assert (
        evaluate_bracket(
            previous=previous,
            candidate=candidate,
            following=following,
            trusted_authority_public_key_path=trusted_key,
        )["bracket_measured"]
        is True
    )

    other_candidate = _published_aggregate(
        "G0", fixture="fixture-zero", config="config-zero", candidate="other"
    )
    with pytest.raises(ContractError, match="candidato/flujo/step/cap"):
        evaluate_bracket(
            previous=previous,
            candidate=other_candidate,
            following=following,
            trusted_authority_public_key_path=trusted_key,
        )
    non_adjacent = copy.deepcopy(candidate)
    non_adjacent["cell_identity"]["geometry_id"] = "G+"
    with pytest.raises(ContractError, match="adyacentes"):
        evaluate_bracket(
            previous=previous,
            candidate=non_adjacent,
            following=following,
            trusted_authority_public_key_path=trusted_key,
        )

    wrong_following_phase = copy.deepcopy(following)
    wrong_following_phase["schedules"] = {
        "screening": _digest("incorrect-screening"),
        "confirmation": None,
        "bracket_following": None,
    }
    with pytest.raises(ContractError, match=r"G\+"):
        evaluate_bracket(
            previous=previous,
            candidate=candidate,
            following=wrong_following_phase,
            trusted_authority_public_key_path=trusted_key,
        )

    unrelated_screening = copy.deepcopy(candidate)
    unrelated_screening["schedules"]["screening"] = _digest("unrelated-screening")
    with pytest.raises(ContractError, match="mismo schedule screening"):
        evaluate_bracket(
            previous=previous,
            candidate=unrelated_screening,
            following=following,
            trusted_authority_public_key_path=trusted_key,
        )

    other_environment = copy.deepcopy(following)
    other_environment["execution_environment_sha256"] = _digest("other-environment")
    with pytest.raises(ContractError, match="identidades estables de entorno"):
        evaluate_bracket(
            previous=previous,
            candidate=candidate,
            following=other_environment,
            trusted_authority_public_key_path=trusted_key,
        )


def test_derivacion_se_cierra_si_bracket_headroom_o_estabilidad_no_estan_medidos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted_key = tmp_path / "trusted-authority.pub"
    previous = _published_aggregate("G-", fixture="fixture-minus", config="config-minus")
    candidate = _published_aggregate("G0", fixture="fixture-zero", config="config-zero")
    following = _published_aggregate(
        "G+", fixture="fixture-plus", config="config-plus", following=True
    )
    monkeypatch.setattr(
        aggregate_module,
        "validate_aggregate",
        lambda value, *, trusted_authority_public_key_path: value,
    )
    for attempt in candidate["attempts"]:
        attempt["metrics"]["peak_job_memory_commit_bytes"] = float(CAPS["C6"])
    with pytest.raises(ContractError, match="sin bracket"):
        derive_hypothesis_candidates(
            previous=previous,
            candidate=candidate,
            following=following,
            trusted_authority_public_key_path=trusted_key,
        )

    for attempt in candidate["attempts"]:
        attempt["metrics"]["peak_job_memory_commit_bytes"] = 100.0
    derived = derive_hypothesis_candidates(
        previous=previous,
        candidate=candidate,
        following=following,
        trusted_authority_public_key_path=trusted_key,
    )
    assert derived == {
        "budget_candidate_seconds": 30,
        "memory_needed_bytes": 256 * 1024**2,
        "disk_free_candidate_bytes": 5 * 256 * 1024**2,
    }

    candidate["statistics"]["wall_seconds"]["stable"] = False
    with pytest.raises(ContractError, match="sin bracket"):
        derive_hypothesis_candidates(
            previous=previous,
            candidate=candidate,
            following=following,
            trusted_authority_public_key_path=trusted_key,
        )


def test_progresion_estadistica_exige_cardinalidad_ordinals_y_screening() -> None:
    attempts = [
        {"attempt_ordinal": ordinal, "classification": "success"} for ordinal in range(1, 11)
    ]
    assert (
        validate_statistical_progression(attempts, phase="confirmation")["screening_promoted"]
        is True
    )

    no_screening = copy.deepcopy(attempts)
    no_screening[1]["classification"] = "job_memory_limit"
    with pytest.raises(ContractError, match="screening previo"):
        validate_statistical_progression(no_screening, phase="confirmation")
    with pytest.raises(ContractError, match="exactamente 10"):
        validate_statistical_progression(attempts[:-1], phase="confirmation")
    wrong_ordinal = copy.deepcopy(attempts)
    wrong_ordinal[-1]["attempt_ordinal"] = 9
    with pytest.raises(ContractError, match="exactos/contiguos"):
        validate_statistical_progression(wrong_ordinal, phase="confirmation")


def test_build_aggregate_conserva_ordinal_y_acepta_posiciones_permutadas(
    tmp_path: Path,
) -> None:
    cell = {
        "candidate_manifest_sha256": _digest("candidate"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": _digest("fixture-minus"),
        "config_hash": _digest("config-minus"),
        "geometry_id": "G-",
        "cap_id": "C6",
    }
    summaries = [
        {
            "attempt_id": attempt_id({**cell, "attempt_ordinal": ordinal}),
            "attempt_ordinal": ordinal,
            "schedule_sha256": _digest("screening-schedule"),
            "schedule_phase": "screening",
            "linked_screening_schedule_sha256": None,
            "schedule_position": position,
            "evidence_sha256": _digest(f"evidence-{ordinal}"),
            "evidence_path": str(tmp_path / f"attempt-{ordinal}.json"),
            "evidence_schema_version": aggregate_module.ATTEMPT_SCHEMA_VERSION,
            "classification": "success",
            "execution_environment_sha256": _digest("execution-environment"),
            "metrics": {
                "wall_seconds": float(ordinal),
                "peak_job_memory_commit_bytes": float(ordinal * 100),
                "peak_incremental_allocated_bytes": float(ordinal * 10),
            },
            "terminal_cause": None,
        }
        for ordinal, position in ((1, 8), (2, 1), (3, 5))
    ]

    aggregate = aggregate_module._assemble_aggregate_from_summaries(
        cell_identity=cell,
        expected_attempt_ids=[str(summary["attempt_id"]) for summary in summaries],
        summaries=summaries,
    )
    assert [attempt["schedule_position"] for attempt in aggregate["attempts"]] == [8, 1, 5]
    assert aggregate["statistics"]["peak_job_memory_commit_bytes"]["values"] == [
        100.0,
        200.0,
        300.0,
    ]
    assert aggregate["statistics"]["peak_job_memory_commit_bytes"]["maximum"] == 300.0

    duplicated_position = copy.deepcopy(summaries)
    duplicated_position[2]["schedule_position"] = 1
    with pytest.raises(ContractError, match="posiciones duplicadas dentro"):
        aggregate_module._assemble_aggregate_from_summaries(
            cell_identity=cell,
            expected_attempt_ids=[str(summary["attempt_id"]) for summary in duplicated_position],
            summaries=duplicated_position,
        )

    mixed_tooling_or_host = copy.deepcopy(summaries)
    mixed_tooling_or_host[-1]["execution_environment_sha256"] = _digest("other-tooling")
    with pytest.raises(ContractError, match="mezcla hosts/runtime/power/volumen/límites"):
        aggregate_module._assemble_aggregate_from_summaries(
            cell_identity=cell,
            expected_attempt_ids=[str(summary["attempt_id"]) for summary in mixed_tooling_or_host],
            summaries=mixed_tooling_or_host,
        )


def test_build_aggregate_cuenta_terminal_post_start_y_detiene_prefijo(
    tmp_path: Path,
) -> None:
    cell = {
        "candidate_manifest_sha256": _digest("candidate"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": _digest("fixture-minus"),
        "config_hash": _digest("config-minus"),
        "geometry_id": "G-",
        "cap_id": "C6",
    }
    schedule_sha256 = _digest("screening-schedule")
    expected_ids = [attempt_id({**cell, "attempt_ordinal": ordinal}) for ordinal in range(1, 4)]
    success = {
        "attempt_id": expected_ids[0],
        "attempt_ordinal": 1,
        "schedule_sha256": schedule_sha256,
        "schedule_phase": "screening",
        "linked_screening_schedule_sha256": None,
        "schedule_position": 0,
        "evidence_sha256": _digest("evidence-1"),
        "evidence_path": str(tmp_path / "attempt-1.json"),
        "evidence_schema_version": aggregate_module.ATTEMPT_SCHEMA_VERSION,
        "classification": "success",
        "execution_environment_sha256": _digest("execution-environment"),
        "metrics": {
            "wall_seconds": 1.0,
            "peak_job_memory_commit_bytes": 100.0,
            "peak_incremental_allocated_bytes": 10.0,
        },
        "terminal_cause": None,
    }
    terminal = {
        "attempt_id": expected_ids[1],
        "attempt_ordinal": 2,
        "schedule_sha256": schedule_sha256,
        "schedule_phase": "screening",
        "linked_screening_schedule_sha256": None,
        "schedule_position": 1,
        "evidence_sha256": _digest("evidence-2"),
        "evidence_path": str(tmp_path / "attempt-2.json"),
        "evidence_schema_version": aggregate_module.POST_START_FAILURE_SCHEMA_VERSION,
        "classification": "evidence_incomplete",
        "execution_environment_sha256": _digest("execution-environment"),
        "metrics": None,
        "terminal_cause": {
            "stage": "terminal_publication",
            "error_type": "OSError",
            "message": "fallo durable tras START",
            "traceback_sha256": _digest("traceback"),
        },
    }
    summaries = [success, terminal]
    aggregate = aggregate_module._assemble_aggregate_from_summaries(
        cell_identity=cell,
        expected_attempt_ids=expected_ids,
        summaries=summaries,
    )
    assert aggregate["received_attempt_ids"] == [success["attempt_id"], terminal["attempt_id"]]
    assert aggregate["completeness"] == {
        "missing": [expected_ids[2]],
        "extra": [],
        "duplicates": [],
        "order_matches": True,
        "complete": False,
    }
    mixed_terminal = copy.deepcopy(summaries)
    mixed_terminal[-1]["execution_environment_sha256"] = _digest("other-host")
    with pytest.raises(ContractError, match="mezcla hosts/runtime/power/volumen/límites"):
        aggregate_module._assemble_aggregate_from_summaries(
            cell_identity=cell,
            expected_attempt_ids=expected_ids,
            summaries=mixed_terminal,
        )
    assert aggregate["attempts"][-1]["classification"] == "evidence_incomplete"
    assert aggregate["statistics"]["wall_seconds"]["values"] == [1.0]

    spoofed_tail = [*expected_ids[:2], _digest("tail-autofirmado")]
    with pytest.raises(ContractError, match=r"cell_identity \+ ordinales"):
        aggregate_module._assemble_aggregate_from_summaries(
            cell_identity=cell,
            expected_attempt_ids=spoofed_tail,
            summaries=summaries,
        )
    persisted_tail_spoof = copy.deepcopy(aggregate)
    persisted_tail_spoof["expected_attempt_ids"][-1] = spoofed_tail[-1]
    persisted_tail_spoof["completeness"]["missing"][-1] = spoofed_tail[-1]
    with pytest.raises(ContractError, match="no deriva de la celda/ordinales"):
        aggregate_module.validate_aggregate(
            persisted_tail_spoof,
            trusted_authority_public_key_path=tmp_path / "unused-key.pem",
        )

    replay_after_terminal = [*summaries, {**success, "attempt_id": expected_ids[2]}]
    with pytest.raises(ContractError, match="terminal post-START"):
        aggregate_module._assemble_aggregate_from_summaries(
            cell_identity=cell,
            expected_attempt_ids=[row["attempt_id"] for row in replay_after_terminal],
            summaries=replay_after_terminal,
        )


def test_terminal_confirmation_exige_schedule_ligado_al_screening_promovido() -> None:
    screening_sha = _digest("screening")
    attempts: list[dict[str, Any]] = [
        {
            "attempt_ordinal": ordinal,
            "schedule_phase": "screening",
            "schedule_sha256": screening_sha,
            "linked_screening_schedule_sha256": None,
            "classification": "success",
            "evidence_schema_version": aggregate_module.ATTEMPT_SCHEMA_VERSION,
        }
        for ordinal in range(1, 4)
    ]
    attempts.append(
        {
            "attempt_ordinal": 4,
            "schedule_phase": "confirmation",
            "schedule_sha256": _digest("confirmation"),
            "linked_screening_schedule_sha256": _digest("unlinked-screening"),
            "classification": "evidence_incomplete",
            "evidence_schema_version": aggregate_module.POST_START_FAILURE_SCHEMA_VERSION,
        }
    )
    with pytest.raises(ContractError, match="no liga screening promovido"):
        aggregate_module._validate_terminal_progression(attempts, expected_count=10)
    attempts[-1]["linked_screening_schedule_sha256"] = screening_sha
    assert aggregate_module._validate_terminal_progression(attempts, expected_count=10)
    prior_confirmation = {
        **attempts[-1],
        "evidence_schema_version": aggregate_module.ATTEMPT_SCHEMA_VERSION,
        "classification": "success",
        "linked_screening_schedule_sha256": _digest("other-screening"),
    }
    later_terminal = {
        **attempts[-1],
        "attempt_ordinal": 5,
    }
    with pytest.raises(ContractError, match="prefijo terminal confirmation"):
        aggregate_module._validate_terminal_progression(
            [*attempts[:3], prior_confirmation, later_terminal], expected_count=10
        )


def test_confirmation_acumula_screening_mas_siete_sin_repetir_ordinales(
    tmp_path: Path,
) -> None:
    cell = {
        "candidate_manifest_sha256": _digest("candidate"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": _digest("fixture-zero"),
        "config_hash": _digest("config-zero"),
        "geometry_id": "G0",
        "cap_id": "C6",
    }
    screening_hash = _digest("screening-schedule")
    confirmation_hash = _digest("confirmation-schedule")
    summaries = []
    for ordinal in range(1, 11):
        unit = {**cell, "attempt_ordinal": ordinal}
        is_screening = ordinal <= 3
        summaries.append(
            {
                "attempt_id": attempt_id(unit),
                "attempt_ordinal": ordinal,
                "schedule_sha256": screening_hash if is_screening else confirmation_hash,
                "schedule_phase": "screening" if is_screening else "confirmation",
                "linked_screening_schedule_sha256": None if is_screening else screening_hash,
                # Repetir posición entre schedules es válido; dentro de cada uno no.
                "schedule_position": ordinal - 1 if is_screening else ordinal - 4,
                "evidence_sha256": _digest(f"evidence-{ordinal}"),
                "evidence_path": str(tmp_path / f"attempt-{ordinal}.json"),
                "evidence_schema_version": aggregate_module.ATTEMPT_SCHEMA_VERSION,
                "classification": "success",
                "execution_environment_sha256": _digest("execution-environment"),
                "metrics": {
                    "wall_seconds": float(ordinal),
                    "peak_job_memory_commit_bytes": 100.0,
                    "peak_incremental_allocated_bytes": 10.0,
                },
                "terminal_cause": None,
            }
        )

    aggregate = aggregate_module._assemble_aggregate_from_summaries(
        cell_identity=cell,
        expected_attempt_ids=[str(summary["attempt_id"]) for summary in summaries],
        summaries=summaries,
    )
    assert aggregate["schedules"] == {
        "screening": screening_hash,
        "confirmation": confirmation_hash,
        "bracket_following": None,
    }
    assert [row["attempt_ordinal"] for row in aggregate["attempts"]] == list(range(1, 11))

    repeated_screening = copy.deepcopy(summaries)
    repeated_screening[3]["attempt_ordinal"] = 1
    with pytest.raises(ContractError, match="ordinales"):
        aggregate_module._assemble_aggregate_from_summaries(
            cell_identity=cell,
            expected_attempt_ids=[str(summary["attempt_id"]) for summary in repeated_screening],
            summaries=repeated_screening,
        )

    broken_link = copy.deepcopy(summaries)
    broken_link[4]["linked_screening_schedule_sha256"] = _digest("otro-screening")
    with pytest.raises(ContractError, match="liga exactamente"):
        aggregate_module._assemble_aggregate_from_summaries(
            cell_identity=cell,
            expected_attempt_ids=[str(summary["attempt_id"]) for summary in broken_link],
            summaries=broken_link,
        )
