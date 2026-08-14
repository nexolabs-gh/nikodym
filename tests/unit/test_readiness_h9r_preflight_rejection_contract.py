from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.readiness_h9r.contracts import (
    PREFLIGHT_REJECTION_SCHEMA_VERSION,
    ContractError,
    validate_preflight_rejection_evidence,
)


def _safe(path: str) -> dict[str, object]:
    return {
        "path": path,
        "present": True,
        "safe_regular_file": True,
        "rejection": None,
        "bytes": 1,
        "sha256": "a" * 64,
    }


def _payload() -> dict[str, object]:
    launch = {
        "unit_path": "C:/source/unit.json",
        "authority_path": "C:/source/authority.json",
        "authorization_text_path": "C:/source/authorization.txt",
        "trusted_authority_public_key_path": "C:/source/authority.pem",
        "candidate_manifest_path": "C:/source/candidate.json",
        "fixture_manifest_path": "C:/source/fixture.json",
        "config_path": "C:/source/config.json",
        "schedule_path": "C:/source/schedule.json",
        "prior_evidence_paths_path": "C:/source/prior.json",
        "document_paths": {"proposal": "C:/source/proposal.md"},
        "workdir": "C:/work/attempt",
    }
    source_path_keys = {
        "unit": "unit_path",
        "authority": "authority_path",
        "authorization_text": "authorization_text_path",
        "trusted_authority_public_key": "trusted_authority_public_key_path",
        "candidate_manifest": "candidate_manifest_path",
        "fixture_manifest": "fixture_manifest_path",
        "config": "config_path",
        "schedule": "schedule_path",
        "prior_evidence_paths": "prior_evidence_paths_path",
    }
    sources = {name: _safe(str(launch[key])) for name, key in source_path_keys.items()}
    sources["document:proposal"] = _safe("C:/source/proposal.md")
    return {
        "schema_version": PREFLIGHT_REJECTION_SCHEMA_VERSION,
        "phase": "preflight",
        "identity": {
            "unit": None,
            "attempt_id": None,
            "evidence_path": "C:/evidence/rejection.json",
            "wall_time_finished_utc": "2026-08-13T00:00:00+00:00",
        },
        "launch_sources": launch,
        "observed": {
            "source_identities": sources,
            "workdir_state": {
                "path": "C:/work/attempt",
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
        "reasons": ["authority ausente"],
    }


def test_rechazo_preflight_valida_sin_fabricar_intento_start() -> None:
    assert validate_preflight_rejection_evidence(_payload())["phase"] == "preflight"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("termination", "start_count"), 1),
        (("termination", "worker_spawned"), True),
        (("gates", "evidence_atomic"), False),
    ],
)
def test_rechazo_preflight_falla_cerrado_ante_inicio_falso(
    path: tuple[str, str], value: object
) -> None:
    payload = deepcopy(_payload())
    nested = payload[path[0]]
    assert isinstance(nested, dict)
    nested[path[1]] = value
    with pytest.raises(ContractError):
        validate_preflight_rejection_evidence(payload)


def test_rechazo_preflight_exige_censo_bidireccional_de_fuentes() -> None:
    payload = deepcopy(_payload())
    observed = payload["observed"]
    assert isinstance(observed, dict)
    sources = observed["source_identities"]
    assert isinstance(sources, dict)
    sources.pop("unit")
    with pytest.raises(ContractError, match="bidireccional"):
        validate_preflight_rejection_evidence(payload)
