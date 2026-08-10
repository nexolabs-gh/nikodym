"""Orquestador *end-to-end* del experimento: la clase :class:`Study` (SDD-01 §4/§6/§7; CT-1/CT-4).

El ``Study`` es la fundación *stateful* de una corrida: aloja el ``config`` (frozen, fuente de
verdad), el ``ArtifactStore`` namespaced, los ``results`` intermedios, el ``RunContext`` (estado de
vida) y el ``SeedManager`` (azar reconstruible, nunca serializado). :meth:`Study.run` ejecuta el
pipeline **en orden de declaración** (motor v1) y sólo **valida prerequisitos** (CT-1): el scheduler
topológico se difiere a F5 sin tocar las firmas. La persistencia es un **directorio atómico**; la
recarga tiene una puerta de confianza ``trust`` (vector *pickle*) y verifica el ``config_hash``
(reproducibilidad). ``core`` recibe el ``AuditSink`` **ya compuesto** vía ``set_audit_sink``
(CT-4): no ensambla ``FanOutSink`` ni resuelve inventario (eso vive en api/runner, no en ``core``).

**Experimental (fuera de la garantía SemVer 1.x):** el motor de orquestación crece (DAG
diferido) en las versiones 1.x. En F0
``NikodymConfig`` no expone secciones de dominio orquestables: el pipeline por defecto
(``steps=None``) es trivial y la resolución config → pasos se materializa en T2 con los dominios.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import tempfile
import time
import uuid
import warnings
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from nikodym.core.artifacts import ArtifactStore
from nikodym.core.audit import AuditEvent, AuditKind, AuditSink, NullAuditSink
from nikodym.core.base import BaseNikodymEstimator
from nikodym.core.config import NikodymConfig, config_hash, dump_config, load_config
from nikodym.core.exceptions import (
    ArtifactNotFoundError,
    ConfigError,
    NikodymError,
    ReproducibilityError,
    UntrustedStudyError,
)
from nikodym.core.lineage import LineageBundle, RunContext, RunError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.seeding import SeedManager

if TYPE_CHECKING:
    from nikodym.core.steps import ArtifactKey, ContextoDeResolucion, Step

__all__ = ["Study"]

# Librerías cuya versión se congela en el lineage (evidencia reproducible de la corrida).
_LIBRERIAS_LINEAGE = ("nikodym", "numpy", "pandas", "pydantic", "PyYAML")
_DOMAIN_MODULES: Final[dict[str, str]] = {
    "data": "nikodym.data",
    "markov": "nikodym.markov",
    "forward": "nikodym.forward",
    "stress": "nikodym.stress",
    "eda": "nikodym.eda",
    "binning": "nikodym.binning",
    "selection": "nikodym.selection",
    "model": "nikodym.model",
    "scorecard": "nikodym.scorecard",
    "calibration": "nikodym.calibration",
    "tuning": "nikodym.tuning",
    "ml": "nikodym.ml",
    "explain": "nikodym.explain",
    "performance": "nikodym.performance",
    "stability": "nikodym.stability",
    "report": "nikodym.report",
    "survival": "nikodym.survival",
    "provisioning_ifrs9": "nikodym.provisioning.ifrs9",
    "provisioning_cmf": "nikodym.provisioning.cmf",
    "provisioning_internal": "nikodym.provisioning.internal",
    "provisioning": "nikodym.provisioning",
    "validation": "nikodym.validation",
}
_DOMAIN_CONFIG_CLASSES: Final[dict[str, tuple[str, str]]] = {
    "data": ("nikodym.data.config", "DataConfig"),
    "markov": ("nikodym.markov.config", "MarkovConfig"),
    "forward": ("nikodym.forward.config", "ForwardConfig"),
    "stress": ("nikodym.stress.config", "StressConfig"),
    "eda": ("nikodym.eda.config", "EdaConfig"),
    "binning": ("nikodym.binning.config", "BinningConfig"),
    "selection": ("nikodym.selection.config", "SelectionConfig"),
    "model": ("nikodym.model.config", "ModelConfig"),
    "scorecard": ("nikodym.scorecard.config", "ScorecardConfig"),
    "calibration": ("nikodym.calibration.config", "CalibrationConfig"),
    "tuning": ("nikodym.tuning.config", "TuningConfig"),
    "ml": ("nikodym.ml.config", "MLConfig"),
    "explain": ("nikodym.explain.config", "ExplainConfig"),
    "performance": ("nikodym.performance.config", "PerformanceConfig"),
    "stability": ("nikodym.stability.config", "StabilityConfig"),
    "report": ("nikodym.report.config", "ReportConfig"),
    "survival": ("nikodym.survival.config", "SurvivalConfig"),
    "provisioning_ifrs9": (
        "nikodym.provisioning.ifrs9.config",
        "IfrsProvisioningConfig",
    ),
    "provisioning_cmf": ("nikodym.provisioning.cmf.config", "CmfProvisioningConfig"),
    "provisioning_internal": (
        "nikodym.provisioning.internal.config",
        "InternalProvisioningConfig",
    ),
    "provisioning": ("nikodym.provisioning.config", "ProvisioningConfig"),
    "validation": ("nikodym.validation.config", "ValidationConfig"),
}
_DEFAULT_DOMAIN_ORDER: Final[tuple[str, ...]] = (
    "data",
    "markov",
    "eda",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "tuning",
    "ml",
    "explain",
    "survival",
    "forward",
    "stress",
    "performance",
    "stability",
    "provisioning_ifrs9",
    "provisioning_cmf",
    "provisioning_internal",
    "provisioning",
    "validation",
    # ``report`` corre AL FINAL: es la foto de todo lo que corrió. Antes vivía tras ``stability``,
    # de modo que ``ReportBuilder`` nunca veía las cards de provisiones y su capítulo condicional
    # era inalcanzable (SDD-28 D8). ``report`` es INFRA (no entra al ``config_hash``), así que
    # reordenar es barato y no mueve la identidad de ninguna corrida.
    "report",
)
_REPLACE_RETRY_ATTEMPTS: Final = 3
_REPLACE_RETRY_BACKOFF_SECONDS: Final = 0.05


def _estado_git() -> tuple[str | None, bool]:
    """Devuelve ``(git_sha, git_dirty)`` del repo en *cwd*; ``(None, False)`` si no hay git."""
    import subprocess  # import perezoso: core no arrastra subprocess al importarse

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, False
    return sha, bool(porcelain)


def _versiones_librerias() -> dict[str, str]:
    """Recolecta la versión instalada de las librerías del lineage (las ausentes se omiten)."""
    versiones: dict[str, str] = {}
    for libreria in _LIBRERIAS_LINEAGE:
        try:
            versiones[libreria] = metadata.version(libreria)
        except metadata.PackageNotFoundError:
            continue
    return versiones


def _advertir_drift_versiones(guardadas: dict[str, str]) -> None:
    """Advierte (sin abortar) si las versiones instaladas difieren de las de la corrida original."""
    actuales = _versiones_librerias()
    drift = {
        lib: (ver, actuales.get(lib)) for lib, ver in guardadas.items() if actuales.get(lib) != ver
    }
    if drift:
        warnings.warn(
            f"Versiones de librerías distintas de la corrida original (original, actual): {drift}",
            stacklevel=2,
        )


def _replace_path(src: Path, dst: Path) -> None:
    """Mueve ``src`` a ``dst`` con reintentos ante locks transitorios del sistema de archivos."""
    attempt = 0
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            attempt += 1
            if attempt >= _REPLACE_RETRY_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_BACKOFF_SECONDS)


def _missing_backup_path(destino: Path) -> Path:
    """Reserva y libera una ruta única inexistente para respaldos laterales."""
    respaldo = Path(tempfile.mkdtemp(prefix=f".{destino.name}.old.", dir=destino.parent))
    respaldo.rmdir()
    return respaldo


def _component_type(sub_cfg: Any) -> str:
    """Lee el discriminador ``type`` de una sección de config; default v1 = ``standard``."""
    if isinstance(sub_cfg, dict):
        raw = sub_cfg.get("type", "standard")
    else:
        raw = getattr(sub_cfg, "type", "standard")
    if not isinstance(raw, str):
        raise ConfigError(
            "El discriminador 'type' de la sección de config debe ser texto; "
            f"se recibió {type(raw).__name__}."
        )
    return raw


class Study:
    """Estado del experimento y orquestador de la corrida (SDD-01 §4/§7).

    Un ``Study`` recién construido arranca en ``status="created"`` y serializa sin valores ficticios
    (DoD F0). :meth:`run` lo transiciona a ``running`` → ``done``/``failed`` y congela el lineage.
    El ``config`` es inmutable: su identidad se ancla al ``config_hash``.
    """

    def __init__(
        self,
        config: NikodymConfig,
        *,
        name: str | None = None,
        apply_global_seed: bool = True,
    ) -> None:
        if name is not None:
            # El config es frozen: un override de nombre construye un config nuevo (name es INFRA,
            # no entra al config_hash, así que no altera la identidad de la corrida).
            config = config.model_copy(update={"name": name})
        self.config = config
        self.seed_manager = SeedManager(config.repro.seed)
        # `apply_global_seed=False` es para INSPECCIONAR un config sin correrlo (lo usa
        # `nikodym.check_pipeline`, que el formulario invoca en cada tecleo). Sembrar es un efecto
        # de PROCESO, no del objeto: `apply_global` resetea el `random` global y fija el hint
        # `PYTHONHASHSEED` que heredan los subprocesos —y lo fija SÓLO la primera vez—. Con la
        # comprobación sembrando, ese hint quedaba anclado a la semilla del config que se estaba
        # EDITANDO, no a la de la corrida que después se ejecuta: justo el no-determinismo
        # silencioso que SDD-01 §9 existe para evitar. Medido.
        if apply_global_seed:
            self.seed_manager.apply_global()
        self._audit: AuditSink = NullAuditSink()
        self.artifacts = ArtifactStore(audit=self._audit)
        # ⚠️ Canal de publicación de métricas hacia `governance` y `tracking`, y NINGÚN paso del
        # motor lo llena hoy: tras una corrida F1 completa sigue siendo `{}` (medido). Sus dos
        # consumidores lo leen igual —`ModelCardBuilder` toma de aquí `metrics`/`metric_sections`
        # (`governance/model_card.py:189`) y `TrackingSink` lo vuelca entero a MLflow
        # (`tracking/sink.py:47`)—, así que un model card publicado sale SIN métricas. No se ve
        # en los presets porque los tres traen `governance: null` y `tracking: null`; quien los
        # encienda sí lo nota. Los resultados reales viven en `self.artifacts`, por
        # `(dominio, clave)`.
        # Llenarlo es contrato (qué claves, qué DTOs) y por tanto trabajo de SDD, no un parche aquí.
        self.results: dict[str, Any] = {}
        self.run_context = RunContext()
        self._injected_artifacts: set[ArtifactKey] = set()
        self._inert_injected_artifacts: tuple[ArtifactKey, ...] = ()
        self._resolved_step_names: frozenset[str] = frozenset()

    # --- Gobernanza (hooks hacia SDD-03; core recibe el sink ya compuesto, CT-4) --------------

    def set_audit_sink(self, sink: AuditSink) -> None:
        """Inyecta el ``AuditSink`` (ya compuesto por api/runner) y lo propaga al ``ArtifactStore``.

        Debe llamarse antes de :meth:`run`. ``core`` no compone ``FanOutSink`` ni resuelve el
        inventario (CT-4): toma un sink ya resuelto.
        """
        self._audit = sink
        self.artifacts._audit = sink

    def lineage_bundle(self) -> LineageBundle:
        """Devuelve el :class:`LineageBundle` congelado en :meth:`run`; levanta si no se corrió."""
        if self.run_context.status == "created" or self.run_context.lineage is None:
            raise NikodymError(
                f"El Study no tiene lineage (status='{self.run_context.status}'): "
                "llame run() antes de pedirlo."
            )
        return self.run_context.lineage

    def _register_injected_artifact(self, domain: str, key: str) -> None:
        """Registra procedencia externa antes de escribir el valor en el ``ArtifactStore``.

        Es un hook interno de la puerta pública ``nikodym.run(..., artifacts=...)``. No valida el
        tipo del valor: esa responsabilidad permanece en el paso consumidor para que ``core`` no
        importe DTOs de dominio.
        """
        self._injected_artifacts.add((domain, key))

    @property
    def inert_injected_artifacts(self) -> tuple[ArtifactKey, ...]:
        """Expone a la API las claves externas que ningún paso activo consume."""
        return self._inert_injected_artifacts

    # --- Orquestación (motor v1: orden de declaración + validación de prerequisitos, CT-1) -----

    def run(self, steps: list[str] | None = None) -> Study:
        """Ejecuta el pipeline y devuelve ``self`` (encadenable).

        El argumento ``steps`` tiene prioridad sobre ``config.run.steps``. ``fail_fast=False`` no se
        soporta en v1: se emite un *warning* ruidoso (no un no-op silencioso) y se procede como
        ``True``. Una excepción en un paso (con ``fail_fast=True``) deja ``status="failed"`` pero
        **conserva el lineage** (evidencia de trazabilidad, SR 11-7), escribe el rastro del fallo en
        ``run_context.error`` (:class:`~nikodym.core.lineage.RunError`: tipo, mensaje y paso), sella
        ``finished_at``, emite ``run_end`` y se re-levanta; el ``Study`` parcial sigue siendo
        guardable.
        """
        nombres = steps if steps is not None else self.config.run.steps
        if not self.config.run.fail_fast:
            warnings.warn(
                "fail_fast=False no está soportado en v1: se fuerza True (reservado para v2).",
                stacklevel=2,
            )
        run_id = uuid.uuid4().hex
        self.run_context.run_id = run_id
        self.run_context.started_at = datetime.now(UTC)
        self.run_context.status = "running"
        # Secuencia del SDD-01 §7.3 paso 2: status="running" → emitir run_start → iniciar el
        # LineageBundle. En F0 ``data_hash`` queda None; en B2+ lo completa el paso de datos antes
        # de cerrar.
        self._emit("run_start", None, {"run_id": run_id, "name": self.config.name})

        # La RESOLUCIÓN del pipeline va después del `run_id` y bajo el mismo registro de fallo que
        # la ejecución (D-ERR-8/D-ERR-9). Estaba antes, y sin `try`: un config inejecutable dejaba
        # el `run_context` intacto —`status="created"`, `error=None`— y `nikodym.run`, que captura
        # el `NikodymError`, devolvía un Study en el que no había NADA que inspeccionar. El motor
        # produce ahí un diagnóstico exacto («el paso X requiere (Y, Z), que ningún paso aguas
        # arriba produce»); se perdía entero, y aguas abajo la UI no podía ni persistir la corrida
        # —sin `run_id` no hay qué guardar— así que respondía un HTTP 500 opaco.
        try:
            pasos = self._resolve_steps(nombres)
            self._validate_injected_artifacts(pasos, emit_warnings=True)
            self._validate_pipeline(pasos)
        except Exception as exc:
            # step=None a propósito (D-ERR-11): no hay paso en curso porque el config es
            # inejecutable ANTES del primero, y eso le dice al lector dónde mirar.
            self._registrar_fallo(exc, paso=None, run_id=run_id)
            raise
        finally:
            # ⚠️ EL LINEAGE SE CONGELA DESPUÉS DE RESOLVER, y el `finally` es lo que mantiene la
            # garantía de D-ERR-8: se cuelga igual si la resolución falla, así que la evidencia
            # (config_hash, git_sha, versiones) no se pierde justo en el caso que más interesa
            # auditar.
            #
            # Construirlo ANTES de resolver —como quedó al implementar D-ERR-9— congelaba un
            # `config_hash` que el propio `save()` luego contradecía: `_resolve_steps` COACCIONA las
            # secciones de dominio que llegan opacas (`_coerce_domain_config` hace un `model_copy`),
            # y esa coacción materializa los defaults que el YAML no traía. El lineage guardaba el
            # hash del config opaco y el `config.yaml` el del coaccionado, así que `Study.load()`
            # rechazaba con `ReproducibilityError` un estudio que esta misma versión acababa
            # de guardar. Medido con un config cargado de YAML al que le falta un campo con default
            # —el caso de quien lo escribe a mano—; no se ve con los presets, que escriben todos los
            # campos explícitos, ni con un config construido en Python, que ya llega tipado.
            self.run_context.lineage = self._build_lineage()

        # El paso en curso se rastrea fuera del try para poder nombrarlo en el rastro del fallo:
        # sin él, "falló la corrida" no dice en qué etapa del pipeline (enmienda RUN-ERROR, D-ERR-2)
        paso_actual: Step | None = None
        try:
            for paso in pasos:
                paso_actual = paso
                self._run_one(paso)
        except Exception as exc:
            self._registrar_fallo(exc, paso=paso_actual, run_id=run_id)
            raise
        self.run_context.finished_at = datetime.now(UTC)
        self.run_context.status = "done"
        self._emit("run_end", None, {"run_id": run_id, "status": "done"})
        return self

    def check_pipeline(self, steps: list[str] | None = None) -> list[str]:
        """Resuelve y valida el pipeline **sin ejecutar nada**; devuelve los pasos en orden.

        Responde la pregunta «¿este config se puede correr?» antes de correrlo, que es lo que
        permite avisarlo mientras se edita en vez de al apretar Ejecutar (enmienda
        VALIDACION-PIPELINE, D-PIPE-3). La capacidad vive aquí, en el núcleo, y no en la capa UI:
        quien trabaja por código tiene la misma respuesta que quien usa el formulario, que es el
        requisito de paridad.

        Es *fail-loud* como :meth:`run`: un config inejecutable levanta el ``ConfigError`` del
        motor con su diagnóstico. El envoltorio de producto que lo captura y devuelve un veredicto
        inspeccionable es :func:`nikodym.check_pipeline`, igual que :func:`nikodym.run` frente a
        :meth:`run` (D-UI-2).

        **No toca el ``run_context``**: no asigna ``run_id``, no cambia ``status`` ni sella
        ``finished_at``. Comprobar no es correr, y una comprobación no debe dejar rastro de corrida
        en el audit-trail. No lee el dataset ni escribe en disco, y cuesta ≤0,1 ms con los dominios
        ya importados (la primera llamada del proceso paga sus imports perezosos, ~1-3 s).

        **Sí tiene un efecto, y no es cosmético:** :meth:`_resolve_steps` coacciona los sub-configs
        opacos a su clase real, exactamente como haría :meth:`run`, y esa coacción materializa los
        defaults que un config cargado de YAML no traía — con lo que **el ``config_hash`` de este
        ``Study`` puede cambiar**. Es convergente (coaccionar dos veces da lo mismo) y deja el
        config en el estado que tendría al correr, así que una corrida posterior sobre el mismo
        ``Study`` es consistente; pero quien compare hashes alrededor de esta llamada debe saberlo.

        Lo que **no** hace es sembrar los RNG del proceso cuando el ``Study`` se construyó con
        ``apply_global_seed=False``, que es como lo hace :func:`nikodym.check_pipeline`.
        """
        nombres = steps if steps is not None else self.config.run.steps
        pasos = self._resolve_steps(nombres)
        self._validate_injected_artifacts(pasos, emit_warnings=False)
        self._validate_pipeline(pasos)
        return [paso.name for paso in pasos]

    def _registrar_fallo(self, exc: Exception, *, paso: Step | None, run_id: str) -> None:
        """Deja el rastro de una corrida fallida en ``run_context`` y en el trail (D-ERR-10).

        UN solo sitio para las dos fases —resolución del pipeline y ejecución de los pasos—, porque
        tenerlo duplicado es exactamente lo que permitió que divergieran: el manejo de fallo cubría
        el bucle de pasos y dejaba fuera la resolución, de modo que un config inejecutable no dejaba
        rastro alguno.

        El diagnóstico del motor se emitía SÓLO al sink; con un ``NullAuditSink`` (el que arma el
        preset recomendado) se perdía. Vive también en el ``run_context`` que el usuario ya tiene en
        la mano (D-ERR-1), y la corrida declara cuándo terminó (D-ERR-3). ``paso=None`` significa
        que no había paso en curso (D-ERR-11).
        """
        self.run_context.status = "failed"
        self.run_context.finished_at = datetime.now(UTC)
        self.run_context.error = RunError(
            type=type(exc).__name__,
            message=str(exc),
            step=paso.name if paso is not None else None,
            is_domain_error=isinstance(exc, NikodymError),
            ts=self.run_context.finished_at,
        )
        # Payload aditivo (D-ERR-6): 'error' se conserva tal cual estaba; un lector existente
        # del trail no se entera de las claves nuevas (CT-3).
        self._emit(
            "run_end",
            None,
            {
                "run_id": run_id,
                "status": "failed",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "step": self.run_context.error.step,
            },
        )

    def run_step(self, name: str) -> Any:
        """Ejecuta un paso aislado y devuelve su resultado; no altera ``run_context.status``.

        Emite sólo los eventos del paso (no ``run_start``/``run_end``) y exige sus prerequisitos
        presentes. En F0 ``NikodymConfig`` no expone secciones de dominio, así que la resolución
        levanta ``ConfigError`` (la orquestación de dominios llega en T2).

        **Se resuelve SIN contexto de dominios activos, a propósito** (D-FX-1). ``[name]`` no es
        «el pipeline de esta invocación»: es *un paso suelto sobre artefactos que ya deben estar en
        el store*. Pasar ``{name}`` como conjunto activo convertiría la comprobación CT-1 de este
        método en vacua para cualquier paso cuyo ``requires`` se derive del contexto —``run_step
        ('report')`` dejaría de exigir sus cards—, y la precedencia que D-FX-1 fija (``steps=`` →
        ``config.run.steps`` → secciones no nulas) describe una **corrida**, no este atajo.
        """
        return self._run_one(self._resolve_step(name))

    def _resolve_steps(self, nombres: list[str] | None) -> list[Step]:
        """Resuelve los nombres de paso a objetos :class:`Step` (config → REGISTRY → StepAdapter).

        Los dominios orquestables se registran al importar su paquete. El import es perezoso para
        que ``import nikodym.core`` no arrastre pandas/pandera/pyarrow ni dominios aguas abajo. El
        pipeline por defecto sigue siendo vacío si no hay secciones activas.

        La lista resuelta es además el **contexto** que se ofrece a cada componente (D-FX-1): un
        paso puede necesitar saber qué otros dominios corren en ESTA invocación para declarar
        honestamente su ``requires``. «Activo» es *estar en la lista efectiva*, no *tener sección no
        nula*: con ``steps=['data','binning']`` el resto está apagado para esta corrida, y usar
        ``section is not None`` describiría un DAG distinto del que se va a ejecutar.
        """
        if nombres is None:
            nombres = self._default_step_names()
        contexto = self._contexto_de_resolucion(frozenset(nombres))
        return [self._resolve_step(nombre, contexto=contexto) for nombre in nombres]

    def _contexto_de_resolucion(self, activos: frozenset[str]) -> ContextoDeResolucion:
        """Arma el DTO que reciben las fábricas contextuales (D-REQ-2).

        Pregunta por :data:`METODO_CONTRATO_VARIABLES`, que es una convención de nombre y no una
        clase base: el núcleo no conoce qué sección lo declara ni qué significan sus claves, sólo
        las transporta.

        🔴 **Recorre las secciones DECLARADAS, no las activas, y la diferencia no es un detalle: el
        primer arreglo la ignoró y dejó el defecto vivo por la puerta pública.** Con
        ``run.steps=['tuning']`` la sección ``ml`` existe y **no corre**, pero ``tuning.execute``
        lee ``study.config.ml`` igual —no mira si ``ml`` está entre los pasos—, así que sus
        requisitos siguen dependiendo de ella. Mirar sólo lo activo describía un config distinto del
        que el paso va a leer, que es exactamente el defecto que esta enmienda cierra.

        ⚠️ ``dominios_activos`` **sí** es el conjunto activo: son dos preguntas distintas —«¿quién
        corre?» y «¿qué se decidió?»— y por eso viven en dos campos del DTO en vez de en uno.

        ⚠️ **Coacciona para preguntar, y si la coacción falla lo trata como «no se sabe».** Una
        sección viaja opaca por defecto —``model_validate`` no la tipa salvo que alguien haya
        importado su capa— y ahí no hay método que llamar; y coaccionar puede levantar (D-ANC-10),
        porque un config inválido es alcanzable desde el formulario. En los dos casos el contrato
        queda vacío y el paso conserva el que declararía por sí solo (D-REQ-4): degradar al
        comportamiento histórico es correcto, romper la resolución del pipeline por no poder mirar
        una sección ajena no lo sería.
        """
        from types import MappingProxyType

        from pydantic import ValidationError

        from nikodym.core.steps import METODO_CONTRATO_VARIABLES, ContextoDeResolucion

        contrato: dict[str, str] = {}
        for nombre in sorted(_DEFAULT_DOMAIN_ORDER):
            seccion = getattr(self.config, nombre, None)
            if seccion is None:
                continue
            try:
                tipada = self._coerce_domain_config(nombre, seccion)
            except (ValidationError, NikodymError):
                continue
            declarado = getattr(tipada, METODO_CONTRATO_VARIABLES, None)
            if callable(declarado):
                contrato.update(declarado())
        return ContextoDeResolucion(
            dominios_activos=activos, contrato_de_variables=MappingProxyType(contrato)
        )

    def _default_step_names(self) -> list[str]:
        """Deriva el pipeline v1 desde secciones activas del config raíz."""
        return [
            domain
            for domain in _DEFAULT_DOMAIN_ORDER
            if getattr(self.config, domain, None) is not None
        ]

    def _resolve_step(
        self,
        name: str,
        *,
        contexto: ContextoDeResolucion | None = None,
    ) -> Step:
        """Resuelve un paso por nombre de sección usando el ``REGISTRY`` global.

        ``contexto`` es lo que el paso puede saber de la invocación (D-FX-1, D-REQ-2). Se entrega
        por una **extensión genérica y opcional** del resolver (D-FX-2): si el componente expone
        ``from_config_with_context(sub_cfg, *, contexto)`` se usa esa fábrica; si no, se usa el
        ``from_config(sub_cfg)`` de siempre. No hay ``if name == "report"`` ni introspección de
        firmas: el núcleo no conoce ningún dominio, y un dominio que no necesite el contexto no
        cambia una línea.

        ``contexto=None`` significa **«no se sabe»**, no «ninguno»: se usa la fábrica histórica y el
        paso conserva el contrato que declararía por sí solo. Es lo que reciben :meth:`run_step` y
        cualquier resolución suelta; el contexto real lo calcula :meth:`_resolve_steps`, que es el
        único sitio donde la precedencia de D-FX-1 se resuelve.
        """
        sub_cfg = getattr(self.config, name, None)
        if sub_cfg is None:
            raise ConfigError(
                f"Los pasos ['{name}'] no son secciones de dominio activas: la orquestación de "
                "dominios exige una sección de config no nula y registrada."
            )
        self._ensure_domain_registered(name)
        sub_cfg = self._coerce_domain_config(name, sub_cfg)

        from nikodym.core.registry import REGISTRY
        from nikodym.core.steps import Step, StepAdapter

        component_type = _component_type(sub_cfg)
        component_cls = REGISTRY.resolve(name, component_type)
        contextual = getattr(component_cls, "from_config_with_context", None)
        factory = getattr(component_cls, "from_config", None)
        if contexto is not None and callable(contextual):
            try:
                component = contextual(sub_cfg, contexto=contexto)
            except TypeError as exc:
                # El hook es un punto de extensión declarado (`core/steps.py`), así que su firma la
                # escribe un dominio y puede estar mal. Un `TypeError` crudo de Python escaparía en
                # inglés hasta el aviso del formulario, que es copy público; se traduce nombrando el
                # dominio y la firma esperada, que es lo que permite arreglarlo.
                raise ConfigError(
                    f"El componente '{component_type}' del dominio '{name}' expone "
                    "from_config_with_context() con una firma incompatible: se espera "
                    f"from_config_with_context(config, *, contexto). Detalle: {exc}"
                ) from exc
        elif callable(factory):
            component = factory(sub_cfg)
        else:
            raise ConfigError(
                f"El componente '{component_type}' del dominio '{name}' no expone from_config()."
            )
        if isinstance(component, Step):
            return component
        if isinstance(component, BaseNikodymEstimator):
            return StepAdapter(name, component)
        raise ConfigError(
            f"El componente '{component_type}' del dominio '{name}' no implementa Step ni es un "
            "BaseNikodymEstimator adaptable."
        )

    def _ensure_domain_registered(self, name: str) -> None:
        """Importa perezosamente dominios con auto-registro, sin contaminar el import de core."""
        module_name = _DOMAIN_MODULES.get(name)
        if module_name is not None:
            importlib.import_module(module_name)

    def _coerce_domain_config(self, name: str, sub_cfg: Any) -> Any:
        """Coacciona configs opacos si la sección se creó antes de importar su dominio."""
        config_spec = _DOMAIN_CONFIG_CLASSES.get(name)
        if config_spec is None:
            return sub_cfg

        module_name, class_name = config_spec
        config_cls = getattr(importlib.import_module(module_name), class_name)
        if not isinstance(sub_cfg, config_cls):
            sub_cfg = config_cls.model_validate(sub_cfg)
            self.config = self.config.model_copy(update={name: sub_cfg})
        return sub_cfg

    def _validate_pipeline(self, pasos: list[Step]) -> None:
        """Validación pre-run global (CT-1): cada ``requires`` debe tener proveedor aguas arriba.

        Un ``requires`` que ningún paso anterior ``provides`` (ni está ya en el ``ArtifactStore``)
        hace el config inejecutable → :class:`~nikodym.core.exceptions.ConfigError`.
        """
        disponibles: set[ArtifactKey] = set(self.artifacts.keys())
        for paso in pasos:
            for dominio, clave in paso.requires:
                if (dominio, clave) not in disponibles:
                    # La clave se redacta, no se interpola cruda: este mensaje viaja al aviso del
                    # formulario, que es copy público, y ahí `('survival', 'term_structure')` es el
                    # `repr` de una tupla de Python. El hermano `_check_prerequisites` ya lo hacía
                    # así; tenerlos formateados distinto era la incoherencia, no una decisión.
                    raise ConfigError(
                        f"El paso '{paso.name}' necesita '{clave}', que produce '{dominio}', "
                        f"y ningún paso anterior lo genera: active '{dominio}' antes de "
                        f"'{paso.name}' o quite este paso."
                    )
            disponibles.update(paso.provides)

    def _validate_injected_artifacts(
        self,
        pasos: list[Step],
        *,
        emit_warnings: bool,
    ) -> None:
        """Valida dominio/colisiones y declara las claves externas inertes (D-ART-4/5)."""
        if not self._injected_artifacts:
            self._inert_injected_artifacts = ()
            return

        invalid_domains = sorted(
            {domain for domain, _key in self._injected_artifacts if domain not in _DOMAIN_MODULES}
        )
        if invalid_domains:
            valid_domains = ", ".join(sorted(_DOMAIN_MODULES))
            raise ConfigError(
                "Dominio(s) de artefacto inyectado desconocido(s): "
                f"{', '.join(invalid_domains)}. Dominios válidos: {valid_domains}."
            )

        providers: dict[ArtifactKey, str] = {}
        required: set[ArtifactKey] = set()
        self._resolved_step_names = frozenset(paso.name for paso in pasos)
        for paso in pasos:
            required.update(paso.requires)
            required.update(getattr(paso, "optional_requires", ()))
            for artifact_key in paso.provides:
                providers.setdefault(artifact_key, paso.name)

        # No lo consume un Step: lo adopta el cierre transversal del lineage (D-ART-8).
        required.add(("data", "data_hash"))

        collisions = sorted(self._injected_artifacts & providers.keys())
        if collisions:
            artifact_key = collisions[0]
            domain, key = artifact_key
            producer = providers[artifact_key]
            raise ConfigError(
                f"El artefacto inyectado ('{domain}', '{key}') colisiona con la salida del paso "
                f"activo '{producer}': apague la sección '{producer}' para usar el valor externo."
            )

        inert = tuple(sorted(self._injected_artifacts - required))
        self._inert_injected_artifacts = inert
        if emit_warnings:
            for domain, key in inert:
                self._emit(
                    "decision",
                    domain,
                    {
                        "regla": "artefacto_inyectado_inerte",
                        "umbral": "requerido por un paso activo",
                        "valor": key,
                        "accion": "advertir",
                    },
                )

    def _check_prerequisites(self, paso: Step) -> None:
        """Validación por paso (CT-1): cada ``requires`` presente antes de ejecutar el paso."""
        for dominio, clave in paso.requires:
            if not self.artifacts.has(dominio, clave):
                raise ArtifactNotFoundError(
                    f"El paso '{paso.name}' requiere el artefacto ('{dominio}', '{clave}'), "
                    "ausente del ArtifactStore."
                )

    def _run_one(self, paso: Step) -> Any:
        """Valida prerequisitos, deriva el ``rng`` por nombre, inyecta el sink y ejecuta el paso."""
        self._check_prerequisites(paso)
        rng = self.seed_manager.generator_for(paso.name)
        if isinstance(paso, AuditableMixin):
            paso._audit = self._audit
        # TODO(T2): un StepAdapter no es AuditableMixin; al materializar StepAdapter.execute debe
        # propagar self._audit al estimador envuelto (paso.estimator), o sus log_decision caerían al
        # NullAuditSink de clase y se perderían del trail (SDD-01 §7.3.c).
        return paso.execute(self, rng)

    def _emit(self, kind: AuditKind, step: str | None, payload: dict[str, Any]) -> None:
        """Construye y emite un :class:`AuditEvent` por el sink interno (siempre seguro)."""
        self._audit.emit(AuditEvent(kind=kind, step=step, payload=payload, ts=datetime.now(UTC)))

    def _build_lineage(self) -> LineageBundle:
        """Ensambla el :class:`LineageBundle` de la corrida (git, config_hash, versiones, seed)."""
        git_sha, git_dirty = _estado_git()
        caveats: list[str] = []
        if git_dirty:
            # Working tree sucio: los cambios sin commitear no son reconstruibles desde git_sha,
            # así que la corrida NO es reproducible-garantizada (SDD-01 §8/§9). Se registra para que
            # el model card (SDD-03) y el inventario (SDD-04) no la lean como reproducible.
            caveats.append("working tree git sucio: cambios sin commitear no reconstruibles")
        if git_sha is None:
            caveats.append("git no disponible: la corrida no tiene SHA de origen")
        injected_artifacts = tuple(
            f"{domain}.{key}" for domain, key in sorted(self._injected_artifacts)
        )
        if injected_artifacts:
            caveats.append(
                "artefactos inyectados desde fuera de la corrida: "
                f"{len(injected_artifacts)} clave(s) no reconstruibles desde config+datos"
            )
        stored_data_hash = (
            self.artifacts.get("data", "data_hash")
            if self.artifacts.has("data", "data_hash")
            else None
        )
        if (
            injected_artifacts
            and "data" not in self._resolved_step_names
            and stored_data_hash is None
        ):
            caveats.append("data_hash ausente: la corrida no ejecutó el paso de datos")
        from nikodym.core.build import build_uv_lock_hash, runtime_environment_hash

        return LineageBundle(
            git_sha=git_sha,
            git_dirty=git_dirty,
            data_hash=stored_data_hash,
            config_hash=config_hash(self.config),
            root_seed=self.config.repro.seed,
            uv_lock_hash=build_uv_lock_hash(),
            runtime_environment_hash=runtime_environment_hash(),
            library_versions=_versiones_librerias(),
            determinism_caveats=caveats,
            created_at=datetime.now(UTC),
            schema_version=self.config.schema_version,
            injected_artifacts=injected_artifacts,
        )

    # --- Persistencia (directorio atómico; el azar NO se serializa) ----------------------------

    def save(self, path: str | Path) -> Path:
        """Serializa el ``Study`` a un directorio de forma atómica (escribe-a-temporal-y-renombra).

        Layout: ``config.yaml`` + ``run_metadata.json`` + ``lineage.json`` (si hay lineage) +
        ``artifacts/<domain>/<key>.joblib``. Al **sobrescribir**, el directorio previo se aparta a
        un respaldo lateral antes de colocar el nuevo y se restaura si el *swap* falla. En el
        doble-fallo (falla el *swap* y también la restauración), el estudio previo queda preservado
        en el respaldo lateral ``.old.*`` y ``path`` podría quedar transitoriamente sin directorio
        válido; se prioriza no perder datos. El azar (``seed_manager``) no se guarda: se reconstruye
        en :meth:`load`. Devuelve el ``Path`` del directorio final.
        """
        import joblib

        destino = Path(path)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{destino.name}.", suffix=".tmp", dir=destino.parent))
        respaldo: Path | None = None
        try:
            (tmp / "config.yaml").write_text(dump_config(self.config), encoding="utf-8")
            (tmp / "run_metadata.json").write_text(
                json.dumps(self.run_context.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if self.run_context.lineage is not None:
                (tmp / "lineage.json").write_text(
                    json.dumps(
                        self.run_context.lineage.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            artefactos = tmp / "artifacts"
            artefactos.mkdir()
            for dominio, clave in self.artifacts.keys():  # noqa: SIM118 (método del ArtifactStore, no dict)
                carpeta = artefactos / dominio
                carpeta.mkdir(parents=True, exist_ok=True)
                joblib.dump(self.artifacts.get(dominio, clave), carpeta / f"{clave}.joblib")
            if destino.exists():
                respaldo = _missing_backup_path(destino)
                _replace_path(destino, respaldo)
            try:
                _replace_path(tmp, destino)
            except BaseException:
                if respaldo is not None:
                    _replace_path(respaldo, destino)  # restaurar el estudio previo intacto
                    respaldo = None
                raise
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        if respaldo is not None:
            shutil.rmtree(respaldo, ignore_errors=True)
        return destino

    @classmethod
    def load(cls, path: str | Path, *, trust: bool = False) -> Study:
        """Recarga un ``Study`` desde un directorio; reconstruye el azar y verifica el config_hash.

        ``trust=False`` (default) rechaza un ``Study`` con artefactos *pickle* (vector de ejecución
        de código). Un ``config_hash`` que no coincide con el del lineage levanta
        :class:`~nikodym.core.exceptions.ReproducibilityError`; una divergencia de versiones de
        librerías sólo advierte. El ``SeedManager`` se reconstruye desde ``config.repro.seed``.

        Nota: el chequeo de ``config_hash`` detecta **divergencia accidental** entre ``config.yaml``
        y el lineage, no manipulación maliciosa (el hash de referencia vive en el mismo directorio
        editable). La integridad fuerte recae en ``trust=True`` + control del origen del directorio.
        """
        import joblib

        origen = Path(path)
        artefactos = origen / "artifacts"
        joblibs = sorted(artefactos.rglob("*.joblib")) if artefactos.exists() else []
        if joblibs and not trust:
            raise UntrustedStudyError(
                f"Carga de '{path}' rechazada: deserializar sus artefactos joblib/pickle ejecuta "
                "código arbitrario. Pase trust=True sólo si el origen es de confianza."
            )

        config = load_config(origen / "config.yaml")
        estudio = cls(config)

        metadatos = json.loads((origen / "run_metadata.json").read_text(encoding="utf-8"))
        run_context = RunContext.model_validate(metadatos)
        if run_context.lineage is not None:
            if config_hash(config) != run_context.lineage.config_hash:
                raise ReproducibilityError(
                    f"El config_hash recargado no coincide con el guardado en '{path}': "
                    "config.yaml diverge del lineage de la corrida."
                )
            _advertir_drift_versiones(run_context.lineage.library_versions)
        estudio.run_context = run_context

        for archivo in joblibs:
            estudio.artifacts.set(archivo.parent.name, archivo.stem, joblib.load(archivo))
        return estudio
