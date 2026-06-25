"""Batería pública de contrato para estimadores propios de Nikodym (SDD-24).

El harness cubre las familias que heredan de :class:`nikodym.core.base.BaseNikodymEstimator` y no
necesariamente de ``sklearn.base.BaseEstimator``. Es deliberadamente pequeño: valida los nueve
invariantes cerrados por SDD-24 y levanta ``AssertionError`` con mensajes en español para que el
autor del estimador vea qué contrato rompió.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Literal, cast, get_args, get_origin

import numpy as np

from nikodym.core.audit import NullAuditSink
from nikodym.core.base import BaseNikodymEstimator
from nikodym.core.config.schema import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError, NotFittedError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.seeding import SeedManager

__all__ = ["all_nikodym_checks", "check_nikodym_estimator"]

Check = Callable[[BaseNikodymEstimator], None]
_OUTPUT_METHODS: tuple[str, ...] = (
    "predict",
    "compute",
    "predict_survival_function",
    "transform",
    "predict_proba",
)
_TRAINING_METHODS: tuple[str, ...] = ("fit", "compute")


def check_nikodym_estimator(estimator: BaseNikodymEstimator) -> None:
    """Ejecuta los nueve checks de contrato Nikodym sobre ``estimator``.

    Parameters
    ----------
    estimator : BaseNikodymEstimator
        Instancia fresca del estimador a validar.

    Raises
    ------
    AssertionError
        Si se viola la primera invariante de la batería.
    """
    for _name, check in all_nikodym_checks():
        check(estimator)


def all_nikodym_checks() -> list[tuple[str, Check]]:
    """Enumera los nueve checks Nikodym como pares ``(nombre, callable)`` materializados."""
    return [
        ("check_no_logic_in_init", _check_no_logic_in_init),
        ("check_get_params_mirrors_config", _check_get_params_mirrors_config),
        ("check_set_params_roundtrip", _check_set_params_roundtrip),
        ("check_not_fitted_raises", _check_not_fitted_raises),
        ("check_fitted_attrs_suffix", _check_fitted_attrs_suffix),
        ("check_from_config_roundtrip", _check_from_config_roundtrip),
        ("check_validate_config", _check_validate_config),
        ("check_audit_default_null", _check_audit_default_null),
        ("check_reproducible", _check_reproducible),
    ]


def _fresh(estimator: BaseNikodymEstimator) -> BaseNikodymEstimator:
    """Reconstruye una instancia fresca desde los hiperparámetros públicos."""
    cls = type(estimator)
    params = estimator.get_params(deep=False)
    try:
        return cls(**params)
    except Exception as exc:
        raise AssertionError(
            f"No se pudo reconstruir {cls.__name__} desde get_params(): {exc!r}."
        ) from exc


def _check_no_logic_in_init(estimator: BaseNikodymEstimator) -> None:
    """``__init__`` solo debe asignar hiperparámetros públicos."""
    params = set(estimator.get_params(deep=False))
    attrs = set(vars(estimator))
    extras = attrs - params
    fitted = sorted(name for name in attrs if name.endswith("_") and not name.startswith("_"))
    if extras:
        raise AssertionError(
            "check_no_logic_in_init: __init__ creó atributos que no son hiperparámetros "
            f"públicos: {sorted(extras)}."
        )
    if fitted:
        raise AssertionError(
            "check_no_logic_in_init: __init__ no debe crear atributos fiteados con sufijo '_'; "
            f"observados: {fitted}."
        )


def _config_cls(estimator: BaseNikodymEstimator) -> type[NikodymBaseConfig]:
    """Obtiene ``config_cls`` validando que sea un sub-config Nikodym."""
    config_cls = getattr(type(estimator), "config_cls", None)
    if not isinstance(config_cls, type) or not issubclass(config_cls, NikodymBaseConfig):
        raise AssertionError(
            "check_get_params_mirrors_config: el estimador debe declarar config_cls como "
            "subclase de NikodymBaseConfig."
        )
    return config_cls


def _expected_param_names(config_cls: type[NikodymBaseConfig]) -> set[str]:
    """Campos de config que deben espejarse en ``get_params``."""
    return set(config_cls.model_fields) - {"type"}


def _check_get_params_mirrors_config(estimator: BaseNikodymEstimator) -> None:
    """``get_params`` debe espejar los campos del sub-config, salvo ``type``."""
    config_cls = _config_cls(estimator)
    expected = _expected_param_names(config_cls)
    observed = set(estimator.get_params(deep=False)) - {"_audit"}
    if observed != expected:
        raise AssertionError(
            "check_get_params_mirrors_config: get_params(deep=False) no espeja config_cls. "
            f"Esperado={sorted(expected)}, observado={sorted(observed)}."
        )


def _changed_value(value: Any, field: str) -> Any:
    """Devuelve un valor alternativo simple para probar ``set_params``."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int) and not isinstance(value, bool):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, str):
        return f"{value}-nikodym"
    raise AssertionError(
        "check_set_params_roundtrip: no hay valor alternativo simple para el hiperparámetro "
        f"'{field}' de tipo {type(value).__name__}."
    )


