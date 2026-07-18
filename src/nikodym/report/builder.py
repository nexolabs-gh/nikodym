"""Constructor lógico del **documento** del informe (SDD-26 §4/§6/§7; mejora 1.1).

``ReportBuilder`` recolecta las cards y artefactos tabulares ya publicados por un ``Study`` y arma
un :class:`~nikodym.report.results.ReportInputBundle`. Lo que ensambla no es un volcado del
pipeline: es un documento —portada, índice, resumen ejecutivo, capítulos y anexos— cuya estructura
declara :mod:`nikodym.report.document`, la **única** fuente de orden y títulos.

Los ocho dominios del pipeline dejan de ser secciones de primer nivel y pasan a ser subsecciones:
las que sostienen el juicio de validación, en *Resultados*; el detalle completo (todas las tablas y
todos los payloads), en los *Anexos B y C*. **Nada de lo que antes se reportaba desaparece**: el
dump se degrada a anexo, que es lo que hace auditable al informe.

El módulo sigue siendo *pass-through*: no recalcula ni normaliza números de dominios aguas arriba.
Sólo toma snapshots defensivos de estructuras mutables, especialmente ``DataFrame``.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import copy
import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn, TypeAlias, cast

from pydantic import BaseModel

from nikodym.report import prose
from nikodym.report._manifest import REPORT_TEMPLATE_VERSION, REPORT_TITLE, html_report_id
from nikodym.report.config import ReportConfig
from nikodym.report.document import (
    APPENDIX_LINEAGE_ID,
    APPENDIX_PARAMETER_DOMAINS,
    APPENDIX_PARAMETERS_ID,
    APPENDIX_TABLES_ID,
    CANONICAL_SECTION_ORDER,
    CHAPTER_SPECS,
    CONTEXT_DOMAINS,
    DOMAIN_TITLES,
    IFRS9_DOMAINS,
    METHODOLOGY_STEPS,
    PIPELINE_DOMAINS,
    PROVISION_DOMAINS,
    RESULT_DOMAINS,
    VALIDATION_FAMILIES,
    ChapterSpec,
    domain_section_id,
)
from nikodym.report.exceptions import ReportInputError
from nikodym.report.results import (
    PlaceholderBlock,
    ReportInputBundle,
    ReportManifest,
    ReportOutputFormat,
    ReportSection,
    ReportSectionStatus,
)

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.lineage import LineageBundle
    from nikodym.core.study import Study

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any
    LineageBundle: TypeAlias = Any
    Study: TypeAlias = Any

__all__ = ["CANONICAL_SECTION_ORDER", "ReportBuilder"]

_CARD_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (
    # Población real (SDD-02). Opcional: no entra en ``ReportStep.requires``.
    ("data", "data_card"),
    ("eda", "eda_card"),
    ("binning", "binning_card"),
    ("selection", "selection_card"),
    ("model", "model_card"),
    ("scorecard", "card"),
    ("calibration", "card"),
    ("performance", "card"),
    ("stability", "card"),
    # Provisiones. Se RECOLECTAN si el dominio corrió, pero NO se exigen: no están en el default
    # de `SectionPolicyConfig.required_sections`, así que una corrida de scorecard no las echa en
    # falta. Su presencia activa el capítulo condicional (`ChapterSpec.requires_domain`).
    ("provisioning_cmf", "card"),
    ("provisioning_internal", "card"),
    ("provisioning", "card"),
    # IFRS 9 / ECL (SDD-16). Se RECOLECTA si el dominio corrió; no se exige (no está en las
    # ``required_sections`` por defecto). Su presencia activa el capítulo condicional ``ifrs9``
    # (``ChapterSpec.requires_domain='provisioning_ifrs9'``), igual que provisiones.
    ("provisioning_ifrs9", "card"),
    # Survival (SDD-18): no genera capítulo propio; su card alimenta la prosa del capítulo IFRS 9
    # (el mecanismo PD→lifetime se describe desde lo que la corrida realmente ajustó, no desde
    # supuestos del preset). Opcional como las demás cards de negocio.
    ("survival", "card"),
    # Resumen de validación formal (SDD-22). El capítulo se gatea por el ``result`` atómico,
    # no por esta card aislada; ambos son opcionales para report.
    ("validation", "card"),
)
_CARD_KEY_BY_DOMAIN: Final[dict[str, str]] = dict(_CARD_ARTIFACTS)
_RESULT_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (("validation", "result"),)
_TABLE_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (
    ("eda", "default_rate"),
    ("eda", "stability"),
    ("eda", "univariate"),
    ("eda", "quality"),
    ("binning", "tables"),
    ("binning", "summary"),
    ("binning", "woe_frame"),
    ("selection", "selected_woe_frame"),
    ("selection", "selection_table"),
    ("selection", "correlation_matrix"),
    ("selection", "vif_table"),
    ("selection", "stability_table"),
    ("model", "coefficients"),
    ("model", "stepwise_trace"),
    ("model", "fit_statistics"),
    ("model", "raw_pd_frame"),
    ("scorecard", "scorecard"),
    ("scorecard", "score"),
    ("calibration", "parameters"),
    ("calibration", "calibrated_pd_frame"),
    ("performance", "performance_table"),
    ("performance", "discriminant_metrics"),
    ("stability", "psi_table"),
    ("stability", "stability_metrics"),
    # Provisiones: solo los frames AGREGADOS (SDD-28 §6.4). NUNCA ``detail`` (6.000 filas por
    # operación): no cabe en el cuerpo de un informe ni en el anexo.
    ("provisioning", "comparison"),
    ("provisioning_cmf", "summary"),
    ("provisioning_internal", "groups"),
    # IFRS 9: solo el ``summary`` agregado por stage (3 filas). NUNCA ``detail``/``staging``
    # (una fila por operación): mismo criterio que provisiones.
    ("provisioning_ifrs9", "summary"),
)
_FIGURE_ARTIFACTS: Final[tuple[tuple[str, str], ...]] = (("eda", "figures"),)
_VALID_OUTPUT_FORMATS: Final[frozenset[str]] = frozenset(
    {"html", "pdf", "md", "docx", "csv", "xlsx"}
)
# La fuente editable se escribe como ``.qmd`` (Quarto), pero su formato lógico es ``md``.
_SUFFIX_ALIASES: Final[dict[str, str]] = {"qmd": "md"}
# Secciones de config que la Metodología necesita para describir lo que realmente se ejecutó.
# F3/F4 requieren los parámetros regulatorios que realmente ejecutan; no se agregan a
# ``PIPELINE_DOMAINS`` porque esa constante conserva la semántica del pipeline scorecard F1.
_PARAM_DOMAINS: Final[tuple[str, ...]] = (
    "data",
    *PIPELINE_DOMAINS,
    "survival",
    "markov",
    "forward",
    *PROVISION_DOMAINS,
    "provisioning_ifrs9",
    "validation",
)


class ReportBuilder:
    """Ensambla el documento lógico desde cards/results; no renderiza."""

    def __init__(self, config: ReportConfig) -> None:
        """Construye el builder desde una ``ReportConfig`` validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: ReportConfig) -> ReportBuilder:
        """Construye ``ReportBuilder`` desde ``NikodymConfig.report``."""
        return cls(cfg)

    def collect(self, study: Study) -> ReportInputBundle:
        """Recolecta cards, tablas, figuras, parámetros y lineage en un snapshot defensivo."""
        lineage = _lineage_from_study(study)
        results = self._collect_results(study)
        cards = self._collect_cards(study)
        _merge_atomic_result_cards(cards, results)
        tables = self._collect_tables(study)
        tables.update(_data_card_tables(cards))
        tables.update(_atomic_result_tables(results))
        tables.update(_extract_card_dataframes(cards))
        figures = self._collect_figures(study)
        pipeline_params = _collect_pipeline_params(study)
        missing_sections = self._missing_required_sections(cards)
        bundle = ReportInputBundle(
            lineage=lineage,
            cards=cards,
            results=results,
            tables=tables,
            figures=figures,
            sections=(),
            missing_sections=missing_sections,
            pipeline_params=pipeline_params,
        )
        return bundle.model_copy(update={"sections": self.build_sections(bundle)})

    def build_sections(self, bundle: ReportInputBundle) -> tuple[ReportSection, ...]:
        """Construye el documento: capítulos, subsecciones de dominio y anexos.

        El orden y los títulos salen de :data:`~nikodym.report.document.CHAPTER_SPECS`; la
        numeración (1-6 para capítulos, A/B/C para anexos) se deriva aquí, de modo que omitir un
        dominio no deja huecos en el índice.

        Un capítulo con ``requires_domain`` informado es **condicional**: se omite entero si ese
        dominio no publicó card. La numeración se reajusta sola, porque se deriva de los capítulos
        efectivamente emitidos y no de la posición en ``CHAPTER_SPECS``.
        """
        sections: list[ReportSection] = []
        chapter_number = 0
        appendix_index = 0
        for spec in CHAPTER_SPECS:
            if spec.requires_domain and spec.requires_domain not in bundle.cards:
                continue  # capítulo condicional: el dominio no corrió ⇒ no existe el capítulo
            if spec.requires_result and spec.requires_result not in bundle.results:
                continue  # capítulo condicional: falta el oracle agregado ⇒ no se emite
            if spec.requires_any_domain and not any(
                domain in bundle.cards for domain in spec.requires_any_domain
            ):
                continue  # condicional any-of: ninguno de sus dominios corrió ⇒ sin capítulo
            if spec.numbered:
                chapter_number += 1
                number = str(chapter_number)
            elif spec.kind == "appendix":
                number = chr(ord("A") + appendix_index)
                appendix_index += 1
            else:
                number = ""
            sections.append(self._chapter_section(spec, bundle, number))
            sections.extend(self._subsections(spec, bundle, number))
        return tuple(sections)

    def _chapter_section(
        self,
        spec: ChapterSpec,
        bundle: ReportInputBundle,
        number: str,
    ) -> ReportSection:
        """Construye el capítulo de primer nivel con su prosa y su bloque por completar."""
        payload: dict[str, Any] = {}
        if spec.id == APPENDIX_LINEAGE_ID:
            payload = _copy_mapping(cast(Mapping[Any, Any], bundle.lineage.model_dump(mode="json")))
        elif spec.id == "limitations":
            payload = {
                "determinism_caveats": tuple(bundle.lineage.determinism_caveats),
                "missing_sections": bundle.missing_sections,
            }
        elif spec.id == APPENDIX_TABLES_ID:
            payload = {
                "table_keys": tuple(bundle.tables),
                "figure_keys": tuple(bundle.figures),
            }
        return ReportSection(
            id=spec.id,
            title=spec.title,
            status="included",
            source_domain="report",
            source_key=spec.id,
            payload=payload,
            metric_sections={},
            kind=spec.kind,
            level=1,
            number=number,
            body=_chapter_body(spec.id, bundle),
            placeholder=_placeholder(spec, self.config),
        )

    def _subsections(
        self,
        spec: ChapterSpec,
        bundle: ReportInputBundle,
        number: str,
    ) -> tuple[ReportSection, ...]:
        """Construye las subsecciones de dominio que cuelgan de un capítulo."""
        if spec.id == "context":
            return self._domain_subsections(spec.id, CONTEXT_DOMAINS, bundle, number, kind="data")
        if spec.id == "methodology":
            return self._methodology_subsections(bundle, number)
        if spec.id == "results":
            return self._domain_subsections(spec.id, RESULT_DOMAINS, bundle, number, kind="data")
        if spec.id == "validation":
            return self._validation_subsections(bundle, number)
        if spec.id == "provisions":
            return self._domain_subsections(spec.id, PROVISION_DOMAINS, bundle, number, kind="data")
        if spec.id == "ifrs9":
            return self._domain_subsections(spec.id, IFRS9_DOMAINS, bundle, number, kind="data")
        if spec.id == APPENDIX_PARAMETERS_ID:
            return self._domain_subsections(
                spec.id,
                APPENDIX_PARAMETER_DOMAINS,
                bundle,
                number,
                kind="appendix",
            )
        return ()

    def _validation_subsections(
        self,
        bundle: ReportInputBundle,
        number: str,
    ) -> tuple[ReportSection, ...]:
        """Proyecta una subsección por familia declarada por el ``ValidationResult`` atómico."""
        card = bundle.cards.get("validation")
        if not isinstance(card, Mapping):
            return ()
        raw_families = card.get("families_run", ())
        families = (
            tuple(str(item) for item in raw_families)
            if isinstance(raw_families, tuple | list)
            else ()
        )
        sections: list[ReportSection] = []
        for family, title in VALIDATION_FAMILIES:
            if family not in families:
                continue
            sections.append(
                ReportSection(
                    id=domain_section_id("validation", family),
                    title=title,
                    status="included",
                    source_domain="validation",
                    source_key="result",
                    payload={},
                    metric_sections={},
                    kind="data",
                    level=2,
                    number=f"{number}.{len(sections) + 1}",
                    body=prose.validation_family_body(bundle, family),
                )
            )
        return tuple(sections)

    def _methodology_subsections(
        self,
        bundle: ReportInputBundle,
        number: str,
    ) -> tuple[ReportSection, ...]:
        """Una subsección por etapa realmente ejecutada, con su prosa de parámetros reales."""
        sections: list[ReportSection] = []
        for step, title in METHODOLOGY_STEPS:
            body = prose.methodology_body(bundle, step)
            if not body:
                continue
            sections.append(
                ReportSection(
                    id=domain_section_id("methodology", step),
                    title=title,
                    status="included",
                    source_domain=step,
                    source_key=_CARD_KEY_BY_DOMAIN.get(step),
                    payload={},
                    metric_sections={},
                    kind="prose",
                    level=2,
                    number=f"{number}.{len(sections) + 1}",
                    body=body,
                )
            )
        return tuple(sections)

    def _domain_subsections(
        self,
        parent_id: str,
        domains: tuple[str, ...],
        bundle: ReportInputBundle,
        number: str,
        *,
        kind: str,
    ) -> tuple[ReportSection, ...]:
        """Construye las subsecciones de dominio de un capítulo aplicando ``missing_policy``."""
        sections: list[ReportSection] = []
        for domain in domains:
            if kind == "appendix" and domain in bundle.pipeline_params:
                # Anexo C documenta todo config efectivo recolectado, incluso si el dominio no
                # publicó card en esta corrida (p. ej. un bloque experimental config-only).
                status: ReportSectionStatus | None = "included"
            else:
                status = self._domain_status(domain, bundle.cards)
            if status is None:
                continue
            # El Anexo C anexa los parámetros de lo que sí corrió; un dominio ausente no tiene
            # parámetros que anexar y ya queda declarado en Limitaciones.
            if status == "missing" and kind == "appendix":
                continue
            sections.append(
                self._domain_section(
                    parent_id=parent_id,
                    domain=domain,
                    status=status,
                    bundle=bundle,
                    number=f"{number}.{len(sections) + 1}",
                    kind=kind,
                )
            )
        return tuple(sections)

    def _domain_status(
        self,
        domain: str,
        cards: Mapping[str, Any],
    ) -> ReportSectionStatus | None:
        """Resuelve si un dominio se publica, se omite o falla, según ``missing_policy``."""
        if domain in cards:
            return "included"
        if domain not in set(self.config.sections.required_sections):
            return None
        if self.config.sections.missing_policy == "error":
            card_key = _CARD_KEY_BY_DOMAIN.get(domain, "<sin contrato de card>")
            raise ReportInputError(
                "Falta una card requerida para construir el reporte: "
                f"dominio='{domain}', clave='{card_key}'. "
                "Ejecute el step aguas arriba o use missing_policy='warn'/'skip' para un "
                "reporte parcial explícito."
            )
        if self.config.sections.missing_policy == "skip":
            return None
        return "missing"

    def _domain_section(
        self,
        *,
        parent_id: str,
        domain: str,
        status: ReportSectionStatus,
        bundle: ReportInputBundle,
        number: str,
        kind: str,
    ) -> ReportSection:
        """Construye una subsección de dominio: datos en el cuerpo, dump completo en el anexo."""
        card_key = _CARD_KEY_BY_DOMAIN.get(domain)
        artifact_name = f"{domain}.{card_key or 'effective_config'}"
        payload: dict[str, Any] = {}
        metric_sections: dict[str, Any] = {}
        if status == "missing":
            payload = {
                "warning": (
                    "Sección requerida ausente; el reporte parcial no inventa números ni "
                    "rellena métricas."
                )
            }
        elif kind == "appendix":
            # Sólo el Anexo C reproduce el payload crudo: el cuerpo lo referencia, no lo repite.
            if domain in bundle.cards:
                payload, metric_sections = _payload_and_metric_sections(
                    _card_to_mapping(bundle.cards[domain], artifact_name),
                    artifact=artifact_name,
                )
            # Cada dominio configurado publica su config efectivo completo junto con la card. No
            # hay dump del config raíz: solo la sección namespaced que realmente alimentó el step.
            effective_config = bundle.pipeline_params.get(domain)
            if isinstance(effective_config, Mapping):
                payload["effective_config"] = _copy_mapping(effective_config)
        return ReportSection(
            id=domain_section_id(parent_id, domain),
            title=DOMAIN_TITLES[domain],
            status=status,
            source_domain=domain,
            source_key=card_key or "effective_config",
            payload=payload,
            metric_sections=metric_sections,
            kind=cast(Any, kind),
            level=2,
            number=number,
            body=prose.results_body(bundle, domain) if kind == "data" else (),
        )

    def build_manifest(self, bundle: ReportInputBundle, *, path: str) -> ReportManifest:
        """Ensambla metadatos pre-render; el renderer completa el ``sha256`` real."""
        output_format = _output_format_from_path(path, self.config)
        return ReportManifest(
            report_id=html_report_id(bundle, self.config),
            title=REPORT_TITLE,
            created_from_lineage_at=bundle.lineage.created_at.isoformat(),
            template_id=self.config.html.template_id,
            template_version=REPORT_TEMPLATE_VERSION,
            output_format=output_format,
            path=path,
            sha256="",
            deterministic=self.config.html.deterministic_ids and not self.config.ai.enabled,
            ai_enabled=self.config.ai.enabled,
            ai_used=False,
            sections=bundle.sections,
        )

    def _collect_cards(self, study: Study) -> dict[str, dict[str, Any]]:
        """Lee las cards canónicas del ``ArtifactStore`` y valida ``metric_sections``."""
        cards: dict[str, dict[str, Any]] = {}
        for domain, key in _CARD_ARTIFACTS:
            if not study.artifacts.has(domain, key):
                continue
            artifact_name = f"{domain}.{key}"
            raw = _card_to_mapping(study.artifacts.get(domain, key), artifact_name)
            _payload_and_metric_sections(raw, artifact=artifact_name)
            cards[domain] = raw
        return cards

    def _collect_results(self, study: Study) -> dict[str, Any]:
        """Recolecta DTOs agregados opcionales usados como oracle atómico por el documento."""
        results: dict[str, Any] = {}
        for domain, key in _RESULT_ARTIFACTS:
            if not study.artifacts.has(domain, key):
                continue
            value = study.artifacts.get(domain, key)
            if not isinstance(value, BaseModel):
                raise ReportInputError(
                    f"El resultado atómico '{domain}.{key}' debe ser un BaseModel; "
                    f"tipo observado={type(value).__name__}."
                )
            results[domain] = _copy_value(value)
        return results

    def _collect_tables(self, study: Study) -> dict[str, DataFrameLike]:
        """Extrae ``DataFrame`` de artefactos tabulares conocidos sin alterar upstream."""
        tables: dict[str, DataFrameLike] = {}
        for domain, key in _TABLE_ARTIFACTS:
            if study.artifacts.has(domain, key):
                tables.update(
                    _extract_dataframes(study.artifacts.get(domain, key), f"{domain}.{key}")
                )
        return tables

    def _collect_figures(self, study: Study) -> dict[str, Any]:
        """Recolecta especificaciones declarativas de figuras publicadas por EDA."""
        figures: dict[str, Any] = {}
        for domain, key in _FIGURE_ARTIFACTS:
            if study.artifacts.has(domain, key):
                figures[f"{domain}.{key}"] = _copy_value(study.artifacts.get(domain, key))
        return figures

    def _missing_required_sections(self, cards: Mapping[str, Any]) -> tuple[str, ...]:
        """Lista los dominios obligatorios ausentes, en el orden del pipeline."""
        required = set(self.config.sections.required_sections)
        return tuple(
            domain for domain in PIPELINE_DOMAINS if domain in required and domain not in cards
        )


