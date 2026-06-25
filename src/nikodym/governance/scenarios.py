"""Registro auditable JSONL de escenarios y overlays (SDD-03 §4.2)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nikodym.governance.exceptions import GovernanceError

__all__ = ["OverlayRecord", "ScenarioLog", "ScenarioRecord"]


class OverlayRecord(BaseModel):
    """Ajuste discrecional auditable con justificación obligatoria."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    overlay_id: str
    scope: str
    justification: str = Field(..., min_length=1)
    author: str
    value_before: float
    value_after: float
    payload: dict[str, Any] | None = None
    approved_by: str | None = None
    ts: datetime

    @field_validator("justification")
    @classmethod
    def _justification_no_vacia(cls, value: str) -> str:
        """Rechaza justificaciones vacías o solo whitespace."""
        clean = value.strip()
        if not clean:
            raise ValueError("justification es obligatoria para un overlay.")
        return clean


class ScenarioRecord(BaseModel):
    """Escenario macro/económico registrado con parámetros trazables."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    kind: Literal["base", "adverso", "severo"] | str
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    params: dict[str, Any] = Field(default_factory=dict)
    ts: datetime


class ScenarioLog:
    """Diario append-only de escenarios y overlays en JSONL canónico."""

    def __init__(self, path: str | Path) -> None:
        """Crea el logger y asegura el directorio padre."""
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GovernanceError(f"No se pudo crear el directorio de scenario_log: {exc}") from exc

    def log_scenario(self, rec: ScenarioRecord) -> None:
        """Añade un escenario al JSONL append-only."""
        self._append("scenario", rec)

    def log_overlay(self, rec: OverlayRecord) -> None:
        """Añade un overlay al JSONL, rechazando justificación vacía si fue manipulada."""
        if not rec.justification.strip():
            raise GovernanceError(
                f"overlay '{rec.overlay_id}' sin justificación: requerido por política "
                "anti earnings-management."
            )
        self._append("overlay", rec)

    def read(self) -> list[ScenarioRecord | OverlayRecord]:
        """Lee y revalida todo el scenario_log en orden de escritura."""
        if not self.path.exists():
            return []
        records: list[ScenarioRecord | OverlayRecord] = []
        try:
            with self.path.open(encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, start=1):
                    records.append(_parse_line(line, lineno=lineno, path=self.path))
        except OSError as exc:
            raise GovernanceError(f"No se pudo leer scenario_log '{self.path}': {exc}") from exc
        return records

    def _append(self, record_type: Literal["scenario", "overlay"], rec: BaseModel) -> None:
        """Serializa un record como línea JSON canónica y la añade al archivo."""
        payload = {"record_type": record_type, **rec.model_dump(mode="json")}
        line = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
        except OSError as exc:
            raise GovernanceError(f"No se pudo escribir scenario_log '{self.path}': {exc}") from exc


def _parse_line(line: str, *, lineno: int, path: Path) -> ScenarioRecord | OverlayRecord:
    """Rehidrata una línea JSONL de escenario u overlay."""
    try:
        payload = json.loads(line)
        record_type = payload.pop("record_type")
        if record_type == "scenario":
            return ScenarioRecord.model_validate(payload)
        if record_type == "overlay":
            return OverlayRecord.model_validate(payload)
    except (KeyError, json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise GovernanceError(
            f"scenario_log '{path}' corrupto en línea {lineno}: no cumple el contrato JSONL."
        ) from exc
    raise GovernanceError(
        f"scenario_log '{path}' corrupto en línea {lineno}: record_type desconocido "
        f"'{record_type}'."
    )
