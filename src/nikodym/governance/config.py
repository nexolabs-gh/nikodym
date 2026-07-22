"""Config de gobernanza e inventario de modelos (SDD-03 §5)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from nikodym.core.config import NikodymBaseConfig

__all__ = ["GovernanceConfig"]


class GovernanceConfig(NikodymBaseConfig):
    """Documenta el modelo para su gobierno: model card, inventario y diario de overlays.

    Cambiar el propósito, los metadatos de inventario o la política de publicación no altera los
    resultados de la corrida ni su ``config_hash``; el cambio queda registrado en el model card
    y en el audit-trail.
    """

    model_name: str = Field(
        default="nikodym-model",
        title="Nombre lógico del modelo",
        description="Identidad en el inventario (clave del MLflow Registry).",
    )
    cartera: Literal["comercial", "consumo", "hipotecario", "grupal"] | None = Field(
        default=None,
        title="Cartera",
        description="Naming CMF en español; se publica como tag nikodym.cartera.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Inventario", "ui_order": 1},
    )
    motor: Literal["scoring", "cmf", "ifrs9"] | None = Field(
        default=None,
        title="Motor",
        description="Separación de motores CMF/IFRS9/scoring; tag nikodym.motor.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Inventario", "ui_order": 2},
    )
    fase: Literal["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "originacion"] | None = Field(
        default=None,
        title="Fase de construcción",
        description="Fase de construcción del modelo; tag nikodym.fase.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Inventario", "ui_order": 3},
    )
    estado_validacion: Literal["desarrollo", "en_validacion", "validado", "retirado"] = Field(
        default="desarrollo",
        title="Estado de validación",
        description=(
            "Ciclo de vida de effective challenge; tag nikodym.estado_validacion. Es ortogonal "
            "a los aliases de despliegue."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Inventario", "ui_order": 4},
    )
    author: str | None = Field(
        default=None,
        title="Autor / responsable",
        description="Email o identidad del responsable; tag nikodym.autor.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Inventario", "ui_order": 5},
    )
    purpose: str = Field(
        default=...,
        title="Propósito del modelo",
        description="Declaración de propósito (SR 11-7); obligatoria para el model card.",
    )
    assumptions: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Supuestos declarados",
        description="Supuestos de desarrollo que se copian al model card.",
    )
    limitations: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Limitaciones declaradas",
        description="Limitaciones de uso que se copian al model card.",
    )
    review_period_months: int = Field(
        default=12,
        ge=1,
        le=60,
        title="Periodicidad de revisión (meses)",
        description="next_review_date = fecha de emisión + este periodo (SR 11-7).",
    )
    publish_to_inventory: bool = Field(
        default=False,
        title="Publicar al inventario",
        description="True requiere el extra tracking; False genera solo evidencia local.",
    )
    scenario_log_filename: str = Field(
        default="scenario_log.jsonl",
        title="Diario de escenarios/overlays",
        description="Nombre del JSONL append-only dentro del directorio del run.",
    )
    require_overlay_justification: bool = Field(
        default=True,
        title="Exigir justificación de overlays",
        description="True: un overlay sin justificación es error anti earnings-management.",
    )
