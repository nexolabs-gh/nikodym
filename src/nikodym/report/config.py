"""Config declarativo de la capa ``report`` (SDD-26 §5).

:class:`ReportConfig` es la sección ``report`` de
:class:`~nikodym.core.config.NikodymConfig`: generación de reportes auditables de scorecard con
HTML básico determinístico por defecto, export tabular opcional, PDF opcional (WeasyPrint) y
narrativa IA opt-in. Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig`
(``extra='forbid'`` y ``frozen=True``); cada campo declara ``title``/``description`` y metadatos
``ui_*`` para que la UI (SDD-23) sea un editor del mismo config. La sección es infraestructura,
por lo que no entra al ``config_hash`` global.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, field_validator

from nikodym.core.config import NikodymBaseConfig

AiProvider = Literal["anthropic", "none"]
BasicReportFormat = Literal["html", "csv", "xlsx", "pdf", "md", "docx"]
MissingPolicy = Literal["error", "warn", "skip"]
PlaceholderPolicy = Literal["show", "hide"]
ReportLanguage = Literal["es"]
ReportTheme = Literal["nikodym", "plain"]
ReportType = Literal["standard"]

# Formatos con una ruta de generación REAL en el motor: los documentos (``html``, ``pdf``, y las
# fuentes editables ``md``/``docx``) y los exports de datos (``csv``/``xlsx``, que entregan las
# tablas por observación completas).
#
# INVARIANTE (test en ``test_report_config.py``): ``BasicReportFormat`` no declara ningún formato
# fuera de este conjunto. El ``Literal`` es lo que ``GET /api/schema`` publica como enum y lo que la
# UI pinta como checkbox, así que un formato declarado y sin motor no es teórico: el usuario lo
# marca y se lleva un ``ValidationError``. El validador de abajo queda como red de seguridad para
# quien amplíe el ``Literal`` sin cablear el motor.
IMPLEMENTED_FORMATS: Final[frozenset[str]] = frozenset({"html", "pdf", "md", "docx", "csv", "xlsx"})

__all__ = [
    "IMPLEMENTED_FORMATS",
    "AiNarrationConfig",
    "DocumentStructureConfig",
    "DocxRenderConfig",
    "HtmlRenderConfig",
    "PdfRenderConfig",
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
    render_charts: bool = Field(
        default=True,
        title="Renderizar gráficos",
        description="True embebe los gráficos SVG deterministas del informe en cada sección.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 6},
    )


class PdfRenderConfig(NikodymBaseConfig):
    """Config del render PDF opcional vía WeasyPrint."""

    enabled: bool = Field(
        default=False,
        title="Activar PDF",
        description=(
            "Solo aplica al uso directo del renderizador PDF. En una corrida, el PDF se activa "
            "incluyendo 'pdf' en `formats`."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "PDF", "ui_order": 1},
    )
    fail_if_unavailable: bool = Field(
        default=False,
        title="Fallar si WeasyPrint no está disponible",
        description="True convierte la ausencia de WeasyPrint en error en vez de fallback a HTML.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "PDF", "ui_order": 2},
    )


class DocxRenderConfig(NikodymBaseConfig):
    """Config del export ``.docx`` opcional (Word) vía ``python-docx``.

    El export se activa incluyendo ``docx`` en ``formats``; aquí solo se decide qué hacer cuando
    la dependencia opcional no está instalada.
    """

    fail_if_unavailable: bool = Field(
        default=False,
        title="Fallar si python-docx no está disponible",
        description=(
            "True convierte la ausencia de python-docx en error; False emite un aviso y omite el "
            ".docx sin tumbar la corrida."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Word", "ui_order": 1},
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
        description="Bloqueado: la narrativa IA nunca recibe datos crudos; solo admite False.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Narrativa IA", "ui_order": 7},
    )
    label_ai_text: bool = Field(
        default=True,
        title="Etiquetar texto generado por IA",
        description="True marca explícitamente los bloques enriquecidos por IA.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Narrativa IA", "ui_order": 8},
    )


class DocumentStructureConfig(NikodymBaseConfig):
    """Metadatos editables de la portada y política de bloques por completar.

    El motor no infiere de qué entidad ni de qué cartera es el modelo: son datos del negocio. Se
    declaran aquí y la portada los imprime; lo que no se declare queda como campo en blanco para
    llenar a mano, nunca como un valor inventado.
    """

    model_name: str = Field(
        default="",
        title="Nombre del modelo",
        description="Nombre del modelo tal como se identifica en el inventario de la entidad.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Documento", "ui_order": 1},
    )
    entity: str = Field(
        default="",
        title="Entidad",
        description="Entidad o institución financiera propietaria del modelo.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Documento", "ui_order": 2},
    )
    portfolio: str = Field(
        default="",
        title="Cartera",
        description="Cartera o producto sobre el que aplica el modelo (p. ej. consumo).",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Documento", "ui_order": 3},
    )
    author: str = Field(
        default="",
        title="Autor",
        description="Área o persona responsable del desarrollo del modelo.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Documento", "ui_order": 4},
    )
    version: str = Field(
        default="",
        title="Versión del informe",
        description="Versión del documento (p. ej. 1.0, borrador para Validación).",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Documento", "ui_order": 5},
    )
    placeholders: PlaceholderPolicy = Field(
        default="show",
        title="Bloques por completar",
        description=(
            "'show' publica los bloques POR COMPLETAR con su guía de redacción; 'hide' los "
            "oculta para la versión final del entregable."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Documento", "ui_order": 6},
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
        title="Secciones obligatorias del scorecard",
        description=(
            "Secciones del scorecard que el informe espera encontrar; qué hacer cuando falta "
            "alguna lo decide `missing_policy`."
        ),
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
        description="Máximo de filas visibles por tabla en el informe renderizado.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Secciones", "ui_order": 4},
    )


class ReportConfig(NikodymBaseConfig):
    """Genera el informe auditable de la corrida y elige sus formatos de salida en `formats`."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema report",
        description="Versión local del schema de report para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: ReportType = Field(
        default="standard",
        title="Tipo de sección report",
        description="Variante de la sección de informe; hoy solo existe la estándar.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    output_dir: str = Field(
        default="reports",
        title="Directorio de salida",
        description="Directorio relativo donde se escriben los artefactos del informe.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "General", "ui_order": 2},
    )
    basename: str = Field(
        default="scorecard_report",
        title="Nombre base",
        description="Nombre base determinístico para los archivos del informe.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "General", "ui_order": 3},
    )
    language: ReportLanguage = Field(
        default="es",
        title="Idioma",
        description="Idioma del informe; hoy solo está disponible el español.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "General", "ui_order": 4},
    )
    formats: tuple[BasicReportFormat, ...] = Field(
        default=("html",),
        title="Formatos del informe",
        description=(
            "Formatos generados por el informe. Documentos: 'html' (siempre), 'pdf' (extra `pdf`, "
            "WeasyPrint + nativas) y las fuentes editables 'md' (Quarto/Markdown, sin extras) y "
            "'docx' (Word, extra `docx`). Exports de datos: 'csv' y 'xlsx' (extra `excel`) "
            "entregan COMPLETAS las tablas por observación, que no viven en el documento. Todo "
            "formato ofrecido aquí tiene motor detrás: el enum no publica opciones que la corrida "
            "no pueda cumplir. Default: solo 'html'."
        ),
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "General", "ui_order": 5},
    )
    document: DocumentStructureConfig = Field(
        default_factory=DocumentStructureConfig,
        title="Documento",
        description="Metadatos de portada y política de bloques por completar del informe.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Documento", "ui_order": 1},
    )
    html: HtmlRenderConfig = Field(
        default_factory=HtmlRenderConfig,
        title="HTML",
        description="Config del render HTML básico standalone.",
        json_schema_extra={"ui_widget": "section", "ui_group": "HTML", "ui_order": 1},
    )
    pdf: PdfRenderConfig = Field(
        default_factory=PdfRenderConfig,
        title="PDF",
        description="Config del PDF opcional del informe mediante WeasyPrint.",
        json_schema_extra={"ui_widget": "section", "ui_group": "PDF", "ui_order": 1},
    )
    docx: DocxRenderConfig = Field(
        default_factory=DocxRenderConfig,
        title="Word",
        description="Config del export .docx opcional del informe mediante python-docx.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Word", "ui_order": 1},
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

    @field_validator("formats")
    @classmethod
    def _rechaza_formatos_no_implementados(
        cls,
        value: tuple[BasicReportFormat, ...],
    ) -> tuple[BasicReportFormat, ...]:
        """Falla ruidosamente ante un formato declarado pero sin ruta de generación real.

        Un formato aceptado por el schema y sin motor detrás produce un reporte silenciosamente
        incompleto: se pide ``xlsx``, la corrida termina "bien" y no hay archivo. El step no puede
        ser más permisivo que el motor, así que el config lo rechaza aquí.

        Hoy ``BasicReportFormat`` ya no declara ningún formato sin motor, así que este validador no
        se dispara con un config válido: es la red de seguridad para quien amplíe el ``Literal``
        sin cablear la generación. La primera línea de defensa es el propio ``Literal``, porque es
        él —no este validador— quien decide qué opciones ve el usuario en la UI.
        """
        pendientes = tuple(dict.fromkeys(item for item in value if item not in IMPLEMENTED_FORMATS))
        if pendientes:
            implementados = ", ".join(sorted(IMPLEMENTED_FORMATS))
            raise ValueError(
                f"Formato de reporte no implementado: {', '.join(pendientes)}. La capa report "
                f"genera: {implementados} ('pdf' requiere el extra `pdf`, 'docx' el extra `docx` y "
                "'xlsx' el extra `excel`). El export 'json' sigue en el roadmap; declararlo hoy no "
                "produciría archivo alguno."
            )
        return value
