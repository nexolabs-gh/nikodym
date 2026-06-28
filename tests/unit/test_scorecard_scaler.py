"""Tests de ``PointsScaler`` y ``Scorecard``: escala, puntos, sklearn e import liviano."""

from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import textwrap
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sklearn.base import clone

import nikodym.scorecard.scaler as scaler_module
import nikodym.scorecard.transformer as transformer_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, MissingDependencyError, NotFittedError
from nikodym.scorecard.config import PointOverrideConfig, ScorecardConfig
from nikodym.scorecard.exceptions import ScorecardFitError, ScorecardTransformError
from nikodym.scorecard.scaler import PointsScaler
from nikodym.scorecard.transformer import Scorecard

FACTOR_GOLDEN = 28.85390081777927
OFFSET_GOLDEN = 487.1228762045055
SALDO_BAJO_POINTS = 233.1740338078522
SALDO_ALTO_POINTS = 256.2571544620756
MORA_BAJA_POINTS = 242.40728206954157
MORA_ALTA_POINTS = 263.18209065834264
SCORE_C1_EXACT = 475.58131587739376
SCORE_C2_EXACT = 519.4392451204183
SCORE_UNSEEN_EXACT = 494.5787241758196
SALDO_UNSEEN_POINTS = 252.17144210627808
HIGHER_IS_HIGHER_RISK_SALDO = 253.94884239665328


def test_golden_escala_puntos_afinidad_y_no_mutacion() -> None:
    coefficients = _coefficients()
    tables = _tables(include_totals=True)
    woe_frame = _woe_frame()
    original_coefficients = coefficients.copy(deep=True)
    original_tables = {feature: table.copy(deep=True) for feature, table in tables.items()}
    original_woe = woe_frame.copy(deep=True)

    scaler = _fit_scaler(
        PointsScaler(rounding_method="none"),
        coefficients=coefficients,
        tables=tables,
    )
    transformed = scaler.transform(woe_frame)

    assert scaler.factor_ == pytest.approx(FACTOR_GOLDEN)
    assert scaler.offset_ == pytest.approx(OFFSET_GOLDEN)
    assert scaler.intercept_ == pytest.approx(-0.4)
    assert scaler.intercept_share_ == pytest.approx(-0.2)
    assert "scikit-learn" not in scaler.dependency_versions_
    assert scaler.points_columns_ == ("saldo__points", "mora__points")

    scorecard = scaler.scorecard_.set_index(["feature", "bin_label"])
    assert scorecard.loc[("saldo", "bajo"), "raw_points"] == pytest.approx(SALDO_BAJO_POINTS)
    assert scorecard.loc[("saldo", "bajo"), "points"] == pytest.approx(SALDO_BAJO_POINTS)
    assert scorecard.loc[("saldo", "alto"), "raw_points"] == pytest.approx(SALDO_ALTO_POINTS)
    assert scorecard.loc[("mora", "baja"), "raw_points"] == pytest.approx(MORA_BAJA_POINTS)
    assert scorecard.loc[("mora", "alta"), "raw_points"] == pytest.approx(MORA_ALTA_POINTS)
    assert scorecard["rounding_delta"].tolist() == pytest.approx([0.0, 0.0, 0.0, 0.0])
    assert scorecard["source"].tolist() == ["binning_table"] * 4
    assert "Totals" not in set(scorecard.index.get_level_values("bin_label"))

    assert transformed["saldo__points"].tolist() == pytest.approx(
        [SALDO_BAJO_POINTS, SALDO_ALTO_POINTS]
    )
    assert transformed["mora__points"].tolist() == pytest.approx(
        [MORA_BAJA_POINTS, MORA_ALTA_POINTS]
    )
    assert transformed["score"].tolist() == pytest.approx([SCORE_C1_EXACT, SCORE_C2_EXACT])
    for observed, exact in zip(transformed["score"], [SCORE_C1_EXACT, SCORE_C2_EXACT], strict=True):
        assert observed == pytest.approx(exact)

    assert_frame_equal(coefficients, original_coefficients)
    assert_frame_equal(woe_frame, original_woe)
    for feature, table in tables.items():
        assert_frame_equal(table, original_tables[feature])


