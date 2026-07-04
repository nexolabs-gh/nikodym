"""Tests de ``StressConfig`` (SDD-21 §5) e integración con ``NikodymConfig``."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

import nikodym.stress as stress_pkg
import nikodym.stress.config as stress_config_module
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
from nikodym.stress.config import (
    ReverseStressConfig,
    SensitivitySweepConfig,
    StressConfig,
    StressInputConfig,
    StressMetric,
    StressOutputConfig,
    StressScenarioConfig,
    StressShockConfig,
    StressTargetConfig,
    StressValidationConfig,
)
from nikodym.stress.exceptions import (
    NonMonotonicStressError,
    ReverseStressError,
    StressConfigError,
    StressDependencyError,
    StressEngineError,
    StressError,
    StressFaltaDatoError,
    StressInputError,
    StressOutputError,
    StressScenarioError,
)

GOLDEN_DEFAULT_CONFIG_HASH = "2dc342f1fd7be6d5ec32bca5a4c3cc4badf1da11f6876b280f7ca9662f857f3e"


@pytest.fixture(autouse=True)
def _capa_stress_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_STRESS_CONFIG_CLS", StressConfig)


def _shock(**overrides: object) -> StressShockConfig:
    """Shock mínimo válido para tests de stress."""
    data: dict[str, object] = {"factor": "unemployment", "value": 1.5}
    data.update(overrides)
    return StressShockConfig.model_validate(data)


def _scenario(**overrides: object) -> StressScenarioConfig:
    """Escenario mínimo válido sin exigir dominancia no demostrable en config puro."""
    data: dict[str, object] = {
        "name": "severe_plus",
        "shocks": (_shock(),),
        "require_dominates_forward_adverse": False,
    }
    data.update(overrides)
    return StressScenarioConfig.model_validate(data)


def _validation_relajada(**overrides: object) -> StressValidationConfig:
    """Validación que desactiva brechas imposibles de demostrar sin artefactos forward."""
    data: dict[str, object] = {
        "require_dominates_forward_adverse": False,
        "fail_on_falta_dato": False,
        "fail_on_missing_ecl_engine": False,
    }
    data.update(overrides)
    return StressValidationConfig.model_validate(data)


def _cfg(**overrides: object) -> StressConfig:
    """Config stress mínimo válido para B21.1."""
    data: dict[str, object] = {
        "scenarios": (_scenario(),),
        "validation": _validation_relajada(),
    }
    data.update(overrides)
    return StressConfig.model_validate(data)


def _manual_default_hash() -> str:
    """Recalcula el golden sin llamar a ``config_hash``."""
    payload = NikodymConfig().model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_stressconfig_defaults_golden() -> None:
    """Los defaults defendibles de SDD-21 §5 coinciden campo a campo."""
    assert StressInputConfig().model_dump(mode="json") == {
        "forward_domain": "forward",
        "macro_projection_key": "macro_projection",
        "satellite_model_key": "satellite_model",
        "term_structure_key": "term_structure",
        "scenario_weighting_key": "scenario_weighting",
        "ecl_input_key": "ecl_input",
        "ecl_engine_artifact": None,
        "provision_engine_artifact": None,
    }
    assert _shock(value=-0.0).model_dump(mode="json") == {
        "factor": "unemployment",
        "operation": "additive",
        "value": 0.0,
        "unit": None,
        "periods": "all",
        "source": "user",
        "description": None,
    }
    assert _scenario().model_dump(mode="json") == {
        "name": "severe_plus",
        "kind": "severe",
        "base_forward_scenario": "severe",
        "severity": 1.0,
        "shocks": [
            {
                "factor": "unemployment",
                "operation": "additive",
                "value": 1.5,
                "unit": None,
                "periods": "all",
                "source": "user",
                "description": None,
            }
        ],
        "weight": None,
        "require_dominates_forward_adverse": False,
        "description": None,
    }
    assert SensitivitySweepConfig(
        name="grid_unemployment", factor="unemployment", shock_value=-0.0
    ).model_dump(mode="json") == {
        "name": "grid_unemployment",
        "factor": "unemployment",
        "operation": "additive",
        "base_forward_scenario": "severe",
        "shock_value": 0.0,
        "severity_grid": [0.0, 0.5, 1.0, 1.5, 2.0],
        "metric": "ecl",
        "group_cols": ["scenario"],
        "require_monotonic": False,
    }
    assert StressTargetConfig(
        name="ecl_25",
        metric="ecl",
        threshold=-0.0,
        scenario_name="severe_plus",
    ).model_dump(mode="json") == {
        "name": "ecl_25",
        "metric": "ecl",
        "threshold": 0.0,
        "direction": "at_least",
        "scenario_name": "severe_plus",
        "group_filter": {},
        "requires_economic_engine": True,
    }
    assert ReverseStressConfig(factor="unemployment", shock_value=1.0).model_dump(mode="json") == {
        "enabled": False,
        "target": None,
        "factor": "unemployment",
        "operation": "additive",
        "shock_value": 1.0,
        "bracket": [0.0, 5.0],
        "severity_tol": 1e-6,
        "metric_tol": 1e-8,
        "max_iterations": 64,
        "monotonicity_check_points": [0.0, 0.5, 1.0, 2.0, 5.0],
    }
    assert StressOutputConfig().model_dump(mode="json") == {
        "metrics": ["pd_marginal", "pd_cumulative", "ecl"],
        "publish_stressed_macro": True,
        "publish_stressed_term_structure": True,
        "publish_reverse_path": True,
        "include_baseline_rows": True,
    }
    assert StressValidationConfig().model_dump(mode="json") == {
        "probability_tol": 1e-10,
        "metric_tol": 1e-8,
        "weight_sum_tol": 1e-12,
        "require_forward_severe": True,
        "require_dominates_forward_adverse": True,
        "fail_on_missing_ecl_engine": True,
        "fail_on_falta_dato": True,
    }
    assert _cfg().model_dump(mode="json") == {
        "type": "standard",
        "input": StressInputConfig().model_dump(mode="json"),
        "scenarios": [_scenario().model_dump(mode="json")],
        "sensitivities": [],
        "reverse": [],
        "output": StressOutputConfig().model_dump(mode="json"),
        "validation": _validation_relajada().model_dump(mode="json"),
    }


def test_round_trip_yaml_stressconfig_y_nikodymconfig() -> None:
    """Serializar y recargar ``stress`` por YAML preserva igualdad exacta."""
    target = StressTargetConfig(
        name="pd_objetivo",
        metric="pd_cumulative",
        threshold=0.25,
        scenario_name="severe_plus",
        requires_economic_engine=False,
    )
    cfg = _cfg(
        scenarios=(
            _scenario(
                severity=1.25,
                weight=0.2,
                shocks=(_shock(unit="pp", periods=(1, 2, 3), description="shock aprobado"),),
                description="escenario severo interno",
            ),
        ),
        sensitivities=(
            SensitivitySweepConfig(
                name="grid_pd",
                factor="unemployment",
                shock_value=1.0,
                severity_grid=(0.0, 1.0, 2.0),
                metric="pd_cumulative",
            ),
        ),
        reverse=(
            ReverseStressConfig(
                enabled=True,
                target=target,
                factor="unemployment",
                shock_value=1.0,
                bracket=(0.0, 3.0),
            ),
        ),
    )
    root = NikodymConfig(stress=cfg)
    assert loads_config(dump_config(root)) == root

    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    raw = yaml.safe_load(text)
    assert StressConfig.model_validate(raw) == cfg


def test_nikodymconfig_stress_instancia_y_dict_coaccionan() -> None:
    """Instancias y dicts en ``stress`` se coaccionan por el hook cargado."""
    stress = _cfg()
    cfg = NikodymConfig(stress=stress)
    assert isinstance(cfg.stress, StressConfig)
    assert cfg.stress is stress

    dict_cfg = NikodymConfig(
        stress={
            "scenarios": [
                {
                    "name": "severe_plus",
                    "shocks": [{"factor": "unemployment", "value": 1.5}],
                    "require_dominates_forward_adverse": False,
                }
            ],
            "validation": {
                "require_dominates_forward_adverse": False,
                "fail_on_falta_dato": False,
                "fail_on_missing_ecl_engine": False,
            },
        }
    )
    assert isinstance(dict_cfg.stress, StressConfig)
    assert dict_cfg.stress.scenarios[0].shocks[0].factor == "unemployment"


def test_nikodymconfig_stress_none_explicito() -> None:
    """``stress=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(stress=None).stress is None


