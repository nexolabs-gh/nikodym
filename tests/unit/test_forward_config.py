"""Tests de ``ForwardConfig`` (SDD-20 §5) e integración con ``NikodymConfig``."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys

import pytest
import yaml
from pydantic import ValidationError

import nikodym.forward as forward_pkg  # importa la capa: puebla el hook
from nikodym.core import study as study_module
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
    dump_config,
    loads_config,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.forward.config import (
    ForwardConfig,
    ForwardInputConfig,
    ForwardValidationConfig,
    MacroModelConfig,
    MacroSourceConfig,
    SatelliteConfig,
    ScenarioConfig,
    ScenarioDefinitionConfig,
    TtcReversionConfig,
)
from nikodym.forward.exceptions import (
    ForwardConfigError,
    ForwardError,
    ForwardFitError,
    ForwardInputError,
    ForwardPredictionError,
    ForwardScenarioError,
    MacroProjectionError,
    PitConsistencyError,
    SatelliteModelError,
)

GOLDEN_DEFAULT_CONFIG_HASH = "0be3798f51c14940597f44e8fb8ac19ec23c88f9c2ab29d94fecd800e093902e"


@pytest.fixture(autouse=True)
def _capa_forward_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_FORWARD_CONFIG_CLS", ForwardConfig)


def _macro_source(**overrides: object) -> MacroSourceConfig:
    """Fuente macro mínima válida para pruebas de forward."""
    data: dict[str, object] = {
        "type": "dataframe",
        "variable_cols": ("unemployment", "gdp"),
    }
    data.update(overrides)
    return MacroSourceConfig.model_validate(data)


def _input(**overrides: object) -> ForwardInputConfig:
    """Config de entrada mínima válida con base PIT explícita."""
    data: dict[str, object] = {
        "macro_source": _macro_source(),
        "pd_basis_assumption": "pit",
    }
    data.update(overrides)
    return ForwardInputConfig.model_validate(data)


def _scenario(name: str, weight: float, **overrides: object) -> ScenarioDefinitionConfig:
    """Construye un escenario macro válido para pruebas."""
    data: dict[str, object] = {"name": name, "weight": weight}
    data.update(overrides)
    return ScenarioDefinitionConfig.model_validate(data)


def _valid_scenarios() -> ScenarioConfig:
    """Escenarios base/adverse/severe con shocks explícitos para evitar FALTA-DATO."""
    return ScenarioConfig(
        scenarios=(
            _scenario("base", 0.60),
            _scenario("adverse", 0.30, shocks={"unemployment": 1.0}),
            _scenario("severe", 0.10, shocks={"unemployment": 2.0}),
        )
    )


def _cfg(**overrides: object) -> ForwardConfig:
    """Config forward mínimo válido para B20.1."""
    data: dict[str, object] = {
        "input": _input(),
        "satellite": SatelliteConfig(factor_cols=("unemployment",)),
        "scenarios": _valid_scenarios(),
    }
    data.update(overrides)
    return ForwardConfig.model_validate(data)


def _manual_default_hash() -> str:
    """Recalcula el golden sin llamar a ``config_hash``."""
    payload = NikodymConfig().model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_forwardconfig_defaults_golden() -> None:
    """Los defaults defendibles de SDD-20 §5 coinciden campo a campo."""
    assert MacroSourceConfig(type="path", path="macro.parquet", variable_cols=("gdp",)).model_dump(
        mode="json"
    ) == {
        "type": "path",
        "path": "macro.parquet",
        "artifact_domain": None,
        "artifact_key": None,
        "time_col": "period",
        "frequency": None,
        "variable_cols": ["gdp"],
        "exogenous_cols": [],
    }
    assert MacroModelConfig().model_dump(mode="json") == {
        "kind": "arima",
        "horizon_periods": 12,
        "arima_order": [1, 0, 0],
        "seasonal_order": None,
        "var_lags": None,
        "vecm_rank": None,
        "use_pmdarima_auto_order": False,
        "auto_arima_random": False,
        "random_state": None,
        "ljung_box_lags": [6, 12],
        "fail_on_ljung_box": False,
    }
    assert SatelliteConfig(factor_cols=("gdp",)).model_dump(mode="json") == {
        "mode": "fit",
        "factor_cols": ["gdp"],
        "segment_col": None,
        "target_components": ["pd"],
        "reference_scenario": "base",
        "coefficient_table_path": None,
        "min_history_periods": 12,
    }
    assert ScenarioConfig().model_dump(mode="json") == {
        "scenarios": [
            {
                "name": "base",
                "weight": 0.60,
                "macro_path_path": None,
                "shocks": {},
                "description": None,
            },
            {
                "name": "adverse",
                "weight": 0.30,
                "macro_path_path": None,
                "shocks": {},
                "description": None,
            },
            {
                "name": "severe",
                "weight": 0.10,
                "macro_path_path": None,
                "shocks": {},
                "description": None,
            },
        ],
        "forbid_mean_scenario": True,
        "require_at_least_three": True,
    }
    assert TtcReversionConfig().model_dump(mode="json") == {
        "enabled": True,
        "reasonable_supportable_periods": 12,
        "reversion_periods": 24,
        "method": "linear_logit",
        "ttc_anchor": "input_term_structure",
    }
    assert ForwardValidationConfig().model_dump(mode="json") == {
        "probability_tol": 1e-10,
        "weight_sum_tol": 1e-12,
        "monotonic_tol": 1e-10,
        "fail_on_missing_scenario_paths": True,
    }
    assert _cfg().schema_version == "1.0.0"
    assert _cfg().type == "standard"
    assert _cfg().fail_on_falta_dato is True


def test_forwardinput_defaults_golden_con_macro_explicita() -> None:
    """``ForwardInputConfig`` conserva defaults de fuentes y PIT/TTC."""
    assert _input(macro_source=_macro_source(variable_cols=("gdp",))).model_dump(mode="json") == {
        "macro_source": {
            "type": "dataframe",
            "path": None,
            "artifact_domain": None,
            "artifact_key": None,
            "time_col": "period",
            "frequency": None,
            "variable_cols": ["gdp"],
            "exogenous_cols": [],
        },
        "term_structure_sources": ["survival", "markov"],
        "pd_basis_assumption": "pit",
        "require_pit_consistency": True,
    }


def test_round_trip_yaml_forwardconfig_y_nikodymconfig() -> None:
    """Serializar y recargar ``forward`` por YAML preserva igualdad exacta."""
    cfg = NikodymConfig(forward=_cfg(macro=MacroModelConfig(kind="sarima")))
    text = dump_config(cfg)
    assert loads_config(text) == cfg

    raw_forward = yaml.safe_load(
        yaml.safe_dump(cfg.forward.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    )
    assert ForwardConfig.model_validate(raw_forward) == cfg.forward


def test_nikodymconfig_forward_instancia_y_dict_coaccionan() -> None:
    """Instancias y dicts en ``forward`` se coaccionan por el hook cargado."""
    forward = _cfg()
    cfg = NikodymConfig(forward=forward)
    assert isinstance(cfg.forward, ForwardConfig)
    assert cfg.forward is forward

    dict_cfg = NikodymConfig(
        forward={
            "input": {
                "macro_source": {"type": "dataframe", "variable_cols": ["unemployment"]},
                "pd_basis_assumption": "pit",
            },
            "satellite": {"factor_cols": ["unemployment"]},
            "scenarios": {
                "scenarios": [
                    {"name": "base", "weight": 0.6},
                    {"name": "adverse", "weight": 0.3, "shocks": {"unemployment": 1.0}},
                    {"name": "severe", "weight": 0.1, "shocks": {"unemployment": 2.0}},
                ]
            },
        }
    )
    assert isinstance(dict_cfg.forward, ForwardConfig)
    assert dict_cfg.forward.input.macro_source.variable_cols == ("unemployment",)


def test_nikodymconfig_forward_none_explicito() -> None:
    """``forward=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(forward=None).forward is None


