"""El tope del cuerpo se aplica sobre el stream ASGI, antes de recibir y de parsear.

Cierra la deuda que ``/api/upload`` declaraba con su razón desde el 2026-08-02: el tope existía,
gobernado ya por ``upload_max_mb``, pero se comprobaba con el cuerpo **ya recibido y ya parseado**
—FastAPI termina el multipart antes de invocar el handler—, así que el archivo rechazado ya había
viajado por la red y ya se había escrito al temporal. Y los **cinco POST de JSON** no tenían tope de
ninguna clase; tres de ellos son públicos.

**Qué prueba cada cosa, y qué NO puede probar.** ⚠️ Medido en starlette 1.3.1: ``TestClient``
entrega el cuerpo entero en **un solo** mensaje ``http.request`` (se comprobó con un espía: un
cuerpo de 300.019 bytes llegó en un único mensaje). Por eso un test que use ``TestClient`` puede
probar que la cabecera no se cree —se declara poco y se envía mucho— pero **no** puede probar que el
corte ocurre sin acumular: con un solo trozo, contar y acumular son indistinguibles. Esa mitad la
prueba :func:`test_el_contador_corta_sin_tragarse_el_cuerpo_entero`, que llama al ASGI directamente
con el cuerpo troceado y cuenta **cuántos trozos se pidieron**. Un test que sólo aseverara el 422
pasaría con las dos implementaciones y no probaría nada.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nikodym.ui.security import CREDENTIALED_PATHS, MUTATING_PATHS, PUBLIC_PATHS

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from _ui_client import TEST_PORT, build_test_runtime, ui_client

from nikodym.ui.settings import UiConfig

#: Un cuerpo cómodamente por encima del tope de 1 MiB que usan los tests.
_GRANDE = b"z" * (4 * 1024 * 1024)

#: Cuerpo de un CSV mínimo válido, muy por debajo de cualquier tope.
_CSV_PEQUENO = b"a,b\n1,2\n"


def _cliente(tmp_path: Path, *, mb: int = 1, con_credenciales: bool = True) -> Any:
    return ui_client(
        UiConfig(workdir=str(tmp_path), upload_max_mb=mb), con_credenciales=con_credenciales
    )


def _posts_de_json() -> list[str]:
    """Los POST del contrato que llevan JSON, **derivados** de las listas de seguridad.

    Escribirlos a mano dejaría el test ciego ante un POST nuevo, que es justo el caso que este
    middleware tiene que cubrir sin que nadie se acuerde de venir aquí. La única exclusión es
    ``/api/upload``, que es multipart y tiene sus propios tests más abajo.
    """
    todos = frozenset(MUTATING_PATHS) | frozenset(CREDENTIALED_PATHS) | frozenset(PUBLIC_PATHS)
    return sorted(ruta for metodo, ruta in todos if metodo == "POST" and ruta != "/api/upload")


# ─────────────────────────── control de que la medición sigue en pie ───────────────────────────


def test_el_contrato_tiene_cinco_post_de_json() -> None:
    """Ancla de la medición previa: 5 POST de JSON sin tope + ``/api/upload`` con el suyo.

    Si el contrato gana un POST, este número cambia y hay que mirar si el tope le sirve tal cual.
    No es un golden decorativo: es lo que impide que la lista derivada quede vacía y los tests
    parametrizados de abajo pasen recorriendo cero endpoints.
    """
    assert _posts_de_json() == [
        "/api/config/from-yaml",
        "/api/config/to-yaml",
        "/api/preflight",
        "/api/run",
        "/api/validate",
    ]


# ────────────────────────────────── multipart: el caso de origen ──────────────────────────────────


def test_un_multipart_sobre_el_tope_no_llega_a_escribir_el_temporal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 El corazón del arreglo: con ``Content-Length`` honesto el parser ni siquiera corre.

    El temporal lo crea ``MultiPartParser`` llamando a ``SpooledTemporaryFile`` (spool de 1 MiB, o
    sea que cualquier archivo mayor **rueda a disco**). Aquí se hace explotar ese constructor: si la
    respuesta sale igual con su 422, es que el multipart no se parseó y no hubo temporal que
    escribir. Aseverar sólo el 422 pasaría también con el defecto puesto.
    """
    import starlette.formparsers as formparsers

    def _prohibido(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("se abrió el temporal del multipart: el cuerpo llegó al parser")

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", _prohibido)

    respuesta = _cliente(tmp_path).post(
        "/api/upload", files={"file": ("grande.csv", _GRANDE, "text/csv")}
    )

    assert respuesta.status_code == 422
    assert "límite admitido" in respuesta.json()["detail"]
    assert "1048576 bytes (1 MiB)" in respuesta.json()["detail"]


def test_un_multipart_bajo_el_tope_sigue_subiendo(tmp_path: Path) -> None:
    """Control positivo: el tope no puede romper el camino normal."""
    respuesta = _cliente(tmp_path).post(
        "/api/upload", files={"file": ("ok.csv", _CSV_PEQUENO, "text/csv")}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["dataset_id"].startswith("uploaded_")


def test_el_tope_del_multipart_lo_gobierna_upload_max_mb(tmp_path: Path) -> None:
    """El middleware lee el campo de config, no una constante suya: subir el tope deja pasar."""
    cuerpo = b"a,b\n" + b"1,2\n" * 400_000  # ~1,6 MiB de CSV válido

    apretado = _cliente(tmp_path / "apretado", mb=1).post(
        "/api/upload", files={"file": ("d.csv", cuerpo, "text/csv")}
    )
    holgado = _cliente(tmp_path / "holgado", mb=8).post(
        "/api/upload", files={"file": ("d.csv", cuerpo, "text/csv")}
    )

    assert apretado.status_code == 422
    assert "1048576 bytes (1 MiB)" in apretado.json()["detail"]
    assert holgado.status_code == 200


# ─────────────────────────────────── los cinco POST de JSON ───────────────────────────────────


@pytest.mark.parametrize("ruta", _posts_de_json())
def test_los_post_de_json_quedan_cubiertos_por_el_tope(ruta: str, tmp_path: Path) -> None:
    """Antes de este middleware **ninguno** tenía tope, y tres de ellos son públicos."""
    respuesta = _cliente(tmp_path).post(
        ruta,
        content=b'{"config": "' + _GRANDE + b'"}',
        headers={"Content-Type": "application/json"},
    )

    assert respuesta.status_code == 422, f"{ruta} aceptó un cuerpo de {len(_GRANDE)} bytes"
    assert "límite admitido" in respuesta.json()["detail"]


@pytest.mark.parametrize("ruta", _posts_de_json())
def test_los_post_de_json_bajo_el_tope_no_cambian(ruta: str, tmp_path: Path) -> None:
    """Control positivo: el tope no puede convertir en 422 lo que antes contestaba otra cosa.

    No se asevera el código exacto —cada endpoint tiene el suyo ante un cuerpo vacío— sino que la
    respuesta **no** es el 422 del tope, que es lo que este cambio podría haber roto.
    """
    respuesta = _cliente(tmp_path).post(ruta, json={})

    detalle = str(respuesta.json().get("detail", ""))
    assert "límite admitido" not in detalle, f"{ruta} disparó el tope con un cuerpo mínimo"


# ─────────────────────── la cabecera no se cree: se cuentan los bytes ───────────────────────


def test_un_content_length_mentiroso_no_burla_el_tope(tmp_path: Path) -> None:
    """🔴 El test que prueba que se cuentan bytes y no se lee una cabecera.

    Se declara ``Content-Length: 10`` y se envían 4 MiB por un generador (httpx respeta la cabecera
    explícita, medido). Con una implementación que se fiara de la cabecera, esto pasaría entero: es
    el control negativo del atajo más tentador.

    ⚠️ **Y lo que este test NO demuestra, medido en vivo contra uvicorn real.** Sobre HTTP/1.1
    conforme, mentir por lo bajo no cuela un cuerpo grande: h11 entrega al app exactamente los 10
    bytes declarados y trata el resto como una petición nueva y malformada —se midió: 422 sobre los
    10 bytes, luego un 400 y la conexión cerrada—. O sea que el vector realmente ilimitado es el
    **chunked** de :func:`test_sin_content_length_el_contador_sigue_gobernando`, no éste. Lo que
    este test conserva es lo que importa: que la garantía **no dependa del servidor de delante**. Si
    el tope se apoyara en la cabecera, sería el h11 de uvicorn —y no este código— quien lo estuviera
    sosteniendo, y bastaría otro servidor ASGI, o un cambio suyo, para que dejara de haber tope.
    """

    def cuerpo() -> Any:
        for _ in range(64):
            yield b"z" * 65536

    respuesta = _cliente(tmp_path).post(
        "/api/validate",
        content=cuerpo(),
        headers={"Content-Type": "application/json", "Content-Length": "10"},
    )

    assert respuesta.status_code == 422
    assert "límite admitido" in respuesta.json()["detail"]
    assert "ya lleva" in respuesta.json()["detail"], "no lo cortó el contador sino la cabecera"


def test_sin_content_length_el_contador_sigue_gobernando(tmp_path: Path) -> None:
    """``Transfer-Encoding: chunked``: no hay cabecera que mirar y el tope tiene que valer igual."""

    def cuerpo() -> Any:
        for _ in range(64):
            yield b"z" * 65536

    respuesta = _cliente(tmp_path).post(
        "/api/validate", content=cuerpo(), headers={"Content-Type": "application/json"}
    )

    assert respuesta.status_code == 422
    assert "ya lleva" in respuesta.json()["detail"]


def test_un_content_length_duplicado_se_queda_con_la_declaracion_mayor() -> None:
    """La cabecera sólo puede endurecer: ante dos valores manda el grande, no el pequeño."""
    from nikodym.ui.security import _content_length

    scope = {"headers": [(b"content-length", b"10"), (b"content-length", b"99999")]}
    assert _content_length(scope) == 99999
    assert _content_length({"headers": [(b"content-length", b"no-es-un-numero")]}) is None
    assert _content_length({"headers": []}) is None


# ─────────────────────── el corte no acumula: se mide sobre el ASGI crudo ───────────────────────


def _scope_post(ruta: str, cabeceras: list[tuple[bytes, bytes]]) -> dict[str, Any]:
    """Un scope ASGI de POST con el ``Host``/``Origin`` que las guardas exigen."""
    runtime = build_test_runtime()
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": ruta,
        "raw_path": ruta.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", runtime.expected_host.encode()),
            (b"origin", runtime.origin.encode()),
            *cabeceras,
        ],
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", TEST_PORT),
    }


