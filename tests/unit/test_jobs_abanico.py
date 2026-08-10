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


def _submodelos(anotacion: Any) -> list[type[BaseModel]]:
    """Todos los submodelos que un campo puede tomar, no sólo el primero.

    🔴 La versión anterior se quedaba con **la primera** rama (`next(...)`), y eso la volvía ciega
    a cualquier punto de elección con forma de unión discriminada: el oráculo veía un único
    `Literal` de un solo valor donde el motor acepta varios, así que el gate ponía en rojo un
    catálogo correcto — y, peor, `_puntos_del_motor` dejaba de ver el path entero, porque exige
    `len(valores) > 1`. Un oráculo que sólo mira una rama no mide el motor: mide una de sus formas.
    """
    return [
        c
        for c in (anotacion, *get_args(anotacion))
        if isinstance(c, type) and issubclass(c, BaseModel)
    ]


def _campos_del_path(path: str) -> list[Any]:
    """Los ``FieldInfo`` que el motor declara en ese path: uno por rama cuando hay unión."""
    seccion, *resto = path.split(".")
    clases: list[type[BaseModel]] = [cargar_configs_de_dominio()[seccion]]
    for nombre in resto[:-1]:
        siguientes: list[type[BaseModel]] = []
        for cls in clases:
            siguientes.extend(_submodelos(cls.model_fields[nombre].annotation))
        assert siguientes, f"{path}: {nombre} no baja a un submodelo"
        clases = siguientes
    campos = [cls.model_fields[resto[-1]] for cls in clases if resto[-1] in cls.model_fields]
    assert campos, f"{path}: ninguna rama declara {resto[-1]!r}"
    return campos


def _campo_del_path(path: str) -> Any:
    """El ``FieldInfo`` de la primera rama; sirve para leer forma (``_es_multiple``), no dominio."""
    return _campos_del_path(path)[0]


def _valores_del_motor(path: str) -> set[str]:
    """Todos los valores que el motor acepta en ese path, UNIENDO las ramas de una unión.

    Con `provisioning_internal.lgd.method` la unión tiene una rama por método y cada una declara un
    `Literal` de UN valor: el dominio real es la unión de todos, que es exactamente lo que el
    usuario puede elegir y lo que el catálogo debe ofrecer.
    """
    return {valor for campo in _campos_del_path(path) for valor in _literales(campo.annotation)}


def _puntos_del_motor() -> dict[str, list[str]]:
    """Todo campo de una sección del CATÁLOGO que ofrezca más de una opción.

    Recorre los submodelos anidados igual que el preflight, y **no** conoce el catálogo del abanico:
    es el oráculo independiente de la segunda cara de la bidireccionalidad.
    """
    clases = cargar_configs_de_dominio()
    encontrados: dict[str, list[str]] = {}

    def recorre(grupo: list[type[BaseModel]], prefijo: str, profundidad: int = 0) -> None:
        # 🔴 Recorre un GRUPO de clases y no una sola: cuando un campo es una unión discriminada,
        # cada rama declara su `method` como un `Literal` de UN valor, y mirándolas por separado el
        # dominio real —la unión— no aparece nunca. El path se perdía entero de este oráculo,
        # justo el que existe para que el catálogo no pueda quedarse a medias en silencio.
        if profundidad > 4:
            return
        nombres = {nombre for cls in grupo for nombre in cls.model_fields}
        for nombre in nombres:
            infos = [cls.model_fields[nombre] for cls in grupo if nombre in cls.model_fields]
            ruta = f"{prefijo}{infos[0].alias or nombre}"
            valores = sorted({v for info in infos for v in _literales(info.annotation)})
            if len(valores) > 1:
                encontrados[ruta] = valores
            hijas = [
                candidata
                for info in infos
                for candidata in _submodelos(info.annotation)
                if candidata not in grupo
            ]
            if hijas:
                recorre(hijas, f"{ruta}.", profundidad + 1)

    for seccion in _SECCIONES_DEL_CATALOGO:
        if seccion in clases:
            recorre([clases[seccion]], f"{seccion}.")
    return encontrados


