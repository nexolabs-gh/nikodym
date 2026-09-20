"""Proyección canónica de una corrida, sin procedencia (enmienda FLUJO-GUIADO-SCORECARD §6-4).

NO es un módulo de test (el prefijo ``_`` lo excluye de la colección de pytest): es el helper que
comparan los gates de paridad computacional —``run()`` frente a ``run(until=) + resume()``, y la
corrida F1 del preset antes y después de una capa— y el que la línea base de S17 usó para
congelar los artefactos sobre ``7364a09``.

Qué proyecta: ``study.results`` (métricas planas y secciones) y los artefactos de los dominios de
**cálculo** —``eda``, ``binning``, ``selection``, ``model``, ``scorecard``, ``calibration``,
``performance``, ``stability``, ``validation`` y ``data``—, serializados sin los campos de
procedencia. ``report`` y ``audit`` quedan fuera: sus artefactos llevan rutas, sellos y el
``run_id``, que son justamente lo que dos corridas distintas del mismo config **no** comparten.

Cómo proyecta: cada valor se reduce a un objeto JSON-able estable —los ``DataFrame`` a un hash de
su contenido lógico (``hash_pandas_object`` sobre índice y celdas, más columnas y dtypes), los
``float`` a su representación hexadecimal exacta (bit a bit, no «parecido»), los modelos Pydantic
a su volcado recursivo, los estimadores a su tipo—. Un aserto sobre dos proyecciones iguales es
por tanto un aserto de igualdad bit a bit de todo lo que la corrida calculó.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

#: Dominios cuyo resultado es cálculo y por tanto entra a la comparación.
DOMINIOS_DE_CALCULO: tuple[str, ...] = (
    "data",
    "eda",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    "validation",
)

#: Claves de procedencia que se descartan a cualquier profundidad: identifican la corrida, no el
#: cálculo. ``source`` es el nombre del archivo de datos —la puerta guiada persiste un snapshot con
#: otro nombre—; ``data_hash`` NO está aquí a propósito, porque el mismo dato debe dar el mismo
#: hash por las dos puertas y esa igualdad es parte de lo que se comprueba.
CLAVES_DE_PROCEDENCIA: frozenset[str] = frozenset(
    {
        "run_id",
        "created_at",
        "created_from_lineage_at",
        "started_at",
        "finished_at",
        "ts",
        "timestamp",
        "lineage",
        "git_sha",
        "git_dirty",
        "path",
        "paths",
        "output_dir",
        "html_path",
        "source",
        "environment",
        "library_versions",
        "dependency_versions",
        "uv_lock_hash",
        "runtime_environment_hash",
    }
)


def proyeccion_canonica(study: Any) -> dict[str, Any]:
    """Proyecta ``study.results`` y los artefactos de cálculo a un objeto JSON-able estable."""
    artefactos: dict[str, Any] = {}
    for dominio, clave in sorted(study.artifacts.keys()):
        if dominio not in DOMINIOS_DE_CALCULO:
            continue
        artefactos[f"{dominio}.{clave}"] = canonizar(study.artifacts.get(dominio, clave))
    return {"results": canonizar(study.results), "artifacts": artefactos}


def canonizar(valor: Any) -> Any:
    """Reduce ``valor`` a un objeto JSON-able estable, sin procedencia (ver el módulo)."""
    if valor is None or isinstance(valor, bool | str):
        return valor
    if isinstance(valor, int) and not isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, float):
        return _float_exacto(valor)
    if isinstance(valor, np.floating):
        return _float_exacto(float(valor))
    if isinstance(valor, np.integer):
        return int(valor)
    if isinstance(valor, np.bool_):
        return bool(valor)
    if isinstance(valor, Enum):
        return canonizar(valor.value)
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    if isinstance(valor, Path):
        return "<ruta>"
    if isinstance(valor, pd.DataFrame):
        return _hash_frame(valor)
    if isinstance(valor, pd.Series):
        return _hash_frame(valor.to_frame())
    if isinstance(valor, pd.Index):
        return _hash_frame(valor.to_frame(index=False))
    if isinstance(valor, np.ndarray):
        return {
            "__ndarray__": hashlib.sha256(np.ascontiguousarray(valor).tobytes()).hexdigest(),
            "dtype": str(valor.dtype),
            "shape": list(valor.shape),
        }
    if isinstance(valor, BaseModel):
        return canonizar(valor.model_dump(mode="python"))
    if isinstance(valor, Mapping):
        return {
            str(k): canonizar(v)
            for k, v in sorted(valor.items(), key=lambda kv: str(kv[0]))
            if str(k) not in CLAVES_DE_PROCEDENCIA
        }
    if isinstance(valor, list | tuple | set | frozenset):
        items = sorted(valor, key=str) if isinstance(valor, set | frozenset) else list(valor)
        return [canonizar(v) for v in items]
    # Estimadores y objetos opacos (el binner de OptBinning, el modelo de statsmodels): su cálculo
    # ya viaja en las tablas y coeficientes; aquí sólo se fija el tipo.
    return {"__tipo__": f"{type(valor).__module__}.{type(valor).__qualname__}"}


def _float_exacto(valor: float) -> str:
    if valor != valor:  # NaN no es igual a sí mismo; se representa de forma estable
        return "nan"
    return valor.hex()


def _hash_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """Hash del contenido lógico del frame: índice, celdas, columnas y dtypes.

    Las celdas de tipo objeto que no son hashables —las tablas de binning guardan los cortes de un
    tramo como ``ndarray``— se reducen a su representación canónica antes de hashear.
    """
    estable = frame.copy(deep=False)
    for columna in estable.columns:
        if pd.api.types.is_object_dtype(estable[columna].dtype):
            estable[columna] = estable[columna].map(_celda_estable)
    hashes = pd.util.hash_pandas_object(estable, index=True).to_numpy()
    digest = hashlib.sha256(np.ascontiguousarray(hashes).tobytes()).hexdigest()
    return {
        "__frame__": digest,
        "columns": [str(c) for c in frame.columns],
        "dtypes": [str(t) for t in frame.dtypes],
        "n_rows": len(frame.index),
    }


def _celda_estable(valor: Any) -> Any:
    """Una celda de tipo objeto hashable y estable: ``ndarray``/listas/tuplas a texto canónico."""
    if isinstance(valor, np.ndarray):
        return json.dumps(canonizar(valor.tolist()), sort_keys=True)
    if isinstance(valor, list | tuple | dict | set | frozenset):
        return json.dumps(canonizar(valor), sort_keys=True)
    if isinstance(valor, float):
        return _float_exacto(valor)
    return valor


def volcar(proyeccion: dict[str, Any]) -> str:
    """JSON canónico de una proyección (claves ordenadas, sin espacios variables)."""
    return json.dumps(proyeccion, ensure_ascii=False, sort_keys=True, indent=1)


def diferencias(a: dict[str, Any], b: dict[str, Any], *, prefijo: str = "") -> list[str]:
    """Rutas en las que dos proyecciones difieren, para un mensaje de aserto legible."""
    if isinstance(a, dict) and isinstance(b, dict):
        salida: list[str] = []
        for clave in sorted(set(a) | set(b)):
            ruta = f"{prefijo}.{clave}" if prefijo else clave
            if clave not in a or clave not in b:
                salida.append(f"{ruta}: sólo en {'la segunda' if clave not in a else 'la primera'}")
            else:
                salida.extend(diferencias(a[clave], b[clave], prefijo=ruta))
        return salida
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{prefijo}: {len(a)} frente a {len(b)} elementos"]
        salida = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            salida.extend(diferencias(x, y, prefijo=f"{prefijo}[{i}]"))
        return salida
    return [] if a == b else [f"{prefijo}: {a!r} != {b!r}"]
