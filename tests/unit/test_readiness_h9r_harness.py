from __future__ import annotations

import base64
import copy
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from scripts.measure_readiness_h9r import (
    DOCUMENT_PATHS,
    ROOT,
    _dispatch_cli,
    _verify_safe_harness_dependencies,
)
from scripts.readiness_h9r import supervisor as supervisor_module
from scripts.readiness_h9r.adapters import (
    validate_adapter_descriptor,
    validate_adapter_request,
)
from scripts.readiness_h9r.artifacts import (
    AtomicOutputPublisher,
    JsonlRecorder,
    allocated_size,
    atomic_write_json_exclusive,
    canonical_tree_identity,
    census_roots,
    disk_footprint_summary,
    validate_census_against_filesystem,
    validate_output_manifest,
    verify_jsonl_sidecar,
)
from scripts.readiness_h9r.consumer import (
    ConsumerBoundary,
    ConsumerPublisher,
    reconstruct_consumer_sidecars,
)
from scripts.readiness_h9r.contracts import (
    ATTEMPT_TOP_LEVEL_OBJECTS,
    AUTHORIZATION_SCHEMA_VERSION,
    CAPS,
    CONFIG_SCHEMA_VERSION,
    GIB,
    MIB,
    PROTOCOL_VERSION,
    SCHEDULE_SCHEMA_VERSION,
    ContractError,
    _validate_material_lease_census,
    attempt_id,
    authority_signing_bytes,
    authorization_consumption_path_digest,
    authorization_statement,
    canonical_json_bytes,
    canonical_json_sha256,
    read_json_object,
    sha256_bytes,
    sha256_file,
    trusted_authority_key_identity,
    validate_preflight_rejection_evidence,
)
from scripts.readiness_h9r.material_lease import (
    LeaseAcquisitionError,
    MaterialLease,
)
from scripts.readiness_h9r.selftest import run_harness_self_test
from scripts.readiness_h9r.supervisor import (
    CANDIDATE_ENVIRONMENT_SCHEMA_VERSION,
    CANDIDATE_SCHEMA_VERSION,
    FIXTURE_CATALOG_SCHEMA_VERSION,
    FIXTURE_COLUMNS_SCHEMA_VERSION,
    FIXTURE_SCHEMA_VERSION,
    Handshake,
    _build_adapter_descriptor,
    _build_adapter_request,
    _classify_windows_oom_exit,
    _consume_authorization,
    _consume_authorization_before_start,
    _ensure_regular_sidecar_exists,
    _expected_start_identity,
    _golden_output_relative_path,
    _launch_external_client_assigned_suspended,
    _normalize_termination_trigger,
    _pre_start_classification,
    _PreStartAbortError,
    _probe_candidate_runtime,
    _publish_post_start_failure,
    _quarantine_final_manifest,
    _quarantine_unexpected_pre_start_token,
    _raise_pre_start_guard_if_needed,
    _reconcile_emergency_durable_state,
    _replace_json_write_through,
    _reserve_authorization_consumption,
    _resume_suspended_before_deadline,
    _revalidate_preflight,
    _run_candidate_probe_in_job,
    _source_identity,
    _validate_authorization_consumption_path,
    _validate_harness_driver,
    _validate_source_revision,
    _wait_for_pre_start_telemetry_sample,
    _wait_json,
    consume_launch_capability,
    run_authorized_attempt,
    run_preflight,
    run_worker,
    tooling_identity,
    validate_candidate_manifest,
    validate_external_workdir,
    validate_harness_config,
    write_preflight_rejection_evidence,
)
from scripts.readiness_h9r.telemetry import POOL_ENVIRONMENT_KEYS, SequenceSensor, TelemetrySampler
from scripts.readiness_h9r.windows_job import (
    WindowsJob,
    current_process_affinity,
    first_cpu_mask,
    resume_suspended_process,
    system_memory_status,
)
from scripts.readiness_h9r.windows_sandbox import LOW_INTEGRITY_SID

TEST_ONEDRIVE_ROOT = Path(os.environ.get("ONEDRIVE") or ROOT)


def _digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def test_sampler_bloqueado_congela_sidecar_antes_de_retornar(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockedSensor:
        def sample(self) -> dict[str, Any]:
            entered.set()
            release.wait(2.0)
            return {}

    path = tmp_path / "blocked-resources.jsonl"
    sampler = TelemetrySampler(
        sensor=BlockedSensor(),
        sidecar_path=path,
        interval_seconds=0.01,
        max_gap_seconds=0.1,
    )
    sampler.start()
    assert entered.wait(1.0)
    assert sampler.wait_guard(0.5)
    result = sampler.stop(timeout_seconds=0.01)
    assert result["summary"]["guard_classification"] == "evidence_incomplete"
    records = verify_jsonl_sidecar(result["sidecar"])
    assert records[-1]["record_type"] == "sensor_failure"
    assert records[-1]["failure"]["message"].startswith("sensor bloqueado")
    frozen = path.read_bytes()
    # La lectura subyacente sigue bloqueada, pero el writer ya terminó y el artefacto es estático.
    time.sleep(0.05)
    assert path.read_bytes() == frozen
    release.set()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _file_entry(path: Path, root: Path) -> dict[str, object]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _fixture_entry(
    path: Path,
    root: Path,
    *,
    file_format: str = "binary",
    rows: int | None = 1,
    expanded_rows: int | None = None,
) -> dict[str, object]:
    assigned, _, _ = allocated_size(path)
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "format": file_format,
        "rows": rows,
        "expanded_rows": expanded_rows,
        "logical_bytes": path.stat().st_size,
        "allocated_bytes": assigned,
        "sha256": sha256_file(path),
    }


def _preflight_material(tmp_path: Path, *, cap_id: str = "C4") -> dict[str, Any]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True)
    candidate_artifacts = artifacts / "candidate"
    fixture_artifacts = artifacts / "fixture"
    control_artifacts = artifacts / "control"
    for root in (candidate_artifacts, fixture_artifacts, control_artifacts):
        root.mkdir()
    wheel = candidate_artifacts / "candidate.whl"
    sdist = candidate_artifacts / "candidate.tar.gz"
    lock = candidate_artifacts / "uv.lock"
    generator = fixture_artifacts / "fixture-generator.py"
    input_root = fixture_artifacts / "inputs"
    bundle_root = fixture_artifacts / "bundle"
    runtime_root = candidate_artifacts / "runtime"
    installed_root = runtime_root / "installed"
    for root in (input_root, bundle_root, installed_root):
        root.mkdir(parents=True)
    input_path = input_root / "input.bin"
    bundle = bundle_root / "bundle.bin"
    installed_file = installed_root / "nikodym-test-only.txt"
    adapter = installed_root / "h9r-adapter.py"
    dist_info = installed_root / "nikodym-test.dist-info"
    dist_info.mkdir()
    metadata = dist_info / "METADATA"
    record = dist_info / "RECORD"
    for path, payload in (
        (wheel, b"wheel-harness-test-only"),
        (sdist, b"sdist-harness-test-only"),
        (lock, b"lock-harness-test-only"),
        (adapter, b"raise SystemExit('adapter de test no debe ejecutarse')\n"),
        (generator, b"raise SystemExit('generador de test no debe ejecutarse')\n"),
        (input_path, b"input-harness-test-only"),
        (bundle, b"bundle-harness-test-only"),
        (installed_file, b"installed-harness-test-only"),
        (metadata, b"Metadata-Version: 2.1\nName: nikodym\nVersion: 0.test-only\n\n"),
        (record, b"nikodym-test-only.txt,,\r\n"),
    ):
        path.write_bytes(payload)

    python_executable = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    # El manifiesto vive en artifacts; el runtime candidato usa el intérprete base, distinto del
    # redirector del venv confiable. La copia no se ejecuta en estos controles pre-START.
    runtime_python = runtime_root / "python.exe"
    shutil.copyfile(python_executable, runtime_python)
    source_sha = "a" * 40
    tree_identity = canonical_tree_identity(installed_root, include_entries=True)
    environment_path = runtime_root / "environment.json"
    environment = {
        "schema_version": CANDIDATE_ENVIRONMENT_SCHEMA_VERSION,
        "distribution": "nikodym",
        "source_sha": source_sha,
        "python_executable_relative_path": runtime_python.relative_to(
            candidate_artifacts
        ).as_posix(),
        "python_executable_sha256": sha256_file(runtime_python),
        "installed_tree_relative_path": installed_root.relative_to(candidate_artifacts).as_posix(),
        "installed_tree_sha256": tree_identity["sha256"],
    }
    _write_json(environment_path, environment)
    provenance = {
        "probe_schema_version": "nikodym.readiness.h9r.runtime-provenance.v1",
        "isolation_flags": ["-I", "-B", "-S"],
        "no_site": True,
        "distribution": "nikodym",
        "version": "0.test-only",
        "distribution_root": str(installed_root.resolve()),
        "dist_info_path": str((installed_root / "nikodym-test.dist-info").resolve()),
        "metadata_sha256": sha256_file(metadata),
        "record_sha256": sha256_file(record),
        "record_entries": 1,
        "imported_package_path": str(installed_file.resolve()),
        "imported_package_sha256": sha256_file(installed_file),
        "installed_tree_sha256": tree_identity["sha256"],
        "wheel_sha256": sha256_file(wheel),
        "lock_sha256": sha256_file(lock),
        "probe_payload_sha256": _digest("probe-test-only"),
    }
    candidate = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "source_sha": source_sha,
        "wheel": _file_entry(wheel, candidate_artifacts),
        "sdist": _file_entry(sdist, candidate_artifacts),
        "lock": _file_entry(lock, candidate_artifacts),
        "runtime": {
            "python_executable": _file_entry(runtime_python, candidate_artifacts),
            "environment": _file_entry(environment_path, candidate_artifacts),
            "installed_tree": {
                "relative_path": installed_root.relative_to(candidate_artifacts).as_posix(),
                **tree_identity,
            },
            "provenance": provenance,
        },
    }
    candidate_path = candidate_artifacts / "candidate.json"
    _write_json(candidate_path, candidate)

    config = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "geometry_id": "G-",
        "consumer": {
            "adapter_id": "nikodym.h9r.score_train.train.v1",
            "entrypoint": {
                "kind": "candidate_installed_script",
                "relative_path": adapter.relative_to(installed_root).as_posix(),
                "sha256": sha256_file(adapter),
            },
            "arguments": [
                "${BROKERED_INPUTS_JSON}",
                "${STAGING_ROOT}",
                "${ADAPTER_RESULT}",
            ],
            "expected_output_identities": ["bundle", "rules", "hashes", "lineage"],
        },
        "external_client": None,
        "flow_config": {"mode": "harness-test-only"},
    }
    config_path = fixture_artifacts / "config.json"
    _write_json(config_path, config)

    fixture_schema_path = fixture_artifacts / "fixture-schema.json"
    _write_json(
        fixture_schema_path,
        {
            "schema_version": FIXTURE_COLUMNS_SCHEMA_VERSION,
            "columns": [{"name": "test_value", "dtype": "bytes", "role": "control"}],
        },
    )
    catalog_path = fixture_artifacts / "fixture-catalog.json"
    _write_json(
        catalog_path,
        {
            "schema_version": FIXTURE_CATALOG_SCHEMA_VERSION,
            "special_values": [],
            "missing_values": [],
            "categories": [],
            "scenarios": [],
            "segments": [],
            "assumptions": ["harness-test-only"],
        },
    )
    golden_path = fixture_artifacts / "golden.json"
    golden_material = []
    for ordinal, identity in enumerate(("bundle", "rules", "hashes", "lineage")):
        output_sha256 = _digest(f"golden-output-{identity}")
        golden_material.append(
            {
                "relative_path": f"{identity}.json",
                "identity": identity,
                "ordinal": ordinal,
                "format": "json",
                "record_count": 1,
                "logical_bytes": 2,
                "sha256": output_sha256,
                "count_evidence": {
                    "mode": "derived",
                    "counter_id": "json-array-items.v1",
                    "records": 1,
                    "output_sha256": output_sha256,
                    "sidecar": None,
                },
            }
        )
    golden_path.write_bytes(canonical_json_bytes(golden_material))
    sub_seed_digest = sha256_bytes(b"h9r-cal-v1\0F-SCORE-TRAIN\0G-")
    fixture = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "geometry_id": "G-",
        "fixture_schema": _fixture_entry(
            fixture_schema_path, fixture_artifacts, file_format="json", rows=1
        ),
        "config": _fixture_entry(config_path, fixture_artifacts, file_format="json", rows=1),
        "config_hash": canonical_json_sha256(config),
        "root_seed": 20240706,
        "sub_seed": int(sub_seed_digest[:16], 16),
        "sub_seed_sha256": sub_seed_digest,
        "generator": {
            "artifact": _fixture_entry(generator, fixture_artifacts, file_format="python", rows=1),
            "source_commit": "b" * 40,
        },
        "dimensions": {"rows": 100_000, "variables": 50, "max_cardinality": 10_000},
        "geometry_source": {
            "primary_input_relative_path": input_path.relative_to(fixture_artifacts).as_posix(),
            "primary_input_sha256": sha256_file(input_path),
        },
        "inputs_root": input_root.relative_to(fixture_artifacts).as_posix(),
        "inputs": [_fixture_entry(input_path, fixture_artifacts)],
        "bundle_root": bundle_root.relative_to(fixture_artifacts).as_posix(),
        "bundle": _fixture_entry(bundle, fixture_artifacts),
        "catalog": _fixture_entry(catalog_path, fixture_artifacts, file_format="json", rows=1),
        "expected": {
            "identities": ["bundle", "rules", "hashes", "lineage"],
            "counts": {"bundle": 1, "rules": 1, "hashes": 1, "lineage": 1},
            "golden": _fixture_entry(golden_path, fixture_artifacts, file_format="json", rows=1),
        },
        "contains_customer_data": False,
        "demo_fixture": False,
    }
    fixture_path = fixture_artifacts / "fixture.json"
    _write_json(fixture_path, fixture)
    unit = {
        "candidate_manifest_sha256": canonical_json_sha256(candidate),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": canonical_json_sha256(fixture),
        "config_hash": canonical_json_sha256(config),
        "geometry_id": "G-",
        "cap_id": cap_id,
        "attempt_ordinal": 1,
    }
    cell = {key: value for key, value in unit.items() if key != "attempt_ordinal"}
    units = [{**cell, "attempt_ordinal": ordinal} for ordinal in range(1, 4)]
    seed_ordinal = 0
    while True:
        seed = _digest(f"test-permutation-{seed_ordinal}")
        units.sort(
            key=lambda candidate: (
                sha256_bytes(f"{seed}\0{attempt_id(candidate)}".encode("ascii")),
                attempt_id(candidate),
            )
        )
        if units[0] == unit:
            break
        seed_ordinal += 1
    schedule = {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "phase": "screening",
        "permutation_algorithm": "sha256-key-sort-v1",
        "permutation_seed_sha256": seed,
        "cells": [cell],
        "units": units,
    }
    schedule_path = control_artifacts / "schedule.json"
    _write_json(schedule_path, schedule)
    schedule_sha256 = canonical_json_sha256(schedule)
    # El runtime calificable y su snapshot de dependencias son exclusivos de Windows. Estos dos
    # consumidores portables del factory sólo necesitan ligar autoridad y documentos; los tests
    # de preflight Windows conservan la identidad viva completa.
    tooling = (
        tooling_identity(DOCUMENT_PATHS)
        if sys.platform == "win32"
        else {
            "manifest_sha256": _digest("portable-test-tooling"),
            "document_sha256": {
                name: sha256_file(path) for name, path in sorted(DOCUMENT_PATHS.items())
            },
        }
    )
    authorization_id = _digest("test-authorization-id")
    authorization_consumption_path = control_artifacts / "authorization-consumption.json"
    authorization_consumption_path_sha256 = authorization_consumption_path_digest(
        authorization_consumption_path
    )
    authorization_bytes = authorization_statement(
        unit,
        authorization_id=authorization_id,
        authorization_consumption_path_sha256=authorization_consumption_path_sha256,
        tooling_sha256=str(tooling["manifest_sha256"]),
        schedule_sha256=schedule_sha256,
        schedule_position=units.index(unit),
        scope="harness-test-only",
    )
    authorization_text = control_artifacts / "authorization.txt"
    authorization_text.write_bytes(authorization_bytes)
    authority = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "scope": "harness-test-only",
        "start_authorized": False,
        "authorization_id": authorization_id,
        "authorization_consumption_path_sha256": authorization_consumption_path_sha256,
        "authorized_unit": unit,
        "attempt_id": attempt_id(unit),
        "authorization_text_sha256": sha256_bytes(authorization_bytes),
        "document_sha256": tooling["document_sha256"],
        "tooling_sha256": tooling["manifest_sha256"],
        "schedule_sha256": schedule_sha256,
        "schedule_position": units.index(unit),
        "signer_public_key_sha256": "0" * 64,
        "signature_ed25519": "0" * 128,
    }
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key_path = control_artifacts / "authority-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    authority["signer_public_key_sha256"] = trusted_authority_key_identity(public_key_path)[1]
    authority["signature_ed25519"] = private_key.sign(authority_signing_bytes(authority)).hex()
    authority_path = control_artifacts / "authority.json"
    _write_json(authority_path, authority)
    prior_evidence_path = control_artifacts / "prior-evidence-paths.json"
    _write_json(prior_evidence_path, [])
    return {
        "unit": unit,
        "authority_path": authority_path,
        "authorization_text": authorization_text,
        "trusted_authority_public_key": public_key_path,
        "candidate_path": candidate_path,
        "fixture_path": fixture_path,
        "config_path": config_path,
        "schedule_path": schedule_path,
        "prior_evidence_paths": [],
        "workdir": tmp_path / "work",
        "evidence": tmp_path / "attempt.json",
        "provenance": provenance,
        "authority_private_key": private_key,
        "authorization_consumption_path": authorization_consumption_path,
        "tooling": tooling,
    }


