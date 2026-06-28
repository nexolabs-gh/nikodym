"""Config declarativo de la capa ``report`` (SDD-26 §5).

:class:`ReportConfig` es la sección ``report`` de
:class:`~nikodym.core.config.NikodymConfig`: generación de reportes auditables de scorecard con
HTML básico determinístico por defecto, export tabular opcional, Quarto opcional y narrativa IA
opt-in. Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig`
(``extra='forbid'`` y ``frozen=True``); cada campo declara ``title``/``description`` y metadatos
``ui_*`` para que la UI (SDD-23) sea un editor del mismo config. La sección es infraestructura,
por lo que no entra al ``config_hash`` global.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from nikodym.core.config import NikodymBaseConfig

AiProvider = Literal["anthropic", "none"]
BasicReportFormat = Literal["html", "json", "csv", "xlsx"]
MissingPolicy = Literal["error", "warn", "skip"]
QuartoFormat = Literal["pdf", "docx"]
ReportLanguage = Literal["es"]
ReportTheme = Literal["nikodym", "plain"]
ReportType = Literal["standard"]

__all__ = [
    "AiNarrationConfig",
    "HtmlRenderConfig",
    "QuartoRenderConfig",
    "ReportConfig",
    "SectionPolicyConfig",
]


class HtmlRenderConfig(NikodymBaseConfig):
    """Config del render HTML básico determinístico."""

    template_id: str = Field(
        default="scorecard_basic_v1",
        title="Plantilla HTML",
        description="Identificador de la plantilla HTML básica de scorecard.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "HTML", "ui_order": 1},
    )
    theme: ReportTheme = Field(
        default="nikodym",
        title="Tema visual",
        description="Tema visual aplicado al HTML básico.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "HTML", "ui_order": 2},
    )
    embed_assets: bool = Field(
        default=True,
        title="Embeder assets",
        description="True embebe CSS, figuras y assets necesarios para un HTML standalone.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 3},
    )
    include_interactive_charts: bool = Field(
        default=False,
        title="Gráficos interactivos",
        description="Activa gráficos interactivos opcionales si el backend está disponible.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 4},
    )
    deterministic_ids: bool = Field(
        default=True,
        title="IDs determinísticos",
        description="True deriva IDs de secciones y figuras sin azar ni timestamps de pared.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 5},
    )


class QuartoRenderConfig(NikodymBaseConfig):
    """Config del render opcional vía Quarto."""

    enabled: bool = Field(
        default=False,
        title="Activar Quarto",
        description="Activa la generación opcional de formatos derivados mediante Quarto.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Quarto", "ui_order": 1},
    )
    formats: tuple[QuartoFormat, ...] = Field(
        default=(),
        title="Formatos Quarto",
        description="Formatos opcionales producidos por Quarto cuando está habilitado.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Quarto", "ui_order": 2},
    )
    fail_if_unavailable: bool = Field(
        default=False,
        title="Fallar si Quarto no está disponible",
        description="True convierte la ausencia del binario Quarto en error en vez de fallback.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Quarto", "ui_order": 3},
    )


class AiNarrationConfig(NikodymBaseConfig):
    """Config de la narrativa IA opcional y aislada de los números."""

    enabled: bool = Field(
        default=False,
        title="Activar narrativa IA",
        description="Activa el enriquecimiento opcional de texto mediante proveedor IA.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Narrativa IA", "ui_order": 1},
    )
    provider: AiProvider = Field(
        default="none",
        title="Proveedor IA",
        description="Proveedor de narrativa IA; 'none' preserva la ruta básica sin red.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Narrativa IA", "ui_order": 2},
    )
    model: str | None = Field(
        default=None,
        title="Modelo IA",
        description="Nombre del modelo IA opcional; None usa el default del narrador.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Narrativa IA", "ui_order": 3},
    )
    api_key_env: str = Field(
        default="ANTHROPIC_API_KEY",
        title="Variable de API key",
        description="Nombre de la variable de entorno que contiene la API key del proveedor.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Narrativa IA", "ui_order": 4},
    )
    timeout_seconds: float = Field(
        default=20.0,
        ge=1.0,
        le=120.0,
        title="Timeout IA",
        description="Tiempo máximo en segundos para una llamada de narrativa IA.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Narrativa IA", "ui_order": 5},
    )
    max_input_tokens: int = Field(
        default=12_000,
        ge=1_000,
        title="Máximo tokens entrada",
        description="Techo de tokens del payload sanitizado enviado al proveedor IA.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Narrativa IA", "ui_order": 6},
    )
    send_raw_data: Literal[False] = Field(
        default=False,
        title="Enviar datos crudos",
        description="Bloqueado en F1: la narrativa IA nunca recibe datos crudos.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Narrativa IA", "ui_order": 7},
    )
    label_ai_text: bool = Field(
        default=True,
        title="Etiquetar texto generado por IA",
        description="True marca explícitamente los bloques enriquecidos por IA.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Narrativa IA", "ui_order": 8},
    )


class SectionPolicyConfig(NikodymBaseConfig):
    """Config de secciones obligatorias, faltantes y tablas renderizadas."""

    required_sections: tuple[str, ...] = Field(
        default=(
            "eda",
            "binning",
            "selection",
            "model",
            "scorecard",
            "calibration",
            "performance",
            "stability",
        ),
        title="Secciones obligatorias F1",
        description="Secciones de scorecard requeridas por el reporte canónico F1.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Secciones", "ui_order": 1},
    )
    missing_policy: MissingPolicy = Field(
        default="error",
        title="Política de sección ausente",
        description="Acción ante secciones ausentes: error, warning o salto explícito.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Secciones", "ui_order": 2},
    )
    include_raw_tables: bool = Field(
        default=False,
        title="Incluir tablas completas",
        description="Activa exports tabulares completos cuando esté permitido por el flujo.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Secciones", "ui_order": 3},
    )
    max_table_rows: int = Field(
        default=200,
        ge=10,
        title="Máximo filas por tabla renderizada",
        description="Máximo de filas visibles por tabla en el reporte renderizado.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Secciones", "ui_order": 4},
    )


class ReportConfig(NikodymBaseConfig):
    """Sección ``report`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-26 §5)."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema report",
        description="Versión local del schema de report para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: ReportType = Field(
        default="standard",
        title="Tipo de sección report",
        description="== @register('standard', domain='report') (SDD-26 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    output_dir: str = Field(
        default="reports",
        title="Directorio de salida",
        description="Directorio relativo donde se escriben los artefactos del reporte.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "General", "ui_order": 2},
    )
    basename: str = Field(
        default="scorecard_report",
        title="Nombre base",
        description="Nombre base determinístico para los archivos del reporte.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "General", "ui_order": 3},
    )
    language: ReportLanguage = Field(
        default="es",
        title="Idioma",
        description="Idioma del reporte; F1 soporta español.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 4},
    )
    formats: tuple[BasicReportFormat, ...] = Field(
        default=("html",),
        title="Formatos básicos",
        description="Formatos básicos generados sin depender de Quarto.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "General", "ui_order": 5},
    )
    html: HtmlRenderConfig = Field(
        default_factory=HtmlRenderConfig,
        title="HTML",
        description="Config del render HTML básico standalone.",
        json_schema_extra={"ui_widget": "section", "ui_group": "HTML", "ui_order": 1},
    )
    quarto: QuartoRenderConfig = Field(
        default_factory=QuartoRenderConfig,
        title="Quarto",
        description="Config de formatos derivados mediante Quarto.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Quarto", "ui_order": 1},
    )
    ai: AiNarrationConfig = Field(
        default_factory=AiNarrationConfig,
        title="Narrativa IA",
        description="Config de enriquecimiento narrativo opcional mediante IA.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Narrativa IA", "ui_order": 1},
    )
    sections: SectionPolicyConfig = Field(
        default_factory=SectionPolicyConfig,
        title="Secciones",
        description="Config de secciones obligatorias, faltantes y límites de tablas.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Secciones", "ui_order": 1},
    )
