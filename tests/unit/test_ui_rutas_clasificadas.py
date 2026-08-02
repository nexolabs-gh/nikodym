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
test —éste sí bajo ``importorskip``— compara lo que el AST leyó contra las rutas que la app
efectivamente registra: si alguien registra una ruta por una vía que el AST no ve, salta ahí.

**Los tres agujeros que tuvo este gate, medidos por una revisión adversarial el 2026-08-02.**
Valen escritos porque los tres son la misma familia —un gate que se dio por suficiente— y porque los
tres daban verde:

1. **Colapsaba método y ruta.** Recogía sólo el path del decorador y las listas de seguridad
   guardaban rutas sueltas, así que inyectar un ``@router.post("/schema")`` con efectos mutadores
   dejaba el conjunto **idéntico** (17 rutas, 0 sin clasificar) y el middleware tampoco lo habría
   cerrado: ``/api/schema`` está declarada pública por su GET. Ahora se clasifica y se compara el
   par ``(método, ruta)``.
2. **Aceptaba en categoría protegida una ruta parametrizada.** El gate razona sobre *templates*
   (``/api/report/{run_id}``) y el middleware compara la URL **concreta**: una guarda declarada
   sobre un template nunca casaría con ``/api/report/20260802T101010-abcd``. Hoy no hay ninguna en
   esas listas, así que no era explotable — pero el gate daba una seguridad falsa. Se cierra
   **haciendo fallar el gate**: se declara la limitación con su razón en vez de simular una defensa
   que la ejecución no tiene (mismo criterio que D-PRE-4 con el alcance del preflight).
3. **Sólo miraba ``routes.py``, que es justo el hueco que decía cerrar.** El barrido leía un único
   archivo y el test de sincronía comparaba contra ``build_router()``, no contra la app final; una
   ruta ``/api`` registrada en ``server.py`` era invisible por partida doble. Y la vía existe hoy en
   el código: ``server.py`` registra los recursos de raíz con ``app.get(f"/{resource}", ...)``.
   Ahora el barrido recorre **todos** los módulos de ``nikodym/ui/`` y el contraste runtime va
   contra ``create_app()``.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from nikodym.ui.security import CREDENTIALED_PATHS, MUTATING_PATHS, PUBLIC_PATHS

_UI_DIR = Path(__file__).resolve().parents[2] / "src" / "nikodym" / "ui"

#: Prefijo del contrato REST: sólo estas rutas exigen clasificación de seguridad. ``/`` y los
#: recursos de raíz (``/favicon.svg``) sirven bytes del propio paquete y quedan fuera, igual que
#: antes de este gate.
_PREFIJO = "/api"

#: Verbos HTTP que registran una ruta al decorar o al llamarse.
_VERBOS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})

#: Clases cuyo constructor produce un objeto sobre el que se registran rutas.
_CLASES_RECEPTORAS = frozenset({"APIRouter", "FastAPI"})

#: Longitud mínima de la razón de una ruta pública: obliga a una frase, no a un "n/a".
_RAZON_MINIMA = 30

#: Registros de ruta con path **dinámico**, que el AST no puede resolver, declarados uno a uno con
#: su razón. Son el equivalente de :data:`PUBLIC_PATHS` para el barrido: un path que el gate no
#: puede leer es indistinguible de un endpoint colado, así que por defecto es rojo y sólo sale de
#: rojo escribiendo aquí por qué no toca el contrato ``/api``.
#:
#: La clave es ``(módulo, expresión del path tal como la reescribe ``ast.unparse``)``. Se ata a la
#: expresión y no al número de línea a propósito: la línea se mueve con cualquier edición y la
#: declaración se volvería una firma vacía que nadie relee.
_REGISTROS_DINAMICOS_DECLARADOS: dict[tuple[str, str], str] = {
    ("server.py", "f'/{resource}'"): (
        "Los recursos de raíz del build (hoy sólo `/favicon.svg`) se registran en un bucle sobre "
        "`runtime.resources`, la lista **verificada por el preflight del launcher**. Cuelgan "
        "de `/` y no de `/api`, así que no entran al contrato REST; y son ficheros estáticos del "
        "propio paquete, sin efectos ni datos de nadie. Si alguien mueve ese bucle bajo `/api`, la "
        "expresión cambia, esta clave deja de casar y el gate se pone rojo."
    ),
}