def test_nikodymconfig_stress_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``stress`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_STRESS_CONFIG_CLS", None)
    cfg = NikodymConfig(stress={"scenarios": [{"name": "severe_plus"}]})
    assert cfg.stress == {"scenarios": [{"name": "severe_plus"}]}


@pytest.mark.parametrize("blob", [{"columnas": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_stress_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``stress`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_STRESS_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(stress=blob)


def test_config_hash_default_con_stress_none_golden_no_tautologico() -> None:
    """El golden por defecto incluye ``stress=None`` con cálculo independiente."""
    assert _manual_default_hash() == GOLDEN_DEFAULT_CONFIG_HASH
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_stress_no_es_infra_section_y_cambia_hash() -> None:
    """``stress`` entra al ``config_hash`` global y sus parámetros mueven identidad."""
    base = config_hash(NikodymConfig(stress=_cfg()))
    variado = config_hash(
        NikodymConfig(
            stress=_cfg(output=StressOutputConfig(metrics=("pd_marginal", "pd_cumulative")))
        )
    )
    assert "stress" not in INFRA_SECTIONS
    assert variado != base


def test_hash_normaliza_ceros_negativos_en_tuplas_float() -> None:
    """``-0.0`` en tuplas de stress no cambia identidad regulatoria."""
    negativo = StressConfig(
        sensitivities=(
            SensitivitySweepConfig(
                name="grid_unemployment",
                factor="unemployment",
                shock_value=1.0,
                severity_grid=(-0.0, 0.5, 1.0),
            ),
        ),
        reverse=(
            ReverseStressConfig(
                factor="unemployment",
                shock_value=1.0,
                bracket=(-0.0, 5.0),
                monotonicity_check_points=(-0.0, 0.5, 1.0, 2.0, 5.0),
            ),
        ),
    )
    positivo = StressConfig(
        sensitivities=(
            SensitivitySweepConfig(
                name="grid_unemployment",
                factor="unemployment",
                shock_value=1.0,
                severity_grid=(0.0, 0.5, 1.0),
            ),
        ),
        reverse=(
            ReverseStressConfig(
                factor="unemployment",
                shock_value=1.0,
                bracket=(0.0, 5.0),
                monotonicity_check_points=(0.0, 0.5, 1.0, 2.0, 5.0),
            ),
        ),
    )

    assert negativo.model_dump(mode="json") == positivo.model_dump(mode="json")
    assert config_hash(NikodymConfig(stress=negativo)) == config_hash(
        NikodymConfig(stress=positivo)
    )


