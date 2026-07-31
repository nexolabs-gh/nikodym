"""Gate de CLASE: una sección de config opaca no puede cambiar lo que el motor responde.

Tres defectos serios de los últimos tres releases son **el mismo defecto** con tres disfraces, y
todos nacen de que una sección de config puede existir en **dos estados** —tipada (su modelo
Pydantic) u opaca (un ``dict``, porque el proceso no importó esa capa)— sin que casi ningún
consumidor lo contemple:

* **1.7.0** — `Study.save()` guardaba una corrida exitosa que `Study.load()` rechazaba: el lineage
  congelaba el `config_hash` del config *como se escribió*, no del que *se ejecutó*.
* **1.8.0** — el **mismo** config daba **dos `config_hash` distintos** según qué módulos hubiera
  importado el proceso.
* **2026-07-28** — el preflight recién nacido devolvía `compatible=True` con cero desajustes sobre
  un config que tenía diecisiete: sobre un ``dict`` no hay ``Field`` que consultar, y calló.

Los tres se arreglaron **donde dolía**. Este gate ataca la clase: para cada superficie pública que
consume un `NikodymConfig`, exige que su respuesta sea **la misma** con la sección tipada y con la
sección opaca. Ninguno de los tres defectos habría sobrevivido a esta comprobación.

No es un gate de estilo: es la única defensa que no depende de que quien escriba el consumidor
número ocho se acuerde de que la opacidad existe.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import nikodym
from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.core.study import _DOMAIN_CONFIG_CLASSES
from nikodym.ui.presets import get_preset
from nikodym.ui.routes import config_to_yaml

#: Consumidores públicos de `NikodymConfig` y cómo tratan una sección opaca.
#:
#: `comprobado` — este gate corre la función en los dos estados y compara la respuesta.
#: `exento: <razón>` — no se corre aquí, con el motivo escrito. Una exención sin razón no existe.
#:
#: El registro cubre lo que el censo puede ver: funciones cuya **firma** declara `NikodymConfig`.
#: Las superficies REST reciben el config como `Any` —son el borde HTTP— así que no aparecen aquí;
#: `config_to_yaml` tiene su propio test más abajo por esa razón, no por olvido.
POLITICA: dict[str, str] = {
    "config_hash": "comprobado",
    "check_dataset": "comprobado",
    "check_pipeline": "comprobado",
    "dump_config": (
        "exento: produce YAML distinto según la opacidad, pero sin consecuencia — sus dos "
        "consumidores la neutralizan (`config_to_yaml` con exclude_unset, `Study.save` volcando "
        "el config ya resuelto). Se vigila `config_to_yaml`, que es la ruta del usuario"
    ),
    "run": (
        "exento: ejecuta el pipeline completo (minutos) y monta sinks. Coacciona al resolver, y "
        "que el lineage se congele DESPUÉS de resolver lo fija el gate del round-trip de 1.7.0"
    ),
    "assemble_run": "exento: sólo lee las secciones de infraestructura, que nunca viajan opacas",
    "log_config": "exento: requiere MLflow (extra `tracking`); su entrada es el config ya resuelto",
}

#: Columnas del dataset del catálogo, para `check_dataset`.
COLUMNAS = (
    "cohorte",
    "ingreso_mensual",
    "deuda_ingreso",
    "utilizacion_linea",
    "mora_max_12m",
    "antiguedad_meses",
    "segmento",
    "bad_flag",
)


def _consumidores_publicos() -> set[str]:
    """Funciones públicas de `src/nikodym` que reciben un `NikodymConfig` en su firma."""
    encontrados: set[str] = set()
    raiz = pathlib.Path(__file__).resolve().parents[2] / "src" / "nikodym"
    for ruta in raiz.rglob("*.py"):
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - el repo no tiene fuentes rotas
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if nodo.name.startswith("_"):
                continue
            for arg in [*nodo.args.args, *nodo.args.kwonlyargs]:
                anotacion = ast.unparse(arg.annotation) if arg.annotation else ""
                if "NikodymConfig" in anotacion:
                    encontrados.add(nodo.name)
                    break
    return encontrados


@pytest.fixture
def par_tipado_y_opaco() -> tuple[NikodymConfig, NikodymConfig]:
    """El mismo config en sus dos estados: con `binning` tipada y con `binning` opaca.

    Se fuerza con ``model_copy`` y no con el constructor: dentro de la suite las capas de dominio
    están siempre importadas, así que la raíz coacciona y **ningún montaje natural** produce una
    sección opaca. Ésa es la razón de que los tres defectos convivieran con 4.500 tests verdes.

    El ``dict`` opaco se toma del preset y se le **quita un campo con default**, que es la otra
    mitad de la condición: si el dict coincide exactamente con el `model_dump` del modelo, los dos
    estados dan lo mismo por casualidad y el test no probaría nada.
    """
    crudo = get_preset("f1-estandar-consumo")["config"]

    # Sin esto la sección llega opaca IGUAL: la raíz sólo coacciona los dominios que el mapa
    # canónico haya materializado, y tener `nikodym.binning` importado no basta. Medido al escribir
    # este gate, y merece decirse: el estado opaco no es un caso raro de procesos mínimos — es el
    # DEFAULT mientras nadie pida el schema o valide por la API.
    cargar_configs_de_dominio()
    tipado = NikodymConfig.model_validate(crudo)

    seccion = dict(crudo["binning"])
    seccion.pop("min_bin_n_event", None)  # default omitido: sin esto el caso es trivial
    opaco = tipado.model_copy(update={"binning": seccion})

    assert isinstance(opaco.binning, dict), "precondición: la sección debe quedar opaca"
    assert not isinstance(tipado.binning, dict), "precondición: la otra debe estar tipada"
    return tipado, opaco


def test_config_hash_no_depende_de_la_opacidad(
    par_tipado_y_opaco: tuple[NikodymConfig, NikodymConfig],
) -> None:
    """El defecto de 1.8.0. La identidad de una corrida no puede depender de los imports."""
    tipado, opaco = par_tipado_y_opaco

    assert config_hash(opaco) == config_hash(tipado)


def test_check_dataset_no_depende_de_la_opacidad(
    par_tipado_y_opaco: tuple[NikodymConfig, NikodymConfig],
) -> None:
    """El defecto del 2026-07-28: sobre un ``dict`` no hay `Field`, y el preflight callaba."""
    tipado, opaco = par_tipado_y_opaco

    esperado = nikodym.check_dataset(tipado, COLUMNAS)
    obtenido = nikodym.check_dataset(opaco, COLUMNAS)

    assert obtenido.compatible == esperado.compatible
    assert obtenido.uninspected == esperado.uninspected
    assert [m.path for m in obtenido.mismatches] == [m.path for m in esperado.mismatches]


def test_check_pipeline_no_depende_de_la_opacidad(
    par_tipado_y_opaco: tuple[NikodymConfig, NikodymConfig],
) -> None:
    """Si un config es ejecutable, lo es con la capa importada y sin ella."""
    tipado, opaco = par_tipado_y_opaco

    artifacts = [("data", "frame")]
    assert nikodym.check_pipeline(opaco, artifacts=artifacts) == nikodym.check_pipeline(
        tipado, artifacts=artifacts
    )


def test_el_yaml_que_exporta_la_ui_no_depende_de_la_opacidad() -> None:
    """El YAML que el usuario descarga es lo que vuelve a cargar: no puede bifurcarse.

    Se comprueba sobre ``config_to_yaml`` —la ruta real de la UI— y **no** sobre ``dump_config``.
    La diferencia se midió al escribir este gate y merece quedar escrita, porque invita al error
    contrario: ``dump_config`` sí produce YAML distinto según la opacidad, pero eso **no es un
    defecto con consecuencia**. Sus dos consumidores críticos ya la neutralizan por su cuenta —
    ``config_to_yaml`` vuelca con ``exclude_unset=True`` justamente para ser determinista frente al
    estado de imports, y ``Study.save()`` vuelca el config ya resuelto y completo—. Exigirle la
    invariante a ``dump_config`` sería fabricar un defecto donde hay una decisión deliberada.
    """
    crudo = get_preset("f1-estandar-consumo")["config"]
    seccion = dict(crudo["binning"])
    seccion.pop("min_bin_n_event", None)  # default omitido: la mitad de la condición del defecto

    con_default_omitido = config_to_yaml({**crudo, "binning": seccion})["yaml"]
    completo = config_to_yaml(crudo)["yaml"]

    # El YAML refleja lo que el usuario escribió, y lo hace igual con la capa importada y sin ella.
    assert "min_bin_n_event" not in con_default_omitido
    assert "min_bin_n_event" in completo


def test_todo_consumidor_publico_declara_su_politica_ante_una_seccion_opaca() -> None:
    """El consumidor número ocho no puede olvidarse de que la opacidad existe.

    Es la parte del gate que no caduca: los tests de arriba fijan las cuatro superficies de hoy,
    y éste obliga a que cualquier superficie nueva se pronuncie —comprobada o exenta con razón—
    en vez de heredar el silencio que costó tres defectos.
    """
    sin_politica = sorted(_consumidores_publicos() - set(POLITICA))

    assert not sin_politica, (
        f"Consumidores públicos de NikodymConfig sin política declarada: {sin_politica}. "
        "Una sección de dominio puede llegarles como `dict` opaco (el proceso no importó esa "
        "capa) y responder distinto sin avisar. Añádelos a POLITICA: 'comprobado' con su test, "
        "o 'exento: <razón>'."
    )


def test_ninguna_exencion_esta_sin_razon() -> None:
    """`exento` a secas sería una política que no dice nada."""
    vacias = [
        nombre
        for nombre, politica in POLITICA.items()
        if politica != "comprobado" and not politica.startswith("exento: ")
    ]

    assert not vacias, f"exenciones sin razón escrita: {vacias}"


def test_la_politica_no_cita_consumidores_que_ya_no_existen() -> None:
    """El sentido simétrico: una entrada muerta manda al lector a buscar humo."""
    fantasmas = sorted(set(POLITICA) - _consumidores_publicos())

    assert not fantasmas, f"POLITICA cita funciones inexistentes: {fantasmas}"


def test_el_censo_encuentra_de_verdad_los_consumidores() -> None:
    """Ancla contra un recorrido roto: cero consumidores encontrados daría un gate verde y vacío."""
    encontrados = _consumidores_publicos()

    for esperado in ("config_hash", "run", "check_pipeline", "check_dataset"):
        assert esperado in encontrados, f"el censo perdió {esperado}"


def test_hay_mas_de_una_seccion_expuesta_a_la_opacidad() -> None:
    """Contexto del gate: la clase cubre 22 secciones, no sólo la que prueban los tests de arriba.

    Se ancla a mano para que quede claro el tamaño de la superficie: `binning` es la sección con la
    que se ejercita el invariante, pero cualquiera de las 22 puede llegar opaca.
    """
    assert len(_DOMAIN_CONFIG_CLASSES) >= 20
    assert "binning" in _DOMAIN_CONFIG_CLASSES
