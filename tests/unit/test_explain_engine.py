"""Tests de ``explain.engine`` (``UnifiedExplainer``): mitad ML SHAP + mitad scorecard (SDD-14).

La mitad ML se ejerce con un explainer ``shap`` **fake** (módulo instalado en ``sys.modules``) y un
challenger **fake** con la superficie sklearn-like mínima (``backend``/``feature_names_in_``/
``estimator_``/``predict_pd``); así se cubre el 100% del cableado sin instalar ``shap``. La mitad
scorecard es **analítica exacta** y no necesita ``shap``. Golden values calculados a mano; la
aditividad se verifica en log-odds (Tree/analítico) y en probabilidad (RF/SVM), la reproducibilidad
byte-a-byte con misma semilla, y la comparativa sobre rankings conocidos con IV.
"""

from __future__ import annotations

import subprocess
import sys
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nikodym.core.audit import InMemoryAuditSink
from nikodym.explain.config import ExplainConfig
from nikodym.explain.engine import ExplanationBundle, UnifiedExplainer
from nikodym.explain.exceptions import ExplainDataError, ExplainExplainerError


# ── fakes de shap y del challenger ───────────────────────────────────────────────────────────────
def _install_fake_shap(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected: Any,
    values: Any,
    version: str | None = "0.99.0-fake",
) -> types.ModuleType:
    """Instala un módulo ``shap`` fake cuyos explainers devuelven ``expected``/``values`` fijos."""
    module = types.ModuleType("shap")
    if version is not None:
        module.__version__ = version  # type: ignore[attr-defined]

    class _FakeExplainer:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.expected_value = expected

        def shap_values(self, X: Any, **kwargs: Any) -> Any:  # noqa: N803
            return values

    module.TreeExplainer = _FakeExplainer  # type: ignore[attr-defined]
    module.LinearExplainer = _FakeExplainer  # type: ignore[attr-defined]
    module.KernelExplainer = _FakeExplainer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "shap", module)
    return module


class _FakeChallenger:
    """Emula la API sklearn-like de ``MLChallenger`` que ``explain`` consume (sin reentrenar)."""

    def __init__(
        self,
        *,
        backend: str,
        feature_names: tuple[str, ...],
        pd_hat: Any,
        kernel: str | None = None,
    ) -> None:
        self.backend = backend
        self.feature_names_in_ = feature_names
        self.estimator_ = object()
        self.classes_ = np.array([0, 1])
        self._pd_hat = np.asarray(pd_hat, dtype="float64")
        if kernel is not None:
            self.hyperparameters = types.SimpleNamespace(kernel=kernel)

    def predict_pd(self, X: Any) -> Any:  # noqa: N803
        return self._pd_hat


_ML_FEATURES = ("f0__woe", "f1__woe")


def _logodds_case() -> tuple[Any, float, Any, Any]:
    """Caso log-odds consistente: ``φ₀ + Σφ = margen`` y ``pd = sigmoid(margen)`` (exacto)."""
    phi = np.array([[0.0, 0.1], [-0.4, -0.35], [0.4, 0.25]])
    phi0 = 0.35
    margin = phi0 + phi.sum(axis=1)
    pd_hat = 1.0 / (1.0 + np.exp(-margin))
    return phi, phi0, margin, pd_hat


def _ml_frame(n_rows: int) -> pd.DataFrame:
    """Frame de features WoE del scope (el fake ignora su contenido; sólo importan las columnas)."""
    return pd.DataFrame(
        {name: np.linspace(0.1, 0.9, n_rows) for name in _ML_FEATURES}, dtype="float64"
    )


