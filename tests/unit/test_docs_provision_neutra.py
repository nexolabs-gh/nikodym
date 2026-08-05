"""Gates de la guía pública de provisiones sin normativa local (D-JUR-8).

Dos cosas distintas, y las dos hacen falta: que el ejemplo publicado **corra** —el sitio no puede
documentar una API que no existe— y que la demostración siga siendo **neutra**, que es su único
contenido: una guía que enseñe a provisionar sin norma local y cuyo ejemplo cargue el motor chileno
no demuestra nada.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_GUIA = _RAIZ / "docs_site/guias/provision-sin-norma-local.md"

#: Bloques ejecutables de la guía, **en orden de lectura**. Son varios a propósito: el segundo
#: continúa al primero —usa el ``config`` que el primero dejó en pantalla— y la auditoría previa a
#: 1.11.0 encontró ahí el defecto exacto que un solo bloque delimitado no podía ver: el snippet de
#: la moneda trataba como modelo Pydantic un ``config`` que la guía había dejado como ``dict``.
_BLOQUES = ("provision-neutra-example", "provision-neutra-moneda")

#: Términos que delatan una jurisdicción. Espejo acotado del detector de
#: ``test_portada_sin_jurisdiccion``; aquí basta con los que el motor CMF usaría.
_JURISDICCION = re.compile(
    # El guion largo va como escape unicode y no literal: ruff marca RUF001/RUF003 sobre
    # caracteres tipograficos ambiguos, y lo haria justo en el gate que existe para detectarlos.
    "\\b(?:CMF|SBIF|SBS|Chile|chilen\\w*|cmf_\\w+|Compendio|Circular|Cap\\.?\\s*B[-\\u2013]\\d)",
    re.IGNORECASE,
)


def _codigo_publicado() -> str:
    """Concatena los bloques ejecutables en orden de lectura, tal como los teclearía un usuario."""
    texto = _GUIA.read_text(encoding="utf-8")
    partes: list[str] = []
    for nombre in _BLOQUES:
        inicio = f"<!-- {nombre}:start -->\n```python\n"
        fin = f"\n```\n<!-- {nombre}:end -->"
        assert texto.count(inicio) == 1 and texto.count(fin) == 1, (
            f"el bloque ejecutable {nombre!r} de la guía perdió sus delimitadores"
        )
        partes.append(texto.split(inicio, maxsplit=1)[1].split(fin, maxsplit=1)[0])
    codigo = "\n".join(partes)
    # Ancla anti-vacuidad: unos delimitadores que envuelvan la nada se leen igual que un ejemplo
    # correcto, y este gate es lo único que ata la guía al motor.
    assert "nikodym.run(" in codigo and '"currency"' in codigo, (
        "el código extraído perdió la corrida o la declaración de moneda: el gate quedaría vacuo"
    )
    return codigo


def test_el_ejemplo_publicado_es_ejecutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extrae y ejecuta **todos** los bloques que lee un usuario, en un solo espacio de nombres.

    Que sean varios bloques no los hace independientes: la guía cuenta un relato continuo y el
    segundo trabaja sobre el ``config`` que dejó el primero. Ejecutarlos juntos es lo que hace
    caer un snippet que no case con la forma real de ese ``config``.

    Se ejecuta con el cwd en un temporal: el ejemplo escribe rutas **relativas** a propósito —es lo
    que un usuario teclea— y un gate que las materializara dentro del repo dejaría basura sin
    versionar en cada corrida de la suite, que es la clase de fricción por la que un gate se acaba
    desactivando.
    """
    pytest.importorskip("optbinning")
    codigo = _codigo_publicado()
    monkeypatch.chdir(tmp_path)
    exec(compile(codigo, str(_GUIA), "exec"), {"__name__": "__main__"})


def test_el_preset_de_la_guia_no_carga_ninguna_seccion_de_norma_local() -> None:
    """🔴 El contenido de la demostración es lo que NO activa, tanto como lo que activa.

    Si el preset arrastrase `provisioning_cmf` —como hace el F3, y como haría cualquiera que lo
    copiase sin pensar— la guía estaría enseñando a provisionar «sin norma local» con el motor de
    una norma local cargado. El orquestador `provisioning` tampoco puede estar: exige **dos**
    fuentes distintas, así que su sola presencia obliga a un segundo motor.
    """
    from nikodym.ui.presets import F5_INTERNA_PRESET_ID, get_preset

    config = get_preset(F5_INTERNA_PRESET_ID)["config"]

    assert config["provisioning_internal"] is not None, "la demostración perdió su único motor"
    for seccion in ("provisioning_cmf", "provisioning_ifrs9", "provisioning"):
        assert config[seccion] is None, (
            f"el preset de la guía neutra activa {seccion!r}: la demostración deja de demostrar"
        )


