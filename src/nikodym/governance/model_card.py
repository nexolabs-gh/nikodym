"""Model card reproducible para gobernanza SR 11-7 (SDD-03 §4.2)."""

from __future__ import annotations

import json
import math
import warnings
from calendar import monthrange
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nikodym.audit import EnvironmentSnapshot, capture_environment, read_trail
from nikodym.core.audit import AuditEvent
from nikodym.governance.config import GovernanceConfig
from nikodym.governance.exceptions import GovernanceError

if TYPE_CHECKING:
    from nikodym.core.study import Study
    from nikodym.data.card import DataCardSection as DataCardSectionLike
else:
    DataCardSectionLike = Any

__all__ = ["DecisionRecord", "ModelCard", "ModelCardBuilder"]


class DecisionRecord(BaseModel):
    """Decisión materializada desde un ``AuditEvent(kind='decision')``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str | None
    regla: str
    umbral: Any
    valor: Any
    accion: str
    ts: datetime


class ModelCard(BaseModel):
    """Ficha auditable del modelo, serializable a JSON canónico y markdown."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    config_hash: str
    data_hash: str | None
    git_sha: str | None
    git_dirty: bool
    root_seed: int
    schema_version: str
    created_at: datetime
    purpose: str
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_description: DataCardSectionLike | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    metric_sections: dict[str, Any] = Field(default_factory=dict)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    determinism_caveats: list[str] = Field(default_factory=list)
    review_date: datetime
    next_review_date: datetime
    environment: EnvironmentSnapshot

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _metric_sections_snapshot(cls, value: Any) -> Any:
        """Toma snapshot profundo de payloads estructurados CT-2 al construir el card."""
        return deepcopy(value)

    def to_json(self) -> str:
        """Serializa el model card a JSON canónico para diff/auditoría."""
        return json.dumps(
            _to_jsonable(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_markdown(self) -> str:
        """Renderiza una versión markdown estable del model card."""
        lines = [
            f"# Model Card: {self.run_id}",
            "",
            "## Identidad",
            f"- config_hash: `{self.config_hash}`",
            f"- data_hash: `{self.data_hash}`",
            f"- git_sha: `{self.git_sha}`",
            f"- git_dirty: `{self.git_dirty}`",
            f"- root_seed: `{self.root_seed}`",
            f"- schema_version: `{self.schema_version}`",
            "",
            "## Propósito",
            self.purpose,
            "",
            "## Métricas",
        ]
        lines.extend(_markdown_mapping(self.metrics))
        if self.metric_sections:
            lines.extend(["", "## Secciones Métricas"])
            lines.extend(_markdown_mapping(self.metric_sections))
        lines.extend(["", "## Datos"])
        if self.data_description is None:
            lines.append("- Sin data_card.")
        else:
            lines.extend(_markdown_mapping(_to_jsonable(self.data_description)))
        lines.extend(["", "## Supuestos"])
        lines.extend(_markdown_list(self.assumptions))
        lines.extend(["", "## Limitaciones"])
        lines.extend(_markdown_list(self.limitations))
        lines.extend(["", "## Decisiones"])
        if self.decisions:
            for decision in self.decisions:
                lines.append(
                    "- "
                    f"{decision.ts.isoformat()} · {decision.step}: {decision.regla} "
                    f"→ {decision.accion}"
                )
        else:
            lines.append("- Sin decisiones registradas.")
        lines.extend(
            [
                "",
                "## Revisión",
                f"- review_date: `{self.review_date.isoformat()}`",
                f"- next_review_date: `{self.next_review_date.isoformat()}`",
            ]
        )
        return "\n".join(lines) + "\n"


class ModelCardBuilder:
    """Ensambla un :class:`ModelCard` desde un ``Study`` finalizado y su trail."""

    def __init__(
        self,
        config: GovernanceConfig,
        *,
        now: Callable[[], datetime] | None = None,
        environment_provider: Callable[[], EnvironmentSnapshot] | None = None,
    ) -> None:
        """Construye el builder con proveedores inyectables para golden values."""
        self.config = config
        self._now = now or (lambda: datetime.now(UTC))
        self._environment_provider = environment_provider or capture_environment

    def build(self, study: Study, *, trail_path: str | Path | None = None) -> ModelCard:
        """Construye el model card desde lineage, resultados, artefactos y audit-trail."""
        status = study.run_context.status
        if status not in {"done", "failed"}:
            raise GovernanceError(
                f"ModelCardBuilder requiere un Study finalizado; status actual='{status}'."
            )
        if study.run_context.run_id is None:
            raise GovernanceError("Study finalizado sin run_id; no se puede construir model card.")

        bundle = study.lineage_bundle()
        review_date = _as_utc(self._now())
        decisions, trail_missing = _read_decisions(trail_path)
        data_description = _data_description(study)
        limitations = _limitations(
            configured=self.config.limitations,
            determinism_caveats=bundle.determinism_caveats,
            git_sha=bundle.git_sha,
            data_hash=bundle.data_hash,
            uv_lock_hash=bundle.uv_lock_hash,
            data_missing=data_description is None,
            failed=status == "failed",
            trail_missing=trail_missing,
        )

        return ModelCard(
            run_id=study.run_context.run_id,
            config_hash=bundle.config_hash,
            data_hash=bundle.data_hash,
            git_sha=bundle.git_sha,
            git_dirty=bundle.git_dirty,
            root_seed=bundle.root_seed,
            schema_version=bundle.schema_version,
            created_at=_as_utc(bundle.created_at),
            purpose=self.config.purpose,
            assumptions=list(self.config.assumptions),
            limitations=limitations,
            data_description=data_description,
            metrics=_metrics(study.results),
            metric_sections=_metric_sections(study.results),
            decisions=decisions,
            determinism_caveats=list(bundle.determinism_caveats),
            review_date=review_date,
            next_review_date=_add_months(review_date, self.config.review_period_months),
            environment=self._environment_provider(),
        )


def _read_decisions(trail_path: str | Path | None) -> tuple[list[DecisionRecord], bool]:
    """Lee decisiones desde el trail persistido; ausencia -> warning y lista vacía."""
    if trail_path is None:
        _warn_trail_missing("trail no disponible: model card parcial.")
        return [], True
    path = Path(trail_path)
    if not path.exists():
        _warn_trail_missing(f"trail no disponible en '{path}': model card parcial.")
        return [], True
    return [
        _decision_from_event(event) for event in read_trail(path) if event.kind == "decision"
    ], False


def _warn_trail_missing(message: str) -> None:
    """Emita warning explícito cuando el model card queda sin decisiones."""
    warnings.warn(message, stacklevel=3)


def _decision_from_event(event: AuditEvent) -> DecisionRecord:
    """Convierte un evento ``decision`` del core al record estable del model card."""
    payload = event.payload
    try:
        regla = payload["regla"]
    except KeyError as exc:
        raise GovernanceError("Evento decision sin campo obligatorio 'regla'.") from exc
    accion = payload.get("accion", payload.get("acción"))
    if accion is None:
        raise GovernanceError("Evento decision sin campo obligatorio 'accion'.")
    return DecisionRecord(
        step=event.step,
        regla=regla,
        umbral=payload.get("umbral"),
        valor=payload.get("valor"),
        accion=accion,
        ts=_as_utc(event.ts),
    )


def _metrics(results: dict[str, Any]) -> dict[str, float]:
    """Extrae ``results['metrics']`` y exige escalares numéricos finitos."""
    raw = results.get("metrics", {})
    if not isinstance(raw, dict):
        raise GovernanceError("study.results['metrics'] debe ser dict[str, float].")
    metrics: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise GovernanceError("Las claves de metrics deben ser str.")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise GovernanceError(f"La métrica '{key}' debe ser numérica finita.")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise GovernanceError(f"La métrica '{key}' debe ser finita.")
        metrics[key] = numeric
    return metrics


def _metric_sections(results: dict[str, Any]) -> dict[str, Any]:
    """Extrae secciones métricas estructuradas (CT-2), si existen."""
    raw = results.get("metric_sections", {})
    if not isinstance(raw, dict):
        raise GovernanceError("study.results['metric_sections'] debe ser un dict.")
    return cast("dict[str, Any]", deepcopy(raw))


def _data_description(study: Study) -> DataCardSectionLike | None:
    """Lee el artefacto ``('data', 'data_card')`` sin importar ``nikodym.data``."""
    if study.artifacts.has("data", "data_card"):
        return cast("DataCardSectionLike", study.artifacts.get("data", "data_card"))
    return None


def _limitations(
    *,
    configured: tuple[str, ...],
    determinism_caveats: list[str],
    git_sha: str | None,
    data_hash: str | None,
    uv_lock_hash: str | None,
    data_missing: bool,
    failed: bool,
    trail_missing: bool,
) -> list[str]:
    """Compone limitaciones declaradas y faltantes explícitos de lineage/trail."""
    values = list(configured)
    values.extend(determinism_caveats)
    if git_sha is None:
        values.append("lineage parcial: sin git SHA")
    if data_hash is None:
        values.append("lineage parcial: sin hash de datos")
    if uv_lock_hash is None:
        values.append("lineage parcial: sin hash de uv.lock")
    if data_missing:
        values.append("run sin data_card: descripción de datos no disponible")
    if failed:
        values.append("run fallido: revisar evento run_end del audit-trail")
    if trail_missing:
        values.append("audit-trail no disponible: decisiones no incluidas")
    return _dedupe(values)


def _dedupe(values: list[str]) -> list[str]:
    """Elimina duplicados preservando el primer orden de aparición."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _add_months(value: datetime, months: int) -> datetime:
    """Suma meses calendario sin dependencia adicional y conserva zona horaria."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _as_utc(value: datetime) -> datetime:
    """Normaliza timestamps naive/aware a UTC para serialización estable."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_jsonable(value: Any) -> Any:
    """Convierte Pydantic/datetime/tuplas a estructuras JSON estándar."""
    if isinstance(value, BaseModel):
        return _to_jsonable(value.model_dump(mode="json"))
    if isinstance(value, datetime):
        return _as_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_to_jsonable(item) for item in value]
    return value


def _markdown_mapping(mapping: dict[str, Any]) -> list[str]:
    """Renderiza un mapping como bullets ordenados por clave."""
    if not mapping:
        return ["- Sin registros."]
    return [f"- {key}: `{_compact_json(value)}`" for key, value in sorted(mapping.items())]


def _markdown_list(values: list[str]) -> list[str]:
    """Renderiza una lista como bullets con fallback estable."""
    if not values:
        return ["- Sin registros."]
    return [f"- {value}" for value in values]


def _compact_json(value: Any) -> str:
    """Serializa valores de bullets en JSON compacto y determinista."""
    return json.dumps(
        _to_jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