# ── explain_ml: Tree exacto, aditividad en log-odds y global ─────────────────────────────────────
def test_explain_ml_tree_log_odds_global_y_reason_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tree/xgboost: aditividad log-odds, ``Φ_j`` con orden estable y reason codes golden."""
    phi, phi0, margin, pd_hat = _logodds_case()
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_hat)
    explainer = UnifiedExplainer(top_n=5)
    bundle = explainer.explain_ml(estimator, _ml_frame(3), seed=7)

    assert bundle.source_model == "ml"
    assert bundle.explainer_kind == "tree"
    assert bundle.contribution_space == "log_odds"
    assert bundle.background_size is None
    assert bundle.deterministic is True
    # Φ_j = mean|φ_j|: f0 = (0+0.4+0.4)/3, f1 = (0.1+0.35+0.25)/3 ⇒ f0 domina.
    assert [record.feature for record in bundle.shap_global] == ["f0__woe", "f1__woe"]
    assert bundle.shap_global[0].mean_abs_contribution == pytest.approx(0.8 / 3)
    assert bundle.shap_global[0].rank == 1
    # prediction reconstruye el margen (aditividad exacta).
    predicciones = [record.prediction for record in bundle.shap_local]
    assert predicciones == pytest.approx(list(margin))
    # reason codes: fila 1 (φ<0 en ambas) queda vacía; fila 2 rankea f0 sobre f1.
    assert bundle.reason_codes[1].reason_codes == ()
    fila2 = bundle.reason_codes[2].reason_codes
    assert [code.feature for code in fila2] == ["f0__woe", "f1__woe"]
    assert all(code.direction == "increases_pd" for code in fila2)

    # atributos fiteados.
    assert explainer.explainer_kind_ == "tree"
    assert explainer.base_value_ == pytest.approx(phi0)
    assert explainer.shap_version_ == "0.99.0-fake"
    assert explainer.background_size_ is None
    assert explainer.feature_names_in_ == _ML_FEATURES
    assert explainer.contribution_space_ == "log_odds"
    assert explainer.seed_ == 7
    assert explainer.deterministic_ is True


def test_explain_ml_reproducible_byte_a_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dos corridas Tree con misma semilla y datos ⇒ bundles idénticos (byte-a-byte)."""
    phi, phi0, _margin, pd_hat = _logodds_case()
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_hat)
    explainer = UnifiedExplainer()
    primero = explainer.explain_ml(estimator, _ml_frame(3), seed=11)
    segundo = explainer.explain_ml(estimator, _ml_frame(3), seed=11)
    assert primero == segundo


def test_explain_ml_tree_interventional_construye_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tree ``interventional`` necesita background: se muestrea seedeado del scope."""
    phi, phi0, _margin, pd_hat = _logodds_case()
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_hat)
    explainer = UnifiedExplainer(feature_perturbation="interventional", background_size=2)
    bundle = explainer.explain_ml(estimator, _ml_frame(3), seed=3)
    assert bundle.background_size == 2
    assert explainer.background_size_ == 2


def test_explain_ml_linear_probability_needs_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """SVM lineal degrada a probabilidad; la aditividad se verifica en escala de probabilidad."""
    phi = np.array([[0.1, -0.05], [0.2, 0.1]])
    phi0 = 0.3
    pd_hat = phi0 + phi.sum(axis=1)  # [0.35, 0.6] ∈ [0, 1]
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(
        backend="svm", feature_names=_ML_FEATURES, pd_hat=pd_hat, kernel="linear"
    )
    explainer = UnifiedExplainer(ml_explainer="linear")
    bundle = explainer.explain_ml(estimator, _ml_frame(2), seed=5)
    assert bundle.explainer_kind == "linear"
    assert bundle.contribution_space == "probability"
    assert bundle.background_size == 2
    assert bundle.deterministic is True


def test_explain_ml_background_explicito_no_muestrea(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un background explícito se usa tal cual (no se muestrea del scope)."""
    phi = np.array([[0.1, -0.05], [0.2, 0.1]])
    phi0 = 0.3
    pd_hat = phi0 + phi.sum(axis=1)
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(
        backend="svm", feature_names=_ML_FEATURES, pd_hat=pd_hat, kernel="linear"
    )
    background = _ml_frame(4)
    explainer = UnifiedExplainer(ml_explainer="linear")
    bundle = explainer.explain_ml(estimator, _ml_frame(2), background=background, seed=1)
    assert bundle.background_size == 4


