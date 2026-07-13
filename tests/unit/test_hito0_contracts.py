"""Pruebas de fuego B4.2 para los contratos transversales del Hito 0."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nikodym.audit import EnvironmentSnapshot
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ConfigError
from nikodym.core.lineage import LineageBundle
from nikodym.core.steps import ArtifactKey
from nikodym.core.study import Study
from nikodym.governance import GovernanceConfig, ModelCardBuilder, OverlayRecord, ScenarioLog
from nikodym.testing import (
    REGULATORY_COVERAGE_INCLUDE,
    REGULATORY_COVERAGE_PATHS,
    minimal_study,
    missing_regulatory_coverage_paths,
    regulatory_coverage_include_arg,
    regulatory_coverage_paths,
)
from nikodym.tracking import TrackingConfig, TrackingRecorder

_TS = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)
_REVIEW_TS = datetime(2026, 6, 25, 14, 30, 0, tzinfo=UTC)
_ENVIRONMENT = EnvironmentSnapshot(
    python_version="3.12.9",
    platform="macOS-15-arm64",
    library_versions={"nikodym": "0.1.0", "pydantic": "2.13.0"},
    uv_lock_hash="uvhash",
    captured_at=datetime(2026, 6, 25, 13, 0, 0, tzinfo=UTC),
)
_EXPECTED_ECL_SECTIONS_JSON = (
    '{"ecl_by_stage_scenario":{"stage_1":{"adverso":51.428571,"base":42.857143},'
    '"stage_2":{"adverso":150.0,"base":125.0},"stage_3":{"adverso":333.25,'
    '"base":310.75}}}'
)
_EXPECTED_OVERLAY_PAYLOAD_JSON = (
    '{"pd_curve":{"stage_2":{"adverso":[0.15,0.24],"base":[0.12,0.18]}},'
    '"scenario_weights":{"adverso":0.35,"base":0.65}}'
)
_EXPECTED_REGULATORY_PATHS = (
    "src/nikodym/core/exceptions.py",
    "src/nikodym/core/seeding.py",
    "src/nikodym/provisioning/cmf/__init__.py",
    "src/nikodym/provisioning/ifrs9/__init__.py",
    # SDD-28: el método interno del B-1 entra COMPLETO al gate (no sólo su `__init__`).
    "src/nikodym/provisioning/internal/__init__.py",
    "src/nikodym/provisioning/internal/config.py",
    "src/nikodym/provisioning/internal/engine.py",
    "src/nikodym/provisioning/internal/exceptions.py",
    "src/nikodym/provisioning/internal/results.py",
    "src/nikodym/provisioning/internal/step.py",
)
_EXPECTED_REGULATORY_INCLUDE_ARG = (
    "*/nikodym/core/exceptions.py,"
    "*/nikodym/core/seeding.py,"
    "*/nikodym/provisioning/cmf/__init__.py,"
    "*/nikodym/provisioning/ifrs9/__init__.py,"
    "*/nikodym/provisioning/internal/__init__.py,"
    "*/nikodym/provisioning/internal/config.py,"
    "*/nikodym/provisioning/internal/engine.py,"
    "*/nikodym/provisioning/internal/exceptions.py,"
    "*/nikodym/provisioning/internal/results.py,"
    "*/nikodym/provisioning/internal/step.py"
)


class _BinningProvider:
    """Proveedor dummy de un artefacto de binning."""

    name = "binning"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = (("binning", "woe_table"),)

    def execute(self, study: Study, rng: Any) -> dict[str, float]:
        """Publica un artefacto de binning determinista."""
        del rng
        payload = {"iv": 0.123456, "woe": -0.45}
        study.artifacts.set("binning", "woe_table", payload)
        return payload


class _CalibrationProvider:
    """Proveedor dummy de un artefacto de calibración."""

    name = "calibration"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = (("calibration", "pd_curve"),)

    def execute(self, study: Study, rng: Any) -> dict[str, dict[str, float]]:
        """Publica una curva PD mínima por stage y escenario."""
        del rng
        payload = {
            "stage_1": {"base": 0.025, "adverso": 0.031},
            "stage_2": {"base": 0.085, "adverso": 0.11},
        }
        study.artifacts.set("calibration", "pd_curve", payload)
        return payload


class _FanInECLStep:
    """Step dummy con fan-in real desde dos dominios distintos."""

    name = "ifrs9"
    requires: tuple[ArtifactKey, ...] = (
        ("binning", "woe_table"),
        ("calibration", "pd_curve"),
    )
    provides: tuple[ArtifactKey, ...] = (("ifrs9", "ecl_dummy"),)

    def __init__(self) -> None:
        self.executed = False

    def execute(self, study: Study, rng: Any) -> dict[str, float]:
        """Lee dos dominios y publica una salida compuesta."""
        del rng
        self.executed = True
        woe_table = study.artifacts.get("binning", "woe_table")
        pd_curve = study.artifacts.get("calibration", "pd_curve")
        result = {
            "iv": woe_table["iv"],
            "stage_2_base_pd": pd_curve["stage_2"]["base"],
        }
        study.artifacts.set("ifrs9", "ecl_dummy", result)
        return result


class _MetricsOnlyMLflow:
    """Fake mínimo para ejercer ``TrackingRecorder.log_metrics``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def log_metric(self, key: str, value: float, *, step: int | None = None) -> None:
        """Registra una métrica fake."""
        self.calls.append(("log_metric", (key, value, step)))

    def log_dict(self, payload: dict[str, Any], artifact_file: str) -> None:
        """Registra un artefacto JSON fake."""
        self.calls.append(("log_dict", (artifact_file, payload)))