def test_redondeo_nearest_integer_respeta_cota_y_audita() -> None:
    audit = InMemoryAuditSink()
    scaler = _fit_scaler(PointsScaler(rounding_method="nearest_integer"), audit=audit)
    transformed = scaler.transform(_woe_frame())

    assert transformed["saldo__points"].tolist() == [233, 256]
    assert transformed["mora__points"].tolist() == [242, 263]
    assert transformed["score"].tolist() == [475, 519]
    for observed, exact in zip(transformed["score"], [SCORE_C1_EXACT, SCORE_C2_EXACT], strict=True):
        assert abs(float(observed) - exact) <= 2 * 0.5
    assert any(event.payload["regla"] == "scorecard_rounding" for event in audit.events)


def test_bin_no_visto_calcula_formula_y_audita() -> None:
    audit = InMemoryAuditSink()
    scaler = _fit_scaler(PointsScaler(rounding_method="none"), audit=audit)
    frame = pd.DataFrame(
        {"saldo__woe": [0.123], "mora__woe": [-0.2]},
        index=pd.Index(["c3"], name="loan_id"),
    )

    transformed = scaler.transform(frame)

    assert transformed.loc["c3", "saldo__points"] == pytest.approx(SALDO_UNSEEN_POINTS)
    assert transformed.loc["c3", "score"] == pytest.approx(SCORE_UNSEEN_EXACT)
    assert scaler.unseen_bins_ == {"saldo": 1}
    assert [event.payload["regla"] for event in audit.events][-1] == "bin_no_visto"


def test_woe_duplicado_usa_primera_clave_feature_woe_y_override_auditado() -> None:
    audit = InMemoryAuditSink()
    override = PointOverrideConfig(
        feature="saldo",
        bin_label="segundo",
        points=999,
        reason="homologacion manual",
    )
    scaler = PointsScaler(
        rounding_method="nearest_integer",
        point_overrides=(override,),
    )
    coefficients = pd.DataFrame(
        [
            {"feature": "intercept", "woe_column": "const", "beta": 0.0},
            {"feature": "saldo", "woe_column": "saldo__woe", "beta": -1.0},
        ]
    )
    tables = {
        "saldo": pd.DataFrame(
            {
                "Bin": ["primero", "segundo"],
                "WoE": [0.1, 0.1],
            }
        )
    }
    scaler.fit(
        coefficients=coefficients,
        final_features=("saldo",),
        final_woe_columns=("saldo__woe",),
        binning_tables=tables,
        woe_column_map={"saldo": "saldo__woe"},
        audit=audit,
    )
    transformed = scaler.transform(pd.DataFrame({"saldo__woe": [0.1]}))
    first_points = int(scaler.scorecard_.loc[0, "points"])

    assert first_points != 999
    assert transformed.loc[0, "saldo__points"] == first_points
    assert transformed.loc[0, "score"] == first_points
    assert scaler._duplicate_woe_keys_[0]["bin_label"] == "segundo"
    assert [event.payload["regla"] for event in audit.events] == [
        "point_override",
        "woe_duplicado",
        "scorecard_rounding",
    ]


def test_clipping_opt_in_y_fuera_de_rango_sin_recorte() -> None:
    clipped_audit = InMemoryAuditSink()
    clipped = _fit_scaler(
        PointsScaler(rounding_method="none", min_score=490.0, max_score=500.0, clip=True),
        audit=clipped_audit,
    ).transform(_woe_frame())
    assert clipped["score"].tolist() == pytest.approx([490.0, 500.0])
    assert [event.payload["regla"] for event in clipped_audit.events] == ["score_clip"]

    flagged_audit = InMemoryAuditSink()
    flagged = _fit_scaler(
        PointsScaler(rounding_method="none", min_score=490.0, max_score=500.0, clip=False),
        audit=flagged_audit,
    ).transform(_woe_frame())
    assert flagged["score"].tolist() == pytest.approx([SCORE_C1_EXACT, SCORE_C2_EXACT])
    assert [event.payload["regla"] for event in flagged_audit.events] == ["score_fuera_de_rango"]

    no_event_audit = InMemoryAuditSink()
    no_event = _fit_scaler(
        PointsScaler(rounding_method="none", min_score=400.0, max_score=600.0, clip=True),
        audit=no_event_audit,
    ).transform(_woe_frame())
    assert no_event["score"].tolist() == pytest.approx([SCORE_C1_EXACT, SCORE_C2_EXACT])
    assert no_event_audit.events == []