def test_explain_ml_kernel_multihilo_no_determinista(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kernel (muestral) con ``n_threads>1`` ⇒ ``deterministic_=False`` (sin byte-a-byte)."""
    phi = np.array([[0.2, -0.1], [0.05, 0.3]])
    pd_hat = np.array([0.4, 0.6])
    _install_fake_shap(monkeypatch, expected=0.3, values=phi)
    estimator = _FakeChallenger(
        backend="svm", feature_names=_ML_FEATURES, pd_hat=pd_hat, kernel="rbf"
    )
    explainer = UnifiedExplainer(ml_explainer="kernel", n_threads=2, deterministic=True)
    bundle = explainer.explain_ml(estimator, _ml_frame(2), seed=9)
    assert bundle.explainer_kind == "kernel"
    assert bundle.deterministic is False
    assert explainer.deterministic_ is False


def test_explain_ml_kernel_single_thread_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kernel con semilla + single-thread es reproducible (deterministic_=True) y byte-a-byte."""
    phi = np.array([[0.2, -0.1], [0.05, 0.3]])
    pd_hat = np.array([0.4, 0.6])
    _install_fake_shap(monkeypatch, expected=0.3, values=phi)
    estimator = _FakeChallenger(
        backend="svm", feature_names=_ML_FEATURES, pd_hat=pd_hat, kernel="rbf"
    )
    explainer = UnifiedExplainer(ml_explainer="kernel", n_threads=1, deterministic=True)
    primero = explainer.explain_ml(estimator, _ml_frame(2), seed=4)
    segundo = explainer.explain_ml(estimator, _ml_frame(2), seed=4)
    assert primero.deterministic is True
    assert primero == segundo


def test_explain_ml_additividad_rota_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ``φ₀+Σφ`` inconsistente con el margen ⇒ ``ExplainExplainerError`` (no se silencia)."""
    phi, phi0, _margin, _pd = _logodds_case()
    pd_incoherente = np.array([0.5, 0.5, 0.5])  # logit=0 ≠ margen reconstruido
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(
        backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_incoherente
    )
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainExplainerError, match="aditividad rota"):
        explainer.explain_ml(estimator, _ml_frame(3), seed=0)


def test_explain_ml_check_additivity_false_no_verifica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``check_additivity=False`` no se verifica la aditividad aunque sea inconsistente."""
    phi, phi0, _margin, _pd = _logodds_case()
    pd_incoherente = np.array([0.5, 0.5, 0.5])
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(
        backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_incoherente
    )
    explainer = UnifiedExplainer(check_additivity=False)
    bundle = explainer.explain_ml(estimator, _ml_frame(3), seed=0)
    assert bundle.explainer_kind == "tree"


@pytest.mark.parametrize(
    ("pd_hat", "match"),
    [
        (np.array([float("nan"), 0.5, 0.5]), "no son finitas"),
        (np.array([1.5, 0.5, 0.5]), "fuera de"),
        (np.array([1.0, 0.5, 0.5]), r"\{0, 1\}"),
    ],
)
def test_explain_ml_pd_invalida_levanta(
    monkeypatch: pytest.MonkeyPatch, pd_hat: Any, match: str
) -> None:
    """PD no finitas, fuera de rango o en los bordes (log-odds) ⇒ ``ExplainDataError``."""
    phi, phi0, _margin, _pd = _logodds_case()
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_hat)
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match=match):
        explainer.explain_ml(estimator, _ml_frame(3), seed=0)


def test_explain_ml_predict_pd_forma_invalida(monkeypatch: pytest.MonkeyPatch) -> None:
    """``predict_pd`` que no devuelve un vector (n,) ⇒ ``ExplainDataError``."""
    phi, phi0, _margin, _pd = _logodds_case()
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(
        backend="xgboost", feature_names=_ML_FEATURES, pd_hat=np.array([0.4, 0.6])
    )
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match="vector"):
        explainer.explain_ml(estimator, _ml_frame(3), seed=0)


def test_explain_ml_estimator_sin_feature_names_levanta() -> None:
    """Un estimador sin ``feature_names_in_`` (no fiteado) ⇒ ``ExplainDataError``."""
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match="feature_names_in_"):
        explainer.explain_ml(object(), _ml_frame(3), seed=0)


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        ([0.1, 0.2, 0.3], "requiere pandas.DataFrame"),
        (pd.DataFrame({name: [] for name in _ML_FEATURES}), "vacío"),
        (pd.DataFrame({"f0__woe": [0.1, 0.2, 0.3]}), "no coinciden"),
    ],
)
def test_explain_ml_alineacion_features_falla(frame: Any, match: str) -> None:
    """Entrada no tabular, vacía o con features desalineadas ⇒ ``ExplainDataError``."""
    estimator = _FakeChallenger(
        backend="xgboost", feature_names=_ML_FEATURES, pd_hat=np.array([0.4, 0.5, 0.6])
    )
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match=match):
        explainer.explain_ml(estimator, frame, seed=0)


def test_explain_ml_no_muta_estimator_ni_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """``explain_ml`` no muta el estimador ni el frame de features (copias defensivas)."""
    phi, phi0, _margin, pd_hat = _logodds_case()
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_hat)
    frame = _ml_frame(3)
    frame_original = frame.copy(deep=True)
    explainer = UnifiedExplainer()
    explainer.explain_ml(estimator, frame, seed=2)
    assert frame.equals(frame_original)
    assert estimator.feature_names_in_ == _ML_FEATURES


