"""La corrida puntúa a la población through-the-door que no entra al ajuste (D-TTD-1…5).

Medido con la muestra pública SBA 7(a): 6.225 préstamos sin desenlace no recibían puntaje ni PD,
aunque SDD-31 §8 ya prometía que «se puntúan, no se ajustan».

- **D-TTD-1**: se puntúan las filas ``fuera_de_modelo`` con ``ttd=True`` —con
  ``ttd_includes_excluded=False``, ninguna— con la transformación de Holdout/OOT, sin reajustar
  nada; puntuarlas nunca detiene la corrida.
- **D-TTD-2**: cuatro claves aditivas ``out_of_model_*`` en cadena, con índice común.
- **D-TTD-3**: «Fuera del ajuste (TTD)» con su composición.
- **D-TTD-4**: PSI de representatividad frente a Desarrollo, con los cortes efectivos.
- **D-TTD-5**: las categorías que no existían en Desarrollo se cuentan por muestra y se dicen; el
  evento del trail dice el ``cat_unknown`` efectivo.

Estos tests usan **OptBinning real**, como los de D-FAL: la cartera sintética tiene indeterminados
repartidos en el tiempo y una categoría que sólo aparece después de la frontera OOT.

Contrato: ``docs/design/_ENMIENDA-PUNTUAR-POBLACION-TTD.md``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym
import nikodym.scorecard.step as scorecard_step
from nikodym.core.steps import entradas_fuera_del_ajuste
from nikodym.data.config import ColumnSplitConfig
from nikodym.guided.summaries import _linea_fuera_del_ajuste, _tabla_pd_por_muestra
from nikodym.report.builder import ReportBuilder
from nikodym.report.config import ReportConfig
from nikodym.report.document import PER_OBSERVATION_TABLES, table_title
from nikodym.scorecard.bundle import FittedScorecardBundle, _calibrate_array
from nikodym.stability.results import _psi_band

pytest.importorskip("optbinning")

_FRONTERA = "2021-07-01"
_CLAVES: tuple[tuple[str, str], ...] = (
    ("binning", "out_of_model_woe_frame"),
    ("model", "out_of_model_pd_frame"),
    ("scorecard", "out_of_model_score"),
    ("calibration", "out_of_model_calibrated_pd_frame"),
)
_ESPEJOS: dict[tuple[str, str], tuple[str, str]] = {
    ("binning", "out_of_model_woe_frame"): ("binning", "woe_frame"),
    ("model", "out_of_model_pd_frame"): ("model", "raw_pd_frame"),
    ("scorecard", "out_of_model_score"): ("scorecard", "score"),
    ("calibration", "out_of_model_calibrated_pd_frame"): ("calibration", "calibrated_pd_frame"),
}


# ───────────────────────── fixtures ─────────────────────────


def _cartera(
    n: int = 1600, *, indeterminados: float = 0.12, semilla: int = 7, muestra: bool = False
) -> pd.DataFrame:
    """Indeterminados repartidos en el tiempo y el segmento «D» sólo tras la frontera OOT."""
    rng = np.random.default_rng(semilla)
    fechas = pd.date_range("2019-01-01", "2021-12-31", periods=n)
    ingreso = rng.normal(size=n)
    antiguedad = rng.integers(1, 120, size=n).astype(float)
    segmento = rng.choice(np.array(["A", "B", "C"], dtype=object), size=n)
    tardias = np.asarray(fechas >= pd.Timestamp(_FRONTERA))
    segmento[tardias & (rng.uniform(size=n) < 0.2)] = "D"
    logit = -1.3 - 0.9 * ingreso + 0.01 * (60 - antiguedad) + (segmento == "C") * 0.6
    y = (rng.uniform(size=n) < 1.0 / (1.0 + np.exp(-logit))).astype(float)
    y[rng.uniform(size=n) < indeterminados] = np.nan
    datos = pd.DataFrame(
        {
            "loan_id": [f"op-{i:05d}" for i in range(n)],
            "fecha": fechas,
            "ingreso": ingreso,
            "antiguedad": antiguedad,
            "segmento": segmento,
            "bad_flag": y,
        }
    )
    if muestra:
        valores = np.where(tardias, "oot", np.where(rng.uniform(size=n) < 0.25, "ho", "dev"))
        otro = rng.uniform(size=n) < 0.06
        valores = np.where(otro, "otro", valores).astype(object)
        datos["muestra"] = valores
    return datos


def _guardar(datos: pd.DataFrame, tmp_path: Path, nombre: str) -> Path:
    ruta = tmp_path / f"{nombre}.parquet"
    datos.to_parquet(ruta)
    return ruta


def _puerta(ruta: Path, tmp_path: Path, nombre: str, **kwargs: Any) -> nikodym.Scorecard:
    argumentos: dict[str, Any] = {"date": "fecha", "oot_from": _FRONTERA}
    argumentos.update(kwargs)
    sc = nikodym.Scorecard(
        ruta,
        target="bad_flag",
        id="loan_id",
        name=nombre,
        run_dir=tmp_path / "run",
        **argumentos,
    )
    sc._echo = lambda _texto: None
    return sc


def _decisiones(project_dir: Path, regla: str) -> list[dict[str, Any]]:
    trail = project_dir / "run" / "audit_trail.jsonl"
    eventos = [json.loads(linea) for linea in trail.read_text(encoding="utf-8").splitlines()]
    return [
        e["payload"]
        for e in eventos
        if e["kind"] == "decision" and e["payload"].get("regla") == regla
    ]


@pytest.fixture(scope="module")
def _corrida(tmp_path_factory: pytest.TempPathFactory) -> tuple[nikodym.Scorecard, pd.DataFrame]:
    # Con alcance de módulo, el fixture de función del conftest que fija la semilla de hash todavía
    # no actuó: se aplica aquí con el mismo mecanismo.
    with pytest.MonkeyPatch.context() as parche:
        parche.setenv("PYTHONHASHSEED", "0")
        tmp_path = tmp_path_factory.mktemp("ttd")
        datos = _cartera()
        sc = _puerta(_guardar(datos, tmp_path, "cartera"), tmp_path, "ttd")
        sc.run()
    return sc, datos


def _fuera(datos: pd.DataFrame) -> pd.Index:
    return datos.index[datos["bad_flag"].isna()]


# ───────────────────────── D-TTD-1/2: las cuatro claves ─────────────────────────


def test_gate_las_filas_fuera_del_ajuste_se_puntuan_en_cuatro_claves(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
) -> None:
    """🔴 Test 1 y 7: la corrida termina `done`, cada clave trae las filas sin desenlace con el
    esquema de su espejo, el índice es disjunto del de las modelables, y el trail cuenta la
    composición."""
    sc, datos = _corrida
    st = sc.study
    assert st.run_context.status == "done", st.run_context.error
    fuera = _fuera(datos)
    assert len(fuera) > 50
    for clave in _CLAVES:
        frame = st.artifacts.get(*clave)
        espejo = st.artifacts.get(*_ESPEJOS[clave])
        assert set(frame.index) == set(fuera), clave
        assert list(frame.columns) == list(espejo.columns), clave
        assert frame.index.intersection(espejo.index).empty, clave
    (decision,) = _decisiones(Path(sc.project_dir), "puntuar_ttd_fuera_de_modelo")
    assert decision["accion"] == "puntuar_sin_ajustar"
    assert decision["valor"] == {
        "filas": len(fuera),
        "indeterminadas": len(fuera),
        "excluidas": 0,
        "con_desenlace": 0,
    }


def test_paridad_con_la_transformacion_de_holdout_en_todas_las_filas(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
) -> None:
    """🔴 Test 2: WoE, predictor lineal, puntaje y PD calibrada son los que dan los objetos ya
    ajustados aplicados a mano, también en las filas con una categoría no vista."""
    sc, datos = _corrida
    st = sc.study
    fuera = _fuera(datos)
    woe = st.artifacts.get("binning", "out_of_model_woe_frame").loc[fuera]
    # Una copia: `transform` reemplaza el conteo de categorías no vistas del binner publicado.
    proceso = copy.deepcopy(st.artifacts.get("binning", "process"))
    columnas = [c for c in woe.columns if c.endswith("__woe")]
    a_mano = proceso.transform(datos.loc[fuera, list(proceso.process_columns_)])
    pd.testing.assert_frame_equal(woe[columnas], a_mano[columnas])

    estimador = st.artifacts.get("model", "estimator")
    finales = list(estimador.final_woe_columns_)
    pd_frame = st.artifacts.get("model", "out_of_model_pd_frame").loc[fuera]
    np.testing.assert_allclose(
        pd_frame["linear_predictor"].to_numpy(),
        np.asarray(estimador.decision_function(woe[finales]), dtype="float64"),
        rtol=0,
        atol=1e-12,
    )

    tarjeta = st.artifacts.get("scorecard", "scorecard")
    puntaje = st.artifacts.get("scorecard", "out_of_model_score").loc[fuera]
    esperado = np.zeros(len(fuera))
    for feature, columna in zip(estimador.final_features_, finales, strict=True):
        filas = tarjeta.loc[tarjeta["feature"].eq(feature)]
        for posicion, valor in enumerate(woe[columna].to_numpy()):
            coincide = np.isclose(filas["woe"].to_numpy(dtype="float64"), valor, atol=1e-9)
            esperado[posicion] += float(filas.loc[coincide, "points"].iloc[0])
    np.testing.assert_allclose(puntaje["score"].to_numpy(dtype="float64"), esperado, atol=0)

    parametros = st.artifacts.get("calibration", "parameters").model_dump(mode="json")
    calibrada = st.artifacts.get("calibration", "out_of_model_calibrated_pd_frame").loc[fuera]
    np.testing.assert_allclose(
        calibrada["pd_calibrated"].to_numpy(),
        _calibrate_array(pd_frame["linear_predictor"].to_numpy(dtype="float64"), parametros),
        rtol=0,
        atol=1e-12,
    )


@pytest.mark.parametrize("metodo", ["intercept_offset", "platt_scaling", "isotonic"])
def test_paridad_de_la_calibracion_con_cada_metodo(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame], tmp_path: Path, metodo: str
) -> None:
    """🔴 Test 2b: el estado ajustado se aplica con los tres métodos; `transform` las filtraría."""
    sc, datos = _corrida
    config = sc.config.model_copy(
        update={"calibration": sc.config.calibration.model_copy(update={"method": metodo})}
    )
    st = nikodym.run(config, run_dir=tmp_path / metodo)
    assert st.run_context.status == "done", st.run_context.error
    fuera = _fuera(datos)
    pd_frame = st.artifacts.get("model", "out_of_model_pd_frame").loc[fuera]
    calibrada = st.artifacts.get("calibration", "out_of_model_calibrated_pd_frame").loc[fuera]
    assert set(calibrada["calibration_method"]) == {metodo}
    parametros = st.artifacts.get("calibration", "parameters").model_dump(mode="json")
    np.testing.assert_allclose(
        calibrada["pd_calibrated"].to_numpy(),
        _calibrate_array(pd_frame["linear_predictor"].to_numpy(dtype="float64"), parametros),
        rtol=0,
        atol=1e-9,
    )


def test_paridad_con_el_bundle_y_el_desacuerdo_conocido_en_categorias_no_vistas(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
) -> None:
    """🔴 Test 3: donde el bundle puntúa, da lo mismo; donde no —una categoría no vista—, el
    motor da el riesgo promedio y el bundle la rechaza (§7, defecto previo fijado a propósito)."""
    sc, datos = _corrida
    st = sc.study
    fuera = _fuera(datos)
    crudo = datos.loc[fuera].drop(columns=["bad_flag"])
    aplicado = FittedScorecardBundle.from_study(st).apply(crudo).application_frame
    aplicado.index = fuera[aplicado["input_position"].to_numpy()]
    puntaje = st.artifacts.get("scorecard", "out_of_model_score")
    calibrada = st.artifacts.get("calibration", "out_of_model_calibrated_pd_frame")
    puntuadas = aplicado.index[aplicado["scoring_status"].eq("scored")]
    rechazadas = aplicado.index[~aplicado["scoring_status"].eq("scored")]
    assert len(puntuadas) > 0
    np.testing.assert_allclose(
        aplicado.loc[puntuadas, "score"].to_numpy(dtype="float64"),
        puntaje.loc[puntuadas, "score"].to_numpy(dtype="float64"),
        atol=0,
    )
    np.testing.assert_allclose(
        aplicado.loc[puntuadas, "pd_calibrated"].to_numpy(dtype="float64"),
        calibrada.loc[puntuadas, "pd_calibrated"].to_numpy(dtype="float64"),
        rtol=0,
        atol=1e-12,
    )
    finales = st.artifacts.get("model", "final_features")
    if "segmento" in finales:
        assert set(datos.loc[rechazadas, "segmento"]) <= {"D"}
        assert (
            aplicado.loc[rechazadas, "not_scorable_reason"]
            .astype(str)
            .str.contains("categoria_no_observada_en_fit")
            .all()
        )
        assert puntaje.loc[rechazadas, "score"].notna().all()


def test_con_ttd_sin_excluidos_no_se_puntua_ninguna_fila_nueva(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame], tmp_path: Path
) -> None:
    """🔴 Test 4: con `ttd_includes_excluded=False` la TTD son sólo las modelables (D-DATA-5)."""
    sc, _ = _corrida
    data = sc.config.data
    particion = data.partition.model_copy(update={"ttd_includes_excluded": False})
    config = sc.config.model_copy(update={"data": data.model_copy(update={"partition": particion})})
    st = nikodym.run(config, run_dir=tmp_path / "sin_ttd")
    assert st.run_context.status == "done", st.run_context.error
    for clave in _CLAVES:
        frame = st.artifacts.get(*clave)
        assert frame.empty, clave
        assert list(frame.columns) == list(st.artifacts.get(*_ESPEJOS[clave]).columns), clave
    card = st.artifacts.get("data", "data_card")
    linea = _linea_fuera_del_ajuste(
        st,
        int(card.partition_sizes["fuera_de_modelo"]),
        int(card.class_counts["indeterminado"]),
        int(card.class_counts["excluido"]),
    )
    assert "no entran al ajuste ni a la población total (TTD), así que no se puntúan" in linea
    assert st.artifacts.get("stability", "out_of_model_psi").empty


def test_division_por_columna_las_filas_con_desenlace_apartadas_se_puntuan_y_se_nombran(
    tmp_path: Path,
) -> None:
    """🔴 Test 4b: un valor no mapeado con desenlace cae fuera del ajuste; se puntúa, la
    composición lo nombra y la tasa observada de su fila se mide sobre esas filas."""
    datos = _cartera(muestra=True, indeterminados=0.0)
    sc = _puerta(
        _guardar(datos, tmp_path, "columna"),
        tmp_path,
        "columna",
        date=None,
        oot_from=None,
        partition="random",
    )
    sc.exclude(["muestra"], reason="define la muestra")
    data = sc.config.data
    estrategia = ColumnSplitConfig(
        type="columna", partition_col="muestra", desarrollo=("dev",), holdout=("ho",), oot=("oot",)
    )
    particion = data.partition.model_copy(update={"strategy": estrategia})
    config = sc.config.model_copy(update={"data": data.model_copy(update={"partition": particion})})
    st = nikodym.run(config, run_dir=tmp_path / "columna_run")
    assert st.run_context.status == "done", st.run_context.error
    otro = datos.index[datos["muestra"].eq("otro")]
    calibrada = st.artifacts.get("calibration", "out_of_model_calibrated_pd_frame")
    assert set(calibrada.index) == set(otro)
    tabla = _tabla_pd_por_muestra(
        st, {"pd_raw_column": "pd_raw", "pd_calibrated_column": "pd_calibrated"}
    )
    fila = tabla.loc[tabla["Muestra"].eq("Fuera del ajuste (TTD)")].iloc[0]
    assert fila["Filas"] == len(otro)
    assert fila["Tasa de malos observada"] == pytest.approx(
        float(datos.loc[otro, "bad_flag"].mean())
    )
    card = st.artifacts.get("data", "data_card")
    linea = _linea_fuera_del_ajuste(
        st,
        int(card.partition_sizes["fuera_de_modelo"]),
        int(card.class_counts["indeterminado"]),
        int(card.class_counts["excluido"]),
    )
    assert f"{len(otro)} con desenlace fuera de las muestras declaradas" in linea
    assert f"se mide sobre las {len(otro)} con desenlace" in linea


def test_sin_filas_fuera_del_ajuste_las_claves_quedan_vacias_y_el_informe_no_las_ve(
    tmp_path: Path,
) -> None:
    """🔴 Test 5: sin filas, cuatro claves vacías con su esquema, sin decisión ni línea, y el
    informe no gana tablas de cero filas."""
    datos = _cartera(indeterminados=0.0)
    sc = _puerta(_guardar(datos, tmp_path, "sin_fuera"), tmp_path, "sin_fuera")
    sc.run()
    st = sc.study
    assert st.run_context.status == "done", st.run_context.error
    for clave in _CLAVES:
        frame = st.artifacts.get(*clave)
        assert frame.empty, clave
        assert list(frame.columns) == list(st.artifacts.get(*_ESPEJOS[clave]).columns), clave
    assert _decisiones(Path(sc.project_dir), "puntuar_ttd_fuera_de_modelo") == []
    assert not any("Fuera del ajuste (TTD)" in linea for linea in sc.summary("scorecard").lines)
    tablas = ReportBuilder(ReportConfig()).collect(st).tables
    assert "scorecard.out_of_model_score" not in tablas
    assert "calibration.out_of_model_calibrated_pd_frame" not in tablas


def test_una_falla_en_la_tarjeta_no_detiene_la_corrida_y_vacia_la_cadena(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Tests 6 y 6a: la falla queda en el trail y en la alerta de su etapa; la calibración no
    publica PD para filas sin puntaje, ni la estabilidad mide su representatividad."""
    original = scorecard_step._assemble_score_frame

    def falla_fuera(**kwargs: Any) -> Any:
        if kwargs["raw_pd_frame"]["partition"].astype(str).eq("fuera_de_modelo").any():
            raise RuntimeError("falla inyectada")
        return original(**kwargs)

    monkeypatch.setattr(scorecard_step, "_assemble_score_frame", falla_fuera)
    datos = _cartera()
    sc = _puerta(_guardar(datos, tmp_path, "falla"), tmp_path, "falla")
    sc.run()
    st = sc.study
    assert st.run_context.status == "done", st.run_context.error
    assert not st.artifacts.get("binning", "out_of_model_woe_frame").empty
    assert not st.artifacts.get("model", "out_of_model_pd_frame").empty
    assert st.artifacts.get("scorecard", "out_of_model_score").empty
    assert st.artifacts.get("calibration", "out_of_model_calibrated_pd_frame").empty
    assert st.artifacts.get("stability", "out_of_model_psi").empty
    (falla,) = _decisiones(Path(sc.project_dir), "ttd_no_puntuada")
    assert falla["umbral"] == "scorecard"
    assert "RuntimeError: falla inyectada" in falla["valor"]["causa"]
    assert any("No se pudo puntuar" in a for a in sc.summary("scorecard").alerts)
    assert not any("No se pudo puntuar" in a for a in sc.summary("calibration").alerts)
    assert not any("No se pudo puntuar" in a for a in sc.summary("model").alerts)


