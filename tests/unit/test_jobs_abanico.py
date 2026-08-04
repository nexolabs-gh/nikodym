"""El abanico metodológico: qué se puede elegir, y qué cuesta cada opción (D-ABA-1…D-ABA-12).

El catálogo se declara **a mano** —del schema no sale ni el idioma de negocio ni qué exige cada
opción, que es el 100 % de lo que D-JOB-4/5 piden— y el riesgo de eso, desincronizarse en silencio,
lo cierra este archivo. Es el mismo trato que D-COL-6 hizo con las formas de respuesta.

**La bidireccionalidad tiene dos caras, y hacen falta las dos:**

1. *Por path*: las opciones declaradas para un punto de elección son **exactamente** los literales
   que el motor acepta en ese campo. Una opción nueva en el motor sin su entrada ⇒ rojo; una
   entrada sin opción detrás ⇒ rojo, porque escribiría un config que el motor rechaza.
2. *Por cobertura*: todo campo del catálogo que ofrezca más de una opción tiene su entrada, salvo
   los exentos con razón escrita. Sin esta cara, el catálogo podría quedarse a medias y ningún gate
   lo notaría — que es exactamente lo que pasó con las 17 exenciones «fuera del alcance F1» del
   preflight, ciertas cuando se escribieron y falsas un mes después.

⚠️ **El oráculo se deriva del motor, nunca del propio catálogo.** Un gate que construyera su
esperado leyendo `_ABANICO_POR_SECCION` sólo mediría que el diccionario es igual a sí mismo.
"""

from __future__ import annotations

import re
import types
from typing import Any, Literal, Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.ui import jobs

# --------------------------------------------------------------------------------------------
# Oráculo: lo que el MOTOR declara, leído de `model_fields`
# --------------------------------------------------------------------------------------------


def _literales(anotacion: Any) -> list[str]:
    """Los valores de un ``Literal``, mirando dentro de ``X | None`` y de ``tuple[Literal, ...]``.

    Se lee de la **anotación** y no del JSON Schema, por la misma razón que
    `_ramas_discriminadas` en el gate de las formas de respuesta: la anotación es la fuente que el
    motor obedece al validar, y el schema es una proyección suya.
    """
    if get_origin(anotacion) is Literal:
        return [str(v) for v in get_args(anotacion)]
    if get_origin(anotacion) in (Union, types.UnionType):
        for rama in get_args(anotacion):
            if rama is type(None):
                continue
            if encontrados := _literales(rama):
                return encontrados
    if get_origin(anotacion) in (tuple, list, frozenset, set):
        for rama in get_args(anotacion):
            if rama is Ellipsis:
                continue
            if encontrados := _literales(rama):
                return encontrados
    return []


def _es_multiple(anotacion: Any) -> bool:
    """Si el campo admite VARIOS valores a la vez y no uno solo."""
    if get_origin(anotacion) in (tuple, list, frozenset, set):
        return True
    if get_origin(anotacion) in (Union, types.UnionType):
        return any(_es_multiple(rama) for rama in get_args(anotacion) if rama is not type(None))
    return False


def _campo_del_path(path: str) -> Any:
    """El ``FieldInfo`` que el motor declara en ese path, bajando por los submodelos."""
    seccion, *resto = path.split(".")
    cls = cargar_configs_de_dominio()[seccion]
    for nombre in resto[:-1]:
        anotacion = cls.model_fields[nombre].annotation
        candidatas = [anotacion, *get_args(anotacion)]
        siguiente = next(
            (c for c in candidatas if isinstance(c, type) and issubclass(c, BaseModel)), None
        )
        assert siguiente is not None, f"{path}: {nombre} no baja a un submodelo"
        cls = siguiente
    return cls.model_fields[resto[-1]]