def test_el_contador_corta_sin_tragarse_el_cuerpo_entero(tmp_path: Path) -> None:
    """🔴 «Sin acumular» sólo se puede medir contando los trozos que se piden al ``receive``.

    ``TestClient`` entrega el cuerpo en un único mensaje (medido), así que por ahí contar y acumular
    son indistinguibles. Aquí el cuerpo llega en 64 trozos de 64 KiB y el tope es 1 MiB: la cuenta
    tiene que pararse en el trozo 17 —16 trozos son exactamente 1 MiB, el 17.º lo cruza— y no en el
    64.º. Sin el corte, el estado medido antes del arreglo era **los 64 trozos pedidos y un 65.º**.
    """
    import anyio

    from nikodym.ui.server import create_app

    app = create_app(UiConfig(workdir=str(tmp_path), upload_max_mb=1), build_test_runtime(tmp_path))
    pedidos = 0
    recibidos: list[dict[str, Any]] = []

    async def escenario() -> None:
        nonlocal pedidos

        async def receive() -> dict[str, Any]:
            nonlocal pedidos
            pedidos += 1
            if pedidos <= 64:
                return {"type": "http.request", "body": b"z" * 65536, "more_body": True}
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(mensaje: dict[str, Any]) -> None:
            recibidos.append(mensaje)

        await app(
            _scope_post("/api/validate", [(b"content-type", b"application/json")]), receive, send
        )

    anyio.run(escenario)

    estados = [m["status"] for m in recibidos if m["type"] == "http.response.start"]
    assert estados == [422]
    assert pedidos == 17, (
        f"el contador pidió {pedidos} trozos de 64 KiB con un tope de 1 MiB: tiene que cortar en "
        "el 17.º (el que cruza el tope), no seguir leyendo el cuerpo entero."
    )