def test_scorecard_clone_from_config_fit_from_artifacts_y_dependency_versions() -> None:
    cfg = ScorecardConfig(rounding_method="none", output_suffix="__pts", score_column="score_total")
    scorecard = Scorecard.from_config(cfg)
    cloned = clone(scorecard)
    cloned.set_params(output_suffix="__points", score_column="score")

    model_result = SimpleNamespace(
        coefficients=_coefficients(),
        final_features=("saldo", "mora"),
        final_woe_columns=("saldo__woe", "mora__woe"),
    )
    binning_result = SimpleNamespace(tables=_tables(), woe_column_map=_woe_column_map())
    fitted = cloned.fit_from_artifacts(model_result=model_result, binning_result=binning_result)

    assert fitted is cloned
    assert fitted.transform(_woe_frame())["score"].tolist() == pytest.approx(
        [SCORE_C1_EXACT, SCORE_C2_EXACT]
    )
    assert "scikit-learn" in fitted.dependency_versions_

    explicit = Scorecard(rounding_method="none").fit_from_artifacts(
        model_result=object(),
        binning_result=object(),
        coefficients=_coefficients(),
        final_features=("saldo", "mora"),
        final_woe_columns=("saldo__woe", "mora__woe"),
        binning_tables=_tables(),
        woe_column_map=_woe_column_map(),
    )
    assert explicit.final_features_ == ("saldo", "mora")


def test_points_scaler_from_config_dict_y_sin_intercepto() -> None:
    scaler = PointsScaler.from_config({"rounding_method": "none"})
    coefficients = _coefficients().loc[lambda df: df["feature"] != "intercept"].copy(deep=True)

    fitted = _fit_scaler(scaler, coefficients=coefficients)

    assert fitted.rounding_method == "none"
    assert fitted.intercept_ == 0.0
    assert fitted.intercept_share_ == 0.0


def test_fit_from_artifacts_valida_requeridos() -> None:
    cases: list[tuple[dict[str, Any], str]] = [
        (
            {
                "final_features": ("saldo",),
                "final_woe_columns": ("saldo__woe",),
                "binning_tables": _tables(),
                "woe_column_map": _woe_column_map(),
            },
            "coefficients",
        ),
        (
            {
                "coefficients": _coefficients(),
                "final_woe_columns": ("saldo__woe",),
                "binning_tables": _tables(),
                "woe_column_map": _woe_column_map(),
            },
            "final_features",
        ),
        (
            {
                "coefficients": _coefficients(),
                "final_features": ("saldo",),
                "binning_tables": _tables(),
                "woe_column_map": _woe_column_map(),
            },
            "final_woe_columns",
        ),
        (
            {
                "coefficients": _coefficients(),
                "final_features": ("saldo",),
                "final_woe_columns": ("saldo__woe",),
                "woe_column_map": _woe_column_map(),
            },
            "binning_tables",
        ),
        (
            {
                "coefficients": _coefficients(),
                "final_features": ("saldo",),
                "final_woe_columns": ("saldo__woe",),
                "binning_tables": _tables(),
            },
            "woe_column_map",
        ),
    ]
    for kwargs, match in cases:
        with pytest.raises(ScorecardFitError, match=match):
            Scorecard().fit_from_artifacts(**kwargs)


def test_fit_from_artifacts_valida_atributos_estructurales() -> None:
    with pytest.raises(ScorecardFitError, match="atributo requerido: coefficients"):
        Scorecard().fit_from_artifacts(model_result=object())


