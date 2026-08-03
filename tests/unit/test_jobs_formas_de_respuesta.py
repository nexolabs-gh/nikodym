"""Gate de las FORMAS DE RESPUESTA de una decisión obligatoria (D-COL-6/8).

Una decisión obligatoria pregunta algo que sólo la institución sabe —qué define a un cliente malo,
cómo se separa la muestra—, pero la mayoría admite **varias formas de contestarla**, y hasta ahora
la interfaz sólo ofrecía una: escribir el config a mano. La que faltaba es justo la del banco que ya
trae la respuesta en su archivo.

Cada forma declara su plantilla —el fragmento de config que produce— y sus `slots`, los huecos que
deja a propósito. Este gate ata las tres piezas al motor real, en las dos direcciones:

- **La plantilla es ejecutable**: rellenada por sus slots, `model_validate` la acepta. Una plantilla
  que el motor rechazaría no puede llegar a la pantalla.
- **Los slots son huecos de verdad**: apuntan a una posición que existe en la plantilla y que está
  vacía. Un slot inventado dejaría la decisión eternamente «sin contestar»; un slot de menos la
  daría por contestada con un dato que nadie escribió, que es el falso «ya está» de D-OBL-5.
- **Cobertura bidireccional de ramas**: para un path cuyo schema es una unión discriminada, el
  conjunto de ids iguala al de discriminadores. Una quinta estrategia sin forma ⇒ rojo; una forma
  sin rama ⇒ rojo.
- **Nadie contesta por el usuario**: ningún path de decisión se materializa en `effective_defaults`
  ni se escribe desde el mapeo de un insumo externo.
- **Identidad**: completar por una forma da el mismo `config_hash` que escribirlo a mano.
"""

from __future__ import annotations

import copy
from typing import Any, Literal, get_args, get_origin

import pytest
from pydantic import BaseModel

from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config.effective_defaults import build_effective_defaults
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.ui import jobs
from nikodym.ui.jobs import decisiones_de, list_jobs
from nikodym.ui.presets import standard_preset

#: Valor de relleno por tipo de hueco. Escrito a mano y no derivado del schema: si se dedujera del
#: mismo sitio que se está comprobando, el gate mediría que la deducción es consistente consigo
#: misma en vez de que la plantilla es válida.
_RELLENO: dict[str, Any] = {
    "data.target.bad_rule": {
        "all_of.0.col": "mora_max_12m",
        "all_of.0.op": ">",
        "all_of.0.value": 90,
    },
    "data.partition.strategy": {
        "date_col": "fecha_obs",
        "oot_from": "2024-04-01",
        "cohort_col": "cohorte",
        "oot_cohorts": ["2024Q2"],
        "partition_col": "muestra",
        "desarrollo": ["DEV"],
    },
}


def _decisiones() -> dict[str, dict[str, Any]]:
    """``{path: decisión}`` tal como el catálogo la publica."""
    return {d["path"]: d for job in list_jobs() for d in job["required_decisions"]}


def _modelo_del_path(path: str) -> tuple[type[BaseModel], str]:
    """Devuelve ``(clase que declara la hoja, nombre del campo)`` para un path del config."""
    seccion, *resto = path.split(".")
    cls = cargar_configs_de_dominio()[seccion]
    for nombre in resto[:-1]:
        anotacion = cls.model_fields[nombre].annotation
        assert isinstance(anotacion, type) and issubclass(anotacion, BaseModel), path
        cls = anotacion
    return cls, resto[-1]


def _ramas_discriminadas(path: str) -> set[str] | None:
    """Los discriminadores del campo, o ``None`` si su tipo no es una unión discriminada.

    Se leen de la anotación —``Annotated[A | B, Field(discriminator=…)]``— y no del JSON Schema:
    la anotación es la fuente que el motor obedece al validar.
    """
    cls, nombre = _modelo_del_path(path)
    anotacion = cls.model_fields[nombre].annotation
    ramas = get_args(anotacion)
    discriminadores: set[str] = set()
    for rama in ramas:
        if not (isinstance(rama, type) and issubclass(rama, BaseModel)):
            return None
        for campo in rama.model_fields.values():
            if get_origin(campo.annotation) is Literal:
                discriminadores.add(str(get_args(campo.annotation)[0]))
                break
    return discriminadores or None


