"""Gate de las invariantes previas (enmienda INVARIANTES-PREVIAS, D-INV-1…D-INV-9).

Un config puede contradecirse a sí mismo sin que ningún campo nombre una columna que falte:
`stability.temporal_axis` distinto de `none` sobre un dataset sin columna de período, `families`
vacío, comparaciones repetidas. El motor lo diagnostica **bien**, pero recién al llegar al paso: el
caso de origen moría en el 8 de 10 con `check_dataset` y `check_pipeline` los dos en verde.

Estos tests miden las dos cosas que hacen creíble la enmienda: que cada invariante se avise
**antes** de correr, y que la cobertura esté **declarada** en vez de callada (D-INV-7).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.core.dataset_check import METODO_REQUISITOS, check_dataset
from nikodym.data.config import TemporalSplitConfig
from nikodym.performance.config import PerformanceConfig
from nikodym.stability.config import TEMPORAL_CANDIDATE_NAMES, StabilityConfig
from nikodym.survival.config import SurvivalConfig
from nikodym.validation.config import ValidationConfig

#: Columnas de un dataset corriente **sin** ninguna candidata a período.
SIN_PERIODO = frozenset({"BAD", "LOAN", "DEBTINC"})


# ── el caso de origen, en sus tres sentidos ───────────────────────────────────────────────────
def test_eje_temporal_sin_columna_de_periodo_avisa() -> None:
    """El caso medido con HMEQ: eje activo, ninguna candidata en el dataset."""
    requisitos = StabilityConfig(temporal_axis="period").requisitos_incumplidos(SIN_PERIODO)

    assert [r.path for r in requisitos] == ["temporal_axis"]
    assert "período" in requisitos[0].message


def test_eje_temporal_con_columna_presente_no_avisa() -> None:
    """La dirección positiva, medida en vivo: con la columna, la corrida llega a `done`.

    Sin este test el gate anterior se satisface con un aviso que salta siempre, que sería peor que
    no avisar: entrena a ignorarlo.
    """
    columnas = SIN_PERIODO | {"period"}

    assert StabilityConfig(temporal_axis="period").requisitos_incumplidos(columnas) == ()


def test_eje_temporal_sin_saber_las_columnas_no_afirma_nada() -> None:
    """`None` significa «no se sabe», no «no hay» (D-INV-4).

    Es la regresión que importa: afirmar sin el dato reintroduce el falso positivo más caro, el
    mismo que costó el rediseño de la firma de `check_dataset` en `1.9.0`.
    """
    assert StabilityConfig(temporal_axis="period").requisitos_incumplidos(None) == ()


def test_eje_temporal_apagado_no_avisa() -> None:
    """Con el eje en `none` el motor ni busca la columna, así que no hay nada que exigir."""
    assert StabilityConfig(temporal_axis="none").requisitos_incumplidos(SIN_PERIODO) == ()


def test_columna_temporal_declarada_la_gobierna_el_preflight_de_columnas() -> None:
    """Con `temporal_column` fijada no se emite requisito: ya la vigila `column_role: input`.

    Duplicarlo daría dos avisos sobre el mismo campo, uno de ellos peor redactado.
    """
    cfg = StabilityConfig(temporal_axis="period", temporal_column="mi_periodo")

    assert cfg.requisitos_incumplidos(SIN_PERIODO) == ()


def test_columna_temporal_ambigua_avisa_y_nombra_las_candidatas() -> None:
    """Dos candidatas: el motor se niega a elegir, y el aviso dice entre cuáles."""
    requisitos = StabilityConfig(temporal_axis="period").requisitos_incumplidos(
        SIN_PERIODO | {"period", "cohorte"}
    )

    assert [r.path for r in requisitos] == ["temporal_column"]
    assert "«cohorte»" in requisitos[0].message
    assert "«period»" in requisitos[0].message


def test_los_nombres_candidatos_son_los_mismos_que_mira_el_motor() -> None:
    """D-INV-9: una constante compartida vive en un sitio, o el aviso acaba mintiendo.

    Estaba triplicada (`evaluator.py`, `step.py` y la que necesitaba el aviso). El test mira las
    dos referencias que quedan y exige que sean el mismo objeto, no dos listas iguales hoy.
    """
    from nikodym.stability import evaluator, step

    assert evaluator.TEMPORAL_CANDIDATE_NAMES is TEMPORAL_CANDIDATE_NAMES
    assert step.TEMPORAL_CANDIDATE_NAMES is TEMPORAL_CANDIDATE_NAMES


# ── las demás invariantes implementadas ───────────────────────────────────────────────────────
def test_comparaciones_repetidas_avisan() -> None:
    cfg = StabilityConfig(comparisons=("dev_vs_holdout", "dev_vs_holdout"))
    requisitos = cfg.requisitos_incumplidos(SIN_PERIODO)

    assert "comparisons" in [r.path for r in requisitos]


def test_particiones_de_desempeno_repetidas_avisan() -> None:
    cfg = PerformanceConfig(partitions=("desarrollo", "desarrollo"))

    assert [r.path for r in cfg.requisitos_incumplidos(None)] == ["partitions"]


def test_familias_de_validacion_vacias_avisan() -> None:
    """`validation` corre PENÚLTIMO: sin esto, un `if` de una línea cobra la corrida entera."""
    assert [r.path for r in ValidationConfig(families=()).requisitos_incumplidos(None)] == [
        "families"
    ]


def test_familias_de_validacion_pobladas_no_avisan() -> None:
    assert ValidationConfig().requisitos_incumplidos(None) == ()


def test_fecha_de_corte_oot_ilegible_avisa() -> None:
    """`oot_from` es un `str` libre y sólo se parsea dentro del PRIMER paso del pipeline."""
    cfg = TemporalSplitConfig(date_col="fecha", oot_from="no-es-fecha")

    assert [r.path for r in cfg.requisitos_incumplidos(None)] == ["oot_from"]


def test_fecha_de_corte_oot_valida_no_avisa() -> None:
    cfg = TemporalSplitConfig(date_col="fecha", oot_from="2024-07-01")

    assert cfg.requisitos_incumplidos(None) == ()


@pytest.mark.parametrize("vacia", ["", "   ", "nan"])
def test_fecha_de_corte_oot_vacia_avisa_aunque_pandas_no_levante(vacia: str) -> None:
    """El caso más probable de todos se iba en silencio: `pandas` devuelve `NaT` sin levantar.

    Hallado por la auditoría previa a `1.10.0`: atrapar `ValueError` no basta, porque
    `pd.Timestamp("")` y `pd.Timestamp("nan")` **no** levantan — devuelven `NaT`—, así que un
    `oot_from` en blanco pasaba el chequeo cuya razón de existir es justo esa fecha.
    """
    cfg = TemporalSplitConfig(date_col="fecha", oot_from=vacia)

    requisitos = cfg.requisitos_incumplidos(None)

    assert [r.path for r in requisitos] == ["oot_from"]
    # Copy público: un valor en blanco no se cita entre comillas, se nombra la carencia.
    if vacia.strip() == "":
        assert requisitos[0].message.startswith("Falta la fecha desde la que empieza el OOT")
        assert "«" not in requisitos[0].message


# ── la integración: lo que ve quien llama a la superficie pública ─────────────────────────────
def test_check_dataset_publica_el_requisito_con_su_ruta_absoluta() -> None:
    """D-INV-5: el dominio declara rutas relativas y el recorrido les pone su prefijo.

    Sin la ruta absoluta el formulario no puede saltar al campo, que es lo que hace útil al aviso.
    """
    cargar_configs_de_dominio()
    config = NikodymConfig.model_validate(
        {"name": "t", "stability": StabilityConfig(temporal_axis="period").model_dump()}
    )

    veredicto = check_dataset(config, sorted(SIN_PERIODO))

    requisitos = [m for m in veredicto.mismatches if m.kind == "unmet_requirement"]
    assert [m.path for m in requisitos] == ["stability.temporal_axis"]
    assert veredicto.compatible is False


def test_un_requisito_incumplido_no_es_una_columna_que_falte() -> None:
    """Los dos tipos conviven en el mismo canal sin confundirse (D-INV-2)."""
    cargar_configs_de_dominio()
    config = NikodymConfig.model_validate(
        {"name": "t", "stability": StabilityConfig(temporal_axis="period").model_dump()}
    )

    veredicto = check_dataset(config, sorted(SIN_PERIODO))

    tipos = {m.kind for m in veredicto.mismatches}
    assert "unmet_requirement" in tipos
    assert "missing_column" not in tipos


# ── cobertura declarada (D-INV-7), con el alcance DERIVADO del catálogo (D-ABA-9) ────────────
#: Secciones del formulario SIN invariantes previas declaradas, cada una con su razón TÉCNICA.
#:
#: Una lista corta y sin explicación se lee como cobertura total (D-PRE-4). Lo que dice esta tabla
#: es que se miró cada sección y se decidió, no que se olvidaron.
#:
#: 🔴 **Aquí ya no cabe «fuera del alcance F1», y ése es el cambio de D-ABA-9.** Esa razón la da
#: ahora el catálogo de trabajos o no la da nadie: una sección que ningún trabajo **disponible**
#: declara está exenta por derivación, y nadie tiene que acordarse de escribirlo. Hasta el
#: 2026-08-04 diez filas alegaban esa frase, y para cuatro de ellas **había dejado de ser cierta**
#: el día que sus trabajos pasaron a disponibles — la exención llevaba tiempo siendo falsa y una
#: lista escrita a mano no tenía forma de notarlo. Ése *es* el defecto que esto cierra.
EXENTAS: dict[str, str] = {
    # --- camino F1: miradas una por una en el censo del 2026-07-29 ---
    "selection": "sus 4 campos son `derived`: la candidatura la produce binning al correr",
    "model": "sus overrides se contrastan contra lo que sobrevivió a selection, que aún no existe",
    "scorecard": "sin invariantes medidas: el censo del 2026-07-29 no encontró ninguna",
    "calibration": "sus invariantes YA están en su `model_validator`, que es el sitio correcto",
    "report": "su invariante (`required_sections`) es ENTRE secciones, no de una: D-INV-8",
    # --- provisiones: entraron al alcance al derivarlo, y tienen razón propia MEDIDA ---
    #
    # Las dos alegaban «fuera del alcance F1» y lo perdieron con D-ABA-9. Su razón real es la misma
    # que la de `calibration`, y se midió el 2026-08-04 al cerrar D-MAX-3: lo que estas secciones
    # se exigen a sí mismas lo levanta su `model_validator` —o sea, el config ni siquiera se
    # construye—, y lo que exigen de OTRA sección lo ve el DAG, que además lo dice mejor porque
    # conoce el orden de los pasos. Declararlo aquí duplicaría un diagnóstico existente, que es la
    # misma razón por la que `survival` no declara `model_raw`.
    "provisioning": (
        "sus invariantes las levanta su `model_validator` (fuentes iguales, regla sin su fuente) "
        "y las que cruzan secciones las ve el DAG por su `requires` dinámico: medido en D-MAX-3"
    ),
    # `provisioning_internal` SALIÓ de esta tabla en 1.11.0: desde D-AMB-2 declara su propia
    # invariante —dos columnas candidatas a cartera y ninguna elegida—, que es justo lo que su
    # exención decía que no tenía. El gate lo cazó el día del cambio.
}


def _secciones_del_catalogo() -> frozenset[str]:
    """Las secciones que algún trabajo DISPONIBLE declara — el alcance del preflight (D-ABA-9).

    🔴 **Se deriva, no se escribe.** El alcance era una frase repetida en diez filas de `EXENTAS`, y
    cuatro de ellas habían dejado de ser ciertas sin que nada lo notara: sus trabajos pasaron a
    disponibles y la lista escrita a mano siguió eximiéndolas. Derivarlo del catálogo hace que una
    sección entre al alcance **el mismo día** en que su trabajo se habilita.

    ⚠️ Sólo cuentan los trabajos **disponibles**: uno que no se puede iniciar no le exige nada a
    nadie. Medido, los dos no disponibles no aportan ninguna sección que no esté ya en uno
    disponible, así que la derivación no depende de cuál se habilite después.

    ⚠️ **Y esto dice qué se EXIGE, no qué se permite.** `validation` está fuera del catálogo —el
    formulario no la ofrece (D-JOB-18)— y sin embargo implementa el protocolo: implementar de más
    es gratis y correcto. Por eso el candado «ninguna exención sobra» se aplica sólo a la lista
    escrita, nunca a este conjunto, que no es una lista donde algo pueda sobrar.
    """
    from nikodym.ui.jobs import list_jobs

    return frozenset(
        seccion
        for job in list_jobs()
        if job["status"] == "available"
        for seccion in job["sections"]
    )


#: Los TRES métodos con que una sección puede declarar lo que se exige a sí misma.
#:
#: ⚠️ Son los que **AÑADEN** avisos. Los dos supresores —`columnas_inactivas` y
#: `columnas_que_produce`— quedan fuera a propósito: declarar que una columna no se lee no es
#: declarar una invariante, y contarlos aquí daría por cubierta una sección que no comprueba nada.
#:
#: El de contexto entró con D-ABA-8. Antes el criterio miraba sólo el primero, y por eso una
#: sección que declarase su invariante por uno de los hermanos seguía contando como incumplidora
#: —el caso de `binning`, que lleva desde D-PERF-4 declarando la suya por el perfil—.
_METODOS_QUE_DECLARAN: tuple[str, ...] = (
    METODO_REQUISITOS,
    "requisitos_incumplidos_por_perfil",
    "requisitos_incumplidos_por_contexto",
)


def _secciones_con_protocolo(seccion: type[BaseModel]) -> bool:
    """¿La sección —o un sub-modelo suyo— declara el protocolo, por cualquiera de sus vías?"""
    vistos: set[type[BaseModel]] = set()
    pendientes: list[type[BaseModel]] = [seccion]
    while pendientes:
        modelo = pendientes.pop()
        if modelo in vistos:
            continue
        vistos.add(modelo)
        if any(callable(getattr(modelo, metodo, None)) for metodo in _METODOS_QUE_DECLARAN):
            return True
        for info in modelo.model_fields.values():
            for arg in (info.annotation, *getattr(info.annotation, "__args__", ())):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    pendientes.append(arg)
                for anidado in getattr(arg, "__args__", ()):
                    if isinstance(anidado, type) and issubclass(anidado, BaseModel):
                        pendientes.append(anidado)
    return False


def test_cada_seccion_declara_su_politica_de_invariantes() -> None:
    """Toda sección de dominio implementa el protocolo o está exenta CON SU RAZÓN (D-INV-7).

    El gate mide contra el registro real de secciones —no contra una lista escrita al lado—, así
    que una sección nueva entra aquí sola y obliga a decidir.
    """
    secciones = cargar_configs_de_dominio()
    en_catalogo = _secciones_del_catalogo()
    sin_politica = [
        nombre
        for nombre, modelo in sorted(secciones.items())
        if nombre in en_catalogo and not _secciones_con_protocolo(modelo) and nombre not in EXENTAS
    ]

    assert not sin_politica, (
        f"Secciones sin política de invariantes previas: {sin_politica}. Implementa "
        f"`{METODO_REQUISITOS}(columnas)` en su config —lo que su motor exige y hoy sólo "
        "se descubre corriendo— o decláralas en `EXENTAS` **con la razón**. Una sección sin "
        "decisión escrita se lee como cobertura, y es justo lo que esta enmienda vino a evitar."
    )


def test_ninguna_exencion_sobra() -> None:
    """Una exención que ya no aplica es una mentira que envejece sola.

    Si una sección exenta implementa el protocolo, deja de existir, **o sale del catálogo**, la fila
    debe salir. El tercer caso es el candado de D-ABA-9: una sección fuera del alcance ya está
    exenta por derivación, y escribirla además sería mantener a mano lo que el catálogo decide.
    """
    secciones = cargar_configs_de_dominio()
    en_catalogo = _secciones_del_catalogo()
    sobrantes = [
        nombre
        for nombre in EXENTAS
        if nombre not in secciones
        or _secciones_con_protocolo(secciones[nombre])
        or nombre not in en_catalogo
    ]

    assert not sobrantes, (
        f"Exenciones que ya no corresponden: {sobrantes}. O la sección desapareció, o ya declara "
        f"sus invariantes, o ningún trabajo disponible la usa —y entonces su exención se DERIVA "
        f"del catálogo (D-ABA-9)—: en los tres casos, saca su fila de `EXENTAS`."
    )


def test_ninguna_exencion_escrita_alega_estar_fuera_del_alcance() -> None:
    """🔴 El segundo candado de D-ABA-9, y sin él lo demás no sirve de nada.

    «Fuera del alcance» la dice el catálogo o no la dice nadie. Sin este gate, la lista escrita
    seguiría pudiendo eximir a mano lo que el catálogo ya incluye — que es exactamente el agujero
    por el que cuatro secciones de provisiones estuvieron exentas por una frase que había dejado de
    ser cierta, sin que ningún test pudiera notarlo.
    """
    culpables = {
        nombre: razon
        for nombre, razon in EXENTAS.items()
        if "fuera del alcance" in razon.lower() or "fuera de alcance" in razon.lower()
    }

    assert not culpables, (
        f"Estas exenciones alegan estar fuera del alcance: {sorted(culpables)}. Esa razón la da "
        "el catálogo de trabajos, no esta lista: si ningún trabajo disponible usa la sección, "
        "quita su fila y la exención se deriva sola. Si alguno la usa, la razón tiene que ser "
        "TÉCNICA."
    )


def test_el_alcance_derivado_no_es_vacuo() -> None:
    """Un alcance vacío eximiría a todo el mundo y dejaría los dos gates de arriba en verde."""
    en_catalogo = _secciones_del_catalogo()

    assert len(en_catalogo) >= 10, f"sólo {len(en_catalogo)} secciones en el alcance: {en_catalogo}"
    for ancla in ("data", "binning", "survival", "provisioning_cmf"):
        assert ancla in en_catalogo, f"«{ancla}» debería estar en el alcance del preflight"
    # Y algo tiene que quedar FUERA: si el alcance fuera todo, la derivación no distinguiría nada.
    secciones = set(cargar_configs_de_dominio())
    assert secciones - en_catalogo, "ninguna sección queda fuera del alcance: la derivación no mide"


@pytest.mark.parametrize(
    "config",
    [
        StabilityConfig(),
        PerformanceConfig(),
        ValidationConfig(),
        TemporalSplitConfig(date_col="fecha", oot_from="2024-07-01"),
    ],
    ids=["stability", "performance", "validation", "temporal_split"],
)
def test_el_protocolo_acepta_columnas_desconocidas(config: BaseModel) -> None:
    """Toda implementación tolera `columnas=None` sin reventar (contrato de D-INV-4)."""
    requisitos = config.requisitos_incumplidos(None)  # type: ignore[attr-defined]

    assert isinstance(requisitos, tuple)


# ── `survival`: grilla temporal e intervalos de KM (D-INV-1, ampliación del 2026-08-03) ──────
#
# 🔴 Es la invariante más cara medida hasta ahora, y era invisible: con los dos campos de la
# grilla en su default, la corrida **aborta después** de cargar el archivo, ajustar el modelo y
# calcular la term-structure. Se midió con corridas reales sobre el preset F4 —los cuatro métodos
# abortan—, no leyendo el código: el fallback lo resuelve el paso, no cada motor.

_SURVIVAL_MINIMO: dict[str, object] = {"input": {"duration_col": "t", "event_col": "e"}}


def _survival(**extra: object) -> SurvivalConfig:
    return SurvivalConfig.model_validate({**_SURVIVAL_MINIMO, **extra})


def _rutas(config: BaseModel) -> list[str]:
    return [r.path for r in config.requisitos_incumplidos(None)]  # type: ignore[attr-defined]


def test_survival_sin_grilla_avisa_antes_de_pagar_la_corrida() -> None:
    """Los dos campos en su default: el motor cae a los tiempos observados y aborta al final."""
    assert _rutas(_survival()) == ["time_grid.horizon_periods"]


@pytest.mark.parametrize(
    "grilla",
    [{"horizon_periods": 12}, {"evaluation_times": [1.0, 2.0]}],
    ids=["horizonte", "tiempos"],
)
def test_declarar_CUALQUIERA_de_los_dos_basta(grilla: dict[str, object]) -> None:  # noqa: N802
    """Control positivo: el `elif` del step los toma en orden, así que uno de los dos alcanza.

    Sin esto, una condición con `and` invertido —o un `or`— exigiría los dos y avisaría sobre
    configs que corren perfectamente, que es el falso positivo que este protocolo no puede darse.
    """
    assert _rutas(_survival(time_grid=grilla)) == []


def test_con_el_flag_apagado_NO_se_avisa_de_nada() -> None:  # noqa: N802
    """🔴 `fail_on_falta_dato` es parte de la condición, no un detalle.

    Medido: con el flag en `False` la corrida llega a `done` y registra el aviso. Avisar ahí sería
    un falso positivo, y el mensaje —que dice que la corrida se detendrá— sería literalmente falso.
    """
    assert _rutas(_survival(fail_on_falta_dato=False)) == []


def test_kaplan_meier_sin_intervalos_avisa_y_los_otros_metodos_no() -> None:
    """`confidence_level=None` es el DEFAULT, así que un KM de fábrica aborta con la grilla puesta.

    ⚠️ La condición es el `or` completo: `level=None` con `transform="loglog"` **es construible**
    —el validador sólo prohíbe el inverso— y emite el aviso igual. Y va acotada a `kaplan_meier`:
    `_global_warnings` sólo lo emite ese motor.
    """
    con_grilla = {"horizon_periods": 12}
    assert _rutas(_survival(method="kaplan_meier", time_grid=con_grilla)) == [
        "kaplan_meier.confidence_level"
    ]
    assert _rutas(
        _survival(
            method="kaplan_meier",
            time_grid=con_grilla,
            kaplan_meier={"confidence_level": None, "confidence_transform": "loglog"},
        )
    ) == ["kaplan_meier.confidence_level"]
    # Control: declarados los dos, no hay aviso; y ningún otro método lo emite.
    assert (
        _rutas(
            _survival(
                method="kaplan_meier",
                time_grid=con_grilla,
                kaplan_meier={"confidence_level": 0.95, "confidence_transform": "loglog"},
            )
        )
        == []
    )
    for metodo in ("discrete_hazard", "cox_ph"):
        assert _rutas(_survival(method=metodo, time_grid=con_grilla)) == [], metodo


def test_los_dos_avisos_pueden_concurrir() -> None:
    """El motor los nombra a los dos en su mensaje de aborto; aquí salen los dos requisitos."""
    assert _rutas(_survival(method="kaplan_meier")) == [
        "time_grid.horizon_periods",
        "kaplan_meier.confidence_level",
    ]


def test_el_preset_de_fabrica_que_usa_survival_no_gana_ningun_aviso() -> None:
    """🔴 Control negativo del conjunto: el F4 declara su grilla y sus intervalos a propósito.

    Si esta invariante tuviera un falso positivo, el ejemplo que la aplicación ofrece aparecería
    avisado nada más abrirlo — que es exactamente cómo se aprende a ignorar un aviso.
    """
    from nikodym.ui.presets import get_preset

    cargar_configs_de_dominio()
    config = NikodymConfig.model_validate(get_preset("f4-ifrs9-retail")["config"])
    assert config.survival is not None
    assert _rutas(config.survival) == []
