"""Tests de ``PDCalibrator``: goldens, métodos opt-in, guards e import liviano."""

from __future__ import annotations

import math
import subprocess
import sys
import textwrap
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sklearn.base import clone

import nikodym.calibration.calibrator as calibrator_module
from nikodym.calibration.calibrator import PDCalibrator
from nikodym.calibration.config import CalibrationConfig
from nikodym.calibration.exceptions import CalibrationFitError, CalibrationTransformError
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, MissingDependencyError, NotFittedError


def test_intercept_offset_golden_constante_no_muta_y_publica_resultado() -> None:
    eta0 = -0.75
    target_pd = 0.07
    frame = _raw_frame([eta0, eta0, eta0, eta0], target=[0, 1, 0, 1])
    original = frame.copy(deep=True)

    calibrator = PDCalibrator(target_pd=target_pd, min_fit_rows=1).fit(frame)
    transformed = calibrator.transform(frame)

    expected_delta = _logit(target_pd) - eta0
    assert calibrator.offset_ == pytest.approx(expected_delta)
    assert calibrator.slope_ is None
    assert calibrator.intercept_ is None
    assert transformed["pd_calibrated"].tolist() == pytest.approx([target_pd] * 4)
    assert transformed["linear_predictor_calibrated"].tolist() == pytest.approx(
        [_logit(target_pd)] * 4
    )
    assert tuple(transformed.columns) == (
        "partition",
        "target",
        "linear_predictor",
        "pd_raw",
        "linear_predictor_calibrated",
        "pd_calibrated",
        "calibration_method",
        "anchor_kind",
    )
    assert [str(transformed[column].dtype) for column in _FLOAT_COLUMNS] == [
        "float64",
        "float64",
        "float64",
        "float64",
    ]
    assert calibrator.parameters_.offset == pytest.approx(expected_delta)
    assert calibrator.card_.ranking_preserved is True
    assert "scipy" in calibrator.dependency_versions_
    assert "scikit-learn" not in calibrator.dependency_versions_
    assert_frame_equal(frame, original)
    assert_frame_equal(calibrator.result_.calibrated_pd_frame, transformed)


def test_intercept_offset_golden_media_central_ranking_y_fit_transform() -> None:
    eta = [-2.2, -1.3, -0.4, 0.2, 1.1, 1.8, -0.8, 0.7]
    partitions = ["desarrollo"] * 6 + ["holdout", "oot"]
    frame = _raw_frame(eta, partition=partitions, target=[0, 0, 1, 0, 1, 1, 0, 1])
    target_pd = 0.23
    expected_delta = _bisect_delta(eta[:6], target_pd)

    calibrator = PDCalibrator(target_pd=target_pd, min_fit_rows=1)
    transformed = calibrator.fit_transform(frame)

    dev_mean = transformed.loc[transformed["partition"].eq("desarrollo"), "pd_calibrated"].mean()
    assert calibrator.offset_ == pytest.approx(expected_delta, abs=1e-12)
    assert dev_mean == pytest.approx(target_pd, abs=1e-12)
    assert transformed.index.tolist() == frame.index.tolist()
    assert (
        transformed["pd_raw"].rank(method="average").tolist()
        == transformed["pd_calibrated"].rank(method="average").tolist()
    )
    assert calibrator.ranking_preserved_ is True
    assert calibrator.ties_created_ == 0


def test_fit_filtra_fuera_de_modelo_y_anchor_development_observed_auditado() -> None:
    audit = InMemoryAuditSink()
    frame = _raw_frame(
        [-1.5, -0.5, 0.3, 1.2, 2.0],
        target=[0, 0, 1, 1, 1],
        partition=["desarrollo", "desarrollo", "desarrollo", "desarrollo", "fuera_modelo"],
    )

    calibrator = PDCalibrator(
        anchor_source="development_observed",
        min_fit_rows=1,
    ).fit(frame, audit=audit)
    transformed = calibrator.transform(frame)

    assert calibrator.target_pd_ == pytest.approx(0.5)
    assert transformed.index.tolist() == ["c0", "c1", "c2", "c3"]
    assert [event.payload["regla"] for event in audit.events].count(
        "calibration_fuera_de_modelo"
    ) == 2
    assert "calibration_anchor" in [event.payload["regla"] for event in audit.events]


