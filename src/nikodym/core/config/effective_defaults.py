"""Catálogo de defaults **efectivos** del config (enmienda DEFAULTS-EFECTIVOS-UI, D-FX-5/D-FX-6).

El formulario del UI pinta un campo ausente y necesita saber **qué valor usaría el motor** si nadie
lo escribe. JSON Schema no puede responder eso: ``default`` es una anotación opcional, no se aplica,
y Pydantic **no la emite** para los submodelos creados por ``default_factory``. Campos como
``report.sections``, ``report.html``, ``model.stepwise`` o ``selection.correlation`` nacen así, de
modo que el formulario los pintaba vacíos, apagados o en cero mientras el motor corría con otra
cosa. Inferir ``{}``/``false``/``0``/«la primera opción» desde el schema duplicaría la lógica de
Pydantic en React y es justo lo que produjo esas divergencias.

La respuesta es una **sola fuente**: este catálogo, derivado de las clases Pydantic registradas
(``cargar_configs_de_dominio()`` + ``model_fields``), ejecutando el mismo ``default`` /
``default_factory`` que ejecutaría el motor y serializando por alias y en modo JSON. JSON Schema
sigue siendo la verdad de **forma y validación** —tipo, nulabilidad, restricciones, enum, widget,
discriminador—; el catálogo decide **qué valor efectivo pinta una ausencia**, y nada más.

**Forma del artefacto** (versionada, aditiva):

.. code-block:: json

    {"version": 1,
     "sections": {"report": {"sections": {"required_sections": {"has_default": true,
                                                                "value": ["eda", "..."]}}}},
     "$defs": {"data__RandomSplitConfig": {"holdout_fraction": {"has_default": true,
                                                                "value": 0.15}}}}

Dos coordenadas, porque el formulario alcanza los campos por dos caminos:

- ``sections`` indexa los campos raíz de :class:`~nikodym.core.config.NikodymConfig` y desciende por
  los submodelos. Es el camino de una **sección** —``report``, ``data``…—, cuyo nodo el schema
  compuesto empotra *inline* y por tanto no tiene ``$ref`` que seguir.
- ``$defs`` replica la coordenada homónima del schema compuesto para modelos anidados y variantes.
  Las claves son **exactamente** las que referencia ``json_schema`` (``<sección>__<Clase>``, o
  ``<Clase>`` para los modelos del config raíz), no un identificador paralelo: es lo que permite que
  el front resuelva una fila de lista o la rama elegida de una unión discriminada, donde la
  coordenada ``sections`` no llega.

**Cada hoja es un descriptor, no el valor desnudo** (D-FX-5): ``{"has_default": false}`` es *no hay
default* y ``{"has_default": true, "value": null}`` es *el default es ``null``*. Confundirlos es
exactamente el error que D-FX-7 prohíbe en el front, así que el contrato no permite expresarlo mal.
Un campo cuyo tipo es **un** submodelo OPCIONAL no lleva descriptor: lleva el mapa de sus hijos,
porque su valor efectivo lo determinan ellos y el formulario nunca pinta un control para el objeto
entero. Si el submodelo es **obligatorio**, en cambio, lleva descriptor **y** hijos —
``{"has_default": false, "children": {…}}`` (D-OBL-2)—, porque tiene que decir las dos cosas: que no
hay valor que ofrecer para el objeto, y cuáles son los defaults de dentro. Sin esa distinción la
proyección canónica escribía el objeto entero y producía configs que el motor rechaza, que es el
defecto que la enmienda DECISIONES-OBLIGATORIAS vino a cerrar.

Un dominio cuyo extra no esté instalado **no se expande**: su sección viaja como un descriptor
(``{"has_default": true, "value": null}``, que es su default real de campo apagable) y sin mapa de
hijos, y no aparece ninguna clave ``<sección>__…`` en ``$defs``. O sea: el formulario no fabrica ni
un default para ella, y las dos superficies —schema y catálogo— dicen lo mismo (D-FX-10). No es que
la clave desaparezca del payload; es que no hay nada debajo que ofrecer.

**Experimental (fuera de la garantía SemVer 1.x):** el catálogo crece aditivamente en las 1.x.
"""

from __future__ import annotations

import types
from typing import Annotated, Any, Final, Union, get_args, get_origin

from pydantic import BaseModel, TypeAdapter
from pydantic.fields import FieldInfo

from nikodym.core.config.schema import (
    NikodymConfig,
    build_full_json_schema,
    cargar_configs_de_dominio,
)

__all__ = [
    "DESCRIPTOR_KEYS",
    "DISCRIMINADOR",
    "EFFECTIVE_DEFAULTS_VERSION",
    "build_effective_defaults",
    "modelos_de_anotacion",
]

