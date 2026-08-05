"""La propuesta de valor no nombra ninguna jurisdicción; la evidencia sí.

Decisión de producto de Cami (2026-08-04), tras cerrar que la normativa local de cada país sale
del alcance de la librería: **una jurisdicción nunca va en la propuesta de valor; va en la
evidencia.** El argumento no es de imagen sino de alcance — nada impide hoy usar Nikodym fuera de
Chile (F1 e IFRS 9 son estándar y el cálculo de ``provisioning/internal`` es neutro), así que lo que
reducía el alcance percibido era el **titular**, no la arquitectura.

Lo que este gate vigila es exactamente eso y nada más: el **titular** de cada superficie pública.

⚠️ Y por eso el corte importa más que la lista de términos. La misma página que no puede nombrar un
país en su primer párrafo **sí debe nombrarlo** treinta líneas más abajo, en la salvedad que dice
qué parámetros no son oficiales: ocultarlo ahí sería la mentira contraria.

🔴 El corte NO puede ser «hasta el primer bloque destacado», que fue el primer criterio y era el
equivocado: ``>`` y ``!!!`` son justamente los marcadores con que Markdown **destaca**, así que
cortar ahí le regalaba al copy el banner más visible de la página — un ``> ## Nikodym es el motor de
la CMF para la banca chilena`` justo bajo el titular pasaba en verde, medido. El titular llega hasta
el primer encabezado de sección o hasta la primera **salvedad** (``!!! warning`` / ``!!! danger``),
que es donde de verdad empieza la evidencia.

No sustituye al criterio humano: un titular puede volverse Chile-only sin escribir «Chile». Lo que
cierra es la regresión mecánica, que es la que ocurre sola al editar copy meses después.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

_RAIZ = Path(__file__).resolve().parents[2]
_README = _RAIZ / "README.md"
_PORTADA_DOCS = _RAIZ / "docs_site" / "index.md"
_PYPROJECT = _RAIZ / "pyproject.toml"
_MKDOCS = _RAIZ / "mkdocs.yml"
_INDEX_HTML = _RAIZ / "web" / "index.html"

# Guiones que un editor de texto puede dejar donde iba un ASCII sin que se note: hyphen-minus,
# hyphen, non-breaking hyphen, figure dash, en dash y em dash. Sin esto, un B seguido de U+2011 y
# un 1 evade el gate y en pantalla se ve idéntico. Van como escapes Unicode, no como literales:
# escritos tal cual, `ruff` los marca RUF001 por ambiguos — que es la misma razón por la que hay
# que vigilarlos.
_G = "[-\u2010\u2011\u2012\u2013\u2014]"

# Reguladores, países y anclas normativas locales. NO entra «IFRS», «Basilea» ni «NIIF»: son
# estándares comunes y su sitio ES la propuesta de valor — precisamente lo que la decisión conserva.
#
# ⚠️ Sin `\b` de cierre global, y no es descuido: con él, `RAN 21-10` NO matcheaba —la frontera caía
# entre el «2» y el «1»— justo con la norma que el repo cita por su nombre. Cada rama delimita por
# su cuenta.
_JURISDICCION = re.compile(
    r"\b(?:CMF|SBIF|SBS"
    r"|Chile|chilen\w*|peruan\w*|bolivian\w*|colombian\w*|ecuatorian\w*"
    r"|Comisi[óo]n para el Mercado Financiero"
    r"|Superintendencia de Banca"
    r"|RAN\s*\d+(?:" + _G + r"\d+)*"
    r"|Circular\s*N?[.°]{0,2}\s*[\d.]+"
    r"|Compendio"
    r"|Cap(?:[íi]tulo)?\.?\s*B" + _G + r"\d+"
    r"|B" + _G + r"[13]\b)",
    re.IGNORECASE,
)

# Una salvedad SÍ debe nombrar la jurisdicción: es la evidencia. Un `!!! note` de estado, no.
_SALVEDAD = ("!!! warning", "!!! danger", "!!! caution", "??? warning")


def _titular(markdown: str) -> str:
    """Prosa de portada: hasta el primer ``## `` o la primera salvedad, lo que llegue antes.

    🔴 A propósito NO corta en ``>`` ni en ``!!! note``: son bloques **destacados**, o sea la parte
    más visible de la portada, y dejarlos fuera convertía el gate en un permiso para escribir ahí
    justo lo que prohíbe tres líneas más arriba.
    """
    lineas: list[str] = []
    for linea in markdown.splitlines():
        pelada = linea.lstrip().lower()
        if pelada.startswith("## ") or pelada.startswith(_SALVEDAD):
            break
        lineas.append(linea)
    return "\n".join(lineas)


def _ofensores(texto: str) -> list[str]:
    return sorted({m.group(0) for m in _JURISDICCION.finditer(texto)})


def test_el_corte_del_titular_no_es_vacuo() -> None:
    """Ancla anti-vacuidad: un titular vacío pasaría todo lo de abajo sin medir nada."""
    for ruta in (_README, _PORTADA_DOCS):
        completo = ruta.read_text(encoding="utf-8")
        titular = _titular(completo)
        assert len(titular) > 200, f"{ruta.name}: el titular quedó en {len(titular)} caracteres"
        assert "riesgo de crédito" in titular, (
            f"{ruta.name}: el corte del titular dejó fuera la descripción del producto, "
            "así que este gate no está mirando la propuesta de valor"
        )
        # Y el corte tiene que estar CORTANDO: si se tragara el archivo entero, dejaría de
        # distinguir titular de evidencia y acusaría a las salvedades, que deben nombrar el país.
        assert len(titular) < len(completo) / 2, f"{ruta.name}: el corte no está cortando"

    # El bloque DESTACADO de la portada tiene que quedar DENTRO. Es donde más se ve y fue el hueco
    # del primer criterio: sin este ancla, el gate volvería a cortar antes de tiempo sin avisar.
    assert "Estado: 1.x (estable)" in _titular(_README.read_text(encoding="utf-8"))
    assert "release estable" in _titular(_PORTADA_DOCS.read_text(encoding="utf-8"))
    # Y la SALVEDAD tiene que quedar fuera: ahí nombrar el país es obligatorio.
    assert "no son oficiales" not in _titular(_PORTADA_DOCS.read_text(encoding="utf-8"))


def test_el_detector_reconoce_una_jurisdiccion() -> None:
    """Auto-test del criterio, con oráculo escrito a mano — una rama por assert, nunca `!= []`.

    Un `!= []` sobre un texto con dos anclas pasa aunque una de las dos ramas esté muerta.
    """
    assert _ofensores("provisiones CMF (Chile) e IFRS 9") == ["CMF", "Chile"]
    assert _ofensores("Capítulo B-1") == ["Capítulo B-1"]
    assert _ofensores("Capitulo B-1") == ["Capitulo B-1"]  # sin tilde
    assert _ofensores("Circular N° 2.346") == ["Circular N° 2.346"]
    assert _ofensores("las tablas del RAN 21-10") == ["RAN 21-10"]  # el `\b` que costó un bug
    assert _ofensores("fiscalizada por la Comisión para el Mercado Financiero") != []
    assert _ofensores("la SBS peruana") == ["SBS", "peruana"]
    assert _ofensores("el B\u20111 con guion tipografico") == ["B\u20111"]
    # Control negativo del propio detector: los estándares comunes NO son jurisdicción.
    assert _ofensores("PD, LGD y EAD, validación e IFRS 9/ECL bajo Basilea") == []
    assert _ofensores("La normativa local se aterriza encima") == []
    assert _ofensores("NIIF 9 y su staging por SICR") == []


@pytest.mark.parametrize("ruta", [_README, _PORTADA_DOCS], ids=lambda r: r.name)
def test_el_titular_no_nombra_ninguna_jurisdiccion(ruta: Path) -> None:
    ofensores = _ofensores(_titular(ruta.read_text(encoding="utf-8")))
    assert not ofensores, (
        f"{ruta.name}: el titular nombra {', '.join(ofensores)}. Una jurisdicción no va en la "
        "propuesta de valor — bájala a la evidencia (la salvedad de la misma página, o "
        "docs_site/norma-local.md)"
    )


def test_la_descripcion_del_paquete_no_nombra_ninguna_jurisdiccion() -> None:
    """Es el titular que más se lee: pypi.org lo muestra bajo el nombre del paquete."""
    descripcion = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["description"]
    assert descripcion, "pyproject no declara `project.description`"
    assert not _ofensores(descripcion), (
        f"la descripción del paquete nombra {', '.join(_ofensores(descripcion))}"
    )
    # `keywords` queda FUERA a propósito: son descubrimiento, no promesa. Quien busca «cmf» en PyPI
    # debe seguir encontrando el paquete (decisión de Cami, 2026-08-05).


def test_la_descripcion_del_sitio_no_nombra_ninguna_jurisdiccion() -> None:
    """`site_description` alimenta la meta etiqueta, las social cards y el buscador del sitio."""
    # `mkdocs.yml` trae tags de Python (`!!python/name:...`), que el loader seguro rechaza; sólo
    # interesa un escalar de nivel raíz, así que se lee con una expresión en vez de parsear todo.
    crudo = _MKDOCS.read_text(encoding="utf-8")
    bloque = re.search(r"^site_description: *>-\n((?:^ +.*\n)+)", crudo, re.MULTILINE)
    assert bloque is not None, "no se encontró `site_description` como bloque plegado en mkdocs.yml"
    descripcion = " ".join(linea.strip() for linea in bloque.group(1).splitlines())
    assert not _ofensores(descripcion), (
        f"la descripción del sitio nombra {', '.join(_ofensores(descripcion))}"
    )
    # El parser real confirma que la expresión de arriba lee el campo que mkdocs lee, y no otro.
    assert yaml.safe_load(f"site_description: >-\n{bloque.group(1)}")["site_description"].strip()


def test_la_meta_description_de_la_app_no_nombra_ninguna_jurisdiccion() -> None:
    """La superficie que viaja más lejos: previsualizaciones de enlace y buscadores.

    Se le olvidó al primer pase y contradecía al H1 de su propia página, que sí se había reescrito.
    """
    crudo = _INDEX_HTML.read_text(encoding="utf-8")
    meta = re.search(r'name="description"\s*\n?\s*content="([^"]*)"', crudo)
    assert meta is not None, "no se encontró la meta description en web/index.html"
    descripcion = meta.group(1)
    assert len(descripcion) > 80, "la meta description quedó demasiado corta para ser la de verdad"
    assert not _ofensores(descripcion), (
        f"la meta description de la app nombra {', '.join(_ofensores(descripcion))}"
    )


def test_la_pagina_del_caso_de_referencia_existe_y_esta_en_el_nav() -> None:
    """La contraparte: si el titular deja de nombrarla, la evidencia tiene que existir.

    Sin esto, «quitar el país del titular» pasaría el gate borrándolo de todas partes — que es
    exactamente la salida que la decisión descartó.
    """
    pagina = _RAIZ / "docs_site" / "norma-local.md"
    assert pagina.exists(), "falta docs_site/norma-local.md"
    texto = pagina.read_text(encoding="utf-8")
    assert _ofensores(texto), "la página del caso de referencia no nombra ninguna jurisdicción"
    # La fecha de verificación tiene que estar A LA VISTA: es lo que convierte «congelado» en una
    # afirmación comprobable en vez de una excusa.
    manifest = _RAIZ / "src" / "nikodym" / "provisioning" / "cmf" / "data" / "manifest.json"
    manifiesto = json.loads(manifest.read_text(encoding="utf-8"))
    extraccion = manifiesto["extraction_date"]
    assert extraccion in texto, (
        f"la página no publica la fecha de EXTRACCIÓN que declara el manifiesto ({extraccion}), "
        "así que «congelado» no es verificable"
    )
    # Y TODOS los cotejos, no sólo la extracción. Publicar la fecha más débil teniendo una más
    # fuerte fue exactamente el defecto del 2026-08-04: el copy llamó «cotejo» a la extracción.
    for cotejo in manifiesto["verifications"]:
        assert cotejo["date"] in texto, (
            f"el manifiesto declara un cotejo el {cotejo['date']} ({cotejo['scope'][:60]}…) y la "
            "página del caso de referencia no lo publica: se estaría afirmando menos de lo que el "
            "trabajo sostiene, que es el error simétrico del que se corrigió"
        )
    # En el NAV, no en el archivo: `# pendiente: norma-local.md` en un comentario satisfaría un
    # `in` y la página quedaría invisible con el gate en verde.
    assert re.search(
        r"^\s+-\s+.+:\s*norma-local\.md\s*$", _MKDOCS.read_text(encoding="utf-8"), re.M
    ), "la página existe pero no tiene entrada de nav: quedaría invisible"


# --------------------------------------------------------------------------------------------
# El formulario es portada también, y esta parte no existía.
# --------------------------------------------------------------------------------------------

_FIXTURE_SCHEMA = _RAIZ / "web" / "src" / "fixtures" / "schema.json"

# Las dos únicas secciones donde nombrar la norma ES el contenido, no un residuo:
#   · `provisioning_cmf` implementa el modelo estándar chileno — callarlo sería la mentira opuesta.
#   · `provisioning` orquesta la comparación, y la regla del máximo que aplica por defecto es
#     literalmente la del Cap. B-1; describirla sin nombrarla la haría incomprensible.
_SECCIONES_CON_JURISDICCION = frozenset({"provisioning", "provisioning_cmf"})


def _frases_del_schema() -> dict[str, list[str]]:
    """Títulos y descripciones publicados, agrupados por la sección a la que pertenecen.

    Se mide sobre el **fixture** y no sobre ``schema_payload()`` a propósito: el payload vive en
    ``nikodym.ui`` y arrastra el extra ``[ui]``, así que un gate montado sobre él **se salta** en
    los jobs mínimos del CI — y un skip se lee igual que un verde. El gate G7 ya obliga a que el
    fixture sea idéntico al payload, así que medir aquí no pierde nada.
    """

    def textos(nodo: object) -> list[str]:
        salida: list[str] = []
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if clave in ("title", "description") and isinstance(valor, str):
                    salida.append(valor)
                elif clave != "$defs":
                    salida.extend(textos(valor))
        elif isinstance(nodo, list):
            for hijo in nodo:
                salida.extend(textos(hijo))
        return salida

    documento = json.loads(_FIXTURE_SCHEMA.read_text(encoding="utf-8"))
    esquema = documento["json_schema"]
    definiciones = esquema["$defs"]
    por_seccion: dict[str, list[str]] = {}
    for seccion, nodo in esquema["properties"].items():
        frases = textos(nodo)
        for nombre, cuerpo in definiciones.items():
            if nombre.startswith(f"{seccion}__"):
                frases.extend(textos(cuerpo))
        por_seccion[seccion] = frases
    return por_seccion


def test_el_barrido_del_formulario_no_es_vacuo() -> None:
    """Anclas: un barrido que recorre cero frases o cero secciones se lee igual que uno limpio."""
    por_seccion = _frases_del_schema()
    assert len(por_seccion) >= 25, f"el barrido sólo ve {len(por_seccion)} secciones"
    assert sum(len(f) for f in por_seccion.values()) >= 1500, "el barrido recorrió muy poco texto"
    assert set(por_seccion) >= _SECCIONES_CON_JURISDICCION, "cambió el nombre de una sección exenta"

    # Control positivo: las secciones exentas TIENEN que dar ofensores. Si dejan de darlos, o el
    # detector se rompió o la evidencia se borró — y las dos convertirían este gate en un adorno
    # que pasa siempre.
    for seccion in _SECCIONES_CON_JURISDICCION:
        assert _ofensores("\n".join(por_seccion[seccion])), (
            f"la sección {seccion!r} dejó de nombrar su jurisdicción: o se borró la evidencia, "
            "o el detector dejó de detectar"
        )


@pytest.mark.parametrize("seccion", sorted(set(_frases_del_schema()) - _SECCIONES_CON_JURISDICCION))
def test_una_seccion_neutra_del_formulario_no_se_rotula_con_una_jurisdiccion(seccion: str) -> None:
    """El tooltip del formulario es copy público, y el título de una sección se lee sin hover.

    🔴 Esto no lo cubría nada, y por eso sobrevivió a la limpieza de las seis superficies: la
    sección de provisión interna —el motor **jurisdiccionalmente neutro**, el que un banco de
    cualquier país usaría— se titulaba «Calcula las provisiones por el método interno del banco
    (Cap. B-1 §3)», y esa frase viaja al JSON Schema, al fixture y al bundle compilado del front.
    Además de reducir el alcance percibido era **falsa**: ese motor no calcula el B-1.
    """
    ofensores = _ofensores("\n".join(_frases_del_schema()[seccion]))
    assert not ofensores, (
        f"la sección {seccion!r} del formulario nombra una jurisdicción en su copy visible: "
        f"{ofensores}. Si la mención es imprescindible para entender el campo, la sección va a "
        "_SECCIONES_CON_JURISDICCION con su razón escrita; si no, se reformula sin el país."
    )
