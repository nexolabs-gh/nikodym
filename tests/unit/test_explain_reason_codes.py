"""Tests de ``explain.reason_codes``: traducción pura de contribuciones a reason codes (SDD-14).

Se ejercen con **golden values calculados a mano** sobre matrices ``(n_obs, n_features)`` conocidas:
signo → dirección, orden por magnitud con desempate lexicográfico, piso ``min_abs_contribution``,
acotado silencioso de ``top_n``, inclusión de protectores y una tupla por observación. La finitud y
la alineación con ``feature_names`` se prueban como contrato ruidoso. Un subproceso verifica el
import liviano (sin arrastrar ``numpy``).
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from nikodym.explain.exceptions import ExplainReasonCodeError
from nikodym.explain.reason_codes import build_reason_codes
from nikodym.explain.results import ReasonCode

_FEATURES = ("ingreso__woe", "mora__woe", "edad__woe")


# ── dirección por signo ─────────────────────────────────────────────────────────────────────────
def test_contribucion_positiva_es_increases_pd() -> None:
    """φ_j > 0 ⇒ direction='increases_pd' (driver adverso, sube la PD)."""
    contributions = np.array([[0.5, 0.1, 0.3]], dtype="float64")
    result = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=False,
        min_abs_contribution=0.0,
    )
    (codes,) = result
    assert all(code.direction == "increases_pd" for code in codes)
    assert [code.feature for code in codes] == ["ingreso__woe", "edad__woe", "mora__woe"]
    assert [code.rank for code in codes] == [1, 2, 3]
    assert [code.contribution for code in codes] == [0.5, 0.3, 0.1]
    assert all(code.bin_label is None for code in codes)


def test_negativos_excluidos_sin_protectores() -> None:
    """Sin include_protective, los φ_j < 0 no entran (solo drivers adversos)."""
    contributions = np.array([[0.5, -0.9, 0.2]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=False,
        min_abs_contribution=0.0,
    )
    assert [code.feature for code in codes] == ["ingreso__woe", "edad__woe"]
    assert all(code.direction == "increases_pd" for code in codes)


def test_protectores_incluidos_con_flag() -> None:
    """φ_j < 0 + include_protective ⇒ direction='decreases_pd' y compiten por magnitud."""
    contributions = np.array([[0.5, -0.9, 0.2]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=True,
        min_abs_contribution=0.0,
    )
    assert [code.feature for code in codes] == ["mora__woe", "ingreso__woe", "edad__woe"]
    assert [code.direction for code in codes] == [
        "decreases_pd",
        "increases_pd",
        "increases_pd",
    ]
    assert [code.contribution for code in codes] == [-0.9, 0.5, 0.2]


def test_contribucion_cero_se_descarta() -> None:
    """φ_j == 0 no empuja la PD: no genera reason code (aunque supere el piso 0.0)."""
    contributions = np.array([[0.0, 0.4, -0.0]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=True,
        min_abs_contribution=0.0,
    )
    assert [code.feature for code in codes] == ["mora__woe"]


# ── orden y desempate ───────────────────────────────────────────────────────────────────────────
def test_desempate_lexicografico_con_magnitudes_iguales() -> None:
    """Dos |φ| iguales se ordenan por nombre de feature ascendente (estable, reproducible)."""
    features = ("zeta__woe", "alfa__woe")
    contributions = np.array([[0.4, 0.4]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        features,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=False,
        min_abs_contribution=0.0,
    )
    assert [code.feature for code in codes] == ["alfa__woe", "zeta__woe"]
    assert [code.rank for code in codes] == [1, 2]


def test_signo_opuesto_misma_magnitud_desempata_por_nombre() -> None:
    """Con protectores, un adverso y un protector de igual |φ| desempatan por nombre."""
    features = ("zeta__woe", "alfa__woe")
    contributions = np.array([[0.4, -0.4]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        features,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=True,
        min_abs_contribution=0.0,
    )
    assert [(code.feature, code.direction) for code in codes] == [
        ("alfa__woe", "decreases_pd"),
        ("zeta__woe", "increases_pd"),
    ]


# ── piso y acotado ──────────────────────────────────────────────────────────────────────────────
def test_min_abs_contribution_filtra_magnitudes_menores() -> None:
    """min_abs_contribution es un piso: descarta features con |φ_j| por debajo."""
    contributions = np.array([[0.5, 0.05, 0.2]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=False,
        min_abs_contribution=0.1,
    )
    assert [code.feature for code in codes] == ["ingreso__woe", "edad__woe"]
    assert all(abs(code.contribution) >= 0.1 for code in codes)


def test_top_n_limita_al_numero_pedido() -> None:
    """top_n < n_features toma solo los primeros top_n por magnitud."""
    contributions = np.array([[0.5, 0.1, 0.3]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=2,
        adverse_direction="increases_pd",
        include_protective=False,
        min_abs_contribution=0.0,
    )
    assert [code.feature for code in codes] == ["ingreso__woe", "edad__woe"]
    assert len(codes) == 2


def test_top_n_mayor_que_features_se_acota_sin_error() -> None:
    """top_n > n_features se acota silenciosamente a min(top_n, n_features) sin error."""
    contributions = np.array([[0.5, 0.1, 0.3]], dtype="float64")
    (codes,) = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=99,
        adverse_direction="increases_pd",
        include_protective=False,
        min_abs_contribution=0.0,
    )
    assert len(codes) == 3
    assert [code.rank for code in codes] == [1, 2, 3]


# ── una tupla por observación ─────────────────────────────────────────────────────────────────────
def test_una_tupla_de_reason_codes_por_observacion() -> None:
    """La salida tiene una tupla de reason codes por fila de la matriz, en orden."""
    contributions = np.array(
        [
            [0.5, 0.1, 0.3],
            [-0.2, 0.8, 0.0],
        ],
        dtype="float64",
    )
    result = build_reason_codes(
        contributions,
        _FEATURES,
        top_n=5,
        adverse_direction="increases_pd",
        include_protective=False,
        min_abs_contribution=0.0,
    )
    assert len(result) == 2
    assert all(isinstance(codes, tuple) for codes in result)
    assert all(isinstance(code, ReasonCode) for codes in result for code in codes)
    assert [code.feature for code in result[0]] == ["ingreso__woe", "edad__woe", "mora__woe"]
    assert [code.feature for code in result[1]] == ["mora__woe"]


def test_matriz_sin_observaciones_da_tupla_vacia() -> None:
    """Una matriz con 0 observaciones produce una tupla vacía (sin reason codes)."""
    contributions = np.empty((0, 3), dtype="float64")
    assert (
        build_reason_codes(
            contributions,
            _FEATURES,
            top_n=5,
            adverse_direction="increases_pd",
            include_protective=False,
            min_abs_contribution=0.0,
        )
        == ()
    )


# ── contrato ruidoso ──────────────────────────────────────────────────────────────────────────────
def test_top_n_menor_que_uno_es_error() -> None:
    """top_n < 1 no tiene sentido (0 reason codes / slice negativo) ⇒ error de contrato."""
    contributions = np.array([[0.5, 0.1, 0.3]], dtype="float64")
    with pytest.raises(ExplainReasonCodeError, match="top_n debe ser al menos 1"):
        build_reason_codes(
            contributions,
            _FEATURES,
            top_n=0,
            adverse_direction="increases_pd",
            include_protective=False,
            min_abs_contribution=0.0,
        )


def test_min_abs_contribution_negativo_es_error() -> None:
    """Un piso negativo es un contrato inválido (no filtra nada de forma silenciosa)."""
    contributions = np.array([[0.5, 0.1, 0.3]], dtype="float64")
    with pytest.raises(ExplainReasonCodeError, match="piso finito y no negativo"):
        build_reason_codes(
            contributions,
            _FEATURES,
            top_n=5,
            adverse_direction="increases_pd",
            include_protective=False,
            min_abs_contribution=-0.1,
        )


def test_min_abs_contribution_no_finito_es_error() -> None:
    """Un piso NaN descartaría todo en silencio (|φ| >= NaN es False) ⇒ error de contrato."""
    contributions = np.array([[0.5, 0.1, 0.3]], dtype="float64")
    with pytest.raises(ExplainReasonCodeError, match="piso finito y no negativo"):
        build_reason_codes(
            contributions,
            _FEATURES,
            top_n=5,
            adverse_direction="increases_pd",
            include_protective=False,
            min_abs_contribution=float("nan"),
        )


def test_matriz_no_bidimensional_es_error() -> None:
    """contributions debe ser 2D (n_obs, n_features); un vector 1D falla ruidoso."""
    contributions = np.array([0.5, 0.1, 0.3], dtype="float64")
    with pytest.raises(ExplainReasonCodeError, match="matriz 2D"):
        build_reason_codes(
            contributions,
            _FEATURES,
            top_n=5,
            adverse_direction="increases_pd",
            include_protective=False,
            min_abs_contribution=0.0,
        )


def test_columnas_desalineadas_con_feature_names_es_error() -> None:
    """El nº de columnas de la matriz debe coincidir con feature_names."""
    contributions = np.array([[0.5, 0.1]], dtype="float64")
    with pytest.raises(ExplainReasonCodeError, match="desalineados"):
        build_reason_codes(
            contributions,
            _FEATURES,
            top_n=5,
            adverse_direction="increases_pd",
            include_protective=False,
            min_abs_contribution=0.0,
        )


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_contribuciones_no_finitas_son_error(bad: float) -> None:
    """NaN/inf en las contribuciones es un error de contrato aguas arriba, no se propaga."""
    contributions = np.array([[0.5, bad, 0.3]], dtype="float64")
    with pytest.raises(ExplainReasonCodeError, match="no finitos"):
        build_reason_codes(
            contributions,
            _FEATURES,
            top_n=5,
            adverse_direction="increases_pd",
            include_protective=False,
            min_abs_contribution=0.0,
        )


# ── import liviano (núcleo) ─────────────────────────────────────────────────────────────────────
def test_import_reason_codes_liviano_no_arrastra_numpy_ni_shap() -> None:
    """Importar el módulo no debe cargar numpy/shap/pandas (import perezoso, SDD-14 §9)."""
    code = (
        "import nikodym.explain.reason_codes, sys;"
        "bloqueados=[m for m in ('numpy','shap','matplotlib','sklearn','pandas') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