def _ecl_metric_sections() -> dict[str, Any]:
    """Metric sections ECL-like stage x escenario con golden values."""
    return {
        "ecl_by_stage_scenario": {
            "stage_1": {"base": 42.857143, "adverso": 51.428571},
            "stage_2": {"base": 125.0, "adverso": 150.0},
            "stage_3": {"base": 310.75, "adverso": 333.25},
        }
    }


def _overlay_payload() -> dict[str, Any]:
    """Payload no escalar de overlay IFRS 9 dummy."""
    return {
        "pd_curve": {
            "stage_2": {
                "base": [0.12, 0.18],
                "adverso": [0.15, 0.24],
            }
        },
        "scenario_weights": {"base": 0.65, "adverso": 0.35},
    }


def _json_compacto(value: Any) -> str:
    """Serializa a JSON compacto y ordenado para golden values."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _lineage() -> LineageBundle:
    """Lineage determinista para construir model cards sin depender del git real."""
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123",
        config_hash="cfg123",
        root_seed=42,
        uv_lock_hash="uvhash",
        library_versions={"nikodym": "0.1.0"},
        determinism_caveats=[],
        created_at=_TS,
        schema_version="1.0.0",
    )


def _study_with_metric_sections(metric_sections: dict[str, Any]) -> Study:
    """Study finalizado con métricas escalares y secciones estructuradas."""
    study = Study(NikodymConfig())
    study.run_context.status = "done"
    study.run_context.run_id = "hito0-run"
    study.run_context.lineage = _lineage()
    study.results["metrics"] = {"auc": 0.8125}
    study.results["metric_sections"] = metric_sections
    return study


def _model_card_builder() -> ModelCardBuilder:
    """Builder determinista para fijar golden values de CT-2."""
    return ModelCardBuilder(
        GovernanceConfig(purpose="Prueba CT-2 payload estructurado"),
        now=lambda: _REVIEW_TS,
        environment_provider=lambda: _ENVIRONMENT,
    )


def test_hito0_ct1_step_dummy_fan_in_satisfecho(monkeypatch: pytest.MonkeyPatch) -> None:
    """CT-1: un Step con fan-in de dos dominios corre si ambos proveedores están aguas arriba."""
    study = minimal_study()
    fan_in_step = _FanInECLStep()
    steps = [_BinningProvider(), _CalibrationProvider(), fan_in_step]
    monkeypatch.setattr(study, "_resolve_steps", lambda nombres: steps)

    study.run(steps=["binning", "calibration", "ifrs9"])

    assert fan_in_step.executed is True
    assert study.run_context.status == "done"
    assert study.artifacts.get("ifrs9", "ecl_dummy") == {
        "iv": 0.123456,
        "stage_2_base_pd": 0.085,
    }


def test_hito0_ct1_step_dummy_fan_in_faltante_falla_pre_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CT-1: si falta un dominio del fan-in, Study falla antes de ejecutar pasos."""
    study = minimal_study()
    fan_in_step = _FanInECLStep()
    steps = [_BinningProvider(), fan_in_step]
    monkeypatch.setattr(study, "_resolve_steps", lambda nombres: steps)

    with pytest.raises(ConfigError, match=r"calibration.*pd_curve.*inejecutable"):
        study.run(steps=["binning", "ifrs9"])

    assert fan_in_step.executed is False
    assert study.run_context.status == "created"
    assert study.artifacts.keys() == []