def test_explain_ml_audita_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """``explain_ml`` con un sink registra la decisión del explainer elegido."""
    phi, phi0, _margin, pd_hat = _logodds_case()
    _install_fake_shap(monkeypatch, expected=phi0, values=phi)
    estimator = _FakeChallenger(backend="xgboost", feature_names=_ML_FEATURES, pd_hat=pd_hat)
    sink = InMemoryAuditSink()
    UnifiedExplainer().explain_ml(estimator, _ml_frame(3), seed=6, audit=sink)
    reglas = [event.payload["regla"] for event in sink.events]
    assert "explain_explainer" in reglas


# ── explain_scorecard: analítico exacto, contribuciones por bin y baseline ────────────────────────
def _coefficients(*, with_intercept: bool = True) -> pd.DataFrame:
    """Coeficientes del scorecard de juguete (2 features + intercepto opcional)."""
    filas = [
        {"feature": "ingreso", "woe_column": "ingreso__woe", "beta": 0.8},
        {"feature": "mora", "woe_column": "mora__woe", "beta": -0.5},
    ]
    if with_intercept:
        filas.insert(0, {"feature": "intercept", "woe_column": "const", "beta": 0.1})
    return pd.DataFrame(filas)


def _x_woe() -> pd.DataFrame:
    """Scope WoE del scorecard con signos de η mixtos (cubre el sigmoide estable)."""
    return pd.DataFrame(
        {"ingreso__woe": [0.5, 0.0, 1.0], "mora__woe": [0.1, 1.0, -0.2]}, dtype="float64"
    )


def _woe_tables() -> dict[str, pd.DataFrame]:
    """Tablas WoE por atributo con una fila agregada y una fila sin WoE (se saltan)."""
    return {
        "ingreso": pd.DataFrame(
            {"Bin": ["b0", "b1", "b2", "Totals"], "WoE": [0.2, 0.5, 1.0, np.nan]}
        ),
        "mora": pd.DataFrame({"Bin": ["m1", "m2", "missing"], "WoE": [0.1, -0.2, np.nan]}),
    }


def test_explain_scorecard_analitico_golden() -> None:
    """β·(WoE - baseline) exacto: aditividad log-odds, global, reason codes y bins."""
    explainer = UnifiedExplainer()
    bundle = explainer.explain_scorecard(_coefficients(), _woe_tables(), _x_woe())

    assert bundle.source_model == "scorecard"
    assert bundle.explainer_kind == "analytic_linear"
    assert bundle.shap_version is None
    # φ0 = 0.1 + 0.8·0.5 - 0.5·0.3 = 0.35 (baseline = medias 0.5, 0.3).
    assert bundle.base_value == pytest.approx(0.35)
    # aditividad exacta: prediction = η = 0.1 + 0.8·WoE_ing - 0.5·WoE_mora.
    eta_directo = 0.1 + 0.8 * np.array([0.5, 0.0, 1.0]) - 0.5 * np.array([0.1, 1.0, -0.2])
    assert [rec.prediction for rec in bundle.shap_local] == pytest.approx(list(eta_directo))
    # ranking por |β·baseline|: |0.8·0.5|=0.4 > |-0.5·0.3|=0.15.
    assert bundle.driver_ranking == ("ingreso__woe", "mora__woe")

    contribuciones = bundle.scorecard_contributions
    assert list(contribuciones.columns) == [
        "feature",
        "woe_column",
        "bin_label",
        "woe",
        "beta",
        "baseline",
        "contribution",
        "points",
        "direction",
    ]
    # ingreso: b0 (WoE 0.2) baja la PD, b1 (=baseline) neutro, b2 (WoE 1.0) la sube.
    ingreso = contribuciones[contribuciones["feature"] == "ingreso"].set_index("bin_label")
    assert ingreso.loc["b0", "direction"] == "decreases_pd"
    assert ingreso.loc["b1", "direction"] == "neutral"
    assert ingreso.loc["b1", "contribution"] == pytest.approx(0.0)
    assert ingreso.loc["b2", "contribution"] == pytest.approx(0.8 * (1.0 - 0.5))
    assert ingreso.loc["b2", "points"] == pytest.approx(0.8 * 1.0)
    # la fila agregada "Totals" y la fila "missing" (WoE NaN) se descartan.
    assert "Totals" not in ingreso.index
    assert "missing" not in contribuciones["bin_label"].tolist()