def test_tuplas_float_rechazan_shape_escalar() -> None:
    """Los normalizadores de tuplas no convierten escalares en listas implícitas."""
    with pytest.raises(ValidationError):
        SensitivitySweepConfig(
            name="grid",
            factor="unemployment",
            shock_value=1.0,
            severity_grid=1.0,  # type: ignore[arg-type]
        )
    with pytest.raises(StressConfigError, match="booleano"):
        SensitivitySweepConfig(
            name="grid",
            factor="unemployment",
            shock_value=1.0,
            severity_grid=np.array([False, True]),
        )
    with pytest.raises(StressConfigError, match="booleano"):
        ReverseStressConfig(
            factor="unemployment",
            shock_value=1.0,
            bracket=np.array([False, True]),
        )


@pytest.mark.parametrize("value", [True, np.bool_(True), np.array(True)])
def test_reverse_max_iterations_rechaza_bool_like(value: object) -> None:
    """``max_iterations`` no acepta booleanos coercibles a ``1``."""
    with pytest.raises(StressConfigError, match=r"max_iterations.*booleano"):
        ReverseStressConfig(factor="unemployment", shock_value=1.0, max_iterations=value)


def test_stressconfig_vacio_falla() -> None:
    """Una sección stress sin escenarios, sensibilidad ni reverse es inválida."""
    with pytest.raises(StressConfigError, match="al menos"):
        StressConfig()
    disabled_reverse = ReverseStressConfig(factor="unemployment", shock_value=1.0)
    with pytest.raises(StressConfigError, match="al menos"):
        StressConfig(scenarios=(), sensitivities=(), reverse=(disabled_reverse,))


def test_stressconfig_con_reverse_enabled_sin_escenarios_es_trabajo_declarado() -> None:
    """Un reverse habilitado cuenta como trabajo declarativo aunque el motor lo difiera."""
    reverse = ReverseStressConfig(
        enabled=True,
        target=StressTargetConfig(
            name="pd_objetivo",
            metric="pd_cumulative",
            threshold=0.25,
            scenario_name="solo_reverse",
            requires_economic_engine=False,
        ),
        factor="unemployment",
        shock_value=1.0,
    )
    cfg = StressConfig(
        scenarios=(),
        sensitivities=(),
        reverse=(reverse,),
        validation=_validation_relajada(),
    )
    assert cfg.reverse[0].enabled is True


