"""Bootstrap del backend FastAPI (SDD-23 §4.3, §7).

:func:`create_app` construye la aplicación FastAPI con import **perezoso** de FastAPI (el núcleo
liviano no arrastra el extra ``[ui]``): monta el router de :mod:`nikodym.ui.routes` y sirve el
build estático de la SPA en ``/static`` **solo si** el directorio existe (aún no hay build → guard,
no falla). Si el extra ``[ui]`` no está instalado, levanta :class:`UiDependencyError` con
``instale nikodym[ui]``. No hay ``__main__``/console-script todavía (eso es B23.6).
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