def _chapter_body(chapter_id: str, bundle: ReportInputBundle) -> tuple[str, ...]:
    """Prosa determinista del capítulo; los capítulos sin prosa propia devuelven vacío."""
    if chapter_id == "context":
        return prose.context_body(bundle)
    if chapter_id == "methodology":
        return prose.methodology_intro(bundle)
    if chapter_id == "results":
        return prose.results_intro(bundle)
    if chapter_id == "validation":
        return prose.validation_intro(bundle)
    if chapter_id == "provisions":
        return prose.provisions_intro(bundle)
    if chapter_id == "ifrs9":
        return prose.ifrs9_intro(bundle)
    if chapter_id == "conclusions":
        return prose.conclusions_body(bundle)
    if chapter_id == "limitations":
        return prose.limitations_body(bundle)
    if chapter_id == APPENDIX_TABLES_ID:
        return (
            "Este anexo reproduce íntegras todas las tablas que produjo la corrida, incluidas "
            "las que el cuerpo del informe ya mostró. Es la trazabilidad completa: nada de lo "
            "que el motor calculó queda fuera del documento.",
        )
    if chapter_id == APPENDIX_PARAMETERS_ID:
        return (
            "Este anexo reproduce el payload completo de cada etapa: los parámetros efectivos y "
            "las métricas estructuradas tal como las publicó cada step, sin resumir.",
        )
    if chapter_id == APPENDIX_LINEAGE_ID:
        return (
            "La corrida queda identificada por los hashes de configuración y de datos, el commit "
            "del código y la semilla raíz. Con estos cuatro valores el resultado es reproducible.",
        )
    return ()


