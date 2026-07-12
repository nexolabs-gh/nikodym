"""Gráficos deterministas para el reporte auditable (net-new, bloque B1).

Funciones puras ``estructura → gráfico`` con ``matplotlib`` **perezoso** (API OO, sin ``pyplot`` ni
estado global). Cada función emite **SVG** (default, para el HTML y el ``.qmd``) o **PNG** (``fmt``,
para el ``.docx``: Word no admite figuras SVG). El SVG resultante es byte-idéntico entre corridas y
entre valores de
``PYTHONHASHSEED`` gracias a: ``rcParams`` fijos (hashsalt/fonttype/font.family), ``metadata`` sin
fecha ni *creator*, orden canónico de particiones y un sanitizado explícito del markup. El módulo
**no** se importa desde :mod:`nikodym.report` (preserva el import liviano del paquete) y **no** trae
``matplotlib`` en import-time: el import pesado ocurre sólo al llamar una función. ``pandas`` sólo
se usa para *type hints* (``TYPE_CHECKING``): las columnas se acceden por el API del ``DataFrame``
sin importar ``pandas`` en runtime.

El cableado al *renderer*/plantilla/secciones vive en :mod:`nikodym.report.renderer`; aquí sólo se
producen gráficos.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, cast

from nikodym.report.exceptions import (
    ReportDependencyError,
    ReportInputError,
    ReportRenderError,
)

if TYPE_CHECKING:  # pragma: no cover - sólo para type-checkers, nunca en runtime.
    import pandas as pd

ChartFormat: TypeAlias = Literal["svg", "png"]

__all__ = [
    "ChartFormat",
    "render_coefficients_forest",
    "render_discrimination_bars",
    "render_gains_chart",
    "render_reliability_chart",
    "render_stability_chart",
]

# ─────────────────────────── constantes de determinismo ───────────────────────────

# Orden canónico de particiones (coincide con nikodym.ui.reliability, binning/model, calibration):
# las presentes se dibujan en este orden; cualquier otra va después, estable por aparición.
_CANONICAL_PARTITIONS: tuple[str, ...] = ("desarrollo", "holdout", "oot")

# Colores FIJOS por categoría (NO el color-cycle automático, que depende del orden de iteración).
_PARTITION_COLORS: dict[str, str] = {
    "desarrollo": "#1f4e79",
    "holdout": "#2e8b57",
    "oot": "#c1440e",
}
_EXTRA_PALETTE: tuple[str, ...] = ("#6a4c93", "#8d6e63", "#455a64", "#00695c", "#9e6b00")
_REFERENCE_COLOR = "#9aa0a6"  # diagonales y líneas de referencia (gris neutro).

_METRIC_COLORS: dict[str, str] = {"auc": "#1f4e79", "gini": "#2e8b57", "ks": "#c1440e"}

_STABILITY_BAR_COLOR = "#1f4e79"
_STABLE_LINE_COLOR = "#2e8b57"
_REVIEW_LINE_COLOR = "#c1440e"

# Umbrales por defecto de estabilidad (PSI/CSI) si el DataFrame no trae las columnas de umbral.
_DEFAULT_STABLE_THRESHOLD = 0.10
_DEFAULT_REVIEW_THRESHOLD = 0.25
# Cap explícito de barras del gráfico de estabilidad: se conservan las de mayor ``value``.
_MAX_STABILITY_BARS = 20

_MISSING_MATPLOTLIB = (
    "matplotlib no está disponible; instale nikodym[report] para generar los gráficos del reporte."
)


# ─────────────────────────── infraestructura matplotlib/SVG ───────────────────────────


def _new_figure(figsize: tuple[float, float], dpi: int) -> Any:
    """Crea una ``Figure`` con canvas Agg vía el API OO (sin ``pyplot``); import perezoso.

    Copia el patrón de :func:`nikodym.explain.step._render_summary_png` (Figure + FigureCanvasAgg,
    sin estado global). Si falta ``matplotlib`` levanta :class:`ReportDependencyError`.
    """
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:  # pragma: no cover - rama de dependencia ausente.
        raise ReportDependencyError(_MISSING_MATPLOTLIB) from exc
    figure = Figure(figsize=figsize, dpi=dpi)
    FigureCanvasAgg(figure)
    return figure


def _numeric_formatter(decimals: int) -> Any:
    """``FuncFormatter`` con ``decimals`` fijos y sin ``-0.0`` (independiente del locale)."""
    from matplotlib.ticker import FuncFormatter

    def _format(value: float, _pos: Any) -> str:
        cleaned = 0.0 if abs(value) < 1e-12 else value
        return f"{cleaned:.{decimals}f}"

    return FuncFormatter(_format)


def _render(figure: Any, title: str, fmt: ChartFormat) -> str | bytes:
    """Serializa ``figure`` al formato pedido: SVG (texto) o PNG (bytes), ambos deterministas.

    El SVG es la ruta primaria (HTML y ``.qmd``). El PNG existe porque **Word no admite SVG**: un
    ``.docx`` con figuras vectoriales no abre, así que el export a Word pide el mismo gráfico
    rasterizado. Es el mismo ``Figure`` y los mismos datos; sólo cambia el serializador.
    """
    if fmt == "png":
        return _deterministic_png(figure)
    return _deterministic_svg(figure, title)


def _deterministic_svg(figure: Any, title: str) -> str:
    """Serializa ``figure`` a un SVG string determinista y sanitizado.

    Envuelve ``savefig`` en ``rc_context`` con los ``rcParams`` fijos verificados (hashsalt para
    matar el UUID de gid/clipPath, ``fonttype='none'`` para texto como ``<text>`` sin freetype, y
    una fuente *bundled*). ``metadata={"Date": None, "Creator": None}`` elimina ``<dc:date>`` y la
    firma de matplotlib. Luego delega en :func:`_sanitize_svg`.
    """
    import io

    import matplotlib

    buffer = io.BytesIO()
    rc_params = {
        "svg.hashsalt": "nikodym",
        "svg.fonttype": "none",
        "font.family": "DejaVu Sans",
    }
    with matplotlib.rc_context(cast("Any", rc_params)):
        figure.savefig(buffer, format="svg", metadata={"Date": None, "Creator": None})
    return _sanitize_svg(buffer.getvalue().decode("utf-8"), title)


def _deterministic_png(figure: Any) -> bytes:
    """Serializa ``figure`` a bytes PNG deterministas (para el ``.docx``, que no admite SVG).

    ``metadata={"Software": None}`` borra el único campo variable que matplotlib escribe en el
    chunk ``tEXt`` del PNG (su propia versión); sin él, dos corridas con matplotlib distinto
    producirían bytes distintos con los mismos datos. El rasterizado sí depende de freetype, así
    que el PNG es determinista *en una máquina*, no byte-idéntico cross-OS —igual que el SVG, cuyo
    digest se excluye del golden del manifest por la misma razón—.
    """
    import io

    import matplotlib

    buffer = io.BytesIO()
    with matplotlib.rc_context(cast("Any", {"font.family": "DejaVu Sans"})):
        figure.savefig(buffer, format="png", metadata={"Software": None})
    return buffer.getvalue()


def _sanitize_svg(raw: str, title: str) -> str:
    """Recorta la cabecera, inyecta atributos accesibles y un ``<title>``; normaliza saltos.

    Deja desde ``<svg`` hasta ``</svg>`` inclusive (descarta ``<?xml ...?>``, ``<!DOCTYPE ...>`` y
    el comentario de matplotlib, que quedan antes del tag raíz), añade ``role="img"`` y
    ``style="max-width:100%;height:auto"`` al tag raíz e inserta como primer hijo un ``<title>``
    accesible con ``title`` escapado.
    """
    text = _normalize_newlines(raw)
    start = text.find("<svg")
    end = text.rfind("</svg>")
    if start == -1 or end == -1:  # pragma: no cover - matplotlib siempre emite <svg>…</svg>.
        raise ReportRenderError("La serialización SVG de matplotlib no produjo un documento <svg>.")
    body = text[start : end + len("</svg>")]

    close = body.find(">")
    if close == -1:  # pragma: no cover - defensivo; el tag raíz siempre cierra.
        raise ReportRenderError("El tag raíz <svg> del gráfico está mal formado.")
    opening_tag = body[:close]
    remainder = body[close + 1 :]
    inject = ' role="img" style="max-width:100%;height:auto"'
    title_element = f"<title>{html.escape(title)}</title>"
    body = f"{opening_tag}{inject}>{title_element}{remainder}"
    return _normalize_newlines(body)


def _normalize_newlines(text: str) -> str:
    """Normaliza saltos a LF y garantiza salto final (estilo ``renderer._normalize_newlines``)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        return f"{normalized}\n"
    return normalized


