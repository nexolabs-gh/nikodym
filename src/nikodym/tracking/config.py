"""Config de tracking MLflow (SDD-04 §5)."""

from __future__ import annotations

from pydantic import Field

from nikodym.core.config import NikodymBaseConfig

__all__ = ["TrackingConfig"]


class TrackingConfig(NikodymBaseConfig):
    """Registra la corrida en MLflow y publica el modelo en el Model Registry.

    Cambiar la URI, el experimento o la política de logging no altera los resultados de la
    corrida ni su ``config_hash``, así que apuntar a otro destino no duplica versiones en el
    inventario.
    """

    enabled: bool = Field(
        default=True,
        title="Tracking activo",
        description="Con False la corrida no se registra en MLflow.",
    )
    tracking_uri: str | None = Field(
        default=None,
        title="Tracking URI (destino de runs)",
        description=(
            "Destino MLflow. None => file store local './mlruns'. Acepta file://, sqlite:// "
            "o http(s):// según despliegue."
        ),
    )
    registry_uri: str | None = Field(
        default=None,
        title="Registry URI (inventario)",
        description=(
            "Destino del Model Registry. None => igual que tracking_uri. El Registry requiere "
            "backend de base de datos."
        ),
    )
    experiment_name: str | None = Field(
        default=None,
        title="Nombre del experimento",
        description="Agrupa los runs. None => se usa config.name en runtime.",
    )
    registered_model_name: str | None = Field(
        default=None,
        title="Nombre del modelo en el inventario",
        description="Nombre por defecto para atajos de registro. None => config.name.",
    )
    register_on_success: bool = Field(
        default=False,
        title="Registrar modelo al terminar",
        description=(
            "Reservado: por sí solo no registra el modelo. La publicación al inventario la "
            "decide governance.publish_to_inventory."
        ),
    )
    autolog: bool = Field(
        default=False,
        title="Autologging de MLflow",
        description=(
            "Nikodym nunca activa el autologging de MLflow: fijarlo en True se ignora con una "
            "advertencia y el registro sigue siendo explícito y auditable."
        ),
    )
    log_study_artifacts: bool = Field(
        default=True,
        title="Loguear el directorio del Study",
        description=(
            "Adjunta config.yaml, lineage.json y artifacts/ al run cuando el llamador lo pide."
        ),
    )
    log_models: bool = Field(
        default=True,
        title="Loguear el/los modelo(s) fiteados",
        description="Adjunta modelos serializados como artefactos de trazabilidad.",
    )
    fail_on_tracking_error: bool = Field(
        default=False,
        title="Abortar si falla el tracking",
        description=(
            "Default False: errores de MLflow degradan a warning + no-op y no tumban el cálculo."
        ),
    )
