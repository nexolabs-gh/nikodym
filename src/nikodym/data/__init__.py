"""Capa ``data`` de Nikodym (SDD-02): carga, validación, target, particiones, ``data_hash``.

Al importarse, registra :class:`~nikodym.data.config.DataConfig` en el *hook* ``_DATA_CONFIG_CLS``
de :mod:`nikodym.core.config.schema`: así ``NikodymConfig`` valida y coacciona su sección ``data``
como :class:`DataConfig` **sin que ``core`` importe ``data``** (núcleo liviano, D-CORE-1). La
inversión de la dependencia vive en este lado (``data`` conoce a ``core``, no al revés).

.. note::
   El SDD-02 §5 preveía resolver el *forward-ref* con ``NikodymConfig.model_rebuild()``; se descartó
   porque Pydantic v2 **no re-narra** un campo ya resuelto (verificado, B2a). El *hook* + validador
   es el reemplazo: valida en construcción y mantiene el núcleo liviano.

**Experimental (SemVer 0.x).**
"""

from nikodym.core.config import schema as _schema
from nikodym.data.card import DataCardSection
from nikodym.data.config import DataConfig
from nikodym.data.hashing import data_hash
from nikodym.data.loading import DataLoader
from nikodym.data.partition import Partitioner, PartitionResult
from nikodym.data.schema import SchemaValidator
from nikodym.data.special import MaskedFrame, SpecialValuePolicy
from nikodym.data.step import DataStep
from nikodym.data.target import LabeledFrame, TargetDefinition

# Registra la clase real del sub-config de datos en el hook de `core`.
_schema._DATA_CONFIG_CLS = DataConfig

__all__ = [
    "DataCardSection",
    "DataConfig",
    "DataLoader",
    "DataStep",
    "LabeledFrame",
    "MaskedFrame",
    "PartitionResult",
    "Partitioner",
    "SchemaValidator",
    "SpecialValuePolicy",
    "TargetDefinition",
    "data_hash",
]
