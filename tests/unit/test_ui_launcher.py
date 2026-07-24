"""Tests del launcher, el preflight y las guardas locales (enmienda B2.2, E-B2.2-1…9).

Cubre lo que B2.2 promete al usuario: que `nikodym-ui` no arranca con un build incompleto, que la
SPA servida **funciona** (no sólo navega) y que las guardas rechazan lo que dicen rechazar.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from _ui_client import TEST_PORT, TEST_TOKEN, build_test_runtime, ui_client

from nikodym.ui import __main__ as launcher
from nikodym.ui.exceptions import UiLaunchError
from nikodym.ui.runtime import TOKEN_HEADER, TOKEN_PLACEHOLDER, build_runtime, preflight_static
from nikodym.ui.settings import UiConfig

_INDEX = (
    "<!doctype html><html><head>"
    '<meta name="nikodym-token" content="{tokens}" />'
    '<link rel="icon" href="/favicon.svg" />'
    '<script type="module" src="/assets/app.js"></script>'
    "</head><body><div id=root></div></body></html>"
)


def _static_minimo(tmp_path: Path, *, placeholders: int = 1, con_favicon: bool = True) -> Path:
    """Build estático sintético mínimo: index + favicon + un asset."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets" / "app.js").write_text("export {}", encoding="utf-8")
    if con_favicon:
        (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    marcas = " ".join([TOKEN_PLACEHOLDER] * placeholders) if placeholders else "sin-token"
    (static / "index.html").write_text(_INDEX.format(tokens=marcas), encoding="utf-8")
    return static


# ─────────────────────────────── preflight ───────────────────────────────


def test_preflight_devuelve_index_y_recursos(tmp_path: Path) -> None:
    index, recursos = preflight_static(_static_minimo(tmp_path))

    assert TOKEN_PLACEHOLDER in index
    assert set(recursos) == {"favicon.svg", "assets/app.js"}


def test_preflight_falla_si_falta_un_recurso_local(tmp_path: Path) -> None:
    """El favicon cuenta: 'falta un recurso' incluye el que nadie mira hasta que falta."""
    static = _static_minimo(tmp_path)
    (static / "favicon.svg").unlink()

    with pytest.raises(UiLaunchError, match=r"favicon\.svg"):
        preflight_static(static)


def test_preflight_acumula_todos_los_problemas(tmp_path: Path) -> None:
    """Reparar de a uno por relanzamiento es una experiencia inaceptable."""
    static = _static_minimo(tmp_path, placeholders=0)
    (static / "favicon.svg").unlink()
    (static / "assets" / "app.js").unlink()

    with pytest.raises(UiLaunchError) as error:
        preflight_static(static)
    mensaje = str(error.value)
    assert "favicon.svg" in mensaje
    assert "app.js" in mensaje
    assert TOKEN_PLACEHOLDER in mensaje


@pytest.mark.parametrize("placeholders", [0, 2])
def test_preflight_exige_exactamente_un_placeholder(tmp_path: Path, placeholders: int) -> None:
    """Cero deja la SPA sin token; dos harían que sólo el primero se sustituyera."""
    with pytest.raises(UiLaunchError, match=TOKEN_PLACEHOLDER):
        preflight_static(_static_minimo(tmp_path, placeholders=placeholders))


def test_preflight_rechaza_symlink_que_escapa(tmp_path: Path) -> None:
    """Un symlink que sale de static/ no existe en un ZIP, pero sí en la instalación."""
    static = _static_minimo(tmp_path)
    afuera = tmp_path / "afuera.js"
    afuera.write_text("export {}", encoding="utf-8")
    destino = static / "assets" / "app.js"
    destino.unlink()
    destino.symlink_to(afuera)

    with pytest.raises(UiLaunchError, match="escapa de static/"):
        preflight_static(static)


def test_preflight_falla_sin_index(tmp_path: Path) -> None:
    with pytest.raises(UiLaunchError, match=r"index\.html"):
        preflight_static(tmp_path / "vacio")


# ─────────────────────────────── RuntimeContext ───────────────────────────────


def test_el_token_no_aparece_en_el_repr(tmp_path: Path) -> None:
    """El repr de un dataclass frozen acaba en los tracebacks de Uvicorn/FastAPI."""
    runtime = build_test_runtime(tmp_path, static_dir=_static_minimo(tmp_path))

    assert TEST_TOKEN not in repr(runtime)
    assert TEST_TOKEN not in str(runtime)


def test_render_index_no_toca_el_archivo_en_disco(tmp_path: Path) -> None:
    static = _static_minimo(tmp_path)
    runtime = build_test_runtime(tmp_path, static_dir=static)

    assert TEST_TOKEN in runtime.render_index()
    assert TOKEN_PLACEHOLDER in (static / "index.html").read_text(encoding="utf-8")


def test_token_no_ascii_devuelve_false_y_no_revienta(tmp_path: Path) -> None:
    """`compare_digest` lanza TypeError con str no-ASCII; sería un 500 en vez del 403."""
    runtime = build_test_runtime(tmp_path, static_dir=_static_minimo(tmp_path))

    assert runtime.token_matches("ñ") is False
    assert runtime.token_matches(None) is False
    assert runtime.token_matches("") is False
    assert runtime.token_matches(TEST_TOKEN) is True


# ─────────────────────────────── guardas HTTP ───────────────────────────────


@pytest.fixture
def static(tmp_path: Path) -> Path:
    return _static_minimo(tmp_path)


def _cliente(tmp_path: Path, static: Path, **kwargs: object) -> object:
    runtime = build_test_runtime(tmp_path, static_dir=static)
    settings = UiConfig.model_validate({"workdir": str(tmp_path), **kwargs})
    return ui_client(settings, runtime=runtime)


@pytest.mark.parametrize("host", ["localhost:8000", "nikodym.cl", "127.0.0.1:9999", ""])
def test_host_distinto_del_bind_es_403(tmp_path: Path, static: Path, host: str) -> None:
    """`localhost` se rechaza a propósito: puede resolver a ::1 y habilita DNS rebinding."""
    client = _cliente(tmp_path, static)

    respuesta = client.get("/api/schema", headers={"Host": host})

    assert respuesta.status_code == 403
    assert "Host no admitido" in respuesta.json()["detail"]


def test_host_correcto_pasa(tmp_path: Path, static: Path) -> None:
    assert _cliente(tmp_path, static).get("/api/schema").status_code == 200


@pytest.mark.parametrize(
    ("headers", "esperado"),
    [
        ({}, "Falta el X-Nikodym-Token"),
        ({TOKEN_HEADER: "token-equivocado"}, "Falta el X-Nikodym-Token"),
    ],
)
def test_mutadores_exigen_token(
    tmp_path: Path, static: Path, headers: dict[str, str], esperado: str
) -> None:
    runtime = build_test_runtime(tmp_path, static_dir=static)
    client = ui_client(
        UiConfig.model_validate({"workdir": str(tmp_path)}),
        runtime=runtime,
        con_credenciales=False,
    )

    respuesta = client.post(
        "/api/run",
        json={"config": {}, "dataset_id": "x"},
        headers={"Origin": runtime.origin, **headers},
    )

    assert respuesta.status_code == 403
    assert esperado in respuesta.json()["detail"]
    # El 403 no es un oráculo: no repite el token esperado.
    assert TEST_TOKEN not in respuesta.text


def test_mutadores_exigen_origin_same_origin(tmp_path: Path, static: Path) -> None:
    runtime = build_test_runtime(tmp_path, static_dir=static)
    client = ui_client(
        UiConfig.model_validate({"workdir": str(tmp_path)}),
        runtime=runtime,
        con_credenciales=False,
    )

    respuesta = client.post(
        "/api/run",
        json={"config": {}, "dataset_id": "x"},
        headers={"Origin": "https://evil.example", TOKEN_HEADER: runtime.token},
    )

    assert respuesta.status_code == 403
    assert "Origen no admitido" in respuesta.json()["detail"]


def test_allow_live_execution_false_deniega_upload_y_run_pero_deja_leer(
    tmp_path: Path, static: Path
) -> None:
    """El flag existía en el config y no lo leía nadie: era un freno decorativo."""
    client = _cliente(tmp_path, static, allow_live_execution=False)

    correr = client.post("/api/run", json={"config": {}, "dataset_id": "x"})
    subir = client.post("/api/upload", files={"file": ("d.csv", b"a,b\n1,2\n", "text/csv")})

    assert correr.status_code == 403
    assert subir.status_code == 403
    assert "ejecución en vivo está deshabilitada" in correr.json()["detail"]
    # La lectura sigue disponible: el flag apaga ejecutar, no consultar.
    assert client.get("/api/schema").status_code == 200
    assert client.get("/api/datasets").status_code == 200


# ─────────────────────────────── rutas y SPA ───────────────────────────────


def test_raiz_sirve_el_index_inyectado_sin_cache(tmp_path: Path, static: Path) -> None:
    respuesta = _cliente(tmp_path, static).get("/")

    assert respuesta.status_code == 200
    assert TEST_TOKEN in respuesta.text
    assert TOKEN_PLACEHOLDER not in respuesta.text
    assert respuesta.headers["cache-control"] == "no-store"


def test_el_fallback_tambien_va_sin_cache(tmp_path: Path, static: Path) -> None:
    """Sirve el mismo token que `/`: cachearlo deja el token en disco y rompe el relanzamiento."""
    respuesta = _cliente(tmp_path, static).get("/resultados", headers={"Accept": "text/html"})

    assert respuesta.status_code == 200
    assert TEST_TOKEN in respuesta.text
    assert respuesta.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/inexistente",
        "/assets/perdido.js",
        "/favicon-que-no-existe.svg",
    ],
)
def test_el_fallback_no_enmascara_un_404(tmp_path: Path, static: Path, ruta: str) -> None:
    """Un 200 text/html en un asset ausente convierte el fallo en una página en blanco."""
    respuesta = _cliente(tmp_path, static).get(ruta, headers={"Accept": "text/html"})

    assert respuesta.status_code == 404


