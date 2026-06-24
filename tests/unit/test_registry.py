"""Tests de ``core.registry`` (SDD-01 §6/§7): registro namespaced con auto-registro por decorador.

Usan instancias ``Registry()`` frescas para aislar; un único test verifica que la función azúcar
``register`` delega en el singleton ``REGISTRY`` (y limpia su entrada para no contaminar).
"""

from __future__ import annotations

import pytest

from nikodym.core.exceptions import DuplicateRegistrationError, UnknownComponentError
from nikodym.core.registry import REGISTRY, Registry, register


def test_register_resolve_round_trip() -> None:
    """``register`` decora sin modificar y ``resolve`` recupera la misma clase."""
    reg = Registry()

    @reg.register("logit", domain="model")
    class Logit:
        pass

    assert reg.resolve("model", "logit") is Logit


def test_resolve_desconocido_levanta() -> None:
    """``resolve`` no registrado levanta ``UnknownComponentError`` (cita domain/name)."""
    reg = Registry()
    with pytest.raises(UnknownComponentError, match=r"'logit'.*'model'"):
        reg.resolve("model", "logit")


def test_registro_duplicado_levanta() -> None:
    """Registrar dos veces ``(domain, name)`` levanta ``DuplicateRegistrationError``."""
    reg = Registry()

    @reg.register("logit", domain="model")
    class A:
        pass

    with pytest.raises(DuplicateRegistrationError, match=r"'logit'.*'model'"):

        @reg.register("logit", domain="model")
        class B:
            pass


def test_namespacing_misma_name_distintos_domains() -> None:
    """La misma ``name`` coexiste en dominios distintos (namespacing real)."""
    reg = Registry()

    @reg.register("default", domain="binning")
    class Binner:
        pass

    @reg.register("default", domain="model")
    class Model:
        pass

    assert reg.resolve("binning", "default") is Binner
    assert reg.resolve("model", "default") is Model


def test_available_lista_solo_su_domain() -> None:
    """``available(domain)`` devuelve sus ``name`` y no las de otros dominios; vacío → ``[]``."""
    reg = Registry()

    @reg.register("logit", domain="model")
    class A:
        pass

    @reg.register("gbm", domain="model")
    class B:
        pass

    @reg.register("optb", domain="binning")
    class C:
        pass

    assert reg.available("model") == ["logit", "gbm"]
    assert reg.available("binning") == ["optb"]
    assert reg.available("inexistente") == []


def test_register_azucar_delega_en_singleton() -> None:
    """La función azúcar ``register`` registra en el singleton ``REGISTRY``."""
    dominio = "__test_azucar__"

    @register("dummy", domain=dominio)
    class Dummy:
        pass

    try:
        assert REGISTRY.resolve(dominio, "dummy") is Dummy
    finally:
        del REGISTRY._registry[(dominio, "dummy")]
