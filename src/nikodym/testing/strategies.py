"""Estrategias Hypothesis públicas para configs Nikodym (SDD-24).

``hypothesis`` es una dependencia de desarrollo, no del wheel. Por eso este módulo no la importa al
cargarse: la función que construye estrategias hace el import perezoso y falla con un mensaje
explícito si el usuario no la instaló en su entorno de test.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Literal, cast, get_args, get_origin

from nikodym.core.config import NikodymConfig, ReproConfig, RunConfig
from nikodym.core.config import schema as core_schema
from nikodym.core.exceptions import MissingDependencyError

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy

__all__ = ["discriminated_union_tags", "nikodym_config_strategy"]

_SECTION_MODULES: dict[str, str] = {"data": "nikodym.data"}


def _hypothesis_strategies() -> Any:
    """Importa ``hypothesis.strategies`` de forma perezosa."""
    try:
        return importlib.import_module("hypothesis.strategies")
    except ImportError as exc:
        raise MissingDependencyError(
            "Las estrategias Hypothesis de nikodym.testing requieren `hypothesis` (MPL-2.0). "
            "Instálalo en tu entorno de test (`pip install hypothesis`) o usa el grupo de "
            "desarrollo del proyecto."
        ) from exc


def nikodym_config_strategy(
    *,
    sections: list[str] | None = None,
    require_data: bool = False,
) -> SearchStrategy[NikodymConfig]:
    """Construye una estrategia Hypothesis que genera ``NikodymConfig`` válidos.

    Parameters
    ----------
    sections : list[str] | None
        Subconjunto de secciones opcionales que pueden venir activas. En F0, la única sección de
        dominio soportada por este helper es ``"data"``.
    require_data : bool
        Si es ``True``, la sección ``data`` se genera siempre y se importa perezosamente
        ``nikodym.data`` para activar su hook de Pydantic.
    """
    st = _hypothesis_strategies()
    allowed = set(sections or [])
    if require_data:
        allowed.add("data")
    unknown = allowed - set(_SECTION_MODULES)
    if unknown:
        raise ValueError(
            f"Secciones no soportadas por nikodym_config_strategy en F0: {sorted(unknown)}."
        )

    repro = st.builds(
        ReproConfig,
        seed=st.integers(min_value=0, max_value=2**32 - 1),
        strict_determinism=st.booleans(),
    )
    run = st.builds(RunConfig, steps=st.none(), fail_fast=st.booleans())
    data = _data_config_strategy(st) if "data" in allowed else st.none()
    return cast(
        "SearchStrategy[NikodymConfig]",
        st.builds(
            NikodymConfig,
            schema_version=st.just("1.0.0"),
            name=st.sampled_from(["nikodym-study", "contrato-testing", "riesgo-crediticio"]),
            repro=repro,
            run=run,
            data=data,
            audit=st.none(),
            governance=st.none(),
            tracking=st.none(),
        ),
    )


def _data_config_strategy(st: Any) -> Any:
    """Estrategia compacta de ``DataConfig`` que respeta validadores cross-field."""
    importlib.import_module("nikodym.data")
    from nikodym.data.config import (
        CohortSplitConfig,
        DataConfig,
        PartitionConfig,
        Predicate,
        RandomSplitConfig,
        Rule,
        TargetConfig,
        TemporalSplitConfig,
    )

    bad_rule = st.builds(
        Rule,
        all_of=st.tuples(
            st.builds(Predicate, col=st.just("dpd_12m"), op=st.just(">="), value=st.just(90))
        ),
        any_of=st.just(()),
    )
    partition_strategy = st.one_of(
        st.builds(
            RandomSplitConfig,
            dev_fraction=st.just(0.7),
            holdout_fraction=st.just(0.15),
            oot_fraction=st.just(0.15),
            stratify_by=st.none(),
        ),
        st.builds(
            TemporalSplitConfig,
            date_col=st.just("fecha_obs"),
            oot_from=st.just("2025-01-01"),
            holdout_fraction=st.floats(min_value=0.0, max_value=0.8, allow_nan=False),
        ),
        st.builds(
            CohortSplitConfig,
            cohort_col=st.just("cohorte"),
            oot_cohorts=st.just(("2025Q1",)),
            holdout_fraction=st.floats(min_value=0.0, max_value=0.8, allow_nan=False),
        ),
    )
    return st.builds(
        DataConfig,
        target=st.builds(TargetConfig, bad_rule=bad_rule),
        partition=st.builds(
            PartitionConfig,
            strategy=partition_strategy,
            ttd_includes_excluded=st.booleans(),
            min_bads_per_partition=st.integers(min_value=0, max_value=100),
        ),
    )


def discriminated_union_tags() -> dict[str, list[str]]:
    """Devuelve tags ``type`` de uniones discriminadas de nivel sección.

    Solo cruza secciones resueltas por el ``REGISTRY`` global. Las uniones anidadas, como
    ``data.partition.strategy``, son factories locales y no aparecen aquí.
    """
    result: dict[str, list[str]] = {}
    for domain, module_name in _SECTION_MODULES.items():
        importlib.import_module(module_name)
        config_cls = _config_cls_for_domain(domain)
        tags = _literal_tags(config_cls.model_fields["type"].annotation)
        result[domain] = tags
    return result


def _config_cls_for_domain(domain: str) -> type[Any]:
    """Resuelve la clase de config de una sección cargada por hook diferido."""
    if domain == "data" and core_schema._DATA_CONFIG_CLS is not None:
        return core_schema._DATA_CONFIG_CLS
    raise AssertionError(f"No hay config_cls cargada para el dominio '{domain}'.")


def _literal_tags(annotation: Any) -> list[str]:
    """Extrae tags string desde ``Literal[...]``."""
    if get_origin(annotation) is not Literal:
        return []
    return [value for value in get_args(annotation) if isinstance(value, str)]
