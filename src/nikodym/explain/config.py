"""Config declarativo de la capa ``explain`` (SDD-14 §5).

:class:`ExplainConfig` es la sección ``explain`` de :class:`~nikodym.core.config.NikodymConfig`: la
**explicabilidad unificada** que descompone la predicción de riesgo en contribuciones por atributo
para el scorecard logístico (analítico, ``β·WoE`` exacto) y para el challenger ML de ``ml`` (vía
SHAP), y produce reason codes y una comparativa scorecard-vs-ML. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description``, sus cotas (``ge``/``le``/``Literal``) y metadatos ``ui_*`` para
que la UI (SDD-23) sea un editor del config.

**Herencia desde ``ml`` (no duplicar).** ``ExplainConfig`` **no** declara ``backend`` ni
``feature_source``: los **lee de** :class:`~nikodym.core.config.NikodymConfig.ml` en runtime (para
resolver el explainer y explicar las mismas features WoE que consumió el challenger). Si
``targets ∈ {ml, both}`` y ``ml is None`` ⇒ :class:`~nikodym.explain.exceptions.ExplainConfigError`
(no hay challenger que explicar); esa comprobación —como las que dependen del backend, de los datos
o del audit sink— es de **runtime** y vive en el motor/step (B14.2+), no en el schema.

La sección es **computacional** (``explain`` ∉ ``INFRA_SECTIONS``): cambiar el explainer, el tamaño
del background, el N de reason codes o la unidad de contribución **mueve el ``config_hash``**.
Al cablear B14.1 se movió ``GOLDEN_DEFAULT_CONFIG_HASH`` (mismo precedente aditivo que
``ml``/``tuning``/``validation``).

Frontera B14.1: aquí solo viven el schema y la única validación determinable **sin datos ni
backend**: un explainer Kernel **forzado** con determinismo byte-a-byte exige single-thread (§5).
Las validaciones que necesitan ``ml.backend`` (``tree``/``linear`` incompatibles), los datos
(``top_n`` > nº features) o el audit sink (fuga de referencia por ``holdout``/``oot``) se difieren a
runtime. Núcleo liviano (principio 9): ``import nikodym.explain.config`` **no** arrastra
``shap``/``matplotlib``/``numba``/``sklearn``/``pandas``/``numpy``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.explain.exceptions import ExplainConfigError

ExplainTargets = Literal["both", "ml", "scorecard"]
MLExplainerChoice = Literal["auto", "tree", "linear", "kernel"]
TreePerturbation = Literal["tree_path_dependent", "interventional"]
ContributionSpace = Literal["log_odds", "probability"]
ScorecardBaseline = Literal["population_mean", "neutral_zero"]
LocalScope = Literal["sample", "partition", "all", "none"]

__all__ = [
    "ContributionSpace",
    "ExplainConfig",
    "ExplainOutputConfig",
    "ExplainTargets",
    "LocalScope",
    "LocalScopeConfig",
    "MLExplainerChoice",
    "MLExplainerConfig",
    "ReasonCodesConfig",
    "ScorecardBaseline",
    "ScorecardExplainConfig",
    "TreePerturbation",
]


class MLExplainerConfig(NikodymBaseConfig):
    """Selección y parametrización del explainer SHAP del challenger ML (SDD-14 §5, D-EXP-1)."""

    ml_explainer: MLExplainerChoice = Field(
        default="auto",
        title="Explainer del challenger",
        description=(
            "'auto' resuelve por backend (Tree para GBDT/RF, Linear para lineales, Kernel "
            "fallback); forzable a 'tree'/'linear'/'kernel' con validación de compatibilidad "
            "en runtime."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Explainer", "ui_order": 1},
    )
    feature_perturbation: TreePerturbation = Field(
        default="tree_path_dependent",
        title="Perturbación de features (Tree)",
        description=(
            "'tree_path_dependent' es exacto sin background y determinista; 'interventional' tiene "
            "semántica causal pero requiere background."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Explainer", "ui_order": 2},
    )
    background_size: int = Field(
        default=100,
        ge=1,
        le=100_000,
        title="Tamaño del background",
        description="Observaciones muestreadas (seeded) para el background (solo Kernel/interv.).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Explainer", "ui_order": 3},
    )
    background_partition: str = Field(
        default="desarrollo",
        title="Partición del background",
        description="Partición de la que se toma el background; nunca holdout/oot como referencia.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Explainer", "ui_order": 4},
    )
    check_additivity: bool = Field(
        default=True,
        title="Gate de aditividad",
        description="Verifica φ0 + Σφ ≈ f(x) (log-odds); un fallo levanta ExplainExplainerError.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Explainer", "ui_order": 5},
    )
    nsamples: int | Literal["auto"] = Field(
        default="auto",
        title="Nº de muestras (Kernel)",
        description="Muestras de Kernel SHAP; 'auto' delega en la heurística de la librería shap.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Explainer", "ui_order": 6},
    )


class ReasonCodesConfig(NikodymBaseConfig):
    """Política de reason codes (top-N drivers de la PD con dirección y magnitud, SDD-14 §5)."""

    top_n: int = Field(
        default=5,
        ge=1,
        le=50,
        title="N de reason codes",
        description=(
            "Nº de drivers principales por observación; default 5 (referencia ECOA/FCRA 'key "
            "factors', NO norma CMF — FALTA-DATO-EXP-1)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Reason codes", "ui_order": 1},
    )
    include_protective: bool = Field(
        default=False,
        title="Incluir protectores",
        description="Si True, añade los drivers que bajan la PD; por default solo los adversos.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Reason codes", "ui_order": 2},
    )
    min_abs_contribution: float = Field(
        default=0.0,
        ge=0.0,
        title="Contribución mínima |φ|",
        description="Magnitud mínima |φ| para que un driver se liste como reason code.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Reason codes", "ui_order": 3},
    )
    adverse_direction: Literal["increases_pd"] = Field(
        default="increases_pd",
        title="Dirección adversa",
        description="La dirección que 'empeora' el riesgo es siempre subir la PD (clase positiva).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Reason codes", "ui_order": 4},
    )


class LocalScopeConfig(NikodymBaseConfig):
    """Scope de las explicaciones locales que se materializan y publican (SDD-14 §5, D-EXP-6)."""

    strategy: LocalScope = Field(
        default="sample",
        title="Estrategia de scope",
        description=(
            "'sample' (muestra representativa), 'partition' (una partición completa), 'all' (toda "
            "la base, con caveat de costo) o 'none' (solo el explainer on-demand)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Scope local", "ui_order": 1},
    )
    sample_size: int = Field(
        default=200,
        ge=1,
        le=1_000_000,
        title="Tamaño de la muestra local",
        description="Nº de observaciones a explicar cuando strategy='sample' (muestreo seeded).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Scope local", "ui_order": 2},
    )
    partition: str = Field(
        default="holdout",
        title="Partición del scope local",
        description="Partición de la que se toma la muestra/subconjunto local a explicar.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Scope local", "ui_order": 3},
    )
    top_by_pd: bool = Field(
        default=False,
        title="Priorizar PD altas",
        description="Si True, la muestra prioriza las observaciones de mayor PD predicha.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Scope local", "ui_order": 4},
    )


class ScorecardExplainConfig(NikodymBaseConfig):
    """Baseline de la mitad scorecard: contribución ``β·(WoE - baseline)`` (SDD-14 §5, D-EXP-7)."""

    baseline: ScorecardBaseline = Field(
        default="population_mean",
        title="Baseline del scorecard",
        description="'population_mean' (E[WoE], ≡ LinearExplainer) o 'neutral_zero' (WoE=0).",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Scorecard", "ui_order": 1},
    )
    baseline_partition: str = Field(
        default="desarrollo",
        title="Partición del baseline",
        description="Partición sobre la que se calcula E[WoE]; nunca holdout/oot como referencia.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Scorecard", "ui_order": 2},
    )


class ExplainOutputConfig(NikodymBaseConfig):
    """Artefactos publicados por ``explain`` (contribuciones locales, top-K, figuras, SDD-14 §5)."""

    publish_local: bool = Field(
        default=True,
        title="Publicar explicaciones locales",
        description="Publica shap_local/reason_codes; si False, solo globales y comparativa.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 1},
    )
    top_k_global: int = Field(
        default=30,
        ge=1,
        title="Top-k global",
        description="Nº de features de mayor importancia global (media |SHAP|) a publicar.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Salida", "ui_order": 2},
    )
    top_k_comparison: int = Field(
        default=15,
        ge=1,
        title="Top-k comparativa",
        description="Nº de drivers top-K a contrastar en la comparativa scorecard-vs-ML.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Salida", "ui_order": 3},
    )
    emit_figures: bool = Field(
        default=True,
        title="Emitir figuras SHAP",
        description="Si True, añade SHAP summary/dependence al card (matplotlib, import perezoso).",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 4},
    )


class ExplainConfig(NikodymBaseConfig):
    """Sección ``explain`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-14 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección explain",
        description="== @register('standard', domain='explain') (SDD-14 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema explain",
        description="Versión local del schema de explicabilidad para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    targets: ExplainTargets = Field(
        default="both",
        title="Qué explicar",
        description=(
            "'both' explica scorecard y ML (degrada a ML si falta el scorecard); 'ml' solo el "
            "challenger; 'scorecard' solo el campeón (sin necesidad del extra [explain])."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 2},
    )
    explainer: MLExplainerConfig = Field(
        default_factory=MLExplainerConfig,
        title="Explainer ML",
        description="Selección y parametrización del explainer SHAP del challenger.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Explainer", "ui_order": 1},
    )
    contribution_space: ContributionSpace = Field(
        default="log_odds",
        title="Unidad de contribución",
        description=(
            "'log_odds' (aditiva, misma unidad que el scorecard, habilita additivity check) o "
            "'probability' (∆PD directo, no perfectamente aditiva)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 3},
    )
    reason_codes: ReasonCodesConfig = Field(
        default_factory=ReasonCodesConfig,
        title="Reason codes",
        description="Política de reason codes (top-N drivers con dirección y magnitud).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Reason codes", "ui_order": 1},
    )
    local_scope: LocalScopeConfig = Field(
        default_factory=LocalScopeConfig,
        title="Scope local",
        description="Qué observaciones se explican y publican (muestra/partición/todo/ninguno).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Scope local", "ui_order": 1},
    )
    scorecard: ScorecardExplainConfig = Field(
        default_factory=ScorecardExplainConfig,
        title="Scorecard",
        description="Baseline analítico de la mitad scorecard (β·WoE exacto).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Scorecard", "ui_order": 1},
    )
    output: ExplainOutputConfig = Field(
        default_factory=ExplainOutputConfig,
        title="Salida",
        description="Artefactos publicados (contribuciones locales, top-K, figuras).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Salida", "ui_order": 1},
    )
    deterministic: bool = Field(
        default=True,
        title="Determinismo byte-a-byte",
        description=(
            "True busca byte-reproducibilidad (golden values); Tree/Linear son exactos siempre, "
            "solo el fallback Kernel exige single-thread."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Reproducibilidad", "ui_order": 1},
    )
    n_threads: int = Field(
        default=1,
        ge=1,
        le=256,
        title="Nº de hilos",
        description=(
            "Hilos del explainer; >1 con deterministic=True solo se restringe si el explainer "
            "forzado es Kernel (muestral). Tree/Linear son deterministas aun multihilo."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Reproducibilidad",
            "ui_order": 2,
        },
    )
    target_column: str = Field(
        default="target",
        title="Columna target binario",
        description="Columna con la etiqueta binaria (0/1) que contextualiza la explicación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    partition_column: str = Field(
        default="partition",
        title="Columna partición",
        description="Columna que identifica desarrollo/holdout/oot.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    pd_hat_column: str = Field(
        default="pd_hat",
        title="Columna PD",
        description="Nombre de la columna de PD predicha (clase 1) que acompaña a la explicación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )

    @model_validator(mode="after")
    def _valida_explain(self) -> Self:
        """Valida el único invariante determinable sin datos ni backend (SDD-14 §5).

        Con determinismo byte-a-byte y un explainer **Kernel forzado** (muestral), ``n_threads>1``
        rompe la reproducibilidad ⇒ :class:`~nikodym.explain.exceptions.ExplainConfigError`
        (D-EXP-det, recomendación de fallar). Con ``ml_explainer='auto'/'tree'/'linear'`` el
        explainer efectivo depende del ``backend`` de ``ml`` y Tree/Linear son exactos aun
        multihilo: esas restricciones se difieren a runtime (motor/step, B14.3+), igual que la
        compatibilidad explainer↔backend, el ``top_n`` > nº features y la fuga de referencia por
        ``holdout``/``oot``.
        """
        if self.deterministic and self.n_threads > 1 and self.explainer.ml_explainer == "kernel":
            raise ExplainConfigError(
                "deterministic=True con ml_explainer='kernel' exige n_threads=1 (Kernel SHAP es "
                f"muestral y multihilo no es byte-reproducible; n_threads={self.n_threads}). Use "
                "deterministic=False, n_threads=1 o un explainer exacto (tree/linear/auto)."
            )
        return self
