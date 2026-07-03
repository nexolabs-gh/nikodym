"""Excepciones propias de la capa ``validation`` (SDD-22 §4/§8).

Toda excepción desciende de :class:`~nikodym.core.exceptions.NikodymError` (raíz propia de la
librería). La jerarquía separa los errores de configuración (:class:`ValidationConfigError`), de
datos de entrada malformados (:class:`ValidationDataError`), de los tests de calibración
(:class:`CalibrationTestError`, p. ej. grupo Hosmer-Lemeshow degenerado) y del backtesting
realizado-vs-estimado (:class:`BacktestError`). Los mensajes van en español e incluyen el test, la
partición/grado/segmento, el estadístico, el umbral, el valor observado y el verdicto si aplica.

En B22.1 solo se materializa la jerarquía; las clases hoja se levantan desde los evaluadores y el
step en bloques posteriores (B22.3+).
"""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "BacktestError",
    "CalibrationTestError",
    "ValidationConfigError",
    "ValidationDataError",
    "ValidationError",
]


class ValidationError(NikodymError):
    """Error base de la validación avanzada (calibración, backtesting, semáforo)."""


class ValidationConfigError(ValidationError):
    """Error en la configuración declarativa de la validación."""


class ValidationDataError(ValidationError):
    """Error en los datos de entrada (PD/target/realizados) que consume la validación."""


class CalibrationTestError(ValidationError):
    """Error en un test de calibración (Hosmer-Lemeshow, binomial/Jeffreys, Brier)."""


class BacktestError(ValidationError):
    """Error en el backtesting realizado-vs-estimado (t-test LGD/EAD, binomial PD)."""
