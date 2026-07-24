"""Launcher de la interfaz web local: ``nikodym-ui`` (enmienda B2.2, E-B2.2-3…5).

Uso típico::

    pip install "nikodym[ui]"
    nikodym-ui                 # 127.0.0.1:8000, abre el navegador y usa .nikodym_ui/

Acepta ``--port``, ``--workdir`` y ``--no-open``. **No ofrece ``--host``**: el bind es fijo a
loopback y exponer la ejecución en vivo a la red es una decisión diferida (D-UI-R0). Tampoco hay una
variable de entorno equivalente — una puerta trasera no declarada es peor que una opción declarada.

``python -m nikodym.ui`` y el console script recorren exactamente el mismo camino.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from nikodym.ui.exceptions import UiError
from nikodym.ui.runtime import LOOPBACK_HOST, RuntimeContext, build_runtime
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:  # pragma: no cover - sólo para tipos
    from uvicorn import Server

__all__ = ["main"]

_PUERTO_MINIMO = 1024
_PUERTO_MAXIMO = 65535
_ESPERA_NAVEGADOR = 15.0


def _puerto(valor: str) -> int:
    """Valida el puerto en el parseo: por debajo de 1024 es privilegiado, no una preferencia."""
    try:
        numero = int(valor)
    except ValueError:
        raise argparse.ArgumentTypeError(f"puerto inválido: {valor!r}") from None
    if not _PUERTO_MINIMO <= numero <= _PUERTO_MAXIMO:
        raise argparse.ArgumentTypeError(
            f"puerto fuera de rango: {numero} (admitidos {_PUERTO_MINIMO}..{_PUERTO_MAXIMO})"
        )
    return numero


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nikodym-ui",
        description=(
            "Levanta la interfaz web de Nikodym en 127.0.0.1 y abre el navegador. "
            "El bind es siempre local: no existe --host."
        ),
    )
    parser.add_argument(
        "--port", type=_puerto, default=8000, help="puerto local (1024..65535; por defecto 8000)"
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        # El default sale del propio modelo: duplicar ".nikodym_ui" aquí lo desincronizaría en
        # silencio el día que UiConfig cambie.
        default=Path(str(UiConfig.model_fields["workdir"].default)),
        help="directorio de trabajo para corridas y datasets (por defecto .nikodym_ui)",
    )
    parser.add_argument(
        "--no-open", action="store_true", help="no abrir el navegador automáticamente"
    )
    return parser


def _reservar_socket(port: int) -> socket.socket:
    """Toma el puerto **antes** de construir nada más y se lo cede luego a Uvicorn.

    Comprobar que el puerto está libre y dejar que Uvicorn lo tome después deja una ventana en la
    que otro proceso puede quedárselo: el navegador abriría contra un servidor ajeno en loopback.
    """
    reservado = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        reservado.bind((LOOPBACK_HOST, port))
    except OSError as error:
        reservado.close()
        raise UiError(
            f"No se pudo tomar {LOOPBACK_HOST}:{port} ({error.strerror or error}). "
            "Probablemente ya hay algo escuchando ahí; use otro puerto: nikodym-ui --port 8001"
        ) from error
    return reservado


def _abrir_cuando_arranque(server: Server, url: str) -> None:
    """Abre el navegador sólo cuando el servidor acepta conexiones; nunca antes."""
    limite = time.monotonic() + _ESPERA_NAVEGADOR
    while not server.started:
        if time.monotonic() > limite:  # pragma: no cover - el arranque local es inmediato
            return
        time.sleep(0.05)
    webbrowser.open(url)


def _servir(
    runtime: RuntimeContext, settings: UiConfig, reservado: socket.socket, abrir: bool
) -> None:
    import uvicorn

    from nikodym.ui.server import create_app

    app = create_app(settings, runtime)
    server = uvicorn.Server(uvicorn.Config(app, log_level="info"))
    if abrir:
        threading.Thread(
            target=_abrir_cuando_arranque, args=(server, runtime.url), daemon=True
        ).start()
    # `serve()` es una corrutina; el entry point síncrono es `run()`. Con `sockets` presente Uvicorn
    # reutiliza el socket ya reservado y no vuelve a bindear.
    server.run(sockets=[reservado])


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de ``nikodym-ui``; devuelve el código de salida del proceso."""
    args = _parser().parse_args(argv)
    workdir = Path(args.workdir).expanduser()
    # `model_validate` y no `UiConfig(workdir=...)`: el __init__ tipado de Pydantic exige todos los
    # campos y aquí sólo se sobreescribe uno; el resto son los defaults del modelo.
    settings = UiConfig.model_validate({"workdir": str(workdir)})

    reservado: socket.socket | None = None
    try:
        # El preflight ocurre ANTES de bind: si el build está incompleto no se levanta un backend
        # REST que parezca una UI sana, y el navegador no se abre.
        runtime = build_runtime(port=args.port, workdir=workdir, static_dir=None)
        reservado = _reservar_socket(args.port)
        workdir.mkdir(parents=True, exist_ok=True)
        # Uvicorn omite su mensaje de arranque cuando se le pasan `sockets`: sin este print, con
        # --no-open el usuario se queda sin saber dónde entrar.
        print(f"Nikodym UI en {runtime.url}  (Ctrl-C para salir)")
        _servir(runtime, settings, reservado, abrir=not args.no_open)
    except UiError as error:
        print(f"nikodym-ui: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interacción del usuario
        return 130
    finally:
        # El socket se cierra pase lo que pase: si `_servir` revienta o no llega a consumirlo, un
        # descriptor colgando deja el puerto tomado por un proceso que ya no sirve nada.
        if reservado is not None:
            reservado.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - ejecución directa
    raise SystemExit(main())