#: Versión del artefacto. Sube sólo si cambia su FORMA (no su contenido): el front la lee para
#: negarse a interpretar un catálogo que no entiende, en vez de leerlo mal en silencio.
EFFECTIVE_DEFAULTS_VERSION: Final[int] = 1

#: Las únicas claves de un descriptor. ``children`` sólo aparece en el descriptor de un submodelo
#: OBLIGATORIO (D-OBL-2): ahí el nodo tiene que decir dos cosas a la vez —que no hay valor que
#: ofrecer para el objeto entero, y cuáles son los defaults de sus hijos—, y un mapa desnudo sólo
#: puede decir la segunda.
DESCRIPTOR_KEYS: Final[tuple[str, ...]] = ("has_default", "value", "children")

#: La clave que **discrimina** un descriptor de un mapa de hijos: un nodo es descriptor si y sólo si
#: tiene ``has_default`` **booleano**. Exigir el tipo, y no la mera presencia, es lo que mantiene la
#: regla decidible aunque algún día un config declare un campo llamado así (entonces su nodo sería
#: un dict, no un bool). ``value`` NO es reservada: ``data.target.bad_rule…value`` ya existe.
DISCRIMINADOR: Final[str] = "has_default"


def modelos_de_anotacion(anotacion: Any) -> list[type[BaseModel]]:
    """Clases ``BaseModel`` alcanzables por una anotación, atravesando uniones y contenedores.

    ``tuple[ColumnSpec, ...]`` devuelve ``[ColumnSpec]`` y ``LogitConfig | XgboostConfig`` devuelve
    las dos. Se usa para dos cosas distintas: decidir si un campo es *un* submodelo (exactamente
    una clase y sin contenedor) y enumerar qué modelos hay que publicar en ``$defs``.
    """
    if isinstance(anotacion, type) and issubclass(anotacion, BaseModel):
        return [anotacion]
    encontrados: list[type[BaseModel]] = []
    for argumento in get_args(anotacion):
        for modelo in modelos_de_anotacion(argumento):
            if modelo not in encontrados:
                encontrados.append(modelo)
    return encontrados


def _submodelo_directo(anotacion: Any) -> type[BaseModel] | None:
    """La clase del campo si es **un** submodelo (admite ``| None`` y ``Annotated``), o ``None``.

    Un campo que es un submodelo se publica como mapa de hijos; una lista de submodelos o una unión
    discriminada se publica como descriptor y sus clases viajan por ``$defs``.
    """
    origen = get_origin(anotacion)
    if origen is Annotated:
        return _submodelo_directo(get_args(anotacion)[0])
    if origen in (Union, types.UnionType):
        candidatos = [a for a in get_args(anotacion) if a is not type(None)]
        if len(candidatos) != 1:
            return None
        return _submodelo_directo(candidatos[0])
    if isinstance(anotacion, type) and issubclass(anotacion, BaseModel):
        return anotacion
    return None


def _clave_publica(nombre: str, campo: FieldInfo) -> str:
    """La clave con que el campo viaja en el payload: su alias si lo tiene, si no su nombre.

    Es la misma que usa ``model_json_schema`` en ``properties`` y ``model_dump(by_alias=True)`` en
    el config, así que un ``path`` del formulario indexa las tres superficies igual. Nunca el nombre
    Python: ``data.schema_`` no existe para nadie fuera de Pydantic.
    """
    return campo.alias or nombre


def _volcado_canonico(cls: type[BaseModel]) -> dict[str, Any] | None:
    """``Cls().model_dump(mode="json", by_alias=True)`` si la clase se puede construir vacía.

    **Es la fuente PREFERENTE del valor efectivo, y no un adorno.** ``FieldInfo.get_default`` sólo
    conoce el ``default``/``default_factory`` declarado en el campo, y hay valores que el modelo
    materializa **después**, en un ``model_validator``. Medido: ``MLConfig.hyperparameters`` declara
    ``None`` y un validador ``mode="before"`` lo rellena con los siete hiperparámetros del backend,
    así que el catálogo publicaba ``null`` donde el motor corre con un dict. Construir la clase
    ejecuta la misma cadena que ejecutará la corrida, que es justo lo que el catálogo promete.

    Un modelo con campos obligatorios —o con un validador que rechaza la instancia vacía— devuelve
    ``None`` y cada campo cae a su ``FieldInfo``: **no se inventa una instancia inválida** (D-FX-5).
    Hoy son cuatro secciones (``data``, ``forward``, ``stress``, ``survival``) más los submodelos
    con
    requeridos, y ahí ningún validador de relleno está en juego.
    """
    try:
        return cls().model_dump(mode="json", by_alias=True)
    except Exception:
        return None


