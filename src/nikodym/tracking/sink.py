"""Sink de auditoría que refleja eventos de ``core`` en un run MLflow (SDD-04 §4)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nikodym.core.audit import AuditEvent
from nikodym.tracking.recorder import TrackingRecorder

if TYPE_CHECKING:
    from nikodym.core.study import Study

__all__ = ["TrackingSink"]


class TrackingSink:
    """Implementa ``AuditSink`` enrutando eventos del ``Study`` hacia ``TrackingRecorder``."""

    def __init__(self, recorder: TrackingRecorder, *, study: Study | None = None) -> None:
        """Envuelve un recorder; ``study`` es opcional para logging post-run completo."""
        self.recorder = recorder
        self.study = study
        self._decisions: list[dict[str, Any]] = []

    def emit(self, event: AuditEvent) -> None:
        """Procesa un evento de auditoría sin levantar hacia ``core`` por defecto."""
        if event.kind == "run_start":
            run_name = event.payload.get("name")
            self.recorder.ensure_run(run_name=str(run_name) if run_name is not None else None)
            self.recorder.log_metrics({"nikodym.run_started": 1.0})
            return
        if event.kind == "decision":
            self._decisions.append(event.model_dump(mode="json"))
            self.recorder.log_metrics({"nikodym.n_decisions": float(len(self._decisions))})
            return
        if event.kind == "artifact":
            path = event.payload.get("path")
            if isinstance(path, str | Path):
                self.recorder.log_artifact_file(path, artifact_path="artifacts")
            return
        if event.kind == "run_end":
            self._flush_decisions()
            if self.study is not None:
                self.recorder.log_metrics(self.study.results)
                if self.study.run_context.lineage is not None:
                    self.recorder.log_lineage(self.study.run_context.lineage)
                self.recorder.snapshot_study(self.study)
            status = "FAILED" if event.payload.get("status") == "failed" else "FINISHED"
            self.recorder.end_run(status=status)

    def _flush_decisions(self) -> None:
        """Adjunta ``decisions.jsonl`` como artefacto si hubo decisiones."""
        if not self._decisions:
            return
        with tempfile.TemporaryDirectory(prefix="nikodym-decisions-") as tmp:
            path = Path(tmp) / "decisions.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    for item in self._decisions
                )
                + "\n",
                encoding="utf-8",
            )
            self.recorder.log_artifact_file(path, artifact_path="audit")
