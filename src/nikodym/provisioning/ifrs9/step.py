"""Paso orquestable de la capa ``provisioning_ifrs9`` (SDD-16 §4/§7/§9; CT-1).

``IfrsProvisioningStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``provisioning_ifrs9``: lee el ``data.frame`` económico y la term-structure lifetime del proveedor
configurado (survival/markov/forward), activa la dependencia condicional de PD calibrada sólo cuando
``pd.base_pd_source='calibration'``, delega el cálculo a :class:`IfrsProvisioningEngine` y publica
staging, detalle, term-structure de ECL, resumen, resultado y card bajo el dominio
``provisioning_ifrs9``.

**``requires`` dinámicos (CT-1, patrón SDD-20 §81).** ``from_config`` construye la lista de
dependencias: siempre ``('data', 'frame')``; ``('calibration', 'calibrated_pd_frame')`` si
``base_pd_source='calibration'``; y ``(<term_structure_source>, 'term_structure')`` con la fuente en
``{survival, markov, forward}``. Un artefacto requerido ausente levanta
:class:`~nikodym.core.exceptions.ArtifactNotFoundError` antes de calcular.

El módulo evita importar ``pandas``, el motor y sus dependencias numéricas en import time.
``nikodym.provisioning.ifrs9`` lo importa para ejecutar ``@register("standard",
domain="provisioning_ifrs9")`` sin contaminar el núcleo liviano; las dependencias tabulares se
cargan dentro de ``execute``.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.audit import AuditEvent
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.provisioning.ifrs9.config import IfrsProvisioningConfig
from nikodym.provisioning.ifrs9.exceptions import IfrsConfigError, IfrsInputError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.provisioning.ifrs9.results import IfrsProvisionResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    DataFrame: TypeAlias = Any
    IfrsProvisionResult: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["IFRS9_PROVISIONING_ARTIFACTS", "IfrsProvisioningStep"]

IFRS9_PROVISIONING_ARTIFACTS: Final[tuple[str, ...]] = (
    "staging",
    "detail",
    "ecl_term_structure",
    "summary",
    "result",
    "card",
)
_CALIBRATION_SOURCE: Final = "calibration"
_IFRS9_EXTRA_MESSAGE: Final = "IfrsProvisioningStep requiere pandas; instale nikodym[scoring]."


@register("standard", domain="provisioning_ifrs9")
class IfrsProvisioningStep(AuditableMixin):
    """Orquesta provisiones IFRS 9/ECL y publica ``domain='provisioning_ifrs9'``."""

    name: str = "provisioning_ifrs9"
    requires: tuple[ArtifactKey, ...] = (("data", "frame"),)
    provides: tuple[ArtifactKey, ...] = tuple(
        ("provisioning_ifrs9", key) for key in IFRS9_PROVISIONING_ARTIFACTS
    )

    def __init__(self, config: IfrsProvisioningConfig) -> None:
        """Construye el paso desde la sección ``IfrsProvisioningConfig`` y arma ``requires``."""
        self.config = config
        self.requires = _requires_for(config)

    @classmethod
    def from_config(cls, cfg: IfrsProvisioningConfig) -> IfrsProvisioningStep:
        """Construye ``IfrsProvisioningStep`` desde ``NikodymConfig.provisioning_ifrs9``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` al motor IFRS 9."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> IfrsProvisionResult:
        """Ejecuta provisiones IFRS 9 deterministas sin consumir ``rng`` y publica artefactos."""
        del rng  # El motor IFRS 9 v1 es determinista (SDD-16 §9): se descarta el azar.
        pd = _import_pandas()

        cfg = _ifrs_config_from_study(study, fallback=self.config)
        frame = _as_dataframe(
            _require_artifact(study, "data", "frame"),
            pd,
            "data.frame",
        ).copy(deep=True)
        as_of_date = _as_of_date_from_frame(frame, cfg)
        term_structure = _as_dataframe(
            _require_artifact(study, cfg.pd.term_structure_source, "term_structure"),
            pd,
            f"{cfg.pd.term_structure_source}.term_structure",
        ).copy(deep=True)
        calibrated_pd = _calibrated_pd_if_required(study, config=cfg, pd=pd)

        from nikodym.provisioning.ifrs9.engine import IfrsProvisioningEngine

        engine = IfrsProvisioningEngine.from_config(cfg)
        result = engine.calculate(
            frame,
            term_structure=term_structure,
            calibrated_pd=None if calibrated_pd is None else calibrated_pd.copy(deep=True),
            as_of_date=as_of_date,
            audit=self,
        )
        self._log_ifrs_decisions(config=cfg, result=result)
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: IfrsProvisionResult) -> None:
        """Publica los seis artefactos estables del dominio ``provisioning_ifrs9``."""
        study.artifacts.set("provisioning_ifrs9", "staging", result.staging.copy(deep=True))
        study.artifacts.set("provisioning_ifrs9", "detail", result.detail.copy(deep=True))
        study.artifacts.set(
            "provisioning_ifrs9",
            "ecl_term_structure",
            result.ecl_term_structure.copy(deep=True),
        )
        study.artifacts.set("provisioning_ifrs9", "summary", result.summary.copy(deep=True))
        study.artifacts.set("provisioning_ifrs9", "result", result.model_copy(deep=True))
        study.artifacts.set("provisioning_ifrs9", "card", result.card.model_copy(deep=True))

    def _log_ifrs_decisions(
        self, *, config: IfrsProvisioningConfig, result: IfrsProvisionResult
    ) -> None:
        """Registra las decisiones auditables exigidas por SDD-16 §9."""
        card = result.card
        self.log_decision(
            regla="ifrs9_term_structure_source",
            umbral=config.pd.term_structure_source,
            valor={"base_pd_source": config.pd.base_pd_source, "n_rows": card.n_rows},
            accion="leer_term_structure_lifetime",
        )
        self.log_decision(
            regla="ifrs9_pit",
            umbral=config.pd.pit_mode,
            valor={
                "rho": config.pd.rho,
                "rho_col": config.pd.rho_col,
                "systemic_factor_col": config.pd.systemic_factor_col,
            },
            accion="resolver_pd_pit",
        )
        self.log_decision(
            regla="ifrs9_pd_horizon",
            umbral={
                "horizon_12m_periods": config.pd.horizon_12m_periods,
                "max_lifetime_periods": config.pd.max_lifetime_periods,
            },
            valor={"falta_dato": card.falta_dato},
            accion="derivar_horizontes_pd",
        )
        self.log_decision(
            regla="ifrs9_lgd",
            umbral=config.lgd.method,
            valor={
                "lgd_floor": config.lgd.lgd_floor,
                "lgd_cap": config.lgd.lgd_cap,
                # La LGD forward de la term-structure no se consume en v1 (FALTA-DATO-IFRS-6).
                "lgd_forward_presente": "FALTA-DATO-IFRS-6" in card.falta_dato,
            },
            accion="estimar_lgd",
        )
        self.log_decision(
            regla="ifrs9_ead",
            umbral=config.ead.method,
            valor={"exposure_profile_col": config.ead.exposure_profile_col},
            accion="estimar_ead",
        )
        self.log_decision(
            regla="ifrs9_staging",
            umbral={
                "sicr_pd_ratio_threshold": config.staging.sicr_pd_ratio_threshold,
                "dpd_sicr_backstop": config.staging.dpd_sicr_backstop,
                "dpd_default_backstop": config.staging.dpd_default_backstop,
            },
            valor={
                "n_stage1": card.n_stage1,
                "n_stage2": card.n_stage2,
                "n_stage3": card.n_stage3,
                "sicr_triggers": _trigger_counts(result.staging),
            },
            accion="asignar_staging",
        )
        self.log_decision(
            regla="ifrs9_scenarios",
            umbral=config.scenarios.source,
            valor={
                "scenarios": card.scenarios,
                "scenario_weights": card.scenario_weights,
                "forbid_mean_scenario": config.scenarios.forbid_mean_scenario,
            },
            accion="ponderar_escenarios",
        )
        self.log_decision(
            regla="ifrs9_ecl",
            umbral={
                "discount_convention": config.ecl.discount_convention,
                "stage3_direct": config.ecl.stage3_direct,
            },
            valor={
                "total_ead": card.total_ead,
                "total_ecl_reported": card.total_ecl_reported,
            },
            accion="calcular_ecl",
        )


def _requires_for(config: IfrsProvisioningConfig) -> tuple[ArtifactKey, ...]:
    """Construye las claves ``requires`` dinámicas del step según la config (CT-1, SDD-16 §4).

    La fuente de term-structure (``pd.term_structure_source``) es un ``Literal`` validado por config
    (``{survival, markov, forward}``), así que aquí sólo se ensambla la lista de dependencias.
    """
    requires: list[ArtifactKey] = [("data", "frame")]
    if config.pd.base_pd_source == _CALIBRATION_SOURCE:
        requires.append(("calibration", "calibrated_pd_frame"))
    requires.append((config.pd.term_structure_source, "term_structure"))
    return tuple(requires)


def _require_artifact(study: Study, domain: str, key: str) -> object:
    """Exige un artefacto presente en el ``ArtifactStore`` o levanta ``ArtifactNotFoundError``."""
    if not study.artifacts.has(domain, key):
        raise ArtifactNotFoundError(
            f"El paso 'provisioning_ifrs9' requiere el artefacto ('{domain}', '{key}'), "
            "ausente del ArtifactStore."
        )
    return study.artifacts.get(domain, key)


def _calibrated_pd_if_required(
    study: Study, *, config: IfrsProvisioningConfig, pd: Any
) -> DataFrame | None:
    """Lee la PD calibrada sólo cuando ``base_pd_source='calibration'`` la exige (CT-1)."""
    if config.pd.base_pd_source != _CALIBRATION_SOURCE:
        return None
    return _as_calibrated_dataframe(
        _require_artifact(study, "calibration", "calibrated_pd_frame"),
        pd,
        "calibration.calibrated_pd_frame",
    ).copy(deep=True)


def _ifrs_config_from_study(
    study: Study, *, fallback: IfrsProvisioningConfig
) -> IfrsProvisioningConfig:
    """Lee ``NikodymConfig.provisioning_ifrs9``; usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "provisioning_ifrs9", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, IfrsProvisioningConfig):
        return raw_config
    return IfrsProvisioningConfig.model_validate(raw_config)


def _as_of_date_from_frame(frame: DataFrame, config: IfrsProvisioningConfig) -> str:
    """Resuelve una fecha de cálculo única desde ``config.as_of_date_col`` (SDD-16 §4)."""
    column = config.as_of_date_col
    if column not in frame.columns:
        raise IfrsConfigError(
            "IfrsProvisioningStep requiere una fecha de cálculo única: "
            f"falta la columna as_of_date_col='{column}'."
        )
    values = tuple(
        dict.fromkeys(
            item
            for item in (str(raw).strip() for raw in cast(Any, frame[column].dropna().tolist()))
            if item
        )
    )
    if not values:
        raise IfrsConfigError(
            "IfrsProvisioningStep requiere una fecha de cálculo no nula en "
            f"as_of_date_col='{column}'."
        )
    if len(values) > 1:
        raise IfrsConfigError(
            "IfrsProvisioningStep requiere una sola fecha de cálculo por corrida: "
            f"as_of_date_col='{column}', valores={values!r}."
        )
    return values[0]


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_IFRS9_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast("DataFrame", value)
    raise IfrsInputError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_calibrated_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida el artefacto de PD calibrada con error de configuración del step."""
    if isinstance(value, pd.DataFrame):
        return cast("DataFrame", value)
    raise IfrsConfigError(
        "base_pd_source='calibration' exige un artefacto de PD calibrada pandas.DataFrame: "
        f"artefacto='{artifact}', tipo observado={type(value).__name__}."
    )


def _trigger_counts(staging: DataFrame) -> dict[str, int]:
    """Cuenta los gatillos SICR disparados desde ``staging.sicr_triggers`` (auditoría §9)."""
    counts: dict[str, int] = {}
    for codes in cast(Any, staging["sicr_triggers"]).tolist():
        for code in codes:
            name = str(code)
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))
