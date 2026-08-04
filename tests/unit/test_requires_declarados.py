"""Gate de CLASE del contrato CT-1: ``Step.requires`` declara lo que el paso VA a leer (D-REQ-8).

🔴 **Existe porque el mismo defecto apareció dos veces con dos disfraces**, y las dos veces hubo que
medirlo ejecutando para verlo: ``tuning``/``explain`` declaraban los requisitos del **default de
fábrica** de ``ml`` en vez de los de la config del usuario (M-2), y ``provisioning_cmf`` declara de
menos bajo ``pd_mapping.method='pd_breaks'`` (M-3). Los dos producen además la **misma tercera
mentira**, encontrada por separado en cada uno sin buscarla: ``PipelineCheck.inert_artifacts``
declara inerte una clave que el paso sí consume.

Sin un gate de clase, el tercer caso vuelve a nacer con la suite entera en verde — que es
exactamente lo que pasó con las tres reincidencias de la sección opaca.

**Qué mide, y por qué así.** La propiedad no es «``requires`` es correcto» —eso exige ejecutar cada
dominio— sino la estructural que separa a un paso honesto de uno que miente: **si los requisitos que
``execute`` compone dependen de la config de OTRO dominio**, entonces al construirse el paso no
podía saberlos; o los recibe por el hook contextual, o su declaración previa es una promesa que el
motor no sostiene.

⚠️ **La primera versión de este gate media otra cosa y acusaba a tres inocentes.** Su condición era
«re-deriva en ``execute``», y con ella salían ``ml``, ``provisioning`` y ``validation`` — que
re-derivan desde **su propia** sección, releída de ``study.config`` por si difiere de la del
constructor. Eso no es el defecto: un paso siempre puede saber lo suyo. Lo que no puede saber, y es
lo que aquí se persigue, es lo que decidió otro.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

_RAIZ: Final = Path(__file__).resolve().parents[2] / "src" / "nikodym"

#: Prefijo de las funciones que **componen** una tupla de ``requires`` dentro de un dominio. Es una
#: convención de nombre del repo (``tuning``, ``explain``, ``ifrs9``, ``internal``…), no una clase
#: base: los dominios no heredan del núcleo para declarar algo suyo.
_PREFIJO_COMPOSITOR: Final = "_requires_for"

#: Pasos que componen requisitos con datos ajenos y **no** declaran el hook, con su razón escrita.
#: Que la excepción esté aquí es lo que impide que se lea como un olvido.
_EXENTOS: Final[dict[str, str]] = {}

#: 🔴 **LO QUE ESTE GATE NO VE, declarado en vez de callado.** Una lista de exentos vacía se lee
#: como «todos los pasos están limpios», y no es cierto: el detector persigue **una** forma
#: —componer los requisitos con datos de otra sección— y hay una segunda que no reconoce.
#:
#: ``provisioning_cmf`` no compone nada: declara un ``requires`` **fijo** y valida sus dependencias
#: condicionales a mano dentro de ``execute`` (`cmf/step.py`), de modo que declara **de menos**
#:
#: ``pd_mapping.method='pd_breaks'``. Está medido —``check_pipeline`` da verde y la corrida revienta
#: con ``ArtifactNotFoundError``— y **no se cierra**: por decisión de producto (2026-08-05) la
#: normativa local de cada país sale del alcance de la librería y su motor no recibe inversión. Ver
#: ``docs/design/_ENMIENDA-REQUISITOS-CMF.md``.
#:
#: Detectar esa segunda forma exige comparar el ``requires`` declarado con lo que ``execute`` lee de
#: verdad, que no es una propiedad sintáctica. El día que haga falta, ése es el trabajo — no ampliar
#: este detector, que mide otra cosa y la mide bien.
_NO_CUBIERTO: Final[dict[str, str]] = {
    "provisioning.cmf": (
        "declara `requires` fijo y valida a mano en execute: el detector busca un compositor "
        "y aquí no hay ninguno. Medido y NO cerrado por decisión de producto (normativa local "
        "fuera de alcance)."
    )
}


def _modulos_de_paso() -> dict[str, ast.Module]:
    """Todos los ``step.py`` de dominio, parseados. Es el universo que el gate barre."""
    modulos: dict[str, ast.Module] = {}
    for ruta in sorted(_RAIZ.glob("*/**/step.py")):
        # `parts`, no `str(...).replace("/", ".")`: en Windows el separador es `\` y el nombre salía
        # como `provisioning\cmf`, así que el ancla anti-vacuidad fallaba **sólo allí**. Lo cazó el
        # CI, que es donde tenía que cazarse — y prueba de paso que el ancla no es decorativa.
        nombre = ".".join(ruta.relative_to(_RAIZ).parent.parts)
        modulos[nombre] = ast.parse(ruta.read_text(encoding="utf-8"))
    return modulos


def _clases_de_paso(modulo: ast.Module) -> list[ast.ClassDef]:
    """Las clases del módulo que declaran ``requires``, o sea las que implementan el Protocol."""
    return [
        nodo
        for nodo in modulo.body
        if isinstance(nodo, ast.ClassDef)
        and any(
            isinstance(hijo, ast.AnnAssign)
            and isinstance(hijo.target, ast.Name)
            and hijo.target.id == "requires"
            for hijo in nodo.body
        )
    ]


def _metodo(clase: ast.ClassDef, nombre: str) -> ast.FunctionDef | None:
    for hijo in clase.body:
        if isinstance(hijo, ast.FunctionDef) and hijo.name == nombre:
            return hijo
    return None


def _lectores_de_config_ajena(execute: ast.FunctionDef, dominio: str) -> set[str]:
    """Variables de ``execute`` que salen de leer la config de OTRO dominio, y sus derivadas.

    El repo nombra esos lectores por convención: ``_<dominio>_config_from_study``. Se propaga por
    asignaciones hasta punto fijo porque el valor rara vez llega directo al compositor —``explain``
    hace ``feature_source = _resolve_feature_source(ml_cfg)`` y pasa **eso**—.
    """
    propio = dominio.rsplit(".", 1)[-1]
    contaminados: set[str] = set()
    while True:
        crecio = False
        for nodo in ast.walk(execute):
            if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
                continue
            destino = nodo.targets[0]
            if not isinstance(destino, ast.Name) or destino.id in contaminados:
                continue
            fuentes = {
                hijo.func.id
                for hijo in ast.walk(nodo.value)
                if isinstance(hijo, ast.Call) and isinstance(hijo.func, ast.Name)
            }
            ajena = any(
                nombre.startswith("_")
                and nombre.endswith("_config_from_study")
                and nombre != f"_{propio}_config_from_study"
                for nombre in fuentes
            )
            usados = {hijo.id for hijo in ast.walk(nodo.value) if isinstance(hijo, ast.Name)}
            if ajena or (usados & contaminados):
                contaminados.add(destino.id)
                crecio = True
        if not crecio:
            return contaminados


def _rederiva_desde_config_ajena(clase: ast.ClassDef, dominio: str) -> bool:
    """``True`` si ``execute`` compone requisitos con datos que decidió OTRA sección."""
    execute = _metodo(clase, "execute")
    if execute is None:
        return False
    contaminados = _lectores_de_config_ajena(execute, dominio)
    for nodo in ast.walk(execute):
        if not (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id.startswith(_PREFIJO_COMPOSITOR)
        ):
            continue
        argumentos = {
            hijo.id
            for argumento in nodo.args
            for hijo in ast.walk(argumento)
            if isinstance(hijo, ast.Name)
        }
        if argumentos & contaminados:
            return True
        # Segunda forma, sin variable de por medio: `_requires_for(study.config.ml.feature_source)`.
        # No es hipotética —es cómo se escribiría el mismo defecto en una línea— y el detector que
        # sólo siguiera asignaciones la dejaría pasar en silencio.
        propio = dominio.rsplit(".", 1)[-1]
        for argumento in nodo.args:
            for hijo in ast.walk(argumento):
                if (
                    isinstance(hijo, ast.Attribute)
                    and isinstance(hijo.value, ast.Attribute)
                    and hijo.value.attr == "config"
                    and hijo.attr != propio
                ):
                    return True
    return False


def test_el_barrido_ve_los_pasos_del_motor_y_no_cero() -> None:
    """ANCLA ANTI-VACUIDAD: un gate que recorre cero pasos da verde y no prueba nada.

    Ya ocurrió en este repo —un gate de copy daba verde recorriendo cero campos— y por eso todo
    barrido nuevo ancla su universo con números y con nombres concretos.
    """
    modulos = _modulos_de_paso()

    assert len(modulos) >= 15, f"el barrido sólo ve {len(modulos)} módulos de paso"
    for esperado in ("tuning", "explain", "report", "provisioning.cmf", "ml"):
        assert esperado in modulos, f"falta {esperado} en el barrido"

    clases = [clase for modulo in modulos.values() for clase in _clases_de_paso(modulo)]
    assert len(clases) >= 15, f"sólo se reconocieron {len(clases)} clases con `requires`"


def test_todo_paso_que_rederiva_en_execute_recibe_el_contexto() -> None:
    """D-REQ-8: si los requisitos dependen de la invocación, el paso tiene que poder saberla.

    Un paso que compone sus requisitos otra vez dentro de ``execute`` está diciendo que lo que
    declaró al construirse podía ser falso. La salida es el hook contextual (D-FX-2/D-REQ-2); la
    alternativa —declarar el default de fábrica y confiar en que ``execute`` lo arregle— es
    literalmente el defecto M-2, que convivió con la suite verde y con dos tests que lo describían.
    """
    culpables: list[str] = []
    for nombre, modulo in _modulos_de_paso().items():
        for clase in _clases_de_paso(modulo):
            if not _rederiva_desde_config_ajena(clase, nombre):
                continue
            if _metodo(clase, "from_config_with_context") is None and nombre not in _EXENTOS:
                culpables.append(f"{nombre}.{clase.name}")

    assert not culpables, (
        "estos pasos componen sus `requires` con datos de OTRA sección y no reciben el contexto de "
        f"la invocación: {culpables}. Declare `from_config_with_context` (D-REQ-2) o añádalo a "
        "_EXENTOS con su razón."
    )


def test_el_gate_caza_el_defecto_que_viene_a_cazar() -> None:
    """CONTROL POSITIVO: sobre el código anterior a D-REQ-1, el gate se pone rojo.

    Un gate que declara barrer una clase se prueba **inyectando** el defecto, no describiéndolo. Se
    reconstruye aquí la forma exacta que tenían ``tuning`` y ``explain`` —compositor llamado en
    ``execute``, sin fábrica contextual— y se comprueba que el detector la marca; y la forma
    corregida, que no.
    """
    antes = ast.parse(
        "class PasoViejo:\n"
        "    requires: tuple = ()\n"
        "    def __init__(self, cfg):\n"
        "        self.requires = _requires_for(_DEFAULT_FEATURE_SOURCE)\n"
        "    def execute(self, study, rng):\n"
        "        return _requires_for(study.config.ml.feature_source)\n"
    )
    despues = ast.parse(
        "class PasoNuevo:\n"
        "    requires: tuple = ()\n"
        "    def __init__(self, cfg, *, contrato=None):\n"
        "        self.requires = _requires_for(contrato)\n"
        "    @classmethod\n"
        "    def from_config_with_context(cls, cfg, *, contexto):\n"
        "        return cls(cfg, contrato=contexto.contrato_de_variables)\n"
        "    def execute(self, study, rng):\n"
        "        return _requires_for(study.config.ml.feature_source)\n"
    )

    inocente = ast.parse(
        "class PasoPropio:\n"
        "    requires: tuple = ()\n"
        "    def __init__(self, cfg):\n"
        "        self.requires = _requires_for(cfg)\n"
        "    def execute(self, study, rng):\n"
        "        cfg = _ml_config_from_study(study, fallback=self.config)\n"
        "        return _requires_for(cfg)\n"
    )

    viejo = _clases_de_paso(antes)[0]
    nuevo = _clases_de_paso(despues)[0]
    propio = _clases_de_paso(inocente)[0]

    assert _rederiva_desde_config_ajena(viejo, "tuning")
    assert _metodo(viejo, "from_config_with_context") is None  # ← lo que el gate marca
    assert _rederiva_desde_config_ajena(nuevo, "tuning")
    assert _metodo(nuevo, "from_config_with_context") is not None
    # CONTROL NEGATIVO: releer la sección PROPIA no es el defecto, y acusarlo sería el falso
    # positivo que la primera versión de este gate cometió con `ml`, `provisioning` y
    # `validation`.
    assert not _rederiva_desde_config_ajena(propio, "ml")


@pytest.mark.parametrize("dominio", ["tuning", "explain"])
def test_los_dos_casos_de_m2_quedan_dentro_del_barrido(dominio: str) -> None:
    """Los pasos que motivaron el gate tienen que **disparar** su condición, no esquivarla.

    Si mañana alguien renombra el compositor o mueve la re-derivación fuera de ``execute``, el gate
    dejaría de mirarlos **en silencio** y volvería a ser verde vacío sobre el defecto original.
    """
    modulo = _modulos_de_paso()[dominio]
    clases = _clases_de_paso(modulo)

    assert clases, f"{dominio} no expone ninguna clase con `requires`"
    assert any(_rederiva_desde_config_ajena(clase, dominio) for clase in clases), (
        f"{dominio} ya no compone sus requisitos con datos ajenos: si el cambio es legítimo, "
        "dejó de vigilarlo y hay que decidir con qué se sustituye"
    )
    assert all(_metodo(clase, "from_config_with_context") is not None for clase in clases)


# ═════════ El efecto en la superficie pública: las TRES mentiras, medidas ═════════
#
# 🔴 Esta sección existe porque el primer arreglo pasaba los tests por-paso y dejaba el defecto VIVO
# aquí: `_contexto_de_resolucion` miraba las secciones ACTIVAS, y con `run.steps=['tuning']` la
# sección `ml` existe y no corre — pero `tuning.execute` la lee igual. Un test del paso no puede ver
# eso; sólo lo vio medir por la puerta que el usuario usa.


def _config_con_ml_no_default() -> object:
    """Config donde ``ml`` elige una fuente de variables distinta del default de fábrica."""
    from nikodym.core.config import NikodymConfig, RunConfig
    from nikodym.ml.config import MLConfig, MonotonicConfig
    from nikodym.tuning.config import TuningConfig

    return NikodymConfig(
        ml=MLConfig(feature_source="selection_woe", monotonic=MonotonicConfig(mode="off")),
        tuning=TuningConfig(),
        run=RunConfig(steps=["tuning"]),
    )


_ARTEFACTOS_REALES: Final = [
    ("data", "labels"),
    ("data", "splits"),
    ("selection", "selected_woe_frame"),
    ("selection", "selected_woe_columns"),
]
_ARTEFACTOS_DEL_DEFAULT: Final = [
    ("data", "labels"),
    ("data", "splits"),
    ("binning", "woe_frame"),
    ("binning", "result"),
    ("binning", "tables"),
]


def test_check_pipeline_ya_no_rechaza_un_pipeline_que_corre() -> None:
    """FALSO ROJO cerrado: con los artefactos que el paso SÍ lee, la comprobación previa acepta.

    Antes respondía ``executable=False`` exigiendo ``binning.woe_frame`` —que con
    ``feature_source='selection_woe'`` el paso no abre nunca— sobre un pipeline perfectamente
    ejecutable.
    """
    import nikodym

    chequeo = nikodym.check_pipeline(_config_con_ml_no_default(), artifacts=_ARTEFACTOS_REALES)

    assert chequeo.executable, f"sigue el falso rojo: {chequeo.message}"


def test_los_artefactos_que_el_paso_consume_dejan_de_declararse_inertes() -> None:
    """D-REQ-7 — la TERCERA mentira, que ningún censo traía y salió midiendo.

    ``PipelineCheck.inert_artifacts`` promete «una clave válida que ningún paso activo consume».
    Declaraba inertes los dos artefactos de ``selection`` que el paso iba a leer, así que el usuario
    recibía a la vez «te falta binning» (falso) y «lo de selection no lo usa nadie» (falso).
    """
    import nikodym

    chequeo = nikodym.check_pipeline(_config_con_ml_no_default(), artifacts=_ARTEFACTOS_REALES)

    assert chequeo.inert_artifacts == (), f"siguen saliendo inertes: {chequeo.inert_artifacts}"


def test_check_pipeline_ya_no_acepta_un_pipeline_que_muere() -> None:
    """FALSO VERDE cerrado, y es la mitad que más importa: un rojo se ve, un verde falso no.

    Con sólo los artefactos del default de ``ml``, la corrida moría en ``execute`` con
    ``ArtifactNotFoundError('selection','selected_woe_frame')`` después de que la comprobación
    previa dijera que todo estaba en orden. Ahora lo dice antes, y nombra la clave.

    Control positivo: los artefactos inyectados que el paso ya **no** lee salen como inertes, que es
    la afirmación simétrica y la que prueba que el veredicto cambió por la razón correcta.
    """
    import nikodym

    chequeo = nikodym.check_pipeline(_config_con_ml_no_default(), artifacts=_ARTEFACTOS_DEL_DEFAULT)

    assert not chequeo.executable, "sigue el falso verde"
    assert "selected_woe_frame" in (chequeo.message or "")
    assert set(chequeo.inert_artifacts) == {
        ("binning", "woe_frame"),
        ("binning", "result"),
        ("binning", "tables"),
    }


def test_una_fuente_diferida_no_entra_al_contrato_y_conserva_su_diagnostico() -> None:
    """``data_raw`` está DIFERIDA: publicarla empeoraba el mensaje que lee el usuario.

    Salió al implementar, y es la clase de daño que un arreglo de ``requires`` puede causar sin que
    nadie lo note: al declarar ``('data','frame')`` como prerequisito duro, el DAG cortaba antes con
    «necesita 'frame', que produce 'data'» —cierto, y mucho peor— en vez del ``FALTA-DATO-ML-1`` que
    nombra la carencia y sus dos salidas. Un paso con ``data_raw`` no llega a correr nunca, así que
    omitirla del contrato no declara de menos: decide **cuál de los dos errores** se lee.
    """
    from nikodym.ml.config import MLConfig

    diferida = MLConfig(feature_source="data_raw").contrato_de_variables_declarado()
    normal = MLConfig(feature_source="selection_woe").contrato_de_variables_declarado()

    assert "origen_de_variables" not in diferida
    assert diferida["monotonia"]  # el otro campo del contrato sigue publicándose
    # Control positivo: una fuente viva SÍ se publica, o el test pasaría con el contrato vacío.
    assert normal["origen_de_variables"] == "selection_woe"
