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
_EXENTOS = {"changelog.md"}


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
