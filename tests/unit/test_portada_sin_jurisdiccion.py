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

import ast
import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

from nikodym.ui.jobs import list_jobs

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


# --------------------------------------------------------------------------------------------
# El ESTADO DE FÁBRICA también es portada, y esto tampoco existía.
# --------------------------------------------------------------------------------------------

# La única sección donde un default puede nombrar la jurisdicción: `provisioning_cmf` implementa el
# modelo estándar chileno y sus columnas de fábrica (`cmf_portfolio`, `cmf_category`,
# `cmf_product_type`) nombran la taxonomía regulatoria que ES su contenido.
#
# ⚠️ La lista NO es `_SECCIONES_CON_JURISDICCION`, y la diferencia está medida: el orquestador
# `provisioning` puede nombrar el Cap. B-1 en su copy —describir la regla del máximo sin nombrarla
# la haría incomprensible— pero **ninguno de sus defaults nombra un país**. Reusar allí la lista de
# copy habría eximido a una sección que no lo necesita, y con ella habría caído el control positivo.
_SECCIONES_CON_DEFAULT_JURISDICCIONAL = frozenset({"provisioning_cmf"})


def _defaults_del_schema() -> dict[str, list[str]]:
    """Valores por defecto de tipo texto publicados, agrupados por sección.

    Mismo criterio de fuente que ``_frases_del_schema``: el **fixture**, nunca ``schema_payload()``.
    """

    def valores(nodo: object) -> list[str]:
        salida: list[str] = []
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if clave == "default":
                    if isinstance(valor, str):
                        salida.append(valor)
                    elif isinstance(valor, list):
                        salida.extend(x for x in valor if isinstance(x, str))
                elif clave != "$defs":
                    salida.extend(valores(valor))
        elif isinstance(nodo, list):
            for hijo in nodo:
                salida.extend(valores(hijo))
        return salida

    documento = json.loads(_FIXTURE_SCHEMA.read_text(encoding="utf-8"))
    esquema = documento["json_schema"]
    definiciones = esquema["$defs"]
    por_seccion: dict[str, list[str]] = {}
    for seccion, nodo in esquema["properties"].items():
        encontrados = valores(nodo)
        for nombre, cuerpo in definiciones.items():
            if nombre.startswith(f"{seccion}__"):
                encontrados.extend(valores(cuerpo))
        por_seccion[seccion] = encontrados
    return por_seccion


def test_el_barrido_de_defaults_no_es_vacuo() -> None:
    """Anclas y control positivo: un barrido que recorre cero defaults se lee como uno limpio."""
    por_seccion = _defaults_del_schema()
    assert len(por_seccion) >= 25, f"el barrido sólo ve {len(por_seccion)} secciones"
    total = sum(len(v) for v in por_seccion.values())
    assert total >= 250, f"el barrido sólo recorrió {total} defaults de texto"
    assert set(por_seccion) >= _SECCIONES_CON_DEFAULT_JURISDICCIONAL, "cambió una sección exenta"

    # Control positivo: la sección exenta TIENE que dar ofensores. Si deja de darlos, o el detector
    # se rompió o la evidencia se borró — y las dos vuelven este gate un adorno que pasa siempre.
    for seccion in _SECCIONES_CON_DEFAULT_JURISDICCIONAL:
        assert _ofensores("\n".join(por_seccion[seccion])), (
            f"la sección {seccion!r} dejó de traer defaults con su taxonomía normativa: o se borró "
            "la evidencia, o el detector dejó de detectar"
        )


@pytest.mark.parametrize(
    "seccion", sorted(set(_defaults_del_schema()) - _SECCIONES_CON_DEFAULT_JURISDICCIONAL)
)
def test_el_default_de_una_seccion_neutra_no_nombra_una_jurisdiccion(seccion: str) -> None:
    """El valor de fábrica es una afirmación tan pública como el título, y no lo miraba nadie.

    🔴 El gate hermano de arriba barre ``title`` y ``description`` de las 29 secciones — y por eso
    **no podía** cazar este defecto: el título y la ayuda de ``provisioning_internal.portfolio_col``
    ya eran neutros, y lo chileno era el **valor**, ``default="cmf_portfolio"``. Un motor que se
    presenta como jurisdiccionalmente neutro pedía de fábrica una columna con el nombre de un
    supervisor, así que un banco de cualquier otro país tenía que renombrar su columna para correr
    un cálculo que no conoce ninguna norma (D-JUR-8).

    Un default no se lee con hover: se ejecuta. Es la afirmación más fuerte que hace el formulario.
    """
    ofensores = _ofensores("\n".join(_defaults_del_schema()[seccion]))
    assert not ofensores, (
        f"la sección {seccion!r} trae un valor de fábrica que nombra una jurisdicción: "
        f"{ofensores}. El estado de fábrica de una sección neutra no puede exigir la taxonomía de "
        "un supervisor; si la sección implementa una norma local, va a "
        "_SECCIONES_CON_DEFAULT_JURISDICCIONAL con su razón escrita."
    )


