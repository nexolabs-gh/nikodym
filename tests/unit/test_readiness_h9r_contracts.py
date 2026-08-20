from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.measure_readiness_h9r import ROOT, catalog_payload
from scripts.readiness_h9r.aggregate import validate_campaign_progress
from scripts.readiness_h9r.contracts import (
    AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
    AUTHORIZATION_SCHEMA_VERSION,
    CAPS,
    CLASSIFICATIONS,
    FLOW_SPECS,
    SCHEDULE_SCHEMA_VERSION,
    ContractError,
    attempt_id,
    authority_signing_bytes,
    authorization_consumption_path_digest,
    authorization_statement,
    canonical_json_bytes,
    canonical_json_sha256,
    evaluate_repetitions,
    robust_summary,
    sha256_bytes,
    trusted_authority_key_identity,
    validate_attempt_unit,
    validate_authority,
    validate_authorization_consumption,
    validate_boundary_events,
    validate_schedule,
)
from scripts.readiness_h9r.copy_gate import assert_no_h9r_capacity_copy, scan_capacity_claims
from scripts.readiness_h9r.supervisor import (
    CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE,
    CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE,
    MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE,
    QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE,
    TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE,
    calibration_start_implementation_blockers,
)


def _digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def _unit(*, ordinal: int = 1, geometry: str = "G-", cap: str = "C4") -> dict[str, object]:
    return {
        "candidate_manifest_sha256": _digest("candidate"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": _digest(f"fixture-{geometry}"),
        "config_hash": _digest(f"config-{geometry}"),
        "geometry_id": geometry,
        "cap_id": cap,
        "attempt_ordinal": ordinal,
    }


def _schedule(*cells: dict[str, object]) -> dict[str, object]:
    normalized_cells = [
        {name: value for name, value in cell.items() if name != "attempt_ordinal"} for cell in cells
    ]
    normalized_cells.sort(key=canonical_json_sha256)
    seed = _digest("schedule-seed")
    units = [
        {**cell, "attempt_ordinal": ordinal} for cell in normalized_cells for ordinal in range(1, 4)
    ]
    units.sort(
        key=lambda unit: (
            sha256_bytes(f"{seed}\0{attempt_id(unit)}".encode("ascii")),
            attempt_id(unit),
        )
    )
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "phase": "screening",
        "permutation_algorithm": "sha256-key-sort-v1",
        "permutation_seed_sha256": seed,
        "cells": normalized_cells,
        "units": units,
    }


def _confirmation_schedule(*cells: dict[str, object]) -> dict[str, object]:
    normalized_cells = [
        {name: value for name, value in cell.items() if name != "attempt_ordinal"} for cell in cells
    ]
    normalized_cells.sort(key=canonical_json_sha256)
    seed = _digest("confirmation-seed")
    units = [
        {**cell, "attempt_ordinal": ordinal}
        for cell in normalized_cells
        for ordinal in range(4, 11)
    ]
    units.sort(
        key=lambda unit: (
            sha256_bytes(f"{seed}\0{attempt_id(unit)}".encode("ascii")),
            attempt_id(unit),
        )
    )
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "phase": "confirmation",
        "permutation_algorithm": "sha256-key-sort-v1",
        "permutation_seed_sha256": seed,
        "screening_schedule_sha256": _digest("promoted-screening-schedule"),
        "promoted_screening_attempt_ids": sorted(
            attempt_id({**cell, "attempt_ordinal": ordinal})
            for cell in normalized_cells
            for ordinal in range(1, 4)
        ),
        "cells": normalized_cells,
        "units": units,
    }


