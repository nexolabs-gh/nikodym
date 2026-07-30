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

from nikodym.ui.routes import schema_payload

#: Las secciones que el formulario expande hoy. Espejo de `CONFIG_SECTIONS`
#: (`web/src/lib/schema.ts`); el gate de deriva de ese catálogo vive en `test_column_roles.py`.
SECCIONES_DEL_FORMULARIO = (
    "data",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    "survival",
    "provisioning_cmf",
    "provisioning_internal",
    "provisioning_ifrs9",
    "provisioning",
    "report",
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

    campos: list[tuple[str, dict[str, Any]]] = []

    def recorrer(nodo: Any, ruta: str, visto: tuple[str, ...] = ()) -> None:
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
