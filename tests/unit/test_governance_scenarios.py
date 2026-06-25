"""Tests del scenario log y overlays de ``nikodym.governance``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from nikodym.governance import GovernanceError, OverlayRecord, ScenarioLog, ScenarioRecord

_TS = datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)
_GOLDEN_SCENARIO_LINE = (
    '{"kind":"adverso","params":{"ipc":0.07,"unemployment":0.11},'
    '"record_type":"scenario","scenario_id":"macro-adv","ts":"2026-06-25T12:00:00Z",'
    '"weight":0.35}'
)
_GOLDEN_OVERLAY_LINE = (
    '{"approved_by":"comite","author":"riesgo@example.com","justification":"Shock supervisor",'
    '"overlay_id":"ov-1","payload":{"curve":[0.1,0.2]},"record_type":"overlay",'
    '"scope":"ifrs9.stage2.consumo","ts":"2026-06-25T12:00:00Z","value_after":0.2,'
    '"value_before":0.1}'
)


def _scenario() -> ScenarioRecord:
    """Escenario sintético con parámetros macro."""
    return ScenarioRecord(
        scenario_id="macro-adv",
        kind="adverso",
        weight=0.35,
        params={"unemployment": 0.11, "ipc": 0.07},
        ts=_TS,
    )


def _overlay() -> OverlayRecord:
    """Overlay sintético con payload estructurado CT-2."""
    return OverlayRecord(
        overlay_id="ov-1",
        scope="ifrs9.stage2.consumo",
        justification="  Shock supervisor  ",
        author="riesgo@example.com",
        value_before=0.1,
        value_after=0.2,
        payload={"curve": [0.1, 0.2]},
        approved_by="comite",
        ts=_TS,
    )


def test_overlay_justification_obligatoria_y_no_vacia() -> None:
    """La justificación falta/blanco falla en validación antes de escribir."""
    with pytest.raises(ValidationError):
        OverlayRecord(
            overlay_id="ov-1",
            scope="x",
            author="a",
            value_before=0.1,
            value_after=0.2,
            ts=_TS,
        )
    with pytest.raises(ValidationError, match="justification"):
        OverlayRecord(
            overlay_id="ov-1",
            scope="x",
            justification="   ",
            author="a",
            value_before=0.1,
            value_after=0.2,
            ts=_TS,
        )

    assert _overlay().justification == "Shock supervisor"


def test_scenario_record_valida_peso() -> None:
    """El peso de escenario, si existe, debe estar en [0, 1]."""
    with pytest.raises(ValidationError):
        ScenarioRecord(scenario_id="x", kind="base", weight=1.2, params={}, ts=_TS)


def test_scenario_log_round_trip_append_only_y_golden(tmp_path: Path) -> None:
    """Escenarios y overlays se escriben como JSONL canónico y se revalidan al leer."""
    path = tmp_path / "scenario_log.jsonl"
    log = ScenarioLog(path)
    assert log.read() == []

    scenario = _scenario()
    overlay = _overlay()
    log.log_scenario(scenario)
    first_text = path.read_text(encoding="utf-8")
    assert first_text == f"{_GOLDEN_SCENARIO_LINE}\n"
    log.log_overlay(overlay)

    assert path.read_text(encoding="utf-8") == (
        f"{_GOLDEN_SCENARIO_LINE}\n{_GOLDEN_OVERLAY_LINE}\n"
    )
    assert log.read() == [scenario, overlay]


def test_scenario_log_rechaza_overlay_manipulado_sin_justificacion(tmp_path: Path) -> None:
    """Incluso con ``model_construct``, log_overlay defiende la regla anti earnings-management."""
    log = ScenarioLog(tmp_path / "scenario_log.jsonl")
    overlay = OverlayRecord.model_construct(
        overlay_id="ov-1",
        scope="x",
        justification=" ",
        author="a",
        value_before=0.0,
        value_after=1.0,
        payload=None,
        approved_by=None,
        ts=_TS,
    )

    with pytest.raises(GovernanceError, match="sin justificación"):
        log.log_overlay(overlay)


def test_scenario_log_envuelve_errores_de_directorio_y_escritura(tmp_path: Path) -> None:
    """Errores de I/O se traducen a ``GovernanceError`` con contexto."""
    parent_as_file = tmp_path / "no_es_dir"
    parent_as_file.write_text("x", encoding="utf-8")
    with pytest.raises(GovernanceError, match="directorio"):
        ScenarioLog(parent_as_file / "scenario.jsonl")

    log = ScenarioLog(tmp_path / "ok.jsonl")
    log.path = tmp_path
    with pytest.raises(GovernanceError, match="escribir"):
        log.log_scenario(_scenario())


def test_scenario_log_envuelve_errores_de_lectura(tmp_path: Path) -> None:
    """Leer un directorio como fichero falla con excepción propia."""
    log = ScenarioLog(tmp_path / "ok.jsonl")
    log.path = tmp_path
    with pytest.raises(GovernanceError, match="leer"):
        log.read()


@pytest.mark.parametrize(
    "line",
    [
        "{no-json}\n",
        '{"record_type":"scenario","scenario_id":"x"}\n',
    ],
)
def test_scenario_log_corrupto_levanta(tmp_path: Path, line: str) -> None:
    """JSON inválido o payload incompleto no se aceptan como trail auditable."""
    path = tmp_path / "scenario_log.jsonl"
    path.write_text(line, encoding="utf-8")

    with pytest.raises(GovernanceError, match="línea 1"):
        ScenarioLog(path).read()


def test_scenario_log_record_type_desconocido_levanta(tmp_path: Path) -> None:
    """Un record_type ajeno al contrato falla ruidoso."""
    path = tmp_path / "scenario_log.jsonl"
    path.write_text('{"record_type":"otro"}\n', encoding="utf-8")

    with pytest.raises(GovernanceError, match="record_type desconocido"):
        ScenarioLog(path).read()