def _en_plantilla(plantilla: Any, slot: str) -> Any:
    """Baja por la plantilla siguiendo el slot; levanta ``KeyError``/``IndexError`` si no existe."""
    nodo = plantilla
    for tramo in slot.split("."):
        nodo = nodo[int(tramo)] if tramo.isdigit() else nodo[tramo]
    return nodo


def _rellena(plantilla: Any, slot: str, valor: Any) -> None:
    """Escribe `valor` en la posición del slot, in place."""
    nodo = plantilla
    tramos = slot.split(".")
    for tramo in tramos[:-1]:
        nodo = nodo[int(tramo)] if tramo.isdigit() else nodo[tramo]
    ultimo = tramos[-1]
    nodo[int(ultimo) if ultimo.isdigit() else ultimo] = valor


def _completada(path: str, forma: dict[str, Any]) -> Any:
    """La plantilla de una forma con todos sus huecos rellenos."""
    plantilla = copy.deepcopy(forma["template"])
    for slot in forma["slots"]:
        _rellena(plantilla, slot, _RELLENO[path][slot])
    return plantilla


def test_el_barrido_no_es_vacuo() -> None:
    """Un gate que recorre cero formas daría verde diciendo nada. Ya pasó en este repo."""
    decisiones = _decisiones()
    assert len(decisiones) == 4, sorted(decisiones)
    con_formas = {p: d["answer_forms"] for p, d in decisiones.items() if d["answer_forms"]}
    assert sorted(con_formas) == ["data.partition.strategy", "data.target.bad_rule"]
    assert len(con_formas["data.partition.strategy"]) == 4
    assert len(con_formas["data.target.bad_rule"]) == 2


def test_toda_plantilla_rellenada_la_acepta_el_motor() -> None:
    """La plantilla es ejecutable, no decorativa: `model_validate` del modelo real la valida."""
    comprobadas = 0
    for path, decision in _decisiones().items():
        for forma in decision["answer_forms"]:
            cls, nombre = _modelo_del_path(path)
            campo = {**{k: v for k, v in _minimo(cls).items()}, nombre: _completada(path, forma)}
            cls.model_validate(campo)
            comprobadas += 1
    assert comprobadas == 6, comprobadas


def _minimo(cls: type[BaseModel]) -> dict[str, Any]:
    """Los otros campos obligatorios de la clase, con un valor cualquiera que valide."""
    fijos: dict[str, dict[str, Any]] = {
        "PartitionConfig": {},
        "TargetConfig": {},
    }
    return fijos.get(cls.__name__, {})


def test_todo_slot_apunta_a_un_hueco_real_de_su_plantilla() -> None:
    """Un slot inventado deja la decisión eternamente «sin contestar» y nadie sabría por qué."""
    for path, decision in _decisiones().items():
        for forma in decision["answer_forms"]:
            for slot in forma["slots"]:
                valor = _en_plantilla(forma["template"], slot)
                assert valor in ("", None, [], {}), (
                    f"{path}/{forma['id']}: el slot «{slot}» no está vacío en la plantilla "
                    f"(vale {valor!r}). Un slot es un hueco que el usuario rellena; si la "
                    "plantilla ya trae el valor, o sobra el slot o el motor está suponiendo."
                )


def test_todo_hueco_de_la_plantilla_esta_declarado_como_slot() -> None:
    """La otra dirección: un hueco sin slot se daría por contestado estando vacío.

    Es el falso «ya está» que D-OBL-5 existe para impedir: la tarjeta pondría el tilde verde con el
    dato institucional sin escribir, y la corrida moriría después con jerga del motor.
    """
    for path, decision in _decisiones().items():
        for forma in decision["answer_forms"]:
            huecos = sorted(_huecos(forma["template"]))
            exceptuados = _HUECOS_NO_EXIGIDOS.get((path, forma["id"]), frozenset())
            assert huecos == sorted(set(forma["slots"]) | exceptuados), (
                f"{path}/{forma['id']}: huecos {huecos} contra slots {sorted(forma['slots'])}. "
                "Si un hueco no debe exigirse, decláralo en `_HUECOS_NO_EXIGIDOS` con su motivo."
            )


