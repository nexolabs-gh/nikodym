"""API fina de orquestación de alto nivel (CT-4): ensamblado de corrida."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nikodym.audit import AuditConfig, JsonlAuditSink
from nikodym.core.audit import AuditSink, FanOutSink, NullAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.governance import GovernanceConfig, ModelInventory, NullInventory
from nikodym.tracking import MLflowInventory, TrackingConfig, TrackingRecorder, TrackingSink
from nikodym.utils.optional import require_extra

__all__ = ["assemble_run"]


def assemble_run(config: NikodymConfig) -> tuple[AuditSink, ModelInventory]:
    """Construye el ``AuditSink`` compuesto y el inventario real/no-op de una corrida.

    ``core`` recibe ambos objetos ya resueltos: no importa ``audit``, ``governance``, ``tracking``
    ni MLflow. Si ``governance.publish_to_inventory=True`` y falta el extra ``tracking``, esta capa
    falla ruidoso con ``MissingDependencyError`` porque la publicación fue una petición explícita.
    """
    audit_cfg = _audit_config(config.audit)
    governance_cfg = _governance_config(config.governance)
    tracking_cfg = _tracking_config(config.tracking)

    sinks: list[AuditSink] = []
    if audit_cfg is not None and audit_cfg.enabled:
        sinks.append(JsonlAuditSink(Path(audit_cfg.trail_filename), config=audit_cfg))
    if tracking_cfg is not None and tracking_cfg.enabled:
        sinks.append(TrackingSink(TrackingRecorder(tracking_cfg)))

    if governance_cfg is not None and governance_cfg.publish_to_inventory:
        require_extra("tracking", "mlflow")
        inventory: ModelInventory = MLflowInventory(tracking_cfg or TrackingConfig())
    else:
        inventory = NullInventory()

    if not sinks:
        return NullAuditSink(), inventory
    if len(sinks) == 1:
        return sinks[0], inventory
    return FanOutSink(sinks), inventory


def _audit_config(value: Any) -> AuditConfig | None:
    """Coacciona la sección audit si el config fue creado antes de importar ``nikodym.audit``."""
    if value is None:
        return None
    if isinstance(value, AuditConfig):
        return value
    return AuditConfig.model_validate(value)


def _governance_config(value: Any) -> GovernanceConfig | None:
    """Coacciona la sección governance si llegó como blob opaco."""
    if value is None:
        return None
    if isinstance(value, GovernanceConfig):
        return value
    return GovernanceConfig.model_validate(value)


def _tracking_config(value: Any) -> TrackingConfig | None:
    """Coacciona la sección tracking si llegó como blob opaco."""
    if value is None:
        return None
    if isinstance(value, TrackingConfig):
        return value
    return TrackingConfig.model_validate(value)