def _puntos_del_motor() -> dict[str, list[str]]:
    """Todo campo de una sección del CATÁLOGO que ofrezca más de una opción.

    Recorre los submodelos anidados igual que el preflight, y **no** conoce el catálogo del abanico:
    es el oráculo independiente de la segunda cara de la bidireccionalidad.
    """
    clases = cargar_configs_de_dominio()
    encontrados: dict[str, list[str]] = {}

    def recorre(cls: type[BaseModel], prefijo: str, profundidad: int = 0) -> None:
        if profundidad > 4:
            return
        for nombre, info in cls.model_fields.items():
            ruta = f"{prefijo}{info.alias or nombre}"
            valores = _literales(info.annotation)
            if len(valores) > 1:
                encontrados[ruta] = valores
            for candidata in (info.annotation, *get_args(info.annotation)):
                if (
                    isinstance(candidata, type)
                    and issubclass(candidata, BaseModel)
                    and candidata is not cls
                ):
                    recorre(candidata, f"{ruta}.", profundidad + 1)

    for seccion in _SECCIONES_DEL_CATALOGO:
        if seccion in clases:
            recorre(clases[seccion], f"{seccion}.")
    return encontrados


_SECCIONES_DEL_CATALOGO: frozenset[str] = frozenset(
    seccion for trabajo in jobs.list_jobs() for seccion in trabajo["sections"]
)

#: Campos con más de una opción que **no** son un punto de elección metodológica, con su razón.
#:
#: Mismo patrón que las exenciones del preflight, y por la misma razón: una lista corta sin
#: explicación se lee como cobertura total. El gate exige además que ninguna exención sobre.
_EXENTOS: dict[str, str] = {
    "data.schema.columns.dtype": (
        "declara de qué tipo es una columna DEL ARCHIVO del usuario, no cómo se calcula nada"
    ),
    "data.schema.strict": (
        "política de validación del esquema del archivo; no elige método sino severidad de lectura"
    ),
    **{
        f"data.target.{regla}.{lista}.op": (
            "es la gramática de un predicado, no un método: la regla que lo contiene YA tiene su "
            "propia superficie como decisión obligatoria con formas de respuesta (D-COL-6)"
        )
        for regla in ("bad_rule", "good_rule", "indeterminate_rule", "exclusion_rules.rule")
        for lista in ("all_of", "any_of")
    },
}


def _abanico() -> dict[str, dict[str, Any]]:
    """El catálogo declarado, indexado por path."""
    return {
        eleccion["path"]: eleccion
        for elecciones in jobs._ABANICO_POR_SECCION.values()
        for eleccion in elecciones
    }


# --------------------------------------------------------------------------------------------
# Cara 1 — las opciones de un punto son las del motor, en las dos direcciones
# --------------------------------------------------------------------------------------------


def test_las_opciones_declaradas_son_exactamente_las_del_motor() -> None:
    """Una opción que el motor no acepta escribiría un config que rechaza al validar."""
    for path, eleccion in _abanico().items():
        del_motor = set(_literales(_campo_del_path(path).annotation))
        del_catalogo = {opcion["value"] for opcion in eleccion["options"]}

        assert del_motor, f"{path}: el motor no declara opciones ahí; ¿cambió el campo?"
        assert del_catalogo == del_motor, (
            f"{path}: el catálogo ofrece {sorted(del_catalogo)} y el motor acepta "
            f"{sorted(del_motor)}. Una opción nueva del motor necesita su entrada; una entrada sin "
            "opción detrás escribe un config que el motor rechaza."
        )


def test_todo_punto_de_eleccion_del_catalogo_esta_declarado_o_exento() -> None:
    """La segunda cara: el catálogo no puede quedarse a medias en silencio."""
    declarados = set(_abanico())
    sin_declarar = sorted(set(_puntos_del_motor()) - declarados - set(_EXENTOS))

    assert sin_declarar == [], (
        "estos campos ofrecen más de una opción y el abanico no dice nada de ellos:\n  "
        + "\n  ".join(sin_declarar)
        + "\nDeclara su entrada, o exímelo con su razón en `_EXENTOS`."
    )


def test_ninguna_exencion_sobra() -> None:
    """Una exención sobre un campo que ya se declaró —o que desapareció— es ruido que engaña."""
    del_motor = set(_puntos_del_motor())
    declarados = set(_abanico())

    sobran = sorted(path for path in _EXENTOS if path in declarados or path not in del_motor)
    assert sobran == [], f"exenciones que ya no aplican: {sobran}"


def test_toda_exencion_declara_una_razon_de_verdad() -> None:
    """Una razón vacía o de tres palabras convierte la lista en un vertedero."""
    for path, razon in _EXENTOS.items():
        assert len(razon) > 40, f"{path}: la razón no explica nada"