def test_fit_valida_mapping_coeficientes_y_tablas() -> None:
    scaler = PointsScaler()
    with pytest.raises(ScorecardFitError, match="mismo largo"):
        _fit_scaler(scaler, features=("saldo",), woe_columns=("saldo__woe", "mora__woe"))
    with pytest.raises(ScorecardFitError, match="al menos una"):
        _fit_scaler(scaler, features=(), woe_columns=(), woe_column_map={})
    with pytest.raises(ScorecardFitError, match="final_features contiene duplicados"):
        _fit_scaler(scaler, features=("saldo", "saldo"))
    with pytest.raises(ScorecardFitError, match="final_woe_columns contiene duplicados"):
        _fit_scaler(scaler, woe_columns=("saldo__woe", "saldo__woe"))
    with pytest.raises(ScorecardFitError, match="no contiene una feature"):
        _fit_scaler(scaler, woe_column_map={"saldo": "saldo__woe"})
    with pytest.raises(ScorecardFitError, match="no coincide"):
        _fit_scaler(scaler, woe_column_map={"saldo": "saldo__woe", "mora": "otra"})
    with pytest.raises(ScorecardFitError, match=r"pandas\.DataFrame"):
        _fit_scaler(scaler, coefficients=[1, 2, 3])
    with pytest.raises(ScorecardFitError, match="DataFrame vacío"):
        _fit_scaler(scaler, coefficients=pd.DataFrame())
    duplicated = pd.DataFrame([[1, 2, 3]], columns=["feature", "feature", "beta"])
    with pytest.raises(ScorecardFitError, match="duplicadas"):
        _fit_scaler(scaler, coefficients=duplicated)
    with pytest.raises(ScorecardFitError, match="columnas requeridas"):
        _fit_scaler(scaler, coefficients=pd.DataFrame({"feature": ["saldo"], "beta": [-1.0]}))
    with pytest.raises(ScorecardFitError, match="beta no es numérico"):
        _fit_scaler(scaler, coefficients=_coefficients(beta_saldo="x"))
    with pytest.raises(ScorecardFitError, match="beta no es finito"):
        _fit_scaler(scaler, coefficients=_coefficients(beta_saldo=math.inf))
    with pytest.raises(ScorecardFitError, match="más de una fila de intercepto"):
        _fit_scaler(
            scaler,
            coefficients=pd.concat(
                [
                    _coefficients(),
                    pd.DataFrame([{"feature": "intercept", "woe_column": "x", "beta": 0.0}]),
                ],
                ignore_index=True,
            ),
        )
    with pytest.raises(ScorecardFitError, match="sin coeficiente"):
        _fit_scaler(
            scaler,
            coefficients=_coefficients().loc[lambda df: df["feature"] != "mora"].copy(deep=True),
        )
    with pytest.raises(ScorecardFitError, match="ambiguo"):
        _fit_scaler(
            scaler,
            coefficients=pd.concat(
                [
                    _coefficients(),
                    pd.DataFrame([{"feature": "saldo", "woe_column": "saldo__woe", "beta": -0.7}]),
                ],
                ignore_index=True,
            ),
        )
    mismatch = _coefficients()
    mismatch.loc[mismatch["feature"].eq("saldo"), "woe_column"] = "otra"
    with pytest.raises(ScorecardFitError, match="mapping final"):
        _fit_scaler(scaler, coefficients=mismatch)

    with pytest.raises(ScorecardFitError, match="sin tabla"):
        _fit_scaler(scaler, tables={"saldo": _tables()["saldo"]})
    with pytest.raises(ScorecardFitError, match=r"pandas\.DataFrame"):
        _fit_scaler(scaler, tables={"saldo": _tables()["saldo"], "mora": [1, 2, 3]})
    with pytest.raises(ScorecardFitError, match="DataFrame vacío"):
        _fit_scaler(scaler, tables={"saldo": _tables()["saldo"], "mora": pd.DataFrame()})
    duplicated_table = pd.DataFrame([[1, 2]], columns=["Bin", "Bin"])
    with pytest.raises(ScorecardFitError, match="duplicadas"):
        _fit_scaler(scaler, tables={"saldo": duplicated_table, "mora": _tables()["mora"]})
    with pytest.raises(ScorecardFitError, match="columnas requeridas"):
        _fit_scaler(
            scaler,
            tables={"saldo": pd.DataFrame({"Bin": ["x"]}), "mora": _tables()["mora"]},
        )
    with pytest.raises(ScorecardFitError, match="bins publicables"):
        _fit_scaler(
            scaler,
            tables={
                "saldo": pd.DataFrame({"Bin": ["Totals"], "WoE": [0.0]}, index=["Totals"]),
                "mora": _tables()["mora"],
            },
        )
    with pytest.raises(ScorecardFitError, match="WoE no finito"):
        _fit_scaler(
            scaler,
            tables={
                "saldo": pd.DataFrame({"Bin": ["x"], "WoE": [math.nan]}),
                "mora": _tables()["mora"],
            },
        )


