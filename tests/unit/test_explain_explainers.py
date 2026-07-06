"""Tests de ``explain.explainers``: analítico exacto, wrappers SHAP perezosos y factory (SDD-14).

La descomposición analítica del scorecard se ejerce con **golden values calculados a mano** (no
requiere ``shap``). Los envoltorios SHAP se ejercen con un explainer nativo **fake** que emula la
superficie mínima de la librería (``expected_value`` + ``shap_values``), cubriendo el 100% del
cableado sin instalar ``shap``; la puerta de dependencia faltante se prueba con la ausencia real de
la librería. Un subproceso verifica el import liviano.
"""

from __future__ import annotations

import importlib.util
import math
import subprocess
import sys
import types
from typing import Any

import numpy as np
import pytest

from nikodym.core.exceptions import MissingDependencyError
from nikodym.explain.exceptions import (
    ExplainConfigError,
    ExplainDataError,
    ExplainExplainerError,
)
from nikodym.explain.explainers import (
    AnalyticLinearExplainer,
    ContributionExplainer,
    KernelShapExplainer,
    LinearShapExplainer,
    TreeShapExplainer,
    resolve_explainer,
    resolve_explainer_kind,
)

# β, alpha y baseline del scorecard de juguete (2 features) para los golden analíticos.
_BETA = (0.8, -0.5)
_ALPHA = 0.1
_BASELINE = (0.2, -0.3)
_FEATURES = ("ingreso__woe", "mora__woe")


def _analytic(**overrides: Any) -> AnalyticLinearExplainer:
    kwargs: dict[str, Any] = {
        "coefficients": _BETA,
        "intercept": _ALPHA,
        "baseline": _BASELINE,
        "feature_names": _FEATURES,
    }
    kwargs.update(overrides)
    return AnalyticLinearExplainer(**kwargs)


# ── explicador analítico exacto (scorecard) ─────────────────────────────────────────────────────
def test_analytic_base_value_y_contribuciones_golden() -> None:
    """φ_j = β_j·(WoE - baseline), φ0 = alpha + Σβ·baseline, calculados a mano."""
    explainer = _analytic()
    assert explainer.kind == "analytic_linear"
    assert explainer.is_exact is True
    assert explainer.needs_background is False
    assert explainer.shap_version() is None
    assert explainer.contribution_space_ == "log_odds"
    assert explainer.feature_names_in_ == _FEATURES

    # φ0 = 0.1 + 0.8·0.2 + (-0.5)·(-0.3) = 0.41
    assert explainer.base_value() == pytest.approx(0.41)

    import pandas as pd

    frame = pd.DataFrame(
        {
            # columnas en orden invertido: el explainer las realinea por feature_names.
            "mora__woe": [0.1, -0.3, 0.5],
            "ingreso__woe": [0.5, 0.2, 1.0],
        }
    )
    phi = explainer.contributions(frame)
    esperado = np.array(
        [
            [0.8 * (0.5 - 0.2), -0.5 * (0.1 - (-0.3))],  # [0.24, -0.20]
            [0.8 * (0.2 - 0.2), -0.5 * (-0.3 - (-0.3))],  # [0.0, 0.0]
            [0.8 * (1.0 - 0.2), -0.5 * (0.5 - (-0.3))],  # [0.64, -0.40]
        ]
    )
    assert np.allclose(phi, esperado)
    # -0.0 normalizado a +0.0 en la fila baseline.
    assert math.copysign(1.0, phi[1, 1]) == 1.0


def test_analytic_reconstruye_eta_exacto() -> None:
    """φ0 + Σ_j φ_j(x_i) reconstruye η_i = alpha + Σ_j β_j·WoE_ij (aditividad exacta, SDD-09)."""
    explainer = _analytic()
    woe = np.array([[0.5, 0.1], [1.0, 0.5], [-0.2, 0.4]])
    phi = explainer.contributions(woe)
    base = explainer.base_value()
    eta_reconstruido = base + phi.sum(axis=1)
    eta_directo = _ALPHA + woe @ np.array(_BETA)
    assert np.allclose(eta_reconstruido, eta_directo)


def test_analytic_consistente_con_puntos_salvo_factor_offset() -> None:
    """Σ puntos = Offset - Factor·η (SDD-09): consistencia salvo la escala de negocio."""
    factor, offset, n_features = 20.0, 500.0, len(_FEATURES)
    explainer = _analytic()
    woe = np.array([[0.5, 0.1], [1.0, -0.2]])
    phi = explainer.contributions(woe)
    base = explainer.base_value()
    for i in range(woe.shape[0]):
        puntos = [
            offset / n_features - factor * (_BETA[j] * woe[i, j] + _ALPHA / n_features)
            for j in range(n_features)
        ]
        eta = base + float(phi[i].sum())
        assert sum(puntos) == pytest.approx(offset - factor * eta)


