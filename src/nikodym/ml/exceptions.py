"""Excepciones propias de la capa ``ml`` (SDD-12 §4/§8).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`MLConfigError`, con la
sub-especialización :class:`MLMonotonicError`), de datos de entrada malformados
(:class:`MLDataError`), del backend (:class:`MLBackendError`, con :class:`MLFitError` y
:class:`MLPredictError`), de la comparación campeón-vs-challenger (:class:`MLComparisonError`) y del
determinismo/reproducibilidad (:class:`MLDeterminismError`). Los mensajes van en español e incluyen,
cuando aplica, el backend, la semilla, la partición, la feature y el valor observado.

``MissingDependencyError`` (de :mod:`nikodym.core.exceptions`) se levanta cuando falta el *extra*
del backend seleccionado; **no** es una excepción propia de ``ml``.

En B12.1 solo se materializa la jerarquía; las clases hoja se levantan desde los backends, el
estimador y el step en bloques posteriores (B12.2+).
"""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "MLBackendError",
    "MLComparisonError",
    "MLConfigError",
    "MLDataError",
    "MLDeterminismError",
    "MLError",
    "MLFitError",
    "MLMonotonicError",
    "MLPredictError",
]


class MLError(NikodymError):
    """Error base del challenger de machine learning (SDD-12)."""


class MLConfigError(MLError):
    """Error en la configuración declarativa del challenger (backend/hiperparámetros/monotonía)."""


class MLDataError(MLError):
    """Error en los datos de entrada (features/target/particiones) que consume el challenger."""


class MLBackendError(MLError):
    """Error del backend nativo (versión no soportada, construcción o estado inválido)."""


class MLFitError(MLBackendError):
    """Error durante el ajuste del backend (no converge o falla la librería nativa)."""


class MLPredictError(MLBackendError):
    """Error durante la predicción del backend (PD fuera de ``[0, 1]`` o no finita)."""


class MLMonotonicError(MLConfigError):
    """Se pidió monotonía en un backend que no la soporta con ``on_unsupported='error'``."""


class MLComparisonError(MLError):
    """Error al comparar campeón vs challenger (índices desalineados o particiones sin match)."""


class MLDeterminismError(MLError):
    """Ruptura del determinismo declarado (semilla/hilos incompatibles con reproducibilidad)."""
