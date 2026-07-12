"""Esquema del documento del informe: **fuente única** de estructura, orden y títulos.

Antes de este módulo, el orden canónico de secciones vivía duplicado en tres sitios
(``builder``, ``renderer`` y ``ai``) y una card del pipeline equivalía a una sección de primer
nivel: el reporte era un volcado del pipeline, no un informe. Aquí se declara el **documento**
—portada, índice, resumen ejecutivo, capítulos 1-6 y anexos A/B/C— y los ocho dominios del
pipeline pasan a ser **subsecciones**: los resultados que un validador lee en el cuerpo, y el
detalle completo (tablas crudas y payloads) en los anexos.

El principio es que el dump **no se pierde**: se degrada a anexo. Nada de lo que hoy se reporta
desaparece; cambia de lugar.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

SectionKind: TypeAlias = Literal["prose", "data", "toc", "appendix"]

__all__ = [
    "APPENDIX_LINEAGE_ID",
    "APPENDIX_PARAMETERS_ID",
    "APPENDIX_TABLES_ID",
    "CANONICAL_SECTION_ORDER",
    "CHAPTER_SPECS",
    "CONTEXT_DOMAINS",
    "DOMAIN_TITLES",
    "KEY_TABLES",
    "METHODOLOGY_STEPS",
    "PIPELINE_DOMAINS",
    "RESULT_DOMAINS",
    "ChapterSpec",
    "domain_section_id",
    "section_sort_key",
    "table_title",
]

# Los ocho dominios del pipeline scorecard F1, en el orden en que se ejecutan.
PIPELINE_DOMAINS: Final[tuple[str, ...]] = (
    "eda",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
)

DOMAIN_TITLES: Final[dict[str, str]] = {
    "eda": "Población y calidad de datos",
    "binning": "Binning WoE y poder predictivo",
    "selection": "Selección de variables",
    "model": "Modelo PD",
    "scorecard": "Scorecard",
    "calibration": "Calibración",
    "performance": "Desempeño y discriminación",
    "stability": "Estabilidad",
}

# Dominios que alimentan el capítulo de Contexto (población) y los de Resultados (el cuerpo).
CONTEXT_DOMAINS: Final[tuple[str, ...]] = ("eda",)
RESULT_DOMAINS: Final[tuple[str, ...]] = (
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
)

APPENDIX_LINEAGE_ID: Final = "appendix_lineage"
APPENDIX_TABLES_ID: Final = "appendix_tables"
APPENDIX_PARAMETERS_ID: Final = "appendix_parameters"

# Etapas que describe el capítulo de Metodología, en el orden en que ocurrieron. ``data`` no publica
# card (es config puro), pero su tratamiento es parte del procedimiento y debe quedar escrito.
METHODOLOGY_STEPS: Final[tuple[tuple[str, str], ...]] = (
    ("data", "Tratamiento de datos y particiones"),
    ("binning", "Binning WoE"),
    ("selection", "Selección de variables"),
    ("model", "Estimación del modelo PD"),
    ("scorecard", "Escalado del scorecard"),
    ("calibration", "Calibración de la PD"),
)

# Tablas que el CUERPO del informe muestra por dominio: las que un validador necesita leer para
# formarse un juicio. El resto (y también estas) siguen íntegras en el Anexo B, que publica TODAS
# las tablas del bundle: el cuerpo cura, el anexo no pierde nada.
KEY_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "eda": ("eda.default_rate", "eda.quality"),
    "binning": ("binning.summary",),
    "selection": ("selection.selection_table", "selection.vif_table"),
    "model": ("model.coefficients", "model.fit_statistics"),
    "scorecard": ("scorecard.scorecard",),
    "calibration": ("calibration.parameters",),
    "performance": ("performance.discriminant_metrics", "performance.performance_table"),
    "stability": ("stability.stability_metrics", "stability.psi_table"),
}

# Títulos legibles por artefacto tabular: el informe habla de "Coeficientes del modelo PD", no de
# `model.coefficients`. Las claves dinámicas (una tabla por variable) se resuelven en `table_title`.
_TABLE_TITLES: Final[dict[str, str]] = {
    "eda.default_rate": "Tasa de incumplimiento observada",
    "eda.stability": "Estabilidad temporal de las variables (EDA)",
    "eda.univariate": "Análisis univariado de variables candidatas",
    "eda.quality": "Calidad de datos por variable",
    "binning.summary": "Resumen de binning — IV por variable",
    "binning.woe_frame": "Dataset transformado a WoE",
    "selection.selection_table": "Criterios de selección por variable",
    "selection.correlation_matrix": "Matriz de correlación entre variables",
    "selection.vif_table": "Factor de inflación de varianza (VIF)",
    "selection.stability_table": "Estabilidad de las variables candidatas",
    "selection.selected_woe_frame": "Dataset WoE de las variables seleccionadas",
    "model.coefficients": "Coeficientes del modelo PD",
    "model.stepwise_trace": "Traza del procedimiento stepwise",
    "model.fit_statistics": "Estadísticos de ajuste del modelo",
    "model.raw_pd_frame": "PD sin calibrar por observación",
    "scorecard.scorecard": "Scorecard — puntajes por atributo",
    "scorecard.score": "Puntaje por observación",
    "calibration.parameters": "Parámetros de la calibración",
    "calibration.calibrated_pd_frame": "PD calibrada por observación",
    "performance.performance_table": "Desempeño por decil de score",
    "performance.discriminant_metrics": "Métricas de discriminación por partición",
    "stability.psi_table": "PSI por tramo de score",
    "stability.stability_metrics": "Métricas de estabilidad (PSI/CSI)",
}
_BINNING_TABLE_PREFIX: Final = "binning.tables."


class ChapterSpec(BaseModel):
    """Capítulo declarado del documento: identidad, tipo de bloque y guía de placeholder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    kind: SectionKind
    numbered: bool = True
    placeholder_title: str = ""
    placeholder_guidance: tuple[str, ...] = ()


