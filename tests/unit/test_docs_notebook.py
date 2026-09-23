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

🔴 Y que sus salidas **sean las de hoy** (revisión adversarial del código, pasadas 1 y 2): ejecutar
sin comparar dejaba el CI verde con cifras viejas publicadas. Cada celda se ejecuta como la ejecuta
un kernel —si la última sentencia es una expresión, su valor es la salida— y lo impreso, el texto
del resultado y su HTML —que es lo que se ve al abrir el cuaderno— se comparan con lo guardado,
con las rutas relativas a la carpeta del cuaderno. Sólo se eximen las menciones del informe en PDF
y en Word, que dependen de los extras instalados y cambian entre entornos sin que el cuaderno esté
viejo, y el hash del archivo de entrada copiado.

El cuaderno termina exportando los once libros de Excel, así que su ejecución exige `openpyxl`:
corre en el job del CI con todos los extras y en la máquina de desarrollo, no en la matriz, que
instala sólo `scoring`.
"""

from __future__ import annotations

import ast
import contextlib
import io
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
#: Menciones que dependen de los extras instalados —el informe en PDF y en Word—: varían entre
#: entornos sin que el cuaderno esté viejo. Aparecen como línea impresa, como par del `repr` del
#: resumen final, como cadena dentro del `repr` de un resumen de etapa y como ítem del HTML.
_MENCIONES_DEL_ENTORNO = (
    re.compile(r"^[ \t]*Informe (?:PDF|Word):.*$", re.M),
    re.compile(r"\('Informe (?:PDF|Word)', '[^']*'\),? ?"),
    re.compile(r"'Informe (?:PDF|Word): [^']*',? ?"),
    re.compile(r"<li>Informe (?:PDF|Word): .*?</li>"),
)
#: El nombre de la copia de entrada lleva el hash del archivo, que depende del escritor de parquet.
_HASH_DE_ENTRADA = re.compile(r"data-[0-9a-f]{16}")


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


def _ejecutar_como_un_kernel(codigo: str, espacio: dict[str, Any], nombre: str) -> tuple[str, Any]:
    """Lo impreso por la celda y el valor de su última expresión, como en jupyter."""
    arbol = ast.parse(codigo)
    ultima = arbol.body.pop() if arbol.body else None
    impreso = io.StringIO()
    valor: Any = None
    with contextlib.redirect_stdout(impreso):
        if arbol.body:
            exec(compile(arbol, nombre, "exec"), espacio)
        if isinstance(ultima, ast.Expr):
            valor = eval(compile(ast.Expression(ultima.value), nombre, "eval"), espacio)
        elif ultima is not None:
            exec(compile(ast.Module([ultima], []), nombre, "exec"), espacio)
    return impreso.getvalue(), valor


def _comparable(texto: str, raices: tuple[Path, ...]) -> list[str]:
    """Relativo a la carpeta del cuaderno, con una sola barra, sin las líneas del entorno."""
    barra = chr(92)
    prefijos: set[str] = set()
    for raiz in raices:
        for base in (str(raiz), str(raiz).replace(barra, "/")):
            for sep in (barra, "/"):
                prefijos |= {base + sep, (base + sep).replace(barra, barra + barra)}
    for prefijo in sorted(prefijos, key=len, reverse=True):
        texto = texto.replace(prefijo, "")
    texto = _HASH_DE_ENTRADA.sub(
        "data-<hash>", texto.replace(barra + barra, "/").replace(barra, "/")
    )
    for mencion in _MENCIONES_DEL_ENTORNO:
        texto = mencion.sub("", texto)
    return [linea.rstrip() for linea in texto.splitlines() if linea.strip()]


def _guardado(salidas: list[dict[str, Any]], tipo: str, formato: str = "text/plain") -> str | None:
    for salida in salidas:
        if salida["output_type"] != tipo:
            continue
        if tipo == "stream":
            return "".join(salida["text"])
        return "".join(salida["data"][formato]) if formato in salida["data"] else None
    return None


def test_el_cuaderno_corre_de_punta_a_punta_y_publica_las_salidas_de_hoy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 El gate que Cami pidió: el cuaderno publicado se ejecuta entero, celda por celda, y cada
    salida guardada es la que produce hoy."""
    pytest.importorskip("optbinning")
    pytest.importorskip("openpyxl")
    pytest.importorskip("docx")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    raices = (tmp_path, tmp_path.resolve())
    espacio: dict[str, Any] = {"__name__": "__main__"}
    celdas = [c for c in _cuaderno()["cells"] if c["cell_type"] == "code"]
    for numero, celda in enumerate(celdas, start=1):
        impreso, valor = _ejecutar_como_un_kernel(
            "".join(celda["source"]), espacio, f"{_CUADERNO.name}#celda{numero}"
        )
        guardado = _guardado(celda["outputs"], "stream")
        assert _comparable(impreso, raices) == _comparable(guardado or "", raices), (
            f"celda {numero}: lo impreso cambió; regenera el cuaderno"
        )
        guardado = _guardado(celda["outputs"], "execute_result")
        if valor is None:
            assert guardado is None, f"celda {numero}: guarda un resultado que ya no produce"
            continue
        assert guardado is not None, f"celda {numero}: produce un resultado que no guarda"
        assert _comparable(repr(valor), raices) == _comparable(guardado, raices), (
            f"celda {numero}: su resultado cambió; regenera el cuaderno"
        )
        html = getattr(valor, "_repr_html_", None)
        html_guardado = _guardado(celda["outputs"], "execute_result", "text/html")
        assert (html_guardado is None) == (not callable(html)), (
            f"celda {numero}: el HTML guardado no corresponde al resultado de hoy"
        )
        if callable(html):
            assert _comparable(str(html()), raices) == _comparable(html_guardado or "", raices), (
                f"celda {numero}: su HTML cambió; regenera el cuaderno"
            )

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
