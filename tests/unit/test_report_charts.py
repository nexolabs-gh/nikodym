"""Tests del módulo net-new ``nikodym.report.charts`` (bloque B1).

Cubren determinismo (auto-consistencia same-machine, independencia de ``PYTHONHASHSEED``),
sanitizado anti-no-determinismo del SVG, validación de columnas, import liviano (importar el módulo
no trae ``matplotlib``) y accesibilidad (``<title>``/``role``/``style``). Todo el archivo se gatea
con ``skipif`` cuando falta el extra ``report`` (matplotlib), como ``test_ml_backends.py``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
import sys
from typing import Any, cast

import pandas as pd
import pytest

from nikodym.report.exceptions import ReportInputError

_HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None

pytestmark = pytest.mark.skipif(not _HAS_MATPLOTLIB, reason="requiere el extra report (matplotlib)")

# El módulo se importa a nivel de test (no de paquete) para no arrastrar matplotlib en otros tests
# cuando el extra no está; con el gate skipif de arriba esto sólo corre si matplotlib existe.
import nikodym.report.charts as charts  # noqa: E402

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_ISO_DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")


# ─────────────────────────── fixtures de datos sintéticos mínimos ───────────────────────────


def _deciles_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "partition": partition,
                "decile": decile,
                "cum_total": decile * 100,
                "cum_bad_capture_rate": min(1.0, decile / 10 * 1.3),
                "cum_good_capture_rate": decile / 10,
                "lift": 1.2,
                "ks_at_decile": 0.3,
            }
            for partition in ("oot", "desarrollo", "holdout")
            for decile in range(1, 11)
        ]
    )


def _reliability_payload() -> list[dict[str, Any]]:
    return [
        {
            "partition": partition,
            "n": 500,
            "brier": 0.12,
            "ece": 0.03,
            "bins": [
                {
                    "bin": index,
                    "n": 50,
                    "mean_predicted_pd": index / 10,
                    "observed_default_rate": min(1.0, index / 10 + 0.02),
                    "ci_low": max(0.0, index / 10 - 0.01),
                    "ci_high": min(1.0, index / 10 + 0.05),
                    "pd_lo": index / 10,
                    "pd_hi": index / 10 + 0.1,
                }
                for index in range(1, 6)
            ],
        }
        for partition in ("holdout", "desarrollo")
    ]


def _coefficients_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"feature": "intercept", "beta": -2.1, "conf_low": -2.3, "conf_high": -1.9},
            {"feature": "ingresos", "beta": -0.8, "conf_low": -1.0, "conf_high": -0.6},
            {"feature": "mora", "beta": 0.5, "conf_low": None, "conf_high": None},
            {"feature": "edad", "beta": -0.15, "conf_low": -0.25, "conf_high": -0.05},
        ]
    )


def _discriminant_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "partition": "desarrollo",
                "n_total": 1000,
                "n_bad": 100,
                "n_good": 900,
                "auc": 0.82,
                "gini": 0.64,
                "ks": 0.48,
            },
            {
                "partition": "holdout",
                "n_total": 500,
                "n_bad": 50,
                "n_good": 450,
                "auc": 0.79,
                "gini": 0.58,
                "ks": 0.44,
            },
            {
                "partition": "oot",
                "n_total": 400,
                "n_bad": None,
                "n_good": None,
                "auc": None,
                "gini": None,
                "ks": None,
            },
        ]
    )


def _stability_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric": "score_psi",
                "comparison": "dev_vs_oot",
                "feature": "",
                "value": 0.18,
                "stable_threshold": 0.10,
                "review_threshold": 0.25,
                "band": "review",
                "action": "vigilar",
            },
            {
                "metric": "pd_psi",
                "comparison": "dev_vs_holdout",
                "feature": "",
                "value": 0.04,
                "stable_threshold": 0.10,
                "review_threshold": 0.25,
                "band": "stable",
                "action": "none",
            },
            {
                "metric": "csi",
                "comparison": "dev_vs_oot",
                "feature": "ingresos",
                "value": 0.31,
                "stable_threshold": 0.10,
                "review_threshold": 0.25,
                "band": "redevelop",
                "action": "redesarrollar",
            },
            {
                "metric": "csi",
                "comparison": "dev_vs_oot",
                "feature": "mora",
                "value": None,
                "stable_threshold": 0.10,
                "review_threshold": 0.25,
                "band": "not_evaluable",
                "action": "none",
            },
        ]
    )


def _all_charts() -> dict[str, str]:
    return {
        "gains": charts.render_gains_chart(_deciles_frame(), title="Ganancia"),
        "reliability": charts.render_reliability_chart(_reliability_payload(), title="Calibración"),
        "coefficients": charts.render_coefficients_forest(
            _coefficients_frame(), title="Coeficientes"
        ),
        "discrimination": charts.render_discrimination_bars(
            _discriminant_frame(), title="Discriminación"
        ),
        "stability": charts.render_stability_chart(_stability_frame(), title="Estabilidad"),
    }


# Código ejecutado en subprocesos para el test de independencia de PYTHONHASHSEED. Emite el sha256
# del SVG por stdout; el test compara los sha entre semillas distintas.
_SUBPROCESS_RENDER = """
import hashlib, sys
import pandas as pd
import nikodym.report.charts as charts

