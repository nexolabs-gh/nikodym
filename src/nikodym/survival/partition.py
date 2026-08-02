"""La partición Dev/HO/OOT tal como la lee la capa ``survival`` (SDD-18 §7).

Aquí viven **la** constante del nombre de la columna y **la** de la etiqueta de Desarrollo, más la
función que las traduce a la máscara de ajuste. Antes estaban escritas tres veces —
``discrete_hazard``, ``cox_aft`` y ``step``— y la lógica de la máscara, dos. Es el mismo criterio de
D-INV-9: una constante que comparten varios módulos de un dominio vive en un solo objeto, y un test
exige que los consumidores usen **ese** objeto y no un string igual.

El módulo respeta el import liviano de :mod:`nikodym.survival`: no importa ``pandas`` ni ``numpy``
en top-level. La constante canónica del proyecto es :data:`nikodym.data.partition.PARTITION_COL`,
pero importarla desde aquí arrastraría pandas al grafo de importación de ``survival``; en su lugar
``tests/unit/test_survival_partition.py`` ata las dos en los dos sentidos, para que la capa que
*produce* la columna y la que la *lee* no puedan separarse en silencio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.survival.exceptions import SurvivalInputError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    DataFrame: TypeAlias = pd.DataFrame
    NDArrayBool: TypeAlias = np.ndarray[Any, np.dtype[np.bool_]]
else:
    DataFrame: TypeAlias = Any
    NDArrayBool: TypeAlias = Any

__all__ = [
    "PARTITION_COL",
    "PARTITION_DESARROLLO",
    "fit_mask",
]

PARTITION_COL: Final = "partition"
"""Nombre de la columna de partición que produce la capa ``data``."""

PARTITION_DESARROLLO: Final = "desarrollo"
"""Etiqueta de la partición sobre la que se ajusta un modelo."""


def fit_mask(frame: DataFrame, *, np: Any) -> NDArrayBool:
    """Selecciona las filas de Desarrollo sobre las que se ajusta el modelo.

    Sin columna ``partition`` el ajuste va sobre el frame completo. **No es un descuido**: es el
    contrato de SDD-18 que ``SurvivalStep`` usa en modo standalone, donde la partición se descarta
    a mano porque el ajuste es de provisión sobre el libro entero y no un ejercicio de validación.

    Parameters
    ----------
    frame : pandas.DataFrame
        Frame ya preparado y validado por el motor.
    np : module
        ``numpy`` inyectado por el llamador para no importarlo en top-level.

    Returns
    -------
    numpy.ndarray
        Máscara booleana de las filas que entran al ajuste.

    Raises
    ------
    SurvivalInputError
        Si la columna ``partition`` existe y trae *missing*.
    """
    if PARTITION_COL not in frame.columns:
        return cast("NDArrayBool", np.ones(len(frame.index), dtype=bool))
    if bool(frame[PARTITION_COL].isna().any()):
        raise SurvivalInputError(f"La columna {PARTITION_COL} no puede contener missing.")
    values = frame[PARTITION_COL].astype("string")
    mask = cast(
        "NDArrayBool", (values == PARTITION_DESARROLLO).to_numpy(dtype=bool, na_value=False)
    )
    if bool(mask.any()):
        return mask
    return cast("NDArrayBool", np.ones(len(frame.index), dtype=bool))
