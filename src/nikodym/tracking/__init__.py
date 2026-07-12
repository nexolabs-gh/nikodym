"""Capa ``tracking`` de Nikodym: frontera MLflow para runs e inventario (SDD-04).

Al importarse, registra :class:`TrackingConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.tracking`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.tracking`` ni ``mlflow``. MLflow se importa
siempre de forma perezosa dentro de los métodos que lo necesitan.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from nikodym.core.config import schema as _schema
from nikodym.governance.exceptions import RegistryUnavailableError
from nikodym.tracking.config import TrackingConfig
from nikodym.tracking.exceptions import ModelNotFoundError, TrackingError
from nikodym.tracking.inventory import MLflowInventory, ModelVersionRef, RegisteredModelInfo
from nikodym.tracking.recorder import RunHandle, TrackingRecorder
from nikodym.tracking.sink import TrackingSink

_schema._TRACKING_CONFIG_CLS = TrackingConfig

__all__ = [
    "MLflowInventory",
    "ModelNotFoundError",
    "ModelVersionRef",
    "RegisteredModelInfo",
    "RegistryUnavailableError",
    "RunHandle",
    "TrackingConfig",
    "TrackingError",
    "TrackingRecorder",
    "TrackingSink",
]
