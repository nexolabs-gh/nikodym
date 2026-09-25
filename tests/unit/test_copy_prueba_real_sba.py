"""Enmienda corta de copy de la prueba real con el SBA (D-CPY-1…4 y D-CPY-6).

Lo que la prueba de Cami con la muestra pública SBA 7(a) mostró mal escrito: el código
``fuera_de_modelo`` en la tabla de muestras, «PSI temporal period» y tres CSI indistinguibles, los
tramos como ``['3 a 4 años']`` y ``(-inf, 50450.00)``, los p-valores ``0,0000`` y un
Hosmer-Lemeshow que falla sin decir la brecha. D-CPY-5 (la coma decimal del sitio) tiene su gate en
``test_docs_site_coma_decimal.py``.

D-CPY-3 no es sólo presentación: el rótulo legible exige que un ajuste manual de puntos case con él
y los bordes efectivos de cada tramo (``("binning", "bin_edges")``), porque la etiqueta de
OptBinning está redondeada a dos decimales.

Contrato: ``docs/design/_ENMIENDA-COPY-PRUEBA-REAL-SBA.md``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym
from nikodym.core.tramos import (
    formatear_borde,
    rotulo_de_rango,
    rotulo_de_tramo,
    rotulos_de_tramos,
)
from nikodym.guided.summaries import (
    _celda,
    _overrides_sin_casar,
    _partition_label,
    _prueba_de_estabilidad,
    _pruebas_decisivas,
    _tabla_muestras,
)
from nikodym.report.builder import ReportBuilder
from nikodym.report.config import ReportConfig
from nikodym.report.renderer import _table_view
from nikodym.scorecard.config import PointOverrideConfig
from nikodym.ui.serializers import _bin_labels


class _Almacen:
    def __init__(self, valores: dict[tuple[str, str], Any]) -> None:
        self._valores = valores

    def has(self, domain: str, key: str) -> bool:
        return (domain, key) in self._valores

    def get(self, domain: str, key: str) -> Any:
        return self._valores[(domain, key)]


def _study(valores: dict[tuple[str, str], Any], **config: Any) -> Any:
    return SimpleNamespace(artifacts=_Almacen(valores), config=SimpleNamespace(**config))


# ───────────────────────── D-CPY-1: «Fuera del ajuste» ─────────────────────────


def test_la_particion_fuera_de_modelo_tiene_rotulo() -> None:
    assert _partition_label("fuera_de_modelo") == "Fuera del ajuste"


def _muestras(objetivo_fuera: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "partition": ["desarrollo"] * 4 + ["fuera_de_modelo"] * len(objetivo_fuera),
            "target": [0.0, 1.0, 0.0, 0.0, *objetivo_fuera],
        }
    )
    estudio = _study(
        {
            ("data", "frame"): frame,
            ("data", "labels"): SimpleNamespace(target_col="target"),
            ("data", "splits"): SimpleNamespace(partition_col="partition"),
        }
    )
    tabla = _tabla_muestras(estudio)
    assert tabla is not None
    return tabla.set_index("Muestra")


def test_sin_desenlaces_los_malos_fuera_del_ajuste_son_desconocidos_no_cero() -> None:
    fila = _muestras([math.nan, math.nan]).loc["Fuera del ajuste"]
    assert _celda(fila["Malos"], "int") == "—"
    assert _celda(fila["Tasa de malos"], "pct") == "—"


def test_con_desenlaces_se_conservan_los_malos_y_la_tasa_se_mide_sobre_ellos() -> None:
    fila = _muestras([1.0, 0.0, math.nan]).loc["Fuera del ajuste"]
    assert fila["Malos"] == 1
    assert fila["Tasa de malos"] == pytest.approx(0.5)


def test_la_tabla_de_particiones_del_informe_pinta_el_rotulo() -> None:
    tabla = pd.DataFrame(
        {
            "Partición": ["desarrollo", "holdout", "oot", "fuera_de_modelo"],
            "Observaciones": [10, 5, 5, 2],
            "Tasa de incumplimiento": [0.2, 0.2, 0.2, 0.0],
        }
    )
    vista = _table_view("data.partitions", tabla, max_rows=10)
    columna = vista["columns"].index("Partición")
    assert [fila[columna] for fila in vista["rows"]] == [
        "Desarrollo",
        "Holdout",
        "Fuera de tiempo (OOT)",
        "Fuera del ajuste",
    ]


# ───────────────────────── D-CPY-2: lo que falló, con nombre ─────────────────────────


def test_la_linea_de_validacion_nombra_la_variable_del_csi_y_el_eje() -> None:
    csi = {"metric": "csi", "comparison": "dev_vs_oot", "feature": "anio_fiscal__points"}
    assert (
        _prueba_de_estabilidad({**csi, "band": "redevelop"})
        == "CSI de anio_fiscal Desarrollo vs. OOT (Redesarrollar)"
    )
    temporal = {"metric": "temporal_score", "comparison": "period", "feature": "score"}
    assert (
        _prueba_de_estabilidad({**temporal, "band": "redevelop"})
        == "PSI temporal por período (Redesarrollar)"
    )
    psi = {"metric": "score_psi", "comparison": "dev_vs_oot", "feature": "score"}
    assert (
        _prueba_de_estabilidad({**psi, "band": "review"})
        == "PSI del score Desarrollo vs. OOT (Revisar)"
    )


# ───────────────────────── D-CPY-4 y D-CPY-6 ─────────────────────────


def test_el_p_valor_de_una_tabla_se_escribe_como_en_las_frases() -> None:
    assert _celda(1e-9, "pvalor") == "< 0,001"
    assert _celda(0.0123, "pvalor") == "0,012"
    assert _celda(None, "pvalor") == "—"


def test_hosmer_lemeshow_dice_la_brecha_media_agregada_sin_atribuirle_causa() -> None:
    calibracion = pd.DataFrame(
        [
            {
                "test": "hosmer_lemeshow",
                "partition": "oot",
                "decision": "fail",
                "p_value": 0.0,
                "expected_pd": 0.271511,
                "observed_dr": 0.217642,
            },
            {
                "test": "brier",
                "partition": "oot",
                "decision": "fail",
                "p_value": None,
                "expected_pd": 0.271511,
                "observed_dr": 0.217642,
            },
        ]
    )
    (hl, brier) = _pruebas_decisivas(_study({("validation", "calibration"): calibracion}))
    assert hl == (
        "Hosmer-Lemeshow en Fuera de tiempo (OOT) (p-valor < 0,001; PD media agregada 27,15 % "
        "frente a 21,76 % observada)"
    )
    assert "PD media agregada" not in brier
    assert "potencia" not in hl


# ───────────────────────── D-CPY-3: el rótulo de un tramo ─────────────────────────


def test_el_borde_se_escribe_en_es_cl_sin_ceros_de_relleno() -> None:
    assert formatear_borde(50450.0) == "50.450"
    assert formatear_borde(102230.5) == "102.230,5"
    assert formatear_borde(7.123456) == "7,123456"
    assert formatear_borde(-0.25) == "-0,25"
    assert formatear_borde(-0.0) == "0"
    # Los cortes de OptBinning son puntos medios en float32: se escriben con los decimales que el
    # motor distingue (medio ulp de float32), no con su expansión binaria ni con dos fijos.
    assert formatear_borde(242795.8828125) == "242.795,88"
    assert formatear_borde(0.37409999966621399) == "0,3741"
    assert formatear_borde(7.12345) == "7,12345"


def test_el_rango_se_escribe_con_comparadores() -> None:
    assert rotulo_de_rango(-math.inf, 50450.0) == "< 50.450"
    assert rotulo_de_rango(50450.0, 102230.5) == "≥ 50.450 y < 102.230,5"
    assert rotulo_de_rango(102230.5, math.inf) == "≥ 102.230,5"
    assert rotulo_de_rango(-math.inf, math.inf) == "todos los valores"


def test_un_tramo_categorico_se_lee_como_texto() -> None:
    assert rotulo_de_tramo(np.array(["2001", "2000"], dtype=object)) == "2001, 2000"
    assert rotulo_de_tramo(["3 a 4 años"]) == "3 a 4 años"
    assert rotulo_de_tramo("Missing") == "Faltantes"
    assert rotulo_de_tramo("Special") == "Valores especiales"
    # Un rango sin sus bordes efectivos se deja como lo escribió el motor.
    assert rotulo_de_tramo("(-inf, 3.00)") == "(-inf, 3.00)"


def test_los_rotulos_de_una_tabla_usan_los_bordes_y_si_no_calzan_la_etiqueta() -> None:
    tabla = pd.DataFrame(
        {"Bin": ["(-inf, 7.12)", "[7.12, inf)", "Special", "Missing", ""]},
        index=[0, 1, 2, 3, "Totals"],
    )
    bordes = pd.DataFrame(
        {
            "variable": ["tasa", "tasa"],
            "bin_index": [0, 1],
            "lower": [-math.inf, 7.123456],
            "upper": [7.123456, math.inf],
        }
    )
    assert rotulos_de_tramos(tabla, bordes, "tasa") == {
        "(-inf, 7.12)": "< 7,123456",
        "[7.12, inf)": "≥ 7,123456",
        "Special": "Valores especiales",
        "Missing": "Faltantes",
    }
    un_borde = bordes.iloc[:1]
    assert rotulos_de_tramos(tabla, un_borde, "tasa")["(-inf, 7.12)"] == "(-inf, 7.12)"
    assert rotulos_de_tramos(tabla, None, "tasa")["[7.12, inf)"] == "[7.12, inf)"


# ───────────────────────── D-CPY-3 de punta a punta ─────────────────────────

pytest.importorskip("optbinning")


@pytest.fixture(scope="module")
def _corrida(tmp_path_factory: pytest.TempPathFactory) -> nikodym.Scorecard:
    with pytest.MonkeyPatch.context() as parche:
        parche.setenv("PYTHONHASHSEED", "0")
        raiz = tmp_path_factory.mktemp("copy")
        rng = np.random.default_rng(3)
        n = 1500
        tasa = np.round(rng.uniform(1.0, 20.0, size=n), 6)
        segmento = rng.choice(np.array(["norte", "sur", "este", "oeste"], dtype=object), size=n)
        logit = -2.0 + 0.12 * tasa + np.where(segmento == "sur", 0.9, 0.0)
        y = (rng.uniform(size=n) < 1.0 / (1.0 + np.exp(-logit))).astype(int)
        datos = pd.DataFrame(
            {
                "loan_id": [f"op-{i:05d}" for i in range(n)],
                "tasa": tasa,
                "segmento": segmento,
                "bad_flag": y,
            }
        )
        ruta = raiz / "cartera.parquet"
        datos.to_parquet(ruta)
        sc = nikodym.Scorecard(
            ruta,
            target="bad_flag",
            id="loan_id",
            partition="random",
            name="copy",
            run_dir=raiz / "run",
        )
        sc._echo = lambda _texto: None
        sc.run()
    return sc


def test_los_bordes_efectivos_son_los_cortes_ajustados_a_precision_completa(
    _corrida: nikodym.Scorecard,
) -> None:
    st = _corrida.study
    assert st.run_context.status == "done", st.run_context.error
    bordes = st.artifacts.get("binning", "bin_edges")
    propios = bordes.loc[bordes["variable"].eq("tasa")].sort_values("bin_index")
    cortes = st.artifacts.get("binning", "process").process_.get_binned_variable("tasa").splits
    assert list(propios["upper"].iloc[:-1]) == [float(c) for c in cortes]
    assert list(propios["lower"].iloc[1:]) == [float(c) for c in cortes]
    assert "segmento" not in set(bordes["variable"])


def test_sc_bins_escribe_el_rango_con_los_bordes_efectivos(_corrida: nikodym.Scorecard) -> None:
    st = _corrida.study
    cortes = [
        float(c)
        for c in st.artifacts.get("binning", "process").process_.get_binned_variable("tasa").splits
    ]
    rangos = list(_corrida.bins("tasa")["Rango"])
    assert rangos[0] == f"< {formatear_borde(cortes[0])}"
    assert rangos[-1] == f"≥ {formatear_borde(cortes[-1])}"
    assert not any("(" in rango or "[" in rango for rango in rangos)


def test_la_tabla_de_la_tarjeta_muestra_el_rotulo_y_el_artefacto_no_cambia(
    _corrida: nikodym.Scorecard,
) -> None:
    st = _corrida.study
    tarjeta = st.artifacts.get("scorecard", "scorecard")
    tabla = _corrida.summary("scorecard").table
    assert tabla is not None
    segmento = tabla.loc[tabla["Variable"].eq("segmento"), "Tramo"]
    assert not segmento.empty
    assert not segmento.str.contains(r"\[|'").any()
    crudas = tarjeta.loc[tarjeta["feature"].eq("segmento"), "bin_label"]
    regulares = crudas.loc[~crudas.isin(["Special", "Missing"])]
    assert regulares.str.startswith("[").all()


def _ajuste(sc: nikodym.Scorecard, feature: str, bin_label: str) -> Any:
    ajuste = PointOverrideConfig(feature=feature, bin_label=bin_label, points=7, reason="comité")
    return sc.config.model_copy(
        update={"scorecard": sc.config.scorecard.model_copy(update={"point_overrides": (ajuste,)})}
    )


def test_un_ajuste_con_el_rotulo_legible_se_aplica(
    _corrida: nikodym.Scorecard, tmp_path: Path
) -> None:
    tabla = _corrida.summary("scorecard").table
    legible = str(tabla.loc[tabla["Variable"].eq("segmento"), "Tramo"].iloc[0])
    st = nikodym.run(_ajuste(_corrida, "segmento", legible), run_dir=tmp_path / "legible")
    assert st.run_context.status == "done", st.run_context.error
    tarjeta = st.artifacts.get("scorecard", "scorecard")
    fila = tarjeta.loc[tarjeta["feature"].eq("segmento")].iloc[0]
    assert (fila["points"], fila["source"]) == (7, "override")
    assert _overrides_sin_casar(st) == ()


def test_un_ajuste_con_la_etiqueta_del_motor_se_aplica_igual_que_antes(
    _corrida: nikodym.Scorecard, tmp_path: Path
) -> None:
    tarjeta = _corrida.study.artifacts.get("scorecard", "scorecard")
    cruda = str(tarjeta.loc[tarjeta["feature"].eq("tasa"), "bin_label"].iloc[0])
    st = nikodym.run(_ajuste(_corrida, "tasa", cruda), run_dir=tmp_path / "cruda")
    assert st.run_context.status == "done", st.run_context.error
    nueva = st.artifacts.get("scorecard", "scorecard")
    fila = nueva.loc[nueva["feature"].eq("tasa") & nueva["bin_label"].eq(cruda)].iloc[0]
    assert (fila["points"], fila["source"]) == (7, "override")


def test_un_ajuste_que_no_calza_se_declara_en_el_trail_y_en_el_resumen(
    _corrida: nikodym.Scorecard, tmp_path: Path
) -> None:
    config = _ajuste(_corrida, "tasa", "no existe")
    st = nikodym.run(config, run_dir=tmp_path / "sin_casar")
    assert st.run_context.status == "done", st.run_context.error
    trail = tmp_path / "sin_casar" / "audit_trail.jsonl"
    eventos = [json.loads(linea) for linea in trail.read_text(encoding="utf-8").splitlines()]
    (evento,) = [
        e["payload"]
        for e in eventos
        if e["kind"] == "decision" and e["payload"].get("regla") == "point_override_sin_casar"
    ]
    assert evento["valor"] == {"feature": "tasa", "bin_label": "no existe"}
    assert evento["accion"] == "no_aplicar"
    assert _overrides_sin_casar(st) == (
        "El ajuste manual de puntos de «tasa» para el tramo «no existe» no calzó con ningún "
        "tramo y no se aplicó",
    )


def test_el_informe_y_la_pantalla_leen_el_mismo_rotulo(_corrida: nikodym.Scorecard) -> None:
    st = _corrida.study
    bundle = ReportBuilder(ReportConfig()).collect(st)
    vista = _table_view(
        "binning.tables.tasa",
        bundle.tables["binning.tables.tasa"],
        max_rows=50,
        bin_labels=bundle.bin_labels,
    )
    columna = vista["columns"].index("Bin")
    primero = vista["rows"][0][columna]
    assert primero.startswith("< ")
    cruda = str(st.artifacts.get("binning", "tables")["tasa"]["Bin"].iloc[0])
    assert _bin_labels(st)["tasa"][cruda] == primero
    tarjeta = _table_view(
        "scorecard.scorecard",
        bundle.tables["scorecard.scorecard"],
        max_rows=100,
        bin_labels=bundle.bin_labels,
    )
    columna = tarjeta["columns"].index("bin_label")
    assert not any("['" in str(fila[columna]) for fila in tarjeta["rows"])
    # El valor del artefacto —el del JSON y del CSV— sigue siendo la etiqueta del motor.
    assert str(bundle.tables["binning.tables.tasa"]["Bin"].iloc[0]) == cruda
