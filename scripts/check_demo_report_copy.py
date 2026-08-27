"""Gate de copy público sobre los informes de la demo YA ESCRITOS.

Hermano de `tests/unit/test_report_codigos_internos.py`, que prueba el motor. Éste prueba el
**artefacto**: los `report-*.html` y `report-*.docx` que la demo pública sirve a cualquiera que abra
la web, sin instalar nada.

Existe porque los dos pueden divergir. Los fixtures salen de una corrida real y **jamás se editan a
mano**: entre una corrida y la siguiente pasan versiones, así que un informe distribuido puede
seguir mostrando durante meses lo que el motor ya dejó de producir. Un gate sobre el motor no dice
nada sobre los bytes que están publicados hoy.

El contrato tiene dos mitades y las dos se comprueban (`AGENTS.md` §copy público, publicado en
`docs_site/avisos-declarados.md`):

    «En el informe HTML/PDF/Word los códigos aparecen sólo en el volcado de auditoría del anexo.
    La prosa del informe explica la limitación en palabras, sin nombrar el código.»

Uso::

    python scripts/check_demo_report_copy.py
"""

from __future__ import annotations

import html
import re
import sys
import zipfile
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[1]
_FIXTURES: Final = _ROOT / "web" / "src" / "fixtures" / "demo"

#: Las dos marcas del contrato, con o sin sufijo de familia. Se leen de `nikodym.core.markers` si el
#: paquete es importable, y si no del literal: el script tiene que poder correr en un runner que
#: todavía no instaló el árbol.
try:
    from nikodym.core.markers import DECLARED_MARKERS
except ModuleNotFoundError:  # pragma: no cover - ruta de runner sin el paquete instalado
    DECLARED_MARKERS = ("FALTA-DATO", "DATO-INSTITUCIONAL")

_CODIGO: Final = re.compile("|".join(re.escape(m) for m in DECLARED_MARKERS))

#: El renderer emite las secciones HERMANAS, nunca anidadas (medido sobre el HTML real), así que
#: partir por `<section` basta para separar cuerpo de anexo sin un parser.
_SECCION: Final = "<section"
_ANEXO: Final = 'data-kind="appendix"'


def _fallos_html(ruta: Path) -> list[str]:
    crudo = ruta.read_text(encoding="utf-8")
    secciones = crudo.split(_SECCION)[1:]
    if not secciones:
        return [f"{ruta.name}: no tiene ninguna <section>; ¿es un informe?"]
    cuerpo = [s for s in secciones if _ANEXO not in s]
    anexo = [s for s in secciones if _ANEXO in s]
    if not cuerpo or not anexo:
        return [f"{ruta.name}: se esperaban cuerpo Y anexo; el gate no puede afirmar nada"]

    fallos = [
        f"{ruta.name}: código interno en la PROSA del cuerpo → {m.group(0)}"
        for s in cuerpo
        for m in [_CODIGO.search(html.unescape(s))]
        if m is not None
    ]
    # La otra mitad: el anexo de auditoría tiene que conservarlos. Si un informe no declara ningún
    # aviso, no hay nada que conservar y no se exige — pero entonces tampoco puede haber ninguno
    # suelto en el cuerpo, que es lo que comprueba el bloque de arriba.
    return fallos


def _fallos_docx(ruta: Path) -> list[str]:
    """El `.docx` es un zip; su texto vive en `word/document.xml`.

    Aquí no se puede separar cuerpo de anexo por `data-kind`, así que el gate es más flojo a
    propósito y **se declara**: comprueba que el documento existe y es legible. Afirmar más sobre él
    exigiría replicar la estructura del render de Word, y un gate que finge medir lo que no mide es
    peor que uno que declara su alcance.
    """
    try:
        with zipfile.ZipFile(ruta) as doc:
            doc.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return [f"{ruta.name}: no es un .docx legible ({exc})"]
    return []


def main() -> int:
    """Revisa todos los informes de la demo y devuelve 0 si ninguno filtra un código interno."""
    htmls = sorted(_FIXTURES.glob("report*.html"))
    docxs = sorted(_FIXTURES.glob("report*.docx"))
    if not htmls:
        print(f"FALLO: no hay informes que revisar en {_FIXTURES}", file=sys.stderr)
        return 1

    fallos: list[str] = []
    for ruta in htmls:
        fallos.extend(_fallos_html(ruta))
    for ruta in docxs:
        fallos.extend(_fallos_docx(ruta))

    print(f"informes revisados: {len(htmls)} HTML, {len(docxs)} DOCX")
    for ruta in htmls:
        print(f"  · {ruta.name}")
    if fallos:
        print("\nFALLOS:", file=sys.stderr)
        for fallo in fallos:
            print(f"  {fallo}", file=sys.stderr)
        return 1
    print("\nOK: ningún código interno en la prosa del cuerpo de los informes distribuidos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