def _placeholder(spec: ChapterSpec, config: ReportConfig) -> PlaceholderBlock | None:
    """Adjunta el bloque POR COMPLETAR salvo que el config pida el entregable final."""
    if not spec.placeholder_title or config.document.placeholders == "hide":
        return None
    return PlaceholderBlock(
        title=spec.placeholder_title,
        guidance=spec.placeholder_guidance,
    )


def _merge_atomic_result_cards(
    cards: dict[str, dict[str, Any]],
    results: Mapping[str, Any],
) -> None:
    """Usa la card incluida en el DTO atómico y rechaza un snapshot independiente incoherente."""
    result = results.get("validation")
    if result is None:
        return
    atomic_card = getattr(result, "card", None)
    if atomic_card is None:
        raise ReportInputError("validation.result no contiene su card resumen atómica.")
    mapped = _card_to_mapping(atomic_card, "validation.result.card")
    standalone = cards.get("validation")
    if standalone is not None and standalone != mapped:
        raise ReportInputError(
            "validation.card no coincide con validation.result.card; el reporte rechaza una "
            "lectura no atómica de la validación."
        )
    cards["validation"] = mapped


def _data_card_tables(cards: Mapping[str, Mapping[str, Any]]) -> dict[str, DataFrameLike]:
    """Proyecta estados, particiones y exclusiones copiando literales de ``DataCardSection``."""
    card = cards.get("data")
    if card is None:
        return {}
    class_counts = _required_mapping(card, "class_counts", artifact="data.data_card")
    partition_sizes = _required_mapping(card, "partition_sizes", artifact="data.data_card")
    partition_rates = _required_mapping(card, "partition_bad_rates", artifact="data.data_card")
    exclusions = _required_mapping(card, "exclusions_by_reason", artifact="data.data_card")

    states = [
        {"Estado": str(state), "Observaciones": _copy_value(count)}
        for state, count in class_counts.items()
    ]
    partitions = [
        {
            "Partición": str(partition),
            "Observaciones": _copy_value(size),
            "Tasa de incumplimiento": _copy_value(partition_rates.get(partition)),
        }
        for partition, size in partition_sizes.items()
    ]
    exclusion_rows = [
        {"Motivo": str(reason), "Exclusiones": _copy_value(count)}
        for reason, count in exclusions.items()
    ]
    return {
        "data.states": _frame_from_records(states, ("Estado", "Observaciones")),
        "data.partitions": _frame_from_records(
            partitions,
            ("Partición", "Observaciones", "Tasa de incumplimiento"),
        ),
        "data.exclusions": _frame_from_records(exclusion_rows, ("Motivo", "Exclusiones")),
    }