def test_nikodymconfig_forward_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``forward`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_FORWARD_CONFIG_CLS", None)
    cfg = NikodymConfig(forward={"input": {"pd_basis_assumption": "pit"}})
    assert cfg.forward == {"input": {"pd_basis_assumption": "pit"}}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_forward_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``forward`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_FORWARD_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(forward=blob)


def test_config_hash_default_con_forward_none_golden_no_tautologico() -> None:
    """El golden por defecto incluye ``forward=None`` con cálculo independiente."""
    assert _manual_default_hash() == GOLDEN_DEFAULT_CONFIG_HASH
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_forward_no_es_infra_section_y_cambia_hash() -> None:
    """``forward`` entra al ``config_hash`` global y sus parámetros mueven identidad."""
    base = config_hash(NikodymConfig(forward=_cfg()))
    variado = config_hash(NikodymConfig(forward=_cfg(macro=MacroModelConfig(horizon_periods=18))))
    assert "forward" not in INFRA_SECTIONS
    assert variado != base


def test_macro_source_variable_cols_no_vacio_y_sin_time_col() -> None:
    """``variable_cols`` no puede estar vacío ni contener ``time_col``."""
    assert MacroSourceConfig._check_variables_raw("ya-validado") == "ya-validado"
    assert MacroSourceConfig._check_variables_raw({"type": "dataframe"}) == {"type": "dataframe"}
    assert _macro_source(variable_cols=("gdp",)).variable_cols == ("gdp",)
    with pytest.raises(ForwardConfigError, match="variable_cols"):
        MacroSourceConfig(type="dataframe", variable_cols=None)  # type: ignore[arg-type]
    with pytest.raises(ForwardConfigError, match="variable_cols"):
        MacroSourceConfig(type="dataframe", variable_cols=())
    with pytest.raises(ForwardConfigError, match="time_col"):
        MacroSourceConfig(type="dataframe", time_col="period", variable_cols=("period",))
    with pytest.raises(ValidationError):
        MacroSourceConfig(type="dataframe", variable_cols=1)


