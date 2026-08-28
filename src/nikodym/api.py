"""API fina de orquestación de alto nivel (CT-4): ensamblado de corrida."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nikodym.audit import AuditConfig, JsonlAuditSink
from nikodym.core.audit import AuditSink, FanOutSink, NullAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.dataset_check import DatasetCheck, check_dataset
from nikodym.core.exceptions import ConfigError, NikodymError
from nikodym.core.steps import ArtifactKey
from nikodym.core.study import Study, _missing_backup_path, _replace_path
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

    ``inert_artifacts`` enumera, en orden canónico, las claves externas que ningún paso activo ni
    el cierre transversal del lineage consumirá. No vuelven el config inejecutable: son un aviso
    contra typos o material preparado para una sección todavía apagada.

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
    inert_artifacts: tuple[ArtifactKey, ...] = ()


def check_pipeline(
    config: NikodymConfig,
    *,
    artifacts: Iterable[ArtifactKey] | Mapping[ArtifactKey, Any] | None = None,
) -> PipelineCheck:
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
    artifacts : Iterable[ArtifactKey] | Mapping[ArtifactKey, Any] | None
        Claves de artefactos que estarán disponibles al correr. Si se entrega un mapping, sus
        valores se ignoran: comprobar sólo necesita las claves. Una clave válida que ningún paso
        activo consume se publica en ``PipelineCheck.inert_artifacts`` en vez de bloquear.

    Returns
    -------
    PipelineCheck
        ``executable=True`` + ``steps`` en orden, o ``executable=False`` + el diagnóstico del motor.
    """
    study: Study | None = None
    try:
        # `apply_global_seed=False`: comprobar no puede sembrar los RNG del proceso. El formulario
        # llama aquí en cada tecleo, y sembrar dejaba el hint `PYTHONHASHSEED` —que se fija una sola
        # vez por proceso— anclado a la semilla del config que se editaba, no a la de la corrida.
        study = Study(config, apply_global_seed=False)
        _inject_artifacts(study, _artifact_values_for_check(artifacts))
        pasos = study.check_pipeline()
    except ValidationError as exc:
        return PipelineCheck(
            executable=False,
            error_type=type(exc).__name__,
            message=_mensaje_de_validacion(exc),
            is_domain_error=True,
            inert_artifacts=study.inert_injected_artifacts if study is not None else (),
        )
    # Captura amplia a propósito (ver docstring): informar nunca debe tumbar al llamante.
    except Exception as exc:
        return PipelineCheck(
            executable=False,
            error_type=type(exc).__name__,
            message=str(exc),
            is_domain_error=isinstance(exc, NikodymError),
            inert_artifacts=study.inert_injected_artifacts if study is not None else (),
        )
    return PipelineCheck(
        executable=True,
        steps=tuple(pasos),
        inert_artifacts=study.inert_injected_artifacts,
    )


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


