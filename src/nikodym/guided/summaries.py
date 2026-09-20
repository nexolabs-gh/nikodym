"""Resúmenes por etapa y resumen final de la puerta guiada (D-FLU-2, D-FLU-4; D-SIM-5).

Una sola fuente para texto, ``_repr_html_`` y —en la capa B— pantalla: cada resumen se arma
**sólo** con lo que su etapa o una anterior ya publicó en el ``ArtifactStore`` (las cards, las
tablas estables y los dos diagnósticos aditivos de §3.6), y todas las palabras que lee una
persona salen de los mapas de rótulos que ya existen —``report.prose``, ``validation.results``,
``stability.results``, ``selection.results``, ``binning.results``, ``eda``—. Aquí no hay una
segunda aritmética: se cuenta, se enumera y se formatea.

Los identificadores del motor (``low_iv``, ``dev_vs_oot``, ``hosmer_lemeshow``, los códigos de
aviso) no llegan a estas frases: lo gatea ``tests/unit/test_guided_summaries.py`` con el mismo
criterio que el informe (``test_report_codigos_internos``).
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np
import pandas as pd

from nikodym.binning.results import IV_BAND_LABELS
from nikodym.eda.default_rate import AXIS_LABELS
from nikodym.eda.quality import QUALITY_FLAG_LABELS
from nikodym.eda.stability import NOT_EVALUABLE_REASON_LABELS, STABILITY_INDICATOR_LABELS
from nikodym.report.prose import (
    _ANCHOR_KINDS,
    _ANCHOR_SOURCES,
    _CALIBRATION_METHODS,
    _COMPARISON_LABELS,
    _DISCRIMINANT_BANDS,
    _MONOTONIC_LABELS,
    _PARTITION_LABELS,
    _STEPWISE_DIRECTIONS,
    _declared_warning_descriptions,
    _enumerar,
    _miles,
    _num,
    _pct,
    _plural,
)
from nikodym.selection.results import REASON_LABELS
from nikodym.stability.results import (
    BAND_LABELS,
    PSI_METRIC_LABELS,
    STABILITY_METRIC_LABELS,
    TEMPORAL_AXIS_LABELS,
)
from nikodym.validation.results import (
    CALIBRATION_TEST_LABELS,
    HL_NOT_EVALUABLE_REASON_LABELS,
    VALIDATION_DECISION_LABELS,
    VALIDATION_FAMILY_LABELS,
    VALIDATION_STATUS_LABELS,
)

if TYPE_CHECKING:
    from nikodym.core.study import Study

__all__ = [
    "STAGE_LABELS",
    "STAGE_ORDER",
    "FinalSummary",
    "StageSummary",
    "SummaryContext",
    "build_final_summary",
    "build_stage_summary",
]

#: Rótulo en español de cada etapa, en el orden del pipeline (D-FLU-2 §3.2). Los nombres son los
#: de las secciones del config y de los pasos; los rótulos, lo que lee una persona (D-SIM-9).
STAGE_LABELS: Final[dict[str, str]] = {
    "data": "Datos y muestras",
    "eda": "Análisis exploratorio",
    "binning": "Tramos y WoE",
    "selection": "Selección de variables",
    "model": "Modelo",
    "scorecard": "Tarjeta de puntuación",
    "calibration": "Calibración",
    "performance": "Desempeño",
    "stability": "Estabilidad",
    "validation": "Validación formal",
    "report": "Informe y ficha",
}
STAGE_ORDER: Final[tuple[str, ...]] = tuple(STAGE_LABELS)

#: Filas de una tabla de decisión que el texto de consola muestra antes de resumir el resto; el
#: HTML del notebook y ``sc.results[<etapa>]`` llevan la tabla entera.
_FILAS_EN_CONSOLA: Final = 40

_Kind = Literal["text", "int", "num", "num2", "num3", "pct", "bool"]

#: Acciones del stepwise en palabras (``model.results.StepwiseDecision.action``).
_STEPWISE_ACTION_LABELS: Final[dict[str, str]] = {
    "enter": "entra",
    "remove": "sale",
    "keep": "se mantiene",
    "flag": "queda marcada",
    "exclude": "se excluye",
}
#: Criterios del stepwise y de las guardas de signo e IV en palabras.
_STEPWISE_CRITERION_LABELS: Final[dict[str, str]] = {
    "wald_pvalue": "p-valor de Wald",
    "lr_test": "test de razón de verosimilitud",
    "both": "p-valor de Wald y test de razón de verosimilitud",
    "sign": "signo del coeficiente",
    "iv_contribution": "contribución al IV",
    "force_include": "inclusión forzada",
    "force_exclude": "exclusión forzada",
}


@dataclass(frozen=True, slots=True)
class SummaryContext:
    """Lo que la puerta sabe y el ``Study`` no: rutas, inferencias y decisiones humanas."""

    project_dir: Path
    run_dir: Path
    source_label: str
    partition_label: str
    inference_lines: tuple[str, ...] = ()
    decision_lines: tuple[str, ...] = ()
    report_dir: Path | None = None
    trail_path: Path | None = None
    card_path: Path | None = None
    config_path: Path | None = None
    until: str | None = None


@dataclass(frozen=True, slots=True)
class StageSummary:
    """El resumen de una etapa: de 3 a 8 líneas, sus alertas y su tabla de decisión (D-SIM-5)."""

    stage: str
    label: str
    lines: tuple[str, ...]
    alerts: tuple[str, ...] = ()
    table: pd.DataFrame | None = None
    formats: Mapping[str, _Kind] = field(default_factory=dict)

    def text(self, *, with_table: bool = True) -> str:
        """El resumen como texto para la consola."""
        partes = [f"── {self.label} ──", *self.lines]
        partes.extend(f"⚠ {alerta}" for alerta in self.alerts)
        if with_table and self.table is not None and not self.table.empty:
            mostrada = _formatear(self.table, self.formats)
            partes.append(mostrada.head(_FILAS_EN_CONSOLA).to_string(index=False))
            resto = len(mostrada.index) - _FILAS_EN_CONSOLA
            if resto > 0:
                partes.append(
                    f"… y {_miles(resto)} {_plural(resto, 'fila más', 'filas más')} en "
                    f"sc.results[{self.stage!r}]"
                )
        return "\n".join(partes)

    def __str__(self) -> str:
        """El texto del resumen."""
        return self.text()

    def _repr_html_(self) -> str:
        """El mismo resumen para el notebook."""
        partes = [f"<h3>{html.escape(self.label)}</h3>", "<ul>"]
        partes.extend(f"<li>{html.escape(linea)}</li>" for linea in self.lines)
        partes.append("</ul>")
        if self.alerts:
            partes.append("<ul>")
            partes.extend(f"<li>⚠ {html.escape(alerta)}</li>" for alerta in self.alerts)
            partes.append("</ul>")
        if self.table is not None and not self.table.empty:
            partes.append(_formatear(self.table, self.formats).to_html(index=False, border=0))
        return f'<div class="nikodym-summary">{"".join(partes)}</div>'


@dataclass(frozen=True, slots=True)
class FinalSummary:
    """El resumen final (D-FLU-4).

    Ejecución y validación técnica por separado, cinco cifras, qué revisar, decisiones y archivos.
    """

    execution: str
    validation: str
    figures: tuple[tuple[str, str], ...]
    review: tuple[str, ...]
    decisions: tuple[str, ...]
    files: tuple[tuple[str, str], ...]
    stages: tuple[StageSummary, ...] = ()

    def text(self) -> str:
        """El resumen final como texto para la consola."""
        partes = ["══ Resumen del scorecard ══", f"Ejecución: {self.execution}"]
        partes.append(f"Validación técnica: {self.validation}")
        if self.figures:
            partes.append("Cifras clave:")
            partes.extend(f"  {rotulo}: {valor}" for rotulo, valor in self.figures)
        partes.append("Qué revisar:")
        if self.review:
            partes.extend(f"  ⚠ {alerta}" for alerta in self.review)
        else:
            partes.append("  Sin alertas en ninguna etapa.")
        partes.append("Decisiones humanas registradas:")
        if self.decisions:
            partes.extend(f"  • {linea}" for linea in self.decisions)
        else:
            partes.append("  Ninguna: la corrida usa los valores de fábrica.")
        partes.append("Dónde quedó cada archivo:")
        partes.extend(f"  {rotulo}: {ruta}" for rotulo, ruta in self.files)
        return "\n".join(partes)

    def __str__(self) -> str:
        """El texto del resumen final."""
        return self.text()

    def _repr_html_(self) -> str:
        """El mismo resumen final para el notebook."""
        partes = ["<h2>Resumen del scorecard</h2>"]
        partes.append(f"<p><b>Ejecución:</b> {html.escape(self.execution)}</p>")
        partes.append(f"<p><b>Validación técnica:</b> {html.escape(self.validation)}</p>")
        if self.figures:
            partes.append("<table><tbody>")
            partes.extend(
                f"<tr><th>{html.escape(rotulo)}</th><td>{html.escape(valor)}</td></tr>"
                for rotulo, valor in self.figures
            )
            partes.append("</tbody></table>")
        partes.append("<h4>Qué revisar</h4><ul>")
        if self.review:
            partes.extend(f"<li>⚠ {html.escape(alerta)}</li>" for alerta in self.review)
        else:
            partes.append("<li>Sin alertas en ninguna etapa.</li>")
        partes.append("</ul><h4>Decisiones humanas registradas</h4><ul>")
        if self.decisions:
            partes.extend(f"<li>{html.escape(linea)}</li>" for linea in self.decisions)
        else:
            partes.append("<li>Ninguna: la corrida usa los valores de fábrica.</li>")
        partes.append("</ul><h4>Dónde quedó cada archivo</h4><ul>")
        partes.extend(
            f"<li>{html.escape(rotulo)}: <code>{html.escape(ruta)}</code></li>"
            for rotulo, ruta in self.files
        )
        partes.append("</ul>")
        return f'<div class="nikodym-summary">{"".join(partes)}</div>'


# ────────────────────────────── resúmenes por etapa ──────────────────────────────


def build_stage_summary(stage: str, study: Study, context: SummaryContext) -> StageSummary:
    """Arma el resumen de ``stage`` con lo que el ``Study`` ya publicó."""
    builder = _BUILDERS.get(stage)
    label = STAGE_LABELS.get(stage, stage)
    if builder is None:
        return StageSummary(stage=stage, label=label, lines=("Etapa sin resumen propio.",))
    return builder(study, context)


def _resumen_data(study: Study, context: SummaryContext) -> StageSummary:
    card = _card(study, "data", "data_card")
    lines: list[str] = [f"Archivo: {context.source_label}"]
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        n_rows = _int(card.get("n_rows")) or 0
        class_counts = _mapping(card.get("class_counts"))
        n_bad = _int(class_counts.get("malo")) or 0
        lines.append(
            f"{_miles(n_rows)} filas · {_miles(n_bad)} malos "
            f"({_pct(card.get('bad_rate'))}) · {_miles(_int(card.get('n_features')) or 0)} columnas"
        )
        sizes = _mapping(card.get("partition_sizes"))
        rates = _mapping(card.get("partition_bad_rates"))
        muestras = tuple(
            f"{_partition_label(str(p))} {_miles(_int(n) or 0)} ({_pct(rates.get(p))})"
            for p, n in sizes.items()
            if str(p) != "fuera_de_modelo" and (_int(n) or 0) > 0
        )
        if muestras:
            lines.append(f"Muestras: {' · '.join(muestras)} — {context.partition_label}")
        fuera = _int(sizes.get("fuera_de_modelo")) or 0
        indeterminados = _int(class_counts.get("indeterminado")) or 0
        excluidos = _int(class_counts.get("excluido")) or 0
        if fuera or indeterminados or excluidos:
            lines.append(
                f"Fuera del ajuste: {_miles(indeterminados)} indeterminadas y "
                f"{_miles(excluidos)} excluidas ({_miles(fuera)} fuera de modelo); se puntúan, "
                "no se ajustan"
            )
        table = _tabla_muestras(study)
    lines.extend(context.inference_lines)
    lines.append(f"Evidencia de la corrida: {context.run_dir}")
    return StageSummary(
        stage="data",
        label=STAGE_LABELS["data"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats={"Filas": "int", "Malos": "int", "Tasa de malos": "pct"},
    )


def _tabla_muestras(study: Study) -> pd.DataFrame | None:
    frame = _artifact(study, "data", "frame")
    labels = _artifact(study, "data", "labels")
    splits = _artifact(study, "data", "splits")
    if not isinstance(frame, pd.DataFrame) or labels is None or splits is None:
        return None
    target_col = getattr(labels, "target_col", "target")
    partition_col = getattr(splits, "partition_col", "partition")
    if target_col not in frame.columns or partition_col not in frame.columns:
        return None
    filas: list[dict[str, Any]] = []
    particiones = frame[partition_col].astype("string")
    for particion in ("desarrollo", "holdout", "oot", "fuera_de_modelo"):
        mascara = particiones.eq(particion).fillna(False).astype(bool)
        n = int(mascara.sum())
        if n == 0:
            continue
        objetivo = frame.loc[mascara, target_col]
        con_target = objetivo.notna()
        malos = int(objetivo[con_target].astype(float).sum()) if con_target.any() else 0
        tasa = malos / int(con_target.sum()) if con_target.any() else float("nan")
        filas.append(
            {
                "Muestra": _partition_label(particion),
                "Filas": n,
                "Malos": malos,
                "Tasa de malos": tasa,
            }
        )
    return pd.DataFrame(filas)


def _resumen_eda(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "eda", "eda_card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    formats: dict[str, _Kind] = {}
    if card is not None:
        eje = AXIS_LABELS.get(str(card.get("axis")), str(card.get("axis")))
        n_periods = _int(card.get("n_periods")) or 0
        lines.append(
            f"Tasa de malos {eje}: {_miles(n_periods)} "
            f"{_plural(n_periods, 'período', 'períodos')}, media "
            f"{_pct(card.get('overall_default_rate'))}"
        )
        causa = card.get("stability_not_evaluable_reason")
        indicador = STABILITY_INDICATOR_LABELS.get(
            str(card.get("stability_metric_used")), str(card.get("stability_metric_used"))
        )
        if causa:
            lines.append(
                "Deterioro de la tasa en el tiempo: no evaluable "
                f"({NOT_EVALUABLE_REASON_LABELS.get(str(causa), str(causa))})"
            )
        elif card.get("stability_flagged"):
            alerts.append(
                f"La tasa de malos se deteriora en el tiempo: {indicador} "
                f"{_num(card.get('stability_value'))} supera el umbral "
                f"{_num(card.get('stability_threshold'))}"
            )
        else:
            lines.append(
                f"Deterioro de la tasa en el tiempo: sin señal ({indicador} "
                f"{_num(card.get('stability_value'))}, umbral "
                f"{_num(card.get('stability_threshold'))})"
            )
        lines.append(
            f"{_miles(_int(card.get('n_columns_profiled')) or 0)} columnas descritas frente al "
            "incumplimiento"
        )
        marcas = _marcas_de_calidad(study)
        if marcas:
            lines.append(f"Marcas de calidad del archivo: {_enumerar(marcas)}")
        else:
            lines.append("Marcas de calidad del archivo: ninguna")
        tasa = _artifact(study, "eda", "default_rate")
        by_period = getattr(tasa, "by_period", None)
        if isinstance(by_period, pd.DataFrame) and not by_period.empty:
            columnas = {
                "period": eje.capitalize(),
                "n_eligible": "Filas",
                "n_bad": "Malos",
                "default_rate": "Tasa de malos",
                "low_confidence": "Poca confianza",
            }
            table = by_period[[c for c in columnas if c in by_period.columns]].rename(
                columns=columnas
            )
            formats = {"Filas": "int", "Malos": "int", "Tasa de malos": "pct"}
    if not lines:
        lines.append("El análisis exploratorio no publicó su resumen.")
    return StageSummary(
        stage="eda",
        label=STAGE_LABELS["eda"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats=formats,
    )


def _marcas_de_calidad(study: Study) -> tuple[str, ...]:
    quality = _artifact(study, "eda", "quality")
    by_column = getattr(quality, "by_column", None)
    if not isinstance(by_column, pd.DataFrame) or by_column.empty:
        return ()
    marcas: list[str] = []
    for flag, rotulo in QUALITY_FLAG_LABELS.items():
        if flag not in by_column.columns:
            continue
        columnas = [str(c) for c in by_column.loc[by_column[flag].astype(bool), "col"]]
        if columnas:
            marcas.append(f"{rotulo}: {', '.join(columnas)}")
    return tuple(marcas)


def _resumen_binning(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "binning", "binning_card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        n_binned = _int(card.get("n_variables_binned")) or 0
        n_requested = _int(card.get("n_variables_requested")) or 0
        n_skipped = _int(card.get("n_variables_skipped")) or 0
        lines.append(
            f"{_miles(n_binned)} de {_miles(n_requested)} variables tramificadas"
            + (f"; {_miles(n_skipped)} no tramificables" if n_skipped else "")
        )
        excluded = tuple(str(c) for c in _sequence(card.get("excluded_by_target_rule")))
        if excluded:
            lines.append(
                f"Fuera por definir el incumplimiento (fuga de información): {', '.join(excluded)}"
            )
        summary = _artifact(study, "binning", "summary")
        if isinstance(summary, pd.DataFrame) and not summary.empty:
            bandas: dict[str, list[str]] = {}
            for _, fila in summary.iterrows():
                if fila.get("skipped_reason"):
                    continue
                banda = IV_BAND_LABELS.get(str(fila.get("iv_band")), str(fila.get("iv_band")))
                bandas.setdefault(banda, []).append(str(fila.get("name")))
            if bandas:
                lines.append(
                    "Poder predictivo (IV): "
                    + " · ".join(f"{banda}: {', '.join(vs)}" for banda, vs in bandas.items())
                )
            sospechosas = [
                str(fila.get("name"))
                for _, fila in summary.iterrows()
                if bool(fila.get("is_suspicious_iv"))
            ]
            if sospechosas:
                alerts.append(
                    "IV sospechosamente alto (posible fuga de información): "
                    f"{', '.join(sospechosas)}"
                )
            omitidas = [
                f"{fila.get('name')} ({fila.get('skipped_reason')})"
                for _, fila in summary.iterrows()
                if fila.get("skipped_reason")
            ]
            if omitidas:
                lines.append(f"No tramificables: {', '.join(omitidas)}")
            columnas = {
                "name": "Variable",
                "dtype": "Tipo",
                "n_bins": "Tramos",
                "iv": "IV",
                "iv_band": "Banda de IV",
                "monotonic_trend": "Tendencia",
            }
            table = summary[[c for c in columnas if c in summary.columns]].rename(columns=columnas)
            table["Banda de IV"] = table["Banda de IV"].map(lambda v: IV_BAND_LABELS.get(str(v), v))
            table["Tendencia"] = table["Tendencia"].map(
                lambda v: _MONOTONIC_LABELS.get(str(v), v) if v is not None else "—"
            )
            table["Tipo"] = table["Tipo"].map(
                lambda v: {"numerical": "numérica", "categorical": "categórica"}.get(str(v), v)
            )
        alerts.extend(_alertas_de_inversion(study))
    if not lines:
        lines.append("El binning no publicó su resumen.")
    return StageSummary(
        stage="binning",
        label=STAGE_LABELS["binning"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats={"Tramos": "int", "IV": "num3"},
    )


def _alertas_de_inversion(study: Study) -> tuple[str, ...]:
    """«Invierte en <muestra>» por variable, desde ``("binning", "event_rate_by_partition")``."""
    tasas = _artifact(study, "binning", "event_rate_by_partition")
    if not isinstance(tasas, pd.DataFrame) or tasas.empty or "inverts" not in tasas.columns:
        return ()
    invierte = tasas[tasas["inverts"].fillna(False).astype(bool)]
    if invierte.empty:
        return ()
    alertas: list[str] = []
    for variable, filas in invierte.groupby("feature", sort=True):
        muestras = sorted({str(p) for p in filas["partition"]}, key=_orden_particion)
        alertas.append(
            f"{variable}: la tasa de malos invierte la tendencia en "
            f"{_enumerar(tuple(_partition_label(p) for p in muestras))}"
        )
    return tuple(alertas)


def _resumen_selection(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "selection", "selection_card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    formats: dict[str, _Kind] = {}
    if card is not None:
        n_sel = _int(card.get("n_selected")) or 0
        n_cand = _int(card.get("n_candidates")) or 0
        lines.append(f"Entran {_miles(n_sel)} de {_miles(n_cand)} variables candidatas")
        tabla = _artifact(study, "selection", "selection_table")
        if isinstance(tabla, pd.DataFrame) and not tabla.empty:
            salen = [
                f"{fila.get('feature')} ({_rotulo(REASON_LABELS, fila.get('reason'))})"
                for _, fila in tabla.iterrows()
                if not bool(fila.get("included"))
            ]
            if salen:
                lines.append(f"Salen: {', '.join(salen)}")
            columnas = {
                "feature": "Variable",
                "included": "Entra",
                "reason": "Motivo",
                "iv": "IV",
                "auc": "AUC",
                "ks": "KS",
                "max_abs_corr": "Correlación máxima",
                "vif": "VIF",
            }
            table = tabla[[c for c in columnas if c in tabla.columns]].rename(columns=columnas)
            table["Motivo"] = table["Motivo"].map(lambda v: REASON_LABELS.get(str(v), v))
            table["Entra"] = table["Entra"].map(lambda v: "sí" if bool(v) else "no")
            formats = {
                "IV": "num3",
                "AUC": "num3",
                "KS": "num3",
                "Correlación máxima": "num3",
                "VIF": "num2",
            }
            table = _anexar_iv_por_muestra(study, table)
            for muestra in ("Desarrollo", "Holdout", "Fuera de tiempo (OOT)"):
                if f"IV {muestra}" in table.columns:
                    formats[f"IV {muestra}"] = "num3"
        corr = card.get("max_abs_correlation_after_selection")
        vif = card.get("max_vif_after_selection")
        frases: list[str] = []
        if corr is not None:
            frases.append(f"correlación máxima entre las finales {_num(corr, decimals=3)}")
        if vif is not None:
            frases.append(f"VIF máximo {_num(vif, decimals=2)}")
        if frases:
            lines.append(_capitalizar(_enumerar(tuple(frases))))
        high_iv = tuple(str(c) for c in _sequence(card.get("high_iv_flags")))
        if high_iv:
            alerts.append(
                f"IV excesivo (posible fuga de información), explicar antes de aprobar: "
                f"{', '.join(high_iv)}"
            )
        inestables = tuple(str(c) for c in _sequence(card.get("stability_flags")))
        if inestables:
            alerts.append(f"Inestabilidad temporal: {', '.join(inestables)}")
        alerts.extend(_alertas_iv_por_muestra(study))
    if not lines:
        lines.append("La selección no publicó su resumen.")
    return StageSummary(
        stage="selection",
        label=STAGE_LABELS["selection"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats=formats,
    )


def _anexar_iv_por_muestra(study: Study, table: pd.DataFrame) -> pd.DataFrame:
    """Suma a la tabla de decisión el IV por muestra de ``("selection", "iv_by_partition")``."""
    iv = _artifact(study, "selection", "iv_by_partition")
    if not isinstance(iv, pd.DataFrame) or iv.empty or "Variable" not in table.columns:
        return table
    ancho = iv.pivot_table(index="feature", columns="partition", values="iv", aggfunc="first")
    salida = table.copy()
    for particion in ("desarrollo", "holdout", "oot"):
        if particion in ancho.columns:
            salida[f"IV {_partition_label(particion)}"] = salida["Variable"].map(ancho[particion])
    return salida


def _alertas_iv_por_muestra(study: Study) -> tuple[str, ...]:
    iv = _artifact(study, "selection", "iv_by_partition")
    if not isinstance(iv, pd.DataFrame) or iv.empty or "not_evaluable_reason" not in iv.columns:
        return ()
    sin_evaluar = iv[iv["not_evaluable_reason"].notna()]
    if sin_evaluar.empty:
        return ()
    muestras = sorted({str(p) for p in sin_evaluar["partition"]}, key=_orden_particion)
    return (
        "IV por muestra no evaluable en "
        f"{_enumerar(tuple(_partition_label(p) for p in muestras))}: la muestra tiene una sola "
        "clase",
    )


def _resumen_model(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "model", "model_card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        finales = tuple(str(c) for c in _sequence(card.get("final_features")))
        lines.append(
            f"Variables finales ({_miles(len(finales))}): {', '.join(finales) or 'ninguna'}"
        )
        umbrales = _mapping(card.get("thresholds"))
        direccion = str(umbrales.get("stepwise.direction", "none"))
        lines.extend(_traza_del_stepwise(study, direccion))
        fit = _mapping(card.get("fit_statistics"))
        if fit:
            partes = [
                f"pseudo-R² de McFadden {_num(fit.get('pseudo_r2_mcfadden'), decimals=3)}",
                f"AIC {_num(fit.get('aic'), decimals=1)}",
            ]
            if fit.get("llr_p_value") is not None:
                partes.append(
                    f"p-valor del test de razón de verosimilitud {_pvalor(fit.get('llr_p_value'))}"
                )
            partes.append("convergió" if fit.get("converged") else "NO convergió")
            lines.append(f"Ajuste en Desarrollo: {' · '.join(partes)}")
            if fit.get("converged") is False:
                alerts.append(
                    "El ajuste no convergió: la inferencia sobre los coeficientes no es válida"
                )
        signos = tuple(str(c) for c in _sequence(card.get("sign_flags")))
        if signos:
            alerts.append(
                "Coeficiente con el signo invertido respecto del riesgo esperado: "
                f"{', '.join(signos)}"
            )
        concentran = tuple(str(c) for c in _sequence(card.get("iv_contribution_flags")))
        if concentran:
            umbral = umbrales.get("iv_contribution.threshold")
            alerts.append(
                f"Concentra más del {_pct(umbral, decimals=0)} del IV del modelo: "
                f"{', '.join(concentran)}"
            )
        coeficientes = _artifact(study, "model", "coefficients")
        if isinstance(coeficientes, pd.DataFrame) and not coeficientes.empty:
            columnas = {
                "feature": "Variable",
                "beta": "Coeficiente",
                "standard_error": "Error estándar",
                "p_value": "p-valor",
                "sign_ok": "Signo esperado",
                "iv": "IV",
                "iv_contribution": "Contribución al IV",
            }
            table = coeficientes[[c for c in columnas if c in coeficientes.columns]].rename(
                columns=columnas
            )
            table["Variable"] = table["Variable"].map(
                lambda v: "intercepto" if str(v) == "intercept" else v
            )
            table["Signo esperado"] = table["Signo esperado"].map(
                lambda v: (
                    "—"
                    if v is None or (isinstance(v, float) and pd.isna(v))
                    else ("sí" if bool(v) else "no")
                )
            )
    if not lines:
        lines.append("El modelo no publicó su resumen.")
    return StageSummary(
        stage="model",
        label=STAGE_LABELS["model"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats={
            "Coeficiente": "num",
            "Error estándar": "num",
            "p-valor": "num",
            "IV": "num3",
            "Contribución al IV": "pct",
        },
    )


def _traza_del_stepwise(study: Study, direccion: str) -> tuple[str, ...]:
    """Qué salió, qué entró y por qué, en palabras, desde ``("model", "stepwise_trace")``."""
    traza = _artifact(study, "model", "stepwise_trace")
    decisiones = list(traza) if isinstance(traza, list | tuple) else []
    if not decisiones:
        return (f"Ajuste {_STEPWISE_DIRECTIONS.get(direccion, direccion)}",)
    iteraciones = max((_int(getattr(d, "iteration", 0)) or 0) for d in decisiones)
    entradas = [d for d in decisiones if getattr(d, "action", "") == "enter"]
    salidas = [d for d in decisiones if getattr(d, "action", "") in {"remove", "exclude"}]
    lineas = [
        f"{_capitalizar(_STEPWISE_DIRECTIONS.get(direccion, direccion))}: "
        f"{_miles(iteraciones)} {_plural(iteraciones, 'iteración', 'iteraciones')}, "
        f"{_miles(len(entradas))} {_plural(len(entradas), 'entrada', 'entradas')} y "
        f"{_miles(len(salidas))} {_plural(len(salidas), 'salida', 'salidas')}"
    ]
    for d in salidas:
        criterio = _STEPWISE_CRITERION_LABELS.get(str(getattr(d, "criterion", "")), "")
        detalle = _detalle_stepwise(d)
        lineas.append(
            f"  Sale {getattr(d, 'feature', '')} en la iteración "
            f"{_miles(_int(getattr(d, 'iteration', 0)) or 0)} por {criterio}{detalle}"
        )
    return tuple(lineas)


def _detalle_stepwise(decision: Any) -> str:
    p_value = getattr(decision, "p_value", None)
    threshold = getattr(decision, "threshold", None)
    if p_value is not None and threshold is not None:
        return f" (p-valor {_pvalor(p_value)}, umbral {_num(threshold, decimals=2)})"
    beta = getattr(decision, "beta", None)
    if beta is not None:
        return f" (coeficiente {_num(beta, decimals=3)})"
    return ""


def _resumen_scorecard(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "scorecard", "card")
    lines: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        lines.append(
            f"Escala: {_num(card.get('pdo'), decimals=0)} puntos por duplicar las odds, "
            f"{_num(card.get('target_score'), decimals=0)} puntos a odds "
            f"{_num(card.get('target_odds'), decimals=0)}:1 "
            f"(factor {_num(card.get('factor'), decimals=2)}, "
            f"desplazamiento {_num(card.get('offset'), decimals=2)})"
        )
        score = _artifact(study, "scorecard", "score")
        columna = str(card.get("score_column", "score"))
        if isinstance(score, pd.DataFrame) and columna in score.columns and not score.empty:
            valores = pd.to_numeric(score[columna], errors="coerce").dropna()
            if not valores.empty:
                lines.append(
                    f"Puntajes observados: de {_num(valores.min(), decimals=0)} a "
                    f"{_num(valores.max(), decimals=0)} (media {_num(valores.mean(), decimals=1)})"
                )
        n_var = _int(card.get("n_variables")) or 0
        lines.append(
            f"{_miles(n_var)} {_plural(n_var, 'variable con puntos', 'variables con puntos')}; "
            + (
                "un puntaje más alto indica menor riesgo"
                if card.get("score_direction") == "higher_is_lower_risk"
                else "un puntaje más alto indica mayor riesgo"
            )
        )
        overrides = _int(card.get("overrides_count")) or 0
        if overrides:
            lines.append(f"Puntos fijados a mano en {_miles(overrides)} tramos")
        tarjeta = _artifact(study, "scorecard", "scorecard")
        if isinstance(tarjeta, pd.DataFrame) and not tarjeta.empty:
            columnas = {
                "feature": "Variable",
                "bin_label": "Tramo",
                "woe": "WoE",
                "points": "Puntos",
            }
            table = tarjeta[[c for c in columnas if c in tarjeta.columns]].rename(columns=columnas)
    if not lines:
        lines.append("La tarjeta no publicó su resumen.")
    return StageSummary(
        stage="scorecard",
        label=STAGE_LABELS["scorecard"],
        lines=tuple(lines),
        table=table,
        formats={"WoE": "num3", "Puntos": "int"},
    )


def _resumen_calibration(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "calibration", "card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        metodo = _CALIBRATION_METHODS.get(str(card.get("method")), str(card.get("method")))
        fuente = _ANCHOR_SOURCES.get(str(card.get("anchor_source")), str(card.get("anchor_source")))
        tipo = _ANCHOR_KINDS.get(str(card.get("anchor_kind")), str(card.get("anchor_kind")))
        lines.append(f"Método: {metodo}; ancla {tipo}: {fuente} = {_pct(card.get('target_pd'))}")
        lines.append(
            f"PD media en Desarrollo: cruda {_pct(card.get('raw_mean_pd_dev'))} → calibrada "
            f"{_pct(card.get('calibrated_mean_pd_dev'))}"
            + (
                f" (desplazamiento del intercepto {_num(card.get('offset'), decimals=4)})"
                if card.get("offset") is not None
                else ""
            )
        )
        empates = _int(card.get("ties_created")) or 0
        lines.append(
            "Orden de riesgo preservado"
            if card.get("ranking_preserved")
            else "El orden de riesgo NO se preservó"
        )
        if not card.get("ranking_preserved"):
            alerts.append("La calibración alteró el orden de riesgo entre operaciones")
        if empates:
            alerts.append(f"La calibración creó {_miles(empates)} empates de PD")
        table = _tabla_pd_por_muestra(study, card)
    if not lines:
        lines.append("La calibración no publicó su resumen.")
    return StageSummary(
        stage="calibration",
        label=STAGE_LABELS["calibration"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats={
            "Filas": "int",
            "PD media cruda": "pct",
            "PD media calibrada": "pct",
            "Tasa de malos observada": "pct",
        },
    )


def _tabla_pd_por_muestra(study: Study, card: Mapping[str, Any]) -> pd.DataFrame | None:
    frame = _artifact(study, "calibration", "calibrated_pd_frame")
    if not isinstance(frame, pd.DataFrame) or frame.empty or "partition" not in frame.columns:
        return None
    cruda = str(card.get("pd_raw_column", "pd_raw"))
    calibrada = str(card.get("pd_calibrated_column", "pd_calibrated"))
    if cruda not in frame.columns or calibrada not in frame.columns:
        return None
    filas: list[dict[str, Any]] = []
    particiones = frame["partition"].astype("string")
    for particion in ("desarrollo", "holdout", "oot"):
        mascara = particiones.eq(particion).fillna(False).astype(bool)
        if not mascara.any():
            continue
        sub = frame.loc[mascara]
        fila: dict[str, Any] = {
            "Muestra": _partition_label(particion),
            "Filas": int(mascara.sum()),
            "PD media cruda": float(pd.to_numeric(sub[cruda], errors="coerce").mean()),
            "PD media calibrada": float(pd.to_numeric(sub[calibrada], errors="coerce").mean()),
        }
        if "target" in sub.columns:
            objetivo = pd.to_numeric(sub["target"], errors="coerce").dropna()
            fila["Tasa de malos observada"] = (
                float(objetivo.mean()) if not objetivo.empty else float("nan")
            )
        filas.append(fila)
    return pd.DataFrame(filas)


def _resumen_performance(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "performance", "card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        maximos = _mapping(card.get("max_metrics_by_partition"))
        bandas = _mapping(card.get("bands_by_partition"))
        for particion in _sequence(card.get("partitions")):
            pid = str(particion)
            valores = _mapping(maximos.get(pid))
            banda = str(bandas.get(pid, ""))
            if banda == "not_evaluable":
                alerts.append(
                    f"Discriminación no evaluable en {_partition_label(pid)}"
                    + _causa_no_evaluable(card, pid)
                )
                continue
            lines.append(
                f"{_partition_label(pid)}: AUC {_num(valores.get('auc'), decimals=3)} · "
                f"Gini {_num(valores.get('gini'), decimals=3)} · "
                f"KS {_num(valores.get('ks'), decimals=3)}"
            )
            if banda == "threshold_flag":
                alerts.append(
                    f"{_partition_label(pid)}: {_DISCRIMINANT_BANDS['threshold_flag'].lower()}"
                )
        caida = _caida_dev_oot(maximos)
        if caida is not None:
            lines.append(caida)
        tabla = _artifact(study, "performance", "performance_table")
        if isinstance(tabla, pd.DataFrame) and not tabla.empty:
            columnas = {
                "partition": "Muestra",
                "decile": "Decil",
                "n_total": "Filas",
                "n_bad": "Malos",
                "bad_rate": "Tasa de malos",
                "mean_pd": "PD media",
                "mean_score": "Puntaje medio",
                "cum_bad_capture_rate": "Captura acumulada de malos",
                "ks_at_decile": "KS en el decil",
            }
            table = tabla[[c for c in columnas if c in tabla.columns]].rename(columns=columnas)
            table["Muestra"] = table["Muestra"].map(lambda v: _partition_label(str(v)))
            table = table.reset_index(drop=True)
    if not lines and not alerts:
        lines.append("El desempeño no publicó su resumen.")
    return StageSummary(
        stage="performance",
        label=STAGE_LABELS["performance"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats={
            "Decil": "int",
            "Filas": "int",
            "Malos": "int",
            "Tasa de malos": "pct",
            "PD media": "pct",
            "Puntaje medio": "num2",
            "Captura acumulada de malos": "pct",
            "KS en el decil": "num3",
        },
    )


def _caida_dev_oot(maximos: Mapping[str, Any]) -> str | None:
    """La caída Desarrollo → OOT (o → Holdout sin OOT) de AUC y KS, en palabras."""
    dev = _mapping(maximos.get("desarrollo"))
    destino = "oot" if "oot" in maximos else ("holdout" if "holdout" in maximos else None)
    if destino is None or not dev:
        return None
    fuera = _mapping(maximos.get(destino))
    frases: list[str] = []
    for clave, rotulo in (("auc", "AUC"), ("ks", "KS")):
        a = _float(dev.get(clave))
        b = _float(fuera.get(clave))
        if a is None or b is None:
            continue
        delta = b - a
        relativo = f" ({_pct(delta / a, decimals=1)})" if a else ""
        signo = "+" if delta > 0 else ""
        frases.append(f"{rotulo} {signo}{_num(delta, decimals=3)}{relativo}")
    if not frases:
        return None
    return f"Caída Desarrollo → {_partition_label(destino)}: {' · '.join(frases)}"


def _causa_no_evaluable(card: Mapping[str, Any], particion: str) -> str:
    secciones = _mapping(card.get("metric_sections"))
    causas = _mapping(
        _mapping(secciones.get("discrimination")).get("not_evaluable_reasons_by_partition")
    )
    causa = causas.get(particion)
    return f" ({causa})" if causa else ""


def _resumen_stability(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "stability", "card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        maximos = _mapping(card.get("max_psi_by_comparison"))
        metricas = _mapping(card.get("psi_metric_by_comparison"))
        bandas = _mapping(card.get("bands_by_comparison"))
        for comparacion in _sequence(card.get("comparisons")):
            cid = str(comparacion)
            banda = str(bandas.get(cid, ""))
            rotulo_banda = BAND_LABELS.get(banda, banda)
            valor = maximos.get(cid)
            magnitud = PSI_METRIC_LABELS.get(str(metricas.get(cid)), "")
            if banda == "not_evaluable" or valor is None:
                lines.append(f"{_COMPARISON_LABELS.get(cid, cid)}: PSI no evaluable")
                continue
            frase = (
                f"{_COMPARISON_LABELS.get(cid, cid)}: peor PSI {_num(valor)} "
                f"({magnitud}) → {rotulo_banda}"
            )
            lines.append(frase)
            if banda in {"review", "redevelop"}:
                alerts.append(
                    f"Estabilidad {_COMPARISON_LABELS.get(cid, cid)}: banda «{rotulo_banda}»"
                )
        peor = card.get("worst_csi_feature")
        if peor is not None:
            lines.append(
                f"CSI más alto: {str(peor).removesuffix('__points').removesuffix('__bin')} "
                f"({_num(card.get('worst_csi_value'))})"
            )
        secciones = _mapping(_mapping(card.get("metric_sections")).get("stability"))
        eje = str(secciones.get("temporal_axis", "none"))
        if eje != "none":
            n = _int(secciones.get("n_periods")) or 0
            lines.append(
                f"Estabilidad temporal del score por {TEMPORAL_AXIS_LABELS.get(eje, eje).lower()}: "
                f"{_miles(n)} {_plural(n, 'período', 'períodos')}"
            )
        metricas_tabla = _artifact(study, "stability", "stability_metrics")
        if isinstance(metricas_tabla, pd.DataFrame) and not metricas_tabla.empty:
            columnas = {
                "metric": "Métrica",
                "comparison": "Comparación",
                "feature": "Variable",
                "value": "Valor",
                "band": "Banda",
            }
            table = metricas_tabla[[c for c in columnas if c in metricas_tabla.columns]].rename(
                columns=columnas
            )
            table["Métrica"] = table["Métrica"].map(
                lambda v: STABILITY_METRIC_LABELS.get(str(v), v)
            )
            table["Comparación"] = table["Comparación"].map(
                lambda v: {**_COMPARISON_LABELS, **TEMPORAL_AXIS_LABELS}.get(str(v), v)
            )
            table["Banda"] = table["Banda"].map(lambda v: BAND_LABELS.get(str(v), v))
            table = table.reset_index(drop=True)
    if not lines:
        lines.append("La estabilidad no publicó su resumen.")
    return StageSummary(
        stage="stability",
        label=STAGE_LABELS["stability"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats={"Valor": "num"},
    )


def _resumen_validation(study: Study, context: SummaryContext) -> StageSummary:
    del context
    card = _card(study, "validation", "card")
    lines: list[str] = []
    alerts: list[str] = []
    table: pd.DataFrame | None = None
    if card is not None:
        estado = str(card.get("overall_status", ""))
        rotulo = VALIDATION_STATUS_LABELS.get(estado, estado)
        decisivas = _pruebas_decisivas(study)
        detalle = f" — lo decide {_enumerar(decisivas)}" if decisivas else ""
        lines.append(f"Estado técnico: {rotulo}{detalle}")
        n_tests = _int(card.get("n_tests")) or 0
        n_failed = _int(card.get("n_failed")) or 0
        familias = tuple(
            VALIDATION_FAMILY_LABELS.get(str(f), str(f)).lower()
            for f in _sequence(card.get("families_run"))
        )
        lines.append(
            f"{_miles(n_tests)} "
            f"{_plural(n_tests, 'prueba con veredicto', 'pruebas con veredicto')}, "
            f"{_miles(n_failed)} {_plural(n_failed, 'fallida', 'fallidas')}; familias: "
            f"{_enumerar(familias) if familias else 'ninguna'}"
        )
        if estado in {"fail", "warn"}:
            alerts.append(
                f"Estado técnico «{rotulo}»"
                + (f": revisar {_enumerar(decisivas)}" if decisivas else "")
            )
        avisos = _declared_warning_descriptions(
            tuple(str(a) for a in _sequence(card.get("falta_dato")))
        )
        alerts.extend(_capitalizar(a) for a in avisos)
        lines.append(
            "El estado técnico es una síntesis del motor; el veredicto lo firma un validador"
        )
        table = _tabla_de_pruebas(study)
    if not lines:
        lines.append("La validación formal no publicó su resumen.")
    return StageSummary(
        stage="validation",
        label=STAGE_LABELS["validation"],
        lines=tuple(lines),
        alerts=tuple(alerts),
        table=table,
        formats={"Valor": "num", "p-valor": "num"},
    )


def _pruebas_decisivas(study: Study) -> tuple[str, ...]:
    """Las pruebas que fallaron o quedaron en revisión, en palabras, con su muestra."""
    decisivas: list[str] = []
    calibracion = _artifact(study, "validation", "calibration")
    if isinstance(calibracion, pd.DataFrame) and not calibracion.empty:
        for _, fila in calibracion.iterrows():
            if str(fila.get("decision")) == "fail":
                prueba = CALIBRATION_TEST_LABELS.get(str(fila.get("test")), str(fila.get("test")))
                decisivas.append(
                    f"{prueba} en {_partition_label(str(fila.get('partition')))} "
                    f"(p-valor {_pvalor(fila.get('p_value'))})"
                )
    estabilidad = _artifact(study, "validation", "stability")
    if isinstance(estabilidad, pd.DataFrame) and not estabilidad.empty:
        for _, fila in estabilidad.iterrows():
            if str(fila.get("decision")) in {"fail", "warn"}:
                metrica = _rotulo(STABILITY_METRIC_LABELS, fila.get("metric"))
                comparacion = _rotulo(_COMPARISON_LABELS, fila.get("comparison"))
                decisivas.append(
                    f"{metrica} {comparacion} ({_rotulo(BAND_LABELS, fila.get('band'))})"
                )
    discriminacion = _artifact(study, "validation", "discrimination")
    if isinstance(discriminacion, pd.DataFrame) and not discriminacion.empty:
        for _, fila in discriminacion.iterrows():
            if str(fila.get("status")) == "not_evaluable":
                decisivas.append(
                    f"discriminación no evaluable en {_partition_label(str(fila.get('partition')))}"
                )
    return tuple(decisivas)


def _tabla_de_pruebas(study: Study) -> pd.DataFrame | None:
    """Una fila por prueba y muestra, con su veredicto en palabras."""
    filas: list[dict[str, Any]] = []
    discriminacion = _artifact(study, "validation", "discrimination")
    if isinstance(discriminacion, pd.DataFrame):
        for _, fila in discriminacion.iterrows():
            filas.append(
                {
                    "Familia": VALIDATION_FAMILY_LABELS["discrimination"],
                    "Prueba": "AUC",
                    "Muestra": _partition_label(str(fila.get("partition"))),
                    "Valor": _float(fila.get("auc")),
                    "p-valor": None,
                    "Veredicto": (
                        "Evaluada" if str(fila.get("status")) == "ok" else "No evaluable"
                    ),
                }
            )
    calibracion = _artifact(study, "validation", "calibration")
    if isinstance(calibracion, pd.DataFrame):
        for _, fila in calibracion.iterrows():
            decision = str(fila.get("decision"))
            veredicto = VALIDATION_DECISION_LABELS.get(decision, decision)
            causa = fila.get("not_evaluable_reason")
            if causa is not None and not (isinstance(causa, float) and pd.isna(causa)):
                veredicto += f" ({HL_NOT_EVALUABLE_REASON_LABELS.get(str(causa), str(causa))})"
            filas.append(
                {
                    "Familia": VALIDATION_FAMILY_LABELS["calibration"],
                    "Prueba": _rotulo(CALIBRATION_TEST_LABELS, fila.get("test")),
                    "Muestra": _partition_label(str(fila.get("partition"))),
                    "Valor": _float(fila.get("statistic")),
                    "p-valor": _float(fila.get("p_value")),
                    "Veredicto": veredicto,
                }
            )
    estabilidad = _artifact(study, "validation", "stability")
    if isinstance(estabilidad, pd.DataFrame):
        for _, fila in estabilidad.iterrows():
            decision = str(fila.get("decision"))
            veredicto = {
                **VALIDATION_DECISION_LABELS,
                "warn": VALIDATION_STATUS_LABELS["warn"],
            }.get(decision, decision)
            filas.append(
                {
                    "Familia": VALIDATION_FAMILY_LABELS["stability"],
                    "Prueba": (
                        f"{_rotulo(STABILITY_METRIC_LABELS, fila.get('metric'))} · "
                        f"{_sin_sufijo(fila.get('feature'))}"
                    ),
                    "Muestra": {**_COMPARISON_LABELS, **TEMPORAL_AXIS_LABELS}.get(
                        str(fila.get("comparison")), str(fila.get("comparison"))
                    ),
                    "Valor": _float(fila.get("value")),
                    "p-valor": None,
                    "Veredicto": f"{veredicto} ({_rotulo(BAND_LABELS, fila.get('band'))})",
                }
            )
    if not filas:
        return None
    return pd.DataFrame(filas)


def _resumen_report(study: Study, context: SummaryContext) -> StageSummary:
    lines: list[str] = []
    resultado = _artifact(study, "report", "result")
    for atributo, rotulo in (
        ("html_path", "Informe HTML"),
        ("docx_path", "Informe Word"),
        ("pdf_path", "Informe PDF"),
        ("md_path", "Fuente editable (Quarto)"),
    ):
        ruta = getattr(resultado, atributo, None) if resultado is not None else None
        if ruta:
            lines.append(f"{rotulo}: {_ruta_absoluta(ruta, context)}")
        elif atributo == "pdf_path" and resultado is not None:
            lines.append(f"{rotulo}: no se generó (falta el extra de PDF o su motor nativo)")
    if context.card_path is not None:
        lines.append(f"Ficha del modelo: {context.card_path}")
    if context.trail_path is not None:
        lines.append(f"Registro de auditoría: {context.trail_path}")
    if not lines:
        lines.append("El informe no publicó sus rutas.")
    return StageSummary(stage="report", label=STAGE_LABELS["report"], lines=tuple(lines))


_BUILDERS: Final[dict[str, Callable[[Study, SummaryContext], StageSummary]]] = {
    "data": _resumen_data,
    "eda": _resumen_eda,
    "binning": _resumen_binning,
    "selection": _resumen_selection,
    "model": _resumen_model,
    "scorecard": _resumen_scorecard,
    "calibration": _resumen_calibration,
    "performance": _resumen_performance,
    "stability": _resumen_stability,
    "validation": _resumen_validation,
    "report": _resumen_report,
}


# ────────────────────────────── resumen final ──────────────────────────────


def build_final_summary(
    study: Study | None,
    stages: Sequence[StageSummary],
    context: SummaryContext,
) -> FinalSummary:
    """Ejecución y validación técnica por separado, cinco cifras, alertas, decisiones y archivos."""
    execution = _estado_de_ejecucion(study, context)
    validation = _estado_de_validacion(study, context)
    figures = _cinco_cifras(study) if study is not None else ()
    review = tuple(f"{s.label}: {a}" for s in stages for a in s.alerts)
    files = _archivos(study, context)
    return FinalSummary(
        execution=execution,
        validation=validation,
        figures=figures,
        review=review,
        decisions=tuple(context.decision_lines),
        files=files,
        stages=tuple(stages),
    )


def _estado_de_ejecucion(study: Study | None, context: SummaryContext) -> str:
    if study is None:
        return "sin correr todavía"
    estado = study.run_context.status
    if estado == "done":
        if context.until is not None:
            hasta = STAGE_LABELS.get(context.until, context.until)
            return f"completada hasta «{hasta}» (corrida parcial)"
        return "completada"
    if estado == "failed":
        error = study.run_context.error
        etapa = STAGE_LABELS.get(
            str(getattr(error, "step", None)), str(getattr(error, "step", None))
        )
        mensaje = getattr(error, "message", "") if error is not None else ""
        donde = f" en «{etapa}»" if getattr(error, "step", None) else " antes del primer paso"
        return f"fallida{donde}: {mensaje}"
    return estado


def _estado_de_validacion(study: Study | None, context: SummaryContext) -> str:
    if study is None:
        return "sin correr todavía"
    card = _card(study, "validation", "card")
    if card is None:
        if context.until is not None:
            return "no corrió: la corrida se detuvo antes de la validación formal"
        if study.run_context.status == "failed":
            return "no corrió: la corrida falló antes"
        return "no corrió: la validación formal no está en el config"
    estado = str(card.get("overall_status", ""))
    rotulo = VALIDATION_STATUS_LABELS.get(estado, estado)
    decisivas = _pruebas_decisivas(study)
    return f"{rotulo}" + (f" — lo decide {_enumerar(decisivas)}" if decisivas else "")


def _cinco_cifras(study: Study) -> tuple[tuple[str, str], ...]:
    """Las cinco cifras del resumen final.

    AUC, Gini y KS en la muestra fuera de tiempo (o la última disponible), caída del AUC de
    Desarrollo a esa muestra y peor PSI con su banda.
    """
    cifras: list[tuple[str, str]] = []
    performance = _card(study, "performance", "card")
    if performance is not None:
        maximos = _mapping(performance.get("max_metrics_by_partition"))
        destino = "oot" if "oot" in maximos else ("holdout" if "holdout" in maximos else None)
        if destino is not None:
            valores = _mapping(maximos.get(destino))
            rotulo = _partition_label(destino)
            cifras.append((f"AUC en {rotulo}", _num(valores.get("auc"), decimals=3)))
            cifras.append((f"Gini en {rotulo}", _num(valores.get("gini"), decimals=3)))
            cifras.append((f"KS en {rotulo}", _num(valores.get("ks"), decimals=3)))
            dev = _float(_mapping(maximos.get("desarrollo")).get("auc"))
            fuera = _float(valores.get("auc"))
            if dev is not None and fuera is not None:
                delta = fuera - dev
                relativo = f" ({_pct(delta / dev, decimals=1)})" if dev else ""
                cifras.append(
                    (f"Caída del AUC Desarrollo → {rotulo}", f"{_num(delta, decimals=3)}{relativo}")
                )
    stability = _card(study, "stability", "card")
    if stability is not None:
        maximos_psi = _mapping(stability.get("max_psi_by_comparison"))
        bandas = _mapping(stability.get("bands_by_comparison"))
        peor: tuple[str, float] | None = None
        for cid, valor in maximos_psi.items():
            v = _float(valor)
            if v is not None and (peor is None or v > peor[1]):
                peor = (str(cid), v)
        if peor is not None:
            banda = BAND_LABELS.get(str(bandas.get(peor[0], "")), str(bandas.get(peor[0], "")))
            cifras.append(
                (
                    "Peor PSI entre score y PD",
                    f"{_num(peor[1])} ({_COMPARISON_LABELS.get(peor[0], peor[0])}) → {banda}",
                )
            )
    return tuple(cifras)


def _archivos(study: Study | None, context: SummaryContext) -> tuple[tuple[str, str], ...]:
    archivos: list[tuple[str, str]] = [("Carpeta del proyecto", str(context.project_dir))]
    if context.config_path is not None:
        archivos.append(("Config vigente", str(context.config_path)))
    archivos.append(("Evidencia de la corrida", str(context.run_dir)))
    if context.trail_path is not None:
        archivos.append(("Registro de auditoría", str(context.trail_path)))
    if context.card_path is not None:
        archivos.append(("Ficha del modelo", str(context.card_path)))
    resultado = _artifact(study, "report", "result") if study is not None else None
    for atributo, rotulo in (
        ("html_path", "Informe HTML"),
        ("docx_path", "Informe Word"),
        ("pdf_path", "Informe PDF"),
        ("md_path", "Fuente editable (Quarto)"),
    ):
        ruta = getattr(resultado, atributo, None) if resultado is not None else None
        if ruta:
            archivos.append((rotulo, _ruta_absoluta(ruta, context)))
    return tuple(archivos)


# ────────────────────────────── utilidades ──────────────────────────────


def _formatear(table: pd.DataFrame, formats: Mapping[str, _Kind]) -> pd.DataFrame:
    """La tabla con cada celda ya escrita como la lee una persona (coma decimal, miles)."""
    salida = table.copy()
    for columna in salida.columns:
        tipo = formats.get(str(columna))
        if tipo is None:
            if pd.api.types.is_float_dtype(salida[columna].dtype):
                tipo = "num"
            elif pd.api.types.is_integer_dtype(salida[columna].dtype):
                tipo = "int"
            else:
                salida[columna] = salida[columna].map(_celda_texto)
                continue
        salida[columna] = salida[columna].map(lambda v, t=tipo: _celda(v, t))
    return salida


def _celda(valor: Any, tipo: _Kind) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor is pd.NA:
        return "—"
    if tipo == "int":
        return _miles(int(valor))
    if tipo == "pct":
        return _pct(valor)
    if tipo == "num2":
        return _num(valor, decimals=2)
    if tipo == "num3":
        return _num(valor, decimals=3)
    if tipo == "num":
        return _num(valor)
    if tipo == "bool":
        return "sí" if bool(valor) else "no"
    return _celda_texto(valor)


def _celda_texto(valor: Any) -> str:
    if valor is None or valor is pd.NA or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    if isinstance(valor, bool | np.bool_):
        return "sí" if bool(valor) else "no"
    return str(valor)


def _pvalor(valor: Any) -> str:
    numero = _float(valor)
    if numero is None:
        return "—"
    if numero < 0.001:
        return "< 0,001"
    return _num(numero, decimals=3)


def _ruta_absoluta(ruta: Any, context: SummaryContext) -> str:
    camino = Path(str(ruta))
    if camino.is_absolute():
        return str(camino)
    return str((Path.cwd() / camino).resolve())


def _rotulo(mapa: Mapping[str, str], valor: Any) -> str:
    """La palabra pública de un identificador, o el identificador si el mapa no lo trae."""
    return mapa.get(str(valor), str(valor))


def _sin_sufijo(valor: Any) -> str:
    return str(valor).removesuffix("__points").removesuffix("__bin")


def _orden_particion(particion: str) -> int:
    return {"desarrollo": 0, "holdout": 1, "oot": 2}.get(particion, 3)


def _partition_label(partition: str) -> str:
    return _PARTITION_LABELS.get(partition, partition)


def _capitalizar(texto: str) -> str:
    return texto[:1].upper() + texto[1:] if texto else texto


def _artifact(study: Study | None, domain: str, key: str) -> Any:
    if study is None or not study.artifacts.has(domain, key):
        return None
    return study.artifacts.get(domain, key)


def _card(study: Study, domain: str, key: str) -> Mapping[str, Any] | None:
    valor = _artifact(study, domain, key)
    if valor is None:
        return None
    if isinstance(valor, Mapping):
        return valor
    dump = getattr(valor, "model_dump", None)
    if callable(dump):
        volcado = dump(mode="python")
        return volcado if isinstance(volcado, Mapping) else None
    return None


def _mapping(valor: Any) -> Mapping[str, Any]:
    return valor if isinstance(valor, Mapping) else {}


def _sequence(valor: Any) -> tuple[Any, ...]:
    if isinstance(valor, str | bytes) or valor is None:
        return ()
    if isinstance(valor, Iterable):
        return tuple(valor)
    return ()


def _int(valor: Any) -> int | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        if isinstance(valor, float) and pd.isna(valor):
            return None
        return int(valor)
    except (TypeError, ValueError):
        return None


def _float(valor: Any) -> float | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(numero) else numero