#: Huecos que la plantilla deja vacíos y que NO se exigen para dar la decisión por contestada, con
#: su motivo. Se enumeran uno a uno —y no por regla— para que añadir uno obligue a justificarlo.
_HUECOS_NO_EXIGIDOS: dict[tuple[str, str], frozenset[str]] = {
    # D-COL-4: con la división leída de una columna, las particiones exigidas son EXACTAMENTE las
    # que el usuario mapeó. Reclamar `holdout` y `oot` sería el motor exigiendo muestras que la
    # institución quizá no separa. `desarrollo` sí se exige: sin ella no hay sobre qué ajustar.
    ("data.partition.strategy", "columna"): frozenset({"holdout", "oot"}),
    # `any_of` vacío es la regla «sólo condiciones unidas por AND», que es la forma normal de una
    # política de mora. Exigirlo obligaría a escribir un OR que nadie necesita.
    ("data.target.bad_rule", "condiciones"): frozenset({"any_of"}),
    ("data.target.bad_rule", "columna_marcada"): frozenset({"any_of"}),
    # `stratify_by` es opcional en el motor y su default ES `None`: no estratificar. Vacío aquí
    # significa «el default», no «falta el dato». Lo cazó este gate en su primera corrida, que es
    # exactamente para lo que sirve distinguir un hueco de un default que resulta ser nulo.
    ("data.partition.strategy", "random"): frozenset({"stratify_by"}),
}


def _huecos(nodo: Any, prefijo: str = "") -> set[str]:
    """Rutas de la plantilla cuyo valor está vacío (`""`, `None`, `[]`, `{}`)."""
    encontrados: set[str] = set()
    if isinstance(nodo, dict):
        hijos = nodo.items()
    elif isinstance(nodo, list):
        hijos = [(str(i), v) for i, v in enumerate(nodo)]  # type: ignore[assignment]
    else:
        return encontrados
    for clave, valor in hijos:
        ruta = f"{prefijo}{clave}"
        if valor in ("", None, [], {}):
            encontrados.add(ruta)
        else:
            encontrados |= _huecos(valor, f"{ruta}.")
    return encontrados


def test_las_formas_cubren_exactamente_las_ramas_que_el_motor_declara() -> None:
    """Bidireccional, y sólo aplicable donde el schema tiene ramas que enumerar."""
    con_ramas = 0
    for path, decision in _decisiones().items():
        ramas = _ramas_discriminadas(path)
        if ramas is None:
            continue
        con_ramas += 1
        ids = {f["id"] for f in decision["answer_forms"]}
        assert ids == ramas, (
            f"{path}: formas {sorted(ids)} contra ramas del motor {sorted(ramas)}. "
            "Una estrategia nueva necesita su forma de respuesta, y una forma sin rama detrás "
            "escribiría un config que el motor rechaza."
        )
    assert con_ramas == 1, "sólo `data.partition.strategy` es hoy una unión discriminada"


def test_una_decision_sin_ramas_ni_alternativas_no_inventa_formas() -> None:
    """Preguntar «¿qué columna?» con una sola forma sería una pantalla de más para lo mismo."""
    decisiones = _decisiones()
    for path in ("survival.input.duration_col", "survival.input.event_col"):
        assert decisiones[path]["answer_forms"] == [], path


def test_el_copy_de_una_forma_no_habla_en_jerga_interna() -> None:
    """Lo único que el usuario lee de una forma es `label` y `help` (D-OBL-9)."""
    prohibido = ("bad_rule", "all_of", "any_of", "partition", "strategy", "config", "path", "slot")
    ofensores = []
    for path, decision in _decisiones().items():
        for forma in decision["answer_forms"]:
            for campo in ("label", "help"):
                texto = forma[campo].lower()
                ofensores += [
                    f"{path}/{forma['id']}.{campo}: «{t}»" for t in prohibido if t in texto
                ]
    assert ofensores == [], ofensores


def test_ninguna_decision_se_materializa_en_los_defaults_efectivos() -> None:
    """Prohibido contestar por el usuario, por CI (gate que la enmienda D-COL pide).

    ⚠️ Se mide sobre el nodo de la decisión, no sobre sus hijos: D-OBL-2 decidió publicar un
    submodelo obligatorio como descriptor **que conserva sus hijos**, así que `bad_rule.all_of`
    tiene default y eso es correcto —es lo que deja al formulario saber pintarlo—. Lo que no puede
    tener valor es la decisión misma, porque materializarla es responderla.
    """
    catalogo = build_effective_defaults()
    for path in _decisiones():
        nodo: Any = catalogo["sections"]
        for tramo in path.split("."):
            nodo = nodo.get(tramo) if tramo in nodo else (nodo.get("children") or {}).get(tramo)
            assert nodo is not None, f"{path}: el catálogo ni siquiera lo describe"
        assert nodo.get("has_default") is False, (
            f"{path} viene con valor en `effective_defaults`: {nodo}. Es una decisión "
            "institucional; publicarle un default es contestarla por el usuario (D-OBL-1)."
        )


