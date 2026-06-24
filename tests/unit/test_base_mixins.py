"""Tests de ``core.base`` y ``core.mixins`` (SDD-01 §4).

Cubren la semántica sklearn de ``get_params``/``set_params``, ``from_config`` (excluye ``type``),
``_validate_config``, ``_check_fitted`` (D-CORE-5: no es la NotFittedError de sklearn), el MRO de
las familias, el ``AuditableMixin`` (``_audit`` nunca ``None``, ``log_decision``) y el
``SerializationMixin`` (round-trip joblib + puerta ``trust``). El invariante SDD-24 §7.2 se verifica
explícitamente.
"""

from __future__ import annotations

import pytest
from pydantic import Field

from nikodym.core.audit import InMemoryAuditSink, NullAuditSink
from nikodym.core.base import (
    BaseECLModel,
    BaseNikodymEstimator,
    BaseProvisionModel,
    NikodymClassifier,
    NikodymTransformer,
)
from nikodym.core.config.schema import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, NikodymError, NotFittedError, UntrustedStudyError
from nikodym.core.mixins import AuditableMixin, SerializationMixin

# --- Dummies a nivel de módulo (picklables para los tests de save/load) -----------------------


class DummyEstimator(BaseNikodymEstimator):
    """Estimador mínimo con dos hiperparámetros."""

    def __init__(self, a: int = 1, b: int = 2) -> None:
        self.a = a
        self.b = b


class MetaEstimator(BaseNikodymEstimator):
    """Estimador con un sub-estimador anidado (para ``get_params(deep=True)``)."""

    def __init__(self, comp: object = None) -> None:
        self.comp = comp


class VarArgsEstimator(BaseNikodymEstimator):
    """Estimador inválido: ``__init__`` con ``*args`` (debe rechazarse)."""

    def __init__(self, *args: object) -> None:
        self.args = args


class DummyConfig(NikodymBaseConfig):
    """Sub-config con discriminador ``type`` y un campo restringido."""

    type: str = "dummy"
    alpha: int = Field(default=1, ge=0)
    beta: int = 2


class ConfiguredEstimator(BaseNikodymEstimator):
    """Estimador con ``config_cls`` que espeja sus hiperparámetros (invariante SDD-24 §7.2)."""

    config_cls = DummyConfig

    def __init__(self, alpha: int = 1, beta: int = 2) -> None:
        self.alpha = alpha
        self.beta = beta


class SaveableEstimator(SerializationMixin, BaseNikodymEstimator):
    """Estimador serializable para el round-trip de ``SerializationMixin``."""

    def __init__(self, a: int = 1) -> None:
        self.a = a


class OtherSaveable(SerializationMixin, BaseNikodymEstimator):
    """Otra clase serializable, para verificar el rechazo por clase incorrecta."""


# --- get_params / set_params ------------------------------------------------------------------


def test_get_params_introspecta_init_ordenado() -> None:
    """``get_params`` devuelve los hiperparámetros de ``__init__`` ordenados; sin ``_audit``."""
    params = DummyEstimator(a=3, b=4).get_params()
    assert params == {"a": 3, "b": 4}
    assert "_audit" not in params


def test_get_params_deep_expande_anidados() -> None:
    """``deep=True`` expande el sub-estimador como ``comp__<sub>``; ``deep=False`` no."""
    meta = MetaEstimator(comp=DummyEstimator(a=7, b=8))
    deep = meta.get_params(deep=True)
    assert deep["comp__a"] == 7
    assert deep["comp__b"] == 8
    assert "comp__a" not in meta.get_params(deep=False)


def test_get_params_rechaza_var_positional() -> None:
    """``*args`` en ``__init__`` levanta ``RuntimeError`` (semántica sklearn)."""
    with pytest.raises(RuntimeError, match="VAR_POSITIONAL"):
        VarArgsEstimator().get_params()


def test_set_params_muta_y_devuelve_self() -> None:
    """``set_params`` asigna y devuelve ``self``."""
    est = DummyEstimator()
    assert est.set_params(b=9) is est
    assert est.b == 9


def test_set_params_clave_invalida_es_config_error() -> None:
    """Una clave inexistente levanta ``ConfigError`` con las claves válidas, no ``ValueError``."""
    with pytest.raises(ConfigError, match="'noexiste'"):
        DummyEstimator().set_params(noexiste=1)


def test_get_params_sin_init_propio_es_vacio() -> None:
    """Una familia sin ``__init__`` propio (object.__init__) devuelve ``{}``."""
    assert NikodymClassifier().get_params() == {}


def test_set_params_vacio_devuelve_self() -> None:
    """``set_params()`` sin argumentos devuelve ``self`` sin cambios (atajo)."""
    est = DummyEstimator(a=1, b=2)
    assert est.set_params() is est
    assert est.get_params() == {"a": 1, "b": 2}


def test_set_params_clave_anidada() -> None:
    """``set_params(comp__a=...)`` propaga al sub-estimador anidado (semántica sklearn)."""
    sub = DummyEstimator(a=1, b=2)
    meta = MetaEstimator(comp=sub)
    assert meta.set_params(comp__a=99) is meta
    assert sub.a == 99


def test_set_params_anidado_sobre_no_estimador_es_config_error() -> None:
    """Clave anidada sobre un parámetro no-estimador → ``ConfigError`` (no AttributeError crudo)."""
    meta = MetaEstimator(comp=5)  # un int, sin set_params
    with pytest.raises(ConfigError, match="no es un sub-estimador"):
        meta.set_params(comp__a=1)