def test_un_diagnostico_aditivo_que_falla_no_detiene_la_corrida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revisión adversarial del código, pasada 1: el conteo de categorías no vistas corría fuera
    de toda captura; ahora una falla suya publica la clave vacía y queda en el trail."""
    import nikodym.binning.transformer as transformer

    def falla(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("conteo roto")

    monkeypatch.setattr(transformer, "_contar_categorias_no_vistas", falla)
    datos = _cartera()
    sc = _puerta(_guardar(datos, tmp_path, "conteo"), tmp_path, "conteo")
    sc.run()
    st = sc.study
    assert st.run_context.status == "done", st.run_context.error
    assert st.artifacts.get("binning", "unseen_categories").empty
    assert not st.artifacts.get("scorecard", "out_of_model_score").empty
    (decision,) = _decisiones(Path(sc.project_dir), "categorias_no_vistas_no_contadas")
    assert "RuntimeError: conteo roto" in decision["valor"]["causa"]


def test_la_representatividad_exige_una_sola_poblacion() -> None:
    """Revisión adversarial del código, pasada 1: con puntaje y PD calibrada de filas distintas
    (artefactos inyectados de corridas distintas) no se publica un PSI."""
    from types import SimpleNamespace

    from nikodym.core.audit import InMemoryAuditSink
    from nikodym.stability.config import StabilityConfig
    from nikodym.stability.step import StabilityStep

    score = pd.DataFrame(
        {"partition": ["desarrollo"] * 20, "score": np.arange(20.0)}, index=range(20)
    )
    fuera = pd.DataFrame({"partition": ["fuera_de_modelo"] * 5, "score": np.arange(5.0)})
    calibrada = pd.DataFrame(
        {"partition": ["fuera_de_modelo"] * 5, "pd_calibrated": [0.1] * 5}, index=range(100, 105)
    )
    valores = {
        ("scorecard", "score"): score,
        ("scorecard", "out_of_model_score"): fuera,
        ("calibration", "out_of_model_calibrated_pd_frame"): calibrada,
    }
    study = SimpleNamespace(
        artifacts=SimpleNamespace(
            has=lambda d, k: (d, k) in valores, get=lambda d, k: valores[(d, k)]
        )
    )
    step = StabilityStep(StabilityConfig())
    sink = InMemoryAuditSink()
    step._audit = sink
    psi = step._psi_fuera_del_ajuste(study, StabilityConfig())  # type: ignore[arg-type]
    assert psi.empty
    (evento,) = [e.payload for e in sink.events if e.kind == "decision"]
    assert evento["regla"] == "ttd_no_puntuada"
    assert "mismo índice" in evento["valor"]["causa"]
    calibrada.index = fuera.index
    assert not step._psi_fuera_del_ajuste(study, StabilityConfig()).empty  # type: ignore[arg-type]


def _con_puntaje_minimo_inalcanzable(sc: nikodym.Scorecard) -> Any:
    """Un config donde TODO puntaje queda fuera de rango: el escalador registra
    `score_fuera_de_rango` en cada transformación, así que el caso nunca es vacuo."""
    return sc.config.model_copy(
        update={"scorecard": sc.config.scorecard.model_copy(update={"min_score": 100000.0})}
    )


def _decisiones_de(run_dir: Path, regla: str) -> list[dict[str, Any]]:
    eventos = [
        json.loads(linea)
        for linea in (run_dir / "audit_trail.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return [
        e["payload"]
        for e in eventos
        if e["kind"] == "decision" and e["payload"].get("regla") == regla
    ]


def test_las_decisiones_del_escalador_fuera_del_ajuste_dicen_su_poblacion(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame], tmp_path: Path
) -> None:
    """Revisión adversarial del código, pasada 3: las decisiones de la segunda transformación
    se mezclaban con las de las muestras. Ahora llevan `poblacion`, y las de las muestras no."""
    sc, datos = _corrida
    st = nikodym.run(_con_puntaje_minimo_inalcanzable(sc), run_dir=tmp_path / "rango")
    assert st.run_context.status == "done", st.run_context.error
    eventos = _decisiones_de(tmp_path / "rango", "score_fuera_de_rango")
    fuera = [e for e in eventos if e["valor"].get("poblacion") == "fuera_del_ajuste"]
    muestras = [e for e in eventos if "poblacion" not in e["valor"]]
    assert len(muestras) == 1
    assert len(fuera) == 1
    assert fuera[0]["valor"]["filas_afectadas"] == len(_fuera(datos))
    assert muestras[0]["valor"]["filas_afectadas"] == len(
        st.artifacts.get("scorecard", "score").index
    )


def test_si_el_puntaje_fuera_del_ajuste_falla_no_quedan_sus_decisiones(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revisión adversarial del código, pasada 3: si el ensamblado falla tras transformar, las
    decisiones de esa transformación no quedan en el trail; queda sólo la falla."""
    original = scorecard_step._assemble_score_frame

    def falla_fuera(**kwargs: Any) -> Any:
        if kwargs["raw_pd_frame"]["partition"].astype(str).eq("fuera_de_modelo").any():
            raise RuntimeError("falla inyectada")
        return original(**kwargs)

    monkeypatch.setattr(scorecard_step, "_assemble_score_frame", falla_fuera)
    sc, _ = _corrida
    st = nikodym.run(_con_puntaje_minimo_inalcanzable(sc), run_dir=tmp_path / "falla")
    assert st.run_context.status == "done", st.run_context.error
    eventos = _decisiones_de(tmp_path / "falla", "score_fuera_de_rango")
    assert len(eventos) == 1
    assert "poblacion" not in eventos[0]["valor"]
    assert len(_decisiones_de(tmp_path / "falla", "ttd_no_puntuada")) == 1