# ─────────────────────────── utilidades de datos (sin importar pandas) ───────────────────────────


def _require_columns(frame: Any, required: frozenset[str], *, what: str) -> None:
    """Valida que ``frame`` sea un DataFrame con todas las columnas ``required``."""
    try:
        columns = set(frame.columns)
    except (AttributeError, TypeError) as exc:
        raise ReportInputError(
            f"{what}: se esperaba un DataFrame con columnas {sorted(required)}."
        ) from exc
    missing = sorted(required - columns)
    if missing:
        raise ReportInputError(f"{what}: faltan columnas requeridas {missing}.")


def _frame_records(frame: Any, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """Convierte las ``columns`` del DataFrame a lista de dicts (orden de filas preservado)."""
    series = {name: list(frame[name]) for name in columns}
    n_rows = len(frame)
    return [{name: series[name][index] for name in columns} for index in range(n_rows)]


def _order_partitions(names: Any) -> list[str]:
    """Canónicas primero (en orden fijo), el resto estable por primera aparición; sin duplicados."""
    observed: list[str] = []
    seen: set[str] = set()
    for value in names:
        label = str(value)
        if label not in seen:
            seen.add(label)
            observed.append(label)
    canonical = [name for name in _CANONICAL_PARTITIONS if name in seen]
    extra = [name for name in observed if name not in _CANONICAL_PARTITIONS]
    return canonical + extra


def _partition_color(name: str, extra_index: int) -> str:
    """Color fijo de la partición ``name``; las no canónicas usan la paleta extra por índice."""
    if name in _PARTITION_COLORS:
        return _PARTITION_COLORS[name]
    return _EXTRA_PALETTE[extra_index % len(_EXTRA_PALETTE)]


def _is_missing(value: Any) -> bool:
    """Detecta valores ausentes: ``None`` o ``NaN``.

    Un ``None`` del record cae como ``NaN`` en la columna ``float64`` del ``DataFrame``; como
    ``NaN is None`` es ``False``, un guard ``is None`` sería letra muerta en el path real. El
    ``isinstance(float)`` cubre ``numpy.float64`` (subclase de ``float``) y ``value != value``
    es ``True`` sólo para ``NaN``.
    """
    if value is None:
        return True
    return isinstance(value, float) and value != value


def _as_float(value: Any) -> float:
    """Castea a ``float`` normalizando ``-0.0`` a ``0.0`` (evita ``-0.0`` en el texto del SVG)."""
    result = float(value)
    return 0.0 if result == 0.0 else result


def _optional_float(value: Any) -> float | None:
    """``None`` si ``value`` es ``None``/``NaN``; en otro caso :func:`_as_float`."""
    return None if _is_missing(value) else _as_float(value)


# ─────────────────────────── gráficos ───────────────────────────


def render_gains_chart(
    deciles: pd.DataFrame, *, title: str, fmt: ChartFormat = "svg"
) -> str | bytes:
    """Curva de ganancia acumulada (fracción de población vs. malos capturados) por partición.

    ``deciles`` es ``performance_table``: se usan ``partition``, ``decile``, ``cum_total`` y
    ``cum_bad_capture_rate``. El eje X es la fracción acumulada de población (``cum_total``
    normalizado por el total de la partición) y el eje Y ``cum_bad_capture_rate``. Cada partición
    (orden canónico) es una línea que arranca en el origen; se añade la diagonal del aleatorio.
    """
    columns = ("partition", "decile", "cum_total", "cum_bad_capture_rate")
    _require_columns(deciles, frozenset(columns), what="render_gains_chart")
    records = _frame_records(deciles, columns)
    if not records:
        raise ReportInputError("render_gains_chart: la tabla de deciles está vacía.")

    by_partition: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_partition.setdefault(str(record["partition"]), []).append(record)

    figure = _new_figure((6.0, 4.5), dpi=100)
    axes = figure.subplots()
    axes.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", color=_REFERENCE_COLOR, label="Aleatorio")

    ordered = _order_partitions(record["partition"] for record in records)
    extra_index = 0
    for name in ordered:
        rows = sorted(by_partition[name], key=lambda row: int(row["decile"]))
        total = _as_float(rows[-1]["cum_total"])
        if total <= 0.0:  # partición sin población acumulada: no aporta curva.
            continue
        xs = [0.0] + [_as_float(row["cum_total"]) / total for row in rows]
        ys = [0.0] + [_as_float(row["cum_bad_capture_rate"]) for row in rows]
        color = _partition_color(name, extra_index)
        extra_index += 0 if name in _PARTITION_COLORS else 1
        axes.plot(xs, ys, marker="o", markersize=3.0, color=color, label=name)

    axes.set_xlim(0.0, 1.0)
    axes.set_ylim(0.0, 1.0)
    axes.set_xlabel("Fracción acumulada de población")
    axes.set_ylabel("Fracción de malos capturada")
    axes.xaxis.set_major_formatter(_numeric_formatter(2))
    axes.yaxis.set_major_formatter(_numeric_formatter(2))
    axes.grid(True, linewidth=0.4, alpha=0.4)
    axes.legend(loc="lower right", frameon=False)
    axes.set_title(title)
    figure.tight_layout()
    return _render(figure, title, fmt)


def render_reliability_chart(
    by_partition: list[dict[str, Any]], *, title: str, fmt: ChartFormat = "svg"
) -> str | bytes:
    """Curva de calibración (PD predicha vs. tasa observada) con banda de confianza por partición.

    ``by_partition`` es la salida de :func:`nikodym.ui.reliability.reliability_curve`: una lista de
    dicts ``{"partition", "n", "brier", "ece", "bins": [{"mean_predicted_pd",
    "observed_default_rate", "ci_low", "ci_high", ...}]}``. Se dibuja una curva por partición (orden
    canónico) con banda ``ci_low``..``ci_high`` y la diagonal de calibración perfecta; la leyenda
    muestra Brier/ECE.
    """
    if not isinstance(by_partition, list) or not by_partition:
        raise ReportInputError(
            "render_reliability_chart: se esperaba una lista no vacía de particiones."
        )

    indexed: dict[str, dict[str, Any]] = {}
    for item in by_partition:
        if not isinstance(item, dict) or "partition" not in item or "bins" not in item:
            raise ReportInputError(
                "render_reliability_chart: cada partición requiere las claves 'partition' y 'bins'."
            )
        indexed[str(item["partition"])] = item

    figure = _new_figure((6.0, 4.5), dpi=100)
    axes = figure.subplots()
    axes.plot(
        [0.0, 1.0], [0.0, 1.0], linestyle="--", color=_REFERENCE_COLOR, label="Calibración perfecta"
    )

    ordered = _order_partitions(str(item["partition"]) for item in by_partition)
    extra_index = 0
    plotted = False
    for name in ordered:
        item = indexed[name]
        bins = sorted(item["bins"], key=lambda entry: _as_float(entry["mean_predicted_pd"]))
        if not bins:
            continue
        xs = [_as_float(entry["mean_predicted_pd"]) for entry in bins]
        observed = [_as_float(entry["observed_default_rate"]) for entry in bins]
        ci_low = [_as_float(entry["ci_low"]) for entry in bins]
        ci_high = [_as_float(entry["ci_high"]) for entry in bins]
        color = _partition_color(name, extra_index)
        extra_index += 0 if name in _PARTITION_COLORS else 1
        label = _reliability_label(name, item)
        axes.fill_between(xs, ci_low, ci_high, color=color, alpha=0.15, linewidth=0.0)
        axes.plot(xs, observed, marker="o", markersize=3.0, color=color, label=label)
        plotted = True

    if not plotted:
        raise ReportInputError(
            "render_reliability_chart: ninguna partición tenía bins para graficar."
        )

    axes.set_xlim(0.0, 1.0)
    axes.set_ylim(0.0, 1.0)
    axes.set_xlabel("PD predicha (media por bin)")
    axes.set_ylabel("Tasa de default observada")
    axes.xaxis.set_major_formatter(_numeric_formatter(2))
    axes.yaxis.set_major_formatter(_numeric_formatter(2))
    axes.grid(True, linewidth=0.4, alpha=0.4)
    axes.legend(loc="upper left", frameon=False, fontsize=8.0)
    axes.set_title(title)
    figure.tight_layout()
    return _render(figure, title, fmt)


def _reliability_label(name: str, item: dict[str, Any]) -> str:
    """Etiqueta de leyenda con Brier/ECE si están presentes (formato fijo, sin locale)."""
    parts = [name]
    brier = item.get("brier")
    ece = item.get("ece")
    if brier is not None:
        parts.append(f"Brier={_as_float(brier):.3f}")
    if ece is not None:
        parts.append(f"ECE={_as_float(ece):.3f}")
    if len(parts) == 1:
        return name
    return f"{parts[0]} ({', '.join(parts[1:])})"


def render_coefficients_forest(
    coefficients: pd.DataFrame | list[dict[str, Any]],
    *,
    title: str,
    fmt: ChartFormat = "svg",
) -> str | bytes:
    """Forest plot de coeficientes: ``beta`` como punto y barra de error ``[conf_low, conf_high]``.

    ``coefficients`` es un DataFrame o lista de dicts de ``CoefficientRecord``. Se excluyen la fila
    ``feature == "intercept"`` y cualquier fila con ``beta`` ausente/no-finito (defense-in-depth: el
    contrato garantiza ``beta`` finito, pero un ``NaN`` volvería el orden dependiente de la
    permutación de entrada). El orden es por ``|beta|`` descendente (desempate por nombre de
    ``feature`` ascendente) → el coeficiente más influyente queda arriba. Se dibuja una línea
    vertical en 0; los intervalos ausentes (``conf_low``/``conf_high`` nulos) omiten la barra.
    """
    used_columns = ("feature", "beta", "conf_low", "conf_high")
    if hasattr(coefficients, "columns"):
        _require_columns(
            coefficients, frozenset({"feature", "beta"}), what="render_coefficients_forest"
        )
        available = set(coefficients.columns)
        records = _frame_records(
            coefficients, tuple(name for name in used_columns if name in available)
        )
    else:
        if not isinstance(coefficients, list) or not coefficients:
            raise ReportInputError(
                "render_coefficients_forest: se requiere un DataFrame o lista no vacía."
            )
        records = []
        for row in coefficients:
            if not isinstance(row, dict) or "feature" not in row or "beta" not in row:
                raise ReportInputError(
                    "render_coefficients_forest: cada coeficiente requiere 'feature' y 'beta'."
                )
            records.append(row)

    plotted = [
        record
        for record in records
        if str(record["feature"]) != "intercept" and not _is_missing(record["beta"])
    ]
    if not plotted:
        raise ReportInputError(
            "render_coefficients_forest: no hay coeficientes (fuera del intercepto)."
        )
    plotted.sort(key=lambda record: (-abs(_as_float(record["beta"])), str(record["feature"])))

    n_coef = len(plotted)
    height = min(9.0, max(3.0, 0.5 * n_coef + 1.5))
    figure = _new_figure((6.5, height), dpi=100)
    axes = figure.subplots()
    axes.axvline(0.0, linestyle="--", color=_REFERENCE_COLOR, linewidth=1.0)

    color = _PARTITION_COLORS["desarrollo"]
    y_positions = list(range(n_coef))
    labels = [str(record["feature"]) for record in plotted]
    for offset, record in enumerate(plotted):
        y_pos = n_coef - 1 - offset  # el más influyente arriba.
        beta = _as_float(record["beta"])
        low = _optional_float(record.get("conf_low"))
        high = _optional_float(record.get("conf_high"))
        if low is not None and high is not None and low <= high:
            axes.plot([low, high], [y_pos, y_pos], color=color, linewidth=1.2)
        axes.plot([beta], [y_pos], marker="o", markersize=4.0, color=color)

    axes.set_yticks(y_positions)
    axes.set_yticklabels(list(reversed(labels)))
    axes.set_ylim(-0.5, n_coef - 0.5)
    axes.set_xlabel("Coeficiente β (IC 95 %)")
    axes.xaxis.set_major_formatter(_numeric_formatter(2))
    axes.grid(True, axis="x", linewidth=0.4, alpha=0.4)
    axes.set_title(title)
    figure.tight_layout()
    return _render(figure, title, fmt)


def render_discrimination_bars(
    discriminant: pd.DataFrame, *, title: str, fmt: ChartFormat = "svg"
) -> str | bytes:
    """Barras agrupadas de AUC/Gini/KS por partición (orden canónico) para ver la degradación.

    ``discriminant`` es ``discriminant_metrics``: se usan ``partition``, ``auc``, ``gini`` y ``ks``.
    Las particiones ``not_evaluable`` traen métricas nulas → se grafican como 0. Cada métrica lleva
    un color fijo; el eje Y va de 0 a 1.
    """
    metrics = ("auc", "gini", "ks")
    columns = ("partition", *metrics)
    _require_columns(discriminant, frozenset(columns), what="render_discrimination_bars")
    records = _frame_records(discriminant, columns)
    if not records:
        raise ReportInputError("render_discrimination_bars: la tabla de discriminación está vacía.")

    by_partition = {str(record["partition"]): record for record in records}
    ordered = _order_partitions(str(record["partition"]) for record in records)

    figure = _new_figure((6.5, 4.0), dpi=100)
    axes = figure.subplots()
    n_metrics = len(metrics)
    bar_width = 0.8 / n_metrics
    positions = list(range(len(ordered)))
    for metric_index, metric in enumerate(metrics):
        offset = (metric_index - (n_metrics - 1) / 2.0) * bar_width
        heights = []
        for name in ordered:
            metric_value = by_partition[name][metric]
            heights.append(0.0 if _is_missing(metric_value) else _as_float(metric_value))
        xs = [pos + offset for pos in positions]
        axes.bar(xs, heights, width=bar_width, color=_METRIC_COLORS[metric], label=metric.upper())

    axes.set_xticks(positions)
    axes.set_xticklabels(ordered)
    axes.set_ylim(0.0, 1.0)
    axes.set_ylabel("Valor de la métrica")
    axes.yaxis.set_major_formatter(_numeric_formatter(2))
    axes.grid(True, axis="y", linewidth=0.4, alpha=0.4)
    axes.legend(loc="upper right", frameon=False)
    axes.set_title(title)
    figure.tight_layout()
    return _render(figure, title, fmt)


def render_stability_chart(
    stability_metrics: pd.DataFrame, *, title: str, fmt: ChartFormat = "svg"
) -> str | bytes:
    """Barras horizontales de PSI/CSI por (métrica·comparación·feature) con umbrales de banda.

    ``stability_metrics``: se usan ``metric``, ``comparison``, ``feature`` y ``value``; si están,
    ``stable_threshold``/``review_threshold`` fijan las dos líneas de umbral (por defecto 0.10 y
    0.25). Las filas con ``value`` nulo (``not_evaluable``) se omiten. Se ordena por ``value``
    descendente (desempate por etiqueta) y se truncan a las ``_MAX_STABILITY_BARS`` mayores.
    """
    base_columns = ("metric", "comparison", "feature", "value")
    _require_columns(stability_metrics, frozenset(base_columns), what="render_stability_chart")
    available = set(stability_metrics.columns)
    threshold_columns = tuple(
        name for name in ("stable_threshold", "review_threshold") if name in available
    )
    records = _frame_records(stability_metrics, base_columns + threshold_columns)

    rows: list[dict[str, Any]] = []
    for record in records:
        value = record["value"]
        if _is_missing(value):
            continue
        feature = str(record["feature"])
        label = f"{record['metric']}·{record['comparison']}"
        if feature:
            label = f"{label}·{feature}"
        rows.append({"label": label, "value": _as_float(value), "record": record})
    if not rows:
        raise ReportInputError("render_stability_chart: no hay métricas de estabilidad evaluables.")

    rows.sort(key=lambda item: (-item["value"], item["label"]))
    truncated = rows[:_MAX_STABILITY_BARS]

    stable_threshold = _DEFAULT_STABLE_THRESHOLD
    review_threshold = _DEFAULT_REVIEW_THRESHOLD
    first = truncated[0]["record"]
    if "stable_threshold" in first and first["stable_threshold"] is not None:
        stable_threshold = _as_float(first["stable_threshold"])
    if "review_threshold" in first and first["review_threshold"] is not None:
        review_threshold = _as_float(first["review_threshold"])

    n_bars = len(truncated)
    height = min(10.0, max(3.0, 0.4 * n_bars + 1.5))
    figure = _new_figure((7.0, height), dpi=100)
    axes = figure.subplots()

    # La barra de mayor value queda arriba: y descendente respecto al orden ya ordenado.
    y_positions = [n_bars - 1 - index for index in range(n_bars)]
    values = [item["value"] for item in truncated]
    labels = [item["label"] for item in truncated]
    axes.barh(y_positions, values, color=_STABILITY_BAR_COLOR, height=0.7)
    axes.axvline(
        stable_threshold,
        linestyle="--",
        color=_STABLE_LINE_COLOR,
        linewidth=1.0,
        label=f"Estable ≤ {stable_threshold:.2f}",
    )
    axes.axvline(
        review_threshold,
        linestyle="--",
        color=_REVIEW_LINE_COLOR,
        linewidth=1.0,
        label=f"Revisar ≤ {review_threshold:.2f}",
    )

    axes.set_yticks(list(range(n_bars)))
    axes.set_yticklabels(list(reversed(labels)))
    axes.set_ylim(-0.5, n_bars - 0.5)
    axes.set_xlabel("PSI / CSI")
    axes.xaxis.set_major_formatter(_numeric_formatter(2))
    axes.grid(True, axis="x", linewidth=0.4, alpha=0.4)
    axes.legend(loc="lower right", frameon=False, fontsize=8.0)
    axes.set_title(title)
    figure.tight_layout()
    return _render(figure, title, fmt)
