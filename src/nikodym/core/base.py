"""Estimador raíz de Nikodym y las seis familias de la jerarquía (SDD-01 §4/§6).

:class:`BaseNikodymEstimator` es una raíz **propia**, no hereda de scikit-learn (D-CORE-1, núcleo
liviano), pero replica la semántica de ``get_params``/``set_params`` por introspección de
``__init__`` para que un estimador de dominio pueda multiheredar ``sklearn.base.*`` sin conflicto.
``config_cls`` es el gancho instancia → clase de sub-config (espejo de ``@register``) que usan
:meth:`BaseNikodymEstimator.from_config` y :meth:`BaseNikodymEstimator._validate_config`.

Las seis familias (``NikodymTransformer``, ``NikodymClassifier``, ``BaseForecaster``,
``BaseSurvivalEstimator``, ``BaseProvisionModel``, ``BaseECLModel``) son cascarones que fijan el MRO
(``AuditableMixin`` primero, para que ``_audit``/``log_decision`` estén disponibles) y documentan su
contrato; los métodos ``fit``/``transform``/``predict``/``compute`` los implementa cada dominio
(T2+), no ``core``. La herencia ``BaseECLModel`` ← ``BaseProvisionModel`` es reutilización del
contrato ``compute()``, **no** parentesco de dominio: CMF e IFRS 9 son dos motores separados (§5.4).

**Experimental (fuera de la garantía SemVer 1.x):** las familias de estimador crecen
aditivamente en las versiones 1.x.
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar, Self

from pydantic import ValidationError

from nikodym.core.config.schema import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, NotFittedError
from nikodym.core.mixins import AuditableMixin

__all__ = [
    "BaseECLModel",
    "BaseForecaster",
    "BaseNikodymEstimator",
    "BaseProvisionModel",
    "BaseSurvivalEstimator",
    "NikodymClassifier",
    "NikodymTransformer",
]


class BaseNikodymEstimator:
    """Raíz propia de todo estimador Nikodym (no hereda de scikit-learn; D-CORE-1).

    Convención: sin lógica en ``__init__`` (sólo asignar hiperparámetros); la validación va en
    ``fit``/``compute``; los atributos fiteados llevan sufijo ``_``. Cada subclase concreta fija
    ``config_cls`` con su clase de sub-config Pydantic (espejo de ``@register``).
    """

    config_cls: ClassVar[type[NikodymBaseConfig]]

    @classmethod
    def _get_param_names(cls) -> list[str]:
        """Nombres de los hiperparámetros (firma de ``__init__``, semántica sklearn).

        Excluye ``self`` y ``**kwargs``; rechaza ``*args`` (``VAR_POSITIONAL``) con ``RuntimeError``
        —un estimador no debe tener parámetros posicionales variables—; devuelve los nombres
        ordenados.
        """
        init = cls.__init__
        if init is object.__init__:
            return []
        parametros = [
            p
            for p in inspect.signature(init).parameters.values()
            if p.name != "self" and p.kind != inspect.Parameter.VAR_KEYWORD
        ]
        for p in parametros:
            if p.kind == inspect.Parameter.VAR_POSITIONAL:
                raise RuntimeError(
                    f"El __init__ de {cls.__name__} usa *args (VAR_POSITIONAL); los estimadores "
                    "Nikodym deben declarar sus hiperparámetros explícitamente (semántica sklearn)."
                )
        return sorted(p.name for p in parametros)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Devuelve los hiperparámetros como ``{nombre: valor}`` (semántica sklearn).

        Con ``deep=True``, expande los sub-estimadores anidados que tengan ``get_params`` como
        ``'<nombre>__<subclave>'``. ``_audit`` nunca aparece (no es parámetro de ``__init__``).
        """
        out: dict[str, Any] = {}
        for key in self._get_param_names():
            value = getattr(self, key)
            if deep and hasattr(value, "get_params") and not isinstance(value, type):
                for sub_key, sub_value in value.get_params().items():
                    out[f"{key}__{sub_key}"] = sub_value
            out[key] = value
        return out

    def set_params(self, **params: Any) -> Self:
        """Asigna hiperparámetros (soporta claves anidadas ``'comp__sub'``); devuelve ``self``.

        Una clave inexistente levanta :class:`~nikodym.core.exceptions.ConfigError` (no un
        ``ValueError`` crudo), con el listado de las claves válidas.
        """
        if not params:
            return self
        validos = self.get_params(deep=True)
        anidados: dict[str, dict[str, Any]] = {}
        for key, value in params.items():
            nombre, delim, sub = key.partition("__")
            if nombre not in validos:
                raise ConfigError(
                    f"Hiperparámetro '{nombre}' desconocido para {type(self).__name__}. "
                    f"Válidos: {sorted(self.get_params(deep=False))}."
                )
            if delim:
                anidados.setdefault(nombre, {})[sub] = value
            else:
                setattr(self, nombre, value)
                validos[nombre] = value
        for nombre, sub_params in anidados.items():
            objeto = validos[nombre]
            if not hasattr(objeto, "set_params"):
                raise ConfigError(
                    f"El hiperparámetro '{nombre}' de {type(self).__name__} no es un sub-estimador "
                    f"(es {type(objeto).__name__}); no admite parámetros anidados '{nombre}__...'."
                )
            objeto.set_params(**sub_params)
        return self

    @classmethod
    def from_config(cls, cfg: NikodymBaseConfig) -> Self:
        """Construye el estimador desde un sub-config, excluyendo el discriminador ``type``.

        ``type`` es la clave que el ``Registry`` usa para resolver la clase, **no** un kwarg de
        ``__init__``; excluirla evita un ``TypeError`` (``exclude={"type"}`` es no-op si no existe).
        """
        kwargs = cfg.model_dump(exclude={"type"})
        return cls(**kwargs)

    def _validate_config(self) -> None:
        """Re-valida los hiperparámetros reconstruyendo ``config_cls`` desde ``get_params``.

        Un valor fuera de rango (lo detecta Pydantic) se re-lanza como
        :class:`~nikodym.core.exceptions.ConfigError`.
        """
        try:
            self.config_cls(**self.get_params(deep=False))
        except ValidationError as exc:
            raise ConfigError(
                f"Hiperparámetros inválidos para {type(self).__name__}: {exc}"
            ) from exc

    def _check_fitted(self) -> None:
        """Levanta :class:`~nikodym.core.exceptions.NotFittedError` si el estimador no está fiteado.

        Considera fiteado al estimador si tiene al menos un atributo de instancia con sufijo ``_``
        que no empiece por ``_`` (convención sklearn de estado tras ``fit``).
        """
        fiteado = any(nombre.endswith("_") and not nombre.startswith("_") for nombre in vars(self))
        if not fiteado:
            raise NotFittedError(
                f"{type(self).__name__} no está fiteado; llame fit(...) antes de "
                "predict/transform/compute."
            )