def _atomic_result_tables(results: Mapping[str, Any]) -> dict[str, DataFrameLike]:
    """Copia los frames de las familias corridas desde un único ``ValidationResult``."""
    result = results.get("validation")
    if result is None:
        return {}
    card = getattr(result, "card", None)
    raw_families = getattr(card, "families_run", ())
    families = {str(item) for item in raw_families}
    tables: dict[str, DataFrameLike] = {}
    for family, _ in VALIDATION_FAMILIES:
        if family not in families:
            continue
        frame = getattr(result, family, None)
        if not _is_dataframe_like(frame):
            raise ReportInputError(
                f"validation.result.{family} debe ser un DataFrame del DTO atómico."
            )
        tables[f"validation.{family}"] = cast(DataFrameLike, _copy_value(frame))
    return tables


def _required_mapping(
    card: Mapping[str, Any],
    key: str,
    *,
    artifact: str,
) -> Mapping[Any, Any]:
    value = card.get(key)
    if not isinstance(value, Mapping):
        raise ReportInputError(f"{artifact}.{key} debe ser un mapping literal.")
    return value


def _frame_from_records(
    records: list[dict[str, Any]],
    columns: tuple[str, ...],
) -> DataFrameLike:
    """Construye una tabla de presentación sin importar pandas al cargar ``nikodym.report``."""
    pd = importlib.import_module("pandas")
    return cast(DataFrameLike, pd.DataFrame.from_records(records, columns=columns))


