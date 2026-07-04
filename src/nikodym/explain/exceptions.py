"""Excepciones propias de la capa ``explain`` (SDD-14 §4/§8).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`ExplainConfigError`), de datos
de entrada malformados o features desalineadas (:class:`ExplainDataError`), del explainer
(:class:`ExplainBackendError`, con :class:`ExplainExplainerError` para el fallo del cálculo SHAP —
additivity, valores no finitos), de la traducción a reason codes (:class:`ExplainReasonCodeError`)
y del determinismo/reproducibilidad (:class:`ExplainDeterminismError`). Los mensajes van en español
e incluyen, cuando aplica, el modelo (scorecard/ml), el backend, el explainer, la semilla, la
feature y el valor observado.

``MissingDependencyError`` (de :mod:`nikodym.core.exceptions`) se levanta cuando falta el *extra*
``[explain]`` (shap); **no** es una excepción propia de ``explain``.

En B14.1 solo se materializa la jerarquía y :class:`ExplainConfigError` se levanta desde
:class:`~nikodym.explain.config.ExplainConfig`; las clases hoja restantes se levantan desde los
explainers, el motor y el step en bloques posteriores (B14.2+).
"""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "ExplainBackendError",
    "ExplainConfigError",
    "ExplainDataError",
    "ExplainDeterminismError",
    "ExplainError",
    "ExplainExplainerError",
    "ExplainReasonCodeError",
]


class ExplainError(NikodymError):
    """Error base de la capa de explicabilidad unificada (SDD-14)."""


class ExplainConfigError(ExplainError):
    """Error en la configuración declarativa de ``explain`` (explainer/targets/determinismo)."""


class ExplainDataError(ExplainError):
    """Error en los datos de entrada (features desalineadas, particiones o PD malformadas)."""


class ExplainBackendError(ExplainError):
    """Error del explainer SHAP (no construible, incompatible o versión no soportada)."""


class ExplainExplainerError(ExplainBackendError):
    """Fallo del cálculo SHAP (additivity roto o contribuciones no finitas)."""


class ExplainReasonCodeError(ExplainError):
    """Error al traducir contribuciones a reason codes (dirección/orden/magnitud inválidos)."""


class ExplainDeterminismError(ExplainError):
    """Ruptura del determinismo declarado (semilla/hilos incompatibles con la reproducibilidad)."""