def _check_set_params_roundtrip(estimator: BaseNikodymEstimator) -> None:
    """``set_params`` debe mutar hiperparámetros válidos y rechazar claves desconocidas."""
    clone = _fresh(estimator)
    params = clone.get_params(deep=False)
    if params:
        key = next(iter(params))
        new_value = _changed_value(params[key], key)
        clone.set_params(**{key: new_value})
        observed = clone.get_params(deep=False)[key]
        if observed != new_value:
            raise AssertionError(
                "check_set_params_roundtrip: set_params no actualizó el hiperparámetro "
                f"'{key}'. Esperado={new_value!r}, observado={observed!r}."
            )
    try:
        clone.set_params(__nikodym_parametro_inexistente__=1)
    except (ConfigError, ValueError) as exc:
        if type(exc).__module__.startswith("sklearn"):
            raise AssertionError(
                "check_set_params_roundtrip: la clave inválida levantó un ValueError de sklearn, "
                "no una excepción propia de Nikodym."
            ) from exc
    else:
        raise AssertionError(
            "check_set_params_roundtrip: una clave inexistente debe levantar ConfigError o "
            "ValueError propio."
        )


def _call_with_neutral_args(
    method: Callable[..., Any],
    *,
    rng: np.random.Generator | None = None,
) -> Any:
    """Invoca ``method`` rellenando argumentos requeridos con valores neutros."""
    kwargs: dict[str, Any] = {}
    args: list[Any] = []
    for param in inspect.signature(method).parameters.values():
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        if param.name == "rng" and rng is not None:
            if param.kind is inspect.Parameter.KEYWORD_ONLY:
                kwargs[param.name] = rng
            else:
                args.append(rng)
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        value: Any = None
        if param.kind is inspect.Parameter.KEYWORD_ONLY:
            kwargs[param.name] = value
        else:
            args.append(value)
    return method(*args, **kwargs)


def _output_method(estimator: BaseNikodymEstimator) -> Callable[..., Any]:
    """Selecciona el primer método de salida conocido que expone el estimador."""
    for name in _OUTPUT_METHODS:
        method = getattr(estimator, name, None)
        if callable(method):
            return cast(Callable[..., Any], method)
    raise AssertionError(
        "check_not_fitted_raises: el estimador debe exponer un método de salida "
        f"entre {_OUTPUT_METHODS}."
    )


def _training_method(estimator: BaseNikodymEstimator) -> Callable[..., Any]:
    """Selecciona ``fit`` o ``compute`` como método que materializa estado."""
    for name in _TRAINING_METHODS:
        method = getattr(estimator, name, None)
        if callable(method):
            return cast(Callable[..., Any], method)
    raise AssertionError(
        "check_fitted_attrs_suffix: el estimador debe exponer fit(...) o compute(...)."
    )


def _check_not_fitted_raises(estimator: BaseNikodymEstimator) -> None:
    """El método de salida debe levantar ``NotFittedError`` antes de entrenar/calcular."""
    fresh = _fresh(estimator)
    method = _output_method(fresh)
    try:
        _call_with_neutral_args(method)
    except NotFittedError:
        return
    except Exception as exc:
        raise AssertionError(
            "check_not_fitted_raises: el método de salida levantó una excepción distinta de "
            f"NotFittedError: {type(exc).__name__}: {exc}."
        ) from exc
    raise AssertionError(
        "check_not_fitted_raises: el método de salida no levantó NotFittedError antes de "
        "fit/compute."
    )


def _fitted_attrs(estimator: BaseNikodymEstimator) -> set[str]:
    """Atributos de instancia fiteados según la convención de sufijo ``_``."""
    return {name for name in vars(estimator) if name.endswith("_") and not name.startswith("_")}


def _check_fitted_attrs_suffix(estimator: BaseNikodymEstimator) -> None:
    """Tras ``fit``/``compute`` debe aparecer al menos un atributo nuevo con sufijo ``_``."""
    fresh = _fresh(estimator)
    before = _fitted_attrs(fresh)
    _call_with_neutral_args(
        _training_method(fresh),
        rng=SeedManager(42).generator_for(type(fresh).__name__),
    )
    added = _fitted_attrs(fresh) - before
    if not added:
        raise AssertionError(
            "check_fitted_attrs_suffix: fit/compute no creó ningún atributo fiteado nuevo "
            "con sufijo '_'."
        )


def _check_from_config_roundtrip(estimator: BaseNikodymEstimator) -> None:
    """``from_config(config_cls(**params))`` debe reconstruir los mismos hiperparámetros."""
    config_cls = _config_cls(estimator)
    params = estimator.get_params(deep=False)
    sub_cfg = config_cls(**params)
    rebuilt = type(estimator).from_config(sub_cfg)
    observed = rebuilt.get_params(deep=False)
    if observed != params:
        raise AssertionError(
            "check_from_config_roundtrip: from_config no preservó los hiperparámetros. "
            f"Esperado={params!r}, observado={observed!r}."
        )