def _run_test_preflight(
    material: dict[str, Any],
    *,
    reserve: bool = False,
    material_lease_out: list[MaterialLease] | None = None,
) -> Any:
    with patch(
        "scripts.readiness_h9r.supervisor._probe_candidate_runtime",
        return_value=material["provenance"],
    ):
        return run_preflight(
            unit=material["unit"],
            authority_path=material["authority_path"],
            authorization_text_path=material["authorization_text"],
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            candidate_manifest_path=material["candidate_path"],
            fixture_manifest_path=material["fixture_path"],
            config_path=material["config_path"],
            schedule_path=material["schedule_path"],
            prior_evidence_paths=material["prior_evidence_paths"],
            document_paths=DOCUMENT_PATHS,
            workdir=material["workdir"],
            evidence_path=material["evidence"],
            checkout_root=ROOT,
            onedrive_root=TEST_ONEDRIVE_ROOT,
            reserve_workdir=reserve,
            material_lease_out=material_lease_out,
        )


def _installed_tree_root(material: dict[str, Any]) -> Path:
    manifest = read_json_object(material["candidate_path"])
    runtime = cast(dict[str, Any], manifest["runtime"])
    relative = str(cast(dict[str, Any], runtime["installed_tree"])["relative_path"])
    return cast(Path, material["candidate_path"]).parent / Path(relative)


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
@pytest.mark.parametrize("cap_id", ("C4", "C5", "C6"))
def test_preflight_reconcilia_autoridad_caps_cpu_memoria_disco_sin_start(
    tmp_path: Path, cap_id: str
) -> None:
    material = _preflight_material(tmp_path, cap_id=cap_id)
    result = _run_test_preflight(material)
    assert result.attempt_id == attempt_id(material["unit"])
    assert result.requested_limits["job_memory_commit_limit_bytes"] == CAPS[cap_id]
    assert result.effective_limits["job_memory_commit_limit_bytes"] == CAPS[cap_id]
    assert result.effective_limits["logical_cpu_count"] == 4
    assert result.effective_limits["kill_on_job_close"] is True
    assert result.resource_guards["passed"] is True
    assert result.authority["start_authorized"] is False
    assert result.elapsed_seconds < 300
    assert not material["workdir"].exists()
    assert not material["evidence"].exists()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_preflight_rechaza_drift_y_attempt_no_puede_convertir_scope_test_en_start(
    tmp_path: Path,
) -> None:
    material = _preflight_material(tmp_path)
    original = material["authority_path"].read_bytes()
    authority = json.loads(original)
    authority["authorized_unit"]["attempt_ordinal"] = 2
    _write_json(material["authority_path"], authority)
    with pytest.raises(ContractError, match=r"firma Ed25519.*inválida"):
        _run_test_preflight(material, reserve=True)
    assert not material["workdir"].exists()
    material["authority_path"].write_bytes(original)
    assert material["authority_path"].read_bytes() == original
    with pytest.raises(ContractError, match="attempt exige autoridad START exacta"):
        _run_test_preflight(material, reserve=True)
    assert not material["workdir"].exists()
    assert not material["evidence"].exists()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_autoridad_invalida_falla_antes_de_probe_runtime(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    authority = json.loads(material["authority_path"].read_bytes())
    authority["signature_ed25519"] = "f" * 128
    _write_json(material["authority_path"], authority)
    with (
        patch("scripts.readiness_h9r.supervisor._probe_candidate_runtime") as probe,
        pytest.raises(ContractError, match=r"signature_ed25519|firma Ed25519"),
    ):
        run_preflight(
            unit=material["unit"],
            authority_path=material["authority_path"],
            authorization_text_path=material["authorization_text"],
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            candidate_manifest_path=material["candidate_path"],
            fixture_manifest_path=material["fixture_path"],
            config_path=material["config_path"],
            schedule_path=material["schedule_path"],
            prior_evidence_paths=material["prior_evidence_paths"],
            document_paths=DOCUMENT_PATHS,
            workdir=material["workdir"],
            evidence_path=material["evidence"],
            checkout_root=ROOT,
            onedrive_root=TEST_ONEDRIVE_ROOT,
            reserve_workdir=False,
        )
    probe.assert_not_called()


def test_validador_publico_candidato_es_pasivo(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    manifest = json.loads(material["candidate_path"].read_bytes())
    with patch("scripts.readiness_h9r.supervisor._probe_candidate_runtime") as probe:
        normalized = validate_candidate_manifest(
            manifest,
            expected_sha256=canonical_json_sha256(manifest),
            manifest_root=material["candidate_path"].parent,
        )
    probe.assert_not_called()
    assert normalized["manifest_sha256"] == canonical_json_sha256(manifest)


def test_manifiesto_normalizado_no_arrastra_entries_a_la_evidencia(tmp_path: Path) -> None:
    """El inventario queda validado en el archivo; el normalizado conserva la forma estable."""
    material = _preflight_material(tmp_path)
    manifest = json.loads(material["candidate_path"].read_bytes())
    assert "entries" in manifest["runtime"]["installed_tree"]
    normalized = validate_candidate_manifest(
        manifest,
        expected_sha256=canonical_json_sha256(manifest),
        manifest_root=material["candidate_path"].parent,
    )
    assert set(normalized["runtime"]["installed_tree"]) == {
        "relative_path",
        "files",
        "logical_bytes",
        "sha256",
        "path",
    }


def _validar_manifiesto_alterado(material: dict[str, Any], manifest: dict[str, Any]) -> None:
    validate_candidate_manifest(
        manifest,
        expected_sha256=canonical_json_sha256(manifest),
        manifest_root=material["candidate_path"].parent,
    )


def test_manifiesto_sin_inventario_por_entrada_se_rechaza(tmp_path: Path) -> None:
    """D-LEA-5: el manifiesto gana el inventario; sin él, el censo cerrado se pone rojo."""
    material = _preflight_material(tmp_path)
    manifest = json.loads(material["candidate_path"].read_bytes())
    del manifest["runtime"]["installed_tree"]["entries"]
    with pytest.raises(ContractError, match="installed_tree no tiene campos exactos"):
        _validar_manifiesto_alterado(material, manifest)


def test_inventario_del_manifiesto_debe_ligar_con_el_digest_agregado(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    manifest = json.loads(material["candidate_path"].read_bytes())
    manifest["runtime"]["installed_tree"]["entries"][0]["sha256"] = "1" * 64
    with pytest.raises(ContractError, match="no liga con el digest agregado"):
        _validar_manifiesto_alterado(material, manifest)


def test_inventario_del_manifiesto_fuera_de_orden_se_rechaza(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    manifest = json.loads(material["candidate_path"].read_bytes())
    entries = manifest["runtime"]["installed_tree"]["entries"]
    assert len(entries) >= 2, "el control exige al menos dos entradas"
    entries[0], entries[1] = entries[1], entries[0]
    with pytest.raises(ContractError, match="duplicado o fuera de orden"):
        _validar_manifiesto_alterado(material, manifest)


def test_inventario_del_manifiesto_debe_reconciliar_files_y_bytes(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    manifest = json.loads(material["candidate_path"].read_bytes())
    manifest["runtime"]["installed_tree"]["entries"][0]["bytes"] += 1
    with pytest.raises(ContractError, match="no reconcilia files/logical_bytes"):
        _validar_manifiesto_alterado(material, manifest)


@pytest.mark.parametrize("revision", ("A" * 40, "0" * 40, "f" * 64))
def test_revisiones_source_y_generator_rechazan_uppercase_y_placeholders(
    revision: str,
) -> None:
    with pytest.raises(ContractError, match=r"placeholder|canónico"):
        _validate_source_revision(revision, context="source revision")


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
@pytest.mark.parametrize("source_name", ("authority_path", "config_path"))
def test_preflight_rechaza_launch_source_symlink_antes_de_probe(
    tmp_path: Path, source_name: str
) -> None:
    material = _preflight_material(tmp_path)
    target = material[source_name]
    junction = tmp_path / f"{source_name}-junction"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target.parent)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:  # pragma: no cover - política Windows excepcional
        pytest.skip(f"host no permite junction de control: {created.stderr}")
    material[source_name] = junction / target.name
    with (
        patch("scripts.readiness_h9r.supervisor._probe_candidate_runtime") as probe,
        pytest.raises(ContractError, match="symlink/reparse"),
    ):
        _run_test_preflight(material)
    probe.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
@pytest.mark.parametrize("source_name", ("authority_path", "config_path"))
def test_preflight_rechaza_launch_source_hardlink_antes_de_probe(
    tmp_path: Path, source_name: str
) -> None:
    material = _preflight_material(tmp_path)
    target = material[source_name]
    alias = tmp_path / f"{source_name}-hardlink{target.suffix}"
    try:
        os.link(target, alias)
    except OSError as exc:  # pragma: no cover - filesystem CI sin hardlinks.
        pytest.skip(f"filesystem sin hardlinks: {exc}")
    material[source_name] = alias
    with (
        patch("scripts.readiness_h9r.supervisor._probe_candidate_runtime") as probe,
        pytest.raises(ContractError, match="hardlink"),
    ):
        _run_test_preflight(material)
    probe.assert_not_called()


def _promote_test_material_to_calibration(material: dict[str, Any]) -> str:
    unit = material["unit"]
    schedule = read_json_object(material["schedule_path"])
    tooling = tooling_identity(DOCUMENT_PATHS)
    schedule_sha256 = canonical_json_sha256(schedule)
    schedule_position = cast(list[dict[str, Any]], schedule["units"]).index(unit)
    authority = read_json_object(material["authority_path"])
    authorization_bytes = authorization_statement(
        unit,
        authorization_id=str(authority["authorization_id"]),
        authorization_consumption_path_sha256=str(
            authority["authorization_consumption_path_sha256"]
        ),
        tooling_sha256=str(tooling["manifest_sha256"]),
        schedule_sha256=schedule_sha256,
        schedule_position=schedule_position,
        scope="calibration-start",
    )
    material["authorization_text"].write_bytes(authorization_bytes)
    authority.update(
        {
            "scope": "calibration-start",
            "start_authorized": True,
            "authorization_text_sha256": sha256_bytes(authorization_bytes),
            "document_sha256": tooling["document_sha256"],
            "tooling_sha256": tooling["manifest_sha256"],
            "schedule_sha256": schedule_sha256,
            "schedule_position": schedule_position,
        }
    )
    authority["signature_ed25519"] = (
        material["authority_private_key"].sign(authority_signing_bytes(authority)).hex()
    )
    _write_json(material["authority_path"], authority)
    return cast(str, authority["signer_public_key_sha256"])


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_revalidate_detecta_replace_entre_captura_y_probe_sin_popen(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    with patch(
        "scripts.readiness_h9r.supervisor.tooling_identity",
        return_value=material["tooling"],
    ):
        preflight = _run_test_preflight(material)
    signer_sha256 = _promote_test_material_to_calibration(material)
    preflight.authority.clear()
    preflight.authority.update(read_json_object(material["authority_path"]))
    launch_paths = {
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
    refreshed = supervisor_module._capture_launch_sources(launch_paths)
    preflight.source_paths["capture_versions"] = {
        name: supervisor_module._launch_capture_version(capture)
        for name, capture in refreshed.items()
    }

    candidate_path = cast(Path, material["candidate_path"])
    original_payload = candidate_path.read_bytes()

    def tooling_then_replace(document_paths: Any, **kwargs: Any) -> dict[str, Any]:
        del document_paths, kwargs
        observed = copy.deepcopy(preflight.tooling)
        replacement = candidate_path.with_name("candidate-replacement.json")
        replacement.write_bytes(original_payload)
        os.replace(replacement, candidate_path)
        return observed

    with (
        patch.object(supervisor_module, "QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
        patch.object(supervisor_module, "CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE", True),
        patch.object(supervisor_module, "CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE", True),
        patch.object(supervisor_module, "MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE", True),
        patch.object(
            supervisor_module,
            "CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256",
            signer_sha256,
        ),
        patch(
            "scripts.readiness_h9r.contracts.CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256",
            signer_sha256,
        ),
        patch(
            "scripts.readiness_h9r.supervisor.tooling_identity",
            side_effect=tooling_then_replace,
        ),
        patch("scripts.readiness_h9r.supervisor._probe_candidate_runtime") as probe,
        patch("scripts.readiness_h9r.supervisor.subprocess.Popen") as popen,
        pytest.raises(ContractError, match=r"before_candidate_probe.*cambió de versión"),
    ):
        _revalidate_preflight(
            preflight,
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            active_candidate_probe=True,
        )
    probe.assert_not_called()
    popen.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_attempt_revalida_firma_externa_y_driver_antes_de_popen(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    preflight = _run_test_preflight(material)
    preflight.authority["scope"] = "calibration-start"
    preflight.authority["start_authorized"] = True
    with (
        patch.object(supervisor_module, "QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
        patch.object(supervisor_module, "CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE", True),
        patch.object(supervisor_module, "CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE", True),
        patch.object(
            supervisor_module,
            "MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE",
            True,
        ),
        patch(
            "scripts.readiness_h9r.contracts.CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256",
            preflight.authority["signer_public_key_sha256"],
        ),
        patch(
            "scripts.readiness_h9r.supervisor._probe_candidate_runtime",
            return_value=material["provenance"],
        ),
        patch("scripts.readiness_h9r.supervisor.subprocess.Popen") as popen,
        pytest.raises(ContractError, match=r"firma Ed25519 de autoridad inválida"),
    ):
        run_authorized_attempt(
            preflight=preflight,
            workdir=material["workdir"],
            evidence_path=material["workdir"] / "attempt.json",
            driver_path=ROOT / "scripts/measure_readiness_h9r.py",
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            authorization_consumption_path=material["authorization_consumption_path"],
        )
    popen.assert_not_called()

    arbitrary_driver = tmp_path / "arbitrary-driver.py"
    arbitrary_driver.write_text("raise SystemExit('no ejecutar')\n", encoding="utf-8")
    with pytest.raises(ContractError, match="driver_path"):
        _validate_harness_driver(preflight, arbitrary_driver)


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_preflight_congela_el_arbol_antes_de_todo_hash_y_hashea_por_handles(
    tmp_path: Path,
) -> None:
    material = _preflight_material(tmp_path)
    tree_calls: list[Path] = []
    real_tree_identity = supervisor_module.canonical_tree_identity

    def spy_tree_identity(root: Path, **kwargs: Any) -> dict[str, Any]:
        tree_calls.append(Path(root))
        return real_tree_identity(root, **kwargs)

    sink: list[MaterialLease] = []
    with patch(
        "scripts.readiness_h9r.supervisor.canonical_tree_identity",
        side_effect=spy_tree_identity,
    ):
        result = _run_test_preflight(material, material_lease_out=sink)
    assert len(sink) == 1
    lease = sink[0]
    try:
        installed_root = Path(
            str(cast(dict[str, Any], result.candidate["runtime"])["installed_tree"]["path"])
        )
        assert lease.released is False
        assert lease.root == installed_root
        # D-LEA-7: el árbol jamás se rehashea por ruta mientras el lease gobierna el preflight.
        assert all(call != installed_root for call in tree_calls)
        attestation = lease.attestation()
        assert attestation["mechanism"] == "windows_share_mode_lease_v1"
        assert attestation["files"] == 4
        assert attestation["first_hash_started_perf_ns"] is not None
        assert (
            attestation["acquisition_completed_perf_ns"]
            <= attestation["first_hash_started_perf_ns"]
        )
    finally:
        lease.release()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_preflight_retiene_el_lease_con_sink_y_lo_libera_verificado_sin_sink(
    tmp_path: Path,
) -> None:
    material = _preflight_material(tmp_path)
    leased_file = _installed_tree_root(material) / "nikodym-test-only.txt"
    _run_test_preflight(material)
    with leased_file.open("ab"):
        pass  # sin sink, run_preflight liberó el lease antes de retornar
    sink: list[MaterialLease] = []
    _run_test_preflight(material, material_lease_out=sink)
    lease = sink[0]
    try:
        with pytest.raises(PermissionError):
            leased_file.open("ab").close()
    finally:
        lease.release()
    assert lease.released is True
    with leased_file.open("ab"):
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_preflight_fail_closed_con_escritor_vivo_es_rechazo_tipado_sin_start(
    tmp_path: Path,
) -> None:
    material = _preflight_material(tmp_path)
    tree_root = _installed_tree_root(material)
    victim = tree_root / "nikodym-test-only.txt"
    sibling = tree_root / "h9r-adapter.py"
    unit_path = tmp_path / "unit.json"
    _write_json(unit_path, material["unit"])
    prior_path = tmp_path / "prior.json"
    _write_json(prior_path, [])
    evidence = tmp_path / "preflight-rejected.json"
    with victim.open("ab"):
        with pytest.raises(LeaseAcquisitionError, match=r"winerror=32") as excinfo:
            _run_test_preflight(material)
        assert isinstance(excinfo.value, ContractError)
        with sibling.open("ab"):
            pass  # el rollback no dejó handles vivos sobre el resto del conjunto
        rejection = write_preflight_rejection_evidence(
            unit_path=unit_path,
            authority_path=material["authority_path"],
            authorization_text_path=material["authorization_text"],
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            candidate_manifest_path=material["candidate_path"],
            fixture_manifest_path=material["fixture_path"],
            config_path=material["config_path"],
            schedule_path=material["schedule_path"],
            prior_evidence_paths_path=prior_path,
            document_paths=DOCUMENT_PATHS,
            workdir=material["workdir"],
            evidence_path=evidence,
            workdir_existed_before=False,
            reason=excinfo.value,
        )
    assert rejection["termination"]["classification"] == "preflight_rejected"
    assert rejection["termination"]["start_count"] == 0
    assert rejection["gates"] == {"no_start": True, "no_worker": True, "evidence_atomic": True}
    assert any("winerror=32" in reason for reason in rejection["reasons"])
    result = _run_test_preflight(material)
    assert result.resource_guards["passed"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_revalidate_conserva_el_mismo_lease_y_rechaza_liberado_o_ajeno(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    sink: list[MaterialLease] = []
    preflight = _run_test_preflight(material, material_lease_out=sink)
    lease = sink[0]
    try:
        _revalidate_preflight(
            preflight,
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            active_candidate_probe=False,
            material_lease=lease,
        )
        foreign_base = tmp_path / "ajeno"
        foreign_base.mkdir()
        foreign_material = _preflight_material(foreign_base)
        foreign_sink: list[MaterialLease] = []
        _run_test_preflight(foreign_material, material_lease_out=foreign_sink)
        foreign_lease = foreign_sink[0]
        try:
            with pytest.raises(ContractError, match="no cubre el árbol"):
                _revalidate_preflight(
                    preflight,
                    trusted_authority_public_key_path=material["trusted_authority_public_key"],
                    active_candidate_probe=False,
                    material_lease=foreign_lease,
                )
        finally:
            foreign_lease.release()
    finally:
        lease.release()
    with pytest.raises(ContractError, match="liberado antes de la quiescencia"):
        _revalidate_preflight(
            preflight,
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            active_candidate_probe=False,
            material_lease=lease,
        )


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_attempt_exige_lease_de_material_vivo_antes_de_popen(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    sink: list[MaterialLease] = []
    _run_test_preflight(material, material_lease_out=sink)
    released_lease = sink[0]
    released_lease.release()
    for stale_lease in (None, released_lease):
        with (
            patch.object(supervisor_module, "QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
            patch.object(supervisor_module, "CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE", True),
            patch.object(supervisor_module, "CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE", True),
            patch.object(supervisor_module, "MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE", True),
            patch("scripts.readiness_h9r.supervisor.subprocess.Popen") as popen,
            pytest.raises(ContractError, match="exige el lease de material vivo"),
        ):
            supervisor_module._run_authorized_attempt_inner(
                preflight=cast(Any, object()),
                workdir=tmp_path,
                evidence_path=tmp_path / "attempt.json",
                driver_path=ROOT / "scripts" / "measure_readiness_h9r.py",
                trusted_authority_public_key_path=tmp_path / "trusted-key.pem",
                authorization_consumption_path=tmp_path / "authorization-consumption.json",
                emergency_state={},
                material_lease=stale_lease,
            )
        popen.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_censo_del_lease_reconcilia_bidireccional_con_el_candidato(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    sink: list[MaterialLease] = []
    result = _run_test_preflight(material, material_lease_out=sink)
    lease = sink[0]
    lease.release()
    census = lease.attestation()
    candidate = cast(dict[str, Any], result.candidate)

    def censo_valido(
        payload: dict[str, Any],
        *,
        classification: str = "success",
        identity: dict[str, Any] | None = None,
    ) -> None:
        # Identidad sintética coherente con el reloj monotónico del censo (D-LEA-18).
        _validate_material_lease_census(
            payload,
            candidate=candidate,
            classification=classification,
            identity=identity
            if identity is not None
            else {
                "start_monotonic_ns": int(census["acquisition_started_monotonic_ns"]) + 1,
                "tree_empty_monotonic_ns": int(census["release_completed_monotonic_ns"]),
            },
        )

    censo_valido(census)
    with pytest.raises(ContractError, match="anterior a la quiescencia"):
        censo_valido(
            census,
            identity={
                "start_monotonic_ns": int(census["acquisition_started_monotonic_ns"]) + 1,
                "tree_empty_monotonic_ns": int(census["release_completed_monotonic_ns"]) + 1,
            },
        )
    with pytest.raises(ContractError, match="adquisición posterior a START"):
        censo_valido(
            census,
            identity={
                "start_monotonic_ns": int(census["acquisition_started_monotonic_ns"]) - 1,
                "tree_empty_monotonic_ns": int(census["release_completed_monotonic_ns"]),
            },
        )
    with pytest.raises(ContractError, match="exige quiescencia acreditada"):
        censo_valido(
            census,
            identity={
                "start_monotonic_ns": int(census["acquisition_started_monotonic_ns"]) + 1,
                "tree_empty_monotonic_ns": None,
            },
        )
    retenido = copy.deepcopy(census)
    retenido["released"] = False
    retenido["release_completed_perf_ns"] = None
    retenido["release_completed_monotonic_ns"] = None
    censo_valido(
        retenido,
        classification="orphan_detected",
        identity={"start_monotonic_ns": None, "tree_empty_monotonic_ns": None},
    )
    with pytest.raises(ContractError, match="sin liberación verificada"):
        censo_valido(retenido)
    sin_liberar = copy.deepcopy(census)
    sin_liberar["released"] = False
    with pytest.raises(ContractError, match="retenido con hito de liberación"):
        censo_valido(sin_liberar, classification="orphan_detected")
    otra_raiz = copy.deepcopy(census)
    otra_raiz["root"] = str(tmp_path)
    with pytest.raises(ContractError, match="no es el árbol instalado"):
        censo_valido(otra_raiz)
    desordenado = copy.deepcopy(census)
    desordenado["acquisition_completed_perf_ns"], desordenado["first_hash_started_perf_ns"] = (
        desordenado["first_hash_started_perf_ns"],
        desordenado["acquisition_completed_perf_ns"],
    )
    with pytest.raises(ContractError, match="fuera de orden"):
        censo_valido(desordenado)
    multivolumen = copy.deepcopy(census)
    multivolumen["entries"][1]["volume_serial"] += 1
    with pytest.raises(ContractError, match="multivolumen"):
        censo_valido(multivolumen)
    incompleto = copy.deepcopy(census)
    incompleto["entries"].pop()
    with pytest.raises(ContractError, match="entries no reconcilia"):
        censo_valido(incompleto)
    con_extra = copy.deepcopy(census)
    con_extra["extra"] = True
    with pytest.raises(ContractError, match="campos faltantes"):
        censo_valido(con_extra)
    bytes_inflados = copy.deepcopy(census)
    file_entry = next(entry for entry in bytes_inflados["entries"] if entry["kind"] == "file")
    file_entry["logical_bytes"] += 1
    with pytest.raises(ContractError, match="bytes lógicos no reconcilian"):
        censo_valido(bytes_inflados)
    ruta_ajena = copy.deepcopy(census)
    entrada_falsa = next(entry for entry in ruta_ajena["entries"] if entry["kind"] == "file")
    entrada_falsa["relative_path"] = "impostor-del-mismo-tamano.bin"
    with pytest.raises(ContractError, match="no liga con el digest"):
        censo_valido(ruta_ajena)


def test_evidencia_de_intento_exige_seccion_material_lease() -> None:
    incomplete = {
        "schema_version": supervisor_module.ATTEMPT_SCHEMA_VERSION,
        **{name: {} for name in ATTEMPT_TOP_LEVEL_OBJECTS if name != "material_lease"},
    }
    with pytest.raises(ContractError, match=r"faltantes=\['material_lease'\]"):
        supervisor_module.validate_attempt_evidence(incomplete)


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_preflight_rechaza_workdir_anidado_con_el_arbol_del_lease(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    material["workdir"] = _installed_tree_root(material) / "workdir-anidado"
    with pytest.raises(ContractError, match="no pueden anidarse"):
        _run_test_preflight(material)


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_cli_preflight_publica_censo_del_lease_y_rechaza_fail_closed(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    unit_path = tmp_path / "unit.json"
    _write_json(unit_path, material["unit"])
    prior_path = tmp_path / "prior.json"
    _write_json(prior_path, [])

    def cli_arguments(output: Path) -> list[str]:
        return [
            "preflight",
            "--unit",
            str(unit_path),
            "--authority",
            str(material["authority_path"]),
            "--trusted-authority-public-key",
            str(material["trusted_authority_public_key"]),
            "--authorization-text",
            str(material["authorization_text"]),
            "--candidate-manifest",
            str(material["candidate_path"]),
            "--fixture-manifest",
            str(material["fixture_path"]),
            "--config",
            str(material["config_path"]),
            "--schedule",
            str(material["schedule_path"]),
            "--prior-evidence-paths",
            str(prior_path),
            "--workdir",
            str(material["workdir"]),
            "--output",
            str(output),
        ]

    assert _dispatch_cli(cli_arguments(material["evidence"])) == 0
    payload = read_json_object(material["evidence"])
    census = cast(dict[str, Any], payload["material_lease"])
    assert census["released"] is True
    assert census["mechanism"] == "windows_share_mode_lease_v1"
    _validate_material_lease_census(
        census,
        candidate=cast(dict[str, Any], payload["candidate"]),
        classification="success",
        identity={
            "start_monotonic_ns": None,
            "tree_empty_monotonic_ns": int(census["release_completed_monotonic_ns"]),
        },
    )
    leased_file = _installed_tree_root(material) / "nikodym-test-only.txt"
    with leased_file.open("ab"):
        pass  # tras publicar la evidencia no queda ningún handle vivo
    rejection_output = tmp_path / "preflight-rejected.json"
    with leased_file.open("ab"):
        assert _dispatch_cli(cli_arguments(rejection_output)) == 2
    rejection = read_json_object(rejection_output)
    assert rejection["termination"]["classification"] == "preflight_rejected"
    assert rejection["termination"]["start_count"] == 0
    assert any("winerror=32" in reason for reason in rejection["reasons"])


def test_blocker_material_impide_swap_restore_antes_de_probe_popen(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate-python.exe"
    replacement = tmp_path / "candidate-python-replacement.exe"
    original_payload = b"candidate-approved"
    candidate.write_bytes(original_payload)
    replacement.write_bytes(b"candidate-not-approved")
    attack_executed = False

    def swap_execute_restore(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal attack_executed
        attack_executed = True
        parked = tmp_path / "candidate-python-approved.exe"
        os.replace(candidate, parked)
        os.replace(replacement, candidate)
        os.replace(candidate, replacement)
        os.replace(parked, candidate)
        raise AssertionError("el Popen bloqueado no puede ejecutar el ABA")

    with (
        patch.object(supervisor_module, "QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
        patch.object(supervisor_module, "TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE", True),
        patch.object(supervisor_module, "MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE", True),
        patch.object(supervisor_module, "CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE", True),
        patch.object(supervisor_module, "CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE", False),
        patch("scripts.readiness_h9r.supervisor.WindowsJob") as job,
        patch(
            "scripts.readiness_h9r.supervisor.subprocess.Popen",
            side_effect=swap_execute_restore,
        ) as popen,
        pytest.raises(ContractError, match="candidate_execution_material_lease_unimplemented"),
    ):
        _run_candidate_probe_in_job(
            [str(candidate), "-I", "-B", "-c", "pass"],
            timeout=1.0,
            memory_bytes=CAPS["C4"],
            affinity_mask=15,
            env={},
            capture_root=tmp_path,
        )
    assert attack_executed is False
    assert candidate.read_bytes() == original_payload
    job.assert_not_called()
    popen.assert_not_called()


def test_flags_antiguos_no_alcanzan_start_ni_popen_sin_fronteras_nuevas(
    tmp_path: Path,
) -> None:
    start_path = tmp_path / "telemetry" / "control" / "start.json"
    with (
        patch.object(supervisor_module, "QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
        patch.object(supervisor_module, "TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE", True),
        patch.object(supervisor_module, "MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.atomic_write_json_exclusive") as writer,
        patch("scripts.readiness_h9r.supervisor.subprocess.Popen") as popen,
        pytest.raises(
            ContractError,
            match=r"candidate_execution_material_lease_unimplemented",
        ),
    ):
        run_authorized_attempt(
            preflight=cast(Any, object()),
            workdir=tmp_path,
            evidence_path=tmp_path / "attempt.json",
            driver_path=ROOT / "scripts" / "measure_readiness_h9r.py",
            trusted_authority_public_key_path=tmp_path / "trusted-key.pem",
            authorization_consumption_path=tmp_path / "authorization-consumption.json",
        )
    assert not start_path.exists()
    writer.assert_not_called()
    popen.assert_not_called()


def test_workdir_debe_ser_nuevo_fuera_checkout_y_onedrive(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="dentro del checkout"):
        validate_external_workdir(ROOT / "forbidden", checkout_root=ROOT, onedrive_root=ROOT.parent)
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "leftover").write_text("x", encoding="utf-8")
    with pytest.raises(ContractError, match="vac"):
        validate_external_workdir(dirty, checkout_root=ROOT, onedrive_root=None)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ContractError, match="inexistente"):
        validate_external_workdir(empty, checkout_root=ROOT, onedrive_root=None)


@pytest.mark.parametrize(
    ("relative_path", "output_format"),
    [
        ("dir\\out.json", "json"),
        ("C:/out.json", "json"),
        ("../out.json", "json"),
        ("dir/out.csv", "json"),
    ],
)
def test_golden_rechaza_ruta_no_portable_o_suffix_incoherente(
    relative_path: str, output_format: str
) -> None:
    with pytest.raises(ContractError, match=r"relativa POSIX|no coincide"):
        _golden_output_relative_path(
            relative_path,
            output_format=output_format,
            context="test.golden.relative_path",
        )
    assert (
        str(
            _golden_output_relative_path(
                "dir/out.json", output_format="json", context="test.golden.relative_path"
            )
        )
        == "dir/out.json"
    )


def test_subcomandos_internos_cerrados_sin_fingerprint_humano(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIKODYM_H9R_ADAPTER_CAPABILITY", "1" * 64)
    with pytest.raises(ContractError, match="fingerprint humano durable"):
        consume_launch_capability(
            role="adapter",
            payload_sha256=_digest("request"),
            expected_commitment_sha256=_digest("commitment"),
        )


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_consumo_one_shot_reserva_exclusiva_y_receipt_durable(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    preflight = _run_test_preflight(material)
    receipt_path = material["authorization_consumption_path"]
    reservation = _reserve_authorization_consumption(
        preflight=preflight,
        path=receipt_path,
        workdir=material["workdir"],
    )
    with pytest.raises(ContractError, match="replay rechazado"):
        _reserve_authorization_consumption(
            preflight=preflight,
            path=receipt_path,
            workdir=material["workdir"],
        )
    consumption = _consume_authorization(reservation, preflight=preflight)
    assert consumption["state"] == "consumed"
    assert read_json_object(receipt_path)["state"] == "consumed"


@pytest.mark.skipif(sys.platform != "win32", reason="junction de receipt exige Windows")
def test_receipt_rechaza_ancestro_junction_antes_de_crear_o_reclamar(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = tmp_path / "receipt-junction"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:  # pragma: no cover - política Windows excepcional.
        pytest.skip(f"host sin junction: {created.stderr}")
    receipt = junction / "authorization-consumption.json"
    authority = {
        "authorization_consumption_path_sha256": authorization_consumption_path_digest(receipt)
    }
    with (
        patch("scripts.readiness_h9r.supervisor.atomic_write_json_exclusive") as publish,
        pytest.raises(ContractError, match="symlink/reparse"),
    ):
        _validate_authorization_consumption_path(
            receipt, authority=authority, workdir=tmp_path / "work"
        )
    publish.assert_not_called()
    assert not (outside / receipt.name).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_barreras_telemetria_y_deadline_dejan_receipt_reserved_y_start_ausente(
    tmp_path: Path,
) -> None:
    material = _preflight_material(tmp_path)
    preflight = _run_test_preflight(material)
    receipt_path = material["authorization_consumption_path"]
    reservation = _reserve_authorization_consumption(
        preflight=preflight,
        path=receipt_path,
        workdir=material["workdir"],
    )
    start_path = material["workdir"] / "telemetry" / "control" / "start.json"

    unsupported = MagicMock()
    unsupported.wait_first_sample.return_value = {
        "job": {
            "memory_usage_information_supported": False,
            "current_job_memory_commit_bytes": None,
        }
    }
    with pytest.raises(ContractError, match="JobMemoryUsageInformation"):
        _wait_for_pre_start_telemetry_sample(unsupported, preflight_deadline=time.monotonic() + 1.0)

    blocked = MagicMock()
    blocked.wait_first_sample.side_effect = TimeoutError("sensor bloqueado")
    with pytest.raises(TimeoutError, match="sensor bloqueado"):
        _wait_for_pre_start_telemetry_sample(blocked, preflight_deadline=time.monotonic() + 1.0)

    with (
        patch("scripts.readiness_h9r.supervisor.time.monotonic", return_value=10.0),
        patch("scripts.readiness_h9r.supervisor._consume_authorization") as consume,
        pytest.raises(ContractError, match="deadline pre-START"),
    ):
        _consume_authorization_before_start(
            reservation,
            preflight=preflight,
            preflight_deadline=10.0,
            emergency_state={},
        )
    consume.assert_not_called()
    assert read_json_object(receipt_path)["state"] == "reserved"
    assert not start_path.exists()


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (_PreStartAbortError("limits_not_applied", "limits"), "limits_not_applied"),
        (
            _PreStartAbortError("safety_abort_system_memory", "memory"),
            "safety_abort_system_memory",
        ),
        (_PreStartAbortError("safety_abort_disk", "disk"), "safety_abort_disk"),
        (_PreStartAbortError("orphan_detected", "tree"), "orphan_detected"),
        (TimeoutError("sensor timeout"), "watchdog_deadline"),
        (
            ContractError("workload_deadline_seconds inválido no es un timeout causal"),
            "invariant_failure",
        ),
        (RuntimeError("deadline textual no tipado"), "supervisor_error"),
    ),
)
def test_clasificacion_pre_start_deriva_tipo_y_no_substrings(
    error: BaseException, expected: str
) -> None:
    assert _pre_start_classification(error) == expected


@pytest.mark.parametrize(
    ("timed_out", "cancelled", "cleanup", "expected_final", "expected_trigger"),
    (
        (True, False, True, "watchdog_deadline", "watchdog_deadline"),
        (True, False, False, "orphan_detected", "watchdog_deadline"),
        (False, True, True, "cancelled", "cancelled"),
        (False, True, False, "orphan_detected", "cancelled"),
    ),
)
def test_trigger_timeout_cancel_se_conserva_ante_defecto_secundario(
    timed_out: bool,
    cancelled: bool,
    cleanup: bool,
    expected_final: str,
    expected_trigger: str,
) -> None:
    reasons: list[str] = []
    final, trigger, normalized_cancelled = _normalize_termination_trigger(
        "evidence_incomplete",
        timed_out=timed_out,
        cancelled=cancelled,
        cleanup_complete=cleanup,
        reasons=reasons,
    )
    assert final == expected_final
    assert trigger == expected_trigger
    assert normalized_cancelled is (cancelled and not timed_out)
    assert reasons


def test_guardas_pre_start_distinguen_memoria_disco_y_clasificacion_sampler(
    tmp_path: Path,
) -> None:
    clear = SimpleNamespace(guard_classification=None, guard_reason=None)
    with (
        patch("scripts.readiness_h9r.supervisor.volume_free_bytes", return_value=10**12),
        pytest.raises(_PreStartAbortError) as low_memory,
    ):
        _raise_pre_start_guard_if_needed(
            clear,
            memory_status={"physical_available_bytes": 0, "commit_available_bytes": 10**12},
            workdir=tmp_path,
            phase="test memory",
        )
    assert low_memory.value.classification == "safety_abort_system_memory"

    with (
        patch("scripts.readiness_h9r.supervisor.volume_free_bytes", return_value=0),
        pytest.raises(_PreStartAbortError) as low_disk,
    ):
        _raise_pre_start_guard_if_needed(
            clear,
            memory_status={
                "physical_available_bytes": 10**12,
                "commit_available_bytes": 10**12,
            },
            workdir=tmp_path,
            phase="test disk",
        )
    assert low_disk.value.classification == "safety_abort_disk"

    sampler = SimpleNamespace(guard_classification="limits_not_applied", guard_reason="fifth CPU")
    with pytest.raises(_PreStartAbortError) as observed:
        _raise_pre_start_guard_if_needed(
            sampler,
            memory_status={
                "physical_available_bytes": 10**12,
                "commit_available_bytes": 10**12,
            },
            workdir=tmp_path,
            phase="test sampler",
        )
    assert observed.value.classification == "limits_not_applied"


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_receipt_reconcilia_fallo_inyectado_despues_del_replace_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = _preflight_material(tmp_path)
    authority = read_json_object(material["authority_path"])
    preflight = SimpleNamespace(authority=authority, attempt_id=authority["attempt_id"])
    reservation = _reserve_authorization_consumption(
        preflight=preflight,
        path=material["authorization_consumption_path"],
        workdir=material["workdir"],
    )
    emergency_state: dict[str, Any] = {
        "authorization_reservation_snapshot": copy.deepcopy(reservation["reserved"])
    }

    def replace_then_fail(path: Path, value: dict[str, Any]) -> None:
        _replace_json_write_through(path, value)
        raise RuntimeError("fallo inyectado post-replace")

    monkeypatch.setattr(supervisor_module, "_replace_json_write_through", replace_then_fail)
    with pytest.raises(RuntimeError, match="post-replace"):
        _consume_authorization(
            reservation,
            preflight=preflight,
            emergency_state=emergency_state,
        )
    assert read_json_object(material["authorization_consumption_path"])["state"] == "consumed"
    _reconcile_emergency_durable_state(
        preflight=preflight,
        authorization_consumption_path=material["authorization_consumption_path"],
        start_path=material["workdir"] / "telemetry" / "control" / "start.json",
        emergency_state=emergency_state,
    )
    assert emergency_state["authorization_consumption_snapshot"]["state"] == "consumed"
    assert emergency_state["authorization_reservation_snapshot"]["state"] == "consumed"


@pytest.mark.skipif(sys.platform != "win32", reason="START calificable exige Windows")
def test_start_reconcilia_fallo_inyectado_despues_del_rename_durable(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    authority = read_json_object(material["authority_path"])
    preflight = SimpleNamespace(authority=authority, attempt_id=authority["attempt_id"])
    control = material["workdir"] / "telemetry" / "control"
    control.mkdir(parents=True, exist_ok=True)
    start_path = control / "start.json"
    start_value = {
        "protocol_version": PROTOCOL_VERSION,
        "authorization_text_sha256": preflight.authority["authorization_text_sha256"],
        "ready_monotonic_ns": 1,
        "start_monotonic_ns": 2,
        "attempt_id": preflight.attempt_id,
    }
    expected_start = _expected_start_identity(path=start_path, value=start_value)
    emergency_state: dict[str, Any] = {
        "start_published": False,
        "start_write_attempted": True,
        "start_expected_snapshot": expected_start,
    }

    def publish_then_fail() -> None:
        atomic_write_json_exclusive(start_path, start_value)
        raise RuntimeError("fallo inyectado post-rename")

    with pytest.raises(RuntimeError, match="post-rename"):
        publish_then_fail()
    _reconcile_emergency_durable_state(
        preflight=preflight,
        authorization_consumption_path=material["authorization_consumption_path"],
        start_path=start_path,
        emergency_state=emergency_state,
    )
    assert emergency_state["start_published"] is True
    assert emergency_state["start_snapshot"] == expected_start


@pytest.mark.skipif(sys.platform != "win32", reason="quarantine calificable exige Windows")
def test_start_ajeno_se_cuarentena_solo_sin_gate_ni_claims(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    authority = read_json_object(material["authority_path"])
    preflight = SimpleNamespace(authority=authority, attempt_id=authority["attempt_id"])
    workdir = material["workdir"]
    control = workdir / "telemetry" / "control"
    control.mkdir(parents=True, exist_ok=True)
    (workdir / "scratch").mkdir(exist_ok=True)
    start_path = control / "start.json"
    unexpected = b'{"forged":true}\n'
    start_path.write_bytes(unexpected)
    quarantine = _quarantine_unexpected_pre_start_token(
        preflight=preflight,
        workdir=workdir,
        authorization_consumption_path=material["authorization_consumption_path"],
        emergency_state={"process": object()},
    )
    assert quarantine is not None
    assert quarantine["worker_created"] is True
    assert not start_path.exists()
    quarantined = workdir / "scratch" / "invalid-pre-start-token.json"
    assert quarantined.read_bytes() == unexpected
    assert all(identity["present"] is False for identity in quarantine["role_claims"].values())


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_fallo_terminal_post_start_publica_emergency_sin_fabricar_attempt(
    tmp_path: Path,
) -> None:
    material = _preflight_material(tmp_path)
    preflight = _run_test_preflight(material)
    workdir = material["workdir"]
    control = workdir / "telemetry" / "control"
    control.mkdir(parents=True)
    (workdir / "scratch").mkdir()
    reservation = _reserve_authorization_consumption(
        preflight=preflight,
        path=material["authorization_consumption_path"],
        workdir=workdir,
    )
    emergency_state: dict[str, Any] = {
        "authority_snapshot": copy.deepcopy(preflight.authority),
        "effective_limits_snapshot": copy.deepcopy(preflight.effective_limits),
        "harness_runtime_snapshot_sha256": _digest("harness-runtime-snapshot"),
        "worker_tree_empty": True,
        "client_tree_empty": True,
    }
    _consume_authorization(reservation, preflight=preflight, emergency_state=emergency_state)
    start = {
        "protocol_version": PROTOCOL_VERSION,
        "authorization_text_sha256": preflight.authority["authorization_text_sha256"],
        "ready_monotonic_ns": 0,
        "start_monotonic_ns": 1,
        "attempt_id": preflight.attempt_id,
    }
    _write_json(control / "start.json", start)
    emergency_state["start_snapshot"] = _expected_start_identity(
        path=control / "start.json", value=start
    )
    emergency_state["start_published"] = True
    evidence_path = workdir / "attempt.json"
    emergency = _publish_post_start_failure(
        preflight=preflight,
        workdir=workdir,
        evidence_path=evidence_path,
        trusted_authority_public_key_path=material["trusted_authority_public_key"],
        authorization_consumption_path=material["authorization_consumption_path"],
        emergency_state=emergency_state,
        error=ContractError("fallo terminal controlado"),
    )
    assert emergency["schema_version"].endswith("post-start-failure.v1")
    assert emergency["result"] == {
        "classification": "evidence_incomplete",
        "statistically_eligible": False,
    }
    assert len(emergency["observed"]["sidecars"]) == 15
    original = evidence_path.read_bytes()
    with pytest.raises(ContractError, match="nunca lo sobrescribe"):
        _publish_post_start_failure(
            preflight=preflight,
            workdir=workdir,
            evidence_path=evidence_path,
            trusted_authority_public_key_path=material["trusted_authority_public_key"],
            authorization_consumption_path=material["authorization_consumption_path"],
            emergency_state={},
            error=RuntimeError("segundo fallo"),
        )
    assert evidence_path.read_bytes() == original


def test_rechazo_preflight_persiste_causa_y_no_borra_workdir_de_una_carrera(
    tmp_path: Path,
) -> None:
    material = _preflight_material(tmp_path)
    unit_path = tmp_path / "unit.json"
    _write_json(unit_path, material["unit"])
    prior_path = tmp_path / "prior.json"
    _write_json(prior_path, [])
    workdir = tmp_path / "reserved"
    (workdir / "scratch").mkdir(parents=True)
    sentinel = workdir / "scratch" / "ajeno.txt"
    sentinel.write_text("no borrar", encoding="utf-8")
    evidence = tmp_path / "preflight-rejected.json"
    payload = write_preflight_rejection_evidence(
        unit_path=unit_path,
        authority_path=material["authority_path"],
        authorization_text_path=material["authorization_text"],
        trusted_authority_public_key_path=material["trusted_authority_public_key"],
        candidate_manifest_path=material["candidate_path"],
        fixture_manifest_path=material["fixture_path"],
        config_path=material["config_path"],
        schedule_path=material["schedule_path"],
        prior_evidence_paths_path=prior_path,
        document_paths=DOCUMENT_PATHS,
        workdir=workdir,
        evidence_path=evidence,
        workdir_existed_before=False,
        reason=ContractError("control preflight rechazado"),
    )
    assert validate_preflight_rejection_evidence(payload) == payload
    assert payload["termination"] == {
        "classification": "preflight_rejected",
        "start_count": 0,
        "ready_count": 0,
        "worker_spawned": False,
        "cleanup_complete": True,
        "workdir_removed": False,
    }
    assert sentinel.read_text(encoding="utf-8") == "no borrar"
    assert evidence.is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_descriptor_y_request_cerrados_se_validan_antes_de_start(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    preflight = _run_test_preflight(material)
    descriptor = _build_adapter_descriptor(preflight)
    descriptor_path = tmp_path / "runtime" / "adapter-descriptor.json"
    _write_json(descriptor_path, descriptor)
    candidate_root = Path(preflight.candidate["runtime"]["installed_tree"]["path"])
    normalized_descriptor = validate_adapter_descriptor(
        descriptor,
        candidate_root=candidate_root,
        expected_flow_id=preflight.unit["flow_id"],
        expected_flow_step=preflight.unit["flow_step"],
        expected_bindings=descriptor["bindings"],
    )
    assert normalized_descriptor["implementation"]["kind"] == "candidate_brokered_script"
    request = _build_adapter_request(
        preflight,
        descriptor_identity={
            "path": str(descriptor_path.resolve()),
            "logical_bytes": descriptor_path.stat().st_size,
            "sha256": sha256_file(descriptor_path),
        },
        paths={
            "outputs": tmp_path / "attempt-runtime" / "outputs",
            "staging": tmp_path / "attempt-runtime" / "scratch" / "consumer-staging",
            "candidate_outputs": tmp_path
            / "attempt-runtime"
            / "scratch"
            / "consumer-staging"
            / "candidate-outputs.json",
            "adapter_result": tmp_path
            / "attempt-runtime"
            / "telemetry"
            / "control"
            / "adapter-result.json",
            "boundary": tmp_path / "attempt-runtime" / "telemetry" / "boundary.jsonl",
            "filesystem_events": tmp_path / "attempt-runtime" / "telemetry" / "filesystem.jsonl",
            "native_pools": tmp_path / "attempt-runtime" / "telemetry" / "native-pools.jsonl",
            "adapter_audit": tmp_path / "attempt-runtime" / "telemetry" / "adapter-audit.jsonl",
            "ui_first_byte": tmp_path / "attempt-runtime" / "telemetry" / "ui-first-byte.jsonl",
        },
        candidate_launch={},
    )
    with pytest.raises(ContractError, match="candidate_launch"):
        validate_adapter_request(request)
    assert request["candidate_launch"] == {}
    assert "candidate_command" not in request
    assert "OUTPUT_ROOT" not in canonical_json_bytes(descriptor).decode("utf-8")
    assert not material["workdir"].exists()


@pytest.mark.skipif(sys.platform != "win32", reason="preflight calificable exige Windows")
def test_config_cerrado_rechaza_modulo_comando_y_output_root(tmp_path: Path) -> None:
    material = _preflight_material(tmp_path)
    preflight = _run_test_preflight(material)
    raw_config = json.loads(material["config_path"].read_bytes())
    candidate_root = Path(preflight.candidate["runtime"]["installed_tree"]["path"])
    as_module = copy.deepcopy(raw_config)
    as_module["consumer"]["entrypoint"] = {
        "kind": "candidate_python_module",
        "module": "nikodym.arbitrario",
    }
    with pytest.raises(ContractError, match="candidate_installed_script"):
        validate_harness_config(
            as_module,
            config_root=material["config_path"].parent,
            candidate_root=candidate_root,
            unit=material["unit"],
            fixture=preflight.fixture,
        )
    with_output_root = copy.deepcopy(raw_config)
    with_output_root["consumer"]["arguments"].append("${OUTPUT_ROOT}")
    with pytest.raises(ContractError, match="placeholder no permitido"):
        validate_harness_config(
            with_output_root,
            config_root=material["config_path"].parent,
            candidate_root=candidate_root,
            unit=material["unit"],
            fixture=preflight.fixture,
        )


def test_probe_runtime_liga_wheel_lock_record_e_import_aislado(tmp_path: Path) -> None:
    tree = tmp_path / "installed"
    package = tree / "nikodym"
    dist_info = tree / "nikodym-9.9.9.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    imported = package / "__init__.py"
    imported.write_bytes(b"__version__ = '9.9.9'\n")
    metadata_bytes = b"Metadata-Version: 2.1\nName: nikodym\nVersion: 9.9.9\n\n"
    metadata = dist_info / "METADATA"
    metadata.write_bytes(metadata_bytes)
    imported_sha = sha256_file(imported)
    imported_b64 = base64.urlsafe_b64encode(bytes.fromhex(imported_sha)).decode().rstrip("=")
    record_bytes = (
        f"nikodym/__init__.py,sha256={imported_b64},{imported.stat().st_size}\r\n"
        "nikodym-9.9.9.dist-info/METADATA,,\r\n"
        "nikodym-9.9.9.dist-info/RECORD,,\r\n"
    ).encode()
    record = dist_info / "RECORD"
    record.write_bytes(record_bytes)
    wheel = tmp_path / "nikodym-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("nikodym/__init__.py", imported.read_bytes())
        archive.writestr("nikodym-9.9.9.dist-info/METADATA", metadata_bytes)
        archive.writestr("nikodym-9.9.9.dist-info/RECORD", record_bytes)
    lock = tmp_path / "uv.lock"
    lock.write_text(
        "[[package]]\n"
        "name = 'nikodym'\n"
        "version = '9.9.9'\n"
        f"wheels = [{{ url = 'file:///nikodym.whl', hash = 'sha256:{sha256_file(wheel)}' }}]\n",
        encoding="ascii",
    )
    probe = {
        "distribution": "nikodym",
        "version": "9.9.9",
        "distribution_root": str(tree.resolve()),
        "dist_info_path": str(dist_info.resolve()),
        "metadata_path": str(metadata.resolve()),
        "metadata_sha256": sha256_file(metadata),
        "record_path": str(record.resolve()),
        "record_sha256": sha256_file(record),
        "record_rows": [
            ["nikodym/__init__.py", f"sha256={imported_b64}", str(imported.stat().st_size)],
            ["nikodym-9.9.9.dist-info/METADATA", "", ""],
            ["nikodym-9.9.9.dist-info/RECORD", "", ""],
        ],
        "imported_package_path": str(imported.resolve()),
        "imported_package_sha256": imported_sha,
        "no_site": True,
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(probe), stderr=""
    )
    with (
        patch("scripts.readiness_h9r.supervisor.require_calibration_start_implementation_ready"),
        patch(
            "scripts.readiness_h9r.supervisor._run_candidate_probe_in_job",
            return_value=completed,
        ),
    ):
        provenance = _probe_candidate_runtime(
            python_executable=Path(sys.executable),
            installed_tree_root=tree,
            wheel_path=wheel,
            lock_path=lock,
            installed_tree_sha256=str(canonical_tree_identity(tree)["sha256"]),
            memory_bytes=CAPS["C4"],
            affinity_mask=15,
            deadline_monotonic=None,
        )
        assert provenance["record_entries"] == 3
        assert provenance["wheel_sha256"] == sha256_file(wheel)
        lock.write_text(
            "[[package]]\nname = 'nikodym'\nversion = '9.9.9'\nwheels = []\n",
            encoding="utf-8",
        )
        with pytest.raises(ContractError, match="lock no contiene"):
            _probe_candidate_runtime(
                python_executable=Path(sys.executable),
                installed_tree_root=tree,
                wheel_path=wheel,
                lock_path=lock,
                installed_tree_sha256=str(canonical_tree_identity(tree)["sha256"]),
                memory_bytes=CAPS["C4"],
                affinity_mask=15,
                deadline_monotonic=None,
            )


def test_probe_autorizado_nace_suspendido_se_asigna_y_reanuda_en_orden(tmp_path: Path) -> None:
    events: list[str] = []
    process = MagicMock()
    process.pid = 321
    process.wait.side_effect = lambda **_kwargs: events.append("wait") or 0
    process.close.side_effect = lambda: events.append("close")
    job = MagicMock()
    job.api = object()
    job.__enter__.return_value = job
    job.__exit__.return_value = None
    job.assign.side_effect = lambda _pid: events.append("assign")
    job.wait_empty.side_effect = lambda _timeout: events.append("empty") or True

    def fake_launch(*_args: Any, **kwargs: Any) -> Any:
        # El probe escribe por handles ya abiertos por el arnés, nunca por rutas propias.
        assert kwargs["stdout_fd"] >= 0 and kwargs["stderr_fd"] >= 0
        (tmp_path / "probe.stdout.bin").write_bytes(b"{}")
        events.append("launch_suspended")
        return process

    with (
        patch("scripts.readiness_h9r.supervisor.require_calibration_start_implementation_ready"),
        patch("scripts.readiness_h9r.supervisor.WindowsJob", return_value=job),
        patch("scripts.readiness_h9r.supervisor.low_integrity_primary_token") as token,
        patch(
            "scripts.readiness_h9r.supervisor.launch_suspended_low_integrity",
            side_effect=fake_launch,
        ),
        patch(
            "scripts.readiness_h9r.supervisor.process_integrity_level",
            return_value=LOW_INTEGRITY_SID,
        ),
        patch(
            "scripts.readiness_h9r.supervisor.resume_suspended_process",
            side_effect=lambda _pid, _api: events.append("resume") or [1],
        ),
    ):
        token.return_value.__enter__.return_value = 1234
        completed = _run_candidate_probe_in_job(
            ["candidate-python", "-I", "-B", "-c", "pass"],
            timeout=1.0,
            memory_bytes=CAPS["C4"],
            affinity_mask=15,
            env={},
            capture_root=tmp_path,
        )
    assert completed.returncode == 0
    assert completed.stdout == "{}"
    assert events == ["launch_suspended", "assign", "resume", "wait", "close", "empty"]


def test_deadline_vencido_no_crea_probe_ni_reanuda_worker_o_cliente() -> None:
    with (
        patch("scripts.readiness_h9r.supervisor.require_calibration_start_implementation_ready"),
        patch("scripts.readiness_h9r.supervisor.launch_suspended_low_integrity") as popen,
        pytest.raises(ContractError, match="antes de crear el proceso"),
    ):
        _probe_candidate_runtime(
            python_executable=Path(sys.executable),
            installed_tree_root=Path.cwd(),
            wheel_path=Path.cwd() / "unused.whl",
            lock_path=Path.cwd() / "unused.lock",
            installed_tree_sha256=_digest("unused-tree"),
            memory_bytes=CAPS["C4"],
            affinity_mask=15,
            deadline_monotonic=time.monotonic() - 1.0,
        )
    popen.assert_not_called()

    with (
        patch("scripts.readiness_h9r.supervisor.resume_suspended_process") as resume,
        pytest.raises(ContractError, match="deadline vencido"),
    ):
        _resume_suspended_before_deadline(
            123,
            object(),
            deadline=time.monotonic() - 1.0,
            context="antes de reanudar el worker",
        )
    resume.assert_not_called()

    with (
        patch("scripts.readiness_h9r.supervisor.resume_suspended_process") as resume,
        pytest.raises(ContractError, match="deadline vencido"),
    ):
        _resume_suspended_before_deadline(
            456,
            object(),
            deadline=time.monotonic() - 1.0,
            context="antes de reanudar el cliente UI",
        )
    resume.assert_not_called()


def test_cliente_ui_efimero_se_censa_antes_de_reanudar(tmp_path: Path) -> None:
    events: list[str] = []
    process = MagicMock()
    process.pid = 654
    job = MagicMock()
    job.assign.side_effect = lambda _pid: events.append("assign")
    job.accounting.side_effect = lambda: events.append("accounting") or {"active_processes": 1}
    job.census.side_effect = lambda: (
        events.append("census")
        or {"tree": {"processes": [{"pid": 654, "creation_time_100ns": 123}]}}
    )

    def fake_popen(*_args: Any, **kwargs: Any) -> Any:
        assert kwargs["creationflags"] == 0x00000004
        events.append("launch_suspended")
        return process

    with patch("scripts.readiness_h9r.supervisor.subprocess.Popen", side_effect=fake_popen):
        observed, accounting, census = _launch_external_client_assigned_suspended(
            job=job,
            command=["ui-client"],
            workdir=tmp_path,
            environment={},
            stdout_handle=subprocess.DEVNULL,
            stderr_handle=subprocess.DEVNULL,
        )
    assert observed is process
    assert accounting["active_processes"] == 1
    assert census["tree"]["processes"][0]["creation_time_100ns"] == 123
    assert events == ["launch_suspended", "assign", "accounting", "census"]


def test_exit_oom_sin_evidencia_kernel_no_se_clasifica_host_oom() -> None:
    observed = _classify_windows_oom_exit(
        0xC0000017,
        job_memory_limit_violated=False,
        system_oom_evidence=False,
    )
    assert observed is not None
    assert observed[0] == "evidence_incomplete"
    assert (
        _classify_windows_oom_exit(
            0xC0000017,
            job_memory_limit_violated=False,
            system_oom_evidence=True,
        )[0]
        == "host_oom"
    )


def test_censo_final_entra_al_footprint_y_quarantine_no_pierde_metadata(
    tmp_path: Path,
) -> None:
    baseline = {
        name: {"logical_bytes": 0, "allocated_bytes": 0}
        for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
    }
    final = copy.deepcopy(baseline)
    final["outputs"] = {"logical_bytes": 100, "allocated_bytes": 4096}
    footprint = disk_footprint_summary(baseline, [final])
    assert footprint["peak_incremental_allocated_bytes"] == 4096

    output_root = tmp_path / "outputs"
    scratch = tmp_path / "scratch"
    output_root.mkdir()
    scratch.mkdir()
    manifest = output_root / "manifest.json"
    manifest.write_bytes(b"{}")
    metadata = _quarantine_final_manifest(output_root, scratch)
    assert metadata is not None
    assert metadata["sha256"] == sha256_bytes(b"{}")
    assert _quarantine_final_manifest(output_root, scratch) is None


def test_sidecars_consumidor_se_reabren_y_evento_falso_no_pasa(tmp_path: Path) -> None:
    boundary_path = tmp_path / "boundary.jsonl"
    filesystem_path = tmp_path / "filesystem.jsonl"
    boundary = ConsumerBoundary(boundary_path, filesystem_path)
    input_path = tmp_path / "input.bin"
    input_path.write_bytes(b"x")
    input_identity = {
        "role": "input",
        "relative_name": "input.bin",
        "logical_bytes": 1,
        "sha256": sha256_file(input_path),
    }
    boundary.first_open(
        [{"logical_id": canonical_json_sha256(input_identity), **input_identity}],
        request_id=_digest("consumer-open"),
        broker_request_sha256=_digest("broker-request"),
        nonce_commitment_sha256=_digest("broker-nonce"),
        candidate_process={"pid": 1, "creation_time_100ns": 1},
    )
    publisher = ConsumerPublisher(tmp_path / "outputs", boundary)
    source = tmp_path / "source.json"
    source.write_bytes(b"[1]")
    publisher.publish_file("result.json", "result", 0, source)
    published = publisher.finalize()["manifest"]
    boundary_metadata = {
        "name": "boundary",
        "path": str(boundary_path),
        "format": "jsonl",
        "records": len(boundary_path.read_text(encoding="utf-8").splitlines()),
        "bytes": boundary_path.stat().st_size,
        "sha256": sha256_file(boundary_path),
    }
    filesystem_metadata = {
        "name": "filesystem",
        "path": str(filesystem_path),
        "format": "jsonl",
        "records": len(filesystem_path.read_text(encoding="utf-8").splitlines()),
        "bytes": filesystem_path.stat().st_size,
        "sha256": sha256_file(filesystem_path),
    }
    reconstructed = reconstruct_consumer_sidecars(
        boundary_metadata=boundary_metadata,
        filesystem_metadata=filesystem_metadata,
        output_root=tmp_path / "outputs",
        manifest=published,
        require_complete=True,
    )
    assert [event["event"] for event in reconstructed["boundary_events"]] == [
        "first_open_or_byte",
        "flush_complete",
        "hash_complete",
        "rename_complete",
    ]
    original = boundary_path.read_bytes()
    boundary_path.write_bytes(original + b'{"event":"false","monotonic_ns":999}\n')
    tampered = {
        **boundary_metadata,
        "bytes": boundary_path.stat().st_size,
        "sha256": sha256_file(boundary_path),
        "records": boundary_metadata["records"] + 1,
    }
    with pytest.raises(ContractError, match="boundary consumidor fuera"):
        reconstruct_consumer_sidecars(
            boundary_metadata=tampered,
            filesystem_metadata=filesystem_metadata,
            output_root=tmp_path / "outputs",
            manifest=published,
            require_complete=True,
        )


def test_handshake_no_emite_start_sin_ready_limites_y_autoridad_exacta() -> None:
    authority_hash = _digest("authority")
    handshake = Handshake(
        expected_authority_text_sha256=authority_hash,
        expected_affinity_mask=15,
        expected_memory_bytes=CAPS["C4"],
        expected_processor_group=0,
    )
    with pytest.raises(ContractError, match="START antes de READY"):
        handshake.start(authorization_text_sha256=authority_hash)
    handshake.boot(pid=123)
    bad_limits = {
        "logical_cpu_count": 5,
        "affinity_mask": 31,
        "job_memory_commit_limit_bytes": CAPS["C4"],
        "processor_group": 0,
        "group_affinities": [{"processor_group": 0, "affinity_mask": 31}],
        "kill_on_job_close": True,
        "affinity_enforced": True,
        "job_memory_enforced": True,
    }
    with pytest.raises(ContractError, match="CPU efectiva"):
        handshake.limits_applied(bad_limits)
    good_limits = {
        **bad_limits,
        "logical_cpu_count": 4,
        "affinity_mask": 15,
        "group_affinities": [{"processor_group": 0, "affinity_mask": 15}],
    }
    handshake.limits_applied(good_limits)
    handshake.ready()
    with pytest.raises(ContractError, match="autoridad START no coincide"):
        handshake.start(authorization_text_sha256=_digest("other"))
    token = handshake.start(authorization_text_sha256=authority_hash)
    assert token["protocol_version"] == PROTOCOL_VERSION
    assert [event["event"] for event in handshake.events] == [
        "boot",
        "limits_applied",
        "ready",
        "start",
    ]


def test_atomicidad_manifest_ultimo_falta_alta_orden_chunks_y_restauracion(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("a.jsonl", "A", 0, b'{"row":1}\n')
    publisher.publish("b.jsonl", "B", 1, b'{"row":1}\n{"row":2}\n')
    assert not (output_root / "manifest.json").exists()
    finalized = publisher.finalize()
    kwargs = {
        "expected_identities": ["A", "B"],
        "expected_counts": {"A": 1, "B": 2},
        "expected_golden_sha256": finalized["manifest"]["golden_observed_sha256"],
    }
    assert validate_output_manifest(output_root, **kwargs)["schema_version"].endswith("outputs.v1")
    with pytest.raises(ContractError, match="identidades/orden"):
        validate_output_manifest(output_root, **{**kwargs, "expected_identities": ["B", "A"]})
    manifest_path = output_root / "manifest.json"
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    manifest["artifacts"][0]["chunks"].append(copy.deepcopy(manifest["artifacts"][0]["chunks"][0]))
    _write_json(manifest_path, manifest)
    with pytest.raises(ContractError, match="chunks"):
        validate_output_manifest(output_root, **kwargs)
    manifest_path.write_bytes(original)
    assert manifest_path.read_bytes() == original
    assert validate_output_manifest(output_root, **kwargs)["artifacts"][1]["record_count"] == 2
    (output_root / "extra.jsonl").write_bytes(b'{"extra":true}\n')
    with pytest.raises(ContractError, match="completitud bidireccional"):
        validate_output_manifest(output_root, **kwargs)


def test_interrupcion_del_publicador_limpia_parcial_y_no_deja_manifest(tmp_path: Path) -> None:
    events: list[tuple[str, Path]] = []

    def interrupt(operation: str, path: Path) -> None:
        events.append((operation, path))
        if operation == "flush":
            raise RuntimeError("crash controlado pre-rename")

    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root, event_callback=interrupt)
    with pytest.raises(RuntimeError, match="pre-rename"):
        publisher.publish("result.jsonl", "result", 0, b'{"partial":true}\n')
    assert [operation for operation, _ in events] == ["create", "flush", "delete"]
    assert not (output_root / "manifest.json").exists()
    assert not list(output_root.rglob("*.partial"))


def test_sidecar_reconcilia_hash_cardinalidad_y_detecta_alteracion(tmp_path: Path) -> None:
    recorder = JsonlRecorder(tmp_path / "samples.jsonl")
    recorder.append({"sample_ordinal": 0})
    recorder.append({"sample_ordinal": 1})
    metadata = recorder.finalize()
    assert [row["sample_ordinal"] for row in verify_jsonl_sidecar(metadata)] == [0, 1]
    original = (tmp_path / "samples.jsonl").read_bytes()
    (tmp_path / "samples.jsonl").write_bytes(b'{"sample_ordinal":0}\n')
    with pytest.raises(ContractError, match=r"bytes del sidecar|SHA-256"):
        verify_jsonl_sidecar(metadata)
    (tmp_path / "samples.jsonl").write_bytes(original)
    assert (tmp_path / "samples.jsonl").read_bytes() == original
    assert len(verify_jsonl_sidecar(metadata)) == 2


def test_identidad_terminal_rechaza_hardlink_mutable_fuera_del_attempt(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar.jsonl"
    alias = tmp_path / "alias.jsonl"
    sidecar.write_bytes(b'{"sample":0}\n')
    try:
        os.link(sidecar, alias)
    except OSError as exc:  # pragma: no cover - filesystem CI sin hardlinks.
        pytest.skip(f"filesystem sin hardlinks: {exc}")
    observed = _source_identity(sidecar, require_single_link=True)
    assert observed["safe_regular_file"] is False
    assert observed["rejection"] == "multiple_hardlinks"
    alias.unlink()
    assert _source_identity(sidecar, require_single_link=True)["safe_regular_file"] is True


def test_worker_y_handshake_rechazan_control_hardlink_antes_de_claim(tmp_path: Path) -> None:
    control = tmp_path / "worker-request.json"
    control.write_bytes(canonical_json_bytes({}) + b"\n")
    alias = tmp_path / "worker-request-alias.json"
    try:
        os.link(control, alias)
    except OSError as exc:  # pragma: no cover - filesystem CI sin hardlinks.
        pytest.skip(f"filesystem sin hardlinks: {exc}")

    process = MagicMock()
    process.poll.return_value = None
    with pytest.raises(ContractError, match="hardlink"):
        _wait_json(alias, timeout_seconds=0.1, process=process)

    with (
        patch("scripts.readiness_h9r.supervisor.require_calibration_start_implementation_ready"),
        patch("scripts.readiness_h9r.supervisor.consume_launch_capability") as consume,
        pytest.raises(ContractError, match="hardlink"),
    ):
        run_worker(alias, _digest("worker-capability"))
    consume.assert_not_called()


def test_reposicion_sidecar_no_sigue_symlink_dangling(tmp_path: Path) -> None:
    outside = tmp_path / "outside-created.bin"
    sidecar = tmp_path / "resources.jsonl"
    try:
        os.symlink(outside, sidecar)
    except OSError:
        outside_root = tmp_path / "outside"
        outside_root.mkdir()
        junction = tmp_path / "telemetry-junction"
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:  # pragma: no cover - política Windows excepcional.
            pytest.skip(f"host sin symlink/junction: {created.stderr}")
        outside = outside_root / "resources.jsonl"
        sidecar = junction / "resources.jsonl"
    with pytest.raises(ContractError, match=r"sidecar existente inseguro|symlink/reparse"):
        _ensure_regular_sidecar_exists(sidecar, context="resources sidecar")
    assert not outside.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="allocation calificable exige Windows")
def test_disco_logico_asignado_y_temporales_en_censo(tmp_path: Path) -> None:
    roots = {
        name: tmp_path / name for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
    }
    for root in roots.values():
        root.mkdir()
    (roots["inputs"] / "input.bin").write_bytes(b"input")
    (roots["scratch"] / "temporary.bin").write_bytes(b"temporary")
    observed = census_roots(roots)
    assert validate_census_against_filesystem(observed, roots) == observed
    falsified = copy.deepcopy(observed)
    falsified["scratch"]["allocated_bytes"] = 0
    with pytest.raises(ContractError, match="no reconcilia"):
        validate_census_against_filesystem(falsified, roots)
    missing_root = dict(observed)
    missing_root.pop("telemetry")
    with pytest.raises(ContractError, match="incompletas"):
        validate_census_against_filesystem(missing_root, roots)
    sample = copy.deepcopy(observed)
    sample["outputs"]["allocated_bytes"] += 4096
    summary = disk_footprint_summary(observed, [observed, sample])
    assert summary["peak_incremental_allocated_bytes"] == 4096


def _sample(
    *,
    physical: int = 4 * GIB,
    commit: int = 4 * GIB,
    disk_free: int = 20 * GIB,
    cpu_count: int = 4,
    process_mask: int = 15,
    host_processes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    roots = {
        name: {
            "root": name,
            "logical_bytes": 0,
            "allocated_bytes": 0,
            "files": 0,
            "allocation_reliable": True,
            "allocation_sources": [],
        }
        for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
    }
    process_metric = {
        "pid": 1,
        "creation_time_100ns": 1,
        "cpu_user_100ns": 0,
        "cpu_kernel_100ns": 0,
        "page_fault_count": 0,
        "working_set_bytes": 20,
        "peak_working_set_bytes": 20,
        "pagefile_bytes": 0,
        "peak_pagefile_bytes": 0,
        "private_usage_bytes": 0,
        "logical_cpu_count_effective": cpu_count,
        "affinity_mask": process_mask,
        "system_affinity_mask": process_mask,
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
    supervisor_metric["pid"] = 2
    supervisor_metric["creation_time_100ns"] = 2
    supervisor_metric["working_set_bytes"] = 30
    supervisor_metric["peak_working_set_bytes"] = 30
    normalized_host_processes: list[dict[str, Any]] = []
    for raw_host_process in host_processes or []:
        raw_io = raw_host_process.get("io", {})
        normalized_host_processes.append(
            {
                "pid": raw_host_process["pid"],
                "creation_time_100ns": raw_host_process["creation_time_100ns"],
                "image_name": raw_host_process["image_name"],
                "cpu_user_100ns": raw_host_process["cpu_user_100ns"],
                "cpu_kernel_100ns": raw_host_process["cpu_kernel_100ns"],
                "private_usage_bytes": raw_host_process["private_usage_bytes"],
                "working_set_bytes": raw_host_process["working_set_bytes"],
                "io": {
                    "read_operations": raw_io.get("read_operations", 0),
                    "write_operations": raw_io.get("write_operations", 0),
                    "other_operations": raw_io.get("other_operations", 0),
                    "read_bytes": raw_io.get("read_bytes", 0),
                    "write_bytes": raw_io.get("write_bytes", 0),
                    "other_bytes": raw_io.get("other_bytes", 0),
                },
            }
        )
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
            "peak_process_memory_commit_bytes": 100,
            "peak_job_memory_commit_bytes": 100,
            "current_job_memory_commit_bytes": 50,
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
            "pids": [1],
            "processes": [process_metric],
            "threads": [
                {
                    "pid": 1,
                    "tid": 1,
                    "creation_time_100ns": 1,
                    "affinity_mask": process_mask if cpu_count <= 4 else 15,
                    "processor_group": 0,
                    "logical_cpu_count_effective": min(cpu_count, 4),
                }
            ],
            "process_query_errors": [],
            "thread_query_errors": [],
        },
        "system_memory": {
            "physical_total_bytes": 8 * GIB,
            "physical_available_bytes": physical,
            "commit_limit_bytes": 8 * GIB,
            "commit_available_bytes": commit,
            "commit_used_bytes": 8 * GIB - commit,
            "memory_load_percent": 50,
            "virtual_total_bytes": 16 * GIB,
            "virtual_available_bytes": 8 * GIB,
        },
        "system_cpu": {"user_100ns": 0, "kernel_100ns": 0, "idle_100ns": 0},
        "disk": {"volume_free_bytes": disk_free, "roots": roots},
        "external_processes": {
            "supervisor": supervisor_metric,
            "client": None,
            "client_job": None,
            "host_processes": {
                "processes": normalized_host_processes,
                "query_errors": [],
                "coverage": {
                    "enumerated_process_count": len(normalized_host_processes),
                    "observed_process_count": len(normalized_host_processes),
                    "query_error_count": 0,
                    "expected_query_error_count": 0,
                    "unexpected_query_error_count": 0,
                    "snapshot_complete": True,
                },
            },
        },
        "native_pools": {name: "4" for name in POOL_ENVIRONMENT_KEYS},
    }


def test_sampler_guardas_memoria_disco_cpu_y_evidencia(tmp_path: Path) -> None:
    low_memory = TelemetrySampler(
        sensor=SequenceSensor(
            [_sample(physical=GIB - 1, commit=GIB - 1), _sample(physical=GIB - 1, commit=GIB - 1)]
        ),
        sidecar_path=tmp_path / "memory.jsonl",
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    low_memory.sample_once()
    assert low_memory.guard_classification is None
    low_memory.sample_once()
    assert low_memory.guard_classification == "safety_abort_system_memory"
    low_memory.stop()
    low_disk = TelemetrySampler(
        sensor=SequenceSensor([_sample(disk_free=GIB - 1)]),
        sidecar_path=tmp_path / "disk.jsonl",
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    low_disk.sample_once()
    assert low_disk.guard_classification == "safety_abort_disk"
    low_disk.stop()
    fifth_cpu = TelemetrySampler(
        sensor=SequenceSensor([_sample(cpu_count=5, process_mask=31)]),
        sidecar_path=tmp_path / "cpu.jsonl",
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    fifth_cpu.sample_once()
    assert fifth_cpu.guard_classification == "limits_not_applied"
    fifth_cpu.stop()


def test_sampler_solo_declara_contaminacion_host_con_pid_creation_atribuible(
    tmp_path: Path,
) -> None:
    baseline_process = {
        "pid": 9001,
        "creation_time_100ns": 101,
        "image_name": "externo.exe",
        "cpu_user_100ns": 10,
        "cpu_kernel_100ns": 5,
        "private_usage_bytes": 4096,
        "working_set_bytes": 8192,
        "io": {"write_bytes": 0},
    }
    ordinary_drift = {
        **baseline_process,
        "cpu_user_100ns": 12,
        "private_usage_bytes": 8192,
    }
    material_drift = {
        **ordinary_drift,
        "io": {"write_bytes": 32 * MIB},
    }
    sampler = TelemetrySampler(
        sensor=SequenceSensor(
            [
                _sample(host_processes=[baseline_process]),
                _sample(host_processes=[ordinary_drift]),
                _sample(
                    disk_free=20 * GIB - 32 * MIB,
                    host_processes=[material_drift],
                ),
            ]
        ),
        sidecar_path=tmp_path / "host-contamination.jsonl",
        expected_affinity_mask=15,
        expected_processor_group=0,
    )
    try:
        first = sampler.sample_once()
        assert sampler.guard_classification is None
        assert first["host_attribution"]["proven_external"] is False
        ordinary = sampler.sample_once()
        assert sampler.guard_classification is None
        assert ordinary["host_attribution"]["proven_external"] is True
        material = sampler.sample_once()
        assert sampler.guard_classification == "evidence_incomplete"
        assert "volumen" in str(sampler.guard_reason)
        assert material["host_attribution"]["proven_processes"][0]["pid"] == 9001
        assert material["host_attribution"]["proven_processes"][0]["write_growth_bytes"] == 32 * MIB
    finally:
        sampler.stop()


def test_sampler_sensor_fallido_deja_evidence_incomplete_y_sidecar_verificable(
    tmp_path: Path,
) -> None:
    sampler = TelemetrySampler(
        sensor=SequenceSensor([RuntimeError("sensor roto")]),
        sidecar_path=tmp_path / "sensor-error.jsonl",
        interval_seconds=0.01,
        max_gap_seconds=0.1,
    )
    sampler.start()
    time.sleep(0.05)
    result = sampler.stop()
    assert sampler.guard_classification == "evidence_incomplete"
    records = verify_jsonl_sidecar(result["sidecar"])
    assert len(records) == 1
    assert records[0]["record_type"] == "sensor_failure"
    assert records[0]["guard_classification"] == "evidence_incomplete"
    assert records[0]["failure"]["error_type"] == "RuntimeError"


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object es exclusivo de Windows")
@pytest.mark.parametrize("cap_id", ("C4", "C5", "C6"))
def test_job_object_aplica_afinidad_y_cap_consultados_al_kernel(cap_id: str) -> None:
    mask = first_cpu_mask(current_process_affinity()["process_mask"])
    with WindowsJob(memory_bytes=CAPS[cap_id], affinity_mask=mask) as job:
        effective = job.effective_limits()
        assert effective["job_memory_commit_limit_bytes"] == CAPS[cap_id]
        assert effective["logical_cpu_count"] == 4
        assert effective["affinity_enforced"] is True
        assert effective["job_memory_enforced"] is True
        assert effective["kill_on_job_close"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object es exclusivo de Windows")
def test_hijo_suspendido_no_puede_ampliar_a_quinta_cpu() -> None:
    code = (
        "import json;from scripts.readiness_h9r.windows_job import "
        "current_process_affinity,try_expand_current_process_affinity;"
        "before=current_process_affinity();outside=before['system_mask']&~before['process_mask'];"
        "requested=before['process_mask']|((outside&-outside) if outside else 0);"
        "print(json.dumps({'before':before,'probe':try_expand_current_process_affinity(requested)}))"
    )
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        creationflags=0x4,
    )
    mask = first_cpu_mask(current_process_affinity()["process_mask"])
    with WindowsJob(memory_bytes=128 * MIB, affinity_mask=mask) as job:
        job.assign(process.pid)
        resume_suspended_process(process.pid, job.api)
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr.decode(errors="replace")
        payload = json.loads(stdout)
        assert payload["before"]["process_mask"] == mask
        host_has_fifth = bool(payload["before"]["system_mask"] & ~mask)
        if not host_has_fifth:
            pytest.skip("host sin quinta CPU fuera del set: defecto no ejercitable")
        assert payload["probe"]["effective_mask"] == mask
        assert payload["probe"]["effective_logical_cpu_count"] == 4
        assert job.wait_empty(5)


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object es exclusivo de Windows")
def test_virtualalloc_c_mas_un_byte_dispara_notificacion_kernel_sin_oom_host() -> None:
    cap = 96 * MIB
    code = f"""
import ctypes,json
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.VirtualAlloc.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint32,ctypes.c_uint32]
k.VirtualAlloc.restype=ctypes.c_void_p
p=k.VirtualAlloc(None,{cap + 1},0x3000,0x04)
print(json.dumps({{'allocated':bool(p),'last_error':ctypes.get_last_error()}}),flush=True)
raise SystemExit(91 if p else 86)
"""
    before = system_memory_status()
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x4,
    )
    mask = first_cpu_mask(current_process_affinity()["process_mask"])
    with WindowsJob(memory_bytes=cap, affinity_mask=mask) as job:
        job.assign(process.pid)
        resume_suspended_process(process.pid, job.api)
        stdout, stderr = process.communicate(timeout=20)
        assert not stderr
        assert json.loads(stdout)["allocated"] is False
        assert process.returncode == 86
        violation = job.memory_limit_violation()
        assert violation["job_memory_limit_violated"] is True
        assert violation["job_memory_limit_bytes"] == cap
        assert job.wait_empty(5)
    after = system_memory_status()
    assert min(before["physical_available_bytes"], after["physical_available_bytes"]) > GIB
    assert min(before["commit_available_bytes"], after["commit_available_bytes"]) > GIB


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object es exclusivo de Windows")
def test_deadline_externo_mantiene_watchdog_hasta_arbol_vacio(tmp_path: Path) -> None:
    sentinel = tmp_path / "late-sentinel"
    child = (
        "import time;from pathlib import Path;time.sleep(1.5);"
        f"Path({str(sentinel)!r}).write_text('orphan',encoding='utf-8')"
    )
    code = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
    )
    process = subprocess.Popen([sys.executable, "-c", code], creationflags=0x4)
    mask = first_cpu_mask(current_process_affinity()["process_mask"])
    with WindowsJob(memory_bytes=128 * MIB, affinity_mask=mask) as job:
        job.assign(process.pid)
        resume_suspended_process(process.pid, job.api)
        deadline = time.monotonic() + 0.2
        classification = None
        while int(job.accounting()["active_processes"]) > 0:
            if time.monotonic() >= deadline:
                classification = "watchdog_deadline"
                job.terminate(233)
            time.sleep(0.01)
        assert classification == "watchdog_deadline"
        assert job.wait_empty(5)
    process.wait(timeout=10)
    time.sleep(1.7)
    assert not sentinel.exists()


@pytest.mark.skipif(
    sys.platform != "win32" or sys.version_info[:2] != (3, 12),
    reason="selftest exige el runtime firmado Windows/CPython 3.12",
)
def test_artefacto_harness_test_declara_cero_start_y_controles(tmp_path: Path) -> None:
    output = tmp_path / "harness-test.json"
    artifact = run_harness_self_test(
        checkout_root=ROOT,
        output_path=output,
        harness_runtime=_verify_safe_harness_dependencies(activate=False),
    )
    assert artifact["start_authorized"] is False
    assert artifact["start_tokens_emitted"] == 0
    assert artifact["materialized_start_units"] == 0
    assert artifact["candidate_workloads_executed"] == 0
    assert artifact["definitive_calibration_fixtures_generated"] == 0
    assert set(artifact["kernel_cap_hypotheses"]) == {"C4", "C5", "C6"}
    expected_controls = [
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
        "candidate_output_os_isolation",
        "copy",
    ]
    assert artifact["control_matrix_order"] == expected_controls
    assert list(artifact["controls"]) == expected_controls
    isolation = artifact["controls"]["candidate_output_os_isolation"]["evidence"]
    assert isolation["mechanism"] == "windows_mandatory_integrity_low_v1"
    assert isolation["low_integrity_child_denied_output_root"] is True
    # Sin el control de vacuidad la denegación anterior no probaría nada: la misma operación
    # tiene que seguir siendo posible para un proceso de integridad media.
    assert isolation["medium_integrity_child_created_equivalent"] is True
    assert isolation["denial_probe_performed"] is True
    assert isolation["output_root_present"] is False
    for control in artifact["controls"].values():
        assert control["green_before"] is True
        assert control["red_observed"] is True
        assert control["red_cause"]
        assert control["restoration"]["byte_exact"] is True
        assert control["restoration"]["before_sha256"] == control["restoration"]["after_sha256"]
        assert control["green_after"] is True
    assert set(artifact["schemas"]) == {
        "attempt",
        "aggregate",
        "preflight-rejection",
        "pre-start-failure",
        "post-start-failure",
        "internal-authorization-precommit",
        "internal-authorization-gate",
        "internal-authorization-release",
    }
    module_paths = [item["relative_path"] for item in artifact["harness_modules"]["files"]]
    assert "scripts/__init__.py" in module_paths
    assert "scripts/measure_readiness_h9r.py" in module_paths
    assert "scripts/readiness_h9r/selftest.py" in module_paths
    assert artifact["harness_modules"]["count"] == len(module_paths)
    assert artifact["harness_runtime"]["bootstrap_mode"] == ("stdlib-record-verified-no-site-v1")
    assert [item["name"] for item in artifact["harness_runtime"]["distributions"]] == [
        "cryptography",
        "pypdf",
    ]
    assert artifact["temporary_cleanup_complete"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["start_tokens_emitted"] == 0