deciles = pd.DataFrame([
    {"partition": p, "decile": d, "cum_total": d * 100,
     "cum_bad_capture_rate": min(1.0, d / 10 * 1.3)}
    for p in ("oot", "desarrollo", "holdout") for d in range(1, 11)
])
disc = pd.DataFrame([
    {"partition": "desarrollo", "auc": 0.82, "gini": 0.64, "ks": 0.48},
    {"partition": "holdout", "auc": 0.79, "gini": 0.58, "ks": 0.44},
])
gains = charts.render_gains_chart(deciles, title="Ganancia")
bars = charts.render_discrimination_bars(disc, title="Discriminación")
sys.stdout.write(hashlib.sha256(gains.encode()).hexdigest())
sys.stdout.write(" ")
sys.stdout.write(hashlib.sha256(bars.encode()).hexdigest())
"""


# ─────────────────────────── determinismo ───────────────────────────


@pytest.mark.parametrize(
    "name", ["gains", "reliability", "coefficients", "discrimination", "stability"]
)
def test_render_es_byte_identico_same_machine(name: str) -> None:
    first = _all_charts()[name]
    second = _all_charts()[name]
    assert first == second, f"{name}: dos renders same-machine deben ser byte-idénticos"


def test_independiente_de_pythonhashseed_via_subprocess() -> None:
    def _shas(seed: str) -> str:
        completed = subprocess.run(
            [sys.executable, "-c", _SUBPROCESS_RENDER],
            check=True,
            capture_output=True,
            text=True,
            env={**_clean_env(), "PYTHONHASHSEED": seed},
        )
        return completed.stdout

    assert _shas("0") == _shas("12345"), "el SVG debe ser idéntico entre valores de PYTHONHASHSEED"


def _clean_env() -> dict[str, str]:
    import os

    return dict(os.environ)


# ─────────────────────────── estructura y anti-no-determinismo ───────────────────────────


@pytest.mark.parametrize(
    "name", ["gains", "reliability", "coefficients", "discrimination", "stability"]
)
def test_svg_estructura_y_accesibilidad(name: str) -> None:
    svg = _all_charts()[name]
    assert "<svg" in svg and "viewBox=" in svg
    assert 'role="img"' in svg
    assert 'style="max-width:100%' in svg
    assert svg.endswith("</svg>\n")


@pytest.mark.parametrize(
    "name", ["gains", "reliability", "coefficients", "discrimination", "stability"]
)
def test_svg_sin_fuentes_de_no_determinismo(name: str) -> None:
    svg = _all_charts()[name]
    assert "<?xml" not in svg
    assert "<!DOCTYPE" not in svg
    assert "<dc:date" not in svg
    assert "/Users/" not in svg
    assert _UUID_RE.search(svg) is None
    assert _ISO_DATE_RE.search(svg) is None
    # ``-0.0`` sólo se vigila en el TEXTO visible (los datos de <path> contienen "-0.05" legítimo).
    visible = re.sub(r"<[^>]+>", "", svg)
    assert "-0.0" not in visible
    assert "202" not in visible


def test_title_accesible_escapado() -> None:
    svg = charts.render_gains_chart(_deciles_frame(), title="Ganancia & <curva>")
    assert "<title>Ganancia &amp; &lt;curva&gt;</title>" in svg
    # El <title> es el primer hijo del <svg> raíz.
    root_open = svg.index(">", svg.index("<svg"))
    assert svg[root_open + 1 :].startswith("<title>")


def test_coefficients_acepta_lista_de_dicts() -> None:
    as_records = cast("list[dict[str, Any]]", _coefficients_frame().to_dict(orient="records"))
    from_records = charts.render_coefficients_forest(as_records, title="Coeficientes")
    from_frame = charts.render_coefficients_forest(_coefficients_frame(), title="Coeficientes")
    assert from_records == from_frame


# ─────────────────────────── validación de entrada ───────────────────────────


def test_gains_sin_columnas_requeridas_falla() -> None:
    frame = _deciles_frame().drop(columns=["cum_bad_capture_rate"])
    with pytest.raises(ReportInputError, match="cum_bad_capture_rate"):
        charts.render_gains_chart(frame, title="Ganancia")


def test_discrimination_sin_columnas_requeridas_falla() -> None:
    frame = _discriminant_frame().drop(columns=["gini"])
    with pytest.raises(ReportInputError, match="gini"):
        charts.render_discrimination_bars(frame, title="Discriminación")


def test_stability_sin_columnas_requeridas_falla() -> None:
    frame = _stability_frame().drop(columns=["value"])
    with pytest.raises(ReportInputError, match="value"):
        charts.render_stability_chart(frame, title="Estabilidad")


def test_coefficients_sin_columna_beta_falla() -> None:
    frame = _coefficients_frame().drop(columns=["beta"])
    with pytest.raises(ReportInputError, match="beta"):
        charts.render_coefficients_forest(frame, title="Coeficientes")


def test_reliability_lista_vacia_falla() -> None:
    with pytest.raises(ReportInputError, match="lista no vacía"):
        charts.render_reliability_chart([], title="Calibración")


def test_coefficients_solo_intercepto_falla() -> None:
    frame = pd.DataFrame(
        [{"feature": "intercept", "beta": -2.1, "conf_low": -2.3, "conf_high": -1.9}]
    )
    with pytest.raises(ReportInputError, match="intercepto"):
        charts.render_coefficients_forest(frame, title="Coeficientes")


# --- not_evaluable: None en un record cae como NaN en la columna float64 ---
# ``pd.DataFrame([record.model_dump()...])`` convierte un ``None`` en ``NaN`` y ``NaN is None`` es
# ``False``. Estos tests usan ese path real (None -> NaN) para blindar los guards ``_is_missing``,
# que fallarían con un simple ``is None``.


def test_discrimination_not_evaluable_se_grafica_como_cero() -> None:
    con_nan = pd.DataFrame(
        [
            {"partition": "desarrollo", "auc": 0.82, "gini": 0.64, "ks": 0.48},
            {"partition": "oot", "auc": None, "gini": None, "ks": None},  # not_evaluable → NaN
        ]
    )
    con_cero = pd.DataFrame(
        [
            {"partition": "desarrollo", "auc": 0.82, "gini": 0.64, "ks": 0.48},
            {"partition": "oot", "auc": 0.0, "gini": 0.0, "ks": 0.0},
        ]
    )
    assert con_nan["auc"].isna().any()  # confirma que None cayó como NaN (path real).
    svg_nan = charts.render_discrimination_bars(con_nan, title="Discriminación")
    svg_cero = charts.render_discrimination_bars(con_cero, title="Discriminación")
    assert svg_nan == svg_cero, (
        "not_evaluable (NaN) debe graficarse idéntico a 0.0, no como barra NaN"
    )


def test_stability_not_evaluable_se_omite() -> None:
    con_nan = pd.DataFrame(
        [
            {
                "metric": "csi",
                "comparison": "dev_vs_oot",
                "feature": "ingresos",
                "value": 0.31,
                "stable_threshold": 0.10,
                "review_threshold": 0.25,
            },
            {
                "metric": "csi",
                "comparison": "dev_vs_oot",
                "feature": "mora",
                "value": None,  # not_evaluable → NaN
                "stable_threshold": 0.10,
                "review_threshold": 0.25,
            },
        ]
    )
    sin_fila = con_nan.iloc[[0]].copy()
    assert con_nan["value"].isna().any()  # confirma NaN (path real).
    svg_con = charts.render_stability_chart(con_nan, title="Estabilidad")
    svg_sin = charts.render_stability_chart(sin_fila, title="Estabilidad")
    assert svg_con == svg_sin, (
        "la fila not_evaluable (NaN) debe omitirse (mismo SVG que sin la fila)"
    )


# ─────────────────────────── import liviano ───────────────────────────


def test_importar_charts_no_trae_matplotlib_por_subprocess() -> None:
    code = (
        "import sys; import nikodym.report.charts; "
        "assert 'matplotlib' not in sys.modules, "
        "'importar charts NO debe traer matplotlib'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_paquete_report_sigue_liviano_por_subprocess() -> None:
    code = (
        "import sys; import nikodym.report; "
        "assert 'matplotlib' not in sys.modules, "
        "'importar nikodym.report NO debe traer matplotlib'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


# ─────────────────────────── constancia informativa de sha same-machine ───────────────────────────


def test_reporta_sha_y_tamano_same_machine(capsys: pytest.CaptureFixture[str]) -> None:
    # No se assertea el sha (es same-machine, no cross-OS): sólo se imprime como constancia.
    with capsys.disabled():
        for name, svg in _all_charts().items():
            sha = hashlib.sha256(svg.encode()).hexdigest()
            size_kb = round(len(svg.encode()) / 1024, 1)
            print(f"[charts] {name:14s} {size_kb:5.1f} KB  sha256={sha}")
