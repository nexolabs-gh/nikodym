"""Gate: la prosa del sitio escribe los decimales con coma (enmienda COPY-PRUEBA-REAL-SBA, D-CPY-5).

Medido el 2026-09-24: ``tutorial.md``, ``guias/binning-seleccion.md`` y
``guias/modelo-calibracion.md`` escribían las cifras con punto decimal (136 en total) y el resto de
las guías con coma. Todo el copy es es-CL: la coma es el separador decimal y el punto, el de miles.

**Qué cuenta como texto visible.** Todo lo que no es código: se excluyen los bloques de código, el
código en línea —``min_iv = 0.02`` es un parámetro y Python lo escribe con punto— y una lista
corta y
explícita de formas que no son decimales: versiones (``versión 1.0``, ``0.20.0``, ``Apache-2.0``,
``1.x``, las versiones de Python), la notación científica y los miles es-CL (``6.000``, ``3.961``).

⚠️ **Qué NO puede ver.** Un decimal de tres cifras con parte entera distinta de cero (``1.002``) se
lee igual que un miles es-CL y no se puede distinguir sin contexto: ese caso lo cubre la conversión
hecha a mano, no este gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_DOCS = _RAIZ / "docs_site"

#: Un decimal con punto, como se escribiría en inglés: dígitos, punto, dígitos, sin más puntos.
_DECIMAL_CON_PUNTO = re.compile(r"(?<![\w.,])\d+\.\d+(?!\w|\.\d)")
#: Formas que no son un decimal, y que el texto visible puede traer con punto.
_NO_DECIMALES: tuple[re.Pattern[str], ...] = (
    re.compile(r"versi[oó]n \d+(?:\.\d+)+"),
    re.compile(r"\d+\.\d+\.\d+"),
    re.compile(r"[A-Za-z]-\d+\.\d+"),
    re.compile(r"Python\W*≥\s*\d+\.\d+"),
    re.compile(r"probado en \d+\.\d+(?:, \d+\.\d+)* y \d+\.\d+"),
    re.compile(r"(?<![\d.,])[1-9]\d{0,2}(?:\.\d{3})+(?:,\d+)?(?!\d)"),
)


def texto_visible(markdown: str) -> str:
    """El texto que se lee: sin código (en bloque ni en línea) ni formas que no son decimales."""
    lineas: list[str] = []
    en_bloque = False
    for linea in markdown.splitlines():
        if linea.lstrip().startswith(("```", "~~~")):
            en_bloque = not en_bloque
            continue
        if en_bloque:
            continue
        sin_codigo = re.sub(r"`[^`]*`", " ", linea)
        for patron in _NO_DECIMALES:
            sin_codigo = patron.sub(" ", sin_codigo)
        lineas.append(sin_codigo)
    return "\n".join(lineas)


def decimales_con_punto(markdown: str) -> list[str]:
    return _DECIMAL_CON_PUNTO.findall(texto_visible(markdown))


def _paginas() -> list[Path]:
    return sorted(_DOCS.rglob("*.md"))


def test_el_barrido_no_es_vacuo() -> None:
    paginas = _paginas()
    assert len(paginas) >= 10, len(paginas)
    nombres = {p.relative_to(_DOCS).as_posix() for p in paginas}
    assert {"tutorial.md", "guias/binning-seleccion.md", "guias/modelo-calibracion.md"} <= nombres


@pytest.mark.parametrize("pagina", _paginas(), ids=lambda p: p.relative_to(_DOCS).as_posix())
def test_ninguna_pagina_escribe_un_decimal_con_punto(pagina: Path) -> None:
    hallados = decimales_con_punto(pagina.read_text(encoding="utf-8"))
    assert hallados == [], f"{pagina.relative_to(_DOCS).as_posix()}: {hallados}"


@pytest.mark.parametrize(
    ("markdown", "esperado"),
    [
        ("El AUC fue 0.712 en desarrollo.", ["0.712"]),
        ("| `ingreso` | 0.305 | desc |", ["0.305"]),
        ("El AUC fue 0,712 en desarrollo.", []),
        ("El parámetro `min_iv = 0.02` filtra.", []),
        ("```python\nx = 0.5\n```", []),
        ("Desde la versión 1.0 y hasta una versión 2.0.", []),
        ("OptBinning 0.20.0 y Apache-2.0.", []),
        ("Python ≥ 3.11 (probado en 3.11, 3.12 y 3.13).", []),
        ("Una cartera de 6.000 filas; n = 3.961, 924 malos; 1.000.", []),
        ("- **Python ≥ 3.11** (probado en 3.11, 3.12 y 3.13).", []),
        ("El tramo «≥ 50.450 y < 102.230,5».", []),
        ("PD de 0,2333 y otra de 0.2333.", ["0.2333"]),
        ("La tasa bajó de 0.4286 → 0.0832.", ["0.4286", "0.0832"]),
    ],
)
def test_el_extractor_ve_los_decimales_y_no_lo_demas(markdown: str, esperado: list[str]) -> None:
    """El extractor probado aparte (revisión adversarial, pasada 1): sin él, el gate nacería rojo
    por literales que la enmienda ordena conservar, o verde por no mirar nada."""
    assert decimales_con_punto(markdown) == esperado