def _descriptor(campo: FieldInfo, volcado: dict[str, Any] | None, clave: str) -> dict[str, Any]:
    """Descriptor de una hoja: el mismo valor efectivo que materializaría el motor.

    ``has_default`` lo decide siempre el campo (``is_required``), porque es una pregunta del
    contrato y no del valor. El VALOR, en cambio, sale del volcado de la instancia cuando la clase
    es construible —ahí ya corrieron los validadores— y sólo si no lo es se cae a
    ``FieldInfo.get_default(call_default_factory=True)``.

    Ese ``call_default_factory=True`` sigue siendo imprescindible en la rama de respaldo: sin él los
    ``default_factory`` —el 100 % de los submodelos y varias listas— no se materializan y el
    catálogo repetiría el hueco que el JSON Schema ya tiene.
    """
    if campo.is_required():
        return {"has_default": False}
    if volcado is not None and clave in volcado:
        return {"has_default": True, "value": volcado[clave]}
    default = campo.get_default(call_default_factory=True)
    return {"has_default": True, "value": _a_json(campo, default)}


def _a_json(campo: FieldInfo, valor: Any) -> Any:
    """Serializa el default **por alias y en modo JSON**, con la anotación real del campo.

    Se delega en Pydantic (``TypeAdapter``) para que una tupla salga como lista, un ``Enum`` como su
    valor y un submodelo como su ``model_dump``: el catálogo debe ser byte-comparable con lo que el
    motor publica, no una traducción propia. Si la anotación no es adaptable —``Any``, un forward
    ref sin resolver— se cae a una conversión estructural explícita en vez de reventar el payload.
    """
    try:
        return TypeAdapter(campo.annotation).dump_python(
            valor, mode="json", by_alias=True, warnings=False
        )
    except Exception:
        # Degradar es correcto: el catálogo es aditivo y su hueco lo cubre `provenance: missing`.
        return _a_json_estructural(valor)


def _a_json_estructural(valor: Any) -> Any:
    """Último recurso: convierte a JSON sin conocer la anotación."""
    if isinstance(valor, BaseModel):
        return valor.model_dump(mode="json", by_alias=True)
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [_a_json_estructural(v) for v in valor]
    if isinstance(valor, dict):
        return {str(k): _a_json_estructural(v) for k, v in valor.items()}
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return str(valor)


def _admite_nulo(anotacion: Any) -> bool:
    """¿La anotación admite ``None``? (``X | None``, ``Optional[X]``, dentro de ``Annotated``)."""
    origen = get_origin(anotacion)
    if origen is Annotated:
        return _admite_nulo(get_args(anotacion)[0])
    if origen in (Union, types.UnionType):
        return type(None) in get_args(anotacion)
    return False


def _submodelo_apagable(campo: FieldInfo) -> bool:
    """¿Es un submodelo **apagable** (``X | None``), el que el formulario pinta con un switch.

    Va como descriptor, no como mapa de hijos, porque lo que el formulario necesita de él es su
    estado efectivo —``null`` = apagado— y un mapa no puede expresarlo. Cuatro campos lo son hoy
    (``data.target.good_rule``, ``indeterminate_rule``, ``window``, ``stress.reverse[].target``) y
    los cuatro nacen apagados; publicarlos como mapa dejaba el interruptor encendido sobre un objeto
    que el motor no crea. Sus hijos siguen alcanzables por la entrada de ``$defs``, que es de donde
    el front toma la proyección canónica cuando el usuario lo activa.

    Se decide por la ANOTACIÓN y no por el valor del default, para que un futuro
    ``X | None = X(...)`` —apagable pero encendido de fábrica— siga publicando su estado.
    """
    return _admite_nulo(campo.annotation)


def _mapa_de_modelo(cls: type[BaseModel], pila: tuple[str, ...]) -> dict[str, Any]:
    """Mapa ``{clave pública: nodo}`` de una clase: descriptor por hoja, mapa por submodelo.

    ``pila`` corta la recursión de un modelo que se referencia a sí mismo (reglas anidadas): ahí se
    publica un mapa vacío y el front sigue el ``$ref`` del schema hasta la entrada de ``$defs``, que
    siempre existe. Sin el corte, un config recursivo colgaría el proceso al construir el payload.

    El volcado de la instancia se calcula **una vez por clase** y se pasa a cada hoja: es la fuente
    preferente del valor efectivo (ver :func:`_volcado_canonico`).

    **Un submodelo OBLIGATORIO va como descriptor con hijos** (D-OBL-2), no como mapa desnudo. Un
    mapa no puede decir «este objeto no tiene default», así que la proyección canónica lo escribía
    entero con los defaults de sus hojas y producía un objeto que el motor rechaza: de ahí salía
    ``data.target.bad_rule = {all_of: [], any_of: []}``, que muere con «una Rule debe declarar al
    menos un predicado». El criterio es la OBLIGATORIEDAD del campo y no la construibilidad de su
    clase —esa decide de dónde sale el valor de las hojas, que es otra pregunta—: medido,
    ``DataConfig.load`` es construible y también salía como mapa.
    """
    salida: dict[str, Any] = {}
    volcado = _volcado_canonico(cls)
    for nombre, campo in cls.model_fields.items():
        clave = _clave_publica(nombre, campo)
        submodelo = _submodelo_directo(campo.annotation)
        if submodelo is None or _submodelo_apagable(campo):
            salida[clave] = _descriptor(campo, volcado, clave)
        elif campo.is_required():
            # Los hijos viajan igual —el formulario sigue necesitando sus defaults— pero colgando
            # de un descriptor que declara el hueco. Si la recursión ya pasó por esta clase, los
            # hijos van vacíos y el front baja por `$defs`, igual que en la rama de abajo.
            hijos = (
                {}
                if submodelo.__name__ in pila
                else _mapa_de_modelo(submodelo, (*pila, submodelo.__name__))
            )
            salida[clave] = {"has_default": False, "children": hijos}
        elif submodelo.__name__ in pila:
            salida[clave] = {}
        else:
            salida[clave] = _mapa_de_modelo(submodelo, (*pila, submodelo.__name__))
    return salida


