"""Interfaces de auditoría que ``core`` emite y que SDD-03 implementa/consume (SDD-01 §4).

``core`` solo conoce el :class:`AuditEvent` (el evento atómico del *audit-trail*) y el
Protocol :class:`AuditSink` (el sumidero al que se emiten). Las implementaciones concretas que
persisten o resumen el trail —``JsonlAuditSink`` (gobernanza, SDD-03), el *sink* de tracking
(SDD-04)— viven **fuera** de ``core`` y se inyectan en el :class:`~nikodym.core.study.Study` vía
``Study.set_audit_sink(...)``. Esta inversión de dependencias mantiene el núcleo liviano
(D-CORE-1): ``core.audit`` solo importa *stdlib* y Pydantic, nunca numpy/mlflow/governance.

``core`` provee además tres *sinks* fundacionales: :class:`NullAuditSink` (no-op, el *default*
que hace ``log_decision``/``emit`` siempre seguros sin necesidad de ``None``),
:class:`InMemoryAuditSink` (acumulador en memoria, oráculo de tests y *replay* liviano) y
:class:`FanOutSink` (compositor que reparte cada evento a N *sinks*; CT-4). El ensamblado de la
corrida (``assemble_run``) que compone los *sinks* reales vive en la capa fina de api/runner, no
aquí.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

__all__ = [
    "AuditEvent",
    "AuditKind",
    "AuditSink",
    "FanOutSink",
    "InMemoryAuditSink",
    "NullAuditSink",
]

# Los 4 tipos de evento que ``core`` emite; alias compartido por AuditEvent.kind y los emisores.
AuditKind = Literal["run_start", "decision", "artifact", "run_end"]


class AuditEvent(BaseModel):
    """Evento atómico del *audit-trail* que ``core`` emite hacia un :class:`AuditSink`.

    ``core`` (``Study.run``, ``ArtifactStore.set``, ``AuditableMixin.log_decision``) construye
    estos eventos y los emite; SDD-03 los persiste (JSONL) y los resume en el *model card*.
    ``payload`` lleva el detalle estructurado: para un ``"decision"`` incluye la regla, el umbral
    gatillante y el valor observado (auditabilidad por construcción, ESPEC §4 principio 2); para
    un ``"artifact"`` la clave ``(domain, key)`` afectada; para ``"run_start"``/``"run_end"`` el
    lineage/estado de la corrida.

    ``frozen``/``extra="forbid"`` blindan el evento: sus **campos** no se reasignan ni admiten
    claves intrusas al revalidarlo desde disco. La inmutabilidad es a nivel de campos: el contenido
    profundo de ``payload`` (un ``dict``) sigue siendo mutable en memoria; la garantía de un trail
    *append-only* la da el *sink* persistente (``JsonlAuditSink``, SDD-03), no este modelo.

    Round-trip garantizado: ``AuditEvent.model_validate(json.loads(json.dumps(
    ev.model_dump(mode="json"), ensure_ascii=False)))`` reconstruye el evento sin pérdida
    (``datetime`` ↔ ISO-8601; tildes/ñ preservadas con ``ensure_ascii=False``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: AuditKind
    step: str | None
    payload: dict[str, Any]
    ts: datetime


class AuditSink(Protocol):
    """Contrato de un sumidero de eventos de auditoría (inversión de dependencias).

    ``core`` solo conoce este Protocol; las implementaciones concretas (``JsonlAuditSink`` de
    SDD-03, el *sink* de tracking de SDD-04) viven fuera de ``core`` y se inyectan en el
    :class:`~nikodym.core.study.Study` vía ``Study.set_audit_sink(...)``. Un *sink* recibe cada
    :class:`AuditEvent` por :meth:`emit`. No lleva ``@runtime_checkable``: se inyecta, no se valida
    con ``isinstance`` en el motor (SDD-01 §4); ``mypy --strict`` valida la conformidad en estático.
    """

    def emit(self, event: AuditEvent) -> None:
        """Recibe un evento de auditoría y lo procesa (persistir, acumular, reenviar…)."""
        ...


class NullAuditSink:
    """*Sink* no-operativo: descarta todo evento. Es el *sink* por defecto de ``core``.

    Garantiza que ``log_decision``/``emit`` sean **siempre** seguros aunque no se haya inyectado un
    *sink* real (nunca es ``None``): ``AuditableMixin._audit = NullAuditSink()`` de clase y
    ``ArtifactStore(audit=NullAuditSink())``. Sin estado, idempotente, no levanta.
    """

    def emit(self, event: AuditEvent) -> None:
        """Descarta el evento (no-op deliberado)."""
        return None


class InMemoryAuditSink:
    """*Sink* que acumula los eventos en una lista en memoria (sin dependencias de test).

    Vive en ``core.audit`` (no en el paquete de tests) para que cualquier capa pueda inspeccionar
    la secuencia emitida (verificar ``run_start → decision → artifact → run_end``, SDD-01 §11) y
    para servir de oráculo contra ``JsonlAuditSink`` (round-trip, SDD-03 §11). Preserva el orden de
    emisión por *append*.
    """

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        """Acumula el evento al final de :attr:`events`, preservando el orden de emisión."""
        self.events.append(event)


class FanOutSink:
    """*Sink* compositor: reenvía cada evento a N *sinks* subordinados (patrón *fan-out*; CT-4).

    Combina varios *sinks* en uno solo (p. ej. el ``JsonlAuditSink`` de gobernanza y el *sink* de
    tracking) y lo entrega como **un** :class:`AuditSink` a ``Study.set_audit_sink(...)``. ``core``
    recibe el *sink* ya compuesto: la composición la hace la capa fina de api/runner
    (``assemble_run``), fuera de ``core`` (CT-4, Hito 0). ``core`` solo provee el compositor.
    """

    def __init__(self, sinks: list[AuditSink]) -> None:
        self.sinks = sinks

    def emit(self, event: AuditEvent) -> None:
        """Reparte el evento a todos los *sinks* subordinados, en orden de la lista."""
        for sink in self.sinks:
            sink.emit(event)
