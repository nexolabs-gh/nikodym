"""Esquema del documento del informe: **fuente única** de estructura, orden y títulos.

Antes de este módulo, el orden canónico de secciones vivía duplicado en tres sitios
(``builder``, ``renderer`` y ``ai``) y una card del pipeline equivalía a una sección de primer
nivel: el reporte era un volcado del pipeline, no un informe. Aquí se declara el **documento**
—portada, índice, resumen ejecutivo, capítulos 1-6 y anexos A/B/C— y los ocho dominios del
pipeline pasan a ser **subsecciones**: los resultados que un validador lee en el cuerpo, y el
detalle completo (tablas agregadas y payloads) en los anexos.

El principio es que la evidencia **no se pierde**: se ordena. El payload crudo y las tablas
agregadas que el cuerpo no muestra se degradan a anexo. Lo único que sale del documento son las
tablas **por observación** (:data:`PER_OBSERVATION_TABLES`), que no son evidencia sino dataset: se
entregan completas como archivos adjuntos y el anexo dice dónde están.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Literal, Protocol, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict

SectionKind: TypeAlias = Literal["prose", "data", "toc", "appendix"]


class _Identified(Protocol):
    """Sección identificable por ``id``.

    Se tipa por protocolo, y no con ``ReportSection``, porque los DTOs importan **de** este módulo:
    depender de ellos crearía un ciclo. El orden lo define el ``id``, nada más.
    """

    @property
    def id(self) -> str:
        """Identificador lógico de la sección (``results.model``, ``appendix_tables``…)."""


_SectionT = TypeVar("_SectionT", bound=_Identified)

__all__ = [
    "APPENDIX_LINEAGE_ID",
    "APPENDIX_PARAMETERS_ID",
    "APPENDIX_TABLES_ID",
    "CANONICAL_SECTION_ORDER",
    "CHAPTER_SPECS",
    "CONTEXT_DOMAINS",
    "DOMAIN_TITLES",
    "IFRS9_DOMAINS",
    "KEY_TABLES",
    "METHODOLOGY_STEPS",
    "PER_OBSERVATION_TABLES",
    "PIPELINE_DOMAINS",
    "RESULT_DOMAINS",
    "ChapterSpec",
    "domain_section_id",
    "ordered_sections",
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
    "provisioning": "La provisión a constituir — la regla del máximo",
    "provisioning_cmf": "Método estándar de la CMF (Cap. B-1)",
    "provisioning_internal": "Método interno del banco",
    "provisioning_ifrs9": "Pérdida crediticia esperada (ECL) por etapas",
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
# Subsecciones del capítulo CONDICIONAL de provisiones (SDD-28 D5). El orquestador primero (es el
# titular: la provisión a constituir y el sobrecosto del estándar en CLP), luego el desglose de cada
# método. Solo se emite el capítulo si ``provisioning`` corrió (``ChapterSpec.requires_domain``).
PROVISION_DOMAINS: Final[tuple[str, ...]] = (
    "provisioning",
    "provisioning_cmf",
    "provisioning_internal",
)
# Subsección del capítulo CONDICIONAL de IFRS 9 (SDD-16). Un solo dominio: la card del step
# ``provisioning_ifrs9`` trae staging, EAD y ECL reportada. Solo se emite si el dominio corrió.
IFRS9_DOMAINS: Final[tuple[str, ...]] = ("provisioning_ifrs9",)

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
# formarse un juicio. El Anexo de tablas publica el RESTO de las tablas agregadas de la corrida —lo
# que el cuerpo no mostró, no lo que ya mostró—: el cuerpo cura, el anexo completa. Repetir una
# tabla íntegra en dos sitios no añade trazabilidad, añade páginas.
KEY_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "eda": ("eda.default_rate", "eda.quality"),
    "binning": ("binning.summary",),
    "selection": ("selection.selection_table", "selection.vif_table"),
    "model": ("model.coefficients", "model.fit_statistics"),
    "scorecard": ("scorecard.scorecard",),
    "calibration": ("calibration.parameters",),
    "performance": ("performance.discriminant_metrics", "performance.performance_table"),
    "stability": ("stability.stability_metrics", "stability.psi_table"),
    "provisioning": ("provisioning.comparison",),
    "provisioning_cmf": ("provisioning_cmf.summary",),
    "provisioning_internal": ("provisioning_internal.groups",),
    "provisioning_ifrs9": ("provisioning_ifrs9.summary",),
}

# Tablas **por observación**: una fila por crédito/cliente. Son frames del dataset, no resúmenes, y
# NO pertenecen al documento: truncadas no sirven como dato (están incompletas) ni como informe
# (nadie lee 200 filas de puntajes). Salen del cuerpo y de los anexos, y se emiten completas como
# exports de datos (:mod:`nikodym.report.exports`), referenciadas desde el Anexo de tablas.
#
# El criterio es la **naturaleza** de la tabla, no su tamaño: una tabla agregada con muchas filas
# (p. ej. el PSI por tramo de score, o el binning de una variable con muchos bins) se queda en el
# documento porque es lo que un validador revisa. Por eso la lista es explícita y no un umbral de
# filas: un umbral expulsaría del informe justo la evidencia que lo sostiene.
PER_OBSERVATION_TABLES: Final[frozenset[str]] = frozenset(
    {
        "binning.woe_frame",
        "calibration.calibrated_pd_frame",
        "model.raw_pd_frame",
        "scorecard.score",
        "selection.selected_woe_frame",
    }
)

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
    "provisioning.comparison": "Comparación estándar vs. interno y regla del máximo",
    "provisioning_cmf.summary": "Provisión estándar por categoría CMF",
    "provisioning_internal.groups": "Provisión interna por grupo homogéneo (banda de score)",
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
    requires_domain: str = ""
    """Dominio del que depende el capítulo. Si está informado y ese dominio **no corrió**, el
    capítulo **no se emite** (y la numeración de los siguientes se reajusta sola).

    Es el mecanismo de los capítulos **condicionales**: un informe de scorecard no debe traer un
    capítulo de provisiones vacío, y un informe con provisiones no debe declarar que no las cubre.
    Vacío (el default) = capítulo incondicional, se emite siempre.
    """


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
    # Capítulo CONDICIONAL (SDD-28 D5): solo se emite si la corrida calculó provisiones. Va tras
    # Resultados —es un resultado de negocio, no una validación del scorecard— y antes de
    # Conclusiones, que pueden referirlo. En una corrida de scorecard no aparece y la numeración se
    # reajusta sola (``build_sections`` deriva los números de los capítulos emitidos).
    ChapterSpec(
        id="provisions",
        title="Provisiones regulatorias",
        kind="prose",
        requires_domain="provisioning",
    ),
    # Capítulo CONDICIONAL de IFRS 9 (SDD-16): solo se emite si la corrida calculó la pérdida
    # crediticia esperada. Misma lógica que ``provisions``: es un resultado de negocio, va tras
    # Resultados y la numeración se reajusta sola cuando no aparece.
    ChapterSpec(
        id="ifrs9",
        title="Provisiones IFRS 9 / ECL",
        kind="prose",
        requires_domain="provisioning_ifrs9",
    ),
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
"""Orden canónico de los capítulos **posibles** del documento.

