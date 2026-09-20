"""Las cinco cifras de simplicidad del scorecard (SDD-31 D-SIM-11, §5; enmienda §13).

Cada cifra es un golden con la misma regla que ``HOJAS_DEL_FORMULARIO``: moverla es legítimo,
moverla sin actualizar el número y decir por qué, no. Línea base medida sobre ``7364a09`` el
2026-09-19, antes de escribir la capa A (``%TEMP%\\nkr\\s17\\antes-7364a09\\cifras.json``):

| Cifra | Antes (quickstart del preset) | Después (notebook mínimo) | Objetivo |
|---|---|---|---|
| Líneas de usuario | 17 (y 83 + ~60 en la Clase 6) | 15 | ≤ 25 |
| Esenciales visibles a la vez, por sección | todos (409 en 12) | 35 (máx. 6) | ≤ 6 por sección |
| Perillas de las doce secciones | 409 | 409 | sin crecer |
| Segundos hasta el primer resumen | sin resumen (9,9 s a ``done``) | ≈ 1 s (datos) | ≤ 30 s |
| Conceptos antes del primer resultado | 11 | 5 | ≤ 5 |
"""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path
from typing import Final

import pytest
from test_copy_del_formulario import _campos_visibles
from test_esenciales_por_seccion import ESENCIALES_VISIBLES_A_LA_VEZ, TOPE_ESENCIALES_POR_SECCION

_DOCS = Path(__file__).resolve().parents[2] / "docs_site"
_BLOQUE = "primer-scorecard"

#: Cifra 1: líneas de usuario del notebook mínimo (sin vacías ni comentarios). Tope de Cami
#: (SDD-31 §12.2): 25. 15 el 2026-09-19 (capa A2: construir, correr, una decisión y `resume`).
LINEAS_DE_USUARIO: Final = 15
TOPE_LINEAS_DE_USUARIO: Final = 25

#: Cifra 5: identificadores de `nikodym` que el notebook obliga a conocer —lo que se importa de
#: `nikodym` y los métodos que se llaman sobre sus objetos—. 5 el 2026-09-19: `Scorecard`,
#: `materialize`, `run`, `exclude`, `resume`. Tope: 5 (SDD-31 §5).
CONCEPTOS: Final[frozenset[str]] = frozenset(
    {"Scorecard", "materialize", "run", "exclude", "resume"}
)
TOPE_CONCEPTOS: Final = 5

#: Cifra 3: perillas de las doce secciones que tocan los dos trabajos del scorecard, con el
#: barrido de `test_copy_del_formulario._campos_visibles`. 409 el 2026-09-15 y el 2026-09-19:
#: la capa A no añade ni retira hojas (D-FLU-12).
SECCIONES_DEL_SCORECARD: Final[tuple[str, ...]] = (
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
    "report",
    "governance",
)
PERILLAS_DE_LAS_DOCE_SECCIONES: Final = 409

#: Cifra 4: segundos hasta el primer resumen (el de «Datos y muestras») con el dataset del
#: paquete. Medido el 2026-09-19 en el entorno de referencia: 1,0 s; la corrida completa, 10,2 s.
TOPE_SEGUNDOS_PRIMER_RESUMEN: Final = 30.0


def _notebook() -> str:
    texto = (_DOCS / "getting-started.md").read_text(encoding="utf-8")
    inicio = f"<!-- {_BLOQUE}:start -->\n```python\n"
    fin = f"\n```\n<!-- {_BLOQUE}:end -->"
    assert texto.count(inicio) == 1 and texto.count(fin) == 1
    return texto.split(inicio, 1)[1].split(fin, 1)[0]


def _lineas_de_usuario(codigo: str) -> list[str]:
    return [ln for ln in codigo.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _conceptos(codigo: str) -> set[str]:
    """Lo importado de `nikodym` más los métodos llamados sobre los objetos que devuelve."""
    importados: set[str] = set()
    for grupo in re.findall(r"^from nikodym[\w.]* import (.+)$", codigo, flags=re.M):
        importados.update(nombre.strip() for nombre in grupo.split(","))
    metodos = set(re.findall(r"\bsc\.(\w+)\(", codigo))
    return importados | metodos


def test_cifra_1_lineas_de_usuario_del_notebook_minimo() -> None:
    lineas = _lineas_de_usuario(_notebook())
    assert len(lineas) == LINEAS_DE_USUARIO, lineas
    assert len(lineas) <= TOPE_LINEAS_DE_USUARIO


def test_cifra_5_conceptos_antes_del_primer_resultado() -> None:
    conceptos = _conceptos(_notebook())
    assert conceptos == set(CONCEPTOS), conceptos
    assert len(conceptos) <= TOPE_CONCEPTOS


def test_cifra_2_esenciales_por_seccion_bajo_el_tope() -> None:
    assert set(ESENCIALES_VISIBLES_A_LA_VEZ) == set(SECCIONES_DEL_SCORECARD)
    assert sum(ESENCIALES_VISIBLES_A_LA_VEZ.values()) == 35
    assert max(ESENCIALES_VISIBLES_A_LA_VEZ.values()) <= TOPE_ESENCIALES_POR_SECCION


def test_cifra_3_las_perillas_de_las_doce_secciones_no_crecen() -> None:
    por_seccion = Counter(ruta.split(".", 1)[0] for ruta, _ in _campos_visibles())
    total = sum(por_seccion[s] for s in SECCIONES_DEL_SCORECARD)
    assert total == PERILLAS_DE_LAS_DOCE_SECCIONES, dict(por_seccion)


def test_cifra_4_el_primer_resumen_llega_antes_de_treinta_segundos(tmp_path: Path) -> None:
    """Sobre el dataset del paquete, con el motor real (exige el extra `scoring`)."""
    pytest.importorskip("optbinning")
    from nikodym import Scorecard
    from nikodym.ui.datasets import materialize

    datos = materialize("consumo_comportamiento", workdir=tmp_path / "datasets")
    t0 = time.perf_counter()
    sc = Scorecard(
        datos,
        target="bad_flag",
        id="loan_id",
        cohort="cohorte",
        oot_cohorts=["2024Q2"],
        run_dir=tmp_path / "corridas",
    )
    marcas: list[float] = []
    sc._echo = lambda _texto: marcas.append(time.perf_counter() - t0)
    sc.run(until="data")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert marcas, "la etapa de datos no contó nada"
    assert marcas[0] <= TOPE_SEGUNDOS_PRIMER_RESUMEN, marcas[0]
