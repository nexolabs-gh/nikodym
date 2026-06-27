"""Fixtures raíz de la suite de tests de Nikodym."""

from __future__ import annotations

import importlib
import math
import os
from typing import TYPE_CHECKING, Any

import pytest
from hypothesis import settings

from nikodym.core.seeding import SeedManager

if TYPE_CHECKING:
    import pandas as pd

settings.register_profile("dev", max_examples=50, deadline=None)
settings.register_profile(
    "ci",
    derandomize=True,
    max_examples=200,
    deadline=None,
    print_blob=True,
)
settings.register_profile(
    "nikodym_deterministic",
    derandomize=True,
    max_examples=25,
    deadline=None,
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(autouse=True)
def _pythonhashseed_fijo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija ``PYTHONHASHSEED`` para toda la suite.

    ``SeedManager.apply_global`` (que ``Study.__init__`` invoca) advierte si ``PYTHONHASHSEED`` no
    está fijo; con ``filterwarnings=error`` ese aviso rompería cualquier test que construya un
    ``Study``. Fijarlo aquí cubre todo el suite (no solo un módulo); los tests de seeding que
    prueban el aviso lo sobrescriben con ``monkeypatch.delenv`` en su propio cuerpo.
    """
    monkeypatch.setenv("PYTHONHASHSEED", "0")


@pytest.fixture
def seed_manager() -> SeedManager:
    """``SeedManager`` con la semilla por defecto del proyecto (42)."""
    return SeedManager(42)


class FakeBinningTable:
    """Tabla mínima compatible con ``OptimalBinning.binning_table``."""

    def __init__(self, table: pd.DataFrame) -> None:
        self._table = table.copy(deep=True)

    def build(self, add_totals: bool = True) -> pd.DataFrame:
        """Devuelve una copia de la tabla de bins."""
        del add_totals
        return self._table.copy(deep=True)


class FakeBinnedVariable:
    """Variable binneada mínima para ``get_binned_variable``."""

    def __init__(self, *, dtype: str, status: str, table: pd.DataFrame) -> None:
        self.dtype = dtype
        self.status = status
        self.binning_table = FakeBinningTable(table)


class FakeBinningProcess:
    """Doble determinista de ``optbinning.BinningProcess`` para tests de orquestación."""

    def __init__(
        self,
        variable_names: list[str],
        *,
        categorical_variables: list[str] | None = None,
        special_codes: dict[str, list[object]] | None = None,
        **kwargs: object,
    ) -> None:
        del kwargs
        self.variable_names = variable_names
        self.categorical_variables = set(categorical_variables or [])
        self.special_codes = special_codes or {}
        self._binned_variables: dict[str, FakeBinnedVariable] = {}
        self._summary: pd.DataFrame | None = None
        self._woe_maps: dict[str, list[tuple[object, float]]] = {}

    def fit(
        self,
        x: pd.DataFrame,
        y: pd.Series,
        sample_weight: pd.Series | None = None,
        check_input: bool = False,
    ) -> FakeBinningProcess:
        """Ajusta tablas manuales con dos bins predictivos por variable."""
        pd = _pd()
        del sample_weight, check_input
        rows: list[dict[str, object]] = []
        for name in self.variable_names:
            dtype = "categorical" if name in self.categorical_variables else "numerical"
            if dtype == "numerical" and not pd.api.types.is_numeric_dtype(x[name]):
                dtype = "categorical"
            table, woe_map = _fake_table_for_series(
                name,
                x[name],
                y,
                dtype=dtype,
                special_codes=self.special_codes.get(name, []),
            )
            self._binned_variables[name] = FakeBinnedVariable(
                dtype=dtype,
                status="OPTIMAL",
                table=table,
            )
            self._woe_maps[name] = woe_map
            rows.append(
                {
                    "name": name,
                    "dtype": dtype,
                    "status": "OPTIMAL",
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
        """Devuelve el summary global con las columnas de OptBinning usadas por Nikodym."""
        assert self._summary is not None
        summary = self._summary.copy(deep=True)
        summary["selected"] = True
        return summary[
            ["name", "dtype", "status", "selected", "n_bins", "iv", "js", "gini", "quality_score"]
        ]

    def get_binned_variable(self, name: str) -> FakeBinnedVariable:
        """Recupera una variable fiteada por nombre."""
        return self._binned_variables[name]

    def transform(
        self,
        x: pd.DataFrame,
        *,
        metric: str,
        metric_special: str | float,
        metric_missing: str | float,
        check_input: bool,
    ) -> pd.DataFrame:
        """Transforma a WoE usando los mapas manuales construidos en ``fit``."""
        pd = _pd()
        del metric, check_input
        transformed: dict[str, list[float]] = {}
        for name in self.variable_names:
            special_values = set(self.special_codes.get(name, []))
            transformed[name] = [
                _fake_transform_value(
                    value,
                    self._woe_maps[name],
                    special_values=special_values,
                    metric_special=metric_special,
                    metric_missing=metric_missing,
                )
                for value in x[name].tolist()
            ]
        return pd.DataFrame(transformed, index=x.index)


@pytest.fixture
def fake_binning_process(monkeypatch: pytest.MonkeyPatch) -> type[FakeBinningProcess]:
    """Parcha ``WoEBinner`` para usar el doble determinista de OptBinning."""
    import nikodym.binning.transformer as transformer_module

    monkeypatch.setattr(transformer_module, "_import_binning_process", lambda: FakeBinningProcess)
    return FakeBinningProcess


def _fake_table_for_series(
    name: str,
    series: pd.Series,
    y: pd.Series,
    *,
    dtype: str,
    special_codes: list[object],
) -> tuple[pd.DataFrame, list[tuple[object, float]]]:
    """Construye una tabla WoE manual para el doble de OptBinning."""
    pd = _pd()
    bins = _categorical_bins(series) if dtype == "categorical" else _numeric_bins(name)
    rows: list[dict[str, object]] = []
    woe_map: list[tuple[object, float]] = []
    total_good = int(y.eq(0).sum())
    total_bad = int(y.eq(1).sum())
    special_set = set(special_codes)
    assigned = pd.Series(False, index=series.index)

    for label, predicate in bins:
        mask = series.map(
            lambda value, current_predicate=predicate: (
                False if pd.isna(value) or value in special_set else bool(current_predicate(value))
            )
        )
        mask = mask.fillna(False).astype("bool")
        assigned = assigned | mask
        row, woe = _aggregate_fake_row(label, mask, y, total_good, total_bad, len(series))
        rows.append(row)
        woe_map.append((label, woe))

    special_mask = series.isin(special_set).fillna(False).astype("bool")
    missing_mask = series.isna() & ~assigned
    special_row, special_woe = _aggregate_fake_row(
        "Special", special_mask, y, total_good, total_bad, len(series)
    )
    missing_row, missing_woe = _aggregate_fake_row(
        "Missing", missing_mask, y, total_good, total_bad, len(series)
    )
    rows.extend([special_row, missing_row, _totals_row(rows, total_good, total_bad, len(series))])
    woe_map.extend([("Special", special_woe), ("Missing", missing_woe)])
    table = pd.DataFrame(rows)
    table.index = [*list(range(len(rows) - 1)), "Totals"]
    return table, woe_map


def _numeric_bins(name: str) -> list[tuple[object, Any]]:
    """Define bins numéricos manuales estables."""
    if name == "risk":
        return [
            ("(-inf, 0.50)", lambda value: float(value) < 0.5),
            ("[0.50, 1.50)", lambda value: 0.5 <= float(value) < 1.5),
            ("[1.50, inf)", lambda value: float(value) >= 1.5),
        ]
    return [
        ("(-inf, 1.50)", lambda value: float(value) < 1.5),
        ("[1.50, inf)", lambda value: float(value) >= 1.5),
    ]


def _categorical_bins(series: pd.Series) -> list[tuple[object, Any]]:
    """Define grupos categóricos manuales."""
    values = set(series.dropna().astype(str))
    if values <= {"A", "B"}:
        return [
            ("[A]", lambda value: str(value) == "A"),
            ("[B]", lambda value: str(value) == "B"),
        ]
    return [
        ("[A]", lambda value: str(value) == "A"),
        ("[B]", lambda value: str(value) == "B"),
        ("[Z]", lambda value: str(value) == "Z"),
    ]


def _aggregate_fake_row(
    label: object,
    mask: pd.Series,
    y: pd.Series,
    total_good: int,
    total_bad: int,
    total_count: int,
) -> tuple[dict[str, object], float]:
    """Calcula conteos, WoE e IV de un bin manual."""
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
    """Construye la fila ``Totals`` compatible con OptBinning."""
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
    """Cuenta bins de modelo no vacíos, excluyendo special/missing/totals."""
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
    """Transforma un valor crudo a WoE según el mapa manual."""
    pd = _pd()
    if value in special_values:
        return _metric_or_empirical(metric_special, woe_map, "Special")
    if pd.isna(value):
        return _metric_or_empirical(metric_missing, woe_map, "Missing")
    numeric_value = float(value) if isinstance(value, int | float) else None
    for label, woe in woe_map:
        if label == "(-inf, 0.50)" and numeric_value is not None and numeric_value < 0.5:
            return woe
        if label == "[0.50, 1.50)" and numeric_value is not None and 0.5 <= numeric_value < 1.5:
            return woe
        if label == "(-inf, 1.50)" and numeric_value is not None and numeric_value < 1.5:
            return woe
        if label == "[1.50, inf)" and numeric_value is not None and numeric_value >= 1.5:
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
    """Resuelve métrica especial/missing fija o empírica."""
    if metric == "empirical":
        for candidate_label, woe in woe_map:
            if candidate_label == label:
                return woe
        return 0.0
    return float(metric)


def _pd() -> Any:
    """Importa pandas bajo demanda dentro de fixtures que lo necesitan."""
    return importlib.import_module("pandas")
