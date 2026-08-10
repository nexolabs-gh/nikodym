from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
S0_EVIDENCE = ROOT / "docs/design/evidencia/readiness-w1-s0-2026-08-10.json"
S3_EVIDENCE = ROOT / "docs/design/evidencia/readiness-w1-s3-2026-08-10.json"
SCRIPT = ROOT / "scripts/measure_readiness_w1.py"
SOURCE_SHA = "315f0711ce001546c2bff096a8cf2f91a6502cc0"
SCRIPT_SHA256 = "b2aa9c3fdbeae348c609a1fec915d178bc8fc1fca468a8f7d4b9db1840c373e4"
S0_SHA256 = "83a7c1ca82911c33148d19a0d4d8f162b4272d6a7ad1128be0663369cd81ccdd"
S3_SHA256 = "fc33bcead3cd52a55fc65f919cb40cde2bea11fad60af1078243810c32d70c4e"
WHEEL_SHA256 = "7c590947a3208a44f3cf2d30c6f758881be1796c302d463b4c71bf0ea6fce307"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_evidencia_w1_congela_candidato_y_cleanroom_s0() -> None:
    evidence = _load(S0_EVIDENCE)

    assert _sha256(S0_EVIDENCE) == S0_SHA256
    assert _sha256(SCRIPT) == SCRIPT_SHA256
    assert evidence["schema_version"] == "nikodym.readiness.w1.v1"
    assert evidence["profile"] == "S0-smoke"
    assert evidence["profile_status"] == "pass"
    assert evidence["source_sha"] == SOURCE_SHA
    assert evidence["driver_sha256"] == SCRIPT_SHA256
    assert evidence["cleanroom"]["checkout_clean"] is True
    assert evidence["cleanroom"]["checkout_sha"] == SOURCE_SHA
    assert evidence["cleanroom"]["pythonpath_empty"] is True
    assert evidence["cleanroom"]["installed_matches_wheel"] is True
    assert evidence["cleanroom"]["metadata_matches_wheel"] is True
    assert evidence["cleanroom"]["wheel_sha256"] == WHEEL_SHA256
    assert evidence["budgets"] == {"batch": True, "peak_rss": True, "train": True}
    assert evidence["train"]["rows"] == 10_000
    assert evidence["train"]["variables"] == 25
    assert evidence["train"]["cardinality_observed"] == 100
    assert evidence["apply"]["negatives"] == {
        "anti_refit_spies": True,
        "incomplete_bundle_rejected": True,
    }
    assert evidence["batch"]["scored_rows"] + evidence["batch"]["not_scorable_rows"] == 10_000


def test_evidencia_w1_congela_limites_s3_y_bloqueo_h9() -> None:
    evidence = _load(S3_EVIDENCE)

    assert _sha256(S3_EVIDENCE) == S3_SHA256
    assert evidence["schema_version"] == "nikodym.readiness.w1.v1"
    assert evidence["profile"] == "S3-limite"
    assert evidence["profile_status"] == "pass"
    assert evidence["source_sha"] == SOURCE_SHA
    assert evidence["driver_sha256"] == SCRIPT_SHA256
    assert evidence["cleanroom"]["wheel_sha256"] == WHEEL_SHA256
    assert evidence["limits"] == {
        "batch_rows": {"4999999": "accepted", "5000000": "accepted", "5000001": "rejected"},
        "train_cardinality": {"99999": "accepted", "100000": "accepted", "100001": "rejected"},
        "train_rows": {"999999": "accepted", "1000000": "accepted", "1000001": "rejected"},
        "train_variables": {"99": "accepted", "100": "accepted", "101": "rejected"},
    }
    assert evidence["hardware"]["logical_cpus"] == 12
    assert evidence["hardware"]["logical_cpus"] < 16
