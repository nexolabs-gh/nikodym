"""Explicadores de contribuciones de ``explain``: analítico exacto + SHAP perezoso (SDD-14 §3/§7).

Este módulo materializa la **atribución aditiva** de una predicción de riesgo, `f(x) = φ₀ + Σ_j φ_j`
(SDD-14 §3), en dos mundos bajo un contrato común, el :class:`ContributionExplainer` Protocol:

- :class:`AnalyticLinearExplainer` — descompone el **scorecard logístico** de forma **exacta y sin
  ``shap``**: `φ_j(x_i) = β_j·(WoE_ij - baseline_j)` y `φ₀ = intercepto + Σ_j β_j·baseline_j`, de
  modo que `φ₀ + Σ_j φ_j = η_i` (el log-odds de SDD-09). Es álgebra cerrada, determinista, y no
  arrastra el extra ``[explain]``.
- :class:`TreeShapExplainer` / :class:`LinearShapExplainer` / :class:`KernelShapExplainer` —
  **envoltorios perezosos** sobre la librería ``shap`` (el ``import shap`` vive **dentro** de la
  factory :func:`resolve_explainer`, nunca en top-level). No reimplementan Shapley: orquestan
  ``shap.TreeExplainer``/``LinearExplainer``/``KernelExplainer``, seleccionan la clase positiva,
  normalizan la salida a una matriz ``(n_obs, n_features)`` finita y marcan el espacio de
  contribución efectivo.

**Espacio aditivo dependiente del backend (nitpick A15(1), D-EXP-4).** El *additivity check* en
log-odds solo es exacto para modelos con **margen log-odds real** (logística analítica, GBDT de
pérdida logística). Random Forest (voto→probabilidad) y SVM con Platt scaling **no** exponen un
margen log-odds aditivo exacto: para ellos el explainer degrada ``contribution_space_`` a
``"probability"`` y expone un ``caveat_`` explícito, sin silenciar la limitación.

**Núcleo liviano (SDD-14 §9).** ``import nikodym.explain.explainers`` **no** importa
``shap``/``matplotlib``/``sklearn``/``pandas``/``numpy``: todo lo pesado se importa perezosamente
dentro de los métodos. Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Sequence
from typing import Any, Literal, Protocol, TypeAlias, runtime_checkable

from nikodym.core.exceptions import MissingDependencyError
from nikodym.explain.config import ContributionSpace, TreePerturbation
from nikodym.explain.exceptions import (
    ExplainConfigError,
    ExplainDataError,
    ExplainExplainerError,
)

# Clase de explicador resuelta por backend (SDD-14 §4, D-EXP-1).
ExplainerKind: TypeAlias = Literal["analytic_linear", "tree", "linear", "kernel"]
ModelKind: TypeAlias = Literal["scorecard", "ml"]

# Backends cuyo margen nativo NO es log-odds aditivo exacto (RF vota probabilidad; SVM usa Platt).
_NON_LOGODDS_MARGIN_BACKENDS: frozenset[str] = frozenset({"random_forest", "svm"})
# Clase positiva explicada siempre (PD, clase 1; SDD-14 §4, D-EXP-5).
_POSITIVE_CLASS: int = 1
_EXPLAIN_EXTRA_MESSAGE = "instale nikodym[explain]"

__all__ = [
    "AnalyticLinearExplainer",
    "ContributionExplainer",
    "ExplainerKind",
    "KernelShapExplainer",
    "LinearShapExplainer",
    "ModelKind",
    "TreeShapExplainer",
    "resolve_explainer",
    "resolve_explainer_kind",
]


@runtime_checkable
class ContributionExplainer(Protocol):
    """Contrato común de atribución aditiva por feature (SDD-14 §4).

    Un explicador expone su clase (:attr:`kind`), si es exacto (:attr:`is_exact`) y si necesita un
    *background* (:attr:`needs_background`), y calcula el valor base ``φ₀`` (:meth:`base_value`), la
    matriz de contribuciones ``φ_j`` (:meth:`contributions`) y la versión de ``shap`` que usó
    (:meth:`shap_version`, ``None`` para el analítico).
    """

    kind: ExplainerKind
    is_exact: bool
    needs_background: bool

    def base_value(self) -> float:
        """Devuelve ``φ₀`` en la unidad de contribución (log-odds por default)."""
        ...

    def contributions(self, X: Any) -> Any:  # noqa: N803
        """Devuelve la matriz ``(n_obs, n_features)`` de contribuciones ``φ_j``."""
        ...

    def shap_version(self) -> str | None:
        """Devuelve la versión de ``shap`` usada, o ``None`` para el explicador analítico."""
        ...


class AnalyticLinearExplainer:
    """Explicador **exacto** del scorecard logístico sin ``shap`` (SDD-14 §3, D-EXP-1).

    Descompone `η_i = intercepto + Σ_j β_j·WoE_ij` en `φ_j(x_i) = β_j·(WoE_ij - baseline_j)` con
    `φ₀ = intercepto + Σ_j β_j·baseline_j`, de modo que `φ₀ + Σ_j φ_j = η_i`. Es álgebra cerrada,
    determinista y sin dependencia de la librería ``shap``.
    """

    kind: ExplainerKind = "analytic_linear"
    is_exact: bool = True
    needs_background: bool = False

    def __init__(
        self,
        *,
        coefficients: Sequence[float],
        intercept: float,
        baseline: Sequence[float],
        feature_names: Sequence[str],
        contribution_space: ContributionSpace = "log_odds",
    ) -> None:
        """Valida y almacena ``β``, el intercepto, el baseline y los nombres de feature."""
        beta = tuple(float(value) for value in coefficients)
        base = tuple(float(value) for value in baseline)
        names = tuple(str(name) for name in feature_names)
        if not len(beta) == len(base) == len(names):
            raise ExplainConfigError(
                "coefficients, baseline y feature_names deben tener la misma longitud "
                f"(β={len(beta)}, baseline={len(base)}, features={len(names)})."
            )
        if len(names) == 0:
            raise ExplainConfigError("el explicador analítico requiere al menos una feature.")
        if len(set(names)) != len(names):
            raise ExplainConfigError("feature_names no puede repetir columnas.")
        intercepto = float(intercept)
        for value in (*beta, *base, intercepto):
            if not math.isfinite(value):
                raise ExplainDataError(
                    "coefficients, baseline e intercept deben ser finitos (ni NaN ni inf)."
                )
        self._beta = beta
        self._baseline = base
        self._feature_names = names
        self._intercept = intercepto
        self.contribution_space_: ContributionSpace = contribution_space
        self.exact_additivity_: bool = True
        self.caveat_: str | None = None

    @property
    def feature_names_in_(self) -> tuple[str, ...]:
        """Nombres de feature en el orden de la descomposición."""
        return self._feature_names

    def base_value(self) -> float:
        """Devuelve ``φ₀ = intercepto + Σ_j β_j·baseline_j`` (exacto, log-odds)."""
        phi0 = self._intercept + math.fsum(
            beta * base for beta, base in zip(self._beta, self._baseline, strict=True)
        )
        return _require_finite_scalar(phi0)

    def contributions(self, X: Any) -> Any:  # noqa: N803
        """Devuelve ``φ_j(x_i) = β_j·(WoE_ij - baseline_j)`` como matriz ``(n_obs, n_features)``."""
        np = _import_numpy()
        matrix = self._as_matrix(X, np)
        beta = np.asarray(self._beta, dtype="float64")
        baseline = np.asarray(self._baseline, dtype="float64")
        phi = (matrix - baseline) * beta
        return _finalize_matrix(phi, np)

    def shap_version(self) -> str | None:
        """Devuelve ``None``: la descomposición analítica no usa ``shap``."""
        return None

    def _as_matrix(self, X: Any, np: Any) -> Any:  # noqa: N803
        """Alinea ``X`` (DataFrame o ndarray) a las columnas de feature y valida su finitud."""
        if hasattr(X, "columns"):
            missing = [name for name in self._feature_names if name not in X.columns]
            if missing:
                faltantes = ", ".join(f"'{name}'" for name in missing)
                raise ExplainDataError(
                    f"faltan features WoE para la explicación analítica: {faltantes}."
                )
            matrix = np.asarray(X.loc[:, list(self._feature_names)].to_numpy(), dtype="float64")
        else:
            matrix = np.asarray(X, dtype="float64")
            if matrix.ndim != 2 or matrix.shape[1] != len(self._feature_names):
                raise ExplainDataError(
                    "la matriz WoE debe tener forma (n_obs, "
                    f"{len(self._feature_names)}); forma observada={matrix.shape}."
                )
        if not bool(np.isfinite(matrix).all()):
            raise ExplainDataError("las features WoE contienen valores no finitos (NaN/inf).")
        return matrix


class _ShapExplainer:
    """Base perezosa de los envoltorios SHAP: selección de clase y normalización (SDD-14 §7).

    Almacena el explainer nativo de ``shap`` ya construido por :func:`resolve_explainer` y expone el
    contrato común: :meth:`base_value` lee ``expected_value`` (clase positiva),
    :meth:`contributions` llama a ``shap_values`` y normaliza la salida a una matriz finita, y
    :meth:`shap_version` reporta la versión pineada.
    """

    kind: ExplainerKind
    is_exact: bool

    def __init__(
        self,
        native: Any,
        *,
        shap_version: str | None,
        needs_background: bool,
        contribution_space: ContributionSpace,
        exact_additivity: bool,
        caveat: str | None,
        shap_values_kwargs: dict[str, Any] | None = None,
        positive_class: int = _POSITIVE_CLASS,
    ) -> None:
        """Almacena el explainer nativo y la metadata de espacio/determinismo del backend."""
        self._native = native
        self._shap_version = shap_version
        self.needs_background = needs_background
        self.contribution_space_: ContributionSpace = contribution_space
        self.exact_additivity_ = exact_additivity
        self.caveat_ = caveat
        self._shap_values_kwargs = dict(shap_values_kwargs or {})
        self._positive_class = positive_class

    def base_value(self) -> float:
        """Devuelve ``φ₀`` leyendo ``expected_value`` del explainer nativo (clase positiva)."""
        np = _import_numpy()
        base = _select_class_scalar(self._native.expected_value, self._positive_class, np)
        return _require_finite_scalar(base)

    def contributions(self, X: Any) -> Any:  # noqa: N803
        """Calcula ``φ`` con ``shap_values`` y normaliza a matriz ``(n_obs, n_features)`` finita."""
        np = _import_numpy()
        raw = self._native.shap_values(X, **self._shap_values_kwargs)
        selected = _select_class_matrix(raw, self._positive_class, np)
        return _finalize_matrix(selected, np)

    def shap_version(self) -> str | None:
        """Devuelve la versión de ``shap`` con la que se pinearon los golden."""
        return self._shap_version


class TreeShapExplainer(_ShapExplainer):
    """Envoltorio de ``shap.TreeExplainer`` (GBDT/RF): exacto y sin muestreo (SDD-14 §3)."""

    kind: ExplainerKind = "tree"
    is_exact: bool = True


class LinearShapExplainer(_ShapExplainer):
    """Envoltorio de ``shap.LinearExplainer`` (modelos lineales): exacto (SDD-14 §3)."""

    kind: ExplainerKind = "linear"
    is_exact: bool = True


class KernelShapExplainer(_ShapExplainer):
    """Envoltorio de ``shap.KernelExplainer`` (fallback model-agnóstico): muestral (SDD-14 §3)."""

    kind: ExplainerKind = "kernel"
    is_exact: bool = False


def resolve_explainer_kind(
    *,
    backend: str | None,
    model_kind: ModelKind,
    forced: ExplainerKind | Literal["auto"] | None,
    supports_tree: bool,
    is_linear_model: bool = False,
) -> ExplainerKind:
    """Resuelve la clase de explainer por backend (D-EXP-1) sin importar ``shap`` (SDD-14 §7).

    Mapea (``backend``, ``forced``) a la clase concreta: el scorecard siempre es analítico; para el
    ML, ``forced='auto'``/``None`` elige Tree si ``supports_tree`` (GBDT/RF), Linear si el modelo es
    lineal (``is_linear_model``, p. ej. SVM de kernel lineal) y Kernel como fallback (SVM ``rbf``).
    Un ``forced`` incompatible con el backend levanta :class:`ExplainConfigError`.
    """
    normalized = None if forced in (None, "auto") else forced
    if model_kind == "scorecard":
        if normalized not in (None, "analytic_linear"):
            raise ExplainConfigError(
                f"el scorecard se explica de forma analítica; '{normalized}' es incompatible."
            )
        return "analytic_linear"
    if normalized == "analytic_linear":
        raise ExplainConfigError(
            "'analytic_linear' es exclusivo del scorecard; el challenger ML usa tree/linear/kernel."
        )
    if normalized == "tree":
        if not supports_tree:
            raise ExplainConfigError(
                f"TreeExplainer exige un backend de árboles; backend='{backend}' no lo es."
            )
        return "tree"
    if normalized == "linear":
        if not is_linear_model:
            raise ExplainConfigError(
                f"LinearExplainer exige un modelo lineal; backend='{backend}' no lo es."
            )
        return "linear"
    if normalized == "kernel":
        return "kernel"
    if supports_tree:
        return "tree"
    if is_linear_model:
        return "linear"
    return "kernel"


def resolve_explainer(
    *,
    backend: str | None,
    model_kind: ModelKind,
    forced: ExplainerKind | Literal["auto"] | None,
    supports_tree: bool,
    is_linear_model: bool = False,
    model: Any = None,
    predict_fn: Any = None,
    background: Any = None,
    feature_perturbation: TreePerturbation = "tree_path_dependent",
    coefficients: Sequence[float] | None = None,
    intercept: float = 0.0,
    baseline: Sequence[float] | None = None,
    feature_names: Sequence[str] | None = None,
    contribution_space: ContributionSpace = "log_odds",
    nsamples: int | Literal["auto"] = "auto",
) -> ContributionExplainer:
    """Construye el explicador que corresponde al backend (D-EXP-1, SDD-14 §7).

    Para el scorecard retorna un :class:`AnalyticLinearExplainer` **sin** importar ``shap``. Para el
    challenger ML importa ``shap`` de forma perezosa (levantando
    :class:`~nikodym.core.exceptions.MissingDependencyError` con el extra ``[explain]`` si falta) y
    envuelve el explainer nativo correspondiente. La *firma* del SDD §4 (``backend``/``model_kind``/
    ``forced``/``supports_tree``) es la de **selección**; los argumentos de construcción restantes
    (modelo, background, coeficientes) los aporta el motor (B14.3).

    Raises
    ------
    ExplainConfigError
        Si ``forced`` es incompatible con el backend, o faltan los insumos del scorecard analítico.
    MissingDependencyError
        Si se construye un explainer SHAP sin el extra ``[explain]`` instalado.
    """
    kind = resolve_explainer_kind(
        backend=backend,
        model_kind=model_kind,
        forced=forced,
        supports_tree=supports_tree,
        is_linear_model=is_linear_model,
    )
    if kind == "analytic_linear":
        if coefficients is None or baseline is None or feature_names is None:
            raise ExplainConfigError(
                "el explicador analítico del scorecard requiere coefficients, baseline y "
                "feature_names."
            )
        return AnalyticLinearExplainer(
            coefficients=coefficients,
            intercept=intercept,
            baseline=baseline,
            feature_names=feature_names,
            contribution_space="log_odds",
        )

    shap = _import_shap()
    version = _shap_version(shap)
    space, caveat = _effective_space(contribution_space, backend)
    if kind == "tree":
        needs_background = feature_perturbation == "interventional"
        native = shap.TreeExplainer(
            model,
            data=background if needs_background else None,
            feature_perturbation=feature_perturbation,
        )
        return TreeShapExplainer(
            native,
            shap_version=version,
            needs_background=needs_background,
            contribution_space=space,
            exact_additivity=True,
            caveat=caveat,
        )
    if kind == "linear":
        native = shap.LinearExplainer(model, background)
        return LinearShapExplainer(
            native,
            shap_version=version,
            needs_background=True,
            contribution_space=space,
            exact_additivity=True,
            caveat=caveat,
        )
    native = shap.KernelExplainer(predict_fn, background)
    return KernelShapExplainer(
        native,
        shap_version=version,
        needs_background=True,
        contribution_space=space,
        exact_additivity=False,
        caveat=caveat,
        shap_values_kwargs={"nsamples": nsamples},
    )


def _effective_space(
    requested: ContributionSpace, backend: str | None
) -> tuple[ContributionSpace, str | None]:
    """Resuelve el espacio de contribución efectivo y el caveat según el backend (nitpick A15(1)).

    El *additivity check* en log-odds solo es exacto con margen log-odds real. Random Forest
    (voto→probabilidad) y SVM (Platt) degradan a ``"probability"`` con caveat explícito; la unidad
    ``"probability"`` pedida directamente tampoco es perfectamente aditiva.
    """
    if requested == "log_odds":
        if backend in _NON_LOGODDS_MARGIN_BACKENDS:
            return "probability", (
                f"el backend '{backend}' no expone un margen log-odds aditivo exacto; SHAP explica "
                "la probabilidad y la aditividad en log-odds no está garantizada."
            )
        return "log_odds", None
    return "probability", (
        "la unidad 'probability' no es perfectamente aditiva; el additivity check se relaja a la "
        "escala de probabilidad."
    )


def _import_numpy() -> Any:
    """Importa ``numpy`` localmente y traduce su ausencia a un mensaje accionable."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError("instale nikodym[ml]") from exc


