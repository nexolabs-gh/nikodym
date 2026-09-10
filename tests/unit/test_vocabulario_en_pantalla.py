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
from nikodym.selection.config import SelectionConfig
from nikodym.selection.results import REASON_LABELS, SelectionDecisionReason
from nikodym.stability.results import BAND_LABELS, PSI_METRIC_LABELS, PsiMetricName, StabilityBand

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
        (REASON_LABELS, SelectionDecisionReason, "REASON_LABELS"),
        (IV_BAND_LABELS, IvBand, "IV_BAND_LABELS"),
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
        (REASON_LABELS, "REASON_LABELS"),
        (IV_BAND_LABELS, "IV_BAND_LABELS"),
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


@pytest.mark.parametrize(
    ("enum", "interfaz"),
    [
        (StabilityBand, "StabilityBand"),
        (PsiMetricName, "PsiSummaryMetric"),
        (SelectionDecisionReason, "SelectionDecisionReason"),
        (IvBand, "IvBand"),
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
        "assert 'pandas' in sys.modules, 'el import perezoso no llegó a ejecutarse'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
