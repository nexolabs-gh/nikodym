"""Paso orquestable de la capa ``provisioning`` (SDD-17 §2/§4/§7/§9; CT-1).

``ProvisioningStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``provisioning``: la **capa fina** que consume el resultado del motor regulatorio CMF (SDD-15,
``('provisioning_cmf', 'result')``) y del motor contable IFRS 9/ECL (SDD-16,
``('provisioning_ifrs9', 'result')``), delega en :class:`ProvisioningOrchestrator` el
``reported = máximo(CMF, IFRS 9)`` por celda (piso prudencial, regla dura ESPEC §5.4) y publica el
comparativo auditable bajo el dominio ``provisioning`` (``comparison``/``summary``/``result``/
``card``). **No** recalcula PI/PDI/PE ni ECL: solo orquesta los dos resultados ya calculados.

**``requires`` dinámicos (CT-1, patrón SDD-16 §4).** ``from_config`` construye la lista de
dependencias según la config: con ``require_both=True`` exige **ambos** ``result``; con
``require_both=False`` degrada a *passthrough* del disponible y solo exige el motor único cuando el
otro está desactivado por ``consume_*`` (el caso "al menos uno de dos" no se expresa como conjunción
CT-1 y lo resuelve el orquestador en *runtime*). Un artefacto requerido ausente levanta
:class:`~nikodym.core.exceptions.ArtifactNotFoundError` antes de orquestar.

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
    from nikodym.provisioning.cmf.results import CmfProvisionResult
    from nikodym.provisioning.ifrs9.results import IfrsProvisionResult
    from nikodym.provisioning.results import ProvisionOrchestrationResult
else:
    AuditEvent: TypeAlias = Any
    CmfProvisionResult: TypeAlias = Any
    IfrsProvisionResult: TypeAlias = Any
    ProvisionOrchestrationResult: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["PROVISIONING_ARTIFACTS", "ProvisioningStep"]

PROVISIONING_ARTIFACTS: Final[tuple[str, ...]] = ("comparison", "summary", "result", "card")

_CMF_DOMAIN: Final = "provisioning_cmf"
_IFRS9_DOMAIN: Final = "provisioning_ifrs9"
_RESULT_KEY: Final = "result"


@register("standard", domain="provisioning")
class ProvisioningStep(AuditableMixin):
    """Orquesta el piso prudencial CMF vs IFRS 9 y publica ``domain='provisioning'``."""

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
        """Orquesta el máximo CMF vs IFRS 9 sin consumir ``rng`` y publica cuatro artefactos."""
        del rng  # El orquestador v1 es determinista (SDD-17 §9): se descarta el azar.
        cfg = _provisioning_config_from_study(study, fallback=self.config)
        _require_present(study, _requires_for(cfg))

        cmf: CmfProvisionResult | None = _load_engine_result(
            study, _CMF_DOMAIN, consume=cfg.consume_cmf
        )
        ifrs9: IfrsProvisionResult | None = _load_engine_result(
            study, _IFRS9_DOMAIN, consume=cfg.consume_ifrs9
        )
        as_of_date = _resolve_as_of_date(cmf, ifrs9)

        orchestrator = ProvisioningOrchestrator.from_config(cfg)
        result = orchestrator.compare(cmf=cmf, ifrs9=ifrs9, as_of_date=as_of_date, audit=self)
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
        del piso (item #6 del audit trail §9), sin duplicar las anteriores.
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
            accion="trazar_brechas_piso_prudencial",
        )


def _requires_for(config: ProvisioningConfig) -> tuple[ArtifactKey, ...]:
    """Construye las claves ``requires`` dinámicas según la config (CT-1, SDD-17 §4).

    Con ``require_both=True`` (config garantiza ambos ``consume_*``) exige los dos ``result``. Con
    ``require_both=False`` el piso degrada a *passthrough*: solo se exige el motor único cuando el
    otro está desactivado por ``consume_*``; con ambos motores habilitados el requisito "al menos
    uno" no es una conjunción CT-1 y lo valida el orquestador en *runtime*.
    """
    if config.require_both:
        return ((_CMF_DOMAIN, _RESULT_KEY), (_IFRS9_DOMAIN, _RESULT_KEY))
    if config.consume_cmf and not config.consume_ifrs9:
        return ((_CMF_DOMAIN, _RESULT_KEY),)
    if config.consume_ifrs9 and not config.consume_cmf:
        return ((_IFRS9_DOMAIN, _RESULT_KEY),)
    return ()


def _require_present(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Exige que cada artefacto ``requires`` (CT-1) esté en el ``ArtifactStore``."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'provisioning' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _load_engine_result(study: Study, domain: str, *, consume: bool) -> Any:
    """Lee el ``result`` de un motor si se consume y está presente; ``None`` en otro caso.

    Devuelve el artefacto opaco del ``ArtifactStore`` (``CmfProvisionResult`` /
    ``IfrsProvisionResult``); el orquestador valida su estructura en ``compare``.
    """
    if not consume:
        return None
    if not study.artifacts.has(domain, _RESULT_KEY):
        return None
    return study.artifacts.get(domain, _RESULT_KEY)


def _resolve_as_of_date(cmf: CmfProvisionResult | None, ifrs9: IfrsProvisionResult | None) -> str:
    """Hereda la fecha de cálculo de los motores presentes; exige una sola fecha de cierre.

    Ambos motores reportan al mismo cierre contable (SDD-17 §4): si difieren, el piso prudencial no
    puede comparar y se levanta :class:`ProvisioningInputError`. Si no hay motor presente para
    heredarla, también levanta (el orquestador re-confirma "al menos un motor" en §7).
    """
    fechas: list[str] = []
    if cmf is not None:
        fechas.append(str(cmf.card.as_of_date).strip())
    if ifrs9 is not None:
        fechas.append(str(ifrs9.card.as_of_date).strip())
    unicas = tuple(dict.fromkeys(fecha for fecha in fechas if fecha))
    if not unicas:
        raise ProvisioningInputError(
            "La orquestación de provisiones requiere al menos un motor (CMF o IFRS 9) presente "
            "para heredar la fecha de cálculo; ninguno está disponible."
        )
    if len(unicas) > 1:
        raise ProvisioningInputError(
            "CMF e IFRS 9 reportan fechas de cálculo distintas; el piso prudencial exige una sola "
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
