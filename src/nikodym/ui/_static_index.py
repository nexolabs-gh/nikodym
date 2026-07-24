"""Semántica canónica de los recursos locales del ``index.html`` de la SPA.

Este módulo es la **única** implementación de «qué referencia el index y a qué ruta local resuelve».
La consumen dos lados con sustratos distintos (enmienda B2.2, E-B2.2-6):

- ``scripts/check_distribution_contents.py`` la aplica sobre los **miembros de un ZIP/TAR** al
  auditar el candidate en CI;
- el launcher (``nikodym.ui.__main__``) la aplica sobre el **filesystem instalado** en el preflight,
  antes de bind.

Vivía en el script de gate, que **no viaja en el wheel**: el launcher corre donde ese archivo no
existe. Copiarla habría creado dos fuentes de verdad sobre un control de seguridad —la clase de
deriva silenciosa que costó tres ciclos de revisión en B2.1—, así que la semántica se distribuye y
el script la importa.

El módulo es **puro** (sólo stdlib): no importa FastAPI/Starlette ni toca el filesystem, de modo que
``import nikodym.ui.server`` sigue sin arrastrar el extra ``[ui]`` (SDD-25 §6, invariante de núcleo
liviano). Quien verifica la existencia de cada ruta es el llamador, en su propio sustrato.

Referencias normativas del parseo: WHATWG HTML §13.2.5.6 y §13.2.5.40.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from nikodym.ui.exceptions import UiStaticIndexError

__all__ = [
    "IndexResourceParser",
    "UiStaticIndexError",
    "local_resource_path",
    "resolve_local_resources",
    "unquote_strict",
]

#: ``rel`` que implican carga o resolución automática de un recurso (no navegación deliberada).
_AUTOMATIC_LINK_RELS = frozenset(
    {
        "stylesheet",
        "icon",
        "preload",
        "modulepreload",
        "preconnect",
        "prefetch",
        "dns-prefetch",
        "manifest",
        "apple-touch-icon",
        "prerender",
    }
)


class IndexResourceParser(HTMLParser):
    """Recolecta las referencias **automáticas** del index (no la navegación deliberada).

    ``a``/``area`` y los ``link`` sin ``rel`` de carga son navegación que el usuario decide seguir;
    todo lo demás —``src``, ``srcset``, ``data`` de ``object``, ``poster``, ``background``,
    ``xlink:href``, ``meta http-equiv=refresh``— lo trae el navegador solo y debe existir en local.
    """

    def __init__(self) -> None:
        super().__init__()
        self.resources: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Acumula en :attr:`resources` cada referencia automática del tag."""
        names = [name.casefold() for name, _value in attrs]
        if len(names) != len(set(names)):
            raise UiStaticIndexError(f"Atributo HTML duplicado en <{tag}>")
        values = {name.casefold(): value or "" for name, value in attrs}
        if values.get("srcdoc"):
            raise UiStaticIndexError(f"srcdoc no vacío prohibido en <{tag}>")
        if values.get("src"):
            self.resources.add(values["src"])
        for attribute in ("srcset", "imagesrcset"):
            for candidate in values.get(attribute, "").split(","):
                url = candidate.strip().split(maxsplit=1)[0] if candidate.strip() else ""
                if url:
                    self.resources.add(url)
        if tag == "object" and values.get("data"):
            self.resources.add(values["data"])
        if values.get("poster"):
            self.resources.add(values["poster"])
        if values.get("background"):
            self.resources.add(values["background"])
        if tag not in {"a", "area", "link"} and values.get("href"):
            self.resources.add(values["href"])
        if tag not in {"a", "area"} and values.get("xlink:href"):
            self.resources.add(values["xlink:href"])
        if tag == "link" and values.get("href"):
            rel = set(values.get("rel", "").lower().split())
            if rel & _AUTOMATIC_LINK_RELS:
                self.resources.add(values["href"])
        if (
            tag == "meta"
            and values.get("http-equiv", "").casefold() == "refresh"
            and values.get("content")
        ):
            match = re.search(r"url\s*=\s*(.+)$", values["content"], re.IGNORECASE)
            separator = re.search(r"[;,]", values["content"])
            fallback = values["content"][separator.end() :].strip() if separator is not None else ""
            target = match.group(1) if match is not None else fallback
            if target:
                self.resources.add(target.strip("\"' "))


def unquote_strict(value: str) -> str:
    """Decodifica porcentajes rechazando traversal y codificación excesiva.

    ``%2e``/``%2f``/``%5c`` se rechazan **antes** de decodificar: un ``..%2f`` que sólo se validara
    tras el ``unquote`` escaparía del directorio.
    """
    decoded = value
    for _ in range(5):
        if re.search(r"%(?:2e|2f|5c)", decoded, re.IGNORECASE):
            raise UiStaticIndexError(f"Separador/traversal porcentual prohibido: {value!r}")
        next_value = unquote(decoded)
        if next_value == decoded:
            return decoded
        decoded = next_value
    raise UiStaticIndexError(f"Codificación porcentual excesiva: {value!r}")


def local_resource_path(resource: str, static_prefix: str) -> str | None:
    """Resuelve una referencia del index a su ruta local bajo ``static_prefix``.

    Parameters
    ----------
    resource : str
        Valor crudo del atributo (``/assets/index-abc.js``, ``favicon.svg``, ...).
    static_prefix : str
        Prefijo del directorio estático en el sustrato del llamador (``nikodym/ui/static`` en el
        wheel, ``src/nikodym/ui/static`` en el sdist, ``static`` relativo en el filesystem).

    Returns
    -------
    str | None
        Ruta POSIX resuelta, o ``None`` si la referencia es un fragmento (``#...``) y no exige
        ningún archivo.

    Raises
    ------
    UiStaticIndexError
        Si la referencia es externa, trae un separador inseguro o escapa del directorio estático.
    """
    decoded = unquote_strict(resource.strip())
    if decoded.startswith("#"):
        return None
    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc or decoded.startswith("//"):
        raise UiStaticIndexError(f"Recurso automático externo prohibido: {resource!r}")
    relative = parsed.path.lstrip("/")
    if "\\" in relative:
        raise UiStaticIndexError(f"Separador inseguro en recurso: {resource!r}")
    resource_path = PurePosixPath(relative)
    if resource_path.is_absolute() or ".." in resource_path.parts or not relative:
        raise UiStaticIndexError(f"Recurso local escapa static/: {resource}")
    return PurePosixPath(static_prefix, resource_path).as_posix()


def resolve_local_resources(index_html: str, static_prefix: str) -> tuple[tuple[str, str], ...]:
    """Parsea el index y devuelve los pares ``(referencia original, ruta local)``, ordenados.

    Los fragmentos se descartan. **No** comprueba existencia: eso lo hace el llamador contra su
    sustrato (miembros del archivo en el checker; archivos regulares en el launcher).
    """
    parser = IndexResourceParser()
    parser.feed(index_html)
    resolved: list[tuple[str, str]] = []
    for resource in sorted(parser.resources):
        local = local_resource_path(resource, static_prefix)
        if local is not None:
            resolved.append((resource, local))
    return tuple(resolved)