def test_run_until_binning_publica_solo_la_clave_de_binning(tmp_path: Path) -> None:
    """🔴 Test 6b: cada paso que corre publica su clave; las de los pasos que no corrieron no
    existen."""
    datos = _cartera()
    sc = _puerta(_guardar(datos, tmp_path, "parcial"), tmp_path, "parcial")
    sc.run(until="binning")
    assert sc.study.artifacts.has("binning", "out_of_model_woe_frame")
    assert not sc.study.artifacts.has("model", "out_of_model_pd_frame")


def test_las_entradas_de_la_cadena_ausentes_o_vacias_no_alertan() -> None:
    """🔴 Test 6b: una entrada ausente (artefactos inyectados) o vacía devuelve `None`."""

    class _Almacen:
        def __init__(self, valores: dict[tuple[str, str], Any]) -> None:
            self._valores = valores

        def has(self, domain: str, key: str) -> bool:
            return (domain, key) in self._valores

        def get(self, domain: str, key: str) -> Any:
            return self._valores[(domain, key)]

    class _Study:
        def __init__(self, valores: dict[tuple[str, str], Any]) -> None:
            self.artifacts = _Almacen(valores)

    lleno = pd.DataFrame({"x": [1.0]})
    claves = (("binning", "out_of_model_woe_frame"), ("model", "out_of_model_pd_frame"))
    assert entradas_fuera_del_ajuste(_Study({}), claves) is None  # type: ignore[arg-type]
    vacio = {claves[0]: lleno, claves[1]: lleno.iloc[0:0]}
    assert entradas_fuera_del_ajuste(_Study(vacio), claves) is None  # type: ignore[arg-type]
    completo = {claves[0]: lleno, claves[1]: lleno}
    assert entradas_fuera_del_ajuste(_Study(completo), claves) is not None  # type: ignore[arg-type]