def test_contrato_roto_pd_raw_vs_sigmoid_falla_aunque_target_tolerance_sea_alto() -> None:
    frame = _raw_frame([-1.0, 0.0, 1.0])
    frame.loc["c1", "pd_raw"] = 0.9

    with pytest.raises(CalibrationFitError, match="sigmoid"):
        PDCalibrator(min_fit_rows=1, target_tolerance=1e-1).fit(frame)


def test_validaciones_de_fit_y_transform_con_mensajes_propios() -> None:
    with pytest.raises(CalibrationFitError, match=r"pandas\.DataFrame"):
        PDCalibrator(min_fit_rows=1).fit("no es frame")  # type: ignore[arg-type]

    empty = pd.DataFrame(columns=["partition", "target", "linear_predictor", "pd_raw"])
    with pytest.raises(CalibrationFitError, match="DataFrame vacío"):
        PDCalibrator(min_fit_rows=1).fit(empty)

    with pytest.raises(NotFittedError, match="no está fiteado"):
        PDCalibrator().transform(_raw_frame([0.0]))

    with pytest.raises(CalibrationFitError, match="columnas requeridas"):
        PDCalibrator(min_fit_rows=1).fit(_raw_frame([0.0]).drop(columns=["pd_raw"]))

    duplicated = pd.concat([_raw_frame([0.0]), _raw_frame([0.0])["pd_raw"]], axis=1)
    with pytest.raises(CalibrationFitError, match="duplicadas"):
        PDCalibrator(min_fit_rows=1).fit(duplicated)

    duplicate_index = _raw_frame([0.0, 0.1])
    duplicate_index.index = ["c0", "c0"]
    with pytest.raises(CalibrationFitError, match="índice único"):
        PDCalibrator(min_fit_rows=1).fit(duplicate_index)

    with pytest.raises(CalibrationFitError, match="min_fit_rows"):
        PDCalibrator(min_fit_rows=3).fit(_raw_frame([0.0, 0.1]))

    invalid_pd = _raw_frame([0.0, 0.1])
    invalid_pd.loc["c0", "pd_raw"] = 1.0
    with pytest.raises(CalibrationFitError, match=r"\(0, 1\)"):
        PDCalibrator(min_fit_rows=1).fit(invalid_pd)

    non_numeric = _raw_frame([0.0, 0.1]).astype({"linear_predictor": "object"})
    non_numeric.loc["c0", "linear_predictor"] = "no numerico"
    with pytest.raises(CalibrationFitError, match="float64-compatible"):
        PDCalibrator(min_fit_rows=1).fit(non_numeric)

    collision = _raw_frame([0.0, 0.1])
    collision["pd_calibrated"] = 0.1
    with pytest.raises(CalibrationFitError, match="colisiones"):
        PDCalibrator(min_fit_rows=1).fit(collision)


def test_transform_valida_contrato_y_devuelve_vacio_si_no_hay_modelables() -> None:
    calibrator = PDCalibrator(min_fit_rows=1).fit(_raw_frame([-0.5, 0.5], target=[0, 1]))
    frame = _raw_frame([-0.2], partition=["fuera_modelo"])

    transformed = calibrator.transform(frame)

    assert transformed.empty
    assert tuple(transformed.columns) == (
        "partition",
        "target",
        "linear_predictor",
        "pd_raw",
        "linear_predictor_calibrated",
        "pd_calibrated",
        "calibration_method",
        "anchor_kind",
    )

    broken = _raw_frame([0.0])
    broken.loc["c0", "linear_predictor"] = math.inf
    with pytest.raises(CalibrationTransformError, match="finitos"):
        calibrator.transform(broken)


