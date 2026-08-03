"""Tests del import perezoso de extras (SDD-25 §4, §11)."""

import tomllib
from pathlib import Path

import pytest

from nikodym.core.exceptions import MissingDependencyError
from nikodym.utils import optional

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_require_extra_returns_imported_modules() -> None:
    """``require_extra`` devuelve los módulos importados, en orden."""
    json_mod, math_mod = optional.require_extra("base", "json", "math")
    assert json_mod.__name__ == "json"
    assert math_mod.__name__ == "math"


def test_require_extra_missing_raises_with_install_hint() -> None:
    """Un módulo ausente levanta MissingDependencyError con la línea de instalación del extra."""
    with pytest.raises(MissingDependencyError, match=r"nikodym\[xgboost\]"):
        optional.require_extra("xgboost", "modulo_que_no_existe_xyz")


def test_has_extra_true_when_present() -> None:
    """``has_extra`` es True si todos los módulos están importables."""
    assert optional.has_extra("base", "json") is True


def test_has_extra_false_when_absent() -> None:
    """``has_extra`` es False (no levanta) si falta un módulo."""
    assert optional.has_extra("xgboost", "modulo_que_no_existe_xyz") is False


def test_extra_map_keys_are_known_extras() -> None:
    """El mapa de extras cubre los extras de usuario esperados (sin 'all')."""
    assert "all" not in optional.EXTRA_TO_DISTRIBUTIONS
    assert "scoring" in optional.EXTRA_TO_DISTRIBUTIONS
    assert optional.EXTRA_TO_DISTRIBUTIONS["scoring"] == ("optbinning", "statsmodels", "sklearn")


def test_extra_map_keys_son_extras_reales_del_pyproject() -> None:
    """Toda clave del mapa es un extra de usuario declarado en el pyproject (sin claves fantasma).

    Nota: la relación es ⊆, no biyección exacta: ``ai``/``report`` viven en el pyproject pero no
    gatean vía ``require_extra`` (sus imports son perezosos en otras capas), por lo que no tienen
    fila en el mapa. Esa asimetría es pre-existente a B23.2 y ortogonal a la migración de ``ui``.
    """
    with _PYPROJECT.open("rb") as handle:
        pyproject = tomllib.load(handle)
    extras = set(pyproject["project"]["optional-dependencies"]) - {"all"}
    assert set(optional.EXTRA_TO_DISTRIBUTIONS) <= extras
    assert "ui" in extras and "ui" in optional.EXTRA_TO_DISTRIBUTIONS


def test_extra_ui_mapea_a_fastapi_y_uvicorn() -> None:
    """El extra ``ui`` (SDD-23, B23.2) resuelve los módulos ``fastapi`` y ``uvicorn``."""
    assert optional.EXTRA_TO_DISTRIBUTIONS["ui"] == ("fastapi", "uvicorn")


# ─────────────── La matriz de extras de la documentación ───────────────
#
# `docs_site/getting-started.md` promete en su encabezado que los nombres de su matriz son
# «exactamente los declarados en `[project.optional-dependencies]`». Era una afirmación falsable y
# estaba siendo falsa: publicaba 16 de los 19, sin `markov`, `docx` ni `pdf`.
#
# 🔴 El gate va en los DOS sentidos a propósito. Un extra sin fila deja al usuario sin saber que
# existe una capacidad instalable —que es la definición de «feature gateada» de este repo—, y una
# fila sin extra le hace escribir un `pip install` que falla. Ninguna de las dos direcciones la
# cazaba nada: `test_extra_map_keys_son_extras_reales_del_pyproject` mide la relación con
# `EXTRA_TO_DISTRIBUTIONS`, que es ⊆ y no toca la documentación.

_DOCS_GETTING_STARTED = Path(__file__).resolve().parents[2] / "docs_site" / "getting-started.md"


def _extras_del_pyproject() -> set[str]:
    with _PYPROJECT.open("rb") as handle:
        return set(tomllib.load(handle)["project"]["optional-dependencies"])


def _extras_de_la_matriz() -> set[str]:
    """Los extras que la matriz de la documentación enumera, leídos de la primera celda.

    Se lee del archivo y NO de una lista escrita al lado: un oráculo derivado de lo que vigila no
    mediría nada. La primera celda de cada fila es ``| `nombre` |``.
    """
    texto = _DOCS_GETTING_STARTED.read_text(encoding="utf-8")
    inicio = texto.index("### Matriz de extras")
    fin = texto.index("Puedes combinar extras", inicio)
    nombres = set()
    for linea in texto[inicio:fin].splitlines():
        if not linea.startswith("| `"):
            continue
        nombres.add(linea.split("`")[1])
    return nombres


def test_la_matriz_de_extras_no_es_vacua() -> None:
    """Ancla anti-vacuidad: un parseo roto devolvería 0 filas y los dos gates darían verde."""
    matriz = _extras_de_la_matriz()
    assert len(matriz) >= 15, f"la matriz sólo devolvió {len(matriz)} filas: el parseo está roto"
    assert {"scoring", "ui", "all"} <= matriz


def test_todo_extra_del_paquete_tiene_su_fila_en_la_documentacion() -> None:
    """Un extra que la matriz no lista es una capacidad que el usuario no sabe que existe."""
    faltan = _extras_del_pyproject() - _extras_de_la_matriz()
    assert not faltan, (
        f"extras declarados en el pyproject y ausentes de la matriz: {sorted(faltan)}. "
        "Añade su fila en docs_site/getting-started.md: quien lea la matriz cree que no existen."
    )


def test_toda_fila_de_la_documentacion_es_un_extra_real() -> None:
    """Una fila sin extra detrás manda al usuario a escribir un `pip install` que falla."""
    sobran = _extras_de_la_matriz() - _extras_del_pyproject()
    assert not sobran, (
        f"filas de la matriz que no son extras del pyproject: {sorted(sobran)}. "
        "O el extra se retiró y la fila quedó, o la fila tiene un typo."
    )


def test_la_matriz_no_promete_que_all_los_agrega_todos() -> None:
    """`all` excluye `pdf` por copyleft, y decir «todos los de arriba» era falso.

    Oráculo independiente: se deriva del pyproject cuáles quedan fuera de `all`, en vez de
    comprobar contra la frase que el propio documento trae.
    """
    with _PYPROJECT.open("rb") as handle:
        opcionales = tomllib.load(handle)["project"]["optional-dependencies"]
    en_all = {
        dep.removeprefix("nikodym[").removesuffix("]")
        for dep in opcionales["all"]
        if dep.startswith("nikodym[")
    }
    fuera = _extras_del_pyproject() - en_all - {"all"}
    assert fuera == {"pdf"}, (
        f"cambió qué extras quedan fuera de `all`: {sorted(fuera)}. "
        "La matriz y el aviso de copyleft de docs_site/getting-started.md nombran a `pdf` como el "
        "único excluido; si eso cambió, hay que barrer las dos superficies."
    )
    texto = _DOCS_GETTING_STARTED.read_text(encoding="utf-8")
    assert "menos `pdf`" in texto, "la fila de `all` volvió a prometer que los agrega todos"
