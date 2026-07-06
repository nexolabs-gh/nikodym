"""API fina de orquestación de alto nivel (CT-4): ensamblado de corrida."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nikodym.audit import AuditConfig, JsonlAuditSink
from nikodym.core.audit import AuditSink, FanOutSink, NullAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import NikodymError
from nikodym.core.study import Study
from nikodym.governance import (
    GovernanceConfig,
    InventoryEntry,
    ModelCardBuilder,
    ModelInventory,
    NullInventory,
)
from nikodym.tracking import MLflowInventory, TrackingConfig, TrackingRecorder, TrackingSink
from nikodym.utils.optional import require_extra

__all__ = ["assemble_run", "run"]


def run(config: NikodymConfig) -> Study:
    """Ejecuta una corrida completa de extremo a extremo y devuelve el ``Study``.

    Superficie pública única de ejecución (CT-4): ensambla el ``AuditSink`` y el
    ``ModelInventory`` (``assemble_run``), corre el ``Study``, y —solo en éxito y solo si
    ``governance.publish_to_inventory``— publica la ``ModelCard`` en el inventario.

    **Semántica de fallo (D-UI-2, decidida).** ``Study.run()`` es el primitivo *fail-loud*:
    ante un fallo marca ``status="failed"``, conserva el lineage y re-levanta. Esta función es
    el envoltorio de producto: **captura el** ``NikodymError`` y devuelve el ``Study`` parcial
    en vez de propagarlo. El fallo no se silencia (vive en ``study.run_context.status``, en el
    audit-trail y en el lineage) pero tampoco explota. Por eso, el consumidor por código **debe
    chequear** ``study.run_context.status`` (``"done"`` vs ``"failed"``) antes de usar
    ``study.results``.
    """
    sink, inventory = assemble_run(config)
    governance_cfg = _governance_config(config.governance)

    study = Study(config)
    study.set_audit_sink(sink)
    try:
        study.run()
    except NikodymError:
        # Fallo esperado de dominio: el Study queda con status="failed" + lineage conservado
        # (SDD-01 §7.3). No se propaga: se devuelve para inspección (D-UI-2).
        _close_audit_sink(sink)
        return study

    # Cierra el sink (flush + close del trail) ANTES de leer el trail para la ModelCard: evita
    # fuga de descriptor y lecturas del JSONL mientras sigue abierto en modo append (Windows).
    _close_audit_sink(sink)
    if governance_cfg is not None and governance_cfg.publish_to_inventory:
        entry = _build_inventory_entry(study, governance_cfg, config)
        inventory.register(entry)
    return study


def _close_audit_sink(sink: AuditSink) -> None:
    """Cierra el ``AuditSink`` que ``run`` posee (y los hijos de un ``FanOutSink``).

    El Protocol ``AuditSink`` solo declara ``emit``; ``close`` es opcional (lo tiene
    ``JsonlAuditSink``, no ``NullAuditSink``/``FanOutSink``). Se cierra de forma tolerante:
    invoca ``close`` si existe y recorre ``sinks`` para cerrar los sumideros compuestos.
    """
    close = getattr(sink, "close", None)
    if callable(close):
        close()
    for child in getattr(sink, "sinks", ()):
        _close_audit_sink(child)


def _build_inventory_entry(
    study: Study, governance_cfg: GovernanceConfig, config: NikodymConfig
) -> InventoryEntry:
    """Deriva la ``InventoryEntry`` desde la ``ModelCard`` de un ``Study`` en éxito.

    La ancla de idempotencia ``(model_name, config_hash)`` la aplica la implementación de
    ``ModelInventory`` (SDD-04); aquí solo se compone la entrada completa que registrar.
    """
    audit_cfg = _audit_config(config.audit)
    trail_path = audit_cfg.trail_filename if audit_cfg is not None and audit_cfg.enabled else None
    card = ModelCardBuilder(governance_cfg).build(study, trail_path=trail_path)
    return InventoryEntry(
        model_name=governance_cfg.model_name,
        config_hash=card.config_hash,
        data_hash=card.data_hash,
        git_sha=card.git_sha,
        run_id=card.run_id,
        metrics=card.metrics,
        model_card=card,
        next_review_date=card.next_review_date,
        tags=_inventory_tags(governance_cfg),
    )


def _inventory_tags(governance_cfg: GovernanceConfig) -> dict[str, str]:
    """Compone los tags ``nikodym.*`` documentados en ``GovernanceConfig`` (cartera/motor/…)."""
    candidatos: dict[str, str | None] = {
        "nikodym.estado_validacion": governance_cfg.estado_validacion,
        "nikodym.cartera": governance_cfg.cartera,
        "nikodym.motor": governance_cfg.motor,
        "nikodym.fase": governance_cfg.fase,
        "nikodym.autor": governance_cfg.author,
    }
    return {key: value for key, value in candidatos.items() if value is not None}


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
