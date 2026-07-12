"""Paso orquestable de la capa ``stress`` (SDD-21 §4/§7/§9; CT-1).

``StressStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``stress``. Cierra
la cadena F5 Lifetime SDD-18/19/20/21: consume los artefactos que ``forward`` publica
(``macro_projection``, ``satellite_model``, ``term_structure``, ``scenario_weighting`` y
``ForwardEclInput``) y delega el cálculo determinista en :class:`StressTestEngine`, que aplica
escenarios severos, barridos de sensibilidad y reverse stress por bisección monotónica.

Sus dependencias son dinámicas (CT-1): siempre requiere los cinco artefactos forward y, sólo si
alguna métrica es económica, los hooks de engine ECL/provisión declarados en ``StressInputConfig``.
El paso ensambla y publica sin importar ``pandas``, ``numpy`` ni motores económicos en import time;
esas dependencias las carga el engine dentro de ``run``.

La validación avanzada y el backtesting (discriminación, calibración y estabilidad) son frontera de
SDD-22/F6 y no se implementan aquí; ``stress`` sólo mide sensibilidad de una cadena forward ya
aprobada.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final, TypeAlias

from nikodym.core.audit import AuditEvent
from nikodym.core.exceptions import ArtifactNotFoundError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.stress.config import StressConfig

if TYPE_CHECKING:
    import numpy as np

    from nikodym.core.study import Study
    from nikodym.stress.engine import EclEngineLike, ProvisionEngineLike, StressTestEngine
    from nikodym.stress.results import StressResult
else:
    Study: TypeAlias = Any
    StressResult: TypeAlias = Any
    StressTestEngine: TypeAlias = Any
    EclEngineLike: TypeAlias = Any
    ProvisionEngineLike: TypeAlias = Any

__all__ = ["STRESS_ARTIFACTS", "StressStep"]

# Las nueve claves ``provides`` bajo el dominio ``stress`` (SDD-21 §4).
STRESS_ARTIFACTS: Final[tuple[str, ...]] = (
    "engine",
    "scenarios",
    "term_structure",
    "impact",
    "sensitivity",
    "reverse",
    "diagnostics",
    "result",
    "card",
)
# Métricas cuyo cálculo exige un engine económico conectado (SDD-21 §5).
_ECONOMIC_METRICS: Final[frozenset[str]] = frozenset({"ecl", "provision", "loss", "ratio"})


@register("standard", domain="stress")
class StressStep(AuditableMixin):
    """Orquesta stress testing severo y publica ``domain='stress'``."""

    name: str = "stress"
    config_cls: ClassVar[type[StressConfig]] = StressConfig
    provides: tuple[ArtifactKey, ...] = tuple(("stress", key) for key in STRESS_ARTIFACTS)

    def __init__(self, config: StressConfig) -> None:
        """Construye el paso desde la sección ``StressConfig`` ya validada."""
        self.config = config
        self.requires = _requires_from_config(config)

    @classmethod
    def from_config(cls, cfg: StressConfig) -> StressStep:
        """Construye ``StressStep`` desde ``NikodymConfig.stress``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` sin exponer el sink interno."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> StressResult:
        """Ejecuta el stress determinista y publica las nueve claves del dominio."""
        cfg = _stress_config_from_study(study, fallback=self.config)
        self.requires = _requires_from_config(cfg)
        _validate_requires(study, self.requires)
        del rng  # v1 no usa RNG: el engine es determinista dados forward, config y engines.

        forward_inputs = _read_forward_artifacts(study, cfg=cfg)
        ecl_engine, provision_engine = _read_economic_engines(study, cfg=cfg)

        engine = _new_engine(cfg)
        result = engine.run(
            forward_ecl_input=forward_inputs["forward_ecl_input"],
            macro_projection=forward_inputs["macro_projection"],
            satellite_model=forward_inputs["satellite_model"],
            forward_term_structure=forward_inputs["forward_term_structure"],
            scenario_weighting=forward_inputs["scenario_weighting"],
            ecl_engine=ecl_engine,
            provision_engine=provision_engine,
            audit=self,
        )
        self._publish_artifacts(study, engine=engine, result=result)
        return result

    def _publish_artifacts(
        self,
        study: Study,
        *,
        engine: StressTestEngine,
        result: StressResult,
    ) -> None:
        """Publica el executor, los frames materializados y los DTOs frozen bajo ``"stress"``.

        Los DataFrames del agregado ``StressResult`` se leen por copia defensiva (vía su acceso
        atributo); los DTOs se clonan con ``model_copy(deep=True)`` para que el artefacto publicado
        no comparta estado con el resultado devuelto.
        """
        study.artifacts.set("stress", "engine", engine)
        study.artifacts.set("stress", "scenarios", result.stress_scenario_frame)
        study.artifacts.set("stress", "term_structure", result.stress_term_structure_frame)
        study.artifacts.set("stress", "impact", result.stress_impact_frame)
        study.artifacts.set("stress", "sensitivity", result.sensitivity_results)
        study.artifacts.set("stress", "reverse", result.reverse_results)
        study.artifacts.set("stress", "diagnostics", result.diagnostics.model_copy(deep=True))
        study.artifacts.set("stress", "result", result.model_copy(deep=True))
        study.artifacts.set("stress", "card", result.card.model_copy(deep=True))


def _requires_from_config(cfg: StressConfig) -> tuple[ArtifactKey, ...]:
    """Deriva las dependencias CT-1 dinámicas desde ``StressConfig`` (SDD-21 §2)."""
    domain = cfg.input.forward_domain
    requires: list[ArtifactKey] = [
        (domain, cfg.input.macro_projection_key),
        (domain, cfg.input.satellite_model_key),
        (domain, cfg.input.term_structure_key),
        (domain, cfg.input.scenario_weighting_key),
        (domain, cfg.input.ecl_input_key),
    ]
    metrics = _requested_metrics(cfg)
    if metrics & _ECONOMIC_METRICS and cfg.input.ecl_engine_artifact is not None:
        requires.append(cfg.input.ecl_engine_artifact)
    if "provision" in metrics and cfg.input.provision_engine_artifact is not None:
        requires.append(cfg.input.provision_engine_artifact)
    return tuple(dict.fromkeys(requires))


def _requested_metrics(cfg: StressConfig) -> frozenset[str]:
    """Reúne toda métrica declarada en output, sensibilidades y targets reverse habilitados."""
    metrics: set[str] = set(cfg.output.metrics)
    metrics.update(sweep.metric for sweep in cfg.sensitivities)
    for reverse in cfg.reverse:
        if reverse.enabled and reverse.target is not None:
            metrics.add(reverse.target.metric)
    return frozenset(metrics)


def _stress_config_from_study(study: Study, *, fallback: StressConfig) -> StressConfig:
    """Lee ``NikodymConfig.stress`` y usa el config del paso como respaldo (API programática)."""
    raw_config = getattr(study.config, "stress", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, StressConfig):
        return raw_config
    return StressConfig.model_validate(raw_config)


def _validate_requires(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Replica la validación CT-1 para ejecuciones directas del step (SDD-21 §8)."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'stress' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _read_forward_artifacts(study: Study, *, cfg: StressConfig) -> dict[str, Any]:
    """Lee y copia defensivamente los artefactos forward que consume el engine (SDD-21 §7)."""
    domain = cfg.input.forward_domain
    return {
        "macro_projection": study.artifacts.get(domain, cfg.input.macro_projection_key).copy(
            deep=True
        ),
        "satellite_model": study.artifacts.get(domain, cfg.input.satellite_model_key),
        "forward_term_structure": study.artifacts.get(domain, cfg.input.term_structure_key).copy(
            deep=True
        ),
        "scenario_weighting": study.artifacts.get(domain, cfg.input.scenario_weighting_key),
        "forward_ecl_input": study.artifacts.get(domain, cfg.input.ecl_input_key),
    }


def _read_economic_engines(
    study: Study,
    *,
    cfg: StressConfig,
) -> tuple[EclEngineLike | None, ProvisionEngineLike | None]:
    """Resuelve los engines económicos sólo cuando alguna métrica los requiere (SDD-21 §7)."""
    metrics = _requested_metrics(cfg)
    ecl_engine: EclEngineLike | None = None
    if metrics & _ECONOMIC_METRICS and cfg.input.ecl_engine_artifact is not None:
        ecl_engine = study.artifacts.get(*cfg.input.ecl_engine_artifact)
    provision_engine: ProvisionEngineLike | None = None
    if "provision" in metrics and cfg.input.provision_engine_artifact is not None:
        provision_engine = study.artifacts.get(*cfg.input.provision_engine_artifact)
    return ecl_engine, provision_engine


def _new_engine(cfg: StressConfig) -> StressTestEngine:
    """Instancia el engine determinista con import perezoso para preservar el núcleo liviano."""
    from nikodym.stress.engine import StressTestEngine

    return StressTestEngine.from_config(cfg)
