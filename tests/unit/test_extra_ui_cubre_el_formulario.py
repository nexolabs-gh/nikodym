"""El extra `[ui]` debe traer lo que el formulario de la interfaz puede ejecutar.

Un extra llamado `ui` que instala la interfaz pero no el motor que esa interfaz dispara es una
promesa falsa por su propio nombre, y rompe el criterio de cierre de B2: el tercero sin checkout
escribe el comando obvio —`pip install nikodym[ui]`— y espera que funcione.

Medido el 2026-07-28 en venv limpio desde PyPI (`1.8.0`), antes de este gate: el extra traía sólo
el servidor + `[excel]` + `[docx]`, la interfaz arrancaba y los **tres** presets fallaban — F1 y F3
en `binning` («WoEBinner requiere OptBinning»), F4 en `survival` («requiere statsmodels»).

Este gate no comprueba la lista que alguien escribió: la **deriva del formulario**. Cada sección que
`CONFIG_SECTIONS` ofrece necesita un extra para correr, y si esa dependencia no está en `[ui]`, la
interfaz ofrece un formulario que no puede ejecutar. Ampliar el formulario (p. ej. a `stress` o
`forward`) obliga a pasar por aquí.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_PYPROJECT = _RAIZ / "pyproject.toml"
_SCHEMA_TS = _RAIZ / "web" / "src" / "lib" / "schema.ts"

#: Extra que exige el motor de cada sección, medido con los mensajes `instale nikodym[<extra>]` que
#: emite `src/nikodym/<seccion>/`. Se escribe A MANO, no se deriva del código: un recorrido
#: automático que se rompiera daría cero incumplimientos y verde permanente.
#:
#: `provisioning*` comparte el motor de `provisioning/`, que sólo declara `scoring`.
EXTRA_POR_SECCION = {
    "data": None,  # el núcleo lee CSV/Parquet; `excel` (xlsx) ya viaja en `[ui]`
    "binning": "scoring",
    "selection": "scoring",
    "model": "scoring",
    "scorecard": "scoring",
    "calibration": "scoring",
    "performance": "scoring",
    "stability": "scoring",
    "survival": "survival",  # además de `scoring`: `kaplan_meier`/`cox_aft` exigen lifelines
    "provisioning_cmf": "scoring",
    "provisioning_internal": "scoring",
    "provisioning_ifrs9": "scoring",
    "provisioning": "scoring",
}


def _sections_del_formulario() -> set[str]:
    """Claves de `CONFIG_SECTIONS` (`web/src/lib/schema.ts`), leídas del propio catálogo."""
    texto = _SCHEMA_TS.read_text(encoding="utf-8")
    _, _, resto = texto.partition("export const CONFIG_SECTIONS")
    bloque, _, _ = resto.partition("\n]")
    return set(re.findall(r'key:\s*"([a-z_0-9]+)"', bloque))


def _extras_de_ui() -> set[str]:
    """Extras de Nikodym que `[ui]` compone (`nikodym[x]` → `x`), resueltos en un nivel."""
    datos = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    opcionales = datos["project"]["optional-dependencies"]

    vistos: set[str] = set()
    pendientes = ["ui"]
    while pendientes:
        extra = pendientes.pop()
        if extra in vistos:
            continue
        vistos.add(extra)
        for req in opcionales.get(extra, []):
            anidado = re.fullmatch(r"nikodym\[([a-z0-9,_-]+)\]", req.strip())
            if anidado:
                pendientes.extend(anidado.group(1).split(","))
    return vistos


def test_el_formulario_no_ofrece_secciones_que_el_extra_ui_no_puede_ejecutar() -> None:
    """Cada sección del formulario tiene, en `[ui]`, el extra que su motor exige."""
    ofrecidas = _sections_del_formulario()
    assert ofrecidas, (
        f"No se pudo leer `CONFIG_SECTIONS` de {_SCHEMA_TS.name}: sin eso el gate quedaría verde "
        "sin comprobar nada."
    )

    instalados = _extras_de_ui()
    faltan = sorted(
        {
            f"{seccion} → nikodym[{EXTRA_POR_SECCION[seccion]}]"
            for seccion in ofrecidas
            if EXTRA_POR_SECCION.get(seccion) is not None
            and EXTRA_POR_SECCION[seccion] not in instalados
        }
    )

    assert not faltan, (
        f"El formulario ofrece secciones cuyo motor `nikodym[ui]` no instala: {faltan}. "
        "Quien haga `pip install nikodym[ui]` verá el formulario y la corrida fallará pidiendo el "
        "extra. Agrégalo al extra `ui` en pyproject.toml, o retira la sección del formulario."
    )


def test_toda_seccion_del_formulario_declara_que_extra_necesita() -> None:
    """Una sección nueva sin entrada en :data:`EXTRA_POR_SECCION` no se comprobaría.

    Sin este test, agregar una sección al formulario y olvidar clasificarla dejaría el gate anterior
    verde: `EXTRA_POR_SECCION.get(...)` devolvería `None` y la saltaría en silencio. Es el mismo
    modo de fallo que persigue el vocabulario `column_role`.
    """
    sin_declarar = sorted(_sections_del_formulario() - set(EXTRA_POR_SECCION))

    assert not sin_declarar, (
        f"Secciones del formulario sin declarar su extra: {sin_declarar}. Agrégalas a "
        "`EXTRA_POR_SECCION` con el extra que su motor exige, o `None` si corre con el núcleo."
    )


def test_ui_no_arrastra_copyleft_ni_lo_que_el_formulario_no_ofrece() -> None:
    """`[ui]` crece por necesidad del formulario, no por comodidad.

    Dos límites que no son negociables por conveniencia:

    - **`pdf` nunca entra**: WeasyPrint arrastra Pyphen (tri-licencia con GPL) y por eso tampoco
      está en `all`; el gate de licencias del CI rechaza el cierre redistribuible con copyleft.
    - **Los extras de secciones que el formulario NO ofrece** no entran: si algún día `ml`, `tuning`
      o `explain` aparecen aquí sin estar en `CONFIG_SECTIONS`, es peso muerto para todos.
    """
    instalados = _extras_de_ui()
    ofrecidas = _sections_del_formulario()

    assert "pdf" not in instalados, (
        "`[ui]` no puede arrastrar `[pdf]`: Pyphen es copyleft y rompería el gate de licencias."
    )

    innecesarios = sorted(
        extra
        for extra in ("ml", "tuning", "explain", "markov", "forecasting")
        if extra in instalados and extra not in ofrecidas
    )
    assert not innecesarios, (
        f"`[ui]` instala extras cuyas secciones el formulario no ofrece: {innecesarios}. "
        "O se agregan al formulario, o salen del extra: hoy son peso muerto."
    )