def run(
    config: NikodymConfig,
    *,
    artifacts: Mapping[ArtifactKey, Any] | None = None,
    run_dir: str | Path | None = None,
) -> Study:
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

    ``study.results`` es el **resumen** firmable de la corrida, no un duplicado del store: trae
    ``metrics`` —plano, ``"<dominio>.<metrica>"``, ``float`` finito— y ``metric_sections`` por
    dominio (D-GOB-1…3). Es lo que leen el model card y MLflow. Una métrica que el dominio no pudo
    evaluar **no aparece**; ausencia y cero no son lo mismo.

    **Dónde queda la evidencia en disco:** en ``run_dir``, y sólo si se pide (D-GOB-6). Con el
    default ``None`` la corrida **no escribe nada**, que es el comportamiento histórico: una
    librería que empieza a dejar archivos en el ``cwd`` de quien la importa es una regresión, no una
    mejora. Con un ``run_dir`` se escribe allí el layout de SDD-03 §6::

        <run_dir>/audit_trail.jsonl   # si `audit` está activo (su nombre lo fija AuditConfig)
        <run_dir>/environment.json    # si `audit` está activo y captura entorno
        <run_dir>/model_card.json     # si `governance` está activa
        <run_dir>/model_card.md       # idem
        <run_dir>/study/              # lo que produce `Study.save`: config, lineage y artefactos

    Cada archivo aparece **sólo si su sección está activa**: ``audit`` sin ``governance`` deja trail
    y entorno, y no card. ``scenario_log.jsonl`` del layout de SDD-03 §6 **no** se escribe: hoy no
    tiene ningún productor, y crear un archivo vacío para cumplir el layout sería teatro.

    **Entrar por la mitad.** ``artifacts=`` permite traer resultados ya calculados. Las claves son
    las parejas ``(dominio, clave)`` declaradas en ``Step.requires``/``Step.provides``; hay que
    apagar en el config la sección que produciría cualquiera de las claves inyectadas. El tipo lo
    valida el paso consumidor, no esta puerta. Toda corrida que recibe artefactos externos los
    enumera en ``lineage.injected_artifacts`` y declara que no es reconstruible sólo desde config
    y datos. Esta puerta es de código: la UI/HTTP no deserializa artefactos externos.

    **Dónde queda el diagnóstico.** En ``study.run_context.error``
    (:class:`~nikodym.core.lineage.RunError`): tipo de la excepción, mensaje del motor y paso que
    falló, sin que haya que configurar nada. El audit-trail lo repite en el evento ``run_end``, pero
    **sólo si el config declara un sink**: los presets lo declaran desde D-GOB-8, pero un config
    escrito a mano puede traer ``audit: null``, así que no dependa de él; y el lineage no guarda el
    error nunca (enmienda RUN-ERROR).
    """
    destino = _preparar_run_dir(run_dir)
    sink, inventory = assemble_run(config, run_dir=destino)
    fallo_de_dominio = False
    try:
        governance_cfg = _governance_config(config.governance)
        study = Study(config)
        study.set_audit_sink(sink)
        _inject_artifacts(study, artifacts or {})
        try:
            study.run()
        except NikodymError:
            # Fallo esperado de dominio: el Study queda con status="failed" + lineage conservado
            # (SDD-01 §7.3). No se propaga: se devuelve para inspección (D-UI-2).
            fallo_de_dominio = True
    finally:
        # El sink pertenece a ``run`` desde que ``assemble_run`` lo entrega. Se cierra ante éxito,
        # error de dominio y cualquier excepción inesperada, incluidos fallos al inyectar o al
        # construir el Study. Además se cierra ANTES de leer el trail para la ModelCard.
        _close_audit_sink(sink)

    # La evidencia se escribe en los DOS caminos y en UN solo punto: el model card de una corrida
    # fallida es explícitamente válido (SDD-03 §7.1.a) y es justo el que hay que conservar.
    #
    # ⚠️ Fuera del `finally` a propósito. Escribirlo allí, con el `return` del camino de fallo
    # pendiente, dejaba que un error de disco REEMPLAZARA al `Study` que D-UI-2 promete devolver:
    # un escritor de evidencia no puede convertir «corrida fallida, inspeccionable» en una
    # excepción opaca. Aquí un fallo al escribir se propaga como lo que es, en los dos caminos.
    if destino is not None:
        _escribir_layout_del_run(study, config, destino)
    if fallo_de_dominio:
        return study

    if governance_cfg is not None and governance_cfg.publish_to_inventory:
        entry = _build_inventory_entry(study, governance_cfg, config)
        inventory.register(entry)
    return study


def _resolver_trail(audit_cfg: AuditConfig, run_dir: Path | None) -> Path:
    """Resuelve la ruta del audit-trail contra el directorio del run, nunca contra el ``cwd``.

    🔴 Antes esto era ``Path(audit_cfg.trail_filename)`` a secas, es decir **relativo al ``cwd``**,
    mientras ``audit/config.py`` describe el campo como «el nombre del JSONL dentro del directorio
    del run». Dos corridas lanzadas desde el mismo ``cwd`` concatenaban sus trails en el mismo
    archivo *append-only*, que es exactamente lo que SDD-03 §8 prohíbe («una instancia por run»).
    Medido antes de D-GOB-7.

    Una ruta **absoluta** se sigue respetando tal cual: quien la escribe ya eligió dónde. Una ruta
    **relativa sin ``run_dir``** pasa a ser un error explícito en vez de escribir en el ``cwd`` en
    silencio — que es la clase de efecto lateral que una librería no debe tener.
    """
    trail = Path(audit_cfg.trail_filename)
    if trail.is_absolute():
        return trail
    if run_dir is not None:
        return run_dir / trail
    raise ConfigError(
        f"audit.enabled=True con trail_filename relativo ('{audit_cfg.trail_filename}') y sin "
        "run_dir: no hay dónde escribir el audit-trail sin dejar archivos en el directorio de "
        "trabajo. Pase run_dir= a nikodym.run(), o dé a trail_filename una ruta absoluta."
    )


def _preparar_run_dir(run_dir: str | Path | None) -> Path | None:
    """Crea el directorio de la corrida; aparta el previo si existe y no está vacío (D-GOB-6).

    La política de sobrescritura es la misma de ``Study.save``: el contenido anterior se **aparta**
    a un respaldo lateral, no se mezcla. Mezclar dos corridas en un directorio produce un trail
    concatenado y un model card que no corresponde a los artefactos de al lado, que es peor que
    perder el previo.

    Por eso reutiliza ``_missing_backup_path``/``_replace_path`` de ``core.study`` en vez de
    reimplementarlos: la enmienda pide LA MISMA política, y dos copias de ella divergirían en el
    primer arreglo que tocara una sola.
    """
    if run_dir is None:
        return None
    destino = Path(run_dir)
    if destino.exists() and any(destino.iterdir()):
        _replace_path(destino, _missing_backup_path(destino))
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _escribir_layout_del_run(study: Study, config: NikodymConfig, destino: Path) -> None:
    """Escribe el layout de SDD-03 §6 en el directorio del run (D-GOB-6).

    Cada archivo depende de que su sección esté activa. Nada se fabrica para completar el layout:
    ``scenario_log.jsonl`` queda fuera porque no tiene productor, y decirlo es más honesto que
    dejar un archivo vacío que aparenta un control que no corre.
    """
    audit_cfg = _audit_config(config.audit)
    governance_cfg = _governance_config(config.governance)

    if audit_cfg is not None and audit_cfg.enabled and audit_cfg.capture_environment:
        from nikodym.audit.environment import capture_environment

        entorno = capture_environment(packages=audit_cfg.tracked_packages)
        (destino / "environment.json").write_text(
            json.dumps(entorno.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if governance_cfg is not None:
        trail = (
            _resolver_trail(audit_cfg, destino)
            if audit_cfg is not None and audit_cfg.enabled
            else None
        )
        try:
            card = ModelCardBuilder(governance_cfg).build(study, trail_path=trail)
        except NikodymError:
            # Corrida demasiado parcial para una card válida: ausente, no fabricada. Es el mismo
            # criterio que la UI (SDD-23 §6/§8); un card inventado sería peor que ninguno.
            card = None
        if card is not None:
            (destino / "model_card.json").write_text(card.to_json(), encoding="utf-8")
            (destino / "model_card.md").write_text(card.to_markdown(), encoding="utf-8")

    if study.run_context.run_id is not None:
        # `Study.save` sustituye su directorio de forma atómica, así que va a un SUBdirectorio: si
        # escribiera en `destino` borraría el trail que la propia corrida acaba de dejar ahí.
        study.save(destino / "study")


def _artifact_values_for_check(
    artifacts: Iterable[ArtifactKey] | Mapping[ArtifactKey, Any] | None,
) -> Mapping[ArtifactKey, object]:
    """Convierte claves declaradas para el preflight en valores centinela que nunca se consumen."""
    if artifacts is None:
        return {}
    keys = artifacts.keys() if isinstance(artifacts, Mapping) else artifacts
    return dict.fromkeys(keys, _ARTIFACT_SENTINEL)


_ARTIFACT_SENTINEL = object()


def _inject_artifacts(study: Study, artifacts: Mapping[ArtifactKey, Any]) -> None:
    """Siembra artefactos externos después de conectar el sink y conserva su procedencia."""
    for (domain, key), value in artifacts.items():
        study._register_injected_artifact(domain, key)
        study.artifacts.set(domain, key, value)


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


def assemble_run(
    config: NikodymConfig, *, run_dir: Path | None = None
) -> tuple[AuditSink, ModelInventory]:
    """Construye el ``AuditSink`` compuesto y el inventario real/no-op de una corrida.

    ``core`` recibe ambos objetos ya resueltos: no importa ``audit``, ``governance``, ``tracking``
    ni MLflow. Si ``governance.publish_to_inventory=True`` y falta el extra ``tracking``, esta capa
    falla ruidoso con ``MissingDependencyError`` porque la publicación fue una petición explícita.

    ``run_dir`` es el directorio de la corrida (D-GOB-6): contra él se resuelve el nombre relativo
    del audit-trail. Sin él, un ``trail_filename`` relativo es un **error explícito** (D-GOB-7).
    """
    audit_cfg = _audit_config(config.audit)
    governance_cfg = _governance_config(config.governance)
    tracking_cfg = _tracking_config(config.tracking)

    sinks: list[AuditSink] = []
    try:
        if audit_cfg is not None and audit_cfg.enabled:
            trail = _resolver_trail(audit_cfg, run_dir)
            sinks.append(JsonlAuditSink(trail, config=audit_cfg))
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
    except BaseException:
        # Si el ensamblado falla después de abrir un sink (p. ej. falta MLflow), ``run`` todavía
        # no recibió nada que pueda cerrar en su ``finally``. Esta capa conserva esa propiedad.
        for sink in sinks:
            _close_audit_sink(sink)
        raise


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