# --------------------------------------------------------------------------------------------
# Prosa y catálogo: las dos superficies grandes que este gate NO barría.
# --------------------------------------------------------------------------------------------
#
# El barrido del formulario mide `title` y `description` del **schema**, así que dos superficies de
# copy público quedaban enteras fuera y son las de más volumen del repo: el catálogo de trabajos
# (`ui/jobs.py`, que es la primera pantalla y publica los 69 puntos de elección del abanico con sus
# 172 opciones) y la **prosa del informe** (`report/prose.py`).
#
# 🔴 La prosa es la de más consecuencia de las dos: es lo que se imprime en el HTML/PDF/Word y se
# entrega a un tercero, y el 2026-08-07 se midió que puede publicar una frase falsa sobre toda la
# cartera sin que ningún gate se ponga rojo.
#
# ⚠️ Alcance declarado, para que nadie lea de más: esto cierra la clase «una jurisdicción se cuela en
# una superficie neutra», que es la de este archivo. **No** cierra «la prosa afirma algo falso sobre
# el cálculo», que es otra clase y se vigila atando cada frase a su aritmética.
#
# ⚠️ Y los dos módulos se pueden medir sin el extra ``[ui]``, verificado bloqueando
# ``starlette``/``fastapi``/``uvicorn`` en el importador: ``nikodym/ui/__init__.py`` es liviano a
# propósito y lo declara en su docstring, y ``report/prose.py`` sólo importa ``decimal`` y
# ``nikodym``. Por eso aquí sí se mide la **fuente** y no un fixture, al contrario que el barrido
# del formulario de arriba — y no es incoherencia: allí el payload arrastraba el extra, aquí no.

_PROSE = _RAIZ / "src" / "nikodym" / "report" / "prose.py"
_JOBS = _RAIZ / "src" / "nikodym" / "ui" / "jobs.py"

# Un identificador en snake_case es una clave de dict o un literal de enum del motor, nunca copy.
# Sin este corte, `"cmf"` y `"cmf_only"` —el valor con que el orquestador nombra su propia rama—
# entran como ofensores: seis falsos positivos medidos, y el detector es `IGNORECASE`.
_ES_IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]*$")


