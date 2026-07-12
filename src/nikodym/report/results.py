"""DTOs puros de resultados de reporte auditable (SDD-26 §4/§6).

Este módulo fija los contenedores de entrada y salida de ``report``: secciones lógicas,
snapshot de inputs, bloques de narrativa IA, manifiesto y resultado agregado. No renderiza,
no escribe archivos, no llama a red y no importa ``pandas`` ni ``LineageBundle`` en runtime; ambos
son solo tipos bajo ``TYPE_CHECKING`` para preservar el import liviano.

``metric_sections`` conserva la puerta CT-2 como estructura anidada y aditiva. Las colecciones
mutables y DataFrames se copian defensivamente al validar y al acceder desde los DTOs para cumplir
la invariante de no mutación de SDD-26 §9.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nikodym.report.document import SectionKind

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.lineage import LineageBundle

    DataFrameLike: TypeAlias = pd.DataFrame
    LineageBundleLike: TypeAlias = LineageBundle
else:
    DataFrameLike: TypeAlias = Any
    LineageBundleLike: TypeAlias = Any

ReportSectionStatus: TypeAlias = Literal["included", "missing", "skipped", "failed"]
ReportOutputFormat: TypeAlias = Literal["html", "pdf", "docx", "json", "csv", "xlsx"]

__all__ = [
    "AiNarrationBlock",
    "PlaceholderBlock",
    "ReportInputBundle",
    "ReportManifest",
    "ReportOutputFormat",
    "ReportResult",
    "ReportSection",
    "ReportSectionStatus",
    "SectionKind",
]


class _ReportBaseModel(BaseModel):
    """Base interna con inmutabilidad y copias defensivas al leer campos mutables."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset()

    def __getattribute__(self, name: str) -> Any:
        """Entrega una copia defensiva para campos mutables declarados por cada DTO."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return _copy_report_value(value)
        return value


class PlaceholderBlock(_ReportBaseModel):
    """Bloque **POR COMPLETAR** que un humano debe redactar, con guía de qué escribir.

    No es un lorem ipsum mudo: ``guidance`` dice explícitamente qué se espera en ese hueco. Con
    ``report.document.placeholders='hide'`` el render lo omite y el mismo motor sirve para el
    borrador y para el entregable final.
    """

    title: str
    guidance: tuple[str, ...] = Field(default=())


class ReportSection(_ReportBaseModel):
    """Sección del documento: capítulo de prosa, bloque de datos, índice o anexo.

    Los campos de estructura (``kind``, ``level``, ``number``, ``body``, ``placeholder``) son
    aditivos y traen default, de modo que un ``ReportSection`` construido con el contrato previo
    —una card del pipeline— sigue validando sin cambios.
    """

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"payload", "metric_sections"})

    id: str
    title: str
    status: ReportSectionStatus
    source_domain: str | None
    source_key: str | None
    payload: dict[str, Any] = Field(default_factory=dict)
    metric_sections: dict[str, Any] = Field(default_factory=dict)
    kind: SectionKind = "data"
    level: int = Field(default=1, ge=1, le=2)
    number: str = ""
    body: tuple[str, ...] = Field(default=())
    placeholder: PlaceholderBlock | None = None

    @field_validator("payload", "metric_sections", mode="before")
    @classmethod
    def _copia_payload_mutable(cls, value: Any) -> Any:
        """Copia profundamente payloads anidados sin aplanar ``metric_sections``."""
        return _copy_report_value(value)


class ReportInputBundle(_ReportBaseModel):
    """Snapshot lógico de cards, tablas, figuras, secciones y lineage usados por el reporte."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"cards", "tables", "figures", "pipeline_params"}
    )

    lineage: LineageBundleLike
    cards: dict[str, Any]
    tables: dict[str, DataFrameLike]
    figures: dict[str, Any]
    sections: tuple[ReportSection, ...]
    missing_sections: tuple[str, ...] = Field(default=())
    pipeline_params: dict[str, Any] = Field(default_factory=dict)
    """Snapshot JSON de las secciones de config de cada dominio del pipeline.

    Es lo que permite que la Metodología describa **lo que realmente se ejecutó** (solver del
    binning, umbrales de selección, escala del scorecard) en vez de frases fijas. Un dominio
    ausente simplemente no aparece: la prosa omite lo que no puede afirmar.
    """

    @field_validator("cards", "tables", "figures", "pipeline_params", mode="before")
    @classmethod
    def _copia_contenedores_mutables(cls, value: Any) -> Any:
        """Copia cards, tablas y figuras para aislar el bundle de mutaciones externas."""
        return _copy_report_value(value)


class AiNarrationBlock(_ReportBaseModel):
    """Bloque de texto narrativo básico o enriquecido por IA opcional."""

    section_id: str
    text: str
    provider: str
    model: str
    generated: bool
    prompt_hash: str
    input_payload_hash: str
    warning: str | None = None


class ReportManifest(_ReportBaseModel):
    """Manifiesto reproducible de un artefacto de reporte escrito por ``report``."""

    report_id: str
    title: str
    created_from_lineage_at: str
    template_id: str
    template_version: str
    output_format: ReportOutputFormat
    path: str
    sha256: str
    deterministic: bool
    ai_enabled: bool
    ai_used: bool
    sections: tuple[ReportSection, ...]


class ReportResult(_ReportBaseModel):
    """Contenedor agregado publicado como salida final de la capa ``report``."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"data_exports"})

    manifest: ReportManifest
    input_bundle: ReportInputBundle
    html_path: str | None = None
    pdf_path: str | None = None
    docx_path: str | None = None
    data_exports: dict[str, str] = Field(default_factory=dict)
    ai_blocks: tuple[AiNarrationBlock, ...] = Field(default=())

    @field_validator("data_exports", mode="before")
    @classmethod
    def _copia_data_exports(cls, value: Any) -> Any:
        """Copia rutas de exports tabulares para evitar aliasing de dicts externos."""
        return _copy_report_value(value)


def _copy_report_value(value: Any) -> Any:
    if _is_dataframe_like(value):
        return value.copy(deep=True)
    if isinstance(value, Mapping):
        return {copy.deepcopy(key): _copy_report_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_report_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_report_value(item) for item in value)
    return copy.deepcopy(value)


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))
