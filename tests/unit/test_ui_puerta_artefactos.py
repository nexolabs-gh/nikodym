"""Tests de la puerta de artefactos por HTTP: allowlist, índice y modo posicional (D-PUE-2/3/4/6/7).

La puerta por código admite cualquier objeto; la de la red admite **una tabla**, y sólo si algún
trabajo disponible declara su clave. Estos tests ejercitan las tres cosas que separan una de otra:
qué se acepta, cómo se alinea con la cartera, y qué se responde cuando no cuadra.

⚠️ El caso que NO se puede cubrir con un test es el que la §D-PUE-6 declara asumido: un archivo con
el mismo número de filas en otro orden produce una corrida sin errores con la probabilidad de cada
cliente asignada a otro. No es un defecto que se pueda detectar aquí —haría falta leer los datos y
tener una llave, que es justamente lo que ese modo no tiene—; por eso lleva su aviso y su caveat.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.ui import datasets as datasets_module
from nikodym.ui import routes
from nikodym.ui.exceptions import UiArtifactError

_PD_CLAVE = ["calibration", "calibrated_pd_frame"]
_SCORE_CLAVE = ["scorecard", "score"]


def _subir(workdir: Path, frame: pd.DataFrame, nombre: str) -> str:
    """Ingesta un frame como si el usuario hubiera subido su CSV, y devuelve su identificador."""
    contenido = frame.to_csv(index=False).encode("utf-8")
    return str(datasets_module.ingest_upload(contenido, nombre, workdir=workdir)["dataset_id"])


@pytest.fixture
def cartera(tmp_path: Path) -> str:
    """Un dataset del usuario con seis operaciones identificadas."""
    frame = pd.DataFrame(
        {
            "id_operacion": [f"OP-{i}" for i in range(6)],
            "saldo": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
        }
    )
    return _subir(tmp_path, frame, "cartera.csv")


@pytest.fixture
def modelo(tmp_path: Path) -> str:
    """Lo que el usuario trae de su modelo: una sola tabla con la PD y el puntaje (D-PUE-4)."""
    frame = pd.DataFrame(
        {
            "id_operacion": [f"OP-{i}" for i in range(6)],
            "muestra": ["dev"] * 4 + ["oot"] * 2,
            "malo": [0, 1, 0, 0, 1, 0],
            "probabilidad": [0.1, 0.8, 0.2, 0.05, 0.7, 0.15],
            "puntaje": [700.0, 400.0, 650.0, 720.0, 430.0, 680.0],
        }
    )
    return _subir(tmp_path, frame, "mi_modelo.csv")


# ─────────────────────────────── allowlist (D-PUE-2) ───────────────────────────────


def test_una_clave_que_ningun_trabajo_admite_se_rechaza_sin_tocar_el_disco(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """La allowlist es lo que separa la puerta de la red de la puerta por código.

    Sin ella, un cliente local podría sembrar cualquier clave del vocabulario de dominios y
    desplazar cálculos que el usuario cree que el motor está haciendo.
    """
    with pytest.raises(UiArtifactError, match="no admite"):
        routes._materializar_externos(
            [{"artifact": ["binning", "woe_frame"], "dataset_id": modelo}],
            cartera,
            workdir=tmp_path,
        )


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"artifact": "calibration.calibrated_pd_frame"},
        {"artifact": ["calibration"]},
        {"artifact": ["calibration", "calibrated_pd_frame", "de_mas"]},
        {"artifact": [1, 2]},
        {},
    ],
)
def test_una_peticion_malformada_se_rechaza_antes_de_mirar_nada(
    tmp_path: Path, cartera: str, cuerpo: dict[str, object]
) -> None:
    """La forma se valida primero: un cuerpo raro no puede llegar a resolver un archivo."""
    with pytest.raises(UiArtifactError):
        routes._materializar_externos([cuerpo], cartera, workdir=tmp_path)


def test_el_insumo_declarado_sin_archivo_no_se_acepta(tmp_path: Path, cartera: str) -> None:
    """Declarar la clave no basta: hay que decir de qué archivo sale."""
    with pytest.raises(UiArtifactError, match="súbelo antes de ejecutar"):
        routes._materializar_externos([{"artifact": _PD_CLAVE}], cartera, workdir=tmp_path)


def test_sin_insumo_declarado_el_camino_es_el_de_siempre(tmp_path: Path, cartera: str) -> None:
    """Aditivo puro (D-PUE-13): omitir el campo deja el comportamiento intacto."""
    assert routes._materializar_externos(None, cartera, workdir=tmp_path) == {}
    assert routes._materializar_externos([], cartera, workdir=tmp_path) == {}


# ─────────────────────────────── índice y alineación (D-PUE-4/6) ───────────────────────────────


def test_con_llave_declarada_el_frame_adopta_el_indice_de_la_cartera(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """El motor alinea por etiqueta, y la etiqueta que vale es la de la CARTERA (D-PUE-6-bis).

    ⚠️ Este test aseveraba antes que el índice quedaba en los valores de la llave, y ése era
    exactamente el defecto: indexar un solo lado no alinea, cruza. La llave se usa para emparejar
    y después el artefacto adopta el índice contra el que el motor va a alinear.
    """
    externos = routes._materializar_externos(
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"}],
        cartera,
        workdir=tmp_path,
    )
    frame = externos[("calibration", "calibrated_pd_frame")]
    assert list(frame.index) == list(range(6)), "el índice es el de la cartera"
    assert "id_operacion" not in frame.columns, "la llave pasa al índice, no se duplica"
    assert {"muestra", "malo", "probabilidad", "puntaje"} <= set(frame.columns)


def test_una_llave_que_el_archivo_no_tiene_se_rechaza_nombrando_las_que_hay(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """Un mensaje que sólo dijera «no existe» obliga a adivinar; se listan las columnas reales.

    ⚠️ El tipo se asevera **explícitamente**, y no con `pytest.raises(Exception)` como hasta el
    2026-08-02: es lo que decide el código HTTP, y con la excepción genérica el test daba verde
    mientras el endpoint respondía 404 sobre entrada corregible del usuario.
    """
    with pytest.raises(UiArtifactError, match="id_inventado") as exc:
        routes._materializar_externos(
            [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_inventado"}],
            cartera,
            workdir=tmp_path,
        )
    assert "probabilidad" in str(exc.value), "el error tiene que listar las columnas disponibles"


def test_un_mismo_archivo_alimenta_las_dos_claves_con_el_mismo_indice(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """D-PUE-4: es lo que hace inalcanzable el desalineamiento que el motor rechaza.

    `performance` levanta si la PD y el puntaje no comparten índice. Con una sola tabla eso se
    cumple por construcción, en vez de fallar a mitad de la corrida después de dos subidas.
    """
    externos = routes._materializar_externos(
        [
            {"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"},
            {"artifact": _SCORE_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"},
        ],
        cartera,
        workdir=tmp_path,
    )
    assert set(externos) == {("calibration", "calibrated_pd_frame"), ("scorecard", "score")}
    pd_frame = externos[("calibration", "calibrated_pd_frame")]
    score = externos[("scorecard", "score")]
    assert pd_frame.index.equals(score.index)
    assert pd_frame.index.is_unique


def test_sin_llave_y_con_otro_numero_de_filas_es_error_duro(tmp_path: Path, cartera: str) -> None:
    """D-PUE-6.1: el único desalineamiento detectable sin leer los datos no se deja pasar.

    Se comprueba contra el conteo del Parquet de la cartera, que no exige cargarla.
    """
    corto = _subir(tmp_path, pd.DataFrame({"probabilidad": [0.1, 0.2, 0.3]}), "corto.csv")
    with pytest.raises(UiArtifactError, match="3 filas y tu cartera tiene 6"):
        routes._materializar_externos(
            [{"artifact": _PD_CLAVE, "dataset_id": corto, "key_column": None}],
            cartera,
            workdir=tmp_path,
        )


def test_sin_llave_y_con_las_mismas_filas_alinea_por_orden(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """Es la decisión que Cami tomó con el riesgo a la vista: cómodo, y declarado en el informe."""
    externos = routes._materializar_externos(
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": None}],
        cartera,
        workdir=tmp_path,
    )
    frame = externos[("calibration", "calibrated_pd_frame")]
    assert list(frame.index) == list(range(6)), "índice posicional, como el de la cartera"
    assert "id_operacion" in frame.columns, "sin llave declarada, la columna sigue siendo una más"


def test_una_llave_mal_tipada_se_rechaza(tmp_path: Path, cartera: str, modelo: str) -> None:
    """`key_column` es el nombre de una columna o nada; un número no es ninguna de las dos."""
    with pytest.raises(UiArtifactError, match="nombre de una columna"):
        routes._materializar_externos(
            [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": 3}],
            cartera,
            workdir=tmp_path,
        )


# ───────────────── la llave tiene que estar en los DOS lados (D-PUE-6-bis, §8) ─────────────────
#
# 🔴 D-PUE-6 llamaba «el modo correcto» a declarar la llave, y no lo era: indexaba SÓLO el frame
# externo. La cartera conserva su `RangeIndex` salvo que el config declare `data.schema.index_col`,
# así que con llaves numéricas los dos índices coinciden por accidente y la probabilidad de cada
# operación cae en otra **sin que nada falle**. Con llaves de texto no coinciden y muere con jerga
# del motor. Ninguno de los dos comportamientos es aceptable, y el primero es peor que el modo
# posicional —que al menos avisa—, así que lo que se prueba aquí es la regla dura: por etiqueta
# sólo con la llave declarada en los dos lados.


def test_con_llaves_numericas_las_filas_ya_no_se_cruzan(tmp_path: Path) -> None:
    """El control negativo del defecto: es EXACTAMENTE el caso que cruzaba en silencio.

    Cartera `[1, 0]` y archivo `[0, 1]`: los dos índices se intersecan del todo con el `RangeIndex`,
    así que nada fallaba y la operación 1 recibía la probabilidad de la 0. Ahora el backend empareja
    de verdad, y lo que se asevera es el VALOR que le toca a cada fila, no que se levante un error:
    el arreglo bueno hace la corrida correcta, no imposible.
    """
    cartera = _subir(tmp_path, pd.DataFrame({"id_operacion": [1, 0], "saldo": [1.0, 2.0]}), "c.csv")
    modelo = _subir(
        tmp_path, pd.DataFrame({"id_operacion": [0, 1], "probabilidad": [0.1, 0.9]}), "m.csv"
    )

    externos = routes._materializar_externos(
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"}],
        cartera,
        workdir=tmp_path,
    )

    pd_frame = externos[("calibration", "calibrated_pd_frame")]
    assert list(pd_frame.index) == [0, 1], "el artefacto adopta el índice de la cartera"
    assert pd_frame["probabilidad"].iloc[0] == 0.9, (
        "la fila 0 de la cartera es la operación 1, y su probabilidad es 0,9 — antes recibía 0,1"
    )
    assert pd_frame["probabilidad"].iloc[1] == 0.1


def test_el_emparejamiento_funciona_con_una_cartera_csv_normal(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """🔴 El primer intento de corregir esto NO funcionaba con `.csv`, que es el caso normal.

    Exigía declarar `data.schema.index_col`, y ese campo comprueba el nombre de un índice **ya
    existente**: nunca hace `set_index` (`data/schema.py:36-39`). Una cartera CSV llega con
    `RangeIndex`, así que declararlo mataba la corrida en su primer paso. Este test es el que
    aquella versión no podía pasar.
    """
    externos = routes._materializar_externos(
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"}],
        cartera,
        workdir=tmp_path,
    )

    frame = externos[("calibration", "calibrated_pd_frame")]
    assert list(frame.index) == list(range(6)), "el índice es el de la cartera, no el de la llave"
    assert list(frame["probabilidad"]) == [0.1, 0.8, 0.2, 0.05, 0.7, 0.15]


def test_una_llave_que_la_cartera_no_tiene_se_rechaza_con_las_dos_salidas(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """Emparejar exige la columna en los dos archivos, y el mensaje ofrece cómo seguir.

    Cami lo pidió explícitamente: la regla es dura, pero quien prueba algo rápido tiene que poder
    continuar. Un mensaje que sólo dijera «falta la columna» dejaría al usuario sin saber que puede
    quitar la llave y emparejar por orden de filas.
    """
    sin_llave = _subir(tmp_path, pd.DataFrame({"probabilidad": [0.1] * 6}), "sin_llave.csv")

    with pytest.raises(UiArtifactError) as exc:
        routes._materializar_externos(
            [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "muestra"}],
            sin_llave,
            workdir=tmp_path,
        )

    mensaje = str(exc.value)
    assert "tu cartera no tiene esa columna" in mensaje
    assert "orden de filas" in mensaje, "el mensaje tiene que decir cómo seguir, no sólo qué falla"


def test_un_archivo_que_no_cubre_la_cartera_se_rechaza_nombrando_lo_que_falta(
    tmp_path: Path, cartera: str
) -> None:
    """La cobertura es lo que el preflight declara no poder comprobar (D-PUE-8): aquí sí se puede.

    Antes esto aparecía a mitad de la corrida con el mensaje del motor. Ahora se detiene en la
    puerta, antes de calcular nada, y nombra las operaciones que faltan.
    """
    incompleto = _subir(
        tmp_path,
        pd.DataFrame({"id_operacion": [f"OP-{i}" for i in range(4)], "probabilidad": [0.1] * 4}),
        "incompleto.csv",
    )

    with pytest.raises(UiArtifactError, match="OP-4") as exc:
        routes._materializar_externos(
            [{"artifact": _PD_CLAVE, "dataset_id": incompleto, "key_column": "id_operacion"}],
            cartera,
            workdir=tmp_path,
        )
    assert "2 de las operaciones" in str(exc.value)


def test_el_modo_posicional_normaliza_el_indice_del_archivo(tmp_path: Path, cartera: str) -> None:
    """⚠️ Un parquet subido con índice propio lo conservaba, y entonces cruzaba igual.

    La pantalla promete «la fila 1 con la fila 1». Con el conteo cuadrando y un índice invertido
    persistido en el parquet, el motor alineaba por esas etiquetas y el resultado salía cruzado sin
    un solo error. Alinear por orden significa por orden.
    """
    con_indice = pd.DataFrame(
        {"probabilidad": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}, index=pd.Index(range(5, -1, -1))
    )
    ruta = tmp_path / "con_indice.parquet"
    con_indice.to_parquet(ruta)
    subido = str(
        datasets_module.ingest_upload(ruta.read_bytes(), "con_indice.parquet", workdir=tmp_path)[
            "dataset_id"
        ]
    )

    externos = routes._materializar_externos(
        [{"artifact": _PD_CLAVE, "dataset_id": subido, "key_column": None}],
        cartera,
        workdir=tmp_path,
    )

    frame = externos[("calibration", "calibrated_pd_frame")]
    assert list(frame.index) == list(range(6)), "índice posicional, como el de la cartera"
    assert frame["probabilidad"].iloc[0] == 0.1, "la primera fila del archivo va con la primera"


def test_quitar_la_llave_es_la_salida_y_no_exige_un_campo_nuevo(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """«Continuar igual» es mandar `key_column: null`: el modo posicional que ya existía.

    No añade ni un campo al contrato, que es la razón de haberlo preferido a inventar un
    `align: "key" | "row_order"`.
    """
    externos = routes._materializar_externos(
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": None}],
        cartera,
        workdir=tmp_path,
    )
    assert list(externos[("calibration", "calibrated_pd_frame")].index) == list(range(6))


def test_el_preflight_avisa_de_la_llave_ausente_en_la_cartera_antes_de_correr(
    tmp_path: Path, modelo: str
) -> None:
    """§8.4: comparar dos listas de nombres de columna no lee un dato, así que respeta D-PRE-1.

    Y tiene que avisarlo aquí: es lo que convierte un 422 al apretar Ejecutar en un click.
    """
    sin_llave = _subir(tmp_path, pd.DataFrame({"probabilidad": [0.1] * 6}), "sin_llave.csv")

    avisos = routes._preflight_insumos(
        {},
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"}],
        sin_llave,
        workdir=tmp_path,
    )

    desajuste = [a for a in avisos if a["kind"] == "external_key_mismatch"]
    clases = [a["kind"] for a in avisos]
    assert len(desajuste) == 1, f"se esperaba un aviso de llave; llegaron {clases}"
    assert "id_operacion" in desajuste[0]["message"]


def test_el_preflight_no_avisa_cuando_la_llave_esta_en_los_dos(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """Control negativo: un aviso que se dispara de más se aprende a ignorar."""
    avisos = routes._preflight_insumos(
        {},
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"}],
        cartera,
        workdir=tmp_path,
    )
    assert not [a for a in avisos if a["kind"] == "external_key_mismatch"]


# ─────────────────────────────── el veredicto deja de mentir (D-PUE-7) ─────────────────────────


def _config_de_validar_un_modelo() -> dict[str, object]:
    """Config con `performance` activo y las secciones que lo alimentan APAGADAS."""
    cargar_configs_de_dominio()
    return NikodymConfig.model_validate({"performance": {}}).model_dump(mode="json", by_alias=True)


def test_sin_las_claves_el_veredicto_dice_que_no_se_puede() -> None:
    """Control negativo: es el comportamiento de hoy, y el que hacía inalcanzable el trabajo."""
    resultado = routes.validate_config(_config_de_validar_un_modelo())
    assert resultado["valid"] is True
    assert resultado["pipeline"]["executable"] is False
    assert resultado["pipeline"]["message"] is not None


def test_con_las_claves_declaradas_el_veredicto_dice_la_verdad() -> None:
    """🔴 D-PUE-7: sin esto, `/api/validate` mentiría justo en el caso que la puerta habilita."""
    resultado = routes.validate_config(
        _config_de_validar_un_modelo(),
        [{"artifact": _SCORE_CLAVE}, {"artifact": _PD_CLAVE}],
    )
    assert resultado["pipeline"]["executable"] is True
    assert resultado["pipeline"]["steps"] == ["performance"]
    assert resultado["pipeline"]["inert_artifacts"] == []


def test_el_veredicto_ignora_el_archivo_y_la_llave() -> None:
    """Comprobar no necesita el valor (D-ART-2), y por eso este endpoint no toca el disco.

    Es lo que le permite conservar su categoría de seguridad: se le puede pasar el cuerpo entero de
    `/api/run` y sigue sin materializar nada.
    """
    con_archivo = routes.validate_config(
        _config_de_validar_un_modelo(),
        [
            {"artifact": _SCORE_CLAVE, "dataset_id": "uploaded_inexistente", "key_column": "x"},
            {"artifact": _PD_CLAVE, "dataset_id": "uploaded_inexistente", "key_column": "x"},
        ],
    )
    solo_claves = routes.validate_config(
        _config_de_validar_un_modelo(),
        [{"artifact": _SCORE_CLAVE}, {"artifact": _PD_CLAVE}],
    )
    assert con_archivo == solo_claves


def test_una_clave_inerte_se_declara_en_el_veredicto() -> None:
    """🔴 Sin proyectarla, el aviso NO tiene por dónde salir a la red.

    La §6.1 de la enmienda de la puerta exige que llegue a las dos superficies —el trail y el
    veredicto— precisamente porque el trail no existe con `audit: null`, que es lo que traen los
    presets. Se calculaba y se tiraba.
    """
    resultado = routes.validate_config(
        _config_de_validar_un_modelo(),
        [
            {"artifact": _SCORE_CLAVE},
            {"artifact": _PD_CLAVE},
            {"artifact": ["model", "raw_pd_frame"]},
        ],
    )
    assert resultado["pipeline"]["executable"] is True
    assert resultado["pipeline"]["inert_artifacts"] == [["model", "raw_pd_frame"]]


def test_un_insumo_malformado_no_revienta_el_endpoint_de_validar() -> None:
    """Contrato «siempre 200»: sale como config inválido, nunca como un 500."""
    resultado = routes.validate_config(_config_de_validar_un_modelo(), "no soy una lista")
    assert resultado["valid"] is False
    assert resultado["pipeline"] is None
    assert resultado["errors"][0]["type"] == "config_error"


# ─────────────────────────── el preflight del insumo externo (D-PUE-8) ─────────────────────────


def _preflight(
    tmp_path: Path, cartera: str, externos: list[dict[str, object]]
) -> dict[str, object]:
    config = {
        "performance": {
            "score_column": "puntaje",
            "pd_column": "probabilidad",
            "partition_column": "muestra",
            "target_column": "malo",
        }
    }
    return routes.preflight_dataset(config, cartera, workdir=tmp_path, external_artifacts=externos)


def test_el_preflight_no_avisa_cuando_el_archivo_trae_lo_que_el_config_nombra(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    """Un aviso que se dispara de más se aprende a ignorar: el caso bueno tiene que salir limpio."""
    resultado = _preflight(
        tmp_path,
        cartera,
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "id_operacion"}],
    )
    assert resultado["external_mismatches"] == []


def test_el_preflight_avisa_de_una_columna_que_el_archivo_no_trae(
    tmp_path: Path, cartera: str
) -> None:
    """Y el aviso lleva el `path` del campo, que es por donde el click salta al formulario."""
    sin_pd = _subir(
        tmp_path,
        pd.DataFrame({"id_operacion": ["OP-0"], "otra_cosa": [1.0]}),
        "sin_pd.csv",
    )
    resultado = _preflight(
        tmp_path,
        cartera,
        [{"artifact": _PD_CLAVE, "dataset_id": sin_pd, "key_column": "id_operacion"}],
    )
    avisos = resultado["external_mismatches"]
    assert [a["kind"] for a in avisos] == ["external_missing_column"] * len(avisos)
    paths = {a["path"] for a in avisos}
    assert "performance.pd_column" in paths, "el aviso tiene que anclar al campo que lo nombra"
    assert any("probabilidad" in a["message"] for a in avisos)


def test_el_preflight_avisa_de_una_llave_que_el_archivo_no_tiene(
    tmp_path: Path, cartera: str, modelo: str
) -> None:
    resultado = _preflight(
        tmp_path,
        cartera,
        [{"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "no_existe"}],
    )
    kinds = [a["kind"] for a in resultado["external_mismatches"]]
    assert "external_missing_key" in kinds


def test_el_preflight_avisa_de_una_llave_repetida_usando_el_perfil(
    tmp_path: Path, cartera: str
) -> None:
    """No abre el archivo: el perfil de la ingesta ya midió los valores distintos (D-PERF-1)."""
    repetida = _subir(
        tmp_path,
        pd.DataFrame(
            {
                "id_operacion": ["OP-0", "OP-0", "OP-1"],
                "muestra": ["dev"] * 3,
                "malo": [0, 1, 0],
                "probabilidad": [0.1, 0.2, 0.3],
                "puntaje": [1.0, 2.0, 3.0],
            }
        ),
        "repetida.csv",
    )
    resultado = _preflight(
        tmp_path,
        cartera,
        [{"artifact": _PD_CLAVE, "dataset_id": repetida, "key_column": "id_operacion"}],
    )
    kinds = [a["kind"] for a in resultado["external_mismatches"]]
    assert "external_duplicated_key" in kinds


def test_el_preflight_avisa_del_conteo_en_el_modo_posicional(tmp_path: Path, cartera: str) -> None:
    """D-PUE-6.1 visto ANTES de correr, que es donde el usuario puede arreglarlo barato."""
    corto = _subir(
        tmp_path,
        pd.DataFrame(
            {
                "muestra": ["dev"] * 2,
                "malo": [0, 1],
                "probabilidad": [0.1, 0.2],
                "puntaje": [1.0, 2.0],
            }
        ),
        "corto.csv",
    )
    resultado = _preflight(
        tmp_path, cartera, [{"artifact": _PD_CLAVE, "dataset_id": corto, "key_column": None}]
    )
    avisos = [a for a in resultado["external_mismatches"] if a["kind"] == "external_row_count"]
    assert avisos and "2 filas" in avisos[0]["message"]


def test_compatible_no_cambia_de_significado(tmp_path: Path, cartera: str, modelo: str) -> None:
    """`compatible` sigue midiendo config contra dataset, y sólo eso.

    Los avisos del insumo externo viven en su propia lista: los de `mismatches` los produce el
    motor, cuyo vocabulario de `kind` es un `Literal` cerrado del núcleo, y un artefacto traído por
    la red es un concepto de esta capa. Mezclarlos obligaría al motor a conocer una puerta que sólo
    existe en HTTP.
    """
    sin_externos = routes.preflight_dataset({"performance": {}}, cartera, workdir=tmp_path)
    con_externos = routes.preflight_dataset(
        {"performance": {}},
        cartera,
        workdir=tmp_path,
        external_artifacts=[
            {"artifact": _PD_CLAVE, "dataset_id": modelo, "key_column": "no_existe"}
        ],
    )
    assert sin_externos["compatible"] == con_externos["compatible"]
    assert sin_externos["external_mismatches"] == []
    assert con_externos["external_mismatches"] != []


# ─────────────────────────── las guardas heredadas siguen puestas ───────────────────────────
#
# D-PUE-3 apoya toda la seguridad de la puerta en que el artefacto viaja por el `/api/upload` que ya
# existe y en que `/api/run` no cambia de categoría. Eso hay que **ejercitarlo con el campo nuevo en
# el cuerpo**, no darlo por heredado: la afirmación «no amplía la superficie» sólo vale si un cuerpo
# con `external_artifacts` se topa con las mismas cuatro guardas.


def _cliente(tmp_path: Path, **ajustes: object):  # type: ignore[no-untyped-def]
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from _ui_client import ui_client

    from nikodym.ui.settings import UiConfig

    return ui_client(UiConfig(workdir=str(tmp_path), **ajustes))  # type: ignore[arg-type]


def _cuerpo_con_insumo() -> dict[str, object]:
    return {
        "config": {"performance": {}},
        "dataset_id": "consumo_comportamiento",
        "external_artifacts": [{"artifact": _PD_CLAVE, "dataset_id": "uploaded_x"}],
    }


def test_correr_con_insumo_externo_sigue_exigiendo_token(tmp_path: Path) -> None:
    """La puerta no abre un camino sin credenciales: `/api/run` sigue en los mutadores."""
    cliente = _cliente(tmp_path)
    respuesta = cliente.post("/api/run", json=_cuerpo_con_insumo(), headers={"origin": "null"})
    assert respuesta.status_code == 403


def test_correr_con_insumo_externo_respeta_el_modo_sin_ejecucion(tmp_path: Path) -> None:
    """Con la ejecución en vivo apagada, traer un archivo tampoco ejecuta nada."""
    cliente = _cliente(tmp_path, allow_live_execution=False)
    respuesta = cliente.post("/api/run", json=_cuerpo_con_insumo())
    assert respuesta.status_code == 403
    assert "ejecución en vivo" in respuesta.json()["detail"]


def test_una_clave_no_admitida_da_422_y_no_404(tmp_path: Path) -> None:
    """El insumo externo es entrada del usuario, no un recurso ausente.

    Importa el código: un 404 le diría «eso no existe» cuando lo que pasa es que este trabajo no lo
    admite, y son dos cosas que se arreglan de forma distinta.
    """
    cliente = _cliente(tmp_path)
    cuerpo = {
        "config": {"performance": {}},
        "dataset_id": "consumo_comportamiento",
        "external_artifacts": [{"artifact": ["binning", "woe_frame"], "dataset_id": "x"}],
    }
    respuesta = cliente.post("/api/run", json=cuerpo)
    assert respuesta.status_code == 422
    assert "no admite" in respuesta.json()["detail"]


def test_validar_rechaza_las_mismas_claves_que_correr(tmp_path: Path) -> None:
    """🔴 Paridad validate↔run (§4.4): el mismo cuerpo no puede dar dos veredictos opuestos.

    Hasta el 2026-08-02 la allowlist se aplicaba **sólo** al materializar, así que `/api/validate`
    respondía `executable=true` sobre claves que `/api/run` rechazaba con 422. El botón Ejecutar
    prometía una corrida que el servidor no iba a aceptar, que es la peor forma de mentir de las
    dos superficies: la que sí mira el config.
    """
    cliente = _cliente(tmp_path)
    cuerpo = {
        "config": _config_de_validar_un_modelo(),
        "dataset_id": "consumo_comportamiento",
        # Las cuatro claves de `data`: ninguna la declara ningún trabajo del catálogo.
        "external_artifacts": [{"artifact": ["data", "frame"], "dataset_id": "uploaded_x"}],
    }

    validar = cliente.post("/api/validate", json=cuerpo)
    correr = cliente.post("/api/run", json=cuerpo)

    assert validar.status_code == 200, "el contrato «siempre 200» no cambia"
    assert validar.json()["valid"] is False, "una clave inadmisible es cuerpo inválido"
    assert correr.status_code == 422
    assert validar.json()["pipeline"] is None


def test_el_preflight_rechaza_una_clave_inadmisible_con_422_y_no_con_500(tmp_path: Path) -> None:
    """El tercer endpoint del contrato único responde como los otros dos.

    Sin su `except`, un cuerpo con una clave fuera de la allowlist —o simplemente malformado— hacía
    escapar la excepción entera y el servidor respondía **500** sobre entrada del usuario, que es
    exactamente lo que SDD-23 §8 prohíbe.
    """
    cliente = _cliente(tmp_path)
    respuesta = cliente.post(
        "/api/preflight",
        json={
            "config": _config_de_validar_un_modelo(),
            "dataset_id": "consumo_comportamiento",
            "external_artifacts": [{"artifact": ["data", "frame"], "dataset_id": "uploaded_x"}],
        },
    )
    assert respuesta.status_code == 422
    assert "no admite" in respuesta.json()["detail"]


def test_una_llave_inexistente_da_422_y_no_404(tmp_path: Path) -> None:
    """Una columna mal escrita es entrada corregible, no un recurso ausente.

    ⚠️ Y el orden de los `except` del handler **no** es lo que lo decide: `UiArtifactError` y
    `UiDatasetError` son hermanas bajo `UiError`, así que ninguna captura a la otra. Lo decide el
    `raise` de origen, y por eso este test vale: si `load_frame` volviera a levantar la de dataset,
    aquí saldría 404 aunque el handler no se toque.
    """
    cliente = _cliente(tmp_path)
    frame = pd.DataFrame({"id_operacion": ["OP-0"], "probabilidad": [0.1]})
    subido = _subir(tmp_path, frame, "modelo.csv")
    respuesta = cliente.post(
        "/api/run",
        json={
            "config": _config_de_validar_un_modelo(),
            "dataset_id": "consumo_comportamiento",
            "external_artifacts": [
                {"artifact": _PD_CLAVE, "dataset_id": subido, "key_column": "id_inventado"}
            ],
        },
    )
    assert respuesta.status_code == 422, respuesta.json()
    assert "id_inventado" in respuesta.json()["detail"]


def test_validar_con_insumo_externo_no_exige_credenciales_ni_escribe(tmp_path: Path) -> None:
    """D-PUE-7: consume sólo las claves, así que conserva su categoría y no toca el disco."""
    cliente = _cliente(tmp_path)
    respuesta = cliente.post(
        "/api/validate",
        json={
            "config": _config_de_validar_un_modelo(),
            "external_artifacts": [{"artifact": _SCORE_CLAVE}, {"artifact": _PD_CLAVE}],
        },
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["pipeline"]["executable"] is True
    assert not (tmp_path / "datasets").exists(), "comprobar no puede materializar nada"


def test_una_corrida_real_con_emparejamiento_llega_a_done(tmp_path: Path) -> None:
    """La corrida completa funciona con la cartera y el archivo en ORDEN DISTINTO.

    ⚠️ **Lo que este test NO prueba, y decirlo evita un falso verde:** que el emparejamiento sea
    correcto. Se comprobó reintroduciendo el defecto —indexar sólo el archivo externo— y este test
    **seguía pasando**. La razón está medida: `performance` no consume `('data', 'frame')`
    (`performance/step.py:62-65`), sólo los dos artefactos externos, que salen del mismo archivo y
    por tanto son consistentes **entre sí** aunque los dos estén cruzados respecto de la cartera.

    🔴 Y eso explica por qué la verificación en vivo de la sesión anterior no vio el defecto: el
    trabajo «validar un modelo existente» no cruza el artefacto con la cartera en ningún paso. Los
    pasos que sí lo hacen son `provisioning_internal` —que exige cobertura del índice de la
    cartera— y `stability` cuando toma el eje temporal de ahí.

    El gate del cruce son los unitarios de arriba, que aseveran **qué valor** recibe cada fila y
    que sí se ponen rojos con el defecto reintroducido. Éste cubre lo suyo: que la cadena entera
    —subida, allowlist, emparejamiento, motor, informe— termina bien.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from _ui_client import ui_client

    from nikodym.ui.settings import UiConfig

    n = 40
    ids = [f"OP-{i:02d}" for i in range(n)]
    malos = [1 if i % 2 else 0 for i in range(n)]
    cartera_id = _subir(tmp_path, pd.DataFrame({"id_operacion": ids, "saldo": [1.0] * n}), "c.csv")
    # El archivo del modelo va en ORDEN INVERSO, y su probabilidad separa perfecto a los malos.
    modelo_id = _subir(
        tmp_path,
        pd.DataFrame(
            {
                "id_operacion": list(reversed(ids)),
                "muestra": ["desarrollo"] * n,
                "malo": list(reversed(malos)),
                "probabilidad": [0.9 if m else 0.1 for m in reversed(malos)],
                "puntaje": [100.0 if m else 900.0 for m in reversed(malos)],
            }
        ),
        "m.csv",
    )

    config = _config_de_validar_un_modelo()
    config["performance"] = {
        "pd_column": "probabilidad",
        "partition_column": "muestra",
        "target_column": "malo",
        "score_column": "puntaje",
        "partitions": ["desarrollo"],
    }
    cliente = ui_client(UiConfig(workdir=str(tmp_path)))
    respuesta = cliente.post(
        "/api/run",
        json={
            "config": config,
            "dataset_id": cartera_id,
            "external_artifacts": [
                {"artifact": _PD_CLAVE, "dataset_id": modelo_id, "key_column": "id_operacion"},
                {"artifact": _SCORE_CLAVE, "dataset_id": modelo_id, "key_column": "id_operacion"},
            ],
        },
    )

    assert respuesta.status_code == 200, respuesta.json()
    assert respuesta.json()["status"] == "done", respuesta.json()
    resultados = cliente.get(f"/api/results/{respuesta.json()['run_id']}").json()
    discriminante = resultados["performance"]["discriminant"]
    assert discriminante, f"la corrida no publicó métricas: {list(resultados['performance'])}"
    aucs = [fila["auc"] for fila in discriminante if "auc" in fila]
    assert aucs and all(auc == pytest.approx(1.0) for auc in aucs), (
        f"AUC {aucs}: el archivo separa perfecto a los malos, así que la cadena entera tiene que "
        "conservar esa relación entre puntaje y resultado observado."
    )