def test_analytic_baseline_neutral_zero() -> None:
    """Con baseline=0, φ_j = β_j·WoE y φ0 = alpha (bin neutro, D-EXP-7)."""
    explainer = _analytic(baseline=(0.0, 0.0))
    assert explainer.base_value() == pytest.approx(_ALPHA)
    woe = np.array([[0.5, 0.1]])
    phi = explainer.contributions(woe)
    assert np.allclose(phi, [[0.8 * 0.5, -0.5 * 0.1]])


@pytest.mark.parametrize(
    ("overrides", "error", "match"),
    [
        ({"coefficients": (0.8,)}, ExplainConfigError, "misma longitud"),
        ({"coefficients": (), "baseline": (), "feature_names": ()}, ExplainConfigError, "al menos"),
        ({"feature_names": ("a", "a")}, ExplainConfigError, "repetir"),
        ({"coefficients": (0.8, float("nan"))}, ExplainDataError, "finitos"),
        ({"intercept": float("inf")}, ExplainDataError, "finitos"),
    ],
)
def test_analytic_constructor_rechaza_invalidos(
    overrides: dict[str, Any], error: type[Exception], match: str
) -> None:
    with pytest.raises(error, match=match):
        _analytic(**overrides)


def test_analytic_contributions_rechaza_datos_malformados() -> None:
    import pandas as pd

    explainer = _analytic()
    # DataFrame sin una feature requerida.
    with pytest.raises(ExplainDataError, match="faltan features"):
        explainer.contributions(pd.DataFrame({"ingreso__woe": [0.5]}))
    # ndarray con nº de columnas incorrecto.
    with pytest.raises(ExplainDataError, match="forma"):
        explainer.contributions(np.zeros((2, 3)))
    # valores no finitos en la matriz WoE.
    with pytest.raises(ExplainDataError, match="no finitos"):
        explainer.contributions(np.array([[0.5, float("inf")]]))


def test_analytic_es_contribution_explainer() -> None:
    assert isinstance(_analytic(), ContributionExplainer)
    assert not isinstance(object(), ContributionExplainer)


# ── wrappers SHAP con explainer nativo fake ─────────────────────────────────────────────────────
class _FakeNative:
    """Emula la superficie mínima de un explainer ``shap`` (expected_value + shap_values)."""

    def __init__(self, *, expected: Any, values: Any) -> None:
        self.expected_value = expected
        self._values = values
        self.last_kwargs: dict[str, Any] | None = None

    def shap_values(self, X: Any, **kwargs: Any) -> Any:  # noqa: N803
        self.last_kwargs = kwargs
        return self._values


def _tree(expected: Any, values: Any) -> TreeShapExplainer:
    return TreeShapExplainer(
        _FakeNative(expected=expected, values=values),
        shap_version="0.44.1",
        needs_background=False,
        contribution_space="log_odds",
        exact_additivity=True,
        caveat=None,
    )


def test_wrapper_atributos_de_clase() -> None:
    assert (TreeShapExplainer.kind, TreeShapExplainer.is_exact) == ("tree", True)
    assert (LinearShapExplainer.kind, LinearShapExplainer.is_exact) == ("linear", True)
    assert (KernelShapExplainer.kind, KernelShapExplainer.is_exact) == ("kernel", False)
    tree = _tree(0.3, np.array([[0.1, -0.2]]))
    assert tree.shap_version() == "0.44.1"
    assert isinstance(tree, ContributionExplainer)


@pytest.mark.parametrize(
    ("expected", "esperado"),
    [
        (0.25, 0.25),  # escalar (ndim 0)
        (np.array([0.9, 0.25]), 0.25),  # vector binario (ndim 1) → clase positiva
        (-0.0, 0.0),  # -0.0 normalizado
    ],
)
def test_wrapper_base_value_selecciona_clase_positiva(expected: Any, esperado: float) -> None:
    tree = _tree(expected, np.array([[0.1, -0.2]]))
    valor = tree.base_value()
    assert valor == pytest.approx(esperado)
    if esperado == 0.0:
        assert math.copysign(1.0, valor) == 1.0


@pytest.mark.parametrize(
    "expected",
    [np.array([0.9]), np.array([[0.1, 0.2]]), float("nan")],
)
def test_wrapper_base_value_rechaza_formas_o_no_finito(expected: Any) -> None:
    with pytest.raises(ExplainExplainerError):
        _tree(expected, np.array([[0.1, -0.2]])).base_value()


def test_wrapper_contributions_forma_2d_y_normaliza() -> None:
    tree = _tree(0.3, np.array([[0.1, -0.0, 0.2]]))
    phi = tree.contributions(np.zeros((1, 3)))
    assert phi.shape == (1, 3)
    assert math.copysign(1.0, phi[0, 1]) == 1.0


