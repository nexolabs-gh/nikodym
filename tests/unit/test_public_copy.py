"""Gate de copy público (lado documentación): un código interno no llega al lector.

Gemelo Python de ``web/src/lib/public-copy.test.ts``, que cubre el front. Aquí se cubre el sitio
público de mkdocs, que es la otra superficie que un visitante lee sin haber instalado nada.

La regla no es callar la limitación —el motor la publica en cada fila que emite, y esconderla sería
mentir por omisión sobre un producto regulatorio—. Es explicarla en el idioma del lector:
``FALTA-DATO-IFRS-4`` es un contrato entre el motor y la UI, y a quien lee la portada de la
documentación no le dice nada.

En markdown no hace falta la heurística que el gate del front necesita para separar copy de
identificador: aquí **todo** es prosa dirigida a alguien. De ahí que baste con buscar la marca.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nikodym.core.markers import DECLARED_MARKERS

#: Raíz del sitio público de mkdocs (`mkdocs.yml` → `docs_dir`).
_DOCS_SITE = Path(__file__).resolve().parents[2] / "docs_site"

#: Cualquiera de las dos marcas, con o sin sufijo de familia. El token pelado cuenta: una salvedad
#: que decía «declaradas como FALTA-DATO», sin sufijo, era igual de opaca para el lector.
_CODIGO_INTERNO = re.compile("|".join(re.escape(m) for m in DECLARED_MARKERS))

#: `docs_site/changelog.md` es un snippet (`--8<-- "CHANGELOG.md"`) que publica el CHANGELOG técnico
#: entero. Ahí los códigos son legítimos y quitarlos sería el error simétrico: un changelog existe
#: para que quien mantiene rastree qué cambió en el motor, no para vender.
#:
#: `avisos-declarados.md` es la página de referencia del *output* del motor: documenta qué significa
#: cada código que el usuario ve en `warning_codes` de su DataFrame. Es la misma excepción que el
#: volcado de auditoría del anexo del informe —ahí el código **es** el dato— y la razón de que el
#: README pueda quedar limpio: la documentación tiene dónde vivir (P1.1, 2026-07-25).
_EXENTOS = {"changelog.md", "avisos-declarados.md"}

#: El `README.md` es la portada de GitHub y de PyPI: la superficie de copy público con más lectores
#: del proyecto, y hasta el 2026-07-25 quedaba fuera del gate porque no había dónde documentar los
#: códigos. Con `avisos-declarados.md` publicada, ya no hay excusa y entra al barrido.
_README = Path(__file__).resolve().parents[2] / "README.md"


#: Espejo de las marcas en el front. El `tsconfig` de la app expone sólo `vite/client`, así que su
#: propio gate no puede leer este módulo Python; la correspondencia se verifica desde aquí, que es
#: el único lado con acceso a los dos.
_MARKERS_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "markers.ts"


def _paginas() -> list[Path]:
    return sorted(p for p in _DOCS_SITE.rglob("*.md") if p.name not in _EXENTOS)


def test_el_front_espeja_exactamente_las_marcas_del_contrato() -> None:
    """Una marca nueva aquí y no allá abre un hueco mudo: el front deja de reconocer sus avisos."""
    espejadas = re.findall(r'"([A-Z-]+)"', _MARKERS_TS.read_text(encoding="utf-8"))
    assert sorted(espejadas) == sorted(DECLARED_MARKERS)


def test_hay_paginas_que_revisar() -> None:
    """Sin esto, un `docs_dir` renombrado dejaría el gate en verde barriendo cero archivos."""
    assert len(_paginas()) >= 5


@pytest.mark.parametrize("pagina", _paginas(), ids=lambda p: p.name)
def test_la_documentacion_publica_no_nombra_el_codigo_interno(pagina: Path) -> None:
    """La limitación se queda y se explica; el código se va."""
    ofensores = [
        f"{pagina.name}:{n}: {linea.strip()}"
        for n, linea in enumerate(pagina.read_text(encoding="utf-8").splitlines(), start=1)
        if _CODIGO_INTERNO.search(linea)
    ]
    assert ofensores == []


def test_el_readme_no_nombra_el_codigo_interno() -> None:
    """La portada de GitHub y de PyPI es la superficie de copy público con más lectores."""
    ofensores = [
        f"README.md:{n}: {linea.strip()}"
        for n, linea in enumerate(_README.read_text(encoding="utf-8").splitlines(), start=1)
        if _CODIGO_INTERNO.search(linea)
    ]
    assert ofensores == []


#: Página de referencia que sostiene la exención: si el README puede quedar limpio es porque el
#: lector tiene dónde buscar el código que ve en su `warning_codes`.
_REFERENCIA = _DOCS_SITE / "avisos-declarados.md"

#: Los códigos con familia tal como los emite el motor (`FALTA-DATO-IFRS-4`), no la marca desnuda.
_CODIGO_CON_FAMILIA = re.compile(
    "(?:" + "|".join(re.escape(m) for m in DECLARED_MARKERS) + r")-[A-Z]+-\d+"
)

#: Raíz del paquete. Se barren sólo los `.py`: un `rglob` sobre todo `src/` tocaría el bundle
#: minificado de `ui/static/assets/`, que devuelve ruido y ningún código legible.
_PAQUETE = Path(__file__).resolve().parents[2] / "src" / "nikodym"


def _codigos_del_motor() -> set[str]:
    return {
        codigo
        for modulo in _PAQUETE.rglob("*.py")
        for codigo in _CODIGO_CON_FAMILIA.findall(modulo.read_text(encoding="utf-8"))
    }


def test_el_censo_del_motor_no_esta_vacio() -> None:
    """Sin esto, un `_PAQUETE` mal apuntado dejaría el gate verde comparando conjuntos vacíos."""
    assert len(_codigos_del_motor()) >= 20


def test_la_pagina_de_referencia_documenta_cada_codigo_que_emite_el_motor() -> None:
    """Un código nuevo sin fila en la tabla deja al lector sin dónde buscarlo.

    Es la contrapartida de haber sacado los códigos del README: la documentación se movió, no se
    borró, y sólo sigue siendo cierto mientras la página esté completa.
    """
    documentados = set(_CODIGO_CON_FAMILIA.findall(_REFERENCIA.read_text(encoding="utf-8")))
    sin_documentar = sorted(_codigos_del_motor() - documentados)
    assert sin_documentar == [], (
        f"Códigos que el motor nombra y la referencia no documenta: {sin_documentar}. "
        f"Añádelos a docs_site/{_REFERENCIA.name}."
    )


def test_la_pagina_de_referencia_no_inventa_codigos() -> None:
    """El error simétrico: documentar un código que ya no existe manda al lector a buscar humo."""
    documentados = set(_CODIGO_CON_FAMILIA.findall(_REFERENCIA.read_text(encoding="utf-8")))
    inexistentes = sorted(documentados - _codigos_del_motor())
    assert inexistentes == []