def test_reverse_forward_only_no_exige_engine_economico() -> None:
    """Targets reverse forward-only no piden engine ECL con validación estricta."""
    reverse = ReverseStressConfig(
        enabled=True,
        target=StressTargetConfig(
            name="pd_objetivo",
            metric="pd_marginal",
            threshold=0.10,
            scenario_name="solo_reverse",
        ),
        factor="unemployment",
        shock_value=1.0,
    )

    cfg = StressConfig(scenarios=(), sensitivities=(), reverse=(reverse,))

    assert cfg.reverse[0].target is not None
    assert cfg.reverse[0].target.metric == "pd_marginal"


def test_scenario_names_unicos_y_no_reservados() -> None:
    """Los escenarios de stress no aceptan duplicados ni nombres de promedio."""
    with pytest.raises(StressScenarioError, match="reservado"):
        StressScenarioConfig(name="mean", shocks=(_shock(),))
    with pytest.raises(StressScenarioError, match="reservado"):
        StressScenarioConfig(name="Mean", shocks=(_shock(),))
    with pytest.raises(StressScenarioError, match="duplicados"):
        _cfg(scenarios=(_scenario(name="uno"), _scenario(name="uno")))


def test_base_forward_scenario_acepta_custom_y_rechaza_reservados() -> None:
    """El escenario base forward acepta nombres custom y bloquea escenarios medios."""
    custom = StressScenarioConfig(
        name="x",
        base_forward_scenario="stress_base",
        shocks=(_shock(),),
    )
    assert custom.base_forward_scenario == "stress_base"

    with pytest.raises(StressScenarioError, match="reservado"):
        StressScenarioConfig(
            name="x",
            base_forward_scenario="weighted_mean_input",
            shocks=(_shock(),),
        )
    with pytest.raises(StressScenarioError, match="reservado"):
        StressScenarioConfig(
            name="x",
            base_forward_scenario="Weighted_Mean_Input",
            shocks=(_shock(),),
        )


def test_shock_cero_solo_permitido_en_escenario_custom() -> None:
    """Un escenario severo no puede declarar shocks nulos; custom sí puede ser identidad."""
    with pytest.raises(StressScenarioError, match=r"shock\.value == 0"):
        StressScenarioConfig(
            name="severe_zero",
            shocks=(_shock(value=0.0),),
            require_dominates_forward_adverse=False,
        )

    custom = StressScenarioConfig(
        name="custom_identity",
        kind="custom",
        shocks=(_shock(value=-0.0),),
        require_dominates_forward_adverse=False,
    )
    assert custom.kind == "custom"
    assert custom.shocks[0].value == 0.0


@pytest.mark.parametrize("periods", [(), (0,), (-1,), (True,), (np.bool_(True),)])
def test_periods_deben_ser_all_o_periodos_positivos(periods: tuple[int, ...]) -> None:
    """``periods`` acepta ``all`` o una tupla no vacía de períodos positivos."""
    with pytest.raises(StressConfigError, match="periods"):
        StressShockConfig(factor="gdp", value=1.0, periods=periods)


def test_periods_all_explicito_y_shape_invalido() -> None:
    """El validador temprano acepta ``all`` y deja shapes inválidos a Pydantic."""
    assert StressShockConfig(factor="gdp", value=1.0, periods="all").periods == "all"
    with pytest.raises(ValidationError):
        StressShockConfig(factor="gdp", value=1.0, periods=1)  # type: ignore[arg-type]


def test_bool_like_numpy_defensivo_config() -> None:
    """El guard bool-like cubre escalares NumPy y objetos defensivos."""

    class FakeBoolShapeNone:
        """Objeto tipo NumPy con dtype bool y shape ausente."""

        __module__ = "numpy"
        dtype = type("Dtype", (), {"kind": "b"})()
        shape = None

    class FakeBoolBadShape:
        """Objeto tipo NumPy con dtype bool y shape no iterable."""

        __module__ = "numpy"
        dtype = type("Dtype", (), {"kind": "b"})()
        shape = object()

    assert stress_config_module._is_bool_like(np.array(True)) is True
    assert stress_config_module._is_bool_like(np.array(1)) is False
    assert stress_config_module._is_bool_like(FakeBoolShapeNone()) is False
    assert stress_config_module._is_bool_like(FakeBoolBadShape()) is False


