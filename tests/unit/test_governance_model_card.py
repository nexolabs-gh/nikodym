"""Tests del model card de ``nikodym.governance``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from nikodym.audit import EnvironmentSnapshot, JsonlAuditSink
from nikodym.core.audit import AuditEvent
from nikodym.core.config import NikodymConfig
from nikodym.core.lineage import LineageBundle
from nikodym.core.study import Study
from nikodym.data.card import DataCardSection
from nikodym.governance import GovernanceConfig, GovernanceError, ModelCardBuilder

_CREATED_AT = datetime(2026, 6, 25, 8, 0, 0, tzinfo=UTC)
_EVENT_TS = datetime(2026, 6, 25, 9, 0, 0, tzinfo=UTC)
_REVIEW_NAIVE = datetime(2026, 1, 31, 10, 30, 0)
_ENV = EnvironmentSnapshot(
    python_version="3.12.9",
    platform="macOS-15-arm64",
    library_versions={"nikodym": "0.1.0", "pydantic": "2.13.0"},
    uv_lock_hash="uvhash",
    captured_at=datetime(2026, 6, 25, 7, 0, 0, tzinfo=UTC),
)
_GOLDEN_MODEL_CARD_JSON = (
    '{"assumptions":["muestra cerrada"],"config_hash":"cfg123","created_at":"2026-06-25T08:00:00Z",'
    '"data_description":{"bad_rate":0.2,"class_counts":{"bueno":8,"malo":2},"data_hash":"data123",'
    '"exclusions_by_reason":{},"n_features":5,"n_rows":10,"partition_bad_rates":{"dev":0.25},'
    '"partition_sizes":{"dev":8,"oot":2},"performance_window_months":12,"source":"clientes.parquet",'
    '"target_col":"target"},"data_hash":"data123","decisions":[{"accion":"descartar","regla":"iv_min",'
    '"step":"binning","ts":"2026-06-25T09:00:00Z","umbral":0.02,"valor":0.01}],'
    '"determinism_caveats":["GBDT multihilo"],"environment":{"captured_at":"2026-06-25T07:00:00Z",'
    '"library_versions":{"nikodym":"0.1.0","pydantic":"2.13.0"},"platform":"macOS-15-arm64",'
    '"python_version":"3.12.9","uv_lock_hash":"uvhash"},"git_dirty":false,"git_sha":"abc123",'
    '"limitations":["uso interno","GBDT multihilo"],"metric_sections":{'
    '"fecha":"2026-06-25T09:00:00Z",'
    '"term_structure":{"base":[0.1,0.2]}},"metrics":{"auc":0.81,"ks":0.42},'
    '"next_review_date":"2026-02-28T10:30:00Z","purpose":"Scorecard comportamiento consumo",'
    '"review_date":"2026-01-31T10:30:00Z","root_seed":1234,"run_id":"run-001",'
    '"schema_version":"1.0.0"}'
)
_GOLDEN_MARKDOWN = """# Model Card: run-001

## Identidad
- config_hash: `cfg123`
- data_hash: `data123`
- git_sha: `abc123`
- git_dirty: `False`
- root_seed: `1234`
- schema_version: `1.0.0`

## Propósito
Scorecard comportamiento consumo

## Métricas
- auc: `0.81`
- ks: `0.42`

## Secciones Métricas
- fecha: `"2026-06-25T09:00:00Z"`
- term_structure: `{"base":[0.1,0.2]}`

## Datos
- bad_rate: `0.2`
- class_counts: `{"bueno":8,"malo":2}`
- data_hash: `"data123"`
- exclusions_by_reason: `{}`
- n_features: `5`
- n_rows: `10`
- partition_bad_rates: `{"dev":0.25}`
- partition_sizes: `{"dev":8,"oot":2}`
- performance_window_months: `12`
- source: `"clientes.parquet"`
- target_col: `"target"`

## Supuestos
- muestra cerrada

## Limitaciones
- uso interno
- GBDT multihilo

## Decisiones
- 2026-06-25T09:00:00+00:00 · binning: iv_min → descartar

