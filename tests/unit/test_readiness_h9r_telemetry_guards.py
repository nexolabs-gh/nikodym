from __future__ import annotations

import copy
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from scripts.readiness_h9r.artifacts import verify_jsonl_sidecar
from scripts.readiness_h9r.contracts import GIB, ContractError
from scripts.readiness_h9r.telemetry import (
    SequenceSensor,
    TelemetrySampler,
    _derive_expected_host_attribution,
    derive_telemetry_guard,
    summarize_telemetry_records,
    validate_process_tree_snapshot,
)
from scripts.readiness_h9r.windows_job import (
    _classify_process_query_error,
    system_process_resource_snapshot,
)


def _roots(*, scratch: int = 0) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "root": name,
            "logical_bytes": scratch if name == "scratch" else 0,
            "allocated_bytes": scratch if name == "scratch" else 0,
            "files": int(name == "scratch" and scratch > 0),
            "allocation_reliable": True,
            "allocation_sources": ["synthetic"] if name == "scratch" and scratch else [],
        }
        for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
    }


def _sample(
    ordinal: int,
    *,
    host_cpu_100ns: int = 0,
    host_private: int = 1024,
    host_write: int = 0,
    physical: int = 4 * GIB,
    commit: int = 4 * GIB,
    volume_free: int = 8 * GIB,
    scratch: int = 0,
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
            "total_page_fault_count": 0,
            "total_processes": 1,
            "active_processes": 1,
            "total_terminated_processes": 0,
            "peak_process_memory_commit_bytes": 512,
            "peak_job_memory_commit_bytes": 1024,
            "current_job_memory_commit_bytes": 512,
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
            "pids": [101],
            "processes": [
                {
                    "pid": 101,
                    "creation_time_100ns": 1001,
                    "cpu_user_100ns": 0,
                    "cpu_kernel_100ns": 0,
                    "page_fault_count": 0,
                    "working_set_bytes": 4096,
                    "peak_working_set_bytes": 4096,
                    "pagefile_bytes": 2048,
                    "peak_pagefile_bytes": 2048,
                    "private_usage_bytes": 2048,
                    "logical_cpu_count_effective": 4,
                    "affinity_mask": 15,
                    "system_affinity_mask": 15,
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
            "threads": [
                {
                    "pid": 101,
                    "tid": 201,
                    "creation_time_100ns": 2001,
                    "affinity_mask": 15,
                    "processor_group": 0,
                    "logical_cpu_count_effective": 4,
                }
            ],
            "process_query_errors": [],
            "thread_query_errors": [],
        },
        "system_memory": {
            "physical_total_bytes": 8 * GIB,
            "physical_available_bytes": physical,
            "commit_limit_bytes": commit + 4 * GIB,
            "commit_available_bytes": commit,
            "commit_used_bytes": 4 * GIB,
            "memory_load_percent": 50,
            "virtual_total_bytes": 128 * GIB,
            "virtual_available_bytes": 64 * GIB,
        },
        "system_cpu": {
            "user_100ns": host_cpu_100ns,
            "kernel_100ns": 0,
            "idle_100ns": 0,
        },
        "disk": {"volume_free_bytes": volume_free, "roots": _roots(scratch=scratch)},
        "external_processes": {
            "supervisor": {
                "pid": 500,
                "creation_time_100ns": 5000,
                "cpu_user_100ns": 0,
                "cpu_kernel_100ns": 0,
                "page_fault_count": 0,
                "working_set_bytes": 1024,
                "peak_working_set_bytes": 1024,
                "pagefile_bytes": 1024,
                "peak_pagefile_bytes": 1024,
                "private_usage_bytes": 1024,
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
            "client": None,
            "client_job": None,
            "host_processes": {
                "processes": [
                    {
                        "pid": 9001,
                        "creation_time_100ns": 90001,
                        "image_name": "external.exe",
                        "cpu_user_100ns": host_cpu_100ns,
                        "cpu_kernel_100ns": 0,
                        "private_usage_bytes": host_private,
                        "working_set_bytes": host_private,
                        "io": {
                            "read_operations": 0,
                            "write_operations": 0,
                            "other_operations": 0,
                            "read_bytes": 0,
                            "write_bytes": host_write,
                            "other_bytes": 0,
                        },
                    }
                ],
                "query_errors": [],
                "coverage": {
                    "enumerated_process_count": 1,
                    "observed_process_count": 1,
                    "query_error_count": 0,
                    "expected_query_error_count": 0,
                    "unexpected_query_error_count": 0,
                    "snapshot_complete": True,
                },
            },
        },
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


def _attach_client_job(
    record: dict[str, Any], *, total_cpu_100ns: int, total_commit_bytes: int
) -> None:
    external = record["external_processes"]
    root = copy.deepcopy(external["supervisor"])
    root_cpu_100ns = min(total_cpu_100ns, 100)
    root.update(
        {
            "pid": 700,
            "creation_time_100ns": 7000,
            "cpu_user_100ns": root_cpu_100ns,
            "cpu_kernel_100ns": 0,
            "private_usage_bytes": 1024,
        }
    )
    descendant = copy.deepcopy(root)
    descendant_private = total_commit_bytes - int(root["private_usage_bytes"])
    descendant.update(
        {
            "pid": 701,
            "creation_time_100ns": 7010,
            "cpu_user_100ns": total_cpu_100ns - root_cpu_100ns,
            "private_usage_bytes": descendant_private,
            "working_set_bytes": descendant_private,
            "peak_working_set_bytes": descendant_private,
            "pagefile_bytes": descendant_private,
            "peak_pagefile_bytes": descendant_private,
        }
    )
    accounting = copy.deepcopy(record["job"])
    accounting.update(
        {
            "source": "windows_external_cleanup_job",
            "root_pid": 700,
            "total_user_time_100ns": total_cpu_100ns,
            "total_kernel_time_100ns": 0,
            "total_user_seconds": total_cpu_100ns / 10_000_000,
            "total_kernel_seconds": 0.0,
            "total_processes": 2,
            "active_processes": 2,
            "peak_process_memory_commit_bytes": max(
                int(root["private_usage_bytes"]), descendant_private
            ),
            "peak_job_memory_commit_bytes": total_commit_bytes,
            "current_job_memory_commit_bytes": total_commit_bytes,
        }
    )
    external["client"] = copy.deepcopy(root)
    external["client_job"] = {
        "accounting": accounting,
        "tree": {
            "pids": [700, 701],
            "processes": [root, descendant],
            "threads": [],
            "process_query_errors": [],
            "thread_query_errors": [],
        },
    }


def _derive_raw(records: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    return derive_telemetry_guard(
        records,
        baseline_roots=_roots(),
        baseline_volume_free_bytes=8 * GIB,
        expected_affinity_mask=15,
        expected_processor_group=0,
    )


def _derive(records: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    previous_attribution: dict[str, int] | None = None
    previous_host: dict[tuple[int, int], dict[str, int | str]] | None = None
    for record in records:
        expected, previous_attribution, previous_host = _derive_expected_host_attribution(
            record,
            previous_attribution=previous_attribution,
            previous_host_processes=previous_host,
        )
        record["host_attribution"] = expected
    return _derive_raw(records)


def test_fila_proceso_raw_exige_todos_los_contadores_instrumentales() -> None:
    records = [_sample(0)]
    del records[0]["tree"]["processes"][0]["pagefile_bytes"]
    with pytest.raises(ContractError, match="campos instrumentales exactos"):
        _derive(records)


def test_fila_proceso_raw_rechaza_peak_inferior_al_working_set() -> None:
    records = [_sample(0)]
    records[0]["tree"]["processes"][0]["peak_working_set_bytes"] = 4095
    with pytest.raises(ContractError, match="contadores imposibles"):
        _derive(records)


def test_censo_raw_reconcilia_pids_con_procesos_y_errores() -> None:
    records = [_sample(0)]
    records[0]["tree"]["pids"] = [102]
    with pytest.raises(ContractError, match="pids no reconcilia"):
        _derive(records)


def test_contador_acumulativo_por_pid_creation_no_retrocede() -> None:
    records = [_sample(0), _sample(1)]
    records[0]["tree"]["processes"][0]["peak_working_set_bytes"] = 8192
    with pytest.raises(ContractError, match="retrocede un contador acumulativo"):
        _derive(records)


def test_muestra_raw_rechaza_campo_top_extra() -> None:
    records = [_sample(0)]
    records[0]["campo_ignorado"] = "spoof"
    with pytest.raises(ContractError, match="campos exactos de muestra"):
        _derive(records)


def test_native_pools_raw_no_puede_desligarse_de_cpu_efectiva() -> None:
    records = [_sample(0)]
    records[0]["native_pools"]["OMP_NUM_THREADS"] = "3"
    assert _derive(records)[0] == "limits_not_applied"


def test_host_attribution_declarada_se_reconstruye_desde_contadores() -> None:
    records = [_sample(0)]
    records[0]["host_attribution"]["unattributed_cpu_100ns"] = 1
    records[0]["host_attribution"]["unattributed_observed"] = True
    with pytest.raises(ContractError, match="host_attribution no deriva"):
        _derive_raw(records)


def test_host_attribution_incluye_descendiente_del_job_cliente_sin_doble_conteo() -> None:
    records = [_sample(0), _sample(1)]
    _attach_client_job(records[0], total_cpu_100ns=0, total_commit_bytes=4096)
    _attach_client_job(records[1], total_cpu_100ns=500, total_commit_bytes=8192)
    records[1]["system_cpu"]["user_100ns"] = 500
    records[1]["system_memory"]["commit_used_bytes"] += 4096
    records[1]["system_memory"]["commit_available_bytes"] -= 4096

    first, attribution_state, host_state = _derive_expected_host_attribution(
        records[0], previous_attribution=None, previous_host_processes=None
    )
    second, current_state, _ = _derive_expected_host_attribution(
        records[1],
        previous_attribution=attribution_state,
        previous_host_processes=host_state,
    )
    assert first["unattributed_observed"] is False
    assert second["unattributed_cpu_100ns"] == 0
    assert second["unattributed_commit_growth_bytes"] == 0
    assert current_state["owned_cpu_100ns"] == 500
    assert current_state["owned_commit_bytes"] == 512 + 1024 + 8192
    assert _derive(records) == (None, None)

    fallback = copy.deepcopy(records)
    for record in fallback:
        record["external_processes"]["client_job"] = None
    fallback[1]["system_cpu"]["user_100ns"] = 100
    fallback[1]["system_memory"]["commit_used_bytes"] = fallback[0]["system_memory"][
        "commit_used_bytes"
    ]
    fallback[1]["system_memory"]["commit_available_bytes"] = fallback[0]["system_memory"][
        "commit_available_bytes"
    ]
    assert _derive(fallback) == (None, None)


def test_censo_host_raw_exige_fila_completa() -> None:
    records = [_sample(0)]
    del records[0]["external_processes"]["host_processes"]["processes"][0]["working_set_bytes"]
    with pytest.raises(ContractError, match="campos host exactos"):
        _derive(records)


@pytest.mark.parametrize("mutation", ("duplicate", "overlap"))
def test_query_errors_host_no_repite_ni_solapa_pid_observado(mutation: str) -> None:
    records = [_sample(0)]
    host = records[0]["external_processes"]["host_processes"]
    error = {
        "pid": 99 if mutation == "duplicate" else 9001,
        "image_name": "System",
        "category": "protected_or_system",
        "winerror": 5,
        "error": "access denied",
    }
    host["query_errors"] = [copy.deepcopy(error)] * (2 if mutation == "duplicate" else 1)
    host["coverage"] = {
        "enumerated_process_count": 1 + len(host["query_errors"]),
        "observed_process_count": 1,
        "query_error_count": len(host["query_errors"]),
        "expected_query_error_count": len(host["query_errors"]),
        "unexpected_query_error_count": 0,
        "snapshot_complete": True,
    }
    with pytest.raises(ContractError, match="PIDs observados/errores"):
        _derive(records)


@pytest.mark.parametrize("mutation", ("pid_spoof", "process_extra", "thread_error_pid"))
def test_censo_final_orphan_no_admite_filas_inventadas(mutation: str) -> None:
    tree = copy.deepcopy(_sample(0)["tree"])
    if mutation == "pid_spoof":
        tree["process_query_errors"] = [{"pid": 101, "error": "fabricado"}]
    elif mutation == "process_extra":
        tree["processes"][0]["caller_field"] = 1
    else:
        tree["thread_query_errors"] = [{"pid": 999, "tid": 1, "error": "fabricado"}]
    with pytest.raises(ContractError):
        validate_process_tree_snapshot(tree, context="external_client.final_census.tree")


def test_error_windows_expuesto_solo_como_errno_se_clasifica_esperado() -> None:
    error = OSError(5, "OpenProcess(4) falló")
    assert getattr(error, "winerror", None) is None
    assert _classify_process_query_error(error) == (5, "protected_or_system")


@pytest.mark.skipif(sys.platform != "win32", reason="smoke de sensores Windows")
def test_censo_real_windows_tolera_procesos_protegidos() -> None:
    snapshot = system_process_resource_snapshot(excluded_pids={os.getpid()})
    coverage = snapshot["coverage"]
    assert coverage["enumerated_process_count"] == (
        coverage["observed_process_count"] + coverage["query_error_count"]
    )
    assert coverage["expected_query_error_count"] == len(snapshot["query_errors"])
    assert coverage["unexpected_query_error_count"] == 0
    assert coverage["snapshot_complete"] is True


def test_actividad_host_ordinaria_se_instrumenta_sin_contaminar() -> None:
    records = [
        _sample(0, host_cpu_100ns=100, host_private=4096),
        _sample(1, host_cpu_100ns=10_100, host_private=8192),
        _sample(2, host_cpu_100ns=20_100, host_private=12_288),
    ]
    assert _derive(records) == (None, None)
    summary = summarize_telemetry_records(
        records,
        baseline_roots=_roots(),
        baseline_volume_free_bytes=8 * GIB,
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    assert summary["guard_classification"] is None


def test_guard_autodeclarada_no_puede_reescribir_sensores() -> None:
    records = [_sample(0), _sample(1)]
    records[-1]["guard_classification"] = "safety_abort_disk"
    records[-1]["guard_reason"] = "declaración fabricada"
    with pytest.raises(ContractError, match="no deriva"):
        summarize_telemetry_records(
            records,
            baseline_roots=_roots(),
            baseline_volume_free_bytes=8 * GIB,
            expected_affinity_mask=15,
            expected_processor_group=0,
        )


@pytest.mark.parametrize(
    ("supported", "current"),
    ((True, None), (False, 512)),
)
def test_job_memory_usage_information_exige_bicondicional(
    supported: bool, current: int | None
) -> None:
    records = [_sample(0)]
    records[0]["job"]["memory_usage_information_supported"] = supported
    records[0]["job"]["current_job_memory_commit_bytes"] = current
    with pytest.raises(ContractError, match=r"current_job_memory|unsupported"):
        _derive(records)


def test_job_memory_usage_information_unsupported_cierra_evidencia() -> None:
    records = [_sample(0)]
    records[0]["job"]["memory_usage_information_supported"] = False
    records[0]["job"]["current_job_memory_commit_bytes"] = None
    assert _derive(records) == (
        "evidence_incomplete",
        "JobMemoryUsageInformation no está soportado para el Job candidato",
    )


@pytest.mark.parametrize(
    "mutation",
    ("missing_creation", "zero_creation", "tid_reuse", "affinity_count"),
)
def test_identidad_tid_exige_creation_y_rechaza_reuso_o_afinidad_spoof(
    mutation: str,
) -> None:
    records = [_sample(0)]
    thread = records[0]["tree"]["threads"][0]
    if mutation == "missing_creation":
        del thread["creation_time_100ns"]
    elif mutation == "zero_creation":
        thread["creation_time_100ns"] = 0
    elif mutation == "tid_reuse":
        records[0]["tree"]["threads"].append(
            {**thread, "creation_time_100ns": thread["creation_time_100ns"] + 1}
        )
    else:
        thread["logical_cpu_count_effective"] = 3
    with pytest.raises(ContractError, match=r"TID|identidad/afinidad"):
        _derive(records)


def test_cpu_externa_material_exige_dos_muestras_causales(tmp_path: Path) -> None:
    samples: list[dict[str, Any] | BaseException] = [
        _sample(0, host_cpu_100ns=0),
        _sample(1, host_cpu_100ns=2_500_000),
        _sample(2, host_cpu_100ns=5_000_000),
    ]
    sampler = TelemetrySampler(
        sensor=SequenceSensor(samples),
        sidecar_path=tmp_path / "resources.jsonl",
        baseline_roots=_roots(),
        baseline_volume_free=8 * GIB,
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    try:
        sampler.sample_once()
        sampler.sample_once()
        assert sampler.guard_classification is None
        sampler.sample_once()
        assert sampler.guard_classification == "host_contamination"
        assert "CPU externa" in str(sampler.guard_reason)
    finally:
        sampler.stop()


def test_error_protegido_esperado_se_persiste_sin_invalidar_cobertura() -> None:
    records = [_sample(0)]
    host = records[0]["external_processes"]["host_processes"]
    records[0]["external_processes"]["host_processes"]["query_errors"] = [
        {
            "pid": 99,
            "image_name": "System",
            "category": "protected_or_system",
            "winerror": 5,
            "error": "access denied",
        }
    ]
    host["coverage"] = {
        "enumerated_process_count": 2,
        "observed_process_count": 1,
        "query_error_count": 1,
        "expected_query_error_count": 1,
        "unexpected_query_error_count": 0,
        "snapshot_complete": True,
    }
    assert _derive(records) == (None, None)


def test_error_de_consulta_host_inesperado_cierra_como_evidencia_incompleta() -> None:
    records = [_sample(0)]
    host = records[0]["external_processes"]["host_processes"]
    host["query_errors"] = [
        {
            "pid": 99,
            "image_name": "unknown.exe",
            "category": "unexpected_query_failure",
            "winerror": 123,
            "error": "unexpected",
        }
    ]
    host["coverage"] = {
        "enumerated_process_count": 2,
        "observed_process_count": 1,
        "query_error_count": 1,
        "expected_query_error_count": 0,
        "unexpected_query_error_count": 1,
        "snapshot_complete": False,
    }
    classification, reason = _derive(records)
    assert classification == "evidence_incomplete"
    assert "inesperados" in str(reason)


def test_pid_previamente_medido_que_deja_de_ser_consultable_cierra() -> None:
    records = [_sample(0), _sample(1)]
    host = records[1]["external_processes"]["host_processes"]
    host["processes"] = []
    host["query_errors"] = [
        {
            "pid": 9001,
            "image_name": "external.exe",
            "category": "process_exited",
            "winerror": 1168,
            "error": "process exited",
        }
    ]
    host["coverage"] = {
        "enumerated_process_count": 1,
        "observed_process_count": 0,
        "query_error_count": 1,
        "expected_query_error_count": 1,
        "unexpected_query_error_count": 0,
        "snapshot_complete": True,
    }
    assert _derive(records)[0] == "evidence_incomplete"


def test_cpu_global_material_no_atribuida_contamina_en_dos_intervalos() -> None:
    records = [_sample(0), _sample(1), _sample(2)]
    for ordinal, record in enumerate(records):
        record["system_cpu"]["user_100ns"] = ordinal * 2_500_000
        record["external_processes"]["host_processes"]["processes"][0]["cpu_user_100ns"] = 0
    classification, reason = _derive(records)
    assert classification == "host_contamination"
    assert "no atribuida" in str(reason)


def test_commit_global_material_no_atribuido_contamina_en_dos_intervalos() -> None:
    records = [_sample(0), _sample(1), _sample(2)]
    for ordinal, record in enumerate(records):
        record["system_memory"]["commit_used_bytes"] = 4 * GIB + ordinal * 128 * 1024**2
        record["system_memory"]["commit_available_bytes"] = (
            record["system_memory"]["commit_limit_bytes"]
            - record["system_memory"]["commit_used_bytes"]
        )
    classification, reason = _derive(records)
    assert classification == "host_contamination"
    assert "commit global" in str(reason)


def test_caida_de_commit_no_se_atribuye_a_delta_externo_irrelevante() -> None:
    low_commit = 512 * 1024 * 1024
    records = [
        _sample(0, host_private=1024, commit=4 * GIB),
        _sample(1, host_private=1025, commit=low_commit),
        _sample(2, host_private=1026, commit=low_commit),
    ]
    classification, reason = _derive(records)
    assert classification == "safety_abort_system_memory"
    assert "dos muestras" in str(reason)


def test_write_bytes_globales_no_atribuyen_perdida_a_un_volumen() -> None:
    loss = 32 * 1024 * 1024
    records = [
        _sample(0, host_write=100),
        _sample(1, host_write=100 + loss, volume_free=8 * GIB - loss),
    ]
    assert _derive(records) == (
        "evidence_incomplete",
        "pérdida material del volumen no pudo atribuirse a las raíces; "
        "los bytes I/O globales por PID no acreditan volumen o path",
    )

    unproven = copy.deepcopy(records)
    unproven[1]["external_processes"]["host_processes"]["processes"][0]["io"]["write_bytes"] = 100
    assert _derive(unproven)[0] == "evidence_incomplete"


def test_falla_sensor_posterior_queda_en_sidecar_y_se_rederiva(tmp_path: Path) -> None:
    sampler = TelemetrySampler(
        sensor=SequenceSensor([_sample(0), RuntimeError("sensor roto")]),
        sidecar_path=tmp_path / "sensor-error.jsonl",
        interval_seconds=0.01,
        max_gap_seconds=0.1,
        baseline_roots=_roots(),
        baseline_volume_free=8 * GIB,
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    sampler.sample_once()
    sampler.start()
    time.sleep(0.05)
    result = sampler.stop()
    assert result["sidecar"]["records"] == 2
    assert result["summary"]["guard_classification"] == "evidence_incomplete"
    assert result["summary"]["guard_reason"] == "sensor falló: RuntimeError: sensor roto"


def test_timeout_de_primera_lectura_persiste_terminal_causal_sin_inventar_muestra(
    tmp_path: Path,
) -> None:
    release = threading.Event()

    class BlockingSensor:
        def sample(self) -> dict[str, Any]:
            release.wait()
            return _sample(0)

    sampler = TelemetrySampler(
        sensor=BlockingSensor(),
        sidecar_path=tmp_path / "sensor-timeout.jsonl",
        interval_seconds=0.01,
        max_gap_seconds=0.03,
        baseline_roots=_roots(),
        baseline_volume_free=8 * GIB,
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    try:
        sampler.start()
        assert sampler.wait_guard(0.2) is True
        result = sampler.stop(timeout_seconds=0.2)
    finally:
        release.set()
    records = verify_jsonl_sidecar(result["sidecar"])
    assert len(records) == 1
    assert records[0]["record_type"] == "sensor_failure"
    assert records[0]["failure"]["kind"] == "timeout"
    assert result["summary"]["records"] == 0
    assert result["summary"]["guard_classification"] == "evidence_incomplete"