def test_platt_scaling_slope_positivo_ok_y_post_offset_monotono() -> None:
    eta = [-2.0, -1.2, -0.8, -0.2, 0.1, 0.6, 1.1, 1.8]
    target = [0, 0, 1, 0, 1, 0, 1, 1]
    frame = _raw_frame(eta, target=target)

    calibrator = PDCalibrator(
        method="platt_scaling",
        anchor_source="development_observed",
        min_fit_rows=1,
        max_iter=500,
    ).fit(frame)
    transformed = calibrator.transform(frame)

    assert calibrator.slope_ is not None
    assert calibrator.slope_ > 0.0
    assert calibrator.offset_ is None
    assert calibrator.post_offset_ is not None
    assert transformed["pd_calibrated"].mean() == pytest.approx(0.5, abs=1e-12)
    assert "scikit-learn" in calibrator.dependency_versions_
    assert (
        transformed["pd_calibrated"].rank(method="average").tolist()
        == transformed["pd_raw"].rank(method="average").tolist()
    )
    assert transformed.loc[:, "pd_calibrated"].between(0.0, 1.0, inclusive="neither").all()


def test_platt_scaling_slope_no_positivo_falla_por_inversion_de_ranking() -> None:
    eta = [-2.0, -1.2, -0.8, -0.2, 0.1, 0.6, 1.1, 1.8]
    target = [1, 1, 0, 1, 0, 1, 0, 0]
    frame = _raw_frame(eta, target=target)

    with pytest.raises(CalibrationFitError, match="slope <= 0"):
        PDCalibrator(
            method="platt_scaling",
            anchor_source="development_observed",
            min_fit_rows=1,
            max_iter=500,
        ).fit(frame)


