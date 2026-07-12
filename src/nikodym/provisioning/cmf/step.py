"""Paso orquestable de la capa ``provisioning_cmf`` (SDD-15 §4/§7/§9; CT-1).

``CmfProvisioningStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``provisioning_cmf``: lee el ``data.frame`` validado, activa dependencias condicionales de PD sólo
cuando ``pd_mapping.method='pd_breaks'``, delega el cálculo regulatorio a
``CmfProvisioningEngine`` y publica detalle, resumen, matrices, resultado y card bajo
``domain='provisioning_cmf'``.

El módulo evita importar ``pandas``, matrices y el motor en import time.
``nikodym.provisioning.cmf`` lo importa para ejecutar ``@register("standard",
domain="provisioning_cmf")`` sin contaminar el núcleo liviano; las dependencias tabulares y
normativas se cargan dentro de ``execute``.

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
from nikodym.provisioning.cmf.config import CmfProvisioningConfig
from nikodym.provisioning.cmf.exceptions import CmfConfigError, CmfInputError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.provisioning.cmf.results import CmfProvisionResult

    DataFrame: TypeAlias = pd.DataFrame
else:
    CmfProvisionResult: TypeAlias = Any
    DataFrame: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["CMF_PROVISIONING_ARTIFACTS", "CmfProvisioningStep"]

CMF_PROVISIONING_ARTIFACTS: Final[tuple[str, ...]] = (
    "detail",
    "summary",
    "matrix_bundle",
    "result",
    "card",
)
_CMF_EXTRA_MESSAGE: Final = "CmfProvisioningStep requiere pandas; instale las dependencias base."
_PD_BREAKS_METHOD: Final = "pd_breaks"
_PROVIDED_CATEGORY_METHOD: Final = "provided_cmf_category"


@register("standard", domain="provisioning_cmf")
class CmfProvisioningStep(AuditableMixin):
    """Orquesta provisiones CMF B-1/B-3 y publica ``domain='provisioning_cmf'``."""

    name: str = "provisioning_cmf"
    requires: tuple[ArtifactKey, ...] = (("data", "frame"),)
    provides: tuple[ArtifactKey, ...] = tuple(
        ("provisioning_cmf", key) for key in CMF_PROVISIONING_ARTIFACTS
    )

    def __init__(self, config: CmfProvisioningConfig) -> None:
        """Construye el paso desde la sección ``CmfProvisioningConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: CmfProvisioningConfig) -> CmfProvisioningStep:
        """Construye ``CmfProvisioningStep`` desde ``NikodymConfig.provisioning_cmf``."""
        return cls(cfg)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` al motor CMF."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> CmfProvisionResult:
        """Ejecuta provisiones CMF deterministas sin consumir ``rng`` y publica artefactos."""
        del rng
        pd = _import_pandas()

        frame = _as_dataframe(
            study.artifacts.get("data", "frame"),
            pd,
            "data.frame",
        ).copy(deep=True)
        cfg = _cmf_config_from_study(study, fallback=self.config)
        as_of_date = _as_of_date_from_frame(frame, cfg)
        pd_frame, conditional_context = _pd_frame_if_required(study, config=cfg, pd=pd)

        from nikodym.provisioning.cmf.engine import CmfProvisioningEngine

        engine = CmfProvisioningEngine.from_config(cfg)
        result = engine.calculate(
            frame.copy(deep=True),
            pd_frame=None if pd_frame is None else pd_frame.copy(deep=True),
            as_of_date=as_of_date,
            audit=self,
        )
        self._log_cmf_decisions(
            frame=frame,
            result=result,
            config=cfg,
            conditional_context=conditional_context,
        )
        self._publish_artifacts(study, result)
        return result

    def _publish_artifacts(self, study: Study, result: CmfProvisionResult) -> None:
        """Publica los cinco artefactos estables del dominio ``provisioning_cmf``."""
        study.artifacts.set("provisioning_cmf", "detail", result.detail.copy(deep=True))
        study.artifacts.set("provisioning_cmf", "summary", result.summary.copy(deep=True))
        study.artifacts.set(
            "provisioning_cmf",
            "matrix_bundle",
            result.matrix_bundle.model_copy(deep=True),
        )
        study.artifacts.set("provisioning_cmf", "result", result.model_copy(deep=True))
        study.artifacts.set("provisioning_cmf", "card", result.card.model_copy(deep=True))

    def _log_cmf_decisions(
        self,
        *,
        frame: DataFrame,
        result: CmfProvisionResult,
        config: CmfProvisioningConfig,
        conditional_context: dict[str, Any],
    ) -> None:
        """Registra decisiones auditables exigidas por SDD-15 §9."""
        manifest = result.matrix_bundle.manifest
        detail = result.detail
        self.log_decision(
            regla="cmf_matrix_version",
            umbral=config.matrices.active_version,
            valor={
                "version": manifest.version,
                "yaml_sha256": manifest.yaml_sha256,
                "effective_date": manifest.effective_date,
                "status": manifest.status,
            },
            accion="usar_matriz_normativa",
        )
        self.log_decision(
            regla="cmf_pd_mapping",
            umbral=config.pd_mapping.method,
            valor=conditional_context,
            accion="resolver_categoria_cmf",
        )
        self.log_decision(
            regla="cmf_consumer_debtor_aggregation",
            umbral=config.debtor_id_col,
            valor=_consumer_aggregation_stats(frame, config=config),
            accion="consolidar_consumo_por_deudor",
        )
        self.log_decision(
            regla="cmf_guarantee_policy",
            umbral={
                "enable_aval_substitution": config.guarantees.enable_aval_substitution,
                "financial_guarantee_policy": config.guarantees.financial_guarantee_policy,
            },
            valor={"guarantee_treatments": _value_counts(detail, "guarantee_treatment")},
            accion="aplicar_garantias",
        )
        self.log_decision(
            regla="cmf_contingent_b3",
            umbral=config.matrices.fail_on_unmapped_contingent_type,
            valor=_contingent_stats(frame, detail=detail, config=config),
            accion="convertir_contingentes_b3",
        )
        self.log_decision(
            regla="cmf_excluded_rows",
            umbral="sin_exclusiones_runtime",
            valor={
                "input_rows": len(frame.index),
                "detail_rows": len(detail.index),
                "excluded_rows": len(frame.index) - len(detail.index),
            },
            accion="publicar_detalle_calculado",
        )
        self.log_decision(
            regla="cmf_rounding_policy",
            umbral=config.exposure.rounding,
            valor={
                "total_provision_amount": str(result.card.total_provision_amount),
                "n_rows": result.card.n_rows,
            },
            accion="aplicar_redondeo",
        )
        self.log_decision(
            regla="cmf_falta_dato",
            umbral=config.guarantees.financial_guarantee_policy,
            valor={
                "pending_items": tuple(
                    item.model_dump(mode="json") for item in manifest.pending_items
                ),
                "warnings": _warning_codes(detail),
            },
            accion="trazar_brechas_normativas",
        )


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_CMF_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise CmfInputError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_pd_source_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida el artefacto PD condicional con error de configuración del step."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise CmfConfigError(
        "pd_mapping.method='pd_breaks' exige un artefacto PD pandas.DataFrame: "
        f"artefacto='{artifact}', tipo observado={type(value).__name__}."
    )


def _cmf_config_from_study(
    study: Study,
    *,
    fallback: CmfProvisioningConfig,
) -> CmfProvisioningConfig:
    """Lee ``NikodymConfig.provisioning_cmf`` y usa el config del paso como respaldo."""
    raw_config = getattr(study.config, "provisioning_cmf", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, CmfProvisioningConfig):
        return raw_config
    return CmfProvisioningConfig.model_validate(raw_config)


def _as_of_date_from_frame(frame: DataFrame, config: CmfProvisioningConfig) -> str:
    """Resuelve una fecha de cierre única desde ``config.as_of_date_col``."""
    column = config.as_of_date_col
    if column not in frame.columns:
        raise CmfConfigError(
            "CmfProvisioningStep requiere una fecha de cierre única: "
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
        raise CmfConfigError(
            "CmfProvisioningStep requiere una fecha de cierre no nula en "
            f"as_of_date_col='{column}'."
        )
    if len(values) > 1:
        raise CmfConfigError(
            "CmfProvisioningStep requiere una sola fecha de cierre por corrida: "
            f"as_of_date_col='{column}', valores={values!r}."
        )
    return values[0]


def _pd_frame_if_required(
    study: Study,
    *,
    config: CmfProvisioningConfig,
    pd: Any,
) -> tuple[DataFrame | None, dict[str, Any]]:
    """Lee PD, labels y splits sólo cuando ``pd_mapping.method='pd_breaks'`` lo exige."""
    mapping = config.pd_mapping
    if mapping.method != _PD_BREAKS_METHOD:
        return None, {
            "method": mapping.method,
            "pd_source": None,
            "pd_column": None,
            "population_artifacts": (),
        }

    pd_artifact = (mapping.pd_source_domain, mapping.pd_source_key)
    _require_artifact_for_pd_breaks(study, *pd_artifact)
    labels = _require_artifact_for_pd_breaks(study, "data", "labels")
    splits = _require_artifact_for_pd_breaks(study, "data", "splits")
    pd_frame = _as_pd_source_dataframe(
        study.artifacts.get(*pd_artifact),
        pd,
        f"{pd_artifact[0]}.{pd_artifact[1]}",
    ).copy(deep=True)
    if mapping.pd_column not in pd_frame.columns:
        raise CmfConfigError(
            "pd_mapping.method='pd_breaks' exige que el artefacto PD contenga "
            f"pd_column='{mapping.pd_column}'."
        )
    return pd_frame, {
        "method": mapping.method,
        "pd_source": pd_artifact,
        "pd_column": mapping.pd_column,
        "pd_rows": len(pd_frame.index),
        "population_artifacts": ("data.labels", "data.splits"),
        "labels_type": type(labels).__name__,
        "splits_type": type(splits).__name__,
    }


def _require_artifact_for_pd_breaks(study: Study, domain: str, key: str) -> object:
    """Exige un artefacto condicional y cita ``pd_breaks`` en el error."""
    if not study.artifacts.has(domain, key):
        raise ArtifactNotFoundError(
            "pd_mapping.method='pd_breaks' exige el artefacto "
            f"('{domain}', '{key}') antes de calcular provisioning_cmf."
        )
    return study.artifacts.get(domain, key)


def _consumer_aggregation_stats(
    frame: DataFrame,
    *,
    config: CmfProvisioningConfig,
) -> dict[str, int | str]:
    """Resume la consolidación de consumo por deudor que ejecuta el motor."""
    portfolio_col = config.portfolio_col
    debtor_col = config.debtor_id_col
    if portfolio_col not in frame.columns:
        return {"portfolio_column": portfolio_col, "consumer_rows": 0, "consumer_debtors": 0}

    mask = cast(Any, frame[portfolio_col].astype("string")).eq("consumer").astype("boolean")
    consumer = frame.loc[mask.to_numpy(dtype=bool, na_value=False)]
    debtors = (
        int(cast(Any, consumer[debtor_col]).nunique(dropna=True))
        if debtor_col in consumer.columns
        else 0
    )
    return {
        "portfolio_column": portfolio_col,
        "consumer_rows": len(consumer.index),
        "consumer_debtors": debtors,
    }


def _contingent_stats(
    frame: DataFrame,
    *,
    detail: DataFrame,
    config: CmfProvisioningConfig,
) -> dict[str, Any]:
    """Resume contingentes B-3 convertidos y overrides de incumplimiento."""
    contingent_col = config.exposure.contingent_amount_col
    default_col = config.exposure.is_default_col
    if contingent_col not in frame.columns:
        return {
            "input_contingent_rows": 0,
            "converted_rows": int(_non_zero_count(detail, "contingent_exposure_amount")),
            "default_override_rows": 0,
            "ccf_percent_counts": _value_counts(detail, "ccf_percent"),
        }

    contingent_mask = _non_zero_mask(cast(Any, frame[contingent_col]))
    default_override_rows = 0
    if default_col in frame.columns:
        default_mask = _false_for_missing_bool_mask(cast(Any, frame[default_col]))
        default_override_rows = int((contingent_mask & default_mask).sum())
    return {
        "input_contingent_rows": int(contingent_mask.sum()),
        "converted_rows": int(_non_zero_count(detail, "contingent_exposure_amount")),
        "default_override_rows": default_override_rows,
        "ccf_percent_counts": _value_counts(detail, "ccf_percent"),
    }


def _value_counts(frame: DataFrame, column: str) -> dict[str, int]:
    """Cuenta valores publicables de una columna preservando representación estable."""
    if column not in frame.columns:
        return {}
    counts = cast(Any, frame[column]).astype("string").value_counts(dropna=False).sort_index()
    return {str(key): int(value) for key, value in counts.items()}


def _non_zero_count(frame: DataFrame, column: str) -> int:
    """Cuenta filas cuyo valor de columna no es cero ni nulo."""
    if column not in frame.columns:
        return 0
    return int(_non_zero_mask(cast(Any, frame[column])).sum())


def _non_zero_mask(series: Any) -> Any:
    """Construye máscara no-nula y no-cero sin ``fillna`` sobre dtype ``object``."""
    return cast(Any, series.notna() & series.ne(0)).astype("boolean")


def _false_for_missing_bool_mask(series: Any) -> Any:
    """Convierte flags a boolean nullable y rellena nulos sin downcast de ``object``."""
    return cast(Any, series).astype("boolean").fillna(False)


def _warning_codes(detail: DataFrame) -> tuple[str, ...]:
    """Extrae códigos de warning únicos desde ``detail.warning_codes``."""
    if "warning_codes" not in detail.columns:
        return ()
    warnings: list[str] = []
    for raw in cast(Any, detail["warning_codes"]).tolist():
        if isinstance(raw, (tuple, list)):
            warnings.extend(str(item) for item in raw)
        elif raw not in (None, ""):
            warnings.append(str(raw))
    return tuple(dict.fromkeys(warnings))
