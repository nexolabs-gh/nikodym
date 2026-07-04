"""Tests de ``WoEBinner``: contrato sklearn, WoE/IV, special values y casos borde."""

# ruff: noqa: N803,N806

from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import textwrap
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from sklearn.base import clone

import nikodym.binning
import nikodym.binning.transformer as transformer_module
from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.exceptions import BinningFitError, BinningTransformError
from nikodym.binning.transformer import WoEBinner
from nikodym.core.exceptions import MissingDependencyError
from nikodym.data.special import MaskedFrame


def _index(n: int) -> pd.Index:
    return pd.Index([f"op-{position:03d}" for position in range(n)], name="loan_id")


def _golden_frame() -> tuple[pd.DataFrame, pd.Series]:
    """Dataset manual: dos bins con buenos/malos 3/1 y 1/3."""
    index = _index(8)
    X = pd.DataFrame({"score": [0, 0, 1, 1, 2, 2, 3, 3]}, index=index)
    y = pd.Series([0, 0, 0, 1, 0, 1, 1, 1], index=index, name="target")
    return X, y


def _binner(**kwargs: Any) -> WoEBinner:
    params: dict[str, object] = {
        "solver": "mip",
        "max_n_prebins": 4,
        "max_n_bins": 4,
        "min_bin_size": 0.1,
        "time_limit": 5,
        "monotonic_trend": None,
        "keep_structural_columns": False,
    }
    params.update(kwargs)
    return WoEBinner(**params)


