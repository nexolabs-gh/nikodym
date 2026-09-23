"""Una categoría rara con una clase en cero no puede matar la corrida (D-RAR-1/2).

El corte de categorías raras (`cat_cutoff`, 0,01 de fábrica) puede dejar **un solo** nivel por
debajo: el grupo de «raras» que debía protegerlo queda igual de solo, y si ese nivel no tiene un
solo malo en desarrollo el WoE no existe y la corrida muere en «Tramos y WoE». Es lo que le pasó a
UCI German Credit (`proposito`, nivel `A48`). El motor reagrupa **una vez** con el menor corte que
deja dos niveles debajo, lo declara, y publica el corte efectivo como resultado.

Estos tests usan **OptBinning real**: el doble determinista de la suite no reproduce el corte de
categorías raras, que es justamente lo que se mide.

Contrato: `docs/design/_ENMIENDA-CATEGORIA-RARA-SIN-CLASE.md`.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nikodym
from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.exceptions import BinningFitError
from nikodym.binning.transformer import WoEBinner
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import config_hash

# Importar `nikodym` no arrastra OptBinning (import perezoso); ajustar sí.
pytest.importorskip("optbinning")

#: El mecanismo de German Credit, en pequeño: `RARO` es el único nivel bajo el 1 % y no tiene
#: ningún malo; `E` es el segundo más raro y sí tiene.
NIVELES_RESCATABLES: dict[str, tuple[int, int]] = {
    "A": (400, 80),
    "B": (300, 60),
    "C": (150, 45),
    "D": (100, 20),
    "E": (12, 4),
    "RARO": (8, 0),
}

#: Ni juntando los dos más raros aparece un malo: el único reintento no puede resolverlo.
NIVELES_SIN_SALIDA: dict[str, tuple[int, int]] = {
    **NIVELES_RESCATABLES,
    "E": (12, 0),
}

#: Ningún nivel queda solo bajo el corte: la regla no tiene nada que hacer.
NIVELES_SANOS: dict[str, tuple[int, int]] = {
    "A": (400, 80),
    "B": (300, 60),
    "C": (150, 45),
    "D": (150, 20),
}


def _cartera(
    niveles: dict[str, tuple[int, int]], semilla: int = 7
) -> tuple[pd.DataFrame, pd.Series]:
    """Una categórica y una numérica informativa; `niveles`: nivel → (filas, malos)."""
    rng = np.random.default_rng(semilla)
    filas: list[str] = []
    malos: list[int] = []
    for nivel, (n, n_malos) in niveles.items():
        filas += [nivel] * n
        malos += [1] * n_malos + [0] * (n - n_malos)
    orden = rng.permutation(len(filas))
    target = np.array(malos)[orden]
    frame = pd.DataFrame(
        {
            "proposito": np.array(filas, dtype=object)[orden],
            "ingreso": rng.normal(size=len(filas)) + target * 0.8,
        },
        index=pd.Index([f"op-{i:04d}" for i in range(len(filas))], name="loan_id"),
    )
    return frame, pd.Series(target, index=frame.index, name="target")


def _ajustar(
    niveles: dict[str, tuple[int, int]], config: BinningConfig | None = None
) -> tuple[WoEBinner, InMemoryAuditSink]:
    frame, y = _cartera(niveles)
    binner = WoEBinner.from_config(config or BinningConfig())
    binner.set_params(feature_columns=("proposito", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()
    binner.fit(frame, y, audit=sink)
    return binner, sink


def _decisiones(sink: InMemoryAuditSink, regla: str) -> list[dict]:
    return [
        event.payload
        for event in sink.events
        if event.kind == "decision" and event.payload.get("regla") == regla
    ]


def _bins_puros(tabla: pd.DataFrame) -> list[object]:
    """Bins con observaciones y una clase en cero, fuera de la fila de totales."""
    regulares = tabla.loc[tabla.index.astype(str) != "Totals"]
    puros = regulares[
        (regulares["Count"] > 0) & ((regulares["Event"] == 0) | (regulares["Non-event"] == 0))
    ]
    return list(puros["Bin"])


# ───────────────────────── la regla ─────────────────────────


def test_el_nivel_aislado_por_el_corte_se_reagrupa_y_el_woe_existe() -> None:
    """🔴 Test 2: hoy muere con «WoE no defendible por bin con una clase en cero»."""
    binner, _ = _ajustar(NIVELES_RESCATABLES)

    assert _bins_puros(binner.tables_["proposito"]) == []
    reagrupada = binner.rare_category_regroupings_["proposito"]
    assert reagrupada.levels == ("RARO",)
    assert (reagrupada.n_obs, reagrupada.n_events) == (8, 0)
    assert reagrupada.declared_cat_cutoff == pytest.approx(0.01)
    assert reagrupada.effective_cat_cutoff > reagrupada.declared_cat_cutoff
    # La variable no se descarta: sigue binificada, con todas sus categorías.
    assert "proposito" in binner.feature_columns_


def test_el_corte_efectivo_deja_dos_niveles_debajo_y_es_el_menor_que_lo_logra() -> None:
    """Test 4, en los dos sentidos: con el corte efectivo hay dos niveles debajo; con uno menos,
    el grupo vuelve a ser unitario."""
    binner, _ = _ajustar(NIVELES_RESCATABLES)
    efectivo = binner.rare_category_regroupings_["proposito"].effective_cat_cutoff
    conteos = pd.Series({nivel: n for nivel, (n, _) in NIVELES_RESCATABLES.items()})
    total = int(conteos.sum())

    def debajo(corte: float) -> set[str]:
        return set(conteos[conteos < math.ceil(corte * total)].index)

    assert debajo(efectivo) == {"RARO", "E"}
    assert debajo(efectivo - 1 / total) == {"RARO"}


def test_sin_niveles_degenerados_no_hay_reintento_ni_decision() -> None:
    """Test 3 (guardrail): la regla sólo entra donde la corrida iba a morir."""
    binner, sink = _ajustar(NIVELES_SANOS)

    assert binner.rare_category_regroupings_ == {}
    assert _decisiones(sink, "categoria_rara_intento_reagrupar") == []
    assert _decisiones(sink, "categoria_rara_reagrupada") == []


def test_intento_y_exito_son_dos_eventos_en_ese_orden() -> None:
    """Test 7, camino exitoso: el intento va antes del reajuste y la reagrupación sólo después."""
    _, sink = _ajustar(NIVELES_RESCATABLES)
    reglas = [
        event.payload["regla"]
        for event in sink.events
        if event.kind == "decision"
        and str(event.payload.get("regla", "")).startswith("categoria_rara")
    ]
    assert reglas == ["categoria_rara_intento_reagrupar", "categoria_rara_reagrupada"]
    intento = _decisiones(sink, "categoria_rara_intento_reagrupar")[0]
    assert intento["accion"] == "intentar"
    assert intento["valor"]["variable"] == "proposito"
    assert intento["valor"]["niveles"] == ["RARO"]
    assert (intento["valor"]["operaciones"], intento["valor"]["incumplidas"]) == (8, 0)
    hecho = _decisiones(sink, "categoria_rara_reagrupada")[0]
    assert hecho["accion"] == "reagrupar"
    assert hecho["umbral"]["corte_efectivo"] == pytest.approx(intento["umbral"]["corte_a_probar"])


def test_un_solo_reintento_y_si_no_basta_el_error_dice_que_se_intento_y_que_salidas_hay() -> None:
    """🔴 Test 6 y test 7 (camino fallido): el trail ya registró el intento —se emite antes de
    propagar— y NO registra una reagrupación que no ocurrió; el mensaje nombra variable, nivel,
    conteos, cortes y las dos salidas ejecutables para una categórica."""
    frame, y = _cartera(NIVELES_SIN_SALIDA)
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("proposito", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()

    with pytest.raises(BinningFitError) as error:
        binner.fit(frame, y, audit=sink)

    mensaje = str(error.value)
    assert mensaje.startswith("WoE no defendible por bin con una clase en cero")
    for fragmento in ("«proposito»", "«RARO»", "8 operaciones", "ninguna incumplida"):
        assert fragmento in mensaje, fragmento
    assert "0,01 →" in mensaje
    assert "excluir la variable" in mensaje
    assert "binning.variable_overrides" in mensaje
    # Salida NO ejecutable para una categórica: el motor rechaza `user_splits` ahí.
    assert "tramos" not in mensaje.lower()
    assert len(_decisiones(sink, "categoria_rara_intento_reagrupar")) == 1
    assert _decisiones(sink, "categoria_rara_reagrupada") == []


def test_un_override_por_variable_es_el_corte_declarado() -> None:
    """El corte de partida es el que rige esa variable, también cuando viene de su override."""
    config = BinningConfig(
        variable_overrides=(VariableBinningConfig(name="proposito", cat_cutoff=0.009),)
    )
    binner, _ = _ajustar(NIVELES_RESCATABLES, config)
    assert binner.rare_category_regroupings_["proposito"].declared_cat_cutoff == pytest.approx(
        0.009
    )


# ───────────────────────── de punta a punta ─────────────────────────


@pytest.fixture
def _cartera_con_categoria_rara(tmp_path: Path) -> Path:
    """Un archivo de banco con una categoría que nunca incumple y pesa menos del 1 %."""
    frame, y = _cartera(NIVELES_RESCATABLES, semilla=11)
    rng = np.random.default_rng(3)
    datos = frame.reset_index().assign(
        bad_flag=y.to_numpy(),
        antiguedad=rng.integers(1, 120, size=len(frame)),
    )
    ruta = tmp_path / "cartera_categoria_rara.parquet"
    datos.to_parquet(ruta)
    return ruta


def test_gate_la_cartera_con_una_categoria_rara_llega_al_final(
    _cartera_con_categoria_rara: Path, tmp_path: Path
) -> None:
    """🔴 Test 1 en la suite (el de German Credit corre fuera, con el archivo de la UCI): la
    corrida termina `done`, la categórica sigue en el modelo de tramos, la card publica el corte
    efectivo y el resumen de «Tramos y WoE» lo dice en español."""
    sc = nikodym.Scorecard(
        _cartera_con_categoria_rara,
        target={"col": "bad_flag", "op": "==", "value": 1},
        id="loan_id",
        partition="random",
        name="categoria_rara",
        run_dir=tmp_path / "run",
    )
    sc.run()

    assert sc.study.run_context.status == "done", sc.study.run_context.error
    card = sc.study.artifacts.get("binning", "binning_card")
    assert "proposito" in card.iv_by_variable
    assert "proposito" in card.rare_category_regroupings
    # 6b: el corte efectivo es RESULTADO; lo declarado no se toca.
    assert sc.study.config.binning.cat_cutoff == pytest.approx(0.01)
    lineas = "\n".join(sc.summary("binning").lines)
    assert "Categorías con muy pocas operaciones agrupadas para poder calcular su WoE" in lineas
    assert "«proposito»" in lineas and "ninguna incumplida" in lineas
    for slug in ("categoria_rara", "rare_category", "cat_cutoff"):
        assert slug not in lineas, slug


def test_el_mismo_config_reproduce_el_mismo_corte_y_el_mismo_binning(
    _cartera_con_categoria_rara: Path, tmp_path: Path
) -> None:
    """6b: la reproducibilidad viene de que la regla es determinista, no de guardar el número; y
    el `config_hash` identifica lo declarado, así que no se mueve."""
    corridas = []
    for nombre in ("primera", "segunda"):
        sc = nikodym.Scorecard(
            _cartera_con_categoria_rara,
            target={"col": "bad_flag", "op": "==", "value": 1},
            id="loan_id",
            partition="random",
            name=nombre,
            run_dir=tmp_path / nombre,
        )
        sc.run()
        corridas.append(sc)

    primera, segunda = (sc.study for sc in corridas)
    # El hash congelado en el lineage es el del config guardado: el corte no se escribió en él.
    for study in (primera, segunda):
        assert study.lineage_bundle().config_hash == config_hash(study.config)
    assert config_hash(primera.config) == config_hash(segunda.config)
    a = primera.artifacts.get("binning", "binning_card").rare_category_regroupings["proposito"]
    b = segunda.artifacts.get("binning", "binning_card").rare_category_regroupings["proposito"]
    assert a == b
    pd.testing.assert_frame_equal(
        primera.artifacts.get("binning", "tables")["proposito"],
        segunda.artifacts.get("binning", "tables")["proposito"],
    )


def test_los_conteos_son_los_de_la_muestra_ajustada_no_los_del_archivo(tmp_path: Path) -> None:
    """🔴 Test 5: `RARO` tiene un malo en el ARCHIVO, pero cae en la cohorte fuera de tiempo; en
    desarrollo —con lo que se ajusta— queda sin ninguno. La regla entra, y sus conteos son los de
    la tabla del paso, no los del archivo."""
    frame, y = _cartera(NIVELES_RESCATABLES, semilla=11)
    datos = frame.reset_index().assign(bad_flag=y.to_numpy(), cohorte="2024Q1")
    # Una operación RARO más, incumplida, en la cohorte que se reserva como fuera de tiempo, junto
    # a un bloque de operaciones corrientes para que esa muestra tenga malos y buenos.
    extra = pd.DataFrame(
        {
            "loan_id": ["op-9000"] + [f"op-{9001 + i}" for i in range(200)],
            "proposito": ["RARO"] + ["A"] * 200,
            "ingreso": [0.5, *np.linspace(-1, 1, 200)],
            "bad_flag": [1] + [1] * 40 + [0] * 160,
            "cohorte": "2024Q2",
        }
    )
    datos = pd.concat([datos, extra], ignore_index=True)
    ruta = tmp_path / "cartera_raro_con_un_malo.parquet"
    datos.to_parquet(ruta)
    en_archivo = datos[datos["proposito"] == "RARO"]
    assert (len(en_archivo), int(en_archivo["bad_flag"].sum())) == (9, 1)

    sc = nikodym.Scorecard(
        ruta,
        target={"col": "bad_flag", "op": "==", "value": 1},
        id="loan_id",
        cohort="cohorte",
        oot_cohorts=["2024Q2"],
        name="raro_oot",
        run_dir=tmp_path / "run",
    )
    sc.run()

    assert sc.study.run_context.status == "done", sc.study.run_context.error
    reagrupada = sc.study.artifacts.get("binning", "binning_card").rare_category_regroupings[
        "proposito"
    ]
    assert reagrupada.n_events == 0
    assert reagrupada.n_obs < 9


# ───────────────────────── revisión adversarial del código ─────────────────────────


def test_una_variable_no_optima_se_descarta_como_antes_y_no_dispara_la_regla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 Pasada 1 de Codex: con `require_optimal`, una variable de estado no óptimo se descarta
    y la corrida sigue. La regla corría ANTES de ese descarte: podía reajustarla —cambiando
    números— o detener una corrida que antes terminaba. Ahora no la mira."""
    from optbinning import OptimalBinning

    estado_real = OptimalBinning.status.fget

    def estado(self: OptimalBinning) -> str:
        return "FEASIBLE" if self.name == "proposito" else estado_real(self)

    monkeypatch.setattr(OptimalBinning, "status", property(estado))
    binner, sink = _ajustar(NIVELES_RESCATABLES)

    assert binner.skipped_variables_["proposito"] == "solver_status:FEASIBLE"
    assert binner.feature_columns_ == ("ingreso",)
    assert binner.rare_category_regroupings_ == {}
    assert _decisiones(sink, "categoria_rara_intento_reagrupar") == []