@pytest.mark.parametrize("grid", [(), (0.0, 0.5, 0.5), (0.0, -0.1), (0.0, math.inf)])
def test_severity_grid_debe_ser_finita_no_negativa_y_creciente(
    grid: tuple[float, ...],
) -> None:
    """La grilla de severidad debe ser no vacía, finita y estrictamente creciente."""
    with pytest.raises(StressConfigError, match="severity_grid"):
        SensitivitySweepConfig(name="grid", factor="gdp", shock_value=1.0, severity_grid=grid)


@pytest.mark.parametrize("bracket", [(1.0, 1.0), (2.0, 1.0), (-0.1, 1.0), (0.0, math.inf)])
def test_reverse_bracket_debe_ser_finito_no_negativo_y_ordenado(
    bracket: tuple[float, float],
) -> None:
    """El bracket de reverse stress debe cumplir ``lo < hi`` con valores no negativos."""
    with pytest.raises(StressConfigError, match="bracket"):
        ReverseStressConfig(factor="gdp", shock_value=1.0, bracket=bracket)


@pytest.mark.parametrize(
    "points",
    [(), (0.0, math.inf), (0.0, -0.1), (1.0, 0.5)],
)
def test_monotonicity_check_points_deben_ser_validos(points: tuple[float, ...]) -> None:
    """Los puntos de monotonicidad deben ser finitos, no negativos y crecientes."""
    with pytest.raises(StressConfigError, match="monotonicity_check_points"):
        ReverseStressConfig(factor="gdp", shock_value=1.0, monotonicity_check_points=points)


def test_reverse_target_obligatorio_si_enabled() -> None:
    """``reverse.target`` es obligatorio si ``enabled=True``."""
    with pytest.raises(StressConfigError, match="target"):
        ReverseStressConfig(enabled=True, factor="gdp", shock_value=1.0)


@pytest.mark.parametrize(
    ("metric", "input_cfg", "expected_missing"),
    [
        ("ecl", StressInputConfig(provision_engine_artifact=("engines", "provision")), "ecl"),
        ("loss", StressInputConfig(provision_engine_artifact=("engines", "provision")), "ecl"),
        ("ratio", StressInputConfig(provision_engine_artifact=("engines", "provision")), "ecl"),
        ("provision", StressInputConfig(ecl_engine_artifact=("engines", "ecl")), "provision"),
        (
            "provision",
            StressInputConfig(provision_engine_artifact=("engines", "provision")),
            "ecl",
        ),
    ],
)
def test_targets_economicos_requieren_engine_correcto(
    metric: StressMetric,
    input_cfg: StressInputConfig,
    expected_missing: str,
) -> None:
    """Targets económicos fallan si falta el engine específico de su métrica."""
    reverse = ReverseStressConfig(
        enabled=True,
        target=StressTargetConfig(
            name=f"{metric}_25",
            metric=metric,
            threshold=25.0,
            scenario_name="severe_plus",
        ),
        factor="unemployment",
        shock_value=1.0,
    )
    with pytest.raises(StressDependencyError, match=expected_missing):
        _cfg(
            input=input_cfg,
            reverse=(reverse,),
            validation=_validation_relajada(fail_on_missing_ecl_engine=True),
        )


@pytest.mark.parametrize(
    ("metric", "input_cfg"),
    [
        ("ecl", StressInputConfig(ecl_engine_artifact=("engines", "ecl"))),
        (
            "provision",
            StressInputConfig(
                ecl_engine_artifact=("engines", "ecl"),
                provision_engine_artifact=("engines", "provision"),
            ),
        ),
    ],
)
def test_targets_economicos_aceptan_engines_requeridos(
    metric: StressMetric,
    input_cfg: StressInputConfig,
) -> None:
    """Targets económicos aceptan solo la combinación mínima consistente."""
    reverse = ReverseStressConfig(
        enabled=True,
        target=StressTargetConfig(
            name=f"{metric}_25",
            metric=metric,
            threshold=25.0,
            scenario_name="severe_plus",
        ),
        factor="unemployment",
        shock_value=1.0,
    )

    cfg = _cfg(
        input=input_cfg,
        reverse=(reverse,),
        validation=_validation_relajada(fail_on_missing_ecl_engine=True),
    )

    assert cfg.reverse[0].target is not None