def test_transform_valida_columnas_y_finitud() -> None:
    scaler = _fit_scaler(PointsScaler(rounding_method="none"))
    with pytest.raises(NotFittedError, match="no está fiteado"):
        PointsScaler().transform(_woe_frame())
    with pytest.raises(ScorecardTransformError, match=r"pandas\.DataFrame"):
        scaler.transform([1, 2, 3])
    with pytest.raises(ScorecardTransformError, match="DataFrame vacío"):
        scaler.transform(pd.DataFrame())
    duplicated = pd.DataFrame([[0.1, 0.2]], columns=["saldo__woe", "saldo__woe"])
    with pytest.raises(ScorecardTransformError, match="duplicadas"):
        scaler.transform(duplicated)
    with pytest.raises(ScorecardTransformError, match="Faltan columnas"):
        scaler.transform(pd.DataFrame({"saldo__woe": [0.1]}))
    with pytest.raises(ScorecardTransformError, match="colisiones"):
        scaler.transform(_woe_frame().assign(score=0.0))
    with pytest.raises(ScorecardTransformError, match="colisiones"):
        scaler.transform(_woe_frame().assign(saldo__points=0.0))
    with pytest.raises(ScorecardTransformError, match="WoE no finita"):
        scaler.transform(pd.DataFrame({"saldo__woe": [math.inf], "mora__woe": [0.1]}))


def test_helpers_privados_de_redondeo_direccion_y_dependencias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert scaler_module._published_points(1.2, "floor_integer") == 1
    assert scaler_module._published_points(1.2, "ceil_integer") == 2
    assert scaler_module._raw_points(
        direction="higher_is_higher_risk",
        factor=FACTOR_GOLDEN,
        offset_share=OFFSET_GOLDEN / 2,
        beta=-0.8,
        woe=-0.7,
        intercept_share=-0.2,
    ) == pytest.approx(HIGHER_IS_HIGHER_RISK_SALDO)
    with pytest.raises(ScorecardFitError, match="raw_points"):
        scaler_module._raw_points(
            direction="higher_is_lower_risk",
            factor=math.inf,
            offset_share=1.0,
            beta=-0.8,
            woe=0.1,
            intercept_share=0.0,
        )
    with pytest.raises(ScorecardFitError, match="no es numérico"):
        scaler_module._finite_float("x", label="valor", error_cls=ScorecardFitError)
    with pytest.raises(ScorecardFitError, match="no es finito"):
        scaler_module._finite_float(math.nan, label="valor", error_cls=ScorecardFitError)
    assert scaler_module._normalize_point(1) == 1
    assert scaler_module._normalize_point(False) == 0.0
    assert scaler_module._normalize_float(-0.0) == 0.0
    assert scaler_module._normalize_float(1.5) == 1.5

    invalid = PointsScaler(pdo=0.0)
    with pytest.raises(ConfigError, match="Hiperparámetros inválidos"):
        invalid.fit(
            coefficients=_coefficients(),
            final_features=("saldo", "mora"),
            final_woe_columns=("saldo__woe", "mora__woe"),
            binning_tables=_tables(),
            woe_column_map=_woe_column_map(),
        )

    real_import = scaler_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(scaler_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        scaler_module._import_pandas()

    def block_numpy(name: str) -> Any:
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name)

    monkeypatch.setattr(scaler_module.importlib, "import_module", block_numpy)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        scaler_module._import_numpy()

    def block_dependency_versions(name: str) -> Any:
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return real_import(name)

    monkeypatch.setattr(scaler_module.importlib, "import_module", block_dependency_versions)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        scaler_module._dependency_versions(PointsScaler())


