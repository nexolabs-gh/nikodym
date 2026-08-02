"""Guardas de la UI local: tope del cuerpo, ``Host`` exacto siempre, ``Origin`` + token al mutar.

Contrato aprobado en B2.0 (D-UI-12) y precisado en la enmienda B2.2 (E-B2.2-2). El modelo protege
contra **sitios web remotos y el navegador**, no contra un atacante ya dentro de la sesión del
usuario; los límites conocidos están declarados en la enmienda (L1…L7) en vez de quedar implícitos.

Hay **dos** guardas, y se instalan por separado porque su orden es una decisión con consecuencia:

- :func:`install_body_limit` — tope del **cuerpo de la petición**, contado sobre el stream ASGI.
- :func:`install_security` — ``Host``, ``Origin`` y token, clasificando el par **(método, ruta)**;
  ver el bloque sobre las tres listas más abajo, que explica qué agujero cierra esa forma y por qué
  un template parametrizado no cabe en las dos listas protegidas.

El framework se importa **dentro** de cada instalador, nunca a nivel de módulo: la suite afirma que
``import nikodym.ui.server`` no arrastra FastAPI/Starlette (núcleo liviano), y un ``from starlette…
import …`` al tope es el modo natural de romper ese invariante sin darse cuenta.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from nikodym.ui.runtime import TOKEN_HEADER, RuntimeContext
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = [
    "CREDENTIALED_PATHS",
    "MUTATING_PATHS",
    "PUBLIC_PATHS",
    "install_body_limit",
    "install_security",
]

# ── Qué clasifican estas tres listas ───────────────────────────────────────────────────────────
#
# El elemento de las tres es el par **(método HTTP, ruta)**, no la ruta sola. Clasificar sólo la
# ruta colapsaba verbos distintos en una misma decisión, y eso no es teórico: añadir un
# ``@router.post("/schema")`` con efectos mutadores dejaba el conjunto de rutas **idéntico** —el
# gate seguía en verde con 17 rutas y 0 sin clasificar— y el middleware tampoco lo habría cerrado,
# porque ``/api/schema`` está declarada pública por su GET. Con el par no hay colapso posible: un
# verbo nuevo es una entrada nueva, y si no está clasificada el gate se pone rojo.
#
# ⚠️ Una ruta **parametrizada** (``/api/report/{run_id}``) no puede vivir en las dos listas
# protegidas. El middleware compara la URL **concreta** por igualdad, así que
# ``/api/report/20260802T101010-abcd`` no casaría jamás con su template y la guarda existiría en el
# papel pero no en la ejecución. La limitación se **declara** en vez de callarse —mismo criterio
# que D-PRE-4 con el alcance del preflight— y la hace cumplir ``test_ui_rutas_clasificadas.py``.
# En :data:`PUBLIC_PATHS` sí son válidas: esa lista es declarativa y el middleware no la consulta
# para abrir nada.
#
# El nombre ``*_PATHS`` se conserva pese a que ya no guarda rutas sueltas: lo citan la enmienda
# D-PUE-9 y el índice de diseño, y renombrarlo dejaría esos documentos apuntando a nada a cambio
# de nada.

#: Endpoints que escriben o ejecutan; exigen ``Origin`` same-origin y token además del ``Host``.
MUTATING_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/upload"),
        ("POST", "/api/run"),
    }
)

#: Endpoints que exigen las mismas credenciales que un mutador pero **no ejecutan el pipeline**.
#:
#: ``/api/preflight`` materializa el dataset para leerle el esquema, así que escribe en el
#: ``workdir`` y no puede quedar abierto a cualquier proceso local —el token existe justamente
#: porque el bind a loopback no se considera suficiente—. Pero comprobar no es correr: dejarlo en
#: :data:`MUTATING_PATHS` lo habría apagado con ``allow_live_execution=false``, que es el modo en
#: el que un aviso de config↔dataset más se agradece. De ahí la categoría propia.
CREDENTIALED_PATHS: frozenset[tuple[str, str]] = frozenset({("POST", "/api/preflight")})

#: Endpoints que **a propósito** no exigen credenciales, cada uno con su razón (D-PUE-9).
#:
#: A diferencia de las otras dos listas, ésta **no la consume el middleware**: es una declaración
#: que el gate ``test_ui_rutas_clasificadas.py`` hace obligatoria. Existe porque hasta el
#: 2026-08-01 una ruta sin credenciales era indistinguible de un olvido — y ése fue exactamente el
#: estado en que ``/api/preflight`` se coló sin token, con la suite entera en verde, hasta que una
#: auditoría adversarial lo encontró. Obligar a escribir la razón convierte el olvido en un rojo.
#:
#: Las claves son ``(método, template)`` tal como el router expone la ruta
#: (``("GET", "/api/report/{run_id}")``), no una URL concreta.
PUBLIC_PATHS: MappingProxyType[tuple[str, str], str] = MappingProxyType(
    {
        ("GET", "/api/schema"): (
            "Sirve el JSON-Schema del config, que es estructura pública del paquete."
        ),
        ("POST", "/api/validate"): (
            "Valida un config recibido y no toca el disco: es la comprobación que el formulario "
            "dispara en cada tecleo. Sigue así con la puerta de artefactos, porque consume sólo "
            "las CLAVES declaradas y nunca el dataset que las respalda (D-PUE-7)."
        ),
        ("GET", "/api/datasets"): ("Lista el catálogo sintético; no expone los datasets subidos."),
        ("GET", "/api/jobs"): (
            "Cataloga los trabajos: es lo que la landing necesita antes de tener token."
        ),
        ("GET", "/api/config/presets"): "Catálogo de presets de fábrica, sin datos de nadie.",
        ("GET", "/api/config/preset"): "Preset de fábrica F1, contenido del propio paquete.",
        ("GET", "/api/config/preset/{preset_id}"): (
            "Preset de fábrica por id, contenido del propio paquete."
        ),
        ("POST", "/api/config/to-yaml"): (
            "Convierte a YAML el config que el cliente ya tiene; no persiste."
        ),
        ("POST", "/api/config/from-yaml"): ("Parsea el YAML que el cliente ya tiene; no persiste."),
        ("GET", "/api/results/{run_id}"): (
            "Lee una corrida ya hecha. El id lo devuelve quien la ejecutó, que sí llevaba token."
        ),
        ("GET", "/api/report/{run_id}"): "Igual que los resultados: lee un informe ya generado.",
        ("GET", "/api/report/{run_id}/pdf"): (
            "Igual que los resultados: descarga un informe ya generado."
        ),
        ("GET", "/api/report/{run_id}/md"): (
            "Igual que los resultados: descarga un informe ya generado."
        ),
        ("GET", "/api/report/{run_id}/docx"): (
            "Igual que los resultados: descarga un informe ya generado."
        ),
    }
)


# ── Tope del cuerpo de la petición ─────────────────────────────────────────────────────────────
#
# Hasta el 2026-08-02 el único tope vivía en el handler de ``/api/upload`` y se comprobaba con el
# cuerpo **ya recibido y ya parseado**: FastAPI termina el multipart antes de invocar el handler, de
# modo que el archivo rechazado ya había viajado por la red y ya se había escrito al temporal en
# disco. Y los **cinco POST de JSON** (`validate`, `preflight`, `run`, `config/to-yaml`,
# `config/from-yaml`) no tenían tope **de ninguna clase**: tres de ellos son públicos, así que
# cualquier proceso local podía empujarles un cuerpo sin cota. Lo que sigue cierra las dos cosas.


def _mensaje_de_tope(medido: str, tamano: int, max_bytes: int) -> str:
    """Copy del tope superado; la cola es **la misma** que la de ``ui.datasets.mensaje_de_tope``.

    Hay dos textos porque el sujeto es distinto —aquí lo que se envía, allá el archivo ya parseado—
    pero el **límite es uno solo**, y el usuario tiene que leer el mismo número con las mismas
    palabras. Dos redacciones para el mismo número le harían creer que son dos límites, que es
    exactamente lo que ``mensaje_de_tope`` existe para evitar. Lo ata un test que compara las dos
    colas carácter a carácter, para que separarlas no pueda pasar desapercibido.

    El sujeto es «el envío» y no «el cuerpo de la petición»: esta guarda corta también subidas de
    archivo, que es su caso frecuente, y ahí la segunda fórmula sería jerga de HTTP en la pantalla
    de alguien que sólo arrastró un `.csv`. Se mantiene en singular para que la cola case con la del
    handler sin concordancias distintas.
    """
    return (
        f"el envío {medido} {tamano} bytes y supera el límite admitido de "
        f"{max_bytes} bytes ({max_bytes // (1024 * 1024)} MiB)."
    )


def _content_length(scope: Any) -> int | None:
    """El mayor ``Content-Length`` declarado, o ``None`` si no viene o no es un entero.

    Se toma el **máximo** y no el primero: la cabecera es del cliente y sólo se usa para rechazar
    antes de leer, nunca para aceptar, así que ante cabeceras repetidas hay que quedarse con la
    declaración más grande. Con la mínima, un cliente podría duplicar la cabecera para bajar el
    valor que se compara y **saltarse el rechazo temprano** — el contador lo cazaría igual, pero
    después de haber entregado el cuerpo al parser, que es justo lo que se quiere evitar.
    """
    mayor: int | None = None
    for nombre, valor in scope.get("headers", ()):
        if nombre.lower() != b"content-length":
            continue
        try:
            declarado = int(valor)
        except ValueError:
            continue
        mayor = declarado if mayor is None else max(mayor, declarado)
    return mayor


def install_body_limit(app: FastAPI, settings: UiConfig) -> None:
    """Registra el tope del cuerpo de **toda** petición HTTP (import perezoso del framework).

    Cuenta bytes sobre el ``receive`` del stream ASGI y corta en cuanto se pasa del tope, **sin
    acumular el cuerpo**. Cuatro decisiones, cada una con su razón:

    1. **El tope es ``UiConfig.upload_max_mb``, uno solo para JSON y para multipart.** No nace un
       segundo campo «tope de JSON»: sería un número más que el usuario no puede relacionar con el
       primero, y un valor fijo no configurable convertiría en irreparable el día que un config
       legítimo —``data.schema.columns`` de una cartera muy ancha— lo pasara. Lo que este tope
       aporta es pasar de **sin cota** a una cota conocida; afinarlo por endpoint es otra decisión y
       no se toma aquí de tapadillo. ⚠️ Se mide sobre el **cuerpo de la petición**, que en un
       multipart incluye unos cientos de bytes de encabezado de parte: un archivo de exactamente el
       tope se rechaza por ese margen, y por eso el mensaje habla del cuerpo y no del archivo.
    2. **Devuelve 422, no 413.** 413 es el código canónico, pero el tope de ``/api/upload`` ya
       responde 422 —está así en el contrato de SDD-23 §7— y este middleware lo intercepta antes,
       así que elegir 413 cambiaría el código que el usuario ve hoy en un endpoint publicado. Un
       cambio de contrato para ganar precisión semántica se decide en su propio SDD, no de paso.
    3. **``Content-Length`` sólo puede endurecer, jamás relajar.** Si viene y declara más que el
       tope se rechaza **sin invocar la app**: es el único camino que garantiza que el parser no
       corre y que no se escribe ningún temporal, y es el caso de todo navegador real. Si no viene
       (``Transfer-Encoding: chunked``) o miente por lo bajo, el contador lo caza igual. La cabecera
       nunca se usa para dar por bueno un cuerpo.
    4. **Dos mecanismos de respuesta, por una razón estructural.** El rechazo por cabecera ocurre
       **antes** de llamar a la app, o sea fuera del ``ExceptionMiddleware`` —que Starlette apila
       por dentro de todo middleware de usuario—, así que ahí una excepción no tendría quien la
       convirtiera en respuesta y se sirve un ``JSONResponse`` a mano. El corte del contador ocurre
       **dentro**, y levanta ``HTTPException``: FastAPI la re-lanza a propósito al parsear el cuerpo
       (``except HTTPException: raise``, con el comentario «If a middleware raises an HTTPException,
       it should be raised again») y ``MultiPartParser`` sólo atrapa ``MultiPartException``/
       ``OSError``, así que llega limpia. Verificado sobre fastapi 0.138 / starlette 1.3.1.
    """
    from starlette.exceptions import HTTPException
    from starlette.responses import JSONResponse

    max_bytes = settings.upload_max_mb * 1024 * 1024

    class _TopeDeCuerpo:
        """Middleware ASGI puro: envuelve ``receive`` y cuenta lo que pasa por él."""

        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            # `lifespan` y `websocket` pasan intactos: no tienen cuerpo que contar y envolverles el
            # canal sólo podría romperlos.
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return

            declarado = _content_length(scope)
            if declarado is not None and declarado > max_bytes:
                respuesta = JSONResponse(
                    status_code=422,
                    content={"detail": _mensaje_de_tope("anuncia", declarado, max_bytes)},
                )
                await respuesta(scope, receive, send)
                return

            leidos = 0

            async def _contando() -> Any:
                nonlocal leidos
                mensaje = await receive()
                if mensaje.get("type") == "http.request":
                    leidos += len(mensaje.get("body", b""))
                    if leidos > max_bytes:
                        # Se levanta **antes** de devolver el trozo que cruza el tope: quien consume
                        # el cuerpo no llega a verlo, así que no se acumula ni se escribe.
                        raise HTTPException(
                            status_code=422,
                            detail=_mensaje_de_tope("ya lleva", leidos, max_bytes),
                        )
                return mensaje

            await self.app(scope, _contando, send)

    app.add_middleware(_TopeDeCuerpo)


def _categoria(metodo: str, ruta: str) -> Literal["mutador", "credenciales"] | None:
    """Clasifica un par ``(método, ruta)`` concreto para decidir qué guarda le toca.

    Existe como función y no como un ``in`` dentro del middleware porque encierra la regla que
    impide que endurecer *abra* algo: hasta el 2026-08-02 la comparación era por ruta sola, de modo
    que ``/api/run`` estaba cerrado para **cualquier** verbo. Al pasar al par, un verbo no
    contratado sobre una ruta con métodos protegidos —``GET /api/run``— dejaría de casar y saldría
    del alcance de la guarda. Aquí se hereda la categoría de la ruta en ese caso: el par gana
    precisión sin ceder ni un caso de los que ya estaban cerrados.
    """
    clave = (metodo.upper(), ruta)
    if clave in MUTATING_PATHS:
        return "mutador"
    if clave in CREDENTIALED_PATHS:
        return "credenciales"
    if clave in PUBLIC_PATHS:
        return None
    # Verbo que no declara ninguna ruta: si la ruta tiene algún método protegido, se hereda el más
    # estricto. El router responderá 404/405, pero no sin pasar antes por las credenciales.
    if any(ruta == protegida for _, protegida in MUTATING_PATHS):
        return "mutador"
    if any(ruta == protegida for _, protegida in CREDENTIALED_PATHS):
        return "credenciales"
    return None


def install_security(app: FastAPI, settings: UiConfig, runtime: RuntimeContext) -> None:
    """Registra el middleware de seguridad local en ``app`` (import perezoso del framework)."""
    from fastapi.responses import JSONResponse

    def _denegar(detalle: str) -> JSONResponse:
        # El cuerpo jamás repite el token recibido ni el esperado: un 403 no es un oráculo.
        return JSONResponse(status_code=403, content={"detail": detalle})

    @app.middleware("http")
    async def _guardas_locales(request: Any, call_next: Any) -> Any:
        host = request.headers.get("host", "")
        if host != runtime.expected_host:
            # `localhost` se rechaza a propósito: puede resolver a ::1 y es la puerta de entrada
            # clásica al DNS rebinding. La UI se abre siempre por IP de loopback.
            return _denegar(
                f"Host no admitido: {host!r}. La interfaz sólo atiende en "
                f"{runtime.expected_host}; abra {runtime.url}"
            )

        # Se clasifica el par (método, ruta) y se compara la URL **concreta**: por eso el gate
        # prohíbe que un template parametrizado entre en las dos listas protegidas (ver arriba).
        categoria = _categoria(request.method, request.url.path.rstrip("/"))
        if categoria is not None:
            if categoria == "mutador" and not settings.allow_live_execution:
                return _denegar(
                    "La ejecución en vivo está deshabilitada (allow_live_execution=false): "
                    "puede consultar schema, presets, resultados e informes, pero no subir "
                    "datos ni ejecutar."
                )
            if request.headers.get("origin") != runtime.origin:
                return _denegar(
                    "Origen no admitido para esta operación: se exige same-origin exacto "
                    f"({runtime.origin})."
                )
            if not runtime.token_matches(request.headers.get(TOKEN_HEADER)):
                return _denegar(
                    f"Falta el {TOKEN_HEADER} de esta sesión o no es válido. Recargue "
                    f"{runtime.url}; si relanzó la interfaz, el token anterior ya no sirve."
                )

        return await call_next(request)