# ───────────────────────── D-TTD-3: lo que se lee ─────────────────────────


def test_los_resumenes_dicen_la_composicion_el_puntaje_y_la_pd_de_la_ttd(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
) -> None:
    """🔴 Test 8: datos, tarjeta y calibración lo dicen en español, sin identificadores."""
    sc, datos = _corrida
    n = len(_fuera(datos))
    datos_lineas = "\n".join(sc.summary("data").lines)
    assert f"Fuera del ajuste: {n} operaciones ({n} indeterminadas)" in datos_lineas
    assert "la tarjeta las puntúa aparte como parte de la población total (TTD)" in datos_lineas
    assert "ni reciben puntaje" not in datos_lineas
    tarjeta = "\n".join(sc.summary("scorecard").lines)
    assert f"Fuera del ajuste (TTD): {n} operaciones puntuadas ({n} indeterminadas)" in tarjeta
    calibracion = sc.summary("calibration")
    muestras = list(calibracion.table["Muestra"])
    assert muestras[-1] == "Fuera del ajuste (TTD)"
    assert any(
        linea.startswith("PD calibrada media de toda la población que pidió crédito (TTD, ")
        for linea in calibracion.lines
    )
    for resumen in (sc.summary("data"), sc.summary("scorecard"), calibracion):
        texto = resumen.text()
        for codigo in ("fuera_de_modelo", "out_of_model", "ttd_no_puntuada"):
            assert codigo not in texto, codigo


