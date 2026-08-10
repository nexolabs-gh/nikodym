"""Genera o verifica el manifiesto canónico que ancla ``uv.lock`` dentro del paquete."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "uv.lock"
MANIFEST = ROOT / "src/nikodym/_build_manifest.json"


def expected_bytes() -> bytes:
    """Construye los bytes canónicos esperados desde el lock fuente."""
    payload = {
        "schema_version": 1,
        "uv_lock_name": "uv.lock",
        "uv_lock_sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def main() -> int:
    """Verifica por defecto; ``--write`` actualiza sólo el recurso derivado."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = expected_bytes()
    if args.write:
        MANIFEST.write_bytes(expected)
        return 0
    if not MANIFEST.is_file() or MANIFEST.read_bytes() != expected:
        raise SystemExit(
            "_build_manifest.json no coincide con uv.lock; ejecute "
            "scripts/check_build_manifest.py --write y revise el diff."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