def test_operation_relative_se_acepta_por_api_publica() -> None:
    """Los shocks relativos se validan en runtime contra el valor base observado."""
    scenario = _scenario(shocks=(_shock(operation="relative"),))
    cfg = _cfg(scenarios=(scenario,))

    assert cfg.scenarios[0].shocks[0].operation == "relative"


def test_source_official_sin_metadata_falla_falta_dato_str_2() -> None:
    """Escenarios oficiales sin evidencia/hash no se aceptan por default."""
    scenario = _scenario(shocks=(_shock(source="official"),))
    validation = _validation_relajada(fail_on_falta_dato=True)
    with pytest.raises(StressFaltaDatoError, match="FALTA-DATO-STR-2"):
        _cfg(scenarios=(scenario,), validation=validation)


def test_dominancia_forward_adverse_se_difiere_a_runtime() -> None:
    """La dominancia necesita macro_projection y no debe bloquear config puro."""
    scenario = StressScenarioConfig(name="severe_plus", shocks=(_shock(),))
    cfg = StressConfig(scenarios=(scenario,))

    assert cfg.validation.fail_on_falta_dato is True
    assert cfg.validation.require_dominates_forward_adverse is True
    assert cfg.scenarios[0].require_dominates_forward_adverse is True


def test_reverse_target_scenario_name_debe_existir_si_hay_escenarios() -> None:
    """El target reverse debe apuntar a un escenario stress existente cuando se declara."""
    reverse = ReverseStressConfig(
        enabled=True,
        target=StressTargetConfig(
            name="pd_objetivo",
            metric="pd_cumulative",
            threshold=0.25,
            scenario_name="no_existe",
            requires_economic_engine=False,
        ),
        factor="unemployment",
        shock_value=1.0,
    )
    with pytest.raises(StressScenarioError, match="scenario_name"):
        _cfg(reverse=(reverse,))


def test_reverse_deshabilitado_no_valida_target_ni_engines() -> None:
    """Un reverse de borrador disabled no bloquea config por target/engine."""
    disabled_reverse = ReverseStressConfig(
        enabled=False,
        target=StressTargetConfig(
            name="provision_draft",
            metric="provision",
            threshold=25.0,
            scenario_name="no_existe",
        ),
        factor="unemployment",
        shock_value=1.0,
    )

    cfg = _cfg(
        input=StressInputConfig(),
        reverse=(disabled_reverse,),
        validation=_validation_relajada(fail_on_missing_ecl_engine=True),
    )

    assert cfg.reverse[0].enabled is False


def test_reverse_sin_target_pasa_si_no_esta_habilitado() -> None:
    """Un reverse deshabilitado sin target queda permitido como config declarativo."""
    reverse = ReverseStressConfig(factor="unemployment", shock_value=1.0)
    cfg = _cfg(reverse=(reverse,))
    assert cfg.reverse[0].target is None


def test_reverse_target_sin_escenarios_difiere_validacion_de_nombre_al_motor() -> None:
    """Sin escenarios stress declarados, el target reverse se valida luego contra outputs."""
    reverse = ReverseStressConfig(
        enabled=True,
        target=StressTargetConfig(
            name="pd_objetivo",
            metric="pd_cumulative",
            threshold=0.25,
            scenario_name="solo_reverse",
            requires_economic_engine=False,
        ),
        factor="unemployment",
        shock_value=1.0,
    )
    cfg = StressConfig(reverse=(reverse,), validation=_validation_relajada())
    assert cfg.reverse[0].target is not None


def test_falta_dato_activo_sin_dominancia_requerida_no_falla() -> None:
    """``fail_on_falta_dato`` puede quedar activo si no hay brecha demostrable en config."""
    validation = StressValidationConfig(
        require_dominates_forward_adverse=False,
        fail_on_missing_ecl_engine=False,
        fail_on_falta_dato=True,
    )
    cfg = StressConfig(scenarios=(_scenario(),), validation=validation)
    assert cfg.validation.fail_on_falta_dato is True


