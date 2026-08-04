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
    "XlsxExportConfig",
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
        title="Incrustar estilos e imágenes",
        description=(
            "Guarda los estilos y las figuras DENTRO del archivo HTML, para que se pueda abrir o "
            "enviar por correo sin carpetas adjuntas."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 3},
    )
    include_interactive_charts: bool = Field(
        default=False,
        title="Gráficos interactivos",
        description=(
            "Añade gráficos interactivos cuando la librería que los dibuja está instalada. Si no "
            "está, el informe sale igual con los gráficos fijos."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 4},
    )
    deterministic_ids: bool = Field(
        default=True,
        title="Identificadores reproducibles",
        description=(
            "Nombra las secciones y las figuras a partir de su contenido, sin azar ni la hora del "
            "reloj: dos corridas iguales producen un archivo idéntico."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 5},
    )
    render_charts: bool = Field(
        default=True,
        title="Renderizar gráficos",
        description="Dibuja los gráficos del informe dentro de cada sección.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "HTML", "ui_order": 6},
    )


class PdfRenderConfig(NikodymBaseConfig):
    """Config del render PDF opcional vía WeasyPrint."""

    enabled: bool = Field(
        default=False,
        title="Activar PDF",
        description=(
            "Solo aplica al uso directo del renderizador PDF. En una corrida, el PDF se activa "
            "marcándolo en «Formatos del informe»."
        ),
        # `hidden`: en una corrida este interruptor NO gobierna nada —la fuente de verdad es
        # `formats`—, así que en el formulario sería un control encendido que no hace nada. Sigue
        # siendo editable por código, donde sí tiene efecto con `PdfReportRenderer` directo.
        json_schema_extra={"ui_widget": "hidden", "ui_group": "PDF", "ui_order": 1},
    )
    fail_if_unavailable: bool = Field(
        default=False,
        title="Detener la corrida si el PDF no se puede generar",
        description=(
            "Si el motor de PDF no está instalado en el sistema: activado detiene la corrida; "
            "apagado deja un aviso y entrega el informe en los demás formatos."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "PDF", "ui_order": 2},
    )


