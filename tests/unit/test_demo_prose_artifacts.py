"""Gate de prosa factual sobre los entregables versionados de las tres demos."""

from pathlib import Path
from runpy import run_path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_demo_prose_artifacts.py"
_SYMBOLS = run_path(str(_SCRIPT))
_normalize = _SYMBOLS["_normalize"]
verify_all_demo_families = _SYMBOLS["verify_all_demo_families"]


def test_normalizacion_tolera_mayusculas_editoriales_y_espaciado_de_extractores() -> None:
    assert _normalize("DESEMPEÑO\n POR  TRAMO DE RIESGO") == _normalize(
        "Desempeño por tramo de riesgo"
    )


def test_html_pdf_word_quarto_y_json_demo_cierran_la_misma_verdad() -> None:
    """Los bytes descargables y el resumen JSON deben pasar el oráculo canónico."""
    pytest.importorskip("docx", reason="el gate Word requiere el extra docx")
    pytest.importorskip("pypdf", reason="el gate PDF requiere las dependencias de test completas")
    verify_all_demo_families()
