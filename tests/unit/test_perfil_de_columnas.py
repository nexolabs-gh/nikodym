"""Gate del perfil de columnas (enmienda PERFIL-DE-COLUMNAS, D-PERF-1…D-PERF-8).

Una columna identificador entra al binning por el comodín, OptBinning manda todas sus categorías al
bin «otros», se queda sin ninguna y mata la corrida. Se descubrió con un CSV de cartera corriente
verificando el gate de aceptación de P1, no con un censo.

Lo que este archivo vigila es que el aviso **exista y no invente**: los dos falsos positivos
plausibles —una columna numérica de cardinalidad máxima, una de texto con pocos valores— tienen su
control negativo, porque un aviso que se dispara de más se aprende a ignorar y deja de servir.
"""

from __future__ import annotations

import pandas as pd
import pytest

from nikodym.binning.config import BinningConfig
from nikodym.binning.transformer import _mensaje_de_fallo
from nikodym.core.config import NikodymConfig
from nikodym.core.dataset_check import PerfilColumna, PerfilDataset, check_dataset
from nikodym.ui.presets import standard_preset


def _perfil(*columnas: PerfilColumna, n_filas: int = 1000) -> PerfilDataset:
    return PerfilDataset(n_filas=n_filas, columnas=columnas)


IDENTIFICADOR = PerfilColumna("id_operacion", n_unicos=1000, es_numerica=False)
CONTINUA = PerfilColumna("carga_financiera", n_unicos=1000, es_numerica=True)
CATEGORICA = PerfilColumna("producto", n_unicos=3, es_numerica=False)


def test_una_columna_identificador_se_avisa() -> None:
    """El caso de origen: texto con un valor por fila, entrando por el comodín."""
    requisitos = BinningConfig().requisitos_incumplidos_por_perfil(_perfil(IDENTIFICADOR))
    assert len(requisitos) == 1
    assert requisitos[0].path == "feature_columns"
    assert "id_operacion" in requisitos[0].message


def test_una_columna_numerica_de_cardinalidad_maxima_no_se_avisa() -> None:
    """Primer falso positivo plausible, y el que más importa descartar (D-PERF-5).

    Una variable continua tiene tantos valores distintos como filas y el binning la discretiza sin
    ningún problema: es el caso NORMAL de un predictor, no una anomalía. Medido en el dataset que
    destapó el defecto: `carga_financiera` tenía 3.423 valores distintos y corrió bien.
    """
    assert BinningConfig().requisitos_incumplidos_por_perfil(_perfil(CONTINUA)) == ()


def test_una_columna_de_texto_con_pocos_valores_no_se_avisa() -> None:
    """Segundo falso positivo: una categórica de verdad es justo lo que el binning quiere."""
    assert BinningConfig().requisitos_incumplidos_por_perfil(_perfil(CATEGORICA)) == ()


@pytest.mark.parametrize(
    "config",
    [
        pytest.param(BinningConfig(exclude_columns=("id_operacion",)), id="excluida"),
        pytest.param(BinningConfig(categorical_columns=("id_operacion",)), id="forzada-categorica"),
        pytest.param(BinningConfig(feature_columns=("edad",)), id="lista-explicita"),
    ],
)
def test_no_se_avisa_cuando_el_usuario_ya_decidio(config: BinningConfig) -> None:
    """Nombrar una columna es decir que la quieres: el aviso es para el descuido del comodín."""
    assert config.requisitos_incumplidos_por_perfil(_perfil(IDENTIFICADOR)) == ()


def test_el_umbral_no_es_el_cien_por_ciento() -> None:
    """D-PERF-5: un identificador real puede traer nulos o algún duplicado y no deja de serlo."""
    casi = PerfilColumna("id_operacion", n_unicos=970, es_numerica=False)
    assert len(BinningConfig().requisitos_incumplidos_por_perfil(_perfil(casi))) == 1
    # Y por debajo del umbral no se afirma nada: 900/1000 es alta cardinalidad, no un identificador.
    poco = PerfilColumna("comuna", n_unicos=900, es_numerica=False)
    assert BinningConfig().requisitos_incumplidos_por_perfil(_perfil(poco)) == ()


def test_un_perfil_sin_filas_no_afirma_nada() -> None:
    """División por cero y afirmación sin base: las dos se evitan con la misma guarda."""
    vacio = PerfilDataset(n_filas=0, columnas=(IDENTIFICADOR,))
    assert BinningConfig().requisitos_incumplidos_por_perfil(vacio) == ()


def test_sin_perfil_check_dataset_se_comporta_igual_que_antes() -> None:
    """D-PERF-2: ``None`` es «no se sabe», no «no hay».

    Es la misma decisión que ``index_columns``, y por la misma razón: afirmar sin el dato
    reintroduce el falso positivo, que aquí sería acusar de identificador a una columna que nadie
    midió. Omitir el parámetro tiene que dejar el veredicto **idéntico**.
    """
    config = NikodymConfig.model_validate(standard_preset()["config"])
    columnas = ["id_operacion", "edad", "renta"]
    sin_perfil = check_dataset(config, columnas)
    con_perfil_none = check_dataset(config, columnas, column_profile=None)
    assert [m.path for m in sin_perfil.mismatches] == [m.path for m in con_perfil_none.mismatches]
    assert sin_perfil.compatible == con_perfil_none.compatible


