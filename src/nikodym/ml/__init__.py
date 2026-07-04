"""Capa ``ml`` de Nikodym: challenger de machine learning (SDD-12).

Al importarse, registra :class:`MLConfig` en el hook diferido de
:mod:`nikodym.core.config.schema` (``_ML_CONFIG_CLS``) para que ``NikodymConfig.ml`` se valide como
sub-config real, **sin** que ``import nikodym.core`` ni ``import nikodym.ml`` arrastren dependencias
de machine learning (scikit-learn/xgboost/lightgbm/catboost) ni tabulares (pandas/numpy): los
backends y el estimador se importan de forma **perezosa** en bloques posteriores (B12.2+). Las
excepciones se reexportan perezosas. El registro del :class:`MLStep`
(``@register('standard', domain='ml')``) llega en B12.5; aquí solo se puebla el hook de config.
Nomenclatura en inglés técnico para APIs; docstrings y errores en español.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
from typing import Any, Final

from nikodym.core.config import schema as _schema
from nikodym.ml.config import (
    CatBoostParams,
    ClassWeight,
    ComparisonMetric,
    FeatureSource,
    LightGBMParams,
    MLBackendName,
    MLComparisonConfig,
    MLConfig,
    MLOutputConfig,
    MLTrainConfig,
    MonotonicConfig,
    MonotonicMode,
    RandomForestParams,
    SvmParams,
    XGBoostParams,
)

# Registra la clase real del sub-config ml en el hook de `core` (sin importar backends ML).
_schema._ML_CONFIG_CLS = MLConfig

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "MLBackendError": ("nikodym.ml.exceptions", "MLBackendError"),
    "MLComparisonError": ("nikodym.ml.exceptions", "MLComparisonError"),
    "MLConfigError": ("nikodym.ml.exceptions", "MLConfigError"),
    "MLDataError": ("nikodym.ml.exceptions", "MLDataError"),
    "MLDeterminismError": ("nikodym.ml.exceptions", "MLDeterminismError"),
    "MLError": ("nikodym.ml.exceptions", "MLError"),
    "MLFitError": ("nikodym.ml.exceptions", "MLFitError"),
    "MLMonotonicError": ("nikodym.ml.exceptions", "MLMonotonicError"),
    "MLPredictError": ("nikodym.ml.exceptions", "MLPredictError"),
}

__all__ = [
    "CatBoostParams",
    "ClassWeight",
    "ComparisonMetric",
    "FeatureSource",
    "LightGBMParams",
    "MLBackendError",
    "MLBackendName",
    "MLComparisonConfig",
    "MLComparisonError",
    "MLConfig",
    "MLConfigError",
    "MLDataError",
    "MLDeterminismError",
    "MLError",
    "MLFitError",
    "MLMonotonicError",
    "MLOutputConfig",
    "MLPredictError",
    "MLTrainConfig",
    "MonotonicConfig",
    "MonotonicMode",
    "RandomForestParams",
    "SvmParams",
    "XGBoostParams",
]


def __getattr__(name: str) -> Any:
    """Carga las excepciones de ``ml`` bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.ml' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
