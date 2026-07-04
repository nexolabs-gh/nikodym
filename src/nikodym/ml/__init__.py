"""Capa ``ml`` de Nikodym: challenger de machine learning (SDD-12).

Al importarse, registra :class:`MLConfig` en el hook diferido de
:mod:`nikodym.core.config.schema` (``_ML_CONFIG_CLS``) para que ``NikodymConfig.ml`` se valide como
sub-config real, **sin** que ``import nikodym.core`` ni ``import nikodym.ml`` arrastren dependencias
de machine learning (scikit-learn/xgboost/lightgbm/catboost) ni tabulares (pandas/numpy): los
backends y el estimador se importan de forma **perezosa** en bloques posteriores (B12.2+). Las
excepciones se reexportan perezosas. Al final se importa ``ml.step`` para ejecutar
``@register('standard', domain='ml')`` sin arrastrar ``pandas``/``numpy`` ni los backends ML (el
step los carga perezosamente dentro de ``execute``). Nomenclatura en inglés técnico para APIs;
docstrings y errores en español.

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
    "MLBackendMetadata": ("nikodym.ml.results", "MLBackendMetadata"),
    "MLCardSection": ("nikodym.ml.results", "MLCardSection"),
    "MLChallenger": ("nikodym.ml.estimator", "MLChallenger"),
    "MLComparisonRecord": ("nikodym.ml.results", "MLComparisonRecord"),
    "MLResult": ("nikodym.ml.results", "MLResult"),
    "MLStep": ("nikodym.ml.step", "MLStep"),
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
    "MLBackendMetadata",
    "MLBackendName",
    "MLCardSection",
    "MLChallenger",
    "MLComparisonConfig",
    "MLComparisonError",
    "MLComparisonRecord",
    "MLConfig",
    "MLConfigError",
    "MLDataError",
    "MLDeterminismError",
    "MLError",
    "MLFitError",
    "MLMonotonicError",
    "MLOutputConfig",
    "MLPredictError",
    "MLResult",
    "MLStep",
    "MLTrainConfig",
    "MonotonicConfig",
    "MonotonicMode",
    "RandomForestParams",
    "SvmParams",
    "XGBoostParams",
]

# Import perezoso a nivel paquete para ejecutar @register("standard", domain="ml") al importar
# `nikodym.ml`, sin arrastrar pandas/numpy ni los backends ML (el step los carga en `execute`).
importlib.import_module("nikodym.ml.step")


def __getattr__(name: str) -> Any:
    """Carga las excepciones de ``ml`` bajo demanda para preservar el import liviano."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'nikodym.ml' has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value