def _collect_pipeline_params(study: Study) -> dict[str, Any]:
    """Snapshot JSON de las secciones de config de cada dominio realmente configurado.

    Es lo que permite a la Metodología describir el binning, la selección o la calibración con sus
    parámetros reales. Un dominio sin config no aparece: la prosa omite lo que no puede afirmar.
    """
    config = getattr(study, "config", None)
    if config is None:
        return {}
    params: dict[str, Any] = {}
    for domain in _PARAM_DOMAINS:
        section = getattr(config, domain, None)
        if section is None:
            continue
        if isinstance(section, BaseModel):
            params[domain] = _copy_mapping(cast(Mapping[Any, Any], section.model_dump(mode="json")))
        elif isinstance(section, Mapping):
            params[domain] = _copy_mapping(section)
    return params


def _lineage_from_study(study: Study) -> LineageBundle:
    lineage = getattr(getattr(study, "run_context", None), "lineage", None)
    if lineage is None:
        try:
            lineage = study.lineage_bundle()
        except Exception as exc:
            raise ReportInputError(
                "El reporte requiere LineageBundle disponible en el Study; ejecute la corrida "
                "o inyecte run_context.lineage antes de construir el bundle."
            ) from exc
    return cast(LineageBundle, _copy_value(lineage))


def _card_to_mapping(value: Any, artifact: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return _copy_mapping(cast(Mapping[Any, Any], value.model_dump(mode="python")))
    if isinstance(value, Mapping):
        return _copy_mapping(value)
    raise ReportInputError(
        f"La card '{artifact}' debe ser un BaseModel o mapping serializable; "
        f"tipo observado={type(value).__name__}."
    )


def _payload_and_metric_sections(
    raw_card: Mapping[str, Any],
    *,
    artifact: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_metric_sections = raw_card.get("metric_sections", {})
    if raw_metric_sections is None:
        metric_sections: dict[str, Any] = {}
    elif isinstance(raw_metric_sections, Mapping):
        metric_sections = _copy_mapping(raw_metric_sections)
    else:
        raise ReportInputError(
            f"metric_sections de '{artifact}' debe ser un mapping JSON-serializable."
        )
    _validate_metric_sections(metric_sections, artifact=artifact)
    payload = {
        key: _payload_value(value, prefix=f"{artifact}.{key}")
        for key, value in raw_card.items()
        if key != "metric_sections"
    }
    return payload, metric_sections


def _validate_metric_sections(metric_sections: Mapping[str, Any], *, artifact: str) -> None:
    try:
        json.dumps(
            metric_sections,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            default=_raise_not_json_serializable,
        )
    except (TypeError, ValueError) as exc:
        raise ReportInputError(
            f"metric_sections de '{artifact}' no es JSON-serializable; "
            "publique métricas estructuradas sin objetos Python opacos ni floats no finitos."
        ) from exc


def _raise_not_json_serializable(value: object) -> NoReturn:
    raise TypeError(f"{type(value).__name__} no es JSON-serializable")


def _extract_dataframes(value: Any, prefix: str) -> dict[str, DataFrameLike]:
    if _is_dataframe_like(value):
        return {prefix: cast(DataFrameLike, _copy_value(value))}
    if isinstance(value, BaseModel):
        return _extract_dataframes(value.model_dump(mode="python"), prefix)
    if isinstance(value, Mapping):
        frames: dict[str, DataFrameLike] = {}
        for raw_key in sorted(value, key=str):
            frames.update(_extract_dataframes(value[raw_key], f"{prefix}.{raw_key}"))
        return frames
    return {}


def _extract_card_dataframes(cards: Mapping[str, Mapping[str, Any]]) -> dict[str, DataFrameLike]:
    frames: dict[str, DataFrameLike] = {}
    for domain, raw_card in cards.items():
        frames.update(_extract_dataframes(raw_card, f"{domain}.{_CARD_KEY_BY_DOMAIN[domain]}"))
    return frames


def _copy_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): _copy_value(item) for key, item in value.items()}


