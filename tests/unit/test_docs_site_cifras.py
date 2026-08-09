"""Gate: las cifras que `docs_site/` atribuye a la corrida de ejemplo son las de esa corrida.

🔴 **Por qué existe.** El tutorial, el glosario y la guía de calibración publicaron durante doce
días que el preset F1 anclaba la PD a ``target_pd = 0.20`` con un offset de ``-0.218``, dejando la
PD media en ``0.200`` exacto, y que la fuente del ancla era ``business_input``. Todo eso fue
cierto: es la salida literal de la corrida F1 del 2026-07-10. Dejó de serlo el 2026-07-21, cuando
el preset pasó a leer el ancla de los propios datos (``development_observed``) — una **corrección**
deliberada, documentada en el CHANGELOG— y nadie propagó el cambio a la documentación, porque
**ningún test lo obligaba**: los dos únicos que leen ``docs_site/`` buscan marcadores internos y
ejecutan un bloque de código, y ninguno abre un fixture.

En un producto de riesgo eso no es una errata de documentación: es la página que explica cómo se
ancla una PD describiendo una decisión del modelador que la corrida reproducible no toma.

**Cómo se ata, y qué NO cubre.** Cada ancla declara la cifra tal como se publica, el archivo donde
aparece y de dónde sale en el fixture. El gate es bidireccional en lo que ancla: si el fixture se
mueve, la cifra deja de cuadrar; si alguien edita el texto, la cifra deja de encontrarse. ⚠️ Lo que
**no** puede hacer es descubrir cifras nuevas: una que se publique sin anclarla aquí no rompe nada.
Se dice en vez de callarlo — una tabla corta sin esa advertencia se lee como cobertura total.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_DOCS = _RAIZ / "docs_site"
_FIXTURES = _RAIZ / "web" / "src" / "fixtures" / "demo"


def _fixture(nombre: str) -> dict[str, Any]:
    datos: dict[str, Any] = json.loads((_FIXTURES / nombre).read_text(encoding="utf-8"))
    return datos


def _en(raiz: Any, ruta: str) -> Any:
    """Baja por una ruta con puntos; los tramos numéricos indexan listas."""
    nodo = raiz
    for tramo in ruta.split("."):
        nodo = nodo[int(tramo)] if tramo.isdigit() else nodo[tramo]
    return nodo


def _reliability(particion: str, metrica: str) -> float:
    filas = _en(_fixture("results-f1.json"), "calibration.reliability.by_partition")
    fila = next(f for f in filas if f["partition"] == particion)
    valor: float = fila[metrica]
    return valor


def _discriminante(particion: str, metrica: str) -> float:
    filas = _en(_fixture("results-f1.json"), "performance.discriminant")
    fila = next(f for f in filas if f["partition"] == particion)
    valor: float = fila[metrica]
    return valor


#: ``(archivo, texto publicado, valor real, decimales)``. El texto se busca LITERAL en el `.md`;
#: el valor se redondea a `decimales` y tiene que dar ese mismo texto. Escritas a mano una a una:
#: derivar la lista del propio documento mediría que el documento es consistente consigo mismo.
_ANCLAS: list[tuple[str, str, float, int]] = [
    # Calibración — el bloque que estuvo doce días desfasado.
    ("tutorial.md", "0.2333", _en(_fixture("results-f1.json"), "calibration.target_pd"), 4),
    (
        "tutorial.md",
        "0.160",
        _reliability("desarrollo", "brier"),
        3,
    ),
    ("tutorial.md", "0.164", _reliability("holdout", "brier"), 3),
    ("tutorial.md", "0.171", _reliability("oot", "brier"), 3),
    ("tutorial.md", "0.011", _reliability("desarrollo", "ece"), 3),
    ("tutorial.md", "0.028", _reliability("holdout", "ece"), 3),
    ("tutorial.md", "0.043", _reliability("oot", "ece"), 3),
    ("glosario.md", "0,233", _en(_fixture("results-f1.json"), "calibration.target_pd"), 3),
    (
        "guias/modelo-calibracion.md",
        "0.2333",
        _en(_fixture("results-f1.json"), "calibration.raw_mean_pd_dev"),
        4,
    ),
    # Discriminación — cuadraban ya, y se anclan para que sigan cuadrando.
    ("tutorial.md", "0.712", _discriminante("desarrollo", "auc"), 3),
    ("tutorial.md", "0.695", _discriminante("holdout", "auc"), 3),
    ("tutorial.md", "0.656", _discriminante("oot", "auc"), 3),
]

#: Afirmaciones cualitativas atadas a un campo del fixture: la frase sólo es cierta si el campo vale
#: eso. Es lo que faltaba de verdad — el número desfasado era el síntoma, pero lo que la
#: documentación describía mal era **de dónde sale el ancla**, que es un campo, no una cifra.
_ANCLAS_DE_TEXTO: list[tuple[str, str, str, str]] = [
    ("tutorial.md", "development_observed", "calibration.anchor_source", "development_observed"),
    ("glosario.md", "development_observed", "calibration.anchor_source", "development_observed"),
    (
        "guias/modelo-calibracion.md",
        "`anchor_source = development_observed`",
        "calibration.anchor_source",
        "development_observed",
    ),
    (
        "guias/modelo-calibracion.md",
        "`n_fit = 3961`",
        "calibration.n_fit",
        "3961",
    ),
]

#: Cifras y literales que la documentación **no puede volver a publicar** sobre la corrida de
#: ejemplo: son los de la corrida del 2026-07-10, que el preset ya no reproduce. Un control por
#: ausencia, que es el que caza la reaparición — un `git revert` descuidado, o copiar un párrafo
#: viejo desde `privado/archivo/`.
_PROSCRITAS: list[tuple[str, str]] = [
    ("tutorial.md", "-0.218"),
    ("tutorial.md", "target_pd = 0.20"),
    ("glosario.md", "target_pd = 0,20"),
    # El documento escribe el menos con el signo MATEMÁTICO (U+2212), no un guion: la búsqueda
    # tiene que usar el mismo carácter o el control por ausencia no encontraría nada y daría verde.
    ("guias/modelo-calibracion.md", "\u22120.2184"),
    ("guias/modelo-calibracion.md", "`target_pd = 0.20`"),
]


def _texto(archivo: str) -> str:
    return (_DOCS / archivo).read_text(encoding="utf-8")


def test_el_barrido_no_es_vacuo() -> None:
    """Una tabla vacía, o apuntando a archivos que no existen, daría verde sin comprobar nada."""
    assert len(_ANCLAS) >= 12, len(_ANCLAS)
    assert len(_ANCLAS_DE_TEXTO) >= 4
    for archivo in {a[0] for a in _ANCLAS} | {a[0] for a in _ANCLAS_DE_TEXTO}:
        assert (_DOCS / archivo).is_file(), archivo
    assert _fixture("results-f1.json")["calibration"], "el fixture no trae calibración"


def test_tutorial_atribuye_todas_sus_cifras_al_fixture_f1_real() -> None:
    tutorial = _texto("tutorial.md")
    fuente = "`web/src/fixtures/demo/results-f1.json`"

    assert tutorial.count(fuente) == 7
    assert "`results.json`" not in tutorial
    assert "`results-f1.json`" not in tutorial


@pytest.mark.parametrize(("archivo", "publicado", "real", "decimales"), _ANCLAS)
def test_toda_cifra_anclada_es_la_del_fixture(
    archivo: str, publicado: str, real: float, decimales: int
) -> None:
    """Las dos direcciones: la cifra está en el documento, y es la que el fixture produce."""
    esperado = f"{real:.{decimales}f}"
    if "," in publicado:
        esperado = esperado.replace(".", ",")
    assert esperado == publicado, (
        f"{archivo}: la corrida de ejemplo da {esperado}, y el ancla dice {publicado}. "
        "Si la corrida cambió, actualiza el documento Y esta tabla."
    )
    assert publicado in _texto(archivo), (
        f"{archivo}: ya no contiene «{publicado}». Si el texto se reescribió, mueve el ancla; "
        "si la cifra desapareció, quítala de la tabla."
    )


@pytest.mark.parametrize(("archivo", "frase", "ruta", "valor"), _ANCLAS_DE_TEXTO)
def test_toda_afirmacion_anclada_la_sostiene_el_fixture(
    archivo: str, frase: str, ruta: str, valor: str
) -> None:
    """Una frase sobre CÓMO corre el ejemplo sólo vale si el campo del fixture dice eso."""
    real = _en(_fixture("results-f1.json"), ruta)
    assert str(real) == valor, (
        f"{ruta} vale {real!r}, no {valor!r}: la frase de {archivo} ya no vale"
    )
    assert frase in _texto(archivo), f"{archivo}: falta «{frase}»"


@pytest.mark.parametrize(("archivo", "proscrita"), _PROSCRITAS)
def test_no_reaparece_una_cifra_de_la_corrida_vieja(archivo: str, proscrita: str) -> None:
    """Control por ausencia: es el que caza el regreso del párrafo viejo."""
    assert proscrita not in _texto(archivo), (
        f"{archivo} vuelve a publicar «{proscrita}», que es de la corrida del 2026-07-10. "
        "El preset dejó de anclar a mano: hoy lee el ancla de los datos."
    )


def test_la_portada_publica_la_version_que_el_paquete_declara() -> None:
    """La versión de la portada se queda stale en cada release, y nada la ataba.

    🔴 Medido en la auditoría previa a `1.11.0`: `docs_site/index.md` afirmaba «Estado: 1.10.0»
    mientras el paquete iba a publicar otra, y el único gate que tocaba esa línea comprobaba la
    frase «release estable», no el número. Es la misma clase que las cifras de calibración que este
    archivo existe para cazar: una afirmación verdadera que dejó de serlo y que ningún test seguía.

    ⚠️ La afirmación se ata a ``__version__`` y no al tag: el tag va después del CI, y para
    entonces la documentación ya está escrita.
    """
    import nikodym

    esperado = f"Estado: {nikodym.__version__} — release estable"
    assert esperado in _texto("index.md"), (
        f"la portada no dice «{esperado}»: el bump de versión no llegó a docs_site/index.md, "
        "así que la página de entrada anuncia una versión que no es la publicada"
    )
