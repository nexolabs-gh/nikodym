"""Gate estructural: toda ruta del contrato REST está clasificada en seguridad (D-PUE-9).

El middleware de `ui/security.py` decide qué exige cada ruta consultando :data:`MUTATING_PATHS` y
:data:`CREDENTIALED_PATHS`. Lo que **no** existía hasta el 2026-08-01 es algo que obligue a una ruta
nueva a aparecer en alguna de las dos, o a declarar por qué no. Y eso no es teórico: es exactamente
el estado en el que ``POST /api/preflight`` estuvo abierto sin token —devolviendo 200 y
materializando el parquet a cualquier proceso local, mientras ``/api/run`` daba 403 en las mismas
condiciones— con 4.522 tests verdes y CI 16/16. Lo encontró una auditoría adversarial previa a
publicar, no la suite.

Este gate convierte ese olvido en un rojo. Un endpoint nuevo sin clasificar no llega a `main`.

**Por qué se mide por AST y no sólo contra el router construido.** El router real exige el extra
``[ui]``; un gate que dependa de él se **salta** donde el extra falta, y un skip se lee igual que un
verde (la lección de `importorskip` no lockeado ya está pagada en este repo). El barrido AST corre
siempre, con fastapi o sin él. Para que ese barrido no se desincronice de la realidad, un segundo
test —éste sí bajo ``importorskip``— compara lo que el AST leyó contra las rutas que el router
efectivamente registra: si alguien registra una ruta por una vía que el AST no ve, salta ahí.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nikodym.ui.security import CREDENTIALED_PATHS, MUTATING_PATHS, PUBLIC_PATHS

_RUTAS_PY = Path(__file__).resolve().parents[2] / "src" / "nikodym" / "ui" / "routes.py"

#: Prefijo del ``APIRouter`` del contrato (``routes.py``: ``APIRouter(prefix="/api")``).
_PREFIJO = "/api"

#: Verbos HTTP que registran una ruta al decorar.
_VERBOS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

#: Longitud mínima de la razón de una ruta pública: obliga a una frase, no a un "n/a".
_RAZON_MINIMA = 30


def _rutas_declaradas_en_el_fuente() -> frozenset[str]:
    """Enumera por AST las rutas que ``routes.py`` registra con ``@router.<verbo>("<path>")``."""
    arbol = ast.parse(_RUTAS_PY.read_text(encoding="utf-8"))
    rutas: set[str] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorador in nodo.decorator_list:
            if not isinstance(decorador, ast.Call):
                continue
            funcion = decorador.func
            if (
                isinstance(funcion, ast.Attribute)
                and funcion.attr in _VERBOS
                and isinstance(funcion.value, ast.Name)
                and funcion.value.id == "router"
                and decorador.args
                and isinstance(decorador.args[0], ast.Constant)
                and isinstance(decorador.args[0].value, str)
            ):
                rutas.add(f"{_PREFIJO}{decorador.args[0].value}")
    return frozenset(rutas)


def test_el_barrido_encuentra_las_rutas_ancla() -> None:
    """Control de que el AST recorre algo: un barrido que lee cero rutas daría verde vacío.

    Es la lección de `test_copy_del_formulario.py`, cuya primera versión pasaba recorriendo cero
    campos: «0 rutas sin clasificar» se lee idéntico a «todas clasificadas».
    """
    rutas = _rutas_declaradas_en_el_fuente()
    assert len(rutas) >= 15, f"el barrido AST sólo encontró {len(rutas)} rutas: revisa el parseo."
    for ancla in ("/api/run", "/api/upload", "/api/preflight", "/api/schema"):
        assert ancla in rutas, f"el barrido AST no encontró la ruta ancla {ancla!r}."


def test_toda_ruta_esta_clasificada() -> None:
    """Cada ruta del contrato está en una de las tres listas de seguridad."""
    clasificadas = MUTATING_PATHS | CREDENTIALED_PATHS | frozenset(PUBLIC_PATHS)
    sin_clasificar = sorted(_rutas_declaradas_en_el_fuente() - clasificadas)
    assert not sin_clasificar, (
        "Estas rutas no están clasificadas en nikodym/ui/security.py: "
        f"{sin_clasificar}. Añádelas a MUTATING_PATHS (escribe o ejecuta), a "
        "CREDENTIALED_PATHS (exige credenciales pero no ejecuta el pipeline) o a "
        "PUBLIC_PATHS con la razón por la que no exige credenciales."
    )


def test_las_listas_no_citan_rutas_inexistentes() -> None:
    """El sentido inverso: una lista que nombra una ruta muerta describe una defensa inexistente."""
    declaradas = _rutas_declaradas_en_el_fuente()
    for nombre, lista in (
        ("MUTATING_PATHS", frozenset(MUTATING_PATHS)),
        ("CREDENTIALED_PATHS", frozenset(CREDENTIALED_PATHS)),
        ("PUBLIC_PATHS", frozenset(PUBLIC_PATHS)),
    ):
        fantasmas = sorted(lista - declaradas)
        assert not fantasmas, f"{nombre} nombra rutas que el router no registra: {fantasmas}."


def test_las_tres_listas_son_disjuntas() -> None:
    """Una ruta en dos categorías deja ambigua la guarda que le toca."""
    publicas = frozenset(PUBLIC_PATHS)
    assert not (MUTATING_PATHS & CREDENTIALED_PATHS)
    assert not (MUTATING_PATHS & publicas)
    assert not (CREDENTIALED_PATHS & publicas)


def test_cada_ruta_publica_escribe_su_razon() -> None:
    """Una ruta sin credenciales tiene que decir por qué; si no, es indistinguible de un olvido."""
    for ruta, razon in PUBLIC_PATHS.items():
        assert len(razon.strip()) >= _RAZON_MINIMA, (
            f"la razón de {ruta!r} en PUBLIC_PATHS es demasiado corta: {razon!r}."
        )


def test_el_ast_ve_las_mismas_rutas_que_el_router_real() -> None:
    """El barrido estático no se desincroniza de lo que el router efectivamente registra."""
    pytest.importorskip("fastapi")
    from nikodym.ui.routes import build_router

    del_router = frozenset(
        ruta.path for ruta in build_router().routes if isinstance(getattr(ruta, "path", None), str)
    )
    assert del_router == _rutas_declaradas_en_el_fuente(), (
        "el barrido AST y el router real no coinciden: "
        f"sólo en el router={sorted(del_router - _rutas_declaradas_en_el_fuente())}, "
        f"sólo en el AST={sorted(_rutas_declaradas_en_el_fuente() - del_router)}."
    )