def test_dominancia_global_activa_no_falla_si_escenario_no_la_exige() -> None:
    """La exigencia global no falla cuando ningún escenario requiere comparar adverse."""
    validation = StressValidationConfig(
        require_dominates_forward_adverse=True,
        fail_on_missing_ecl_engine=False,
        fail_on_falta_dato=True,
    )
    cfg = StressConfig(scenarios=(_scenario(),), validation=validation)
    assert cfg.validation.require_dominates_forward_adverse is True


@pytest.mark.parametrize(
    ("constructor", "kwargs", "error_cls", "match"),
    [
        (StressShockConfig, {"factor": "gdp", "value": math.nan}, StressScenarioError, "finito"),
        (StressShockConfig, {"factor": "gdp", "value": True}, StressScenarioError, "booleano"),
        (
            StressShockConfig,
            {"factor": "gdp", "value": np.bool_(True)},
            StressScenarioError,
            "booleano",
        ),
        (
            StressShockConfig,
            {"factor": "gdp", "value": np.array(True)},
            StressScenarioError,
            "booleano",
        ),
        (
            StressShockConfig,
            {"factor": "gdp", "value": "no-numero"},
            StressScenarioError,
            "finito",
        ),
        (
            StressScenarioConfig,
            {"name": "x", "shocks": (_shock(),), "weight": math.inf},
            StressScenarioError,
            "finito",
        ),
        (
            StressScenarioConfig,
            {"name": "x", "shocks": (_shock(),), "severity": np.bool_(True)},
            StressScenarioError,
            "booleano",
        ),
        (
            StressTargetConfig,
            {"name": "x", "metric": "ecl", "threshold": math.inf, "scenario_name": "s"},
            StressConfigError,
            "finito",
        ),
        (StressValidationConfig, {"probability_tol": math.nan}, StressConfigError, "finito"),
    ],
)
def test_floats_no_finitos_rechazados_con_excepcion_propia(
    constructor: type[object],
    kwargs: dict[str, object],
    error_cls: type[Exception],
    match: str,
) -> None:
    """NaN/inf no entran al config ni al ``config_hash``."""
    with pytest.raises(error_cls, match=match):
        constructor(**kwargs)


def test_group_filter_rechaza_claves_vacias_y_no_finitos() -> None:
    """``group_filter`` debe ser JSON-canónico y determinista."""
    with pytest.raises(StressConfigError, match="claves vacías"):
        StressTargetConfig(
            name="x", metric="pd_marginal", threshold=0.1, scenario_name="s", group_filter={" ": 1}
        )
    with pytest.raises(StressConfigError, match="float finitos"):
        StressTargetConfig(
            name="x",
            metric="pd_marginal",
            threshold=0.1,
            scenario_name="s",
            group_filter={"segment": math.nan},
        )


def test_strings_de_config_no_pueden_ser_vacios() -> None:
    """Los campos declarativos de texto fallan con mensajes propios."""
    with pytest.raises(StressConfigError, match="input"):
        StressInputConfig(forward_domain=" ")
    with pytest.raises(StressConfigError, match="group_cols"):
        SensitivitySweepConfig(name="grid", factor="gdp", shock_value=1.0, group_cols=())
    with pytest.raises(StressConfigError, match="strings vacíos"):
        SensitivitySweepConfig(name="grid", factor="gdp", shock_value=1.0, group_cols=(" ",))
    with pytest.raises(StressScenarioError, match="name"):
        StressScenarioConfig(name=" ", shocks=(_shock(),))
    with pytest.raises(StressScenarioError, match="base_forward_scenario"):
        StressScenarioConfig(name="x", base_forward_scenario=" ", shocks=(_shock(),))


def test_weight_none_explicito_permanece_none() -> None:
    """``weight=None`` explícito conserva el default opcional."""
    scenario = StressScenarioConfig(
        name="x",
        shocks=(_shock(),),
        weight=None,
        require_dominates_forward_adverse=False,
    )
    assert scenario.weight is None


def test_output_metrics_no_puede_ser_vacio() -> None:
    """La salida de stress debe publicar al menos una métrica."""
    with pytest.raises(StressConfigError, match="metrics"):
        StressOutputConfig(metrics=())


def test_output_metrics_rechaza_duplicados() -> None:
    """Las métricas duplicadas duplican filas de impacto y se rechazan en config."""
    with pytest.raises(StressConfigError, match="duplicadas"):
        StressOutputConfig(metrics=("pd_marginal", "pd_marginal"))