class DocxRenderConfig(NikodymBaseConfig):
    """Config del export ``.docx`` opcional (Word) vía ``python-docx``.

    El export se activa incluyendo ``docx`` en ``formats``; aquí solo se decide qué hacer cuando
    la dependencia opcional no está instalada.
    """

    fail_if_unavailable: bool = Field(
        default=False,
        title="Detener la corrida si el Word no se puede generar",
        description=(
            "Si falta la librería que escribe el .docx: activado detiene la corrida; apagado deja "
            "un aviso y entrega el informe en los demás formatos."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Word", "ui_order": 1},
    )


class XlsxExportConfig(NikodymBaseConfig):
    """Config del export ``.xlsx`` opcional (planilla) vía ``openpyxl``.

    Gemelo de :class:`DocxRenderConfig`: el export se activa incluyendo ``xlsx`` en ``formats``, y
    aquí sólo se decide qué hacer cuando la dependencia opcional no está instalada. Hasta que este
    interruptor existió, ``xlsx`` era el único formato **sin** degradación: la falta de ``openpyxl``
    no dejaba sin planilla, dejaba sin informe.
    """

    fail_if_unavailable: bool = Field(
        default=False,
        title="Detener la corrida si la planilla no se puede generar",
        description=(
            "Si falta la librería que escribe el .xlsx: activado detiene la corrida; apagado deja "
            "un aviso y entrega el informe en los demás formatos."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Planilla", "ui_order": 1},
    )


class AiNarrationConfig(NikodymBaseConfig):
    """Config de la narrativa IA opcional y aislada de los números."""

    enabled: bool = Field(
        default=False,
        title="Activar narrativa IA",
        description=(
            "Deja que un proveedor de IA redacte texto de apoyo. Los números NO los toca: el "
            "cálculo y las tablas son siempre del motor."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Narrativa IA", "ui_order": 1},
    )
    provider: AiProvider = Field(
        default="none",
        title="Proveedor IA",
        description=(
            "Quién redacta el texto de apoyo. Con «none» el informe se escribe sin salir a la red."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Narrativa IA", "ui_order": 2},
    )
    model: str | None = Field(
        default=None,
        title="Modelo IA",
        description=(
            "Modelo a usar. Si se deja vacío, se usa el que el proveedor traiga por defecto."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Narrativa IA", "ui_order": 3},
    )
    api_key_env: str = Field(
        default="ANTHROPIC_API_KEY",
        title="Variable de entorno con la credencial",
        description=(
            "Nombre de la variable de entorno donde está la credencial del proveedor. La "
            "credencial nunca se escribe en el config."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Narrativa IA", "ui_order": 4},
    )
    timeout_seconds: float = Field(
        default=20.0,
        ge=1.0,
        le=120.0,
        title="Espera máxima por respuesta (segundos)",
        description="Cuánto se espera una respuesta del proveedor antes de seguir sin ella.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Narrativa IA", "ui_order": 5},
    )
    max_input_tokens: int = Field(
        default=12_000,
        ge=1_000,
        title="Máximo de tokens de entrada",
        description=(
            "Tope de tamaño del texto que se le envía al proveedor, ya depurado de datos crudos."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Narrativa IA", "ui_order": 6},
    )
    send_raw_data: Literal[False] = Field(
        default=False,
        title="Enviar datos crudos",
        description="Bloqueado: la narrativa IA nunca recibe datos crudos.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Narrativa IA", "ui_order": 7},
    )
    label_ai_text: bool = Field(
        default=True,
        title="Etiquetar texto generado por IA",
        description="Marca en el informe qué bloques los redactó la IA.",
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
            "Los bloques que firma quien valida: «show» los publica con su guía de redacción, "
            "«hide» los oculta para la versión final del entregable."
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
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Secciones",
            "ui_order": 1,
            # `not_a_column`: estos nombres son SECCIONES del informe (`binning`, `model`, …), no
            # columnas del dataset. Declararlo importa para el formulario: sin rol, el multiselect
            # se quedaba sin opciones y pintaba sus ocho valores de fábrica en rojo con «(no está
            # en el dataset)» —una falsedad sobre un config válido—. Y no amplía el preflight:
            # `dataset_check.py` hace `continue` sobre este rol.
            "column_role": "not_a_column",
        },
    )
    missing_policy: MissingPolicy = Field(
        default="error",
        title="Política de sección ausente",
        description=(
            # ⚠️ Los literales van tal cual los pinta el selector (`error`, `warn`, `skip`): las
            # opciones se muestran crudas, así que nombrar un «warning» que no existe manda al
            # usuario a buscar algo que no está. Reincidencia del defecto de `stability`.
            "Qué hacer si el informe no encuentra una de esas secciones: «error» detiene la "
            "corrida, «warn» deja un aviso y sigue, «skip» la omite en silencio."
        ),
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
            # ⚠️ Los literales van tal cual los pinta el multiselect. Y `csv`/`xlsx` se declaran
            # como lo que son —archivos en el directorio de salida, sin botón de descarga en la
            # interfaz—, porque exponer este campo en el formulario convirtió esa diferencia en algo
            # que el usuario puede provocar con un click (auditoría previa a 1.10.0).
            "Qué se genera. Documentos del informe: «html» (siempre disponible), «pdf» (exige el "
            "motor de PDF instalado en el sistema) y las fuentes editables «md» (Quarto) y «docx» "
            "(Word). Y dos exports de datos, «csv» y «xlsx», que entregan COMPLETAS las tablas por "
            "observación que no caben en el documento: **quedan como archivos en el directorio de "
            "salida**, no entre los botones de descarga. Por defecto sale solo «html»."
        ),
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "General", "ui_order": 5},
    )
    document: DocumentStructureConfig = Field(
        default_factory=DocumentStructureConfig,
        title="Portada y bloques por completar",
        description=(
            "De qué entidad y de qué cartera es el modelo, quién lo desarrolló y con qué versión: "
            "los datos que el motor no puede inferir y que imprime en la primera página."
        ),
        json_schema_extra={"ui_widget": "section", "ui_group": "Documento", "ui_order": 1},
    )
    html: HtmlRenderConfig = Field(
        default_factory=HtmlRenderConfig,
        title="Opciones del HTML",
        description="Cómo se arma el HTML, que es el formato que sale siempre.",
        json_schema_extra={"ui_widget": "section", "ui_group": "HTML", "ui_order": 1},
    )
    pdf: PdfRenderConfig = Field(
        default_factory=PdfRenderConfig,
        title="Opciones del PDF",
        description="Qué hacer si el motor de PDF no está instalado en el sistema.",
        json_schema_extra={"ui_widget": "section", "ui_group": "PDF", "ui_order": 1},
    )
    docx: DocxRenderConfig = Field(
        default_factory=DocxRenderConfig,
        title="Opciones del Word",
        description="Qué hacer si falta la librería que escribe el .docx.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Word", "ui_order": 1},
    )
    xlsx: XlsxExportConfig = Field(
        default_factory=XlsxExportConfig,
        title="Opciones de la planilla",
        description="Qué hacer si falta la librería que escribe el .xlsx.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Planilla", "ui_order": 1},
    )
    ai: AiNarrationConfig = Field(
        default_factory=AiNarrationConfig,
        title="Texto de apoyo con IA",
        description="Redacción opcional asistida. Nunca toca los números ni las tablas.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Narrativa IA", "ui_order": 1},
    )
    sections: SectionPolicyConfig = Field(
        default_factory=SectionPolicyConfig,
        title="Capítulos exigidos",
        description="Qué capítulos espera encontrar el informe y qué hacer si falta alguno.",
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
