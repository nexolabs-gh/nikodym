"""Estado de un lanzamiento de la UI local (enmienda B2.2, E-B2.2-1).

:class:`RuntimeContext` transporta lo que el launcher resuelve **una vez por lanzamiento**: el bind
loopback, el directorio de trabajo, el build estático ya verificado y el token efímero de 256 bits.
Es inmutable y **no serializable a propósito**: no es config del usuario, no entra al
``config_hash`` (D-UI-3) y nunca se vuelca. :class:`~nikodym.ui.settings.UiConfig` sigue siendo el
único config de la herramienta.

El módulo es puro (stdlib): no importa FastAPI ni Uvicorn, de modo que ``import nikodym.ui.server``
sigue sin arrastrar el extra ``[ui]`` (invariante de núcleo liviano, SDD-25 §6).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path

from nikodym.ui._static_index import resolve_local_resources
from nikodym.ui.exceptions import UiLaunchError, UiStaticIndexError

__all__ = [
    "LOOPBACK_HOST",
    "TOKEN_HEADER",
    "TOKEN_PLACEHOLDER",
    "RuntimeContext",
    "build_runtime",
    "preflight_static",
]

#: Único bind admitido en `1.6.0`. No existe `--host`: exponer a red es D-UI-R0 (decisión de Cami).
LOOPBACK_HOST = "127.0.0.1"

#: Header por el que la SPA envía el token. Fijado por contrato para que front y back no diverjan.
TOKEN_HEADER = "X-Nikodym-Token"

#: Marca que el build distribuido lleva **exactamente una vez**; se sustituye en memoria al servir.
TOKEN_PLACEHOLDER = "__NIKODYM_TOKEN__"


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Contexto inmutable de un lanzamiento; el token nunca aparece en su ``repr``.

    ``repr=False`` en el token no es cosmética: un ``dataclass`` frozen genera un ``__repr__`` con
    todos sus campos, y ese repr acaba en los tracebacks de Uvicorn/FastAPI.
    """

    port: int
    workdir: Path
    static_dir: Path
    index_template: str
    resources: tuple[str, ...]
    host: str = LOOPBACK_HOST
    token: str = field(repr=False, default="")

    @property
    def origin(self) -> str:
        """Origen exacto que se exige en los mutadores (``http://127.0.0.1:<puerto>``)."""
        return f"http://{self.host}:{self.port}"

    @property
    def expected_host(self) -> str:
        """Valor exacto admitido en el header ``Host`` (``127.0.0.1:<puerto>``)."""
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        """URL que se imprime y se abre en el navegador; **nunca** lleva el token."""
        return f"{self.origin}/"

    def token_matches(self, candidate: str | None) -> bool:
        """Compara el token en tiempo constante y sin reventar con entradas no-ASCII.

        ``secrets.compare_digest`` lanza ``TypeError`` con ``str`` no-ASCII, y Starlette decodifica
        las cabeceras en latin-1: comparar sobre ``str`` convertiría un header con un byte ``0xF1``
        en un 500 en vez del 403 contratado. Por eso se compara sobre ``bytes``.
        """
        if not candidate:
            return False
        expected = self.token.encode("utf-8", "surrogateescape")
        received = candidate.encode("utf-8", "surrogateescape")
        return secrets.compare_digest(expected, received)

    def render_index(self) -> str:
        """Devuelve el index con el token inyectado **en memoria**.

        El archivo en disco conserva el placeholder: nunca se reescribe, para que un lanzamiento no
        deje el token de la sesión anterior dentro del paquete instalado.
        """
        return self.index_template.replace(TOKEN_PLACEHOLDER, self.token, 1)


def default_static_dir() -> Path:
    """Directorio del build estático distribuido (``nikodym/ui/static``)."""
    return Path(__file__).resolve().parent / "static"


def preflight_static(static_dir: Path) -> tuple[str, tuple[str, ...]]:
    """Valida el build estático **antes de bind** y devuelve ``(index, recursos locales)``.

    Aplica la semántica canónica de :mod:`nikodym.ui._static_index` —la misma que el gate de
    distribución usa en CI— sobre el filesystem instalado. Comprueba, además de lo que comprueba el
    gate, lo que sólo existe en disco: que cada recurso sea un **archivo regular** y que no escape
    de ``static_dir`` a través de un symlink.

    Returns
    -------
    tuple[str, tuple[str, ...]]
        El index con el placeholder intacto y las rutas locales (relativas a ``static_dir``) que el
        servidor debe exponer.

    Raises
    ------
    UiLaunchError
        Con **todos** los problemas encontrados, no sólo el primero: reparar de a uno por
        relanzamiento es una experiencia inaceptable para un fallo de instalación.
    """
    index_path = static_dir / "index.html"
    if not index_path.is_file():
        raise UiLaunchError(
            f"La interfaz web no está instalada por completo: falta {index_path}. "
            "Reinstale con: pip install --force-reinstall 'nikodym[ui]'."
        )
    try:
        index_html = index_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise UiLaunchError(f"El index de la interfaz no es UTF-8 válido: {index_path}") from error

    try:
        resolved = resolve_local_resources(index_html, "")
    except UiStaticIndexError as error:
        raise UiLaunchError(f"El index de la interfaz es inválido: {error}") from error

    root = static_dir.resolve()
    problems: list[str] = []
    resources: list[str] = []
    for resource, local in resolved:
        target = static_dir / local
        try:
            real = target.resolve()
        except OSError:  # pragma: no cover - ruta ilegible por el sistema de archivos
            problems.append(f"{resource!r}: no se pudo resolver {target}")
            continue
        if not real.is_relative_to(root):
            problems.append(f"{resource!r}: escapa de static/ ({real})")
        elif not real.is_file():
            problems.append(f"{resource!r}: no es un archivo regular ({target})")
        else:
            resources.append(local)

    placeholders = index_html.count(TOKEN_PLACEHOLDER)
    if placeholders != 1:
        problems.append(
            f"el index debe contener exactamente un {TOKEN_PLACEHOLDER};"
            f" encontrados: {placeholders}"
        )

    if problems:
        detalle = "\n  - ".join(problems)
        raise UiLaunchError(
            "La interfaz web no está instalada por completo. Problemas detectados:\n  - "
            f"{detalle}\nReinstale con: pip install --force-reinstall 'nikodym[ui]'."
        )
    return index_html, tuple(resources)


def build_runtime(
    *,
    port: int,
    workdir: Path,
    static_dir: Path | None = None,
    token: str | None = None,
) -> RuntimeContext:
    """Construye el contexto de un lanzamiento tras un preflight exitoso.

    Es la **factory pública**: el launcher, los tests y los scripts que levantan la app sin servidor
    (capturas de fixtures, smoke de instalación) la usan en vez de instanciar el dataclass a mano,
    que es la vía rápida a varias variantes divergentes del mismo contexto.

    Parameters
    ----------
    token : str | None
        Sólo para escenarios reproducibles (tests). En un lanzamiento real se deja en ``None`` y se
        genera ``secrets.token_bytes(32)``.
    """
    directory = default_static_dir() if static_dir is None else static_dir
    index_template, resources = preflight_static(directory)
    return RuntimeContext(
        port=port,
        workdir=workdir,
        static_dir=directory,
        index_template=index_template,
        resources=resources,
        token=token if token is not None else secrets.token_urlsafe(32),
    )