## Revisión
- review_date: `2026-01-31T10:30:00+00:00`
- next_review_date: `2026-02-28T10:30:00+00:00`
"""


def _lineage(
    *,
    git_sha: str | None = "abc123",
    data_hash: str | None = "data123",
    uv_lock_hash: str | None = "uvhash",
    caveats: list[str] | None = None,
) -> LineageBundle:
    """Lineage determinista para construir model cards sin depender de git real."""
    return LineageBundle(
        git_sha=git_sha,
        git_dirty=False,
        data_hash=data_hash,
        config_hash="cfg123",
        root_seed=1234,
        uv_lock_hash=uv_lock_hash,
        library_versions={"nikodym": "0.1.0"},
        determinism_caveats=caveats or ["GBDT multihilo"],
        created_at=_CREATED_AT,
        schema_version="1.0.0",
    )


def _data_card() -> DataCardSection:
    """Data card sintético usado como artefacto de entrada del model card."""
    return DataCardSection(
        source="clientes.parquet",
        n_rows=10,
        n_features=5,
        target_col="target",
        bad_rate=0.2,
        class_counts={"bueno": 8, "malo": 2},
        partition_sizes={"dev": 8, "oot": 2},
        partition_bad_rates={"dev": 0.25},
        performance_window_months=12,
        exclusions_by_reason={},
        data_hash="data123",
    )


def _study(status: str = "done") -> Study:
    """Study finalizado en memoria con resultados y artefactos deterministas."""
    study = Study(NikodymConfig())
    study.run_context.status = status  # type: ignore[assignment]
    study.run_context.run_id = "run-001"
    study.run_context.lineage = _lineage()
    study.results["metrics"] = {"auc": 0.81, "ks": 0.42}
    study.results["metric_sections"] = {
        "term_structure": {"base": [0.1, 0.2]},
        "fecha": _EVENT_TS,
    }
    study.artifacts.set("data", "data_card", _data_card())
    return study


def _trail(path: Path, *, payload: dict[str, object] | None = None) -> Path:
    """Escribe un trail mínimo con un evento decision."""
    event = AuditEvent(
        kind="decision",
        step="binning",
        payload=payload
        or {"regla": "iv_min", "umbral": 0.02, "valor": 0.01, "accion": "descartar"},
        ts=_EVENT_TS,
    )
    with JsonlAuditSink(path) as sink:
        sink.emit(event)
    return path


def _builder(
    config: GovernanceConfig | None = None,
    *,
    now: datetime = _REVIEW_NAIVE,
) -> ModelCardBuilder:
    """Builder con reloj y entorno inyectados."""
    return ModelCardBuilder(
        config
        or GovernanceConfig(
            purpose="Scorecard comportamiento consumo",
            assumptions=("muestra cerrada",),
            limitations=("uso interno", "GBDT multihilo"),
            review_period_months=1,
        ),
        now=lambda: now,
        environment_provider=lambda: _ENV,
    )


def test_model_card_builder_compone_card_golden(tmp_path: Path) -> None:
    """Builder lee lineage, metrics, data_card y trail; JSON/markdown son bit-idénticos."""
    card = _builder().build(_study(), trail_path=_trail(tmp_path / "audit.jsonl"))

    assert card.run_id == "run-001"
    assert card.config_hash == "cfg123"
    assert card.data_description == _data_card()
    assert card.metrics == {"auc": 0.81, "ks": 0.42}
    assert card.metric_sections == {
        "term_structure": {"base": [0.1, 0.2]},
        "fecha": _EVENT_TS,
    }
    assert card.decisions[0].accion == "descartar"
    assert card.review_date == datetime(2026, 1, 31, 10, 30, 0, tzinfo=UTC)
    assert card.next_review_date == datetime(2026, 2, 28, 10, 30, 0, tzinfo=UTC)
    assert card.to_json() == _GOLDEN_MODEL_CARD_JSON
    assert card.to_markdown() == _GOLDEN_MARKDOWN


def test_model_card_builder_run_fallido_sin_trail_ni_lineage_completo_advierte() -> None:
    """Un run fallido también produce card, marcando faltantes y sin decisiones."""
    study = Study(NikodymConfig())
    study.run_context.status = "failed"
    study.run_context.run_id = "run-failed"
    study.run_context.lineage = _lineage(
        git_sha=None,
        data_hash=None,
        uv_lock_hash=None,
        caveats=["caveat", "caveat"],
    )

    with pytest.warns(UserWarning, match="trail no disponible"):
        card = _builder(GovernanceConfig(purpose="Documentar fallo")).build(study)

    assert card.decisions == []
    assert card.metrics == {}
    assert card.metric_sections == {}
    assert card.data_description is None
    assert card.limitations == [
        "caveat",
        "lineage parcial: sin git SHA",
        "lineage parcial: sin hash de datos",
        "lineage parcial: sin hash de uv.lock",
        "run sin data_card: descripción de datos no disponible",
        "run fallido: revisar evento run_end del audit-trail",
        "audit-trail no disponible: decisiones no incluidas",
    ]
    assert "- Sin data_card." in card.to_markdown()
    assert "- Sin registros." in card.to_markdown()


def test_model_card_builder_trail_ausente_advierte(tmp_path: Path) -> None:
    """Un path inexistente no se adivina ni aborta: card parcial con warning."""
    with pytest.warns(UserWarning, match="trail no disponible"):
        card = _builder().build(_study(), trail_path=tmp_path / "ausente.jsonl")

    assert card.decisions == []
    assert "audit-trail no disponible" in card.limitations[-1]


@pytest.mark.parametrize("status", ["created", "running"])
def test_model_card_builder_rechaza_study_no_finalizado(status: str) -> None:
    """``created``/``running`` no tienen evidencia suficiente para model card."""
    study = Study(NikodymConfig())
    study.run_context.status = status  # type: ignore[assignment]
    with pytest.raises(GovernanceError, match="Study finalizado"):
        _builder().build(study)


def test_model_card_builder_rechaza_finalizado_sin_run_id() -> None:
    """Un status final sin ``run_id`` es inconsistente y falla ruidoso."""
    study = Study(NikodymConfig())
    study.run_context.status = "done"
    study.run_context.lineage = _lineage()
    with pytest.raises(GovernanceError, match="sin run_id"):
        _builder().build(study)


@pytest.mark.parametrize(
    ("results", "match"),
    [
        ({"metrics": []}, "metrics"),
        ({"metrics": {1: 0.1}}, "claves"),
        ({"metrics": {"flag": True}}, "numérica"),
        ({"metrics": {"auc": float("nan")}}, "finita"),
        ({"metric_sections": []}, "metric_sections"),
    ],
)
def test_model_card_builder_rechaza_results_mal_formados(
    tmp_path: Path,
    results: dict[str, object],
    match: str,
) -> None:
    """El builder no adivina métricas si el namespace no cumple contrato."""
    study = _study()
    study.results.clear()
    study.results.update(results)

    with pytest.raises(GovernanceError, match=match):
        _builder().build(study, trail_path=_trail(tmp_path / "audit.jsonl"))


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"accion": "x"}, "regla"),
        ({"regla": "x"}, "accion"),
        ({"regla": "x", "acción": "mantener"}, "mantener"),
    ],
)
def test_model_card_builder_valida_payload_decision(
    tmp_path: Path,
    payload: dict[str, object],
    match: str,
) -> None:
    """DecisionRecord conserva trazabilidad 1:1 y acepta el alias histórico con tilde."""
    if match == "mantener":
        card = _builder().build(
            _study(), trail_path=_trail(tmp_path / "audit.jsonl", payload=payload)
        )
        assert card.decisions[0].accion == "mantener"
        return
    with pytest.raises(GovernanceError, match=match):
        _builder().build(
            _study(),
            trail_path=_trail(tmp_path / "audit.jsonl", payload=payload),
        )


def test_model_card_builder_normaliza_timestamps_aware_no_utc(tmp_path: Path) -> None:
    """Un reloj aware no-UTC se normaliza a UTC antes de serializar."""
    tz = timezone(timedelta(hours=-4))
    card = _builder(now=datetime(2026, 6, 25, 8, 0, 0, tzinfo=tz)).build(
        _study(),
        trail_path=_trail(tmp_path / "audit.jsonl"),
    )
    assert card.review_date == datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC)
