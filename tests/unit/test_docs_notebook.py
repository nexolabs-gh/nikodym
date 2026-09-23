"""El cuaderno publicado `docs_site/notebooks/primer-scorecard.ipynb` corre de verdad, en cada CI.

Decisión de Cami del 2026-09-23 (interactiva): el notebook del criterio de completado del scorecard
vive en `docs_site/notebooks/`, se publica en docs.nikodym.cl y **se ejecuta en CI**, para que sus
salidas no puedan quedar viejas sin que nada lo acuse.

Se ejecuta **sin jupyter**: el `.ipynb` es JSON, sus celdas de código son Python plano y se
corren en orden en un mismo espacio de nombres —que es lo que hace un kernel—, con el directorio de
trabajo dentro de `tmp_path`. Así el gate no añade `nbclient`, `nbformat` ni `ipykernel` a las
dependencias de desarrollo y mide lo mismo: que el cuaderno llega hasta el final.

Tres cosas más que un cuaderno publicado tiene que cumplir, y que un test de «corre» no vería:
que su flujo no se aparte del notebook mínimo que publican las guías, que no traiga una celda en
error y que no filtre rutas de la máquina en la que se generó.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_CUADERNO = _RAIZ / "docs_site" / "notebooks" / "primer-scorecard.ipynb"
_GUIA = _RAIZ / "docs_site" / "getting-started.md"
_BLOQUE = "primer-scorecard"
_TOPE_LINEAS_DE_USUARIO = 25


def _cuaderno() -> dict[str, Any]:
    return json.loads(_CUADERNO.read_text(encoding="utf-8"))


def _celdas_de_codigo() -> list[str]:
    return [
        "".join(celda["source"]) for celda in _cuaderno()["cells"] if celda["cell_type"] == "code"
    ]


def _lineas_de_usuario(codigo: str) -> list[str]:
    return [
        linea.split("#", 1)[0].rstrip()
        for linea in codigo.splitlines()
        if linea.strip() and not linea.lstrip().startswith("#")
    ]


def _bloque_de_la_guia() -> str:
    texto = _GUIA.read_text(encoding="utf-8")
    inicio = f"<!-- {_BLOQUE}:start -->\n```python\n"
    fin = f"\n```\n<!-- {_BLOQUE}:end -->"
    assert texto.count(inicio) == 1 and texto.count(fin) == 1
    return texto.split(inicio, maxsplit=1)[1].split(fin, maxsplit=1)[0]


def test_el_cuaderno_es_un_notebook_valido_con_salidas_y_sin_errores() -> None:
    """nbformat 4, cada celda de código con su salida y ninguna salida de error."""
    cuaderno = _cuaderno()
    assert cuaderno["nbformat"] == 4
    codigo = [c for c in cuaderno["cells"] if c["cell_type"] == "code"]
    assert codigo, "un cuaderno sin celdas de código no ejecuta nada"
    for celda in codigo:
        assert celda["outputs"], f"celda {celda['execution_count']} sin salida: no se ejecutó"
        for salida in celda["outputs"]:
            assert salida["output_type"] != "error", f"celda {celda['execution_count']} en error"
            assert "Traceback" not in "".join(salida.get("text", [])), (
                f"celda {celda['execution_count']} publica un traceback"
            )


def test_el_cuaderno_no_filtra_rutas_de_la_maquina_que_lo_genero() -> None:
    """El repo es público: ni el usuario ni las carpetas de la máquina de quien lo generó."""
    texto = _CUADERNO.read_text(encoding="utf-8")
    barra = chr(92)
    for rastro in (f"Users{barra}", "Users/", "AppData", "OneDrive", "/home/", "/tmp/"):
        assert rastro not in texto, rastro


def test_el_flujo_del_cuaderno_es_el_notebook_minimo_de_las_guias() -> None:
    """Cada línea del notebook mínimo publicado aparece en el cuaderno, en el mismo orden.

    El cuaderno añade celdas —mirar una etapa, el resumen, el Excel—, pero no puede apartarse del
    flujo canónico: si alguien cambia el bloque de las guías y no el cuaderno, esto se pone rojo.
    """
    esperado = _lineas_de_usuario(_bloque_de_la_guia())
    presente = _lineas_de_usuario("\n".join(_celdas_de_codigo()))
    posicion = 0
    for linea in esperado:
        assert linea in presente[posicion:], f"falta o está fuera de orden: {linea!r}"
        posicion = presente.index(linea, posicion) + 1


def test_el_cuaderno_cabe_en_el_tope_de_lineas_de_usuario() -> None:
    """D-SIM-8: un cuaderno que crece sin tope deja de ser el mínimo."""
    lineas = _lineas_de_usuario("\n".join(_celdas_de_codigo()))
    assert len(lineas) <= _TOPE_LINEAS_DE_USUARIO, len(lineas)


def test_el_cuaderno_corre_de_punta_a_punta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 El gate que Cami pidió: el cuaderno publicado se ejecuta entero, celda por celda."""
    pytest.importorskip("optbinning")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    espacio: dict[str, Any] = {"__name__": "__main__"}
    for numero, codigo in enumerate(_celdas_de_codigo(), start=1):
        exec(compile(codigo, f"{_CUADERNO.name}#celda{numero}", "exec"), espacio)

    sc = espacio["sc"]
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert sc.summary().execution == "completada"
    proyecto = tmp_path / "nikodym-runs" / "consumo_v01"
    assert (proyecto / "reports" / "scorecard_report.html").is_file()
    libros = sorted((proyecto / "excel").glob("*.xlsx"))
    assert len(libros) == 11, [libro.name for libro in libros]


def test_la_guia_enlaza_el_cuaderno() -> None:
    """Un cuaderno que ninguna página enlaza existe sólo para quien ya sabe que existe."""
    texto = _GUIA.read_text(encoding="utf-8")
    assert re.search(r"\]\(notebooks/primer-scorecard\.ipynb\)", texto), (
        "getting-started.md no enlaza notebooks/primer-scorecard.ipynb"
    )
