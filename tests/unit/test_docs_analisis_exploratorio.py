"""Gates de la guía pública del análisis exploratorio (capa 3 del scorecard completo, D-SC-1…5).

Lo mismo que exigen las demás guías con código: que el ejemplo publicado **corra** —el sitio no
puede documentar una API que no existe— y que lo que la guía afirma del motor sea lo que el motor
hace: aquí, que sobre cohortes la señal temporal se declara no evaluable con su causa (D-SC-2), y
que las palabras que la guía publica sean las de la fuente única (D-SC-5).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nikodym.eda.default_rate import AXIS_LABELS
from nikodym.eda.quality import QUALITY_FLAG_LABELS
from nikodym.eda.stability import NOT_EVALUABLE_REASON_LABELS, STABILITY_INDICATOR_LABELS

_RAIZ = Path(__file__).resolve().parents[2]
_GUIA = _RAIZ / "docs_site" / "guias" / "analisis-exploratorio.md"
_BLOQUE = "eda-example"


def _codigo_publicado() -> str:
    texto = _GUIA.read_text(encoding="utf-8")
    inicio = f"<!-- {_BLOQUE}:start -->\n```python\n"
    fin = "\n```\n" + f"<!-- {_BLOQUE}:end -->"
    assert texto.count(inicio) == 1 and texto.count(fin) == 1, (
        f"el bloque ejecutable {_BLOQUE!r} de la guía perdió sus delimitadores"
    )
    codigo = texto.split(inicio, maxsplit=1)[1].split(fin, maxsplit=1)[0]
    # Ancla anti-vacuidad: unos delimitadores que envuelvan la nada se leen igual que un ejemplo.
    assert "DefaultRateAnalyzer(" in codigo and "TemporalStabilityAnalyzer(" in codigo
    return codigo


def test_el_ejemplo_publicado_es_ejecutable_y_declara_la_causa_sobre_cohortes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """El ejemplo corre tal cual y termina donde la guía dice: `eje_cohorte`, sin excepción.

    🔴 Es el control positivo de D-SC-2 desde la superficie pública: hasta la capa 3 este mismo
    código levantaba ``EdaError`` («solo aplica al eje temporal»).
    """
    exec(compile(_codigo_publicado(), str(_GUIA), "exec"), {"__name__": "__main__"})
    salida = capsys.readouterr().out
    assert "eje_cohorte" in salida
    assert "2024Q1" in salida and "2024Q3" in salida


def test_la_guia_publica_las_palabras_de_la_fuente_unica_y_no_los_identificadores() -> None:
    """Las causas, las marcas, los ejes y los indicadores se leen en la guía con SUS palabras."""
    texto = _GUIA.read_text(encoding="utf-8")
    for palabra in NOT_EVALUABLE_REASON_LABELS.values():
        assert palabra[0].upper() + palabra[1:] in texto or palabra in texto, palabra
    for palabra in QUALITY_FLAG_LABELS.values():
        assert palabra in texto, palabra
    for palabra in STABILITY_INDICATOR_LABELS.values():
        assert palabra in texto, palabra
    assert AXIS_LABELS["cohort"] in texto and "fecha de observación" in texto
    # Los identificadores viven en la referencia de la API y en el ejemplo por código, no en la
    # prosa: fuera del bloque ejecutable, ninguno aparece.
    prosa = re.sub(r"<!-- eda-example:start -->.*?<!-- eda-example:end -->", "", texto, flags=re.S)
    for slug in (
        "pocos_periodos_evaluables",
        "tasa_media_cero",
        "near_constant",
        "high_cardinality",
    ):
        assert slug not in prosa, slug


def test_la_guia_esta_en_la_navegacion_y_enlazada_desde_empezar() -> None:
    nav = (_RAIZ / "mkdocs.yml").read_text(encoding="utf-8")
    assert "guias/analisis-exploratorio.md" in nav
    empezar = (_RAIZ / "docs_site" / "getting-started.md").read_text(encoding="utf-8")
    assert "guias/analisis-exploratorio.md" in empezar