def test_macro_source_path_artifact_y_dataframe_requeridos() -> None:
    """``path`` y ``artifact`` exigen las claves declaradas por SDD-20 §5."""
    assert MacroSourceConfig(type="path", path="macro.csv", variable_cols=("gdp",)).path
    assert (
        MacroSourceConfig(
            type="artifact",
            artifact_domain="data",
            artifact_key="macro_history",
            variable_cols=("gdp",),
        ).artifact_key
        == "macro_history"
    )
    assert MacroSourceConfig(type="dataframe", variable_cols=("gdp",)).type == "dataframe"
    with pytest.raises(ForwardConfigError, match="path"):
        MacroSourceConfig(type="path", variable_cols=("gdp",))
    with pytest.raises(ForwardConfigError, match="artifact_domain"):
        MacroSourceConfig(type="artifact", artifact_domain="data", variable_cols=("gdp",))


def test_var_vecm_exigen_dos_variables_macro() -> None:
    """VAR/VECM son multivariados y fallan con una sola variable."""
    two_vars = _input(macro_source=_macro_source(variable_cols=("gdp", "unemployment")))
    assert _cfg(input=two_vars, macro=MacroModelConfig(kind="var")).macro.kind == "var"
    assert _cfg(input=two_vars, macro=MacroModelConfig(kind="vecm")).macro.kind == "vecm"

    one_var = _input(macro_source=_macro_source(variable_cols=("gdp",)))
    with pytest.raises(ForwardConfigError, match="dos variable_cols"):
        _cfg(
            input=one_var,
            satellite=SatelliteConfig(factor_cols=("gdp",)),
            macro=MacroModelConfig(kind="var"),
        )


def test_arimax_exige_exogenas() -> None:
    """ARIMAX exige columnas exógenas declaradas."""
    source = _macro_source(variable_cols=("gdp",), exogenous_cols=("policy_rate",))
    assert (
        _cfg(
            input=_input(macro_source=source),
            satellite=SatelliteConfig(factor_cols=("gdp",)),
            macro=MacroModelConfig(kind="arimax"),
        ).macro.kind
        == "arimax"
    )
    with pytest.raises(ForwardConfigError, match="exogenous_cols"):
        _cfg(
            input=_input(macro_source=_macro_source(variable_cols=("gdp",))),
            satellite=SatelliteConfig(factor_cols=("gdp",)),
            macro=MacroModelConfig(kind="arimax"),
        )


def test_pmdarima_auto_order_solo_univariado_arima_sarima_arimax() -> None:
    """``use_pmdarima_auto_order`` queda limitado a rutas univariadas permitidas."""
    one_var = _input(macro_source=_macro_source(variable_cols=("gdp",)))
    assert (
        _cfg(
            input=one_var,
            satellite=SatelliteConfig(factor_cols=("gdp",)),
            macro=MacroModelConfig(kind="sarima", use_pmdarima_auto_order=True),
        ).macro.use_pmdarima_auto_order
        is True
    )

    with pytest.raises(ForwardConfigError, match="univariado"):
        _cfg(macro=MacroModelConfig(kind="var", use_pmdarima_auto_order=True))
    with pytest.raises(ForwardConfigError, match="univariado"):
        _cfg(macro=MacroModelConfig(kind="arima", use_pmdarima_auto_order=True))