# --- from_config / _validate_config / invariante 7.2 ------------------------------------------


def test_from_config_excluye_type() -> None:
    """``from_config`` construye el estimador excluyendo el discriminador ``type``."""
    est = ConfiguredEstimator.from_config(DummyConfig(alpha=5))
    assert est.alpha == 5
    assert est.beta == 2


def test_from_config_sin_type_es_no_op() -> None:
    """``exclude={'type'}`` es no-op si el sub-config no tiene ``type``."""

    class SinTypeConfig(NikodymBaseConfig):
        alpha: int = 1

    est = ConfiguredEstimator.from_config(SinTypeConfig(alpha=4))
    assert est.alpha == 4


def test_invariante_get_params_vs_model_fields() -> None:
    """SDD-24 §7.2: ``set(get_params()) == set(config_cls.model_fields) - {'type'}``."""
    est = ConfiguredEstimator()
    assert set(est.get_params()) == set(est.config_cls.model_fields) - {"type"}


def test_validate_config_revalida_y_lanza_config_error() -> None:
    """``_validate_config`` reconstruye ``config_cls`` y re-lanza ``ConfigError`` si está mal."""
    est = ConfiguredEstimator()
    est._validate_config()  # alpha=1 válido, no levanta
    est.alpha = -1  # viola ge=0
    with pytest.raises(ConfigError):
        est._validate_config()


# --- _check_fitted ----------------------------------------------------------------------------


def test_check_fitted_sin_estado_levanta() -> None:
    """Sin atributo con sufijo ``_``, ``_check_fitted`` levanta ``NotFittedError``."""
    with pytest.raises(NotFittedError, match="no está fiteado"):
        DummyEstimator()._check_fitted()


def test_check_fitted_con_estado_no_levanta() -> None:
    """Tras setear un atributo ``coef_``, ``_check_fitted`` no levanta."""
    est = DummyEstimator()
    est.coef_ = [1.0, 2.0]  # type: ignore[attr-defined]
    est._check_fitted()


def test_not_fitted_error_no_desciende_de_sklearn() -> None:
    """D-CORE-5: ``NotFittedError`` desciende de ``NikodymError`` y de nada de sklearn."""
    assert issubclass(NotFittedError, NikodymError)
    assert all("sklearn" not in cls.__module__ for cls in NotFittedError.__mro__)


# --- MRO de las familias ----------------------------------------------------------------------


def test_mro_auditable_primero() -> None:
    """En el MRO de las familias, ``AuditableMixin`` precede a ``BaseNikodymEstimator``."""
    mro = NikodymTransformer.__mro__
    assert mro.index(AuditableMixin) < mro.index(BaseNikodymEstimator)


def test_familias_son_estimadores_y_auditables() -> None:
    """Las familias son ``BaseNikodymEstimator`` y ``AuditableMixin``; ECL reutiliza Provision."""
    assert isinstance(NikodymClassifier(), BaseNikodymEstimator)
    assert isinstance(NikodymClassifier(), AuditableMixin)
    assert issubclass(BaseECLModel, BaseProvisionModel)


# --- AuditableMixin ---------------------------------------------------------------------------


def test_audit_default_es_null_sink_no_none() -> None:
    """``_audit`` por defecto es ``NullAuditSink`` (nunca ``None``); ``log_decision`` no levanta."""
    est = NikodymClassifier()
    assert isinstance(est._audit, NullAuditSink)
    est.log_decision(regla="iv", umbral=0.02, valor=0.01, accion="descartó")


def test_log_decision_emite_evento_decision() -> None:
    """``log_decision`` emite un único ``AuditEvent`` ``decision`` con las 4 claves del payload."""
    est = NikodymClassifier()
    sink = InMemoryAuditSink()
    est._audit = sink
    est.log_decision(regla="max_iv", umbral=0.02, valor=0.015, accion="descartó")
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.kind == "decision"
    assert ev.step is None
    assert ev.payload == {
        "regla": "max_iv",
        "umbral": 0.02,
        "valor": 0.015,
        "accion": "descartó",
    }


def test_log_decision_exige_kwargs() -> None:
    """``log_decision`` sólo admite argumentos por palabra clave."""
    with pytest.raises(TypeError):
        NikodymClassifier().log_decision("iv", 0.02, 0.01, "descartó")  # type: ignore[misc]


# --- SerializationMixin -----------------------------------------------------------------------


def test_save_load_round_trip(tmp_path: object) -> None:
    """``save`` + ``load(trust=True)`` reconstruye un estimador equivalente."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    path = tmp_path / "est.joblib"
    SaveableEstimator(a=42).save(path)
    cargado = SaveableEstimator.load(path, trust=True)
    assert cargado.a == 42


def test_load_sin_trust_rechaza(tmp_path: object) -> None:
    """``load(trust=False)`` rechaza el origen no verificado (vector pickle)."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    path = tmp_path / "est.joblib"
    SaveableEstimator(a=1).save(path)
    with pytest.raises(UntrustedStudyError, match="trust=True"):
        SaveableEstimator.load(path)


def test_load_clase_incorrecta_es_config_error(tmp_path: object) -> None:
    """Cargar con la clase equivocada levanta ``ConfigError``."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    path = tmp_path / "est.joblib"
    SaveableEstimator(a=1).save(path)
    with pytest.raises(ConfigError, match="no es un OtherSaveable"):
        OtherSaveable.load(path, trust=True)
