"""Tests de ``nikodym.audit``: sink JSONL y replay del audit-trail."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nikodym.audit import AuditConfig, AuditError, JsonlAuditSink, iter_trail, read_trail
from nikodym.core.audit import AuditEvent

_TS = datetime(2026, 6, 25, 12, 30, 0, tzinfo=UTC)
_GOLDEN_START_LINE = (
    '{"kind":"run_start","payload":{"name":"estudio café","run_id":"r-001"},'
    '"step":null,"ts":"2026-06-25T12:30:00Z"}'
)
_GOLDEN_DECISION_LINE = (
    '{"kind":"decision","payload":{"acción":"descartó por años","regla":"mora >= 90"},'
    '"step":"selección","ts":"2026-06-25T12:30:00Z"}'
)
_GOLDEN_END_LINE = (
    '{"kind":"run_end","payload":{"run_id":"r-001","status":"done"},'
    '"step":null,"ts":"2026-06-25T12:30:00Z"}'
)


class _FailingHandle:
    """Handle mínimo que simula un fallo de escritura."""

    def write(self, text: str) -> int:
        """Levanta ``OSError`` para cubrir el envoltorio ``AuditError``."""
        raise OSError("disco lleno")

    def flush(self) -> None:
        """No-op: ``emit`` no llega aquí porque ``write`` falla."""
        return None


def _event(kind: str = "decision") -> AuditEvent:
    """Evento canónico con tildes/ñ para verificar JSONL UTF-8."""
    if kind == "run_start":
        return AuditEvent(
            kind="run_start",
            step=None,
            payload={"run_id": "r-001", "name": "estudio café"},
            ts=_TS,
        )
    if kind == "run_end":
        return AuditEvent(
            kind="run_end",
            step=None,
            payload={"run_id": "r-001", "status": "done"},
            ts=_TS,
        )
    return AuditEvent(
        kind="decision",
        step="selección",
        payload={"regla": "mora >= 90", "acción": "descartó por años"},
        ts=_TS,
    )


def test_jsonl_sink_round_trip_append_only_utf8_y_orden(tmp_path: Path) -> None:
    """Emitir → escribir → leer reconstruye eventos idénticos y conserva líneas previas."""
    path = tmp_path / "audit_trail.jsonl"
    start, decision, end = _event("run_start"), _event(), _event("run_end")

    with JsonlAuditSink(path, flush_each=True) as sink:
        assert sink.__enter__() is sink
        sink.emit(start)
        sink.emit(decision)

    first_text = path.read_text(encoding="utf-8")
    assert first_text == f"{_GOLDEN_START_LINE}\n{_GOLDEN_DECISION_LINE}\n"
    assert "café" in first_text and "selección" in first_text and "\\u" not in first_text
    assert read_trail(path) == [start, decision]

    with JsonlAuditSink(path, config=AuditConfig(flush_each=False)) as sink:
        assert sink.flush_each is False
        sink.emit(end)

    second_text = path.read_text(encoding="utf-8")
    assert second_text == f"{first_text}{_GOLDEN_END_LINE}\n"
    assert [event.kind for event in iter_trail(path)] == ["run_start", "decision", "run_end"]
    assert read_trail(path) == [start, decision, end]


def test_sink_close_idempotente_y_emit_cerrado_levanta(tmp_path: Path) -> None:
    """``close`` puede llamarse dos veces y emitir tras cerrar falla ruidoso."""
    sink = JsonlAuditSink(tmp_path / "trail.jsonl")
    sink.close()
    sink.close()

    with pytest.raises(AuditError, match="ya está cerrado"):
        sink.emit(_event())


def test_sink_envuelve_error_de_apertura_y_escritura(tmp_path: Path) -> None:
    """Errores de I/O se traducen a ``AuditError`` con contexto del trail."""
    parent_as_file = tmp_path / "no_es_directorio"
    parent_as_file.write_text("x", encoding="utf-8")
    with pytest.raises(AuditError, match="No se pudo abrir"):
        JsonlAuditSink(parent_as_file / "trail.jsonl")

    sink = JsonlAuditSink(tmp_path / "ok.jsonl")
    sink.close()
    sink._handle = _FailingHandle()  # type: ignore[assignment]
    with pytest.raises(AuditError, match="No se pudo escribir"):
        sink.emit(_event())
    sink._handle = None


def test_replay_descarta_linea_final_truncada(tmp_path: Path) -> None:
    """Una cola truncada por crash se descarta y las líneas previas siguen válidas."""
    path = tmp_path / "trail.jsonl"
    path.write_text(f'{_GOLDEN_START_LINE}\n{{"kind":', encoding="utf-8")

    with pytest.warns(UserWarning, match="línea\\(s\\) finales corruptas"):
        events = read_trail(path)

    assert events == [_event("run_start")]


def test_replay_linea_intermedia_corrupta_levanta(tmp_path: Path) -> None:
    """Una corrupción intermedia no se trata como crash de cola."""
    path = tmp_path / "trail.jsonl"
    path.write_text(
        f'{_GOLDEN_START_LINE}\n{{"kind":\n{_GOLDEN_END_LINE}\n',
        encoding="utf-8",
    )

    with pytest.raises(AuditError, match="línea intermedia 2"):
        read_trail(path)


def test_replay_fichero_ausente_levanta_auditerror(tmp_path: Path) -> None:
    """Un trail inexistente falla con excepción propia del módulo."""
    with pytest.raises(AuditError, match="No se pudo leer"):
        read_trail(tmp_path / "no_existe.jsonl")
