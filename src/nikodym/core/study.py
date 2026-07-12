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
from nikodym.core.lineage import LineageBundle, RunContext
from nikodym.core.mixins import AuditableMixin
from nikodym.core.seeding import SeedManager

if TYPE_CHECKING:
    from nikodym.core.steps import ArtifactKey, Step

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
    "report",
    "provisioning_ifrs9",
    "provisioning_cmf",
    "provisioning",
    "validation",
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

    def __init__(self, config: NikodymConfig, *, name: str | None = None) -> None:
        if name is not None:
            # El config es frozen: un override de nombre construye un config nuevo (name es INFRA,
            # no entra al config_hash, así que no altera la identidad de la corrida).
            config = config.model_copy(update={"name": name})
        self.config = config
        self.seed_manager = SeedManager(config.repro.seed)
        self.seed_manager.apply_global()
        self._audit: AuditSink = NullAuditSink()
        self.artifacts = ArtifactStore(audit=self._audit)
        self.results: dict[str, Any] = {}
        self.run_context = RunContext()

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

    # --- Orquestación (motor v1: orden de declaración + validación de prerequisitos, CT-1) -----

    def run(self, steps: list[str] | None = None) -> Study:
        """Ejecuta el pipeline y devuelve ``self`` (encadenable).

        El argumento ``steps`` tiene prioridad sobre ``config.run.steps``. ``fail_fast=False`` no se
        soporta en v1: se emite un *warning* ruidoso (no un no-op silencioso) y se procede como
        ``True``. Una excepción en un paso (con ``fail_fast=True``) deja ``status="failed"`` pero
        **conserva el lineage** (evidencia de trazabilidad, SR 11-7), emite ``run_end`` con el error
        y se re-levanta; el ``Study`` parcial sigue siendo guardable.
        """
        nombres = steps if steps is not None else self.config.run.steps
        if not self.config.run.fail_fast:
            warnings.warn(
                "fail_fast=False no está soportado en v1: se fuerza True (reservado para v2).",
                stacklevel=2,
            )
        pasos = self._resolve_steps(nombres)
        self._validate_pipeline(pasos)

        run_id = uuid.uuid4().hex
        self.run_context.run_id = run_id
        self.run_context.started_at = datetime.now(UTC)
        self.run_context.status = "running"
        # Secuencia del SDD-01 §7.3 paso 2: status="running" → emitir run_start → iniciar el
        # LineageBundle. El bundle se cuelga del run_context ANTES del bucle de pasos, de modo que
        # invariante post-run (§6) se cumple también si la corrida falla: la evidencia (config_hash,
        # git_sha, versiones) no se pierde justo en el caso que más interesa auditar. En F0
        # ``data_hash`` queda None; en B2+ lo completa el paso de datos antes de cerrar.
        self._emit("run_start", None, {"run_id": run_id, "name": self.config.name})
        self.run_context.lineage = self._build_lineage()
        try:
            for paso in pasos:
                self._run_one(paso)
        except Exception as exc:
            self.run_context.status = "failed"
            self._emit("run_end", None, {"run_id": run_id, "status": "failed", "error": str(exc)})
            raise
        self.run_context.finished_at = datetime.now(UTC)
        self.run_context.status = "done"
        self._emit("run_end", None, {"run_id": run_id, "status": "done"})
        return self

    def run_step(self, name: str) -> Any:
        """Ejecuta un paso aislado y devuelve su resultado; no altera ``run_context.status``.

        Emite sólo los eventos del paso (no ``run_start``/``run_end``) y exige sus prerequisitos
        presentes. En F0 ``NikodymConfig`` no expone secciones de dominio, así que la resolución
        levanta ``ConfigError`` (la orquestación de dominios llega en T2).
        """
        pasos = self._resolve_steps([name])
        return self._run_one(pasos[0])

    def _resolve_steps(self, nombres: list[str] | None) -> list[Step]:
        """Resuelve los nombres de paso a objetos :class:`Step` (config → REGISTRY → StepAdapter).

        Los dominios orquestables se registran al importar su paquete. El import es perezoso para
        que ``import nikodym.core`` no arrastre pandas/pandera/pyarrow ni dominios aguas abajo. El
        pipeline por defecto sigue siendo vacío si no hay secciones activas.
        """
        if nombres is None:
            nombres = self._default_step_names()
        return [self._resolve_step(nombre) for nombre in nombres]

    def _default_step_names(self) -> list[str]:
        """Deriva el pipeline v1 desde secciones activas del config raíz."""
        return [
            domain
            for domain in _DEFAULT_DOMAIN_ORDER
            if getattr(self.config, domain, None) is not None
        ]

    def _resolve_step(self, name: str) -> Step:
        """Resuelve un paso por nombre de sección usando el ``REGISTRY`` global."""
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
        factory = getattr(component_cls, "from_config", None)
        if not callable(factory):
            raise ConfigError(
                f"El componente '{component_type}' del dominio '{name}' no expone from_config()."
            )
        component = factory(sub_cfg)
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
            for clave in paso.requires:
                if clave not in disponibles:
                    raise ConfigError(
                        f"El paso '{paso.name}' requiere {clave}, que ningún paso aguas arriba "
                        "produce: config inejecutable."
                    )
            disponibles.update(paso.provides)

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
        return LineageBundle(
            git_sha=git_sha,
            git_dirty=git_dirty,
            data_hash=None,  # F0: sin paso de datos; lo completa el step de datos en B2+
            config_hash=config_hash(self.config),
            root_seed=self.config.repro.seed,
            uv_lock_hash=None,  # F0: la localización robusta del uv.lock se difiere
            library_versions=_versiones_librerias(),
            determinism_caveats=caveats,
            created_at=datetime.now(UTC),
            schema_version=self.config.schema_version,
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
