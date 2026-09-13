"""Los prefijos de fórmula de una planilla se neutralizan al exportar, y sólo ellos.

🔴 Hallazgo de la revisión adversarial (pasada 2 sobre d99bc9d): la tabla completa de la tasa por
cohorte viaja como CSV con BOM «para Excel» y la etiqueta de cohorte viene del archivo del usuario,
así que un valor ``=HYPERLINK(...)`` llegaba como fórmula viva al escritorio de quien lo abre. Los
exports por observación del informe (CSV y XLSX) llevan el mismo tipo de datos y se protegen igual.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nikodym.core.spreadsheet_safety import FORMULA_PREFIXES, neutralize_formula_prefixes

_VENENOSOS = [
    '=HYPERLINK("http://x.invalid";"ver")',
    "+1+1",
    "-cmd|' /C calc'!A0",
    "@SUM(A1)",
    "\t=1",
    "\r=1",
]


def test_las_celdas_de_texto_con_prefijo_activo_se_protegen_y_las_demas_no() -> None:
    frame = pd.DataFrame(
        {
            "texto": [*_VENENOSOS, "normal", "op-001", ""],
            "numero": [-1, -2, -3, -4, -5, -6, -7, -8, -9],
            "logico": [True] * 9,
        }
    )
    protegido = neutralize_formula_prefixes(frame)
    assert protegido["texto"].tolist() == [*(f"'{v}" for v in _VENENOSOS), "normal", "op-001", ""]
    # Un número negativo NO es un prefijo de fórmula: sigue siendo un número.
    assert protegido["numero"].tolist() == frame["numero"].tolist()
    assert protegido["logico"].tolist() == [True] * 9
    # El frame recibido no se muta.
    assert frame["texto"].tolist()[0] == _VENENOSOS[0]


def test_el_indice_de_texto_tambien_se_protege() -> None:
    """El identificador de la operación sale como índice en los exports del informe."""
    frame = pd.DataFrame({"valor": [1, 2]}, index=pd.Index(["=1+1", "op-002"], name="loan_id"))
    protegido = neutralize_formula_prefixes(frame)
    assert protegido.index.tolist() == ["'=1+1", "op-002"]
    assert protegido.index.name == "loan_id"
    assert frame.index.tolist() == ["=1+1", "op-002"]


def test_sin_celdas_activas_devuelve_el_mismo_objeto() -> None:
    """Un export sin nada que proteger sigue siendo, byte a byte, el de siempre."""
    frame = pd.DataFrame({"texto": ["a", "b"], "n": [1, 2]}, index=pd.Index(["x", "y"]))
    assert neutralize_formula_prefixes(frame) is frame


def test_una_columna_de_texto_nativa_de_pandas_se_protege_igual() -> None:
    frame = pd.DataFrame({"texto": pd.array(["=1", "b"], dtype="string")})
    assert neutralize_formula_prefixes(frame)["texto"].tolist() == ["'=1", "b"]


def test_los_encabezados_y_el_nombre_del_indice_tambien_son_celdas() -> None:
    """🔴 Pasada 3 de la revisión adversarial (b71f599): el nombre de una columna es una celda del
    CSV/XLSX y viene del archivo del usuario (una variable llamada `=HYPERLINK(...)`, y el WoE
    deriva nombres de la variable original); el nombre del índice, igual."""
    frame = pd.DataFrame(
        {"=SUM(A1)": [1, 2], "normal": [3, 4], 7: [5, 6]},
        index=pd.Index(["a", "b"], name="-id"),
    )
    protegido = neutralize_formula_prefixes(frame)
    assert list(protegido.columns) == ["'=SUM(A1)", "normal", 7]
    assert protegido.index.name == "'-id"
    assert list(frame.columns) == ["=SUM(A1)", "normal", 7] and frame.index.name == "-id"


def test_una_categorica_y_un_indice_categorico_se_protegen() -> None:
    """🔴 Pasada 3: `category` no es `object` ni `string`, pero sus niveles son texto del usuario.

    Y un índice categórico, igual: es el identificador que sale como primera columna.
    """
    frame = pd.DataFrame(
        {"nivel": pd.Categorical(["=1", "b", "@x"]), "n": [1, 2, 3]},
        index=pd.CategoricalIndex(["+a", "b", "c"], name="loan_id"),
    )
    protegido = neutralize_formula_prefixes(frame)
    assert protegido["nivel"].tolist() == ["'=1", "b", "'@x"]
    assert protegido.index.tolist() == ["'+a", "b", "c"]
    assert protegido["n"].tolist() == [1, 2, 3]
    assert frame["nivel"].tolist() == ["=1", "b", "@x"]


@pytest.mark.parametrize("prefijo", FORMULA_PREFIXES)
def test_cada_prefijo_declarado_se_protege(prefijo: str) -> None:
    frame = pd.DataFrame({"texto": [f"{prefijo}x"]})
    assert neutralize_formula_prefixes(frame)["texto"].tolist() == [f"'{prefijo}x"]
