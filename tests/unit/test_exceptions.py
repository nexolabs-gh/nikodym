"""Tests de la jerarquía de excepciones (SDD-01 §4): toda excepción cuelga de NikodymError."""

import pytest

from nikodym.core import exceptions as exc

# Pares (subclase, padre directo esperado) que fijan la forma del árbol.
HIERARCHY: list[tuple[type[exc.NikodymError], type[exc.NikodymError]]] = [
    (exc.ConfigError, exc.NikodymError),
    (exc.ConfigVersionError, exc.ConfigError),
    (exc.MigrationNotFoundError, exc.ConfigError),
    (exc.DataValidationError, exc.NikodymError),
    (exc.NotFittedError, exc.NikodymError),
    (exc.RegistryError, exc.NikodymError),
    (exc.UnknownComponentError, exc.RegistryError),
    (exc.DuplicateRegistrationError, exc.RegistryError),
    (exc.ArtifactNotFoundError, exc.NikodymError),
    (exc.ArtifactExistsError, exc.NikodymError),
    (exc.ReproducibilityError, exc.NikodymError),
    (exc.UntrustedStudyError, exc.NikodymError),
    (exc.RegulatoryError, exc.NikodymError),
    (exc.MissingDependencyError, exc.NikodymError),
]


@pytest.mark.parametrize(("child", "parent"), HIERARCHY)
def test_direct_parent(child: type[exc.NikodymError], parent: type[exc.NikodymError]) -> None:
    """Cada subclase tiene el padre directo esperado."""
    assert issubclass(child, parent)


@pytest.mark.parametrize("klass", [child for child, _ in HIERARCHY])
def test_all_descend_from_root(klass: type[exc.NikodymError]) -> None:
    """Toda excepción del núcleo desciende de NikodymError (regla única)."""
    assert issubclass(klass, exc.NikodymError)


def test_root_is_exception() -> None:
    """NikodymError es una Exception estándar (capturable con except NikodymError)."""
    assert issubclass(exc.NikodymError, Exception)


def test_except_root_catches_subclass() -> None:
    """``except NikodymError`` captura cualquier subclase concreta."""
    with pytest.raises(exc.NikodymError):
        raise exc.MissingDependencyError("falta el extra")


def test_all_exported_names_exist() -> None:
    """Cada nombre de ``__all__`` existe y es subclase de NikodymError."""
    for name in exc.__all__:
        obj = getattr(exc, name)
        assert issubclass(obj, exc.NikodymError)
