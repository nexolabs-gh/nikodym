"""Gate del copy VISIBLE del formulario del UI instalable.

`test_public_copy.py` vigila que los códigos internos de aviso no salgan al copy público. Este
gate vigila la otra mitad del mismo problema, y la que se paga en una demo: que el formulario no
hable en Python. Nace de tres hallazgos consecutivos, los tres encontrados **mirando la pantalla**
y ninguno cazado por 4.550 tests:

1. La auditoría previa a `1.10.0`: ocho descripciones que empezaban por «True …» sobre interruptores
   que en pantalla dicen Activado/Desactivado, y cinco etiquetas en inglés o calcadas.
2. La reincidencia del tooltip de `missing_policy`, que mandaba a elegir «warning» cuando el
   selector muestra `error`, `warn`, `skip`.
3. El ensayo D3: **26 descripciones** con `None`, `True` o `False` como literales de Python en
   secciones que se abren en la demo (`data`, `binning`, `selection`, `model`, `scorecard`,
   `calibration`).

⚠️ Por qué la `description` cuenta como copy visible **sin hover**: `fieldPlaceholder`
(`web/src/lib/form-engine.ts`) cae en la `description` cuando el campo no declara `examples`, así
que es el *placeholder* del input. Un `None` ahí lo lee cualquiera que abra la pantalla.

Alcance: las secciones que el formulario ofrece de verdad (`CONFIG_SECTIONS` del front). Las demás
—`ml`, `tuning`, `explain`, `markov`, `forward`, `stress`— no tienen pantalla, así que su copy no
es todavía copy público; el día que entren al formulario, entran a este gate por la misma lista.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from nikodym.core.markers import DECLARED_MARKERS
from nikodym.ui.routes import schema_payload

#: Las secciones que el formulario expande hoy. Espejo de `CONFIG_SECTIONS`
#: (`web/src/lib/schema.ts`); el gate de deriva de ese catálogo vive en `test_column_roles.py`.
SECCIONES_DEL_FORMULARIO = (
    "data",
    "eda",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    "validation",
    "survival",
    "provisioning_cmf",
    "provisioning_internal",
    "provisioning_ifrs9",
    "provisioning",
    "report",
    "governance",
)

#: Literales de Python que no significan nada para quien mira una pantalla en español. `None` es
#: «en blanco»/«sin definir»; `True`/`False` son «activado»/«desactivado», que es justo lo que el
#: interruptor muestra al lado.
_LITERALES_PYTHON = re.compile(r"\b(None|True|False)\b")


def _campos_visibles() -> list[tuple[str, dict[str, Any]]]:
    """Todos los campos hoja que el formulario pinta, con su ruta legible.

    Baja por `$ref`, por la rama no-nula de un `anyOf` (una sección apagable viaja como
    ``anyOf: [<objeto>, null]``) y por los `items` de las listas de objetos, que desde `dd8161f`
    se editan fila a fila y por tanto también se ven.
    """
    schema = schema_payload()["json_schema"]
    defs = schema.get("$defs", {})

    def resolver(nodo: Any, visto: tuple[str, ...]) -> dict[str, Any]:
        if not isinstance(nodo, dict):
            return {}
        if "$ref" in nodo:
            nombre = nodo["$ref"].rsplit("/", 1)[-1]
            if nombre in visto:  # recursión (p. ej. reglas anidadas): se corta
                return {}
            base = resolver(defs.get(nombre, {}), (*visto, nombre))
            return {**base, **{k: v for k, v in nodo.items() if k != "$ref"}}
        for rama in nodo.get("anyOf") or nodo.get("oneOf") or []:
            if isinstance(rama, dict) and rama.get("type") != "null":
                hijo = resolver(rama, visto)
                if hijo.get("properties") or hijo.get("type"):
                    # Hereda TODO lo del padre menos la unión misma. Heredar sólo `title` y
                    # `description` costó un falso positivo: `ui_widget: "hidden"` vive en el
                    # padre de un `bool | None`, así que dos campos ocultos se contaban como
                    # visibles.
                    heredado = {k: v for k, v in nodo.items() if k not in ("anyOf", "oneOf")}
                    return {**heredado, **hijo}
        return nodo

    def ramas_de(nodo: dict[str, Any]) -> list[dict[str, Any]]:
        """Las ramas no-nulas de una unión, TODAS.

        🔴 ``resolver`` se queda con la **primera**, y eso dejaba fuera del gate cualquier campo que
        sólo exista en otra rama: con la unión discriminada de la LGD del método interno, el
        formulario pinta cinco formas y este barrido veía una. Es el mismo defecto que el oráculo
        del abanico tuvo hasta el 2026-08-08 —«inspecciona la primera rama»— y la tercera vez que
        aparece en este repo. Medido al cerrarlo: la cobertura pasa de 192 a **424 rutas**, y los
        otros dos gates de este archivo siguen en cero ofensores.
        """
        ramas = [
            r
            for r in (nodo.get("anyOf") or nodo.get("oneOf") or [])
            if isinstance(r, dict) and r.get("type") != "null"
        ]
        if len(ramas) < 2:
            return []
        heredado = {k: v for k, v in nodo.items() if k not in ("anyOf", "oneOf")}
        return [{**heredado, **resolver(r, visto_vacio)} for r in ramas]

    visto_vacio: tuple[str, ...] = ()

    campos: list[tuple[str, dict[str, Any]]] = []

    def recorrer(nodo: Any, ruta: str, visto: tuple[str, ...] = ()) -> None:
        if ramas := ramas_de(nodo if isinstance(nodo, dict) else {}):
            # Una unión de VARIAS ramas se recorre entera: cada forma pinta campos distintos.
            for rama in ramas:
                recorrer(rama, ruta, visto)
            return
        resuelto = resolver(nodo, visto)
        if resuelto.get("ui_widget") == "hidden":
            return  # fontanería del config: no se pinta, así que no es copy
        if propiedades := resuelto.get("properties"):
            for nombre, hijo in propiedades.items():
                recorrer(hijo, f"{ruta}.{nombre}", visto)
            return
        if items := resuelto.get("items"):
            # La LISTA tiene su propio título visible («Catálogo de valores especiales»), así que
            # se registra antes de bajar a la fila. Sin esto el gate perdía el título de las once
            # listas del config — y ahí vivía uno en inglés que sólo se vio al leer un aria-label.
            campos.append((ruta, resuelto))
            recorrer(items, f"{ruta}[]", visto)
            return
        campos.append((ruta, resuelto))

    for seccion in SECCIONES_DEL_FORMULARIO:
        nodo = (schema.get("properties") or {}).get(seccion)
        if nodo is not None:
            recorrer(nodo, seccion)
    return campos


def test_las_secciones_del_barrido_son_las_que_el_formulario_ofrece() -> None:
    """El espejo escrito a mano se compara con el catálogo del front, en los dos sentidos.

    🔴 Hasta la capa 3 del scorecard completo (2026-09-11) nadie lo comparaba: este archivo,
    `test_effective_defaults.py` y `test_jobs_decisiones.py` copian `CONFIG_SECTIONS` a mano, y
    una sección nueva que entrara al formulario sin sumarse aquí dejaba **su copy sin gate** en
    silencio —el barrido no la recorría, así que ni un literal Python ni una marca interna en sus
    tooltips ponían rojo—. Es la clase de censo que S8 anotó como «ninguno lo dice hasta la suite
    entera», y ahora lo dice este test, con el orden incluido.
    """
    from test_column_roles import _SCHEMA_TS

    texto = _SCHEMA_TS.read_text(encoding="utf-8")
    _, _, resto = texto.partition("export const CONFIG_SECTIONS")
    bloque, _, _ = resto.partition("\n]")
    del_front = re.findall(r'key:\s*"([a-z_0-9]+)"', bloque)
    assert del_front, "no se pudo leer CONFIG_SECTIONS de schema.ts"
    assert list(SECCIONES_DEL_FORMULARIO) == del_front, (
        "el espejo de secciones de este gate no coincide con `CONFIG_SECTIONS` del front: una "
        "sección que entre al formulario sin sumarse aquí se queda sin gate de copy"
    )


def test_el_barrido_ve_el_formulario_completo() -> None:
    """Sin esto, un gate que no recorre nada da verde y no prueba nada.

    Ya pasó al medir esto por primera vez: una suposición equivocada sobre la forma del payload
    dejó el barrido en **cero campos** y el resultado se leyó como «no hay ofensores».
    """
    campos = _campos_visibles()
    assert len(campos) > 300, f"el formulario tiene cientos de campos, no {len(campos)}"
    rutas = {ruta for ruta, _ in campos}
    # Anclas concretas de las tres pantallas que se recorren en una demo.
    assert "data.schema.columns[].name" in rutas, "las filas de una lista también se editan"
    # Una lista de strings baja a sus `items`, así que su ruta lleva el sufijo `[]`.
    assert "binning.feature_columns[]" in rutas
    assert "report.document.model_name" in rutas


@pytest.mark.parametrize("campo", ["title", "description"])
def test_ningun_campo_visible_habla_en_python(campo: str) -> None:
    """`None`, `True` y `False` no son palabras: son literales del lenguaje.

    El usuario ve «en blanco» y un interruptor que dice Activado/Desactivado. Escribir «Si True…»
    lo manda a buscar en la pantalla algo que la pantalla no muestra — el mismo defecto que la
    auditoría encontró ocho veces en la sección «Informe» y que reincidió en `missing_policy`.
    """
    ofensores = [
        f"{ruta}: {nodo[campo]}"
        for ruta, nodo in _campos_visibles()
        if isinstance(nodo.get(campo), str) and _LITERALES_PYTHON.search(nodo[campo])
    ]
    assert ofensores == [], "\n".join(ofensores)


def test_el_gate_caza_lo_que_promete() -> None:
    """La regla, aplicada al texto exacto que se corrigió en el ensayo D3.

    Un gate cuyo detector no se prueba puede estar midiendo la nada (ver
    `test_el_barrido_ve_el_formulario_completo`): aquí se ancla el detector a los textos reales.
    """
    assert _LITERALES_PYTHON.search("Si True, una selección vacía aborta.")
    assert _LITERALES_PYTHON.search("Número mínimo de bins finales; None deja la decisión.")
    assert _LITERALES_PYTHON.search("Si False, un nulo viola la validación.")
    # Y no acusa a lo que sólo se le parece: «Ninguno» en español, o `none` como literal de opción.
    assert not _LITERALES_PYTHON.search("Ninguno de los bins queda vacío.")
    assert not _LITERALES_PYTHON.search("Pon el eje temporal en none.")


# --------------------------------------------------------------------------------------------
# Y los CÓDIGOS INTERNOS, que son vocabulario del motor y no del formulario
# --------------------------------------------------------------------------------------------


def test_ningun_campo_visible_publica_una_marca_de_aviso_declarado() -> None:
    """`FALTA-DATO-VAL-2` no es una frase: es un identificador para el anexo de auditoría.

    El contrato del repo lo dice desde AGENTS.md —«los códigos internos no van al copy público»— y
    la superficie donde más fácil se cuela es ésta: el tooltip de un campo cuyo interruptor
    enciende justo la prueba que declara la brecha. Al poner `validation` en pantalla (D-SC-7) el
    copy aprobado dice «está declarado como brecha del motor: el resultado sale con ese aviso»,
    que es la misma información en idioma de negocio; el código lo lleva el anexo, con su marca.

    ⚠️ El detector se deriva de :mod:`nikodym.core.markers`, que es la fuente de las dos marcas:
    escribir la lista al lado la dejaría stale el día que nazca una tercera.
    """
    marcas = re.compile("|".join(re.escape(m) for m in DECLARED_MARKERS))
    ofensores = [
        f"{ruta}.{campo}: {nodo[campo]}"
        for ruta, nodo in _campos_visibles()
        for campo in ("title", "description", "ui_help")
        if isinstance(nodo.get(campo), str) and marcas.search(nodo[campo])
    ]
    assert ofensores == [], (
        "hay copy del formulario que publica una marca interna:\n"
        + "\n".join(ofensores)
        + "\n\nNo se arregla borrando la advertencia: se dice en idioma de negocio («declarado "
        "como brecha del motor») y el código se queda en el anexo, que es donde se audita."
    )


def test_el_gate_de_marcas_caza_lo_que_promete() -> None:
    """Ancla del detector contra los códigos reales que la sección `validation` puede emitir."""
    marcas = re.compile("|".join(re.escape(m) for m in DECLARED_MARKERS))
    assert marcas.search("Activa el contraste (FALTA-DATO-VAL-2) por grado.")
    assert marcas.search("DATO-INSTITUCIONAL-VAL-4: families incluye 'backtesting'.")
    assert marcas.search("Deja el aviso FALTA-DATO registrado.")
    # Y no acusa a la frase aprobada, que dice lo mismo sin el código.
    assert not marcas.search(
        "Los cortes del semáforo están declarados como brecha del motor: el resultado sale con "
        "ese aviso."
    )


#: Pares de delimitadores que, desbalanceados, delatan una frase editada a medias.
_PARES_DELIMITADORES: tuple[tuple[str, str], ...] = (("{", "}"), ("(", ")"), ("[", "]"))


def _desbalance(texto: str) -> list[str]:
    """Pares cuyos delimitadores no cuadran en el texto, con su conteo."""
    return [
        f"{abre}{cierra}: {texto.count(abre)} abre / {texto.count(cierra)} cierra"
        for abre, cierra in _PARES_DELIMITADORES
        if texto.count(abre) != texto.count(cierra)
    ]


@pytest.mark.parametrize("campo", ["title", "description", "ui_help"])
def test_ningun_campo_visible_tiene_delimitadores_sueltos(campo: str) -> None:
    """D-ANC-9: una llave huérfana delata una frase editada a medias, y se lee en la pantalla.

    El caso que lo motivó: la ayuda de `calibration.target_pd` decía «Con las fuentes
    'historical_default_rate', 'external_regulatory'} es OBLIGATORIA» — con una `}` sin abrir **y**
    omitiendo `business_input`, una de las tres fuentes que sí la exigen. La enumeración se había
    recortado sin cerrar la frase, y el `}` sobreviviente era la única huella.

    Importa porque **`fieldPlaceholder` cae en la `description`**: ese texto se lee **sin hover**,
    dentro del input. Y se cierra la CLASE y no el caso: medido sobre el formulario completo, hoy
    había exactamente **un** ofensor, así que el gate no arrastra falsos positivos.
    """
    ofensores = [
        f"{ruta} [{campo}] — {'; '.join(_desbalance(nodo[campo]))}\n    {nodo[campo]!r}"
        for ruta, nodo in _campos_visibles()
        if isinstance(nodo.get(campo), str) and _desbalance(nodo[campo])
    ]
    assert ofensores == [], "\n".join(ofensores)


def test_el_gate_de_delimitadores_caza_lo_que_promete() -> None:
    """El detector, anclado al texto real que se corrigió — y a lo que NO debe acusar.

    Sin esto el gate podría estar midiendo la nada: «cero ofensores» y «no recorrí nada» se leen
    igual. El oráculo se escribe **a mano**, no se deriva de lo que el gate vigila.
    """
    roto = (
        "Con las fuentes 'historical_default_rate', 'external_regulatory'} es OBLIGATORIA "
        "y explícita."
    )
    assert _desbalance(roto), "la llave huérfana del caso real tiene que salir acusada"
    assert _desbalance("Un paréntesis (que no cierra")
    assert _desbalance("Una lista [a, b")

    # Y no acusa a la puntuación legítima, que es mayoría en este formulario.
    assert not _desbalance("La tasa central (TTC) se estima de Desarrollo.")
    assert not _desbalance("Columnas [a, b] y su rango (0, 1).")
    assert not _desbalance("Sin ningún delimitador.")


# --------------------------------------------------------------------------------------------
# Y la LONGITUD, porque una `description` no es sólo el tooltip: es el placeholder del input.
# --------------------------------------------------------------------------------------------

#: Tope de la `description` de un campo que se pinta como placeholder.
#:
#: 🔴 No es una preferencia de estilo: `fieldPlaceholder` (`form-engine.ts:348`) devuelve la
#: `description` cuando el campo no declara `examples`, y el front la pasa como `placeholder` de los
#: inputs de número y de texto libre. Un párrafo de 551 caracteres **dentro de un input** no se lee:
#: se ve como un borrón que tapa el control.
#:
#: ⚠️ Y el tope no obliga a perder información, que era el riesgo de acortar: el detalle baja a
#: `ui_help`, que es el tooltip ⓘ y admite el texto largo (`fieldHelp` lo prefiere sobre la
#: `description`). Medido al cerrarlo: 16 campos pasaban de 160 caracteres, el peor con 551, y
#: **ninguno era de las descripciones nuevas de LGD** —la deuda del HANDOFF lo atribuía a eso y la
#: medición lo refutó: la mediana de los 354 placeholders es 67 y los peores eran preexistentes.
_TOPE_PLACEHOLDER = 160

#: Los tipos cuyo control recibe el placeholder. Un `enum` se pinta como selector y un `const` es el
#: tag de una unión discriminada: ninguno de los dos muestra placeholder, así que su `description`
#: sólo viaja al tooltip y el tope no le aplica.
_TIPOS_CON_PLACEHOLDER = frozenset({"number", "integer", "string"})

#: Widgets de texto que NO pintan placeholder. `TextareaField` (`FieldRenderer.tsx`) no pasa
#: `placeholder` a su `<textarea>`, así que la `description` de un campo `textarea` sólo se lee en
#: el tooltip ⓘ y el tope no le aplica. Medido el 2026-09-07 al poner `governance.purpose` en
#: pantalla (D-GOB-12/13): su copy aprobado tiene 162 caracteres y el control no lo pinta dentro.
#: El gate de abajo ancla esa premisa al fuente del front: si el textarea gana placeholder, vuelve.
_WIDGETS_SIN_PLACEHOLDER = frozenset({"textarea", "text_area"})


def _recibe_placeholder(nodo: dict[str, Any]) -> bool:
    return (
        nodo.get("type") in _TIPOS_CON_PLACEHOLDER
        and not nodo.get("enum")
        and "const" not in nodo
        and nodo.get("ui_widget") not in _WIDGETS_SIN_PLACEHOLDER
    )


def test_ninguna_description_que_se_pinta_como_placeholder_es_un_parrafo() -> None:
    """Cierra la clase: el texto que se lee DENTRO del input tiene que caber en el input."""
    ofensores = [
        f"{ruta} — {len(nodo['description'])} caracteres: {nodo['description'][:60]!r}…"
        for ruta, nodo in _campos_visibles()
        if isinstance(nodo.get("description"), str)
        and _recibe_placeholder(nodo)
        and len(nodo["description"]) > _TOPE_PLACEHOLDER
    ]
    assert ofensores == [], (
        "hay descriptions que se pintan dentro del input y no caben:\n"
        + "\n".join(ofensores)
        + f"\n\nEl tope son {_TOPE_PLACEHOLDER} caracteres. NO se resuelve borrando información: "
        "el detalle baja a `ui_help`, que es el tooltip y no tiene tope."
    )


def test_el_gate_del_placeholder_no_es_vacuo() -> None:
    """Anclas: si el barrido no viera campos con placeholder, el de arriba pasaría midiendo nada.

    Y un control positivo del criterio: los campos que NO reciben placeholder —selectores y tags de
    unión— tienen que quedar fuera, o el gate acusaría descripciones que sólo se leen en el tooltip.
    """
    campos = _campos_visibles()
    con_placeholder = [
        ruta
        for ruta, nodo in campos
        if isinstance(nodo.get("description"), str) and _recibe_placeholder(nodo)
    ]
    assert len(con_placeholder) > 220, f"sólo {len(con_placeholder)} campos reciben placeholder"
    # Un campo concreto de cada tipo, para que el filtro no pueda degenerar a «ninguno».
    assert "report.document.model_name" in con_placeholder  # texto libre
    assert any(r.endswith("max_n_bins") for r in con_placeholder)  # número
    # 🔴 Y un campo que sólo existe en una rama NO PRIMERA de una unión discriminada: es lo que
    # el barrido no veía, y ahí vivía uno de los 16 que se acortaron al cerrar esta deuda.
    assert "provisioning_internal.lgd.recovery_col" in con_placeholder

    # Un textarea tampoco entra: su control no pinta placeholder (ver `_WIDGETS_SIN_PLACEHOLDER`).
    assert "governance.purpose" not in con_placeholder
    assert any(nodo.get("ui_widget") == "textarea" for _, nodo in campos), (
        "el formulario tiene un textarea: si no se ve, el filtro no se está probando"
    )

    # Control positivo del criterio: un selector NO entra, aunque su description sea larga.
    selectores = [
        ruta
        for ruta, nodo in campos
        if nodo.get("enum") and isinstance(nodo.get("description"), str)
    ]
    assert selectores, "el formulario tiene selectores: si no se ven, el filtro está mal"
    assert not set(selectores) & set(con_placeholder), (
        "un campo con `enum` se pinta como selector y no muestra placeholder: no puede estar en "
        "los dos conjuntos"
    )


def test_el_textarea_del_front_sigue_sin_pintar_placeholder() -> None:
    """Ancla de `_WIDGETS_SIN_PLACEHOLDER` al fuente que la sostiene.

    La exención del textarea no es una preferencia: es que `TextareaField` no pasa `placeholder`
    a su control, así que la `description` sólo se lee en el tooltip. Si algún día lo pasa, este
    gate se pone rojo y el tope vuelve a aplicar —y `governance.purpose` (162 caracteres, copy
    aprobado que no se reescribe aquí) tendría que bajar su detalle a `ui_help`—.
    """
    from pathlib import Path

    fuente = (
        Path(__file__).resolve().parents[2] / "web" / "src" / "components" / "FieldRenderer.tsx"
    )
    cuerpo = fuente.read_text(encoding="utf-8")
    inicio = cuerpo.index("function TextareaField(")
    textarea = cuerpo[inicio : cuerpo.index("\n}", inicio)]
    assert "<textarea" in textarea, "TextareaField ya no pinta un <textarea>: revisar la premisa"
    assert "placeholder" not in textarea, (
        "`TextareaField` pasa `placeholder`: la description de un textarea vuelve a leerse dentro "
        "del control y el tope de `_TOPE_PLACEHOLDER` tiene que aplicarle"
    )
    # Y el control positivo de la premisa contraria: los inputs de texto y número SÍ lo pasan.
    assert cuerpo.count("placeholder={fieldPlaceholder(") >= 2