def test_el_aviso_llega_por_check_dataset_con_perfil() -> None:
    """La invariante no sirve si el recorrido no la recoge: se mira la superficie pública."""
    config = NikodymConfig.model_validate(
        {**standard_preset()["config"], "binning": {"type": "standard", "feature_columns": "*"}}
    )
    columnas = ["id_operacion", "edad"]
    perfil = _perfil(
        IDENTIFICADOR,
        PerfilColumna("edad", n_unicos=54, es_numerica=True),
    )
    veredicto = check_dataset(config, columnas, column_profile=perfil)
    avisos = [m for m in veredicto.mismatches if m.path == "binning.feature_columns"]
    assert len(avisos) == 1, [m.path for m in veredicto.mismatches]
    assert avisos[0].kind == "unmet_requirement"
    assert "id_operacion" in avisos[0].message


def test_el_copy_del_aviso_no_trae_jerga_ni_nombra_la_libreria() -> None:
    """Es copy público: se lee sin hover y sin saber qué hay debajo (regla de copy del repo)."""
    mensaje = BinningConfig().requisitos_incumplidos_por_perfil(_perfil(IDENTIFICADOR))[0].message
    for prohibido in ("OptBinning", "cardinalidad", "None", "True", "False", "dtype", "nunique"):
        assert prohibido not in mensaje, prohibido
    # Y dice la SALIDA, no sólo el problema (D-INV-6).
    assert "llave de unicidad" in mensaje


def test_el_error_del_motor_nombra_la_columna_y_la_salida() -> None:
    """D-PERF-8: el aviso previo no sustituye al mensaje del motor.

    Quien usa la librería por código no pasa por el preflight, y quien ignora el aviso aterriza
    igual aquí. Antes, el error era el de OptBinning tal cual: en inglés, sin nombrar la columna y
    sin decir qué hacer.

    Se prueba la TRADUCCIÓN con el mensaje literal que emite OptBinning, en vez de ajustar el motor
    de verdad: el ajuste real sobre un frame así hace caer el solver dentro de pytest —comprobado—,
    y un test que revienta el runner no vigila nada. El mensaje literal es lo que hay que reconocer,
    y es lo que este test ancla.
    """
    frame = pd.DataFrame(
        {"id_op": [f"OP{i:05d}" for i in range(400)], "edad": [20 + i % 50 for i in range(400)]}
    )
    original = ValueError(
        "All categories moved to others' bin. At least one category is needed to perform binning."
    )
    mensaje = _mensaje_de_fallo(original, frame)
    assert "id_op" in mensaje
    assert "llave de unicidad" in mensaje
    assert "OptBinning" not in mensaje
    assert "categories" not in mensaje


def test_un_fallo_del_motor_por_otra_causa_no_se_disfraza() -> None:
    """El error simétrico: no todo fallo del ajuste es una columna identificador.

    Sin esta guarda, cualquier caída del binning se explicaría con la misma historia y mandaría al
    usuario a declarar una llave que no tiene nada que ver.
    """
    frame = pd.DataFrame({"edad": [20, 30, 40]})
    mensaje = _mensaje_de_fallo(ValueError("target must be binary"), frame)
    assert "identificador" not in mensaje
    assert "target must be binary" in mensaje


def test_el_fallo_sin_columna_sospechosa_no_acusa_a_ninguna() -> None:
    """Mismo mensaje de OptBinning pero sin ninguna columna que encaje: no se inventa una."""
    frame = pd.DataFrame({"producto": ["a", "b", "a", "b"]})
    mensaje = _mensaje_de_fallo(ValueError("All categories moved to others' bin."), frame)
    assert "identificador" not in mensaje
    assert "Revisa las variables candidatas" in mensaje


def test_el_perfil_viaja_por_la_ingesta_y_lo_recupera_el_preflight(tmp_path: object) -> None:
    """La cadena completa: sin ella la invariante existe y el usuario no la ve nunca."""
    from pathlib import Path

    from nikodym.ui import datasets

    workdir = Path(str(tmp_path))
    frame = pd.DataFrame(
        {"id_operacion": [f"OP{i:05d}" for i in range(50)], "edad": list(range(20, 70))}
    )
    contenido = frame.to_csv(index=False).encode("utf-8")
    ingerido = datasets.ingest_upload(contenido, "cartera.csv", workdir=workdir)

    perfil = datasets.load_profile(ingerido["dataset_id"], workdir=workdir)
    assert perfil is not None
    assert perfil.n_filas == 50
    identificador = perfil.de("id_operacion")
    assert identificador is not None
    assert identificador.n_unicos == 50
    assert identificador.es_numerica is False
    edad = perfil.de("edad")
    assert edad is not None and edad.es_numerica is True
    # Una columna que no existe no se inventa.
    assert perfil.de("no_existe") is None


def test_un_dataset_sin_perfil_devuelve_none(tmp_path: object) -> None:
    """El error simétrico: un dataset del catálogo o anterior a la enmienda no tiene perfil."""
    from pathlib import Path

    from nikodym.ui import datasets

    assert datasets.load_profile("consumo_comportamiento", workdir=Path(str(tmp_path))) is None
