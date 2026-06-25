"""Schema declarativo raíz del config de Nikodym (SDD-01 §4-5, SDD-05 §5).

Define la base común inmutable :class:`NikodymBaseConfig` y el config raíz
:class:`NikodymConfig`, que agrega las secciones transversales del experimento:
reproducibilidad (:class:`ReproConfig`), orquestación (:class:`RunConfig`) y el enganche
opcional a datos (``data``). El config es *frozen*: su identidad se fija por ``config_hash``
(ver :mod:`nikodym.core.config.hashing`), no por mutación. ``NikodymConfig()`` debe construir
sin argumentos —todas las secciones tienen valor por defecto— de modo que la UI sea un editor
del mismo objeto. **Experimental (SemVer 0.x):** las secciones de dominio se añaden de forma
aditiva por capa; el orden de declaración define el pipeline por defecto y el orden del YAML
legible.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from nikodym.audit.config import AuditConfig
    from nikodym.data.config import DataConfig
    from nikodym.governance.config import GovernanceConfig
    from nikodym.tracking.config import TrackingConfig

__all__ = ["NikodymBaseConfig", "NikodymConfig", "ReproConfig", "RunConfig"]

# Hook poblado por `nikodym.data` al importarse: la clase real del sub-config de la sección `data`.
# `core` NO importa `data` (núcleo liviano, D-CORE-1); `data` registra aquí su `DataConfig` para que
# `NikodymConfig` valide/coaccione esa sección sin que el núcleo conozca el módulo. Mientras sea
# None (core en solitario), `data` se trata como un blob JSON-canónico opaco (ver `_valida_data`).
# Reemplaza el `model_rebuild()` del SDD-02 §5: Pydantic v2 no re-narra un campo ya resuelto (B2a).
_DATA_CONFIG_CLS: type[BaseModel] | None = None
_AUDIT_CONFIG_CLS: type[BaseModel] | None = None
_GOVERNANCE_CONFIG_CLS: type[BaseModel] | None = None
_TRACKING_CONFIG_CLS: type[BaseModel] | None = None


class NikodymBaseConfig(BaseModel):
    """Base común de todo config: cerrada (``extra='forbid'``) e inmutable (``frozen``).

    ``extra='forbid'`` convierte un campo desconocido en YAML (típicamente un *typo*) en un
    error de validación en vez de un descarte silencioso. ``frozen=True`` impide mutar una
    instancia ya construida: la identidad de una corrida se ancla al ``config_hash`` y un cambio
    exige construir un config nuevo. ``frozen`` no congela el contenido de listas/dicts anidados
    ni vuelve el modelo *hashable*; por eso la identidad va por ``config_hash``, no por
    ``__hash__``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReproConfig(NikodymBaseConfig):
    """Parámetros de reproducibilidad del experimento."""

    seed: int = Field(
        default=42,
        ge=0,
        title="Semilla",
        description="Semilla raíz del azar (>= 0; SeedSequence rechaza entropía negativa).",
    )
    strict_determinism: bool = Field(
        default=False,
        title="Determinismo estricto",
        description="True fuerza single-thread en GBDT a costa de velocidad (caveat multihilo).",
    )


class RunConfig(NikodymBaseConfig):
    """Parámetros de orquestación de la corrida."""

    steps: list[str] | None = Field(
        default=None,
        title="Pasos a ejecutar",
        description="None = pipeline por defecto (las secciones no-None en orden de declaración).",
    )
    fail_fast: bool = Field(
        default=True,
        title="Fallar rápido",
        description="v1: forzado a True; False queda reservado para v2 (lo valida el orquestador).",
    )