def _import_shap() -> Any:
    """Importa ``shap`` de forma perezosa; si falta el extra ``[explain]`` lo nombra explícito."""
    try:
        return importlib.import_module("shap")
    except ImportError as exc:
        raise MissingDependencyError(_EXPLAIN_EXTRA_MESSAGE) from exc


def _shap_version(shap: Any) -> str | None:
    """Lee la versión de ``shap`` para pinear los golden; ``None`` si no la expone."""
    version = getattr(shap, "__version__", None)
    return None if version is None else str(version)


def _select_class_scalar(expected: Any, positive_class: int, np: Any) -> float:
    """Selecciona el ``expected_value`` de la clase positiva (escalar o vector binario)."""
    arr = np.asarray(expected, dtype="float64")
    if arr.ndim == 0:
        return float(arr)
    if arr.ndim == 1:
        if positive_class >= arr.shape[0]:
            raise ExplainExplainerError(
                f"expected_value no contiene la clase positiva {positive_class}; forma={arr.shape}."
            )
        return float(arr[positive_class])
    raise ExplainExplainerError(f"expected_value con forma inesperada: {arr.shape}.")


def _select_class_matrix(raw: Any, positive_class: int, np: Any) -> Any:
    """Selecciona la matriz SHAP de la clase positiva de las formas que devuelve ``shap``."""
    if isinstance(raw, (list, tuple)):
        if positive_class >= len(raw):
            raise ExplainExplainerError(
                f"shap_values no contiene la clase positiva {positive_class} (n={len(raw)})."
            )
        selected = np.asarray(raw[positive_class], dtype="float64")
    else:
        selected = np.asarray(raw, dtype="float64")
        if selected.ndim == 3:
            selected = selected[:, :, positive_class]
    if selected.ndim != 2:
        raise ExplainExplainerError(
            f"la matriz de contribuciones SHAP debe ser 2D; ndim observado={selected.ndim}."
        )
    return selected


def _finalize_matrix(matrix: Any, np: Any) -> Any:
    """Valida finitud y normaliza ``-0.0`` a ``0.0`` en la matriz de contribuciones (§9)."""
    arr = np.asarray(matrix, dtype="float64")
    if not bool(np.isfinite(arr).all()):
        raise ExplainExplainerError("las contribuciones contienen valores no finitos (NaN/inf).")
    result = np.array(arr, dtype="float64", copy=True)
    result[result == 0.0] = 0.0
    return result


def _require_finite_scalar(value: float) -> float:
    """Exige un escalar finito y publica ``-0.0`` como ``0.0`` (valor base ``φ₀``)."""
    if not math.isfinite(value):
        raise ExplainExplainerError("el valor base φ₀ no es finito (NaN/inf).")
    return 0.0 if value == 0.0 else value
