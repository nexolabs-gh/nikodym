from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from scripts.readiness_h9r.contracts import (
    AGGREGATE_SCHEMA_VERSION,
    ATTEMPT_SCHEMA_VERSION,
    CLASSIFICATIONS,
    aggregate_json_schema,
    attempt_json_schema,
    internal_authorization_gate_json_schema,
    internal_authorization_precommit_json_schema,
    internal_authorization_release_json_schema,
    post_start_failure_json_schema,
    pre_start_failure_json_schema,
    preflight_rejection_json_schema,
    read_json_object,
    robust_summary,
    sha256_bytes,
    write_internal_authorization_release_reservation,
)


def _digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def _walk_schema(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False, path
            assert "properties" in value, path
        if value.get("pattern") == "^[0-9a-f]{64}$":
            assert value.get("not") == {"enum": ["0" * 64, "f" * 64]}, path
        if value.get("pattern") == "^(?:[0-9a-f]{40}|[0-9a-f]{64})$":
            assert value.get("not") == {"enum": ["0" * 40, "f" * 40, "0" * 64, "f" * 64]}, path
        if value.get("pattern") == "^[0-9a-f]{128}$":
            assert value.get("not") == {"enum": ["0" * 128, "f" * 128]}, path
        for key, child in value.items():
            _walk_schema(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_schema(child, path=f"{path}[{index}]")


@pytest.mark.parametrize(
    "factory",
    [
        attempt_json_schema,
        aggregate_json_schema,
        preflight_rejection_json_schema,
        pre_start_failure_json_schema,
        post_start_failure_json_schema,
        internal_authorization_precommit_json_schema,
        internal_authorization_gate_json_schema,
        internal_authorization_release_json_schema,
    ],
)
def test_schema_h9r_cierra_recursivamente_todos_los_objetos(factory: Any) -> None:
    schema = factory()
    Draft202012Validator.check_schema(schema)
    _walk_schema(schema)


def test_schema_intento_cierra_clases_sidecars_y_cliente_externo() -> None:
    schema = attempt_json_schema()
    properties = schema["properties"]
    assert properties["result"]["properties"]["classification"]["enum"] == list(CLASSIFICATIONS)
    sidecars = properties["resources"]["properties"]["sidecars"]
    assert (sidecars["minItems"], sidecars["maxItems"]) == (15, 15)
    assert sidecars["items"] is False
    assert [item["properties"]["name"]["const"] for item in sidecars["prefixItems"]] == [
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
    ]
    assert [item["properties"]["format"]["const"] for item in sidecars["prefixItems"]] == [
        *(["jsonl"] * 6),
        "binary",
        "binary",
        "jsonl",
        "binary",
        "binary",
        "binary",
        "binary",
        "binary",
        "binary",
    ]
    assert "authorization_consumption" in properties
    assert properties["authority"]["properties"]["signer_public_key_sha256"] == {"not": {}}
    termination = properties["termination"]["properties"]
    assert termination["client_tree_empty"] == {"type": "boolean"}
    orphan_rule = next(
        rule
        for rule in schema["allOf"]
        if rule.get("if", {})
        .get("properties", {})
        .get("result", {})
        .get("properties", {})
        .get("classification")
        == {"const": "orphan_detected"}
    )
    assert orphan_rule["then"]["properties"]["termination"]["properties"]["cleanup_complete"] == {
        "const": False
    }
    assert orphan_rule["else"]["properties"]["termination"]["properties"]["client_tree_empty"] == {
        "const": True
    }
    assert set(properties["resources"]["properties"]["external_client"]["required"]) == {
        "declared",
        "command_sha256",
        "accounting",
        "final_census",
    }
    final_tree = schema["$defs"]["external_census"]["properties"]["tree"]
    process = final_tree["properties"]["processes"]["items"]
    assert process["additionalProperties"] is False
    assert set(process["required"]) == {
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
    assert (
        final_tree["properties"]["process_query_errors"]["items"]["additionalProperties"] is False
    )
    assert final_tree["properties"]["thread_query_errors"]["items"]["additionalProperties"] is False


def test_schema_termination_preserva_trigger_si_cleanup_deriva_orphan() -> None:
    attempt_schema = attempt_json_schema()
    relationship_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "termination": attempt_schema["properties"]["termination"],
            "result": attempt_schema["properties"]["result"],
        },
        "required": ["termination", "result"],
        "allOf": attempt_schema["allOf"],
        "$defs": attempt_schema["$defs"],
    }
    validator = Draft202012Validator(relationship_schema)
    base_termination = {
        "returncode_signed": None,
        "returncode_unsigned": None,
        "client_returncode_signed": None,
        "client_returncode_unsigned": None,
        "cleanup_complete": True,
        "tree_empty": True,
        "client_tree_empty": True,
        "trigger_classification": "watchdog_deadline",
        "timed_out": True,
        "cancelled": False,
        "worker_result": None,
    }
    watchdog = {
        "termination": base_termination,
        "result": {
            "classification": "watchdog_deadline",
            "statistically_eligible": False,
            "reasons": ["deadline"],
        },
    }
    validator.validate(watchdog)

    orphan = copy.deepcopy(watchdog)
    orphan["termination"].update(
        {"cleanup_complete": False, "tree_empty": False, "client_tree_empty": True}
    )
    orphan["result"]["classification"] = "orphan_detected"
    validator.validate(orphan)

    missing_trigger_flag = copy.deepcopy(orphan)
    missing_trigger_flag["termination"]["timed_out"] = False
    assert list(validator.iter_errors(missing_trigger_flag))
    overwritten_trigger = copy.deepcopy(watchdog)
    overwritten_trigger["result"]["classification"] = "consumer_error"
    assert list(validator.iter_errors(overwritten_trigger))


def test_schema_sha_y_git_sha_rechazan_uppercase_y_placeholders() -> None:
    schema = attempt_json_schema()
    sha = schema["$defs"]["sha256"]
    source_sha = schema["properties"]["candidate"]["properties"]["source_sha"]
    source_commit = schema["properties"]["fixture"]["properties"]["generator"]["properties"][
        "source_commit"
    ]
    signature = schema["properties"]["authority"]["properties"]["signature_ed25519"]
    Draft202012Validator(sha).validate(_digest("sha-válido"))
    for invalid in ("A" + "1" * 63, "0" * 64, "f" * 64):
        assert list(Draft202012Validator(sha).iter_errors(invalid))
    for git_schema in (source_sha, source_commit):
        Draft202012Validator(git_schema).validate("1" * 40)
        for invalid in ("A" + "1" * 39, "0" * 40, "f" * 64):
            assert list(Draft202012Validator(git_schema).iter_errors(invalid))
    Draft202012Validator(signature).validate("1" * 128)
    for invalid in ("A" + "1" * 127, "0" * 128, "f" * 128):
        assert list(Draft202012Validator(signature).iter_errors(invalid))


def test_schema_agregado_exige_schedule_y_summaries_cerrados() -> None:
    schema = aggregate_json_schema()
    assert "schedules" in schema["required"]
    schedules = schema["properties"]["schedules"]
    assert set(schedules["required"]) == {"screening", "confirmation", "bracket_following"}
    attempt = schema["properties"]["attempts"]["items"]
    assert attempt["additionalProperties"] is False
    assert set(attempt["required"]) == {
        "attempt_id",
        "attempt_ordinal",
        "schedule_sha256",
        "schedule_phase",
        "linked_screening_schedule_sha256",
        "schedule_position",
        "evidence_sha256",
        "evidence_path",
        "evidence_schema_version",
        "classification",
        "execution_environment_sha256",
        "metrics",
        "terminal_cause",
    }


def test_schemas_draft202012_validan_instancias_contractuales(
    tmp_path: Path,
) -> None:
    # Importar factories privadas de tests mantiene este gate sin crear una segunda fuente de
    # verdad para objetos grandes. Son exclusivamente harness-test-only.
    from test_readiness_h9r_contract_runtime_guards import (
        _internal_gate_fixture,
        _post_start_payload,
        _pre_start_payload,
    )
    from test_readiness_h9r_preflight_rejection_contract import _payload as rejection_payload

    pre_root = tmp_path / "pre"
    post_root = tmp_path / "post"
    gate_root = tmp_path / "gate"
    for root in (pre_root, post_root, gate_root):
        root.mkdir()
    pre, _ = _pre_start_payload(pre_root)
    post, _ = _post_start_payload(post_root)
    gate, _key, _workdir, receipt, requests, capabilities = _internal_gate_fixture(gate_root)
    precommit = read_json_object(Path(gate["internal_authorization_precommit"]["path"]))
    release = write_internal_authorization_release_reservation(
        precommit=precommit,
        role="worker",
        request_payload_sha256=requests["worker"],
        capability_commitment_sha256=capabilities["worker"],
        authorization_consumption_path=receipt,
    )["value"]
    instances = (
        (
            pre_start_failure_json_schema(allow_harness_test_authority=True),
            pre,
        ),
        (
            post_start_failure_json_schema(allow_harness_test_authority=True),
            post,
        ),
        (
            internal_authorization_gate_json_schema(allow_harness_test_authority=True),
            gate,
        ),
        (internal_authorization_precommit_json_schema(), precommit),
        (internal_authorization_release_json_schema(), release),
        (preflight_rejection_json_schema(), rejection_payload()),
    )
    for schema, instance in instances:
        Draft202012Validator(schema).validate(instance)

    consumed_pre = copy.deepcopy(pre)
    consumed_pre["authorization_reservation"]["state"] = "consumed"
    consumed_pre["authorization_reservation"]["consumed_at_utc"] = "2026-08-13T00:00:00+00:00"
    consumed_pre["gates"]["authorization_reserved"] = False
    Draft202012Validator(pre_start_failure_json_schema(allow_harness_test_authority=True)).validate(
        consumed_pre
    )


def test_schema_agregado_draft202012_valida_instancia_representativa() -> None:
    cell = {
        "candidate_manifest_sha256": _digest("candidate"),
        "flow_id": "F-SCORE-TRAIN",
        "flow_step": "train",
        "fixture_manifest_sha256": _digest("fixture"),
        "config_hash": _digest("config"),
        "geometry_id": "G-",
        "cap_id": "C4",
    }
    metrics = {
        "wall_seconds": 1.0,
        "peak_job_memory_commit_bytes": 2.0,
        "peak_incremental_allocated_bytes": 3.0,
    }
    row = {
        "attempt_id": _digest("attempt"),
        "attempt_ordinal": 1,
        "schedule_sha256": _digest("schedule"),
        "schedule_phase": "screening",
        "linked_screening_schedule_sha256": None,
        "schedule_position": 0,
        "evidence_sha256": _digest("evidence"),
        "evidence_path": "C:/evidence/attempt.json",
        "evidence_schema_version": ATTEMPT_SCHEMA_VERSION,
        "classification": "success",
        "execution_environment_sha256": _digest("environment"),
        "metrics": metrics,
        "terminal_cause": None,
    }
    aggregate = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "cell_identity": cell,
        "execution_environment_sha256": row["execution_environment_sha256"],
        "schedules": {
            "screening": row["schedule_sha256"],
            "confirmation": None,
            "bracket_following": None,
        },
        "expected_attempt_ids": [row["attempt_id"]],
        "received_attempt_ids": [row["attempt_id"]],
        "attempts": [row],
        "completeness": {
            "missing": [],
            "extra": [],
            "duplicates": [],
            "order_matches": True,
            "complete": True,
        },
        "statistics": {name: robust_summary([value]) for name, value in metrics.items()},
    }
    validator = Draft202012Validator(aggregate_json_schema())
    validator.validate(aggregate)
    tampered = copy.deepcopy(aggregate)
    tampered["attempts"][0]["metrics"]["extra"] = 1
    assert list(validator.iter_errors(tampered))
    all_null_without_terminal = copy.deepcopy(aggregate)
    all_null_without_terminal["schedules"] = {
        "screening": None,
        "confirmation": None,
        "bracket_following": None,
    }
    assert list(validator.iter_errors(all_null_without_terminal))

    terminal = copy.deepcopy(aggregate)
    terminal["schedules"] = all_null_without_terminal["schedules"]
    terminal["execution_environment_sha256"] = _digest("execution-environment")
    terminal["statistics"] = {}
    terminal_row = terminal["attempts"][0]
    terminal_row.update(
        {
            "schedule_phase": "screening",
            "evidence_schema_version": "nikodym.readiness.h9r.post-start-failure.v1",
            "classification": "evidence_incomplete",
            "execution_environment_sha256": _digest("execution-environment"),
            "metrics": None,
            "terminal_cause": {
                "stage": "terminal_publication",
                "error_type": "OSError",
                "message": "fallo causal",
                "traceback_sha256": _digest("traceback"),
            },
        }
    )
    validator.validate(terminal)