def test_el_rechazo_por_cabecera_no_pide_un_solo_trozo(tmp_path: Path) -> None:
    """El camino barato: con ``Content-Length`` por encima del tope no se lee **nada**."""
    import anyio

    from nikodym.ui.server import create_app

    app = create_app(UiConfig(workdir=str(tmp_path), upload_max_mb=1), build_test_runtime(tmp_path))
    pedidos = 0
    recibidos: list[dict[str, Any]] = []

    async def escenario() -> None:
        async def receive() -> dict[str, Any]:
            nonlocal pedidos
            pedidos += 1
            return {"type": "http.request", "body": b"z" * 65536, "more_body": False}

        async def send(mensaje: dict[str, Any]) -> None:
            recibidos.append(mensaje)

        await app(
            _scope_post(
                "/api/validate",
                [(b"content-type", b"application/json"), (b"content-length", b"99999999")],
            ),
            receive,
            send,
        )

    anyio.run(escenario)

    assert [m["status"] for m in recibidos if m["type"] == "http.response.start"] == [422]
    assert pedidos == 0, f"se pidieron {pedidos} trozos pese a que la cabecera ya bastaba"


# ─────────────────────────────── orden respecto de las credenciales ───────────────────────────────


def test_sin_credenciales_manda_el_403_y_el_cuerpo_no_se_lee(tmp_path: Path) -> None:
    """Fija el orden: el tope va por DENTRO de las credenciales, no por fuera.

    Registrar el tope **después** de ``install_security`` lo dejaría por fuera y esta petición
    respondería 422 tras contar 4 MiB de un cliente que ni siquiera tiene token. Con el orden bueno
    se rechaza con 403 sin leer un byte. Invertir las dos líneas de ``create_app`` pone esto rojo.
    """
    respuesta = _cliente(tmp_path, con_credenciales=False).post(
        "/api/run", content=_GRANDE, headers={"Content-Type": "application/json"}
    )

    assert respuesta.status_code == 403
    assert "límite admitido" not in str(respuesta.json()["detail"])


