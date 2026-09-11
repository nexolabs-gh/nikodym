"""Gate de la capa 1 de SCORECARD-COMPLETO: una palabra, una fuente, dos superficies.

Hasta esta capa el mismo dato salía con **dos vocabularios**: la interfaz pintaba «Revisar» y la
prosa del informe escribía «Requiere revisión» para la banda ``review``; la guía publicaba los
slugs en inglés. Cada superficie tenía su diccionario y nadie los comparaba, así que la deriva era
invisible hasta abrir el informe al lado de la pantalla (D-SC-10, D-SC-11).

Aquí se fija lo contrario: **Python es la fuente** —el dominio que produce el dato publica su
rótulo— y el front lo **replica** con un espejo gateado en los dos sentidos. El slug no se toca: es
el dato del JSON y sigue viajando entero.

Tres oráculos, y los tres importan:

1. **Completitud contra el enum**: el mapa cubre exactamente los literales del tipo. Añadir un
   motivo de selección sin su palabra, o dejar una palabra huérfana, pone rojo.
2. **Espejo Python ↔ TypeScript**: mismas claves y mismos valores. Cambiar «Revisar» de un solo
   lado pone rojo (control negativo preespecificado del §6 de la enmienda).
3. **Contra la realidad medida**: los rótulos de los umbrales de selección son los ``title`` de los
   campos del formulario, y las claves son las que la card publica de verdad en una corrida real.

Molde: ``MODEL_CARD_NO_PINTADO`` / ``LINEAGE_NO_PINTADO`` (S4), gates de dos fuentes con un solo
oráculo.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final, get_args

import pytest
from pydantic import BaseModel

from nikodym.binning.results import IV_BAND_LABELS, IvBand
from nikodym.eda.card import EdaCardSection
from nikodym.eda.default_rate import _RESULT_COLUMNS as _COLUMNAS_TASA
from nikodym.eda.default_rate import AXIS_LABELS, EdaAxis
from nikodym.eda.quality import _RESULT_COLUMNS as _COLUMNAS_CALIDAD
from nikodym.eda.quality import QUALITY_FLAG_LABELS, QualityFlag
from nikodym.eda.stability import (
    NOT_EVALUABLE_REASON_LABELS,
    STABILITY_INDICATOR_LABELS,
    NotEvaluableReason,
    StabilityMetric,
)
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)
from nikodym.selection.results import REASON_LABELS, SelectionDecisionReason
from nikodym.selection.step import _thresholds_from_config
from nikodym.stability.results import (
    BAND_LABELS,
    PSI_METRIC_LABELS,
    STABILITY_METRIC_LABELS,
    PsiMetricName,
    StabilityBand,
    StabilityMetricName,
)
from nikodym.validation.config import BacktestParameter, ValidationFamily
from nikodym.validation.results import (
    BACKTEST_PARAMETER_LABELS,
    BACKTEST_TEST_LABELS,
    CALIBRATION_TEST_LABELS,
    DISCRIMINATION_SOURCE_LABELS,
    DISCRIMINATION_STATUS_LABELS,
    PD_TEST_LABELS,
    TRAFFIC_LIGHT_LABELS,
    VALIDATION_DECISION_LABELS,
    VALIDATION_FAMILY_LABELS,
    VALIDATION_STATUS_LABELS,
    BacktestTest,
    CalibrationDecision,
    CalibrationTest,
    DiscriminationSource,
    DiscriminationStatus,
    OverallStatus,
    PdTest,
    TrafficLight,
)

_RAIZ: Final = Path(__file__).resolve().parents[2]
_CHART_THEME: Final = _RAIZ / "web" / "src" / "components" / "charts" / "chart-theme.ts"
_RESULTS_FORMAT: Final = _RAIZ / "web" / "src" / "lib" / "results-format.ts"
_RESULTS_TYPES: Final = _RAIZ / "web" / "src" / "lib" / "results-types.ts"
_PROSE: Final = _RAIZ / "src" / "nikodym" / "report" / "prose.py"
_RESULTS_F1: Final = _RAIZ / "web" / "src" / "fixtures" / "demo" / "results-f1.json"


def _mapa_ts(archivo: Path, nombre: str) -> dict[str, str]:
    """Lee ``export const <nombre>: Record<string, string> = { ... }`` de un módulo TypeScript.

    Se parsea el fuente y no se ejecuta el bundle a propósito: este gate corre en la suite de
    Python, que es la que tiene acceso a los dos lados. El front prueba sus helpers por su cuenta.
    """
    texto = archivo.read_text(encoding="utf-8")
    cuerpo = re.search(
        rf"^export const {re.escape(nombre)}: Record<string, string> = \{{\n(.*?)^\}}",
        texto,
        re.S | re.M,
    )
    assert cuerpo is not None, f"{archivo.name} no declara `export const {nombre}`"
    entradas = re.findall(r'^  "?([A-Za-z0-9_.]+)"?: "([^"]*)",', cuerpo.group(1), re.M)
    assert entradas, f"{nombre} quedó sin entradas legibles"
    return dict(entradas)


def _union_ts(nombre: str) -> set[str]:
    """Los literales de ``export type <nombre> = "a" | "b" | ...`` en ``results-types.ts``."""
    texto = _RESULTS_TYPES.read_text(encoding="utf-8")
    inicio = texto.find(f"export type {nombre} =")
    assert inicio != -1, f"results-types.ts no declara `export type {nombre}`"
    fin = texto.find("\n\n", inicio)
    cuerpo = texto[inicio:] if fin == -1 else texto[inicio:fin]
    literales = set(re.findall(r'"([^"]+)"', cuerpo))
    assert literales, f"{nombre} quedó sin literales legibles"
    return literales


def _titulo_del_formulario(modelo: type[BaseModel], ruta: str) -> str | None:
    """El ``title`` del campo que la ruta punteada nombra dentro de un modelo Pydantic."""
    actual: Any = modelo
    campo = None
    for tramo in ruta.split("."):
        campos = getattr(actual, "model_fields", None)
        assert campos is not None, ruta
        campo = campos[tramo]
        actual = campo.annotation
    assert campo is not None
    return campo.title


# ───────────────────────── 1. completitud contra el enum del motor ─────────────────────────


@pytest.mark.parametrize(
    ("mapa", "enum", "nombre"),
    [
        (BAND_LABELS, StabilityBand, "BAND_LABELS"),
        (PSI_METRIC_LABELS, PsiMetricName, "PSI_METRIC_LABELS"),
        (STABILITY_METRIC_LABELS, StabilityMetricName, "STABILITY_METRIC_LABELS"),
        (REASON_LABELS, SelectionDecisionReason, "REASON_LABELS"),
        (IV_BAND_LABELS, IvBand, "IV_BAND_LABELS"),
        (VALIDATION_STATUS_LABELS, OverallStatus, "VALIDATION_STATUS_LABELS"),
        (VALIDATION_FAMILY_LABELS, ValidationFamily, "VALIDATION_FAMILY_LABELS"),
        (VALIDATION_DECISION_LABELS, CalibrationDecision, "VALIDATION_DECISION_LABELS"),
        (CALIBRATION_TEST_LABELS, CalibrationTest, "CALIBRATION_TEST_LABELS"),
        (TRAFFIC_LIGHT_LABELS, TrafficLight, "TRAFFIC_LIGHT_LABELS"),
        (DISCRIMINATION_STATUS_LABELS, DiscriminationStatus, "DISCRIMINATION_STATUS_LABELS"),
        (DISCRIMINATION_SOURCE_LABELS, DiscriminationSource, "DISCRIMINATION_SOURCE_LABELS"),
        (BACKTEST_PARAMETER_LABELS, BacktestParameter, "BACKTEST_PARAMETER_LABELS"),
        (BACKTEST_TEST_LABELS, BacktestTest, "BACKTEST_TEST_LABELS"),
        (PD_TEST_LABELS, PdTest, "PD_TEST_LABELS"),
        # D-SC-5: los cuatro vocabularios del análisis exploratorio.
        (AXIS_LABELS, EdaAxis, "AXIS_LABELS"),
        (STABILITY_INDICATOR_LABELS, StabilityMetric, "STABILITY_INDICATOR_LABELS"),
        (NOT_EVALUABLE_REASON_LABELS, NotEvaluableReason, "NOT_EVALUABLE_REASON_LABELS"),
        (QUALITY_FLAG_LABELS, QualityFlag, "QUALITY_FLAG_LABELS"),
    ],
)
def test_cada_mapa_cubre_exactamente_su_enum(mapa: dict[str, str], enum: Any, nombre: str) -> None:
    """Un valor nuevo del motor sin palabra —o una palabra huérfana— es un hueco mudo."""
    assert set(mapa) == set(get_args(enum)), nombre


@pytest.mark.parametrize(
    ("mapa", "nombre"),
    [
        (BAND_LABELS, "BAND_LABELS"),
        (PSI_METRIC_LABELS, "PSI_METRIC_LABELS"),
        (STABILITY_METRIC_LABELS, "STABILITY_METRIC_LABELS"),
        (REASON_LABELS, "REASON_LABELS"),
        (IV_BAND_LABELS, "IV_BAND_LABELS"),
        (VALIDATION_STATUS_LABELS, "VALIDATION_STATUS_LABELS"),
        (VALIDATION_FAMILY_LABELS, "VALIDATION_FAMILY_LABELS"),
        (VALIDATION_DECISION_LABELS, "VALIDATION_DECISION_LABELS"),
        (TRAFFIC_LIGHT_LABELS, "TRAFFIC_LIGHT_LABELS"),
        (DISCRIMINATION_STATUS_LABELS, "DISCRIMINATION_STATUS_LABELS"),
        (DISCRIMINATION_SOURCE_LABELS, "DISCRIMINATION_SOURCE_LABELS"),
        (BACKTEST_PARAMETER_LABELS, "BACKTEST_PARAMETER_LABELS"),
        (AXIS_LABELS, "AXIS_LABELS"),
        (STABILITY_INDICATOR_LABELS, "STABILITY_INDICATOR_LABELS"),
        (NOT_EVALUABLE_REASON_LABELS, "NOT_EVALUABLE_REASON_LABELS"),
        (QUALITY_FLAG_LABELS, "QUALITY_FLAG_LABELS"),
    ],
)
def test_ninguna_palabra_publica_es_un_slug(mapa: dict[str, str], nombre: str) -> None:
    """El copy está en español: si una palabra es su propio slug, no se tradujo nada."""
    sin_traducir = [clave for clave, palabra in mapa.items() if palabra == clave]
    assert sin_traducir == [], f"{nombre}: {sin_traducir}"


def test_las_cuatro_palabras_de_las_bandas_son_las_aprobadas() -> None:
    """D-SC-11, respuesta 2 de Cami del 2026-09-09. Ancla literal: no se re-litiga al editar."""
    assert BAND_LABELS == {
        "stable": "Estable",
        "review": "Revisar",
        "redevelop": "Redesarrollar",
        "not_evaluable": "No evaluable",
    }


def test_las_tres_palabras_del_estado_tecnico_son_las_aprobadas() -> None:
    """D-SC-9, respuesta 3 de Cami del 2026-09-09: «Pasa · Revisar · Falla», bajo «Estado técnico».

    Sustituyen a «Pass técnico / Requiere revisión / Falla técnica», que era el vocabulario que la
    prosa del informe usaba en solitario: la pantalla no decía nada porque no había panel.
    """
    assert VALIDATION_STATUS_LABELS == {
        "pass": "Pasa",
        "warn": "Revisar",
        "fail": "Falla",
    }


# ───────────────────────── 2. espejo Python ↔ TypeScript ─────────────────────────


def test_el_front_espeja_las_bandas_de_estabilidad() -> None:
    """El control negativo del §6: cambiar «Revisar» sólo en TS tiene que poner esto rojo."""
    assert _mapa_ts(_CHART_THEME, "BAND_LABELS") == BAND_LABELS


def test_el_front_espeja_los_motivos_de_seleccion() -> None:
    """La tabla de decisiones del panel dice lo mismo que la prosa del informe."""
    assert _mapa_ts(_RESULTS_FORMAT, "SELECTION_REASON_LABELS") == REASON_LABELS


def test_el_front_espeja_las_bandas_de_iv() -> None:
    assert _mapa_ts(_RESULTS_FORMAT, "IV_BAND_LABELS") == IV_BAND_LABELS


def test_el_front_espeja_la_identidad_del_resumen_psi() -> None:
    assert _mapa_ts(_RESULTS_FORMAT, "PSI_METRIC_LABELS") == PSI_METRIC_LABELS


def test_el_front_espeja_lo_que_mide_cada_fila_de_estabilidad() -> None:
    """Las CUATRO métricas del frame, no las dos del resumen A1.

    El panel de validación publica `stability_metrics` entera —CSI incluido—, y sin este mapa la
    columna mostraba el identificador crudo `csi`. Medido en la UI viva.
    """
    assert _mapa_ts(_RESULTS_FORMAT, "STABILITY_METRIC_LABELS") == STABILITY_METRIC_LABELS


@pytest.mark.parametrize(
    ("nombre", "fuente"),
    [
        ("VALIDATION_STATUS_LABELS", VALIDATION_STATUS_LABELS),
        ("VALIDATION_FAMILY_LABELS", VALIDATION_FAMILY_LABELS),
        ("VALIDATION_DECISION_LABELS", VALIDATION_DECISION_LABELS),
        ("CALIBRATION_TEST_LABELS", CALIBRATION_TEST_LABELS),
        ("TRAFFIC_LIGHT_LABELS", TRAFFIC_LIGHT_LABELS),
        ("DISCRIMINATION_STATUS_LABELS", DISCRIMINATION_STATUS_LABELS),
        ("DISCRIMINATION_SOURCE_LABELS", DISCRIMINATION_SOURCE_LABELS),
        ("BACKTEST_PARAMETER_LABELS", BACKTEST_PARAMETER_LABELS),
        ("BACKTEST_TEST_LABELS", BACKTEST_TEST_LABELS),
        ("PD_TEST_LABELS", PD_TEST_LABELS),
    ],
)
def test_el_front_espeja_el_vocabulario_de_la_validacion(
    nombre: str, fuente: dict[str, str]
) -> None:
    """Los diez mapas que el panel «Validación formal» consume (D-SC-9).

    Diez y no uno: cada columna de las cuatro tablas traduce un enum distinto del motor, y una
    palabra cambiada de un solo lado deja la pantalla diciendo algo que el informe no dice.
    """
    assert _mapa_ts(_RESULTS_FORMAT, nombre) == fuente


@pytest.mark.parametrize(
    ("nombre", "fuente"),
    [
        ("EDA_AXIS_LABELS", AXIS_LABELS),
        ("EDA_STABILITY_INDICATOR_LABELS", STABILITY_INDICATOR_LABELS),
        ("EDA_NOT_EVALUABLE_REASON_LABELS", NOT_EVALUABLE_REASON_LABELS),
        ("EDA_QUALITY_FLAG_LABELS", QUALITY_FLAG_LABELS),
    ],
)
def test_el_front_espeja_el_vocabulario_del_analisis_exploratorio(
    nombre: str, fuente: dict[str, str]
) -> None:
    """Los cuatro mapas que el panel «Análisis exploratorio» consume (D-SC-5).

    El eje efectivo, el indicador, la causa de no evaluar y las marcas de calidad: cada uno es un
    enum distinto del motor, y una palabra cambiada de un solo lado deja la pantalla diciendo
    algo que el informe no dice —justo la deriva que la capa 1 vino a cerrar—.
    """
    assert _mapa_ts(_RESULTS_FORMAT, nombre) == fuente


def test_los_colores_del_estado_tecnico_cubren_las_tres_palabras() -> None:
    """El semáforo del panel no puede tener un estado sin color: se pintaría gris y mentiría.

    ⚠️ Se comprueban las CLAVES, no los valores, y por eso NO se usa `_mapa_ts`: los colores se
    reúsan de las bandas de estabilidad a propósito —dos escalas para lo mismo se leerían como dos
    significados— así que sus valores son expresiones (`BAND_COLORS.stable`) y no literales.
    """
    texto = _CHART_THEME.read_text(encoding="utf-8")
    patron = (
        r"^export const VALIDATION_STATUS_COLORS: Record<string, string> = \{"
        r"\n(.*?)^\}"
    )
    cuerpo = re.search(patron, texto, re.S | re.M)
    assert cuerpo is not None, "chart-theme.ts no declara `VALIDATION_STATUS_COLORS`"
    claves = set(re.findall(r'^  "?([A-Za-z0-9_]+)"?:', cuerpo.group(1), re.M))
    assert claves == set(VALIDATION_STATUS_LABELS), claves


@pytest.mark.parametrize(
    ("enum", "interfaz"),
    [
        (StabilityBand, "StabilityBand"),
        (PsiMetricName, "PsiSummaryMetric"),
        (SelectionDecisionReason, "SelectionDecisionReason"),
        (IvBand, "IvBand"),
        (OverallStatus, "ValidationOverallStatus"),
        (ValidationFamily, "ValidationFamily"),
        (CalibrationDecision, "ValidationDecision"),
        (TrafficLight, "TrafficLight"),
        (DiscriminationSource, "DiscriminationSource"),
        (DiscriminationStatus, "DiscriminationStatus"),
        (CalibrationTest, "CalibrationTest"),
        (BacktestParameter, "BacktestParameter"),
        (BacktestTest, "BacktestTest"),
        (EdaAxis, "EdaAxis"),
        (StabilityMetric, "EdaStabilityIndicator"),
        (NotEvaluableReason, "EdaNotEvaluableReason"),
        (QualityFlag, "EdaQualityFlag"),
    ],
)
def test_el_tipo_del_front_espeja_el_enum_del_motor(enum: Any, interfaz: str) -> None:
    """El slug es el dato: si el motor gana un valor y el tipo del front no, el front deja de
    reconocerlo y el fallback lo pinta crudo sin que nada lo acuse."""
    assert _union_ts(interfaz) == set(get_args(enum))


# ───────────────────────── 3. contra la realidad medida ─────────────────────────


def test_los_rotulos_de_umbrales_son_los_del_formulario() -> None:
    """Un tercer nombre para el mismo campo es la deriva que esta capa vino a cerrar."""
    mapa = _mapa_ts(_RESULTS_FORMAT, "SELECTION_THRESHOLD_LABELS")
    esperado = {ruta: _titulo_del_formulario(SelectionConfig, ruta) for ruta in mapa}
    assert mapa == esperado


def test_los_umbrales_rotulados_son_los_que_la_card_publica() -> None:
    """Medido sobre la corrida real que la demo sirve: ni un umbral mudo ni un rótulo fantasma."""
    thresholds = json.loads(_RESULTS_F1.read_text(encoding="utf-8"))["selection"]["thresholds"]
    assert set(_mapa_ts(_RESULTS_FORMAT, "SELECTION_THRESHOLD_LABELS")) == set(thresholds)


def test_un_control_inerte_queda_atado_al_umbral_que_lo_apaga() -> None:
    """El serializer publica la acción SIEMPRE y anula sólo su umbral, así que el panel decide si
    un control describe la corrida mirando el umbral del que depende. Esta tabla es la que el front
    espeja; si el motor dejara de anular ese umbral, la pantalla atribuiría un criterio que no
    corrió y nadie lo notaría.

    🔴 Hallazgo de la segunda pasada de la revisión adversarial de S8, verificado en el motor:
    ``_apply_stability_action`` sale por tabla vacía con la estabilidad apagada, el clustering por
    correlación sólo se consume dentro de ``if self.correlation_enabled`` y la acción ante IV alto
    sólo dentro de ``if estimator.max_iv is not None``.
    """
    depende_de = _mapa_ts(_RESULTS_FORMAT, "SELECTION_THRESHOLD_DEPENDS_ON")
    assert depende_de == {
        "max_iv_action": "max_iv",
        "correlation.clustering_method": "correlation.threshold",
        "stability.action": "stability.stable_threshold",
    }

    apagado = _thresholds_from_config(
        SelectionConfig(
            max_iv=None,
            correlation=CorrelationSelectionConfig(enabled=False),
            vif=VifSelectionConfig(enabled=False),
            stability=StabilitySelectionConfig(enabled=False),
        )
    )
    encendido = _thresholds_from_config(
        SelectionConfig(
            max_iv=0.5,
            correlation=CorrelationSelectionConfig(enabled=True),
            vif=VifSelectionConfig(enabled=True),
            stability=StabilitySelectionConfig(enabled=True),
        )
    )
    for control, umbral in depende_de.items():
        # Apagado: el umbral se anula y el control queda inerte —pero el serializer lo sigue
        # publicando, que es justo por lo que el front necesita la tabla—.
        assert apagado[umbral] is None, umbral
        assert apagado[control] is not None, control
        # Encendido: los dos viajan, y el panel los pinta.
        assert encendido[umbral] is not None, umbral
        assert encendido[control] is not None, control

    # `correlation.method` no depende de nada: la matriz se calcula aunque el filtro esté apagado.
    assert "correlation.method" not in depende_de
    assert apagado["correlation.method"] is not None


def test_la_prosa_del_informe_ya_no_tiene_su_propio_vocabulario_de_validacion() -> None:
    """Los dos mapas locales de `prose.py` desaparecen: si vuelven, vuelve la deriva.

    Y con ellos las palabras viejas: ninguna de las tres puede sobrevivir en el fuente del
    informe, porque la única forma de que aparezcan es que alguien las haya vuelto a escribir.
    """
    fuente = _PROSE.read_text(encoding="utf-8")
    assert "_VALIDATION_STATUS_BANDS" not in fuente
    assert "_VALIDATION_FAMILY_LABELS" not in fuente
    for palabra in ("Pass técnico", "Falla técnica"):
        assert palabra not in fuente, f"«{palabra}» sigue escrita en la prosa del informe"


def test_el_semaforo_del_html_lee_las_palabras_de_su_fuente() -> None:
    """El tercer consumidor censado en S8: `_band_class` mapea por RÓTULO, no por slug.

    Con las palabras repetidas a mano, traducir una banda dejaba su color en gris —«no evaluado»—
    sin que nada lo acusara. Ahora las lee de las dos fuentes únicas, y este gate fija que siga
    siendo así: un literal nuevo ahí es la reaparición del defecto.
    """
    fuente = (_RAIZ / "src" / "nikodym" / "report" / "renderer.py").read_text(encoding="utf-8")
    for palabra in ("Pass técnico", "Falla técnica", "Requiere revisión", "Requiere redesarrollo"):
        assert palabra not in fuente, f"«{palabra}» volvió al mapa del semáforo"
    assert 'BAND_LABELS["review"]' in fuente
    assert 'VALIDATION_STATUS_LABELS["fail"]' in fuente


def test_la_prosa_del_informe_ya_no_tiene_su_propio_diccionario_de_bandas() -> None:
    """La fuente es una: si vuelve a nacer un mapa local, el espejo deja de significar algo."""
    fuente = _PROSE.read_text(encoding="utf-8")
    assert "_STABILITY_BANDS" not in fuente
    assert "Requiere redesarrollo" not in fuente
    assert "from nikodym.stability.results import BAND_LABELS, PSI_METRIC_LABELS" in fuente


def test_la_prosa_del_informe_sigue_sin_arrastrar_pandas() -> None:
    """El rótulo de los motivos vive en ``selection`` (que sí importa pandas) y por eso su import
    va dentro de ``_reason_label``. Sin este gate, subirlo al módulo pasa inadvertido."""
    code = (
        "import sys, nikodym.report.prose as p;"
        "assert 'pandas' not in sys.modules, 'prose arrastró pandas al importarse';"
        "assert p._reason_label('low_iv') == 'IV insuficiente';"
        "assert p._quality_label('near_unique') == 'casi única';"
        "assert p._eda_axis_label('cohort') == 'por cohorte';"
        "assert p._eda_reason_label('tasa_media_cero').startswith('sin incumplimientos');"
        "assert 'pandas' in sys.modules, 'el import perezoso no llegó a ejecutarse'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# ───────────────── 4. D-SC-5: los tipos del panel de EDA espejan al motor ─────────────────


def _claves_de_la_interfaz_ts(nombre: str) -> list[str]:
    """Las claves de ``export interface <nombre> { ... }`` en ``results-types.ts``, en su orden."""
    texto = _RESULTS_TYPES.read_text(encoding="utf-8")
    cuerpo = re.search(rf"^export interface {re.escape(nombre)} \{{\n(.*?)^\}}", texto, re.S | re.M)
    assert cuerpo is not None, f"results-types.ts no declara `export interface {nombre}`"
    return re.findall(r"^  ([a-z_0-9]+)\??:", cuerpo.group(1), re.M)


def test_el_tipo_eda_result_espeja_la_card_y_sus_tres_tablas() -> None:
    """Renombrar, añadir o quitar un campo de ``EdaCardSection`` sin tocar el tipo pone rojo.

    Las tres tablas van al final, en el orden en que el serializer las fusiona, y son las únicas
    claves que la card no declara: cualquier otra diferencia es deriva.
    """
    assert _claves_de_la_interfaz_ts("EdaResult") == [
        *EdaCardSection.model_fields,
        "default_rate",
        "quality",
        "univariate",
    ]


def test_las_filas_de_la_tasa_y_de_la_calidad_espejan_las_columnas_del_motor() -> None:
    """Las tablas viajan tal cual las publica el motor: mismas columnas, mismo orden.

    La fila de la tasa lleva además `period_type`, que añade el serializer al final: el tipo con
    que el motor distinguió la cohorte, para que la pantalla no funda dos que JSON escribe igual.
    """
    from nikodym.ui import serializers

    fuente = Path(serializers.__file__).read_text(encoding="utf-8")
    inicio = fuente.index("def _eda_default_rate(")
    cuerpo = fuente[inicio : fuente.index("\n\n\ndef ", inicio)]
    asignadas = re.findall(r"^\s+([a-z_]+)=by_period\[", cuerpo, re.M)
    anadidas = [columna for columna in asignadas if columna not in _COLUMNAS_TASA]
    assert anadidas == ["period_type"], "el serializer cambió lo que añade a la fila de la tasa"
    assert _claves_de_la_interfaz_ts("EdaPeriodRow") == [*_COLUMNAS_TASA, *anadidas]
    assert _claves_de_la_interfaz_ts("EdaQualityRow") == list(_COLUMNAS_CALIDAD)


def test_la_fila_del_perfil_espeja_lo_que_el_serializer_aplana() -> None:
    """El perfil por variable no es un frame del motor sino la proyección plana del serializer
    (columna delante, un tramo por fila): el tipo espeja esa proyección, medida sobre su código."""
    from nikodym.ui import serializers

    fuente = Path(serializers.__file__).read_text(encoding="utf-8")
    inicio = fuente.index("def _eda_univariate(")
    cuerpo = fuente[inicio : fuente.index("\n\n\ndef ", inicio)]
    claves = re.findall(r'^\s+"([a-z_]+)": ', cuerpo, re.M)
    assert claves, "no se pudieron leer las claves que `_eda_univariate` escribe"
    assert _claves_de_la_interfaz_ts("EdaProfileRow") == claves
