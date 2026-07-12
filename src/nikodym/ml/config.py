"""Config declarativo de la capa ``ml`` (SDD-12 §5).

:class:`MLConfig` es la sección ``ml`` de :class:`~nikodym.core.config.NikodymConfig`: el
**challenger de machine learning** (SVM, Random Forest, XGBoost, LightGBM o CatBoost, seleccionable
por ``backend``) que reta al scorecard logístico campeón sobre el mismo pipeline de datos. Toda
clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y
``frozen=True``); cada campo declara ``title``/``description``, sus cotas
(``ge``/``le``/``Literal``) y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del config.

Los **hiperparámetros son estructuras Pydantic tipadas por backend** (``SvmParams`` …
``CatBoostParams``), **nunca** ``dict[str, Any]`` ni expresiones ejecutables: un
``model_validator`` coacciona la sección
``hyperparameters`` al sub-schema del ``backend`` seleccionado (factory por backend análogo a la
unión anidada de ``data``). Así el config no admite hiperparámetros de un backend distinto al
elegido.

La sección es **computacional, no infraestructura** (``ml`` ∉ ``INFRA_SECTIONS``): cambiar el
backend, los hiperparámetros, la fuente de features o la monotonía **cambia el ``config_hash``
global**. Al cablear B12.1 se mueve ``GOLDEN_DEFAULT_CONFIG_HASH`` (mismo precedente que
``validation``/``provisioning_ifrs9``).

Frontera B12.1: aquí solo viven el schema y sus validaciones determinables sin datos ni backends
instalados. La *presencia* de la fuente de features en el DAG (``selection`` aguas arriba para
``feature_source='selection_woe'``) es un contrato de runtime que valida CT-1 antes de ejecutar
(§6/§8), de modo que ``MLConfig()`` siga construyendo sin argumentos.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Final, Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.ml.exceptions import MLConfigError, MLMonotonicError

MLBackendName = Literal["svm", "random_forest", "xgboost", "lightgbm", "catboost"]
FeatureSource = Literal["binning_woe", "selection_woe", "data_raw"]
MonotonicMode = Literal["off", "from_binning", "explicit"]
ClassWeight = Literal["none", "balanced"]
ComparisonMetric = Literal["auc", "gini", "ks", "psi"]

__all__ = [
    "CatBoostParams",
    "ClassWeight",
    "ComparisonMetric",
    "FeatureSource",
    "LightGBMParams",
    "MLBackendName",
    "MLComparisonConfig",
    "MLConfig",
    "MLOutputConfig",
    "MLTrainConfig",
    "MonotonicConfig",
    "MonotonicMode",
    "RandomForestParams",
    "SvmParams",
    "XGBoostParams",
]

# Backends GBDT: soportan early stopping y monotonic constraints, no son byte-deterministas
# multihilo (ESPECIFICACIONES.md:L77 → default single-thread).
_GBDT_BACKENDS: Final[frozenset[str]] = frozenset({"xgboost", "lightgbm", "catboost"})
# Backends sin soporte de monotonic constraints (ignoran o fallan según ``on_unsupported``).
_MONOTONE_UNSUPPORTED: Final[frozenset[str]] = frozenset({"svm", "random_forest"})
# Backends que no toleran ``NaN`` sin política de imputación (FALTA-DATO-ML-1 con ``data_raw``).
_NAN_INTOLERANT: Final[frozenset[str]] = frozenset({"svm", "random_forest"})


# ── hiperparámetros tipados por backend (sin ``seed``/``n_threads``: se gestionan aparte) ──
class SvmParams(NikodymBaseConfig):
    """Hiperparámetros del backend ``svm`` (scikit-learn ``SVC(probability=True)``)."""

    C: float = Field(
        default=1.0,
        gt=0.0,
        title="Parámetro de regularización C",
        description="Inverso de la fuerza de regularización; C mayor penaliza menos el error.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "SVM", "ui_order": 1},
    )
    kernel: Literal["rbf", "linear"] = Field(
        default="rbf",
        title="Kernel",
        description="Función núcleo del SVM: 'rbf' (radial) o 'linear'.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "SVM", "ui_order": 2},
    )
    gamma: Literal["scale", "auto"] = Field(
        default="scale",
        title="Coeficiente gamma",
        description="Coeficiente del kernel: 'scale' (default sklearn) o 'auto'.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "SVM", "ui_order": 3},
    )


class RandomForestParams(NikodymBaseConfig):
    """Hiperparámetros del backend ``random_forest`` (scikit-learn ``RandomForestClassifier``)."""

    n_estimators: int = Field(
        default=300,
        ge=1,
        le=5000,
        title="Nº de árboles",
        description="Cantidad de árboles del bosque; más árboles reducen varianza a mayor costo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "RandomForest", "ui_order": 1},
    )
    max_depth: int | None = Field(
        default=None,
        ge=1,
        title="Profundidad máxima",
        description="Profundidad máxima por árbol; None crece hasta hojas puras.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "RandomForest", "ui_order": 2},
    )
    min_samples_leaf: int = Field(
        default=50,
        ge=1,
        title="Mínimo de muestras por hoja",
        description="Nº mínimo de observaciones en una hoja; mayor regulariza el árbol.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "RandomForest", "ui_order": 3},
    )
    max_features: Literal["sqrt", "log2"] | float = Field(
        default="sqrt",
        title="Features por split",
        description="Nº de features candidatas por split: 'sqrt', 'log2' o una fracción en (0, 1].",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "RandomForest", "ui_order": 4},
    )


class XGBoostParams(NikodymBaseConfig):
    """Hiperparámetros del backend ``xgboost`` (GBDT con early stopping y monotonía)."""

    n_estimators: int = Field(
        default=500,
        ge=1,
        le=10000,
        title="Nº de rondas de boosting",
        description="Número máximo de árboles; el early stopping recorta las rondas efectivas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "XGBoost", "ui_order": 1},
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        le=12,
        title="Profundidad máxima",
        description="Profundidad por árbol; árboles poco profundos evitan overfit del challenger.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "XGBoost", "ui_order": 2},
    )
    learning_rate: float = Field(
        default=0.05,
        gt=0.0,
        le=1.0,
        title="Tasa de aprendizaje",
        description="Contracción por ronda; menor es más conservador y exige más rondas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "XGBoost", "ui_order": 3},
    )
    subsample: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        title="Submuestreo de filas",
        description="Fracción de filas muestreadas por ronda (regularización estocástica).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "XGBoost", "ui_order": 4},
    )
    colsample_bytree: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        title="Submuestreo de columnas por árbol",
        description="Fracción de columnas muestreadas al construir cada árbol.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "XGBoost", "ui_order": 5},
    )
    reg_lambda: float = Field(
        default=1.0,
        ge=0.0,
        title="Regularización L2",
        description="Penalización L2 sobre los pesos de las hojas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "XGBoost", "ui_order": 6},
    )
    min_child_weight: float = Field(
        default=1.0,
        ge=0.0,
        title="Peso mínimo por hoja (hessiano)",
        description="Suma mínima de hessianos por hoja; mayor regulariza los splits.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "XGBoost", "ui_order": 7},
    )


class LightGBMParams(NikodymBaseConfig):
    """Hiperparámetros del backend ``lightgbm`` (GBDT leaf-wise con early stopping y monotonía)."""

    n_estimators: int = Field(
        default=500,
        ge=1,
        le=10000,
        title="Nº de rondas de boosting",
        description="Número máximo de árboles; el early stopping recorta las rondas efectivas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LightGBM", "ui_order": 1},
    )
    num_leaves: int = Field(
        default=31,
        ge=2,
        le=1024,
        title="Nº de hojas",
        description="Máximo de hojas por árbol (crecimiento leaf-wise); mayor aumenta capacidad.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LightGBM", "ui_order": 2},
    )
    learning_rate: float = Field(
        default=0.05,
        gt=0.0,
        le=1.0,
        title="Tasa de aprendizaje",
        description="Contracción por ronda; menor es más conservador y exige más rondas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LightGBM", "ui_order": 3},
    )
    subsample: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        title="Submuestreo de filas",
        description="Fracción de filas muestreadas por ronda (bagging).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LightGBM", "ui_order": 4},
    )
    colsample_bytree: float = Field(
        default=0.8,
        gt=0.0,
        le=1.0,
        title="Submuestreo de columnas por árbol",
        description="Fracción de columnas muestreadas al construir cada árbol.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LightGBM", "ui_order": 5},
    )
    reg_lambda: float = Field(
        default=1.0,
        ge=0.0,
        title="Regularización L2",
        description="Penalización L2 sobre los pesos de las hojas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LightGBM", "ui_order": 6},
    )
    min_child_samples: int = Field(
        default=50,
        ge=1,
        title="Mínimo de muestras por hoja",
        description="Nº mínimo de observaciones en una hoja; mayor regulariza el árbol.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LightGBM", "ui_order": 7},
    )


class CatBoostParams(NikodymBaseConfig):
    """Hiperparámetros del backend ``catboost`` (GBDT con árboles simétricos y monotonía)."""

    iterations: int = Field(
        default=500,
        ge=1,
        le=10000,
        title="Nº de iteraciones",
        description="Número máximo de árboles; el early stopping recorta las iteraciones reales.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "CatBoost", "ui_order": 1},
    )
    depth: int = Field(
        default=4,
        ge=1,
        le=16,
        title="Profundidad de los árboles",
        description="Profundidad de los árboles simétricos (oblivious trees).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "CatBoost", "ui_order": 2},
    )
    learning_rate: float = Field(
        default=0.05,
        gt=0.0,
        le=1.0,
        title="Tasa de aprendizaje",
        description="Contracción por iteración; menor es más conservador y exige más iteraciones.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "CatBoost", "ui_order": 3},
    )
    l2_leaf_reg: float = Field(
        default=3.0,
        ge=0.0,
        title="Regularización L2 de hojas",
        description="Coeficiente de regularización L2 del término de las hojas.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "CatBoost", "ui_order": 4},
    )


# Factory por backend (D-CONV-2 aplica solo a uniones de nivel sección; esta es anidada, SDD-05 §3).
_PARAMS_BY_BACKEND: Final[dict[str, type[NikodymBaseConfig]]] = {
    "svm": SvmParams,
    "random_forest": RandomForestParams,
    "xgboost": XGBoostParams,
    "lightgbm": LightGBMParams,
    "catboost": CatBoostParams,
}
_PARAMS_CLASSES: Final[tuple[type[NikodymBaseConfig], ...]] = tuple(_PARAMS_BY_BACKEND.values())


class MonotonicConfig(NikodymBaseConfig):
    """Restricciones de monotonía del challenger (dirección por variable en el espacio WoE)."""

    mode: MonotonicMode = Field(
        default="from_binning",
        title="Modo de monotonía",
        description=(
            "'from_binning' deriva la dirección de la tendencia del binning (WoE↑⇒PD↓, constraint "
            "-1); 'explicit' usa el mapa declarado; 'off' no aplica constraints."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Monotonía", "ui_order": 1},
    )
    explicit: dict[str, Literal[-1, 0, 1]] = Field(
        default_factory=dict,
        title="Direcciones explícitas por variable",
        description="Mapa feature→dirección (-1/0/1) en espacio WoE; requerido en modo 'explicit'.",
        json_schema_extra={"ui_widget": "table", "ui_group": "Monotonía", "ui_order": 2},
    )
    on_unsupported: Literal["warn", "error"] = Field(
        default="warn",
        title="Backend sin soporte de monotonía",
        description="'warn' ignora la constraint con auditoría; 'error' falla (svm/random_forest).",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Monotonía", "ui_order": 3},
    )


class MLTrainConfig(NikodymBaseConfig):
    """Ajuste, particiones de predicción y early stopping interno del challenger."""

    fit_partition: str = Field(
        default="desarrollo",
        title="Partición de ajuste",
        description="Partición sobre la que se entrena el challenger (misma que el campeón).",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Entrenamiento", "ui_order": 1},
    )
    predict_partitions: tuple[str, ...] = Field(
        default=("desarrollo", "holdout", "oot"),
        title="Particiones a predecir",
        description="Particiones sobre las que se materializa la PD del challenger.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Entrenamiento", "ui_order": 2},
    )
    validation_fraction: float = Field(
        default=0.2,
        ge=0.0,
        lt=1.0,
        title="Fracción de early stopping interno",
        description=(
            "Recorte seeded de desarrollo para detener el entrenamiento; 0.0 desactiva el early "
            "stopping. Holdout/OOT nunca se usan para entrenar."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Entrenamiento", "ui_order": 3},
    )
    early_stopping_rounds: int | None = Field(
        default=50,
        ge=1,
        title="Rondas de early stopping",
        description="Rondas sin mejora antes de detener (GBDT); None desactiva el early stopping.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Entrenamiento", "ui_order": 4},
    )
    class_weight: ClassWeight = Field(
        default="none",
        title="Reponderación de clases",
        description="'none' no repondera; 'balanced' pesa inverso a la frecuencia de clase.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Entrenamiento", "ui_order": 5},
    )
    require_both_classes: bool = Field(
        default=True,
        title="Exigir ambas clases",
        description="Si True, una partición de ajuste con una sola clase levanta MLDataError.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Entrenamiento", "ui_order": 6},
    )


class MLComparisonConfig(NikodymBaseConfig):
    """Comparación cabeza-a-cabeza challenger-vs-campeón (reúso de SDD-11)."""

    metrics: tuple[ComparisonMetric, ...] = Field(
        default=("auc", "gini", "ks", "psi"),
        title="Métricas de comparación",
        description="Métricas de discriminación/estabilidad reúsadas de SDD-11 (no se recalculan).",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Comparación", "ui_order": 1},
    )
    partitions: tuple[str, ...] = Field(
        default=("desarrollo", "holdout", "oot"),
        title="Particiones a comparar",
        description="Particiones sobre las que se reporta la brecha campeón-vs-challenger.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Comparación", "ui_order": 2},
    )
    tie_tolerance: float = Field(
        default=1e-6,
        gt=0.0,
        lt=1e-2,
        title="Tolerancia de empate",
        description="|delta| ≤ tolerancia se reporta como 'tie' entre campeón y challenger.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Comparación", "ui_order": 3},
    )


class MLOutputConfig(NikodymBaseConfig):
    """Artefactos publicados por el challenger (PD calibrada opcional e importancias nativas)."""

    publish_calibrated_pd: bool = Field(
        default=True,
        title="Publicar PD calibrada",
        description="Publica calibrated_pd_frame; solo tiene efecto si calibrate_challenger=True.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 1},
    )
    publish_feature_importances: bool = Field(
        default=True,
        title="Publicar importancias nativas",
        description="Publica las importancias nativas del backend (gain/split), nunca SHAP.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 2},
    )
    top_k_importances: int = Field(
        default=30,
        ge=1,
        title="Top-k de importancias",
        description="Nº de features de mayor importancia nativa a publicar en el card.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Salida", "ui_order": 3},
    )


class MLConfig(NikodymBaseConfig):
    """Sección ``ml`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-12 §5)."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema ml",
        description="Versión local del schema del challenger para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección ml",
        description="== @register('standard', domain='ml') (SDD-12 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    backend: MLBackendName = Field(
        default="xgboost",
        title="Backend del challenger",
        description=(
            "GBDT canónico 'xgboost' por defecto (requiere nikodym[xgboost]); "
            "svm/random_forest corren con el extra base [ml]."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 2},
    )
    feature_source: FeatureSource = Field(
        default="binning_woe",
        title="Fuente de features",
        description=(
            "'binning_woe' por defecto (consistencia de pipeline); 'selection_woe' "
            "apples-to-apples; 'data_raw' diferido."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 3},
    )
    hyperparameters: (
        SvmParams | RandomForestParams | XGBoostParams | LightGBMParams | CatBoostParams | None
    ) = Field(
        default=None,
        title="Hiperparámetros del backend",
        description=(
            "Sub-schema tipado según el backend; None instancia los defaults del backend. Nunca "
            "un dict libre ni una expresión ejecutable."
        ),
        json_schema_extra={"ui_widget": "section", "ui_group": "Hiperparámetros", "ui_order": 1},
    )
    train: MLTrainConfig = Field(
        default_factory=MLTrainConfig,
        title="Entrenamiento",
        description="Ajuste, particiones de predicción y early stopping interno.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Entrenamiento", "ui_order": 1},
    )
    monotonic: MonotonicConfig = Field(
        default_factory=MonotonicConfig,
        title="Monotonía",
        description="Restricciones de monotonía con el riesgo por variable (espacio WoE).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Monotonía", "ui_order": 1},
    )
    comparison: MLComparisonConfig = Field(
        default_factory=MLComparisonConfig,
        title="Comparación",
        description="Comparación cabeza-a-cabeza challenger-vs-campeón (reúso de SDD-11).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Comparación", "ui_order": 1},
    )
    calibrate_challenger: bool = Field(
        default=False,
        title="Calibrar el challenger",
        description=(
            "False por defecto: la comparación de discriminación no lo necesita; True alimenta "
            "validación/report con PD calibrada (reúso de PDCalibrator, SDD-10)."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "General", "ui_order": 4},
    )
    output: MLOutputConfig = Field(
        default_factory=MLOutputConfig,
        title="Salida",
        description="Artefactos publicados (PD calibrada opcional e importancias nativas).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Salida", "ui_order": 1},
    )
    deterministic: bool = Field(
        default=True,
        title="Determinismo byte-a-byte",
        description=(
            "True fuerza single-thread para byte-reproducibilidad (golden values); False habilita "
            "el modo performance multihilo marcado como no byte-reproducible."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Reproducibilidad", "ui_order": 1},
    )
    n_threads: int = Field(
        default=1,
        ge=1,
        le=256,
        title="Nº de hilos",
        description=(
            "Hilos del backend; >1 exige deterministic=False (GBDT multihilo no es determinista)."
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
        description="Columna con la etiqueta binaria (0/1) que consume el challenger.",
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
        title="Columna PD del challenger",
        description="Nombre de la columna de PD predicha por el challenger (clase 1).",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )

    @model_validator(mode="before")
    @classmethod
    def _resuelve_hyperparameters(cls, data: object) -> object:
        """Coacciona ``hyperparameters`` al sub-schema del ``backend`` (factory por backend §5).

        Un ``dict`` se valida contra el modelo tipado del backend seleccionado (rangos Pydantic
        nativos); ``None`` instancia los defaults del backend. Una instancia ya construida pasa tal
        cual y su coherencia con el backend la verifica :meth:`_valida_ml`. Con un ``backend``
        desconocido se deja intacto para que el ``Literal`` del campo levante el error estándar.
        """
        if not isinstance(data, dict):
            return data
        backend = data.get("backend", "xgboost")
        params_cls = _PARAMS_BY_BACKEND.get(backend)
        if params_cls is None:
            return data
        hp = data.get("hyperparameters")
        if isinstance(hp, _PARAMS_CLASSES):
            return data
        resuelto = dict(data)
        resuelto["hyperparameters"] = params_cls() if hp is None else params_cls.model_validate(hp)
        return resuelto

    @model_validator(mode="after")
    def _valida_ml(self) -> Self:
        """Valida coherencia backend↔hiperparámetros, determinismo y monotonía (SDD-12 §5)."""
        esperado = _PARAMS_BY_BACKEND[self.backend]
        if not isinstance(self.hyperparameters, esperado):
            recibido = type(self.hyperparameters).__name__
            raise MLConfigError(
                f"hyperparameters debe ser {esperado.__name__} para backend='{self.backend}', "
                f"pero se recibió {recibido}."
            )
        if self.deterministic and self.n_threads > 1:
            raise MLConfigError(
                "deterministic=True exige n_threads=1 (los GBDT multihilo no son deterministas; "
                f"n_threads={self.n_threads}). Use deterministic=False para el modo performance."
            )
        if self.monotonic.mode == "explicit" and not self.monotonic.explicit:
            raise MLConfigError(
                "monotonic.mode='explicit' exige un mapa 'explicit' no vacío de feature→dirección."
            )
        if (
            self.monotonic.mode != "off"
            and self.backend in _MONOTONE_UNSUPPORTED
            and self.monotonic.on_unsupported == "error"
        ):
            raise MLMonotonicError(
                f"el backend '{self.backend}' no soporta monotonic constraints y "
                f"monotonic.on_unsupported='error' (use 'warn' o backend GBDT)."
            )
        if self.feature_source == "data_raw" and self.backend in _NAN_INTOLERANT:
            raise MLConfigError(
                f"feature_source='data_raw' con backend '{self.backend}' exige una política de "
                "imputación declarada (el backend no tolera NaN): FALTA-DATO-ML-1."
            )
        if (
            self.backend in _GBDT_BACKENDS
            and self.train.validation_fraction == 0.0
            and self.train.early_stopping_rounds is not None
        ):
            raise MLConfigError(
                "train.validation_fraction=0.0 desactiva el early stopping, pero "
                f"train.early_stopping_rounds={self.train.early_stopping_rounds} lo pide con un "
                f"backend GBDT ('{self.backend}'): contradicción. Suba validation_fraction o ponga "
                "early_stopping_rounds=None."
            )
        return self