def test_los_dos_exports_por_observacion_salen_con_su_titulo(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
) -> None:
    """🔴 Test 9."""
    sc, _ = _corrida
    tablas = ReportBuilder(ReportConfig()).collect(sc.study).tables
    for clave, titulo in (
        ("scorecard.out_of_model_score", "Puntaje de las operaciones fuera del ajuste (TTD)"),
        (
            "calibration.out_of_model_calibrated_pd_frame",
            "PD calibrada de las operaciones fuera del ajuste (TTD)",
        ),
    ):
        assert clave in PER_OBSERVATION_TABLES
        assert table_title(clave) == titulo
        assert clave in tablas


# ───────────────────────── D-TTD-4: representatividad ─────────────────────────


def test_la_representatividad_sigue_los_cortes_y_no_entra_al_veredicto(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
) -> None:
    """🔴 Test 10."""
    sc, _ = _corrida
    st = sc.study
    psi = st.artifacts.get("stability", "out_of_model_psi")
    assert not psi.empty
    assert set(psi["comparison"]) == {"dev_vs_out_of_model"}
    total = float(psi["total_value"].iloc[0])
    cfg = st.config.stability
    assert set(psi["band"]) == {
        _psi_band(total, cfg.psi_stable_threshold, cfg.psi_review_threshold)
    }
    lineas = "\n".join(sc.summary("stability").lines)
    assert "Fuera del ajuste frente a Desarrollo: PSI " in lineas
    assert "Redesarrollar" not in lineas.split("Fuera del ajuste frente a Desarrollo")[1]
    validacion = st.artifacts.get("validation", "stability")
    assert "dev_vs_out_of_model" not in set(validacion["comparison"].astype(str))