def test_static_ya_no_se_monta(tmp_path: Path, static: Path) -> None:
    """Andamio de B2.1: dos URLs para el mismo byte, y el index crudo expuesto."""
    client = _cliente(tmp_path, static)

    assert client.get("/static/index.html").status_code == 404


def test_los_recursos_de_raiz_del_preflight_se_sirven(tmp_path: Path, static: Path) -> None:
    client = _cliente(tmp_path, static)

    assert client.get("/favicon.svg").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


# ─────────────────────────────── CLI ───────────────────────────────


@pytest.mark.parametrize("argv", [["--port", "80"], ["--port", "70000"], ["--port", "cero"]])
def test_puertos_invalidos_fallan_en_el_parseo(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        launcher._parser().parse_args(argv)


def test_no_existe_la_opcion_host() -> None:
    """Exponer a red es D-UI-R0; tampoco hay variable de entorno equivalente."""
    with pytest.raises(SystemExit):
        launcher._parser().parse_args(["--host", "0.0.0.0"])

    opciones = {
        accion.option_strings[0] for accion in launcher._parser()._actions if accion.option_strings
    }
    assert "--host" not in opciones
    assert {"--port", "--workdir", "--no-open"} <= opciones


def test_puerto_ocupado_falla_sin_abrir_navegador(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """El navegador no se abre contra un servidor que no arrancó."""
    abierto: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: abierto.append(url))

    ocupado = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ocupado.bind(("127.0.0.1", 0))
    ocupado.listen()
    puerto = ocupado.getsockname()[1]
    try:
        codigo = launcher.main(["--port", str(puerto), "--workdir", str(tmp_path / "wd")])
    finally:
        ocupado.close()

    assert codigo == 2
    assert abierto == []
    assert "No se pudo tomar" in capsys.readouterr().err


def test_preflight_fallido_no_reserva_socket_ni_abre_navegador(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Un backend a medias que parezca una UI sana es un fallo, no una degradación."""
    abierto: list[str] = []
    reservas: list[int] = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: abierto.append(url))
    monkeypatch.setattr(launcher, "_reservar_socket", lambda port: reservas.append(port))

    def _preflight_roto(**kwargs: object) -> object:
        raise UiLaunchError("build incompleto de mentira")

    monkeypatch.setattr(launcher, "build_runtime", _preflight_roto)

    codigo = launcher.main(["--workdir", str(tmp_path / "wd")])

    assert codigo == 2
    assert abierto == []
    assert reservas == []
    assert "build incompleto de mentira" in capsys.readouterr().err


def test_el_launcher_anuncia_la_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Uvicorn omite su mensaje de arranque cuando se le pasan `sockets`."""
    servido: list[int] = []
    monkeypatch.setattr(launcher, "_servir", lambda *a, **k: servido.append(1))

    codigo = launcher.main(["--port", "8123", "--no-open", "--workdir", str(tmp_path / "wd")])

    assert codigo == 0
    assert servido == [1]
    assert "http://127.0.0.1:8123/" in capsys.readouterr().out


def test_el_workdir_se_crea(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(launcher, "_servir", lambda *a, **k: None)
    destino = tmp_path / "nuevo" / "workdir"

    launcher.main(["--port", "8124", "--no-open", "--workdir", str(destino)])

    assert destino.is_dir()


def test_la_fixture_de_tests_usa_loopback_real() -> None:
    """Apuntar la fixture a `testserver` pondría la suite verde y mataría el chequeo de Host."""
    runtime = build_runtime(port=TEST_PORT, workdir=Path("."), token=TEST_TOKEN)

    assert runtime.host == "127.0.0.1"
    assert runtime.expected_host == f"127.0.0.1:{TEST_PORT}"
    assert runtime.origin == f"http://127.0.0.1:{TEST_PORT}"


def test_los_recursos_de_raiz_no_aceptan_parametros(tmp_path: Path, static: Path) -> None:
    """Regresión: el handler NO puede exponer su ruta como query param.

    Escrito con `async def h(target: str = resource)`, FastAPI trataba `target` como parámetro de
    consulta y `/favicon.svg?target=<lo que sea>` servía cualquier archivo alcanzable desde
    `static_dir`. El handler se cierra sobre la ruta y no acepta entrada.
    """
    client = _cliente(tmp_path, static)
    (tmp_path / "secreto.txt").write_text("no debería salir de aquí", encoding="utf-8")

    respuesta = client.get("/favicon.svg", params={"target": "../secreto.txt"})

    assert respuesta.status_code == 200
    assert "secreto" not in respuesta.text
    assert respuesta.text == "<svg/>"
