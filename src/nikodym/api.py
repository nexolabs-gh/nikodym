"""API fina de orquestación de alto nivel (CT-4): ensamblado de corrida."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nikodym.audit import AuditConfig, JsonlAuditSink
from nikodym.core.audit import AuditSink, FanOutSink, NullAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.dataset_check import DatasetCheck, check_dataset
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

__all__ = [
    "DatasetCheck",
    "PipelineCheck",
    "assemble_run",
    "check_dataset",
    "check_pipeline",
    "run",
]


@dataclass(frozen=True, slots=True)
class PipelineCheck:
    """Veredicto de ejecutabilidad de un config, sin correr nada (D-PIPE-2/D-PIPE-3).

    ``steps`` trae los pasos en el orden en que correrían —útil por sí solo: es lo que el usuario
    va a ejecutar—, y queda **vacío** si el config no es ejecutable, porque en ese caso no hay
    pipeline que anunciar.

    ``message`` guarda ``str(exc)`` **íntegro**, con el código de marca si el motor lo trae al
    frente: esta es superficie de código, donde el código es el dato, igual que en
    :class:`~nikodym.core.lineage.RunError`. El copy público lo sanea al publicarlo
    (:func:`~nikodym.core.markers.strip_declared_codes`, D-ERR-4).

    ``is_domain_error`` distingue el diagnóstico **accionable por quien configura** de una
    excepción inesperada, cuyo texto puede ser detalle interno sin valor para quien usa el
    formulario (mismo criterio que D-ERR-5).

    Cubre dos familias, y el ``ValidationError`` no es un añadido cosmético: las secciones de
    dominio son ``Any`` en el schema raíz, así que un valor fuera de rango dentro de ellas **no lo
    caza** ``NikodymConfig.model_validate`` — lo caza la coacción que hace la resolución, y llega
    aquí como ``ValidationError`` de Pydantic. Es el diagnóstico más accionable que produce esta
    función (nombra el campo y la restricción); clasificarlo como «inesperado» lo habría ocultado
    justo en el caso más común.
    """

    executable: bool
    steps: tuple[str, ...] = ()
    error_type: str | None = None
    message: str | None = None
    is_domain_error: bool = False


def check_pipeline(config: NikodymConfig) -> PipelineCheck:
    """Responde si ``config`` es ejecutable, **sin ejecutarlo**, y con qué pasos.

    Envoltorio de producto de :meth:`~nikodym.core.study.Study.check_pipeline`: donde el primitivo
    del núcleo re-levanta, esta función **captura y devuelve el veredicto**, igual que :func:`run`
    frente a ``Study.run`` (D-UI-2). Sirve para avisar mientras se edita —el usuario sabe que le
    falta encender una sección antes de apretar Ejecutar— y es la misma respuesta por código y por
    interfaz (D-PIPE-3).

    No ejecuta pasos, no lee el dataset, no monta sinks ni inventario y no deja rastro de corrida:
    comprobar no es correr.

    **Captura ``Exception``, no sólo ``NikodymError``.** Es deliberado y más amplio que :func:`run`:
    una comprobación existe para informar, así que tumbar a quien la llama —el formulario la invoca
    en cada tecleo— sería peor que cualquier fallo que quiera reportar. Un ``from_config`` de
    dominio puede levantar algo que no es de la familia del motor; ``is_domain_error`` lo declara
    en vez de disfrazarlo (D-PIPE-6).

    Parameters
    ----------
    config : NikodymConfig
        Config ya reconstruido. Que reconstruya es precondición, no resultado: la validez del
        modelo Pydantic y la ejecutabilidad del pipeline son dos preguntas distintas (D-PIPE-1).

    Returns
    -------
    PipelineCheck
        ``executable=True`` + ``steps`` en orden, o ``executable=False`` + el diagnóstico del motor.
    """
    try:
        # `apply_global_seed=False`: comprobar no puede sembrar los RNG del proceso. El formulario
        # llama aquí en cada tecleo, y sembrar dejaba el hint `PYTHONHASHSEED` —que se fija una sola
        # vez por proceso— anclado a la semilla del config que se editaba, no a la de la corrida.
        pasos = Study(config, apply_global_seed=False).check_pipeline()
    except ValidationError as exc:
        return PipelineCheck(
            executable=False,
            error_type=type(exc).__name__,
            message=_mensaje_de_validacion(exc),
            is_domain_error=True,
        )
    # Captura amplia a propósito (ver docstring): informar nunca debe tumbar al llamante.
    except Exception as exc:
        return PipelineCheck(
            executable=False,
            error_type=type(exc).__name__,
            message=str(exc),
            is_domain_error=isinstance(exc, NikodymError),
        )
    return PipelineCheck(executable=True, steps=tuple(pasos))


# Tope de errores citados en el mensaje: un config recién editado puede violar decenas de
# restricciones a la vez, y volcarlas todas convierte el aviso en un muro. El mensaje DICE cuántas
# omitió (nunca trunca en silencio) y el detalle íntegro sigue estando en el ValidationError.
_MAX_ERRORES_CITADOS = 5


def _mensaje_de_validacion(exc: ValidationError) -> str:
    """Compacta un ``ValidationError`` de coacción a ``campo: restricción``, una por línea.

    ``str(exc)`` es multilínea y arrastra ``[type=…, input_value=…]`` más una URL a la
    documentación de Pydantic: legible para quien programa, ruido para quien edita un formulario.
    Aquí se cita lo accionable —la ruta del campo y la restricción violada—; el objeto íntegro
    sigue disponible para quien llame a la API por código.
    """
    errores = exc.errors()
    lineas = [
        f"{'.'.join(str(parte) for parte in error['loc'])}: {error['msg']}"
        for error in errores[:_MAX_ERRORES_CITADOS]
    ]
    if len(errores) > _MAX_ERRORES_CITADOS:
        lineas.append(f"(y {len(errores) - _MAX_ERRORES_CITADOS} problema(s) más)")
    return " · ".join(lineas)


def run(config: NikodymConfig) -> Study:
    """Ejecuta una corrida completa de extremo a extremo y devuelve el ``Study``.

    Superficie pública única de ejecución (CT-4): ensambla el ``AuditSink`` y el
    ``ModelInventory`` (``assemble_run``), corre el ``Study``, y —solo en éxito y solo si
    ``governance.publish_to_inventory``— publica la ``ModelCard`` en el inventario.

    **Semántica de fallo (D-UI-2, decidida).** ``Study.run()`` es el primitivo *fail-loud*:
    ante un fallo marca ``status="failed"``, conserva el lineage y re-levanta. Esta función es
    el envoltorio de producto: **captura el** ``NikodymError`` y devuelve el ``Study`` parcial
    en vez de propagarlo. El fallo no se silencia pero tampoco explota. Por eso, el consumidor por
    código **debe chequear** ``study.run_context.status`` (``"done"`` vs ``"failed"``) antes de leer
    los resultados.

    **Dónde quedan los resultados: en** ``study.artifacts``, indexado por ``(dominio, clave)``::

        study = nikodym.run(config)
        assert study.run_context.status == "done"
        study.artifacts.get("performance", "result")     # métricas de discriminación
        study.artifacts.get("model", "coefficients")     # los betas del modelo
        study.artifacts.keys()                           # todo lo que dejó la corrida

    ⚠️ **No en** ``study.results``, que este docstring mandaba usar y **siempre está vacío**: es un
    canal de publicación que ningún paso llena hoy (ver :class:`~nikodym.core.study.Study`).

    **Dónde queda el diagnóstico.** En ``study.run_context.error``
    (:class:`~nikodym.core.lineage.RunError`): tipo de la excepción, mensaje del motor y paso que
    falló, sin que haya que configurar nada. El audit-trail lo repite en el evento ``run_end``, pero
    **sólo si el config declara un sink** — el preset F1 trae ``audit: null``, así que no dependa de
    él; y el lineage no guarda el error nunca (enmienda RUN-ERROR).
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
