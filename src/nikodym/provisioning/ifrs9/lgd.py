"""Estimación de la LGD IFRS 9 por los enfoques provided/beta/fractional/workout (SDD-16 §3/§7).

:class:`LgdEngine` calcula la pérdida dado default (LGD) por operación desde el ``frame`` económico,
respetando la distribución bimodal de la LGD (ESPEC §5.5): **nunca OLS plano**. Enfoques del campo
``IfrsLgdConfig.method``:

- ``provided``: consume la LGD entregada por la institución desde ``lgd_col``; si ``recovery_col``
  está informada, aplica la identidad ``LGD = 1 - recovery`` sobre esa tasa de recuperación.
- ``beta_regression``: regresión Beta (statsmodels ``BetaModel``) sobre ``covariate_cols``; el
  objetivo debe caer estrictamente en ``(0, 1)``.
- ``fractional_response``: GLM binomial con link logit (Papke-Wooldridge) sobre ``covariate_cols``;
  el objetivo admite masas en 0/1 dentro de ``[0, 1]``.
- ``workout``: ``LGD = 1 - PV(recuperaciones - costos)/EAD`` con los flujos descontados a la EIR del
  instrumento o a una tasa contractual según ``workout_discount`` (D-IFRS-12).

Contrato transversal (SDD-16 §6/§8): la salida se acota con ``lgd_floor``/``lgd_cap`` (clip
explícito y auditado, dentro de ``[0, 1]``); si un valor estimado cae fuera de ``[0, 1]`` (o no es
finito) se levanta :class:`~nikodym.provisioning.ifrs9.exceptions.IfrsLgdError` en vez de clipar en
silencio, y ``-0.0`` se normaliza a ``0.0``. El motor no muta el ``frame`` (solo lee columnas y
construye una salida nueva alineada por índice).

``pandas``/``numpy``/``statsmodels`` se importan de forma perezosa dentro de los métodos (extra
``scoring``): ni ``import nikodym.core`` ni ``import nikodym.provisioning.ifrs9`` deben arrastrar
esas dependencias pesadas en top-level.

**Columnas convencionales del enfoque workout.** ``IfrsLgdConfig`` (fijado en B16.1) parametriza
solo ``recovery_col`` y ``workout_discount``; el resto de insumos workout se leen del ``frame`` por
nombre fijo (``ead``, ``recovery_cost`` opcional, ``recovery_time_years`` y ``contractual_rate``
cuando el descuento es contractual). El panel longitudinal económico completo se difiere por CT-3.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import warnings
from typing import TYPE_CHECKING, Any, Self, TypeAlias, cast

from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.ifrs9.exceptions import IfrsLgdError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.provisioning.ifrs9.config import IfrsLgdConfig

    NDArrayFloat: TypeAlias = np.ndarray[Any, np.dtype[np.float64]]
    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series
else:
    NDArrayFloat: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["LgdEngine"]

# Columnas convencionales del enfoque workout (no parametrizadas en IfrsLgdConfig en B16.4; el panel
# longitudinal económico se difiere por CT-3). El motor las lee del frame por nombre fijo.
_WORKOUT_EAD_COLUMN: str = "ead"
_WORKOUT_COST_COLUMN: str = "recovery_cost"
_WORKOUT_TIME_COLUMN: str = "recovery_time_years"
_WORKOUT_CONTRACTUAL_RATE_COLUMN: str = "contractual_rate"

_NUMPY_MESSAGE: str = "LgdEngine requiere numpy; instale nikodym[scoring]."
_PANDAS_MESSAGE: str = "LgdEngine requiere pandas; instale nikodym[scoring]."
_STATSMODELS_MESSAGE: str = (
    "El enfoque LGD beta_regression/fractional_response requiere statsmodels; "
    "instale nikodym[scoring]."
)


class LgdEngine:
    """Motor de estimación de la LGD IFRS 9 por los cuatro enfoques soportados (SDD-16 §3)."""

    def __init__(self, config: IfrsLgdConfig) -> None:
        """Inicializa el motor con su sub-config ``IfrsLgdConfig`` ya validado."""
        self._config = config

    @classmethod
    def from_config(cls, cfg: IfrsLgdConfig) -> Self:
        """Construye el motor LGD desde ``IfrsLgdConfig`` (molde hermano ``from_config``)."""
        return cls(cfg)

    def estimate(self, frame: DataFrame, *, eir: Series | None = None) -> DataFrame:
        """Estima la LGD por operación según el enfoque configurado y aplica floor/cap.

        Parameters
        ----------
        frame
            DataFrame económico con las columnas que exige el enfoque (LGD/recovery, covariables o
            insumos workout). No se muta.
        eir
            Tasa efectiva por instrumento, alineada por posición al ``frame``; obligatoria en el
            enfoque ``workout`` con ``workout_discount='eir'`` e ignorada en el resto.

        Returns
        -------
        pandas.DataFrame
            Una fila por operación con la columna ``lgd`` en ``[lgd_floor, lgd_cap]`` y el índice
            del ``frame`` preservado.

        Raises
        ------
        IfrsLgdError
            Si falta una columna requerida, un insumo no es finito/numérico, el enfoque workout no
            recibe la EIR o la LGD estimada cae fuera de ``[0, 1]``.
        MissingDependencyError
            Si falta ``numpy``/``pandas`` o ``statsmodels`` para los enfoques de regresión.
        """
        numpy = _import_numpy()
        pandas = _import_pandas()
        method = self._config.method
        if method == "provided":
            raw = self._estimate_provided(frame, numpy)
        elif method == "workout":
            raw = self._estimate_workout(frame, eir, numpy)
        else:
            raw = self._estimate_regression(frame, numpy)
        return self._finalize(frame, raw, numpy, pandas)

    def _estimate_provided(self, frame: DataFrame, numpy: Any) -> NDArrayFloat:
        """Consume la LGD entregada o la deriva de ``recovery_col`` con ``LGD = 1 - recovery``."""
        config = self._config
        recovery_col = config.recovery_col
        if recovery_col is not None:
            recovery = _column(frame, recovery_col, numpy)
            return cast("NDArrayFloat", 1.0 - recovery)
        return _column(frame, config.lgd_col, numpy)

    def _estimate_workout(self, frame: DataFrame, eir: Series | None, numpy: Any) -> NDArrayFloat:
        """Calcula ``LGD = 1 - PV(recuperaciones - costos)/EAD`` descontando a EIR o contractual."""
        config = self._config
        # IfrsLgdConfig garantiza recovery_col no-None cuando method='workout' (SDD-16 §5).
        recovery_col = cast("str", config.recovery_col)
        recovery = _column(frame, recovery_col, numpy)
        ead = _column(frame, _WORKOUT_EAD_COLUMN, numpy)
        time_years = _column(frame, _WORKOUT_TIME_COLUMN, numpy)
        if _WORKOUT_COST_COLUMN in frame.columns:
            cost = _column(frame, _WORKOUT_COST_COLUMN, numpy)
        else:
            cost = numpy.zeros_like(recovery)
        rate = self._workout_rate(frame, eir, numpy)
        if bool(numpy.any(rate <= -1.0)):
            raise IfrsLgdError(
                "El enfoque LGD 'workout' exige una tasa de descuento mayor que -1 por fila."
            )
        if bool(numpy.any(ead <= 0.0)):
            raise IfrsLgdError(
                "El enfoque LGD 'workout' exige una EAD estrictamente positiva por fila."
            )
        if bool(numpy.any(time_years < 0.0)):
            raise IfrsLgdError(
                "El enfoque LGD 'workout' exige un tiempo de recupero no negativo por fila."
            )
        discount = numpy.power(1.0 + rate, time_years)
        present_value = (recovery - cost) / discount
        return cast("NDArrayFloat", 1.0 - present_value / ead)

    def _workout_rate(self, frame: DataFrame, eir: Series | None, numpy: Any) -> NDArrayFloat:
        """Resuelve la tasa de descuento workout: EIR de la serie o columna contractual."""
        if self._config.workout_discount == "eir":
            if eir is None:
                raise IfrsLgdError(
                    "El enfoque LGD 'workout' con descuento 'eir' requiere la serie eir."
                )
            return _series_to_array(eir, frame, numpy, name="eir")
        return _column(frame, _WORKOUT_CONTRACTUAL_RATE_COLUMN, numpy)

    def _estimate_regression(self, frame: DataFrame, numpy: Any) -> NDArrayFloat:
        """Ajusta la LGD con regresión Beta o GLM fraccional y devuelve el ajuste por fila."""
        config = self._config
        target = self._regression_target(frame, numpy)
        exog_raw = numpy.column_stack(
            [_column(frame, column, numpy) for column in config.covariate_cols]
        )
        statsmodels_api = _import_statsmodels()
        exog = statsmodels_api.add_constant(exog_raw, has_constant="add")
        return _fit_predict(config.method, target, exog, statsmodels_api, numpy)

    def _regression_target(self, frame: DataFrame, numpy: Any) -> NDArrayFloat:
        """Deriva el objetivo LGD del ajuste y valida su soporte según el enfoque de regresión."""
        config = self._config
        recovery_col = config.recovery_col
        if recovery_col is not None:
            target = 1.0 - _column(frame, recovery_col, numpy)
        else:
            target = _column(frame, config.lgd_col, numpy)
        if config.method == "beta_regression":
            if bool(numpy.any((target <= 0.0) | (target >= 1.0))):
                raise IfrsLgdError("beta_regression exige el objetivo LGD estrictamente en (0, 1).")
        elif bool(numpy.any((target < 0.0) | (target > 1.0))):
            raise IfrsLgdError("fractional_response exige el objetivo LGD en [0, 1].")
        return cast("NDArrayFloat", target)

    def _finalize(self, frame: DataFrame, raw: NDArrayFloat, numpy: Any, pandas: Any) -> DataFrame:
        """Valida rango/finitud, aplica floor/cap explícito, normaliza ``-0.0`` y arma la salida."""
        values = numpy.asarray(raw, dtype=numpy.float64)
        valid = numpy.isfinite(values) & (values >= 0.0) & (values <= 1.0)
        if not bool(numpy.all(valid)):
            raise IfrsLgdError(
                "La LGD estimada debe ser finita y estar en [0, 1]; no se clipa en silencio."
            )
        config = self._config
        clipped = numpy.clip(values, config.lgd_floor, config.lgd_cap)
        normalized = numpy.where(clipped == 0.0, 0.0, clipped)
        return cast("DataFrame", pandas.DataFrame({"lgd": normalized}, index=frame.index))


def _column(frame: DataFrame, name: str, numpy: Any) -> NDArrayFloat:
    """Extrae una columna del ``frame`` como arreglo float64 finito, o levanta ``IfrsLgdError``."""
    if name not in frame.columns:
        raise IfrsLgdError(f"La columna '{name}' requerida por el enfoque LGD no está en el frame.")
    return _to_float_array(frame[name].to_numpy(), name, numpy)


def _series_to_array(series: Series, frame: DataFrame, numpy: Any, *, name: str) -> NDArrayFloat:
    """Convierte una serie a float64 finito y valida que alinee su longitud con el ``frame``."""
    array = _to_float_array(series.to_numpy(), name, numpy)
    if array.shape[0] != frame.shape[0]:
        raise IfrsLgdError(
            f"La serie '{name}' debe alinear su longitud con el frame ({frame.shape[0]} filas)."
        )
    return array


def _to_float_array(values: Any, name: str, numpy: Any) -> NDArrayFloat:
    """Castea a float64 y exige valores finitos, mapeando fallos a ``IfrsLgdError``."""
    try:
        array = numpy.asarray(values, dtype=numpy.float64)
    except (ValueError, TypeError) as exc:
        raise IfrsLgdError(f"El campo '{name}' debe ser numérico.") from exc
    if not bool(numpy.all(numpy.isfinite(array))):
        raise IfrsLgdError(f"El campo '{name}' debe contener sólo valores finitos.")
    return cast("NDArrayFloat", array)


def _fit_predict(
    method: str, endog: NDArrayFloat, exog: Any, statsmodels_api: Any, numpy: Any
) -> NDArrayFloat:
    """Ajusta el modelo de regresión LGD y devuelve la predicción ajustada, con error controlado."""
    model: Any
    fit_kwargs: dict[str, Any]
    if method == "beta_regression":
        beta_model_cls = _import_beta_model()
        model = beta_model_cls(endog, exog)
        fit_kwargs = {"disp": 0}
    else:
        model = statsmodels_api.GLM(endog, exog, family=statsmodels_api.families.Binomial())
        fit_kwargs = {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            predicted = model.fit(**fit_kwargs).predict(exog)
    except Exception as exc:
        raise IfrsLgdError(f"El ajuste LGD '{method}' no convergió o falló: {exc}") from exc
    return _to_float_array(numpy.asarray(predicted), "lgd_predicha", numpy)


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


def _import_statsmodels() -> Any:
    """Importa ``statsmodels.api`` bajo demanda (dependencia pesada del extra ``scoring``)."""
    try:
        return importlib.import_module("statsmodels.api")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_STATSMODELS_MESSAGE) from exc


def _import_beta_model() -> Any:
    """Importa ``statsmodels.othermod.betareg.BetaModel`` bajo demanda (extra ``scoring``)."""
    try:
        module = importlib.import_module("statsmodels.othermod.betareg")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_STATSMODELS_MESSAGE) from exc
    return module.BetaModel
