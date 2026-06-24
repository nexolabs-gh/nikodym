"""Tests de ``core.artifacts`` (SDD-01 §6/§7): almacén namespaced ``(domain, key)`` en memoria.

Cubren el round-trip por identidad, los errores de ausencia/duplicado, el namespacing cruzado y la
emisión de ``AuditEvent`` ``"artifact"`` en escritura inicial y sobrescritura (flag ``overwrite``).
"""

from __future__ import annotations

import pytest

from nikodym.core.artifacts import ArtifactStore
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ArtifactExistsError, ArtifactNotFoundError


def test_set_get_round_trip_por_identidad() -> None:
    """``get`` tras ``set`` devuelve el mismo objeto (identidad, sin copia)."""
    store = ArtifactStore()
    obj = [1, 2, 3]
    store.set("data", "frame", obj)
    assert store.get("data", "frame") is obj


def test_get_ausente_levanta() -> None:
    """``get`` de una clave ausente levanta ``ArtifactNotFoundError`` citando domain/key."""
    store = ArtifactStore()
    with pytest.raises(ArtifactNotFoundError, match=r"'data'.*'frame'"):
        store.get("data", "frame")


def test_set_duplicado_sin_overwrite_levanta() -> None:
    """Reescribir sin ``overwrite=True`` levanta ``ArtifactExistsError``."""
    store = ArtifactStore()
    store.set("data", "frame", 1)
    with pytest.raises(ArtifactExistsError, match=r"'data'.*'frame'"):
        store.set("data", "frame", 2)


def test_overwrite_sobrescribe() -> None:
    """``overwrite=True`` sobrescribe sin levantar."""
    store = ArtifactStore()
    store.set("data", "frame", 1)
    store.set("data", "frame", 2, overwrite=True)
    assert store.get("data", "frame") == 2


def test_has_y_keys() -> None:
    """``has`` refleja presencia; ``keys`` lista las claves en orden de inserción."""
    store = ArtifactStore()
    assert not store.has("data", "frame")
    store.set("data", "frame", 1)
    store.set("model", "fit", 2)
    assert store.has("data", "frame")
    assert store.keys() == [("data", "frame"), ("model", "fit")]


def test_namespacing_cruzado() -> None:
    """``(data, frame)`` y ``(model, frame)`` son claves distintas."""
    store = ArtifactStore()
    store.set("data", "frame", "a")
    store.set("model", "frame", "b")
    assert store.get("data", "frame") == "a"
    assert store.get("model", "frame") == "b"


def test_set_inicial_emite_artifact() -> None:
    """La escritura inicial emite un ``AuditEvent`` ``artifact`` con ``overwrite=False``."""
    sink = InMemoryAuditSink()
    store = ArtifactStore(audit=sink)
    store.set("data", "frame", 1)
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.kind == "artifact"
    assert ev.step == "data"
    assert ev.payload == {"domain": "data", "key": "frame", "overwrite": False}


def test_overwrite_emite_artifact_con_flag() -> None:
    """La sobrescritura emite un segundo ``artifact`` con ``overwrite=True``."""
    sink = InMemoryAuditSink()
    store = ArtifactStore(audit=sink)
    store.set("data", "frame", 1)
    store.set("data", "frame", 2, overwrite=True)
    assert len(sink.events) == 2
    assert sink.events[1].payload == {"domain": "data", "key": "frame", "overwrite": True}


def test_audit_none_cae_a_null_sink() -> None:
    """Sin sink (``audit=None``), ``set`` no falla (emit no-op seguro)."""
    store = ArtifactStore()
    store.set("data", "frame", 1)  # no levanta
    assert store.has("data", "frame")