def test_con_cortes_de_estabilidad_cambiados_la_banda_los_sigue(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame], tmp_path: Path
) -> None:
    """🔴 Test 10a: con cortes minúsculos, la lectura es «difieren» y sube como alerta."""
    sc, _ = _corrida
    estabilidad = sc.config.stability.model_copy(
        update={"psi_stable_threshold": 0.00001, "psi_review_threshold": 0.00002}
    )
    config = sc.config.model_copy(update={"stability": estabilidad})
    st = nikodym.run(config, run_dir=tmp_path / "cortes")
    assert st.run_context.status == "done", st.run_context.error
    psi = st.artifacts.get("stability", "out_of_model_psi")
    assert set(psi["band"]) == {"redevelop"}
    from nikodym.guided.summaries import _linea_representatividad

    resultado = _linea_representatividad(st)
    assert resultado is not None
    linea, alerta = resultado
    assert "— difieren:" in linea
    assert alerta is not None and "la muestra de ajuste no las representa" in alerta


# ───────────────────────── D-TTD-5: categorías no vistas ─────────────────────────


def test_las_categorias_no_vistas_se_cuentan_por_muestra_sin_tocar_lo_auditado(
    _corrida: tuple[nikodym.Scorecard, pd.DataFrame],
) -> None:
    """🔴 Tests 10b y 10c: `segmento` «D» existe sólo tras la frontera; se cuenta en OOT y fuera
    del ajuste, el evento del trail y el estado del `process` son los de las modelables."""
    sc, datos = _corrida
    st = sc.study
    tabla = st.artifacts.get("binning", "unseen_categories")
    segmento = tabla.loc[tabla["variable"].eq("segmento")].set_index("muestra")["filas"]
    frame = st.artifacts.get("data", "frame")
    en_oot = int((frame["partition"].eq("oot") & datos["segmento"].eq("D")).sum())
    en_fuera = int((datos["bad_flag"].isna() & datos["segmento"].eq("D")).sum())
    assert segmento.to_dict() == {"oot": en_oot, "fuera_de_modelo": en_fuera}
    (evento,) = [
        d
        for d in _decisiones(Path(sc.project_dir), "categoria_no_vista")
        if d["valor"]["variable"] == "segmento"
    ]
    assert evento["valor"]["conteo"] == en_oot
    assert evento["accion"] == "asignar_woe_neutral"
    assert st.artifacts.get("binning", "process").unknown_categories_["segmento"] == en_oot
    alertas = "\n".join(sc.summary("binning").alerts)
    assert (
        f"«segmento»: {en_oot + en_fuera} operaciones con una categoría que no existía en "
        f"Desarrollo ({en_oot} en Fuera de tiempo (OOT) y {en_fuera} fuera del ajuste); en esa "
        "variable reciben WoE 0, el riesgo promedio"
    ) in alertas


