"""Tests del harness público ``nikodym.testing.estimator_checks``."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Self

import numpy as np
import pytest
from pydantic import Field

from nikodym.core.audit import NullAuditSink
from nikodym.core.base import BaseNikodymEstimator, NikodymClassifier
from nikodym.core.config.schema import NikodymBaseConfig
from nikodym.testing import all_nikodym_checks, check_nikodym_estimator
from nikodym.testing.estimator_checks import (
    _call_with_neutral_args,
    _changed_value,
    _literal_values,
)


class HarnessConfig(NikodymBaseConfig):
    """Sub-config válido para dummies del harness."""

    type: Literal["harness"] = "harness"
    alpha: int = Field(default=1, ge=0, le=10)


class ValidEstimator(NikodymClassifier):
    """Estimador mínimo que cumple los nueve contratos."""

    config_cls: ClassVar[type[NikodymBaseConfig]] = HarnessConfig

    def __init__(self, alpha: int = 1) -> None:
        self.alpha = alpha

    def fit(
        self,
        x: object = None,
        y: object = None,
        *,
        rng: np.random.Generator,
    ) -> Self:
        """Valida config y materializa un atributo fiteado reproducible."""
        del x, y
        self._validate_config()
        self.coef_ = int(rng.integers(0, 2**31)) + self.alpha
        return self

    def predict(self, x: object = None) -> list[int]:
        """Devuelve una predicción mínima tras validar estado fiteado."""
        del x
        self._check_fitted()
        return [self.coef_]


def _check(name: str) -> Any:
    """Obtiene un check por nombre desde la API pública enumerada."""
    return dict(all_nikodym_checks())[name]


def test_all_nikodym_checks_enumera_los_nueve_en_orden() -> None:
    """La lista pública es cerrada y estable según SDD-24 §7.2."""
    assert [name for name, _ in all_nikodym_checks()] == [
        "check_no_logic_in_init",
        "check_get_params_mirrors_config",
        "check_set_params_roundtrip",
        "check_not_fitted_raises",
        "check_fitted_attrs_suffix",
        "check_from_config_roundtrip",
        "check_validate_config",
        "check_audit_default_null",
        "check_reproducible",
    ]


def test_check_nikodym_estimator_pasa_estimador_valido() -> None:
    """Un estimador mínimo bien formado pasa la batería completa."""
    check_nikodym_estimator(ValidEstimator())


def test_check_no_logic_in_init_falla_por_atributo_extra() -> None:
    """Contrato 1: ``__init__`` no puede crear caches o estado derivado."""

    class ExtraAttrEstimator(ValidEstimator):
        def __init__(self, alpha: int = 1) -> None:
            super().__init__(alpha)
            self.cache = "no permitido"

    with pytest.raises(AssertionError, match="atributos que no son hiperparámetros"):
        _check("check_no_logic_in_init")(ExtraAttrEstimator())


def test_check_no_logic_in_init_falla_por_parametro_con_sufijo_fiteado() -> None:
    """Contrato 1: tampoco se acepta un hiperparámetro con pinta de atributo fiteado."""

    class CoefConfig(NikodymBaseConfig):
        coef_: int = Field(default=1, ge=0)

    class FittedParamEstimator(NikodymClassifier):
        config_cls: ClassVar[type[NikodymBaseConfig]] = CoefConfig

        def __init__(self, coef_: int = 1) -> None:
            self.coef_ = coef_

    with pytest.raises(AssertionError, match="atributos fiteados"):
        _check("check_no_logic_in_init")(FittedParamEstimator())


def test_check_get_params_mirrors_config_falla_por_drift() -> None:
    """Contrato 2: campos de config e hiperparámetros deben coincidir."""

    class DriftConfig(NikodymBaseConfig):
        type: Literal["drift"] = "drift"
        alpha: int = Field(default=1, ge=0)
        beta: int = 2

    class DriftEstimator(ValidEstimator):
        config_cls: ClassVar[type[NikodymBaseConfig]] = DriftConfig

    with pytest.raises(AssertionError, match="no espeja config_cls"):
        _check("check_get_params_mirrors_config")(DriftEstimator())


def test_check_get_params_mirrors_config_falla_sin_config_cls() -> None:
    """Contrato 2: la clase debe declarar ``config_cls``."""

    class NoConfigEstimator(NikodymClassifier):
        def __init__(self, alpha: int = 1) -> None:
            self.alpha = alpha

    with pytest.raises(AssertionError, match="debe declarar config_cls"):
        _check("check_get_params_mirrors_config")(NoConfigEstimator())


def test_check_set_params_roundtrip_falla_si_no_actualiza() -> None:
    """Contrato 3: ``set_params`` debe mutar y rechazar claves inválidas."""

    class BrokenSetParams(ValidEstimator):
        def set_params(self, **params: Any) -> Self:
            del params
            return self

    with pytest.raises(AssertionError, match="no actualizó"):
        _check("check_set_params_roundtrip")(BrokenSetParams())


def test_check_set_params_roundtrip_pasa_sin_hiperparametros() -> None:
    """Contrato 3: un estimador sin params igual debe rechazar claves inválidas."""

    class ParamlessConfig(NikodymBaseConfig):
        type: Literal["paramless"] = "paramless"

    class ParamlessEstimator(NikodymClassifier):
        config_cls: ClassVar[type[NikodymBaseConfig]] = ParamlessConfig

    _check("check_set_params_roundtrip")(ParamlessEstimator())


def test_check_set_params_roundtrip_soporta_bool_float_y_str() -> None:
    """Contrato 3: el valor alternativo cubre tipos escalares comunes."""

    class ScalarConfig(NikodymBaseConfig):
        type: Literal["scalar"] = "scalar"
        enabled: bool = True
        weight: float = Field(default=0.5, ge=0.0, le=1.0)
        label: str = "base"

    class BoolEstimator(NikodymClassifier):
        config_cls: ClassVar[type[NikodymBaseConfig]] = ScalarConfig

        def __init__(self, enabled: bool = True, weight: float = 0.5, label: str = "base") -> None:
            self.enabled = enabled
            self.weight = weight
            self.label = label

    class FloatEstimator(BoolEstimator):
        def __init__(self, weight: float = 0.5, enabled: bool = True, label: str = "base") -> None:
            super().__init__(enabled=enabled, weight=weight, label=label)

    class StrEstimator(BoolEstimator):
        def __init__(self, label: str = "base", enabled: bool = True, weight: float = 0.5) -> None:
            super().__init__(enabled=enabled, weight=weight, label=label)

    _check("check_set_params_roundtrip")(BoolEstimator())
    _check("check_set_params_roundtrip")(FloatEstimator())
    _check("check_set_params_roundtrip")(StrEstimator())


def test_changed_value_cubre_escalares() -> None:
    """El helper interno produce alternativas para los escalares soportados."""
    assert _changed_value(True, "enabled") is False
    assert _changed_value(1, "alpha") == 2
    assert _changed_value(0.5, "weight") == 1.5
    assert _changed_value("base", "label") == "base-nikodym"


def test_check_set_params_roundtrip_falla_con_parametro_no_soportado() -> None:
    """Contrato 3: un hiperparámetro no escalar requiere soporte explícito."""

    class TupleConfig(NikodymBaseConfig):
        values: tuple[int, ...] = (1, 2)

    class TupleEstimator(NikodymClassifier):
        config_cls: ClassVar[type[NikodymBaseConfig]] = TupleConfig

        def __init__(self, values: tuple[int, ...] = (1, 2)) -> None:
            self.values = values

    with pytest.raises(AssertionError, match="valor alternativo simple"):
        _check("check_set_params_roundtrip")(TupleEstimator())


def test_check_set_params_roundtrip_falla_si_no_reconstruye() -> None:
    """Contrato 3: ``get_params`` debe permitir reconstruir una instancia fresca."""

    class BadFresh(ValidEstimator):
        def __init__(self, alpha: int = 1) -> None:
            if not isinstance(alpha, int):
                raise TypeError("alpha debe ser int")
            super().__init__(alpha)

        def get_params(self, deep: bool = True) -> dict[str, Any]:
            del deep
            return {"alpha": object()}

    with pytest.raises(AssertionError, match="No se pudo reconstruir"):
        _check("check_set_params_roundtrip")(BadFresh())


def test_check_set_params_roundtrip_falla_si_usa_value_error_sklearn() -> None:
    """Contrato 3: no se acepta una excepción de sklearn como error propio."""

    class SklearnValueError(ValueError):
        pass

    SklearnValueError.__module__ = "sklearn.fake"

    class SklearnErrorEstimator(ValidEstimator):
        def set_params(self, **params: Any) -> Self:
            if "__nikodym_parametro_inexistente__" in params:
                raise SklearnValueError("sklearn")
            return super().set_params(**params)

    with pytest.raises(AssertionError, match="ValueError de sklearn"):
        _check("check_set_params_roundtrip")(SklearnErrorEstimator())


def test_check_set_params_roundtrip_falla_si_no_rechaza_clave_invalida() -> None:
    """Contrato 3: una clave desconocida no puede ser un no-op silencioso."""

    class IgnoresInvalidKey(ValidEstimator):
        def set_params(self, **params: Any) -> Self:
            filtered = {key: value for key, value in params.items() if key in self.get_params()}
            return super().set_params(**filtered)

    with pytest.raises(AssertionError, match="clave inexistente"):
        _check("check_set_params_roundtrip")(IgnoresInvalidKey())


def test_check_not_fitted_raises_falla_si_predict_no_valida_estado() -> None:
    """Contrato 4: el método de salida debe llamar ``_check_fitted``."""

    class NoNotFitted(ValidEstimator):
        def predict(self, x: object = None) -> list[int]:
            del x
            return [0]

    with pytest.raises(AssertionError, match="no levantó NotFittedError"):
        _check("check_not_fitted_raises")(NoNotFitted())


def test_check_not_fitted_raises_falla_si_no_hay_metodo_salida() -> None:
    """Contrato 4: debe existir algún método de salida conocido."""

    class NoOutput(NikodymClassifier):
        config_cls: ClassVar[type[NikodymBaseConfig]] = HarnessConfig

        def __init__(self, alpha: int = 1) -> None:
            self.alpha = alpha

        def fit(self, *, rng: np.random.Generator) -> Self:
            del rng
            self.coef_ = self.alpha
            return self

    with pytest.raises(AssertionError, match="método de salida"):
        _check("check_not_fitted_raises")(NoOutput())


def test_check_not_fitted_raises_falla_si_levanta_otro_error() -> None:
    """Contrato 4: no se aceptan excepciones distintas de ``NotFittedError``."""

    class OtherError(ValidEstimator):
        def predict(self, x: object = None) -> list[int]:
            del x
            raise RuntimeError("otro")

    with pytest.raises(AssertionError, match="excepción distinta"):
        _check("check_not_fitted_raises")(OtherError())


def test_check_fitted_attrs_suffix_falla_si_fit_no_crea_estado() -> None:
    """Contrato 5: entrenar debe crear al menos un atributo ``*_``."""

    class NoFittedAttr(ValidEstimator):
        def fit(
            self,
            x: object = None,
            y: object = None,
            *,
            rng: np.random.Generator,
        ) -> Self:
            del x, y, rng
            self._validate_config()
            return self

    with pytest.raises(AssertionError, match="ningún atributo fiteado"):
        _check("check_fitted_attrs_suffix")(NoFittedAttr())


def test_check_fitted_attrs_suffix_falla_sin_fit_ni_compute() -> None:
    """Contrato 5: el estimador debe tener una entrada de entrenamiento o cálculo."""

    class NoTraining(NikodymClassifier):
        config_cls: ClassVar[type[NikodymBaseConfig]] = HarnessConfig

        def __init__(self, alpha: int = 1) -> None:
            self.alpha = alpha

        def predict(self, x: object = None) -> list[int]:
            del x
            self._check_fitted()
            return [self.alpha]

    with pytest.raises(AssertionError, match=r"fit\(\.\.\.\) o compute"):
        _check("check_fitted_attrs_suffix")(NoTraining())


def test_check_from_config_roundtrip_falla_si_from_config_cambia_params() -> None:
    """Contrato 6: ``from_config`` debe preservar los campos del sub-config."""

    class BadFromConfig(ValidEstimator):
        @classmethod
        def from_config(cls, cfg: NikodymBaseConfig) -> Self:
            del cfg
            return cls(alpha=9)

    with pytest.raises(AssertionError, match="from_config no preservó"):
        _check("check_from_config_roundtrip")(BadFromConfig())


def test_check_validate_config_falla_si_fit_no_revalida() -> None:
    """Contrato 7: ``fit`` debe llamar ``_validate_config`` y levantar ``ConfigError``."""

    class NoValidate(ValidEstimator):
        def fit(
            self,
            x: object = None,
            y: object = None,
            *,
            rng: np.random.Generator,
        ) -> Self:
            del x, y
            self.coef_ = int(rng.integers(0, 2**31))
            return self

    with pytest.raises(AssertionError, match="debe levantar ConfigError"):
        _check("check_validate_config")(NoValidate())


@pytest.mark.parametrize(
    "config_cls",
    [
        type(
            "GtConfig",
            (NikodymBaseConfig,),
            {
                "__annotations__": {
                    "type": Literal["gt"],
                    "alpha": int,
                },
                "type": "gt",
                "alpha": Field(default=1, gt=0),
            },
        ),
        type(
            "LeConfig",
            (NikodymBaseConfig,),
            {
                "__annotations__": {
                    "type": Literal["le"],
                    "alpha": int,
                },
                "type": "le",
                "alpha": Field(default=1, le=10),
            },
        ),
        type(
            "LtConfig",
            (NikodymBaseConfig,),
            {
                "__annotations__": {
                    "type": Literal["lt"],
                    "alpha": int,
                },
                "type": "lt",
                "alpha": Field(default=1, lt=10),
            },
        ),
    ],
)
def test_check_validate_config_soporta_cotas_gt_le_lt(
    config_cls: type[NikodymBaseConfig],
) -> None:
    """Contrato 7: la búsqueda de valor inválido cubre todas las cotas Pydantic usadas."""

    class BoundedEstimator(ValidEstimator):
        pass

    BoundedEstimator.config_cls = config_cls
    _check("check_validate_config")(BoundedEstimator())


def test_check_validate_config_falla_si_init_valida_rangos() -> None:
    """Contrato 7: los rangos no deben validarse en ``__init__``."""

    class InitValidates(ValidEstimator):
        def __init__(self, alpha: int = 1) -> None:
            if alpha < 0:
                raise ValueError("alpha inválido")
            super().__init__(alpha)

    with pytest.raises(AssertionError, match="__init__ no debe validar"):
        _check("check_validate_config")(InitValidates())


def test_check_validate_config_falla_si_fit_levanta_otro_error() -> None:
    """Contrato 7: un parámetro inválido debe traducirse a ``ConfigError``."""

    class OtherErrorOnInvalid(ValidEstimator):
        def fit(
            self,
            x: object = None,
            y: object = None,
            *,
            rng: np.random.Generator,
        ) -> Self:
            del x, y, rng
            if self.alpha < 0:
                raise RuntimeError("rango inválido")
            return super().fit(rng=np.random.default_rng(0))

    with pytest.raises(AssertionError, match="distinta de ConfigError"):
        _check("check_validate_config")(OtherErrorOnInvalid())


def test_check_validate_config_falla_sin_cotas() -> None:
    """Contrato 7: debe haber al menos un campo acotado para probar diferimiento."""

    class NoBoundsConfig(NikodymBaseConfig):
        type: Literal["nobounds"] = "nobounds"
        alpha: int = 1

    class NoBounds(ValidEstimator):
        config_cls: ClassVar[type[NikodymBaseConfig]] = NoBoundsConfig

    with pytest.raises(AssertionError, match="ge/gt/le/lt"):
        _check("check_validate_config")(NoBounds())


def test_check_audit_default_null_falla_si_audit_es_none() -> None:
    """Contrato 8: ``_audit`` nunca debe ser ``None``."""

    class AuditNone(ValidEstimator):
        def __init__(self, alpha: int = 1) -> None:
            super().__init__(alpha)
            self._audit = None  # type: ignore[assignment]

    with pytest.raises(AssertionError, match="NullAuditSink"):
        _check("check_audit_default_null")(AuditNone())


def test_check_audit_default_null_falla_sin_auditable_mixin() -> None:
    """Contrato 8: el estimador debe exponer ``log_decision`` vía ``AuditableMixin``."""

    class PlainEstimator(BaseNikodymEstimator):
        config_cls: ClassVar[type[NikodymBaseConfig]] = HarnessConfig
        _audit = NullAuditSink()

        def __init__(self, alpha: int = 1) -> None:
            self.alpha = alpha

    with pytest.raises(AssertionError, match="AuditableMixin"):
        _check("check_audit_default_null")(PlainEstimator())


def test_check_audit_default_null_falla_si_reclonado_pierde_null_sink() -> None:
    """Contrato 8: una instancia fresca también debe caer a ``NullAuditSink``."""

    class BadReclone(ValidEstimator):
        builds: ClassVar[int] = 0

        def __init__(self, alpha: int = 1) -> None:
            super().__init__(alpha)
            type(self).builds += 1
            if type(self).builds >= 3:
                self._audit = object()  # type: ignore[assignment]

    BadReclone.builds = 0
    estimator = BadReclone()
    with pytest.raises(AssertionError, match="instancia fresca"):
        _check("check_audit_default_null")(estimator)


def test_check_reproducible_falla_si_ignora_seed_manager() -> None:
    """Contrato 9: dos corridas con la misma semilla deben ser bit-idénticas."""

    class NonReproducible(ValidEstimator):
        counter: ClassVar[int] = 0

        def fit(
            self,
            x: object = None,
            y: object = None,
            *,
            rng: np.random.Generator,
        ) -> Self:
            del x, y, rng
            self._validate_config()
            type(self).counter += 1
            self.coef_ = type(self).counter
            return self

    NonReproducible.counter = 0
    with pytest.raises(AssertionError, match="no fueron bit-idénticas"):
        _check("check_reproducible")(NonReproducible())


def test_check_reproducible_acepta_compute_que_devuelve_resultado() -> None:
    """Contrato 9: si ``compute`` devuelve resultado, se compara directamente."""

    class ComputeConfig(NikodymBaseConfig):
        type: Literal["compute"] = "compute"
        alpha: int = Field(default=1, ge=0)

    class ComputeReturns(BaseNikodymEstimator):
        config_cls: ClassVar[type[NikodymBaseConfig]] = ComputeConfig

        def __init__(self, alpha: int = 1) -> None:
            self.alpha = alpha

        def compute(self, *, rng: np.random.Generator) -> list[int]:
            self._validate_config()
            return [int(rng.integers(0, 2**31)) + self.alpha]

    _check("check_reproducible")(ComputeReturns())


def test_call_with_neutral_args_cubre_firmas_variadas() -> None:
    """El invocador genérico cubre ``*args``, ``**kwargs``, rng posicional y kwargs requeridos."""

    def varargs(*args: object, **kwargs: object) -> tuple[tuple[object, ...], dict[str, object]]:
        return args, kwargs

    def positional_rng(rng: np.random.Generator) -> bool:
        return isinstance(rng, np.random.Generator)

    def required_args(value: object, *, label: object) -> tuple[object, object]:
        return value, label

    assert _call_with_neutral_args(varargs) == ((), {})
    assert _call_with_neutral_args(positional_rng, rng=np.random.default_rng(0)) is True
    assert _call_with_neutral_args(required_args) == (None, None)


def test_literal_values_extrae_solo_literal() -> None:
    """Helper interno: ``Literal`` produce valores; otros tipos producen tupla vacía."""
    assert _literal_values(Literal["x", 1]) == ("x", 1)
    assert _literal_values(int) == ()
