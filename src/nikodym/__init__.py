"""Nikodym RiskLib — librería de riesgo de crédito (scoring, ML, provisiones e IFRS 9).

`import nikodym` mantiene el **núcleo liviano**: no arrastra el stack ML pesado, que vive tras
*extras* opcionales con import perezoso (ver :mod:`nikodym.utils.optional`). La superficie
pública de alto nivel (`run`, `check_pipeline`, `assemble_run`) se re-exporta de forma
**perezosa** (PEP 562):
:mod:`nikodym.api` importa audit/governance/tracking en top-level, así que solo se importa al
**acceder** el atributo, nunca al hacer `import nikodym`.
"""

from typing import TYPE_CHECKING, Any

__version__ = "1.12.0"

__all__ = [
    "DatasetCheck",
    "FittedScorecardBundle",
    "PipelineCheck",
    "__version__",
    "apply",
    "assemble_run",
    "check_dataset",
    "check_pipeline",
    "fit_scorecard_bundle",
    "run",
]

_LAZY = frozenset(
    {
        "run",
        "check_pipeline",
        "check_dataset",
        "assemble_run",
        "PipelineCheck",
        "DatasetCheck",
    }
)

_SCORECARD_LAZY = frozenset({"apply", "fit_scorecard_bundle", "FittedScorecardBundle"})

if TYPE_CHECKING:  # pragma: no cover - solo para el type-checker, no en runtime
    from nikodym.api import (
        DatasetCheck,
        PipelineCheck,
        assemble_run,
        check_dataset,
        check_pipeline,
        run,
    )
    from nikodym.scorecard.bundle import FittedScorecardBundle, apply, fit_scorecard_bundle


def __getattr__(name: str) -> Any:
    """Importa perezosamente la superficie de :mod:`nikodym.api` (PEP 562).

    El import de ``nikodym.api`` (y su stack audit/governance/tracking) ocurre solo al acceder
    el atributo, para no romper el núcleo liviano al hacer ``import nikodym``.
    """
    if name in _LAZY:
        from nikodym import api

        return getattr(api, name)
    if name in _SCORECARD_LAZY:
        from nikodym.scorecard import bundle

        return getattr(bundle, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Expone los símbolos perezosos en ``dir(nikodym)`` además de los del módulo."""
    return sorted({*globals(), *_LAZY, *_SCORECARD_LAZY})
