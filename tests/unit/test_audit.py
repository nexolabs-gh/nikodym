"""Tests de ``core.audit`` (SDD-01 §4): AuditEvent + los tres *sinks* fundacionales.

Verifican el contrato de eventos (kinds válidos, round-trip JSON, payload estructurado — CT-2),
los invariantes de los *sinks* (Null no-op, InMemory ordenado, FanOut reparte a todos) y la
conformidad estructural con el Protocol :class:`AuditSink`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nikodym.core.audit import (
    AuditEvent,
    AuditSink,
    FanOutSink,
    InMemoryAuditSink,
    NullAuditSink,
)

_TS = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _event(kind: str = "decision", step: str | None = "binning") -> AuditEvent:
    return AuditEvent(
        kind=kind,  # type: ignore[arg-type]
        step=step,
        payload={"regla": "max_iv", "umbral": 0.02, "valor": 0.015, "accion": "descartó"},
        ts=_TS,
    )


# --- AuditEvent -------------------------------------------------------------------------------


def test_audit_event_acepta_los_cuatro_kinds() -> None:
    """Los 4 únicos kinds que ``core`` emite construyen sin error."""
    for kind in ("run_start", "decision", "artifact", "run_end"):
        ev = AuditEvent(kind=kind, step=None, payload={}, ts=_TS)  # type: ignore[arg-type]
        assert ev.kind == kind


def test_audit_event_kind_invalido_levanta() -> None:
    """Un kind fuera del Literal es ValidationError de Pydantic."""
    with pytest.raises(ValidationError):
        AuditEvent(kind="foo", step=None, payload={}, ts=_TS)  # type: ignore[arg-type]


def test_audit_event_step_none_y_step_nombrado_validos() -> None:
    """``step=None`` (evento de nivel-run) y ``step="binning"`` (evento de paso) son válidos."""
    assert AuditEvent(kind="run_start", step=None, payload={}, ts=_TS).step is None
    assert _event(step="binning").step == "binning"


def test_audit_event_round_trip_json_sin_perdida() -> None:
    """model_dump(mode='json') → json → model_validate reconstruye el evento idéntico."""
    ev = _event()
    raw = json.dumps(ev.model_dump(mode="json"), ensure_ascii=False)
    ev2 = AuditEvent.model_validate(json.loads(raw))
    assert ev2 == ev
    assert ev2.ts == _TS


def test_audit_event_round_trip_preserva_tildes() -> None:
    """``ensure_ascii=False`` conserva tildes/ñ en el payload (sin mojibake)."""
    ev = AuditEvent(
        kind="decision",
        step="selección",
        payload={"acción": "descartó por años", "razón": "señal débil"},
        ts=_TS,
    )
    raw = json.dumps(ev.model_dump(mode="json"), ensure_ascii=False)
    assert "descartó" in raw and "señal" in raw
    assert AuditEvent.model_validate(json.loads(raw)) == ev


def test_audit_event_payload_estructurado_aguanta() -> None:
    """CT-2 (criterio de aceptación F0): un payload ECL-like por stage x escenario no rompe."""
    payload = {
        "metric_sections": {
            "ecl": {
                "base": {"stage_1": [0.1, 0.2], "stage_2": [0.3, 0.4]},
                "adverso": {"stage_1": [0.2, 0.3], "stage_2": [0.5, 0.6]},
            }
        }
    }
    ev = AuditEvent(kind="decision", step="ecl", payload=payload, ts=_TS)
    ev2 = AuditEvent.model_validate(json.loads(json.dumps(ev.model_dump(mode="json"))))
    assert ev2.payload == payload


def test_audit_event_es_inmutable() -> None:
    """``frozen=True``: reasignar un campo levanta ValidationError."""
    ev = _event()
    with pytest.raises(ValidationError):
        ev.kind = "run_end"  # type: ignore[misc]


# --- NullAuditSink ----------------------------------------------------------------------------


def test_null_sink_emit_devuelve_none_y_no_acumula() -> None:
    """NullAuditSink descarta todo: emit → None, sin estado, no levanta tras N llamadas."""
    sink = NullAuditSink()
    for _ in range(3):
        assert sink.emit(_event()) is None
    assert not hasattr(sink, "events")


# --- InMemoryAuditSink ------------------------------------------------------------------------


def test_in_memory_sink_arranca_vacio() -> None:
    """Recién construido, ``.events`` es una lista vacía (no None)."""
    assert InMemoryAuditSink().events == []


def test_in_memory_sink_acumula_en_orden() -> None:
    """Emitir la secuencia canónica acumula los 4 eventos en orden (oráculo SDD-01 §11)."""
    sink = InMemoryAuditSink()
    secuencia = [
        AuditEvent(kind="run_start", step=None, payload={}, ts=_TS),
        _event(kind="decision"),
        AuditEvent(kind="artifact", step="binning", payload={"key": ("binning", "woe")}, ts=_TS),
        AuditEvent(kind="run_end", step=None, payload={"status": "ok"}, ts=_TS),
    ]
    for ev in secuencia:
        sink.emit(ev)
    assert sink.events == secuencia
    assert [e.kind for e in sink.events] == ["run_start", "decision", "artifact", "run_end"]


# --- FanOutSink -------------------------------------------------------------------------------


def test_fan_out_reparte_a_todos_los_sinks() -> None:
    """Un evento emitido por FanOutSink llega a cada *sink* subordinado."""
    s1, s2 = InMemoryAuditSink(), InMemoryAuditSink()
    fan = FanOutSink([s1, s2])
    ev = _event()
    fan.emit(ev)
    assert s1.events == [ev]
    assert s2.events == [ev]


def test_fan_out_lista_vacia_es_no_op() -> None:
    """FanOutSink([]) emite sin levantar (no-op silencioso)."""
    FanOutSink([]).emit(_event())


def test_fan_out_preserva_orden_en_cada_sink() -> None:
    """Al emitir varios eventos, cada *sink* subordinado conserva el orden de emisión."""
    s1, s2 = InMemoryAuditSink(), InMemoryAuditSink()
    fan = FanOutSink([s1, s2])
    eventos = [_event(kind="run_start"), _event(kind="decision"), _event(kind="run_end")]
    for ev in eventos:
        fan.emit(ev)
    assert s1.events == eventos
    assert s2.events == eventos


# --- Conformidad con el Protocol AuditSink ----------------------------------------------------


def test_los_tres_sinks_satisfacen_el_protocol() -> None:
    """Una función que pide ``AuditSink`` acepta los tres *sinks* (tipado estructural)."""

    def consumir(sink: AuditSink, ev: AuditEvent) -> None:
        sink.emit(ev)

    ev = _event()
    for sink in (NullAuditSink(), InMemoryAuditSink(), FanOutSink([InMemoryAuditSink()])):
        consumir(sink, ev)
