"""Excepciones propias de la capa ``calibration`` (SDD-10 §8)."""

from nikodym.core.exceptions import NikodymError

__all__ = [
    "CalibrationError",
    "CalibrationFitError",
    "CalibrationOffsetExceededError",
    "CalibrationTransformError",
]


class CalibrationError(NikodymError):
    """Error base de la calibración de PD cruda a PD calibrada."""


class CalibrationFitError(CalibrationError):
    """Error al ajustar parámetros de calibración desde la partición de desarrollo."""


class CalibrationOffsetExceededError(CalibrationFitError):
    """Error cuando el reanclaje a tasa central excede el máximo configurado."""

    def __init__(
        self,
        *,
        offset: float,
        max_abs_offset: float,
        method: str,
        partition: str,
    ) -> None:
        """Publica atributos auditables del guard de offset extremo."""
        self.offset = 0.0 if offset == 0.0 else float(offset)
        self.max_abs_offset = float(max_abs_offset)
        self.method = method
        self.partition = partition
        super().__init__(
            "El offset de reanclaje a tasa central excede max_abs_offset: "
            f"offset={self.offset!r}, max_abs_offset={self.max_abs_offset!r}, "
            f"method={self.method!r}, partition={self.partition!r}."
        )


class CalibrationTransformError(CalibrationError):
    """Error al transformar PD cruda o publicar columnas calibradas."""
