"""Schema declarativo raíz del config de Nikodym (SDD-01 §4-5, SDD-05 §5).

Define la base común inmutable :class:`NikodymBaseConfig` y el config raíz
:class:`NikodymConfig`, que agrega las secciones transversales del experimento:
reproducibilidad (:class:`ReproConfig`), orquestación (:class:`RunConfig`) y los enganches
opcionales a datos (``data``), análisis exploratorio (``eda``), binning (``binning``), selección
pre-modelo (``selection``), modelo PD (``model``), escalamiento de scorecard (``scorecard``) y
calibración de PD (``calibration``). El config es *frozen*: su identidad se fija por
``config_hash`` (ver
:mod:`nikodym.core.config.hashing`), no por mutación.
``NikodymConfig()`` debe construir sin argumentos —todas las secciones tienen valor por defecto—
de modo que la UI sea un editor del mismo objeto. **Experimental (SemVer 0.x):** las secciones de
dominio se añaden de forma aditiva por capa; el orden de declaración define el pipeline por
defecto y el orden del YAML legible.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from nikodym.audit.config import AuditConfig
    from nikodym.binning.config import BinningConfig
    from nikodym.calibration.config import CalibrationConfig
    from nikodym.data.config import DataConfig
    from nikodym.eda.config import EdaConfig
    from nikodym.governance.config import GovernanceConfig
    from nikodym.model.config import ModelConfig
    from nikodym.scorecard.config import ScorecardConfig
    from nikodym.selection.config import SelectionConfig
    from nikodym.tracking.config import TrackingConfig

__all__ = ["NikodymBaseConfig", "NikodymConfig", "ReproConfig", "RunConfig"]

# Hook poblado por `nikodym.data` al importarse: la clase real del sub-config de la sección `data`.
# `core` NO importa `data` (núcleo liviano, D-CORE-1); `data` registra aquí su `DataConfig` para que
# `NikodymConfig` valide/coaccione esa sección sin que el núcleo conozca el módulo. Mientras sea
# None (core en solitario), `data` se trata como un blob JSON-canónico opaco (ver `_valida_data`).
# Reemplaza el `model_rebuild()` del SDD-02 §5: Pydantic v2 no re-narra un campo ya resuelto (B2a).
_DATA_CONFIG_CLS: type[BaseModel] | None = None
_EDA_CONFIG_CLS: type[BaseModel] | None = None
_BINNING_CONFIG_CLS: type[BaseModel] | None = None
_SELECTION_CONFIG_CLS: type[BaseModel] | None = None
_MODEL_CONFIG_CLS: type[BaseModel] | None = None
_SCORECARD_CONFIG_CLS: type[BaseModel] | None = None
_CALIBRATION_CONFIG_CLS: type[BaseModel] | None = None
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
    ``data``, ``eda``, ``binning``, ``selection``, ``model``, ``scorecard``, ``calibration``).
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
        # Vista de mypy: tipo estricto. En runtime el campo es `Any` (rama `else`) y la
        # validación/coerción a `EdaConfig` la hace `_valida_eda` vía el hook `_EDA_CONFIG_CLS`.
        eda: EdaConfig | None
    else:
        eda: Any = Field(
            default=None,
            title="EDA",
            description="Sección de análisis exploratorio descriptivo (capa `eda`, SDD-27).",
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto. En runtime el campo es `Any` (rama `else`) y la
        # validación/coerción a `BinningConfig` la hace `_valida_binning` vía hook diferido.
        binning: BinningConfig | None
    else:
        binning: Any = Field(
            default=None,
            title="Binning",
            description="Sección de binning supervisado WoE/IV (capa `binning`, SDD-06).",
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto. En runtime el campo es `Any` (rama `else`) y la
        # validación/coerción a `SelectionConfig` la hace `_valida_selection` vía hook diferido.
        selection: SelectionConfig | None
    else:
        selection: Any = Field(
            default=None,
            title="Selección",
            description=(
                "Sección de selección pre-modelo de variables WoE (capa `selection`, SDD-07)."
            ),
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto. En runtime el campo es `Any` (rama `else`) y la
        # validación/coerción a `ModelConfig` la hace `_valida_model` vía hook diferido.
        model: ModelConfig | None
    else:
        model: Any = Field(
            default=None,
            title="Modelo",
            description=(
                "Sección de modelo logístico PD sobre variables WoE (capa `model`, SDD-08)."
            ),
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto. En runtime el campo es `Any` (rama `else`) y la
        # validación/coerción a `ScorecardConfig` la hace `_valida_scorecard` vía hook diferido.
        scorecard: ScorecardConfig | None
    else:
        scorecard: Any = Field(
            default=None,
            title="Scorecard",
            description=("Sección de escalamiento log-odds a puntos (capa `scorecard`, SDD-09)."),
        )
    if TYPE_CHECKING:
        # Vista de mypy: tipo estricto. En runtime el campo es `Any` (rama `else`) y la
        # validación/coerción a `CalibrationConfig` la hace `_valida_calibration` vía hook diferido.
        calibration: CalibrationConfig | None
    else:
        calibration: Any = Field(
            default=None,
            title="Calibración",
            description="Sección de calibración de PD cruda a PD calibrada (capa `calibration`).",
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

    @field_validator("eda", mode="before")
    @classmethod
    def _valida_eda(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``eda`` según haya o no capa ``eda`` cargada.

        Con ``nikodym.eda`` importado (``_EDA_CONFIG_CLS`` poblado), un ``dict`` se valida y
        coacciona a :class:`EdaConfig` (``extra='forbid'`` y rangos); una instancia ya validada
        pasa tal cual. Sin la capa cargada, ``eda`` es un *blob* opaco: se exige JSON-canónico y
        determinista (sin sets, objetos no serializables ni floats no finitos) para no corromper el
        ``config_hash`` entre procesos.
        """
        if valor is None:
            return valor
        if _EDA_CONFIG_CLS is not None:
            if isinstance(valor, _EDA_CONFIG_CLS):
                return valor
            return _EDA_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "eda debe ser JSON-canónico y determinista (sin sets, objetos no serializables ni "
                "floats no finitos), o importa `nikodym.eda` para validarlo como EdaConfig."
            ) from exc
        return valor

    @field_validator("binning", mode="before")
    @classmethod
    def _valida_binning(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``binning`` según haya o no capa ``binning`` cargada.

        Con ``nikodym.binning`` importado (``_BINNING_CONFIG_CLS`` poblado), un ``dict`` se valida
        y coacciona a :class:`BinningConfig` (``extra='forbid'`` y rangos); una instancia ya
        validada pasa tal cual. Sin la capa cargada, ``binning`` es un *blob* opaco: se exige
        JSON-canónico y determinista (sin sets, objetos no serializables ni floats no finitos)
        para no corromper el ``config_hash`` entre procesos.
        """
        if valor is None:
            return valor
        if _BINNING_CONFIG_CLS is not None:
            if isinstance(valor, _BINNING_CONFIG_CLS):
                return valor
            return _BINNING_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "binning debe ser JSON-canónico y determinista (sin sets, objetos no "
                "serializables ni floats no finitos), o importa `nikodym.binning` para validarlo "
                "como BinningConfig."
            ) from exc
        return valor

    @field_validator("selection", mode="before")
    @classmethod
    def _valida_selection(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``selection`` según haya o no capa ``selection`` cargada.

        Con ``nikodym.selection`` importado (``_SELECTION_CONFIG_CLS`` poblado), un ``dict`` se
        valida y coacciona a :class:`SelectionConfig` (``extra='forbid'`` y rangos); una instancia
        ya validada pasa tal cual. Sin la capa cargada, ``selection`` es un *blob* opaco: se exige
        JSON-canónico y determinista (sin sets, objetos no serializables ni floats no finitos) para
        no corromper el ``config_hash`` entre procesos.
        """
        if valor is None:
            return valor
        if _SELECTION_CONFIG_CLS is not None:
            if isinstance(valor, _SELECTION_CONFIG_CLS):
                return valor
            return _SELECTION_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "selection debe ser JSON-canónico y determinista (sin sets, objetos no "
                "serializables ni floats no finitos), o importa `nikodym.selection` para validarlo "
                "como SelectionConfig."
            ) from exc
        return valor

    @field_validator("model", mode="before")
    @classmethod
    def _valida_model(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``model`` según haya o no capa ``model`` cargada.

        Con ``nikodym.model`` importado (``_MODEL_CONFIG_CLS`` poblado), un ``dict`` se valida y
        coacciona a :class:`ModelConfig` (``extra='forbid'`` y rangos); una instancia ya validada
        pasa tal cual. Sin la capa cargada, ``model`` es un *blob* opaco: se exige JSON-canónico y
        determinista (sin sets, objetos no serializables ni floats no finitos) para no corromper el
        ``config_hash`` entre procesos.
        """
        if valor is None:
            return valor
        if _MODEL_CONFIG_CLS is not None:
            if isinstance(valor, _MODEL_CONFIG_CLS):
                return valor
            return _MODEL_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "model debe ser JSON-canónico y determinista (sin sets, objetos no "
                "serializables ni floats no finitos), o importa `nikodym.model` para validarlo "
                "como ModelConfig."
            ) from exc
        return valor

    @field_validator("scorecard", mode="before")
    @classmethod
    def _valida_scorecard(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``scorecard`` según haya o no capa cargada.

        Con ``nikodym.scorecard`` importado (``_SCORECARD_CONFIG_CLS`` poblado), un ``dict`` se
        valida y coacciona a :class:`ScorecardConfig` (``extra='forbid'`` y rangos); una instancia
        ya validada pasa tal cual. Sin la capa cargada, ``scorecard`` es un *blob* opaco: se exige
        JSON-canónico y determinista (sin sets, objetos no serializables ni floats no finitos) para
        no corromper el ``config_hash`` entre procesos.
        """
        if valor is None:
            return valor
        if _SCORECARD_CONFIG_CLS is not None:
            if isinstance(valor, _SCORECARD_CONFIG_CLS):
                return valor
            return _SCORECARD_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "scorecard debe ser JSON-canónico y determinista (sin sets, objetos no "
                "serializables ni floats no finitos), o importa `nikodym.scorecard` para "
                "validarlo como ScorecardConfig."
            ) from exc
        return valor

    @field_validator("calibration", mode="before")
    @classmethod
    def _valida_calibration(cls, valor: Any) -> Any:
        """Valida/coacciona la sección ``calibration`` según haya o no capa cargada.

        Con ``nikodym.calibration`` importado (``_CALIBRATION_CONFIG_CLS`` poblado), un ``dict``
        se valida y coacciona a :class:`CalibrationConfig` (``extra='forbid'`` y rangos); una
        instancia ya validada pasa tal cual. Sin la capa cargada, ``calibration`` es un *blob*
        opaco: se exige JSON-canónico y determinista (sin sets, objetos no serializables ni floats
        no finitos) para no corromper el ``config_hash`` entre procesos.
        """
        if valor is None:
            return valor
        if _CALIBRATION_CONFIG_CLS is not None:
            if isinstance(valor, _CALIBRATION_CONFIG_CLS):
                return valor
            return _CALIBRATION_CONFIG_CLS.model_validate(valor)
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "calibration debe ser JSON-canónico y determinista (sin sets, objetos no "
                "serializables ni floats no finitos), o importa `nikodym.calibration` para "
                "validarlo como CalibrationConfig."
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
