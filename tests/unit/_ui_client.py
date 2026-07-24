"""Cliente de test de la UI atado al bind real (enmienda B2.2, E-B2.2-8).

``TestClient`` usa ``base_url="http://testserver"`` por defecto, y el middleware de B2.2 rechaza
cualquier ``Host`` que no sea el bind efectivo. La salida barata ante ese 403 sería construir el
contexto con ``host="testserver"``: la suite se pondría verde y el chequeo de ``Host`` —único
mitigante de DNS rebinding (L2)— no se ejercitaría **nunca**. Por eso el helper vive aquí, ata el
cliente a ``127.0.0.1`` y añade ``Origin`` + token: usarlo es más fácil que esquivarlo.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nikodym.ui.runtime import TOKEN_HEADER, RuntimeContext, build_runtime
from nikodym.ui.server import create_app
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from starlette.testclient import TestClient

__all__ = ["TEST_PORT", "TEST_TOKEN", "build_test_runtime", "ui_client"]

TEST_PORT = 8000

#: Token fijo: los tests necesitan reproducibilidad, no entropía. El token real se genera en el
#: launcher con ``secrets``; aquí sólo se comprueba que el contrato lo exige y lo compara bien.
TEST_TOKEN = "token-de-prueba-no-secreto"


def build_test_runtime(
    workdir: Path | str = ".",
    *,
    static_dir: Path | None = None,
    token: str = TEST_TOKEN,
    port: int = TEST_PORT,
) -> RuntimeContext:
    """Construye un contexto de prueba con la misma factory que usa el launcher."""
    return build_runtime(port=port, workdir=Path(workdir), static_dir=static_dir, token=token)


def ui_client(
    settings: UiConfig | None = None,
    *,
    runtime: RuntimeContext | None = None,
    con_credenciales: bool = True,
) -> TestClient:
    """Devuelve un ``TestClient`` de la app con el ``Host`` correcto y, por defecto, credenciales.

    Parameters
    ----------
    con_credenciales : bool
        ``False`` omite ``Origin`` y token para ejercitar los rechazos de los mutadores.
    """
    from starlette.testclient import TestClient

    resolved_settings = UiConfig() if settings is None else settings
    resolved_runtime = build_test_runtime(resolved_settings.workdir) if runtime is None else runtime
    headers = (
        {"Origin": resolved_runtime.origin, TOKEN_HEADER: resolved_runtime.token}
        if con_credenciales
        else {}
    )
    return TestClient(
        create_app(resolved_settings, resolved_runtime),
        base_url=resolved_runtime.origin,
        headers=headers,
    )
