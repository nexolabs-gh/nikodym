"""Paso orquestable de la capa ``provisioning_internal`` (SDD-28 §4.1/§9; CT-1).

``InternalProvisioningStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``provisioning_internal``: lee el ``data.frame`` validado y la PD por operación de la fuente
declarada, delega el cálculo del método interno del B-1 a :class:`InternalProvisioningEngine` y
publica detalle, grupos homogéneos, resumen, resultado y card bajo el dominio
``provisioning_internal``.

**``requires`` dinámicos (CT-1, patrón SDD-16 §4).** ``from_config`` arma las dependencias: siempre
``('data', 'frame')``; más ``('calibration', 'calibrated_pd_frame')`` cuando
``pd_source='calibration'`` (el default: el B-1 pide una PD *basada en análisis histórico
fundamentado*, esto es, calibrada) o ``('model', 'raw_pd_frame')`` con ``pd_source='model'``.

El módulo evita importar ``pandas`` y el motor en import time. ``nikodym.provisioning.internal`` lo
importa para ejecutar ``@register("standard", domain="provisioning_internal")`` sin contaminar el
núcleo liviano; las dependencias tabulares se cargan dentro de ``execute``.

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
from nikodym.provisioning.internal.config import InternalProvisioningConfig
from nikodym.provisioning.internal.exceptions import InternalConfigError, InternalInputError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.provisioning.internal.results import InternalProvisionResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    DataFrame: TypeAlias = Any
    InternalProvisionResult: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["INTERNAL_PROVISIONING_ARTIFACTS", "InternalProvisioningStep"]

INTERNAL_PROVISIONING_ARTIFACTS: Final[tuple[str, ...]] = (
    "detail",
    "groups",
    "summary",
    "result",
    "card",
)
_PD_ARTIFACT_BY_SOURCE: Final[dict[str, tuple[str, str]]] = {
    "calibration": ("calibration", "calibrated_pd_frame"),
    "model": ("model", "raw_pd_frame"),
}
_INTERNAL_EXTRA_MESSAGE: Final = (
    "InternalProvisioningStep requiere pandas; instale las dependencias base."
)


@register("standard", domain="provisioning_internal")
class InternalProvisioningStep(AuditableMixin):
    """Orquesta el método interno del B-1 y publica ``domain='provisioning_internal'``."""

    name: str = "provisioning_internal"
    requires: tuple[ArtifactKey, ...] = (("data", "frame"),)
    provides: tuple[ArtifactKey, ...] = tuple(
        ("provisioning_internal", key) for key in INTERNAL_PROVISIONING_ARTIFACTS
    )

    def __init__(self, config: InternalProvisioningConfig) -> None:
        """Construye el paso desde ``InternalProvisioningConfig`` y arma sus ``requires``."""
        self.config = config
        self.requires = _requires_for(config)

    @classmethod
    def from_config(cls, cfg: InternalProvisioningConfig) -> InternalProvisioningStep:
        """Construye ``InternalProvisioningStep`` desde ``NikodymConfig.provisioning_internal``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` al motor interno."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> InternalProvisionResult:
        """Ejecuta el método interno determinista sin consumir ``rng`` y publica artefactos."""
        del rng  # El método interno es determinista (SDD-28 §9): no se consume azar.
        pandas = _import_pandas()

        cfg = _internal_config_from_study(study, fallback=self.config)
        frame = _as_dataframe(
            _require_artifact(study, "data", "frame"),
            pandas,
            "data.frame",
        ).copy(deep=True)
        as_of_date = _as_of_date_from_frame(frame, cfg)
        pd_domain, pd_key = _PD_ARTIFACT_BY_SOURCE[cfg.pd_source]
        pd_frame = _as_pd_source_dataframe(
            _require_artifact(study, pd_domain, pd_key),
            pandas,
            f"{pd_domain}.{pd_key}",
            pd_source=cfg.pd_source,
        ).copy(deep=True)

        from nikodym.provisioning.internal.engine import InternalProvisioningEngine

        engine = InternalProvisioningEngine.from_config(cfg)
        result = engine.calculate(
            frame,
            pd_frame=pd_frame,
            as_of_date=as_of_date,
            audit=self,
        )
        self._log_internal_decisions(config=cfg, result=result, pd_artifact=(pd_domain, pd_key))
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: InternalProvisionResult) -> None:
        """Publica los cinco artefactos estables del dominio ``provisioning_internal``."""
        study.artifacts.set("provisioning_internal", "detail", result.detail.copy(deep=True))
        study.artifacts.set("provisioning_internal", "groups", result.groups.copy(deep=True))
        study.artifacts.set("provisioning_internal", "summary", result.summary.copy(deep=True))
        study.artifacts.set("provisioning_internal", "result", result.model_copy(deep=True))
        study.artifacts.set("provisioning_internal", "card", result.card.model_copy(deep=True))

    def _log_internal_decisions(
        self,
        *,
        config: InternalProvisioningConfig,
        result: InternalProvisionResult,
        pd_artifact: tuple[str, str],
    ) -> None:
        """Registra las decisiones auditables exigidas por SDD-28 §9."""
        card = result.card
        self.log_decision(
            regla="internal_pd_source",
            umbral=config.pd_source,
            valor={"artefacto": list(pd_artifact), "pd_column": config.pd_column},
            accion="leer_pd_por_operacion",
        )
        self.log_decision(
            regla="internal_grouping",
            umbral={
                "grouping": config.grouping,
                "n_score_bands": config.n_score_bands,
                "group_col": config.group_col,
            },
            valor={
                "n_groups": card.n_groups,
                "n_rows": card.n_rows,
                "groups_by_portfolio": card.metric_sections["provisioning_internal"][
                    "groups_by_portfolio"
                ],
            },
            accion="formar_grupos_homogeneos",
        )
        self.log_decision(
            regla="internal_lgd",
            umbral={
                "method": config.lgd.method,
                "lgd_floor": config.lgd.lgd_floor,
                "lgd_cap": config.lgd.lgd_cap,
            },
            valor={"lgd_col": config.lgd.lgd_col, "aplicada": config.method == "pd_lgd"},
            accion="resolver_lgd_del_grupo",
        )
        self.log_decision(
            regla="internal_b1_method",
            umbral=config.method,
            valor={
                "total_exposure": str(card.total_exposure),
                "total_internal_provision": str(card.total_internal_provision),
            },
            accion="calcular_provision_del_grupo",
        )
        self.log_decision(
            regla="internal_rounding_policy",
            umbral=config.rounding,
            valor={"total_internal_provision": str(card.total_internal_provision)},
            accion="aplicar_redondeo",
        )
        self.log_decision(
            regla="internal_falta_dato",
            umbral=config.fail_on_falta_dato,
            valor={
                "falta_dato": list(card.falta_dato),
                "warning_codes": list(
                    card.metric_sections["provisioning_internal"]["warning_codes"]
                ),
            },
            accion="trazar_faltantes_y_avisos",
        )


def _requires_for(config: InternalProvisioningConfig) -> tuple[ArtifactKey, ...]:
    """Arma las claves ``requires`` dinámicas según ``pd_source`` (CT-1, SDD-28 §4.1)."""
    return (("data", "frame"), _PD_ARTIFACT_BY_SOURCE[config.pd_source])


def _require_artifact(study: Study, domain: str, key: str) -> object:
    """Exige un artefacto presente en el ``ArtifactStore`` o levanta ``ArtifactNotFoundError``."""
    if not study.artifacts.has(domain, key):
        raise ArtifactNotFoundError(
            f"El paso 'provisioning_internal' requiere el artefacto ('{domain}', '{key}'), "
            "ausente del ArtifactStore."
        )
    return study.artifacts.get(domain, key)


def _internal_config_from_study(
    study: Study,
    *,
    fallback: InternalProvisioningConfig,
) -> InternalProvisioningConfig:
    """Lee ``NikodymConfig.provisioning_internal``; usa el config del paso como respaldo."""
    raw_config = getattr(study.config, "provisioning_internal", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, InternalProvisioningConfig):
        return raw_config
    return InternalProvisioningConfig.model_validate(raw_config)


def _as_of_date_from_frame(frame: DataFrame, config: InternalProvisioningConfig) -> str:
    """Resuelve una fecha de cierre única desde ``config.as_of_date_col`` (SDD-28 §5.1)."""
    column = config.as_of_date_col
    if column not in frame.columns:
        raise InternalConfigError(
            "InternalProvisioningStep requiere una fecha de cierre única: "
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
        raise InternalConfigError(
            "InternalProvisioningStep requiere una fecha de cierre no nula en "
            f"as_of_date_col='{column}'."
        )
    if len(values) > 1:
        raise InternalConfigError(
            "InternalProvisioningStep requiere una sola fecha de cierre por corrida: "
            f"as_of_date_col='{column}', valores={values!r}."
        )
    return values[0]


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_INTERNAL_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, pandas: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular antes de leerlo."""
    if isinstance(value, pandas.DataFrame):
        return cast("DataFrame", value)
    raise InternalInputError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_pd_source_dataframe(
    value: object,
    pandas: Any,
    artifact: str,
    *,
    pd_source: str,
) -> DataFrame:
    """Valida el artefacto de PD con un error de configuración que nombra la fuente declarada."""
    if isinstance(value, pandas.DataFrame):
        return cast("DataFrame", value)
    raise InternalConfigError(
        f"pd_source='{pd_source}' exige un artefacto de PD pandas.DataFrame: "
        f"artefacto='{artifact}', tipo observado={type(value).__name__}."
    )
