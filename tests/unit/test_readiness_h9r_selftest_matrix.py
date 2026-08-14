"""Regresiones del self-test seguro y de sus probes internos sin START."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from scripts.readiness_h9r.artifacts import validate_output_manifest
from scripts.readiness_h9r.contracts import read_json_object
from scripts.readiness_h9r.probes import run_probe
from scripts.readiness_h9r.selftest import (
    _control_authority_preflight,
    _control_fifth_cpu,
)
from scripts.readiness_h9r.windows_job import current_process_affinity

_PATH_ENVIRONMENT = (
    "NIKODYM_H9R_BOUNDARY_JSONL",
    "NIKODYM_H9R_FILESYSTEM_JSONL",
    "NIKODYM_H9R_OUTPUT_ROOT",
    "NIKODYM_H9R_NATIVE_POOLS_JSONL",
)


def _configure_probe_paths(monkeypatch: MonkeyPatch, root: Path) -> dict[str, Path]:
    paths = {
        "boundary": root / "boundary.jsonl",
        "filesystem": root / "filesystem.jsonl",
        "outputs": root / "outputs",
        "pools": root / "pools.jsonl",
    }
    for name, path in zip(_PATH_ENVIRONMENT, paths.values(), strict=True):
        monkeypatch.setenv(name, str(path))
    return paths


def test_probe_normal_publica_bin_con_sidecar_y_partial_registra_catalogo(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    normal = tmp_path / "normal"
    normal.mkdir()
    normal_paths = _configure_probe_paths(monkeypatch, normal)
    input_path = normal / "input.bin"
    input_path.write_bytes(b"abc")
    assert run_probe("normal", input_path=input_path, delay_seconds=0) == 0
    manifest = read_json_object(normal_paths["outputs"] / "manifest.json")
    validated = validate_output_manifest(
        normal_paths["outputs"],
        expected_identities=["probe-result"],
        expected_counts={"probe-result": 1},
        expected_golden_sha256=str(manifest["golden_observed_sha256"]),
    )
    assert validated["artifacts"][0]["count_evidence"]["mode"] == "hash_bound_attestation"

    partial = tmp_path / "partial"
    partial.mkdir()
    partial_paths = _configure_probe_paths(monkeypatch, partial)
    partial_input = partial / "input.bin"
    partial_input.write_bytes(b"abc")
    assert run_probe("partial-crash", input_path=partial_input, delay_seconds=0) == 92
    events = [
        json.loads(line)
        for line in partial_paths["filesystem"].read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == ["create", "flush"]
    assert list(partial_paths["outputs"].glob("*.partial"))
    assert not (partial_paths["outputs"] / "manifest.json").exists()


def test_probe_deadline_sin_input_no_exige_paths_de_worker(
    monkeypatch: MonkeyPatch,
) -> None:
    for name in _PATH_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    assert run_probe("deadline", input_path=None, delay_seconds=0) == 0


def test_authority_preflight_rechaza_handshake_real_sin_token_ni_workload(
    tmp_path: Path,
) -> None:
    control = _control_authority_preflight(tmp_path)
    evidence = control["evidence"]
    assert control["restoration"]["byte_exact"] is True
    assert evidence["start_tokens_emitted"] == 0
    assert evidence["workload_started"] is False
    assert evidence["protocol_start_tokens"] == 0
    assert evidence["handshake_rejections"] == {
        "start_before_ready": {
            "final_state": "created",
            "start_events": 0,
            "start_token_emitted": False,
            "workload_started": False,
        },
        "wrong_authority_digest": {
            "final_state": "ready",
            "start_events": 0,
            "start_token_emitted": False,
            "workload_started": False,
        },
    }
    assert any("START antes de READY" in cause for cause in control["red_cause"])
    assert any("autoridad START no coincide" in cause for cause in control["red_cause"])


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object es exclusivo de Windows")
def test_quinta_cpu_sintetica_no_exige_quinta_fisica_y_censa_hasta_cuatro(
    tmp_path: Path,
) -> None:
    control = _control_fifth_cpu(tmp_path)
    evidence = control["evidence"]
    assert control["restoration"]["byte_exact"] is True
    assert evidence["injected_logical_cpu_count"] == 5
    assert evidence["physical_fifth_cpu_required"] is False
    assert evidence["effective_logical_cpu_count"] == min(
        4, current_process_affinity()["process_mask"].bit_count()
    )
    assert evidence["effective_outside_selected_mask"] == 0
    assert evidence["effective_fifth_cpu_visible"] is False
