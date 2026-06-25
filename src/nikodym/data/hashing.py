"""Hash reproducible del contenido lógico tabular (SDD-02 D-DATA-2).

``data_hash`` no hashea bytes de CSV/Parquet: calcula un ``sha256`` sobre un encabezado de
esquema canónico y sobre los hashes vectorizados de pandas por bloques. La función ordena columnas
e índice internamente, y trabaja sobre una copia para no mutar el ``DataFrame`` recibido.

Ratificación B2b.3: fijar el orden estable por índice mediante ``sort_index`` agrega un coste
``O(n log n)`` al preprocesamiento respecto del pseudocódigo ``O(n)`` del SDD-02 §7. Se acepta
porque el índice es el identificador regulatorio de observación y la invariancia ante permutaciones
de filas importa más que evitar ese ordenamiento.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import hashlib
from typing import Final

import pandas as pd
from pandas.util import hash_pandas_object

__all__ = ["data_hash"]

_PANDAS_HASH_KEY: Final = "0123456789123456"
_PANDAS_HASH_ENCODING: Final = "utf8"
_PANDAS_HASH_CATEGORIZE: Final = True
_SCHEMA_HEADER_PREFIX: Final = "nikodym.data_hash.v1"


def data_hash(df: pd.DataFrame, *, block_size: int = 1_000_000) -> str:
    """Calcula el ``sha256`` del contenido lógico de un ``DataFrame``.

    El contrato sigue D-DATA-2: columnas en orden canónico, filas en orden estable de índice,
    encabezado de esquema antes de los datos y ``hash_pandas_object(index=True)`` por bloques. Los
    bytes de los hashes se fuerzan a ``<u8`` para que el resultado sea estable entre arquitecturas
    little/big-endian, y las columnas float normalizan ``-0.0`` a ``0.0`` antes de hashear.

    Parameters
    ----------
    df : pandas.DataFrame
        Dataset validado que se quiere anclar en lineage.
    block_size : int, default=1_000_000
        Número de filas por bloque al alimentar el ``sha256``.

    Returns
    -------
    str
        Digest hexadecimal de 64 caracteres.

    Raises
    ------
    ValueError
        Si ``block_size`` es menor que 1.
    """
    if block_size < 1:
        raise ValueError("block_size debe ser mayor o igual a 1.")

    frame = _canonical_frame(df)
    digest = hashlib.sha256()
    digest.update(_schema_header(frame))

    for start in range(0, len(frame), block_size):
        block = frame.iloc[start : start + block_size]
        block_hashes = hash_pandas_object(
            block,
            index=True,
            encoding=_PANDAS_HASH_ENCODING,
            hash_key=_PANDAS_HASH_KEY,
            categorize=_PANDAS_HASH_CATEGORIZE,
        ).to_numpy(dtype="<u8", copy=True)
        digest.update(block_hashes.tobytes())

    return digest.hexdigest()


def _canonical_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una copia con columnas/filas en orden canónico y floats normalizados."""
    columns = sorted(df.columns)
    frame = df.loc[:, columns].copy(deep=True).sort_index(kind="mergesort")

    for column in frame.columns:
        if pd.api.types.is_float_dtype(frame[column].dtype):
            frame[column] = frame[column] + 0.0
    return frame


def _schema_header(frame: pd.DataFrame) -> bytes:
    """Serializa el esquema de columnas de forma determinista para el prefijo del hash."""
    lines = [_SCHEMA_HEADER_PREFIX]
    lines.extend(f"{column}\t{dtype}" for column, dtype in frame.dtypes.items())
    lines.append("")
    return "\n".join(lines).encode("utf-8")