def test_el_multiple_declarado_coincide_con_el_tipo_del_motor() -> None:
    """Si el motor admite varias y el catálogo dice una, el formulario pinta el control erróneo."""
    for path, eleccion in _abanico().items():
        assert eleccion["multiple"] == _es_multiple(_campo_del_path(path).annotation), (
            f"{path}: `multiple` no coincide con lo que el motor admite"
        )


def test_el_barrido_no_es_vacuo() -> None:
    """Un gate que recorre cero puntos da verde y no prueba nada: pasó ya dos veces en este repo."""
    declarados = _abanico()

    assert len(declarados) >= 69, f"sólo {len(declarados)} puntos de elección declarados"
    for ancla in (
        "provisioning_ifrs9.lgd.method",
        "survival.method",
        "stability.csi_source",
        "calibration.method",
        "provisioning.rule",
    ):
        assert ancla in declarados, f"falta el punto de elección «{ancla}»"


# --------------------------------------------------------------------------------------------
# Cara 2 — el abanico NO es la tarjeta de decisiones obligatorias (D-ABA-3)
# --------------------------------------------------------------------------------------------


def test_todo_punto_del_abanico_tiene_default_en_el_motor() -> None:
    """Es LA diferencia con una decisión obligatoria, y no una convención de estilo.

    Una decisión obligatoria no tiene default y el config **no construye** sin ella; un punto del
    abanico sí lo tiene y el motor corre. Si un punto del abanico no tuviera default, el usuario
    quedaría con un config inejecutable creyendo que eligió algo opcional.
    """
    for path in _abanico():
        assert not _campo_del_path(path).is_required(), (
            f"{path} no tiene default: es una decisión obligatoria y va en la otra tarjeta"
        )


def test_ningun_path_esta_en_las_dos_estructuras() -> None:
    """Preguntar lo mismo dos veces en la misma pantalla es peor que no preguntarlo."""
    de_decisiones = {
        decision["path"]
        for decisiones in jobs._DECISIONES_POR_SECCION.values()
        for decision in decisiones
    }
    repetidos = sorted(de_decisiones & set(_abanico()))

    assert repetidos == [], f"declarados como decisión obligatoria y como abanico: {repetidos}"


# --------------------------------------------------------------------------------------------
# Los tres estados y sus obligaciones (D-ABA-4/5/6)
# --------------------------------------------------------------------------------------------


def _opciones() -> list[tuple[str, dict[str, Any]]]:
    return [(path, o) for path, e in _abanico().items() for o in e["options"]]


def test_el_vocabulario_de_estados_es_cerrado() -> None:
    for path, opcion in _opciones():
        assert opcion["estado"] in jobs._ESTADOS_DE_OPCION, f"{path}/{opcion['value']}"


def test_una_opcion_disponible_no_lleva_motivo_ni_prueba() -> None:
    """Un motivo sobre algo que sí se puede usar sólo confunde."""
    for path, opcion in _opciones():
        if opcion["estado"] == jobs._DISPONIBLE:
            assert opcion["motivo"] is None, f"{path}/{opcion['value']} explica algo que no pasa"
            assert opcion["prueba"] is None, f"{path}/{opcion['value']}"


def test_una_opcion_no_implementada_explica_por_que() -> None:
    for path, opcion in _opciones():
        if opcion["estado"] == jobs._NO_IMPLEMENTADA:
            assert opcion["motivo"] and len(opcion["motivo"]) > 40, (
                f"{path}/{opcion['value']}: se declara no implementada sin decir qué pasa"
            )


def test_una_opcion_no_implementada_tambien_esta_cerrada_en_el_motor() -> None:
    """D-ABA-5: rotularla sólo en el catálogo deja el defecto vivo para quien llega por código.

    Nikodym es una librería antes que una aplicación, y quien la usa por YAML o por Python no ve
    este catálogo. La opción tiene que ser imposible de construir, no sólo estar en gris.
    """
    clases = cargar_configs_de_dominio()
    for path, opcion in _opciones():
        if opcion["estado"] != jobs._NO_IMPLEMENTADA:
            continue
        seccion, *resto = path.split(".")
        base = clases[seccion]().model_dump(mode="json", by_alias=True)
        nodo = base
        for nombre in resto[:-1]:
            nodo = nodo[nombre]
        nodo[resto[-1]] = opcion["value"]

        with pytest.raises(Exception, match=r".") as capturado:
            clases[seccion].model_validate(base)
        assert capturado.value, f"{path}={opcion['value']!r} se construye sin error"


