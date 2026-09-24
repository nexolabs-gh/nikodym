"""Un bin de faltantes sin una clase no mata la corrida, y excluir excluye de verdad (D-FAL, D-EXC).

Medido con una muestra pública de préstamos 7(a) de la SBA: ocho préstamos no declaran la
antigüedad de la empresa y en desarrollo su bin `Missing` queda con 4 buenos y 0 malos; el WoE no
existe y la corrida moría en «Tramos y WoE». Tampoco se podía salir excluyendo la variable, porque
`exclude()` sólo escribía la lista forzada de la selección.

- **D-FAL-1**: un bin `Missing` o `Special` con operaciones y una clase en cero, con WoE empírico,
  recibe el WoE del tramo regular de mayor tasa de malos observada —el de menor WoE; ante un
  empate, la primera fila—, con IV 0 en su fila, y comparte sus puntos: hereda su ajuste manual y
  no admite uno propio.
- **D-FAL-2**: trail, card (`assigned_bins`) y una línea por bin en el resumen.
- **D-EXC-1**: `exclude()` escribe `binning.exclude_columns`; los tramos fijados de una variable
  excluida quedan en suspenso y `keep()` los reactiva.

Estos tests usan **OptBinning real**: el doble determinista de la suite no produce bins de
faltantes sin una clase, que es justamente lo que se mide.

Contrato: `docs/design/_ENMIENDA-FALTANTES-SIN-CLASE-Y-EXCLUSION.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym
import nikodym.binning.transformer as transformer_module
from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.exceptions import BinningFitError
from nikodym.binning.step import _active_overrides
from nikodym.binning.transformer import WoEBinner
from nikodym.core.audit import InMemoryAuditSink
from nikodym.data.special import MaskedFrame
from nikodym.guided.summaries import _bins_asignados
from nikodym.scorecard.bundle import FittedScorecardBundle
from nikodym.scorecard.config import PointOverrideConfig
from nikodym.scorecard.exceptions import ScorecardFitError
from nikodym.scorecard.scaler import PointsScaler

# Importar `nikodym` no arrastra OptBinning (import perezoso); ajustar sí.
pytest.importorskip("optbinning")


# ───────────────────────── fixtures ─────────────────────────


def _cartera(
    n: int = 1200,
    *,
    faltantes_buenos: int = 10,
    especiales_malos: int = 0,
    semilla: int = 5,
) -> tuple[pd.DataFrame, pd.Series, MaskedFrame | None]:
    """Una numérica con faltantes sólo entre los buenos y, opcionalmente, especiales sólo malos."""
    rng = np.random.default_rng(semilla)
    y = (rng.uniform(size=n) < 0.2).astype(int)
    index = pd.Index([f"op-{i:05d}" for i in range(n)], name="loan_id")
    antiguedad = (rng.integers(1, 40, size=n) - y * 5).astype(float)
    antiguedad[np.where(y == 0)[0][:faltantes_buenos]] = np.nan
    frame = pd.DataFrame(
        {"antiguedad": antiguedad, "ingreso": rng.normal(size=n) - y * 0.6}, index=index
    )
    target = pd.Series(y, index=index, name="target")
    if not especiales_malos:
        return frame, target, None
    mask = pd.DataFrame(False, index=index, columns=frame.columns)
    mask.loc[index[np.where(y == 1)[0][:especiales_malos]], "antiguedad"] = True
    frame.loc[mask["antiguedad"], "antiguedad"] = np.nan
    special = MaskedFrame(
        frame=frame.copy(deep=True),
        special_mask=mask,
        special_catalog={"antiguedad": [-999.0]},
    )
    return frame, target, special


def _ajustar(
    frame: pd.DataFrame,
    y: pd.Series,
    special: MaskedFrame | None = None,
    **config: Any,
) -> tuple[WoEBinner, InMemoryAuditSink]:
    binner = WoEBinner.from_config(BinningConfig(**config))
    binner.set_params(feature_columns=("antiguedad", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()
    binner.fit(frame, y, special=special, audit=sink)
    return binner, sink


def _decisiones(sink: InMemoryAuditSink, regla: str) -> list[dict[str, Any]]:
    return [
        event.payload
        for event in sink.events
        if event.kind == "decision" and event.payload.get("regla") == regla
    ]


def _fila(tabla: pd.DataFrame, etiqueta: str) -> pd.Series:
    return tabla.loc[tabla["Bin"].map(lambda b: isinstance(b, str) and b == etiqueta)].iloc[0]


def _peor_tramo(tabla: pd.DataFrame) -> tuple[str, float]:
    """El tramo regular de menor WoE —la primera fila ante un empate— y ese WoE."""
    regulares = tabla.loc[
        (tabla.index.astype(str) != "Totals")
        & ~tabla["Bin"].map(lambda b: isinstance(b, str) and b in {"Missing", "Special"})
    ]
    woe = pd.to_numeric(regulares["WoE"])
    return str(regulares.loc[woe.idxmin(), "Bin"]), float(woe.min())


# ───────────────────────── la regla en el binner ─────────────────────────


def test_faltantes_sin_malos_reciben_el_woe_del_peor_tramo_con_iv_cero() -> None:
    """🔴 Test 2: hoy muere con «WoE no defendible por bin con una clase en cero»."""
    frame, y, _ = _cartera()
    binner, sink = _ajustar(frame, y)

    tabla = binner.tables_["antiguedad"]
    tramo, woe_peor = _peor_tramo(tabla)
    faltantes = _fila(tabla, "Missing")
    assert (int(faltantes["Count"]), int(faltantes["Event"])) == (10, 0)
    assert float(faltantes["WoE"]) == woe_peor
    assert float(faltantes["IV"]) == 0.0
    # La transformación da ese mismo WoE a las filas faltantes: tabla y puntaje no discrepan.
    woe = binner.transform(frame)["antiguedad__woe"]
    assert set(woe[frame["antiguedad"].isna()]) == {woe_peor}
    assert binner.assigned_bins_[0].model_dump() == {
        "variable": "antiguedad",
        "bin": "Missing",
        "n_obs": 10,
        "n_events": 0,
        "assigned_woe": woe_peor,
        "reference_bin": tramo,
    }
    assert _decisiones(sink, "bin_sin_clase_asignado") == [
        {
            "regla": "bin_sin_clase_asignado",
            "umbral": {
                "regla": "peor_tramo_observado",
                "woe_asignado": woe_peor,
                "tramo_de_referencia": tramo,
            },
            "valor": {
                "variable": "antiguedad",
                "bin": "Missing",
                "operaciones": 10,
                "incumplidas": 0,
            },
            "accion": "asignar_woe",
        }
    ]


def test_el_iv_de_la_variable_no_cambia_el_bin_asignado_no_aporta_evidencia() -> None:
    frame, y, _ = _cartera()
    binner, _ = _ajustar(frame, y)
    tabla = binner.tables_["antiguedad"]
    sin_totales = tabla.loc[tabla.index.astype(str) != "Totals"]
    iv = binner.summary_.set_index("name").loc["antiguedad", "iv"]
    assert iv == pytest.approx(float(pd.to_numeric(sin_totales["IV"]).sum()))


def test_especiales_todos_malos_reciben_el_woe_del_peor_tramo() -> None:
    """🔴 Test 3: un bin `Special` puede quedar hecho sólo de malos."""
    frame, y, special = _cartera(faltantes_buenos=0, especiales_malos=6)
    binner, sink = _ajustar(frame, y, special)

    tabla = binner.tables_["antiguedad"]
    _, woe_peor = _peor_tramo(tabla)
    especiales = _fila(tabla, "Special")
    assert (int(especiales["Count"]), int(especiales["Non-event"])) == (6, 0)
    assert float(especiales["WoE"]) == woe_peor
    assert float(especiales["IV"]) == 0.0
    assert special is not None
    filas = special.special_mask["antiguedad"]
    assert set(binner.transform(frame)["antiguedad__woe"][filas]) == {woe_peor}
    (asignado,) = binner.assigned_bins_
    assert (asignado.bin, asignado.n_obs, asignado.n_events) == ("Special", 6, 6)
    assert len(_decisiones(sink, "bin_sin_clase_asignado")) == 1


def test_dos_bins_asignados_en_una_variable() -> None:
    """🔴 Test 8e: la unidad es el par (variable, bin); una variable puede tener los dos."""
    frame, y, special = _cartera(faltantes_buenos=10, especiales_malos=6)
    binner, sink = _ajustar(frame, y, special)

    assert [(a.variable, a.bin) for a in binner.assigned_bins_] == [
        ("antiguedad", "Special"),
        ("antiguedad", "Missing"),
    ]
    decisiones = _decisiones(sink, "bin_sin_clase_asignado")
    assert [d["valor"]["bin"] for d in decisiones] == ["Special", "Missing"]
    _, woe_peor = _peor_tramo(binner.tables_["antiguedad"])
    woe = binner.transform(frame)["antiguedad__woe"]
    assert set(woe[frame["antiguedad"].isna()]) == {woe_peor}


def test_con_un_valor_declarado_el_comportamiento_no_cambia() -> None:
    """Test 4 (guardrail del alcance): con `metric_missing` numérico la regla no entra."""
    frame, y, _ = _cartera()
    binner = WoEBinner.from_config(BinningConfig(metric_missing=-0.5))
    binner.set_params(feature_columns=("antiguedad", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()

    with pytest.raises(BinningFitError, match="una clase en cero"):
        binner.fit(frame, y, audit=sink)
    assert _decisiones(sink, "bin_sin_clase_asignado") == []


def test_sin_bins_degenerados_no_hay_decision_ni_asignacion() -> None:
    """Test 5: la regla sólo entra donde la corrida iba a morir."""
    frame, y, _ = _cartera(faltantes_buenos=0)
    faltan = frame.index[:12]  # buenos y malos mezclados
    frame.loc[faltan, "antiguedad"] = np.nan
    assert 0 < int(y.loc[faltan].sum()) < len(faltan)
    binner, sink = _ajustar(frame, y)

    assert binner.assigned_bins_ == ()
    assert _decisiones(sink, "bin_sin_clase_asignado") == []


def test_con_pesos_una_clase_de_masa_pequena_no_se_toma_por_ausente() -> None:
    """🔴 Pasada 2 de Codex: OptBinning publica las masas ponderadas truncadas a entero. Con dos
    malos de peso 0,1 entre los faltantes, la tabla dice `Event=0`, pero la clase existe: el bin
    conserva su WoE empírico, no hay asignación ni decisión, y la corrida se comporta como antes
    —la validación de siempre sigue leyendo la tabla y la detiene—."""
    frame, y, _ = _cartera()
    malos = np.where(y.to_numpy() == 1)[0][:2]
    frame.iloc[malos, frame.columns.get_loc("antiguedad")] = np.nan
    pesos = pd.Series(1.0, index=frame.index)
    pesos.iloc[malos] = 0.1
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("antiguedad", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()

    with pytest.raises(BinningFitError, match="una clase en cero"):
        binner.fit(frame, y, sample_weight=pesos, audit=sink)
    assert _decisiones(sink, "bin_sin_clase_asignado") == []


def test_con_pesos_una_clase_de_masa_cero_si_se_asigna() -> None:
    """Con pesos, lo que falta es MASA: sin ningún malo entre los faltantes, la regla entra igual
    que sin pesos, y los conteos publicados son operaciones."""
    frame, y, _ = _cartera()
    pesos = pd.Series(2.0, index=frame.index)
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("antiguedad", "ingreso"), exclude_columns=())
    binner.fit(frame, y, sample_weight=pesos)
    (asignado,) = binner.assigned_bins_
    assert (asignado.bin, asignado.n_obs, asignado.n_events) == ("Missing", 10, 0)


def test_ante_un_empate_la_referencia_es_la_primera_fila_regular() -> None:
    """🔴 Test 8f: dos tramos con el mismo WoE mínimo; la referencia es el primero, que es el
    que usa la búsqueda de puntos del escalador."""
    tabla = pd.DataFrame(
        {
            "Bin": ["(-inf, 1)", "[1, 2)", "[2, inf)", "Special", "Missing", ""],
            "Count": [40, 40, 40, 0, 5, 125],
            "Non-event": [30, 35, 30, 0, 5, 100],
            "Event": [10, 5, 10, 0, 0, 25],
            "WoE": [-0.5, 0.3, -0.5, 0.0, 0.0, ""],
            "IV": [0.1, 0.05, 0.1, 0.0, 0.0, 0.25],
        },
        index=[0, 1, 2, 3, 4, "Totals"],
    )
    working = pd.DataFrame({"x": [np.nan] * 5 + [1.0] * 120})
    target = pd.Series([0] * 5 + [0, 1] * 60)
    salida: list[Any] = []

    patched, asignados = transformer_module._assign_classless_bins(
        "x",
        tabla,
        estimator=WoEBinner(),
        working=working,
        target=target,
        weights=None,
        special_codes={},
        out=salida,
    )

    assert asignados == frozenset({"Missing"})
    assert float(patched.loc[4, "WoE"]) == -0.5
    assert salida[0].reference_bin == "(-inf, 1)"
    assert float(tabla.loc[4, "WoE"]) == 0.0  # la tabla de entrada no se muta


# ───────────────────────── los puntos del bin asignado ─────────────────────────


def _tablas_con_empate() -> dict[str, pd.DataFrame]:
    return {
        "x": pd.DataFrame(
            {
                "Bin": ["(-inf, 1)", "[1, 2)", "[2, inf)", "Special", "Missing"],
                "WoE": [-0.5, 0.3, -0.5, 0.0, -0.5],
            }
        )
    }


def _escalar(
    overrides: tuple[PointOverrideConfig, ...], audit: InMemoryAuditSink | None = None
) -> PointsScaler:
    coeficientes = pd.DataFrame(
        [
            {"feature": "intercept", "woe_column": "const", "beta": -1.0},
            {"feature": "x", "woe_column": "x__woe", "beta": -0.9},
        ]
    )
    return PointsScaler(rounding_method="nearest_integer", point_overrides=overrides).fit(
        coefficients=coeficientes,
        final_features=("x",),
        final_woe_columns=("x__woe",),
        binning_tables=_tablas_con_empate(),
        woe_column_map={"x": "x__woe"},
        audit=audit,
        assigned_bins={"x": {"Missing"}},
    )


def test_el_override_del_tramo_de_referencia_se_hereda_y_se_declara() -> None:
    """🔴 Test 8b/8f: el override de la PRIMERA fila con el WoE mínimo llega a la fila `Missing`
    de la tabla de puntos —la que congela el bundle— y a la búsqueda de la corrida."""
    ajuste = PointOverrideConfig(feature="x", bin_label="(-inf, 1)", points=7, reason="comité")
    audit = InMemoryAuditSink()
    scaler = _escalar((ajuste,), audit)

    tabla = scaler.scorecard_.set_index("bin_label")
    assert tabla.loc["Missing", "points"] == 7
    assert tabla.loc["Missing", "source"] == "override"
    assert tabla.loc["Missing", "bin_index"] == 4
    # El segundo tramo con el mismo WoE no hereda: no es la referencia.
    assert tabla.loc["[2, inf)", "points"] != 7
    assert scaler.transform(pd.DataFrame({"x__woe": [-0.5]})).loc[0, "x__points"] == 7
    heredados = _decisiones(audit, "point_override_heredado")
    assert heredados == [
        {
            "regla": "point_override_heredado",
            "umbral": "(-inf, 1)",
            "valor": {"feature": "x", "bin_label": "Missing", "puntos_nuevo": 7},
            "accion": "heredar_override",
        }
    ]


def test_sin_override_el_bin_asignado_tiene_los_puntos_de_su_referencia() -> None:
    tabla = _escalar(()).scorecard_.set_index("bin_label")
    assert tabla.loc["Missing", "points"] == tabla.loc["(-inf, 1)", "points"]
    assert tabla.loc["Missing", "source"] == "binning_table"


def test_un_override_sobre_el_bin_asignado_se_rechaza() -> None:
    """🔴 Test 8c: aparecería en la tabla y no se aplicaría a sus filas."""
    ajuste = PointOverrideConfig(feature="x", bin_label="Missing", points=7, reason="comité")
    with pytest.raises(ScorecardFitError, match="comparte los puntos de su tramo de referencia"):
        _escalar((ajuste,))


# ───────────────────────── lo que dice el resumen ─────────────────────────


def test_el_resumen_dice_el_tipo_de_bin_y_la_clase_que_falta() -> None:
    """🔴 Test 8d: un bin especial puede estar hecho sólo de malos."""
    lineas = _bins_asignados(
        [
            {"variable": "antiguedad", "bin": "Missing", "n_obs": 4, "n_events": 0},
            {"variable": "saldo", "bin": "Special", "n_obs": 1, "n_events": 1},
        ]
    )
    assert lineas == (
        "Faltantes de «antiguedad» (4 operaciones, ninguna incumplida): se les asignó el riesgo "
        "de su peor tramo",
        "Valores especiales de «saldo» (1 operación, todas incumplidas): se les asignó el riesgo "
        "de su peor tramo",
    )


# ───────────────────────── de punta a punta ─────────────────────────


@pytest.fixture
def _archivo_con_faltantes(tmp_path: Path) -> Path:
    frame, y, _ = _cartera()
    ruta = tmp_path / "cartera_faltantes.parquet"
    frame.reset_index().assign(bad_flag=y.to_numpy()).to_parquet(ruta)
    return ruta


def _puerta(ruta: Path, tmp_path: Path, nombre: str) -> nikodym.Scorecard:
    sc = nikodym.Scorecard(
        ruta,
        target={"col": "bad_flag", "op": "==", "value": 1},
        id="loan_id",
        partition="random",
        name=nombre,
        run_dir=tmp_path / "run",
    )
    sc._echo = lambda _texto: None
    return sc


def _decisiones_del_trail(sc: nikodym.Scorecard, regla: str) -> list[dict[str, Any]]:
    trail = Path(sc.project_dir) / "run" / "audit_trail.jsonl"
    eventos = [json.loads(linea) for linea in trail.read_text(encoding="utf-8").splitlines()]
    return [
        e["payload"]
        for e in eventos
        if e["kind"] == "decision" and e["payload"].get("regla") == regla
    ]


def test_gate_la_cartera_con_faltantes_sin_malos_llega_al_final(
    _archivo_con_faltantes: Path, tmp_path: Path
) -> None:
    """🔴 Test 1 en la suite (el de la SBA corre fuera, con el archivo público) y tests 6 y 8b:
    la corrida termina `done`, la card y el trail declaran la asignación, el resumen la dice en
    español, y corrida, tabla de puntos y bundle dan los mismos puntos a las filas faltantes."""
    sc = _puerta(_archivo_con_faltantes, tmp_path, "faltantes")
    sc.run()

    assert sc.study.run_context.status == "done", sc.study.run_context.error
    (asignado,) = sc.study.artifacts.get("binning", "binning_card").assigned_bins
    assert (asignado.variable, asignado.bin, asignado.n_events) == ("antiguedad", "Missing", 0)
    assert len(_decisiones_del_trail(sc, "bin_sin_clase_asignado")) == 1
    lineas = "\n".join(sc.summary("binning").lines)
    assert "Faltantes de «antiguedad» (" in lineas
    assert "ninguna incumplida): se les asignó el riesgo de su peor tramo" in lineas
    for slug in ("Missing", "bin_sin_clase", "assigned", "WoE asignado"):
        assert slug not in lineas, slug

    puntos = sc.study.artifacts.get("scorecard", "scorecard")
    puntos = puntos.loc[puntos["feature"].eq("antiguedad")].set_index("bin_label")
    assert puntos.loc["Missing", "points"] == puntos.loc[asignado.reference_bin, "points"]
    datos = pd.read_parquet(_archivo_con_faltantes)
    faltan = datos.index[datos["antiguedad"].isna()]
    score = sc.study.artifacts.get("scorecard", "score")
    assert set(score.loc[faltan, "antiguedad__points"]) == {puntos.loc["Missing", "points"]}
    aplicado = FittedScorecardBundle.from_study(sc.study).apply(datos.drop(columns=["bad_flag"]))
    por_fila = aplicado.application_frame.set_index("input_position")["score"].astype(float)
    assert (por_fila.loc[faltan] - score.loc[faltan, "score"].astype(float)).abs().max() == 0.0


def test_override_en_la_referencia_llega_al_bundle_y_en_el_bin_asignado_se_rechaza(
    _archivo_con_faltantes: Path, tmp_path: Path
) -> None:
    """🔴 Tests 8b (con override) y 8c por el config completo."""
    sc = _puerta(_archivo_con_faltantes, tmp_path, "base")
    sc.run(until="binning")
    (asignado,) = sc.study.artifacts.get("binning", "binning_card").assigned_bins

    def con_override(bin_label: str) -> Any:
        ajuste = PointOverrideConfig(
            feature="antiguedad", bin_label=bin_label, points=7, reason="comité"
        )
        return sc.config.model_copy(
            update={
                "scorecard": sc.config.scorecard.model_copy(update={"point_overrides": (ajuste,)})
            }
        )

    study = nikodym.run(con_override(asignado.reference_bin), run_dir=tmp_path / "referencia")
    assert study.run_context.status == "done", study.run_context.error
    datos = pd.read_parquet(_archivo_con_faltantes)
    faltan = datos.index[datos["antiguedad"].isna()]
    score = study.artifacts.get("scorecard", "score")
    assert set(score.loc[faltan, "antiguedad__points"]) == {7}
    aplicado = FittedScorecardBundle.from_study(study).apply(datos.drop(columns=["bad_flag"]))
    traza = aplicado.trace_frame
    en_bundle = traza.loc[traza["input_position"].isin(faltan) & traza["feature"].eq("antiguedad")]
    assert set(en_bundle["points"].astype(float)) == {7.0}
    por_fila = aplicado.application_frame.set_index("input_position")["score"].astype(float)
    assert (por_fila.loc[faltan] - score.loc[faltan, "score"].astype(float)).abs().max() == 0.0

    rechazado = nikodym.run(con_override("Missing"), run_dir=tmp_path / "asignado")
    assert rechazado.run_context.status == "failed"
    assert rechazado.run_context.error is not None
    assert "comparte los puntos de su tramo de referencia" in rechazado.run_context.error.message


# ───────────────────────── exclude() excluye de verdad ─────────────────────────


#: Una categórica que D-RAR no puede rescatar: ni juntando sus dos niveles raros aparece un malo.
_NIVELES_SIN_SALIDA: dict[str, tuple[int, int]] = {
    "A": (400, 80),
    "B": (300, 60),
    "C": (150, 45),
    "D": (100, 20),
    "E": (12, 0),
    "RARO": (8, 0),
}


@pytest.fixture
def _archivo_que_muere_en_binning(tmp_path: Path) -> Path:
    rng = np.random.default_rng(11)
    niveles: list[str] = []
    malos: list[int] = []
    for nivel, (n, n_malos) in _NIVELES_SIN_SALIDA.items():
        niveles += [nivel] * n
        malos += [1] * n_malos + [0] * (n - n_malos)
    orden = rng.permutation(len(niveles))
    y = np.array(malos)[orden]
    datos = pd.DataFrame(
        {
            "loan_id": [f"op-{i:04d}" for i in range(len(niveles))],
            "proposito": np.array(niveles, dtype=object)[orden],
            "ingreso": rng.normal(size=len(niveles)) + y * 0.8,
            "antiguedad": rng.integers(1, 120, size=len(niveles)),
            "bad_flag": y,
        }
    )
    ruta = tmp_path / "cartera_que_muere.parquet"
    datos.to_parquet(ruta)
    return ruta


def test_exclude_saca_la_variable_del_binning_y_la_corrida_termina(
    _archivo_que_muere_en_binning: Path, tmp_path: Path
) -> None:
    """🔴 Test 7: hoy la corrida muere en «Tramos y WoE» aunque la variable esté excluida."""
    sc = _puerta(_archivo_que_muere_en_binning, tmp_path, "excluir")
    sc.run()
    assert sc.study.run_context.status == "failed"
    assert sc.study.run_context.error is not None
    assert sc.study.run_context.error.step == "binning"

    sc.exclude("proposito", reason="la categoría no tiene malos en ningún nivel raro")
    assert sc.config.binning.exclude_columns == ("proposito",)
    # No se escribe la lista forzada de la selección: la selección rechaza forzar una variable
    # que el binning ya no publica.
    assert sc.config.selection.force_exclude == ()
    sc.run()

    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert "proposito" not in sc.study.artifacts.get("binning", "tables")
    assert "proposito" not in sc.study.artifacts.get("model", "final_features")
    (decision,) = _decisiones_del_trail(sc, "decision_del_usuario")
    assert decision["valor"] == {"binning.exclude_columns": ["proposito"]}


def test_keep_despues_de_exclude_devuelve_la_variable_al_binning(
    _archivo_con_faltantes: Path, tmp_path: Path
) -> None:
    """Test 8: la última decisión gana."""
    sc = _puerta(_archivo_con_faltantes, tmp_path, "keep")
    sc.exclude("ingreso", reason="prueba")
    sc.keep("ingreso", reason="el comité la quiere")
    assert sc.config.binning.exclude_columns == ()
    assert sc.config.selection.force_include == ("ingreso",)
    assert sc.config.model.force_include == ("ingreso",)
    sc.run(until="binning")
    assert "ingreso" in sc.study.artifacts.get("binning", "tables")


def test_set_bins_luego_exclude_deja_el_override_en_suspenso_y_keep_lo_reactiva(
    _archivo_con_faltantes: Path, tmp_path: Path
) -> None:
    """🔴 Test 8a: hoy `exclude()` después de fijar tramos deja un override de una variable que
    el binning no tramifica, y la corrida muere."""
    sc = _puerta(_archivo_con_faltantes, tmp_path, "suspenso")
    sc.run(until="binning")
    sc.set_bins("ingreso", [-0.5, 0.5], reason="los cortes del manual")
    sc.exclude("ingreso", reason="dato no disponible en originación")
    sc.run(until="binning")

    assert sc.study.run_context.error is None
    assert "ingreso" not in sc.study.artifacts.get("binning", "tables")
    assert _decisiones_del_trail(sc, "override_en_suspenso") == [
        {
            "regla": "override_en_suspenso",
            "umbral": "binning.exclude_columns",
            "valor": {"variable": "ingreso"},
            "accion": "no_aplicar_override",
        }
    ]
    # El override sigue en el config: `keep()` lo reactiva sin volver a escribirlo.
    assert [o.name for o in sc.config.binning.variable_overrides] == ["ingreso"]
    sc.keep("ingreso", reason="vuelve")
    sc.run(until="binning")
    assert sc.study.run_context.error is None
    assert list(sc.bins("ingreso")["Tramo"]) == [1, 2, 3]
    assert _decisiones_del_trail(sc, "override_en_suspenso") == []


def test_un_override_de_una_variable_que_no_existe_sigue_siendo_un_error() -> None:
    """Sólo quedan en suspenso los overrides de variables excluidas; el de una variable que no
    existe sigue activo, y el binner lo rechaza como siempre."""
    config = BinningConfig(
        exclude_columns=("ingreso",),
        variable_overrides=(
            VariableBinningConfig(name="ingreso", user_splits=(0.0,)),
            VariableBinningConfig(name="no_existe", user_splits=(1.0,)),
        ),
    )
    columnas = ("antiguedad", "ingreso")
    activos, suspendidos = _active_overrides(config, ("antiguedad",), columnas)
    assert [o.name for o in activos] == ["no_existe"]
    assert [o.name for o in suspendidos] == ["ingreso"]
    frame, y, _ = _cartera()
    binner = WoEBinner.from_config(config)
    binner.set_params(
        feature_columns=("antiguedad",), exclude_columns=(), variable_overrides=activos
    )
    with pytest.raises(BinningFitError, match="no serán binneadas"):
        binner.fit(frame, y)


def test_un_override_inexistente_no_se_suspende_aunque_este_excluido() -> None:
    """🔴 Pasada 1 de Codex: una columna que no existe, nombrada a la vez en `exclude_columns` y
    en `variable_overrides`, no puede quedar «en suspenso»: el override sigue activo y el binner lo
    rechaza como siempre."""
    config = BinningConfig(
        exclude_columns=("fantasma",),
        variable_overrides=(VariableBinningConfig(name="fantasma", user_splits=(1.0,)),),
    )
    activos, suspendidos = _active_overrides(config, ("antiguedad",), ("antiguedad", "ingreso"))
    assert [o.name for o in activos] == ["fantasma"]
    assert suspendidos == ()