def _literal_values(annotation: Any) -> tuple[Any, ...]:
    """Extrae valores ``Literal`` de una anotación si aplica."""
    if get_origin(annotation) is Literal:
        return get_args(annotation)
    return ()


def _constraint_value(metadata: list[Any], name: str) -> Any:
    """Lee una cota Pydantic/annotated-types desde ``FieldInfo.metadata``."""
    for item in metadata:
        value = getattr(item, name, None)
        if value is not None:
            return value
    return None


def _invalid_value_for_config(config_cls: type[NikodymBaseConfig]) -> tuple[str, Any]:
    """Encuentra un campo con cota y devuelve un valor inválido para forzar ``ConfigError``."""
    for name, field in config_cls.model_fields.items():
        if name == "type" or _literal_values(field.annotation):
            continue
        metadata = list(field.metadata)
        ge = _constraint_value(metadata, "ge")
        if ge is not None:
            return name, ge - 1
        gt = _constraint_value(metadata, "gt")
        if gt is not None:
            return name, gt
        le = _constraint_value(metadata, "le")
        if le is not None:
            return name, le + 1
        lt = _constraint_value(metadata, "lt")
        if lt is not None:
            return name, lt
    raise AssertionError(
        "check_validate_config: config_cls debe tener al menos un hiperparámetro con ge/gt/le/lt "
        "para probar validación diferida."
    )


def _check_validate_config(estimator: BaseNikodymEstimator) -> None:
    """La validación de config debe ocurrir en ``fit``/``compute``, no en ``__init__``."""
    config_cls = _config_cls(estimator)
    fresh = _fresh(estimator)
    fresh._validate_config()
    field, invalid = _invalid_value_for_config(config_cls)
    params = estimator.get_params(deep=False) | {field: invalid}
    try:
        invalid_estimator = type(estimator)(**params)
    except Exception as exc:
        raise AssertionError(
            "check_validate_config: __init__ no debe validar rangos del config; debe diferirlo a "
            f"fit/compute. Excepción observada: {type(exc).__name__}: {exc}."
        ) from exc
    try:
        _call_with_neutral_args(
            _training_method(invalid_estimator),
            rng=SeedManager(42).generator_for(type(invalid_estimator).__name__),
        )
    except ConfigError:
        return
    except Exception as exc:
        raise AssertionError(
            "check_validate_config: fit/compute levantó una excepción distinta de ConfigError "
            f"para un hiperparámetro inválido: {type(exc).__name__}: {exc}."
        ) from exc
    raise AssertionError(
        "check_validate_config: fit/compute debe levantar ConfigError al revalidar un "
        "hiperparámetro fuera de rango."
    )


def _check_audit_default_null(estimator: BaseNikodymEstimator) -> None:
    """El sink de auditoría por defecto debe ser ``NullAuditSink`` y nunca ``None``."""
    fresh = _fresh(estimator)
    audit = getattr(fresh, "_audit", None)
    if not isinstance(audit, NullAuditSink):
        raise AssertionError(
            "check_audit_default_null: _audit por defecto debe ser NullAuditSink, "
            f"observado={type(audit).__name__}."
        )
    if not isinstance(fresh, AuditableMixin):
        raise AssertionError(
            "check_audit_default_null: el estimador debe heredar de AuditableMixin para "
            "log_decision(...)."
        )
    fresh.log_decision(regla="testing", umbral=0, valor=0, accion="sin_efecto")
    recloned = _fresh(fresh)
    if not isinstance(getattr(recloned, "_audit", None), NullAuditSink):
        raise AssertionError(
            "check_audit_default_null: una instancia fresca debe caer nuevamente a NullAuditSink."
        )


def _result_after_training(estimator: BaseNikodymEstimator, name: str) -> Any:
    """Entrena/calcula con una semilla derivada y devuelve una salida comparable."""
    result = _call_with_neutral_args(
        _training_method(estimator),
        rng=SeedManager(42).generator_for(name),
    )
    if result is not None and result is not estimator:
        return result
    return _call_with_neutral_args(_output_method(estimator))


def _bitwise_payload(value: Any) -> bytes:
    """Serializa valores comunes a bytes deterministas para comparar reproducibilidad."""
    import pickle

    return pickle.dumps(value, protocol=5)


def _check_reproducible(estimator: BaseNikodymEstimator) -> None:
    """Dos corridas con el mismo ``SeedManager`` deben devolver salida bit-idéntica."""
    first = _fresh(estimator)
    second = _fresh(estimator)
    name = type(estimator).__name__
    first_result = _result_after_training(first, name)
    second_result = _result_after_training(second, name)
    if _bitwise_payload(first_result) != _bitwise_payload(second_result):
        raise AssertionError(
            "check_reproducible: dos corridas con la misma semilla no fueron bit-idénticas. "
            f"Primera={first_result!r}, segunda={second_result!r}."
        )
