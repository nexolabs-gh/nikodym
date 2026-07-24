"""Bootstrap del backend FastAPI (SDD-23 §4.3, §7).

:func:`create_app` construye la aplicación FastAPI con import **perezoso** de FastAPI (el núcleo
liviano no arrastra el extra ``[ui]``): monta el router de :mod:`nikodym.ui.routes` y expone los
archivos del build estático versionado bajo ``/static`` **solo si** el directorio existe (el guard
también cubre instalaciones incompletas sin fallar al importar). Si el extra ``[ui]`` no está
instalado, levanta :class:`UiDependencyError` con ``instale nikodym[ui]``.

.. warning::
   Exponer los archivos **no** equivale todavía a servir la SPA navegable: el ``index.html`` del
   build referencia sus recursos con base absoluta (``/assets/...``, ``/favicon.svg``), de modo que
   abrir ``/static/index.html`` devuelve 404 en esos recursos y renderiza una página en blanco. El
   servido navegable —orden de rutas API → assets → fallback SPA— es alcance de **B2.2**, igual que
   el ``__main__``/console-script. B2.1 sólo garantiza que el build distribuido es correcto y
   auditable, no que ya sea alcanzable por el usuario final.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nikodym.ui.exceptions import UiDependencyError
from nikodym.ui.routes import build_router
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["create_app"]


def _static_dir() -> Path:
    """Directorio del build estático de la SPA (``nikodym/ui/static``), montado si existe."""
    return Path(__file__).resolve().parent / "static"


def create_app(settings: UiConfig) -> FastAPI:
    """Construye la aplicación FastAPI de la UI (import perezoso de FastAPI).

    Parameters
    ----------
    settings : UiConfig
        Ajustes de la app (tema, modo de despliegue, workdir, ...). Se guardan en ``app.state``
        para que las rutas los consulten; no entran al ``config_hash`` (D-UI-3).

    Returns
    -------
    FastAPI
        La app con el router ``/api`` montado y ``/static`` si hay build.

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

    app = FastAPI(title="Nikodym UI")
    app.state.settings = settings
    app.include_router(build_router())

    static_dir = _static_dir()
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="static")
    return app
