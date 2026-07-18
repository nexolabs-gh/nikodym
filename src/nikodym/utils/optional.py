"""Import perezoso de *extras* opcionales (SDD-25 §4).

:func:`require_extra` importa los módulos de un extra y, si falta alguno, levanta
:class:`~nikodym.core.exceptions.MissingDependencyError` con la línea de instalación exacta. El
import ocurre **dentro** de la función que lo necesita, para que ``import nikodym`` nunca
arrastre el stack pesado: ``from nikodym.ml import XGBoostModel`` no falla; solo falla al
*usar* el backend sin el extra.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from nikodym.core.exceptions import MissingDependencyError

__all__ = ["EXTRA_TO_DISTRIBUTIONS", "has_extra", "require_extra"]

# Mapa extra -> nombres de MÓDULOS importables a verificar (no las distribuciones pip
# completas: p. ej. el extra "scoring" instala "scikit-learn" pero su módulo de import es
# "sklearn"). Por contrato, el conjunto de CLAVES coincide exactamente con el de
# [project.optional-dependencies] menos "all" para los extras atendidos por ``require_extra``.
# Otros extras poseen validación específica en su módulo (p. ej. report/pdf/docx/ai); por eso el
# contrato es de inclusión, no una biyección exacta (test en ``test_optional.py``).
EXTRA_TO_DISTRIBUTIONS: dict[str, tuple[str, ...]] = {
    "scoring": ("optbinning", "statsmodels", "sklearn"),
    "ml": ("sklearn",),
    "xgboost": ("xgboost",),
    "lightgbm": ("lightgbm",),
    "catboost": ("catboost",),
    "tuning": ("optuna",),
    "explain": ("shap", "matplotlib"),
    "forecasting": ("statsmodels", "pmdarima"),
    "survival": ("lifelines",),
    "tracking": ("mlflow",),
    "ui": ("fastapi", "uvicorn"),
    "sweep": ("hydra", "omegaconf"),
    "polars": ("polars",),
}


def require_extra(extra: str, *modules: str) -> tuple[ModuleType, ...]:
    """Importa y devuelve los módulos de un extra; si falta uno, levanta ``MissingDependencyError``.

    Parameters
    ----------
    extra : str
        Nombre del extra (clave de ``[project.optional-dependencies]``), usado en el mensaje
        de instalación.
    *modules : str
        Nombres de módulos importables a resolver (p. ej. ``"xgboost"``).

    Returns
    -------
    tuple of module
        Los módulos importados, en el mismo orden.

    Raises
    ------
    MissingDependencyError
        Si alguno de los módulos no se puede importar.

    Examples
    --------
    >>> xgb, = require_extra("xgboost", "xgboost")  # doctest: +SKIP
    """
    imported: list[ModuleType] = []
    for module_name in modules:
        try:
            imported.append(importlib.import_module(module_name))
        except ImportError as exc:
            raise MissingDependencyError(
                f"La función requiere el extra '{extra}'. Instálalo con: "
                f"pip install 'nikodym[{extra}]' (o uv add 'nikodym[{extra}]')."
            ) from exc
    return tuple(imported)


def has_extra(extra: str, *modules: str) -> bool:
    """Devuelve ``True`` si todos los ``modules`` del extra están importables (sin levantar)."""
    try:
        require_extra(extra, *modules)
    except MissingDependencyError:
        return False
    return True
