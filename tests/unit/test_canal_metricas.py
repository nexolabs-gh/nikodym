"""Gates del canal de métricas ``study.results`` (D-GOB-1…5; SDD-01 §6).

Preespecificados en §6 de ``docs/design/_ENMIENDA-GOBERNANZA-ALCANZABLE.md`` **antes** de escribir
el productor, a propósito: un gate escrito después del arreglo tiende a describirlo en vez de
vigilarlo.

Los tests 4 y 5 de esa lista —el ``model_card.json`` en disco y los dos trails separados— viven en
``test_run_dir.py``: pertenecen al layout de la corrida (D-GOB-6/7), no al canal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _ui_f1 import full_f1_config, write_behavior_parquet

import nikodym
from nikodym.core.exceptions import ConfigError
from nikodym.core.study import Study
from nikodym.governance.config import GovernanceConfig
from nikodym.governance.exceptions import GovernanceError
from nikodym.governance.model_card import ModelCardBuilder
from nikodym.testing.metrics import (
    DECLARED_METRICS,
    DOMAINS_WITHOUT_METRICS,
    is_declared_metric,
    orchestrable_domains,
)
from nikodym.tracking.recorder import _metric_items


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita OR-Tools dentro del proceso pytest para los tests in-process con binning."""
    del fake_binning_process


@pytest.fixture
def fuente_f1(tmp_path: Path) -> str:
    """Frame de comportamiento de 30 filas, el mismo que usa el resto de la capa F1."""
    source = tmp_path / "behavior.parquet"
    write_behavior_parquet(source)
    return str(source)


def _corrida_f1(fuente: str, *, min_rows_por_particion: int | None = None) -> Study:
    """Corre el pipeline F1 completo por la puerta pública ``nikodym.run``."""
    config = full_f1_config(fuente)
    if min_rows_por_particion is not None:
        config = config.model_copy(
            update={
                "performance": config.performance.model_copy(
                    update={"min_rows_per_partition": min_rows_por_particion}
                )
            }
        )
    return nikodym.run(config)


# ─────────────────── 1. el canal se llena de verdad, sobre la puerta pública ───────────────────


def test_canal_se_llena_con_las_claves_declaradas_por_dominio(fuente_f1: str) -> None:
    """Una corrida F1 real deja ``results['metrics']`` lleno y con las claves de D-GOB-4.

    El control negativo de este gate —borrar el ``metrics()`` de un dominio— está en
    :func:`test_borrar_el_productor_de_un_dominio_nombra_ese_dominio`, que comprueba además que el
    rojo **nombra el dominio** en vez de fallar genéricamente.
    """
    # `min_rows_per_partition=4` para que `performance` sea evaluable con 30 filas: sin eso sus
    # tres particiones salen `not_evaluable` y el dominio no aporta clave (que es el test 6).
    study = _corrida_f1(fuente_f1, min_rows_por_particion=4)

    assert study.run_context.status == "done"
    metricas = study.results["metrics"]
    assert metricas, "una corrida F1 completa no puede dejar el canal vacío"

    dominios_activos = {clave.split(".", 1)[0] for clave in metricas}
    esperados = {
        "data",
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
    }
    assert dominios_activos == esperados

    for clave in metricas:
        dominio, _, nombre = clave.partition(".")
        assert is_declared_metric(dominio, nombre), (
            f"'{clave}' no está declarada en nikodym.testing.metrics. Publicar una métrica que "
            "nadie declaró la imprime en cada model card sin que ningún SDD la respalde."
        )

    for dominio in esperados - {"performance"}:
        publicadas = {
            clave.partition(".")[2] for clave in metricas if clave.startswith(f"{dominio}.")
        }
        faltantes = set(DECLARED_METRICS[dominio]) - publicadas
        assert not faltantes, f"el dominio '{dominio}' no publicó {sorted(faltantes)}"


