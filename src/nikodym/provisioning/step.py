"""Paso orquestable de la capa ``provisioning`` (SDD-17 §2/§4/§7/§9; CT-1).

``ProvisioningStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``provisioning``: la **capa fina** que consume el ``result`` de **dos fuentes configurables**
(``source_a`` y ``source_b``: ``provisioning_cmf`` — método estándar del B-1 —,
``provisioning_internal`` — método interno, SDD-28 — o ``provisioning_ifrs9`` — ECL —), delega en
:class:`ProvisioningOrchestrator` la aplicación de la regla declarada (``rule='max'`` /
``rule='use_internal'``) por celda y publica el comparativo auditable bajo el dominio
``provisioning`` (``comparison``/``summary``/``result``/``card``). **No** recalcula PI/PDI/PE, ECL
ni el método interno: solo orquesta los dos resultados ya calculados.

**``requires`` dinámicos (CT-1, patrón SDD-16 §4).** ``from_config`` construye la lista de
dependencias **a partir de las fuentes declaradas**: con ``require_both=True`` exige el ``result``
de ambas; con ``require_both=False`` degrada a *passthrough* de la disponible y solo exige la fuente
única cuando la otra está desactivada por ``consume_*`` (el caso "al menos una de dos" no se expresa
como conjunción CT-1 y lo resuelve el orquestador en *runtime*). Un artefacto requerido ausente
levanta :class:`~nikodym.core.exceptions.ArtifactNotFoundError` antes de orquestar.

El módulo **no** importa ``pandas`` (ni en ``TYPE_CHECKING`` para runtime): el step solo mueve
artefactos opacos entre el ``ArtifactStore`` y el orquestador, que resuelve ``pandas`` de forma
perezosa dentro de ``compare``. Así ``import nikodym.provisioning`` registra ``@register("standard",
domain="provisioning")`` sin contaminar el núcleo liviano. El orquestador v1 es **determinista**:
``execute`` descarta el ``rng``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, TypeAlias

from nikodym.core.exceptions import ArtifactNotFoundError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.provisioning.config import ProvisioningConfig
from nikodym.provisioning.exceptions import ProvisioningInputError
from nikodym.provisioning.orchestrator import ProvisioningOrchestrator

if TYPE_CHECKING:
    import numpy as np

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.provisioning.results import ProvisionOrchestrationResult
else:
    AuditEvent: TypeAlias = Any
    ProvisionOrchestrationResult: TypeAlias = Any
    Study: TypeAlias = Any

# El ``result`` de cada fuente es un artefacto opaco del ``ArtifactStore``: el orquestador valida su
# estructura en ``compare`` (no se importan los motores aquí).
SourceResult: TypeAlias = Any

__all__ = ["PROVISIONING_ARTIFACTS", "ProvisioningStep"]

PROVISIONING_ARTIFACTS: Final[tuple[str, ...]] = ("comparison", "summary", "result", "card")

_RESULT_KEY: Final = "result"


@register("standard", domain="provisioning")
class ProvisioningStep(AuditableMixin):
    """Orquesta dos fuentes de provisión bajo la regla declarada (``domain='provisioning'``)."""

    name: str = "provisioning"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = tuple(
        ("provisioning", key) for key in PROVISIONING_ARTIFACTS
    )

    def __init__(self, config: ProvisioningConfig) -> None:
        """Construye el paso desde la sección ``ProvisioningConfig`` y arma ``requires`` (CT-1)."""
        self.config = config
        self.requires = _requires_for(config)

    @classmethod
    def from_config(cls, cfg: ProvisioningConfig) -> ProvisioningStep:
        """Construye ``ProvisioningStep`` desde ``NikodymConfig.provisioning``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` al orquestador (SDD-17 §9)."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> ProvisionOrchestrationResult:
        """Aplica la regla a las dos fuentes sin usar ``rng`` y publica cuatro artefactos."""
        del rng  # El orquestador v1 es determinista (SDD-17 §9): se descarta el azar.
        cfg = _provisioning_config_from_study(study, fallback=self.config)
        _require_present(study, _requires_for(cfg))

        result_a: SourceResult | None = _load_engine_result(
            study, cfg.source_a, consume=cfg.consume_source_a
        )
        result_b: SourceResult | None = _load_engine_result(
            study, cfg.source_b, consume=cfg.consume_source_b
        )
        as_of_date = _resolve_as_of_date(result_a, result_b)

        orchestrator = ProvisioningOrchestrator.from_config(cfg)
        result = orchestrator.compare(
            result_a=result_a, result_b=result_b, as_of_date=as_of_date, audit=self
        )
        self._log_falta_dato(config=cfg, result=result)
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: ProvisionOrchestrationResult) -> None:
        """Publica los cuatro artefactos estables del dominio ``provisioning`` (copias)."""
        study.artifacts.set("provisioning", "comparison", result.comparison)
        study.artifacts.set("provisioning", "summary", result.summary)
        study.artifacts.set("provisioning", "result", result.model_copy(deep=True))
        study.artifacts.set("provisioning", "card", result.card.model_copy(deep=True))

    def _log_falta_dato(
        self, *, config: ProvisioningConfig, result: ProvisionOrchestrationResult
    ) -> None:
        """Registra la decisión ``provisioning_falta_dato`` de SDD-17 §9.

        El orquestador emite las decisiones ``level``/``engines``/``reconciliation``/``binding``/
        ``coverage`` (``compare(audit=self)``); aquí se añade la traza explícita de brechas críticas
        de la comparación (item #6 del audit trail §9), sin duplicar las anteriores.
        """
        card = result.card
        self.log_decision(
            regla="provisioning_falta_dato",
            umbral=config.fail_on_falta_dato,
            valor={
                "falta_dato": list(card.falta_dato),
                "engines_present": list(card.engines_present),
                "coverage_policy": config.coverage_policy,
            },
            accion="trazar_brechas_comparacion",
        )


def _requires_for(config: ProvisioningConfig) -> tuple[ArtifactKey, ...]:
    """Construye las claves ``requires`` dinámicas desde las fuentes declaradas (CT-1, SDD-17 §4).

    Con ``require_both=True`` (config garantiza ambos ``consume_*``) exige los dos ``result``. Con
    ``require_both=False`` la comparación degrada a *passthrough*: solo se exige la fuente única
    cuando la otra está desactivada por ``consume_*``; con ambas fuentes habilitadas el requisito
    "al menos una" no es una conjunción CT-1 y lo valida el orquestador en *runtime*.
    """
    consume_a, consume_b = config.consume_source_a, config.consume_source_b
    if config.require_both:
        return ((config.source_a, _RESULT_KEY), (config.source_b, _RESULT_KEY))
    if consume_a and not consume_b:
        return ((config.source_a, _RESULT_KEY),)
    if consume_b and not consume_a:
        return ((config.source_b, _RESULT_KEY),)
    return ()


def _require_present(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Exige que cada artefacto ``requires`` (CT-1) esté en el ``ArtifactStore``."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'provisioning' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _load_engine_result(study: Study, domain: str, *, consume: bool) -> SourceResult | None:
    """Lee el ``result`` de una fuente si se consume y está presente; ``None`` en otro caso.

    Devuelve el artefacto opaco del ``ArtifactStore`` (``CmfProvisionResult`` /
    ``InternalProvisionResult`` / ``IfrsProvisionResult``); el orquestador valida su estructura en
    ``compare``.
    """
    if not consume:
        return None
    if not study.artifacts.has(domain, _RESULT_KEY):
        return None
    return study.artifacts.get(domain, _RESULT_KEY)


def _resolve_as_of_date(result_a: SourceResult | None, result_b: SourceResult | None) -> str:
    """Hereda la fecha de cálculo de las fuentes presentes; exige una sola fecha de cierre.

    Ambas fuentes reportan al mismo cierre contable (SDD-17 §4): si difieren, la comparación no es
    posible y se levanta :class:`ProvisioningInputError`. Si no hay fuente presente para heredarla,
    también levanta (el orquestador re-confirma "al menos un motor" en §7).
    """
    fechas = [
        str(result.card.as_of_date).strip() for result in (result_a, result_b) if result is not None
    ]
    unicas = tuple(dict.fromkeys(fecha for fecha in fechas if fecha))
    if not unicas:
        raise ProvisioningInputError(
            "La orquestación de provisiones requiere al menos un motor presente para heredar la "
            "fecha de cálculo; ninguno está disponible."
        )
    if len(unicas) > 1:
        raise ProvisioningInputError(
            "Las fuentes reportan fechas de cálculo distintas; la comparación exige una sola "
            f"fecha de cierre por corrida: {unicas!r}."
        )
    return unicas[0]


def _provisioning_config_from_study(
    study: Study, *, fallback: ProvisioningConfig
) -> ProvisioningConfig:
    """Lee ``NikodymConfig.provisioning``; usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "provisioning", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ProvisioningConfig):
        return raw_config
    return ProvisioningConfig.model_validate(raw_config)