def test_explain_scorecard_baseline_neutral_zero() -> None:
    """Con baseline ``neutral_zero`` el baseline es 0 y φ0 = intercepto."""
    explainer = UnifiedExplainer(scorecard_baseline="neutral_zero")
    bundle = explainer.explain_scorecard(_coefficients(), _woe_tables(), _x_woe())
    assert bundle.base_value == pytest.approx(0.1)
    baseline_col = bundle.scorecard_contributions["baseline"].tolist()
    assert all(value == 0.0 for value in baseline_col)


def test_explain_scorecard_ranking_por_iv() -> None:
    """Con ``binning_summary`` el ranking del campeón usa el IV (nitpick A15(2))."""
    summary = pd.DataFrame({"name": ["ingreso", "mora"], "iv": [0.1, 0.5]})
    explainer = UnifiedExplainer()
    bundle = explainer.explain_scorecard(
        _coefficients(), _woe_tables(), _x_woe(), binning_summary=summary
    )
    # mora tiene mayor IV ⇒ encabeza el ranking pese a menor |β·baseline|.
    assert bundle.driver_ranking == ("mora__woe", "ingreso__woe")


def test_explain_scorecard_sin_intercepto_usa_cero() -> None:
    """Sin fila de intercepto, el intercepto por defecto es 0.0."""
    explainer = UnifiedExplainer(scorecard_baseline="neutral_zero")
    bundle = explainer.explain_scorecard(
        _coefficients(with_intercept=False), _woe_tables(), _x_woe()
    )
    assert bundle.base_value == pytest.approx(0.0)


def test_explain_scorecard_tabla_ausente_se_salta() -> None:
    """Un atributo sin tabla WoE se salta en las contribuciones por bin (no error)."""
    tables = {"ingreso": _woe_tables()["ingreso"]}  # falta "mora"
    explainer = UnifiedExplainer()
    bundle = explainer.explain_scorecard(_coefficients(), tables, _x_woe())
    assert set(bundle.scorecard_contributions["feature"]) == {"ingreso"}


def test_explain_scorecard_woe_tables_no_mapa_da_frame_vacio() -> None:
    """``woe_tables`` sin ``get`` (no es un mapa) ⇒ contribuciones vacías, sin romper."""
    explainer = UnifiedExplainer()
    bundle = explainer.explain_scorecard(_coefficients(), object(), _x_woe())
    assert bundle.scorecard_contributions.empty


def test_explain_scorecard_audita_decision() -> None:
    """``explain_scorecard`` con un sink registra la decisión del baseline."""
    sink = InMemoryAuditSink()
    UnifiedExplainer().explain_scorecard(_coefficients(), _woe_tables(), _x_woe(), audit=sink)
    reglas = [event.payload["regla"] for event in sink.events]
    assert "explain_scorecard" in reglas


@pytest.mark.parametrize(
    ("coefficients", "match"),
    [
        (pd.DataFrame({"feature": ["a"], "beta": [0.5]}), "requiere las columnas"),
        (
            pd.DataFrame({"feature": ["intercept"], "woe_column": ["const"], "beta": [0.1]}),
            "no contiene features",
        ),
    ],
)
def test_explain_scorecard_coeficientes_invalidos(coefficients: pd.DataFrame, match: str) -> None:
    """Coeficientes sin columnas requeridas o sólo con intercepto ⇒ ``ExplainDataError``."""
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match=match):
        explainer.explain_scorecard(coefficients, _woe_tables(), _x_woe())


def test_explain_scorecard_tabla_woe_sin_columnas() -> None:
    """Una tabla WoE sin las columnas 'Bin'/'WoE' ⇒ ``ExplainDataError``."""
    tables = {
        "ingreso": pd.DataFrame({"foo": [1]}),
        "mora": _woe_tables()["mora"],
    }
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match="'Bin' y 'WoE'"):
        explainer.explain_scorecard(_coefficients(), tables, _x_woe())


def test_explain_scorecard_summary_sin_columnas() -> None:
    """Un ``binning_summary`` sin columnas 'name'/'iv' ⇒ ``ExplainDataError``."""
    summary = pd.DataFrame({"variable": ["ingreso"], "info_value": [0.1]})
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match="'name' e 'iv'"):
        explainer.explain_scorecard(
            _coefficients(), _woe_tables(), _x_woe(), binning_summary=summary
        )