@pytest.fixture(autouse=True)
def _fake_optbinning_process(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Evita importar OR-Tools en pytest; los smokes reales van en subprocess."""
    if request.node.name in {
        "test_missing_dependency_error_optbinning",
        "test_import_binning_process_success_sin_importar_optbinning_real",
    }:
        return
    monkeypatch.setattr(transformer_module, "_import_binning_process", lambda: _FakeBinningProcess)


class _FakeBinningTable:
    """Tabla mínima compatible con ``OptimalBinning.binning_table``."""

    def __init__(self, table: pd.DataFrame) -> None:
        self._table = table.copy(deep=True)

    def build(self, add_totals: bool = True) -> pd.DataFrame:
        del add_totals
        return self._table.copy(deep=True)


class _FakeBinnedVariable:
    """Variable binneada mínima para ``get_binned_variable``."""

    def __init__(self, *, dtype: str, status: str, table: pd.DataFrame) -> None:
        self.dtype = dtype
        self.status = status
        self.binning_table = _FakeBinningTable(table)


class _FakeBinningProcess:
    """Doble de prueba determinista de ``optbinning.BinningProcess``."""

    def __init__(
        self,
        variable_names: list[str],
        *,
        categorical_variables: list[str] | None = None,
        special_codes: dict[str, list[object]] | None = None,
        binning_fit_params: dict[str, dict[str, object]] | None = None,
        **kwargs: object,
    ) -> None:
        del kwargs
        self.variable_names = variable_names
        self.categorical_variables = set(categorical_variables or [])
        self.special_codes = special_codes or {}
        self.binning_fit_params = binning_fit_params or {}
        self._binned_variables: dict[str, _FakeBinnedVariable] = {}
        self._summary: pd.DataFrame | None = None
        self._woe_maps: dict[str, list[tuple[object, float]]] = {}

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weight: pd.Series | None = None,
        check_input: bool = False,
    ) -> _FakeBinningProcess:
        del sample_weight, check_input
        rows: list[dict[str, object]] = []
        for name in self.variable_names:
            dtype = "categorical" if name in self.categorical_variables else "numerical"
            if dtype == "numerical" and not pd.api.types.is_numeric_dtype(X[name]):
                dtype = "categorical"
            status = "FEASIBLE" if name == "slow_solver" else "OPTIMAL"
            table, woe_map = _fake_table_for_series(
                name,
                X[name],
                y,
                dtype=dtype,
                special_codes=self.special_codes.get(name, []),
            )
            self._binned_variables[name] = _FakeBinnedVariable(
                dtype=dtype,
                status=status,
                table=table,
            )
            self._woe_maps[name] = woe_map
            rows.append(
                {
                    "name": name,
                    "dtype": dtype,
                    "status": status,
                    "n_bins": _n_model_bins(table),
                    "iv": float(table.loc[table.index != "Totals", "IV"].sum()),
                    "js": float(table.loc[table.index != "Totals", "JS"].sum()),
                    "gini": 0.5,
                    "quality_score": 0.05,
                }
            )
        self._summary = pd.DataFrame(rows)
        return self

    def summary(self) -> pd.DataFrame:
        assert self._summary is not None
        summary = self._summary.copy(deep=True)
        summary["selected"] = True
        return summary[
            ["name", "dtype", "status", "selected", "n_bins", "iv", "js", "gini", "quality_score"]
        ]

    def get_binned_variable(self, name: str) -> _FakeBinnedVariable:
        return self._binned_variables[name]

    def transform(
        self,
        X: pd.DataFrame,
        *,
        metric: str,
        metric_special: str | float,
        metric_missing: str | float,
        check_input: bool,
    ) -> pd.DataFrame:
        del metric, check_input
        transformed: dict[str, list[float]] = {}
        for name in self.variable_names:
            special_values = set(self.special_codes.get(name, []))
            values: list[float] = []
            for value in X[name].tolist():
                values.append(
                    _fake_transform_value(
                        value,
                        self._woe_maps[name],
                        special_values=special_values,
                        metric_special=metric_special,
                        metric_missing=metric_missing,
                    )
                )
            transformed[name] = values
        return pd.DataFrame(transformed, index=X.index)


def _fake_table_for_series(
    name: str,
    series: pd.Series,
    y: pd.Series,
    *,
    dtype: str,
    special_codes: list[object],
) -> tuple[pd.DataFrame, list[tuple[object, float]]]:
    """Construye una tabla WoE manual para el doble de OptBinning."""
    if dtype == "categorical":
        bins = _categorical_bins(series)
    elif name == "risk":
        bins = [
            ("(-inf, 0.50)", lambda value: float(value) < 0.5),
            ("[0.50, 1.50)", lambda value: 0.5 <= float(value) < 1.5),
            ("[1.50, inf)", lambda value: float(value) >= 1.5),
        ]
    elif name == "flat":
        bins = [
            ("(-inf, 1.50)", lambda value: float(value) < 1.5),
            ("[1.50, 2.50)", lambda value: 1.5 <= float(value) < 2.5),
            ("[2.50, inf)", lambda value: float(value) >= 2.5),
        ]
    else:
        bins = [
            ("(-inf, 1.50)", lambda value: float(value) < 1.5),
            ("[1.50, inf)", lambda value: float(value) >= 1.5),
        ]

    rows: list[dict[str, object]] = []
    woe_map: list[tuple[object, float]] = []
    total_good = int(y.eq(0).sum())
    total_bad = int(y.eq(1).sum())
    assigned = pd.Series(False, index=series.index)
    special_set = set(special_codes)
    special_mask = series.isin(special_set).fillna(False).astype("bool")
    missing_mask = series.isna()

    for label, predicate in bins:

        def matches(value: object, current_predicate: Any = predicate) -> bool:
            if pd.isna(value) or value in special_set:
                return False
            return bool(current_predicate(value))

        mask = series.map(matches)
        mask = mask.fillna(False).astype("bool")
        assigned = assigned | mask
        row, woe = _aggregate_fake_row(label, mask, y, total_good, total_bad, len(series))
        rows.append(row)
        woe_map.append((label, woe))

    special_row, special_woe = _aggregate_fake_row(
        "Special",
        special_mask,
        y,
        total_good,
        total_bad,
        len(series),
    )
    missing_row, missing_woe = _aggregate_fake_row(
        "Missing",
        missing_mask & ~assigned,
        y,
        total_good,
        total_bad,
        len(series),
    )
    rows.extend([special_row, missing_row, _totals_row(rows, total_good, total_bad, len(series))])
    woe_map.extend([("Special", special_woe), ("Missing", missing_woe)])
    table = pd.DataFrame(rows)
    table.index = [*list(range(len(rows) - 1)), "Totals"]
    return table, woe_map


def _categorical_bins(series: pd.Series) -> list[tuple[object, Any]]:
    values = set(series.dropna().astype(str))
    if values <= {"A", "B"}:
        return [
            ("[A]", lambda value: str(value) == "A"),
            ("[B]", lambda value: str(value) == "B"),
        ]
    return [
        ("[A]", lambda value: str(value) == "A"),
        ("[C]", lambda value: str(value) == "C"),
        ("[B]", lambda value: str(value) == "B"),
        ("[R1, R2]", lambda value: str(value) in {"R1", "R2"}),
    ]


def _aggregate_fake_row(
    label: object,
    mask: pd.Series,
    y: pd.Series,
    total_good: int,
    total_bad: int,
    total_count: int,
) -> tuple[dict[str, object], float]:
    count = int(mask.sum())
    bad = int(y.loc[mask].eq(1).sum())
    good = int(y.loc[mask].eq(0).sum())
    if count > 0 and good > 0 and bad > 0:
        dist_good = good / total_good
        dist_bad = bad / total_bad
        woe = math.log(dist_good / dist_bad)
        iv = (dist_good - dist_bad) * woe
    else:
        woe = 0.0
        iv = 0.0
    return (
        {
            "Bin": label,
            "Count": count,
            "Count (%)": count / total_count,
            "Non-event": good,
            "Event": bad,
            "Event rate": 0.0 if count == 0 else bad / count,
            "WoE": woe,
            "IV": iv,
            "JS": iv / 8.4,
        },
        woe,
    )


def _totals_row(
    rows: list[dict[str, object]],
    total_good: int,
    total_bad: int,
    total_count: int,
) -> dict[str, object]:
    return {
        "Bin": "",
        "Count": total_count,
        "Count (%)": 1.0,
        "Non-event": total_good,
        "Event": total_bad,
        "Event rate": total_bad / total_count,
        "WoE": "",
        "IV": float(sum(float(row["IV"]) for row in rows)),
        "JS": float(sum(float(row["JS"]) for row in rows)),
    }


def _n_model_bins(table: pd.DataFrame) -> int:
    model_bins = table.loc[
        (table.index != "Totals")
        & ~table["Bin"].isin(["Special", "Missing"])
        & table["Count"].gt(0)
    ]
    return len(model_bins)


def _fake_transform_value(
    value: object,
    woe_map: list[tuple[object, float]],
    *,
    special_values: set[object],
    metric_special: str | float,
    metric_missing: str | float,
) -> float:
    if value in special_values:
        return _metric_or_empirical(metric_special, woe_map, "Special")
    if pd.isna(value):
        return _metric_or_empirical(metric_missing, woe_map, "Missing")
    numeric_value = (
        float(value) if isinstance(value, int | float | np.integer | np.floating) else None
    )
    for label, woe in woe_map:
        if label == "(-inf, 0.50)" and numeric_value is not None and numeric_value < 0.5:
            return woe
        if label == "[0.50, 1.50)" and numeric_value is not None and 0.5 <= numeric_value < 1.5:
            return woe
        if label == "(-inf, 1.50)" and numeric_value is not None and numeric_value < 1.5:
            return woe
        if label == "[1.50, 2.50)" and numeric_value is not None and 1.5 <= numeric_value < 2.5:
            return woe
        if label in {"[1.50, inf)", "[2.50, inf)"} and numeric_value is not None:
            left = 1.5 if label == "[1.50, inf)" else 2.5
            if numeric_value >= left:
                return woe
        if isinstance(label, str) and str(value) in label.replace("[", "").replace("]", "").split(
            ", "
        ):
            return woe
    return 0.0


def _metric_or_empirical(
    metric: str | float,
    woe_map: list[tuple[object, float]],
    label: str,
) -> float:
    if metric == "empirical":
        for candidate_label, woe in woe_map:
            if candidate_label == label:
                return woe
        return 0.0
    return float(metric)


def test_reexport_perezoso_publica_woebinner() -> None:
    """``nikodym.binning.WoEBinner`` carga el transformer bajo demanda."""
    assert nikodym.binning.WoEBinner is WoEBinner


def test_import_binning_process_success_sin_importar_optbinning_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El helper de import devuelve ``BinningProcess`` desde un módulo compatible."""

    class FakeModule:
        BinningProcess = _FakeBinningProcess

    def fake_import_module(name: str) -> object:
        assert name == "optbinning"
        return FakeModule()

    monkeypatch.setattr(transformer_module.importlib, "import_module", fake_import_module)

    assert transformer_module._import_binning_process() is _FakeBinningProcess


def test_woebinner_ejerce_optbinning_real_en_subprocess() -> None:
    """Smoke real con golden WoE/IV para no cargar OR-Tools dentro del proceso pytest."""
    script = textwrap.dedent(
        """
        import math

        import pandas as pd
        from nikodym.binning.transformer import WoEBinner

        index = pd.Index([f"op-{i}" for i in range(8)], name="loan_id")
        X = pd.DataFrame({"score": [0, 0, 1, 1, 2, 2, 3, 3]}, index=index)
        y = pd.Series([0, 0, 0, 1, 0, 1, 1, 1], index=index)
        binner = WoEBinner(
            feature_columns=("score",),
            solver="mip",
            max_n_prebins=4,
            max_n_bins=4,
            min_bin_size=0.1,
            time_limit=5,
            monotonic_trend=None,
            keep_structural_columns=False,
        )
        transformed = binner.fit_transform(X, y)
        table = binner.tables_["score"]
        log3 = math.log(3.0)
        assert binner.process_.summary().loc[0, "status"] == "OPTIMAL"
        assert transformed.columns.tolist() == ["score__woe"]
        assert table.loc[0, "Non-event"] == 3
        assert table.loc[0, "Event"] == 1
        assert abs(float(table.loc[0, "WoE"]) - log3) < 1e-12
        assert abs(float(table.loc[1, "WoE"]) + log3) < 1e-12
        assert abs(float(binner.summary_.loc[0, "iv"]) - log3) < 1e-12
        assert abs(float(transformed.iloc[0, 0]) - log3) < 1e-12
        assert abs(float(transformed.iloc[-1, 0]) + log3) < 1e-12
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_woebinner_default_binnea_numericas_continuas_reales_en_subprocess() -> None:
    """Regresión B0 (P0): con OptBinning REAL y config DEFAULT, las numéricas continuas
    mezcladas con una categórica se binnean de verdad (dtype numerical, IV>0, bins monótonos).

    Este es el test que habría cazado la ruta principal rota: (a) el solver default 'cp' se cuelga
    sobre continuas → aquí el subprocess haría timeout; (b) ``check_array(dtype=None)`` colapsa el
    frame mixto (float + object) a un array object y OptBinning trataba TODA numérica como
    categorical (1 bin, IV=0, descartada en silencio) → aquí las numéricas quedarían fuera de
    ``feature_columns_``. Se corre en subprocess para no cargar OR-Tools en el proceso pytest.
    """
    script = textwrap.dedent(
        """
        import numpy as np
        import pandas as pd
        from nikodym.binning.transformer import WoEBinner

        rng = np.random.default_rng(20260704)
        n = 2500
        income = rng.uniform(0.0, 1.0, n)   # continua con señal
        util = rng.uniform(0.0, 1.0, n)     # continua con señal
        region = rng.choice(["A", "B", "C"], n)   # categórica (columna object)
        lin = -0.5 - 2.5 * income + 2.0 * util + (region == "C") * 1.2
        p = 1.0 / (1.0 + np.exp(-lin))
        y = (rng.uniform(0.0, 1.0, n) < p).astype(int)
        X = pd.DataFrame({"income": income, "util": util, "region": region})

        # Config 100% DEFAULT: sin override de solver ni de dtype.
        binner = WoEBinner()
        woe = binner.fit_transform(X, pd.Series(y))

        selected = set(binner.feature_columns_)
        assert {"income", "util"} <= selected, f"numericas descartadas: {selected}"

        summary = binner.summary_.set_index("name")
        for col in ("income", "util"):
            row = summary.loc[col]
            assert row["dtype"] == "numerical", (col, row["dtype"])
            assert row["status"] == "OPTIMAL", (col, row["status"])
            assert bool(row["selected"]) is True
            assert int(row["n_bins"]) >= 3, (col, row["n_bins"])
            assert float(row["iv"]) > 0.05, (col, row["iv"])
        assert summary.loc["region", "dtype"] == "categorical"

        # Bins monótonos por defecto (monotonic_trend='auto_asc_desc') en una numérica.
        table = binner.tables_["income"]
        is_interval = table["Bin"].astype(str).str.startswith(("[", "("))
        woe_bins = table.loc[is_interval, "WoE"].astype(float).tolist()
        assert len(woe_bins) >= 3
        diffs = [b - a for a, b in zip(woe_bins, woe_bins[1:])]
        non_decreasing = all(d >= -1e-9 for d in diffs)
        non_increasing = all(d <= 1e-9 for d in diffs)
        assert non_decreasing or non_increasing, woe_bins

        # La transformación WoE produce columnas finitas para las numéricas.
        for col in ("income", "util"):
            values = woe[f"{col}__woe"].to_numpy(dtype="float64")
            assert np.isfinite(values).all()

        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_reexport_woebinner_sin_sklearn_falla_con_missing_dependency_espanol() -> None:
    """El export lazy traduce sklearn ausente a ``MissingDependencyError`` accionable."""
    script = textwrap.dedent(
        """
        import sys

        import nikodym.binning
        from nikodym.core.exceptions import MissingDependencyError


        class BlockSklearn:
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "sklearn" or fullname.startswith("sklearn."):
                    raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
                return None


        sys.meta_path.insert(0, BlockSklearn())
        try:
            nikodym.binning.WoEBinner
        except MissingDependencyError as exc:
            assert "instale nikodym[scoring]" in str(exc)
        else:
            raise AssertionError("WoEBinner no tradujo la ausencia de sklearn")
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_import_transformer_sin_sklearn_cubre_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La rama de import de ``sklearn`` ausente queda cubierta sin descargar el módulo real."""

    class BlockSklearn:
        def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
            del path, target
            if fullname == "sklearn" or fullname.startswith("sklearn."):
                raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")

    sklearn_modules = [
        name for name in sys.modules if name == "sklearn" or name.startswith("sklearn.")
    ]
    for name in sklearn_modules:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [BlockSklearn(), *sys.meta_path])

    module_path = transformer_module.__file__
    assert module_path is not None
    spec = importlib.util.spec_from_file_location(
        "nikodym.binning._missing_sklearn_transformer_test",
        module_path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        loader.exec_module(module)


def test_golden_woe_iv_manual_y_no_muta_inputs() -> None:
    """WoE/IV canónico: goods/bads 3/1 y 1/3 → WoE=±ln(3), IV total=ln(3)."""
    X, y = _golden_frame()
    original_X = X.copy(deep=True)
    original_y = y.copy(deep=True)

    binner = _binner(feature_columns=("score",)).fit(X, y)
    transformed = binner.transform(X)

    log3 = math.log(3.0)
    table = binner.tables_["score"]
    assert binner.feature_columns_ == ("score",)
    assert binner.woe_column_map_ == {"score": "score__woe"}
    assert binner.skipped_variables_ == {}
    assert table.loc[0, "Non-event"] == 3
    assert table.loc[0, "Event"] == 1
    assert table.loc[0, "WoE"] == pytest.approx(log3)
    assert table.loc[0, "IV"] == pytest.approx(0.5 * log3)
    assert table.loc[1, "Non-event"] == 1
    assert table.loc[1, "Event"] == 3
    assert table.loc[1, "WoE"] == pytest.approx(-log3)
    assert table.loc[1, "IV"] == pytest.approx(0.5 * log3)
    assert binner.summary_.loc[0, "iv"] == pytest.approx(log3)
    assert binner.summary_.loc[0, "iv_band"] == "suspicious"

    expected = pd.DataFrame(
        {"score__woe": [log3, log3, log3, log3, -log3, -log3, -log3, -log3]},
        index=X.index,
    )
    assert_frame_equal(transformed, expected)
    assert np.isfinite(transformed["score__woe"].to_numpy()).all()
    assert_frame_equal(X, original_X)
    assert_series_equal(y, original_y)


def test_keep_structural_columns_conserva_solo_columnas_de_data() -> None:
    """Las columnas estructurales se preservan sin reintroducir features crudas."""
    X, y = _golden_frame()
    frame = X.assign(
        target=y,
        label_status=pd.Categorical(["bueno", "bueno", "bueno", "malo"] * 2),
        partition=pd.Categorical(["desarrollo"] * 8),
        ttd=True,
    )

    transformed = _binner(feature_columns=("score",), keep_structural_columns=True).fit_transform(
        frame, y
    )

    assert transformed.columns.tolist() == [
        "target",
        "label_status",
        "partition",
        "ttd",
        "score__woe",
    ]
    assert "score" not in transformed.columns
    assert transformed.index.equals(frame.index)


def test_anti_leakage_transform_no_modifica_tablas_ni_summary() -> None:
    """Transformar OOT con distribución distinta no recalcula cortes, WoE ni IV."""
    X, y = _golden_frame()
    binner = _binner(feature_columns=("score",)).fit(X, y)
    original_table = binner.tables_["score"].copy(deep=True)
    original_summary = binner.summary_.copy(deep=True)

    oot = pd.DataFrame({"score": [3, 3, 3, 0]}, index=_index(4))
    transformed = binner.transform(oot)

    assert transformed["score__woe"].tolist()[:3] == pytest.approx([-math.log(3.0)] * 3)
    assert_frame_equal(binner.tables_["score"], original_table)
    assert_frame_equal(binner.summary_, original_summary)


def test_special_separate_y_as_missing_tienen_conteos_distintos() -> None:
    """Un centinela normalizado y missing genuino quedan separados o fusionados según config."""
    index = _index(12)
    raw = pd.DataFrame(
        {"score": [0, 0, 1, 1, 2, 2, 3, 3, np.nan, np.nan, -999.0, -999.0]},
        index=index,
    )
    y = pd.Series([0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1], index=index)
    mask = pd.DataFrame(False, index=index, columns=["score"])
    mask.loc[index[-2:], "score"] = True
    normalized = raw.copy(deep=True)
    normalized.loc[mask["score"], "score"] = np.nan
    special = MaskedFrame(
        frame=normalized.copy(deep=True),
        special_mask=mask.copy(deep=True),
        special_catalog={"score": [-999.0]},
    )

    separate = _binner(feature_columns=("score",), special_handling="separate").fit(
        normalized, y, special=special
    )
    as_missing = _binner(feature_columns=("score",), special_handling="as_missing").fit(
        normalized, y, special=special
    )

    separate_table = separate.tables_["score"]
    as_missing_table = as_missing.tables_["score"]
    missing_separate = separate_table.loc[separate_table["Bin"].eq("Missing")]
    special_separate = separate_table.loc[
        separate_table["Count"].eq(2) & ~separate_table["Bin"].eq("Missing")
    ]
    missing_as_missing = as_missing_table.loc[as_missing_table["Bin"].eq("Missing")]

    assert missing_separate["Count"].tolist() == [2]
    assert special_separate["Count"].tolist() == [2]
    assert missing_as_missing["Count"].tolist() == [4]
    assert separate.special_codes_ == {"score": [-999.0]}
    assert_frame_equal(normalized, special.frame)


def test_categoricas_agrupan_raros_y_unknown_transforma_neutral() -> None:
    """``cat_cutoff`` agrupa niveles raros y una categoría no vista recibe WoE neutral 0."""
    index = _index(16)
    X = pd.DataFrame(
        {"segment": ["A"] * 4 + ["B"] * 4 + ["C"] * 4 + ["R1"] * 2 + ["R2"] * 2},
        index=index,
    )
    y = pd.Series(
        [0, 0, 0, 1, 0, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1],
        index=index,
    )
    binner = _binner(
        feature_columns=("segment",),
        categorical_columns=("segment",),
        cat_cutoff=0.13,
    ).fit(X, y)

    table = binner.tables_["segment"]
    assert any("R1" in str(bin_label) and "R2" in str(bin_label) for bin_label in table["Bin"])

    oot = pd.DataFrame({"segment": ["A", "Z", "B", "R1"]}, index=_index(4))
    transformed = binner.transform(oot)

    assert transformed.loc["op-001", "segment__woe"] == 0.0
    assert binner.unknown_categories_ == {"segment": 1}


def test_monotonia_auto_asc_desc_produce_event_rate_monotona() -> None:
    """Una variable de riesgo creciente queda con event rate monótona."""
    index = _index(16)
    X = pd.DataFrame({"risk": [0] * 4 + [1] * 4 + [2] * 4 + [3] * 4}, index=index)
    y = pd.Series([0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1], index=index)

    binner = _binner(feature_columns=("risk",), monotonic_trend="auto_asc_desc").fit(X, y)

    table = binner.tables_["risk"]
    model_bins = table.loc[
        (table.index != "Totals")
        & table["Count"].gt(0)
        & ~table["Bin"].isin(["Special", "Missing"])
    ]
    rates = model_bins["Event rate"].astype(float).tolist()
    assert rates == sorted(rates) or rates == sorted(rates, reverse=True)


def test_iv_cero_se_conserva_y_normaliza_menos_cero() -> None:
    """Una variable válida sin poder predictivo se conserva con ``iv_band='none'``."""
    index = _index(8)
    X = pd.DataFrame({"flat": [0, 0, 1, 1, 2, 2, 3, 3]}, index=index)
    y = pd.Series([0, 1, 0, 1, 0, 1, 0, 1], index=index)

    binner = _binner(feature_columns=("flat",)).fit(X, y)
    transformed = binner.transform(X)

    assert binner.feature_columns_ == ("flat",)
    assert binner.summary_.loc[0, "iv"] == 0.0
    assert math.copysign(1.0, binner.summary_.loc[0, "iv"]) == 1.0
    assert binner.summary_.loc[0, "iv_band"] == "none"
    assert transformed["flat__woe"].eq(0.0).all()


@pytest.mark.parametrize(
    ("column", "values", "reason"),
    [
        ("constant", [7.0] * 8, "constant"),
        (
            "single_non_missing",
            [np.nan, np.nan, 5.0, np.nan, np.nan, np.nan, np.nan, np.nan],
            "constant",
        ),
        ("all_missing", [np.nan] * 8, "all_missing"),
    ],
)
def test_variables_no_binneables_se_saltan_con_razon(
    column: str, values: list[float], reason: str
) -> None:
    """Constantes y 100% missing se omiten sin abortar si queda otra variable válida."""
    X, y = _golden_frame()
    X[column] = values

    binner = _binner(feature_columns=("score", column)).fit(X, y)

    assert binner.feature_columns_ == ("score",)
    assert binner.skipped_variables_[column] == reason
    skipped_row = binner.summary_.loc[binner.summary_["name"].eq(column)].iloc[0]
    assert not bool(skipped_row["selected"])
    assert skipped_row["skipped_reason"] == reason


def test_fail_on_non_binnable_aborta_primera_variable_no_binneable() -> None:
    X, y = _golden_frame()
    X["constant"] = 1.0

    with pytest.raises(BinningFitError, match="Variable no binneable"):
        _binner(feature_columns=("constant", "score"), fail_on_non_binnable=True).fit(X, y)


def test_require_optimal_salta_o_falla_segun_fail_on_non_binnable() -> None:
    """Un status no óptimo queda trazado o aborta según la política configurada."""
    X, y = _golden_frame()
    X["slow_solver"] = X["score"]

    binner = _binner(feature_columns=("score", "slow_solver")).fit(X, y)
    assert binner.feature_columns_ == ("score",)
    assert binner.skipped_variables_["slow_solver"] == "solver_status:FEASIBLE"

    with pytest.raises(BinningFitError, match="solver_status:FEASIBLE"):
        _binner(feature_columns=("score", "slow_solver"), fail_on_non_binnable=True).fit(X, y)


def test_todas_las_variables_skipped_levantan_binningfiterror() -> None:
    X, y = _golden_frame()
    X = pd.DataFrame({"constant": [1.0] * len(X)}, index=X.index)

    with pytest.raises(BinningFitError, match="ninguna variable binneable"):
        _binner(feature_columns=("constant",)).fit(X, y)


@pytest.mark.parametrize("target", [[0] * 8, [1] * 8])
def test_target_degenerado_levanta_binningfiterror(target: list[int]) -> None:
    X, _ = _golden_frame()
    y = pd.Series(target, index=X.index)

    with pytest.raises(BinningFitError, match="Target degenerado"):
        _binner(feature_columns=("score",)).fit(X, y)


def test_inf_no_declarado_levanta_error_y_special_ausente_no_falla() -> None:
    X, y = _golden_frame()
    X["score"] = X["score"].astype("float64")
    X.loc[X.index[0], "score"] = math.inf
    with pytest.raises(BinningFitError, match="infinitos no declarados"):
        _binner(feature_columns=("score",)).fit(X, y)

    clean_X, clean_y = _golden_frame()
    special = MaskedFrame(
        frame=clean_X.copy(deep=True),
        special_mask=pd.DataFrame(False, index=clean_X.index, columns=clean_X.columns),
        special_catalog={"score": [-999.0]},
    )
    binner = _binner(feature_columns=("score",), special_handling="separate").fit(
        clean_X, clean_y, special=special
    )
    assert binner.special_codes_ == {"score": [-999.0]}
    special_count = binner.tables_["score"].loc[
        binner.tables_["score"]["Bin"].eq("Special"), "Count"
    ]
    assert special_count.tolist() == [0]


def test_variable_inexistente_y_transform_sin_columna_fallan_con_error_propio() -> None:
    X, y = _golden_frame()
    with pytest.raises(BinningFitError, match="inexistente"):
        _binner(feature_columns=("no_existe",)).fit(X, y)

    binner = _binner(feature_columns=("score",)).fit(X, y)
    with pytest.raises(BinningTransformError, match="faltan"):
        binner.transform(pd.DataFrame({"otra": [1.0]}, index=["oot-1"]))


def test_woe_no_defendible_por_bin_puro_levanta_binningfiterror() -> None:
    """Si una tabla deja una clase en cero, el wrapper falla aunque OptBinning ponga WoE=0."""
    index = _index(8)
    X = pd.DataFrame({"segment": ["A", "A", "A", "A", "B", "B", "B", "B"]}, index=index)
    y = pd.Series([0, 0, 0, 0, 1, 1, 1, 1], index=index)

    with pytest.raises(BinningFitError, match="clase en cero"):
        _binner(feature_columns=("segment",), categorical_columns=("segment",)).fit(X, y)


def test_reproducibilidad_y_reordenar_filas_no_cambia_tablas() -> None:
    X, y = _golden_frame()

    first = _binner(feature_columns=("score",)).fit(X, y)
    second = _binner(feature_columns=("score",)).fit(X, y)
    reversed_X = X.loc[list(reversed(X.index))]
    reversed_y = y.loc[reversed_X.index]
    reversed_fit = _binner(feature_columns=("score",)).fit(reversed_X, reversed_y)

    assert_frame_equal(first.tables_["score"], second.tables_["score"])
    assert_frame_equal(first.summary_, second.summary_)
    assert_frame_equal(first.transform(X), second.transform(X))
    assert_frame_equal(first.tables_["score"], reversed_fit.tables_["score"])
    assert_frame_equal(first.summary_, reversed_fit.summary_)


def test_contrato_sklearn_clone_get_params_set_params_y_from_config() -> None:
    cfg = BinningConfig(
        feature_columns=("score",),
        categorical_columns=("segment",),
        variable_overrides=(VariableBinningConfig(name="score", max_n_bins=4, min_bin_size=0.1),),
        solver="mip",
        max_n_bins=4,
        time_limit=5,
        output_suffix="__w",
    )

    binner = WoEBinner.from_config(cfg)
    cloned = clone(binner)

    assert cloned is not binner
    assert cloned.get_params()["output_suffix"] == "__w"
    assert cloned.get_params()["variable_overrides"] == cfg.variable_overrides
    cloned.set_params(output_suffix="__woe", max_n_bins=3)
    assert cloned.output_suffix == "__woe"
    assert cloned.max_n_bins == 3


def test_ramas_de_error_y_helpers_internos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cubre ramas defensivas del wrapper sin importar OptBinning real en pytest."""
    x, y = _golden_frame()
    pd_mod = pd
    np_mod = np

    from_dict = WoEBinner.from_config({"feature_columns": ("score",), "solver": "mip"})
    assert from_dict.feature_columns == ("score",)

    with pytest.raises(BinningFitError, match="split_digits"):
        _binner(feature_columns=("score",), split_digits=9).fit(x, y)
    with pytest.raises(BinningFitError, match=r"pandas\.DataFrame"):
        _binner(feature_columns=("score",)).fit([1, 2, 3], y)
    with pytest.raises(BinningFitError, match="DataFrame vacío"):
        _binner(feature_columns=("score",)).fit(pd.DataFrame(), pd.Series(dtype="int64"))
    with pytest.raises(BinningFitError, match="misma cantidad"):
        _binner(feature_columns=("score",)).fit(x, y.iloc[:-1])
    with pytest.raises(BinningFitError, match="sample_weight"):
        _binner(feature_columns=("score",)).fit(x, y, sample_weight=pd.Series([1.0], index=["x"]))
    with pytest.raises(BinningFitError, match="valores observados inválidos"):
        _binner(feature_columns=("score",)).fit(
            x, pd.Series([0, 1, 2, 1, 0, 1, 0, 1], index=x.index)
        )
    with pytest.raises(BinningFitError, match="duplicadas"):
        duplicated = pd.DataFrame([[0, 1], [2, 3]], columns=["score", "score"])
        _binner(feature_columns="*").fit(duplicated, pd.Series([0, 1], index=duplicated.index))
    with pytest.raises(BinningFitError, match="No hay columnas candidatas"):
        _binner(feature_columns=("score",), exclude_columns=("score",)).fit(x, y)
    with pytest.raises(BinningFitError, match="variable_overrides"):
        _binner(
            feature_columns=("score",),
            variable_overrides=(VariableBinningConfig(name="otra"),),
        ).fit(x, y)

    reversed_y = y.loc[list(reversed(y.index))]
    reversed_weight = pd.Series([1.0] * len(y), index=reversed_y.index)
    _binner(feature_columns=("score",)).fit(x, reversed_y, sample_weight=reversed_weight)
    _binner(feature_columns=("score",)).fit(x, y, sample_weight=[1.0] * len(y))
    same_index_weight = transformer_module._as_weight_series(
        pd.Series([1.0] * len(y), index=y.index),
        y.index,
        pd_mod,
    )
    assert same_index_weight is not None
    assert same_index_weight.index.equals(y.index)

    structural_frame = x.assign(target=y, label_status="bueno", partition="desarrollo", ttd=True)
    star_binner = _binner(feature_columns="*").fit(structural_frame, y)
    assert star_binner.feature_columns_ == ("score",)

    class FailingFitProcess(_FakeBinningProcess):
        def fit(
            self,
            X: pd.DataFrame,
            y: pd.Series,
            sample_weight: pd.Series | None = None,
            check_input: bool = False,
        ) -> _FakeBinningProcess:
            del X, y, sample_weight, check_input
            raise RuntimeError("fallo fake")

    monkeypatch.setattr(transformer_module, "_import_binning_process", lambda: FailingFitProcess)
    with pytest.raises(BinningFitError, match="fallo fake"):
        _binner(feature_columns=("score",)).fit(x, y)

    monkeypatch.setattr(transformer_module, "_import_binning_process", lambda: _FakeBinningProcess)
    with pytest.raises(BinningFitError, match="variables publicables"):
        _binner(feature_columns=("slow_solver",)).fit(x.rename(columns={"score": "slow_solver"}), y)

    binner = WoEBinner(
        feature_columns=("score",),
        solver="mip",
        max_n_prebins=4,
        max_n_bins=4,
        min_bin_size=0.1,
        time_limit=5,
        monotonic_trend=None,
        keep_structural_columns=True,
    ).fit(x, y)
    assert binner.transform(x).columns.tolist() == ["score__woe"]

    def fail_transform(*args: object, **kwargs: object) -> pd.DataFrame:
        del args, kwargs
        raise RuntimeError("transform roto")

    binner.process_.transform = fail_transform
    with pytest.raises(BinningTransformError, match="transform roto"):
        binner.transform(x)

    binner = _binner(feature_columns=("score",)).fit(x, y)

    def inf_transform(*args: object, **kwargs: object) -> pd.DataFrame:
        del args, kwargs
        return pd.DataFrame({"score": [math.inf] * len(x)}, index=x.index)

    binner.process_.transform = inf_transform
    with pytest.raises(BinningTransformError, match="no finito"):
        binner.transform(x)

    special = MaskedFrame(
        frame=x.copy(deep=True),
        special_mask=pd.DataFrame(False, index=x.index, columns=["otra"]),
        special_catalog={"score": [-999.0]},
    )
    with pytest.raises(BinningFitError, match="inconsistentes"):
        _binner(feature_columns=("score",)).fit(x, y, special=special)
    special = MaskedFrame(
        frame=x.copy(deep=True),
        special_mask=pd.DataFrame(False, index=x.index[:-1], columns=["score"]),
        special_catalog={"score": [-999.0]},
    )
    with pytest.raises(BinningFitError, match="no cubre"):
        _binner(feature_columns=("score",)).fit(x, y, special=special)
    no_codes = MaskedFrame(
        frame=x.copy(deep=True),
        special_mask=pd.DataFrame(False, index=x.index, columns=["score"]),
        special_catalog={"otra": [-999.0]},
    )
    state_without_codes = transformer_module._prepare_special_state(
        special=no_codes,
        columns=("score",),
        index=x.index,
        special_handling="separate",
    )
    assert state_without_codes.codes == {}

    mask = pd.DataFrame(False, index=x.index, columns=["score"])
    state = transformer_module.SpecialState(
        codes={"score": [-999.0]},
        mask=mask,
        fill_values={"score": -999.0, "otra": -1.0},
    )
    assert_frame_equal(transformer_module._apply_special_state(x, state, "separate", pd_mod), x)
    other_index = pd.DataFrame({"score": [1.0]}, index=["sin-cruce"])
    assert_frame_equal(
        transformer_module._apply_special_state(other_index, state, "separate", pd_mod),
        other_index,
    )

    infinite = pd.DataFrame({"score": [math.inf, -math.inf]}, index=["a", "b"])
    transformer_module._validate_no_undeclared_infinite(
        infinite,
        {"score": [math.inf, -math.inf]},
        error_cls=BinningFitError,
        context="fit",
    )
    transformer_module._validate_no_undeclared_infinite(
        pd.DataFrame({"score": [math.inf]}, index=["a"]),
        {"score": [math.inf]},
        error_cls=BinningFitError,
        context="fit",
    )
    with pytest.raises(BinningFitError, match="infinitos no declarados"):
        transformer_module._validate_no_undeclared_infinite(
            infinite,
            {"score": [math.inf]},
            error_cls=BinningFitError,
            context="fit",
        )

    overrides = (
        VariableBinningConfig(
            name="score",
            dtype="categorical",
            monotonic_trend="ascending",
            max_n_bins=3,
            min_bin_size=0.0,
            cat_cutoff=0.0,
        ),
    )
    params = transformer_module._build_binning_fit_params(
        _binner(
            feature_columns=("score",),
            min_bin_size=0.0,
            max_pvalue=0.0,
            cat_cutoff=0.0,
            variable_overrides=overrides,
        ),
        ["score"],
        ["score"],
    )
    assert params["score"]["dtype"] == "categorical"
    assert params["score"]["monotonic_trend"] == "ascending"
    assert params["score"]["max_n_bins"] == 3
    assert "min_bin_size" not in params["score"]
    assert transformer_module._none_if_zero(0) is None
    # Sin override de dtype, Nikodym fija el dtype explícito (fix B0): 'numerical' si la variable
    # no está en el set categórico resuelto, 'categorical' si lo está.
    default_override_params = transformer_module._build_binning_fit_params(
        _binner(
            feature_columns=("score",),
            monotonic_trend=None,
            variable_overrides=(VariableBinningConfig(name="score"),),
        ),
        ["score"],
        [],
    )
    assert default_override_params["score"]["dtype"] == "numerical"
    assert "monotonic_trend" not in default_override_params["score"]

    cat_frame = pd.DataFrame({"obj": ["a", "b"], "num": [1, 2]})
    categorical = transformer_module._categorical_variables_for_fit(
        frame=cat_frame,
        columns=["obj", "num"],
        categorical_columns=(),
        variable_overrides=(VariableBinningConfig(name="obj", dtype="numerical"),),
    )
    assert categorical == []

    class MissingSummaryProcess(_FakeBinningProcess):
        def summary(self) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "name": ["otra"],
                    "dtype": ["numerical"],
                    "status": ["OPTIMAL"],
                    "selected": [True],
                    "n_bins": [1],
                    "iv": [0.0],
                    "js": [0.0],
                    "gini": [0.0],
                    "quality_score": [0.0],
                }
            )

    skipped: dict[str, str] = {}
    tables, summary, binned, dtypes = transformer_module._collect_fitted_outputs(
        process=MissingSummaryProcess(["score"]),
        process_columns=["score"],
        skipped=skipped,
        require_optimal=True,
        fail_on_non_binnable=False,
        np=np_mod,
        pd=pd_mod,
    )
    assert tables == {}
    assert summary.empty
    assert binned == []
    assert dtypes == {}
    assert skipped == {"score": "missing_summary"}

    empty_summary = transformer_module._append_skipped_summary(
        pd.DataFrame(),
        requested_columns=("score",),
        skipped={},
        frame=x,
        pd=pd_mod,
    )
    assert empty_summary.empty

    with pytest.raises(BinningFitError, match="columnas requeridas"):
        transformer_module._validate_finite_woe_table(
            "score",
            pd.DataFrame({"WoE": [0.0]}),
            np_mod,
            pd_mod,
        )
    with pytest.raises(BinningFitError, match="WoE no finito"):
        transformer_module._validate_finite_woe_table(
            "score",
            pd.DataFrame({"WoE": [math.inf], "Count": [1], "Event": [1], "Non-event": [1]}),
            np_mod,
            pd_mod,
        )

    unknown_missing_column = transformer_module._count_unknown_categories(
        pd.DataFrame({"otra": ["x"]}),
        {"segment": {"A"}},
        {},
    )
    unknown_empty = transformer_module._count_unknown_categories(
        pd.DataFrame({"segment": [None]}),
        {"segment": {"A"}},
        {},
    )
    assert unknown_missing_column == {"segment": 0}
    assert unknown_empty == {"segment": 0}
    assert transformer_module._safe_float(None) == 0.0
    assert transformer_module._safe_float("") == 0.0
    assert math.isnan(transformer_module._normalize_float(math.nan))


def test_missing_dependency_error_optbinning(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ausencia de ``optbinning`` falla con mensaje accionable del extra scoring."""
    X, y = _golden_frame()
    real_import = transformer_module.importlib.import_module

    def fake_import_module(name: str) -> Any:
        if name == "optbinning":
            raise ImportError("sin optbinning")
        return real_import(name)

    monkeypatch.setattr(transformer_module.importlib, "import_module", fake_import_module)

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        _binner(feature_columns=("score",)).fit(X, y)
