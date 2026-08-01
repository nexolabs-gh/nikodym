"""Gate de las DECISIONES OBLIGATORIAS de un trabajo (D-OBL-6/7, enmienda DECISIONES-OBLIGATORIAS).

Una decisión obligatoria es lo que el motor **no puede rellenar por nadie**: qué define un cliente
malo en esta cartera, cómo se separa la muestra. Son `DATO-INSTITUCIONAL`, y por eso el catálogo de
defaults efectivos las omite en vez de inventarlas (D-OBL-1/2) y el trabajo las pregunta en
idioma de negocio (D-OBL-6).

**Por qué el gate es bidireccional, y por qué eso es lo único que lo hace útil.** Los paths se
declaran a mano en ``nikodym/ui/jobs.py`` —tienen que ser literales, porque esa capa es
*domain-agnostic* por otro gate—, así que sin nada que los ate al motor se separarían en silencio en
las dos direcciones:

- **Falta una pregunta** ⇒ alguien añade un campo obligatorio al motor y un trabajo pasa a ser
  incompletable sin que la interfaz sepa decir qué falta. Es el modo de fallo caro.
- **Sobra una pregunta** ⇒ el copy pide algo que ya tiene default, y la interfaz reclama por un
  campo que el usuario no necesita tocar.

El oráculo se deriva de ``model_fields``, que es donde Pydantic guarda la obligatoriedad de verdad.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import BaseModel

from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.ui.jobs import decisiones_de, list_jobs

#: Las 14 secciones que el formulario ofrece. Espejo del catálogo del front; el gate de deriva de
#: esa lista vive en `test_column_roles.py`, y aquí sólo acota el barrido a lo navegable.
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


def _hojas_obligatorias(cls: type[BaseModel], prefijo: tuple[str, ...]) -> list[str]:
    """Paths de las HOJAS obligatorias sin default, bajando por los submodelos obligatorios.

    Baja sólo por lo obligatorio a propósito: dentro de un submodelo **opcional** los campos
    requeridos no son decisiones pendientes —el submodelo entero se puede omitir—, así que
    preguntarlos sería reclamar por algo que el usuario no tiene que contestar.
    """
    encontradas: list[str] = []
    for nombre, campo in cls.model_fields.items():
        if not campo.is_required():
            continue
        clave = campo.alias or nombre
        anotacion = campo.annotation
        if isinstance(anotacion, type) and issubclass(anotacion, BaseModel):
            hijas = _hojas_obligatorias(anotacion, (*prefijo, clave))
            # Un submodelo obligatorio cuyos hijos tienen todos default es él mismo la decisión.
            encontradas.extend(hijas or [".".join((*prefijo, clave))])
        else:
            encontradas.append(".".join((*prefijo, clave)))
    return encontradas


def _obligatorias_del_formulario() -> dict[str, list[str]]:
    """``{sección: [paths obligatorios]}`` para las secciones que el formulario ofrece."""
    disponibles = cargar_configs_de_dominio()
    salida: dict[str, list[str]] = {}
    for seccion in SECCIONES_DEL_FORMULARIO:
        cls = disponibles.get(seccion)
        if cls is None:
            continue  # extra ausente: su sección no se expande, y no hay nada que preguntar
        paths = _hojas_obligatorias(cls, (seccion,))
        if paths:
            salida[seccion] = paths
    return salida


def _decisiones_declaradas() -> dict[str, dict[str, Any]]:
    """``{path: decisión}`` de todo lo que el catálogo declara, sin repetir."""
    declaradas: dict[str, dict[str, Any]] = {}
    for job in list_jobs():
        for decision in job["required_decisions"]:
            declaradas[decision["path"]] = decision
    return declaradas


def test_el_barrido_no_es_vacuo() -> None:
    """Sin esto, un oráculo roto daría verde con cero campos — ya pasó en este repo."""
    obligatorias = _obligatorias_del_formulario()
    assert obligatorias, "el barrido no encontró ni una sección con campos obligatorios"
    assert "data" in obligatorias, "`data.target.bad_rule` existe: el oráculo está roto"
    assert _decisiones_declaradas(), "el catálogo no declara ninguna decisión"


def test_toda_decision_declarada_es_de_verdad_obligatoria() -> None:
    """Dirección 1: no se reclama por un campo que ya tiene default."""
    todas = {p for paths in _obligatorias_del_formulario().values() for p in paths}
    sobrantes = sorted(set(_decisiones_declaradas()) - todas)
    assert sobrantes == [], (
        f"el catálogo pregunta por campos que no son obligatorios: {sobrantes}. "
        "Si el motor les dio un default, quita su pregunta del catálogo."
    )


def test_todo_campo_obligatorio_del_formulario_tiene_su_pregunta() -> None:
    """Dirección 2: la que de verdad importa.

    Sin ella, añadir un campo obligatorio al motor deja un trabajo incompletable y la interfaz
    callada — el usuario ve «este campo es obligatorio» y ningún sitio le dice cuál ni por qué.
    """
    declaradas = set(_decisiones_declaradas())
    faltan = sorted(
        f"{seccion}: {path}"
        for seccion, paths in _obligatorias_del_formulario().items()
        for path in paths
        if path not in declaradas
    )
    assert faltan == [], (
        f"campos obligatorios sin pregunta declarada: {faltan}. Añádeles su entrada en "
        "`_DECISIONES_POR_SECCION` de `nikodym/ui/jobs.py`, con la pregunta en idioma de negocio."
    )


def test_un_trabajo_hereda_exactamente_las_decisiones_de_sus_secciones() -> None:
    """El reparto por sección no puede dejar a un trabajo con preguntas de una sección que no ve."""
    obligatorias = _obligatorias_del_formulario()
    for job in list_jobs():
        suyas = set(job["sections"])
        for decision in job["required_decisions"]:
            seccion = decision["path"].split(".", 1)[0]
            assert seccion in suyas, (
                f"«{job['id']}» pregunta por {decision['path']}, de una sección que no muestra"
            )
        esperadas = {p for s, paths in obligatorias.items() if s in suyas for p in paths}
        assert {d["path"] for d in job["required_decisions"]} == esperadas, job["id"]


def test_los_dos_trabajos_con_survival_preguntan_cuatro_cosas() -> None:
    """Ancla nominal: escrita a mano, no derivada, para que el gate no sea una tautología."""
    por_id = {job["id"]: job for job in list_jobs()}
    if "survival" not in cargar_configs_de_dominio():
        pytest.skip("el extra de survival no está instalado")
    for job_id in ("pd_lifetime", "provisiones_ifrs9"):
        paths = [d["path"] for d in por_id[job_id]["required_decisions"]]
        assert paths == [
            "data.target.bad_rule",
            "data.partition.strategy",
            "survival.input.duration_col",
            "survival.input.event_col",
        ], job_id
    assert [d["path"] for d in por_id["scorecard_pd"]["required_decisions"]] == [
        "data.target.bad_rule",
        "data.partition.strategy",
    ]


#: Lo que una pregunta NO puede contener: el path, el nombre de una clase o cualquier literal que
#: sólo signifique algo dentro del código (D-OBL-9). El usuario lee negocio, no coordenadas.
_JERGA = re.compile(
    r"\b(None|True|False|null|bad_rule|good_rule|target_col|duration_col|event_col|strategy|"
    r"partition|BaseModel|NikodymConfig|config_hash|DataFrame|dataframe)\b"
)


def test_el_copy_de_una_decision_no_filtra_jerga_interna() -> None:
    """El path es la coordenada interna; lo que se lee es la pregunta.

    Mismo criterio que el gate de copy del catálogo de trabajos: una superficie que un humano lee no
    puede nombrar un campo del config. Aquí importa el doble, porque la decisión es justo el sitio
    donde la tentación de «pon el nombre del campo y se entiende» es más fuerte.
    """
    ofensores: list[str] = []
    for path, decision in _decisiones_declaradas().items():
        for campo in ("question", "help"):
            encontrado = _JERGA.search(decision[campo])
            if encontrado:
                ofensores.append(f"{path}.{campo}: «{encontrado.group(0)}»")
    assert ofensores == [], ofensores


def test_una_decision_declara_las_tres_piezas_y_se_lee_como_pregunta() -> None:
    """Forma mínima: sin `question` no hay nada que enseñar, y sin `help` la pregunta queda sola."""
    for path, decision in _decisiones_declaradas().items():
        assert set(decision) == {"path", "question", "help"}, path
        assert decision["question"].endswith("?"), f"{path}: la pregunta no pregunta"
        assert len(decision["help"]) > 40, f"{path}: la ayuda no ayuda"


def test_el_catalogo_devuelve_copias() -> None:
    """Mutar lo que devuelve el catálogo no puede contaminar el proceso."""
    primero = list_jobs()[0]["required_decisions"]
    primero[0]["question"] = "MUTADO"
    assert list_jobs()[0]["required_decisions"][0]["question"] != "MUTADO"


def test_decisiones_de_no_repite_ni_depende_del_orden() -> None:
    """Dos trabajos con las mismas secciones preguntan lo mismo, en el mismo orden."""
    assert decisiones_de(["data", "survival"]) == decisiones_de(["survival", "data"])
    assert decisiones_de(["data", "data"]) == decisiones_de(["data"])
    assert decisiones_de([]) == []
    assert decisiones_de(["binning", "report"]) == [], "esas secciones no imponen decisiones"