@pytest.mark.parametrize(
    ("config_cls", "kwargs"),
    [
        (StressConfig, {"type": "custom"}),
        (StressShockConfig, {"factor": "gdp", "operation": "multiplicative", "value": 1.0}),
        (StressScenarioConfig, {"name": "x", "kind": "regulatory", "shocks": (_shock(),)}),
        (
            SensitivitySweepConfig,
            {"name": "x", "factor": "gdp", "shock_value": 1.0, "metric": "auc"},
        ),
        (
            StressTargetConfig,
            {
                "name": "x",
                "metric": "loss",
                "threshold": 1.0,
                "direction": "above",
                "scenario_name": "s",
            },
        ),
        (ReverseStressConfig, {"factor": "gdp", "shock_value": 1.0, "max_iterations": 0}),
        (StressValidationConfig, {"metric_tol": 1e-2}),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    config_cls: type[object],
    kwargs: dict[str, object],
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        config_cls(**kwargs)


def test_campos_stress_tienen_metadatos_ui() -> None:
    """Todos los campos de config stress declaran metadata de UI para SDD-23."""
    for modelo in (
        StressInputConfig,
        StressShockConfig,
        StressScenarioConfig,
        SensitivitySweepConfig,
        StressTargetConfig,
        ReverseStressConfig,
        StressOutputConfig,
        StressValidationConfig,
        StressConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_stress_public_api_minimo() -> None:
    """El paquete expone config y excepciones de B21.1."""
    assert stress_pkg.StressConfig is StressConfig
    assert stress_pkg.StressError is StressError
    assert "StressConfig" in stress_pkg.__all__


def test_stress_errors_descienden_de_nikodym_error_y_respetan_jerarquia() -> None:
    """Las excepciones de ``stress`` cuelgan de la raíz propia y jerarquía SDD-21."""
    for error_cls in (
        StressError,
        StressConfigError,
        StressInputError,
        StressScenarioError,
        StressEngineError,
        StressOutputError,
        StressDependencyError,
        StressFaltaDatoError,
        ReverseStressError,
        NonMonotonicStressError,
    ):
        assert issubclass(error_cls, NikodymError)
        with pytest.raises(StressError, match="fallo stress"):
            raise error_cls("fallo stress")
    assert issubclass(ReverseStressError, StressEngineError)
    assert issubclass(NonMonotonicStressError, ReverseStressError)


def test_core_study_cablea_stress_en_orden_por_defecto() -> None:
    """``Study`` conoce ``stress`` inmediatamente después de ``forward``."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("forward") < order.index("stress") < order.index("performance")
    assert study_module._DOMAIN_MODULES["stress"] == "nikodym.stress"
    assert study_module._DOMAIN_CONFIG_CLASSES["stress"] == (
        "nikodym.stress.config",
        "StressConfig",
    )


def test_import_stress_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.stress`` registra hook sin arrastrar engines pesados."""
    code = (
        "import nikodym.stress, sys;"
        "assert 'nikodym.stress.results' not in sys.modules;"
        "from nikodym.core.config import schema as _schema;"
        "assert _schema._STRESS_CONFIG_CLS is nikodym.stress.StressConfig;"
        "from nikodym.core.config import NikodymConfig;"
        "bloqueados=[m for m in ('pandas','numpy','scipy','statsmodels','nikodym.provisioning') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(stress={'scenarios':[{'name':'severe_plus',"
        "'shocks':[{'factor':'unemployment','value':1.5}],"
        "'require_dominates_forward_adverse':False}],"
        "'validation':{'require_dominates_forward_adverse':False,"
        "'fail_on_falta_dato':False,'fail_on_missing_ecl_engine':False}});"
        "assert type(cfg.stress).__name__ == 'StressConfig';"
        "assert type(cfg.stress).__module__ == 'nikodym.stress.config';"
        "bloqueados=[m for m in ('pandas','numpy','scipy','statsmodels','nikodym.provisioning') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "assert 'nikodym.stress.results' not in sys.modules;"
        "assert isinstance(cfg.stress, nikodym.stress.StressConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_config_stress_no_importa_numpy_pandas_scipy_statsmodels() -> None:
    """``config.py`` no declara imports pesados propios de motores."""
    assert stress_config_module.__file__ is not None
    contenido = Path(stress_config_module.__file__).read_text(encoding="utf-8")
    assert "import numpy" not in contenido
    assert "import pandas" not in contenido
    assert "import scipy" not in contenido
    assert "import statsmodels" not in contenido
