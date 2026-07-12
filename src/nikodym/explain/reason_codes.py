"""Traducción de contribuciones a reason codes regulatorios (SDD-14 §3/§7, pasos 5f y 6c).

Un **reason code** es un *driver principal* de la PD de una observación, expresado como
``(rank, feature, dirección, magnitud)``: la dirección indica si la feature **sube**
(``"increases_pd"``, adversa) o **baja** (``"decreases_pd"``, protectora) la PD respecto de la base,
y la magnitud es la contribución ``φ_j`` en la unidad de contribución (log-odds por default). Este
módulo expone :func:`build_reason_codes`, la función **pura** que traduce una matriz de
contribuciones ``(n_obs, n_features)`` a los top-N drivers por observación.

**Contrato común scorecard + ML (SDD-14 §3).** La *misma* función traduce las contribuciones SHAP
del challenger ML y las contribuciones analíticas ``β·(WoE - baseline)`` del scorecard: ambos mundos
producen :class:`~nikodym.explain.results.ReasonCode` con la misma forma, habilitando la comparativa
de drivers aguas abajo. Por eso :func:`build_reason_codes` recibe contribuciones **ya calculadas** y
no conoce el origen (SHAP o álgebra cerrada).

**Sin norma inventada (FALTA-DATO-EXP-1).** ``top_n`` y ``adverse_direction`` son **configurables**
(referencia ECOA/FCRA "key factors", *no* norma CMF): este módulo **no** hardcodea un número ni un
umbral normativo. El piso ``min_abs_contribution`` filtra magnitudes irrelevantes sin fijar un
umbral de gobierno (FALTA-DATO-EXP-2).

**Función pura (SDD-14 §7).** :func:`build_reason_codes` **no** recibe ``audit`` ni emite
``log_decision`` (el acotado de ``top_n`` lo audita el motor B14.4); tampoco puebla ``bin_label``
(``None`` en esta capa, lo aporta el motor desde ``binning.tables``). Solo ordena, filtra y etiqueta
la dirección de forma **estable y reproducible** (desempate lexicográfico por nombre de feature).

**Núcleo liviano (SDD-14 §9).** ``import nikodym.explain.reason_codes`` **no** importa ``numpy``:
se importa de forma **perezosa** dentro de :func:`build_reason_codes`. Nomenclatura en inglés
técnico para APIs; docstrings y errores en español.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
import math
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from nikodym.core.exceptions import MissingDependencyError
from nikodym.explain.exceptions import ExplainReasonCodeError
from nikodym.explain.results import Direction, ReasonCode

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

    # Matriz ``(n_obs, n_features)`` de contribuciones ``φ_j`` (``numpy.ndarray`` de la firma §4).
    ContributionMatrix: TypeAlias = npt.NDArray[np.float64]
else:
    ContributionMatrix: TypeAlias = Any

# Dirección opuesta a la adversa: el driver protector baja la PD (SDD-14 §3).
_OPPOSITE_DIRECTION: dict[Direction, Direction] = {
    "increases_pd": "decreases_pd",
    "decreases_pd": "increases_pd",
}

__all__ = ["build_reason_codes"]


def build_reason_codes(
    contributions: ContributionMatrix,
    feature_names: tuple[str, ...],
    *,
    top_n: int,
    adverse_direction: Literal["increases_pd"],
    include_protective: bool,
    min_abs_contribution: float,
) -> tuple[tuple[ReasonCode, ...], ...]:
    """Traduce una matriz de contribuciones a reason codes top-N por observación (SDD-14 §7).

    Para cada fila de ``contributions`` (una observación) selecciona los drivers que empujan la PD,
    los ordena por magnitud ``|φ_j|`` descendente con **desempate lexicográfico** por
    ``feature_names[j]`` (estable y reproducible), toma los primeros ``top_n`` y les asigna
    ``rank`` 1..k. Un driver es **adverso** si ``φ_j > 0`` (dirección ``adverse_direction``) y
    **protector** si ``φ_j < 0`` (dirección opuesta); los protectores se incluyen solo si
    ``include_protective``. Los drivers con ``φ_j == 0`` (ni suben ni bajan la PD) y los que no
    superan el piso ``min_abs_contribution`` se descartan.

    ``top_n`` mayor que el número de features se **acota silenciosamente** a ``min(top_n,
    n_features)`` sin error (el motor B14.4 lo audita con ``log_decision``). ``bin_label`` se deja
    en ``None``: lo puebla el motor desde ``binning.tables``.

    Contrato común scorecard + ML: la misma traducción sirve para las contribuciones SHAP del
    challenger y para las analíticas ``β·(WoE - baseline)`` del scorecard.

    Raises
    ------
    ExplainReasonCodeError
        Si ``top_n < 1``; si ``min_abs_contribution`` no es un piso finito y no negativo; si
        ``contributions`` no es una matriz 2D alineada con ``feature_names``; o si contiene valores
        no finitos (``NaN``/``inf``) — un error de contrato aguas arriba, pues el explainer debe
        entregar ``φ`` finitos.
    """
    if top_n < 1:
        raise ExplainReasonCodeError(
            f"top_n debe ser al menos 1 para listar reason codes; top_n={top_n}."
        )
    if not math.isfinite(min_abs_contribution) or min_abs_contribution < 0.0:
        raise ExplainReasonCodeError(
            "min_abs_contribution debe ser un piso finito y no negativo; "
            f"min_abs_contribution={min_abs_contribution}."
        )

    np = _import_numpy()
    matrix = np.asarray(contributions, dtype="float64")
    n_features = len(feature_names)
    if matrix.ndim != 2:
        raise ExplainReasonCodeError(
            "contributions debe ser una matriz 2D (n_obs, n_features); "
            f"ndim observado={matrix.ndim}."
        )
    if matrix.shape[1] != n_features:
        raise ExplainReasonCodeError(
            "contributions y feature_names están desalineados: "
            f"n_features de la matriz={matrix.shape[1]}, feature_names={n_features}."
        )
    if not bool(np.isfinite(matrix).all()):
        raise ExplainReasonCodeError(
            "las contribuciones contienen valores no finitos (NaN/inf); es un error de contrato "
            "aguas arriba (el explainer debe entregar φ finitos)."
        )

    protective_direction = _OPPOSITE_DIRECTION[adverse_direction]
    effective_top_n = min(top_n, n_features)
    reason_codes_por_obs: list[tuple[ReasonCode, ...]] = []
    for row in matrix.tolist():
        candidatos = _select_candidates(
            row,
            include_protective=include_protective,
            min_abs_contribution=min_abs_contribution,
        )
        candidatos.sort(key=lambda item: (-abs(item[1]), feature_names[item[0]]))
        seleccion = candidatos[:effective_top_n]
        reason_codes_por_obs.append(
            tuple(
                ReasonCode(
                    rank=rank,
                    feature=feature_names[index],
                    direction=adverse_direction if phi > 0.0 else protective_direction,
                    contribution=phi,
                    bin_label=None,
                )
                for rank, (index, phi) in enumerate(seleccion, start=1)
            )
        )
    return tuple(reason_codes_por_obs)


def _select_candidates(
    row: list[float],
    *,
    include_protective: bool,
    min_abs_contribution: float,
) -> list[tuple[int, float]]:
    """Selecciona ``(índice, φ)`` de los drivers que empujan la PD y superan el piso de magnitud.

    Un driver es candidato si es adverso (``φ > 0``) o protector (``φ < 0`` con
    ``include_protective``) y su magnitud ``|φ|`` alcanza ``min_abs_contribution``. ``φ == 0`` (que
    no empuja la PD) queda fuera por no tener dirección.
    """
    candidatos: list[tuple[int, float]] = []
    for index, phi in enumerate(row):
        adverse = phi > 0.0
        protective = phi < 0.0 and include_protective
        if not (adverse or protective):
            continue
        if abs(phi) < min_abs_contribution:
            continue
        candidatos.append((index, phi))
    return candidatos


def _import_numpy() -> Any:
    """Importa ``numpy`` localmente y traduce su ausencia (dep base) a un mensaje accionable."""
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as exc:  # pragma: no cover - numpy es dep base de data
        raise MissingDependencyError("instale nikodym[ml]") from exc
