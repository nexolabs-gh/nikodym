"""Tests de ``MarkovConfig`` (SDD-19 §5) e integración con ``NikodymConfig``."""

from __future__ import annotations

import math
import subprocess
import sys

import pytest
import yaml
from pydantic import ValidationError

import nikodym.markov as markov_pkg  # importa la capa: puebla el hook
from nikodym.core import study as study_module
from nikodym.core.config import INFRA_SECTIONS, NikodymConfig, config_hash
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.markov.config import (
    MarkovConfig,
    MarkovDynamicsConfig,
    MarkovEstimationConfig,
    MarkovInputConfig,
    MarkovStateConfig,
    MarkovValidationConfig,
)
from nikodym.markov.exceptions import (
    InvalidGeneratorError,
    MarkovConfigError,
    MarkovEmbeddingError,
    MarkovError,
    MarkovFitError,
    MarkovInputError,
    MarkovTransformError,
    NonStochasticMatrixError,
)
from nikodym.testing.strategies import _config_cls_for_domain

GOLDEN_DEFAULT_CONFIG_HASH = "0e1016e38154a09a93e3e4b1a551b71afa06b257b58f6081ce2f4e24fb4e4c69"


@pytest.fixture(autouse=True)
def _capa_markov_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_MARKOV_CONFIG_CLS", MarkovConfig)


def _input(**overrides: object) -> MarkovInputConfig:
    """Config de entrada mínima válida para Markov."""
    data: dict[str, object] = {
        "id_col": "account_id",
        "time_col": "period",
        "state_col": "state",
    }
    data.update(overrides)
    return MarkovInputConfig.model_validate(data)


def _states(**overrides: object) -> MarkovStateConfig:
    """Config de estados mínima válida para Markov."""
    data: dict[str, object] = {"states": ("current", "delinquent", "default")}
    data.update(overrides)
    return MarkovStateConfig.model_validate(data)


def _markov_config_minimo(**overrides: object) -> MarkovConfig:
    """Config Markov mínimo válido con taxonomía explícita."""
    data: dict[str, object] = {"input": _input(), "states": _states()}
    data.update(overrides)
    return MarkovConfig.model_validate(data)


def test_markovconfig_defaults_golden() -> None:
    """``MarkovConfig`` por defecto coincide bit a bit con el golden defendible."""
    assert MarkovConfig().model_dump(mode="json") == {
        "schema_version": "1.0.0",
        "type": "standard",
        "input": {
            "id_col": "id",
            "time_col": "time",
            "state_col": "state",
            "segment_col": None,
            "partition_col": "partition",
            "weight_col": None,
            "exposure_time_col": None,
            "transition_time_col": None,
        },
        "states": {
            "states": ["performing", "default"],
            "default_state": "default",
            "absorbing_states": ["default"],
            "allow_unknown_states": False,
        },
        "estimation": {
            "method": "cohort",
            "interval": 1.0,
            "use_weights": False,
            "min_origin_count": 1,
        },
        "dynamics": {
            "projection_mode": "homogeneous",
            "time_unit": "period",
            "horizon_periods": [1, 2, 3, 4, 5],
            "evaluation_times": [],
            "embedding_policy": "diagnose",
        },
        "validation": {
            "stochastic_tol": 1e-10,
            "generator_tol": 1e-10,
            "imaginary_tol": 1e-10,
            "normalize_within_tolerance": True,
            "fail_on_missing_periods": True,
        },
        "fail_on_falta_dato": True,
    }


def test_round_trip_yaml_markovconfig() -> None:
    """Serializar y recargar ``MarkovConfig`` por YAML preserva igualdad exacta."""
    cfg = MarkovConfig(
        input=MarkovInputConfig(
            id_col="rut",
            time_col="fecha_cierre",
            state_col="rating",
            segment_col="segmento",
            partition_col="split",
            weight_col="exposicion",
            exposure_time_col="tiempo_riesgo",
            transition_time_col="fecha_transicion",
        ),
        states=MarkovStateConfig(
            states=("A", "B", "default", "prepaid"),
            absorbing_states=("default", "prepaid"),
        ),
        estimation=MarkovEstimationConfig(method="duration", interval=0.5, use_weights=True),
        dynamics=MarkovDynamicsConfig(
            projection_mode="aalen_johansen",
            time_unit="month",
            horizon_periods=(1, 3, 6, 12),
            evaluation_times=(0.5, 1.0, 2.0),
            embedding_policy="regularize",
        ),
        validation=MarkovValidationConfig(
            stochastic_tol=1e-9,
            generator_tol=1e-9,
            imaginary_tol=1e-9,
            normalize_within_tolerance=False,
            fail_on_missing_periods=False,
        ),
        fail_on_falta_dato=False,
    )
    text = yaml.safe_dump(cfg.model_dump(mode="json", by_alias=True), sort_keys=False)
    raw = yaml.safe_load(text)
    assert MarkovConfig.model_validate(raw) == cfg


