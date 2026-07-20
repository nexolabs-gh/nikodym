"""Prosa determinista del informe: Metodología, Resultados y hallazgos (SDD-26; mejora 1.1).

El motor sabe exactamente qué hizo y con qué parámetros, así que puede **redactarlo**: qué solver
resolvió el binning, con cuántos bins y qué monotonía; qué umbrales de IV/VIF/estabilidad filtraron
las variables; cómo se escaló el scorecard (PDO/offset); qué método calibró la PD. Nada de esto es
una frase fija: sale del config real de la corrida (``bundle.pipeline_params``) y de las cards
(``bundle.cards``).

Tres reglas, no negociables porque esto va a un regulador:

1. **Determinista y sin red.** Dos corridas del mismo modelo producen el mismo texto, byte a byte.
   Este módulo no llama al ``AINarrator`` ni a ningún proveedor: la IA sigue siendo opt-in y
   decorativa.
2. **Cero números inventados.** Cada cifra sale de un payload o artefacto real. Si un dato no está,
   la frase se omite o declara la ausencia; jamás se rellena con un supuesto.
3. **No recalcula.** ``report`` es pass-through: la prosa enuncia e interpreta usando las métricas
   y **bandas** que los dominios ya publicaron (``bands_by_partition``, ``bands_by_comparison``,
   ``threshold_flags_by_partition``), nunca derivando métricas nuevas.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from nikodym.methodology import build_ifrs9_methodology_card, methodology_paragraphs
from nikodym.report.document import DOMAIN_TITLES

if TYPE_CHECKING:
    from nikodym.report.results import ReportInputBundle

__all__ = [
    "ExecutiveMetric",
    "ExecutiveView",
    "conclusions_body",
    "context_body",
    "executive_view",
    "ifrs9_intro",
    "limitations_body",
    "methodology_body",
    "methodology_intro",
    "provisions_intro",
    "results_body",
    "results_intro",
    "validation_family_body",
    "validation_intro",
]

_PARTITION_LABELS: Final[dict[str, str]] = {
    "desarrollo": "Desarrollo",
    "holdout": "Holdout",
    "oot": "Fuera de tiempo (OOT)",
}
_COMPARISON_LABELS: Final[dict[str, str]] = {
    "dev_vs_holdout": "Desarrollo vs. Holdout",
    "dev_vs_oot": "Desarrollo vs. OOT",
}
_DISCRIMINANT_BANDS: Final[dict[str, str]] = {
    "ok": "Sin alertas",
    "threshold_flag": "Bajo el umbral configurado",
    "not_evaluable": "No evaluable",
}
_STABILITY_BANDS: Final[dict[str, str]] = {
    "stable": "Estable",
    "review": "Requiere revisión",
    "redevelop": "Requiere redesarrollo",
    "not_evaluable": "No evaluable",
}
_VALIDATION_STATUS_BANDS: Final[dict[str, str]] = {
    "pass": "Pass técnico",
    "warn": "Requiere revisión",
    "fail": "Falla técnica",
}
_VALIDATION_FAMILY_LABELS: Final[dict[str, str]] = {
    "discrimination": "discriminación",
    "calibration": "calibración",
    "stability": "estabilidad",
    "backtesting": "backtesting",
}
_SOLVER_LABELS: Final[dict[str, str]] = {
    "cp": "programación con restricciones (CP)",
    "mip": "programación entera mixta (MIP)",
}
_MONOTONIC_LABELS: Final[dict[str, str]] = {
    "auto": "automática",
    "auto_heuristic": "automática (heurística)",
    "auto_asc_desc": "automática (ascendente o descendente)",
    "ascending": "ascendente",
    "descending": "descendente",
    "concave": "cóncava",
    "convex": "convexa",
    "peak": "con máximo interior",
    "peak_heuristic": "con máximo interior (heurística)",
    "valley": "con mínimo interior",
    "valley_heuristic": "con mínimo interior (heurística)",
}
_CALIBRATION_METHODS: Final[dict[str, str]] = {
    "intercept_offset": "desplazamiento del intercepto (intercept offset)",
    "platt_scaling": "escalamiento de Platt",
    "isotonic": "regresión isotónica",
}
_ANCHOR_SOURCES: Final[dict[str, str]] = {
    "business_input": "un ancla de negocio declarada explícitamente",
    "historical_default_rate": "la tasa de incumplimiento histórica",
    "development_observed": "la tasa de incumplimiento observada en Desarrollo",
    "external_regulatory": "un ancla regulatoria externa",
}
_ANCHOR_KINDS: Final[dict[str, str]] = {
    "through_the_cycle": "a través del ciclo (TTC)",
    "point_in_time": "puntual en el tiempo (PIT)",
}
_ENGINE_LABELS: Final[dict[str, str]] = {
    "logit": "regresión logística (logit)",
    "glm_binomial": "modelo lineal generalizado binomial",
}
_STEPWISE_DIRECTIONS: Final[dict[str, str]] = {
    "none": "sin stepwise: se ajustó con todas las variables seleccionadas",
    "forward": "stepwise hacia adelante",
    "backward": "stepwise hacia atrás",
    "bidirectional": "stepwise bidireccional",
}
_SCORE_DIRECTIONS: Final[dict[str, str]] = {
    "higher_is_lower_risk": "un puntaje más alto indica menor riesgo",
    "higher_is_higher_risk": "un puntaje más alto indica mayor riesgo",
}
_ROUNDING_METHODS: Final[dict[str, str]] = {
    "none": "sin redondeo",
    "nearest_integer": "redondeo al entero más cercano",
    "floor_integer": "redondeo hacia abajo",
    "ceil_integer": "redondeo hacia arriba",
}
_SPECIAL_HANDLING: Final[dict[str, str]] = {
    "separate": "en un bin propio",
    "as_missing": "junto con los faltantes",
}
_DISCRIMINANT_METRIC_LABELS: Final[tuple[tuple[str, str], ...]] = (
    ("auc", "AUC"),
    ("gini", "Gini"),
    ("ks", "KS"),
)
_NOT_AVAILABLE: Final = "No disponible"


class ExecutiveMetric:
    """Fila del semáforo del resumen ejecutivo: una métrica, su alcance y su banda."""

    __slots__ = ("band", "label", "scope", "value")

    def __init__(self, *, label: str, scope: str, value: str, band: str) -> None:
        self.label = label
        self.scope = scope
        self.value = value
        self.band = band


class ExecutiveView:
    """Vista del resumen ejecutivo: métricas clave y las notas que evitan leerlas de más."""

    __slots__ = ("metrics", "notes")

    def __init__(self, *, metrics: tuple[ExecutiveMetric, ...], notes: tuple[str, ...]) -> None:
        self.metrics = metrics
        self.notes = notes


# ────────────────────────────── resumen ejecutivo ──────────────────────────────


def executive_view(bundle: ReportInputBundle) -> ExecutiveView:
    """Arma el semáforo de métricas clave (AUC/KS/Gini y PSI) con la banda que publicó el motor.

    Nunca emite un veredicto: el veredicto lo firma el validador. Y si ``performance`` corrió sin
    umbrales configurados, lo dice: sin umbral no hay alerta posible, y una banda "sin alertas"
    leída como "cumple" sería engañosa.
    """
    metrics: list[ExecutiveMetric] = []
    notes: list[str] = []

    performance = _card(bundle, "performance")
    if performance is not None:
        max_metrics = _mapping(performance.get("max_metrics_by_partition"))
        bands = _mapping(performance.get("bands_by_partition"))
        for partition in _sequence(performance.get("partitions")):
            partition_id = str(partition)
            values = _mapping(max_metrics.get(partition_id))
            band = _DISCRIMINANT_BANDS.get(str(bands.get(partition_id, "")), _NOT_AVAILABLE)
            for key, label in _DISCRIMINANT_METRIC_LABELS:
                metrics.append(
                    ExecutiveMetric(
                        label=label,
                        scope=_partition_label(partition_id),
                        value=_num(values.get(key), decimals=4),
                        band=band,
                    )
                )
        if not _mapping(performance.get("thresholds")):
            notes.append(
                "No se configuraron umbrales de discriminación, de modo que el motor no puede "
                "levantar alertas sobre AUC, Gini ni KS: «sin alertas» significa que no había "
                "umbral contra el cual comparar, no que la métrica sea satisfactoria."
            )

    stability = _card(bundle, "stability")
    if stability is not None:
        max_psi = _mapping(stability.get("max_psi_by_comparison"))
        bands = _mapping(stability.get("bands_by_comparison"))
        for comparison in _sequence(stability.get("comparisons")):
            comparison_id = str(comparison)
            metrics.append(
                ExecutiveMetric(
                    label="PSI del score",
                    scope=_comparison_label(comparison_id),
                    value=_num(max_psi.get(comparison_id), decimals=4),
                    band=_STABILITY_BANDS.get(str(bands.get(comparison_id, "")), _NOT_AVAILABLE),
                )
            )
        stable = _float(stability.get("stable_threshold"))
        review = _float(stability.get("review_threshold"))
        if stable is not None and review is not None:
            notes.append(
                f"Las bandas de PSI usan los umbrales configurados: estable por debajo de "
                f"{_num(stable, decimals=2)} y redesarrollo por sobre {_num(review, decimals=2)}."
            )

    validation = _card(bundle, "validation") if "validation" in bundle.results else None
    if validation is not None:
        n_tests = _int(validation.get("n_tests"))
        n_failed = _int(validation.get("n_failed"))
        status = _text(validation.get("overall_status"))
        model_ref = _text(validation.get("model_ref")) or "Modelo evaluado"
        if n_tests is not None and n_failed is not None:
            metrics.append(
                ExecutiveMetric(
                    label="Estado técnico de validación formal",
                    scope=model_ref,
                    value=(
                        f"{_miles(n_failed)} de {_miles(n_tests)} "
                        f"{_plural(n_tests, 'test', 'tests')} fallidos"
                    ),
                    band=_VALIDATION_STATUS_BANDS.get(status or "", _NOT_AVAILABLE),
                )
            )
        families = tuple(
            _VALIDATION_FAMILY_LABELS.get(str(item), str(item))
            for item in _sequence(validation.get("families_run"))
        )
        if families:
            notes.append(
                "La validación formal ejecutó "
                f"{_enumerar(families)}. Su estado es una síntesis técnica del motor y no "
                "sustituye el veredicto que debe firmar un validador humano."
            )

    # IFRS 9: cifras contables reportadas por el motor (SDD-16). No son bandas de validación
    # —el semáforo no aplica—, pero SON las métricas clave de una corrida ECL: sin ellas el
    # resumen ejecutivo de un informe IFRS 9 quedaría vacío.
    ifrs9 = _card(bundle, "provisioning_ifrs9")
    if ifrs9 is not None:
        ecl = _float(ifrs9.get("total_ecl_reported"))
        ead = _float(ifrs9.get("total_ead"))
        if ecl is not None:
            metrics.append(
                ExecutiveMetric(
                    label="ECL reportada (IFRS 9)",
                    scope="Cartera total",
                    value=_clp(ecl),
                    band="Cifra contable",
                )
            )
        if ead is not None:
            metrics.append(
                ExecutiveMetric(
                    label="Exposición al incumplimiento (EAD)",
                    scope="Cartera total",
                    value=_clp(ead),
                    band="Cifra contable",
                )
            )
        if ecl is not None and ead:
            metrics.append(
                ExecutiveMetric(
                    label="Cobertura ECL / EAD",
                    scope="Cartera total",
                    value=_pct(ecl / ead),
                    band="Cifra contable",
                )
            )
        n_s1 = _int(ifrs9.get("n_stage1"))
        n_s2 = _int(ifrs9.get("n_stage2"))
        n_s3 = _int(ifrs9.get("n_stage3"))
        if n_s1 is not None and n_s2 is not None and n_s3 is not None:
            metrics.append(
                ExecutiveMetric(
                    label="Staging (Stage 1 / 2 / 3)",
                    scope="Operaciones",
                    value=f"{_miles(n_s1)} / {_miles(n_s2)} / {_miles(n_s3)}",
                    band="Cifra contable",
                )
            )
        notes.append(
            "Las cifras IFRS 9 son el cálculo contable que reportó el motor (función "
            "experimental, SDD-16), no bandas de validación: la columna Estado no les aplica "
            "semáforo."
        )

    if not metrics:
        notes.append(
            "Las métricas clave no están disponibles: la corrida no publicó las cards de "
            "desempeño ni de estabilidad. El informe no las sustituye por supuestos."
        )
    return ExecutiveView(metrics=tuple(metrics), notes=tuple(notes))


# ────────────────────────────── contexto ──────────────────────────────


def context_body(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Redacta lo que el motor sí sabe de la población: volumen, incumplimiento y particiones."""
    paragraphs: list[str] = []
    data = _card(bundle, "data")
    eda = _card(bundle, "eda")
    data_params = _params(bundle, "data")

    if data is not None:
        n_rows = _int(data.get("n_rows"))
        n_features = _int(data.get("n_features"))
        bad_rate = _float(data.get("bad_rate"))
        target_col = _text(data.get("target_col"))
        facts: list[str] = []
        if n_rows is not None:
            facts.append(f"{_miles(n_rows)} observaciones")
        if n_features is not None:
            facts.append(f"{_miles(n_features)} variables de entrada")
        if bad_rate is not None:
            facts.append(f"una tasa de incumplimiento de {_pct(bad_rate)}")
        if facts:
            paragraphs.append(
                f"La población procesada contiene {_enumerar(tuple(facts))}. "
                "Los conteos por estado, partición y motivo de exclusión se reproducen "
                "literalmente en las tablas de esta sección."
            )
        if target_col is not None:
            paragraphs.append(f"La columna objetivo publicada por data es «{target_col}».")

    if eda is not None:
        rate = _float(eda.get("overall_default_rate"))
        periods = _int(eda.get("n_periods"))
        columns = _int(eda.get("n_columns_profiled"))
        frases: list[str] = []
        if rate is not None:
            frases.append(
                f"La tasa de incumplimiento observada en la población analizada es de {_pct(rate)}"
            )
        if periods is not None:
            frases.append(
                f"la ventana de análisis abarca {periods} {_plural(periods, 'período', 'períodos')}"
            )
        if columns is not None:
            frases.append(
                f"se perfilaron {columns} {_plural(columns, 'variable', 'variables')} candidatas"
            )
        if frases:
            paragraphs.append(f"{_enumerar(frases)}.")

        flags = _mapping(eda.get("quality_flag_counts"))
        alertas = tuple(
            f"{_int(count)} {_quality_label(str(flag))}"
            for flag, count in sorted(flags.items(), key=lambda item: str(item[0]))
            if _int(count)
        )
        if alertas:
            paragraphs.append(
                f"El perfilado de calidad de datos levantó alertas sobre {_enumerar(alertas)}. "
                "El detalle por variable está en el Anexo B."
            )
        else:
            paragraphs.append(
                "El perfilado de calidad de datos no levantó alertas de variables casi "
                "constantes, casi únicas ni de cardinalidad excesiva."
            )

        if _bool(eda.get("stability_flagged")):
            metric = _text(eda.get("stability_metric_used"))
            value = _float(eda.get("stability_value"))
            threshold = _float(eda.get("stability_threshold"))
            if metric is not None and value is not None and threshold is not None:
                paragraphs.append(
                    f"La estabilidad temporal de la tasa de incumplimiento quedó marcada: el "
                    f"indicador «{metric}» alcanza {_num(value)} frente al umbral configurado de "
                    f"{_num(threshold)}. Este punto debe explicarse en el bloque de contexto."
                )

    target = _mapping(data_params.get("target"))
    target_col = _text(target.get("target_col"))
    # El target es "la variable objetivo del ejercicio" solo si alguna etapa de construcción lo
    # consume: en una cadena standalone (p. ej. IFRS 9) el data step lo construye igual, pero
    # declararlo objetivo del ejercicio sería falso.
    construccion = any(
        domain in bundle.cards
        for domain in ("binning", "selection", "model", "scorecard", "calibration")
    )
    if target_col is not None and construccion:
        paragraphs.append(
            f"La variable objetivo del ejercicio es «{target_col}», construida por las reglas de "
            "incumplimiento declaradas en el config (Anexo C). La definición de negocio que "
            "justifica esas reglas —p. ej. 90+ días de mora— debe explicitarla el analista: el "
            "motor aplica la regla, no la fundamenta."
        )

    partition = _mapping(data_params.get("partition"))
    strategy = _mapping(partition.get("strategy"))
    strategy_type = _text(strategy.get("type"))
    if strategy_type is not None:
        paragraphs.append(_partition_sentence(strategy_type, strategy))

    if not paragraphs:
        paragraphs.append(
            "La corrida no publicó datos de población (data card, card de EDA ni config de "
            "datos); este "
            "capítulo debe completarse íntegramente a mano."
        )
    return tuple(paragraphs)


