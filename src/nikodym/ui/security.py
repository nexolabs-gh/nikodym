"""Guardas de la UI local: ``Host`` exacto siempre, ``Origin`` + token en los mutadores.

Contrato aprobado en B2.0 (D-UI-12) y precisado en la enmienda B2.2 (E-B2.2-2). El modelo protege
contra **sitios web remotos y el navegador**, no contra un atacante ya dentro de la sesión del
usuario; los límites conocidos están declarados en la enmienda (L1…L7) en vez de quedar implícitos.

El framework se importa **dentro** de :func:`install_security`, nunca a nivel de módulo: la suite
afirma que ``import nikodym.ui.server`` no arrastra FastAPI/Starlette (núcleo liviano), y un
``from starlette… import …`` al tope es el modo natural de romper ese invariante sin darse cuenta.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nikodym.ui.runtime import TOKEN_HEADER, RuntimeContext
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["CREDENTIALED_PATHS", "MUTATING_PATHS", "install_security"]

#: Endpoints que escriben o ejecutan; exigen ``Origin`` same-origin y token además del ``Host``.
MUTATING_PATHS = frozenset({"/api/upload", "/api/run"})

#: Endpoints que exigen las mismas credenciales que un mutador pero **no ejecutan el pipeline**.
#:
#: ``/api/preflight`` materializa el dataset para leerle el esquema, así que escribe en el
#: ``workdir`` y no puede quedar abierto a cualquier proceso local —el token existe justamente
#: porque el bind a loopback no se considera suficiente—. Pero comprobar no es correr: dejarlo en
#: :data:`MUTATING_PATHS` lo habría apagado con ``allow_live_execution=false``, que es el modo en
#: el que un aviso de config↔dataset más se agradece. De ahí la categoría propia.
CREDENTIALED_PATHS = frozenset({"/api/preflight"})


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

        ruta = request.url.path.rstrip("/")
        if ruta in MUTATING_PATHS or ruta in CREDENTIALED_PATHS:
            if ruta in MUTATING_PATHS and not settings.allow_live_execution:
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
