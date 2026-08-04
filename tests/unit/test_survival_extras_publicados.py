"""Lo que se publica sobre qué extra exige cada método de survival tiene que ser cierto.

🔴 **Por qué existe.** El 2026-08-03 se corrigió que el motor exigiera `lifelines` para
`kaplan_meier`, cuyo estimador no lo importa en ninguna ruta (`survival/kaplan_meier.py` usa numpy y
`statistics.NormalDist`). El código quedó bien y **cinco superficies siguieron publicando la frase
vieja** durante un día: `pyproject.toml`, `docs/ROADMAP.md`, dos puntos de
`docs/design/18-survival.md` y un comentario de `test_extra_ui_cubre_el_formulario.py`. Nada las
comparaba con el motor.

Es la clase que este repo ya tiene documentada —*una corrección en una superficie no se propaga*—
y cuesta caro justo aquí: quien lee la documentación instala un extra de más, o peor, cree que no
puede usar un método que sí puede.

**El oráculo es el motor**, no una lista escrita al lado: :data:`_METODOS_SIN_EXTRA` de
``survival/step.py`` es el mismo dato que gobierna la corrida. Si mañana otro método deja de exigir
su extra, este gate empieza a vigilarlo solo.

⚠️ **Las exenciones son FRASES, no archivos.** Eximir `18-survival.md` entero habría dejado sin
vigilancia el archivo donde vivían dos de los cinco residuos. Lo que se exime es cada texto concreto
que habla del defecto **ya corregido**, y si ese texto cambia hay que volver a mirarlo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nikodym.survival.step import _METODOS_SIN_EXTRA

_RAIZ = Path(__file__).resolve().parents[2]

#: Superficies que AFIRMAN algo sobre los extras y que un tercero lee.
#:
#: `src/` queda fuera a propósito: ahí `lifelines` y `kaplan_meier` conviven en el código que
#: implementa la distinción, así que la co-ocurrencia es la implementación y no una afirmación.
_SUPERFICIES: tuple[tuple[str, str], ...] = (
    ("", "pyproject.toml"),
    ("", "README.md"),
    ("docs", "**/*.md"),
    ("docs_site", "**/*.md"),
    ("tests", "**/*.py"),
)

#: Textos que nombran el método y el extra **para contar el defecto ya corregido**.
#:
#: Se comparan por fragmento contenido en la línea, escritos a mano y aparte del código que
#: vigilan: derivarlos del propio barrido haría el gate autorreferencial.
_HISTORICAS: tuple[str, ...] = (
    # El censo y el SDD del abanico registran el defecto tal como se midió, antes de cerrarlo.
    "el gate de `lifelines` es más estricto que el motor",
    "el gate de `lifelines` sobre `kaplan_meier`",
    # El propio arreglo, y este archivo.
    "`kaplan_meier` ya NO exige lifelines",
    "ya no lo es",
    # Las frases corregidas, que nombran los tres a la vez justamente para desmentir la vieja.
    "`kaplan_meier` **no**",
    "`kaplan_meier` NO",
    "KM no exige ningún extra",
    "(KM no)",
    "`kaplan_meier` no exige ninguno",
)


def _lineas_publicadas() -> list[tuple[Path, int, str]]:
    lineas: list[tuple[Path, int, str]] = []
    for carpeta, patron in _SUPERFICIES:
        base = _RAIZ / carpeta if carpeta else _RAIZ
        rutas = sorted(base.glob(patron)) if "*" in patron else [base / patron]
        for ruta in rutas:
            if not ruta.is_file() or ruta.resolve() == Path(__file__).resolve():
                continue
            for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), start=1):
                lineas.append((ruta, n, linea))
    return lineas


def test_el_barrido_encuentra_las_superficies() -> None:
    """Un gate que recorre cero archivos da verde y no prueba nada."""
    lineas = _lineas_publicadas()
    archivos = {ruta for ruta, _, _ in lineas}

    assert len(archivos) >= 100, f"sólo {len(archivos)} archivos barridos"
    for ancla in ("pyproject.toml", "ROADMAP.md", "18-survival.md"):
        assert any(ruta.name == ancla for ruta in archivos), f"falta {ancla} en el barrido"


def test_el_oraculo_sale_del_motor_y_no_esta_vacio() -> None:
    """Si `_METODOS_SIN_EXTRA` quedara vacío, el gate pasaría sin comprobar nada."""
    assert _METODOS_SIN_EXTRA, "el motor no declara ningún método sin extra"
    assert "kaplan_meier" in _METODOS_SIN_EXTRA


@pytest.mark.parametrize("metodo", sorted(_METODOS_SIN_EXTRA))
def test_ninguna_superficie_dice_que_un_metodo_sin_extra_lo_exige(metodo: str) -> None:
    """Dirección única y suficiente: el motor manda, y el texto no puede contradecirlo."""
    ofensores = [
        f"{ruta.relative_to(_RAIZ)}:{n}: {linea.strip()[:120]}"
        for ruta, n, linea in _lineas_publicadas()
        if metodo in linea
        and "lifelines" in linea
        and not any(historica in linea for historica in _HISTORICAS)
    ]

    assert ofensores == [], (
        f"«{metodo}» NO exige lifelines (lo declara `_METODOS_SIN_EXTRA` en survival/step.py) y "
        "estas superficies dicen lo contrario:\n  " + "\n  ".join(ofensores)
    )


def test_los_metodos_que_si_exigen_el_extra_siguen_documentados() -> None:
    """Control simétrico: el gate no puede empujar a borrar la frase verdadera.

    Sin esto, la forma más fácil de poner el gate en verde sería quitar de la documentación toda
    mención a `lifelines`, y entonces nadie sabría que Cox/AFT lo necesitan.
    """
    survival_md = (_RAIZ / "docs" / "design" / "18-survival.md").read_text(encoding="utf-8")

    assert re.search(r"[Cc]ox.{0,12}AFT.{0,40}lifelines", survival_md), (
        "18-survival.md dejó de decir que Cox/AFT exigen lifelines, que sí es cierto"
    )