class NikodymConfig(NikodymBaseConfig):
    """Config raíz declarativo: agrega las secciones transversales del experimento.

    ``NikodymConfig()`` construye sin argumentos con todos los valores por defecto (DoD F0). Las
    secciones de dominio (binning, model, provisioning, ...) se añaden de forma aditiva por capa;
    en F0 solo viven las transversales (``schema_version``, ``name``, ``repro``, ``run``,
    ``data``).
    """

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del schema",
        description="SemVer del schema del config; gobierna la migración al cargar.",
    )
    name: str = Field(
        default="nikodym-study",
        title="Nombre del estudio",
        description="Etiqueta humana del experimento; infraestructural, no entra al config_hash.",
    )
    repro: ReproConfig = Field(default_factory=ReproConfig, title="Reproducibilidad")
    run: RunConfig = Field(default_factory=RunConfig, title="Orquestación")
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto. En runtime el campo es `Any` (rama `else`) y la
        # validación/coerción a `DataConfig` la hace `_valida_data` vía el hook `_DATA_CONFIG_CLS`
        # (Pydantic v2 no puede re-narrar un campo ya resuelto con `model_rebuild`; ver B2a).
        data: DataConfig | None
    else:
        data: Any = Field(
            default=None,
            title="Datos",
            description="Sección de origen y validación de datos (capa `data`, SDD-02).",
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto sin importar `nikodym.audit` en runtime.
        audit: AuditConfig | None
    else:
        audit: Any = Field(
            default=None,
            title="Auditoría",
            description="Sección de infraestructura para persistencia del audit-trail (SDD-03).",
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto sin importar `nikodym.governance` en runtime.
        governance: GovernanceConfig | None
    else:
        governance: Any = Field(
            default=None,
            title="Gobernanza",
            description="Sección de infraestructura para model card e inventario (SDD-03).",
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto sin importar `nikodym.tracking` ni MLflow en runtime.
        tracking: TrackingConfig | None
    else:
        tracking: Any = Field(
            default=None,
            title="Tracking",
            description="Sección de infraestructura para MLflow runs/registry (SDD-04).",
        )

    @field_validator("data", mode="before")
    @classmethod
    def _valida_data(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``data`` según haya o no capa ``data`` cargada.

        Con ``nikodym.data`` importado (``_DATA_CONFIG_CLS`` poblado), un ``dict`` se valida y
        coacciona a :class:`DataConfig` (``extra='forbid'``, tipos, mini-DSL); una instancia ya
        validada pasa tal cual. Sin la capa cargada, ``data`` es un *blob* opaco: se exige
        JSON-canónico y determinista (sin sets —cuyo orden depende de ``PYTHONHASHSEED``—, objetos
        no serializables ni floats no finitos) para no corromper el ``config_hash`` entre procesos.
        """
        if valor is None:
            return valor
        if _DATA_CONFIG_CLS is not None:
            if isinstance(valor, _DATA_CONFIG_CLS):
                return valor
            return _DATA_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "data debe ser JSON-canónico y determinista (sin sets, objetos no serializables ni "
                "floats no finitos), o importa `nikodym.data` para validarlo como DataConfig."
            ) from exc
        return valor

    @field_validator("audit", mode="before")
    @classmethod
    def _valida_audit(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``audit`` sin importar la capa desde ``core``."""
        if valor is None:
            return valor
        if _AUDIT_CONFIG_CLS is not None:
            if isinstance(valor, _AUDIT_CONFIG_CLS):
                return valor
            return _AUDIT_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "audit debe ser JSON-canónico y determinista (sin sets, objetos no serializables "
                "ni floats no finitos), o importa `nikodym.audit` para validarlo como AuditConfig."
            ) from exc
        return valor

    @field_validator("governance", mode="before")
    @classmethod
    def _valida_governance(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``governance`` sin importarla desde ``core``."""
        if valor is None:
            return valor
        if _GOVERNANCE_CONFIG_CLS is not None:
            if isinstance(valor, _GOVERNANCE_CONFIG_CLS):
                return valor
            return _GOVERNANCE_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "governance debe ser JSON-canónico y determinista (sin sets, objetos no "
                "serializables ni floats no finitos), o importa `nikodym.governance` para "
                "validarlo como GovernanceConfig."
            ) from exc
        return valor

    @field_validator("tracking", mode="before")
    @classmethod
    def _valida_tracking(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``tracking`` sin importar MLflow desde ``core``."""
        if valor is None:
            return valor
        if _TRACKING_CONFIG_CLS is not None:
            if isinstance(valor, _TRACKING_CONFIG_CLS):
                return valor
            return _TRACKING_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "tracking debe ser JSON-canónico y determinista (sin sets, objetos no "
                "serializables ni floats no finitos), o importa `nikodym.tracking` para "
                "validarlo como TrackingConfig."
            ) from exc
        return valor

    @model_validator(mode="after")
    def _check_cross_section(self) -> Self:
        """Valida invariantes estructurales entre secciones (no reglas de dominio).

        ``run.steps`` no puede referenciar una sección inactiva (``None``): sería un paso sin
        configuración. Las reglas de dominio (p. ej. "provisioning exige calibration") las valida
        el orquestador en runtime, no el schema.
        """
        if self.run.steps:
            inactivas = [s for s in self.run.steps if getattr(self, s, None) is None]
            if inactivas:
                raise ValueError(f"run.steps referencia secciones inactivas (None): {inactivas}.")
        return self