⚠️ **No es la lista de los capítulos emitidos.** Desde que existen capítulos condicionales
(``ChapterSpec.requires_domain``), un informe concreto emite un **subconjunto** de esta tupla,
preservando el orden relativo. Quien compare contra esta constante debe verificar *subsecuencia*,
no igualdad — un informe de scorecard no trae el capítulo de provisiones, y eso es lo correcto.
"""

_CHAPTER_INDEX: Final[dict[str, int]] = {spec.id: index for index, spec in enumerate(CHAPTER_SPECS)}
# Orden de las subsecciones dentro de cada capítulo que las admite.
_CHILD_ORDER: Final[dict[str, tuple[str, ...]]] = {
    "context": CONTEXT_DOMAINS,
    "methodology": tuple(step for step, _ in METHODOLOGY_STEPS),
    "results": RESULT_DOMAINS,
    "provisions": PROVISION_DOMAINS,
    "ifrs9": IFRS9_DOMAINS,
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


def ordered_sections(sections: Iterable[_SectionT]) -> tuple[_SectionT, ...]:
    """Ordena secciones por la clave canónica del documento.

    Vive aquí —y no en cada renderer— porque el orden del documento es **uno**: el HTML, el
    ``.qmd``, el ``.docx`` y la narrativa IA recorren los capítulos en la misma secuencia. Antes
    había una copia de esta función por consumidor, que es exactamente como se desincronizan.
    """
    return tuple(sorted(sections, key=lambda section: (*section_sort_key(section.id), section.id)))


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