def test_wrapper_contributions_selecciona_clase_de_lista_y_3d() -> None:
    # Lista [clase0, clase1] → toma la clase positiva (índice 1).
    lista = _tree(0.3, [np.array([[9.0, 9.0]]), np.array([[0.1, -0.2]])])
    assert np.allclose(lista.contributions(np.zeros((1, 2))), [[0.1, -0.2]])
    # ndarray 3D (n, features, clases) → selecciona [:, :, 1].
    cubo = np.zeros((1, 2, 2))
    cubo[0, :, 1] = [0.3, -0.4]
    assert np.allclose(_tree(0.3, cubo).contributions(np.zeros((1, 2))), [[0.3, -0.4]])


@pytest.mark.parametrize(
    "values",
    [
        np.array([0.1, 0.2]),  # ndim 1 → forma inesperada
        [np.array([[0.1, 0.2]])],  # lista de largo 1 → sin clase positiva
        np.array([[0.1, float("inf")]]),  # no finito
    ],
)
def test_wrapper_contributions_rechaza_salidas_invalidas(values: Any) -> None:
    with pytest.raises(ExplainExplainerError):
        _tree(0.3, values).contributions(np.zeros((1, 2)))


def test_kernel_wrapper_pasa_nsamples_a_shap_values() -> None:
    native = _FakeNative(expected=0.3, values=np.array([[0.1, -0.2]]))
    kernel = KernelShapExplainer(
        native,
        shap_version="0.44.1",
        needs_background=True,
        contribution_space="probability",
        exact_additivity=False,
        caveat="muestral",
        shap_values_kwargs={"nsamples": 256},
    )
    kernel.contributions(np.zeros((1, 2)))
    assert native.last_kwargs == {"nsamples": 256}


# ── selección de explainer por backend (D-EXP-1) ────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("backend", "forced", "supports_tree", "is_linear", "esperado"),
    [
        ("xgboost", "auto", True, False, "tree"),
        ("random_forest", None, True, False, "tree"),
        ("svm", "auto", False, True, "linear"),
        ("svm", None, False, False, "kernel"),
        ("xgboost", "tree", True, False, "tree"),
        ("svm", "linear", False, True, "linear"),
        ("svm", "kernel", False, False, "kernel"),
    ],
)
def test_resolve_kind_mapea_backend(
    backend: str, forced: Any, supports_tree: bool, is_linear: bool, esperado: str
) -> None:
    kind = resolve_explainer_kind(
        backend=backend,
        model_kind="ml",
        forced=forced,
        supports_tree=supports_tree,
        is_linear_model=is_linear,
    )
    assert kind == esperado


def test_resolve_kind_scorecard_siempre_analitico() -> None:
    assert (
        resolve_explainer_kind(
            backend=None, model_kind="scorecard", forced=None, supports_tree=False
        )
        == "analytic_linear"
    )
    assert (
        resolve_explainer_kind(
            backend=None, model_kind="scorecard", forced="analytic_linear", supports_tree=False
        )
        == "analytic_linear"
    )


@pytest.mark.parametrize(
    ("model_kind", "forced", "supports_tree", "is_linear", "match"),
    [
        ("scorecard", "tree", False, False, "analítica"),
        ("ml", "analytic_linear", True, False, "exclusivo del scorecard"),
        ("ml", "tree", False, False, "backend de árboles"),
        ("ml", "linear", True, False, "modelo lineal"),
    ],
)
def test_resolve_kind_forced_incompatible_falla(
    model_kind: str, forced: Any, supports_tree: bool, is_linear: bool, match: str
) -> None:
    with pytest.raises(ExplainConfigError, match=match):
        resolve_explainer_kind(
            backend="svm",
            model_kind=model_kind,  # type: ignore[arg-type]
            forced=forced,
            supports_tree=supports_tree,
            is_linear_model=is_linear,
        )


# ── factory resolve_explainer ────────────────────────────────────────────────────────────────────
def test_resolve_explainer_scorecard_no_importa_shap() -> None:
    explainer = resolve_explainer(
        backend=None,
        model_kind="scorecard",
        forced=None,
        supports_tree=False,
        coefficients=_BETA,
        intercept=_ALPHA,
        baseline=_BASELINE,
        feature_names=_FEATURES,
    )
    assert isinstance(explainer, AnalyticLinearExplainer)
    assert explainer.base_value() == pytest.approx(0.41)
    assert "shap" not in sys.modules


def test_resolve_explainer_scorecard_sin_insumos_falla() -> None:
    with pytest.raises(ExplainConfigError, match="requiere coefficients"):
        resolve_explainer(backend=None, model_kind="scorecard", forced=None, supports_tree=False)