def test_hito0_ct2_metric_sections_pasan_por_log_metrics_y_model_card(
    tmp_path: Path,
) -> None:
    """CT-2: metric_sections ECL-like soporta payload estructurado y snapshot profundo."""
    metric_sections = _ecl_metric_sections()
    fake_mlflow = _MetricsOnlyMLflow()
    recorder = TrackingRecorder(TrackingConfig(), mlflow_module=fake_mlflow)

    recorder.log_metrics({"metrics": {"auc": 0.8125}, "metric_sections": metric_sections}, step=4)

    assert ("log_metric", ("auc", 0.8125, 4)) in fake_mlflow.calls
    results_payload = next(value for name, value in fake_mlflow.calls if name == "log_dict")[1]
    assert results_payload == {"metric_sections": _ecl_metric_sections()}
    assert _json_compacto(results_payload["metric_sections"]) == _EXPECTED_ECL_SECTIONS_JSON

    trail_path = tmp_path / "audit.jsonl"
    trail_path.write_text("", encoding="utf-8")
    card = _model_card_builder().build(
        _study_with_metric_sections(metric_sections),
        trail_path=trail_path,
    )

    assert card.metric_sections == _ecl_metric_sections()
    assert _json_compacto(json.loads(card.to_json())["metric_sections"]) == (
        _EXPECTED_ECL_SECTIONS_JSON
    )

    metric_sections["ecl_by_stage_scenario"]["stage_2"]["adverso"] = 999.0
    assert results_payload["metric_sections"] == _ecl_metric_sections()
    assert card.metric_sections == _ecl_metric_sections()


def test_hito0_ct2_overlay_payload_no_escalar_toma_snapshot_y_round_trip_jsonl(
    tmp_path: Path,
) -> None:
    """CT-2: OverlayRecord acepta payload no escalar y no queda aliasado al input."""
    payload = _overlay_payload()
    overlay = OverlayRecord(
        overlay_id="ov-hito0",
        scope="ifrs9.stage2.consumo",
        justification="Overlay dummy estructurado",
        author="riesgo@example.com",
        value_before=125.0,
        value_after=150.0,
        payload=payload,
        approved_by="comite",
        ts=_TS,
    )

    payload["pd_curve"]["stage_2"]["base"][0] = 9.99
    assert overlay.payload == _overlay_payload()
    assert _json_compacto(overlay.payload) == _EXPECTED_OVERLAY_PAYLOAD_JSON

    log = ScenarioLog(tmp_path / "scenario_log.jsonl")
    log.log_overlay(overlay)
    read_back = log.read()[0]
    assert isinstance(read_back, OverlayRecord)
    assert read_back.payload == _overlay_payload()

    line = (tmp_path / "scenario_log.jsonl").read_text(encoding="utf-8").strip()
    assert _json_compacto(json.loads(line)["payload"]) == _EXPECTED_OVERLAY_PAYLOAD_JSON


def test_hito0_gate_regulatorio_declara_paths_existentes() -> None:
    """El gate regulatorio usa la lista canónica y falla si un path declarado no existe."""
    repo_root = Path(__file__).resolve().parents[2]

    assert REGULATORY_COVERAGE_PATHS == _EXPECTED_REGULATORY_PATHS
    assert tuple(_EXPECTED_REGULATORY_INCLUDE_ARG.split(",")) == REGULATORY_COVERAGE_INCLUDE
    assert regulatory_coverage_include_arg() == _EXPECTED_REGULATORY_INCLUDE_ARG
    assert missing_regulatory_coverage_paths(repo_root) == ()
    assert all(path.is_file() for path in regulatory_coverage_paths(repo_root))


def test_hito0_gate_regulatorio_detecta_vacuidad_si_falta_path(tmp_path: Path) -> None:
    """La misma lista falla ruidoso contra una raíz sin módulos regulatorios."""
    missing = tuple(
        path.relative_to(tmp_path).as_posix()
        for path in missing_regulatory_coverage_paths(tmp_path)
    )
    assert missing == _EXPECTED_REGULATORY_PATHS
