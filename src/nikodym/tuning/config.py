"""Config declarativo de la capa ``tuning`` (SDD-13 §5).

:class:`TuningConfig` es la sección ``tuning`` de :class:`~nikodym.core.config.NikodymConfig`: la
búsqueda de hiperparámetros con Optuna que afina el challenger de ``ml`` (SDD-12). **No duplica** el
``backend``/``feature_source``/``monotonic`` de ``ml``: los **hereda** en runtime de
``NikodymConfig.ml`` (:meth:`TuningConfig.resolve_search_space`), de modo que el espacio de búsqueda
por defecto se resuelve para el backend elegido y no hay dos fuentes de verdad. Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config.

La sección es **computacional** (``tuning`` ∉ ``INFRA_SECTIONS``): cambiar el sampler, el espacio de
búsqueda, ``n_trials`` o la métrica **mueve el ``config_hash`` global**. Al cablear B13.2 se movió
``GOLDEN_DEFAULT_CONFIG_HASH`` (mismo precedente aditivo que ``ml``/``validation``).

Núcleo liviano (principio 9): ``import nikodym.tuning`` **no** arrastra optuna/sklearn/pandas/numpy
ni los backends ML. El cross-check del espacio de búsqueda contra el params-model del backend
(``nikodym.ml.config._PARAMS_BY_BACKEND``, SDD-12 §5) importa ``nikodym.ml.config`` de forma
**perezosa** dentro de :meth:`resolve_search_space` (en runtime, cuando ya hay challenger que
tunear), no en import time.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from types import UnionType
from typing import TYPE_CHECKING, Any, Literal, Self, Union, get_args, get_origin

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.tuning.exceptions import TuningConfigError, TuningSearchSpaceError
from nikodym.tuning.search_space import SearchSpaceConfig, default_search_space

if TYPE_CHECKING:
    from nikodym.ml.config import MLConfig

TuningSampler = Literal["tpe", "random"]
TuningPruner = Literal["none", "median"]
TuningMetric = Literal["auc", "gini", "ks"]
ValidationStrategy = Literal["cv", "holdout"]

__all__ = [
    "TuningConfig",
    "TuningMetric",
    "TuningObjectiveConfig",
    "TuningPruner",
    "TuningSampler",
    "TuningSamplerConfig",
    "TuningValidationConfig",
    "ValidationStrategy",
]


class TuningObjectiveConfig(NikodymBaseConfig):
    """Métrica objetivo que maximiza la búsqueda de hiperparámetros."""

    metric: TuningMetric = Field(
        default="auc",
        title="Métrica objetivo",
        description=(
            "Métrica de discriminación a optimizar en validación interna; 'auc' (default) es "
            "invariante a la calibración. 'gini'/'ks' también se maximizan."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Objetivo", "ui_order": 1},
    )
    direction: Literal["maximize"] = Field(
        default="maximize",
        title="Dirección",
        description="auc/gini/ks son «mayor = mejor»; la búsqueda siempre maximiza.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Objetivo", "ui_order": 2},
    )


class TuningSamplerConfig(NikodymBaseConfig):
    """Sampler, pruner y presupuesto de trials del estudio Optuna."""

    sampler: TuningSampler = Field(
        default="tpe",
        title="Sampler",
        description="'tpe' (Bayesiano, eficiente en pocos trials, seedeable) o 'random'.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Sampler", "ui_order": 1},
    )
    pruner: TuningPruner = Field(
        default="none",
        title="Pruner",
        description=(
            "'none' (búsqueda completa, determinismo simple) o 'median' (poda con valores por "
            "fold; exige validación 'cv')."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Sampler", "ui_order": 2},
    )
    n_trials: int = Field(
        default=50,
        ge=1,
        le=10000,
        title="Nº de trials",
        description="Cantidad de combinaciones de hiperparámetros a evaluar (≈ n_trials·K·fit).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Sampler", "ui_order": 3},
    )
    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        title="Timeout (segundos)",
        description=(
            "Corte por reloj de pared; None (default) es byte-reproducible. Un valor no nulo exige "
            "deterministic=False (el corte por tiempo no es byte-a-byte reproducible)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Sampler", "ui_order": 4},
    )


class TuningValidationConfig(NikodymBaseConfig):
    """Estrategia de validación interna sobre ``desarrollo``; holdout y OOT nunca entran."""

    strategy: ValidationStrategy = Field(
        default="cv",
        title="Estrategia de validación",
        description=(
            "'cv' (K folds estratificados seeded) o 'holdout' (split interno único). Siempre sobre "
            "'desarrollo'; holdout/oot nunca entran a la búsqueda."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Validación", "ui_order": 1},
    )
    n_folds: int = Field(
        default=5,
        ge=2,
        le=20,
        title="Nº de folds",
        description="Número de folds estratificados para strategy='cv' (fijas entre trials).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 2},
    )
    holdout_fraction: float = Field(
        default=0.2,
        gt=0.0,
        lt=1.0,
        title="Fracción de holdout interno",
        description="Fracción de 'desarrollo' reservada para validación en strategy='holdout'.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Validación", "ui_order": 3},
    )
    fit_partition: str = Field(
        default="desarrollo",
        title="Partición de búsqueda",
        description=(
            "Campo reservado: hoy no altera la búsqueda. La partición de ajuste efectiva es la "
            "declarada en `ml.train.fit_partition`."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Validación", "ui_order": 4},
    )


class TuningConfig(NikodymBaseConfig):
    """Busca con Optuna los hiperparámetros del challenger definido en ``ml``."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección tuning",
        description="Variante de la sección tuning; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema tuning",
        description="Versión local del schema del tuning para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    objective: TuningObjectiveConfig = Field(
        default_factory=TuningObjectiveConfig,
        title="Objetivo",
        description="Métrica de discriminación que la búsqueda maximiza.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Objetivo", "ui_order": 1},
    )
    optimizer: TuningSamplerConfig = Field(
        default_factory=TuningSamplerConfig,
        title="Sampler",
        description="Sampler, pruner, número de trials y timeout del estudio Optuna.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Sampler", "ui_order": 1},
    )
    validation: TuningValidationConfig = Field(
        default_factory=TuningValidationConfig,
        title="Validación",
        description="Estrategia de validación interna anti-leakage sobre 'desarrollo'.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Validación", "ui_order": 1},
    )
    search_space: SearchSpaceConfig = Field(
        default_factory=SearchSpaceConfig,
        title="Espacio de búsqueda",
        description=(
            "Mapa hiperparámetro→distribución; vacío ⇒ default por backend de 'ml'. Las claves "
            "deben ser hiperparámetros del backend de 'ml'."
        ),
        json_schema_extra={"ui_widget": "table", "ui_group": "Espacio de búsqueda", "ui_order": 1},
    )
    refit_best: bool = Field(
        default=True,
        title="Reajustar el mejor",
        description="Publica best_estimator reajustado sobre 'desarrollo' con los HP ganadores.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "General", "ui_order": 2},
    )
    deterministic: bool = Field(
        default=True,
        title="Determinismo byte-a-byte",
        description=(
            "True fuerza secuencial single-thread sin timeout para byte-reproducibilidad (golden "
            "values); False habilita el modo performance marcado como no byte-reproducible."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Reproducibilidad", "ui_order": 1},
    )
    n_jobs: int = Field(
        default=1,
        ge=1,
        le=256,
        title="Nº de trials en paralelo",
        description="Trials concurrentes; >1 exige deterministic=False (rompe el orden).",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Reproducibilidad",
            "ui_order": 2,
        },
    )

    @model_validator(mode="after")
    def _valida_tuning(self) -> Self:
        """Valida determinismo y coherencia pruner↔validación (SDD-13 §5).

        El cross-check del espacio de búsqueda contra el params-model del backend se difiere a
        :meth:`resolve_search_space` porque necesita la sección ``ml`` (el backend no se duplica
        aquí).
        """
        if self.deterministic and self.n_jobs > 1:
            raise TuningConfigError(
                "deterministic=True exige n_jobs=1 (el paralelismo de trials rompe el orden "
                f"reproducible; n_jobs={self.n_jobs}). Use deterministic=False para el modo "
                "performance."
            )
        if self.deterministic and self.optimizer.timeout_seconds is not None:
            raise TuningConfigError(
                "deterministic=True exige timeout_seconds=None (el corte por reloj de pared no es "
                f"byte-reproducible; timeout_seconds={self.optimizer.timeout_seconds})."
            )
        if self.optimizer.pruner != "none" and self.validation.strategy == "holdout":
            raise TuningConfigError(
                f"pruner='{self.optimizer.pruner}' exige strategy='cv' (el holdout interno no "
                "reporta valores intermedios por fold que podar)."
            )
        return self

    def resolve_search_space(self, ml_config: MLConfig | None) -> SearchSpaceConfig:
        """Resuelve el espacio de búsqueda efectivo contra el backend de ``ml`` (SDD-13 §5).

        ``tuning`` hereda el backend de ``ml`` (no lo duplica): un ``ml`` ausente impide tunear
        (:class:`~nikodym.tuning.exceptions.TuningConfigError`). Con ``search_space`` vacío devuelve
        ``default_search_space(ml.backend)``; si el usuario declaró claves, cada una debe ser un
        hiperparámetro del params-model del backend y su ``kind`` debe casar con el tipo del campo
        (:class:`~nikodym.tuning.exceptions.TuningSearchSpaceError`).
        """
        if ml_config is None:
            raise TuningConfigError(
                "tuning requiere una sección 'ml' activa (no hay challenger que tunear): declare "
                "'ml' en el config o retire 'tuning'."
            )
        from nikodym.ml.config import _PARAMS_BY_BACKEND

        backend = ml_config.backend
        if not self.search_space.params:
            return default_search_space(backend)
        campos = _PARAMS_BY_BACKEND[backend].model_fields
        for nombre, spec in self.search_space.params.items():
            campo = campos.get(nombre)
            if campo is None:
                validos = ", ".join(sorted(campos))
                raise TuningSearchSpaceError(
                    f"el hiperparámetro '{nombre}' no existe en el backend '{backend}'; "
                    f"campos válidos: {validos}."
                )
            kinds = _kinds_admitidos(campo.annotation)
            if spec.kind not in kinds and spec.kind != "categorical":
                admitidos = ", ".join(sorted(kinds)) or "categorical"
                raise TuningSearchSpaceError(
                    f"la distribución '{spec.kind}' es incompatible con el hiperparámetro "
                    f"'{nombre}' del backend '{backend}' (kinds admitidos: {admitidos})."
                )
        return self.search_space


def _kinds_admitidos(annotation: Any) -> frozenset[str]:
    """Deriva los ``kind`` de spec numéricos admisibles para el tipo de un hiperparámetro.

    Un tipo ``int`` admite ``IntSpec``; ``float`` admite ``FloatSpec``; las uniones agregan los
    ``kind`` de sus miembros (``int | None`` sigue siendo entero). Los ``Literal`` y demás tipos no
    numéricos no admiten spec numérica (solo ``CategoricalSpec``, aceptada por cualquier campo).
    """
    if get_origin(annotation) in (Union, UnionType):
        kinds: set[str] = set()
        for arg in get_args(annotation):
            kinds |= _kinds_admitidos(arg)
        return frozenset(kinds)
    if annotation is int:
        return frozenset({"int"})
    if annotation is float:
        return frozenset({"float"})
    return frozenset()