def test_ni_el_preset_ni_su_dataset_nombran_una_jurisdiccion() -> None:
    """El estado de fábrica es una afirmación: ni sus valores ni sus columnas pueden nombrar país.

    Cubre el caso exacto de D-JUR-8: el default `portfolio_col="cmf_portfolio"` era neutro en su
    título y su ayuda, y chileno en su **valor** — que es lo que se ejecuta.
    """
    from nikodym.ui.datasets import list_datasets
    from nikodym.ui.presets import F5_INTERNA_DATASET_ID, F5_INTERNA_PRESET_ID, get_preset

    preset = get_preset(F5_INTERNA_PRESET_ID)
    interna = preset["config"]["provisioning_internal"]
    valores = [str(v) for v in interna.values() if isinstance(v, str)]
    ofensores = sorted({m.group(0) for v in valores for m in _JURISDICCION.finditer(v)})
    assert not ofensores, f"el preset neutro trae valores con jurisdicción: {ofensores}"

    descriptor = next(d for d in list_datasets() if d["id"] == F5_INTERNA_DATASET_ID)
    columnas = [c["name"] for c in descriptor["columns"]]
    sucias = sorted({c for c in columnas if _JURISDICCION.search(c)})
    assert not sucias, f"el dataset neutro trae columnas con jurisdicción: {sucias}"
    # Ancla anti-vacuidad: un barrido sobre cero columnas se lee igual que uno limpio.
    assert len(columnas) >= 10, f"el barrido sólo vio {len(columnas)} columnas"
    for exigida in ("as_of_date", "portfolio", "exposure_amount", "lgd"):
        assert exigida in columnas, f"el dataset perdió {exigida!r}, que el motor interno exige"


def test_todo_preset_del_catalogo_esta_curado_en_el_front() -> None:
    """🔴 El fallback de la tarjeta rotula «estable» por defecto, y eso es una sobrepromesa.

    ``presetDisplay`` (``web/src/lib/presentation.ts``) decide la píldora de madurez así: si el
    preset no está en ``CURATED``, mira si su ``description`` contiene la palabra «experimental» y,
    si no, lo rotula **estable**. Un preset nuevo de provisiones —motor declarado experimental en
    todo el paquete— nace por tanto prometiendo un contrato congelado bajo SemVer 1.x.

    No se arregla invirtiendo el default, que sólo cambiaría el sentido de la mentira: se arregla
    exigiendo que **todo** preset publicado esté curado, de modo que su madurez sea una decisión
    escrita y no el residuo de si alguien usó una palabra en la descripción.

    Se vio abriendo la pantalla; ninguna suite compara esa píldora con la madurez del dominio.
    """
    from nikodym.ui.presets import list_presets

    fuente = (_RAIZ / "web/src/lib/presentation.ts").read_text(encoding="utf-8")
    # Ancla anti-vacuidad: si el bloque se renombra, este gate no puede pasar mirando a la nada.
    assert "const CURATED" in fuente and 'garantia: "experimental"' in fuente

    ids = [p["id"] for p in list_presets()]
    assert len(ids) >= 3, f"el catálogo sólo publica {len(ids)} presets"
    sin_curar = [pid for pid in ids if f'"{pid}"' not in fuente]
    assert not sin_curar, (
        f"presets publicados sin entrada curada en presentation.ts: {sin_curar}. Caerían al "
        "fallback, que los rotula «estable» salvo que su descripción diga «experimental»."
    )


def test_el_detector_de_la_guia_no_es_vacuo() -> None:
    """Control positivo: si el detector deja de detectar, los dos tests de arriba pasan siempre."""
    assert _JURISDICCION.search("cmf_portfolio")
    assert _JURISDICCION.search("Cap. B-1")
    assert _JURISDICCION.search("Compendio de Normas Contables")
    assert not _JURISDICCION.search("portfolio")
    assert not _JURISDICCION.search("exposure_amount")
