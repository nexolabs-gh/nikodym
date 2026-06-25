"""Capa ``audit`` de Nikodym: JSONL, entorno, hashing y replay (SDD-03).

Al importarse, registra :class:`AuditConfig` en el hook diferido de
:mod:`nikodym.core.config.schema`. Así ``NikodymConfig.audit`` se valida como sub-config real sin
que ``import nikodym.core`` arrastre ``nikodym.audit`` ni sus dependencias perezosas.

**Experimental (SemVer 0.x).**
"""

from nikodym.audit.config import AuditConfig
from nikodym.audit.environment import (
    DEFAULT_TRACKED_PACKAGES,
    EnvironmentSnapshot,
    capture_environment,
)
from nikodym.audit.exceptions import AuditError
from nikodym.audit.hashing import hash_dataframe, hash_file
from nikodym.audit.replay import iter_trail, read_trail
from nikodym.audit.sink import JsonlAuditSink
from nikodym.core.config import schema as _schema

_schema._AUDIT_CONFIG_CLS = AuditConfig

__all__ = [
    "DEFAULT_TRACKED_PACKAGES",
    "AuditConfig",
    "AuditError",
    "EnvironmentSnapshot",
    "JsonlAuditSink",
    "capture_environment",
    "hash_dataframe",
    "hash_file",
    "iter_trail",
    "read_trail",
]
