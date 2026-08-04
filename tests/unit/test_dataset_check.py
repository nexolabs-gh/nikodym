"""Gate del preflight config contra dataset (`_ENMIENDA-PREFLIGHT-DATASET.md`, D-PRE-1…D-PRE-9).

El caso que originó la capacidad se midió el 2026-07-28 contra `1.8.0` **instalado desde PyPI**,
con `nikodym-ui` levantado fuera del checkout: un CSV con nombres de columna propios exige seis
ediciones del preset F1 en seis lugares distintos, y el motor las revela **de a una** —cada corrida
fallida destapa la siguiente—. Aquí se fija que salgan todas juntas y sin correr nada.

Los dos tests que de verdad protegen no son los positivos, sino:

* el **control negativo**: el preset contra *su* dataset no puede acusar nada. Sin él, un preflight
  que devolviera desajustes siempre pasaría todos los casos positivos;
* el de **columnas derivadas**: `score_column`, `pd_column` y `partition_column` las produce el
  pipeline, así que exigirlas en el dataset crudo sería un falso positivo en la mayoría de los
  campos que nombran columnas (D-PRE-3).
"""

from __future__ import annotations

import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.dataset_check import (
    CLAVE_ROL,
    ROL_DERIVADA,
    ROL_ENTRADA,
    ROLES,
    check_dataset,
)
from nikodym.ui.presets import get_preset

#: Columnas del dataset del catálogo `consumo_comportamiento` **tal como las ve el motor**:
#: `loan_id` no aparece porque vive en el índice del parquet, no entre las columnas.
COLUMNAS_CATALOGO = (
    "cohorte",
    "ingreso_mensual",
    "deuda_ingreso",
    "utilizacion_linea",
    "mora_max_12m",
    "antiguedad_meses",
    "segmento",
    "bad_flag",
)

#: El mismo contenido con nombres de una cartera chilena real: el caso que enfrenta un tercero.
COLUMNAS_PROPIAS = (
    "rut_operacion",
    "periodo_camada",
    "renta_liquida",
    "carga_financiera",
    "uso_linea_rotativa",
    "peor_mora_12m",
    "meses_relacion",
    "tramo_cliente",
    "marca_incumplimiento",
)


@pytest.fixture
def config_f1() -> NikodymConfig:
    """El preset F1 tal como lo sirve la UI, reconstruido."""
    return NikodymConfig.model_validate(get_preset("f1-estandar-consumo")["config"])


def test_el_preset_contra_su_propio_dataset_no_acusa_nada(config_f1: NikodymConfig) -> None:
    """Control negativo: sin esto, un preflight que acusara siempre pasaría los demás tests."""
    veredicto = check_dataset(config_f1, COLUMNAS_CATALOGO)

    assert veredicto.compatible is True
    assert veredicto.mismatches == ()
    assert veredicto.uninspected == ()


def test_un_csv_con_nombres_propios_reporta_todos_los_desajustes_de_una_vez(
    config_f1: NikodymConfig,
) -> None:
    """D-PRE-2: total, no corto-circuito. Es la razón de existir de la capacidad."""
    veredicto = check_dataset(config_f1, COLUMNAS_PROPIAS)

    assert veredicto.compatible is False
    rutas = {m.path for m in veredicto.mismatches}

    # Las seis ediciones que la medición del 2026-07-28 destapó en seis corridas seriales,
    # todas presentes en una sola llamada. `data.schema.columns[N].name` cubre la segunda.
    assert any(r.startswith("data.schema.columns[") for r in rutas)
    assert "data.target.bad_rule.all_of[0].col" in rutas
    assert "data.partition.strategy.cohort_col" in rutas
    assert "binning.feature_columns" in rutas
    assert "binning.categorical_columns" in rutas


def test_las_columnas_derivadas_no_se_exigen_al_dataset(config_f1: NikodymConfig) -> None:
    """D-PRE-3: las produce el pipeline; exigirlas sería un falso positivo.

    Se comprueba contra el dataset de nombres propios —donde *nada* calza— porque es el escenario
    en que un preflight ingenuo acusaría absolutamente todos los campos que nombran columnas.
    """
    veredicto = check_dataset(config_f1, COLUMNAS_PROPIAS)
    rutas = {m.path for m in veredicto.mismatches}

    for derivada in (
        "performance.score_column",
        "performance.pd_column",
        "performance.partition_column",
        "stability.score_column",
        "stability.partition_column",
        "scorecard.score_column",
        "calibration.pd_calibrated_column",
        "data.target.target_col",
    ):
        assert derivada not in rutas, f"{derivada} es derivada y no debe exigirse al dataset"


