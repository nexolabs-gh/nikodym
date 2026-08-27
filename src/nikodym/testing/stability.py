"""Fuente única de la marca de estabilidad SemVer de cada dominio (D-EST).

`AGENTS.md` promete que **el pipeline scorecard F1 es API estable bajo SemVer 1.x**. Hasta 1.11.0
esa promesa no la derivaba nadie: cada paquete escribía la marca a mano en su *docstring*, ningún
test la comprobaba y la referencia pública enumeraba una tercera lista. Se contradecía en las
dos direcciones a la vez —``model``, que es la regresión logística PD del propio F1, se declaraba
*experimental*, mientras ``audit``, que no es F1, se declaraba *estable*—, de modo que la etiqueta
no significaba nada para quien instala con ``pip``.

Este módulo es la lista canónica, del mismo modo que :mod:`nikodym.testing.regulatory` lo es para la
cobertura regulatoria. Lo consumen el gate ``tests/unit/test_marca_estabilidad.py`` y quien quiera
preguntar, desde código, qué superficie está bajo garantía.

Cambiar una entrada de aquí **es** cambiar un compromiso público: lo que entra no puede romper hasta
un 2.0, y lo que sale restringe una garantía ya publicada. Exige decisión explícita registrada en
``docs/design/DECISIONES-VIGENTES.md``, no la preferencia de quien edita.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = [
    "EXPERIMENTAL_DOMAINS",
    "STABLE_DOMAINS",
    "UNMARKED_PACKAGES",
    "declared_stability",
    "domain_packages",
]

STABLE_DOMAINS: Final[tuple[str, ...]] = (
    # Los nueve dominios del pipeline scorecard F1, en orden de ejecución. `model` incluido: es la
    # regresión logística PD que sostiene el scorecard, y SDD-08 la declara F1 desde su cabecera.
    "data",
    "eda",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    # El informe HTML es parte de la promesa de F1: `api.md` lo enumera junto a los dominios.
    "report",
    # `audit` no pertenece a F1. Entra por decisión de producto de Cami (2026-08-27, D-EST-3): el
    # trail JSONL, el hashing y el replay ya son superficie de integración de terceros, y romperlos
    # en un minor costaría más que el compromiso de sostenerlos.
    "audit",
)
"""Dominios bajo garantía SemVer 1.x: su API pública no rompe hasta un 2.0."""

EXPERIMENTAL_DOMAINS: Final[tuple[str, ...]] = (
    "explain",
    "forward",
    "governance",
    "markov",
    "ml",
    "provisioning",
    "stress",
    "survival",
    "tracking",
    "tuning",
    "validation",
)
"""Superficies que aún crecen: pueden cambiar de forma aditiva o romper dentro de 1.x."""

UNMARKED_PACKAGES: Final[tuple[str, ...]] = (
    # Infraestructura transversal, no un «dominio» con capítulo, preset y config propios. No llevan
    # marca por dominio porque su superficie se documenta pieza a pieza en `api.md`.
    #
    # ⚠️ Abierto conocido: `core` aloja el trío `run` → `Study` → `NikodymConfig`, que `api.md` sí
    # declara estable. Darle marca de paquete ampliaría el compromiso a todo `nikodym.core`, que es
    # más de lo que hoy está decidido; queda registrado como abierto en vez de resuelto por un
    # agente. Ver `DECISIONES-VIGENTES.md` §D-EST.
    "core",
    "testing",
    "ui",
    "utils",
)
"""Paquetes sin marca de estabilidad por dominio, con su razón escrita."""

#: Literales exactos que puede llevar la cabecera de un dominio. Se comparan por igualdad y no por
#: substring: «Experimental (fuera de la garantía SemVer 1.x)» contiene «SemVer 1.x», así que un
#: `in` ingenuo daría por estable justo al que no lo es.
_MARCA_ESTABLE: Final = "**Estable (SemVer 1.x).**"
_MARCA_EXPERIMENTAL: Final = "**Experimental (fuera de la garantía SemVer 1.x).**"

_PACKAGE_ROOT: Final = Path(__file__).resolve().parent.parent


def domain_packages() -> tuple[str, ...]:
    """Enumera los subpaquetes reales de ``nikodym``, leídos del filesystem.

    Se mide el árbol en vez de confiar en las listas de este módulo: es lo que permite que el gate
    detecte un paquete **nuevo** que nadie clasificó, que es el sentido en el que un censo se rompe
    en silencio.
    """
    return tuple(
        sorted(
            path.name
            for path in _PACKAGE_ROOT.iterdir()
            if path.is_dir() and (path / "__init__.py").is_file() and not path.name.startswith("_")
        )
    )


def declared_stability(package: str) -> str | None:
    """Devuelve ``"estable"``, ``"experimental"`` o ``None`` según la cabecera del paquete.

    Lee el ``__init__.py`` como texto en vez de importarlo: importar ``nikodym.ml`` o
    ``nikodym.provisioning`` arrastra dependencias opcionales que el gate no debería exigir.
    """
    init = _PACKAGE_ROOT / package / "__init__.py"
    if not init.is_file():
        return None
    texto = init.read_text(encoding="utf-8")
    if _MARCA_ESTABLE in texto:
        return "estable"
    if _MARCA_EXPERIMENTAL in texto:
        return "experimental"
    return None