def _modelos_alcanzables(cls: type[BaseModel], acumulado: dict[str, type[BaseModel]]) -> None:
    """Recolecta, por nombre de clase, todos los modelos alcanzables desde ``cls``."""
    if cls.__name__ in acumulado:
        return
    acumulado[cls.__name__] = cls
    for campo in cls.model_fields.values():
        for modelo in modelos_de_anotacion(campo.annotation):
            _modelos_alcanzables(modelo, acumulado)


def build_effective_defaults() -> dict[str, Any]:
    """Catálogo versionado de defaults efectivos, listo para ``GET /api/schema``.

    Se construye contra el **schema compuesto** para que las claves de ``$defs`` sean literalmente
    las que ``json_schema`` referencia: se publica una entrada por cada modelo alcanzable cuyo
    nombre calce con una clave real del schema. Un modelo que Pydantic renombrara se quedaría sin
    entrada, y el gate ``test_effective_defaults.py`` —que exige cobertura total de los ``$defs``
    con ``properties``— lo pondría rojo en vez de dejar al front a ciegas.

    Returns
    -------
    dict
        ``{"version": int, "sections": {...}, "$defs": {...}}``. Determinista: dos llamadas en el
        mismo proceso producen los mismos bytes.
    """
    schema = build_full_json_schema()
    defs_schema: dict[str, Any] = schema.get("$defs", {})
    dominios = cargar_configs_de_dominio()

    secciones: dict[str, Any] = {}
    volcado_raiz = _volcado_canonico(NikodymConfig)
    for nombre, campo in NikodymConfig.model_fields.items():
        clave = _clave_publica(nombre, campo)
        # Una sección de dominio es un campo ``Any`` en el núcleo liviano: su clase real la conoce
        # el registro de dominios, no la anotación. Un extra ausente no aparece en ``dominios`` y
        # por tanto tampoco aquí: sección opaca, sin defaults fabricados (D-FX-10).
        cls = dominios.get(nombre) or _submodelo_directo(campo.annotation)
        if cls is None:
            secciones[clave] = _descriptor(campo, volcado_raiz, clave)
        else:
            secciones[clave] = _mapa_de_modelo(cls, (cls.__name__,))

    catalogo_defs: dict[str, Any] = {}
    for prefijo, raices in _raices_por_prefijo(dominios).items():
        alcanzables: dict[str, type[BaseModel]] = {}
        for cls in raices:
            _modelos_alcanzables(cls, alcanzables)
        for nombre_cls, cls in alcanzables.items():
            clave_def = f"{prefijo}{nombre_cls}"
            if clave_def in defs_schema:
                catalogo_defs[clave_def] = _mapa_de_modelo(cls, (nombre_cls,))

    return {
        "version": EFFECTIVE_DEFAULTS_VERSION,
        "sections": secciones,
        "$defs": dict(sorted(catalogo_defs.items())),
    }


def _raices_por_prefijo(
    dominios: dict[str, type[BaseModel]],
) -> dict[str, list[type[BaseModel]]]:
    """``{prefijo de ``$defs``: clases desde las que se alcanzan sus modelos}``.

    ``_empotrar_seccion`` hoistea los ``$defs`` de cada sub-config con el prefijo ``<sección>__``
    para que dos dominios con una clase homónima no colisionen; los modelos del config raíz viajan
    sin prefijo. Este mapa reproduce esa misma partición, que es la única razón por la que basta
    calzar por nombre de clase.
    """
    raices: dict[str, list[type[BaseModel]]] = {"": []}
    for campo in NikodymConfig.model_fields.values():
        raices[""].extend(modelos_de_anotacion(campo.annotation))
    for seccion, cls in dominios.items():
        raices[f"{seccion}__"] = [cls]
    return raices
