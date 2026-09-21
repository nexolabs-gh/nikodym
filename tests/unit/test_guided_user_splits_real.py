"""Los cortes fijados desde la puerta guiada llegan a OptBinning de verdad (§8-9 (a)).

Los tests de ``test_guided_decisiones`` usan el doble determinista de OptBinning; éste corre el
motor real sobre el dataset del paquete —como ``test_simplicidad_scorecard``— porque lo que se
promete («junta estos dos tramos», «fija estos cortes») sólo se prueba viendo los tramos que el
solver devuelve con ``user_splits``/``user_splits_fixed``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("optbinning", reason="exige nikodym[scoring]")


def _puerta(tmp_path: Path) -> Any:
    from nikodym import Scorecard
    from nikodym.ui.datasets import materialize

    datos = materialize("consumo_comportamiento", workdir=tmp_path / "datasets")
    sc = Scorecard(
        datos,
        target="bad_flag",
        id="loan_id",
        cohort="cohorte",
        oot_cohorts=["2024Q2"],
        run_dir=tmp_path / "corridas",
        name="cortes",
    )
    sc._echo = lambda _texto: None
    return sc


def _splits(sc: Any, columna: str) -> list[float]:
    binner = sc.study.artifacts.get("binning", "process")
    return [float(s) for s in binner.process_.get_binned_variable(columna).splits]


def test_set_bins_y_merge_bins_fijan_los_tramos_en_optbinning(tmp_path: Path) -> None:
    sc = _puerta(tmp_path)
    sc.run(until="binning")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    de_fabrica = _splits(sc, "antiguedad_meses")
    assert len(de_fabrica) >= 3
    tramos = sc.bins("antiguedad_meses")
    assert list(tramos.columns)[:2] == ["Tramo", "Rango"]
    assert len(tramos.index) == len(de_fabrica) + 1

    sc.set_bins("antiguedad_meses", [24, 60], reason="los tramos del manual de crédito")
    sc.run(until="binning")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert _splits(sc, "antiguedad_meses") == [24.0, 60.0]
    assert len(sc.bins("antiguedad_meses").index) == 3
    resumen = sc.summary("binning")
    assert "antiguedad_meses" in " ".join(resumen.lines)

    sc.merge_bins("antiguedad_meses", [2, 3], reason="misma tasa de malos")
    sc.run(until="binning")
    assert sc.study.run_context.status == "done", sc.study.run_context.error
    assert _splits(sc, "antiguedad_meses") == [24.0]
    assert len(sc.bins("antiguedad_meses").index) == 2
    # La decisión vive en el config: la puerta completa la reproduce tal cual.
    override = next(o for o in sc.config.binning.variable_overrides if o.name == "antiguedad_meses")
    assert override.user_splits == (24.0,) and override.user_splits_fixed == (True,)
    assert np.isfinite(override.user_splits).all()