def test_auto_arima_random_exige_random_state() -> None:
    """La ruta aleatoria de auto_arima exige semilla explícita."""
    assert MacroModelConfig(auto_arima_random=True, random_state=123).random_state == 123
    with pytest.raises(ForwardConfigError, match="random_state"):
        MacroModelConfig(auto_arima_random=True)


def test_horizon_debe_cubrir_periodo_razonable_ttc() -> None:
    """El horizonte debe cubrir el período razonable si la reversión TTC está activa."""
    assert _cfg().ttc_reversion.reasonable_supportable_periods == 12
    assert (
        _cfg(
            macro=MacroModelConfig(horizon_periods=6),
            ttc_reversion=TtcReversionConfig(method="none"),
        ).ttc_reversion.method
        == "none"
    )
    with pytest.raises(ForwardConfigError, match="horizon_periods"):
        _cfg(macro=MacroModelConfig(horizon_periods=6))


def test_scenarios_validan_unicidad_requeridos_y_pesos() -> None:
    """Escenarios duplicados, incompletos o con pesos fuera de suma fallan."""
    assert _cfg(scenarios=_valid_scenarios()).scenarios.require_at_least_three is True
    solo_base = ScenarioConfig(
        scenarios=(_scenario("base", 1.0),),
        require_at_least_three=False,
    )
    assert _cfg(scenarios=solo_base).scenarios.require_at_least_three is False

    with pytest.raises(ForwardScenarioError, match="duplicados"):
        _cfg(
            scenarios=ScenarioConfig(
                scenarios=(
                    _scenario("base", 0.5),
                    _scenario("base", 0.5),
                    _scenario("severe", 0.0, shocks={"unemployment": 2.0}),
                )
            )
        )
    with pytest.raises(ForwardScenarioError, match="faltan"):
        _cfg(
            scenarios=ScenarioConfig(
                scenarios=(
                    _scenario("base", 0.7),
                    _scenario("adverse", 0.3, shocks={"unemployment": 1.0}),
                )
            )
        )
    with pytest.raises(ForwardScenarioError, match="suma"):
        _cfg(
            scenarios=ScenarioConfig(
                scenarios=(
                    _scenario("base", 0.50),
                    _scenario("adverse", 0.30, shocks={"unemployment": 1.0}),
                    _scenario("severe", 0.10, shocks={"unemployment": 2.0}),
                )
            )
        )


def test_forbid_mean_scenario_veta_nombres_reservados() -> None:
    """El guard anti escenario medio veta mean/average/weighted_mean_input."""
    allowed = ScenarioConfig(
        scenarios=(
            _scenario("base", 0.60),
            _scenario("adverse", 0.30, shocks={"unemployment": 1.0}),
            _scenario("severe", 0.10, shocks={"unemployment": 2.0}),
            _scenario("mean", 0.0),
        ),
        forbid_mean_scenario=False,
    )
    assert _cfg(scenarios=allowed).scenarios.forbid_mean_scenario is False

    with pytest.raises(ForwardScenarioError, match="escenarios medios"):
        _cfg(
            scenarios=ScenarioConfig(
                scenarios=(
                    _scenario("base", 0.60),
                    _scenario("adverse", 0.30, shocks={"unemployment": 1.0}),
                    _scenario("severe", 0.10, shocks={"unemployment": 2.0}),
                    _scenario("weighted_mean_input", 0.0),
                )
            )
        )


def test_adverse_severe_sin_paths_ni_shocks_falla_por_default() -> None:
    """FALTA-DATO-FWD-1 falla por default y no inventa shocks adversos/severos."""
    with pytest.raises(ForwardScenarioError, match="FALTA-DATO-FWD-1"):
        _cfg(scenarios=ScenarioConfig())

    assert _cfg(scenarios=ScenarioConfig(), fail_on_falta_dato=False).fail_on_falta_dato is False
    assert (
        _cfg(
            scenarios=ScenarioConfig(),
            validation=ForwardValidationConfig(fail_on_missing_scenario_paths=False),
        ).validation.fail_on_missing_scenario_paths
        is False
    )