def test_una_opcion_sin_efecto_cita_la_medicion_que_lo_prueba() -> None:
    """D-ABA-6: decir «esto no cambia tu resultado» es una afirmación fuerte sobre el motor.

    Sin la disciplina de la cita, el estado se convierte en un vertedero de dudas.
    """
    cita = re.compile(r"[\w/]+\.py:\d+")
    for path, opcion in _opciones():
        if opcion["estado"] == jobs._SIN_EFECTO:
            assert opcion["prueba"] and cita.search(opcion["prueba"]), (
                f"{path}/{opcion['value']}: se declara sin efecto sin citar dónde se midió"
            )
            assert opcion["motivo"] and len(opcion["motivo"]) > 40, f"{path}/{opcion['value']}"


# --------------------------------------------------------------------------------------------
# Copy: lo que el usuario lee
# --------------------------------------------------------------------------------------------

_JERGA = re.compile(
    r"\b(None|True|False|null|bad_rule|good_rule|target_col|duration_col|event_col|strategy|"
    r"partition|BaseModel|NikodymConfig|config_hash|DataFrame|dataframe)\b"
)


def test_el_copy_del_abanico_no_filtra_jerga_interna() -> None:
    """El `path` es la coordenada interna; lo que se lee es la pregunta (D-ABA-11)."""
    ofensores: list[str] = []
    for path, eleccion in _abanico().items():
        for campo in ("question", "help"):
            if hallado := _JERGA.search(eleccion[campo]):
                ofensores.append(f"{path}.{campo}: «{hallado.group(0)}»")
        for opcion in eleccion["options"]:
            for campo in ("label", "help", "motivo"):
                valor = opcion[campo]
                if isinstance(valor, str) and (hallado := _JERGA.search(valor)):
                    ofensores.append(f"{path}/{opcion['value']}.{campo}: «{hallado.group(0)}»")
    assert ofensores == [], ofensores


def test_el_copy_no_enseña_el_path_ni_el_nombre_del_campo() -> None:
    """«Pon el nombre del campo y se entiende» es la tentación exacta que D-ABA-11 prohíbe."""
    for path, eleccion in _abanico().items():
        hoja = path.rsplit(".", 1)[-1]
        for campo in ("question", "help"):
            assert path not in eleccion[campo], f"{path}: el copy enseña el path"
            assert hoja not in eleccion[campo], f"{path}: el copy enseña el nombre del campo"


def test_cada_punto_se_lee_como_una_pregunta_con_su_ayuda() -> None:
    for path, eleccion in _abanico().items():
        assert set(eleccion) == {"path", "question", "help", "multiple", "options"}, path
        assert eleccion["question"].endswith("?"), f"{path}: la pregunta no pregunta"
        assert len(eleccion["help"]) > 40, f"{path}: la ayuda no ayuda"
        assert len(eleccion["options"]) > 1, f"{path}: un abanico de una sola opción no es abanico"
        for opcion in eleccion["options"]:
            assert opcion["label"], f"{path}/{opcion['value']}: sin etiqueta"
            assert len(opcion["help"]) > 40, f"{path}/{opcion['value']}: la ayuda no ayuda"


def test_las_etiquetas_de_un_punto_no_se_repiten() -> None:
    """Dos opciones con la misma etiqueta son indistinguibles en pantalla."""
    for path, eleccion in _abanico().items():
        etiquetas = [o["label"] for o in eleccion["options"]]
        assert len(set(etiquetas)) == len(etiquetas), f"{path}: etiquetas repetidas"


# --------------------------------------------------------------------------------------------
# Herencia, serialización e identidad
# --------------------------------------------------------------------------------------------


def test_un_trabajo_hereda_exactamente_el_abanico_de_sus_secciones() -> None:
    for trabajo in jobs.list_jobs():
        esperado = [
            eleccion["path"]
            for seccion, elecciones in jobs._ABANICO_POR_SECCION.items()
            if seccion in set(trabajo["sections"])
            for eleccion in elecciones
        ]
        assert [e["path"] for e in trabajo["methodology_choices"]] == esperado, trabajo["id"]


