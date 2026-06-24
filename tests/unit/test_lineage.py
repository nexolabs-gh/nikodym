"""Tests de ``core.lineage`` (SDD-01 §4): ``LineageBundle`` y ``RunContext``.

El test ancla es el **DoD F0**: ``RunContext()`` arranca en ``"created"`` y serializa sin valores
ficticios (nulls, no UUIDs/timestamps inventados), de modo que un ``Study`` vacío se crea, serializa
y recarga.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nikodym.core.lineage import LineageBundle, RunContext

_CREATED = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


def _bundle() -> LineageBundle:
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="deadbeef",
        config_hash="02b667fc",
        root_seed=42,
        uv_lock_hash="lockhash",
        library_versions={"numpy": "2.3.3", "pandas": "2.3.3"},
        determinism_caveats=["GBDT multihilo no determinista"],
        created_at=_CREATED,
        schema_version="1.0.0",
    )


# --- RunContext (DoD F0) ----------------------------------------------------------------------


def test_run_context_arranca_en_created() -> None:
    """DoD F0: ``RunContext()`` construye sin argumentos en ``created`` y lo demás en None."""
    ctx = RunContext()
    assert ctx.status == "created"
    assert ctx.run_id is None
    assert ctx.started_at is None
    assert ctx.finished_at is None
    assert ctx.lineage is None


def test_run_context_serializa_sin_valores_ficticios() -> None:
    """DoD F0: el volcado de un ``RunContext`` recién creado es todo nulls, sin datos inventados."""
    assert RunContext().model_dump(mode="json") == {
        "run_id": None,
        "started_at": None,
        "finished_at": None,
        "status": "created",
        "lineage": None,
    }


def test_run_context_round_trip() -> None:
    """``RunContext`` recarga idéntico desde su volcado JSON (run_metadata.json)."""
    ctx = RunContext()
    assert RunContext.model_validate(ctx.model_dump(mode="json")) == ctx


@pytest.mark.parametrize("status", ["created", "running", "done", "failed"])
def test_run_context_status_validos(status: str) -> None:
    """Los 4 estados del Literal son válidos."""
    assert RunContext(status=status).status == status  # type: ignore[arg-type]


def test_run_context_status_invalido_levanta() -> None:
    """Un estado fuera del Literal levanta ``ValidationError``."""
    with pytest.raises(ValidationError):
        RunContext(status="paused")  # type: ignore[arg-type]


def test_run_context_con_lineage_round_trip() -> None:
    """Un ``RunContext`` con ``lineage`` poblado anida y reconstruye el bundle."""
    ctx = RunContext(status="done", lineage=_bundle())
    recargado = RunContext.model_validate(ctx.model_dump(mode="json"))
    assert recargado == ctx
    assert recargado.lineage is not None
    assert recargado.lineage.config_hash == "02b667fc"


# --- LineageBundle ----------------------------------------------------------------------------


def test_lineage_bundle_round_trip() -> None:
    """Un ``LineageBundle`` completo recarga idéntico desde su volcado JSON."""
    bundle = _bundle()
    assert LineageBundle.model_validate(bundle.model_dump(mode="json")) == bundle


def test_lineage_bundle_campos_requeridos() -> None:
    """Omitir un campo requerido (``config_hash``) levanta ``ValidationError``."""
    with pytest.raises(ValidationError):
        LineageBundle(  # type: ignore[call-arg]
            git_sha=None,
            git_dirty=True,
            data_hash=None,
            root_seed=42,
            uv_lock_hash=None,
            library_versions={},
            determinism_caveats=[],
            created_at=_CREATED,
            schema_version="1.0.0",
        )


def test_lineage_bundle_none_justificado() -> None:
    """``git_sha``/``data_hash``/``uv_lock_hash`` admiten None (repo/datos/uv.lock ausentes)."""
    bundle = LineageBundle(
        git_sha=None,
        git_dirty=True,
        data_hash=None,
        config_hash="02b667fc",
        root_seed=0,
        uv_lock_hash=None,
        library_versions={},
        determinism_caveats=[],
        created_at=_CREATED,
        schema_version="1.0.0",
    )
    assert bundle.git_sha is None
    assert bundle.data_hash is None
    assert bundle.uv_lock_hash is None


def test_lineage_bundle_created_at_iso_8601() -> None:
    """``created_at`` serializa a ISO-8601 y reconstruye al mismo ``datetime`` (API de SDD-04)."""
    dump = _bundle().model_dump(mode="json")
    assert isinstance(dump["created_at"], str)
    assert dump["created_at"].startswith("2026-06-24T12:00:00")
    assert LineageBundle.model_validate(dump).created_at == _CREATED
