"""Helpers de hashing para auditoría y reproducibilidad (SDD-03 §4/§7)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from nikodym.audit.exceptions import AuditError

if TYPE_CHECKING:
    import pandas as pd

__all__ = ["hash_dataframe", "hash_file"]


class _HashLike(Protocol):
    """Mínimo contrato que usa este módulo de los objetos hash de ``hashlib``."""

    def update(self, data: bytes) -> None:
        """Alimenta bytes al digest."""
        ...

    def hexdigest(self) -> str:
        """Devuelve el digest hexadecimal."""
        ...


def hash_file(path: str | Path, *, algo: str = "sha256") -> str:
    """Calcula el hash hexadecimal de un fichero leído por bloques."""
    digest = _new_hash(algo)
    ruta = Path(path)
    try:
        with ruta.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AuditError(f"No se pudo hashear el fichero '{ruta}': {exc}") from exc
    return digest.hexdigest()


def hash_dataframe(df: pd.DataFrame, *, algo: str = "sha256") -> str:
    """Delegación perezosa al ``data_hash`` canónico de SDD-02."""
    if algo != "sha256":
        raise AuditError(
            "hash_dataframe solo soporta algo='sha256': el contrato regulatorio de "
            "data_hash lo fija SDD-02."
        )
    from nikodym.data.hashing import data_hash

    return data_hash(df)


def _new_hash(algo: str) -> _HashLike:
    """Construye el digest solicitado con error propio y mensaje en español."""
    try:
        return hashlib.new(algo)
    except ValueError as exc:
        raise AuditError(f"Algoritmo de hash no soportado para auditoría: '{algo}'.") from exc