def _nombre_referido(nodo: ast.expr) -> str | None:
    """El nombre final de una referencia (``FastAPI``, ``fastapi.FastAPI``, ``"FastAPI"``)."""
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute):
        return nodo.attr
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    return None


def _receptores_del_modulo(arbol: ast.Module) -> dict[str, str]:
    """Mapea cada variable que sostiene un router o una app a su prefijo de rutas.

    El prefijo se **deriva** del fuente (``APIRouter(prefix="/api")``) en vez de escribirse a mano
    aquí, porque es dato del código: fijarlo en el test lo dejaría desincronizado en silencio el día
    que cambie.

    Se incluyen también los parámetros anotados ``FastAPI``/``APIRouter``: ``install_security``
    recibe la app así, y un ``app.post(...)`` colado dentro de esa función registraría una ruta sin
    pasar nunca por ``routes.py``. Restringir el barrido a estos nombres es lo que evita confundir
    un ``config.get("x")`` cualquiera con el registro de un endpoint.
    """
    receptores: dict[str, str] = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call):
            if _nombre_referido(nodo.value.func) not in _CLASES_RECEPTORAS:
                continue
            prefijo = ""
            for clave in nodo.value.keywords:
                if (
                    clave.arg == "prefix"
                    and isinstance(clave.value, ast.Constant)
                    and isinstance(clave.value.value, str)
                ):
                    prefijo = clave.value.value
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    receptores[destino.id] = prefijo
        elif isinstance(nodo, ast.arg) and nodo.annotation is not None:
            if _nombre_referido(nodo.annotation) in _CLASES_RECEPTORAS:
                receptores.setdefault(nodo.arg, "")
    return receptores


