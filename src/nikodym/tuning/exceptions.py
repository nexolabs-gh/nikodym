"""Excepciones propias de la capa ``tuning`` (SDD-13 §4/§8).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`TuningConfigError`, con la
sub-especialización :class:`TuningSearchSpaceError` para el espacio de búsqueda), de datos de
entrada malformados o particiones degeneradas (:class:`TuningDataError`), de la optimización Optuna
(:class:`TuningOptimizeError`) y del determinismo/reproducibilidad
(:class:`TuningDeterminismError`). Los mensajes van en español e incluyen, cuando aplica, el
sampler, la semilla, el backend, el hiperparámetro, el trial y el valor observado.

``MissingDependencyError`` (de :mod:`nikodym.core.exceptions`) se levanta cuando falta el *extra*
``[tuning]`` (optuna); **no** es una excepción propia de ``tuning``.

En B13.1 solo se materializa la jerarquía; las clases hoja se levantan desde el espacio de búsqueda,
el optimizador y el step en bloques posteriores (B13.2+).
"""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "TuningConfigError",
    "TuningDataError",
    "TuningDeterminismError",
    "TuningError",
    "TuningOptimizeError",
    "TuningSearchSpaceError",
]


class TuningError(NikodymError):
    """Error base de la búsqueda de hiperparámetros (SDD-13)."""


class TuningConfigError(TuningError):
    """Error en la configuración declarativa del tuning (sampler/validación/determinismo)."""


class TuningSearchSpaceError(TuningConfigError):
    """Error en el espacio de búsqueda (distribución inválida, rango o tipos incoherentes)."""


class TuningDataError(TuningError):
    """Error en los datos de búsqueda (una sola clase, folds imposibles o filas insuficientes)."""


class TuningOptimizeError(TuningError):
    """Error durante la optimización Optuna (todos los trials fallaron o valor no finito)."""


class TuningDeterminismError(TuningError):
    """Ruptura del determinismo declarado (paralelismo/timeout rompen la byte-reproducción)."""