def test_satellite_factor_cols_subconjunto_de_variables_macro() -> None:
    """Los factores satellite deben estar proyectados por el modelo macro."""
    assert _cfg(satellite=SatelliteConfig(factor_cols=("gdp",))).satellite.factor_cols == ("gdp",)
    assert SatelliteConfig._check_factores_raw("ya-validado") == "ya-validado"
    assert SatelliteConfig._check_factores_raw({"mode": "fit"}) == {"mode": "fit"}
    with pytest.raises(ForwardConfigError, match="factor_cols"):
        SatelliteConfig(factor_cols=None)  # type: ignore[arg-type]
    with pytest.raises(ForwardConfigError, match="factor_cols"):
        SatelliteConfig(factor_cols=())
    with pytest.raises(SatelliteModelError, match="subconjunto"):
        _cfg(satellite=SatelliteConfig(factor_cols=("inflation",)))
    with pytest.raises(ValidationError):
        SatelliteConfig(factor_cols=1)


def test_pd_basis_assumption_requerido_si_no_viene_pd_basis() -> None:
    """Sin ``pd_basis`` en term-structure, la config exige supuesto PIT/TTC."""
    assert _input(pd_basis_assumption="ttc").pd_basis_assumption == "ttc"
    assert (
        ForwardInputConfig(
            macro_source=_macro_source(variable_cols=("gdp",)),
            require_pit_consistency=False,
        ).pd_basis_assumption
        is None
    )
    with pytest.raises(PitConsistencyError, match="pd_basis_assumption"):
        ForwardInputConfig(macro_source=_macro_source(variable_cols=("gdp",)))


def test_shocks_y_pesos_no_finitos_se_rechazan() -> None:
    """Pesos y shocks no finitos no entran al config_hash."""
    assert _scenario("adverse", 0.3, shocks={"gdp": -0.0}).shocks == {"gdp": 0.0}
    assert _scenario("severe", -0.0, shocks={"gdp": 2.0}).weight == 0.0
    with pytest.raises(ForwardScenarioError, match="finito"):
        ScenarioDefinitionConfig(name="base", weight=float("nan"))
    with pytest.raises(ForwardScenarioError, match="finito"):
        ScenarioDefinitionConfig(name="base", weight=1.0, shocks={"gdp": math.inf})
    with pytest.raises(ValidationError):
        ScenarioDefinitionConfig(name="base", weight="no-numero")


def test_weight_cero_con_signo_no_mueve_config_hash() -> None:
    """``weight=-0.0`` se normaliza y no crea identidad distinta del estudio."""
    positive_zero = ScenarioConfig(
        scenarios=(
            _scenario("base", 0.70),
            _scenario("adverse", 0.30, shocks={"unemployment": 1.0}),
            _scenario("severe", 0.0, shocks={"unemployment": 2.0}),
        )
    )
    negative_zero = ScenarioConfig(
        scenarios=(
            _scenario("base", 0.70),
            _scenario("adverse", 0.30, shocks={"unemployment": 1.0}),
            _scenario("severe", -0.0, shocks={"unemployment": 2.0}),
        )
    )

    assert negative_zero.scenarios[2].weight == 0.0
    assert config_hash(NikodymConfig(forward=_cfg(scenarios=negative_zero))) == config_hash(
        NikodymConfig(forward=_cfg(scenarios=positive_zero))
    )