def test_schemas_draft202012_rechazan_extra_anidado_y_orden_sidecar(
    tmp_path: Path,
) -> None:
    from test_readiness_h9r_contract_runtime_guards import _pre_start_payload
    from test_readiness_h9r_preflight_rejection_contract import _payload as rejection_payload

    pre_root = tmp_path / "pre"
    pre_root.mkdir()
    pre, _ = _pre_start_payload(pre_root)
    nested_extra = copy.deepcopy(pre)
    nested_extra["observed"]["handshake"]["boot"]["extra"] = True
    assert list(
        Draft202012Validator(
            pre_start_failure_json_schema(allow_harness_test_authority=True)
        ).iter_errors(nested_extra)
    )

    reordered = copy.deepcopy(pre)
    sidecars = reordered["observed"]["sidecars"]
    sidecars[0], sidecars[1] = sidecars[1], sidecars[0]
    assert list(
        Draft202012Validator(
            pre_start_failure_json_schema(allow_harness_test_authority=True)
        ).iter_errors(reordered)
    )

    uppercase_signature = copy.deepcopy(pre)
    uppercase_signature["authority"]["signature_ed25519"] = uppercase_signature["authority"][
        "signature_ed25519"
    ].upper()
    assert (
        uppercase_signature["authority"]["signature_ed25519"]
        != pre["authority"]["signature_ed25519"]
    )
    assert list(
        Draft202012Validator(
            pre_start_failure_json_schema(allow_harness_test_authority=True)
        ).iter_errors(uppercase_signature)
    )

    placeholder_digest = copy.deepcopy(pre)
    placeholder_digest["authority"]["authorization_id"] = "0" * 64
    assert list(
        Draft202012Validator(
            pre_start_failure_json_schema(allow_harness_test_authority=True)
        ).iter_errors(placeholder_digest)
    )

    rejection = rejection_payload()
    rejection["observed"]["workdir_state"]["extra"] = "prohibido"
    assert list(Draft202012Validator(preflight_rejection_json_schema()).iter_errors(rejection))