def _install_fake_shap(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected: Any = 0.3,
    values: Any = None,
    version: str | None = "0.99.0-fake",
) -> types.ModuleType:
    if values is None:
        values = np.array([[0.1, -0.2, 0.05]])
    module = types.ModuleType("shap")
    if version is not None:
        module.__version__ = version  # type: ignore[attr-defined]

    class _FakeExplainer:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.expected_value = expected
            self.init_args = args
            self.init_kwargs = kwargs

        def shap_values(self, X: Any, **kwargs: Any) -> Any:  # noqa: N803
            return values

    module.TreeExplainer = _FakeExplainer  # type: ignore[attr-defined]
    module.LinearExplainer = _FakeExplainer  # type: ignore[attr-defined]
    module.KernelExplainer = _FakeExplainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", module)
    return module


def test_resolve_explainer_tree_con_fake_shap(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_shap(monkeypatch, expected=0.3, values=np.array([[0.1, -0.2]]))
    explainer = resolve_explainer(
        backend="xgboost",
        model_kind="ml",
        forced="auto",
        supports_tree=True,
        model=object(),
        feature_perturbation="tree_path_dependent",
        contribution_space="log_odds",
    )
    assert isinstance(explainer, TreeShapExplainer)
    assert explainer.needs_background is False
    assert explainer.contribution_space_ == "log_odds"
    assert explainer.caveat_ is None
    assert explainer.shap_version() == "0.99.0-fake"
    assert explainer.base_value() == pytest.approx(0.3)
    assert np.allclose(explainer.contributions(np.zeros((1, 2))), [[0.1, -0.2]])


def test_resolve_explainer_tree_interventional_needs_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_shap(monkeypatch)
    explainer = resolve_explainer(
        backend="xgboost",
        model_kind="ml",
        forced="tree",
        supports_tree=True,
        model=object(),
        background=np.zeros((5, 3)),
        feature_perturbation="interventional",
    )
    assert explainer.needs_background is True


def test_resolve_explainer_linear_y_version_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_shap(monkeypatch, version=None)
    explainer = resolve_explainer(
        backend="svm",
        model_kind="ml",
        forced="linear",
        supports_tree=False,
        is_linear_model=True,
        model=object(),
        background=np.zeros((5, 3)),
    )
    assert isinstance(explainer, LinearShapExplainer)
    assert explainer.needs_background is True
    assert explainer.shap_version() is None


def test_resolve_explainer_kernel_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_shap(monkeypatch, values=np.array([[0.2, -0.1, 0.0]]))
    explainer = resolve_explainer(
        backend="svm",
        model_kind="ml",
        forced="kernel",
        supports_tree=False,
        predict_fn=lambda x: x,
        background=np.zeros((5, 3)),
        nsamples=128,
    )
    assert isinstance(explainer, KernelShapExplainer)
    assert explainer.is_exact is False


@pytest.mark.parametrize(
    ("backend", "contribution_space", "esperado_space", "tiene_caveat"),
    [
        ("xgboost", "log_odds", "log_odds", False),
        ("random_forest", "log_odds", "probability", True),
        ("svm", "log_odds", "probability", True),
        ("xgboost", "probability", "probability", True),
    ],
)
def test_resolve_explainer_espacio_efectivo_y_caveat(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    contribution_space: Any,
    esperado_space: str,
    tiene_caveat: bool,
) -> None:
    _install_fake_shap(monkeypatch)
    explainer = resolve_explainer(
        backend=backend,
        model_kind="ml",
        forced="auto",
        supports_tree=backend in {"xgboost", "random_forest"},
        is_linear_model=False,
        model=object(),
        predict_fn=lambda x: x,
        background=np.zeros((3, 3)),
        contribution_space=contribution_space,
    )
    assert explainer.contribution_space_ == esperado_space
    assert (explainer.caveat_ is not None) is tiene_caveat


@pytest.mark.skipif(
    importlib.util.find_spec("shap") is not None,
    reason="Prueba la puerta de dependencia con la ausencia REAL de shap; el job all-extras lo instala.",
)
def test_resolve_explainer_sin_extra_shap_levanta_missing_dependency() -> None:
    """Sin ``shap`` instalado, construir un explainer ML nombra el extra [explain]."""
    assert "shap" not in sys.modules
    with pytest.raises(MissingDependencyError, match=r"nikodym\[explain\]"):
        resolve_explainer(
            backend="xgboost",
            model_kind="ml",
            forced="tree",
            supports_tree=True,
            model=object(),
        )


# ── import liviano (núcleo) ─────────────────────────────────────────────────────────────────────
def test_import_explainers_liviano_no_arrastra_shap_ni_tabulares() -> None:
    code = (
        "import nikodym.explain.explainers, sys;"
        "bloqueados=[m for m in ('shap','matplotlib','sklearn','pandas','numpy') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