def _boundary_events() -> list[dict[str, object]]:
    protected_identity = {
        "role": "input",
        "relative_name": "input.bin",
        "logical_bytes": 1,
        "sha256": _digest("input"),
    }
    return [
        {"event": "boot", "monotonic_ns": 10, "pid": 1, "heavy_work_started": False},
        {
            "event": "limits_applied",
            "monotonic_ns": 20,
            "effective_limits": {
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
        {"event": "ready", "monotonic_ns": 30, "heavy_work_started": False},
        {"event": "start", "monotonic_ns": 40},
        {
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
        },
        {"event": "flush_complete", "monotonic_ns": 60, "artifact_count": 1, "logical_bytes": 1},
        {
            "event": "hash_complete",
            "monotonic_ns": 70,
            "artifact_count": 1,
            "artifact_sha256": [_digest("output")],
        },
        {
            "event": "rename_complete",
            "monotonic_ns": 80,
            "path": "C:/out/manifest.json",
            "sha256": _digest("manifest"),
        },
        {"event": "tree_empty", "monotonic_ns": 90},
    ]


def test_catalogo_cierra_caps_geometrias_flujos_steps_y_resultados() -> None:
    payload = catalog_payload()
    assert payload["caps_hypothesis_bytes"] == {
        "C4": 4_294_967_296,
        "C5": 5_368_709_120,
        "C6": 6_442_450_944,
    }
    assert payload["flow_id_count"] == 14
    assert payload["flow_step_count"] == 15
    assert payload["materialized_start_units"] == 0
    assert payload["calibration_start_enabled"] is False
    assert payload["calibration_start_blockers"] == [
        "durable_calibration_authority_fingerprint_unpinned",
        "qualifying_boundary_adapters_unavailable",
        "candidate_execution_material_lease_unimplemented",
        "multiprocess_native_pool_observer_unimplemented",
    ]
    assert payload["calibration_start_disabled_reason"] == "; ".join(
        payload["calibration_start_blockers"]
    )
    assert calibration_start_implementation_blockers() == (
        "qualifying_boundary_adapters_unavailable",
        "candidate_execution_material_lease_unimplemented",
        "multiprocess_native_pool_observer_unimplemented",
    )
    assert QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE is False
    assert CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE is False
    # Implementado y acreditado con su censo OS y sus controles negativos; la puerta global sigue
    # cerrada por los otros tres blockers.
    assert CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE is True
    assert TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE is True
    assert MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE is False
    assert len(FLOW_SPECS) == 15
    assert len({spec.flow_id for spec in FLOW_SPECS}) == 14
    assert {spec.step for spec in FLOW_SPECS if spec.flow_id == "F-LGD-OOS"} == {
        "fit",
        "apply",
    }
    assert tuple(payload["classifications"]) == CLASSIFICATIONS
    assert len(CLASSIFICATIONS) == 15
    assert len(payload["consumer_adapters"]) == 15
    assert len(set(payload["consumer_adapters"].values())) == 15


def test_unidad_start_exige_identidad_expandida_y_rechaza_placeholders() -> None:
    unit = _unit()
    assert validate_attempt_unit(unit) == unit
    assert attempt_id(unit) == canonical_json_sha256(unit)
    missing = dict(unit)
    missing.pop("fixture_manifest_sha256")
    with pytest.raises(ContractError, match="faltantes"):
        validate_attempt_unit(missing)
    with pytest.raises(ContractError, match="extra"):
        validate_attempt_unit({**unit, "profile": "inventado"})
    with pytest.raises(ContractError, match="placeholder"):
        validate_attempt_unit({**unit, "config_hash": "0" * 64})
    with pytest.raises(ContractError, match="fuera del cat"):
        validate_attempt_unit({**unit, "flow_step": "run"})


def test_schedule_firmado_ubica_unidad_exacta_y_rechaza_duplicados() -> None:
    schedule = _schedule(_unit())
    second = schedule["units"][1]
    assert isinstance(second, dict)
    schedule_sha256, position = validate_schedule(schedule, second)
    assert schedule_sha256 == canonical_json_sha256(schedule)
    assert position == 1
    duplicate = _schedule(_unit(), _unit())
    with pytest.raises(ContractError, match="sin duplicados"):
        validate_schedule(duplicate, _unit())


def test_confirmation_extiende_screening_con_ordinales_cuatro_a_diez() -> None:
    schedule = _confirmation_schedule(_unit())
    ordinals = sorted(unit["attempt_ordinal"] for unit in schedule["units"])
    assert ordinals == list(range(4, 11))
    target = schedule["units"][3]
    assert isinstance(target, dict)
    assert validate_schedule(schedule, target)[1] == 3
    orphan = copy.deepcopy(schedule)
    orphan["promoted_screening_attempt_ids"] = orphan["promoted_screening_attempt_ids"][:-1]
    with pytest.raises(ContractError, match="screening promovidos"):
        validate_schedule(orphan, target)


def test_autorizacion_one_shot_liga_receipt_y_start_cierra_sin_fingerprint(
    tmp_path: Path,
) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    unit = _unit()
    tooling_sha256 = _digest("tooling")
    schedule_sha256 = _digest("schedule")
    document_hashes = {"protocol": _digest("protocol")}
    authorization_id = _digest("authorization-one-shot")
    receipt_path = tmp_path / "consumption.json"
    consumption_path_sha256 = authorization_consumption_path_digest(receipt_path)
    statement = authorization_statement(
        unit,
        authorization_id=authorization_id,
        authorization_consumption_path_sha256=consumption_path_sha256,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        schedule_position=0,
        scope="harness-test-only",
    )
    private_key = Ed25519PrivateKey.generate()
    public_key_path = tmp_path / "authority-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    authority = {
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
        "schedule_position": 0,
        "signer_public_key_sha256": trusted_authority_key_identity(public_key_path)[1],
        "signature_ed25519": "0" * 128,
    }
    authority["signature_ed25519"] = private_key.sign(authority_signing_bytes(authority)).hex()
    assert (
        validate_authority(
            authority,
            unit,
            document_hashes=document_hashes,
            tooling_sha256=tooling_sha256,
            schedule_sha256=schedule_sha256,
            schedule_position=0,
            trusted_authority_public_key_path=public_key_path,
        )["authorization_id"]
        == authorization_id
    )

    consumed_at_utc = "2026-08-13T00:00:00+00:00"
    receipt_value = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": authorization_id,
        "attempt_id": attempt_id(unit),
        "authority_sha256": canonical_json_sha256(authority),
        "state": "consumed",
        "consumed_at_utc": consumed_at_utc,
    }
    receipt_bytes = canonical_json_bytes(receipt_value) + b"\n"
    receipt_path.write_bytes(receipt_bytes)
    consumption = {
        "authorization_id": authorization_id,
        "authorization_consumption_path_sha256": consumption_path_sha256,
        "state": "consumed",
        "consumed_at_utc": consumed_at_utc,
        "attempt_id": attempt_id(unit),
        "authority_sha256": canonical_json_sha256(authority),
        "receipt": {
            "path": str(receipt_path),
            "bytes": len(receipt_bytes),
            "sha256": sha256_bytes(receipt_bytes),
        },
    }
    assert (
        validate_authorization_consumption(
            consumption,
            authority=authority,
            expected_attempt_id=attempt_id(unit),
            verify_receipt=True,
        )["state"]
        == "consumed"
    )
    relative_receipt = copy.deepcopy(consumption)
    relative_receipt["receipt"]["path"] = "consumption.json"
    with pytest.raises(ContractError, match="ruta absoluta lexical"):
        validate_authorization_consumption(
            relative_receipt,
            authority=authority,
            expected_attempt_id=attempt_id(unit),
            verify_receipt=False,
        )

    start_statement = authorization_statement(
        unit,
        authorization_id=authorization_id,
        authorization_consumption_path_sha256=consumption_path_sha256,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        schedule_position=0,
        scope="calibration-start",
    )
    start_authority = {
        **authority,
        "scope": "calibration-start",
        "start_authorized": True,
        "authorization_text_sha256": sha256_bytes(start_statement),
        "signature_ed25519": "0" * 128,
    }
    start_authority["signature_ed25519"] = private_key.sign(
        authority_signing_bytes(start_authority)
    ).hex()
    with pytest.raises(ContractError, match="fingerprint humano durable"):
        validate_authority(
            start_authority,
            unit,
            document_hashes=document_hashes,
            tooling_sha256=tooling_sha256,
            schedule_sha256=schedule_sha256,
            schedule_position=0,
            trusted_authority_public_key_path=public_key_path,
        )