def _payload_value(value: Any, *, prefix: str) -> Any:
    if _is_dataframe_like(value):
        return {"table_ref": prefix}
    if isinstance(value, BaseModel):
        return _payload_value(value.model_dump(mode="python"), prefix=prefix)
    if isinstance(value, Mapping):
        return {
            str(key): _payload_value(item, prefix=f"{prefix}.{key}") for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _payload_value(item, prefix=f"{prefix}.{index}") for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            _payload_value(item, prefix=f"{prefix}.{index}") for index, item in enumerate(value)
        )
    return _copy_value(value)


def _copy_value(value: Any) -> Any:
    if _is_dataframe_like(value):
        return value.copy(deep=True)
    if isinstance(value, BaseModel):
        return value.model_copy(deep=True)
    if isinstance(value, Mapping):
        return {copy.deepcopy(key): _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_value(item) for item in value)
    return copy.deepcopy(value)


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _output_format_from_path(path: str, config: ReportConfig) -> ReportOutputFormat:
    """Deriva el formato del manifest desde la extensión del archivo, con respaldo en el config.

    ``.qmd`` es la extensión de Quarto, pero el formato lógico del manifiesto es ``md``: el archivo
    es Markdown, la extensión sólo dice qué herramienta lo compila.
    """
    suffix = _SUFFIX_ALIASES.get(
        Path(path).suffix.lower().lstrip("."), Path(path).suffix.lower().lstrip(".")
    )
    if suffix in _VALID_OUTPUT_FORMATS:
        return cast(ReportOutputFormat, suffix)
    return config.formats[0] if config.formats else "html"