def test_borrar_el_productor_de_un_dominio_nombra_ese_dominio(
    fuente_f1: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control negativo del test 1: sin ``metrics()`` en un dominio, el gate lo nombra a él.

    Lo que se vigila no es «hubo un rojo» sino que el rojo IDENTIFICA al dominio mudo. Un gate que
    sólo dijera «faltan métricas» obligaría a bisecar ocho pasos para saber cuál dejó de producir.
    """
    from nikodym.calibration.step import CalibrationStep

    monkeypatch.delattr(CalibrationStep, "metrics")
    study = _corrida_f1(fuente_f1, min_rows_por_particion=4)

    metricas = study.results["metrics"]
    mudos = {"calibration"} - {clave.split(".", 1)[0] for clave in metricas}
    assert mudos == {"calibration"}
    assert not any(clave.startswith("calibration.") for clave in metricas)


# ─────────────── 2. la forma es la única que los dos consumidores aceptan ───────────────


def test_los_dos_consumidores_leen_las_mismas_claves(fuente_f1: str) -> None:
    """``ModelCardBuilder.build`` y ``_metric_items`` devuelven lo mismo sobre el mismo ``results``.

    Este es el gate que impide que la contradicción medida en §2.1 de la enmienda se reabra en
    silencio: ``governance`` exige un plano ``dict[str, float]`` y ``tracking`` aplana lo anidado,
    así que sólo la forma plana satisface a ambos. Hoy no rompe nadie porque el canal se llena
    plano; si alguien lo llenara anidado, el model card fallaría **en ejecución**.
    """
    study = _corrida_f1(fuente_f1, min_rows_por_particion=4)

    card = _card_sin_trail(study)
    del_tracking, _ = _metric_items(study.results)

    assert set(card.metrics) == set(del_tracking)
    assert card.metrics == del_tracking
    assert card.metrics, "el model card no puede salir sin métricas tras una corrida completa"


def test_una_seccion_anidada_desde_un_dominio_rompe_governance(fuente_f1: str) -> None:
    """Control negativo del test 2: la forma anidada levanta ``GovernanceError``.

    Se inyecta directamente en ``results`` —no por un dominio— porque el núcleo ya rechaza un
    ``dict`` como valor de métrica (``_como_float_publicable``): son dos barreras distintas y esta
    comprueba la del consumidor, que es la que la enmienda midió.
    """
    study = _corrida_f1(fuente_f1, min_rows_por_particion=4)
    study.results["metrics"] = {"performance": {"auc_oot": 0.78}}

    with pytest.raises(GovernanceError, match="performance"):
        _card_sin_trail(study)

    # …y el otro consumidor la acepta sin quejarse. Esa asimetría ES el defecto latente.
    aplanadas, _ = _metric_items(study.results)
    assert aplanadas == {"performance.auc_oot": 0.78}


def test_el_nucleo_rechaza_una_clave_con_punto_del_dominio(
    fuente_f1: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El prefijo lo pone ``core``: un dominio que lo componga rompe la corrida (D-GOB-2).

    Se comprueba sobre el ``Study`` devuelto y no con ``pytest.raises``: ``nikodym.run`` **captura**
    el ``NikodymError`` y devuelve el estudio parcial con ``status="failed"`` (``api.py``), que es
    el contrato público. Medido, no supuesto: exigir la excepción aquí habría dado un verde falso
    sobre un camino que la puerta pública no recorre.
    """
    from nikodym.scorecard.step import ScorecardStep

    monkeypatch.setattr(
        ScorecardStep,
        "metrics",
        lambda self, study: {"scorecard.n_variables": 2.0},
    )
    study = _corrida_f1(fuente_f1)

    assert study.run_context.status == "failed"
    error = study.run_context.error
    assert error is not None
    assert error.step == "scorecard"
    assert "con punto" in error.message
    assert error.type == ConfigError.__name__

    # Y por la puerta directa —`Study.run`, sin el envoltorio de producto— sí propaga.
    with pytest.raises(ConfigError, match="con punto"):
        Study(full_f1_config(fuente_f1)).run()


# ─────────────── 3. bidireccional sobre D-GOB-4: en los DOS sentidos ───────────────


def test_toda_metrica_declarada_existe_en_el_codigo(fuente_f1: str) -> None:
    """Sentido A: quitar del código una métrica que el registro declara → rojo.

    Recorre la declaración y exige que la corrida la produzca. Es el sentido que detecta que
    alguien dejó de publicar algo que el registro sigue prometiendo.
    """
    study = _corrida_f1(fuente_f1, min_rows_por_particion=4)
    publicadas = set(study.results["metrics"])

    faltantes: list[str] = []
    for dominio in ("data", "binning", "selection", "model", "scorecard", "calibration"):
        for nombre in DECLARED_METRICS[dominio]:
            if f"{dominio}.{nombre}" not in publicadas:
                faltantes.append(f"{dominio}.{nombre}")
    assert not faltantes, f"declaradas en el registro pero ausentes de la corrida: {faltantes}"

    # `performance` se declara por plantilla: se exige que se resuelva al menos una vez.
    assert any(clave.startswith("performance.auc_") for clave in publicadas)


def test_todo_dominio_orquestable_esta_clasificado() -> None:
    """Sentido B: un dominio NUEVO sin lista declarada → rojo.

    Es el sentido que un gate ingenuo omite. Comprobar sólo las métricas que ya existen afirma
    «lo declarado está», no «está todo lo que debería»: un dominio nuevo entraría mudo y nadie se
    enteraría. Es la lección de D-VIS-6, aplicada aquí antes de que el hueco exista.
    """
    sin_clasificar = [
        dominio
        for dominio in orchestrable_domains()
        if dominio not in DECLARED_METRICS and dominio not in DOMAINS_WITHOUT_METRICS
    ]
    assert not sin_clasificar, (
        "Dominios orquestables que no declaran su lista de métricas ni su razón para no tenerla: "
        f"{sin_clasificar}. Añadirlos a DECLARED_METRICS o a DOMAINS_WITHOUT_METRICS "
        "(nikodym/testing/metrics.py) con su motivo escrito."
    )

    solapados = set(DECLARED_METRICS) & set(DOMAINS_WITHOUT_METRICS)
    assert not solapados, f"dominios en las dos listas a la vez: {sorted(solapados)}"

    conocidos = set(orchestrable_domains())
    fantasmas = (set(DECLARED_METRICS) | set(DOMAINS_WITHOUT_METRICS)) - conocidos
    assert not fantasmas, f"clasificados pero no orquestables: {sorted(fantasmas)}"

    for dominio, razon in DOMAINS_WITHOUT_METRICS.items():
        assert razon.strip(), f"'{dominio}' declara no publicar métricas sin escribir por qué"


# ─────────────────────── 6. la ausencia no se rellena ───────────────────────


def test_una_metrica_no_evaluable_se_omite_en_vez_de_valer_cero(fuente_f1: str) -> None:
    """Con las particiones bajo el mínimo, ``performance`` no publica NINGUNA clave.

    Es el caso real de una cartera corta: las tres particiones salen ``not_evaluable`` y la card
    trae ``auc=None``. Publicar ``0.0`` diría «AUC de 0.0» —peor que no decir nada— y publicar la
    clave con ``None`` rompería a ``governance``, que exige ``float`` finito.
    """
    study = _corrida_f1(fuente_f1)  # min_rows_per_partition por defecto = 30 > 20/4/6

    card_perf = study.artifacts.get("performance", "card")
    evaluables = [
        valor
        for metricas in card_perf.max_metrics_by_partition.values()
        for valor in metricas.values()
        if valor is not None
    ]
    assert not evaluables, "el fixture debe dejar performance no evaluable para este gate"

    metricas = study.results["metrics"]
    assert not [clave for clave in metricas if clave.startswith("performance.")]
    assert all(valor == valor for valor in metricas.values())  # ningún NaN
    assert all(isinstance(valor, float) for valor in metricas.values())

    # …y el resto del canal sigue lleno: la ausencia de un dominio no vacía a los demás.
    assert {clave.split(".", 1)[0] for clave in metricas} == {
        "data",
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
    }


def test_publicar_cero_en_lugar_de_la_ausencia_es_rojo(fuente_f1: str) -> None:
    """Control negativo del test 6: rellenar con ``0.0`` lo no evaluable se detecta.

    Inyecta el defecto exacto que D-GOB-2 prohíbe —el productor devuelve ``0.0`` donde la card
    trae ``None``— y comprueba que el gate anterior se pondría rojo. Sin este control, aquel test
    pasaría igual si alguien cambiara la omisión por un cero.
    """
    from nikodym.performance.step import PerformanceStep

    original = PerformanceStep.metrics

    def metrics_que_rellena(self: Any, study: Study) -> dict[str, float | None]:
        card = study.artifacts.get("performance", "card")
        return {
            f"{nombre}_{particion}": (valores.get(nombre) or 0.0)
            for particion, valores in card.max_metrics_by_partition.items()
            for nombre in ("auc", "gini", "ks")
        }

    try:
        PerformanceStep.metrics = metrics_que_rellena  # type: ignore[method-assign]
        study = _corrida_f1(fuente_f1)
    finally:
        PerformanceStep.metrics = original  # type: ignore[method-assign]

    rellenadas = {
        clave: valor
        for clave, valor in study.results["metrics"].items()
        if clave.startswith("performance.")
    }
    assert rellenadas, "el defecto inyectado debe hacerse visible en el canal"
    assert set(rellenadas.values()) == {0.0}, (
        "el control negativo debe producir exactamente el defecto que D-GOB-2 prohíbe: "
        "ceros donde la card dice que no hay medición"
    )


def test_nan_e_infinito_se_omiten_igual_que_la_ausencia(
    fuente_f1: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NaN`` e ``inf`` son ausencias, no valores: se omiten (D-GOB-2).

    🔴 Este gate existe porque el CONTROL NEGATIVO de la capa lo exigió. La primera versión del
    test 6 sólo ejercía la rama ``None`` —que es como llega una partición ``not_evaluable``—, así
    que cambiar el descarte de no-finitos por un ``0.0`` en ``core`` NO ponía rojo a nadie: la
    rama existía sin oráculo. Un ``NaN`` publicado es alcanzable de verdad (una división por cero
    en una reducción de dominio), y ``governance`` lo rechazaría con ``GovernanceError`` en
    ejecución, así que la omisión tiene que estar vigilada aquí.
    """
    from nikodym.model.step import ModelStep

    monkeypatch.setattr(
        ModelStep,
        "metrics",
        lambda self, study: {
            "n_final_features": float("nan"),
            "no_declarada_inf": float("inf"),
            "no_declarada_menos_inf": float("-inf"),
        },
    )
    study = _corrida_f1(fuente_f1)

    assert study.run_context.status == "done"
    metricas = study.results["metrics"]
    assert not [clave for clave in metricas if clave.startswith("model.")], (
        "NaN e inf deben omitirse, no publicarse ni convertirse en 0.0"
    )

    # El consumidor estricto lo confirma: con un NaN dentro habría levantado.
    card = _card_sin_trail(study)
    assert all(clave.split(".", 1)[0] != "model" for clave in card.metrics)


def test_un_valor_de_tipo_equivocado_no_se_silencia(
    fuente_f1: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un ``str`` o un ``bool`` es contrato roto por el dominio, no una ausencia (D-GOB-2).

    La distinción importa: omitir en silencio un tipo equivocado dejaría al dominio publicando
    nada sin que nadie se entere, mientras que ``governance`` levantaría después con un mensaje que
    no nombra al culpable. Aquí el error lo nombra.
    """
    from nikodym.data.step import DataStep

    monkeypatch.setattr(DataStep, "metrics", lambda self, study: {"n_rows": True})
    study = _corrida_f1(fuente_f1)

    assert study.run_context.status == "failed"
    error = study.run_context.error
    assert error is not None
    assert error.step == "data"
    assert "n_rows" in error.message


# ─────────────────────── metric_sections (D-GOB-3/5) ───────────────────────


def test_metric_sections_llega_un_nivel_por_dominio_sin_aplanar(fuente_f1: str) -> None:
    """``results['metric_sections'][dominio]`` copia la puerta CT-2 tal cual (D-GOB-3)."""
    study = _corrida_f1(fuente_f1, min_rows_por_particion=4)

    secciones = study.results["metric_sections"]
    assert "performance" in secciones, "performance tiene un productor CT-2 vivo desde 1.x"
    assert "discrimination" in secciones["performance"]

    # Un nivel por dominio: no se aplana ni se fusiona entre dominios.
    card_perf = study.artifacts.get("performance", "card")
    assert secciones["performance"] is not card_perf.metric_sections

    # D-GOB-5: los dominios sin payload CT-2 no reciben la clave con un dict vacío.
    assert "data" not in secciones
    assert "binning" not in secciones
    assert "selection" not in secciones

    card = _card_sin_trail(study)
    assert card.metric_sections["performance"]["discrimination"]


def _card_sin_trail(study: Study) -> Any:
    """Construye el model card asumiendo el aviso de «trail no disponible».

    El aviso es correcto y deliberado: sin ``audit`` encendido no hay decisiones que copiar, y el
    card sale parcial. Se declara aquí con ``pytest.warns`` en vez de filtrarse, porque es
    exactamente el hueco que D-GOB-6/7 cierra escribiendo el trail dentro del ``run_dir``; taparlo
    con un filtro dejaría el gate ciego a que la ruta completa nunca se ejerció.
    """
    with pytest.warns(UserWarning, match="trail no disponible"):
        return ModelCardBuilder(_gobernanza()).build(study)


def _gobernanza() -> GovernanceConfig:
    """Config de gobernanza mínima y válida: ``purpose`` es obligatorio (SR 11-7)."""
    return GovernanceConfig(
        model_name="canal-metricas",
        purpose="Gate del canal de métricas (D-GOB).",
    )
