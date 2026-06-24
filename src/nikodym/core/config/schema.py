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
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["NikodymBaseConfig", "NikodymConfig", "ReproConfig", "RunConfig"]


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
    # TODO(B2/SDD-02): endurecer a `DataConfig | None` (forward-ref resuelto con `model_rebuild()`
    # al importar `nikodym.data`). En F0 el módulo data no existe; el placeholder `Any` permite
    # construir `NikodymConfig()` hoy y, como por defecto es None, no altera el `config_hash` al
    # endurecerlo (con `data=None` ambas anotaciones serializan a `null`).
    data: Any = Field(
        default=None,
        title="Datos",
        description="Sección de origen y validación de datos (se define en la capa data).",
    )

    @field_validator("data")
    @classmethod
    def _data_json_canonica(cls, valor: Any) -> Any:
        """Exige que el placeholder ``data`` sea JSON-canónico y determinista.

        Mientras ``data`` sea ``Any`` (hasta endurecerlo a ``DataConfig`` en B2), un ``set``,
        un objeto no serializable o un float no finito dentro de ``data`` entraría al
        ``config_hash`` y lo volvería no determinista entre procesos (el orden de iteración de
        un ``set`` depende de ``PYTHONHASHSEED``) o lo corromperían en silencio: ambos rompen la
        identidad de la corrida. Se rechazan al construir, con ``ConfigError`` vía Pydantic.
        """
        if valor is None:
            return valor
        try:
            json.dumps(valor, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "data debe ser JSON-canónico y determinista (sin sets, objetos no serializables "
                "ni floats no finitos); se endurecerá a DataConfig en B2."
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