# ───────────────────────────── un solo límite, un solo número ─────────────────────────────


def test_los_dos_mensajes_del_tope_declaran_el_mismo_limite() -> None:
    """Middleware y handler hablan del mismo límite con las mismas palabras.

    Son dos textos porque el sujeto difiere (el cuerpo de la petición / el archivo ya parseado),
    pero la cola tiene que ser idéntica: dos redacciones del mismo número le harían creer al usuario
    que hay dos límites, que es lo que ``mensaje_de_tope`` existe para evitar.
    """
    from nikodym.ui.datasets import mensaje_de_tope
    from nikodym.ui.security import _mensaje_de_tope

    cola = "supera el límite admitido de 1048576 bytes (1 MiB)."
    assert mensaje_de_tope(9_000_000, 1048576).endswith(cola)
    assert _mensaje_de_tope("anuncia", 9_000_000, 1048576).endswith(cola)
    assert _mensaje_de_tope("ya lleva", 9_000_000, 1048576).endswith(cola)


# ─────────────────────────────── lo que el tope no puede romper ───────────────────────────────


def test_las_rutas_sin_cuerpo_y_el_lifespan_siguen_intactos(tmp_path: Path) -> None:
    """Un GET no tiene cuerpo que contar, y ``lifespan`` no es ``http``: pasan sin tocarse."""
    with _cliente(tmp_path) as cliente:  # el `with` entra y sale del lifespan de la app
        assert cliente.get("/api/schema").status_code == 200
        assert cliente.get("/api/jobs").status_code == 200
        assert cliente.get("/").status_code == 200