_SECCIONES_DEL_CATALOGO: frozenset[str] = frozenset(
    seccion for trabajo in jobs.list_jobs() for seccion in trabajo["sections"]
)

#: Campos con más de una opción que **no** son un punto de elección metodológica, con su razón.
#:
#: Mismo patrón que las exenciones del preflight, y por la misma razón: una lista corta sin
#: explicación se lee como cobertura total. El gate exige además que ninguna exención sobre.
_EXENTOS: dict[str, str] = {
    "data.partition.strategy.type": (
        "no es abanico sino DECISIÓN OBLIGATORIA, y la separación es deliberada (D-ABA-3): no "
        "tiene default, el config no construye sin ella, y ya tiene su superficie propia con "
        "formas de respuesta en `_DECISIONES_POR_SECCION`. Duplicarla aquí llenaría la tarjeta "
        "de decisiones de cosas que el motor sí sabe rellenar, y si todo es una decisión "
        "ninguna lo es. ⚠️ Apareció al enseñarle uniones a este oráculo (D-LGD-1-bis): antes "
        "era invisible por construcción, no por criterio"
    ),
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
        del_motor = _valores_del_motor(path)
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


def test_cada_opcion_soportada_declara_dispatcher_y_effect_oracle_ejecutables() -> None:
    """D-RDY-ABA-2/3: disponible/condicionada enlaza dos oráculos internos, nunca REST."""
    for path, opcion in _opciones():
        supported = opcion["estado"] in {jobs._DISPONIBLE, jobs._EXIGE_OTRO_CAMPO}
        dispatcher = opcion["dispatcher_oracle"]
        effect = opcion["effect_oracle"]
        if not supported:
            assert dispatcher is None and effect is None, f"{path}/{opcion['value']}"
            continue
        pair = f"{path}={opcion['value']}"
        assert dispatcher == f"option-dispatch:{pair}", (
            f"{path}/{opcion['value']}: dispatcher sin registry"
        )
        assert effect == f"option-effect:{pair}", (
            f"{path}/{opcion['value']}: effect_oracle sin registry"
        )


def test_los_oraculos_internos_no_viajan_por_rest() -> None:
    """La metadata de gates no amplía el contrato ni el copy de la UI."""
    for choice in jobs.abanico_de(jobs._ABANICO_POR_SECCION):
        for option in choice["options"]:
            assert "dispatcher_oracle" not in option
            assert "effect_oracle" not in option


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


def test_sin_efecto_desaparece_del_contrato_seleccionable() -> None:
    """D-RDY-ABA-1: ninguna opción puede volver al estado retirado ``sin_efecto``."""
    assert all(opcion["estado"] != "sin_efecto" for _, opcion in _opciones())


# ------------------------------------------------------------------------------------------
# D-EXI-2/3: la opción que exige otro campo, y el oráculo que la descubre
# ------------------------------------------------------------------------------------------


def test_una_opcion_que_exige_otro_campo_declara_cual_y_por_que() -> None:
    """La bicondicional que sostiene que ``exige`` sea una clave OPCIONAL.

    ``_CLAVES_DE_OPCION`` no la incluye —obligar a las 207 opciones a declarar ``exige: ()``
    sería ruido que esconde la señal— y el precio de eso es que podría faltar sin que nadie lo
    note. Este test es ese precio pagado: se exige en los **dos** sentidos.
    """
    cita = re.compile(r"[\w/]+\.py:\d+")
    con_exige = 0
    for path, opcion in _opciones():
        exige = opcion.get("exige", ())
        if opcion["estado"] == jobs._EXIGE_OTRO_CAMPO:
            con_exige += 1
            assert exige, (
                f"{path}/{opcion['value']}: se declara «exige otro campo» y no dice cuál. Sin "
                "la ruta el front no puede llevar al usuario al control, y el estado es un adorno."
            )
            assert opcion["motivo"] and len(opcion["motivo"]) > 40, (
                f"{path}/{opcion['value']}: no explica en idioma de negocio qué falta"
            )
            assert opcion["prueba"] and cita.search(opcion["prueba"]), (
                f"{path}/{opcion['value']}: se declara sin citar el validador que lo impone. "
                "Misma disciplina que `sin_efecto` (D-ABA-6): afirma algo sobre el motor."
            )
        else:
            # El otro sentido: `exige` sólo tiene sentido en ese estado. Declararlo en otro sería
            # prometer un hueco que el motor no pide.
            assert not exige, (
                f"{path}/{opcion['value']} declara `exige` en estado {opcion['estado']!r}: o el "
                "estado está mal, o el campo no hace falta."
            )
    assert con_exige >= 3, (
        f"sólo {con_exige} opciones usan `exige_otro_campo`; si baja de 3, o se corrigió el "
        "motor o alguien reetiquetó las ramas modeladas de LGD"
    )


def test_lo_que_exige_una_opcion_es_un_campo_que_el_motor_tiene() -> None:
    """La ruta declarada no puede apuntar al vacío: se resuelve contra ``model_fields``.

    ⚠️ Se resuelve por el mismo camino que el resto de este gate (``_campo_del_path``), que ya
    sabe bajar por submodelos y por las ramas de una unión discriminada. Una ruta escrita a mano
    que ya no exista dejaría el estado en pie apuntando a un control que no está.
    """
    for path, opcion in _opciones():
        for exigido in opcion.get("exige", ()):
            campo = _campo_del_path(exigido)
            assert campo is not None, (
                f"{path}/{opcion['value']} exige {exigido!r}, que el motor no declara como campo"
            )


def test_un_punto_que_no_aplica_siempre_declara_su_condicion() -> None:
    """D-EXI-6: un punto de elección inerte se FILTRA, y su condición viaja como dato.

    🔴 El defecto: con ``provisioning_internal.method='direct_loss_rate'`` la subsección ``lgd``
    entera es inerte —``columnas_inactivas`` lo declara (D-SUB-2) y el motor no abre una sola
    columna suya— y el formulario seguía ofreciendo el punto de la severidad. Elegir ahí una rama
    modelada **rechazaba el config completo**, y el propio ``help`` prometía lo contrario.

    ⚠️ Se cierra en la SUPERFICIE y no relajando el validador: mover la regla al padre obligaría
    a que ``InternalLgdWorkout()`` dejara de fallar —dos clases públicas— y contradiría D-LGD, que
    decidió que en una unión **la rama ES el método** y por eso la regla es incondicional. Medido al
    implementarlo; no estaba en la enmienda.
    """
    condicion = None
    for path, eleccion in _abanico().items():
        cuando = eleccion.get("when")
        if cuando is None:
            continue
        assert set(cuando) == {"path", "equals"}, (
            f"{path}: la condición no tiene la forma del `when` de `external_artifacts`, que es el "
            "precedente vivo. Un segundo lenguaje de condiciones en el front es lo que se evita."
        )
        # La ruta de la condición tiene que existir en el motor, o el punto se ocultaría siempre.
        assert _valores_del_motor(cuando["path"]), f"{path}: `when.path` no ofrece valores"
        assert cuando["equals"] in _valores_del_motor(cuando["path"]), (
            f"{path}: `when.equals={cuando['equals']!r}` no es un valor que el motor acepte en "
            f"{cuando['path']!r}, así que este punto no se mostraría nunca"
        )
        if path == "provisioning_internal.lgd.method":
            condicion = cuando

    assert condicion == {"path": "provisioning_internal.method", "equals": "pd_lgd"}, (
        "el punto de la severidad dejó de declarar su condición: volvería a ofrecerse con la "
        "subsección inerte, que es el defecto que D-EXI-6 cierra"
    )


def test_el_help_de_la_severidad_no_promete_que_da_igual() -> None:
    """La frase que el defecto hacía falsa, atada a que no vuelva.

    Decía que con la tasa de pérdida directa «esta elección no cambia el resultado». Era falso en el
    peor sentido: no es que dé igual, es que **rechaza el config entero**. Ahora el punto no se
    ofrece en ese caso, así que la frase no sólo era falsa: sobraba.
    """
    eleccion = _abanico()["provisioning_internal.lgd.method"]
    assert "no cambia el resultado" not in eleccion["help"]
    assert "Sólo se aplica si" not in eleccion["help"]


def _ramas_de_union(anotacion: Any) -> list[type[BaseModel]]:
    if isinstance(anotacion, types.UnionType) or get_origin(anotacion) is Union:
        return [a for a in get_args(anotacion) if isinstance(a, type) and issubclass(a, BaseModel)]
    return []


def _discriminador(info: Any) -> str | None:
    """El discriminador de una unión viaja en los METADATOS del campo, no en la anotación.

    ⚠️ Pydantic **desenvuelve el ``Annotated``**: ``model_fields[x].annotation`` de una unión
    discriminada es ya la unión desnuda y el ``Field(discriminator=...)`` va aparte. Buscarlo en
    la anotación devuelve el conjunto vacío — trampa ya pagada en este repo.
    """
    for meta in getattr(info, "metadata", None) or []:
        if getattr(meta, "discriminator", None):
            return str(meta.discriminator)
    disc = getattr(info, "discriminator", None)
    return str(disc) if disc else None


def _ramas_que_no_construyen() -> list[tuple[str, str]]:
    """``(path del campo, rama)`` de toda rama que el usuario no puede elegir sola.

    🔴 El criterio es más fino que «la rama no construye», y la diferencia está medida: ese
    criterio a secas acusa **9** ramas y **6 son inocentes**. Lo que separa a las culpables es si
    alguien le pregunta al usuario por lo que falta:

    · ``data.partition.strategy`` es una unión discriminada cuyo campo es ``is_required()`` ⇒
      **D-OBL la declara** y el trabajo la pregunta en idioma de negocio, con sus huecos a la
      vista. Sus tres ramas no construyen con defaults y eso está bien: ya se le interroga.
    · ``good_rule``/``indeterminate_rule``/``window`` son ``X | None``, o sea submodelos
      **opcionales** y no uniones de método: activarlos abre sus campos en el formulario.
    · ``provisioning_internal.lgd`` es unión discriminada con ``default_factory`` ⇒ el campo
      **no** es requerido, así que D-OBL **no puede** declararla —su gate lo prohíbe, control
      negativo ejecutado: 3 tests rojos— y nadie pregunta nada. Ése es el hueco.

    De ahí el criterio: unión **discriminada** + campo **no requerido** + rama que no construye.
    """
    clases = cargar_configs_de_dominio()
    culpables: list[tuple[str, str]] = []
    for seccion, cls in sorted(clases.items()):
        pila: list[tuple[str, type[BaseModel]]] = [(seccion, cls)]
        vistos: set[type[BaseModel]] = set()
        while pila:
            prefijo, modelo = pila.pop()
            if modelo in vistos:
                continue
            vistos.add(modelo)
            for campo, info in modelo.model_fields.items():
                ramas = _ramas_de_union(info.annotation)
                sospechoso = bool(_discriminador(info)) and not info.is_required()
                for rama in ramas:
                    if sospechoso:
                        try:
                            rama.model_validate({})
                        except Exception:
                            culpables.append((f"{prefijo}.{campo}", rama.__name__))
                    pila.append((f"{prefijo}.{campo}", rama))
                anotacion = info.annotation
                if isinstance(anotacion, type) and issubclass(anotacion, BaseModel):
                    pila.append((f"{prefijo}.{campo}", anotacion))
    return culpables


def test_el_oraculo_de_las_ramas_no_es_vacuo() -> None:
    """Ancla: si el barrido dejara de encontrar ramas, el test de abajo pasaría sin medir nada."""
    culpables = _ramas_que_no_construyen()
    assert len(culpables) >= 3, f"el oráculo sólo ve {len(culpables)} ramas inelegibles"
    # Y tiene que estar mirando la unión que motivó el criterio, por nombre.
    assert {r for _, r in culpables} >= {
        "InternalLgdBetaRegression",
        "InternalLgdFractionalResponse",
        "InternalLgdWorkout",
    }, f"el oráculo dejó de ver las ramas modeladas de LGD: {culpables}"
    # Control negativo del CRITERIO: las ramas de partición NO pueden entrar. Si entran, el
    # criterio volvió a ser «no construye» y acusa a seis inocentes que D-OBL ya cubre.
    assert not {r for _, r in culpables} & {
        "TemporalSplitConfig",
        "CohortSplitConfig",
        "ColumnSplitConfig",
        "Rule",
        "PerformanceWindow",
    }, f"el criterio se relajó y acusa ramas que el formulario sí pregunta: {culpables}"


def test_toda_rama_inelegible_esta_declarada_en_el_abanico() -> None:
    """D-EXI-3: si el motor rechaza una rama elegida sola, el catálogo tiene que decirlo.

    🔴 Este gate nació ROJO acusando exactamente las tres ramas modeladas de LGD, que se
    publicaban `disponible` con `motivo=None` sobre una elección que el motor rechaza al
    instante — o sea D-ABA-3 violado en producción. Y el gate anterior **no podía verlo** por dos
    razones medidas: no comprobaba constructibilidad, y sobre una unión inspeccionaba **la
    primera rama**, no las cinco.
    """
    declarados = {
        (path.rsplit(".", 1)[0], opcion["value"])
        for path, opcion in _opciones()
        if opcion["estado"] == jobs._EXIGE_OTRO_CAMPO
    }
    clases = cargar_configs_de_dominio()
    sin_declarar: list[str] = []
    for campo, rama in _ramas_que_no_construyen():
        seccion, *resto = campo.split(".")
        modelo: Any = clases[seccion]
        for nombre in resto:
            modelo = modelo.model_fields[nombre].annotation
        tag = next(
            (
                r.model_fields["method"].default
                for r in _ramas_de_union(modelo)
                if r.__name__ == rama and "method" in r.model_fields
            ),
            None,
        )
        if tag is None or (campo, tag) not in declarados:
            sin_declarar.append(f"{campo} → {rama} (tag {tag!r})")
    assert not sin_declarar, (
        "hay ramas que el motor rechaza si se eligen solas y el abanico las ofrece como si no: "
        f"{sin_declarar}. Van con `estado=_EXIGE_OTRO_CAMPO` y su clave `exige`, nunca como "
        "`no_implementada` —eso publicaría que la librería no las tiene, que es falso."
    )


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
        # Este gate mide el LITERAL del catálogo, no el payload: ahí `when` es opcional (sólo la
        # declara un punto que no aplica siempre, D-EXI-6). Se exige por los dos lados igual —las
        # obligatorias presentes y nada ajeno—, que es lo que impide que una clave nueva se cuele
        # sin decisión detrás; su publicación al contrato REST la vigila `_exige_claves`.
        assert set(eleccion) >= jobs._CLAVES_DE_ELECCION, path
        assert not set(eleccion) - jobs._CLAVES_DE_ELECCION - jobs._CLAVES_OPCIONALES_DE_ELECCION, (
            f"{path}: clave del abanico que nadie decidió cómo publicar"
        )
        assert eleccion["question"].endswith("?"), f"{path}: la pregunta no pregunta"
        assert len(eleccion["help"]) > 40, f"{path}: la ayuda no ayuda"
        assert eleccion["options"], f"{path}: el catálogo no puede quedar sin opción canónica"
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