def test_con_cat_unknown_declarado_el_trail_y_la_alerta_dicen_ese_valor() -> None:
    """🔴 Test 10d, a nivel de unidad: el evento decía «neutral» aunque se declarara otro valor, y
    la alerta dice el tratamiento efectivo.

    De punta a punta no es alcanzable hoy: con un ``cat_unknown`` numérico la corrida muere en
    ``transform_bins`` (OptBinning exige texto para la métrica de bins). Es un defecto previo,
    registrado aparte en la enmienda; este test fija lo que D-TTD-5 promete sobre el registro.
    """
    from types import SimpleNamespace

    from nikodym.binning.config import BinningConfig
    from nikodym.binning.step import BinningStep
    from nikodym.core.audit import InMemoryAuditSink
    from nikodym.guided.summaries import _alertas_categorias_no_vistas

    step = BinningStep(BinningConfig())
    sink = InMemoryAuditSink()
    step._audit = sink
    step._log_unknown_categories({"segmento": 3, "otra": 0}, -0.5)
    step._log_unknown_categories({"segmento": 2}, None)
    declarado, neutral = (e.payload for e in sink.events if e.kind == "decision")
    assert (declarado["accion"], declarado["umbral"]) == ("asignar_woe_declarado", -0.5)
    assert (neutral["accion"], neutral["umbral"]) == ("asignar_woe_neutral", 0)

    tabla = pd.DataFrame({"variable": ["segmento"], "muestra": ["oot"], "filas": [3]})

    class _Almacen:
        def has(self, domain: str, key: str) -> bool:
            return (domain, key) == ("binning", "unseen_categories")

        def get(self, domain: str, key: str) -> Any:
            return tabla

    for valor, esperado in (
        (-0.5, "reciben el WoE declarado para categorías no vistas (-0,50)"),
        (None, "reciben WoE 0, el riesgo promedio"),
    ):
        study = SimpleNamespace(
            artifacts=_Almacen(), config=SimpleNamespace(binning=SimpleNamespace(cat_unknown=valor))
        )
        (alerta,) = _alertas_categorias_no_vistas(study)  # type: ignore[arg-type]
        assert alerta == (
            "«segmento»: 3 operaciones con una categoría que no existía en Desarrollo "
            f"(3 en Fuera de tiempo (OOT)); en esa variable {esperado}"
        )