@pytest.mark.parametrize(
    "niveles",
    [
        pytest.param({"A": (992, 200), "RARO": (8, 0)}, id="dos-categorias"),
        pytest.param({"A": (496, 100), "B": (496, 100), "RARO": (8, 0)}, id="empate-arriba"),
    ],
)
def test_si_reagrupar_mandaria_todas_a_otros_no_se_intenta_y_la_salida_es_ejecutable(
    niveles: dict[str, tuple[int, int]],
) -> None:
    """🔴 Pasada 1 de Codex: si el menor corte que junta dos niveles deja TODAS las categorías bajo
    el umbral, OptBinning no puede ajustar. No se intenta —el trail no registra un intento
    imposible— y el mensaje sólo ofrece excluir la variable: subir el umbral no lo resuelve."""
    frame, y = _cartera(niveles)
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("proposito", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()

    with pytest.raises(BinningFitError) as error:
        binner.fit(frame, y, audit=sink)

    mensaje = str(error.value)
    assert "«proposito»" in mensaje and "«RARO»" in mensaje
    assert "excluir la variable" in mensaje
    assert "variable_overrides" not in mensaje
    assert _decisiones(sink, "categoria_rara_intento_reagrupar") == []


def test_si_el_reintento_no_basta_y_subir_el_umbral_tampoco_la_unica_salida_es_excluir() -> None:
    """Pasada 1 de Codex: tras juntar las dos raras sigue sin malos, y la categoría que viene es
    la mayoritaria —juntarla dejaría todo en «raras»—. Hubo un intento, y el mensaje no ofrece un
    umbral que no resuelve nada."""
    frame, y = _cartera({"A": (970, 200), "E": (12, 0), "RARO": (8, 0)})
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("proposito", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()

    with pytest.raises(BinningFitError) as error:
        binner.fit(frame, y, audit=sink)

    mensaje = str(error.value)
    assert "Se reagrupó con las categorías más raras" in mensaje
    assert mensaje.endswith("Puedes excluir la variable.")
    assert "variable_overrides" not in mensaje
    assert len(_decisiones(sink, "categoria_rara_intento_reagrupar")) == 1
    assert _decisiones(sink, "categoria_rara_reagrupada") == []


def test_con_pesos_se_publican_operaciones_y_no_masas_ponderadas() -> None:
    """🔴 Pasada 2 de Codex: con pesos, la tabla de OptBinning trae masas —y 0.20 las trunca: ocho
    filas con un malo a peso 0,5 salen como `Count 3, Event 0`—. La regla decide con la misma
    tabla que la validación de siempre (que con esos pesos también moría), pero lo que publica y
    dice son OPERACIONES reales: 8 y 1 incumplida, no 3 y ninguna."""
    frame, y = _cartera({**NIVELES_RESCATABLES, "RARO": (8, 1)})
    pesos = pd.Series(0.5, index=frame.index)
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("proposito", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()

    binner.fit(frame, y, sample_weight=pesos, audit=sink)

    reagrupada = binner.rare_category_regroupings_["proposito"]
    assert (reagrupada.n_obs, reagrupada.n_events) == (8, 1)
    intento = _decisiones(sink, "categoria_rara_intento_reagrupar")[0]
    assert (intento["valor"]["operaciones"], intento["valor"]["incumplidas"]) == (8, 1)


def test_el_sumidero_vale_solo_para_su_ajuste() -> None:
    """🔴 Pasada 2 de Codex: el sumidero quedaba guardado en el binner, así que un segundo ajuste
    sin `audit` escribía en el trail anterior —o fallaba si ese trail ya estaba cerrado—."""

    class TrailCerrable(InMemoryAuditSink):
        cerrado = False

        def emit(self, event: object) -> None:
            if self.cerrado:
                raise RuntimeError("trail cerrado")
            super().emit(event)  # type: ignore[arg-type]

    frame, y = _cartera(NIVELES_RESCATABLES)
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("proposito", "ingreso"), exclude_columns=())
    primero = TrailCerrable()
    binner.fit(frame, y, audit=primero)
    antes = len(primero.events)
    assert antes >= 2
    primero.cerrado = True

    binner.fit(frame, y)  # sin sumidero: no puede escribir en el anterior

    assert len(primero.events) == antes
    assert "proposito" in binner.rare_category_regroupings_


def test_un_reajuste_no_optimo_es_un_reintento_fallido_y_no_se_declara_exito(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 Pasada 3 de Codex: si el reajuste no alcanza el estado óptimo que exige el config, la
    recolección descartaría la variable; declarar «reagrupada» y publicar el corte afirmaría algo
    que no ocurrió, y descartar la variable es decisión de la persona (§1). Es un reintento
    fallido: el motor se detiene con su diagnóstico y el trail sólo registra el intento."""
    from optbinning import OptimalBinning

    estado_real = OptimalBinning.status.fget

    def estado(self: OptimalBinning) -> str:
        reajuste = self.name == "proposito" and self.cat_cutoff not in (None, 0.01)
        return "FEASIBLE" if reajuste else estado_real(self)

    monkeypatch.setattr(OptimalBinning, "status", property(estado))
    frame, y = _cartera(NIVELES_RESCATABLES)
    binner = WoEBinner.from_config(BinningConfig())
    binner.set_params(feature_columns=("proposito", "ingreso"), exclude_columns=())
    sink = InMemoryAuditSink()

    with pytest.raises(BinningFitError) as error:
        binner.fit(frame, y, audit=sink)

    assert "FEASIBLE" in str(error.value)
    assert len(_decisiones(sink, "categoria_rara_intento_reagrupar")) == 1
    assert _decisiones(sink, "categoria_rara_reagrupada") == []
