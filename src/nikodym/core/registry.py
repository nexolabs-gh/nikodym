"""Registro namespaced de componentes de Nikodym (SDD-01 §4/§6/§7).

El :class:`Registry` mapea una pareja ``(domain, name)`` a la **clase** de un componente, donde
``domain`` es el nombre de la sección de config y ``name`` es el discriminador ``type`` de la unión
discriminada (D-CONV-2). Los dominios se auto-registran al importarse con el decorador
:func:`register` (azúcar sobre el singleton :data:`REGISTRY`); una colisión ``(domain, name)`` se
detecta en *import time* (:class:`~nikodym.core.exceptions.DuplicateRegistrationError`). El registro
es *namespaced*: la misma ``name`` puede coexistir en dominios distintos.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from nikodym.core.exceptions import DuplicateRegistrationError, UnknownComponentError

__all__ = ["REGISTRY", "Registry", "register", "unregister"]

T = TypeVar("T")


class Registry:
    """Tabla *namespaced* ``(domain, name) → type`` con auto-registro por decorador.

    El estado interno (``_registry``) no forma parte de la API pública. La pareja ``(domain, name)``
    es única; ``resolve`` la recupera y ``available`` lista las ``name`` de un dominio.
    """

    def __init__(self) -> None:
        self._registry: dict[tuple[str, str], type] = {}

    def register(self, name: str, *, domain: str) -> Callable[[type[T]], type[T]]:
        """Devuelve un decorador que registra la clase bajo ``(domain, name)`` y la devuelve igual.

        Una pareja ``(domain, name)`` ya presente levanta
        :class:`~nikodym.core.exceptions.DuplicateRegistrationError` (detectado en *import time*).
        """

        def decorador(cls: type[T]) -> type[T]:
            clave = (domain, name)
            if clave in self._registry:
                raise DuplicateRegistrationError(
                    f"Componente '{name}' ya registrado en el dominio '{domain}'; "
                    "cada pareja (domain, name) debe ser única."
                )
            self._registry[clave] = cls
            return cls

        return decorador

    def resolve(self, domain: str, name: str) -> type:
        """Devuelve la clase registrada bajo ``(domain, name)``.

        Una pareja no registrada levanta :class:`~nikodym.core.exceptions.UnknownComponentError`,
        citando el dominio, el nombre y los disponibles.
        """
        clave = (domain, name)
        if clave not in self._registry:
            raise UnknownComponentError(
                f"No hay componente '{name}' en el dominio '{domain}'. "
                f"Disponibles: {self.available(domain)}."
            )
        return self._registry[clave]

    def unregister(self, name: str, *, domain: str) -> None:
        """Elimina la clase registrada bajo ``(domain, name)``.

        Una pareja ausente levanta :class:`~nikodym.core.exceptions.UnknownComponentError`, en
        vez de comportarse como no-op, para mantener la misma semántica ruidosa de ``resolve``:
        pedir un componente inexistente es un error de contrato. Los cleanup donde la ausencia sea
        esperada deben comprobar ``available(domain)`` antes de llamar a este método.
        """
        clave = (domain, name)
        if clave not in self._registry:
            raise UnknownComponentError(
                f"No hay componente '{name}' en el dominio '{domain}' para desregistrar. "
                f"Disponibles: {self.available(domain)}."
            )
        del self._registry[clave]

    def available(self, domain: str) -> list[str]:
        """Lista las ``name`` registradas bajo ``domain`` (orden de inserción); ``[]`` si no hay."""
        return [name for (dom, name) in self._registry if dom == domain]


REGISTRY = Registry()


def register(name: str, *, domain: str) -> Callable[[type[T]], type[T]]:
    """Azúcar de módulo: registra en el singleton :data:`REGISTRY`.

    Es la forma que usan los dominios: ``@register("logit", domain="model")``.
    """
    return REGISTRY.register(name, domain=domain)


def unregister(name: str, *, domain: str) -> None:
    """Azúcar de módulo: elimina una entrada del singleton :data:`REGISTRY`."""
    REGISTRY.unregister(name, domain=domain)
