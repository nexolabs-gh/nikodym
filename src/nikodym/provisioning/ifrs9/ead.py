"""Estimación de la EAD/CCF IFRS 9 y el perfil de exposición por período (SDD-16 §3/§7).

:class:`EadEngine` calcula la exposición al default (EAD) por operación desde el ``frame``
económico y la despliega a lo largo de los ``periods`` solicitados. Enfoques del campo
``IfrsEadConfig.method``:

- ``provided``: consume la EAD entregada por la institución desde ``ead_col``.
- ``ccf``: aplica ``EAD = drawn + CCF*(limite - drawn)`` usando ``drawn_col``/``limit_col`` y el
  factor de conversión (CCF) por fila (``ccf_col``) o de config (``ccf_value``). La *presencia*
  de una fuente CCF cuando ``method='ccf'`` es un contrato de runtime (SDD-16 §6/§8): el config solo
  garantiza que no se informen ambas a la vez; si falta cualquiera se levanta :class:`IfrsEadError`.

**Perfil de exposición por período (CT-3).** Si el ``frame`` trae ``exposure_profile_col``, esa
columna aporta la EAD(t) longitudinal y se usa por período. Si no existe, la EAD se despliega
**constante** en todos los ``periods`` y cada fila publica el código de aviso ``FALTA-DATO-IFRS-4``
en la columna ``warning_codes`` (el panel longitudinal económico completo se difiere por CT-3). El
aviso viaja por la columna ``warning_codes`` (homóloga a survival/markov/forward), nunca por un
``warnings.warn`` crudo, de modo que no rompe ``filterwarnings=error``.

**Piso D-IFRS-13.** En el enfoque ``ccf``, ante ``credit_limit < drawn`` el término
``CCF*(limite - drawn)`` es negativo y la EAD se acota por default a ``EAD >= drawn`` (no se permite
que el CCF reduzca la exposición por debajo del dispuesto); las filas afectadas publican el código
``ead_floored_limit_below_drawn``. Con independencia del enfoque, una EAD final negativa (p. ej.
``provided`` negativa o ``drawn`` negativo) levanta :class:`IfrsEadError`: en general ``EAD >= 0`` y
no se clipa en silencio. ``-0.0`` se normaliza a ``0.0`` (reproducibilidad).

La salida es un ``DataFrame`` tidy largo por identificador de fila x período con las columnas
``period``, ``ead`` y ``warning_codes``, preservando el índice del ``frame`` (repetido por período).
El motor no muta el ``frame`` (solo lee columnas y construye una salida nueva).

``pandas``/``numpy`` se importan de forma perezosa dentro de los métodos: ni ``import nikodym.core``
ni ``import nikodym.provisioning.ifrs9`` deben arrastrar esas dependencias en top-level.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import importlib
import operator
from typing import TYPE_CHECKING, Any, Self, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9.exceptions import IfrsEadError

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    import pandas as pd

    from nikodym.provisioning.ifrs9.config import IfrsEadConfig

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    NDArrayBool: TypeAlias = np.ndarray[Any, np.dtype[np.bool_]]
    DataFrame: TypeAlias = pd.DataFrame
else:
    NDArrayFloat: TypeAlias = Any
    NDArrayBool: TypeAlias = Any
    DataFrame: TypeAlias = Any

__all__ = ["EadEngine"]

# Aviso CT-3: sin panel longitudinal, la EAD se despliega constante por período (SDD-16 §8/§10).
_WARNING_CONSTANT_PROFILE: str = "FALTA-DATO-IFRS-4"
# Aviso D-IFRS-13: se acotó la EAD a >= drawn ante credit_limit < drawn (SDD-16 §8).
_WARNING_EAD_FLOORED: str = "ead_floored_limit_below_drawn"

_NUMPY_MESSAGE: str = "EadEngine requiere numpy; instale nikodym[scoring]."
_PANDAS_MESSAGE: str = "EadEngine requiere pandas; instale nikodym[scoring]."


class EadEngine:
    """Motor de estimación de la EAD/CCF IFRS 9 por los enfoques provided/ccf (SDD-16 §3)."""

    def __init__(self, config: IfrsEadConfig) -> None:
        """Inicializa el motor con su sub-config ``IfrsEadConfig`` ya validado."""
        self._config = config

    @classmethod
    def from_config(cls, cfg: IfrsEadConfig) -> Self:
        """Construye el motor EAD desde ``IfrsEadConfig`` (molde hermano ``from_config``)."""
        return cls(cfg)

    def estimate(self, frame: DataFrame, *, periods: Sequence[int]) -> DataFrame:
        """Estima la EAD por operación y la despliega a lo largo de ``periods``.

        Parameters
        ----------
        frame
            DataFrame económico con las columnas que exige el enfoque (``ead`` provista, o
            ``drawn``/``credit_limit``/CCF), y opcionalmente ``exposure_profile_col``. No se muta.
        periods
            Secuencia de períodos (enteros ``>= 1``) sobre los que desplegar la EAD(t); no vacía.

        Returns
        -------
        pandas.DataFrame
            Tabla tidy larga por fila x período con ``period``, ``ead`` (``>= 0``) y
            ``warning_codes`` (tupla de códigos por fila); el índice del ``frame`` se repite por
            período.

        Raises
        ------
        IfrsEadError
            Si ``periods`` es vacío o trae un período no entero/``< 1``, falta una columna
            requerida, un insumo no es finito/numérico, ``method='ccf'`` no recibe fuente de CCF, o
            la EAD resultante es negativa.
        MissingDependencyError
            Si falta ``numpy`` o ``pandas``.
        """
        numpy = _import_numpy()
        pandas = _import_pandas()
        resolved_periods = _validate_periods(periods)
        level, warning_codes = self._estimate_level(frame, numpy)
        return self._finalize(frame, level, warning_codes, resolved_periods, numpy, pandas)

    def _estimate_level(
        self, frame: DataFrame, numpy: Any
    ) -> tuple[NDArrayFloat, list[tuple[str, ...]]]:
        """Resuelve la EAD por operación y sus ``warning_codes`` según perfil y enfoque."""
        config = self._config
        profile_col = config.exposure_profile_col
        if profile_col is not None and profile_col in frame.columns:
            # Perfil longitudinal declarado: la EAD(t) proviene de la columna de perfil (sin CT-3).
            level = _column(frame, profile_col, numpy)
            return level, [() for _ in range(level.shape[0])]
        # Sin perfil longitudinal: EAD constante por período; se marca CT-3 en cada fila.
        if config.method == "provided":
            level = _column(frame, config.ead_col, numpy)
            floored = numpy.zeros(level.shape[0], dtype=bool)
        else:
            level, floored = self._estimate_ccf(frame, numpy)
        warning_codes: list[tuple[str, ...]] = [
            (_WARNING_EAD_FLOORED, _WARNING_CONSTANT_PROFILE)
            if bool(flag)
            else (_WARNING_CONSTANT_PROFILE,)
            for flag in floored
        ]
        return level, warning_codes

    def _estimate_ccf(self, frame: DataFrame, numpy: Any) -> tuple[NDArrayFloat, NDArrayBool]:
        """Calcula ``EAD = drawn + CCF*(limite - drawn)`` con el piso D-IFRS-13 (EAD >= drawn)."""
        config = self._config
        drawn = _column(frame, config.drawn_col, numpy)
        limit = _column(frame, config.limit_col, numpy)
        ccf = self._resolve_ccf(frame, drawn, numpy)
        raw = drawn + ccf * (limit - drawn)
        floored = numpy.maximum(raw, drawn)  # D-IFRS-13: la EAD no baja de drawn.
        return cast("NDArrayFloat", floored), cast("NDArrayBool", limit < drawn)

    def _resolve_ccf(self, frame: DataFrame, drawn: NDArrayFloat, numpy: Any) -> NDArrayFloat:
        """Resuelve el CCF por fila (``ccf_col``) o único de config (``ccf_value``)."""
        config = self._config
        if config.ccf_col is not None:
            return _column(frame, config.ccf_col, numpy)
        if config.ccf_value is not None:
            return cast("NDArrayFloat", numpy.full(drawn.shape[0], float(config.ccf_value)))
        raise IfrsEadError(
            "ead.method='ccf' exige una fuente de CCF (ccf_col o ccf_value) en tiempo de cálculo."
        )

    def _finalize(
        self,
        frame: DataFrame,
        level: NDArrayFloat,
        warning_codes: list[tuple[str, ...]],
        periods: tuple[int, ...],
        numpy: Any,
        pandas: Any,
    ) -> DataFrame:
        """Valida ``EAD >= 0`` finita, normaliza ``-0.0`` y arma la salida tidy fila x período."""
        values = numpy.asarray(level, dtype=numpy.float64)
        valid = numpy.isfinite(values) & (values >= 0.0)
        if not bool(numpy.all(valid)):
            raise IfrsEadError(
                "La EAD estimada debe ser finita y no negativa (EAD >= 0); no se clipa en silencio."
            )
        normalized = numpy.where(values == 0.0, 0.0, values)
        n_periods = len(periods)
        period_col = numpy.tile(numpy.asarray(periods, dtype=numpy.int64), normalized.shape[0])
        ead_col = numpy.repeat(normalized, n_periods)
        codes_col = [codes for codes in warning_codes for _ in range(n_periods)]
        return cast(
            "DataFrame",
            pandas.DataFrame(
                {"period": period_col, "ead": ead_col, "warning_codes": codes_col},
                index=frame.index.repeat(n_periods),
            ),
        )


def _validate_periods(periods: Sequence[int]) -> tuple[int, ...]:
    """Valida que ``periods`` sea no vacío y contenga sólo enteros ``>= 1``."""
    resolved: list[int] = []
    for period in periods:
        try:
            value = operator.index(period)
        except TypeError as exc:
            raise IfrsEadError(f"Cada período debe ser un entero; valor: {period!r}.") from exc
        if value < 1:
            raise IfrsEadError(f"Cada período debe ser un entero >= 1; valor: {value!r}.")
        resolved.append(value)
    if not resolved:
        raise IfrsEadError("El horizonte 'periods' no puede estar vacío.")
    return tuple(resolved)


def _column(frame: DataFrame, name: str, numpy: Any) -> NDArrayFloat:
    """Extrae una columna del ``frame`` como arreglo float64 finito, o levanta ``IfrsEadError``."""
    if name not in frame.columns:
        raise IfrsEadError(f"La columna '{name}' requerida por el enfoque EAD no está en el frame.")
    return _to_float_array(frame[name].to_numpy(), name, numpy)


def _to_float_array(values: Any, name: str, numpy: Any) -> NDArrayFloat:
    """Castea a float64 y exige valores finitos, mapeando fallos a ``IfrsEadError``."""
    try:
        array = numpy.asarray(values, dtype=numpy.float64)
    except (ValueError, TypeError) as exc:
        raise IfrsEadError(f"El campo '{name}' debe ser numérico.") from exc
    if not bool(numpy.all(numpy.isfinite(array))):
        raise IfrsEadError(f"El campo '{name}' debe contener sólo valores finitos.")
    return cast("NDArrayFloat", array)


def _import_numpy() -> Any:
    """Importa ``numpy`` bajo demanda para preservar el import liviano del núcleo."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_NUMPY_MESSAGE) from exc


def _import_pandas() -> Any:
    """Importa ``pandas`` bajo demanda para preservar el import liviano del núcleo."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_PANDAS_MESSAGE) from exc