class NikodymTransformer(AuditableMixin, BaseNikodymEstimator):
    """Familia de transformadores: contrato ``fit(X, y=None) → Self`` y ``transform(X)``.

    Los métodos los implementa cada dominio (binning, WoE, escalado…); ``core`` sólo fija el MRO.
    """


class NikodymClassifier(AuditableMixin, BaseNikodymEstimator):
    """Familia de clasificadores: contrato ``fit``/``predict``/``predict_proba``."""


class BaseForecaster(AuditableMixin, BaseNikodymEstimator):
    """Familia de *forecasters*: ``fit(y, X, fh)`` y ``predict(fh, X)``; estado ``cutoff_``."""


class BaseSurvivalEstimator(AuditableMixin, BaseNikodymEstimator):
    """Familia de supervivencia: ``y`` estructurado ``(event, time)``; produce ``S(t)``/``h(t)``."""


class BaseProvisionModel(AuditableMixin, BaseNikodymEstimator):
    """Familia de provisión: contrato ``compute(exposures) → ProvisionResultLike`` (CMF, SDD-15)."""


class BaseECLModel(BaseProvisionModel):
    """Familia ECL (IFRS 9): contrato ``compute(...) → ECLResultLike`` (SDD-16).

    Reutiliza el contrato ``compute()`` de :class:`BaseProvisionModel` (no re-mixea
    ``AuditableMixin``); la herencia expresa sólo un contrato de cálculo. CMF e IFRS 9 son motores
    separados; SDD-17 compara fuentes configurables y sólo representa el máximo B-1 para
    estándar-CMF frente a método interno bajo sus precondiciones explícitas.
    """