def _partition_sentence(strategy_type: str, strategy: Mapping[str, Any]) -> str:
    """Describe la partición realmente usada, con sus parámetros."""
    if strategy_type == "temporal":
        date_col = _text(strategy.get("date_col"))
        oot_from = _text(strategy.get("oot_from"))
        fraction = _float(strategy.get("holdout_fraction"))
        detalle = f"por corte temporal sobre «{date_col}»" if date_col else "por corte temporal"
        if oot_from:
            detalle += f", con la ventana fuera de tiempo (OOT) desde {oot_from}"
        if fraction is not None:
            detalle += f", y un Holdout de {_pct(fraction)} del resto"
        return f"La población se particionó {detalle}."
    if strategy_type == "cohort":
        cohort_col = _text(strategy.get("cohort_col"))
        cohorts = _sequence(strategy.get("oot_cohorts"))
        fraction = _float(strategy.get("holdout_fraction"))
        detalle = f"por cohorte sobre «{cohort_col}»" if cohort_col else "por cohorte"
        if cohorts:
            detalle += (
                f", reservando como OOT {_plural(len(cohorts), 'la cohorte', 'las cohortes')} "
                f"{_enumerar(tuple(f'«{cohort}»' for cohort in cohorts))}"
            )
        if fraction is not None:
            detalle += f", y un Holdout de {_pct(fraction)} del resto"
        return f"La población se particionó {detalle}."
    if strategy_type == "random":
        dev = _float(strategy.get("dev_fraction"))
        holdout = _float(strategy.get("holdout_fraction"))
        oot = _float(strategy.get("oot_fraction"))
        partes = tuple(
            f"{label} {_pct(value)}"
            for label, value in (("Desarrollo", dev), ("Holdout", holdout), ("OOT", oot))
            if value is not None
        )
        if partes:
            return f"La población se particionó de forma aleatoria: {_enumerar(partes)}."
        return "La población se particionó de forma aleatoria."
    return f"La población se particionó con la estrategia «{strategy_type}»."


# ────────────────────────────── metodología ──────────────────────────────