def test_isotonic_crea_empates_y_registra_knots() -> None:
    eta = [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
    target = [0, 1, 0, 1, 0, 1]
    frame = _raw_frame(eta, target=target)

    calibrator = PDCalibrator(
        method="isotonic",
        anchor_source="development_observed",
        min_fit_rows=1,
    ).fit(frame)
    transformed = calibrator.transform(frame)

    assert calibrator.ties_created_ > 0
    assert calibrator.ranking_preserved_ is False
    assert len(calibrator.isotonic_knots_) >= 2
    assert transformed["pd_calibrated"].nunique() < transformed["pd_raw"].nunique()
    assert "scikit-learn" in calibrator.dependency_versions_


def test_anchor_development_observed_y_supervisado_exigen_target_binario_ambas_clases() -> None:
    with pytest.raises(CalibrationFitError, match="ambas clases"):
        PDCalibrator(anchor_source="development_observed", min_fit_rows=1).fit(
            _raw_frame([0.0, 0.1], target=[0, 0])
        )

    with pytest.raises(CalibrationFitError, match="binario"):
        PDCalibrator(method="isotonic", min_fit_rows=1).fit(
            _raw_frame([0.0, 0.1, 0.2], target=[0, 0.5, 1])
        )


def test_solver_no_converge_publica_contexto() -> None:
    with pytest.raises(CalibrationFitError, match="target_pd"):
        PDCalibrator(target_pd=0.87, min_fit_rows=1, max_iter=1).fit(
            _raw_frame([-2.0, -1.0, 0.0, 1.0, 2.0])
        )


def test_checks_finales_de_media_fallan_con_contexto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_transform = calibrator_module._transform_with_state

    def wrong_mean(*args: Any, **kwargs: Any) -> pd.DataFrame:
        transformed = original_transform(*args, **kwargs)
        transformed["pd_calibrated"] = 0.99
        return transformed

    monkeypatch.setattr(calibrator_module, "_transform_with_state", wrong_mean)
    with pytest.raises(CalibrationFitError, match="media_alcanzada"):
        PDCalibrator(target_pd=0.2, min_fit_rows=1).fit(_raw_frame([-1.0, 0.0, 1.0]))


def test_verificacion_local_de_offset_falla_si_solver_devuelve_media_invalida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bad_solve(*args: Any, **kwargs: Any) -> tuple[float, float, tuple[float, float], int]:
        del args, kwargs
        return 0.0, 0.99, (-1.0, 1.0), 1

    monkeypatch.setattr(calibrator_module, "_solve_offset", bad_solve)
    with pytest.raises(CalibrationFitError, match="target_pd"):
        PDCalibrator(target_pd=0.2, min_fit_rows=1).fit(_raw_frame([-1.0, 0.0, 1.0]))


def test_platt_e_isotonic_traducen_fallo_del_estimador(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenLogistic:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        def fit(self, X: Any, y: Any) -> None:  # noqa: N803
            del X, y
            raise RuntimeError("boom logistic")

    class BrokenIsotonic:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        def fit(self, X: Any, y: Any) -> None:  # noqa: N803
            del X, y
            raise RuntimeError("boom isotonic")

    monkeypatch.setattr(calibrator_module, "_import_logistic_regression", lambda: BrokenLogistic)
    with pytest.raises(CalibrationFitError, match="platt_scaling"):
        PDCalibrator(method="platt_scaling", min_fit_rows=1).fit(
            _raw_frame([-1.0, 0.0, 1.0, 2.0], target=[0, 1, 0, 1])
        )

    monkeypatch.setattr(calibrator_module, "_import_isotonic_regression", lambda: BrokenIsotonic)
    with pytest.raises(CalibrationFitError, match="isotonic"):
        PDCalibrator(method="isotonic", min_fit_rows=1).fit(
            _raw_frame([-1.0, 0.0, 1.0, 2.0], target=[0, 1, 0, 1])
        )


def test_helpers_defensivos_numericos() -> None:
    np = calibrator_module._import_numpy()
    expit = calibrator_module._import_scipy_expit()
    linear = np.asarray([0.0], dtype="float64")

    def raising_brentq(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise ValueError("sin bracket")

    with pytest.raises(CalibrationFitError, match="target_pd"):
        calibrator_module._solve_offset(
            linear,
            target_pd=0.4,
            tolerance=1e-12,
            max_iter=3,
            expit=expit,
            brentq=raising_brentq,
            np=np,
        )
    with pytest.raises(CalibrationFitError, match="bracket finito"):
        calibrator_module._offset_bracket(
            np.asarray([math.inf], dtype="float64"),
            target_pd=0.5,
            np=np,
        )
    with pytest.raises(CalibrationFitError, match="offset"):
        calibrator_module._mean_sigmoid(linear, delta=math.inf, expit=expit, np=np)
    with pytest.raises(CalibrationFitError, match="métricas"):
        calibrator_module._as_float_array([0.0, math.inf], np=np)
    with pytest.raises(CalibrationTransformError, match="PD no finita"):
        calibrator_module._clip_probability_array([math.nan], np=np)
    with pytest.raises(CalibrationFitError, match="logit"):
        calibrator_module._logit_array(np.asarray([1.0], dtype="float64"), np=np)
    with pytest.raises(CalibrationFitError, match="slope"):
        calibrator_module._finite_scalar(math.inf, label="slope")


def test_estado_fiteado_invalido_falla_en_transformacion() -> None:
    np = calibrator_module._import_numpy()
    calibrator = PDCalibrator(method="isotonic", min_fit_rows=1).fit(
        _raw_frame([-1.0, 0.0, 1.0, 2.0], target=[0, 1, 0, 1])
    )
    calibrator._isotonic_model_ = None

    with pytest.raises(CalibrationTransformError, match="isotonic"):
        calibrator.transform(_raw_frame([-0.5, 0.5], target=[0, 1]))

    bad_state = calibrator_module.FitState(
        method="platt_scaling",
        target_pd=0.5,
        offset=None,
        slope=math.inf,
        intercept=0.0,
        post_offset=None,
        isotonic_model=None,
        isotonic_knots=(),
        ties_created=0,
        bracket=(0.0, 1.0),
        iterations=1,
    )
    with pytest.raises(CalibrationTransformError, match="lineal no finito"):
        calibrator_module._calibrated_linear(
            np.asarray([0.0], dtype="float64"), state=bad_state, np=np
        )


def test_clone_safe_from_config_set_params_y_runtime_config() -> None:
    cfg = CalibrationConfig(target_pd=0.08, min_fit_rows=1, method="intercept_offset")
    calibrator = PDCalibrator.from_config(cfg)
    from_dict = PDCalibrator.from_config(cfg.model_dump())  # type: ignore[arg-type]
    cloned = clone(calibrator)

    assert cloned.get_params()["target_pd"] == 0.08
    assert cloned.get_params()["min_fit_rows"] == 1
    assert from_dict.get_params()["method"] == "intercept_offset"
    assert cloned.set_params(target_pd=0.09).get_params()["target_pd"] == 0.09

    cloned.set_params(target_pd=1.0)
    with pytest.raises(ConfigError, match="PDCalibrator"):
        cloned.fit(_raw_frame([0.0, 0.1]))


def test_import_calibration_liviano_subprocess() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.calibration

        blocked = [m for m in ("pandas", "scipy", "sklearn") if m in sys.modules]
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


def test_import_calibrator_liviano_subprocess() -> None:
    code = textwrap.dedent(
        """
        import sys
        from nikodym.calibration.calibrator import PDCalibrator

        assert PDCalibrator.__name__ == "PDCalibrator"
        blocked = [m for m in ("pandas", "scipy", "sklearn") if m in sys.modules]
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


def test_imports_perezosos_traducen_dependencias(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = calibrator_module.importlib.import_module

    def block(name: str) -> Any:
        blocked = {
            "pandas",
            "numpy",
            "scipy.special",
            "scipy.optimize",
            "sklearn.linear_model",
            "sklearn.isotonic",
        }
        if name in blocked:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name)

    monkeypatch.setattr(calibrator_module.importlib, "import_module", block)

    for helper in (
        calibrator_module._import_pandas,
        calibrator_module._import_numpy,
        calibrator_module._import_scipy_expit,
        calibrator_module._import_scipy_brentq,
        calibrator_module._import_logistic_regression,
        calibrator_module._import_isotonic_regression,
    ):
        with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
            helper()


def test_dependency_versions_traduce_dependencia_ausente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = calibrator_module.importlib.import_module

    def block_scipy(name: str) -> Any:
        if name == "scipy":
            raise ModuleNotFoundError("No module named 'scipy'", name="scipy")
        return real_import(name)

    monkeypatch.setattr(calibrator_module.importlib, "import_module", block_scipy)
    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[scoring\]"):
        calibrator_module._dependency_versions(include_scipy=True, include_sklearn=False)

    monkeypatch.setattr(calibrator_module.importlib, "import_module", real_import)
    versions = calibrator_module._dependency_versions(include_scipy=False, include_sklearn=True)
    assert "scikit-learn" in versions
    assert "scipy" not in versions


def _raw_frame(
    eta: list[float],
    *,
    target: list[float | int] | None = None,
    partition: list[str] | None = None,
) -> pd.DataFrame:
    n = len(eta)
    targets = target if target is not None else [0 if i % 2 == 0 else 1 for i in range(n)]
    partitions = partition if partition is not None else ["desarrollo"] * n
    return pd.DataFrame(
        {
            "partition": partitions,
            "target": targets,
            "linear_predictor": eta,
            "pd_raw": [_sigmoid(value) for value in eta],
        },
        index=[f"c{i}" for i in range(n)],
    )


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(probability: float) -> float:
    return math.log(probability) - math.log1p(-probability)


def _bisect_delta(eta: list[float], target_pd: float) -> float:
    lower = _logit(target_pd) - max(eta) - 8.0
    upper = _logit(target_pd) - min(eta) + 8.0
    for _ in range(200):
        mid = (lower + upper) / 2.0
        mean = sum(_sigmoid(value + mid) for value in eta) / len(eta)
        if mean < target_pd:
            lower = mid
        else:
            upper = mid
    return (lower + upper) / 2.0


_FLOAT_COLUMNS = (
    "linear_predictor",
    "pd_raw",
    "linear_predictor_calibrated",
    "pd_calibrated",
)