def test_el_abanico_no_depende_del_orden_en_que_se_pidan_las_secciones() -> None:
    secciones = ["stability", "data"]
    assert abanico_paths(secciones) == abanico_paths(list(reversed(secciones)))


def abanico_paths(secciones: list[str]) -> list[str]:
    return [e["path"] for e in jobs.abanico_de(secciones)]


def test_el_catalogo_devuelve_copias_hasta_el_fondo() -> None:
    """Mutar lo que devuelve el catálogo no puede tocar el literal del módulo."""
    primero = jobs.abanico_de(["stability"])
    primero[0]["options"][0]["label"] = "mutado"
    assert jobs.abanico_de(["stability"])[0]["options"][0]["label"] != "mutado"


def test_la_prueba_interna_no_viaja_al_contrato_rest() -> None:
    """`prueba` es evidencia para quien mantiene el catálogo, no algo que el usuario deba leer."""
    for eleccion in jobs.abanico_de(sorted(_SECCIONES_DEL_CATALOGO)):
        for opcion in eleccion["options"]:
            assert "prueba" not in opcion, f"{eleccion['path']}: la cita interna se publicó"


@pytest.mark.parametrize(
    ("serializador", "entrada", "esperadas"),
    [
        (jobs._eleccion_json, {"path": "x"}, jobs._CLAVES_DE_ELECCION),
        (jobs._opcion_json, {"value": "x"}, jobs._CLAVES_DE_OPCION),
    ],
)
def test_una_clave_nueva_rompe_en_vez_de_perderse(
    serializador: Any, entrada: dict[str, Any], esperadas: frozenset[str]
) -> None:
    """Escribir campo a campo evita que una clave nueva se cuele; sólo el guardián la delata."""
    del esperadas
    with pytest.raises(ValueError, match="no cuadra con lo que se publica"):
        serializador(entrada)


# --------------------------------------------------------------------------------------------
# Identidad — D-ABA-12
# --------------------------------------------------------------------------------------------

#: `config_hash` de los tres presets, medido sobre el árbol ANTERIOR a que existiera el abanico.
#:
#: Escritos a mano y a propósito: derivarlos del árbol actual haría el gate autorreferencial —sólo
#: mediría que la función es determinista, que es el defecto de paridad que este repo ya pagó—. El
#: oráculo es el pasado, y por eso se anclan.
_HASHES_ANTES_DEL_ABANICO: dict[str, str] = {
    "f1-estandar-consumo": "ec10eb43314cad2e369584c7dabe4bbf2456391e255a2b69218d405bba2a448e",
    "f3-provisiones-consumo": "857b06eef5aff267c36076641ffbdbf2fb17836511c206ea04fc5c160983886d",
    "f4-ifrs9-retail": "013e69dc4c96e03ee87e9f3f54bcf5e1f6e6fd56b5a1b1ffdd5bf021093360b6",
}


def test_el_abanico_no_mueve_un_solo_config_hash() -> None:
    """Declara opciones que YA existen: no añade un campo, así que la identidad no se mueve.

    Importa más de lo que parece. De ese digest cuelgan el lineage, la ficha del modelo, el informe
    y el ancla de idempotencia del inventario, así que moverlo sin decirlo rompe la comparabilidad
    entre corridas de dos versiones. Y elegir una opción del abanico tiene que producir exactamente
    el mismo config que escribirla a mano en el formulario (D-JOB-9): dos usuarios que llegan al
    mismo config por caminos distintos producen la misma identidad.

    Control negativo natural: convertir cualquier opción del abanico en un campo de config —que es
    la forma más fácil de equivocarse aquí— movería estos tres.
    """
    from nikodym.core.config.hashing import config_hash
    from nikodym.core.config.schema import NikodymConfig
    from nikodym.ui import presets

    for preset_id, esperado in _HASHES_ANTES_DEL_ABANICO.items():
        config = NikodymConfig.model_validate(presets.get_preset(preset_id)["config"])
        assert config_hash(config) == esperado, (
            f"{preset_id} cambió de identidad. El abanico declara opciones que YA existen: si "
            "movió un hash, alguna de sus entradas se convirtió en un campo del config."
        )