def _ruta_constante(nodo: ast.expr) -> str | None:
    """El path de un registro, si es un literal que el AST puede leer."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    return None


def _metodos_declarados(llamada: ast.Call) -> tuple[str, ...] | None:
    """Los verbos de ``methods=[...]`` en ``add_api_route``/``add_route``, si son literales."""
    for clave in llamada.keywords:
        if clave.arg != "methods":
            continue
        if not isinstance(clave.value, ast.List):
            return None
        metodos: list[str] = []
        for elemento in clave.value.elts:
            if not isinstance(elemento, ast.Constant) or not isinstance(elemento.value, str):
                return None
            metodos.append(elemento.value.upper())
        return tuple(metodos)
    return None


def _barrer_modulo(archivo: Path) -> tuple[set[tuple[str, str]], list[str]]:
    """Enumera los registros de ruta de un módulo y los que no se pueden resolver estáticamente.

    Un solo recorrido con :func:`ast.walk` cubre las dos formas de registrar, porque los decoradores
    también son nodos ``Call``: ``@router.get("/x")`` y ``app.get("/y")(handler)`` se ven igual.
    """
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    receptores = _receptores_del_modulo(arbol)
    registros: set[tuple[str, str]] = set()
    problemas: list[str] = []

    def _sin_resolver(llamada: ast.Call, que: str) -> None:
        expresion = ast.unparse(llamada.args[0]) if llamada.args else "<sin argumentos>"
        if (archivo.name, expresion) in _REGISTROS_DINAMICOS_DECLARADOS:
            return
        problemas.append(
            f"{archivo.name}:{llamada.lineno}: {que} con un path que el barrido no puede leer "
            f"({expresion}). Escríbelo como literal, o declara en "
            f"_REGISTROS_DINAMICOS_DECLARADOS[({archivo.name!r}, {expresion!r})] por qué no toca "
            f"el contrato {_PREFIJO}."
        )

    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        funcion = nodo.func
        if not isinstance(funcion, ast.Attribute) or not isinstance(funcion.value, ast.Name):
            continue
        if funcion.value.id not in receptores:
            continue
        prefijo = receptores[funcion.value.id]
        llamado = f"{funcion.value.id}.{funcion.attr}()"

        if funcion.attr in _VERBOS:
            path = _ruta_constante(nodo.args[0]) if nodo.args else None
            if path is None:
                _sin_resolver(nodo, llamado)
            else:
                registros.add((funcion.attr.upper(), f"{prefijo}{path}"))

        elif funcion.attr in {"add_api_route", "add_route"}:
            path = _ruta_constante(nodo.args[0]) if nodo.args else None
            metodos = _metodos_declarados(nodo)
            if path is None or metodos is None:
                _sin_resolver(nodo, f"{llamado} sin path o sin methods literales,")
            else:
                registros.update((metodo, f"{prefijo}{path}") for metodo in metodos)

        elif funcion.attr in {"websocket", "add_websocket_route"}:
            problemas.append(
                f"{archivo.name}:{nodo.lineno}: {llamado} registra un websocket, y ni el "
                "barrido ni el middleware de ui/security.py saben clasificarlo. Extiende los "
                "dos antes de abrir uno."
            )

        elif funcion.attr == "mount":
            path = _ruta_constante(nodo.args[0]) if nodo.args else ""
            if path is None or path.startswith(_PREFIJO):
                problemas.append(
                    f"{archivo.name}:{nodo.lineno}: {llamado} monta una sub-app bajo "
                    f"{_PREFIJO}. El barrido no puede enumerar las rutas de una sub-app, así "
                    "que quedarían fuera de la clasificación de seguridad."
                )

        elif funcion.attr == "include_router":
            incluido = nodo.args[0] if nodo.args else None
            if not (
                isinstance(incluido, ast.Call) and _nombre_referido(incluido.func) == "build_router"
            ):
                problemas.append(
                    f"{archivo.name}:{nodo.lineno}: {llamado} incluye un router que no es "
                    "build_router(); el barrido no sabe de dónde salen sus rutas."
                )

    return registros, problemas


@cache
def _barrido() -> tuple[frozenset[tuple[str, str]], tuple[str, ...], tuple[str, ...]]:
    """Recorre **todos** los módulos de ``nikodym/ui/``: registros, problemas y módulos leídos."""
    registros: set[tuple[str, str]] = set()
    problemas: list[str] = []
    modulos = sorted(_UI_DIR.glob("*.py"))
    for archivo in modulos:
        del_modulo, problemas_del_modulo = _barrer_modulo(archivo)
        registros |= del_modulo
        problemas += problemas_del_modulo
    return frozenset(registros), tuple(problemas), tuple(archivo.name for archivo in modulos)


def _rutas_del_contrato() -> frozenset[tuple[str, str]]:
    """Los pares ``(método, ruta)`` bajo ``/api`` que la capa ``ui/`` registra por cualquier vía."""
    registros, _, _ = _barrido()
    return frozenset(par for par in registros if par[1].startswith(f"{_PREFIJO}/"))


def _rutas_de_la_app(app: Any) -> frozenset[tuple[str, str]]:
    """Enumera los ``(método, ruta)`` de una app FastAPI recorriendo sus contenedores.

    ⚠️ ``app.routes`` **no** aplana el router incluido. Medido en fastapi 0.138 / starlette 1.3.1:
    devuelve ``[_IncludedRouter, Mount /assets, APIRoute /favicon.svg, APIRoute /]``, y las 17 rutas
    de ``/api`` cuelgan del atributo ``original_router`` de ese ``_IncludedRouter`` —que **no**
    tiene ni ``routes`` ni ``router``, medido con ``hasattr``—. De ahí que se baje por varios
    atributos posibles: atarse a uno solo deja el gate a merced del refactor interno de un
    tercero. Y de ahí
    también que el test lleve su control de anclas: si una versión futura renombra ese atributo, el
    recorrido devolvería cero rutas ``/api`` y un barrido que no recorre nada da verde vacío.
    """
    encontrados: set[tuple[str, str]] = set()
    vistos: set[int] = set()
    pendientes: list[Any] = [app]
    while pendientes:
        actual = pendientes.pop()
        if id(actual) in vistos:
            continue
        vistos.add(id(actual))
        path = getattr(actual, "path", None)
        metodos = getattr(actual, "methods", None)
        if isinstance(path, str) and metodos:
            encontrados.update((str(metodo).upper(), path) for metodo in metodos)
        for atributo in ("routes", "router", "original_router", "app"):
            hijo = getattr(actual, atributo, None)
            if hijo is None:
                continue
            pendientes.extend(hijo) if isinstance(hijo, list) else pendientes.append(hijo)
    return frozenset(encontrados)


# ─────────────────────────────── controles de que el barrido barre ───────────────────────────────


def test_el_barrido_recorre_todos_los_modulos_de_ui() -> None:
    """El barrido lee la capa entera y no un archivo: leer sólo ``routes.py`` era el defecto D6."""
    _, _, modulos = _barrido()
    assert len(modulos) >= 10, f"el barrido sólo vio {len(modulos)} módulos en ui/: {modulos}."
    for ancla in ("routes.py", "server.py", "security.py"):
        assert ancla in modulos, f"el barrido no recorrió {ancla}."


def test_el_barrido_encuentra_las_rutas_ancla() -> None:
    """Control de que el AST recorre algo: un barrido que lee cero rutas daría verde vacío.

    Es la lección de `test_copy_del_formulario.py`, cuya primera versión pasaba recorriendo cero
    campos: «0 rutas sin clasificar» se lee idéntico a «todas clasificadas». Las anclas llevan su
    verbo porque el gate clasifica pares: comprobar sólo el path dejaría pasar el defecto D4.
    """
    rutas = _rutas_del_contrato()
    assert len(rutas) >= 15, f"el barrido AST sólo encontró {len(rutas)} rutas: revisa el parseo."
    for ancla in (
        ("POST", "/api/run"),
        ("POST", "/api/upload"),
        ("POST", "/api/preflight"),
        ("GET", "/api/schema"),
    ):
        assert ancla in rutas, f"el barrido AST no encontró la ruta ancla {ancla}."


def test_el_prefijo_del_contrato_sale_del_fuente() -> None:
    """El ``/api`` de este test no es convención escrita al lado: lo declara el propio router."""
    arbol = ast.parse((_UI_DIR / "routes.py").read_text(encoding="utf-8"))
    prefijos = set(_receptores_del_modulo(arbol).values())
    assert _PREFIJO in prefijos, (
        f"routes.py ya no declara ningún APIRouter con prefix={_PREFIJO!r} "
        f"(vio {sorted(prefijos)}): el barrido estaría prefijando las rutas con algo que el "
        "router no usa."
    )


def test_el_barrido_no_deja_registros_sin_resolver() -> None:
    """Un registro que el AST no puede leer es indistinguible de un endpoint colado.

    Por eso es rojo por defecto y sólo sale de rojo declarándolo en
    :data:`_REGISTROS_DINAMICOS_DECLARADOS` con su razón, igual que ``PUBLIC_PATHS`` obliga a decir
    por qué una ruta no exige credenciales.
    """
    _, problemas, _ = _barrido()
    detalle = "\n".join(f"  - {problema}" for problema in problemas)
    assert not problemas, (
        f"El barrido de nikodym/ui/ no pudo clasificar estos registros:\n{detalle}"
    )


def test_los_registros_dinamicos_declarados_siguen_existiendo() -> None:
    """El sentido inverso: una declaración sobre código que ya no existe es una firma vacía."""
    encontrados: set[tuple[str, str]] = set()
    for archivo in sorted(_UI_DIR.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        receptores = _receptores_del_modulo(arbol)
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and isinstance(nodo.func.value, ast.Name)
                and nodo.func.value.id in receptores
                and nodo.args
            ):
                encontrados.add((archivo.name, ast.unparse(nodo.args[0])))
    fantasmas = sorted(set(_REGISTROS_DINAMICOS_DECLARADOS) - encontrados)
    assert not fantasmas, (
        f"_REGISTROS_DINAMICOS_DECLARADOS describe registros que ya no existen: {fantasmas}."
    )


def test_cada_registro_dinamico_escribe_su_razon() -> None:
    """Declarar sin explicar sería el olvido con otro nombre."""
    for clave, razon in _REGISTROS_DINAMICOS_DECLARADOS.items():
        assert len(razon.strip()) >= _RAZON_MINIMA, (
            f"la razón de {clave} en _REGISTROS_DINAMICOS_DECLARADOS es demasiado corta: {razon!r}."
        )


# ─────────────────────────────────── clasificación de seguridad ───────────────────────────────────


def test_toda_ruta_esta_clasificada() -> None:
    """Cada par ``(método, ruta)`` del contrato está en una de las tres listas de seguridad."""
    clasificadas = MUTATING_PATHS | CREDENTIALED_PATHS | frozenset(PUBLIC_PATHS)
    sin_clasificar = sorted(_rutas_del_contrato() - clasificadas)
    assert not sin_clasificar, (
        "Estos pares (método, ruta) no están clasificados en nikodym/ui/security.py: "
        f"{sin_clasificar}. Añádelos a MUTATING_PATHS (escribe o ejecuta), a "
        "CREDENTIALED_PATHS (exige credenciales pero no ejecuta el pipeline) o a "
        "PUBLIC_PATHS con la razón por la que no exige credenciales. Un método nuevo sobre una "
        "ruta ya clasificada es una entrada nueva: la categoría no se hereda del verbo vecino."
    )


def test_las_listas_no_citan_rutas_inexistentes() -> None:
    """El sentido inverso: una lista que nombra una ruta muerta describe una defensa inexistente."""
    declaradas = _rutas_del_contrato()
    for nombre, lista in (
        ("MUTATING_PATHS", frozenset(MUTATING_PATHS)),
        ("CREDENTIALED_PATHS", frozenset(CREDENTIALED_PATHS)),
        ("PUBLIC_PATHS", frozenset(PUBLIC_PATHS)),
    ):
        fantasmas = sorted(lista - declaradas)
        assert not fantasmas, f"{nombre} nombra rutas que la app no registra: {fantasmas}."


def test_las_tres_listas_son_disjuntas() -> None:
    """Un par en dos categorías deja ambigua la guarda que le toca."""
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


def test_las_tres_listas_clasifican_pares_metodo_ruta() -> None:
    """La forma del elemento es contrato: con la ruta sola, dos verbos colapsan en una decisión.

    Sin esto, alguien podría «arreglar» un choque volviendo a poner un string suelto y el gate
    seguiría verde recorriendo lo mismo — que es exactamente cómo se coló el defecto D4.
    """
    for nombre, lista in (
        ("MUTATING_PATHS", frozenset(MUTATING_PATHS)),
        ("CREDENTIALED_PATHS", frozenset(CREDENTIALED_PATHS)),
        ("PUBLIC_PATHS", frozenset(PUBLIC_PATHS)),
    ):
        for entrada in lista:
            assert isinstance(entrada, tuple) and len(entrada) == 2, (
                f"{nombre} contiene {entrada!r}, que no es un par (método, ruta)."
            )
            metodo, ruta = entrada
            assert metodo.upper() in {verbo.upper() for verbo in _VERBOS}, (
                f"{nombre} declara el método {metodo!r}, que no es un verbo HTTP conocido."
            )
            assert ruta.startswith(f"{_PREFIJO}/"), (
                f"{nombre} declara la ruta {ruta!r}, fuera del contrato {_PREFIJO}."
            )


def test_ninguna_ruta_protegida_es_parametrizada() -> None:
    """El middleware compara la URL CONCRETA: un template en categoría protegida no casaría nunca.

    El gate razona sobre lo que declara el router (``/api/report/{run_id}``) y el middleware ve lo
    que pide el navegador (``/api/report/20260802T101010-abcd``). Aceptar un template en las listas
    protegidas dejaría escrita una guarda que la ejecución no aplica — una seguridad falsa, que es
    peor que ninguna porque nadie la vuelve a mirar.

    Se cierra **haciendo fallar el gate** y no enseñándole al middleware a resolver templates: es el
    criterio del repo de declarar la limitación con su razón (D-PRE-4) en vez de rodearla, y deja el
    invariante simple de verificar — todo lo que está en las listas protegidas es una URL literal—.
    Quien necesite proteger una ruta parametrizada tiene que ampliar el middleware primero, y este
    rojo se lo dice.
    """
    for nombre, lista in (
        ("MUTATING_PATHS", MUTATING_PATHS),
        ("CREDENTIALED_PATHS", CREDENTIALED_PATHS),
    ):
        parametrizadas = sorted(f"{metodo} {ruta}" for metodo, ruta in lista if "{" in ruta)
        assert not parametrizadas, (
            f"{nombre} contiene rutas parametrizadas: {parametrizadas}. El middleware compara la "
            "URL concreta por igualdad, y esa guarda no se aplicaría a ninguna petición real. "
            "Enseña primero a nikodym/ui/security.py a resolver la URL contra su template, o no "
            "declares protegida una ruta que no lo estaría."
        )


# ─────────────────────── el middleware distingue el método, y no abre nada ───────────────────────


def test_el_clasificador_distingue_el_metodo() -> None:
    """La guarda se decide por el par, no por la ruta: es la mitad de D4 que vive en runtime."""
    from nikodym.ui.security import _categoria

    assert _categoria("POST", "/api/run") == "mutador"
    assert _categoria("POST", "/api/upload") == "mutador"
    assert _categoria("POST", "/api/preflight") == "credenciales"
    assert _categoria("GET", "/api/schema") is None
    assert _categoria("GET", "/api/results/cualquiera") is None


def test_un_verbo_no_contratado_sobre_una_ruta_protegida_sigue_protegido() -> None:
    """Endurecer no puede ABRIR: hasta hoy ``/api/run`` estaba cerrado para cualquier verbo.

    Pasar de clasificar rutas a clasificar pares es más preciso, y por eso mismo podría dejar fuera
    de la guarda un verbo que hoy sí la pasa. Este test fija que no ocurre.
    """
    from nikodym.ui.security import _categoria

    for verbo in ("GET", "PUT", "DELETE", "HEAD", "PATCH", "OPTIONS"):
        assert _categoria(verbo, "/api/run") == "mutador", f"{verbo} /api/run quedó sin guarda."
        assert _categoria(verbo, "/api/upload") == "mutador"
    for verbo in ("GET", "PUT", "DELETE"):
        assert _categoria(verbo, "/api/preflight") == "credenciales"


def test_una_ruta_puede_ser_publica_por_un_verbo_y_protegida_por_otro() -> None:
    """La capacidad que D4 desbloquea, ejercitada de punta a punta contra la app real.

    Con la comparación por ruta sola esto era **inexpresable**: declarar mutador ``/api/schema``
    habría cerrado también su GET público. Se monta con ``monkeypatch`` porque hoy ninguna ruta del
    contrato tiene dos verbos —si algún día la tiene, este test ya la cubre— y se comprueba sobre
    ``TestClient``, no sobre la función suelta: el defecto D4 vivía en el middleware.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from _ui_client import ui_client

    from nikodym.ui import security

    sin_credenciales = ui_client(con_credenciales=False)
    assert sin_credenciales.get("/api/schema").status_code == 200

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(
            security, "MUTATING_PATHS", MUTATING_PATHS | {("POST", "/api/schema")}, raising=True
        )
        assert security._categoria("POST", "/api/schema") == "mutador"
        # Y el GET, que sigue declarado público, no se contagia: es la precisión que D4 aporta.
        assert security._categoria("GET", "/api/schema") is None
        assert ui_client(con_credenciales=False).get("/api/schema").status_code == 200


