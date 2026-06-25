"""Capa ``governance`` de Nikodym: model card, inventario y escenarios (SDD-03).

Al importarse, registra :class:`GovernanceConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.governance`` se valida como sub-config real
sin que ``import nikodym.core`` arrastre ``nikodym.governance``.

**Experimental (SemVer 0.x).**
"""

from nikodym.core.config import schema as _schema
from nikodym.governance.config import GovernanceConfig
from nikodym.governance.exceptions import GovernanceError, RegistryUnavailableError
from nikodym.governance.inventory import (
    InventoryEntry,
    InventoryRecord,
    ModelInventory,
    NullInventory,
    publish_inventory,
)
from nikodym.governance.model_card import DecisionRecord, ModelCard, ModelCardBuilder
from nikodym.governance.scenarios import OverlayRecord, ScenarioLog, ScenarioRecord

_schema._GOVERNANCE_CONFIG_CLS = GovernanceConfig

__all__ = [
    "DecisionRecord",
    "GovernanceConfig",
    "GovernanceError",
    "InventoryEntry",
    "InventoryRecord",
    "ModelCard",
    "ModelCardBuilder",
    "ModelInventory",
    "NullInventory",
    "OverlayRecord",
    "RegistryUnavailableError",
    "ScenarioLog",
    "ScenarioRecord",
    "publish_inventory",
]
