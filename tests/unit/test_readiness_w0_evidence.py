from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/design/evidencia/readiness-w0-2026-08-09.json"
SCRIPT = ROOT / "scripts/measure_readiness_w0.py"
EVIDENCE_SHA256 = "757c55ef3d8274ca44232eb03943f6fd04e26d5a568774bcdbef025933e092ab"
MEASURED_SHA = "8c610e3cf00ba74de1e3b401d62c1ea01525ab35"
SCRIPT_SHA256 = "d309efbd5b4ec073fd778aa3619d15262774f8168efac6c338dceea1af7cf8e0"
UV_LOCK_SHA256 = "13534883b272fdd9a0c502a91cbe7ab63f0de43a73b6233b6a5f4dcab694b10a"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence() -> dict[str, Any]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def _harness() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPT), run_name="readiness_w0_test")


def test_baseline_w0_congela_fuente_perfiles_y_estados() -> None:
    evidence = _evidence()

    assert _sha256(EVIDENCE) == EVIDENCE_SHA256
    assert evidence["schema_version"] == "nikodym.readiness.w0.v1"
    assert evidence["scope"] == "W0_only"
    assert evidence["source"] == {
        "git_branch": "main",
        "git_dirty": False,
        "git_sha": MEASURED_SHA,
        "measurement_script": "scripts/measure_readiness_w0.py",
        "measurement_script_sha256": SCRIPT_SHA256,
        "uv_lock_sha256": UV_LOCK_SHA256,
    }
    assert evidence["profiles"] == {
        "S0-smoke": {
            "cardinality": 100,
            "horizon": 12,
            "rows": 10_000,
            "scenarios": 1,
            "target_ram_gib": 4,
            "variables": 25,
        },
        "S1-local": {
            "cardinality": 10_000,
            "horizon": 60,
            "rows": 100_000,
            "scenarios": 3,
            "target_ram_gib": 16,
            "variables": 50,
        },
        "S2-equipo": {
            "batch_rows": 5_000_000,
            "cardinality": 100_000,
            "horizon": 120,
            "rows": 1_000_000,
            "scenarios": 5,
            "target_ram_gib": 32,
            "temporal_operations": 100_000,
            "variables": 100,
        },
    }
    assert evidence["summary"] == {
        "measurement_statuses": {"measured": 2, "proxy": 6},
        "profile_cells_no_medible": 10,
    }

    cells = evidence["profile_cells"]
    assert len(cells) == 12
    assert len({(cell["profile"], cell["channel"]) for cell in cells}) == 12
    assert sum(cell["status"] == "no_medible" for cell in cells) == 10
    assert all(cell.get("reason") for cell in cells if cell["status"] == "no_medible")


def test_baseline_w0_reconcilia_censo_hashes_temporal_y_lineage() -> None:
    measurements = {item["probe"]: item for item in _evidence()["measurements"]}

    assert len(measurements) == 8
    assert {item["status"] for item in measurements.values()} == {"measured", "proxy"}
    census = measurements["contract-census"]
    assert census["option_pairs"] == census["option_pairs_unique"] == 207
    assert census["option_states"] == {
        "disponible": 197,
        "exige_otro_campo": 3,
        "no_implementada": 2,
        "sin_efecto": 5,
    }

    for probe in ("frame-hash-s0", "frame-hash-s1", "frame-hash-s2"):
        assert measurements[probe]["repeat_digest_equal"] is True

    f4 = measurements["preset-f4"]
    assert f4["temporal_input_operations"] == 6_000
    assert f4["temporal_periods"] == 5
    assert f4["temporal_scenarios"] == 1
    assert f4["temporal_expanded_rows"] == 30_000
    assert f4["temporal_geometry_reconciles"] is True

    for probe in ("preset-f1", "preset-f3", "preset-f4", "score-train-s0"):
        run = measurements[probe]
        assert run["lineage_git_sha"] == MEASURED_SHA
        assert run["lineage_git_dirty"] is False
        assert run["lineage_data_hash"]
        assert run["lineage_config_hash"]
        assert run["lineage_uv_lock_hash"] is None


def test_arnes_w0_no_sobredeclara_medicion_ni_hardware() -> None:
    harness = _harness()
    synthetic = [{"probe": "score-train-s0", "status": "no_medible"}]

    cells = harness["_profile_cells"](synthetic, 64 * harness["GIB"])
    s0 = [cell for cell in cells if cell["profile"] == "S0-smoke"]
    assert {cell["status"] for cell in s0} == {"no_medible"}
    assert all(cell.get("reason") for cell in s0)

    reason = harness["_hardware_reason"]("S2-equipo", 64 * harness["GIB"])
    assert "cumple la RAM nominal" in reason
    assert "no ejecutó el flujo completo" in reason
    assert "no cumple" not in reason


def test_arnes_w0_rechaza_sobrescritura_y_arbol_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness()
    run_parent = harness["_run_parent"]
    existing = tmp_path / "baseline.json"
    existing.write_text("inmutable", encoding="utf-8")

    with pytest.raises(SystemExit, match="no se sobrescribe"):
        run_parent(existing)

    output = tmp_path / "nuevo.json"
    monkeypatch.setitem(
        run_parent.__globals__, "_git", lambda *args: "?? evidencia-no-versionada.json"
    )
    with pytest.raises(SystemExit, match="commit limpio"):
        run_parent(output)