def test_nikodymconfig_markov_instancia() -> None:
    """Pasar una instancia ``MarkovConfig`` a ``NikodymConfig`` la conserva."""
    markov = _markov_config_minimo()
    cfg = NikodymConfig(markov=markov)
    assert isinstance(cfg.markov, MarkovConfig)
    assert cfg.markov is markov


def test_nikodymconfig_markov_dict_coacciona() -> None:
    """Un dict en ``markov`` se coacciona a ``MarkovConfig`` por el hook cargado."""
    cfg = NikodymConfig(
        markov={
            "input": {"id_col": "id", "time_col": "periodo", "state_col": "estado"},
            "states": {"states": ["A", "B", "default"]},
            "dynamics": {"embedding_policy": "forbid"},
        }
    )
    assert isinstance(cfg.markov, MarkovConfig)
    assert cfg.markov.input.time_col == "periodo"
    assert cfg.markov.dynamics.embedding_policy == "forbid"


def test_nikodymconfig_markov_none_explicito() -> None:
    """``markov=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(markov=None).markov is None


def test_nikodymconfig_markov_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``markov`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_MARKOV_CONFIG_CLS", None)
    cfg = NikodymConfig(markov={"states": {"states": ["A", "default"]}})
    assert cfg.markov == {"states": {"states": ["A", "default"]}}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_markov_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``markov`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_MARKOV_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(markov=blob)


def test_config_hash_cambia_al_variar_method() -> None:
    """``markov.estimation.method`` es computacional y cambia identidad."""
    base = config_hash(NikodymConfig(markov=_markov_config_minimo()))
    variado = config_hash(
        NikodymConfig(
            markov=_markov_config_minimo(
                input=_input(exposure_time_col="tiempo_riesgo"),
                estimation=MarkovEstimationConfig(method="duration"),
            )
        )
    )
    assert variado != base


def test_config_hash_cambia_al_variar_projection_mode() -> None:
    """``markov.dynamics.projection_mode`` es computacional y cambia identidad."""
    base = config_hash(NikodymConfig(markov=_markov_config_minimo()))
    variado = config_hash(
        NikodymConfig(
            markov=_markov_config_minimo(
                dynamics=MarkovDynamicsConfig(projection_mode="period_matrices")
            )
        )
    )
    assert variado != base


def test_config_hash_cambia_al_variar_embedding_policy() -> None:
    """``markov.dynamics.embedding_policy`` es computacional y cambia identidad."""
    base = config_hash(NikodymConfig(markov=_markov_config_minimo()))
    variado = config_hash(
        NikodymConfig(
            markov=_markov_config_minimo(dynamics=MarkovDynamicsConfig(embedding_policy="forbid"))
        )
    )
    assert variado != base


def test_config_hash_cambia_al_variar_estados() -> None:
    """``markov.states`` es computacional y cambia identidad."""
    base = config_hash(NikodymConfig(markov=_markov_config_minimo()))
    variado = config_hash(
        NikodymConfig(markov=_markov_config_minimo(states=_states(states=("A", "B", "default"))))
    )
    assert variado != base


def test_config_hash_cambia_al_variar_horizonte() -> None:
    """``markov.dynamics.horizon_periods`` es computacional y cambia identidad."""
    base = config_hash(NikodymConfig(markov=_markov_config_minimo()))
    variado = config_hash(
        NikodymConfig(
            markov=_markov_config_minimo(
                dynamics=MarkovDynamicsConfig(horizon_periods=(1, 2, 3, 6))
            )
        )
    )
    assert variado != base


def test_config_hash_cambia_al_variar_tolerancia() -> None:
    """``markov.validation.stochastic_tol`` es computacional y cambia identidad."""
    base = config_hash(NikodymConfig(markov=_markov_config_minimo()))
    variado = config_hash(
        NikodymConfig(
            markov=_markov_config_minimo(validation=MarkovValidationConfig(stochastic_tol=1e-9))
        )
    )
    assert variado != base


def test_config_hash_default_con_markov_none_golden() -> None:
    """El hash por defecto incorpora la nueva clave computacional ``markov=None``."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_markov_no_es_infra_section() -> None:
    """``markov`` entra al ``config_hash`` global."""
    assert "markov" not in INFRA_SECTIONS


def test_config_cls_for_domain_resuelve_markov() -> None:
    """El helper interno resuelve ``MarkovConfig`` cuando el hook está poblado."""
    assert _config_cls_for_domain("markov") is MarkovConfig


