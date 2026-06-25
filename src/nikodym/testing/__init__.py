"""Utilidades públicas de testing para extensores de Nikodym (SDD-24).

El paquete se distribuye en el wheel para que terceros validen sus estimadores con el mismo
harness. Importarlo no carga ``hypothesis``; las estrategias lo importan de forma perezosa cuando
se solicitan.
"""

from nikodym.testing.estimator_checks import all_nikodym_checks, check_nikodym_estimator
from nikodym.testing.fixtures import dummy_step_config, golden_seed_sequence, minimal_study
from nikodym.testing.regulatory import (
    REGULATORY_COVERAGE_INCLUDE,
    REGULATORY_COVERAGE_PATHS,
    missing_regulatory_coverage_paths,
    regulatory_coverage_include_arg,
    regulatory_coverage_paths,
)
from nikodym.testing.reproducibility import assert_bitwise_reproducible
from nikodym.testing.strategies import discriminated_union_tags, nikodym_config_strategy

__all__ = [
    "REGULATORY_COVERAGE_INCLUDE",
    "REGULATORY_COVERAGE_PATHS",
    "all_nikodym_checks",
    "assert_bitwise_reproducible",
    "check_nikodym_estimator",
    "discriminated_union_tags",
    "dummy_step_config",
    "golden_seed_sequence",
    "minimal_study",
    "missing_regulatory_coverage_paths",
    "nikodym_config_strategy",
    "regulatory_coverage_include_arg",
    "regulatory_coverage_paths",
]
