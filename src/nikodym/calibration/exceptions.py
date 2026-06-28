"""Excepciones propias de la capa ``calibration`` (SDD-10 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = ["CalibrationError", "CalibrationFitError", "CalibrationTransformError"]


class CalibrationError(NikodymError):
    """Error base de la calibración de PD cruda a PD calibrada."""


class CalibrationFitError(CalibrationError):
    """Error al ajustar parámetros de calibración desde la partición de desarrollo."""


class CalibrationTransformError(CalibrationError):
    """Error al transformar PD cruda o publicar columnas calibradas."""