def test_import_scorecard_liviano_y_exports_perezosos() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.scorecard as scorecard

        blocked = [
            name for name in ("pandas", "statsmodels", "sklearn", "scipy", "optbinning")
            if name in sys.modules
        ]
        assert blocked == [], blocked
        assert scorecard.PointsScaler.__name__ == "PointsScaler"
        blocked = [
            name for name in ("pandas", "statsmodels", "sklearn", "scipy", "optbinning")
            if name in sys.modules
        ]
        assert blocked == [], blocked
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_reexport_scorecard_sin_sklearn_falla_con_missing_dependency() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.scorecard
        from nikodym.core.exceptions import MissingDependencyError


        class BlockSklearn:
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "sklearn" or fullname.startswith("sklearn."):
                    raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")
                return None


        sys.meta_path.insert(0, BlockSklearn())
        try:
            nikodym.scorecard.Scorecard
        except MissingDependencyError as exc:
            assert "instale nikodym[scoring]" in str(exc)
        else:
            raise AssertionError("Scorecard no tradujo la ausencia de sklearn")
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_import_transformer_sin_sklearn_cubre_rama_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockSklearn:
        def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
            del path, target
            if fullname == "sklearn" or fullname.startswith("sklearn."):
                raise ModuleNotFoundError("No module named 'sklearn'", name="sklearn")

    for name in [name for name in sys.modules if name == "sklearn" or name.startswith("sklearn.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [BlockSklearn(), *sys.meta_path])

    module_path = transformer_module.__file__
    assert module_path is not None
    spec = importlib.util.spec_from_file_location(
        "nikodym.scorecard._missing_sklearn_transformer_test",
        module_path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        loader.exec_module(module)


def _fit_scaler(
    scaler: PointsScaler,
    *,
    coefficients: Any | None = None,
    features: tuple[str, ...] = ("saldo", "mora"),
    woe_columns: tuple[str, ...] = ("saldo__woe", "mora__woe"),
    tables: Mapping[str, Any] | None = None,
    woe_column_map: Mapping[str, str] | None = None,
    audit: InMemoryAuditSink | None = None,
) -> PointsScaler:
    return scaler.fit(
        coefficients=_coefficients() if coefficients is None else coefficients,
        final_features=features,
        final_woe_columns=woe_columns,
        binning_tables=_tables() if tables is None else tables,
        woe_column_map=_woe_column_map() if woe_column_map is None else woe_column_map,
        audit=audit,
    )


def _coefficients(
    *,
    alpha: object = -0.4,
    beta_saldo: object = -0.8,
    beta_mora: object = -1.2,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"feature": "intercept", "woe_column": "const", "beta": alpha},
            {"feature": "saldo", "woe_column": "saldo__woe", "beta": beta_saldo},
            {"feature": "mora", "woe_column": "mora__woe", "beta": beta_mora},
        ]
    )


def _tables(*, include_totals: bool = False) -> dict[str, pd.DataFrame]:
    saldo = pd.DataFrame({"Bin": ["bajo", "alto"], "WoE": [-0.7, 0.3]})
    mora = pd.DataFrame({"Bin": ["baja", "alta"], "WoE": [-0.2, 0.4]})
    if include_totals:
        saldo = pd.concat(
            [saldo, pd.DataFrame({"Bin": ["Totals"], "WoE": [0.0]}, index=["Totals"])],
        )
        mora = pd.concat(
            [mora, pd.DataFrame({"Bin": ["Totals"], "WoE": [0.0]}, index=["Totals"])],
        )
    return {"saldo": saldo, "mora": mora}


def _woe_column_map() -> dict[str, str]:
    return {"saldo": "saldo__woe", "mora": "mora__woe"}


def _woe_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "partition": ["desarrollo", "holdout"],
            "saldo__woe": [-0.7, 0.3],
            "mora__woe": [-0.2, 0.4],
        },
        index=pd.Index(["c1", "c2"], name="loan_id"),
    )
