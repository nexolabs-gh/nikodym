"""Tests de la jerarquía de excepciones de ``tuning`` (SDD-13 §4): todo cuelga de NikodymError."""

import pytest

from nikodym.core.exceptions import NikodymError
from nikodym.tuning import exceptions as exc

# Pares (subclase, padre directo esperado) que fijan la forma del árbol (SDD-13 §4).
HIERARCHY: list[tuple[type[exc.TuningError], type[NikodymError]]] = [
    (exc.TuningError, NikodymError),
    (exc.TuningConfigError, exc.TuningError),
    (exc.TuningSearchSpaceError, exc.TuningConfigError),
    (exc.TuningDataError, exc.TuningError),
    (exc.TuningOptimizeError, exc.TuningError),
    (exc.TuningDeterminismError, exc.TuningError),
]


@pytest.mark.parametrize(("child", "parent"), HIERARCHY)
def test_direct_parent(child: type[exc.TuningError], parent: type[NikodymError]) -> None:
    assert issubclass(child, parent)


@pytest.mark.parametrize("klass", [child for child, _ in HIERARCHY])
def test_all_descend_from_root(klass: type[exc.TuningError]) -> None:
    assert issubclass(klass, NikodymError)


def test_search_space_es_config_error_transitivo() -> None:
    # TuningSearchSpaceError → TuningConfigError → TuningError → NikodymError.
    assert issubclass(exc.TuningSearchSpaceError, exc.TuningConfigError)
    assert issubclass(exc.TuningConfigError, exc.TuningError)


def test_except_root_captura_subclase() -> None:
    with pytest.raises(NikodymError):
        raise exc.TuningSearchSpaceError("espacio de búsqueda inválido")


def test_except_tuning_error_captura_subclase() -> None:
    with pytest.raises(exc.TuningError):
        raise exc.TuningOptimizeError("todos los trials fallaron")


def test_todos_los_nombres_exportados_existen() -> None:
    for name in exc.__all__:
        obj = getattr(exc, name)
        assert issubclass(obj, exc.TuningError)