@pytest.mark.parametrize(
    ("config_cls", "kwargs"),
    [
        (
            ForwardConfig,
            {
                "input": _input(),
                "satellite": SatelliteConfig(factor_cols=("gdp",)),
                "type": "custom",
            },
        ),
        (MacroSourceConfig, {"type": "ftp", "variable_cols": ("gdp",)}),
        (MacroModelConfig, {"kind": "ets"}),
        (MacroModelConfig, {"horizon_periods": 0}),
        (MacroModelConfig, {"var_lags": 0}),
        (MacroModelConfig, {"vecm_rank": 0}),
        (SatelliteConfig, {"factor_cols": ("gdp",), "mode": "predict"}),
        (SatelliteConfig, {"factor_cols": ("gdp",), "target_components": ("ead",)}),
        (SatelliteConfig, {"factor_cols": ("gdp",), "min_history_periods": 2}),
        (ForwardInputConfig, {"macro_source": _macro_source(), "pd_basis_assumption": "point"}),
        (ForwardValidationConfig, {"probability_tol": 0.0}),
        (ForwardValidationConfig, {"weight_sum_tol": 1e-3}),
        (ForwardValidationConfig, {"monotonic_tol": 1e-3}),
        (TtcReversionConfig, {"reasonable_supportable_periods": 0}),
        (TtcReversionConfig, {"reversion_periods": 0}),
        (TtcReversionConfig, {"method": "step"}),
        (TtcReversionConfig, {"ttc_anchor": "portfolio_mean"}),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    config_cls: type[object],
    kwargs: dict[str, object],
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        config_cls(**kwargs)


def test_campos_forward_tienen_metadatos_ui() -> None:
    """Todos los campos de config forward declaran metadata de UI para SDD-23."""
    for modelo in (
        MacroSourceConfig,
        MacroModelConfig,
        SatelliteConfig,
        ScenarioDefinitionConfig,
        ScenarioConfig,
        TtcReversionConfig,
        ForwardInputConfig,
        ForwardValidationConfig,
        ForwardConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_forward_public_api_minimo() -> None:
    """El paquete expone config y excepciones de B20.1."""
    assert forward_pkg.ForwardConfig is ForwardConfig
    assert forward_pkg.ForwardError is ForwardError
    assert "ForwardConfig" in forward_pkg.__all__


def test_forward_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``forward`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        ForwardError,
        ForwardConfigError,
        ForwardInputError,
        ForwardFitError,
        ForwardPredictionError,
        ForwardScenarioError,
        PitConsistencyError,
        MacroProjectionError,
        SatelliteModelError,
    ):
        assert issubclass(error_cls, NikodymError)
        with pytest.raises(ForwardError, match="fallo forward"):
            raise error_cls("fallo forward")


def test_import_forward_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.forward`` registra hook sin arrastrar forecasting pesado."""
    code = (
        "import nikodym.forward, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.forward.config import ForwardConfig;"
        "bloqueados=[m for m in ('statsmodels','pmdarima','pandas','scipy') if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(forward={"
        "'input': {'macro_source': {'type': 'dataframe', 'variable_cols': ['gdp']}, "
        "'pd_basis_assumption': 'pit'},"
        "'satellite': {'factor_cols': ['gdp']},"
        "'scenarios': {'scenarios': ["
        "{'name': 'base', 'weight': 0.6},"
        "{'name': 'adverse', 'weight': 0.3, 'shocks': {'gdp': 1.0}},"
        "{'name': 'severe', 'weight': 0.1, 'shocks': {'gdp': 2.0}}]}});"
        "assert isinstance(cfg.forward, ForwardConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_forward_como_blob_opaco_sin_importar_forward() -> None:
    """El core acepta ``forward`` JSON/dict sin importar la capa forward."""
    code = (
        "from nikodym.core.config import NikodymConfig, dump_config;"
        "import sys;"
        "assert 'nikodym.forward' not in sys.modules;"
        "cfg=NikodymConfig(forward={'input': {'pd_basis_assumption': 'pit'}});"
        "assert cfg.forward == {'input': {'pd_basis_assumption': 'pit'}};"
        "texto=dump_config(cfg);"
        "assert 'forward:' in texto;"
        "assert 'nikodym.forward' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_import_core_no_arrastra_forward_en_proceso_fresco() -> None:
    """``import nikodym.core`` mantiene el hook forward sin importar la capa."""
    code = "import nikodym.core, sys; assert 'nikodym.forward' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_study_cablea_forward_en_orden_por_defecto() -> None:
    """``Study`` conoce ``forward`` tras survival/markov y antes de provisiones CMF."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("markov") < order.index("forward")
    assert order.index("survival") < order.index("forward") < order.index("provisioning_cmf")
    assert study_module._DOMAIN_MODULES["forward"] == "nikodym.forward"
    assert study_module._DOMAIN_CONFIG_CLASSES["forward"] == (
        "nikodym.forward.config",
        "ForwardConfig",
    )


def test_dump_load_nikodymconfig_con_forward_idempotente() -> None:
    """``dump_config``/``loads_config`` preservan la sección ``forward`` cableada."""
    cfg = NikodymConfig(forward=_cfg())
    assert loads_config(dump_config(cfg)) == cfg