def test_el_middleware_sigue_cerrando_los_mutadores_sin_credenciales() -> None:
    """Control de no-regresión del endurecimiento: lo que estaba en 403 sigue en 403."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from _ui_client import ui_client

    sin_credenciales = ui_client(con_credenciales=False)
    assert sin_credenciales.post("/api/run", json={}).status_code == 403
    assert sin_credenciales.post("/api/preflight", json={}).status_code == 403
    # Verbo no contratado sobre una ruta mutadora: 403 antes de llegar al router, como siempre.
    assert sin_credenciales.get("/api/run").status_code == 403


# ─────────────────────── sincronía del barrido con la app que se sirve ───────────────────────


def test_el_ast_ve_las_mismas_rutas_que_la_app_real(tmp_path: Path) -> None:
    """El barrido estático no se desincroniza de lo que la app final registra.

    Se contrasta contra ``create_app()`` y no contra ``build_router()``: comparar contra el router
    era el defecto D6, porque dejaba fuera justo lo que el barrido no veía —las rutas que
    ``server.py`` registra directamente sobre la app—.
    """
    pytest.importorskip("fastapi")
    from _ui_client import build_test_runtime

    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    app = create_app(UiConfig(workdir=str(tmp_path)), build_test_runtime(tmp_path))
    de_la_app = frozenset(par for par in _rutas_de_la_app(app) if par[1].startswith(f"{_PREFIJO}/"))
    assert len(de_la_app) >= 15, (
        f"el recorrido de create_app() sólo encontró {len(de_la_app)} rutas {_PREFIJO}: el "
        "árbol de rutas de fastapi cambió de forma y este contraste mide el vacío."
    )
    assert de_la_app == _rutas_del_contrato(), (
        "el barrido AST y la app real no coinciden: "
        f"sólo en la app={sorted(de_la_app - _rutas_del_contrato())}, "
        f"sólo en el AST={sorted(_rutas_del_contrato() - de_la_app)}."
    )