def test_el_comodin_de_feature_columns_no_es_un_nombre_de_columna(
    config_f1: NikodymConfig,
) -> None:
    """`feature_columns='*'` significa «todas las disponibles», no una columna llamada `*`."""
    veredicto = check_dataset(config_f1, COLUMNAS_PROPIAS)

    assert not [m for m in veredicto.mismatches if m.declared == "*"]


def test_index_col_sobre_una_columna_corriente_tiene_diagnostico_propio(
    config_f1: NikodymConfig,
) -> None:
    """D-PRE-6: un CSV no puede transportar un índice, y el mensaje debe decir eso y la salida."""
    # El mismo dataset del catálogo servido como CSV: `loan_id` pasa a ser columna corriente.
    veredicto = check_dataset(config_f1, (*COLUMNAS_CATALOGO, "loan_id"))

    indices = [m for m in veredicto.mismatches if m.kind == "index_not_a_column"]
    assert len(indices) == 1
    assert indices[0].path == "data.schema.index_col"
    assert indices[0].declared == "loan_id"
    assert "no puede transportar un índice" in indices[0].message


def test_index_col_satisfecho_por_el_indice_no_se_reporta(config_f1: NikodymConfig) -> None:
    """El sentido simétrico del anterior: con el índice puesto, no hay nada que decir."""
    veredicto = check_dataset(config_f1, COLUMNAS_CATALOGO)

    assert not [m for m in veredicto.mismatches if m.kind == "index_not_a_column"]


def test_index_col_ausente_del_todo_se_reporta(config_f1: NikodymConfig) -> None:
    """El TERCER caso de ``index_col``: ni índice ni columna.

    D-PRE-6 diseñó el campo «en sus dos sentidos» y este se quedó sin rama, así que el preflight
    devolvía ``compatible=True`` —verde total, ``uninspected`` vacío— sobre un config que la
    corrida rechaza en el primer paso. Es justo el «todo bien» sobre lo no mirado que D-PRE-9
    declara la peor respuesta posible.
    """
    config = config_f1.model_copy(
        update={
            "data": config_f1.data.model_copy(
                update={
                    "schema_": config_f1.data.schema_.model_copy(update={"index_col": "NO_EXISTE"})
                }
            )
        }
    )

    veredicto = check_dataset(config, COLUMNAS_CATALOGO, index_columns=("loan_id",))

    faltantes = [m for m in veredicto.mismatches if m.kind == "missing_index"]
    assert len(faltantes) == 1
    assert faltantes[0].path == "data.schema.index_col"
    assert faltantes[0].declared == "NO_EXISTE"
    assert not veredicto.compatible


def test_declarar_los_indices_no_reintroduce_el_falso_positivo_del_catalogo(
    config_f1: NikodymConfig,
) -> None:
    """El preset contra su propio dataset sigue limpio **con** los índices declarados.

    Es el falso positivo más caro posible —el dataset del catálogo incompatible con su propio
    preset— y sólo apareció probando en vivo, así que se ancla en los dos sentidos.
    """
    veredicto = check_dataset(config_f1, COLUMNAS_CATALOGO, index_columns=("loan_id",))

    assert veredicto.compatible
    assert veredicto.mismatches == ()


def test_sin_declarar_los_indices_no_se_afirma_que_el_indice_falte(
    config_f1: NikodymConfig,
) -> None:
    """``index_columns=None`` significa «no se sabe», no «no hay» — y callar es lo correcto.

    El índice, por definición, no está entre las columnas: sin ese dato un ``index_col`` correcto
    es indistinguible de uno inexistente. Quien llame sin el parámetro debe seguir viendo el
    comportamiento anterior, no una acusación falsa sobre su propio dataset.
    """
    veredicto = check_dataset(config_f1, COLUMNAS_CATALOGO)

    assert not [m for m in veredicto.mismatches if m.kind == "missing_index"]
    assert veredicto.compatible


def test_una_seccion_opaca_que_coacciona_se_inspecciona_igual(
    config_f1: NikodymConfig,
) -> None:
    """El camino normal: la coacción resuelve la opacidad y la sección se mira de verdad.

    Se fuerza el estado con ``model_copy`` en vez del constructor: dentro de la suite las capas de
    dominio están siempre importadas, así que la raíz coacciona y el montaje natural nunca produce
    una sección opaca. Es el mismo motivo por el que el P0 del round-trip necesitó este truco.

    Sin la coacción de :func:`check_dataset` este caso devolvería ``compatible=True`` con cero
    desajustes —el recorrido no encuentra un solo `Field` que consultar dentro de un ``dict``—,
    que es el falso negativo que D-PRE-9 persigue.
    """
    opaco = config_f1.model_copy(
        update={"binning": {"type": "standard", "feature_columns": ("no_existe",)}}
    )

    # Precondición del test: la sección tiene que estar realmente opaca antes de comprobar.
    assert isinstance(opaco.binning, dict)

    veredicto = check_dataset(opaco, COLUMNAS_CATALOGO)

    assert veredicto.uninspected == ()  # coaccionó: sí se pudo mirar
    assert veredicto.compatible is False
    assert [m.declared for m in veredicto.mismatches] == ["no_existe"]


