"""Bootstrap del backend FastAPI (SDD-23 §4.3, §7; enmienda B2.2 E-B2.2-7).

:func:`create_app` construye la aplicación con import **perezoso** de FastAPI (el núcleo liviano no
arrastra el extra ``[ui]``) y registra, **en este orden**:

1. las guardas de seguridad local (``Host`` siempre; ``Origin`` + token en los mutadores);
2. el router ``/api``;
3. ``/assets`` y **exactamente** los recursos de raíz que devolvió el preflight;
4. ``/`` y el fallback de navegación de la SPA, ambos con el token inyectado en memoria.

El orden importa: el fallback nunca puede capturar un ``/api/*`` desconocido ni un asset ausente. Un
fallback que responde ``200 text/html`` a ``/assets/perdido.js`` convierte un asset faltante en una
página en blanco sin error, que es el modo de fallo que este contrato prohíbe.

A diferencia de B2.1, **no se monta ``/static``**: dos URLs para el mismo byte son superficie
duplicada, y montar el directorio entero expondría el ``index.html`` crudo —con el placeholder sin
sustituir— y los notices en rutas no contratadas.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nikodym.ui.exceptions import UiDependencyError
from nikodym.ui.routes import build_router
from nikodym.ui.runtime import RuntimeContext
from nikodym.ui.security import install_security
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["create_app"]

#: Cabeceras del index inyectado. `no-store` evita que el token quede en la caché de disco del
#: navegador; `frame-ancestors 'none'` impide que una página remota framee el origen local, que es
#: el paso previo de cualquier intento de operar contra la UI desde fuera.
_NO_STORE = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
}


def create_app(settings: UiConfig, runtime: RuntimeContext) -> FastAPI:
    """Construye la aplicación FastAPI de la UI (import perezoso de FastAPI).

    Parameters
    ----------
    settings : UiConfig
        Ajustes de la app (tema, modo de despliegue, workdir, ...). Se guardan en ``app.state``
        para que las rutas los consulten; no entran al ``config_hash`` (D-UI-3).
    runtime : RuntimeContext
        Contexto del lanzamiento: bind efectivo, build ya verificado por el preflight y token
        efímero. Es **obligatorio**: con un default ``None``, casi toda la suite construiría la app
        sin las guardas de seguridad y los gates pasarían verdes sin ejercitarlas nunca. Los
        consumidores que no son el launcher lo obtienen de
        :func:`nikodym.ui.runtime.build_runtime`.

    Returns
    -------
    FastAPI
        La app con seguridad, ``/api``, assets y SPA navegable.

    Raises
    ------
    UiDependencyError
        Si el extra ``[ui]`` (fastapi/uvicorn) no está instalado.
    """
    try:
        from fastapi import FastAPI
    except ImportError as exc:  # pragma: no cover - guard del extra [ui] ausente
        raise UiDependencyError(
            "la interfaz web requiere el extra 'ui'. Instálalo con: "
            "pip install 'nikodym[ui]' (o uv add 'nikodym[ui]')."
        ) from exc

    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    # Sin `/docs`, `/redoc` ni `/openapi.json`: FastAPI los registra por defecto y sus páginas
    # cargan Swagger UI / ReDoc desde `cdn.jsdelivr.net` con un pin flotante. Serían el único
    # contenido del origen local que ejecuta script de terceros, en el mismo origen donde vive el
    # token — y contradicen de plano el gate anti-request que B2.1 costó tres ciclos. La UI local
    # no es una consola de API; quien quiera explorar el contrato tiene SDD-23 §4.2.
    app = FastAPI(title="Nikodym UI", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.runtime = runtime

    install_security(app, settings, runtime)
    app.include_router(build_router())

    assets_dir = runtime.static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    def _servir_archivo(target: str) -> Callable[[], Awaitable[Any]]:
        """Crea un handler sin parámetros para un recurso fijo del preflight.

        La ruta se cierra sobre `target`. Un parámetro con default —`async def h(target=resource)`—
        parecería equivalente y no lo es: FastAPI lo tomaría por un **query param**, y
        `/favicon.svg?target=../../secreto` serviría cualquier archivo del disco.
        """

        async def _handler() -> Any:
            return FileResponse(runtime.static_dir / target)

        return _handler

    for resource in runtime.resources:
        if not resource.startswith("assets/"):
            app.get(f"/{resource}", include_in_schema=False)(_servir_archivo(resource))

    def _index() -> Any:
        return HTMLResponse(runtime.render_index(), headers=_NO_STORE)

    @app.get("/", include_in_schema=False)
    async def _raiz() -> Any:
        return _index()

    async def _fallback_spa(request: Any, exc: Any) -> Any:
        """Sirve la SPA **sólo** para navegación; nunca enmascara un 404 real.

        Va como handler de 404 y no como ruta catch-all: una ruta `"/{full_path:path}"` competiría
        con el router y con `/assets`, mientras que aquí sólo se entra cuando nada resolvió.
        """
        path = request.url.path
        es_navegacion = (
            not path.startswith("/api/")
            and not path.startswith("/assets/")
            and "." not in path.rsplit("/", 1)[-1]
            and "text/html" in request.headers.get("accept", "")
        )
        if not es_navegacion:
            # `add_exception_handler(404, ...)` se registra por CÓDIGO, así que este handler
            # intercepta también los 404 de dominio de `/api/*`. Propagar el `detail` original es
            # obligatorio: si no, "dataset sintético desconocido: X" le llega al usuario como un
            # "Recurso no encontrado" que no le dice qué arreglar.
            detalle = getattr(exc, "detail", None) or "Recurso no encontrado"
            cabeceras = getattr(exc, "headers", None)
            return JSONResponse(status_code=404, content={"detail": detalle}, headers=cabeceras)
        return _index()

    app.add_exception_handler(404, _fallback_spa)
    return app
