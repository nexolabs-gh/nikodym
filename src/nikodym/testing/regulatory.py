"""Fuente única del gate de cobertura regulatoria (SDD-24 §11, Hito 0).

El job ``coverage-regulatory`` debe consumir estos targets para evitar falsos verdes por vacuidad:
si un módulo declarado desaparece del filesystem, el test asociado falla antes de aceptar un
``coverage report`` 100 % sobre una lista vacía.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = [
    "REGULATORY_COVERAGE_INCLUDE",
    "REGULATORY_COVERAGE_PATHS",
    "missing_regulatory_coverage_paths",
    "regulatory_coverage_include_arg",
    "regulatory_coverage_paths",
]

REGULATORY_COVERAGE_PATHS: Final[tuple[str, ...]] = (
    "src/nikodym/core/exceptions.py",
    "src/nikodym/core/seeding.py",
    "src/nikodym/provisioning/cmf/__init__.py",
    "src/nikodym/provisioning/ifrs9/__init__.py",
)
"""Rutas fuente que deben existir y quedar al 100 % de cobertura."""

REGULATORY_COVERAGE_INCLUDE: Final[tuple[str, ...]] = tuple(
    f"*/{path.removeprefix('src/')}" for path in REGULATORY_COVERAGE_PATHS
)
"""Patrones ``coverage report --include`` derivados de ``REGULATORY_COVERAGE_PATHS``."""


def regulatory_coverage_include_arg() -> str:
    """Devuelve el argumento ``--include`` canónico para ``coverage report``."""
    return ",".join(REGULATORY_COVERAGE_INCLUDE)


def regulatory_coverage_paths(root: Path) -> tuple[Path, ...]:
    """Materializa las rutas regulatorias contra la raíz del repo."""
    return tuple(root / relative for relative in REGULATORY_COVERAGE_PATHS)


def missing_regulatory_coverage_paths(root: Path) -> tuple[Path, ...]:
    """Lista rutas regulatorias declaradas que no existen bajo ``root``."""
    return tuple(path for path in regulatory_coverage_paths(root) if not path.is_file())