def test_una_seccion_que_no_coacciona_impide_declarar_compatible(
    config_f1: NikodymConfig,
) -> None:
    """D-PRE-9: no se afirma «todo bien» sobre lo que no se pudo mirar.

    Una sección opaca puede llevar un campo que el schema del dominio prohíbe —el *blob* lo acepta
    por no conocer su schema—, así que la coacción falla y se devuelve sin coaccionar (D-HASH-8).
    Ahí el preflight no sabe nada de esa sección, y decir «compatible» sería mentir a quien está a
    punto de lanzar una corrida.
    """
    invalido = config_f1.model_copy(update={"binning": {"type": "standard", "min_bin_size": -1}})

    assert isinstance(invalido.binning, dict)

    veredicto = check_dataset(invalido, COLUMNAS_CATALOGO)

    assert "binning" in veredicto.uninspected
    assert veredicto.compatible is False


def test_un_error_de_dominio_tampoco_vuelve_fallable_el_preflight(
    config_f1: NikodymConfig,
) -> None:
    """D-ANC-10: `check_dataset` no puede reventar porque la coacción falle por la OTRA vía.

    Hermano del de arriba, que elige como sección inválida un **campo desconocido** — o sea la única
    familia que ``_coaccionar_secciones_opacas`` atrapaba, porque ``extra_forbidden`` sí es
    ``ValidationError``. Aquí la sección es estructuralmente válida y la rechaza el **validador del
    dominio**, que levanta ``ConfigError``; pydantic no lo envuelve, porque ``NikodymError`` no
    hereda de ``ValueError``. El preflight debe seguir contestando: declarar la sección
    ``uninspected`` es lo honesto, propagar la excepción a quien sólo preguntó es romperle la
    pantalla.

    ``binning.solver='cp'`` se elige a propósito: es **un solo `Select`** del formulario, y su
    ``raise`` se escribió el 2026-08-04 cerrando otro defecto.
    """
    invalido = config_f1.model_copy(update={"binning": {"type": "standard", "solver": "cp"}})

    assert isinstance(invalido.binning, dict)

    veredicto = check_dataset(invalido, COLUMNAS_CATALOGO)  # no debe levantar

    assert "binning" in veredicto.uninspected
    assert veredicto.compatible is False


def test_la_seccion_sin_inspeccionar_dice_por_que(config_f1: NikodymConfig) -> None:
    """D-ANC-11: publicar QUÉ no se pudo mirar sin decir POR QUÉ no deja nada que corregir.

    Y el matiz que hace útil el dato: la coacción la hace ``model_validate`` del config **raíz**, o
    sea todo-o-nada, así que UNA sección inválida deja opacas también a las que estaban bien. El
    motivo se averigua coaccionando cada una **por separado**, de modo que sale nombrada la
    culpable y no el vecindario.

    Sin esta distinción el aviso de la pantalla atribuía las dos causas a la instalación —«esta
    instalación no sabe leerla»—, que es falso cuando el motor rechaza el config por una razón
    concreta que él mismo ya redactó.
    """
    invalido = config_f1.model_copy(
        update={
            # La culpable: un solo `Select` del formulario.
            "binning": {"type": "standard", "solver": "cp"},
            # La arrastrada: es válida, y sólo queda opaca porque la coacción es del raíz.
            "selection": {"type": "standard"},
        }
    )

    veredicto = check_dataset(invalido, COLUMNAS_CATALOGO)

    assert {"binning", "selection"} <= set(veredicto.uninspected), "las dos quedan opacas"

    motivos = dict(veredicto.uninspection_reasons)
    assert "binning" in motivos, "la culpable sale nombrada con su motivo"
    assert "selection" not in motivos, "la arrastrada NO se acusa: coacciona bien por su cuenta"
    assert "cp" in motivos["binning"] or "restricciones" in motivos["binning"], (
        f"el motivo es el del validador del dominio, no uno inventado: {motivos['binning']!r}"
    )


def test_el_vocabulario_de_roles_es_cerrado() -> None:
    """Un rol nuevo sin entrada en :data:`ROLES` degradaría en silencio a «no clasificado»."""
    assert set(ROLES) == {"input", "derived", "index", "not_a_column"}
    assert ROL_ENTRADA in ROLES
    assert ROL_DERIVADA in ROLES
    assert CLAVE_ROL == "column_role"