# ── compare_drivers ──────────────────────────────────────────────────────────────────────────────
def test_compare_drivers_rankings_conocidos() -> None:
    """Solape correcto sobre rankings conocidos: both / scorecard_only / ml_only."""
    scorecard = ExplanationBundle(
        source_model="scorecard", driver_ranking=("a__woe", "b__woe", "c__woe")
    )
    ml = ExplanationBundle(source_model="ml", driver_ranking=("b__woe", "d__woe", "a__woe"))
    explainer = UnifiedExplainer()
    records = explainer.compare_drivers(scorecard, ml, top_k=2)
    por_feature = {record.feature: record for record in records}
    assert set(por_feature) == {"a__woe", "b__woe", "d__woe"}
    assert por_feature["a__woe"].agreement == "scorecard_only"
    assert por_feature["a__woe"].scorecard_rank == 1
    assert por_feature["a__woe"].ml_rank == 3
    assert por_feature["b__woe"].agreement == "both"
    assert por_feature["d__woe"].agreement == "ml_only"
    assert por_feature["d__woe"].scorecard_rank is None


def test_compare_drivers_top_k_invalido() -> None:
    """``top_k < 1`` ⇒ ``ExplainDataError``."""
    ml = ExplanationBundle(source_model="ml", driver_ranking=("a__woe",))
    explainer = UnifiedExplainer()
    with pytest.raises(ExplainDataError, match="top_k debe ser"):
        explainer.compare_drivers(None, ml, top_k=0)


def test_compare_drivers_sin_scorecard_targets_both_degrada() -> None:
    """``targets='both'`` sin scorecard ⇒ audita ``explain_scorecard_skipped`` y queda ML-only."""
    ml = ExplanationBundle(source_model="ml", driver_ranking=("a__woe", "b__woe"))
    sink = InMemoryAuditSink()
    explainer = UnifiedExplainer(targets="both")
    explainer._audit_sink = sink  # lo fija normalmente explain_ml; aquí se inyecta directo.
    records = explainer.compare_drivers(None, ml, top_k=2)
    assert all(record.agreement == "ml_only" for record in records)
    reglas = [event.payload["regla"] for event in sink.events]
    assert reglas == ["explain_scorecard_skipped"]


def test_compare_drivers_sin_scorecard_targets_ml_no_audita() -> None:
    """``targets='ml'`` sin scorecard no audita degradación (no se esperaba scorecard)."""
    ml = ExplanationBundle(source_model="ml", driver_ranking=("a__woe",))
    sink = InMemoryAuditSink()
    explainer = UnifiedExplainer(targets="ml")
    explainer._audit_sink = sink
    explainer.compare_drivers(None, ml, top_k=1)
    assert sink.events == []


def test_compare_drivers_sin_audit_sink_no_rompe() -> None:
    """Sin ``_audit_sink`` previo, la degradación no rompe (sink ausente ⇒ no-op)."""
    ml = ExplanationBundle(source_model="ml", driver_ranking=("a__woe",))
    explainer = UnifiedExplainer(targets="both")
    records = explainer.compare_drivers(None, ml, top_k=1)
    assert [record.feature for record in records] == ["a__woe"]


# ── from_config y bundle ─────────────────────────────────────────────────────────────────────────
def test_from_config_desde_config_y_dict() -> None:
    """``from_config`` acepta un ``ExplainConfig`` o un mapping y aplana los sub-configs."""
    desde_config = UnifiedExplainer.from_config(ExplainConfig(targets="ml"))
    assert desde_config.targets == "ml"
    assert desde_config.top_n == 5
    desde_dict = UnifiedExplainer.from_config({"targets": "scorecard", "n_threads": 3})
    assert desde_dict.targets == "scorecard"
    assert desde_dict.n_threads == 3


def test_explanation_bundle_defaults() -> None:
    """El bundle intermedio expone defaults inmutables razonables."""
    bundle = ExplanationBundle(source_model="ml")
    assert bundle.shap_global == ()
    assert bundle.scorecard_contributions is None
    assert bundle.contribution_space == "log_odds"
    assert bundle.deterministic is True


def test_import_engine_liviano_no_arrastra_shap_ni_tabulares() -> None:
    """``import nikodym.explain.engine`` no arrastra shap/matplotlib/sklearn/pandas/numpy."""
    code = (
        "import nikodym.explain.engine, sys;"
        "bloqueados=[m for m in ('shap','matplotlib','sklearn','pandas','numpy') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