# El documento. Portada y resumen ejecutivo los emite la plantilla (no son secciones lógicas: la
# portada son metadatos y el resumen es la vista de las métricas clave). Todo lo demás es sección.
CHAPTER_SPECS: Final[tuple[ChapterSpec, ...]] = (
    ChapterSpec(id="toc", title="Índice", kind="toc", numbered=False),
    ChapterSpec(
        id="introduction",
        title="Introducción",
        kind="prose",
        placeholder_title="Introducción",
        placeholder_guidance=(
            "Declara el propósito del informe y qué decisión habilita: ¿es una validación "
            "inicial previa a la puesta en producción, una revisión periódica o un "
            "recalibrado?",
            "Delimita el alcance (qué modelo y qué cartera cubre, qué queda fuera) e "
            "identifica la audiencia: Validación independiente, Comité de Riesgo, regulador.",
        ),
    ),
    ChapterSpec(
        id="context",
        title="Contexto del modelo y de la cartera",
        kind="prose",
        placeholder_title="Contexto del modelo",
        placeholder_guidance=(
            "Describe la cartera sobre la que se construyó el modelo: producto, segmento, "
            "volumen y período.",
            "Explicita la definición de incumplimiento utilizada (p. ej. 90+ días de mora) y "
            "por qué; declara las exclusiones aplicadas a la población y su justificación.",
        ),
    ),
    ChapterSpec(id="methodology", title="Metodología", kind="prose"),
    ChapterSpec(id="results", title="Resultados", kind="prose"),
    ChapterSpec(
        id="conclusions",
        title="Conclusiones y recomendación",
        kind="prose",
        placeholder_title="Conclusiones y recomendación",
        placeholder_guidance=(
            "Emite el juicio: ¿el modelo es apto para el uso previsto? La recomendación "
            "(aprobar, aprobar con observaciones o rechazar) la firma un humano, no el motor.",
            "Enumera las observaciones y condiciones de uso, con responsable y plazo para cada "
            "una, y fija la fecha de la próxima revisión.",
        ),
    ),
    ChapterSpec(id="limitations", title="Limitaciones y supuestos", kind="prose"),
    # Los anexos se numeran con letras (A/B/C) al construir el documento; el título no repite la
    # palabra "Anexo": la antepone el render, igual que hace con "1", "2"… en los capítulos.
    ChapterSpec(
        id=APPENDIX_LINEAGE_ID,
        title="Lineage y reproducibilidad",
        kind="appendix",
        numbered=False,
    ),
    ChapterSpec(
        id=APPENDIX_TABLES_ID,
        title="Tablas detalladas",
        kind="appendix",
        numbered=False,
    ),
    ChapterSpec(
        id=APPENDIX_PARAMETERS_ID,
        title="Parámetros completos",
        kind="appendix",
        numbered=False,
    ),
)

CANONICAL_SECTION_ORDER: Final[tuple[str, ...]] = tuple(spec.id for spec in CHAPTER_SPECS)

_CHAPTER_INDEX: Final[dict[str, int]] = {spec.id: index for index, spec in enumerate(CHAPTER_SPECS)}
# Orden de las subsecciones dentro de cada capítulo que las admite.
_CHILD_ORDER: Final[dict[str, tuple[str, ...]]] = {
    "context": CONTEXT_DOMAINS,
    "methodology": tuple(step for step, _ in METHODOLOGY_STEPS),
    "results": RESULT_DOMAINS,
    APPENDIX_PARAMETERS_ID: PIPELINE_DOMAINS,
}


def domain_section_id(parent_id: str, domain: str) -> str:
    """Deriva el id estable de una subsección de dominio dentro de su capítulo."""
    return f"{parent_id}.{domain}"


def section_sort_key(section_id: str) -> tuple[int, int]:
    """Clave de orden canónica de una sección: su capítulo y su posición dentro de él.

    Es la **única** definición del orden del documento. Un id desconocido cae al final en vez de
    romper el render: el informe nunca deja de emitirse por una sección inesperada.
    """
    parent, separator, child = section_id.partition(".")
    parent_index = _CHAPTER_INDEX.get(parent, len(CHAPTER_SPECS))
    if not separator:
        return (parent_index, 0)
    children = _CHILD_ORDER.get(parent, ())
    if child in children:
        return (parent_index, children.index(child) + 1)
    return (parent_index, len(children) + 1)


def table_title(key: str) -> str:
    """Traduce la clave interna de una tabla a un título legible por un humano.

    Las claves dinámicas (``binning.tables.<variable>``) nombran una variable del cliente: se
    muestra tal cual, entre comillas, sin inventarle acentos ni traducirla. Una clave desconocida
    degrada a su propio nombre en vez de romper el render.
    """
    if key in _TABLE_TITLES:
        return _TABLE_TITLES[key]
    if key.startswith(_BINNING_TABLE_PREFIX):
        variable = key[len(_BINNING_TABLE_PREFIX) :]
        return f"Tabla de binning WoE — variable «{variable}»"
    return f"Tabla «{key}»"