def _prosa_por_funcion(ruta: Path) -> dict[str, list[tuple[int, str]]]:
    """Literales de texto que un humano lee, agrupados por la función que los emite.

    Se mide por **AST del fuente** y no ejecutando el informe, y la razón es de cobertura: un
    barrido sobre documentos renderizados sólo ve las ramas que sus fixtures ejercitan, y el
    defecto del capítulo mudo del 2026-08-05 vivía justamente en la única combinación que nadie
    enumeró. El AST ve las ramas que ningún fixture alcanza.

    Quedan fuera, con su razón: los **docstrings** (documentación de implementación, no copy), los
    **comentarios** —que el AST ni ve, y en este archivo son la mitad de las menciones: explican por
    qué una frase NO puede nombrar un país— y las **claves** de los dicts de labels, que el repo ya
    tiene excluidas del copy público.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    dueno: dict[int, str] = {}
    docstrings: set[int] = set()
    claves: set[tuple[int, int]] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
            for linea in range(nodo.lineno, (nodo.end_lineno or nodo.lineno) + 1):
                dueno[linea] = nodo.name
        if isinstance(nodo, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            primero = nodo.body[0] if nodo.body else None
            if (
                isinstance(primero, ast.Expr)
                and isinstance(primero.value, ast.Constant)
                and isinstance(primero.value.value, str)
            ):
                fin = primero.end_lineno or primero.lineno
                docstrings.update(range(primero.lineno, fin + 1))
        if isinstance(nodo, ast.Dict):
            claves.update(
                (clave.lineno, clave.col_offset)
                for clave in nodo.keys
                if isinstance(clave, ast.Constant) and isinstance(clave.value, str)
            )

    salida: dict[str, list[tuple[int, str]]] = {}
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)):
            continue
        if nodo.lineno in docstrings or (nodo.lineno, nodo.col_offset) in claves:
            continue
        if _ES_IDENTIFICADOR.match(nodo.value):
            continue
        salida.setdefault(dueno.get(nodo.lineno, "<módulo>"), []).append((nodo.lineno, nodo.value))
    return salida


# Las funciones de prosa donde nombrar la norma ES el contenido. La lista se escribe a mano —el
# nombre de una función no dice a qué dominio pertenece de forma fiable— pero **no queda sin
# ancla**:
# `test_las_funciones_de_prosa_exentas_son_coherentes` exige que cada nombre exista de verdad, que
# emita prosa y que su dominio sea uno de los dos ya exentos en el formulario. Los cuatro nombres
# cubren exactamente esos dos dominios:
#   · `provisioning` (el orquestador de la comparación) → `provisions_intro`,
#     `_provisions_intro_motor_unico`, `_results_provisioning`. La regla del máximo que aplica por
#     defecto es literalmente la del Cap. B-1: describirla sin nombrarla la haría incomprensible, y
#     el informe que la invoca tiene que poder citar su circular.
#   · `provisioning_cmf` (el modelo estándar chileno) → `_results_provisioning_cmf`.
#
# 🔴 Lo que NO entra, y es el punto entero de este gate: `_results_provisioning_internal` y
# `_results_provisioning_ifrs9`. El primero describe el motor **jurisdiccionalmente neutro**, y
# hasta el 2026-08-05 publicaba «el método interno es el que la norma también exige» —cierta en
# Chile y falsa para quien corre ese motor sin norma detrás—. Corregido; esto impide que vuelva.
_FUNCIONES_DE_PROSA_CON_JURISDICCION = frozenset(
    {
        "provisions_intro",
        "_provisions_intro_motor_unico",
        "_results_provisioning",
        "_results_provisioning_cmf",
    }
)


def test_el_barrido_de_la_prosa_del_informe_no_es_vacuo() -> None:
    """Anclas: una prosa que recorre cero funciones o cero frases se lee igual que una limpia."""
    por_funcion = _prosa_por_funcion(_PROSE)
    assert len(por_funcion) >= 40, f"el barrido sólo ve {len(por_funcion)} funciones de prosa"
    total = sum(len(v) for v in por_funcion.values())
    assert total >= 500, f"el barrido sólo recorrió {total} literales de prosa"

    # Y que esté mirando la prosa DEL INFORME, no cualquier string: tres frases que se imprimen.
    todo = "\n".join(t for frases in por_funcion.values() for _, t in frases)
    for ancla in ("provisión", "cartera", "incumplimiento"):
        assert ancla in todo, f"el barrido no encuentra {ancla!r}: no está leyendo la prosa"

    # Control positivo: las funciones exentas TIENEN que dar ofensores. Si dejan de darlos, o el
    # detector se rompió o la evidencia se borró — y las dos vuelven este gate un adorno.
    for funcion in _FUNCIONES_DE_PROSA_CON_JURISDICCION:
        assert _ofensores("\n".join(t for _, t in por_funcion[funcion])), (
            f"la función de prosa {funcion!r} dejó de nombrar la norma que aplica: o se borró la "
            "evidencia del informe, o el detector dejó de detectar"
        )


def test_las_funciones_de_prosa_exentas_son_coherentes() -> None:
    """La exención escrita a mano no puede quedar sin ancla: se cotejan sus tres condiciones.

    Sin esto, un nombre mal escrito eximiría a nadie (y pasaría en verde), y un nombre nuevo podría
    eximir un dominio que el formulario no exime — que sería decidir por la puerta de atrás lo que
    ``_SECCIONES_CON_JURISDICCION`` ya decidió.
    """
    por_funcion = _prosa_por_funcion(_PROSE)
    for funcion in _FUNCIONES_DE_PROSA_CON_JURISDICCION:
        assert funcion in por_funcion, (
            f"{funcion!r} está exenta y no emite prosa en {_PROSE.name}: o se renombró, o la "
            "exención sobra. Una exención que no apunta a nada se lee como cobertura."
        )
    # El dominio de las cuatro tiene que ser uno de los dos que el formulario ya exime. `provisions`
    # es el prefijo con que este archivo nombra al orquestador `provisioning`.
    for funcion in _FUNCIONES_DE_PROSA_CON_JURISDICCION:
        assert any(
            dominio.removeprefix("provisioning") in funcion.replace("provisions", "provisioning")
            for dominio in _SECCIONES_CON_JURISDICCION
        ), (
            f"{funcion!r} no pertenece a ninguno de los dominios exentos "
            f"{sorted(_SECCIONES_CON_JURISDICCION)}"
        )


@pytest.mark.parametrize(
    "funcion", sorted(set(_prosa_por_funcion(_PROSE)) - _FUNCIONES_DE_PROSA_CON_JURISDICCION)
)
def test_la_prosa_neutra_del_informe_no_nombra_ninguna_jurisdiccion(funcion: str) -> None:
    """El informe se entrega a un tercero, y esta superficie no la miraba ningún gate.

    Un capítulo que no implementa una norma local no puede invocarla: quien corre este motor en otro
    país recibiría un documento que afirma una regla que no le rige.
    """
    frases = _prosa_por_funcion(_PROSE)[funcion]
    ofensores = sorted({o for _, texto in frases for o in _ofensores(texto)})
    culpables = [f"{_PROSE.name}:{ln}" for ln, texto in frases if _ofensores(texto)]
    assert not ofensores, (
        f"la prosa de {funcion!r} nombra una jurisdicción ({', '.join(ofensores)}) en "
        f"{', '.join(culpables)}. El informe lo lee un tercero: si esa función implementa una "
        "norma local, va a _FUNCIONES_DE_PROSA_CON_JURISDICCION con su razón escrita; si no, se "
        "reformula sin la norma."
    )


def _copy_de_los_trabajos() -> dict[str, list[str]]:
    """Todo el texto que el catálogo de trabajos publica, por trabajo.

    Se recorren los **valores** del catálogo construido, nunca sus claves, y se barre en
    profundidad: así entran las preguntas de las decisiones obligatorias, los motivos de no
    disponibilidad y —lo
    que más pesa— los rótulos y las ayudas de las opciones del abanico metodológico, que son la
    superficie de copy más grande que publica el backend.
    """

    def textos(nodo: object) -> list[str]:
        if isinstance(nodo, str):
            return [] if _ES_IDENTIFICADOR.match(nodo) else [nodo]
        if isinstance(nodo, dict):
            return [t for valor in nodo.values() for t in textos(valor)]
        if isinstance(nodo, list | tuple):
            return [t for hijo in nodo for t in textos(hijo)]
        return []

    return {str(trabajo["id"]): textos(trabajo) for trabajo in list_jobs()}


def _trabajos_con_jurisdiccion() -> frozenset[str]:
    """Los trabajos exentos se **derivan** del catálogo, no de una lista escrita al lado.

    El discriminador es ``jurisdiction_code``, que el catálogo ya declaraba antes de este gate y que
    el front usa para sacar esos trabajos del listado principal (decisión del 2026-08-04). Derivarlo
    tiene dos consecuencias buenas: un caso de referencia nuevo hereda la exención **declarando su
    jurisdicción**, que es exactamente lo que debe hacer; y silenciar un rojo declarando `CL` en un
    trabajo neutro no es gratis — lo saca del listado principal, que es un costo visible.
    """
    return frozenset(
        str(t["id"]) for t in list_jobs() if t.get("jurisdiction_code") not in (None, "")
    )


def test_el_barrido_del_catalogo_de_trabajos_no_es_vacuo() -> None:
    """Anclas y control positivo del catálogo."""
    por_trabajo = _copy_de_los_trabajos()
    assert len(por_trabajo) >= 10, f"el barrido sólo ve {len(por_trabajo)} trabajos"
    total = sum(len(v) for v in por_trabajo.values())
    assert total >= 600, f"el barrido sólo recorrió {total} textos del catálogo"

    exentos = _trabajos_con_jurisdiccion()
    assert exentos, (
        "ningún trabajo declara jurisdicción: el caso de referencia se borró del catálogo"
    )
    assert set(por_trabajo) >= exentos, "un trabajo exento no aparece en el barrido"

    # Control positivo: un trabajo que declara jurisdicción TIENE que nombrarla en su copy. Si no la
    # nombra, `jurisdiction_code` se está usando para silenciar este gate y no para declarar un caso
    # de referencia — que es el único abuso que la derivación automática dejaría abierto.
    for trabajo in exentos:
        assert _ofensores("\n".join(por_trabajo[trabajo])), (
            f"el trabajo {trabajo!r} declara jurisdicción y no la nombra en su copy: o se borró la "
            "evidencia, o `jurisdiction_code` se está usando para eximirse de este gate"
        )


def test_el_catalogo_publica_todo_el_copy_con_jurisdiccion_del_fuente() -> None:
    """Que medir el catálogo construido no deje texto del fuente sin mirar.

    🔴 El riesgo es el simétrico del que este archivo ya paga en el formulario: allí se mide un
    fixture porque el payload arrastra un extra, y un gate G7 aparte garantiza que el fixture no
    derive. Aquí se mide el objeto construido, así que hace falta la garantía inversa — que ningún
    literal de jurisdicción viva en el fuente **sin llegar** al catálogo, donde este gate no lo
    vería. Medido hoy: 21 literales sólo existen en el fuente y **ninguno** nombra jurisdicción (son
    citas ``archivo:línea`` de comentarios y trozos de mensajes de error de otro gate).
    """
    arbol = ast.parse(_JOBS.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    claves: set[tuple[int, int]] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            primero = nodo.body[0] if nodo.body else None
            if (
                isinstance(primero, ast.Expr)
                and isinstance(primero.value, ast.Constant)
                and isinstance(primero.value.value, str)
            ):
                docstrings.update(range(primero.lineno, (primero.end_lineno or primero.lineno) + 1))
        if isinstance(nodo, ast.Dict):
            claves.update(
                (clave.lineno, clave.col_offset)
                for clave in nodo.keys
                if isinstance(clave, ast.Constant) and isinstance(clave.value, str)
            )

    publicado = {t for textos in _copy_de_los_trabajos().values() for t in textos}
    assert len(publicado) >= 500, f"el catálogo sólo publica {len(publicado)} textos distintos"

    huerfanos: list[str] = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)):
            continue
        if nodo.lineno in docstrings or (nodo.lineno, nodo.col_offset) in claves:
            continue
        if _ES_IDENTIFICADOR.match(nodo.value) or nodo.value in publicado:
            continue
        if _ofensores(nodo.value):
            huerfanos.append(f"{_JOBS.name}:{nodo.lineno} {nodo.value[:70]!r}")
    assert not huerfanos, (
        "hay copy con jurisdicción en el fuente del catálogo que `list_jobs()` no publica, así que "
        f"este gate no lo estaría mirando: {huerfanos}"
    )


@pytest.mark.parametrize(
    "trabajo", sorted(set(_copy_de_los_trabajos()) - _trabajos_con_jurisdiccion())
)
def test_un_trabajo_neutro_no_nombra_ninguna_jurisdiccion(trabajo: str) -> None:
    """El catálogo es la PRIMERA pantalla: es la propuesta de valor de la aplicación.

    Y es la superficie de copy más grande del backend, porque cada trabajo publica además su abanico
    metodológico con lo que hace y lo que exige cada opción. Un trabajo que no declara jurisdicción
    no puede nombrar una: o la declara —y sale del listado principal, como el caso de referencia—, o
    su copy es neutro.
    """
    textos = _copy_de_los_trabajos()[trabajo]
    ofensores = sorted({o for texto in textos for o in _ofensores(texto)})
    assert not ofensores, (
        f"el trabajo {trabajo!r} no declara `jurisdiction_code` y su copy nombra "
        f"{', '.join(ofensores)}. Si el trabajo implementa una norma local, declara su "
        "jurisdicción en el catálogo —eso lo mueve al bloque de casos de referencia—; si no, "
        "reformula el copy."
    )


# --------------------------------------------------------------------------------------------
# Dos superficies más que el censo destapó, y las dos eran ofensores REALES.
# --------------------------------------------------------------------------------------------
#
# 🔴 Este bloque nació de una revisión adversarial del gate de arriba, y su lección es que **el
# alcance de un gate de copy se mide, no se supone**. Los dos barridos anteriores nacieron verdes
# —ni el catálogo ni la prosa tenían un solo ofensor— y aun así quedaban vivos éstos:
#
# 1. **El docstring del paquete raíz** decía «librería de riesgo de crédito (scoring, ML,
#    provisiones **CMF** e IFRS 9)». Es la portada del paquete **por código**: medido ejecutando,
#    `nikodym.__doc__` y `help(nikodym)` la publican como primera línea. Es hermana exacta de
#    `project.description` —que ya estaba en este gate desde el 2026-08-04— y se escapó por no
#    estar en la lista de superficies.
# 2. **El panel de resultados de la aplicación** rotulaba «Provisiones — la regla del máximo (CMF
#    Cap. B-1)» con la bajada «La norma **chilena** obliga … (Circular N° 2.346). **Montos en pesos
#    (CLP)**.», y más abajo «por grupo homogéneo **(B-1 §3)**» sobre el motor neutro. Texto
#    **fijo**, visible sin hover, sobre un orquestador que admite `provisioning_ifrs9` +
#    `provisioning_internal` **sin CMF**. La prosa del informe dejó de hacerlo el 2026-08-05
#    (`prose.py:1601-1637` gatea la cita del B-1); **la corrección no se propagó a la
#    pantalla**, que es la que ve quien corre por la interfaz. Y «(B-1 §3)» era la reincidencia
#    literal del título que esta misma sección llevaba en el formulario hasta D-JUR-8.
#
# ⚠️ Lo que este gate NO puede vigilar, medido y declarado en vez de callado: el censo confirmó tres
# ofensores más —«al peso entero», «por peso expuesto» y «la norma exige agrupar»— que este detector
# **no caza y no debe cazar**. «Peso» es homónimo en español (unidad monetaria y ponderación) y
# añadirlo produce ~10 falsos positivos sobre los «pesos de escenario» de IFRS 9 y forward; y «la
# norma exige» es legítimo donde la norma **es** un estándar internacional (NIIF 9). Los tres se
# corrigieron a mano; la clase «afirmación normativa sin norma detrás» necesita otro mecanismo, y un
# vocabulario inflado con falsos positivos se aprende a ignorar, que es peor que no tenerlo.

_INIT_PAQUETE = _RAIZ / "src" / "nikodym" / "__init__.py"

# Atributos de un componente cuyo valor literal se pinta como texto. `title` y `description` son los
# de `ResultsSection`; los otros tres entran porque son copy visible de la misma clase.
_ATRIBUTO_DE_COPY = re.compile(
    r'\b(title|description|label|placeholder|helpText)=\{?"((?:[^"\\]|\\.)*)"\}?'
)

# El copy del front donde nombrar la norma ES el contenido: son los dos rótulos del bloque que
# publica el **método estándar CMF por categoría**, gateado por la presencia de la card de ese
# motor.
# Va por su literal exacto y no por archivo, a propósito: si alguien reescribe una de estas dos
# frases el gate se pone rojo y hay que volver a declararla — y revisar ese copy es justo lo que se
# quiere que ocurra. La razón de fondo es la misma que exime a `provisioning_cmf` en el formulario:
# ese bloque implementa el modelo estándar chileno, y callarlo sería la mentira opuesta.
_COPY_DEL_FRONT_CON_JURISDICCION = frozenset(
    {
        "Método estándar CMF por categoría",
        (
            "Provisión estándar por categoría del Cap. B-1, ordenada de mayor a menor. La "
            "categoría se deriva de (días de mora · crédito hipotecario en el sistema · mora en "
            "el sistema)."
        ),
    }
)


def _copy_literal_del_front() -> list[tuple[str, str, str]]:
    """``(archivo, atributo, texto)`` de todo copy literal de los componentes.

    Se leen los **atributos** y no el archivo entero, y no es una comodidad: los comentarios de
    estos mismos componentes nombran el Cap. B-1 legítimamente —explican por qué el copy ya no puede
    nombrarlo—, así que un barrido del texto crudo se acusaría a sí mismo. Un atributo con valor
    literal es exactamente la superficie del defecto: texto fijo que se pinta sin condición.

    ⚠️ Alcance declarado: el copy que llega por **expresión** (``title={algo}``) no se ve desde aquí,
    y es a propósito — ahí el texto lo decide una función, que es lo que este gate quiere que pase.
    El caso corregido pasó justamente de literal a expresión (`provisioningSectionCopy`), y su
    corrección la vigila un test de comportamiento en vitest, no un detector de términos.
    """
    salida: list[tuple[str, str, str]] = []
    for archivo in sorted((_RAIZ / "web" / "src").rglob("*.tsx")):
        contenido = archivo.read_text(encoding="utf-8")
        for atributo, valor in _ATRIBUTO_DE_COPY.findall(contenido):
            salida.append((archivo.name, atributo, valor))
    return salida


def test_el_barrido_del_copy_del_front_no_es_vacuo() -> None:
    """Anclas y control positivo: 96 atributos en 14 componentes al escribir esto."""
    copy = _copy_literal_del_front()
    assert len(copy) >= 70, f"el barrido sólo ve {len(copy)} atributos de copy"
    assert len({archivo for archivo, _, _ in copy}) >= 10, "el barrido ve muy pocos componentes"
    assert any(atributo == "description" for _, atributo, _ in copy), (
        "el barrido no encuentra un solo `description`: la regex dejó de casar"
    )

    # Control positivo: los literales exentos tienen que SEGUIR existiendo y seguir dando
    # ofensores. Si uno desaparece, la exención quedó apuntando al vacío y este gate se relajó sin
    # que nadie lo decida.
    presentes = {texto for _, _, texto in copy}
    for texto in _COPY_DEL_FRONT_CON_JURISDICCION:
        assert texto in presentes, (
            f"el copy exento {texto[:50]!r} ya no está en ningún componente: la exención sobra, o "
            "se borró la evidencia del caso de referencia"
        )
        assert _ofensores(texto), (
            f"el copy exento {texto[:50]!r} dejó de nombrar una jurisdicción: o el detector se "
            "rompió, o esa exención no hacía falta"
        )


def test_el_copy_literal_del_front_no_nombra_ninguna_jurisdiccion() -> None:
    """La pantalla de resultados es lo que ve quien corre por la interfaz, y no la miraba nadie."""
    ofensores = [
        (archivo, atributo, _ofensores(texto), texto)
        for archivo, atributo, texto in _copy_literal_del_front()
        if _ofensores(texto) and texto not in _COPY_DEL_FRONT_CON_JURISDICCION
    ]
    assert not ofensores, (
        "hay copy fijo del front que nombra una jurisdicción: "
        + "; ".join(
            f"{archivo} [{atributo}] {sorted(marcas)} → {texto[:70]!r}"
            for archivo, atributo, marcas, texto in ofensores
        )
        + ". Si el bloque implementa una norma local, su literal va a "
        "_COPY_DEL_FRONT_CON_JURISDICCION con su razón; si el texto depende de lo que la corrida "
        "comparó, se DERIVA de los resultados como hace la prosa del informe."
    )


def test_la_portada_del_paquete_por_codigo_no_nombra_ninguna_jurisdiccion() -> None:
    """El docstring de ``nikodym`` es lo que imprime ``help(nikodym)``: portada, no implementación.

    Hermana exacta de ``project.description`` —que este gate ya vigila— y se escapó de la limpieza
    del 2026-08-04 por no estar en la lista de superficies. Se lee por AST y no importando el
    paquete, para no depender de que el import funcione en un job sin extras.
    """
    arbol = ast.parse(_INIT_PAQUETE.read_text(encoding="utf-8"))
    docstring = ast.get_docstring(arbol)
    assert docstring, "el paquete `nikodym` perdió su docstring: `help(nikodym)` saldría vacío"
    titular = docstring.splitlines()[0]
    assert "riesgo de crédito" in titular, (
        "la primera línea del docstring dejó de describir el producto: este gate no está mirando "
        "la portada"
    )
    assert not _ofensores(titular), (
        f"el docstring del paquete nombra {', '.join(_ofensores(titular))} en su primera línea, "
        "que es lo que imprime `help(nikodym)`. Una jurisdicción no va en la propuesta de valor."
    )
