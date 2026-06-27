"""Fixtures programáticas públicas para tests de extensores Nikodym (SDD-24)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from nikodym.core.config import NikodymConfig, RunConfig
from nikodym.core.registry import REGISTRY
from nikodym.core.seeding import SeedManager
from nikodym.core.steps import ArtifactKey, Step
from nikodym.core.study import Study

if TYPE_CHECKING:
    from numpy.random import Generator

__all__ = ["dummy_step_config", "golden_seed_sequence", "minimal_study"]

_DUMMY_DOMAIN = "testing"
_DUMMY_NAME = "dummy"


class _DummyStep:
    """Step mínimo registrado por ``dummy_step_config`` para pruebas de contrato."""

    name: ClassVar[str] = _DUMMY_DOMAIN
    requires: ClassVar[tuple[ArtifactKey, ...]] = ()
    provides: ClassVar[tuple[ArtifactKey, ...]] = ((_DUMMY_DOMAIN, "dummy_value"),)

    @classmethod
    def from_config(cls, cfg: Any) -> _DummyStep:
        """Construye el step ignorando un sub-config de juguete."""
        del cfg
        return cls()

    def execute(self, study: Study, rng: Generator) -> int:
        """Escribe un artefacto entero reproducible y lo devuelve."""
        value = int(rng.integers(0, 2**31))
        study.artifacts.set(_DUMMY_DOMAIN, "dummy_value", value, overwrite=True)
        return value


def minimal_study() -> Study:
    """Devuelve ``Study(NikodymConfig())`` sin argumentos adicionales (DoD F0)."""
    return Study(NikodymConfig(data=None, eda=None, audit=None, governance=None, tracking=None))


def dummy_step_config() -> NikodymConfig:
    """Registra un ``Step`` dummy y devuelve un ``NikodymConfig`` mínimo válido.

    En F0 el schema raíz no admite una sección ``testing`` dinámica; por eso el helper registra el
    componente en ``REGISTRY`` para tests de contrato y devuelve un config mínimo con ``run.steps``
    vacío. Los tests que necesiten ejecutar el step pueden resolverlo desde el registro.
    """
    _ensure_dummy_step_registered()
    return NikodymConfig(
        name="nikodym-dummy-step",
        run=RunConfig(steps=[]),
        data=None,
        eda=None,
        audit=None,
        governance=None,
        tracking=None,
    )


def golden_seed_sequence(name: str, n: int) -> list[int]:
    """Devuelve los primeros ``n`` enteros dorados de ``SeedManager(42).generator_for(name)``."""
    if n < 0:
        raise ValueError("n debe ser >= 0 para generar una secuencia de semillas dorada.")
    return [
        int(value)
        for value in SeedManager(42).generator_for(name).integers(0, 2**31, size=n).tolist()
    ]


def _ensure_dummy_step_registered() -> None:
    """Registra el step dummy una sola vez, evitando colisiones en suites largas."""
    if _DUMMY_NAME not in REGISTRY.available(_DUMMY_DOMAIN):
        REGISTRY.register(_DUMMY_NAME, domain=_DUMMY_DOMAIN)(_DummyStep)
    resolved = REGISTRY.resolve(_DUMMY_DOMAIN, _DUMMY_NAME)
    factory = getattr(resolved, "from_config", None)
    if not callable(factory) or not isinstance(factory(None), Step):
        raise AssertionError("El componente dummy registrado no satisface el Protocol Step.")


def _unregister_dummy_step_if_registered() -> None:
    """Limpia el step dummy del ``REGISTRY`` global si fue registrado por tests."""
    if _DUMMY_NAME in REGISTRY.available(_DUMMY_DOMAIN):
        REGISTRY.unregister(_DUMMY_NAME, domain=_DUMMY_DOMAIN)