def test_core_study_cablea_markov_en_orden_por_defecto() -> None:
    """``Study`` conoce ``markov`` después de datos y antes de provisiones CMF."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("data") < order.index("markov") < order.index("provisioning_cmf")
    assert study_module._DOMAIN_MODULES["markov"] == "nikodym.markov"
    assert study_module._DOMAIN_CONFIG_CLASSES["markov"] == (
        "nikodym.markov.config",
        "MarkovConfig",
    )


def test_import_markov_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.markov`` registra hook sin arrastrar scipy ni pandas."""
    code = (
        "import nikodym.markov, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.markov.config import MarkovConfig;"
        "bloqueados=[m for m in ('scipy','pandas') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "assert 'nikodym.markov.step' in sys.modules;"
        "assert 'nikodym.markov.transition' not in sys.modules;"
        "cfg=NikodymConfig(markov={'states': {'states': ['A', 'default']}});"
        "assert isinstance(cfg.markov, MarkovConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_markov_como_blob_opaco_sin_importar_markov() -> None:
    """El core acepta ``markov`` JSON/dict sin importar la capa Markov."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "assert 'nikodym.markov' not in sys.modules;"
        "cfg=NikodymConfig(markov={'states': {'states': ['A', 'default']}});"
        "assert cfg.markov == {'states': {'states': ['A', 'default']}};"
        "assert 'nikodym.markov' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_lazy_exports_markov(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los exports futuros se cargan bajo demanda y los nombres desconocidos fallan limpio."""

    class DummyModule:
        """Módulo mínimo para simular el futuro ``transition.py``."""

        TransitionMatrixEstimator = object()

    def fake_import_module(name: str) -> type[DummyModule]:
        """Simula import perezoso sin crear el módulo futuro."""
        assert name == "nikodym.markov.transition"
        return DummyModule

    monkeypatch.setattr(markov_pkg.importlib, "import_module", fake_import_module)
    markov_pkg.__dict__.pop("TransitionMatrixEstimator", None)
    assert markov_pkg.TransitionMatrixEstimator is DummyModule.TransitionMatrixEstimator
    with pytest.raises(AttributeError, match="nope"):
        markov_pkg.__getattr__("nope")


def test_markov_public_api_minimo() -> None:
    """El paquete expone config y excepciones de B19.1."""
    assert markov_pkg.MarkovConfig is MarkovConfig
    assert markov_pkg.MarkovError is MarkovError
    assert "TransitionMatrixEstimator" in markov_pkg.__all__


def test_markov_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``markov`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        MarkovError,
        MarkovConfigError,
        MarkovInputError,
        MarkovFitError,
        MarkovTransformError,
        NonStochasticMatrixError,
        InvalidGeneratorError,
        MarkovEmbeddingError,
    ):
        assert issubclass(error_cls, NikodymError)
        with pytest.raises(MarkovError, match="fallo markov"):
            raise error_cls("fallo markov")


def test_campos_markov_tienen_metadatos_ui() -> None:
    """Todos los campos de config Markov declaran metadata de UI para SDD-23."""
    for modelo in (
        MarkovInputConfig,
        MarkovStateConfig,
        MarkovEstimationConfig,
        MarkovDynamicsConfig,
        MarkovValidationConfig,
        MarkovConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_columnas_requeridas_faltantes_levantan_markovconfigerror() -> None:
    """``id_col``, ``time_col`` y ``state_col`` son obligatorios."""
    with pytest.raises(MarkovConfigError, match="faltan"):
        MarkovInputConfig(time_col="period", state_col="state")  # type: ignore[call-arg]
    assert MarkovInputConfig._check_requeridos_raw("ya-validado") == "ya-validado"


def test_columnas_id_tiempo_estado_deben_ser_distintas() -> None:
    """``id_col``, ``time_col`` y ``state_col`` deben identificar columnas distintas."""
    with pytest.raises(MarkovConfigError, match="distintas"):
        MarkovInputConfig(id_col="id", time_col="id", state_col="state")


def test_columnas_no_pueden_ser_vacias() -> None:
    """Las columnas declarativas no pueden quedar vacías."""
    with pytest.raises(MarkovConfigError, match="input"):
        MarkovInputConfig(id_col=" ", time_col="period", state_col="state")


def test_states_no_puede_tener_duplicados() -> None:
    """``states`` no acepta estados duplicados."""
    with pytest.raises(MarkovConfigError, match="duplicados"):
        MarkovStateConfig(states=("A", "A", "default"))


def test_states_debe_contener_default_state() -> None:
    """``states`` debe contener ``default_state``."""
    with pytest.raises(MarkovConfigError, match="default_state"):
        MarkovStateConfig(states=("A", "B"), default_state="default")


def test_absorbing_states_debe_ser_subconjunto_de_states() -> None:
    """``absorbing_states`` debe ser subconjunto de ``states``."""
    with pytest.raises(MarkovConfigError, match="subconjunto"):
        MarkovStateConfig(states=("A", "default"), absorbing_states=("default", "prepaid"))


def test_absorbing_states_debe_contener_default_state() -> None:
    """``absorbing_states`` debe contener ``default_state``."""
    with pytest.raises(MarkovConfigError, match="contener default_state"):
        MarkovStateConfig(states=("A", "default", "prepaid"), absorbing_states=("prepaid",))


def test_estados_no_pueden_ser_vacios() -> None:
    """Estados, default y absorbentes no pueden ser strings vacíos."""
    with pytest.raises(MarkovConfigError, match="states"):
        MarkovStateConfig(states=("A", " "), default_state="A", absorbing_states=("A",))
    with pytest.raises(MarkovConfigError, match="absorbing_states"):
        MarkovStateConfig(states=("A", "default"), absorbing_states=("default", " "))


def test_method_duration_exige_exposure_time_col() -> None:
    """``method='duration'`` exige ``input.exposure_time_col``."""
    with pytest.raises(MarkovConfigError, match="exposure_time_col"):
        _markov_config_minimo(estimation=MarkovEstimationConfig(method="duration"))


def test_projection_mode_aalen_johansen_exige_transition_time_col() -> None:
    """``projection_mode='aalen_johansen'`` exige ``input.transition_time_col``."""
    with pytest.raises(MarkovConfigError, match="transition_time_col"):
        _markov_config_minimo(dynamics=MarkovDynamicsConfig(projection_mode="aalen_johansen"))


def test_use_weights_exige_weight_col() -> None:
    """``use_weights=True`` exige ``input.weight_col``."""
    with pytest.raises(MarkovConfigError, match="weight_col"):
        _markov_config_minimo(estimation=MarkovEstimationConfig(use_weights=True))


def test_horizon_periods_debe_ser_positivo_y_creciente() -> None:
    """``horizon_periods`` debe contener enteros positivos estrictamente crecientes."""
    with pytest.raises(MarkovConfigError, match="positivos"):
        MarkovDynamicsConfig(horizon_periods=(1, 0, 2))
    with pytest.raises(MarkovConfigError, match="estrictamente creciente"):
        MarkovDynamicsConfig(horizon_periods=(1, 3, 3))


@pytest.mark.parametrize("interval", [float("nan"), float("inf")])
def test_interval_debe_ser_finito(interval: float) -> None:
    """``interval`` rechaza NaN e infinitos antes de entrar al ``config_hash``."""
    with pytest.raises(MarkovConfigError, match="finito"):
        MarkovEstimationConfig(interval=interval)


def test_evaluation_times_debe_ser_positivo_y_creciente() -> None:
    """``evaluation_times`` debe contener positivos estrictamente crecientes."""
    assert MarkovDynamicsConfig(evaluation_times=(0.5, 1.0)).evaluation_times == (0.5, 1.0)
    with pytest.raises(MarkovConfigError, match="positivos"):
        MarkovDynamicsConfig(evaluation_times=(0.0, 1.0))
    with pytest.raises(MarkovConfigError, match="estrictamente creciente"):
        MarkovDynamicsConfig(evaluation_times=(1.0, 0.5))


@pytest.mark.parametrize("evaluation_time", [float("nan"), float("inf")])
def test_evaluation_times_debe_ser_finito(evaluation_time: float) -> None:
    """``evaluation_times`` rechaza NaN e infinitos para preservar reproducibilidad."""
    with pytest.raises(MarkovConfigError, match="finitos"):
        MarkovDynamicsConfig(evaluation_times=(evaluation_time,))


def test_time_unit_no_puede_ser_vacio() -> None:
    """``time_unit`` debe ser texto no vacío."""
    with pytest.raises(MarkovConfigError, match="dynamics"):
        MarkovDynamicsConfig(time_unit=" ")


@pytest.mark.parametrize(
    ("config_cls", "kwargs"),
    [
        (MarkovConfig, {"type": "custom"}),
        (MarkovEstimationConfig, {"method": "invalid"}),
        (MarkovEstimationConfig, {"interval": 0.0}),
        (MarkovEstimationConfig, {"interval": "no-numero"}),
        (MarkovEstimationConfig, {"min_origin_count": 0}),
        (MarkovDynamicsConfig, {"projection_mode": "nonhomogeneous"}),
        (MarkovDynamicsConfig, {"embedding_policy": "silent"}),
        (MarkovValidationConfig, {"stochastic_tol": 0.0}),
        (MarkovValidationConfig, {"generator_tol": 1e-3}),
        (MarkovValidationConfig, {"imaginary_tol": 1e-3}),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    config_cls: type[object],
    kwargs: dict[str, object],
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        config_cls(**kwargs)
