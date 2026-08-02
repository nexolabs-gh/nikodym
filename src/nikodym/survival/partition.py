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

from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias, cast

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
    "SCOPE_DESARROLLO",
    "SCOPE_POBLACION_COMPLETA",
    "FitScope",
    "fit_mask",
]

PARTITION_COL: Final = "partition"
"""Nombre de la columna de partición que produce la capa ``data``."""

PARTITION_DESARROLLO: Final = "desarrollo"
"""Etiqueta de la partición sobre la que se ajusta un modelo."""

FitScope: TypeAlias = Literal["desarrollo", "poblacion_completa"]
"""Sobre qué población se ajustó el modelo. Viaja al card y al audit-trail."""

SCOPE_DESARROLLO: Final[FitScope] = "desarrollo"
"""Se ajustó sólo sobre las filas ``desarrollo`` de la columna de partición."""

SCOPE_POBLACION_COMPLETA: Final[FitScope] = "poblacion_completa"
"""Se ajustó sobre el frame entero porque no había columna de partición."""


def fit_mask(frame: DataFrame, *, np: Any) -> tuple[NDArrayBool, FitScope]:
    """Selecciona las filas de ajuste y **declara** sobre qué población se ajusta.

    El alcance vuelve junto a la máscara a propósito: así el llamador no puede quedarse sin
    saberlo, que es exactamente lo que ocurría cuando esta función devolvía una máscara de unos y
    nadie distinguía «ajusté sobre Desarrollo» de «ajusté sobre todo el libro».

    Los dos casos sin filtro eran silenciosos y **no son el mismo caso**:

    **Sin columna** ``partition`` **el ajuste va sobre el frame completo, y eso se mantiene.** Es
    el contrato de SDD-18 que ``SurvivalStep`` usa en modo standalone, donde la partición se
    descarta a mano porque el ajuste es de provisión sobre el libro entero y no un ejercicio de
    validación. Lo único que cambia es que el alcance se publica en vez de deducirse.

    **Con columna** ``partition`` **y ninguna fila** ``desarrollo``, en cambio, se levanta. Ese
    caso no estaba documentado en ninguna parte y ajustaba sobre la población completa
    *contradiciendo la columna que el propio usuario declaró*: el número cambiaba y nada enrojecía.
    Que el motor ya quisiera fallar ahí está escrito en los dos motores —``"No hay filas de
    Desarrollo para ajustar…"``—, mensaje que la máscara de unos volvía inalcanzable salvo con el
    frame entero vacío, o sea justo cuando el texto miente. No es un aviso declarado: la
    institución **sí** aportó el dato y el motor no difirió ninguna capacidad; es una entrada que
    se contradice a sí misma, y para eso está :class:`SurvivalInputError`.

    Parameters
    ----------
    frame : pandas.DataFrame
        Frame ya preparado y validado por el motor.
    np : module
        ``numpy`` inyectado por el llamador para no importarlo en top-level.

    Returns
    -------
    tuple of (numpy.ndarray, str)
        Máscara booleana de las filas que entran al ajuste y el alcance (:data:`FitScope`).

    Raises
    ------
    SurvivalInputError
        Si la columna ``partition`` trae *missing*, o si existe y no trae ninguna fila
        ``desarrollo``.
    """
    if PARTITION_COL not in frame.columns:
        completa = cast("NDArrayBool", np.ones(len(frame.index), dtype=bool))
        return completa, SCOPE_POBLACION_COMPLETA
    if bool(frame[PARTITION_COL].isna().any()):
        raise SurvivalInputError(f"La columna {PARTITION_COL} no puede contener missing.")
    values = frame[PARTITION_COL].astype("string")
    mask = cast(
        "NDArrayBool", (values == PARTITION_DESARROLLO).to_numpy(dtype=bool, na_value=False)
    )
    if not bool(mask.any()):
        observadas = ", ".join(sorted({str(value) for value in values.dropna().unique()}))
        raise SurvivalInputError(
            f"La columna '{PARTITION_COL}' no trae ninguna fila '{PARTITION_DESARROLLO}': "
            f"etiquetas observadas = [{observadas}]. El ajuste survival se hace sobre Desarrollo. "
            f"Renombre la etiqueta a '{PARTITION_DESARROLLO}', o quite la columna si de verdad "
            "quiere ajustar sobre la población completa."
        )
    return mask, SCOPE_DESARROLLO
