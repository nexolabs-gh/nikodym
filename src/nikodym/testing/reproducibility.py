"""Asserts públicos de reproducibilidad bit a bit (SDD-24)."""

from __future__ import annotations

import pickle
from collections.abc import Callable
from typing import Any

__all__ = ["assert_bitwise_reproducible"]


def assert_bitwise_reproducible(
    run: Callable[[], Any],
    *,
    normalize: Callable[[Any], Any] | None = None,
) -> None:
    """Ejecuta ``run`` dos veces y asevera igualdad bit a bit del resultado.

    ``normalize`` permite retirar campos legítimamente no deterministas, como timestamps de
    lineage, antes de serializar ambos resultados. La comparación asume estructuras con orden de
    iteración determinista; úsalo para canonicalizar payloads que ``pickle`` no pueda ordenar por sí
    mismo.
    """
    first = run()
    second = run()
    if normalize is not None:
        first = normalize(first)
        second = normalize(second)
    first_bytes = _canonical_bytes(first)
    second_bytes = _canonical_bytes(second)
    if first_bytes != second_bytes:
        raise AssertionError(
            "La corrida no es bit a bit reproducible: las dos ejecuciones produjeron bytes "
            f"distintos (len1={len(first_bytes)}, len2={len(second_bytes)})."
        )


def _canonical_bytes(value: Any) -> bytes:
    """Serializa ``value`` con pickle protocolo 5 para la comparación interna.

    ``pickle`` no garantiza una representación canónica para estructuras cuyo orden de iteración
    puede variar, como ``set``/``frozenset`` o diccionarios construidos con órdenes distintos. Dos
    objetos semánticamente iguales pueden producir bytes distintos; en esos casos, quien llama debe
    pasar ``normalize`` a ``assert_bitwise_reproducible``.
    """
    try:
        return pickle.dumps(value, protocol=5)
    except Exception as exc:
        raise AssertionError(
            "No se pudo serializar el resultado para comparar reproducibilidad bit a bit: "
            f"{type(exc).__name__}: {exc}."
        ) from exc