def methodology_intro(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Encuadra la metodología: qué etapas se ejecutaron realmente y bajo qué trazabilidad."""
    etapas = tuple(
        DOMAIN_TITLES[domain]
        for domain in ("binning", "selection", "model", "scorecard", "calibration")
        if domain in bundle.cards
    )
    if not etapas:
        return (
            "Esta corrida no ejecutó etapas de construcción de scorecard (segmentación, "
            "selección, modelo, calibración): este capítulo describe únicamente las etapas que "
            "sí corrieron, con los parámetros efectivos que constan en el config trazado en el "
            "Anexo A. La metodología de los cálculos de dominio se describe en su capítulo "
            "correspondiente.",
        )
    return (
        "Este capítulo describe el procedimiento realmente ejecutado por el motor en esta "
        "corrida, con los parámetros efectivos que constan en el config trazado en el Anexo A. "
        "No es una descripción genérica de la técnica: cada cifra citada aquí es la que produjo "
        "este modelo.",
    )


def methodology_body(bundle: ReportInputBundle, domain: str) -> tuple[str, ...]:
    """Despacha la prosa metodológica de la etapa pedida."""
    if domain == "data":
        return _methodology_data(bundle)
    if domain == "binning":
        return _methodology_binning(bundle)
    if domain == "selection":
        return _methodology_selection(bundle)
    if domain == "model":
        return _methodology_model(bundle)
    if domain == "scorecard":
        return _methodology_scorecard(bundle)
    if domain == "calibration":
        return _methodology_calibration(bundle)
    if domain == "provisioning_ifrs9":
        return _methodology_provisioning_ifrs9(bundle)
    return ()


def _methodology_provisioning_ifrs9(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Ficha F4 compartida con la UI, derivada del config y de las cards de la corrida."""
    card = build_ifrs9_methodology_card(
        config=bundle.pipeline_params,
        survival_card=bundle.cards.get("survival"),
        ifrs9_card=bundle.cards.get("provisioning_ifrs9"),
    )
    return methodology_paragraphs(card) if card is not None else ()


def _methodology_data(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Tratamiento de datos: esquema, faltantes, especiales y ventana de desempeño."""
    params = _params(bundle, "data")
    if not params:
        return ()
    paragraphs: list[str] = []

    schema = _mapping(params.get("schema_")) or _mapping(params.get("schema"))
    columns = _sequence(schema.get("columns"))
    if columns:
        paragraphs.append(
            f"El dataset se validó contra un esquema declarado de {len(columns)} "
            f"{_plural(len(columns), 'columna', 'columnas')}, con tipos y nulabilidad "
            "explícitos; una desviación del esquema detiene la corrida en vez de propagarse."
        )

    missing = _mapping(params.get("missing"))
    max_missing = _float(missing.get("max_missing_rate"))
    specials = _sequence(missing.get("special_values"))
    frases: list[str] = []
    if max_missing is not None:
        frases.append(
            f"se rechaza toda variable con más de {_pct(max_missing)} de valores faltantes"
        )
    if specials:
        frases.append(
            f"se declararon {len(specials)} {_plural(len(specials), 'grupo', 'grupos')} de "
            "valores especiales (centinelas), que no se confunden con faltantes"
        )
    if frases:
        paragraphs.append(f"En el tratamiento de faltantes {_enumerar(frases)}.")

    target = _mapping(params.get("target"))
    window = _mapping(target.get("window"))
    months = _int(window.get("months"))
    if months is not None:
        paragraphs.append(
            f"El incumplimiento se observa en una ventana de desempeño de {months} "
            f"{_plural(months, 'mes', 'meses')} desde la fecha de observación."
        )
    exclusions = _sequence(target.get("exclusion_rules"))
    if exclusions:
        paragraphs.append(
            f"Se aplicaron {len(exclusions)} {_plural(len(exclusions), 'regla', 'reglas')} de "
            "exclusión sobre la población; su detalle literal consta en el Anexo C."
        )
    return tuple(paragraphs)


def _methodology_binning(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Binning WoE: solver, número de bins, tamaño mínimo, monotonía y especiales."""
    card = _card(bundle, "binning")
    params = _params(bundle, "binning")
    if card is None and not params:
        return ()
    paragraphs: list[str] = []

    solver = _text(params.get("solver"))
    max_bins = _int(params.get("max_n_bins"))
    min_bins = _int(params.get("min_n_bins"))
    min_size = _float(params.get("min_bin_size"))
    prebins = _int(params.get("max_n_prebins"))
    frases: list[str] = []
    if solver is not None:
        frases.append(
            f"se discretizó cada variable con OptBinning, resolviendo el problema óptimo por "
            f"{_SOLVER_LABELS.get(solver, solver)}"
        )
    if prebins is not None:
        frases.append(f"partiendo de un máximo de {prebins} pre-bins")
    if max_bins is not None:
        limite = f"un máximo de {max_bins} bins por variable"
        if min_bins is not None:
            limite = f"entre {min_bins} y {max_bins} bins por variable"
        frases.append(f"con {limite}")
    if min_size is not None:
        frases.append(f"un tamaño mínimo de bin de {_pct(min_size)} de la población")
    if frases:
        paragraphs.append(f"{_capitalizar(_enumerar(frases))}.")

    trend = _text(params.get("monotonic_trend"))
    if trend is not None:
        paragraphs.append(
            f"La tendencia monótona exigida al WoE es {_MONOTONIC_LABELS.get(trend, trend)}: el "
            "riesgo debe comportarse de forma coherente entre tramos contiguos, sin quiebres "
            "que un analista no pueda defender."
        )
    elif params:
        paragraphs.append(
            "No se exigió tendencia monótona al WoE: los bins pueden no ordenar el riesgo de "
            "forma monótona y esa decisión debe justificarse."
        )

    if card is not None:
        requested = _int(card.get("n_variables_requested"))
        binned = _int(card.get("n_variables_binned"))
        skipped = _int(card.get("n_variables_skipped"))
        if requested is not None and binned is not None:
            frase = (
                f"De {requested} {_plural(requested, 'variable candidata', 'variables candidatas')}"
                f", {binned} {_plural(binned, 'quedó binificada', 'quedaron binificadas')}"
            )
            if skipped:
                frase += f" y {skipped} se {_plural(skipped, 'descartó', 'descartaron')}"
            paragraphs.append(f"{frase}.")

        special = _text(card.get("special_handling"))
        missing = _text(card.get("missing_handling"))
        version = _text(card.get("optbinning_version"))
        frases = []
        if special is not None:
            tratamiento = _SPECIAL_HANDLING.get(special, special)
            frases.append(f"los valores especiales se agrupan {tratamiento}")
        if missing is not None:
            frases.append(f"los faltantes reciben el tratamiento «{missing}»")
        if frases:
            cierre = f" (OptBinning {version})" if version and version != "no_instalado" else ""
            paragraphs.append(f"{_capitalizar(_enumerar(frases))}{cierre}.")
    return tuple(paragraphs)


def _methodology_selection(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Selección: umbrales de IV, correlación, VIF y estabilidad realmente aplicados."""
    card = _card(bundle, "selection")
    params = _params(bundle, "selection")
    if card is None and not params:
        return ()
    paragraphs: list[str] = []

    thresholds = _mapping(card.get("thresholds")) if card is not None else {}
    min_iv = _float(thresholds.get("min_iv")) if thresholds else _float(params.get("min_iv"))
    max_iv = _float(thresholds.get("max_iv")) if thresholds else _float(params.get("max_iv"))
    if min_iv is not None:
        frase = f"Se descartaron las variables con IV inferior a {_num(min_iv, decimals=2)}"
        if max_iv is not None:
            accion = _text(thresholds.get("max_iv_action")) or _text(params.get("max_iv_action"))
            verbo = "se excluyeron" if accion == "exclude" else "se marcaron para revisión"
            frase += (
                f"; las de IV superior a {_num(max_iv, decimals=2)} {verbo}, porque un poder "
                "predictivo tan alto suele indicar fuga de información más que señal legítima"
            )
        paragraphs.append(f"{frase}.")

    correlation = _mapping(params.get("correlation"))
    vif = _mapping(params.get("vif"))
    frases: list[str] = []
    if _bool(correlation.get("enabled")):
        method = _text(correlation.get("method"))
        threshold = _float(correlation.get("threshold"))
        if threshold is not None:
            metodo = f" ({method})" if method else ""
            frases.append(
                f"se eliminó la redundancia entre pares de variables con correlación"
                f"{metodo} sobre {_num(threshold, decimals=2)}"
            )
    if _bool(vif.get("enabled")):
        threshold = _float(vif.get("threshold"))
        if threshold is not None:
            frases.append(
                f"se acotó la multicolinealidad exigiendo un VIF bajo {_num(threshold, decimals=1)}"
            )
    if frases:
        paragraphs.append(f"{_capitalizar(_enumerar(frases))}.")

    stability = _mapping(params.get("stability"))
    if _bool(stability.get("enabled")):
        stable = _float(stability.get("stable_threshold"))
        review = _float(stability.get("review_threshold"))
        action = _text(stability.get("action"))
        if stable is not None and review is not None:
            consecuencia = (
                "y las inestables se excluyeron"
                if action == "exclude"
                else "y las inestables se reportaron sin excluirse"
            )
            paragraphs.append(
                f"La estabilidad temporal de cada variable candidata se evaluó con umbrales de "
                f"{_num(stable, decimals=2)} (estable) y {_num(review, decimals=2)} (revisión), "
                f"{consecuencia}."
            )

    if card is not None:
        candidates = _int(card.get("n_candidates"))
        selected = _int(card.get("n_selected"))
        if candidates is not None and selected is not None:
            paragraphs.append(
                f"El filtro dejó {selected} de {candidates} "
                f"{_plural(candidates, 'variable candidata', 'variables candidatas')}; el motivo "
                "de exclusión de cada variable descartada consta en la tabla de selección."
            )
    return tuple(paragraphs)


def _methodology_model(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Modelo PD: motor, stepwise, significancia y políticas de signo/contribución."""
    card = _card(bundle, "model")
    params = _params(bundle, "model")
    if card is None and not params:
        return ()
    paragraphs: list[str] = []

    engine = _text(card.get("engine")) if card is not None else _text(params.get("engine"))
    alpha = _float(params.get("alpha"))
    if engine is not None:
        frase = (
            f"La probabilidad de incumplimiento se modeló mediante "
            f"{_ENGINE_LABELS.get(engine, engine)} sobre las variables transformadas a WoE"
        )
        if alpha is not None:
            frase += f", con un nivel de significancia de {_num(alpha, decimals=2)}"
        paragraphs.append(f"{frase}.")

    stepwise = _mapping(params.get("stepwise"))
    direction = _text(stepwise.get("direction"))
    if not _bool(stepwise.get("enabled")):
        direction = "none"
    if direction is not None:
        frase = _STEPWISE_DIRECTIONS.get(direction, f"stepwise «{direction}»")
        if direction != "none":
            criterion = _text(stepwise.get("criterion"))
            entry = _float(stepwise.get("entry_p_value"))
            exit_value = _float(stepwise.get("exit_p_value"))
            detalle: list[str] = []
            if criterion is not None:
                detalle.append(f"criterio «{criterion}»")
            if entry is not None and exit_value is not None:
                detalle.append(
                    f"p-valor de entrada {_num(entry, decimals=2)} y de salida "
                    f"{_num(exit_value, decimals=2)}"
                )
            if detalle:
                frase += f" ({_enumerar(tuple(detalle))})"
        paragraphs.append(f"La construcción del modelo usó {frase}.")

    sign_policy = _mapping(params.get("sign_policy"))
    action = _text(sign_policy.get("action"))
    if action is not None:
        consecuencia = {
            "exclude": "se excluye la variable",
            "flag": "se marca la variable sin excluirla",
            "fail": "la corrida falla",
        }.get(action, f"se aplica la acción «{action}»")
        paragraphs.append(
            "Se exige que el coeficiente de cada variable en WoE tenga el signo esperado "
            f"(negativo): cuando se invierte, {consecuencia}. Un signo invertido significa que "
            "la variable contradice la relación de riesgo que su binning declara."
        )

    if card is not None:
        candidates = _int(card.get("n_candidates"))
        final = _int(card.get("n_final_features"))
        if candidates is not None and final is not None:
            paragraphs.append(
                f"El modelo final retiene {final} de {candidates} "
                f"{_plural(candidates, 'variable', 'variables')} de entrada."
            )
    return tuple(paragraphs)


def _methodology_scorecard(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Escalado del scorecard: PDO, odds/score objetivo, factor y offset derivados."""
    card = _card(bundle, "scorecard")
    if card is None:
        return ()
    paragraphs: list[str] = []

    pdo = _float(card.get("pdo"))
    target_score = _float(card.get("target_score"))
    target_odds = _float(card.get("target_odds"))
    if pdo is not None and target_score is not None and target_odds is not None:
        paragraphs.append(
            f"El modelo se escaló a puntaje con la convención PDO: un puntaje de "
            f"{_num(target_score, decimals=0)} corresponde a odds de "
            f"{_num(target_odds, decimals=0)}:1, y cada {_num(pdo, decimals=0)} puntos "
            "adicionales duplican esas odds."
        )

    factor = _float(card.get("factor"))
    offset = _float(card.get("offset"))
    if factor is not None and offset is not None:
        paragraphs.append(
            f"De esa convención se derivan los parámetros efectivos de la escala: factor "
            f"{_num(factor)} y offset {_num(offset)}."
        )

    direction = _text(card.get("score_direction"))
    rounding = _text(card.get("rounding_method"))
    frases: list[str] = []
    if direction is not None:
        frases.append(_SCORE_DIRECTIONS.get(direction, direction))
    if rounding is not None:
        frases.append(f"los puntajes se emiten con {_ROUNDING_METHODS.get(rounding, rounding)}")
    if frases:
        paragraphs.append(f"{_capitalizar(_enumerar(frases))}.")

    overrides = _int(card.get("overrides_count"))
    if overrides:
        paragraphs.append(
            f"Se aplicaron {overrides} {_plural(overrides, 'override', 'overrides')} manuales de "
            "puntaje; cada uno lleva su justificación declarada en el config (Anexo C)."
        )
    return tuple(paragraphs)


def _methodology_calibration(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Calibración: método, ancla, partición de ajuste y parámetros resultantes."""
    card = _card(bundle, "calibration")
    if card is None:
        return ()
    paragraphs: list[str] = []

    method = _text(card.get("method"))
    anchor_source = _text(card.get("anchor_source"))
    anchor_kind = _text(card.get("anchor_kind"))
    target_pd = _float(card.get("target_pd"))
    if method is not None:
        frase = (
            f"La PD se calibró por {_CALIBRATION_METHODS.get(method, method)}, ajustando sobre la "
            "partición de Desarrollo"
        )
        if anchor_source is not None:
            frase += f" contra {_ANCHOR_SOURCES.get(anchor_source, anchor_source)}"
        if target_pd is not None:
            frase += f", con una PD objetivo de {_pct(target_pd)}"
        if anchor_kind is not None:
            frase += f". El ancla es {_ANCHOR_KINDS.get(anchor_kind, anchor_kind)}"
        paragraphs.append(f"{frase}.")

    offset = _float(card.get("offset"))
    slope = _float(card.get("slope"))
    intercept = _float(card.get("intercept"))
    if offset is not None:
        paragraphs.append(
            f"El desplazamiento aplicado al intercepto es {_num(offset)}, lo que preserva el "
            "ordenamiento del score: la calibración corrige el nivel de la PD, no su ranking."
        )
    elif slope is not None and intercept is not None:
        paragraphs.append(
            f"Los parámetros ajustados son pendiente {_num(slope)} e intercepto {_num(intercept)}."
        )

    n_fit = _int(card.get("n_fit"))
    if n_fit is not None:
        paragraphs.append(
            f"El ajuste se realizó sobre {n_fit} "
            f"{_plural(n_fit, 'observación', 'observaciones')} de Desarrollo."
        )
    return tuple(paragraphs)


# ────────────────────────────── resultados ──────────────────────────────


def results_intro(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Encuadra los resultados y remite el detalle completo a los anexos."""
    del bundle
    return (
        "Los resultados se presentan por etapa, con las tablas que sostienen el juicio de "
        "validación. El detalle exhaustivo —todas las tablas y todos los parámetros de cada "
        "paso— no se pierde: vive en los Anexos B y C, que son parte de este mismo informe.",
    )


def results_body(bundle: ReportInputBundle, domain: str) -> tuple[str, ...]:
    """Despacha la prosa de resultados de la etapa pedida."""
    if domain == "data":
        return _results_data(bundle)
    if domain == "binning":
        return _results_binning(bundle)
    if domain == "selection":
        return _results_selection(bundle)
    if domain == "model":
        return _results_model(bundle)
    if domain == "scorecard":
        return _results_scorecard(bundle)
    if domain == "calibration":
        return _results_calibration(bundle)
    if domain == "performance":
        return _results_performance(bundle)
    if domain == "stability":
        return _results_stability(bundle)
    if domain == "eda":
        return _results_eda(bundle)
    if domain == "provisioning":
        return _results_provisioning(bundle)
    if domain == "provisioning_cmf":
        return _results_provisioning_cmf(bundle)
    if domain == "provisioning_internal":
        return _results_provisioning_internal(bundle)
    if domain == "provisioning_ifrs9":
        return _results_provisioning_ifrs9(bundle)
    return ()


def _results_data(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Describe la proyección literal del ``DataCardSection`` sin derivar estadísticas."""
    if _card(bundle, "data") is None:
        return ()
    return (
        "Las tablas siguientes son una proyección de presentación del DataCardSection publicado "
        "por data. Estados, tamaños y tasas por partición, y exclusiones se copian literalmente; "
        "el informe no recalcula ni completa valores ausentes.",
    )


# ────────────────────────────── validación formal ──────────────────────────────


def validation_intro(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Resume objetivamente la card del ``ValidationResult`` sin emitir veredicto humano."""
    if "validation" not in bundle.results:
        return ()
    card = _card(bundle, "validation")
    if card is None:
        return ()
    model_ref = _text(card.get("model_ref")) or "modelo sin referencia publicada"
    status = _text(card.get("overall_status")) or "no disponible"
    n_tests = _int(card.get("n_tests"))
    n_failed = _int(card.get("n_failed"))
    families = tuple(
        _VALIDATION_FAMILY_LABELS.get(str(item), str(item))
        for item in _sequence(card.get("families_run"))
    )
    paragraphs = [
        f"La validación formal del modelo «{model_ref}» ejecutó {_enumerar(families)}. "
        f"El estado técnico agregado publicado por el motor es «{status}».",
    ]
    if n_tests is not None and n_failed is not None:
        paragraphs.append(
            f"El resultado registra {_miles(n_tests)} {_plural(n_tests, 'test', 'tests')}, de los "
            f"cuales {_miles(n_failed)} quedaron fallidos. Las tablas se copian del "
            "ValidationResult atómico, sin recalcular métricas ni decisiones."
        )
    gaps = tuple(str(item) for item in _sequence(card.get("falta_dato")))
    if gaps:
        paragraphs.append(f"Brechas de dato declaradas por validation: {_enumerar(gaps)}.")
    paragraphs.append(
        "Este estado es evidencia técnica; el veredicto de aprobación, aprobación con "
        "observaciones o rechazo corresponde al validador humano y queda POR COMPLETAR."
    )
    return tuple(paragraphs)


def validation_family_body(bundle: ReportInputBundle, family: str) -> tuple[str, ...]:
    """Explica qué columnas publica cada familia; la tabla conserva los valores del DTO."""
    table = bundle.tables.get(f"validation.{family}")
    rows = len(table.index) if table is not None else 0
    descriptions = {
        "discrimination": (
            "La tabla reproduce por partición AUC, Gini y KS, junto con población, fuente y "
            "estado de evaluabilidad."
        ),
        "calibration": (
            "La tabla reúne Hosmer-Lemeshow, Brier y, cuando fue configurado, el contraste por "
            "grado con sus decisiones y semáforo publicados."
        ),
        "stability": (
            "La tabla reproduce PSI/estabilidad, umbrales, banda, acción y decisión publicados "
            "por validation."
        ),
        "backtesting": (
            "La tabla contrasta valores estimados y realizados por parámetro y segmento, con el "
            "test, p-valor y decisión publicados."
        ),
    }
    description = descriptions.get(family)
    if description is None:
        return ()
    if rows == 0:
        return (
            f"{description} La familia fue ejecutada, pero no publicó filas evaluables; las "
            "brechas quedan declaradas en la síntesis del capítulo.",
        )
    return (f"{description} Filas publicadas por el DTO: {_miles(rows)}.",)


def _results_eda(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Población: qué muestran las tablas de tasa de incumplimiento y calidad."""
    card = _card(bundle, "eda")
    if card is None:
        return ()
    figures = _int(card.get("n_figures"))
    if figures:
        return (
            f"El EDA publicó {figures} {_plural(figures, 'figura', 'figuras')} y las tablas de "
            "tasa de incumplimiento y calidad que se reproducen a continuación.",
        )
    return ()


def _results_binning(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Poder predictivo: IV por variable y monotonía efectiva del WoE."""
    card = _card(bundle, "binning")
    if card is None:
        return ()
    paragraphs: list[str] = []

    iv_by_variable = _mapping(card.get("iv_by_variable"))
    medidos = tuple(
        (str(name), iv)
        for name, value in iv_by_variable.items()
        if (iv := _float(value)) is not None
    )
    disponibles = tuple(sorted(medidos, key=lambda item: (-item[1], item[0])))
    if disponibles:
        mejores = tuple(f"«{name}» ({_num(value, decimals=3)})" for name, value in disponibles[:3])
        paragraphs.append(
            f"El poder predictivo univariado (IV) de las {len(disponibles)} variables binificadas "
            f"lo encabezan {_enumerar(mejores)}. El IV de cada variable consta en la tabla "
            "siguiente y su binning completo, bin a bin, en el Anexo B."
        )

    monotonicity = _mapping(card.get("monotonicity_by_variable"))
    tendencias: dict[str, int] = {}
    sin_tendencia = 0
    for value in monotonicity.values():
        trend = _text(value)
        if trend is None:
            sin_tendencia += 1
            continue
        tendencias[trend] = tendencias.get(trend, 0) + 1
    if tendencias:
        detalle = tuple(
            f"{count} {_plural(count, 'variable', 'variables')} con tendencia "
            f"{_MONOTONIC_LABELS.get(trend, trend)}"
            for trend, count in sorted(tendencias.items())
        )
        frase = f"La monotonía efectiva del WoE resultó en {_enumerar(detalle)}"
        if sin_tendencia:
            frase += f", y {sin_tendencia} sin tendencia monótona resuelta, lo que debe revisarse"
        paragraphs.append(f"{frase}.")
    return tuple(paragraphs)


def _results_selection(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Selección: qué entró, qué quedó fuera y por qué; colinealidad residual."""
    card = _card(bundle, "selection")
    if card is None:
        return ()
    paragraphs: list[str] = []

    selected = _sequence(card.get("selected_features"))
    if selected:
        nombres = _enumerar(tuple(f"«{feature}»" for feature in selected))
        paragraphs.append(
            f"Las {len(selected)} {_plural(len(selected), 'variable', 'variables')} que pasaron "
            f"el filtro son {nombres}."
        )

    reasons = _mapping(card.get("excluded_by_reason"))
    descartes = tuple(
        f"{count} por {_reason_label(str(reason))}"
        for reason, count in sorted(reasons.items(), key=lambda item: str(item[0]))
        if str(reason) != "included" and _int(count)
    )
    if descartes:
        paragraphs.append(f"Las exclusiones se reparten en {_enumerar(descartes)}.")

    max_corr = _float(card.get("max_abs_correlation_after_selection"))
    max_vif = _float(card.get("max_vif_after_selection"))
    frases: list[str] = []
    if max_corr is not None:
        frases.append(
            f"la correlación absoluta máxima entre las variables finales es {_num(max_corr)}"
        )
    if max_vif is not None:
        frases.append(f"el VIF máximo es {_num(max_vif, decimals=2)}")
    if frases:
        paragraphs.append(f"Tras la selección, {_enumerar(frases)}.")

    high_iv = _sequence(card.get("high_iv_flags"))
    stability_flags = _sequence(card.get("stability_flags"))
    if high_iv:
        nombres = _enumerar(tuple(f"«{feature}»" for feature in high_iv))
        paragraphs.append(
            f"Quedaron marcadas por IV excesivo (posible fuga de información): {nombres}. "
            "Requieren una explicación de negocio antes de aprobar el modelo."
        )
    if stability_flags:
        nombres = _enumerar(tuple(f"«{feature}»" for feature in stability_flags))
        paragraphs.append(f"Quedaron marcadas por inestabilidad temporal: {nombres}.")
    return tuple(paragraphs)


def _results_model(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Ajuste: variables finales, convergencia, pseudo-R² y alertas de signo."""
    card = _card(bundle, "model")
    if card is None:
        return ()
    paragraphs: list[str] = []

    final_features = _sequence(card.get("final_features"))
    if final_features:
        nombres = _enumerar(tuple(f"«{feature}»" for feature in final_features))
        paragraphs.append(
            f"El modelo final incluye {len(final_features)} "
            f"{_plural(len(final_features), 'variable', 'variables')}: {nombres}."
        )

    fit = _mapping(card.get("fit_statistics"))
    if fit:
        converged = _bool(fit.get("converged"))
        pseudo_r2 = _float(fit.get("pseudo_r2_mcfadden"))
        n_obs = _int(fit.get("n_obs_dev"))
        n_events = _int(fit.get("n_events_dev"))
        frases: list[str] = []
        if converged is not None:
            frases.append(
                "el optimizador convergió" if converged else "el optimizador NO convergió"
            )
        if n_obs is not None and n_events is not None:
            frases.append(
                f"el ajuste usó {n_obs} observaciones de Desarrollo, de las cuales {n_events} "
                f"{_plural(n_events, 'es un incumplimiento', 'son incumplimientos')}"
            )
        if pseudo_r2 is not None:
            frases.append(f"el pseudo-R² de McFadden es {_num(pseudo_r2)}")
        if frases:
            paragraphs.append(f"En el ajuste in-sample, {_enumerar(frases)}.")
        if converged is False:
            paragraphs.append(
                "La no convergencia invalida la inferencia sobre los coeficientes: el modelo no "
                "puede aprobarse en este estado."
            )

    sign_flags = _sequence(card.get("sign_flags"))
    iv_flags = _sequence(card.get("iv_contribution_flags"))
    if sign_flags:
        nombres = _enumerar(tuple(f"«{feature}»" for feature in sign_flags))
        paragraphs.append(
            f"Con el signo del coeficiente invertido respecto de lo esperado: {nombres}. Cada "
            "caso contradice la relación de riesgo declarada por su binning y debe justificarse."
        )
    if iv_flags:
        nombres = _enumerar(tuple(f"«{feature}»" for feature in iv_flags))
        paragraphs.append(
            f"Marcadas por concentrar una contribución excesiva al IV del modelo: {nombres}."
        )
    return tuple(paragraphs)


def _results_scorecard(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Scorecard: rango de puntajes y número de atributos."""
    card = _card(bundle, "scorecard")
    if card is None:
        return ()
    paragraphs: list[str] = []

    n_variables = _int(card.get("n_variables"))
    min_score = _float(card.get("min_score"))
    max_score = _float(card.get("max_score"))
    if n_variables is not None:
        frase = (
            f"El scorecard asigna puntajes a los tramos de {n_variables} "
            f"{_plural(n_variables, 'variable', 'variables')}"
        )
        if min_score is not None and max_score is not None:
            frase += (
                f", con un rango teórico de puntaje entre {_num(min_score, decimals=0)} y "
                f"{_num(max_score, decimals=0)} puntos"
            )
        paragraphs.append(f"{frase}.")
    return tuple(paragraphs)


def _results_calibration(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Calibración: nivel de PD alcanzado vs. observado y preservación del ranking."""
    card = _card(bundle, "calibration")
    if card is None:
        return ()
    paragraphs: list[str] = []

    raw_mean = _float(card.get("raw_mean_pd_dev"))
    calibrated_mean = _float(card.get("calibrated_mean_pd_dev"))
    observed = _float(card.get("observed_default_rate_dev"))
    if calibrated_mean is not None:
        frase = f"En Desarrollo, la PD media calibrada es {_pct(calibrated_mean)}"
        if raw_mean is not None:
            frase += f", frente a {_pct(raw_mean)} antes de calibrar"
        if observed is not None:
            frase += f", contra una tasa de incumplimiento observada de {_pct(observed)}"
        paragraphs.append(f"{frase}.")
    elif observed is not None:
        paragraphs.append(f"La tasa de incumplimiento observada en Desarrollo es {_pct(observed)}.")

    ranking = _bool(card.get("ranking_preserved"))
    ties = _int(card.get("ties_created"))
    if ranking is True:
        frase = (
            "La calibración preservó el ordenamiento de las observaciones: la capacidad "
            "discriminante del modelo no se altera"
        )
        if ties:
            frase += f", aunque introdujo {ties} {_plural(ties, 'empate', 'empates')}"
        paragraphs.append(f"{frase}.")
    elif ranking is False:
        paragraphs.append(
            "La calibración NO preservó el ordenamiento de las observaciones: las métricas de "
            "discriminación calculadas sobre la PD calibrada pueden diferir de las del score."
        )
    return tuple(paragraphs)


def _results_performance(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Discriminación: AUC/Gini/KS por partición, con las bandas y flags publicados."""
    card = _card(bundle, "performance")
    if card is None:
        return ()
    paragraphs: list[str] = []

    source = _text(card.get("evaluation_source"))
    if source is not None:
        base = "la PD calibrada" if source == "pd_calibrated" else "el puntaje del scorecard"
        paragraphs.append(f"Las métricas de discriminación se calcularon sobre {base}.")

    max_metrics = _mapping(card.get("max_metrics_by_partition"))
    bands = _mapping(card.get("bands_by_partition"))
    for partition in _sequence(card.get("partitions")):
        partition_id = str(partition)
        values = _mapping(max_metrics.get(partition_id))
        band = str(bands.get(partition_id, ""))
        if band == "not_evaluable":
            reason = _not_evaluable_reason(card, partition_id)
            detalle = f" ({reason})" if reason else ""
            paragraphs.append(
                f"En {_partition_label(partition_id)} la discriminación no es evaluable"
                f"{detalle}: el informe no la sustituye por una estimación."
            )
            continue
        cifras = tuple(
            f"{label} {_num(values.get(key), decimals=4)}"
            for key, label in _DISCRIMINANT_METRIC_LABELS
            if _float(values.get(key)) is not None
        )
        if not cifras:
            continue
        frase = f"En {_partition_label(partition_id)} el modelo alcanza {_enumerar(cifras)}"
        flags = _threshold_flags(card, partition_id)
        if flags:
            metricas = _enumerar(tuple(flag.upper() for flag in flags))
            frase += (
                f". {metricas} {_plural(len(flags), 'queda', 'quedan')} bajo el umbral "
                "configurado, lo que constituye una alerta explícita de validación"
            )
        paragraphs.append(f"{frase}.")

    deciles = _int(card.get("n_deciles"))
    if deciles is not None:
        paragraphs.append(
            f"La tabla de desempeño reparte la población en {deciles} tramos de riesgo "
            "ordenados por score, y permite verificar que la tasa de incumplimiento observada "
            "sea monótona entre tramos."
        )
    return tuple(paragraphs)


def _results_stability(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Estabilidad: PSI por comparación con su banda, y peor variable por CSI."""
    card = _card(bundle, "stability")
    if card is None:
        return ()
    paragraphs: list[str] = []

    max_psi = _mapping(card.get("max_psi_by_comparison"))
    bands = _mapping(card.get("bands_by_comparison"))
    psi_bins = _int(card.get("psi_bins"))
    for comparison in _sequence(card.get("comparisons")):
        comparison_id = str(comparison)
        value = _float(max_psi.get(comparison_id))
        band = str(bands.get(comparison_id, ""))
        if band == "not_evaluable" or value is None:
            paragraphs.append(
                f"El PSI de {_comparison_label(comparison_id)} no es evaluable con los datos "
                "disponibles."
            )
            continue
        lectura = {
            "stable": (
                "La distribución del score se mantiene, de modo que no hay evidencia de "
                "desplazamiento poblacional."
            ),
            "review": (
                "La distribución del score se desplazó lo suficiente para exigir una revisión "
                "antes de seguir usando el modelo."
            ),
            "redevelop": (
                "El desplazamiento de la distribución es severo: el motor lo clasifica en banda "
                "de redesarrollo."
            ),
        }.get(band, "La banda resultante no tiene una lectura definida.")
        paragraphs.append(
            f"El PSI del score en {_comparison_label(comparison_id)} es {_num(value)} "
            f"(banda «{_STABILITY_BANDS.get(band, band)}»). {lectura}"
        )

    worst_feature = _text(card.get("worst_csi_feature"))
    worst_value = _float(card.get("worst_csi_value"))
    if worst_feature is not None and worst_value is not None:
        paragraphs.append(
            f"A nivel de variable, el mayor CSI corresponde a «{worst_feature}» con "
            f"{_num(worst_value)}."
        )
    if psi_bins is not None:
        paragraphs.append(
            f"El PSI se calculó sobre {psi_bins} tramos del score, definidos en Desarrollo."
        )
    return tuple(paragraphs)


# ────────────────────────────── provisiones (capítulo condicional) ──────────────────────────────


_PROVISION_WARNINGS: Final[dict[str, str]] = {
    "comparacion_incompleta": (
        "una de las dos fuentes no cubrió todas las exposiciones, así que la regla se aplicó "
        "sobre cobertura parcial"
    ),
    "piso_incompleto": (
        "una de las dos fuentes no cubrió todas las exposiciones, así que la regla se aplicó "
        "sobre cobertura parcial"
    ),
    "cobertura_imputada_cero": (
        "a las exposiciones sin dato de una fuente se les imputó provisión cero, lo que puede "
        "subestimar el máximo"
    ),
}


def _provision_warning_descriptions(warnings: tuple[str, ...]) -> tuple[str, ...]:
    """Normaliza códigos y mensajes FALTA-DATO de cobertura sin duplicar aliases legacy."""
    descriptions: list[str] = []
    for warning in warnings:
        description = _PROVISION_WARNINGS.get(warning)
        folded = warning.casefold()
        if description is None and (
            "falta-dato-prov-3" in folded or "comparación incompleta" in folded
        ):
            description = _PROVISION_WARNINGS["comparacion_incompleta"]
        elif description is None and ("imputó 0" in folded or "imputada" in folded):
            description = _PROVISION_WARNINGS["cobertura_imputada_cero"]
        elif description is None and "falta-dato-prov-1" in folded:
            description = "algunas celdas no tenían contraparte y quedaron fuera del comparativo"
        if description is not None and description not in descriptions:
            descriptions.append(description)
    return tuple(descriptions)


def provisions_intro(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Titular del capítulo según fuentes, nivel y regla efectivamente configurados."""
    orq = _card(bundle, "provisioning")
    if orq is None:
        return ()
    cmf = _card(bundle, "provisioning_cmf")
    source_a = str(orq.get("source_a") or "")
    source_b = str(orq.get("source_b") or "")
    rule = str(orq.get("rule") or "")
    level = str(orq.get("comparison_level") or "")
    amount_a = _float(orq.get("total_provision_a"))
    amount_b = _float(orq.get("total_provision_b"))
    reportado = _float(orq.get("total_reported_provision"))
    exposicion = _float(cmf.get("total_exposure_amount")) if cmf is not None else None
    binding = str(orq.get("binding") or "")
    amounts = {source_a: amount_a, source_b: amount_b}
    estandar = amounts.get("cmf")
    interno_total = amounts.get("internal")
    is_standard_internal = {source_a, source_b} == {"cmf", "internal"}
    is_b1_binding = is_standard_internal and level == "total"

    if is_b1_binding and rule == "max":
        paragraphs: list[str] = [
            "El Compendio de Normas Contables para Bancos (Cap. B-1, hoja 10-11, Circular "
            "N° 2.346) exige considerar el mayor valor entre el método estándar de la CMF y el "
            "método interno, por institución."
        ]
    elif is_b1_binding and rule == "use_internal":
        paragraphs = [
            "La corrida usa directamente el método interno. El Cap. B-1 permite esa ruta sólo "
            "cuando el método fue evaluado y no objetado; Nikodym no verifica esa condición."
        ]
    else:
        paragraphs = [
            "Este capítulo presenta una comparación configurada entre dos fuentes. El resultado "
            "es diagnóstico y no constituye por sí solo la regla B-1 por institución."
        ]

    if (
        is_standard_internal
        and estandar is not None
        and interno_total is not None
        and reportado is not None
    ):
        alcance = f"Sobre colocaciones por {_clp(exposicion)}, " if exposicion is not None else ""
        base = (
            f"{alcance}el método estándar de la CMF calcula "
            f"{_clp(estandar)} y el método interno {_clp(interno_total)}. La provisión a "
            f"reportar según la regla configurada es {_clp(reportado)}."
        )
        if rule == "use_internal":
            relacion = "por debajo" if interno_total < estandar else "por encima"
            paragraphs.append(
                base + f" Se usa el método interno, que queda {relacion} del estándar; la validez "
                "regulatoria depende de su evaluación y no objeción institucional."
            )
        elif binding == "cmf":
            sobrecosto = reportado - interno_total
            extra_pct = (sobrecosto / interno_total * 100.0) if interno_total else None
            titular = (
                f" Manda el estándar: cuesta {_clp(sobrecosto)} por encima de lo que el propio "
                "modelo interno del banco pediría"
            )
            titular += f" (un {extra_pct:.0f} % más)." if extra_pct is not None else "."
            paragraphs.append(base + titular)
        elif binding == "internal":
            paragraphs.append(
                base + " Manda el método interno: el modelo del banco ya provisiona por encima "
                "del estándar de la CMF, de modo que el estándar no añade sobrecosto."
            )
        else:
            paragraphs.append(base + " Ambos métodos arrojan la misma provisión.")
    elif amount_a is not None and amount_b is not None and reportado is not None:
        labels = {
            "cmf": "método estándar CMF",
            "internal": "método interno",
            "ifrs9": "ECL IFRS 9",
        }
        paragraphs.append(
            f"{labels.get(source_a, source_a)}: {_clp(amount_a)}; "
            f"{labels.get(source_b, source_b)}: {_clp(amount_b)}; resultado de la regla: "
            f"{_clp(reportado)}."
        )

    if is_b1_binding:
        paragraphs.append(
            "El nivel total sólo representa «por institución» bajo el precontrato de una "
            "institución por corrida; Nikodym no valida ese perímetro."
        )
    return tuple(paragraphs)


def _results_provisioning(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Subsección del orquestador: regla configurada, alcance normativo y warnings."""
    card = _card(bundle, "provisioning")
    if card is None:
        return ()
    paragraphs: list[str] = []

    rule = str(card.get("rule") or "")
    binding = str(card.get("binding") or "")
    level = str(card.get("comparison_level") or "")
    source_a = str(card.get("source_a") or "")
    source_b = str(card.get("source_b") or "")
    is_standard_internal = {source_a, source_b} == {"cmf", "internal"}
    is_b1_binding = is_standard_internal and level == "total"
    if rule == "max":
        binding_label = {
            "cmf": "el método estándar de la CMF",
            "internal": "el método interno",
            "ifrs9": "el ECL IFRS 9",
            "tie": "ambas fuentes por igual (empate)",
            "cmf_only": "sólo el método estándar CMF disponible",
            "internal_only": "sólo el método interno disponible",
            "ifrs9_only": "sólo el ECL IFRS 9 disponible",
        }.get(binding, binding)
        nivel_label = {
            "total": "la entidad",
            "portfolio": "cada cartera",
            "segment": "cada segmento",
        }
        paragraphs.append(
            f"La regla configurada toma el máximo entre las dos fuentes a nivel de "
            f"{nivel_label.get(level, level)}; resulta vinculante {binding_label}."
        )
        if not is_b1_binding:
            paragraphs.append(
                "Este resultado es un comparativo diagnóstico y no constituye por sí solo la regla "
                "B-1 por institución."
            )
    elif rule == "use_internal":
        paragraphs.append(
            "La regla configurada selecciona el método interno directamente, sin tomar el máximo."
        )
        if not is_b1_binding:
            paragraphs.append(
                "En este par o nivel la selección es diagnóstica y no acredita el uso regulatorio "
                "del método interno bajo B-1."
            )

    # La asimetría de consolidación es real y normativa: sin declararla, parece un bug (SDD-28 §8).
    if is_standard_internal:
        paragraphs.append(
            "Los dos métodos agrupan la cartera de forma distinta, y es deliberado: el método "
            "estándar consolida a nivel de deudor —sube a incumplimiento todas sus operaciones si "
            "alguna supera 90 días de mora—, mientras que el método interno agrupa por "
            "banda de score. La asimetría responde a sus contratos respectivos, no es un error de "
            "cálculo."
        )

    orchestration_metrics = _mapping(
        _mapping(card.get("metric_sections")).get("provisioning_orchestration")
    )
    source_a_binding = _float(orchestration_metrics.get("source_a_binding_ratio"))
    if source_a_binding is None:
        source_a_binding = _float(orchestration_metrics.get("floor_bite_ratio"))
    if source_a_binding is not None and level != "total":
        source_a_label = "El estándar" if card.get("source_a") == "cmf" else "La fuente A"
        paragraphs.append(
            f"{source_a_label} resulta vinculante en el {_pct(source_a_binding)} de las celdas "
            "comparadas (diagnóstico secundario, no regla por institución)."
        )

    warnings = tuple(str(code) for code in _sequence(card.get("falta_dato")))
    descritos = _provision_warning_descriptions(warnings)
    if descritos:
        paragraphs.append(
            "El orquestador reportó advertencias que el lector debe conocer: "
            + _enumerar(descritos)
            + "."
        )
    return tuple(paragraphs)


def _results_provisioning_cmf(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Subsección del método estándar: exposición, provisión, índice de riesgo y matriz."""
    card = _card(bundle, "provisioning_cmf")
    if card is None:
        return ()
    exposicion = _float(card.get("total_exposure_amount"))
    provision = _float(card.get("total_provision_amount"))
    matrix = _text(card.get("matrix_version"))
    paragraphs: list[str] = []
    if exposicion is not None and provision is not None:
        indice = provision / exposicion if exposicion else None
        detalle = (
            f"El método estándar de la CMF provisiona {_clp(provision)} sobre {_clp(exposicion)} "
            "de colocaciones"
        )
        detalle += f", un índice de riesgo del {_pct(indice)}." if indice is not None else "."
        paragraphs.append(detalle)
    paragraphs.append(
        "En cartera de consumo el factor de provisión es PI por PDI; la categoría no es un input: "
        "la deriva el motor del tramo de mora, la tenencia de hipotecario y la mora en el sistema "
        "financiero, según la matriz del Cap. B-1."
        + (f" Matriz aplicada: {matrix}." if matrix is not None else "")
    )
    return tuple(paragraphs)


def _results_provisioning_internal(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Subsección del método interno: PD por LGD por exposición, por grupo homogéneo."""
    card = _card(bundle, "provisioning_internal")
    if card is None:
        return ()
    provision = _float(card.get("total_internal_provision"))
    n_groups = _int(card.get("n_groups"))
    pd_source = str(card.get("pd_source") or "")
    grouping = str(card.get("grouping") or "")
    paragraphs: list[str] = []
    detalle = "El método interno es el que la norma también exige: pérdida esperada por grupo "
    detalle += "homogéneo, como probabilidad de incumplimiento por pérdida dado el incumplimiento "
    detalle += "por exposición del grupo."
    if provision is not None:
        detalle += f" Sobre esta cartera suma {_clp(provision)}."
    paragraphs.append(detalle)
    fuente_pd = {
        "calibration": "la PD calibrada del scorecard —el modelo del banco entra por aquí en el "
        "número reportado—",
        "model": "la PD del modelo",
    }.get(pd_source, "la PD configurada")
    agrupacion = {
        "score_band": "banda de score",
        "segment": "segmento",
        "provided": "grupo provisto",
    }
    detalle_pd = f"La PD proviene de {fuente_pd}"
    if n_groups is not None:
        detalle_pd += (
            f", agrupada en {n_groups} grupos por {agrupacion.get(grouping, grouping)}"
            if grouping
            else f", en {n_groups} grupos"
        )
    paragraphs.append(detalle_pd + ".")
    return tuple(paragraphs)


# ────────────────────────────── IFRS 9 / ECL (capítulo condicional) ──────────────────────────────

_IFRS9_PIT_MODE_LABELS: Final[dict[str, str]] = {
    "ttc_only": "through-the-cycle (TTC)",
    "apply_vasicek": "point-in-time por ajuste de Vasicek",
    "consume_pit": "point-in-time provista en los datos",
}
# Las claves espejan el enum ``IfrsPdConfig.term_structure_source`` ({survival, markov, forward});
# un valor fuera del dict cae al fallback genérico "la fuente '<slug>'" en quien lo consume.
_IFRS9_TERM_SOURCE_LABELS: Final[dict[str, str]] = {
    "survival": "la curva lifetime PD del modelo de supervivencia (discrete-time hazard)",
    "markov": "la curva lifetime PD derivada de las matrices de transición de la capa markov",
    "forward": "la term-structure condicionada a escenarios macro de la capa forward-looking",
}
_IFRS9_WARNING_LABELS: Final[dict[str, str]] = {
    # SDD-16 §6: el panel EAD(t) por período está diferido a CT-3; la EAD se despliega constante.
    "FALTA-DATO-IFRS-4": (
        "la exposición (EAD) se proyectó constante a lo largo de la vida de cada operación, "
        "porque el dataset no trae un perfil de exposición por período (código FALTA-DATO-IFRS-4)"
    ),
    # SDD-20 FALTA-DATO-FWD-6: la LGD condicionada de forward no se consume en v1.
    "FALTA-DATO-IFRS-6": (
        "la LGD condicionada por escenario que publica la capa forward-looking no se consumió: "
        "la LGD del cálculo proviene del enfoque configurado en el motor IFRS 9 "
        "(código FALTA-DATO-IFRS-6)"
    ),
}


def ifrs9_intro(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Titular del capítulo: la ECL a constituir, su cobertura sobre la EAD y el staging.

    Es el número contable de IFRS 9 (SDD-16): Stage 1 provisiona la pérdida esperada a 12 meses y
    Stage 2/3 la pérdida esperada lifetime (IFRS 9 5.5.3/5.5.5). Solo afirma lo que la card trae.
    """
    card = _card(bundle, "provisioning_ifrs9")
    if card is None:
        return ()

    ecl = _float(card.get("total_ecl_reported"))
    ead = _float(card.get("total_ead"))
    n_rows = _int(card.get("n_rows"))
    n_s1 = _int(card.get("n_stage1"))
    n_s2 = _int(card.get("n_stage2"))
    n_s3 = _int(card.get("n_stage3"))
    as_of = _text(card.get("as_of_date"))

    paragraphs: list[str] = [
        "IFRS 9 (NIIF 9) exige reconocer provisiones por pérdida crediticia esperada (ECL) según "
        "el deterioro relativo de cada exposición: las operaciones sin aumento significativo del "
        "riesgo (Stage 1) provisionan la pérdida esperada a 12 meses, y las que lo presentan o ya "
        "están deterioradas (Stage 2 y 3) provisionan la pérdida esperada de por vida (IFRS 9 "
        "5.5.3 y 5.5.5). Este capítulo reporta el cálculo sobre la cartera de la corrida."
    ]

    if ecl is not None and ead is not None:
        titular = (
            f"Sobre una exposición al incumplimiento (EAD) de {_clp(ead)}, la pérdida crediticia "
            f"esperada a constituir es {_clp(ecl)}"
        )
        cobertura = (ecl / ead) if ead else None
        titular += f", una cobertura del {_pct(cobertura)}." if cobertura is not None else "."
        if as_of is not None:
            titular += f" Fecha de corte: {as_of}."
        paragraphs.append(titular)

    if n_rows is not None and n_s1 is not None and n_s2 is not None and n_s3 is not None:
        paragraphs.append(
            f"De las {_miles(n_rows)} operaciones de la cartera, {_miles(n_s1)} clasifican en "
            f"Stage 1, {_miles(n_s2)} en Stage 2 y {_miles(n_s3)} en Stage 3."
        )

    paragraphs.append(
        "El cálculo IFRS 9 es una función experimental (SDD-16 en borrador, fuera de la garantía "
        "SemVer 1.x): los números son trazables y deterministas, pero la superficie puede cambiar "
        "entre versiones."
    )
    return tuple(paragraphs)


def _results_provisioning_ifrs9(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Subsección de la ECL: de dónde sale la PD, los escenarios y qué muestra la tabla."""
    card = _card(bundle, "provisioning_ifrs9")
    if card is None:
        return ()
    paragraphs: list[str] = []

    term_source = str(card.get("term_structure_source") or "")
    pit_mode = str(card.get("pit_mode") or "")
    fuente = _IFRS9_TERM_SOURCE_LABELS.get(term_source, f"la fuente '{term_source}'")
    pit = _IFRS9_PIT_MODE_LABELS.get(pit_mode, pit_mode)
    paragraphs.append(
        f"La probabilidad de incumplimiento por periodo proviene de {fuente}, en modalidad {pit}. "
        "La ECL de cada operación multiplica PD marginal, LGD y EAD periodo a periodo y descuenta "
        "cada pérdida al presente; Stage 1 corta el horizonte a 12 meses y Stage 2/3 lo extienden "
        "a la vida remanente."
    )

    # Mecanismo PD→lifetime (la pregunta que un validador hace primero): se describe desde la
    # card del survival —lo que la corrida ajustó de verdad—, no desde el preset. Solo aplica si
    # la curva la produjo survival y su card viaja en el bundle.
    survival = _card(bundle, "survival")
    if term_source == "survival" and survival is not None:
        n_rows_surv = _int(survival.get("n_rows"))
        n_events = _int(survival.get("n_events"))
        n_censored = _int(_mapping(survival.get("diagnostics")).get("n_censored"))
        detalle = (
            "La curva lifetime no extrapola la PD de horizonte fijo del modelo: se estima un "
            "modelo de riesgo en tiempo discreto (discrete-time hazard) sobre la historia de "
            "duración censurada de la propia cartera"
        )
        if n_rows_surv is not None and n_events is not None:
            detalle += (
                f" ({_miles(n_rows_surv)} operaciones, {_miles(n_events)} eventos de "
                "incumplimiento observados"
            )
            detalle += f" y {_miles(n_censored)} censuradas)" if n_censored is not None else ")"
        detalle += (
            ". La probabilidad condicional de incumplimiento se estima período a período, y de "
            "ella se derivan la supervivencia y la PD marginal de cada período: la dimensión "
            "temporal la aportan los datos de duración, no un supuesto de hazard constante."
        )
        paragraphs.append(detalle)
        pd_source_surv = str(survival.get("pd_source") or "")
        if pd_source_surv == "model_raw":
            paragraphs.append(
                "El modelo PD estimado en esta misma corrida participa del ajuste como insumo: "
                "su rol es ordenar el riesgo entre operaciones; el nivel y la forma temporal de "
                "la curva los fija la historia observada."
            )
        elif pd_source_surv == "none":
            paragraphs.append(
                "El ajuste no toma insumos de un scorecard de originación: el orden de riesgo "
                "entre operaciones lo aportan covariables propias de la cartera, y el nivel y la "
                "forma temporal de la curva los fija la historia de duración observada. La "
                "pérdida esperada queda así autocontenida en el área IFRS 9."
            )

    scenarios = tuple(str(s) for s in _sequence(card.get("scenarios")))
    weights = _mapping(card.get("scenario_weights"))
    if len(scenarios) > 1:
        detalle = ", ".join(
            f"{name} ({_pct(weights.get(name))})" for name in scenarios if name in weights
        )
        paragraphs.append(
            "La ECL reportada pondera escenarios macroeconómicos, como pide IFRS 9 5.5.17: "
            + detalle
            + "."
        )
    elif scenarios:
        paragraphs.append(
            "La corrida usa un escenario único (sin ponderación macroeconómica múltiple); la "
            "norma admite incorporar escenarios adicionales cuando la entidad disponga de ellos."
        )

    paragraphs.append(
        "La tabla resume la cartera por etapa: número de operaciones, EAD, ECL reportada y "
        "cobertura. La distribución por etapas reconcilia exactamente con el total del capítulo."
    )

    warnings = tuple(str(code) for code in _sequence(card.get("falta_dato")))
    if warnings:
        descritos = tuple(_IFRS9_WARNING_LABELS.get(code, code) for code in warnings)
        paragraphs.append(
            "El step reportó advertencias de datos que el lector debe conocer: "
            + _enumerar(descritos)
            + "."
        )
    return tuple(paragraphs)


# ────────────────────────────── conclusiones y limitaciones ──────────────────────────────


def conclusions_body(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Resume los hallazgos que el motor sí puede afirmar; el juicio lo firma un humano."""
    hallazgos: list[str] = []

    performance = _card(bundle, "performance")
    if performance is not None:
        bands = _mapping(performance.get("bands_by_partition"))
        max_metrics = _mapping(performance.get("max_metrics_by_partition"))
        flagged = tuple(
            _partition_label(str(partition))
            for partition, band in sorted(bands.items(), key=lambda item: str(item[0]))
            if str(band) == "threshold_flag"
        )
        auc_por_particion = tuple(
            f"{_partition_label(str(partition))} {_num(_mapping(values).get('auc'), decimals=4)}"
            for partition, values in sorted(max_metrics.items(), key=lambda item: str(item[0]))
            if _float(_mapping(values).get("auc")) is not None
        )
        if auc_por_particion:
            hallazgos.append(f"Discriminación (AUC): {_enumerar(auc_por_particion)}.")
        if flagged:
            hallazgos.append(f"Hay alertas de discriminación bajo umbral en {_enumerar(flagged)}.")

    stability = _card(bundle, "stability")
    if stability is not None:
        bands = _mapping(stability.get("bands_by_comparison"))
        max_psi = _mapping(stability.get("max_psi_by_comparison"))
        detalles = tuple(
            f"{_comparison_label(str(comparison))} {_num(max_psi.get(comparison))} "
            f"(«{_STABILITY_BANDS.get(str(band), str(band))}»)"
            for comparison, band in sorted(bands.items(), key=lambda item: str(item[0]))
            if _float(max_psi.get(comparison)) is not None
        )
        if detalles:
            hallazgos.append(f"Estabilidad (PSI del score): {_enumerar(detalles)}.")
        criticas = tuple(
            _comparison_label(str(comparison))
            for comparison, band in sorted(bands.items(), key=lambda item: str(item[0]))
            if str(band) in {"review", "redevelop"}
        )
        if criticas:
            hallazgos.append(
                f"La estabilidad exige atención en {_enumerar(criticas)} antes de aprobar el uso "
                "continuado del modelo."
            )

    calibration = _card(bundle, "calibration")
    if calibration is not None:
        calibrated = _float(calibration.get("calibrated_mean_pd_dev"))
        observed = _float(calibration.get("observed_default_rate_dev"))
        if calibrated is not None and observed is not None:
            hallazgos.append(
                f"Calibración: la PD media calibrada en Desarrollo ({_pct(calibrated)}) se "
                f"contrasta con la tasa observada ({_pct(observed)})."
            )

    model = _card(bundle, "model")
    if model is not None:
        sign_flags = _sequence(model.get("sign_flags"))
        converged = _bool(_mapping(model.get("fit_statistics")).get("converged"))
        if converged is False:
            hallazgos.append("El ajuste del modelo no convergió: hallazgo bloqueante.")
        if sign_flags:
            hallazgos.append(
                f"Hay {len(sign_flags)} {_plural(len(sign_flags), 'variable', 'variables')} con "
                "el signo del coeficiente invertido."
            )

    if bundle.missing_sections:
        hallazgos.append(
            "El informe es parcial: faltan las secciones "
            f"{_enumerar(tuple(str(item) for item in bundle.missing_sections))}."
        )

    if not hallazgos:
        return (
            "El motor no dispone de hallazgos automáticos que resumir: la corrida no publicó las "
            "cards de desempeño, estabilidad ni calibración.",
        )
    hallazgos.append(
        "Estos hallazgos son los que el motor puede sostener con los números de la corrida. La "
        "recomendación —aprobar, aprobar con observaciones o rechazar— es un juicio humano y no "
        "se deriva automáticamente de ellos."
    )
    return tuple(hallazgos)


def limitations_body(bundle: ReportInputBundle) -> tuple[str, ...]:
    """Limitaciones: alcance de la fase, caveats de determinismo y secciones ausentes."""
    tiene_provisiones = _card(bundle, "provisioning") is not None
    tiene_ifrs9 = _card(bundle, "provisioning_ifrs9") is not None
    validation = _card(bundle, "validation") if "validation" in bundle.results else None
    validation_families = set(_sequence(validation.get("families_run"))) if validation else set()
    if tiene_ifrs9 and not tiene_provisiones:
        # Corrida IFRS 9 (SDD-16): el capítulo de ECL ES el alcance. Decir aquí que "IFRS 9
        # corresponde a fases posteriores" sería falso; y la cadena mínima ECL no corre la
        # validación completa del scorecard, así que tampoco se reclama (G8). La salvedad sobre
        # la curva PD depende de cómo se ajustó: standalone (pd_source='none') no hay modelo de
        # scorecard del que hablar.
        survival = _card(bundle, "survival")
        pd_source_surv = str(survival.get("pd_source") or "") if survival is not None else ""
        if pd_source_surv == "none":
            curva = (
                "La curva PD lifetime se ajustó en esta misma corrida de forma autocontenida "
                "sobre la historia de la propia cartera, sin insumos de un scorecard de "
                "originación."
            )
        else:
            curva = "El modelo PD que alimenta la curva se estimó en esta misma corrida."
        alcance = (
            "El alcance de este informe es el cálculo de la pérdida crediticia esperada IFRS 9 "
            "(capítulo «Provisiones IFRS 9 / ECL»), una función experimental (SDD-16 en "
            f"borrador) fuera de la garantía SemVer 1.x. {curva}"
        )
    elif tiene_provisiones:
        # Con provisiones en la corrida el informe deja de ser "solo validación de scorecard":
        # se declara el capítulo regulatorio (experimental) para no subdeclarar lo que el informe
        # sí contiene (G8, SDD-28 §11). La salvedad de IFRS 9 solo aplica si NO corrió.
        alcance = (
            "El informe cubre el scorecard y reporta además el cálculo regulatorio de "
            "provisiones (capítulo «Provisiones regulatorias»), una función experimental fuera "
            "de la garantía SemVer 1.x."
        )
        if tiene_ifrs9:
            alcance += (
                " La corrida calculó también la pérdida esperada IFRS 9 (capítulo «Provisiones "
                "IFRS 9 / ECL», igualmente experimental)."
            )
    else:
        alcance = "El alcance de este informe es la construcción y evaluación del scorecard."

    if validation is None:
        alcance += (
            " Esta corrida no ejecutó la capa de validación formal; el informe no infiere sus "
            "resultados."
        )
    else:
        families = tuple(
            _VALIDATION_FAMILY_LABELS.get(str(item), str(item))
            for item in _sequence(validation.get("families_run"))
        )
        alcance += (
            f" La validación formal ejecutó {_enumerar(families)} y se documenta en su capítulo "
            "propio; el estado técnico no sustituye el veredicto humano."
        )
    if tiene_ifrs9 and "backtesting" not in validation_families:
        alcance += " El backtesting de la ECL no se ejecutó ni se infiere aquí."
    paragraphs: list[str] = [
        alcance,
        "Todas las métricas provienen de la corrida trazada en el Anexo A. El informe no "
        "completa ningún hueco con supuestos: lo que no se pudo calcular aparece declarado como "
        "no disponible.",
    ]

    caveats = tuple(str(item) for item in _sequence(bundle.lineage.determinism_caveats))
    if caveats:
        paragraphs.append(
            f"Caveats de reproducibilidad declarados por la corrida: {_enumerar(caveats)}."
        )

    if bundle.missing_sections:
        paragraphs.append(
            "Secciones obligatorias ausentes en esta corrida: "
            f"{_enumerar(tuple(str(item) for item in bundle.missing_sections))}. El reporte "
            "declara la ausencia en vez de rellenarla."
        )
    else:
        paragraphs.append("No hay secciones obligatorias ausentes en esta corrida.")

    stability = _card(bundle, "stability")
    if stability is not None:
        metric_sections = _mapping(_mapping(stability.get("metric_sections")).get("stability"))
        if _bool(metric_sections.get("include_pd_stability")) is False:
            paragraphs.append(
                "La estabilidad de la PD calibrada no se evaluó en esta corrida (queda fuera del "
                "config): sólo se midió la del score."
            )
    return tuple(paragraphs)


# ────────────────────────────── acceso seguro y formato ──────────────────────────────


def _card(bundle: ReportInputBundle, domain: str) -> Mapping[str, Any] | None:
    """Devuelve la card cruda de un dominio, o ``None`` si la corrida no la publicó."""
    card = bundle.cards.get(domain)
    if isinstance(card, Mapping):
        return card
    return None


def _params(bundle: ReportInputBundle, domain: str) -> Mapping[str, Any]:
    """Devuelve la sección de config de un dominio; ``{}`` si no se ejecutó."""
    return _mapping(bundle.pipeline_params.get(domain))


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _float(value: Any) -> float | None:
    """Coacciona a float sólo lo que ya ES un número finito; nunca parsea ni asume.

    Acepta ``Decimal`` además de ``int``/``float``: las cards de provisiones publican sus cifras
    contables en ``Decimal`` y ``model_dump(mode="python")`` las conserva como tal.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float | Decimal):
        numeric = float(value)
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            return None
        return numeric
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def _bool(value: Any, default: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    return default


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _num(value: Any, *, decimals: int = 4) -> str:
    """Formatea un número real; un dato ausente se declara, no se inventa."""
    numeric = _float(value)
    if numeric is None:
        return _NOT_AVAILABLE
    if numeric == 0.0:
        numeric = 0.0
    return f"{numeric:.{decimals}f}"


def _pct(value: Any, *, decimals: int = 2) -> str:
    numeric = _float(value)
    if numeric is None:
        return _NOT_AVAILABLE
    return f"{numeric * 100:.{decimals}f} %"


def _clp(value: Any) -> str:
    """Formatea una cifra en pesos chilenos con separador de miles (``$697.376.974``).

    Una provisión sin unidad es ilegible para quien la lee en millones (SDD-28 §6.3.10). Se redondea
    al peso —la política ``rounding`` del motor ya cuantizó la cifra— y se usa el punto como
    separador de miles, convención chilena.
    """
    numeric = _float(value)
    if numeric is None:
        return _NOT_AVAILABLE
    return "$" + f"{round(numeric):,}".replace(",", ".")


def _miles(value: int) -> str:
    """Formatea un conteo con punto como separador de miles (``5.235``), convención es-CL."""
    return f"{value:,}".replace(",", ".")


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _enumerar(items: Sequence[str]) -> str:
    """Une frases con comas y una «y» final, como escribiría un humano."""
    values = tuple(item for item in items if item)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} y {values[-1]}"


def _capitalizar(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _partition_label(partition: str) -> str:
    return _PARTITION_LABELS.get(partition, partition)


def _comparison_label(comparison: str) -> str:
    return _COMPARISON_LABELS.get(comparison, comparison)


def _quality_label(flag: str) -> str:
    return {
        "near_constant": "variables casi constantes",
        "near_unique": "variables casi únicas",
        "high_cardinality": "variables de cardinalidad excesiva",
    }.get(flag, f"variables con la marca «{flag}»")


def _reason_label(reason: str) -> str:
    return {
        "business_exclude": "exclusión de negocio",
        "business_include": "inclusión forzada de negocio",
        "low_iv": "IV insuficiente",
        "high_iv": "IV excesivo (posible fuga)",
        "low_auc": "AUC insuficiente",
        "low_ks": "KS insuficiente",
        "low_gini": "Gini insuficiente",
        "high_correlation": "correlación excesiva",
        "high_vif": "VIF excesivo",
        "cluster_representative_lost": "no ser representante de su clúster",
        "constant_or_nonfinite": "ser constante o no finita",
        "missing_binning_artifact": "faltar su artefacto de binning",
        "forced_conflict": "conflicto entre reglas forzadas",
        "high_stability": "inestabilidad temporal",
    }.get(reason, f"la razón «{reason}»")


def _threshold_flags(card: Mapping[str, Any], partition: str) -> tuple[str, ...]:
    """Lee las métricas bajo umbral que ``performance`` publicó para una partición."""
    metric_sections = _mapping(card.get("metric_sections"))
    discrimination = _mapping(metric_sections.get("discrimination"))
    flags = _mapping(discrimination.get("threshold_flags_by_partition"))
    return tuple(str(item) for item in _sequence(flags.get(partition)))


def _not_evaluable_reason(card: Mapping[str, Any], partition: str) -> str | None:
    """Lee el motivo por el que una partición quedó no evaluable, si el motor lo declaró."""
    metric_sections = _mapping(card.get("metric_sections"))
    discrimination = _mapping(metric_sections.get("discrimination"))
    reasons = _mapping(discrimination.get("not_evaluable_reasons_by_partition"))
    return _text(reasons.get(partition))