def test_ningun_insumo_externo_escribe_en_un_path_de_decision() -> None:
    """La otra vía por la que algo podría contestarse solo: el mapeo de un archivo externo.

    Un `config_path` que apuntara a una decisión la daría por respondida con lo que trae **otro**
    archivo — y encima uno que el motor lee por separado de la cartera (D-COL-8).
    """
    decisiones = set(_decisiones())
    escritos = {
        ruta
        for job in list_jobs()
        for entrada in job["external_artifacts"]
        for columna in entrada["columns"]
        for ruta in columna["config_paths"]
    }
    assert escritos, "el barrido no encontró ni un `config_path`: el oráculo está roto"
    assert escritos & decisiones == set(), sorted(escritos & decisiones)


def test_completar_por_una_forma_da_la_misma_identidad_que_escribirlo_a_mano() -> None:
    """Un clic escribe exactamente lo que el usuario habría escrito (D-COL-8, D-OBL-10).

    Si el `config_hash` difiriera, dos corridas idénticas quedarían con identidades distintas según
    por dónde entró el usuario, y el lineage dejaría de identificar el cálculo.
    """
    preset = standard_preset()["config"]
    forma = next(
        f for f in _decisiones()["data.partition.strategy"]["answer_forms"] if f["id"] == "cohort"
    )
    plantilla = copy.deepcopy(forma["template"])
    _rellena(plantilla, "cohort_col", "cohorte")
    _rellena(plantilla, "oot_cohorts", ["2024Q2"])

    por_formulario = copy.deepcopy(preset)
    por_formulario["data"]["partition"]["strategy"] = plantilla

    a_mano = copy.deepcopy(preset)
    a_mano["data"]["partition"]["strategy"] = {
        "type": "cohort",
        "cohort_col": "cohorte",
        "oot_cohorts": ["2024Q2"],
        "holdout_fraction": 0.2,
    }
    assert config_hash(NikodymConfig.model_validate(por_formulario)) == config_hash(
        NikodymConfig.model_validate(a_mano)
    )
    # Y es el del preset intacto: la forma reconstruye su estrategia sin moverle la identidad.
    assert config_hash(NikodymConfig.model_validate(por_formulario)) == config_hash(
        NikodymConfig.model_validate(preset)
    )


def test_el_catalogo_devuelve_copias_hasta_el_fondo() -> None:
    """Con `answer_forms` la decisión dejó de ser plana: una copia superficial ya no basta.

    El gate anterior mutaba sólo una clave de primer nivel, así que habría seguido verde mientras el
    llamador contaminaba las plantillas del proceso entero.
    """
    primero = decisiones_de(["data"])
    primero[0]["answer_forms"][0]["template"]["all_of"][0]["col"] = "MUTADO"
    primero[0]["answer_forms"][0]["slots"].append("MUTADO")
    limpio = decisiones_de(["data"])
    assert limpio[0]["answer_forms"][0]["template"]["all_of"][0]["col"] == ""
    assert "MUTADO" not in limpio[0]["answer_forms"][0]["slots"]


@pytest.mark.parametrize(
    ("literal", "serializador", "clave"),
    [
        ({"path": "x", "question": "¿?", "help": "h", "answer_forms": ()}, "_decision_json", "x"),
        (
            {"id": "i", "label": "l", "help": "h", "template": {}, "slots": ()},
            "_forma_json",
            "y",
        ),
    ],
)
def test_una_clave_nueva_en_el_literal_rompe_en_vez_de_perderse(
    literal: dict[str, Any], serializador: str, clave: str
) -> None:
    """🔴 El defecto que este paquete encontró y arregló, ahora con gate.

    Los serializadores del catálogo se escriben campo a campo para que una clave nueva no se cuele
    al contrato REST con la forma que tuviera. Pero eso, por sí solo, **no avisa**: la descarta en
    silencio. Medido sobre `_insumo_json` antes de arreglarlo — con una clave inventada en el
    literal, los 31 gates del catálogo seguían verdes y el dato desaparecía. Un campo nuevo así es
    una feature muerta que nadie ve, como D-JOB-17.
    """
    fn = getattr(jobs, serializador)
    fn(literal)  # tal cual, pasa
    with pytest.raises(ValueError, match="decide cómo viaja"):
        fn({**literal, clave: "nueva"})