def test_digest_receipt_es_absoluto_lexical_y_no_resuelve_fuentes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_path = tmp_path / "store" / "receipt.json"
    lexical_alias = tmp_path / "store" / ".." / "store" / "receipt.json"
    assert authorization_consumption_path_digest(lexical_alias) == (
        authorization_consumption_path_digest(receipt_path)
    )

    def _forbid_resolve(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("el digest lexical no puede resolver ni abrir la ruta")

    monkeypatch.setattr(Path, "resolve", _forbid_resolve)
    assert authorization_consumption_path_digest(receipt_path) == (
        authorization_consumption_path_digest(receipt_path)
    )


def test_avance_campana_exige_cada_evidencia_previa_y_detiene_rojo(tmp_path: Path) -> None:
    schedule = _schedule(_unit())
    first = schedule["units"][0]
    second = schedule["units"][1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    trusted_key = tmp_path / "authority.pub"
    with pytest.raises(ContractError, match="avance de campa"):
        validate_campaign_progress(
            schedule=schedule,
            current_unit=second,
            prior_evidence_paths=[],
            trusted_authority_public_key_path=trusted_key,
        )
    # No se inventa una evidencia para saltarse el gate: un attempt ausente también debe fallar.
    with pytest.raises(ContractError, match="ausente"):
        validate_campaign_progress(
            schedule=schedule,
            current_unit=second,
            prior_evidence_paths=[tmp_path / "attempt.json"],
            trusted_authority_public_key_path=trusted_key,
        )
    assert (
        validate_campaign_progress(
            schedule=schedule,
            current_unit=first,
            prior_evidence_paths=[],
            trusted_authority_public_key_path=trusted_key,
        )["advance_allowed"]
        is True
    )


def test_frontera_rechaza_lectura_antes_de_start_generacion_despues_y_orden() -> None:
    assert validate_boundary_events(_boundary_events())["tree_empty"] == 8
    early_open = [
        _boundary_events()[0],
        {"event": "input_open", "monotonic_ns": 15},
        *_boundary_events()[1:],
    ]
    with pytest.raises(ContractError, match="fuera del catálogo"):
        validate_boundary_events(early_open)
    generated_inside = [
        *_boundary_events()[:2],
        {"event": "fixture_generation", "monotonic_ns": 25},
        *_boundary_events()[2:],
    ]
    with pytest.raises(ContractError, match="fuera del catálogo"):
        validate_boundary_events(generated_inside)
    permuted = copy.deepcopy(_boundary_events())
    permuted[5], permuted[6] = permuted[6], permuted[5]
    permuted[5]["monotonic_ns"] = 60
    permuted[6]["monotonic_ns"] = 70
    with pytest.raises(ContractError, match="orden de frontera"):
        validate_boundary_events(permuted)


def test_estadistica_conserva_maximo_y_aplica_mad_u_sin_outliers() -> None:
    values = [10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
    summary = robust_summary(values)
    assert summary["values"] == [float(value) for value in values]
    assert summary["count"] == 10
    assert summary["median"] == 10
    assert summary["maximum"] == 100
    assert summary["mad_star"] == 0
    assert summary["u"] == 100
    assert summary["stable"] is True
    assert evaluate_repetitions(["success"] * 3, phase="screening")["all_success"] is True
    with pytest.raises(ContractError, match="exactamente 3"):
        evaluate_repetitions(["success"] * 2, phase="screening")


def test_copy_gate_censa_arbol_real_y_detecta_inyeccion(tmp_path: Path) -> None:
    assert assert_no_h9r_capacity_copy(ROOT) > 0
    injected = tmp_path / "README.md"
    injected.write_text("Nikodym funciona en 4 CPU y 8 GB de RAM.\n", encoding="utf-8")
    findings = scan_capacity_claims([injected])
    assert [(finding["line"], finding["literal"]) for finding in findings] == [
        (1, "4 CPU"),
        (1, "8 GB de RAM"),
    ]


@pytest.mark.parametrize("cap_id", ("C4", "C5", "C6"))
def test_caps_son_hipotesis_job_wide_exactas(cap_id: str) -> None:
    assert CAPS[cap_id] in {4 * 1024**3, 5 * 1024**3, 6 * 1024**3}
