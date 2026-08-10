"""Ejecuta las suites focales que sostienen los 69 grupos y 203 pares D-RDY-ABA."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "tests" / "fixtures" / "option_effect_oracles.txt"


def _nodes(selected_path: str | None = None) -> list[str]:
    nodes: set[str] = set()
    for number, raw in enumerate(REGISTRY.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 4:
            raise RuntimeError(f"línea {number}: registry inválido")
        if selected_path is not None and parts[0] != selected_path:
            continue
        for cell in parts[2:]:
            nodes.update(node for node in cell.split(";") if node)
    if not nodes:
        raise RuntimeError("el registry de oráculos está vacío")
    return sorted(nodes)


def main() -> int:
    """Ejecuta o sólo colecta el conjunto focal, sin duplicar node ids."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--path")
    args = parser.parse_args()
    command = [sys.executable, "-m", "pytest", "-q"]
    if args.collect_only:
        command.append("--collect-only")
    nodes = _nodes(args.path)
    if not nodes:
        raise SystemExit(f"path sin suite registrada: {args.path!r}")
    command.extend(nodes)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
